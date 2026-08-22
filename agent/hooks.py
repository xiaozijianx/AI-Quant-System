# -*- coding: utf-8 -*-
"""生命周期钩子系统 — 对标 Cline AgentRuntimeHooks + HookBag

9 个钩子点，AgentRuntime 在关键节点调用:

    before_run           — 运行开始前（可 stop 中止运行）
    after_run            — 运行结束后（无论成功/失败/中止）
    before_model         — 每次调 LLM 前（可修改 messages/tools/options，可 stop）
    after_model          — LLM 返回后（可 stop）
    before_tool          — 工具执行前（可 skip 跳过 / 修改 input / stop）
    after_tool           — 工具执行后（可修改 result / stop）
    prepare_turn_input   — 用户输入预处理（Phase 23 新增，可修改用户输入文本）
    format_user_input_block — 用户输入块格式化（Phase 23 新增，可注入上下文元数据）
    before_approval      — 工具审批前拦截（Phase 23 新增，可自动批准/拒绝）

典型用途:
    - before_model: 注入技能上下文、上下文压缩、修改 system prompt
    - before_tool: 权限控制、参数校验、日志记录
    - after_tool: 结果后处理、敏感信息过滤、使用量统计
    - prepare_turn_input: 用户输入预处理（如去除敏感信息、注入上下文标记）
    - format_user_input_block: 用户输入块格式化（如添加时间戳、工作目录等元数据）
    - before_approval: 审批前自动决策（如白名单命令自动批准）

对标 Cline 源码:
    - 接口定义: sdk/packages/shared/src/agent.ts L265-364
    - HookBag: sdk/packages/agents/src/agent-runtime.ts L229-237
    - 注册逻辑: agent-runtime.ts L544-554
    - 调用逻辑: agent-runtime.ts L796-809 (run hooks), L1067-1074 (model hooks),
                L1371-1393 (tool hooks), L1523-1538 (after tool hooks),
                L1208-1250 (prepareTurnInput), formatUserInputBlock
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable, Union

from agent.types import (
    AgentMessage,
    AgentModelRequest,
    AgentRunResult,
    AgentRuntimeStateSnapshot,
    AgentTool,
    AgentToolDefinition,
    AgentToolResult,
    ToolCallPart,
)


# ============================================================================
# 停止控制 — 对标 Cline AgentStopControl
# ============================================================================

@dataclass
class StopControl:
    """停止控制信号 — 对标 Cline AgentStopControl

    hook 返回此对象时，AgentRuntime 会中止运行。
    """
    stop: bool = False
    reason: str | None = None


# ============================================================================
# 钩子上下文 — 对标 Cline 的各种 Context 接口
# ============================================================================

@dataclass
class RunLifecycleContext:
    """运行生命周期上下文 — 对标 Cline AgentRunLifecycleContext

    before_run 和 after_run 共用的上下文。
    """
    snapshot: AgentRuntimeStateSnapshot


@dataclass
class AfterRunContext:
    """after_run 钩子上下文 — 对标 Cline RunLifecycleContext & { result }"""
    snapshot: AgentRuntimeStateSnapshot
    result: AgentRunResult


@dataclass
class BeforeModelContext:
    """before_model 钩子上下文 — 对标 Cline AgentBeforeModelContext

    Phase 26 修复: 增加 session_id，供 ContextCompactor 等需要会话隔离的钩子使用。
    Stage 11.2 (J12) 新增: abort_signal 字段，让 before_model 钩子（如 ContextCompactor
                  的 fallback 路径）能响应中止信号，避免中止后继续执行压缩流程。
    """
    snapshot: AgentRuntimeStateSnapshot
    request: AgentModelRequest
    session_id: str | None = None
    # Stage 11.2 (J12): 中止信号 — 对标 Cline compaction-runner.ts fallback 订阅 abort
    # None 时表示无中止信号可用（向后兼容），钩子可不检查
    abort_signal: Any = None


@dataclass
class BeforeModelResult:
    """before_model 钩子返回值 — 对标 Cline AgentBeforeModelResult

    可修改 LLM 请求的 messages/tools/options，或 stop 中止运行。
    """
    stop: bool = False
    reason: str | None = None
    messages: list[AgentMessage] | None = None
    tools: list[AgentToolDefinition] | None = None
    options: dict[str, Any] | None = None


@dataclass
class AfterModelContext:
    """after_model 钩子上下文 — 对标 Cline AgentAfterModelContext"""
    snapshot: AgentRuntimeStateSnapshot
    assistant_message: AgentMessage
    finish_reason: str


@dataclass
class BeforeToolContext:
    """before_tool 钩子上下文 — 对标 Cline AgentBeforeToolContext"""
    snapshot: AgentRuntimeStateSnapshot
    tool: AgentTool | None
    tool_call: ToolCallPart
    input: Any


@dataclass
class BeforeToolResult:
    """before_tool 钩子返回值 — 对标 Cline AgentBeforeToolResult

    skip=True 时跳过工具执行（返回 skip_reason 作为错误结果）。
    input 可覆盖工具输入参数。
    stop=True 时中止整个运行。
    policy 可覆盖 tool_policies 决策（Stage 5.7 新增，对标 Cline agent-runtime.ts L1381-1386
        的 policyOverride 合并），支持 {"enabled": False} / {"autoApprove": False} 等字段。
    additional_context 可注入上下文到模型对话（Stage 12.3 P9 新增，对标 Cline
        beforeTool hook 返回的 additionalContext），runtime 会将其作为 system message
        追加到 self._state.messages，LLM 下一轮能看到。
    """
    skip: bool = False
    stop: bool = False
    reason: str | None = None
    input: Any | None = None
    # Stage 5.7 (U2): 策略覆盖 — 对标 Cline AgentBeforeToolResult.policy
    policy: dict[str, Any] | None = None
    # Stage 12.3 (P9): 上下文注入 — 对标 Cline AgentBeforeToolResult.additionalContext
    # runtime 收到此字段后，作为 system message 追加到 messages
    additional_context: str | None = None


@dataclass
class AfterToolContext:
    """after_tool 钩子上下文 — 对标 Cline AgentAfterToolContext"""
    snapshot: AgentRuntimeStateSnapshot
    tool: AgentTool | None
    tool_call: ToolCallPart
    input: Any
    result: AgentToolResult
    started_at: datetime
    ended_at: datetime
    duration_ms: int


@dataclass
class AfterToolResult:
    """after_tool 钩子返回值 — 对标 Cline AgentAfterToolResult

    result 可覆盖工具执行结果（用于后处理/过滤）。
    stop=True 时中止整个运行。
    """
    stop: bool = False
    reason: str | None = None
    result: AgentToolResult | None = None


# ============================================================================
# Phase 23 新增钩子点 — 用户输入预处理 / 格式化 / 审批拦截
# ============================================================================


@dataclass
class PrepareTurnInputContext:
    """prepare_turn_input 钩子上下文 — Phase 23 新增，对标 Cline prepareTurnInput

    在用户输入进入主循环前调用，可修改输入文本。
    典型用途:
        - 去除敏感信息（如 API key）
        - 注入上下文标记（如当前文件、选中文本）
        - 规范化输入格式
    """
    snapshot: AgentRuntimeStateSnapshot
    user_input: str  # 原始用户输入文本


@dataclass
class PrepareTurnInputResult:
    """prepare_turn_input 钩子返回值 — Phase 23 新增

    modified_input 可覆盖用户输入文本（None 表示不修改）。
    stop=True 时中止整个运行（如检测到禁止内容）。
    """
    stop: bool = False
    reason: str | None = None
    modified_input: str | None = None


@dataclass
class FormatUserInputBlockContext:
    """format_user_input_block 钩子上下文 — Phase 23 新增，对标 Cline formatUserInputBlock

    在用户消息添加到历史前调用，可注入元数据/上下文。
    与 prepare_turn_input 的区别:
        - prepare_turn_input 修改用户输入文本本身
        - format_user_input_block 在输入文本外包裹元数据（如时间戳、环境信息）

    典型用途:
        - 添加工作目录、时间戳等环境信息
        - 注入选中文本、当前文件等 IDE 上下文
        - 添加用户偏好/记忆
    """
    snapshot: AgentRuntimeStateSnapshot
    user_input: str  # 已经过 prepare_turn_input 处理的输入文本
    formatted_block: str  # 当前格式化后的文本块（可进一步修改）


@dataclass
class FormatUserInputBlockResult:
    """format_user_input_block 钩子返回值 — Phase 23 新增

    modified_block 可覆盖格式化后的文本块（None 表示不修改）。
    """
    modified_block: str | None = None


@dataclass
class BeforeApprovalContext:
    """before_approval 钩子上下文 — Phase 23 新增，对标 Cline 审批钩子

    在工具审批请求发出前调用，可自动决策（跳过用户审批）。
    典型用途:
        - 白名单命令自动批准（如 ls / cat / git status 等只读命令）
        - 黑名单命令自动拒绝（如 rm -rf / drop database）
        - 基于用户配置的自动审批规则
    """
    snapshot: AgentRuntimeStateSnapshot
    tool_name: str
    tool_call_id: str
    input: dict[str, Any]


@dataclass
class BeforeApprovalResult:
    """before_approval 钩子返回值 — Phase 23 新增

    decision 可取值:
        - None: 不决策，继续走默认审批流程（等待用户）
        - "approved": 自动批准，跳过用户审批
        - "denied": 自动拒绝，工具不执行
    reason 为决策原因（用于日志）。
    """
    decision: str | None = None  # None / "approved" / "denied"
    reason: str | None = None


# ============================================================================
# 钩子函数类型
# ============================================================================

# 每个钩子是同步或异步函数，返回对应结果类型或 None
BeforeRunHook = Callable[[RunLifecycleContext], Union[StopControl, None, Awaitable[Union[StopControl, None]]]]
AfterRunHook = Callable[[AfterRunContext], Union[None, Awaitable[None]]]
BeforeModelHook = Callable[[BeforeModelContext], Union[BeforeModelResult, None, Awaitable[Union[BeforeModelResult, None]]]]
AfterModelHook = Callable[[AfterModelContext], Union[StopControl, None, Awaitable[Union[StopControl, None]]]]
BeforeToolHook = Callable[[BeforeToolContext], Union[BeforeToolResult, None, Awaitable[Union[BeforeToolResult, None]]]]
AfterToolHook = Callable[[AfterToolContext], Union[AfterToolResult, None, Awaitable[Union[AfterToolResult, None]]]]
# Phase 23 新增钩子类型
PrepareTurnInputHook = Callable[[PrepareTurnInputContext], Union[PrepareTurnInputResult, None, Awaitable[Union[PrepareTurnInputResult, None]]]]
FormatUserInputBlockHook = Callable[[FormatUserInputBlockContext], Union[FormatUserInputBlockResult, None, Awaitable[Union[FormatUserInputBlockResult, None]]]]
BeforeApprovalHook = Callable[[BeforeApprovalContext], Union[BeforeApprovalResult, None, Awaitable[Union[BeforeApprovalResult, None]]]]


@dataclass
class AgentHooks:
    """Agent 钩子集合 — 对标 Cline AgentRuntimeHooks

    每个字段是可选的，只需实现需要的钩子。
    通过 AgentRuntime.register_hooks() 注册。

    Phase 23 新增: prepare_turn_input / format_user_input_block / before_approval

    用法:
        hooks = AgentHooks(
            before_model=my_context_compaction,
            before_tool=my_permission_check,
            prepare_turn_input=my_input_sanitizer,
            before_approval=my_auto_approval_rules,
        )
        runtime.register_hooks(hooks)
    """
    before_run: BeforeRunHook | None = None
    after_run: AfterRunHook | None = None
    before_model: BeforeModelHook | None = None
    after_model: AfterModelHook | None = None
    before_tool: BeforeToolHook | None = None
    after_tool: AfterToolHook | None = None
    # Phase 23 新增
    prepare_turn_input: PrepareTurnInputHook | None = None
    format_user_input_block: FormatUserInputBlockHook | None = None
    before_approval: BeforeApprovalHook | None = None


# ============================================================================
# HookBag — 对标 Cline agent-runtime.ts L229-237 HookBag
# ============================================================================

class HookBag:
    """钩子容器 — 对标 Cline HookBag

    管理所有已注册的钩子，按类型分组存储。
    AgentRuntime 内部使用此类管理钩子。

    Phase 23 新增: prepare_turn_input / format_user_input_block / before_approval
    """

    def __init__(self) -> None:
        self.before_run: list[BeforeRunHook] = []
        self.after_run: list[AfterRunHook] = []
        self.before_model: list[BeforeModelHook] = []
        self.after_model: list[AfterModelHook] = []
        self.before_tool: list[BeforeToolHook] = []
        self.after_tool: list[AfterToolHook] = []
        # Phase 23 新增
        self.prepare_turn_input: list[PrepareTurnInputHook] = []
        self.format_user_input_block: list[FormatUserInputBlockHook] = []
        self.before_approval: list[BeforeApprovalHook] = []

    def add(self, hooks: AgentHooks) -> None:
        """注册一组钩子 — 对标 Cline registerHooks() L544-554"""
        if hooks.before_run is not None:
            self.before_run.append(hooks.before_run)
        if hooks.after_run is not None:
            self.after_run.append(hooks.after_run)
        if hooks.before_model is not None:
            self.before_model.append(hooks.before_model)
        if hooks.after_model is not None:
            self.after_model.append(hooks.after_model)
        if hooks.before_tool is not None:
            self.before_tool.append(hooks.before_tool)
        if hooks.after_tool is not None:
            self.after_tool.append(hooks.after_tool)
        # Phase 23 新增
        if hooks.prepare_turn_input is not None:
            self.prepare_turn_input.append(hooks.prepare_turn_input)
        if hooks.format_user_input_block is not None:
            self.format_user_input_block.append(hooks.format_user_input_block)
        if hooks.before_approval is not None:
            self.before_approval.append(hooks.before_approval)

    def clear(self) -> None:
        """清空所有钩子"""
        self.before_run.clear()
        self.after_run.clear()
        self.before_model.clear()
        self.after_model.clear()
        self.before_tool.clear()
        self.after_tool.clear()
        # Phase 23 新增
        self.prepare_turn_input.clear()
        self.format_user_input_block.clear()
        self.before_approval.clear()

    @property
    def is_empty(self) -> bool:
        """是否没有任何钩子"""
        return (
            not self.before_run
            and not self.after_run
            and not self.before_model
            and not self.after_model
            and not self.before_tool
            and not self.after_tool
            and not self.prepare_turn_input
            and not self.format_user_input_block
            and not self.before_approval
        )
