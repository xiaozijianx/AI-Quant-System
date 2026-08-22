# -*- coding: utf-8 -*-
"""AgentModel 协议和消息转换工具 — 对标 Cline gateway provider format.ts

AgentModel 协议定义在 agent/types.py 中，此文件提供:
    1. 从 types.py 导出 AgentModel 协议
    2. AgentMessage → OpenAI 消息格式的转换工具
    3. AgentToolDefinition → OpenAI function calling 格式的转换工具

这些转换工具被各 provider 共用（Qwen / OpenAI / 其他兼容 API）。
"""

from __future__ import annotations

import json
from typing import Any

from agent.types import (
    AgentMessage,
    AgentToolDefinition,
    ImagePart,
    MessageRole,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)

# 从 types.py 导出 AgentModel 协议
from agent.types import AgentModel, AgentModelEvent, AgentModelFinishReason, AgentModelRequest


# ============================================================================
# 能力降级 — Stage 13.1 (R5) 新增，对标 Cline llm-gateway.ts capability downgrade
# ============================================================================

# 能力常量 — 对标 Cline ProviderCapability
CAPABILITY_TOOL_CALLS = "tools"
CAPABILITY_VISION = "vision"
CAPABILITY_REASONING = "reasoning"
CAPABILITY_STREAMING = "streaming"


def apply_capability_downgrade(request: AgentModelRequest) -> AgentModelRequest:
    """根据 capabilities 降级 request 中的 content — Stage 13.1 (R5) 新增

    对标 Cline llm-gateway.ts 中的能力降级逻辑：
        - 无 vision 能力时，将 ImagePart 降级为文本描述 [image: alt_text]
        - 无 reasoning 能力时，丢弃 ReasoningPart（不传给 LLM）
        - 无 tools 能力时，tools 字段置空（让 LLM 用文本描述操作意图）

    降级在 request 副本上进行，不修改原 request（避免影响压缩历史）。

    Args:
        request: 原始请求

    Returns:
        降级后的新请求（原 request 不变）
    """
    caps = request.capabilities

    # 无能力约束时直接返回原 request（向后兼容，无拷贝开销）
    if not caps:
        return request

    # 判断是否需要降级
    need_vision_downgrade = CAPABILITY_VISION not in caps
    need_reasoning_downgrade = CAPABILITY_REASONING not in caps
    need_tools_downgrade = CAPABILITY_TOOL_CALLS not in caps

    # 若全部能力都在 caps 中，无需降级
    if not (need_vision_downgrade or need_reasoning_downgrade or need_tools_downgrade):
        return request

    # 构造降级后的新 request（深拷贝 messages，避免修改原 request）
    import copy
    new_request = AgentModelRequest(
        system_prompt=request.system_prompt,
        messages=copy.deepcopy(request.messages),
        tools=list(request.tools) if not need_tools_downgrade else [],
        options=dict(request.options),
        capabilities=list(request.capabilities),
    )

    # tools 降级：无 tools 能力时，在 system_prompt 追加提示
    if need_tools_downgrade and request.tools:
        tools_hint = (
            "\n\n[能力提示] 当前模型不支持工具调用，请用文本描述你想执行的操作。"
        )
        new_request.system_prompt = (new_request.system_prompt or "") + tools_hint

    # messages 内容降级
    for msg in new_request.messages:
        if not msg.content:
            continue
        new_content: list = []
        for part in msg.content:
            # vision 降级：ImagePart → TextPart
            if isinstance(part, ImagePart) and need_vision_downgrade:
                alt = part.alt_text or "image"
                new_content.append(TextPart(text=f"[image: {alt}]"))
                continue
            # reasoning 降级：丢弃 ReasoningPart
            if isinstance(part, ReasoningPart) and need_reasoning_downgrade:
                continue
            new_content.append(part)
        msg.content = new_content

    return new_request


# ============================================================================
# 消息转换: AgentMessage → OpenAI 格式 — 对标 Cline format.ts
# ============================================================================

# 对标 Cline message-builder.ts MISSING_TOOL_RESULT_TEXT：
# 工具执行被中断未产出结果时的占位提示文案
MISSING_TOOL_RESULT_TEXT = "Tool execution was interrupted before a result was produced."


def _repair_missing_tool_messages(messages: list[AgentMessage]) -> list[AgentMessage]:
    """补齐缺失的工具结果消息 — 对标 Cline message-builder.ts addMissingToolResults()

    当某个 assistant 消息带有 tool_calls，但历史里缺少对应的 tool 响应消息时
    （例如工具执行被中断 / 并行执行异常 / 从中间态检查点恢复），发给 OpenAI
    兼容 API 会报 400：
        "An assistant message with 'tool_calls' must be followed by tool messages
         responding to each 'tool_call_id'"

    Cline 的处理不是删除该 assistant 消息，而是在其后追加一个占位的错误 tool
    结果消息（is_error=True），保证每个 tool_call 都有响应，同时保留 assistant
    消息让模型能看到自己发起的（被中断的）工具调用。
    """
    if not messages:
        return messages

    # 收集历史里所有已有响应的 tool_call_id（对标 Cline collectToolResultIds）
    answered_ids = {
        part.tool_call_id
        for msg in messages
        if msg.role == MessageRole.TOOL
        for part in msg.content
        if isinstance(part, ToolResultPart)
    }

    result: list[AgentMessage] = []
    for msg in messages:
        result.append(msg)
        if msg.role != MessageRole.ASSISTANT:
            continue
        # 找出该 assistant 消息里缺少响应的工具调用
        missing = [
            part
            for part in msg.content
            if isinstance(part, ToolCallPart) and part.tool_call_id not in answered_ids
        ]
        if not missing:
            continue
        # 追加占位错误工具结果（对标 Cline createMissingToolResultBlocks）
        result.append(
            AgentMessage(
                role=MessageRole.TOOL,
                content=[
                    ToolResultPart(
                        tool_call_id=part.tool_call_id,
                        tool_name=part.tool_name,
                        output={
                            "error": f"{MISSING_TOOL_RESULT_TEXT} Tool: {part.tool_name}."
                        },
                        is_error=True,
                    )
                    for part in missing
                ],
            )
        )
    return result

def agent_messages_to_openai(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """将 AgentMessage 列表转为 OpenAI Chat API 消息格式

    对标 Cline format.ts 中的消息转换逻辑。

    转换规则:
        - user 消息: {"role": "user", "content": text}
        - assistant 消息:
            {"role": "assistant", "content": text, "tool_calls": [...]}
            （如果只有 reasoning 无 text，content 设为 None）
        - tool 消息: {"role": "tool", "tool_call_id": ..., "content": output}

    序列化前先补齐缺失的工具结果消息（对标 Cline addMissingToolResults），
    避免孤立 tool_calls 导致 OpenAI 400 错误。
    """
    messages = _repair_missing_tool_messages(messages)
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == MessageRole.USER:
            text = _extract_text(msg)
            result.append({"role": "user", "content": text})

        elif msg.role == MessageRole.ASSISTANT:
            entry: dict[str, Any] = {"role": "assistant"}
            text = _extract_text(msg)
            # Qwen/OpenAI API 要求 content 字段存在且为字符串（不能为 None）。
            # 当 assistant 消息只有 tool_calls 或只有 reasoning 时，用空字符串占位。
            entry["content"] = text if text else ""
            tool_calls = [
                part for part in msg.content
                if isinstance(part, ToolCallPart)
            ]
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(
                                tc.input, ensure_ascii=False
                            ) if tc.input else "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            result.append(entry)

        elif msg.role == MessageRole.TOOL:
            for part in msg.content:
                if isinstance(part, ToolResultPart):
                    output = part.output
                    if not isinstance(output, str):
                        output = json.dumps(output, ensure_ascii=False)
                    result.append({
                        "role": "tool",
                        "tool_call_id": part.tool_call_id,
                        "content": output,
                    })

    return result


def _extract_text(message: AgentMessage) -> str:
    """从消息中提取文本片段（TextPart + ReasoningPart）"""
    parts = []
    for part in message.content:
        if isinstance(part, TextPart):
            parts.append(part.text)
        elif isinstance(part, ReasoningPart):
            # reasoning 不放入 OpenAI content（Qwen reasoning_content 是独立字段）
            # 这里只提取 TextPart
            pass
    return "".join(parts)


# ============================================================================
# 工具转换: AgentToolDefinition → OpenAI function calling 格式
# ============================================================================

def tools_to_openai(tools: list[AgentToolDefinition]) -> list[dict[str, Any]]:
    """将 AgentToolDefinition 列表转为 OpenAI function calling 格式

    对标 Cline format.ts 中的工具转换逻辑。

    格式:
        {
            "type": "function",
            "function": {
                "name": "exec",
                "description": "执行脚本",
                "parameters": { JSON Schema }
            }
        }
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


# ============================================================================
# OpenAI finish_reason → AgentModelFinishReason 映射
# ============================================================================

_FINISH_REASON_MAP = {
    "stop": AgentModelFinishReason.STOP,
    "tool_calls": AgentModelFinishReason.TOOL_CALLS,
    "length": AgentModelFinishReason.MAX_TOKENS,
    "max_tokens": AgentModelFinishReason.MAX_TOKENS,
    "content_filter": AgentModelFinishReason.ERROR,
}


def map_finish_reason(reason: str | None) -> AgentModelFinishReason:
    """将 OpenAI finish_reason 映射为 AgentModelFinishReason

    对标 Cline stream.ts 中的 finish reason 映射。
    """
    if reason is None:
        return AgentModelFinishReason.STOP
    return _FINISH_REASON_MAP.get(reason, AgentModelFinishReason.STOP)
