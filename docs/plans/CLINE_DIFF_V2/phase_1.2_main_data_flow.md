# Phase 1.2 主数据流对比报告

## 说明

`AGENT_COMPARISON_PLAN_V2.md` 中 `P1.2` 的标题为“分层架构对比”，但本次任务按用户明确的“主数据流（用户输入 → AgentRuntime → LLM → 工具 → SSE → 前端）”维度执行，并参考计划中 `P2.2 主循环 run() 控制流对比`、`P2.3 _generate_assistant_message 流式组装对比`、`P2.4 _execute_tool_calls 工具执行对比`、`P2.9 事件系统 EventEmitter 对比` 的相关项。

## 1. 执行摘要

Charles 已将 Cline `AgentRuntime.execute()` 的主循环语义在 `agent/runtime.py::AgentRuntime.run()` 中对齐到函数级：运行初始化 → 输入注入 → `while` 主循环 → 流式生成 assistant 消息 → tool_call 提取/执行 → 完成或继续。事件系统（`agent/events.py`）与 Cline `AgentRuntimeEvent` 在生命周期事件、文本/推理增量、工具事件、用量事件上基本一致。

主要差异集中在 **传输层与运行时的耦合方式**：

- Cline 的运行时通过 `listeners` + `onEvent` hooks 将事件暴露给宿主，由 `apps/vscode`、`apps/cli` 等宿主决定如何向前端推送（WebView postMessage、CLI 打印等），运行时本身无 SSE 概念。
- Charles 将 SSE 生成器直接内嵌在 `agent/server.py` 中，`AgentRuntime` 通过 `EventEmitter` 发射事件，`server.py` 订阅后映射为 SSE 事件推送到前端。此外 `runtime.py` 还额外提供了 `register_sse_event_callback` 供 `file_context_tracker` 等 hook 直接绕过事件总线推送 SSE。

另外，`routes/chat.py` 仍是基于旧 `nanobot` 实现的遗留 SSE 路由，当前 `app.py` 已改用 `agent/server.py` 的 `/api/chat/stream`，但旧文件未删除，构成明显的历史残留与代码重复。

## 2. 逐项对比表

| # | 对比项 | Cline | Charles | 关键差异 | 一致性等级 |
|---|--------|-------|---------|---------|-----------|
| 1.2.1 | 用户输入入口 | 由宿主应用将输入传给 `AgentRuntime.execute(input)` | `agent/server.py::chat_stream` 接收 JSON，`history` 转消息，并在 HTTP 层用 `<user_input mode>` 标签包装消息 | Charles 输入格式化在 HTTP 路由层完成，Cline 由 runtime/host 处理 | 弱对齐 |
| 1.2.2 | `execute()` / `run()` 主循环结构 | `agent-runtime.ts` L595-794：`while maxIterations → throwIfAborted → turn-started → generateAssistantMessage → message-added → assistant-message → 无 tool_calls 则 completion_policy 判断/执行 tool_calls → turn-finished → findCompletingToolMessage` | `agent/runtime.py` L521-752：结构与 Cline 一致，额外注入 `initial_messages`、循环前 `completion_reminder`、无效 tool_call 处理、重复失败检测 | 控制流骨架一致；Charles 在主循环中叠加了更多业务增强 | 强对齐 |
| 1.2.3 | 运行前钩子与 `run-started` 时机 | `callBeforeRunHooks()` 后 `emit run-started`（L610-611） | `_call_before_run_hooks()` 后 `_emit(run-started)`（L559-562） | 顺序一致 | 强对齐 |
| 1.2.4 | `completion_tool` 提醒注入 | `getCompletionToolReminderMessage()` 在循环前追加 reminder（L622-625） | 循环前预注入 `_inject_completion_reminder`（L590-597），第一轮即提示必须以 completing tool 结束 | 语义一致，Charles 显式标记“预注入” | 强对齐 |
| 1.2.5 | `iteration` 自增与 while 条件 | `while maxIterations === undefined \|\| iteration < maxIterations`，自增在 `throwIfAborted` 之后（L629-635） | `while max_iterations is None or iteration < max_iterations`，自增在 `_throw_if_aborted` 之后（L626-632） | 一致 | 强对齐 |
| 1.2.6 | 流式消费与 `assistant-text-delta`/`assistant-reasoning-delta` | `generateAssistantMessage()` L913-962：逐 chunk 合并文本/推理 part 并发射 delta 事件 | `_generate_assistant_message()` L909-942：同样的合并与发射逻辑，并额外做 `_capture_unexpected_reasoning_tokens` | 基本一致；Charles 增加 finish 后 reasoning 碎片检测 | 强对齐 |
| 1.2.7 | `tool_call` 增量组装 key 策略 | `key = event.toolCallId ?? \`tool_${event.index ?? nextToolIndex}\``，仅当 index 与 toolCallId 均为空时自增 `nextToolIndex`（L966-970） | `key` 计算与自增逻辑完全复刻 Cline，使用 `is None` 避免 `index=0` 被误判（L950-960） | key 策略一致 | 强对齐 |
| 1.2.8 | `input_text` 累积方式 | `mergeToolInputText(assembly.inputText, event.inputText)`（L996-1000） | `assembly.input_text += event.input_text`（L978） | Cline 可能有去重/合并策略；Charles 为简单追加 | 弱对齐 |
| 1.2.9 | 流式 metadata 合并 | `mergeToolMetadata(assembly.metadata, event.metadata)`（L990-994） | `_deep_merge_metadata(assembly.metadata, event.metadata)`（L983-984） | 语义一致 | 强对齐 |
| 1.2.10 | `invalidToolCalls` 检测与反馈 | 缺少 `toolName` 或 JSON 解析失败时写入 `message.metadata.invalidToolCalls`，并在 `toolCallPart.metadata` 中保留 `inputParseError`/`rawInputText`（L1024-1050） | 检测到 missing_name/parse 失败后，既写入 `message.metadata.invalid_tool_calls`，又会立即构造错误 `tool-result` 消息追加到历史（L654-690） | Charles 反馈更激进（立即注入错误结果），Cline 留待下一轮统一处理 | 弱对齐 |
| 1.2.11 | `assistant-message` 与 `message-added` 顺序 | 先 `state.messages.push(message)`，再 `emit message-added`，再 `emit assistant-message`（L658-671） | 先 append，再 `message-added`，再 `assistant-message`（L659-669），注释明确“先通用后专用” | 一致 | 强对齐 |
| 1.2.12 | 无 `tool_calls` 分支 / `completion_policy` | 无 tool_calls 且 `requireCompletionTool` 为 true 时追加 reminder 并 `continue`；否则 `finishRun` + `run-finished`（L681-703） | 逻辑相同（L693-718），并额外发送 `turn-finished(0)` | 一致 | 强对齐 |
| 1.2.13 | `execute_tool_calls` 调用与并行执行 | `toolExecution === "parallel"` 时用 `Promise.all` 并行执行（L1299-1303），否则顺序执行 | `tool_execution == "parallel"` 时用 `asyncio.gather`（L1435-1439），否则顺序执行 | 都支持 parallel/sequential | 强对齐 |
| 1.2.14 | 工具执行的超时与重试 | `executePreparedTool` 内部使用 `withTimeout`（未在本次片段展开）；工具定义有 `retryable`/`maxRetries`，但 runtime 层未显式实现重试循环 | `_execute_with_timeout_and_retry()` 显式实现超时 `asyncio.wait_for` + 指数退避重试（L1918-2042），`retryable=True` 时按 `max_retries` 重试 | Charles runtime 层显式实现超时/重试；Cline 可能由工具内部或 host 处理 | 弱对齐 |
| 1.2.15 | `tool-started` / `tool-finished` 事件字段 | `tool-started` 携带完整 `toolCall` part；`tool-finished` 携带 `toolCall` + `message`（L1469-1557） | `tool-started` 携带 `tool_name`/`tool_call_id`/`tool_input`；`tool-finished` 携带序列化后的 `tool_output`/`is_error`/`duration_ms`（L1782-1910） | 字段结构不同，但语义等价 | 弱对齐 |
| 1.2.16 | `completes_run` 检测 | `findCompletingToolMessage()` 按顺序检查 `lifecycle.completesRun === true` 且结果非 error（L1312-1332） | `_find_completing_tool()` 同样按顺序检查 `lifecycle.completes_run` 与非 error（L2048-2074） | 一致 | 强对齐 |
| 1.2.17 | 事件发送顺序 | `run-started → message-added(input) → turn-started → deltas → message-added(assistant) → assistant-message → [tool-started → tool-finished → message-added(tool)] → turn-finished → run-finished` | 主顺序与 Cline 一致；额外在 assistant 后插入无效 tool 的 `message-added`，并在工具执行中通过 `STATUS_NOTICE` 发射 `approval_request` | 主顺序一致，Charles 额外事件穿插 | 强对齐 |
| 1.2.18 | 中止控制流 | `AbortController.signal` + `throwIfAborted()` 在循环顶、stream 中、tool 前检查（L588, L610, L634, L796 等） | `abort.py::AbortController` + `_throw_if_aborted()` 在循环顶与 stream 中检查；`_check_aborted()` 在工具内部检查 | 语义一致，`signal` 类型不同（`AbortSignal` vs `asyncio.Event`） | 强对齐 |
| 1.2.19 | 用量更新 | `usage` event 调用 `updateUsage()` | `usage` event 调用 `self._state.usage.add()` 并发射 `usage-updated` | 一致 | 强对齐 |
| 1.2.20 | 事件发射器 | `listeners` Set + `onEvent` hooks，`emit()` 同步调用 listeners 后 `await` hooks（L1605-1659） | `EventEmitter` 类，`subscribe()` 返回 unsubscribe，`emit()` 顺序 `await` 所有 listener，支持 `emit_sync()` 处理同步回调（`events.py` L128-227） | Charles 更偏向异步订阅模型，并提供 `emit_sync` 解决实时性问题 | 弱对齐 |
| 1.2.21 | 运行时 → 前端的传输层 | Cline 无内置 SSE，由宿主决定；典型路径为 `AgentRuntime` → `ClineCore`/`SessionRuntime` → VSCode webview postMessage / CLI stdout | `AgentRuntime` → `EventEmitter` → `agent/server.py` 订阅 → `asyncio.Queue` → `StreamingResponse` SSE → `static/js/ai-chat.js` | Charles 将运行时与 SSE 直接耦合；Cline 解耦 | 语义不等价 |
| 1.2.22 | SSE 事件映射 | 无固定 SSE 事件；宿主自行映射 | `agent/server.py::_handle_event()` 将 runtime 事件映射为 `phase`/`token`/`tool_call`/`tool_output`/`done`/`error` 等前端事件；token 缓冲 ≥3 字符才 yield（L848-854） | Charles 做了固定且简化的映射，并引入 token 缓冲，丢失 `turn-started`/`turn-finished`/`usage-updated`/`assistant-message` 等事件 | 弱对齐 |
| 1.2.23 | 前端事件消费 | VSCode/CLI 宿主消费原生事件 | `static/js/ai-chat.js::_handleSSEEvent()` 消费 `phase/token/plan/tool_call/tool_output/todos_updated/mode_changed/approval_request/terminal_output/file_context_updated/pending_prompts*` 等 | 前端事件类型更丰富，但与 Cline 事件模型不是一一映射 | 弱对齐 |
| 1.2.24 | 错误/异常捕获 | `catch` 块统一处理 aborted/failed，aborted 时 emit `run-finished`，failed 时 emit `run-failed`（L745-790） | 单独 catch `ControlledStopError` 返回 `status="completed"`；其他异常按 `is_aborted` 决定 `run-finished` 或 `run-failed`（L754-813） | Charles 显式区分 hook 主动 stop 与系统 abort，Cline 用 `ControlledStopError` 统一 catch | 弱对齐 |
| 1.2.25 | 旧 SSE 路由残留 | 无 | `routes/chat.py` 仍基于 `third_party/charles_bundle/charles-nanobot/agent.py` 的 `nanobot` 实现提供 `/api/chat/stream`（L351-374） | `app.py` 已改用 `agent/server.py` 的路由，`routes/chat.py` 未挂载但代码仍存在 | 缺失/残留 |

## 3. 重点差距详细说明

### 3.1 运行时与 SSE 传输层紧耦合

- **Cline**：`AgentRuntime` 只负责产生事件，通过 `listeners`/`onEvent` 暴露给宿主；`apps/vscode`、`apps/cli` 各自实现向前端推送的方式，运行时完全不感知网络协议。
- **Charles**：`agent/server.py` 直接订阅 `AgentRuntime` 事件并转换为 SSE。这种方式在单一 Web 宿主下工作良好，但导致：
  - 运行时无法脱离 FastAPI/SSE 被 CLI 或测试夹具复用；
  - `register_sse_event_callback`（L1248-L1275）让 `file_context_tracker` 等 hook 可以直接绕过事件总线推送 SSE，形成“运行时 → HTTP”的第二条路径，破坏事件系统单一出口原则。

### 3.2 SSE 事件映射丢失运行时语义

`agent/server.py::_handle_event()` 只转发有限几种事件：

- `ASSISTANT_TEXT_DELTA` / `ASSISTANT_REASONING_DELTA` → `token`（且缓冲 ≥3 字符）
- `TOOL_EXECUTION_STARTED` → `tool_call`
- `TOOL_EXECUTION_FINISHED` → `tool_output`
- `RUN_FINISHED` / `RUN_FAILED` → 仅刷新缓冲或发送 `error`
- `STATUS_NOTICE` / `TOOL_UPDATED` → 按 metadata 硬编码分发

以下 Cline 事件在前端不可见：

- `run-started`、`turn-started`、`turn-finished`
- `message-added`
- `assistant-message`
- `usage-updated`
- 通用的 `tool-started`/`tool-finished` 字段

这导致前端无法基于 `turn-finished` 做轮次边界展示，也无法显示 token 用量。

### 3.3 用户输入格式化位置偏移

Charles 在 `agent/server.py::_sse_generator()` 的 HTTP 层使用 `<user_input mode="...">` 标签包装用户输入（L595-L605）。Cline 的输入格式化通常由 runtime 层的 `prepareTurn` / `formatUserInputBlock` / host 投影完成。将格式逻辑放在 SSE 路由中，使得非 HTTP 调用 `AgentRuntime.run()` 时（如测试、CLI）无法复用相同的输入包装逻辑。

### 3.4 无效 tool_call 的处理粒度不同

Cline 将无效 tool_call 记录到 `assistantMessage.metadata.invalidToolCalls`，并在下一轮生成错误 tool result；Charles 会立即构造错误 tool result 并追加到历史（L683-690）。Charles 的方式可以更快让 LLM 看到错误，但也改变了消息历史的时序：在 Cline 中无效 tool_call 不立即产生 tool 消息，而 Charles 会。

### 3.5 遗留 `routes/chat.py` 与新 `agent/server.py` 并存

`routes/chat.py` 仍引用 `third_party/charles_bundle/charles-nanobot/agent.py` 并实现了旧版 `/api/chat/stream`。`app.py` 当前挂载的是 `agent/server.py` 的 router（L105），因此 `routes/chat.py` 是死代码，但保留了 `nanobot` 路径、导入和 `_StreamCollectorHook`，容易造成维护困惑。

## 4. nanobot 残留检查

在主数据流相关文件中发现以下 `nanobot` 命名残留：

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `routes/chat.py` | 4 | docstring “复用 Charles nanobot 的流式对话逻辑” | nanobot 残留 |
| `routes/chat.py` | 47-48 | `_CHARLES_AGENT_PY` 指向 `third_party/charles_bundle/charles-nanobot/agent.py` | 遗留路径依赖 |
| `routes/chat.py` | 92 | 动态模块名 `charles_nanobot_agent_...` | 遗留命名 |
| `routes/chat.py` | 159 | `_StreamCollectorHook` docstring “nanobot AgentHook” | nanobot 残留 |
| `agent/server.py` | 2、4、28 | docstring 提到“对标 Cline server + nanobot routes/chat.py”、“用 AgentRuntime 替换 nanobot” | nanobot 残留 |
| `agent/session.py` | 2、22 | docstring 提到“nanobot session_key” | nanobot 残留 |
| `agent/providers/qwen.py` | 21、49、116、214、253、385、406 | 多处注释“兼容 nanobot 现有配置”、“对标 nanobot ...” | nanobot 残留 |
| `agent/context.py` | 275 | 注释“[已废弃] nanobot 风格的额外段落” | nanobot 残留 |
| `agent/tools/__init__.py` | 2 | 模块 docstring “对标 Cline extensions/tools 和 nanobot agent/tools” | nanobot 残留 |
| `agent/tools/exec_tool.py` | 2、8-10、18-19、41、57、123、165、181、263 | 大量“nanobot ShellTool”对标说明 | nanobot 残留 |
| `agent/tools/file_tools.py` | 2、7、12、27、115、130、165 | 多处“nanobot FilesystemTool”对标说明 | nanobot 残留 |
| `agent/tools/web_tool.py` | 2、9-10、13、28、111、165 | 多处“nanobot WebSearchTool”对标说明 | nanobot 残留 |
| `agent/skills/loader.py` | 2、29、48、96、167、222、392、423 | 多处“nanobot SkillsLoader”对标说明 | nanobot 残留 |
| `agent/skills/registry.py` | 2、20、100、184 | docstring/注释提到“nanobot SkillsLoader” | nanobot 残留 |
| `agent/skills/__init__.py` | 2、23 | 类似 nanobot 对标说明 | nanobot 残留 |
| `agent/skills/skill_tool.py` | 18 | 提到“与 nanobot 的‘子 agent 隔离执行’有本质区别” | nanobot 残留 |

其中 **`routes/chat.py` 是主数据流层面最实质性的残留**：它仍试图加载旧的 nanobot agent bundle，而当前系统已全面切换到 `agent/runtime.py` + `agent/server.py`。

## 5. 修复建议

### P0（阻碍后续对比/集成）

1. **移除或归档 `routes/chat.py`**：当前 `app.py` 已使用 `agent/server.py`，旧路由不再挂载。应删除 `routes/chat.py` 或移入 `legacy/` 目录，避免与 `agent/server.py` 的 `/api/chat/stream` 产生路径和概念冲突。
2. **统一事件出口**：将 `register_sse_event_callback` / `_emit_sse_event` 机制替换为标准 `AgentEvent`（例如新增 `file-context-updated` 事件类型），让 `EventEmitter` 成为运行时事件的唯一出口，`server.py` 仅作为订阅者。
3. **恢复运行时事件完整性**：在 `agent/server.py::_handle_event()` 中补充转发 `run-started`、`turn-started`、`turn-finished`、`assistant-message`、`usage-updated` 等事件；前端 `ai-chat.js` 按需消费，避免当前 SSE 映射过度裁剪。

### P1（架构债务）

4. **将用户输入格式化下沉到 runtime**：把 `<user_input mode>` 包装逻辑从 `agent/server.py` 移到 `format_user_input_block` hook 或 `prepare_turn_input` hook，使非 HTTP 调用也能复用。
5. **降低 SSE token 缓冲延迟**：当前 `token_buf` 累积到 3 个字符才 yield，在低 token 输出场景会引入可感知延迟；建议改为按时间（如 50ms）或字符数双条件刷新。
6. **整理 `STATUS_NOTICE` / `TOOL_UPDATED` 硬编码分发**：`_handle_status_notice()` 中 `todos_updated`、`mode_changed`、`terminal_output` 等键名来自工具内部约定，应收敛到 `agent/events.py` 的显式事件类型或统一 schema，减少服务端与工具的隐式耦合。

### P2（功能增强）

7. **显式暴露 `toolExecution` 配置**：`_create_runtime()` 当前未设置 `tool_execution`，默认走 sequential；应在配置中提供环境变量或参数切换 parallel，并对只读工具默认并行执行。
8. **补齐前端事件展示**：在 `ai-chat.js` 中增加对 `turn-finished`、`usage-updated` 等事件的渲染，便于用户观察轮次边界和 token 消耗。

### P3（文档/规范）

9. **批量替换 nanobot 历史注释**：对 `agent/server.py`、`agent/providers/qwen.py`、各 `agent/tools/*.py`、`agent/skills/*.py` 中的 nanobot 对标说明，统一改为“Charles 历史实现”或直接删除。
10. **补充 `agent/SSE_DATA_FLOW.md`**：用序列图说明 `runtime → EventEmitter → server.py → SSE → ai-chat.js` 的数据流，以及 `register_sse_event_callback` 的临时路径，便于后续维护。

## 6. 验证方法建议

1. **事件顺序对比测试**：启动一次包含“文本 + 工具调用 + 完成”的运行，打印 `agent/events.py` 发射的所有事件序列，与 Cline `AgentRuntime` 的参考序列对比，确认 `run-started/turn-started/deltas/message-added/assistant-message/tool-started/tool-finished/turn-finished/run-finished` 顺序一致。
2. **SSE 映射验证**：用 `curl -N -H Accept:text/event-stream -d '{...}' http://localhost:7865/api/chat/stream` 抓取实际 SSE 事件，检查是否包含 `run-started`、`turn-finished`、`usage-updated` 等（修复后），并确认 `token` 事件没有明显延迟。
3. **tool_call 组装边界测试**：构造 dummy provider，返回仅有 `index=0`、无 `tool_call_id` 的 `tool-call-delta` 序列，验证 Charles 与 Cline 都能正确组装出 tool_call，且 `nextToolIndex` 递增逻辑正确。
4. **并行执行验证**：配置 `tool_execution="parallel"`，让 assistant 一次请求两个 `read_files` tool_call，记录耗时；与 sequential 模式对比，确认并行执行生效。
5. **中止响应测试**：在流式生成中途和工具执行中途分别调用 abort，验证 SSE 收到 `done`/`error`，且 `AgentRuntime` 状态正确重置。
6. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/ routes/chat.py` 并统计行数；删除 `routes/chat.py` 后确认无旧 bundle 路径引用。
7. **路由挂载确认**：检查 `app.py` 只 `include_router(agent_chat_router)`，确保 `/api/chat/stream` 实际由 `agent/server.py` 处理，而非 `routes/chat.py`。

---

*报告生成时间：2026-07-28*  
*覆盖文件：AGENT_COMPARISON_PLAN_V2.md §P2.2/P2.3/P2.4/P2.9、cline sdk `agent-runtime.ts`/`shared/src/agent.ts`、Charles `agent/runtime.py`/`agent/events.py`/`agent/server.py`/`routes/chat.py`/`static/js/ai-chat.js`/`app.py`*
