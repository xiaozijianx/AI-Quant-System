# -*- coding: utf-8 -*-
"""
集中式 Agent 系统级功能开关配置存储。

将系统级功能开关统一持久化到 agent_config/settings.yaml，
避免开关散落在各功能代码或仅依赖环境变量，便于前端统一管理。
后续新增系统级功能开关时，在此处扩展即可。

配置文件格式 (agent_config/settings.yaml):
    features:
        file_checkpoint: false   # 文件检查点开关（默认关闭）
"""
import os
import tempfile
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 默认配置文件路径（相对 CWD，app.py 已 os.chdir 到项目根）
_DEFAULT_SETTINGS_PATH = Path("agent_config") / "settings.yaml"


class SettingsStore:
    """
    加载/保存 agent_config/settings.yaml，提供功能开关的读取/写入操作。
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._config_path = Path(config_path) if config_path else _DEFAULT_SETTINGS_PATH
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """从 yaml 加载配置"""
        try:
            if self._config_path.exists():
                raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            else:
                self._data = {}
        except Exception as e:
            logger.warning("加载 settings.yaml 失败: %s", e)
            self._data = {}

    def save(self) -> None:
        """保存配置到 yaml（原子写入，避免写一半损坏）"""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_text = yaml.safe_dump(self._data, allow_unicode=True, sort_keys=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._config_path.parent),
            prefix=".settings.yaml.",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(yaml_text)
            Path(tmp_path).replace(self._config_path)
        except Exception:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def get_feature(self, name: str) -> bool:
        """读取功能开关状态（默认关闭）"""
        features = self._data.get("features")
        if isinstance(features, dict):
            return bool(features.get(name, False))
        return False

    def set_feature(self, name: str, enabled: bool) -> bool:
        """设置功能开关状态并持久化，返回最终状态"""
        features = self._data.get("features")
        if not isinstance(features, dict):
            features = {}
            self._data["features"] = features
        features[name] = bool(enabled)
        self.save()
        return self.get_feature(name)


# 模块级单例
_store: SettingsStore | None = None


def get_settings_store() -> SettingsStore:
    """获取 SettingsStore 单例"""
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store


def is_feature_enabled(name: str) -> bool:
    """读取功能开关状态（供启动逻辑调用，异常时返回 False 兜底）"""
    try:
        return get_settings_store().get_feature(name)
    except Exception:
        return False