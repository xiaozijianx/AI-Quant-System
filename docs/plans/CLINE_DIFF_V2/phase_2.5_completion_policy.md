# Phase 2.5 completion_policy + completes_run 对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在运行完成策略上的差异，覆盖 `CompletionPolicy` 字段定义、`require_completion_tool` 触发逻辑、`completion_guard` 回调契约、`completes_run` 工具检测条件、`completes_run` 命中后 status 处理、循环前 reminder 预注入六个维度。

总体结论：Charles 已将 Cline 的"完成策略 + 终止工具检测"核心语义对齐到函数级，`CompletionPolicy` 字段结构、`completes_run` 检测算法、命中后 `finishRun("completed")` 行为均与 Cline 等价。但存在三处显著分歧：

1. **循环前预注入 reminder 不 emit `message-added` 事件**（最重要分歧）：Cline `addUserReminderMessage`（agent-runtime.ts L584-593）push 消息后 emit `message-added` 事件，前端可感知预注入的 reminder；Charles `_inject_completion_reminder`（runtime.py L2323-2346）只 push 消息到 `state.messages`，**不 emit `message-added` 事件**，前端无法感知，且 reminder 不会出现在事件流历史中。这导致前端展示与实际 message 历史不一致。
2. **reminder 内容策略不同**：Cline 每轮 reminder（包括预注入和兜底）都列出所有 `completesRun=true` 的工具名（sort 后逗号分隔，L567-575）；Charles 预注入只引用第一个 completing tool（`_find_completing_tool_name` L2308-2321 多个时取第一个），兜底 reminder（`_build_completion_reminder` L2348-2364）完全不包含工具名，只输出"你必须调用完成工具..."的通用文案。多 completing tool 场景下信息量不等价。
3. **completion_guard 异常处理策略不同**：Cline `completionGuard?.()`（L580）不捕获异常，guard 抛出的异常会向上传播终止运行；Charles `policy.completion_guard()`（L2354-2360）try/except 捕获异常，warning 日志后降级到默认中文文案继续运行。Charles 的容错性更好但与 Cline 语义分歧——Cline 期望 guard 是"纯函数"，异常应传播；Charles 把 guard 当成"可能失败的外部回调"。

`nanobot` 残留检查结论：在 `agent/types.py`、`agent/runtime.py` 两个 P2.5 重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）。其他文件的 nanobot 残留均为注释/docstring 层面的历史对标注说明，与 P2.4 报告结论一致，不影响 completion_policy 与 completes_run 的实现逻辑。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.5 章节定义的 6 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.5.1 | CompletionPolicy 字段 | `agent.ts` L430-433（内联匿名对象 `{ requireCompletionTool?, completionGuard? }`） | `types.py` L489-503（独立 `CompletionPolicy` dataclass，`require_completion_tool: bool` + `completion_guard: Callable[..., str \| None] \| None`） | 字段完整性一致（2 字段）；实现形式不同（Cline 内联类型 vs Charles 独立 dataclass）；命名风格不同（camelCase vs snake_case）；Charles dataclass 更利于复用与测试 | 已对齐 |
| 2.5.2 | require_completion_tool 逻辑 | `agent-runtime.ts` L681-695（`getCompletionReminderMessages()` 返回数组 = [terminalToolNames reminder, completionGuard()] filter Boolean；数组非空时遍历 `addUserReminderMessage` 注入并 continue；数组空时 `finishRun("completed")`） | `runtime.py` L693-707（`_build_completion_reminder(policy)` 返回单字符串 = completion_guard() 或默认中文文案；非空时 push + emit message-added 并 continue；require_completion_tool=True 时永远返回非空故一定 continue） | ① reminder 数量：Cline 可能注入 2 条（toolNames + guard），Charles 只注入 1 条；② reminder 内容：Cline 含工具名列表，Charles 兜底不含工具名；③ 异常处理：Cline 不捕获 guard 异常，Charles 捕获降级；④ 语言：Cline 英文，Charles 中文 | 弱对齐 |
| 2.5.3 | completion_guard 回调 | `agent-runtime.ts` L580（`this.config.completionPolicy?.completionGuard?.()` 调用，无 try/catch，异常向上传播） | `runtime.py` L2354-2360（`policy.completion_guard()` 调用，try/except 捕获异常，warning 日志后降级到默认文案 `"你必须调用完成工具..."`） | Charles 额外有异常捕获和降级逻辑；Cline 让异常传播终止运行。Charles 容错性更好但与 Cline "guard 是纯函数"语义分歧 | 语义不等价 |
| 2.5.4 | completes_run 检查 | `agent-runtime.ts` L1312-1332（`findCompletingToolMessage` 同步方法；遍历 toolCalls，`this.tools.get(toolName)?.lifecycle?.completesRun !== true` 跳过，找 toolMessages[index] 中 `part.type === "tool-result" && part.toolCallId === toolCall.toolCallId && !result.isError` 返回） | `runtime.py` L2048-2074（`_find_completing_tool` 同步方法；遍历 tool_calls，`tool is None` 跳过，`lifecycle is None or not lifecycle.completes_run` 跳过，`i >= len(tool_messages)` 跳过，找 `isinstance(part, ToolResultPart) && part.tool_call_id == tool_call.tool_call_id && not part.is_error` 返回） | Charles 额外有 `tool is None` 和 `i >= len(tool_messages)` 显式边界检查；Cline 用 `?.` 链式安全访问隐式处理。语义等价 | 已对齐 |
| 2.5.5 | completes_run 后 status | `agent-runtime.ts` L727-738（`finishRun("completed", finalAssistantMessage, textFromToolMessage(terminalToolMessage) \|\| undefined)` → `callAfterRunHooks(result)` → emit `run-finished` → return result） | `runtime.py` L742-747（`_finish_run("completed", final_assistant_message, output_text)` → `_call_after_run_hooks(result)` → emit `make_run_finished` → return result） | 完全对齐：status 同为 `"completed"`，均调用 after_run hooks，均 emit run-finished，均 return result；output_text 提取方式等价（`textFromToolMessage` vs `text_from_tool_message`） | 已对齐 |
| 2.5.6 | reminder 循环前预注入 | `agent-runtime.ts` L622-625（`getCompletionToolReminderMessage()` 返回含所有 terminalToolNames 的英文 reminder → `addUserReminderMessage()` 内部 push + emit `message-added`；每次 `execute()` 都重新注入，无幂等标记） | `runtime.py` L585-597 + L2323-2346（`_find_completing_tool_name()` 取第一个 completing tool → `_inject_completion_reminder()` **只 push 不 emit message-added**；用 `_completion_reminder_injected` 标记保证只注入一次，`restore()` 时重置） | ① emit 事件：Cline emit message-added，Charles 不 emit（前端无法感知）；② 幂等性：Charles 用标记防重复（适合多次 run 共享 state 架构），Cline 无标记（每次 execute 重置 state 自然不重复）；③ 工具名：Cline 列出所有 completesRun 工具，Charles 只取第一个；④ 位置：Charles 在历史消息注入前，Cline 在 input 消息注入后；⑤ 语言：Cline 英文，Charles 中文 | 弱对齐 |

## 3. 重点差距详细说明

### 3.1 预注入 reminder 不 emit `message-added` 事件（对应对比项 2.5.6）

- **Cline 设计**：`execute()` 主循环开始前（L622-625）调用 `getCompletionToolReminderMessage()` 获取 reminder，若非空则调用 `addUserReminderMessage(reminder)`（L584-593）。`addUserReminderMessage` 内部：
  1. `createMessage("user", [{ type: "text", text }])` 创建 user 消息
  2. `this.state.messages.push(reminderMessage)` 推入历史
  3. `await this.emit({ type: "message-added", snapshot, message: reminderMessage })` 发射事件
  - 前端通过 `message-added` 事件可实时感知预注入的 reminder，并在 UI 中渲染。
- **Charles 设计**：`run()` 主循环开始前（L585-597）调用 `_find_completing_tool_name()` 取得 completing tool 名，调用 `_inject_completion_reminder(completing_tool)`（L2323-2346）。该方法：
  1. 构造中文 reminder 文本 `"[System Reminder] 本任务必须以 {completing_tool} 工具结束..."`
  2. `create_text_message(MessageRole.USER, reminder_text)` 创建 user 消息
  3. `self._state.messages.append(reminder_msg)` 推入历史
  4. `self._logger.info(...)` 日志记录
  - **未调用 `self._emit(make_message_added(...))`**，前端无法感知预注入的 reminder。
- **影响**：
  1. 前端展示与实际 message 历史不一致：message 历史中有 reminder，但前端事件流中没有对应 `message_added` 事件，前端展示的对话列表会"少一条"。
  2. 持久化层不一致：若前端基于事件流构建本地消息列表，restore 时从 `state.messages` 重新加载会发现多出一条 reminder，与前端展示不符。
  3. 调试困难：开发者查看事件流日志看不到预注入的 reminder，但 LLM 第一轮请求中确实包含该 reminder，排查时容易困惑。
- **残留性质**：非残留，属于 Stage 10.3 (B9) 实现遗漏。Charles 的 `_inject_completion_reminder` 注释明确说"对标 Cline callBeforeRunHooks 中预注入 reminder 的逻辑"，但漏掉了 emit 事件步骤。

### 3.2 reminder 内容策略：工具名列表 vs 单工具名/无工具名（对应对比项 2.5.2 + 2.5.6）

- **Cline 设计**：`getCompletionToolReminderMessage()`（L567-575）调用 `getRequiredCompletionToolNames()`（L557-565）从 `this.tools` 中 filter 出所有 `lifecycle.completesRun === true` 的工具名，**sort 后逗号分隔**拼接成英文 reminder：
  ```
  [SYSTEM] This run is not complete until you call one of these terminal completion tools: attempt_completion, submit_and_exit. Continue working if requirements are not met. If the task is complete, call the appropriate terminal completion tool now.
  ```
  - 该 reminder 在两个位置使用：a) 预注入（L622-625）；b) 无 tool_calls 兜底（L688-695 通过 `getCompletionReminderMessages` 数组返回）。两处都包含完整工具名列表。
- **Charles 设计**：分两个路径：
  1. **预注入路径**（L585-597 + L2323-2346）：`_find_completing_tool_name()`（L2308-2321）从 `self._tools` 中查找 `lifecycle.completes_run=True` 的工具，**多个时取第一个**（与 Cline sort 后列全部不同），注入中文 reminder `"[System Reminder] 本任务必须以 {completing_tool} 工具结束..."`
  2. **兜底路径**（L693-707 + L2348-2364）：`_build_completion_reminder(policy)` 优先调用 `completion_guard()`，否则返回默认中文文案 `"你必须调用完成工具（如 attempt_completion 或 submit_and_exit）来结束本次任务..."`，**完全不包含实际工具名**（仅举例 attempt_completion / submit_and_exit）。
- **影响**：
  1. 多 completing tool 场景信息丢失：若 agent 注册了 `attempt_completion` + `submit_and_exit` + `plan_mode` 三个 completesRun 工具，Cline reminder 列出全部三个，LLM 可选择合适的；Charles 预注入只列第一个（如 `attempt_completion`），兜底不列任何，LLM 可能不知道还有其他选项。
  2. 兜底 reminder 信息量不足：Charles 兜底文案是固定中文，不含实际注册的工具名，LLM 可能尝试调用不存在的工具名（如 `attempt_completion` 但实际只注册了 `submit_and_exit`）。
  3. 一致性：Cline 预注入与兜底 reminder 内容一致（都含工具名列表）；Charles 预注入含单工具名，兜底不含工具名，两路径不对齐。
- **残留性质**：非残留，属于 Charles 实现简化。Charles 注释说"与 Cline 行为一致"但实际多工具处理与 Cline 不一致。

### 3.3 completion_guard 异常处理：传播 vs 捕获降级（对应对比项 2.5.3）

- **Cline 设计**：`getCompletionReminderMessages()`（L577-582）调用 `this.config.completionPolicy?.completionGuard?.()`，**无 try/catch**。若 guard 抛异常，异常向上传播到 `execute()` 的 catch 块（L745-790），被捕获后 `status="failed"`，emit `run-failed` 事件，运行终止。
- **Charles 设计**：`_build_completion_reminder()`（L2348-2364）调用 `policy.completion_guard()`，**try/except 捕获所有 Exception**：
  ```python
  try:
      guard_text = policy.completion_guard()
      if guard_text:
          return guard_text
  except Exception as e:
      logger.warning(f"completion_guard 执行失败: {e}")
  return "你必须调用完成工具..."  # 降级到默认文案
  ```
  - guard 抛异常时仅 warning 日志，降级到默认中文文案继续运行。
- **影响**：
  1. 语义分歧：Cline 把 guard 当作"纯函数"，异常是 bug 应传播终止；Charles 把 guard 当作"可能失败的外部回调"，异常应容错降级。
  2. 调试体验：Cline guard 异常会立即终止运行并在 `run-failed` 事件中暴露；Charles guard 异常被吞掉（仅 warning 日志），开发者可能不知道 guard 出过错。
  3. 可用性：Charles 的容错策略对生产环境更友好（guard 失败不影响 agent 继续运行），但偏离 Cline 设计意图。
- **残留性质**：非残留，属于 Charles 主动增强的容错策略。

## 4. nanobot 残留检查

### 检查范围

P2.5 重点文件为 `agent/types.py`（CompletionPolicy dataclass 定义）和 `agent/runtime.py`（completion_policy 逻辑、completes_run 检查、reminder 注入）。

### 重点文件检查结论

| 文件 | 残留性质 | 是否影响 completion_policy / completes_run 实现 |
|------|---------|----------------------------------------------|
| `agent/types.py` | **无残留** | 不适用 |
| `agent/runtime.py` | **无残留** | 不适用 |

`agent/types.py` 和 `agent/runtime.py` 中 grep `nanobot` 均无任何匹配，CompletionPolicy dataclass、ToolLifecycle dataclass、`_find_completing_tool` / `_find_completing_tool_name` / `_inject_completion_reminder` / `_build_completion_reminder` / `_finish_run` 等核心方法均无 nanobot 命名或 nanobot 风格逻辑。

### 其他文件残留（与 P2.4 报告一致，仅供完整性参考）

`agent/` 其他文件的 nanobot 残留全部为注释/docstring 层面的历史对标注说明，不影响 P2.5 对比项的实现逻辑：

| 文件 | 残留性质 | 是否影响 completion_policy / completes_run |
|------|---------|------------------------------------------|
| `agent/tools/__init__.py` L2 | docstring 标题对标说明 | 否（注释） |
| `agent/tools/exec_tool.py` L2-263 | 多处 docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | 多处 docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | 多处 docstring 对标 nanobot WebSearchTool | 否（注释） |
| `agent/tools/attempt_completion.py` / `submit_and_exit.py` / `plan_mode.py` | docstring 对标 Cline 同名工具的 `lifecycle.completesRun` | 否（注释，对标 Cline 而非 nanobot） |
| `agent/skills/loader.py` L2-423 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/skills/registry.py` L2-184 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/providers/qwen.py` L21-406 | 多处 docstring 对标 nanobot openai_compat_provider | 否（注释） |
| `agent/server.py` L2-28 | docstring 对标 nanobot routes/chat.py | 否（注释） |
| `agent/session.py` L2-22 | docstring 对标 nanobot session_key | 否（注释） |
| `agent/context.py` L275 | 注释标注"[已废弃] nanobot 风格的额外段落" | 否（注释） |

> 注：上述残留全部为注释/docstring 性质，**无实现逻辑残留**。completion_policy 与 completes_run 的核心方法（`CompletionPolicy` / `ToolLifecycle` / `_find_completing_tool` / `_find_completing_tool_name` / `_inject_completion_reminder` / `_build_completion_reminder` / `_finish_run`）均无 nanobot 命名或 nanobot 风格逻辑。

### 注释残留 vs 实现逻辑残留区分

- **注释残留**：docstring 中引用 `nanobot xxx` 作为历史来源标注（如"对标 nanobot SkillsLoader"），不影响代码运行时行为。P2.5 重点文件（types.py / runtime.py）无此类残留。
- **实现逻辑残留**：代码中直接移植 nanobot 的类名、方法名、数据结构或控制流。P2.5 重点文件 **未发现** 任何实现逻辑残留，所有实现均基于 Cline 对标设计。

## 5. 修复建议

### P0（阻碍前端展示一致性）

1. **预注入 reminder 补齐 `message-added` 事件**：`_inject_completion_reminder`（runtime.py L2323-2346）当前只 `append` 不 `emit`，导致前端无法感知预注入的 reminder。建议在 `self._state.messages.append(reminder_msg)` 后补齐 `await self._emit(make_message_added(self.snapshot(), reminder_msg))`。同时将 `_inject_completion_reminder` 改为 `async def` 以支持 await emit。
   - **影响**：修复后前端事件流与 message 历史一致，restore 后无差异。
   - **风险**：低，仅补齐遗漏的 emit 调用，不改变核心逻辑。

### P1（功能对齐）

2. **reminder 工具名列表对齐**：`_find_completing_tool_name`（L2308-2321）当前多个时只取第一个，应改为返回所有 completesRun 工具名列表（sort 后），对齐 Cline `getRequiredCompletionToolNames`（L557-565）。`_inject_completion_reminder` 和 `_build_completion_reminder` 的 reminder 文本应包含完整工具名列表，让 LLM 知道所有可选的完成工具。
   - **影响**：多 completing tool 场景下 LLM 决策信息更完整。
   - **风险**：低，仅扩展返回值类型和文本拼接逻辑。

3. **兜底 reminder 含实际工具名**：`_build_completion_reminder` 默认文案（L2361-2364）当前固定写死 `"attempt_completion 或 submit_and_exit"`，应改为从 `self._tools` 动态查询实际注册的 completesRun 工具名，避免 LLM 调用不存在的工具。

### P2（架构债务）

4. **明确 completion_guard 异常处理策略**：当前 Charles 捕获异常降级（L2354-2360），Cline 让异常传播。建议二选一：
   - 方案 A（对齐 Cline）：移除 try/except，让 guard 异常传播由主循环 catch 块处理 `status="failed"`。适用于 guard 是纯函数的场景。
   - 方案 B（保留 Charles 增强）：在 docstring 中明确标注"Charles 主动增强：guard 异常降级到默认文案，避免终止运行"，避免未来对齐时误删。
   - **推荐**：方案 B，因为 Charles 的容错策略对生产环境更友好，但需文档化。

### P3（可选，注释清理）

5. **清理 nanobot 注释残留**：`agent/tools/`、`agent/skills/`、`agent/providers/`、`agent/server.py`、`agent/session.py`、`agent/context.py` 的 40+ 处 nanobot 历史对标注释，统一改为"Charles 历史实现"或直接删除。此项与 P2.4 报告建议 7 一致，非 P2.5 新增问题。

## 6. 验证方法建议

1. **预注入 reminder 事件流验证**：构造 `require_completion_tool=True` + 注册一个 `completes_run=True` 工具的 config，运行 agent，捕获事件流。预期：
   - Cline：事件流含 `message-added`（reminder）事件，前端可渲染。
   - Charles（当前）：事件流 **不含** `message-added`（reminder）事件，但 `state.messages` 中有 reminder 消息。
   - Charles（修复后）：事件流含 `message-added`（reminder）事件，与 Cline 一致。

2. **多 completing tool 验证**：注册 3 个 `completes_run=True` 工具（如 `attempt_completion` / `submit_and_exit` / `plan_mode`），运行 agent，检查预注入 reminder 文本：
   - Cline：reminder 含全部 3 个工具名（sort 后逗号分隔）。
   - Charles（当前）：reminder 只含第一个工具名。
   - Charles（修复后）：reminder 含全部 3 个工具名。

3. **completion_guard 异常验证**：构造 `completion_guard=lambda: 1/0`（抛 ZeroDivisionError），运行 agent 不调用 completing tool：
   - Cline：运行终止，`status="failed"`，`run-failed` 事件含 ZeroDivisionError。
   - Charles：运行继续，`status` 不变，日志含 warning `"completion_guard 执行失败: division by zero"`，下一轮注入默认中文 reminder。

4. **completes_run 命中后 status 验证**：构造 LLM 第一轮调用 `submit_and_exit`（`completes_run=True`）工具且执行成功的场景，运行 agent：
   - 两边预期：`status="completed"`，`run-finished` 事件发射，`output_text` 为 tool result 文本，`after_run` hooks 调用。
   - 验证点：对比 `AgentRunResult.status` / `output_text` / `iterations` 字段值。

5. **completes_run 失败不结束验证**：构造 LLM 调用 `submit_and_exit` 但工具执行返回 `is_error=True` 的场景：
   - 两边预期：`_find_completing_tool` 返回 None，运行继续下一轮。
   - 验证点：确认 `is_error=True` 时不会误触发 finishRun。

6. **nanobot 残留回归**：运行 `grep -r "nanobot" agent/types.py agent/runtime.py` 确认重点文件无残留；运行 `grep -r "nanobot" agent/` 统计总残留行数，建立基线（当前 55 行），后续修复后确认重点文件保持 0 残留。
