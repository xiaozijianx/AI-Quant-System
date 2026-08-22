# -*- coding: utf-8 -*-
"""MCP 模块 — 对标 Cline mcp 集成

提供 MCP (Model Context Protocol) 客户端能力，让 AI agent 可以调用
外部 MCP 服务器的工具和资源。

模块结构:
    - client.py: MCPClient，JSON-RPC 2.0 over stdio/http 通信
    - registry.py: MCPRegistry，服务器配置加载与连接管理

工作流程:
    1. 启动时 MCPRegistry 从 agent_config/mcp_servers.yaml 加载配置
    2. agent 调用 use_mcp_tool(server_name, tool_name, args)
    3. MCPRegistry 按需初始化对应 MCPClient（lazy connect）
    4. MCPClient 通过 JSON-RPC 调用 tools/call
    5. 结果返回给 agent

对标 Cline:
    - sdk/packages/core/src/extensions/tools/mcp/use-mcp-tool.ts
    - sdk/packages/core/src/extensions/tools/mcp/access-mcp-resource.ts
    - sdk/packages/core/src/services/mcp-service.ts
"""

from agent.mcp.client import MCPClient, MCPToolDef, MCPResourceDef
from agent.mcp.registry import MCPRegistry, get_registry

__all__ = [
    "MCPClient",
    "MCPToolDef",
    "MCPResourceDef",
    "MCPRegistry",
    "get_registry",
]
