# -*- coding: utf-8 -*-
"""用户输入排队服务 — 对标 Cline PendingPromptService + PendingPromptsController

Cline 源码位置：
    - sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts
    - sdk/packages/agents/src/agent-runtime.ts L841-852（consumePendingUserMessage）
    - sdk/packages/agents/src/agent-runtime.ts L1252-1267（consumePendingUserMessage 实现）

核心机制：
    1. 用户在 agent 运行中发送的新输入排队（pendingPrompts 队列）
    2. 两种 delivery 模式：
       - queue: 排队，当前 run 结束后由 drain 自动消费下一条
       - steer: 实时插入到当前 iteration 的 model request（iteration > 1 时）
    3. steer 优先级高于 queue（steer 放队首，queue 放队尾）
    4. 同 prompt 已存在时合并更新（避免重复入队）
    5. drain 失败时 requeueFront 重新入队，避免丢失
    6. session.aborting 时禁止操作
    7. drainingPendingPrompts 标志防止 drain 重入

与 Cline 的等价映射：
    PendingPromptEntry         ↔ Python dataclass
    PendingPromptQueueState    ↔ PendingPromptQueueState dataclass
    PendingPromptService       ↔ PendingPromptService 类（纯逻辑层）
    PendingPromptsController   ↔ PendingPromptsController 类（依赖注入 + 调度）
    consumePendingUserMessage  ↔ AgentRuntimeConfig.consume_pending_user_message 回调
    drain                      ↔ PendingPromptsController.drain 协程
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ============================================================================
# 类型定义 — 对标 Cline PendingPromptEntry / PendingPromptQueueState
# ============================================================================


def _generate_prompt_id() -> str:
    """生成 pending prompt ID — 对标 Cline `pending_${Date.now()}_${nanoid(5)}`"""
    return f"pending_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5]}"


@dataclass
class PendingPromptEntry:
    """待处理用户输入条目 — 对标 Cline PendingPromptEntry

    Attributes:
        id: 唯一 ID（pending_<timestamp>_<rand>）
        prompt: 用户输入文本
        mode: agent 模式（act / plan），None 表示继承当前模式
        delivery: 投递模式
            - "queue": 排队，run 结束后消费
            - "steer": 实时插入当前 iteration
        user_images: 用户附带的图片路径列表
        user_files: 用户附带的文件路径列表
    """

    id: str
    prompt: str
    mode: str | None = None
    delivery: str = "queue"
    user_images: list[str] = field(default_factory=list)
    user_files: list[str] = field(default_factory=list)


@dataclass
class PendingPromptQueueState:
    """待处理输入队列状态 — 对标 Cline PendingPromptQueueState

    Attributes:
        pending_prompts: 待处理输入列表（steer 在前，queue 在后）
    """

    pending_prompts: list[PendingPromptEntry] = field(default_factory=list)


def snapshot_prompt(entry: PendingPromptEntry) -> dict[str, Any]:
    """生成 prompt 快照（深拷贝）— 对标 Cline snapshotPrompt

    返回字典形式，避免外部修改影响队列内部状态。
    """
    return {
        "id": entry.id,
        "prompt": entry.prompt,
        "delivery": entry.delivery,
        "mode": entry.mode,
        "attachment_count": len(entry.user_images) + len(entry.user_files),
        "user_images": list(entry.user_images),
        "user_files": list(entry.user_files),
    }


def snapshot_prompts(state: PendingPromptQueueState) -> list[dict[str, Any]]:
    """生成队列快照 — 对标 Cline snapshotPrompts"""
    return [snapshot_prompt(p) for p in state.pending_prompts]


# ============================================================================
# PendingPromptService — 纯逻辑层，对标 Cline PendingPromptService
# ============================================================================


class PendingPromptService:
    """待处理输入纯逻辑服务 — 对标 Cline PendingPromptService

    所有方法不依赖外部状态，仅操作传入的 state 对象。
    Controller 层负责依赖注入和调度。
    """

    def list(self, state: PendingPromptQueueState | None) -> list[dict[str, Any]]:
        """列出所有待处理输入 — 对标 Cline PendingPromptService.list"""
        return snapshot_prompts(state) if state else []

    def enqueue(
        self,
        state: PendingPromptQueueState,
        prompt: str,
        mode: str | None = None,
        delivery: str = "queue",
        user_images: list[str] | None = None,
        user_files: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """入队 — 对标 Cline PendingPromptService.enqueue

        逻辑：
            1. 若同 prompt 已存在，合并更新（保留原 mode/attachments）
            2. steer 类型放队首（高优先级）
            3. queue 类型放队尾
            4. steer + queue 合并时升级为 steer

        Args:
            state: 队列状态
            prompt: 用户输入文本（不可为空）
            mode: agent 模式
            delivery: "queue" 或 "steer"
            user_images: 图片路径列表
            user_files: 文件路径列表

        Returns:
            入队后的队列快照
        """
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("prompt cannot be empty")

        user_images = user_images or []
        user_files = user_files or []

        # 检查是否已存在相同 prompt
        existing_index = -1
        for i, queued in enumerate(state.pending_prompts):
            if queued.prompt == prompt:
                existing_index = i
                break

        if existing_index >= 0:
            # 合并更新已有条目
            existing = state.pending_prompts.pop(existing_index)
            merged_delivery = "steer" if (delivery == "steer" or existing.delivery == "steer") else "queue"
            next_entry = PendingPromptEntry(
                id=existing.id,
                prompt=prompt,
                mode=mode if mode is not None else existing.mode,
                delivery=merged_delivery,
                user_images=user_images if user_images else existing.user_images,
                user_files=user_files if user_files else existing.user_files,
            )
            if merged_delivery == "steer":
                state.pending_prompts.insert(0, next_entry)
            else:
                state.pending_prompts.append(next_entry)
        else:
            # 新建条目
            new_entry = PendingPromptEntry(
                id=_generate_prompt_id(),
                prompt=prompt,
                mode=mode,
                delivery=delivery,
                user_images=user_images,
                user_files=user_files,
            )
            if delivery == "steer":
                state.pending_prompts.insert(0, new_entry)
            else:
                state.pending_prompts.append(new_entry)

        return snapshot_prompts(state)

    def consume_steer(
        self, state: PendingPromptQueueState
    ) -> tuple[PendingPromptEntry | None, list[dict[str, Any]]]:
        """消费队首的 steer 类型条目 — 对标 Cline PendingPromptService.consumeSteer

        Returns:
            (entry, prompts_snapshot)
            - entry: 取出的 steer 条目，无则 None
            - prompts_snapshot: 消费后的队列快照
        """
        steer_index = -1
        for i, entry in enumerate(state.pending_prompts):
            if entry.delivery == "steer":
                steer_index = i
                break

        if steer_index < 0:
            return None, snapshot_prompts(state)

        entry = state.pending_prompts.pop(steer_index)
        return entry, snapshot_prompts(state)

    def shift_next(
        self, state: PendingPromptQueueState
    ) -> tuple[PendingPromptEntry | None, list[dict[str, Any]]]:
        """取出队首 — 对标 Cline PendingPromptService.shiftNext

        Returns:
            (entry, prompts_snapshot)
        """
        if not state.pending_prompts:
            return None, snapshot_prompts(state)
        entry = state.pending_prompts.pop(0)
        return entry, snapshot_prompts(state)

    def requeue_front(
        self,
        state: PendingPromptQueueState,
        entry: PendingPromptEntry,
    ) -> list[dict[str, Any]]:
        """重新入队到队首 — 对标 Cline PendingPromptService.requeueFront

        用于 drain 失败时把 entry 重新放回队首，避免丢失。
        """
        state.pending_prompts.insert(0, entry)
        return snapshot_prompts(state)

    def update(
        self,
        state: PendingPromptQueueState,
        prompt_id: str,
        prompt: str | None = None,
        mode: str | None = None,
        delivery: str | None = None,
    ) -> tuple[bool, dict[str, Any] | None, list[dict[str, Any]]]:
        """更新条目 — 对标 Cline PendingPromptService.update

        Args:
            state: 队列状态
            prompt_id: 要更新的条目 ID
            prompt: 新 prompt（None 表示不修改）
            mode: 新 mode
            delivery: 新 delivery

        Returns:
            (updated, updated_entry_snapshot, prompts_snapshot)
        """
        prompt_id = (prompt_id or "").strip()
        index = -1
        for i, entry in enumerate(state.pending_prompts):
            if entry.id == prompt_id:
                index = i
                break

        if index < 0:
            return False, None, snapshot_prompts(state)

        existing = state.pending_prompts[index]
        new_prompt = (prompt or "").strip() if prompt is not None else existing.prompt
        if not new_prompt:
            raise ValueError("prompt cannot be empty")

        new_delivery = delivery if delivery is not None else existing.delivery
        new_mode = mode if mode is not None else existing.mode

        next_entry = PendingPromptEntry(
            id=existing.id,
            prompt=new_prompt,
            mode=new_mode,
            delivery=new_delivery,
            user_images=existing.user_images,
            user_files=existing.user_files,
        )

        # 重新插入：steer 放队首，queue 保持原位
        state.pending_prompts.pop(index)
        if next_entry.delivery == "steer" and existing.delivery != "steer":
            state.pending_prompts.insert(0, next_entry)
        elif next_entry.delivery != "steer" and existing.delivery == "steer":
            state.pending_prompts.append(next_entry)
        else:
            state.pending_prompts.insert(index, next_entry)

        return True, snapshot_prompt(next_entry), snapshot_prompts(state)

    def delete(
        self,
        state: PendingPromptQueueState,
        prompt_id: str,
    ) -> tuple[bool, dict[str, Any] | None, list[dict[str, Any]]]:
        """删除条目 — 对标 Cline PendingPromptService.delete

        Returns:
            (removed, removed_entry_snapshot, prompts_snapshot)
        """
        prompt_id = (prompt_id or "").strip()
        index = -1
        for i, entry in enumerate(state.pending_prompts):
            if entry.id == prompt_id:
                index = i
                break

        if index < 0:
            return False, None, snapshot_prompts(state)

        removed = state.pending_prompts.pop(index)
        return True, snapshot_prompt(removed), snapshot_prompts(state)

    def clear(self, state: PendingPromptQueueState) -> list[dict[str, Any]]:
        """清空队列 — 对标 Cline PendingPromptService.clear"""
        state.pending_prompts.clear()
        return []


# ============================================================================
# PendingPromptsController — 依赖注入 + 调度层，对标 Cline PendingPromptsController
# ============================================================================


# 会话状态查询回调：返回 (is_aborting, is_draining, can_start_run)
SessionStatusQuery = Callable[[str], tuple[bool, bool, bool]]
# 发送消息回调：触发 agent 运行
SendCallback = Callable[[str, str, str | None, list[str], list[str]], Awaitable[None]]
# 事件发射回调
EmitCallback = Callable[[dict[str, Any]], None]


class PendingPromptsController:
    """待处理输入控制器 — 对标 Cline PendingPromptsController

    依赖注入：
        - session_status_query: 查询会话状态 (is_aborting, is_draining, can_start_run)
        - send_callback: 触发 agent 运行（await send(session_id, prompt, mode, images, files)）
        - emit_callback: 发射 SSE 事件
        - get_state: 获取会话的队列状态（返回 None 表示无状态）

    调度逻辑：
        - enqueue/update/delete 后自动 scheduleDrain
        - scheduleDrain 检查条件后用 asyncio.create_task 调度 drain
        - drain 取出队首并调用 send_callback，失败时 requeueFront
    """

    def __init__(
        self,
        session_status_query: SessionStatusQuery,
        send_callback: SendCallback,
        emit_callback: EmitCallback | None = None,
    ) -> None:
        self._service = PendingPromptService()
        self._session_status_query = session_status_query
        self._send_callback = send_callback
        self._emit_callback = emit_callback
        # 会话队列状态存储 — session_id -> PendingPromptQueueState
        self._states: dict[str, PendingPromptQueueState] = {}
        # 防止 drain 重入 - session_id -> bool
        self._draining: set[str] = set()
        # 已调度的 drain 任务，避免被 GC
        self._drain_tasks: dict[str, asyncio.Task] = {}

    def get_state(self, session_id: str) -> PendingPromptQueueState:
        """获取或创建会话队列状态"""
        if session_id not in self._states:
            self._states[session_id] = PendingPromptQueueState()
        return self._states[session_id]

    def list(self, session_id: str) -> list[dict[str, Any]]:
        """列出会话的待处理输入"""
        return self._service.list(self._states.get(session_id))

    def enqueue(
        self,
        session_id: str,
        prompt: str,
        mode: str | None = None,
        delivery: str = "queue",
        user_images: list[str] | None = None,
        user_files: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """入队 — 对标 Cline PendingPromptsController.enqueue

        若会话正在 aborting，忽略入队请求。
        """
        is_aborting, _, _ = self._session_status_query(session_id)
        if is_aborting:
            logger.debug("turn_queue: session %s 正在 aborting，忽略入队", session_id)
            return []

        state = self.get_state(session_id)
        prompts = self._service.enqueue(
            state, prompt, mode, delivery, user_images, user_files,
        )
        self._emit_prompts(session_id, prompts)
        self._schedule_drain(session_id)
        return prompts

    def update(
        self,
        session_id: str,
        prompt_id: str,
        prompt: str | None = None,
        mode: str | None = None,
        delivery: str | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """更新条目 — 对标 Cline PendingPromptsController.update"""
        is_aborting, _, _ = self._session_status_query(session_id)
        if is_aborting:
            return False, []

        state = self._states.get(session_id)
        if state is None:
            return False, []

        updated, _, prompts = self._service.update(
            state, prompt_id, prompt, mode, delivery,
        )
        self._emit_prompts(session_id, prompts)
        self._schedule_drain(session_id)
        return updated, prompts

    def delete(
        self,
        session_id: str,
        prompt_id: str,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """删除条目 — 对标 Cline PendingPromptsController.delete"""
        is_aborting, _, _ = self._session_status_query(session_id)
        if is_aborting:
            return False, []

        state = self._states.get(session_id)
        if state is None:
            return False, []

        removed, _, prompts = self._service.delete(state, prompt_id)
        self._emit_prompts(session_id, prompts)
        self._schedule_drain(session_id)
        return removed, prompts

    def consume_steer(self, session_id: str) -> PendingPromptEntry | None:
        """消费 steer 条目 — 对标 Cline PendingPromptsController.consumeSteer

        AgentRuntime 在 iteration > 1 时调用此方法获取 steer 消息，
        追加到当前 model request 的 messages 末尾。
        """
        state = self._states.get(session_id)
        if state is None:
            return None

        entry, prompts = self._service.consume_steer(state)
        if entry is not None:
            self._emit_prompts(session_id, prompts)
            self._emit_submitted(session_id, entry)
        return entry

    def clear_aborted(self, session_id: str) -> None:
        """abort 后清空队列 — 对标 Cline PendingPromptsController.clearAborted"""
        state = self._states.get(session_id)
        if state is None or not state.pending_prompts:
            return
        prompts = self._service.clear(state)
        self._emit_prompts(session_id, prompts)

    def clear(self, session_id: str) -> None:
        """显式清空会话队列（用于 session 销毁）"""
        state = self._states.pop(session_id, None)
        if state:
            self._service.clear(state)
        self._draining.discard(session_id)
        task = self._drain_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

    def _emit_prompts(self, session_id: str, prompts: list[dict[str, Any]]) -> None:
        """发射 pending_prompts 事件 — 对标 Cline emitPrompts"""
        if self._emit_callback is None:
            return
        self._emit_callback({
            "type": "pending_prompts",
            "payload": {
                "session_id": session_id,
                "prompts": prompts,
            },
        })

    def _emit_submitted(self, session_id: str, entry: PendingPromptEntry) -> None:
        """发射 pending_prompt_submitted 事件 — 对标 Cline emitSubmitted"""
        if self._emit_callback is None:
            return
        snapshot = snapshot_prompt(entry)
        self._emit_callback({
            "type": "pending_prompt_submitted",
            "payload": {
                "session_id": session_id,
                "id": snapshot["id"],
                "prompt": snapshot["prompt"],
                "delivery": snapshot["delivery"],
                "attachment_count": snapshot["attachment_count"],
                "user_images": snapshot["user_images"],
                "user_files": snapshot["user_files"],
            },
        })

    def _schedule_drain(self, session_id: str) -> None:
        """调度 drain — 对标 Cline PendingPromptsController.scheduleDrain

        条件：
            - 队列非空
            - 非 aborting
            - 非 draining
            - agent 可以启动新 run（can_start_run）
        """
        state = self._states.get(session_id)
        if state is None or not state.pending_prompts:
            return

        is_aborting, is_draining, can_start_run = self._session_status_query(session_id)
        if is_aborting or is_draining or not can_start_run:
            return

        # 取消已存在的 drain 任务
        existing = self._drain_tasks.get(session_id)
        if existing and not existing.done():
            return  # 已有 drain 在排队，避免重复调度

        # 用 asyncio.create_task 调度 drain — 对标 Cline queueMicrotask
        # 注意：enqueue 可能在同步上下文调用（无运行中 event loop），此时跳过调度
        # 真正的 drain 由 server 层在 async 上下文中触发（如 _sse_generator 结束时）
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._drain(session_id))
            self._drain_tasks[session_id] = task
        except RuntimeError:
            # 无运行中事件循环（同步上下文），跳过自动 drain
            # server 层会在 run 结束后通过 pending_prompts_drained 事件通知前端
            logger.debug("turn_queue: 无运行中事件循环，跳过 drain 调度 session=%s", session_id)

    async def _drain(self, session_id: str) -> None:
        """消费队列 — 对标 Cline PendingPromptsController.drain

        持续消费队列直到空或失败：
            1. 检查条件（非 aborting / 非 draining / can_start_run）
            2. shift_next 取出队首
            3. 标记 draining
            4. 调用 send_callback 触发 agent 运行
            5. 失败时 requeueFront 重新入队
            6. 成功且队列非空时继续 drain
        """
        is_aborting, is_draining, can_start_run = self._session_status_query(session_id)
        if is_aborting or is_draining or not can_start_run:
            return

        state = self._states.get(session_id)
        if state is None:
            return

        entry, prompts = self._service.shift_next(state)
        if entry is None:
            return

        self._emit_prompts(session_id, prompts)
        self._emit_submitted(session_id, entry)

        self._draining.add(session_id)
        continue_drain = True
        try:
            await self._send_callback(
                session_id,
                entry.prompt,
                entry.mode,
                entry.user_images,
                entry.user_files,
            )
        except Exception as e:
            logger.warning("turn_queue: drain 发送失败 session=%s: %s", session_id, e)
            continue_drain = False
            # 重新入队到队首，避免丢失
            state_after = self._states.get(session_id)
            if state_after is not None:
                self._service.requeue_front(state_after, entry)
                self._emit_prompts(session_id, snapshot_prompts(state_after))
        finally:
            self._draining.discard(session_id)
            self._drain_tasks.pop(session_id, None)

            # 队列还有且未失败，继续 drain
            state_after = self._states.get(session_id)
            if (
                continue_drain
                and state_after is not None
                and state_after.pending_prompts
            ):
                # 检查会话状态，避免 aborting/failed 时继续 drain
                is_aborting2, _, can_start2 = self._session_status_query(session_id)
                if not is_aborting2 and can_start2:
                    self._schedule_drain(session_id)


# ============================================================================
# 模块级便捷实例 — 延迟初始化，由 server.py 注入依赖
# ============================================================================


_controller: PendingPromptsController | None = None


def init_controller(
    session_status_query: SessionStatusQuery,
    send_callback: SendCallback,
    emit_callback: EmitCallback | None = None,
) -> PendingPromptsController:
    """初始化全局 controller — 由 server.py 在启动时调用"""
    global _controller
    _controller = PendingPromptsController(
        session_status_query=session_status_query,
        send_callback=send_callback,
        emit_callback=emit_callback,
    )
    return _controller


def get_controller() -> PendingPromptsController | None:
    """获取全局 controller — 由 runtime.py / server.py 调用"""
    return _controller
