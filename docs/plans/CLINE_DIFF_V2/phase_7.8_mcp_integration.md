# Phase 7.8 MCP 集成对比

> 对比范围：Cline `sdk/packages/core/src/extensions/mcp/` 的 MCP 集成体系（服务器管理 / 工具加载 / 工具调用 / 配置管理 / 策略与命名空间）与 Charles `agent/mcp/` + `agent/tools/mcp.py` + `agent/runtime.py` 的 MCP 集成体系逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段聚焦"MCP 集成架构"维度，与 P3.19（MCP 工具对比，侧重 first-class vs 调度器范式）形成互补：P3.19 侧重工具暴露方式的范式差异，P7.8 侧重集成链路的四个核心环节（服务器管理 / 工具加载 / 工具调用 / 配置）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/index.ts`（L1-70，模块导出入口）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/types.ts`（L1-135，McpToolDescriptor / McpToolProvider / McpManager / McpServerTransportConfig / McpServerOAuthState / McpServerClient 接口）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/client.ts`（L1-579，StdioMcpClient + SdkUrlMcpClient + createDefaultMcpServerClientFactory）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/manager.ts`（L1-260，InMemoryMcpManager — 连接池 + 工具缓存 TTL + runExclusive 串行锁）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/tools.ts`（L1-47，createMcpTools — first-class 工具工厂）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/policies.ts`（L1-47，createDisabledMcpToolPolicy — 按 name-transform 后的工具名生成策略）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/name-transform.ts`（L1-35，defaultMcpToolNameTransform — SHA1 hash + 64 字符截断）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/config-loader.ts`（L1-828，mcpSettings.json 加载 + 跨进程文件锁 + 原子写 + Zod 校验 + OAuth 状态持久化）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/oauth.ts`（L1-100+，authorizeMcpServerOAuth — 浏览器 OAuth 流 + 本地回调服务器）
> - `third_party/cline/sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts`（L1-260，插件 MCP 服务器规范化 + env.fromEnv 注入）
> - `third_party/cline/sdk/packages/core/src/runtime/tools/tool-approval.ts`（L1-80+，requestDesktopToolApproval — 文件 IPC 审批）
>
> Charles 源码：
> - `agent/mcp/__init__.py`（L1-33，模块导出入口）
> - `agent/mcp/client.py`（L1-642，MCPClient — JSON-RPC over stdio/http + MCPToolDef / MCPResourceDef）
> - `agent/mcp/registry.py`（L1-528，MCPRegistry + MCPServerConfig + MCPToolPolicy + get_registry 单例）
> - `agent/mcp/name_transform.py`（L1-79，default_mcp_tool_name_transform — 工具函数，未在 registry 中强制应用）
> - `agent/tools/mcp.py`（L1-352，UseMcpToolTool / AccessMcpResourceTool — 调度器模式入口）
> - `agent/runtime.py` L1543-1644（_get_mcp_tool_policy_override — 调度器侧策略查询与注入）
> - `agent_config/mcp_servers.yaml`（L1-86，YAML 配置示例 + tool_policies 段）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 MCP 集成链路。**核心结论：Charles 的 MCP 集成在"基础协议通信 + per-tool 策略 + name-transform 算法"三个维度与 Cline 高度对齐，但在"传输协议覆盖 / OAuth 认证 / 配置可靠性 / 插件注册 / 工具暴露方式"五个维度存在显著简化。Charles 的简化是单进程 + OpenAI 兼容协议架构下的有意设计，并非缺陷。**

### 核心结论

1. **MCP 客户端实现策略不同**：Cline `client.ts` 基于 `@modelcontextprotocol/sdk` 封装（L4-5 导入 `Client` / `UnauthorizedError`），stdio 客户端手写 JSON-RPC 支持 newline + framed 双协议模式自动尝试（L158-184 attempts 数组），http/sse/streamableHttp 走 SDK 的 `SdkUrlMcpClient`（L443-570）；Charles `client.py` 完全手写 JSON-RPC，不依赖 MCP SDK，stdio 仅 newline 协议（L482-544），http 用 `urllib.request` 同步 POST + `asyncio.to_thread` 包装（L546-577）。Charles 的好处是零外部依赖，代价是不支持 framed 协议与 SSE/StreamableHttp 流式传输。

2. **工具加载与缓存机制差异**：Cline `manager.ts` L13 `DEFAULT_TOOLS_CACHE_TTL_MS = 5000` 实现 5 秒 TTL 缓存（L131-138 listTools 检查 `toolCacheUpdatedAt`），过期自动 `refreshTools`；Charles `registry.py` L276-303 `list_tools` 是永久缓存（除非 `refresh=True` 或 `close_all`），无 TTL。Cline 的 TTL 机制更适合多客户端频繁查询场景，Charles 的永久缓存适合单 agent 会话场景。

3. **工具暴露范式根本不同**：Cline `tools.ts` L16-46 `createMcpTools` 将每个 MCP 工具展开为独立 `AgentTool`（first-class LLM function），LLM 直接看到 `filesystem__read_file` 等工具；Charles `tools/mcp.py` L46-197 `UseMcpToolTool` 是单一调度器工具，LLM 调用 `use_mcp_tool(server_name, tool_name, args)` 转发。Cline 模式让 LLM 看到更细粒度的工具接口，Charles 模式让 LLM 工具列表保持稳定（不随 MCP 服务器增减而变化）。

4. **OAuth 认证完全缺失**：Cline `oauth.ts` L28-30 实现完整 OAuth 流程（本地回调服务器 + 多端口回退 1456/1457/1458 + 5 分钟超时 + token 持久化到 mcpSettings.json）；Charles 无任何 OAuth 实现，`mcp_servers.yaml` 注释 L25-26 明确说明 API key 通过 `${ENV_VAR}` 语法引用系统环境变量。这与 Charles "OpenAI 兼容协议优先" 架构一致——量化场景的 MCP 服务器多为本地 stdio 或内网 http，无需 OAuth。

5. **per-tool 策略机制已对齐**：Cline `policies.ts` L17-30 `createDisabledMcpToolPolicy` 按 `name_transform` 转换后的工具名生成 `Record<string, ToolPolicy>`，注入 `toolPolicies` map；Charles `registry.py` L67-82 `MCPToolPolicy` 按 `(server_name, tool_name)` 元组键存储（L128 `_tool_policies: dict[tuple[str, str], MCPToolPolicy]`），`runtime.py` L1596-1644 `_get_mcp_tool_policy_override` 在 use_mcp_tool 调用时查询策略并转换为 `autoApprove` / `enabled` 字段合并到 `policy_override`。两者语义等价（禁用工具 + 强制审批），实现位置不同（Cline 在工具注册时应用，Charles 在调度器侧查询）。

6. **auto_approve 消费部分对齐**：Cline 在 first-class 工具注册时（`tools.ts` + `policies.ts`）将策略注入 `toolPolicies` map，runtime 通过 `resolveToolPolicy` 统一查询；Charles `runtime.py` L1548-1551 仅在 `tool_call.tool_name == "use_mcp_tool"` 时触发 `_get_mcp_tool_policy_override`，对 `access_mcp_resource` 不消费策略。Charles 的策略消费是**调度器侧单点**，Cline 是**工具级全局**。

7. **配置可靠性差距大**：Cline `config-loader.ts` L231-261 `atomicWriteSettingsFile` 实现 tmp + rename 原子写入，L270-447 实现跨进程文件锁（mkdir + rename + stale reclaim + 10 秒超时 + 25ms 轮询），L530-551 `runPureSettingsMutator` 实现 mutator 纯度校验（双重调用对比 JSON），支持 VSCode + CLI + JetBrains 多 host 并发写；Charles `registry.py` L137-225 `load_config` 仅 PyYAML 加载 + dict 解析，无锁、无原子写、无纯度校验。Charles 单进程架构下无需跨进程锁，但缺原子写在异常退出时可能留下半写文件。

8. **plugin-server-registration 完全缺失**：Cline `plugin-server-registration.ts` L90-221 `normalizePluginMcpServerRegistration` 支持从插件注册 MCP 服务器，含 `env.fromEnv` 必填校验（L54-88 `resolvePluginMcpEnv`）+ 按 owner 去重（L223-260 `resolvePluginMcpServerRegistrations`）；Charles 无插件系统，配置文件一次性加载，无运行时动态注册。这与 Charles 单进程架构一致。

9. **name-transform 算法完全对齐**：Cline `name-transform.ts` L20-34 与 Charles `name_transform.py` L52-79 算法完全一致——SHA1 hash 前 8 位 + sanitize 非法字符为下划线 + 64 字符截断 + `mcp_tool` fallback。Charles Stage 32.3 已对齐，但当前架构下未启用（`name_transform.py` L12-16 注释明确说明 MCP 工具不作为独立 LLM function 暴露，转换函数仅作为工具函数提供）。

10. **nanobot 残留**：P7.8 范围内（`agent/mcp/` 目录 + `agent/tools/mcp.py` + `agent/runtime.py` L1543-1644 + `agent_config/mcp_servers.yaml`）共 **0 处注释残留 + 0 处实现逻辑残留**。这与 P3.19 的检查结果一致——MCP 模块是 Charles 已完全清理的模块。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| MCP 客户端协议 | 中 | 均实现 JSON-RPC 2.0 + initialize 握手 + tools/list + tools/call，但传输协议覆盖与 SDK 依赖不同 |
| 工具加载与缓存 | 中 | 均有工具缓存，但 TTL 机制不同（Cline 5s TTL vs Charles 永久） |
| 工具调用 | 高 | 均通过 MCP 协议调用，超时控制均支持 |
| OAuth 认证 | 缺失 | Cline 完整实现，Charles 不实施 |
| per-tool 策略 | 高 | 语义等价（禁用 + 强制审批），实现位置不同 |
| auto_approve 消费 | 中 | Charles 仅 use_mcp_tool 消费，Cline 全局工具消费 |
| 配置管理 | 低 | 格式不同（JSON vs YAML）+ 可靠性差距大（锁 + 原子写 + 纯度校验） |
| 插件注册 | 缺失 | Cline 有，Charles 不实施 |
| name-transform | 高 | 算法完全对齐，但 Charles 当前架构未启用 |
| 传输协议覆盖 | 低 | Cline 三种（stdio/sse/streamableHttp），Charles 两种（stdio/http） |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.8.1 | MCP 客户端 | `client.ts` StdioMcpClient（L126-434）+ SdkUrlMcpClient（L443-570），基于 `@modelcontextprotocol/sdk` | `client.py` MCPClient（L101-597），手写 JSON-RPC，不依赖 MCP SDK | 中 | Cline 支持 newline + framed 双协议自动尝试（L158-184），Charles 仅 newline。Cline http 走 SDK 的 SSEClientTransport / StreamableHTTPClientTransport，Charles 用 urllib 同步 POST + to_thread 包装。Charles 零外部依赖，代价是不支持 framed / SSE / StreamableHttp |
| 7.8.2 | 工具动态注册 | `tools.ts` L16-46 createMcpTools — 每个 MCP 工具展开为独立 AgentTool（first-class LLM function） | `tools/mcp.py` L46-197 UseMcpToolTool — 单一调度器工具，通过 use_mcp_tool(server, tool, args) 转发 | 低 | 范式根本不同。Cline 让 LLM 直接看到 N 个 MCP 工具，Charles 让 LLM 看到 1 个调度器工具。Charles 的 name_transform 未启用（注释说明） |
| 7.8.3 | OAuth 认证 | `oauth.ts` L28-30 完整 OAuth 流（本地回调服务器 + 多端口回退 + 5 分钟超时 + token 持久化）+ `config-loader.ts` L639-817 OAuth state 持久化 | 无 | 缺失 | Charles 不实施。`mcp_servers.yaml` L25-26 注释明确说明 API key 通过 ${ENV_VAR} 引用系统环境变量 |
| 7.8.4 | per-tool policies | `policies.ts` L17-30 createDisabledMcpToolPolicy — 按 name_transform 后的工具名生成 Record<string, ToolPolicy> | `registry.py` L67-82 MCPToolPolicy + L128 `_tool_policies: dict[tuple[str, str], MCPToolPolicy]` | 高 | 语义等价（禁用 + 强制审批）。Cline 按转换后工具名 key，Charles 按 (server, tool) 元组 key。Charles L201-222 load_config 时加载 tool_policies 段 |
| 7.8.5 | auto_approve 消费 | first-class 工具注册时（`tools.ts` + `policies.ts`）注入 toolPolicies map，runtime 通过 resolveToolPolicy 全局查询 | `runtime.py` L1548-1551 仅 use_mcp_tool 调用时触发 `_get_mcp_tool_policy_override`（L1596-1644），access_mcp_resource 不消费策略 | 中 | Charles 是调度器侧单点消费，Cline 是工具级全局消费。Charles L1641-1644 返回 `{autoApprove, enabled}` 合并到 policy_override |
| 7.8.6 | plugin-server-registration | `plugin-server-registration.ts` L90-221 normalizePluginMcpServerRegistration + L54-88 resolvePluginMcpEnv（fromEnv/value/required）+ L223-260 按 owner 去重 | 无 | 缺失 | Charles 不实施。单进程架构无插件系统，配置文件一次性加载 |
| 7.8.7 | name-transform | `name-transform.ts` L20-34 defaultMcpToolNameTransform — SHA1 hash 前 8 位 + sanitize + 64 字符截断 + mcp_tool fallback | `name_transform.py` L52-79 default_mcp_tool_name_transform — 算法完全一致 | 高 | Charles Stage 32.3 已对齐。但 Charles 当前架构下未启用（L12-16 注释说明 MCP 工具不作为独立 LLM function），仅作为工具函数提供 |
| 7.8.8 | config-loader | `config-loader.ts` L231-261 atomicWriteSettingsFile（tmp + rename）+ L270-447 跨进程文件锁（mkdir + rename + stale reclaim + 10s 超时）+ L530-551 mutator 纯度校验 + Zod schema 校验 | `registry.py` L137-225 load_config — PyYAML 加载 + dict 解析，无锁、无原子写 | 低 | 格式不同（JSON vs YAML）+ 可靠性差距大。Cline 支持 VSCode + CLI + JetBrains 多 host 并发写，Charles 单进程无需跨进程锁 |
| 7.8.9 | OpenAI 兼容 provider | N/A | `name_transform.py` L27-28 注释考虑 OpenAI function name 64 字符限制（Stage 32.2） | 额外增强 | Charles 的 name_transform 显式考虑 OpenAI 兼容 provider 的 64 字符限制，取 OpenAI/Anthropic 较小值 |
| 7.8.10 | 工具缓存 TTL | `manager.ts` L13 `DEFAULT_TOOLS_CACHE_TTL_MS = 5000` + L131-138 listTools 检查 TTL + L140-153 refreshTools | `registry.py` L276-303 list_tools 永久缓存（除非 refresh=True 或 close_all） | 低 | Cline 5 秒 TTL 自动刷新，Charles 永久缓存。Charles 适合单 agent 会话，Cline 适合多客户端频繁查询 |
| 7.8.11 | 连接状态机 | `manager.ts` L187-227 connectState/disconnectState — disconnected/connecting/connected 三态 + lastError + updatedAt | `client.py` L158-161 is_connected bool（_connected + _initialized） | 中 | Cline 有完整状态机 + 快照接口（McpServerSnapshot），Charles 仅 bool 标志 |
| 7.8.12 | 串行锁机制 | `manager.ts` L237-259 runExclusive — Promise 链式锁，按 serverName 隔离 | `registry.py` L121 `_client_locks: dict[str, asyncio.Lock]` + L295 `async with lock` | 高 | 两者均按 serverName 隔离串行化（MCP 协议是串行的）。Cline 用 Promise 链，Charles 用 asyncio.Lock |
| 7.8.13 | 资源读取 | `types.ts` McpServerClient 接口无 listResources/readResource（仅 listTools/callTool） | `client.py` L331-401 list_resources + read_resource + `tools/mcp.py` L205-352 AccessMcpResourceTool | 额外增强 | Charles 实现了 MCP resources/list + resources/read，Cline 的 McpServerClient 接口未定义资源方法（资源访问可能通过其他路径） |
| 7.8.14 | 心跳检测 | 无显式 ping | `client.py` L403-421 ping 方法 — 5 秒超时心跳检测 | 额外增强 | Charles 实现了 MCP ping 方法，Cline 的 StdioMcpClient 无 ping |
| 7.8.15 | 优雅关闭 | `client.ts` L192-203 disconnect — kill 子进程，无 shutdown 通知 | `client.py` L423-455 close — 发送 shutdown 请求 + terminate + kill 兜底 | 高 | Charles 实现了 MCP shutdown 通知（L429-437），Cline 直接 kill。Charles 更符合 MCP 协议规范 |
| 7.8.16 | 环境变量解析 | `plugin-server-registration.ts` L54-88 resolvePluginMcpEnv — fromEnv/value/required 三态语义 | `client.py` L605-642 _resolve_env_value — ${VAR} 语法引用系统环境变量 | 中 | 两者均支持环境变量引用，Cline 更严格（required 必填校验），Charles 更简单（未找到则保留原样） |
| 7.8.17 | stderr 缓冲 | `client.ts` L275-283 stderrBuffer 16KB 缓冲 + 错误信息附加 stderr | `client.py` L513-526 错误时读取 stderr 2048 字节 | 中 | 两者均捕获 stderr 用于错误诊断。Cline 持续缓冲 16KB，Charles 仅错误时读取 2KB |
| 7.8.18 | 协议版本 | `client.ts` L40 `MCP_PROTOCOL_VERSION = "2024-11-05"` | `client.py` L50 `_MCP_PROTOCOL_VERSION = "2024-11-05"` | 高 | 完全一致 |
| 7.8.19 | 客户端标识 | `client.ts` L171-173 `name: "@cline/core", version: "0.0.0"` | `client.py` L53-54 `_CLIENT_NAME = "charles-agent", _CLIENT_VERSION = "1.0.0"` | 高 | 两者均在 initialize 握手时声明客户端标识，仅名称不同 |

---

## 三、重点差距详解

### 3.1 MCP 客户端传输协议覆盖差距

**严重度**：P2（Charles 量化场景下影响有限，但限制 MCP 生态接入）

**Cline 实现**（`client.ts` L126-570）：

Cline 通过 `createDefaultMcpServerClientFactory`（L572-578）根据 `transport.type` 分发：
- `stdio` → `StdioMcpClient`（L126-434）：手写 JSON-RPC，支持 newline + framed 双协议模式自动尝试（L158-184 attempts 数组先 newline 后 framed）
- `sse` / `streamableHttp` → `SdkUrlMcpClient`（L443-570）：基于 `@modelcontextprotocol/sdk` 的 `SSEClientTransport` / `StreamableHTTPClientTransport`

```typescript
// client.ts L158-184 — 双协议自动尝试
const attempts: StdioProtocolMode[] = ["newline", "framed"];
let lastError: Error | undefined;
for (const protocolMode of attempts) {
    await this.disconnect().catch(() => {});
    this.spawnProcess(protocolMode);
    try {
        await this.request("initialize", {...}, MCP_CONNECT_TIMEOUT_MS);
        this.notify("notifications/initialized");
        this.connected = true;
        this.protocolMode = protocolMode;
        return;
    } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
    }
}
```

**Charles 实现**（`client.py` L101-597）：

Charles `MCPClient` 单一实现，根据 `transport` 字段分发：
- `stdio` → `_send_request_stdio`（L482-544）：仅 newline 协议，`asyncio.create_subprocess_exec` spawn 子进程
- `http` → `_send_request_http`（L546-577）：`urllib.request` 同步 POST + `asyncio.to_thread` 包装

```python
# client.py L475-480 — 单协议分发
if self.transport == "stdio":
    return await self._send_request_stdio(request, timeout)
elif self.transport == "http":
    return await self._send_request_http(request, timeout)
else:
    raise ValueError(f"不支持的传输方式: {self.transport}")
```

**对比**：
- Cline 支持 3 种传输（stdio / sse / streamableHttp），Charles 支持 2 种（stdio / http）
- Cline stdio 双协议自动尝试（newline → framed），Charles 仅 newline
- Cline http 走 SDK 的流式传输（SSE / StreamableHttp），Charles 是单次 POST（无流式）
- Cline 依赖 `@modelcontextprotocol/sdk`，Charles 零外部依赖
- Charles 的 http 模式适合内网 MCP 服务器（无流式需求），Cline 的 sse/streamableHttp 适合远程 MCP 服务器

### 3.2 工具加载与缓存机制差距

**严重度**：P3（Charles 单 agent 会话场景下影响小，但多客户端场景下缓存陈旧）

**Cline 实现**（`manager.ts` L13 + L131-153）：

Cline `InMemoryMcpManager` 实现 5 秒 TTL 缓存：

```typescript
// manager.ts L13
const DEFAULT_TOOLS_CACHE_TTL_MS = 5000;

// manager.ts L131-138 — listTools 检查 TTL
async listTools(serverName: string): Promise<readonly McpToolDescriptor[]> {
    const state = this.requireServer(serverName);
    const fetchedAt = state.toolCacheUpdatedAt ?? 0;
    if (state.toolCache && nowMs() - fetchedAt <= this.toolsCacheTtlMs) {
        return state.toolCache;
    }
    return this.refreshTools(serverName);
}

// manager.ts L140-153 — refreshTools 强制刷新
async refreshTools(serverName: string): Promise<readonly McpToolDescriptor[]> {
    return this.runExclusive(serverName, async () => {
        const state = this.requireServer(serverName);
        const client = await this.ensureConnectedClient(state);
        const tools = await client.listTools();
        const cloned = cloneTools(tools);
        state.toolCache = cloned;
        state.toolCacheUpdatedAt = nowMs();
        state.updatedAt = nowMs();
        return cloned;
    });
}
```

**Charles 实现**（`registry.py` L276-303）：

Charles `MCPRegistry` 实现永久缓存：

```python
# registry.py L276-303 — list_tools 永久缓存
async def list_tools(self, server_name: str, refresh: bool = False) -> list[MCPToolDef]:
    # 检查缓存
    if not refresh and server_name in self._tools_cache:
        return self._tools_cache[server_name]

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
```

**对比**：
- Cline 5 秒 TTL 自动刷新，保证多客户端看到的工具列表新鲜
- Charles 永久缓存，除非显式 `refresh=True` 或 `close_all`，否则永不刷新
- Charles 适合单 agent 会话（工具列表在一次会话内不变），Cline 适合多客户端频繁查询
- Charles 的 `refresh=True` 参数允许调用方主动刷新，但 `UseMcpToolTool`（`tools/mcp.py` L130-153）未使用此参数——每次调用都走缓存

### 3.3 per-tool 策略机制对比

**严重度**：P3（已对齐，仅实现位置不同）

**Cline 实现**（`policies.ts` L17-30 + `tools.ts` L16-46）：

Cline 在 first-class 工具注册时应用策略：

```typescript
// policies.ts L17-30 — 按转换后工具名生成策略
export function createDisabledMcpToolPolicy(
    options: CreateDisabledMcpToolPolicyOptions,
): Record<string, ToolPolicy> {
    const nameTransform = options.nameTransform ?? defaultMcpToolNameTransform;
    const name = nameTransform({
        serverName: options.serverName,
        toolName: options.toolName,
    });
    return {
        [name]: {
            enabled: false,
        },
    };
}

// tools.ts L16-46 — createMcpTools 注册时应用 name_transform
export async function createMcpTools(options: CreateMcpToolsOptions): Promise<AgentTool[]> {
    const descriptors = await options.provider.listTools(options.serverName);
    const nameTransform = options.nameTransform ?? defaultMcpToolNameTransform;
    return descriptors.map((descriptor) => {
        const agentToolName = nameTransform({
            serverName: options.serverName,
            toolName: descriptor.name,
        });
        return createTool({
            name: agentToolName,
            description: defaultMcpDescription(options.serverName, descriptor),
            inputSchema: descriptor.inputSchema,
            execute: async (input, context) =>
                options.provider.callTool({
                    serverName: options.serverName,
                    toolName: descriptor.name,
                    arguments: input && typeof input === "object" && !Array.isArray(input)
                        ? (input as Record<string, unknown>) : undefined,
                    context,
                }),
        });
    });
}
```

**Charles 实现**（`registry.py` L67-82 + L201-222 + `runtime.py` L1596-1644）：

Charles 在调度器侧查询策略：

```python
# registry.py L67-82 — MCPToolPolicy 数据类
@dataclass
class MCPToolPolicy:
    server_name: str
    tool_name: str
    enabled: bool = True
    auto_approve: bool = True

# registry.py L201-222 — load_config 加载 tool_policies 段
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

# runtime.py L1596-1644 — _get_mcp_tool_policy_override 调度器侧查询
def _get_mcp_tool_policy_override(self, tool_call: ToolCallPart) -> dict[str, Any]:
    input_value = tool_call.input if isinstance(tool_call.input, dict) else {}
    server_name = input_value.get("server_name", "")
    mcp_tool_name = input_value.get("tool_name", "")
    if not server_name or not mcp_tool_name:
        return {}
    try:
        from agent.mcp.registry import get_registry
        registry = get_registry()
        policy = registry.get_tool_policy(server_name, mcp_tool_name)
    except Exception as e:
        logger.warning(f"Stage 9.1: 获取 MCP 工具策略失败 ({server_name}/{mcp_tool_name}): {e}")
        return {}
    if policy is None:
        return {}
    return {
        "autoApprove": policy.auto_approve,
        "enabled": policy.enabled,
    }
```

**对比**：
- Cline 策略 key 是 `name_transform` 转换后的工具名（如 `filesystem__read_file`），与 first-class 工具注册一致
- Charles 策略 key 是 `(server_name, tool_name)` 元组，与调度器模式一致
- Cline 策略在工具注册时应用（`createMcpTools` + `createDisabledMcpToolPolicy`），runtime 通过 `resolveToolPolicy` 全局查询
- Charles 策略在 `runtime._get_mcp_tool_policy_override` 调度器侧查询，仅 `use_mcp_tool` 调用时触发
- 两者语义等价：`enabled: false` 禁用工具，`auto_approve: false` 强制审批
- Charles 的 `auto_approve` 字段（`registry.py` L82）对应 Cline 的 `ToolPolicy.autoApprove`（`shared/llms/tools.ts`）

### 3.4 配置可靠性差距

**严重度**：P2（Charles 单进程下影响有限，但异常退出时可能丢配置）

**Cline 实现**（`config-loader.ts` L231-551）：

Cline 实现三层配置可靠性机制：

1. **原子写入**（L231-261 `atomicWriteSettingsFile`）：tmp 文件 + rename，保证读者看到完整文件
2. **跨进程文件锁**（L270-447）：mkdir + rename 实现目录锁 + stale reclaim（10 秒超时强制接管）+ 25ms 轮询 + 同步/异步两种获取方式
3. **mutator 纯度校验**（L530-551 `runPureSettingsMutator`）：双重调用 mutator 对比 JSON 输出，确保无副作用

```typescript
// config-loader.ts L231-261 — 原子写入
function atomicWriteSettingsFile(filePath: string, contents: string): void {
    mkdirSync(dirname(filePath), { recursive: true });
    const tempPath = `${filePath}.tmp.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2)}`;
    try {
        writeFileSync(tempPath, contents, { encoding: "utf8", flag: "wx" });
        renameSync(tempPath, filePath);
    } catch (error) {
        try { unlinkSync(tempPath); } catch {}
        throw error;
    }
}

// config-loader.ts L530-551 — mutator 纯度校验
function runPureSettingsMutator<T>(settings, mutator): T {
    const before = JSON.stringify(settings);
    const shadow = JSON.parse(before) as Record<string, unknown>;
    const shadowResult = mutator(shadow);
    const shadowAfter = JSON.stringify(shadow);
    const result = mutator(settings);
    const after = JSON.stringify(settings);
    if (after !== shadowAfter) {
        throw new McpSettingsMutatorPurityError("...");
    }
    if (JSON.stringify(result) !== JSON.stringify(shadowResult)) {
        throw new McpSettingsMutatorPurityError("...");
    }
    return result;
}
```

**Charles 实现**（`registry.py` L137-225）：

Charles `load_config` 仅 PyYAML 加载 + dict 解析：

```python
# registry.py L152-163 — 加载配置
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
```

**对比**：
- Cline 支持 VSCode + CLI + JetBrains 多 host 并发写，Charles 单进程无需跨进程锁
- Cline 原子写入保证读者看到完整文件，Charles 无原子写入——异常退出时可能留下半写文件
- Cline mutator 纯度校验防止副作用，Charles 无此机制（Charles 的 load_config 是只读操作，无 mutator）
- Cline 用 Zod schema 校验配置结构（L39-181），Charles 用 dict.get + 类型检查（L168-198）
- Charles 的 `mcp_servers.yaml` 是只读配置（运行时不修改），Cline 的 `mcpSettings.json` 支持运行时修改（setMcpServerDisabled / updateMcpServerOAuthState）

### 3.5 OAuth 认证缺失分析

**严重度**：P3（Charles 量化场景下无需 OAuth，但限制公网 MCP 服务器接入）

**Cline 实现**（`oauth.ts` L1-100+ + `config-loader.ts` L639-817）：

Cline 实现完整 OAuth 流程：

1. **本地回调服务器**（`oauth.ts` L28-30）：默认端口 1456/1457/1458 三端口回退，5 分钟超时
2. **OAuth 客户端元数据**（`oauth.ts` L84-92）：`client_name: "Cline"`，`grant_types: ["authorization_code", "refresh_token"]`
3. **OAuth 状态持久化**（`config-loader.ts` L639-817）：`McpServerOAuthState` 含 `clientInformation` / `tokens` / `codeVerifier` / `discoveryState` / `redirectUrl` / `lastError` / `lastAuthenticatedAt`
4. **UnauthorizedError 处理**（`client.ts` L482-491）：捕获 `UnauthorizedError` 后格式化授权 URL 提示

**Charles 实现**：

Charles 完全无 OAuth 实现。`mcp_servers.yaml` L25-26 注释明确说明：

```yaml
# 安全约束:
#   - API keys 必须从系统环境变量读取，使用 ${ENV_VAR} 语法
#   - 例: api_key: ${MCP_API_KEY}  会读取 os.environ["MCP_API_KEY"]
#   - 不要在此文件直接硬编码密钥
```

**对比**：
- Cline 适合公网 MCP 服务器（如 Anthropic / GitHub 等需 OAuth 的服务）
- Charles 适合内网/本地 MCP 服务器（stdio + 内网 http，API key 通过环境变量传入）
- Charles 的 `${ENV_VAR}` 语法（`client.py` L605-642 `_resolve_env_value`）是 OAuth 的轻量替代——用环境变量管理凭据，无需 OAuth 流程
- Charles 量化场景下 MCP 服务器多为本地 stdio（如 filesystem / quant-data），无需 OAuth

### 3.6 plugin-server-registration 缺失分析

**严重度**：P3（Charles 单进程架构下无需插件系统）

**Cline 实现**（`plugin-server-registration.ts` L1-260）：

Cline 支持从插件注册 MCP 服务器：

```typescript
// plugin-server-registration.ts L54-88 — env.fromEnv 必填校验
function resolvePluginMcpEnv(server: AgentExtensionMcpServer): ResolvedPluginMcpEnv {
    const entries = server.env ? Object.entries(server.env) : [];
    if (entries.length === 0) return { ok: true };
    const env: Record<string, string> = {};
    for (const [targetName, value] of entries) {
        if (typeof value === "string") {
            env[targetName] = value;
            continue;
        }
        const sourceName = value.fromEnv?.trim() || targetName;
        const sourceValue = process.env[sourceName];
        if (typeof sourceValue === "string" && sourceValue.length > 0) {
            env[targetName] = sourceValue;
            continue;
        }
        if (typeof value.value === "string") {
            env[targetName] = value.value;
            continue;
        }
        if (value.required === true) {
            return { ok: false, reason: `required environment variable "${sourceName}" is not set` };
        }
    }
    return { ok: true, env: Object.keys(env).length > 0 ? env : undefined };
}

// plugin-server-registration.ts L223-260 — 按 owner 去重
export function resolvePluginMcpServerRegistrations<TOwner>(servers): PluginMcpServerResolution<TOwner>[] {
    const firstOwnerByName = new Map<string, string | undefined>();
    return servers.map(({ server, owner, ownerLabel }) => {
        const normalized = normalizePluginMcpServerRegistration(server);
        if (!normalized.registration) {
            return { owner, name: normalized.name, loadError: normalized.loadError ?? "..." };
        }
        const firstOwner = firstOwnerByName.get(normalized.registration.name);
        if (firstOwnerByName.has(normalized.registration.name)) {
            return {
                owner, name: normalized.registration.name,
                loadError: `duplicate MCP server name "${normalized.registration.name}" already registered by ${firstOwner}`,
            };
        }
        firstOwnerByName.set(normalized.registration.name, ownerLabel);
        return { owner, name: normalized.registration.name, registration: normalized.registration };
    });
}
```

**Charles 实现**：

Charles 无插件系统，`registry.py` L137-225 `load_config` 一次性从 `mcp_servers.yaml` 加载所有配置，无运行时动态注册。

**对比**：
- Cline 支持运行时从多个插件注册 MCP 服务器，含 `fromEnv` / `value` / `required` 三态 env 解析 + 按 owner 去重
- Charles 单进程架构，配置文件一次性加载，无动态注册
- Charles 的 `${ENV_VAR}` 语法（`client.py` L605-642）覆盖了 Cline `fromEnv` 的部分功能，但无 `required` 必填校验
- Charles 量化场景下 MCP 服务器清单固定（filesystem / quant-data 等），无需插件动态注册

---

## 四、nanobot 残留审计

### 4.1 检查范围

P7.8 范围内核心文件：
- `agent/mcp/__init__.py`（33 行）
- `agent/mcp/client.py`（642 行）
- `agent/mcp/registry.py`（528 行）
- `agent/mcp/name_transform.py`（79 行）
- `agent/tools/mcp.py`（352 行）
- `agent/runtime.py` L1543-1644（`_get_mcp_tool_policy_override` 方法，102 行）
- `agent_config/mcp_servers.yaml`（86 行）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/mcp/__init__.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 仅对标 "Cline mcp 集成" |
| `agent/mcp/client.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline MCP 服务连接管理" / "Cline mcp-service.ts" / "Cline use-mcp-tool.ts" |
| `agent/mcp/registry.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline mcpService" / "Cline policies.ts" / "Cline mcp-tool-factory.ts" |
| `agent/mcp/name_transform.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline name-transform.ts" |
| `agent/tools/mcp.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline use_mcp_tool / access_mcp_resource" / "Cline createUseMcpToolTool" / "Cline createAccessMcpResourceTool" |
| `agent/runtime.py` L1543-1644 | 0 处 | 0 处 | `_get_mcp_tool_policy_override` 方法无 "nanobot" 字样。注释对标 "Cline mcp-policy-loader.ts" |
| `agent_config/mcp_servers.yaml` | 0 处 | 0 处 | 全文无 "nanobot" 字样。注释对标 "Cline mcpSettings.json" / "Cline policies.ts ToolPolicy" |

**P7.8 范围内 nanobot 残留总计：0 处注释残留 + 0 处实现逻辑残留。**

### 4.3 实现逻辑残留检查

**0 处实现逻辑残留**。验证依据：

1. `client.py` 的 `MCPClient` 是 Stage 22 全新实现，基于 `asyncio.subprocess` + `urllib.request` 手写 JSON-RPC，无 nanobot 代码导入或复制
2. `registry.py` 的 `MCPRegistry` 是 Stage 22 + Stage 3.8 全新实现，基于 `asyncio.Lock` + dict 缓存，无 nanobot 逻辑
3. `name_transform.py` 的 `default_mcp_tool_name_transform` 是 Stage 32.3 全新实现，基于 `hashlib.sha1` + `re.sub`，无 nanobot 逻辑
4. `tools/mcp.py` 的 `UseMcpToolTool` / `AccessMcpResourceTool` 是 Stage 22 全新实现，基于 `BaseTool` 抽象类，无 nanobot 逻辑
5. `runtime.py` L1543-1644 `_get_mcp_tool_policy_override` 是 Stage 9.1 (Q8) 全新实现，对标 Cline mcp-policy-loader.ts，无 nanobot 逻辑
6. `mcp_servers.yaml` 是 Stage 22 + Stage 3.8 全新配置文件，无 nanobot 配置项

**结论**：P7.8 范围内 MCP 集成模块是 Charles 已完全清理的模块，无任何 nanobot 残留。所有 docstring 均对标 "Cline" 而非 "nanobot"。

### 4.4 范围外残留说明

以下文件的 nanobot 残留**超出 P7.8 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1 |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20 |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20 |
| `agent/providers/qwen.py` 7 处 | 注释残留 | docstring 对标 "nanobot openai_compat_provider.py" | P7.4 |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |

---

## 五、修复建议

### 5.1 高优先级：工具缓存 TTL 机制

**问题**：Charles `registry.py` L276-303 `list_tools` 是永久缓存，除非显式 `refresh=True` 或 `close_all`，否则永不刷新。Cline `manager.ts` L13 实现 5 秒 TTL 缓存，保证多客户端看到的工具列表新鲜。

**修复建议**：**可选补**。理由：
1. Charles 单 agent 会话场景下，工具列表在一次会话内通常不变，永久缓存可接受
2. 但若 MCP 服务器在会话中途增减工具（如动态加载插件的 MCP 服务器），Charles 的缓存会陈旧
3. 建议在 `MCPRegistry` 增加 `_tools_cache_time: dict[str, float]` 字段，记录缓存时间，`list_tools` 检查 TTL（建议 60 秒，比 Cline 的 5 秒宽松，因为 Charles 单会话场景下工具列表变化频率低）
4. 或者更简单：在 `UseMcpToolTool` 调用 `registry.call_tool` 失败时（工具不存在），自动 `refresh=True` 重试一次

**优先级**：中。当前永久缓存在量化场景下可接受，但若未来 MCP 服务器支持动态工具，需补 TTL。

### 5.2 中优先级：配置文件原子写入

**问题**：Charles `registry.py` L137-225 `load_config` 是只读操作，但若未来支持运行时修改配置（如通过 REST API 添加 MCP 服务器），无原子写入可能导致半写文件。Cline `config-loader.ts` L231-261 实现 tmp + rename 原子写入。

**修复建议**：**按需补**。理由：
1. Charles 当前 `mcp_servers.yaml` 是只读配置（运行时不修改），无原子写入需求
2. 但若未来补 `/mcp/servers` POST 端点（运行时添加 MCP 服务器），需补原子写入
3. 建议参考 Charles `provider_settings.py` 的 `_save` 方法（tmp + replace 原子写入），该模式已在 Charles 中验证
4. Charles 单进程无需跨进程锁，仅原子写入即可

**优先级**：低。当前只读配置无原子写入需求。

### 5.3 中优先级：framed 协议支持

**问题**：Charles `client.py` L482-544 `_send_request_stdio` 仅支持 newline 协议。Cline `client.ts` L158-184 支持 newline + framed 双协议自动尝试。部分 MCP 服务器（如基于 LSP 的服务器）仅支持 framed 协议。

**修复建议**：**按需补**。理由：
1. Charles 量化场景下 MCP 服务器多为自定义 Python 服务器（newline 协议），framed 协议需求低
2. 但若未来接入基于 LSP 的 MCP 服务器（如 language servers），需补 framed 协议
3. 建议在 `MCPClient` 增加 `protocol_mode: str = "newline"` 参数，支持 "newline" / "framed" / "auto" 三种模式
4. "auto" 模式参考 Cline 的 attempts 数组：先 newline 尝试，失败则 framed 重试

**优先级**：低。当前量化场景下 newline 协议足够。

### 5.4 低优先级：access_mcp_resource 策略消费

**问题**：Charles `runtime.py` L1548-1551 仅在 `tool_call.tool_name == "use_mcp_tool"` 时触发 `_get_mcp_tool_policy_override`，对 `access_mcp_resource` 不消费策略。Cline 的 first-class 模式下所有 MCP 工具均消费策略。

**修复建议**：**可选补**。理由：
1. `access_mcp_resource` 是读取资源（通常无副作用），策略控制需求低
2. 但若 MCP 资源含敏感数据（如数据库凭据），应支持 per-resource 策略
3. 建议在 `runtime.py` L1548 增加 `or tool_call.tool_name == "access_mcp_resource"` 条件，并在 `_get_mcp_tool_policy_override` 中解析 `uri` 参数查询策略
4. 需扩展 `MCPToolPolicy` 支持 `(server_name, uri)` 元组键

**优先级**：低。当前 `access_mcp_resource` 用于读取文件等无副作用资源，策略控制需求低。

### 5.5 低优先级：连接状态机

**问题**：Charles `client.py` L158-161 `is_connected` 仅 bool 标志（`_connected + _initialized`）。Cline `manager.ts` L187-227 实现完整状态机（disconnected/connecting/connected + lastError + updatedAt）+ `McpServerSnapshot` 快照接口。

**修复建议**：**不建议补**。理由：
1. Charles 单 agent 会话场景下，连接状态简单（连接/未连接），无需复杂状态机
2. Cline 的状态机主要用于多客户端监控（VSCode UI 显示连接状态），Charles 无 UI 监控需求
3. Charles 的 `logger.info` 已记录连接/断开事件，足够诊断
4. 补状态机会增加 `MCPClient` 复杂度，收益低

### 5.6 不建议补：OAuth 认证

**问题**：Cline `oauth.ts` 实现完整 OAuth 流程，Charles 完全无 OAuth 实现。

**修复建议**：**不建议补**。理由：
1. Charles 量化场景下 MCP 服务器多为本地 stdio 或内网 http，无需 OAuth
2. OAuth 流程复杂（本地回调服务器 + token 刷新 + 持久化），与 Charles "OpenAI 兼容协议优先" 架构原则不符
3. 若需访问公网 OAuth MCP 服务器，可通过环境变量传入 API key（`${ENV_VAR}` 语法）
4. 补 OAuth 会引入额外依赖（`@modelcontextprotocol/sdk` 或 equivalent Python OAuth 库）和测试成本

### 5.7 不建议补：plugin-server-registration

**问题**：Cline `plugin-server-registration.ts` 支持从插件注册 MCP 服务器，Charles 无插件系统。

**修复建议**：**不建议补**。理由：
1. Charles 单进程架构无插件系统，配置文件一次性加载
2. 插件注册机制复杂（按 owner 去重 + env.fromEnv 必填校验），与 Charles 简单架构不符
3. 若未来 Charles 支持插件，可参考 Cline 的 `resolvePluginMcpEnv` 实现

### 5.8 不建议补：first-class 工具展开

**问题**：Cline `tools.ts` L16-46 `createMcpTools` 将每个 MCP 工具展开为独立 LLM function，Charles 用调度器模式（`use_mcp_tool` 单一工具）。

**修复建议**：**不建议补**。理由：
1. Charles 调度器模式是有意为之的简化设计（`name_transform.py` L12-16 注释明确说明）
2. 调度器模式让 LLM 工具列表保持稳定（不随 MCP 服务器增减而变化），降低 LLM token 消耗
3. first-class 模式需要 name_transform 截断（64 字符限制），可能丢失工具名可读性
4. Charles 的 system prompt 概览（`registry.py` L458-501 `build_servers_summary`）已告知 LLM 可用工具列表
5. 调度器模式与 Charles 的 Qwen / DeepSeek 等国内模型兼容性更好（这些模型对长工具列表的处理能力弱于 Claude / GPT）

---

## 六、附录

### 6.1 MCP 协议方法实现对比

| 协议方法 | Cline 实现 | Charles 实现 | 一致性 |
|---------|-----------|-------------|--------|
| initialize | `client.ts` L165-176 | `client.py` L216-253 `_do_initialize` | 高 |
| notifications/initialized | `client.ts` L177 | `client.py` L248-253 `_send_notification` | 高 |
| tools/list | `client.ts` L205-231 | `client.py` L255-288 `list_tools` | 高 |
| tools/call | `client.ts` L233-241 | `client.py` L290-329 `call_tool` | 高 |
| resources/list | 未在 McpServerClient 接口定义 | `client.py` L331-366 `list_resources` | Charles 额外 |
| resources/read | 未在 McpServerClient 接口定义 | `client.py` L368-401 `read_resource` | Charles 额外 |
| ping | 无显式实现 | `client.py` L403-421 `ping` | Charles 额外 |
| shutdown | 无显式实现（直接 kill） | `client.py` L423-455 `close`（发送 shutdown + kill 兜底） | Charles 更规范 |

### 6.2 配置文件格式对比

**Cline mcpSettings.json**（JSON + Zod schema）：

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "env": { "FOO": "bar" }
      },
      "disabled": false,
      "oauth": { "tokens": { "access_token": "..." } }
    }
  }
}
```

**Charles mcp_servers.yaml**（YAML + PyYAML）：

```yaml
servers:
  - name: filesystem
    transport: stdio
    enabled: true
    description: 提供本地文件系统读写能力
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
    env: {}

tool_policies:
  - server: trading
    tool: place_order
    auto_approve: false
  - server: filesystem
    tool: delete_file
    enabled: false
```

**差异**：
- Cline 用 `disabled: false`（默认不禁用），Charles 用 `enabled: true`（默认启用）—— 语义反向但等价
- Cline 在 transport 内嵌套配置（`transport.type` / `transport.command`），Charles 在顶层平铺
- Cline 支持 `oauth` 字段，Charles 无
- Charles 有 `tool_policies` 段（per-tool 策略），Cline 的策略通过 `policies.ts` 动态生成（不持久化在配置文件）
- Cline 支持 `metadata` 字段（附加元数据），Charles 无

### 6.3 name_transform 算法对比

**Cline 实现**（`name-transform.ts` L20-34）：

```typescript
export const defaultMcpToolNameTransform: McpToolNameTransform = ({ serverName, toolName }): string => {
    const rawName = `${serverName}__${toolName}`;
    const sanitizedName = sanitizeMcpToolNameCandidate(rawName);
    if (sanitizedName === rawName && rawName.length <= MAX_MCP_TOOL_NAME_LENGTH) {
        return rawName;
    }
    const hash = buildMcpToolNameHash(rawName);
    const maxBaseLength = MAX_MCP_TOOL_NAME_LENGTH - HASH_SEPARATOR_LENGTH - HASH_LENGTH;
    const baseName = sanitizedName.slice(0, maxBaseLength) || FALLBACK_BASE_NAME;
    return `${baseName}_${hash}`;
};
```

**Charles 实现**（`name_transform.py` L52-79）：

```python
def default_mcp_tool_name_transform(server_name: str, tool_name: str) -> str:
    raw_name = f"{server_name}__{tool_name}"
    sanitized_name = _sanitize_mcp_tool_name_candidate(raw_name)
    if sanitized_name == raw_name and len(raw_name) <= MAX_MCP_TOOL_NAME_LENGTH:
        return raw_name
    hash_value = _build_mcp_tool_name_hash(raw_name)
    max_base_length = MAX_MCP_TOOL_NAME_LENGTH - _HASH_SEPARATOR_LENGTH - _HASH_LENGTH
    base_name = sanitized_name[:max_base_length] or _FALLBACK_BASE_NAME
    return f"{base_name}_{hash_value}"
```

**对比**：
- 算法完全一致：`serverName__toolName` → sanitize → 检查长度 → SHA1 hash 前 8 位 + 64 字符截断 + `mcp_tool` fallback
- 常量完全一致：`MAX_MCP_TOOL_NAME_LENGTH = 64` / `HASH_LENGTH = 8` / `HASH_SEPARATOR_LENGTH = 1` / `FALLBACK_BASE_NAME = "mcp_tool"`
- 差异：Charles Stage 32.3 已对齐，但当前架构下未启用（`name_transform.py` L12-16 注释说明 MCP 工具不作为独立 LLM function 暴露）
- Charles 的 `name_transform` 仅作为工具函数提供，未来若按 Cline 模式将 MCP 工具展开为独立 LLM function 时可直接调用

### 6.4 引用文件清单

**Cline 文件**：
- `third_party/cline/sdk/packages/core/src/extensions/mcp/index.ts`（70 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/types.ts`（135 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/client.ts`（579 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/manager.ts`（260 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/tools.ts`（47 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/policies.ts`（47 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/name-transform.ts`（35 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/config-loader.ts`（828 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/oauth.ts`（100+ 行）
- `third_party/cline/sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts`（260 行）
- `third_party/cline/sdk/packages/core/src/runtime/tools/tool-approval.ts`（80+ 行）

**Charles 文件**：
- `agent/mcp/__init__.py`（33 行）
- `agent/mcp/client.py`（642 行）
- `agent/mcp/registry.py`（528 行）
- `agent/mcp/name_transform.py`（79 行）
- `agent/tools/mcp.py`（352 行）
- `agent/runtime.py` L1543-1644（102 行）
- `agent_config/mcp_servers.yaml`（86 行）
