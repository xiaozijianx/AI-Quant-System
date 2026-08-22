# Phase 7.17 Turn Queue 对比

> 对比范围：Cline `sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` 的 `PendingPromptEntry` / `PendingPromptQueueState` / `PendingPromptService` / `PendingPromptsController`（含 `enqueue` / `consumeSteer` / `shiftNext` / `requeueFront` / `update` / `delete` / `clear` / `list` 纯逻辑 + `scheduleDrain` / `drain` 调度 + `emitPrompts` / `emitSubmitted` 事件）+ Cline `agent-runtime.ts` L841-852 `consumePendingUserMessage` 回调点 + Cline `local-runtime-host.ts` L640-648 回调注入 + L928-930 `queueMicrotask(drain)` 触发；对比 Charles `agent/turn_queue.py` 的 `PendingPromptEntry` / `PendingPromptQueueState` dataclass + `snapshot_prompt` / `snapshot_prompts` + `PendingPromptService` 类 + `PendingPromptsController` 类（含 `_schedule_drain` / `_drain` / `consume_steer` / `clear_aborted`）+ `agent/runtime.py` L855-882 `consume_pending_user_message` 回调集成 + `agent/server.py` L94-161 `_get_turn_queue_controller` 依赖注入（`send_callback` 空操作）+ L308-339 `_make_consume_pending_user_message_callback` 回调构造 + L760-829 `_sse_generator` 末尾 queue 消费循环 + L984-1051 `/stream` 入队入口 + L1145-1213 REST 端点 + L1250-1256 `/abort` 清空队列 + `static/js/ai-chat.js` 前端事件处理；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` L14-23（`PendingPromptDelivery` 类型 + `PendingPromptEntry` 接口）+ L25-27（`PendingPromptQueueState`）+ L29-52（依赖接口 + 输入/输出接口）+ L54-205（`PendingPromptService` 类：list/update/delete/enqueue/consumeSteer/shiftNext/requeueFront/clear）+ L207-352（`PendingPromptsController` 类：list/update/delete/enqueue/consumeSteer/clearAborted/emitPrompts/scheduleDrain/drain/emitSubmitted）+ L354-385（snapshotPrompt/snapshotPrompts/insertUpdatedPrompt 辅助函数）
> - `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L841-852（`iteration > 1` 时调用 `consumePendingUserMessage` 回调）+ L1252-1267（回调实现）
> - `third_party/cline/sdk/packages/core/src/extensions/host/local/local-runtime-host.ts` L640-648（`consumePendingUserMessage` 回调注入 `consumeSteer` + `formatModePrompt`）+ L928-930（`runTurn` 完成后 `queueMicrotask(() => void this.pendingPromptsController.drain(sessionId))`）
>
> Charles 源码：
> - `agent/turn_queue.py` L1-639（完整模块：`_generate_prompt_id` L46-48 + `PendingPromptEntry` dataclass L51-71 + `PendingPromptQueueState` dataclass L74-82 + `snapshot_prompt` L85-98 + `snapshot_prompts` L101-103 + `PendingPromptService` 类 L111-328 + `PendingPromptsController` 类 L344-611 + 模块级单例 L619-639）
> - `agent/runtime.py` L855-882（`iteration > 1` 时调 `consume_pending_user_message` 回调 + 追加到 state.messages/request.messages + emit message_added）
> - `agent/server.py` L89-161（`_turn_queue_controller` 延迟初始化 + `_get_turn_queue_controller` 注入 `session_status_query` / `send_callback`（空操作）/ `emit_callback`（仅日志））+ L308-339（`_make_consume_pending_user_message_callback` 构造 steer 消费回调）+ L760-829（`_sse_generator` 末尾 while 循环消费 queue 条目）+ L984-1051（`/stream` 入口检查活跃 runtime 后入队）+ L1145-1213（GET/DELETE/PUT `/pending_prompts` REST 端点）+ L1250-1256（`/abort` 端点调 `clear_aborted`）
> - `agent/types.py` L557（`AgentRuntimeConfig.consume_pending_user_message` 字段定义）
> - `static/js/ai-chat.js` L518-559（`_enqueueMessage` 前端入队）+ L647-661（SSE 事件分发：pending_prompts / pending_prompt_submitted / pending_prompts_drained / pending_prompts_updated）+ L697-（UI 处理）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Turn Queue 机制（用户输入排队、队列管理、并发控制、SSE 事件通知）。**核心结论：计划文件 P7.17 列出的 8 项对比项中 5 项已强对齐（PendingPromptEntry 字段 / delivery 枚举 / enqueue 入队 / consume 消费 / consume_for_steer），2 项 Charles 简化（queue 自动启动新 run + 状态持久化），1 项弱对齐（SSE 事件通知 — 入队事件类型不同）。**

### 计划文件核实结果

AGENT_COMPARISON_PLAN_V2.md L2929-2938 的 P7.17 对比表标注 7.17.1-7.17.5 + 7.17.8 全部"已对齐"，7.17.6 / 7.17.7 标注"Charles 简化"。经源码核实：

| 计划项 | 计划标注 | 实际核实 | 一致性 |
|--------|---------|---------|--------|
| 7.17.1 PendingPromptEntry 字段 | 已对齐 | Cline L16-23 interface（id/prompt/mode?/delivery/userImages?/userFiles?）；Charles L51-71 dataclass（id/prompt/mode/delivery/user_images/user_files）字段一一对应，仅命名风格差异（camelCase vs snake_case） | 高 |
| 7.17.2 delivery 枚举 | 已对齐（Stage 30.1） | Cline L14 `type PendingPromptDelivery = "queue" \| "steer"`（字面量联合类型，编译期校验）；Charles L69 `delivery: str = "queue"`（str 无枚举校验，运行时分支判断） | 高（语义等价，类型校验弱） |
| 7.17.3 enqueue 入队 | 已对齐 | Cline L137-175 splice + unshift/push；Charles L122-195 pop + insert(0)/append，逻辑完全对齐（同 prompt 合并、steer 队首、queue 队尾、steer+queue 升级为 steer） | 高 |
| 7.17.4 consume 消费 | 已对齐 | Cline L188-191 `shiftNext` + L295-335 `drain` 协程；Charles L219-230 `shift_next` + L553-611 `_drain` 协程 + `server.py` L760-829 `_sse_generator` 末尾循环。**消费语义对齐，但触发方式不同**（见 7.17.6） | 高（语义对齐） |
| 7.17.5 consume_for_steer | 已对齐 | Cline `agent-runtime.ts` L841-852 + `local-runtime-host.ts` L640-648；Charles `runtime.py` L855-882 + `server.py` L308-339。**两者都在 iteration > 1 时调回调取 steer**，但 Charles 不包裹 `<user_input mode="...">` 标签（裸文本），Cline 通过 `formatModePrompt` 包裹 | 中-高（语义对齐，文本格式不同） |
| 7.17.6 queue 自动启动新 run | Charles 简化 | Cline L928-930 `queueMicrotask(drain)` + L311 `await this.deps.send()` 真实启动新 run（独立于 SSE 连接）；Charles `send_callback` 实现为**空操作**（L125-146），真实消费由 `_sse_generator` 末尾 while 循环在原 SSE 连接上完成（L760-829） | 中（Charles 简化，SSE 断开后队列残留） |
| 7.17.7 状态持久化 | Charles 简化 | Cline 队列状态存于 `ActiveSession.pendingPrompts`（session.ts L35），与 session 生命周期绑定，session 持久化时队列随之持久化；Charles 队列状态存于 `PendingPromptsController._states: dict[str, PendingPromptQueueState]`（turn_queue.py L370），**纯内存**，服务重启后丢失 | 中（Charles 简化） |
| 7.17.8 SSE 事件通知 | 已对齐 | Cline L271-279 `emitPrompts` 发 `pending_prompts` + L337-351 `emitSubmitted` 发 `pending_prompt_submitted`；Charles 入队时发 `pending_prompts_updated`（含 queued_message + delivery，server.py L1026-1031），消费时发 `pending_prompts` + `pending_prompt_submitted`（L781-790）。**入队事件类型不同** | 中（消费事件对齐，入队事件不同） |

### 核心结论

1. **PendingPromptEntry 数据结构完整对齐**：双方都实现了 id/prompt/mode/delivery/user_images/user_files 六字段，仅命名风格差异（Cline TypeScript interface + camelCase；Charles Python dataclass + snake_case）。Charles 字段默认值更明确（mode=None, delivery="queue", user_images/user_files=default_factory=list）。
2. **delivery 枚举语义等价**：Cline 用 TypeScript 字面量联合类型 `"queue" | "steer"`（编译期校验），Charles 用 `str` 无枚举校验（运行时通过 `if delivery == "steer"` 分支处理）。运行时行为一致，但 Charles 缺少类型校验（理论上可传入非法值，但 server.py L1008-1009 在入口处校验 `if delivery not in ("queue", "steer"): delivery = "queue"`）。
3. **enqueue 入队逻辑完全对齐**：① 同 prompt 已存在时合并更新（Cline splice + Charles pop）② steer 放队首（unshift/insert(0)）③ queue 放队尾（push/append）④ steer + queue 合并时升级为 steer。ID 生成格式均为 `pending_<timestamp>_<rand>`（Cline 用 `Date.now()` + `nanoid(5)`，Charles 用 `int(time.time() * 1000)` + `uuid.uuid4().hex[:5]`）。
4. **consume 消费语义对齐但触发方式不同**：Cline 的 `drain()` 协程通过 `send_callback` 真实启动新 run（`runTurn`），由 `queueMicrotask` 自动调度，drain 独立于 SSE 连接；Charles 的 `_schedule_drain` 在 run 运行中因 `can_start_run=False` 跳过，run 结束后由 `_sse_generator` 末尾 while 循环接管消费，`send_callback` 空操作。Charles SSE 断开后队列无法自动消费。
5. **consume_for_steer 时机对齐但文本格式不同**：两者都在 `iteration > 1` 时调用回调取 steer 消息追加到 model request。Cline 通过 `formatModePrompt` 把 steer prompt 包裹为 `<user_input mode="...">...</user_input>`；Charles 直接返回 `entry.prompt` 裸文本，runtime 创建 message 时不包裹 mode 标签（但 queue 类型消息在 _sse_generator L813 会包裹 `<user_input mode="...">`）。
6. **drain 重入保护数据结构差异**：Cline 用 `session.drainingPendingPrompts: boolean` 单标志；Charles 用 `_draining: set[str]` 集合 + `_drain_tasks: dict[str, asyncio.Task]` 双结构（额外的 task 引用防止 GC，因为 Python `asyncio.create_task` 未持有引用的 Task 可能被回收）。
7. **状态持久化差异**：Cline 队列状态与 ActiveSession 绑定，session 持久化时队列随之持久化；Charles 队列状态由 controller 单例持有，纯内存，服务重启后丢失。
8. **SSE 事件命名差异**：Cline 入队和消费都发 `pending_prompts` 事件；Charles 入队发 `pending_prompts_updated`（含 queued_message + delivery 字段），消费发 `pending_prompts` + `pending_prompt_submitted`。前端需监听两个不同事件类型。
9. **REST 端点完整对齐**：Charles 实现了 GET（list）/ DELETE（delete）/ PUT（update）/ DELETE-all（clear）四个端点，与 Cline hub API 等价。
10. **abort 时清空队列对齐**：Cline `clearAborted`（L265-269）在 session.aborting 时清空；Charles `/abort` 端点（L1250-1256）调用 `controller.clear_aborted` 清空。
11. **nanobot 残留**：P7.17 直接相关代码（`turn_queue.py` + `runtime.py` consume_pending_user_message 分支 + `server.py` turn queue 端点 + `types.py` consume_pending_user_message 字段）共 **0 处注释残留 + 0 处实现逻辑残留**。间接相关的 `server.py` 文件头有 3 处 nanobot 注释残留（L2/L4/L28，类型 A：实现来源标注），**全部为注释残留**，**未发现实现逻辑残留**。

### 一致性总体评估

- **PendingPromptEntry 字段**：**高**。双方六字段一一对应。
- **delivery 枚举**：**高**。语义等价，类型校验方式不同。
- **enqueue 入队**：**高**。合并/插队/升级逻辑完全对齐。
- **consume 消费**：**高**（语义对齐）。drain 触发方式不同但消费语义一致。
- **consume_for_steer**：**中-高**。时机对齐，文本格式不同（Cline 包裹 mode 标签，Charles 裸文本）。
- **queue 自动启动新 run**：**中**。Charles 简化为 SSE 连接内消费，SSE 断开后队列残留。
- **状态持久化**：**中**。Charles 简化为纯内存，服务重启丢失。
- **SSE 事件通知**：**中**。消费事件对齐，入队事件类型不同。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.17.1 | PendingPromptEntry 字段 | `pending-prompt-service.ts` L16-23 interface：`id: string` / `prompt: string` / `mode?: AgentMode` / `delivery: PendingPromptDelivery` / `userImages?: string[]` / `userFiles?: string[]` | `turn_queue.py` L51-71 dataclass：`id: str` / `prompt: str` / `mode: str \| None = None` / `delivery: str = "queue"` / `user_images: list[str] = field(default_factory=list)` / `user_files: list[str] = field(default_factory=list)` | 高 | 字段完整对齐。差异：(a) Cline interface + camelCase，Charles dataclass + snake_case；(b) Charles 字段默认值更明确（mode=None / delivery="queue" / user_images/user_files=default_factory=list），Cline 用可选属性（`?`）默认 undefined；(c) Charles dataclass 不可变约束弱（无 frozen=True），但实际通过 snapshot 机制对外隔离 |
| 7.17.2 | delivery 枚举 | L14 `export type PendingPromptDelivery = "queue" \| "steer"`（TypeScript 字面量联合类型，编译期校验非法值） | `turn_queue.py` L69 `delivery: str = "queue"`（str 无枚举校验）；`server.py` L1008-1009 入口校验 `if delivery not in ("queue", "steer"): delivery = "queue"` | 高 | 语义等价。差异：(a) Cline 编译期类型校验，Charles 运行时入口校验；(b) Charles 在 `enqueue` 内通过 `if delivery == "steer"` 分支处理（L190/L168），无非法值兜底（但入口已校验）；(c) Charles 缺少 `PendingPromptDelivery` 类型别名 |
| 7.17.3 | enqueue 入队 | L137-175 `enqueue(state, input)`：① `findIndex` 查同 prompt ② splice 移除已存在 ③ 合并 delivery（`delivery === "steer" \|\| existing.delivery === "steer"` 升级为 steer）④ unshift（steer）/ push（queue）⑤ 新建条目 `id: pending_${Date.now()}_${nanoid(5)}` | `turn_queue.py` L122-195 `enqueue(state, prompt, mode, delivery, user_images, user_files)`：① `enumerate` 查同 prompt ② pop 移除已存在 ③ 合并 delivery（`"steer" if (delivery == "steer" or existing.delivery == "steer") else "queue"`）④ insert(0)（steer）/ append（queue）⑤ 新建条目 `id: pending_{int(time.time()*1000)}_{uuid.uuid4().hex[:5]}` | 高 | 完全对齐。差异：(a) 查找方式 — Cline `findIndex` O(n)，Charles `enumerate` O(n)；(b) 移除方式 — Cline `splice` 原地，Charles `pop` 取出后重新插入；(c) ID 生成 — Cline `Date.now()` 毫秒时间戳 + `nanoid(5)` 21 字符 base64，Charles `int(time.time()*1000)` 毫秒时间戳 + `uuid4().hex[:5]` 5 字符 hex；(d) Charles 额外 `prompt.strip()` 去空白 + `if not prompt: raise ValueError` 空检查（L150-152） |
| 7.17.4 | consume 消费 | L188-191 `shiftNext(state)`：`state.pendingPrompts.shift()` 取出队首 + `snapshotPrompts`；L295-335 `drain(sessionId)` 协程：① 检查 aborting/draining/canStartRun ② shiftNext ③ emitPrompts + emitSubmitted ④ `session.drainingPendingPrompts = true` ⑤ `await this.deps.send({...})` 真实启动新 run ⑥ catch 时 requeueFront + emitPrompts ⑦ finally 重置 drainingPendingPrompts，队列非空时 queueMicrotask 继续 drain | `turn_queue.py` L219-230 `shift_next(state)`：`state.pending_prompts.pop(0)` 取出队首 + `snapshot_prompts`；L553-611 `_drain(session_id)` 协程：① 检查 aborting/draining/can_start_run ② shift_next ③ emit_prompts + emit_submitted ④ `_draining.add(session_id)` ⑤ `await send_callback(...)` **空操作** ⑥ except 时 requeue_front + emit_prompts ⑦ finally `_draining.discard` + `_drain_tasks.pop`，队列非空时 `_schedule_drain` 继续；**实际消费由 `server.py` L760-829 `_sse_generator` 末尾 while 循环接管** | 高（语义对齐） | 消费语义对齐。差异：(a) drain 触发 — Cline `queueMicrotask` 自动调度，Charles `_schedule_drain` 在 run 运行中因 can_start_run=False 跳过，run 结束后由 `_sse_generator` 末尾循环接管；(b) send_callback — Cline 真实启动新 run（runTurn），Charles 空操作；(c) 重入保护 — Cline `session.drainingPendingPrompts: boolean` 单标志，Charles `_draining: set[str]` + `_drain_tasks: dict[str, asyncio.Task]` 双结构；(d) Charles `_drain` 内的 shift_next + send 与 `_sse_generator` 内的 shift_next + `_run_once` 存在重复消费风险（但 send_callback 空操作，实际不启动新 run，无重复） |
| 7.17.5 | consume_for_steer | `agent-runtime.ts` L841-852：`if (this.state.iteration > 1 && this.config.consumePendingUserMessage) { const pendingUserMessage = await this.config.consumePendingUserMessage(); if (pendingUserMessage) { this.state.messages.push(message); request.messages = [...request.messages, ...cloneMessages([pendingUserMessage])]; emit message-added } }`；`local-runtime-host.ts` L640-648：回调内 `consumeSteer(sessionId)` + `formatModePrompt(entry.prompt, entry.mode ?? configWithProvider.mode)` 包裹 `<user_input mode="...">` | `runtime.py` L855-882：`if (self._state.iteration > 1 and self.config.consume_pending_user_message is not None) { pending_text = await self.config.consume_pending_user_message(session_id); if pending_text: { pending_msg = create_message(USER, [TextPart(text=pending_text)]); self._state.messages.append(pending_msg); request.messages = list(request.messages) + [pending_msg]; emit make_message_added } }`；`server.py` L322-337 `_consume`：`entry = controller.consume_steer(sid); return entry.prompt`（**裸文本，不包裹 mode 标签**） | 中-高 | 时机对齐。差异：(a) 回调签名 — Cline `() => string \| undefined`（无参），Charles `(session_id) -> str \| None`（有参，防御性用 arg）；(b) 文本格式 — Cline 通过 `formatModePrompt` 包裹 `<user_input mode="act">...</user_input>`，Charles 直接返回 `entry.prompt` 裸文本；(c) 异常处理 — Cline 无 try/catch（异常会冒泡），Charles 在 `_consume` 内 try/except 返回 None（L335-337）+ runtime.py L859-865 二次 try/except；(d) 消息克隆 — Cline `cloneMessages` 深拷贝，Charles `list(request.messages) + [pending_msg]` 浅拷贝 |
| 7.17.6 | queue 自动启动新 run | `local-runtime-host.ts` L928-930：`runTurn` 完成后 `queueMicrotask(() => void this.pendingPromptsController.drain(input.sessionId))`；`drain` L311 `await this.deps.send({sessionId, prompt, mode, userImages, userFiles})` 真实启动新 run（send 回调注入为 `this.runTurn`），事件通过 `onEvent` 回调独立推送，与原请求 SSE 连接解耦 | `server.py` L760-829 `_sse_generator` 末尾 while 循环：① `controller._states.get(session_id)` 取队列状态 ② 队列空 → break ③ `shift_next` 取队首 ④ steer 类型 → requeue_front + break（防御性）⑤ yield pending_prompts + pending_prompt_submitted SSE 事件 ⑥ 若 mode 变化 → set_mode + 重建系统提示 ⑦ `async for sse in _run_once(entry.prompt, queued_messages, run_system_prompt): yield sse` 启动新 run ⑧ except 时 requeue_front + break；`send_callback`（L125-146）实现为**空操作**，仅记录日志 | 中（Charles 简化） | 关键差异：(a) drain 调度 — Cline `queueMicrotask` 异步微任务独立调度，Charles SSE 生成器内 while 循环同步串行；(b) send_callback — Cline 真实启动新 run（runTurn），Charles 空操作（真实消费由 `_sse_generator` 末尾循环完成）；(c) 事件推送通道 — Cline 独立 onEvent 回调 → hub，Charles 原 SSE 连接 yield；(d) SSE 断开影响 — Cline 不影响 drain，新 run 事件通过 hub 推送，Charles drain 中断，队列残留；(e) Charles 优势 — 单一 SSE 连接内闭环消费，事件时序清晰，无需 hub 中转 |
| 7.17.7 | 状态持久化 | 队列状态存于 `ActiveSession.pendingPrompts: PendingPrompt[]`（session.ts L35），与 session 生命周期绑定；`local-runtime-host.ts` L753 创建 session 时 `pendingPrompts: []` 初始化；session 持久化时队列随之持久化（通过 session snapshot/restore） | `turn_queue.py` L370 `self._states: dict[str, PendingPromptQueueState]`（PendingPromptsController 实例属性，纯内存）；L376-380 `get_state(session_id)` 懒初始化；server.py L91 `_turn_queue_controller: Any = None` 模块级单例，服务重启后丢失；**无持久化机制** | 中（Charles 简化） | 差异：(a) 存储位置 — Cline ActiveSession.pendingPrompts（session 内聚），Charles PendingPromptsController._states（controller 单例持有，session 解耦）；(b) 持久化 — Cline 随 session 持久化，Charles 纯内存；(c) 生命周期 — Cline 队列与 session 同生命周期，Charles 需显式 `clear(session_id)` 清理（L479-487）；(d) 影响 — Charles 服务重启后排队消息丢失，Cline 可恢复 |
| 7.17.8 | SSE 事件通知 | L271-279 `emitPrompts(session)` 发 `pending_prompts` 事件（含 sessionId + prompts snapshot）；L337-351 `emitSubmitted(session, entry)` 发 `pending_prompt_submitted` 事件（含 sessionId + id + prompt + delivery + attachmentCount + userImages + userFiles）；入队时 `enqueue` L251 `emitPrompts` 发 `pending_prompts`（与消费同事件类型）；消费时 `drain` L306-307 emitPrompts + emitSubmitted | `server.py` L1026-1031 入队时 `_sse_event("pending_prompts_updated", {session_id, prompts, queued_message, delivery})` + `done` with reason=queued；L781-790 消费时 `yield _sse_event("pending_prompts", {session_id, prompts})` + `yield _sse_event("pending_prompt_submitted", {session_id, id, prompt, delivery})`；turn_queue.py L489-499 `_emit_prompts` 发 `pending_prompts`（通过 emit_callback，但 server.py L148-154 emit_callback 为空操作，仅日志）；L501-517 `_emit_submitted` 发 `pending_prompt_submitted`（同样空操作） | 中（消费事件对齐，入队事件不同） | 差异：(a) 入队事件类型 — Cline `pending_prompts`（与消费同），Charles `pending_prompts_updated`（含 queued_message + delivery 字段）；(b) 消费事件类型 — 两者均发 `pending_prompts` + `pending_prompt_submitted`；(c) 事件发射通道 — Cline 通过 `deps.emit(event)` → hub 推送，Charles 在 `_sse_generator` 内直接 yield（controller 的 emit_callback 为空操作）；(d) 字段命名 — Cline `attachmentCount` camelCase，Charles `attachment_count` snake_case（但 server.py L781-790 的 SSE 事件不含 attachment_count 字段）；(e) 前端处理 — `ai-chat.js` L647-661 监听 `pending_prompts` / `pending_prompt_submitted` / `pending_prompts_drained` / `pending_prompts_updated` 四种事件 |

---

## 三、重点差距详解

### 差距 1：drain 触发方式与 send_callback 角色（对应对比项 7.17.4、7.17.6）

**严重度**：P2（影响 SSE 断开后队列消费）

**Cline 设计**（`pending-prompt-service.ts` L281-335 + `local-runtime-host.ts` L928-930）：

```
runTurn 完成
  → queueMicrotask(() => void pendingPromptsController.drain(sessionId))
  → drain() 内：
      ① 检查 session.aborting / drainingPendingPrompts / canStartRun
      ② shiftNext 取出队首
      ③ emitPrompts + emitSubmitted
      ④ session.drainingPendingPrompts = true
      ⑤ await this.deps.send({sessionId, prompt, mode, userImages, userFiles})  ← 真实启动新 run
      ⑥ catch 时 requeueFront + emitPrompts
      ⑦ finally 重置 drainingPendingPrompts，队列非空时 queueMicrotask 继续 drain
```

`send` 回调由 `local-runtime-host.ts` L279 注入为 `this.runTurn(input)`，即 drain 内部启动新 run，run 的事件通过 `onEvent` 回调（L651-656）独立推送到 hub，与原请求的 SSE 连接解耦。

**Charles 设计**（`server.py` L94-161 + L760-829）：

```
run 结束（_sse_generator 内 _run_once 完成）
  → while True 循环：
      ① controller._states.get(session_id) 取队列状态
      ② 队列空 → break
      ③ shift_next 取出队首
      ④ 队首是 steer → requeue_front + break（防御性，steer 应已被 iteration 消费）
      ⑤ yield pending_prompts + pending_prompt_submitted SSE 事件
      ⑥ 若 entry.mode 变化 → set_mode + 重建系统提示
      ⑦ async for sse in _run_once(entry.prompt, queued_messages, run_system_prompt): yield sse  ← 启动新 run
      ⑧ except 时 requeue_front + break
```

`send_callback`（L125-146）实现为**空操作**，仅记录日志：

```python
async def send_callback(session_id, prompt, mode, user_images, user_files) -> None:
    logger.info(
        "turn_queue: drain session=%s prompt=%d字符（由 _sse_generator 末尾循环消费）",
        session_id, len(prompt),
    )
    # 不抛异常，让 controller 认为发送成功，继续 drain 下一条
    # 真正的 run 由 _sse_generator 末尾循环启动
```

**差异分析**：

| 维度 | Cline | Charles |
|------|-------|---------|
| drain 调度 | `queueMicrotask` 异步微任务 | SSE 生成器内 while 循环（同步串行） |
| send_callback | 真实启动新 run（`runTurn`） | 空操作（仅日志） |
| 事件推送通道 | 独立 onEvent 回调 → hub | 原 SSE 连接 yield |
| SSE 断开影响 | 不影响 drain，新 run 事件通过 hub 推送 | drain 中断，队列残留 |
| drain 重入保护 | `session.drainingPendingPrompts: boolean` | `_draining: set[str]` + `_drain_tasks: dict[str, asyncio.Task]` |

**影响**：Charles 的设计在 SSE 连接稳定时工作正常，但若客户端断开重连，原 SSE 生成器会被取消，未消费的 queue 条目会滞留在内存队列中，需用户重新发消息触发新的 `/stream` 请求才能消费（但 `/stream` 入口会先检查 `_active_runtimes`，若 runtime 已结束则直接启动新 run，不会消费残留队列）。Cline 的 drain 与 SSE 连接解耦，hub 持有 session 状态，新连接可继续接收事件。

**Charles 的优势**：在单一 SSE 连接内闭环消费，事件时序清晰（同一连接按顺序推送），无需 hub 中转。Cline 的 drain 启动的新 run 事件可能跨多个 SSE 连接推送，前端需按 sessionId 关联。

**修复建议**：保持现状，功能等价。若需提升 SSE 断开后鲁棒性，可将 `send_callback` 改为真实启动新 run（需引入事件中转通道），但涉及 SSE 架构调整，风险较高。

**优先级**：P2

---

### 差距 2：steer 消息文本是否包裹 mode 标签（对应对比项 7.17.5）

**严重度**：P3（功能等价，LLM 上下文略有差异）

**Cline 设计**（`local-runtime-host.ts` L640-648）：

```typescript
consumePendingUserMessage: () => {
    const entry = this.pendingPromptsController.consumeSteer(sessionId);
    return entry
        ? formatModePrompt(entry.prompt, entry.mode ?? configWithProvider.mode)
        : undefined;
},
```

`formatModePrompt` 内部调用 `formatUserInputBlock`，把 prompt 包裹为 `<user_input mode="act">...</user_input>` 格式。runtime 的 `consumePendingUserMessage`（`agent-runtime.ts` L1257）拿到的是已包裹的字符串，创建 message 后 push 到 state.messages。

**Charles 设计**（`server.py` L322-337 + `runtime.py` L871-873）：

```python
async def _consume(session_id_arg: str) -> str | None:
    controller = _get_turn_queue_controller()
    entry = controller.consume_steer(sid)
    if entry is None:
        return None
    return entry.prompt  # 原始文本，未包裹

# runtime.py L871-873
pending_msg = create_message(
    MessageRole.USER, [TextPart(text=pending_text)],
)
```

Charles 的回调直接返回 `entry.prompt` 原始文本，runtime 创建 message 时不包裹 mode 标签。

**影响**：steer 消息进入 model request 时，Cline 的消息含 `<user_input mode="act">` 包裹，LLM 能看到 mode 上下文；Charles 的消息是裸文本，LLM 不知道当前 mode。但实际上 Charles 的 steer 消息通常用于补充指令（如"再分析一下 X 股票"），mode 上下文已在 system prompt 中体现，影响较小。

**注**：Charles 的常规用户输入（queue 类型）通过 `_sse_generator` L813 包裹 `<user_input mode="...">`，但 steer 消息绕过了此包裹逻辑。

**修复建议**：在 `server.py` `_consume` 回调内调用 `format_user_input_block` 或手动包裹 `<user_input mode="...">`，对齐 Cline `formatModePrompt`。改动范围：server.py `_make_consume_pending_user_message_callback` 函数内新增 1-2 行包裹逻辑。

**优先级**：P3

---

### 差距 3：drain 重入保护数据结构（对应对比项 7.17.4）

**严重度**：P3（实现差异，功能等价）

**Cline 设计**（`pending-prompt-service.ts` L285-286, L308, L323）：

```typescript
scheduleDrain(sessionId, session) {
    if (session.drainingPendingPrompts || ...) return;
    queueMicrotask(() => void this.drain(sessionId));
}

async drain(sessionId) {
    if (session.drainingPendingPrompts) return;
    session.drainingPendingPrompts = true;
    try { ... } finally { session.drainingPendingPrompts = false; }
}
```

单一布尔标志，存于 `ActiveSession.drainingPendingPrompts`（session.ts L36）。

**Charles 设计**（`turn_queue.py` L372-374, L519-611）：

```python
self._draining: set[str] = set()  # session_id 集合
self._drain_tasks: dict[str, asyncio.Task] = {}  # session_id -> Task 引用

def _schedule_drain(session_id) -> None:
    existing = self._drain_tasks.get(session_id)
    if existing and not existing.done():
        return  # 已有 drain 在排队
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._drain(session_id))
        self._drain_tasks[session_id] = task  # 防止 GC
    except RuntimeError:
        # 无运行中事件循环，跳过（由 server 层触发）
        ...

async def _drain(session_id) -> None:
    if session_id in self._draining: return
    self._draining.add(session_id)
    try { ... } finally:
        self._draining.discard(session_id)
        self._drain_tasks.pop(session_id, None)
```

双结构：`_draining` 集合防重入 + `_drain_tasks` 字典持有 Task 引用防 GC。

**差异分析**：

| 维度 | Cline | Charles |
|------|-------|---------|
| 防重入标志 | `session.drainingPendingPrompts: boolean` | `_draining: set[str]`（按 session_id 隔离） |
| Task 引用管理 | 无（queueMicrotask 不返回 Task） | `_drain_tasks` 字典持有 `asyncio.Task` |
| 无事件循环处理 | 不存在（JS 始终有事件循环） | `try/except RuntimeError` 跳过调度 |
| 清理时机 | drain finally 内重置布尔 | drain finally 内 discard + pop |

**影响**：Charles 的双结构更复杂，但解决了 Python `asyncio.create_task` 的 Task GC 问题（未持有引用的 Task 可能被回收）。Cline 的 `queueMicrotask` 不返回 Task，无需管理引用。两者功能等价。

**Charles 的额外保护**：`_schedule_drain` 在无运行中事件循环时（如同步上下文调用 enqueue）跳过调度，由 server 层在 async 上下文中触发。Cline 不存在此问题（JS 始终有事件循环）。

**修复建议**：保持现状，功能等价。

**优先级**：P3

---

### 差距 4：入队时 SSE 事件命名差异（对应对比项 7.17.8）

**严重度**：P3（前端兼容性差异）

**Cline 设计**：入队时 `enqueue`（L238-253）调用 `emitPrompts` 发射 `pending_prompts` 事件，与消费时事件类型相同。前端通过同一事件类型区分入队/消费状态。

**Charles 设计**：入队时（`server.py` L1026-1031）返回 `pending_prompts_updated` 事件，携带 `queued_message` + `delivery` 字段；消费时（L781-790）发 `pending_prompts` + `pending_prompt_submitted` 两个事件。

**差异**：

| 事件类型 | Cline | Charles |
|---------|-------|---------|
| 入队 | `pending_prompts` | `pending_prompts_updated`（含 queued_message + delivery） |
| 消费（queue） | `pending_prompts` + `pending_prompt_submitted` | `pending_prompts` + `pending_prompt_submitted` |
| 消费（steer） | `pending_prompts` + `pending_prompt_submitted`（在 consumeSteer 内 emit） | `pending_prompts` + `pending_prompt_submitted`（在 consume_steer 内 emit，但 emit_callback 为空操作，实际由 _sse_generator 内 yield） |

**影响**：前端需监听两个不同事件类型（`pending_prompts` 和 `pending_prompts_updated`）。Charles 的 `pending_prompts_updated` 携带 `queued_message` 字段，前端可显示"已排队：xxx"提示。Cline 统一用 `pending_prompts` 事件，前端通过队列长度变化判断是否入队。

**修复建议**：保持现状。Charles 的 `pending_prompts_updated` 提供了更丰富的入队反馈（queued_message + delivery），前端体验更好。若要对齐 Cline，可将入队事件改为 `pending_prompts`，但需评估前端兼容性。

**优先级**：P3

---

### 差距 5：状态持久化差异（对应对比项 7.17.7）

**严重度**：P3（服务重启后队列丢失）

**Cline 设计**：队列状态存于 `ActiveSession.pendingPrompts`（session.ts L35），与 session 生命周期绑定。session 持久化时（通过 session snapshot/restore），队列随之持久化到磁盘，服务重启后可恢复。

**Charles 设计**：队列状态存于 `PendingPromptsController._states: dict[str, PendingPromptQueueState]`（turn_queue.py L370），由 controller 单例持有，**纯内存**。server.py L91 `_turn_queue_controller: Any = None` 模块级单例，服务重启后丢失。**无持久化机制**。

**影响**：Charles 服务重启后，所有会话的排队消息丢失。若用户在服务重启前排队了重要消息，重启后需重新发送。Cline 的队列随 session 持久化，重启后可恢复。

**修复建议**：若需持久化，可在 `turn_queue.py` 的 `enqueue` / `update` / `delete` / `clear` 方法内调用 session_manager 持久化队列状态，或在 session 持久化时序列化 `PendingPromptQueueState`。但当前 Charles 的 session 持久化（session.py）未包含队列状态，需扩展序列化格式。改动范围较大，优先级低。

**优先级**：P3

---

## 四、nanobot 残留专项检查

### 检查范围

P7.17 直接相关代码：
- `agent/turn_queue.py`（PendingPromptService + PendingPromptsController 完整实现）
- `agent/runtime.py` L855-882（`consume_pending_user_message` 回调集成）
- `agent/server.py` L89-161（`_get_turn_queue_controller` 依赖注入）+ L308-339（`_make_consume_pending_user_message_callback` 回调构造）+ L760-829（`_sse_generator` 末尾 queue 消费循环）+ L984-1051（`/stream` 入队入口）+ L1145-1213（REST 端点）+ L1250-1256（`/abort` 清空队列）
- `agent/types.py` L557（`AgentRuntimeConfig.consume_pending_user_message` 字段定义）
- `static/js/ai-chat.js` L518-559 + L647-661（前端入队 + 事件处理）

P7.17 间接相关代码（涉及 turn queue 但非核心）：
- `agent/server.py` 文件头（L2/L4/L28，模块级 docstring nanobot 残留，与 turn queue 无关，属 P7.1 范围）
- `tests/test_turn_queue_consume.py`（测试文件，非生产代码）

### 检查结果

| 文件 | nanobot 残留类型 | 残留数量 | 残留位置 | 影响评估 |
|------|----------------|---------|---------|---------|
| `agent/turn_queue.py` | 注释残留 | 0 处 | — | 无（模块 docstring L2-27 全部对标 Cline `pending-prompt-service.ts`，无 nanobot 标注） |
| `agent/turn_queue.py` | 实现逻辑残留 | 0 处 | — | 无（`PendingPromptService` + `PendingPromptsController` 完全对标 Cline，无 nanobot 逻辑） |
| `agent/runtime.py`（L855-882 consume_pending_user_message 分支） | 注释残留 | 0 处 | — | 无（L855-857 注释对标 Cline `agent-runtime.ts` L841-852） |
| `agent/runtime.py`（consume_pending_user_message 分支） | 实现逻辑残留 | 0 处 | — | 无（回调集成完全对标 Cline） |
| `agent/server.py`（L89-161 _get_turn_queue_controller） | 注释残留 | 0 处 | — | 无（L89-106 docstring 对标 Cline drain() L295-335） |
| `agent/server.py`（L308-339 _make_consume_pending_user_message_callback） | 注释残留 | 0 处 | — | 无（L314 注释对标 Cline `agent-runtime.ts` L1252-1267） |
| `agent/server.py`（L760-829 _sse_generator 末尾循环） | 注释残留 | 0 处 | — | 无（L756-758 注释对标 Cline drain() L295-335） |
| `agent/server.py`（L984-1051 /stream 入队入口） | 注释残留 | 0 处 | — | 无（L988-991 docstring 描述 turn_queue 机制，无 nanobot） |
| `agent/server.py`（L1145-1213 REST 端点） | 注释残留 | 0 处 | — | 无（L1141 注释对标 Cline `PendingPromptsController` API） |
| `agent/server.py`（L1250-1256 /abort 清空队列） | 注释残留 | 0 处 | — | 无（L1250 注释对标 Cline `clearAborted`） |
| `agent/types.py`（L557 consume_pending_user_message 字段） | 注释残留 | 0 处 | — | 无（L555-556 注释描述回调签名，无 nanobot） |
| `static/js/ai-chat.js`（L518-559 + L647-661） | 注释残留 | 0 处 | — | 无（L518/L647/L697 注释对标 Cline `pending_prompts` / `pending_prompt_submitted` 事件） |
| `tests/test_turn_queue_consume.py` | 注释残留 | 0 处 | — | 无（测试文件，非生产代码） |

### 间接相关文件的 nanobot 注释残留（与 turn queue 无关）

| 文件 | nanobot 注释残留位置 | 残留类型 | 与 turn queue 关系 |
|------|---------------------|---------|---------------------|
| `agent/server.py` | L2（`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`）+ L4（`提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`）+ L28（`对标 nanobot:\n    - routes/chat.py _sse_generator() + _StreamCollectorHook`） | 注释残留（类型 A：实现来源标注） | 与 turn queue 无关（属 P7.1 范围已审计，这些注释标注的是 SSE 服务端整体设计来源，turn queue 实现在 L89-161 / L308-339 / L760-829 / L984-1051 / L1145-1213 完全对标 Cline） |

### nanobot 残留结论

- **P7.17 直接相关代码（`turn_queue.py` + `runtime.py` consume_pending_user_message 分支 + `server.py` turn queue 相关代码 + `types.py` consume_pending_user_message 字段 + `ai-chat.js` 前端处理）**：**0 处注释残留 + 0 处实现逻辑残留**。Turn Queue 机制的实现完全对标 Cline `pending-prompt-service.ts`，无 nanobot 逻辑残留。
- **间接相关文件的 nanobot 注释残留**：`server.py` 文件头（L2/L4/L28）有 3 处 nanobot 注释残留（类型 A：实现来源标注），但**全部为注释残留**，**未发现实现逻辑残留**，且与 turn queue 功能无关（属 P7.1 范围已审计）。
- **建议**：Turn Queue 机制无需任何 nanobot 清理。间接相关的 `server.py` 文件头注释残留可由 P7.1 阶段统一清理。

---

## 五、验证方法建议

### 验证方法 1：queue 类型排队顺序测试

1. 启动一个长 run（如让 agent 执行耗时工具调用）
2. 在 run 运行中连续发送 3 条消息：A（queue）、B（queue）、C（queue）
3. 等待当前 run 结束
4. 观察后续 run 的执行顺序

**预期**：
- Cline：drain 自动按 A → B → C 顺序启动 3 个新 run，每个 run 的事件通过 onEvent 推送
- Charles：_sse_generator 末尾 while 循环按 A → B → C 顺序启动 3 个新 run，事件通过原 SSE 连接 yield 推送

### 验证方法 2：steer 类型实时插入测试

1. 启动一个多 iteration 的 run（如 agent 需要多次工具调用）
2. 在 iteration 1 结束后、iteration 2 开始前，发送一条 steer 消息"再分析一下 X"
3. 观察 iteration 2 的 model request 是否包含该 steer 消息

**预期**：
- Cline：iteration 2 的 `request.messages` 末尾包含 steer 消息（含 `<user_input mode="act">` 包裹），`state.messages` 也持久化该消息，前端收到 `message-added` 事件
- Charles：iteration 2 的 `request.messages` 末尾包含 steer 消息（裸文本，无 mode 包裹），`state.messages` 也持久化该消息，前端收到 `message_added` 事件

### 验证方法 3：同 prompt 合并测试

1. 发送消息 A="分析茅台"（queue）
2. 立即发送消息 B="分析茅台"（queue，同 prompt）
3. 检查队列长度

**预期**：两者队列长度均为 1（同 prompt 合并更新，不重复入队）。

### 验证方法 4：steer + queue 合并升级测试

1. 发送消息 A="分析茅台"（queue）
2. 立即发送消息 B="分析茅台"（steer，同 prompt）
3. 检查队列中条目的 delivery

**预期**：两者队列中该条目的 delivery 均为 "steer"（queue + steer 合并升级为 steer），且位于队首。

### 验证方法 5：drain 失败 requeue 测试

1. 在 queue 消费过程中模拟 send_callback 抛异常（Cline）或 _run_once 抛异常（Charles）
2. 检查队列状态

**预期**：
- Cline：`requeueFront` 把 entry 放回队首，`continueDrain=false` 停止 drain，需外部触发重试
- Charles：`requeue_front` 把 entry 放回队首，`break` 退出 while 循环，SSE 生成器结束，客户端需重连

### 验证方法 6：abort 时清空队列测试

1. 发送 3 条 queue 消息
2. 调用 `/abort` 端点中止当前 run
3. 检查队列状态

**预期**：两者队列均为空（`clearAborted` / `clear_aborted` 清空队列）。

### 验证方法 7：SSE 断开后 queue 残留测试（差距 1 验证）

1. 启动一个长 run
2. 发送 2 条 queue 消息
3. 在当前 run 结束前断开 SSE 连接（如关闭浏览器）
4. 重新连接 SSE，检查队列中的 queue 消息是否被消费

**预期**：
- Cline：drain 独立于 SSE 连接，run 结束后 drain 仍启动新 run 消费 queue 消息（事件通过 hub 推送，新 SSE 连接可接收）
- Charles：SSE 断开后 _sse_generator 被取消，while 循环未执行，queue 消息残留 in memory；重新连接时 `/stream` 入口检查 `_active_runtimes`，若 runtime 已结束则直接启动新 run（不消费残留 queue）；需手动调用 `/pending_prompts` 端点查看残留并手动重新提交

### 验证方法 8：delivery 枚举校验测试（差距 7.17.2 验证）

1. 发送消息时指定 `delivery: "invalid"`
2. 检查队列行为

**预期**：
- Cline：TypeScript 编译期报错（`Type '"invalid"' is not assignable to type '"queue" | "steer"'`）
- Charles：`server.py` L1008-1009 入口校验 `if delivery not in ("queue", "steer"): delivery = "queue"`，降级为 queue 类型入队

### 验证方法 9：状态持久化测试（差距 7.17.7 验证）

1. 发送 2 条 queue 消息
2. 重启服务
3. 检查队列状态

**预期**：
- Cline：队列状态随 session 持久化，重启后恢复（若 session 持久化机制启用）
- Charles：队列状态纯内存，重启后丢失，需用户重新发送

---

## 六、与 P2.11 的差异说明

P7.17 与 P2.11（已完成的 Turn Queue 对比报告 `phase_2.11_turn_queue.md`）的对比范围基本重合，但有以下差异：

| 维度 | P2.11 | P7.17 |
|------|-------|-------|
| 对比项数量 | 11 项（含 list_pending / delete_update / SSE 事件） | 8 项（聚焦计划文件 P7.17 定义的项） |
| 对比焦点 | drain 触发方式 / steer 文本格式 / drain 重入保护 / 入队事件命名 / drain 失败行为 | 计划文件 8 项的逐项核实 + nanobot 残留专项检查 |
| nanobot 检查 | 简要提及（server.py 3 处注释残留） | 专项检查（直接相关 0 处 + 间接相关 3 处） |
| 一致性等级 | 强对齐 / 弱对齐 / 已对齐 | 高 / 中-高 / 中（更细粒度） |

P7.17 的核心新增内容：
1. **nanobot 残留专项检查**：详细列出直接相关代码（turn_queue.py / runtime.py / server.py / types.py / ai-chat.js）的残留情况，区分注释残留与实现逻辑残留。
2. **计划文件核实**：逐项核实 AGENT_COMPARISON_PLAN_V2.md L2929-2938 的标注是否准确。
3. **一致性等级细化**：从 P2.11 的"强对齐/弱对齐"细化为"高/中-高/中"。

P2.11 已发现的差距（drain 触发方式 / steer 文本格式 / drain 重入保护 / 入队事件命名 / drain 失败行为）在 P7.17 中作为重点差距详解重复列出，但措辞更简洁。

---

## 七、修复建议汇总

### P0（高优先级，影响功能正确性）

无。当前 Charles 的 Turn Queue 机制功能完整，queue 类型在 SSE 连接稳定时能自动消费，steer 类型能实时插入 model request，不影响运行时正确性。

### P1（中优先级，改善 SSE 断开后鲁棒性）

**建议 1：解耦 drain 与 SSE 连接（对应差距 1）**

参考 Cline `drain()` 通过 `send_callback` 真实启动新 run 的设计，将 Charles 的 `send_callback` 改为真实启动新 run（而非空操作），让 drain 独立于 SSE 连接。

**收益**：SSE 断开后，drain 仍能通过 `send_callback` 启动新 run，事件通过 hub 或独立通道推送。避免 SSE 断开导致队列残留。

**改动范围**：
- `server.py` `send_callback` 改为真实调用 `_run_once` 并通过事件队列推送事件
- 需引入事件中转通道（如 `asyncio.Queue` + 独立任务），让 SSE 重连后能继续接收事件
- `_sse_generator` 末尾的 while 循环可移除（由 drain 接管）

**注意**：此改动涉及 SSE 架构调整，风险较高。当前 Charles 的 SSE 单连接闭环设计在稳定网络下工作正常，若用户网络稳定可暂不修改。

**优先级**：P2（实际影响有限，因 SSE 断开后用户重新发消息即可触发新 run）

### P2（低优先级，改善 steer 消息一致性）

**建议 2：steer 消息包裹 mode 标签（对应差距 2）**

参考 Cline `formatModePrompt` 在 `consumePendingUserMessage` 回调内包裹 `<user_input mode="...">`，在 Charles 的 `_consume` 回调（server.py L322-337）内调用 `format_user_input_block` 或手动包裹：

```python
async def _consume(session_id_arg: str) -> str | None:
    entry = controller.consume_steer(sid)
    if entry is None:
        return None
    mode = entry.mode or _get_current_mode(sid)
    return f'<user_input mode="{mode}">\n{entry.prompt}\n</user_input>'
```

**收益**：steer 消息与常规用户输入格式一致，LLM 能看到 mode 上下文。

**改动范围**：server.py `_make_consume_pending_user_message_callback` 函数内新增 1-2 行包裹逻辑。

**优先级**：P3

### P3（可选，事件命名对齐）

**建议 3：统一入队事件类型（对应差距 4）**

参考 Cline 入队时也发 `pending_prompts` 事件（而非 `pending_prompts_updated`），将 Charles 入队时的事件类型改为 `pending_prompts`，前端通过队列长度变化判断入队。

**收益**：前端只需监听一个事件类型，简化事件处理逻辑。

**注意**：Charles 的 `pending_prompts_updated` 携带 `queued_message` + `delivery` 字段，前端可能依赖此信息显示"已排队"提示。改动需评估前端兼容性。

**优先级**：P3

### P4（可选，状态持久化）

**建议 4：队列状态持久化（对应差距 5）**

参考 Cline 队列状态与 ActiveSession 绑定，在 Charles 的 session 持久化机制中扩展队列状态序列化。

**收益**：服务重启后排队消息可恢复。

**改动范围**：
- `turn_queue.py` 的 `enqueue` / `update` / `delete` / `clear` 方法内调用持久化
- `session.py` 的 session 序列化格式扩展队列状态字段
- 服务启动时从持久化数据恢复队列

**优先级**：P3（当前 Charles 的 session 持久化已存在，但未包含队列状态）

---

## 八、总结

Charles 的 Turn Queue 机制在数据结构（PendingPromptEntry / PendingPromptQueueState）、纯逻辑层（PendingPromptService 的 enqueue / consume_steer / shift_next / requeue_front / update / delete / clear / list）、调度层（PendingPromptsController 的 scheduleDrain / drain / clear_aborted）三个层面均对标 Cline 实现，**核心语义完整对齐**。

主要差异集中在**调度层的 drain 触发方式**（Cline 独立于 SSE 连接，Charles 与 SSE 连接绑定）和**steer 消息文本格式**（Cline 包裹 mode 标签，Charles 裸文本），以及**状态持久化**（Cline 随 session 持久化，Charles 纯内存）。这些差异属于实现细节差异，不影响核心功能正确性，但在 SSE 断开后鲁棒性、LLM mode 上下文感知、服务重启后队列恢复三个场景下有功能影响。

nanobot 残留检查结论：**直接相关代码 0 处残留**，间接相关代码（server.py 文件头）3 处注释残留（类型 A：实现来源标注），**未发现实现逻辑残留**。
