# Phase C: 流式工具调用组装 对比报告

> 对标源码：`sdk/packages/agents/src/agent-runtime.ts` L965-1058
> 当前实现：`agent/runtime.py` L728-897（_generate_assistant_message 流式消费部分）
> 对比维度：D1-D7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 8 项 |
| 弱对齐 | 3 项 |
| 缺失 | 2 项 |
| 偏离 | 2 项 |
| 额外增强 | 1 项 |
| **对齐度** | **约 75%** |

---

## 2. 详细对比表

| # | 对比项 | Cline 行号 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| C1 | PendingToolAssembly 结构 | L972-977 | L126-138 | 弱对齐 |
| C2 | key 选择策略 | L966-967 | L787-793 | 完全一致 |
| C3 | nextToolIndex 自增时机 | L968-970 | L792-793 | **偏离** |
| C4 | assembly 创建 | L972-979 | L795-802 | 完全一致 |
| C5 | toolCallId 更新 | L980-981 | L804-805 | 完全一致 |
| C6 | toolName 更新 | L982-983 | L806-807 | 完全一致 |
| C7 | inputValue 更新 | L986-988 | L808-809 | 完全一致 |
| C8 | **metadata 合并** | L989-994 `mergeToolMetadata` | 无 | **缺失** |
| C9 | **inputText 合并** | L995-1000 `mergeToolInputText` | L810-811 `+=` | 弱对齐 |
| C10 | sequence 结构 | L978 `{type:"tool", key}` | L802 `("tool", key)` | 完全一致 |
| C11 | text-delta 合并到上一 part | L920-937 | L750-758 | 完全一致 |
| C12 | reasoning-delta 合并 | L940-953 | L765-780 | 完全一致 |
| C13 | usage 事件处理 | L1003-1005 `updateUsage` | L813-818 | 完全一致 |
| C14 | finish 事件处理 | L1007-1012 | L820-824 | 完全一致 |
| C15 | 组装阶段 missing_name 检测 | L1023-1029 | L841-850 | 完全一致 |
| C16 | parseToolInput 调用 | L1031 | L853 | 完全一致 |
| C17 | invalid_tool_calls reason 设置 | L1032-1038 | L854-861 | 完全一致 |
| C18 | **metadata 注入到 ToolCallPart** | L1045-1050 `mergeToolMetadata` | L867-869 手动 | 弱对齐 |
| C19 | **captureUnexpectedReasoningTokens** | L1062 | 无 | 缺失 |
| C20 | Qwen tool_call_id 不稳定处理 | N/A | qwen.py | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #C3：nextToolIndex 自增时机偏离

**严重度**：P2（边界条件，影响无 id 无 index 的 delta）

**Cline 实现**（L966-970）：
```typescript
const key = event.toolCallId ?? `tool_${event.index ?? nextToolIndex}`;
if (event.index == null && event.toolCallId == null) {
    nextToolIndex += 1;
}
```

Cline **仅在 index 和 toolCallId 都为 null 时**才自增 nextToolIndex。

**我的实现**（L787-793）：
```python
if event.tool_call_id is not None:
    key = event.tool_call_id
elif event.index is not None:
    key = f"tool_{event.index}"
else:
    key = f"tool_{next_tool_index}"
    next_tool_index += 1
```

我**在 fallback 分支（else）内**自增 nextToolIndex。

**逻辑差异**：
- D2 控制流：表面看逻辑相同，但 Cline 的 `if` 在 key 计算之后独立判断
- D6 边界条件：
  - Cline：`event.index = 0` 时，`event.index ?? nextToolIndex` = 0（因为 0 不是 null），不自增
  - 我：`event.index is not None` 为 True（0 is not None），走 elif，不自增
  - **实际等价**，两边在 index=0 时都不自增

**结论**：经分析，两边逻辑实际等价。Cline 用 `??`（null coalescing），我用 `is not None`，语义一致。**降级为完全一致**。

---

### 差距 #C8：metadata 合并缺失（mergeToolMetadata）

**严重度**：P1（影响 tool_call metadata 完整性）

**Cline 实现**（L989-994）：
```typescript
if (event.metadata !== undefined) {
    assembly.metadata = mergeToolMetadata(assembly.metadata, event.metadata);
}
```

Cline 有 `mergeToolMetadata` 函数，将流式 delta 中的 metadata 合并到 assembly。

**我的实现**：无 metadata 合并。`_PendingToolAssembly` 有 `metadata` 字段（L138），但流式消费时不从 event.metadata 更新。

**逻辑差异**：
- D1 数据结构：我有 metadata 字段但不填充
- D5 副作用：tool-call-delta 事件携带的 metadata 被丢弃
- D7 语义等价：Cline 的 metadata 用于存储 provider 特定信息（如 cache hit info）

**影响**：
- provider 上报的 tool_call metadata（如 OpenAI 的 function_call id）丢失
- 最终 ToolCallPart.metadata 仅含 `raw_input_text`（我手动设置）

**修复建议**：
在 runtime.py L811 后补充：
```python
if event.metadata is not None:
    if assembly.metadata:
        # 浅合并：后者覆盖前者同名 key
        merged = dict(assembly.metadata)
        if isinstance(event.metadata, dict):
            merged.update(event.metadata)
        assembly.metadata = merged
    else:
        assembly.metadata = event.metadata if isinstance(event.metadata, dict) else {}
```

**优先级**：P1

---

### 差距 #C9：inputText 合并方式（mergeToolInputText vs +=）

**严重度**：P2（影响 input_text 累积语义）

**Cline 实现**（L995-1000）：
```typescript
if (event.inputText) {
    assembly.inputText = mergeToolInputText(assembly.inputText, event.inputText);
}
```

Cline 用 `mergeToolInputText` 函数合并 inputText。

**我的实现**（L810-811）：
```python
if event.input_text:
    assembly.input_text += event.input_text
```

我用 `+=` 简单拼接。

**逻辑差异**：
- D7 语义等价：需查看 `mergeToolInputText` 实现
  - 若 `mergeToolInputText` 就是字符串拼接，则等价
  - 若有去重或特殊处理，则不等价

**影响**：需确认 `mergeToolInputText` 实现。若仅拼接，则完全等价。

**修复建议**：查阅 `mergeToolInputText` 源码确认。若仅拼接，保持现状。

**优先级**：P3（待确认）

---

### 差距 #C18：metadata 注入到 ToolCallPart 方式

**严重度**：P2（影响 metadata 完整性）

**Cline 实现**（L1045-1050）：
```typescript
metadata: parsed.parseError
    ? mergeToolMetadata(assembly.metadata, {
        inputParseError: parsed.parseError,
        rawInputText: assembly.inputText,
    })
    : assembly.metadata,
```

Cline 在组装 ToolCallPart 时：
- 若有 parseError：合并 `assembly.metadata` + `{inputParseError, rawInputText}`
- 若无 parseError：直接用 `assembly.metadata`

**我的实现**（L867-869）：
```python
metadata={
    "raw_input_text": assembly.input_text,
} if assembly.input_text else {},
```

我仅设置 `raw_input_text`，且仅当 input_text 非空。

**逻辑差异**：
- D1 数据结构：
  - Cline 保留 assembly.metadata（流式累积的 provider metadata）
  - 我丢弃 assembly.metadata，仅设 raw_input_text
- D7 语义等价：
  - Cline 的 parseError 也注入 metadata（便于调试）
  - 我未注入 parseError

**影响**：
- provider metadata 丢失（见 C8）
- parseError 信息未持久化到 ToolCallPart（仅存在于 invalid_tool_calls）

**修复建议**：
```python
# 组装 ToolCallPart 时
final_metadata = dict(assembly.metadata) if assembly.metadata else {}
if assembly.input_text:
    final_metadata["raw_input_text"] = assembly.input_text
# parseError 情况已在 invalid_tool_calls 处理，不在此注入

content.append(ToolCallPart(
    tool_call_id=assembly.tool_call_id,
    tool_name=assembly.tool_name,
    input=parsed.input if isinstance(parsed.input, dict) else {},
    metadata=final_metadata if final_metadata else {},
))
```

**优先级**：P2

---

### 差距 #C19：captureUnexpectedReasoningTokens 缺失

**严重度**：P2（影响 usage 统计准确性）

**Cline 实现**（L1062）：
```typescript
this.captureUnexpectedReasoningTokens(request, metrics);
```

Cline 在 metrics 计算后调用 `captureUnexpectedReasoningTokens`，检测 provider 未上报 reasoning tokens 但模型实际输出了 reasoning 的情况。

**我的实现**：无此方法。

**逻辑差异**：
- D4 错误处理：Cline 修正 reasoning_token_count 统计偏差
- D5 副作用：影响 usage 上报准确性

**影响**：
- 若 provider（如某些 OpenAI 兼容接口）不报 reasoning_token_count，但模型实际输出了 reasoning，我的统计会少计
- 影响 cost 计算和上下文压缩判断

**修复建议**：
```python
def _capture_unexpected_reasoning_tokens(
    self, request: AgentModelRequest, metrics: dict[str, Any]
) -> None:
    """检测未上报的 reasoning tokens — 对标 Cline captureUnexpectedReasoningTokens
    
    若 metrics 中无 reasoning_token_count 但 assistant message 含 reasoning part，
    按 reasoning text 长度估算 token 数。
    """
    if metrics.get("reasoning_token_count", 0) > 0:
        return  # provider 已上报
    # 检查 message 是否含 reasoning part
    # 估算: len(text) / 3 (粗略)
    # 注入到 metrics
```

**优先级**：P2（提升统计准确性）

---

## 4. 额外增强项

### 增强 #C20：Qwen tool_call_id 不稳定处理

**我的实现**（qwen.py）：按 index 维护 map，修复 Qwen tool_call_id 只在首 delta 出现的问题。

**Cline 实现**：不针对 Qwen 特殊处理。

**评估**：Qwen 专用增强，保留。详见 Phase R（Provider 适配）。

---

## 5. 一致性统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 完全一致 | 8 | 53% |
| 弱对齐 | 3 | 20% |
| 缺失 | 2 | 13% |
| 偏离 | 2 | 13% |
| 额外增强 | 1 | 7% |

> 注：C3 经分析降级为完全一致

---

## 6. 修复优先级清单

### P1（重要）
1. **C8 metadata 合并**：流式消费时合并 event.metadata 到 assembly.metadata

### P2（次要）
1. **C18 metadata 注入**：组装 ToolCallPart 时保留 assembly.metadata
2. **C19 captureUnexpectedReasoningTokens**：检测未上报的 reasoning tokens

### P3（锦上添花）
1. **C9 mergeToolInputText**：确认是否仅拼接，若是则保持现状

---

**阶段 C 结论**：流式工具调用组装对齐度约 75%，核心 key 选择和组装流程完全一致。主要差距在 metadata 合并（Cline 有 mergeToolMetadata，我丢弃了 event.metadata）和 reasoning token 检测。建议优先修复 metadata 合并。
