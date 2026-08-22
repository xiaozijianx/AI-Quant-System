# -*- coding: utf-8 -*-
"""Provider 配置持久化 — Stage 13.2 (R10) 新增，对标 Cline provider-settings.ts

将用户运行时可修改的 Provider 配置（model_id / base_url / temperature / max_tokens）
持久化到 agent_config/providers.yaml，跨会话保留。

设计要点:
    1. api_key 不允许通过 API 修改（仅环境变量配置，符合用户规则）
    2. yaml 文件存储 per-provider 的运行时覆盖配置
    3. 配置变更不重建已运行的 Provider 实例（避免影响进行中的 run）
    4. 文件写入用 tmp.replace 保证原子性

配置文件格式 (agent_config/providers.yaml):
    qwen:
      model_id: qwen-plus
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
      temperature: 0.1
      max_tokens: 8192
    deepseek:
      model_id: deepseek-chat
      temperature: 0.3
      max_tokens: 4096
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ============================================================================
# ProviderConfig — 运行时可修改的 Provider 配置
# ============================================================================


@dataclass
class ProviderConfig:
    """单个 Provider 的运行时配置 — Stage 13.2 (R10) 新增

    字段说明:
        alias: 配置别名，作为 providers.yaml 的 key 和前端列表唯一标识
        provider_id: 实际 Provider 类型（qwen / deepseek / openai 等），决定 factory 创建哪个模型实现
        model_id / base_url / api_key / temperature / max_tokens: 运行时可修改参数
    """
    alias: str
    provider_id: str
    model_id: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 8192

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（用于 yaml 写入和 API 返回）"""
        return {
            "alias": self.alias,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderConfig":
        """从 dict 反序列化

        兼容旧版 providers.yaml：旧版没有 alias 和 provider_id 字段，yaml key 即为 provider_id。
        """
        alias = str(data.get("alias", ""))
        provider_id = str(data.get("provider_id", ""))
        if not provider_id:
            # 旧版兼容：yaml key 作为 provider_id，alias 也回退到该 key
            provider_id = alias
        if not alias:
            alias = provider_id
        return cls(
            alias=alias,
            provider_id=provider_id,
            model_id=str(data.get("model_id", "")),
            base_url=str(data.get("base_url", "")),
            api_key=str(data.get("api_key", "")),
            temperature=float(data.get("temperature", 0.1)),
            max_tokens=int(data.get("max_tokens", 8192)),
        )


# ============================================================================
# 可修改字段白名单 — api_key 可通过 API 修改并持久化到 providers.yaml
# ============================================================================

# 允许通过 PUT/POST API 修改的字段
# alias 是 yaml key，不允许通过 API 修改；provider_id 表示实际 Provider 类型，新建时必须指定。
UPDATABLE_FIELDS: set[str] = {"provider_id", "model_id", "base_url", "api_key", "temperature", "max_tokens"}


# ============================================================================
# ProviderSettingsStore — 持久化存储
# ============================================================================


class ProviderSettingsStore:
    """Provider 配置持久化存储 — Stage 13.2 (R10) 新增

    加载/保存 agent_config/providers.yaml，提供 get/update/list 操作。

    线程安全: 使用文件锁（tmp.replace 原子写入）保证并发安全。
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        """初始化

        Args:
            config_path: yaml 配置文件路径，默认 agent_config/providers.yaml
        """
        if config_path is None:
            config_path = Path("agent_config") / "providers.yaml"
        self._config_path = Path(config_path)
        self._configs: dict[str, ProviderConfig] = {}
        self._load()

    def _load(self) -> None:
        """从 yaml 加载配置"""
        if not self._config_path.exists():
            return
        try:
            data = yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("providers.yaml 内容非 dict，已忽略")
                return
            for alias, cfg_data in data.items():
                if not isinstance(cfg_data, dict):
                    continue
                cfg_data_with_alias = dict(cfg_data)
                cfg_data_with_alias["alias"] = alias
                self._configs[alias] = ProviderConfig.from_dict(cfg_data_with_alias)
        except Exception as e:
            logger.warning("加载 providers.yaml 失败: %s", e)

    def _save(self) -> None:
        """保存配置到 yaml（原子写入）"""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        # 以 alias 为 key，value 保留完整字段（含 alias / provider_id）便于阅读
        data = {cfg.alias: cfg.to_dict() for cfg in self._configs.values()}
        yaml_text = yaml.safe_dump(data, allow_unicode=True, sort_keys=True)

        # 原子写入: 先写 tmp 文件，再 replace
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._config_path.parent),
            prefix=".providers.yaml.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(yaml_text)
            Path(tmp_path).replace(self._config_path)
        except Exception:
            # 写入失败时清理 tmp 文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def list_providers(self) -> list[ProviderConfig]:
        """列出所有已配置的 provider"""
        return list(self._configs.values())

    def get_provider(self, alias: str) -> ProviderConfig | None:
        """获取单个 provider 配置（按 alias）"""
        return self._configs.get(alias)

    def update_provider(
        self, alias: str, updates: dict[str, Any],
    ) -> ProviderConfig:
        """更新 provider 配置并持久化

        Args:
            alias: 配置别名（providers.yaml 的 key）
            updates: 更新字段（仅 UPDATABLE_FIELDS 中的字段有效）

        Returns:
            更新后的 ProviderConfig

        Raises:
            ValueError: updates 含非法字段，或新建时未指定 provider_id
        """
        # 校验非法字段
        invalid_fields = set(updates.keys()) - UPDATABLE_FIELDS
        if invalid_fields:
            raise ValueError(
                f"非法字段: {invalid_fields}，允许字段: {UPDATABLE_FIELDS}"
            )

        # 获取或创建配置
        config = self._configs.get(alias)
        if config is None:
            provider_id = updates.get("provider_id", "")
            if not provider_id:
                raise ValueError(
                    f"新建 Provider 配置 {alias} 时必须指定 provider_id"
                )
            config = ProviderConfig(alias=alias, provider_id=provider_id)
            self._configs[alias] = config

        # 应用更新
        for key, value in updates.items():
            if hasattr(config, key):
                setattr(config, key, value)

        # 持久化
        self._save()
        logger.info(
            "Provider 配置已更新并持久化: alias=%s, provider_id=%s, updates=%s",
            alias, config.provider_id, list(updates.keys()),
        )
        return config

    def delete_provider(self, alias: str) -> bool:
        """删除 provider 配置

        Returns:
            True 表示已删除，False 表示不存在
        """
        if alias not in self._configs:
            return False
        del self._configs[alias]
        self._save()
        return True


# ============================================================================
# 全局单例
# ============================================================================

_global_store: ProviderSettingsStore | None = None


def get_provider_settings_store() -> ProviderSettingsStore:
    """获取全局 ProviderSettingsStore 单例"""
    global _global_store
    if _global_store is None:
        _global_store = ProviderSettingsStore()
    return _global_store


def mask_api_key(api_key: str) -> str:
    """脱敏 api_key — 仅显示前 4 位 + ***"""
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return api_key[:2] + "***"
    return api_key[:4] + "***"
