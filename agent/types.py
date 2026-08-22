# -*- coding: utf-8 -*-
"""核心类型定义 — 对标 Cline SDK @cline/shared/agent.ts

定义 Agent 引擎全部核心数据结构和协议接口:
    - 消息类型: AgentMessage, TextPart, ReasoningPart, ToolCallPart, ToolResultPart
    - 工具类型: AgentToolDefinition, AgentToolResult, AgentToolContext, AgentTool
    - 模型类型: AgentModelRequest, AgentModelEvent, AgentModel
    - 运行时状态: AgentUsage, AgentRuntimeStateSnapshot, AgentRunResult, AgentRuntimeConfig

所有后续模块（runtime / hooks / providers / tools / skills）都依赖此文件。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol, runtime_checkable


# ============================================================================
# 消息类型 — 对标 Cline AgentMessage / AgentMessagePart
# ============================================================================

class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class TextPart:
    """文本消息片段 — 对标 Cline AgentMessagePart text 类型

    LLM 输出的正文内容，最终展示给用户的回答。
    """
    type: str = field(default="text", init=False, repr=False)
    text: str = ""


@dataclass
class ReasoningPart:
    """推理/思考过程片段 — 对标 Cline AgentMessagePart reasoning 类型

    LLM 的思考过程（如 Qwen 的 reasoning_content），
    与 TextPart 分离以便前端区分展示。
    """
    type: str = field(default="reasoning", init=False, repr=False)
    text: str = ""
    redacted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallPart:
    """工具调用片段 — 对标 Cline AgentMessagePart tool-call 类型

    LLM 发起的工具调用请求，包含工具名和输入参数。
    """
    type: str = field(default="tool-call", init=False, repr=False)
    tool_call_id: str = ""
    tool_name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultPart:
    """工具结果片段 — 对标 Cline AgentMessagePart tool-result 类型

    工具执行后的返回结果，会作为 tool 角色消息发回 LLM。
    """
    type: str = field(default="tool-result", init=False, repr=False)
    tool_call_id: str = ""
    tool_name: str = ""
    output: Any = None
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImagePart:
    """图片消息片段 — 对标 Cline AgentImagePart (agent.ts L37-41)

    用于承载用户上传的图片输入（如 K 线截图分析），
    image 字段支持 base64 字符串或原始字节。
    provider 暂未处理，后续接入多模态时扩展。

    Stage 11.4 (J18) 新增:
        - truncated: 是否被截断（image_data 超过阈值时清空，保留 alt_text）
        - truncate_reason: 截断原因（"image_data_exceeds_limit"）
        - alt_text: 图片替代文本（截断后让 LLM 知道图片存在但数据被丢弃）
        默认值 False / "" / "" 保证向后兼容
    """
    type: str = field(default="image", init=False, repr=False)
    image: str | bytes = b""
    media_type: str | None = None  # image/png 等
    # Stage 11.4 (J18): 截断标记 — 对标 Cline compaction-truncator.ts
    alt_text: str = ""
    truncated: bool = False
    truncate_reason: str = ""


@dataclass
class FilePart:
    """文件消息片段 — 对标 Cline AgentFilePart (agent.ts L43-47)

    用于承载用户上传的文件附件内容，
    与 read_files 工具不同：FilePart 是直接进 message 的文件内容。
    provider 暂未处理，后续按需扩展。

    Stage 11.4 (J18) 新增:
        - truncated: 是否被截断（content 超过阈值时清空，保留 path）
        - truncate_reason: 截断原因（"file_data_exceeds_limit"）
        默认值 False / "" 保证向后兼容
    """
    type: str = field(default="file", init=False, repr=False)
    path: str = ""
    content: str = ""
    # Stage 11.4 (J18): 截断标记 — 对标 Cline compaction-truncator.ts
    truncated: bool = False
    truncate_reason: str = ""


# 消息片段联合类型 — 对标 Cline AgentMessagePart (agent.ts L65-71)
# Phase 2.2: 补齐 ImagePart / FilePart，联合类型从 4 种扩展到 6 种
MessagePart = TextPart | ReasoningPart | ImagePart | FilePart | ToolCallPart | ToolResultPart


@dataclass
class AgentMessage:
    """Agent 消息 — 对标 Cline AgentMessage

    一条消息包含角色、内容片段列表、创建时间和元数据。
    assistant 消息的 content 可以同时包含 text/reasoning/tool-call 片段。
    tool 消息的 content 包含 tool-result 片段。
    """
    role: MessageRole
    content: list[MessagePart] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    metadata: dict[str, Any] = field(default_factory=dict)
    # 模型信息（仅 assistant 消息）
    model_info: dict[str, str] | None = None
    # token 用量（仅 assistant 消息）
    metrics: dict[str, Any] | None = None


# ============================================================================
# 工具类型 — 对标 Cline AgentToolDefinition / AgentTool / AgentToolResult
# ============================================================================

@dataclass
class ToolLifecycle:
    """工具生命周期标记 — 对标 Cline ToolLifecycle

    completes_run=True 的工具执行成功后，AgentRuntime 直接结束运行。
    用于 attempt_completion / submit_and_exit 等终止性工具。
    """
    completes_run: bool = False


@dataclass
class AgentToolDefinition:
    """工具静态定义 — 对标 Cline AgentToolDefinition

    传递给 LLM 的工具描述信息，LLM 据此决定是否调用工具。
    """
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema 格式
    lifecycle: ToolLifecycle | None = None


@dataclass
class AgentToolResult:
    """工具执行结果 — 对标 Cline AgentToolResult

    工具 execute() 方法的返回值，output 会被序列化为 tool-result 消息。
    """
    output: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentToolContext:
    """工具执行上下文 — 对标 Cline AgentToolContext

    传递给工具 execute() 方法的上下文信息，包含运行时状态和回调。

    Stage 10.5 (A7) 新增:
        - metadata: 工具运行时元数据 dict，由 AgentRuntime 填充
          工具可通过 context.metadata.get(key) 读取运行时上下文做行为决策
          标准键名见 AGENT_TOOL_METADATA_KEYS（run_id/iteration/trigger_source 等）
          metadata 是只读上下文，工具不应修改；不参与序列化（不写入会话 JSON）
    """
    agent_id: str = ""
    session_id: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    iteration: int = 0
    tool_call_id: str | None = None
    snapshot: AgentRuntimeStateSnapshot | None = None  # 前向引用，运行时填充
    emit_update: Callable[[Any], None] | None = None
    abort_signal: Any = None  # Phase 28.2: asyncio.Event，工具可选择性检查以响应中止
    # Stage 10.5 (A7): 工具运行时元数据 — 对标 Cline AgentToolContext.metadata
    # 默认空 dict，由 AgentRuntime._prepare_tool_execution 填充标准键名
    # 工具按需读取，不强制；保持现有工具兼容（默认不读 metadata）
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentTool(Protocol):
    """可执行工具协议 — 对标 Cline AgentTool

    每个工具需实现此协议: 提供静态定义 + execute 方法。
    BaseTool（Phase 4）会提供更完整的基类实现。
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    @property
    def lifecycle(self) -> ToolLifecycle | None: ...

    timeout_ms: int | None
    retryable: bool
    max_retries: int

    async def execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult: ...

    def to_definition(self) -> AgentToolDefinition: ...


# ============================================================================
# 模型类型 — 对标 Cline AgentModelRequest / AgentModelEvent / AgentModel
# ============================================================================

@dataclass
class AgentModelRequest:
    """LLM 请求 — 对标 Cline AgentModelRequest

    AgentRuntime 每轮迭代构建此请求发给 LLM。

    Stage 13.1 (R5) 新增:
        capabilities: 模型能力列表（如 ["tool_calls", "vision", "reasoning"]），
                      供 Provider 在 stream_chat 中做能力降级。
                      默认空 list（无能力约束，向后兼容）。
    """
    system_prompt: str | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    tools: list[AgentToolDefinition] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    # Stage 13.1 (R5): 模型能力列表 — 对标 Cline AgentModelRequest.capabilities
    capabilities: list[str] = field(default_factory=list)


class AgentModelFinishReason(str, Enum):
    """LLM 完成原因 — 对标 Cline AgentModelFinishReason"""
    STOP = "stop"                  # 正常结束（无工具调用）
    TOOL_CALLS = "tool-calls"      # 请求工具调用
    MAX_TOKENS = "max-tokens"      # 达到最大 token 数
    ABORTED = "aborted"            # 被中止
    ERROR = "error"                # 出错


@dataclass
class AgentModelEvent:
    """LLM 流式事件 — 对标 Cline AgentModelEvent

    AgentModel.stream() 产出的事件流，AgentRuntime 消费后转为 AgentRuntimeEvent。

    事件类型:
        - text-delta: 文本增量（最终回答）
        - reasoning-delta: 推理增量（思考过程）
        - tool-call-delta: 工具调用增量（逐步组装工具调用）
        - usage: token 用量
        - finish: 流结束
    """
    type: str
    # text-delta / reasoning-delta
    text: str | None = None
    # reasoning-delta
    redacted: bool | None = None
    # tool-call-delta
    index: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    input_text: str | None = None
    input_value: Any | None = None
    # usage
    usage: dict[str, int] | None = None
    # finish
    reason: AgentModelFinishReason | None = None
    error: str | None = None
    # 通用元数据
    metadata: Any | None = None


@runtime_checkable
class AgentModel(Protocol):
    """LLM 适配器协议 — 对标 Cline AgentModel

    每个 LLM provider（Qwen / OpenAI / Anthropic）实现此协议。
    核心方法 stream() 返回异步事件流。
    """

    async def stream(
        self,
        request: AgentModelRequest,
        abort_signal: Any = None,
    ) -> AsyncIterator[AgentModelEvent]: ...


# ============================================================================
# 运行时状态 — 对标 Cline AgentUsage / AgentRuntimeStateSnapshot / AgentRunResult
# ============================================================================

@dataclass
class AgentUsage:
    """token 用量 — 对标 Cline AgentUsage"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_token_count: int = 0
    total_cost: float = 0.0

    def add(self, other: dict[str, int]) -> None:
        """累加 token 用量"""
        self.input_tokens += other.get("input_tokens", 0)
        self.output_tokens += other.get("output_tokens", 0)
        self.cache_read_tokens += other.get("cache_read_tokens", 0)
        self.cache_write_tokens += other.get("cache_write_tokens", 0)
        self.reasoning_token_count += other.get("reasoning_token_count", 0)
        self.total_cost += other.get("total_cost", 0.0)

    def to_dict(self) -> dict[str, int | float]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_token_count": self.reasoning_token_count,
            "total_cost": self.total_cost,
        }


@dataclass
class LoopDetectionConfig:
    """循环检测配置 — 对标 Cline LoopDetectionConfig

    soft_threshold: 连续相同调用达到此阈值时记录软警告
    hard_threshold: 连续相同调用达到此阈值时中止运行
    """
    soft_threshold: int = 3
    hard_threshold: int = 5


@dataclass
class AgentRuntimeStateSnapshot:
    """运行时状态快照 — 对标 Cline AgentRuntimeStateSnapshot

    AgentRuntime 在任意时刻的状态快照，供 hooks 和 UI 查询。
    Phase 2.3 A20: messages / pending_tool_calls 改为 tuple（只读视图），
                    对标 Cline readonly AgentMessage[]，防止 listener 误修改内部状态。
    Stage 11.3 (J13) 新增:
        - compaction: 压缩状态快照，None 表示无压缩活动
          压缩进行中由 CompactionStateManager.project() 填充
          前端从事件中读取 snapshot.compaction 显示压缩进度
    """
    agent_id: str = ""
    agent_role: str | None = None
    parent_agent_id: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    status: str = "idle"  # idle / running / completed / aborted / failed
    iteration: int = 0
    messages: tuple[AgentMessage, ...] = field(default_factory=tuple)
    pending_tool_calls: tuple[str, ...] = field(default_factory=tuple)
    usage: AgentUsage = field(default_factory=AgentUsage)
    last_error: str | None = None
    # Stage 11.3 (J13): 压缩状态快照 — 对标 Cline CompactionStateManager.project()
    # 默认 None（无压缩活动时），由 ContextCompactor 在压缩生命周期中填充
    compaction: "CompactionStateSnapshot | None" = None


@dataclass(frozen=True)
class CompactionStateSnapshot:
    """压缩状态快照 — Stage 11.3 (J13) 新增，对标 Cline CompactionStateManager.project()

    CompactionStateManager.project() 返回此快照，供前端显示压缩进度。
    frozen=True 保证不可变，与 AgentRuntimeStateSnapshot 语义一致，避免前端误改。

    Attributes:
        original_count: 原始消息数（压缩前）
        compacted_count: 压缩后消息数
        discarded_count: 被丢弃的消息数（original - compacted - 1，1 为摘要消息）
        elapsed_ms: 压缩耗时（毫秒）
        status: 压缩状态（"pending" / "running" / "completed" / "failed"）
        system_prompt_preserved: system_prompt 是否被保留（True 表示未参与压缩）
    """
    original_count: int = 0
    compacted_count: int = 0
    discarded_count: int = 0
    elapsed_ms: int = 0
    status: str = "pending"
    system_prompt_preserved: bool = False


@dataclass
class AgentRunResult:
    """运行结果 — 对标 Cline AgentRunResult

    AgentRuntime.run() 的返回值，包含最终输出、消息历史、用量等。

    Stage 10.4 (B33) 新增:
        - finish_reason: 完成原因，前端根据值显示不同图标和文案
          取值: "stop" / "tool_calls" / "max_iterations" / "aborted" /
                "error" / "controlled_stop"
          - controlled_stop: hook 主动 stop（非失败），黄色图标"被规则拦截"
          - stop: 正常完成，绿色图标
          - aborted: 用户中止，灰色图标
          - error: 运行失败，红色图标
    """
    agent_id: str = ""
    agent_role: str | None = None
    run_id: str = ""
    status: str = "completed"  # completed / aborted / failed
    iterations: int = 0
    output_text: str | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)
    error: Exception | None = None
    # Stage 10.4 (B33): 完成原因 — 对标 Cline AgentRunResult.finishReason
    # 默认 "stop"（正常完成），由 runtime 根据退出路径填充
    finish_reason: str = "stop"


# ============================================================================
# Stage 10.4 (B33): ControlledStopError 异常 — 对标 Cline ControlledStopError
# ============================================================================


class ControlledStopError(Exception):
    """受控停止异常 — Stage 10.4 (B33) 新增，对标 Cline ControlledStopError

    hook 主动 stop（如用户配置的拦截规则）时抛出此异常。
    与 RuntimeError 区分：hook stop 是受控停止，不是失败。

    主循环 catch 后:
        - status = "completed"（非 "failed"）
        - finish_reason = "controlled_stop"
        - 发射 run_finished 事件（非 run_failed）

    设计说明:
        - 不继承 RuntimeError，避免与现有 except RuntimeError 冲突
        - source 字段记录触发来源，便于前端展示
          "hook" / "policy" / "user"

    Attributes:
        reason: 停止原因（人类可读）
        source: 触发来源（"hook" / "policy" / "user"）
    """

    def __init__(self, reason: str = "", source: str = "hook") -> None:
        self.reason = reason
        self.source = source
        super().__init__(reason or "controlled stop")


# ============================================================================
# 运行时配置 — 对标 Cline AgentRuntimeConfig
# ============================================================================

@dataclass
class CompletionPolicy:
    """完成策略 — 对标 Cline AgentRuntimeConfig.completionPolicy

    控制 agent 在没有调用完成工具时是否结束运行。

    Attributes:
        require_completion_tool: 为 True 时，agent 必须调用 attempt_completion /
            submit_and_exit 等 completes_run 工具才能结束运行；若 LLM 直接返回
            文本而不调用完成工具，runtime 会追加 reminder 继续下一轮。
        completion_guard: 可选 guard 函数，返回非空字符串时作为提醒内容插入
            下一轮用户消息前，提示 agent 继续完成工具调用。
    """
    require_completion_tool: bool = False
    completion_guard: Callable[[], str | None] | None = None


@dataclass
class AgentRuntimeConfig:
    """AgentRuntime 配置 — 对标 Cline AgentRuntimeConfig

    包含模型、系统提示、工具、迭代限制、执行模式等。

    Phase 19 新增:
        - auto_approve: 是否跳过工具审批（对标 Cline autoApprove）
          True 时所有 requires_approval=True 的工具直接执行，不弹审批 UI
          False 时需要用户手动批准危险工具调用

    Phase 26 新增:
        - completion_policy: 完成策略，控制是否必须调用完成工具

    Stage 10.6 (A16) 新增:
        - initial_messages: 初始化消息（如系统预设上下文），首次 run 时注入
        - plugins: 插件列表（预留字段，当前不实现加载逻辑）
        - logger: 自定义 logger，None 时用模块级 logger
        - telemetry: 遥测服务注入，None 时跳过遥测调用
    """
    model: AgentModel
    system_prompt: str | None = None
    max_iterations: int | None = 50
    tool_execution: str = "sequential"  # sequential / parallel
    agent_id: str = ""
    agent_role: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    parent_agent_id: str | None = None
    model_options: dict[str, Any] = field(default_factory=dict)
    tool_policies: dict[str, dict[str, Any]] = field(default_factory=dict)
    message_model_info: dict[str, str] | None = None
    max_tool_result_chars: int = 16000
    context_window_tokens: int = 65536
    # Phase 19: 工具审批开关 — 对标 Cline autoApprove
    auto_approve: bool = False
    # 工具执行默认超时（毫秒），None 或 0 表示不限制
    default_tool_timeout_ms: int = 300_000
    # Phase 26: 循环检测配置 — 对标 Cline LoopDetectionConfig
    loop_detection: LoopDetectionConfig = field(default_factory=LoopDetectionConfig)
    # Phase 26: 完成策略 — 对标 Cline completionPolicy
    completion_policy: CompletionPolicy = field(default_factory=CompletionPolicy)
    # Phase 28.3: 文件 hook 系统配置 — 对标 Cline hooksDir
    # enable_file_hooks=True 时从 file_hooks_dir 加载脚本 hook 并注册到对应 Python hook 点
    enable_file_hooks: bool = False
    file_hooks_dir: str | None = None  # 默认 agent_config/hooks/
    # Phase 30.1: turn queue steer 消息消费回调 — 对标 Cline consumePendingUserMessage
    # runtime 在 iteration > 1 时调用此回调获取 steer 类型的待处理用户消息，
    # 追加到当前 model request 的 messages 末尾。
    # 回调签名: async (session_id) -> str | None
    # 返回 None 表示无 steer 消息；返回非空字符串作为 user 消息追加。
    consume_pending_user_message: Callable[[str], Awaitable[str | None]] | None = None
    # Phase 32.1: 模型工具路由配置 — 对标 Cline model-tool-routing
    # provider_id / model_id 用于路由规则匹配，留空时 runtime 自动从 config.model 推断
    # tool_routing_rules 为 None 时使用 DEFAULT_MODEL_TOOL_ROUTING_RULES
    # get_tools() 会根据当前 mode + provider_id + model_id 过滤工具列表
    provider_id: str = ""
    model_id: str = ""
    tool_routing_rules: list[Any] | None = None
    # Stage 10.6 (A16): 缺失字段补全 — 对标 Cline AgentRuntimeConfig
    # initial_messages: 初始化消息列表，首次 run 时追加到 state.messages（仅当 messages 为空）
    # 多轮 run 中只注入一次（_initial_messages_injected 标记），restore() 时重置
    initial_messages: list[AgentMessage] = field(default_factory=list)
    # plugins: 插件列表预留字段，当前不实现加载逻辑（Stage 8 已确认 Y 阶段不实施）
    # AgentRuntime.__init__ 中仅存储不处理，未来扩展时使用
    plugins: list[Any] = field(default_factory=list)
    # logger: 自定义 logger 实例，None 时用模块级 logger（向后兼容）
    # AgentRuntime 内所有 logger.xxx 调用改为 self._logger.xxx
    logger: Any = None  # logging.Logger | None
    # telemetry: 遥测服务实例，None 时跳过遥测调用（不等价于 opt_out，opt_out 是用户选择）
    # AgentRuntime 在所有遥测调用前判断 if self._telemetry:
    telemetry: Any = None  # TelemetryService | None


# Stage 10.6 (A16): AgentRuntimeConfig 字段标准键名定义
# 对标 Cline AgentRuntimeConfig 的字段标准化，供 AgentRuntime 填充 metadata 时使用
AGENT_TOOL_METADATA_KEYS: dict[str, str] = {
    "run_id": "当前 run 的唯一 ID",
    "iteration": "当前迭代轮次",
    "trigger_source": "调用来源（user/checkpoint/scheduler）",
    "checkpoint_id": "关联的 checkpoint ID（若有）",
    "verbose": "是否启用详细日志",
}


# Stage 10.1 (C8/C18): Provider metadata 标准字段名 — 对标 Cline llm-gateway chunk.metadata
# Provider 填充 tool-call-delta 事件的 metadata 时按此列表标准化字段名，避免拼写不一致
# 不强制要求所有字段都填充，缺失字段不写入
PROVIDER_METADATA_FIELDS: list[str] = [
    "request_id",        # 请求 ID（provider 返回，用于追踪）
    "model_version",     # 实际使用的模型版本（可能与请求的 model 不同）
    "finish_reason",     # 完成原因（仅 finish chunk 有值）
    "prompt_tokens",     # 输入 token 数（部分 provider 在 chunk 中返回）
    "completion_tokens", # 输出 token 数（部分 provider 在 chunk 中返回）
]


# ============================================================================
# 辅助函数
# ============================================================================

def create_message(
    role: MessageRole | str,
    content: list[MessagePart] | None = None,
    **kwargs: Any,
) -> AgentMessage:
    """创建消息的便捷函数 — 对标 Cline createMessage"""
    if isinstance(role, str):
        role = MessageRole(role)
    return AgentMessage(
        role=role,
        content=content or [],
        **kwargs,
    )


def create_text_message(role: MessageRole | str, text: str, **kwargs: Any) -> AgentMessage:
    """创建纯文本消息"""
    return create_message(role, [TextPart(text=text)], **kwargs)


def text_from_message(message: AgentMessage | None) -> str:
    """从消息中提取所有文本片段 — 对标 Cline textFromMessage"""
    if message is None:
        return ""
    return "".join(
        part.text for part in message.content
        if isinstance(part, (TextPart, ReasoningPart))
    )


def text_from_tool_message(message: AgentMessage) -> str:
    """从工具结果消息中提取文本 — 对标 Cline textFromToolMessage"""
    parts = []
    for part in message.content:
        if isinstance(part, ToolResultPart):
            output = part.output
            if isinstance(output, str):
                parts.append(output)
            else:
                parts.append(str(output))
    return "".join(parts)


def _clone_part(part: MessagePart) -> MessagePart:
    """深拷贝单个消息片段 — 对标 Cline cloneMessages 中 content.map((part) => ({ ...part }))

    为每种 Part 类型创建新对象，dict 字段浅拷贝。
    ToolResultPart.output 为 Any 类型（可能含不可深拷贝对象），保留引用，
    但通过创建新 ToolResultPart 实例确保 part 本身是独立副本。

    Args:
        part: 原始消息片段

    Returns:
        新的消息片段对象（独立副本）
    """
    if isinstance(part, TextPart):
        return TextPart(text=part.text)
    if isinstance(part, ReasoningPart):
        return ReasoningPart(
            text=part.text,
            redacted=part.redacted,
            metadata=dict(part.metadata),
        )
    if isinstance(part, ToolCallPart):
        return ToolCallPart(
            tool_call_id=part.tool_call_id,
            tool_name=part.tool_name,
            input=dict(part.input),
            metadata=dict(part.metadata),
        )
    if isinstance(part, ToolResultPart):
        # output 为 Any 类型（str / dict / list 等），保留引用避免深拷贝未知对象；
        # 通过新建 ToolResultPart 实例确保 part 本身可被安全替换/修改
        return ToolResultPart(
            tool_call_id=part.tool_call_id,
            tool_name=part.tool_name,
            output=part.output,
            is_error=part.is_error,
            metadata=dict(part.metadata),
        )
    if isinstance(part, ImagePart):
        # image 为 str|bytes，str/bytes 不可变无需拷贝；其余字段为基本类型
        return ImagePart(
            image=part.image,
            media_type=part.media_type,
            alt_text=part.alt_text,
            truncated=part.truncated,
            truncate_reason=part.truncate_reason,
        )
    if isinstance(part, FilePart):
        return FilePart(
            path=part.path,
            content=part.content,
            truncated=part.truncated,
            truncate_reason=part.truncate_reason,
        )
    # 兜底：未知类型直接返回原对象（向后兼容）
    return part


def clone_messages(messages: list[AgentMessage]) -> list[AgentMessage]:
    """深拷贝消息列表 — 对标 Cline cloneMessages

    P1-14 增强：从浅拷贝升级为深拷贝，确保返回的消息列表与原列表完全独立。
    对标 Cline agent-runtime.ts L292-300:
        return messages.map((message) => ({
            ...message,
            content: message.content.map((part) => ({ ...part })),
            metadata: message.metadata ? { ...message.metadata } : undefined,
            modelInfo: message.modelInfo ? { ...modelInfo } : undefined,
            metrics: message.metrics ? { ...metrics } : undefined,
        }));

    修改前（浅拷贝）: content 列表新建，但 part 元素仍是引用，
                      外部修改 part 内部字段会影响原消息。
    修改后（深拷贝）: content 列表新建，每个 part 也新建，
                      外部修改 snapshot 不影响 runtime 内部状态。

    用于 snapshot() / prepareTurn / restore 等需要完全独立副本的场景。

    Args:
        messages: 原始消息列表

    Returns:
        新的消息列表（每条 message 及其 content 中每个 part 均为独立副本）
    """
    return [
        AgentMessage(
            role=msg.role,
            content=[_clone_part(part) for part in msg.content],
            created_at=msg.created_at,
            id=msg.id,
            metadata=dict(msg.metadata),
            model_info=dict(msg.model_info) if msg.model_info else None,
            metrics=dict(msg.metrics) if msg.metrics else None,
        )
        for msg in messages
    ]


def clone_usage(usage: AgentUsage) -> AgentUsage:
    """拷贝用量对象 — 对标 Cline cloneUsage"""
    return AgentUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        reasoning_token_count=usage.reasoning_token_count,
        total_cost=usage.total_cost,
    )


# ============================================================================
# Stage 14.3 (Z3/Z4): 遥测事件类型枚举 — 对标 Cline TelemetryEvent 枚举
# ============================================================================


class TelemetryEventType(str, Enum):
    """遥测事件类型枚举 — Stage 14.3 (Z3/Z4) 新增

    对标 Cline sdk/packages/core/src/services/telemetry/events.ts 的 TelemetryEvent 枚举。

    命名说明:
        agent/telemetry.py 中已存在 TelemetryEvent 数据类（单条事件记录），
        为避免命名冲突，此处枚举命名为 TelemetryEventType。
        枚举值采用点号分隔的字符串（如 "run.started"），与现有调用点保持一致，
        继承 str, Enum 让枚举值可直接作为字符串使用，向后兼容现有 capture() 签名。

    事件分组:
        - Run 事件: run.started / run.finished / run.failed / run.aborted
        - Tool 事件: tool.started / tool.finished / tool.failed
        - Compaction 事件: compaction.started / completed / failed / skipped
        - Budget 事件: budget.projection
        - Hook 事件: hook.executed / hook.failed
        - Approval 事件: approval.requested / approval.decided
        - Checkpoint 事件: checkpoint.created / checkpoint.restored
        - Session 事件: session.created / session.restored / session.closed
        - Provider 事件: provider.called / provider.error
        - MistakeTracker 事件: mistake.recorded / mistake.limit_reached
        - LoopDetection 事件: loop.detected_soft / loop.detected_hard
        - 服务事件: service.activated / telemetry.opt_out
    """

    # Run 事件 — 对标 Cline run 事件组
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"
    RUN_FAILED = "run.failed"
    RUN_ABORTED = "run.aborted"

    # Tool 事件 — 对标 Cline tool 事件组
    TOOL_STARTED = "tool.started"
    TOOL_FINISHED = "tool.finished"
    TOOL_FAILED = "tool.failed"

    # Compaction 事件 — 对标 Cline compaction 事件组
    COMPACTION_STARTED = "compaction.started"
    COMPACTION_COMPLETED = "compaction.completed"
    COMPACTION_FAILED = "compaction.failed"
    COMPACTION_SKIPPED = "compaction.skipped"

    # Budget 事件 — 对标 Cline budget 事件组
    BUDGET_PROJECTION = "budget.projection"

    # Hook 事件 — 对标 Cline hook 事件组
    HOOK_EXECUTED = "hook.executed"
    HOOK_FAILED = "hook.failed"

    # Approval 事件 — 对标 Cline approval 事件组
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"

    # Checkpoint 事件 — 对标 Cline checkpoint 事件组
    CHECKPOINT_CREATED = "checkpoint.created"
    CHECKPOINT_RESTORED = "checkpoint.restored"

    # Session 事件 — 对标 Cline session 事件组
    SESSION_CREATED = "session.created"
    SESSION_RESTORED = "session.restored"
    SESSION_CLOSED = "session.closed"

    # Provider 事件 — 对标 Cline provider 事件组
    PROVIDER_CALLED = "provider.called"
    PROVIDER_ERROR = "provider.error"

    # MistakeTracker 事件 — 对标 Cline mistake 事件组
    MISTAKE_RECORDED = "mistake.recorded"
    MISTAKE_LIMIT_REACHED = "mistake.limit_reached"

    # LoopDetection 事件 — 对标 Cline loop 事件组
    LOOP_DETECTED_SOFT = "loop.detected_soft"
    LOOP_DETECTED_HARD = "loop.detected_hard"

    # 服务事件 — 对标 Cline service 事件组
    SERVICE_ACTIVATED = "service.activated"
    TELEMETRY_OPT_OUT = "telemetry.opt_out"

    @classmethod
    def values(cls) -> list[str]:
        """返回所有事件类型字符串值 — 便于覆盖率检查"""
        return [member.value for member in cls]
