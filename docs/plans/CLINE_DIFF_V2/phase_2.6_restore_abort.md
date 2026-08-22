# Phase 2.6 restore() + abort() 对比报告

## 1. 执行摘要

Cline 与 Charles 在 restore() + abort() 机制上整体已对齐核心语义，二者均采用"AbortController + 幂等 abort + restore 先 abort 再重置"的设计模式。Charles 在 Phase 28.2 / 30.2 / 30.3 / 2.6 / 2.7 等阶段已主动对齐 Cline 的关键行为：abort 时记录 last_error、abort 时 kill 子进程、幂等检查、reason 字段传播等。

主要差距集中在两点：
1. **AbortController 类实现**：Cline 使用原生 Web 标准 `AbortController`（signal: AbortSignal + abort() + reason），Charles 自定义 `AbortController`（signal: asyncio.Event + abort() + reason），同时**额外保留 `_aborted: bool` + `_abort_reason: str` 双重状态**，形成"布尔标志 + AbortController"双轨制。双轨制带来一致性维护成本（abort/restore/run 三处都要同步重置），但功能上等价。
2. **throwIfAborted 调用点数量**：Cline 在循环顶、prepareTurn 后、before_model 后、before stream、stream 内每个 event、openTaskLifecycleStream 等约 7 个检查点调用；Charles 仅在循环顶和 stream 内每个 event 共 2 个检查点调用。Charles 缺失 before_model 后、prepareTurn 后等中间检查点，理论上 abort 响应延迟可能多一个 hook 执行周期。

nanobot 残留检查结论：在 abort/restore 直接相关代码（abort.py + runtime.py 的 abort/restore/_throw_if_aborted）中**未发现 nanobot 残留**；间接相关的 `agent/tools/exec_tool.py` 中有 3 处 nanobot 注释残留（类型 A：实现来源标注），**全部为注释残留**，**未发现实现逻辑残留**。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.6 章节定义的 16 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.6.1 | AbortController 类结构 | agent-runtime.ts L424（`private abortController?: AbortController`） | abort.py L38-100（自定义类）+ runtime.py L272（`self._abort_controller = AbortController()`） | Cline 用原生 AbortController；Charles 自定义类，字段含 `_signal: asyncio.Event` + `_reason: str`；Charles 额外保留 `_aborted: bool` + `_abort_reason: str` 在 runtime 中形成双轨制 | 弱对齐 |
| 2.6.2 | signal 类型 | AbortSignal（Web 标准，支持 addEventListener / wait / aborted 属性） | asyncio.Event（仅 is_set / set / clear / wait） | 类型不同：AbortSignal 是事件驱动型（可注册多个 listener）；asyncio.Event 是协程等待型（仅能 await wait()），无 listener 机制 | 弱对齐 |
| 2.6.3 | abort() 副作用 | L454-470：① 幂等检查 ② 创建/复用 AgentRuntimeAbortError ③ `state.lastError = abortError.message` ④ `captureTaskLifecycle(TASK_CANCELLED_EVENT, ...)` ⑤ `abortController.abort(abortError)` | runtime.py L405-423：① 幂等检查 ② `_aborted=True` ③ `_abort_reason=...` ④ `state.status="aborted"` ⑤ `state.last_error=...` ⑥ `_abort_controller.abort(...)` | Charles 在 abort() 内立即设 status="aborted"；Cline 只在 catch 块设 status。Charles 缺失 `captureTaskLifecycle(TASK_CANCELLED_EVENT)` 遥测事件 | 弱对齐 |
| 2.6.4 | throwIfAborted 调用点 | L633（循环顶）、L855（prepareTurn 后）、L862（before_model 后）、L875（before stream）、L892（captureTaskLifecycle 前）、L914（stream 内每个 event）、L1087-1088（openTaskLifecycleStream 内 2 处）共 ~7 处 | runtime.py L630（循环顶）、L910（stream 内每个 event）共 2 处 | Charles 缺失 before_model 后、prepareTurn 后、before stream、openTaskLifecycleStream 内的检查点；hook 执行中 abort 无法立即响应 | 弱对齐 |
| 2.6.5 | signal 透传到 model.stream | L831：`signal: this.abortController?.signal` 写入 AgentModelRequest | runtime.py L900：`self.config.model.stream(request, abort_signal=self._abort_controller.signal)`；qwen.py L130, L170-176 检查 `abort_signal.is_set()` | 已对齐：Charles qwen.py 在 chunk 间隙检查 signal，触发时 yield finish event with ABORTED reason | 强对齐 |
| 2.6.6 | signal 透传到 tool.execute | L1495：`signal: this.abortController?.signal` 写入 AgentToolContext | runtime.py L1824：`abort_signal=self._abort_controller.signal` 写入 AgentToolContext | 已对齐：字段名不同（`signal` vs `abort_signal`）但语义一致 | 强对齐 |
| 2.6.7 | stream 中途 abort 行为 | L914 throwIfAborted 直接抛 `AgentRuntimeAbortError`；stream 通过 signal.aborted 让 fetch 自身中断 | qwen.py L170-176 yield `finish` event with `ABORTED` reason + `error="aborted by user"`，然后 return；runtime L910 `_throw_if_aborted` 抛 RuntimeError | 行为差异：Cline 直接抛异常中断流；Charles 先 yield finish event（优雅终止）再由 runtime 抛异常。Charles 多一次 finish event 发射 | 弱对齐 |
| 2.6.8 | tool 中途 abort 行为 | L700+：AbortSignal 触发时，BashTool 通过 fetch/invoke 自动取消（Web 标准） | exec_tool.py L205-260 `_wait_process_with_abort`：组合 `communicate + abort_signal.wait + timeout`，abort 先触发时 `process.kill()` + 抛 `AbortedError` | Charles 显式 kill 子进程（Stage 30.3 对齐）；Cline 依赖 AbortSignal 自动取消 | 强对齐 |
| 2.6.9 | abort 后状态清理 | L792 finally：`this.abortController = undefined`（不 unsubscribe listeners，不重置 state） | runtime.py L815-817 finally：`_aborted = False` + `_abort_reason = ""`（不重置 _abort_controller，不 unsubscribe listeners） | Charles 在 finally 重置布尔标志；Cline 直接置空 abortController。两者均不 unsubscribe listeners | 弱对齐 |
| 2.6.10 | abort 事件 emit | L466-468：`captureTaskLifecycle(TASK_CANCELLED_EVENT, {error})` 在 abort() 内 emit 遥测事件；catch 块 L777-789 根据 isAborted 决定 run_failed vs run_finished | runtime.py：abort() 内不 emit 任何事件；catch 块 L808-811 根据 is_aborted 决定 run_failed vs run_finished | Charles 缺失 TASK_CANCELLED_EVENT 遥测事件；run_failed/run_finished 分支逻辑已对齐 | 弱对齐 |
| 2.6.11 | reason 字段传播 | L465：`state.lastError = abortError.message`；snapshot.lastError 返回；AgentRuntimeAbortError.reason 保留原始 reason | runtime.py L421：`state.last_error = _abort_reason`；snapshot.last_error 返回；`_abort_reason` 保留原始 reason | 已对齐（Charles Phase 30.2） | 强对齐 |
| 2.6.12 | 多次 abort 幂等 | L458-460：检查 `signal.aborted`，已 aborted 直接 return | runtime.py L415-416：检查 `_aborted`，已 aborted 直接 return；abort.py L80-81：AbortController.abort() 内再次幂等检查 | 三层幂等（runtime._aborted + AbortController._signal.is_set()）；Cline 一层幂等（signal.aborted） | 强对齐 |
| 2.6.13 | restore() 实现 | L487-503：abort → 重置 runId/status/iteration/pendingToolCalls/usage/lastError/messages → `config.initialMessages = cloneMessages(messages)` | runtime.py L376-403：abort → 重置 runId/status/iteration/pendingToolCalls/usage/lastError/messages → 额外重置 `_recent_tool_errors`/`_loop_tracker.reset()`/`_mistake_tracker.reset()`/`_abort_controller.reset()`/`_aborted`/`_abort_reason`/`_initial_messages_injected`/`_completion_reminder_injected` | Charles 重置内容更多（含 tracker 重置，因 Charles 无 SessionRuntime 层，tracker 与 runtime 生命周期绑定）；Cline 不重置 tracker（由 SessionRuntime 持有） | 弱对齐 |
| 2.6.14 | restore 与 abort 关系 | L488：restore 第一行调用 `this.abort("Agent state restored")` | runtime.py L385：restore 第一行调用 `self.abort("Agent state restored")` | 已对齐：两者均先 abort 再重置 | 强对齐 |
| 2.6.15 | abort 时记录 lastError | L465：`state.lastError = abortError.message` | runtime.py L421：`state.last_error = self._abort_reason` | 已对齐（Charles Phase 30.2） | 强对齐 |
| 2.6.16 | abort 时 kill 子进程 | bash.ts L291-307：AbortSignal 触发时 fetch/invoke 自动取消，OS 级别 kill | exec_tool.py L205-260 `_wait_process_with_abort`：`asyncio.wait({comm_task, abort_task}, FIRST_COMPLETED)`，abort 先触发时 `process.kill()` + `await process.wait()` | 已对齐（Charles Phase 30.3 / 2.7 显式 kill） | 强对齐 |

## 3. 重点差距详细说明

### 差距 1：AbortController 双轨制状态维护（对应对比项 2.6.1、2.6.3、2.6.9）

**Cline 设计**：单一 `AbortController` 实例（L424 `private abortController?: AbortController`），所有中止状态由 `abortController.signal.aborted` 单一来源决定：
- `abort()` (L454-470)：检查 `signal.aborted` 幂等 → `abortController.abort(abortError)`
- `throwIfAborted()` (L588-593)：检查 `signal.aborted` → 抛 `normalizeAbortError()`
- `execute()` finally (L792)：`this.abortController = undefined`
- `execute()` 入口 (L601)：`this.abortController = new AbortController()`

**Charles 设计**：双重状态源——`runtime._aborted: bool` + `_abort_reason: str`（L261-262）与 `AbortController._signal: asyncio.Event` + `_reason: str`（abort.py L59-60）并行存在：
- `abort()` (L405-423)：先设 `_aborted=True` + `_abort_reason` + `state.status="aborted"` + `state.last_error`，再调 `_abort_controller.abort()`
- `_throw_if_aborted()` (L2204-2207)：只检查 `_aborted`（不检查 `_abort_controller.is_set()`）
- `run()` 入口 (L544-549)：重置 `_aborted=False` + `_abort_reason=""` + `_abort_controller.reset()`
- `run()` finally (L815-817)：只重置 `_aborted=False` + `_abort_reason=""`（不重置 `_abort_controller`）
- `restore()` (L396-399)：重置 `_abort_controller.reset()` + `_aborted=False` + `_abort_reason=""`

**影响**：双轨制需要 abort/restore/run 三处同步重置，存在一致性维护成本。当前实现中 `_throw_if_aborted` 只检查 `_aborted` 布尔，若仅 `_abort_controller.abort()` 被调用而 `_aborted` 未设（理论上的代码路径），runtime 主循环不会响应。实际 `abort()` 方法同时设置两者，无功能 bug，但抽象上不如 Cline 单一来源清晰。

**Charles 的优势**：`_aborted` 布尔提供了"快速路径"检查（无需访问 AbortController 实例），在主循环高频检查点开销略低。

### 差距 2：throwIfAborted 调用点缺失（对应对比项 2.6.4）

**Cline 调用点**（共 ~7 处）：
1. L633：主循环顶（每轮迭代开始）
2. L855：`prepareTurnForModelRequest` 之后
3. L862：每个 `before_model` hook 之后
4. L875：`captureTaskLifecycle(PROVIDER_REQUEST_STARTED)` 之前
5. L892：`captureTaskLifecycle(PROVIDER_STREAM_STARTED)` 之前
6. L914：stream 内每个 event 循环
7. L1087-1088：`openTaskLifecycleStream` 内 `model.stream(request)` 前后

**Charles 调用点**（共 2 处）：
1. runtime.py L630：主循环顶
2. runtime.py L910：stream 内每个 event 循环

**Charles 缺失的检查点**：
- `prepareTurnForModelRequest` 之后（Charles L854 无检查）
- 每个 `before_model` hook 之后（Charles L885 无检查）
- `captureTaskLifecycle` 对应位置（Charles 无 captureTaskLifecycle 抽象）
- `openTaskLifecycleStream` 内（Charles 无此抽象）

**影响**：在 `before_model` hook 执行耗时较长（如 ContextCompactor 压缩历史）时，用户 abort 后 Charles 需等 hook 完成才能响应，延迟可能达数秒。Cline 在每个 hook 后检查，响应延迟在毫秒级。

### 差距 3：stream 中途 abort 的优雅终止 vs 异常中断（对应对比项 2.6.7）

**Cline 设计**：stream 内每个 event 检查 `throwIfAborted()`（L914），触发时直接抛 `AgentRuntimeAbortError`，stream 被异常中断，已累积的 content parts 仍保留在 sequence 中由 catch 块处理。

**Charles 设计**：qwen.py L170-176 在 chunk 间隙检查 `abort_signal.is_set()`，触发时 **yield 一个 `finish` event**（reason=ABORTED, error="aborted by user"）再 `return`，stream 正常结束；runtime L910 `_throw_if_aborted` 检查到 `_aborted` 后抛 `RuntimeError`。

**差异分析**：
- Cline：1 次异常中断，stream 未发射 finish event
- Charles：2 次信号——先 yield finish event（让上层 `finish_reason` 处理逻辑看到 ABORTED），再由 runtime 抛异常

Charles 的设计在 finish event 中携带了 ABORTED reason，理论上让 `_generate_assistant_message` 的 finish_reason 处理逻辑（L638-639）能先处理 ABORTED 分支。但实际 L638-639 直接 `raise RuntimeError(self._abort_reason)`，与 L910 的 `_throw_if_aborted` 行为一致，未利用 finish event 的额外信息。

### 差距 4：缺失 TASK_CANCELLED_EVENT 遥测事件（对应对比项 2.6.10）

**Cline 设计**：`abort()` 内 L466-468 调用 `captureTaskLifecycle(TASK_CANCELLED_EVENT, {error: abortError})`，向上层遥测系统发送 task 取消事件，包含 error 详情、agentId、runId、iteration 等上下文。

**Charles 设计**：`abort()` 内不发射任何遥测事件；catch 块 L808-811 根据 `is_aborted` 决定 emit `run_failed`（失败）或 `run_finished`（中止）。

**影响**：Charles 缺失独立的 task 取消遥测事件，外部遥测系统无法区分"用户主动 abort"与"运行异常 failed"，只能通过 `result.status` 事后判断。Cline 的 TASK_CANCELLED_EVENT 在 abort 触发瞬间即上报，时序更精确。

## 4. nanobot 残留检查

### 检查范围

在 `agent/` 目录下执行 `grep -ri "nanobot"` 搜索，共发现 55 行 nanobot 残留。与 P2.6（restore + abort）**直接相关**的文件中：

| 文件 | 与 P2.6 关系 | nanobot 残留数 | 残留类型 |
|------|-------------|---------------|---------|
| `agent/abort.py` | 直接相关（AbortController 实现） | 0 | 无 |
| `agent/runtime.py` | 直接相关（abort/restore/_throw_if_aborted） | 0 | 无 |
| `agent/providers/qwen.py` | 间接相关（stream 中途 abort 检查） | 7 | 类型 A（实现来源标注） |
| `agent/tools/exec_tool.py` | 间接相关（tool 中途 abort kill 子进程） | 3 | 类型 A（实现来源标注） |

### 注释残留分类

#### 类型 A：实现来源标注（与 P2.6 间接相关）

形式：`对标 nanobot xxx 方法` / `对标 nanobot xxx.py L123-185`

出现在（与 abort/restore 间接相关部分）：
- `agent/providers/qwen.py` L21, L49, L116, L214, L253, L385, L406 — 说明 stream 实现参考了 nanobot openai_compat_provider.py
- `agent/tools/exec_tool.py` L8-10, L18-19 — 说明 ExecTool 实现参考了 nanobot shell.py，包括 `_wait_process_with_abort` 的设计来源标注（L142-147 标注"对标 run_commands._wait_process_with_abort"，run_commands 为 nanobot 模块名）

**性质**：纯注释，说明当前代码实现参考了 nanobot 的某个方法/文件，实际代码已用 Cline 对标设计重写。不影响运行时行为。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。所有 abort/restore 相关代码均基于 Cline 对标设计：
- `AbortController` 类（abort.py）对标 Cline `AbortController`（agent-runtime.ts L424）
- `AbortedError` 异常对标 Cline `AgentRuntimeAbortError`（agent-runtime.ts L249-265）
- `restore()` / `abort()` / `_throw_if_aborted()` 方法签名与逻辑均对标 Cline agent-runtime.ts
- `ExecTool._wait_process_with_abort` 对标 Cline BashTool 的 AbortSignal 响应逻辑
- 未发现任何从 nanobot 直接移植的 abort/restore 代码逻辑

### 残留风险评估

| 残留类型 | 文件数（与 P2.6 相关） | 风险等级 | 处理建议 |
|---------|----------------------|---------|---------|
| 类型 A（实现来源标注） | 2（qwen.py + exec_tool.py） | 低 | 可保留作为历史来源参考，或统一清理为"对标 Cline" |

## 5. 修复建议

### P0（高优先级，影响 abort 响应及时性）

无。当前 Charles 的 abort 机制功能完整，能在循环边界和 stream 内响应 abort，不影响运行时正确性。响应延迟差距在 hook 执行时间内（通常 < 1 秒）。

### P1（中优先级，改善 abort 响应延迟）

**建议 1：补齐 throwIfAborted 调用点（对应差距 2）**

参考 Cline agent-runtime.ts L855, L862, L875, L892，在 Charles runtime.py 的以下位置补充 `self._throw_if_aborted()` 调用：
- `_generate_assistant_message` 中 `before_model` hooks 循环内每个 hook 之后（对标 L862）
- `_generate_assistant_message` 中 `before_model` hooks 全部完成后、构建 stream 前（对标 L875）
- `prepareTurnForModelRequest` 调用后（若有此抽象，对标 L855）

**收益**：abort 响应延迟从"hook 执行完成"降到"单次 hook 执行完成"，提升长 hook 场景的用户体验。

**改动范围**：runtime.py `_generate_assistant_message` 方法内新增 2-3 行 `self._throw_if_aborted()`。

### P2（低优先级，改善抽象清晰度）

**建议 2：统一 AbortController 单一状态源（对应差距 1）**

参考 Cline 单一 `abortController.signal.aborted` 来源，将 Charles 的 `_throw_if_aborted` 改为检查 `self._abort_controller.is_set()`，逐步移除 `_aborted: bool` 双轨制。或反向：移除 `_abort_controller`，仅用 `_aborted` 布尔（但会失去向 stream/tool 透传 signal 的能力）。

**收益**：减少双轨制的一致性维护成本，避免未来修改时遗漏同步。

**注意**：此改动需谨慎评估，当前双轨制无功能 bug，改动风险高于收益。建议保留现状，在文档中明确双轨制设计。

### P3（可选，遥测对齐）

**建议 3：补充 TASK_CANCELLED 遥测事件（对应差距 4）**

参考 Cline `captureTaskLifecycle(TASK_CANCELLED_EVENT, ...)`，在 Charles `abort()` 内补充遥测事件发射（若有遥测系统接入）。

**收益**：外部遥测系统能在 abort 触发瞬间上报，时序精确。

**注意**：Charles 当前无 `captureTaskLifecycle` 抽象，需先评估是否引入遥测系统。

## 6. 验证方法建议

### 验证方法 1：abort 响应延迟测试

构造以下场景验证响应延迟差距：
1. 注册一个耗时 2 秒的 `before_model` hook（如 `async def hook(ctx): await asyncio.sleep(2)`）
2. 在 hook 执行 0.5 秒后调用 `runtime.abort("test")`
3. 测量从 `abort()` 调用到 `run()` 返回的时间

**预期**：
- Cline：在 hook 完成后立即检查 `throwIfAborted`，响应时间 ~1.5 秒（hook 剩余时间）
- Charles：在 hook 完成后进入 stream 才检查，响应时间 ~1.5 秒 + stream 首个 event 时间，差距在百毫秒级

### 验证方法 2：stream 中途 abort 行为对比

1. 配置 Qwen provider 流式生成
2. 在首个 text-delta event 到达后调用 `runtime.abort("test")`
3. 观察事件流：Charles 应先收到 `finish` event（reason=ABORTED），再收到 `run_finished`（status=aborted）；Cline 应直接收到 `run_finished`（status=aborted），无 `finish` event

**预期**：Charles 多一个 `finish` event with ABORTED reason。

### 验证方法 3：tool 中途 abort 子进程 kill 验证

1. 调用 `exec_tool` 执行 `sleep 30` 命令
2. 在命令执行 1 秒后调用 `runtime.abort("test")`
3. 检查子进程是否被 kill（通过 `ps aux | grep sleep` 或任务管理器）

**预期**：Charles `ExecTool._wait_process_with_abort` 在 abort 触发后 `process.kill()`，子进程立即终止；`run()` 返回 status=aborted。

### 验证方法 4：restore() 重置完整性测试

1. 运行一轮 agent，触发 `_mistake_tracker` 累积错误、`_loop_tracker` 记录循环、`_initial_messages_injected=True`、`_completion_reminder_injected=True`
2. 调用 `runtime.restore([])`
3. 检查所有 tracker 和注入标记是否重置

**预期**：Charles 的 `_mistake_tracker` / `_loop_tracker` / `_abort_controller` / `_aborted` / `_abort_reason` / `_initial_messages_injected` / `_completion_reminder_injected` 全部重置；Cline 的 tracker 不重置（由 SessionRuntime 持有），仅 runtime 级状态重置。

### 验证方法 5：多次 abort 幂等测试

1. 调用 `runtime.abort("reason1")`
2. 立即调用 `runtime.abort("reason2")`
3. 检查 `_abort_reason` 是否仍为 "reason1"

**预期**：Charles 三层幂等（`_aborted` 检查 + `AbortController._signal.is_set()` 检查）确保首次中止原因不被覆盖；`_abort_reason` 保持 "reason1"。
