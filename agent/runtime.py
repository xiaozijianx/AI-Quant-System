# -*- coding: utf-8 -*-
"""AgentRuntime 主循环 — 对标 Cline agent-runtime.ts

AgentRuntime 是 Agent 引擎的核心，负责:
    1. 主循环: generate → tool_calls → execute → repeat
    2. 流式消费 LLM 输出 (text/reasoning/tool_call delta)
    3. 工具执行 (parallel/sequential + before/after hooks)
    4. 事件发射 (12 种事件类型)
    5. 中止控制 (abort)
    6. 用量追踪 (token usage)
    7. completes_run 检测 (工具标记运行完成)

核心循环逻辑 (对标 agent-runtime.ts L595-794 execute 方法):
    while iteration < max_iterations:
        1. throw_if_aborted()
        2. emit(turn_started)
        3. message, finish_reason = generate_assistant_message()
        4. extract tool_calls from message
        5. push message, emit(message_added)
        6. if no tool_calls: finish_run("completed")
        7. tool_messages = execute_tool_calls(tool_calls)
        8. push tool_messages, emit(message_added)
        9. if completing_tool succeeded: finish_run("completed")
       10. emit(turn_finished)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from agent.types import (
    AgentMessage,
    AgentModel,
    AgentModelEvent,
    AgentModelFinishReason,
    AgentModelRequest,
    AgentRunResult,
    AgentRuntimeConfig,
    AgentRuntimeStateSnapshot,
    AgentTool,
    AgentToolContext,
    AgentToolDefinition,
    AgentToolResult,
    AgentUsage,
    CompletionPolicy,
    ControlledStopError,
    MessageRole,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolLifecycle,
    ToolResultPart,
    clone_messages,
    clone_usage,
    create_message,
    create_text_message,
    text_from_message,
    text_from_tool_message,
)
from agent.events import (
    EventEmitter,
    AgentEvent,
    EventListener,
    make_message_added,
    make_assistant_message,
    make_tool_updated,
    make_reasoning_delta,
    make_run_failed,
    make_run_finished,
    make_run_started,
    make_status_notice,
    make_text_delta,
    make_tool_finished,
    make_tool_started,
    make_turn_finished,
    make_turn_started,
    make_usage_updated,
    RUN_STARTED,
    TURN_STARTED,
    ASSISTANT_TEXT_DELTA,
    ASSISTANT_REASONING_DELTA,
    MESSAGE_ADDED,
    ASSISTANT_MESSAGE,
    TURN_FINISHED,
    RUN_FINISHED,
    RUN_FAILED,
    TOOL_EXECUTION_STARTED,
    TOOL_EXECUTION_FINISHED,
    TOOL_UPDATED,
    USAGE_UPDATED,
    STATUS_NOTICE,
)
from agent.hooks import (
    AgentHooks,
    AfterModelContext,
    AfterRunContext,
    AfterToolContext,
    AfterToolResult,
    BeforeApprovalContext,
    BeforeApprovalResult,
    BeforeModelContext,
    BeforeModelResult,
    BeforeToolContext,
    BeforeToolResult,
    FormatUserInputBlockContext,
    FormatUserInputBlockResult,
    HookBag,
    PrepareTurnInputContext,
    PrepareTurnInputResult,
    RunLifecycleContext,
    StopControl,
)
from agent.loop_detection import LoopDetectionTracker
from agent.mistake_tracker import MistakeTracker, MistakeType, classify_mistake
from agent.abort import AbortController, AbortedError

# P1-7: 导入全局 HookProcessRegistry，用于 abort 时 kill 所有 hook 进程
from agent.file_hooks.registry import get_global_registry

logger = logging.getLogger(__name__)


# ============================================================================
# 工具调用组装辅助结构 — 对标 Cline PendingToolAssembly
# ============================================================================

@dataclass
class _PendingToolAssembly:
    """流式工具调用组装器 — 对标 Cline PendingToolAssembly

    LLM 流式返回 tool_call_delta 时，参数是分片到达的，
    需要逐步组装成完整的 ToolCallPart。

    Stage 10.1 (C8/C18) 增强: metadata 字段在每个 chunk 到达时深度合并，
    用于记录工具调用的 provider 上下文（如 model_version、request_id、finish_reason）。
    """
    tool_call_id: str = ""
    tool_name: str = ""
    input_text: str = ""       # JSON 字符串分片累积
    input_value: Any | None = None  # 已解析的输入值（部分 API 直接返回 dict）
    parse_error: str | None = None  # 输入解析错误信息
    metadata: dict[str, Any] = field(default_factory=dict)


def _deep_merge_metadata(assembly_meta: dict[str, Any], chunk_meta: dict[str, Any]) -> None:
    """深度合并 metadata — Stage 10.1 (C8/C18) 新增，对标 Cline agent-runtime.ts L1020-1030

    将 chunk_meta 合并到 assembly_meta（原地修改，无返回值）。
    合并规则:
        - provider_metadata 子字段: 深度合并（嵌套 dict 递归 update）
        - 顶层字段（如 request_id/model_version/finish_reason）: 覆盖语义（后到为准）

    Args:
        assembly_meta: 累积的 metadata（原地修改）
        chunk_meta: 当前 chunk 的 metadata
    """
    if not chunk_meta:
        return
    for key, value in chunk_meta.items():
        if key == "provider_metadata" and isinstance(value, dict):
            # provider_metadata 深度合并
            existing = assembly_meta.get("provider_metadata")
            if not isinstance(existing, dict):
                assembly_meta["provider_metadata"] = dict(value)
            else:
                existing.update(value)
        else:
            # 顶层字段覆盖语义
            assembly_meta[key] = value


@dataclass
class _InvalidToolCall:
    """无效工具调用记录 — 对标 Cline InvalidToolCall

    当 LLM 输出的 tool-call 缺少工具名、缺少参数或参数无法解析时，
    将其记录到 assistant 消息的 metadata 中，便于上层展示或反馈给 LLM。
    """
    tool_call_id: str
    reason: str  # "missing_name" | "missing_arguments" | "invalid_arguments"
    tool_name: str | None = None
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ParsedToolInput:
    """工具输入解析结果 — 对标 Cline parseToolInput() 返回值"""
    input: Any
    invalid_input: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None
    reason: str | None = None  # "missing_arguments" | "invalid_arguments"


@dataclass
class _PreparedToolExecution:
    """准备好的工具执行 — 对标 Cline PreparedToolExecution"""
    tool_call: ToolCallPart
    tool: AgentTool | None
    input: Any
    skip_reason: str | None = None


# ============================================================================
# 运行时内部状态
# ============================================================================

@dataclass
class _RuntimeState:
    """运行时内部状态 — 对标 Cline AgentRuntime.state"""
    agent_id: str = ""
    agent_role: str | None = None
    parent_agent_id: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    status: str = "idle"  # idle / running / completed / aborted / failed
    iteration: int = 0
    messages: list[AgentMessage] = field(default_factory=list)
    pending_tool_calls: list[str] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)
    last_error: str | None = None


# ============================================================================
# AgentRuntime — 对标 Cline AgentRuntime 类
# ============================================================================

class AgentRuntime:
    """Agent 运行时 — 对标 Cline AgentRuntime

    用法:
        runtime = AgentRuntime(config=AgentRuntimeConfig(
            model=qwen_model,
            system_prompt="You are a helpful assistant.",
            max_iterations=50,
        ))
        runtime.register_tool(my_tool)
        runtime.register_hooks(AgentHooks(before_model=my_hook))

        # 订阅事件（SSE 层会订阅此事件流转为 SSE 流）
        runtime.subscribe(lambda e: print(e.type))

        # 运行
        result = await runtime.run("帮我写一份研报")
    """

    def __init__(self, config: AgentRuntimeConfig) -> None:
        self.config = config
        self._emitter = EventEmitter()
        self._tools: dict[str, AgentTool] = {}
        self._hooks = HookBag()
        self._state = _RuntimeState(
            agent_id=config.agent_id or uuid.uuid4().hex[:8],
            agent_role=config.agent_role,
            parent_agent_id=config.parent_agent_id,
            conversation_id=config.conversation_id,
        )
        self._aborted: bool = False
        self._abort_reason: str = ""
        # Phase 26: 工具错误历史 — 用于检测重复失败导致的死循环
        self._recent_tool_errors: list[tuple[str, str]] = []
        # Phase 26: 循环检测器 — 对标 Cline LoopDetectionTracker
        self._loop_tracker = LoopDetectionTracker(config=config.loop_detection)
        # 注册循环检测为 before_tool hook
        self._hooks.before_tool.append(self._loop_detection_hook)
        # Phase 28.1: 连续错误追踪器 — 对标 Cline MistakeTracker
        self._mistake_tracker = MistakeTracker()
        # Phase 28.2: 中止控制器 — 对标 Cline AbortController
        self._abort_controller = AbortController()
        # Phase 28.3: 文件 hook 系统 — 加载并注册外部脚本 hook
        # 对标 Cline hooksDir 配置，启用后从 file_hooks_dir 扫描脚本并
        # 注册到对应的 Python hook 点（before_tool / after_tool 等）
        self._file_hooks_loaded: bool = False
        if config.enable_file_hooks:
            self._load_file_hooks()
        # Phase 29.3: 文件上下文追踪器 — 自动记录工具读写的文件路径
        # 注册 after_tool hook，根据 tool_name + input 提取路径并记录到 tracker
        # 压缩摘要和前端 /api/agent/file_context 端点复用 tracker 数据
        self._file_tracker = None
        if config.session_id:
            try:
                from agent.file_context_tracker import get_tracker
                self._file_tracker = get_tracker(config.session_id)
            except Exception as e:
                logger.warning("FileContextTracker 初始化失败: %s", e)
        self._hooks.after_tool.append(self._file_context_tracker_hook)

        # Stage 6.7: SSE 事件回调列表 — runtime 主动推送事件给前端
        # 由 server.py 的 stream_chat 函数注册回调，runtime 在 hook 中调用
        # callback 签名: async def callback(event_type: str, data: dict) -> None
        self._sse_event_callbacks: list = []

        # Stage 10.6 (A16): 接入 config 新增字段 — 对标 Cline AgentRuntimeConfig
        # logger: 自定义 logger，None 时用模块级 logger（向后兼容）
        # 后续 self._logger.xxx 调用统一走此实例，上层可注入实现日志聚合
        self._logger = config.logger or logger
        # telemetry: 遥测服务实例，None 时跳过遥测调用
        # 不等价于 opt_out（opt_out 是用户选择，None 是未配置）
        self._telemetry = config.telemetry
        # initial_messages: 初始化消息列表，首次 run 时追加到 state.messages
        # 复制避免外部修改；用 _initial_messages_injected 标记防止重复注入
        self._initial_messages: list[AgentMessage] = list(config.initial_messages)
        self._initial_messages_injected: bool = False
        # plugins: 插件列表预留字段，当前不实现加载逻辑（Stage 8 已确认 Y 阶段不实施）
        # 仅存储不处理，未来扩展时使用
        self._plugins: list[Any] = list(config.plugins)
        # Stage 10.3 (B9): completion reminder 注入标记
        # require_completion_tool=True 时，run 开始时注入 system reminder
        # 首次注入后置 True，后续 run 不再注入（除非 restore 重置）
        self._completion_reminder_injected: bool = False

    def _load_file_hooks(self) -> None:
        """加载文件 hook 并注册到 Python hook 点 — Phase 28.3 新增

        对标 Cline 从 hooksDir 加载脚本的逻辑。
        在 __init__ 中调用，也可在外部更新 file_hooks_dir 后手动调用重新加载。
        """
        from pathlib import Path

        from agent.file_hooks.integration import build_file_hooks_agent_hooks

        hooks_dir_str = self.config.file_hooks_dir
        if not hooks_dir_str:
            # 默认路径：agent_config/hooks/（相对于当前工作目录）
            hooks_dir_str = "agent_config/hooks"
            logger.debug(
                "file_hooks_dir 未配置，使用默认路径: %s",
                hooks_dir_str,
            )

        hooks_dir = Path(hooks_dir_str)
        session_id = self.config.session_id or ""
        agent_id = self._state.agent_id

        try:
            file_hooks = build_file_hooks_agent_hooks(
                hooks_dir=hooks_dir,
                session_id=session_id,
                agent_id=agent_id,
            )
        except Exception as e:
            logger.exception("加载文件 hook 失败: %s", e)
            self._file_hooks_loaded = False
            return

        if file_hooks is None:
            self._file_hooks_loaded = False
            return

        self.register_hooks(file_hooks)
        self._file_hooks_loaded = True
        logger.info(
            "文件 hook 已加载并注册: dir=%s, session_id=%s",
            hooks_dir, session_id,
        )

    # ========================================================================
    # 公开接口
    # ========================================================================

    def register_tool(self, tool: AgentTool) -> None:
        """注册工具 — 对标 Cline AgentRuntime tools Map.set"""
        self._tools[tool.name] = tool

    def register_hooks(self, hooks: AgentHooks) -> None:
        """注册钩子 — 对标 Cline registerHooks() L544-554"""
        self._hooks.add(hooks)

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """订阅事件 — 对标 Cline AgentRuntime.on()"""
        return self._emitter.subscribe(listener)

    def restore(self, messages: list[AgentMessage]) -> None:
        """恢复会话状态 — 对标 Cline AgentRuntime.restore() L487-503

        用给定的消息历史替换当前对话，保留 model、工具、钩子和订阅者，
        重置运行状态以便重新启动。用于外部持久化会话后重新注入 runtime。

        Stage 10.3 / 10.6: 重置 initial_messages_injected 和
        completion_reminder_injected 标记，允许新会话重新注入。
        """
        self.abort("Agent state restored")
        self._state.run_id = None
        self._state.status = "idle"
        self._state.iteration = 0
        self._state.pending_tool_calls = []
        self._state.usage = AgentUsage()
        self._state.last_error = None
        self._state.messages = clone_messages(messages)
        self._recent_tool_errors = []
        self._loop_tracker.reset()
        self._mistake_tracker.reset()
        self._abort_controller.reset()
        # abort() 设置了 _aborted，恢复后需要复位以允许新运行
        self._aborted = False
        self._abort_reason = ""
        # Stage 10.6 (A16): 重置 initial_messages 注入标记，允许新会话重新注入
        self._initial_messages_injected = False
        # Stage 10.3 (B9): 重置 completion reminder 注入标记，允许新会话重新注入
        self._completion_reminder_injected = False

    async def restore_checkpoint_messages_only(
        self,
        checkpoint_id: str,
    ) -> "list[AgentMessage] | None":
        """仅回滚消息历史 — 对标 Cline ClineCheckpointRestore = "task" 模式

        从检查点恢复 runtime 的消息状态，不触发文件回滚，不删除检查点。
        复用 restore() 重置 runtime 运行状态并注入恢复后的消息列表。

        与完整回滚的区别:
            - 不调用文件回滚（git stash/restore）
            - 不删除 checkpoint（同一 checkpoint 可多次仅消息回滚）
            - 仅用检查点快照替换 runtime 当前消息历史

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            恢复后的消息列表（AgentMessage），检查点不存在时返回 None
        """
        # 延迟导入以避免循环依赖
        from agent.checkpoint import get_checkpoint_manager
        from agent.session import _dict_to_message

        manager = get_checkpoint_manager()
        messages_data = manager.restore_messages_only(checkpoint_id)
        if messages_data is None:
            self._logger.warning(
                "restore_checkpoint_messages_only: 检查点 %s 不存在", checkpoint_id
            )
            return None

        restored_messages = [_dict_to_message(m) for m in messages_data]
        # 复用 restore() 重置 runtime 状态（中止运行、重置计数器、注入消息）
        self.restore(restored_messages)
        self._logger.info(
            "restore_checkpoint_messages_only: 已仅消息回滚到检查点 %s "
            "（恢复 %d 条消息，文件状态和检查点保留）",
            checkpoint_id,
            len(restored_messages),
        )
        return restored_messages

    def reset_mistake_tracker(self) -> None:
        """手动重置 MistakeTracker — P1-12 新增

        对标 Cline MistakeTracker.reset()，用于用户确认后或外部主动重置场景。
        P1-12 修改后 run() 不再自动重置 mistake_tracker，连续错误计数跨轮次累积。
        当用户确认已知晓错误、或切换到全新任务时，可调用此方法清空计数。

        与 restore() 的区别：
            - restore() 重置整个会话状态（消息、工具、计数器等），用于会话边界
            - reset_mistake_tracker() 仅重置错误计数，保留对话历史和其他状态
        """
        self._mistake_tracker.reset()
        self._logger.info("P1-12: MistakeTracker 已手动重置")

    def abort(self, reason: str = "") -> None:
        """中止运行 — 对标 Cline AgentRuntime.abort() L454-470

        设置中止标志，主循环在下一次检查点会抛出异常。
        Phase 30.2: 同步记录 last_error，对标 Cline L465 `this.state.lastError = abortError.message`，
                    让前端能展示中止原因。
        Phase 2.6: 幂等检查 — 已 aborted 时直接返回，避免覆盖首次中止原因。
        P1-7: 同步 kill 所有运行中的 hook 进程，避免 hook 继续执行到超时。
        """
        # 幂等检查 — 对标 Cline L458-460
        # 已 aborted 时直接返回，避免覆盖首次中止原因
        if self._aborted:
            return
        self._aborted = True
        self._abort_reason = reason or "aborted by user"
        self._state.status = "aborted"
        # Phase 30.2: 记录中止原因到 state.last_error，前端可展示
        self._state.last_error = self._abort_reason
        # Phase 28.2: 同步触发 AbortController，让 stream/工具能立即响应
        self._abort_controller.abort(self._abort_reason)
        # P1-7: 同步 kill 所有运行中的 hook 进程
        # abort_signal 设置后，hook 执行前的检查会跳过新 hook；
        # kill_all_sync 终止已在运行的 hook 子进程，避免执行到超时
        try:
            registry = get_global_registry()
            registry.kill_all_sync()
        except Exception as e:
            logger.warning("abort 时 kill_all hook 进程失败: %s", e)

    def snapshot(self) -> AgentRuntimeStateSnapshot:
        """获取状态快照 — 对标 Cline AgentRuntime.snapshot()

        Phase 2.3 A20: messages / pending_tool_calls 用 tuple 构造只读视图，
                        对标 Cline readonly AgentMessage[]，防止 listener 误修改。
        P1-14 增强: messages 改用 clone_messages 深拷贝，对标 Cline snapshot()
                     中的 cloneMessages(this.state.messages)。
                     修改前 tuple(self._state.messages) 仅创建新 tuple，message
                     对象仍是内部引用，外部修改 snapshot.messages[i].content 会
                     影响 runtime 内部状态；修改后每条 message 及其 content 中的
                     每个 part 均为独立副本，确保 snapshot 完全隔离。
        """
        return AgentRuntimeStateSnapshot(
            agent_id=self._state.agent_id,
            agent_role=self._state.agent_role,
            parent_agent_id=self._state.parent_agent_id,
            conversation_id=self._state.conversation_id,
            run_id=self._state.run_id,
            status=self._state.status,
            iteration=self._state.iteration,
            messages=tuple(clone_messages(self._state.messages)),
            pending_tool_calls=tuple(self._state.pending_tool_calls),
            usage=clone_usage(self._state.usage),
            last_error=self._state.last_error,
        )

    def get_tools(self) -> list[AgentToolDefinition]:
        """获取所有已注册工具的定义 — 用于构建 LLM 请求

        Phase 32.1: 应用模型工具路由 — 对标 Cline model-tool-routing。
        根据 provider_id / model_id / mode 动态启用或禁用工具，
        适配不同模型的工具支持能力（如 OpenAI 模型在 act 模式下
        用 apply_patch 替代 editor）。
        """
        defs: list[AgentToolDefinition] = []
        for tool in self._tools.values():
            if hasattr(tool, "to_definition"):
                defs.append(tool.to_definition())
            else:
                defs.append(AgentToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    lifecycle=getattr(tool, "lifecycle", None),
                ))

        # Phase 32.1: 应用工具路由过滤
        toggles = self._resolve_tool_routing_toggles()
        if toggles:
            defs = [
                d for d in defs
                if toggles.get(d.name, True)
            ]
        return defs

    def _resolve_tool_routing_toggles(self) -> dict[str, bool]:
        """解析当前会话的工具路由开关 — Phase 32.1 新增

        对标 Cline resolveToolRoutingConfig。结合 provider_id、model_id、
        当前 mode（从 SessionState 读取，无 session_id 时默认 act）和
        tool_routing_rules 计算开关字典。

        Returns:
            dict[tool_name, enabled]，空字典表示无需过滤
        """
        from agent.tools.routing import (
            DEFAULT_MODEL_TOOL_ROUTING_RULES,
            extract_model_info,
            resolve_tool_routing,
        )

        rules = self.config.tool_routing_rules
        if rules is None:
            rules = DEFAULT_MODEL_TOOL_ROUTING_RULES
        if not rules:
            return {}

        # 推断 provider_id / model_id（显式配置优先，否则从 model 对象提取）
        provider_id = self.config.provider_id
        model_id = self.config.model_id
        if not provider_id or not model_id:
            extracted_provider, extracted_model = extract_model_info(self.config.model)
            if not provider_id:
                provider_id = extracted_provider
            if not model_id:
                model_id = extracted_model

        # 读取当前 mode（act / plan），无 session_id 时默认 act
        mode: str = "act"
        if self.config.session_id:
            try:
                from agent.state import get_mode
                mode = get_mode(self.config.session_id)
            except Exception:
                pass

        return resolve_tool_routing(provider_id, model_id, mode, rules)

    # ========================================================================
    # 主循环 — 对标 Cline execute() L595-794
    # ========================================================================

    async def run(
        self,
        input: str | AgentMessage | list[AgentMessage],
        messages: list[AgentMessage] | None = None,
    ) -> AgentRunResult:
        """运行 Agent — 对标 Cline execute()

        主循环: generate → tool_calls → execute → repeat
        直到 LLM 不再请求工具调用，或达到 max_iterations，或被中止。

        Args:
            input: 用户输入，可以是字符串、单条消息或消息列表。
            messages: 历史消息列表（可选）。如果提供，会作为初始消息历史
                     注入到 runtime 状态中，然后再添加 input 消息。
                     用于支持会话续接（如 server.py 传入之前的对话历史）。

        Returns:
            AgentRunResult: 运行结果，包含最终输出、消息历史、用量等。
        """
        if self._state.status == "running":
            raise RuntimeError("Agent runtime is already running")

        # 初始化运行状态
        self._aborted = False
        self._abort_reason = ""
        self._recent_tool_errors = []
        self._loop_tracker.reset()
        # P1-12: MistakeTracker 跨 run() 累积 — 对标 Cline mistakeTracker 不在 execute() 中重置
        # Cline session-runtime-orchestrator.ts 中 mistakeTracker.reset() 仅在
        # resetConversationBoundaryTrackers()（会话边界）调用，execute()（对标 run()）不重置。
        # 此处移除 reset()，让连续错误计数跨轮次累积，避免循环检测在跨轮次场景下失效。
        # 手动重置请调用 reset_mistake_tracker()（如用户确认后重置）。
        self._abort_controller.reset()
        self._state.run_id = uuid.uuid4().hex[:12]
        self._state.status = "running"
        self._state.iteration = 0
        self._state.pending_tool_calls = []
        self._state.last_error = None
        self._state.usage = AgentUsage()
        # P1-7: 将 runtime 的 abort_signal 绑定到全局 HookProcessRegistry
        # 使 hook 执行前能检查 abort_signal，abort 时 kill_all_sync 终止 hook 进程
        try:
            get_global_registry().set_abort_signal(self._abort_controller.signal)
        except Exception as e:
            logger.warning("绑定 abort_signal 到 HookProcessRegistry 失败: %s", e)

        try:
            # before_run hooks
            await self._call_before_run_hooks()

            # 发射 run-started 事件
            await self._emit(make_run_started(self.snapshot()))

            # Stage 10.6 (A16): initial_messages 注入 — 对标 Cline AgentRuntimeConfig.initialMessages
            # 首次 run 且 state.messages 为空时，追加 config.initial_messages
            # 多轮 run 中只注入一次（_initial_messages_injected 标记），restore() 时重置
            # 注入的消息触发 message_added 事件，让前端可见初始上下文
            if (
                not self._initial_messages_injected
                and self._initial_messages
                and not self._state.messages
            ):
                for msg in self._initial_messages:
                    self._state.messages.append(msg)
                    await self._emit(make_message_added(self.snapshot(), msg))
                self._initial_messages_injected = True
                self._logger.info(
                    "Stage 10.6: 已注入 %d 条 initial_messages",
                    len(self._initial_messages),
                )
            elif not self._initial_messages_injected:
                # 即使 messages 为空但无 initial_messages，也标记为已注入避免重复检查
                self._initial_messages_injected = True

            # Stage 10.3 (B9): completion reminder 循环前预注入 — 对标 Cline callBeforeRunHooks
            # require_completion_tool=True 时，run 开始时注入 system reminder
            # 提示 LLM "本任务必须以 completing_tool 结束"，让 LLM 从第一轮就规划工具调用
            # 首次注入后置 True，后续 run 不再注入（除非 restore 重置）
            # 现有"第一轮失败后 reminder"逻辑保留作为兜底
            #
            # P1-18: 对标 Cline getRequiredCompletionToolNames() + getCompletionToolReminderMessage()，
            # 收集所有 completes_run=True 的工具名并在 reminder 中列出，让 LLM 知道所有可选的完成工具。
            if (
                not self._completion_reminder_injected
                and self.config.completion_policy.require_completion_tool
            ):
                completing_tools = self._find_completing_tool_names()
                if completing_tools:
                    await self._inject_completion_reminder(completing_tools)
                    self._completion_reminder_injected = True

            # 注入历史消息（可选）— 支持会话续接
            # 历史消息不触发 message_added 事件（避免前端重复渲染）
            if messages:
                for msg in messages:
                    self._state.messages.append(msg)

            # Phase 23: prepare_turn_input 钩子 — 用户输入预处理
            # 对标 Cline prepareTurnInput，在输入进入主循环前修改文本
            # 典型用途: 去除敏感信息、注入上下文标记、规范化格式
            if isinstance(input, str):
                input = await self._call_prepare_turn_input_hooks(input)

            # 添加输入消息
            input_messages = self._normalize_input(input)

            # Phase 23: format_user_input_block 钩子 — 用户输入块格式化
            # 对标 Cline formatUserInputBlock，在消息添加到历史前注入元数据
            # 典型用途: 添加时间戳、工作目录、选中文本等 IDE 上下文
            input_messages = await self._call_format_user_input_block_hooks(input_messages)

            for msg in input_messages:
                self._state.messages.append(msg)
                await self._emit(make_message_added(self.snapshot(), msg))

            final_assistant_message: AgentMessage | None = None

            # 主循环
            while (
                self.config.max_iterations is None
                or self._state.iteration < self.config.max_iterations
            ):
                self._throw_if_aborted()

                self._state.iteration += 1
                await self._emit(make_turn_started(self.snapshot(), self._state.iteration))

                # P1-9: LLM 请求前检查 abort_signal — 对标 Cline L854 throwIfAborted
                # 在调用 LLM 前检查，避免 abort 后仍发送 LLM 请求
                self._check_signal_aborted()

                # 调 LLM 生成 assistant 消息
                message, finish_reason = await self._generate_assistant_message()

                if finish_reason == AgentModelFinishReason.ABORTED.value:
                    raise RuntimeError(self._abort_reason or "aborted")

                if len(message.content) == 0:
                    raise RuntimeError(
                        "Model returned empty response"
                        if finish_reason != AgentModelFinishReason.ERROR.value
                        else (self._state.last_error or "Model stream failed")
                    )

                # 提取工具调用
                tool_calls = [
                    part for part in message.content
                    if isinstance(part, ToolCallPart)
                ]

                # Phase 26: 提取无效工具调用记录
                invalid_tool_calls = self._extract_invalid_tool_calls(message)

                # 保存 assistant 消息
                final_assistant_message = message
                # P1-9: 消息追加前检查 abort_signal — 对标 Cline throwIfAborted
                self._check_signal_aborted()
                self._state.messages.append(message)
                await self._emit(make_message_added(self.snapshot(), message))
                # Phase 2.8: emit assistant-message 事件 — 对标 Cline agent-runtime.ts L665-671
                # 携带 finish_reason，前端可据此区分 stop/tool-calls/max-tokens 等完成原因
                # 与 message-added 配套：先通用 message-added，后专用 assistant-message
                await self._emit(make_assistant_message(
                    self.snapshot(),
                    self._state.iteration,
                    message,
                    finish_reason,
                ))

                # max_tokens 且无工具调用 → 报错
                if finish_reason == AgentModelFinishReason.MAX_TOKENS.value and len(tool_calls) == 0:
                    raise RuntimeError(
                        "Model reached the maximum output token limit before completing the turn"
                    )
                # error 且无工具调用 → 报错
                if finish_reason == AgentModelFinishReason.ERROR.value and len(tool_calls) == 0:
                    raise RuntimeError(self._state.last_error or "Model stream failed")

                self._state.pending_tool_calls = [tc.tool_call_id for tc in tool_calls]

                # Phase 26: 为无效工具调用生成错误结果，让 LLM 在下一轮看到自己调用错了
                invalid_tool_messages: list[AgentMessage] = []
                for itc in invalid_tool_calls:
                    invalid_tool_messages.append(
                        self._build_invalid_tool_result_message(itc)
                    )
                for invalid_msg in invalid_tool_messages:
                    self._state.messages.append(invalid_msg)
                    await self._emit(make_message_added(self.snapshot(), invalid_msg))

                # 无有效工具调用时：要么结束运行，要么要求调用完成工具
                if len(tool_calls) == 0:
                    policy = self.config.completion_policy
                    if policy.require_completion_tool:
                        # 追加完成工具提醒，继续下一轮
                        reminder = self._build_completion_reminder(policy)
                        if reminder:
                            reminder_msg = create_text_message(
                                MessageRole.USER, reminder
                            )
                            self._state.messages.append(reminder_msg)
                            await self._emit(make_message_added(self.snapshot(), reminder_msg))
                        await self._emit(make_turn_finished(
                            self.snapshot(), self._state.iteration, 0
                        ))
                        continue

                    # 不需要完成工具时，正常结束运行
                    await self._emit(make_turn_finished(
                        self.snapshot(), self._state.iteration, 0
                    ))
                    result = self._finish_run(
                        "completed", final_assistant_message
                    )
                    await self._call_after_run_hooks(result)
                    await self._emit(make_run_finished(self.snapshot(), result))
                    return result

                # 执行有效工具调用
                # P1-9: 工具执行前检查 abort_signal — 对标 Cline throwIfAborted
                # 避免 abort 后仍启动工具执行（特别是长耗时工具如 run_commands）
                self._check_signal_aborted()
                tool_messages = await self._execute_tool_calls(tool_calls)

                # Phase 26: 检测重复失败死循环
                self._check_repeated_tool_failures(tool_calls, tool_messages)

                self._state.pending_tool_calls = []

                # 先追加工具结果到消息历史，再检查 abort 信号
                # 对标 Cline: 确保当 abort 发生时，tool_calls 已被 tool 消息响应，
                # 避免消息序列不完整导致下次 API 调用报 400 错误
                for tool_message in tool_messages:
                    self._state.messages.append(tool_message)
                    await self._emit(make_message_added(self.snapshot(), tool_message))

                # P1-9: 消息追加后检查 abort_signal — 对标 Cline throwIfAborted
                self._check_signal_aborted()

                await self._emit(make_turn_finished(
                    self.snapshot(), self._state.iteration, len(tool_calls)
                ))

                # 检查 completes_run 工具
                completing_message = self._find_completing_tool(tool_calls, tool_messages)
                if completing_message is not None:
                    output_text = text_from_tool_message(completing_message) or None
                    result = self._finish_run("completed", final_assistant_message, output_text)
                    await self._call_after_run_hooks(result)
                    await self._emit(make_run_finished(self.snapshot(), result))
                    return result

            # 超过 max_iterations
            raise RuntimeError(
                f"Agent runtime exceeded maxIterations ({self.config.max_iterations})"
            )

        except ControlledStopError as error:
            # Stage 10.4 (B33): hook 主动 stop — 受控停止，非失败
            # 对标 Cline ControlledStopError catch 分支
            # status="aborted"，finish_reason="controlled_stop"
            # 发射 run_finished 事件（非 run_failed），前端显示"被规则拦截"
            self._state.status = "aborted"
            self._state.last_error = str(error)

            last_assistant = self._find_last_assistant_message()
            result = AgentRunResult(
                agent_id=self._state.agent_id,
                agent_role=self._state.agent_role,
                run_id=self._state.run_id or uuid.uuid4().hex[:12],
                status="aborted",
                iterations=self._state.iteration,
                output_text=text_from_message(last_assistant),
                messages=list(self._state.messages),
                usage=clone_usage(self._state.usage),
                error=error,
                finish_reason="controlled_stop",
            )

            await self._call_after_run_hooks(result)
            await self._emit(make_run_finished(self.snapshot(), result))
            self._logger.info(
                "Stage 10.4: ControlledStopError (source=%s, reason=%s)",
                error.source, error.reason,
            )
            return result

        except Exception as error:
            # 异常处理 — 对标 Cline execute() catch 块 L745-790
            is_aborted = self._aborted
            status = "aborted" if is_aborted else "failed"
            self._state.status = status
            self._state.last_error = str(error)

            last_assistant = self._find_last_assistant_message()
            result = AgentRunResult(
                agent_id=self._state.agent_id,
                agent_role=self._state.agent_role,
                run_id=self._state.run_id or uuid.uuid4().hex[:12],
                status=status,
                iterations=self._state.iteration,
                output_text=text_from_message(last_assistant),
                messages=list(self._state.messages),
                usage=clone_usage(self._state.usage),
                error=error if not is_aborted else None,
                # Stage 10.4 (B33): 填充 finish_reason
                finish_reason="aborted" if is_aborted else "error",
            )

            await self._call_after_run_hooks(result)

            if status == "failed":
                await self._emit(make_run_failed(self.snapshot(), error))
            else:
                await self._emit(make_run_finished(self.snapshot(), result))

            return result

        finally:
            self._aborted = False
            self._abort_reason = ""

    # ========================================================================
    # LLM 生成 — 对标 Cline generateAssistantMessage() L811-1077
    # ========================================================================

    async def _generate_assistant_message(self) -> tuple[AgentMessage, str]:
        """调用 LLM 生成 assistant 消息 — 对标 Cline generateAssistantMessage()

        1. 构建 AgentModelRequest
        2. before_model hooks（可修改 messages/tools/options）
        3. model.stream(request) → 流式消费
        4. 组装 content parts
        5. after_model hooks

        Returns:
            (message, finish_reason)
        """
        usage_before = clone_usage(self._state.usage)

        # Stage 13.1 (R5): 从 model 读取 capabilities 透传到 request
        # Provider 在 stream_chat 中根据 capabilities 做能力降级
        model_capabilities: list[str] = []
        try:
            model_caps = getattr(self.config.model, "capabilities", None)
            if model_caps:
                model_capabilities = list(model_caps)
        except Exception as e:
            logger.warning("读取 model.capabilities 失败: %s", e)

        # 构建请求
        request = AgentModelRequest(
            system_prompt=self.config.system_prompt,
            messages=clone_messages(self._state.messages),
            tools=self.get_tools(),
            options=dict(self.config.model_options),
            capabilities=model_capabilities,
        )

        # Phase 30.1: iteration > 1 时消费 steer 消息 — 对标 Cline L841-852
        # 从 turn_queue 获取 steer 类型的待处理用户输入，追加到 messages 末尾
        # 让用户能在 agent 运行中实时插入补充指令
        if self._state.iteration > 1 and self.config.consume_pending_user_message is not None:
            try:
                pending_text = await self.config.consume_pending_user_message(
                    self.config.session_id or ""
                )
            except Exception as e:
                logger.warning("runtime: consume_pending_user_message 回调异常: %s", e)
                pending_text = None

            if pending_text:
                pending_text = pending_text.strip()
                if pending_text:
                    pending_msg = create_message(
                        MessageRole.USER, [TextPart(text=pending_text)],
                    )
                    # 追加到 state.messages（持久化）和 request.messages（本轮请求）
                    self._state.messages.append(pending_msg)
                    request.messages = list(request.messages) + [pending_msg]
                    # 发射 message_added 事件 — 对标 Cline L1263 emit message-added
                    await self._emit(make_message_added(self.snapshot(), pending_msg))
                    logger.info(
                        "runtime: iteration=%s 追加 steer 消息 (%d 字符)",
                        self._state.iteration, len(pending_text),
                    )

        # before_model hooks — 可修改请求或中止
        stop_control = await self._call_before_model_hooks(request)
        if stop_control is not None and stop_control.stop:
            raise RuntimeError(stop_control.reason or "stopped by before_model hook")

        # P1-9: before_model hooks 之后检查 abort_signal — 对标 Cline L861 throwIfAborted
        # before_model hook 可能耗时较长（如 context compaction），检查是否在此期间被 abort
        self._check_signal_aborted()

        # 流式消费
        content: list[Any] = []
        tool_assemblies: dict[str, _PendingToolAssembly] = {}
        sequence: list[Any] = []  # 保持 text/reasoning/tool_call 的顺序
        finish_reason = AgentModelFinishReason.STOP.value
        accumulated_text = ""
        accumulated_reasoning = ""
        next_tool_index = 0  # Cline: 用于无 id 也无 index 的 delta 生成 fallback key

        # P1-9: LLM 请求前检查 abort_signal — 对标 Cline L891 throwIfAborted
        # 在发起 model.stream 请求前最后检查一次，避免 abort 后仍发送网络请求
        self._check_signal_aborted()

        try:
            stream = self.config.model.stream(
                request, abort_signal=self._abort_controller.signal
            )
            if hasattr(stream, "__aiter__"):
                # 已经是 async iterator
                pass
            else:
                # stream() 返回的是 awaitable，await 它
                stream = await stream

            async for event in stream:
                self._throw_if_aborted()

                if event.type == "text-delta":
                    accumulated_text += event.text or ""
                    # 尝试合并到上一个 text part
                    last = sequence[-1] if sequence else None
                    if last is not None and isinstance(last, TextPart):
                        last.text += event.text or ""
                    else:
                        part = TextPart(text=event.text or "")
                        sequence.append(part)
                    # 发射事件
                    await self._emit(make_text_delta(
                        self.snapshot(), self._state.iteration,
                        event.text or "", accumulated_text,
                    ))

                elif event.type == "reasoning-delta":
                    accumulated_reasoning += event.text or ""
                    last = sequence[-1] if sequence else None
                    if last is not None and isinstance(last, ReasoningPart):
                        last.text += event.text or ""
                    else:
                        part = ReasoningPart(
                            text=event.text or "",
                            redacted=event.redacted or False,
                        )
                        sequence.append(part)
                    await self._emit(make_reasoning_delta(
                        self.snapshot(), self._state.iteration,
                        event.text or "", accumulated_reasoning,
                        event.redacted or False, event.metadata,
                    ))

                elif event.type == "tool-call-delta":
                    # 对标 Cline agent-runtime.ts L965-1000:
                    # key = event.toolCallId ?? `tool_${event.index ?? nextToolIndex}`
                    # 注意：Python 的 `or` 会把空字符串/0 当作 falsy，必须用 is None 判断，
                    # 否则 index=0 的 tool call 会丢失参数。
                    # Phase 2.4: 将 key 计算与 nextToolIndex 自增分离 — 对标 Cline L966-970
                    if event.tool_call_id is not None:
                        key = event.tool_call_id
                    elif event.index is not None:
                        key = f"tool_{event.index}"
                    else:
                        key = f"tool_{next_tool_index}"

                    # 自增决策独立判断 — 对标 Cline L968-970
                    # 仅当 index 与 tool_call_id 均为 None 时自增
                    if event.index is None and event.tool_call_id is None:
                        next_tool_index += 1

                    assembly = tool_assemblies.get(key)
                    if assembly is None:
                        assembly = _PendingToolAssembly(
                            tool_call_id=event.tool_call_id or uuid.uuid4().hex[:12],
                            input_text="",
                        )
                        tool_assemblies[key] = assembly
                        sequence.append(("tool", key))

                    if event.tool_call_id:
                        assembly.tool_call_id = event.tool_call_id
                    if event.tool_name:
                        assembly.tool_name = event.tool_name
                    if event.input_value is not None:
                        assembly.input_value = event.input_value
                    if event.input_text:
                        assembly.input_text += event.input_text
                    # Stage 10.1 (C8/C18): 流式 metadata 深度合并
                    # 对标 Cline agent-runtime.ts L1020-1030，每个 chunk 到达时
                    # 将 event.metadata 合并到 assembly.metadata
                    # provider_metadata 子字段深度合并，顶层字段覆盖语义
                    if event.metadata and isinstance(event.metadata, dict):
                        _deep_merge_metadata(assembly.metadata, event.metadata)

                elif event.type == "usage":
                    if event.usage:
                        self._state.usage.add(event.usage)
                        await self._emit(make_usage_updated(
                            self.snapshot(), clone_usage(self._state.usage)
                        ))

                elif event.type == "finish":
                    if event.reason:
                        finish_reason = event.reason.value if isinstance(event.reason, AgentModelFinishReason) else event.reason
                    if event.error:
                        self._state.last_error = event.error

        except Exception as e:
            if self._aborted:
                raise RuntimeError(self._abort_reason or "aborted")
            finish_reason = AgentModelFinishReason.ERROR.value
            self._state.last_error = str(e)

        # Stage 10.2 (C19): captureUnexpectedReasoningTokens — 对标 Cline agent-runtime.ts
        # finish_reason="tool_calls" 或 "stop" 后仍可能有意外 reasoning content
        # 部分 Provider（如 DeepSeek R1）未以 reasoning-delta 事件标识思考链，
        # 而是混入 text-delta。此处检测并转换为 ReasoningPart，避免污染 TextPart。
        # 保守策略：仅检测明确的 <think>...</think> 标签或启发式思考碎片
        if (
            finish_reason in (AgentModelFinishReason.TOOL_CALLS.value, AgentModelFinishReason.STOP.value)
            and accumulated_text
        ):
            reasoning_parts, remaining_text = self._capture_unexpected_reasoning_tokens(
                accumulated_text, finish_reason
            )
            if reasoning_parts:
                # 移除原 TextPart（在 sequence 末尾），追加 ReasoningPart
                # 从末尾向前移除属于意外 reasoning 的 TextPart
                removed_text_len = len(accumulated_text) - len(remaining_text)
                if removed_text_len > 0:
                    # 从 sequence 末尾移除 TextPart 直到移除足够字符
                    removed_chars = 0
                    while removed_chars < removed_text_len and sequence:
                        last = sequence[-1]
                        if isinstance(last, TextPart):
                            removed_chars += len(last.text)
                            sequence.pop()
                        else:
                            break
                # 追加 ReasoningPart
                for rp in reasoning_parts:
                    sequence.append(rp)
                # 剩余 text 作为新 TextPart 追加（若有）
                if remaining_text:
                    sequence.append(TextPart(text=remaining_text))
                self._logger.info(
                    "Stage 10.2: 检测到意外 reasoning tokens，转换 %d 个 ReasoningPart",
                    len(reasoning_parts),
                )

        # 组装 content parts
        invalid_tool_calls: list[_InvalidToolCall] = []
        for item in sequence:
            if isinstance(item, (TextPart, ReasoningPart)):
                content.append(item)
                continue
            if isinstance(item, tuple) and item[0] == "tool":
                key = item[1]
                assembly = tool_assemblies.get(key)
                if assembly is None or not assembly.tool_name:
                    # 对标 Cline: 记录缺少工具名的无效调用
                    invalid_tool_calls.append(_InvalidToolCall(
                        tool_call_id=assembly.tool_call_id if assembly else str(key),
                        reason="missing_name",
                        input=self._build_invalid_tool_input(
                            assembly.input_text if assembly else ""
                        ),
                    ))
                    continue

                # 解析工具输入
                parsed = self._parse_tool_input(assembly)
                if parsed.reason:
                    invalid_tool_calls.append(_InvalidToolCall(
                        tool_call_id=assembly.tool_call_id,
                        reason=parsed.reason,
                        tool_name=assembly.tool_name,
                        input=parsed.invalid_input,
                    ))
                    continue

                content.append(ToolCallPart(
                    tool_call_id=assembly.tool_call_id,
                    tool_name=assembly.tool_name,
                    input=parsed.input if isinstance(parsed.input, dict) else {},
                    # Stage 10.1 (C8/C18): metadata 合并 assembly 累积的 provider 元数据
                    # 对标 Cline PendingToolAssembly.metadata 写入 ToolCallPart.metadata
                    # 保留原 raw_input_text 字段（调试用），合并 assembly.metadata
                    metadata={
                        **({"raw_input_text": assembly.input_text} if assembly.input_text else {}),
                        **assembly.metadata,
                    },
                ))

        # 创建 assistant 消息
        message = create_message(MessageRole.ASSISTANT, content)
        if invalid_tool_calls:
            message.metadata["invalid_tool_calls"] = [
                {
                    "tool_call_id": itc.tool_call_id,
                    "tool_name": itc.tool_name,
                    "input": itc.input,
                    "reason": itc.reason,
                }
                for itc in invalid_tool_calls
            ]
        if self.config.message_model_info:
            message.model_info = dict(self.config.message_model_info)

        # 计算本轮用量增量
        usage_delta = self._compute_usage_delta(usage_before, self._state.usage)
        if usage_delta:
            message.metrics = usage_delta

        # after_model hooks
        stop_control = await self._call_after_model_hooks(message, finish_reason)
        if stop_control is not None and stop_control.stop:
            raise RuntimeError(stop_control.reason or "stopped by after_model hook")

        return message, finish_reason

    # ========================================================================
    # 工具执行 — 对标 Cline executeToolCalls() L1291-1310
    # ========================================================================

    async def _file_context_tracker_hook(
        self,
        ctx: AfterToolContext,
    ) -> AfterToolResult | None:
        """文件上下文追踪 after_tool hook — Phase 29.3 新增

        工具执行成功后，根据 tool_name + input 提取文件路径并记录到 tracker。
        失败的工具调用（is_error=True）不记录，避免噪声。

        工具名到操作的映射:
            - read_files / list_files: OP_READ
            - editor / apply_patch: OP_EDITED（已存在）/ OP_CREATED（新建）
            - file_write: OP_EDITED（覆盖）/ OP_CREATED（新建）

        路径提取规则（与 context.py::_summarize_tool_activity 一致）:
            - read_files: input.files[].path
            - list_files: input.path
            - editor / file_write: input.path
            - apply_patch: input.path 或 input.diff 中解析
        """
        # 工具失败时不记录
        if ctx.result.is_error:
            return None

        if self._file_tracker is None:
            return None

        tool_name = ctx.tool_call.tool_name
        tool_input = ctx.input if isinstance(ctx.input, dict) else {}
        iteration = ctx.snapshot.iteration if ctx.snapshot else 0

        try:
            from agent.file_context_tracker import (
                OP_CREATED, OP_DELETED, OP_EDITED, OP_READ,
            )

            # 按工具名提取路径并记录
            if tool_name in ("read_files", "file_read"):
                # read_files: input.files[].path
                files_list = tool_input.get("files", []) or []
                for item in files_list:
                    if isinstance(item, dict):
                        p = item.get("path", "")
                        if p:
                            self._file_tracker.record(
                                p, OP_READ,
                                tool_name=tool_name,
                                iteration=iteration,
                            )
                    elif isinstance(item, str) and item:
                        self._file_tracker.record(
                            item, OP_READ,
                            tool_name=tool_name,
                            iteration=iteration,
                        )
            elif tool_name == "list_files":
                # list_files: input.path（目录路径也记录为 read）
                p = tool_input.get("path", "")
                if p:
                    self._file_tracker.record(
                        p, OP_READ,
                        tool_name=tool_name,
                        iteration=iteration,
                    )
            elif tool_name in ("editor", "file_write", "apply_patch"):
                # 编辑类工具：提取 path 字段
                paths = []
                for key in ("path", "file_path", "target_file"):
                    v = tool_input.get(key)
                    if isinstance(v, str) and v:
                        paths.append(v)
                # apply_patch 可能用 diff 字段
                if tool_name == "apply_patch":
                    diff = tool_input.get("diff", "")
                    if isinstance(diff, str):
                        # 从 unified diff 头解析文件路径
                        for line in diff.splitlines():
                            if line.startswith("+++ ") or line.startswith("--- "):
                                # 形如 +++ b/path/to/file.py
                                parts = line[4:].split("/", 1)
                                if len(parts) == 2:
                                    paths.append(parts[1])
                                elif len(parts) == 1 and parts[0]:
                                    paths.append(parts[0])

                # 判断 created vs edited：根据 result 内容或路径是否存在
                # 简化策略：file_write 时若 result 含 "created" 标志则为 created，
                # 否则统一记为 edited（保守策略，不依赖文件系统检查）
                operation = OP_EDITED
                result_output = ctx.result.output
                if isinstance(result_output, dict):
                    created_flag = result_output.get("created") or result_output.get("is_new")
                    if created_flag:
                        operation = OP_CREATED
                elif isinstance(result_output, str) and "created" in result_output.lower():
                    operation = OP_CREATED

                for p in paths:
                    self._file_tracker.record(
                        p, operation,
                        tool_name=tool_name,
                        iteration=iteration,
                    )
            elif tool_name in ("exec", "run_commands"):
                # 命令执行不记录文件，跳过
                pass

            # 持久化 tracker 状态（每次工具调用后写盘，保证崩溃不丢数据）
            # 工具调用不是高频操作，性能影响可接受
            self._file_tracker.save()

            # Stage 6.7 新增：推送 file_context_updated SSE 事件
            # 对标 Cline 的实时事件推送，前端无需轮询 GET /file_context
            try:
                state = self._file_tracker.get_state()
                await self._emit_sse_event("file_context_updated", {
                    "session_id": self.config.session_id,
                    "state": state,
                })
            except Exception as e:
                logger.debug("FileContextTracker SSE 推送失败（已忽略）: %s", e)
        except Exception as e:
            # 追踪失败不影响主流程
            logger.debug("FileContextTracker 记录失败（已忽略）: %s", e)

        return None

    # ------------------------------------------------------------------
    # Stage 6.7: SSE 事件回调机制 — runtime 主动推送事件给前端
    # ------------------------------------------------------------------

    def register_sse_event_callback(self, callback) -> None:
        """注册 SSE 事件回调 — Stage 6.7 新增

        callback 签名: async def callback(event_type: str, data: dict) -> None
        server.py 的 stream_chat 函数注册回调，将事件放入 asyncio.Queue，
        SSE 生成器从队列读取并 yield。

        Args:
            callback: 异步事件回调函数
        """
        self._sse_event_callbacks.append(callback)

    async def _emit_sse_event(self, event_type: str, data: dict) -> None:
        """向所有注册的 SSE 回调推送事件 — Stage 6.7 新增

        回调失败不影响主流程（仅记录 debug 日志），避免 tracker 异常阻塞工具执行。

        Args:
            event_type: 事件类型（如 file_context_updated）
            data: 事件数据
        """
        if not self._sse_event_callbacks:
            return
        for callback in self._sse_event_callbacks:
            try:
                await callback(event_type, data)
            except Exception as e:
                logger.debug("SSE 事件回调异常（已忽略）: %s", e)

    async def _loop_detection_hook(
        self,
        ctx: BeforeToolContext,
    ) -> BeforeToolResult | None:
        """循环检测 before_tool hook — 对标 Cline loop-detection beforeTool hook

        检查 LLM 是否连续以相同参数调用同一工具。

        Stage 5.1 (M3) 增强: 软阈值触发时，将 verdict.message 作为 user 消息追加到
            self._state.messages 并发射 message_added 事件，让 LLM 在下一轮看到
            "建议换思路"提示后主动改变策略（对标 Cline session-runtime-orchestrator.ts
            L1256-1263 的 soft 分支）。工具调用本身不阻止。

        Stage 5.2 (M4) 增强: 硬阈值不直接返回 stop，而是调用 MistakeTracker.record(
            force_at_limit=True)，由 MistakeTracker 的 outcome.action=="stop" 决定是否
            abort。统一 abort 路径，让 status 一致为 "aborted"（关联 M10 修复）。
            对标 Cline session-runtime-orchestrator.ts L1265-1308 的 hard 分支。
        """
        if ctx.tool_call is None:
            return None
        verdict = self._loop_tracker.inspect(
            ctx.tool_call.tool_name,
            ctx.input,
        )
        if verdict.kind == "hard":
            # Stage 5.2 (M4): 硬阈值联动 MistakeTracker — 对标 Cline enqueueMistakeRecord
            # 调用 record(force_at_limit=True) 让 MistakeTracker 立即达到 max_total，
            # 由 outcome.action 决定后续行为
            outcome = self._mistake_tracker.record(
                iteration=self._state.iteration,
                mistake_type=MistakeType.EXEC_ERROR,
                tool_name=ctx.tool_call.tool_name,
                details=verdict.message or "",
                force_at_limit=True,
            )
            if outcome.action == "stop":
                # 调用 abort 让 status="aborted"（关联 M10 修复），与 Cline activeRuntime.abort 对齐
                stop_reason = outcome.message or verdict.message or "Loop detection hard limit reached"
                self.abort(stop_reason)
                return BeforeToolResult(stop=True, reason=stop_reason)
            if outcome.action == "continue_with_guidance" and outcome.guidance:
                # 复用 5.1 的注入逻辑：把 guidance 作为 user 消息追加并 emit
                await self._inject_user_notice(outcome.guidance)
                return None
            # outcome.action == "continue" 兜底（force_at_limit 后理论上不会走到）
            return None
        if verdict.kind == "soft":
            # Stage 5.1 (M3): 软阈值注入 LLM 上下文 — 对标 Cline soft 分支
            # 保留原 logger.warning 日志（不删除原逻辑）
            logger.warning(
                "Loop detection soft warning: %s",
                verdict.message,
            )
            # 将 verdict.message 作为 user 消息追加并 emit message_added 事件
            if verdict.message:
                await self._inject_user_notice(verdict.message)
        return None

    async def _inject_user_notice(self, text: str) -> None:
        """将文本作为 user 消息追加到 messages 并 emit message_added 事件

        Stage 5.1 (M3) 新增：辅助 _loop_detection_hook 的 soft 分支与
        Stage 5.2 (M4) 的 continue_with_guidance 分支复用。
        对标 Cline session-runtime-orchestrator.ts L1258-1261:
            this.conversation.appendMessage({
                role: "user",
                content: [{ type: "text", text: verdict.message }]
            })
        """
        notice_msg = create_text_message(MessageRole.USER, text)
        self._state.messages.append(notice_msg)
        await self._emit(make_message_added(self.snapshot(), notice_msg))

    def _check_repeated_tool_failures(
        self,
        tool_calls: list[ToolCallPart],
        tool_messages: list[AgentMessage],
        threshold: int = 3,
    ) -> None:
        """检测工具重复失败死循环 — Phase 26

        如果同一工具、同一错误连续出现 threshold 次，主动抛出 RuntimeError，
        避免 LLM 在同样的参数错误上无限重试直到 max_iterations。

        Args:
            tool_calls: 本轮调用的工具
            tool_messages: 对应的工具结果消息
            threshold: 连续重复错误阈值

        Raises:
            RuntimeError: 检测到重复失败死循环
        """
        for tc, tm in zip(tool_calls, tool_messages):
            tool_result_part = next(
                (part for part in tm.content if isinstance(part, ToolResultPart)),
                None,
            )
            if tool_result_part is None or not tool_result_part.is_error:
                # 成功调用清空历史，避免跨任务累积误报
                self._recent_tool_errors = [
                    entry for entry in self._recent_tool_errors
                    if entry[0] != tc.tool_name
                ]
                # Phase 28.1: 成功调用重置 MistakeTracker
                self._mistake_tracker.reset()
                continue

            error_text = str(tool_result_part.output or "")[:200]

            # Phase 28.1: MistakeTracker 记录错误（按类型分类计数）
            mistake_type = classify_mistake(error_text)
            outcome = self._mistake_tracker.record(
                iteration=self._state.iteration,
                mistake_type=mistake_type,
                tool_name=tc.tool_name,
                details=error_text,
            )
            if outcome.action == "stop":
                # Stage 5.2 (M4): 调用 abort 让 status="aborted"（关联 M10 修复），
                # 对标 Cline activeRuntime.abort 的统一中止路径
                stop_reason = outcome.message or "MistakeTracker 达到硬阈值上限"
                self.abort(stop_reason)
                raise RuntimeError(self._abort_reason)
            if outcome.action == "continue_with_guidance" and outcome.guidance:
                # 把恢复提示作为 user message 注入下一轮 LLM 上下文
                guidance_msg = create_text_message(MessageRole.USER, outcome.guidance)
                self._state.messages.append(guidance_msg)

            # 保留原有"同一工具同一错误连续 N 次"硬阈值逻辑（Phase 26）
            entry = (tc.tool_name, error_text)
            self._recent_tool_errors.append(entry)

            # 统计同一工具同一错误的连续次数
            consecutive = 0
            for prev_name, prev_err in reversed(self._recent_tool_errors):
                if prev_name != tc.tool_name:
                    break
                if prev_err == error_text:
                    consecutive += 1
                else:
                    break

            if consecutive >= threshold:
                raise RuntimeError(
                    f"检测到工具 {tc.tool_name} 连续 {consecutive} 次以相同错误失败: "
                    f"{error_text}。已中止运行，请检查工具参数或提示词。"
                )

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCallPart],
    ) -> list[AgentMessage]:
        """执行工具调用 — 对标 Cline executeToolCalls()

        支持 parallel 和 sequential 两种模式。
        """
        prepared = [await self._prepare_tool_execution(tc) for tc in tool_calls]

        if self.config.tool_execution == "parallel":
            results = await asyncio.gather(
                *[self._execute_prepared_tool(p) for p in prepared]
            )
            return list(results)

        results: list[AgentMessage] = []
        for p in prepared:
            results.append(await self._execute_prepared_tool(p))
        return results

    async def _prepare_tool_execution(
        self,
        tool_call: ToolCallPart,
    ) -> _PreparedToolExecution:
        """准备工具执行 — 对标 Cline prepareToolExecution() L1334-1422

        1. 从注册表解析工具
        2. 规范化输入
        3. before_tool hooks（可 skip/修改 input/stop）
        4. 工具策略检查
        5. 工具审批检查（Phase 19 新增，对标 Cline tool-approval）
        """
        tool = self._tools.get(tool_call.tool_name)
        input_value: Any = tool_call.input
        skip_reason: str | None = None

        # Phase 26: 按 Schema 规范化输入 — 对标 Cline normalizeJsonLikeStringsForSchema
        # 在 before_tool hooks 之前执行，确保钩子拿到的是规范化后的输入
        if tool is not None:
            input_value = self._normalize_input_for_schema(
                input_value, tool.input_schema
            )

        if tool is not None:
            # before_tool hooks
            # Stage 5.7 (U2): 收集 hook 返回的 policy 覆盖 — 对标 Cline agent-runtime.ts L1381-1386
            # `policyOverride = {...policyOverride, ...result.policy}`
            policy_override: dict[str, Any] = {}
            # Stage 12.3 (P9): 收集 hook 返回的 additional_context — 对标 Cline beforeTool additionalContext
            # 在工具调用前作为 system message 注入到 messages，LLM 下一轮能看到
            additional_contexts: list[str] = []
            for hook in self._hooks.before_tool:
                ctx = BeforeToolContext(
                    snapshot=self.snapshot(),
                    tool=tool,
                    tool_call=tool_call,
                    input=input_value,
                )
                result = await self._call_hook(hook, ctx)
                if result is None:
                    continue
                if result.input is not None:
                    input_value = result.input
                # Stage 5.7 (U2): 合并 hook 返回的 policy 覆盖
                if result.policy:
                    policy_override = {**policy_override, **result.policy}
                # Stage 12.3 (P9): 收集 additional_context（不 break，继续处理其他 hook）
                if result.additional_context:
                    additional_contexts.append(result.additional_context)
                if result.skip:
                    skip_reason = result.reason or f"Tool {tool_call.tool_name} was blocked by a runtime hook"
                    break
                if result.stop:
                    # Stage 10.4 (B33): 区分用户 hook stop 与系统安全 stop
                    # 对标 Cline ControlledStopError：hook 主动 stop 是受控停止，非失败
                    # - 用户配置的 hook stop（未触发 abort）→ ControlledStopError
                    #   主循环 catch 后 status="completed", finish_reason="controlled_stop"
                    # - 系统安全 stop（loop detection / mistake tracker 已调用 abort）
                    #   保持 RuntimeError，主循环 catch 后 status="aborted"
                    if self._aborted:
                        # 系统安全 hook 已调用 abort，保持原 RuntimeError 路径
                        raise RuntimeError(result.reason or "stopped by system safety hook")
                    # 用户 hook 主动 stop — Stage 10.4 (B33) 新增
                    raise ControlledStopError(
                        reason=result.reason or "stopped by before_tool hook",
                        source="hook",
                    )

            # Stage 12.3 (P9): 注入 hook 返回的 additional_context 到 messages
            # 对标 Cline beforeTool hook 的 additionalContext 注入逻辑：
            #   - 作为 system message 追加到 self._state.messages
            #   - LLM 下一轮能看到注入的上下文（如 git 分支、文件列表等）
            #   - 单次工具调用最多注入 5 条（防止 hook 失控）
            MAX_HOOK_CONTEXT_INJECTIONS = 5
            if additional_contexts and not skip_reason:
                if len(additional_contexts) > MAX_HOOK_CONTEXT_INJECTIONS:
                    logger.warning(
                        "before_tool hook 返回 %d 条 additional_context，超过上限 %d，仅注入前 %d 条",
                        len(additional_contexts), MAX_HOOK_CONTEXT_INJECTIONS,
                        MAX_HOOK_CONTEXT_INJECTIONS,
                    )
                    additional_contexts = additional_contexts[:MAX_HOOK_CONTEXT_INJECTIONS]
                for context_text in additional_contexts:
                    if not context_text or not context_text.strip():
                        continue
                    # 注入为 USER 消息（兼容性：MessageRole.SYSTEM 部分模型不支持），
                    # 加 [System Reminder] 前缀标识来源
                    injection_msg = create_text_message(
                        MessageRole.USER,
                        f"[System Reminder] {context_text}",
                        metadata={
                            "kind": "hook_context_injection",
                        },
                    )
                    self._state.messages.append(injection_msg)
                    await self._emit(make_message_added(self.snapshot(), injection_msg))

        # Stage 9.1 (Q8): MCP per-tool auto_approve 策略注入 — 对标 Cline mcp-policy-loader
        # 对 use_mcp_tool 工具，从 MCPRegistry 查询调用的具体 MCP 工具策略，
        # 转换为 runtime 的 autoApprove/enabled 字段，合并到 policy_override
        # 优先级：global_policy("*.") → per-tool policy → MCP per-tool policy → hook policy_override
        # MCP auto_approve=true 时跳过审批，auto_approve=false 时强制审批
        if tool is not None and tool_call.tool_name == "use_mcp_tool":
            mcp_policy_override = self._get_mcp_tool_policy_override(tool_call)
            if mcp_policy_override:
                policy_override = {**policy_override, **mcp_policy_override}

        # 工具策略检查
        # Stage 5.7 (U2): 三态语义 — 对标 Cline resolveToolPolicy + agent-runtime.ts L1396-1413
        #   - enabled is False → deny（工具被禁用，直接 skip）
        #   - autoApprove is False → ask（走 _request_tool_approval 审批流程）
        #   - 默认（未设/True）→ 按原逻辑（requires_approval + auto_approve）决定
        # 合并顺序：global_policy("*.") → per-tool policy → MCP policy → hook policy_override
        if tool is not None and skip_reason is None:
            policy = self.config.tool_policies.get(tool_call.tool_name, {})
            global_policy = self.config.tool_policies.get("*", {})
            merged = {**global_policy, **policy, **policy_override}
            if merged.get("enabled") is False:
                skip_reason = merged.get("reason") or f'Tool "{tool_call.tool_name}" is disabled by policy'
            elif merged.get("autoApprove") is False:
                # 显式配置需审批，无论 tool.requires_approval 如何
                skip_reason = await self._request_tool_approval(tool_call, input_value)

        # Phase 19: 工具审批检查 — 对标 Cline tool-approval
        # requires_approval=True 且 auto_approve=False 时，挂起等待用户审批
        # Stage 5.7 (U2): 仅当策略未显式设 autoApprove 时，按工具属性 + 全局开关决定
        if tool is not None and skip_reason is None:
            policy = self.config.tool_policies.get(tool_call.tool_name, {})
            global_policy = self.config.tool_policies.get("*", {})
            merged = {**global_policy, **policy, **policy_override}
            # 若策略已显式设 autoApprove（True 或 False），则不再走 requires_approval 兜底
            auto_approve_explicit = "autoApprove" in merged
            if not auto_approve_explicit:
                requires_approval = getattr(tool, "requires_approval", False)
                if requires_approval and not self.config.auto_approve:
                    skip_reason = await self._request_tool_approval(
                        tool_call, input_value,
                    )

        return _PreparedToolExecution(
            tool_call=ToolCallPart(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                input=input_value if isinstance(input_value, dict) else {},
            ),
            tool=tool,
            input=input_value,
            skip_reason=skip_reason,
        )

    def _get_mcp_tool_policy_override(
        self,
        tool_call: ToolCallPart,
    ) -> dict[str, Any]:
        """获取 MCP 工具的策略覆盖 — Stage 9.1 (Q8) 新增

        对标 Cline mcp-policy-loader.ts：当 agent 调用 use_mcp_tool 时，
        从 MCPRegistry 查询该具体 MCP 工具的 per-tool 策略
        （mcp_servers.yaml 中 tool_policies 段），转换为 runtime 的
        autoApprove/enabled 字段。

        语义映射:
            - MCP auto_approve=True  → autoApprove=True（跳过审批）
            - MCP auto_approve=False → autoApprove=False（强制审批）
            - MCP enabled=False      → enabled=False（禁用工具）
            - 无策略配置             → 返回空 dict（走默认逻辑）

        P1-19 增强: 无 per-tool 策略时，额外检查服务器的 auto_approve 列表
        （对标 Cline McpHub.listTools 的 autoApprove 机制）。
        若工具在 auto_approve 列表中，返回 autoApprove=True 跳过审批。
        优先级：per-tool 策略 > 服务器 auto_approve 列表 > 默认逻辑

        Args:
            tool_call: 工具调用片段（需含 server_name/tool_name 输入）

        Returns:
            策略 dict（含 autoApprove/enabled 字段），无策略时返回空 dict
        """
        input_value = tool_call.input if isinstance(tool_call.input, dict) else {}
        server_name = input_value.get("server_name", "")
        mcp_tool_name = input_value.get("tool_name", "")
        if not server_name or not mcp_tool_name:
            return {}
        try:
            from agent.mcp.registry import get_registry
            registry = get_registry()
            policy = registry.get_tool_policy(server_name, mcp_tool_name)
        except Exception as e:
            logger.warning(
                f"Stage 9.1: 获取 MCP 工具策略失败 "
                f"({server_name}/{mcp_tool_name}): {e}"
            )
            return {}
        if policy is None:
            # P1-19: 无 per-tool 策略时，检查服务器的 auto_approve 列表
            # 对标 Cline McpHub.listTools 的 autoApprove 机制:
            # servers 段配置的 auto_approve 列表中的工具自动跳过审批
            # 注意: per-tool 策略优先级更高，仅当无 per-tool 策略时才检查列表
            try:
                if registry.is_tool_auto_approved(server_name, mcp_tool_name):
                    logger.info(
                        f"P1-19: MCP 工具 {server_name}/{mcp_tool_name} "
                        f"在 auto_approve 列表中，自动跳过审批"
                    )
                    return {"autoApprove": True}
            except Exception as e:
                logger.warning(
                    f"P1-19: 查询 auto_approve 列表失败 "
                    f"({server_name}/{mcp_tool_name}): {e}"
                )
            return {}
        logger.info(
            f"Stage 9.1: 命中 MCP per-tool 策略 "
            f"{server_name}/{mcp_tool_name} "
            f"(enabled={policy.enabled}, auto_approve={policy.auto_approve})"
        )
        return {
            "autoApprove": policy.auto_approve,
            "enabled": policy.enabled,
        }

    async def _request_tool_approval(
        self,
        tool_call: ToolCallPart,
        input_value: Any,
    ) -> str | None:
        """请求工具审批 — Phase 19 新增，对标 Cline requestDesktopToolApproval

        Phase 23 增强: 调用 before_approval 钩子，可自动决策（跳过用户审批）
            - 白名单命令自动批准（如 ls / cat / git status）
            - 黑名单命令自动拒绝（如 rm -rf）
            - 无钩子决策时走默认用户审批流程

        1. 调用 before_approval 钩子（Phase 23 新增）
        2. 钩子未决策时: 创建审批请求 + emit + 等待用户
        3. 钩子决策 approved: 直接返回 None（跳过用户审批）
        4. 钩子决策 denied: 返回拒绝原因

        Args:
            tool_call: 工具调用片段
            input_value: 工具输入参数

        Returns:
            None 表示批准，非 None 字符串表示拒绝原因（作为 skip_reason）
        """
        from agent.approval import (
            request_approval,
            get_approval_result,
            clear_approval,
            APPROVAL_TIMEOUT_SECONDS,
            is_auto_approved,
        )

        # Stage 5.6 (U10): 会话级"始终允许"记忆检查 — 优先级最高
        # 用户在审批卡片勾选"始终允许此工具"后，后续该会话内对同一工具的调用直接跳过审批
        # 对标 Cline autoApprove 三层粒度中的会话级（VS Code 端 autoApprovalSettings.actions）
        session_id = self.config.session_id or ""
        if is_auto_approved(session_id, tool_call.tool_name):
            logger.info(
                f"工具 {tool_call.tool_name} 已被会话级记忆自动批准（session={session_id}）"
            )
            return None

        # Phase 23: before_approval 钩子 — 审批前自动决策
        # 对标 Cline 审批钩子，可在 emit 审批请求前自动批准/拒绝
        # 典型用途: 白名单命令自动批准、黑名单命令自动拒绝
        if self._hooks.before_approval:
            input_dict = input_value if isinstance(input_value, dict) else {}
            for hook in self._hooks.before_approval:
                ctx = BeforeApprovalContext(
                    snapshot=self.snapshot(),
                    tool_name=tool_call.tool_name,
                    tool_call_id=tool_call.tool_call_id,
                    input=input_dict,
                )
                hook_result = await self._call_hook(hook, ctx)
                if hook_result is None or hook_result.decision is None:
                    continue
                if hook_result.decision == "approved":
                    logger.info(
                        f"工具审批自动通过（before_approval 钩子）: "
                        f"{tool_call.tool_name}, reason={hook_result.reason}"
                    )
                    return None
                elif hook_result.decision == "denied":
                    reason = hook_result.reason or f"工具 {tool_call.tool_name} 被 before_approval 钩子拒绝"
                    logger.info(
                        f"工具审批自动拒绝（before_approval 钩子）: "
                        f"{tool_call.tool_name}, reason={reason}"
                    )
                    return reason

        # 创建审批请求
        entry = request_approval(
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_name,
            input=input_value if isinstance(input_value, dict) else {},
            session_id=self.config.session_id or "",
        )

        # emit approval_request 事件到前端 — 通过 STATUS_NOTICE 转发
        approval_event = AgentEvent(
            type=STATUS_NOTICE,
            snapshot=self.snapshot(),
            notice=f"approval_request from {tool_call.tool_name}",
            metadata={
                "type": "approval_request",
                "tool_call_id": tool_call.tool_call_id,
                "tool_name": tool_call.tool_name,
                "input": input_value if isinstance(input_value, dict) else {},
            },
        )
        await self._emit(approval_event)

        logger.info(
            f"等待工具审批: tool={tool_call.tool_name}, "
            f"tool_call_id={tool_call.tool_call_id}, "
            f"timeout={APPROVAL_TIMEOUT_SECONDS}s"
        )

        # 等待审批结果（带超时）
        try:
            await asyncio.wait_for(
                entry.event.wait(),
                timeout=APPROVAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            clear_approval(tool_call.tool_call_id)
            return f"工具 {tool_call.tool_name} 审批超时（{int(APPROVAL_TIMEOUT_SECONDS)} 秒）"

        # 读取审批结果
        result = get_approval_result(tool_call.tool_call_id)
        clear_approval(tool_call.tool_call_id)

        if result == "approved":
            logger.info(f"工具审批通过: {tool_call.tool_name}")
            return None
        else:
            reason = f"工具 {tool_call.tool_name} 被用户拒绝"
            logger.info(f"工具审批拒绝: {tool_call.tool_name}")
            return reason

    async def _execute_prepared_tool(
        self,
        prepared: _PreparedToolExecution,
    ) -> AgentMessage:
        """执行准备好的工具 — 对标 Cline executePreparedTool() L1464-1560

        1. emit(tool_started)
        2. 执行 tool.execute() 或返回 skip/unknown 错误
        3. after_tool hooks（可修改 result）
        4. 构建 tool result 消息
        5. emit(tool_finished)
        """
        started_at = datetime.now(timezone.utc)

        # 发射 tool-started 事件
        await self._emit(make_tool_started(
            self.snapshot(), self._state.iteration,
            prepared.tool_call.tool_name,
            prepared.tool_call.tool_call_id,
            prepared.input,
        ))

        # 执行工具
        if prepared.skip_reason:
            result = AgentToolResult(
                output={"error": prepared.skip_reason},
                is_error=True,
            )
        elif prepared.tool is None:
            result = AgentToolResult(
                output={"error": f"Unknown tool: {prepared.tool_call.tool_name}"},
                is_error=True,
            )
        else:
            # Phase 12: emit_update 通过 STATUS_NOTICE 事件转发到事件流，
            # 让 Plan Mode 工具的 update（如
            # mode_changed）能被 SSE 层接收并发给前端
            # Stage 10.5 (A7): 填充 metadata 字段 — 对标 Cline AgentToolContext.metadata
            # 标准键名见 AGENT_TOOL_METADATA_KEYS，工具按需读取运行时上下文
            tool_metadata = {
                "run_id": self._state.run_id or "",
                "iteration": self._state.iteration,
                "trigger_source": "user",  # 默认用户触发，未来扩展 checkpoint/scheduler
                "verbose": bool(getattr(self.config, "verbose", False)),
            }
            context = AgentToolContext(
                agent_id=self._state.agent_id,
                session_id=self.config.session_id,
                conversation_id=self.config.conversation_id,
                run_id=self._state.run_id,
                iteration=self._state.iteration,
                tool_call_id=prepared.tool_call.tool_call_id,
                snapshot=self.snapshot(),
                emit_update=self._make_emit_update(
                    prepared.tool_call.tool_name,
                    prepared.tool_call.tool_call_id,
                ),
                abort_signal=self._abort_controller.signal,
                metadata=tool_metadata,
            )
            # Phase 29.2: 带超时和重试的工具执行
            try:
                result = await self._execute_with_timeout_and_retry(
                    prepared.tool, prepared.input, context
                )
            except asyncio.TimeoutError:
                # 重试耗尽后的最终超时
                timeout_ms = (
                    prepared.tool.timeout_ms
                    if prepared.tool.timeout_ms is not None
                    else self.config.default_tool_timeout_ms
                )
                max_retries = prepared.tool.max_retries if prepared.tool.retryable else 0
                logger.warning(
                    "工具执行超时（重试耗尽）: %s (%d ms, retries=%d)",
                    prepared.tool_call.tool_name, timeout_ms, max_retries,
                )
                result = AgentToolResult(
                    output={
                        "error": f"工具 {prepared.tool_call.tool_name} 执行超时"
                                 f"（{timeout_ms} ms，已重试 {max_retries} 次）"
                    },
                    is_error=True,
                )
            except AbortedError:
                # Phase 28.2: 中止异常向上传播，由主循环处理状态
                raise
            except Exception as e:
                max_retries = prepared.tool.max_retries if prepared.tool.retryable else 0
                result = AgentToolResult(
                    output={
                        "error": f"工具执行失败（已重试 {max_retries} 次）: {e}",
                    },
                    is_error=True,
                )

        ended_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))

        # after_tool hooks — 可修改 result
        if prepared.tool is not None:
            for hook in self._hooks.after_tool:
                ctx = AfterToolContext(
                    snapshot=self.snapshot(),
                    tool=prepared.tool,
                    tool_call=prepared.tool_call,
                    input=prepared.input,
                    result=result,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                )
                after_result = await self._call_hook(hook, ctx)
                if after_result is not None:
                    if after_result.result is not None:
                        result = after_result.result
                    if after_result.stop:
                        raise RuntimeError(after_result.reason or "stopped by after_tool hook")

        # 构建 tool result 消息
        # Phase 26: 与 Cline 一致，ToolResultPart.output 保持原始类型，
        # 不由 runtime 强制序列化为字符串。序列化仅在事件展示 / provider
        # 请求时进行。
        # P0-7: 对存入 message history 的 output 进行 head+tail 截断，
        # 防止大输出工具（如 run_commands / search_codebase）撑爆上下文。
        # 对标 Cline 48000 字符 head+tail 策略。
        output_for_msg = result.output
        serialized_for_msg = self._serialize_tool_output(
            result.output, prepared.tool_call.tool_name
        )
        MAX_MSG_OUTPUT_CHARS = 48000
        if len(serialized_for_msg) > MAX_MSG_OUTPUT_CHARS:
            half = MAX_MSG_OUTPUT_CHARS // 2
            output_for_msg = (
                serialized_for_msg[:half]
                + f"\n\n[...输出已截断，原始长度 {len(serialized_for_msg)} 字符...]\n\n"
                + serialized_for_msg[-half:]
            )

        message = create_message(MessageRole.TOOL, [
            ToolResultPart(
                tool_call_id=prepared.tool_call.tool_call_id,
                tool_name=prepared.tool_call.tool_name,
                output=output_for_msg,
                is_error=result.is_error,
            )
        ])

        # 发射 tool-finished 事件：前端展示需要字符串形式
        output_for_event = self._serialize_tool_output(
            result.output, prepared.tool_call.tool_name
        )
        await self._emit(make_tool_finished(
            self.snapshot(), self._state.iteration,
            prepared.tool_call.tool_name,
            prepared.tool_call.tool_call_id,
            output_for_event,
            result.is_error,
            duration_ms,
        ))

        return message

    # ========================================================================
    # 带超时和重试的工具执行 — Phase 29.2 新增
    # ========================================================================

    async def _execute_with_timeout_and_retry(
        self,
        tool: AgentTool,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """带超时和重试的工具执行 — Phase 29.2 新增，对标 Cline withTimeout + retryable

        执行流程:
            1. 按 tool.timeout_ms（或 default_tool_timeout_ms）设置超时
            2. retryable=True 时按 max_retries 重试，间隔指数退避（200ms * 2^n）
            3. AbortedError 不重试（用户中止应立即生效）
            4. schema 校验失败不重试（参数错误重试也不会变）
            5. 工具返回 is_error=True 的结果时，retryable=True 则重试

        重试策略:
            - 退避公式: delay = 0.2 * (2 ** attempt) 秒
            - attempt=0（首次）失败后等 0.2s 重试
            - attempt=1 失败后等 0.4s 重试
            - attempt=2 失败后等 0.8s 重试
            - 达到 max_retries 后返回最后一次错误结果

        Args:
            tool: 工具实例
            input: 工具输入参数（已通过 schema 校验）
            context: 工具执行上下文

        Returns:
            AgentToolResult: 工具执行结果（重试耗尽时返回最后一个错误结果）

        Raises:
            asyncio.TimeoutError: 重试耗尽后仍超时（由 _execute_prepared_tool 捕获）
            AbortedError: 用户中止（不重试，直接抛出）
        """
        timeout_ms = (
            tool.timeout_ms
            if tool.timeout_ms is not None
            else self.config.default_tool_timeout_ms
        )
        max_retries = tool.max_retries if tool.retryable else 0

        last_exception: Exception | None = None
        last_error_result: AgentToolResult | None = None

        for attempt in range(max_retries + 1):
            try:
                if timeout_ms and timeout_ms > 0:
                    output = await asyncio.wait_for(
                        tool.execute(input, context),
                        timeout=timeout_ms / 1000.0,
                    )
                else:
                    output = await tool.execute(input, context)

                # 工具可能直接返回 AgentToolResult（BaseTool 体系），
                # 也可能返回原始输出（对标 Cline 的 raw tool return）
                if isinstance(output, AgentToolResult):
                    result = output
                else:
                    result = AgentToolResult(output=output)

                # 成功：直接返回
                if not result.is_error:
                    return result

                # 检查是否是 schema 校验错误（不重试）
                # schema 校验失败的 output 包含 validation_errors 字段
                if (
                    isinstance(result.output, dict)
                    and "validation_errors" in result.output
                ):
                    return result

                # is_error 结果：retryable=True 时重试
                if attempt < max_retries:
                    last_error_result = result
                    delay = 0.2 * (2 ** attempt)
                    error_brief = str(result.output)[:100]
                    logger.info(
                        "工具 %s 第 %d/%d 次返回错误: %s，%.2fs 后重试",
                        tool.name, attempt + 1, max_retries + 1,
                        error_brief, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                # 重试耗尽，返回最后一个错误结果
                return result

            except AbortedError:
                # 用户中止，不重试，立即抛出
                raise
            except asyncio.TimeoutError as e:
                last_exception = e
                if attempt < max_retries:
                    delay = 0.2 * (2 ** attempt)
                    logger.info(
                        "工具 %s 第 %d/%d 次超时（%d ms），%.2fs 后重试",
                        tool.name, attempt + 1, max_retries + 1,
                        timeout_ms, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                # 重试耗尽，抛出最后一次超时
                raise
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    delay = 0.2 * (2 ** attempt)
                    logger.info(
                        "工具 %s 第 %d/%d 次失败: %s，%.2fs 后重试",
                        tool.name, attempt + 1, max_retries + 1,
                        str(e)[:100], delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                # 重试耗尽，抛出最后一次异常
                raise

        # 重试耗尽：优先返回最后一个 is_error 结果，否则抛出异常
        if last_error_result is not None:
            return last_error_result
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("retry exhausted without exception or result")

    # ========================================================================
    # completes_run 检测 — 对标 Cline findCompletingToolMessage() L1312-1332
    # ========================================================================

    def _find_completing_tool(
        self,
        tool_calls: list[ToolCallPart],
        tool_messages: list[AgentMessage],
    ) -> AgentMessage | None:
        """检查是否有 completes_run 工具成功执行

        对标 Cline findCompletingToolMessage()。
        如果工具的 lifecycle.completes_run=True 且执行成功（非 error），
        则返回对应的 tool message，AgentRuntime 据此结束运行。
        """
        for i, tool_call in enumerate(tool_calls):
            tool = self._tools.get(tool_call.tool_name)
            if tool is None:
                continue
            lifecycle = getattr(tool, "lifecycle", None)
            if lifecycle is None or not lifecycle.completes_run:
                continue

            if i >= len(tool_messages):
                continue
            tool_message = tool_messages[i]
            for part in tool_message.content:
                if isinstance(part, ToolResultPart):
                    if part.tool_call_id == tool_call.tool_call_id and not part.is_error:
                        return tool_message
        return None

    # ========================================================================
    # 钩子调用 — 对标 Cline callBeforeRunHooks / callAfterRunHooks 等
    # ========================================================================

    async def _call_before_run_hooks(self) -> None:
        """调用 before_run 钩子 — 对标 Cline callBeforeRunHooks() L796-803"""
        for hook in self._hooks.before_run:
            ctx = RunLifecycleContext(snapshot=self.snapshot())
            control = await self._call_hook(hook, ctx)
            if control is not None and control.stop:
                raise ControlledStopError(control.reason or "stopped by before_run hook")

    async def _call_after_run_hooks(self, result: AgentRunResult) -> None:
        """调用 after_run 钩子 — 对标 Cline callAfterRunHooks() L805-809"""
        for hook in self._hooks.after_run:
            ctx = AfterRunContext(snapshot=self.snapshot(), result=result)
            await self._call_hook(hook, ctx)

    async def _call_before_model_hooks(
        self,
        request: AgentModelRequest,
    ) -> StopControl | None:
        """调用 before_model 钩子 — 对标 Cline before_model hooks L840-865

        可修改 request 的 messages/tools/options。

        Stage 11.2 (J12): 传递 abort_signal 到 BeforeModelContext，
        让 before_model 钩子（如 ContextCompactor 的 fallback 路径）能响应中止信号。
        """
        for hook in self._hooks.before_model:
            ctx = BeforeModelContext(
                snapshot=self.snapshot(),
                request=request,
                session_id=self.config.session_id,
                # Stage 11.2 (J12): 透传 abort signal 给钩子
                abort_signal=self._abort_controller.signal,
            )
            result = await self._call_hook(hook, ctx)
            if result is None:
                continue
            if result.messages is not None:
                request.messages = list(result.messages)
            if result.tools is not None:
                request.tools = list(result.tools)
            if result.options is not None:
                request.options.update(result.options)
            if result.stop:
                return StopControl(stop=True, reason=result.reason)
        return None

    async def _call_after_model_hooks(
        self,
        message: AgentMessage,
        finish_reason: str,
    ) -> StopControl | None:
        """调用 after_model 钩子 — 对标 Cline after_model hooks L1067-1074"""
        for hook in self._hooks.after_model:
            ctx = AfterModelContext(
                snapshot=self.snapshot(),
                assistant_message=message,
                finish_reason=finish_reason,
            )
            control = await self._call_hook(hook, ctx)
            if control is not None and control.stop:
                return control
        return None

    # ========================================================================
    # 内部辅助方法
    # ========================================================================

    async def _emit(self, event: AgentEvent) -> None:
        """发射事件"""
        await self._emitter.emit(event)

    def _make_emit_update(
        self,
        tool_name: str,
        tool_call_id: str,
    ) -> Callable[[Any], None]:
        """构造 emit_update 回调 — Phase 12 新增，Phase 2.5 改用 TOOL_UPDATED 事件

        工具通过 context.emit_update(update) 发送的 update（如 todos_updated /
        mode_changed）会被转为 TOOL_UPDATED 事件，进入事件流。

        Phase 2.5: 对标 Cline agent-runtime.ts L1498-1506 的 emitUpdate，
                    事件类型从 STATUS_NOTICE 改为 TOOL_UPDATED，并补充 tool_call_id
                    和 iteration 字段，让前端能区分"工具进度更新"与"普通状态通知"。

        Phase 35.1: 改用 emit_sync 同步发射，解决 asyncio.create_task 时序问题。
                    原实现用 asyncio.create_task(self._emit(event)) fire-and-forget，
                    task 不会立即执行，需等事件循环调度。在 run_commands._read_stream
                    频繁调用 emit_update 时，task 可能堆积，导致 terminal_output 事件
                    延迟到 tool_output 之后才进入 event_queue，前端无法实时看到终端输出。
                    改用 emit_sync 后，同步 listener（如 server.py 的 on_event）被立即
                    调用，事件被立即放入 event_queue，确保前端实时收到 terminal_output。

        SSE 层监听 TOOL_UPDATED 事件后，将 update 数据作为 SSE 消息发给前端。

        Args:
            tool_name: 触发 update 的工具名（用于事件溯源）
            tool_call_id: 触发 update 的工具调用 ID（用于前端关联工具卡片）

        Returns:
            emit_update 回调函数
        """
        def emit_update(update: Any) -> None:
            try:
                # 构造 TOOL_UPDATED 事件 — 对标 Cline tool-updated
                # tool_call_id 和 tool_name 用于前端关联工具卡片
                # metadata 存放完整 update 数据
                event = AgentEvent(
                    type=TOOL_UPDATED,
                    snapshot=self.snapshot(),
                    iteration=self._state.iteration,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    metadata=update if isinstance(update, dict) else {"value": update},
                )
                # Phase 35.1: 改用 emit_sync 同步发射，确保事件立即进入 event_queue
                # 原实现用 asyncio.create_task(self._emit(event)) fire-and-forget，
                # 会导致 terminal_output 事件延迟，前端无法实时看到终端输出
                self._emitter.emit_sync(event)
            except Exception:
                # update 转发失败不影响工具主流程
                pass
        return emit_update

    def _throw_if_aborted(self) -> None:
        """检查中止标志 — 对标 Cline throwIfAborted()"""
        if self._aborted:
            raise RuntimeError(self._abort_reason or "aborted")

    def _check_signal_aborted(self) -> None:
        """检查 abort_signal — P1-9 新增，对标 Cline throwIfAborted 使用 AbortController.signal

        与 _throw_if_aborted 互补：
            - _throw_if_aborted 检查 self._aborted 布尔，抛出 RuntimeError（向后兼容）
            - _check_signal_aborted 检查 AbortController.signal，抛出 AbortedError

        在主循环关键位置（LLM 请求前/工具执行前/消息追加前/事件发射前）调用，
        让 AbortedError 与 ControlledStopError 区分，便于上层精确处理中止场景。
        """
        if self._abort_controller is not None and self._abort_controller.is_set():
            raise AbortedError(self._abort_reason or "aborted")

    def _normalize_input(
        self,
        input: str | AgentMessage | list[AgentMessage],
    ) -> list[AgentMessage]:
        """规范化输入为消息列表"""
        if isinstance(input, str):
            return [create_message(MessageRole.USER, [TextPart(text=input)])]
        if isinstance(input, AgentMessage):
            return [input]
        return list(input)

    def _finish_run(
        self,
        status: str,
        assistant_message: AgentMessage | None = None,
        output_text: str | None = None,
    ) -> AgentRunResult:
        """完成运行 — 对标 Cline finishRun() L1562-1580"""
        self._state.status = status
        if output_text is None and assistant_message is not None:
            output_text = text_from_message(assistant_message)
        return AgentRunResult(
            agent_id=self._state.agent_id,
            agent_role=self._state.agent_role,
            run_id=self._state.run_id or uuid.uuid4().hex[:12],
            status=status,
            iterations=self._state.iteration,
            output_text=output_text,
            messages=list(self._state.messages),
            usage=clone_usage(self._state.usage),
        )

    # Stage 10.3 (B9): completion reminder 预注入辅助方法
    # 对标 Cline callBeforeRunHooks 中的 reminder 注入逻辑

    def _capture_unexpected_reasoning_tokens(
        self,
        text_buffer: str,
        finish_reason: str | None,
    ) -> tuple[list[ReasoningPart], str]:
        """检测 finish 后的意外 reasoning tokens — Stage 10.2 (C19) 新增

        对标 Cline agent-runtime.ts captureUnexpectedReasoningTokens。
        部分 LLM Provider（如 DeepSeek R1、Claude 3.7 Sonnet）在
        finish_reason="tool_calls" 时仍可能输出 reasoning content（思考链），
        但流式响应中未明确以 reasoning-delta 事件标识，而是混入 text-delta。

        检测策略（保守，避免误判）:
            1. <think>...</think> 标签: 正则提取，识别为 reasoning
            2. 启发式思考碎片: finish_reason="tool_calls" 时，内容以
               "让我"/"我需要"/"首先"/"Let me"/"I need to" 开头且长度 > 50
            3. 不识别则原样返回 text（保守策略）

        Args:
            text_buffer: 累积的 text 内容
            finish_reason: finish 事件的原因

        Returns:
            (reasoning_parts, remaining_text)
            - reasoning_parts: 识别为 reasoning 的部分
            - remaining_text: 剩余的真实 text（未识别为 reasoning 的部分）
        """
        import re

        if not text_buffer:
            return [], ""

        reasoning_parts: list[ReasoningPart] = []
        remaining_text = text_buffer

        # 1. 检测 <think>...</think> 标签
        think_pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
        think_matches = think_pattern.findall(text_buffer)
        if think_matches:
            for match in think_matches:
                reasoning_parts.append(ReasoningPart(text=match.strip()))
            # 移除 <think>...</think> 标签后的剩余文本
            remaining_text = think_pattern.sub("", text_buffer).strip()
            return reasoning_parts, remaining_text

        # 2. 启发式思考碎片检测（仅 finish_reason="tool_calls" 时）
        # 量化场景下，LLM 在调用工具前的思考过程可能被误认为 text
        if finish_reason == AgentModelFinishReason.TOOL_CALLS.value:
            thinking_prefixes = (
                "让我", "我需要", "首先", "让我想想", "我考虑",
                "Let me", "I need to", "First,", "Let's",
            )
            stripped = text_buffer.strip()
            if (
                len(stripped) > 50
                and any(stripped.startswith(p) for p in thinking_prefixes)
            ):
                # 整体识别为 reasoning
                reasoning_parts.append(ReasoningPart(text=text_buffer))
                return reasoning_parts, ""

        # 3. 不识别，原样返回
        return [], text_buffer

    def _find_completing_tool_name(self) -> str | None:
        """查找 completing tool 名称 — Stage 10.3 (B9) 新增

        从 self._tools 中查找 lifecycle.completes_run=True 的工具，
        多个时取第一个（与 Cline 行为一致）。

        Returns:
            工具名或 None（无 completing tool 时）
        """
        for name, tool in self._tools.items():
            lifecycle = getattr(tool, "lifecycle", None)
            if lifecycle is not None and getattr(lifecycle, "completes_run", False):
                return name
        return None

    def _find_completing_tool_names(self) -> list[str]:
        """查找所有 completing tool 名称 — P1-18 新增

        对标 Cline agent-runtime.ts getRequiredCompletionToolNames() L557-565。
        收集 self._tools 中所有 lifecycle.completes_run=True 的工具名并排序，
        用于在 completion reminder 中列出所有可用的完成工具。

        与 _find_completing_tool_name()（单数，取第一个）的区别：
            - 单数版本仅返回第一个，用于向后兼容
            - 复数版本返回全部，对标 Cline 行为，让 LLM 知道所有可选的完成工具

        Returns:
            排序后的工具名列表（无 completing tool 时为空列表）
        """
        names = [
            name
            for name, tool in self._tools.items()
            if getattr(getattr(tool, "lifecycle", None), "completes_run", False)
        ]
        return sorted(names)

    async def _inject_completion_reminder(self, completing_tool: str | list[str]) -> None:
        """在循环开始前注入 completion reminder — Stage 10.3 (B9) 新增

        对标 Cline callBeforeRunHooks 中预注入 reminder 的逻辑。
        reminder 作为 system message 注入（不污染 user/assistant 历史），
        提示 LLM "本任务必须以 completing_tool 结束"。

        P1-18 增强: 对标 Cline getCompletionToolReminderMessage() L567-575，
        支持传入多个 completing tool 名称，在 reminder 中列出所有可选的完成工具，
        让 LLM 知道可以调用其中任意一个来结束任务。

        现有"第一轮失败后 reminder"逻辑保留作为兜底，预注入是优化。

        Args:
            completing_tool: completing tool 名称（字符串）或名称列表。
                             传列表时在 reminder 中列出所有工具名（对标 Cline 行为）。
        """
        # P1-18: 统一转换为列表处理，对标 Cline terminalToolNames.join(", ")
        if isinstance(completing_tool, str):
            tool_names = [completing_tool]
        else:
            tool_names = list(completing_tool)

        if not tool_names:
            return

        # P1-18: 对标 Cline "call one of these terminal completion tools: X, Y, Z"
        if len(tool_names) == 1:
            reminder_text = (
                f"[System Reminder] 本任务必须以 `{tool_names[0]}` 工具结束。"
                f"请在完成所有准备工作后调用该工具提交结果。"
            )
        else:
            tools_str = ", ".join(f"`{name}`" for name in tool_names)
            reminder_text = (
                f"[System Reminder] 本任务必须以以下完成工具之一结束: {tools_str}。"
                f"请在完成所有准备工作后调用其中一个工具提交结果。"
            )
        # 用 USER 角色注入（与现有 _build_completion_reminder 一致），
        # 文本前缀 [System Reminder] 标识其为系统提示，不污染 assistant 历史
        reminder_msg = create_text_message(MessageRole.USER, reminder_text)
        self._state.messages.append(reminder_msg)
        await self._emit(make_message_added(self.snapshot(), reminder_msg))
        self._logger.info(
            "Stage 10.3: 已预注入 completion reminder (completing_tools=%s)",
            tool_names,
        )

    def _build_completion_reminder(self, policy: CompletionPolicy) -> str:
        """构造完成工具提醒消息 — 对标 Cline completionPolicy.completionGuard

        当 require_completion_tool=True 且 LLM 未调用完成工具时，
        将返回的文本作为用户消息追加到历史，提示 agent 继续调用完成工具。
        """
        if policy.completion_guard is not None:
            guard_text = policy.completion_guard()
            if guard_text:
                return guard_text
        return (
            "你必须调用完成工具（如 attempt_completion 或 submit_and_exit）"
            "来结束本次任务。请直接调用相应工具，不要只返回文本。"
        )

    def _find_last_assistant_message(self) -> AgentMessage | None:
        """找到最后一条 assistant 消息"""
        for msg in reversed(self._state.messages):
            if msg.role == MessageRole.ASSISTANT:
                return msg
        return None

    def _extract_invalid_tool_calls(
        self,
        message: AgentMessage,
    ) -> list[_InvalidToolCall]:
        """从 assistant 消息 metadata 中提取无效工具调用记录"""
        raw = message.metadata.get("invalid_tool_calls", [])
        if not isinstance(raw, list):
            return []
        result: list[_InvalidToolCall] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            result.append(_InvalidToolCall(
                tool_call_id=str(item.get("tool_call_id", "")),
                reason=str(item.get("reason", "invalid_arguments")),
                tool_name=item.get("tool_name"),
                input=item.get("input") if isinstance(item.get("input"), dict) else {},
            ))
        return result

    def _build_invalid_tool_result_message(
        self,
        invalid: _InvalidToolCall,
    ) -> AgentMessage:
        """为无效工具调用构造错误结果消息，让 LLM 在下一轮看到自己调用错了"""
        reason_text = {
            "missing_name": "工具调用缺少工具名，请使用正确的工具名称。",
            "missing_arguments": "工具调用缺少必要参数，请检查参数是否完整。",
            "invalid_arguments": "工具调用参数无法解析为合法 JSON，请检查参数格式。",
        }.get(invalid.reason, f"工具调用无效: {invalid.reason}")

        detail = ""
        raw_input = invalid.input.get("raw_input_text")
        parse_error = invalid.input.get("parse_error")
        if raw_input:
            detail += f" 原始输入: {raw_input}"
        if parse_error:
            detail += f" 解析错误: {parse_error}"

        output = f"{reason_text}{detail}".strip()
        return create_message(MessageRole.TOOL, [
            ToolResultPart(
                tool_call_id=invalid.tool_call_id,
                tool_name=invalid.tool_name or "",
                output=output,
                is_error=True,
            )
        ])

    def _parse_tool_input(self, assembly: _PendingToolAssembly) -> _ParsedToolInput:
        """解析工具输入 — 对标 Cline parseToolInput()

        优先使用已解析的 input_value，否则尝试解析 input_text JSON。
        返回解析结果及可能的解析错误信息，用于生成 invalid_tool_calls。
        """
        if assembly.input_value is not None:
            value_json = ""
            try:
                value_json = json.dumps(assembly.input_value, ensure_ascii=False)
            except (TypeError, ValueError):
                pass
            return _ParsedToolInput(
                input=assembly.input_value,
                invalid_input=self._build_invalid_tool_input(value_json),
            )

        if not assembly.input_text or not assembly.input_text.strip():
            return _ParsedToolInput(
                input={},
                invalid_input={},
            )

        parsed = self._parse_tool_arguments(assembly.input_text)
        if parsed["ok"]:
            return _ParsedToolInput(
                input=parsed["value"],
                invalid_input=self._build_invalid_tool_input(assembly.input_text),
            )

        parse_error = (
            f"Tool call {assembly.tool_name or assembly.tool_call_id} emitted "
            f"invalid JSON arguments: {parsed['error']}"
        )
        return _ParsedToolInput(
            input={},
            invalid_input=self._build_invalid_tool_input(
                assembly.input_text, parsed["error"]
            ),
            parse_error=parse_error,
            reason="invalid_arguments",
        )

    def _parse_tool_arguments(
        self,
        value: str,
    ) -> dict[str, Any]:
        """解析工具参数字符串 — 对标 Cline parseToolArguments()

        Returns:
            {"ok": True, "value": <解析后的值>} 或
            {"ok": False, "error": <错误信息>}
        """
        trimmed = value.strip()
        if not trimmed:
            return {"ok": False, "error": "Tool call arguments were empty."}

        try:
            return {"ok": True, "value": json.loads(trimmed)}
        except (json.JSONDecodeError, TypeError):
            pass

        if not (trimmed.startswith("{") or trimmed.startswith("[")):
            return {
                "ok": False,
                "error": "Tool call arguments must be encoded as a JSON object or array.",
            }

        return {
            "ok": False,
            "error": (
                "Tool call arguments could not be parsed as JSON. "
                "Ensure the outer tool payload is valid JSON and escape "
                "embedded quotes/newlines inside string fields."
            ),
        }

    def _build_invalid_tool_input(
        self,
        value: str,
        parse_error: str | None = None,
    ) -> dict[str, Any]:
        """构造无效工具调用的 input 记录 — 对标 Cline buildInvalidToolInput()"""
        trimmed = value.strip()
        if not trimmed:
            return {}
        if parse_error:
            return {"raw_input_text": value, "parse_error": parse_error}
        return {"raw_input_text": value}

    def _normalize_input_for_schema(
        self,
        input_value: Any,
        schema: dict[str, Any],
    ) -> Any:
        """按 Schema 规范化输入 — 对标 Cline normalizeJsonLikeStringsForSchema

        当 LLM 把 object/array 参数写成 JSON 字符串时，根据 schema 期望的类型
        尝试解析为真正的 object/array，并递归处理嵌套结构。
        """
        value = self._parse_json_string_for_schema(input_value, schema)

        if isinstance(value, list):
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                changed = False
                normalized: list[Any] = []
                for item in value:
                    next_item = self._normalize_input_for_schema(item, items_schema)
                    changed |= next_item is not item
                    normalized.append(next_item)
                return normalized if changed else value
            return value

        if isinstance(value, dict):
            properties = schema.get("properties")
            if isinstance(properties, dict):
                changed = False
                normalized: dict[str, Any] = dict(value)
                for key, prop_schema in properties.items():
                    if key not in value or not isinstance(prop_schema, dict):
                        continue
                    next_value = self._normalize_input_for_schema(
                        value[key], prop_schema
                    )
                    if next_value is not value[key]:
                        normalized[key] = next_value
                        changed = True
                return normalized if changed else value
            return value

        return value

    def _parse_json_string_for_schema(
        self,
        value: Any,
        schema: dict[str, Any],
    ) -> Any:
        """如果 schema 期望 object/array 且输入是字符串，尝试解析 JSON"""
        if not isinstance(value, str):
            return value

        trimmed = value.strip()
        expects_array = self._schema_accepts_kind(schema, "array")
        expects_object = self._schema_accepts_kind(schema, "object")
        if (
            (not expects_array or not trimmed.startswith("["))
            and (not expects_object or not trimmed.startswith("{"))
        ):
            return value

        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, list):
                return parsed if expects_array else value
            if isinstance(parsed, dict):
                return parsed if expects_object else value
            return value
        except (json.JSONDecodeError, TypeError):
            return value

    def _schema_accepts_kind(
        self,
        schema: dict[str, Any],
        kind: str,
    ) -> bool:
        """检查 schema 是否接受指定类型（object/array）"""
        type_field = schema.get("type")
        types: list[str] = []
        if isinstance(type_field, str):
            types = [type_field]
        elif isinstance(type_field, list):
            types = [t for t in type_field if isinstance(t, str)]

        if kind in types:
            return True

        for key in ("anyOf", "oneOf", "allOf"):
            branches = schema.get(key)
            if isinstance(branches, list):
                for branch in branches:
                    if isinstance(branch, dict) and self._schema_accepts_kind(branch, kind):
                        return True
        return False

    def _serialize_tool_output(self, output: Any, tool_name: str) -> str:
        """序列化工具输出为字符串

        LLM 需要文本格式的工具结果。
        对长输出进行截断，防止撑爆上下文。
        """
        if output is None:
            return ""
        if isinstance(output, str):
            text = output
        elif isinstance(output, dict):
            # 如果 dict 里有 error 字段，直接返回 error 消息
            if "error" in output and len(output) == 1:
                return str(output["error"])
            try:
                text = json.dumps(output, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                text = str(output)
        else:
            text = str(output)

        # 截断过长输出
        max_chars = self.config.max_tool_result_chars
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[输出已截断，原始长度 {len(text)} 字符]"
        return text

    def _compute_usage_delta(
        self,
        before: AgentUsage,
        after: AgentUsage,
    ) -> dict[str, Any] | None:
        """计算用量增量 — 对标 Cline usageDelta()

        与 Cline 一致:
        1. 所有字段取 max(0, delta)，避免 provider 上报异常导致负值
        2. 只有存在非零字段时才返回 metrics
        3. reasoning_token_count / total_cost 为零时不展开，减少无意义字段
        """
        input_tokens = max(0, after.input_tokens - before.input_tokens)
        output_tokens = max(0, after.output_tokens - before.output_tokens)
        cache_read_tokens = max(0, after.cache_read_tokens - before.cache_read_tokens)
        cache_write_tokens = max(0, after.cache_write_tokens - before.cache_write_tokens)
        reasoning_token_count = max(0, after.reasoning_token_count - before.reasoning_token_count)
        total_cost = max(0.0, after.total_cost - before.total_cost)

        if (
            input_tokens == 0
            and output_tokens == 0
            and cache_read_tokens == 0
            and cache_write_tokens == 0
            and reasoning_token_count == 0
            and total_cost == 0
        ):
            return None

        delta: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
        }
        if reasoning_token_count > 0:
            delta["reasoning_token_count"] = reasoning_token_count
        if total_cost > 0:
            delta["total_cost"] = total_cost
        return delta

    async def _call_hook(self, hook: Callable, ctx: Any) -> Any:
        """调用钩子函数（自动处理同步/异步）"""
        result = hook(ctx)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    # ========================================================================
    # Phase 23: 用户输入预处理 / 格式化钩子调用
    # ========================================================================

    async def _call_prepare_turn_input_hooks(self, user_input: str) -> str:
        """调用 prepare_turn_input 钩子 — Phase 23 新增

        对标 Cline prepareTurnInput，在用户输入进入主循环前修改文本。
        多个钩子按顺序执行，前一个的输出作为后一个的输入。

        Args:
            user_input: 原始用户输入文本

        Returns:
            处理后的用户输入文本（无钩子时返回原文本）

        Raises:
            RuntimeError: 钩子返回 stop=True 时中止运行
        """
        if not self._hooks.prepare_turn_input:
            return user_input

        current_input = user_input
        for hook in self._hooks.prepare_turn_input:
            ctx = PrepareTurnInputContext(
                snapshot=self.snapshot(),
                user_input=current_input,
            )
            result = await self._call_hook(hook, ctx)
            if result is None:
                continue
            if result.modified_input is not None:
                current_input = result.modified_input
            if result.stop:
                raise RuntimeError(result.reason or "stopped by prepare_turn_input hook")

        return current_input

    async def _call_format_user_input_block_hooks(
        self,
        messages: list[AgentMessage],
    ) -> list[AgentMessage]:
        """调用 format_user_input_block 钩子 — Phase 23 新增

        对标 Cline formatUserInputBlock，在用户消息添加到历史前注入元数据。
        仅处理 USER 角色且含 TextPart 的消息，其他消息原样返回。

        Stage 36.2 (M2) 增强: 无钩子时执行默认 <user_input> 包装
        对标 Cline sdk/packages/shared/src/prompt/format.ts L5-10 formatUserInputBlock:
            return `<user_input mode="${mode}">${input}</user_input>`
        runtime 层保证用户输入被 <user_input mode="..."> 包裹，即使非 server.py 入口
        调用 runtime.run() 也能正确包装。若文本已以 <user_input 开头（如 server.py
        已包装），跳过避免双重包装。

        Args:
            messages: 已规范化的输入消息列表

        Returns:
            处理后的消息列表（可能含修改后的文本）
        """
        if not self._hooks.format_user_input_block:
            # Stage 36.2 (M2): 无钩子时执行默认 <user_input> 包装
            return self._apply_default_user_input_wrap(messages)

        result_messages: list[AgentMessage] = []
        for msg in messages:
            if msg.role != MessageRole.USER:
                result_messages.append(msg)
                continue

            # 提取用户输入文本
            user_text = ""
            new_parts: list[Any] = []
            for part in msg.content:
                if isinstance(part, TextPart):
                    user_text += part.text
                else:
                    new_parts.append(part)

            # 调用钩子链
            current_block = user_text
            for hook in self._hooks.format_user_input_block:
                ctx = FormatUserInputBlockContext(
                    snapshot=self.snapshot(),
                    user_input=user_text,
                    formatted_block=current_block,
                )
                hook_result = await self._call_hook(hook, ctx)
                if hook_result is None:
                    continue
                if hook_result.modified_block is not None:
                    current_block = hook_result.modified_block

            # 重建消息（保留非文本 parts，替换文本部分）
            new_parts.insert(0, TextPart(text=current_block))
            from agent.types import AgentMessage as _AM
            new_msg = _AM(
                id=msg.id,
                role=msg.role,
                content=new_parts,
                created_at=msg.created_at,
                metadata=msg.metadata,
            )
            result_messages.append(new_msg)

        return result_messages

    def _apply_default_user_input_wrap(
        self,
        messages: list[AgentMessage],
    ) -> list[AgentMessage]:
        """默认 <user_input> 包装 — Stage 36.2 (M2) 新增

        对标 Cline formatUserInputBlock (format.ts L5-10):
            return `<user_input mode="${mode}">${input}</user_input>`

        当无 format_user_input_block 钩子时，runtime 层默认包装用户输入。
        若文本已以 <user_input 开头（如 server.py 已包装），跳过避免双重包装。

        语义对齐 Cline:
            - Cline 的 formatUserInputBlock 在 runtime 层的 prepareTurnInput 调用
            - Charles 的 server.py 在调用 runtime 前手动包装（兼容层）
            - runtime 默认包装会检测已包装而跳过，避免双重包装
            - 非 server.py 入口直接调用 runtime.run() 时，由 runtime 保证包装

        Args:
            messages: 已规范化的输入消息列表

        Returns:
            包装后的消息列表
        """
        mode = self._get_current_mode_for_wrap()
        result_messages: list[AgentMessage] = []
        for msg in messages:
            if msg.role != MessageRole.USER:
                result_messages.append(msg)
                continue

            # 提取文本部分
            user_text = ""
            new_parts: list[Any] = []
            for part in msg.content:
                if isinstance(part, TextPart):
                    user_text += part.text
                else:
                    new_parts.append(part)

            # 检测是否已被 <user_input> 包装
            # server.py 入口已包装的消息跳过，避免双重包装
            if user_text.lstrip().startswith("<user_input"):
                new_parts.insert(0, TextPart(text=user_text))
            else:
                # 未包装，执行默认包装（与 server.py 格式一致，含 \n）
                wrapped = f'<user_input mode="{mode}">\n{user_text}\n</user_input>'
                new_parts.insert(0, TextPart(text=wrapped))

            from agent.types import AgentMessage as _AM
            new_msg = _AM(
                id=msg.id,
                role=msg.role,
                content=new_parts,
                created_at=msg.created_at,
                metadata=msg.metadata,
            )
            result_messages.append(new_msg)

        return result_messages

    def _get_current_mode_for_wrap(self) -> str:
        """获取当前 mode 用于 <user_input> 包装 — Stage 36.2 (M2) 新增

        从 agent.state.get_mode(session_id) 获取当前模式。
        无 session_id 或查询失败时返回 "act"（对标 Cline formatUserInputBlock 默认值）。

        Returns:
            当前模式字符串（act / plan）
        """
        if not self.config.session_id:
            return "act"
        try:
            from agent.state import get_mode
            return get_mode(self.config.session_id)
        except Exception:
            return "act"
