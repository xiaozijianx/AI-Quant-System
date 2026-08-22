# -*- coding: utf-8 -*-
"""SSE 服务端 — 对标 Cline server

提供 /api/chat/stream SSE 端点，基于 AgentRuntime 实现。
保持与现有前端完全兼容的 SSE 事件格式。

SSE 事件格式:
    data: {"type": "phase", "phase": "thinking"}           -- 思考阶段（保留，供旧逻辑参考）
    data: {"type": "reasoning", "text": "..."}             -- LLM 思考过程增量（reasoning-delta）
    data: {"type": "token", "text": "..."}                  -- LLM 正文输出增量（text-delta）
    data: {"type": "tool_call", "name": "...", "args": "...", "idx": 1}  -- 工具调用
    data: {"type": "tool_output", "output": "...", "error": false, "idx": 1}  -- 工具结果
    data: {"type": "phase", "phase": "answering"}           -- 回答阶段
    data: {"type": "done"}                                   -- 结束
    data: {"type": "error", "text": "..."}                  -- 错误

AgentRuntime 事件 → SSE 映射:
    run-started              → phase: thinking
    assistant-text-delta     → token (即时发送，无缓冲)
    assistant-reasoning-delta → reasoning (即时发送，无缓冲)
    tool-started             → tool_call
    tool-finished            → tool_output
    run-finished             → phase: answering + done
    run-failed               → error + done

对标 Cline:
    - sdk/packages/core/src/extensions/tools/executors/web-search.ts
    - SSE 事件流设计
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agent.context import CompactionStateManager, ContextCompactor, SystemPromptBuilder
from agent.events import (
    AgentEvent,
    ASSISTANT_MESSAGE,
    ASSISTANT_REASONING_DELTA,
    ASSISTANT_TEXT_DELTA,
    MESSAGE_ADDED,
    RUN_FAILED,
    RUN_FINISHED,
    RUN_STARTED,
    STATUS_NOTICE,
    TOOL_EXECUTION_FINISHED,
    TOOL_EXECUTION_STARTED,
    TOOL_UPDATED,
    TURN_FINISHED,
    TURN_STARTED,
    USAGE_UPDATED,
    EventEmitter,
)
from agent.approval_policy import AutoApprovalPolicy
from agent.hooks import AgentHooks
from agent.providers.qwen import QwenModel
from agent.providers.errors import ProviderError
from agent.runtime import AgentRuntime
from agent.session import SessionManager
from agent.skills import SkillRegistry, SkillsTool
from agent.tools import create_default_tools
from agent.types import (
    AgentMessage,
    AgentRuntimeConfig,
    MessageRole,
    create_text_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ============================================================================
# 全局单例
# ============================================================================

_session_manager = SessionManager()
_skill_registry: SkillRegistry | None = None
# Phase 13: 移除全局 _compactor，改为在 _create_runtime 中按需创建
# （因为 ContextCompactor 需要 model 实例，而 model 在 _create_runtime 中创建）
# 活跃的 AgentRuntime 实例（用于 abort）: session_id → AgentRuntime
_active_runtimes: dict[str, AgentRuntime] = {}

# 会话级事件广播器: session_id → SessionRouter
# 解耦 SSE 连接与 run 生命周期: 一个会话同时只有一个 run 在运行,
# 事件广播给订阅该会话的所有 SSE 连接（多标签页 / 刷新接管共享同一信息流）
_session_router: dict[str, "SessionRouter"] = {}

# event_log 条数上限（防御性: 防止超长 run 导致内存无限增长）。
# 正常研报/分析任务事件量约几千条，远低于此上限，不会触发截断；
# 触发时丢弃最早的事件（早期 thinking/tool 历史），保证界面核心内容可重建。
_EVENT_LOG_MAX = 50000


class SessionRouter:
    """会话级事件广播器

    - subscribers: conn_id -> asyncio.Queue（每个 SSE 连接一个订阅队列）
    - event_log: 当前 run 已产生的全部 SSE 事件，供新订阅者（刷新/新标签页）重放
    - run_task: 会话 turn 循环任务（drain queue + 首次 run + auto-continue + 末尾 drain）

    broadcast(None) 表示 run 结束哨兵：所有订阅者收到后结束各自连接，
    但 run 本身不因订阅者断开而取消（断开只移除订阅者）。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.subscribers: dict[str, asyncio.Queue] = {}
        self.event_log: list[str] = []
        self.run_task: asyncio.Task | None = None

    def broadcast(self, payload: str | None) -> None:
        """广播事件给所有订阅者；payload=None 表示 run 结束哨兵（不入 event_log）"""
        for q in list(self.subscribers.values()):
            try:
                q.put_nowait(payload)
            except Exception:
                pass
        if payload is not None:
            self.event_log.append(payload)
            # 防御性限长: 超限时丢弃最早的事件，避免超长 run 内存无限增长
            if len(self.event_log) > _EVENT_LOG_MAX:
                del self.event_log[: len(self.event_log) - _EVENT_LOG_MAX]

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        """注册订阅者，返回 (conn_id, queue)。

        注意: 订阅后必须立即（同一同步段内）重放 event_log,
        否则新订阅者会漏掉已产生的事件。
        """
        import uuid
        conn_id = uuid.uuid4().hex
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers[conn_id] = q
        return conn_id, q

    def unsubscribe(self, conn_id: str) -> None:
        """移除订阅者（连接断开时调用），不影响 run 运行"""
        self.subscribers.pop(conn_id, None)

    def is_active(self) -> bool:
        """当前会话是否有正在运行的 turn 循环"""
        return self.run_task is not None and not self.run_task.done()

# Phase 30.1: turn queue controller — 用户输入排队
# 延迟初始化（首次调用 _get_turn_queue_controller 时创建）
_turn_queue_controller: Any = None


def _get_turn_queue_controller() -> Any:
    """获取或初始化 turn queue controller — Phase 30.1 新增

    controller 需要三个依赖：
        - session_status_query: 查询会话状态 (is_aborting, is_draining, can_start_run)
        - send_callback: 触发 agent 运行（drain 时调用）
        - emit_callback: 发射 SSE 事件（pending_prompts_updated）

    send_callback 在 drain 时被调用，但当前架构下 _schedule_drain 在 run 运行中
    本就因 can_start_run=False 跳过，run 结束后由 _sse_generator 末尾的循环消费段
    直接启动新 run（对标 Cline drain() L295-335）。因此 send_callback 实现为"空操作"，
    真正的消费由 _sse_generator 内部闭环完成，事件通过原 SSE 连接推送。
    """
    global _turn_queue_controller
    if _turn_queue_controller is not None:
        return _turn_queue_controller

    from agent.turn_queue import init_controller

    def session_status_query(session_id: str) -> tuple[bool, bool, bool]:
        """查询会话状态: (is_aborting, is_draining, can_start_run)"""
        runtime = _active_runtimes.get(session_id)
        if runtime is None:
            # 无活跃 runtime，可以启动新 run
            return (False, False, True)
        snapshot = runtime.snapshot()
        is_aborting = snapshot.status == "aborted"
        is_running = snapshot.status == "running"
        # running 时不能启动新 run（需走 enqueue 路径）
        return (is_aborting, False, not is_running)

    async def send_callback(
        session_id: str,
        prompt: str,
        mode: str | None,
        user_images: list[str],
        user_files: list[str],
    ) -> None:
        """drain 触发新 run — P1-17 修改：drain 检查移到 send_callback 开始处

        对标 Cline drain() L294-334：drain 在 send_callback 启动时检查 turn queue，
        若有待处理消息则立即处理，而非等待当前 turn 结束。

        P1-17 修改前：send_callback 为空操作，drain 检查仅在 _sse_generator 末尾循环。
        P1-17 修改后：send_callback 开始时检查 turn queue 状态，记录待处理消息数。
        实际 SSE 事件消费仍由 _sse_generator 处理（因为 send_callback 无法 yield SSE 事件），
        但 _sse_generator 末尾循环和首部 drain 检查共同确保 turn queue 及时消费：
            1. 首部 drain（send_callback 开始处）：消费上一轮遗留的 queue 消息
            2. 末尾循环：消费当前 run 期间新增的 queue 消息
        """
        # P1-17: 在 send_callback 开始处检查 turn queue 是否有待处理消息
        # 对标 Cline drain() L300 `if (!session.agent.canStartRun()) return;` 之前的检查
        try:
            controller = _get_turn_queue_controller()
            q_state = controller._states.get(session_id)
            pending_count = len(q_state.pending_prompts) if q_state else 0
        except Exception:
            pending_count = 0

        logger.info(
            "turn_queue: drain session=%s prompt=%d字符 pending=%d（send_callback 开始处检查）",
            session_id, len(prompt), pending_count,
        )
        # 不抛异常，让 controller 认为发送成功，继续 drain 下一条
        # 真正的 run 由 _sse_generator 首部/末尾循环启动

    def emit_callback(event: dict) -> None:
        """发射 turn_queue 事件 — 当前为空操作

        SSE 事件由 _sse_generator 内部直接 yield，不通过此回调。
        controller 调用 emit_callback 时仅记录日志，便于调试。
        """
        logger.debug("turn_queue event: %s", event.get("type"))

    _turn_queue_controller = init_controller(
        session_status_query=session_status_query,
        send_callback=send_callback,
        emit_callback=emit_callback,
    )
    return _turn_queue_controller

# Phase 18: 启动时从磁盘加载所有持久化的会话和会话状态
# 确保服务重启后会话历史和 todos/mode 状态可恢复
try:
    restored_sessions = _session_manager.load_all()
    if restored_sessions > 0:
        logger.info(f"Phase 18: 已恢复 {restored_sessions} 个持久化会话")
except Exception as e:
    logger.warning(f"Phase 18: 加载持久化会话失败: {e}", exc_info=True)

try:
    from agent.state import load_all_states
    restored_states = load_all_states()
    if restored_states > 0:
        logger.info(f"Phase 18: 已恢复 {restored_states} 个持久化会话状态")
except Exception as e:
    logger.warning(f"Phase 18: 加载持久化会话状态失败: {e}", exc_info=True)


def _get_skill_registry() -> SkillRegistry:
    """获取全局技能注册表（延迟初始化）

    Phase 31.3: 支持通过环境变量 AGENT_ALLOWED_SKILLS 配置白名单 — 对标 Cline
    allowedSkillNames。多个技能名用逗号分隔，如 "write-report,read-pdf"。
    默认 None（全部允许）。
    """
    global _skill_registry
    if _skill_registry is None:
        # 从 agent_config/skills 目录加载（Cline 风格配置）
        project_root = Path(__file__).resolve().parent.parent
        skills_path = project_root / "agent_config" / "skills"
        # Phase 31.3: 从环境变量读取白名单
        allowed_str = os.environ.get("AGENT_ALLOWED_SKILLS", "").strip()
        allowed_skill_names: list[str] | None = None
        if allowed_str:
            allowed_skill_names = [
                n.strip() for n in allowed_str.split(",") if n.strip()
            ]
        _skill_registry = SkillRegistry(
            skills_dir=skills_path,
            allowed_skill_names=allowed_skill_names,
        )
        _skill_registry.discover()
        logger.info(
            f"技能注册表已加载: {[s.name for s in _skill_registry.list_skills()]}"
            f"{f' (白名单: {allowed_skill_names})' if allowed_skill_names else ''}"
        )
    return _skill_registry


def _get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).resolve().parent.parent


# ============================================================================
# SSE 辅助函数
# ============================================================================

# SSE 响应通用头 — 禁止代理缓冲，保持流式实时推送
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sanitize(obj: Any) -> Any:
    """递归替换 NaN/Inf 为 null — 项目约束：SSE 消息必须序列化 NaN/Inf 为 null"""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _sse_event(event_type: str, data: dict | None = None) -> str:
    """构建一条 SSE 事件 — 与 routes/chat.py 格式一致

    ts 字段: 事件产生的墙钟时间戳（毫秒），供前端性能日志计算
    "事件产生 → 前端接收"的端到端延迟，定位事件是否在传输/订阅队列中积压。
    前端 _handleSSEEvent 忽略未知字段，不影响渲染逻辑。
    """
    payload = _sanitize({"type": event_type, **(data or {})})
    payload["ts"] = int(time.time() * 1000)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _format_tool_args(args: Any) -> str:
    """格式化工具参数"""
    try:
        if isinstance(args, dict):
            return json.dumps(args, ensure_ascii=False, indent=2)
        return str(args)
    except Exception:
        return str(args)


def _format_tool_output(output: Any, max_chars: int = 2000) -> str:
    """格式化工具输出"""
    try:
        if isinstance(output, dict):
            text = json.dumps(output, ensure_ascii=False)
        elif isinstance(output, str):
            text = output
        else:
            text = str(output)
    except Exception:
        text = str(output)

    if len(text) > max_chars:
        text = text[:max_chars] + "...(截断)"
    return text


# ============================================================================
# AgentRuntime 工厂
# ============================================================================


def _create_model(provider_alias: str | None = None) -> QwenModel | Any:
    """创建模型实例 — 支持从环境变量或 providers.yaml 配置创建

    Phase 32.2: 改用 provider 工厂，支持 OpenAI / DeepSeek / Moonshot / Zhipu 等
    兼容 OpenAI 协议的 provider。Qwen 走专用适配器保持向后兼容。

    Args:
        provider_alias: 前端选择的 Provider 配置别名。为空时回退到环境变量默认配置。

    环境变量:
        AGENT_PROVIDER_ID: provider 标识，默认 "qwen"
        AGENT_MODEL_NAME: 模型名称，默认使用 provider 的默认模型
        AGENT_MODEL_API_KEY: API Key，默认回退到 provider 对应的环境变量
        AGENT_MODEL_BASE_URL: API Base URL
        AGENT_MODEL_MAX_TOKENS: 最大输出 token 数，默认 8192
        AGENT_MODEL_TEMPERATURE: 采样温度，默认 0.1

    Returns:
        实现 AgentModel 协议的实例（QwenModel 或 OpenAIModel）
    """
    if provider_alias:
        from agent.provider_settings import get_provider_settings_store
        from agent.providers.factory import create_model_from_config

        store = get_provider_settings_store()
        cfg = store.get_provider(provider_alias)
        if cfg is None:
            raise RuntimeError(f"Provider 配置 {provider_alias} 不存在")
        provider_id = cfg.provider_id
        try:
            model = create_model_from_config(cfg)
        except (ValueError, ProviderError) as e:
            raise RuntimeError(f"创建模型失败（alias={provider_alias}, provider={provider_id}）: {e}") from e
    else:
        from agent.providers.factory import create_model_from_env

        provider_id = os.environ.get("AGENT_PROVIDER_ID", "qwen")
        try:
            model = create_model_from_env()
        except (ValueError, ProviderError) as e:
            raise RuntimeError(f"创建模型失败（provider={provider_id}）: {e}") from e

    model_name = getattr(model, "model", "")
    max_tokens = getattr(model, "max_tokens", 0)
    temperature = getattr(model, "temperature", 0.0)
    logger.info(
        "创建模型: alias=%s, provider=%s, model=%s (max_tokens=%d, temperature=%.2f)",
        provider_alias or "(env)", provider_id, model_name, max_tokens, temperature,
    )
    return model


def _make_consume_pending_user_message_callback(
    session_id: str,
) -> Callable[[str], Awaitable[str | None]]:
    """构造 consume_pending_user_message 回调 — Phase 30.1 新增

    返回一个 async 函数，runtime 在 iteration > 1 时调用它从 turn_queue 取 steer 消息。
    对标 Cline agent-runtime.ts L1252-1267 consumePendingUserMessage。

    Args:
        session_id: 会话 ID（闭包捕获）

    Returns:
        async (session_id_arg) -> str | None
    """
    async def _consume(session_id_arg: str) -> str | None:
        # session_id_arg 应与闭包的 session_id 一致，但优先用 arg（防御性）
        sid = session_id_arg or session_id
        try:
            controller = _get_turn_queue_controller()
            entry = controller.consume_steer(sid)
            if entry is None:
                return None
            logger.info(
                "turn_queue: runtime iteration 消费 steer 消息 session=%s prompt=%d字符",
                sid, len(entry.prompt),
            )
            return entry.prompt
        except Exception as e:
            logger.warning("turn_queue: consume_steer 失败 session=%s: %s", sid, e)
            return None

    return _consume


def _create_runtime(
    system_prompt: str,
    session_id: str = "default",
    provider_alias: str | None = None,
) -> AgentRuntime:
    """创建配置好的 AgentRuntime 实例

    Phase 16 增强（修复 B4）:
        - Plan 模式下通过 tool_policies 禁用 editor / apply_patch / file_write
        - 配合 PLAN_MODE_PROMPT + switch_to_act_mode 工具约束 LLM 行为

    Phase 12 增强: 传入 session_id 让 Plan Mode 工具按会话隔离状态。
    Phase 13 增强: 创建 ContextCompactor 并注册为 before_model hook，
                   自动触发 LLM 上下文压缩。

    Args:
        system_prompt: 系统提示文本
        session_id: 会话 ID（Phase 12 新增，用于 Plan Mode 状态隔离）
        provider_alias: 前端选择的 Provider 配置别名。为空时使用环境变量默认配置。
    """
    # 创建模型（根据 provider_alias 从 providers.yaml 或环境变量读取配置）
    model = _create_model(provider_alias)

    # 根据当前 mode 配置工具策略
    from agent.state import get_mode

    current_mode = get_mode(session_id)
    tool_policies: dict[str, dict[str, Any]] = {}
    if current_mode == "plan":
        # Plan 模式下禁止编辑/写文件类工具
        tool_policies = {
            "editor": {"enabled": False, "reason": "Plan 模式下禁止编辑文件，如需执行请先切换到 Act 模式"},
            "apply_patch": {"enabled": False, "reason": "Plan 模式下禁止打补丁，如需执行请先切换到 Act 模式"},
            "file_write": {"enabled": False, "reason": "Plan 模式下禁止写文件，如需执行请先切换到 Act 模式"},
        }

    # 解析本次运行实际使用的 provider_id / model_id（用于 runtime tool routing）
    if provider_alias:
        from agent.provider_settings import get_provider_settings_store
        cfg = get_provider_settings_store().get_provider(provider_alias)
        runtime_provider_id = cfg.provider_id if cfg else os.environ.get("AGENT_PROVIDER_ID", "")
        runtime_model_id = cfg.model_id if cfg else os.environ.get("AGENT_MODEL_NAME", "")
    else:
        runtime_provider_id = os.environ.get("AGENT_PROVIDER_ID", "")
        runtime_model_id = os.environ.get("AGENT_MODEL_NAME", "")

    # 创建 AgentRuntime
    config = AgentRuntimeConfig(
        model=model,
        system_prompt=system_prompt,
        max_iterations=20,
        session_id=session_id,  # Phase 12: 传入 session_id 供 runtime 上下文使用
        tool_policies=tool_policies,  # Phase 16: Plan 模式下禁用编辑类工具
        # Phase 30.1: 注入 turn_queue steer 消息消费回调
        # runtime 在 iteration > 1 时调用此回调，从 turn_queue 取 steer 类型消息追加到 model request
        consume_pending_user_message=_make_consume_pending_user_message_callback(session_id),
        # Phase 32.1: 模型工具路由配置 — 对标 Cline model-tool-routing
        # provider_id 留空时由 runtime 从 model 对象自动推断（QwenModel → "qwen"）
        provider_id=runtime_provider_id,
        model_id=runtime_model_id,
    )
    runtime = AgentRuntime(config=config)

    # 注册工具 — Phase 12: 传入 session_id 让 Plan Mode 按会话隔离状态
    project_root = _get_project_root()
    for tool in create_default_tools(
        working_dir=str(project_root),
        session_id=session_id,
    ):
        runtime.register_tool(tool)

    # 注册 skills 工具 — 对标 Cline createSkillsTool
    # skills 工具在主 agent 上下文中注入 skill 指令，不创建独立子 runtime
    registry = _get_skill_registry()
    # Stage 37.2 (S2): skills_timeout_ms 可配置 — 对标 Cline config.skillsTimeoutMs
    # 通过 AGENT_SKILLS_TIMEOUT_MS 环境变量覆盖默认 30000ms（P2-13: 从 15000 提升到 30000）
    skills_timeout_ms = int(os.environ.get("AGENT_SKILLS_TIMEOUT_MS", "30000"))
    runtime.register_tool(SkillsTool(registry, skills_timeout_ms=skills_timeout_ms))

    # Phase 13: 注册 ContextCompactor 作为 before_model hook
    # Phase 16: 参数对齐 Cline（移除硬编码 65536/0.8/6，用默认值 128000/0.9/20000）
    # 对标 Cline createContextCompactionPrepareTurn，每轮调 LLM 前自动检查并压缩上下文
    # 使用主 agent 的 QwenModel 实例生成 agentic 摘要，失败时回退到 basic 策略
    compactor = ContextCompactor(
        model=model,
        state_manager=CompactionStateManager(),
    )
    runtime.register_hooks(AgentHooks(before_model=compactor.before_model))

    # Phase 21: 注册 CheckpointHook — 写工具执行前保存会话快照
    # 对标 Cline checkpoint 机制，在 requires_approval=True 的工具执行前创建检查点
    # Stage 6.6: 增加 AGENT_ENABLE_MESSAGE_CHECKPOINT 开关，默认开启保持向后兼容
    #   - 默认: 开启（保持向后兼容）
    #   - 设为 "0"/"false"/"no" 关闭
    #   - 关闭后 /rollback 端点无法回滚消息（无 checkpoint 可用）
    if os.environ.get("AGENT_ENABLE_MESSAGE_CHECKPOINT", "true").lower() not in ("0", "false", "no"):
        from agent.checkpoint import CheckpointHook
        runtime.register_hooks(CheckpointHook(
            session_id=session_id,
            session_manager=_session_manager,
        ))
    else:
        logger.info(f"Stage 6.6: 消息 checkpoint 已通过 AGENT_ENABLE_MESSAGE_CHECKPOINT 关闭")

    # Phase 33.2: 注册 FileCheckpointHook — 写工具执行前保存工作区文件状态快照
    # 对标 Cline shadow-git checkpoint，用 git stash create 捕获工作区状态
    # 通过前端 Agent 设置页写入 agent_config/settings.yaml 的 file_checkpoint 开关，或
    # AGENT_ENABLE_FILE_CHECKPOINT=1 环境变量启用（环境变量优先），默认关闭以保持现有性能
    # 启用后可在 /api/chat/file_checkpoints 端点查询，/api/chat/rollback_file 回滚
    # 与 AGENT_ENABLE_MESSAGE_CHECKPOINT 独立：消息 checkpoint 默认开启，文件 checkpoint 默认关闭
    # 启用后 /rollback 端点会联动文件回滚（见 Stage 6.5）
    # 注意：本钩子在启动时注册，运行期切换开关需重启服务才生效
    if os.environ.get("AGENT_ENABLE_FILE_CHECKPOINT", "").lower() in ("1", "true", "yes"):
        _file_checkpoint_enabled = True
    else:
        try:
            from agent.settings_store import is_feature_enabled
            _file_checkpoint_enabled = is_feature_enabled("file_checkpoint")
        except Exception:
            _file_checkpoint_enabled = False
    if _file_checkpoint_enabled:
        try:
            from agent.file_checkpoint import (
                create_before_tool_checkpoint_hook,
                init_checkpoint_manager as init_file_checkpoint_manager,
            )
            # 初始化全局 FileCheckpointManager 单例
            init_file_checkpoint_manager()
            # 确定工作区根目录：优先 AGENT_WORKSPACE_ROOT，否则用项目根目录
            workspace_root = os.environ.get("AGENT_WORKSPACE_ROOT") or os.getcwd()
            runtime.register_hooks(AgentHooks(
                before_tool=create_before_tool_checkpoint_hook(
                    session_id=session_id,
                    workspace_root=workspace_root,
                ),
            ))
            logger.info(
                f"Phase 33.2: 已注册 FileCheckpointHook (session={session_id}, workspace={workspace_root})"
            )
        except Exception as e:
            logger.warning(f"Phase 33.2: 注册 FileCheckpointHook 失败: {e}")

    # Phase 24: 注册 TelemetryHooks — 记录运行/工具事件到遥测系统
    # 对标 Cline telemetry，通过 hooks 集成，不侵入 runtime 主循环
    # 注意: 必须复用同一个 TelemetryHooks 实例，因为 before_tool 在
    # self._tool_starts 记录开始时间，after_tool 从同一 dict 读取计算耗时，
    # 多实例会导致 duration_ms 永远回退到 ctx.duration_ms（Phase 25 修复）
    try:
        from agent.telemetry import TelemetryHooks
        telemetry_hooks = TelemetryHooks(session_id)
        runtime.register_hooks(AgentHooks(
            before_run=telemetry_hooks.before_run,
            after_run=telemetry_hooks.after_run,
            before_tool=telemetry_hooks.before_tool,
            after_tool=telemetry_hooks.after_tool,
        ))
    except Exception as e:
        logger.warning(f"Phase 24: 注册 TelemetryHooks 失败: {e}")

    # Phase 26: 注册 AutoApprovalPolicy — 自动审批策略
    # 只读工具/命令自动批准，写操作需用户审批，危险命令自动拒绝
    # 必须在 ConnectorHooks 之前注册，确保本地策略优先决策
    try:
        auto_approval_policy = AutoApprovalPolicy()
        runtime.register_hooks(AgentHooks(
            before_approval=auto_approval_policy.before_approval,
        ))
        logger.info(f"Phase 26: 已注册自动审批策略 (mode={auto_approval_policy.mode})")
    except Exception as e:
        logger.warning(f"Phase 26: 注册自动审批策略失败: {e}")

    # Phase 24: 注册 ConnectorHooks — 将 agent 事件路由到外部命令
    # 对标 Cline connectors，监听运行/工具/审批事件并派发到外部 shell 命令
    try:
        from agent.connectors import ConnectorHooks
        connector_hooks = ConnectorHooks(session_id=session_id)
        runtime.register_hooks(AgentHooks(
            before_run=connector_hooks.before_run,
            after_run=connector_hooks.after_run,
            before_tool=connector_hooks.before_tool,
            after_tool=connector_hooks.after_tool,
            before_approval=connector_hooks.before_approval,
        ))
    except Exception as e:
        logger.warning(f"Phase 24: 注册 ConnectorHooks 失败: {e}")

    # Memory: 注册 动态召回(before_model) + 抽取(after_run) 钩子 — 对齐 Claude Code
    #   - before_model: 每次 query 首次调 LLM 前召回相关记忆，作为 [System Reminder] 注入
    #   - after_run: 每次 query 结束后 fire-and-forget 抽取新记忆
    # 静态记忆指令 + 索引由 _build_system_prompt 的 register_rule 注入 system prompt。
    # 总开关 AGENT_ENABLE_MEMORY（默认开启）统一门控。
    try:
        from agent.memory.hooks import (
            memory_after_run_hook,
            memory_before_model_hook,
            memory_enabled,
        )

        if memory_enabled():
            runtime.register_hooks(AgentHooks(
                before_model=memory_before_model_hook,
                after_run=memory_after_run_hook,
            ))
            logger.info(f"Memory: 已注册 memory 钩子 (session={session_id})")
    except Exception as e:
        logger.warning(f"Memory: 注册 memory 钩子失败: {e}")

    return runtime


def _build_system_prompt(
    session_id: str = "default",
    task_type: str = "general",
    provider_alias: str | None = None,
) -> str:
    """构建系统提示 — 使用 agent_config/ 下的 Cline 风格配置

    Phase 16 增强（修复 B1）:
        - 传入 tools 列表给 SystemPromptBuilder，构建 tools_section 段
        - 传入 working_dir 给 SystemPromptBuilder，构建 environment 段

    Phase 12 增强: 传入 session_id 让 SystemPromptBuilder 查询当前 mode，
    Plan 模式时注入 PLAN_MODE_PROMPT。

    Args:
        session_id: 会话 ID（Phase 12 新增，用于查询当前 mode）
        task_type: 任务类型，用于加载 agent_config/rules/<task_type>.md
                   默认 "general"，可传 "report" / "analysis" / "trading_plan" 等
        provider_alias: 前端选择的 Provider 配置别名，用于确定 provider_id

    Returns:
        完整的系统提示文本
    """
    project_root = _get_project_root()
    agents_path = project_root / "agent_config" / "AGENTS.md"
    # Phase 29.5: rules_dir 指向 agent_config/rules/，供 rules_loader 扫描
    rules_dir = project_root / "agent_config" / "rules"

    registry = _get_skill_registry()

    # Phase 16: 获取工具列表用于构建 tools_section 段
    tools = create_default_tools(
        working_dir=str(project_root),
        session_id=session_id,
    )

    builder = SystemPromptBuilder(
        agents_path=agents_path if agents_path.exists() else None,
        skills_registry=registry,
        session_id=session_id,  # Phase 12: 传入 session_id 用于查询 mode
        tools=tools,  # Phase 16: 工具列表用于 tools_section
        working_dir=str(project_root),  # Phase 16: 工作目录用于 environment 段
        rules_dir=rules_dir if rules_dir.exists() else None,  # Phase 29.5: 规则目录
    )
    # Memory: 静态记忆指令 + MEMORY.md 索引注入 system prompt — 对齐 Claude Code loadMemoryPrompt
    # 通过 Cline 原生 register_rule（contributionRegistry）注入，作为 rule 合并到 Rules 段末尾。
    # 动态召回（按 query 选择相关记忆）由 before_model 钩子完成，见 _create_runtime。
    try:
        from agent.memory.hooks import memory_enabled
        from agent.memory import memory_manager as _mgr
        from agent.memory.memory_recall import build_memory_prompt

        if memory_enabled():
            _mem_dir = _mgr.ensure_memory_dir_exists()
            _entry = _mgr.read_entrypoint(_mem_dir)
            builder.register_rule("memory", build_memory_prompt(_mem_dir, _entry))
    except Exception as e:
        logger.warning("Memory: 注入静态记忆指令失败: %s", e)
    # P2-15: 透传 provider_id 到 SystemPromptBuilder.build()，使 metadata 门控生效
    # 与 _create_runtime 保持同一来源（优先前端选择的 alias 配置，其次环境变量），
    # 保证 system prompt 的 metadata 注入判断与 runtime 的 provider 路由一致
    if provider_alias:
        from agent.provider_settings import get_provider_settings_store
        cfg = get_provider_settings_store().get_provider(provider_alias)
        provider_id = cfg.provider_id if cfg else os.environ.get("AGENT_PROVIDER_ID", "")
    else:
        provider_id = os.environ.get("AGENT_PROVIDER_ID", "")
    return builder.build(task_type=task_type, provider_id=provider_id)


# ============================================================================
# SSE 生成器
# ============================================================================


async def _run_session_turn_loop(
    router: SessionRouter,
    message: str,
    session_id: str,
    history: list[dict] | None = None,
    mode: str | None = None,
    task_type: str = "general",
    provider_alias: str | None = None,
) -> Any:
    """会话级 turn 循环 — 将本会话的全部 run 事件广播给订阅者

    会话级事件广播架构: 一个会话同时只有一个 run（其余消息经 turn_queue 排队），
    本循环依次执行: 首部 drain 排队消息 -> 首次 run -> mode rebuild/auto-continue -> 末尾 drain。
    所有事件通过 router.broadcast 推送给订阅该会话的全部 SSE 连接（多标签页/刷新共享），
    不再与发起请求的单个连接绑定。

    对比旧 _sse_generator: 业务逻辑（turn_queue 排队、runtime、session_manager）完全不变，
    仅将事件分发从"yield 给单个连接"改为"广播给会话订阅者"。
    """
    broadcast = router.broadcast

    # Phase 15: 根据前端传入的 mode 设置会话模式
    # 让用户通过前端按钮切换的模式能在本次请求中生效
    if mode in ("act", "plan"):
        from agent.state import set_mode
        set_mode(session_id, mode)

    # 0. 预热 MCP 工具缓存：确保 system prompt 构建前已加载各服务器的工具列表
    try:
        from agent.mcp.registry import get_registry
        registry = get_registry()
        for srv in registry.list_servers():
            try:
                await registry.list_tools(srv.name)
            except Exception as e:
                logger.warning(f"MCP 工具预热失败 {srv.name}: {e}")
    except Exception as e:
        logger.warning(f"MCP 注册表预热失败: {e}")

    # 1. 构建系统提示 — Phase 12: 传入 session_id 用于查询 mode
    try:
        system_prompt = _build_system_prompt(
            session_id=session_id,
            task_type=task_type,
            provider_alias=provider_alias,
        )
    except Exception as e:
        broadcast(_sse_event("error", {"text": f"系统提示构建失败: {e}"}))
        broadcast(_sse_event("done", {}))
        return

    # 3. 准备消息历史（首次 run 使用；后续 queue 消费的 run 会重新从 session_manager 取最新消息）
    messages = _session_manager.get_messages(session_id)

    # Stage 40: 修复中止后重发消息导致 tool_calls 不匹配的 400 错误
    # 如果最后一条 assistant 消息有 tool_calls 但未被 tool 消息响应，
    # 插入错误 tool 结果，确保消息序列有效（OpenAI API 要求）。
    _fix_unresolved_tool_calls(messages, _session_manager, session_id)
    # 注释掉：前端 history 覆盖会导致工具调用结果丢失
    # SessionManager 已完整持久化消息历史，无需前端 history 参数
    # if history:
    #     messages = _convert_history(history)

    # Phase 16: 用户消息包裹 <user_input mode="..."> 标签 — 修复 B5
    # 对标 Cline MODE_TAG_INSTRUCTIONS，让 LLM 能识别当前工作模式
    from agent.state import get_mode, set_mode
    current_mode = get_mode(session_id)
    # Stage 36.1 (M1): prepend <mode_notice> 若有 pending mode 切换
    # 对标 Cline sdk-session-lifecycle.ts L374 / formatModeSwitchNotice
    # 在 set_mode 切换 mode 时记录 pending notice，下一条用户消息前 consume 并 prepend
    from agent.state import consume_mode_notice, format_mode_switch_notice
    notice = consume_mode_notice(session_id)
    notice_prefix = format_mode_switch_notice(notice) + "\n" if notice else ""
    wrapped_message = f'{notice_prefix}<user_input mode="{current_mode}">\n{message}\n</user_input>'
    messages.append(create_text_message(MessageRole.USER, wrapped_message))

    # Phase 13: 移除手动上下文压缩 — ContextCompactor 现在作为 before_model hook
    # 在 runtime 内部每轮调 LLM 前自动检查并压缩，无需在 server 层手动处理

    # ------------------------------------------------------------------
    # _run_once：单次 agent 运行的嵌套 async generator
    # 对标 Cline 单次 run：创建 runtime + 启动 run_agent + 消费事件 + 清理
    # 可重复调用：首次 run 和 queue 消费的后续 run 都通过此函数
    # ------------------------------------------------------------------
    async def _run_once(
        user_message: str,
        run_messages: list,
        run_system_prompt: str,
        on_sse: Callable[[str], None] | None = None,
    ) -> Any:
        """单次 agent 运行 — 通过 on_sse 回调推送 SSE 事件

        Args:
            user_message: 用户输入文本（用于 runtime.run 入参）
            run_messages: 消息历史列表（含本次用户消息）
            run_system_prompt: 系统提示文本
            on_sse: 事件回调（默认回退为 async generator yield，兼容旧调用）
        """
        # 会话级广播模式: 事件通过 on_sse 回调分发（必须传入）
        emit = on_sse or (lambda sse: None)

        # 创建 AgentRuntime — Phase 12: 传入 session_id 让工具按会话隔离状态
        try:
            runtime = _create_runtime(
                run_system_prompt,
                session_id=session_id,
                provider_alias=provider_alias,
            )
        except Exception as e:
            emit(_sse_event("error", {"text": str(e)}))
            return

        # 事件队列 + 状态跟踪
        event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        # Stage 6.7: runtime 主动推送事件队列 — 用于 file_context_updated 等事件
        # runtime 在 after_tool hook 中通过 register_sse_event_callback 注册的回调
        # 将事件放入此队列，主循环消费时 yield 给前端
        sse_event_queue: asyncio.Queue[dict] = asyncio.Queue()
        run_state = {
            "tool_idx": 0,
            "has_tool_calls": False,
        }

        def on_event(event: AgentEvent) -> None:
            """事件监听器 — 将 AgentRuntime 事件放入队列"""
            event_queue.put_nowait(event)

        runtime.subscribe(on_event)

        # Stage 6.7: 注册 SSE 事件回调 — runtime 主动推送事件给前端
        # 对标 Cline 的实时事件推送机制（Cline 也无此事件，本任务为体验增强）
        async def _runtime_sse_callback(event_type: str, data: dict) -> None:
            """runtime SSE 事件回调 — 将事件放入 sse_event_queue 供主循环消费

            callback 签名要求 async def，且参数为 (event_type, data)。
            data 字段会被展开为 SSE 载荷。
            """
            await sse_event_queue.put({"type": event_type, **data})

        runtime.register_sse_event_callback(_runtime_sse_callback)

        # 注册到活跃 runtime 表（用于 abort）
        _active_runtimes[session_id] = runtime

        # 启动 Agent 运行（后台任务）
        async def run_agent() -> None:
            try:
                result = await runtime.run(user_message, messages=run_messages)
                if result and result.messages:
                    _session_manager.update(session_id, result.messages)
            except Exception as e:
                logger.error(f"Agent 运行失败: {e}", exc_info=True)
                await event_queue.put(AgentEvent(type=RUN_FAILED, error=e))
            finally:
                _active_runtimes.pop(session_id, None)
                await event_queue.put(None)  # 哨兵

        run_task = asyncio.create_task(run_agent())

        # 发送初始事件
        emit(_sse_event("phase", {"phase": "thinking"}))

        # 流式文本时间窗合并缓冲 (性能优化: 降低 reasoning/token SSE 事件频率)
        # 仅合并传输层的 reasoning/token 事件, 不改动 agent 业务逻辑, 最终显示内容不变
        # 窗口: reasoning 20ms (thinking 更新更快), token 40ms (正文 markdown 渲染有前端 100ms 节流)
        _stream_window_reasoning = 0.02
        _stream_window_token = 0.04
        _pending_reasoning: list[str] = []
        _pending_token: list[str] = []
        # 终端输出合并缓冲 (性能优化: run_commands 长输出逐行推送 → 按窗口合并, 事件量降一个数量级)
        # 每条 terminal_output 的 text 是 readline() 完整一行(含 \n 结尾), 拼接后行不粘连, 显示内容不变
        _pending_term: list[dict] = []
        _last_flush = time.time()

        def _flush_stream_pending() -> list[str]:
            """将 pending 缓冲合并为完整 SSE 事件并清空, 保持 reasoning 先于 token 的顺序"""
            nonlocal _last_flush
            out: list[str] = []
            if _pending_reasoning:
                out.append(_sse_event("reasoning", {"text": "".join(_pending_reasoning)}))
                _pending_reasoning.clear()
            if _pending_token:
                out.append(_sse_event("token", {"text": "".join(_pending_token)}))
                _pending_token.clear()
            if out:
                _last_flush = time.time()
            return out

        def _flush_term_pending() -> list[str]:
            """将终端输出缓冲按命令(index)合并为完整 SSE 事件并清空

            同一 80ms 窗口内同一命令的 stdout 文本拼接为一条事件:
            事件量从"每行一条"降到"每窗口每条命令一条", 文本内容与逐条推送一致
            (每条 text 均以 \\n 结尾, 拼接不粘连)。
            """
            nonlocal _last_flush
            out: list[str] = []
            if _pending_term:
                # 按 index 分组合并, 保持插入顺序 (Python 3.7+ dict 保序)
                merged: dict = {}
                for _d in _pending_term:
                    _idx = _d.get("index")
                    if _idx not in merged:
                        merged[_idx] = dict(_d)
                    else:
                        merged[_idx]["text"] = (merged[_idx].get("text") or "") + (_d.get("text") or "")
                for _d in merged.values():
                    out.append(_sse_event("terminal_output", _d))
                _pending_term.clear()
                _last_flush = time.time()
            return out

        def _flush_all_pending() -> list[str]:
            """统一 flush 全部缓冲 (term → reasoning → token), 保证转发顺序"""
            return _flush_term_pending() + _flush_stream_pending()

        # 消费事件
        started_at = time.time()
        timeout_seconds = 600

        try:
            while True:
                # 动态超时: 有 pending 缓冲时, 时间窗到期即自动 flush, 保证流式实时性
                # reasoning 用更短窗口(thinking 刷新更快), token/终端用 40ms
                wait_timeout = 30.0
                if _pending_reasoning or _pending_token or _pending_term:
                    _win = _stream_window_reasoning if _pending_reasoning else _stream_window_token
                    wait_timeout = max(0.001, _win - (time.time() - _last_flush))
                try:
                    event = await asyncio.wait_for(
                        event_queue.get(),
                        timeout=wait_timeout,
                    )
                except asyncio.TimeoutError:
                    # 检查总超时
                    if time.time() - started_at > timeout_seconds:
                        for _s in _flush_all_pending():
                            emit(_s)
                        emit(_sse_event("error", {"text": "对话超时 (600s)"}))
                        break
                    if _pending_reasoning or _pending_token or _pending_term:
                        # 时间窗到期, flush 缓冲后继续等待
                        for _s in _flush_all_pending():
                            emit(_s)
                        continue
                    # 发送心跳保持连接
                    emit(": heartbeat\n\n")
                    continue

                # 哨兵：运行结束
                if event is None:
                    for _s in _flush_all_pending():
                        emit(_s)
                    break

                # 处理事件: reasoning/token/terminal_output 进入合并缓冲, 其余事件先 flush 再转发, 保证顺序
                async for sse in _handle_event(event, run_state):
                    if sse.startswith("data: "):
                        try:
                            _payload = json.loads(sse[6:].strip())
                        except Exception:
                            _payload = {}
                        _etype = _payload.get("type")
                        if _etype == "reasoning":
                            _pending_reasoning.append(_payload.get("text", "") or "")
                            continue
                        if _etype == "token":
                            _pending_token.append(_payload.get("text", "") or "")
                            continue
                        if _etype == "terminal_output":
                            # 终端输出合并: finished 标记(命令结束)与 stderr 即时转发以保持状态语义,
                            # 普通 stdout 进入 80ms 合并缓冲
                            if _payload.get("finished") or _payload.get("is_stderr"):
                                for _s in _flush_all_pending():
                                    emit(_s)
                                emit(sse)
                                continue
                            _pending_term.append(_payload)
                            # 缓冲过大时立即 flush, 防止单窗口文本拼接过长
                            if len(_pending_term) >= 200:
                                for _s in _flush_all_pending():
                                    emit(_s)
                            continue
                    for _s in _flush_all_pending():
                        emit(_s)
                    emit(sse)

                # Stage 6.7: 排空 runtime 主动推送的 SSE 事件队列
                # after_tool hook（含 _file_context_tracker_hook）在
                # TOOL_EXECUTION_FINISHED 事件发射前执行，因此处理完
                # tool_output 事件后即可排空 sse_event_queue
                while not sse_event_queue.empty():
                    try:
                        evt = sse_event_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    emit(_sse_event(evt.get("type", "unknown"), evt))

        finally:
            # 确保后台任务完成
            if not run_task.done():
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass

        # Stage 6.7: 运行结束后再排空一次 SSE 事件队列，避免遗漏
        while not sse_event_queue.empty():
            try:
                evt = sse_event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            emit(_sse_event(evt.get("type", "unknown"), evt))

        emit(_sse_event("phase", {"phase": "answering"}))

    # ------------------------------------------------------------------
    # P1-17: drain 检查移到 send_callback 开始处 — 首部 drain 循环
    # 对标 Cline drain() L294-334：send_callback 启动时检查 turn queue
    # 若上一轮 run 遗留了未消费的 queue 消息，在处理当前用户消息前先消费它们
    # 避免遗留消息等待当前 turn 结束才被处理（消费延迟问题）
    # 与末尾循环互补：首部消费遗留消息，末尾消费当前 run 期间新增的消息
    # ------------------------------------------------------------------
    while True:
        entry = None
        try:
            controller = _get_turn_queue_controller()
            q_state = controller._states.get(session_id)
            if q_state is None or not q_state.pending_prompts:
                break

            # 取出队首
            entry, prompts_snapshot = controller._service.shift_next(q_state)
            if entry is None:
                break

            # steer 条目由 runtime iteration 消费，不应在 run 间消费
            # 防御性判断：若队首是 steer，放回队首并退出
            if entry.delivery == "steer":
                controller._service.requeue_front(q_state, entry)
                break

            # 发射 pending_prompts + pending_prompt_submitted 事件
            # 对标 Cline drain() L306-307 emitPrompts + emitSubmitted
            broadcast(_sse_event("pending_prompts", {
                "session_id": session_id,
                "prompts": prompts_snapshot,
            }))
            broadcast(_sse_event("pending_prompt_submitted", {
                "session_id": session_id,
                "id": entry.id,
                "prompt": entry.prompt,
                "delivery": entry.delivery,
            }))

            # 如果 entry 指定了 mode，更新会话模式并重建系统提示
            run_system_prompt = system_prompt
            if entry.mode and entry.mode != current_mode:
                set_mode(session_id, entry.mode)
                current_mode = entry.mode
                try:
                    run_system_prompt = _build_system_prompt(
                        session_id=session_id, task_type=task_type
                    )
                except Exception as e:
                    logger.warning("turn_queue: 首部 drain 重建系统提示失败: %s", e)
                    run_system_prompt = system_prompt

            # 重新从 session_manager 取最新消息（含上一轮 assistant 响应），
            # 追加本次 queue 用户消息
            queued_messages = _session_manager.get_messages(session_id)
            # Stage 36.1 (M1): prepend <mode_notice> 若有 pending mode 切换
            notice = consume_mode_notice(session_id)
            notice_prefix = format_mode_switch_notice(notice) + "\n" if notice else ""
            wrapped = f'{notice_prefix}<user_input mode="{current_mode}">\n{entry.prompt}\n</user_input>'
            queued_messages.append(create_text_message(MessageRole.USER, wrapped))

            # 复用 _run_once 启动新 run，事件广播给会话全部订阅者
            await _run_once(entry.prompt, queued_messages, run_system_prompt, on_sse=broadcast)
        except Exception as e:
            logger.warning("turn_queue: 首部 drain 消费 queue 失败 session=%s: %s", session_id, e)
            # 失败时把 entry 重新入队（对标 Cline requeueFront L320）
            try:
                controller = _get_turn_queue_controller()
                q_state = controller._states.get(session_id)
                if q_state is not None and entry is not None:
                    controller._service.requeue_front(q_state, entry)
            except Exception:
                pass
            break

    # ------------------------------------------------------------------
    # 首次 run
    # ------------------------------------------------------------------
    await _run_once(message, messages, system_prompt, on_sse=broadcast)

    # ------------------------------------------------------------------
    # 会话重建 + auto-continue — 对标 Cline rebuildSessionForMode
    # ------------------------------------------------------------------
    # run 期间若发生模式切换（SwitchToActModeTool / SwitchToPlanModeTool），
    # 工具会通过 request_mode_rebuild 写入 pending 请求。
    # 此处消费该请求，执行：
    #   1. rebuild_messages_for_mode: 清理旧模式上下文，保留最近几轮对话
    #   2. 若 to_mode == "act": 重建 act 模式系统提示，注入 ACT_MODE_CONTINUATION_PROMPT
    #      自动启动续跑（对标 Cline autoContinue + ACT_MODE_CONTINUATION_PROMPT）
    #   3. 若 to_mode == "plan": 仅清理消息，不自动续跑（plan 方向无 auto-continue）
    # ------------------------------------------------------------------
    from agent.tools.plan_mode import (
        ACT_MODE_CONTINUATION_PROMPT,
        consume_mode_rebuild,
        rebuild_messages_for_mode,
    )

    rebuild_info = consume_mode_rebuild(session_id)
    if rebuild_info is not None:
        new_mode = rebuild_info.get("to_mode", "")

        # 会话重建：清理旧模式上下文
        # 取最新消息（含本轮 assistant 响应），裁剪后写回 session_manager
        latest_messages = _session_manager.get_messages(session_id)
        rebuilt_messages = rebuild_messages_for_mode(latest_messages)
        _session_manager.update(session_id, rebuilt_messages)

        if new_mode == "act":
            # plan → act: auto-continue
            # 重建 act 模式系统提示（不含 PLAN_MODE_PROMPT）
            try:
                act_system_prompt = _build_system_prompt(
                    session_id=session_id, task_type=task_type
                )
            except Exception as e:
                logger.warning("auto-continue: 重建 act 系统提示失败: %s", e)
                act_system_prompt = system_prompt

            # 更新 current_mode 和 system_prompt 供后续 queue 消费使用
            current_mode = "act"
            system_prompt = act_system_prompt

            # 注入 ACT_MODE_CONTINUATION_PROMPT 作为合成的 user message
            # 对标 Cline fireAndForgetSend(prompt) — 不作为用户气泡展示，
            # 仅驱动 LLM 继续执行已批准的计划
            continuation_messages = _session_manager.get_messages(session_id)
            wrapped_continuation = (
                f'<user_input mode="act">\n{ACT_MODE_CONTINUATION_PROMPT}\n</user_input>'
            )
            continuation_messages.append(
                create_text_message(MessageRole.USER, wrapped_continuation)
            )

            # 启动续跑 — 复用 _run_once，事件广播给会话全部订阅者
            await _run_once(
                ACT_MODE_CONTINUATION_PROMPT,
                continuation_messages,
                act_system_prompt,
                on_sse=broadcast,
            )
        elif new_mode == "plan":
            # act → plan: 仅会话重建，无 auto-continue
            # 更新 current_mode 供后续 queue 消费使用
            current_mode = "plan"
            try:
                system_prompt = _build_system_prompt(
                    session_id=session_id, task_type=task_type
                )
            except Exception as e:
                logger.warning("mode rebuild: 重建 plan 系统提示失败: %s", e)

    # ------------------------------------------------------------------
    # Phase 30.1 P0 修复：run 结束后自动消费 queue 类型排队消息
    # 对标 Cline drain() L295-335：await this.deps.send() 启动新 run
    # 在 _sse_generator 内部循环消费，确保事件通过原 SSE 连接推送
    #
    # P1-17: drain 触发方式调整后，此末尾循环保留用于消费"当前 run 期间新增"的 queue 消息。
    # 上一轮遗留的 queue 消息已由首部 drain 循环（send_callback 开始处）提前消费。
    # 两处循环互补：首部 drain 消费遗留消息，末尾循环消费当前 run 期间入队的新消息。
    # -------------------------------------------------------------------
    while True:
        entry = None
        try:
            controller = _get_turn_queue_controller()
            q_state = controller._states.get(session_id)
            if q_state is None or not q_state.pending_prompts:
                break

            # 取出队首
            entry, prompts_snapshot = controller._service.shift_next(q_state)
            if entry is None:
                break

            # steer 条目由 runtime iteration 消费，不应在 run 间消费
            # 防御性判断：若队首是 steer，放回队首并退出（run 结束后 steer 应已被消费）
            if entry.delivery == "steer":
                controller._service.requeue_front(q_state, entry)
                break

            # 发射 pending_prompts + pending_prompt_submitted 事件
            # 对标 Cline drain() L306-307 emitPrompts + emitSubmitted
            broadcast(_sse_event("pending_prompts", {
                "session_id": session_id,
                "prompts": prompts_snapshot,
            }))
            broadcast(_sse_event("pending_prompt_submitted", {
                "session_id": session_id,
                "id": entry.id,
                "prompt": entry.prompt,
                "delivery": entry.delivery,
            }))

            # 如果 entry 指定了 mode，更新会话模式并重建系统提示
            run_system_prompt = system_prompt
            if entry.mode and entry.mode != current_mode:
                set_mode(session_id, entry.mode)
                current_mode = entry.mode
                try:
                    run_system_prompt = _build_system_prompt(
                        session_id=session_id, task_type=task_type
                    )
                except Exception as e:
                    logger.warning("turn_queue: 重建系统提示失败: %s", e)
                    run_system_prompt = system_prompt

            # 重新从 session_manager 取最新消息（含上一轮 assistant 响应），
            # 追加本次 queue 用户消息
            queued_messages = _session_manager.get_messages(session_id)
            # Stage 36.1 (M1): prepend <mode_notice> 若有 pending mode 切换
            # 对标 Cline formatModeSwitchNotice，queue 消费的 run 同样需要 consume notice
            from agent.state import consume_mode_notice, format_mode_switch_notice
            notice = consume_mode_notice(session_id)
            notice_prefix = format_mode_switch_notice(notice) + "\n" if notice else ""
            wrapped = f'{notice_prefix}<user_input mode="{current_mode}">\n{entry.prompt}\n</user_input>'
            queued_messages.append(create_text_message(MessageRole.USER, wrapped))

            # 复用 _run_once 启动新 run，事件广播给会话全部订阅者
            await _run_once(entry.prompt, queued_messages, run_system_prompt, on_sse=broadcast)
        except Exception as e:
            logger.warning("turn_queue: 自动消费 queue 失败 session=%s: %s", session_id, e)
            # 失败时把 entry 重新入队（对标 Cline requeueFront L320）
            try:
                controller = _get_turn_queue_controller()
                q_state = controller._states.get(session_id)
                if q_state is not None and entry is not None:
                    controller._service.requeue_front(q_state, entry)
            except Exception:
                pass
            break

    broadcast(_sse_event("done", {}))


async def _handle_event(event: AgentEvent, state: dict) -> Any:
    """将单个 AgentRuntime 事件映射为 SSE 事件

    Args:
        event: AgentRuntime 事件
        state: 状态字典 {tool_idx, has_tool_calls}

    Yields:
        SSE 格式字符串
    """
    if event.type == RUN_STARTED:
        # 运行开始，不需要额外操作（已在外部发送 phase: thinking）
        pass

    elif event.type == ASSISTANT_REASONING_DELTA:
        # 思考过程增量 — 独立事件类型，前端直接渲染到 thinking 区域
        # 对标 Cline assistant-reasoning-delta，不再合并到 token
        if event.text:
            yield _sse_event("reasoning", {"text": event.text})

    elif event.type == ASSISTANT_TEXT_DELTA:
        # 正文输出增量 — 独立事件类型，前端直接渲染到 answer 区域
        # 对标 Cline assistant-text-delta，不再合并到 token
        if event.text:
            yield _sse_event("token", {"text": event.text})

    elif event.type == TOOL_EXECUTION_STARTED:
        # 工具调用开始
        state["has_tool_calls"] = True

        state["tool_idx"] += 1
        yield _sse_event("tool_call", {
            "name": event.tool_name or "unknown",
            "args": _format_tool_args(event.tool_input),
            "idx": state["tool_idx"],
        })

    elif event.type == TOOL_EXECUTION_FINISHED:
        # 工具调用完成
        output = _format_tool_output(event.tool_output)
        yield _sse_event("tool_output", {
            "output": output,
            "error": bool(event.tool_is_error),
            "idx": state["tool_idx"],
        })

    elif event.type == RUN_FINISHED:
        # 运行完成
        pass

    elif event.type == RUN_FAILED:
        # 运行失败
        error_msg = str(event.error) if event.error else "未知错误"
        yield _sse_event("error", {"text": error_msg})

    elif event.type == STATUS_NOTICE:
        # 状态通知 — Phase 12: 转发工具的 emit_update 到前端
        # Plan Mode 工具通过 emit_update 发送 update，
        # runtime 将其转为 STATUS_NOTICE 事件，这里转为对应的 SSE 事件
        async for sse in _handle_status_notice(event):
            yield sse

    elif event.type == TOOL_UPDATED:
        # Phase 2.5: 工具进度更新事件 — 对标 Cline tool-updated
        # _make_emit_update 改为发射 TOOL_UPDATED（原 STATUS_NOTICE），
        # 复用 _handle_status_notice 的分发逻辑（approval_request/todos_updated/mode_changed）
        async for sse in _handle_status_notice(event):
            yield sse

    elif event.type == MESSAGE_ADDED:
        # P1-13: 消息添加事件 — 对标 Cline message-added
        # 通知前端新消息已加入会话，含角色和文本内容
        if event.message is not None:
            msg = event.message
            # 提取文本内容（content 中 TextPart/ReasoningPart 的 text 拼接）
            text_parts = []
            for part in (msg.content or []):
                part_type = getattr(part, "type", None)
                if part_type in ("text", "reasoning"):
                    text_parts.append(getattr(part, "text", ""))
            yield _sse_event("message_added", {
                "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                "text": "\n".join(text_parts) if text_parts else "",
                "message_id": getattr(msg, "id", ""),
            })

    elif event.type == TURN_STARTED:
        # P1-13: 轮次开始事件 — 对标 Cline turn-started
        # 通知前端新的一轮 LLM 调用开始
        yield _sse_event("turn_started", {
            "iteration": event.iteration or 0,
        })

    elif event.type == TURN_FINISHED:
        # P1-13: 轮次完成事件 — 对标 Cline turn-finished
        # 通知前端一轮 LLM 调用完成，含工具调用数
        yield _sse_event("turn_finished", {
            "iteration": event.iteration or 0,
            "tool_call_count": event.tool_call_count or 0,
        })

    elif event.type == ASSISTANT_MESSAGE:
        # P1-13: assistant 消息完成事件 — 对标 Cline assistant-message
        # 通知前端 assistant 消息已完成，含完成原因（stop/tool-calls/max-tokens 等）
        yield _sse_event("assistant_message", {
            "iteration": event.iteration or 0,
            "finish_reason": event.finish_reason or "",
        })

    elif event.type == USAGE_UPDATED:
        # P1-13: 用量更新事件 — 对标 Cline usage-updated
        # 通知前端 token 用量已更新，前端可展示 token 消耗
        usage_data: dict = {}
        if event.usage is not None:
            to_dict_fn = getattr(event.usage, "to_dict", None)
            if callable(to_dict_fn):
                usage_data = to_dict_fn()
            else:
                usage_data = {
                    "input_tokens": getattr(event.usage, "input_tokens", 0),
                    "output_tokens": getattr(event.usage, "output_tokens", 0),
                }
        yield _sse_event("usage_updated", usage_data)


# ============================================================================
# 历史消息转换
# ============================================================================


def _fix_unresolved_tool_calls(messages: list, session_manager=None, session_id: str = "") -> None:
    """修复中止后重发消息导致 tool_calls 不匹配的 400 错误

    遍历消息列表，如果最后一条 assistant 消息有 tool_calls 但未被后续 tool 消息响应，
    插入错误 tool 结果，确保消息序列有效（OpenAI API 要求）。
    """
    last_tool_call_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            last_tool_call_idx = i
            break

    if last_tool_call_idx < 0:
        return  # 没有 tool_calls，无需修复

    # 检查是否有 tool 消息响应了这些 tool_calls
    tool_call_ids = {tc.id for tc in messages[last_tool_call_idx].tool_calls}
    if not tool_call_ids:
        return

    for i in range(last_tool_call_idx + 1, len(messages)):
        msg = messages[i]
        if hasattr(msg, "tool_call_id") and msg.tool_call_id in tool_call_ids:
            tool_call_ids.discard(msg.tool_call_id)

    if not tool_call_ids:
        return  # 所有 tool_calls 都已响应

    # 有未响应的 tool_calls，插入错误 tool 结果
    from agent.types import create_message, MessageRole
    for tc_id in sorted(tool_call_ids):
        messages.append(create_message(
            MessageRole.TOOL,
            tool_call_id=tc_id,
            content=[{"type": "text", "text": json.dumps(
                {"error": "用户手动中止，工具调用被取消", "status": "aborted"}
            )}]
        ))

    # 持久化修复后的消息历史
    if session_manager and session_id:
        session_manager.update(session_id, messages)


def _convert_history(history: list[dict]) -> list[AgentMessage]:
    """将前端历史消息格式转为 AgentMessage 列表

    前端格式: [{"role": "user", "content": "..."}, ...]
    """
    messages: list[AgentMessage] = []
    for item in history:
        role_str = item.get("role", "user")
        content = item.get("content", "")
        if role_str == "user":
            messages.append(create_text_message(MessageRole.USER, content))
        elif role_str == "assistant":
            messages.append(create_text_message(MessageRole.ASSISTANT, content))
    return messages


# ============================================================================
# 状态通知处理 — Phase 12 新增
# ============================================================================


async def _handle_status_notice(event: AgentEvent) -> Any:
    """处理 STATUS_NOTICE 事件 — Phase 12 新增，Phase 15/19 增强

    将工具通过 emit_update 发送的 update 转为对应的 SSE 事件:
        - approval_request: 工具审批请求（runtime 请求用户批准危险工具，Phase 19）
        - ask_question: 向用户提问（ask_question 工具，P1-10 阻塞等待模式）
        - todos_updated: 任务清单更新
        - mode_changed: 模式切换（switch_to_act_mode / switch_to_plan_mode）

    Args:
        event: STATUS_NOTICE 事件，metadata 字段存放 update 数据

    Yields:
        SSE 格式字符串
    """
    metadata = event.metadata
    if not isinstance(metadata, dict):
        return

    # 工具审批请求 — Phase 19 新增，runtime 请求用户批准危险工具调用
    if metadata.get("type") == "approval_request":
        yield _sse_event("approval_request", {
            "tool_call_id": metadata.get("tool_call_id", ""),
            "tool_name": metadata.get("tool_name", ""),
            "input": metadata.get("input", {}),
        })
        return

    # 向用户提问 — P1-10 ask_question 工具阻塞等待用户回答
    # 前端展示问题卡片，用户回答后 POST /api/chat/answer_question
    if metadata.get("type") == "ask_question":
        yield _sse_event("ask_question", {
            "tool_call_id": metadata.get("tool_call_id", ""),
            "question": metadata.get("question", ""),
            "options": metadata.get("options", []),
        })
        return

    # 任务清单更新
    if "todos_updated" in metadata:
        todos_data = metadata["todos_updated"]
        yield _sse_event("todos_updated", {"todos": todos_data})

    # 模式切换 — switch_to_act_mode / switch_to_plan_mode 触发
    if "mode_changed" in metadata:
        mode_data = metadata["mode_changed"]
        yield _sse_event("mode_changed", mode_data)

    # 实时终端输出 — run_commands 长耗时命令进度推送
    if "terminal_output" in metadata:
        term_data = metadata["terminal_output"]
        yield _sse_event("terminal_output", term_data)


# ============================================================================
# 路由定义
# ============================================================================


@router.post("/stream")
async def chat_stream(request: Request):
    """SSE 流式对话接口 — 与 routes/chat.py /stream 完全兼容

    会话级事件广播架构: 一个会话同时只有一个 run（其余消息经 turn_queue 排队）。
    - 无活跃 run: 创建 SessionRouter 并启动会话 turn 循环，本连接订阅其广播流
    - 有活跃 run: 消息入队 turn_queue，返回短 SSE 提示"已排队"
      （排队消息由 turn 循环的 drain 消费并广播，多页面通过 /stream/subscribe 接收）
    """
    try:
        body = await request.json()
    except Exception:
        return _sse_error_response("请求体不是有效的 JSON")

    message = (body.get("message") or "").strip()
    if not message:
        return _sse_error_response("消息不能为空")

    session_id = body.get("session_id", "ui:single")
    history = body.get("history", [])
    mode = body.get("mode")  # Phase 15: 前端传入的工作模式 act | plan
    task_type = body.get("task_type", "general")  # 任务类型，如 report / analysis / general
    provider_alias = body.get("provider_id") or None  # 前端选择的 Provider 配置别名
    # Phase 30.1: 投递模式 — queue(默认) / steer
    delivery = body.get("delivery", "queue")
    if delivery not in ("queue", "steer"):
        delivery = "queue"

    # 检查当前会话是否有活跃的 turn 循环
    router = _session_router.get(session_id)
    if router is not None and router.is_active():
        # 会话有活跃 run → 消息入队（由 turn 循环的 drain 消费并广播），返回短流确认
        controller = _get_turn_queue_controller()
        prompts = controller.enqueue(
            session_id=session_id,
            prompt=message,
            mode=mode,
            delivery=delivery,
        )
        # 广播排队状态给当前会话的所有订阅者（多页面共享排队信息）
        router.broadcast(_sse_event("pending_prompts_updated", {
            "session_id": session_id,
            "prompts": prompts,
            "queued_message": message,
            "delivery": delivery,
        }))

        # 返回特殊 SSE 流提示"已排队"
        async def _queued_stream():
            yield _sse_event("pending_prompts_updated", {
                "session_id": session_id,
                "prompts": prompts,
                "queued_message": message,
                "delivery": delivery,
            })
            yield _sse_event("done", {"reason": "queued"})
        return StreamingResponse(
            _queued_stream(),
            media_type="text/event-stream",
            headers=dict(_SSE_HEADERS),
        )

    # 无活跃 run → 创建会话 router 并启动 turn 循环（含 drain + 首次 run + auto-continue）
    router = SessionRouter(session_id)
    _session_router[session_id] = router
    router.run_task = asyncio.create_task(
        _watch_turn_loop(
            router,
            _run_session_turn_loop(
                router, message, session_id, history, mode, task_type,
                provider_alias=provider_alias,
            ),
        )
    )

    # 订阅该会话的广播流（同一同步段内重放 event_log，保证先重放后增量）
    # 重放末尾追加 ": replay-end" 注释标记，前端据此区分重放与增量:
    # 重放事件统一批处理渲染（避免逐事件重建 DOM），收到标记后切换为实时增量渲染
    conn_id, queue = router.subscribe()
    for ev in router.event_log:
        queue.put_nowait(ev)
    queue.put_nowait(": replay-end\n\n")

    return StreamingResponse(
        _consume_router_stream(router, conn_id, queue),
        media_type="text/event-stream",
        headers=dict(_SSE_HEADERS),
    )


async def _consume_router_stream(
    router: SessionRouter,
    conn_id: str,
    queue: asyncio.Queue,
) -> Any:
    """消费订阅队列直到 run 结束哨兵（payload=None）。

    连接断开时只移除订阅者，不取消 run —— 这正是"刷新/关闭页面对话不打断"的关键。
    """
    try:
        while True:
            payload = await queue.get()
            if payload is None:
                break
            yield payload
    finally:
        router.unsubscribe(conn_id)


async def _watch_turn_loop(router: SessionRouter, coro) -> None:
    """包装会话 turn 循环：无论正常/异常结束，都广播结束哨兵并清理 router。

    订阅者收到 None 哨兵后结束各自 SSE 连接；run 本身运行完毕不受订阅者断开影响。
    """
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"会话 turn 循环异常 session={router.session_id}: {e}", exc_info=True)
    finally:
        router.broadcast(None)
        if _session_router.get(router.session_id) is router:
            _session_router.pop(router.session_id, None)


@router.get("/stream/subscribe")
async def subscribe_stream(session_id: str = "ui:single"):
    """订阅会话的活跃 run 广播流（含 event_log 重放）。

    用于前端页面加载/刷新后接管进行中的 run：先重放该 run 已产生的全部事件，
    再实时接收增量，实现"对话不打断、多页面共享同一信息流"。
    无活跃 run 时立即返回空流（无副作用）。
    """
    router = _session_router.get(session_id)
    if router is None or not router.is_active():
        async def _empty_stream():
            yield ": no-active-run\n\n"
        return StreamingResponse(
            _empty_stream(),
            media_type="text/event-stream",
            headers=dict(_SSE_HEADERS),
        )

    # 同一同步段内: 注册订阅 + 重放 event_log，保证重放与增量广播之间无遗漏/乱序
    # 重放末尾追加 ": replay-end" 注释标记（与 /stream 首次订阅一致）
    conn_id, queue = router.subscribe()
    for ev in router.event_log:
        queue.put_nowait(ev)
    queue.put_nowait(": replay-end\n\n")

    return StreamingResponse(
        _consume_router_stream(router, conn_id, queue),
        media_type="text/event-stream",
        headers=dict(_SSE_HEADERS),
    )


@router.get("/sessions")
async def list_sessions():
    """列出所有会话"""
    sessions = _session_manager.list_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "title": s.title,
                "message_count": s.message_count,
                "created_at": s.created_at,
                "last_active": s.last_active,
            }
            for s in sessions
        ]
    }


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """获取会话的完整消息历史 — 供前端从后端恢复对话记录

    前端侧栏对话列表原本只存于浏览器 localStorage, 换端口/清缓存/换浏览器后会丢失;
    后端 agent_data/sessions/<session_id>.json 是权威存储。此接口让前端启动时能
    按 session_id 拉回完整消息并恢复显示, 使对话上下文可接续。
    """
    from agent.session import _message_to_dict
    messages = _session_manager.get_messages(session_id)
    return {
        "session_id": session_id,
        "messages": [_message_to_dict(m) for m in messages],
    }


@router.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """清空指定会话

    Phase 18 增强: 同时清除持久化的会话状态文件（todos/mode）。
    """
    _session_manager.clear(session_id)
    # Phase 18: 同步清除会话状态（todos/mode）持久化文件
    try:
        from agent.state import clear_session_state
        clear_session_state(session_id)
    except Exception as e:
        logger.warning(f"清除会话状态失败 {session_id}: {e}", exc_info=True)
    # 清除 pending mode rebuild 请求，避免清除后触发 auto-continue
    try:
        from agent.tools.plan_mode import cancel_pending_mode_rebuild
        cancel_pending_mode_rebuild(session_id)
    except Exception as e:
        logger.warning(f"清除 pending mode rebuild 失败 {session_id}: {e}")
    return {"status": "ok"}


@router.get("/sessions/{session_id}/file_context")
async def get_file_context(session_id: str):
    """获取会话的文件上下文状态 — Phase 29.3 新增

    返回当前会话涉及的所有文件，按操作类型分组:
        - read: 读取过的文件
        - edited: 编辑过的文件
        - created: 创建的文件
        - deleted: 删除过的文件

    用途:
        - 前端展示当前会话涉及的文件列表
        - 调试文件操作追踪
        - 后续 budget-projection（Phase 29.4）数据源

    Returns:
        {
            "session_id": "abc123",
            "state": {"read": [...], "edited": [...], "created": [...], "deleted": [...]},
            "entries": [{path, operation, timestamp, tool_name, iteration}, ...],
            "total": <int>
        }
    """
    from agent.file_context_tracker import get_tracker

    tracker = get_tracker(session_id)
    state = tracker.get_state()
    entries = tracker.get_entries()

    return {
        "session_id": session_id,
        "state": state,
        "entries": entries,
        "total": len(entries),
    }


@router.delete("/sessions/{session_id}/file_context")
async def clear_file_context(session_id: str):
    """清空会话的文件上下文状态 — Phase 29.3 新增

    清除内存记录和持久化文件。用于会话重置或调试。
    """
    from agent.file_context_tracker import get_tracker, clear_tracker_cache

    tracker = get_tracker(session_id)
    tracker.clear()
    # 从缓存中移除，下次 get_tracker 会重新创建空 tracker
    clear_tracker_cache(session_id)
    return {"status": "ok", "session_id": session_id}


# ============================================================================
# Turn queue 端点 — Phase 30.1 新增，对标 Cline PendingPromptsController API
# ============================================================================


@router.get("/sessions/{session_id}/pending_prompts")
async def list_pending_prompts(session_id: str):
    """列出会话的待处理输入队列 — Phase 30.1 新增

    Returns:
        {"session_id": "...", "prompts": [{id, prompt, delivery, ...}], "total": N}
    """
    controller = _get_turn_queue_controller()
    prompts = controller.list(session_id)
    return {
        "session_id": session_id,
        "prompts": prompts,
        "total": len(prompts),
    }


@router.delete("/sessions/{session_id}/pending_prompts/{prompt_id}")
async def delete_pending_prompt(session_id: str, prompt_id: str):
    """删除待处理输入条目 — Phase 30.1 新增

    用于前端从排队队列中移除某条消息（用户撤销排队输入）。
    """
    controller = _get_turn_queue_controller()
    removed, prompts = controller.delete(session_id, prompt_id)
    return {
        "session_id": session_id,
        "removed": removed,
        "prompts": prompts,
    }


@router.put("/sessions/{session_id}/pending_prompts/{prompt_id}")
async def update_pending_prompt(session_id: str, prompt_id: str, request: Request):
    """更新待处理输入条目 — Phase 30.1 新增

    用于前端编辑排队中的消息内容/投递模式。

    Body:
        {"prompt": "...", "mode": "act|plan", "delivery": "queue|steer"}
        所有字段可选，未提供则保持原值。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    controller = _get_turn_queue_controller()
    updated, prompts = controller.update(
        session_id=session_id,
        prompt_id=prompt_id,
        prompt=body.get("prompt"),
        mode=body.get("mode"),
        delivery=body.get("delivery"),
    )
    return {
        "session_id": session_id,
        "updated": updated,
        "prompts": prompts,
    }


@router.delete("/sessions/{session_id}/pending_prompts")
async def clear_pending_prompts(session_id: str):
    """清空会话的待处理输入队列 — Phase 30.1 新增

    用于会话重置或用户取消所有排队消息。
    """
    controller = _get_turn_queue_controller()
    controller.clear(session_id)
    return {"status": "ok", "session_id": session_id}


@router.post("/abort")
async def abort_chat(request: Request):
    """中止正在运行的对话 — 对标 Cline abort 机制

    Phase 19 增强: 同时取消该会话的所有待审批请求，避免孤儿审批。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = body.get("session_id", "")
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}

    runtime = _active_runtimes.get(session_id)
    if runtime is None:
        return {"status": "ok", "message": "没有活跃的对话"}

    try:
        runtime.abort("用户手动中止")
        logger.info(f"会话 {session_id} 已请求中止")
    except Exception as e:
        logger.warning(f"中止会话 {session_id} 失败: {e}")
        return {"status": "error", "message": str(e)}

    # Phase 19: 取消该会话的所有待审批请求
    try:
        from agent.approval import cancel_pending_approvals_for_session
        cancelled = cancel_pending_approvals_for_session(session_id)
        if cancelled > 0:
            logger.info(f"已取消 {cancelled} 个待审批请求: {session_id}")
    except Exception as e:
        logger.warning(f"取消待审批请求失败 {session_id}: {e}")

    # P1-10: 取消该会话的所有待回答问题，避免孤儿问题请求
    try:
        from agent.tools.ask_question import cancel_pending_questions_for_session
        cancelled_questions = cancel_pending_questions_for_session(session_id)
        if cancelled_questions > 0:
            logger.info(f"已取消 {cancelled_questions} 个待回答问题: {session_id}")
    except Exception as e:
        logger.warning(f"取消待回答问题失败 {session_id}: {e}")

    # Phase 30.1: 中止时清空 turn_queue — 对标 Cline clearAborted
    # 避免中止后排队消息被 drain 自动消费
    try:
        controller = _get_turn_queue_controller()
        controller.clear_aborted(session_id)
    except Exception as e:
        logger.warning(f"清空 turn_queue 失败 {session_id}: {e}")

    # 清除 pending mode rebuild 请求，避免中止后触发 auto-continue
    try:
        from agent.tools.plan_mode import cancel_pending_mode_rebuild
        cancel_pending_mode_rebuild(session_id)
    except Exception as e:
        logger.warning(f"清除 pending mode rebuild 失败 {session_id}: {e}")

    return {"status": "ok", "message": "已发送中止信号"}


@router.post("/approve")
async def approve_tool(request: Request):
    """工具审批端点 — Phase 19 新增

    接收用户对工具调用的审批结果（批准/拒绝）。
    runtime 在 _prepare_tool_execution 中 await 等待审批结果，
    用户通过此端点设置结果后唤醒 runtime 继续执行。

    请求体:
        {
            "tool_call_id": "xxx",          // 工具调用 ID
            "approved": true/false,         // true=批准, false=拒绝
            "auto_approve": false           // Stage 5.6 新增：是否"始终允许此工具"
        }

    Stage 5.6 (U10) 增强:
        - 接收 auto_approve 字段，若为 True 且 approved=True，
          调用 mark_auto_approved 写入会话级记忆
        - 返回值增加 auto_approved_tools 字段（当前会话已自动批准的工具列表）

    Returns:
        {"status": "ok", "auto_approved_tools": [...]} 或 {"status": "error", "message": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    tool_call_id = body.get("tool_call_id", "")
    approved = body.get("approved", False)
    auto_approve = body.get("auto_approve", False)

    if not tool_call_id:
        return {"status": "error", "message": "tool_call_id 不能为空"}

    from agent.approval import (
        set_approval_result,
        get_pending_approval_meta,
        mark_auto_approved,
        list_auto_approved,
    )
    result = "approved" if approved else "denied"
    success = set_approval_result(tool_call_id, result)

    if not success:
        return {"status": "error", "message": "未找到待审批的工具调用"}

    # Stage 5.6 (U10): 用户勾选"始终允许"且批准时，写入会话级记忆
    # 注意：必须在 clear_approval 之前调用 get_pending_approval_meta，
    # 因为 clear_approval 会从 _pending_approvals 字典中移除 entry
    meta = get_pending_approval_meta(tool_call_id) or {}
    session_id = meta.get("session_id", "")
    tool_name = meta.get("tool_name", "")
    if auto_approve and approved and session_id and tool_name:
        mark_auto_approved(session_id, tool_name)

    # 返回当前会话已自动批准的工具列表（供前端展示）
    auto_approved_tools = list_auto_approved(session_id) if session_id else []

    logger.info(
        f"工具审批结果: tool_call_id={tool_call_id}, result={result}, "
        f"auto_approve={auto_approve}, auto_approved_tools={auto_approved_tools}"
    )
    return {
        "status": "ok",
        "message": f"已{'批准' if approved else '拒绝'}工具调用",
        "auto_approved_tools": auto_approved_tools,
    }


@router.post("/answer_question")
async def answer_question(request: Request):
    """回答 ask_question 工具的问题 — P1-10 新增

    接收用户对 ask_question 工具调用问题的回答。
    ask_question 工具在 execute 中 await asyncio.Event 挂起等待，
    用户通过此端点提交回答后唤醒工具继续执行。

    请求体:
        {
            "tool_call_id": "xxx",   // 工具调用 ID（必填，用于关联回答）
            "answer": "用户回答文本"  // 用户的回答（必填）
        }

    Returns:
        {"status": "ok", "message": "..."} 或 {"status": "error", "message": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    tool_call_id = body.get("tool_call_id", "")
    answer = body.get("answer", "")

    if not tool_call_id:
        return {"status": "error", "message": "tool_call_id 不能为空"}

    from agent.tools.ask_question import set_question_answer, get_pending_question_meta

    meta = get_pending_question_meta(tool_call_id)
    if meta is None:
        return {"status": "error", "message": "未找到待回答的问题"}

    success = set_question_answer(tool_call_id, answer)
    if not success:
        return {"status": "error", "message": "设置回答失败"}

    logger.info(
        f"P1-10: ask_question 回答已接收: tool_call_id={tool_call_id}, "
        f"answer={answer[:80]}..."
    )
    return {
        "status": "ok",
        "message": "回答已提交",
        "question": meta.get("question", ""),
    }


# ============================================================================
# Stage 9.6 (U10): 持久化审批记忆管理 API — 对标 Cline globalState 管理
# 跨会话保留"始终允许此工具"的审批记忆，agent 重启后仍生效
# ============================================================================


@router.get("/mode")
async def get_session_mode(request: Request):
    """获取会话当前工作模式 — P0-2 新增

    查询参数:
        session_id: 会话 ID（必填）

    返回:
        {"status": "ok", "mode": "act" | "plan"}
    """
    session_id = request.query_params.get("session_id", "")
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}
    from agent.state import get_mode
    return {"status": "ok", "mode": get_mode(session_id)}


@router.post("/mode")
async def set_session_mode(request: Request):
    """设置会话工作模式 — P0-2 新增

    让前端切换 mode 后立即同步到后端 SessionState，
    而不是等到下次 /stream 请求才生效。

    请求体:
        {"session_id": "xxx", "mode": "act" | "plan"}

    返回:
        {"status": "ok", "mode": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体必须是 JSON"}
    session_id = body.get("session_id", "")
    mode = body.get("mode", "")
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}
    if mode not in ("act", "plan", "yolo"):
        return {"status": "error", "message": f"无效的 mode: {mode}，必须是 act、plan 或 yolo"}
    from agent.state import set_mode
    set_mode(session_id, mode)
    logger.info("会话 %s 模式已切换为 %s", session_id, mode)
    return {"status": "ok", "mode": mode}


# ============================================================================


@router.get("/approval_memory")
async def list_approval_memory(request: Request):
    """列出所有持久化自动批准的工具 — Stage 9.6 新增

    返回 agent_config/approval_memory.json 中持久化的工具列表，
    供前端"审批记忆管理"页面展示。

    Returns:
        {"status": "ok", "tools": [...], "count": N}
    """
    from agent.approval import list_persistent_auto_approved
    tools = list_persistent_auto_approved()
    return {
        "status": "ok",
        "tools": tools,
        "count": len(tools),
    }


@router.delete("/approval_memory")
async def clear_approval_memory(request: Request):
    """清空所有持久化自动批准记忆 — Stage 9.6 新增

    用户在管理页面点击"全部清空"时调用。
    清空后，所有工具调用都需重新审批。

    Returns:
        {"status": "ok", "cleared_count": N}
    """
    from agent.approval import clear_persistent_auto_approved
    count = clear_persistent_auto_approved()
    logger.info(f"Stage 9.6: 已清空 {count} 个持久化审批记忆")
    return {
        "status": "ok",
        "message": f"已清空 {count} 个持久化审批记忆",
        "cleared_count": count,
    }


@router.delete("/approval_memory/{tool_name}")
async def remove_approval_memory(tool_name: str):
    """删除单个工具的持久化自动批准记忆 — Stage 9.6 新增

    用户在管理页面单条删除时调用。

    Path Args:
        tool_name: 工具名

    Returns:
        {"status": "ok"} 或 {"status": "error", "message": "..."}
    """
    from agent.approval import remove_persistent_auto_approved
    if not tool_name:
        return {"status": "error", "message": "tool_name 不能为空"}
    success = remove_persistent_auto_approved(tool_name)
    if not success:
        return {
            "status": "error",
            "message": f"工具 {tool_name} 不在持久化审批记忆中",
        }
    logger.info(f"Stage 9.6: 已删除工具 {tool_name} 的持久化审批记忆")
    return {
        "status": "ok",
        "message": f"已删除工具 {tool_name} 的持久化审批记忆",
    }


# ============================================================================
# Phase 21: 检查点 API — 对标 Cline checkpoint / rollback
# ============================================================================


@router.get("/checkpoints")
async def list_checkpoints(request: Request):
    """列出会话的检查点 — Phase 21 新增

    查询参数:
        session_id: 会话 ID

    返回:
        检查点列表，按时间正序（最早的在前）
    """
    session_id = request.query_params.get("session_id", "")
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}

    from agent.checkpoint import get_checkpoint_manager
    manager = get_checkpoint_manager()
    # list_checkpoints 返回 checkpoint_id 字符串列表（按创建顺序）
    # 需通过 get_checkpoint 获取 Checkpoint 对象才能读取字段
    cp_ids = manager.list_checkpoints(session_id)

    checkpoints_payload = []
    for cp_id in cp_ids:
        cp = manager.get_checkpoint(cp_id)
        if cp is None:
            # 内存缓存未命中（可能未持久化加载），跳过并记录告警
            logger.warning("list_checkpoints: 检查点 %s 不在内存缓存中", cp_id)
            continue
        checkpoints_payload.append({
            "checkpoint_id": cp.checkpoint_id,
            "tool_call_id": cp.tool_call_id,
            "tool_name": cp.tool_name,
            "created_at": cp.created_at,
            "description": cp.description,
            "message_count": len(cp.messages),
        })

    return {
        "status": "ok",
        "checkpoints": checkpoints_payload,
    }


@router.get("/diff_checkpoint")
async def diff_checkpoint(request: Request):
    """查询指定检查点与前一个检查点之间的消息差异 — P2-23 新增

    对标 Cline checkpoint diff 对比视图。返回目标检查点与同 session
    紧邻的前一个检查点之间的消息新增/移除情况，便于前端展示 diff。

    查询参数:
        checkpoint_id: 目标检查点 ID

    返回:
        diff 字典，包含 added/removed 消息列表及统计信息；
        检查点不存在时返回 status=error
    """
    checkpoint_id = request.query_params.get("checkpoint_id", "")
    if not checkpoint_id:
        return {"status": "error", "message": "checkpoint_id 不能为空"}

    from agent.checkpoint import get_checkpoint_manager
    manager = get_checkpoint_manager()
    diff = manager.get_diff(checkpoint_id)
    if diff is None:
        return {"status": "error", "message": f"检查点 {checkpoint_id} 不存在"}

    return {"status": "ok", "diff": diff}


@router.post("/rollback")
async def rollback_to_checkpoint(request: Request):
    """回滚到检查点 — Phase 21 新增，Stage 6.5 增加文件联动

    请求体:
        {
            "session_id": "xxx",
            "checkpoint_id": "cp_xxxxxx"
        }

    回滚后:
        1. 从检查点恢复会话消息列表
        2. 清除该检查点之后的所有检查点
        3. 若 AGENT_ENABLE_FILE_CHECKPOINT 启用，联动回滚文件状态
        4. 前端重新加载会话消息
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    session_id = body.get("session_id", "")
    checkpoint_id = body.get("checkpoint_id", "")

    if not session_id or not checkpoint_id:
        return {"status": "error", "message": "session_id 和 checkpoint_id 不能为空"}

    from agent.checkpoint import get_checkpoint_manager
    from agent.session import _dict_to_message
    manager = get_checkpoint_manager()

    # Stage 9.5 (T5): 先查询 checkpoint，用于文件回滚的预检
    # 对标 Cline checkpoint-restore.ts 的"消息+文件"原子性恢复
    # 文件回滚失败时不应触动消息，因此先尝试文件回滚，成功后再回滚消息
    cp_preview = manager.get_checkpoint(checkpoint_id)
    if cp_preview is None or cp_preview.session_id != session_id:
        return {"status": "error", "message": "检查点不存在或会话不匹配"}

    # Stage 9.5 (T5): 文件回滚预检 — 在消息回滚之前执行
    # 仅当 AGENT_ENABLE_FILE_CHECKPOINT 启用时触发
    # 用消息检查点的 tool_call_id 查找对应的文件 checkpoint
    # 文件回滚失败时直接返回错误，不触动消息和后续 checkpoints（原子性保证）
    file_rollback_result = None
    file_checkpoint_enabled = os.environ.get(
        "AGENT_ENABLE_FILE_CHECKPOINT", ""
    ).lower() in ("1", "true", "yes")
    if file_checkpoint_enabled:
        try:
            file_rollback_result = _try_rollback_file_for_message_checkpoint(
                session_id, cp_preview.tool_call_id,
            )
        except Exception as e:
            logger.error(f"Stage 9.5: 联动文件回滚失败，中止消息回滚: {e}")
            return {
                "status": "error",
                "message": (
                    f"联动文件回滚失败，消息未回滚（保证原子性）: {e}"
                ),
            }
        # 文件回滚执行但返回 rolled_back=False 时，也视为失败
        if (
            file_rollback_result is not None
            and not file_rollback_result.get("rolled_back", False)
        ):
            logger.error(
                f"Stage 9.5: 文件回滚返回失败结果，中止消息回滚: {file_rollback_result}"
            )
            return {
                "status": "error",
                "message": (
                    "联动文件回滚失败（git 操作失败），消息未回滚（保证原子性）"
                ),
                "file_rollback": file_rollback_result,
            }

    # 执行消息回滚（删除该检查点之后的所有检查点）
    cp = manager.rollback_to_checkpoint(session_id, checkpoint_id)
    if cp is None:
        return {"status": "error", "message": "检查点不存在或会话不匹配"}

    # 恢复会话消息列表
    try:
        restored_messages = [_dict_to_message(m) for m in cp.messages]
        _session_manager.update(session_id, restored_messages)
        logger.info(
            f"Phase 21: 会话 {session_id} 已回滚到检查点 {checkpoint_id} "
            f"(恢复 {len(restored_messages)} 条消息)"
        )
    except Exception as e:
        logger.error(f"Phase 21: 恢复会话消息失败: {e}", exc_info=True)
        return {"status": "error", "message": f"恢复会话消息失败: {e}"}

    # 停止该会话正在运行的 runtime，避免回滚后 runtime 继续基于旧状态运行
    runtime = _active_runtimes.pop(session_id, None)
    if runtime is not None:
        try:
            runtime.abort("rollback to checkpoint")
            logger.info(f"Phase 21: 已中止会话 {session_id} 的活跃 runtime")
        except Exception as e:
            logger.warning(f"Phase 21: 中止 runtime 时出错: {e}")

    # 清理该会话的上下文压缩状态，避免摘要与回滚后的历史不一致
    try:
        CompactionStateManager().clear(session_id)
        logger.info(f"Phase 21: 已清理会话 {session_id} 的压缩状态")
    except Exception as e:
        logger.warning(f"Phase 21: 清理压缩状态失败: {e}")

    return {
        "status": "ok",
        "message": f"已回滚到检查点（工具 {cp.tool_name} 执行前）",
        "checkpoint": {
            "checkpoint_id": cp.checkpoint_id,
            "tool_name": cp.tool_name,
            "created_at": cp.created_at,
            "description": cp.description,
            "message_count": len(cp.messages),
        },
        "file_rollback": file_rollback_result,
    }


@router.post("/rollback_message")
async def rollback_to_user_message(request: Request):
    """消息级回滚 — 回滚到某条用户提问之前 — 自研增强

    与现有 /rollback（按工具检查点回滚）不同，本接口按"用户消息"定位：
    删除指定用户消息及其之后的所有内容（AI 回答、工具调用、工具结果等），
    使对话上下文恢复到该提问之前的状态，便于重新生成。

    对标 Cline：Cline 原生无消息级回滚，此为自研增强，仅回滚对话上下文；
    不还原文件（工具执行产生的文件状态保持当前值），符合用户需求。

    请求体:
        {
            "session_id": "xxx",
            "user_index": 2   # 第 user_index 条用户消息（0 起），
                              # 删除该条及之后所有内容
        }
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    session_id = body.get("session_id", "")
    user_index = body.get("user_index")
    user_text = body.get("text", "")

    if not session_id or user_index is None or user_index < 0:
        return {"status": "error", "message": "session_id 和 user_index 不能为空"}

    import re

    from agent.providers.base import _extract_text

    def _unwrap_user_input(text: str) -> str:
        """去掉 <user_input mode="..."> 包装，还原原始用户提问文本"""
        m = re.search(r"<user_input[^>]*>(.*?)</user_input>", text, re.S)
        raw = m.group(1) if m else text
        return raw.strip()

    messages = _session_manager.get_messages(session_id)

    # ---- 定位要回滚的提问位置(截断到该提问之前) ----
    # 前端 localStorage 是完整对话视图；后端 session 是 LLM 上下文，
    # 可能因模式切换 rebuild/上下文压缩被截断，导致前后端提问数量不一致。
    # 因此不能仅依赖 user_index(索引)，优先用"提问文本"在后端消息中匹配，
    # 匹配不到再回退到"相邻去重"的 user_index 定位。
    truncate_at: int | None = None

    # 1) 文本匹配优先: 从前往后找第一个与前端提问文本一致的用户消息，
    #    截断到它之前（删除该提问第一次出现及其后所有内容，含 runtime 重复）
    if user_text:
        expected = user_text.strip()
        for i, m in enumerate(messages):
            if m.role != MessageRole.USER:
                continue
            if _unwrap_user_input(_extract_text(m)) == expected:
                truncate_at = i
                break

    # 2) 回退: 相邻去重的 user_index 定位
    if truncate_at is None:
        dedup_positions: list[int] = []
        last_user_text: str | None = None
        for i, m in enumerate(messages):
            if m.role != MessageRole.USER:
                continue
            text = _extract_text(m)
            if text and text == last_user_text:
                continue  # runtime 历史注入+input 生成导致重复，跳过
            last_user_text = text
            dedup_positions.append(i)
        if 0 <= user_index < len(dedup_positions):
            truncate_at = dedup_positions[user_index]

    if truncate_at is None:
        return {
            "status": "error",
            "message": "该提问已不在当前会话的 LLM 上下文中（可能已被模式切换重建或上下文压缩清理），无法精确回滚到它之前",
        }

    truncated = messages[:truncate_at]

    # ---- 安全收拢结尾 ----
    # 截断后保留的上下文必须是完整、合法结尾，否则 LLM 调用会因
    # "孤立 tool 消息"或"assistant 带未响应 tool_calls"而报 400。
    # 从末尾向前丢弃不完整的尾部（孤立 tool 消息、带未响应 tool_calls 的
    # assistant），直到停留在 user 或已完整响应的 assistant 上。
    from agent.types import ToolCallPart, ToolResultPart

    def _has_unanswered_tool_calls(msgs: list[AgentMessage], end: int) -> bool:
        """检查 msgs[:end] 的最后一条 assistant 是否带未响应的 tool_calls"""
        if end == 0:
            return False
        last = msgs[end - 1]
        if last.role != MessageRole.ASSISTANT:
            return False
        answered_ids = {
            part.tool_call_id
            for msg in msgs[:end]
            if msg.role == MessageRole.TOOL
            for part in msg.content
            if isinstance(part, ToolResultPart)
        }
        return any(
            isinstance(p, ToolCallPart) and p.tool_call_id not in answered_ids
            for p in last.content
        )

    end = len(truncated)
    while end > 0:
        last = truncated[end - 1]
        if last.role == MessageRole.USER:
            break
        if last.role == MessageRole.TOOL:
            # 孤立 tool 消息（其 assistant 响应可能已被截断）-> 向前删
            end -= 1
            continue
        if last.role == MessageRole.ASSISTANT:
            if _has_unanswered_tool_calls(truncated, end):
                # assistant 带未响应的 tool_calls -> 不完整，向前删
                end -= 1
                continue
            # 完整 assistant -> 作为合法结尾
            break
    truncated = truncated[:end]

    _session_manager.update(session_id, truncated)
    logger.info(
        f"消息级回滚: 会话 {session_id} 回滚到第 {user_index} 条用户提问前 "
        f"(剩余 {len(truncated)} 条消息)"
    )

    # 停止该会话正在运行的 runtime，避免回滚后继续基于旧状态运行
    runtime = _active_runtimes.pop(session_id, None)
    if runtime is not None:
        try:
            runtime.abort("rollback to user message")
            logger.info(f"消息级回滚: 已中止会话 {session_id} 的活跃 runtime")
        except Exception as e:
            logger.warning(f"消息级回滚: 中止 runtime 时出错: {e}")

    # 清理被回滚掉的消息对应的消息检查点（仅删除被删部分触发过的检查点，
    # 保留之前建立的，避免误删仍有效的检查点快照）
    try:
        from agent.checkpoint import get_checkpoint_manager
        from agent.types import ToolCallPart
        removed_tool_call_ids = {
            part.tool_call_id
            for m in messages[truncate_at:]
            for part in m.content
            if isinstance(part, ToolCallPart)
        }
        if removed_tool_call_ids:
            get_checkpoint_manager().delete_by_tool_call_ids(
                session_id, removed_tool_call_ids
            )
    except Exception as e:
        logger.warning(f"消息级回滚: 清理消息检查点失败: {e}")

    return {
        "status": "ok",
        "remaining": len(truncated),
        "message": "已回滚到该提问之前的状态",
    }


def _try_rollback_file_for_message_checkpoint(
    session_id: str,
    tool_call_id: str,
) -> dict | None:
    """联动文件回滚 — 根据 tool_call_id 查找文件 checkpoint 并回滚

    Stage 6.5 新增，对标 Cline applyCheckpointToWorktree 的"消息+文件"组合恢复。
    消息检查点和文件检查点都按 tool_call_id 索引，可关联查找。

    Args:
        session_id: 会话 ID
        tool_call_id: 触发检查点的工具调用 ID

    Returns:
        回滚结果 dict，None 表示无对应文件 checkpoint
    """
    from agent.file_checkpoint import get_checkpoint_manager as get_file_checkpoint_manager
    file_manager = get_file_checkpoint_manager()
    # 列出该 session 所有文件 checkpoint，找 tool_call_id 匹配的
    refs = file_manager.list_checkpoints(session_id)
    target_ref = None
    for ref in refs:
        if ref.tool_call_id == tool_call_id:
            target_ref = ref
            break
    if target_ref is None:
        return None
    ok = file_manager.restore_checkpoint(target_ref.checkpoint_id)
    return {
        "rolled_back": ok,
        "checkpoint_id": target_ref.checkpoint_id,
        "file_count": len(target_ref.file_paths),
    }


@router.post("/rollback_messages_only")
async def rollback_messages_only(request: Request):
    """仅回滚消息历史，不回滚文件变更 — 对标 Cline ClineCheckpointRestore = "task" 模式

    请求体:
        {
            "session_id": "xxx",
            "checkpoint_id": "cp_xxxxxx"
        }

    与 /rollback（完整回滚）的区别:
        1. 不触发文件回滚（git stash/restore），工作区文件变更保留
        2. 不删除 checkpoint（包括目标之后的），同一 checkpoint 可再次回滚
        3. 仅恢复会话消息历史到检查点快照

    回滚后:
        1. 从检查点恢复会话消息列表（不删除任何检查点）
        2. 停止该会话正在运行的 runtime
        3. 清理上下文压缩状态
        4. 前端重新加载会话消息
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    session_id = body.get("session_id", "")
    checkpoint_id = body.get("checkpoint_id", "")

    if not session_id or not checkpoint_id:
        return {"status": "error", "message": "session_id 和 checkpoint_id 不能为空"}

    from agent.checkpoint import get_checkpoint_manager
    from agent.session import _dict_to_message
    manager = get_checkpoint_manager()

    # 预检：检查 checkpoint 存在且会话匹配
    cp_preview = manager.get_checkpoint(checkpoint_id)
    if cp_preview is None or cp_preview.session_id != session_id:
        return {"status": "error", "message": "检查点不存在或会话不匹配"}

    # 仅消息回滚（不删除任何检查点，不触发文件回滚）
    messages_data = manager.restore_messages_only(checkpoint_id)
    if messages_data is None:
        return {"status": "error", "message": "检查点不存在"}

    # 恢复会话消息列表
    try:
        restored_messages = [_dict_to_message(m) for m in messages_data]
        _session_manager.update(session_id, restored_messages)
        logger.info(
            f"仅消息回滚: 会话 {session_id} 已回滚到检查点 {checkpoint_id} "
            f"(恢复 {len(restored_messages)} 条消息，文件状态和检查点保留)"
        )
    except Exception as e:
        logger.error(f"仅消息回滚: 恢复会话消息失败: {e}", exc_info=True)
        return {"status": "error", "message": f"恢复会话消息失败: {e}"}

    # 停止该会话正在运行的 runtime，避免回滚后 runtime 继续基于旧状态运行
    runtime = _active_runtimes.pop(session_id, None)
    if runtime is not None:
        try:
            runtime.abort("rollback messages only")
            logger.info(f"仅消息回滚: 已中止会话 {session_id} 的活跃 runtime")
        except Exception as e:
            logger.warning(f"仅消息回滚: 中止 runtime 时出错: {e}")

    # 清理该会话的上下文压缩状态，避免摘要与回滚后的历史不一致
    try:
        CompactionStateManager().clear(session_id)
        logger.info(f"仅消息回滚: 已清理会话 {session_id} 的压缩状态")
    except Exception as e:
        logger.warning(f"仅消息回滚: 清理压缩状态失败: {e}")

    return {
        "status": "ok",
        "message": f"已仅回滚消息（工具 {cp_preview.tool_name} 执行前），文件状态未变更",
        "checkpoint": {
            "checkpoint_id": cp_preview.checkpoint_id,
            "tool_name": cp_preview.tool_name,
            "created_at": cp_preview.created_at,
            "description": cp_preview.description,
            "message_count": len(cp_preview.messages),
        },
    }


@router.delete("/checkpoints")
async def clear_checkpoints(request: Request):
    """清除会话的所有检查点 — Phase 21 新增

    查询参数:
        session_id: 会话 ID
    """
    session_id = request.query_params.get("session_id", "")
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}

    from agent.checkpoint import get_checkpoint_manager
    manager = get_checkpoint_manager()
    count = manager.clear_checkpoints(session_id)

    return {"status": "ok", "message": f"已清除 {count} 个检查点"}


# ============================================================================
# Phase 33.2: 文件状态快照 checkpoint API — 对标 Cline shadow-git checkpoint
# 与 Phase 21 的会话消息检查点互补：本端点回滚工作区文件状态
# ============================================================================


@router.get("/file_checkpoints")
async def list_file_checkpoints(request: Request):
    """列出会话的文件状态快照 — Phase 33.2 新增

    查询参数:
        session_id: 会话 ID

    返回:
        文件 checkpoint 列表，按创建时间正序
    """
    session_id = request.query_params.get("session_id", "")
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}

    from agent.file_checkpoint import get_checkpoint_manager
    manager = get_checkpoint_manager()
    refs = manager.list_checkpoints(session_id)

    return {
        "status": "ok",
        "checkpoints": [
            {
                "checkpoint_id": ref.checkpoint_id,
                "tool_call_id": ref.tool_call_id,
                "tool_name": ref.tool_name,
                "stash_commit": ref.stash_commit[:8] if ref.stash_commit else "",
                "file_paths": ref.file_paths,
                "created_at": ref.created_at,
                "description": ref.description,
            }
            for ref in refs
        ],
    }


@router.get("/settings/file_checkpoint")
async def get_file_checkpoint_setting(request: Request):
    """获取文件检查点功能开关状态 — 集中存储于 settings.yaml

    返回当前开关状态、来源（环境变量 / 配置文件）以及是否需要重启生效。
    """
    from agent.settings_store import is_feature_enabled

    env_override = os.environ.get(
        "AGENT_ENABLE_FILE_CHECKPOINT", ""
    ).lower() in ("1", "true", "yes")
    enabled = env_override or is_feature_enabled("file_checkpoint")
    return {
        "status": "ok",
        "enabled": enabled,
        "source": "env" if env_override else "config",
        "requires_restart": True,
    }


@router.put("/settings/file_checkpoint")
async def set_file_checkpoint_setting(request: Request):
    """设置文件检查点功能开关，持久化到 agent_config/settings.yaml

    请求体:
        {
            "enabled": true/false
        }

    注意: 本钩子在服务启动时注册，运行期切换开关需重启服务才生效。
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    enabled = bool(body.get("enabled", False))
    from agent.settings_store import get_settings_store

    get_settings_store().set_feature("file_checkpoint", enabled)
    return {
        "status": "ok",
        "enabled": enabled,
        "requires_restart": True,
        "message": "文件检查点配置已保存，需重启服务后生效",
    }


@router.post("/rollback_file")
async def rollback_file_checkpoint(request: Request):
    """回滚文件状态到指定 checkpoint — Phase 33.2 新增

    请求体:
        {
            "session_id": "xxx",
            "checkpoint_id": "ckpt_xxx"
        }

    回滚行为:
        1. git checkout <stash_commit> -- <file_paths> 还原指定文件
        2. file_paths 为空时还原整个工作区
        3. 不影响会话消息历史（仅还原文件内容）

    注意:
        仅在 git 仓库内有效；非 git 仓库的 checkpoint 不会创建，回滚也无操作
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    session_id = body.get("session_id", "")
    checkpoint_id = body.get("checkpoint_id", "")

    if not session_id or not checkpoint_id:
        return {"status": "error", "message": "session_id 和 checkpoint_id 不能为空"}

    from agent.file_checkpoint import get_checkpoint_manager
    manager = get_checkpoint_manager()

    ref = manager.get_checkpoint(checkpoint_id)
    if ref is None or ref.session_id != session_id:
        return {"status": "error", "message": "checkpoint 不存在或会话不匹配"}

    ok = manager.restore_checkpoint(checkpoint_id)
    if not ok:
        return {"status": "error", "message": "回滚失败（git checkout 异常）"}

    logger.info(
        f"Phase 33.2: 会话 {session_id} 已回滚文件状态到 checkpoint {checkpoint_id} "
        f"(还原 {len(ref.file_paths)} 个文件)"
    )

    return {
        "status": "ok",
        "message": f"已回滚文件状态（{ref.tool_name} 执行前）",
        "checkpoint": {
            "checkpoint_id": ref.checkpoint_id,
            "tool_name": ref.tool_name,
            "stash_commit": ref.stash_commit[:8] if ref.stash_commit else "",
            "file_paths": ref.file_paths,
            "description": ref.description,
        },
    }


# ============================================================================
# Phase 22: MCP 服务器管理 API — 对标 Cline mcp 服务管理
# ============================================================================


@router.get("/mcp/servers")
async def list_mcp_servers(request: Request):
    """列出已配置的 MCP 服务器及其工具 — Phase 22 新增

    查询参数:
        refresh: 是否强制刷新工具列表缓存（"true" 刷新）

    返回:
        servers: 服务器列表，每项含 name/transport/description/enabled/tools

    用途:
        - 前端展示可用 MCP 服务器
        - 调试 MCP 连接问题
        - agent 不直接调用此端点，通过 use_mcp_tool 工具调用
    """
    refresh = request.query_params.get("refresh", "").lower() == "true"

    from agent.mcp.registry import get_registry
    registry = get_registry()

    servers = registry.list_servers()
    result_servers = []

    for srv in servers:
        # 尝试加载工具列表（首次会建立连接）
        tools = await registry.list_tools(srv.name, refresh=refresh)
        result_servers.append({
            "name": srv.name,
            "transport": srv.transport,
            "description": srv.description,
            "enabled": srv.enabled,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ],
            "tools_count": len(tools),
        })

    return {
        "status": "ok",
        "servers": result_servers,
        "total_servers": len(result_servers),
        "total_tools": sum(len(s["tools"]) for s in result_servers),
    }


@router.get("/mcp/resources")
async def list_mcp_resources(request: Request):
    """列出 MCP 服务器的资源 — Phase 22 新增

    查询参数:
        server_name: 服务器名称（可选，不传则列出所有服务器的资源）
        refresh: 是否强制刷新缓存

    返回:
        resources: 资源列表
    """
    server_name = request.query_params.get("server_name", "")
    refresh = request.query_params.get("refresh", "").lower() == "true"

    from agent.mcp.registry import get_registry
    registry = get_registry()

    all_resources = []
    if server_name:
        resources = await registry.list_resources(server_name, refresh=refresh)
        all_resources.extend(resources)
    else:
        for srv in registry.list_servers():
            resources = await registry.list_resources(srv.name, refresh=refresh)
            all_resources.extend(resources)

    return {
        "status": "ok",
        "resources": [
            {
                "server_name": r.server_name,
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mime_type": r.mime_type,
            }
            for r in all_resources
        ],
        "total": len(all_resources),
    }


@router.post("/mcp/reload")
async def reload_mcp_config(request: Request):
    """重新加载 MCP 配置 — Phase 22 新增

    修改 agent_config/mcp_servers.yaml 后调用此端点热加载，
    无需重启后端服务。

    注意: 已建立的 MCP 客户端连接会被关闭，下次调用时重新建立。
    """
    from agent.mcp.registry import get_registry
    registry = get_registry()

    # 关闭所有现有连接
    await registry.close_all()

    # 重新加载配置
    count = registry.load_config()

    return {
        "status": "ok",
        "message": f"已重新加载 MCP 配置，{count} 个服务器已启用",
        "enabled_servers": count,
    }


# ----------------------------------------------------------------------------
# MCP 服务器 CRUD 辅助函数 — 读写 mcp_servers.yaml
# ----------------------------------------------------------------------------


def _read_mcp_servers_yaml() -> dict:
    """读取 MCP 配置 YAML 文件，返回完整配置字典

    返回结构: {"servers": [...], "tool_policies": [...]}
    若文件不存在或为空，返回带空列表的默认结构。
    """
    from agent.mcp.registry import get_registry
    registry = get_registry()
    config_path = registry.config_path

    try:
        import yaml
    except ImportError:
        raise RuntimeError("未安装 PyYAML，无法读写 MCP 配置")

    if not config_path.exists():
        return {"servers": [], "tool_policies": []}

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        return {"servers": [], "tool_policies": []}

    # 规范化结构，确保 servers / tool_policies 为列表
    if not isinstance(data.get("servers"), list):
        data["servers"] = []
    if not isinstance(data.get("tool_policies"), list):
        data["tool_policies"] = []
    return data


def _write_mcp_servers_yaml(data: dict) -> None:
    """将配置字典写回 MCP 配置 YAML 文件"""
    from agent.mcp.registry import get_registry
    registry = get_registry()
    config_path = registry.config_path

    try:
        import yaml
    except ImportError:
        raise RuntimeError("未安装 PyYAML，无法读写 MCP 配置")

    # 确保目录存在
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def _build_mcp_server_entry(body: dict, name: str | None = None) -> dict:
    """根据请求体构建单个服务器配置字典

    Args:
        body: 请求体（含 transport/command/args/env 等字段）
        name: 服务器名称（编辑时由路径参数提供，添加时从 body 取）
    """
    srv_name = name if name else (body.get("name") or "").strip()
    transport = (body.get("transport") or "stdio").strip().lower()
    if transport not in ("stdio", "http"):
        transport = "stdio"

    entry: dict[str, Any] = {
        "name": srv_name,
        "transport": transport,
        "enabled": bool(body.get("enabled", True)),
        "description": (body.get("description") or "").strip(),
    }

    if transport == "stdio":
        command = (body.get("command") or "").strip()
        if command:
            entry["command"] = command
        # args: 字符串列表
        args = body.get("args")
        if isinstance(args, list):
            entry["args"] = [str(a) for a in args]
        # env: 键值对字典，保留 ${ENV_VAR} 语法
        env = body.get("env")
        if isinstance(env, dict) and env:
            entry["env"] = {str(k): str(v) for k, v in env.items()}
    elif transport == "http":
        url = (body.get("url") or "").strip()
        if url:
            entry["url"] = url
        headers = body.get("headers")
        if isinstance(headers, dict) and headers:
            entry["headers"] = {str(k): str(v) for k, v in headers.items()}

    # auto_approve: 工具名列表
    auto_approve = body.get("auto_approve")
    if isinstance(auto_approve, list) and auto_approve:
        entry["auto_approve"] = [str(a) for a in auto_approve]

    return entry


async def _reload_mcp_and_list(registry) -> list[dict]:
    """重载 MCP 配置并返回服务器列表（含工具）

    供 CRUD 端点统一返回最新列表，避免前端二次请求。
    """
    await registry.close_all()
    registry.load_config()

    result_servers: list[dict] = []
    for srv in registry.list_servers():
        tools = await registry.list_tools(srv.name)
        result_servers.append({
            "name": srv.name,
            "transport": srv.transport,
            "description": srv.description,
            "enabled": srv.enabled,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ],
            "tools_count": len(tools),
        })
    return result_servers


@router.get("/mcp/servers/raw")
async def get_mcp_server_raw(request: Request):
    """获取单个 MCP 服务器的原始配置 — 前端编辑表单回填用

    查询参数:
        name: 服务器名称

    返回:
        status: ok | error
        server: 原始配置字典（含 command/args/env/url/headers/auto_approve）
    """
    name = request.query_params.get("name", "").strip()
    if not name:
        return {"status": "error", "message": "name 参数不能为空"}

    try:
        data = _read_mcp_servers_yaml()
    except Exception as e:
        logger.error(f"读取 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"读取配置失败: {e}"}

    for srv in data["servers"]:
        if isinstance(srv, dict) and srv.get("name", "").strip() == name:
            return {"status": "ok", "server": srv}

    return {"status": "error", "message": f"服务器 '{name}' 不存在"}


@router.post("/mcp/servers")
async def add_mcp_server(request: Request):
    """添加新的 MCP 服务器 — 前端 CRUD 管理

    请求体 (JSON):
        name: 服务器唯一标识（必填）
        transport: stdio | http（必填）
        enabled: 是否启用（可选，默认 true）
        description: 描述（可选）
        command: stdio 启动命令
        args: 参数列表
        env: 环境变量字典（${ENV_VAR} 语法保留）
        url: http 服务器地址
        headers: http 请求头
        auto_approve: 自动批准的工具名列表

    返回:
        status: ok | error
        servers: 添加后的完整服务器列表
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    name = (body.get("name") or "").strip()
    if not name:
        return {"status": "error", "message": "服务器名称 name 不能为空"}
    if not (body.get("transport") or "").strip():
        return {"status": "error", "message": "传输方式 transport 不能为空"}

    try:
        data = _read_mcp_servers_yaml()
    except Exception as e:
        logger.error(f"读取 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"读取配置失败: {e}"}

    # 检查名称是否已存在
    servers = data["servers"]
    for srv in servers:
        if isinstance(srv, dict) and srv.get("name", "").strip() == name:
            return {"status": "error", "message": f"服务器 '{name}' 已存在"}

    # 构建新条目并追加
    entry = _build_mcp_server_entry(body)
    servers.append(entry)

    try:
        _write_mcp_servers_yaml(data)
    except Exception as e:
        logger.error(f"写入 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"写入配置失败: {e}"}

    # 重载并返回最新列表
    from agent.mcp.registry import get_registry
    registry = get_registry()
    try:
        result_servers = await _reload_mcp_and_list(registry)
    except Exception as e:
        logger.error(f"重载 MCP 配置失败: {e}", exc_info=True)
        return {"status": "ok", "message": f"已添加但重载失败: {e}", "servers": []}

    return {
        "status": "ok",
        "message": f"已添加 MCP 服务器: {name}",
        "servers": result_servers,
    }


@router.put("/mcp/servers/{name}")
async def update_mcp_server(name: str, request: Request):
    """编辑已有的 MCP 服务器 — 前端 CRUD 管理

    路径参数:
        name: 服务器名称（原名称）

    请求体 (JSON): 同添加接口（不含 name，name 由路径参数决定）

    返回:
        status: ok | error
        servers: 更新后的完整服务器列表
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        data = _read_mcp_servers_yaml()
    except Exception as e:
        logger.error(f"读取 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"读取配置失败: {e}"}

    servers = data["servers"]
    target_idx = None
    for i, srv in enumerate(servers):
        if isinstance(srv, dict) and srv.get("name", "").strip() == name:
            target_idx = i
            break

    if target_idx is None:
        return {"status": "error", "message": f"服务器 '{name}' 不存在"}

    # 构建更新后的条目（保留原 name）
    entry = _build_mcp_server_entry(body, name=name)
    servers[target_idx] = entry

    try:
        _write_mcp_servers_yaml(data)
    except Exception as e:
        logger.error(f"写入 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"写入配置失败: {e}"}

    from agent.mcp.registry import get_registry
    registry = get_registry()
    try:
        result_servers = await _reload_mcp_and_list(registry)
    except Exception as e:
        logger.error(f"重载 MCP 配置失败: {e}", exc_info=True)
        return {"status": "ok", "message": f"已更新但重载失败: {e}", "servers": []}

    return {
        "status": "ok",
        "message": f"已更新 MCP 服务器: {name}",
        "servers": result_servers,
    }


@router.delete("/mcp/servers/{name}")
async def delete_mcp_server(name: str):
    """删除 MCP 服务器 — 前端 CRUD 管理

    路径参数:
        name: 服务器名称

    返回:
        status: ok | error
        servers: 删除后的完整服务器列表
    """
    try:
        data = _read_mcp_servers_yaml()
    except Exception as e:
        logger.error(f"读取 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"读取配置失败: {e}"}

    servers = data["servers"]
    new_servers = [
        srv for srv in servers
        if not (isinstance(srv, dict) and srv.get("name", "").strip() == name)
    ]

    if len(new_servers) == len(servers):
        return {"status": "error", "message": f"服务器 '{name}' 不存在"}

    data["servers"] = new_servers

    try:
        _write_mcp_servers_yaml(data)
    except Exception as e:
        logger.error(f"写入 MCP 配置失败: {e}", exc_info=True)
        return {"status": "error", "message": f"写入配置失败: {e}"}

    from agent.mcp.registry import get_registry
    registry = get_registry()
    try:
        result_servers = await _reload_mcp_and_list(registry)
    except Exception as e:
        logger.error(f"重载 MCP 配置失败: {e}", exc_info=True)
        return {"status": "ok", "message": f"已删除但重载失败: {e}", "servers": []}

    return {
        "status": "ok",
        "message": f"已删除 MCP 服务器: {name}",
        "servers": result_servers,
    }


# ============================================================================
# Stage 13.2 (R10): Provider 配置持久化 API — 对标 Cline provider-settings
# ============================================================================


@router.get("/providers")
async def list_providers():
    """列出所有 Provider 配置 — Stage 13.2 新增

    返回:
        providers: 已配置的 provider 列表（api_key 脱敏），每项含 alias / provider_id
        builtin: 内置 provider 标识列表（用于前端展示可选项）
        active_provider: 当前实际生效的 provider 完整信息
    """
    from agent.provider_settings import get_provider_settings_store, mask_api_key
    from agent.providers.factory import BUILTIN_PROVIDER_DEFAULTS

    store = get_provider_settings_store()
    configs = store.list_providers()

    # 收集已配置 provider，附带 api_key 脱敏（优先 providers.yaml，其次环境变量）
    providers_list = []
    for cfg in configs:
        defaults = BUILTIN_PROVIDER_DEFAULTS.get(cfg.provider_id)
        env_key = defaults.env_key if defaults else ""
        api_key = cfg.api_key if cfg.api_key else (os.environ.get(env_key, "") if env_key else "")
        item = cfg.to_dict()
        item["api_key_masked"] = mask_api_key(api_key)
        item["api_key_source"] = "configured" if cfg.api_key else ("env" if env_key and os.environ.get(env_key) else "none")
        item["env_key"] = env_key
        providers_list.append(item)

    # 构建当前实际生效的 provider 信息
    active_provider_id = os.environ.get("AGENT_PROVIDER_ID", "qwen")
    active_defaults = BUILTIN_PROVIDER_DEFAULTS.get(active_provider_id)
    # 从已配置中找第一个匹配 active_provider_id 的配置作为代表
    active_override = None
    for cfg in configs:
        if cfg.provider_id == active_provider_id:
            active_override = cfg
            break

    if active_defaults is not None:
        if active_override is not None:
            source = "configured"
        elif "AGENT_PROVIDER_ID" in os.environ:
            source = "env_override"
        else:
            source = "env_default"

        env_key = active_defaults.env_key
        active_api_key = (
            active_override.api_key
            if active_override and active_override.api_key
            else os.environ.get(env_key, "")
        )
        active_provider = {
            "alias": active_override.alias if active_override else active_provider_id,
            "provider_id": active_provider_id,
            "model_id": (active_override.model_id or active_defaults.default_model_id) if active_override else active_defaults.default_model_id,
            "base_url": (active_override.base_url or active_defaults.base_url) if active_override else active_defaults.base_url,
            "temperature": active_override.temperature if active_override else 0.1,
            "max_tokens": active_override.max_tokens if active_override else 8192,
            "env_key": env_key,
            "api_key_masked": mask_api_key(active_api_key),
            "api_key_source": "configured" if (active_override and active_override.api_key) else ("env" if env_key and os.environ.get(env_key) else "none"),
            "source": source,
        }
    else:
        # 未知 provider 时的兜底：仅保留标识，避免前端空白
        active_provider = {
            "alias": active_provider_id,
            "provider_id": active_provider_id,
            "model_id": "",
            "base_url": "",
            "temperature": 0.1,
            "max_tokens": 8192,
            "env_key": "",
            "api_key_masked": "",
            "source": "env_override" if "AGENT_PROVIDER_ID" in os.environ else "env_default",
        }

    return {
        "status": "ok",
        "providers": providers_list,
        "builtin": list(BUILTIN_PROVIDER_DEFAULTS.keys()),
        "active_provider": active_provider,
    }


@router.get("/providers/{alias}")
async def get_provider(alias: str):
    """获取单个 Provider 配置 — Stage 13.2 新增

    Path Args:
        alias: 配置别名（providers.yaml 的 key）

    返回:
        provider 配置（api_key 脱敏）
    """
    from agent.provider_settings import get_provider_settings_store, mask_api_key
    from agent.providers.factory import BUILTIN_PROVIDER_DEFAULTS

    store = get_provider_settings_store()
    cfg = store.get_provider(alias)
    if cfg is None:
        return {
            "status": "error",
            "message": f"provider {alias} 未配置",
        }

    defaults = BUILTIN_PROVIDER_DEFAULTS.get(cfg.provider_id)
    env_key = defaults.env_key if defaults else ""
    api_key = cfg.api_key if cfg.api_key else (os.environ.get(env_key, "") if env_key else "")

    item = cfg.to_dict()
    item["api_key_masked"] = mask_api_key(api_key)
    item["api_key_source"] = "configured" if cfg.api_key else ("env" if env_key and os.environ.get(env_key) else "none")
    item["env_key"] = env_key
    return {"status": "ok", "provider": item}


@router.put("/providers/{alias}")
async def update_provider(alias: str, request: Request):
    """更新 Provider 配置 — Stage 13.2 新增

    请求体（允许以下字段）:
        {
            "provider_id": "qwen",       // 新建时必须指定；更新时可修改实际 Provider 类型
            "model_id": "qwen-plus",
            "base_url": "https://...",
            "api_key": "sk-...",
            "temperature": 0.1,
            "max_tokens": 8192
        }

    注意:
        - alias 是配置唯一标识，不可通过 API 修改
        - api_key 可通过 API 修改并持久化到 providers.yaml（明文存储，注意安全）
        - 若 api_key 为空字符串，则回退到环境变量
        - 更新后立即持久化到 agent_config/providers.yaml
        - 进行中的 run 不受影响（已创建的 Provider 实例独立）
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    if not isinstance(body, dict):
        return {"status": "error", "message": "请求体必须是 JSON 对象"}

    from agent.provider_settings import get_provider_settings_store, mask_api_key
    from agent.providers.factory import BUILTIN_PROVIDER_DEFAULTS

    store = get_provider_settings_store()
    try:
        cfg = store.update_provider(alias, body)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    defaults = BUILTIN_PROVIDER_DEFAULTS.get(cfg.provider_id)
    env_key = defaults.env_key if defaults else ""
    api_key = cfg.api_key if cfg.api_key else (os.environ.get(env_key, "") if env_key else "")

    item = cfg.to_dict()
    item["api_key_masked"] = mask_api_key(api_key)
    item["api_key_source"] = "configured" if cfg.api_key else ("env" if env_key and os.environ.get(env_key) else "none")
    item["env_key"] = env_key

    logger.info(f"Stage 13.2: Provider {alias} 配置已更新")

    return {
        "status": "ok",
        "message": f"Provider {alias} 配置已更新",
        "provider": item,
    }


@router.delete("/providers/{alias}")
async def delete_provider(alias: str):
    """删除 Provider 配置 — Stage 13.2 新增

    删除后回退到环境变量配置 + 内置默认值。
    """
    from agent.provider_settings import get_provider_settings_store

    store = get_provider_settings_store()
    success = store.delete_provider(alias)
    if not success:
        return {
            "status": "error",
            "message": f"provider {alias} 不存在",
        }

    logger.info(f"Stage 13.2: Provider {alias} 配置已删除")
    return {
        "status": "ok",
        "message": f"Provider {alias} 配置已删除",
    }


# ============================================================================
# Stage 13.3 (X7): global/local rule toggle API — 对标 Cline workspaceState
# ============================================================================


@router.get("/sessions/{session_id}/rule_toggles")
async def get_session_rule_toggles(session_id: str, request: Request):
    """获取会话的 rule toggles — Stage 13.3 新增

    查询参数:
        scope: "local" 仅返回 local，"merged" 返回合并后（默认），"global" 仅返回 global

    返回:
        toggles: toggle dict
        scope: 实际返回的 scope
    """
    scope = request.query_params.get("scope", "merged")
    from agent.rules_loader import (
        _default_toggles_store_path,
        load_local_toggles,
        load_merged_toggles,
        load_toggles,
    )

    rules_dir = Path("agent_config") / "rules"
    global_path = _default_toggles_store_path(rules_dir)

    if scope == "local":
        toggles = load_local_toggles(session_id)
    elif scope == "global":
        toggles = load_toggles(global_path)
    else:  # merged
        toggles = load_merged_toggles(global_path, session_id)

    return {
        "status": "ok",
        "toggles": toggles,
        "scope": scope,
    }


@router.put("/sessions/{session_id}/rule_toggles")
async def update_session_rule_toggles(session_id: str, request: Request):
    """更新会话的 local rule toggles — Stage 13.3 新增

    请求体:
        {
            "toggles": {"general.md": false, "trading.md": true}
        }

    写入 local 文件，覆盖 global。session_id 为空时返回错误。
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    toggles = body.get("toggles")
    if not isinstance(toggles, dict):
        return {"status": "error", "message": "toggles 必须是 dict"}

    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}

    from agent.rules_loader import save_local_toggles

    # 校验 value 必须为 bool
    clean_toggles: dict[str, bool] = {}
    for k, v in toggles.items():
        if isinstance(k, str) and isinstance(v, bool):
            clean_toggles[k] = v

    save_local_toggles(session_id, clean_toggles)

    return {
        "status": "ok",
        "message": f"已更新会话 {session_id} 的 local toggles（{len(clean_toggles)} 项）",
        "toggles": clean_toggles,
    }


@router.delete("/sessions/{session_id}/rule_toggles")
async def clear_session_rule_toggles(session_id: str):
    """清空会话的 local rule toggles，回退到 global — Stage 13.3 新增"""
    if not session_id:
        return {"status": "error", "message": "session_id 不能为空"}

    from agent.rules_loader import clear_local_toggles

    success = clear_local_toggles(session_id)
    if not success:
        return {
            "status": "ok",
            "message": f"会话 {session_id} 无 local toggles（已是 global 状态）",
        }

    return {
        "status": "ok",
        "message": f"已清空会话 {session_id} 的 local toggles，回退到 global",
    }


# ============================================================================
# Stage 14.2 (Z11): Cron 管理 API — 对标 Cline cron 完整架构
# ============================================================================


@router.get("/cron/specs")
async def list_cron_specs():
    """列出当前 cron spec — Stage 14.2 新增

    返回 agent_config/cron/ 下所有 yaml spec。
    """
    import sys
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scheduler import load_cron_specs, _cron_specs_dir

    specs = load_cron_specs(_cron_specs_dir())
    return {
        "status": "ok",
        "specs": specs,
        "total": len(specs),
    }


@router.get("/cron/last_run/{name}")
async def get_cron_last_run(name: str):
    """获取 cron job 上次执行结果 — Stage 14.2 新增"""
    from agent.cron_materializer import CronMaterializer

    materializer = CronMaterializer()
    run_info = materializer.get_last_run(name)
    if run_info is None:
        return {
            "status": "error",
            "message": f"job {name} 无执行记录",
        }
    return {
        "status": "ok",
        "name": name,
        "last_run": run_info,
    }


@router.get("/cron/all_runs")
async def list_cron_all_runs():
    """列出所有 cron job 的上次执行结果 — Stage 14.2 新增"""
    from agent.cron_materializer import CronMaterializer

    materializer = CronMaterializer()
    all_runs = materializer.get_all_last_runs()
    # 前端期望 runs 为列表，每项包含 name 字段
    runs_list = [{"name": name, **info} for name, info in all_runs.items()]
    return {
        "status": "ok",
        "runs": runs_list,
        "total": len(runs_list),
    }


@router.post("/cron/reconcile")
async def trigger_cron_reconcile():
    """手动触发 cron reconcile — Stage 14.2 新增

    重新扫描 agent_config/cron/ 目录，更新已注册 job。
    注意: 此端点仅在有活跃 scheduler 时有效（scheduler 作为独立进程运行）。
    """
    import sys
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scheduler import load_cron_specs, _cron_specs_dir
    from agent.cron_materializer import CronMaterializer

    # 仅返回当前 spec 列表和状态（实际 reconcile 在独立 scheduler 进程中）
    specs = load_cron_specs(_cron_specs_dir())
    materializer = CronMaterializer()
    recorded_specs = materializer.get_all_specs()
    all_runs = materializer.get_all_last_runs()

    return {
        "status": "ok",
        "message": "当前 spec 和状态已返回（实际 reconcile 在 scheduler 进程中执行）",
        "current_specs": specs,
        "recorded_specs": list(recorded_specs.keys()),
        "last_runs": list(all_runs.keys()),
    }


# ============================================================================
# Phase 24: Telemetry / Connectors / Kanban API — 对标 Cline 特色系统
# ============================================================================


@router.get("/telemetry/events")
async def list_telemetry_events(request: Request):
    """查询遥测事件 — Phase 24 新增

    查询参数:
        session_id: 按会话过滤（可选）
        event_type: 按事件类型过滤（可选，如 run.started / tool.finished）
        limit: 返回事件数上限（默认 100，最大 500）

    返回:
        events: 事件列表（最新在前），每项含 event/ts/session_id/properties 等字段
        total: 返回的事件数
    """
    session_id = request.query_params.get("session_id", "")
    event_type = request.query_params.get("event_type", "")
    try:
        limit = int(request.query_params.get("limit", "100"))
        limit = max(1, min(500, limit))
    except ValueError:
        limit = 100

    from agent.telemetry import get_telemetry_service
    service = get_telemetry_service()
    events = service.query_events(
        session_id=session_id or None,
        event_type=event_type or None,
        limit=limit,
    )

    return {
        "status": "ok",
        "events": events,
        "total": len(events),
    }


@router.get("/telemetry/sinks")
async def list_telemetry_sinks():
    """列出已注册的遥测 sink — Phase 24 新增

    返回:
        sinks: sink 列表，每项含 name 和 type
    """
    from agent.telemetry import get_telemetry_service
    service = get_telemetry_service()
    return {
        "status": "ok",
        "sinks": service.list_sinks(),
    }


@router.post("/telemetry/flush")
async def flush_telemetry():
    """刷新遥测 sink 缓冲区 — Phase 24 新增

    手动触发将缓冲区中的事件写入持久化存储（如文件）。
    """
    from agent.telemetry import get_telemetry_service
    service = get_telemetry_service()
    service.flush()
    return {"status": "ok", "message": "已刷新所有 sink"}


@router.get("/connectors")
async def list_connectors():
    """列出已配置的连接器 — Phase 24 新增

    返回:
        connectors: 连接器列表
        total: 连接器总数
        enabled: 启用的连接器数
    """
    from agent.connectors import get_connector_manager
    manager = get_connector_manager()
    connectors = [c.to_dict() for c in manager.list_connectors()]
    enabled = sum(1 for c in connectors if c.get("enabled"))
    return {
        "status": "ok",
        "connectors": connectors,
        "total": len(connectors),
        "enabled": enabled,
    }


@router.post("/connectors/reload")
async def reload_connectors():
    """重新加载连接器配置 — Phase 24 新增

    修改 agent_config/connectors.yaml 后调用此端点热加载。
    """
    from agent.connectors import get_connector_manager
    manager = get_connector_manager()
    count = manager.reload()
    return {
        "status": "ok",
        "message": f"已重新加载连接器配置，{count} 个连接器已启用",
        "enabled": count,
    }


# ===== 看板功能已屏蔽（2026-08-04）=====
# 原因：TodoWrite 工具已从代码中移除，SessionState.todos 无数据源，看板失去意义。
# 处理：三个看板端点（/kanban、/kanban/overview、/kanban/progress）整体注释，
#       前端对应入口（ai-chat.html 工具栏按钮、ai-chat.js 看板调用点）也已屏蔽。
#       若日后恢复 TodoWrite 工具，可取消本段注释并恢复前端入口。
# @router.get("/kanban")
# async def get_kanban_board(request: Request):
#     """获取会话的看板视图 — Phase 24 新增
#
#     查询参数:
#         session_id: 会话 ID（必填）
#
#     返回:
#         看板数据，含 3 列（待办/进行中/已完成）和进度统计
#     """
#     session_id = request.query_params.get("session_id", "")
#     if not session_id:
#         return {"status": "error", "message": "session_id 不能为空"}
#
#     from agent.kanban import get_kanban_manager
#     manager = get_kanban_manager()
#     board = manager.get_board(session_id)
#     return {
#         "status": "ok",
#         "board": board.to_dict(),
#     }
#
#
# @router.get("/kanban/overview")
# async def get_kanban_overview():
#     """获取所有会话的看板概览 — Phase 24 新增
#
#     返回所有持久化会话的看板摘要，用于多项目看板视图。
#
#     返回:
#         sessions: 各会话的看板摘要列表
#         total_sessions: 会话总数
#         total_tasks: 任务总数
#     """
#     from agent.kanban import get_kanban_manager
#     manager = get_kanban_manager()
#     overview = manager.get_overview()
#     return {"status": "ok", **overview}
#
#
# @router.get("/kanban/progress")
# async def get_kanban_progress(request: Request):
#     """获取会话的任务进度统计 — Phase 24 新增
#
#     查询参数:
#         session_id: 会话 ID（必填）
#
#     返回:
#         进度统计 {total, pending, in_progress, completed, completion_rate}
#     """
#     session_id = request.query_params.get("session_id", "")
#     if not session_id:
#         return {"status": "error", "message": "session_id 不能为空"}
#
#     from agent.kanban import get_kanban_manager
#     manager = get_kanban_manager()
#     progress = manager.get_progress(session_id)
#     return {"status": "ok", "progress": progress}




def _sse_error_response(text: str):
    """错误响应"""
    return StreamingResponse(
        iter([_sse_event("error", {"text": text}), _sse_event("done", {})]),
        media_type="text/event-stream",
    )
