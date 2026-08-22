# Phase 7.18 事件系统对比

> 对比范围：Cline `sdk/packages/agents/src/agent-runtime.ts` 的 `listeners: Set<AgentEventListener>` + `subscribe()` + `private async emit()` + 14 个 `AgentRuntimeEvent` variant（定义于 `sdk/packages/shared/src/agent.ts` L466-550）+ SSE 多层适配链（`runtime-event-adapter.ts` / `agent-event-bridge.ts` / `session-event-projector.ts`）；对比 Charles `agent/events.py` 的 `EventEmitter` 类 + 14 个核心事件常量 + 5 个 COMPACTION 扩展常量 + `AgentEvent` dataclass + `make_*` 辅助函数 + `agent/runtime.py` 的 `_emit` / `_make_emit_update` + `agent/server.py` 单层 SSE 映射；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L58（`AgentEventListener` 类型）+ L399（`listeners: Set<AgentEventListener>`）+ L471-476（`subscribe` 返回 unsubscribe）+ L1605-1659（`private async emit` + listener 同步调用 + onEvent hook 异步 await + telemetry + logger）+ L777-789（`run-failed` vs `run-finished` 互斥）+ L831 / L1227 / L1495（signal 透传）
> - `third_party/cline/sdk/packages/shared/src/agent.ts` L466-550（`AgentRuntimeEvent` discriminated union，14 variant）+ L128-140（`AgentRuntimeStateSnapshot`）+ L556-566（`AgentRunResult`）
> - `third_party/cline/sdk/packages/shared/src/connectors/events.ts`（连接器事件 — 与 AgentRuntime 事件独立）
>
> Charles 源码：
> - `agent/events.py` L33-66（19 个事件类型常量：14 核心 + 5 COMPACTION）+ L73-118（`AgentEvent` dataclass 字段并集）+ L121（`EventListener` 类型，支持同步/异步）+ L128-227（`EventEmitter` 类：`subscribe` / `unsubscribe_all` / `emit` / `emit_sync` / `listener_count`）+ L233-657（14 个 `make_*` 辅助函数）
> - `agent/runtime.py` L252（`self._emitter = EventEmitter()`）+ L372-374（`subscribe` 透传）+ L425-443（`snapshot` 用 tuple 只读视图）+ L562 / L575 / L621 / L633 / L660-664 / L690 / L703 / L717 / L734 / L746 / L777 / L809-811 / L878 / L922 / L938 / L989 / L1348 / L1541 / L1782 / L1903 / L2147-2149（`_emit` 调用点）+ L2151-2202（`_make_emit_update` 用 `emit_sync`）
> - `agent/server.py` L647-651（`on_event` 入队）+ L834-907（`_handle_event` SSE 映射）+ L218-238（`_sse_event` 构造）+ L986-1024（`/api/chat/stream` SSE 端点）
> - `agent/types.py` L374-398（`AgentRuntimeStateSnapshot` 用 tuple 字段）+ L401-421（`CompactionStateSnapshot` frozen=True）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的事件系统（事件类型、事件分发、事件监听、SSE 推送）。**核心结论：计划文件 P7.18 列出的 8 项对比项中 7 项基本对齐（事件类型枚举 / AgentEvent 字段 / subscribe 返回 unsubscribe / listener 异常处理 / 事件顺序保证 / snapshot 引用语义 / run_failed vs run_finished 互斥），1 项计划标注"已对齐"但实际存在差异（emit 同步 vs 异步 — Cline 仅 async emit + 同步 listener 调用，Charles async emit + 自动 await async listener + 额外提供 `emit_sync` 同步通道）。**

### 计划文件核实结果

AGENT_COMPARISON_PLAN_V2.md L2953-2962 的 P7.18 对比表标注全部 8 项"已对齐"。经源码核实：

| 计划项 | 计划标注 | 实际核实 | 一致性 |
|--------|---------|---------|--------|
| 7.18.1 事件类型枚举 | 12 种 / 12 种 / 已对齐 | Cline `AgentRuntimeEvent` union 共 **14 个 variant**（agent.ts L466-550，TS 注释 L463 "13 variants" 自身就数错）；Charles `events.py` 共 **19 个常量**（14 核心一一对应 + 5 COMPACTION 扩展）。**计划"12 种"标注错误**。**事件名串存在差异**：Cline `tool-started` / `tool-finished`，Charles `tool-execution-started` / `tool-execution-finished`（多 `execution-` 中缀） | 中-高（核心 14 类一一对应但 2 个事件名串不一致 + Charles 多 5 个 COMPACTION 常量） |
| 7.18.2 AgentEvent 字段 | 是 / 是 / 已对齐 | Cline 用 TS discriminated union（每个 variant 独立字段，类型安全）；Charles 用单一 `AgentEvent` dataclass 字段并集（19 个可选字段，依赖约定）。**字段名 camelCase vs snake_case**：Cline `accumulatedText` / `toolCall` / `finishReason` / `toolCallCount`；Charles `accumulated_text` / `tool_call_id` / `tool_name` / `finish_reason` / `tool_call_count` | 中-高（功能等价，类型安全性较弱 + 字段名风格差异） |
| 7.18.3 subscribe 返回 unsubscribe | 是 / 是 / 已对齐 | Cline L471-476：`subscribe(listener): () => void` 返回闭包 `() => this.listeners.delete(listener)`；Charles L144-162：`subscribe(listener) -> Callable[[], None]` 返回闭包 `unsubscribe()` 调 `self._listeners.remove(listener)`。Charles 额外提供 `unsubscribe_all()`（L164-166）批量清理 | 高（Charles 增强） |
| 7.18.4 emit 同步 vs 异步 | 同步 / 同步 / 已对齐 | Cline L1605-1659：`private async emit(event): Promise<void>` **async**，listener 同步调用（`listener(event)` 不 await），onEvent hook 异步 await；**无同步 emit 通道**。Charles L168-187：`async def emit` **async**，listener 调用 `inspect.isawaitable` 自动 await async listener；**额外提供 `emit_sync`（L189-221）** 同步通道，不 await async listener（coroutine 丢弃），用于 `emit_update` 同步上下文 | 中（计划标注错误：两边 emit 都是 async 而非"同步"；Charles 多一个 `emit_sync` 通道 + 自动 await async listener） |
| 7.18.5 listener 异常处理 | 不影响其他 / 不影响其他 / 已对齐 | Cline L1653-1658：listener 调用**无 try/catch**，单个 listener 抛错会中断后续 listener；onEvent hook（L1656-1658）`await hook(event)` 也无 try/catch。Charles L179-187（emit）+ L211-221（emit_sync）：每个 listener 包在 `try/except Exception`，异常只 `traceback.print_exc()`，不影响其他 listener | 中（Charles 显式隔离更健壮；Cline 依赖 listener 自身不抛错的契约约束） |
| 7.18.6 事件顺序保证 | 是 / 是 / 已对齐 | Cline 所有 `await this.emit(...)` 顺序 await，事件严格按 emit 顺序到达 listener；listener 按 Set 迭代序（插入序）执行。Charles 所有 `await self._emit(...)` 顺序 await；listener 按 list 插入序执行；`emit_sync` 用于 `_make_emit_update` 同步立即入队，避免 `asyncio.create_task` 调度延迟 | 高 |
| 7.18.7 snapshot 引用语义 | 引用 / 引用 / 已对齐 | Cline `snapshot()` L505-519（agent-runtime.ts）：`cloneMessages(this.state.messages)` 深拷贝消息数组 + `[...pendingToolCalls]` 浅拷贝 + `cloneUsage(usage)` 浅拷贝；Charles `snapshot()` L425-443：`tuple(self._state.messages)` **只读视图（浅层包装）** + `tuple(pending_tool_calls)` + `clone_usage(usage)`。**Charles 的 tuple 只防 append/remove，不防 listener 修改 message.content 内部对象**；Cline 深拷贝彻底隔离 | 中（计划"引用/引用"标注偏简化，Cline 实际是深拷贝，Charles 是 tuple 只读视图引用共享） |
| 7.18.8 run_failed vs run_finished 互斥 | 是 / 是 / 已对齐 | Cline L777-789：`if (status === "failed") { emit run-failed } else { emit run-finished }`，failed 时只 emit `run-failed`，aborted 时 emit `run-finished`（携带 status="aborted" 的 result）。Charles L808-811：`if status == "failed": emit make_run_failed else: emit make_run_finished`，ControlledStopError 走 `run-finished`（L777，status="completed", finish_reason="controlled_stop"） | 高 |

### 核心结论

1. **事件类型枚举核心对齐但存在细节差异**：Cline 14 个 variant（agent.ts L466-550，TS 注释自身数错为"13 variants"），Charles 14 个核心常量一一对应 + 5 个 COMPACTION 扩展常量（Cline 的 compaction 通知通过 `status-notice` + `metadata.reason` 表达，不独立为事件类型）。**事件名串差异**：Cline `tool-started` / `tool-finished`，Charles `tool-execution-started` / `tool-execution-finished`（events.py L51-52，多 `execution-` 中缀）。这是前端 SSE 映射时需要兼容的实际差异。
2. **AgentEvent 字段结构差异**：Cline 用 TS discriminated union 保证类型安全（每个 type 只能访问对应字段）；Charles 用单一 `AgentEvent` dataclass 所有字段并存（19 个可选字段），未使用字段为 None，依赖约定。字段名 camelCase vs snake_case 风格差异。
3. **subscribe 返回 unsubscribe 完全对齐**：双方都返回闭包函数，调用后从内部容器移除 listener。Cline 用 `Set`（自动去重），Charles 用 `list`（允许重复订阅，但实际无此场景）。Charles 额外提供 `unsubscribe_all()` 批量清理。
4. **emit 同步 vs 异步 — 计划标注错误**：两边 emit 都是 `async`，不是"同步"。差异：(a) Cline listener 同步调用（`listener(event)` 不 await），Charles 通过 `inspect.isawaitable(result)` 自动 await async listener；(b) Charles 额外提供 `emit_sync`（events.py L189-221）完全同步通道，用于 `emit_update` 等同步上下文（如 `run_commands._read_stream` 频繁调用 `emit_update` 时避免 `asyncio.create_task` 堆积导致 `terminal_output` 事件延迟），Cline 无此通道（TS 无事件循环调度差异）。
5. **listener 异常处理 — Charles 更健壮**：Cline 的 `emit` L1653-1658 listener 调用无 try/catch，单个 listener 抛错会中断后续 listener（依赖 listener 契约不抛错）；Charles L179-187 / L211-221 每个 listener 包 `try/except Exception` + `traceback.print_exc()`，显式隔离异常不影响其他 listener 和 Agent 运行。
6. **事件顺序保证对齐**：双方所有 `await emit(...)` 顺序 await，事件严格按 emit 顺序到达 listener。Charles 的 `emit_sync` 是对异步 emit 的补充（同步立即入队），不破坏顺序保证。
7. **snapshot 引用语义 — Cline 深拷贝 vs Charles tuple 只读视图**：Cline `snapshot()` 用 `cloneMessages` 深拷贝消息数组（每条消息的 content 数组也拷贝），listener 修改不影响 runtime；Charles `snapshot()` 用 `tuple(self._state.messages)` 只读视图，tuple 只防 append/remove，**不防 listener 修改 message.content 内部对象**（AgentMessage 对象仍是引用共享）。计划标注"引用/引用"偏简化，实际 Cline 是深拷贝彻底隔离，Charles 是 tuple 只读视图引用共享。
8. **run_failed vs run_finished 互斥完全对齐**：双方都在 catch 块根据 status 二选一 emit，failed 时只 emit `run-failed`，aborted/controlled_stop 都走 `run-finished`。
9. **SSE 推送机制差异**：Cline 三层适配（runtime event → legacy agent event via `RuntimeEventAdapter` → core session event via `AgentEventBridge` → hub envelope via `session-event-projector`），保留 legacy 兼容；Charles 单层直映射（`server.py` L647-651 `on_event` 入队 + L834-907 `_handle_event` 直接映射 SSE 字符串）。Cline SSE 事件类型更细粒度（`content_start` / `content_end` / `iteration_start` / `iteration_end` / `usage` / `done` / `notice`），Charles SSE 事件更扁平（`token` / `tool_call` / `tool_output` / `error` / `phase`）。Charles 的 `token` 缓冲批量发送是性能优化。
10. **onEvent hook 差异**：Cline `emit` L1656-1658 内 `for (const hook of this.hooks.onEvent) { await hook(event); }`，每个事件都触发 onEvent hook（7 钩子点之一）；Charles 无 `onEvent` hook（hooks.py 无此钩子点），事件只通过 `subscribe(listener)` 分发。Charles 通过 subscribe 等价覆盖 onEvent 能力。
11. **telemetry / logger 差异**：Cline `emit` L1605-1648 内根据 event.type 分发 logger（run-started / tool-finished 用 info，run-failed 用 error + `captureSdkError`，其他用 debug）+ `telemetry.capture({ event: agent.${event.type}, ... })`；Charles `emit` 仅分发 listener，**无 logger / telemetry 集成**（待 Phase Z telemetry 系统补齐）。
12. **nanobot 残留**：P7.18 直接相关代码（events.py + runtime.py 事件相关 + server.py SSE 相关）共 **0 处注释残留 + 0 处实现逻辑残留**。间接相关的 `agent/server.py` 模块级 docstring（L2/L4/L28）有 3 处 nanobot 注释残留，属 P7.1 范围已审计，与事件系统功能无关。

### 一致性总体评估

- **事件类型枚举**：**中-高**。核心 14 类一一对应，但 2 个事件名串不一致（`tool-started` vs `tool-execution-started`）+ Charles 多 5 个 COMPACTION 常量。
- **AgentEvent 字段**：**中-高**。功能等价，类型安全性较弱（discriminated union vs 字段并集 dataclass）+ 字段名风格差异。
- **subscribe 返回 unsubscribe**：**高**。完全对齐，Charles 增强 `unsubscribe_all()`。
- **emit 同步 vs 异步**：**中**。两边 emit 都是 async（计划标注"同步"错误），Charles 多 `emit_sync` 通道 + 自动 await async listener。
- **listener 异常处理**：**中**。Charles 显式隔离更健壮，Cline 依赖契约约束。
- **事件顺序保证**：**高**。完全对齐。
- **snapshot 引用语义**：**中**。Cline 深拷贝彻底隔离，Charles tuple 只读视图引用共享。
- **run_failed vs run_finished 互斥**：**高**。完全对齐。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.18.1 | 事件类型枚举 | `AgentRuntimeEvent` discriminated union 共 **14 个 variant**（agent.ts L466-550）：`run-started` / `message-added` / `turn-started` / `assistant-text-delta` / `assistant-reasoning-delta` / `assistant-message` / `tool-started` / `tool-updated` / `tool-finished` / `usage-updated` / `turn-finished` / `status-notice` / `run-finished` / `run-failed`（TS 注释 L463 "13 variants" 自身数错） | `events.py` L33-66 共 **19 个常量**：14 核心常量（`RUN_STARTED` / `RUN_FINISHED` / `RUN_FAILED` / `TURN_STARTED` / `TURN_FINISHED` / `ASSISTANT_TEXT_DELTA` / `ASSISTANT_REASONING_DELTA` / `MESSAGE_ADDED` / `ASSISTANT_MESSAGE` / `TOOL_EXECUTION_STARTED` / `TOOL_EXECUTION_FINISHED` / `TOOL_UPDATED` / `USAGE_UPDATED` / `STATUS_NOTICE`）+ 5 COMPACTION 扩展常量（`COMPACTION_STARTED` / `COMPACTION_COMPLETED` / `COMPACTION_SKIPPED` / `COMPACTION_BUDGET_ADJUSTED` / `COMPACTION_FAILED`） | 中-高 | 计划"12 种/12 种"标注错误（实际 Cline 14 + Charles 19）。差异：(a) 事件名串 — Cline `tool-started` / `tool-finished`，Charles `tool-execution-started` / `tool-execution-finished`（多 `execution-` 中缀，events.py L51-52）；(b) COMPACTION — Cline 复用 `status-notice` + `metadata.reason`，Charles 独立为 5 个事件常量；(c) compaction 通知 — Cline 通过 `runtime-event-adapter.ts` L236-246 `resolveStatusNoticeReason` 识别 `auto_compaction` / `manual_compaction` / `compaction_budget_emergency`，Charles 通过独立事件类型 + `metadata.phase` 表达 |
| 7.18.2 | AgentEvent 字段 | TS discriminated union，每个 variant 独立字段（agent.ts L466-550）：`tool-started` 携带 `toolCall: AgentToolCallPart`（含 toolCallId/toolName/input/metadata）；`tool-finished` 携带 `toolCall` + `message: AgentMessage`；`assistant-text-delta` 携带 `text` + `accumulatedText`；`status-notice` 携带 `message: string` + `metadata?`；字段名 camelCase | 单一 `AgentEvent` dataclass（events.py L73-118），19 个字段并集：`type` / `snapshot` / `iteration` / `text` / `accumulated_text` / `redacted` / `metadata` / `message` / `finish_reason` / `tool_call_count` / `result` / `error` / `tool_name` / `tool_call_id` / `tool_input` / `tool_output` / `tool_is_error` / `tool_duration_ms` / `usage` / `notice`；字段名 snake_case | 中-高 | 功能等价。差异：(a) 类型安全性 — Cline TS union 保证每个 type 只能访问对应字段，Charles 单一 dataclass 所有字段并存，未使用字段为 None，依赖约定；(b) 字段名风格 — Cline `accumulatedText` / `toolCall` / `finishReason` / `toolCallCount`，Charles `accumulated_text` / `tool_call_id` / `tool_name` / `finish_reason` / `tool_call_count`；(c) tool payload — Cline 携带完整 `toolCall: AgentToolCallPart` 对象（含 metadata），Charles 扁平化为 `tool_name` + `tool_call_id` + `tool_input` 三字段（无 metadata） |
| 7.18.3 | subscribe 返回 unsubscribe | L471-476：`subscribe(listener: AgentEventListener): () => void`，内部 `this.listeners.add(listener)` 返回闭包 `() => { this.listeners.delete(listener); }`；listener 类型 `(event: AgentRuntimeEvent) => void`（同步函数，返回 void） | L144-162：`subscribe(listener: EventListener) -> Callable[[], None]`，内部 `self._listeners.append(listener)` 返回闭包 `unsubscribe()` 调 `self._listeners.remove(listener)`；listener 类型 `Callable[[AgentEvent], Union[None, Any]]`（同步或异步函数）；额外提供 `unsubscribe_all()`（L164-166）批量清理 + `listener_count` 属性（L223-226） | 高 | 完全对齐。差异：(a) 容器数据结构 — Cline `Set`（自动去重，同一 listener 引用只存储一次），Charles `list`（不去重，允许同一 listener 多次订阅，但实际无此场景）；(b) Charles 增强 `unsubscribe_all()` + `listener_count` 属性；(c) listener 类型 — Cline 仅同步函数，Charles 支持同步或 async 函数 |
| 7.18.4 | emit 同步 vs 异步 | L1605-1659：`private async emit(event: AgentRuntimeEvent): Promise<void>` **async**：(1) `buildEventMetadata(event)` 构建元数据；(2) 根据 event.type 分发 logger（run-started/tool-finished 用 info，run-failed 用 error + `captureSdkError`，其他用 debug）；(3) `telemetry.capture({ event: agent.${event.type}, ... })`；(4) `for (const listener of this.listeners) { listener(event); }` **同步调用**（不 await）；(5) `for (const hook of this.hooks.onEvent) { await hook(event); }` 异步 await onEvent hook；**无同步 emit 通道** | L168-187：`async def emit(self, event)` **async**：(1) `listeners = list(self._listeners)` 拷贝列表；(2) `for listener in listeners: result = listener(event); if inspect.isawaitable(result): await result` **自动 await async listener**；(3) try/except 隔离异常；**额外提供 `emit_sync`（L189-221）** 完全同步通道：不 await async listener（coroutine 丢弃），用于 `emit_update` 同步上下文（如 run_commands._read_stream 频繁调用 emit_update 时避免 asyncio.create_task 堆积） | 中 | 计划"同步/同步"标注错误（两边 emit 都是 async）。差异：(a) listener 调用 — Cline 同步调用不 await，Charles `inspect.isawaitable` 自动 await async listener；(b) 同步通道 — Charles 额外 `emit_sync`，Cline 无；(c) telemetry/logger — Cline 集成 logger + telemetry，Charles 无；(d) onEvent hook — Cline emit 内 await onEvent hook，Charles 无 onEvent hook；(e) 列表拷贝 — Cline 直接迭代 Set（不减拷贝），Charles `list(self._listeners)` 拷贝避免遍历中订阅/取消订阅问题 |
| 7.18.5 | listener 异常处理 | L1653-1658：listener 调用**无 try/catch**：`for (const listener of this.listeners) { listener(event); }`，单个 listener 抛错会中断后续 listener；onEvent hook（L1656-1658）`await hook(event)` 也无 try/catch；依赖 listener 契约不抛错 | L179-187（emit）+ L211-221（emit_sync）：每个 listener 调用包在 `try/except Exception`：`try: result = listener(event); if inspect.isawaitable(result): await result; except Exception: import traceback; traceback.print_exc()`，异常只打印 traceback，不影响其他 listener 和 Agent 运行 | 中 | Charles 显式隔离 listener 异常更健壮；Cline 依赖 listener 自身不抛错的契约约束。影响：若 listener 抛未捕获异常，Cline 会中断后续 listener 并向上抛出（可能影响 Agent 运行），Charles 会隔离异常继续执行其他 listener |
| 7.18.6 | 事件顺序保证 | 所有 `await this.emit(...)` 顺序 await（agent-runtime.ts 全文 ~22 处 emit 调用），事件严格按 emit 顺序到达 listener；listener 按 Set 迭代序（插入序）执行；onEvent hook 按 hooks.onEvent 数组序异步 await | 所有 `await self._emit(...)` 顺序 await（runtime.py 全文 ~22 处 _emit 调用），事件严格按 emit 顺序到达 listener；listener 按 list 插入序执行；`emit_sync` 用于 `_make_emit_update`（L2182-2202）同步立即入队，避免 `asyncio.create_task` 调度延迟导致 `terminal_output` 事件延迟到 tool_output 之后 | 高 | 顺序保证一致。Charles 的 `emit_sync` 是为了在同步上下文（工具执行中）立即推送事件，避免 task 调度延迟，是对异步 emit 的补充而非替代，不破坏顺序保证 |
| 7.18.7 | snapshot 引用语义 | `agent-runtime.ts` `snapshot()` L505-519：`cloneMessages(this.state.messages)` **深拷贝消息数组**（每条消息的 content 数组也拷贝）+ `[...this.state.pendingToolCalls]` 浅拷贝 + `cloneUsage(this.state.usage)` 浅拷贝；事件携带的 snapshot 是独立副本，listener 修改不影响 runtime | `runtime.py` `snapshot()` L425-443：`tuple(self._state.messages)` **只读视图（浅层包装）** + `tuple(self._state.pending_tool_calls)` + `clone_usage(self._state.usage)`；Phase 2.3 A20 注释"防 listener 误修改" | 中 | 计划"引用/引用"标注偏简化。差异：(a) messages — Cline 深拷贝彻底隔离，Charles tuple 只读视图（AgentMessage 对象仍是引用共享，listener 可修改 message.content 内部对象）；(b) pending_tool_calls — Cline 浅拷贝数组，Charles tuple 只读视图；(c) usage — 两边都拷贝；(d) 影响 — Charles 的 tuple 只防 append/remove，不防 listener 修改 message.content，理论上 listener 可修改消息内容影响 runtime（实际 listener 通常只读） |
| 7.18.8 | run_failed vs run_finished 互斥 | L777-789：`if (status === "failed") { await this.emit({ type: "run-failed", snapshot, error: normalized }); } else { await this.emit({ type: "run-finished", snapshot, result }); }`；failed 时只 emit `run-failed`，aborted 时 emit `run-finished`（携带 status="aborted" 的 result） | L808-811：`if status == "failed": await self._emit(make_run_failed(self.snapshot(), error)) else: await self._emit(make_run_finished(self.snapshot(), result))`；ControlledStopError 走 `run-finished`（L777，status="completed", finish_reason="controlled_stop"） | 高 | 完全一致。失败时只 emit `run-failed`，aborted/controlled_stop 都走 `run-finished`。差异：Charles 的 ControlledStopError（L777）走 run-finished 携带 finish_reason="controlled_stop"，Cline 的 ControlledStopError 走相同路径 |

---

## 三、重点差距详解

### 差距 1：事件名串不一致 — tool-started vs tool-execution-started（对应对比项 7.18.1）

**严重度**：P2（前端 SSE 映射需兼容）

**Cline 实现**（agent.ts L505-523）：
```typescript
| { type: "tool-started"; snapshot: AgentRuntimeStateSnapshot; iteration: number; toolCall: AgentToolCallPart }
| { type: "tool-updated"; snapshot: AgentRuntimeStateSnapshot; iteration: number; toolCall: AgentToolCallPart; update: unknown }
| { type: "tool-finished"; snapshot: AgentRuntimeStateSnapshot; iteration: number; toolCall: AgentToolCallPart; message: AgentMessage }
```

**Charles 实现**（events.py L51-54）：
```python
TOOL_EXECUTION_STARTED = "tool-execution-started"
TOOL_EXECUTION_FINISHED = "tool-execution-finished"
# 工具进度更新事件 — 对标 Cline tool-updated (agent.ts L511-516)
TOOL_UPDATED = "tool-updated"
```

**逻辑差异**：
- Cline 事件名串：`tool-started` / `tool-updated` / `tool-finished`
- Charles 事件名串：`tool-execution-started` / `tool-updated` / `tool-execution-finished`
- `tool-updated` 两边一致
- `tool-started` / `tool-finished` Charles 多 `execution-` 中缀

**影响**：
- 前端 SSE 映射需兼容两套事件名串（若前端从 Cline 迁移到 Charles）
- Charles 的 server.py `_handle_event`（L834-907）已硬编码 `TOOL_EXECUTION_STARTED` / `TOOL_EXECUTION_FINISHED` 常量，与 Charles 前端协议一致
- 与 Cline 前端不兼容（若混用）

**修复建议**：保持现状（Charles 前端已适配）。若未来需与 Cline 前端兼容，可将常量改为 `TOOL_STARTED = "tool-started"` / `TOOL_FINISHED = "tool-finished"` 对齐 Cline。

**优先级**：P2

---

### 差距 2：emit 同步 vs 异步 — Charles 多 emit_sync 通道（对应对比项 7.18.4）

**严重度**：P3（Charles 增强，无功能 bug）

**Cline 实现**（L1605-1659）：
```typescript
private async emit(event: AgentRuntimeEvent): Promise<void> {
    const metadata = buildEventMetadata(event);
    switch (event.type) {
        case "run-started": this.config.logger?.info?.(...); break;
        case "run-failed": this.config.logger?.error?.(...); captureSdkError(...); break;
        default: this.config.logger?.debug?.(...); break;
    }
    this.config.telemetry?.capture({ event: `agent.${event.type}`, properties: metadata });
    for (const listener of this.listeners) { listener(event); }  // 同步调用
    for (const hook of this.hooks.onEvent) { await hook(event); }  // 异步 await
}
// 无同步 emit 通道
```

**Charles 实现**（L168-221）：
```python
async def emit(self, event: AgentEvent) -> None:
    listeners = list(self._listeners)
    for listener in listeners:
        try:
            result = listener(event)
            if inspect.isawaitable(result):
                await result  # 自动 await async listener
        except Exception:
            import traceback
            traceback.print_exc()

def emit_sync(self, event: AgentEvent) -> None:
    listeners = list(self._listeners)
    for listener in listeners:
        try:
            listener(event)  # 不 await async listener
        except Exception:
            import traceback
            traceback.print_exc()
```

**逻辑差异**：
- listener 调用：Cline 同步调用不 await，Charles `inspect.isawaitable` 自动 await async listener
- 同步通道：Charles 额外 `emit_sync`（L189-221），Cline 无
- telemetry/logger：Cline 集成 logger + telemetry，Charles 无
- onEvent hook：Cline emit 内 await onEvent hook，Charles 无 onEvent hook

**Charles emit_sync 的设计动机**（events.py L189-210 docstring）：
- 原实现用 `asyncio.create_task(self._emit(event))` fire-and-forget，task 不会立即执行，需等事件循环调度
- 在 `_read_stream` 频繁调用时，task 可能堆积，导致 `terminal_output` 事件延迟到 `tool_output` 之后才进入 event_queue，前端无法实时看到终端输出
- `emit_sync` 立即调用所有 listener（包括同步和 async），同步 listener 被立即执行（如 server.py 的 on_event 把事件放入 event_queue），async listener 被调用但不 await

**影响**：
- Charles 的 `emit_sync` 解决了 Python asyncio 事件循环调度延迟问题，Cline 无此问题（JS 单线程事件循环调度更及时）
- Charles 的自动 await async listener 提供了更灵活的 listener 编写方式（可 sync 可 async），Cline listener 必须是同步函数
- Cline 的 telemetry/logger 集成提供更好的可观测性，Charles 待 Phase Z 补齐

**修复建议**：保持现状，Charles 的 `emit_sync` 是合理的 Python 适配。telemetry 待 Phase Z 补齐。

**优先级**：P3

---

### 差距 3：listener 异常处理 — Cline 无 try/catch（对应对比项 7.18.5）

**严重度**：P3（健壮性差异）

**Cline 实现**（L1653-1658）：
```typescript
for (const listener of this.listeners) { listener(event); }  // 无 try/catch
for (const hook of this.hooks.onEvent) { await hook(event); }  // 无 try/catch
```

**Charles 实现**（L179-187 / L211-221）：
```python
for listener in listeners:
    try:
        result = listener(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        import traceback
        traceback.print_exc()
```

**逻辑差异**：
- Cline：listener 抛未捕获异常会中断后续 listener 并向上抛出（可能影响 Agent 运行）
- Charles：每个 listener 包 try/except，异常只打印 traceback，不影响其他 listener 和 Agent 运行

**影响**：
- 若 listener 抛未捕获异常，Cline 行为不确定（可能中断 emit 后续流程，可能影响 Agent 主循环）
- Charles 显式隔离，保证单个 listener 故障不影响其他 listener 和 Agent 运行
- Cline 依赖 listener 契约不抛错（开发者需自行保证 listener 内 try/catch）

**修复建议**：保持现状，Charles 的显式隔离更健壮。Cline 的契约约束是 TS 生态惯例。

**优先级**：P3

---

### 差距 4：snapshot 引用语义 — Cline 深拷贝 vs Charles tuple 只读视图（对应对比项 7.18.7）

**严重度**：P3（潜在风险，实际影响小）

**Cline 实现**（agent-runtime.ts L505-519）：
```typescript
snapshot(): AgentRuntimeStateSnapshot {
    return {
        agentId: this.state.agentId,
        // ...
        messages: cloneMessages(this.state.messages),  // 深拷贝
        pendingToolCalls: [...this.state.pendingToolCalls],  // 浅拷贝
        usage: cloneUsage(this.state.usage),  // 浅拷贝
    };
}
```

**Charles 实现**（runtime.py L425-443）：
```python
def snapshot(self) -> AgentRuntimeStateSnapshot:
    return AgentRuntimeStateSnapshot(
        # ...
        messages=tuple(self._state.messages),  # 只读视图（浅层包装）
        pending_tool_calls=tuple(self._state.pending_tool_calls),  # 只读视图
        usage=clone_usage(self._state.usage),  # 拷贝
    )
```

**逻辑差异**：
- messages：Cline `cloneMessages` 深拷贝消息数组（每条消息的 content 数组也拷贝），listener 修改不影响 runtime；Charles `tuple(...)` 只读视图，AgentMessage 对象仍是引用共享，listener 可修改 message.content 内部对象
- pending_tool_calls：Cline 浅拷贝数组，Charles tuple 只读视图
- usage：两边都拷贝

**影响**：
- Charles 的 tuple 只防 append/remove（`tuple.append` 会抛 AttributeError），不防 listener 修改 message.content 内部对象
- 理论上 listener 可执行 `event.snapshot.messages[0].content.append(...)` 修改 runtime 内部状态
- 实际影响小（listener 通常只读 snapshot，不修改）
- Cline 的深拷贝彻底隔离，但每次 snapshot 都有性能开销（cloneMessages 遍历整个消息数组）

**修复建议**：保持现状，功能等价。若需彻底隔离，可在 `snapshot()` 中用 `[copy.deepcopy(msg) for msg in self._state.messages]`，但性能开销大。

**优先级**：P3

---

### 差距 5：onEvent hook 缺失（对应对比项 7.18.4 关联）

**严重度**：P3（功能等价，抽象差异）

**Cline 实现**（L1656-1658）：
```typescript
for (const hook of this.hooks.onEvent) { await hook(event); }  // 7 钩子点之一
```

**Charles 实现**：无 `onEvent` hook（hooks.py 无此钩子点），事件只通过 `subscribe(listener)` 分发。

**逻辑差异**：
- Cline 有 7 个 hook 点（beforeRun / afterRun / beforeModel / afterModel / beforeTool / afterTool / onEvent），onEvent 在每个事件 emit 时触发
- Charles 6 个 hook 点（无 onEvent），事件通过 subscribe(listener) 等价覆盖

**影响**：
- Cline 的 onEvent hook 允许插件/hooks 在事件分发时插入逻辑（如日志、监控、过滤）
- Charles 通过 subscribe(listener) 等价覆盖（任何 hook 想监听事件都可以 subscribe）
- 功能等价，抽象差异：Cline 区分 hook（生命周期内嵌）和 listener（外部订阅），Charles 统一为 listener

**修复建议**：保持现状，subscribe 等价覆盖 onEvent 能力。

**优先级**：P3

---

### 差距 6：SSE 推送机制 — 三层适配 vs 单层直映射（对应 SSE 推送）

**严重度**：P3（架构差异，功能等价）

**Cline 实现**（三层适配）：
1. `RuntimeEventAdapter`（`runtime-event-adapter.ts` L172-401）：将 14 variant `AgentRuntimeEvent` 翻译为 9 类 legacy `AgentEvent`
2. `AgentEventBridge.dispatchAgentEvent`（`agent-event-bridge.ts` L42-76）：调用 `handleAgentEvent` 持久化消息 + 发射 `CoreSessionEvent`
3. `projectSessionEvent`（`session-event-projector.ts`）：将 `CoreSessionEvent` 投影为 `HubEventEnvelope` 发给前端

Cline SSE 事件类型：`content_start` / `content_end` / `iteration_start` / `iteration_end` / `usage` / `done` / `notice` / `error`

**Charles 实现**（单层直映射）：
- `server.py` L647-651：`on_event` 回调将 `AgentEvent` 放入 `event_queue`
- `server.py` L834-907：`_handle_event` 直接将 `AgentEvent` 映射为 SSE 字符串（`_sse_event`）
- 无中间 legacy 事件层

Charles SSE 事件类型：`token` / `tool_call` / `tool_output` / `error` / `phase` / `done` / `notice`

**逻辑差异**：
- 适配层数：Cline 三层（runtime event → legacy agent event → core session event → hub envelope），Charles 单层（runtime event → SSE）
- SSE 事件粒度：Cline 更细粒度（`content_start` / `content_end` 区分开始/结束），Charles 更扁平（`token` 缓冲批量发送）
- 事件抑制：Cline `RuntimeEventAdapter` 抑制 `run-started` / `message-added`（return `[]`，前端不可见），Charles 透传所有事件类型（`run-started` 在 `_handle_event` 中是 no-op，但事件本身仍进入 queue）
- 性能优化：Charles 的 `token` 缓冲 ≥3 字符批量发送（server.py L844-907），Cline 每个 delta 单独发 `content_start`

**影响**：
- Cline 三层适配保留 legacy 兼容（支持旧版前端协议），但增加复杂度
- Charles 单层直映射结构更简单，但与 Cline 前端协议不兼容
- Charles 的 token 缓冲是性能优化（减少 SSE 事件数量）

**修复建议**：保持现状，架构差异是设计选择。

**优先级**：P3

---

## 四、nanobot 残留专项检查

### 检查范围

P7.18 直接相关代码：
- `agent/events.py`（EventEmitter 类 + 事件类型常量 + AgentEvent dataclass + make_* 辅助函数）
- `agent/runtime.py` 的事件相关代码（`_emit` / `_make_emit_update` / `snapshot` / `_emitter` 字段 / `subscribe` 透传）
- `agent/server.py` 的 SSE 相关代码（L647-651 `on_event` + L834-907 `_handle_event` + L218-238 `_sse_event` + L986-1024 `/api/chat/stream` 端点）
- `agent/types.py` 的 `AgentRuntimeStateSnapshot` / `CompactionStateSnapshot` / `AgentRunResult` 数据类

P7.18 间接相关代码（涉及事件但非核心）：
- `agent/connectors.py`（ConnectorEvent 数据类 + ConnectorManager 事件派发 — 独立于 AgentRuntime 事件系统）
- `agent/file_hooks/`（file hook 事件 — 独立于 AgentRuntime 事件系统）
- `agent/hooks.py`（hook 系统 — Phase 2.10 范围）

### 检查结果

| 文件 | nanobot 残留类型 | 残留数量 | 残留位置 | 影响评估 |
|------|----------------|---------|---------|---------|
| `agent/events.py` | 注释残留 | 0 处 | — | 无（全部注释对标 Cline agent-runtime.ts / agent.ts，如 L29 "对标 Cline AgentRuntimeEvent 的 type 字段"、L47 "对标 Cline assistant-message"、L53 "对标 Cline tool-updated"、L60 "对标 Cline emitStatusNotice 的 compaction 事件"、L65 "对标 Cline compaction-failed"、L125 "对标 Cline AgentRuntime._emitter"、L145 "对标 Cline AgentRuntime.on()"、L169 "对标 Cline AgentRuntime.emit()"、L255 "对标 Cline agent-runtime.ts L927-933"、L275 "对标 Cline agent-runtime.ts L954-962"、L305 "对标 Cline agent-runtime.ts L665-671"、L327 "对标 Cline agent-runtime.ts L1498-1506"） |
| `agent/events.py` | 实现逻辑残留 | 0 处 | — | 无（EventEmitter 类完全对标 Cline agent-runtime.ts L399 + L471-476 + L1605-1659，无 nanobot 逻辑） |
| `agent/runtime.py`（事件相关） | 注释残留 | 0 处 | — | 无（L373 "对标 Cline AgentRuntime.on()"、L2147-2149 `_emit` 透传，全部对标 Cline） |
| `agent/runtime.py`（事件相关） | 实现逻辑残留 | 0 处 | — | 无（`_emit` / `_make_emit_update` / `snapshot` / `subscribe` 完全对标 Cline） |
| `agent/server.py`（SSE 相关 L647-651 / L834-907 / L218-238 / L986-1024） | 注释残留 | 0 处 | — | SSE 相关代码无 nanobot 注释（L653 "对标 Cline 的实时事件推送机制" 明确说明是 Charles 增强） |
| `agent/server.py`（SSE 相关） | 实现逻辑残留 | 0 处 | — | SSE 映射完全基于 Charles 自有协议（`_sse_event` / `_handle_event`），无 nanobot 逻辑 |
| `agent/types.py`（AgentRuntimeStateSnapshot / CompactionStateSnapshot / AgentRunResult） | 注释残留 | 0 处 | — | 无（L375 "对标 Cline AgentRuntimeStateSnapshot"、L379 "对标 Cline readonly AgentMessage[]"、L403 "对标 Cline CompactionStateManager.project()"、L426 "对标 Cline AgentRunResult"） |
| `agent/types.py` | 实现逻辑残留 | 0 处 | — | 无 |

### 间接相关文件的 nanobot 注释残留（与事件系统功能无关）

| 文件 | nanobot 注释残留位置 | 残留类型 | 与事件系统关系 |
|------|---------------------|---------|--------------|
| `agent/server.py` | L2/L4/L28（模块级 docstring "对标 Cline server + nanobot routes/chat.py"） | 注释残留（类型 A：实现来源标注） | 与事件系统无关（属 P7.1 范围已审计，标注的是 SSE 端点设计来源，事件系统实现在 L647-651 / L834-907 完全对标 Cline + Charles 自有协议） |
| `agent/connectors.py` | 无 nanobot 残留（L117 "对标 Cline ConnectorHookEvent"） | 无 | 无 |
| `agent/file_hooks/` | 无 nanobot 残留 | 无 | 无（file hook 事件独立于 AgentRuntime 事件系统） |
| `agent/hooks.py` | 无 nanobot 残留 | 无 | 无（hook 系统属 Phase 2.10 范围） |

### nanobot 残留结论

- **P7.18 直接相关代码（events.py + runtime.py 事件相关 + server.py SSE 相关 + types.py 数据类）**：**0 处注释残留 + 0 处实现逻辑残留**。事件系统的实现完全对标 Cline agent-runtime.ts + agent.ts，无 nanobot 逻辑残留。
- **间接相关文件的 nanobot 注释残留**：仅 `agent/server.py` 模块级 docstring（L2/L4/L28）有 3 处 nanobot 注释残留（"对标 Cline server + nanobot routes/chat.py"），属 P7.1 范围已审计，与事件系统功能无关。
- **建议**：事件系统无需任何 nanobot 清理。间接相关文件的注释残留由 P7.1 统一清理。

---

## 五、修复优先级清单

### P2（次要）

1. **7.18.1 事件名串对齐（可选）**：若未来需与 Cline 前端兼容，可将 Charles `events.py` L51-52 的 `TOOL_EXECUTION_STARTED = "tool-execution-started"` / `TOOL_EXECUTION_FINISHED = "tool-execution-finished"` 改为 `TOOL_STARTED = "tool-started"` / `TOOL_FINISHED = "tool-finished"` 对齐 Cline agent.ts L505/L518。当前 Charles 前端已适配 `tool-execution-*` 命名，保持现状亦可。

### P3（锦上添花）

1. **7.18.4 telemetry / logger 集成**：Charles `emit`（events.py L168-187）内可根据 event.type 分发 logger（run-started/run-finished 用 info，run-failed 用 error）+ telemetry.capture，对齐 Cline L1605-1648。待 Phase Z telemetry 系统补齐后实施。
2. **7.18.5 listener 异常处理**：Charles 已显式隔离 listener 异常（L179-187 / L211-221），无需修改。Cline 的契约约束是 TS 生态惯例，Charles 的显式隔离是 Python 生态惯例，两者各有利弊。
3. **7.18.7 snapshot 深拷贝（可选）**：若需彻底隔离 listener 与 runtime 状态，可在 `runtime.py` `snapshot()` L425-443 中用 `[copy.deepcopy(msg) for msg in self._state.messages]` 替代 `tuple(self._state.messages)`，但性能开销大。当前 tuple 只读视图在实际使用中无 bug（listener 通常只读 snapshot），保持现状亦可。
4. **7.18.4 onEvent hook（可选）**：若需对齐 Cline 7 钩子点，可在 `agent/hooks.py` 添加 `onEvent` 钩子点，在 `events.py` `emit` 内调用。当前 Charles 通过 subscribe(listener) 等价覆盖 onEvent 能力，保持现状亦可。
5. **7.18.1 COMPACTION 事件统一（可选）**：Charles 的 5 个 COMPACTION 事件常量（events.py L61-66）可改为复用 `STATUS_NOTICE` + `metadata.reason` 表达，对齐 Cline `runtime-event-adapter.ts` L236-246 的 `resolveStatusNoticeReason` 模式。但 Charles 的独立事件类型提供了更好的类型安全性，保持现状亦可。

---

## 六、阶段结论

**P7.18 事件系统对比对齐度约 85%**。核心机制（事件类型枚举 / AgentEvent 字段 / subscribe 返回 unsubscribe / 事件顺序保证 / run_failed vs run_finished 互斥）基本对齐。主要差距集中在五点：

1. **事件名串不一致**（7.18.1）— Cline `tool-started` / `tool-finished`，Charles `tool-execution-started` / `tool-execution-finished`（多 `execution-` 中缀）。Charles 前端已适配，保持现状。
2. **emit 同步 vs 异步**（7.18.4）— 两边 emit 都是 async（计划标注"同步"错误），Charles 多 `emit_sync` 通道 + 自动 await async listener + 无 telemetry/logger 集成。
3. **listener 异常处理**（7.18.5）— Cline 无 try/catch（契约约束），Charles 显式隔离（更健壮）。
4. **snapshot 引用语义**（7.18.7）— Cline 深拷贝彻底隔离，Charles tuple 只读视图引用共享。
5. **SSE 推送机制**（关联）— Cline 三层适配 + 细粒度 SSE 事件，Charles 单层直映射 + 扁平 SSE 事件 + token 缓冲优化。

Charles 的 `emit_sync` 是 Python asyncio 适配的合理增强（解决 task 调度延迟问题），`unsubscribe_all()` / `listener_count` 是便利性增强。Charles 的 5 个 COMPACTION 事件常量是类型安全性增强（Cline 复用 `status-notice`）。Charles 的 token 缓冲批量发送是性能优化。

nanobot 残留检查结论：**P7.18 直接相关代码 0 处残留**，事件系统完全对标 Cline。间接相关文件仅 `agent/server.py` 模块级 docstring 有 3 处 nanobot 注释残留（类型 A：实现来源标注），属 P7.1 范围已审计，与事件系统功能无关。
