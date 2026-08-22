# -*- coding: utf-8 -*-
"""MCP 客户端 — 对标 Cline MCP 服务连接管理

实现 JSON-RPC 2.0 over stdio / http，与 MCP 服务器通信。

支持的传输:
    1. stdio: spawn 子进程，通过 stdin/stdout 用换行分隔的 JSON-RPC 通信
    2. http: POST JSON-RPC 到 HTTP 端点

MCP 协议方法（对标 Model Context Protocol 规范）:
    - initialize: 握手，交换 capabilities
    - notifications/initialized: 通知服务器已初始化完成
    - tools/list: 列出服务器提供的工具
    - tools/call: 调用工具
    - resources/list: 列出服务器提供的资源
    - resources/read: 读取资源内容
    - shutdown: 优雅关闭
    - ping: 心跳检测

设计要点:
    - 异步 I/O: stdio 用 asyncio.subprocess，http 用 urllib
    - 请求/响应关联: 用自增 id 匹配 request 和 response
    - 超时控制: 每个请求默认 30 秒超时
    - 懒连接: 第一次调用工具时才 spawn 子进程 / 建立 HTTP 连接
    - 进程生命周期: 显式 shutdown 或析构时 kill 子进程

对标 Cline:
    - sdk/packages/core/src/services/mcp-service.ts
    - sdk/packages/core/src/extensions/tools/mcp/use-mcp-tool.ts
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# 默认请求超时（秒）
_DEFAULT_TIMEOUT = 30.0

# MCP 协议版本
_MCP_PROTOCOL_VERSION = "2024-11-05"

# 客户端名称与版本（用于 initialize 握手）
_CLIENT_NAME = "charles-agent"
_CLIENT_VERSION = "1.0.0"


# ============================================================================
# 数据类 — MCP 工具/资源定义
# ============================================================================


@dataclass
class MCPToolDef:
    """MCP 工具定义 — 对标 Cline McpToolDefinition

    Attributes:
        name: 工具名称（在服务器内唯一）
        description: 工具描述
        input_schema: 输入参数的 JSON Schema
        server_name: 所属服务器名称
    """
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPResourceDef:
    """MCP 资源定义 — 对标 Cline McpResourceDefinition

    Attributes:
        uri: 资源 URI（如 "file:///path" 或自定义 scheme）
        name: 资源名称
        description: 资源描述
        mime_type: MIME 类型（可选）
        server_name: 所属服务器名称
    """
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_name: str = ""


# ============================================================================
# MCP 客户端 — JSON-RPC 2.0 通信
# ============================================================================


class MCPClient:
    """MCP 客户端 — 管理与单个 MCP 服务器的连接

    支持两种传输方式:
        - stdio: spawn 子进程，stdin/stdout 通信
        - http: POST JSON-RPC

    生命周期:
        1. __init__: 仅保存配置，不建立连接
        2. ensure_connected(): 懒连接 + initialize 握手
        3. list_tools() / call_tool() / list_resources() / read_resource()
        4. close(): shutdown 并清理资源

    线程安全: 单个 client 实例不应被多个协程并发使用（MCP 协议是串行的）。
    多个并发请求应使用多个 client 实例，或在 registry 层加锁。
    """

    def __init__(
        self,
        server_name: str,
        transport: str,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """初始化 MCP 客户端

        Args:
            server_name: 服务器名称（用于日志和标识）
            transport: 传输方式，"stdio" 或 "http"
            command: stdio 模式下的启动命令
            args: stdio 模式下的命令参数列表
            env: stdio 模式下的额外环境变量
            url: http 模式下的服务器 URL
            headers: http 模式下的请求头
        """
        self.server_name = server_name
        self.transport = transport
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.url = url
        self.headers = headers or {}

        # 连接状态
        self._connected = False
        self._initialized = False

        # stdio 模式的子进程
        self._process: asyncio.subprocess.Process | None = None
        # 请求 id 自增计数器
        self._next_id = 1
        # stdio 模式的写锁（避免并发写入 stdin 导致消息交错）
        self._write_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """是否已建立连接并完成 initialize 握手"""
        return self._connected and self._initialized

    async def ensure_connected(self) -> None:
        """确保连接已建立 — 懒连接模式

        第一次调用时:
            1. stdio: spawn 子进程
            2. http: 无需预连接，标记为 connected
            3. 发送 initialize 请求完成握手
            4. 发送 notifications/initialized 通知
        """
        if self.is_connected:
            return

        if self.transport == "stdio":
            await self._spawn_process()
        elif self.transport == "http":
            # http 模式无需预连接，直接标记
            self._connected = True
        else:
            raise ValueError(f"不支持的传输方式: {self.transport}")

        # 发送 initialize 握手
        await self._do_initialize()
        self._initialized = True
        logger.info(f"MCP 服务器 {self.server_name} 已连接 (transport={self.transport})")

    async def _spawn_process(self) -> None:
        """spawn MCP 服务器子进程 — stdio 模式"""
        if self.command is None:
            raise ValueError("stdio 模式需要 command 参数")

        # 合并环境变量（系统 env + 配置 env）
        # API keys 应从系统环境变量读取，配置中用 ${VAR} 语法引用
        merged_env = dict(os.environ)
        for key, value in self.env.items():
            merged_env[key] = _resolve_env_value(value, merged_env)

        # Windows 兼容：npx / npm 等 Node 脚本需要 .cmd 扩展名才能直接执行
        command = self.command
        if os.name == 'nt' and not os.path.splitext(command)[1]:
            for ext in ('.cmd', '.exe', '.bat'):
                candidate = command + ext
                # 先在 PATH 中查找，找不到时回退到原命令让系统报错
                if self._is_executable_on_path(candidate, merged_env.get('PATH', '')):
                    command = candidate
                    break

        try:
            self._process = await asyncio.create_subprocess_exec(
                command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            self._connected = True
            logger.info(
                f"MCP 服务器 {self.server_name} 子进程已启动: "
                f"{command} {' '.join(self.args)}"
            )
        except Exception as e:
            raise RuntimeError(f"启动 MCP 服务器 {self.server_name} 失败: {e}") from e

    @staticmethod
    def _is_executable_on_path(name: str, path_env: str) -> bool:
        """检查可执行文件是否在 PATH 中（Windows 辅助）"""
        for directory in path_env.split(os.pathsep):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return True
        return False

    async def _do_initialize(self) -> None:
        """发送 initialize 请求完成 MCP 握手

        对标 MCP 规范 initialize 方法:
            请求: protocolVersion + capabilities + clientInfo
            响应: protocolVersion + capabilities + serverInfo
        """
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {
                    # 客户端能力声明（我们只消费工具和资源，不提供）
                    "roots": {"listChanged": False},
                },
                "clientInfo": {
                    "name": _CLIENT_NAME,
                    "version": _CLIENT_VERSION,
                },
            },
        }
        self._next_id += 1

        response = await self._send_request(request)

        if "error" in response:
            raise RuntimeError(
                f"MCP initialize 握手失败: {response['error'].get('message', 'unknown')}"
            )

        # 发送 notifications/initialized 通知（无需响应）
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await self._send_notification(notification)

    async def list_tools(self) -> list[MCPToolDef]:
        """列出服务器提供的工具 — 对标 MCP tools/list

        Returns:
            工具定义列表
        """
        await self.ensure_connected()

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
            "params": {},
        }
        self._next_id += 1

        response = await self._send_request(request)
        if "error" in response:
            raise RuntimeError(
                f"tools/list 失败: {response['error'].get('message', 'unknown')}"
            )

        result = response.get("result", {})
        tools_raw = result.get("tools", [])

        return [
            MCPToolDef(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.server_name,
            )
            for t in tools_raw
        ]

    async def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """调用 MCP 工具 — 对标 MCP tools/call

        Args:
            tool_name: 工具名称
            args: 工具参数
            timeout: 超时秒数

        Returns:
            工具执行结果，含 content / isError 字段
        """
        await self.ensure_connected()

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args or {},
            },
        }
        self._next_id += 1

        response = await self._send_request(request, timeout=timeout)

        if "error" in response:
            err = response["error"]
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"MCP 错误: {err.get('message', 'unknown')}"}],
                "error_code": err.get("code"),
            }

        return response.get("result", {})

    async def list_resources(self) -> list[MCPResourceDef]:
        """列出服务器提供的资源 — 对标 MCP resources/list

        Returns:
            资源定义列表
        """
        await self.ensure_connected()

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "resources/list",
            "params": {},
        }
        self._next_id += 1

        response = await self._send_request(request)
        if "error" in response:
            # 部分服务器不支持 resources，返回空列表
            err_msg = response["error"].get("message", "")
            logger.debug(f"MCP {self.server_name} resources/list 失败: {err_msg}")
            return []

        result = response.get("result", {})
        resources_raw = result.get("resources", [])

        return [
            MCPResourceDef(
                uri=r.get("uri", ""),
                name=r.get("name", ""),
                description=r.get("description", ""),
                mime_type=r.get("mimeType", ""),
                server_name=self.server_name,
            )
            for r in resources_raw
        ]

    async def read_resource(
        self,
        uri: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """读取 MCP 资源内容 — 对标 MCP resources/read

        Args:
            uri: 资源 URI

        Returns:
            资源内容，含 contents 字段
        """
        await self.ensure_connected()

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "resources/read",
            "params": {"uri": uri},
        }
        self._next_id += 1

        response = await self._send_request(request, timeout=timeout)

        if "error" in response:
            err = response["error"]
            return {
                "isError": True,
                "contents": [],
                "error": err.get("message", "unknown"),
            }

        return response.get("result", {})

    async def ping(self) -> bool:
        """心跳检测 — 对标 MCP ping

        Returns:
            服务器是否存活
        """
        try:
            await self.ensure_connected()
            request = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "ping",
                "params": {},
            }
            self._next_id += 1
            await self._send_request(request, timeout=5.0)
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """关闭连接并清理资源"""
        if not self._connected:
            return

        # 尝试发送 shutdown 通知
        try:
            shutdown_req = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "shutdown",
                "params": {},
            }
            self._next_id += 1
            await self._send_request(shutdown_req, timeout=2.0)
        except Exception:
            pass  # shutdown 失败不影响清理

        # 终止子进程
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        self._connected = False
        self._initialized = False
        logger.info(f"MCP 服务器 {self.server_name} 已断开")

    # ========================================================================
    # JSON-RPC 传输层
    # ========================================================================

    async def _send_request(
        self,
        request: dict[str, Any],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """发送 JSON-RPC 请求并等待响应

        Args:
            request: JSON-RPC 请求对象
            timeout: 超时秒数

        Returns:
            JSON-RPC 响应对象
        """
        if self.transport == "stdio":
            return await self._send_request_stdio(request, timeout)
        elif self.transport == "http":
            return await self._send_request_http(request, timeout)
        else:
            raise ValueError(f"不支持的传输方式: {self.transport}")

    async def _send_request_stdio(
        self,
        request: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """stdio 传输：通过子进程 stdin/stdout 通信

        消息格式: 每条 JSON-RPC 消息占一行，用 \\n 分隔
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("stdio 子进程未启动")

        # 序列化请求（确保无内嵌换行）
        message = json.dumps(request, ensure_ascii=False)
        message_bytes = (message + "\n").encode("utf-8")

        async with self._write_lock:
            self._process.stdin.write(message_bytes)
            await self._process.stdin.drain()

        # 读取响应行
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"MCP 请求超时 ({timeout}s): {request.get('method')}")

        if not line:
            # 子进程可能已退出，读取 stderr 获取错误信息
            stderr_msg = ""
            if self._process.stderr:
                try:
                    err_bytes = await asyncio.wait_for(
                        self._process.stderr.read(2048),
                        timeout=1.0,
                    )
                    stderr_msg = err_bytes.decode("utf-8", errors="replace")
                except Exception:
                    pass
            raise RuntimeError(
                f"MCP 服务器 {self.server_name} 连接断开"
                + (f"，stderr: {stderr_msg}" if stderr_msg else "")
            )

        # 解析 JSON-RPC 响应
        try:
            response = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"MCP 响应不是有效 JSON: {e}, 原始: {line!r}")

        # 校验 id 匹配（MCP 服务器可能发送通知，但 readline 只读到一条）
        if response.get("id") != request.get("id"):
            # 可能是通知，递归读取下一条
            # 简单处理：记录日志并继续读下一行
            logger.debug(
                f"MCP {self.server_name} 收到非预期响应 id={response.get('id')}，"
                f"期望 id={request.get('id')}，继续读取"
            )
            return await self._send_request_stdio(request, timeout)

        return response

    async def _send_request_http(
        self,
        request: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """http 传输：POST JSON-RPC 到服务器 URL"""
        if not self.url:
            raise ValueError("http 模式需要 url 参数")

        def _do_post() -> dict[str, Any]:
            """同步 HTTP POST（在线程池中执行）"""
            data = json.dumps(request, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **self.headers,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)

        try:
            return await asyncio.to_thread(_do_post)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"MCP HTTP 请求失败: HTTP {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"MCP HTTP 请求失败: {e.reason}") from e

    async def _send_notification(self, notification: dict[str, Any]) -> None:
        """发送 JSON-RPC 通知（无 id，无响应）

        用于 notifications/initialized 等单向通知。
        """
        if self.transport == "stdio":
            if self._process is None or self._process.stdin is None:
                raise RuntimeError("stdio 子进程未启动")
            message = json.dumps(notification, ensure_ascii=False)
            message_bytes = (message + "\n").encode("utf-8")
            async with self._write_lock:
                self._process.stdin.write(message_bytes)
                await self._process.stdin.drain()
        elif self.transport == "http":
            # http 模式下通知也通过 POST 发送，但忽略响应
            try:
                await self._send_request_http(notification, timeout=5.0)
            except Exception as e:
                logger.debug(f"MCP http 通知发送失败（可忽略）: {e}")


# ============================================================================
# 辅助函数
# ============================================================================


def _resolve_env_value(value: str, env: dict[str, str]) -> str:
    """解析环境变量引用 — 对标 shell ${VAR} 语法

    配置文件中可使用 ${ENV_VAR} 引用系统环境变量，
    避免 API key 等敏感信息硬编码在配置文件中。

    Args:
        value: 配置值，可能含 ${VAR} 引用
        env: 当前环境变量字典

    Returns:
        解析后的值

    Examples:
        _resolve_env_value("${API_KEY}", {"API_KEY": "abc"}) → "abc"
        _resolve_env_value("prefix-${VAR}-suffix", {"VAR": "x"}) → "prefix-x-suffix"
        _resolve_env_value("plain_value", {}) → "plain_value"
    """
    if not isinstance(value, str) or "${" not in value:
        return value

    result = value
    # 简单实现：循环替换 ${VAR} 模式
    import re
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return env.get(var_name, match.group(0))  # 未找到则保留原样

    # 多次替换以处理嵌套引用（极少见，但安全起见）
    for _ in range(3):
        new_result = pattern.sub(replacer, result)
        if new_result == result:
            break
        result = new_result

    return result
