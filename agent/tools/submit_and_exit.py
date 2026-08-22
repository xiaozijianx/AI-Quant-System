# -*- coding: utf-8 -*-
"""任务完成工具 — 对标 Cline createSubmitAndExitTool

提交最终答案并结束对话。工具执行后 runtime 检测到
lifecycle.completes_run=True 后结束运行。

工作流程:
    1. Agent 完成调查任务后调用 submit_and_exit(summary="...", verified=true)
    2. 工具返回 AgentToolResult(output={summary, verified, status})
    3. AgentRuntime 检测到 lifecycle.completes_run=True
    4. runtime 结束运行，将 summary 作为最终结果返回

关键设计:
    - lifecycle.completes_run = True: 执行成功后直接结束运行
    - summary 至少 10 字符，避免空结果
    - verified 标记是否已验证结果

对标 Cline:
    - sdk/packages/core/src/extensions/tools/submit-and-exit-tool.ts
"""

from __future__ import annotations

from typing import Any

from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult, ToolLifecycle


class SubmitAndExitTool(BaseTool):
    """任务完成工具 — 对标 Cline createSubmitAndExitTool

    lifecycle.completes_run = True
    提交最终答案后 runtime 结束运行。

    参数:
        summary: 调查总结（必填，至少 10 字符）
        verified: 是否已验证（必填）
    """

    @property
    def name(self) -> str:
        return "submit_and_exit"

    @property
    def description(self) -> str:
        return (
            "提交最终答案并结束对话。"
            "参数: summary(必填): 调查总结（至少10字符）; "
            "verified(必填): 是否已验证"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "minLength": 10,
                    "description": "调查总结（至少 10 字符）",
                },
                "verified": {
                    "type": "boolean",
                    "description": "是否已验证结果",
                },
            },
            "required": ["summary", "verified"],
        }

    @property
    def lifecycle(self) -> ToolLifecycle:
        """生命周期标记 — completes_run=True

        对标 Cline submit_and_exit 工具的 lifecycle.completes_run。
        AgentRuntime._find_completing_tool() 检测此标记后结束运行。
        """
        return ToolLifecycle(completes_run=True)

    @property
    def read_only(self) -> bool:
        # 终止性工具，不修改文件，标记为 False 以符合规范
        return False

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """提交最终答案 — runtime 检测 completes_run 后结束运行"""
        summary = input["summary"]
        verified = input["verified"]

        return AgentToolResult(
            output={
                "summary": summary,
                "verified": verified,
                "status": "任务完成",
            },
            metadata={
                "tool": "submit_and_exit",
                "completed": True,
                "verified": verified,
            },
        )
