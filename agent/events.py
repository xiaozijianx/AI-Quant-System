# -*- coding: utf-8 -*-
"""事件系统 — 对标 Cline AgentRuntime 的事件发射机制

AgentRuntime 通过 EventEmitter 向外部发送事件，
SSE 路由层订阅事件后转为 SSE 流发给前端。
这种设计解耦了 Agent 运行时和传输层（SSE / WebSocket / CLI）。

事件类型:
    - 运行生命周期: run-started / run-finished / run-failed
    - 轮次生命周期: turn-started / turn-finished
    - LLM 输出: assistant-text-delta / assistant-reasoning-delta
    - 消息变更: message-added
    - 工具执行: tool-started / tool-finished
    - 用量更新: usage-updated
    - 状态通知: status-notice
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Union

from agent.types import AgentMessage, AgentRunResult, AgentRuntimeStateSnapshot, AgentUsage


# ============================================================================
# 事件类型常量 — 对标 Cline AgentRuntimeEvent 的 type 字段
# ============================================================================

# 运行生命周期
RUN_STARTED = "run-started"
RUN_FINISHED = "run-finished"
RUN_FAILED = "run-failed"

# 轮次生命周期
TURN_STARTED = "turn-started"
TURN_FINISHED = "turn-finished"

# LLM 输出
ASSISTANT_TEXT_DELTA = "assistant-text-delta"
ASSISTANT_REASONING_DELTA = "assistant-reasoning-delta"

# 消息变更
MESSAGE_ADDED = "message-added"
# assistant 消息完成事件 — 对标 Cline assistant-message (agent.ts L497-503)
ASSISTANT_MESSAGE = "assistant-message"

# 工具执行 — 对标 Cline tool-started / tool-finished (agent.ts L505-523)
# 常量名保留 TOOL_EXECUTION_* 前缀向后兼容，值已对齐 Cline
TOOL_EXECUTION_STARTED = "tool-started"
TOOL_EXECUTION_FINISHED = "tool-finished"
# 工具进度更新事件 — 对标 Cline tool-updated (agent.ts L511-516)
TOOL_UPDATED = "tool-updated"

# 用量与状态
USAGE_UPDATED = "usage-updated"
STATUS_NOTICE = "status-notice"

# 压缩生命周期 — Stage 4.8 (J20) 新增，对标 Cline emitStatusNotice 的 compaction 事件
COMPACTION_STARTED = "compaction-started"
COMPACTION_COMPLETED = "compaction-completed"
COMPACTION_SKIPPED = "compaction-skipped"
COMPACTION_BUDGET_ADJUSTED = "compaction-budget-adjusted"
# Stage 11.3 (J13): 压缩失败事件 — 对标 Cline compaction-failed
COMPACTION_FAILED = "compaction-failed"


# ============================================================================
# 事件数据类
# ============================================================================

@dataclass
class AgentEvent:
    """Agent 运行时事件 — 对标 Cline AgentRuntimeEvent

    所有事件的统一容器，不同 type 使用不同字段。
    snapshot 始终携带当前运行时状态快照。
    """
    type: str
    snapshot: AgentRuntimeStateSnapshot | None = None

    # 轮次相关
    iteration: int | None = None

    # LLM 输出相关 (assistant-text-delta / assistant-reasoning-delta)
    text: str | None = None              # 增量文本
    accumulated_text: str | None = None  # 累积文本

    # reasoning-delta 专用
    redacted: bool | None = None
    metadata: Any | None = None

    # 消息相关 (message-added)
    message: AgentMessage | None = None

    # 轮次完成相关 (turn-finished)
    finish_reason: str | None = None
    tool_call_count: int | None = None

    # 运行完成相关 (run-finished / run-failed)
    result: AgentRunResult | None = None
    error: Exception | None = None

    # 工具执行相关 (tool-started / tool-finished)
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_input: Any | None = None
    tool_output: Any | None = None
    tool_is_error: bool | None = None
    tool_duration_ms: int | None = None

    # 用量相关 (usage-updated)
    usage: AgentUsage | None = None

    # 状态通知 (status-notice)
    notice: str | None = None


# 事件监听器类型: 同步或异步函数
EventListener = Callable[[AgentEvent], Union[None, Any]]


# ============================================================================
# 事件发射器 — 对标 Cline AgentRuntime 的 listeners Set + emit 方法
# ============================================================================

class EventEmitter:
    """事件发射器 — 对标 Cline AgentRuntime._emitter

    AgentRuntime 持有一个 EventEmitter 实例，
    外部通过 subscribe() 订阅事件，通过 emit() 发射事件。

    用法:
        emitter = EventEmitter()
        unsubscribe = emitter.subscribe(lambda e: print(e.type))
        await emitter.emit(AgentEvent(type=RUN_STARTED))
        unsubscribe()  # 取消订阅
    """

    def __init__(self) -> None:
        # P2-26: 监听器容器从 list 改为 set，避免同一 listener 重复注册
        # 对标 Cline AgentRuntime 的 listeners Set（agent-runtime.ts 中用 Set 存储）
        self._listeners: set[EventListener] = set()

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """订阅事件 — 对标 Cline AgentRuntime.on()

        返回取消订阅函数，调用后移除该监听器。

        Args:
            listener: 事件监听函数，接收 AgentEvent 参数。
                      可以是同步函数或 async 函数。

        Returns:
            取消订阅函数，调用后移除该监听器。
        """
        self._listeners.add(listener)

        def unsubscribe() -> None:
            # P2-26: 使用 discard 避免不存在时抛 KeyError（向后兼容）
            self._listeners.discard(listener)

        return unsubscribe

    def unsubscribe_all(self) -> None:
        """移除所有监听器"""
        self._listeners.clear()

    async def emit(self, event: AgentEvent) -> None:
        """发射事件给所有监听器 — 对标 Cline AgentRuntime.emit()

        依次调用每个监听器。如果监听器是 async 函数则 await，
        否则同步调用。单个监听器异常不影响其他监听器。

        Args:
            event: 要发射的事件对象。
        """
        # 拷贝列表避免遍历过程中订阅/取消订阅导致的问题
        listeners = list(self._listeners)
        for listener in listeners:
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # 单个监听器异常不影响其他监听器和 Agent 运行
                import traceback
                traceback.print_exc()

    def emit_sync(self, event: AgentEvent) -> None:
        """同步发射事件给所有监听器 — 用于同步上下文的实时事件推送

        与 emit() 的区别:
            - emit() 是 async 函数，需要 await，适用于 runtime 主流程的事件发射
            - emit_sync() 是同步函数，立即调用所有 listener，不 await async listener
              适用于 emit_update 等同步回调（如 run_commands 的 terminal_output 推送）

        解决的问题:
            原来 emit_update 用 asyncio.create_task(self._emit(event)) fire-and-forget，
            task 不会立即执行，需等事件循环调度。在 _read_stream 频繁调用时，
            task 可能堆积，导致 terminal_output 事件延迟到 tool_output 之后才进入
            event_queue，前端无法实时看到终端输出。

        emit_sync 立即调用所有 listener（包括同步和 async），同步 listener 被立即
        执行（如 server.py 的 on_event 把事件放入 event_queue），async listener
        被调用但不 await（返回的 coroutine 会被丢弃，这些 listener 应在 emit() 中
        被正确 await）。

        Args:
            event: 要发射的事件对象。
        """
        # 拷贝列表避免遍历过程中订阅/取消订阅导致的问题
        listeners = list(self._listeners)
        for listener in listeners:
            try:
                # 同步调用 listener，不 await 返回的 coroutine
                # async listener 会在后续的 emit() 中被正确 await
                listener(event)
            except Exception:
                # 单个监听器异常不影响其他监听器和 Agent 运行
                import traceback
                traceback.print_exc()

    @property
    def listener_count(self) -> int:
        """当前监听器数量"""
        return len(self._listeners)


# ============================================================================
# 事件构造辅助函数 — 简化 AgentRuntime 中的事件创建
# ============================================================================

def make_run_started(snapshot: AgentRuntimeStateSnapshot) -> AgentEvent:
    """构造 run-started 事件"""
    return AgentEvent(type=RUN_STARTED, snapshot=snapshot)


def make_turn_started(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
) -> AgentEvent:
    """构造 turn-started 事件"""
    return AgentEvent(type=TURN_STARTED, snapshot=snapshot, iteration=iteration)


def make_text_delta(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    text: str,
    accumulated_text: str,
) -> AgentEvent:
    """构造 assistant-text-delta 事件

    对标 Cline agent-runtime.ts L927-933 的 emit({type: "assistant-text-delta", ...})
    """
    return AgentEvent(
        type=ASSISTANT_TEXT_DELTA,
        snapshot=snapshot,
        iteration=iteration,
        text=text,
        accumulated_text=accumulated_text,
    )


def make_reasoning_delta(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    text: str,
    accumulated_text: str,
    redacted: bool = False,
    metadata: Any = None,
) -> AgentEvent:
    """构造 assistant-reasoning-delta 事件

    对标 Cline agent-runtime.ts L954-962 的 emit({type: "assistant-reasoning-delta", ...})

    reasoning_delta 携带 LLM 的思考过程（如 Qwen reasoning_content），
    与 text_delta 分离以便前端区分展示"思考"和"回答"。
    """
    return AgentEvent(
        type=ASSISTANT_REASONING_DELTA,
        snapshot=snapshot,
        iteration=iteration,
        text=text,
        accumulated_text=accumulated_text,
        redacted=redacted,
        metadata=metadata,
    )


def make_message_added(
    snapshot: AgentRuntimeStateSnapshot,
    message: AgentMessage,
) -> AgentEvent:
    """构造 message-added 事件"""
    return AgentEvent(type=MESSAGE_ADDED, snapshot=snapshot, message=message)


def make_assistant_message(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    message: AgentMessage,
    finish_reason: str,
) -> AgentEvent:
    """构造 assistant-message 事件 — 对标 Cline agent-runtime.ts L665-671

    assistant 消息完成时发射，携带 finishReason，
    前端可据此区分 stop/tool-calls/max-tokens 等完成原因。
    与 message-added 配套发射：先 message-added（通用），后 assistant-message（专用）。
    """
    return AgentEvent(
        type=ASSISTANT_MESSAGE,
        snapshot=snapshot,
        iteration=iteration,
        message=message,
        finish_reason=finish_reason,
    )


def make_tool_updated(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    tool_call_id: str,
    tool_name: str,
    update: Any,
) -> AgentEvent:
    """构造 tool-updated 事件 — 对标 Cline agent-runtime.ts L1498-1506

    工具执行过程中发射进度更新，携带 toolCall 标识和 update 数据。
    与 status-notice 区分：status-notice 用于 prepareTurn 等中间状态通知，
    tool-updated 专用于工具执行中的进度更新。
    """
    return AgentEvent(
        type=TOOL_UPDATED,
        snapshot=snapshot,
        iteration=iteration,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        metadata=update if isinstance(update, dict) else {"value": update},
    )


def make_turn_finished(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    tool_call_count: int,
) -> AgentEvent:
    """构造 turn-finished 事件"""
    return AgentEvent(
        type=TURN_FINISHED,
        snapshot=snapshot,
        iteration=iteration,
        tool_call_count=tool_call_count,
    )


def make_run_finished(
    snapshot: AgentRuntimeStateSnapshot,
    result: AgentRunResult,
) -> AgentEvent:
    """构造 run-finished 事件"""
    return AgentEvent(type=RUN_FINISHED, snapshot=snapshot, result=result)


def make_run_failed(
    snapshot: AgentRuntimeStateSnapshot,
    error: Exception,
) -> AgentEvent:
    """构造 run-failed 事件"""
    return AgentEvent(type=RUN_FAILED, snapshot=snapshot, error=error)


def make_tool_started(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    tool_name: str,
    tool_call_id: str,
    tool_input: Any,
) -> AgentEvent:
    """构造 tool-started 事件"""
    return AgentEvent(
        type=TOOL_EXECUTION_STARTED,
        snapshot=snapshot,
        iteration=iteration,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_input=tool_input,
    )


def make_tool_finished(
    snapshot: AgentRuntimeStateSnapshot,
    iteration: int,
    tool_name: str,
    tool_call_id: str,
    tool_output: Any,
    is_error: bool,
    duration_ms: int,
) -> AgentEvent:
    """构造 tool-finished 事件"""
    return AgentEvent(
        type=TOOL_EXECUTION_FINISHED,
        snapshot=snapshot,
        iteration=iteration,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_output=tool_output,
        tool_is_error=is_error,
        tool_duration_ms=duration_ms,
    )


def make_usage_updated(
    snapshot: AgentRuntimeStateSnapshot,
    usage: AgentUsage,
) -> AgentEvent:
    """构造 usage-updated 事件"""
    return AgentEvent(type=USAGE_UPDATED, snapshot=snapshot, usage=usage)


def make_status_notice(
    snapshot: AgentRuntimeStateSnapshot,
    message: str,
    metadata: Any = None,
) -> AgentEvent:
    """构造 status-notice 事件

    用于 prepareTurn 等中间状态通知，如"正在压缩上下文..."。
    """
    return AgentEvent(
        type=STATUS_NOTICE,
        snapshot=snapshot,
        notice=message,
        metadata=metadata,
    )


# ============================================================================
# 压缩事件辅助函数 — Stage 4.8 (J20) 新增，对标 Cline emitStatusNotice 的 compaction 事件
# ============================================================================


def make_compaction_started(
    snapshot: AgentRuntimeStateSnapshot,
    reason: str,
    trigger_tokens: int,
    target_tokens: int,
    max_input_tokens: int,
    iteration: int | None = None,
    compaction_snapshot: Any = None,
) -> AgentEvent:
    """构造 compaction-started 事件 — 对标 Cline compacting/auto-compacting

    Args:
        snapshot: 运行时状态快照
        reason: 触发原因（如 "auto-compaction" / "manual-compaction"）
        trigger_tokens: 触发阈值 token 数
        target_tokens: 压缩后目标 token 数
        max_input_tokens: 模型最大输入 token 数
        iteration: 当前迭代轮次
        compaction_snapshot: Stage 11.3 (J13) 新增，CompactionStateSnapshot 实例，
                            None 时不附加；前端从 snapshot 读取压缩进度
    """
    metadata = {
        "kind": reason,
        "reason": reason,
        "phase": "started",
        "trigger_tokens": trigger_tokens,
        "target_tokens": target_tokens,
        "max_input_tokens": max_input_tokens,
    }
    # Stage 11.3 (J13): 附加 CompactionStateSnapshot 字段
    if compaction_snapshot is not None:
        metadata["compaction_snapshot"] = {
            "original_count": compaction_snapshot.original_count,
            "compacted_count": compaction_snapshot.compacted_count,
            "discarded_count": compaction_snapshot.discarded_count,
            "elapsed_ms": compaction_snapshot.elapsed_ms,
            "status": compaction_snapshot.status,
            "system_prompt_preserved": compaction_snapshot.system_prompt_preserved,
        }
    return AgentEvent(
        type=COMPACTION_STARTED,
        snapshot=snapshot,
        iteration=iteration,
        metadata=metadata,
    )


def make_compaction_completed(
    snapshot: AgentRuntimeStateSnapshot,
    reason: str,
    tokens_before: int,
    tokens_after: int,
    messages_before: int,
    messages_after: int,
    max_input_tokens: int,
    iteration: int | None = None,
    compaction_snapshot: Any = None,
) -> AgentEvent:
    """构造 compaction-completed 事件 — 对标 Cline compacted/auto-compacted

    Args:
        snapshot: 运行时状态快照
        reason: 触发原因
        tokens_before: 压缩前 token 数
        tokens_after: 压缩后 token 数
        messages_before: 压缩前消息数
        messages_after: 压缩后消息数
        max_input_tokens: 模型最大输入 token 数
        iteration: 当前迭代轮次
        compaction_snapshot: Stage 11.3 (J13) 新增，CompactionStateSnapshot 实例
    """
    metadata = {
        "kind": reason,
        "reason": reason,
        "phase": "completed",
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "messages_before": messages_before,
        "messages_after": messages_after,
        "max_input_tokens": max_input_tokens,
    }
    if compaction_snapshot is not None:
        metadata["compaction_snapshot"] = {
            "original_count": compaction_snapshot.original_count,
            "compacted_count": compaction_snapshot.compacted_count,
            "discarded_count": compaction_snapshot.discarded_count,
            "elapsed_ms": compaction_snapshot.elapsed_ms,
            "status": compaction_snapshot.status,
            "system_prompt_preserved": compaction_snapshot.system_prompt_preserved,
        }
    return AgentEvent(
        type=COMPACTION_COMPLETED,
        snapshot=snapshot,
        iteration=iteration,
        metadata=metadata,
    )


def make_compaction_skipped(
    snapshot: AgentRuntimeStateSnapshot,
    reason: str,
    max_input_tokens: int,
    iteration: int | None = None,
    compaction_snapshot: Any = None,
) -> AgentEvent:
    """构造 compaction-skipped 事件 — 对标 Cline compaction-skipped

    Args:
        snapshot: 运行时状态快照
        reason: 跳过原因（如 "below-threshold" / "already-compacted"）
        max_input_tokens: 模型最大输入 token 数
        iteration: 当前迭代轮次
        compaction_snapshot: Stage 11.3 (J13) 新增，CompactionStateSnapshot 实例
    """
    metadata = {
        "kind": reason,
        "reason": reason,
        "phase": "skipped",
        "max_input_tokens": max_input_tokens,
    }
    if compaction_snapshot is not None:
        metadata["compaction_snapshot"] = {
            "original_count": compaction_snapshot.original_count,
            "compacted_count": compaction_snapshot.compacted_count,
            "discarded_count": compaction_snapshot.discarded_count,
            "elapsed_ms": compaction_snapshot.elapsed_ms,
            "status": compaction_snapshot.status,
            "system_prompt_preserved": compaction_snapshot.system_prompt_preserved,
        }
    return AgentEvent(
        type=COMPACTION_SKIPPED,
        snapshot=snapshot,
        iteration=iteration,
        metadata=metadata,
    )


def make_compaction_failed(
    snapshot: AgentRuntimeStateSnapshot,
    reason: str,
    error: str,
    max_input_tokens: int,
    iteration: int | None = None,
    compaction_snapshot: Any = None,
) -> AgentEvent:
    """构造 compaction-failed 事件 — Stage 11.3 (J13) 新增，对标 Cline compaction-failed

    压缩失败时由 ContextCompactor.before_model 触发，
    前端据此显示压缩失败状态。

    Args:
        snapshot: 运行时状态快照
        reason: 失败原因（如 "agentic-failed" / "fallback-failed" / "aborted"）
        error: 错误消息文本
        max_input_tokens: 模型最大输入 token 数
        iteration: 当前迭代轮次
        compaction_snapshot: CompactionStateSnapshot 实例
    """
    metadata = {
        "kind": reason,
        "reason": reason,
        "phase": "failed",
        "error": error,
        "max_input_tokens": max_input_tokens,
    }
    if compaction_snapshot is not None:
        metadata["compaction_snapshot"] = {
            "original_count": compaction_snapshot.original_count,
            "compacted_count": compaction_snapshot.compacted_count,
            "discarded_count": compaction_snapshot.discarded_count,
            "elapsed_ms": compaction_snapshot.elapsed_ms,
            "status": compaction_snapshot.status,
            "system_prompt_preserved": compaction_snapshot.system_prompt_preserved,
        }
    return AgentEvent(
        type=COMPACTION_FAILED,
        snapshot=snapshot,
        iteration=iteration,
        metadata=metadata,
    )


def make_compaction_budget_adjusted(
    snapshot: AgentRuntimeStateSnapshot,
    reason: str,
    policy_intent: str,
    action_count: int,
    warning_count: int,
    iteration: int | None = None,
) -> AgentEvent:
    """构造 compaction-budget-adjusted 事件 — 对标 Cline compaction-budget-adjusted

    budget emergency 时触发，表示已应用 budget projection 进行裁剪。

    Args:
        snapshot: 运行时状态快照
        reason: 调整原因
        policy_intent: budget policy 意图（如 "basic-compaction-projection"）
        action_count: 执行的裁剪动作数
        warning_count: 警告数
        iteration: 当前迭代轮次
    """
    return AgentEvent(
        type=COMPACTION_BUDGET_ADJUSTED,
        snapshot=snapshot,
        iteration=iteration,
        metadata={
            "kind": reason,
            "reason": reason,
            "phase": "budget-adjusted",
            "policy_intent": policy_intent,
            "action_count": action_count,
            "warning_count": warning_count,
        },
    )
