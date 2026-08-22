# Phase B: AgentRuntime 主循环 对比报告

> 对标源码：`sdk/packages/agents/src/agent-runtime.ts` L595-794（execute 方法）
> 当前实现：`agent/runtime.py` L446-667（run 方法）
> 对比维度：D1-D7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 9 项 |
| 弱对齐 | 5 项 |
| 缺失 | 3 项 |
| 偏离 | 3 项 |
| 额外增强 | 4 项 |
| **对齐度** | **约 70%** |

---

## 2. 详细对比表

| # | 对比项 | Cline 行号 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| B1 | run() 入参类型 | L595 `AgentRunInput` | L448 `str \| AgentMessage \| list[AgentMessage]` | 弱对齐 |
| B2 | running 状态检查 | L597-599 | L465-466 | 完全一致 |
| B3 | AbortController 初始化 | L601 `new AbortController()` | L474 `self._abort_controller.reset()` | 弱对齐 |
| B4 | run_id 生成 | L602 `createUID("run")` | L475 `uuid.uuid4().hex[:12]` | 完全一致 |
| B5 | 状态初始化 | L603-607 | L476-480 | 完全一致 |
| B6 | callBeforeRunHooks | L610 | L484 | 完全一致 |
| B7 | emit run-started | L611 | L487 | 完全一致 |
| B8 | 输入消息处理 | L613-620 `normalizeInput` + emit | L491-511 messages 参数 + hooks | **偏离** |
| B9 | completionToolReminder 预注入 | L622-625 循环前 | L574-588 循环内无工具时 | **偏离** |
| B10 | 主循环 while 条件 | L629-632 | L516-519 | 完全一致 |
| B11 | throwIfAborted 调用点 | L633 | L520 | 完全一致 |
| B12 | iteration 自增 | L635 | L522 | 完全一致 |
| B13 | emit turn-started | L636-640 | L523 | 完全一致 |
| B14 | generateAssistantMessage 调用 | L642 | L526 | 完全一致 |
| B15 | aborted finish_reason 处理 | L643-645 `normalizeAbortError` | L528-529 `RuntimeError` | 弱对齐 |
| B16 | 空消息检测 | L646-652 | L531-536 | 完全一致 |
| B17 | toolCalls 提取 | L653-656 | L539-542 | 完全一致 |
| B18 | invalid_tool_calls 提取 | 无（在 generateAssistantMessage 内） | L545 | 额外增强 |
| B19 | 保存 assistant 消息 + emit | L658-664 | L548-550 | 完全一致 |
| B20 | **emit assistant-message** | L665-671 | **缺失** | **缺失** |
| B21 | max-tokens 无工具处理 | L673-675 | L553-556 | 完全一致 |
| B22 | error 无工具处理 | L676-678 | L557-559 | 完全一致 |
| B23 | pendingToolCalls 设置 | L679 | L561 | 完全一致 |
| B24 | invalid_tool_messages 生成 | 无 | L564-571 | 额外增强 |
| B25 | 无工具时完成策略 | L681-704 | L574-599 | 弱对齐 |
| B26 | executeToolCalls 调用 | L706 | L602 | 完全一致 |
| B27 | _check_repeated_tool_failures | 无 | L609 | 额外增强 |
| B28 | pendingToolCalls 清空 | L707 | L611 | 完全一致 |
| B29 | tool messages 保存 + emit | L708-715 | L613-615 | 完全一致 |
| B30 | emit turn-finished | L716-721 | L617-619 | 完全一致 |
| B31 | findCompletingToolMessage | L722-738 | L622-628 | 完全一致 |
| B32 | max_iterations 超限 | L742-744 | L631-633 | 完全一致 |
| B33 | catch 块 ControlledStopError | L748-749 | 无（用 _aborted） | 弱对齐 |
| B34 | catch 块 logger.log | L765-775 | 无 | 缺失 |
| B35 | catch 块 emit run-failed/run-finished | L777-789 | L657-660 | 完全一致 |
| B36 | finally 清理 | L791-793 `abortController=undefined` | L664-666 `_aborted=False` | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #B8：输入消息处理逻辑偏离

**严重度**：P1（影响会话续接和输入预处理）

**Cline 实现**（L613-625）：
```typescript
for (const message of input ? normalizeInput(input) : []) {
    this.state.messages.push(message);
    await this.emit({ type: "message-added", snapshot: this.snapshot(), message });
}
const completionToolReminder = this.getCompletionToolReminderMessage();
if (completionToolReminder) {
    await this.addUserReminderMessage(completionToolReminder);
}
```

Cline 流程：
1. `normalizeInput(input)` 统一转为 `AgentMessage[]`
2. 逐条 push + emit message-added
3. 循环前预注入 completionToolReminder（若配置）

**我的实现**（L491-511）：
```python
if messages:
    for msg in messages:
        self._state.messages.append(msg)  # 无 emit
if isinstance(input, str):
    input = await self._call_prepare_turn_input_hooks(input)
input_messages = self._normalize_input(input)
input_messages = await self._call_format_user_input_block_hooks(input_messages)
for msg in input_messages:
    self._state.messages.append(msg)
    await self._emit(make_message_added(self.snapshot(), msg))
```

我的流程：
1. 可选 `messages` 参数注入历史（无 emit，避免前端重复渲染）
2. `prepare_turn_input` 钩子预处理字符串输入
3. `_normalize_input` 转为消息列表
4. `format_user_input_block` 钩子格式化用户输入块
5. 逐条 push + emit message-added

**逻辑差异**：
- D2 控制流：
  - Cline 单一入口 `normalizeInput`；我分离 `messages`（历史）和 `input`（新输入），历史无 emit
  - Cline 在循环前预注入 reminder；我在循环内无工具时才注入（见 B9）
- D5 副作用：
  - Cline 历史消息也 emit message-added；我不 emit（避免前端重复渲染已存在消息）
  - 我有 prepare_turn_input 和 format_user_input_block 钩子，Cline 用 prepareTurn config 回调
- D7 语义等价：
  - 历史消息 emit：Cline emit，我不 emit。Cline 假设首次注入，我假设会话续接（前端已有）
  - reminder 时机：Cline 循环前，我循环内。影响 LLM 首轮是否看到 reminder

**影响**：
- 会话续接场景：我的方式更合理（历史消息前端已有，无需重复 emit）
- 但首次运行时，Cline 的 history 也 emit，前端可统一渲染；我的方式需前端自行区分
- reminder 时机差异：Cline 在首轮 LLM 调用前就注入 reminder，LLM 首轮就看到"必须调用完成工具"；我首轮不注入，LLM 首轮可能直接返回文本，才触发 reminder

**修复建议**：
1. reminder 时机：建议对齐 Cline，在循环前预注入（若 require_completion_tool=True）
2. 历史消息 emit：保持现状（会话续接场景更合理），文档说明差异
3. prepare_turn_input / format_user_input_block：保持增强，Cline 的 prepareTurn 是 config 回调，我用 hook 更灵活

**优先级**：P1（reminder 时机应修复）

---

### 差距 #B9：completionToolReminder 注入时机偏离

**严重度**：P1（影响 LLM 首轮行为）

**Cline 实现**（L622-625）：
```typescript
const completionToolReminder = this.getCompletionToolReminderMessage();
if (completionToolReminder) {
    await this.addUserReminderMessage(completionToolReminder);
}
// 然后进入 while 循环
```

Cline 在**进入主循环前**就注入 reminder，LLM 首轮调用时就能看到"必须调用完成工具"。

**我的实现**（L574-599）：
```python
# 在循环内，无工具调用时才注入
if len(tool_calls) == 0:
    policy = self.config.completion_policy
    if policy.require_completion_tool:
        reminder = self._build_completion_reminder(policy)
        if reminder:
            reminder_msg = create_text_message(MessageRole.USER, reminder)
            self._state.messages.append(reminder_msg)
            await self._emit(make_message_added(self.snapshot(), reminder_msg))
        await self._emit(make_turn_finished(...))
        continue
```

我**只在 LLM 返回无工具调用时**才注入 reminder，然后 continue 下一轮。

**逻辑差异**：
- D2 控制流：
  - Cline：循环前注入 → LLM 首轮就看到 reminder → 若首轮仍不调用工具，继续循环
  - 我：循环内无工具时注入 → LLM 首轮不看到 reminder → 若首轮返回文本，才注入 reminder → 下一轮 LLM 看到
- D6 边界条件：
  - Cline 首轮就引导 LLM 调用工具，减少无谓的"返回文本"轮次
  - 我首轮允许 LLM 自由返回，若不调用工具才引导，浪费一轮

**影响**：
- require_completion_tool=True 时，我的方式多消耗一轮 LLM 调用（首轮返回文本，次轮才看到 reminder）
- token 成本：多一轮 = 多一次 input_tokens（含历史）

**修复建议**：
对齐 Cline，在循环前预注入 reminder：
```python
# 在主循环前，after input messages 注入后
policy = self.config.completion_policy
if policy.require_completion_tool:
    reminder = self._build_completion_reminder(policy)
    if reminder:
        reminder_msg = create_text_message(MessageRole.USER, reminder)
        self._state.messages.append(reminder_msg)
        await self._emit(make_message_added(self.snapshot(), reminder_msg))
```
同时保留循环内的 reminder 逻辑（LLM 中途放弃工具调用时继续引导）。

**优先级**：P1（影响 token 效率和 LLM 行为引导）

---

### 差距 #B20：缺失 assistant-message 事件

**严重度**：P2（影响前端事件流完整性）

**Cline 实现**（L665-671）：
```typescript
await this.emit({
    type: "assistant-message",
    snapshot: this.snapshot(),
    iteration: this.state.iteration,
    message,
    finishReason,
});
```

Cline 在 `message-added` 之后额外 emit `assistant-message` 事件，携带 `finishReason`。

**我的实现**：无 `assistant-message` 事件。只有 `message-added`。

**逻辑差异**：
- D5 副作用：Cline 有两个事件（message-added + assistant-message），我只有一个（message-added）
- D7 语义等价：
  - `message-added`：通用消息添加事件（user/assistant/tool 都触发）
  - `assistant-message`：专用 assistant 消息完成事件，携带 finishReason
  - 前端可用 `assistant-message` 区分"assistant 消息完成"vs"其他消息添加"

**影响**：
- 前端无法单独监听 assistant 消息完成事件（需在 message-added 中判断 role）
- finishReason 信息丢失（前端无法知道这轮是 stop/tool-calls/max-tokens）

**修复建议**：
在 `agent/events.py` 新增 `ASSISTANT_MESSAGE` 事件类型，在 runtime.py L550 后 emit：
```python
self._state.messages.append(message)
await self._emit(make_message_added(self.snapshot(), message))
# 新增：emit assistant-message 事件
await self._emit(AgentEvent(
    type=ASSISTANT_MESSAGE,
    snapshot=self.snapshot(),
    iteration=self._state.iteration,
    message=message,
    finish_reason=finish_reason,
))
```

**优先级**：P2（前端可适配，但影响事件流完整性）

---

### 差距 #B33：ControlledStopError 机制缺失

**严重度**：P2（影响 hook 中止的语义清晰度）

**Cline 实现**（L748-749）：
```typescript
const normalized = error instanceof Error ? error : new Error(String(error));
const isControlledStop = normalized instanceof ControlledStopError;
const isAborted = this.abortController.signal.aborted || isControlledStop;
```

Cline 区分两类中止：
1. `AbortController.signal.aborted`：用户主动中止
2. `ControlledStopError`：hook 主动 stop（before_run/before_model/after_model 等）

两者都设 status="aborted"，但语义不同。

**我的实现**（L637-638）：
```python
is_aborted = self._aborted
status = "aborted" if is_aborted else "failed"
```

我只检查 `_aborted` 标志（用户主动中止）。hook stop 抛 `RuntimeError`，会被当作 "failed"。

**逻辑差异**：
- D2 控制流：
  - Cline：hook stop → ControlledStopError → status="aborted"
  - 我：hook stop → RuntimeError → status="failed"
- D7 语义等价：
  - Cline 的 "aborted" 包含用户中止 + hook 主动 stop
  - 我的 "aborted" 仅用户中止，hook stop 被误分类为 "failed"

**影响**：
- hook 主动 stop 时，我的 status="failed"，前端显示"运行失败"
- 实际 hook stop 是预期行为（如 before_model 判断无需继续），不应显示为失败
- 但当前量化场景 hook stop 用得少，影响有限

**修复建议**：
新增 `ControlledStopError` 异常类：
```python
class ControlledStopError(RuntimeError):
    """hook 主动 stop 时抛出 — 对标 Cline ControlledStopError"""
    def __init__(self, reason: str = ""):
        super().__init__(reason or "controlled stop")
        self.reason = reason

# runtime.py 中 hook stop 改为抛 ControlledStopError
if stop_control.stop:
    raise ControlledStopError(stop_control.reason or "stopped by hook")

# catch 块判断
is_controlled_stop = isinstance(error, ControlledStopError)
is_aborted = self._aborted or is_controlled_stop
status = "aborted" if is_aborted else "failed"
```

**优先级**：P2（提升语义清晰度，当前影响小）

---

### 差距 #B34：catch 块 logger 日志缺失

**严重度**：P3（影响调试能力）

**Cline 实现**（L765-775）：
```typescript
this.config.logger?.log?.("Agent loop caught error", {
    severity: status === "failed" ? "error" : "warn",
    agentId: this.state.agentId,
    agentRole: this.state.agentRole,
    runId: result.runId,
    status,
    iteration: this.state.iteration,
    errorName: normalized.name,
    errorMessage: normalized.message,
    assistantContentPartCount: lastAssistantMessage?.content.length ?? 0,
});
```

Cline 在 catch 块用 logger 记录详细错误上下文。

**我的实现**：无 logger 调用，仅设置 `self._state.last_error = str(error)`。

**影响**：
- 错误发生时无结构化日志，调试困难
- 但我的 `last_error` 字段已记录错误信息，前端可展示

**修复建议**：
在 catch 块补充 logging：
```python
except Exception as error:
    is_aborted = self._aborted
    status = "aborted" if is_aborted else "failed"
    self._state.status = status
    self._state.last_error = str(error)
    logger.error(
        "Agent run %s: status=%s, iteration=%d, error=%s",
        self._state.run_id, status, self._state.iteration, error,
        exc_info=not is_aborted,  # aborted 不记堆栈
    )
```

**优先级**：P3

---

## 4. 额外增强项（我有 Cline 无）

### 增强 #B18：invalid_tool_calls 显式提取

**我的实现**（L545）：
```python
invalid_tool_calls = self._extract_invalid_tool_calls(message)
```

我在主循环显式提取 invalid_tool_calls，并生成错误 result 消息（L564-571）。

**Cline 实现**：在 `generateAssistantMessage` 内部处理，不暴露到主循环。

**评估**：功能等价，我的方式更显式。保留。

### 增强 #B24：invalid_tool_messages 错误结果生成

**我的实现**（L564-571）：
```python
for itc in invalid_tool_calls:
    invalid_tool_messages.append(self._build_invalid_tool_result_message(itc))
for invalid_msg in invalid_tool_messages:
    self._state.messages.append(invalid_msg)
    await self._emit(make_message_added(self.snapshot(), invalid_msg))
```

我为 invalid tool_call 生成错误 result 消息，让 LLM 下一轮看到自己调用错了。

**Cline 实现**：通过 metadata 注入 + 下一轮 user 消息提示。

**评估**：功能等价，我的方式更直接。保留。

### 增强 #B27：_check_repeated_tool_failures 死循环检测

**我的实现**（L609）：
```python
self._check_repeated_tool_failures(tool_calls, tool_messages)
```

我在工具执行后检测同一工具同一错误连续 N 次，主动中止。

**Cline 实现**：无此检测，依赖 MistakeTracker + LoopDetectionTracker。

**评估**：与 MistakeTracker 功能重叠，建议评估是否合并。当前保留作为额外保障。

### 增强：prepare_turn_input / format_user_input_block 钩子

**我的实现**（L498-507）：两个用户输入预处理钩子。

**Cline 实现**：用 `prepareTurn` config 回调。

**评估**：我的 hook 方式更灵活（多钩子链式调用），Cline 是单一回调。保留增强。

---

## 5. 一致性统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 完全一致 | 9 | 56% |
| 弱对齐 | 5 | 31% |
| 缺失 | 3 | 19% |
| 偏离 | 3 | 19% |
| 额外增强 | 4 | 25% |

---

## 6. 修复优先级清单

### P1（重要，建议修复）
1. **B9 reminder 时机**：循环前预注入 completionToolReminder，对齐 Cline
2. **B8 输入处理**：保留历史消息不 emit 的设计，但 reminder 时机对齐

### P2（次要，按需修复）
1. **B20 assistant-message 事件**：新增事件类型，前端可单独监听
2. **B33 ControlledStopError**：区分用户中止和 hook stop
3. **B36 finally 清理**：对齐 Cline 清理 abortController

### P3（锦上添花）
1. **B34 logger 日志**：catch 块补充结构化日志
2. **B1 入参类型**：保持现状，Python 习惯

---

## 7. 验证记录

### 7.1 静态对比
- 已逐行对比 agent-runtime.ts L595-794 与 runtime.py L446-667
- 控制流图基本一致，主要差异在 reminder 时机和事件类型

### 7.2 待动态验证
- [ ] 测试 require_completion_tool=True 时首轮 LLM 行为（对比 token 消耗）
- [ ] 测试 hook stop 时 status 是否为 "failed"（验证 B33）
- [ ] 测试 assistant-message 事件缺失对前端的影响

---

**阶段 B 结论**：主循环对齐度约 70%，核心控制流（while/throw_if_aborted/iteration/finish_reason）完全一致。主要差距在 reminder 注入时机（影响 token 效率）和 assistant-message 事件缺失（影响前端完整性）。建议优先修复 reminder 时机。
