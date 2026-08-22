# -*- coding: utf-8 -*-
"""文件 hook 集成层 — Phase 28.3 新增

将文件 hook 系统桥接到 Python 内建 hook 系统。

设计思路（对标 Cline HookProcess 注入到 AgentRuntimeHooks）：
    1. 扫描 agent_config/hooks/ 目录加载 FileHookConfig 列表
    2. 按 hook_type 分组：PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete
    3. 每组生成一个 Python hook 函数，内部并行执行所有匹配的文件 hook（Stage 12.5/P16）
    4. 文件 hook 返回 block 时，Python hook 返回对应的 stop/skip/result

文件 hook 类型到 Python hook 点的映射：
    PreToolUse       → before_tool      （block 时 skip=True）
    PostToolUse      → after_tool       （block 时 stop=True）
    UserPromptSubmit → prepare_turn_input（block 时 stop=True）
    TaskStart        → before_run       （block 时 stop=True）
    TaskComplete     → after_run        （block 时不影响，仅记录日志）

典型用法（在 AgentRuntime.__init__ 中调用）：
    from agent.file_hooks.integration import build_file_hooks_agent_hooks

    if config.enable_file_hooks and config.file_hooks_dir:
        file_hooks = build_file_hooks_agent_hooks(
            hooks_dir=config.file_hooks_dir,
            session_id=config.session_id or "",
            agent_id=config.agent_id or "",
        )
        if file_hooks is not None:
            self.register_hooks(file_hooks)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent.file_hooks.loader import load_hooks_from_dir
from agent.file_hooks.registry import get_global_registry
from agent.file_hooks.runner import run_hook
from agent.file_hooks.types import (
    FileHookConfig,
    FileHookContext,
    FileHookType,
    HOOK_TYPE_MAPPING,
)
from agent.hooks import (
    AgentHooks,
    AfterRunContext,
    AfterToolContext,
    AfterToolResult,
    BeforeRunHook,
    BeforeToolContext,
    BeforeToolResult,
    PrepareTurnInputContext,
    PrepareTurnInputResult,
    RunLifecycleContext,
    StopControl,
)
from agent.types import AgentToolResult

logger = logging.getLogger(__name__)


# ============================================================================
# 上下文构建辅助函数
# ============================================================================


def _make_context(
    hook_type: FileHookType,
    snapshot: Any,
    session_id: str,
    agent_id: str,
    **extra: Any,
) -> FileHookContext:
    """构建 FileHookContext

    Args:
        hook_type: hook 类型
        snapshot: AgentRuntimeStateSnapshot（用于提取 run_id/iteration）
        session_id: 会话 ID
        agent_id: Agent ID
        **extra: 额外字段（tool_name、input、result 等）

    Returns:
        FileHookContext 实例
    """
    run_id = ""
    iteration = 0
    # snapshot 是 AgentRuntimeStateSnapshot dataclass
    try:
        run_id = getattr(snapshot, "run_id", "") or ""
        iteration = getattr(snapshot, "iteration", 0) or 0
    except Exception:
        pass

    return FileHookContext(
        hook_type=hook_type.value,
        session_id=session_id,
        run_id=run_id,
        iteration=iteration,
        **extra,
    )


# ============================================================================
# Hook 执行辅助函数
# ============================================================================

# Stage 12.5 (P16): 并行执行 hook 的并发上限 — 对标 Cline 资源限制
# 超过此数量的 hook 将分批执行，避免启动过多子进程导致系统资源耗尽
_MAX_PARALLEL_HOOKS = 10


async def _run_hooks_of_type(
    configs: list[FileHookConfig],
    context: FileHookContext,
    tool_name: str | None = None,
) -> tuple[str, str]:
    """并行执行一组同类型文件 hook — Stage 12.5 (P16) 改造

    使用 asyncio.gather 并行执行所有匹配的 hook，结果按注册顺序合并。
    对标 Cline file-hooks.ts 的 Promise.all 并行执行模型。

    资源限制:
        同时运行的 hook 数量上限为 _MAX_PARALLEL_HOOKS（10），
        超出部分串行追加执行（保留注册顺序），避免启动过多子进程。

    P1-7 增强: 获取全局 HookProcessRegistry 并传递给 run_hook，使
    hook 进程注册到 registry，abort 时可统一 kill。

    Args:
        configs: 同类型的 FileHookConfig 列表
        context: hook 执行上下文
        tool_name: 当前工具名（仅 PreToolUse/PostToolUse 时使用，用于 apply_to 过滤）

    Returns:
        (action, reason) 元组
            action: "continue" / "block"
            reason:
                - block 时为阻止原因
                - continue 时为 context_injection 文本（多个 hook 的注入用空行分隔，可能为空字符串）
    """
    # 1. 预过滤：apply_to 不匹配的 hook 不参与执行
    applicable_configs = [
        cfg for cfg in configs
        if tool_name is None or cfg.applies_to_tool(tool_name)
    ]

    if not applicable_configs:
        return "continue", ""

    # P1-7: 获取全局 registry，传递给 run_hook 以注册进程
    # registry 绑定了 runtime 的 abort_signal，abort 时 kill_all 终止 hook 进程
    registry = get_global_registry()

    # P1-7: 执行前检查 abort_signal，避免 abort 后仍启动 hook 进程
    if registry.is_aborted():
        logger.info("文件 hook 因 abort 跳过执行（共 %d 个）", len(applicable_configs))
        return "continue", ""

    # 2. 资源限制：超过 _MAX_PARALLEL_HOOKS 时分批执行
    #    前一批并行执行，超出部分串行追加（保留注册顺序）
    batch = applicable_configs[:_MAX_PARALLEL_HOOKS]
    overflow = applicable_configs[_MAX_PARALLEL_HOOKS:]

    if overflow:
        logger.warning(
            "文件 hook 数量 %d 超过并发上限 %d，超出部分将串行执行",
            len(applicable_configs), _MAX_PARALLEL_HOOKS,
        )

    # 收集所有 context_injection（continue 时可能注入文本）
    injections: list[str] = []

    # 3. 并行执行第一批（asyncio.gather 保留注册顺序）
    # P1-7: 传递 registry 让 hook 进程注册到全局注册表
    tasks = [run_hook(cfg, context, registry=registry) for cfg in batch]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 4. 按注册顺序处理结果
    for cfg, result in zip(batch, results):
        # asyncio.gather(return_exceptions=True) 时异常作为结果返回
        if isinstance(result, Exception):
            if cfg.blocking:
                logger.info(
                    "文件 hook 阻塞异常: %s, error=%s",
                    cfg.script_path.name, result,
                )
                return "block", f"hook {cfg.script_path.name} 执行异常: {result}"
            logger.warning(
                "文件 hook 执行异常（非阻塞，已忽略）: %s, error=%s",
                cfg.script_path.name, result,
            )
            continue

        if result.action == "continue":
            if result.context_injection:
                injections.append(result.context_injection)
            continue

        if result.action == "block":
            # 任一 hook block 即终止（第一个 block 生效）
            logger.info(
                "文件 hook 阻止执行: %s, reason=%s",
                cfg.script_path.name, result.reason,
            )
            return "block", result.reason

        if result.action == "error":
            # 错误时根据 blocking 决定是否终止
            if cfg.blocking:
                return "block", result.reason
            # 非 blocking 时仅记录日志，继续处理下一个
            logger.warning(
                "文件 hook 执行错误（非阻塞，已忽略）: %s, reason=%s",
                cfg.script_path.name, result.reason,
            )

    # 5. 串行执行超出部分（如果有）— 保留注册顺序，与并行批次结果合并
    # P1-7: 传递 registry 让 hook 进程注册到全局注册表
    # P2 增强：并行批次完成后检查 abort 状态，若已 abort 跳过所有串行 hook
    if overflow and registry.is_aborted():
        logger.info(
            "并行批次完成后检测到 abort，跳过剩余 %d 个串行 hook",
            len(overflow),
        )
        injection_text = "\n\n".join(injections) if injections else ""
        return "continue", injection_text

    for cfg in overflow:
        # P1-7: 每个串行 hook 执行前检查 abort
        if registry.is_aborted():
            logger.info("文件 hook 因 abort 跳过剩余串行执行: %s", cfg.script_path.name)
            break

        result = await run_hook(cfg, context, registry=registry)

        if result.action == "continue":
            if result.context_injection:
                injections.append(result.context_injection)
            continue

        if result.action == "block":
            logger.info(
                "文件 hook 阻止执行: %s, reason=%s",
                cfg.script_path.name, result.reason,
            )
            return "block", result.reason

        if result.action == "error":
            if cfg.blocking:
                return "block", result.reason
            logger.warning(
                "文件 hook 执行错误（非阻塞，已忽略）: %s, reason=%s",
                cfg.script_path.name, result.reason,
            )

    # 6. 所有 hook 通过，把 injections 拼接返回（用空行分隔）
    injection_text = "\n\n".join(injections) if injections else ""
    return "continue", injection_text


# ============================================================================
# 各 hook 点的 Python hook 函数工厂
# ============================================================================


def _make_before_tool_hook(
    configs: list[FileHookConfig],
    session_id: str,
    agent_id: str,
) -> BeforeRunHook:
    """构建 before_tool Python hook — 对应 PreToolUse 文件 hook

    文件 hook block 时返回 BeforeToolResult(skip=True)。
    文件 hook continue 且有 context_injection 时，通过 additional_context 字段
    传递给 runtime，runtime 会作为 system message 注入到 messages。
    Stage 12.3 (P9): 激活 context_injection 实际注入（之前仅记录日志）。
    """
    async def hook(ctx: BeforeToolContext) -> BeforeToolResult | None:
        tool_name = ctx.tool_call.tool_name
        file_ctx = _make_context(
            FileHookType.PRE_TOOL_USE,
            ctx.snapshot,
            session_id,
            agent_id,
            tool_name=tool_name,
            tool_call_id=ctx.tool_call.tool_call_id,
            input=ctx.input,
        )
        action, reason = await _run_hooks_of_type(
            configs, file_ctx, tool_name=tool_name,
        )
        if action == "block":
            return BeforeToolResult(
                skip=True,
                reason=reason or f"工具 {tool_name} 被文件 hook 阻止",
            )
        # Stage 12.3 (P9): continue 时若有 context_injection，通过 additional_context
        # 字段返回给 runtime，runtime 会作为 system message 注入到 messages
        if reason:
            logger.debug("before_tool context_injection: %s", reason[:200])
            return BeforeToolResult(additional_context=reason)
        return None

    return hook


def _make_after_tool_hook(
    configs: list[FileHookConfig],
    session_id: str,
    agent_id: str,
) -> BeforeRunHook:
    """构建 after_tool Python hook — 对应 PostToolUse 文件 hook

    文件 hook block 时返回 AfterToolResult(stop=True)。
    """
    async def hook(ctx: AfterToolContext) -> AfterToolResult | None:
        tool_name = ctx.tool_call.tool_name
        # 序列化 result.output 供脚本使用
        result_data: Any
        try:
            output = ctx.result.output
            if isinstance(output, (str, int, float, bool, list, dict, type(None))):
                result_data = output
            else:
                result_data = str(output)
        except Exception:
            result_data = None

        file_ctx = _make_context(
            FileHookType.POST_TOOL_USE,
            ctx.snapshot,
            session_id,
            agent_id,
            tool_name=tool_name,
            tool_call_id=ctx.tool_call.tool_call_id,
            input=ctx.input,
            result=result_data,
            is_error=ctx.result.is_error,
            duration_ms=ctx.duration_ms,
        )
        action, _ = await _run_hooks_of_type(
            configs, file_ctx, tool_name=tool_name,
        )
        if action == "block":
            return AfterToolResult(
                stop=True,
                reason=f"工具 {tool_name} 后置 hook 被文件 hook 阻止",
            )
        return None

    return hook


def _make_prepare_turn_input_hook(
    configs: list[FileHookConfig],
    session_id: str,
    agent_id: str,
) -> BeforeRunHook:
    """构建 prepare_turn_input Python hook — 对应 UserPromptSubmit 文件 hook

    文件 hook block 时返回 PrepareTurnInputResult(stop=True)。
    文件 hook continue 且有 context_injection 时，注入到 modified_input。
    """
    async def hook(ctx: PrepareTurnInputContext) -> PrepareTurnInputResult | None:
        file_ctx = _make_context(
            FileHookType.USER_PROMPT_SUBMIT,
            ctx.snapshot,
            session_id,
            agent_id,
            user_input=ctx.user_input,
        )
        action, injection = await _run_hooks_of_type(configs, file_ctx)
        if action == "block":
            return PrepareTurnInputResult(
                stop=True,
                reason="用户输入被文件 hook 阻止",
            )
        # continue 时若有 context_injection，附加到用户输入末尾
        if injection:
            modified = f"{ctx.user_input}\n\n[hook 注入]\n{injection}"
            return PrepareTurnInputResult(modified_input=modified)
        return None

    return hook


def _make_before_run_hook(
    configs: list[FileHookConfig],
    session_id: str,
    agent_id: str,
    resume_configs: list[FileHookConfig] | None = None,
) -> BeforeRunHook:
    """构建 before_run Python hook — 对应 TaskStart / TaskResume 文件 hook

    文件 hook block 时返回 StopControl(stop=True)。

    Phase 31.6: 新增 resume_configs 参数 — 对标 Cline TaskResume。
    根据 snapshot.messages 是否非空判断是 TaskStart 还是 TaskResume：
        - messages 非空（恢复会话）→ 触发 TaskResume 文件 hook
        - messages 为空（新任务）→ 触发 TaskStart 文件 hook
    """
    resume_configs = resume_configs or []

    async def hook(ctx: RunLifecycleContext) -> StopControl | None:
        # Phase 31.6: 判断是 TaskStart 还是 TaskResume
        # messages 非空表示恢复会话（对标 Cline agent_resume）
        is_resume = bool(ctx.snapshot.messages)
        hook_type = FileHookType.TASK_RESUME if is_resume else FileHookType.TASK_START
        active_configs = resume_configs if is_resume else configs

        # 构建上下文（TaskResume 时附带 previous_state）
        extra: dict[str, Any] = {}
        if is_resume:
            # 对标 Cline taskResume.previousState
            extra["previous_state"] = {
                "message_count": len(ctx.snapshot.messages),
                "last_message_ts": (
                    ctx.snapshot.messages[-1].created_at.isoformat()
                    if ctx.snapshot.messages else ""
                ),
                "conversation_history_deleted": "false",
            }

        file_ctx = _make_context(
            hook_type,
            ctx.snapshot,
            session_id,
            agent_id,
            **extra,
        )
        action, _ = await _run_hooks_of_type(active_configs, file_ctx)
        if action == "block":
            reason = "任务恢复被文件 hook 阻止" if is_resume else "任务被文件 hook 阻止启动"
            return StopControl(stop=True, reason=reason)
        return None

    return hook


def _make_after_run_hook(
    configs: list[FileHookConfig],
    session_id: str,
    agent_id: str,
    cancel_configs: list[FileHookConfig] | None = None,
) -> BeforeRunHook:
    """构建 after_run Python hook — 对应 TaskComplete / TaskCancel 文件 hook

    after_run 不支持 stop，文件 hook block 仅记录日志。

    Phase 31.6: 新增 cancel_configs 参数 — 对标 Cline TaskCancel。
    根据 result.status 判断是 TaskComplete 还是 TaskCancel：
        - status == "aborted" → 触发 TaskCancel 文件 hook
        - 其他 → 触发 TaskComplete 文件 hook
    """
    cancel_configs = cancel_configs or []

    async def hook(ctx: AfterRunContext) -> None:
        # Phase 31.6: 判断是 TaskComplete 还是 TaskCancel
        # status == "aborted" 表示被用户中止（对标 Cline agent_abort）
        is_cancel = ctx.result.status == "aborted"
        hook_type = FileHookType.TASK_CANCEL if is_cancel else FileHookType.TASK_COMPLETE
        active_configs = cancel_configs if is_cancel else configs

        # 构建上下文（TaskCancel 时附带 completion_status）
        extra: dict[str, Any] = {}
        if is_cancel:
            # 对标 Cline taskCancel.completionStatus
            extra["completion_status"] = ctx.result.status

        file_ctx = _make_context(
            hook_type,
            ctx.snapshot,
            session_id,
            agent_id,
            **extra,
        )
        action, _ = await _run_hooks_of_type(active_configs, file_ctx)
        if action == "block":
            logger.warning("after_run 文件 hook 试图阻止已完成的任务（忽略）")
        return None

    return hook


# ============================================================================
# 顶层构建函数
# ============================================================================


def build_file_hooks_agent_hooks(
    hooks_dir: Path | str,
    session_id: str = "",
    agent_id: str = "",
) -> AgentHooks | None:
    """从目录加载文件 hook 并构建 AgentHooks — Phase 28.3 入口函数

    扫描 hooks_dir/{hook_type}/ 下的脚本，按类型分组后构建 AgentHooks。
    任意类型有脚本时返回 AgentHooks，否则返回 None。

    Args:
        hooks_dir: hooks 根目录路径（如 agent_config/hooks/）
        session_id: 会话 ID（用于 hook 上下文）
        agent_id: Agent ID（用于日志和上下文）

    Returns:
        AgentHooks 实例（无任何脚本时返回 None）

    Example:
        hooks = build_file_hooks_agent_hooks(
            hooks_dir="agent_config/hooks",
            session_id="abc123",
        )
        if hooks is not None:
            runtime.register_hooks(hooks)
    """
    hooks_dir_path = Path(hooks_dir)
    configs = load_hooks_from_dir(hooks_dir_path)

    if not configs:
        logger.info("未在 %s 找到任何文件 hook，跳过集成", hooks_dir_path)
        return None

    # 按 hook_type 分组
    grouped: dict[FileHookType, list[FileHookConfig]] = {t: [] for t in FileHookType}
    for cfg in configs:
        grouped[cfg.hook_type].append(cfg)

    # 统计日志
    type_counts = ", ".join(
        f"{t.value}={len(grouped[t])}" for t in FileHookType if grouped[t]
    )
    logger.info("文件 hook 集成: %s", type_counts)

    agent_hooks = AgentHooks()

    # Phase 31.6: before_run 同时处理 TaskStart 和 TaskResume
    # 任意一个有脚本就注册 before_run hook
    if grouped[FileHookType.TASK_START] or grouped[FileHookType.TASK_RESUME]:
        agent_hooks.before_run = _make_before_run_hook(
            grouped[FileHookType.TASK_START],
            session_id,
            agent_id,
            resume_configs=grouped[FileHookType.TASK_RESUME],
        )

    # Phase 31.6: after_run 同时处理 TaskComplete 和 TaskCancel
    # 任意一个有脚本就注册 after_run hook
    if grouped[FileHookType.TASK_COMPLETE] or grouped[FileHookType.TASK_CANCEL]:
        agent_hooks.after_run = _make_after_run_hook(
            grouped[FileHookType.TASK_COMPLETE],
            session_id,
            agent_id,
            cancel_configs=grouped[FileHookType.TASK_CANCEL],
        )

    if grouped[FileHookType.PRE_TOOL_USE]:
        agent_hooks.before_tool = _make_before_tool_hook(
            grouped[FileHookType.PRE_TOOL_USE], session_id, agent_id,
        )

    if grouped[FileHookType.POST_TOOL_USE]:
        agent_hooks.after_tool = _make_after_tool_hook(
            grouped[FileHookType.POST_TOOL_USE], session_id, agent_id,
        )

    if grouped[FileHookType.USER_PROMPT_SUBMIT]:
        agent_hooks.prepare_turn_input = _make_prepare_turn_input_hook(
            grouped[FileHookType.USER_PROMPT_SUBMIT], session_id, agent_id,
        )

    return agent_hooks


__all__ = [
    "build_file_hooks_agent_hooks",
]
