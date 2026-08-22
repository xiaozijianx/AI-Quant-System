# Phase 7.4 LLM Provider 适配对比

> 对比范围：Cline `sdk/packages/llms/` + `sdk/packages/core/src/services/llms/` + `sdk/packages/shared/src/llms/gateway.ts` 中的 Provider 适配体系，与 Charles `agent/providers/` + `agent/provider_settings.py` + `agent/tools/routing.py` 的 Provider 适配体系逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/services/llms/handler-factory.ts`（L1-258，createAgentModelFromConfig 工厂）
> - `third_party/cline/sdk/packages/core/src/services/llms/provider-defaults.ts`（L1-954，BuiltInProviderManifest + getProviderConfig）
> - `third_party/cline/sdk/packages/core/src/services/llms/provider-settings.ts`（L1-318，ProviderSettingsSchema + toProviderConfig）
> - `third_party/cline/sdk/packages/llms/src/providers/builtins.ts`（L1-1187，BUILTIN_SPEC_OVERRIDES 含 40+ provider）
> - `third_party/cline/sdk/packages/llms/src/providers/vendors/anthropic.ts` / `bedrock.ts` / `vertex.ts` / `openai.ts` / `openai-compatible.ts`（vendor 实现）
> - `third_party/cline/sdk/packages/llms/src/providers/handler.ts`（ApiHandler 接口）
> - `third_party/cline/sdk/packages/llms/src/providers/stream.ts`（ApiStreamChunk 类型）
> - `third_party/cline/sdk/packages/llms/src/providers/gateway.ts`（DefaultGateway + GatewayModelAdapter）
> - `third_party/cline/sdk/packages/llms/src/providers/errors.ts`（ClineNotSubscribedError 等）
> - `third_party/cline/sdk/packages/llms/src/providers/routing/anthropic-compatible.ts`（能力路由）
>
> Charles 源码：
> - `agent/providers/__init__.py`（L1-34，模块导出）
> - `agent/providers/base.py`（L1-239，AgentModel 协议工具 + apply_capability_downgrade）
> - `agent/providers/factory.py`（L1-313，BUILTIN_PROVIDER_DEFAULTS + create_model）
> - `agent/providers/openai.py`（L1-389，OpenAIModel 适配器）
> - `agent/providers/qwen.py`（L1-427，QwenModel 适配器）
> - `agent/provider_settings.py`（L1-244，ProviderSettingsStore 持久化）
> - `agent/types.py` L249-325（AgentModelRequest / AgentModelEvent / AgentModel 协议）
> - `agent/tools/routing.py`（L1-203，model-tool-routing）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 LLM Provider 适配层。**核心结论：Charles 的 Provider 适配层在"OpenAI 兼容协议 + 国内量化场景"维度与 Cline 的 OpenAI 兼容子集对齐度较高（apply_capability_downgrade / provider-settings 持久化 / tool_call_id 稳定性 / AgentModel 协议均完整实现），但在 Provider 覆盖广度、API 抽象层级、错误处理专用化程度上存在显著差距。**

### 核心结论

1. **Provider 覆盖广度差距大**：Cline 通过 `BUILTIN_SPEC_OVERRIDES`（builtins.ts L628-1087）+ `GENERATED_PROVIDER_SPECS` 注册了 40+ 个 provider（含 anthropic / bedrock / vertex / gemini / openai-native / openai-codex / claude-code / qwen / qwen-code / deepseek / xai / mistral / minimax / openrouter / ollama / lmstudio / litellm / oca / asksage / doubao / zai / zai-coding-plan / kilo / hicap / together / groq / cerebras / sambanova / vercel-ai-gateway / v0 / aihubmix / nousResearch / huawei-cloud-maas / sapaicore / opencode / dify / cline / cline-pass / openai-compatible 等）；Charles `BUILTIN_PROVIDER_DEFAULTS` 仅注册 7 个（qwen / openai / openai-native / deepseek / moonshot / zhipu / openai-compatible）。
2. **Anthropic / Bedrock / Vertex 完全缺失**：Cline 在 `vendors/anthropic.ts` / `vendors/bedrock.ts` / `vendors/vertex.ts` 中分别用 `@ai-sdk/anthropic` / `@ai-sdk/amazon-bedrock` / `@ai-sdk/google-vertex` 实现了原生协议适配；Charles 无任何原生协议适配，仅依赖 OpenAI 兼容协议。
3. **API 抽象层级差异**：Cline 三层抽象（`ApiHandler` 接口 → `DefaultGateway` + `GatewayRegistry` → `@ai-sdk/*` vendor）；Charles 两层抽象（`AgentModel` Protocol → `QwenModel` / `OpenAIModel` 直接使用 `openai` Python SDK）。Charles 无 gateway registry，无 host handler 注册机制。
4. **流式响应事件模型基本对齐**：Cline `ApiStreamChunk` 五种类型（text / reasoning / usage / tool_calls / done）；Charles `AgentModelEvent` 五种类型（text-delta / reasoning-delta / tool-call-delta / usage / finish）。命名上 Charles 更细粒度（`-delta` 后缀），事件序列一致。
5. **错误处理专用化差距大**：Cline 有专用 `errors.ts`（ClineNotSubscribedError / ClineOrgIndividualInferenceSubscriptionError / ClinePassLimitError / ClinePassLimitError），`extractErrorMessage` 多层级结构化提取，`onResponseError` 钩子；Charles 仅 `try/except` 兜底 + `TimeoutError` 单独处理，无 provider 专用错误类型。
6. **apply_capability_downgrade 已对齐**：Charles `base.py` L43-108 显式实现 `apply_capability_downgrade`（vision/reasoning/tools 降级，深拷贝 request），对标 Cline 的 `toGatewayCapabilities`（builtins.ts L427-478）+ `GatewayModelCapability` 过滤机制。两者实现位置不同（Charles 在请求层降级，Cline 在 gateway 层过滤），效果等价。
7. **provider-settings 持久化 Charles 更显式**：Charles `provider_settings.py` 有完整 `ProviderSettingsStore`（yaml 持久化 + tmp.replace 原子写入 + UPDATABLE_FIELDS 白名单 + mask_api_key 脱敏）；Cline `provider-settings.ts` 主要是 Zod schema 校验 + `toProviderConfig` 转换，文件持久化由 host 的 settings manager 负责（不在本文件）。
8. **tool_call_id 稳定性 Charles 显式处理**：Charles `qwen.py` L160-358 / `openai.py` L161-328 显式维护 `tool_call_ids: dict[int, str]` 按 index 复用 id，fallback 到 `uuid4`；Cline 由 `@ai-sdk/openai-compatible` 内部处理（Cline 源码不可见）。Charles 的 Qwen 特化处理是必要的——DashScope 的 tool_call_id 通常只在首个 delta 出现。
9. **nanobot 残留**：P7.4 范围内（`agent/providers/` 目录 + `agent/provider_settings.py` + `agent/tools/routing.py`）共 **7 处注释残留**（全部在 `qwen.py` docstring 中），**0 处实现逻辑残留**。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| Provider 列表覆盖 | 低 | Cline 40+ provider，Charles 7 个 |
| API 调用方式 | 中 | 均走 OpenAI 兼容协议，抽象层级不同 |
| 流式响应 | 高 | 事件类型基本对应，序列一致 |
| 错误处理 | 低 | Cline 有专用错误类型 + 钩子，Charles 仅兜底 |
| apply_capability_downgrade | 高 | Charles 显式实现，效果等价 |
| provider-settings 持久化 | 高 | Charles 有完整持久化逻辑，更显式 |
| tool_call_id 稳定性 | 高 | Charles 显式处理，Qwen 特化必要 |
| AgentModel 协议 | 高 | 两者均有协议定义 |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.4.1 | Qwen 适配 | `builtins.ts` L778-788（qwen）+ L791-800（qwen-code），走 `vendors/openai-compatible.ts` 通用适配器 | `agent/providers/qwen.py` L1-427，专用 `QwenModel` 类 | 中 | Charles 有专用 Qwen 适配器（含 tool_call_id 稳定性特化），Cline 走通用 OpenAI 兼容路径。Charles 量化特化更深入 |
| 7.4.2 | OpenAI 适配 | `vendors/openai.ts` L1-51，使用 `@ai-sdk/openai` 的 `provider.responses(modelId)`（Responses API） | `agent/providers/openai.py` L1-389，使用 `openai` Python SDK 的 `AsyncOpenAI.chat.completions.create`（Chat Completions API） | 中 | Cline 走 OpenAI Responses API（新协议），Charles 走 Chat Completions API（兼容协议）。两者协议层级不同，但 Stage 32.2 已对齐基本行为 |
| 7.4.3 | Anthropic 适配 | `vendors/anthropic.ts` L1-39，使用 `@ai-sdk/anthropic` | 无 | 缺失 | Charles 完全无 Anthropic 原生适配。Claude 模型只能通过 OpenAI 兼容代理（如 OpenRouter）访问，丢失 thinking / prompt cache 等原生能力 |
| 7.4.4 | Bedrock 适配 | `vendors/bedrock.ts` L1-100+，使用 `@ai-sdk/amazon-bedrock` + AWS SDK credential providers | 无 | 缺失 | Charles 无 Bedrock 适配。AWS 用户无法直接接入 |
| 7.4.5 | Vertex AI 适配 | `vendors/vertex.ts` L1-80，使用 `@ai-sdk/google-vertex` + `@ai-sdk/google-vertex/anthropic`（Claude on Vertex） | 无 | 缺失 | Charles 无 Vertex 适配。GCP 用户无法直接接入 |
| 7.4.6 | apply_capability_downgrade | `builtins.ts` L427-478 `toGatewayCapabilities` + `gateway.ts` L131-159 `toGatewayCapabilities`（gateway 层过滤） | `agent/providers/base.py` L43-108 `apply_capability_downgrade`（请求层降级） | 高 | Charles Stage 13.1 显式实现，对标 Cline 能力过滤。Charles 在请求层做 content 降级（ImagePart→TextPart / 丢弃 ReasoningPart / tools 置空），Cline 在 gateway 层做 capability 映射 |
| 7.4.7 | provider-settings 持久化 | `provider-settings.ts` L142-310 ProviderSettingsSchema (Zod) + toProviderConfig | `agent/provider_settings.py` L1-244 ProviderSettingsStore | 高 | Charles Stage 13.2 有完整 yaml 持久化 + 原子写入 + 字段白名单 + api_key 脱敏。Cline 侧重 schema 校验，文件持久化由 host settings manager 负责 |
| 7.4.8 | tool_call_id 不稳定处理 | `@ai-sdk/openai-compatible` 内部按 index 组装（Cline 源码不可见） | `qwen.py` L160-358 / `openai.py` L161-328 显式 `tool_call_ids: dict[int, str]` | 高 | Charles Qwen 特化必要——DashScope 的 tool_call_id 只在首个 delta 出现。Charles 显式处理可见可维护，Cline 依赖 AI SDK 黑盒 |
| 7.4.9 | AgentModel 协议 | `shared/agent.ts` AgentModel 接口（stream 方法） | `agent/types.py` L313-325 AgentModel Protocol（stream 方法） | 高 | 两者均定义 stream(request) → AsyncIterator[event] 协议。Charles 用 Python Protocol（structural typing），Cline 用 TypeScript interface |
| 7.4.10 | ApiHandler 接口 | `handler.ts` L25-69 ApiHandler 接口（getMessages / createMessage / getModel / abort） | 无（直接用 AgentModel 协议） | 缺失 | Cline 的 ApiHandler 是历史遗留接口（兼容 VS Code `vscode.lm` 等 host handler），Charles 无 host handler 概念，不需要 |
| 7.4.11 | Gateway 注册机制 | `gateway.ts` L183-292 DefaultGateway + GatewayRegistry，支持 `registerProvider` / `configureProvider` 动态注册 | 无（factory.py L194-271 `create_model` 工厂函数 if/else 分支） | 缺失 | Cline 支持运行时动态注册 provider + 模型，Charles 仅静态工厂分支。Charles 架构简单，无需动态注册 |
| 7.4.12 | 流式事件类型 | `stream.ts` L16-21 ApiStreamChunk 联合类型（text / reasoning / usage / tool_calls / done） | `agent/types.py` L281-310 AgentModelEvent（text-delta / reasoning-delta / tool-call-delta / usage / finish） | 高 | 事件类型一一对应，命名上 Charles 更细粒度（`-delta` 后缀）。Charles 的 `tool-call-delta` 携带 `metadata.provider_metadata`（Stage 10.1），Cline 的 `tool_calls` 携带 `id` + `signature` |
| 7.4.13 | usage 解析 | `stream.ts` L56-72 ApiStreamUsageChunk（inputTokens / outputTokens / cacheWriteTokens / cacheReadTokens / thoughtsTokenCount / totalCost） | `qwen.py` L258-296 / `openai.py` L230-274 usage dict（6 字段：input_tokens / output_tokens / cache_read_tokens / cache_write_tokens / reasoning_token_count / total_cost） | 高 | Charles Stage 7.8 (R15) 显式补全 6 字段，对标 Cline ApiStreamUsageChunk。Charles 解析 `prompt_tokens_details.cached_tokens` / `cache_creation_input_tokens` / `completion_tokens_details.reasoning_tokens` |
| 7.4.14 | 错误处理 | `errors.ts` L1-100+（ClineNotSubscribedError / ClinePassLimitError / ClineOrgIndividualInferenceSubscriptionError）+ `format.ts` extractErrorMessage + `onResponseError` 钩子 + AI SDK 重试 | `qwen.py` L163-209 / `openai.py` L147-208 try/except + TimeoutError + max_retries=0 | 低 | Cline 有 4 种专用错误类型 + 多层级 message 提取 + 响应错误钩子；Charles 仅 `try/except` 兜底，错误信息以 `str(e)` 透传，无 provider 专用错误分类 |
| 7.4.15 | 中止信号 | `gateway.ts` L62-117 signal（AbortSignal） | `qwen.py` L131-176 / `openai.py` L145-177 abort_signal（Any，is_set() 检查） | 高 | 两者均支持流式中止。Cline 用标准 AbortSignal，Charles 用 `asyncio.Event` 风格的 abort_signal。中止时均 yield finish with ABORTED reason |
| 7.4.16 | 内置 provider 默认配置 | `provider-defaults.ts` L52-66 BUILTIN_PROVIDER_MANIFESTS（从 MODEL_COLLECTIONS_BY_PROVIDER_ID 派生） | `factory.py` L104-181 BUILTIN_PROVIDER_DEFAULTS（7 个 ProviderDefaults） | 中 | Cline 从 generated catalog 派生 40+ provider 清单，Charles 手写 7 个。Charles 的 `ProviderDefaults` 字段（provider_id / base_url / default_model_id / supports_reasoning / env_key / capabilities）与 Cline 的 `BuiltInProviderManifest` 字段对齐 |
| 7.4.17 | reasoning_content 处理 | `stream.ts` L39-51 ApiStreamReasoningChunk + `routing/glm-thinking.ts` / `routing/minimax-thinking.ts` 等 routing 模块 | `qwen.py` L315-320 无条件解析 `delta.reasoning_content`；`openai.py` L290-296 按 `supports_reasoning` 开关解析 | 中 | Cline 有 provider 专用 reasoning routing（GLM / MiniMax / Anthropic thinking），Charles 仅按 `supports_reasoning` bool 开关。Charles 的 QwenModel 无条件解析，OpenAIModel 可配置 |
| 7.4.18 | provider metadata 提取 | `stream.ts` L31 ApiStreamTextChunk.id + L82 ApiStreamToolCallsChunk.id + `apihandler-agent-model-adapter.ts` metadata 传递 | `qwen.py` L325-340 / `openai.py` L301-314 chunk_metadata（request_id / model_version / finish_reason）包装为 provider_metadata | 高 | Charles Stage 10.1 (C8/C18) 显式提取 chunk 顶层 `id` / `model` / `finish_reason` 包装为 `provider_metadata`，对标 Cline 的 chunk.id 传递 |
| 7.4.19 | create_model_from_env | 无（依赖 host 加载 AgentConfig） | `factory.py` L274-313 create_model_from_env | 额外增强 | Charles 有从环境变量创建模型的便捷入口（AGENT_PROVIDER_ID / AGENT_MODEL_NAME / AGENT_MODEL_API_KEY / AGENT_MODEL_BASE_URL / AGENT_MODEL_MAX_TOKENS / AGENT_MODEL_TEMPERATURE），Cline 无此便捷入口 |
| 7.4.20 | model-tool-routing 集成 | `core/src/extensions/tools/model-tool-routing.ts` L60-134 | `agent/tools/routing.py` L1-203 | 高 | Charles Stage 7.x 实现 DEFAULT_MODEL_TOOL_ROUTING_RULES（openai-native 用 apply_patch 替代 editor；codex/gpt 系列同）。规则匹配条件（mode + provider_id_includes + model_id_includes）与 Cline 一致 |

---

## 三、重点差距详解

### 3.1 Provider 覆盖广度差距

**严重度**：P2（Charles 量化场景下影响有限，但扩展性受限）

**Cline 实现**（`builtins.ts` L628-1087 + `GENERATED_PROVIDER_SPECS`）：

Cline 通过两层机制注册 provider：
1. `GENERATED_PROVIDER_SPECS`：从 `models.dev` catalog 自动生成的 provider 清单
2. `BUILTIN_SPEC_OVERRIDES`：手写的 Cline 专属覆盖（L628-1087）

实测 `builtins.ts` 中 `id: "..."` 模式匹配到 40 个 provider（含 sonnet / cline / openai-compatible / deepseek / xai / together / groq / cerebras / sambanova / litellm / vercel-ai-gateway / v0 / aihubmix / hicap / nousResearch / huawei-cloud-maas / qwen / qwen-code / doubao / zai / zai-coding-plan / kilo / openrouter / ollama / lmstudio / oca / asksage / openai-native / openai-codex / openai-codex-cli / anthropic / claude-code / gemini / vertex / bedrock / mistral / minimax / opencode / dify / sapaicore）。

每个 provider spec 含字段：`id` / `name` / `description` / `family` / `popular` / `capabilities` / `defaultModelId` / `apiKeyEnv` / `modelsProviderId` / `defaults.baseUrl` / `configFields` / `metadata`。

**Charles 实现**（`factory.py` L104-181）：

Charles `BUILTIN_PROVIDER_DEFAULTS` 字典手写 7 个 provider：

| provider_id | base_url | default_model_id | capabilities |
|------------|----------|------------------|--------------|
| qwen | dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus | reasoning, tools, streaming |
| openai | "" (SDK 默认) | gpt-4o | reasoning, tools, streaming, vision, structured-output, prompt-cache |
| openai-native | "" (SDK 默认) | gpt-4o | 同上 |
| deepseek | api.deepseek.com/v1 | deepseek-chat | reasoning, tools, streaming |
| moonshot | api.moonshot.cn/v1 | moonshot-v1-8k | tools, streaming |
| zhipu | open.bigmodel.cn/api/paas/v4 | glm-4-plus | tools, streaming |
| openai-compatible | "" (必须显式提供) | "" | reasoning, tools, streaming |

**差距分析**：
- Charles 覆盖了国内量化场景主流 provider（Qwen / DeepSeek / Moonshot / Zhipu），但缺少 Cline 的全球 provider（anthropic / bedrock / vertex / gemini / openrouter / ollama / litellm 等）
- Charles 的 7 个 provider 全部走 OpenAI 兼容协议，无原生协议适配
- Charles 的 provider 清单是静态手写，Cline 支持从 catalog 动态生成 + 手写覆盖
- Charles 无 `modelsSourceUrl`（动态模型列表拉取）、无 `knownModels`（模型清单）、无 `configFields`（UI 配置字段）

### 3.2 API 调用方式差异

**Cline 三层抽象**：

```
AgentModel (shared/agent.ts)
    ↓
GatewayModelAdapter (gateway.ts L54-118)
    ↓
DefaultGateway.stream() (gateway.ts L243-291)
    ↓
GatewayRegistry.resolveModel() + createProvider()
    ↓
@ai-sdk/* vendor (vendors/anthropic.ts / openai.ts / bedrock.ts / vertex.ts / openai-compatible.ts)
    ↓
provider.stream() → ApiStreamChunk
```

Cline 通过 `createAgentModelFromConfig`（handler-factory.ts L182-257）创建 AgentModel：
1. 先调用 `resolveKnownModelsFromConfig` 合并 catalog / generated / user-knownModels 三层模型清单（L90-129）
2. 检查 `hasRegisteredHandler` 是否有 host 注册的自定义 handler（L213-221），命中则走 `createAgentModelFromApiHandler`
3. 否则调用 `createGateway({ providerConfigs, logger, telemetry, fetch })` 再 `.createAgentModel({providerId, modelId}, {maxTokens, temperature})`（L223-257）
4. `buildGatewayProviderOptions`（L35-82）按 provider_id 注入 bedrock / vertex / sapaicore / azure 专有选项

**Charles 两层抽象**：

```
AgentModel Protocol (types.py L313-325)
    ↓
QwenModel / OpenAIModel (providers/qwen.py / openai.py)
    ↓
openai Python SDK AsyncOpenAI.chat.completions.create(stream=True)
    ↓
AgentModelEvent
```

Charles 通过 `create_model`（factory.py L194-271）创建 AgentModel：
1. 从 `BUILTIN_PROVIDER_DEFAULTS` 查 provider 默认配置（L216-221）
2. 解析参数（显式参数 > 环境变量 > provider 默认值）（L223-245）
3. 按 `provider_id` 分支：`qwen` 走 `QwenModel`，其他走 `OpenAIModel`（L247-271）
4. 无 host handler 检查、无 gateway 注册、无模型清单合并

**差距分析**：
- Cline 的 gateway 抽象支持运行时动态注册 provider 和模型，Charles 仅静态工厂分支
- Cline 支持 host handler（如 VS Code `vscode.lm`），Charles 不支持
- Cline 的 `buildGatewayProviderOptions` 为 bedrock / vertex / sapaicore / azure 注入专有选项（AWS credentials / GCP project / Azure apiVersion），Charles 无此能力
- Charles 简单直接，无 gateway 开销，适合单 agent 场景

### 3.3 流式响应事件模型对比

**Cline `ApiStreamChunk`**（`stream.ts` L16-21）：

```typescript
type ApiStreamChunk =
  | ApiStreamTextChunk        // { type: "text", text, id, signature? }
  | ApiStreamReasoningChunk   // { type: "reasoning", reasoning, details?, signature?, redacted_data?, id }
  | ApiStreamUsageChunk       // { type: "usage", inputTokens, outputTokens, cacheWriteTokens?, cacheReadTokens?, thoughtsTokenCount?, totalCost?, id }
  | ApiStreamToolCallsChunk   // { type: "tool_calls", tool_call: { call_id?, function: { id?, name?, arguments? } }, id, signature? }
  | ApiStreamDoneChunk;       // { type: "done", success, error?, incompleteReason?, id }
```

**Charles `AgentModelEvent`**（`types.py` L281-310）：

```python
@dataclass
class AgentModelEvent:
    type: str  # "text-delta" / "reasoning-delta" / "tool-call-delta" / "usage" / "finish"
    text: str | None = None              # text-delta / reasoning-delta
    redacted: bool | None = None         # reasoning-delta
    index: int | None = None             # tool-call-delta
    tool_call_id: str | None = None      # tool-call-delta
    tool_name: str | None = None         # tool-call-delta
    input_text: str | None = None        # tool-call-delta
    input_value: Any | None = None       # tool-call-delta
    usage: dict[str, int] | None = None  # usage
    reason: AgentModelFinishReason | None = None  # finish
    error: str | None = None             # finish
    metadata: Any | None = None          # 通用元数据
```

**事件类型对应关系**：

| Cline | Charles | 说明 |
|-------|---------|------|
| text | text-delta | Charles 命名更细粒度（`-delta` 后缀） |
| reasoning | reasoning-delta | Charles 命名更细粒度 |
| usage | usage | 完全一致 |
| tool_calls | tool-call-delta | Charles 命名更细粒度 |
| done | finish | 命名不同，语义一致 |

**Charles 的增强**：
- `tool-call-delta` 携带 `index`（按 index 组装工具调用）+ `metadata.provider_metadata`（Stage 10.1 C8/C18，含 request_id / model_version / finish_reason）
- `finish` 用 `AgentModelFinishReason` 枚举（STOP / TOOL_CALLS / MAX_TOKENS / ABORTED / ERROR），Cline 用 `success: bool` + `incompleteReason?: string`

**Cline 的增强**：
- `ApiStreamReasoningChunk` 含 `signature`（Anthropic thinking block 签名）+ `redacted_data`（推理脱敏数据）
- `ApiStreamTextChunk` 含 `signature`（Gemini thought signature）
- `ApiStreamToolCallsChunk` 含 `signature`（Gemini）

Charles 缺少 `signature` 字段——这是 Anthropic / Gemini 原生协议特有字段，在 OpenAI 兼容协议下不存在。

### 3.4 错误处理差距

**Cline 错误处理体系**（`errors.ts` + `format.ts` + `onResponseError` 钩子）：

1. **专用错误类型**（`errors.ts` L47-79）：
   - `ClineNotSubscribedError`：用户未订阅 ClinePass
   - `ClineOrgIndividualInferenceSubscriptionError`：组织账户不能用个人订阅
   - `ClinePassLimitError`：达到 ClinePass 限额
   - 每种错误含 `providerId` 字段，便于上层按 provider 分类处理

2. **结构化错误消息提取**（`format.ts` L1-100+ `extractErrorMessage`）：
   - 多层级提取：`error.message` / `error.error.message` / `error.detail` / `error.errors[]` / `error.responseBody`
   - 处理 generic wrapper messages（如 "no output generated"）
   - 处理 cause chain（`error.cause`）

3. **响应错误钩子**（`openai-compatible.ts` L77-105 `readResponseErrorHandler` + `createResponseErrorFetch`）：
   - provider manifest 可注册 `onResponseError` 回调（`builtins.ts` L599-603）
   - 在 fetch wrapper 中拦截 HTTP 响应，解析 body 抛出专用错误

4. **AI SDK 重试**：`@ai-sdk/*` 内置重试机制

**Charles 错误处理**（`qwen.py` L163-209 / `openai.py` L147-208）：

```python
try:
    stream = await self._client.chat.completions.create(**kwargs)
    # ... 流式接收 ...
except asyncio.TimeoutError:
    yield AgentModelEvent(
        type="finish",
        reason=AgentModelFinishReason.ERROR,
        error=f"Qwen API 流式响应超时（{self.idle_timeout}秒无数据）",
    )
except Exception as e:
    yield AgentModelEvent(
        type="finish",
        reason=AgentModelFinishReason.ERROR,
        error=str(e),
    )
```

**差距分析**：
- Charles 无专用错误类型，所有错误以 `str(e)` 透传到 finish 事件
- Charles 无结构化错误消息提取，provider 返回的 JSON 错误体不会被解析
- Charles 无响应错误钩子，无法在 HTTP 层拦截错误
- Charles `max_retries=0`（qwen.py L124 / openai.py L135），重试由 AgentRuntime 层处理
- Charles 的优势：错误处理简单透明，无 provider 专用逻辑耦合

### 3.5 apply_capability_downgrade 对比

**Charles 实现**（`base.py` L43-108）：

```python
def apply_capability_downgrade(request: AgentModelRequest) -> AgentModelRequest:
    caps = request.capabilities
    if not caps:
        return request
    # 判断需要降级的能力
    need_vision_downgrade = CAPABILITY_VISION not in caps
    need_reasoning_downgrade = CAPABILITY_REASONING not in caps
    need_tools_downgrade = CAPABILITY_TOOL_CALLS not in caps
    # 深拷贝 request，避免修改原 request
    new_request = AgentModelRequest(
        system_prompt=request.system_prompt,
        messages=copy.deepcopy(request.messages),
        tools=list(request.tools) if not need_tools_downgrade else [],
        ...
    )
    # tools 降级：在 system_prompt 追加提示
    if need_tools_downgrade and request.tools:
        new_request.system_prompt = (new_request.system_prompt or "") + tools_hint
    # messages 内容降级
    for msg in new_request.messages:
        for part in msg.content:
            if isinstance(part, ImagePart) and need_vision_downgrade:
                new_content.append(TextPart(text=f"[image: {alt}]"))
            if isinstance(part, ReasoningPart) and need_reasoning_downgrade:
                continue  # 丢弃
```

**Cline 实现**（`builtins.ts` L427-478 `toGatewayCapabilities` + `gateway.ts` L131-159）：

```typescript
function toGatewayCapabilities(capabilities): GatewayModelDefinition["capabilities"] {
    const mapped = new Set<...>();
    for (const capability of capabilities ?? []) {
        switch (capability) {
            case "tools": mapped.add("tools"); break;
            case "reasoning": mapped.add("reasoning"); break;
            case "prompt-cache": mapped.add("prompt-cache"); break;
            case "images": mapped.add("images"); break;
            case "structured_output": mapped.add("structured-output"); break;
            default: mapped.add("text");
        }
    }
    mapped.add("text");
    return [...mapped];
}
```

**对比**：
- Charles 在**请求层**做 content 降级（ImagePart → TextPart / 丢弃 ReasoningPart / tools 置空 + system_prompt 提示），是显式的内容转换
- Cline 在**gateway 层**做 capability 映射（model capabilities → gateway capabilities），不直接修改 request content
- 两者效果不同：Charles 的降级是"让不支持 vision 的模型也能处理图片（以文本描述）"，Cline 的映射是"标记模型能力供 routing 决策"
- Charles 的降级更贴近 Cline 的 `splitToolImagesMiddleware`（`openai-compatible.ts` L141-150），但 Cline 的 middleware 是在 wire format 转换前操作，Charles 在 request 构建时操作

### 3.6 provider-settings 持久化对比

**Charles 实现**（`provider_settings.py` L1-244）：

```python
class ProviderSettingsStore:
    def __init__(self, config_path=None):
        self._config_path = Path(config_path or "agent_config/providers.yaml")
        self._configs: dict[str, ProviderConfig] = {}
        self._load()

    def _save(self) -> None:
        # 原子写入: tmp.replace
        tmp_fd, tmp_path = tempfile.mkstemp(...)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(yaml_text)
        Path(tmp_path).replace(self._config_path)

    def update_provider(self, provider_id, updates) -> ProviderConfig:
        if "api_key" in updates:
            raise ValueError("api_key 不允许通过 API 修改")
        invalid_fields = set(updates.keys()) - UPDATABLE_FIELDS
        if invalid_fields:
            raise ValueError(f"非法字段: {invalid_fields}")
        # ... 应用更新 + 持久化 ...

def mask_api_key(api_key: str) -> str:
    if len(api_key) <= 4:
        return api_key[:2] + "***"
    return api_key[:4] + "***"
```

UPDATABLE_FIELDS = {"model_id", "base_url", "temperature", "max_tokens"}（api_key 不允许通过 API 修改）

**Cline 实现**（`provider-settings.ts` L1-318）：

```typescript
export const ProviderSettingsSchema = z.object({
    provider: ProviderIdSchema,
    apiKey: z.string().optional(),
    auth: AuthSettingsSchema.optional(),
    model: z.string().optional(),
    protocol: ProviderProtocolSchema.optional(),
    client: ProviderClientSchema.optional(),
    // ... 含 aws / gcp / azure / sap / oca 等专有设置 ...
    capabilities: z.array(z.enum([
        "reasoning", "prompt-cache", "streaming", "tools",
        "vision", "computer-use", "oauth", "popular"
    ])).optional(),
    modelCatalog: ModelCatalogSettingsSchema.optional(),
});

export function toProviderConfig(settings: ProviderSettings): ProviderConfig {
    // Zod schema 解析 + 字段映射 + 默认值填充
    // 含 routingProviderId 推断 / knownModels 合并 / api_key 从 auth registry 读取
}
```

**对比**：
- Charles 有完整文件持久化逻辑（yaml + 原子写入），Cline 的 `provider-settings.ts` 主要是 schema 校验 + 转换，文件持久化由 host 的 settings manager 负责（不在本文件）
- Charles 的 `UPDATABLE_FIELDS` 白名单显式禁止 `api_key` 通过 API 修改，Cline 通过 `getPersistedProviderApiKey`（auth/provider-auth-registry）单独管理 api_key
- Charles 的 `mask_api_key` 脱敏函数显式实现，Cline 无对应函数（在 UI 层处理）
- Cline 的 schema 更丰富（含 aws / gcp / azure / sap / oca 专有设置 + modelCatalog 动态模型列表配置），Charles 仅通用字段
- Charles 侧重"运行时可修改的配置持久化"，Cline 侧重"完整的 settings schema 校验"

### 3.7 tool_call_id 稳定性处理对比

**Charles 实现**（`qwen.py` L160-358，`openai.py` L161-328）：

```python
# qwen.py L160
tool_call_ids: dict[int | None, str] = {}

# qwen.py L342-358
for tc in tool_calls:
    tc_dict = _to_dict(tc)
    fn_dict = _to_dict(tc_dict.get("function", {}))
    index = tc_dict.get("index")
    raw_id = tc_dict.get("id") or ""

    # 保持同一 index 的 tool_call_id 稳定
    id_map = tool_call_ids if tool_call_ids is not None else {}
    if raw_id:
        id_map[index] = raw_id
    tool_call_id = id_map.get(index)
    if not tool_call_id:
        tool_call_id = raw_id or f"tool_{uuid.uuid4().hex[:8]}"
        id_map[index] = tool_call_id

    yield AgentModelEvent(
        type="tool-call-delta",
        index=index,
        tool_call_id=tool_call_id,
        ...
    )
```

**Cline 实现**：
- Cline 源码中无显式 tool_call_id 稳定性处理逻辑
- 由 `@ai-sdk/openai-compatible` 内部按 index 组装（AI SDK 黑盒）
- `stream.ts` L77-102 `ApiStreamToolCallsChunk` 仅定义 `tool_call.call_id` / `tool_call.function.id`，无 index 字段

**对比**：
- Charles 显式处理 tool_call_id 稳定性，逻辑可见可维护
- Charles 的 Qwen 特化处理是必要的——DashScope 的 tool_call_id 通常只在首个 delta 出现，后续 delta 的 id 为空字符串（qwen.py L156-159 注释说明）
- Charles fallback 到 `uuid4` 生成临时 id（qwen.py L357），确保即使所有 delta 都无 id 也能组装工具调用
- Cline 依赖 AI SDK 黑盒，不可见但经过 AI SDK 社区测试

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P7.4 范围内涉及以下文件：
- `agent/providers/__init__.py`（34 行）
- `agent/providers/base.py`（239 行）
- `agent/providers/factory.py`（313 行）
- `agent/providers/openai.py`（389 行）
- `agent/providers/qwen.py`（427 行）
- `agent/provider_settings.py`（244 行）
- `agent/tools/routing.py`（203 行）
- `agent/types.py` L249-325（AgentModel 协议部分，77 行）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/providers/__init__.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 仅对标 "Cline @cline/llms gateway" |
| `agent/providers/base.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline gateway provider format.ts" / "Cline llm-gateway.ts" |
| `agent/providers/factory.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline handler-factory.ts + provider-defaults.ts" |
| `agent/providers/openai.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline gateway openai-compatible client" |
| `agent/providers/qwen.py` | 7 处 | 0 处 | 见下方详表 |
| `agent/provider_settings.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline provider-settings.ts" |
| `agent/tools/routing.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 对标 "Cline model-tool-routing.ts" |
| `agent/types.py` L249-325 | 0 处 | 0 处 | AgentModel 协议部分无 "nanobot" 字样。docstring 对标 "Cline AgentModelRequest / AgentModelEvent / AgentModel" |

**P7.4 范围内 nanobot 残留总计：7 处注释残留 + 0 处实现逻辑残留。**

### 4.3 qwen.py nanobot 注释残留详表

| 行号 | 残留类型 | 内容 | 上下文 |
|------|---------|------|--------|
| L21 | 注释残留（docstring） | `兼容 nanobot 现有配置:` | 模块 docstring 的"兼容性说明"段，列出 nanobot 现有配置（DASHSCOPE_API_KEY / DashScope base URL / qwen-plus 默认模型 / OpenAI function calling） |
| L49 | 注释残留（注释行） | `# 默认流式空闲超时（秒），与 nanobot 一致` | `_DEFAULT_IDLE_TIMEOUT = 90` 常量注释，说明超时值与 nanobot 一致 |
| L116 | 注释残留（docstring） | `对标 nanobot openai_compat_provider.py 的客户端创建逻辑。` | `_create_client()` 方法 docstring，说明客户端创建逻辑对标 nanobot |
| L214 | 注释残留（docstring） | `对标 nanobot openai_compat_provider.py _build_kwargs() 方法。` | `_build_kwargs()` 方法 docstring，说明请求参数构建对标 nanobot |
| L253 | 注释残留（docstring） | `对标 nanobot _parse_chunks 的单 chunk 处理。` | `_parse_chunk()` 方法 docstring，说明 chunk 解析对标 nanobot |
| L385 | 注释残留（docstring） | `对标 nanobot _maybe_mapping() 方法。` | `_to_dict()` 辅助函数 docstring，说明对象转 dict 对标 nanobot |
| L406 | 注释残留（docstring） | `对标 nanobot _get_nested_int() 但更通用。` | `_get_nested()` 辅助函数 docstring，说明嵌套取值对标 nanobot |

### 4.4 实现逻辑残留检查

**0 处实现逻辑残留**。验证依据：

1. `qwen.py` 所有逻辑均基于 `openai` Python SDK 的 `AsyncOpenAI` 客户端（L119-125 `_create_client`），无 nanobot 代码导入或复制
2. `openai.py` 同样基于 `AsyncOpenAI`（L131-139 `_create_client`），无 nanobot 代码
3. `base.py` 的 `apply_capability_downgrade` 是 Stage 13.1 全新实现，对标 Cline llm-gateway.ts，无 nanobot 逻辑
4. `factory.py` 的 `BUILTIN_PROVIDER_DEFAULTS` 是 Stage 7.8 全新实现，对标 Cline BUILTIN_PROVIDER_MANIFESTS，无 nanobot 逻辑
5. `provider_settings.py` 是 Stage 13.2 全新实现，对标 Cline provider-settings.ts，无 nanobot 逻辑
6. `tools/routing.py` 是 Stage 7.x 全新实现，对标 Cline model-tool-routing.ts，无 nanobot 逻辑
7. `types.py` 的 AgentModel 协议是 Stage 1.x 全新实现，对标 Cline AgentModel 接口，无 nanobot 逻辑

**结论**：P7.4 范围内 nanobot 残留全部为 docstring/注释中的"对标 nanobot"说明性文字，无实际代码逻辑残留。这些注释属"历史溯源标注"，不影响功能，但若需清除可统一替换为"对标 Cline"或删除。

### 4.5 范围外残留说明

以下文件的 nanobot 残留**超出 P7.4 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1 |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20 |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20 |
| `agent/skills/skill_tool.py` L18 | 注释残留 | "nanobot 子 agent 隔离执行"对比说明 | P4.x |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |
| `agent/skills/__init__.py` | 注释残留 | 待确认 | P4.x |
| `agent/tools/__init__.py` | 注释残留 | 待确认 | P3.x |

---

## 五、修复建议

### 5.1 高优先级：Anthropic 适配缺失

**问题**：Cline `vendors/anthropic.ts` 通过 `@ai-sdk/anthropic` 实现 Anthropic 原生协议适配，支持 Claude 的 thinking blocks / prompt cache / signature 等原生能力。Charles 完全无 Anthropic 适配，Claude 模型只能通过 OpenAI 兼容代理（如 OpenRouter）访问，丢失原生能力。

**修复建议**：**不建议补**。理由：
1. Charles 量化场景主要使用 Qwen / DeepSeek 等国内模型，Claude 使用频率低
2. Anthropic 原生协议（Messages API）与 OpenAI 兼容协议差异大，需引入 `anthropic` Python SDK
3. 若需 Claude 能力，可通过 OpenRouter（Charles 可通过 `openai-compatible` provider + OpenRouter base_url 接入）
4. 补 Anthropic 适配会引入额外依赖和测试成本，与 Charles "OpenAI 兼容优先" 架构原则不符

**权衡**：若未来 Charles 需要深度使用 Claude 的 thinking blocks 或 prompt cache，可考虑补 `agent/providers/anthropic.py`，使用 `anthropic` Python SDK 的 `AsyncAnthropic` 客户端。当前无需。

### 5.2 高优先级：错误处理专用化

**问题**：Charles 错误处理仅 `try/except` 兜底 + `str(e)` 透传，无 provider 专用错误类型。Cline 有 `ClineNotSubscribedError` / `ClinePassLimitError` 等专用错误 + `extractErrorMessage` 多层级提取 + `onResponseError` 钩子。

**修复建议**：**部分补**。理由：
1. Charles 无 ClinePass 等订阅机制，不需要 `ClineNotSubscribedError` 等专用错误
2. 但 `extractErrorMessage` 的多层级提取逻辑值得借鉴——provider 返回的 JSON 错误体（如 `{"error": {"message": "..."}}`）应被解析
3. 建议在 `agent/providers/base.py` 新增 `extract_error_message(error: Exception) -> str` 辅助函数，对标 Cline `format.ts` 的 `extractErrorMessage`
4. 建议在 `QwenModel` / `OpenAIModel` 的 `except Exception as e` 分支调用此函数，替代 `str(e)`

**优先级**：中。当前 `str(e)` 对 openai SDK 的错误已能提取有用信息（openai SDK 的 APIError 已含 message），但解析 JSON body 能提供更精确的错误信息。

### 5.3 中优先级：provider 清单扩展

**问题**：Charles 仅 7 个 provider，Cline 40+。Charles 缺少 ollama / litellm / openrouter 等本地/代理 provider。

**修复建议**：**按需补**。理由：
1. Charles 量化场景下，`openai-compatible` provider 已能覆盖任意 OpenAI 兼容端点（包括 Ollama / vLLM / LiteLLM 等）
2. 补 `ollama` 专用 provider 的价值：自动从 `http://localhost:11434/api/tags` 拉取本地模型列表（Cline `builtins.ts` L867-883）
3. 补 `openrouter` 专用 provider 的价值：自动支持 sticky session（Cline `builtins.ts` L51-57）+ 多模型路由
4. 建议：若 Charles 未来需要本地模型或 OpenRouter 多模型路由，再补专用 provider。当前 `openai-compatible` 足够

### 5.4 低优先级：qwen.py nanobot 注释清理

**问题**：`qwen.py` 含 7 处 "对标 nanobot" 注释残留（L21 / L49 / L116 / L214 / L253 / L385 / L406），属历史溯源标注。

**修复建议**：**可选清理**。理由：
1. 这些注释不影响功能，仅是历史溯源
2. 清理可统一替换为"对标 Cline"或删除
3. 优先级低，与其他阶段的 nanobot 残留清理一并进行

**建议替换方案**：
- L21 `兼容 nanobot 现有配置:` → `兼容既有 DashScope 配置:`
- L49 `# 默认流式空闲超时（秒），与 nanobot 一致` → `# 默认流式空闲超时（秒）`
- L116 `对标 nanobot openai_compat_provider.py 的客户端创建逻辑。` → 删除（对标 Cline 已在模块 docstring 说明）
- L214 `对标 nanobot openai_compat_provider.py _build_kwargs() 方法。` → 删除
- L253 `对标 nanobot _parse_chunks 的单 chunk 处理。` → 删除
- L385 `对标 nanobot _maybe_mapping() 方法。` → 删除
- L406 `对标 nanobot _get_nested_int() 但更通用。` → 删除

### 5.5 低优先级：ApiHandler 接口缺失

**问题**：Cline `handler.ts` L25-69 定义了 `ApiHandler` 接口（getMessages / createMessage / getModel / abort），Charles 无此接口。

**修复建议**：**不建议补**。理由：
1. Cline 的 `ApiHandler` 是历史遗留接口，主要用于兼容 VS Code `vscode.lm` 等 host handler
2. Cline 自身也通过 `apihandler-agent-model-adapter.ts` 将 `ApiHandler` 适配到 `AgentModel` 协议
3. Charles 无 host handler 概念，直接用 `AgentModel` 协议即可，无需额外的 `ApiHandler` 层
4. 补 `ApiHandler` 会引入不必要的抽象层，与 Charles 简洁架构原则不符

---

## 六、验证方法

### 6.1 Provider 列表覆盖验证

1. Grep `third_party/cline/sdk/packages/llms/src/providers/builtins.ts` 搜索 `^\s+id: "[a-z]` 模式，确认 40 个 provider（含 sonnet / cline / openai-compatible / deepseek / xai / together / groq / cerebras / sambanova / litellm / vercel-ai-gateway / v0 / aihubmix / hicap / nousResearch / huawei-cloud-maas / qwen / qwen-code / doubao / zai / zai-coding-plan / kilo / openrouter / ollama / lmstudio / oca / asksage / openai-native / openai-codex / openai-codex-cli / anthropic / claude-code / gemini / vertex / bedrock / mistral / minimax / opencode / dify / sapaicore）
2. 读取 `agent/providers/factory.py` L104-181 `BUILTIN_PROVIDER_DEFAULTS`，确认 7 个 provider（qwen / openai / openai-native / deepseek / moonshot / zhipu / openai-compatible）
3. 确认 Charles 缺失：anthropic / bedrock / vertex / gemini / ollama / openrouter / litellm / mistral / minimax / claude-code 等

### 6.2 API 调用方式验证

1. 读取 `third_party/cline/sdk/packages/core/src/services/llms/handler-factory.ts` L182-257 `createAgentModelFromConfig`，确认三层抽象（AgentModel → Gateway → ai-sdk vendor）
2. 读取 `agent/providers/factory.py` L194-271 `create_model`，确认两层抽象（AgentModel → QwenModel/OpenAIModel）
3. 确认 Charles 无 `hasRegisteredHandler` / `createGateway` / `GatewayRegistry` 等机制

### 6.3 流式响应事件模型验证

1. 读取 `third_party/cline/sdk/packages/llms/src/providers/stream.ts` L16-21，确认 `ApiStreamChunk` 五种类型
2. 读取 `agent/types.py` L281-310，确认 `AgentModelEvent` 五种 type（text-delta / reasoning-delta / tool-call-delta / usage / finish）
3. 确认事件类型一一对应（text↔text-delta / reasoning↔reasoning-delta / usage↔usage / tool_calls↔tool-call-delta / done↔finish）

### 6.4 错误处理验证

1. 读取 `third_party/cline/sdk/packages/llms/src/providers/errors.ts` L47-79，确认 3 种专用错误类型（ClineNotSubscribedError / ClineOrgIndividualInferenceSubscriptionError / ClinePassLimitError）
2. 读取 `third_party/cline/sdk/packages/llms/src/providers/format.ts` L1-100+，确认 `extractErrorMessage` 多层级提取
3. 读取 `agent/providers/qwen.py` L163-209 / `agent/providers/openai.py` L147-208，确认仅 `try/except` + `TimeoutError` + `str(e)` 透传

### 6.5 apply_capability_downgrade 验证

1. 读取 `agent/providers/base.py` L43-108，确认 `apply_capability_downgrade` 函数（vision/reasoning/tools 降级 + 深拷贝）
2. 读取 `third_party/cline/sdk/packages/llms/src/providers/builtins.ts` L427-478，确认 `toGatewayCapabilities`（capability 映射）
3. 确认 Charles 在请求层降级，Cline 在 gateway 层映射

### 6.6 provider-settings 持久化验证

1. 读取 `agent/provider_settings.py` L90-220 `ProviderSettingsStore`，确认 yaml 持久化 + 原子写入 + UPDATABLE_FIELDS 白名单
2. 读取 `third_party/cline/sdk/packages/core/src/services/llms/provider-settings.ts` L142-310，确认 Zod schema + toProviderConfig
3. 确认 Charles 有文件持久化，Cline 侧重 schema 校验

### 6.7 tool_call_id 稳定性验证

1. 读取 `agent/providers/qwen.py` L160-358，确认 `tool_call_ids: dict[int, str]` + index 复用 + uuid fallback
2. 读取 `agent/providers/openai.py` L161-328，确认同样机制
3. Grep `third_party/cline/sdk/packages/llms/src/providers/vendors/openai-compatible.ts` 搜索 `toolCallId|tool_call_id`，确认 0 匹配（Cline 由 AI SDK 内部处理）

### 6.8 nanobot 残留验证

1. Grep `agent/providers/` 目录搜索 `nanobot`（case-insensitive），确认 7 匹配（全部在 `qwen.py`）
2. Grep `agent/provider_settings.py` 搜索 `nanobot`，确认 0 匹配
3. Grep `agent/tools/routing.py` 搜索 `nanobot`，确认 0 匹配
4. Grep `agent/types.py` L249-325 搜索 `nanobot`，确认 0 匹配
5. 逐行检查 `qwen.py` L21 / L49 / L116 / L214 / L253 / L385 / L406，确认全部为注释/docstring，无代码逻辑

---

## 七、附录

### 7.1 Cline BUILTIN_SPEC_OVERRIDES 完整 provider 清单（40 个）

| # | provider_id | family | default_model_id | base_url | 说明 |
|---|------------|--------|------------------|----------|------|
| 1 | openai-compatible | openai-compatible | gpt-4o | api.openai.com/v1 | 通用 OpenAI 兼容 |
| 2 | cline | openai-compatible | anthropic/claude-sonnet-4.6 | cline api/v1 | Cline 计费 |
| 3 | cline-pass | openai-compatible | (generated) | cline api/v1 | ClinePass 订阅 |
| 4 | deepseek | openai-compatible | deepseek-v4-flash | api.deepseek.com/v1 | DeepSeek |
| 5 | xai | openai-compatible | grok-4.20-0309 | api.x.ai/v1 | xAI Grok |
| 6 | together | openai-compatible | Qwen/Qwen3.5-397B | api.together.xyz/v1 | Together AI |
| 7 | groq | openai-compatible | moonshotai/kimi-k2 | api.groq.com/openai/v1 | Groq LPU |
| 8 | cerebras | openai-compatible | zai-glm-4.7 | api.cerebras.ai/v1 | Cerebras |
| 9 | sambanova | openai-compatible | - | api.sambanova.ai/v1 | SambaNova |
| 10 | litellm | openai-compatible | gpt-5.4 | localhost:4000/v1 | LiteLLM 代理 |
| 11 | vercel-ai-gateway | openai-compatible | alibaba/qwen3.6-plus | ai-gateway.vercel.sh/v1 | Vercel AI Gateway |
| 12 | v0 | openai-compatible | v0-1.5-md | api.v0.dev/v1 | Vercel V0 |
| 13 | aihubmix | openai-compatible | gpt-4o | api.aihubmix.com/v1 | AI Hub Mix |
| 14 | hicap | openai-compatible | hicap-pro | api.hicap.ai/v1 | HiCap |
| 15 | nousResearch | openai-compatible | DeepHermes-3-Llama | inference-api.nousresearch.com/v1 | Nous Research |
| 16 | huawei-cloud-maas | openai-compatible | DeepSeek-R1 | infer-modelarts.cn-southwest-2.myhuaweicloud.com/v1 | 华为云 MaaS |
| 17 | qwen | openai-compatible | qwen-plus-latest | dashscope.aliyuncs.com/compatible-mode/v1 | 阿里 Qwen |
| 18 | qwen-code | openai-compatible | qwen3-coder-plus | dashscope.aliyuncs.com/compatible-mode/v1 | Qwen Code OAuth |
| 19 | doubao | openai-compatible | doubao-1-5-pro-256k | ark.cn-beijing.volces.com/api/v3 | 豆包 |
| 20 | zai | openai-compatible | glm-5v-turbo | api.z.ai/api/paas/v4 | Z.AI GLM |
| 21 | zai-coding-plan | openai-compatible | glm-5.2 | api.z.ai/api/coding/paas/v4 | Z.AI Coding Plan |
| 22 | kilo | openai-compatible | gpt-4o | api.kilo.ai/api/gateway | Kilo Gateway |
| 23 | openrouter | openai-compatible | anthropic/claude-sonnet-4.6 | openrouter.ai/api/v1 | OpenRouter |
| 24 | ollama | ollama | - | localhost:11434 | Ollama 本地 |
| 25 | lmstudio | openai-compatible | - | localhost:1234/v1 | LM Studio 本地 |
| 26 | oca | openai-compatible | anthropic/claude-3-7-sonnet | code.aiservice.us-chicago-1.oci.oraclecloud.com | Oracle Code Assist |
| 27 | asksage | openai-compatible | gpt-4o | api.asksage.ai/server | AskSage |
| 28 | openai-native | openai | gpt-5.4 | api.openai.com/v1 | OpenAI 原生（Responses API） |
| 29 | openai-codex | openai | gpt-5.4 | chatgpt.com/backend-api/codex | OpenAI ChatGPT 订阅 |
| 30 | openai-codex-cli | openai-codex | gpt-5.6-sol | chatgpt.com/backend-api/codex | OpenAI Codex CLI |
| 31 | anthropic | anthropic | claude-sonnet-5 | api.anthropic.com/v1 | Anthropic 原生 |
| 32 | claude-code | claude-code | sonnet | - | Claude Code SDK |
| 33 | gemini | google | - | generativelanguage.googleapis.com/v1beta | Google Gemini |
| 34 | vertex | vertex | - | - | Google Vertex AI |
| 35 | bedrock | bedrock | minimax.minimax-m2.5 | - | AWS Bedrock |
| 36 | mistral | mistral | - | api.mistral.ai/v1 | Mistral |
| 37 | minimax | anthropic | MiniMax-M2.5 | api.minimax.io/anthropic/v1 | MiniMax（Anthropic 兼容） |
| 38 | opencode | opencode | openai/gpt-5.6-sol | - | OpenCode SDK |
| 39 | dify | dify | default | - | Dify workflow |
| 40 | sapaicore | sap-ai-core | anthropic--claude-3.5-sonnet | - | SAP AI Core |

### 7.2 Charles BUILTIN_PROVIDER_DEFAULTS 完整 provider 清单（7 个）

| # | provider_id | base_url | default_model_id | capabilities | env_key |
|---|------------|----------|------------------|--------------|---------|
| 1 | qwen | dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus | reasoning, tools, streaming | DASHSCOPE_API_KEY |
| 2 | openai | "" (SDK 默认) | gpt-4o | reasoning, tools, streaming, vision, structured-output, prompt-cache | OPENAI_API_KEY |
| 3 | openai-native | "" (SDK 默认) | gpt-4o | 同上 | OPENAI_API_KEY |
| 4 | deepseek | api.deepseek.com/v1 | deepseek-chat | reasoning, tools, streaming | DEEPSEEK_API_KEY |
| 5 | moonshot | api.moonshot.cn/v1 | moonshot-v1-8k | tools, streaming | MOONSHOT_API_KEY |
| 6 | zhipu | open.bigmodel.cn/api/paas/v4 | glm-4-plus | tools, streaming | ZHIPU_API_KEY |
| 7 | openai-compatible | "" (必须显式) | "" | reasoning, tools, streaming | OPENAI_API_KEY |

### 7.3 Cline vendor 协议适配文件清单

| vendor 文件 | 依赖 SDK | 协议 | Charles 对应 |
|------------|---------|------|--------------|
| `vendors/anthropic.ts` | `@ai-sdk/anthropic` | Anthropic Messages API | 无 |
| `vendors/bedrock.ts` | `@ai-sdk/amazon-bedrock` + `@aws-sdk/credential-providers` | AWS Bedrock Runtime | 无 |
| `vendors/vertex.ts` | `@ai-sdk/google-vertex` + `@ai-sdk/google-vertex/anthropic` | Google Vertex AI | 无 |
| `vendors/openai.ts` | `@ai-sdk/openai` | OpenAI Responses API | 无（Charles 用 Chat Completions） |
| `vendors/openai-compatible.ts` | `@ai-sdk/openai-compatible` | OpenAI Chat Completions | `agent/providers/openai.py`（用 `openai` Python SDK） |
| `vendors/ollama.ts` | `@ai-sdk/openai-compatible`（Ollama 原生 API） | Ollama API | 无 |
| `vendors/mistral.ts` | `@ai-sdk/mistral` | Mistral API | 无 |
| `vendors/google.ts` | `@ai-sdk/google` | Google Gemini API | 无 |
| `vendors/minimax-thinking.ts` | 自定义 fetch wrapper | MiniMax thinking | 无 |
| `vendors/community.ts` | `@ai-sdk/community` | 社区 provider（Dify / OpenCode / SAP AI Core） | 无 |

### 7.4 流式事件序列对比

```
Cline ApiStreamChunk 序列（vendor 层产出）:
  ┌── text chunk*           (delta.content)
  ├── reasoning chunk*      (delta.reasoning_content / thinking)
  ├── tool_calls chunk*     (delta.tool_calls，含 call_id + function)
  ├── usage chunk?          (inputTokens / outputTokens / cacheWrite / cacheRead / thoughtsTokenCount / totalCost)
  └── done chunk            (success / error / incompleteReason)


Charles AgentModelEvent 序列（QwenModel/OpenAIModel 层产出）:
  ┌── text-delta*           (delta.content)
  ├── reasoning-delta*      (delta.reasoning_content)
  ├── tool-call-delta*      (delta.tool_calls，含 index + tool_call_id + tool_name + input_text + metadata.provider_metadata)
  ├── usage?                (input_tokens / output_tokens / cache_read / cache_write / reasoning_token_count / total_cost)
  └── finish                (reason: STOP / TOOL_CALLS / MAX_TOKENS / ABORTED / ERROR)


差异点:
  1. Cline done chunk 含 success: bool，Charles finish 用 reason 枚举（含 ABORTED 区分用户中止 vs 真实错误）
  2. Cline tool_calls chunk 含 signature（Gemini），Charles 无 signature（OpenAI 兼容协议无此字段）
  3. Cline reasoning chunk 含 signature + redacted_data（Anthropic），Charles 无（OpenAI 兼容协议无此字段）
  4. Charles tool-call-delta 含 metadata.provider_metadata（request_id / model_version / finish_reason），Cline 无显式 metadata 字段
  5. Charles 的 abort_signal 检查在每个 chunk 间隙（qwen.py L170-176），Cline 的 AbortSignal 由 AI SDK 内部处理
```

### 7.5 Charles QwenModel 与 OpenAIModel 差异

| 维度 | QwenModel | OpenAIModel |
|------|-----------|-------------|
| 默认 base_url | dashscope.aliyuncs.com/compatible-mode/v1 | None（使用 openai SDK 默认） |
| 默认 idle_timeout | 90s | 120s |
| 默认 api_key 环境变量 | DASHSCOPE_API_KEY | OPENAI_API_KEY |
| reasoning_content 解析 | 无条件解析 | 按 `supports_reasoning` 开关 |
| provider_id | 固定 "qwen"（不暴露为类属性） | 构造参数，默认 "openai" |
| capabilities 默认值 | ["reasoning", "tools", "streaming"] | 按 supports_reasoning 派生 |
| 工厂分支 | `factory.py` L247-257 专用分支 | `factory.py` L260-271 通用分支 |
| nanobot 注释残留 | 7 处 | 0 处 |

### 7.6 双方 Provider 适配架构对比

```
Cline Provider 适配架构:
  ┌──────────────────────────────────────────┐
  │ AgentModel (shared/agent.ts)             │  协议层
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ GatewayModelAdapter (gateway.ts L54-118) │  适配层
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ DefaultGateway + GatewayRegistry         │  网关层
  │   - registerProvider()                   │
  │   - configureProvider()                  │
  │   - resolveModel()                       │
  │   - createProvider()                     │
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ @ai-sdk/* vendor                         │  vendor 层
  │   - anthropic.ts (@ai-sdk/anthropic)     │
  │   - openai.ts (@ai-sdk/openai)           │
  │   - bedrock.ts (@ai-sdk/amazon-bedrock)  │
  │   - vertex.ts (@ai-sdk/google-vertex)    │
  │   - openai-compatible.ts                 │
  │   - ollama.ts / mistral.ts / google.ts   │
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ ApiStreamChunk (stream.ts)               │  事件层
  └──────────────────────────────────────────┘


Charles Provider 适配架构:
  ┌──────────────────────────────────────────┐
  │ AgentModel Protocol (types.py L313-325)  │  协议层
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ QwenModel / OpenAIModel                  │  适配层（直接实现）
  │   - stream()                             │
  │   - _build_kwargs()                      │
  │   - _parse_chunk()                       │
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ openai Python SDK AsyncOpenAI            │  SDK 层
  │   - chat.completions.create(stream=True) │
  └──────────────────────────────────────────┘
                    ↓
  ┌──────────────────────────────────────────┐
  │ AgentModelEvent (types.py L281-310)      │  事件层
  └──────────────────────────────────────────┘


差异总结:
  1. Cline 4 层抽象（AgentModel → Adapter → Gateway → vendor），Charles 2 层（AgentModel → QwenModel/OpenAIModel）
  2. Cline gateway 支持动态注册，Charles 静态工厂分支
  3. Cline vendor 走 ai-sdk（多协议），Charles 走 openai SDK（仅 OpenAI 兼容协议）
  4. Charles 简洁直接，无 gateway 开销；Cline 扩展性强，支持 host handler
```
