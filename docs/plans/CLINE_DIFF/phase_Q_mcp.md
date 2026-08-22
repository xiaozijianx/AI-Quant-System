# Phase Q: MCP 集成 对比报告

> 对标源码：`sdk/packages/core/src/extensions/mcp/`（client.ts / config-loader.ts / manager.ts / policies.ts / name-transform.ts / plugin-server-registration.ts / tools.ts / oauth.ts / types.ts / index.ts）+ `runtime/orchestration/runtime-builder.ts`
> 当前实现：`agent/mcp/__init__.py` + `agent/mcp/client.py` + `agent/mcp/registry.py` + `agent/mcp/name_transform.py` + `agent/tools/mcp.py` + `agent_config/mcp_servers.yaml` + `agent/server.py`（MCP API）+ `agent/context.py`（system prompt 注入）
> 对比维度：Q1-Q16

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 1 项 |
| 弱对齐 | 8 项 |
| 缺失 | 3 项（其中 2 项为合理特化） |
| 额外增强 | 4 项 |
| **对齐度** | **约 65%** |

说明：
- 完全一致项为 Q9（name-transform 算法逐行等价移植）。
- 弱对齐项核心 JSON-RPC / stdio / http / 配置 / 缓存 / 重试 / 工具注册架构可工作，但在并发模型、协议模式、传输类型、TTL、文件锁等细节上与 Cline 存在差距。
- 缺失项中 Q5（OAuth）与 Q10（插件注册）属量化场景合理特化（本地 stdio MCP + 单一配置源，无远程 OAuth 服务器与插件生态需求），仅 Q8（per-tool policies）为真正功能缺口。
- 额外增强项（`${VAR}` 解析、真懒连接、`/mcp/reload` 端点、system prompt 概览段）为本系统在量化场景下的合理补强，应保留。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| Q1 | MCPClient 协议实现 | `client.ts`（StdioMcpClient + SdkUrlMcpClient） | `agent/mcp/client.py`（MCPClient） | 弱对齐 |
| Q2 | JSON-RPC 2.0 实现 | `client.ts` L19-36, L360-425 | `agent/mcp/client.py` L461-597 | 弱对齐 |
| Q3 | stdio 传输 | `client.ts` L63-307（newline + framed 双模式） | `agent/mcp/client.py` L188-214, L482-544（仅 newline） | 弱对齐 |
| Q4 | http 传输 | `client.ts` L443-570（SSE + StreamableHTTP via SDK） | `agent/mcp/client.py` L546-577（urllib POST） | 弱对齐 |
| Q5 | OAuth 认证 | `oauth.ts`（完整 PKCE + 本地回调服务器） | 无 | 缺失（合理特化） |
| Q6 | 配置格式 | `config-loader.ts`（JSON + 原子写 + 跨进程锁 + zod） | `agent/mcp/registry.py`（YAML，无锁无原子写） | 弱对齐 |
| Q7 | `${ENV_VAR}` 解析 | `config-loader.ts` 无；`plugin-server-registration.ts` 有 `fromEnv` | `agent/mcp/client.py` L605-642 `_resolve_env_value` | 额外增强 |
| Q8 | policies.ts 工具策略 | `policies.ts` + `shared/llms/tools.ts`（enabled + autoApprove） | 无 | 缺失 |
| Q9 | name-transform（SHA1 截断） | `name-transform.ts` L1-35 | `agent/mcp/name_transform.py` L1-79 | 完全一致 |
| Q10 | plugin-server-registration | `plugin-server-registration.ts`（插件 MCP + fromEnv + 去重） | 无 | 缺失（合理特化） |
| Q11 | 工具注册为独立 LLM function | `tools.ts`（createMcpTools 展开 N 个 AgentTool） | `agent/tools/mcp.py`（单个 use_mcp_tool） | 弱对齐 |
| Q12 | 懒连接（首次调用才连接） | `manager.ts` ensureConnectedClient（但 startup 强制 listTools 枚举） | `agent/mcp/registry.py` + `client.py` ensure_connected（真懒连接） | 额外增强 |
| Q13 | 连接重试 | `client.ts` L158-184（newline→framed 协议回退） | `agent/mcp/client.py`（无回退，下次调用隐式重试） | 弱对齐 |
| Q14 | 工具/资源缓存 | `manager.ts` L13, L131-153（TTL 5s + cloneTools） | `agent/mcp/registry.py` L104-107（永久缓存 + resources 缓存） | 弱对齐 |
| Q15 | 配置热加载 | `config-loader.ts`（细粒度 mutation API，无全量 reload） | `agent/server.py` L1483-1505 `POST /mcp/reload` | 额外增强 |
| Q16 | MCP 服务器概览注入 system prompt | 无（依赖 Q11 工具作为独立 function 暴露） | `agent/context.py` L311-368 `_build_mcp_servers_section` | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #Q1：MCPClient 协议实现（resources 接口超集，工具协议对齐）

**严重度**：P3（架构差异，非缺陷）

**Cline 实现**：
- `McpServerClient` 接口（`types.ts` L92-101）仅声明四个方法：`connect()` / `disconnect()` / `listTools()` / `callTool()`。
- `StdioMcpClient`（`client.ts` L126-434）实现 stdio 上的 initialize + tools/list + tools/call。
- `SdkUrlMcpClient`（`client.ts` L443-570）通过 MCP SDK 的 `Client` 实现 SSE/streamableHttp 上的 listTools + callTool。
- Cline 不在 `McpServerClient` 抽象层暴露 resources/list 与 resources/read（resources 能力由 SDK Client 内部支持，但 manager 与 tools.ts 不使用）。

**我的实现**：
- `MCPClient`（`agent/mcp/client.py` L101-597）实现：`ensure_connected()`（含 initialize + notifications/initialized）、`list_tools()`、`call_tool()`、`list_resources()`、`read_resource()`、`ping()`、`close()`（含 shutdown）。
- initialize 握手 params 中声明 `capabilities: {"roots": {"listChanged": False}}`，Cline 声明 `capabilities: {}`（语义微差，不影响功能）。

**影响**：
- initialize / tools/list / tools/call 三方法行为对齐。
- resources/list + resources/read 为超集，用于支撑 `access_mcp_resource` 工具（Cline 无此工具）。这是合理增强，因为本系统通过 `access_mcp_resource` 暴露资源读取能力。
- 客户端能力声明微差（roots capability）不影响 MCP 服务器行为（服务器通常忽略客户端 capabilities）。

**修复建议**：保持现状。resources 接口为 access_mcp_resource 工具所需，属合理超集。

**优先级**：P3

---

### 差距 #Q2：JSON-RPC 2.0 并发模型不同

**严重度**：P2（高并发场景下性能差异，量化场景影响小）

**Cline 实现**：
- `JsonRpcRequest` 类型（`client.ts` L19-24）：`{jsonrpc:"2.0", id:number, method, params?}`。
- `pending` Map（L130-137）按 id 索引 `{resolve, reject, timeout}`，支持多个 in-flight 请求并发。
- `request()`（L360-408）：分配 id → 写入 stdin → 返回 pending Promise；响应到达时按 id 路由到对应 pending。
- `notify()`（L410-425）：无 id，无等待。
- 默认请求超时 5000ms，连接超时 1500ms。
- 响应处理（`handleStdout` L309-339）：解析消息 → 按 id 查 pending → resolve/reject → 清除 timeout。

**我的实现**：
- 请求 dict（`client.py` L223-238 等）：`{jsonrpc:"2.0", id, method, params}`，结构一致。
- `_send_request_stdio()`（L482-544）：写一行 → `readline()` 阻塞读一行 → id 校验，不匹配则递归读下一行。
- `_send_notification()`（L579-597）：stdio 写入即返回；http 模式下通知也 POST 但忽略响应。
- 默认请求超时 30s。
- `_write_lock`（L156）串行化 stdin 写入，但读响应仍是阻塞式串行。

**影响**：
- Cline 支持并发 in-flight 请求（多请求同时等待响应，按 id 路由）；我的实现是写-读串行（一次只处理一个请求），MCP 协议本身是串行的所以功能等价，但并发性能差。
- 我的 id 不匹配时递归读取（`client.py` L535-542）在通知密集时可能栈深，且无超时保护（递归路径不重置 timeout）。
- 超时阈值差异（Cline 5s，我 30s）——我的更宽松，适合慢速 MCP 工具，但失败感知更慢。

**修复建议**：
- 短期：保持串行模型（量化场景单 agent 调用 MCP 工具频率低，串行足够）。
- 中期：改用 Cline 的 pending Map + asyncio.Future 模式，支持并发 in-flight 请求，按 id 路由响应。消除递归读取，改为循环 + timeout。

**优先级**：P2

---

### 差距 #Q3：stdio 传输缺少 framed 协议模式

**严重度**：P2（影响部分 MCP 服务器兼容性）

**Cline 实现**：
- 双协议模式（`client.ts` L38, L158-184）：先尝试 `"newline"`（换行分隔 JSON），失败再尝试 `"framed"`（LSP 风格 `Content-Length: N\r\n\r\n<body>`）。
- `FramedMessageParser`（L63-100）+ `NewlineMessageParser`（L102-124）。
- `encodeFramedMessage` / `encodeNewlineMessage`（L50-61）。
- stderr buffer 16KB 上限（L280-282），用于错误诊断。
- 进程 exit/error 事件触发 `failAllPending`（L284-306）。
- win32 平台 `windowsHide: true, shell: true`（L256-262）。

**我的实现**：
- 仅 newline 模式（`client.py` L495-496）：`json.dumps + "\n"`。
- 无 framed 解析器，无协议回退。
- stderr 仅在 stdout 读到空行时按需读取 2048 字节（L513-522），无主动 buffer。
- 进程异常在下次调用时通过空响应感知，无主动事件回调。
- 无 shell 选项，直接 `create_subprocess_exec`。

**影响**：
- 部分 MCP 服务器（如基于 LSP 框架的）只支持 framed 模式，我的实现无法连接。
- stderr 不缓冲导致进程崩溃时错误信息可能丢失（仅在空响应时尝试读一次）。
- 无进程 exit 主动回调，连接状态可能滞后。

**修复建议**：
- 中期：实现 `FramedMessageParser` + `NewlineMessageParser`，连接时先 newline 后 framed 回退（参照 Cline `connect()` L158-184）。
- 中期：增加 stderr 持续 buffer（16KB 上限），进程 exit/error 时 failAllPending。
- 短期：win32 下加 `shell=True` 选项以兼容 PATH 解析（参照 Cline L260）。

**优先级**：P2

---

### 差距 #Q4：http 传输不支持 SSE / StreamableHTTP

**严重度**：P2（影响 HTTP MCP 服务器兼容性）

**Cline 实现**：
- `SdkUrlMcpClient`（`client.ts` L443-570）通过 MCP SDK 的 `SSEClientTransport`（sse 类型）和 `StreamableHTTPClientTransport`（streamableHttp 类型）建立长连接。
- SSE：服务器推送事件流，支持服务器主动推送与长会话。
- StreamableHTTP：MCP 标准的流式 HTTP 传输。
- 与 OAuth 集成（通过 `authProvider`）。
- 配置区分 `sse` 与 `streamableHttp` 两种 transport type（`config-loader.ts` L47-57）。

**我的实现**：
- `_send_request_http()`（`client.py` L546-577）：每次请求 `urllib.request.urlopen` POST 一条 JSON-RPC，读取一次响应即返回。
- 无长连接，无 SSE 订阅，无流式传输。
- 仅支持 `http` 一种 transport type（`registry.py` L57, L169）。
- headers 支持手动 Authorization（如 `Bearer xxx`），但无 OAuth 自动刷新。

**影响**：
- 仅支持 stateless HTTP JSON-RPC 的 MCP 服务器可工作；SSE/streamableHttp 标准服务器无法工作。
- MCP 规范推荐 SSE/streamableHttp 作为 HTTP 传输，本实现对 HTTP MCP 生态兼容性受限。
- 量化场景当前以本地 stdio MCP 为主（见 `mcp_servers.yaml` 示例），HTTP 服务器需求低，影响可控。

**修复建议**：
- 长期：引入 `httpx` + `sseclient` 或直接依赖 `mcp` Python SDK（官方 `mcp` 包提供 SSEClientTransport / StreamableHTTPTransport），替换 urllib 实现。
- 区分 `sse` / `streamableHttp` 配置项。
- 短期：保持 urllib POST，文档标注"仅支持 stateless HTTP MCP 服务器"。

**优先级**：P2

---

### 差距 #Q5：OAuth 认证缺失

**严重度**：P3（量化场景合理特化）

**Cline 实现**：
- `oauth.ts` 实现完整 OAuth 2.0 Authorization Code + PKCE 流程：
  - 本地回调服务器（`startLocalOAuthServer`，端口 1456/1457/1458，5 分钟超时）。
  - `OAuthClientProvider` 实现：`redirectUrl` / `clientMetadata` / `state` / `clientInformation` / `tokens` / `codeVerifier` / `discoveryState` 等。
  - 状态持久化到 settings JSON 文件（`updateMcpServerOAuthState`）。
  - `authorizeMcpServerOAuth` 入口：发现 → 跳转授权 URL → 等待回调 → 交换 token → 重试连接。
  - Token 刷新与失效处理（`invalidateCredentials` scope: all/client/tokens/verifier/discovery）。
  - `UnauthorizedError` 捕获后生成可读错误信息含授权 URL。

**我的实现**：
- 无 OAuth 模块。
- HTTP 模式仅支持 `headers` 字段手动传 Bearer token（`mcp_servers.yaml` 示例 3）。

**影响**：
- 无法连接需要 OAuth 的远程 MCP 服务器（如 Anthropic / Zapier 等托管 MCP 服务）。
- 量化场景 MCP 服务器以本地 stdio 为主（数据查询、文件系统等），无 OAuth 需求。
- 手动 Bearer token 方式可覆盖简单鉴权场景。

**修复建议**：标注为"合理特化"，暂不实现。若未来接入远程托管 MCP 服务，再引入 `mcp` Python SDK 的 OAuth 支持或参照 Cline oauth.ts 移植。

**优先级**：P3（合理特化）

---

### 差距 #Q6：配置格式与并发安全

**严重度**：P2（多进程并发写场景有风险，量化场景单进程影响小）

**Cline 实现**：
- JSON 格式（`config-loader.ts`）：`mcpSettingsSchema` zod 校验，`mcpServers` 为 `Record<string, RegistrationBody>`（按 name 索引，天然去重）。
- 三种 transport type：`stdio` / `sse` / `streamableHttp`（`config-loader.ts` L39-63）。
- 原子写：`atomicWriteSettingsFile`（L245-261）temp 文件 + rename。
- 跨进程锁：directory lock + owner marker（L288-386），10s stale reclaim，25ms 轮询，sync/async 双版本。
- 纯函数校验：`runPureSettingsMutator`（L530-551）双重调用对比防止 mutator 副作用。
- 旧格式迁移：`legacyStdioRegistrationSchema` / `legacyUrlRegistrationSchema`（L96-169）将扁平 command/url 结构转换为嵌套 transport。
- 运行时 API：`setMcpServerDisabled` / `updateMcpServerOAuthState` / `getMcpServerOAuthState` / `listMcpServerOAuthStatuses`。
- OAuth state 存储于 settings 文件。

**我的实现**：
- YAML 格式（`registry.py` L116-180）：`yaml.safe_load`，`servers` 为 list（数组，不去重）。
- 两种 transport type：`stdio` / `http`（不区分 sse/streamableHttp）。
- 无原子写（直接 `open` + `yaml.safe_load`，写场景由用户手动编辑文件）。
- 无跨进程锁（单进程单例 `get_registry()`）。
- 无 schema 校验（仅字段存在性检查 `registry.py` L166-171）。
- 无旧格式迁移。
- 无运行时 toggle API（`enabled` 字段需 reload）。
- 无 OAuth state 存储。

**影响**：
- 格式差异（YAML vs JSON）合理：YAML 支持注释，对用户友好；Cline 用 JSON 因其面向多客户端共享配置。
- 数组 vs dict：我的数组允许同名重复，后加载覆盖前者（潜在歧义）。
- 无原子写/锁：单进程下无影响，但若未来多进程（如多 worker）共享配置则有竞态。
- 无 schema 校验：配置错误仅在运行时连接失败时暴露，Cline 在加载时即报错。
- 无运行时 toggle：禁用某服务器需 reload 整个配置（关闭所有连接）。

**修复建议**：
- 短期：将 `servers` 改为 dict 按 name 索引（避免重复），增加 schema 校验（pydantic 或手动）。
- 中期：实现 `set_server_enabled(name, enabled)` 运行时 toggle API，避免全量 reload。
- 长期：若引入多进程，参照 Cline 实现文件锁（Python 可用 `filelock` 库 + 原子写）。

**优先级**：P2

---

### 差距 #Q7：${ENV_VAR} 解析（额外增强）

**严重度**：增强项（无差距，标注语义差异）

**Cline 实现**：
- `config-loader.ts` 中 `transport.env` 为 `Record<string, string>`（zod `stringRecordSchema`），值直接作为字面量传给子进程，**无 `${VAR}` 插值**。
- `plugin-server-registration.ts` 的 `resolvePluginMcpEnv`（L54-88）支持结构化 env 值：`{fromEnv: "VAR_NAME", value: "fallback", required: true}` —— `fromEnv` 读取 `process.env[VAR_NAME]`，`value` 为 fallback，`required` 为 true 时缺失则报错。
- 即 Cline 仅在插件 MCP 场景支持 env 引用，且用结构化对象而非字符串模板。

**我的实现**：
- `_resolve_env_value()`（`client.py` L605-642）：用正则 `\$\{([^}]+)\}` 匹配 `${VAR}` 语法，从 env dict 取值替换，未找到则保留原样。
- 支持 `${VAR}` 嵌套（3 次迭代替换）。
- 在 `_spawn_process()` 合并 env 时应用（L196-197）：`merged_env[key] = _resolve_env_value(value, merged_env)`。

**影响**：
- 我的 `${VAR}` 语法对 YAML 配置更友好（避免硬编码 API key），是合理增强。
- 语义差异：Cline 期望 config 中的 env 值为字面量（secrets 直接写在 JSON 或通过插件 fromEnv）；我期望 config 中的 env 值可含 `${VAR}` 引用。
- 量化场景：YAML + `${VAR}` 让用户能把 `api_key: ${MCP_API_KEY}` 写在配置里，运行时从系统环境变量解析，符合 12-factor app 实践。

**修复建议**：保留为额外增强。文档中明确标注语义差异（配置值支持 `${VAR}` 插值）。

**优先级**：增强项（不修复）

---

### 差距 #Q8：policies.ts 工具策略缺失

**严重度**：P1（安全相关，per-tool auto-approve 控制）

**Cline 实现**：
- `ToolPolicy` 类型（`shared/llms/tools.ts` L7-18）：`{enabled?: boolean (default true), autoApprove?: boolean (default true)}`。
- `policies.ts`：
  - `createDisabledMcpToolPolicy(serverName, toolName)`：用 `nameTransform` 计算展开后的工具名，返回 `{[name]: {enabled: false}}`。
  - `createDisabledMcpToolPolicies`：批量版本。
- `toolPolicies` map 传入 runtime（`shared/agents/types.ts` L797），runtime 在工具执行前查询策略：`enabled: false` 跳过执行，`autoApprove: false` 触发 `requestToolApproval` 回调请求用户批准。
- 即 Cline 支持按工具粒度：禁用某 MCP 工具 / 要求用户批准某 MCP 工具。

**我的实现**：
- 无 per-tool policy 概念。
- 所有 MCP 工具通过单一 `use_mcp_tool` 调用，`read_only=True`（`mcp.py` L104-107, L253-255），runtime 自动批准且可并行。
- 无机制禁用某个具体 MCP 工具（server_name + tool_name 组合）。
- 无机制要求用户批准某个 MCP 工具调用。

**影响**：
- 无法对敏感 MCP 工具（如执行交易的 MCP 工具）强制人工审批，存在安全风险。
- 无法在配置层禁用某 MCP 服务器的部分工具（只能整体 enabled/disabled 服务器）。
- 量化场景下若 MCP 工具涉及下单/资金操作，缺少 auto-approve=false 机制是真实安全缺口。

**修复建议**：
- 中期：在 `mcp_servers.yaml` 增加 `tool_policies` 段，支持 per-tool `enabled` / `auto_approve` 配置：
  ```yaml
  tool_policies:
    - server: trading
      tool: place_order
      auto_approve: false  # 调用前需用户确认
    - server: filesystem
      tool: delete_file
      enabled: false        # 完全禁用
  ```
- 在 `UseMcpToolTool._execute` 调用 `registry.call_tool` 前查询策略：`enabled: false` 返回错误；`auto_approve: false` 走 approval 流程（对接现有 `agent/approval.py`）。
- 短期：至少在配置层支持 `disabled_tools: [server/tool]` 列表禁用某些工具。

**优先级**：P1

---

### 差距 #Q9：name-transform（SHA1 截断）

**严重度**：无差距（完全一致）

**Cline 实现**（`name-transform.ts`）：
- `MAX_MCP_TOOL_NAME_LENGTH = 64`
- `INVALID_MCP_TOOL_NAME_CHARACTERS = /[^a-zA-Z0-9_-]+/g`
- `HASH_LENGTH = 8`，`HASH_SEPARATOR_LENGTH = 1`，`FALLBACK_BASE_NAME = "mcp_tool"`
- `buildMcpToolNameHash(value) = sha1(value).hex().slice(0, 8)`
- `sanitizeMcpToolNameCandidate(value) = value.replace(INVALID, "_")`
- `defaultMcpToolNameTransform({serverName, toolName})`：
  - `rawName = `${serverName}__${toolName}``
  - `sanitizedName = sanitize(rawName)`
  - if `sanitizedName === rawName && rawName.length <= 64` return `rawName`
  - else `baseName = sanitizedName.slice(0, 64-1-8) || "mcp_tool"`; return `${baseName}_${hash}`

**我的实现**（`agent/mcp/name_transform.py`）：
- 常量逐字相同（L29, L32, L35-36, L39）。
- `_build_mcp_tool_name_hash`（L42-44）：`hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]` —— 与 Cline sha1 hex slice 0..8 等价。
- `_sanitize_mcp_tool_name_candidate`（L47-49）：`re.sub(r"[^a-zA-Z0-9_-]+", "_", value)` —— 与 Cline 正则等价。
- `default_mcp_tool_name_transform(server_name, tool_name)`（L52-79）：逻辑分支与 Cline 完全一致（合法且未超长直接返回，否则截断 + hash 后缀）。

**影响**：算法逻辑完全等价。

**注意**：
- 当前 `name_transform.py` 在 registry 中**未被调用**（见模块 docstring L14-16："本系统的 MCP 工具通过 use_mcp_tool 统一调用，MCP 工具名不直接作为 LLM function name 暴露，因此不需要在 registry 中强制应用此转换"）。
- Cline 在 `tools.ts` 的 `createMcpTools` 与 `policies.ts` 中调用 name-transform，因为 Cline 将每个 MCP 工具展开为独立 LLM function。
- 本系统因 Q11 架构不同（单一 use_mcp_tool），name-transform 暂未启用，作为未来扩展预留。

**修复建议**：保持现状。函数已实现且通过 `test_phase32_3_name_transform.py` 验证，未来若改为 Cline 式工具展开可立即启用。

**优先级**：无（完全一致）

---

### 差距 #Q10：plugin-server-registration 缺失

**严重度**：P3（量化场景合理特化）

**Cline 实现**：
- `plugin-server-registration.ts`：
  - `normalizePluginMcpServerRegistration(server)`：校验插件声明的 MCP 服务器配置（name 必填、transport type 合法、stdio 需 command、sse/http 需 url）。
  - `resolvePluginMcpEnv(server)`：解析结构化 env `{fromEnv, value, required}` —— `fromEnv` 读 `process.env`，`value` 为 fallback，`required` 缺失报错。
  - `resolvePluginMcpServerRegistrations(servers)`：跨 owner 检测同名 MCP 服务器冲突（first-owner-wins，后续标记 `loadError: "duplicate"`）。
  - 返回 `PluginMcpServerResolution<TOwner>` 含 owner / name / registration / loadError。

**我的实现**：
- 无插件系统。
- MCP 配置仅从单一 `mcp_servers.yaml` 加载（`registry.py` L116-180）。

**影响**：
- 无法通过插件动态注册 MCP 服务器。
- 量化场景无插件生态，单一配置源足够。
- 语义差异：Cline 区分"用户配置"（config-loader）与"插件配置"（plugin-server-registration）两个来源；本系统只有用户配置一个来源。

**修复建议**：标注为"合理特化"，暂不实现。若未来引入插件系统，再参照 Cline 移植。

**优先级**：P3（合理特化）

---

### 差距 #Q11：工具注册架构（单个 use_mcp_tool vs N 个独立 function）

**严重度**：P2（LLM 调用体验差异，非缺陷）

**Cline 实现**：
- `tools.ts` 的 `createMcpTools({serverName, provider, ...})`（L16-46）：
  - 调用 `provider.listTools(serverName)` 获取工具描述符列表。
  - 对每个 descriptor，用 `nameTransform({serverName, toolName: descriptor.name})` 计算 LLM 函数名（如 `filesystem__read_file` 或截断 hash 形式）。
  - `createTool({name: agentToolName, description: defaultMcpDescription(serverName, descriptor), inputSchema: descriptor.inputSchema, execute: (input) => provider.callTool({serverName, toolName, arguments: input})})` 创建独立 AgentTool。
  - 返回 `AgentTool[]`（N 个），并入 runtime 的 tool registry。
  - LLM 直接看到每个 MCP 工具作为独立 function，schema 由 MCP 服务器定义，LLM 强制类型校验。
- `runtime-builder.ts` 的 `loadConfiguredMcpTools`（L186-243）启动时遍历所有 enabled 服务器，`Promise.allSettled(createMcpTools(...))` 展开所有工具，失败的服务器跳过并 log。

**我的实现**：
- `agent/tools/mcp.py` 仅定义两个工具：
  - `UseMcpToolTool`（`use_mcp_tool`）：参数 `{server_name, tool_name, args}`，`args` 为 opaque object（无 per-tool schema）。
  - `AccessMcpResourceTool`（`access_mcp_resource`）：参数 `{server_name, uri}`。
- LLM 通过 system prompt 段（Q16）知道有哪些 server/tool，调用时填 `server_name` + `tool_name` + `args`。
- `args` 字段 schema 为 `{type: "object"}`（`mcp.py` L93-98），LLM 不强制具体 MCP 工具的参数 schema。

**影响**：
- LLM 体验：Cline 模式下 LLM 看到具体工具名和精确 schema，调用更准确；我的模式下 LLM 需读 system prompt 段，且 args 无 schema 约束，可能填错参数。
- Token 开销：Cline 模式 N 个工具 = N 个 function 定义（每个含 schema），工具多时 token 开销大；我的模式固定 2 个工具定义，token 开销恒定。
- 动态性：Cline 需在启动时枚举所有工具（触发连接）；我的模式延迟到首次调用才连接（Q12 真懒连接）。
- 错误处理：Cline 模式 LLM 直接看到 MCP 工具错误；我的模式错误包装在 use_mcp_tool 返回值中。
- name-transform：Cline 必须用 name-transform（避免名字冲突 + 长度限制）；我的模式不需要（tool_name 不直接作为 function name）。

**修复建议**：
- 短期：保持现状（单一 use_mcp_tool）。量化场景 MCP 工具数量少（通常 < 10），system prompt 段足够让 LLM 知道可用工具。token 节省对量化场景（长上下文）有价值。
- 中期：可选实现"混合模式"——对工具数少（< 5）的服务器展开为独立 function，对工具数多的服务器保留 use_mcp_tool。或加 `expand_tools: true` 配置项让用户选择。
- 注意：若改为 Cline 式展开，需同步实现 Q8 per-tool policies 与 Q9 name-transform 启用。

**优先级**：P2

---

### 差距 #Q12：懒连接（额外增强）

**严重度**：增强项（本系统更优）

**Cline 实现**：
- `manager.ts` 的 `ensureConnectedClient(state)`（L175-185）在 `listTools` / `callTool` / `refreshTools` 前调用 `connectState`，单 server 维度是懒连接。
- 但 `runtime-builder.ts` 的 `loadConfiguredMcpTools`（L186-243）在 session 启动时调用 `createMcpTools({serverName, provider: manager})`，而 `createMcpTools`（`tools.ts` L19）调用 `provider.listTools(serverName)` 触发 `manager.listTools` → `refreshTools` → `ensureConnectedClient` → `connectState`。
- 即 Cline 在 session 启动时为枚举工具**主动连接所有 enabled MCP 服务器**（eager connect for tool discovery）。
- 后续 `callTool` 复用已建立的连接。

**我的实现**：
- `registry.py` 的 `get_client(name)`（L197-229）仅创建 `MCPClient` 实例，不连接。
- `client.py` 的 `ensure_connected()`（L163-186）在 `list_tools` / `call_tool` / `list_resources` / `read_resource` 首次调用时才 spawn 进程 + initialize。
- `list_tools` 在 `refresh=False` 时优先返回缓存（`registry.py` L242-243），首次调用才触发连接。
- 即本系统**真懒连接**：直到 agent 实际调用某个 MCP 工具时才连接对应服务器。

**影响**：
- 本系统启动更快（无需连接所有 MCP 服务器）。
- 未使用的 MCP 服务器不消耗进程资源。
- 缺点：MCP 服务器故障在首次调用时才暴露（Cline 在启动时即发现）。
- 量化场景下 MCP 服务器通常按需使用（如盘后查数据），真懒连接节省资源。

**修复建议**：保留为额外增强。可选：在 `GET /mcp/servers?refresh=true` 时主动连接枚举（已在 `server.py` L1416 实现）。

**优先级**：增强项（不修复）

---

### 差距 #Q13：连接重试与协议回退

**严重度**：P3（影响 stdio 兼容性）

**Cline 实现**：
- `StdioMcpClient.connect()`（`client.ts` L148-190）：尝试 `attempts: StdioProtocolMode[] = ["newline", "framed"]`，先 newline 模式 spawn + initialize（1500ms 超时），失败则 disconnect + framed 模式重试。
- 即 stdio 连接有 1 次 protocol-mode 回退重试。
- `manager.ts` 的 `connectState`（L187-212）无重试，失败设 `status: "disconnected"` + `lastError`，抛出。
- 即 Cline 重试仅限协议模式回退，无通用 backoff 重试。

**我的实现**：
- `ensure_connected()`（`client.py` L163-186）无重试，spawn 或 initialize 失败直接 raise。
- 下次 `call_tool` 调用时因 `is_connected=False` 会重新尝试 `ensure_connected`（隐式重试，但无主动重试循环）。
- 无协议模式回退（仅 newline）。

**影响**：
- framed-only 的 MCP 服务器无法连接（Q3 已述）。
- spawn 失败（如命令不存在）立即报错，无重试（合理，因配置错误不会自愈）。
- 网络抖动场景下无指数退避重试（量化场景 MCP 通常本地，网络抖动少）。

**修复建议**：
- 中期：实现协议模式回退（与 Q3 一起做）。
- 短期：保持现状，隐式重试（下次调用重连）已覆盖大部分场景。
- 不建议加通用 backoff 重试（掩盖配置错误）。

**优先级**：P3

---

### 差距 #Q14：工具/资源缓存

**严重度**：P2（缓存陈旧性）

**Cline 实现**：
- `manager.ts` L13：`DEFAULT_TOOLS_CACHE_TTL_MS = 5000`（5 秒）。
- `toolCache` + `toolCacheUpdatedAt` per server（`ManagedServerState` L21-22）。
- `listTools(serverName)`（L131-138）：if `toolCache && nowMs() - fetchedAt <= TTL` return cached; else `refreshTools`。
- `refreshTools`（L140-153）：`runExclusive` 加锁 → `ensureConnectedClient` → `client.listTools()` → `cloneTools`（深拷贝，L29-37）→ 更新 cache + updatedAt。
- 无 resource 缓存（resources 不在 McpServerClient 接口）。
- `callTool` 不读 cache，直接走 `ensureConnectedClient` + `client.callTool`。

**我的实现**：
- `registry.py` L104-107：`_tools_cache` + `_resources_cache`（dict 永久缓存）。
- `list_tools(server_name, refresh=False)`（L231-258）：if `not refresh and server_name in cache` return cached; else 加锁 → `client.list_tools()` → 存 cache。
- `list_resources` 同理（L312-329）。
- 无 TTL（cache 永久有效，除非 `refresh=True` 或 `close_all`）。
- 无 clone（直接存 list 引用，调用方修改会污染 cache）。
- `call_tool` 不读 cache。

**影响**：
- 无 TTL：MCP 服务器工具列表变更（如热更新插件）后，我的 cache 不会自动失效，需手动 `refresh=True` 或 `/mcp/reload`。Cline 5s 自动失效。
- 资源缓存：我有，Cline 无（因 Cline 不暴露 resources 接口）。
- 无 clone：调用方若修改返回的 list 会污染 cache（当前调用方未修改，潜在风险）。
- 量化场景工具列表基本静态（MCP 服务器很少变更工具），无 TTL 影响小。

**修复建议**：
- 短期：`list_tools` 返回前 `list(tools)` 浅拷贝避免污染（或参照 Cline `cloneTools` 深拷贝）。
- 中期：加 TTL（如 60s，量化场景可较 Cline 5s 长）。
- 保留资源缓存（合理增强）。

**优先级**：P2

---

### 差距 #Q15：配置热加载（额外增强）

**严重度**：增强项（本系统更优）

**Cline 实现**：
- `config-loader.ts` 提供细粒度 mutation API：
  - `setMcpServerDisabled({name, disabled})`：单 server 启停（L692-725），加锁读改写。
  - `updateMcpServerOAuthState(serverName, updater)`：单 server OAuth 状态更新。
  - `updateMcpSettingsFile(filePath, mutator)`：通用 locked read-modify-write。
- 但**无全量 reload 端点**：session 启动后 `loadConfiguredMcpTools` 加载的工具与 manager 状态在内存中持有，新增 server 需重启 session 或手动调用 `manager.registerServer`。
- 配置变更通过文件锁原子写入，但运行时 manager 不会自动感知文件变化。

**我的实现**：
- `agent/server.py` L1483-1505 `POST /mcp/reload`：
  - `await registry.close_all()`（关闭所有客户端连接 + 清空 cache）。
  - `registry.load_config()`（重新读 YAML）。
  - 下次工具调用时按新配置懒连接。
- `GET /mcp/servers`（L1391-1438）：列出服务器 + 工具，支持 `refresh=true` 强制刷新工具 cache。
- `GET /mcp/resources`（L1441-1480）：列出资源。

**影响**：
- 本系统支持运行时全量热加载（修改 YAML 后 POST /mcp/reload 即生效，无需重启）。
- Cline 支持细粒度单 server toggle，但无全量 reload。
- 代价：我的 reload 关闭所有连接（包括正在使用的），有短暂中断；Cline 的 setMcpServerDisabled 只影响目标 server。

**修复建议**：保留为额外增强。可选中期补一个 `POST /mcp/servers/{name}/toggle` 细粒度端点（参照 Cline `setMcpServerDisabled`），避免全量 reload 中断。

**优先级**：增强项（不修复）

---

### 差距 #Q16：MCP 服务器概览注入 system prompt（额外增强）

**严重度**：增强项（架构上必要）

**Cline 实现**：
- **不注入** system prompt 段。
- MCP 工具通过 Q11 的 `createMcpTools` 展开为独立 LLM function，工具名 + description + inputSchema 直接在 LLM 的 tool 列表中可见。
- LLM 通过 function 列表知道有哪些 MCP 工具可用，无需 system prompt 提示。
- `disableMcpSettingsTools` 配置项（`runtime-builder.ts` L293）控制是否加载 MCP 工具。

**我的实现**：
- `agent/context.py` L207-211：system prompt 构建时调用 `_build_mcp_servers_section()`。
- `_build_mcp_servers_section()`（L311-368）：
  - 列出每个 server（name + transport note + description）。
  - 从 `_tools_cache` 读工具列表（cache 命中时列工具名 + 描述首行 80 字符）。
  - cache 未命中时提示"工具列表未加载，调用 use_mcp_tool 时会自动连接并加载"。
  - 指导 LLM 用 `use_mcp_tool(server_name, tool_name, args)` / `access_mcp_resource(server_name, uri)`。
- `registry.py` 的 `build_servers_summary()`（L378-421）提供等价方法（同步版）。

**影响**：
- 本系统因 Q11 选择单一 use_mcp_tool，**必须**有 system prompt 段让 LLM 知道可用 server/tool，否则 LLM 无法调用。
- 该段依赖 `_tools_cache`，若工具未加载（无人调用过）则段内只列 server 名不列工具——LLM 可能不知道具体工具名。
- Cline 模式下 LLM 直接看到工具，无需 system prompt 提示，信息更完整。
- 量化场景工具数少，system prompt 段开销可接受。

**修复建议**：
- 短期：在 `GET /mcp/servers` 调用时主动预加载工具 cache（已在 server.py 实现），让 system prompt 段能列全工具。
- 中期：考虑首次构建 system prompt 时触发 `list_all_tools()` 预加载（同步阻塞，需评估延迟）。
- 保留为额外增强（架构上必要，非冗余）。

**优先级**：增强项（不修复）

---

## 4. 一致性统计

| 一致性等级 | 数量 | 子项 |
|-----------|------|------|
| 完全一致 | 1 | Q9 |
| 弱对齐 | 8 | Q1, Q2, Q3, Q4, Q6, Q11, Q13, Q14 |
| 缺失（合理特化） | 2 | Q5, Q10 |
| 缺失（真缺口） | 1 | Q8 |
| 额外增强 | 4 | Q7, Q12, Q15, Q16 |
| **合计** | **16** | — |

按优先级分布：
- P1（真缺口，需修复）：Q8（per-tool policies）—— 1 项
- P2（弱对齐，建议修复）：Q2, Q3, Q4, Q6, Q11, Q14 —— 6 项
- P3（合理特化或低影响）：Q1, Q5, Q10, Q13 —— 4 项
- 增强项（保留）：Q7, Q9（已一致）, Q12, Q15, Q16 —— 5 项

**对齐度计算**：
- 完全一致 + 额外增强 = 5 项（31%）完全等价或更优
- 合理特化缺失 = 2 项（12.5%）量化场景可接受
- 弱对齐 = 8 项（50%）功能可用但有差距
- 真缺口 = 1 项（6%）需修复

综合对齐度 ≈ (5 + 2 + 8×0.5) / 16 = 11/16 ≈ **65%**

---

## 5. 修复建议

### 短期（1-2 天，低成本高收益）

1. **Q8 per-tool policies（P1）**：在 `mcp_servers.yaml` 增加 `tool_policies` 段，至少支持 `enabled: false` 禁用某些 MCP 工具（如 `trading/place_order`）。在 `UseMcpToolTool._execute` 调用前查询策略，禁用工具返回错误。这是唯一 P1 真缺口，优先修复。
2. **Q14 缓存 clone**：`list_tools` / `list_resources` 返回前 `list(...)` 浅拷贝，避免调用方污染 cache。
3. **Q6 配置去重**：将 `servers` list 改为 dict 按 name 索引（或加载时检测重复并 warn）。

### 中期（1-2 周，提升兼容性）

1. **Q3 framed 协议**：实现 `FramedMessageParser` + `NewlineMessageParser`，连接时先 newline 后 framed 回退（参照 Cline `client.ts` L158-184）。增加 stderr 持续 buffer（16KB）与进程 exit 主动回调。
2. **Q4 SSE/streamableHttp**：引入 `mcp` Python SDK（官方包）或 `httpx` + `sseclient`，替换 urllib，支持 SSE 长连接与流式 HTTP。区分 `sse` / `streamableHttp` 配置项。
3. **Q2 并发 JSON-RPC**：改用 pending Map + `asyncio.Future`，按 id 路由响应，支持并发 in-flight 请求。消除递归读取。
4. **Q6 运行时 toggle**：实现 `set_server_enabled(name, enabled)` API + `POST /mcp/servers/{name}/toggle` 端点，避免全量 reload 中断。
5. **Q8 auto_approve**：对接 `agent/approval.py`，`auto_approve: false` 的 MCP 工具调用前请求用户批准。
6. **Q14 TTL**：加 tools cache TTL（建议 60s，量化场景可较 Cline 5s 长）。

### 长期（按需，架构演进）

1. **Q11 混合工具注册**：可选实现"工具数少（< 5）展开为独立 LLM function，工具数多用 use_mcp_tool"的混合模式。加 `expand_tools: true` 配置项。若启用需同步启用 Q9 name-transform。
2. **Q6 文件锁**：若引入多进程（如多 worker），参照 Cline 实现 directory lock + atomic write（Python 可用 `filelock` 库）。
3. **Q5 OAuth**：若接入远程托管 MCP 服务，引入 `mcp` Python SDK 的 OAuth 支持或移植 Cline oauth.ts。
4. **Q10 插件注册**：若引入插件系统，移植 plugin-server-registration.ts。

---

## 6. 验证记录

- 已逐文件 Read 对比 Cline 源码（client.ts / config-loader.ts / manager.ts / name-transform.ts / policies.ts / plugin-server-registration.ts / tools.ts / oauth.ts / types.ts / index.ts）与本系统实现（agent/mcp/__init__.py / client.py / registry.py / name_transform.py / agent/tools/mcp.py / agent_config/mcp_servers.yaml / agent/server.py L1385-1505 / agent/context.py L207-368）。
- 已交叉验证 `ToolPolicy` 类型定义（`shared/llms/tools.ts` L7-18：`enabled` + `autoApprove`）与 `toolPolicies` 字段（`shared/agents/types.ts` L797）。
- 已确认 Cline `runtime-builder.ts` L186-243 `loadConfiguredMcpTools` 在 session 启动时主动连接所有 enabled MCP 服务器枚举工具（Q12 证据）。
- 已确认 Cline `config-loader.ts` 中 `transport.env` 为 `stringRecordSchema`（zod `Record<string, string>`），无 `${VAR}` 插值（Q7 证据）；`${VAR}` 风格的 env 引用在 Cline 中仅以结构化 `{fromEnv, value, required}` 形式存在于 `plugin-server-registration.ts`。
- 已确认本系统 `name_transform.py` 与 Cline `name-transform.ts` 常量与算法逐字等价（Q9 证据），且当前未被 registry 调用（模块 docstring L14-16 说明）。
- 已确认本系统 `_build_mcp_servers_section`（context.py L311-368）与 `build_servers_summary`（registry.py L378-421）为 Q11 单一 use_mcp_tool 架构下的必要补充（Q16 证据）。
- 报告中所有文件路径均为绝对路径或相对项目根的路径，行号基于实际 Read 结果。
