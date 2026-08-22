# -*- coding: utf-8 -*-
"""Hook 进程注册表 — Stage 12.4 (P12) 新增，对标 Cline HookProcessRegistry

管理运行中的 hook 子进程，提供：
    1. 注册：hook 启动后注册到 registry
    2. 注销：hook 完成后从 registry 移除
    3. 查询：list_running 列出所有运行中的 hook 进程
    4. 终止：kill_all 在 abort 时统一 kill 所有运行中 hook 进程

设计要点:
    - 用 asyncio.Lock 保证并发安全（多个 hook 可能并行执行）
    - hook_id 由调用方生成（如 "session_id/script_name"），保证唯一
    - 进程对象用 asyncio.subprocess.Process，与 runner.py 一致
    - kill_all 与 Stage 9.2 subprocess kill on abort 联动：
      abort signal 触发时，runtime 调用 kill_all 终止所有 hook 进程

对标 Cline:
    - third_party/cline/apps/vscode/src/core/hooks/hook-process-registry.ts
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class HookProcessRegistry:
    """hook 子进程注册表 — Stage 12.4 (P12) 新增

    管理运行中的 hook 子进程，支持 abort 时统一 kill。

    用法:
        registry = HookProcessRegistry()
        await registry.register("hook_id_1", process)
        ...
        await registry.unregister("hook_id_1")
        ...
        # abort 时
        await registry.kill_all()

    P1-7 增强: 创建时可传入 abort_signal（asyncio.Event），hook 执行前
    通过 is_aborted() 检查信号，abort 触发时 kill_all_sync() 立即终止
    所有运行中的 hook 进程，避免 hook 继续执行到超时。
    """

    def __init__(self, abort_signal: asyncio.Event | None = None) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._lock = asyncio.Lock()
        # P1-7: 保存 abort_signal，用于 hook 执行前检查
        self._abort_signal: asyncio.Event | None = abort_signal

    def set_abort_signal(self, abort_signal: asyncio.Event | None) -> None:
        """设置 abort_signal — P1-7 新增

        允许在 registry 创建后绑定 abort_signal（如 runtime 在 __init__ 中
        创建 AbortController 后绑定到全局 registry）。

        Args:
            abort_signal: asyncio.Event，set() 后表示已中止
        """
        self._abort_signal = abort_signal

    def is_aborted(self) -> bool:
        """检查 abort_signal 是否已触发 — P1-7 新增

        用于 hook 执行前检查，避免 abort 后仍启动新的 hook 进程。

        Returns:
            True 表示已中止，False 表示未中止或未绑定 abort_signal
        """
        return self._abort_signal is not None and self._abort_signal.is_set()

    async def register(
        self,
        hook_id: str,
        proc: asyncio.subprocess.Process,
    ) -> None:
        """注册 hook 子进程

        Args:
            hook_id: hook 唯一标识（如 "session_id/script_name"）
            proc: asyncio 子进程对象
        """
        async with self._lock:
            self._processes[hook_id] = proc

    async def unregister(self, hook_id: str) -> None:
        """注销 hook 子进程（完成后调用）

        Args:
            hook_id: hook 唯一标识
        """
        async with self._lock:
            self._processes.pop(hook_id, None)

    async def list_running(self) -> list[str]:
        """列出所有运行中的 hook ID

        Returns:
            运行中的 hook ID 列表（returncode is None 表示仍在运行）
        """
        async with self._lock:
            return [
                hid for hid, p in self._processes.items()
                if p.returncode is None
            ]

    async def kill_all(self) -> int:
        """kill 所有运行中 hook 进程 — abort 时调用

        统一终止所有注册的 hook 子进程，避免 abort 后仍有 hook 在后台运行。
        与 Stage 9.2 subprocess kill on abort 联动。

        Returns:
            被 kill 的进程数量
        """
        async with self._lock:
            killed = 0
            for hook_id, proc in self._processes.items():
                if proc.returncode is None:
                    try:
                        proc.kill()
                        killed += 1
                    except ProcessLookupError:
                        # 进程已退出，忽略
                        pass
                    except Exception as e:
                        logger.warning(
                            "kill hook 进程失败 (%s): %s",
                            hook_id, e,
                        )
            # 清空注册表
            self._processes.clear()
            if killed > 0:
                logger.info(
                    "HookProcessRegistry.kill_all: 已终止 %d 个 hook 进程",
                    killed,
                )
            return killed

    async def get_count(self) -> int:
        """获取注册表中的进程总数（含已完成但未注销的）

        Returns:
            进程总数
        """
        async with self._lock:
            return len(self._processes)

    def kill_all_sync(self) -> int:
        """同步 kill 所有运行中 hook 进程 — P1-7 新增

        与 kill_all() 功能相同，但不获取 asyncio.Lock，适用于在
        runtime.abort() 等同步上下文中立即终止 hook 进程。
        abort 场景下跳过锁是可接受的：进程正在退出，register/unregister
        的竞态不会造成数据损坏。

        Returns:
            被 kill 的进程数量
        """
        killed = 0
        for hook_id, proc in list(self._processes.items()):
            if proc.returncode is None:
                try:
                    proc.kill()
                    killed += 1
                except ProcessLookupError:
                    # 进程已退出，忽略
                    pass
                except Exception as e:
                    logger.warning(
                        "kill_all_sync: kill hook 进程失败 (%s): %s",
                        hook_id, e,
                    )
        # 清空注册表
        self._processes.clear()
        if killed > 0:
            logger.info(
                "HookProcessRegistry.kill_all_sync: 已终止 %d 个 hook 进程",
                killed,
            )
        return killed


# ============================================================================
# 全局 registry 实例 — 供 runtime abort 时统一 kill
# ============================================================================

_global_registry: HookProcessRegistry | None = None


def get_global_registry(
    abort_signal: asyncio.Event | None = None,
) -> HookProcessRegistry:
    """获取全局 HookProcessRegistry 实例 — Stage 12.4 新增

    全局单例，供 runtime 在 abort 时调用 kill_all 终止所有 hook 进程。

    P1-7 增强: 首次创建时可传入 abort_signal，后续调用若传入新的
    abort_signal 会通过 set_abort_signal 更新绑定。

    Args:
        abort_signal: 可选的 asyncio.Event，绑定到 registry 用于 hook
                      执行前检查（首次创建时传入，或更新现有 registry 的绑定）
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = HookProcessRegistry(abort_signal=abort_signal)
    elif abort_signal is not None:
        # P1-7: 更新现有 registry 的 abort_signal 绑定
        _global_registry.set_abort_signal(abort_signal)
    return _global_registry


__all__ = [
    "HookProcessRegistry",
    "get_global_registry",
]
