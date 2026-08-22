# Phase 3.5 工具超时与重试对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在工具超时与重试机制（`timeoutMs`/`retryable`/`maxRetries`）上的差异，覆盖字段默认值、超时包裹方式、重试策略、超时后行为、各工具具体配置、`withTimeout` 实现方式七个维度。

总体结论：**计划 P3.5 的描述存在多处重大错误**，实际代码与计划描述截然不同。核心发现如下：

1. **Cline 的 `retryable`/`maxRetries` 字段是"死字段"**：`AgentTool` 接口（`agent.ts` L179-181）声明了 `retryable?: boolean` 与 `maxRetries?: number`，`createTool`（`create.ts` L125-127）设置了默认值（retryable=true, maxRetries=3），但 `agent-runtime.ts` 的 `executePreparedTool`（L1464-1560）**没有任何重试循环**，直接调用一次 `prepared.tool.execute()` 即返回。全 `packages/agents/` 目录搜索 `retry`/`retries`/`backoff` 关键词均无匹配。Cline 实际上**没有运行时级别的重试机制**，重试字段仅作为元数据存在。

2. **Cline 的 `timeoutMs` 字段同样不被 runtime 强制执行**：`agent-runtime.ts` 的 `executePreparedTool` 不会用 `withTimeout` 包裹 `tool.execute()`。超时由各工具在自己的 `execute()` 实现内**显式调用 `withTimeout` 包裹 executor**（如 `definitions.ts` L196-200 run_commands、L310-313 read_files、L372-375 search_codebase、L538-541 fetch_web_content、L627-629 apply_patch、L690-693 editor、L742-750 skills、L820-823 submit_and_exit）。未在 `execute()` 内调用 `withTimeout` 的工具（如 ask_question）实际无超时保护。

3. **Charles 的超时与重试实现反而更完整**：`runtime.py` L1918-2042 的 `_execute_with_timeout_and_retry` 方法是运行时级别的统一封装，对所有工具的 `execute()` 调用：
   - 用 `asyncio.wait_for` 强制 `tool.timeout_ms`（或 `default_tool_timeout_ms=300000`）
   - `retryable=True` 时按 `max_retries` 重试，指数退避（`0.2 * 2^n` 秒，即 0.2s / 0.4s / 0.8s）
   - `AbortedError` 不重试（用户中止立即生效）
   - schema 校验失败不重试（含 `validation_errors` 字段的结果直接返回）
   - `is_error=True` 的结果也会触发重试

4. **计划 P3.5 多处描述与实际代码不符**（详见第 3 节）：
   - P3.5.1 称 "Cline timeoutMs 默认 60000" → 实际 `createTool` 默认 `30_000`（`create.ts` L125）
   - P3.5.1 称 "Cline retryable 默认 false" → 实际 `createTool` 默认 `true`（`create.ts` L126）
   - P3.5.5 称 "Charles 无 max_retries 字段" → 实际 `base.py` L86-88 有 `max_retries` 属性
   - P3.5.3 称 "Charles 仅 run_commands 有超时" → 实际 exec_tool / run_commands / fetch_web_content / web_tool / skills 均覆盖了 `timeout_ms`
   - P3.5.6 / P3.5.7 称 "Charles 缺失重试错误判定 / 重试间隔" → 实际 Charles 是**唯一**实现了指数退避重试的一方

`nanobot` 残留检查：在 `agent/tools/base.py`、`agent/runtime.py`、`agent/types.py` 三个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）；`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标注说明（详见第 4 节）。

## 2. 逐项对比表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 3.5.1 | timeoutMs 默认值 | `create.ts` L125（`config.timeoutMs ?? 30_000`） | `base.py` L76-78（`timeout_ms` 默认 `None`）+ `types.py` L543（`default_tool_timeout_ms = 300_000`） | **计划描述错误**：Cline 默认 30000（非 60000）；Charles 工具默认 None 时回退到 runtime 的 300000ms | 弱对齐 |
| 3.5.2 | retryable 默认值 | `create.ts` L126（`config.retryable ?? true`） | `base.py` L81-83（默认 `False`） | **计划描述错误**：Cline 默认 true（非 false）；Charles 默认 False。默认值相反 | 未对齐 |
| 3.5.3 | maxRetries 默认值 | `create.ts` L127（`config.maxRetries ?? 3`） | `base.py` L86-88（默认 `0`） | Cline 默认 3，Charles 默认 0；但 Cline 默认值实际未被使用（见 3.5.7） | 未对齐 |
| 3.5.4 | withTimeout 实现方式 | `helpers.ts` L48-59（`Promise.race` + `setTimeout`，抛 `TimeoutError`） | `runtime.py` L1965-1968（`asyncio.wait_for`，抛 `asyncio.TimeoutError`） | 实现机制不同（Promise.race vs asyncio.wait_for），语义等价；Cline 由工具自行调用，Charles 由 runtime 统一包裹 | Charles 更完整 |
| 3.5.5 | withTimeout 包裹位置 | 各工具 `execute()` 内显式调用（`definitions.ts` L196/L310/L372/L538/L627/L690/L742/L820） | `runtime.py` L1965 `_execute_with_timeout_and_retry` 统一包裹 | **计划描述错误**：Cline 非全工具自动包裹（ask_question 未调用 withTimeout）；Charles 是 runtime 级别全工具统一包裹 | Charles 更完整 |
| 3.5.6 | 重试逻辑实现位置 | **无**（`agent-runtime.ts` 无重试循环） | `runtime.py` L1962-2042 `_execute_with_timeout_and_retry` 的 `for attempt in range(max_retries + 1)` 循环 | **计划描述错误**：Cline 实际无运行时重试；Charles 是唯一实现重试的一方 | Charles 独有 |
| 3.5.7 | 重试策略（指数退避） | **无**（无重试逻辑） | `runtime.py` L1994/L2013/L2026（`delay = 0.2 * (2 ** attempt)` 秒，即 0.2s/0.4s/0.8s） | **计划描述错误**：Cline 无重试间隔；Charles 有指数退避 | Charles 独有 |
| 3.5.8 | 重试错误判定 | **无**（无重试逻辑） | `runtime.py` L2007-2009（`AbortedError` 不重试）、L1985-1989（schema 校验失败不重试）、L1992-2002（`is_error=True` 触发重试） | **计划描述错误**：Cline 无重试错误判定；Charles 有完整判定逻辑 | Charles 独有 |
| 3.5.9 | 超时后行为 | 工具内 `withTimeout` 抛 `TimeoutError`，由工具自行 catch 转 `error` 字段（如 `definitions.ts` L206-213 run_commands） | `runtime.py` L1832-1850 catch `asyncio.TimeoutError`，返回 `is_error=True` 的 `AgentToolResult`（含超时毫秒数和重试次数） | 两者超时后均返回错误结果，不向上抛异常；Charles 错误信息含超时毫秒数和重试次数 | 已对齐 |
| 3.5.10 | skills 工具超时 | `definitions.ts` L723（`config.skillsTimeoutMs ?? 15000`，默认 15000ms） | `skill_tool.py` L55-56/L105-114（`skills_timeout_ms=15000`，可通过 `__init__` 参数注入） | 两者默认值一致（15000ms）；Charles 可通过构造函数参数覆盖 | 已对齐 |
| 3.5.11 | run_commands 超时 | `definitions.ts` L460（`config.bashTimeoutMs ?? 30000`，工具 timeoutMs 设为 `timeoutMs * 2 = 60000`） | `run_commands.py` L109-110（`self._MAX_TIMEOUT * 1000 = 600000`） | Cline 工具级 60000ms，Charles 工具级 600000ms（10 倍差异）；Charles 用于量化脚本执行，需更长超时 | 弱对齐 |
| 3.5.12 | read_files 超时 | `definitions.ts` L248（`config.fileReadTimeoutMs ?? 10000`，工具 timeoutMs 设为 `timeoutMs * 2 = 20000`） | `read_files.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Cline 工具级 20000ms，Charles 回退到 300000ms；差异大 | 弱对齐 |
| 3.5.13 | search_codebase 超时 | `definitions.ts` L344（`config.searchTimeoutMs ?? 30000`，工具 timeoutMs 设为 `timeoutMs * 2 = 60000`） | `search_codebase.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Cline 工具级 60000ms，Charles 回退到 300000ms | 弱对齐 |
| 3.5.14 | fetch_web_content 超时 | `definitions.ts` L518（`config.webFetchTimeoutMs ?? 30000`，工具 timeoutMs 设为 `timeoutMs * 2 = 60000`） | `fetch_web_content.py` L154-156（`60_000`） | 两者均为 60000ms，已对齐 | 已对齐 |
| 3.5.15 | editor 超时 | `definitions.ts` L660（`config.editorTimeoutMs ?? 30000`） | `editor.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Cline 工具级 30000ms，Charles 回退到 300000ms | 弱对齐 |
| 3.5.16 | apply_patch 超时 | `definitions.ts` L611（`config.applyPatchTimeoutMs ?? 30000`） | `apply_patch.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Cline 工具级 30000ms，Charles 回退到 300000ms | 弱对齐 |
| 3.5.17 | exec_tool 超时 | Cline 无 exec_tool（只有 run_commands） | `exec_tool.py` L111-112（`self._DEFAULT_TIMEOUT * 1000 = 60000`） | Charles 独有工具，无对比对象 | N/A |
| 3.5.18 | web_tool 超时 | Cline 无独立 web_tool（web 搜索由 fetch_web_content 承担） | `web_tool.py` L71-73（`30_000`） | Charles 独有工具，无对比对象 | N/A |
| 3.5.19 | ask_question 超时 | `definitions.ts` L776-794（无 timeoutMs 字段，无 withTimeout 包裹） | `ask_question.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Cline ask_question 实际无超时保护；Charles 有 runtime 级 300000ms 超时 | Charles 更完整 |
| 3.5.20 | submit_and_exit 超时 | `definitions.ts` L801（`config.submitTimeoutMs ?? 15000`，有 withTimeout 包裹 L820） | `submit_and_exit.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Cline 工具级 15000ms，Charles 回退到 300000ms | 弱对齐 |
| 3.5.21 | list_files 超时 | Cline 无 list_files 工具 | `list_files.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Charles 独有工具，无对比对象 | N/A |
| 3.5.22 | todo_write 超时 | Cline 无 todo_write 工具 | `todo_write.py` 无覆盖（用 base 默认 `None` → runtime 回退 300000ms） | Charles 独有工具，无对比对象 | N/A |
| 3.5.23 | default_tool_timeout_ms 配置 | 无（Cline 无 runtime 级默认超时） | `types.py` L543（`default_tool_timeout_ms: int = 300_000`） | Charles 独有的 runtime 级兜底超时；Cline 工具不设 timeoutMs 时无超时保护 | Charles 独有 |
| 3.5.24 | retryable 实际生效 | `create.ts` L126 设置默认值，但 `agent-runtime.ts` 不读取此字段 | `runtime.py` L1957（`max_retries = tool.max_retries if tool.retryable else 0`） | **Cline 的 retryable 字段是死字段**；Charles 实际读取并生效 | Charles 独有 |
| 3.5.25 | maxRetries 实际生效 | `create.ts` L127 设置默认值，但 `agent-runtime.ts` 不读取此字段 | `runtime.py` L1957（`max_retries = tool.max_retries if tool.retryable else 0`） | **Cline 的 maxRetries 字段是死字段**；Charles 实际读取并生效 | Charles 独有 |

## 3. 重点差距详细说明

### 3.1 计划 P3.5 多处描述错误

计划 `AGENT_COMPARISON_PLAN_V2.md` L747-772 的 P3.5 章节存在多处与实际代码不符的描述：

| 计划描述 | 实际代码 | 影响程度 |
|---------|---------|---------|
| "Cline per-tool timeoutMs（默认 60000）" | `create.ts` L125：`timeoutMs: config.timeoutMs ?? 30_000`，默认 30000 | 中（默认值错误 2 倍） |
| "Cline per-tool retryable（默认 false）" | `create.ts` L126：`retryable: config.retryable ?? true`，默认 true | 高（默认值相反） |
| "Cline per-tool maxRetries（默认 3）" | `create.ts` L127：`maxRetries: config.maxRetries ?? 3`，默认 3 | 低（数值正确，但字段未被使用） |
| "Charles 无 max_retries 字段" | `base.py` L86-88：`def max_retries(self) -> int: return 0` | 高（字段存在） |
| "Charles 仅 run_commands 有超时" | exec_tool / run_commands / fetch_web_content / web_tool / skills 均有 | 高（5 个工具有超时） |
| "Charles 缺失重试错误判定" | `runtime.py` L2007-2009 / L1985-1989 有完整判定 | 高（Charles 是唯一有判定的一方） |
| "Charles 缺失重试间隔" | `runtime.py` L1994 等有指数退避 `0.2 * 2^n` | 高（Charles 是唯一有退避的一方） |
| "Cline withTimeout 包裹全工具" | ask_question 未调用 withTimeout | 中（非全工具） |

**残留性质**：非代码残留，属于计划文档描述错误。建议后续修订计划文档时更正。

### 3.2 Cline 的 retryable/maxRetries 是"死字段"

- **字段声明**：`agent.ts` L179-181 在 `AgentTool` 接口声明了 `timeoutMs?: number` / `retryable?: boolean` / `maxRetries?: number` 三个可选字段。
- **默认值设置**：`create.ts` L125-127 的 `createTool` 函数为这三个字段设置了默认值：
  ```typescript
  timeoutMs: config.timeoutMs ?? 30_000,
  retryable: config.retryable ?? true,
  maxRetries: config.maxRetries ?? 3,
  ```
- **runtime 不读取**：`agent-runtime.ts` 的 `executePreparedTool`（L1464-1560）是工具执行的唯一入口，其核心逻辑（L1487-1517）：
  ```typescript
  try {
      const output = await prepared.tool.execute(prepared.input, { ... });
      result = { output };
  } catch (error) {
      result = {
          output: { error: error instanceof Error ? error.message : String(error) },
          isError: true,
      };
  }
  ```
  **没有任何 retry 循环**，不读取 `tool.retryable` 或 `tool.maxRetries`，直接调用一次 `execute()` 即返回。全 `packages/agents/` 目录搜索 `retry`/`retries`/`backoff`/`sleep` 关键词均无匹配。
- **字段用途推测**：这两个字段可能是为未来版本预留的元数据，或者供外部消费者（如插件系统 `plugin-sandbox.ts` L393、MCP 工具 `mcp/tools.ts` L33-34）读取后自行实现重试逻辑。但 Cline 的核心 runtime 不使用它们。
- **影响**：Cline 的工具一旦失败就失败，不会自动重试。`retryable=true`/`maxRetries=3` 的默认值仅是元数据声明，不产生实际重试行为。
- **残留性质**：非残留，属于 Cline 的设计选择（字段预留）。

### 3.3 Cline 的 timeoutMs 不被 runtime 强制，由工具自行 withTimeout

- **runtime 不包裹超时**：`agent-runtime.ts` 的 `executePreparedTool` 不会用 `withTimeout` 包裹 `tool.execute()`。`tool.timeoutMs` 字段在 runtime 层完全不被读取。
- **工具内显式调用**：超时由各工具在自己的 `execute()` 实现内显式调用 `withTimeout` 包裹 executor。以 `run_commands` 为例（`definitions.ts` L196-200）：
  ```typescript
  const output = await withTimeout(
      executor(command, cwd, context),
      timeoutMs,
      `Command timed out after ${timeoutMs}ms`,
  );
  ```
- **未调用 withTimeout 的工具无超时保护**：`ask_question`（`definitions.ts` L776-794）的 `execute()` 直接调用 `executor(...)` 无 withTimeout 包裹，实际无超时保护。
- **withTimeout 实现**（`helpers.ts` L48-59）：
  ```typescript
  export function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
      return Promise.race([
          promise,
          new Promise<never>((_, reject) => {
              setTimeout(() => reject(new TimeoutError(message, ms)), ms);
          }),
      ]);
  }
  ```
  使用 `Promise.race` 与 `setTimeout` 实现，超时后抛 `TimeoutError`（`helpers.ts` L38-46）。
- **影响**：Cline 的超时是"工具自治"模式，工具开发者需自行在 execute() 内调用 withTimeout；忘记调用则无超时保护。
- **残留性质**：非残留，属于 Cline 的设计选择（工具自治）。

### 3.4 Charles 的 _execute_with_timeout_and_retry 是运行时级别统一封装

- **统一入口**：`runtime.py` L1828-1831 在 `_execute_prepared_tool` 中调用 `self._execute_with_timeout_and_retry(prepared.tool, prepared.input, context)`，所有工具的执行都经过此方法。
- **超时实现**（L1964-1968）：
  ```python
  if timeout_ms and timeout_ms > 0:
      output = await asyncio.wait_for(
          tool.execute(input, context),
          timeout=timeout_ms / 1000.0,
      )
  else:
      output = await tool.execute(input, context)
  ```
  使用 `asyncio.wait_for` 强制超时，超时后抛 `asyncio.TimeoutError`。
- **重试循环**（L1962-2042）：
  ```python
  for attempt in range(max_retries + 1):
      try:
          # ... asyncio.wait_for 包裹 execute ...
          if not result.is_error:
              return result
          # schema 校验失败不重试
          if isinstance(result.output, dict) and "validation_errors" in result.output:
              return result
          # is_error 结果：retryable=True 时重试
          if attempt < max_retries:
              delay = 0.2 * (2 ** attempt)
              await asyncio.sleep(delay)
              continue
          return result
      except AbortedError:
          raise  # 用户中止不重试
      except asyncio.TimeoutError as e:
          if attempt < max_retries:
              delay = 0.2 * (2 ** attempt)
              await asyncio.sleep(delay)
              continue
          raise
      except Exception as e:
          if attempt < max_retries:
              delay = 0.2 * (2 ** attempt)
              await asyncio.sleep(delay)
              continue
          raise
  ```
- **退避公式**：`delay = 0.2 * (2 ** attempt)` 秒，即 attempt=0 失败后等 0.2s，attempt=1 失败后等 0.4s，attempt=2 失败后等 0.8s。
- **不重试的情况**：
  1. `AbortedError`（用户中止，L2007-2009）
  2. schema 校验失败（output 含 `validation_errors` 字段，L1985-1989）
  3. `retryable=False`（`max_retries` 被置为 0，L1957）
- **超时后行为**（L1832-1850）：catch `asyncio.TimeoutError`，返回 `is_error=True` 的 `AgentToolResult`，错误信息含超时毫秒数和重试次数：
  ```python
  result = AgentToolResult(
      output={
          "error": f"工具 {prepared.tool_call.tool_name} 执行超时"
                   f"（{timeout_ms} ms，已重试 {max_retries} 次）"
      },
      is_error=True,
  )
  ```
- **影响**：Charles 的超时与重试是"runtime 统一"模式，工具开发者只需声明 `timeout_ms`/`retryable`/`max_retries` 属性，无需在 execute() 内自行实现。这是 Charles 相对 Cline 的功能增强。
- **残留性质**：非残留，属于 Charles 的主动增强（Phase 29.2）。

### 3.5 Charles 工具超时配置覆盖情况

Charles 的 `BaseTool`（`base.py` L76-88）提供三个默认值：
- `timeout_ms` 默认 `None`（由 runtime 用 `default_tool_timeout_ms=300000` 兜底）
- `retryable` 默认 `False`
- `max_retries` 默认 `0`

各工具的覆盖情况：

| 工具 | timeout_ms | retryable | max_retries | 来源 |
|------|-----------|-----------|-------------|------|
| exec_tool | 60000 | False（默认） | 0（默认） | `exec_tool.py` L111-112 |
| run_commands | 600000 | False（默认） | 0（默认） | `run_commands.py` L109-110 |
| fetch_web_content | 60000 | True | 2 | `fetch_web_content.py` L154-166 |
| web_tool | 30000 | True | 2 | `web_tool.py` L71-83 |
| skills | 15000（可配置） | False（默认） | 0（默认） | `skill_tool.py` L55-56/L105-114 |
| read_files | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| search_codebase | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| list_files | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| editor | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| apply_patch | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| ask_question | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| submit_and_exit | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |
| todo_write | None（回退 300000） | False（默认） | 0（默认） | 无覆盖 |

- **影响**：只有 `fetch_web_content` 和 `web_tool` 两个网络类工具启用了重试（retryable=True, max_retries=2）；其余工具 retryable=False，失败后不重试。
- **残留性质**：非残留，属于 Charles 的合理设计（网络请求才需重试，文件读写/命令执行不应自动重试）。

### 3.6 Cline 与 Charles 的工具超时值对比

| 工具 | Cline timeoutMs | Charles timeout_ms | 差异 |
|------|----------------|-------------------|------|
| read_files | 20000（fileReadTimeoutMs=10000 × 2） | 300000（runtime 兜底） | Charles 15 倍 |
| search_codebase | 60000（searchTimeoutMs=30000 × 2） | 300000（runtime 兜底） | Charles 5 倍 |
| run_commands | 60000（bashTimeoutMs=30000 × 2） | 600000 | Charles 10 倍 |
| fetch_web_content | 60000（webFetchTimeoutMs=30000 × 2） | 60000 | 一致 |
| editor | 30000 | 300000（runtime 兜底） | Charles 10 倍 |
| apply_patch | 30000 | 300000（runtime 兜底） | Charles 10 倍 |
| skills | 15000 | 15000 | 一致 |
| submit_and_exit | 15000 | 300000（runtime 兜底） | Charles 20 倍 |
| ask_question | 无（未设 withTimeout） | 300000（runtime 兜底） | Charles 有保护，Cline 无 |

- **影响**：Charles 的工具超时普遍比 Cline 长 5-20 倍。这是合理的场景差异——Charles 用于量化脚本执行（如 `ratio_analysis.py`、`query_report.py`），需要更长超时；Cline 面向通用编程助手场景，超时更短。
- **残留性质**：非残留，属于场景驱动的配置差异。

## 4. nanobot 残留检查

### 4.1 重点文件检查结果

在以下重点文件中搜索 `nanobot` 字符串：
- `agent/tools/base.py`：**未发现** nanobot 残留
- `agent/runtime.py`：**未发现** nanobot 残留
- `agent/types.py`：**未发现** nanobot 残留
- `agent/tools/exec_tool.py`：**发现** 6 处 nanobot 残留（均为注释/docstring）
- `agent/tools/run_commands.py`：**未发现** nanobot 残留
- `agent/tools/fetch_web_content.py`：**未发现** nanobot 残留
- `agent/tools/web_tool.py`：**未发现** nanobot 残留
- `agent/skills/skill_tool.py`：**发现** 1 处 nanobot 残留（docstring）

### 4.2 注释残留（非实现逻辑残留）

以下 nanobot 残留均为注释/docstring 层面的历史对标注说明，**不影响实现逻辑**：

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/tools/exec_tool.py` | L2 | `"""命令执行工具 — 对标 Cline BashTool + nanobot ShellTool` | docstring 对标说明 |
| `agent/tools/exec_tool.py` | L8 | `1. asyncio.create_subprocess_shell 异步执行（对标 nanobot shell.py）` | docstring 对标说明 |
| `agent/tools/exec_tool.py` | L9 | `2. deny_patterns 阻止危险命令（对标 nanobot _guard_command）` | docstring 对标说明 |
| `agent/tools/exec_tool.py` | L10 | `3. 输出截断防止撑爆上下文（对标 nanobot _MAX_OUTPUT）` | docstring 对标说明 |
| `agent/tools/exec_tool.py` | L18-19 | `对标 nanobot:\n    - nanobot/agent/tools/shell.py L113-183` | docstring 对标说明 |
| `agent/tools/exec_tool.py` | L57 | `# 危险命令模式 — 对标 nanobot deny_patterns` | 注释对标说明 |
| `agent/tools/exec_tool.py` | L123 | `# 安全检查 — 对标 nanobot _guard_command` | 注释对标说明 |
| `agent/tools/exec_tool.py` | L165 | `# 组装输出 — 对标 nanobot shell.py L156-168` | 注释对标说明 |
| `agent/tools/exec_tool.py` | L181 | `# 输出截断 — 对标 nanobot shell.py L171-178` | 注释对标说明 |
| `agent/tools/exec_tool.py` | L263 | `"""安全检查 — 对标 nanobot _guard_command` | docstring 对标说明 |
| `agent/skills/skill_tool.py` | L18 | `这与 nanobot 的"子 agent 隔离执行"有本质区别:` | docstring 对标说明 |

### 4.3 实现逻辑残留检查

**未发现** 任何 nanobot 实现逻辑残留。所有超时与重试相关的实现逻辑均对标 Cline：
- `BaseTool` 的 `timeout_ms`/`retryable`/`max_retries` 属性对标 `AgentTool` 接口（`base.py` L17-20 注释明确标注）
- `_execute_with_timeout_and_retry` 方法对标 Cline `withTimeout` + retryable（`runtime.py` L1924 docstring 明确标注）

## 5. 总结

### 5.1 实际对齐状态

| 维度 | Cline | Charles | 谁更完整 |
|------|-------|---------|---------|
| 字段声明 | AgentTool 接口有 timeoutMs/retryable/maxRetries | BaseTool 有 timeout_ms/retryable/max_retries | 等价 |
| 字段默认值 | createTool 默认 30000/true/3 | BaseTool 默认 None/False/0 | 不同（场景差异） |
| 超时实现 | 工具内 withTimeout 自治 | runtime 统一 asyncio.wait_for | Charles 更完整 |
| 重试实现 | **无**（字段是死字段） | runtime 统一指数退避重试 | **Charles 独有** |
| 重试策略 | **无** | 0.2 * 2^n 指数退避 | **Charles 独有** |
| 重试错误判定 | **无** | AbortedError/schema 失败不重试 | **Charles 独有** |
| 超时后行为 | 工具内 catch 转 error 字段 | runtime catch 转 is_error 结果 | 等价 |

### 5.2 核心结论

1. **Charles 的超时与重试机制比 Cline 更完整**：Charles 有 runtime 级别的统一超时包裹和指数退避重试，Cline 只有工具级自治超时且无重试。
2. **Cline 的 retryable/maxRetries 是死字段**：声明了默认值但 runtime 从不读取，不产生实际重试行为。
3. **计划 P3.5 描述与实际代码严重不符**：多处将 Cline 描述为有重试、Charles 描述为缺失，实际恰好相反。
4. **超时值差异是场景驱动的合理设计**：Charles 用于量化脚本执行，超时比 Cline 长 5-20 倍是合理的。
5. **nanobot 残留均为注释/docstring**：不影响超时与重试的实现逻辑。

### 5.3 建议后续动作

1. 修订 `AGENT_COMPARISON_PLAN_V2.md` P3.5 章节的错误描述
2. 无需修改 Charles 源码（Charles 的实现已优于 Cline）
3. 若需进一步对齐 Cline，可考虑让 Cline 的 runtime 实际使用 retryable/maxRetries 字段（但这是 Cline 侧的改进，非 Charles 侧）
