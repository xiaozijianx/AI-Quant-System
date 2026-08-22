# -*- coding: utf-8 -*-
"""工具系统 — 对标 Cline extensions/tools

工具是 Agent 与外部环境交互的能力:
    - RunCommandsTool: 批量执行命令行命令（对标 Cline run_commands）
    - ReadFilesTool: 批量读取文件内容（对标 Cline read_files，支持多文件+行范围）
    - FileWriteTool: 写入文件内容（对标 Cline FileWriteTool）
    - SwitchToActModeTool: 切换到 Act 模式（对标 Cline switch_to_act_mode，Phase 12 新增）
    - SwitchToPlanModeTool: 切换到 Plan 模式（对标 Cline switch_to_plan_mode，Phase 12 新增）
    - EditorTool: 行级文件编辑工具（对标 Cline createEditorTool）
    - ApplyPatchTool: diff 补丁工具（对标 Cline createApplyPatchTool）
    - SearchCodebaseTool: 正则代码搜索工具（对标 Cline createSearchTool）
    - FetchWebContentTool: URL 抓取工具（对标 Cline createWebFetchTool）
    - AskQuestionTool: 向用户提问工具（对标 Cline createAskQuestionTool）
    - ListFilesTool: 目录列表工具
    - SubmitAndExitTool: 任务完成工具（对标 Cline createSubmitAndExitTool）
    - UseMcpToolTool: 调用 MCP 服务器工具（对标 Cline use_mcp_tool，Phase 22 新增）
    - AccessMcpResourceTool: 读取 MCP 服务器资源（对标 Cline access_mcp_resource，Phase 22 新增）
    - SubAgentTool: 子 agent 工具（对标 Cline spawn_agent，创建独立子 runtime 执行委派任务）

所有工具继承 BaseTool，实现 AgentTool 协议（agent/types.py）。
"""

from agent.tools.apply_patch import ApplyPatchTool
from agent.tools.ask_question import AskQuestionTool
from agent.tools.base import BaseTool
from agent.tools.editor import EditorTool
from agent.tools.fetch_web_content import FetchWebContentTool
from agent.tools.file_tools import FileWriteTool
from agent.tools.list_files import ListFilesTool
from agent.tools.mcp import AccessMcpResourceTool, UseMcpToolTool
from agent.tools.plan_mode import (
    PLAN_MODE_PROMPT,
    SwitchToActModeTool,
    SwitchToPlanModeTool,
)
from agent.tools.read_files import ReadFilesTool
from agent.tools.run_commands import RunCommandsTool
from agent.tools.search_codebase import SearchCodebaseTool
from agent.tools.sub_agent import SubAgentTool
from agent.tools.submit_and_exit import SubmitAndExitTool



def create_default_tools(
    working_dir: str | None = None,
    session_id: str | None = None,
) -> list[BaseTool]:
    """创建默认工具集 — 对标 Cline initialize() 中的工具注册

    Phase 12 重构后的默认工具集（Cline 结构化风格 + Plan Mode）:
        - RunCommandsTool: 批量命令执行
        - ReadFilesTool: 批量文件读取（对标 Cline read_files，支持多文件+行范围）
        - FileWriteTool: 单文件写入
        - SwitchToActModeTool: 切换到 Act 模式（Phase 12 新增）
        - SwitchToPlanModeTool: 切换到 Plan 模式（Phase 12 新增）
        - EditorTool: 行级文件编辑（对标 Cline createEditorTool）
        - ApplyPatchTool: diff 补丁（对标 Cline createApplyPatchTool）
        - SearchCodebaseTool: 正则代码搜索（对标 Cline createSearchTool）
        - FetchWebContentTool: URL 抓取（对标 Cline createWebFetchTool）
        - AskQuestionTool: 向用户提问（对标 Cline createAskQuestionTool）
        - ListFilesTool: 目录列表
        - SubmitAndExitTool: 任务完成（对标 Cline createSubmitAndExitTool）
        - UseMcpToolTool: 调用 MCP 服务器工具（Phase 22 新增）
        - AccessMcpResourceTool: 读取 MCP 服务器资源（Phase 22 新增）
        - SubAgentTool: 子 agent 工具（对标 Cline spawn_agent，创建独立子 runtime）

    Args:
        working_dir: 工具执行的工作目录，默认为当前目录
        session_id: 会话 ID（用于 Plan Mode 状态隔离），
                    None 时使用默认值 "default"

    Returns:
        默认工具列表
    """
    # session_id 为空时使用默认值 — Phase 12 工具需要按会话隔离状态
    sid = session_id or "default"
    from agent.state import get_mode

    current_mode = get_mode(sid)

    tools: list[BaseTool] = [
        # 结构化工具（Phase 11）
        RunCommandsTool(working_dir=working_dir),
        ReadFilesTool(working_dir=working_dir),  # 对标 Cline read_files，支持多文件+行范围
        FileWriteTool(working_dir=working_dir),
        # 代码编辑与搜索工具（对标 Cline 工具集）
        EditorTool(working_dir=working_dir),
        ApplyPatchTool(working_dir=working_dir),
        SearchCodebaseTool(working_dir=working_dir),
        FetchWebContentTool(),
        AskQuestionTool(),
        ListFilesTool(working_dir=working_dir),
        SubmitAndExitTool(),
        # MCP 服务器工具（Phase 22 新增，对标 Cline use_mcp_tool / access_mcp_resource）
        # 无配置服务器时也可注册，agent 调用会返回"无可用服务器"提示
        UseMcpToolTool(),
        AccessMcpResourceTool(),
        # 子 agent 工具（对标 Cline spawn_agent，创建独立子 runtime 执行委派任务）
        SubAgentTool(working_dir=working_dir),
    ]

    # 模式切换工具：Plan 模式下需要切换到 Act，Act 模式下需要切换回 Plan
    tools.append(SwitchToActModeTool(session_id=sid))
    tools.append(SwitchToPlanModeTool(session_id=sid))

    return tools


__all__ = [
    "BaseTool",
    "RunCommandsTool",
    "ReadFilesTool",
    "FileWriteTool",
    "SwitchToActModeTool",
    "SwitchToPlanModeTool",
    "PLAN_MODE_PROMPT",
    "EditorTool",
    "ApplyPatchTool",
    "SearchCodebaseTool",
    "FetchWebContentTool",
    "AskQuestionTool",
    "ListFilesTool",
    "SubmitAndExitTool",
    "UseMcpToolTool",
    "AccessMcpResourceTool",
    "SubAgentTool",
    "create_default_tools",
]
