# Phase R: LLM Provider 适配 对比报告

> 对标源码：
> - `sdk/packages/core/src/services/llms/handler-factory.ts`
> - `sdk/packages/core/src/services/llms/provider-defaults.ts`
> - `sdk/packages/core/src/services/llms/provider-settings.ts`
> - `sdk/packages/core/src/services/llms/apihandler-agent-model-adapter.ts`
> - `sdk/packages/shared/src/llms/gateway.ts`
> - `sdk/packages/shared/src/agent.ts`（AgentModel 协议）
> - `sdk/packages/llms/src/providers/stream.ts` + `vendors/openai-compatible.ts`
> - `sdk/packages/core/src/extensions/tools/model-tool-routing.ts`
>
> 当前实现：
> - `agent/providers/__init__.py`
> - `agent/providers/base.py`
> - `agent/providers/factory.py`
> - `agent/providers/openai.py`
> - `agent/providers/qwen.py`
> - `agent/tools/routing.py`
> - `agent/types.py`（AgentModel 协议定义）
>
> 对比维度：R1-R15

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 4 项 |
| 弱对齐 | 7 项 |
| 缺失 | 3 项 |
| 额外增强 | 1 项 |
| **对齐度** | **约 57%** |

> 计算口径：完全一致 = 1.0，弱对齐 = 0.5，缺失 = 0，额外增强 = 1.0。
> 对齐度 = (4×1.0 + 7×0.5 + 3×0 + 1×1.0) / 15 ≈ 57%。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| R1 | `AgentModel` 协议 | `shared/agent.ts` L259-263 | `agent/types.py` L252-263 | 完全一致 |
| R2 | `handler-factory` 工厂 | `handler-factory.ts` L182-257 | `agent/providers/factory.py` L120-193 | 弱对齐 |
| R3 | 内置 provider 清单 | `provider-defaults.ts` L52-66（100+ 项） | `factory.py` L57-107（7 项） | 弱对齐 |
| R4 | `provider-defaults` 字段 | `provider-defaults.ts` L15-25 / L92-97 | `factory.py` L38-53 | 弱对齐 |
| R5 | `capabilities` 字段 | `provider-defaults.ts` L99-114；`provider-settings.ts` L163-176；`gateway.ts` L26-33 | 无（仅 `supports_reasoning: bool`） | 缺失 |
| R6 | OpenAI 兼容适配 | `vendors/openai-compatible.ts` L107-152 | `agent/providers/openai.py` L45-296 | 弱对齐 |
| R7 | 流式 tool_calls 组装 | `@ai-sdk/openai-compatible` 内部按 index 组装 | `qwen.py` L296-323 / `openai.py` L267-289 | 完全一致 |
| R8 | `reasoning_content` 处理 | `stream.ts` L39-51；`apihandler-agent-model-adapter.ts` L36-42；`routing/glm-thinking.ts` 等 | `qwen.py` L288-294 / `openai.py` L257-264 | 弱对齐 |
| R9 | `tool_call_id` 稳定性 | `@ai-sdk/openai-compatible` 内部保证 | `qwen.py` L149 / L305-315；`openai.py` L144 / L274-281 | 完全一致 |
| R10 | `provider-settings` 持久化 | `provider-settings.ts` L142-178 + `provider-settings-manager.ts` | 无 | 缺失 |
| R11 | `agent-model-adapter` | `apihandler-agent-model-adapter.ts` L115-171 | 无 | 缺失 |
| R12 | model-tool-routing 集成 | `model-tool-routing.ts` L60-134 | `agent/tools/routing.py` L59-139 | 完全一致 |
| R13 | `create_model_from_env` | 无（依赖 host 加载 AgentConfig） | `factory.py` L196-235 | 额外增强 |
| R14 | 错误处理 | `apihandler-agent-model-adapter.ts` L160-168；`errors.ts`；AI SDK 重试 | `qwen.py` L152-197 / `openai.py` L147-190 | 弱对齐 |
| R15 | usage 解析 | `stream.ts` L56-72；`apihandler-agent-model-adapter.ts` L60-73 | `qwen.py` L258-270 / `openai.py` L230-242 | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #R2：handler-factory 工厂结构差异

**严重度**：P1（影响扩展性与 host handler 接入）

**Cline 实现**：
- `createAgentModelFromConfig(config, logger, telemetry)`（handler-factory.ts L182-257）接收复合 `AgentConfig` 对象，内嵌 `providerConfig`。
- 先调用 `resolveKnownModelsFromConfig` 合并 catalog/generated/user-knownModels 三层模型清单（L90-129）。
- 通过 `hasRegisteredHandler(normalizeProviderId(...))` 检查 host 是否注册了自定义 handler（如 VS Code `vscode.lm`），命中则走 `createAgentModelFromApiHandler` 适配（L213-221）。
- 否则调用 `createGateway({ providerConfigs:[...], logger, telemetry, fetch })` 再 `.createAgentModel({providerId, modelId}, {maxTokens, temperature})`（L223-257）。
- 工厂内置 `buildGatewayProviderOptions`，按 provider_id 注入 bedrock / vertex / sapaicore / azure 等专有选项（L35-82）。

**我的实现**：
- `create_model(provider_id, model_id, api_key, base_url, **options)`（factory.py L120-193）使用扁平参数，不接收 `AgentConfig` 复合对象。
- 无 `hasRegisteredHandler` 检查，无 host handler 注册机制。
- 直接按 `provider_id` 分支：`qwen` 走 `QwenModel`，其他走 `OpenAIModel`（L171-193）。
- 不合并 catalog / generated / user-knownModels 三层模型清单。

**影响**：
- 无法接入 host 注册的 LM API（如 IDE 内置模型），仅支持 HTTP API provider。
- 无 provider 专有选项注入路径（bedrock/vertex/azure 等），扩展受限。
- 模型清单无动态合并能力，新增模型需改代码。

**修复建议**：
- 短期：维持扁平 API，但增加一个 `create_model_from_config(config: AgentConfig)` 入口以对齐 Cline 调用约定。
- 中期：引入 handler 注册表（`register_handler(provider_id, factory)`），支持 host 注入自定义模型适配器。
- 长期：将 bedrock/vertex/azure 选项纳入 `**options` 透传。

**优先级**：P1

---

### 差距 #R3：内置 provider 清单规模差异

**严重度**：P2（量化场景以 OpenAI 兼容为主，规模差距可接受）

**Cline 实现**：
- `BUILTIN_PROVIDER_MANIFESTS` 由 `Llms.MODEL_COLLECTIONS_BY_PROVIDER_ID` 派生（provider-defaults.ts L52-66），含 100+ 项。
- `provider-ids.generated.ts` 列出 models.dev 自动生成的 provider ID（302ai / abacus / alibaba / anthropic / bedrock / deepseek / gemini / groq / mistral / ollama / openai / vertex / 等等）。
- 每个 manifest 含 `id / baseUrl / modelsSourceUrl / modelId / knownModels / capabilities / env / client / protocol` 完整字段。
- 支持 OpenAI / Anthropic / Gemini / Bedrock / Vertex / Ollama / LM Studio / OpenRouter / Cline-Pass / OCA 等多种协议。

**我的实现**：
- `BUILTIN_PROVIDER_DEFAULTS`（factory.py L57-107）仅 7 项：`qwen / openai / openai-native / deepseek / moonshot / zhipu / openai-compatible`。
- 全部为 OpenAI 兼容协议，无 Anthropic 原生 / Gemini 原生 / Bedrock / Vertex 等。
- 每项仅含 `provider_id / base_url / default_model_id / supports_reasoning / env_key` 5 个字段。

**影响**：
- 无法直接接入 Anthropic Claude（需走 OpenAI 兼容代理）、Gemini、Bedrock 等原生协议。
- 量化场景以国内 OpenAI 兼容 provider 为主，7 项已覆盖核心需求。
- 缺少 `modelsSourceUrl` 导致无法动态拉取 provider 支持的模型清单。

**修复建议**：
- 短期：维持现状，量化场景足够。
- 中期：补充 `anthropic`（原生协议）与 `gemini`（原生协议）两个 provider。
- 长期：若需支持 model catalog 动态拉取，引入 `modelsSourceUrl` 字段。

**优先级**：P2

---

### 差距 #R4：provider-defaults 字段缺失

**严重度**：P2（影响 provider 元数据完整性）

**Cline 实现**：
- `BuiltInProviderManifest`（provider-defaults.ts L15-25）字段：`id / baseUrl / modelsSourceUrl / modelId / knownModels / capabilities / env / client / protocol`。
- `ProviderDefaults`（运行时，L92-97）字段：`baseUrl / modelId / knownModels / capabilities`。
- `client` 枚举：`anthropic / ai-sdk / ai-sdk-community / openai / openai-compatible / openai-r1 / gemini / bedrock / custom / fetch / vertex`（provider-settings.ts L42-54）。
- `protocol` 枚举：`anthropic / gemini / openai-chat / openai-responses / openai-r1 / ai-sdk`（L33-40）。

**我的实现**：
- `ProviderDefaults`（factory.py L38-53）字段：`provider_id / base_url / default_model_id / supports_reasoning / env_key`。
- 无 `knownModels`（无内置模型清单）。
- 无 `capabilities`（仅一个 `supports_reasoning` 布尔）。
- 无 `client` / `protocol`（默认全部走 OpenAI 兼容）。
- 无 `modelsSourceUrl`（无动态模型清单）。
- `env_key` 是单字符串，Cline 的 `env` 是 `("browser"|"node")[]` 上下文列表（语义不等价）。

**影响**：
- 无法表达 provider 协议差异（Anthropic 原生 vs OpenAI 兼容）。
- 无法表达 provider 能力差异（prompt-cache / vision / computer-use 等）。
- 无法在 UI 中展示 provider 支持的模型列表。

**修复建议**：
- 短期：添加 `protocol: str = "openai-chat"` 与 `client: str = "openai-compatible"` 字段，默认值覆盖现有行为。
- 中期：添加 `capabilities: list[str]` 字段替代 `supports_reasoning`，并把 `supports_reasoning` 改为 `"reasoning" in capabilities` 的派生属性。
- 长期：引入 `known_models: dict[str, ModelInfo]` 字段（参考 Cline `ModelInfo`）。

**优先级**：P2

---

### 差距 #R5：capabilities 字段完全缺失

**严重度**：P1（影响模型能力发现与路由决策）

**Cline 实现**：
三层 capabilities 体系：
1. `ProviderCapability`（provider-settings.ts L163-176）：`reasoning / prompt-cache / streaming / tools / vision / computer-use / oauth / popular`。
2. `GatewayModelCapability`（gateway.ts L26-33）：`text / tools / reasoning / prompt-cache / images / audio / structured-output`。
3. `toGatewayCapabilities`（handler-factory.ts L131-159）：将 `ModelInfo.capabilities` 映射为 `GatewayModelDefinition.capabilities`，自动补 `text`，把 `structured_output` 转 `structured-output`。
4. `toRuntimeCapabilities`（provider-defaults.ts L99-114）：将 catalog 的 capability 列表收敛为运行时 `ProviderCapability[]`。

capabilities 被用于：
- `GatewayStreamRequest` 路由匹配（`requiredCapability`，gateway.ts L43-54）。
- 模型清单 UI 展示。
- prompt-cache / reasoning 路由决策（`GatewayProviderRouting`，gateway.ts L55-64）。

**我的实现**：
- 完全无 capabilities 字段。
- 仅有 `ProviderDefaults.supports_reasoning: bool`（factory.py L52），表示是否解析 `reasoning_content` 字段。
- 无 prompt-cache / tools / images / vision / structured-output 等能力表达。

**影响**：
- 无法基于能力路由（如"只调用支持 tools 的模型"）。
- 无法表达 prompt-cache 能力（影响 Anthropic / Qwen 缓存路由）。
- 无法表达 vision 能力（影响多模态消息构建）。
- `supports_reasoning` 仅控制是否解析 `reasoning_content` 字段，不等价于 `capabilities.contains("reasoning")`（语义不等价）。

**修复建议**：
- 短期：在 `ProviderDefaults` 增加 `capabilities: list[str] = []` 字段，将 `supports_reasoning` 改为 `capabilities` 派生属性（保持向后兼容）。
- 中期：定义 `ModelCapability` 枚举常量，对齐 Cline `GatewayModelCapability`。
- 长期：将 capabilities 透传到 `AgentModelRequest`，供 runtime 决策。

**优先级**：P1

---

### 差距 #R6：OpenAI 兼容适配实现差异

**严重度**：P2（功能等价，但 SDK 与中间件差异明显）

**Cline 实现**：
- `createOpenAICompatibleProviderModule`（openai-compatible.ts L107-152）使用 `@ai-sdk/openai-compatible` 库的 `createOpenAICompatible`。
- 自动注入 `includeUsage: true`（L130）。
- 通过 `wrapLanguageModel({ model, middleware: splitToolImagesMiddleware })` 包装，将含图片的 `role:"tool"` 消息拆分为 placeholder text + 合成 user 消息（L133-150）。
- 支持 Azure API Version 自动注入（`createAzureApiVersionFetch`，L17-74）。
- 支持自定义 `onResponseError` 钩子（L76-105）。
- baseURL / headers / fetch 全可配置。

**我的实现**：
- `OpenAIModel` 类（openai.py L45-296）使用 `openai` Python SDK 的 `AsyncOpenAI` 客户端。
- 手动构建 `kwargs`，包含 `stream_options: {"include_usage": True}`（L205）。
- 手动解析 SSE chunk（`_parse_chunk`，L221-296）。
- 不支持 Azure API Version 自动注入。
- 不支持 `splitToolImagesMiddleware`（多模态 tool 消息会丢失图片字节）。
- 不支持 `onResponseError` 钩子。
- 暴露 `provider_id` 类属性供 model-tool-routing 使用（Cline 通过 manifest.id）。

**影响**：
- 多模态 tool 消息（含图片的 tool result）会被 `JSON.stringify` 丢失图片字节，影响视觉工具场景。
- Azure 部署需用户手动拼 `base_url`，不如 Cline 自动注入 `api-version`。
- 无法注入响应错误钩子（如 401 自动刷新 token）。

**修复建议**：
- 短期：维持现状，量化场景以文本为主，多模态影响小。
- 中期：实现 `splitToolImagesMiddleware` 等价逻辑（在 `agent_messages_to_openai` 中拆分图片 tool 消息）。
- 长期：若需 Azure 支持，增加 `azure_api_version` 选项与 URL 改写逻辑。

**优先级**：P2

---

### 差距 #R8：reasoning_content 处理深度不足

**严重度**：P2（影响 Anthropic / Gemini 推理模型集成）

**Cline 实现**：
- `ApiStreamReasoningChunk`（stream.ts L39-51）字段：`reasoning / details / signature / redacted_data / id`。
- 适配为 `AgentModelEvent` 时携带 `metadata.thoughtSignature` 与 `metadata.details`（apihandler-agent-model-adapter.ts L36-42）。
- 通过 `GatewayReasoningFormat`（gateway.ts L39-42）支持三种推理编码：
  - `anthropic-thinking`：Anthropic 思考块（含 signature 用于 prompt cache）。
  - `glm-thinking`：智谱 GLM 思考块。
  - `minimax-thinking`：MiniMax 思考块。
- `routing/anthropic-compatible.ts` / `glm-thinking.ts` / `minimax-thinking.ts` 实现各格式编解码。
- 支持 `redacted_data`（Anthropic 安全推理）。

**我的实现**：
- `qwen.py` L288-294 / `openai.py` L257-264：仅读取 `delta.reasoning_content` 字符串字段，发射 `reasoning-delta` 事件含 `text`。
- 不解析 `signature`（无 thought signature 透传）。
- 不解析 `redacted_data`（无安全推理支持）。
- 不区分 `anthropic-thinking` / `glm-thinking` / `minimax-thinking` 编码格式。
- `AgentModelEvent.redacted` 字段定义了但未赋值（types.py L235）。

**影响**：
- Anthropic Claude 思考块的 `signature` 丢失，破坏 prompt cache 命中（思考块需带 signature 才能缓存）。
- 智谱 GLM / MiniMax 的思考格式可能不被正确解析。
- 安全推理（redacted reasoning）场景下数据丢失。

**修复建议**：
- 短期：维持现状（量化场景以 Qwen/DeepSeek 为主，`reasoning_content` 字段已足够）。
- 中期：在 `AgentModelEvent` 中填充 `metadata={"thought_signature": ...}` 字段，透传 thought signature。
- 长期：若接入 Anthropic Claude，实现 `anthropic-thinking` 编解码器。

**优先级**：P2

---

### 差距 #R10：provider-settings 持久化完全缺失

**严重度**：P1（影响用户配置保存与多 provider 切换）

**Cline 实现**：
- `ProviderSettingsSchema`（provider-settings.ts L142-178）使用 zod 定义完整 schema，含：
  - 基础：`provider / apiKey / model / protocol / client / baseUrl / headers / timeout / maxTokens / contextWindow`。
  - 认证：`auth: AuthSettingsSchema`（apiKey / accessToken / refreshToken / expiresAt / accountId / organizationId 等）。
  - 推理：`reasoning: ReasoningSettingsSchema`（enabled / effort / budgetTokens）。
  - 云厂商：`aws / gcp / azure / sap / oca` 子 schema。
  - 模型目录：`modelCatalog: ModelCatalogSettingsSchema`（loadLatestOnInit / loadPrivateOnAuth / url / cacheTtlMs / failOnError）。
  - 能力：`capabilities: ["reasoning" | "prompt-cache" | "streaming" | "tools" | "vision" | "computer-use" | "oauth" | "popular"]`。
- `parseSettings` / `safeParseSettings` / `toProviderConfig` / `createProviderConfig` / `safeCreateProviderConfig` 提供完整解析与转换链。
- `provider-settings-manager.ts` 提供 SQLite 持久化（参考 Phase S）。
- `getPersistedProviderApiKey` 从 auth registry 读取持久化 API Key（L224）。
- `provider-settings-legacy-migration.ts` 提供旧格式迁移。

**我的实现**：
- 无任何持久化层。
- Provider 配置通过 `create_model()` 函数参数即时构造，或通过 `create_model_from_env()` 从环境变量读取。
- 无 zod 等校验，无 schema 定义。
- 无 auth registry，无 token 刷新机制。
- 无云厂商子配置。

**影响**：
- 用户无法在 UI 中保存 provider 偏好（每次需重新配置）。
- 无法持久化 API Key（依赖环境变量）。
- 无 OAuth token 刷新（access token 过期需手动处理）。
- 无旧配置迁移路径。
- 多 provider 切换需重启或重新调用 `create_model`。

**修复建议**：
- 短期：维持环境变量方案（适合 headless 量化场景）。
- 中期：实现 `ProviderSettings` dataclass + JSON 持久化（参考 `agent/session.py` 的 JSON 存储模式）。
- 长期：若需 UI 配置，引入 zod 等价校验（pydantic）+ SQLite 持久化。

**优先级**：P1

---

### 差距 #R11：agent-model-adapter 缺失

**严重度**：P3（无 legacy handler 场景下非必要）

**Cline 实现**：
- `createAgentModelFromApiHandler(source: ApiHandlerSource)`（apihandler-agent-model-adapter.ts L115-171）将旧版 `ApiHandler`（`createMessage -> ApiStreamChunk`）适配为 `AgentModel`（`stream -> AgentModelEvent`）。
- `ApiHandlerSource` 支持函数形式以延迟构造（L108-110），适配 `registerAsyncHandler` 注册的 provider。
- 内部 `toAgentModelEvents(chunk)` 将 5 种 `ApiStreamChunk`（text / reasoning / tool_calls / usage / done）映射为对应 `AgentModelEvent`（L27-88）。
- `doneFinishReason` 将 `incompleteReason` 映射为 `max-tokens` / `error` / `stop`（L90-101）。
- 在 `handler-factory.ts` L213-221 由 `hasRegisteredHandler` 触发。
- 用于 VS Code `vscode.lm` API 等 host-only 依赖的 provider。

**我的实现**：
- 无等价适配器。所有 provider 直接实现 `AgentModel` 协议（`stream` 方法）。
- 无 legacy `ApiHandler` 概念，无需适配层。

**影响**：
- 无法接入 host 注册的 LM API（如 IDE 内置 `vscode.lm`）。
- 量化场景为 headless 服务，无 IDE 集成需求，影响有限。

**修复建议**：
- 短期：暂不实现（无 IDE 集成需求）。
- 长期：若需 IDE 集成，引入 `ApiHandler` 协议与适配层。

**优先级**：P3

---

### 差距 #R14：错误处理策略差异

**严重度**：P2（影响限流恢复与错误分类）

**Cline 实现**：
- `apihandler-agent-model-adapter.ts` L160-168：try/catch 包裹整个流，捕获异常后发射 `finish` 事件，`reason` 为 `"aborted"`（若 `signal.aborted`）或 `"error"`，`error` 为 `Error.message`。
- AI SDK 内置 `max_retries`（默认 2），自动重试 429 / 5xx。
- `errors.ts` 定义类型化错误：`ClineNotSubscribedError` / `ClinePassLimitError` / `ClineOrgIndividualInferenceSubscriptionError` 等，可被 UI 精确展示。
- `fetchWithTimeout`（provider-defaults.ts L267-282）使用 `AbortController` 实现 HTTP 请求级超时。
- `handler.setAbortSignal?.(request.signal)` 将 abort signal 透传给 handler（apihandler-agent-model-adapter.ts L129）。

**我的实现**：
- `qwen.py` L152-197 / `openai.py` L147-190：try/except 包裹流，捕获 `asyncio.TimeoutError`（idle 超时）与通用 `Exception`，发射 `finish` 事件含 `reason=ERROR` 与 `error=str(e)`。
- `max_retries=0`（qwen.py L116 / openai.py L121）：显式禁用 SDK 重试，重试由 AgentRuntime 层统一处理。
- `asyncio.wait_for(stream_iter.__anext__(), timeout=self.idle_timeout)`（qwen.py L166-169）实现 chunk 间空闲超时（90s/120s）。
- 在 chunk 间隙主动检查 `abort_signal.is_set()`（qwen.py L158-164），命中则发射 `finish` 含 `reason=ERROR` 与 `error="aborted by user"`。
- 无类型化错误分类（所有错误统一为 `str(e)`）。

**语义不等价点**：
- 我将 abort 映射为 `reason=ERROR` + `error="aborted by user"`；Cline 映射为 `reason="aborted"`。Cline 的 `AgentModelFinishReason` 枚举含 `"aborted"`（agent.ts L226-230），我的枚举也有 `ABORTED = "aborted"`（types.py L214），但 provider 实现未使用，统一走 `ERROR`。

**影响**：
- 错误信息无分类，UI 无法区分"限流"/"未订阅"/"网络错误"。
- `reason=ERROR` 与 `reason=ABORTED` 混用，runtime 难以区分用户中止与真实错误。
- SDK 重试被禁用，限流恢复完全依赖 runtime 层（增加 runtime 复杂度）。

**修复建议**：
- 短期：将 abort 分支改为 `reason=AgentModelFinishReason.ABORTED`，对齐 Cline 语义。
- 中期：引入错误分类（`RateLimitError` / `AuthError` / `NetworkError`），在 `AgentModelEvent.error` 中携带类型字段。
- 长期：评估是否启用 SDK 内置重试（`max_retries=2`），或维持 runtime 层重试。

**优先级**：P2

---

### 差距 #R15：usage 解析字段不全

**严重度**：P2（影响成本统计与缓存命中率分析）

**Cline 实现**：
- `ApiStreamUsageChunk`（stream.ts L56-72）字段：`inputTokens / outputTokens / cacheWriteTokens / cacheReadTokens / thoughtsTokenCount / totalCost / id`。
- 适配为 `AgentModelEvent.usage: Partial<AgentUsage>`（apihandler-agent-model-adapter.ts L60-73），包含：
  - `inputTokens / outputTokens / cacheReadTokens / cacheWriteTokens`：token 计数。
  - `reasoningTokenCount`：来自 `thoughtsTokenCount`（推理 token）。
  - `totalCost`：来自 provider 报告或 `billing.ts` 计算。
- `AgentTokenUsage`（agent.ts L79-86）含 `reasoningTokenCount?: number`。
- `billing.ts` 提供成本计算（按模型定价）。

**我的实现**：
- `qwen.py` L258-270 / `openai.py` L230-242：仅解析三个字段：
  - `input_tokens` ← `usage.prompt_tokens`
  - `output_tokens` ← `usage.completion_tokens`
  - `cache_read_tokens` ← `usage.prompt_tokens_details.cached_tokens`
- `AgentUsage`（types.py L271-278）定义了 `cache_write_tokens` / `reasoning_token_count` / `total_cost` 字段，但 provider 从未填充。
- 无 `cache_write_tokens` 解析（Anthropic prompt cache 写入 token）。
- 无 `reasoning_token_count` 解析（Qwen 思考 token）。
- 无 `total_cost` 计算（无定价表）。

**影响**：
- 缓存写入 token 丢失，无法完整统计缓存效率。
- 推理 token 丢失，无法准确统计推理模型成本。
- 总成本无法自动计算，需手动统计。
- `AgentUsage` 字段定义但未填充，存在"假完整"陷阱。

**修复建议**：
- 短期：在 `usage_dict` 中尝试读取 `cache_write_tokens`（如 `completion_tokens_details.reasoning_tokens`）与 `reasoning_token_count`（如 `prompt_tokens_details.reasoning_tokens`），缺失则为 0。
- 中期：引入模型定价表（参考 Cline `billing.ts`），按 `input/output/cache` token 计算成本。
- 长期：将 `AgentUsage` 字段与 provider 解析对齐，确保定义即填充。

**优先级**：P2

---

## 4. 一致性统计

| 一致性等级 | 数量 | 子项编号 |
|-----------|------|---------|
| 完全一致 | 4 项 | R1, R7, R9, R12 |
| 弱对齐 | 7 项 | R2, R3, R4, R6, R8, R14, R15 |
| 缺失 | 3 项 | R5, R10, R11 |
| 额外增强 | 1 项 | R13 |

**完全一致项详解**：
- **R1（AgentModel 协议）**：`stream(request) -> AsyncIterator[AgentModelEvent]` 协议形态等价；我的版本额外提供 `abort_signal` 参数（可选），向后兼容。
- **R7（流式 tool_calls 组装）**：两边均以 `index` 为主键组装 tool_call；Cline 通过 ai-sdk 内部处理，我手动维护 `tool_call_ids: dict[int|None, str]`，逻辑等价。
- **R9（tool_call_id 稳定性）**：两边均保证同一 index 的所有 delta 使用相同 `tool_call_id`；我额外提供 UUID 合成回退（`f"tool_{uuid.uuid4().hex[:8]}"`）。
- **R12（model-tool-routing 集成）**：默认规则完全一致（`openai-native-use-apply-patch` + `codex-and-gpt-use-apply-patch`）；匹配逻辑（大小写不敏感子串、mode 过滤、后规则覆盖前规则）等价；我额外提供 `apply_tool_routing` 工具列表过滤助手。

**额外增强项详解**：
- **R13（create_model_from_env）**：Cline 无等价入口，依赖 host 加载 `AgentConfig`；我提供 `create_model_from_env()` 从 `AGENT_PROVIDER_ID` / `AGENT_MODEL_NAME` / `AGENT_MODEL_API_KEY` / `AGENT_MODEL_BASE_URL` / `AGENT_MODEL_MAX_TOKENS` / `AGENT_MODEL_TEMPERATURE` 环境变量创建模型，适合 headless / 容器化部署场景。保留此增强。

**弱对齐项共性**：
- R2/R3/R4：工厂结构与 provider 清单规模差距源于设计目标不同（Cline 面向多 provider 通用 IDE，我面向量化场景）。
- R6/R8/R14/R15：均因采用不同 SDK（Cline: ai-sdk，我: openai Python SDK）与不同协议覆盖广度导致字段缺失或行为差异。

---

## 5. 修复建议

### 短期（P1，建议本阶段完成）

1. **R14 abort 语义对齐**：将 `qwen.py` L159-163 与 `openai.py` L154-158 中的 `reason=AgentModelFinishReason.ERROR` 改为 `reason=AgentModelFinishReason.ABORTED`，对齐 Cline `apihandler-agent-model-adapter.ts` L164 的 `request.signal?.aborted ? "aborted" : "error"` 语义。
2. **R5 capabilities 字段引入**：在 `ProviderDefaults` 增加 `capabilities: list[str] = field(default_factory=list)` 字段，将 `supports_reasoning` 改为 `capabilities` 的派生属性（`@property`），保持向后兼容。最小能力集：`["reasoning", "prompt-cache", "tools", "images"]`。
3. **R15 usage 字段补全**：在 `qwen.py` / `openai.py` 的 `_parse_chunk` usage 分支中，尝试读取 `completion_tokens_details.reasoning_tokens`（→ `reasoning_token_count`）与 `prompt_tokens_details.cached_tokens`（已有），缺失则填 0；`cache_write_tokens` 暂填 0（OpenAI 兼容 API 通常不返回）。

### 中期（P2，下个迭代）

1. **R2 工厂入口扩展**：增加 `create_model_from_config(config: AgentConfig)` 入口，对齐 Cline `createAgentModelFromConfig` 调用约定；保留 `create_model` 扁平 API。
2. **R4 provider-defaults 字段补全**：添加 `protocol: str = "openai-chat"` 与 `client: str = "openai-compatible"` 字段；引入 `known_models: dict[str, dict] = field(default_factory=dict)` 字段。
3. **R6 多模态 tool 消息拆分**：在 `agent_messages_to_openai` 中实现 `splitToolImagesMiddleware` 等价逻辑，将含图片的 `tool` 消息拆分为 placeholder text + 合成 user 消息。
4. **R8 thought signature 透传**：在 `AgentModelEvent` 的 `metadata` 字段中携带 `thought_signature`，供下游 prompt cache 使用。
5. **R10 持久化层**：实现 `ProviderSettings` dataclass + JSON 持久化（参考 `agent/session.py`），最小 schema：`provider / apiKey / model / baseUrl / maxTokens / temperature`。
6. **R3 补充 Anthropic / Gemini 原生 provider**：若需接入 Claude / Gemini 原生协议，新增 `AnthropicModel` / `GeminiModel` 适配器。
7. **R14 错误分类**：引入 `RateLimitError` / `AuthError` / `NetworkError` 类型化异常，在 `AgentModelEvent.error` 中携带类型字段。

### 长期（P3，按需推进）

1. **R11 host handler 适配层**：若需 IDE 集成（如 VS Code `vscode.lm`），引入 `ApiHandler` 协议与 `create_agent_model_from_api_handler` 适配器。
2. **R2 handler 注册表**：引入 `register_handler(provider_id, factory)` 注册机制，支持 host 注入自定义模型适配器。
3. **R15 成本计算**：引入模型定价表（参考 Cline `billing.ts`），按 `input/output/cache` token 自动计算 `total_cost`。
4. **R3 动态模型清单**：若需 model catalog 动态拉取，引入 `modelsSourceUrl` 字段与缓存机制（参考 Cline `getLiveModelsCatalog`）。

---

## 6. 验证记录

| 验证项 | 验证方法 | 结果 |
|-------|---------|------|
| R1 AgentModel 协议 | 对比 `agent/types.py` L252-263 与 `shared/agent.ts` L259-263 签名 | 形态等价，我的版本含可选 `abort_signal` 参数 |
| R7 tool_calls 组装 | 检查 `qwen.py` L296-323 按 `index` 维护 `tool_call_ids` map | 与 ai-sdk 内部按 index 组装逻辑等价 |
| R9 tool_call_id 稳定性 | 检查 `qwen.py` L305-315 首次出现 id 记录、后续复用 | 与 ai-sdk 行为一致，额外提供 UUID 回退 |
| R12 model-tool-routing | 对比 `routing.py` L59-74 默认规则与 `model-tool-routing.ts` L60-75 | 规则名 / mode / includes / enable / disable 完全一致 |
| R13 create_model_from_env | 检查 `factory.py` L196-235 环境变量读取 | Cline 无等价入口，确认为额外增强 |
| R5 capabilities 缺失 | 在 `factory.py` L38-53 搜索 `capabilities` 字段 | 确认仅有 `supports_reasoning: bool`，无 capabilities 列表 |
| R10 持久化缺失 | 在 `agent/providers/` 搜索持久化逻辑 | 确认无 schema / 无 save / 无 load |
| R15 usage 字段 | 对比 `qwen.py` L258-270 解析字段与 `stream.ts` L56-72 定义字段 | 确认缺失 `cache_write_tokens` / `reasoning_token_count` / `total_cost` |
| R14 abort 语义 | 对比 `qwen.py` L159-163 与 `apihandler-agent-model-adapter.ts` L164 | 确认 abort 走 `ERROR` 而非 `ABORTED`，语义不等价 |
| R2 host handler 检查 | 在 `factory.py` 搜索 `hasRegisteredHandler` 等价逻辑 | 确认无 host handler 注册机制 |

---

## 7. 附录：Cline 与我的实现 SDK 选择对比

| 维度 | Cline | 我的实现 |
|------|-------|---------|
| OpenAI 兼容 SDK | `@ai-sdk/openai-compatible`（TypeScript） | `openai` Python SDK `AsyncOpenAI` |
| 流式 chunk 解析 | ai-sdk 内部解析，发射 `ApiStreamChunk` | 手动解析 SSE chunk（`_parse_chunk`） |
| tool_calls 组装 | ai-sdk 内部按 index 组装 | 手动维护 `tool_call_ids` dict |
| 重试 | ai-sdk 默认 `max_retries=2` | `max_retries=0`，runtime 层重试 |
| 超时 | `AbortController` + `fetchWithTimeout` | `asyncio.wait_for` + `idle_timeout` |
| 中止信号 | `request.signal` 透传给 handler | `abort_signal.is_set()` 在 chunk 间隙检查 |
| 错误分类 | 类型化错误（`ClineNotSubscribedError` 等） | 统一 `str(e)` |
| 多模态 tool 消息 | `splitToolImagesMiddleware` 自动拆分 | 无（图片字节会丢失） |
| Azure 支持 | `createAzureApiVersionFetch` 自动注入 api-version | 无（需手动拼 base_url） |
| 模型 catalog | `models.dev` 动态拉取 + 生成 | 静态 `BUILTIN_PROVIDER_DEFAULTS` |

---

## 8. 结论

Phase R 整体对齐度约 **57%**，主要差距集中在：

1. **provider 元数据完整性**（R3/R4/R5）：Cline 有 100+ provider 完整 manifest，我仅有 7 项精简配置；capabilities 字段完全缺失。
2. **持久化层**（R10）：完全缺失，依赖环境变量。
3. **错误与 usage 字段精度**（R14/R15）：abort 语义不等价，usage 缺失 cache_write / reasoning / cost 字段。
4. **多模态与 host handler**（R6/R11）：splitToolImagesMiddleware 与 ApiHandler 适配层缺失。

核心 streaming 路径（R1/R7/R9/R12）对齐度高，tool_calls 组装与 model-tool-routing 逻辑等价，可保证基础 agent loop 行为一致。

短期修复优先级最高的是 **R14 abort 语义对齐** 与 **R5 capabilities 引入**，两者均影响 runtime 决策正确性。
