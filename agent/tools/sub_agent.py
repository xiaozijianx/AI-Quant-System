# -*- coding: utf-8 -*-
"""子 agent 工具 — 对标 Cline spawn agent

允许主 agent 创建子 agent 执行特定任务。子 agent 有独立的上下文窗口和
受限的工具集，适合委派需要专注处理的子任务（如代码搜索、信息收集、
局部分析等），避免子任务的中间过程污染主 agent 的上下文。

对标 Cline:
    - sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts
    - sdk/packages/core/src/extensions/tools/team/delegated-agent.ts

设计要点（对标 Cline spawn_agent）:
    1. 子 agent 使用独立的 AgentRuntime 实例（独立消息历史、独立用量）
    2. 子 agent 的工具集受限（通过 allowed_tools 参数指定，默认只读工具集）
    3. 子 agent 执行完成后，结果以 ToolResult 形式返回给主 agent
    4. 子 agent 不直接与用户交互（不发射 SSE 事件，不包含 ask_question 工具）
    5. 子 agent 的 abort_signal 与主 agent 共享（主 agent 中止时子 agent 一并中止）
    6. 子 agent 的最大迭代次数限制（默认 10 次，防止失控）

与 skills 工具的区别:
    - skills: 主上下文内的指令注入，不创建独立 runtime，不限制工具集
    - sub_agent: 独立 runtime + 独立消息历史 + 受限工具集，结果返回主 agent
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Callable

from agent.tools.base import BaseTool
from agent.types import (
    AgentRunResult,
    AgentRuntimeConfig,
    AgentToolContext,
    AgentToolResult,
    MessageRole,
    ToolLifecycle,
    text_from_message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 子 agent 默认可用工具名列表 — 只读工具 + 任务完成工具
# 不包含 ask_question（子 agent 不与用户交互）
# 不包含 editor/apply_patch/file_write/run_commands（默认限制副作用，可通过 allowed_tools 开启）
DEFAULT_SUB_AGENT_TOOLS: list[str] = [
    "read_files",
    "search_codebase",
    "list_files",
    "fetch_web_content",
    "use_mcp_tool",
    "submit_and_exit",
]

# 子 agent 默认最大迭代次数 — 对标 Cline defaultMaxIterations
DEFAULT_SUB_AGENT_MAX_ITERATIONS = 10

# 子 agent 简化系统提示 — 不包含 AGENTS.md 规则、不包含技能列表
# 对标 Cline buildSubAgentSystemPrompt 中的 overridePrompt（精简版 prompt）
SUB_AGENT_SYSTEM_PROMPT = """你是 Charles 的子 agent，负责执行主 agent 委派的特定任务。

## 工作规则

1. 专注于委派任务，高效完成，不要扩展到无关工作。
2. 使用可用的工具收集信息、执行操作，每个思考步骤后选择最合适的工具。
3. 任务完成后必须调用 submit_and_exit 工具提交结果摘要，由主 agent 决定后续动作。
4. 无法获取必要信息时，在摘要中说明限制和原因，不要臆测或编造。
5. 涉及文件系统时使用绝对路径或相对于工作目录的清晰路径，避免歧义。
6. 独立的工具调用可在一次回复中并行发起，有依赖的调用必须分多轮。

## 输出要求

调用 submit_and_exit 时，summary 字段应包含:
- 任务结果（关键发现/产出/结论）
- 简要执行过程（主要步骤）
- 遇到的限制或问题（如有）
"""


# ============================================================================
# SubAgentTool — 对标 Cline createSpawnAgentTool
# ============================================================================


class SubAgentTool(BaseTool):
    """子 agent 工具 — 对标 Cline spawn_agent

    允许主 agent 创建子 agent 执行特定任务。子 agent 有独立的上下文窗口
    和受限的工具集，执行完成后结果返回给主 agent。

    参数:
        task: 委派给子 agent 的任务描述（必填）
        allowed_tools: 子 agent 可用的工具名列表（可选，默认只读工具集）

    工作流程:
        1. 主 agent 调用 sub_agent(task="搜索 X 的实现", allowed_tools=[...])
        2. 工具创建独立的 AgentRuntime 实例（独立消息历史）
        3. 子 agent 使用受限工具集执行任务
        4. 子 agent 调用 submit_and_exit 或自然结束后，结果返回主 agent
        5. 主 agent 在后续轮次中使用子 agent 的结果继续工作

    对标 Cline spawn-agent-tool.ts:
        - createSpawnAgentTool → SubAgentTool
        - createDelegatedAgent → 内部创建 AgentRuntime
        - SpawnAgentInputSchema → input_schema
    """

    def __init__(
        self,
        working_dir: str | None = None,
        max_iterations: int = DEFAULT_SUB_AGENT_MAX_ITERATIONS,
    ) -> None:
        """初始化子 agent 工具

        Args:
            working_dir: 工具执行的工作目录，默认为当前目录。
                         子 agent 的文件类工具（read_files 等）基于此目录解析路径。
            max_iterations: 子 agent 最大迭代次数，默认 10。
                            对标 Cline SpawnAgentToolConfig.defaultMaxIterations。
        """
        self._working_dir = working_dir or os.getcwd()
        self._max_iterations = max_iterations

    @property
    def name(self) -> str:
        return "sub_agent"

    @property
    def description(self) -> str:
        return (
            "创建子 agent 执行特定任务。子 agent 有独立的上下文窗口和受限的工具集，"
            "适合委派需要专注处理的子任务（如代码搜索、信息收集、局部分析），"
            "避免子任务的中间过程污染主 agent 的上下文。"
            "参数: task(必填): 委派任务描述，应清晰具体; "
            "allowed_tools(可选): 子 agent 可用工具名列表，省略时使用默认只读工具集"
            "（read_files/search_codebase/list_files/fetch_web_content/use_mcp_tool/"
            "submit_and_exit）。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "委派给子 agent 的任务描述，应清晰、具体地说明目标和约束",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "子 agent 可用的工具名列表。省略时使用默认只读工具集。"
                        "可选工具名: read_files, search_codebase, list_files, "
                        "fetch_web_content, use_mcp_tool, submit_and_exit, "
                        "run_commands, file_write, editor, apply_patch。"
                    ),
                },
            },
            "required": ["task"],
        }

    @property
    def lifecycle(self) -> ToolLifecycle | None:
        """不标记 completes_run — 子 agent 完成后主 agent 继续工作

        对标 Cline spawn_agent：工具执行后返回结果给主 agent，主 agent 继续
        后续轮次。若标记 completes_run=True 会导致主 agent 在调用 sub_agent
        后立即结束运行，无法处理子 agent 返回的结果。
        """
        return None

    @property
    def read_only(self) -> bool:
        # 子 agent 可能执行写操作（取决于 allowed_tools），标记为 False
        return False

    @property
    def timeout_ms(self) -> int | None:
        """子 agent 超时 — 对标 Cline spawn_agent timeoutMs: 300000"""
        return 300_000

    # ------------------------------------------------------------------
    # 工具集构建
    # ------------------------------------------------------------------

    def _build_sub_tools(self, allowed_tools: list[str] | None) -> list[BaseTool]:
        """构建子 agent 的受限工具集 — 对标 Cline subAgentTools / createSubAgentTools

        Args:
            allowed_tools: 允许的工具名列表，None 时使用 DEFAULT_SUB_AGENT_TOOLS

        Returns:
            工具实例列表。始终包含 submit_and_exit（子 agent 需要它来提交结果）。
        """
        from agent.tools.apply_patch import ApplyPatchTool
        from agent.tools.editor import EditorTool
        from agent.tools.fetch_web_content import FetchWebContentTool
        from agent.tools.file_tools import FileWriteTool
        from agent.tools.list_files import ListFilesTool
        from agent.tools.read_files import ReadFilesTool
        from agent.tools.run_commands import RunCommandsTool
        from agent.tools.search_codebase import SearchCodebaseTool
        from agent.tools.submit_and_exit import SubmitAndExitTool

        sub_agent_sid = f"sub_agent_{uuid.uuid4().hex[:8]}"

        # 工具名 → 工厂函数映射（对标 Cline createSubAgentTools）
        tool_factories: dict[str, Callable[[], BaseTool]] = {
            "read_files": lambda: ReadFilesTool(working_dir=self._working_dir),
            "search_codebase": lambda: SearchCodebaseTool(working_dir=self._working_dir),
            "list_files": lambda: ListFilesTool(working_dir=self._working_dir),
            "fetch_web_content": lambda: FetchWebContentTool(),
            "submit_and_exit": lambda: SubmitAndExitTool(),
            "run_commands": lambda: RunCommandsTool(working_dir=self._working_dir),
            "file_write": lambda: FileWriteTool(working_dir=self._working_dir),
            "editor": lambda: EditorTool(working_dir=self._working_dir),
            "apply_patch": lambda: ApplyPatchTool(working_dir=self._working_dir),
        }

        names = allowed_tools if allowed_tools is not None else DEFAULT_SUB_AGENT_TOOLS
        tools: list[BaseTool] = []
        for n in names:
            factory = tool_factories.get(n)
            if factory is not None:
                tool = factory()
                # 避免重复注册同名工具
                if not any(t.name == tool.name for t in tools):
                    tools.append(tool)

        # 始终确保 submit_and_exit 存在 — 子 agent 需要它来提交结构化结果
        if not any(t.name == "submit_and_exit" for t in tools):
            tools.append(SubmitAndExitTool())

        return tools

    # ------------------------------------------------------------------
    # 执行逻辑
    # ------------------------------------------------------------------

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行子 agent — 对标 Cline spawn_agent execute()

        流程:
            1. 解析 task 和 allowed_tools 参数
            2. 创建子 agent 模型（复用主 agent 的 provider 配置）
            3. 构建子 agent 受限工具集
            4. 创建独立的 AgentRuntime 实例
            5. 共享主 agent 的 abort_signal
            6. 运行子 agent
            7. 提取结果返回给主 agent

        Args:
            input: 工具输入参数
            context: 工具执行上下文（包含 abort_signal 等运行时信息）

        Returns:
            AgentToolResult: 包含子 agent 的执行结果
        """
        task = (input.get("task") or "").strip()
        allowed_tools = input.get("allowed_tools")

        if not task:
            return AgentToolResult(
                output={"error": "task 不能为空"},
                is_error=True,
            )

        # 规范化 allowed_tools
        if allowed_tools is not None:
            if not isinstance(allowed_tools, list):
                return AgentToolResult(
                    output={"error": "allowed_tools 必须是字符串数组"},
                    is_error=True,
                )
            allowed_tools = [str(t) for t in allowed_tools]

        # 1. 创建子 agent 模型 — 复用主 agent 的 provider 配置
        # 对标 Cline DelegatedAgentConfigProvider.getConnectionConfig()
        from agent.providers.factory import create_model_from_env

        try:
            sub_model = create_model_from_env()
        except Exception as e:
            logger.warning("子 agent 模型创建失败: %s", e)
            return AgentToolResult(
                output={"error": f"创建子 agent 模型失败: {e}"},
                is_error=True,
            )

        # 2. 构建子 agent 工具集
        sub_tools = self._build_sub_tools(allowed_tools)

        # 3. 创建子 agent runtime 配置 — 对标 Cline buildDelegatedAgentConfig
        sub_agent_id = f"sub-{uuid.uuid4().hex[:8]}"
        sub_config = AgentRuntimeConfig(
            model=sub_model,
            system_prompt=SUB_AGENT_SYSTEM_PROMPT,
            max_iterations=self._max_iterations,
            agent_id=sub_agent_id,
            agent_role="subagent",
            parent_agent_id=context.agent_id or None,
            # 子 agent 不绑定主会话状态，避免触发主会话的 mode/plan 逻辑
            session_id=None,
            # 子 agent 不需要完成工具强制策略 — submit_and_exit 可选调用
            # require_completion_tool 默认 False，子 agent 自然结束即可
        )

        # 4. 创建子 agent runtime — 对标 Cline createDelegatedAgent
        from agent.runtime import AgentRuntime

        sub_runtime = AgentRuntime(config=sub_config)
        for tool in sub_tools:
            sub_runtime.register_tool(tool)

        # 5. 共享 abort_signal — 主 agent 中止时子 agent 一并中止
        # 对标 Cline createDelegatedAgent 中的 abortSignal: context.signal
        # 主 agent 的 abort_signal 是 asyncio.Event，无法直接注入子 runtime 的
        # AbortController，通过监听任务桥接：主 agent abort → 子 runtime abort
        parent_signal = getattr(context, "abort_signal", None)
        abort_watcher: asyncio.Task[None] | None = None
        if parent_signal is not None and hasattr(parent_signal, "wait"):
            async def _watch_parent_abort() -> None:
                """监听主 agent 的 abort_signal，触发时中止子 agent"""
                try:
                    await parent_signal.wait()
                except asyncio.CancelledError:
                    return
                sub_runtime.abort("主 agent 已中止，子 agent 一并中止")

            abort_watcher = asyncio.create_task(_watch_parent_abort())

        # 6. 运行子 agent — 对标 Cline subAgent.run(input.task)
        try:
            result: AgentRunResult = await sub_runtime.run(task)
        except Exception as e:
            logger.exception("子 agent 运行异常: %s", e)
            return AgentToolResult(
                output={"error": f"子 agent 运行失败: {e}", "task": task},
                is_error=True,
            )
        finally:
            if abort_watcher is not None and not abort_watcher.done():
                abort_watcher.cancel()

        # 7. 提取子 agent 的最终输出文本
        # 优先取最后一条 assistant 消息的文本（比工具结果 dict 更清晰）
        # 对标 Cline SpawnAgentOutput.text = result.text
        output_text = self._extract_output_text(result)

        # 构造返回给主 agent 的结果
        usage_dict: dict[str, Any] = {}
        if hasattr(result.usage, "to_dict"):
            usage_dict = result.usage.to_dict()

        return AgentToolResult(
            output={
                "task": task,
                "result": output_text,
                "iterations": result.iterations,
                "status": result.status,
                "finish_reason": result.finish_reason,
                "usage": usage_dict,
                "sub_agent_id": sub_agent_id,
            },
            metadata={
                "tool": "sub_agent",
                "sub_agent_id": sub_agent_id,
                "iterations": result.iterations,
                "finish_reason": result.finish_reason,
            },
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_output_text(result: AgentRunResult) -> str:
        """从子 agent 运行结果中提取输出文本

        优先级:
            1. 最后一条 assistant 消息的文本（通常包含子 agent 的总结）
            2. result.output_text（可能是 submit_and_exit 工具结果的字符串化 dict）
            3. 空字符串

        对标 Cline SpawnAgentOutput.text = result.text

        Args:
            result: 子 agent 的运行结果

        Returns:
            输出文本
        """
        # 优先取最后一条 assistant 消息 — 比 submit_and_exit 的 dict 输出更清晰
        for msg in reversed(result.messages):
            if msg.role == MessageRole.ASSISTANT:
                text = text_from_message(msg)
                if text.strip():
                    return text

        # 回退到 result.output_text（可能是工具结果 dict 的字符串化形式）
        return result.output_text or ""
