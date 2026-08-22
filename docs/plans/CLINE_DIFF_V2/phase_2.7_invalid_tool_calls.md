# Phase 2.7 invalidToolCalls + normalize_input_for_schema 对比报告

## 1. 执行摘要

Cline 与 Charles 在 invalidToolCalls 检测与 `normalizeJsonLikeStringsForSchema` 规范化逻辑上**核心算法完全对齐**：两者都采用"组装阶段写入 `message.metadata` + 单独函数解析输入 + JSON 字符串按 schema 反序列化"的设计。逐字段对照可以看出 Charles 的 `_parse_tool_input` / `_build_invalid_tool_input` / `_parse_tool_arguments` / `_normalize_input_for_schema` / `_parse_json_string_for_schema` / `_schema_accepts_kind` 与 Cline 的 `parseToolInput` / `buildInvalidToolInput` / `parseToolArguments` / `normalizeJsonLikeStringsForSchema` / `parseJsonStringForSchema` / `schemaAcceptsKind` 一一对应，错误消息文案与控制流均保留。

主要差距集中在以下三点：

1. **Charles 主动为 invalidToolCalls 生成错误 result 消息（Cline 不生成）**：Cline 仅把 invalidToolCalls 写入 `assistantMessage.metadata.invalidToolCalls`，**没有任何代码读取该字段并产生对应的 tool-result 消息**；Charles 在 `runtime.py` L681-689 / L722-724 实现了 `_extract_invalid_tool_calls` + `_build_invalid_tool_result_message`，主动为每个 invalidToolCall 生成 `ToolResultPart(is_error=True)` 并追加到 `state.messages`，让 LLM 下一轮能看到自己调用错了。这是 Charles 独有的增强（实现逻辑差异，非注释残留），但当前实现存在 **invalid_tool_messages 被双重追加 + 双重 emit** 的 bug（见差距 1）。

2. **metadata 字段命名风格不同 + ToolCallPart.metadata 写入策略不同**：Cline 使用 camelCase（`invalidToolCalls` / `rawInputText` / `inputParseError`），Charles 使用 snake_case（`invalid_tool_calls` / `raw_input_text` / `parse_error`）。更深层的差异是：Cline 的 `ToolCallPart.metadata` 仅在 `parsed.parseError` 存在时合并 `{inputParseError, rawInputText}`（L1045-1050），但 `parsed.parseError` 与 `parsed.reason` 同时出现，而 `parsed.reason` 存在时立即 `continue` 跳过 `content.push`——所以 Cline 的 ToolCallPart.metadata 实际**永远不会**包含 `inputParseError`/`rawInputText`（这是 Cline 的死代码）；Charles L1080-1083 则**无条件**把 `raw_input_text` 写入每个 ToolCallPart.metadata（只要有 input_text），偏离了 Cline 的精确语义。

3. **schema 校验调用时机与错误格式不同**：Cline 的 `validateWithZod` 在每个工具的 `execute()` 内部由工具自己调用（如 `definitions.ts` L263、L360、L532...），是工具职责；Charles 的 `_validate_input` 在 `BaseTool.execute()` 入口统一调用（base.py L117），是基类职责。错误格式上，Cline 的 `validateWithZod` 抛 `Error(z.prettifyError(result.error))`（单一字符串），Charles 的 `_validate_input` 返回结构化错误列表（field/message/validator/expected/got），并附 `received_input`，对 LLM 自我纠正更友好。

nanobot 残留检查结论：在 P2.7 直接相关的文件（`agent/runtime.py` 的 invalidToolCalls / normalize 段落 + `agent/tools/base.py` 的 `_validate_input`）中**未发现 nanobot 残留**（既无注释残留也无实现逻辑残留）。`runtime.py` 全文 grep `nanobot` 返回 0 行；`base.py` 中的 `_validate_input` 注释明确标注"对标 Cline validateWithZod"。P2.1 报告中提到的 nanobot 残留均位于 `providers/` / `tools/exec_tool.py` / `tools/file_tools.py` / `tools/web_tool.py` / `skills/` / `session.py` / `server.py` 等其他模块，与本阶段无关。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.7 章节定义的 6 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.7.1 | invalidToolCalls 检测条件 | `agent-runtime.ts` L1022-1039（`!assembly?.toolName` → `missing_name`；`parsed.reason` 非空 → `invalid_arguments`） | `runtime.py` L1050-1071（`assembly is None or not assembly.tool_name` → `missing_name`；`parsed.reason` 非空 → `invalid_arguments`） | 检测条件一一对应；两者均未实际使用 `missing_arguments` 枚举值（类型定义中存在但代码路径不产生） | 完全对齐 |
| 2.7.2 | invalidToolCalls 写入位置 | `agent-runtime.ts` L1054-1058 `createMessage("assistant", content, invalidToolCalls.length > 0 ? { invalidToolCalls } : undefined)` 写入 `message.metadata.invalidToolCalls`（camelCase） | `runtime.py` L1088-1097 `message.metadata["invalid_tool_calls"] = [...]`（snake_case） | 写入位置等价（assistant 消息 metadata）；字段命名风格不同（camelCase vs snake_case）；条目字段名也不同（Cline `toolCallId`/`toolName` vs Charles `tool_call_id`/`tool_name`） | 弱对齐（命名风格） |
| 2.7.3 | 下一轮错误 result 生成 | **无**——Cline 全仓库（`sdk/packages/agents` + `sdk/packages/core`）grep `invalidToolCalls` 仅 2 个文件命中（`agent-runtime.ts` 写入 + `types.ts` 类型定义），**无任何代码读取 metadata.invalidToolCalls 生成 tool-result 消息** | `runtime.py` L654 `_extract_invalid_tool_calls(message)` + L681-689 `_build_invalid_tool_result_message(itc)` 生成 `ToolResultPart(is_error=True)` + L687-689 立即追加到 `state.messages` 并 emit；L722-724 再次追加到 `tool_messages` 列表（**双重追加 bug**） | **Charles 独有增强**：主动让 LLM 下一轮看到 invalid tool call 的错误反馈；Cline 仅记录 metadata 供上层（如 SessionRuntime）观察，不自动反馈给 LLM。Charles 当前实现存在双重追加 + 双重 emit bug | Charles 超出 Cline（但有 bug） |
| 2.7.4 | normalizeJsonLikeStringsForSchema 递归深度 | `json.ts` L158-200：先 `parseJsonStringForSchema`（L126-156）尝试解析字符串为 object/array，再递归处理 array.items 和 object.properties；递归深度无显式上限，由 schema 嵌套层级决定 | `runtime.py` L2512-2553 `_normalize_input_for_schema` + L2555-2581 `_parse_json_string_for_schema` + L2583-2605 `_schema_accepts_kind`：算法一一对应，递归处理 list.items_schema 和 dict.properties | 算法完全等价；两者均无递归深度上限（依赖 schema 实际嵌套）；Charles 多了 `ensure_ascii=False`（在 `_parse_tool_arguments` 的 `json.loads` 中），对含中文输入更稳定 | 完全对齐 |
| 2.7.5 | schema 校验调用时机 | 每个 tool 的 `execute()` 内部由工具自己调用 `validateWithZod`（如 `definitions.ts` L263 `list_files`、L360 `search_codebase`、L532 `fetch_web_content`、L622 `apply_patch`、L676 `edit_file`...），是**工具职责**；runtime 层不调用 | `tools/base.py` L117 `BaseTool.execute()` 入口统一调用 `self._validate_input(input)`，是**基类职责**；runtime 层不调用 | 架构差异：Cline 工具各自为政（部分工具可能漏校验），Charles 基类强制统一校验（所有工具都校验）；Charles 更集中 | 弱对齐（架构不同） |
| 2.7.6 | schema 校验失败错误格式 | `zod.ts` L13-18 `validateWithZod`：`schema.safeParse(input)` 失败时 `throw new Error(z.prettifyError(result.error))`——抛出**单一字符串**，由 `executeToolCalls` 的 catch 块（`agent-runtime.ts` L1509-1515）转为 `{error: error.message}` + `isError:true` | `base.py` L117-127 `_validate_input` 返回**结构化错误列表**：`[{field, message, validator, expected?, got?}]`，最终输出 `{error: "参数 schema 校验失败", tool, validation_errors: [...], received_input: input}` + `is_error:true` | Charles 错误信息更结构化（含字段路径、期望值、实际值、完整输入），对 LLM 自我纠正更友好；Cline 是扁平字符串 | Charles 超出 Cline |

## 3. 重点差距详细说明

### 差距 1：Charles 主动生成 invalidToolCall 错误 result 消息（对应对比项 2.7.3）

**Cline 设计**（`agent-runtime.ts` L1054-1058）：

Cline 在 `generateAssistantMessage` 末尾把 invalidToolCalls 数组写入 `message.metadata`：

```typescript
const message = createMessage(
    "assistant",
    content,
    invalidToolCalls.length > 0 ? { invalidToolCalls } : undefined,
);
```

之后整个 SDK 仓库（`sdk/packages/agents` + `sdk/packages/core`）**没有任何代码读取 `metadata.invalidToolCalls`**：
- `agent-runtime.ts` 的 `executeToolCalls` (L1291-1310) 只处理 `toolCalls`（即 `content` 中的 `tool-call` part），不读取 metadata
- `session-runtime-orchestrator.ts` 的 `handleRuntimeEvent` (L1062-1191) 处理 `message-added`/`assistant-message` 事件时只调用 `syncConversationFromRuntimeMessage`，不读 metadata
- `enqueueMistakeRecord` 的 `reason: "invalid_tool_call"` 枚举值存在，但当前 `handleRuntimeEvent` 中**没有任何代码路径**实际以 `"invalid_tool_call"` 调用 `enqueueMistakeRecord`（只有 `tool_execution_failed` 和 `forceAtLimit` 路径）

这意味着 Cline 的 invalidToolCalls 是**纯观察性 metadata**，供外部消费者（如 UI、日志、遥测）使用，LLM 下一轮**看不到**自己产生了 invalid tool call——因为对话历史中只有 assistant 消息（不含 invalid tool calls 的 tool-call part，因为 `continue` 跳过了 `content.push`），没有对应的 tool-result 消息。

**Charles 设计**（`runtime.py` L654, L681-689, L722-724, L2373-2420）：

Charles 在主循环中主动提取并生成错误反馈：

```python
# L654: 提取 invalid_tool_calls
invalid_tool_calls = self._extract_invalid_tool_calls(message)

# L681-689: 为每个 invalid call 生成 ToolResultPart(is_error=True) 并立即追加
invalid_tool_messages: list[AgentMessage] = []
for itc in invalid_tool_calls:
    invalid_tool_messages.append(
        self._build_invalid_tool_result_message(itc)
    )
for invalid_msg in invalid_tool_messages:
    self._state.messages.append(invalid_msg)
    await self._emit(make_message_added(self.snapshot(), invalid_msg))

# L720-724: 执行有效工具后，把 invalid_tool_messages 再次追加到 tool_messages
tool_messages = await self._execute_tool_calls(tool_calls)
for invalid_msg in invalid_tool_messages:
    tool_messages.append(invalid_msg)

# L731-733: 把 tool_messages 追加到 state.messages 并 emit（含 invalid_tool_messages）
for tool_message in tool_messages:
    self._state.messages.append(tool_message)
    await self._emit(make_message_added(self.snapshot(), tool_message))
```

`_build_invalid_tool_result_message` (L2393-2420) 生成中文错误消息：

```python
reason_text = {
    "missing_name": "工具调用缺少工具名，请使用正确的工具名称。",
    "missing_arguments": "工具调用缺少必要参数，请检查参数是否完整。",
    "invalid_arguments": "工具调用参数无法解析为合法 JSON，请检查参数格式。",
}.get(invalid.reason, f"工具调用无效: {invalid.reason}")
# ...附 raw_input_text / parse_error 详情
return create_message(MessageRole.TOOL, [
    ToolResultPart(
        tool_call_id=invalid.tool_call_id,
        tool_name=invalid.tool_name or "",
        output=output,
        is_error=True,
    )
])
```

**Bug：invalid_tool_messages 被双重追加 + 双重 emit**

- 第一次：L687-689 直接 `state.messages.append(invalid_msg)` + `emit message_added`
- 第二次：L722-724 `tool_messages.append(invalid_msg)` → L731-733 `state.messages.append(tool_message)` + `emit message_added`

后果：每个 invalid tool call 在 `state.messages` 中出现 2 次，前端 UI 收到 2 次 `message_added` 事件，对话历史中 LLM 下一轮看到 2 份相同错误反馈。这会污染上下文且让 LLM 困惑。

**Cline 不生成反馈的设计意图推测**：Cline 把 invalidToolCalls 视为"模型不应产生"的异常情况，写入 metadata 仅供观察；若 LLM 真的产生 invalid tool call，Cline 主循环 L653-656 的 `toolCalls.length === 0` 分支会触发（因为 invalid 的不进入 `content`），进入 completion reminder 或 finishRun 路径，不专门反馈错误。

**Charles 的增强价值**：Charles 主动反馈让 LLM 有机会自我纠正（如修复 JSON 格式错误），减少后续 iteration 重复犯错。但需修复双重追加 bug。

### 差距 2：ToolCallPart.metadata 写入策略不同（对应对比项 2.7.2）

**Cline 设计**（`agent-runtime.ts` L1040-1051）：

```typescript
content.push({
    type: "tool-call",
    toolCallId: assembly.toolCallId,
    toolName: assembly.toolName,
    input: parsed.input,
    metadata: parsed.parseError
        ? mergeToolMetadata(assembly.metadata, {
                inputParseError: parsed.parseError,
                rawInputText: assembly.inputText,
            })
        : assembly.metadata,
});
```

注意：这段 `content.push` 在 `if (parsed.reason) { invalidToolCalls.push(...); continue; }` **之后**，仅当 `parsed.reason` 为空时执行。而 `parsed.parseError` 与 `parsed.reason` 同时设置（`parseToolInput` L1723-1728 仅在 `parsed.reason = "invalid_arguments"` 时设 `parseError`）。所以 `parsed.parseError` 非空 ⟺ `parsed.reason` 非空 ⟺ 已 `continue` 跳过此处。

**结论**：Cline 的 `parsed.parseError ? ... : assembly.metadata` 三元表达式的 truthy 分支是**死代码**，永远不会执行。ToolCallPart.metadata 实际上只包含 `assembly.metadata`（provider 流式累积的元数据），**永远不会**包含 `inputParseError`/`rawInputText`。

**Charles 设计**（`runtime.py` L1073-1084）：

```python
content.append(ToolCallPart(
    tool_call_id=assembly.tool_call_id,
    tool_name=assembly.tool_name,
    input=parsed.input if isinstance(parsed.input, dict) else {},
    metadata={
        **({"raw_input_text": assembly.input_text} if assembly.input_text else {}),
        **assembly.metadata,
    },
))
```

Charles **无条件**把 `raw_input_text` 写入每个 ToolCallPart.metadata（只要有 input_text），与 `assembly.metadata` 合并。这偏离了 Cline 的精确语义：

- Cline：ToolCallPart.metadata 仅含 provider 元数据
- Charles：ToolCallPart.metadata 含 `raw_input_text` + provider 元数据

**影响**：Charles 的 ToolCallPart.metadata 多了 `raw_input_text` 字段，对调试有利（能看到 LLM 原始输入），但若下游消费者不期望此字段可能产生兼容性问题。另外字段名 `raw_input_text`（snake_case）与 Cline 的 `rawInputText`（camelCase）不同，跨语言序列化时需注意。

### 差距 3：schema 校验调用时机与错误格式不同（对应对比项 2.7.5 / 2.7.6）

**Cline 设计**：

- **调用时机**：每个 tool 在自己的 `execute()` 内部调用 `validateWithZod(Schema, input)`，如 `definitions.ts` L263（list_files）、L360（search_codebase）、L532（fetch_web_content）、L622（apply_patch）、L676（edit_file）、L741（skills）、L791（ask_question）、L819（submit）。**runtime 层不调用**。
- **错误格式**：`zod.ts` L13-18 `validateWithZod` 内部 `schema.safeParse(input)` 失败时 `throw new Error(z.prettifyError(result.error))`，抛出单一字符串。`executePreparedTool` 的 catch 块（L1509-1515）捕获后转为 `{error: error.message}` + `isError:true`。
- **未校验的工具**：若某工具的 `execute()` 未调用 `validateWithZod`，则该工具无 schema 校验（如自定义工具）。

**Charles 设计**：

- **调用时机**：`tools/base.py` L117 `BaseTool.execute()` 入口统一调用 `self._validate_input(input)`，所有继承 `BaseTool` 的工具自动获得 schema 校验。**runtime 层不调用**（runtime 调 `tool.execute()`，由 `BaseTool.execute()` 内部触发校验）。
- **错误格式**：`_validate_input` 返回结构化错误列表 `[{field, message, validator, expected?, got?}]`，`BaseTool.execute()` L118-127 检测到错误时返回 `{error: "参数 schema 校验失败", tool, validation_errors: [...], received_input: input}` + `is_error=True`。
- **字段路径**：`_validate_input` L248-258 通过 `error.absolute_path` 构建 `commands[0].path` 格式的字段路径，便于 LLM 定位错误。
- **所有工具强制校验**：基类统一处理，无遗漏风险。

**影响**：

- Charles 的结构化错误（含字段路径、期望值、实际值、完整输入）对 LLM 自我纠正更友好，减少因参数错误导致的重复失败循环。
- Charles 的基类强制校验避免了 Cline 中"工具自己漏校验"的风险。
- Cline 的 Zod 校验是 TypeScript 类型安全的延伸（schema 即类型），Charles 的 jsonschema 校验是运行时反射（schema 即数据），两者哲学不同但功能等价。

### 差距 4：metadata 字段命名风格不一致（对应对比项 2.7.2 / 2.7.4）

**Cline 字段命名**（camelCase，遵循 TypeScript 惯例）：
- `message.metadata.invalidToolCalls`
- 条目字段：`toolCallId` / `toolName` / `input` / `reason`
- ToolCallPart.metadata：`inputParseError` / `rawInputText`（死代码，实际不写入）
- `assembly.metadata` 由 provider 流式累积

**Charles 字段命名**（snake_case，遵循 Python 惯例）：
- `message.metadata["invalid_tool_calls"]`
- 条目字段：`tool_call_id` / `tool_name` / `input` / `reason`
- ToolCallPart.metadata：`raw_input_text`（无条件写入）
- `assembly.metadata` 由 provider 流式累积

**影响**：跨语言序列化（如 Charles 通过 SSE 推送到前端）时需注意字段名转换。若前端期望 camelCase，Charles 需在序列化层转换；若前后端均 Python，则 snake_case 一致。

## 4. nanobot 残留检查

### 检查范围

在 `agent/` 目录下执行 `grep -ri "nanobot"` 搜索，共发现 55 行 nanobot 残留。与 P2.7（invalidToolCalls + normalize_input_for_schema）**直接相关**的文件中：

| 文件 | 与 P2.7 关系 | nanobot 残留数 | 残留类型 |
|------|-------------|---------------|---------|
| `agent/runtime.py` | 直接相关（_extract_invalid_tool_calls / _build_invalid_tool_result_message / _parse_tool_input / _normalize_input_for_schema / _parse_json_string_for_schema / _schema_accepts_kind） | 0 | 无 |
| `agent/tools/base.py` | 直接相关（_validate_input / execute schema 校验入口） | 0 | 无 |

### 注释残留分类

P2.7 直接相关文件中**无 nanobot 注释残留**。`runtime.py` 全文 grep `nanobot` 返回 0 行；`base.py` 的 `_validate_input` 注释明确标注"对标 Cline validateWithZod"（L213），无 nanobot 引用。

P2.1 报告中提到的 55 行 nanobot 残留均位于 P2.7 不涉及的模块：
- `agent/providers/qwen.py`（7 行，类型 A 实现来源标注）
- `agent/tools/exec_tool.py`（3 行，类型 A）
- `agent/tools/file_tools.py`（多处，类型 A）
- `agent/tools/web_tool.py`（多处，类型 A）
- `agent/skills/`（多处，类型 A）
- `agent/session.py` / `agent/server.py` / `agent/context.py`（各 1-3 行，类型 A）

这些文件与 invalidToolCalls 检测、normalize_input_for_schema、schema 校验均无关。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。所有 invalidToolCalls / normalize / schema 校验相关代码均基于 Cline 对标设计：

- `_InvalidToolCall` dataclass（runtime.py L177-186）对标 Cline `InvalidToolCall` interface（agent-runtime.ts L148-153）
- `_ParsedToolInput` dataclass（runtime.py L190-195）对标 Cline `parseToolInput` 返回值类型
- `_parse_tool_input` 方法对标 Cline `parseToolInput` 函数（agent-runtime.ts L1698-1729）
- `_parse_tool_arguments` 方法对标 Cline `parseToolArguments` 函数（L1744-1773）
- `_build_invalid_tool_input` 方法对标 Cline `buildInvalidToolInput` 函数（L1731-1742）
- `_normalize_input_for_schema` 方法对标 Cline `normalizeJsonLikeStringsForSchema` 函数（json.ts L158-200）
- `_parse_json_string_for_schema` 方法对标 Cline `parseJsonStringForSchema` 函数（json.ts L126-156）
- `_schema_accepts_kind` 方法对标 Cline `schemaAcceptsKind` 函数（json.ts L102-124）
- `_validate_input` 方法对标 Cline `validateWithZod`（zod.ts L13-18）
- Charles 独有增强：`_extract_invalid_tool_calls` + `_build_invalid_tool_result_message`（Cline 无对应实现）

未发现任何从 nanobot 直接移植的 invalidToolCalls / normalize / schema 校验代码逻辑。

### 残留风险评估

| 残留类型 | 文件数（与 P2.7 相关） | 风险等级 | 处理建议 |
|---------|----------------------|---------|---------|
| 注释残留 | 0 | 无 | 无需处理 |
| 实现逻辑残留 | 0 | 无 | 无需处理 |

## 5. 修复建议

### P0（高优先级，影响对话历史正确性）

**建议 1：修复 invalid_tool_messages 双重追加 bug（对应差距 1）**

Charles `runtime.py` L681-733 中 invalid_tool_messages 被双重追加到 `state.messages` 并双重 emit。建议选择以下两种方案之一：

**方案 A（推荐）：移除 L687-689 的立即追加，统一在 L731-733 追加**

```python
# L681-686: 仅生成，不立即追加
invalid_tool_messages: list[AgentMessage] = []
for itc in invalid_tool_calls:
    invalid_tool_messages.append(
        self._build_invalid_tool_result_message(itc)
    )
# 移除原 L687-689 的立即追加 + emit

# L720-724: 保留，把 invalid_tool_messages 加入 tool_messages
tool_messages = await self._execute_tool_calls(tool_calls)
for invalid_msg in invalid_tool_messages:
    tool_messages.append(invalid_msg)

# L731-733: 统一追加 + emit（含 invalid_tool_messages）
for tool_message in tool_messages:
    self._state.messages.append(tool_message)
    await self._emit(make_message_added(self.snapshot(), tool_message))
```

**方案 B：移除 L722-724 的追加到 tool_messages，保留 L687-689 的立即追加**

```python
# L681-689: 保留立即追加 + emit
# L720-724: 移除 invalid_tool_messages 追加到 tool_messages
# L727: _check_repeated_tool_failures 需调整参数（仅传 tool_messages，不含 invalid）
# L731-733: 仅追加有效 tool_messages
```

方案 A 更简单，且让 `_check_repeated_tool_failures`（L727）能统一处理 invalid_tool_messages 的错误（当前 L727 已包含 invalid_tool_messages，方案 A 保持此行为）。

**收益**：消除对话历史中的重复消息，避免 LLM 困惑，避免前端 UI 重复渲染。

**改动范围**：`runtime.py` L681-733，删除 L687-689 的 3 行。

### P1（中优先级，改善 LLM 自我纠正能力）

无。Charles 主动生成 invalidToolCall 错误 result 消息的设计优于 Cline（Cline 不反馈），应保留此增强。修复 P0 bug 后即可。

### P2（低优先级，改善一致性）

**建议 2：统一 ToolCallPart.metadata 写入策略（对应差距 2）**

参考 Cline agent-runtime.ts L1040-1051 的精确语义，决定 Charles 是否在 ToolCallPart.metadata 中写入 `raw_input_text`：

- **选项 A（对齐 Cline）**：移除 `runtime.py` L1080-1083 中无条件写入 `raw_input_text` 的逻辑，仅保留 `assembly.metadata`。但 Charles 当前在 invalid_tool_calls 条目中已含 `raw_input_text`（通过 `_build_invalid_tool_input`），调试信息不丢失。
- **选项 B（保留 Charles 增强）**：保留 `raw_input_text` 写入，但在文档中明确这是 Charles 独有增强，偏离 Cline 语义。

**收益**：与 Cline 语义对齐，减少跨实现的行为差异。

**注意**：此改动影响 ToolCallPart.metadata 的所有下游消费者，需评估影响范围。

### P3（可选，命名风格统一）

**建议 3：评估 metadata 字段命名风格统一（对应差距 4）**

若 Charles 前端期望 camelCase，可在 SSE 序列化层统一转换 `snake_case → camelCase`；若前后端均 Python，则保持 snake_case。此为风格选择，非 bug。

## 6. 验证方法建议

### 验证 invalidToolCalls 检测条件（对应对比项 2.7.1）

构造以下 tool_call 输入，对比两边处理：

1. **空 name**：tool_call 无 tool_name 字段 → 期望两边均产生 `reason: "missing_name"` 的 invalidToolCall
2. **空 arguments**：tool_call 有 name 但 input_text 为空 → 期望两边均不产生 invalidToolCall（parseToolInput 返回 input={}, 无 reason）
3. **畸形 JSON**：tool_call 有 name 但 input_text = `{invalid` → 期望两边均产生 `reason: "invalid_arguments"` 的 invalidToolCall，parseError 含 "Tool call {name} emitted invalid JSON arguments: ..."
4. **合法 JSON 但非 object/array**：input_text = `"hello"` → 期望两边均产生 `reason: "invalid_arguments"`，错误消息含 "must be encoded as a JSON object or array"
5. **嵌套 JSON 字符串**：input_text = `{"key": "{\"nested\": true}"}` 且 schema 期望 object → 期望两边均通过 `normalizeJsonLikeStringsForSchema` 解析嵌套字符串

### 验证下一轮错误 result 生成（对应对比项 2.7.3）

构造场景 2（畸形 JSON），让 LLM 产生 invalid tool call，检查：

- **Cline**：assistant 消息 metadata 含 invalidToolCalls，但对话历史中**无**对应的 tool-result 消息；LLM 下一轮看不到错误反馈
- **Charles**（修复 P0 bug 后）：assistant 消息 metadata 含 invalid_tool_calls，对话历史中**有**对应的 ToolResultPart(is_error=True) 消息；LLM 下一轮看到中文错误反馈（"工具调用参数无法解析为合法 JSON..."）

### 验证 schema 校验错误格式（对应对比项 2.7.6）

构造场景：调用 `read_files` 工具但 `files` 字段缺失（required 字段）：

- **Cline**：`validateWithZod` 抛 `Error(z.prettifyError(...))`，tool-result 为 `{error: "<prettified string>"}` + `isError: true`
- **Charles**：`_validate_input` 返回 `[{field: "files", message: "'files' is a required property", validator: "required"}]`，tool-result 为 `{error: "参数 schema 校验失败", tool: "read_files", validation_errors: [...], received_input: {...}}` + `is_error: true`

### 验证 normalizeJsonLikeStringsForSchema 递归（对应对比项 2.7.4）

构造场景：工具 schema 期望 `{"type": "object", "properties": {"config": {"type": "object", "properties": {"debug": {"type": "boolean"}}}}}`，LLM 输入 `{"config": "{\"debug\": true}"}`（嵌套 JSON 字符串）：

- 期望两边均递归解析 `config` 字段为 `{"debug": true}`，最终输入为 `{"config": {"debug": true}}`

## 7. 参考文件

### Cline 源码
- `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L148-153（InvalidToolCall 接口）、L904（invalidToolCalls 数组初始化）、L1022-1058（检测与写入）、L1040-1051（ToolCallPart.metadata 写入）、L1291-1310（executeToolCalls）、L1698-1742（parseToolInput / buildInvalidToolInput）、L1744-1773（parseToolArguments）
- `third_party/cline/sdk/packages/shared/src/agents/types.ts` L1057-1063（invalidToolCalls 类型定义）
- `third_party/cline/sdk/packages/shared/src/parse/json.ts` L102-200（normalizeJsonLikeStringsForSchema / parseJsonStringForSchema / schemaAcceptsKind）
- `third_party/cline/sdk/packages/shared/src/parse/zod.ts` L13-18（validateWithZod）
- `third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts` L263/L360/L532/L622/L676/L741/L791/L819（各工具 validateWithZod 调用）
- `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L1062-1191（handleRuntimeEvent，确认无 invalidToolCalls 读取）、L1287-1310（enqueueMistakeRecord，确认无 invalid_tool_call 路径触发）

### Charles 源码
- `agent/runtime.py` L177-195（_InvalidToolCall / _ParsedToolInput dataclass）、L654（_extract_invalid_tool_calls 调用）、L681-733（invalid_tool_messages 生成与追加，含双重追加 bug）、L1042-1097（组装阶段检测与写入 metadata）、L1350-1423（_check_repeated_tool_failures）、L1446-1466（_prepare_tool_execution 中 normalize 调用）、L2373-2420（_extract_invalid_tool_calls / _build_invalid_tool_result_message）、L2422-2463（_parse_tool_input）、L2465-2497（_parse_tool_arguments）、L2499-2510（_build_invalid_tool_input）、L2512-2553（_normalize_input_for_schema）、L2555-2581（_parse_json_string_for_schema）、L2583-2605（_schema_accepts_kind）
- `agent/tools/base.py` L105-138（execute 入口统一校验）、L212-275（_validate_input 结构化错误）

### 计划文件
- `CASE-AI量化系统/AGENT_COMPARISON_PLAN_V2.md` L465-487（P2.7 章节定义）
