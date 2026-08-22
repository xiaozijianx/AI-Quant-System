# Phase 2.9 事件系统 EventEmitter emit 对比

> 对比对象：
> - Cline：`third_party/cline/sdk/packages/agents/src/agent-runtime.ts` + `third_party/cline/sdk/packages/shared/src/agent.ts` + `core/src/runtime/orchestration/runtime-event-adapter.ts` + `core/src/runtime/host/local/agent-event-bridge.ts`
> - Charles：`agent/runtime.py` + `agent/events.py` + `agent/server.py`
>
> 计划章节：`AGENT_COMPARISON_PLAN_V2.md` P2.9（L520-546）
>
> 验证范围：事件类型清单、emit 时机、事件 payload 字段、事件桥接机制、SSE 事件映射、事件顺序

---

## 一、源码定位

| 模块 | Cline 文件 | Charles 文件 |
|------|-----------|-------------|
| 事件类型定义（union / 常量） | `shared/src/agent.ts` L466-550（`AgentRuntimeEvent` 14 变体） | `agent/events.py` L33-66（14 个常量 + 5 个 COMPACTION 扩展常量） |
| 事件 payload 数据结构 | `shared/src/agent.ts` L466-550（每个 variant 独立字段） | `agent/events.py` L73-118（单一 `AgentEvent` dataclass，字段并集） |
| EventEmitter / listeners 容器 | `agent-runtime.ts` L399（`listeners: Set<AgentEventListener>`）+ L472-477（subscribe）+ L1605-1659（emit） | `agent/events.py` L128-227（`EventEmitter` 类） |
| emit 调用点 | `agent-runtime.ts` L587, L611, L615, L636, L660, L665, L682, L698, L710, L716, L733, L778, L784, L927, L954, L1229, L1263, L1284, L1468, L1499, L1551 | `agent/runtime.py` L562, L575, L621, L633, L660, L664, L690, L703, L717, L734, L736, L746, L809, L811, L878, L1348, L1541, L1782, L1903, L2187（via `_emit` / `emit_sync`） |
| 事件桥接（runtime → SSE/前端） | `core/src/runtime/orchestration/runtime-event-adapter.ts`（RuntimeEventAdapter）+ `core/src/services/agent-events.ts`（handleAgentEvent）+ `core/src/runtime/host/local/agent-event-bridge.ts`（AgentEventBridge）+ `core/src/hub/server/handlers/session-event-projector.ts` | `agent/server.py` L647-651（on_event 入队）+ L834-907（`_handle_event` SSE 映射） |
| SSE 事件构造 | `session-event-projector.ts` + `hub-server-transport.ts`（多层封装） | `agent/server.py` L235-238（`_sse_event`） |

---

## 二、对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 关键差异 | 残留类型 |
|---|--------|-----------|-------------|---------|---------|
| 2.9.1 | 事件类型枚举完整性 | `AgentRuntimeEvent` 14 个 variant（agent.ts L466-550）：`run-started` / `message-added` / `turn-started` / `assistant-text-delta` / `assistant-reasoning-delta` / `assistant-message` / `tool-started` / `tool-updated` / `tool-finished` / `usage-updated` / `turn-finished` / `status-notice` / `run-finished` / `run-failed` | 14 个事件常量（events.py L33-58）与 Cline 一一对应 + 5 个 COMPACTION 扩展常量（L61-66：`COMPACTION_STARTED` / `COMPACTION_COMPLETED` / `COMPACTION_SKIPPED` / `COMPACTION_BUDGET_ADJUSTED` / `COMPACTION_FAILED`） | Charles 额外定义 5 个 COMPACTION 事件常量（Cline 的 compaction 通知通过 `status-notice` + `metadata.reason` 表达，不独立为事件类型）。核心 14 类完整性对齐。 | 无 |
| 2.9.2 | AgentEvent 字段结构 | 每个 variant 独立字段（discriminated union）：`tool-started` 携带 `toolCall: AgentToolCallPart`（含 toolCallId/toolName/input/metadata）；`tool-finished` 携带 `toolCall` + `message: AgentMessage`；`assistant-text-delta` 携带 `text` + `accumulatedText`；`assistant-reasoning-delta` 携带 `text` + `accumulatedText` + `redacted?` + `metadata?`；`status-notice` 携带 `message: string` + `metadata?` | 单一 `AgentEvent` dataclass（events.py L73-118），字段并集：`type` / `snapshot` / `iteration` / `text` / `accumulated_text` / `redacted` / `metadata` / `message` / `finish_reason` / `tool_call_count` / `result` / `error` / `tool_name` / `tool_call_id` / `tool_input` / `tool_output` / `tool_is_error` / `tool_duration_ms` / `usage` / `notice` | Cline 用 TS union 保证类型安全（每个 type 只能访问对应字段）；Charles 用单一 dataclass 所有字段并存，未使用的字段为 None，依赖约定。功能等价但类型安全性较弱。 | 无 |
| 2.9.3 | subscribe 返回值 | `agent-runtime.ts` L472-477：`subscribe(listener): () => void`，返回 unsubscribe 函数，内部 `this.listeners.delete(listener)` | `events.py` L144-162：`subscribe(listener) -> Callable[[], None]`，返回 unsubscribe 函数，内部 `self._listeners.remove(listener)` | 完全一致。Cline 用 `Set`，Charles 用 `list`；Charles 额外提供 `unsubscribe_all()`（L164-166）批量清理。 | 无 |
| 2.9.4 | emit 同步 vs 异步 | `agent-runtime.ts` L1605-1659：`private async emit(event): Promise<void>`，完全异步。listener 同步调用（`listener(event)` 不 await），onEvent hook 异步 await（`await hook(event)`）。无同步 emit 通道。 | `events.py` L168-187：`async def emit(self, event)` 异步，listener 调用支持同步/异步（`inspect.isawaitable` 自动 await）。**额外提供 `emit_sync`（L189-221）**：完全同步，不 await async listener（coroutine 被丢弃），用于 `emit_update` 等同步上下文。 | Charles 额外增加 `emit_sync` 方法（Phase 35.1），解决 `run_commands._read_stream` 频繁调用 `emit_update` 时 `asyncio.create_task` 堆积导致 `terminal_output` 事件延迟问题。Cline 无此问题（TS 无事件循环调度差异）。 | 无（Charles 增强） |
| 2.9.5 | listener 异常处理 | `agent-runtime.ts` L1653-1658：listener 同步调用无 try/catch，单个 listener 抛错会中断后续 listener。onEvent hook（L1656-1658）`await hook(event)` 也无 try/catch。 | `events.py` L179-187（emit）+ L211-221（emit_sync）：每个 listener 调用包在 `try/except Exception`，异常只打印 traceback，不影响其他 listener 和 Agent 运行。 | Charles 显式隔离 listener 异常（更健壮）；Cline 依赖 listener 自身不抛错（契约约束）。 | 无 |
| 2.9.6 | 事件顺序保证 | 所有 `await this.emit(...)` 顺序 await（agent-runtime.ts 全文），事件严格按 emit 顺序到达 listener。listener 同步调用按 Set 迭代顺序（插入序）。 | 所有 `await self._emit(...)` 顺序 await（runtime.py 全文），事件严格按 emit 顺序到达 listener。listener 按 list 插入序执行。`emit_sync` 用于 `_make_emit_update`（L2182-2202），同步立即入队，避免 `asyncio.create_task` 调度延迟。 | 顺序保证一致。Charles 的 `emit_sync` 是为了在同步上下文（工具执行中）立即推送事件，避免 task 调度延迟，是对异步 emit 的补充而非替代。 | 无 |
| 2.9.7 | snapshot 在事件中的角色 | `agent-runtime.ts` L505-519：`snapshot()` 每次调用都 `cloneMessages(this.state.messages)`（深拷贝消息数组）+ `[...this.state.pendingToolCalls]`（浅拷贝）+ `cloneUsage(this.state.usage)`（浅拷贝）。事件携带的 snapshot 是独立副本，listener 修改不影响 runtime。 | `runtime.py` L425-443：`snapshot()` 用 `tuple(self._state.messages)`（只读视图，浅层包装）+ `tuple(self._state.pending_tool_calls)` + `clone_usage(self._state.usage)`。Phase 2.3 A20 注释：防 listener 误修改。 | Cline 深拷贝 messages（每条消息的 content 数组也拷贝）；Charles 用 tuple 包装但内部 `AgentMessage` 对象仍是引用共享。Charles 的 tuple 只防 append/remove，不防 listener 修改 message.content。usage 两边都拷贝。 | 无 |
| 2.9.8 | accumulated_text 语义 | `assistant-text-delta.accumulatedText`（L932）：本轮累积的全部文本。`assistant-reasoning-delta.accumulatedText`（L959）：本轮累积的全部 reasoning 文本。字段名相同但语义随 type 切换。 | `make_text_delta`（events.py L246-262）`accumulated_text`：本轮累积文本。`make_reasoning_delta`（L265-288）`accumulated_text`：本轮累积 reasoning 文本。 | 语义完全一致。Cline 字段名 `accumulatedText`（camelCase），Charles `accumulated_text`（snake_case）。 | 无 |
| 2.9.9 | message_added 触发时机 | L587-591（addUserReminderMessage）、L615-619（input 消息）、L660-664（assistant 消息）、L710-714（tool message）、L1263-1267（consumePendingUserMessage）。user/assistant/tool 三类消息都 emit。 | L575（initial_messages）、L621（input 消息）、L660（assistant 消息）、L690（invalid_tool_messages）、L703（reminder_msg）、L734（tool_message）、L878（pending_msg via consume_pending_user_message）、L1348（notice via _inject_user_notice）、L1541（additional_context injection）。 | 触发时机对齐：user/assistant/tool 三类消息都 emit。Charles 额外对 `invalid_tool_messages`（L690）、`additional_context injection`（L1541）、`_inject_user_notice`（L1348）也 emit，覆盖更全。 | 无 |
| 2.9.10 | status_notice 用途 | `agent-runtime.ts` L1228-1236：`prepareTurn` 中通过 `emitStatusNotice(message, metadata)` 回调发射，用于 `prepareTurn` 等中间状态通知（如"正在压缩上下文..."）。compaction 通知也通过 `status-notice` + `metadata.reason`（`runtime-event-adapter.ts` L236-246 `resolveStatusNoticeReason` 识别 `auto_compaction` / `manual_compaction` / `compaction_budget_emergency`）。 | `events.py` L421-435 `make_status_notice`：用于 `prepareTurn` 中间状态通知。同时被复用为 `approval_request` 转发（`runtime.py` L1726-1737：`AgentEvent(type=STATUS_NOTICE, metadata={"type": "approval_request", ...})`）。Phase 2.5 后 tool update 改用 `TOOL_UPDATED`，但 `STATUS_NOTICE` 仍用于 approval_request。 | Cline 的 `status-notice` 仅用于 prepareTurn 通知；Charles 额外复用为 approval_request 通道（Cline 的 approval 走独立 `requestToolApproval` 回调，不进事件流）。Charles 还独立定义 5 个 COMPACTION 事件常量（Cline 复用 `status-notice`）。 | 无 |
| 2.9.11 | tool_started 字段 | `agent-runtime.ts` L1468-1473：`emit({type: "tool-started", snapshot, iteration, toolCall: prepared.toolCall})`。`toolCall` 是完整 `AgentToolCallPart`（含 toolCallId / toolName / input / metadata）。 | `runtime.py` L1782-1787 `make_tool_started`：携带 `tool_name` / `tool_call_id` / `tool_input`（扁平化字段）。无 `metadata` 字段。 | Cline 携带完整 `toolCall` 对象（含 metadata）；Charles 扁平化为 3 个字段，丢失 metadata。 | 无 |
| 2.9.12 | run_failed vs run_finished 互斥 | `agent-runtime.ts` L777-789：`if (status === "failed") { emit run-failed } else { emit run-finished }`。failed 时只 emit `run-failed`，aborted 时 emit `run-finished`（携带 status="aborted" 的 result）。 | `runtime.py` L808-811：`if status == "failed": emit make_run_failed else: emit make_run_finished`。语义与 Cline 一致。ControlledStopError 走 `run-finished`（L777，status="completed", finish_reason="controlled_stop"）。 | 完全一致。失败时只 emit `run-failed`，aborted/controlled_stop 都走 `run-finished`。 | 无 |
| 2.9.13 | 事件桥接机制（runtime → SSE） | 三层适配：① `RuntimeEventAdapter`（`runtime-event-adapter.ts` L172-401）将 14 variant `AgentRuntimeEvent` 翻译为 9 类 legacy `AgentEvent`；② `AgentEventBridge.dispatchAgentEvent`（`agent-event-bridge.ts` L42-76）调用 `handleAgentEvent` 持久化消息 + 发射 `CoreSessionEvent`；③ `projectSessionEvent`（`session-event-projector.ts`）将 `CoreSessionEvent` 投影为 `HubEventEnvelope` 发给前端。`run-started` / `message-added` 被适配器抑制（return `[]`）。 | 单层适配：`server.py` L647-651 `on_event` 回调将 `AgentEvent` 放入 `event_queue`；L834-907 `_handle_event` 直接将 `AgentEvent` 映射为 SSE 字符串（`_sse_event`）。无中间 legacy 事件层。 | Cline 三层适配（runtime event → legacy agent event → core session event → hub envelope），保留 legacy 兼容；Charles 单层直映射，结构更简单。Cline 抑制 `run-started` / `message-added`（前端不可见），Charles 透传所有事件类型（`run-started` 在 `_handle_event` 中是 no-op，但事件本身仍进入 queue）。 | 无 |
| 2.9.14 | SSE 事件映射 | `runtime-event-adapter.ts` L183-263：`turn-started` → `iteration_start`；`turn-finished` → `iteration_end`；`assistant-text-delta` → `content_start(text)`（per delta）；`assistant-reasoning-delta` → `content_start(reasoning)`；`assistant-message` → `content_end(text/reasoning)`；`tool-started` → `content_start(tool)`；`tool-updated` → `content_update(tool)`；`tool-finished` → `content_end(tool)`；`usage-updated` → `usage`（含 delta 计算）；`status-notice` → `notice`；`run-finished` → `done`；`run-failed` → `error`。 | `server.py` L844-907：`run-started` → no-op；`assistant-text-delta` / `assistant-reasoning-delta` → `token`（缓冲 ≥3 字符批量发送）；`tool-execution-started` → `tool_call`；`tool-execution-finished` → `tool_output`；`run-finished` → 刷新缓冲（无 SSE 事件）；`run-failed` → `error` + 刷新缓冲；`status-notice` → 转发 `_handle_status_notice`；`tool-updated` → 转发 `_handle_status_notice`。 | Cline SSE 事件类型更细粒度（`content_start` / `content_end` / `iteration_start` / `iteration_end` / `usage` / `done` / `notice`）；Charles SSE 事件更扁平（`token` / `tool_call` / `tool_output` / `error` / `done` / `phase`）。Charles 的 `token` 缓冲批量发送是性能优化（Cline 每个 delta 单独发 `content_start`）。 | 无 |
| 2.9.15 | 事件顺序（典型一轮） | `run-started` → `message-added`(user) → `turn-started` → `assistant-text-delta`(多次) → `assistant-reasoning-delta`(多次) → `message-added`(assistant) → `assistant-message` → `tool-started` → `tool-updated`(多次) → `tool-finished` → `message-added`(tool) → `turn-finished` → (循环) → `run-finished` / `run-failed` | `run-started` → `message-added`(initial + user) → `turn-started` → `assistant-text-delta`(多次) → `assistant-reasoning-delta`(多次) → `message-added`(assistant) → `assistant-message` → `message-added`(invalid_tool_calls) → `tool-execution-started` → `tool-updated`(多次, via `emit_sync`) → `tool-execution-finished` → `message-added`(tool) → `turn-finished` → (循环) → `run-finished` / `run-failed` | 顺序基本一致。Charles 额外在 assistant 消息后 emit `invalid_tool_calls` 的 `message-added`（L690），Cline 无此独立步骤（invalid 工具调用直接合入 assistant metadata）。 | 无 |
| 2.9.16 | onEvent hook 触发 | `agent-runtime.ts` L1656-1658：`emit` 内 `for (const hook of this.hooks.onEvent) { await hook(event); }`，每个事件都触发 onEvent hook（异步 await）。 | Charles 无 `onEvent` hook（hooks.py 无此钩子点）。事件只通过 `subscribe` 的 listener 分发。 | Cline 有 `onEvent` hook（7 钩子点之一），Charles 未实现。Charles 的事件消费通过 `subscribe(listener)` 等价覆盖。 | 无（P2.10 范围） |
| 2.9.17 | listener 容器数据结构 | `Set<AgentEventListener>`（L399），去重（同一 listener 引用只存储一次），迭代顺序为插入序。 | `list[EventListener]`（L142），不去重，允许同一 listener 多次订阅。 | Cline 用 Set 自动去重；Charles 用 list 允许重复订阅。功能影响小（实际无重复订阅场景）。 | 无 |
| 2.9.18 | tool_updated 事件 payload | `agent-runtime.ts` L1498-1506：`emit({type: "tool-updated", snapshot, iteration, toolCall: prepared.toolCall, update})`。携带完整 `toolCall` 对象 + `update` 字段。 | `runtime.py` L2187-2194（`_make_emit_update`）：`AgentEvent(type=TOOL_UPDATED, snapshot, iteration, tool_call_id, tool_name, metadata=update)`。扁平化 `tool_call_id` / `tool_name` + `metadata` 存放 update。 | Cline 携带完整 `toolCall` + 独立 `update` 字段；Charles 扁平化 + metadata 存 update。 | 无 |
| 2.9.19 | assistant_message 事件 | `agent-runtime.ts` L665-671：`emit({type: "assistant-message", snapshot, iteration, message, finishReason})`。携带完整 `AgentMessage` + `finishReason`。 | `runtime.py` L664-669 `make_assistant_message`：`AgentEvent(type=ASSISTANT_MESSAGE, snapshot, iteration, message, finish_reason)`。 | 完全一致。Charles 注释（L661）明确对标 Cline L665-671。 | 无 |
| 2.9.20 | usage_updated 事件 | `agent-runtime.ts` L1284-1288：`emit({type: "usage-updated", snapshot, usage: cloneUsage(this.state.usage)})`。携带累积 usage 快照。 | `runtime.py` L989-991 `make_usage_updated`：`AgentEvent(type=USAGE_UPDATED, snapshot, usage=clone_usage(self._state.usage))`。 | 完全一致。Cline 的 `RuntimeEventAdapter`（runtime-event-adapter.ts L334-370）额外计算 delta 给 legacy `usage` 事件；Charles 直接透传累积值，delta 由前端计算。 | 无 |

---

## 三、事件类型清单对照

| Cline variant | Charles 常量 | Cline payload | Charles payload | 对齐状态 |
|---------------|-------------|---------------|-----------------|---------|
| `run-started` | `RUN_STARTED` | `snapshot` | `snapshot` | 对齐 |
| `message-added` | `MESSAGE_ADDED` | `snapshot` + `message` | `snapshot` + `message` | 对齐 |
| `turn-started` | `TURN_STARTED` | `snapshot` + `iteration` | `snapshot` + `iteration` | 对齐 |
| `assistant-text-delta` | `ASSISTANT_TEXT_DELTA` | `snapshot` + `iteration` + `text` + `accumulatedText` | `snapshot` + `iteration` + `text` + `accumulated_text` | 对齐 |
| `assistant-reasoning-delta` | `ASSISTANT_REASONING_DELTA` | `snapshot` + `iteration` + `text` + `accumulatedText` + `redacted?` + `metadata?` | `snapshot` + `iteration` + `text` + `accumulated_text` + `redacted` + `metadata` | 对齐 |
| `assistant-message` | `ASSISTANT_MESSAGE` | `snapshot` + `iteration` + `message` + `finishReason` | `snapshot` + `iteration` + `message` + `finish_reason` | 对齐 |
| `tool-started` | `TOOL_EXECUTION_STARTED` | `snapshot` + `iteration` + `toolCall`（完整对象） | `snapshot` + `iteration` + `tool_name` + `tool_call_id` + `tool_input` | **差异**：Charles 扁平化，丢失 metadata |
| `tool-updated` | `TOOL_UPDATED` | `snapshot` + `iteration` + `toolCall` + `update` | `snapshot` + `iteration` + `tool_call_id` + `tool_name` + `metadata`(=update) | **差异**：Charles 扁平化 |
| `tool-finished` | `TOOL_EXECUTION_FINISHED` | `snapshot` + `iteration` + `toolCall` + `message`（完整 tool result message） | `snapshot` + `iteration` + `tool_name` + `tool_call_id` + `tool_output` + `tool_is_error` + `tool_duration_ms` | **差异**：Charles 扁平化输出字段，Cline 携带完整 message |
| `usage-updated` | `USAGE_UPDATED` | `snapshot` + `usage` | `snapshot` + `usage` | 对齐 |
| `turn-finished` | `TURN_FINISHED` | `snapshot` + `iteration` + `toolCallCount` | `snapshot` + `iteration` + `tool_call_count` | 对齐 |
| `status-notice` | `STATUS_NOTICE` | `snapshot` + `message` + `metadata?` | `snapshot` + `notice` + `metadata` | **差异**：字段名 `message`(Cline) vs `notice`(Charles) |
| `run-finished` | `RUN_FINISHED` | `snapshot` + `result` | `snapshot` + `result` | 对齐 |
| `run-failed` | `RUN_FAILED` | `snapshot` + `error` | `snapshot` + `error` | 对齐 |
| （无） | `COMPACTION_STARTED` | （Cline 复用 `status-notice`） | `snapshot` + `iteration` + `metadata`（含 kind/reason/phase/trigger_tokens/target_tokens/max_input_tokens/compaction_snapshot） | **Charles 增强**：独立事件类型 |
| （无） | `COMPACTION_COMPLETED` | （Cline 复用 `status-notice`） | `snapshot` + `iteration` + `metadata`（含 tokens_before/after, messages_before/after） | **Charles 增强**：独立事件类型 |
| （无） | `COMPACTION_SKIPPED` | （Cline 复用 `status-notice`） | `snapshot` + `iteration` + `metadata`（含 reason） | **Charles 增强**：独立事件类型 |
| （无） | `COMPACTION_BUDGET_ADJUSTED` | （Cline 复用 `status-notice`） | `snapshot` + `iteration` + `metadata`（含 policy_intent/action_count/warning_count） | **Charles 增强**：独立事件类型 |
| （无） | `COMPACTION_FAILED` | （Cline 复用 `status-notice`） | `snapshot` + `iteration` + `metadata`（含 error） | **Charles 增强**：独立事件类型 |

---

## 四、emit 时机对照

### 4.1 run-started

| 位置 | Cline | Charles |
|------|-------|---------|
| 主循环入口 | `agent-runtime.ts` L611 `await this.emit({type: "run-started", snapshot})` | `runtime.py` L562 `await self._emit(make_run_started(self.snapshot()))` |
| 触发条件 | `execute()` 中 `callBeforeRunHooks()` 之后 | `run()` 中 `_call_before_run_hooks()` 之后 |

### 4.2 turn-started

| 位置 | Cline | Charles |
|------|-------|---------|
| 主循环内 | L636-640 `emit({type: "turn-started", snapshot, iteration})` | L633 `await self._emit(make_turn_started(self.snapshot(), self._state.iteration))` |
| 触发条件 | 每次迭代开始，`state.iteration += 1` 之后 | 同 Cline |

### 4.3 assistant-text-delta / assistant-reasoning-delta

| 位置 | Cline | Charles |
|------|-------|---------|
| 流式消费 | L927-933（text-delta）+ L954-962（reasoning-delta） | L922-925（text-delta）+ L938-942（reasoning-delta） |
| 触发条件 | `model.stream` 事件 `text-delta` / `reasoning-delta` | 同 Cline |

### 4.4 message-added

| 位置 | Cline | Charles |
|------|-------|---------|
| user 输入 | L615-619 | L621 |
| assistant 消息 | L660-664 | L660 |
| tool message | L710-714 | L734 |
| reminder / pending | L587-591（addUserReminderMessage）+ L1263-1267（consumePendingUserMessage） | L703（reminder_msg）+ L878（pending_msg via consume_pending_user_message）+ L1348（_inject_user_notice）+ L1541（additional_context injection） |
| initial_messages | 无独立 emit（通过 `initialMessages` config 在构造时注入） | L575（首次 run 时 emit message-added） |

### 4.5 assistant-message

| 位置 | Cline | Charles |
|------|-------|---------|
| assistant 消息完成后 | L665-671 | L664-669 |
| 触发条件 | `message-added`(assistant) 之后立即 emit | 同 Cline（注释 L661 明确对标） |

### 4.6 tool-started / tool-finished

| 位置 | Cline | Charles |
|------|-------|---------|
| tool-started | L1468-1473 | L1782-1787 |
| tool-finished | L1551-1557 | L1903-1910 |
| tool-updated | L1498-1506（emitUpdate 回调） | L2187-2198（_make_emit_update via emit_sync） |

### 4.7 turn-finished

| 位置 | Cline | Charles |
|------|-------|---------|
| 无工具调用时 | L682-687 | L710-712 |
| 有工具调用时 | L716-721 | L736-738 |

### 4.8 run-finished / run-failed

| 位置 | Cline | Charles |
|------|-------|---------|
| 正常完成 | L698-702 / L733-738 | L717 / L746 |
| 异常 | L778-789（catch 块） | L809-811（except 块） |
| ControlledStop | （Cline 走 catch 块的 isAborted 分支，emit run-finished） | L777（ControlledStopError 单独 except，emit run-finished，status="completed"） |

---

## 五、事件桥接机制对比

### 5.1 Cline 桥接链路

```
AgentRuntime.emit(AgentRuntimeEvent)
    ↓ listeners Set 同步调用
RuntimeEventAdapter.translate(AgentRuntimeEvent) -> AgentEvent[]   # 14 variant → 9 legacy type
    ↓
AgentEventBridge.dispatchAgentEvent(sessionId, config, AgentEvent)
    ↓ handleAgentEvent
CoreSessionEvent emit
    ↓
projectSessionEvent(CoreSessionEvent) -> HubEventEnvelope
    ↓ ctx.publish
SSE / WebSocket 前端推送
```

关键特征：
- 三层适配（runtime event → legacy agent event → core session event → hub envelope）
- `RuntimeEventAdapter` 是有状态适配器（L172-274）：维护 `lastUsage`（用于 usage delta 计算）+ `toolStartedAt`（用于 tool duration 计算）
- `run-started` / `message-added` 被适配器抑制（`return []`，前端不可见）
- 持久化消息在 `handleAgentEvent` 中完成（`persistMessages` 回调）

### 5.2 Charles 桥接链路

```
AgentRuntime._emit(AgentEvent) -> EventEmitter.emit
    ↓ listener 同步/异步调用
on_event(AgentEvent) -> event_queue.put_nowait(event)   # server.py L647-651
    ↓
_handle_event(AgentEvent, state) -> SSE 字符串           # server.py L834-907
    ↓ yield
SSE 前端推送
```

关键特征：
- 单层适配（AgentEvent 直映射为 SSE 字符串）
- 无中间 legacy 事件层
- 无有状态适配器（usage delta 由前端计算，tool duration 在 runtime 层计算后放入 `tool_duration_ms` 字段）
- 所有事件类型都进入 queue（`run-started` 在 `_handle_event` 中 no-op，但事件本身仍入队）
- 消息持久化在 `run_agent` 协程中（L672-673：`result = await runtime.run(...)` 后 `_session_manager.update`）

---

## 六、SSE 事件映射对比

| Cline legacy AgentEvent | Charles SSE 事件 | 说明 |
|------------------------|------------------|------|
| `iteration_start` | （无对应 SSE 事件） | Charles 不发射 iteration_start，前端通过 `phase: thinking` 推断 |
| `iteration_end` | （无对应 SSE 事件） | Charles 不发射 iteration_end |
| `content_start(text)` | `token`（缓冲 ≥3 字符批量） | Charles 批量发送优化 |
| `content_start(reasoning)` | `token`（缓冲 ≥3 字符批量） | Charles 不区分 text/reasoning，统一作为 token |
| `content_end(text)` | （无对应，由 `run-finished` 刷新缓冲） | Charles 不发 content_end |
| `content_end(reasoning)` | （无对应） | Charles 不发 content_end |
| `content_start(tool)` | `tool_call` | 字段映射：toolName → name, input → args |
| `content_update(tool)` | （转发 `_handle_status_notice`） | Charles 的 tool-updated 走 status_notice 分发 |
| `content_end(tool)` | `tool_output` | 字段映射：output, error, durationMs |
| `usage` | （无对应 SSE 事件） | Charles 不通过 SSE 发送 usage（前端从 run-finished 的 result.usage 读取） |
| `notice` | （转发 `_handle_status_notice`） | Charles 的 status-notice 走 `_handle_status_notice` |
| `done` | `done` | 一致 |
| `error` | `error` | 一致 |
| （无） | `phase` | Charles 额外的 phase 事件（thinking/answering） |
| （无） | `pending_prompts` / `pending_prompt_submitted` | Charles 额外的 turn queue 事件 |
| （无） | `file_context_updated` | Charles 额外的文件上下文事件（Stage 6.7） |

---

## 七、nanobot 残留分析

### 7.1 注释残留（不影响功能）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/context.py` | 275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` | docstring 说明已废弃参数 |
| `agent/server.py` | 2, 4, 28 | `"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py""""` 等 | docstring 引用 nanobot 历史实现 |
| `agent/session.py` | 2, 22 | `"""会话管理 — 对标 Cline session persistence + nanobot session_key"""` | docstring 引用 nanobot |
| `agent/providers/qwen.py` | 21, 49, 116, 214, 253, 385, 406 | 多处 docstring `对标 nanobot openai_compat_provider.py` | docstring 引用 nanobot |
| `agent/tools/exec_tool.py` | 2, 8, 9, 10, 18, 19, 41, 57, 123, 165, 181, 263 | docstring `对标 nanobot ShellTool` / `nanobot shell.py` | docstring 引用 nanobot |
| `agent/tools/file_tools.py` | 2, 7, 12, 27, 115, 130, 165 | docstring `对标 nanobot FilesystemTool` | docstring 引用 nanobot |
| `agent/tools/web_tool.py` | 2, 9, 10, 13, 28, 111, 165 | docstring `对标 nanobot WebSearchTool` | docstring 引用 nanobot |
| `agent/skills/__init__.py` | 2, 23 | docstring `对标 nanobot SkillsLoader` | docstring 引用 nanobot |
| `agent/skills/registry.py` | 2, 20, 100, 184 | docstring `对标 nanobot SkillsLoader` | docstring 引用 nanobot |
| `agent/skills/skill_tool.py` | 18 | docstring `nanobot 的"子 agent 隔离执行"` | docstring 引用 nanobot |
| `agent/skills/loader.py` | 2, 29, 48, 96, 167, 222, 392, 423 | docstring `对标 nanobot SkillsLoader` | docstring 引用 nanobot |
| `agent/tools/__init__.py` | 2 | docstring `对标 nanobot agent/tools` | docstring 引用 nanobot |

### 7.2 实现逻辑残留

| 文件 | 行号 | 残留内容 | 性质 | 影响 |
|------|------|---------|------|------|
| `agent/context.py` | 275 | `extra_sections` 参数（`SystemPromptBuilder.__init__` 签名） | 已废弃参数，保留签名向后兼容 | 无功能影响（注释明确"当前无调用方传入"） |

**结论**：事件系统相关源码（`events.py` / `runtime.py` 事件部分 / `server.py` SSE 部分）无 nanobot 残留。nanobot 残留集中在工具/skills/provider 的 docstring 中，属于历史溯源注释，不影响事件系统功能。唯一的实现逻辑残留是 `context.py` 的 `extra_sections` 已废弃参数，与事件系统无关。

---

## 八、关键差异总结

### 8.1 Charles 相对 Cline 的增强

1. **`emit_sync` 方法**（events.py L189-221）：解决同步上下文（`emit_update`）的事件推送延迟问题，Cline 无此需求（TS 无事件循环调度差异）。
2. **listener 异常隔离**（events.py L179-187）：每个 listener 调用包 try/except，单个 listener 异常不影响其他 listener。Cline 无此保护（依赖 listener 契约）。
3. **5 个 COMPACTION 事件常量**（events.py L61-66）：将 Cline 通过 `status-notice` + `metadata.reason` 表达的 compaction 通知独立为事件类型，前端无需解析 metadata.reason。
4. **`unsubscribe_all` 方法**（events.py L164-166）：批量清理所有 listener，Cline 无此方法。
5. **`message-added` 覆盖更全**：Charles 对 `invalid_tool_messages` / `additional_context injection` / `_inject_user_notice` 也 emit `message-added`，Cline 仅对 user/assistant/tool 三类消息 emit。

### 8.2 Charles 相对 Cline 的缺失

1. **`onEvent` hook**：Cline 在 `emit` 内 `await hook(event)`（L1656-1658），Charles 无此钩子点（事件消费通过 `subscribe(listener)` 等价覆盖）。
2. **`tool-started` / `tool-updated` / `tool-finished` 的完整 `toolCall` 对象**：Cline 携带完整 `AgentToolCallPart`（含 metadata），Charles 扁平化为 `tool_name` / `tool_call_id` / `tool_input`，丢失 `metadata` 字段。
3. **`tool-finished` 的完整 `message`**：Cline 携带完整 `AgentMessage`（含 ToolResultPart），Charles 拆分为 `tool_output` / `tool_is_error` / `tool_duration_ms` 扁平字段。
4. **`status-notice` 字段名**：Cline 字段名 `message`，Charles 字段名 `notice`（可能与 `message-added` 的 `message` 字段冲突而改名）。
5. **事件桥接的 legacy 兼容层**：Cline 通过 `RuntimeEventAdapter` 保留 9 类 legacy `AgentEvent`，Charles 无此兼容层（直接映射 SSE）。

### 8.3 设计等价但实现差异

1. **事件 payload 数据结构**：Cline 用 TS discriminated union（类型安全），Charles 用单一 dataclass 字段并集（依赖约定）。
2. **snapshot 拷贝策略**：Cline 深拷贝 messages（`cloneMessages`），Charles 用 tuple 浅层包装（内部 AgentMessage 引用共享）。
3. **listener 容器**：Cline 用 `Set`（去重），Charles 用 `list`（允许重复）。
4. **事件桥接层数**：Cline 三层（runtime event → legacy agent event → core session event → hub envelope），Charles 单层（AgentEvent → SSE 字符串）。

---

## 九、结论

P2.9 事件系统 emit 对比的核心结论：

1. **事件类型清单对齐**：14 个核心事件类型完全对齐，Charles 额外定义 5 个 COMPACTION 事件常量（Cline 复用 `status-notice`）。
2. **emit 时机对齐**：所有 emit 调用点的触发条件与顺序与 Cline 一致，Charles 在 `invalid_tool_messages` / `additional_context` 等场景额外 emit `message-added`。
3. **事件 payload 字段**：核心字段对齐，差异集中在 `tool-started` / `tool-updated` / `tool-finished`（Cline 携带完整 `toolCall` 对象，Charles 扁平化）和 `status-notice` 字段名（`message` vs `notice`）。
4. **事件桥接机制**：Cline 三层适配 + legacy 兼容层，Charles 单层直映射。Charles 结构更简单但无 legacy 兼容。
5. **SSE 事件映射**：Cline SSE 事件更细粒度（`content_start` / `content_end` / `iteration_start` / `iteration_end`），Charles SSE 事件更扁平（`token` / `tool_call` / `tool_output` / `phase`）。
6. **事件顺序**：两边都通过 `await emit` 保证严格顺序，Charles 额外用 `emit_sync` 解决同步上下文的事件推送延迟。
7. **nanobot 残留**：事件系统源码无残留；nanobot 残留集中在工具/skills/provider 的 docstring 中（注释残留），唯一的实现逻辑残留是 `context.py` 的 `extra_sections` 已废弃参数（与事件系统无关）。
