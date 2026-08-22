# -*- coding: utf-8 -*-
"""文件写入工具 — 对标 Cline FileWriteTool

FileWriteTool:
    - 写入文件内容，自动创建父目录
    - 对标 Cline FileWriteTool
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult


# P2-37: 输入参数字符上限 — 对标 Cline schemas.ts L10 INPUT_ARG_CHAR_LIMIT=6000
# 防止 LLM 发送超大 payload 导致写入超时，引导 LLM 拆分为多次小编辑
INPUT_ARG_CHAR_LIMIT = 6000


class FileWriteTool(BaseTool):
    """文件写入工具 — 对标 Cline FileWriteTool

    参数:
        file_path: 文件路径（必填）
        content: 文件内容（必填）
        working_dir: 工作目录（可选，用于解析相对路径，默认当前目录）
    """

    def __init__(self, working_dir: str | None = None) -> None:
        self._working_dir = working_dir or os.getcwd()

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return (
            "写入文件内容。自动创建父目录。"
            "参数: file_path(必填): 文件路径; "
            "content(必填): 文件内容"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "文件内容",
                },
            },
            "required": ["file_path", "content"],
        }

    @property
    def requires_approval(self) -> bool:
        """写入文件需要用户审批 — Phase 19"""
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        file_path = input["file_path"]
        content = input["content"]

        # P2-37: 输入参数大小检查 — 对标 Cline getEditorSizeError + INPUT_ARG_CHAR_LIMIT
        # content 超过上限时返回错误，引导 LLM 拆分为多次小编辑，避免超大 payload 超时
        if len(content) > INPUT_ARG_CHAR_LIMIT:
            return AgentToolResult(
                output={"error": (
                    f"content 过大（{len(content)} 字符），超过上限 {INPUT_ARG_CHAR_LIMIT} 字符。"
                    "请拆分为多次小写入，或使用 editor 工具的增量编辑模式。"
                )},
                is_error=True,
            )

        path = Path(file_path)
        if not path.is_absolute():
            path = Path(self._working_dir) / path

        try:
            # 自动创建父目录
            path.parent.mkdir(parents=True, exist_ok=True)

            # 写入文件 — UTF-8 编码（项目约束）
            path.write_text(content, encoding="utf-8")

            return AgentToolResult(
                output=f"文件已写入: {file_path} ({len(content)} 字符)",
                metadata={"file_path": str(path), "chars": len(content)},
            )

        except PermissionError as e:
            return AgentToolResult(
                output={"error": f"权限不足: {e}"},
                is_error=True,
            )
        except Exception as e:
            return AgentToolResult(
                output={"error": f"写入失败: {e}"},
                is_error=True,
            )
