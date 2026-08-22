# Phase 3.4 AgentToolContext 字段对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在 `AgentToolContext` 数据结构上的差异，覆盖字段清单、字段类型、context 构建方式、abort_signal 透传链路、snapshot 字段、emit_update 用途、metadata 填充策略七个维度。

总体结论：Charles 已将 Cline 的 `AgentToolContext` 字段结构对齐到 1:1 等价，**10 个字段全部对齐**，无字段缺失。但存在三处需要澄清的细节：

1. **计划 P3.4.7 描述不准确**：计划声称"Charles 缺失 emit_update（用 emit 事件替代）"，但实际 Charles `types.py` L207 明确定义了 `emit_update: Callable[[Any], None] | None = None` 字段，且 `runtime.py` L1820-1823 在构建 context 时填充该字段，`tools/ask_question.py` / `tools/plan_mode.py` / `tools/run_commands.py` 等工具实际使用该字段。Charles 未缺失 emit_update，只是实现方式与 Cline 略有差异（_make_emit_update 辅助方法 + emit_sync 同步发射）。
2. **metadata 填充策略不同**：Cline `agent-runtime.ts` L1496 直接透传 `this.config.toolContextMetadata`（由调用方在 config 中预填）；Charles `runtime.py` L1806-1811 在 runtime 层显式构建 dict，含 `run_id` / `iteration` / `trigger_source` / `verbose` 四个标准键（Stage 10.5）。Charles 的实现更主动，标准键名定义在 `types.py` L582-588 `AGENT_TOOL_METADATA_KEYS`，与 Cline 的"调用方自治"语义不同。
3. **abort_signal 透传与检查机制不同**：Cline `signal` 字段是 `AbortSignal`（Web 标准），工具需自行检查 `signal.aborted`；Charles `abort_signal` 字段是 `asyncio.Event`，且 `BaseTool._check_aborted`（`base.py` L140-159）提供统一的检查方法，封装了 `signal.is_set() → raise AbortedError` 逻辑。Charles 的封装是功能增强。

`nanobot` 残留检查：在 `agent/types.py`、`agent/runtime.py`、`agent/abort.py`、`agent/tools/base.py` 四个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）；`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标注说明，详见第 4 节。

## 2. 逐项对比表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 3.4.1 | session_id 字段 | `agent.ts` L165（`sessionId?: string`） | `types.py` L201（`session_id: str \| None = None`） | 字段名 snake_case vs camelCase；类型差异（string vs str \| None），语义等价 | 已对齐 |
| 3.4.2 | agent_id 字段 | `agent.ts` L166（`agentId: string`，必填） | `types.py` L200（`agent_id: str = ""`，默认空串） | Cline 必填，Charles 默认空串（向后兼容）；运行时两者都从 config.agent_id 填充 | 已对齐 |
| 3.4.3 | conversation_id 字段 | `agent.ts` L167（`conversationId?: string`） | `types.py` L202（`conversation_id: str \| None = None`） | 字段名差异；计划 P3.4 未列出此字段，但两者都有 | 已对齐 |
| 3.4.4 | run_id 字段 | `agent.ts` L168（`runId?: string`） | `types.py` L203（`run_id: str \| None = None`） | 字段名差异，语义等价 | 已对齐 |
| 3.4.5 | signal / abort_signal 字段类型 | `agent.ts` L171（`signal?: AbortSignal`） | `types.py` L208（`abort_signal: Any = None`，实际 asyncio.Event） | 类型不同（AbortSignal vs asyncio.Event），语义等价；计划描述正确 | 已对齐 |
| 3.4.6 | snapshot 字段 | `agent.ts` L173（`snapshot?: AgentRuntimeStateSnapshot`） | `types.py` L206（`snapshot: AgentRuntimeStateSnapshot \| None = None`） | 两者类型等价；Charles 的 AgentRuntimeStateSnapshot 额外有 compaction 字段（Stage 11.3 J13），Cline 无 | 已对齐 |
| 3.4.7 | emit_update 字段 | `agent.ts` L174（`emitUpdate?: (update: unknown) => void`） | `types.py` L207（`emit_update: Callable[[Any], None] \| None = None`） | **计划描述错误**：Charles 未缺失，字段已定义且被工具实际使用；只是实现方式不同（_make_emit_update 辅助方法 + emit_sync 同步发射，Phase 35.1） | 已对齐 |
| 3.4.8 | metadata 字段 | `agent.ts` L172（`metadata?: Record<string, unknown>`） | `types.py` L212（`metadata: dict[str, Any] = field(default_factory=dict)`） | 类型等价；填充策略不同（见 3.4.10） | 已对齐 |
| 3.4.9 | abort_signal 透传链路 | `agent-runtime.ts` L1495（`signal: this.abortController?.signal`） | `runtime.py` L1824（`abort_signal=self._abort_controller.signal`） | 字段名不同（signal vs abort_signal），透传链路等价；Charles 额外有 `BaseTool._check_aborted` 统一检查方法 | 已对齐 |
| 3.4.10 | metadata 填充策略 | `agent-runtime.ts` L1496（`metadata: this.config.toolContextMetadata`，透传 config） | `runtime.py` L1806-1811（runtime 层显式构建 dict，含 run_id/iteration/trigger_source/verbose 标准键） | Cline 由调用方在 config 预填，Charles runtime 层主动构建；Charles 标准键定义在 `types.py` L582-588 `AGENT_TOOL_METADATA_KEYS` | 弱对齐 |
| 3.4.11 | tool_call_id 字段 | `agent.ts` L170（`toolCallId?: string`） | `types.py` L205（`tool_call_id: str \| None = None`） | 字段名差异，语义等价；计划 P3.4 未列出此字段，但两者都有 | 已对齐 |
| 3.4.12 | iteration 字段 | `agent.ts` L169（`iteration: number`，必填） | `types.py` L204（`iteration: int = 0`，默认 0） | Cline 必填，Charles 默认 0（向后兼容）；运行时两者都从 state.iteration 填充 | 已对齐 |
| 3.4.13 | context 构建位置 | `agent-runtime.ts` L1488-1507（`executePreparedTool` 内联构建） | `runtime.py` L1812-1826（`_execute_prepared_tool` 内联构建） | 两者都在 executePreparedTool 内联构建，字段一一对应赋值 | 已对齐 |
| 3.4.14 | emit_update 实现方式 | `agent-runtime.ts` L1498-1506（内联闭包，emit `tool-updated` 事件） | `runtime.py` L2151-2202（`_make_emit_update` 辅助方法返回闭包，emit_sync `TOOL_UPDATED` 事件） | Charles 抽取为辅助方法；Phase 35.1 改用 emit_sync 同步发射解决时序问题（run_commands terminal_output 实时性） | 已对齐 |
| 3.4.15 | emit_update 事件类型 | `agent-runtime.ts` L1499-1505（`tool-updated` 事件，含 snapshot/iteration/toolCall/update） | `runtime.py` L2187-2194（`TOOL_UPDATED` 事件，含 snapshot/iteration/tool_call_id/tool_name/metadata） | 字段名差异（toolCall vs tool_call_id），Charles 额外有 tool_name 字段；语义等价 | 已对齐 |
| 3.4.16 | snapshot 构建调用 | `agent-runtime.ts` L1497（`snapshot: this.snapshot()`） | `runtime.py` L1819（`snapshot=self.snapshot()`） | 完全一致，均调用 runtime.snapshot() 方法 | 已对齐 |
| 3.4.17 | run_id fallback | `agent-runtime.ts` L1492（`this.state.runId ?? createUID("run")`，运行时若未设置则生成） | `runtime.py` L1816（`run_id=self._state.run_id`，无 fallback） | Cline 有 createUID 兜底，Charles 无兜底（run() 启动时已设置 run_id，无需兜底） | 已对齐 |
| 3.4.18 | abort_signal 类型语义 | Web 标准 `AbortSignal`（可通过 `signal.aborted` 检查或 `signal.addEventListener('abort', ...)` 监听） | `asyncio.Event`（可通过 `signal.is_set()` 检查或 `await signal.wait()` 等待） | 类型不同但语义等价；asyncio.Event 协程安全，可多协程同时 wait | 已对齐 |
| 3.4.19 | abort_signal 工具侧检查 | 无统一封装，工具需自行 `if (context.signal?.aborted)` | `BaseTool._check_aborted`（`base.py` L140-159）统一封装，`signal.is_set() → raise AbortedError` | Charles 提供统一检查方法，是功能增强；Cline 工具需各自实现 | 已对齐（Charles 增强） |
| 3.4.20 | abort_signal 透传到 model.stream | `agent-runtime.ts` L831（`signal: this.abortController?.signal`，通过 AgentModelRequest.signal） | `runtime.py` L900（`abort_signal=self._abort_controller.signal`，通过 stream() 参数） | 透传路径不同：Cline 通过 request.signal，Charles 通过 stream() 关键字参数；语义等价 | 已对齐 |
| 3.4.21 | abort_signal 透传到 before_model hook | 无（Cline AgentBeforeModelContext 无 signal 字段） | `runtime.py` L2098-2112（`BeforeModelContext.abort_signal=self._abort_controller.signal`，Stage 11.2 J12） | Charles 额外透传到 before_model hook，让 ContextCompactor 等 hook 能响应中止；Cline 未透传 | 弱对齐（Charles 增强） |
| 3.4.22 | context 字段总数 | 10 个（sessionId/agentId/conversationId/runId/iteration/toolCallId/signal/metadata/snapshot/emitUpdate） | 10 个（agent_id/session_id/conversation_id/run_id/iteration/tool_call_id/snapshot/emit_update/abort_signal/metadata） | 字段数完全一致，1:1 对应 | 已对齐 |

## 3. 重点差距详细说明

### 3.1 计划 P3.4.7 描述错误：Charles 未缺失 emit_update

- **计划描述**：P3.4.7 表格声称"emit_update | 是 | 无 | Charles 缺失（用 emit 事件替代）"。
- **实际代码**：Charles `types.py` L207 明确定义了 `emit_update: Callable[[Any], None] | None = None` 字段，且：
  - `runtime.py` L1820-1823 在 `_execute_prepared_tool` 构建 context 时通过 `self._make_emit_update(tool_name, tool_call_id)` 填充该字段。
  - `runtime.py` L2151-2202 的 `_make_emit_update` 方法返回一个闭包，闭包内构造 `TOOL_UPDATED` 事件并通过 `emit_sync` 同步发射（Phase 35.1 改用同步发射解决时序问题）。
  - 实际工具使用该字段：`ask_question.py` L93-95、`plan_mode.py` L142-144 / L244-246、`run_commands.py` L195 / L225-228 / L248、`todo_write.py` 等均通过 `context.emit_update({...})` 推送进度更新到前端。
- **影响**：计划描述与实际代码不符，会误导后续修复决策。Charles 的 emit_update 实际是已对齐字段，仅实现方式与 Cline 略有差异（辅助方法 vs 内联闭包，emit_sync vs emit）。
- **残留性质**：非残留，属于计划描述错误。

### 3.2 metadata 填充策略：Cline 透传 config vs Charles runtime 层显式构建

- **Cline**：`agent-runtime.ts` L1496 在构建 context 时直接透传 `this.config.toolContextMetadata`，该字段由调用方在 `AgentRuntimeConfig.toolContextMetadata`（`agent.ts` L436）中预填。runtime 层不主动构建 metadata，仅做透传。
- **Charles**：`runtime.py` L1806-1811 在 `_execute_prepared_tool` 构建 context 时显式构建 metadata dict：
  ```python
  tool_metadata = {
      "run_id": self._state.run_id or "",
      "iteration": self._state.iteration,
      "trigger_source": "user",  # 默认用户触发，未来扩展 checkpoint/scheduler
      "verbose": bool(getattr(self.config, "verbose", False)),
  }
  ```
  标准键名定义在 `types.py` L582-588 `AGENT_TOOL_METADATA_KEYS` dict，包含 `run_id` / `iteration` / `trigger_source` / `checkpoint_id` / `verbose` 五个标准键的说明。
- **影响**：
  1. Charles 的 metadata 内容由 runtime 决定，工具可读取固定标准键；Cline 的 metadata 内容由调用方决定，工具需与调用方约定键名。
  2. Charles 的 `checkpoint_id` 标准键未实际填充（L1806-1811 未包含），属于预留字段；Cline 无此概念。
  3. Charles 的 `trigger_source` 默认 "user"，注释称"未来扩展 checkpoint/scheduler"，但当前未实现差异化填充。
- **残留性质**：非残留，属于设计选择差异。Charles 的实现更主动，标准键名更明确，便于工具读取运行时上下文。

### 3.3 abort_signal 检查机制：Charles 提供 BaseTool._check_aborted 统一封装

- **Cline**：`AgentToolContext.signal` 是 Web 标准 `AbortSignal`，工具需自行检查 `context.signal?.aborted` 并抛出异常。Cline `sdk/packages/agents/src/` 目录无统一封装方法，工具实现自治。
- **Charles**：`AgentToolContext.abort_signal` 是 `asyncio.Event`，`BaseTool._check_aborted`（`base.py` L140-159）提供统一封装：
  ```python
  def _check_aborted(self, context: AgentToolContext) -> None:
      signal = getattr(context, "abort_signal", None)
      if signal is not None and signal.is_set():
          raise AbortedError("aborted by user")
  ```
  工具在长 IO 操作（循环批量执行、网络请求等）的关键检查点调用 `self._check_aborted(context)`，统一抛出 `AbortedError`。
- **影响**：
  1. Charles 的封装避免每个工具重复实现检查逻辑，是功能增强。
  2. `AbortedError` 被 `BaseTool.execute`（L131-133）特殊处理：`except AbortedError: raise`，让中止异常向上传播由主循环处理 `status="aborted"`，不被转为 is_error 结果。
  3. Cline 工具若忘记检查 signal.aborted，中止信号会被忽略直到下一次循环边界检查；Charles 工具调用 `_check_aborted` 可在工具内部关键点立即响应。
- **残留性质**：非残留，属于 Charles 主动增强。

### 3.4 abort_signal 透传到 before_model hook：Charles 额外增强

- **Cline**：`AgentBeforeModelContext`（`agent.ts` L269-272）只有 `snapshot` 和 `request` 两个字段，无 `signal` 字段。before_model hook 无法直接响应中止信号。
- **Charles**：`BeforeModelContext`（`hooks.py` L90-98，Stage 11.2 J12）额外有 `abort_signal: Any = None` 字段，`runtime.py` L2098-2112 在调用 before_model hook 时透传 `abort_signal=self._abort_controller.signal`。
- **影响**：Charles 的 before_model hook（如 `ContextCompactor` 的 fallback 路径，`context.py` L1504-1505 / L1759-1816）能在压缩关键步骤前检查 abort_signal，触发时抛 `AbortedError`，避免压缩过程中忽略用户中止。Cline 的 before_model hook 无此能力，压缩过程中中止信号只能在下一次循环边界检查生效。
- **残留性质**：非残留，属于 Charles 主动增强（Stage 11.2 J12）。

### 3.5 snapshot 字段结构差异：Charles 多 compaction 字段

- **Cline**：`AgentRuntimeStateSnapshot`（`agent.ts` L128-140）字段：`agentId` / `agentRole?` / `parentAgentId?` / `conversationId?` / `runId?` / `status` / `iteration` / `messages` / `pendingToolCalls` / `usage` / `lastError?`，共 11 个字段。
- **Charles**：`AgentRuntimeStateSnapshot`（`types.py` L374-398）字段：`agent_id` / `agent_role` / `parent_agent_id` / `conversation_id` / `run_id` / `status` / `iteration` / `messages` / `pending_tool_calls` / `usage` / `last_error` / `compaction`，共 12 个字段。
- **差异**：Charles 多 `compaction: CompactionStateSnapshot | None` 字段（Stage 11.3 J13），由 `ContextCompactor` 在压缩生命周期中填充，前端从事件中读取 `snapshot.compaction` 显示压缩进度。Cline 无此字段。
- **影响**：Charles 的 snapshot 字段更丰富，支持压缩进度展示；Cline 无压缩功能故无此字段。两者核心字段完全对齐，`compaction` 是 Charles 扩展字段。
- **残留性质**：非残留，属于 Charles 功能扩展（Stage 11.3 J13）。

## 4. nanobot 残留检查

在 `agent/types.py`、`agent/runtime.py`、`agent/abort.py`、`agent/tools/base.py` 四个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）。

`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标说明，未影响 AgentToolContext 字段定义与 context 构建逻辑。重点文件清单：

| 文件 | 残留性质 | 是否影响 AgentToolContext |
|------|---------|--------------------------|
| `agent/types.py` | 无残留 | 不适用 |
| `agent/runtime.py` | 无残留 | 不适用 |
| `agent/abort.py` | 无残留 | 不适用 |
| `agent/tools/base.py` | 无残留 | 不适用 |
| `agent/tools/__init__.py` L2 | docstring 标题对标说明 | 否（注释） |
| `agent/tools/exec_tool.py` L2-263 | 多处 docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | 多处 docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | 多处 docstring 对标 nanobot WebSearchTool | 否（注释） |
| `agent/skills/loader.py` L2-423 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/skills/registry.py` L2-184 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/skills/__init__.py` L2-23 | docstring 对标说明 | 否（注释） |
| `agent/skills/skill_tool.py` L18 | docstring 对标说明 | 否（注释） |
| `agent/providers/qwen.py` L21-406 | 多处 docstring 对标 nanobot openai_compat_provider | 否（注释） |
| `agent/server.py` L2-28 | docstring 对标 nanobot routes/chat.py | 否（注释） |
| `agent/session.py` L2-22 | docstring 对标 nanobot session_key | 否（注释） |
| `agent/context.py` L275 | 注释标注"[已废弃] nanobot 风格的额外段落" | 否（注释） |

> 注：上述残留全部为注释/docstring 性质，**无实现逻辑残留**。AgentToolContext 的字段定义（`types.py` L189-212）、context 构建逻辑（`runtime.py` L1806-1826）、abort_signal 透传链路（`runtime.py` L1824 / `abort.py` L54-55）、emit_update 实现（`runtime.py` L2151-2202）均无 nanobot 命名或 nanobot 风格逻辑。

## 5. 修复建议

### P0（阻碍后续对比/集成）
1. **修正计划 P3.4.7 描述**：计划表格声称"Charles 缺失 emit_update"，实际 Charles `types.py` L207 已定义该字段且被工具实际使用。建议将计划描述改为"已对齐，实现方式不同（_make_emit_update 辅助方法 + emit_sync 同步发射）"，避免误导后续修复决策。

### P1（架构债务）
2. **统一 metadata 填充策略**：Charles runtime 层显式构建 metadata 含 4 个标准键（run_id/iteration/trigger_source/verbose），Cline 透传 config.toolContextMetadata。建议二选一：
   - 方案 A（对齐 Cline）：移除 runtime 层显式构建，改为透传 config.tool_context_metadata，由调用方预填。
   - 方案 B（保留 Charles 增强）：在文档中明确标注此为 Charles 主动增强，标准键名定义在 `AGENT_TOOL_METADATA_KEYS`，与 Cline 的"调用方自治"语义不同。
3. **补齐 checkpoint_id 标准键填充**：Charles `AGENT_TOOL_METADATA_KEYS` 定义了 5 个标准键，但 `runtime.py` L1806-1811 实际只填充 4 个（缺 `checkpoint_id`）。若未来支持 checkpoint 触发，需在 metadata 中填充该键；当前属于预留字段，可暂缓。

### P2（功能增强）
4. **统一 abort_signal 工具侧检查**：Charles `BaseTool._check_aborted` 是功能增强，建议保留。但需确保所有长 IO 工具（run_commands / read_files / search_codebase / fetch_web_content）在关键循环点调用 `self._check_aborted(context)`，避免中止信号被忽略。当前 `run_commands.py` L195 / L248 已正确使用，其他工具需核查。
5. **对齐 before_model hook 的 abort_signal 透传**：Charles `BeforeModelContext.abort_signal`（Stage 11.2 J12）是功能增强，建议保留。Cline 的 `AgentBeforeModelContext` 无此字段，未来若 Cline 增加压缩功能需参考 Charles 实现。

### P3（文档/规范）
6. **清理 nanobot 残留**：`agent/tools/`、`agent/skills/`、`agent/providers/`、`agent/server.py`、`agent/session.py`、`agent/context.py` 的 40+ 处 nanobot 历史对标注释，统一改为"Charles 历史实现"或直接删除。
7. **补齐计划 P3.4 字段清单**：计划 P3.4 表格未列出 `conversation_id`（3.4.3）和 `tool_call_id`（3.4.11）字段，但两者在 Cline 和 Charles 中都已对齐。建议补齐计划表格，避免遗漏。

## 6. 验证方法建议

1. **字段清单完整性验证**：在 Charles 中创建 `AgentToolContext()` 实例，通过 `dataclasses.asdict(context)` 获取所有字段，与 Cline `Object.keys(context)` 对比，确认 10 个字段全部存在。
2. **emit_update 字段实际使用验证**：在 `ask_question` / `plan_mode` / `run_commands` 工具执行时，断点确认 `context.emit_update` 不为 None，调用后确认 `TOOL_UPDATED` 事件被发射到事件流（通过 `EventEmitter` 订阅验证）。
3. **abort_signal 透传链路验证**：在工具执行中调用 `runtime.abort()`，确认：a) `context.abort_signal.is_set()` 返回 True；b) `BaseTool._check_aborted` 抛出 `AbortedError`；c) `AbortedError` 被 `BaseTool.execute` 透传（L131-133）；d) 主循环 catch 后 `status="aborted"`。
4. **metadata 填充内容验证**：在工具 execute 中读取 `context.metadata`，确认包含 `run_id` / `iteration` / `trigger_source` / `verbose` 四个标准键，值与 runtime state 一致。
5. **snapshot 字段结构验证**：在工具 execute 中读取 `context.snapshot`，确认 12 个字段全部存在（含 `compaction` 字段，默认 None）；与 Cline 的 11 个字段对比，确认 `compaction` 是 Charles 扩展字段。
6. **before_model hook abort_signal 透传验证**：在 before_model hook 中读取 `ctx.abort_signal`，确认不为 None；在 hook 执行中调用 `runtime.abort()`，确认 hook 内 `abort_signal.is_set()` 返回 True（Stage 11.2 J12 透传链路验证）。
7. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/` 并统计行数，建立基线（当前约 55 行）；后续修复后确认重点文件（types.py / runtime.py / abort.py / base.py）无残留。
