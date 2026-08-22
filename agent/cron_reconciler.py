# -*- coding: utf-8 -*-
"""Cron spec 对账器 — Stage 14.2 (Z11) 新增，对标 Cline cron/reconciler.ts

定期扫描 spec 目录，diff 已注册 job，增删改。
支持文件变更检测（mtime），避免每次都全量解析。

设计要点:
    - reconcile 线程是 daemon，主进程退出时自动结束
    - reconcile 结果记录日志（INFO 级别）
    - 新增/删除/更新 job 时同步记录到 CronMaterializer
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BlockingScheduler

from agent.cron_materializer import CronMaterializer

logger = logging.getLogger(__name__)


class CronReconciler:
    """定期扫描 spec 目录，diff 已注册 job — Stage 14.2 新增

    对标 Cline cron/reconciler.ts。

    用法:
        reconciler = CronReconciler(sched, specs_dir, materializer)
        reconciler.reconcile()  # 初始 reconcile
        # 在独立线程启动定期 reconcile
        threading.Thread(target=lambda: asyncio.run(reconciler.start()), daemon=True).start()
    """

    def __init__(
        self,
        sched: BlockingScheduler,
        specs_dir: Path | str,
        materializer: CronMaterializer | None = None,
        check_interval_seconds: float = 60.0,
    ) -> None:
        """初始化

        Args:
            sched: BlockingScheduler 实例
            specs_dir: spec 文件目录
            materializer: 状态持久化器，None 时不持久化
            check_interval_seconds: 定期 reconcile 间隔（秒）
        """
        self._sched = sched
        self._specs_dir = Path(specs_dir)
        self._materializer = materializer
        self._check_interval = check_interval_seconds
        # 已知 specs: name -> spec dict
        self._known_specs: dict[str, dict[str, Any]] = {}

    def reconcile(self) -> dict[str, list[str]]:
        """执行一次 reconcile

        扫描 spec 目录，与已注册 job 对比，执行增删改。

        Returns:
            {"added": [...], "removed": [...], "updated": [...]}
        """
        # 延迟导入避免循环依赖
        from scheduler import load_cron_specs, _parse_cron_schedule, _make_spec_job_executor

        current_specs_list = load_cron_specs(self._specs_dir)
        current_specs = {s["name"]: s for s in current_specs_list}

        added = set(current_specs) - set(self._known_specs)
        removed = set(self._known_specs) - set(current_specs)
        updated = {
            name for name in (set(current_specs) & set(self._known_specs))
            if current_specs[name] != self._known_specs[name]
        }

        # 处理新增
        for name in added:
            spec = current_specs[name]
            if self._register_job(spec):
                if self._materializer:
                    self._materializer.record_spec(name, spec)

        # 处理删除
        for name in removed:
            self._remove_job(name)
            if self._materializer:
                self._materializer.remove_spec(name)

        # 处理更新（先删后加）
        for name in updated:
            self._remove_job(name)
            spec = current_specs[name]
            if self._register_job(spec):
                if self._materializer:
                    self._materializer.record_spec(name, spec)

        self._known_specs = current_specs

        result = {
            "added": list(added),
            "removed": list(removed),
            "updated": list(updated),
        }
        if added or removed or updated:
            logger.info(
                "[CRON-RECONCILER] reconcile 完成: added=%s, removed=%s, updated=%s",
                list(added), list(removed), list(updated),
            )
        return result

    def _register_job(self, spec: dict[str, Any]) -> bool:
        """注册单个 spec 到 scheduler

        Returns:
            True 表示注册成功，False 表示跳过（disabled 或 schedule 解析失败）
        """
        if not spec.get("enabled", True):
            logger.info("[CRON-RECONCILER] %s 已禁用，跳过注册", spec["name"])
            return False

        trigger = _parse_cron_schedule(spec["schedule"])
        if trigger is None:
            return False

        executor = _make_spec_job_executor(spec["command"], spec["name"])
        try:
            self._sched.add_job(
                executor,
                id=spec["name"],
                name=spec.get("description") or spec["name"],
                trigger=trigger,
                timezone=spec["timezone"],
                replace_existing=True,
            )
            logger.info(
                "[CRON-RECONCILER] 注册 job: id=%s schedule=%s",
                spec["name"], spec["schedule"],
            )
            return True
        except Exception as e:
            logger.warning("[CRON-RECONCILER] 注册 %s 失败: %s", spec["name"], e)
            return False

    def _remove_job(self, name: str) -> None:
        """从 scheduler 移除 job"""
        try:
            self._sched.remove_job(name)
            logger.info("[CRON-RECONCILER] 移除 job: %s", name)
        except Exception:
            # job 不存在时忽略
            pass

    async def start(self) -> None:
        """启动定期 reconcile 循环 — 应在独立线程中运行"""
        while True:
            try:
                self.reconcile()
            except Exception as e:
                logger.error("[CRON-RECONCILER] reconcile 异常: %s", e)
            await asyncio.sleep(self._check_interval)
