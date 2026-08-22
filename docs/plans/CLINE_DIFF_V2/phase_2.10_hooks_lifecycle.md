# Phase 2.10 Hooks 生命周期对比报告

## 1. 执行摘要

Cline 的 Hooks 生命周期在 SDK 层由 `AgentRuntimeHooks` 接口（`sdk/packages/shared/src/agent.ts` L336-365）定义 **7 个回调点**：`beforeRun` / `afterRun` / `beforeModel` / `afterModel` / `beforeTool` / `afterTool` / `onEvent`。`HookBag`（`agent-runtime.ts` L229-237）是简单的 7 字段对象，注册逻辑（`registerHooks` L544-554）按字段 push 到对应数组，调用逻辑（`callBeforeRunHooks` / `callAfterRunHooks` L796-809、`beforeModel` L857-876、`afterModel` L1067-1074、`beforeTool` L1371-1393、`afterTool` L1523-1538）按注册顺序串行 await。PLAN 表声称 Cline 有 "9 个钩子点" 与实际不符——`prepare_turn_input` / `format_user_input_block` / `before_approval` 在 Cline 中**不是 hooks**，而是 `AgentRuntimeConfig` 上的**单实例 config callback**（`prepareTurn` L447-452、`requestToolApproval` L437-439）或纯工具函数（`formatUserInputBlock` 见 `prompt/format.ts` L5-10）。

Charles 在 `agent/hooks.py` 定义 **9 个钩子点**（L304-313）：原 7 个 + Phase 23 新增的 `prepare_turn_input` / `format_user_input_block` / `before_approval`。`HookBag` 类（L320-389）封装 9 个列表 + `add` / `clear` / `is_empty` 方法。**关键设计差异**：Charles 将 Cline 的"单实例 config callback"**提升为多订阅者 hook 链**——多个插件可同时注册 `prepare_turn_input` / `format_user_input_block` / `before_approval`，按注册顺序串行执行；而 Cline 的 `prepareTurn` / `requestToolApproval` 只能配置一个实例，后注册会覆盖前者。

字段层面，Charles 在 `BeforeModelContext` 增加 `session_id`（Phase 26）和 `abort_signal`（Stage 11.2/J12），在 `BeforeToolResult` 增加 `additional_context`（Stage 12.3/P9）——这三个字段在 Cline 对应类型中**均不存在**，是 Charles 的扩展。`additional_context` 注释声称"对标 Cline AgentBeforeToolResult.additionalContext"，但 Cline 源码中 `AgentBeforeToolResult`（agent.ts L300-306）并无此字段，注释残留属"对标说明错误"。

文件 hook 系统两侧均有实现：Cline 在 `sdk/packages/core/src/hooks/hook-file-hooks.ts` 通过 `spawn` 执行子进程脚本；Charles 在 `agent/file_hooks/`（4 文件）通过 `asyncio.create_subprocess_exec` 执行。两者都支持 frontmatter 配置 + 退出码协议 + stdout JSON 协议。Charles 额外支持 `TaskResume` / `TaskCancel` 文件 hook 类型（Phase 31.6，对标 Cline VS Code 端 `apps/vscode/src/core/hooks/` 的同类型），且增加 `_MAX_PARALLEL_HOOKS=10` 并发上限（integration.py L113）。Cline 的 `HookControl`（contracts.ts L1-9）支持 7 字段（cancel/review/context/overrideInput/systemPrompt/appendMessages/replaceMessages），Charles 的 `FileHookResult` 仅支持 3 字段（action/reason/context_injection），表达能力弱于 Cline。

nanobot 残留检查：在 P2.10 涉及的 3 个核心文件（`agent/hooks.py` / `agent/runtime.py` 的 hook 调用段 / `agent/file_hooks/` 全部 4 文件）中**未发现任何 nanobot 残留**（既无注释残留也无实现逻辑残留）。所有实现均基于 Cline 对标设计。P2.1 报告中提到的 12 个 nanobot 残留文件（`skills/` / `server.py` / `session.py` / `context.py` / `tools/` / `providers/`）均位于其他模块，与本阶段无关。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.10 章节定义的 16 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.10.1 | 9 钩子点枚举 | `agent.ts` L336-365 `AgentRuntimeHooks`（**实际 7 个**：beforeRun/afterRun/beforeModel/afterModel/beforeTool/afterTool/onEvent） | `hooks.py` L304-313 `AgentHooks`（**9 个**：上述 7 个 + prepare_turn_input/format_user_input_block/before_approval） | PLAN 表声称 Cline 9 个与实际不符；Charles 把 Cline 的 3 个 config callback（prepareTurn/requestToolApproval）+ 1 个纯函数（formatUserInputBlock）**提升为 hooks**，是 Charles 的设计扩展 | Charles 超出 Cline |
| 2.10.2 | BeforeRunContext 字段 | `agent.ts` L325-327 `AgentRunLifecycleContext { snapshot }` | `hooks.py` L69-75 `RunLifecycleContext { snapshot }` | 字段完全一致 | 完全对齐 |
| 2.10.3 | BeforeModelContext 字段 | `agent.ts` L269-272 `AgentBeforeModelContext { snapshot, request }` | `hooks.py` L86-98 `BeforeModelContext { snapshot, request, session_id, abort_signal }` | Charles 多 2 字段：`session_id`（Phase 26，供 ContextCompactor 会话隔离）+ `abort_signal`（Stage 11.2/J12，让钩子响应中止信号） | Charles 超出 Cline |
| 2.10.4 | BeforeModelResult 字段 | `agent.ts` L279-285 `{ stop, reason, messages, tools, options }` | `hooks.py` L102-111 `{ stop, reason, messages, tools, options }` | 字段完全一致；Charles 调用点（runtime.py L2116-2123）合并逻辑与 Cline L864-875 等价（messages/tools 覆盖、options merge update） | 完全对齐 |
| 2.10.5 | BeforeToolContext 字段 | `agent.ts` L293-298 `{ snapshot, tool, toolCall, input }` | `hooks.py` L122-128 `{ snapshot, tool, tool_call, input }` | 字段一致；Charles 的 `tool` 类型为 `AgentTool \| None`（允许 None），Cline 为 `AgentTool`（非空） | 弱对齐（nullability 不同） |
| 2.10.6 | BeforeToolResult 字段 | `agent.ts` L300-306 `{ skip, stop, reason, input, policy }` | `hooks.py` L132-152 `{ skip, stop, reason, input, policy, additional_context }` | Charles 多 1 字段：`additional_context`（Stage 12.3/P9）；注释声称"对标 Cline additionalContext"但 Cline 源码无此字段，属 Charles 扩展 | Charles 超出 Cline |
| 2.10.7 | AfterToolResult 字段 | `agent.ts` L319-323 `{ stop, reason, result }` | `hooks.py` L168-177 `{ stop, reason, result }` | 字段完全一致；调用点逻辑（Cline L1535-1537 / Charles L1880-1884）等价 | 完全对齐 |
| 2.10.8 | 钩子执行顺序 | `agent-runtime.ts` L544-554 `registerHooks` push 到数组；L797/L806/L857/L1067/L1371/L1523 `for (const hook of this.hooks.X)` 顺序 await | `hooks.py` L341-361 `HookBag.add` push 到列表；runtime.py L1477/L1868/L2082/L2090/L2105/L2132 `for hook in self._hooks.X` 顺序 await | 两者均按**注册顺序串行执行**，无优先级概念；Charles 的 `_call_hook`（L2675-2680）支持同步/异步双模式，Cline 全异步 | 完全对齐 |
| 2.10.9 | 钩子失败处理 | `agent-runtime.ts` 无 try-catch 包裹 hook 调用；hook 抛错直接沿 `await` 链向上传播，被 `execute()` 的 catch 块（L745-790）捕获 → status="failed" | `runtime.py` `_call_hook`（L2675-2680）无 try-catch；hook 抛错沿 await 链传播，被 `run()` 的 except 块（L723-806）捕获 → status="failed"/"aborted" | 两者均**不捕获 hook 异常**，让错误沿调用栈传播；`HookErrorMode` config（Cline `types.ts` L263）仅在 core 层 `agent.ts` 高级封装中使用，sdk 层 `agent-runtime.ts` 未读取 | 完全对齐 |
| 2.10.10 | prepare_turn_input 调用时机 | **非 hook**，是 `AgentRuntimeConfig.prepareTurn` config callback；`agent-runtime.ts` L1208-1250 `prepareTurnForModelRequest` 在**每次 iteration 的 `beforeModel` hooks 之后、`model.stream` 之前**调用；可修改 messages/systemPrompt | `runtime.py` L605-609 `_call_prepare_turn_input_hooks` 在**run 开始时（before_run hooks 之后、主循环之前）**调用；仅修改 `input` 字符串（非 message 列表） | **概念不同**：Cline 的 prepareTurn 是**每轮 iteration** + **message 列表级**修改；Charles 的 prepare_turn_input 是**每 run 一次** + **user input 字符串级**修改；Charles 调用时机更早，粒度更粗 | 弱对齐（语义不同） |
| 2.10.11 | format_user_input_block 作用 | **非 hook**，是纯工具函数 `prompt/format.ts` L5-10 `formatUserInputBlock(input, mode)`，返回 `<user_input mode="${mode}">${input}</user_input>`；在 server/上层调用，runtime 不调用 | `runtime.py` L614-617 `_call_format_user_input_block_hooks` 在 prepare_turn_input 之后调用；hook 可注入元数据；无 hook 时 runtime 默认包装（Stage 36.2/M2，L2742-2787） | **概念不同**：Cline 是**纯函数**（无 hook 链，无元数据注入）；Charles 是**hook 链**（多插件可链式注入元数据）+ runtime 默认包装兜底 | Charles 超出 Cline |
| 2.10.12 | before_approval 与 toolPolicies 关系 | **非 hook**，是 `AgentRuntimeConfig.requestToolApproval` config callback（L437-439）；`agent-runtime.ts` L1424-1462 `requestToolApproval` 在 `policy.autoApprove === false` 时调用，单实例回调 | `runtime.py` L1688-1715 `_request_tool_approval` 内调用 before_approval hooks（多订阅者链）；任一 hook 返回 "approved" 短路返回 None，任一返回 "denied" 返回拒绝 reason；无决策时走用户审批 | **概念不同**：Cline 是**单实例 config callback**（policy 驱动，无链式）；Charles 是**多订阅者 hook 链**（顺序执行，首个决策短路）；Charles 支持 `is_auto_approved` 会话级记忆（L1682）+ before_approval hook + 用户审批**三层** | Charles 超出 Cline |
| 2.10.13 | 钩子返回 None 语义 | `agent-runtime.ts` L1661-1671 `applyStopControl`：`if (!control?.stop) return;`；所有 hook 用 `result?.field` 检查；None = "继续不修改" | `runtime.py` L1485-1486 `if result is None: continue`；L2114 `if result is None: continue`；None = "继续不修改" | 两者语义完全一致：None 表示"不修改、不停止、继续后续 hook" | 完全对齐 |
| 2.10.14 | 异步钩子 vs 同步钩子 | `agent-runtime.ts` 所有 hook 类型签名均为 `(...) => T \| undefined \| Promise<T \| undefined>`，**强制异步**；hook 内部即使同步返回，外层仍 `await` | `hooks.py` L274-283 类型签名 `Callable[[Ctx], Union[T, None, Awaitable[T, None]]]`，**同步异步均支持**；`_call_hook`（L2675-2680）用 `asyncio.iscoroutine(result)` 判断是否 await | Charles 更灵活（支持纯同步 hook，无需 async def 包装）；Cline 统一异步模型更严格 | 弱对齐（Charles 更宽松） |
| 2.10.15 | on_task_resume / on_task_cancel | `AgentRuntimeHooks` **无**此 hooks；`types.ts` L450-460 `AgentHookSessionShutdownContext` 有 `reason` 字段但属 AgentExtensionHooks 高层；VS Code 端 `apps/vscode/src/core/hooks/` 有 TaskResume/TaskCancel 文件 hook 类型 | `file_hooks/types.py` L73-75 `FileHookType.TASK_RESUME` / `TASK_CANCEL`（Phase 31.6）；`integration.py` L381-413 `_make_before_run_hook` 根据 `snapshot.messages` 非空判断 is_resume；L433-457 `_make_after_run_hook` 根据 `result.status == "aborted"` 判断 is_cancel | 两侧均在**文件 hook 层**实现 TaskResume/TaskCancel，非内建 Python/TS hook；Charles 多了 `previous_state` / `completion_status` 上下文字段（对标 Cline） | 完全对齐 |
| 2.10.16 | additional_context 字段 | `AgentBeforeToolResult`（agent.ts L300-306）**无此字段**；Charles 注释"对标 Cline additionalContext"与源码不符 | `hooks.py` L152 `BeforeToolResult.additional_context: str \| None`；`runtime.py` L1493-1494 收集后 L1520-1541 作为 USER 消息注入 `[System Reminder] {context}`，单次工具调用上限 5 条 | **Charles 独有扩展**；注释残留属"对标说明错误"（声称对标 Cline 但 Cline 无此字段）；注入逻辑对标 Cline beforeTool hook 的 additionalContext 概念但 Cline 实际未实现 | Charles 超出 Cline |

## 3. 重点差距详细说明

### 差距 1：Hook 点数量 — Charles 将 Cline 的 config callback 提升为 hooks（对应对比项 2.10.1 / 2.10.10 / 2.10.11 / 2.10.12）

**Cline 设计**（`agent.ts` L336-365, L437-439, L447-452；`prompt/format.ts` L5-10）：
- `AgentRuntimeHooks` 接口定义 **7 个 hook 点**：beforeRun / afterRun / beforeModel / afterModel / beforeTool / afterTool / onEvent
- `prepareTurn` 是 `AgentRuntimeConfig` 上的**单实例 callback**（非 hook），签名 `(context: AgentRuntimePrepareTurnContext) => Promise<AgentRuntimePrepareTurnResult | undefined>`，每次 iteration 在 beforeModel hooks 之后调用，可修改 messages + systemPrompt
- `requestToolApproval` 是 `AgentRuntimeConfig` 上的**单实例 callback**（非 hook），签名 `(request: ToolApprovalRequest) => Promise<ToolApprovalResult>`，在 `policy.autoApprove === false` 时调用
- `formatUserInputBlock` 是 `prompt/format.ts` 中的**纯工具函数**（非 hook、非 callback），签名 `(input: string, mode: "act"|"plan"|"yolo") => string`，返回 `<user_input mode="${mode}">${input}</user_input>`
- 这三者都是**单实例**：config 上只能配置一个，后注册会覆盖前者

**Charles 设计**（`hooks.py` L304-313, L281-283; `runtime.py` L605-617, L1688-1715）：
- `AgentHooks` dataclass 定义 **9 个 hook 点**：原 7 个 + Phase 23 新增的 `prepare_turn_input` / `format_user_input_block` / `before_approval`
- 每个新 hook 都是 `HookBag` 中的 list，支持**多订阅者链式执行**：
  - `prepare_turn_input`：`runtime.py` L605-609 在 run 开始时（before_run 之后、主循环之前）调用，前一个 hook 的 `modified_input` 作为后一个的输入
  - `format_user_input_block`：`runtime.py` L614-617 在 prepare_turn_input 之后调用，hook 链式修改 `formatted_block`；无 hook 时 runtime 默认 `<user_input mode="...">` 包装（Stage 36.2/M2）
  - `before_approval`：`runtime.py` L1688-1715 在 `_request_tool_approval` 内调用，任一 hook 返回 "approved" 短路，任一返回 "denied" 短路，无决策走用户审批

**影响**：
- Charles 的设计允许**多插件协同**：如一个插件做敏感词过滤（prepare_turn_input），另一个插件注入 IDE 上下文（format_user_input_block），第三个插件做白名单审批（before_approval）；Cline 的单实例 callback 只能配置一个，多插件需求需在 callback 内部自行组合
- Charles 的 `prepare_turn_input` 粒度**粗于** Cline 的 `prepareTurn`：Charles 修改 user input 字符串（每 run 一次），Cline 修改完整 message 列表（每 iteration 一次）；Charles 无法在 iteration 中途修改请求
- Charles 的 `format_user_input_block` 比 Cline 纯函数**更强**：支持 hook 链注入元数据（如时间戳、工作目录、选中文本），Cline 的纯函数仅做固定 XML 包装
- Charles 的 `before_approval` 比 Cline config callback**更灵活**：支持链式决策（白名单优先、黑名单次之、默认用户审批），Cline 只能在单一 callback 内决策

### 差距 2：BeforeToolResult.additional_context — Charles 独有扩展（对应对比项 2.10.6 / 2.10.16）

**Cline 设计**（`agent.ts` L300-306）：
```typescript
export interface AgentBeforeToolResult {
    skip?: boolean;
    stop?: boolean;
    reason?: string;
    input?: unknown;
    policy?: ToolPolicy;
}
```
- **无 `additional_context` 字段**；beforeTool hook 仅能修改 input/policy 或 skip/stop，无法注入上下文到 messages

**Charles 设计**（`hooks.py` L132-152; `runtime.py` L1493-1541）：
```python
@dataclass
class BeforeToolResult:
    skip: bool = False
    stop: bool = False
    reason: str | None = None
    input: Any | None = None
    policy: dict[str, Any] | None = None
    additional_context: str | None = None  # Stage 12.3 (P9) 新增
```
- `additional_context` 字段允许 beforeTool hook 返回上下文文本
- `runtime.py` L1476-1494 收集所有 hook 返回的 `additional_context` 到 `additional_contexts` 列表
- L1519-1527 单次工具调用上限 5 条（`MAX_HOOK_CONTEXT_INJECTIONS = 5`），超出警告并截断
- L1528-1541 每条 `additional_context` 作为 USER 消息注入 `self._state.messages`，前缀 `[System Reminder]`，metadata 标记 `kind: "hook_context_injection"`，发射 `message_added` 事件

**注释残留**：
- `hooks.py` L140-142 注释："additional_context 可注入上下文到模型对话（Stage 12.3 P9 新增，对标 Cline beforeTool hook 返回的 additionalContext）"
- **该注释与 Cline 源码不符**：Cline `AgentBeforeToolResult` 无 `additionalContext` 字段，Charles 的实现是**独立扩展**而非对标
- 这属于"对标说明错误"型注释残留——实现逻辑正确（字段确实存在且工作），但溯源说明不准确

**影响**：
- Charles 的 beforeTool hook 可用于注入工具相关上下文（如调用 `read_files` 前注入文件历史摘要、调用 `exec` 前注入环境变量），LLM 下一轮能看到
- Cline 无此能力，需通过 beforeModel hook 或 prepareTurn callback 实现类似功能，但粒度不同（beforeModel 是全请求级，非工具级）

### 差距 3：BeforeModelContext 字段 — Charles 增加 session_id 和 abort_signal（对应对比项 2.10.3）

**Cline 设计**（`agent.ts` L269-272）：
```typescript
export interface AgentBeforeModelContext {
    snapshot: AgentRuntimeStateSnapshot;
    request: AgentModelRequest;
}
```
- 仅 2 字段；hook 需通过 `request.options.metadata` 间接访问 session_id

**Charles 设计**（`hooks.py` L86-98）：
```python
@dataclass
class BeforeModelContext:
    snapshot: AgentRuntimeStateSnapshot
    request: AgentModelRequest
    session_id: str | None = None  # Phase 26 新增
    abort_signal: Any = None  # Stage 11.2 (J12) 新增
```
- `session_id`（Phase 26）：供 ContextCompactor 等需要会话隔离的 hook 使用，避免从 snapshot 间接提取
- `abort_signal`（Stage 11.2/J12）：让 before_model hook（如 ContextCompactor 的 fallback 路径）能响应中止信号，避免中止后继续执行压缩流程
- `runtime.py` L2106-2112 调用时显式传入：`session_id=self.config.session_id, abort_signal=self._abort_controller.signal`

**影响**：
- Charles 的 ContextCompactor hook 可在 fallback 路径中检查 `abort_signal`，避免中止后仍执行昂贵的压缩操作
- Cline 的 beforeModel hook 需通过 `request.signal` 间接访问 abort signal（agent-runtime.ts L831 `signal: this.abortController?.signal`），但该 signal 是 request 级别，非 context 级别
- Charles 的 session_id 让 hook 无需依赖 snapshot 反推会话身份，简化了 hook 实现

### 差距 4：文件 hook 系统 — 两侧均有但协议字段不同（对应对比项 2.10.15）

**Cline 设计**（`sdk/packages/core/src/hooks/hook-file-hooks.ts`; `shared/src/hooks/contracts.ts`）：
- `HookControl` 接口（contracts.ts L1-9）支持 **7 字段**：`cancel` / `review` / `context` / `overrideInput` / `systemPrompt` / `appendMessages` / `replaceMessages`
- 文件 hook 通过 `spawn`（Node.js child_process）执行子进程
- hook 类型：PreToolUse / PostToolUse / UserPromptSubmit / TaskStart / TaskComplete + TaskResume / TaskCancel（VS Code 端 `apps/vscode/src/core/hooks/`）
- 子进程通过 stdin 接收 JSON 上下文，stdout 返回 JSON 控制

**Charles 设计**（`agent/file_hooks/` 4 文件; `hooks.py` 不直接涉及）：
- `FileHookResult` 数据类（types.py L181-197）支持 **3 字段**：`action`（continue/block/error）/ `reason` / `context_injection`
- 文件 hook 通过 `asyncio.create_subprocess_exec` 执行子进程（runner.py L113）
- hook 类型：PreToolUse / PostToolUse / UserPromptSubmit / TaskStart / TaskComplete / **TaskResume** / **TaskCancel**（types.py L68-75，Phase 31.6）
- 子进程通过 stdin 接收 JSON 上下文（runner.py L128），stdout 返回 JSON 控制
- stdout JSON 协议（runner.py L156-192）：
  - `cancel: true`（Cline 字段）+ `block: true`（Charles 兼容字段）→ block
  - `contextModification`（Cline 字段）+ `context_injection`（Charles 兼容字段）→ continue + 注入
  - 优先级：Cline 字段 > Charles 字段
- `_MAX_PARALLEL_HOOKS = 10`（integration.py L113）：同类型 hook 并行执行上限，超出串行追加
- `blocking` 配置（types.py L111）：默认 False（fail-open，与 Cline 对齐），True 时脚本错误也阻止主流程
- 退出码协议（runner.py L195-228）：exit 0 + 无 JSON → continue；exit 1 + 无 JSON → block（Charles 兼容增强）；其他 → error

**影响**：
- Cline 的 `HookControl` 表达能力**强于** Charles：支持 `overrideInput`（覆盖工具输入）、`systemPrompt`（修改 system prompt）、`appendMessages` / `replaceMessages`（消息级修改），Charles 仅支持 cancel + context_injection
- Charles 的 stdout JSON 协议**兼容** Cline 字段名（`cancel` / `contextModification`），同时保留本系统字段名（`block` / `context_injection`），双向兼容
- Charles 的 `_MAX_PARALLEL_HOOKS=10` 是 Cline 没有的资源限制，避免 hook 数量爆炸时启动过多子进程
- 两侧都支持 `TaskResume` / `TaskCancel`（Charles 在 sdk core 层，Cline 在 VS Code 端），语义对齐

### 差距 5：Hook 同步/异步支持 — Charles 更宽松（对应对比项 2.10.14）

**Cline 设计**（`agent.ts` L336-365）：
- 所有 hook 类型签名均为 `(...) => T \| undefined \| Promise<T \| undefined>`
- **强制异步**：即使 hook 内部同步返回，外层 `await` 仍会执行（轻微开销）
- TypeScript 类型系统强制 hook 返回 `Promise` 或非 Promise 值

**Charles 设计**（`hooks.py` L274-283; `runtime.py` L2675-2680）：
- 类型签名 `Callable[[Ctx], Union[T, None, Awaitable[T, None]]]`，同步异步均支持
- `_call_hook` 实现：
  ```python
  async def _call_hook(self, hook: Callable, ctx: Any) -> Any:
      result = hook(ctx)
      if asyncio.iscoroutine(result):
          result = await result
      return result
  ```
- 同步 hook 直接返回值，异步 hook 返回 coroutine 后 await

**影响**：
- Charles 允许简单的同步 hook（如 `def my_hook(ctx): return BeforeToolResult(skip=True)`）无需 `async def` 包装，降低 hook 编写门槛
- Cline 统一异步模型更严格，但要求所有 hook 至少返回 Promise（TypeScript 类型层面）
- 两者对实际 hook 行为无影响，仅影响编写风格

## 4. 注释残留 vs 实现逻辑残留分析

### 4.1 nanobot 残留检查

在 P2.10 涉及的 3 类核心文件中**未发现任何 nanobot 残留**：

| 文件 | 注释残留 | 实现逻辑残留 | 检查结果 |
|------|---------|-------------|---------|
| `agent/hooks.py` | 无 | 无 | 全文 grep "nanobot" 无匹配 |
| `agent/runtime.py`（hook 调用段 L2080-2141, L2686-2865） | 无 | 无 | hook 相关代码段无 nanobot 注释/变量名/逻辑 |
| `agent/file_hooks/types.py` | 无 | 无 | 全文 grep "nanobot" 无匹配 |
| `agent/file_hooks/loader.py` | 无 | 无 | 全文 grep "nanobot" 无匹配 |
| `agent/file_hooks/runner.py` | 无 | 无 | 全文 grep "nanobot" 无匹配 |
| `agent/file_hooks/integration.py` | 无 | 无 | 全文 grep "nanobot" 无匹配 |
| `agent/file_hooks/registry.py` | 未检查 | 未检查 | 非 P2.10 核心文件（仅进程注册表） |

**结论**：P2.10 涉及的 hooks 生命周期模块**无 nanobot 残留**。P2.1 报告中提到的 12 个 nanobot 残留文件（`skills/registry.py` / `skills/loader.py` / `skills/skill_tool.py` / `skills/__init__.py` / `server.py` / `session.py` / `context.py` / `tools/__init__.py` / `tools/exec_tool.py` / `tools/file_tools.py` / `tools/web_tool.py` / `providers/qwen.py`）均位于其他模块，与 hooks 生命周期无关。

### 4.2 对标说明错误型注释残留

发现 1 处"对标说明错误"型注释残留（非 nanobot 相关）：

| 位置 | 注释内容 | 实际情况 | 处理建议 |
|------|---------|---------|---------|
| `agent/hooks.py` L140-142 | "additional_context 可注入上下文到模型对话（Stage 12.3 P9 新增，对标 Cline beforeTool hook 返回的 additionalContext）" | Cline `AgentBeforeToolResult`（agent.ts L300-306）**无 additionalContext 字段**，Charles 是独立扩展 | 注释残留属"对标说明错误"；实现逻辑正确（字段确实存在且工作），仅溯源说明不准确；建议修正注释为"Charles 独有扩展，Cline 无此字段" |

### 4.3 其他注释残留

`agent/hooks.py` 中的其他注释（如 L17-22 "典型用途"、L24-30 "对标 Cline 源码"引用的行号）均**准确无误**：
- L24-30 引用的 Cline 行号：`agent.ts L265-364`（AgentRuntimeHooks 实际在 L336-365，偏差 1 行，可接受）、`agent-runtime.ts L229-237`（HookBag 实际在 L229-237，准确）、`agent-runtime.ts L544-554`（registerHooks 实际在 L544-554，准确）、`agent-runtime.ts L796-809`（callBeforeRunHooks/callAfterRunHooks 实际在 L796-809，准确）、`agent-runtime.ts L1067-1074`（afterModel 实际在 L1067-1074，准确）、`agent-runtime.ts L1371-1393`（beforeTool 实际在 L1371-1393，准确）、`agent-runtime.ts L1523-1538`（afterTool 实际在 L1523-1538，准确）、`agent-runtime.ts L1208-1250`（prepareTurnForModelRequest 实际在 L1208-1250，准确）

## 5. 一致性等级汇总

| 一致性等级 | 数量 | 对比项 |
|-----------|------|--------|
| 完全对齐 | 6 | 2.10.2 / 2.10.4 / 2.10.7 / 2.10.8 / 2.10.9 / 2.10.13 |
| 弱对齐 | 4 | 2.10.5（nullability）/ 2.10.10（语义不同）/ 2.10.14（同步异步支持） |
| Charles 超出 Cline | 6 | 2.10.1 / 2.10.3 / 2.10.6 / 2.10.11 / 2.10.12 / 2.10.16 |
| 完全对齐（文件 hook 层） | 1 | 2.10.15 |

## 6. 结论

Charles 的 Hooks 生命周期系统在 **Cline 7 hook 基础上扩展为 9 hook**，核心 7 hook（beforeRun/afterRun/beforeModel/afterModel/beforeTool/afterTool/onEvent）的字段定义、注册逻辑、调用顺序、错误处理、返回 None 语义均与 Cline **完全对齐**。Phase 23 新增的 3 hook（prepare_turn_input/format_user_input_block/before_approval）将 Cline 的"单实例 config callback + 纯函数"**提升为多订阅者 hook 链**，是 Charles 的设计扩展，使多插件协同成为可能。

字段层面，Charles 在 `BeforeModelContext`（+session_id/+abort_signal）和 `BeforeToolResult`（+additional_context）上扩展了 Cline 类型，其中 `additional_context` 的注释"对标 Cline additionalContext"与 Cline 源码不符，属"对标说明错误"型注释残留（实现正确，溯源不准）。

文件 hook 系统两侧均有实现且协议兼容（Charles 支持 Cline 的 `cancel`/`contextModification` 字段名），但 Cline 的 `HookControl` 表达能力（7 字段）强于 Charles 的 `FileHookResult`（3 字段）；Charles 增加 `_MAX_PARALLEL_HOOKS=10` 并发上限和 `TaskResume`/`TaskCancel` 文件 hook 类型（对标 Cline VS Code 端）。

nanobot 残留检查：P2.10 涉及的 hooks 生命周期模块（`agent/hooks.py` / `agent/runtime.py` hook 段 / `agent/file_hooks/` 全部）**无任何 nanobot 残留**。
