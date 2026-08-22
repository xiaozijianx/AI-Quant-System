# Agent 实现 vs Cline 源码：分阶段逻辑级对比计划

> 生成时间：2026-07-26
> 目标：从代码级、逻辑级细节评估当前 agent 实现与 Cline 的差距
> 原则：**不停留在"模块有无"层面**，深入到每个函数的逻辑分支、数据流、状态变迁、错误处理等细节
> 用法：每个阶段独立可执行，按优先级或依赖关系逐步推进

---

## 一、对比方法论

### 1.1 逻辑级对比维度（每阶段都需覆盖）

每个对比项不止问"有没有"，而要逐项验证以下 7 个维度：

| 维度 | 含义 | 示例 |
|------|------|------|
| **D1 数据结构** | 字段是否齐全、类型是否等价、可选性是否一致 | `AgentToolContext` 字段对比 |
| **D2 控制流** | 分支条件、循环边界、提前返回、异常路径 | `run()` 主循环的 abort 检查点 |
| **D3 状态变迁** | 状态字段何时变更、变更顺序、并发安全 | `status` 从 running→completed 的路径 |
| **D4 错误处理** | 异常捕获范围、错误传播、降级策略 | LLM 调用失败时的 retry vs abort |
| **D5 副作用** | 事件发射、持久化、日志、外部调用时机 | emit 事件的顺序保证 |
| **D6 边界条件** | 空值、超长、越界、并发、超时 | 0 条消息、max_iterations 边界 |
| **D7 语义等价** | 同名方法/字段的行为是否真正等价 | `restore()` 是否真的清空 usage |

### 1.2 验证手段

- **静态对比**：源码逐行 diff（人工 + Grep）
- **动态验证**：构造相同输入，对比两边输出/事件流
- **边界测试**：构造极端场景（空消息、超长、并发 abort）
- **回归测试**：`python tests/test_agent_e2e.py` + 新增针对性测试

### 1.3 对比记录格式

每阶段输出一份 `CLINE_DIFF_phaseN.md`，含：

```markdown
| 对比项 | Cline 实现 | 我的实现 | 一致性 | 差距描述 |
|--------|-----------|---------|--------|---------|
| ...    | L123-145  | L200-220 | 一致/弱/缺失 | ... |
```

---

## 二、阶段总览（26 个阶段，按 Cline 架构分层）

| 阶段 | 主题 | Cline 主对标 | 优先级 | 依赖 |
|------|------|-------------|--------|------|
| **A** | 类型系统与消息契约 | `shared/agent.ts` + `shared/llms/*.ts` | P0 | 无 |
| **B** | AgentRuntime 主循环 | `agents/agent-runtime.ts` L595-794 | P0 | A |
| **C** | 流式工具调用组装 | `agents/agent-runtime.ts` L965-1058 | P0 | A, B |
| **D** | 事件系统 | `agents/agent-runtime.ts` emit 点 + `shared/agent.ts` | P0 | A |
| **E** | Hooks 生命周期 | `shared/agent.ts` L265-364 + runtime hook 调用点 | P0 | A, B |
| **F** | 工具系统基础设施 | `shared/tools/create.ts` + `core/extensions/tools/runtime.ts` | P0 | A |
| **G** | 内置工具逐项（read_files/run_commands/editor/apply_patch） | `core/extensions/tools/executors/` | P0 | F |
| **H** | 内置工具逐项（search/list/ask/submit/attempt/todo/plan_mode） | `core/extensions/tools/definitions.ts` | P1 | F |
| **I** | 技能系统 | `core/extensions/config/user-instruction-plugin.ts` | P0 | F |
| **J** | 上下文压缩 | `core/extensions/context/compaction*.ts` | P0 | A, B |
| **K** | Budget Projection | `core/extensions/context/budget-projection/` | P1 | J |
| **L** | 系统提示构造 | `core/runtime/orchestration/runtime-builder.ts` + `shared/prompt/` | P0 | I, J |
| **M** | 循环检测 + MistakeTracker | `core/runtime/safety/` | P0 | E |
| **N** | AbortController 与中止语义 | `agents/agent-runtime.ts` L424-470 | P0 | B |
| **O** | Turn Queue 用户输入排队 | `core/runtime/turn-queue/pending-prompt-service.ts` | P1 | B |
| **P** | 文件 Hooks 系统 | `apps/vscode/src/core/hooks/` + `core/src/hooks/` | P0 | E |
| **Q** | MCP 集成 | `core/extensions/mcp/` | P1 | F |
| **R** | LLM Provider 适配 | `core/services/llms/` + `shared/llms/gateway.ts` | P0 | A |
| **S** | 会话持久化与锁 | `core/services/storage/sqlite-session-store.ts` + `apps/vscode/SqliteLockManager.ts` | P1 | A |
| **T** | Checkpoint 机制 | `apps/vscode/src/core/controller/checkpoints/` + shadow-git | P2 | S |
| **U** | 审批机制 + ToolPolicies | `core/runtime/tools/tool-approval.ts` + `extensions/tools/presets.ts` | P1 | F |
| **V** | Sub-agent / 多 Agent | `core/extensions/tools/team/` | P2 | B, F |
| **W** | FileContextTracker | `apps/vscode/src/core/context/context-tracking/` | P1 | J |
| **X** | Cline Rules / Frontmatter / Workflows | `apps/vscode/src/core/context/instructions/user-instructions/` | P1 | L |
| **Y** | Plugin / Marketplace 系统 | `core/extensions/plugin/` + `apps/vscode/marketplace/` | P3 | F |
| **Z** | Telemetry / Connectors / Kanban / Hub | `core/services/telemetry/` + `apps/cli/connectors/` + `core/src/hub/` | P3 | 无 |

---

## 三、阶段详情

### 阶段 A：类型系统与消息契约对比

**对标 Cline 源码**：
- `sdk/packages/shared/src/agent.ts`（核心类型）
- `sdk/packages/shared/src/llms/messages.ts`（消息结构）
- `sdk/packages/shared/src/llms/tools.ts`（工具类型）
- `sdk/packages/shared/src/llms/requests.ts`（请求/响应）

**当前实现**：`agent/types.py`

**对比维度（逐项验证 D1-D7）**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| A1 | `MessageRole` 枚举值 | agent.ts L50-60 | types.py L? | 是否含 system/user/assistant/tool，string enum 语义 |
| A2 | `TextPart`/`ReasoningPart`/`ToolCallPart`/`ToolResultPart` 字段 | messages.ts 全文 | types.py | `redacted`/`provider_metadata` 等可选字段是否齐全 |
| A3 | `ToolCallPart` 的 `input` 类型 | messages.ts | types.py | Cline 是 `Record<string, unknown>`，我的实现是否等价 |
| A4 | `ToolCallPart` 的 `partial_input` 字段 | messages.ts | types.py | 流式累积用，是否有等价机制 |
| A5 | `AgentToolDefinition` 字段 | agent.ts L146-186 | types.py | `name`/`description`/`input_schema`/`lifecycle`/`timeout_ms`/`retryable`/`max_retries` |
| A6 | `ToolLifecycle` 完整字段 | agent.ts L150-155 | types.py | 是否只有 `completes_run`，还是有更多（如 `blocking`） |
| A7 | `AgentToolContext` 字段 | agent.ts L170-186 | types.py | `session_id`/`agent_id`/`run_id`/`iteration`/`signal`/`snapshot`/`emit_update` 是否齐全 |
| A8 | `AgentModelRequest` 字段 | agent.ts L192-220 | types.py | `system_prompt`/`messages`/`tools`/`options`/`signal`/`tool_choice` |
| A9 | `AgentModelEvent` 类型枚举 | agent.ts L232-257 | types.py | `text-delta`/`reasoning-delta`/`tool-call-delta`/`usage`/`finish`/`error` 是否齐全 |
| A10 | `AgentModelFinishReason` 枚举 | agent.ts L259-265 | types.py | 是否含 `stop`/`tool-calls`/`max-tokens`/`aborted`/`error`/`content-filter` |
| A11 | `AgentUsage` 字段 | agent.ts L280-290 | types.py | `input_tokens`/`output_tokens`/`cache_read`/`cache_write`/`reasoning_token_count`/`total_cost` |
| A12 | `AgentRuntimeStateSnapshot` 字段 | agent.ts L300-320 | types.py | `status` 枚举值是否齐全（idle/running/completed/aborted/failed/paused） |
| A13 | `AgentRunResult` 字段 | agent.ts L330-345 | types.py | `error` 类型（Exception vs Error 对象）|
| A14 | `CompletionPolicy` 字段 | agent.ts L430-433 | types.py | `require_completion_tool` + `completion_guard` 回调 |
| A15 | 消息不可变性语义 | messages.ts | types.py | Cline 用 readonly/freeze，我用 dataclass 是否有等价保护 |
| A16 | `AgentTool` Protocol 方法签名 | agent.ts L146 | types.py | `execute` 返回 `AsyncIterator` vs `AgentToolResult`，Cline 是否支持流式工具 |

**验证方法**：
- Grep 两边文件，逐字段填表
- 构造边界场景：空 messages、空 tools、null signal
- 检查 Python dataclass 默认值是否与 TypeScript 接口默认值语义等价

**预期产出**：字段差异表 + 缺失字段清单 + 语义不等价项

---

### 阶段 B：AgentRuntime 主循环对比

**对标 Cline 源码**：`sdk/packages/agents/src/agent-runtime.ts` L595-794

**当前实现**：`agent/runtime.py::AgentRuntime.run()`

**对比维度**：

| # | 对比项 | Cline 行号 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| B1 | `execute()` 入参类型 | L595-600 | runtime.py | 接受 `string | AgentMessage | list[AgentMessage]`，我接受什么 |
| B2 | 主循环 `while` 条件 | L600-610 | runtime.py | `iteration < maxIterations && !aborted && !stopped`，三个条件的顺序 |
| B3 | `throwIfAborted()` 调用点 | L588-593, L610, L796 | runtime.py | 在循环顶端、stream 中途、tool 执行前各检查一次？ |
| B4 | `emit run_started` 时机 | L611 | runtime.py | 在 hooks 调用前还是后 |
| B5 | `callBeforeRunHooks` 返回 stop 时行为 | L612-620 | runtime.py | 是否立即 finish_run，status 是什么 |
| B6 | 添加 user message 的位置 | L625-640 | runtime.py | 是否经过 `formatUserInputBlock` 钩子 |
| B7 | `generateAssistantMessage()` 调用 | L645-660 | runtime.py | 返回 `(message, finish_reason)` 元组 |
| B8 | `emit message_added` 时机 | L660 | runtime.py | assistant message 添加后立即 emit 还是 batch |
| B9 | 无 tool_calls 时的分支 | L665-680 | runtime.py | 走 `completion_policy` 还是直接 finish |
| B10 | `completion_policy.require_completion_tool` 逻辑 | L670-678 | runtime.py | True 时追加 reminder 消息，False 时 finish |
| B11 | `completion_guard` 回调调用 | L675 | runtime.py | 是否真的调用 guard 函数判断 |
| B12 | `executeToolCalls()` 调用 | L685-700 | runtime.py | parallel vs sequential 模式选择 |
| B13 | `findCompletingToolMessage()` | L1312-1332 | runtime.py | 检查 `lifecycle.completes_run` 且 `!is_error` |
| B14 | completes_run 成功后 finish 语义 | L700-710 | runtime.py | status 是 `completed` 还是 `completed_with_tool` |
| B15 | `emit turn_finished` 时机 | L730 | runtime.py | 每轮结束都 emit 还是仅在 finish 时 |
| B16 | max_iterations 超限处理 | L790-794 | runtime.py | status 是 `failed` 还是 `max_iterations_exceeded`，是否 emit run_failed |
| B17 | 异常捕获范围 | L796-809 | runtime.py | try/except 包裹范围，哪些异常会被吞掉 |
| B18 | `finally` 清理逻辑 | L805-809 | runtime.py | status 重置、emit run_finished、unsubscribe |
| B19 | `consumePendingUserMessage` 调用 | L841-852 | runtime.py | iteration > 1 时检查 steer delivery |
| B20 | `iteration` 自增时机 | L605 | runtime.py | 在 hooks 前 vs 后，影响 hook 看到的 iteration 值 |

**验证方法**：
- 画两边的控制流图，逐节点对比
- 构造 max_iterations 边界测试
- 构造 abort 在 stream 中途、tool 中途、hooks 中途的场景
- 检查 emit 事件顺序（用 listener 记录所有事件 type 序列）

---

### 阶段 C：流式工具调用组装对比

**对标 Cline 源码**：`sdk/packages/agents/src/agent-runtime.ts` L965-1058

**当前实现**：`agent/runtime.py::_generate_assistant_message()` + `agent/providers/qwen.py`

**对比维度**：

| # | 对比项 | Cline 行号 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| C1 | `PendingToolAssembly` 数据结构 | L965-980 | runtime.py | 字段：`tool_call_id`/`tool_name`/`input_text`/`input_value`/`index` |
| C2 | 组装 key 策略 | L985-1000 | runtime.py | Cline 用 `toolCallId ?? tool_${index}`，我用什么 |
| C3 | `tool_call_id` 不稳定处理 | N/A（Cline 不需要） | qwen.py | Qwen 特殊处理：按 index 维护 map |
| C4 | `input_text` 增量累积 | L1000-1020 | runtime.py | 字符串拼接 vs Buffer |
| C5 | 增量 JSON parse 尝试 | L1020-1030 | runtime.py | 流式过程中是否尝试 parse 部分 JSON |
| C6 | `invalidToolCalls` 检测 | L1031-1058 | runtime.py | 什么条件算 invalid（空 name、parse 失败、schema 不匹配） |
| C7 | `invalidToolCalls` 反馈机制 | L1040-1050 | runtime.py | 写入 `message.metadata`，下一轮生成错误 result message |
| C8 | tool_call 完成判定 | L1050-1058 | runtime.py | finish 事件 vs input 解析完成 |
| C9 | `tool_name` 为空时行为 | L1035 | runtime.py | 跳过、报错、还是计入 invalid |
| C10 | 多 tool_call 并发组装 | L965-1000 | runtime.py | 多个 PendingToolAssembly 并存，按 index 区分 |
| C11 | `usage` event 处理 | L302-347 | runtime.py | 累积 vs 替换，零值过滤 |
| C12 | `reasoning_delta` 累积 | L1015-1020 | runtime.py | 是否单独累积成 ReasoningPart |
| C13 | `finish` event 处理 | L1080-1090 | runtime.py | finish_reason 提取，stream 结束判定 |

**验证方法**：
- 用 dummy model 构造流式分片（每个 delta 只含部分 input JSON）
- 对比两边最终组装出的 ToolCallPart
- 构造 invalid tool_call（空 name、JSON 不完整）
- 测 Qwen 特殊场景：tool_call_id 只在首 delta 出现

---

### 阶段 D：事件系统对比

**对标 Cline 源码**：
- `sdk/packages/agents/src/agent-runtime.ts`（emit 调用点散落全文）
- `sdk/packages/shared/src/agent.ts`（事件类型定义）

**当前实现**：`agent/events.py`

**对比维度**：

| # | 对比项 | Cline | 我的位置 | 关键逻辑点 |
|---|--------|-------|---------|-----------|
| D1 | 事件类型枚举完整性 | agent.ts | events.py | run_started/turn_started/assistant_text_delta/assistant_reasoning_delta/message_added/turn_finished/run_finished/run_failed/tool_execution_started/tool_execution_finished/usage_updated/status_notice 是否齐全 |
| D2 | `AgentEvent` 字段 | agent.ts | events.py | `type`/`snapshot`/`iteration`/`text`/`accumulated_text`/`message`/`finish_reason`/`tool_call_count`/`result`/`error`/`metadata` |
| D3 | `EventEmitter.subscribe` 返回值 | agent-runtime.ts L399 | events.py | 返回 unsubscribe 函数 |
| D4 | `emit()` 同步 vs 异步 | L611 etc. | events.py | Cline emit 是同步还是异步，listener 是 await 还是 fire-and-forget |
| D5 | listener 异常处理 | L611-620 | events.py | 一个 listener 抛错是否影响其他 listener |
| D6 | 事件顺序保证 | 全文 | events.py | 同步 emit 顺序 vs 异步 task 顺序 |
| D7 | `snapshot` 在事件中的角色 | agent.ts | events.py | 是引用还是深拷贝，listener 修改 snapshot 是否影响 runtime |
| D8 | `accumulated_text` 语义 | agent.ts | events.py | 是当前 delta 文本还是累积全文 |
| D9 | `message_added` 触发时机 | L660, L720 | events.py | assistant message 和 tool message 都 emit 吗 |
| D10 | `status_notice` 用途 | agent.ts | events.py | Cline 用它做什么，我是否等价 |
| D11 | 事件批量 vs 单发 | 全文 | events.py | 是否有 batch event 机制 |
| D12 | `tool_execution_started` 字段 | agent.ts | events.py | 含哪些 metadata（tool_name/args/idx） |
| D13 | `run_failed` vs `run_finished` 互斥 | L796-809 | events.py | 失败时是否只 emit 一个 |

**验证方法**：
- 订阅所有事件，记录 type 序列，对比两边
- 构造 listener 抛错场景
- 检查 snapshot 引用语义（修改 listener 收到的 snapshot）

---

### 阶段 E：Hooks 生命周期对比

**对标 Cline 源码**：
- `sdk/packages/shared/src/agent.ts` L265-364（HookBag + 9 个钩子点）
- `sdk/packages/agents/src/agent-runtime.ts` L229-237, L544-554, L796-809（注册与调用）

**当前实现**：`agent/hooks.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| E1 | 9 个钩子点枚举 | agent.ts L265-364 | hooks.py | before_run/after_run/before_model/after_model/before_tool/after_tool/prepare_turn_input/format_user_input_block/before_approval |
| E2 | `BeforeRunContext` 字段 | agent.ts | hooks.py | `snapshot` |
| E3 | `BeforeModelContext` 字段 | agent.ts | hooks.py | `snapshot`/`request`/`session_id`（Cline 是否含 session_id） |
| E4 | `BeforeModelResult` 字段 | agent.ts | hooks.py | `stop`/`reason`/`messages`/`tools`/`options`，是否能修改 system_prompt |
| E5 | `BeforeToolContext` 字段 | agent.ts | hooks.py | `snapshot`/`tool`/`tool_call`/`input` |
| E6 | `BeforeToolResult` 字段 | agent.ts | hooks.py | `skip`/`stop`/`reason`/`input`（能否修改工具入参） |
| E7 | `AfterToolResult` 字段 | agent.ts | hooks.py | `stop`/`reason`/`result`（能否修改工具结果） |
| E8 | 钩子执行顺序 | L544-554 | hooks.py | 同一钩子点多个 hook 的执行顺序（注册序 vs 优先级） |
| E9 | 钩子失败处理 | L544-554 | hooks.py | 一个 hook 抛错是否中断后续 hook |
| E10 | `prepare_turn_input` 调用时机 | L841-852 | runtime.py | 在 model.stream 前，能修改 user input |
| E11 | `format_user_input_block` 作用 | L625-640 | runtime.py | 包装用户输入为特定格式（如 `<user_input mode>`） |
| E12 | `before_approval` 与 toolPolicies 关系 | agent.ts | hooks.py + approval.py | Cline 用 config 回调，我用 hook，语义是否等价 |
| E13 | 钩子返回 `None` 语义 | L544-554 | hooks.py | None = 继续不修改 vs 显式返回 result |
| E14 | 异步钩子 vs 同步钩子 | agent.ts | hooks.py | Cline 是否区分 async hook |
| E15 | `on_task_resume` / `on_task_cancel` | apps/vscode hooks | hooks.py | Cline 在哪触发，我是否对齐 |

**验证方法**：
- 注册多个同类型 hook，看执行顺序
- 构造 hook 抛错，看后续 hook 是否执行
- 检查 `BeforeModelResult.messages` 修改是否真的影响下一轮 LLM 请求

---

### 阶段 F：工具系统基础设施对比

**对标 Cline 源码**：
- `sdk/packages/shared/src/tools/create.ts`（createTool 工厂）
- `sdk/packages/core/src/extensions/tools/runtime.ts`（ToolRuntime）
- `sdk/packages/core/src/extensions/tools/definitions.ts`（工具定义）
- `sdk/packages/core/src/extensions/tools/schemas.ts`（zod schema）

**当前实现**：`agent/tools/base.py` + `agent/tools/__init__.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| F1 | `createTool()` 工厂签名 | create.ts | base.py | 接收 `name`/`description`/`inputSchema`/`execute`/`lifecycle`/`timeoutMs` 等 |
| F2 | `AgentTool` 接口方法 | create.ts | base.py | `execute` 返回 `AsyncIterator<AgentToolResult>` vs `AgentToolResult` |
| F3 | 工具流式输出支持 | create.ts | base.py | Cline 工具能否 yield 多个 result（进度更新） |
| F4 | `lifecycle.completesRun` 语义 | definitions.ts | base.py | 执行成功才 completes 还是无论成败 |
| F5 | `lifecycle.blocking` 字段 | definitions.ts | base.py | 是否有阻塞 UI 的标记 |
| F6 | `timeoutMs` per-tool | definitions.ts | base.py | 默认值、覆盖语义 |
| F7 | `retryable` + `maxRetries` | definitions.ts | base.py | 重试间隔、哪些错误可重试 |
| F8 | `withTimeout` 包裹实现 | definitions.ts L742-750 | runtime.py | `asyncio.wait_for` vs Promise.race |
| F9 | Schema 运行时校验 | schemas.ts (zod) | base.py | jsonschema vs zod，校验失败错误格式 |
| F10 | `validateWithZod` 调用时机 | definitions.ts | base.py | 在 execute 入口 vs runtime 层 |
| F11 | `ToolRegistry` 数据结构 | runtime.ts | base.py | Map vs dict，是否支持别名 |
| F12 | `get_definitions()` 输出 | runtime.ts | base.py | 返回 `AgentToolDefinition[]` 给 LLM |
| F13 | 工具启用/禁用机制 | runtime.ts | base.py | `enabled` 字段或动态过滤 |
| F14 | `toolPolicies` 应用时机 | presets.ts | approval_policy.py | 在 registry 层还是 runtime 层过滤 |
| F15 | 工具描述动态生成 | definitions.ts (skills 工具) | skill_tool.py | description 是 getter 还是属性 |

**验证方法**：
- 对比 `createTool` 接收的所有参数
- 检查流式工具输出（progress update）支持
- 测试 timeout/retry 行为
- 对比 schema 校验错误信息格式

---

### 阶段 G：内置工具逐项对比（文件/命令/编辑类）

**对标 Cline 源码**：`sdk/packages/core/src/extensions/tools/executors/`

**当前实现**：`agent/tools/read_files.py`, `run_commands.py`, `editor.py`, `apply_patch.py`

**逐工具对比维度**：

#### G1: `read_files` vs `file-read.ts`
| # | 对比项 | Cline | 我的位置 |
|---|--------|-------|---------|
| G1.1 | 输入 schema（files 数组结构） | schemas.ts | read_files.py |
| G1.2 | `start_line`/`end_line` 语义 | file-read.ts | read_files.py | 1-based vs 0-based |
| G1.3 | 最大行数限制 | output-limits.ts | constants.py | 值是否一致 |
| G1.4 | 二进制文件检测 | file-read.ts | read_files.py | 如何检测，是否跳过 |
| G1.5 | 编码检测 | file-read.ts | read_files.py | UTF-8 vs 自动检测 |
| G1.6 | 行号格式输出 | file-read.ts | read_files.py | 是否含 `cat -n` 风格行号 |
| G1.7 | 大文件分页 | file-read.ts | read_files.py | 超过 max_lines 时返回什么 |
| G1.8 | 错误信息格式 | file-read.ts | read_files.py | 文件不存在的错误结构 |

#### G2: `run_commands` vs `bash.ts`
| # | 对比项 | Cline | 我的位置 |
|---|--------|-------|---------|
| G2.1 | 输入 schema（commands 数组） | schemas.ts | run_commands.py |
| G2.2 | 命令执行模式 | bash.ts | run_commands.py | parallel vs sequential |
| G2.3 | 单命令超时 | bash.ts | run_commands.py | 默认值，超时行为 |
| G2.4 | 子进程 kill on abort | bash.ts | run_commands.py | `_wait_process_with_abort` 逻辑 |
| G2.5 | 输出截断 | output-limits.ts | constants.py | stdout/stderr 截断阈值 |
| G2.6 | 环境变量继承 | bash.ts | run_commands.py | PYTHONUNBUFFERED，敏感变量屏蔽 |
| G2.7 | 工作目录 | bash.ts | run_commands.py | cwd 来源 |
| G2.8 | exit_code 返回 | bash.ts | run_commands.py | 每条命令独立 exit_code |
| G2.9 | shell 元字符处理 | bash.ts | run_commands.py | 引号、管道、&& |
| G2.10 | 危险命令拦截 | bash.ts | run_commands.py | 黑名单 vs hook 拦截 |

#### G3: `editor` vs `editor.ts`
| # | 对比项 | Cline | 我的位置 |
|---|--------|-------|---------|
| G3.1 | 输入 schema | schemas.ts | editor.py | path/old_text/new_text/insert_line |
| G3.2 | `old_text` 唯一性检查 | editor.ts | editor.py | 多次匹配时行为 |
| G3.3 | `old_text` 为空时插入 | editor.ts | editor.py | insert_line 语义 |
| G3.4 | 文件不存在时创建 | editor.ts | editor.py | 是否自动创建 |
| G3.5 | 行号计算 | editor.ts | editor.py | 1-based vs 0-based |
| G3.6 | diff 生成 | editor.ts | editor.py | 是否返回 diff 给 LLM |
| G3.7 | 原子写入 | editor.ts | editor.py | tmp + rename vs 直接写 |
| G3.8 | 备份机制 | editor.ts | editor.py | 是否保留 .bak |

#### G4: `apply_patch` vs `apply-patch.ts`
| # | 对比项 | Cline | 我的位置 |
|---|--------|-------|---------|
| G4.1 | patch 格式 | apply-patch-parser.ts | apply_patch.py | unified diff vs custom format |
| G4.2 | 解析器容错 | apply-patch-parser.ts | apply_patch.py | 畸形 patch 处理 |
| G4.3 | 多文件 patch | apply-patch.ts | apply_patch.py | 一个 patch 含多文件 |
| G4.4 | 部分成功回滚 | apply-patch.ts | apply_patch.py | 一个文件失败时是否回滚全部 |
| G4.5 | 上下文行匹配 | apply-patch-parser.ts | apply_patch.py | 模糊匹配 vs 严格匹配 |

**验证方法**：
- 用相同输入跑两边工具，对比输出
- 构造边界：空文件、二进制文件、超大文件、不存在路径
- 对比错误信息格式

---

### 阶段 H：内置工具逐项对比（搜索/交互/控制类）

**对标 Cline 源码**：`sdk/packages/core/src/extensions/tools/definitions.ts` + `executors/search.ts` + `executors/web-fetch.ts`

**当前实现**：`agent/tools/search_codebase.py`, `list_files.py`, `fetch_web_content.py`, `ask_question.py`, `submit_and_exit.py`, `attempt_completion.py`, `todo_write.py`, `plan_mode.py`

**逐工具对比维度**：

| 工具 | 对比项 | Cline 位置 | 我的位置 | 关键差异 |
|------|--------|-----------|---------|---------|
| `search_codebase` | queries 数组 vs 单 query | search.ts | search_codebase.py | Cline 支持并行多 query |
| `search_codebase` | 正则 vs glob | search.ts | search_codebase.py | 文件名匹配 vs 内容匹配 |
| `search_codebase` | 输出格式 | search.ts | search_codebase.py | 匹配数 vs 字符数限制 |
| `list_files` | 递归选项 | definitions.ts | list_files.py | recursive 参数 |
| `list_files` | 忽略规则 | definitions.ts | list_files.py | .clineignore 支持 |
| `fetch_web_content` | requests 数组 | web-fetch.ts | fetch_web_content.py | url + prompt 结构 |
| `fetch_web_content` | prompt 用途 | web-fetch.ts | fetch_web_content.py | 是否真的用 prompt 提取 |
| `ask_question` | options 数量限制 | definitions.ts | ask_question.py | 2-4 vs 2-5 |
| `ask_question` | multiSelect | definitions.ts | ask_question.py | 是否支持多选 |
| `submit_and_exit` | `verified` 字段 | definitions.ts | submit_and_exit.py | 是否含验证标记 |
| `submit_and_exit` | completes_run | definitions.ts | submit_and_exit.py | True vs False |
| `attempt_completion` | `result` vs `command` | definitions.ts | attempt_completion.py | Cline 是否含 command 字段 |
| `todo_write` | 替换 vs 增量 | definitions.ts | todo_write.py | Cline 是替换式 |
| `todo_write` | `active_form` 必填 | definitions.ts | todo_write.py | in_progress 时是否强制 |
| `switch_to_act_mode` | completes_run | sdk-session-config-builder.ts | plan_mode.py | True vs False |
| `switch_to_plan_mode` | 输入 schema | sdk-session-config-builder.ts | plan_mode.py | 是否含 plan 文本参数 |

**验证方法**：
- 逐工具对比 input_schema 字段
- 对比 executes 后的 AgentToolResult 格式
- 检查 completes_run 标记是否一致

---

### 阶段 I：技能系统对比

**对标 Cline 源码**：
- `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`
- `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts`
- `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts`
- `sdk/packages/core/src/extensions/tools/definitions.ts`（createSkillsTool）

**当前实现**：`agent/skills/skill_tool.py`, `loader.py`, `registry.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| I1 | `skills` 工具名 | definitions.ts L719 | skill_tool.py | 是否完全一致 |
| I2 | `skill` 参数必填 | definitions.ts L725 | skill_tool.py | required 数组 |
| I3 | `args` 参数可选 | definitions.ts L726 | skill_tool.py | 是否支持 args 透传 |
| I4 | description 动态构造 | definitions.ts L728-731 | skill_tool.py | `_build_description()` 追加技能列表 |
| I5 | XML 返回格式 | user-instruction-plugin.ts L202 | skill_tool.py | `<command-name>`/`<command-args>`/`<command-instructions>` |
| I6 | `runningSkills` Set 去重 | user-instruction-plugin.ts L179 | skill_tool.py | try/finally 释放 |
| I7 | `skillsTimeoutMs` 15000 | user-instruction-plugin.ts | skill_tool.py | `withTimeout` 包裹 |
| I8 | `allowedSkillNames` 白名单 | user-instruction-plugin.ts L39-73 | registry.py | `toAllowedSkillSet` + `isSkillAllowed` |
| I9 | frontmatter `disabled` 字段 | skill-frontmatter-toggle.ts | loader.py | 加载时跳过 |
| I10 | frontmatter `always` 字段 | skill-frontmatter-toggle.ts | loader.py | always 技能是否自动注入 system prompt |
| I11 | 三级加载（metadata/instructions/resources） | user-instruction-plugin.ts | loader.py | Level 3 resources 是否实现 |
| I12 | SKILL.md frontmatter 解析 | user-instruction-config-loader.ts | loader.py | YAML 解析，复用 rules_loader |
| I13 | 技能目录扫描 | user-instruction-config-loader.ts | loader.py | 递归扫描，排序保证 |
| I14 | 技能 `scripts` 自动发现 | N/A（Cline 不做） | loader.py | 我额外的增强 |
| I15 | 技能 `keywords` 字段 | user-instruction-config-loader.ts | loader.py | 是否用于匹配 |
| I16 | 技能 `source` 字段 | user-instruction-config-loader.ts | loader.py | local vs remote |
| I17 | 多技能目录支持 | user-instruction-config-loader.ts | loader.py | workspace skills + global skills |
| I18 | 技能热重载 | unified-config-file-watcher.ts | loader.py | 文件变更时重新加载 |
| I19 | 技能 marketplace | marketplace.ts | 无 | 是否支持远程技能安装 |
| I20 | `build_summary()` 输出格式 | user-instruction-plugin.ts | registry.py | 表格 vs 列表，是否标注"非工具" |

**验证方法**：
- 对比 XML 返回格式字节级一致
- 测试 runningSkills 并发去重
- 测试 allowedSkillNames 过滤
- 检查 always 技能是否真的注入 system prompt

---

### 阶段 J：上下文压缩对比

**对标 Cline 源码**：
- `sdk/packages/core/src/extensions/context/compaction.ts`
- `sdk/packages/core/src/extensions/context/agentic-compaction.ts`
- `sdk/packages/core/src/extensions/context/basic-compaction.ts`
- `sdk/packages/core/src/extensions/context/compaction-shared.ts`

**当前实现**：`agent/context.py::ContextCompactor`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| J1 | `maxInputTokens` 默认值 | compaction.ts | context.py | 128000 是否一致 |
| J2 | `triggerRatio` 默认值 | compaction.ts | context.py | 0.9 是否一致 |
| J3 | `preserveRecentTokens` 默认值 | compaction.ts | context.py | 20000 是否一致 |
| J4 | `should_compact` 触发条件 | compaction.ts | context.py | `current >= trigger_tokens` |
| J5 | `_find_cut_index` 安全切割 | compaction-shared.ts | context.py | 不在 tool_use/tool_result 中间切 |
| J6 | `_is_safe_cut_boundary` 判定 | compaction-shared.ts | context.py | 哪些位置算安全 |
| J7 | `_summarize_tool_activity` | compaction-shared.ts | context.py | 工具调用摘要格式 |
| J8 | `_build_dropped_work_summary_block` | compaction-shared.ts | context.py | 被丢弃工作的摘要块 |
| J9 | `_build_summary_request` | agentic-compaction.ts | context.py | LLM 摘要 prompt 构造 |
| J10 | `_ensure_files_section` | compaction-shared.ts | context.py | Files 段保证 |
| J11 | `PRESERVED_ASSISTANT_TEXT_COUNT` | compaction-shared.ts | context.py | 保留最近 3 条 assistant 文本 |
| J12 | agentic 失败 fallback 到 basic | agentic-compaction.ts | context.py | 异常捕获范围 |
| J13 | `CompactionStateManager` 持久化 | compaction.ts | context.py | 压缩状态跨轮次保持 |
| J14 | `before_model` hook 集成 | compaction.ts | context.py | 注册方式，返回 BeforeModelResult |
| J15 | 压缩后消息结构 | compaction.ts | context.py | 摘要 message 的 role/content 格式 |
| J16 | `summary_max_tokens` 限制 | agentic-compaction.ts | context.py | 摘要长度控制 |
| J17 | 压缩触发日志 | compaction.ts | context.py | 记录压缩原因、前后 token 数 |
| J18 | 工具结果截断 `_truncate_tool_results` | compaction-shared.ts | context.py | 单 tool_result 最大字符数 |
| J19 | `FileContextTracker` 集成 | compaction-shared.ts | context.py | `_summarize_tool_activity_v2` 优先级 |
| J20 | 压缩事件 emit | compaction.ts | context.py | 是否 emit 压缩事件给前端 |

**验证方法**：
- 构造 100+ 消息的长对话，对比压缩前后 token 数
- 检查摘要是否保留关键数字
- 测试在 tool_use/tool_result 中间切割的场景
- 对比 agentic 失败时 basic fallback 行为

---

### 阶段 K：Budget Projection 对比

**对标 Cline 源码**：
- `sdk/packages/core/src/extensions/context/budget-projection/index.ts`
- `sdk/packages/core/src/extensions/context/budget-projection/project.ts`
- `sdk/packages/core/src/extensions/context/budget-projection/types.ts`

**当前实现**：`agent/budget_policy.py` + `agent/context.py::_project_future_usage`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| K1 | `BudgetPolicyIntent` 枚举 | types.ts | budget_policy.py | AGENTIC_SUMMARY/BASIC_COMPACTION_PROJECTION/NORMAL_PROVIDER_REQUEST |
| K2 | `ProjectionPolicy` 字段 | types.ts | budget_policy.py | protect_latest_typed_user/protect_live_tail_from_drop/drop_unsafe_outside_live_tail/drop_thinking_blocks |
| K3 | `resolve_projection_policy` 逻辑 | project.ts | budget_policy.py | 按 intent 解析策略 |
| K4 | `find_latest_typed_user_message_index` | project.ts | budget_policy.py | 找最后一条用户输入 |
| K5 | `find_protected_tail_start_index` | project.ts | budget_policy.py | live tail 起始（含未配对 tool_use） |
| K6 | `drop_thinking_blocks` | project.ts | budget_policy.py | 移除 ReasoningPart |
| K7 | `apply_budget_policy` | project.ts | budget_policy.py | 块级策略应用 |
| K8 | `estimate_protected_token_budget` | project.ts | budget_policy.py | 受保护内容 token 估算 |
| K9 | `_project_future_usage` 公式 | project.ts | context.py | `current + tools_tokens + avg_tool_result_tokens` |
| K10 | `projection_ratio` 默认值 | index.ts | context.py | 0.8 是否一致 |
| K11 | `tool_result_history_max` | index.ts | context.py | 历史样本数 |
| K12 | 提前压缩触发条件 | index.ts | context.py | `projected >= projection_trigger_tokens` |
| K13 | `compaction_reason` 标记 | index.ts | context.py | `budget_projection` vs `threshold_exceeded` |
| K14 | 无历史样本时行为 | project.ts | context.py | avg=0 保守策略 |

**验证方法**：
- 构造不同 intent 场景，对比策略应用
- 测试 live tail 保护（含未配对 tool_use）
- 对比 token 估算精度

---

### 阶段 L：系统提示构造对比

**对标 Cline 源码**：
- `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`
- `sdk/packages/shared/src/prompt/system.ts`
- `sdk/packages/shared/src/prompt/cline.ts`

**当前实现**：`agent/context.py::SystemPromptBuilder`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| L1 | 分层结构 | runtime-builder.ts | context.py | Cline 几层，我几层 |
| L2 | `<env>` 段内容 | system.ts | context.py | 时间/平台/cwd/shell |
| L3 | 工具列表段 | runtime-builder.ts | context.py | 自动生成 vs 手写 |
| L4 | `<user_input mode>` 标签 | cline.ts | context.py | plan/act 标签语义 |
| L5 | MCP 服务器概览 | runtime-builder.ts | context.py | 服务器名+工具数 |
| L6 | cline-rules 段 | cline-rules.ts | rules_loader.py | 加载顺序、合并方式 |
| L7 | frontmatter 解析 | frontmatter.ts | rules_loader.py | YAML 解析、fail-open |
| L8 | rule-conditionals 按 mode | rule-conditionals.ts | rules_loader.py | applyTo/mode/paths 条件 |
| L9 | external-rules | external-rules.ts | 无 | .cursorrules/.windsurfrules 支持 |
| L10 | workflows | workflows.ts | 无 | 工作流文件加载 |
| L11 | always 技能注入 | runtime-builder.ts | context.py | always: true 的技能自动注入 |
| L12 | on-demand 技能概览 | runtime-builder.ts | context.py | name + description 列表 |
| L13 | mode 切换注入 | session-runtime.ts | context.py | PLAN_MODE_PROMPT 内容 |
| L14 | AGENTS.md 加载 | runtime-builder.ts | context.py | 单文件 vs 多文件 |
| L15 | memory 段 | runtime-builder.ts | 无 | MEMORY.md 加载 |
| L16 | 工具描述截断 | runtime-builder.ts | context.py | 150 字符截断，skills 工具不截断 |
| L17 | system prompt 顺序 | runtime-builder.ts | context.py | env → identity → tools → skills → rules → memory |
| L18 | 动态上下文注入 | runtime-builder.ts | context.py | 当前时间、git 状态、open files |

**验证方法**：
- 对比完整 system prompt 文本
- 测试 plan/act 模式切换时 prompt 变化
- 检查 always 技能是否真的注入

---

### 阶段 M：循环检测 + MistakeTracker 对比

**对标 Cline 源码**：
- `sdk/packages/core/src/runtime/safety/loop-detection.ts`
- `sdk/packages/core/src/runtime/safety/mistake-tracker.ts`
- `sdk/packages/core/src/runtime/safety/rules.ts`

**当前实现**：`agent/loop_detection.py`, `agent/mistake_tracker.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| M1 | `LoopDetectionTracker` 数据结构 | loop-detection.ts | loop_detection.py | 软阈值 3 / 硬阈值 5 |
| M2 | 循环判定 key | loop-detection.ts | loop_detection.py | tool_name + input hash |
| M3 | 软阈值触发行为 | loop-detection.ts | loop_detection.py | 注入提示 vs 警告 |
| M4 | 硬阈值触发行为 | loop-detection.ts | loop_detection.py | abort + status |
| M5 | key 老化机制 | loop-detection.ts | loop_detection.py | LRU 淘汰、时间窗口 |
| M6 | `MistakeTracker` mistake_type 枚举 | mistake-tracker.ts | mistake_tracker.py | param_error/tool_not_found/permission_denied/exec_error/timeout |
| M7 | 每类独立阈值 | mistake-tracker.ts | mistake_tracker.py | 软/硬阈值是否按类型独立 |
| M8 | 错误分类逻辑 | mistake-tracker.ts | mistake_tracker.py | 如何从 Exception 判定 mistake_type |
| M9 | 软阈值提示格式 | mistake-tracker.ts | mistake_tracker.py | 注入 LLM 的提示结构 |
| M10 | 硬阈值 abort 标记 | mistake-tracker.ts | mistake_tracker.py | `MistakeLimitExceeded` |
| M11 | 集成方式 | rules.ts | runtime.py | hook vs inline 调用 |
| M12 | safety rules 引擎 | rules.ts | 无 | 规则注册、优先级、执行 |
| M13 | 跨轮次状态保持 | mistake-tracker.ts | mistake_tracker.py | 状态在 session 还是 runtime |

**验证方法**：
- 构造连续相同参数工具调用
- 构造不同类型错误（param/not_found/timeout）
- 测试跨轮次 mistake 累积

---

### 阶段 N：AbortController 与中止语义对比

**对标 Cline 源码**：`sdk/packages/agents/src/agent-runtime.ts` L424-470, L588-593, L796-809

**当前实现**：`agent/abort.py` + `agent/runtime.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| N1 | `AbortController` 类结构 | agent-runtime.ts L424 | abort.py | `signal` + `abort()` + `reason` |
| N2 | `signal` 类型 | L424 | abort.py | `AbortSignal` vs `asyncio.Event` |
| N3 | `abort()` 副作用 | L455-465 | runtime.py | 设置 status、last_error、emit 事件 |
| N4 | `throwIfAborted()` 调用点 | L588-593 | runtime.py | 循环顶端、stream 中、tool 前 |
| N5 | signal 透传到 `model.stream()` | L645 | qwen.py | stream 内部检查 signal |
| N6 | signal 透传到 `tool.execute()` | L685 | tools/ | `AgentToolContext.signal` |
| N7 | stream 中途 abort 行为 | L796 | qwen.py | raise `AbortedError` 还是 break |
| N8 | tool 中途 abort 行为 | L700 | run_commands.py | 子进程 kill 时机 |
| N9 | abort 后状态清理 | L805-809 | runtime.py | unsubscribe、释放资源 |
| N10 | abort 事件 emit | L465 | events.py | emit `run_failed` 还是 `run_finished` |
| N11 | `reason` 字段传播 | L465 | runtime.py | 传播到 snapshot.last_error |
| N12 | 多次 abort 幂等 | L455 | runtime.py | 重复调用 abort 行为 |
| N13 | abort 与 hooks 交互 | L544-554 | runtime.py | hook 中 abort 的处理 |
| N14 | `restore()` 与 abort 关系 | L487-503 | runtime.py | restore 是否先 abort 当前运行 |

**验证方法**：
- stream 中途调用 abort，测响应时间
- tool 执行中调用 abort，测子进程 kill
- 测试 abort 与 hook 的交互

---

### 阶段 O：Turn Queue 用户输入排队对比

**对标 Cline 源码**：`sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts`

**当前实现**：`agent/turn_queue.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| O1 | `PendingPromptEntry` 字段 | pending-prompt-service.ts L54 | turn_queue.py | id/prompt/mode/delivery/user_images/user_files |
| O2 | `delivery` 枚举 | L60 | turn_queue.py | queue vs steer |
| O3 | `enqueue()` 入队语义 | L100 | turn_queue.py | steer 是否插队首 |
| O4 | `consume()` 消费时机 | L150 | runtime.py | run 结束后自动消费 |
| O5 | `consume_for_steer()` 消费时机 | L200 | runtime.py | iteration > 1 时检查 |
| O6 | steer 插入位置 | agent-runtime.ts L841 | runtime.py | 插入到 model request messages |
| O7 | queue 自动启动新 run | pending-prompt-service.ts | server.py | Cline 自动 vs 我前端触发 |
| O8 | 状态持久化 | L300 | turn_queue.py | 内存 vs 磁盘 |
| O9 | `list_pending()` 查询 | L250 | server.py | 返回排队列表 |
| O10 | `delete()` 删除 | L280 | server.py | 删除指定 prompt |
| O11 | `update()` 更新 | L290 | server.py | 更新排队内容 |
| O12 | SSE 事件通知 | session-event-projector | server.py | `pending_prompts_updated` |
| O13 | 前端排队 badge | webview-ui | ai-chat.js | 显示排队数 |

**验证方法**：
- 运行中发送多条消息，测试排队顺序
- 测试 steer delivery 实时插入
- 测试服务重启后排队状态

---

### 阶段 P：文件 Hooks 系统对比

**对标 Cline 源码**：
- `apps/vscode/src/core/hooks/HookProcess.ts`
- `apps/vscode/src/core/hooks/hook-factory.ts`
- `apps/vscode/src/core/hooks/templates.ts`
- `apps/vscode/src/core/hooks/shell-escape.ts`
- `apps/vscode/src/core/hooks/HookError.ts` + `HookProcessRegistry.ts`
- `sdk/packages/core/src/hooks/`（核心层）

**当前实现**：`agent/file_hooks/`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| P1 | 7 种 hook 类型 | HookProcess.ts | types.py | PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete/TaskResume/TaskCancel |
| P2 | frontmatter 字段 | hook-factory.ts | loader.py | description/applyTo/blocking |
| P3 | `applyTo` 匹配逻辑 | hook-factory.ts | loader.py | glob 匹配 tool_name |
| P4 | `blocking` 语义 | hook-factory.ts | runner.py | true 时阻塞主流程 |
| P5 | 脚本执行方式 | HookProcess.ts | runner.py | subprocess + stdin JSON |
| P6 | stdin JSON 上下文格式 | HookProcess.ts | runner.py | 字段是否齐全 |
| P7 | stdout 解析 | HookProcess.ts | runner.py | JSON 解析 vs 退出码 |
| P8 | 退出码语义 | HookProcess.ts | runner.py | 0=continue/1=block/其他=error |
| P9 | `context-injection` 语义 | HookProcess.ts | runner.py | stdout 文本注入模型上下文 |
| P10 | hook 超时 | HookProcess.ts | runner.py | 默认 30s |
| P11 | `HookError` 异常 | HookError.ts | 无 | 错误类型 |
| P12 | `HookProcessRegistry` | HookProcessRegistry.ts | 无 | 进程注册表（用于取消） |
| P13 | `shell-escape` | shell-escape.ts | 无 | shell 转义 |
| P14 | hook 模板 | templates.ts | 无 | 新建 hook 模板 |
| P15 | hook 发现缓存 | HookDiscoveryCache.ts | loader.py | 避免重复扫描 |
| P16 | hook 并发执行 | HookProcess.ts | runner.py | 同类型多 hook 并行 vs 串行 |
| P17 | hook 与 Python hook 集成 | hooks-adapter.ts | integration.py | 文件 hook 包装为 Python hook |
| P18 | hook 失败降级 | hooks-utils.ts | integration.py | 失败时 continue vs block |

**验证方法**：
- 创建各种类型 hook 脚本，测试触发
- 测试 blocking hook 阻塞主流程
- 测试 context-injection 注入
- 测试 hook 超时

---

### 阶段 Q：MCP 集成对比

**对标 Cline 源码**：`sdk/packages/core/src/extensions/mcp/`

**当前实现**：`agent/mcp/`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| Q1 | `MCPClient` 协议实现 | client.ts | client.py | initialize/tools/list/tools/call/resources/list/resources/read |
| Q2 | JSON-RPC 2.0 实现 | client.ts | client.py | 请求/响应/通知 |
| Q3 | stdio 传输 | client.ts | client.py | 子进程 + stdin/stdout |
| Q4 | http 传输 | client.ts | client.py | SSE vs WebSocket |
| Q5 | OAuth 认证 | oauth.ts | 无 | 是否支持 |
| Q6 | 配置格式 | config-loader.ts | mcp_servers.yaml | JSON vs YAML |
| Q7 | `${ENV_VAR}` 解析 | config-loader.ts | registry.py | 环境变量替换 |
| Q8 | `policies.ts` 工具策略 | policies.ts | 无 | per-tool auto-approve |
| Q9 | `name-transform` | name-transform.ts | name_transform.py | SHA1 截断 |
| Q10 | `plugin-server-registration` | plugin-server-registration.ts | 无 | 插件注册 MCP |
| Q11 | 工具注册为独立 LLM function | tools.ts | mcp.py | Cline 展开 vs 我用 use_mcp_tool |
| Q12 | 懒连接 | manager.ts | registry.py | 首次调用才连接 |
| Q13 | 连接重试 | manager.ts | registry.py | 失败重试策略 |
| Q14 | 工具/资源缓存 | manager.ts | registry.py | 缓存 TTL |
| Q15 | 配置热加载 | config-loader.ts | server.py | `/mcp/reload` 端点 |
| Q16 | MCP 服务器概览注入 system prompt | runtime-builder.ts | context.py | 服务器名+工具数 |

**验证方法**：
- 启动一个 stdio MCP 服务器，测试工具调用
- 测试 OAuth 场景（如适用）
- 对比 name-transform 输出

---

### 阶段 R：LLM Provider 适配对比

**对标 Cline 源码**：
- `sdk/packages/core/src/services/llms/handler-factory.ts`
- `sdk/packages/core/src/services/llms/provider-defaults.ts`
- `sdk/packages/core/src/services/llms/provider-settings.ts`
- `sdk/packages/shared/src/llms/gateway.ts`

**当前实现**：`agent/providers/`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| R1 | `AgentModel` 协议 | shared/agent.ts | base.py | `stream(request) -> AsyncIterator[AgentModelEvent]` |
| R2 | `handler-factory` 工厂 | handler-factory.ts | factory.py | 按 provider_id 路由 |
| R3 | 内置 provider 清单 | provider-defaults.ts | factory.py | 数量、字段 |
| R4 | `provider-defaults` 字段 | provider-defaults.ts | factory.py | model_id/api_key/base_url/capabilities |
| R5 | `capabilities` 字段 | provider-defaults.ts | 无 | reasoning/prompt-cache/tools/images |
| R6 | OpenAI 兼容适配 | handler-factory.ts | openai.py | base_url 配置 |
| R7 | 流式 tool_calls 组装 | handler-factory.ts | qwen.py/openai.py | 按 index 主键 |
| R8 | `reasoning_content` 处理 | handler-factory.ts | qwen.py | reasoning_delta event |
| R9 | `tool_call_id` 稳定性 | N/A | qwen.py | 按 index 维护 map |
| R10 | `provider-settings` 持久化 | provider-settings.ts | 无 | 用户配置保存 |
| R11 | `agent-model-adapter` | apihandler-agent-model-adapter.ts | 无 | 旧 API handler 适配 |
| R12 | model-tool-routing 集成 | model-tool-routing.ts | routing.py | 按 provider+model 过滤工具 |
| R13 | `create_model_from_env` | handler-factory.ts | factory.py | 环境变量创建模型 |
| R14 | 错误处理 | handler-factory.ts | providers/ | API 限流、网络错误、超时 |
| R15 | usage 解析 | handler-factory.ts | providers/ | input/output/cache token |

**验证方法**：
- 用相同 prompt 跑两边，对比事件流
- 测试 tool_call 流式组装
- 测试 reasoning_content（如模型支持）

---

### 阶段 S：会话持久化与锁对比

**对标 Cline 源码**：
- `sdk/packages/core/src/services/storage/sqlite-session-store.ts`
- `sdk/packages/core/src/services/storage/session-store.ts`
- `apps/vscode/src/core/locks/SqliteLockManager.ts`
- `apps/vscode/src/core/storage/state-migrations.ts`

**当前实现**：`agent/session.py` + `agent/file_lock.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| S1 | 存储格式 | sqlite-session-store.ts | session.py | SQLite vs JSON |
| S2 | schema 结构 | sqlite-session-store.ts | session.py | 表/字段 |
| S3 | `SqliteLockManager` 跨进程锁 | SqliteLockManager.ts | file_lock.py | SQLite 事务 vs 文件锁 |
| S4 | 锁超时 | SqliteLockManager.ts | file_lock.py | 默认值 |
| S5 | 锁 stale 接管 | SqliteLockManager.ts | file_lock.py | 死锁检测 |
| S6 | `state-migrations` 版本迁移 | state-migrations.ts | 无 | schema 升级 |
| S7 | `session-export` 导出 | apps/cli/export.ts | 无 | 导出格式 |
| S8 | session 列表查询 | sqlite-session-store.ts | session.py | 索引查询 vs 文件扫描 |
| S9 | session 元信息 | session-store.ts | session.py | created_at/updated_at/title |
| S10 | 消息增量保存 | sqlite-session-store.ts | session.py | 全量 vs 增量 |
| S11 | 并发写安全 | sqlite-session-store.ts | session.py | 事务隔离级别 |
| S12 | 数据迁移 | state-migrations.ts | 无 | 旧格式 → 新格式 |
| S13 | 备份机制 | disk.ts | 无 | 自动备份 |
| S14 | session 索引内存缓存 | N/A | session.py | 我额外的增强 |

**验证方法**：
- 并发写同一 session，测试锁
- 测试大量 session 时 list 查询性能
- 测试服务重启后会话恢复

---

### 阶段 T：Checkpoint 机制对比

**对标 Cline 源码**：
- `apps/vscode/src/core/controller/checkpoints/checkpointRestore.ts`
- Cline shadow-git 机制（文档 `docs/core-workflows/checkpoints.mdx`）

**当前实现**：`agent/checkpoint.py` + `agent/file_checkpoint.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| T1 | 检查点创建时机 | checkpointRestore.ts | file_checkpoint.py | 每次工具执行前 vs 每轮 |
| T2 | 检查点内容 | shadow-git | file_checkpoint.py | 文件状态快照 vs 消息快照 |
| T3 | git stash 实现 | shadow-git | file_checkpoint.py | `git add -A` + `git stash create` |
| T4 | 检查点查询 | checkpointRestore.ts | server.py | 列表、详情 |
| T5 | 回滚语义 | checkpointRestore.ts | server.py | 文件恢复 vs 消息恢复 |
| T6 | 持久化 | shadow-git | file_checkpoint.py | 引用持久化到磁盘 |
| T7 | 清理机制 | checkpointRestore.ts | 无 | 自动清理旧检查点 |
| T8 | 启用开关 | config | env | `AGENT_ENABLE_FILE_CHECKPOINT` |
| T9 | shadow-git 仓库 | shadow-git | 无 | 独立 git 仓库 |
| T10 | 未跟踪文件处理 | shadow-git | file_checkpoint.py | `git add -A` 包含 |

**验证方法**：
- 工具执行后回滚，测试文件恢复
- 测试检查点持久化（重启后查询）

---

### 阶段 U：审批机制 + ToolPolicies 对比

**对标 Cline 源码**：
- `sdk/packages/core/src/runtime/tools/tool-approval.ts`
- `sdk/packages/core/src/extensions/tools/presets.ts`

**当前实现**：`agent/approval.py` + `agent/approval_policy.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| U1 | `autoApprove` 全局开关 | tool-approval.ts | approval.py | 默认 false |
| U2 | `toolPolicies` per-tool 配置 | presets.ts | approval_policy.py | allow/deny/ask |
| U3 | `requestToolApproval` 回调 | tool-approval.ts | hooks.py | Cline config 回调 vs 我 hook |
| U4 | Plan Mode 工具策略 | presets.ts | server.py | 禁用 editor/apply_patch/file_write |
| U5 | 审批 UI 流程 | vscode 原生 | ai-chat.js | 弹窗 + approve/deny |
| U6 | 审批超时 | tool-approval.ts | 无 | 超时行为 |
| U7 | `before_approval` hook | shared/agent.ts | hooks.py | hook 形式 vs config 形式 |
| U8 | 审批结果传播 | tool-approval.ts | approval.py | approve → 执行，deny → 跳过 |
| U9 | 工具分组审批 | presets.ts | 无 | 同组工具一次审批 |
| U10 | 审批记忆 | presets.ts | 无 | "始终允许" 选项 |

**验证方法**：
- 调用危险工具，测试审批流程
- 测试 Plan Mode 工具禁用
- 测试 auto-approve 开关

---

### 阶段 V：Sub-agent / 多 Agent 对比

**对标 Cline 源码**：
- `sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts`
- `sdk/packages/core/src/extensions/tools/team/delegated-agent.ts`
- `sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts`
- `sdk/packages/core/src/extensions/tools/team/configured-agent-tool.ts`
- `sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
- `sdk/packages/core/src/extensions/tools/team/projections.ts`
- `apps/vscode/src/core/task/tools/subagent/AgentConfigLoader.ts`

**当前实现**：无（Phase 27 移除了技能子 agent，无 spawn_agent 工具）

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| V1 | `spawn_agent` 工具 | spawn-agent-tool.ts | 无 | 输入 schema |
| V2 | `delegated-agent` 创建 | delegated-agent.ts | 无 | 独立 runtime 创建 |
| V3 | `subagent-prompts` 构造 | subagent-prompts.ts | 无 | 子 agent system prompt |
| V4 | `configured-agent-tool` | configured-agent-tool.ts | 无 | 预配置 agent |
| V5 | `multi-agent` 协作 | multi-agent.ts | 无 | 多 agent 通信 |
| V6 | `projections` 事件投影 | projections.ts | 无 | 子 agent 事件投影到主 |
| V7 | `AgentConfigLoader` yaml | AgentConfigLoader.ts | 无 | agent 配置加载 |
| V8 | 子 agent 工具集限制 | spawn-agent-tool.ts | 无 | 无 spawn_agent 防递归 |
| V9 | 子 agent max_iterations | spawn-agent-tool.ts | 无 | 独立计数 |
| V10 | 子 agent 事件冒泡 | projections.ts | 无 | SSE sub_agent_event |

**验证方法**：
- 评估量化场景是否真的需要 sub-agent
- 如需实现，参照 Cline spawn-agent-tool.ts

---

### 阶段 W：FileContextTracker 对比

**对标 Cline 源码**：
- `apps/vscode/src/core/context/context-tracking/FileContextTracker.ts`
- `apps/vscode/src/core/context/context-tracking/ContextTrackerTypes.ts`

**当前实现**：`agent/file_context_tracker.py`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| W1 | `FileContextTracker` 类结构 | FileContextTracker.ts | file_context_tracker.py | 字段、方法 |
| W2 | 记录时机 | FileContextTracker.ts | runtime.py | after_tool hook |
| W3 | 操作类型枚举 | ContextTrackerTypes.ts | file_context_tracker.py | read/edited/created/deleted |
| W4 | 持久化格式 | FileContextTracker.ts | file_context_tracker.py | JSON 结构 |
| W5 | 持久化路径 | FileContextTracker.ts | file_context_tracker.py | 按 session_id 隔离 |
| W6 | `get_state()` 返回 | FileContextTracker.ts | file_context_tracker.py | 精简视图 |
| W7 | `get_entries()` 返回 | FileContextTracker.ts | file_context_tracker.py | 完整记录 |
| W8 | 路径规范化 | FileContextTracker.ts | file_context_tracker.py | expanduser + resolve |
| W9 | 去重策略 | FileContextTracker.ts | file_context_tracker.py | 同 path+operation 保留首次 |
| W10 | 集成到压缩 | compaction-shared.ts | context.py | `_summarize_tool_activity_v2` |
| W11 | SSE 事件 | FileContextTracker.ts | server.py | `file_context_updated` |
| W12 | API 端点 | FileContextTracker.ts | server.py | GET/DELETE |
| W13 | 原子写入 | FileContextTracker.ts | file_context_tracker.py | tmp + replace |

**验证方法**：
- 跑一轮会话，对比 tracker 记录
- 测试持久化重启恢复
- 测试集成到压缩

---

### 阶段 X：Cline Rules / Frontmatter / Workflows 对比

**对标 Cline 源码**：
- `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts`
- `apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts`
- `apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts`
- `apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts`
- `apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts`
- `apps/vscode/src/core/context/instructions/user-instructions/workflows.ts`
- `apps/vscode/src/core/context/instructions/user-instructions/skills.ts`

**当前实现**：`agent/rules_loader.py` + `agent_config/rules/`

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| X1 | frontmatter YAML 解析 | frontmatter.ts | rules_loader.py | fail-open 策略 |
| X2 | `applyTo` 条件 | rule-conditionals.ts | rules_loader.py | act/plan 过滤 |
| X3 | `mode` 条件 | rule-conditionals.ts | rules_loader.py | 业务模式过滤 |
| X4 | `paths` glob 匹配 | rule-conditionals.ts | rules_loader.py | 工作空间路径匹配 |
| X5 | `enabled` 字段 | rule-conditionals.ts | rules_loader.py | false 时跳过 |
| X6 | `toggles` 机制 | rule-helpers.ts | rules_loader.py | 用户开关 |
| X7 | cline-rules 加载顺序 | cline-rules.ts | rules_loader.py | 优先级 |
| X8 | external-rules | external-rules.ts | 无 | .cursorrules/.windsurfrules |
| X9 | workflows | workflows.ts | 无 | 工作流文件 |
| X10 | skills 加载 | skills.ts | loader.py | 与 rules 区分 |
| X11 | 多目录扫描 | cline-rules.ts | rules_loader.py | workspace + global |
| X12 | 热重载 | unified-config-file-watcher.ts | 无 | 文件变更重新加载 |
| X13 | rule 合并方式 | cline-rules.ts | rules_loader.py | 拼接 vs 覆盖 |
| X14 | rule 优先级 | cline-rules.ts | rules_loader.py | 后加载覆盖前加载 |

**验证方法**：
- 创建带 frontmatter 的规则文件，测试条件过滤
- 测试 toggles 开关
- 对比加载顺序

---

### 阶段 Y：Plugin / Marketplace 系统

**对标 Cline 源码**：
- `sdk/packages/core/src/extensions/plugin/`
- `apps/vscode/src/core/controller/marketplace/`

**当前实现**：无

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| Y1 | `plugin-config-loader` | plugin-config-loader.ts | 无 | 插件配置加载 |
| Y2 | `plugin-loader` | plugin-loader.ts | 无 | 插件模块加载 |
| Y3 | `plugin-sandbox` | plugin-sandbox.ts | 无 | 沙箱执行 |
| Y4 | `plugin-targeting` | plugin-targeting.ts | 无 | 插件目标 |
| Y5 | marketplace 安装 | installMarketplaceEntry.ts | 无 | 远程插件安装 |
| Y6 | marketplace 卸载 | uninstallMarketplaceEntry.ts | 无 | 卸载 |
| Y7 | marketplace 列表 | getMarketplaceCatalog.ts | 无 | 目录查询 |

**验证方法**：评估是否需要插件系统（量化场景可能不需要）

---

### 阶段 Z：Telemetry / Connectors / Kanban / Hub

**对标 Cline 源码**：
- `sdk/packages/core/src/services/telemetry/`
- `apps/cli/src/connectors/`
- `apps/cli/src/commands/kanban.ts`
- `sdk/packages/core/src/hub/`
- `sdk/packages/core/src/cron/`

**当前实现**：`agent/telemetry.py` + `agent/connectors.py` + `agent/kanban.py`（骨架）

**对比维度**：

| # | 对比项 | Cline 位置 | 我的位置 | 关键逻辑点 |
|---|--------|-----------|---------|-----------|
| Z1 | `TelemetryLoggerSink` | TelemetryLoggerSink.ts | telemetry.py | 日志 sink |
| Z2 | `OpenTelemetryAdapter` | OpenTelemetryAdapter.ts | telemetry.py | OTLP 上报 |
| Z3 | `TelemetryService` | TelemetryService.ts | telemetry.py | 服务层 |
| Z4 | `core-events` 事件 | core-events.ts | telemetry.py | 事件枚举 |
| Z5 | `tool-context` | tool-context.ts | telemetry.py | 工具上下文 |
| Z6 | connectors 适配器 | apps/cli/connectors/ | connectors.py | 飞书/钉钉/Slack/TG |
| Z7 | connector 注册 | registry.ts | connectors.py | 注册机制 |
| Z8 | Kanban 看板 | kanban.ts | kanban.py | 任务看板 |
| Z9 | Hub client/server | core/src/hub/ | 无 | 远程会话 |
| Z10 | Hub daemon | hub/daemon/ | 无 | 守护进程 |
| Z11 | Cron 调度 | core/src/cron/ | 无 | 定时任务 |
| Z12 | `FeatureFlagsService` | feature-flags/ | 无 | 功能开关 |
| Z13 | telemetry 隐私 | TelemetryService.ts | telemetry.py | PII 脱敏 |

**验证方法**：评估哪些功能量化场景需要

---

## 四、优先级矩阵

### P0（必做，影响核心功能正确性）
- 阶段 A：类型系统（基础）
- 阶段 B：AgentRuntime 主循环（核心）
- 阶段 C：流式工具调用组装（核心）
- 阶段 D：事件系统（核心）
- 阶段 E：Hooks 生命周期（核心）
- 阶段 F：工具系统基础设施（核心）
- 阶段 G：内置工具（文件/命令/编辑）（核心）
- 阶段 I：技能系统（核心）
- 阶段 J：上下文压缩（核心）
- 阶段 L：系统提示构造（核心）
- 阶段 M：循环检测 + MistakeTracker（稳定性）
- 阶段 N：AbortController（用户体验）
- 阶段 P：文件 Hooks（扩展性）
- 阶段 R：LLM Provider（核心）

### P1（重要，影响体验和稳定性）
- 阶段 H：内置工具（搜索/交互/控制类）
- 阶段 K：Budget Projection
- 阶段 O：Turn Queue
- 阶段 Q：MCP 集成
- 阶段 S：会话持久化与锁
- 阶段 U：审批机制
- 阶段 W：FileContextTracker
- 阶段 X：Cline Rules / Frontmatter

### P2（可选，按需推进）
- 阶段 T：Checkpoint
- 阶段 V：Sub-agent

### P3（锦上添花）
- 阶段 Y：Plugin / Marketplace
- 阶段 Z：Telemetry / Connectors / Kanban / Hub

---

## 五、推荐执行顺序

### 第一轮：核心架构对比（2-3 周）
1. **阶段 A**（类型系统）→ 基础，先做
2. **阶段 B**（AgentRuntime 主循环）→ 核心
3. **阶段 C**（流式工具调用）→ 依赖 A, B
4. **阶段 D**（事件系统）→ 依赖 A
5. **阶段 E**（Hooks）→ 依赖 A, B
6. **阶段 N**（AbortController）→ 依赖 B

### 第二轮：工具与技能对比（2-3 周）
7. **阶段 F**（工具基础设施）→ 基础
8. **阶段 G**（文件/命令/编辑工具）→ 依赖 F
9. **阶段 H**（搜索/交互/控制工具）→ 依赖 F
10. **阶段 I**（技能系统）→ 依赖 F
11. **阶段 R**（LLM Provider）→ 依赖 A

### 第三轮：上下文与提示对比（1-2 周）
12. **阶段 J**（上下文压缩）→ 依赖 A, B
13. **阶段 K**（Budget Projection）→ 依赖 J
14. **阶段 L**（系统提示构造）→ 依赖 I, J
15. **阶段 W**（FileContextTracker）→ 依赖 J

### 第四轮：安全与扩展对比（1-2 周）
16. **阶段 M**（循环检测 + MistakeTracker）→ 依赖 E
17. **阶段 P**（文件 Hooks）→ 依赖 E
18. **阶段 U**（审批机制）→ 依赖 F
19. **阶段 X**（Cline Rules / Frontmatter）→ 依赖 L

### 第五轮：辅助系统对比（1-2 周）
20. **阶段 O**（Turn Queue）→ 依赖 B
21. **阶段 Q**（MCP 集成）→ 依赖 F
22. **阶段 S**（会话持久化）→ 依赖 A

### 第六轮：可选对比（按需）
23. **阶段 T**（Checkpoint）
24. **阶段 V**（Sub-agent）
25. **阶段 Y**（Plugin）
26. **阶段 Z**（Telemetry / Hub）

---

## 六、对比产出规范

### 6.1 每阶段输出文件

`CLINE_DIFF/phase_<X>_<name>.md`，含：

```markdown
# Phase X: <主题> 对比报告

## 1. 对标源码
- Cline: <文件路径 + 行号>
- 我的: <文件路径 + 行号>

## 2. 详细对比表
| # | 对比项 | Cline 实现 | 我的实现 | 一致性 | 差距描述 | 修复建议 |
|---|--------|-----------|---------|--------|---------|---------|
| X1 | ... | ... | ... | 一致/弱/缺失 | ... | ... |

## 3. 一致性统计
- 完全一致: N 项
- 弱对齐: N 项
- 缺失: N 项
- 语义不等价: N 项

## 4. 关键差距清单（按严重度排序）
1. [P0] ...
2. [P1] ...

## 5. 修复建议
- 短期: ...
- 中期: ...
- 长期: ...

## 6. 验证记录
- 测试用例: ...
- 测试结果: ...
```

### 6.2 一致性等级定义

| 等级 | 含义 |
|------|------|
| **完全一致** | 逻辑、字段、语义全部等价 |
| **弱对齐** | 有类似实现，但字段缺失或语义不等价 |
| **缺失** | Cline 有，我没有 |
| **额外** | 我有，Cline 没有（增强） |
| **语义不等价** | 同名但行为不同 |

### 6.3 总体差距统计

完成所有阶段后，汇总到 `CLINE_DIFF/SUMMARY.md`：

```markdown
# Cline 对齐差距总览

## 整体对齐度: X%

## 按模块统计
| 模块 | 完全一致 | 弱对齐 | 缺失 | 额外 | 对齐度 |
|------|---------|--------|------|------|--------|
| 类型系统 | ... | ... | ... | ... | ... |
| ... | ... | ... | ... | ... | ... |

## P0 差距清单
1. ...

## 修复优先级建议
1. ...
```

---

## 七、附录：Cline 源码位置速查

### shared 包（类型 + 协议）
- `sdk/packages/shared/src/agent.ts` — Agent 协议、hooks、config
- `sdk/packages/shared/src/llms/messages.ts` — 消息结构
- `sdk/packages/shared/src/llms/tools.ts` — 工具类型
- `sdk/packages/shared/src/llms/requests.ts` — 请求/响应
- `sdk/packages/shared/src/llms/gateway.ts` — LLM 网关
- `sdk/packages/shared/src/tools/create.ts` — createTool 工厂
- `sdk/packages/shared/src/prompt/system.ts` — 系统 prompt
- `sdk/packages/shared/src/prompt/cline.ts` — Cline 默认 prompt

### agents 包（stateless loop）
- `sdk/packages/agents/src/agent-runtime.ts` — 主循环、流式组装、tool 执行

### core 包（stateful 编排）
- `sdk/packages/core/src/ClineCore.ts` — Cline 核心类
- `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` — 系统提示构造
- `sdk/packages/core/src/runtime/orchestration/session-runtime.ts` — 会话运行时
- `sdk/packages/core/src/runtime/safety/loop-detection.ts` — 循环检测
- `sdk/packages/core/src/runtime/safety/mistake-tracker.ts` — 错误追踪
- `sdk/packages/core/src/runtime/safety/rules.ts` — 安全规则
- `sdk/packages/core/src/runtime/tools/tool-approval.ts` — 工具审批
- `sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts` — 子进程沙箱
- `sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` — 输入排队
- `sdk/packages/core/src/runtime/host/local/agent-event-bridge.ts` — 事件桥接
- `sdk/packages/core/src/extensions/tools/definitions.ts` — 默认工具定义
- `sdk/packages/core/src/extensions/tools/schemas.ts` — zod schema
- `sdk/packages/core/src/extensions/tools/presets.ts` — 工具预设
- `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` — 工具路由
- `sdk/packages/core/src/extensions/tools/team/` — Sub-agent
- `sdk/packages/core/src/extensions/tools/executors/` — 工具执行器
- `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` — 技能系统
- `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` — 技能开关
- `sdk/packages/core/src/extensions/context/compaction.ts` — 上下文压缩
- `sdk/packages/core/src/extensions/context/budget-projection/` — 预算投影
- `sdk/packages/core/src/extensions/mcp/` — MCP 集成
- `sdk/packages/core/src/extensions/plugin/` — 插件系统
- `sdk/packages/core/src/hooks/` — 核心 hooks
- `sdk/packages/core/src/services/storage/sqlite-session-store.ts` — 会话存储
- `sdk/packages/core/src/services/telemetry/` — 遥测
- `sdk/packages/core/src/services/llms/handler-factory.ts` — LLM 工厂
- `sdk/packages/core/src/services/llms/provider-defaults.ts` — Provider 默认值
- `sdk/packages/core/src/hub/` — Hub 远程运行时
- `sdk/packages/core/src/cron/` — 定时调度

### apps/vscode（VSCode 扩展）
- `apps/vscode/src/core/hooks/` — 文件 hooks 系统
- `apps/vscode/src/core/context/instructions/user-instructions/` — Cline Rules
- `apps/vscode/src/core/context/context-tracking/FileContextTracker.ts` — 文件追踪
- `apps/vscode/src/core/locks/SqliteLockManager.ts` — SQLite 锁
- `apps/vscode/src/core/storage/state-migrations.ts` — 状态迁移
- `apps/vscode/src/core/controller/checkpoints/` — Checkpoint
- `apps/vscode/src/core/controller/marketplace/` — Marketplace

### apps/cli（CLI 版本）
- `apps/cli/src/connectors/` — 连接器适配器
- `apps/cli/src/commands/kanban.ts` — Kanban 看板
- `apps/cli/src/session/export.ts` — 会话导出

---

## 八、注意事项

### 8.1 对比原则
1. **逻辑级而非功能级**：不止问"有没有"，问"逻辑是否等价"
2. **以 Cline 为准**：当两边逻辑冲突时，以 Cline 为参考标准
3. **保留合理增强**：我的实现中有但 Cline 没有的合理增强（如脚本自动发现）应保留
4. **标注语义不等价**：同名但行为不同的项要特别标注

### 8.2 常见陷阱
1. **默认值差异**：TypeScript 接口默认值 vs Python dataclass 默认值语义可能不同
2. **异步语义**：JavaScript Promise vs Python asyncio 的错误传播不同
3. **不可变性**：TypeScript readonly vs Python 无原生支持
4. **空值语义**：TypeScript `undefined`/`null` vs Python `None`
5. **枚举值**：string enum 的比较语义

### 8.3 量化场景特化
对比时注意保留量化场景的合理特化：
- JSON 会话存储（量化场景消息量可控）
- 文件锁替代 SQLite 锁（单机场景够用）
- 不实现 OAuth（量化场景用不到）
- 不实现 Hub/远程运行时（单机场景）

这些差异在对应阶段标注为"合理特化"而非"缺失"。

---

**计划结束。按上述阶段逐步执行对比，每阶段产出 `CLINE_DIFF/phase_<X>_<name>.md` 报告。**
