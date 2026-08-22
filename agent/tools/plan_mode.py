# -*- coding: utf-8 -*-
"""Plan Mode 切换工具 — 对标 Cline switch_to_act_mode + Charles 扩展 switch_to_plan_mode

实现 Cline 的 Plan Mode 工作流:
    - Plan 模式: LLM 只能探索、分析、规划，不能编辑文件或运行破坏性命令
    - Act 模式: 直接执行任务（默认模式）

工作流程:
    1. 复杂任务时，用户或 LLM 切换到 Plan 模式
    2. Plan 模式下 LLM 读取文件、搜索代码、呈现计划
    3. 用户审核并明确批准后，LLM 调用 switch_to_act_mode 切换到 Act 模式
    4. Act 模式下 LLM 执行计划

关键设计:
    - lifecycle.completes_run = True: 切换后结束本轮，等待用户响应
    - 通过 SessionState.mode 持久化模式状态
    - SystemPromptBuilder 根据 mode 注入 PLAN_MODE_PROMPT
    - 工具策略: Plan 模式下写入类工具由 tool_policies 硬禁用，run_commands 仅限只读

对标 Cline:
    - apps/vscode/src/sdk/sdk-session-config-builder.ts L51-80 createSwitchToActModeTool
    - sdk/packages/shared/src/prompt/cline.ts L32-45 PLAN_MODE_INSTRUCTIONS

注: switch_to_plan_mode 为 Charles 扩展（Cline 仅有 switch_to_act_mode），
    允许 LLM 主动从 Act 切回 Plan 进行重新规划。
"""

from __future__ import annotations

from typing import Any

from agent.state import AgentMode, get_mode, set_mode
from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult, ToolLifecycle


# ============================================================================
# Plan Mode 提示词 — 对标 Cline PLAN_MODE_INSTRUCTIONS
# ============================================================================

PLAN_MODE_PROMPT = """# Plan Mode

当前处于 Plan（规划）模式。你的任务是探索、分析并给出清晰的执行计划，而不是直接执行。

## 模式行为契约

- **探索**: 可以调用 read_files / list_files / search_codebase / run_commands（只读检查：列目录、搜索、git log、查版本等）/ use_mcp_tool / skills（除 write-report 外）收集上下文
- **run_commands 限制**: run_commands 在 Plan 模式下仅用于只读检查（列目录、搜索 grep、读配置、查 git 历史/diff、查工具版本等），禁止用于任何修改操作：不创建/修改/删除文件、不运行会变更状态的命令（安装、迁移、数据库/Schema 变更、容器状态变更等）。需要修改的任务必须写入计划，等切换到 Act 模式后执行。
- **规划**: 将任务拆解为清晰的步骤，按计划呈现格式输出（见 plan-mode-rules.md）
- **不执行**: 不要直接实现或输出最终产物；重点是给出计划、大纲和步骤
- **工具限制**: editor / apply_patch / file_write / write-report 等写入/编辑类工具已由 tool_policies 硬禁用，无需自律

## 完成规划后

调用 switch_to_act_mode 工具切换到 Act 模式，等待用户明确批准后再开始执行。
用户批准方式包括: 用户说"可以"、"开始执行"、"切换到 Act"等明确指令。

注意: 不要把原始任务请求当作批准；呈现计划后结束当前轮次，等待用户响应。"""


# ============================================================================
# Auto-continue 续跑提示词 — 对标 Cline ACT_MODE_CONTINUATION_PROMPT
# ============================================================================

# 当从 plan 模式切换到 act 模式时，自动注入此 prompt 让 LLM 立即开始执行计划。
# 对标 Cline:
#   - apps/vscode/src/sdk/sdk-mode-coordinator.ts L25 ACT_MODE_CONTINUATION_PROMPT
#   - apps/cli/src/runtime/interactive/mode.ts L28-29 ACT_MODE_CONTINUATION_PROMPT
# 这是一个合成的 user message，不作为用户气泡展示，仅驱动 LLM 继续执行。
ACT_MODE_CONTINUATION_PROMPT = (
    "用户已批准切换到 act 模式。现在请按照已批准的计划，逐步开始执行。"
)


# ============================================================================
# 会话重建辅助 — 对标 Cline rebuildSessionForMode
# ============================================================================

# 全局 pending mode rebuild 请求: session_id → {"from_mode": ..., "to_mode": ...}
# 对标 Cline pendingModeChange — 标记需要重建会话的会话
# SwitchToActModeTool / SwitchToPlanModeTool 切换模式后写入，
# SSE 生成器在 run 结束后消费，执行消息清理和 auto-continue。
_pending_mode_rebuilds: dict[str, dict[str, str]] = {}


def request_mode_rebuild(session_id: str, from_mode: str, to_mode: str) -> None:
    """请求会话重建 — 对标 Cline pendingModeChange.current = target

    由 SwitchToActModeTool / SwitchToPlanModeTool 在切换模式后调用。
    SSE 生成器在 run 结束后通过 consume_mode_rebuild 消费此请求，
    执行消息清理（rebuild_messages_for_mode）和 auto-continue（仅 plan→act）。

    Args:
        session_id: 会话 ID
        from_mode: 切换前的模式（act / plan）
        to_mode: 切换后的模式（act / plan）
    """
    _pending_mode_rebuilds[session_id] = {
        "from_mode": from_mode,
        "to_mode": to_mode,
    }


def consume_mode_rebuild(session_id: str) -> dict[str, str] | None:
    """取出并清除 pending mode rebuild 请求 — 对标 Cline applyPendingModeChange

    由 SSE 生成器在 run 结束后调用。若返回非 None，说明 run 期间发生了模式切换，
    需要执行会话重建（消息清理）。若 to_mode == "act"，还需 auto-continue。

    Args:
        session_id: 会话 ID

    Returns:
        含 from_mode / to_mode 的字典（若存在 pending 请求），否则 None
    """
    return _pending_mode_rebuilds.pop(session_id, None)


def cancel_pending_mode_rebuild(session_id: str) -> None:
    """取消 pending mode rebuild 请求（会话中止/清除时调用）"""
    _pending_mode_rebuilds.pop(session_id, None)


def rebuild_messages_for_mode(
    messages: list[Any],
    keep_recent: int = 10,
) -> list[Any]:
    """会话重建：清理旧模式上下文，保留最近几轮对话 — 对标 Cline rebuildSessionForMode

    切换模式时调用，裁剪消息历史以减少旧模式上下文干扰:
        1. 保留最近 keep_recent 条消息（默认 10 条，约 2-3 轮对话）
        2. 避免从孤立的 tool 消息开始（tool 消息需要前序 assistant tool-call 配对）
        3. 若消息总数不足 keep_recent，原样返回

    对标 Cline performRebuildSessionForMode 中的 loadInitialMessages + 替换会话逻辑。
    Cline 重建时会用旧会话消息作为新会话的 initialMessages，本实现在此基础上
    做了裁剪以减少上下文膨胀（Charles 的 ContextCompactor 会进一步处理溢出）。

    Args:
        messages: 原始消息列表
        keep_recent: 保留的最近消息条数，默认 10

    Returns:
        裁剪后的消息列表
    """
    if len(messages) <= keep_recent:
        return list(messages)

    # 从末尾取最近 keep_recent 条
    trimmed = list(messages[-keep_recent:])

    # 避免从孤立的 tool 消息开始：若首条是 tool 消息，移除它
    # （tool 消息依赖前序 assistant 的 tool-call，孤立存在会让 LLM 困惑）
    from agent.types import MessageRole
    while trimmed and trimmed[0].role == MessageRole.TOOL:
        trimmed.pop(0)

    return trimmed


# ============================================================================
# 模式切换工具
# ============================================================================


class SwitchToActModeTool(BaseTool):
    """切换到 Act 模式 — 对标 Cline switch_to_act_mode

    从 Plan 模式切换到 Act 模式，切换后立即开始执行计划。
    lifecycle.completes_run = True: 切换后结束本轮，等待用户下次输入。

    使用约束:
        - 仅在 Plan 模式下可用（server.py 通过 tool_policies 控制）
        - 必须在用户明确批准计划后调用
        - 不要在呈现计划的同一轮调用
    """

    def __init__(self, session_id: str) -> None:
        """初始化切换到 Act 模式工具

        Args:
            session_id: 会话 ID
        """
        self._session_id = session_id

    @property
    def name(self) -> str:
        return "switch_to_act_mode"

    @property
    def description(self) -> str:
        return (
            "从 Plan 模式切换到 Act 模式。切换后立即开始执行计划。"
            "仅在用户明确批准计划后调用（如'可以'、'开始执行'、'切换到 Act 模式'）。"
            "不要在呈现计划的同一轮调用，不要把原始任务请求当作批准。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "description": "无参数。调用后立即切换到 Act 模式。",
        }

    @property
    def lifecycle(self) -> ToolLifecycle:
        """生命周期标记 — completes_run=True

        切换模式后结束本轮，等待用户下次输入再开始执行。
        对标 Cline switch_to_act_mode 的 completes_run 行为。
        """
        return ToolLifecycle(completes_run=True)

    @property
    def read_only(self) -> bool:
        # 仅修改会话状态，无外部副作用
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行模式切换

        1. 校验当前模式（必须为 plan 才能切换到 act）
        2. 更新 SessionState.mode
        3. 通知前端 mode 切换
        4. 请求会话重建 + auto-continue（对标 Cline pendingModeChange + ACT_MODE_CONTINUATION_PROMPT）
        5. 返回切换结果
        """
        current_mode = get_mode(self._session_id)
        if current_mode != "plan":
            return AgentToolResult(
                output={
                    "error": f"当前已是 {current_mode} 模式，无需切换",
                    "current_mode": current_mode,
                },
                is_error=True,
            )

        old_mode = set_mode(self._session_id, "act")

        # 通知前端
        if context.emit_update is not None:
            try:
                context.emit_update({
                    "mode_changed": {
                        "old_mode": old_mode,
                        "new_mode": "act",
                    },
                })
            except Exception:
                pass

        # 请求会话重建 + auto-continue — 对标 Cline pendingModeChange.current = "act"
        # SSE 生成器在 run 结束后消费此请求：
        #   1. 调用 rebuild_messages_for_mode 清理旧 plan 模式上下文
        #   2. 重建 act 模式系统提示和工具
        #   3. 自动注入 ACT_MODE_CONTINUATION_PROMPT 启动续跑
        request_mode_rebuild(self._session_id, old_mode, "act")

        return AgentToolResult(
            output=(
                f"已从 {old_mode} 模式切换到 act 模式。"
                "你现在可以编辑文件、运行命令、执行计划。"
                "(switch_to_act_mode 工具仅在 plan 模式可用)"
            ),
            metadata={
                "old_mode": old_mode,
                "new_mode": "act",
                "session_id": self._session_id,
            },
        )


class SwitchToPlanModeTool(BaseTool):
    """切换到 Plan 模式 — Charles 扩展（Cline 仅有 switch_to_act_mode）

    从 Act 模式切换到 Plan 模式，切换后进入只读规划状态。
    lifecycle.completes_run = True: 切换后结束本轮，等待用户下次输入。

    使用场景:
        - 用户希望重新规划任务
        - 任务方向偏离，需要重新对齐
        - 复杂任务开始前的规划阶段
    """

    def __init__(self, session_id: str) -> None:
        """初始化切换到 Plan 模式工具

        Args:
            session_id: 会话 ID
        """
        self._session_id = session_id

    @property
    def name(self) -> str:
        return "switch_to_plan_mode"

    @property
    def description(self) -> str:
        return (
            "从 Act 模式切换到 Plan 模式。切换后进入只读规划状态。"
            "用于重新规划任务或复杂任务开始前的规划阶段。"
            "Plan 模式下只能读取文件、搜索代码、呈现计划，不能编辑或运行破坏性命令。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "description": "无参数。调用后立即切换到 Plan 模式。",
        }

    @property
    def lifecycle(self) -> ToolLifecycle:
        """生命周期标记 — completes_run=True

        切换模式后结束本轮，等待用户下次输入再开始规划。
        """
        return ToolLifecycle(completes_run=True)

    @property
    def read_only(self) -> bool:
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行模式切换

        1. 校验当前模式（必须为 act 才能切换到 plan）
        2. 更新 SessionState.mode
        3. 通知前端 mode 切换
        4. 请求会话重建（对标 Cline rebuildSessionForMode，无 auto-continue）
        5. 返回切换结果
        """
        current_mode = get_mode(self._session_id)
        if current_mode != "act":
            return AgentToolResult(
                output={
                    "error": f"当前已是 {current_mode} 模式，无需切换",
                    "current_mode": current_mode,
                },
                is_error=True,
            )

        old_mode = set_mode(self._session_id, "plan")

        # 通知前端
        if context.emit_update is not None:
            try:
                context.emit_update({
                    "mode_changed": {
                        "old_mode": old_mode,
                        "new_mode": "plan",
                    },
                })
            except Exception:
                pass

        # 请求会话重建 — 对标 Cline rebuildSessionForMode（plan 方向无 auto-continue）
        # SSE 生成器在 run 结束后消费此请求：
        #   1. 调用 rebuild_messages_for_mode 清理旧 act 模式上下文
        #   2. 下次用户输入时使用 plan 模式系统提示和工具
        request_mode_rebuild(self._session_id, old_mode, "plan")

        return AgentToolResult(
            output=(
                f"已从 {old_mode} 模式切换到 plan 模式。"
                "你现在可以读取文件、搜索代码、呈现计划，但不能编辑或运行破坏性命令。"
                "完成规划后调用 switch_to_act_mode 切换回 act 模式开始执行。"
            ),
            metadata={
                "old_mode": old_mode,
                "new_mode": "plan",
                "session_id": self._session_id,
            },
        )


# ============================================================================
# 辅助函数 — 供 SystemPromptBuilder 和 runtime 使用
# ============================================================================


def get_mode_prompt(session_id: str) -> str | None:
    """根据当前 mode 返回对应的提示词

    Plan 模式返回 PLAN_MODE_PROMPT，Act 模式返回 None。

    Args:
        session_id: 会话 ID

    Returns:
        Plan 模式提示词，或 None（Act 模式）
    """
    mode = get_mode(session_id)
    if mode == "plan":
        return PLAN_MODE_PROMPT
    return None


def is_plan_mode(session_id: str) -> bool:
    """判断当前是否为 Plan 模式"""
    return get_mode(session_id) == "plan"


def is_act_mode(session_id: str) -> bool:
    """判断当前是否为 Act 模式"""
    return get_mode(session_id) == "act"
