# Phase 1.3 事件系统顶层对比

> 对标视角：V1 功能结构 + V2 实现结构
> 目标：对比 Charles 与 Cline 的事件类型、EventEmitter、事件顺序、SSE 映射及 snapshot 引用语义
> 说明：本阶段在 AGENT_COMPARISON_PLAN_V2.md 中对应 P2.9 / P7.18 的事件系统对比项，按 Phase 1 输出格式整理为顶层对比表。

## 一、对标文件

| 角色 | 文件路径 | 说明 |
|------|---------|------|
| Cline 事件类型定义 | `third_party/cline/sdk/packages/shared/src/agent.ts` L466-550 | `AgentRuntimeEvent` 联合类型（14 个变体） |
| Cline Runtime 发射点 | `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` | `emit()` / `subscribe()` / 全部 `this.emit({...})` 调用点 |
| Charles 事件定义 | `agent/events.py` | 事件常量、`AgentEvent`、`EventEmitter` 及构造辅助函数 |
| Charles Runtime 发射点 | `agent/runtime.py` | `_emit()` 调用点（L562-L2197） |
| Charles SSE 映射 | `agent/server.py` | `_handle_event()` / `_sse_generator()` |
| Charles 核心类型 | `agent/types.py` | `AgentRuntimeStateSnapshot` / `AgentModelEvent` |

## 二、总体结论

| 维度 | 一致性评估 | 关键差距 |
|------|-----------|---------|
| 事件类型枚举 | **高（约 90%）** | 核心 14 个事件语义已对齐；工具事件命名不同（`tool-started` vs `tool-execution-started`）；Charles 额外扩展 5 个 compaction 事件 |
| EventEmitter 接口 | **中（约 75%）** | `subscribe` 返回值等价；Cline 用 `Set`、Charles 用 `list`；Charles 多了 `emit_sync` 和 SSE 回调机制；Cline 有 `onEvent` hook，Charles 缺失 |
| listener 异常处理 | **Charles 更健壮** | Cline 未捕获 listener 异常，单点失败会中断后续 listener 和 onEvent hooks；Charles 逐个 try/except 隔离 |
| 事件顺序 | **基本一致** | 两者都是顺序调用/await；Charles `emit_sync` 对 async listener 不 await，存在时序风险 |
| snapshot 引用语义 | **语义不等价** | Cline `snapshot()` 深拷贝 messages；Charles 仅 tuple 只读视图，内部 `AgentMessage` 对象仍共享引用 |
| SSE 映射 | **弱对齐** | Cline 由 core 层二次转换为 `CoreSessionEvent`；Charles 直接映射到前端 SSE，且扩展了排队/文件上下文等事件 |
| nanobot 残留 | **存在** | Charles 多个文件 docstring/注释仍保留 nanobot 历史引用，Cline 无 |

## 三、事件类型枚举对比

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性 | 差距描述 | 修复建议 |
|---|--------|-----------|-------------|--------|---------|---------|
| 1.1 | 事件总数 | 14 个 `AgentRuntimeEvent` 变体（`agent.ts` L466-550） | 14 个核心事件 + 5 个 compaction 事件（`events.py` L33-66） | 弱对齐 | 核心事件基本覆盖；Charles 额外扩展 compaction 生命周期事件 | 合理增强，保留 |
| 1.2 | `run-started` | `type: "run-started"`（`agent.ts` L468） | `RUN_STARTED = "run-started"`（`events.py` L33） | 完全一致 | 字段均含 `snapshot` | 无需修改 |
| 1.3 | `message-added` | `type: "message-added"`（`agent.ts` L472） | `MESSAGE_ADDED = "message-added"`（`events.py` L46） | 完全一致 | 均携带完整 `message` | 无需修改 |
| 1.4 | `turn-started` | `type: "turn-started"`（`agent.ts` L477） | `TURN_STARTED = "turn-started"`（`events.py` L38） | 完全一致 | 均含 `iteration` | 无需修改 |
| 1.5 | `assistant-text-delta` | `type: "assistant-text-delta"`（`agent.ts` L482） | `ASSISTANT_TEXT_DELTA = "assistant-text-delta"`（`events.py` L42） | 完全一致 | 均含 `text` / `accumulatedText` | 无需修改 |
| 1.6 | `assistant-reasoning-delta` | `type: "assistant-reasoning-delta"`（`agent.ts` L489） | `ASSISTANT_REASONING_DELTA = "assistant-reasoning-delta"`（`events.py` L43） | 完全一致 | 均含 `redacted` / `metadata` | 无需修改 |
| 1.7 | `assistant-message` | `type: "assistant-message"`（`agent.ts` L498） | `ASSISTANT_MESSAGE = "assistant-message"`（`events.py` L48） | 完全一致 | 均含 `finishReason` / `message` | 无需修改 |
| 1.8 | 工具开始事件 | `type: "tool-started"`（`agent-runtime.ts` L1469） | `TOOL_EXECUTION_STARTED = "tool-execution-started"`（`events.py` L51） | 风格差异 | 命名不同，语义等价；Cline 携带完整 `toolCall`，Charles 展开为 `tool_name` / `tool_call_id` / `tool_input` | 无需修改，SSE 层已统一映射 |
| 1.9 | 工具完成事件 | `type: "tool-finished"`（`agent-runtime.ts` L1552） | `TOOL_EXECUTION_FINISHED = "tool-execution-finished"`（`events.py` L52） | 风格差异 | 命名不同；Cline 携带 `toolCall` + `message`，Charles 展开为 `tool_output` / `tool_is_error` / `tool_duration_ms` | 无需修改，语义等价 |
| 1.10 | `tool-updated` | `type: "tool-updated"`（`agent.ts` L511） | `TOOL_UPDATED = "tool-updated"`（`events.py` L54） | 完全一致 | 均用于工具进度/状态更新 | 无需修改 |
| 1.11 | `usage-updated` | `type: "usage-updated"`（`agent.ts` L525） | `USAGE_UPDATED = "usage-updated"`（`events.py` L57） | 完全一致 | 均携带累计 usage | 无需修改 |
| 1.12 | `turn-finished` | `type: "turn-finished"`（`agent.ts` L530） | `TURN_FINISHED = "turn-finished"`（`events.py` L39） | 完全一致 | 均含 `iteration` / `toolCallCount` | 无需修改 |
| 1.13 | `status-notice` | `type: "status-notice"`（`agent.ts` L536） | `STATUS_NOTICE = "status-notice"`（`events.py` L58） | 完全一致 | 均用于中间状态通知 | 无需修改 |
| 1.14 | `run-finished` | `type: "run-finished"`（`agent.ts` L542） | `RUN_FINISHED = "run-finished"`（`events.py` L34） | 完全一致 | 均含 `result` | 无需修改 |
| 1.15 | `run-failed` | `type: "run-failed"`（`agent.ts` L547） | `RUN_FAILED = "run-failed"`（`events.py` L35） | 完全一致 | 均含 `error` | 无需修改 |
| 1.16 | compaction 事件 | 无（AgentRuntimeEvent 未包含；core 层有独立 context 事件） | `COMPACTION_STARTED` / `COMPLETED` / `SKIPPED` / `FAILED` / `BUDGET_ADJUSTED`（`events.py` L61-66） | 额外 | Charles 将压缩生命周期提升到 AgentRuntime 事件层，便于前端显示压缩进度 | 合理增强，保留 |

## 四、EventEmitter 接口对比

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性 | 差距描述 | 修复建议 |
|---|--------|-----------|-------------|--------|---------|---------|
| 2.1 | listener 存储结构 | `private readonly listeners = new Set<AgentEventListener>()`（`agent-runtime.ts` L399） | `self._listeners: list[EventListener] = []`（`events.py` L142） | 弱对齐 | Cline 用 Set 去重，Charles 用 list 允许重复订阅 | 如需要防重复，可改用 `dict` 或 `set` |
| 2.2 | `subscribe` 返回值 | 返回 unsubscribe 函数（`agent-runtime.ts` L472-477） | 返回 unsubscribe 函数（`events.py` L144-162） | 完全一致 | 两者 API 形式一致 | 无需修改 |
| 2.3 | unsubscribe 实现 | `Set.delete(listener)` O(1) | `list.remove(listener)` O(n)，且只删除第一个匹配项 | 弱对齐 | Charles 在重复 listener 场景下可能误删 | 如需要，改为按 id 或 set 管理 |
| 2.4 | `emit` 同步/异步 | `private async emit(event)`：`listeners` 同步调用，`hooks.onEvent` 顺序 await（`agent-runtime.ts` L1605-1659） | `async emit(event)`：顺序调用并 await 每个 listener（`events.py` L168-187） | 弱对齐 | Cline 的 listener 约定为同步 void；Charles 允许 async listener 并被 await | 明确 listener 语义即可 |
| 2.5 | `emit_sync` 机制 | 无 | `emit_sync(event)` 同步调用 listener，不 await async listener（`events.py` L189-221） | 额外 | Charles 为解决 `terminal_output` 实时推送问题引入；Cline 无此机制 | 属于 Charles 实现细节，保留 |
| 2.6 | listener 异常处理 | 未捕获 listener 异常，单点抛错会中断后续 listener 和 onEvent hooks | 每个 listener 独立 try/except，`traceback.print_exc()` 后继续（`events.py` L180-187） | 语义不等价 | Charles 更健壮；Cline 一个 listener 失败会影响全部 | 如需严格对齐 Cline，可保持现状；否则建议 Cline 侧也做隔离 |
| 2.7 | `onEvent` hook | `AgentRuntimeHooks.onEvent?` 在 emit 后被顺序 await（`shared/agent.ts` L364 / `agent-runtime.ts` L1656-1658） | `AgentHooks` / `HookBag` 均无 `on_event` 字段（`hooks.py` L304-313） | 缺失 | Charles 缺少与 `subscribe` 对应的 hook 级事件监听点 | 如需插件/遥测统一监听，可在 `HookBag` 中增加 `on_event` |
| 2.8 | 事件元数据/遥测 | `buildEventMetadata` + telemetry capture（`agent-runtime.ts` L1606-1652） | 无内置遥测元数据构建 | 缺失 | Cline 每次 emit 自动构建 metadata 并上报 telemetry；Charles 仅在 `TelemetryHooks` 中通过 hooks 间接记录 | 如需统一遥测，可在 `_emit` 中复用 metadata |
| 2.9 | SSE 主动推送回调 | 无 | `register_sse_event_callback()` / `_emit_sse_event()`（`runtime.py` L1248-L1269） | 额外 | Charles 为 `file_context_updated` 等非 runtime 事件提供单独推送通道 | 属于 Charles 体验增强，保留 |

## 五、事件顺序对比

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性 | 差距描述 | 修复建议 |
|---|--------|-----------|-------------|--------|---------|---------|
| 3.1 | 单轮内事件顺序 | `turn-started` → `message-added`(assistant) → `assistant-message` → `message-added`(tool) → `turn-finished`（`agent-runtime.ts` L636-721） | `turn-started` → `message-added`(assistant) → `assistant-message` → `message-added`(tool) → `turn-finished`（`runtime.py` L633-738） | 完全一致 | 顺序与 Cline 一致 | 无需修改 |
| 3.2 | 完成工具检测顺序 | `turn-finished` 先于 `run-finished` 发射，随后若检测到 completing tool 再发射 `run-finished`（`agent-runtime.ts` L716-738） | 同样先 `turn-finished` 后 `run-finished`（`runtime.py` L736-747） | 完全一致 | 顺序一致 | 无需修改 |
| 3.3 | 失败时事件互斥 | `failed` 发射 `run-failed`，`aborted` / `controlled_stop` 发射 `run-finished`（`agent-runtime.ts` L777-789） | `failed` 发射 `run-failed`，`aborted` 发射 `run-finished`（`runtime.py` L808-811） | 完全一致 | 互斥逻辑一致 | 无需修改 |
| 3.4 | `emit_sync` 时序 | 无 | `run_commands` 等工具通过 `emit_update` → `emit_sync` 推送 `TOOL_UPDATED`，不进入主 `await emit()` 队列（`runtime.py` L2194-2197） | 弱对齐 | `emit_sync` 与 `emit()` 混合使用，若 async listener 被调用但不 await，可能导致事件处理顺序与代码调用顺序不一致 | 文档化约束：emit_sync 的 listener 应为同步；或统一用 queue 保证顺序 |
| 3.5 | delta 事件顺序 | `assistant-text-delta` / `assistant-reasoning-delta` / `tool-call-delta` 按模型流顺序依次 emit（`agent-runtime.ts` L920-955） | 按 `AgentModelEvent` 流顺序依次 emit（`runtime.py` L922-989） | 完全一致 | 均保持模型原始顺序 | 无需修改 |

## 六、snapshot 引用语义对比

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性 | 差距描述 | 修复建议 |
|---|--------|-----------|-------------|--------|---------|---------|
| 4.1 | snapshot 类型 | `AgentRuntimeStateSnapshot.messages: readonly AgentMessage[]`（`agent.ts` L136） | `AgentRuntimeStateSnapshot.messages: tuple[AgentMessage, ...]`（`types.py` L392） | 风格差异 | 两者都表达只读视图 | 无需修改 |
| 4.2 | messages 拷贝深度 | `snapshot()` 内调用 `cloneMessages()`：新建 message 对象并浅拷贝 content parts（`agent-runtime.ts` L514） | `snapshot()` 仅 `tuple(self._state.messages)`，message 对象仍为内部引用（`runtime.py` L439） | 语义不等价 | Charles listener 若修改 message 内容会直接影响 runtime 内部状态；Cline 有防御性拷贝 | 在 Charles `snapshot()` 中增加 `clone_messages()`，与 Cline 对齐 |
| 4.3 | usage 拷贝 | `cloneUsage()` 浅拷贝（`agent-runtime.ts` L516） | `clone_usage()` 浅拷贝（`runtime.py` L441） | 完全一致 | usage 字段均为标量/简单值，浅拷贝足够 | 无需修改 |
| 4.4 | pendingToolCalls 拷贝 | `[...this.state.pendingToolCalls]`（`agent-runtime.ts` L515） | `tuple(self._state.pending_tool_calls)`（`runtime.py` L440） | 完全一致 | 均生成新容器 | 无需修改 |

## 七、SSE 映射对比

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性 | 差距描述 | 修复建议 |
|---|--------|-----------|-------------|--------|---------|---------|
| 7.1 | 映射层级 | `@cline/core` 通过 `RuntimeEventAdapter` 将 `AgentRuntimeEvent` 转换为 `CoreSessionEvent` 后再给宿主 | `server.py::_handle_event()` 直接映射 `AgentEvent` → SSE（`server.py` L833-907） | 弱对齐 | Charles 缺少 core 层的事件适配抽象 | 如需多宿主复用，可抽取独立 adapter |
| 7.2 | `run-started` | 无直接 SSE 映射（由宿主决定） | 不单独映射，外部已发送 `phase: thinking`（`server.py` L683 / L843-845） | 弱对齐 | Charles 在 SSE 层前置发送 thinking 阶段，不依赖 runtime 事件 | 当前实现满足前端，保留 |
| 7.3 | `assistant-text-delta` / `assistant-reasoning-delta` | 宿主侧缓冲为 token 流 | 缓冲 `token_buf` 到 >=3 字符后 yield `token`（`server.py` L847-853） | 弱对齐 | 缓冲策略不同（Cline 由宿主决定，Charles 固定 3 字符阈值） | 如需对齐，可将缓冲阈值做成配置 |
| 7.4 | `tool-execution-started` | 映射为工具开始 UI 事件 | 映射为 `tool_call` SSE，含 `name` / `args` / `idx`（`server.py` L855-868） | 弱对齐 | 字段结构不同，但信息等价 | 无需修改 |
| 7.5 | `tool-execution-finished` | 映射为工具完成 UI 事件 | 映射为 `tool_output` SSE，含 `output` / `error` / `idx`（`server.py` L870-877） | 弱对齐 | 字段结构不同，信息等价；Charles 对输出做 2000 字符截断 | 截断阈值可配置化 |
| 7.6 | `run-finished` | 映射为会话结束事件 | 刷新 token 缓冲后进入 `phase: answering` + 最终 `done`（`server.py` L879-883 / L746 / L830） | 弱对齐 | Charles 的 `done` 在 turn queue 消费完所有排队消息后才发送 | 无需修改 |
| 7.7 | `run-failed` | 映射为 error 事件 | 刷新缓冲后 yield `error` SSE（`server.py` L885-892） | 一致 | 均向前端暴露错误 | 无需修改 |
| 7.8 | `STATUS_NOTICE` / `TOOL_UPDATED` | 无直接映射（由宿主或 hook 消费） | 复用 `_handle_status_notice()` 分发为 `approval_request` / `todos_updated` / `mode_changed` / `terminal_output`（`server.py` L894-907） | 额外 | Charles 扩展了多种前端实时事件，Cline 无 | 合理增强，保留 |
| 7.9 | 排队消息事件 | core 层 `PendingPromptService`  emit `pending_prompts_updated` | `server.py` 直接 yield `pending_prompts` / `pending_prompt_submitted`（`server.py` L780-789） | 弱对齐 | Charles 在 SSE 生成器内部直接处理排队消息事件，未经过 runtime 事件层 | 如需统一，可引入事件层转发 |
| 7.10 | 非 runtime 主动推送 | core 层通过 `session-event-projector` 统一投影 | `runtime.register_sse_event_callback()` 直接入队 `sse_event_queue`（`server.py` L652-662 / L717-739） | 额外 | Charles 为文件上下文等事件开了旁路通道 | 保留，但需确保与主事件顺序不冲突 |

## 八、nanobot 残留引用

| # | 对比项 | Cline | Charles | 一致性 | 差距描述 | 修复建议 |
|---|--------|-------|---------|--------|---------|---------|
| 8.1 | 事件/服务端注释 | 无 nanobot 引用 | `agent/server.py` L2/L4/L28 仍出现 "nanobot routes/chat.py"、"替换 nanobot" 等注释 | 风格差异 | 历史迁移注释未清理，不影响运行 | 清理 docstring/注释中的 nanobot 历史描述 |
| 8.2 | 工具层注释 | 无 | `agent/tools/exec_tool.py`、`file_tools.py`、`web_tool.py` 等多处 docstring 含 "nanobot" | 风格差异 | 工具实现注释仍保留旧系统对标说明 | 逐步清理，保留 Cline 对标说明即可 |
| 8.3 | 技能/会话层注释 | 无 | `agent/skills/*.py`、`agent/session.py`、`agent/context.py` 等含 nanobot 引用 | 风格差异 | 历史参照注释 | 按 F-base 清理计划移除 |
| 8.4 | 遗留 sub_agent 文件 | 无 | `agent/sub_agent.py` / `sub_agent_worker.py` 仍保留（`AGENT_COMPARISON_PLAN_V2.md` P7.19 已记录） | 缺失 | 旧 nanobot 子 agent 实现未删除 | 确认无引用后删除 |

## 九、修复建议汇总

| 优先级 | 修复项 | 影响文件 | 说明 |
|--------|--------|---------|------|
| P1 | `snapshot()` 增加 messages 防御性拷贝 | `agent/runtime.py` | 与 Cline 语义对齐，防止 listener 误改内部状态 |
| P2 | 清理 nanobot 历史注释 | `agent/server.py`、`agent/tools/*.py`、`agent/skills/*.py` 等 | 按 F-base 清理计划执行，保留 Cline 对标说明 |
| P2 | 明确 `emit_sync` 使用约束 | `agent/events.py`、`agent/runtime.py` | 在注释中说明 async listener 不应依赖 `emit_sync` 的 await 语义 |
| P3 | 评估 EventEmitter 是否去重 | `agent/events.py` | 如 Cline `Set` 语义需要，可用 `dict` 替换 `list` |
| P3 | 可选：增加 `on_event` hook | `agent/hooks.py`、`agent/runtime.py` | 与 Cline `AgentRuntimeHooks.onEvent` 对齐，便于插件统一监听 |
| P3 | 可选：SSE 缓冲阈值配置化 | `agent/server.py` | 将 token 缓冲 3 字符阈值做成配置 |

## 十、验证方法

1. **事件序列对比**：构造相同输入，订阅 Cline `agent.subscribe()` 与 Charles `runtime.subscribe()`，记录 `event.type` 序列，确认 14 个核心事件顺序一致。
2. **snapshot 引用测试**：在 listener 中修改 `event.snapshot.messages[0].content[0].text`，检查是否影响 runtime 内部 messages。
3. **listener 异常隔离测试**：注册一个抛错的 listener 后再注册正常 listener，Cline 应中断，Charles 应继续。
4. **SSE 映射验证**：启动 Charles server，调用 `/api/chat/stream`，检查 `phase/token/tool_call/tool_output/done` 序列与 Cline 宿主层输出一致。
5. **nanobot 清理验证**：`grep -R "nanobot" agent/` 仅保留必要的 Cline 对标说明，其余移除。
