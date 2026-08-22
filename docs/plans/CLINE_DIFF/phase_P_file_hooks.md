# Phase P: 文件 Hooks 系统 对比报告

> 对标源码：
> - `apps/vscode/src/core/hooks/HookProcess.ts`
> - `apps/vscode/src/core/hooks/hook-factory.ts`
> - `apps/vscode/src/core/hooks/templates.ts`
> - `apps/vscode/src/core/hooks/shell-escape.ts`
> - `apps/vscode/src/core/hooks/HookError.ts`
> - `apps/vscode/src/core/hooks/HookProcessRegistry.ts`
> - `apps/vscode/src/core/hooks/HookDiscoveryCache.ts`
> - `sdk/packages/core/src/hooks/hook-file-config.ts`
> - `sdk/packages/core/src/hooks/hook-file-hooks.ts`
> - `sdk/packages/core/src/hooks/subprocess.ts`
>
> 当前实现：`agent/file_hooks/types.py` + `agent/file_hooks/loader.py` + `agent/file_hooks/runner.py` + `agent/file_hooks/integration.py`
>
> 对比维度：P1-P18

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 2 项 |
| 弱对齐 | 9 项 |
| 缺失 | 3 项 |
| 额外增强 | 3 项 |
| 等价（不同实现） | 1 项 |
| **对齐度** | **约 50%** |

> 说明：核心 7 种 hook 类型与 subprocess+stdin 的执行机制与 Cline 对齐，但存在多处语义不等价（退出码语义、blocking 默认值、并发模型、失败降级策略）。我额外引入 frontmatter/applyTo/blocking 配置能力，但 Cline 本身没有这些字段，属于设计方向分歧。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| P1 | 7 种 hook 类型 | hook-factory.ts L102-130（VSCode 9 种）/ hook-file-config.ts L17-28（SDK 10 种） | types.py L46-65 | 弱对齐 |
| P2 | frontmatter 字段 | 无（Cline 通过文件名识别类型，不解析 frontmatter） | loader.py L93-129 | 额外增强 |
| P3 | applyTo 匹配逻辑 | 无（所有工具都触发） | loader.py L163-187 + types.py L102-113 | 额外增强（非 glob） |
| P4 | blocking 语义 | 无 blocking 字段（默认 fail-open，仅 cancel:true 阻止） | runner.py L164 + types.py L99 | 弱对齐（语义不等价） |
| P5 | 脚本执行方式 | HookProcess.ts L176-182（spawn + stdin JSON） | runner.py L94-101（create_subprocess_exec + stdin JSON） | 弱对齐 |
| P6 | stdin JSON 上下文格式 | hook-factory.ts L198-218（clineVersion/hookName/timestamp/workspaceRoots/userId/model + 嵌套 hook 字段） | types.py L117-166（hook_type/session_id/run_id/iteration + 扁平字段） | 弱对齐 |
| P7 | stdout 解析 | hook-factory.ts L349-450（JSON.parse + 末尾扫描提取 + validateHookOutput） | runner.py L133-140（json.loads，失败忽略） | 弱对齐 |
| P8 | 退出码语义 | hook-factory.ts L452-529（退出码不决定 block，仅 JSON cancel:true 决定） | runner.py L130-169（0=continue/1=block/其他=error） | 弱对齐（语义不等价） |
| P9 | context-injection 语义 | hook-factory.ts L363-371（contextModification 50KB 截断 + 多 hook \n\n 合并） | runner.py L137 + integration.py L284-285（context_injection，仅 UserPromptSubmit 注入） | 弱对齐 |
| P10 | hook 超时 | HookProcess.ts L187-196（HOOK_EXECUTION_TIMEOUT_MS=30000，SDK tool_call 120000ms） | types.py L189 + runner.py L104-107（DEFAULT_HOOK_TIMEOUT=30，per-hook 可配） | 完全一致（+增强） |
| P11 | HookError 异常 | HookError.ts（4 种错误类型 + 结构化 info） | 无独立异常类，runner.py 返回 FileHookResult(action="error") | 缺失 |
| P12 | HookProcessRegistry | HookProcessRegistry.ts（单例 Set + terminateAll） | 无进程注册表 | 缺失 |
| P13 | shell-escape | shell-escape.ts（Windows 双引号 / Unix 单引号转义） | 无（create_subprocess_exec 不经 shell，无需转义） | 等价（不同实现） |
| P14 | hook 模板 | templates.ts（Bash/PowerShell 模板，9 种类型） | 无 | 缺失 |
| P15 | hook 发现缓存 | HookDiscoveryCache.ts（单例 + per-hookName 缓存 + 文件 watcher 失效） | loader.py L57-90（每次全量扫描，无缓存） | 弱对齐 |
| P16 | hook 并发执行 | hook-factory.ts L651-684（CombinedHookRunner Promise.all 并行 + 结果合并） | integration.py L111-165（for 循环 await 串行 + 遇 block 即止） | 弱对齐（语义不等价） |
| P17 | hook 与 Python hook 集成 | hook-file-hooks.ts createHookConfigFileHooks（包装为 AgentHooks） | integration.py build_file_hooks_agent_hooks（包装为 AgentHooks） | 完全一致 |
| P18 | hook 失败降级 | hook-factory.ts 注释 fail-open + SDK onDispatchError（脚本错误不阻止） | integration.py L153-161 + runner.py L164（blocking=true 时 error→block） | 弱对齐（语义不等价） |

---

## 3. 关键差距详细分析

### 差距 #P1：7 种 hook 类型覆盖不全

**严重度**：P3

**Cline 实现**：
- VSCode 端 `hook-factory.ts` L102-130 定义 `Hooks` 接口，包含 9 种：PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskResume/TaskCancel/TaskComplete/Notification/PreCompact
- SDK 端 `hook-file-config.ts` L17-28 定义 `HookConfigFileName` 枚举，包含 10 种：上述 + TaskError + SessionShutdown（无 Notification）

**我的实现**：`types.py` L46-65 定义 `FileHookType` 枚举，包含 7 种：PRE_TOOL_USE/POST_TOOL_USE/USER_PROMPT_SUBMIT/TASK_START/TASK_COMPLETE/TASK_RESUME/TASK_CANCEL

**影响**：
- 缺少 Notification（用户注意力边界通知，观察性质）
- 缺少 PreCompact（上下文压缩前触发）
- 缺少 TaskError（任务异常退出时触发）
- 缺少 SessionShutdown（会话关闭时触发）
- 核心工具/任务生命周期类型已覆盖，主流程不受影响

**修复建议**：可选扩展 `FileHookType` 增加 PRE_COMPACT/TASK_ERROR/SESSION_SHUTDOWN。Notification 因观察性质且 Cline caller 忽略 cancel，可不实现。

**优先级**：P3

---

### 差距 #P4：blocking 语义与 Cline fail-open 模型冲突

**严重度**：P1（语义不等价，影响主流程是否继续）

**Cline 实现**：
- 无 `blocking` 字段，采用 fail-open 语义（`hook-factory.ts` L268-272 注释）
- 脚本执行错误（非零退出）抛 `HookExecutionError`，但 caller 通常 catch 后继续
- 只有 hook 显式返回 JSON `{cancel: true}` 才阻止主流程
- SDK 端 `subprocess.ts` L425-428 `beforeTool` 失败时返回 undefined（继续执行工具）

**我的实现**：
- `types.py` L99 `blocking: bool = True`（默认阻塞）
- `runner.py` L164 `action = "block" if config.blocking else "error"`（错误时若 blocking=true 则 block）
- `integration.py` L153-161 `if config.blocking: return "block", result.reason`

**影响**：
- 默认行为相反：Cline 脚本崩溃时工具仍执行，我的脚本崩溃时工具被阻止
- 量化场景下脚本崩溃可能掩盖真实问题，fail-closed 更安全；但与 Cline 行为不一致
- 用户若同时使用 Cline 和本系统，行为预期会不一致

**修复建议**：
- 短期：将 `blocking` 默认值改为 `False`，与 Cline fail-open 对齐
- 长期：保留 `blocking` 字段作为额外增强，但默认值与 Cline 一致

**优先级**：P1

---

### 差距 #P6：stdin JSON 上下文字段不齐全

**严重度**：P2

**Cline 实现**：
- VSCode 端 `hook-factory.ts` L198-218 `completeParams` 注入公共字段：`clineVersion`/`hookName`/`timestamp`/`workspaceRoots`/`userId`/`model`
- hook 特定字段使用嵌套结构：`{preToolUse: {toolName, parameters}}` / `{postToolUse: {toolName, parameters, result, success, executionTimeMs}}` / `{userPromptSubmit: {prompt, attachments}}` / `{taskResume: {taskMetadata, previousState}}` 等
- SDK 端 `subprocess.ts` L214-243 还包含 `agent_id`/`parent_agent_id`/`sessionContext`/`workspaceInfo`

**我的实现**：`types.py` L117-166 `FileHookContext.to_dict()` 输出扁平结构：`hook_type`/`session_id`/`run_id`/`iteration`/`tool_name`/`tool_call_id`/`input`/`result`/`is_error`/`duration_ms`/`user_input`/`previous_state`/`completion_status`

**影响**：
- 缺少 `clineVersion`/`userId`/`workspaceRoots`/`model`/`agent_id`/`parent_agent_id` 等元数据
- 字段命名风格不同（我 snake_case，Cline camelCase + 嵌套）
- 跨系统 hook 脚本无法互通（Cline 脚本在本系统会因字段缺失失败）
- 我的字段更扁平直接，对 Python 脚本友好

**修复建议**：
- 短期：补充 `cline_version`/`user_id`/`workspace_roots`/`agent_id` 字段
- 中期：将 hook 特定字段包装为嵌套结构（`pre_tool_use: {tool_name, parameters}`），与 Cline 对齐
- 长期：提供 Cline 兼容模式，支持运行 Cline 格式的 hook 脚本

**优先级**：P2

---

### 差距 #P8：退出码语义不等价（重大语义差异）

**严重度**：P1（语义不等价，block 触发条件完全不同）

**Cline 实现**：
- `hook-factory.ts` L452-529：退出码不决定 continue/block
- exit code 0 + 有效 JSON → 按 JSON 的 `cancel` 字段决定
- exit code 0 + 无 JSON → continue（L524-526）
- exit code 非 0 + 有效 JSON → 仍按 JSON 决定（L454-499，"If we have valid JSON, honor it regardless of exit code"）
- exit code 非 0 + 无 JSON → throw HookExecutionError（caller 决定是否阻止）
- **block 只通过 JSON 的 `cancel: true` 实现，不用退出码 1**

**我的实现**：
- `runner.py` L130-169：退出码直接决定 action
- exit code 0 → continue（解析 context_injection）
- exit code 1 → block（stderr 作为 reason）
- 其他 → error（若 blocking=true 则 block）

**影响**：
- Cline hook 脚本（用 `exit 1` 表示阻止）在本系统会 block，但 Cline 自身 `exit 1` 不阻止
- 我的 hook 脚本（用 `exit 1` 表示阻止）在 Cline 不会阻止
- 跨系统迁移 hook 脚本时行为不一致
- 我的方式更符合 Unix 传统（退出码表示成功/失败），但与 Cline 协议不兼容

**修复建议**：
- 短期：在文档中明确标注此差异，提示用户迁移时需调整脚本
- 中期：增加兼容模式，支持解析 stdout JSON 的 `cancel` 字段作为 block 信号
- 长期：统一为 Cline 语义（JSON cancel 决定 block），退出码仅表示执行成功/失败

**优先级**：P1

---

### 差距 #P9：context-injection 注入点受限

**严重度**：P2

**Cline 实现**：
- `hook-factory.ts` L363-371：`contextModification` 字段，50KB 截断
- `CombinedHookRunner` L669-676：多 hook 的 contextModification 用 `\n\n` 连接
- caller（ToolExecutor）负责将 contextModification 注入到模型上下文
- 所有 hook 类型都支持 contextModification

**我的实现**：
- `runner.py` L137：解析 `context_injection` 字段（非 Cline 的 `contextModification`）
- `integration.py` L284-285：仅 `prepare_turn_input`（UserPromptSubmit）实际注入到 `modified_input`
- `integration.py` L204-205：`before_tool`（PreToolUse）的 context_injection 仅记录日志，未注入

**影响**：
- PreToolUse hook 无法实际注入上下文（功能缺失）
- 字段名与 Cline 不一致（`context_injection` vs `contextModification`）
- 无 50KB 截断保护，可能因超大注入导致 prompt overflow
- 多 hook 注入合并仅在 `_run_hooks_of_type` 内用 `\n\n` 连接（L164），与 Cline 一致

**修复建议**：
- 短期：实现 `before_tool` 的 context_injection 注入（通过 `BeforeToolResult.input` 或 metadata）
- 中期：增加 50KB 截断保护（参考 Cline `MAX_CONTEXT_MODIFICATION_SIZE`）
- 长期：字段名改为 `contextModification` 与 Cline 对齐

**优先级**：P2

---

### 差距 #P11：HookError 异常类缺失

**严重度**：P3

**Cline 实现**：`HookError.ts` 定义 `HookExecutionError` 类
- 4 种错误类型：TIMEOUT/VALIDATION/EXECUTION/CANCELLATION
- 结构化 `HookErrorInfo`：type/message/details/scriptPath/exitCode/stderr
- 静态工厂方法：`timeout()`/`validation()`/`execution()`/`cancellation()`
- `isHookError()` 类型守卫

**我的实现**：无独立异常类，`runner.py` 返回 `FileHookResult(action="error", reason=...)`

**影响**：
- 错误信息不结构化，caller 难以区分错误类型（超时 vs 执行失败 vs 取消）
- 无错误传播链，错误仅记录日志
- 实际功能等价（错误都能被处理），但可观测性差

**修复建议**：可选实现 `FileHookError` 异常类，包含 type/script_path/exit_code/stderr 字段。当前 `FileHookResult` 已携带足够信息，影响较小。

**优先级**：P3

---

### 差距 #P12：HookProcessRegistry 进程注册表缺失

**严重度**：P3

**Cline 实现**：`HookProcessRegistry.ts` 单例 `Set<HookProcess>`
- `register`/`unregister` 自动管理
- `terminateAll()` 扩展卸载时清理僵尸进程
- `getActiveCount()` 监控调试

**我的实现**：无进程注册表

**影响**：
- Agent 进程异常退出时，正在执行的 hook 子进程可能成为僵尸
- 无法全局取消所有正在执行的 hook
- `runner.py` 超时后会 `process.kill()`，但仅限单个 hook 范围

**修复建议**：
- 短期：在 `integration.py` 维护一个 `set[asyncio.subprocess.Process]` 注册表
- 中期：实现 `terminate_all_hooks()` 函数，agent abort 时调用
- 长期：与 `agent/abort.py` 集成，abort 信号触发时清理所有 hook 进程

**优先级**：P3

---

### 差距 #P14：hook 模板缺失

**严重度**：P3

**Cline 实现**：`templates.ts` 为 9 种 hook 类型提供 Bash/PowerShell 模板
- 每个模板含完整示例（读取 stdin JSON、解析字段、输出 JSON）
- Windows 用 PowerShell 模板，Unix 用 Bash 模板
- 用户可通过 `cline hook create` 命令生成

**我的实现**：无模板系统

**影响**：
- 用户编写 hook 脚本时无参考模板，门槛较高
- 无 CLI 命令生成脚手架
- 量化场景下 hook 数量少，影响有限

**修复建议**：可选实现 `agent/file_hooks/templates.py`，为 7 种类型提供 Python/Bash 模板。当前优先级低。

**优先级**：P3

---

### 差距 #P15：hook 发现缓存缺失

**严重度**：P2

**Cline 实现**：`HookDiscoveryCache.ts` 单例
- per-hookName 缓存扫描结果
- 文件 watcher 监听 hooks 目录变化自动失效
- 并发扫描去重（`scanningPromises` Map）
- 工作区变化时 `invalidateAll()`

**我的实现**：`loader.py` L57-90 `load_hooks_from_dir` 每次调用都全量扫描

**影响**：
- 实际影响小：`integration.py` `build_file_hooks_agent_hooks` 仅在 agent 初始化时调用一次，运行时不再扫描
- 但若 hooks 目录在运行时新增脚本，无法热加载
- Cline 的缓存+watcher 支持运行时新增 hook 立即生效

**修复建议**：
- 短期：保持现状（初始化一次扫描足够）
- 中期：若需热加载，可实现简单的 mtime 缓存（检查目录修改时间决定是否重扫）
- 长期：参考 Cline 实现 watcher，但 Python 跨平台 watcher 实现复杂（watchdog 库）

**优先级**：P2

---

### 差距 #P16：hook 并发执行模型不同

**严重度**：P2（语义不等价）

**Cline 实现**：`hook-factory.ts` L651-684 `CombinedHookRunner`
- `Promise.all` 并行执行所有同类型 hook
- 结果合并：任一 `cancel=true` 则最终 `cancel=true`
- contextModification 用 `\n\n` 连接
- errorMessage 用 `\n` 连接
- 所有 hook 都会执行完（即使某个 cancel）

**我的实现**：`integration.py` L111-165 `_run_hooks_of_type`
- `for` 循环 `await` 串行执行
- 遇到 `block` 立即返回，后续 hook 不执行
- context_injection 用 `\n\n` 连接（仅 continue 的）

**影响**：
- 串行执行慢于并行（多 hook 时延迟叠加）
- 遇 block 短路语义不同：Cline 仍执行所有 hook，我立即停止
- Cline 的 block 信号是 `cancel:true`（JSON），我的是 `exit code 1`
- 多 hook 场景下，我的 block 后续 hook 不执行，可能遗漏日志/审计

**修复建议**：
- 短期：保持串行（量化场景 hook 数量少，性能影响小）
- 中期：改为 `asyncio.gather` 并行执行，收集所有结果后合并
- 长期：统一合并语义（任一 block 则最终 block，但所有 hook 都执行）

**优先级**：P2

---

### 差距 #P18：hook 失败降级策略不等价

**严重度**：P1（语义不等价，影响主流程是否继续）

**Cline 实现**：
- `hook-factory.ts` L268-272 注释 "fail-open"：脚本错误不阻止工具执行
- SDK 端 `subprocess.ts` L425-428 `beforeTool` catch 错误后返回 undefined（继续执行工具）
- `hook-file-hooks.ts` L552-558 `runBlockingHookCommands` catch 错误后 `logHookError` 继续
- 只有显式 JSON `{cancel: true}` 才阻止

**我的实现**：
- `runner.py` L164 `action = "block" if config.blocking else "error"`
- `integration.py` L153-161 `if config.blocking: return "block", result.reason`
- `blocking` 默认 `True`，所以默认 fail-closed

**影响**：
- 与 #P4 同源问题：默认行为相反
- Cline 脚本崩溃时工具仍执行，我的脚本崩溃时工具被阻止
- 量化场景下 fail-closed 更安全（避免错误命令执行），但与 Cline 不一致

**修复建议**：与 #P4 统一处理：
- 短期：`blocking` 默认值改为 `False`，与 Cline fail-open 对齐
- 长期：保留 `blocking` 字段作为额外增强，但默认值与 Cline 一致

**优先级**：P1

---

## 4. 一致性统计

### 按一致性等级分布

| 等级 | 数量 | 占比 | 子项 |
|------|------|------|------|
| 完全一致 | 2 | 11% | P10, P17 |
| 弱对齐 | 9 | 50% | P1, P5, P6, P7, P8, P9, P15, P16, P18 |
| 缺失 | 3 | 17% | P11, P12, P14 |
| 额外增强 | 3 | 17% | P2, P3, P4 |
| 等价（不同实现） | 1 | 6% | P13 |

### 按严重度分布

| 严重度 | 数量 | 子项 |
|--------|------|------|
| P1（语义不等价，影响主流程） | 3 | P4, P8, P18 |
| P2（功能缺失或弱对齐） | 5 | P6, P9, P15, P16, P1 |
| P3（可选增强） | 4 | P11, P12, P14 |

### 语义不等价项汇总

| 子项 | Cline 语义 | 我的语义 |
|------|-----------|---------|
| P4 blocking | 无此字段，fail-open | 默认 blocking=true，fail-closed |
| P8 退出码 | 退出码不决定 block，仅 JSON cancel:true 决定 | exit code 1 = block |
| P16 并发 | Promise.all 并行，所有 hook 都执行 | for 循环串行，遇 block 短路 |
| P18 降级 | fail-open，脚本错误不阻止 | 默认 fail-closed，脚本错误阻止 |

---

## 5. 修复建议

### 短期（P1，必须修复）

1. **P4/P18 blocking 默认值**：将 `types.py` L99 `blocking: bool = True` 改为 `blocking: bool = False`，与 Cline fail-open 语义对齐。保留 `blocking` 字段作为额外增强，允许用户显式开启 fail-closed。

2. **P8 退出码语义**：在 `runner.py` 增加 stdout JSON 的 `cancel` 字段解析。当 stdout 有效 JSON 且含 `cancel: true` 时，无论退出码如何都视为 block。退出码 0 + 无 JSON → continue。保留 exit code 1 = block 作为兼容，但文档标注与 Cline 不一致。

### 中期（P2，建议修复）

3. **P6 stdin JSON 字段**：在 `FileHookContext` 补充 `cline_version`/`user_id`/`workspace_roots`/`agent_id` 字段。考虑将 hook 特定字段包装为嵌套结构（`pre_tool_use: {tool_name, parameters}`）。

4. **P9 context-injection 注入**：实现 `before_tool` 的 context_injection 实际注入（通过 `BeforeToolResult.input` 或 metadata）。增加 50KB 截断保护。字段名考虑改为 `contextModification`。

5. **P15 hook 发现缓存**：若需热加载，实现简单的 mtime 缓存。当前初始化一次扫描足够。

6. **P16 hook 并发执行**：将 `_run_hooks_of_type` 改为 `asyncio.gather` 并行执行，收集所有结果后合并。统一合并语义（任一 block 则最终 block，但所有 hook 都执行）。

### 长期（P3，可选增强）

7. **P1 hook 类型扩展**：增加 PRE_COMPACT/TASK_ERROR/SESSION_SHUTDOWN 类型。

8. **P11 HookError 异常类**：实现 `FileHookError` 异常类，结构化错误信息。

9. **P12 HookProcessRegistry**：维护进程注册表，agent abort 时清理所有 hook 进程。

10. **P14 hook 模板**：为 7 种类型提供 Python/Bash 模板。

---

## 6. 验证记录

### 6.1 文件读取验证

| 文件 | 路径 | 行数 | 状态 |
|------|------|------|------|
| Cline HookProcess.ts | `third_party/cline/apps/vscode/src/core/hooks/HookProcess.ts` | 456 | 已读 |
| Cline hook-factory.ts | `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts` | 1014 | 已读 |
| Cline templates.ts | `third_party/cline/apps/vscode/src/core/hooks/templates.ts` | 494 | 已读 |
| Cline shell-escape.ts | `third_party/cline/apps/vscode/src/core/hooks/shell-escape.ts` | 67 | 已读 |
| Cline HookError.ts | `third_party/cline/apps/vscode/src/core/hooks/HookError.ts` | 123 | 已读 |
| Cline HookProcessRegistry.ts | `third_party/cline/apps/vscode/src/core/hooks/HookProcessRegistry.ts` | 64 | 已读 |
| Cline HookDiscoveryCache.ts | `third_party/cline/apps/vscode/src/core/hooks/HookDiscoveryCache.ts` | 329 | 已读 |
| Cline hook-file-config.ts | `third_party/cline/sdk/packages/core/src/hooks/hook-file-config.ts` | 117 | 已读 |
| Cline hook-file-hooks.ts | `third_party/cline/sdk/packages/core/src/hooks/hook-file-hooks.ts` | 1143 | 已读 |
| Cline subprocess.ts | `third_party/cline/sdk/packages/core/src/hooks/subprocess.ts` | 543 | 已读 |
| 我的 types.py | `agent/file_hooks/types.py` | 192 | 已读 |
| 我的 loader.py | `agent/file_hooks/loader.py` | 204 | 已读 |
| 我的 runner.py | `agent/file_hooks/runner.py` | 207 | 已读 |
| 我的 integration.py | `agent/file_hooks/integration.py` | 480 | 已读 |

### 6.2 关键逻辑点验证

| 验证项 | Cline 位置 | 我的位置 | 结论 |
|--------|-----------|---------|------|
| hook 类型枚举 | hook-factory.ts L102-130 | types.py L46-65 | 7 种核心一致，Cline 多 3-4 种 |
| 超时常量 | hook-factory.ts L27 `HOOK_EXECUTION_TIMEOUT_MS=30000` | types.py L189 `DEFAULT_HOOK_TIMEOUT=30` | 默认值一致（30s） |
| subprocess spawn | HookProcess.ts L176 `spawn` | runner.py L94 `create_subprocess_exec` | 机制一致 |
| stdin JSON 写入 | HookProcess.ts L268 `stdin.write(inputJson)` | runner.py L105 `communicate(input=context_json.encode)` | 机制一致 |
| 超时处理 | HookProcess.ts L187-196 `setTimeout` + `kill SIGTERM` | runner.py L104-114 `asyncio.wait_for` + `process.kill` | 机制一致 |
| CombinedHookRunner | hook-factory.ts L651-684 `Promise.all` | integration.py L132 `for` 循环 | 串行 vs 并行 |
| AgentHooks 包装 | hook-file-hooks.ts L790 `createHookConfigFileHooks` | integration.py L394 `build_file_hooks_agent_hooks` | 架构一致 |
| fail-open 注释 | hook-factory.ts L268-272 | 无（默认 fail-closed） | 语义不等价 |

### 6.3 额外增强项验证

| 增强项 | 我的位置 | Cline 是否有 | 评估 |
|--------|---------|-------------|------|
| frontmatter 解析 | loader.py L132-160 `_parse_frontmatter` | 无 | 合理增强，用户可在脚本内声明配置 |
| applyTo 字段 | loader.py L163-187 + types.py L102-113 | 无 | 合理增强，但应支持 glob 而非精确匹配 |
| blocking 字段 | types.py L99 + runner.py L164 | 无 | 合理增强，但默认值应与 Cline fail-open 对齐 |
| per-hook timeout | types.py L100 + loader.py L121 | 无（Cline 全局 30s） | 合理增强 |
| 多解释器支持 | runner.py L44-49（.py/.sh/.js/.bat） | Cline 仅 shebang + 扩展名 | 合理增强，Windows 友好 |
| UTF-8 强制 | runner.py L88-89 `PYTHONIOENCODING=utf-8` | 无 | 合理增强，避免 Windows 中文乱码 |

---

**阶段 P 结论**：文件 Hooks 系统对齐度约 50%。核心 7 种 hook 类型、subprocess+stdin 执行机制、30s 超时、AgentHooks 包装架构与 Cline 完全一致。主要语义差异集中在 3 处：(1) `blocking` 默认 fail-closed vs Cline fail-open；(2) 退出码 1=block vs Cline 仅 JSON cancel:true=block；(3) 串行执行遇 block 短路 vs Cline 并行执行所有 hook。我额外增强 frontmatter/applyTo/blocking/per-hook-timeout/多解释器/UTF-8，配置能力更强但与 Cline 协议不互通。建议短期将 `blocking` 默认值改为 `False`，中期实现 `cancel` 字段解析与 Cline 语义对齐。
