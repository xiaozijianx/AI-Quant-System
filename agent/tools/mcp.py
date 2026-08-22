# -*- coding: utf-8 -*-
"""MCP 工具 — 对标 Cline MCP 工具集成

提供以下工具让 AI agent 调用 MCP 服务器:
    1. use_mcp_tool: 调用 MCP 服务器的工具，传入 server_name + tool_name + args
       对标 Cline createUseMcpToolTool
    2. access_mcp_resource: 读取 MCP 服务器的资源，传入 server_name + uri
       对标 Cline createAccessMcpResourceTool

对标 Cline:
    - sdk/packages/core/src/extensions/tools/mcp/use-mcp-tool.ts
    - sdk/packages/core/src/extensions/tools/mcp/access-mcp-resource.ts
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.mcp.registry import get_registry
from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)


# ============================================================================
# use_mcp_tool 工具
# ============================================================================


class UseMcpToolTool(BaseTool):
    """use_mcp_tool 工具 — 对标 Cline createUseMcpToolTool

    调用 MCP 服务器的工具。

    参数:
        server_name: MCP 服务器名称（必填）
        tool_name: 要调用的工具名称（必填）
        args: 工具参数对象（可选，默认空对象）

    示例:
        use_mcp_tool(
            server_name="filesystem",
            tool_name="read_file",
            args={"path": "/tmp/test.txt"}
        )
    """

    # MCP 工具调用超时（秒）— MCP 工具可能执行较久（如 tavily 首次下载/网络慢）
    _CALL_TIMEOUT = 120.0

    @property
    def name(self) -> str:
        return "use_mcp_tool"

    @property
    def description(self) -> str:
        return (
            "调用 MCP 服务器的工具。"
            "MCP (Model Context Protocol) 服务器提供外部能力扩展。"
            "参数: server_name(必填): MCP 服务器名称; "
            "tool_name(必填): 要调用的工具名称; "
            "args(可选): 工具参数对象，默认空对象"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server_name": {
                    "type": "string",
                    "description": "MCP 服务器名称（在 mcp_servers.yaml 中配置）",
                },
                "tool_name": {
                    "type": "string",
                    "description": "要调用的工具名称",
                },
                "args": {
                    "type": "object",
                    "description": "工具参数对象（JSON Schema 由具体工具定义）",
                    "default": {},
                },
            },
            "required": ["server_name", "tool_name"],
        }

    @property
    def read_only(self) -> bool:
        # MCP 工具可能是写操作，但工具本身不修改本地状态，标记为 read_only
        # 让 runtime 可以并行调用多个 MCP 工具
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行 MCP 工具调用"""
        server_name = input.get("server_name", "").strip()
        tool_name = input.get("tool_name", "").strip()
        args = input.get("args") or {}

        if not server_name:
            return AgentToolResult(
                output={"error": "server_name 不能为空"},
                is_error=True,
            )
        if not tool_name:
            return AgentToolResult(
                output={"error": "tool_name 不能为空"},
                is_error=True,
            )

        # 获取 MCP 注册表
        registry = get_registry()

        # 校验服务器是否存在
        server_config = registry.get_server(server_name)
        if server_config is None:
            available = [s.name for s in registry.list_servers()]
            return AgentToolResult(
                output={
                    "error": f"MCP 服务器不存在或未启用: {server_name}",
                    "available_servers": available,
                    "hint": "在 agent_config/mcp_servers.yaml 中配置 MCP 服务器",
                },
                is_error=True,
            )

        # 调用 MCP 工具
        try:
            result = await registry.call_tool(
                server_name=server_name,
                tool_name=tool_name,
                args=args if isinstance(args, dict) else {},
                timeout=self._CALL_TIMEOUT,
            )
        except Exception as e:
            return AgentToolResult(
                output={
                    "error": f"MCP 工具调用异常: {e}",
                    "server_name": server_name,
                    "tool_name": tool_name,
                },
                is_error=True,
            )

        # 解析 MCP 结果格式
        # MCP tools/call 返回: {content: [{type: "text", text: "..."}], isError: bool}
        is_error = result.get("isError", False)
        content = result.get("content", [])

        # 提取文本内容
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                else:
                    # 非 text 类型（如 image/resource），保留 JSON 表示
                    text_parts.append(json.dumps(item, ensure_ascii=False))
            else:
                text_parts.append(str(item))

        output_text = "\n".join(text_parts) if text_parts else "(MCP 工具无输出)"

        return AgentToolResult(
            output={
                "server_name": server_name,
                "tool_name": tool_name,
                "result": output_text,
                "is_error": is_error,
                "raw": result if is_error else None,  # 错误时保留原始结果用于调试
            },
            is_error=is_error,
            metadata={
                "mcp_server": server_name,
                "mcp_tool": tool_name,
                "content_items": len(content),
            },
        )


# ============================================================================
# access_mcp_resource 工具
# ============================================================================


class AccessMcpResourceTool(BaseTool):
    """access_mcp_resource 工具 — 对标 Cline createAccessMcpResourceTool

    读取 MCP 服务器的资源内容。

    参数:
        server_name: MCP 服务器名称（必填）
        uri: 资源 URI（必填，如 "file:///path/to/file"）

    示例:
        access_mcp_resource(
            server_name="filesystem",
            uri="file:///tmp/test.txt"
        )
    """

    _READ_TIMEOUT = 60.0

    @property
    def name(self) -> str:
        return "access_mcp_resource"

    @property
    def description(self) -> str:
        return (
            "读取 MCP 服务器的资源内容。"
            "资源是 MCP 服务器提供的可读数据（如文件、数据库记录等）。"
            "参数: server_name(必填): MCP 服务器名称; "
            "uri(必填): 资源 URI（如 file:///path/to/file）"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server_name": {
                    "type": "string",
                    "description": "MCP 服务器名称",
                },
                "uri": {
                    "type": "string",
                    "description": "资源 URI（如 file:///path/to/file 或自定义 scheme）",
                },
            },
            "required": ["server_name", "uri"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行 MCP 资源读取"""
        server_name = input.get("server_name", "").strip()
        uri = input.get("uri", "").strip()

        if not server_name:
            return AgentToolResult(
                output={"error": "server_name 不能为空"},
                is_error=True,
            )
        if not uri:
            return AgentToolResult(
                output={"error": "uri 不能为空"},
                is_error=True,
            )

        registry = get_registry()

        # 校验服务器是否存在
        server_config = registry.get_server(server_name)
        if server_config is None:
            available = [s.name for s in registry.list_servers()]
            return AgentToolResult(
                output={
                    "error": f"MCP 服务器不存在或未启用: {server_name}",
                    "available_servers": available,
                },
                is_error=True,
            )

        # 读取 MCP 资源
        try:
            result = await registry.read_resource(
                server_name=server_name,
                uri=uri,
                timeout=self._READ_TIMEOUT,
            )
        except Exception as e:
            return AgentToolResult(
                output={
                    "error": f"MCP 资源读取异常: {e}",
                    "server_name": server_name,
                    "uri": uri,
                },
                is_error=True,
            )

        # 解析 MCP resources/read 返回格式
        # {contents: [{uri, mimeType, text/blob}]}
        is_error = result.get("isError", False)
        if is_error:
            return AgentToolResult(
                output={
                    "error": result.get("error", "MCP 资源读取失败"),
                    "server_name": server_name,
                    "uri": uri,
                },
                is_error=True,
            )

        contents = result.get("contents", [])
        text_parts: list[str] = []
        for item in contents:
            if not isinstance(item, dict):
                text_parts.append(str(item))
                continue
            if "text" in item:
                text_parts.append(item["text"])
            elif "blob" in item:
                # blob 是 base64 编码的二进制数据，保留前 200 字符
                blob = item["blob"]
                if isinstance(blob, str) and len(blob) > 200:
                    text_parts.append(f"[blob data, {len(blob)} chars, 前 200: {blob[:200]}]")
                else:
                    text_parts.append(f"[blob: {blob}]")
            else:
                text_parts.append(json.dumps(item, ensure_ascii=False))

        output_text = "\n".join(text_parts) if text_parts else "(MCP 资源无内容)"

        return AgentToolResult(
            output={
                "server_name": server_name,
                "uri": uri,
                "content": output_text,
                "items_count": len(contents),
            },
            metadata={
                "mcp_server": server_name,
                "mcp_resource_uri": uri,
            },
        )
