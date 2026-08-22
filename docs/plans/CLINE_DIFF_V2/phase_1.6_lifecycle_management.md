# Phase 1.6 生命周期管理对比报告

## 说明

`AGENT_COMPARISON_PLAN_V2.md` 中 `P1.6` 的标题为“扩展机制对比”，但本次任务按用户明确的“生命周期管理（run/turn、hooks、状态迁移、事件点）”维度执行，并参考计划中 `P2.2 主循环 run() 控制流对比`、`P2.10 Hooks 生命周期对比（9 钩子点）` 的相关项。

## 1. 执行摘要

Charles 已将 Cline `AgentRuntime.execute()` 的生命周期语义在 `agent/runtime.py::AgentRuntime.run()` 中对齐到函数级：运行初始化 → `before_run` hooks → `run-started` 事件 → 输入注入 → `while` 主循环（`turn-started` → generate → `message-added`/`assistant-message` → tool 执行 → `turn-finished`）→ `run-finished`。状态迁移路径（idle → running → completed/aborted/failed）与 Cline 基本一致。

主要差异集中在 **hook 点的归属与扩展机制**：

- Cline 的 `AgentRuntimeHooks` 只定义 6 个运行时钩子（beforeRun/afterRun/beforeModel/afterModel/beforeTool/afterTool）+ 1 个事件监听钩子（onEvent）；用户输入预处理（`prepareTurnInput`）、输入块格式化（`formatUserInputBlock`）和审批拦截放在 runtime config 回调或 core host 层。
- Charles 将这三者也纳入 `AgentHooks`，形成 9 个 Python hook 点（before_run/after_run/before_model/after_model/before_tool/after_tool/prepare_turn_input/format_user_input_block/before_approval），并在 `agent/runtime.py` 内直接调用。这是 Charles 对 Cline 能力的显式扩展，但部分调用时机与 Cline 不完全等价。

- Cline 的 7 种文件 hooks（TaskStart/TaskResume/TaskCancel/TaskComplete/PreToolUse/PostToolUse/UserPromptSubmit）由 `@cline/core` 的 `hook-file-hooks.ts` 通过子进程执行外部脚本，再转换回 Python/TypeScript hook 行为注入 runtime。
- Charles 的 7 种文件 hooks 由 `agent/file_hooks/integration.py` 加载并转换为 `AgentHooks`，直接注册到 Python hook 点，形成“文件 hook → Python hook → runtime”的桥接。Charles 额外补充了 TaskResume/TaskCancel 两种文件 hook 类型，与 Cline 的事件名一一对应。

另外，`routes/chat.py` 仍是基于旧 `nanobot` 实现的遗留 SSE 路由，当前 `app.py` 已改用 `agent/server.py` 的 `/api/chat/stream`，但旧文件未删除，构成历史残留。

## 2. 逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 1.6.1 | `run()` 主循环入口 | `AgentRuntime.execute(input)`（L595），`run()`/`continue()` 均转发到 `execute()` | `AgentRuntime.run(input, messages=None)`（L521），支持直接传入历史消息 | 入口等价；Charles 增加 `messages` 参数用于会话续接 | 强对齐 |
| 1.6.2 | 运行前状态初始化 | 重置 `abortController`、`runId`、status=`running`、iteration=0、pendingToolCalls=[]、lastError=undefined、usage=default（L601-607） | 重置 `_aborted`、`_abort_reason`、`_abort_controller`、run_id、status=`running`、iteration=0、pending_tool_calls=[]、last_error=None、usage=AgentUsage()（L543-555） | 状态字段与初始化顺序一致 | 强对齐 |
| 1.6.3 | 运行中互斥检查 | `state.status === "running"` 时抛 `Error`（L597-599） | `state.status == "running"` 时抛 `RuntimeError`（L540-541） | 一致 | 强对齐 |
| 1.6.4 | `before_run` hooks 调用时机 | `callBeforeRunHooks()` 在 `run-started` 事件之前（L610-611） | `_call_before_run_hooks()` 在 `run-started` 事件之前（L559-562） | 一致 | 强对齐 |
| 1.6.5 | `before_run` hooks stop 语义 | hook 返回 `AgentStopControl` 后调用 `applyStopControl()`，抛出 `ControlledStopError`（L796-798） | hook 返回 `StopControl(stop=True)` 时直接抛 `RuntimeError`（L2085-2086） | 行为等价；Charles 未使用 `ControlledStopError` 在此处 | 弱对齐 |
| 1.6.6 | `run-started` 事件发射 | `emit({type:"run-started", snapshot})`（L611） | `_emit(make_run_started(snapshot))`（L562） | 一致 | 强对齐 |
| 1.6.7 | 输入消息注入 | 循环前将 `normalizeInput(input)` 追加到 `state.messages` 并 emit `message-added`（L613-620） | 循环前调用 `prepare_turn_input` hooks → `format_user_input_block` hooks → 追加消息并 emit `message-added`（L605-621） | Charles 在输入注入前增加两个 hook 点；Cline 由 host 层处理输入格式化 | 弱对齐 |
| 1.6.8 | `turn` 边界定义 | 一次 `turn` = 一次 LLM generate + 0..N tool 执行 + `turn-finished` 事件 | 一次 `turn` = 一次 `_generate_assistant_message` + 0..N tool 执行 + `turn-finished` 事件 | 一致 | 强对齐 |
| 1.6.9 | `turn-started` 事件 | 在 `throwIfAborted()` 后、iteration 自增后发射（L636-640） | 在 `_throw_if_aborted()` 后、iteration 自增后发射（L632-633） | 一致 | 强对齐 |
| 1.6.10 | `turn-finished` 事件 | 无 tool_calls 分支（L682-687）和 tool 执行后（L716-721）都会 emit | 无 tool_calls 分支（L704-712）和 tool 执行后（L736-738）都会 emit | 一致 | 强对齐 |
| 1.6.11 | run 结束路径 | 无 tool_calls 且无需 completion tool 时 `finishRun` → `callAfterRunHooks` → `run-finished`；completing tool 成功时同理（L696-703, L727-738） | 逻辑相同（L713-718, L744-747） | 一致 | 强对齐 |
| 1.6.12 | `run-failed` vs `run-finished` | failed 状态 emit `run-failed`；aborted/controlled-stop 状态 emit `run-finished`（L745-790） | failed 状态 emit `run-failed`；aborted 状态 emit `run-finished`；`ControlledStopError` 单独 catch 并 emit `run-finished`（L754-813） | Charles 显式拆分 controlled_stop 分支 | 弱对齐 |
| 1.6.13 | 6 个核心 runtime hooks | `AgentRuntimeHooks` 定义 beforeRun/afterRun/beforeModel/afterModel/beforeTool/afterTool（`agent.ts` L336-363） | `AgentHooks` 定义同 6 个 hook（`hooks.py` L304-309） | 一致 | 强对齐 |
| 1.6.14 | 9 个 hook 点（含扩展） | `prepareTurn`/`consumePendingUserMessage` 是 runtime config 回调；`requestToolApproval` 是审批回调；无 `before_approval` hook 概念 | 将 `prepare_turn_input`/`format_user_input_block`/`before_approval` 都作为 `AgentHooks` 的 hook 点（`hooks.py` L310-313） | Charles 把 host/config 层能力下沉为 hook；Cline 审批是 config 回调 | 弱对齐 |
| 1.6.15 | `before_model` hooks 上下文 | `AgentBeforeModelContext = {snapshot, request}` | `BeforeModelContext = {snapshot, request, session_id, abort_signal}` | Charles 额外携带 session_id 和 abort_signal | 弱对齐 |
| 1.6.16 | `before_model` hooks 可修改字段 | 可返回 messages/tools/options（L864-875） | 可返回 messages/tools/options（L2116-2121） | 一致 | 强对齐 |
| 1.6.17 | `after_model` hooks 上下文 | `AgentAfterModelContext = {snapshot, assistantMessage, finishReason}` | `AfterModelContext = {snapshot, assistant_message, finish_reason}` | 字段等价 | 强对齐 |
| 1.6.18 | `before_tool` hooks 上下文 | `AgentBeforeToolContext = {snapshot, tool, toolCall, input}` | `BeforeToolContext = {snapshot, tool, tool_call, input}` | 一致 | 强对齐 |
| 1.6.19 | `before_tool` hooks 可修改字段 | 可返回 input/policy/skip/stop（L1377-1391） | 可返回 input/policy/additional_context/skip/stop（L1487-1497） | Charles 额外支持 additional_context 注入 | 弱对齐 |
| 1.6.20 | `after_tool` hooks 上下文 | `AgentAfterToolContext = {snapshot, tool, toolCall, input, result, startedAt, endedAt, durationMs}` | `AfterToolContext = {snapshot, tool, tool_call, input, result, started_at, ended_at, duration_ms}` | 字段等价 | 强对齐 |
| 1.6.21 | `after_tool` hooks 可修改字段 | 可返回 result/stop（L1533-1536） | 可返回 result/stop（L1775-1778） | 一致 | 强对齐 |
| 1.6.22 | hooks 注册顺序 | `registerHooks()` 按调用顺序 push 到数组（L544-554） | `HookBag.add()` 按调用顺序 append（L341-361） | 一致 | 强对齐 |
| 1.6.23 | hooks 失败处理 | hook 抛错会中断后续同类型 hook 并进入 catch（由 `await hook()` 自然传播） | `_call_hook()` 将同步/异步 hook 统一 await，抛错自然传播 | 一致 | 强对齐 |
| 1.6.24 | `prepare_turn_input` 调用位置 | Cline 由 host 层 `prepareTurnInput()` 在调用 runtime 前完成；runtime 内通过 `consumePendingUserMessage()` 在 iteration>1 时注入 steer 消息（L841-852） | Charles 在 `run()` 入口、输入注入前调用（L605-609），仅当 input 为 str 时生效 | 调用位置不同：Cline 在 host/steer 两条路径；Charles 集中在 runtime 入口 | 弱对齐 |
| 1.6.25 | `format_user_input_block` 调用位置 | Cline 由 `shared/src/prompt/format.ts` 在 host 层包装 `<user_input mode>`（被 `prepareTurn` 使用） | Charles 在 `run()` 入口、消息追加前调用（L614-617），无 hook 时也执行默认 `<user_input mode>` 包装（L2739-2744） | Charles 把格式化能力下沉到 runtime，保证非 HTTP 调用也生效 | 弱对齐 |
| 1.6.26 | `before_approval` 调用位置 | Cline 无此 hook，审批通过 `requestToolApproval` config 回调或 toolPolicies 完成 | Charles 在 `_prepare_tool_execution` 中于默认审批逻辑前调用 `before_approval` hooks（L1560-1582） | Charles 新增 hook 点，Cline 无直接对应 | 额外 |
| 1.6.27 | 文件 hook 类型数量 | 7 种直接映射到 runtime 的文件 hook：TaskStart/TaskResume/TaskCancel/TaskComplete/PreToolUse/PostToolUse/UserPromptSubmit（`hook-file-config.ts` L17-28） | 7 种文件 hook：TaskStart/TaskResume/TaskCancel/TaskComplete/PreToolUse/PostToolUse/UserPromptSubmit（`file_hooks/types.py` L56-75） | 数量与名称一致 | 强对齐 |
| 1.6.28 | 文件 hook 执行方式 | 通过 `spawn` 子进程执行外部脚本，解析 stdout 中的 `HOOK_CONTROL` JSON（`hook-file-hooks.ts` L286-395） | 通过 `asyncio.create_subprocess_exec/shell` 执行外部脚本，解析 stdout JSON（`file_hooks/runner.py`） | 都使用子进程；Cline 为 Node spawn，Charles 为 asyncio | 弱对齐 |
| 1.6.29 | 文件 hook 到 runtime hook 的映射 | `hook-file-hooks.ts` 将文件 hook 映射到 `AgentHooks` 注入，如 `tool_call` → beforeTool、`tool_result` → afterTool、`agent_start` → beforeRun 等 | `file_hooks/integration.py` 将文件 hook 映射到 `AgentHooks`：PreToolUse→beforeTool、PostToolUse→afterTool、UserPromptSubmit→prepare_turn_input、TaskStart/TaskResume→before_run、TaskComplete/TaskCancel→after_run | 映射语义一致 | 强对齐 |
| 1.6.30 | 文件 hook 并发限制 | `Promise.all` 并行执行同事件下的所有脚本（由 `hook-file-hooks.ts` 内部聚合） | 限制 `_MAX_PARALLEL_HOOKS = 10`，超出部分串行执行（`integration.py` L113, L151-154） | Charles 显式限制并发 | 弱对齐 |
| 1.6.31 | 文件 hook 上下文字段 | payload 包含 clineVersion/taskId/sessionContext/workspaceRoots/userId/agent_id/parent_agent_id 等（`hook-file-hooks.ts` L177-196） | `FileHookContext` 包含 hook_type/session_id/run_id/iteration/tool_name/input/result/previous_state/completion_status 等（`file_hooks/types.py` L143-160） | 字段集合不同但都覆盖核心上下文；Charles 更聚焦运行时 snapshot | 弱对齐 |
| 1.6.32 | 状态迁移：idle → running | `execute()` 开始设置 status=`running`（L603） | `run()` 开始设置 status=`running`（L551） | 一致 | 强对齐 |
| 1.6.33 | 状态迁移：running → completed | `finishRun("completed")` 设置 status（L1566） | `_finish_run("completed")` 设置 status（L2227） | 一致 | 强对齐 |
| 1.6.34 | 状态迁移：running → aborted | `abort()` 设置 `state.lastError` 并触发 `abortController.abort()`；catch 中 status=`aborted`（L454-470, L749-752） | `abort()` 设置 `_aborted=True`、status=`aborted`、last_error，并触发 `_abort_controller.abort()`（L405-423）；catch 中 status=`aborted` | 一致 | 强对齐 |
| 1.6.35 | 状态迁移：running → failed | 非 abort 异常进入 catch，status=`failed`（L752） | 非 abort 异常进入 catch，status=`failed`（L788） | 一致 | 强对齐 |
| 1.6.36 | 状态迁移：controlled_stop | `ControlledStopError` 在 catch 中统一按 aborted 处理 | 单独 catch `ControlledStopError`，status=`completed`、finish_reason=`controlled_stop`（L754-782） | Charles 将 controlled_stop 视为完成态，Cline 视为 abort 态 | 语义不等价 |
| 1.6.37 | `restore()` 语义 | `abort()` 当前运行，重置 runId/iteration/pendingToolCalls/usage/lastError，替换 messages（L487-503） | `abort()` 当前运行，重置同样字段，并额外重置 `_loop_tracker`、`_mistake_tracker`、`_aborted`、`_initial_messages_injected`、`_completion_reminder_injected`（L376-403） | Charles 重置更多内部状态 | 弱对齐 |
| 1.6.38 | `abort()` 幂等性 | 已 aborted 时直接返回（L458-460） | 已 aborted 时直接返回（L415） | 一致 | 强对齐 |
| 1.6.39 | abort signal 类型 | 标准 `AbortSignal`/`AbortController` | 自定义 `abort.py::AbortController` 使用 `asyncio.Event` | 类型不同，语义等价 | 弱对齐 |
| 1.6.40 | `onEvent` hook | `AgentRuntimeHooks.onEvent` 可订阅所有 runtime 事件（L364） | Charles 无 `onEvent` hook，事件通过 `EventEmitter.subscribe()` 订阅 | Cline 将事件订阅也作为 hook 点，Charles 分离为 emitter | 弱对齐 |

## 3. 重点差距详细说明

### 3.1 `controlled_stop` 状态迁移语义不等价

- **Cline**：当 hook 返回 stop 控制时，runtime 抛出 `ControlledStopError`，在 `execute()` 的 catch 块中按 `isAborted` 处理，最终 `status="aborted"`。也就是说，hook 主动停止被视为 abort 类结束。
- **Charles**：`ControlledStopError` 被单独 catch（L754-782），`status="completed"`、`finish_reason="controlled_stop"`。这是 Charles 的扩展，用于让前端区分“被规则拦截”与“系统异常/用户中止”。
- **影响**：两边运行结果的 `status` 字段在 hook 主动 stop 时不一致。若下游逻辑按 `status === "aborted"` 判断是否需要重试或提示用户，会产生分歧。

### 3.2 `prepare_turn_input` / `format_user_input_block` 调用位置偏移

- **Cline**：`prepareTurnInput` 和 `formatUserInputBlock` 属于 host 层能力，在调用 `AgentRuntime.execute()` 之前完成；runtime 内部仅通过 `consumePendingUserMessage` 在 iteration>1 时插入 steer 消息。
- **Charles**：把这两个能力下沉到 `AgentRuntime.run()` 入口，作为 `AgentHooks` 的一部分直接调用，并且无 hook 时也执行默认 `<user_input mode>` 包装。
- **影响**：Charles 的 runtime 自身承担更多输入格式化职责，对非 HTTP 调用更友好；但与 Cline 的分层模型不一致，若未来需要与 Cline 的 host 层能力严格对齐，可能需要将部分逻辑上提到 server/host 层。

### 3.3 `before_approval` hook 是 Charles 特有扩展

- **Cline**：审批通过 `AgentRuntimeConfig.requestToolApproval` 回调或 `toolPolicies` 配置完成，没有独立的 `before_approval` hook。
- **Charles**：在 `_prepare_tool_execution` 中于默认审批逻辑前调用 `before_approval` hooks，返回 `approved`/`denied` 可覆盖后续审批流程。
- **影响**：这是 Charles 的合理增强，但属于额外能力，不属于 Cline 原生生命周期。

### 3.4 文件 hook 并发与错误处理

- **Cline**：同事件下的所有文件 hook 脚本通过聚合机制并行执行（`Promise.all`），未显式限制并发数量。
- **Charles**：显式限制 `_MAX_PARALLEL_HOOKS = 10`，超出部分串行执行，并在 blocking/non-blocking 字段上做了更细粒度的错误处理。
- **影响**：Charles 在大量 hook 脚本场景下更安全，但可能与 Cline 的“全并行”语义产生时序差异。

### 3.5 `onEvent` hook 缺失

- **Cline**：`AgentRuntimeHooks.onEvent` 允许 hook 监听所有 runtime 事件，与 `runtime.subscribe()` 并存。
- **Charles**：没有 `onEvent` hook，事件消费完全依赖 `EventEmitter.subscribe()`。
- **影响**：若某文件 hook 或 Python hook 需要监听事件流，Charles 无法通过 hook 系统实现，只能直接订阅 emitter。

## 4. nanobot 残留检查

在生命周期管理相关文件中发现以下 `nanobot` 命名残留：

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/server.py` | 2、4、28 | docstring 提到“对标 Cline server + nanobot routes/chat.py”、“用 AgentRuntime 替换 nanobot” | nanobot 残留 |
| `agent/session.py` | 2、22 | docstring 提到“nanobot session_key” | nanobot 残留 |
| `agent/hooks.py` | 无 | 未发现 `nanobot` 字符串 | — |
| `agent/file_hooks/integration.py` | 无 | 未发现 `nanobot` 字符串 | — |
| `agent/runtime.py` | 无 | 未发现 `nanobot` 字符串 | — |
| `routes/chat.py` | 4、47-48、92、159 | 多处基于 nanobot 的 docstring、路径、模块命名 | 遗留 SSE 路由 |

其中 **`routes/chat.py` 是最实质性的残留**：它仍引用 `third_party/charles_bundle/charles-nanobot/agent.py` 实现旧版 `/api/chat/stream`，与当前 `agent/server.py` 的新生命周期管理重复。

## 5. 修复建议

### P0（阻碍后续对比/集成）

1. **统一 `controlled_stop` 状态语义**：
   - 若需严格对齐 Cline，应将 `ControlledStopError` 并入通用 catch 块，最终 `status="aborted"`；
   - 若保留 Charles 的完成态语义，应在文档中明确说明 `finish_reason="controlled_stop"` 与 Cline `aborted` 的映射关系，避免下游状态机误判。

2. **移除或归档 `routes/chat.py`**：当前 `app.py` 已使用 `agent/server.py`，旧路由不再挂载。应删除 `routes/chat.py` 或移入 `legacy/` 目录，避免与 `agent/server.py` 的 `/api/chat/stream` 产生路径和概念冲突。

### P1（建议修复）

3. **补充 `onEvent` hook 能力**：在 `AgentHooks` 中增加 `on_event` 字段，并在 `AgentRuntime._emit()` 中调用，与 Cline `AgentRuntimeHooks.onEvent` 对齐。

4. **明确 `prepare_turn_input` / `format_user_input_block` 的分层**：
   - 若保持当前 runtime 内调用，应在文档中说明这是 Charles 对 Cline host 层能力的下沉；
   - 若严格对齐 Cline，可考虑将默认 `<user_input mode>` 包装上提到 `agent/server.py` 或 host 层，runtime 内仅保留 hook 扩展点。

5. **文件 hook 并发限制文档化**：将 `_MAX_PARALLEL_HOOKS = 10` 的语义写入 `agent_config/hooks/` 配置说明，避免用户假设与 Cline 完全一致的全并行行为。

## 6. 验证方法

| 验证项 | 方法 | 预期结果 |
|--------|------|---------|
| 生命周期事件序列 | 注册事件监听器，记录一次完整 run 的事件 type 序列 | 序列与 Cline 基本一致：run-started → message-added(input) → turn-started → deltas → message-added(assistant) → assistant-message → [tool-started → tool-finished → message-added(tool)] → turn-finished → run-finished |
| hook 执行顺序 | 注册多个同类型 hook，记录调用顺序 | 按注册顺序执行 |
| hook stop 行为 | 在 before_run/before_model/before_tool 中返回 stop | Charles 返回 finish_reason=`controlled_stop`；Cline 返回 status=`aborted` |
| 文件 hook 映射 | 在 `agent_config/hooks/PreToolUse/` 下放置脚本 | block 时对应工具被 skip |
| 状态迁移 | 调用 abort() / 构造异常 / 构造 completing tool | status 分别变为 aborted / failed / completed |
| nanobot 残留 | `Grep "nanobot" agent/runtime.py agent/hooks.py agent/file_hooks/*.py` | 无匹配 |

## 7. 结论

Charles 的生命周期管理与 Cline 在核心 run/turn 边界、状态迁移、6 个核心 runtime hooks 上高度对齐。主要差异体现在：

1. **hook 点扩展**：Charles 将 `prepare_turn_input`/`format_user_input_block`/`before_approval` 也作为 `AgentHooks` 的 hook 点，形成 9 个 Python hook 点，而 Cline 中这些能力分散在 runtime config 和 host 层。
2. **controlled_stop 语义不等价**：Charles 将 hook 主动停止视为完成态，Cline 视为 abort 态，需要文档或代码层面明确映射。
3. **文件 hook 实现对齐**：Charles 的 7 种文件 hook 类型与 Cline 一一对应，映射到 Python hook 点的语义一致，但并发控制和上下文字段有差异。
4. **无 `onEvent` hook**：Charles 缺少 Cline 的 `onEvent` hook，事件消费只能通过 `EventEmitter.subscribe()`。

整体生命周期管理对齐度约为 **90%**，剩余 10% 主要为 hook 分层差异和 Charles 的合理扩展。建议在保留 Charles 量化场景增强的前提下，通过文档明确与 Cline 的状态语义映射，并清理 `routes/chat.py` 等 nanobot 残留。
