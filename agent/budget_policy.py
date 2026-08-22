# -*- coding: utf-8 -*-
"""预算策略与意图 — 对标 Cline budget-projection types.ts

Phase 33.3 新增。区分 BudgetPolicyIntent 让 ContextCompactor 按场景选择策略：
    1. agentic-summary: 用 LLM 生成摘要，可丢弃 thinking 块、不安全块
    2. basic-compaction-projection: 基础截断压缩，同样丢弃 thinking 块
    3. normal-provider-request: 正常请求，保留所有块（仅投影 token 用量）

策略标志（ProjectionPolicy）:
    - protect_latest_typed_user: 保护最新用户消息不被丢弃/截断
    - protect_live_tail_from_drop: 保护含未配对 tool_use 的尾部消息
    - drop_unsafe_outside_live_tail: 在 live tail 之外丢弃 image/redacted 块
    - drop_thinking_blocks: 丢弃 reasoning/thinking 块（压缩时通常可丢）

辅助函数:
    - find_latest_typed_user_message_index: 找到最后一条非 tool_result 的 user 消息
    - find_protected_tail_start_index: 找到第一条含未配对 tool_use 的消息
    - drop_thinking_blocks: 移除消息中的 ReasoningPart
    - resolve_projection_policy: 按 intent 解析为 ProjectionPolicy

对标 Cline:
    - sdk/packages/core/src/extensions/context/budget-projection/types.ts
    - sdk/packages/core/src/extensions/context/budget-projection/project.ts L17-42
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent.types import (
    AgentMessage,
    MessageRole,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)


class BudgetPolicyIntent(str, Enum):
    """预算策略意图 — 对标 Cline BudgetPolicyIntent

    不同场景下应采用不同的保护/丢弃策略：
        - agentic-summary: LLM 生成摘要压缩时，可丢弃 thinking 和不安全块
        - basic-compaction-projection: 基础截断压缩时，同样丢弃 thinking 块
        - normal-provider-request: 正常请求投影 token，保留所有内容

    枚举值统一使用 kebab-case（对标 Cline 事件名风格），出现在事件 metadata
    的 policy_intent 字段时与事件名风格保持一致。
    """
    AGENTIC_SUMMARY = "agentic-summary"
    BASIC_COMPACTION_PROJECTION = "basic-compaction-projection"
    NORMAL_PROVIDER_REQUEST = "normal-provider-request"


@dataclass
class ProjectionPolicy:
    """投影策略标志 — 对标 Cline ProjectionPolicy

    Attributes:
        protect_latest_typed_user: 保护最新 typed user 消息
        protect_live_tail_from_drop: 保护 live tail（含未配对 tool_use 的尾部）
        drop_unsafe_outside_live_tail: 在 live tail 之外丢弃不安全块（image/redacted）
        drop_thinking_blocks: 丢弃 thinking/reasoning 块
    """
    protect_latest_typed_user: bool = False
    protect_live_tail_from_drop: bool = False
    drop_unsafe_outside_live_tail: bool = False
    drop_thinking_blocks: bool = False


def resolve_projection_policy(intent: BudgetPolicyIntent) -> ProjectionPolicy:
    """按 intent 解析投影策略 — 对标 Cline resolveProjectionPolicy

    Args:
        intent: 预算策略意图

    Returns:
        ProjectionPolicy 实例

    策略矩阵:
        intent                          | protect_user | protect_tail | drop_unsafe | drop_thinking
        --------------------------------|--------------|--------------|-------------|--------------
        agentic-summary                |     True     |     True     |    True     |     True
        basic-compaction-projection    |     True     |     True     |    True     |     True
        normal-provider-request        |     True     |     True     |    False    |     False
    """
    if intent in (BudgetPolicyIntent.AGENTIC_SUMMARY, BudgetPolicyIntent.BASIC_COMPACTION_PROJECTION):
        return ProjectionPolicy(
            protect_latest_typed_user=True,
            protect_live_tail_from_drop=True,
            drop_unsafe_outside_live_tail=True,
            drop_thinking_blocks=True,
        )
    # normal-provider-request: 保留所有内容
    return ProjectionPolicy(
        protect_latest_typed_user=True,
        protect_live_tail_from_drop=True,
        drop_unsafe_outside_live_tail=False,
        drop_thinking_blocks=False,
    )


def is_tool_result_only_user_message(message: AgentMessage) -> bool:
    """判断 user 消息是否只包含 tool_result — 对标 Cline isToolResultOnlyUserMessage

    只含 tool_result 的 user 消息不算"typed user"（用户输入的文字），
    压缩时可以被截断或丢弃，不需要特殊保护。
    """
    if message.role != MessageRole.USER:
        return False
    if not message.content:
        return False
    return all(isinstance(p, ToolResultPart) for p in message.content)


def find_latest_typed_user_message_index(messages: list[AgentMessage]) -> int:
    """找到最后一条 typed user 消息的索引 — 对标 Cline findLatestTypedUserMessageIndex

    typed user 消息 = role=user 且不是纯 tool_result 的消息（即用户真正输入的文字）。

    Args:
        messages: 消息列表

    Returns:
        索引（0-based），找不到返回 -1
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role == MessageRole.USER and not is_tool_result_only_user_message(message):
            return index
    return -1


def find_first_typed_user_message_index(messages: list[AgentMessage]) -> int:
    """找到第一条 typed user 消息的索引 — 对标 Cline findFirstTypedUserMessageIndex"""
    for index in range(len(messages)):
        message = messages[index]
        if message.role == MessageRole.USER and not is_tool_result_only_user_message(message):
            return index
    return -1


def _collect_tool_call_ids(message: AgentMessage) -> set[str]:
    """收集消息中所有 tool_call_id（来自 ToolCallPart 和 ToolResultPart）"""
    ids: set[str] = set()
    for part in message.content:
        if isinstance(part, ToolCallPart) and part.tool_call_id:
            ids.add(part.tool_call_id)
        elif isinstance(part, ToolResultPart) and part.tool_call_id:
            ids.add(part.tool_call_id)
    return ids


def find_protected_tail_start_index(messages: list[AgentMessage]) -> int:
    """找到 live tail 的起始索引 — 对标 Cline findProtectedTailStartIndex

    live tail = 从最后一条未配对 tool_use（无对应 tool_result）的消息开始到末尾。
    这部分消息不能被丢弃，否则会破坏 tool_use/tool_result 配对。

    Args:
        messages: 消息列表

    Returns:
        起始索引；无未配对 tool_use 时返回 len(messages)
    """
    # 收集所有已配对的 tool_call_id（即出现 tool_result 的）
    resolved_tool_call_ids: set[str] = set()
    for message in messages:
        for part in message.content:
            if isinstance(part, ToolResultPart) and part.tool_call_id:
                resolved_tool_call_ids.add(part.tool_call_id)

    # 从末尾向前找第一条含未配对 tool_use 的消息
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        for part in message.content:
            if (
                isinstance(part, ToolCallPart)
                and part.tool_call_id
                and part.tool_call_id not in resolved_tool_call_ids
            ):
                return index
    return len(messages)


def drop_thinking_blocks(
    messages: list[AgentMessage],
    actions: list[BudgetAction] | None = None,
    original_indexes: list[int] | None = None,
) -> list[AgentMessage]:
    """移除消息中的 ReasoningPart — 对标 Cline dropThinkingBlocks

    压缩时 reasoning/thinking 块通常可丢弃（它们是 LLM 的中间思考过程，
    对后续对话无关键影响），可显著减少 token 占用。

    Stage 7.7 (K6) 增强: 增加 actions 与 original_indexes 参数，每删除一个
    ReasoningPart 都记录一条 BudgetAction(kind="dropped_block")，对标 Cline
    project.ts:301-327 的审计轨迹。original_indexes 用于在裁剪过 messages 后
    仍能正确指向原始索引（如 build_budget_projection 多步流水线场景）。

    Args:
        messages: 原始消息列表
        actions: 审计动作列表（可选，传入时追加 dropped_block 动作）
        original_indexes: 原始消息索引映射（可选，传入时按映射记录 message_index；
                          None 时用当前列表索引）

    Returns:
        新的消息列表（ReasoningPart 已移除；空内容的消息会被保留以维持索引对齐，
        由调用方决定是否通过 prune_empty_messages 进一步裁剪）
    """
    result: list[AgentMessage] = []
    for msg_idx, message in enumerate(messages):
        new_content = []
        for block_idx, part in enumerate(message.content):
            if isinstance(part, ReasoningPart):
                # Stage 7.7: 记录 dropped_block 审计动作
                if actions is not None:
                    orig_idx = (
                        original_indexes[msg_idx]
                        if original_indexes is not None and msg_idx < len(original_indexes)
                        else msg_idx
                    )
                    actions.append(BudgetAction(
                        kind="dropped_block",
                        path={
                            "message_index": orig_idx,
                            "block_index": block_idx,
                            "part_type": "reasoning",
                        },
                        reason="unsafe_to_truncate",
                        original_size=len(repr(part)),
                        final_size=0,
                    ))
                continue
            new_content.append(part)
        # 复制消息并替换 content（避免修改原对象）
        new_message = AgentMessage(
            role=message.role,
            content=new_content,
            created_at=message.created_at,
            id=message.id,
            metadata=dict(message.metadata),
            model_info=message.model_info,
            metrics=message.metrics,
        )
        result.append(new_message)
    return result


def apply_budget_policy(
    messages: list[AgentMessage],
    intent: BudgetPolicyIntent,
    actions: list[BudgetAction] | None = None,
    prune_empty: bool = True,
) -> list[AgentMessage]:
    """按预算策略调整消息列表 — Phase 33.3 新增

    根据意图应用策略：
        1. drop_thinking_blocks=True 时移除 ReasoningPart（并记录 dropped_block 动作）
        2. prune_empty=True 时调用 prune_empty_messages 裁剪空内容消息

    本函数不截断文本（那是 build_budget_projection 的职责），
    仅做块级别的策略性丢弃，保留消息结构。

    Stage 7.7 (K6) 增强:
        - 增加 actions 参数，透传给 drop_thinking_blocks 与 prune_empty_messages
        - 增加 prune_empty 参数，默认 True 对齐 Cline buildBudgetProjection 行为
          （drop_thinking_blocks 后立即 prune_empty_messages）
        - 原行为（保留空消息以维持索引对齐）可通过 prune_empty=False 保留

    Args:
        messages: 原始消息列表
        intent: 预算策略意图
        actions: 审计动作列表（可选）
        prune_empty: 是否裁剪空消息（默认 True，对齐 Cline）

    Returns:
        调整后的消息列表（可能比原列表短或同长）
    """
    policy = resolve_projection_policy(intent)
    result = list(messages)

    if policy.drop_thinking_blocks:
        # 传入原始索引映射（drop_thinking_blocks 阶段索引与原始一致）
        result = drop_thinking_blocks(
            result,
            actions=actions,
            original_indexes=list(range(len(result))),
        )
        if prune_empty:
            result, _ = prune_empty_messages(result, actions=actions)

    return result


def estimate_protected_token_budget(
    messages: list[AgentMessage],
    intent: BudgetPolicyIntent,
    target_tokens: int,
    estimate_tokens_fn: Any = None,
) -> dict[str, int]:
    """估算受保护内容的 token 预算 — Phase 33.3 新增

    计算 live tail 和 latest typed user 占用的 token 数，
    帮助 build_budget_projection 决定可截断的预算空间。

    Args:
        messages: 消息列表
        intent: 预算策略意图
        target_tokens: 目标 token 预算
        estimate_tokens_fn: token 估算函数，None 时用 estimate_messages_tokens

    Returns:
        dict:
            total_tokens: 当前总 token 数
            protected_tokens: 受保护消息的 token 数
            available_for_truncation: 可用于截断的 token 预算
            latest_typed_user_index: 最新 typed user 索引（-1 表示无）
            protected_tail_start_index: live tail 起始索引
    """
    if estimate_tokens_fn is None:
        from agent.context import estimate_messages_tokens
        estimate_tokens_fn = estimate_messages_tokens

    policy = resolve_projection_policy(intent)
    total_tokens = estimate_tokens_fn(messages)

    latest_typed_user_idx = (
        find_latest_typed_user_message_index(messages)
        if policy.protect_latest_typed_user else -1
    )
    protected_tail_start_idx = (
        find_protected_tail_start_index(messages)
        if policy.protect_live_tail_from_drop else len(messages)
    )

    # 计算受保护消息的 token 数
    protected_indices: set[int] = set()
    if latest_typed_user_idx >= 0:
        protected_indices.add(latest_typed_user_idx)
    for idx in range(protected_tail_start_idx, len(messages)):
        protected_indices.add(idx)

    protected_tokens = 0
    for idx in protected_indices:
        if 0 <= idx < len(messages):
            protected_tokens += estimate_tokens_fn([messages[idx]])

    available = max(0, target_tokens - protected_tokens)

    return {
        "total_tokens": total_tokens,
        "protected_tokens": protected_tokens,
        "available_for_truncation": available,
        "latest_typed_user_index": latest_typed_user_idx,
        "protected_tail_start_index": protected_tail_start_idx,
    }


# ============================================================================
# Stage 4.3 (K7): 4 步流水线 — 对标 Cline buildBudgetProjection project.ts:483-672
# ============================================================================


@dataclass
class BudgetAction:
    """预算裁剪动作 — 对标 Cline BudgetAction

    记录每一步裁剪操作的审计信息，便于 telemetry 和调试。

    Attributes:
        kind: 动作类型（dropped_block / dropped_message / truncated_text）
        path: 动作定位信息（含 message_index / part_type / original_size 等）
        reason: 动作原因
        original_size: 原始大小（token 或字符数）
        final_size: 最终大小
    """
    kind: str
    path: dict[str, Any]
    reason: str
    original_size: int = 0
    final_size: int = 0


@dataclass
class BudgetProjectionWarning:
    """预算投影警告 — 对标 Cline BudgetProjectionWarning

    Attributes:
        code: 警告码（如 budget_impossible / budget_unachievable_with_protections）
        message: 警告信息
    """
    code: str
    message: str


@dataclass
class BudgetProjectionResult:
    """预算投影结果 — 对标 Cline BudgetProjectionResult

    Attributes:
        status: 状态（ok / failed）
        messages: 投影后的消息列表
        actions: 执行的裁剪动作列表（审计用）
        live_tail_handling: live tail 处理方式描述
        estimated_tokens: 投影后估算 token 数
        warnings: 警告列表
    """
    status: str
    messages: list[AgentMessage]
    actions: list[BudgetAction]
    live_tail_handling: str
    estimated_tokens: int
    warnings: list[BudgetProjectionWarning]


def _estimate_messages_tokens_safe(messages: list[AgentMessage]) -> int:
    """安全估算消息列表的 token 数 — 内部辅助"""
    try:
        from agent.context import estimate_messages_tokens
        return estimate_messages_tokens(messages)
    except Exception:
        # 退化估算：按字符数 / 4 估算
        total_chars = 0
        for m in messages:
            for p in m.content:
                if hasattr(p, "text") and isinstance(p.text, str):
                    total_chars += len(p.text)
                else:
                    total_chars += len(str(p))
        return total_chars // 4


def prune_empty_messages(
    messages: list[AgentMessage],
    actions: list[BudgetAction] | None = None,
) -> tuple[list[AgentMessage], list[int]]:
    """移除空内容消息 — 对标 Cline pruneEmptyMessages project.ts:217-241

    content 长度为 0 的消息（如 drop_thinking_blocks 后只剩空壳）需要移除，
    避免污染下游 LLM 请求。

    Args:
        messages: 原始消息列表
        actions: 审计动作列表（可选，删除时追加 dropped_message 动作）

    Returns:
        (新消息列表, 保留消息在原列表中的索引映射)
    """
    result: list[AgentMessage] = []
    kept_indexes: list[int] = []
    for idx, message in enumerate(messages):
        if message.content:
            result.append(message)
            kept_indexes.append(idx)
        else:
            if actions is not None:
                actions.append(BudgetAction(
                    kind="dropped_message",
                    path={"message_index": idx},
                    reason="empty_after_drop",
                    original_size=0,
                    final_size=0,
                ))
    return result, kept_indexes


def drop_unsafe_blocks(
    messages: list[AgentMessage],
    latest_typed_user_idx: int,
    protected_tail_start_idx: int,
    actions: list[BudgetAction] | None = None,
) -> list[AgentMessage]:
    """丢弃不安全块（redacted reasoning）— 对标 Cline dropUnsafeBlocks project.ts:329-399

    在 live tail 之外且非 latest typed user 的消息中，
    移除 ReasoningPart(redacted=True) 块（对标 Cline redacted_thinking）。

    Args:
        messages: 原始消息列表
        latest_typed_user_idx: 最新 typed user 消息索引（保护）
        protected_tail_start_idx: live tail 起始索引（保护）
        actions: 审计动作列表

    Returns:
        新的消息列表（不安全块已移除）
    """
    result: list[AgentMessage] = []
    for idx, message in enumerate(messages):
        # 保护 latest typed user 和 live tail
        is_protected = (idx == latest_typed_user_idx) or (idx >= protected_tail_start_idx)
        if is_protected:
            result.append(message)
            continue

        new_content = []
        dropped_any = False
        for part in message.content:
            # ReasoningPart(redacted=True) 对应 Cline redacted_thinking，不安全
            if isinstance(part, ReasoningPart) and getattr(part, "redacted", False):
                dropped_any = True
                if actions is not None:
                    actions.append(BudgetAction(
                        kind="dropped_block",
                        path={"message_index": idx, "part_type": "redacted_reasoning"},
                        reason="unsafe_to_truncate",
                    ))
                continue
            new_content.append(part)

        if not dropped_any:
            result.append(message)
        else:
            # 复制消息并替换 content
            new_message = AgentMessage(
                role=message.role,
                content=new_content,
                created_at=message.created_at,
                id=message.id,
                metadata=dict(message.metadata),
                model_info=message.model_info,
                metrics=message.metrics,
            )
            result.append(new_message)
    return result


def truncate_message_text(
    message: AgentMessage,
    target_chars: int,
    message_index: int = -1,
    actions: list[BudgetAction] | None = None,
) -> AgentMessage:
    """截断消息中的 TextPart — 对标 Cline truncateMessageText project.ts:401-431

    对 message.content 中的 TextPart 截断到 target_chars 字符。
    跳过 ToolCallPart / ToolResultPart（不截断工具部分）。

    Args:
        message: 原始消息
        target_chars: 目标字符数
        message_index: 消息索引（审计用）
        actions: 审计动作列表

    Returns:
        新的消息（TextPart 已截断）
    """
    if target_chars <= 0:
        return message

    new_content = []
    truncated = False
    for part in message.content:
        if isinstance(part, TextPart) and len(part.text) > target_chars:
            original_size = len(part.text)
            new_text = part.text[:target_chars]
            new_content.append(TextPart(text=new_text))
            truncated = True
            if actions is not None:
                actions.append(BudgetAction(
                    kind="truncated_text",
                    path={"message_index": message_index, "part_type": "text"},
                    reason="budget_truncation",
                    original_size=original_size,
                    final_size=target_chars,
                ))
        else:
            new_content.append(part)

    if not truncated:
        return message

    return AgentMessage(
        role=message.role,
        content=new_content,
        created_at=message.created_at,
        id=message.id,
        metadata=dict(message.metadata),
        model_info=message.model_info,
        metrics=message.metrics,
    )


def collect_message_closure(
    messages: list[AgentMessage],
    start_index: int,
) -> set[int]:
    """收集 tool_use/tool_result 闭包 — 对标 Cline collectMessageClosure project.ts:433-481

    从 start_index 开始，收集关联的 assistant 消息和 tool_result user 消息。
    闭包含：
        - start_index 处的 assistant 消息（含 ToolCallPart）
        - 所有对应的 tool_result user 消息（含匹配 tool_call_id 的 ToolResultPart）

    Args:
        messages: 消息列表
        start_index: 起始索引

    Returns:
        闭包内消息索引集合
    """
    closure: set[int] = set()
    if start_index < 0 or start_index >= len(messages):
        return closure

    start_msg = messages[start_index]
    # 收集 start_index 处的 tool_call_id
    tool_call_ids: set[str] = set()
    for part in start_msg.content:
        if isinstance(part, ToolCallPart) and part.tool_call_id:
            tool_call_ids.add(part.tool_call_id)

    if not tool_call_ids:
        # 无 tool_call，仅含本消息
        closure.add(start_index)
        return closure

    closure.add(start_index)

    # 向后查找对应的 tool_result 消息
    for idx in range(start_index + 1, len(messages)):
        msg = messages[idx]
        for part in msg.content:
            if isinstance(part, ToolResultPart) and part.tool_call_id in tool_call_ids:
                closure.add(idx)
                break

    return closure


def remove_messages_at(
    messages: list[AgentMessage],
    closure: set[int],
    actions: list[BudgetAction] | None = None,
) -> tuple[list[AgentMessage], list[int]]:
    """移除指定索引集合的消息 — 对标 Cline removeMessagesAt

    Args:
        messages: 原始消息列表
        closure: 待移除的索引集合
        actions: 审计动作列表

    Returns:
        (新消息列表, 保留消息在原列表中的索引映射)
    """
    result: list[AgentMessage] = []
    kept_indexes: list[int] = []
    for idx, message in enumerate(messages):
        if idx in closure:
            if actions is not None:
                actions.append(BudgetAction(
                    kind="dropped_message",
                    path={"message_index": idx},
                    reason="closure_removal",
                ))
            continue
        result.append(message)
        kept_indexes.append(idx)
    return result, kept_indexes


def build_budget_projection(
    messages: list[AgentMessage],
    target_tokens: int,
    intent: BudgetPolicyIntent,
    estimate_tokens_fn: Any = None,
) -> BudgetProjectionResult:
    """构建预算投影 — 对标 Cline buildBudgetProjection project.ts:483-672

    4 步流水线，输出一个能塞进 target_tokens 的消息列表：
        1. drop_thinking_blocks + prune_empty_messages
        2. drop_unsafe_blocks + prune_empty_messages（live tail 之外）
        3. truncate_message_text（从尾到头按 target_chars 截断文本）
        4. collect_message_closure + remove_messages_at（从头丢整条闭包）

    Args:
        messages: 原始消息列表
        target_tokens: 目标 token 预算
        intent: 预算策略意图
        estimate_tokens_fn: token 估算函数，None 时用 estimate_messages_tokens

    Returns:
        BudgetProjectionResult 含 status / messages / actions / warnings
    """
    actions: list[BudgetAction] = []
    warnings: list[BudgetProjectionWarning] = []

    # target_tokens <= 0 时直接失败
    if target_tokens <= 0:
        warnings.append(BudgetProjectionWarning(
            code="budget_impossible",
            message=f"target_tokens={target_tokens} 不合法，必须 > 0",
        ))
        return BudgetProjectionResult(
            status="failed",
            messages=list(messages),
            actions=actions,
            live_tail_handling="not_applied",
            estimated_tokens=_estimate_messages_tokens_safe(messages),
            warnings=warnings,
        )

    if estimate_tokens_fn is None:
        estimate_tokens_fn = _estimate_messages_tokens_safe

    policy = resolve_projection_policy(intent)
    result_messages = list(messages)

    # step 1: drop_thinking_blocks + prune_empty_messages
    if policy.drop_thinking_blocks:
        # Stage 7.7: 传入 actions 让 drop_thinking_blocks 记录 dropped_block 审计动作
        result_messages = drop_thinking_blocks(
            result_messages,
            actions=actions,
            original_indexes=list(range(len(result_messages))),
        )
        result_messages, _ = prune_empty_messages(result_messages, actions)

    # step 2: drop_unsafe_blocks + prune_empty_messages
    if policy.drop_unsafe_outside_live_tail:
        latest_typed_user_idx = find_latest_typed_user_message_index(result_messages)
        protected_tail_start_idx = find_protected_tail_start_index(result_messages)
        result_messages = drop_unsafe_blocks(
            result_messages,
            latest_typed_user_idx=latest_typed_user_idx,
            protected_tail_start_idx=protected_tail_start_idx,
            actions=actions,
        )
        result_messages, _ = prune_empty_messages(result_messages, actions)

    # 估算当前 token，若已达标直接返回
    current_tokens = estimate_tokens_fn(result_messages)
    if current_tokens <= target_tokens:
        return BudgetProjectionResult(
            status="ok",
            messages=result_messages,
            actions=actions,
            live_tail_handling="preserved",
            estimated_tokens=current_tokens,
            warnings=warnings,
        )

    # step 3: truncate_message_text 从尾到头截断
    # 按 Cline: targetChars = max(16, target_tokens * chars_per_token / message_count)
    # chars_per_token 取 4（保守估算，英文约 4 字符/token，中文约 1.5 字符/token）
    chars_per_token = 4
    message_count = max(1, len(result_messages))
    target_chars = max(16, target_tokens * chars_per_token // message_count)

    latest_typed_user_idx = find_latest_typed_user_message_index(result_messages)
    protected_tail_start_idx = find_protected_tail_start_index(result_messages)

    # 从尾到头截断（跳过 latest typed user 和 live tail）
    for idx in range(len(result_messages) - 1, -1, -1):
        if current_tokens <= target_tokens:
            break
        if idx == latest_typed_user_idx or idx >= protected_tail_start_idx:
            continue
        old_tokens = estimate_tokens_fn([result_messages[idx]])
        result_messages[idx] = truncate_message_text(
            result_messages[idx],
            target_chars=target_chars,
            message_index=idx,
            actions=actions,
        )
        new_tokens = estimate_tokens_fn([result_messages[idx]])
        current_tokens = current_tokens - old_tokens + new_tokens

    # 重新检查
    current_tokens = estimate_tokens_fn(result_messages)
    if current_tokens <= target_tokens:
        return BudgetProjectionResult(
            status="ok",
            messages=result_messages,
            actions=actions,
            live_tail_handling="preserved",
            estimated_tokens=current_tokens,
            warnings=warnings,
        )

    # step 4: collect_message_closure + remove_messages_at 从头丢闭包
    first_typed_user_idx = find_first_typed_user_message_index(result_messages)
    latest_typed_user_idx = find_latest_typed_user_message_index(result_messages)
    protected_tail_start_idx = find_protected_tail_start_index(result_messages)

    idx = 0
    while idx < len(result_messages) and current_tokens > target_tokens:
        # 跳过保护项
        if idx == first_typed_user_idx or idx == latest_typed_user_idx or idx >= protected_tail_start_idx:
            idx += 1
            continue

        closure = collect_message_closure(result_messages, idx)
        if not closure:
            idx += 1
            continue

        # 检查闭包是否触及保护项
        if (first_typed_user_idx in closure or latest_typed_user_idx in closure
                or any(i >= protected_tail_start_idx for i in closure)):
            idx += 1
            continue

        removed_tokens = sum(estimate_tokens_fn([result_messages[i]]) for i in closure)
        result_messages, _ = remove_messages_at(result_messages, closure, actions)
        current_tokens -= removed_tokens
        # 不增加 idx，因为列表已缩短，下一个消息仍在 idx 位置
        # 但需要重新计算保护索引
        latest_typed_user_idx = find_latest_typed_user_message_index(result_messages)
        first_typed_user_idx = find_first_typed_user_message_index(result_messages)
        protected_tail_start_idx = find_protected_tail_start_index(result_messages)
        # 防止 idx 超出新长度
        if idx >= len(result_messages):
            break

    current_tokens = estimate_tokens_fn(result_messages)
    if current_tokens <= target_tokens:
        return BudgetProjectionResult(
            status="ok",
            messages=result_messages,
            actions=actions,
            live_tail_handling="preserved",
            estimated_tokens=current_tokens,
            warnings=warnings,
        )

    # 仍超预算
    warnings.append(BudgetProjectionWarning(
        code="budget_unachievable_with_protections",
        message=f"应用全部 4 步后仍超预算（{current_tokens} > {target_tokens}），"
                f"已保护 latest typed user 和 live tail，无法进一步裁剪",
    ))
    return BudgetProjectionResult(
        status="failed",
        messages=result_messages,
        actions=actions,
        live_tail_handling="preserved",
        estimated_tokens=current_tokens,
        warnings=warnings,
    )
