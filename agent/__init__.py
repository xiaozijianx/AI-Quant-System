# -*- coding: utf-8 -*-
"""Agent 引擎包 — 对标 Cline SDK 架构，用 Python 实现核心 Agent 运行时。

主要组件:
    - types: 核心类型定义（消息、工具、模型、事件、状态）
    - events: 事件系统（EventEmitter + 事件类型常量）
    - hooks: 生命周期钩子（before_run/after_run/before_model/after_model/before_tool/after_tool）
    - runtime: AgentRuntime 主循环
    - prompt: 系统提示分层构造器
    - context: 上下文管理（压缩/预算）
    - providers: LLM 适配层（Qwen 等）
    - tools: 工具系统（exec/file/web/skill）
    - skills: 技能系统（渐进式加载）
"""

from agent.types import (
    # 消息类型
    MessageRole,
    TextPart,
    ReasoningPart,
    ToolCallPart,
    ToolResultPart,
    AgentMessage,
    # 工具类型
    ToolLifecycle,
    AgentToolDefinition,
    AgentToolResult,
    AgentToolContext,
    AgentTool,
    # 模型类型
    AgentModelRequest,
    AgentModelFinishReason,
    AgentModelEvent,
    AgentModel,
    # 运行时状态
    AgentUsage,
    AgentRuntimeStateSnapshot,
    AgentRunResult,
    AgentRuntimeConfig,
)

from agent.events import (
    EventEmitter,
    AgentEvent,
    # 事件类型常量
    RUN_STARTED,
    TURN_STARTED,
    ASSISTANT_TEXT_DELTA,
    ASSISTANT_REASONING_DELTA,
    MESSAGE_ADDED,
    TURN_FINISHED,
    RUN_FINISHED,
    RUN_FAILED,
    TOOL_EXECUTION_STARTED,
    TOOL_EXECUTION_FINISHED,
    USAGE_UPDATED,
    STATUS_NOTICE,
)

from agent.hooks import (
    AgentHooks,
    HookBag,
    StopControl,
    RunLifecycleContext,
    AfterRunContext,
    BeforeModelContext,
    BeforeModelResult,
    AfterModelContext,
    BeforeToolContext,
    BeforeToolResult,
    AfterToolContext,
    AfterToolResult,
)

from agent.runtime import AgentRuntime

__all__ = [
    # types
    "MessageRole", "TextPart", "ReasoningPart", "ToolCallPart", "ToolResultPart",
    "AgentMessage",
    "ToolLifecycle", "AgentToolDefinition", "AgentToolResult", "AgentToolContext", "AgentTool",
    "AgentModelRequest", "AgentModelFinishReason", "AgentModelEvent", "AgentModel",
    "AgentUsage", "AgentRuntimeStateSnapshot", "AgentRunResult", "AgentRuntimeConfig",
    # events
    "EventEmitter", "AgentEvent",
    "RUN_STARTED", "TURN_STARTED", "ASSISTANT_TEXT_DELTA", "ASSISTANT_REASONING_DELTA",
    "MESSAGE_ADDED", "TURN_FINISHED", "RUN_FINISHED", "RUN_FAILED",
    "TOOL_EXECUTION_STARTED", "TOOL_EXECUTION_FINISHED", "USAGE_UPDATED", "STATUS_NOTICE",
    # hooks
    "AgentHooks", "HookBag", "StopControl",
    "RunLifecycleContext", "AfterRunContext",
    "BeforeModelContext", "BeforeModelResult", "AfterModelContext",
    "BeforeToolContext", "BeforeToolResult", "AfterToolContext", "AfterToolResult",
    # runtime
    "AgentRuntime",
]
