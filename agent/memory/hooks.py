# -*- coding: utf-8 -*-
"""Memory 生命周期挂载钩子 — 把 memory 挂到 Cline 原生生命周期

对齐 Claude Code 的三阶段 memory 实现，挂到 Cline 原生扩展点：

    1. 静态指令 + 索引  → register_rule（在 server.py 装配时注入 system prompt）
    2. 动态召回          → before_model 钩子（每次 query 首次调 LLM 前注入相关记忆）
    3. 抽取              → after_run 钩子（每次 query 结束后 fire-and-forget 抽取记忆）

总开关：
    AGENT_ENABLE_MEMORY 环境变量控制，默认开启（向后兼容）。
    设为 "0"/"false"/"no" 时关闭整个 memory 系统。

注入约定：
    - 本代码库 MessageRole 无 SYSTEM（部分模型不支持），动态召回记忆按
      runtime.py additional_context 的既有约定，用 USER 消息 + [System Reminder] 前缀注入。
    - 静态记忆指令（行为指令 + MEMORY.md 索引）由 register_rule 注入 system prompt，
      本钩子只注入按 query 动态召回的相关主题文件内容，避免重复。

对标 Claude Code:
    - findRelevantMemories.ts（beforeModel 召回 + system-reminder 注入）
    - extractMemories.ts（handleStopHooks 抽取）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent.hooks import (
    AfterRunContext,
    BeforeModelContext,
    BeforeModelResult,
)
from agent.memory import memory_manager as mm
from agent.memory import memory_recall as mr
from agent.memory import memory_age as ma
from agent.types import (
    MessageRole,
    TextPart,
    ToolCallPart,
    create_text_message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 总开关 — 环境变量门控，默认开启
# ============================================================================

def memory_enabled() -> bool:
    """memory 总开关 — 默认开启，可通过 AGENT_ENABLE_MEMORY 关闭

    AGENT_ENABLE_MEMORY 取值 "0"/"false"/"no" 时关闭，其余（含未设置）开启。

    Returns:
        True 表示启用 memory 系统
    """
    return os.environ.get("AGENT_ENABLE_MEMORY", "1").lower() not in ("0", "false", "no")


# ============================================================================
# 辅助函数 — 从 snapshot 提取查询与最近工具
# ============================================================================


def _get_last_user_text(snapshot) -> str:
    """从 snapshot 取最后一条用户文本消息（作为召回 query）

    Args:
        snapshot: AgentRuntimeStateSnapshot

    Returns:
        最后一条用户文本；无则返回空字符串
    """
    for m in reversed(snapshot.messages):
        if m.role != MessageRole.USER:
            continue
        texts = [p.text for p in m.content if isinstance(p, TextPart) and p.text]
        if texts:
            return "\n".join(texts)
    return ""


def _get_recent_tools(snapshot, limit: int = 8) -> list[str]:
    """从 snapshot 提取最近用过的工具名 — 对齐 Claude Code recentTools

    用于召回选择器过滤"正在使用的工具的使用文档"，避免误召回。

    Args:
        snapshot: AgentRuntimeStateSnapshot
        limit: 最多返回的工具数

    Returns:
        最近用过的工具名列表（去重，按时间倒序）
    """
    tools: list[str] = []
    for m in reversed(snapshot.messages):
        if m.role != MessageRole.ASSISTANT:
            continue
        for p in m.content:
            if isinstance(p, ToolCallPart) and p.tool_name:
                if p.tool_name not in tools:
                    tools.append(p.tool_name)
        if len(tools) >= limit:
            break
    return tools


# ============================================================================
# before_model 钩子 — 动态召回相关记忆，注入 request.messages
# ============================================================================


async def memory_before_model_hook(ctx: BeforeModelContext) -> BeforeModelResult | None:
    """before_model 钩子 — 每次 query 首次调 LLM 前召回相关记忆

    对齐 Claude Code findRelevantMemories：
        - 仅主 agent 召回（子 agent 跳过）
        - 仅首轮迭代召回（避免每轮重复调用 DeepSeek 选择器）
        - 用 DeepSeek V4 Flash 选择相关主题文件，读取内容 + 时效标注，
          作为 [System Reminder] USER 消息追加到 request.messages

    Args:
        ctx: BeforeModelContext

    Returns:
        BeforeModelResult（追加记忆消息）或 None（无相关记忆/未启用）
    """
    if not memory_enabled():
        return None
    # 仅主 agent 召回
    if getattr(ctx.snapshot, "agent_role", None) == "subagent":
        return None
    # 仅首轮迭代召回，避免每轮重复调用选择器
    if getattr(ctx.snapshot, "iteration", 0) != 1:
        return None

    query = _get_last_user_text(ctx.snapshot)
    if not query:
        return None

    recent_tools = _get_recent_tools(ctx.snapshot)
    try:
        relevant = await mr.find_relevant_memories(
            query,
            recent_tools=recent_tools,
        )
    except Exception as e:
        logger.warning("memory_hooks: 召回相关记忆失败: %s", e)
        return None

    if not relevant:
        return None

    section = mr.build_recalled_memories_section(relevant)
    if not section.strip():
        return None

    reminder_msg = create_text_message(
        MessageRole.USER,
        f"[System Reminder] {section}",
        metadata={"kind": "memory_reminder"},
    )
    return BeforeModelResult(messages=list(ctx.request.messages) + [reminder_msg])


# ============================================================================
# after_run 钩子 — 抽取记忆（fire-and-forget）
# ============================================================================


async def memory_after_run_hook(ctx: AfterRunContext) -> None:
    """after_run 钩子 — 每次 query 结束后抽取新记忆

    对齐 Claude Code executeExtractMemories（handleStopHooks）：
        - 仅主 agent 抽取（子 agent 跳过，避免递归）
        - 受限子 agent 从本轮新增消息中抽取，best-effort 不阻塞主循环

    Args:
        ctx: AfterRunContext
    """
    if not memory_enabled():
        return
    # 仅主 agent 抽取，避免 sub-agent 递归触发
    if getattr(ctx.snapshot, "agent_role", None) == "subagent":
        return

    from agent.memory.memory_extract import (
        execute_extract_memories,
        get_memory_extractor,
        init_memory_extractor,
    )

    if get_memory_extractor() is None:
        init_memory_extractor(enabled=True)
    try:
        await execute_extract_memories(ctx.result)
    except Exception as e:
        logger.warning("memory_hooks: 抽取记忆失败: %s", e)