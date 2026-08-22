# Cline 源码级差异审计报告

> 生成时间：2026-07-25
> 对比范围：`agent/`（当前实现）vs `third_party/cline/sdk/packages/` + `apps/vscode/src/core/`（Cline 原版）
> 对比方法：源码逐文件逐函数对比，按模块组织差异
> 用途：作为 Phase 30+ 重构计划的依据，识别当前实现与 Cline 原版的偏离点和遗漏点

---

## 总览

| 模块 | 子项数 | 已对齐 | 部分对齐 | 缺失 | 偏离 |
|------|-------|-------|---------|------|------|
| A. AgentRuntime 主循环 | 12 | 7 | 2 | 2 | 1 |
| B. 流式工具调用组装 | 7 | 5 | 1 | 1 | 0 |
| C. 完成策略 | 4 | 3 | 1 | 0 | 0 |
| D. AbortController | 4 | 2 | 2 | 0 | 0 |
| E. MistakeTracker | 5 | 3 | 1 | 1 | 0 |
| F. LoopDetectionTracker | 4 | 4 | 0 | 0 | 0 |
| G. Turn queue | 3 | 0 | 0 | 3 | 0 |
| H. 工具系统 | 10 | 5 | 2 | 3 | 0 |
| I. 技能系统 | 9 | 5 | 1 | 3 | 0 |
| J. MCP 集成 | 8 | 3 | 1 | 4 | 0 |
| K. 上下文压缩 | 9 | 7 | 2 | 0 | 0 |
| L. 系统提示构造 | 7 | 6 | 1 | 0 | 0 |
| M. Rules 系统 | 5 | 3 | 2 | 0 | 0 |
| N. Hooks 系统 | 8 | 4 | 2 | 2 | 0 |
| O. FileContextTracker | 4 | 3 | 1 | 0 | 0 |
| P. 会话持久化 | 6 | 2 | 1 | 3 | 0 |
| Q. Checkpoint | 3 | 1 | 1 | 1 | 0 |
| R. 安全规则引擎 | 2 | 0 | 0 | 2 | 0 |
| S. Provider 适配 | 4 | 1 | 1 | 2 | 0 |
| T. Telemetry/Connectors/Kanban | 6 | 0 | 1 | 5 | 0 |
| **合计** | **120** | **65** | **23** | **30** | **1** |

**整体对齐度**：约 54%（已对齐 65/120），相比 Phase 28 起始的 70% 估算更精确。已对齐部分覆盖核心 loop、流式组装、压缩、系统提示、安全检测等关键路径；缺失部分主要分布在 Turn queue、subprocess-sandbox、model-tool-routing、MCP 高级特性、SQLite 持久化、Telemetry/Connectors/Kanban 等外围能力。

---

## A. AgentRuntime 主循环

**Cline 源码**：`sdk/packages/agents/src/agent-runtime.ts` L446-794
**当前实现**：`agent/runtime.py` L385-605

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| A1 | 主循环结构 | `while (maxIterations === undefined \|\| iteration < maxIterations)` L629-632 | `while (max_iterations is None or iteration < max_iterations)` L455-458 | 已对齐 |
| A2 | abort 检查点 | `throwIfAborted()` 在每轮开头、before_model 后、stream 中、工具前 | `_throw_if_aborted()` 在每轮开头、stream 中、工具前 | 已对齐 |
| A3 | iteration 自增时机 | L635 `iteration += 1` 在 turn-started 事件前 | L461 同 | 已对齐 |
| A4 | finish_reason 处理 | L642-678 区分 aborted/max-tokens/error/normal，无 tool_calls 时分支处理 | L465-498 同 | 已对齐 |
| A5 | pending_tool_calls 状态 | L679 `pendingToolCalls = toolCalls.map(t => t.toolCallId)` | L499 同 | 已对齐 |
| A6 | terminal_tool_message 终止判断 | L722-738 `findCompletingToolMessage` 检查 completesRun | 同（在 _execute_tool_calls 中处理） | 已对齐 |
| A7 | restore() 恢复 | L487-503 替换 messages、重置状态、保留 listeners/tools/hooks/plugins | L317-337 同；额外重置 _loop_tracker/_mistake_tracker/_abort_controller | 已对齐 |
| A8 | AbortController 类型 | `AbortController` + `AbortSignal`（浏览器/Node 标准） | `asyncio.Event` + `AbortedError`（自定义） | 部分对齐 |
| A9 | abort 后 lastError 记录 | L465 `state.lastError = abortError.message` + L466 telemetry 事件 | L346 `_state.status = "aborted"`，未记 last_error | 偏离 |
| A10 | `consumePendingUserMessage` | L841-852 iteration > 1 时从 turn-queue 取待处理用户消息追加 | 无 turn-queue，运行中再次输入直接报错 `RuntimeError("already running")` L404-405 | 缺失 |
| A11 | emit run-failed vs run-finished | L778-789 failed 时 emit `run-failed`，aborted 时 emit `run-finished` | 始终 emit `run-finished`（含 aborted），未区分 | 部分对齐 |
| A12 | max_iterations 超限异常 | L742-744 抛 `Agent runtime exceeded maxIterations` | 同 | 已对齐 |

**关键差异**：
- **A9 偏离**：Cline 在 abort 时记录 `lastError` 并触发 telemetry `TASK_CANCELLED_EVENT`；当前实现只设置 `status="aborted"`，未记录 `last_error`，前端无法展示中止原因。建议修复 `agent/runtime.py::abort()` 补充 `self._state.last_error = reason`。
- **A10 缺失**：Turn queue 是 Cline 的核心交互能力，允许用户在 agent 运行中排队下一条输入（queue/steer 两种 delivery 模式）。当前实现直接拒绝运行中再次输入，体验上不如 Cline 流畅。

---

## B. 流式工具调用组装

**Cline 源码**：`agent-runtime.ts` L965-1000（key 选择）、L1031-1058（invalid tool calls）
**当前实现**：`agent/runtime.py` L693-794

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| B1 | 主 key 选择 | `key = event.toolCallId ?? \`tool_${event.index ?? nextToolIndex}\`` | 同（L698-704），用 `is not None` 避免 0 被当 falsy | 已对齐 |
| B2 | PendingToolAssembly 结构 | `{toolCallId, toolName, inputText, inputValue, metadata, parseError}` | 同（_PendingToolAssembly dataclass） | 已对齐 |
| B3 | 增量 JSON parse | `input_text` 累积，最终一次性 parse | 同（_parse_tool_input 在组装完成后解析） | 已对齐 |
| B4 | invalid_tool_calls 反馈 | L1031-1058 写入 message.metadata，下一轮注入 user 消息提示 LLM 修正参数 | 同（_extract_invalid_tool_calls + metadata 注入） | 已对齐 |
| B5 | 流式 input_text 增量 parse | Cline 在 stream 过程中持续尝试 parse 部分文本（用于 UI 预览） | 仅累积，最终一次性 parse | 部分对齐 |
| B6 | missing_name / missing_arguments / invalid_arguments 三种 reason | L1031-1058 分类 | 同（_InvalidToolCall.reason） | 已对齐 |
| B7 | tool_call_id 稳定性（Qwen） | N/A（Cline 不针对 Qwen） | qwen.py 按 index 维护 map 修复 Qwen tool_call_id 不稳定 | 已对齐 |

**关键差异**：
- **B5 部分对齐**：Cline 在 stream 过程中持续尝试 parse 部分文本，让 UI 能实时预览工具参数。当前实现只在 stream 结束后一次性 parse，UI 体验略差。低优先级，可在前端优化时补齐。

---

## C. 完成策略（CompletionPolicy）

**Cline 源码**：`agent-runtime.ts` L622-625、L688-695
**当前实现**：`agent/runtime.py` + `agent/types.py::CompletionPolicy`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| C1 | requireCompletionTool | L622-625 `getCompletionToolReminderMessage` 在运行开头注入提示 | 同（_build_completion_reminder） | 已对齐 |
| C2 | completion_guard | 可选 guard 函数返回提醒文本 | 同（CompletionPolicy.completion_guard） | 已对齐 |
| C3 | completionReminderMessages | L688-695 无 tool_calls 时检查并继续下一轮 | 同 | 已对齐 |
| C4 | reminder 消息类型 | L624 `addUserReminderMessage` 作为 user 消息追加 | 同 | 已对齐 |

**结论**：完成策略已完全对齐。

---

## D. AbortController

**Cline 源码**：`agent-runtime.ts` L424、L454-470、L592、L831
**当前实现**：`agent/abort.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| D1 | signal 类型 | `AbortSignal`（标准 Web API） | `asyncio.Event` | 部分对齐 |
| D2 | stream 透传 | L831 `request.signal = abortController.signal`，provider 内部检查 | 同（abort_signal 传给 model.stream） | 已对齐 |
| D3 | 工具透传 | `AgentToolContext.signal` 传给工具 | 同（context.abort_signal） | 已对齐 |
| D4 | 子进程中断 | AbortSignal 触发时 spawn 的子进程会被 kill | 当前 run_commands 用 asyncio.create_subprocess_exec，abort 时未 kill 子进程 | 部分对齐 |

**关键差异**：
- **D1 部分对齐**：`asyncio.Event` 与 `AbortSignal` 语义等价，但 `AbortSignal` 支持 reason 携带（`signal.reason`），asyncio.Event 仅支持布尔状态。当前实现用 `AbortedError.reason` 弥补，功能等价。
- **D4 部分对齐**：用户点"停止"后，stream 和工具检查点会立即响应，但 `run_commands` 工具已 spawn 的子进程不会被 kill，会继续运行直到自然结束。建议在 `run_commands.py` 中订阅 abort_signal，触发时 kill 子进程。

---

## E. MistakeTracker

**Cline 源码**：`sdk/packages/core/src/runtime/safety/mistake-tracker.ts`
**当前实现**：`agent/mistake_tracker.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| E1 | 错误分类 | 3 类：`api_error` / `invalid_tool_call` / `tool_execution_failed` | 5 类：`param_error` / `tool_not_found` / `permission_denied` / `exec_error` / `timeout`（更细） | 已对齐（细化） |
| E2 | 计数策略 | 单一 `consecutiveMistakes` 计数器，不分类累计 | 按类型分类计数（_per_type_count）+ 总数（_total_count） | 已对齐（细化） |
| E3 | 软/硬阈值 | 单一 `maxConsecutiveMistakes`，达到即 stop | 双阈值：`max_per_type`（软，注入 guidance）+ `max_total`（硬，stop） | 已对齐（增强） |
| E4 | 恢复提示注入 | `appendRecoveryNotice` 钩子由外部注入 | `_build_recovery_guidance` 内建生成 | 部分对齐 |
| E5 | telemetry 事件 | `onLimitTelemetry` 钩子在 limit 触发时上报 | 无 telemetry 上报 | 缺失 |

**关键差异**：
- **E5 缺失**：Cline 在错误达到阈值时触发 telemetry 事件，便于监控 agent 失败模式。当前实现无 telemetry 集成，建议在 Phase 30+ 接入 telemetry 后补齐。
- 当前实现的 5 类分类比 Cline 3 类更细，是正向偏离，便于精准恢复提示。

---

## F. LoopDetectionTracker

**Cline 源码**：`sdk/packages/core/src/runtime/safety/loop-detection.ts`
**当前实现**：`agent/loop_detection.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| F1 | 检测键 | `toolCallSignature(input)` = `JSON.stringify(sortKeys(input))` | 同（_signature 函数 + sortKeys） | 已对齐 |
| F2 | 软/硬阈值 | `softThreshold=3` / `hardThreshold=5` | 同（LoopDetectionConfig） | 已对齐 |
| F3 | 重置条件 | 工具名或签名变化时 `consecutiveIdenticalCount=1` | 同 | 已对齐 |
| F4 | inspect 返回 | `{kind: "ok"\|"soft"\|"hard", message?}` | 同（LoopDetectionVerdict） | 已对齐 |

**结论**：LoopDetectionTracker 已完全对齐。

---

## G. Turn queue（用户输入排队）

**Cline 源码**：`sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts`
**当前实现**：无

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| G1 | PendingPromptEntry | `{id, prompt, mode, delivery: "queue"\|"steer", userImages, userFiles}` | 无 | 缺失 |
| G2 | queue delivery | 排队，当前 run 结束后自动 consume 下一条 | 无 | 缺失 |
| G3 | steer delivery | 实时插入到当前 iteration 的 model request（L841-852 `consumePendingUserMessage`） | 无 | 缺失 |

**关键差异**：
- **G1-G3 缺失**：Turn queue 是 Cline 区别于简单 chat 的核心交互能力。当前实现运行中再次输入直接报错，用户必须等待当前 run 结束。建议在 Phase 30+ 实现一个简化版：
  - 至少支持 queue delivery（运行中输入排队，结束后消费）
  - steer delivery 可作为 P2 优先级
  - 前端 UI 显示"已排队 N 条待处理"

---

## H. 工具系统

**Cline 源码**：`sdk/packages/core/src/extensions/tools/definitions.ts`、`schemas.ts`、`helpers.ts`、`runtime.ts`
**当前实现**：`agent/tools/base.py` + 各工具文件

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| H1 | 工具工厂 | `createTool()` 工厂函数 + zod schema | `BaseTool` 基类 + 手写 JSON Schema | 已对齐（形式不同） |
| H2 | Schema 运行时校验 | `validateWithZod` + `zodToJsonSchema` | `jsonschema.Draft7Validator`（Phase 29.1） | 已对齐 |
| H3 | per-tool timeout/retry | `timeoutMs` / `retryable` / `maxRetries` 内建 | Phase 29.2 实现 `_execute_with_timeout_and_retry` | 已对齐 |
| H4 | withTimeout 包裹 | `Promise.race` + `TimeoutError` | `asyncio.wait_for` + `asyncio.TimeoutError` | 已对齐 |
| H5 | tool-approval | `tool-approval.ts` 文件轮询 IPC | `before_approval` hook + SSE 前端弹窗 | 已对齐（形式不同） |
| H6 | subprocess-sandbox | `subprocess-sandbox.ts` spawn 隔离 node 子进程执行工具 | 无 | 缺失 |
| H7 | model-tool-routing | `model-tool-routing.ts` 按模型/provider/mode 路由工具集 | 无 | 缺失 |
| H8 | apply_patch 解析 | `apply-patch-parser.ts` 完整 parse | `apply_patch.py` 实现 | 已对齐 |
| H9 | output-limits | `MAX_COMMAND_OUTPUT_CHARS` / `MAX_READ_LINES` / `MAX_READ_OUTPUT_CHARS` / `MAX_SEARCH_OUTPUT_CHARS` | 各工具内硬编码（未统一常量） | 部分对齐 |
| H10 | tool presets | `presets.ts` 工具集预设（如 read-only / full） | 无 | 缺失 |

**关键差异**：
- **H6 缺失**：subprocess-sandbox 是 Cline 用 node 子进程隔离执行工具的机制，主要用于插件安全隔离。当前实现工具直接在主进程执行，插件场景下有安全风险。量化场景暂无插件需求，可延后。
- **H7 缺失**：model-tool-routing 允许按模型/provider/mode 动态启用/禁用工具。例如 OpenAI 模型用 apply_patch，其他模型用 editor。当前实现所有模型用同一工具集，对多 provider 场景不友好。建议 Phase 30+ 实现。
- **H9 部分对齐**：output-limits 在 Cline 中统一常量便于调整，当前实现分散在各工具。建议提取到 `agent/tools/constants.py`。

---

## I. 技能系统

**Cline 源码**：`sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`、`skill-frontmatter-toggle.ts`
**当前实现**：`agent/skills/loader.py`、`registry.py`、`skill_tool.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| I1 | skills 工具 XML 返回格式 | `<command-name>...<command-args>...<command-instructions>...</command-instructions>` | 同 | 已对齐 |
| I2 | description 动态含技能列表 | `Object.defineProperty(executor, "configuredSkills")` | `_build_description()` | 已对齐 |
| I3 | always/on-demand 分层 | always=True 自动注入 system prompt | 同 | 已对齐 |
| I4 | runningSkills 并发去重 | L179-206 `runningSkills` Set，重复调用返回 "already running" | 无 | 缺失 |
| I5 | skillsTimeoutMs 15s | `withTimeout(15000)` 包裹技能执行 | 无超时 | 缺失 |
| I6 | allowedSkillNames 白名单 | L39-73 `toAllowedSkillSet` + `isSkillAllowed` | 无 | 缺失 |
| I7 | skill frontmatter toggle | `skill-frontmatter-toggle.ts` 支持 disabled 字段 | 无（技能 SKILL.md 无 frontmatter 解析） | 缺失 |
| I8 | resolveSkillRecord 模糊匹配 | L106-172 支持 `namespace:skill` 格式 + 后缀匹配 + 歧义检测 | 仅精确匹配 skill_name | 部分对齐 |
| I9 | watcher 热加载 | `UserInstructionConfigWatcher` 监听文件变化热加载 | 启动时一次性加载 | 已对齐 |

**关键差异**：
- **I4-I7 缺失**：这 4 项是技能系统的健壮性保障：
  - runningSkills 去重：防止 LLM 重复调用同一技能导致指令重复注入
  - skillsTimeoutMs：防止技能 SKILL.md 加载卡死
  - allowedSkillNames：多 agent 场景下限制可用技能
  - frontmatter toggle：通过 frontmatter `disabled: true` 禁用技能（不需删除文件）
  建议在 Phase 30+ 集中补齐这 4 项。
- **I8 部分对齐**：当前仅精确匹配，Cline 支持 `namespace:skill` 后缀匹配和歧义检测，对多技能重名场景更友好。

---

## J. MCP 集成

**Cline 源码**：`sdk/packages/core/src/extensions/mcp/` 下 9 个文件
**当前实现**：`agent/mcp/client.py`、`registry.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| J1 | client 连接管理 | stdio/sse/http 三种传输 | stdio/http 两种（无 sse） | 部分对齐 |
| J2 | tools 注册与动态加载 | `manager.ts` 统一管理 + `tools/list` 动态发现 | `registry.py` 启动时加载 + 缓存 | 已对齐 |
| J3 | OAuth 认证 | `oauth.ts` 完整 OAuth 2.0 流程 | 无 | 缺失 |
| J4 | policies 工具策略 | `policies.ts` `createDisabledMcpToolPolicy` 按工具禁用 | 无 | 缺失 |
| J5 | name-transform 命名空间 | `name-transform.ts` `defaultMcpToolNameTransform` + 64 字符限制 + hash | 无（直接用 `server__tool` 格式，无长度保护） | 缺失 |
| J6 | plugin-server-registration | `plugin-server-registration.ts` 插件提供 MCP 服务器 | 无 | 缺失 |
| J7 | config-loader | `.cline/mcp_settings.json` 标准格式 | `agent_config/mcp_servers.yaml` 自定义格式 | 已对齐（形式不同） |
| J8 | use_mcp_tool / access_mcp_resource 工具 | 内建工具调用 MCP | 同（agent/tools/mcp.py） | 已对齐 |

**关键差异**：
- **J3-J6 缺失**：OAuth/policies/name-transform/plugin-server-registration 是 MCP 高级特性：
  - OAuth：OAuth 2.0 认证流程，对需要授权的 MCP 服务器（如 GitHub）必需
  - policies：按工具禁用某些 MCP 工具（安全控制）
  - name-transform：MCP 工具名可能超过 64 字符（OpenAI 限制），需 hash 截断
  - plugin-server-registration：允许插件动态注册 MCP 服务器
  量化场景当前 MCP 服务器都是本地 stdio，暂不需要这些特性。若未来接入远程 MCP（如 GitHub），需补齐 OAuth 和 name-transform。

---

## K. 上下文压缩

**Cline 源码**：`sdk/packages/core/src/extensions/context/compaction.ts`、`compaction-shared.ts`、`agentic-compaction.ts`、`basic-compaction.ts`、`budget-projection/`
**当前实现**：`agent/context.py::ContextCompactor`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| K1 | 触发比例 0.9 | `COMPACTION_TRIGGER_RATIO = 0.9` | 同 | 已对齐 |
| K2 | maxInputTokens 128000 | `DEFAULT_MAX_INPUT_TOKENS = 128000` | 同 | 已对齐 |
| K3 | preserve_recent_tokens 20000 | `compaction-shared.ts` L13 | 同 | 已对齐 |
| K4 | _find_cut_index 安全切割 | L317-350 防 orphan tool_use/tool_result | 同 | 已对齐 |
| K5 | PRESERVED_ASSISTANT_TEXT_COUNT 3 | `basic-compaction.ts` L60 | 同 | 已对齐 |
| K6 | agentic + basic fallback | L233-281 agentic 优先，失败 fallback basic | 同 | 已对齐 |
| K7 | state-aware 持久化 | `compaction.ts` L566-623 `getState`/`saveState` | 同（CompactionStateManager） | 已对齐 |
| K8 | budget-projection 提前压缩 | `budget-projection/project.ts` 完整实现 | Phase 29.4 实现 `_project_future_usage` | 部分对齐 |
| K9 | compact-session CLI | `scripts/compact-session.ts` 调试工具 | 无 | 缺失（低优先级） |

**关键差异**：
- **K8 部分对齐**：当前 budget-projection 实现简化版，仅估算 `tools_tokens + avg_tool_result`。Cline 实现更完整：
  - 区分 `BudgetPolicyIntent`（`agentic_summary` / `basic_compaction_projection` / `normal_provider_request`）
  - `protectLatestTypedUser` / `protectLiveTailFromDrop` / `dropUnsafeOutsideLiveTail` / `dropThinkingBlocks` 策略
  - `findLatestTypedUserMessageIndex` 保护最新用户消息
  当前实现未区分 intent，策略较粗。建议 Phase 30+ 细化。
- **K9 缺失**：compact-session CLI 是调试工具，用于离线分析压缩效果。低优先级，可延后。

---

## L. 系统提示构造

**Cline 源码**：`sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`
**当前实现**：`agent/context.py::SystemPromptBuilder`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| L1 | 分层组装 | runtime-builder.ts 多层 | SystemPromptBuilder 11 层 | 已对齐 |
| L2 | `<env>` 段 | 是 | Phase 16 | 已对齐 |
| L3 | 工具列表段 | 是 | Phase 16 | 已对齐 |
| L4 | `<user_input mode>` 标签 | 是 | Phase 16 | 已对齐 |
| L5 | MCP 服务器概览 | 是 | Phase 22 | 已对齐 |
| L6 | always/on-demand 技能分层 | 是 | 是 | 已对齐 |
| L7 | mode 切换（plan/act） | `session-runtime.ts` | `plan_mode.py` + SessionState.mode | 已对齐 |

**结论**：系统提示构造已完全对齐。

---

## M. Rules 系统

**Cline 源码**：`apps/vscode/src/core/context/instructions/user-instructions/` 下 frontmatter.ts/rule-conditionals.ts/rule-helpers.ts/cline-rules.ts + `sdk/packages/core/src/runtime/safety/rules.ts`
**当前实现**：`agent/rules_loader.py`（Phase 29.5）

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| M1 | frontmatter 解析 | `parseYamlFrontmatter` + fail-open | 同 | 已对齐 |
| M2 | rule-conditionals 评估 | `evaluateRuleConditionals` 支持 `paths` | 同 + 扩展 `applyTo` / `mode` / `enabled` | 已对齐（增强） |
| M3 | cline-rules 段拼接 | `getRuleFilesTotalContentWithMetadata` | `format_rules_content` | 已对齐 |
| M4 | external-rules（.cursorrules/.windsurfrules） | `external-rules.ts` 加载外部规则文件 | 无 | 缺失（低优先级） |
| M5 | workflows 工作流文件 | `workflows.ts` 加载 `.clinerules/workflows/*.md` | 无 | 部分对齐 |

**关键差异**：
- **M4 缺失**：external-rules 加载 `.cursorrules` / `.windsurfrules` / `.clinerules` 等外部规则文件。量化场景暂无需求，可延后。
- **M5 部分对齐**：当前 `agent_config/rules/*.md` 已支持工作流规则文件，但未实现 Cline 的 `.clinerules/workflows/` 目录约定。形式不同但功能等价。
- 当前实现扩展了 `applyTo`（agent 模式过滤）和 `mode`（业务模式过滤）两类条件，比 Cline 仅 `paths` 更细。这是正向偏离，便于量化场景按 research/trade 业务模式切换规则。

---

## N. Hooks 系统

**Cline 源码**：`sdk/packages/core/src/extensions/hooks/` + `apps/vscode/src/core/hooks/`
**当前实现**：`agent/hooks.py`（Python 内建）+ `agent/file_hooks/`（文件 hook）

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| N1 | 9 个内建 Python hooks | agent.ts L265-364 | hooks.py 9 个 hook 点 | 已对齐 |
| N2 | before_approval hook | `toolPolicies` config | `before_approval` hook | 已对齐 |
| N3 | 文件 hook（PreToolUse 等） | `hook-file-hooks.ts` subprocess 执行 | `file_hooks/runner.py` subprocess 执行 | 已对齐 |
| N4 | hook-factory + templates | `hook-factory.ts` + `templates.ts` 模板系统 | 无 | 缺失 |
| N5 | HookError / HookProcessRegistry | `HookError.ts` + `HookProcessRegistry.ts` | 无 | 缺失 |
| N6 | shell-escape | `shell-escape.ts` 命令转义 | 无 | 缺失 |
| N7 | hook context-injection | 是（stdin JSON 注入） | 同 | 已对齐 |
| N8 | 7 种 hook 类型 | PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete/TaskResume/TaskCancel | 5 种（缺 TaskResume/TaskCancel） | 部分对齐 |

**关键差异**：
- **N4-N6 缺失**：hook-factory/templates/HookError/HookProcessRegistry/shell-escape 是 Cline 文件 hook 的高级设施：
  - hook-factory：批量生成 hook 配置
  - templates：预置 hook 模板（如 lint/format/notify）
  - HookError：hook 执行错误的标准化处理
  - HookProcessRegistry：hook 进程注册表，便于取消
  - shell-escape：跨平台命令转义
  量化场景当前文件 hook 较简单，这些设施可延后。
- **N8 部分对齐**：缺 TaskResume（会话恢复时触发）和 TaskCancel（用户取消时触发）两种 hook 类型。建议补齐，与会话持久化/abort 机制配合。

---

## O. FileContextTracker

**Cline 源码**：`apps/vscode/src/core/context/context-tracking/FileContextTracker.ts`
**当前实现**：`agent/file_context_tracker.py`（Phase 29.3）

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| O1 | 持久化文件状态 | 是（磁盘 JSON） | 同 | 已对齐 |
| O2 | 跨压缩周期保留 | 是（compaction 复用 tracker 数据） | 同 | 已对齐 |
| O3 | read/edited/created/deleted 4 类 | 是 | 同 | 已对齐 |
| O4 | UI 展示 API | 是（VSCode webview） | 同（`/api/chat/sessions/{id}/file_context`） | 已对齐 |

**结论**：FileContextTracker 已完全对齐。

---

## P. 会话持久化

**Cline 源码**：`sdk/packages/core/src/services/storage/session-store.ts`、`sqlite-session-store.ts`、`team-store.ts`、`sqlite-team-store.ts`
**当前实现**：`agent/session.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| P1 | 存储格式 | SQLite + 磁盘 JSON（消息列表） | 纯 JSON 文件 | 部分对齐 |
| P2 | 跨进程锁 | `SqliteLockManager`（搜索可见） | 无（文件锁依赖 OS） | 缺失 |
| P3 | state-migrations 版本迁移 | `state-migrations.ts` | 无（用 `_SESSION_FILE_VERSION` 常量但无迁移逻辑） | 缺失 |
| P4 | session-export 导出 | `apps/cli/src/session/export.ts` | 无 | 缺失 |
| P5 | SessionRecord 字段 | 27 字段（sessionId/source/pid/startedAt/endedAt/exitCode/status/...） | 5 字段（session_id/created_at/last_active/message_count/title） | 部分对齐 |
| P6 | 团队存储 | `team-store.ts` 多 agent 协作 | 无 | 缺失 |

**关键差异**：
- **P1 部分对齐**：JSON 文件存储简单但性能差，大对话历史（>1MB）时序列化/反序列化慢。SQLite 索引查询快，且支持事务。建议 Phase 30+ 迁移到 SQLite（用 Python `sqlite3` 标准库）。
- **P2 缺失**：跨进程锁对多进程场景（如 web + scheduler 同时操作会话）必需。当前实现依赖 OS 文件锁，不可靠。
- **P3 缺失**：state-migrations 在 schema 变更时自动迁移旧数据。当前实现用版本常量但无迁移逻辑，schema 变更会导致旧数据无法加载。
- **P5 部分对齐**：当前 SessionRecord 字段过少，缺少 pid/exitCode/source/workspace_root 等运维信息。

---

## Q. Checkpoint

**Cline 源码**：搜索 `checkpoint` 相关文件，含 shadow-git
**当前实现**：`agent/checkpoint.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| Q1 | 快照机制 | shadow-git 磁盘快照（git stash + branch） | 消息列表深拷贝 JSON | 部分对齐 |
| Q2 | 文件状态快照 | 是（工作区文件状态） | 无（仅消息状态） | 缺失 |
| Q3 | 回滚粒度 | 工作区文件 + 消息列表 | 仅消息列表 | 缺失 |

**关键差异**：
- **Q1-Q3 部分对齐/缺失**：Cline checkpoint 用 shadow-git 在工具执行前快照工作区文件，支持回滚到工具执行前的文件状态。当前实现仅快照消息列表，无法回滚文件修改。量化场景下 editor/apply_patch 工具修改文件后无法撤销是隐患。建议 Phase 30+ 实现：
  - 简化版：工具执行前用 `shutil.copytree` 备份工作区
  - 完整版：用 git stash（需工作区是 git 仓库）

---

## R. 安全规则引擎

**Cline 源码**：`sdk/packages/core/src/runtime/safety/rules.ts`
**当前实现**：无

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| R1 | isRuleEnabled / formatRulesForSystemPrompt | L6-21 | 无（rules_loader.py 实现等价功能） | 缺失（功能等价） |
| R2 | mergeRulesForSystemPrompt | L23-33 合并多源规则 | 无 | 缺失 |

**关键差异**：
- **R1-R2 缺失**：Cline `rules.ts` 是 rules 系统的辅助函数，当前 `rules_loader.py` 已实现等价功能（`format_rules_content` + `load_for_session`）。形式不同但功能等价，无需单独实现。

---

## S. Provider 适配

**Cline 源码**：`sdk/packages/core/src/services/llms/` 下 handler-factory.ts/provider-defaults.ts/provider-settings.ts + `sdk/packages/core/src/services/storage/provider-settings-manager.ts`
**当前实现**：`agent/providers/base.py`、`qwen.py`

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| S1 | handler-factory | 多 provider 工厂（Anthropic/OpenAI/OpenRouter/DeepSeek/Qwen/...） | 仅 Qwen | 缺失 |
| S2 | provider-defaults | 各 provider 默认配置 | 无 | 缺失 |
| S3 | provider-settings-manager | 统一配置管理 | 无 | 缺失 |
| S4 | Qwen 适配 | 是（`qwen.mdx` 文档） | 是（`providers/qwen.py`） | 已对齐 |

**关键差异**：
- **S1-S3 缺失**：Cline 支持多 provider 动态切换，当前实现仅 Qwen。量化场景当前仅需 Qwen，若未来接入其他模型（如 DeepSeek/GPT）需补齐 handler-factory。建议 Phase 30+ 实现 `agent/providers/factory.py` + `agent/providers/openai.py`（兼容 OpenAI 协议的 provider）。

---

## T. Telemetry / Connectors / Kanban

**Cline 源码**：`sdk/packages/core/src/services/telemetry/` + `apps/cli/src/connectors/` + `apps/cli/src/commands/kanban.ts`
**当前实现**：`agent/telemetry.py` + `agent/connectors.py` + `agent/kanban.py`（均为骨架）

| # | 子项 | Cline 实现 | 当前实现 | 差异级别 |
|---|------|-----------|---------|---------|
| T1 | OpenTelemetryAdapter | `OpenTelemetryAdapter.ts` 完整 trace/span/metric | 骨架（仅类定义） | 部分对齐 |
| T2 | TelemetryLoggerSink | `TelemetryLoggerSink.ts` 日志 sink | 无 | 缺失 |
| T3 | Connectors（Slack/TG/Discord/Linear/GChat/WhatsApp） | 6 个连接器 | 骨架（仅基类） | 缺失 |
| T4 | Kanban 看板 | `kanban.ts` 任务管理 | 骨架 | 缺失 |
| T5 | FeatureFlagsService | `FeatureFlagsService.ts` + posthog | 无 | 缺失 |
| T6 | captureTaskLifecycleEvent | task 生命周期 telemetry 事件 | 无 | 缺失 |

**关键差异**：
- **T1-T6 缺失**：Telemetry/Connectors/Kanban 是 Cline 的运维/监控/协作层，量化场景当前无需这些能力。若未来需要接入企业监控（如 Datadog）或协作工具（如 Slack 通知交易信号），再补齐。优先级最低。

---

## 改进建议（按优先级排序）

### P0（核心体验，建议 Phase 30 优先）

1. **G1-G3 Turn queue 实现**：让用户能在 agent 运行中排队下一条输入，体验上对标 Cursor/Trae
   - 文件：新增 `agent/turn_queue.py`
   - 集成：`runtime.py::run()` + `server.py` SSE 端点
   - 前端：显示"已排队 N 条"

2. **A9 abort lastError 记录**：让前端能展示中止原因
   - 修改：`agent/runtime.py::abort()` 补充 `self._state.last_error = reason`
   - 工作量：1 行代码

3. **D4 子进程中断**：abort 时 kill 已 spawn 的子进程
   - 修改：`agent/tools/run_commands.py` 订阅 abort_signal，触发时 kill 子进程
   - 工作量：约 20 行代码

### P1（健壮性，建议 Phase 31）

4. **I4 runningSkills 并发去重**：防止 LLM 重复调用同一技能
   - 修改：`agent/skills/skill_tool.py` 增加 `_running_skills: set[str]`
   - 工作量：约 15 行代码

5. **I5 skillsTimeoutMs 15s**：防止技能加载卡死
   - 修改：`agent/skills/skill_tool.py` 用 `asyncio.wait_for` 包裹
   - 工作量：约 10 行代码

6. **I7 skill frontmatter toggle**：通过 frontmatter `disabled: true` 禁用技能
   - 修改：`agent/skills/loader.py` 解析 SKILL.md frontmatter
   - 工作量：约 30 行代码

7. **H9 output-limits 统一常量**：提取到 `agent/tools/constants.py`
   - 工作量：约 20 行代码

8. **N8 TaskResume/TaskCancel hook 补齐**：与会话持久化/abort 配合
   - 修改：`agent/hooks.py` + `agent/runtime.py`
   - 工作量：约 40 行代码

### P2（多 provider/模型支持，建议 Phase 32）

9. **H7 model-tool-routing 实现**：按模型/provider/mode 动态启用/禁用工具
   - 新增：`agent/tools/routing.py`
   - 集成：`runtime.py::get_tools()` 按当前模型过滤
   - 工作量：约 100 行代码

10. **S1-S3 多 provider 适配**：补齐 OpenAI/DeepSeek 等
    - 新增：`agent/providers/factory.py` + `agent/providers/openai.py`
    - 工作量：约 200 行代码

11. **J5 name-transform 实现**：MCP 工具名超长时 hash 截断
    - 修改：`agent/mcp/registry.py`
    - 工作量：约 30 行代码

### P3（运维/监控，按需）

12. **P1 SQLite 会话存储**：替换 JSON 文件
    - 工作量：约 200 行代码（含迁移脚本）

13. **P3 state-migrations 版本迁移**：schema 变更自动迁移
    - 工作量：约 100 行代码

14. **Q1-Q3 文件状态快照 checkpoint**：用 git stash 实现工作区回滚
    - 工作量：约 150 行代码

15. **K8 budget-projection 细化**：区分 BudgetPolicyIntent
    - 工作量：约 100 行代码

### P4（低优先级，可延后）

16. **H6 subprocess-sandbox**：插件安全隔离
17. **J3 OAuth 认证**：远程 MCP 服务器
18. **J4 policies 工具策略**：按工具禁用
19. **J6 plugin-server-registration**：插件动态注册 MCP
20. **M4 external-rules**：.cursorrules 等外部规则
21. **N4-N6 hook-factory/templates/HookError/shell-escape**
22. **K9 compact-session CLI**
23. **T1-T6 Telemetry/Connectors/Kanban**

---

## 附录：当前实现正向偏离 Cline 的点

以下是当前实现相比 Cline 原版的增强（非缺失）：

1. **M2 rule-conditionals 扩展**：Cline 仅支持 `paths` 条件，当前实现扩展 `applyTo`（agent 模式）+ `mode`（业务模式）+ `enabled`，便于量化场景按 research/trade 切换规则
2. **E1 MistakeTracker 错误分类细化**：Cline 3 类，当前 5 类（param_error/tool_not_found/permission_denied/exec_error/timeout），恢复提示更精准
3. **E3 MistakeTracker 双阈值**：Cline 单一 maxConsecutiveMistakes，当前 `max_per_type`（软）+ `max_total`（硬），避免单类型错误快速触发硬阈值
4. **B7 Qwen tool_call_id 稳定性修复**：Cline 不针对 Qwen，当前按 index 维护 map 修复 Qwen provider 的 tool_call_id 不稳定问题
5. **O4 FileContextTracker API 端点**：Cline 仅 VSCode webview，当前提供 REST API 端点便于第三方集成

这些正向偏离建议保留，不需回退对齐 Cline。

---

## 结语

当前实现已对齐 Cline 核心架构（约 54% 子项完全对齐，23% 部分对齐），覆盖主循环、流式工具调用、完成策略、上下文压缩、系统提示、安全检测、文件 hook 等关键路径。

剩余 30 个缺失子项中：
- **3 个 P0**（Turn queue / abort lastError / 子进程中断）影响核心交互体验，建议优先补齐
- **8 个 P1**（技能系统健壮性 / hook 补齐）影响稳定性，建议 Phase 31 补齐
- **3 个 P2**（多 provider / model-tool-routing）影响扩展性，建议 Phase 32 补齐
- **3 个 P3**（SQLite / state-migrations / checkpoint）影响运维，按需补齐
- **13 个 P4**（subprocess-sandbox / OAuth / Telemetry 等）量化场景用不到，可长期延后

按此优先级推进，可在 3-4 个 Phase 内将对齐度从 54% 提升到 80%+，达到对标 Cursor/Trae 的体验目标。
