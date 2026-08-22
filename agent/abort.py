# -*- coding: utf-8 -*-
"""中止控制器 — 对标 Cline AbortController

提供可向下透传的中止信号，让 stream/工具能在长 IO 操作中响应中止。
与 runtime._aborted 布尔互补:
    - _aborted: Phase 26 实现的布尔标志，仅在循环边界检查
    - AbortController: Phase 28.2 新增，基于 asyncio.Event，可在 stream/工具内部检查

核心概念:
    - signal: asyncio.Event，set() 后所有检查点立即抛出 AbortedError
    - abort(reason): 触发中止，记录原因
    - reset(): 清除中止状态，允许新运行
    - throw_if_aborted(): 检查并抛出异常（对标 Cline throwIfAborted）

设计说明:
    - asyncio.Event 是协程安全的，可在多个 await 点同时等待
    - signal.wait() 可用于 asyncio.wait() 组合等待，实现"立即中断"
    - 保留 runtime._aborted 布尔作为兼容（向后兼容 Phase 26 逻辑）
"""

from __future__ import annotations

import asyncio


class AbortedError(RuntimeError):
    """中止异常 — 对标 Cline AbortedError

    当 abort 被触发后，所有检查点抛出此异常。
    runtime 主循环捕获后转为 status="aborted"。
    """

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        super().__init__(reason or "aborted")


class AbortController:
    """中止控制器 — 对标 Cline AbortController

    用法:
        controller = AbortController()
        controller.abort("用户手动中止")
        # 在 stream/工具内部:
        controller.throw_if_aborted()  # 抛出 AbortedError
        # 或检查状态:
        if controller.is_set():
            ...

    透传方式:
        # 传给 model.stream
        async for event in model.stream(request, abort_signal=controller.signal):
            ...
        # 传给工具（通过 AgentToolContext.abort_signal）
        context.abort_signal = controller.signal
    """

    def __init__(self) -> None:
        self._signal: asyncio.Event = asyncio.Event()
        self._reason: str = ""

    @property
    def signal(self) -> asyncio.Event:
        """返回 asyncio.Event — 可用于 asyncio.wait() 组合等待"""
        return self._signal

    @property
    def reason(self) -> str:
        """返回中止原因"""
        return self._reason

    def abort(self, reason: str = "") -> None:
        """触发中止 — 对标 Cline AbortController.abort()

        Args:
            reason: 中止原因，记录到日志和异常消息
        """
        # 幂等检查 — 对标 Cline agent-runtime.ts L458-460
        # 已 aborted 时直接返回，避免覆盖首次中止原因
        if self._signal.is_set():
            return
        self._reason = reason
        self._signal.set()

    def is_set(self) -> bool:
        """是否已触发中止"""
        return self._signal.is_set()

    def throw_if_aborted(self) -> None:
        """检查并抛出异常 — 对标 Cline throwIfAborted

        若已中止则抛出 AbortedError，否则什么也不做。
        在 stream 循环、工具执行关键点调用。
        """
        if self._signal.is_set():
            raise AbortedError(self._reason)

    def reset(self) -> None:
        """重置中止状态 — 允许新运行"""
        self._signal.clear()
        self._reason = ""
