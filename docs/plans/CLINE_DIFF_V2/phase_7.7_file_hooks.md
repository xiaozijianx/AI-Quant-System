# Phase 7.7 文件 Hooks 系统对比

> 对比范围：Cline `apps/vscode/src/core/hooks/` 下的 `hook-factory.ts` / `HookProcess.ts` / `HookProcessRegistry.ts` / `HookError.ts` / `shell-escape.ts` / `templates.ts` / `hooks-utils.ts` / `HookDiscoveryCache.ts`，对比 Charles `agent/file_hooks/` 的 `types.py` + `registry.py` + `runner.py` + `loader.py` + `integration.py` + `agent_config/hooks/templates/`；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts` L1-820+（`HookRunner` 抽象 + `StdioHookRunner` + `CombinedHookRunner` + `NoOpRunner` + `HookFactory.create/createWithStreaming` + `validateHookOutput` + `MAX_CONTEXT_MODIFICATION_SIZE = 50000` + `HOOK_EXECUTION_TIMEOUT_MS = 30000` + `EXIT_CODE_SIGINT = 130`）
> - `third_party/cline/apps/vscode/src/core/hooks/HookProcess.ts` L1-300+（`HookProcess extends EventEmitter` + `getHookLaunchConfig` + Windows PowerShell 缓存 + `MAX_HOOK_OUTPUT_SIZE = 1MB` + abort signal 订阅 + 流式 stdout/stderr）
> - `third_party/cline/apps/vscode/src/core/hooks/HookProcessRegistry.ts` L1-64（`HookProcessRegistry` 静态类 + `activeProcesses: Set<HookProcess>` + `register/unregister/terminateAll/getActiveCount`）
> - `third_party/cline/apps/vscode/src/core/hooks/HookError.ts` L1-123（`HookErrorType` 枚举 4 类型 + `HookErrorInfo` + `HookExecutionError` + `timeout/validation/execution/cancellation` 静态工厂）
> - `third_party/cline/apps/vscode/src/core/hooks/shell-escape.ts` L1-67（`escapeWindowsShellPath` + `escapeUnixShellPath` + `escapeShellPath`）
> - `third_party/cline/apps/vscode/src/core/hooks/templates.ts` L1-100+（9 个 hook 模板 + Windows PowerShell 模板）
> - `third_party/cline/apps/vscode/src/core/hooks/HookDiscoveryCache.ts`（hook 脚本发现缓存）
> - `third_party/cline/apps/vscode/src/core/hooks/hooks-utils.ts` L1-8（`getHooksEnabledSafe`）
> - `third_party/cline/.clinerules/hooks/README.md` L1-80（hook 类型文档：TaskStart / TaskResume / TaskCancel / TaskComplete / UserPromptSubmit / PreToolUse / PostToolUse / PreCompact / Notification）
>
> Charles 源码：
> - `agent/file_hooks/types.py` L1-230（`FileHookType` 7 类型枚举 + `FileHookConfig` + `FileHookContext` + `FileHookResult` + `HookError` + `DEFAULT_HOOK_TIMEOUT = 30` + `SUPPORTED_SCRIPT_EXTENSIONS`）
> - `agent/file_hooks/registry.py` L1-148（`HookProcessRegistry` 实例类 + `asyncio.Lock` + `register/unregister/list_running/kill_all/get_count` + `get_global_registry` 单例）
> - `agent/file_hooks/runner.py` L1-289（`run_hook` 异步函数 + `_build_command` + `_parse_stdout_json` + `_INTERPRETER_MAP` + `PYTHONIOENCODING=utf-8`）
> - `agent/file_hooks/loader.py` L1-205（`load_hooks_from_dir` + `_parse_hook_script` + `_parse_frontmatter` + `_parse_apply_to`）
> - `agent/file_hooks/integration.py` L1-552（`build_file_hooks_agent_hooks` + `_run_hooks_of_type` + `_MAX_PARALLEL_HOOKS = 10` + 5 个 hook 工厂函数 `_make_before_tool_hook` 等）
> - `agent_config/hooks/templates/` 4 个模板（`pre_command_template.py` / `pre_edit_template.py` / `post_edit_template.py` / `context_injection_template.py`）
> - `agent/runtime.py` L273-358（`_load_file_hooks` 加载入口 + `enable_file_hooks` / `file_hooks_dir` 配置）
> - `agent/types.py` L548-551（`enable_file_hooks: bool = False` + `file_hooks_dir: str | None`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的文件 Hooks 系统。**核心结论：计划文件 P7.7 列出的 18 项对比项多数已对齐（hook 类型/PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete/TaskResume/TaskCancel/hook-factory/templates/HookError/HookProcessRegistry/context-injection/asyncio.gather/超时/Windows 编码），但计划低估了 Cline 的 hook 类型数（实际 9 个而非 7 个，Charles 缺 Notification + PreCompact），且未识别 4 个关键缺口：(1) HookProcessRegistry 已实现但未接入 runtime abort 流程；(2) `run_hook` 未接受 abort_signal 参数，单 hook 无法被中止；(3) Charles 无流式 stdout/stderr 输出，仅全量收集；(4) Charles 无 JSON 混合输出提取逻辑，无输出大小限制，无 contextModification 大小限制。**

### 计划文件核实结果

AGENT_COMPARISON_PLAN_V2.md L2652-2692 的 P7.7 对比表标注 7.7.1-7.7.18 全部"已对齐"或"实现不同但等价"。经源码核实：

| 计划项 | 计划标注 | 实际核实 | 一致性 |
|--------|---------|---------|--------|
| 7.7.1 hook 类型数 | 7 vs 7 已对齐 | Cline 9 个（PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskResume/TaskCancel/TaskComplete/Notification/PreCompact）/ Charles 7 个（缺 Notification + PreCompact） | **计划不准** — Cline 多 2 个 |
| 7.7.2 PreToolUse | 已对齐 | Cline `Hooks.PreToolUse` + `PreToolUseData` / Charles `FileHookType.PRE_TOOL_USE` | 高 |
| 7.7.3 PostToolUse | 已对齐 | Cline `Hooks.PostToolUse` + `PostToolUseData` / Charles `FileHookType.POST_TOOL_USE` | 高 |
| 7.7.4 UserPromptSubmit | 已对齐 | Cline `Hooks.UserPromptSubmit` + `UserPromptSubmitData` / Charles `FileHookType.USER_PROMPT_SUBMIT` | 高 |
| 7.7.5 TaskStart | 已对齐 | Cline `Hooks.TaskStart` / Charles `FileHookType.TASK_START` | 高 |
| 7.7.6 TaskComplete | 已对齐 | Cline `Hooks.TaskComplete` / Charles `FileHookType.TASK_COMPLETE` | 高 |
| 7.7.7 TaskResume | 已对齐（Stage 31.6） | Cline `Hooks.TaskResume` + `TaskResumeData.previousState` / Charles `FileHookType.TASK_RESUME` + `previous_state` | 高 |
| 7.7.8 TaskCancel | 已对齐（Stage 31.6） | Cline `Hooks.TaskCancel` + `TaskCancelData.completionStatus` / Charles `FileHookType.TASK_CANCEL` + `completion_status` | 高 |
| 7.7.9 HookProcess | 是 vs subprocess 等价 | Cline `HookProcess extends EventEmitter`（流式 + abort + 1MB 限制 + Windows PowerShell 缓存）/ Charles `run_hook` 函数（asyncio.create_subprocess_exec 全量收集） | 中（功能等价但 Cline 多 4 项增强） |
| 7.7.10 hook-factory | 已对齐 | Cline `HookFactory` + `HookRunner` 抽象 + `StdioHookRunner` + `CombinedHookRunner` + `NoOpRunner` / Charles `build_file_hooks_agent_hooks` 单函数 | 中-高（Charles 简化但功能对齐） |
| 7.7.11 templates | 已对齐 | Cline 9 模板 + PowerShell 模板 / Charles 4 模板（pre_command/pre_edit/post_edit/context_injection） | 中（数量差距，Charles 缺 TaskStart/TaskResume/TaskCancel/TaskComplete/UserPromptSubmit 模板） |
| 7.7.12 HookError | 已对齐（Stage 12.4） | Cline `HookExecutionError` + 4 类型枚举（TIMEOUT/VALIDATION/EXECUTION/CANCELLATION）+ 静态工厂 / Charles `HookError` 简单异常类 | 中（Charles 无错误分类） |
| 7.7.13 HookProcessRegistry | 已对齐（Stage 12.4） | Cline 静态类 + `terminateAll` 被 HookProcess 自动调用 / Charles 实例类 + `get_global_registry` 单例 **但 runtime 未调用 `kill_all`** | 低-中（实现存在但未接入 abort 流程） |
| 7.7.14 shell-escape | shlex.quote 等价 | Cline `escapeShellPath` 专用文件 / Charles **未使用** shlex（file_hooks 无 shell 转义，因 `create_subprocess_exec` 数组参数无需 shell） | **计划不准** — Charles 不是用 shlex.quote，而是无需 shell 转义 |
| 7.7.15 context-injection | 已对齐（Stage 12.3） | Cline `contextModification` 字段 + 50KB 截断 / Charles `contextModification` + `context_injection` 双字段兼容，**无大小限制** | 中-高（Charles 无截断） |
| 7.7.16 hook 并发执行 | asyncio.gather 已对齐（Stage 12.5） | Cline `Promise.all` 在 `CombinedHookRunner` / Charles `asyncio.gather` + `_MAX_PARALLEL_HOOKS = 10` 批次 | 高（Charles 多了资源限制） |
| 7.7.17 hook 超时 | 已对齐 | Cline `HOOK_EXECUTION_TIMEOUT_MS = 30000` / Charles `DEFAULT_HOOK_TIMEOUT = 30` | 高 |
| 7.7.18 Windows 编码 | N/A vs PYTHONIOENCODING=utf-8 Charles 特化 | Cline 不需要（Node.js 原生 UTF-8）/ Charles `runner.py` L105 设置 `PYTHONIOENCODING=utf-8` 防 cp936 乱码 | 高（Charles 特化合理） |

### 核心结论

1. **7 类核心 hook 已对齐**：PreToolUse / PostToolUse / UserPromptSubmit / TaskStart / TaskComplete / TaskResume / TaskCancel 在双方均有实现，类型枚举值、字段映射、Python hook 点映射对齐。
2. **Cline 多 2 类 hook**：`Notification`（通知类 hook）和 `PreCompact`（压缩前 hook）在 Charles 完全缺失。Cline 源码 `hook-factory.ts` L102-130 的 `Hooks` interface 明确列出 9 个 hook 类型。
3. **HookProcessRegistry 实现存在但未接入 runtime abort 流程**（关键缺口 P1）：Charles `registry.py` L30-115 完整实现了 `register/unregister/kill_all/get_count`，但 `integration.py` L166/L210 调用 `run_hook(cfg, context)` 时**未传 `registry` 参数**（runner.py L64 该参数默认 None）；`runtime.py` 的 `abort()` 方法 L405-423 也不调用 `get_global_registry().kill_all()`。结果是 abort 后 hook 子进程仍可能在后台运行。
4. **`run_hook` 不接受 abort_signal**（关键缺口 P2）：Cline `HookProcess.run(inputJson)` 内部订阅 `abortSignal` 立即 kill 子进程；Charles `run_hook(cfg, context, registry=None)` 签名无 abort_signal 参数，唯一的中止路径是 `asyncio.wait_for` 超时后 `process.kill()`。
5. **流式输出完全缺失**（缺口 P2）：Cline `HookProcess extends EventEmitter` 通过 `on("line", ...)` 实时推送 stdout/stderr 行到 UI；Charles 仅在子进程退出后用 `process.communicate()` 全量收集 stdout/stderr，无实时反馈。
6. **JSON 提取鲁棒性差距大**：Cline `parseJsonOutput()` 有两阶段提取（直接 parse → 从末尾扫描大括号边界提取），可处理 hook 输出 debug 日志 + JSON 混合场景；Charles `_parse_stdout_json` 仅 `json.loads(stdout_text)`，任意 debug 输出都会导致解析失败退化为按退出码处理。
7. **输出大小限制缺失**：Cline `MAX_HOOK_OUTPUT_SIZE = 1MB`（stdout + stderr 合计）+ `MAX_CONTEXT_MODIFICATION_SIZE = 50KB`（contextModification 截断 + `[... context truncated due to size limit ...]` 标记）；Charles 无任何大小限制，hook 输出超大时可能导致 OOM 或 prompt 溢出。
8. **错误分类差距**：Cline `HookExecutionError` 有 4 类错误枚举（TIMEOUT/VALIDATION/EXECUTION/CANCELLATION）+ 静态工厂方法 + 详细 `details` 字段；Charles `HookError` 仅有 `hook_name/exit_code/stderr` 三字段，无错误分类，无用户友好消息。
9. **Telemetry 完全缺失**：Cline 在 hook 执行 started/completed/cancelled/failed 5 个时机上报 `telemetryService.captureHookExecution`（含 durationMs/exitCode/contextSize/errorType）；Charles 无任何 hook 遥测。
10. **shell-escape 计划标注失实**：计划 7.7.14 标注 Charles 用 `shlex.quote` 等价 Cline `shell-escape.ts`。实际 Charles `file_hooks/runner.py` 用 `asyncio.create_subprocess_exec(*cmd, ...)` 数组参数（`shell=False`），**完全不需要 shell 转义**；`shlex` 仅在 `agent/connectors.py` L40 出现，与 file_hooks 无关。
11. **Charles 合理扩展**：(a) `applyTo` frontmatter 字段支持工具白名单过滤（Cline 无此机制，hook 对所有工具生效）；(b) `blocking` frontmatter 字段支持阻塞模式（Cline 始终 fail-open）；(c) `_MAX_PARALLEL_HOOKS = 10` 资源限制防子进程耗尽（Cline 用 `Promise.all` 无限制）；(d) `PYTHONIOENCODING=utf-8` Windows 编码特化；(e) `context_injection` 兼容字段。
12. **架构差异 — 单文件 vs 多文件**：Cline 拆成 7 个文件（hook-factory.ts + HookProcess.ts + HookProcessRegistry.ts + HookError.ts + shell-escape.ts + templates.ts + HookDiscoveryCache.ts）；Charles 拆成 5 个文件（types.py + registry.py + runner.py + loader.py + integration.py）+ 4 个模板文件。
13. **hook 脚本约定差异**：Cline 用**无扩展名** + **shebang** 的可执行文件（`PreToolUse` 文件名，首行 `#!/usr/bin/env bash`），Unix 需 `chmod +x`，Windows 不支持；Charles 用**带扩展名**文件（`.py` / `.sh` / `.js` / `.bat`），按扩展名选解释器，Windows 通过 `cmd /c` 支持 `.bat`。
14. **frontmatter 配置 Charles 独有**：Charles `loader.py` L93-130 解析 YAML frontmatter（`description` / `applyTo` / `blocking` / `timeout`）；Cline 无 frontmatter，配置由文件名 + shebang 决定。
15. **nanobot 残留**：P7.7 范围内（`agent/file_hooks/` + `agent_config/hooks/` + `agent/runtime.py` 加载入口 + `agent/types.py` 配置字段）共 **0 处注释残留、0 处实现逻辑残留**。所有文件均无 "nanobot" 字样。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| hook 类型覆盖 | 中 | 7/9 对齐，Charles 缺 Notification + PreCompact |
| hook 执行模型 | 中 | subprocess 等价，但 Charles 无流式输出 + 无 abort_signal |
| HookProcessRegistry 接入 | 低 | Charles 实现完整但未接入 runtime abort |
| hook-factory 抽象 | 中-高 | Charles 单函数简化，功能对齐但缺 NoOpRunner + DiscoveryCache |
| templates 覆盖 | 中 | 4/9 对齐，Charles 缺 5 个生命周期 hook 模板 |
| HookError 分类 | 中 | Charles 无错误类型枚举 |
| shell-escape | 高 | Charles 无需 shell 转义（架构差异，非缺陷） |
| context-injection | 中-高 | 双字段兼容合理，但 Charles 无 50KB 截断 |
| hook 并发执行 | 高 | asyncio.gather + 资源限制（Charles 增强） |
| hook 超时 | 高 | 30s 默认值一致 |
| Windows 编码 | 高 | Charles PYTHONIOENCODING=utf-8 合理特化 |
| 输出大小限制 | 低 | Charles 无 1MB / 50KB 限制 |
| JSON 提取鲁棒性 | 低 | Charles 无混合输出提取逻辑 |
| Telemetry | 缺失 | Charles 无 hook 遥测 |
| abort 中止 | 低 | Charles 单 hook 不可中止 + registry 未接入 |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.7.1 | hook 类型数 | 9（`Hooks` interface L102-130：PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskResume/TaskCancel/TaskComplete/Notification/PreCompact） | 7（`FileHookType` L56-75：缺 Notification + PreCompact） | 中 | Charles 缺 2 类 hook。Notification 用于通知类事件，PreCompact 用于压缩前触发 |
| 7.7.2 | PreToolUse | `Hooks.PreToolUse = { preToolUse: PreToolUseData }`；`StdioHookRunner` 执行；可 cancel + contextModification | `FileHookType.PRE_TOOL_USE`；`_make_before_tool_hook` 工厂；block 时 `BeforeToolResult(skip=True)` | 高 | 已对齐。Cline 用 `cancel: true` 字段，Charles 用 `action: "block"` |
| 7.7.3 | PostToolUse | `Hooks.PostToolUse = { postToolUse: PostToolUseData }`；含 tool_name/result/is_error/duration_ms | `FileHookType.POST_TOOL_USE`；`_make_after_tool_hook` 工厂；block 时 `AfterToolResult(stop=True)` | 高 | 已对齐。Charles `FileHookContext` L146-152 字段与 Cline PostToolUseData 对齐 |
| 7.7.4 | UserPromptSubmit | `Hooks.UserPromptSubmit = { userPromptSubmit: UserPromptSubmitData }`；含 prompt 字段；空 prompt 显式补全 | `FileHookType.USER_PROMPT_SUBMIT`；`_make_prepare_turn_input_hook` 工厂；block 时 `PrepareTurnInputResult(stop=True)` | 高 | 已对齐。Cline L317-319 显式补 `prompt=""` 防 proto3 omit；Charles 无此问题（dict 序列化） |
| 7.7.5 | TaskStart | `Hooks.TaskStart = { taskStart: TaskStartData }`；含 taskMetadata（taskId/ulid/initialTask） | `FileHookType.TASK_START`；`_make_before_run_hook` 工厂；block 时 `StopControl(stop=True)` | 高 | 已对齐。Charles `FileHookContext` 无 taskMetadata 字段，但通过 `snapshot` 间接获取 |
| 7.7.6 | TaskComplete | `Hooks.TaskComplete = { taskComplete: TaskCompleteData }` | `FileHookType.TASK_COMPLETE`；`_make_after_run_hook` 工厂；block 仅记录日志 | 高 | 已对齐。Charles `_make_after_run_hook` L454-455 明确 "after_run 文件 hook 试图阻止已完成的任务（忽略）"，与 Cline TaskComplete 不可 cancel 一致 |
| 7.7.7 | TaskResume | `Hooks.TaskResume = { taskResume: TaskResumeData }`；含 `previousState`（last_message_ts / message_count / conversation_history_deleted） | `FileHookType.TASK_RESUME`；`_make_before_run_hook` 通过 `is_resume=bool(ctx.snapshot.messages)` 区分；`previous_state` dict 字段对齐 | 高 | 已对齐（Phase 31.6）。Charles `integration.py` L391-398 构建 `previous_state` 与 Cline taskResume.previousState 字段一致 |
| 7.7.8 | TaskCancel | `Hooks.TaskCancel = { taskCancel: TaskCancelData }`；含 `completionStatus`；README 标注 "NOT cancellable" | `FileHookType.TASK_CANCEL`；`_make_after_run_hook` 通过 `result.status == "aborted"` 区分；`completion_status` 字段对齐 | 高 | 已对齐（Phase 31.6）。Charles `integration.py` L436 用 `is_cancel = ctx.result.status == "aborted"` 区分 |
| 7.7.9 | HookProcess | `HookProcess extends EventEmitter` L89-300+；spawn 子进程；流式 stdout/stderr via `on("line")`；`MAX_HOOK_OUTPUT_SIZE = 1MB`；`abortSignal` 订阅；Windows PowerShell 缓存 `WINDOWS_HOOK_LAUNCHER_CACHE_TTL_MS = 5min`；`getHookLaunchConfig` 平台分支 | `run_hook(cfg, context, registry=None)` async 函数；`asyncio.create_subprocess_exec` 数组参数；`process.communicate()` 全量收集；`PYTHONIOENCODING=utf-8`；`_INTERPRETER_MAP` 按扩展名选解释器 | 中 | 功能等价但 Cline 多 5 项增强：(a) 流式输出；(b) abort_signal；(c) 1MB 输出限制；(d) Windows PowerShell 缓存；(e) EventEmitter 事件模型 |
| 7.7.10 | hook-factory | `HookFactory` 类 L720-820+；`create/createWithStreaming` 工厂方法；`HookRunner` 抽象 + `StdioHookRunner` + `CombinedHookRunner`（Promise.all 合并） + `NoOpRunner`（null-object 模式）；`HookDiscoveryCache` O(1) 缓存 | `build_file_hooks_agent_hooks` 单函数 L466-547；按 hook_type 分组；`_run_hooks_of_type` 内联 `asyncio.gather` 合并；无 hook 时返回 `None` | 中-高 | Charles 简化但功能对齐。差异：(a) Charles 无 NoOpRunner（用 None 替代）；(b) Charles 无 HookDiscoveryCache（每次重新扫描目录）；(c) Charles 无 CombinedHookRunner 类（内联在 `_run_hooks_of_type`） |
| 7.7.11 | templates | `templates.ts` L1-100+；9 个模板（TaskStart/TaskResume/TaskCancel/TaskComplete/PreToolUse/PostToolUse/UserPromptSubmit/Notification/PreCompact）+ Windows PowerShell 统一模板；Unix 为 bash 脚本 + jq 解析 | `agent_config/hooks/templates/` 4 个 Python 模板（pre_command_template.py / pre_edit_template.py / post_edit_template.py / context_injection_template.py） | 中 | 数量差距 4 vs 9。Charles 缺 TaskStart/TaskResume/TaskCancel/TaskComplete/UserPromptSubmit 模板。Charles 模板用 Python + frontmatter，Cline 用 bash + jq |
| 7.7.12 | HookError | `HookError.ts` L1-123；`HookErrorType` 枚举 4 类（TIMEOUT/VALIDATION/EXECUTION/CANCELLATION）；`HookErrorInfo` 结构化信息（type/message/details/scriptPath/exitCode/stderr）；`HookExecutionError extends Error`；4 个静态工厂（`timeout/validation/execution/cancellation`）；`isHookError` 类型守卫 | `types.py` L200-223 `HookError(Exception)`；`hook_name` / `exit_code` / `stderr` 三字段；无错误类型枚举；无静态工厂 | 中 | Charles 无错误分类。Cline 的 `HookErrorType.VALIDATION` 专门处理 JSON 校验失败，`CANCELLATION` 专门处理 abort，Charles 都归入通用错误 |
| 7.7.13 | HookProcessRegistry | `HookProcessRegistry.ts` L1-64；**静态类** + `activeProcesses: Set<HookProcess>`；`register/unregister` 由 `HookProcess` 自动调用（constructor + safeUnregister）；`terminateAll` 在 extension deactivation 调用；`getActiveCount` 监控 | `registry.py` L30-125；**实例类** + `asyncio.Lock`；`register/unregister/list_running/kill_all/get_count`；`get_global_registry()` 全局单例 | 低-中 | **关键缺口**：Charles 实现完整但未接入。`integration.py` L166 `run_hook(cfg, context)` 不传 `registry` 参数；`runtime.py` `abort()` 不调用 `kill_all()`。Cline 的 register/unregister 由 HookProcess 自动调用，Charles 需调用方手动传参 |
| 7.7.14 | shell-escape | `shell-escape.ts` L1-67；`escapeWindowsShellPath`（双引号 + 双 "" 转义）+ `escapeUnixShellPath`（单引号 + '\'' 转义）+ `escapeShellPath` 平台分支；用于 `spawn(shell: true)` 场景 | **无** shell 转义逻辑（`file_hooks/runner.py` 用 `asyncio.create_subprocess_exec(*cmd, shell=False)` 数组参数，无需 shell 转义） | 高（架构差异） | **计划标注失实**：计划 7.7.14 称 Charles 用 `shlex.quote` 等价。实际 Charles file_hooks 模块**完全不用** shlex（shlex 仅在 `agent/connectors.py` L40 出现，与 file_hooks 无关）。Charles 用 `create_subprocess_exec` 数组参数绕过 shell，安全性更高 |
| 7.7.15 | context-injection | `contextModification` 字段；`MAX_CONTEXT_MODIFICATION_SIZE = 50000`（~50KB）截断 + `[... context truncated due to size limit ...]` 标记 | `contextModification` + `context_injection` 双字段兼容（优先级 `contextModification > context_injection`）；**无大小限制** | 中-高 | Charles 双字段兼容合理（Stage 5.4 P8），但缺失 50KB 截断可能导致 prompt 溢出 |
| 7.7.16 | hook 并发执行 | `CombinedHookRunner` L651-684 用 `Promise.all(this.runners.map(...))` 并行；`cancel = results.some(r => r.cancel)`；`contextModification = results.map(...).join("\n\n")` | `_run_hooks_of_type` L116-234 用 `asyncio.gather(*tasks, return_exceptions=True)`；`_MAX_PARALLEL_HOOKS = 10` 批次；超出部分串行；`injections.append(...)` 后 `"\n\n".join(...)` | 高 | Charles 多了资源限制（10 并发上限），Cline 无限制。合并逻辑一致（任一 block 即 block，context 用 `\n\n` 连接） |
| 7.7.17 | hook 超时 | `HOOK_EXECUTION_TIMEOUT_MS = 30000`（30s）；`setTimeout` 触发后 `childProcess.kill("SIGTERM")`；抛 `HookExecutionError.timeout` | `DEFAULT_HOOK_TIMEOUT = 30`（30s）；`asyncio.wait_for(..., timeout=config.timeout)` 触发后 `process.kill()` + `asyncio.wait_for(process.wait(), timeout=2.0)`；返回 `FileHookResult(action="error" or "block")` | 高 | 已对齐。差异：Cline 抛异常 + telemetry，Charles 返回 result 由调用方判断 |
| 7.7.18 | Windows 编码 | 不需要（Node.js 原生 UTF-8 处理） | `runner.py` L104-105 `env["PYTHONIOENCODING"] = "utf-8"` 防 Windows cp936 乱码 | 高 | Charles 特化合理。Windows 上 Python 子进程默认用 cp936 编码，中文 stderr 会乱码 |
| 7.7.19 | 流式输出 | `HookProcess extends EventEmitter`；`on("line", line, stream)` 实时推送 stdout/stderr 行；UI 可实时显示 hook 执行进度 | 无（`process.communicate()` 全量收集，仅在子进程退出后获取 stdout/stderr） | 缺失 | Charles 无实时反馈，长时 hook 用户看不到进度 |
| 7.7.20 | abort_signal 支持 | `HookProcess` constructor 接受 `abortSignal?: AbortSignal`；`abortSignal.addEventListener("abort", abortHandler)`；abort 时立即 `childProcess.kill("SIGTERM")` + reject | `run_hook` 签名无 `abort_signal` 参数；仅 `asyncio.wait_for` 超时路径可终止 | 缺失 | **关键缺口**：Charles 单 hook 无法被用户中止，只能等超时 |
| 7.7.21 | JSON 提取鲁棒性 | `parseJsonOutput()` 两阶段：(a) 直接 `JSON.parse(stdout)`；(b) 失败后从末尾扫描大括号边界提取（处理 debug 日志 + JSON 混合） | `_parse_stdout_json` 单阶段：`json.loads(stdout_text)`，失败返回 None | 低 | Charles 任意 debug 输出（如 `print("starting...")`）都会导致 JSON 解析失败 |
| 7.7.22 | 输出大小限制 | `MAX_HOOK_OUTPUT_SIZE = 1MB`（stdout + stderr 合计）+ `MAX_CONTEXT_MODIFICATION_SIZE = 50KB` | 无任何大小限制 | 缺失 | Charles hook 输出超大时可能 OOM 或 prompt 溢出 |
| 7.7.23 | Telemetry | `telemetryService.captureHookExecution` 在 started/completed/cancelled/failed 5 时机上报；含 durationMs/exitCode/contextSize/errorType/source( global/workspace)/toolName | 无 hook 遥测 | 缺失 | Charles 无 hook 执行统计 |
| 7.7.24 | HookDiscoveryCache | `HookDiscoveryCache.ts` 单例；O(1) 缓存 hook 脚本发现结果；避免重复扫描目录 | 无（每次 `load_hooks_from_dir` 重新扫描目录） | 缺失 | Charles 多 hook 触发时重复 IO |
| 7.7.25 | NoOpRunner（null-object 模式） | `NoOpRunner` L230-241；无 hook 时返回 `NoOpRunner`，调用方无需 null 检查 | `build_file_hooks_agent_hooks` 返回 `None`；`runtime._load_file_hooks` 检查 `if file_hooks is None` | 中 | Charles 用 None 检查替代，功能等价但需调用方判空 |
| 7.7.26 | CombinedHookRunner | `CombinedHookRunner` L651-684 独立类；`Promise.all` 并行 + 结果合并 | `_run_hooks_of_type` L116-234 内联函数；`asyncio.gather` 并行 + 结果合并 | 高 | 功能等价。Charles 无独立类但逻辑一致 |
| 7.7.27 | shouldContinue 弃用检查 | `validateHookOutput` L41-61 检查 `shouldContinue` 字段，返回迁移指南 | 无（Charles 从未支持 `shouldContinue` 字段） | 不适用 | Charles 无历史包袱 |
| 7.7.28 | frontmatter 配置 | 无（配置由文件名 + shebang 决定） | `loader.py` L93-130 解析 YAML frontmatter（`description`/`applyTo`/`blocking`/`timeout`） | Charles 增强 | Charles 独有增强，配置更灵活 |
| 7.7.29 | applyTo 工具白名单 | 无（hook 对所有工具生效） | `FileHookConfig.apply_to` + `applies_to_tool(tool_name)` 方法 | Charles 增强 | Charles 独有增强，可按工具过滤 |
| 7.7.30 | blocking 阻塞模式 | 无（始终 fail-open） | `FileHookConfig.blocking` 字段（默认 False fail-open，True 时错误也阻止） | Charles 增强 | Charles 独有增强，支持阻塞模式 |
| 7.7.31 | 脚本命名约定 | 无扩展名 + shebang（`PreToolUse` 文件名，首行 `#!/usr/bin/env bash`）；Unix 需 `chmod +x`；Windows 不支持 | 带扩展名（`.py`/`.sh`/`.js`/`.bat`）；按扩展名选解释器；Windows 通过 `cmd /c` 支持 `.bat` | 架构差异 | Cline git-style 跨平台一致但 Windows 不支持；Charles 多语言支持但需匹配解释器 |
| 7.7.32 | EXIT_CODE_SIGINT | `EXIT_CODE_SIGINT = 130`（128 + signal 2）；用于 cancel telemetry exitCode 字段 | 无 | 缺失 | Charles 无 SIGINT 约定处理 |
| 7.7.33 | 全局/工作区 hook 分离 | `getAllHooksDirs` 返回全局（`~/Documents/Cline/Hooks/`）+ 工作区（`.clinerules/hooks/`）多目录；`source: "global" \| "workspace"` 标记；CombinedHookRunner 合并 | 单一 `file_hooks_dir`（默认 `agent_config/hooks/`）；无全局/工作区分离 | 缺失 | Charles 无多工作区支持 |

---

## 三、重点差距详解

### 3.1 HookProcessRegistry 未接入 runtime abort 流程（关键缺口 P1）

**严重度**：P1（abort 后 hook 子进程可能继续运行，导致资源泄漏 + 潜在副作用）

**Cline 实现**（`HookProcessRegistry.ts` + `HookProcess.ts`）：

Cline 的 `HookProcessRegistry` 是**静态类**，`activeProcesses: Set<HookProcess>` 全局唯一。`HookProcess` 在 `run()` 方法 L128 自动调用 `HookProcessRegistry.register(this)`，在 `safeUnregister()` L292-297 自动调用 `HookProcessRegistry.unregister(this)`。Extension deactivation 时调用 `terminateAll()` 统一 kill。

```typescript
// HookProcess.ts L128
HookProcessRegistry.register(this)
this.isRegistered = true
// ... 子进程执行 ...
// L292 safeUnregister
private safeUnregister(): void {
    if (this.isRegistered) {
        HookProcessRegistry.unregister(this)
        this.isRegistered = false
    }
}
```

**Charles 实现**（`registry.py` + `runner.py` + `integration.py` + `runtime.py`）：

Charles 的 `HookProcessRegistry` 是**实例类**，`get_global_registry()` 提供全局单例。`run_hook` 函数接受可选 `registry: HookProcessRegistry | None = None` 参数（runner.py L64），若传入则在 L122-124 注册、L148-150 注销。

**关键问题**：`integration.py` L166 和 L210 调用 `run_hook(cfg, context)` 时**未传 `registry` 参数**：

```python
# integration.py L165-167
tasks = [run_hook(cfg, context) for cfg in batch]  # 未传 registry
results = await asyncio.gather(*tasks, return_exceptions=True)

# integration.py L209-210
for cfg in overflow:
    result = await run_hook(cfg, context)  # 未传 registry
```

同时 `runtime.py` 的 `abort()` 方法 L405-423 仅设置 `_aborted` 标志 + 调用 `_abort_controller.abort()`，**不调用** `get_global_registry().kill_all()`：

```python
# runtime.py L405-423
def abort(self, reason: str = "") -> None:
    if self._aborted:
        return
    self._aborted = True
    self._abort_reason = reason or "aborted by user"
    self._state.status = "aborted"
    self._state.last_error = self._abort_reason
    self._abort_controller.abort(self._abort_reason)
    # ↑ 未调用 get_global_registry().kill_all()
```

**修复建议**：
1. `integration.py` 的 `_run_hooks_of_type` 接受 `registry` 参数，传给 `run_hook(cfg, context, registry=registry)`。
2. `build_file_hooks_agent_hooks` 调用 `get_global_registry()` 获取单例，传给各 hook 工厂函数。
3. `runtime.py` 的 `abort()` 方法在 `_abort_controller.abort()` 后调用 `await get_global_registry().kill_all()`（需将 `abort()` 改为 async 或在 `_run_async` 中订阅 abort signal 调用 `kill_all`）。

### 3.2 `run_hook` 不接受 abort_signal（关键缺口 P2）

**严重度**：P2（用户中止后 hook 仍执行到超时，浪费资源 + 用户体验差）

**Cline 实现**（`HookProcess.ts` L110-169）：

`HookProcess` constructor 接受 `abortSignal?: AbortSignal`，在 `run()` 中：

```typescript
// HookProcess.ts L132-169
if (this.abortSignal?.aborted) {
    reject(new Error("Hook execution cancelled"))
    return
}
const abortHandler = () => {
    if (this.childProcess && !this.isCompleted) {
        this.isCompleted = true
        if (this.abortSignal) {
            this.abortSignal.removeEventListener("abort", abortHandler)
        }
        if (this.timeoutHandle) {
            clearTimeout(this.timeoutHandle)
            this.timeoutHandle = null
        }
        this.safeUnregister()
        if (this.childProcess.pid) {
            this.childProcess.kill("SIGTERM")  // 立即 kill
        }
        reject(new Error("Hook execution cancelled by user"))
    }
}
if (this.abortSignal) {
    this.abortSignal.addEventListener("abort", abortHandler, { once: true })
}
```

**Charles 实现**（`runner.py` L61-244）：

`run_hook` 签名无 `abort_signal` 参数：

```python
async def run_hook(
    config: FileHookConfig,
    context: FileHookContext,
    registry: HookProcessRegistry | None = None,
) -> FileHookResult:
    # ... 无 abort_signal 订阅 ...
    try:
        process = await asyncio.create_subprocess_exec(...)
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input=context_json.encode("utf-8")),
            timeout=config.timeout,  # 唯一终止路径：超时
        )
    except asyncio.TimeoutError:
        process.kill()  # 超时才 kill
```

**修复建议**：`run_hook` 增加 `abort_signal: asyncio.Event | None = None` 参数，在 `process.communicate()` 期间用 `asyncio.wait(communicate_task, abort_signal.wait())` 监听 abort，触发时 `process.kill()`。

### 3.3 流式输出完全缺失（缺口 P2）

**严重度**：P2（长时 hook 无进度反馈）

**Cline 实现**（`HookProcess.ts` L89-300）：

`HookProcess extends EventEmitter`，子进程 stdout/stderr 的 `data` 事件按行切割后 `emit("line", line, stream)`，UI 通过 `on("line", ...)` 实时显示。

```typescript
// HookProcess.ts L199-218
this.childProcess.stdout?.on("data", (data) => {
    const output = data.toString()
    this.stdoutBuffer += output
    this.handleOutput(output, didEmitEmptyLine, "stdout")
    if (!didEmitEmptyLine && output) {
        this.emit("line", "", "stdout")  // "start of output" 标记
        didEmitEmptyLine = true
    }
})
```

`hook-factory.ts` L329-336 把 `streamCallback` 注入 `HookProcess.on("line", ...)`，UI 实时接收。

**Charles 实现**（`runner.py` L113-130）：

Charles 用 `asyncio.create_subprocess_exec` + `process.communicate()`，**仅在子进程退出后**一次性获取 stdout_bytes/stderr_bytes：

```python
# runner.py L127-130
stdout_bytes, stderr_bytes = await asyncio.wait_for(
    process.communicate(input=context_json.encode("utf-8")),
    timeout=config.timeout,
)
# ↑ 无实时输出
```

**修复建议**：用 `process.stdout.readline()` 异步逐行读取，通过 callback 或 `asyncio.Queue` 推送到 UI。

### 3.4 JSON 提取鲁棒性差距（缺口 P2）

**严重度**：P2（hook 输出 debug 日志时 JSON 解析失败，退化为按退出码处理）

**Cline 实现**（`hook-factory.ts` L349-450）：

两阶段提取：
1. 直接 `JSON.parse(stdout)`
2. 失败后从末尾扫描大括号边界，提取最后一个完整 JSON 对象

```typescript
// hook-factory.ts L378-408
const lines = stdout.split("\n")
let jsonCandidate = ""
let braceCount = 0
let startCollecting = false
for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trimEnd()
    for (let j = line.length - 1; j >= 0; j--) {
        if (line[j] === "}") {
            braceCount++
            if (!startCollecting) startCollecting = true
        } else if (line[j] === "{") {
            braceCount--
        }
    }
    if (startCollecting) {
        jsonCandidate = line + "\n" + jsonCandidate
    }
    if (startCollecting && braceCount === 0) break
}
```

**Charles 实现**（`runner.py` L269-289）：

单阶段 `json.loads`，失败返回 None：

```python
def _parse_stdout_json(stdout_text: str) -> dict[str, Any] | None:
    if not stdout_text:
        return None
    try:
        parsed = json.loads(stdout_text)
    except (json.JSONDecodeError, ValueError):
        return None  # ← 任意 debug 输出都会到这
    if not isinstance(parsed, dict):
        return None
    return parsed
```

**影响**：hook 脚本若 `print("starting...")` 后再 `print(json.dumps({"cancel": True}))`，Charles 会因 `json.loads("starting...\n{...}")` 失败而退化为按退出码处理（exit 0 → continue，丢失 cancel 信号）。

**修复建议**：移植 Cline 的两阶段提取逻辑到 `_parse_stdout_json`。

### 3.5 hook 类型覆盖差距（Notification + PreCompact 缺失）

**严重度**：P3（Charles 量化场景下影响有限）

**Cline 实现**（`hook-factory.ts` L102-130）：

```typescript
export interface Hooks {
    PreToolUse: { preToolUse: PreToolUseData }
    PostToolUse: { postToolUse: PostToolUseData }
    UserPromptSubmit: { userPromptSubmit: UserPromptSubmitData }
    TaskStart: { taskStart: TaskStartData }
    TaskResume: { taskResume: TaskResumeData }
    TaskCancel: { taskCancel: TaskCancelData }
    TaskComplete: { taskComplete: TaskCompleteData }
    Notification: { notification: NotificationData }       // ← Charles 缺失
    PreCompact: { preCompact: PreCompactData }             // ← Charles 缺失
}
```

**Charles 实现**（`types.py` L56-75）：

```python
class FileHookType(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    TASK_START = "TaskStart"
    TASK_COMPLETE = "TaskComplete"
    TASK_RESUME = "TaskResume"
    TASK_CANCEL = "TaskCancel"
    # ← 无 Notification
    # ← 无 PreCompact
```

**影响**：
- `Notification` hook：Cline 用于通知类事件（如用户空闲提醒、权限请求），Charles 无对应场景可忽略。
- `PreCompact` hook：Cline 在上下文压缩前触发，可用于日志记录、状态保存。Charles 的 `agent/context.py` `ContextCompactor` 无 hook 触发点。

**修复建议**：PreCompact 可在 `ContextCompactor.compact()` 入口添加 `FileHookType.PRE_COMPACT` 触发；Notification 可暂不实现（Charles 无通知系统）。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

- `agent/file_hooks/types.py`
- `agent/file_hooks/registry.py`
- `agent/file_hooks/runner.py`
- `agent/file_hooks/loader.py`
- `agent/file_hooks/integration.py`
- `agent_config/hooks/templates/*.py`
- `agent_config/hooks/PreToolUse/*.py`
- `agent_config/hooks/PostToolUse/*.py`
- `agent/runtime.py`（file_hooks 加载入口 L273-358）
- `agent/types.py`（配置字段 L548-551）
- `agent/hooks.py`（Python 内建 hook 系统）
- `tests/test_stage12_tools_hooks.py`

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 说明 |
|------|---------|-------------|------|
| `agent/file_hooks/types.py` | 0 | 0 | docstring 全部为 "对标 Cline ..."，无 nanobot |
| `agent/file_hooks/registry.py` | 0 | 0 | docstring "对标 Cline HookProcessRegistry"，无 nanobot |
| `agent/file_hooks/runner.py` | 0 | 0 | docstring "对标 Cline HookProcess"，无 nanobot |
| `agent/file_hooks/loader.py` | 0 | 0 | docstring "对标 Cline hook-factory + templates"，无 nanobot |
| `agent/file_hooks/integration.py` | 0 | 0 | docstring "对标 Cline HookProcess 注入到 AgentRuntimeHooks"，无 nanobot |
| `agent_config/hooks/templates/*.py` | 0 | 0 | 4 个模板文件无 nanobot |
| `agent/runtime.py` | 0 | 0 | file_hooks 加载入口无 nanobot |
| `agent/types.py` | 0 | 0 | 配置字段无 nanobot |
| `agent/hooks.py` | 0 | 0 | Python 内建 hook 系统无 nanobot |
| `tests/test_stage12_tools_hooks.py` | 0 | 0 | 测试文件无 nanobot |

**总计**：P7.7 范围内 **0 处注释残留、0 处实现逻辑残留**。所有 file_hooks 相关文件均无 "nanobot" 字样，docstring 均正确标注 "对标 Cline ..."。

### 4.3 历史渊源说明

Charles 的 file_hooks 系统是 **Phase 28.3 + Stage 12.4 + Stage 5.3/5.4 + Phase 31.6** 多阶段新建的系统，**直接对标 Cline hooks 实现**，并非从 nanobot 迁移而来。`third_party/charles_bundle/nanobot-main/` 目录仅保留 LICENSE 文件，无源码，与 file_hooks 无关联。

---

## 五、修复建议优先级

### P1 — 必须修复

1. **接入 HookProcessRegistry 到 runtime abort 流程**：
   - `integration.py` `_run_hooks_of_type` 接受 `registry` 参数，传给 `run_hook`
   - `build_file_hooks_agent_hooks` 调用 `get_global_registry()` 获取单例
   - `runtime.py` `abort()` 方法在 `_abort_controller.abort()` 后调用 `await get_global_registry().kill_all()`

### P2 — 建议修复

2. **`run_hook` 增加 abort_signal 参数**：支持单 hook 中止，避免 abort 后等超时
3. **移植 JSON 两阶段提取逻辑**：处理 hook 输出 debug 日志 + JSON 混合场景
4. **增加输出大小限制**：`MAX_HOOK_OUTPUT_SIZE = 1MB` + `MAX_CONTEXT_MODIFICATION_SIZE = 50KB` 截断
5. **增加流式输出支持**：用 `process.stdout.readline()` 异步逐行读取

### P3 — 可选增强

6. **补全 Notification + PreCompact hook 类型**：PreCompact 在 ContextCompactor 入口触发
7. **补全 5 个生命周期 hook 模板**：TaskStart / TaskResume / TaskCancel / TaskComplete / UserPromptSubmit
8. **增加 HookError 错误分类**：4 类枚举（TIMEOUT/VALIDATION/EXECUTION/CANCELLATION）
9. **增加 HookDiscoveryCache**：避免重复扫描目录
10. **增加 hook telemetry**：上报 started/completed/cancelled/failed 5 时机

---

## 六、附录

### 6.1 文件清单

| 角色 | Cline 文件 | 行数 | Charles 文件 | 行数 |
|------|-----------|------|-------------|------|
| 类型定义 | `apps/vscode/src/core/hooks/hook-factory.ts`（Hooks interface） | L102-130 | `agent/file_hooks/types.py` | L1-230 |
| 进程执行 | `apps/vscode/src/core/hooks/HookProcess.ts` | L1-300+ | `agent/file_hooks/runner.py` | L1-289 |
| 进程注册表 | `apps/vscode/src/core/hooks/HookProcessRegistry.ts` | L1-64 | `agent/file_hooks/registry.py` | L1-148 |
| 错误类型 | `apps/vscode/src/core/hooks/HookError.ts` | L1-123 | `agent/file_hooks/types.py`（HookError 类） | L200-223 |
| shell 转义 | `apps/vscode/src/core/hooks/shell-escape.ts` | L1-67 | 无（架构差异） | - |
| 工厂入口 | `apps/vscode/src/core/hooks/hook-factory.ts`（HookFactory 类） | L720-820+ | `agent/file_hooks/integration.py`（build_file_hooks_agent_hooks） | L466-547 |
| 脚本加载 | `apps/vscode/src/core/hooks/HookDiscoveryCache.ts` | - | `agent/file_hooks/loader.py` | L1-205 |
| 模板 | `apps/vscode/src/core/hooks/templates.ts` | L1-100+ | `agent_config/hooks/templates/*.py`（4 文件） | - |
| 工具函数 | `apps/vscode/src/core/hooks/hooks-utils.ts` | L1-8 | 无 | - |
| runtime 接入 | （由 ToolExecutor 调用 HookFactory.create） | - | `agent/runtime.py` L273-358 | L273-358 |
| 配置字段 | （VS Code settings） | - | `agent/types.py` L548-551 | L548-551 |
| 文档 | `.clinerules/hooks/README.md` | L1-80 | （无独立文档） | - |

### 6.2 常量对比

| 常量 | Cline 值 | Charles 值 | 一致性 |
|------|---------|-----------|--------|
| hook 超时 | `HOOK_EXECUTION_TIMEOUT_MS = 30000` | `DEFAULT_HOOK_TIMEOUT = 30` | 高（30s 一致） |
| context 截断 | `MAX_CONTEXT_MODIFICATION_SIZE = 50000` | 无 | 缺失 |
| 输出大小限制 | `MAX_HOOK_OUTPUT_SIZE = 1MB` | 无 | 缺失 |
| SIGINT 退出码 | `EXIT_CODE_SIGINT = 130` | 无 | 缺失 |
| Windows PowerShell 缓存 | `WINDOWS_HOOK_LAUNCHER_CACHE_TTL_MS = 5min` | 不需要（用 sys.executable） | 架构差异 |
| 并发上限 | 无 | `_MAX_PARALLEL_HOOKS = 10` | Charles 增强 |
| 默认 blocking | fail-open（始终） | `blocking: bool = False`（默认 fail-open） | 高 |
| 支持的脚本扩展名 | 无扩展名 + shebang | `.py` / `.sh` / `.js` / `.bat` | 架构差异 |

### 6.3 hook 类型对比

| hook 类型 | Cline | Charles | 一致性 |
|----------|-------|---------|--------|
| PreToolUse | `Hooks.PreToolUse` | `FileHookType.PRE_TOOL_USE` | 高 |
| PostToolUse | `Hooks.PostToolUse` | `FileHookType.POST_TOOL_USE` | 高 |
| UserPromptSubmit | `Hooks.UserPromptSubmit` | `FileHookType.USER_PROMPT_SUBMIT` | 高 |
| TaskStart | `Hooks.TaskStart` | `FileHookType.TASK_START` | 高 |
| TaskResume | `Hooks.TaskResume` | `FileHookType.TASK_RESUME` | 高（Phase 31.6） |
| TaskCancel | `Hooks.TaskCancel` | `FileHookType.TASK_CANCEL` | 高（Phase 31.6） |
| TaskComplete | `Hooks.TaskComplete` | `FileHookType.TASK_COMPLETE` | 高 |
| Notification | `Hooks.Notification` | **缺失** | 缺失 |
| PreCompact | `Hooks.PreCompact` | **缺失** | 缺失 |
