# Phase D: 事件系统 对比报告

> 对标源码：`sdk/packages/shared/src/agent.ts` L466-550（AgentRuntimeEvent 14 变体）+ `agent-runtime.ts` emit 点
> 当前实现：`agent/events.py`
> 对比维度：D1-D7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 8 项 |
| 弱对齐 | 3 项 |
| 缺失 | 3 项 |
| 语义不等价 | 2 项 |
| **对齐度** | **约 65%** |

---

## 2. 事件类型枚举对比

| # | Cline 事件类型 | 我的事件类型 | 一致性 |
|---|---------------|-------------|--------|
| D1 | `run-started` | `RUN_STARTED` | 完全一致 |
| D2 | `message-added` | `MESSAGE_ADDED` | 完全一致 |
| D3 | `turn-started` | `TURN_STARTED` | 完全一致 |
| D4 | `assistant-text-delta` | `ASSISTANT_TEXT_DELTA` | 完全一致 |
| D5 | `assistant-reasoning-delta` | `ASSISTANT_REASONING_DELTA` | 完全一致 |
| D6 | **`assistant-message`** | **缺失** | 缺失 |
| D7 | `tool-started` | `TOOL_EXECUTION_STARTED` | 弱对齐（命名不同） |
| D8 | **`tool-updated`** | **缺失** | 缺失 |
| D9 | `tool-finished` | `TOOL_EXECUTION_FINISHED` | 弱对齐（命名不同） |
| D10 | `usage-updated` | `USAGE_UPDATED` | 完全一致 |
| D11 | `turn-finished` | `TURN_FINISHED` | 完全一致 |
| D12 | `status-notice` | `STATUS_NOTICE` | 完全一致 |
| D13 | `run-finished` | `RUN_FINISHED` | 完全一致 |
| D14 | `run-failed` | `RUN_FAILED` | 完全一致 |

**Cline 14 种 vs 我 12 种**，缺失 `assistant-message` 和 `tool-updated`。

---

## 3. 详细对比表

| # | 对比项 | Cline | 我的位置 | 一致性 |
|---|--------|-------|---------|--------|
| D15 | AgentEvent 数据结构 | discriminated union（14 变体） | 单一 dataclass | 语义不等价 |
| D16 | snapshot 字段 | 每个变体都有 | 始终携带 | 完全一致 |
| D17 | subscribe 返回 unsubscribe | L399 `on()` 返回 unsubscribe | L132-150 | 完全一致 |
| D18 | emit 同步/异步 | `async emit()` | `async emit()` | 完全一致 |
| D19 | listener 异常隔离 | try/catch 吞错 | L168-175 try/except | 完全一致 |
| D20 | accumulatedText 语义 | L486 累积全文 | L76 `accumulated_text` | 完全一致 |
| D21 | assistant-message 字段 | L497-503 含 finishReason | 缺失 | 缺失 |
| D22 | tool-updated 字段 | L511-516 含 update | 缺失 | 缺失 |
| D23 | tool-started 命名 | `tool-started` | `tool-execution-started` | 弱对齐 |
| D24 | tool-finished 命名 | `tool-finished` | `tool-execution-finished` | 弱对齐 |
| D25 | status-notice metadata | L537-540 `metadata?` | L80 `metadata` | 完全一致 |
| D26 | run-failed error 类型 | L549 `error: Error` | L91 `error: Exception` | 弱对齐 |
| D27 | turn-finished toolCallCount | L533 `toolCallCount` | L87 `tool_call_count` | 完全一致 |
| D28 | listener 遍历拷贝 | 无（Cline 用 Set 快照） | L166 `list(self._listeners)` | 完全一致 |

---

## 4. 关键差距详细分析

### 差距 #D6/D21：assistant-message 事件缺失

**严重度**：P2（影响前端事件流完整性）

**Cline 实现**（agent.ts L497-503）：
```typescript
| {
    type: "assistant-message";
    snapshot: AgentRuntimeStateSnapshot;
    iteration: number;
    message: AgentMessage;
    finishReason: AgentModelFinishReason;
}
```

Cline 在 `message-added` 之后 emit `assistant-message`，携带 `finishReason`。

**我的实现**：无此事件。

**逻辑差异**：
- D5 副作用：
  - Cline：`message-added`（通用）+ `assistant-message`（专用，含 finishReason）
  - 我：仅 `message-added`（通用，无 finishReason）
- D7 语义等价：
  - 前端若需知道"这轮 assistant 消息的完成原因"（stop/tool-calls/max-tokens），需从 `assistant-message` 获取
  - 我的方式前端无法获取 finishReason（除非从 tool_call_count 推断）

**影响**：
- 前端无法展示"模型因 max-tokens 截断"等状态
- 调试时无法区分"正常结束"和"max-tokens 截断"

**修复建议**：
1. events.py 新增 `ASSISTANT_MESSAGE = "assistant-message"` 常量
2. runtime.py L550 后 emit：
```python
await self._emit(AgentEvent(
    type=ASSISTANT_MESSAGE,
    snapshot=self.snapshot(),
    iteration=self._state.iteration,
    message=message,
    finish_reason=finish_reason,
))
```
3. 前端 ai-chat.js 监听 `assistant-message` 事件

**优先级**：P2

---

### 差距 #D8/D22：tool-updated 事件缺失

**严重度**：P2（影响工具进度更新）

**Cline 实现**（agent.ts L511-516）：
```typescript
| {
    type: "tool-updated";
    snapshot: AgentRuntimeStateSnapshot;
    iteration: number;
    toolCall: AgentToolCallPart;
    update: unknown;
}
```

Cline 有 `tool-updated` 事件，工具执行过程中可 emit 进度更新。

**我的实现**：无 `tool-updated` 事件。用 `STATUS_NOTICE` + `emit_update` 回调替代（runtime.py L1686-1717）。

**逻辑差异**：
- D2 控制流：
  - Cline：工具通过 `AgentToolContext.emitUpdate` → `tool-updated` 事件
  - 我：工具通过 `emit_update` 回调 → `STATUS_NOTICE` 事件（复用）
- D7 语义等价：
  - Cline 的 `tool-updated` 携带 `toolCall`（标识哪个工具）+ `update`（进度数据）
  - 我的 `STATUS_NOTICE` 携带 `notice`（工具名）+ `metadata`（update 数据）
  - 功能等价，但事件类型不同

**影响**：
- 前端需监听 `STATUS_NOTICE` 并从 metadata 判断是否是工具更新
- 不如 Cline 的专用 `tool-updated` 事件清晰
- 当前 TodoWrite / Plan Mode 的 update 通过此机制工作正常

**修复建议**：
方案 A（对齐 Cline）：新增 `TOOL_UPDATED` 事件类型，`emit_update` 回调发射 `tool-updated` 而非 `status-notice`
方案 B（保持现状）：`STATUS_NOTICE` 复用，文档说明

建议方案 A，提升事件语义清晰度：
```python
# events.py
TOOL_UPDATED = "tool-updated"

# runtime.py _make_emit_update
def emit_update(update: Any) -> None:
    event = AgentEvent(
        type=TOOL_UPDATED,
        snapshot=self.snapshot(),
        iteration=self._state.iteration,
        tool_name=tool_name,
        metadata=update if isinstance(update, dict) else {"value": update},
    )
    asyncio.create_task(self._emit(event))
```

**优先级**：P2

---

### 差距 #D15：AgentEvent 单一 dataclass vs discriminated union

**严重度**：P3（影响类型安全）

**Cline 实现**：14 个独立 interface 组成 discriminated union，编译期类型安全。

**我的实现**：单一 `AgentEvent` dataclass 含所有字段（events.py L61-105），多数字段为 None。

**逻辑差异**：
- D1 数据结构：Cline 每个事件只含相关字段；我所有字段并存
- D4 错误处理：Cline 编译期防止访问错误字段；我运行时可能误访问 None
- D6 边界条件：易忘记设置某字段

**影响**：
- 类型安全弱，但功能等价
- Python 无原生 discriminated union，改造代价大

**修复建议**：保持现状，加强测试覆盖。

**优先级**：P3

---

### 差距 #D23/D24：工具事件命名不一致

**严重度**：P3（影响前端兼容性）

| Cline | 我 |
|-------|---|
| `tool-started` | `tool-execution-started` |
| `tool-finished` | `tool-execution-finished` |

**逻辑差异**：命名风格不同，功能完全一致。

**影响**：
- 前端需用我的命名监听
- 与 Cline 文档/生态不一致

**修复建议**：
- 方案 A：重命名为 Cline 风格（需改前端）
- 方案 B：保持现状（文档说明）

建议方案 B（重命名影响大，收益小）。

**优先级**：P3

---

## 5. EventEmitter 行为对比

### emit 异常隔离

**Cline**：listener 异常被 try/catch 吞掉，不影响其他 listener。
**我**（L168-175）：
```python
try:
    result = listener(event)
    if inspect.isawaitable(result):
        await result
except Exception:
    import traceback
    traceback.print_exc()
```
**完全一致**。

### listener 遍历安全

**Cline**：用 Set 快照遍历。
**我**（L166）：`listeners = list(self._listeners)` 拷贝列表。
**完全一致**。

### 同步/异步 listener 支持

**Cline**：支持同步和异步 listener（`Promise.resolve(result)`）。
**我**（L169-171）：`inspect.isawaitable(result)` 判断后 await。
**完全一致**。

---

## 6. 一致性统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 完全一致 | 8 | 62% |
| 弱对齐 | 3 | 23% |
| 缺失 | 3 | 23% |
| 语义不等价 | 2 | 15% |

---

## 7. 修复优先级清单

### P2（次要，建议修复）
1. **D6 assistant-message 事件**：新增事件类型，携带 finishReason
2. **D8 tool-updated 事件**：新增事件类型，替代 STATUS_NOTICE 复用

### P3（锦上添花）
1. **D15 discriminated union**：保持现状，加强测试
2. **D23/D24 命名**：保持现状，文档说明
3. **D26 error 类型**：Python Exception vs JS Error，语义等价

---

**阶段 D 结论**：事件系统对齐度约 65%，12/14 事件类型已覆盖。主要差距在 `assistant-message`（携带 finishReason）和 `tool-updated`（工具进度）两个事件缺失。EventEmitter 行为（subscribe/emit/异常隔离）完全一致。建议优先补齐 `assistant-message` 事件。
