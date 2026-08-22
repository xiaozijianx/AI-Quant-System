# -*- coding: utf-8 -*-
"""Cron job 执行器 — Stage 14.2 (Z11) 新增，对标 Cline cron/runner.ts

job 执行抽象，支持同步 subprocess、超时控制、错误处理。
执行结果记录到 CronMaterializer。

设计要点:
    - 超时/错误不抛出（仅记录，避免阻塞 scheduler）
    - stdout/stderr 截断到 10000 字符（避免文件膨胀）
    - 执行结果持久化到 materializer
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from agent.cron_materializer import CronMaterializer

logger = logging.getLogger(__name__)


# stdout/stderr 截断上限（字符数）
_MAX_OUTPUT_LENGTH = 10000

# 默认超时（秒）
_DEFAULT_TIMEOUT = 600.0


class CronRunner:
    """job 执行抽象 — Stage 14.2 新增

    对标 Cline cron/runner.ts。

    用法:
        runner = CronRunner(materializer)
        await runner.run(spec)
    """

    def __init__(
        self,
        materializer: CronMaterializer,
        default_timeout: float = _DEFAULT_TIMEOUT,
        cwd: str | None = None,
    ) -> None:
        """初始化

        Args:
            materializer: 状态持久化器
            default_timeout: 默认超时（秒），spec 未指定 timeout 时使用
            cwd: 命令执行目录，None 时使用当前工作目录
        """
        self._materializer = materializer
        self._default_timeout = default_timeout
        self._cwd = cwd

    async def run(self, spec: dict[str, Any]) -> dict[str, Any]:
        """执行 spec.command

        执行流程:
            1. 记录 started_at 状态到 materializer
            2. 通过 asyncio.create_subprocess_shell 执行 command
            3. 等待完成（带超时）
            4. 记录 completed_at / exit_code / stdout / stderr 到 materializer

        Args:
            spec: cron spec 字典，含 command / name / timeout 字段

        Returns:
            执行结果 run_info dict
        """
        name = spec.get("name", "unknown")
        command = spec.get("command", "")
        timeout = spec.get("timeout", self._default_timeout)

        start_time = datetime.now(timezone.utc)
        run_info: dict[str, Any] = {
            "started_at": start_time.isoformat(),
            "status": "running",
            "command": command,
        }
        self._materializer.record_run(name, run_info)

        if not command:
            run_info.update({
                "status": "failed",
                "error": "command 为空",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            self._materializer.record_run(name, run_info)
            return run_info

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # 超时: 终止进程
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    pass
                run_info.update({
                    "status": "timeout",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "timeout_seconds": timeout,
                })
                self._materializer.record_run(name, run_info)
                logger.warning("[CRON-RUNNER] %s 超时（%ss）", name, timeout)
                return run_info

            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")

            # 截断过长输出
            stdout_text, stdout_truncated = _truncate_output(stdout_text)
            stderr_text, stderr_truncated = _truncate_output(stderr_text)

            run_info.update({
                "status": "completed" if proc.returncode == 0 else "failed",
                "exit_code": proc.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })

            logger.info(
                "[CRON-RUNNER] %s 完成 (exit_code=%s)",
                name, proc.returncode,
            )

        except Exception as e:
            run_info.update({
                "status": "error",
                "error": str(e),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.error("[CRON-RUNNER] %s 执行异常: %s", name, e)

        self._materializer.record_run(name, run_info)
        return run_info


def _truncate_output(text: str) -> tuple[str, bool]:
    """截断过长输出，返回 (截断后文本, 是否截断)"""
    if len(text) <= _MAX_OUTPUT_LENGTH:
        return text, False
    half = _MAX_OUTPUT_LENGTH // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - _MAX_OUTPUT_LENGTH
    truncated_text = head + f"\n\n[... {omitted} characters omitted ...]\n\n" + tail
    return truncated_text, True
