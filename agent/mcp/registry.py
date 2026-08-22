# -*- coding: utf-8 -*-
"""MCP 服务器注册表 — 对标 Cline mcpService

管理多个 MCP 服务器的配置加载、客户端连接、工具/资源缓存。

职责:
    1. 从 agent_config/mcp_servers.yaml 加载服务器配置
    2. 按需创建 MCPClient 实例（lazy init）
    3. 缓存工具列表和资源列表（避免每次调用都 list）
    4. 提供统一接口: list_servers / list_tools / call_tool / list_resources / read_resource
    5. 关闭时统一清理所有客户端

线程安全:
    - 客户端实例按服务器名隔离，不同服务器可并发调用
    - 同一服务器的并发调用通过 _client_lock 串行化（MCP 协议是串行的）

对标 Cline:
    - sdk/packages/core/src/services/mcp-service.ts
    - sdk/packages/core/src/extensions/tools/mcp/mcp-tool-factory.ts
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.mcp.client import MCPClient, MCPResourceDef, MCPToolDef

logger = logging.getLogger(__name__)


# ============================================================================
# 配置数据类
# ============================================================================


@dataclass
class MCPServerConfig:
    """MCP 服务器配置 — 从 mcp_servers.yaml 加载

    Attributes:
        name: 服务器唯一标识
        transport: 传输方式 (stdio / http)
        enabled: 是否启用
        description: 服务器用途说明（注入 system prompt）
        command: stdio 模式的启动命令
        args: stdio 模式的命令参数
        env: stdio 模式的环境变量
        url: http 模式的服务器 URL
        headers: http 模式的请求头
        auto_approve: P1-19 自动批准的工具名列表（对标 Cline McpServer.autoApprove）
                     列表中的工具调用时跳过用户审批，直接执行。
    """
    name: str
    transport: str = "stdio"
    enabled: bool = True
    description: str = ""
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    auto_approve: list[str] | None = None


@dataclass
class MCPToolPolicy:
    """MCP 工具策略 — 对标 Cline shared/llms/tools.ts ToolPolicy

    Phase 3.8 (Q8): per-tool 粒度策略，支持禁用工具和强制审批。

    Attributes:
        server_name: 服务器名
        tool_name: 工具名
        enabled: 是否启用（默认 True；False 表示完全禁用）
        auto_approve: 是否自动批准（默认 True；False 表示需用户批准）
    """
    server_name: str
    tool_name: str
    enabled: bool = True
    auto_approve: bool = True


# ============================================================================
# MCP 注册表 — 全局单例
# ============================================================================


class MCPRegistry:
    """MCP 服务器注册表 — 管理所有 MCP 服务器连接

    用法:
        registry = get_registry()
        registry.load_config()  # 启动时加载配置

        # agent 调用
        tools = await registry.list_tools("filesystem")
        result = await registry.call_tool("filesystem", "read_file", {"path": "..."})

        # 关闭时
        await registry.close_all()
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        """初始化注册表

        Args:
            config_path: 配置文件路径，默认 agent_config/mcp_servers.yaml
        """
        if config_path is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            config_path = project_root / "agent_config" / "mcp_servers.yaml"
        self._config_path = Path(config_path)

        # 服务器配置: name → MCPServerConfig
        self._configs: dict[str, MCPServerConfig] = {}
        # 客户端实例: name → MCPClient（懒创建）
        self._clients: dict[str, MCPClient] = {}
        # 每个服务器的锁: name → threading.Lock（串行化同服务器调用）
        self._client_locks: dict[str, asyncio.Lock] = {}
        # 工具列表缓存: name → list[MCPToolDef]
        self._tools_cache: dict[str, list[MCPToolDef]] = {}
        # 资源列表缓存: name → list[MCPResourceDef]
        self._resources_cache: dict[str, list[MCPResourceDef]] = {}
        # Phase 3.8 (Q8): per-tool 策略缓存 — 对标 Cline policies.ts
        # key: (server_name, tool_name) → MCPToolPolicy
        self._tool_policies: dict[tuple[str, str], MCPToolPolicy] = {}
        # 是否已加载配置
        self._loaded = False

    @property
    def config_path(self) -> Path:
        """配置文件路径"""
        return self._config_path

    def load_config(self) -> int:
        """从 YAML 文件加载 MCP 服务器配置

        Returns:
            已加载的服务器数量（enabled=True 的）
        """
        self._configs.clear()
        # Phase 3.8: 清空策略缓存
        self._tool_policies.clear()
        self._loaded = True

        if not self._config_path.exists():
            logger.info(f"MCP 配置文件不存在: {self._config_path}，跳过加载")
            return 0

        try:
            import yaml
        except ImportError:
            logger.warning("未安装 PyYAML，无法加载 MCP 配置文件")
            return 0

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}", exc_info=True)
            return 0

        servers_raw = data.get("servers", []) or []
        enabled_count = 0

        for srv in servers_raw:
            if not isinstance(srv, dict):
                continue
            name = srv.get("name", "").strip()
            if not name:
                logger.warning(f"MCP 配置项缺少 name 字段，跳过: {srv}")
                continue

            config = MCPServerConfig(
                name=name,
                transport=srv.get("transport", "stdio"),
                enabled=srv.get("enabled", True),
                description=srv.get("description", ""),
                command=srv.get("command"),
                args=srv.get("args"),
                env=srv.get("env"),
                url=srv.get("url"),
                headers=srv.get("headers"),
                auto_approve=srv.get("auto_approve"),
            )

            # 校验配置完整性
            if config.transport == "stdio" and not config.command:
                logger.warning(f"MCP 服务器 {name}: stdio 模式缺少 command，跳过")
                continue
            if config.transport == "http" and not config.url:
                logger.warning(f"MCP 服务器 {name}: http 模式缺少 url，跳过")
                continue

            self._configs[name] = config
            if config.enabled:
                enabled_count += 1
                logger.info(f"MCP 服务器已配置: {name} (transport={config.transport})")

            # P1-19: 记录 auto_approve 列表加载情况 — 对标 Cline autoApprove
            if config.auto_approve:
                logger.info(
                    f"MCP 服务器 {name}: auto_approve 列表已加载 "
                    f"({len(config.auto_approve)} 个工具)"
                )

        # Phase 3.8 (Q8): 加载 tool_policies 段 — 对标 Cline policies.ts
        policies_raw = data.get("tool_policies", []) or []
        for policy in policies_raw:
            if not isinstance(policy, dict):
                continue
            server = (policy.get("server") or "").strip()
            tool = (policy.get("tool") or "").strip()
            if not server or not tool:
                logger.warning(f"MCP tool_policy 缺少 server/tool 字段，跳过: {policy}")
                continue
            self._tool_policies[(server, tool)] = MCPToolPolicy(
                server_name=server,
                tool_name=tool,
                enabled=policy.get("enabled", True),
                auto_approve=policy.get("auto_approve", True),
            )
            logger.info(
                f"MCP tool_policy 已加载: {server}/{tool} "
                f"(enabled={policy.get('enabled', True)}, "
                f"auto_approve={policy.get('auto_approve', True)})"
            )

        if enabled_count > 0:
            logger.info(f"MCP 配置加载完成: {enabled_count} 个服务器已启用")
        return enabled_count

    def list_servers(self) -> list[MCPServerConfig]:
        """列出所有已配置的服务器（仅 enabled 的）"""
        if not self._loaded:
            self.load_config()
        return [c for c in self._configs.values() if c.enabled]

    def get_server(self, name: str) -> MCPServerConfig | None:
        """获取服务器配置"""
        if not self._loaded:
            self.load_config()
        config = self._configs.get(name)
        if config is None or not config.enabled:
            return None
        return config

    def get_client(self, name: str) -> MCPClient:
        """获取或创建 MCP 客户端 — 懒创建

        第一次调用时创建客户端实例，后续复用。
        客户端实例的 ensure_connected() 也是懒连接。

        Args:
            name: 服务器名称

        Returns:
            MCPClient 实例

        Raises:
            KeyError: 服务器未配置或未启用
        """
        config = self.get_server(name)
        if config is None:
            raise KeyError(f"MCP 服务器未配置或未启用: {name}")

        if name not in self._clients:
            client = MCPClient(
                server_name=config.name,
                transport=config.transport,
                command=config.command,
                args=config.args,
                env=config.env,
                url=config.url,
                headers=config.headers,
            )
            self._clients[name] = client
            self._client_locks[name] = asyncio.Lock()

        return self._clients[name]

    async def list_tools(self, server_name: str, refresh: bool = False) -> list[MCPToolDef]:
        """列出服务器的工具列表 — 带缓存

        Args:
            server_name: 服务器名称
            refresh: 是否强制刷新缓存

        Returns:
            工具定义列表
        """
        # 检查缓存
        if not refresh and server_name in self._tools_cache:
            return self._tools_cache[server_name]

        # 先确保客户端已创建（懒初始化），否则 _client_locks 不存在
        try:
            self.get_client(server_name)
        except KeyError:
            # 服务器未配置或未启用
            return []

        lock = self._client_locks.get(server_name)
        if lock is None:
            return []

        async with lock:
            client = self.get_client(server_name)
            try:
                tools = await client.list_tools()
                self._tools_cache[server_name] = tools
                return tools
            except Exception as e:
                logger.error(f"MCP {server_name} list_tools 失败: {e}", exc_info=True)
                return []

    async def list_all_tools(self) -> list[MCPToolDef]:
        """列出所有服务器的所有工具 — 聚合

        Returns:
            所有服务器工具的列表，每项含 server_name 字段
        """
        all_tools: list[MCPToolDef] = []
        for server in self.list_servers():
            tools = await self.list_tools(server.name)
            all_tools.extend(tools)
        return all_tools

    def get_tool_policy(
        self,
        server_name: str,
        tool_name: str,
    ) -> MCPToolPolicy | None:
        """查询 per-tool 策略 — 对标 Cline runtime 查询 toolPolicies

        Phase 3.8 (Q8): 调用方（UseMcpToolTool）在调用前查询策略。

        Args:
            server_name: 服务器名
            tool_name: 工具名

        Returns:
            MCPToolPolicy 实例（若配置存在），None 表示无策略（默认全部允许）
        """
        if not self._loaded:
            self.load_config()
        return self._tool_policies.get((server_name, tool_name))

    def is_tool_auto_approved(
        self,
        server_name: str,
        tool_name: str,
    ) -> bool:
        """查询工具是否在服务器的 auto_approve 列表中 — P1-19 新增

        对标 Cline McpHub.listTools: 从 mcp_settings 读取 autoApprove 数组，
        列表中的工具标记为 autoApprove=true，调用时跳过用户审批。

        与 get_tool_policy 的区别:
            - get_tool_policy 查询 tool_policies 段的 per-server/tool 策略
            - is_tool_auto_approved 查询 servers 段的 per-server auto_approve 列表
            两者互补，优先级见 runtime._get_mcp_tool_policy_override

        Args:
            server_name: 服务器名
            tool_name: 工具名

        Returns:
            True 表示工具在 auto_approve 列表中，应跳过审批；
            False 表示不在列表中，按默认审批逻辑处理
        """
        if not self._loaded:
            self.load_config()
        config = self._configs.get(server_name)
        if config is None:
            return False
        auto_approve_list = config.auto_approve
        if not auto_approve_list:
            return False
        return tool_name in auto_approve_list

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """调用 MCP 工具

        Phase 3.8 (Q8): 调用前查询 per-tool 策略，enabled=False 拒绝执行。
        auto_approve=False 由调用方（UseMcpToolTool）处理。

        Args:
            server_name: 服务器名称
            tool_name: 工具名称
            args: 工具参数
            timeout: 超时秒数（MCP 工具可能执行较久，默认 60s）

        Returns:
            工具执行结果

        Raises:
            KeyError: 服务器未配置
            RuntimeError: 工具调用失败
        """
        # Phase 3.8 (Q8): 策略查询 — 对标 Cline runtime enabled: false 跳过执行
        policy = self.get_tool_policy(server_name, tool_name)
        if policy is not None and not policy.enabled:
            logger.warning(f"MCP 工具 {server_name}/{tool_name} 已被策略禁用")
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": f"MCP 工具 {server_name}/{tool_name} 已被策略禁用（enabled=false）",
                }],
            }

        lock = self._client_locks.get(server_name)
        if lock is None:
            raise KeyError(f"MCP 服务器未配置: {server_name}")

        async with lock:
            client = self.get_client(server_name)
            try:
                return await client.call_tool(tool_name, args, timeout=timeout)
            except Exception as e:
                logger.error(
                    f"MCP {server_name}/{tool_name} 调用失败: {e}",
                    exc_info=True,
                )
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"MCP 工具调用失败: {e}"}],
                }

    async def list_resources(self, server_name: str, refresh: bool = False) -> list[MCPResourceDef]:
        """列出服务器的资源列表 — 带缓存"""
        if not refresh and server_name in self._resources_cache:
            return self._resources_cache[server_name]

        # 先确保客户端已创建（懒初始化），否则 _client_locks 不存在
        try:
            self.get_client(server_name)
        except KeyError:
            return []

        lock = self._client_locks.get(server_name)
        if lock is None:
            return []

        async with lock:
            client = self.get_client(server_name)
            try:
                resources = await client.list_resources()
                self._resources_cache[server_name] = resources
                return resources
            except Exception as e:
                logger.error(f"MCP {server_name} list_resources 失败: {e}", exc_info=True)
                return []

    async def read_resource(
        self,
        server_name: str,
        uri: str,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """读取 MCP 资源

        Args:
            server_name: 服务器名称
            uri: 资源 URI

        Returns:
            资源内容
        """
        lock = self._client_locks.get(server_name)
        if lock is None:
            raise KeyError(f"MCP 服务器未配置: {server_name}")

        async with lock:
            client = self.get_client(server_name)
            try:
                return await client.read_resource(uri, timeout=timeout)
            except Exception as e:
                logger.error(
                    f"MCP {server_name}/read_resource({uri}) 失败: {e}",
                    exc_info=True,
                )
                return {
                    "isError": True,
                    "contents": [],
                    "error": str(e),
                }

    async def close_all(self) -> None:
        """关闭所有客户端连接 — 在服务停止时调用"""
        for name, client in list(self._clients.items()):
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"关闭 MCP 客户端 {name} 失败: {e}")
        self._clients.clear()
        self._client_locks.clear()
        self._tools_cache.clear()
        self._resources_cache.clear()
        logger.info("所有 MCP 客户端已关闭")

    def build_servers_summary(self) -> str:
        """构建 MCP 服务器概览文本 — 注入 system prompt

        格式:
            # 可用 MCP 服务器

            ## server_name (transport)
            description

            可用工具:
            - tool_name: tool_description
            ...

        Returns:
            概览文本，无服务器时返回空字符串
        """
        servers = self.list_servers()
        if not servers:
            return ""

        parts = ["# 可用 MCP 服务器\n"]
        parts.append(
            "通过 use_mcp_tool(server_name, tool_name, args) 调用 MCP 工具，"
            "通过 access_mcp_resource(server_name, uri) 读取 MCP 资源。\n"
        )

        # 尝试加载工具列表（同步上下文中无法 await，用缓存的工具列表）
        for srv in servers:
            transport_note = f" ({srv.transport})" if srv.transport != "stdio" else ""
            parts.append(f"## {srv.name}{transport_note}")
            if srv.description:
                parts.append(srv.description)

            cached_tools = self._tools_cache.get(srv.name, [])
            if cached_tools:
                parts.append("可用工具:")
                for tool in cached_tools:
                    desc = (tool.description or "").split("\n")[0][:80]
                    parts.append(f"- {tool.name}: {desc}")
            else:
                parts.append("(工具列表未加载，调用 use_mcp_tool 时自动加载)")
            parts.append("")

        return "\n".join(parts)


# ============================================================================
# 全局单例
# ============================================================================

# 全局注册表实例 — 进程内共享
_registry: MCPRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> MCPRegistry:
    """获取全局 MCP 注册表单例 — 线程安全

    第一次调用时创建实例并加载配置。
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = MCPRegistry()
                _registry.load_config()
    return _registry


# 导入 asyncio（用于类型注解，放最后避免循环导入）
import asyncio  # noqa: E402
