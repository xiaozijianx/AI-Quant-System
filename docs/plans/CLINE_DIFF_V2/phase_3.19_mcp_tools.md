# Phase 3.19 MCP 工具对比（first-class 注册 vs 调度器模式）

> 对比范围：Cline `extensions/mcp/` 的 MCP 集成（first-class 工具展开 + 传输/认证/策略/配置层）与 Charles `agent/mcp/` + `agent/tools/mcp.py` 的 MCP 集成（调度器模式 + 单一 use_mcp_tool / access_mcp_resource 入口）的实现范式差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/mcp/index.ts`（模块导出入口）
> - `sdk/packages/core/src/extensions/mcp/types.ts`（McpToolDescriptor / McpToolProvider / McpManager / McpServerTransportConfig / McpServerOAuthState 接口）
> - `sdk/packages/core/src/extensions/mcp/tools.ts`（createMcpTools — first-class 工具工厂）
> - `sdk/packages/core/src/extensions/mcp/manager.ts`（InMemoryMcpManager — 连接池 + 工具缓存）
> - `sdk/packages/core/src/extensions/mcp/client.ts`（StdioMcpClient / SdkUrlMcpClient / createDefaultMcpServerClientFactory）
> - `sdk/packages/core/src/extensions/mcp/name-transform.ts`（defaultMcpToolNameTransform — 64 字符截断 + hash）
> - `sdk/packages/core/src/extensions/mcp/oauth.ts`（authorizeMcpServerOAuth — 浏览器 OAuth 流）
> - `sdk/packages/core/src/extensions/mcp/policies.ts`（createDisabledMcpToolPolicy — first-class 策略生成）
> - `sdk/packages/core/src/extensions/mcp/config-loader.ts`（mcpSettings.json 加载 + 跨进程文件锁 + OAuth 状态持久化）
> - `sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts`（插件 MCP 服务器规范化 + env.fromEnv 注入）
> - `sdk/packages/shared/src/llms/tools.ts` L7-18（ToolPolicy 接口）
>
> Charles 源码：
> - `agent/mcp/__init__.py`（模块导出入口）
> - `agent/mcp/client.py`（MCPClient — JSON-RPC over stdio/http）
> - `agent/mcp/registry.py`（MCPRegistry + MCPServerConfig + MCPToolPolicy + get_registry 单例）
> - `agent/mcp/name_transform.py`（default_mcp_tool_name_transform — 工具函数，未在 registry 中应用）
> - `agent/tools/mcp.py`（UseMcpToolTool / AccessMcpResourceTool — 调度器模式入口）
> - `agent/runtime.py` L1596-1644（_get_mcp_tool_policy_override — 调度器侧策略查询）
> - `agent/server.py` L1775-1893（/mcp/servers、/mcp/resources、/mcp/reload REST 端点）
> - `agent/context.py` L788-834（_build_mcp_servers_section — system prompt 概览注入）
> - `agent_config/mcp_servers.yaml`（YAML 配置示例）

---

## 一、执行摘要

Cline 与 Charles 在 MCP 集成上采用了**两种完全不同的范式**，差异比任何 P3.x 子阶段都大：

1. **Cline 采用 first-class 工具模式**：MCP 服务器上的每个工具都被 `createMcpTools()` 展开成**独立的 LLM function**（`serverName__toolName` 经 name-transform 后作为 function name），LLM 直接看到 `filesystem__read_file`、`github__create_issue` 等独立工具，agent runtime 无需知道 MCP 协议，每个工具就是一个 `AgentTool` 实例。

2. **Charles 采用调度器模式**：MCP 工具不展开为独立 LLM function，而是通过**两个固定工具** `use_mcp_tool(server_name, tool_name, args)` 和 `access_mcp_resource(server_name, uri)` 转发调用，LLM 必须先识别 MCP 服务器名 + 工具名，再调用调度器。MCP 工具列表通过 system prompt 段（`# MCP 服务器` 概览）告知 LLM。

3. **关键架构差异**：

   | 维度 | Cline | Charles |
   |------|-------|---------|
   | 工具暴露方式 | first-class LLM function（每工具一个 AgentTool 实例） | 调度器模式（2 个固定工具） |
   | 工具名命名空间 | `serverName__toolName` + 64 字符截断 + hash 后缀 | 原始 `tool_name`，无截断（仅作为 use_mcp_tool 的参数） |
   | LLM 看到的工具数 | 1 + N（运行时 + N 个 MCP 工具） | 固定（仅 use_mcp_tool / access_mcp_resource） |
   | 传输协议 | stdio + sse + streamableHttp（三种） | stdio + http（两种，http 实为单次 POST） |
   | OAuth 浏览器流 | 完整实现（authorizeMcpServerOAuth + 本地回调服务器 + 持久化 token） | **未实现** |
   | 配置文件 | mcpSettings.json + 跨进程文件锁 + 原子写 + Zod 校验 | mcp_servers.yaml + PyYAML 加载，无锁 |
   | 策略机制 | first-class：`createDisabledMcpToolPolicy` 按 `serverName__toolName` key 写入 `toolPolicies` map | 调度器侧：`MCPToolPolicy(server, tool)` 二元组 key，在 `runtime._get_mcp_tool_policy_override()` 查询 |
   | 插件注册 | `plugin-server-registration.ts` 含 `fromEnv` 必填校验、按 owner 去重 | 无插件系统，配置文件一次性加载 |

4. **nanobot 残留**：P3.19 核心文件（`agent/mcp/*` + `agent/tools/mcp.py` + `agent_config/mcp_servers.yaml`）**完全无 nanobot 残留**（0 注释残留 + 0 实现逻辑残留）。这与 P3.1（`tools/__init__.py` L2 有 1 处注释残留）形成对比，P3.19 是已完全清理的模块。

5. **一致性总体评估**：**低**。两种范式在功能上部分等价（都能调用 MCP 工具、读取资源），但 LLM 看到的工具接口、name-transform 应用、策略机制、传输协议覆盖、OAuth 完整度、配置可靠性差异巨大。Charles 的调度器模式是**有意为之的简化设计**（在 `name_transform.py` docstring 明确说明），并非缺陷。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.19.1 | MCP 工具暴露范式 | first-class：`createMcpTools()` 展开为 N 个 `AgentTool` 实例 | 调度器：`use_mcp_tool` / `access_mcp_resource` 固定 2 个工具 | 低（设计差异） | 范式选择不同，非缺陷 |
| 3.19.2 | LLM 看到的工具数量 | 1（dispatcher） + N（每个 MCP 工具一个 function） | 固定（仅 2 个调度器工具） | 低 | Charles LLM context 更小，但需多一次推理跳转 |
| 3.19.3 | 工具名命名空间 | `serverName__toolName` 全局扁平命名 | `server_name` + `tool_name` 二参数分离 | 低 | Charles 无需考虑名称冲突，天然隔离 |
| 3.19.4 | name-transform 应用位置 | `createMcpTools()` 中作为 createTool 的 name 字段 | **未在 registry 中应用**，仅作为工具函数提供 | 低 | Charles 调度器模式不需要截断 |
| 3.19.5 | name-transform 算法 | SHA1 前 8 位 + 截断到 55 字符 + `_hash` 后缀，总长 ≤ 64 | 算法**完全等价**（SHA1 8 位 + 55 截断 + `_hash` 后缀） | 高 | 算法移植正确，仅未启用 |
| 3.19.6 | 工具描述动态生成 | `defaultMcpDescription(serverName, tool)` — 含 server 上下文 | 工具描述为 use_mcp_tool 的静态 description | 低 | Charles 在 system prompt 段补充上下文 |
| 3.19.7 | use_mcp_tool 等价物 | **无**（first-class 模式不需要调度器工具） | `UseMcpToolTool`（`agent/tools/mcp.py` L46-197） | 低 | Charles 独有，Cline 不需要 |
| 3.19.8 | access_mcp_resource 等价物 | **无**（resources 通过 first-class tool 或 listTools 暴露） | `AccessMcpResourceTool`（`agent/tools/mcp.py` L205-352） | 低 | Charles 独有 |
| 3.19.9 | 传输协议：stdio | `StdioMcpClient`（spawn 子进程 + newline/framed 双协议尝试） | `MCPClient._spawn_process`（asyncio.create_subprocess_exec + 仅 newline） | 中 | Charles 不支持 framed 协议 |
| 3.19.10 | 传输协议：sse | `SdkUrlMcpClient` + `SSEClientTransport`（MCP SDK 提供） | **未实现** | 低 | **Charles 缺失** |
| 3.19.11 | 传输协议：streamableHttp | `SdkUrlMcpClient` + `StreamableHTTPClientTransport` | `MCPClient._send_request_http`（单次 POST，非 streamable） | 低 | Charles http 模式不等价于 streamableHttp |
| 3.19.12 | OAuth 浏览器流 | `authorizeMcpServerOAuth`（本地回调服务器 + state + code_verifier + token 持久化） | **未实现** | 低 | **Charles 缺失** |
| 3.19.13 | OAuth 状态持久化 | `mcpSettings.json` 的 `oauth` 字段 + 跨进程文件锁保护 | 无 OAuth 状态 | 低 | 同 3.19.12 |
| 3.19.14 | MCP SDK 依赖 | `@modelcontextprotocol/sdk`（官方 SDK） | 无（手写 JSON-RPC） | 低 | Charles 自实现协议层 |
| 3.19.15 | 连接池管理 | `InMemoryMcpManager`（registerServer / unregisterServer / connectServer / disconnectServer / setServerDisabled） | `MCPRegistry`（load_config / get_client 懒创建 / close_all） | 中 | Charles 懒创建 vs Cline 显式 register |
| 3.19.16 | 工具列表缓存 | `toolsCacheTtlMs`（默认 5000ms TTL，过期自动 refreshTools） | `_tools_cache`（永久缓存，需手动 refresh=True） | 中 | Charles 缓存策略更简单，无 TTL |
| 3.19.17 | 并发控制 | `operationLocks`（Promise 链式串行化，per-server 隔离） | `_client_locks`（asyncio.Lock，per-server 隔离） | 高 | 语义等价 |
| 3.19.18 | 服务器禁用机制 | `setServerDisabled(name, disabled)`（运行时 API + 持久化到 settings） | `enabled` 字段（配置加载时读取，无运行时 API） | 中 | Charles 仅配置文件层 |
| 3.19.19 | 服务器快照 | `McpServerSnapshot`（含 status / disabled / lastError / toolCount / updatedAt / metadata） | `MCPServerConfig`（仅含静态配置，无 status / lastError / toolCount） | 中 | Charles 缺运行时状态 |
| 3.19.20 | 配置文件格式 | JSON（mcpSettings.json） | YAML（mcp_servers.yaml） | 中（语言习惯） | Python 项目偏好 YAML |
| 3.19.21 | 配置文件加载 | `loadMcpSettingsFile`（Zod schema + discriminatedUnion + legacy 兼容） | `MCPRegistry.load_config`（PyYAML safe_load + 手写字段校验） | 中 | Charles 校验较弱 |
| 3.19.22 | 配置文件写入 | `updateMcpSettingsFile`（跨进程目录锁 + 原子 tmp + rename + mutator 纯度校验） | 无（YAML 不支持运行时写入） | 低 | **Charles 缺失**，无 OAuth 状态写入需求 |
| 3.19.23 | 配置文件热加载 | 无（通过 setMcpServerDisabled 运行时 API 调整） | `/mcp/reload` REST 端点（close_all + load_config） | 中 | Charles 用 REST 替代运行时 API |
| 3.19.24 | 工具策略机制 | first-class：`createDisabledMcpToolPolicy(serverName, toolName)` 生成 `{name: {enabled: false}}` 写入 `toolPolicies` map | 调度器侧：`MCPToolPolicy(server, tool, enabled, auto_approve)` 二元组 key | 中 | 两种机制功能等价，但 key 结构不同 |
| 3.19.25 | 策略 key 命名 | name-transform 后的扁平 key（如 `filesystem__read_file_abc12345`） | 二元组 `(server_name, tool_name)` 原始名 | 中 | Charles 无需 name-transform |
| 3.19.26 | 策略查询位置 | runtime 在工具调度前查 `toolPolicies[toolName]` | `runtime._get_mcp_tool_policy_override(tool_call)` 提取 server/tool 参数后查 registry | 中 | Charles 多一步参数提取 |
| 3.19.27 | 策略 enabled=false 行为 | 工具完全不出现在 LLM 工具列表中（first-class 模式下天然过滤） | 工具调用时返回 `isError: true`（运行时拦截） | 中 | Charles 是运行时拦截，非编译时过滤 |
| 3.19.28 | 策略 auto_approve=false 行为 | LLM 调用工具时触发审批流程 | runtime 在 `_request_tool_approval` 前置查询策略，强制走用户审批 | 高 | 语义等价 |
| 3.19.29 | 插件 MCP 服务器 | `plugin-server-registration.ts`（owner 去重 + env.fromEnv 必填校验 + 多源聚合） | 无插件系统 | 低 | **Charles 缺失** |
| 3.19.30 | 环境变量解析 | `resolvePluginMcpEnv`（支持 `{fromEnv, value, required}` 结构 + 缺失必填时报错） | `_resolve_env_value`（仅支持 `${VAR}` 字符串模板 + 未找到保留原样） | 中 | Charles 简化版 |
| 3.19.31 | REST API | 无（Cline 通过 SDK API 调用） | `/mcp/servers` / `/mcp/resources` / `/mcp/reload` | 中 | Charles 独有，前端调试用 |
| 3.19.32 | system prompt 概览 | 无（每个工具自带 description，无需额外说明） | `_build_mcp_servers_section` + `build_servers_summary`（注入 `# MCP 服务器` 段） | 中 | Charles 用 prompt 补偿调度器模式的上下文缺失 |
| 3.19.33 | 资源读取协议方法 | `resources/list` + `resources/read`（通过 McpServerClient 接口） | `resources/list` + `resources/read`（MCPClient 直接实现） | 高 | 协议方法对齐 |
| 3.19.34 | 工具调用协议方法 | `tools/list` + `tools/call`（通过 McpServerClient 接口） | `tools/list` + `tools/call`（MCPClient 直接实现） | 高 | 协议方法对齐 |
| 3.19.35 | initialize 握手 | `Client.connect(transport)` 内部完成（MCP SDK） | `_do_initialize`（手写 initialize 请求 + notifications/initialized 通知） | 高 | 协议对齐 |
| 3.19.36 | 客户端名称 | `@cline/core` | `charles-agent` | 高 | 各自正确 |
| 3.19.37 | 协议版本 | `2024-11-05` | `2024-11-05` | 高 | 完全一致 |
| 3.19.38 | 默认超时 | `MCP_REQUEST_TIMEOUT_MS = 5000` / `MCP_CONNECT_TIMEOUT_MS = 1500` | `_DEFAULT_TIMEOUT = 30.0` / 工具调用 `_CALL_TIMEOUT = 60.0` | 中 | Charles 超时更长，符合 MCP 工具可能执行较久的特性 |
| 3.19.39 | 进程退出处理 | `child.once("exit")` → `failAllPending` + stderr 捕获 | `readline` 返回空时读取 stderr 抛错 | 中 | Charles 处理较粗 |
| 3.19.40 | framed 协议支持 | 是（`FramedMessageParser` + Content-Length 头） | 否 | 低 | **Charles 缺失**，仅 newline 模式 |
| 3.19.41 | 协议自动降级 | 是（先试 newline，失败再试 framed） | 否 | 低 | 同 3.19.40 |
| 3.19.42 | 错误信息格式 | MCP 协议层抛 Error（含 stderr 后缀） | `AgentToolResult(output={error: ...}, is_error=True)` | 中 | Charles 包装为工具结果，Cline 抛异常 |
| 3.19.43 | 单例模式 | 无（通过依赖注入 McpManager 实例） | `get_registry()` 全局单例 + `_registry_lock` 线程锁 | 中 | Charles 单例更适合 CLI 场景 |

**一致性总评**：43 项中，高一致性 8 项、中一致性 19 项、低一致性 16 项。低一致性项集中在 OAuth、传输协议覆盖、first-class 模式特有抽象（name-transform 应用、插件系统、配置文件锁）。

---

## 三、重点差距详细说明

### 差距 1：first-class vs 调度器 — 范式根本差异（3.19.1 / 3.19.2 / 3.19.3 / 3.19.4 / 3.19.7 / 3.19.8）

**Cline 实现**（`tools.ts` L16-46）：

`createMcpTools(options)` 调用 `options.provider.listTools(serverName)` 获取 MCP 工具描述符列表，对每个描述符调用 `createTool({...})` 创建独立的 `AgentTool` 实例。LLM 看到的工具列表中，filesystem 服务器的 `read_file` 工具会作为一个名为 `filesystem__read_file`（或经 name-transform 截断后的变体）的独立 function 出现，LLM 直接调用该 function 即可触发 MCP `tools/call`。

**Charles 实现**（`tools/mcp.py`）：

`UseMcpToolTool` 是一个固定工具，LLM 看到的工具列表中只有 `use_mcp_tool`，其 input schema 是 `{server_name, tool_name, args}`。LLM 必须先通过 system prompt 中的 `# MCP 服务器` 概览段识别可用的 server/tool 组合，再构造 `use_mcp_tool(server_name="filesystem", tool_name="read_file", args={...})` 调用。`AccessMcpResourceTool` 同理处理 `resources/read`。

**Charles 设计选择的明确说明**（`name_transform.py` L11-16）：

```python
当前架构说明:
    本系统的 MCP 工具通过 use_mcp_tool(server_name, tool_name, args) 统一调用，
    MCP 工具名不直接作为 LLM function name 暴露，因此不需要在 registry 中
    强制应用此转换。本模块作为工具函数提供，未来若按 Cline 模式将 MCP 工具
    展开为独立 LLM function 时可直接调用 default_mcp_tool_name_transform。
```

**影响**：

- Charles 的调度器模式 LLM context 更小（工具数固定），但需多一次推理跳转（LLM 先选 server+tool，再调 use_mcp_tool）。
- Cline 的 first-class 模式 LLM 直接看到每个 MCP 工具的 inputSchema，参数提示更精确。
- Charles 的 name_transform 模块虽实现完整但未启用，是**有意保留的未启用代码**，非残留。

**建议**：不强制补齐。Charles 的调度器模式是设计选择，已在 docstring 中明确说明。若未来需要 first-class 模式，可直接调用 `default_mcp_tool_name_transform`。

### 差距 2：OAuth 浏览器流完全缺失（3.19.12 / 3.19.13 / 3.19.14）

**Cline 实现**（`oauth.ts` L275-401）：

`authorizeMcpServerOAuth(options)` 实现完整的 OAuth 2.0 Authorization Code Flow：

1. 启动本地回调服务器（`startLocalOAuthServer`，监听 1456/1457/1458 端口，路径 `/mcp/oauth/callback`）。
2. 创建 `OAuthClientProvider`（`createMcpOAuthProviderContext`），实现 `redirectUrl` / `clientMetadata` / `state` / `clientInformation` / `saveClientInformation` / `tokens` / `saveTokens` / `redirectToAuthorization` / `saveCodeVerifier` / `codeVerifier` / `invalidateCredentials` / `saveDiscoveryState` / `discoveryState` 共 13 个方法。
3. 调用 `createMcpSdkTransport`（SSE 或 StreamableHTTP）建立 transport。
4. 尝试 `client.connect(transport)` + `client.listTools()`；若抛 `UnauthorizedError`，从 `getLastAuthorizationUrl()` 取授权 URL，调用 `options.openUrl` 打开浏览器。
5. 等待回调服务器收到 `code` + `state`，校验 state 匹配，调用 `transport.finishAuth(code)`。
6. 重新创建 client + transport，重试 `connect` + `listTools`。
7. OAuth 状态（tokens / codeVerifier / clientInformation / discoveryState / redirectUrl / lastError / lastAuthenticatedAt）通过 `updateMcpServerOAuthStateAsync` 持久化到 mcpSettings.json，受跨进程文件锁保护。

**Charles 实现**：

`agent/mcp/` 模块中**完全无 OAuth 相关代码**（grep "oauth" 0 匹配）。`mcp_servers.yaml` 配置中 http 传输的 `headers.Authorization: "Bearer ${MCP_SEARCH_TOKEN}"` 是静态 token，不支持 OAuth 流。

**影响**：

- Charles 无法连接需要 OAuth 认证的 MCP 服务器（如 GitHub MCP、Notion MCP 等公开服务）。
- 仅支持 stdio（本地无认证）和 http + 静态 Bearer Token 两种场景。
- 对于企业内部 MCP 服务器（通常用 API key），Charles 当前方案够用。

**建议**：不强制补齐。OAuth 浏览器流实现复杂（需本地回调服务器 + 状态持久化 + token 刷新），且 Charles 当前场景（量化系统、企业内部 MCP）通常用 API key 认证。若未来接入公开 MCP 服务（如 GitHub），可参考 Cline `oauth.ts` 实现。

### 差距 3：传输协议覆盖差异（3.19.9 / 3.19.10 / 3.19.11 / 3.19.40 / 3.19.41）

**Cline 实现支持三种传输**：

| 传输类型 | 实现类 | 协议特征 |
|---------|--------|---------|
| stdio | `StdioMcpClient` | spawn 子进程 + newline/framed 双协议自动降级 |
| sse | `SdkUrlMcpClient` + `SSEClientTransport` | Server-Sent Events 长连接 |
| streamableHttp | `SdkUrlMcpClient` + `StreamableHTTPClientTransport` | HTTP 流式响应 |

`StdioMcpClient` 的 `connect()` 方法尝试两种协议：先试 newline（`\n` 分隔 JSON），失败再试 framed（`Content-Length: N\r\n\r\n{body}`），自动适配不同 MCP 服务器实现。

**Charles 实现支持两种传输**：

| 传输类型 | 实现方法 | 协议特征 |
|---------|---------|---------|
| stdio | `MCPClient._send_request_stdio` | asyncio.create_subprocess_exec + 仅 newline 协议 |
| http | `MCPClient._send_request_http` | 单次 POST + urllib，非 streamable |

**影响**：

- Charles 不支持 SSE 传输的 MCP 服务器（部分远程 MCP 服务用 SSE 推送）。
- Charles 的 http 模式是单次 POST，不等价于 streamableHttp（无法处理流式响应）。
- Charles 不支持 framed 协议（部分 MCP 服务器仅支持 framed，如基于 LSP 的实现）。
- 对于本地 stdio MCP 服务器（最常见场景），Charles newline 模式够用。

**建议**：不强制补齐。Charles 当前 MCP 服务器配置为空（`servers: []`），无实际 MCP 服务器接入需求。若未来接入需要 SSE 或 framed 的服务器，可参考 Cline `client.ts` 实现。

### 差距 4：配置文件可靠性差异（3.19.20 / 3.19.21 / 3.19.22 / 3.19.23）

**Cline 实现**（`config-loader.ts`）：

- **格式**：JSON（`mcpSettings.json`）。
- **校验**：Zod schema + discriminatedUnion + legacy 兼容（支持旧版 `type` / `transportType` / `command` / `url` 平铺字段，自动转换为嵌套 `transport` 结构）。
- **跨进程锁**：`tryAcquireSettingsLock` 基于目录的跨进程锁（`mkdir` + `rename` 原子操作），支持多进程并发写入（CLI + VS Code 扩展 + JetBrains 同时运行）。锁过期 10 秒自动回收（`reclaimStaleLock`）。
- **原子写**：`atomicWriteSettingsFile` 先写 tmp 文件再 rename，避免并发读取到半写状态。
- **mutator 纯度校验**：`runPureSettingsMutator` 调用 mutator 两次，对比结果一致性，防止 mutator 有副作用（如随机数、时间戳）导致配置漂移。
- **运行时 API**：`updateMcpSettingsFileSync` / `updateMcpSettingsFile` / `setMcpServerDisabled` / `updateMcpServerOAuthState` / `updateMcpServerOAuthStateAsync` 支持运行时修改配置并持久化。

**Charles 实现**（`registry.py` L137-225）：

- **格式**：YAML（`mcp_servers.yaml`）。
- **校验**：PyYAML `safe_load` + 手写字段校验（`if not name` / `if transport == "stdio" and not command`）。
- **跨进程锁**：无。
- **原子写**：无（YAML 不支持运行时写入）。
- **mutator 纯度校验**：无。
- **运行时 API**：`/mcp/reload` REST 端点（close_all + load_config 重新加载，非增量更新）。

**影响**：

- Charles 不支持运行时修改单个服务器配置（必须整体 reload，会中断现有连接）。
- Charles 无跨进程锁，若多进程同时读取 mcp_servers.yaml 通常不会冲突（只读），但无写入场景所以无实际影响。
- Charles 的 YAML 格式更易手工编辑（注释友好），适合 CLI 场景。

**建议**：不强制补齐。Charles 是单进程 CLI，无跨进程锁需求。YAML 格式更适合人工编辑。运行时 reload 通过 REST 端点已能满足需求。

### 差距 5：策略机制 key 结构差异（3.19.24 / 3.19.25 / 3.19.26 / 3.19.27）

**Cline 实现**（`policies.ts`）：

`createDisabledMcpToolPolicy({serverName, toolName})` 调用 `defaultMcpToolNameTransform({serverName, toolName})` 生成扁平 key（如 `filesystem__read_file` 或截断后的 `filesystem__read_file_abc12345`），写入 `Record<string, ToolPolicy>` map。runtime 在调度工具前查 `toolPolicies[toolName]`。

由于 first-class 模式下工具名就是 name-transform 后的扁平 key，策略查询天然对齐。`enabled: false` 的工具**不会出现在 LLM 工具列表中**（在 `resolveCoreSelectedToolIds` 阶段被过滤），是**编译时过滤**。

**Charles 实现**（`registry.py` L67-82 + `runtime.py` L1596-1644）：

`MCPToolPolicy(server_name, tool_name, enabled, auto_approve)` 是 dataclass，存储在 `_tool_policies: dict[tuple[str, str], MCPToolPolicy]` 中，key 是 `(server_name, tool_name)` 二元组。

`runtime._get_mcp_tool_policy_override(tool_call)` 从 `tool_call.input` 中提取 `server_name` 和 `tool_name`，调用 `registry.get_tool_policy(server, tool)` 查询策略，返回 `{autoApprove, enabled}` dict 给 runtime 的审批逻辑。

`enabled: false` 的工具**仍出现在 LLM 工具列表中**（use_mcp_tool 工具不变），但调用时在 `registry.call_tool` 内返回 `isError: true`（L362-372），是**运行时拦截**。

**影响**：

- Cline 的 first-class 模式下，禁用工具对 LLM 不可见，LLM 不会尝试调用。
- Charles 的调度器模式下，LLM 仍可能尝试调用被禁用的工具（因为 use_mcp_tool 工具始终可见），但调用会被拦截并返回错误。
- Charles 的运行时拦截对 LLM 体验略差（LLM 可能反复尝试），但功能正确。

**建议**：不强制补齐。两种机制功能等价（都能禁用工具）。Charles 的调度器模式天然无法在编译时过滤（因为 use_mcp_tool 是固定工具），运行时拦截是合理选择。

### 差距 6：插件 MCP 服务器系统缺失（3.19.29 / 3.19.30）

**Cline 实现**（`plugin-server-registration.ts`）：

支持插件（agent extension）注册 MCP 服务器：

- `normalizePluginMcpServerRegistration(server)`：规范化插件 MCP 服务器配置，支持 `env: {KEY: {fromEnv, value, required}}` 结构化环境变量声明。
- `resolvePluginMcpEnv(server)`：解析环境变量，`fromEnv` 指定源变量名，`required: true` 时缺失必填变量会报错（`loadError`）。
- `resolvePluginMcpServerRegistrations(servers)`：多源聚合，按 `name` 去重，第一个注册的 owner 优先，后续重复注册返回 `loadError: "duplicate MCP server name"`。

**Charles 实现**：

无插件系统，`mcp_servers.yaml` 一次性加载所有服务器配置。环境变量解析仅支持 `${VAR}` 字符串模板（`_resolve_env_value`），不支持 `{fromEnv, value, required}` 结构化声明。

**影响**：

- Charles 不支持插件动态注册 MCP 服务器。
- Charles 的环境变量解析较简单，缺失必填变量时不会报错（保留原样 `${VAR}`）。

**建议**：不强制补齐。Charles 无插件系统需求。环境变量解析的简化版已能满足当前场景。

---

## 四、nanobot 残留检查

针对 P3.19 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.19 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/mcp/__init__.py` | **0** | 无 | docstring 仅标注"对标 Cline mcp 集成" |
| `agent/mcp/client.py` | **0** | 无 | docstring 仅标注"对标 Cline MCP 服务连接管理" |
| `agent/mcp/registry.py` | **0** | 无 | docstring 仅标注"对标 Cline mcpService" |
| `agent/mcp/name_transform.py` | **0** | 无 | docstring 仅标注"对标 Cline name-transform.ts" |
| `agent/tools/mcp.py` | **0** | 无 | docstring 仅标注"对标 Cline use_mcp_tool / access_mcp_resource" |
| `agent_config/mcp_servers.yaml` | **0** | 无 | 注释仅标注"对标 Cline mcpSettings.json" |
| `agent/runtime.py`（MCP 策略段落 L1596-1644） | **0** | 无 | docstring 标注"对标 Cline mcp-policy-loader.ts" |
| `agent/server.py`（MCP REST 端点 L1775-1893） | **0** | 无 | 注释标注"对标 Cline mcp 服务管理" |
| `agent/context.py`（_build_mcp_servers_section L788-834） | **0** | 无 | 无 nanobot 引用 |

### 4.2 残留分类

#### 注释残留（0 处）

P3.19 核心文件中**无任何 nanobot 注释残留**。所有 docstring 和行内注释均统一标注"对标 Cline"，无历史溯源引用 nanobot。

#### 实现逻辑残留（0 处）

P3.19 核心文件中**无任何从 nanobot 直接移植的实现逻辑**：

- `MCPClient`（`client.py`）对标 Cline `StdioMcpClient` + `SdkUrlMcpClient`，手写 JSON-RPC 2.0 实现，不依赖 nanobot 的任何模块。
- `MCPRegistry`（`registry.py`）对标 Cline `InMemoryMcpManager` + `config-loader.ts`，单例模式 + YAML 加载，不依赖 nanobot 的任何模块。
- `default_mcp_tool_name_transform`（`name_transform.py`）算法完全对标 Cline `defaultMcpToolNameTransform`（SHA1 8 位 + 55 截断 + `_hash` 后缀），非 nanobot 移植。
- `UseMcpToolTool` / `AccessMcpResourceTool`（`tools/mcp.py`）是 Charles 独有的调度器模式工具，Cline 无对应实现（Cline 用 first-class 模式不需要调度器），非 nanobot 移植。
- `MCPToolPolicy`（`registry.py` L67-82）对标 Cline `ToolPolicy` + `createDisabledMcpToolPolicy`，dataclass + 二元组 key 设计，非 nanobot 移植。
- `_get_mcp_tool_policy_override`（`runtime.py` L1596-1644）是 Charles 独有的调度器侧策略查询逻辑，Cline 无对应实现（Cline 在 first-class 模式下天然按工具名查询），非 nanobot 移植。

### 4.3 P3.19 范围外但相关的 nanobot 残留

P3.19 核心文件全部清洁，无范围外残留需处理。

---

## 五、修复建议

### 建议 1：不强制补齐 first-class 工具模式 [P3 不修复]

**理由**：

- Charles 的调度器模式是**有意为之的设计选择**，在 `name_transform.py` docstring 中明确说明。
- 调度器模式 LLM context 更小（工具数固定），适合 token 受限场景。
- `name_transform.py` 模块已实现完整且经过测试，未来切换到 first-class 模式可直接启用。
- 调度器模式 + system prompt 概览段的组合已能满足 LLM 识别 MCP 工具的需求。

**保留条件**：若未来 LLM provider 支持 large toolset（如 Gemini 2.0+ 支持 1000+ 工具），可考虑切换到 first-class 模式以获得更精确的参数提示。

### 建议 2：不强制补齐 OAuth 浏览器流 [P3 不修复]

**理由**：

- OAuth 实现复杂（本地回调服务器 + state + code_verifier + token 持久化 + 跨进程文件锁），开发成本高。
- Charles 当前场景（量化系统、企业内部 MCP）通常用 API key 认证，静态 Bearer Token 够用。
- `mcp_servers.yaml` 的 `headers.Authorization: "Bearer ${MCP_SEARCH_TOKEN}"` 已支持环境变量引用。

**保留条件**：若未来接入需要 OAuth 的公开 MCP 服务（如 GitHub MCP、Notion MCP），可参考 Cline `oauth.ts` 实现。

### 建议 3：不强制补齐 SSE / streamableHttp / framed 传输 [P3 不修复]

**理由**：

- Charles 当前 MCP 服务器配置为空（`servers: []`），无实际 MCP 服务器接入需求。
- stdio + http（单次 POST）已覆盖本地 MCP 服务器和简单远程 MCP 服务器场景。
- framed 协议主要用于 LSP 风格的 MCP 服务器，较少见。

**保留条件**：若未来接入需要 SSE 或 framed 的服务器，可参考 Cline `client.ts` 的 `StdioMcpClient`（framed 支持）和 `SdkUrlMcpClient`（SSE / streamableHttp 支持）。

### 建议 4：不强制补齐跨进程文件锁 [P3 不修复]

**理由**：

- Charles 是单进程 CLI，无跨进程并发写入需求。
- YAML 格式不支持运行时写入，无文件锁需求。
- `/mcp/reload` REST 端点已能满足配置热加载需求。

**保留条件**：若未来 Charles 支持多进程并发（如 Web 端 + CLI 端同时运行），可参考 Cline `config-loader.ts` 的目录锁实现。

### 建议 5：不强制补齐插件 MCP 服务器系统 [P3 不修复]

**理由**：

- Charles 无插件系统需求，MCP 服务器配置通过 `mcp_servers.yaml` 集中管理。
- 环境变量解析的 `${VAR}` 模板已能满足需求。

**保留条件**：若未来 Charles 引入插件系统（如第三方扩展注册 MCP 服务器），可参考 Cline `plugin-server-registration.ts` 实现。

### 建议 6：保留调度器侧策略查询 [P0 不变]

**理由**：Charles 的 `_get_mcp_tool_policy_override` 是调度器模式的必要补充，在 `runtime._request_tool_approval` 前置查询 MCP per-tool 策略，**不应移除**。这是 Charles 相对 Cline 的功能等价实现，只是 key 结构不同（二元组 vs name-transform 扁平 key）。

### 建议 7：保留 name_transform 模块作为未启用工具函数 [P0 不变]

**理由**：`name_transform.py` 是有意保留的未启用模块，docstring 明确说明"未来若按 Cline 模式将 MCP 工具展开为独立 LLM function 时可直接调用"。算法实现与 Cline 完全等价（已在 3.19.5 验证），不应移除。

---

## 六、验证方法建议

### 验证方法 1：范式差异验证

确认 Charles 的调度器模式（use_mcp_tool + access_mcp_resource 固定 2 个工具）与 Cline 的 first-class 模式（N 个独立工具）：

```powershell
# Charles 侧：确认 tools/mcp.py 仅定义 2 个工具类
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\mcp.py" -Pattern "class \w+Tool\(BaseTool\)"
# 预期：UseMcpToolTool / AccessMcpResourceTool

# Cline 侧：确认 createMcpTools 展开为 N 个 AgentTool
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\mcp\tools.ts" -Pattern "createTool|AgentTool"
```

### 验证方法 2：name-transform 算法等价性验证

确认 Charles `default_mcp_tool_name_transform` 与 Cline `defaultMcpToolNameTransform` 算法完全等价：

```powershell
# Charles 侧：确认常量和算法步骤
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\name_transform.py" -Pattern "MAX_MCP_TOOL_NAME_LENGTH|_HASH_LENGTH|sha1|hexdigest"
# 预期：MAX_MCP_TOOL_NAME_LENGTH = 64 / _HASH_LENGTH = 8 / sha1 + hexdigest[:8]

# Cline 侧：确认常量和算法步骤
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\mcp\name-transform.ts" -Pattern "MAX_MCP_TOOL_NAME_LENGTH|HASH_LENGTH|createHash|sha1"
# 预期：MAX_MCP_TOOL_NAME_LENGTH = 64 / HASH_LENGTH = 8 / createHash("sha1").slice(0, 8)
```

### 验证方法 3：策略机制差异验证

确认 Charles 的二元组 key 策略与 Cline 的 name-transform 扁平 key 策略：

```powershell
# Charles 侧：确认 MCPToolPolicy 用 (server, tool) 二元组 key
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\registry.py" -Pattern "_tool_policies|tuple\[str, str\]"
# 预期：_tool_policies: dict[tuple[str, str], MCPToolPolicy]

# Cline 侧：确认 createDisabledMcpToolPolicy 用 name-transform 后的扁平 key
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\mcp\policies.ts" -Pattern "nameTransform|defaultMcpToolNameTransform"
# 预期：const name = nameTransform({serverName, toolName})
```

### 验证方法 4：OAuth 缺失验证

确认 Charles 的 MCP 模块完全无 OAuth 实现：

```powershell
# 预期：0 匹配
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\*.py" -Pattern "oauth|OAuth|Oauth" -CaseSensitive:$false
```

### 验证方法 5：传输协议覆盖验证

确认 Charles 仅支持 stdio + http，不支持 sse / streamableHttp / framed：

```powershell
# Charles 侧：确认仅 stdio + http
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\client.py" -Pattern "transport ==|stdio|http"
# 预期：transport == "stdio" / transport == "http"

# Cline 侧：确认 stdio + sse + streamableHttp
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\mcp\types.ts" -Pattern "type:.*\"(stdio|sse|streamableHttp)\""
# 预期：stdio / sse / streamableHttp 三种
```

### 验证方法 6：nanobot 残留扫描

```powershell
# P3.19 核心文件扫描（应全部 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\*.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\mcp.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\mcp_servers.yaml" -Pattern "nanobot" -CaseSensitive:$false
```

### 验证方法 7：调度器侧策略查询验证

确认 Charles runtime 在 use_mcp_tool 调用前查询 MCP per-tool 策略：

```powershell
# 确认 _get_mcp_tool_policy_override 方法存在且调用 registry.get_tool_policy
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "_get_mcp_tool_policy_override|get_tool_policy"
# 预期：方法定义 + 调用 registry.get_tool_policy(server_name, mcp_tool_name)
```

### 验证方法 8：REST API 端点验证

确认 Charles 的 MCP REST 端点（Cline 无对应实现）：

```powershell
# 确认 /mcp/servers / /mcp/resources / /mcp/reload 三个端点
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "@router\.(get|post).*mcp"
# 预期：3 个端点
```

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/mcp/index.ts` | L1-70 | 模块导出入口 |
| `sdk/packages/core/src/extensions/mcp/types.ts` | L3-21 | McpToolDescriptor / McpToolProvider 接口 |
| `sdk/packages/core/src/extensions/mcp/types.ts` | L23-26 | McpToolNameTransform 类型 |
| `sdk/packages/core/src/extensions/mcp/types.ts` | L28-35 | CreateMcpToolsOptions 接口 |
| `sdk/packages/core/src/extensions/mcp/types.ts` | L39-62 | McpStdioTransportConfig / McpSseTransportConfig / McpStreamableHttpTransportConfig |
| `sdk/packages/core/src/extensions/mcp/types.ts` | L64-80 | McpServerOAuthState / McpServerRegistration 接口 |
| `sdk/packages/core/src/extensions/mcp/types.ts` | L92-135 | McpServerClient / McpServerClientFactory / McpManager 接口 |
| `sdk/packages/core/src/extensions/mcp/tools.ts` | L5-14 | defaultMcpDescription |
| `sdk/packages/core/src/extensions/mcp/tools.ts` | L16-46 | createMcpTools — first-class 工具工厂 |
| `sdk/packages/core/src/extensions/mcp/manager.ts` | L13-48 | DEFAULT_TOOLS_CACHE_TTL_MS + InMemoryMcpManager 构造 |
| `sdk/packages/core/src/extensions/mcp/manager.ts` | L51-115 | registerServer / unregisterServer / connectServer / disconnectServer / setServerDisabled |
| `sdk/packages/core/src/extensions/mcp/manager.ts` | L131-166 | listTools / refreshTools / callTool（含 TTL 缓存） |
| `sdk/packages/core/src/extensions/mcp/manager.ts` | L175-227 | ensureConnectedClient / connectState / disconnectState |
| `sdk/packages/core/src/extensions/mcp/manager.ts` | L237-259 | runExclusive — Promise 链式串行化 |
| `sdk/packages/core/src/extensions/mcp/client.ts` | L38-124 | StdioProtocolMode + FramedMessageParser + NewlineMessageParser |
| `sdk/packages/core/src/extensions/mcp/client.ts` | L126-434 | StdioMcpClient（spawn + 双协议尝试 + pending map） |
| `sdk/packages/core/src/extensions/mcp/client.ts` | L443-570 | SdkUrlMcpClient（SSE / streamableHttp + OAuth 集成） |
| `sdk/packages/core/src/extensions/mcp/client.ts` | L572-579 | createDefaultMcpServerClientFactory 工厂 |
| `sdk/packages/core/src/extensions/mcp/name-transform.ts` | L1-35 | defaultMcpToolNameTransform（SHA1 8 位 + 55 截断 + _hash） |
| `sdk/packages/core/src/extensions/mcp/oauth.ts` | L28-30 | OAuth 回调端口 + 路径 + 超时常量 |
| `sdk/packages/core/src/extensions/mcp/oauth.ts` | L84-92 | createOAuthClientMetadata |
| `sdk/packages/core/src/extensions/mcp/oauth.ts` | L94-231 | createMcpOAuthProviderContext（13 个 OAuthClientProvider 方法） |
| `sdk/packages/core/src/extensions/mcp/oauth.ts` | L233-263 | createMcpSdkTransport（SSE / streamableHttp） |
| `sdk/packages/core/src/extensions/mcp/oauth.ts` | L275-401 | authorizeMcpServerOAuth（完整 OAuth 浏览器流） |
| `sdk/packages/core/src/extensions/mcp/policies.ts` | L5-15 | CreateDisabledMcpToolPolicyOptions / CreateDisabledMcpToolPoliciesOptions |
| `sdk/packages/core/src/extensions/mcp/policies.ts` | L17-30 | createDisabledMcpToolPolicy（name-transform 后扁平 key） |
| `sdk/packages/core/src/extensions/mcp/policies.ts` | L32-47 | createDisabledMcpToolPolicies（批量生成） |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L25-181 | Zod schema + discriminatedUnion + legacy 兼容 |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L231-261 | resolveDefaultMcpSettingsPath + atomicWriteSettingsFile |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L270-447 | 跨进程目录锁（SETTINGS_LOCK_STALE_MS + tryAcquireSettingsLock + reclaimStaleLock） |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L454-510 | runLockedSettingsMutation + runPureSettingsMutator（mutator 纯度校验） |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L612-690 | loadMcpSettingsFile + normalizeMcpServerOAuthState + resolveMcpServerRegistrations |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L692-817 | setMcpServerDisabled + getMcpServerOAuthState + listMcpServerOAuthStatuses |
| `sdk/packages/core/src/extensions/mcp/config-loader.ts` | L819-828 | registerMcpServersFromSettingsFile |
| `sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts` | L7-12 | PluginMcpServerResolution 接口 |
| `sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts` | L41-88 | isPluginMcpEnvValue + resolvePluginMcpEnv（fromEnv / value / required） |
| `sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts` | L90-221 | normalizePluginMcpServerRegistration（stdio / sse / streamableHttp 规范化） |
| `sdk/packages/core/src/extensions/mcp/plugin-server-registration.ts` | L223-260 | resolvePluginMcpServerRegistrations（多源聚合 + owner 去重） |
| `sdk/packages/shared/src/llms/tools.ts` | L7-18 | ToolPolicy 接口（enabled / autoApprove） |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/mcp/__init__.py` | L1-33 | 模块导出入口 + 工作流程说明 |
| `agent/mcp/client.py` | L47-94 | MCPToolDef / MCPResourceDef 数据类 |
| `agent/mcp/client.py` | L101-156 | MCPClient 构造 + ensure_connected 懒连接 |
| `agent/mcp/client.py` | L188-214 | _spawn_process（asyncio.create_subprocess_exec） |
| `agent/mcp/client.py` | L216-253 | _do_initialize（手写 initialize + notifications/initialized） |
| `agent/mcp/client.py` | L255-329 | list_tools / call_tool（tools/list + tools/call） |
| `agent/mcp/client.py` | L331-401 | list_resources / read_resource（resources/list + resources/read） |
| `agent/mcp/client.py` | L461-544 | _send_request_stdio（newline 协议 + readline） |
| `agent/mcp/client.py` | L546-577 | _send_request_http（urllib 单次 POST） |
| `agent/mcp/client.py` | L605-642 | _resolve_env_value（${VAR} 模板解析） |
| `agent/mcp/registry.py` | L41-64 | MCPServerConfig 数据类 |
| `agent/mcp/registry.py` | L67-82 | MCPToolPolicy 数据类（对标 Cline ToolPolicy） |
| `agent/mcp/registry.py` | L90-131 | MCPRegistry 构造 + 缓存字段 |
| `agent/mcp/registry.py` | L137-225 | load_config（PyYAML + 手写校验 + tool_policies 加载） |
| `agent/mcp/registry.py` | L242-274 | get_client（懒创建 + asyncio.Lock） |
| `agent/mcp/registry.py` | L276-315 | list_tools / list_all_tools（带缓存） |
| `agent/mcp/registry.py` | L317-335 | get_tool_policy（二元组 key 查询） |
| `agent/mcp/registry.py` | L337-390 | call_tool（策略查询 + enabled=false 拦截） |
| `agent/mcp/registry.py` | L411-443 | read_resource |
| `agent/mcp/registry.py` | L445-456 | close_all |
| `agent/mcp/registry.py` | L458-501 | build_servers_summary（system prompt 概览） |
| `agent/mcp/registry.py` | L508-525 | get_registry 全局单例 + _registry_lock |
| `agent/mcp/name_transform.py` | L29-78 | default_mcp_tool_name_transform（SHA1 8 位 + 55 截断 + _hash，未启用） |
| `agent/tools/mcp.py` | L1-29 | 模块 docstring（对标 Cline use_mcp_tool / access_mcp_resource） |
| `agent/tools/mcp.py` | L46-197 | UseMcpToolTool（调度器工具，60s 超时） |
| `agent/tools/mcp.py` | L205-352 | AccessMcpResourceTool（调度器工具，60s 超时） |
| `agent/runtime.py` | L1596-1644 | _get_mcp_tool_policy_override（调度器侧策略查询） |
| `agent/server.py` | L1779-1826 | /mcp/servers 端点 |
| `agent/server.py` | L1829-1868 | /mcp/resources 端点 |
| `agent/server.py` | L1871-1893 | /mcp/reload 端点（close_all + load_config） |
| `agent/context.py` | L788-834 | _build_mcp_servers_section（system prompt 概览段） |
| `agent_config/mcp_servers.yaml` | L1-86 | YAML 配置示例 + tool_policies 段 |

---

## 八、结论

P3.19 MCP 工具对比的核心结论：

1. **范式差异是设计选择，非缺陷**：Cline 的 first-class 工具模式 vs Charles 的调度器模式，两种范式都能调用 MCP 工具和读取资源。Charles 的调度器模式在 `name_transform.py` docstring 中明确说明是有意为之的简化设计，LLM context 更小，适合 token 受限场景。

2. **核心协议层已对齐**：MCP 协议方法（initialize / tools/list / tools/call / resources/list / resources/read / notifications/initialized）、协议版本（2024-11-05）、JSON-RPC 2.0 格式、客户端名称（各自正确）、超时控制等核心协议层在两侧都有对应实现。

3. **Charles 缺少五个抽象层**（已知差异，建议不修复）：
   - first-class 工具展开（`createMcpTools`）— Charles 用调度器模式替代
   - OAuth 浏览器流（`authorizeMcpServerOAuth`）— Charles 用静态 Bearer Token 替代
   - SSE / streamableHttp / framed 传输协议 — Charles 仅支持 stdio + http
   - 跨进程文件锁 + 原子写 + mutator 纯度校验 — Charles 单进程无此需求
   - 插件 MCP 服务器系统（`plugin-server-registration`）— Charles 无插件系统

4. **Charles 在三个点上独有实现**（应予保留）：
   - 调度器模式工具（`UseMcpToolTool` / `AccessMcpResourceTool`）— Cline 无对应实现
   - 调度器侧策略查询（`_get_mcp_tool_policy_override`）— Cline 在 first-class 模式下天然按工具名查询
   - MCP REST API（`/mcp/servers` / `/mcp/resources` / `/mcp/reload`）— Cline 通过 SDK API 调用

5. **name-transform 算法等价但未启用**：Charles 的 `default_mcp_tool_name_transform` 与 Cline `defaultMcpToolNameTransform` 算法**完全等价**（SHA1 8 位 + 55 截断 + `_hash` 后缀，总长 ≤ 64），但 Charles 因调度器模式不需要 name-transform，模块作为未启用工具函数保留。

6. **nanobot 残留**：P3.19 核心文件**完全无 nanobot 残留**（0 注释残留 + 0 实现逻辑残留），是 P3.x 系列中清理最彻底的模块。所有 docstring 和注释统一标注"对标 Cline"，无历史溯源引用 nanobot。

7. **策略机制功能等价但 key 结构不同**：Cline 用 name-transform 后的扁平 key（`filesystem__read_file_abc12345`），Charles 用二元组 key（`("filesystem", "read_file")`）。两者都能实现 enabled=false 禁用和 auto_approve=false 强制审批，但 Cline 是编译时过滤（工具不出现在 LLM 列表），Charles 是运行时拦截（工具调用时返回错误）。

**整体一致性等级**：**低**。P3.19 是 P3.x 系列中一致性最低的子阶段（43 项中 16 项低一致性），但这反映的是**两种合理的范式选择**而非缺陷。Charles 的调度器模式在 docstring 中明确说明，name_transform 模块作为未启用工具函数保留，策略机制通过调度器侧查询实现功能等价。P3.19 范围内无需阻塞性修复，所有低一致性项均为已知差异且建议不修复。
