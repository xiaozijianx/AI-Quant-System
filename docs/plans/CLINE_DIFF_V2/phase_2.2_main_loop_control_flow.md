# Phase 2.2 主循环 run() 控制流对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）`agent-runtime.ts::execute()`（L595-794）与 Charles（Python）`agent/runtime.py::run()`（L521-817）的主循环控制流。两边主循环骨架（while → throwIfAborted → iteration++ → emit turn-started → generate → emit message-added → tool_calls 分支 → executeToolCalls → findCompletingToolMessage → emit turn-finished）在语义上高度对齐，关键差异集中在三处：

1. **异常分类与 status 映射**：Cline 用单一 catch 块 + `ControlledStopError instanceof` 判定，将 ControlledStopError 归为 `status="aborted"`；Charles 拆分为两个 except 块，将 `ControlledStopError` 归为 `status="completed"` + `finish_reason="controlled_stop"`，语义不一致。
2. **before_run hook stop 处理**：Cline 的 `callBeforeRunHooks` 通过 `applyStopControl` 抛 `ControlledStopError`（受控停止）；Charles 的 `_call_before_run_hooks` 直接抛 `RuntimeError`（被归为失败），与 before_tool hook 的 ControlledStopError 路径不一致。
3. **Charles 主循环扩展项**：Charles 在 Cline 基础上新增了 `invalid_tool_calls` 错误结果注入、`_check_repeated_tool_failures` 死循环检测、`_initial_messages` 注入、`_completion_reminder_injected` 预注入、`prepare_turn_input` / `format_user_input_block` 钩子、历史 `messages` 参数注入等扩展，Cline 无对应实现。

`agent/runtime.py` 中 **未发现** `nanobot` 字符串残留（注释/实现均无）。

## 2. 逐项对比表

| # | 对比项 | Cline 行号 | Charles 行号 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.2.1 | while 条件 | L629-632 | L626-629 | 两边均为 `maxIterations is None/undefined OR iteration < maxIterations`；Cline 无 `!aborted` 条件（靠循环内 throwIfAborted 退出），Charles 同样无 `!_aborted` 条件。条件顺序与逻辑一致 | 对齐 |
| 2.2.2 | throwIfAborted 调用点 | L633（主循环）+ L855/L862/L892/L914/L1087（generateAssistantMessage 内） | L630（主循环）+ L910（stream 循环）+ L1000（异常 handler 内 _aborted 检查） | Cline 主循环 1 处 + generateAssistantMessage 5 处；Charles 主循环 1 处 + stream 循环 1 处 + 异常 handler 1 处。Cline 检查点更密集 | 弱对齐 |
| 2.2.3 | emit run_started 时机 | L611（after callBeforeRunHooks L610） | L562（after _call_before_run_hooks L559） | 顺序一致：hooks → emit run_started。Charles 在 emit 后还有 initial_messages 注入与 completion_reminder 预注入，Cline 无 | 对齐 |
| 2.2.4 | beforeRunHooks stop 处理 | L796-803 + L1661-1671（applyStopControl 抛 ControlledStopError） | L2080-2086（直接抛 RuntimeError） | **关键差异**：Cline before_run stop → ControlledStopError → catch 中 status="aborted"；Charles before_run stop → RuntimeError → except Exception 中 status="failed"。Charles before_run 与 before_tool（L1509 抛 ControlledStopError）路径不一致 | 语义不等价 |
| 2.2.5 | addUserMessage 位置 | L613-620（normalizeInput 循环 push + emit message-added） | L619-621（_normalize_input 循环 push + emit message_added） | Charles 在 push 前额外调用 `_call_prepare_turn_input_hooks`（L609）与 `_call_format_user_input_block_hooks`（L617），Cline 无对应钩子。Charles 还支持 `messages` 历史参数静默注入（L601-603，不触发 emit） | 弱对齐 |
| 2.2.6 | generateAssistantMessage 返回 | L642 `{ message, finishReason }` | L636 `tuple[AgentMessage, str]` (message, finish_reason) | 结构等价，仅类型表达差异。Charles 的 `_generate_assistant_message` 内部含 `consume_pending_user_message` 逻辑（L859-882），Cline 同样在 `generateAssistantMessage` 内（L840-851） | 对齐 |
| 2.2.7 | emit message_added 时机 | L660-664（push 后立即 emit）+ L710-714（tool message 循环 emit） | L660（push 后立即 emit）+ L734（tool message 循环 emit） | 两边均为立即 emit，非 batch。Charles 额外在 invalid_tool_messages 注入时 emit（L690） | 对齐 |
| 2.2.8 | 无 tool_calls 分支 | L681-704 | L693-718 | **差异**：Cline 先 emit turn-finished(toolCallCount=0)，再取 `getCompletionReminderMessages()`（合并 requireCompletionTool + completionGuard），有 reminder 则 addUserReminderMessage + continue，无则 finishRun。Charles 先判断 `policy.require_completion_tool`，True 时 `_build_completion_reminder` 注入 + emit turn-finished + continue，False 时 emit turn-finished + finish_run。Charles 的 reminder 文本为硬编码中文兜底，Cline 为英文模板 | 弱对齐 |
| 2.2.9 | executeToolCalls 调用 | L706 `executeToolCalls(toolCalls)`，支持 `toolExecution: "parallel" \| "sequential"`（L1299-1309） | L721 `_execute_tool_calls(tool_calls)`，仅 sequential | **差异**：Cline 支持 parallel（Promise.all）与 sequential 两种模式；Charles 仅 sequential。Charles 额外处理 invalid_tool_calls 拼接（L724-725）与 `_check_repeated_tool_failures`（L728） | 弱对齐 |
| 2.2.10 | findCompletingToolMessage | L1312-1332 | L2048-2074 | 两边逻辑一致：遍历 toolCalls → 检查 `lifecycle.completesRun` → 匹配 toolCallId → 检查 `!isError`。Cline 用 `tools.get(toolCall.toolName)`，Charles 用 `self._tools.get(tool_call.tool_name)` | 对齐 |
| 2.2.11 | completes_run 后 finish | L727-738 `finishRun("completed", finalAssistantMessage, textFromToolMessage(...) \|\| undefined)` | L744-747 `_finish_run("completed", final_assistant_message, output_text)` | status 均为 "completed"，均调用 afterRunHooks + emit run-finished + return。Charles 的 `output_text` 来自 `text_from_tool_message(completing_message) or None`，与 Cline `|| undefined` 等价 | 对齐 |
| 2.2.12 | emit turn_finished 时机 | L682-687（无 tool_calls 分支）+ L716-721（有 tool_calls 分支） | L704-706/L710-712（无 tool_calls 分支）+ L736-738（有 tool_calls 分支） | 两边每轮均 emit turn-finished。Charles 在无 tool_calls + require_completion_tool 分支中 emit turn-finished 后 continue（L704-707），Cline 同样（L682-694） | 对齐 |
| 2.2.13 | max_iterations 超限 | L742-744 `throw new Error(...)` | L750-752 `raise RuntimeError(...)` | 两边均抛异常，进入 catch/except 后 status="failed"。Cline 走单一 catch（isControlledStop=false, isAborted=false → failed）；Charles 走 `except Exception`（_aborted=False → failed） | 对齐 |
| 2.2.14 | 异常捕获范围 | L745-790 单一 catch 块 | L754-813 两个 except 块（ControlledStopError + Exception） | **关键差异**：Cline 单 catch 内用 `instanceof ControlledStopError` 判定 → isAborted=true → status="aborted"，emit run-finished；Charles 单独捕获 ControlledStopError → status="completed" + finish_reason="controlled_stop"，emit run-finished。语义不同：Cline 视为 aborted，Charles 视为 completed | 语义不等价 |
| 2.2.15 | finally 清理 | L791-793 `this.abortController = undefined` | L815-817 `self._aborted = False; self._abort_reason = ""` | Cline 清空 abortController 引用；Charles 重置 abort 标志位。Charles 的 `_abort_controller` 在 run 开始时 reset（L549），finally 中未额外处理 | 弱对齐 |
| 2.2.16 | consumePendingUserMessage | L840-851（在 generateAssistantMessage 内，iteration > 1 时调用） | L859-882（在 _generate_assistant_message 内，iteration > 1 时调用） | 逻辑一致。Cline 回调无参数 `consumePendingUserMessage()`；Charles 传 `session_id` `config.consume_pending_user_message(session_id)`。两边均 emit message-added | 对齐 |
| 2.2.17 | iteration 自增时机 | L635（throwIfAborted 后、emit turn-started 前） | L632（_throw_if_aborted 后、emit turn_started 前） | 完全一致 | 对齐 |

## 3. 重点差距详细说明

### 3.1 ControlledStopError 的 status 映射不一致（语义不等价）

- **Cline**（L745-790）：单一 catch 块，通过 `isControlledStop = normalized instanceof ControlledStopError` 判定，`isAborted = abortController.signal.aborted || isControlledStop`，`status = isAborted ? "aborted" : "failed"`。即 ControlledStopError → status="aborted"，随后 emit `run-finished`（非 run-failed）。
- **Charles**（L754-813）：拆分为两个 except 块。`except ControlledStopError`（L754-782）设 `status="completed"`、`finish_reason="controlled_stop"`、emit `run_finished`；`except Exception`（L784-813）按 `_aborted` 判定 `status="aborted"/"failed"`。
- **影响**：同一个 ControlledStopError，Cline 报告为 aborted，Charles 报告为 completed。前端/调用方若按 status 判断是否展示"被规则拦截"或"正常完成"，会得到不同语义。Charles 的 Stage 10.4 注释明确说明"status=completed，finish_reason=controlled_stop，前端显示'被规则拦截'"，这是有意的本地化设计，但与 Cline 语义偏离。

### 3.2 before_run hook stop 路径不一致（Charles 内部不一致 + 与 Cline 不一致）

- **Cline**（L796-803, L1661-1671）：`callBeforeRunHooks` 对每个 hook 调用 `applyStopControl(control)`，后者在 `control.stop` 时抛 `ControlledStopError`。进入 catch 后归为 aborted。
- **Charles**（L2080-2086）：`_call_before_run_hooks` 在 `control.stop` 时直接 `raise RuntimeError(control.reason or "stopped by before_run hook")`。RuntimeError 不被 `except ControlledStopError` 捕获，落入 `except Exception`，因 `_aborted=False` → status="failed"。
- **Charles 内部不一致**：`before_tool` hook stop（L1505-1512）在 `_aborted=False` 时抛 `ControlledStopError`（status=completed），但 `before_run` hook stop 抛 RuntimeError（status=failed）。同为 hook 主动 stop，处理路径不同。
- **影响**：用户配置的 before_run hook 若调用 stop，会被 Charles 当作失败，而 Cline 当作受控停止。建议统一为 ControlledStopError 路径。

### 3.3 Charles 主循环扩展项（Cline 无对应）

Charles 在 Cline 主循环骨架上新增以下扩展，Cline 完全无对应实现：

| 扩展项 | Charles 位置 | 说明 |
|--------|-------------|------|
| `_initial_messages` 注入 | L568-583 | 首次 run 且 messages 为空时注入 config.initial_messages，对标 Cline `AgentRuntimeConfig.initialMessages`（注释声称对标，但 Cline execute() 中未见注入逻辑） |
| `_completion_reminder_injected` 预注入 | L590-597 | require_completion_tool=True 时，循环前预注入 system reminder，标记位避免重复注入 |
| 历史 `messages` 参数静默注入 | L601-603 | 支持会话续接，不触发 message_added 事件 |
| `_call_prepare_turn_input_hooks` | L609 | Phase 23 新增，对标 Cline `prepareTurnInput`（Cline 源码中未找到同名函数） |
| `_call_format_user_input_block_hooks` | L617 | Phase 23 新增，对标 Cline `formatUserInputBlock`（Cline 源码中未找到同名函数） |
| `invalid_tool_calls` 提取与错误结果注入 | L655, L683-690, L724-725 | Phase 26 新增，从 assistant 消息 metadata 提取无效工具调用，生成错误结果让 LLM 下一轮看到 |
| `_check_repeated_tool_failures` | L728 | Phase 26 新增，检测重复失败死循环 |

- **影响**：`prepare_turn_input` 与 `format_user_input_block` 钩子的对标说明声称"对标 Cline"，但在 `agent-runtime.ts` 中未找到对应函数实现，可能对标的是 Cline 其他层（如 `core` 或 `apps`），需在后续 Phase 核实。`invalid_tool_calls` 与 `_check_repeated_tool_failures` 是 Charles 独有的健壮性增强。

### 3.4 无 tool_calls 分支的 completion reminder 逻辑差异

- **Cline**（L681-704）：
  1. emit `turn-finished`（toolCallCount=0）
  2. 调用 `getCompletionReminderMessages()`，合并 `getCompletionToolReminderMessage()`（检查 `requireCompletionTool`）与 `completionPolicy?.completionGuard?.()`
  3. 有 reminder → 对每条 `addUserReminderMessage` → continue
  4. 无 reminder → `finishRun("completed")` → afterRunHooks → emit run-finished → return

- **Charles**（L693-718）：
  1. 检查 `policy.require_completion_tool`
  2. True → `_build_completion_reminder(policy)`（先调 `completion_guard()`，失败则硬编码中文兜底）→ 追加 user message + emit message_added → emit turn-finished → continue
  3. False → emit turn-finished → `_finish_run("completed")` → afterRunHooks → emit run-finished → return

- **差异**：
  - Cline 先 emit turn-finished 再判 reminder；Charles 先判 policy 再 emit turn-finished（两条分支各自 emit）。
  - Cline 的 reminder 合并了 `requireCompletionTool` 检查与 `completionGuard` 调用；Charles 仅在 `require_completion_tool=True` 时进入 reminder 分支，`completion_guard` 在 `_build_completion_reminder` 内调用。
  - Cline reminder 为英文模板；Charles 兜底为中文硬编码（"你必须调用完成工具..."）。
  - Charles 额外有循环前的 `_completion_reminder_injected` 预注入（L590-597），Cline 无预注入，仅每轮失败后注入。

### 3.5 finally 清理差异

- **Cline**（L791-793）：`this.abortController = undefined` — 清空 AbortController 引用，下次 execute 时重建。
- **Charles**（L815-817）：`self._aborted = False; self._abort_reason = ""` — 重置标志位，但 `_abort_controller` 不在此重置（它在 run 开始时 L549 `reset()`）。
- **影响**：Charles 的 `_abort_controller` 是长期持有对象（通过 reset 复用），Cline 的 `abortController` 是每次 execute 重建。若中途 abort 后再次 run，Charles 的 `_abort_controller` 状态依赖 reset 调用，Cline 则天然干净。

## 4. nanobot 残留检查

在 `agent/runtime.py`（本次对比的重点文件）中 **未发现** `nanobot` 字符串残留（注释与实现逻辑均无）。

`agent/` 目录其他文件中仍存在多处 `nanobot` 注释残留（与 Phase 1.1 报告一致），但不影响 runtime.py 主循环控制流对比。重点文件清单：

| 文件 | nanobot 残留 | 性质 |
|------|-------------|------|
| `agent/runtime.py` | 无 | — |
| `agent/server.py` | L2, L4, L28 | 注释残留 |
| `agent/providers/qwen.py` | L21, L49, L116, L214, L253, L385, L406 | 注释残留 |
| `agent/tools/exec_tool.py` | L2, L8-10, L18-19, L41, L57, L123, L165, L181, L263 | 注释残留 |
| `agent/tools/file_tools.py` | L2, L7, L12, L27, L115, L130, L165 | 注释残留 |
| `agent/tools/web_tool.py` | L2, L9-10, L13, L28, L111, L165 | 注释残留 |
| `agent/skills/loader.py` | L2, L29, L96, L167, L222, L392, L423 | 注释残留 |
| `agent/skills/registry.py` | L2, L20, L100, L184 | 注释残留 |
| `agent/skills/__init__.py` | L2, L23 | 注释残留 |
| `agent/skills/skill_tool.py` | L18 | 注释残留 |
| `agent/session.py` | L2, L22 | 注释残留 |
| `agent/context.py` | L275 | 注释残留（标注"已废弃"） |
| `agent/tools/__init__.py` | L2 | 注释残留 |

> 上述残留均为注释/docstring 层面的历史对标说明，**非实现逻辑残留**。runtime.py 主循环控制流中无任何 nanobot 实现逻辑残留。

## 5. 修复建议

### P0（语义不一致，阻碍行为对齐）

1. **统一 before_run hook stop 路径**：将 `agent/runtime.py::_call_before_run_hooks`（L2085-2086）中的 `raise RuntimeError(...)` 改为 `raise ControlledStopError(reason=control.reason or "stopped by before_run hook", source="hook")`，与 before_tool hook（L1509）路径一致，也对齐 Cline `applyStopControl` 抛 ControlledStopError 的行为。
2. **明确 ControlledStopError 的 status 语义**：当前 Charles 将 ControlledStopError 归为 `status="completed"`（L759），Cline 归为 `status="aborted"`（L749-750）。需决策：
   - 方案 A（对齐 Cline）：将 Charles `except ControlledStopError` 块的 status 改为 "aborted"，与 Cline 一致。
   - 方案 B（保留 Charles 语义）：在文档中明确标注此为有意偏离，并在 AGENT_COMPARISON_PLAN 中记录。
   建议选 A 以降低跨实现调试成本。

### P1（健壮性与对齐）

3. **补齐 throwIfAborted 检查点密度**：Cline 在 `generateAssistantMessage` 内有 5 处 throwIfAborted（L855, L862, L892, L914, L1087），Charles 在 `_generate_assistant_message` 的 stream 循环内仅 1 处（L910）。建议在 before_model hooks 后、after_model hooks 后、stream 结束后各补一处 `_throw_if_aborted()`，对齐 Cline 的中止响应灵敏度。
4. **对齐 completion reminder 顺序**：将 Charles 无 tool_calls 分支（L693-718）调整为先 emit turn-finished 再判 reminder，与 Cline（L682-694）一致。当前 Charles 在 require_completion_tool 分支中 emit turn-finished 后 continue（L704-707），与 Cline 一致；但不要求分支的 emit 位置（L710-712）与 Cline 略有差异，需核对。

### P2（功能增强）

5. **补齐 parallel 工具执行**：Charles `_execute_tool_calls` 仅 sequential，Cline 支持 `toolExecution: "parallel"`。建议基于 `BaseTool.read_only` 属性实现并行调度（已在 Phase 1.1 报告中提及）。
6. **核实 prepare_turn_input / format_user_input_block 对标声明**：Charles L606-607 与 L614-616 声称对标 Cline `prepareTurnInput` / `formatUserInputBlock`，但在 `agent-runtime.ts` 中未找到。需确认是否对标 Cline 其他层（core/apps），或为 Charles 独有扩展，并修正注释。

### P3（文档/规范）

7. **清理 nanobot 注释残留**：按 Phase 1.1 报告建议，逐步替换为"Charles 历史实现"或删除。runtime.py 已无残留，重点清理 tools/、skills/、providers/ 目录。
8. **补充控制流图**：在报告中补充两边的控制流图（mermaid 或文字版），逐节点标注行号，便于后续 review。

## 6. 验证方法建议

1. **控制流图逐节点对比**：绘制 Cline execute() 与 Charles run() 的控制流图（while → abort → iteration++ → emit → generate → tool_calls 分支 → execute → completing → finish），逐节点核对行号与顺序。
2. **ControlledStopError 边界测试**：构造 before_run hook 返回 `stop=True` 的用例，对比两边 status（Cline 应为 "aborted"，Charles 当前为 "failed"）。再构造 before_tool hook 返回 `stop=True` 的用例，对比两边 status（Cline "aborted"，Charles 当前 "completed"）。
3. **max_iterations 边界测试**：设置 `max_iterations=1`，构造 LLM 每轮都请求工具调用的场景，验证两边均在第 1 轮后抛 "exceeded maxIterations" 异常，status="failed"。
4. **abort 中途响应测试**：在 stream 循环中调用 `abort()`，对比两边 throwIfAborted 响应时机。Cline 应在 L855/L862/L892/L914/L1087 任一检查点抛出；Charles 应在 L910 stream 循环检查点抛出。
5. **consumePendingUserMessage 测试**：设置 `consume_pending_user_message` 回调返回非空文本，iteration=2 时验证两边均追加 user message 到 state.messages 与 request.messages，并 emit message-added。
6. **completion reminder 测试**：设置 `require_completion_tool=True`，构造 LLM 不调用工具的响应，验证两边均注入 reminder 并 continue 下一轮。对比 reminder 文本内容（Cline 英文 vs Charles 中文兜底）。
7. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/runtime.py` 确认无残留；对 `agent/` 其他文件建立基线行数，后续清理后回归。

---

*报告生成时间：2026-07-28*  
*覆盖文件：AGENT_COMPARISON_PLAN_V2.md §P2.2、cline sdk/packages/agents/src/agent-runtime.ts L595-794 + L796-809 + L840-852 + L1252-1269 + L1291-1332 + L1588-1603 + L1661-1671、Charles agent/runtime.py L405-423 + L521-817 + L1490-1512 + L2048-2074 + L2080-2124 + L2204-2240 + L2308-2365 + L2675-2680*
