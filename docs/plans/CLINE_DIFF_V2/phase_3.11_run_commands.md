# Phase 3.11 run_commands 工具实现细节对比

> 对比范围：Cline `RunCommandsInputSchema` + `createShellTool` + `executeShellCommands` + `createShellExecutor`（bash.ts）+ `output-limits.ts` 与 Charles `RunCommandsTool` + `constants.py` 的命令批量执行工具实现差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/schemas.ts` L125-170（`CommandInputSchema` / `StructuredCommandInputSchema` / `RunCommandsInputSchema` / `RunCommandsInputUnionSchema`）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L179-233（`executeShellCommands` 批量执行器）L397-437（`RUN_COMMANDS_SHARED_INSTRUCTIONS` + `buildRunCommandsDescription`）L454-507（`createShellTool` 工厂）
> - `sdk/packages/core/src/extensions/tools/helpers.ts` L137-165（`normalizeRunCommandsInput` 输入归一化）L185-207（`formatRunCommandQueryPreview` 命令回显截断）
> - `sdk/packages/core/src/extensions/tools/executors/bash.ts`（`createShellExecutor` + `spawnAndCollect` + `createRollingCollector` + `killProcessTree`）
> - `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` L17-38（`MAX_COMMAND_OUTPUT_CHARS = 48_000` + `truncateCommandOutput` 首尾截断）
> - `sdk/packages/shared/src/parse/shell.ts` L11-67（`getDefaultShell` + `getShellKind` + `getShellArgs` 平台 shell 分发）
>
> Charles 源码：
> - `agent/tools/run_commands.py`（`RunCommandsTool` + `_execute` / `_execute_single` / `_graceful_kill` / `_truncate_output` / `_wait_process_with_abort` / `_wait_process_with_abort_stream` / `_guard_command`）
> - `agent/tools/constants.py` L23-47（`MAX_OUTPUT_PER_COMMAND = 8000` / `MAX_STDERR_PER_COMMAND = 2000` / `MAX_COMMANDS = 10` / `DEFAULT_COMMAND_TIMEOUT_SECONDS = 60` / `MAX_COMMAND_TIMEOUT_SECONDS = 600`）
> - `agent/abort.py`（`AbortController` + `AbortedError`）
> - `agent/types.py` L188-208（`AgentToolContext.abort_signal` + `emit_update`）

---

## 一、执行摘要

Cline 与 Charles 在 `run_commands` 工具上采用了**结构相似但执行模型差异显著**的实现：

1. **输入 schema 高度对齐**：两侧都用 `commands: string[]` 数组接收命令。Cline 通过 `RunCommandsInputUnionSchema` 联合类型支持 9 种输入形态（string / array / object / StructuredCommandInput 等），Charles 只支持单一 object+array 形态。Charles 在 schema 中硬编码 `maxItems: 10`，Cline 不在 schema 层限长（在描述中提示）。

2. **批量执行模型根本不同**：
   - **Cline 用 `Promise.all` 并行执行**（`definitions.ts` L191）：所有命令同时启动，互不阻塞，单条失败不影响其他命令的执行结果。
   - **Charles 用 `for` 循环串行执行**（`run_commands.py` L146）：命令按顺序执行，前一条完成后才启动下一条；单条失败不阻塞后续（`continue`），但**等待时长 = 所有命令耗时之和**。
   - 这是**最显著的实现差异**，对 LLM 调用体验有直接影响（并行 vs 串行的总耗时差异可达 N 倍）。

3. **子进程创建方式不同**：
   - Cline `child_process.spawn(executable, args, ...)`：通过 shell 二次启动（`bash -c` / `powershell -NoProfile -NonInteractive -Command` / `cmd /d /s /c` / `wsl bash -c`），命令作为 shell 的 `-c` / `-Command` 参数传入，**不经过系统 shell 解析二次转义**。
   - Charles `asyncio.create_subprocess_shell(command, ...)`：直接交给系统 `/bin/sh`（POSIX）或 `cmd.exe`（Windows）解析，依赖 shell 自身的引号处理。
   - **计划文档 P3.11 描述为 "asyncio.create_subprocess_exec" 与实际不符**，实际是 `_shell` 变体。

4. **stdout / stderr 处理策略相反**：
   - Cline 默认 `combineOutput=true`：把 stderr 拼到 stdout 末尾（`\n[stderr]\n` 分隔），返回**单字符串**；若 `combineOutput=false` 则**完全丢弃 stderr**。
   - Charles **始终保持分离**：result 中 `stdout` 和 `stderr` 是两个独立字段，LLM 同时拿到两路输出。
   - **计划文档 P3.11 描述 "Charles 合并" 与实际相反**，Charles 实际比 Cline 默认行为更分离。

5. **输出截断阈值差异较大**：
   - Cline `MAX_COMMAND_OUTPUT_CHARS = 48000`（单字符上限，stdout+stderr 合并后截断）。
   - Charles `MAX_OUTPUT_PER_COMMAND = 8000`（stdout 上限）+ `MAX_STDERR_PER_COMMAND = 2000`（stderr 上限），**两侧分别截断**，单条命令总上限 10000 字符。
   - 截断策略两侧**都是首尾各半**（head + tail），中间用 `[... omitted ...]` 标记连接。Charles 还额外在 result 中返回 `truncated: bool` 布尔标记。

6. **超时行为差异**：
   - Cline：超时 `killProcessTree`（SIGKILL）+ `reject(TimeoutError)`，**抛错路径**；executeShellCommands 捕获后转为 `success: false` 结果。默认 `bashTimeoutMs=30000`（30s），tool 层 `timeoutMs = bashTimeoutMs * 2`（60s）。
   - Charles：超时 `_graceful_kill`（SIGTERM 等 1s → SIGKILL）+ 设置 `timed_out=True` 标记 + 返回部分输出，**正常返回路径**。默认 `_MAX_TIMEOUT = 600s`（10 分钟）。
   - **Charles 默认超时是 Cline 的 20 倍**，且不抛错只标记，行为更"宽容"。

7. **优雅 kill 策略 Charles 更优**：
   - Cline `killProcessTree` 直接用 `process.kill(-childPid, "SIGKILL")`（POSIX）或 `taskkill /T /F`（Windows），**只强制 kill，无 SIGTERM 优雅阶段**。
   - Charles `_graceful_kill` 先 `SIGTERM`（Windows 上 `terminate()`）等 1 秒，再 `SIGKILL`，给子进程 flush 缓冲、关闭连接的机会。
   - **计划文档 P3.11 描述 "Cline SIGTERM → SIGKILL" 与实际不符**，Cline 实际只 SIGKILL；Charles 才是两阶段。

8. **abort_signal kill 子进程语义对齐**：
   - Cline：`context.signal.addEventListener("abort", abortHandler)` → `killProcessTree` → reject Error("Command was aborted")。
   - Charles：`asyncio.wait({wait_task, abort_task}, FIRST_COMPLETED)` → `_graceful_kill` → 抛 `AbortedError("aborted by user")`。
   - **语义等价**，但 Charles 用 `asyncio.wait` 轮询模式，Cline 用事件监听器模式。

9. **Charles 额外能力**（Cline 无对应）：
   - **危险命令拦截**：`_DENY_PATTERNS` 9 条正则（`rm -rf /` / `mkfs` / `dd if=of=/dev/` / `shutdown` / `reboot` / `format x:` 等），命中即拒绝执行。
   - **实时终端输出推送**：`emit_update` 回调把 stdout/stderr 按行推送到前端 `terminal_output` 面板，支持长耗时命令的进度监控。
   - **PYTHONUNBUFFERED=1**：项目约束，强制 Python 子进程实时刷新输出。
   - **超时标记字段**：`timed_out: bool` + 输出末尾追加 `[timeout after Ns]`。
   - **截断标记字段**：`truncated: bool`。

10. **Cline 额外能力**（Charles 无对应）：
    - **StructuredCommandInput**：`{command: "node", args: ["script.js", "--flag"]}` 结构化输入，args 直接传给 exec 不经 shell 解析，避免注入风险。
    - **多形态输入联合 schema**：9 种输入形态（string / array / object / StructuredCommand / cmd 别名 等），LLM 可灵活调用。
    - **Heredoc 合并**：`coalesceAdjacentStringHeredocs` 把跨数组元素的 heredoc 合并为单条命令（如 `cat <<EOF` + body + `EOF`）。
    - **平台 shell 分发**：`getDefaultShell` + `getShellArgs` + `getShellKind` 自动识别 powershell/cmd/wsl/posix 并使用对应调用参数。
    - **命令回显截断**：`RUN_COMMAND_QUERY_PREVIEW_LIMIT=200`，长命令在 result.query 中只保留前 200 字符 + 截断提示，避免 heredoc 类大命令在结果中重复消耗 token。
    - **遥测**：`captureRunCommandsTimeout` 上报超时事件。

11. **nanobot 残留**：P3.11 核心文件 `run_commands.py` 和 `constants.py` **均无 nanobot 残留**（0 处匹配）。`run_commands.py` 是 Charles 自研工具，明确标注"对标 Cline RunCommandsInputSchema + bash.ts"，未引用 nanobot。同目录的废弃文件 `exec_tool.py` 有 12 处 nanobot 残留（含注释 + 实现逻辑引用），但不在 P3.11 范围内。

12. **一致性总体评估**：**中**。核心功能（命令执行、超时、abort、输出截断、退出码）两侧都有对应实现且语义基本对齐，但**执行模型差异**（并行 vs 串行）和**默认值差异**（30s vs 600s、48000 vs 8000）影响实际行为，需在文档中明确记录。Charles 增强的危险命令拦截和实时终端推送是有益功能增强，应予保留。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.11.1 | 输入 schema | `RunCommandsInputSchema`：`commands: string[]`，无 maxItems 限制 | `commands: string[]`，`maxItems: 10`（`MAX_COMMANDS`） | 中 | Charles 在 schema 层硬限长，Cline 仅描述提示 |
| 3.11.2 | 输入形态灵活性 | `RunCommandsInputUnionSchema` 联合 9 种形态（string / array / object / StructuredCommand / cmd 别名 等） | 单一 object+array 形态 | 低 | **Charles 缺联合 schema**，LLM 调用形态受限 |
| 3.11.3 | StructuredCommandInput | 支持 `{command, args}` 结构化输入，args 直接传给 exec | 不支持，仅 string 命令 | 低 | **Charles 缺结构化输入**，所有命令都经 shell 解析 |
| 3.11.4 | 子进程创建 | `child_process.spawn(shell, shellArgs, ...)` | `asyncio.create_subprocess_shell(command, ...)` | 中 | Cline 通过 shell 二次启动，Charles 直交给系统 shell |
| 3.11.5 | 批量执行模型 | `Promise.all(commands.map(...))` **并行** | `for cmd in commands: await ...` **串行** | 低 | **根本差异**：并行 vs 串行，总耗时差异可达 N 倍 |
| 3.11.6 | cwd 参数 | `config.cwd ?? process.cwd()`，传给 spawn | `self._working_dir`（构造时 `os.getcwd()`），传给 subprocess | 高 | 已对齐 |
| 3.11.7 | env 参数 | `env: { ...process.env, ...config.env }` | `env = os.environ.copy(); env["PYTHONUNBUFFERED"] = "1"` | 高 | Charles 强制追加 PYTHONUNBUFFERED=1 |
| 3.11.8 | 单条命令 timeout | `bashTimeoutMs ?? 30000`（30s 默认），tool 层 ×2 = 60s | `_MAX_TIMEOUT = 600s`（硬编码使用 MAX 值，不读 DEFAULT） | 低 | **Charles 默认超时是 Cline 的 20 倍** |
| 3.11.9 | 独立 timeout | 每条命令 `withTimeout(executor(...), timeoutMs)` 独立超时 | 每条命令 `_wait_process_with_abort_stream(timeout=self._MAX_TIMEOUT)` 独立超时 | 高 | 两侧都支持 per-command 独立超时 |
| 3.11.10 | 独立 exit_code | `CommandExitError(exitCode, output)`，executeShellCommands 转为 `success: false` | `result["exit_code"] = process.returncode`，每条独立返回 | 高 | 已对齐 |
| 3.11.11 | abort_signal kill | `signal.addEventListener("abort", abortHandler)` → `killProcessTree` | `asyncio.wait({wait_task, abort_task})` → `_graceful_kill` | 高 | 语义等价（事件监听 vs 轮询等待） |
| 3.11.12 | abort 后行为 | `reject(Error("Command was aborted"))`，executeShellCommands 转为 `success: false` | 抛 `AbortedError("aborted by user")`，由 runtime 捕获 | 中 | Cline 转结果，Charles 抛异常中断整个工具调用 |
| 3.11.13 | 输出截断阈值 | `MAX_COMMAND_OUTPUT_CHARS = 48000`（合并后单上限） | `MAX_OUTPUT_PER_COMMAND = 8000` + `MAX_STDERR_PER_COMMAND = 2000`（分 stream 上限） | 低 | **阈值差 6 倍**（48000 vs 10000 总和） |
| 3.11.14 | 截断策略 | 首尾各半（`headLimit = ceil(maxChars/2)` + `tailLimit = maxChars - headLimit`） | 首尾各半（`half = limit // 2` + head + tail） | 高 | 策略相同 |
| 3.11.15 | 截断提示文本 | `[... output truncated: ${totalChars} chars total. Refine the command ...]` | `[... ${omitted} characters omitted ...]` | 中 | 文案不同（Cline 含总数+建议，Charles 只含省略数） |
| 3.11.16 | 截断标记字段 | 无独立字段，仅文本内嵌标记 | `truncated: bool` 独立字段 | 中 | Charles 多一个布尔字段 |
| 3.11.17 | stdout/stderr 分离 | `combineOutput=true` 默认合并为单字符串；`=false` 丢弃 stderr | **始终分离**，result.stdout 和 result.stderr 独立字段 | 中 | **Charles 比默认更分离**（计划文档描述有误） |
| 3.11.18 | 退出码非零行为 | 抛 `CommandExitError`，executeShellCommands 转为 `success: false` + result | result.exit_code = 非 0，正常返回 | 高 | 两侧都返回结果而非中断 |
| 3.11.19 | 超时行为 | `killProcessTree` SIGKILL + reject TimeoutError | `_graceful_kill` SIGTERM→SIGKILL + `timed_out=True` + 返回部分输出 | 中 | Cline 抛错，Charles 标记返回 |
| 3.11.20 | 优雅 kill | **无 SIGTERM 阶段**，直接 `process.kill(-pid, "SIGKILL")` 或 `taskkill /T /F` | `_graceful_kill`：SIGTERM 等 1s → SIGKILL | 中 | **Charles 更优雅**（计划文档描述有误） |
| 3.11.21 | 命令注入防护 | 描述提示"shell-escaped"；StructuredCommandInput 可绕过 shell | 无 shell-escape，仅 `_DENY_PATTERNS` 9 条正则黑名单 | 中 | 策略不同：Cline 依赖描述+结构化输入，Charles 用黑名单 |
| 3.11.22 | 危险命令拦截 | 无内建拦截 | `_DENY_PATTERNS`：`rm -rf /` / `mkfs` / `dd if=of=/dev/` / `shutdown` / `reboot` / `format x:` 等 9 条 | 低 | **Charles 多一层安全拦截**，Cline 无 |
| 3.11.23 | Heredoc 合并 | `coalesceAdjacentStringHeredocs` + `coalesceSplitHeredocCommands` 合并跨数组元素的 heredoc | 无 heredoc 处理 | 低 | **Charles 缺**，heredoc 跨数组会执行失败 |
| 3.11.24 | 平台 shell 分发 | `getDefaultShell`（win=powershell, posix=/bin/bash）+ `getShellArgs`（powershell/cmd/wsl/posix 各自参数） | `asyncio.create_subprocess_shell` 自带分发（POSIX 用 /bin/sh，Windows 用 cmd.exe） | 中 | Cline 显式控制 shell，Charles 依赖 asyncio 默认 |
| 3.11.25 | Windows 兼容 | `taskkill /pid <pid> /T /F` 杀进程树 + `windowsHide: true` 隐藏控制台窗口 | `process.terminate()`（Windows 上等价 TerminateProcess） | 中 | 两侧都支持 Windows，但 Charles 不杀子进程树 |
| 3.11.26 | 进程树 kill | `taskkill /T /F`（Windows）或 `process.kill(-pid, SIGKILL)`（POSIX，进程组） | 仅 `process.terminate()` / `process.kill()`，不杀子进程树 | 低 | **Charles 不杀进程树**，子进程可能残留 |
| 3.11.27 | 命令回显截断 | `formatRunCommandQueryPreview` 截断到 200 字符 + 提示 | 无截断，full command 原样回显 | 中 | Cline 节省 token，Charles 保留完整命令 |
| 3.11.28 | 实时终端输出 | 无 | `emit_update` 推送 `terminal_output` 事件到前端 | 低 | **Charles 独有**，支持长命令进度监控 |
| 3.11.29 | 遥测 | `captureRunCommandsTimeout` 上报超时事件 | 无遥测 | 中 | Cline 有遥测，Charles 无 |
| 3.11.30 | PYTHONUNBUFFERED | 无 | 强制 `env["PYTHONUNBUFFERED"] = "1"` | 中 | Charles 项目约束，确保 Python 子进程实时输出 |
| 3.11.31 | requires_approval | 由 `toolPolicies` 外部策略决定 | `BaseTool.requires_approval = True`（L113-115 自声明） | 中 | Charles 工具自声明需审批 |
| 3.11.32 | retryable | `retryable: false, maxRetries: 0`（L480-481） | `BaseTool.retryable = False, max_retries = 0`（默认） | 高 | 两侧都不重试 |
| 3.11.33 | 工具级 timeout | `timeoutMs: timeoutMs * 2`（60s 默认） | `timeout_ms = self._MAX_TIMEOUT * 1000`（600000ms = 600s） | 低 | 工具级 timeout 差 10 倍 |

**一致性总评**：33 项中，高一致性 9 项、中一致性 16 项、低一致性 8 项。低一致性项集中在：批量执行模型（3.11.5）、超时默认值（3.11.8 / 3.11.33）、输出截断阈值（3.11.13）、StructuredCommandInput 缺失（3.11.3 / 3.11.2）、进程树 kill 缺失（3.11.26）、heredoc 处理缺失（3.11.23）。

---

## 三、重点差距详细说明

### 差距 1：批量执行模型根本不同（3.11.5）

**Cline 实现**（`definitions.ts` L191-232）：

```typescript
async function executeShellCommands(commands, options): Promise<ToolOperationResult[]> {
    return Promise.all(
        commands.map(async (command): Promise<ToolOperationResult> => {
            // ... 每条命令独立执行
            const output = await withTimeout(executor(command, cwd, context), timeoutMs, ...);
            return { query, result: output, success: true };
        }),
    );
}
```

`Promise.all` **并行启动所有命令**，N 条命令的总耗时 ≈ max(单条最长耗时)，互不阻塞。单条失败不影响其他命令的 result 产出。

**Charles 实现**（`run_commands.py` L146-171）：

```python
for idx, cmd in enumerate(commands):
    self._check_aborted(context)
    guard_error = self._guard_command(cmd)
    if guard_error:
        results.append({...})
        continue
    result_item = await self._execute_single(cmd, env, idx, context)
    results.append(result_item)
```

`for` 循环 **串行执行**，前一条完成才启动下一条，N 条命令的总耗时 = sum(各条耗时)。单条失败用 `continue` 不阻塞后续，但**等待时长远大于 Cline**。

**影响**：
- 调用 `run_commands(commands=["ls", "git status", "pwd"])` 三条快速命令：
  - Cline：三条同时启动，总耗时 ≈ 100ms
  - Charles：串行执行，总耗时 ≈ 300ms
- 调用 `run_commands(commands=["npm test", "ls"])`：
  - Cline：`ls` 立即返回，`npm test` 超时时两条都中断
  - Charles：`ls` 必须等 `npm test` 完成才能执行
- Charles 的串行模型对**有依赖关系的命令**（如 `cd build && make`）更安全，但**对独立命令浪费等待时间**。

**建议**：不强制改为并行。Charles 的串行模型更符合"LLM 提交一批有序命令"的语义（避免命令间竞态），且与 `_check_aborted` 在命令边界检查中止信号的语义一致。若未来需要并行，可考虑增加 `parallel: bool` 参数。

### 差距 2：超时默认值差异 20 倍（3.11.8 / 3.11.33）

| 字段 | Cline 默认 | Charles 默认 | 倍数 |
|------|-----------|-------------|------|
| 单条命令 timeout | 30s（`bashTimeoutMs`） | 600s（`_MAX_TIMEOUT`） | 20× |
| 工具级 timeout | 60s（`bashTimeoutMs * 2`） | 600s（`_MAX_TIMEOUT * 1000ms`） | 10× |

**分析**：
- Cline 的 30s 偏向"短命令快速失败"（ls / git status / grep 类）。
- Charles 的 600s 偏向"长命令容忍"（read-pdf 下载、index 构建、Python 脚本执行等量化场景长任务）。
- Charles 在 `_execute_single` 中实际使用 `self._MAX_TIMEOUT`（600s），未使用 `_DEFAULT_TIMEOUT`（60s），这是**实现细节**：常量定义了 DEFAULT 但代码未引用。

**影响**：
- Cline 30s 超时对量化场景（Python 脚本执行）过短，可能误杀正常长任务。
- Charles 600s 超时对快速命令过长，但配合 `_graceful_kill` 优雅终止和 `timed_out` 标记，影响可控。

**建议**：保留 Charles 现状。量化场景命令耗时普遍较长（数据下载、回测、报告生成），600s 是合理上限。若未来区分短命令/长命令，可考虑 per-command timeout 参数。

### 差距 3：输出截断阈值差异 6 倍（3.11.13）

| 字段 | Cline | Charles |
|------|-------|---------|
| stdout 上限 | 48000 字符（合并后） | 8000 字符（独立） |
| stderr 上限 | 48000 字符（合并后，受同一上限约束） | 2000 字符（独立） |
| 单条总上限 | 48000 字符 | 10000 字符（8000+2000） |

**分析**：
- Cline 48000 字符上限对应约 12k token，是 LLM 上下文的合理上限。
- Charles 10000 字符上限对应约 2.5k token，**保守 6 倍**。
- Charles 的 stdout/stderr 分别截断策略**更精细**：stdout（编译输出、日志）给更多空间，stderr（错误信息）给少空间。
- 但 Charles 的 8000 上限对长输出命令（如 `pip list -v`、`pytest -v`）容易触发截断。

**影响**：
- Charles 的 8000 上限可能截断关键错误信息（如 Python traceback 通常在末尾）。
- 首尾各半截断策略两侧都有，但 Charles 在 result 中额外返回 `truncated: bool` 字段，让 LLM 能感知截断并主动重试 narrower 命令。

**建议**：保留 Charles 现状。量化场景命令输出普遍较短（脚本输出 + 状态码），8000 字符够用。若未来出现长输出需求，可在 constants.py 调整。

### 差距 4：stdout/stderr 处理策略相反（3.11.17）

**Cline 实现**（`bash.ts` L218-251）：

```typescript
let failureOutput = combineOutput
    ? out.text + (err.text ? `\n[stderr]\n${err.text}` : "")
    : out.text;  // stderr 被丢弃
```

- `combineOutput=true`（默认）：stderr 拼到 stdout 末尾，返回**单字符串**。
- `combineOutput=false`：stderr **完全丢弃**，只返回 stdout。
- 两种模式下 LLM 都拿到**单字段 result**。

**Charles 实现**（`run_commands.py` L290-298）：

```python
result = {
    "stdout": stdout_text,
    "stderr": stderr_text if stderr_text.strip() else "",
    "exit_code": process.returncode,
    ...
}
```

- **始终分离**：stdout 和 stderr 是 result 中两个独立字段。
- LLM 同时拿到 stdout + stderr + exit_code 三个字段。

**影响**：
- Charles 的分离策略让 LLM 能区分正常输出和错误输出，更易定位问题。
- Cline 的合并策略简单粗暴，但 stderr 被标记为 `[stderr]` 前缀，LLM 仍可识别。
- **计划文档 P3.11 描述 "Charles 合并" 与实际相反**，应更正为 "Charles 分离，Cline 默认合并"。

**建议**：保留 Charles 现状。分离策略对 LLM 推理更友好。

### 差距 5：Cline 缺危险命令拦截，Charles 缺进程树 kill（3.11.22 / 3.11.26）

**Charles 危险命令拦截**（`run_commands.py` L66-76 / L521-530）：

```python
_DENY_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/",
    r">\s*/dev/sd",
    r"shutdown",
    r"reboot",
    r"format\s+[a-z]:",
]
```

`_guard_command` 在每条命令执行前检查，命中即返回 `error: "命令被安全检查阻止"`。

**Cline 进程树 kill**（`bash.ts` L159-175）：

```typescript
const killProcessTree = () => {
    if (!childPid) return;
    if (isWindows) {
        const killer = spawn("taskkill", ["/pid", String(childPid), "/T", "/F"], ...);
        killer.unref();
        return;
    }
    try {
        process.kill(-childPid, "SIGKILL");  // 杀整个进程组
    } catch {
        child.kill("SIGKILL");
    }
};
```

- `taskkill /T /F`：`/T` 杀整个进程树（含子进程），`/F` 强制。
- `process.kill(-pid, ...)`：负 PID 杀整个进程组（POSIX 语义）。

**Charles 实现**（`run_commands.py` L341-362）：

```python
if sys.platform == "win32":
    process.terminate()  # Windows: TerminateProcess，只杀主进程
else:
    process.send_signal(signal.SIGTERM)
# ...
process.kill()  # SIGKILL，只杀主进程
```

**Charles 不杀进程树**，超时/中止时子进程（如 shell 启动的子命令）可能残留为僵尸进程。

**影响**：
- Charles 缺进程树 kill，对 `bash -c "long_running | tee log"` 这类管道命令，超时只杀 bash，管道下游进程可能继续运行。
- Cline 缺危险命令拦截，依赖 LLM 自律 + toolPolicies 策略，对 `rm -rf /` 类命令无主动防护。
- 两侧**互补缺失**：Charles 多安全拦截，Cline 多进程树清理。

**建议**：
- Charles 不强制补进程树 kill（POSIX 上 `process.kill(-pgid)` 需要 setpgid，asyncio 不直接支持，引入复杂度高）。
- Cline 不强制补危险命令拦截（依赖外部 toolPolicies 是设计选择）。
- 若未来 Charles 出现僵尸子进程问题，可考虑 `start_new_session=True` + `os.killpg(pid, SIGKILL)`。

### 差距 6：Cline 多 StructuredCommandInput + Heredoc 合并（3.11.3 / 3.11.23）

**Cline StructuredCommandInput**（`schemas.ts` L131-140）：

```typescript
export const StructuredCommandInputSchema = z.object({
    command: z.string().min(1).describe("The executable to run directly without shell parsing."),
    args: z.array(z.string()).optional().describe("Optional argv list passed directly to the executable."),
});
```

LLM 可传入 `{command: "node", args: ["script.js", "--flag"]}`，executor 直接 `spawn("node", ["script.js", "--flag"])`，**args 不经 shell 解析**，避免引号转义和注入风险。

**Cline Heredoc 合并**（`definitions.ts` L115-177）：

`coalesceAdjacentStringHeredocs` 检测相邻字符串命令中的 heredoc 起始（`<<EOF`）和结束（`EOF`），把跨数组元素的 heredoc 合并为单条命令字符串：

```typescript
// 输入: ["cat <<EOF", "line1", "line2", "EOF", "ls"]
// 合并后: ["cat <<EOF\nline1\nline2\nEOF", "ls"]
```

**Charles 缺失**：LLM 若传 `["cat <<EOF", "line1", "EOF"]`，Charles 会逐条执行，`cat <<EOF` 等待 stdin EOF 而挂起。

**影响**：
- Charles 不支持 StructuredCommandInput，所有命令都经 shell 解析，引号转义依赖 LLM。
- Charles 不支持 heredoc 跨数组元素，LLM 必须把整个 heredoc 作为单条字符串命令传入。
- 量化场景命令简单（`python script.py` / `pip install` / `git status`），缺失影响小。

**建议**：不强制补齐。Charles 的 LLM prompt 应明确指导"heredoc 必须作为单条字符串命令传入"，避免误用。

---

## 四、nanobot 残留检查

针对 P3.11 核心文件执行 nanobot 残留扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.11 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/run_commands.py` | **0** | 无 | 全文无 nanobot 引用，docstring 明确"对标 Cline RunCommandsInputSchema + bash.ts" |
| `agent/tools/constants.py` | **0** | 无 | 全文无 nanobot 引用，docstring 明确"对标 Cline output-limits.ts" |
| `agent/abort.py` | **0** | 无 | docstring 明确"对标 Cline AbortController" |
| `agent/types.py`（AgentToolContext 段落） | **0** | 无 | `abort_signal` 字段注释无 nanobot 引用 |

### 4.2 残留分类

#### 注释残留（0 处）

P3.11 核心文件**无任何 nanobot 注释残留**。`run_commands.py` 是 Charles 自研工具（非从 nanobot 移植），明确标注对标 Cline `RunCommandsInputSchema + bash.ts`，未引用 nanobot。

#### 实现逻辑残留（0 处）

P3.11 核心文件**未发现任何从 nanobot 直接移植的实现逻辑**：

- `RunCommandsTool` 类设计对标 Cline `createShellTool`（`run_commands.py` L51 标注"对标 Cline run_commands tool"）。
- `_execute` 批量执行对标 Cline `executeShellCommands`（L122 标注）。
- `_execute_single` 单条执行对标 Cline `bash.ts executor`（L180 标注）。
- `_graceful_kill` 优雅 kill 对标 Cline（L327 标注"Stage 12.1 (G2.4) 新增，对标 Cline 优雅 kill"）。
- `_truncate_output` 截断对标 Cline 首尾各一半（L365 标注"Stage 12.1 (G2.5) 新增，对标 Cline 首尾各一半截断"）。
- `_wait_process_with_abort` 对标 Cline AbortSignal（L390 docstring 暗示）。
- `_guard_command` 复用自 `ExecTool._guard_command`（L522 标注"复用自 ExecTool._guard_command"），而 ExecTool 的 `_guard_command` 历史上"对标 nanobot _guard_command"（`exec_tool.py` L263），但**run_commands.py 自身不直接引用 nanobot**。
- `MAX_COMMAND_OUTPUT_CHARS` 常量对标 Cline `output-limits.ts`（`constants.py` L7 标注）。

### 4.3 P3.11 范围外但相关的 nanobot 残留

以下文件有 nanobot 残留，但不在 P3.11 处理范围：

| 文件 | nanobot 匹配数 | 对应小阶段 | 说明 |
|------|---------------|-----------|------|
| `agent/tools/exec_tool.py` | 12 | 已废弃 | Charles 单命令执行工具（ExecTool），已被 run_commands 取代但未删除；含 docstring + 行内注释 + 1 处实现逻辑引用（"对标 nanobot shell.py L113-183"） |
| `agent/tools/file_tools.py` | 7 | P3.x（FileReadTool 专项） | 文件读写工具，docstring 标注"对标 nanobot FilesystemTool" |
| `agent/tools/__init__.py` | 1 | P3.1（已知） | L2 docstring 残留 |

**exec_tool.py 特殊说明**：`run_commands.py` 的 `_DENY_PATTERNS` 和 `_guard_command` 方法**复用自 ExecTool**（`run_commands.py` L65 注释"复用自 ExecTool._DENY_PATTERNS"，L522 注释"复用自 ExecTool._guard_command"），而 ExecTool 的对应实现历史上源自 nanobot。这是一个**间接的 nanobot 实现逻辑残留**——代码本身在 `run_commands.py` 中，但溯源链经过 `exec_tool.py` 指向 nanobot `shell.py`。**严格意义上**，`run_commands.py` 的危险命令拦截逻辑是 nanobot 实现逻辑的二次移植。属 P3 级别历史溯源，不影响当前功能。

---

## 五、修复建议

### 建议 1：不修改批量执行模型（保留串行） [P3 不修复]

**理由**：
- Charles 的串行模型符合"LLM 提交有序命令"的语义，避免命令间竞态。
- 配合 `_check_aborted` 在命令边界检查中止信号，语义清晰。
- 量化场景命令普遍短小，串行开销可接受。
- 改为并行需引入 `asyncio.gather` + 中止信号传递复杂度，收益有限。

**保留条件**：若未来出现"批量独立命令耗时过长"问题，可考虑增加 `parallel: bool` 参数。

### 建议 2：不调整超时默认值 [P3 不修复]

**理由**：
- 600s 超时符合量化场景长任务需求（Python 脚本执行、数据下载、回测）。
- 配合 `_graceful_kill` 优雅终止和 `timed_out` 标记，超时影响可控。
- Cline 的 30s 偏短，不适合量化场景。

**保留条件**：若未来引入"短命令快速失败"需求，可考虑 per-command timeout 参数。

### 建议 3：不调整输出截断阈值 [P3 不修复]

**理由**：
- 8000 + 2000 的分 stream 上限对量化场景够用（脚本输出 + 错误信息）。
- 首尾各半截断策略已对齐 Cline。
- `truncated: bool` 字段让 LLM 感知截断并主动重试。
- 调整为 48000 会增加 token 消耗，影响 LLM 推理质量。

### 建议 4：不补 StructuredCommandInput [P3 不修复]

**理由**：
- 量化场景命令简单（`python script.py` / `git status`），shell 解析足够。
- 引入 StructuredCommandInput 需在 schema + executor + LLM prompt 三处同步修改，复杂度高。
- Charles 的 `_DENY_PATTERNS` 已提供基础安全防护。

### 建议 5：不补 Heredoc 合并 [P3 不修复]

**理由**：
- 量化场景无 heredoc 需求。
- LLM 可通过 prompt 指导"heredoc 作为单条字符串命令传入"。
- 引入 `coalesceAdjacentStringHeredocs` 增加解析复杂度，收益低。

### 建议 6：保留危险命令拦截 [P0 不变]

**理由**：Charles 的 `_DENY_PATTERNS` 是有益安全增强，应予保留。`rm -rf /` / `mkfs` / `dd` / `shutdown` 等命令对量化交易系统有数据破坏风险，黑名单拦截是必要防护。

### 建议 7：保留实时终端输出推送 [P0 不变]

**理由**：`emit_update` + `terminal_output` 事件让前端能监控长命令进度（如数据下载、索引构建），是 Charles 相对 Cline 的功能增强，符合 TRAE 风格的终端面板需求。

### 建议 8：保留 stdout/stderr 分离 [P0 不变]

**理由**：分离策略让 LLM 更易区分正常输出和错误输出，比 Cline 的合并策略更友好。

### 建议 9：考虑补进程树 kill [P2 可选]

**理由**：当前 `_graceful_kill` 只杀主进程，对 `bash -c "cmd1 | cmd2"` 类管道命令可能残留子进程。

**方案**：
- POSIX：`asyncio.create_subprocess_shell(..., start_new_session=True)` 创建新进程组，超时时 `os.killpg(os.getpgid(pid), SIGTERM)`。
- Windows：`subprocess.Popen(..., creationflags=CREATE_NEW_PROCESS_GROUP)` + `taskkill /T /F`。

**优先级**：P2，待出现僵尸子进程问题再处理。

---

## 六、验证方法建议

### 验证方法 1：批量执行模型差异验证

对比 Cline 并行 vs Charles 串行的总耗时差异：

```powershell
# Cline 侧（Promise.all 并行）
# 预期：3 条命令总耗时 ≈ max(单条最长)

# Charles 侧（for 串行）
# 预期：3 条命令总耗时 = sum(各条)
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "for idx, cmd in enumerate"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts" -Pattern "Promise.all"
```

### 验证方法 2：超时默认值差异验证

```powershell
# Cline 默认 30s
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\bash.ts" -Pattern "timeoutMs = 30000|timeoutMs ?? 30000"

# Charles 默认 600s
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "_MAX_TIMEOUT|MAX_COMMAND_TIMEOUT_SECONDS"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern "MAX_COMMAND_TIMEOUT_SECONDS = 600"
```

### 验证方法 3：输出截断阈值差异验证

```powershell
# Cline 48000
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\output-limits.ts" -Pattern "MAX_COMMAND_OUTPUT_CHARS = 48"

# Charles 8000 + 2000
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern "MAX_OUTPUT_PER_COMMAND|MAX_STDERR_PER_COMMAND"
```

### 验证方法 4：stdout/stderr 分离策略验证

```powershell
# Cline combineOutput 默认 true（合并）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\bash.ts" -Pattern "combineOutput|combineOutput = true"

# Charles 始终分离（result.stdout + result.stderr 独立字段）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern '"stdout":|"stderr":'
```

### 验证方法 5：优雅 kill 策略验证

```powershell
# Cline 直接 SIGKILL（无 SIGTERM 阶段）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\bash.ts" -Pattern "SIGKILL|taskkill"

# Charles 两阶段（SIGTERM 等 1s → SIGKILL）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "SIGTERM|SIGKILL|terminate|wait_for.*timeout=1.0"
```

### 验证方法 6：危险命令拦截验证

```powershell
# Charles _DENY_PATTERNS 9 条
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "_DENY_PATTERNS|_guard_command"

# Cline 无内建拦截（应无匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\bash.ts" -Pattern "DENY_PATTERNS|guard_command"
```

### 验证方法 7：abort_signal kill 子进程验证

```powershell
# Cline AbortSignal 事件监听
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\bash.ts" -Pattern "signal.*addEventListener|abortHandler"

# Charles asyncio.wait 组合等待
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "asyncio.wait|abort_task|sig.wait"
```

### 验证方法 8：nanobot 残留扫描

```powershell
# P3.11 核心文件（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern "nanobot" -CaseSensitive:$false

# 范围外但相关（exec_tool.py 12 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\exec_tool.py" -Pattern "nanobot" -CaseSensitive:$false
```

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L125-129 | `CommandInputSchema`（命令字符串 schema，含 INPUT_ARG_CHAR_LIMIT 提示） |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L131-140 | `StructuredCommandInputSchema`（command + args 结构化输入） |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L147-151 | `RunCommandsInputSchema`（commands 数组） |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L160-170 | `RunCommandsInputUnionSchema`（9 种联合形态） |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L115-177 | `coalesceAdjacentStringHeredocs` + `coalesceSplitHeredocCommands` heredoc 合并 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L179-233 | `executeShellCommands` 批量执行器（`Promise.all` 并行） |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L397-437 | `RUN_COMMANDS_SHARED_INSTRUCTIONS` + `buildRunCommandsDescription` 平台 shell 描述 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L454-507 | `createShellTool` 工厂（timeoutMs × 2、retryable=false） |
| `sdk/packages/core/src/extensions/tools/helpers.ts` | L137-165 | `normalizeRunCommandsInput` 输入归一化 |
| `sdk/packages/core/src/extensions/tools/helpers.ts` | L185-207 | `formatRunCommandQueryPreview` 命令回显截断（200 字符） |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L21-29 | `CommandExitError` 异常类 |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L34-73 | `ShellExecutorOptions`（shell / timeoutMs / maxOutputChars / env / combineOutput） |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L86-124 | `createRollingCollector` 滚动收集器（首尾各半） |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L126-262 | `spawnAndCollect` 子进程启动 + 输出收集 + 超时 kill |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L159-175 | `killProcessTree`（Windows taskkill /T /F，POSIX 进程组 SIGKILL） |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L277-308 | `createShellExecutor` 工厂入口 |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L17-18 | `MAX_COMMAND_OUTPUT_CHARS = 48_000` |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L20-38 | `truncateCommandOutput` 首尾各半截断 |
| `sdk/packages/shared/src/parse/shell.ts` | L11-13 | `getDefaultShell`（win=powershell, posix=/bin/bash） |
| `sdk/packages/shared/src/parse/shell.ts` | L29-50 | `getShellKind`（powershell/cmd/wsl/posix 分类） |
| `sdk/packages/shared/src/parse/shell.ts` | L52-67 | `getShellArgs`（各 shell 调用参数） |
| `sdk/packages/shared/src/agent.ts` | L164-175 | `AgentToolContext`（含 `signal?: AbortSignal`） |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/run_commands.py` | L1-26 | 模块 docstring（对标 Cline RunCommandsInputSchema + bash.ts） |
| `agent/tools/run_commands.py` | L50-63 | `RunCommandsTool` 类定义 + 常量别名（_MAX_COMMANDS / _MAX_OUTPUT_PER_COMMAND 等） |
| `agent/tools/run_commands.py` | L66-76 | `_DENY_PATTERNS` 9 条危险命令正则 |
| `agent/tools/run_commands.py` | L78-79 | `__init__`（working_dir 默认 os.getcwd()） |
| `agent/tools/run_commands.py` | L82-106 | `name` / `description` / `input_schema` / `timeout_ms` / `requires_approval` 属性 |
| `agent/tools/run_commands.py` | L117-171 | `_execute` 批量执行入口（for 循环串行） |
| `agent/tools/run_commands.py` | L173-324 | `_execute_single` 单条执行（create_subprocess_shell + 流式读取 + emit_update） |
| `agent/tools/run_commands.py` | L326-362 | `_graceful_kill`（SIGTERM 等 1s → SIGKILL） |
| `agent/tools/run_commands.py` | L364-388 | `_truncate_output`（首尾各半 + `[... N characters omitted ...]`） |
| `agent/tools/run_commands.py` | L390-448 | `_wait_process_with_abort`（communicate 版本，供外部调用） |
| `agent/tools/run_commands.py` | L450-519 | `_wait_process_with_abort_stream`（流式版本，主路径） |
| `agent/tools/run_commands.py` | L521-530 | `_guard_command`（危险命令检查） |
| `agent/tools/constants.py` | L23-47 | 命令执行类常量（MAX_OUTPUT_PER_COMMAND=8000 / MAX_STDERR_PER_COMMAND=2000 / MAX_COMMANDS=10 / DEFAULT_COMMAND_TIMEOUT_SECONDS=60 / MAX_COMMAND_TIMEOUT_SECONDS=600） |
| `agent/tools/constants.py` | L12-21 | docstring（Cline 原始常量参考 + Charles 数值说明） |
| `agent/abort.py` | L26-35 | `AbortedError` 异常类 |
| `agent/abort.py` | L38-101 | `AbortController`（asyncio.Event + abort / is_set / throw_if_aborted / reset） |
| `agent/types.py` | L188-211 | `AgentToolContext`（含 `emit_update` + `abort_signal` 字段） |
| `agent/tools/base.py` | L140-159 | `_check_aborted` 中止检查辅助 |

---

## 八、结论

P3.11 `run_commands` 工具实现细节对比的核心结论：

1. **核心功能已对齐**：命令执行、超时控制、abort_signal kill、输出截断、退出码返回、单条失败不阻塞后续命令——这些核心功能在两侧都有对应实现且语义基本对齐。

2. **执行模型根本差异**（已知差异，建议不修复）：
   - Cline 用 `Promise.all` **并行执行**，Charles 用 `for` 循环**串行执行**。
   - Charles 的串行模型符合"有序命令"语义，与 `_check_aborted` 命令边界检查一致。
   - 量化场景命令普遍短小，串行开销可接受。

3. **默认值策略差异显著**（已知差异，建议不修复）：
   - 超时：Cline 30s，Charles 600s（20 倍）。
   - 截断：Cline 48000 字符，Charles 8000+2000 字符（6 倍）。
   - Charles 的保守默认值符合量化场景长任务需求。

4. **stdout/stderr 处理策略相反**（计划文档描述有误，需更正）：
   - Cline 默认 `combineOutput=true` **合并为单字符串**。
   - Charles **始终保持分离**（独立 stdout / stderr 字段）。
   - Charles 比默认更分离，对 LLM 推理更友好。

5. **优雅 kill 策略 Charles 更优**（计划文档描述有误，需更正）：
   - Cline 只用 SIGKILL（killProcessTree），无 SIGTERM 阶段。
   - Charles 用 SIGTERM 等 1s → SIGKILL 两阶段，给子进程清理机会。

6. **Charles 额外能力**（应予保留）：
   - 危险命令拦截（`_DENY_PATTERNS` 9 条正则）。
   - 实时终端输出推送（`emit_update` + `terminal_output`）。
   - `timed_out` / `truncated` 布尔标记字段。
   - `PYTHONUNBUFFERED=1` 强制实时输出。

7. **Cline 额外能力**（Charles 缺失，建议不补）：
   - `StructuredCommandInput` 结构化输入（避免 shell 解析）。
   - `RunCommandsInputUnionSchema` 9 种输入形态。
   - `coalesceAdjacentStringHeredocs` heredoc 合并。
   - 平台 shell 分发（powershell/cmd/wsl/posix）。
   - 命令回显截断（`formatRunCommandQueryPreview` 200 字符）。
   - 遥测（`captureRunCommandsTimeout`）。

8. **Charles 缺进程树 kill**（P2 可选修复）：
   - 当前 `_graceful_kill` 只杀主进程。
   - 对管道命令可能残留子进程。
   - 待出现僵尸子进程问题再处理。

9. **nanobot 残留**：P3.11 核心文件 `run_commands.py` 和 `constants.py` **均无 nanobot 残留**（0 处匹配）。`run_commands.py` 是 Charles 自研工具，明确对标 Cline。但 `_DENY_PATTERNS` 和 `_guard_command` 复用自 `ExecTool`，而 ExecTool 历史上源自 nanobot `shell.py`，属**间接的 nanobot 实现逻辑残留**——代码在 `run_commands.py` 中，溯源链经过 `exec_tool.py` 指向 nanobot。不影响当前功能，属 P3 级别历史溯源。

10. **计划文档 P3.11 描述需更正**：
    - "Charles asyncio.create_subprocess_exec" → 实际是 `create_subprocess_shell`。
    - "Charles stdout/stderr 合并" → 实际**始终保持分离**。
    - "Cline SIGTERM → SIGKILL" → 实际 Cline **只用 SIGKILL**，Charles 才是两阶段。
    - "Charles 输出截断 30000" → 实际是 8000（stdout）+ 2000（stderr），总计 10000。

**整体一致性等级**：**中**。核心功能对齐，执行模型和默认值差异是设计选择非缺陷。Charles 的危险命令拦截和实时终端推送是有益功能增强。P3.11 范围内无需阻塞性修复，建议 9（进程树 kill）为 P2 可选优化，待出现实际问题再处理。
