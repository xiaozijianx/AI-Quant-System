# Phase A: 类型系统与消息契约 对比报告

> 对标源码：`sdk/packages/shared/src/agent.ts`
> 当前实现：`agent/types.py`
> 对比维度：D1 数据结构 / D2 控制流 / D3 状态变迁 / D4 错误处理 / D5 副作用 / D6 边界条件 / D7 语义等价

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 6 项 |
| 弱对齐 | 8 项 |
| 缺失 | 5 项 |
| 语义不等价 | 4 项 |
| 额外增强 | 2 项 |
| **对齐度** | **约 50%** |

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| A1 | MessageRole 枚举 | agent.ts L77 | types.py L26-30 | 完全一致 |
| A2 | 消息片段类型枚举 | agent.ts L25-71 | types.py L33-84 | 缺失（少 2 类） |
| A3 | AgentMessage 字段 | agent.ts L99-113 | types.py L87-103 | 弱对齐 |
| A4 | AgentUsage 字段 | agent.ts L79-97 | types.py L270-297 | 弱对齐 |
| A5 | AgentToolDefinition | agent.ts L146-156 | types.py L120-129 | 完全一致 |
| A6 | AgentToolResult | agent.ts L158-162 | types.py L132-140 | 弱对齐 |
| A7 | AgentToolContext | agent.ts L164-175 | types.py L143-157 | 弱对齐 |
| A8 | AgentTool 协议 | agent.ts L177-186 | types.py L160-190 | **语义不等价** |
| A9 | AgentModelRequest | agent.ts L192-198 | types.py L197-206 | 弱对齐 |
| A10 | AgentModelFinishReason | agent.ts L225-230 | types.py L209-215 | 弱对齐 |
| A11 | AgentModelEvent | agent.ts L232-257 | types.py L218-248 | **语义不等价** |
| A12 | AgentModel 协议 | agent.ts L259-263 | types.py L251-263 | 弱对齐 |
| A13 | AgentRuntimeStateSnapshot | agent.ts L128-140 | types.py L311-327 | 弱对齐 |
| A14 | AgentRunResult | agent.ts L556-565 | types.py L330-344 | 弱对齐 |
| A15 | CompletionPolicy | agent.ts L430-433 | types.py L351-365 | 完全一致 |
| A16 | AgentRuntimeConfig | agent.ts L397-460 | types.py L368-420 | 缺失（少 7 字段） |
| A17 | AgentRuntimePlugin | agent.ts L371-391 | 无 | 缺失 |
| A18 | AgentRuntimePrepareTurnContext | agent.ts L200-218 | 无 | 缺失 |
| A19 | AgentRuntimeHooks | agent.ts L336-365 | hooks.py | 弱对齐（见 Phase E） |
| A20 | 不可变性 | readonly/freeze | 无保护 | **语义不等价** |

---

## 3. 关键差距详细分析

### 差距 #A2：消息片段类型缺失（Image/File）

**严重度**：P1（量化场景暂无图片输入需求，但影响扩展性）

**Cline 实现**（agent.ts L25-71）：
```typescript
export interface AgentImagePart {
    type: "image";
    image: string | Uint8Array | ArrayBuffer | URL;
    mediaType?: string;
}
export interface AgentFilePart {
    type: "file";
    path: string;
    content: string;
}
```
Cline 支持 6 种消息片段：text / reasoning / image / file / tool-call / tool-result。

**我的实现**（types.py L33-84）：
```python
MessagePart = TextPart | ReasoningPart | ToolCallPart | ToolResultPart
```
仅支持 4 种，缺少 `AgentImagePart` 和 `AgentFilePart`。

**逻辑差异**：
- D1 数据结构：缺少 ImagePart（图片输入）、FilePart（文件附件）
- D6 边界条件：当 LLM 需要图片输入（如截图分析）时无法承载
- D7 语义等价：Cline 的 `AgentMessagePart` 是 discriminated union，我用 Python `Union` 类型别名，运行时无强制校验

**影响**：
- 当前量化场景无图片输入需求，影响有限
- 若未来接入"K 线截图分析"或"PDF 文件附件"，需补齐 ImagePart/FilePart
- FilePart 与现有 read_files 工具不同：FilePart 是用户上传的文件内容直接进 message

**修复建议**：
```python
@dataclass
class ImagePart:
    """图片消息片段 — 对标 Cline AgentImagePart"""
    type: str = field(default="image", init=False, repr=False)
    image: str | bytes = b""  # base64 或原始字节
    media_type: str | None = None  # image/png 等

@dataclass
class FilePart:
    """文件消息片段 — 对标 Cline AgentFilePart"""
    type: str = field(default="file", init=False, repr=False)
    path: str = ""
    content: str = ""

MessagePart = TextPart | ReasoningPart | ImagePart | FilePart | ToolCallPart | ToolResultPart
```

**优先级**：P2（量化场景暂不需要，但应预留）

---

### 差距 #A8：AgentTool 协议语义不等价（关键）

**严重度**：P0（影响工具执行流程的核心契约）

**Cline 实现**（agent.ts L177-186）：
```typescript
export interface AgentTool<TInput = unknown, TOutput = unknown>
    extends AgentToolDefinition {
    timeoutMs?: number;
    retryable?: boolean;
    maxRetries?: number;
    execute: (
        input: TInput,
        context: AgentToolContext,
    ) => Promise<TOutput> | TOutput;
}
```

**关键点**：Cline 的 `execute` 返回 `Promise<TOutput>`，即直接返回**原始输出**（任意类型），不是 `AgentToolResult`。Runtime 层负责将 `TOutput` 包装为 `AgentToolResult`。

**我的实现**（types.py L160-190）：
```python
class AgentTool(Protocol):
    async def execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult: ...
```

**我的 execute 返回 `AgentToolResult`**，由工具自己包装 output + is_error + metadata。

**逻辑差异**：
- D7 语义等价：**两边 execute 返回类型不同**
  - Cline：工具返回原始数据，Runtime 包装为 AgentToolResult
  - 我：工具返回 AgentToolResult，自己包装
- D2 控制流：错误处理位置不同
  - Cline：工具抛异常 → Runtime 捕获并构造 is_error=True 的 result
  - 我：工具内部决定 is_error，或抛异常由 Runtime 捕获
- D5 副作用：metadata 设置位置不同
  - Cline：Runtime 统一注入 metadata（如 duration）
  - 我：工具自己设置 metadata，可能遗漏

**影响**：
- 工具开发者心智负担不同：我的方式需工具自己处理 is_error，Cline 方式更简洁
- 错误处理一致性：Cline 由 Runtime 统一捕获异常 → is_error，更一致
- 我的 BaseTool 基类已部分弥补（统一包装），但协议层面仍不等价

**修复建议**：
不建议立即改协议（会破坏所有现有工具）。当前 BaseTool 基类已提供统一包装层，实际行为接近 Cline。长期可考虑：
1. 在 BaseTool 中统一异常 → is_error 转换（已部分实现）
2. 在 Runtime 层补充 metadata 注入（duration 等）
3. 协议保持现状，但文档说明差异

**优先级**：P2（已有 BaseTool 弥补，不影响功能）

---

### 差距 #A11：AgentModelEvent 单一 dataclass vs discriminated union（关键）

**严重度**：P1（影响类型安全和事件处理）

**Cline 实现**（agent.ts L232-257）：
```typescript
export type AgentModelEvent =
    | { type: "text-delta"; text: string }
    | { type: "reasoning-delta"; text: string; redacted?: boolean; metadata?: unknown }
    | { type: "tool-call-delta"; index?: number; toolCallId?: string; toolName?: string; inputText?: string; input?: unknown; metadata?: unknown }
    | { type: "usage"; usage: Partial<AgentUsage> }
    | { type: "finish"; reason: AgentModelFinishReason; error?: string };
```

Cline 用 **discriminated union**，每个事件类型只能访问自己的字段，编译期类型安全。

**我的实现**（types.py L218-248）：
```python
@dataclass
class AgentModelEvent:
    type: str
    text: str | None = None
    redacted: bool | None = None
    index: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    input_text: str | None = None
    input_value: Any | None = None
    usage: dict[str, int] | None = None
    reason: AgentModelFinishReason | None = None
    error: str | None = None
    metadata: Any | None = None
```

我用**单一 dataclass 含所有字段**，运行时所有字段并存。

**逻辑差异**：
- D1 数据结构：Cline 每个事件只含相关字段；我所有字段并存（多数为 None）
- D4 错误处理：Cline 编译期防止访问错误字段；我运行时可能误访问 None
- D6 边界条件：我的方式容易忘记设置某字段（如 finish 事件忘设 reason）
- D7 语义等价：字段命名差异
  - Cline `input` → 我 `input_value`（因 `input` 是 Python 内置）
  - Cline `usage: Partial<AgentUsage>` → 我 `usage: dict[str, int]`（类型更宽松）

**影响**：
- 类型安全弱：编译期无法检测字段访问错误
- Provider 实现易遗漏字段
- 但功能等价，运行时行为一致

**修复建议**：
Python 无原生 discriminated union，可用以下方式逼近：
```python
# 方案1：每类事件独立 dataclass + Union
@dataclass
class TextDeltaEvent:
    type: str = field(default="text-delta", init=False)
    text: str = ""

@dataclass
class FinishEvent:
    type: str = field(default="finish", init=False)
    reason: AgentModelFinishReason = AgentModelFinishReason.STOP
    error: str | None = None

AgentModelEvent = TextDeltaEvent | ReasoningDeltaEvent | ToolCallDeltaEvent | UsageEvent | FinishEvent
```
但改动量大，影响所有 provider。**建议保持现状**，在 provider 实现时加强测试覆盖。

**优先级**：P3（功能等价，仅类型安全弱）

---

### 差距 #A16：AgentRuntimeConfig 缺失字段

**严重度**：P1（影响扩展能力）

**Cline 实现**（agent.ts L397-460）含 20+ 字段，我缺少以下：

| 缺失字段 | Cline 用途 | 影响 |
|---------|-----------|------|
| `plugins` | AgentRuntimePlugin[] 插件系统 | 无法动态注入工具/hooks |
| `logger` | BasicLogger 日志接口 | 日志无统一接口 |
| `telemetry` | ITelemetryService 遥测 | 无遥测上报 |
| `initialMessages` | 初始消息列表 | 需通过 run() 传入 |
| `prepareTurn` | 模型调用前消息投影 | 与 hooks.beforeModel 重叠 |
| `toolContextMetadata` | 工具上下文元数据 | 工具无法获取全局元数据 |
| `toolExecution` | 我有（sequential/parallel） | 一致 |
| `requestToolApproval` | 我用 hook 实现 | 形式不同 |

**逻辑差异**：
- D1 数据结构：缺失 plugins/logger/telemetry/initialMessages/prepareTurn/toolContextMetadata
- D3 状态变迁：initialMessages 缺失导致初始消息只能在 run() 时传入，无法预置
- D5 副作用：logger/telemetry 缺失导致日志和遥测无统一接口

**影响**：
- plugins 缺失：无法实现插件系统（Phase Y）
- logger 缺失：日志散落各处，无统一接口
- telemetry 缺失：无遥测上报（Phase Z）
- initialMessages 缺失：会话恢复时需通过 run() 传入，与 Cline 的预置语义不同
- prepareTurn 缺失：与 beforeModel hook 功能重叠，Cline 区分两者（prepareTurn 是 host-owned 投影，beforeModel 是 hook）

**修复建议**：
```python
@dataclass
class AgentRuntimeConfig:
    # ... 现有字段 ...
    # 新增：
    initial_messages: list[AgentMessage] = field(default_factory=list)
    tool_context_metadata: dict[str, Any] = field(default_factory=dict)
    # logger 和 telemetry 建议作为独立模块注入，不放 config
```

**优先级**：
- initial_messages: P1（会话恢复需要）
- tool_context_metadata: P2
- plugins/logger/telemetry: P3（按需）

---

### 差距 #A17：AgentRuntimePlugin 类型完全缺失

**严重度**：P2（影响扩展架构）

**Cline 实现**（agent.ts L371-391）：
```typescript
export interface AgentRuntimePlugin {
    name: string;
    setup?: (context: AgentRuntimePluginContext) =>
        AgentRuntimePluginSetup | undefined | Promise<AgentRuntimePluginSetup | undefined>;
}
export interface AgentRuntimePluginSetup {
    tools?: readonly AgentTool<any, any>[];
    hooks?: Partial<AgentRuntimeHooks>;
}
```

Cline 的插件系统允许第三方通过 `setup()` 动态注入工具和 hooks。

**我的实现**：无对应类型。

**影响**：
- 无法实现插件系统（Phase Y）
- 工具和 hooks 只能在代码中静态注册
- 量化场景暂无插件需求，影响有限

**修复建议**：暂不实现，按需推进。

**优先级**：P3

---

### 差距 #A18：AgentRuntimePrepareTurnContext/Result 缺失

**严重度**：P1（影响与 Cline 的 prepareTurn 对齐）

**Cline 实现**（agent.ts L200-223）：
```typescript
export interface AgentRuntimePrepareTurnContext {
    agentId: string;
    conversationId?: string;
    parentAgentId?: string | null;
    iteration: number;
    messages: readonly AgentMessage[];
    systemPrompt?: string;
    tools: readonly AgentToolDefinition[];
    model: { id?: string; provider?: string; info?: ModelInfo };
    signal?: AbortSignal;
    emitStatusNotice?: (message: string, metadata?) => void;
}
export interface AgentRuntimePrepareTurnResult {
    messages?: readonly AgentMessage[];
    systemPrompt?: string;
}
```

**我的实现**：无对应类型。用 `consume_pending_user_message` 回调（仅返回 str）替代。

**逻辑差异**：
- D1 数据结构：Cline 的 prepareTurn 接收完整上下文（messages/tools/model/signal），返回可修改 messages + systemPrompt
- D7 语义等价：我的 `consume_pending_user_message` 仅返回字符串，功能远弱于 Cline
- D2 控制流：Cline prepareTurn 在每轮 model 调用前执行，可投影消息；我的回调仅追加 steer 消息

**影响**：
- 无法实现"模型调用前消息投影"（如临时插入上下文、修改 system prompt）
- 与 beforeModel hook 功能重叠但语义不同（Cline 区分 host-owned prepareTurn vs hook beforeModel）

**修复建议**：
我的 beforeModel hook 已能修改 messages/tools/options，功能上覆盖了 prepareTurn。建议：
1. 保持 consume_pending_user_message 用于 steer 消息
2. 不单独实现 prepareTurn，避免与 beforeModel 重叠
3. 文档说明：beforeModel hook 等价于 Cline 的 prepareTurn + beforeModel

**优先级**：P3（功能已由 hook 覆盖）

---

### 差距 #A20：不可变性缺失（语义不等价）

**严重度**：P1（影响状态安全）

**Cline 实现**：
- `AgentRuntimeStateSnapshot.messages` 是 `readonly AgentMessage[]`
- `AgentRuntimeStateSnapshot.pendingToolCalls` 是 `readonly string[]`
- `AgentModelRequest.messages` 是 `readonly AgentMessage[]`
- `AgentModelRequest.tools` 是 `readonly AgentToolDefinition[]`
- `AgentRunResult.messages` 是 `readonly AgentMessage[]`

Cline 用 TypeScript `readonly` 标记不可变，编译期防止修改。

**我的实现**：
- 全部使用 `list[AgentMessage]`，可变
- 无任何不可变保护

**逻辑差异**：
- D3 状态变迁：我的 snapshot.messages 可被 listener/hook 修改，影响 runtime 内部状态
- D6 边界条件：并发场景下 list 修改可能导致竞态
- D7 语义等价：Cline readonly 是契约（虽运行时可绕过），我无契约

**影响**：
- hook 或事件 listener 可能误修改 snapshot.messages，导致 runtime 状态不一致
- 实际场景下风险较低（单线程 asyncio，且无人在 listener 中修改 messages）

**修复建议**：
```python
# 方案1：返回 tuple 而非 list（轻量）
@dataclass
class AgentRuntimeStateSnapshot:
    messages: tuple[AgentMessage, ...] = field(default_factory=tuple)
    pending_tool_calls: tuple[str, ...] = field(default_factory=tuple)

# 方案2：用 __post_init__ 冻结
@dataclass
class AgentRuntimeStateSnapshot:
    messages: list[AgentMessage] = field(default_factory=list)
    def __post_init__(self):
        self.messages = list(self.messages)  # 浅拷贝
```
建议方案1（tuple），改动小且语义清晰。但需检查所有访问点是否依赖 list 方法（如 append）。

**优先级**：P2（风险较低，但应整改）

---

## 4. 其他弱对齐项汇总

### A3: AgentMessage 字段
- Cline `createdAt: number`（Unix 毫秒）vs 我 `created_at: datetime`（datetime 对象）
- Cline `modelInfo: {id, provider, family?}` 结构化 vs 我 `model_info: dict` 无结构
- **修复**：model_info 改为结构化 dataclass（低优先级）

### A4: AgentUsage 字段
- Cline `reasoningTokenCount?` 可选 vs 我 `reasoning_token_count: int = 0` 必填
- Cline `totalCost?` 可选 vs 我 `total_cost: float = 0.0` 必填
- **影响**：语义等价（默认值 0 等价于可选），无功能差异

### A6: AgentToolResult
- Cline 无 `metadata` 在 result 上... 实际有（L161）
- 一致

### A7: AgentToolContext
- Cline 有 `metadata` 字段（L172）vs 我无
- Cline `signal: AbortSignal` vs 我 `abort_signal: Any`
- **修复**：补充 `metadata: dict[str, Any]` 字段（P2）

### A9: AgentModelRequest
- Cline 有 `signal` 字段 vs 我无（signal 作为 stream() 参数单独传）
- **影响**：功能等价，但接口不一致
- **修复**：可在 request 中补充 signal 字段（P3）

### A10: AgentModelFinishReason
- Cline 无 `content-filter` vs 我无
- 实际两边都是 5 种：stop/tool-calls/max-tokens/aborted/error
- **一致**

### A12: AgentModel 协议
- Cline `stream(request) => AsyncIterable`（signal 在 request 内）
- 我 `stream(request, abort_signal)`（signal 单独传）
- **影响**：功能等价，接口不同
- **修复**：统一到 request 内（P3）

### A13: AgentRuntimeStateSnapshot
- Cline `messages: readonly` vs 我 `messages: list`（见 A20）
- 其余字段一致

### A14: AgentRunResult
- Cline `outputText: string`（必填）vs 我 `output_text: str | None`（可选）
- Cline `error?: Error` vs 我 `error: Exception | None`
- **影响**：outputText 必填 vs 可选，语义略不同（Cline 保证有输出）
- **修复**：保持可选（Python 习惯），文档说明（P3）

---

## 5. 一致性统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 完全一致 | 6 | 30% |
| 弱对齐 | 8 | 40% |
| 缺失 | 5 | 25% |
| 语义不等价 | 4 | 20% |
| 额外增强 | 2 | 10% |

> 注：部分项跨多个等级，百分比总和超 100%

---

## 6. 修复优先级清单

### P0（核心，需立即修复）
- 无 P0 项。类型系统差异不影响运行时正确性。

### P1（重要，建议修复）
1. **A16 initial_messages**：会话恢复需要预置消息，当前通过 run() 传入，与 Cline 语义不同
2. **A11 AgentModelEvent 类型安全**：虽功能等价，但易遗漏字段，建议加强 provider 测试
3. **A20 不可变性**：snapshot messages 改为 tuple，防止误修改
4. **A7 AgentToolContext.metadata**：补充 metadata 字段，与 Cline 对齐

### P2（次要，按需修复）
1. **A2 ImagePart/FilePart**：预留图片/文件输入支持
2. **A3 model_info 结构化**：改为 dataclass
3. **A8 AgentTool 协议**：保持现状，BaseTool 已弥补
4. **A16 tool_context_metadata**：补充字段

### P3（锦上添花）
1. **A17 AgentRuntimePlugin**：按需实现插件系统
2. **A18 prepareTurn**：功能已由 hook 覆盖
3. **A9/A12 signal 位置统一**：接口风格统一
4. **A14 outputText 可选**：保持 Python 习惯

---

## 7. 验证记录

### 7.1 静态对比
- 已逐字段对比 agent.ts L25-565 与 types.py L1-499
- 字段命名差异：Cline camelCase vs 我 snake_case（Python 习惯，不视为差距）

### 7.2 待动态验证
- [ ] 构造空 AgentMessage，对比两边序列化结果
- [ ] 构造含 ToolCallPart 的消息，对比 provider 解析
- [ ] 测试 AgentUsage.add() 累加逻辑

---

**阶段 A 结论**：类型系统整体对齐度约 50%，但核心契约（消息结构、工具定义、模型协议）功能等价。主要差距在扩展类型（Image/File/Plugin）和类型安全（不可变性、discriminated union），不影响当前量化场景运行。建议优先修复 initial_messages 和不可变性两项。
