# Phase 2.4 _execute_tool_calls 工具执行对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在工具执行流程上的差异，覆盖 `executeToolCalls` / `_execute_tool_calls` 入口、`prepareToolExecution` / `_prepare_tool_execution` 准备阶段、`executePreparedTool` / `_execute_prepared_tool` 执行阶段、beforeTool/afterTool hooks、`tool.execute` 传参、tool result message 构建、超时、重试、abort_signal 透传、工具结果截断与序列化十个维度。

总体结论：Charles 已将 Cline 的核心工具执行语义对齐到函数级，parallel/sequential 双模式、beforeTool/afterTool hook 调用顺序、tool.execute 传参结构、tool result message 字段结构均与 Cline 等价。但存在三处显著分歧：

1. **超时与重试层位置不同**（最重要分歧）：Cline 在 `agent-runtime.ts` 中 **不使用** `timeoutMs` / `retryable` / `maxRetries` 字段，这三个字段仅定义在 `AgentTool` 接口（`shared/src/agent.ts` L179-181）和 `createTool` 工厂（`shared/src/tools/create.ts` L125-127，默认 30s / retryable=true / maxRetries=3）中，由工具实现自行消费；Charles 在 `runtime.py::_execute_with_timeout_and_retry`（L1918-2042）中 **在 runtime 层统一实现** 超时（`asyncio.wait_for`）与重试（指数退避 200ms * 2^n），覆盖所有工具。Charles 的实现是 Cline 接口契约的"提前实现"，属于功能增强而非残留，但与 Cline 的"工具自治"语义不同。
2. **工具结果截断策略不同**：Cline 双层截断（per-tool executor 48000 字符 head+tail 保中间删 + MessageBuilder 8000 字符预算重截），截断标记结构化且含恢复指引；Charles 单层截断（runtime `_serialize_tool_output` 16000 字符 head-only），截断标记简单。两者阈值与保尾策略不同。
3. **plan 中 P2.4.1 "Charles 仅 sequential" 描述不准确**：Charles `runtime.py` L1435-1439 实际已实现 parallel 模式（`asyncio.gather`），与 Cline L1299-1303（`Promise.all`）语义等价；Charles `types.py` L529 默认值为 `"sequential"`，与 Cline L438 `?? "sequential"` 默认值一致。

`nanobot` 残留检查：在 `agent/runtime.py`、`agent/tools/base.py` 两个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）；`agent/` 其他文件（skills/、tools/、providers/、server.py、session.py、context.py）的 nanobot 残留均为注释/docstring 层面的历史对标注说明，详见第 4 节。

## 2. 逐项对比表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.4.1 | parallel 模式支持 | `agent-runtime.ts` L1299-1303（`Promise.all`） | `runtime.py` L1435-1439（`asyncio.gather`） | 两者均支持 parallel/sequential 双模式，默认均 sequential；plan 中"Charles 仅 sequential"描述不准确 | 已对齐 |
| 2.4.2 | beforeTool 调用顺序 | `agent-runtime.ts` L1370-1393（`prepareToolExecution`） | `runtime.py` L1477-1512（`_prepare_tool_execution`） | 调用顺序一致（schema 规范化 → beforeTool hooks → policy 检查 → 审批）；Charles 额外有 additional_context 注入（Stage 12.3）、ControlledStopError 区分（Stage 10.4）、MCP per-tool 策略（Stage 9.1） | 弱对齐 |
| 2.4.3 | tool.execute 传参 | `agent-runtime.ts` L1488-1507 | `runtime.py` L1812-1826 | context 字段结构对齐（session_id/agent_id/conversation_id/run_id/iteration/tool_call_id/snapshot/emit_update/abort_signal/metadata）；字段名差异：Cline `signal`，Charles `abort_signal` | 已对齐 |
| 2.4.4 | afterTool 调用顺序 | `agent-runtime.ts` L1522-1538 | `runtime.py` L1867-1884 | 调用顺序一致（executePreparedTool 末尾遍历 afterTool hooks，after.result 可替换 result）；Charles 缺少 Cline 的 `applyStopControl` 统一封装，但 `after_result.stop` 同样抛 RuntimeError | 已对齐 |
| 2.4.5 | tool result message 构建 | `agent-runtime.ts` L1541-1549 | `runtime.py` L1890-1897 | 字段结构对齐（tool_call_id/tool_name/output/is_error）；两者均保持 output 原始类型不强制序列化 | 已对齐 |
| 2.4.6 | tool 执行超时 | `agent-runtime.ts` **未实现**（timeoutMs 字段仅定义不消费） | `runtime.py` L1918-2042（`_execute_with_timeout_and_retry`，`asyncio.wait_for`） | Cline runtime 层不超时，由工具自治；Charles runtime 层统一超时（默认 300000ms = 5 分钟，`types.py` L543） | 语义不等价 |
| 2.4.7 | tool 重试 | `agent-runtime.ts` **未实现**（retryable/maxRetries 字段仅定义不消费） | `runtime.py` L1957-2042（retryable=True 时按 max_retries 指数退避重试） | Cline runtime 层不重试，由工具自治；Charles runtime 层统一重试（默认 retryable=False、max_retries=0，`base.py` L82-88） | 语义不等价 |
| 2.4.8 | abort_signal 透传 | `agent-runtime.ts` L1495（`signal: this.abortController?.signal`） | `runtime.py` L1824（`abort_signal=self._abort_controller.signal`） | 字段名不同（signal vs abort_signal），语义等价；BaseTool._check_aborted（base.py L140-159）检查 signal.is_set() 抛 AbortedError | 已对齐 |
| 2.4.9 | 工具结果截断 | `output-limits.ts`（per-tool 48000 字符 head+tail）+ `message-builder.ts` L28（DEFAULT_MAX_TOOL_RESULT_CHARS=8000 预算重截） | `runtime.py` L2607-2632（`_serialize_tool_output`，max_tool_result_chars=16000 head-only） | Cline 双层截断保 head+tail，Charles 单层截断仅保 head；阈值不同（8000/48000 vs 16000） | 弱对齐 |
| 2.4.10 | 工具结果序列化 | `agent-runtime.ts` L1546（output 原样存入 message） | `runtime.py` L1894（output 原样存入 message） | 两者均不在 message 构建时序列化，序列化仅在事件展示 / provider 请求时进行（Charles `_serialize_tool_output` 仅用于 emit 事件） | 已对齐 |
| 2.4.11 | prepare 阶段 inputParseError 检查 | `agent-runtime.ts` L1347-1349（metadata.inputParseError → skipReason） | `runtime.py` 无对应（invalid_tool_calls 在 `_generate_assistant_message` 阶段已处理并生成错误 result message） | Cline 在 prepare 阶段二次检查；Charles 在 stream 组装阶段已拦截，prepare 阶段无此检查 | 弱对齐 |
| 2.4.12 | prepare 阶段 toolSource.executionMode 检查 | `agent-runtime.ts` L1351-1363（provider 模式 → skipReason） | `runtime.py` 无对应 | Charles 缺失 provider-side tool execution 跳过逻辑 | 缺失 |
| 2.4.13 | prepare 阶段 schema 规范化时机 | `agent-runtime.ts` L1365-1367（beforeTool hooks 之前） | `runtime.py` L1464-1467（before_tool hooks 之前） | 时机一致，均确保 hooks 拿到规范化后的输入 | 已对齐 |
| 2.4.14 | prepare 阶段 policy 三态语义 | `agent-runtime.ts` L1396-1413（enabled=False → deny，autoApprove=False → ask） | `runtime.py` L1559-1583（同三态 + requires_approval 兜底） | Charles 额外有 requires_approval 兜底（L1572-1583），Cline 无兜底 | 弱对齐 |
| 2.4.15 | execute 阶段 skip_reason 结果 | `agent-runtime.ts` L1476-1480（`{error: skipReason}`, isError=true） | `runtime.py` L1790-1794（`{error: skip_reason}`, is_error=true） | 字段名不同（isError vs is_error），语义等价 | 已对齐 |
| 2.4.16 | execute 阶段 unknown tool 结果 | `agent-runtime.ts` L1481-1485（`Unknown tool: ${name}`） | `runtime.py` L1795-1799（`Unknown tool: ${name}`） | 完全一致 | 已对齐 |
| 2.4.17 | execute 阶段 exception 捕获 | `agent-runtime.ts` L1509-1516（catch → `{error: message}`, isError=true） | `runtime.py` L1854-1861（catch → `{error: 已重试 N 次: e}`, is_error=true） | Charles 因 runtime 层重试，错误信息含重试次数；Cline 无重试故错误信息为原始异常 | 弱对齐 |
| 2.4.18 | execute 阶段 AbortedError 传播 | `agent-runtime.ts` 无特殊处理（走 catch → isError=true） | `runtime.py` L1851-1853（`except AbortedError: raise` 重新抛出） | Charles 让中止异常向上传播由主循环处理 status="aborted"；Cline 将中止转为错误结果 | 语义不等价 |
| 2.4.19 | execute 阶段 emit_update 事件类型 | `agent-runtime.ts` L1499-1505（emit `tool-updated` 事件，含 toolCall+update） | `runtime.py` L2151-2202（emit_sync `TOOL_UPDATED` 事件，含 tool_call_id+tool_name+metadata） | Charles 用 emit_sync 同步发射解决时序问题（Phase 35.1）；字段结构等价 | 已对齐 |
| 2.4.20 | execute 阶段 started_at/ended_at/duration_ms | `agent-runtime.ts` L1467/1519-1520（Date 计算 durationMs） | `runtime.py` L1779/1863-1864（datetime 计算 duration_ms） | 完全一致，均传给 afterTool hooks | 已对齐 |
| 2.4.21 | tool-started 事件 emit | `agent-runtime.ts` L1468-1473 | `runtime.py` L1782-1787 | 字段结构等价（snapshot/iteration/tool_name/tool_call_id/input） | 已对齐 |
| 2.4.22 | tool-finished 事件 emit | `agent-runtime.ts` L1551-1557（含 message 字段） | `runtime.py` L1903-1910（含 output_for_event/is_error/duration_ms） | Cline emit 整个 message；Charles emit 序列化后的 output 字符串 + 额外字段 | 弱对齐 |

## 3. 重点差距详细说明

### 3.1 超时与重试：Cline 接口定义但不消费，Charles runtime 层统一实现

- **Cline**：`AgentTool` 接口（`shared/src/agent.ts` L177-186）定义了 `timeoutMs?` / `retryable?` / `maxRetries?` 三个可选字段，`createTool` 工厂（`shared/src/tools/create.ts` L125-127）给出默认值 `timeoutMs=30_000` / `retryable=true` / `maxRetries=3`。但在 `agent-runtime.ts::executePreparedTool`（L1464-1560）中 **完全没有引用这三个字段**，整个 `sdk/packages/agents/src/` 目录 grep `timeoutMs|retryable|maxRetries|withTimeout` 无任何匹配。这意味着 Cline 的 runtime 层不负责超时与重试，工具实现者需自行在 `execute()` 内部用 `AbortSignal.timeout()` 或类似机制实现。
- **Charles**：`BaseTool`（`base.py` L75-88）定义了 `timeout_ms` / `retryable` / `max_retries` 三个属性（默认 None / False / 0），`AgentRuntimeConfig`（`types.py` L543）定义了 `default_tool_timeout_ms=300_000`。`runtime.py::_execute_with_timeout_and_retry`（L1918-2042）在 runtime 层统一实现：
  - 超时：`asyncio.wait_for(tool.execute(...), timeout=timeout_ms/1000.0)`
  - 重试：`for attempt in range(max_retries + 1)`，退避 `delay = 0.2 * (2 ** attempt)` 秒
  - 不重试场景：`AbortedError`（用户中止）、schema 校验失败（`validation_errors` in output）
  - 重试耗尽：返回最后一个 is_error 结果或抛出最后一次异常
- **影响**：Charles 的实现是 Cline 接口契约的"提前实现"，功能上更完善（统一超时/重试避免每个工具重复实现），但与 Cline 的"工具自治"语义分歧。若未来 Charles 工具自行实现超时/重试，会与 runtime 层逻辑叠加导致超时时间翻倍或重试次数倍增。
- **残留性质**：非残留，属于 Charles 主动增强。

### 3.2 工具结果截断：双层 head+tail vs 单层 head-only

- **Cline**：双层截断。
  - Per-tool executor 层（`output-limits.ts`）：`MAX_COMMAND_OUTPUT_CHARS=48_000`、`MAX_READ_OUTPUT_CHARS=48_000`、`MAX_SEARCH_OUTPUT_CHARS=48_000`，`truncateCommandOutput`（L20-38）保留 head+tail，中间插入结构化截断标记 `[... output truncated: N chars total. Refine the command (grep, head, tail) to view the elided middle ...]`，含恢复指引。
  - MessageBuilder 层（`message-builder.ts` L28）：`DEFAULT_MAX_TOOL_RESULT_CHARS=8_000`，在构建 provider 请求时对超长 tool-result 再次截断，标记 `...[truncated N chars]...` 或 `...[truncated N chars to fit provider request budget]...`。
- **Charles**：单层截断。`runtime.py::_serialize_tool_output`（L2607-2632）在 emit `tool-finished` 事件时序列化 output，`max_tool_result_chars=16_000`（`types.py` L538），仅保留 head（`text[:max_chars]`），标记 `[输出已截断，原始长度 N 字符]`，无恢复指引。
- **影响**：
  1. 阈值不同：Cline 双阈值（8000/48000），Charles 单阈值（16000）；Charles 单次截断阈值介于 Cline 两层之间。
  2. 保尾策略不同：Cline 保 head+tail（tail 长度 `Math.max(1, maxChars - headLimit)`），Charles 仅保 head；长输出末尾的结论/错误信息在 Charles 中可能丢失。
  3. 截断标记不同：Cline 标记含恢复指引（"Refine the command..."），引导 LLM 改用 grep/head/tail；Charles 标记仅声明截断，无引导。
  4. 截断时机不同：Cline per-tool 截断在工具内部完成，MessageBuilder 截断在构建 provider 请求时完成；Charles 截断仅在 emit 事件时完成，**存入 message 的 output 未截断**（L1894 原样存入），截断只在事件展示层生效。这意味着 Charles 的 message 历史可能包含未截断的超长 output，撑爆 provider 上下文。
- **残留性质**：非残留，属于 Charles 实现不完整（message 历史未截断是潜在 bug）。

### 3.3 prepare 阶段 Cline 独有检查：inputParseError / toolSource.executionMode

- **Cline**：`prepareToolExecution`（L1334-1422）开头检查 `metadata.inputParseError`（L1347-1349）和 `toolSource.executionMode === "provider"`（L1351-1363），命中时设置 skipReason 跳过工具执行。
- **Charles**：`_prepare_tool_execution`（L1446-1594）无这两个检查。
  - inputParseError 等价处理：Charles 在 `_generate_assistant_message` 的 stream 组装阶段（L1062-1071）已拦截 invalid_tool_calls，生成错误 result message 让 LLM 下一轮看到，因此 prepare 阶段无需二次检查。
  - toolSource.executionMode：Charles 缺失 provider-side tool execution 跳过逻辑。Cline 该机制用于当工具由 provider 侧执行（如 OpenAI 的内置 web_search）时，runtime 跳过本地执行；Charles 无 provider-side execution 能力，缺失此检查符合当前架构。
- **影响**：inputParseError 等价处理已对齐；toolSource.executionMode 缺失是功能差距，但 Charles 短期无 provider-side execution 计划，影响可忽略。
- **残留性质**：非残留，属于架构差异。

### 3.4 execute 阶段 AbortedError 传播策略不同

- **Cline**：`executePreparedTool`（L1487-1516）的 `try { await tool.execute(...) } catch (error)` 捕获所有异常（包括 abort），统一转为 `{output: {error: message}, isError: true}`。中止不会向上传播，工具结果 message 正常存入历史。
- **Charles**：`_execute_prepared_tool`（L1828-1861）的 `except AbortedError: raise` 让中止异常向上传播，由主循环 catch 块处理 `status="aborted"`。中止时工具结果 message 不存入历史。
- **影响**：中止后 Cline 历史含错误工具结果（LLM 下一轮能看到中止原因），Charles 历史不含工具结果（中止直接结束运行）。Charles 的策略更干净（中止即停，不污染历史），但与 Cline 语义分歧。
- **残留性质**：非残留，属于设计选择差异。

### 3.5 afterTool hook stop 处理：applyStopControl vs RuntimeError

- **Cline**：`applyStopControl`（L1534）统一处理 hook 返回的 stop 控制，具体行为未在截取代码中体现但属于标准化封装。
- **Charles**：`after_result.stop` 时直接 `raise RuntimeError(after_result.reason)`（L1884），未区分用户 hook stop 与系统安全 stop。
- **影响**：Charles 的 after_tool stop 走 RuntimeError 路径，主循环 catch 后 `status="failed"`；而 before_tool stop 已区分 ControlledStopError（Stage 10.4）走 `status="completed"`。after_tool stop 缺少 ControlledStopError 区分，可能导致用户 hook 主动 stop 被误判为失败。
- **残留性质**：非残留，属于 Stage 10.4 未完全对齐 after_tool 分支。

## 4. nanobot 残留检查

在 `agent/runtime.py`、`agent/tools/base.py` 两个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）。

`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标说明，未影响工具执行流程的实现逻辑。重点文件清单：

| 文件 | 残留性质 | 是否影响工具执行流程 |
|------|---------|---------------------|
| `agent/runtime.py` | 无残留 | 不适用 |
| `agent/tools/base.py` | 无残留 | 不适用 |
| `agent/tools/__init__.py` L2 | docstring 标题对标说明 | 否（注释） |
| `agent/tools/exec_tool.py` L2-263 | 多处 docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | 多处 docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | 多处 docstring 对标 nanobot WebSearchTool | 否（注释） |
| `agent/skills/loader.py` L2-423 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/skills/registry.py` L2-184 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/providers/qwen.py` L21-406 | 多处 docstring 对标 nanobot openai_compat_provider | 否（注释） |
| `agent/server.py` L2-28 | docstring 对标 nanobot routes/chat.py | 否（注释） |
| `agent/session.py` L2-22 | docstring 对标 nanobot session_key | 否（注释） |
| `agent/context.py` L275 | 注释标注"[已废弃] nanobot 风格的额外段落" | 否（注释） |

> 注：上述残留全部为注释/docstring 性质，**无实现逻辑残留**。工具执行流程的核心方法（`_execute_tool_calls` / `_prepare_tool_execution` / `_execute_prepared_tool` / `_execute_with_timeout_and_retry` / `_serialize_tool_output`）均无 nanobot 命名或 nanobot 风格逻辑。

## 5. 修复建议

### P0（阻碍后续对比/集成）
1. **统一 tool result 截断策略**：当前 Charles `_serialize_tool_output` 仅在 emit 事件时截断，**存入 message 的 output 未截断**（`runtime.py` L1894 原样存入），长输出会撑爆 provider 上下文。建议在存入 message 前对 output 做截断，或对齐 Cline 的 MessageBuilder 层在构建 provider 请求时截断。同时考虑保 head+tail 策略，避免长输出末尾结论丢失。
2. **明确超时/重试责任归属**：Charles runtime 层统一超时/重试（`_execute_with_timeout_and_retry`）与 Cline 工具自治语义分歧。建议二选一：
   - 方案 A（对齐 Cline）：移除 runtime 层超时/重试，由工具自行实现（需确保每个工具有合理超时）。
   - 方案 B（保留 Charles 增强）：在文档中明确标注此为 Charles 主动增强，避免未来对齐时误删。

### P1（架构债务）
3. **补齐 afterTool hook 的 ControlledStopError 区分**：当前 `_execute_prepared_tool` 的 after_tool stop 走 RuntimeError（L1884），未像 before_tool 那样区分用户 hook stop（ControlledStopError）与系统安全 stop（RuntimeError）。建议对齐 Stage 10.4 的 before_tool 分支逻辑。
4. **补齐 toolSource.executionMode 检查占位**：若未来支持 provider-side tool execution，需在 `_prepare_tool_execution` 开头补齐 `metadata.toolSource.executionMode === "provider"` 检查。短期无此计划可暂缓。

### P2（功能增强）
5. **截断标记增加恢复指引**：对齐 Cline 的 `[... output truncated: N chars total. Refine the command (grep, head, tail) to view the elided middle ...]`，引导 LLM 改用分页/过滤命令查看超长输出。
6. **tool-finished 事件字段对齐**：Cline emit 整个 message（L1556），Charles emit 序列化后的 output 字符串 + 额外字段（L1903-1910）。建议统一字段结构，便于前端复用。

### P3（文档/规范）
7. **清理 nanobot 残留**：`agent/tools/`、`agent/skills/`、`agent/providers/`、`agent/server.py`、`agent/session.py`、`agent/context.py` 的 40+ 处 nanobot 历史对标注释，统一改为"Charles 历史实现"或直接删除。

## 6. 验证方法建议

1. **parallel 执行验证**：构造一次 assistant 消息包含两个 `read_files` tool_call 的输入，在 Charles 中将 `tool_execution="parallel"` 运行并记录耗时；与 `sequential` 模式对比，确认 `asyncio.gather` 实际并行执行。
2. **超时/重试验证**：构造一个 `timeout_ms=1000` / `retryable=True` / `max_retries=2` 的测试工具，内部 `asyncio.sleep(2000)` 模拟超时，运行并确认：a) 3 次尝试（1 + 2 重试）；b) 退避间隔约 0.2s / 0.4s；c) 最终返回 is_error=True 的超时结果。
3. **截断验证**：构造工具返回 20000 字符 output，确认：a) message 历史中 output 长度（当前未截断，预期 20000）；b) tool-finished 事件中 output 长度（预期 16000 + 截断标记）。
4. **abort 传播验证**：在工具执行中调用 `runtime.abort()`，确认：a) AbortedError 向上传播；b) 主循环 catch 后 `status="aborted"`；c) 工具结果 message 未存入历史。
5. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/` 并统计行数，建立基线（当前 55 行）；后续修复后确认重点文件（runtime.py / base.py / types.py）无残留。
