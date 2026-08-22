# -*- coding: utf-8 -*-
"""Cron 状态持久化 — Stage 14.2 (Z11) 新增，对标 Cline cron/materializer.ts

将 spec 和 job 状态持久化到 agent_config/cron_store.json，
跨重启保留 spec 变更历史和 job 执行结果。

设计要点:
    - 文件写入用 tmp.replace 保证原子性
    - 每次 spec 变更或 job 执行后调用 save()
    - stdout/stderr 截断到 10000 字符（避免文件膨胀）
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# CronMaterializer — spec 和 job 状态持久化
# ============================================================================


class CronMaterializer:
    """将 spec 和 job 状态持久化 — Stage 14.2 新增

    对标 Cline cron/materializer.ts。

    持久化路径: agent_config/cron_store.json

    存储结构:
        {
            "version": 1,
            "specs": { "<name>": <spec_dict> },
            "last_run": { "<name>": <run_info_dict> }
        }
    """

    def __init__(self, store_path: Path | str | None = None) -> None:
        """初始化

        Args:
            store_path: 持久化文件路径，默认 agent_config/cron_store.json
        """
        if store_path is None:
            store_path = Path("agent_config") / "cron_store.json"
        self._store_path = Path(store_path)
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        """从文件加载状态"""
        if not self._store_path.exists():
            return {"version": 1, "specs": {}, "last_run": {}}
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("cron_store.json 内容非 dict，使用初始状态")
                return {"version": 1, "specs": {}, "last_run": {}}
            # 保证结构完整
            data.setdefault("version", 1)
            data.setdefault("specs", {})
            data.setdefault("last_run", {})
            return data
        except Exception as e:
            logger.warning("加载 cron_store.json 失败: %s", e)
            return {"version": 1, "specs": {}, "last_run": {}}

    def save(self) -> None:
        """保存状态到文件（原子写入）"""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_text = json.dumps(self._state, ensure_ascii=False, indent=2)

        # 原子写入: 先写 tmp 文件，再 replace
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._store_path.parent),
            prefix=".cron_store.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(yaml_text)
            Path(tmp_path).replace(self._store_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def record_spec(self, name: str, spec: dict[str, Any]) -> None:
        """记录 spec 到持久化存储"""
        self._state["specs"][name] = spec
        self.save()

    def remove_spec(self, name: str) -> None:
        """移除 spec 记录"""
        self._state["specs"].pop(name, None)
        self.save()

    def record_run(self, name: str, run_info: dict[str, Any]) -> None:
        """记录 job 执行结果"""
        self._state["last_run"][name] = run_info
        self.save()

    def get_last_run(self, name: str) -> dict[str, Any] | None:
        """获取上次执行结果"""
        return self._state["last_run"].get(name)

    def get_all_specs(self) -> dict[str, dict[str, Any]]:
        """获取所有已记录的 spec"""
        return dict(self._state.get("specs", {}))

    def get_all_last_runs(self) -> dict[str, dict[str, Any]]:
        """获取所有 job 的上次执行结果"""
        return dict(self._state.get("last_run", {}))
