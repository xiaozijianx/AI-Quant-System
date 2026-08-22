# Phase 7.1 上下文压缩架构对比

> 对比范围：Cline `sdk/packages/core/src/extensions/context/` 下的 `compaction.ts` / `compaction-shared.ts` / `basic-compaction.ts` / `agentic-compaction.ts` / `budget-projection/` 与 `sdk/packages/core/src/session/models/session-compaction.ts`，对比 Charles `agent/context.py` 的 `ContextCompactor` + `CompactionStateManager` + `agent/budget_policy.py` + `agent/events.py` 压缩事件 + `agent/server.py` 压缩接入；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/extensions/context/compaction.ts` L1-623（`createContextCompactionPrepareTurn` + `createCompactionStateAwarePrepareTurn` 入口）
> - `third_party/cline/sdk/packages/core/src/extensions/context/compaction-shared.ts` L1-741（常量 + `findCutIndex` + `summarizeToolActivity` + `buildSummaryRequest` + `buildSummaryMessage` + `truncateToolResultContentForCompaction`）
> - `third_party/cline/sdk/packages/core/src/extensions/context/basic-compaction.ts` L1-695（`runBasicCompaction` + `mergeAdjacentUserTurns` + `PRESERVED_ASSISTANT_TEXT_COUNT` + `isPreservedByCompaction`）
> - `third_party/cline/sdk/packages/core/src/extensions/context/agentic-compaction.ts` L1-281（`runAgenticCompaction` + `buildAgenticSummaryInputBudget`）
> - `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/project.ts` L1-672（`buildBudgetProjection` + `BudgetPolicyIntent`）
> - `third_party/cline/sdk/packages/core/src/session/models/session-compaction.ts` L1-188（`SessionCompactionState` schema + `projectSessionCompactionState`）
>
> Charles 源码：
> - `agent/context.py` L940-2666（常量 + `ContextCompactor` + `CompactionStateManager` + `is_compaction_summary_message`）
> - `agent/budget_policy.py` L42-100（`BudgetPolicyIntent` + `ProjectionPolicy` + `resolve_projection_policy`）
> - `agent/events.py` L60-65 + L439-640（压缩事件常量 + `make_compaction_*` 辅助函数）
> - `agent/server.py` L407-415（`ContextCompactor` 注册为 `before_model` hook）+ L1601-1606（rollback 时清理压缩状态）
> - `agent/types.py` L401-421（`CompactionStateSnapshot` dataclass）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的上下文压缩架构。**核心结论：计划文件 P7.1 列出的 10 项对比项全部对齐，常量值与核心算法语义高度一致；但双方在 basic 策略的实现路径上存在架构性差异（Cline 双策略分文件、Charles 单方法统一摘要），且 Charles 在 state-aware 持久化、budget-projection、abort_signal、file/image 截断、压缩事件 5 个增强点上做了合理扩展。**

### 计划文件核实结果

AGENT_COMPARISON_PLAN_V2.md L2496-2523 的 P7.1 对比表标注 7.1.1-7.1.10 全部"已对齐"。经源码核实：

| 计划项 | 计划标注 | 实际核实 | 一致性 |
|--------|---------|---------|--------|
| 7.1.1 触发比例 0.9 | 已对齐 | Cline `COMPACTION_TRIGGER_RATIO = 0.9`（compaction-shared.ts L17）/ Charles `_DEFAULT_COMPACTION_TRIGGER_RATIO = 0.9`（context.py L941） | 高 |
| 7.1.2 maxInput 128000 | 已对齐 | Cline `DEFAULT_MAX_INPUT_TOKENS = 128_000`（L13）/ Charles `_DEFAULT_MAX_INPUT_TOKENS = 128000`（L944） | 高 |
| 7.1.3 preserve_recent_tokens 20000 | 已对齐 | Cline `DEFAULT_PRESERVE_RECENT_TOKENS = 20_000`（L19）/ Charles `_DEFAULT_PRESERVE_RECENT_TOKENS = 20000`（L947） | 高 |
| 7.1.4 _find_cut_index | 已对齐 | Cline `findCutIndex`（L317-350）/ Charles `_find_cut_index`（context.py L1994-2057） | 高 |
| 7.1.5 _summarize_tool_activity | 已对齐 | Cline `summarizeToolActivity`（L535-609）/ Charles `_summarize_tool_activity`（context.py L2117-2271） | 高 |
| 7.1.6 PRESERVED_ASSISTANT_TEXT_COUNT | 已对齐 | Cline `PRESERVED_ASSISTANT_TEXT_COUNT = 3`（basic-compaction.ts L60）/ Charles `PRESERVED_ASSISTANT_TEXT_COUNT = 3`（context.py L968） | 高 |
| 7.1.7 agentic + basic fallback | 已对齐 | Cline `BUILTIN_COMPACTION_STRATEGIES` + try/catch fallback（compaction.ts L419-437）/ Charles `before_model` try/except + `_simple_summary` fallback（context.py L1587-1660） | 高 |
| 7.1.8 CompactionStateManager | 已对齐（Stage 11.3） | Cline `createCompactionStateAwarePrepareTurn` + `SessionCompactionState`（compaction.ts L566-623 + session-compaction.ts）/ Charles `CompactionStateManager` 类（context.py L989-1164） | 中-高（持久化机制不同） |
| 7.1.9 abort_signal 透传 | 已对齐（Stage 11.2） | Cline `ContextPipelinePrepareTurnInput.abortSignal` + `isCompactionCancellation`（compaction.ts L40/L83-94）/ Charles `BeforeModelContext.abort_signal` + `AbortedError`（context.py L1505/L1606-1629） | 高 |
| 7.1.10 file/image 截断 | 已对齐（Stage 11.4） | Cline `truncateToolResultContentForCompaction`（compaction-shared.ts L100-124）+ budget-projection `dropUnsafeBlocks`（project.ts L243-299）/ Charles `_truncate_tool_results`（context.py L1853-1947） | 中-高（实现位置不同） |

### 核心结论

1. **常量集合完全对齐**：7 个核心常量（trigger_ratio / maxInput / preserve_recent_tokens / summary_max_tokens / tool_result_char_limit / file_content_char_limit / preserved_assistant_text_count / command_summary_char_limit）值与含义逐项一致。
2. **核心算法语义对齐**：`findCutIndex` / `summarizeToolActivity` / `buildSummaryRequest` / `ensureFilesSection` / `buildSummaryMessage` / `isSafeCutBoundary` / `isCompactionSummaryMessage` 的边界判定与输出结构对齐。
3. **架构差异 — basic 策略实现路径不同**：Cline 在 `basic-compaction.ts` 中保留 typed user 消息 + 折叠中间消息为 `<SYSTEM_NOTICE>` 块（不产生 `compaction_summary` 消息）；Charles 的 basic 策略通过同一 `compact()` 方法产生 `compaction_summary` 摘要消息 + recent_messages。Charles 设计更简单但与 Cline 行为不同。
4. **架构差异 — 文件分层不同**：Cline 把 compaction 拆成 4 个文件（compaction.ts 入口 + compaction-shared.ts 共享 + basic-compaction.ts + agentic-compaction.ts）；Charles 全部集中在 `context.py` 的 `ContextCompactor` 类中。
5. **state-aware 持久化机制不同**：Cline 用 `SessionCompactionState` zod schema + `source_prefix_hash`（SHA-256）验证源消息未变 + `source_last_message_key` 兜底；Charles 用 `CompactionState` dataclass + JSON 文件持久化 + `compacted_count` 整数偏移，无 hash 验证。Charles 更简单但抗篡改能力弱。
6. **Charles 合理扩展**：(a) `_summarize_tool_activity_v2` 接入 `FileContextTracker` 跨压缩周期保留文件状态（Phase 29.3）；(b) `_DEFAULT_PROJECTION_RATIO = 0.8` 提前压缩触发（Phase 29.4）；(c) `MAX_FILE_DATA_LENGTH = 100_000` / `MAX_IMAGE_DATA_LENGTH = 50_000` file/image 数据截断阈值（Stage 11.4）；(d) `compaction-failed` 事件（Stage 11.3 J13，Cline 无对应独立事件）；(e) `get_stats` 方法返回 budget_projection 统计信息供前端显示。
7. **abort_signal 透传完全对齐**：双方均把 abort 信号透传到压缩内部，AbortedError/AbortError 不触发 fallback，直接向上抛出。
8. **nanobot 残留**：P7.1 范围内（context.py + server.py + budget_policy.py + events.py + types.py）共 **4 处注释残留、0 处实现逻辑残留**。残留均为 docstring 中"对标 nanobot ..."的历史说明，不影响功能。

### 一致性总体评估

- **常量与核心算法**：**高**。8 个常量逐项相同，`findCutIndex` / `summarizeToolActivity` / `buildSummaryRequest` 输出结构对齐。
- **触发与 fallback 策略**：**高**。trigger_ratio / maxInput / preserve_recent_tokens 对齐，agentic 失败回退 basic 行为一致。
- **basic 策略实现**：**中**。Cline 保留 typed user + `<SYSTEM_NOTICE>` 块；Charles 统一产生 `compaction_summary` 消息。语义不同但 Charles 设计更简单。
- **state-aware 持久化**：**中**。双方都有持久化，但 Cline 用 hash 验证、Charles 用整数偏移，抗篡改能力不同。
- **abort_signal 透传**：**高**。完全对齐。
- **file/image 截断**：**中-高**。双方都截断，但 Charles 增加了 base64 数据长度阈值（100KB/50KB），Cline 用 char_limit + budget-projection 的 `dropUnsafeBlocks`。
- **budget-projection**：**高**。`BudgetPolicyIntent` 三值枚举完全对齐，`ProjectionPolicy` 矩阵一致。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.1.1 | 触发比例 | `COMPACTION_TRIGGER_RATIO = 0.9`（compaction-shared.ts L17）；触发条件 `requestInputTokens >= maxInputTokens * 0.9`（compaction.ts L307-312） | `_DEFAULT_COMPACTION_TRIGGER_RATIO = 0.9`（context.py L941）；触发条件 `request_tokens >= self._trigger_tokens`（context.py L1336） | 高 | 已对齐。双方均用 0.9 作为压缩触发比例 |
| 7.1.2 | maxInput | `DEFAULT_MAX_INPUT_TOKENS = 128_000`（compaction-shared.ts L13）；`resolveEffectiveMaxInputTokens` 优先取 model.info.maxInputTokens，无值时退化为 `contextWindow * 0.9`（L49-68） | `_DEFAULT_MAX_INPUT_TOKENS = 128000`（context.py L944）；直接用默认值，不查询 model.info | 高 | 已对齐（默认值）。Cline 多了从 model.info 动态解析的逻辑，Charles 用静态默认值。Charles 后续可扩展为从 model.info 解析 |
| 7.1.3 | preserve_recent_tokens | `DEFAULT_PRESERVE_RECENT_TOKENS = 20_000`（compaction-shared.ts L19）；用于 `findCutIndex` 从尾部累计 token 直到达到此值（L317-350） | `_DEFAULT_PRESERVE_RECENT_TOKENS = 20000`（context.py L947）；用于 `_find_cut_index` 从尾部累计 token（L1994-2057） | 高 | 已对齐。语义与默认值完全一致 |
| 7.1.4 | _find_cut_index | `findCutIndex`（compaction-shared.ts L317-350）：从尾部累计 token → 取 `lastTurnStartIndex` → `Math.min(candidate, lastTurnStartIndex)` → 向前调整到 `isSafeCutBoundary` | `_find_cut_index`（context.py L1994-2057）：从尾部累计 token → 取 `last_turn_start` → `min(candidate, last_turn_start)` → 向前调整到 `_is_safe_cut_boundary` | 高 | 已对齐。算法步骤逐项对应。Charles 在 candidate=0 时额外检查 `messages[0]` 是否是 `compaction_summary`（非安全边界返回 -1），与 Cline `isTurnStartMessage` 中 `!isCompactionSummaryMessage` 语义一致 |
| 7.1.5 | _summarize_tool_activity | `summarizeToolActivity`（compaction-shared.ts L535-609）：遍历 tool_use 块，按 tool_name 分流到 readFiles/editedFiles/commands；editor/apply_patch 从 tool_result 的 diff 提取行号范围 `path:start-end` | `_summarize_tool_activity`（context.py L2117-2271）：遍历 ToolCallPart，按 tool_name 分流到 read_files/edited_files/commands；editor/apply_patch 从 diff `@@ -old +new,len @@` 提取行号 `path#Lstart-end` | 高 | 已对齐。分流逻辑与行号提取语义一致。差异：(a) Cline 用 `path:start-end`，Charles 用 `path#Lstart-end`（格式微差）；(b) Charles `_summarize_tool_activity_v2` 优先从 `FileContextTracker` 取文件列表（Phase 29.3 扩展，Cline 无对应） |
| 7.1.6 | PRESERVED_ASSISTANT_TEXT_COUNT | `PRESERVED_ASSISTANT_TEXT_COUNT = 3`（basic-compaction.ts L60）；在 `mergeAdjacentUserTurns` 中从尾部向前找最近 3 条 assistant 文本（L143-151） | `PRESERVED_ASSISTANT_TEXT_COUNT = 3`（context.py L968）；在 `_extract_preserved_assistant_texts` 中从尾部向前找最近 3 条 assistant 文本（L2273-2294） | 高 | 已对齐。常量值与提取逻辑一致。差异：Cline 在 `mergeAdjacentUserTurns` 内部提取（按原始索引集合筛选），Charles 在独立方法 `_extract_preserved_assistant_texts` 中提取后传给 `_build_dropped_work_summary_block` |
| 7.1.7 | agentic + basic fallback | `BUILTIN_COMPACTION_STRATEGIES = { basic, agentic }`（compaction.ts L142-167）；try/catch 中 agentic 失败且非 abort 时回退到 basic（L419-437） | `before_model` 中 if model 存在用 `_llm_summarize`（agentic），失败 except 回退到 `compact(summarize_func=None)`（basic，用 `_simple_summary`）（context.py L1587-1660） | 高 | 已对齐。agentic 优先 + basic fallback 策略一致。差异：(a) Cline 的 basic 是独立 `runBasicCompaction`（保留 typed user + `<SYSTEM_NOTICE>` 块），Charles 的 basic 是同一 `compact()` 方法用 `_simple_summary` 生成摘要消息；(b) Cline abort 不回退（`isCompactionCancellation` 返回 true 时 throw），Charles abort 不回退（`AbortedError` 直接 raise）—— 行为一致 |
| 7.1.8 | CompactionStateManager | `createCompactionStateAwarePrepareTurn`（compaction.ts L566-623）+ `SessionCompactionState`（session-compaction.ts L25-150）：zod schema 校验 + `source_prefix_hash`（SHA-256）验证源消息未变 + `projectSessionCompactionState` 投影 | `CompactionStateManager` 类（context.py L989-1164）：`load/save/clear` JSON 文件持久化 + `start_compaction/finish_compaction/fail_compaction` 生命周期 + `project` 返回 `CompactionStateSnapshot`；用 `compacted_count` 整数偏移投影 | 中-高 | 已对齐（功能）。差异：(a) Cline 用 hash 验证源消息完整性，Charles 用整数偏移（无 hash）；(b) Cline schema 用 zod 严格校验，Charles 用 dataclass + try/except；(c) Charles 增加 `start/finish/fail` 生命周期方法（Stage 11.3 J13），Cline 无对应（Cline 在 `createContextCompactionPrepareTurn` 内部用 `startedAt = Date.now()` 记录耗时）；(d) Charles 增加 `compaction-failed` 事件，Cline 无独立 failed 事件 |
| 7.1.9 | abort_signal 透传 | `ContextPipelinePrepareTurnInput.abortSignal: AbortSignal`（compaction.ts L40）；传给 `providerConfig.abortSignal`（L408）；`isCompactionCancellation` 检查 `abortSignal.aborted` 或 `error.name === "AbortError"`（L83-94）；abort 时不回退直接 throw（L422-427） | `BeforeModelContext.abort_signal`（context.py L1505）；传给 `compact(abort_signal=...)`（L1598）；关键步骤前检查 `abort_signal.is_set()` 抛 `AbortedError`（L1761-1762）；`except AbortedError` 不回退直接 raise（L1606-1629） | 高 | 已对齐。abort 信号透传与不回退策略一致。差异：Cline 用 `AbortSignal.aborted` 属性 + `AbortError` 异常名；Charles 用 `asyncio.Event.is_set()` + `AbortedError` 异常类（语言生态差异） |
| 7.1.10 | file/image 截断 | `truncateToolResultContentForCompaction`（compaction-shared.ts L100-124）：string 用 `truncateText(content, 2000)`；list 中 text 用 `truncateText(block.text, 2000)`、file 用 `truncateText(block.content, 2000)`、image 不截断保留原值。budget-projection 的 `dropUnsafeBlocks` 在 live tail 之外丢弃 image/redacted_thinking（project.ts L243-299） | `_truncate_tool_results`（context.py L1853-1947）：string output 超 2000 字符截断；list output 中 FilePart.content 超 `MAX_FILE_DATA_LENGTH=100_000` 清空保留 path、ImagePart.image 超 `MAX_IMAGE_DATA_LENGTH=50_000` 清空保留 alt_text；截断后追加 `[truncated]` 标记 | 中-高 | 已对齐（截断意图）。差异：(a) Cline 用字符截断（2000 chars），Charles 增加数据量阈值（100KB/50KB base64）；(b) Cline image 不截断保留原值（仅 budget-projection 阶段才丢弃），Charles image 超阈值清空；(c) Charles 截断后追加 `[truncated]` 文本标记，Cline 用 `...[truncated N chars]` 内联标记 |

---

## 三、重点差距详解

### 3.1 basic 策略实现路径的根本差异（架构差异，非缺陷）

这是本阶段最显著的架构差异：

**Cline `runBasicCompaction`（basic-compaction.ts L442-694）**：
- 不产生 `kind: "compaction_summary"` 消息
- 保留所有 typed user 消息（`isTurnStartMessage` 判定）
- 在最新 typed turn 之前，按 token 预算保留尾部消息（snap 到 assistant 消息保持 tool 配对）
- 旧 turn 的 concluding assistant answer 按预算保留（newest first）
- 通过 `mergeAdjacentUserTurns` 把相邻 typed user 之间的 dropped 工具活动折叠为 `<SYSTEM_NOTICE>` 块附加到 surviving user 消息
- 通过 `isPreservedByCompaction` / `markPreservedByCompaction` 冻结已保留消息，避免下次压缩重复处理

**Charles `compact()` basic 路径（context.py L1719-1851 + `_simple_summary`）**：
- 产生 `kind: "compaction_summary"` 摘要消息（与 agentic 路径相同的消息结构）
- 用 `_find_cut_index` 找切割点，前半段用 `_simple_summary` 生成文本（每条消息前 200 字符拼接）
- 输出 = `[summary_message] + recent_messages`
- 无 `mergeAdjacentUserTurns` 折叠逻辑
- 无 `isPreservedByCompaction` 冻结机制（依赖 `CompactionStateManager` 的 `compacted_count` 偏移实现"不重复处理"）

**影响分析**：
- Cline basic 策略保留了"用户问什么"的完整上下文（typed user 全保留），LLM 能看到所有原始问题
- Charles basic 策略把旧问题也压缩进摘要，LLM 只能看到摘要中的"用户问过 X"复述
- Charles 设计更简单（统一消息结构），但损失了原始 typed user 的精确语义
- 此差异不影响 agentic 策略（双方都用 LLM 生成摘要消息）

**修复建议**：**不建议修改**。Charles 的统一摘要设计更易维护，且 agentic 是默认策略（basic 仅 fallback）。若需完全对齐，可在 `_simple_summary` 中保留 typed user 消息原文 + 折叠工具活动，但会增加复杂度。

### 3.2 state-aware 持久化机制差异

**Cline `SessionCompactionState`（session-compaction.ts L25-181）**：
```typescript
{
    version: 1,
    updated_at: ISO datetime,
    conversation_id: string,
    source_message_count: number,        // 原始消息数
    source_prefix_hash: "sha256:...",    // SHA-256 hash 验证源消息未变
    source_last_message_key: string,     // 兜底 boundary key
    messages: [...],                     // 压缩后的消息列表
    system_prompt: string,
}
```
- `projectSessionCompactionState` 投影时校验 `source_prefix_hash` 或 `source_last_message_key`，源消息不匹配时返回 `undefined`（不投影）
- 用 zod schema 严格校验持久化数据结构

**Charles `CompactionState` + `CompactionStateManager`（context.py L980-1164）**：
```python
@dataclass
class CompactionState:
    summary_message: AgentMessage
    compacted_count: int                # 被摘要替代的原始消息数量
    created_at: str                     # ISO datetime
```
- 持久化到 `agent_data/compaction_states/<session_id>.json`
- `before_model` 加载时用 `compacted_count` 作为偏移：`messages = [summary_message] + messages[compacted_count:]`
- 防御性校验：`0 < compacted_count < len(messages)`，不合法时忽略状态
- 无 hash 验证源消息完整性

**影响分析**：
- Cline 的 hash 验证能检测源消息被修改/插入/删除，避免摘要与源消息错位
- Charles 的整数偏移假设源消息列表的头部不变，若用户回滚/插入消息，偏移可能错位（但 Charles 在 `/rollback` 时主动调用 `CompactionStateManager().clear(session_id)` 清理状态，缓解此问题）
- Charles 的 `start_compaction/finish_compaction/fail_compaction` 生命周期方法 + `project()` 快照投影是 Cline 没有的扩展（Cline 仅在 `createContextCompactionPrepareTurn` 内部用 `startedAt = Date.now()` 记录耗时）

**修复建议**：**不建议修改**。Charles 的整数偏移 + rollback 清理策略在当前场景下足够，hash 验证对 Python 生态过度设计。Charles 的生命周期方法 + `project()` 快照是合理扩展，应保留。

### 3.3 Charles 扩展：FileContextTracker 集成（Phase 29.3）

Charles `_summarize_tool_activity_v2`（context.py L2059-2115）优先从 `FileContextTracker` 取文件列表：
```python
tracker = get_tracker(session_id)
state = tracker.get_state()
# state = {"read": [...], "edited": [...], "created": [...]}
```
- tracker 跨压缩周期保留文件状态（不受压缩影响）
- tracker 无数据时回退到 `_summarize_tool_activity` 从消息扫描
- Cline 无对应机制（每次压缩都从消息扫描）

**影响**：Charles 在多次压缩后仍能保留完整的文件读写历史（tracker 不被压缩），Cline 每次压缩只能看到当前消息列表中的工具调用。这是 Charles 的合理增强。

### 3.4 Charles 扩展：budget-projection 提前压缩（Phase 29.4）

Charles 增加 `_DEFAULT_PROJECTION_RATIO = 0.8`（context.py L957）：
- `should_compact` 中两级触发：常规 `request_tokens >= trigger_tokens`（0.9 * maxInput）+ 提前 `projected_total >= projection_trigger_tokens`（0.9 * 0.8 * maxInput = 0.72 * maxInput）
- `_project_future_usage` 估算下一轮 token：`projected = current + tools_tokens + avg_tool_result`
- `avg_tool_result` 从最近 `tool_result_history_max=10` 个 tool_result 估算均值

Cline 的 `buildBudgetProjection`（project.ts L483-672）是压缩**内部**的预算投影（决定保留哪些消息），不是压缩**触发**的提前投影。Cline 的触发只看当前 `requestInputTokens >= requestTriggerTokens`（compaction.ts L312），无提前压缩机制。

**影响**：Charles 能在下一轮 tool_result 注入前提前压缩，避免"下一轮立即超限"。Cline 无此机制，可能在下一轮因 tool_result 注入而超限。这是 Charles 的合理增强。

### 3.5 Charles 扩展：compaction-failed 事件（Stage 11.3 J13）

Charles `events.py` L65 定义 `COMPACTION_FAILED = "compaction-failed"`，`make_compaction_failed` 辅助函数（L580-620）构造 failed 事件，含 `reason`（`"aborted"` / `"fallback_failed"`）+ `error` 字符串 + `compaction_snapshot`。

Cline 无独立 `compaction-failed` 事件。Cline 的 `createContextCompactionPrepareTurn` 在压缩失败时直接 throw 异常（compaction.ts L426），由上层 runtime 处理错误，不 emit 独立 failed 事件。Cline 仅在 `compaction-budget-adjusted` 事件（compaction.ts L526-534）中携带 budget 警告，但这是预算调整而非压缩失败。

**影响**：Charles 的 `compaction-failed` 事件让前端能感知压缩失败并显示提示，Cline 仅在 runtime 层处理错误。Charles 的扩展更友好。

### 3.6 file/image 截断阈值差异

**Cline `truncateToolResultContentForCompaction`（compaction-shared.ts L100-124）**：
- string: `truncateText(content, TOOL_RESULT_CHAR_LIMIT=2000)`
- text block: `truncateText(block.text, TOOL_RESULT_CHAR_LIMIT=2000)`
- file block: `truncateText(block.content, FILE_CONTENT_CHAR_LIMIT=2000)`
- image block: 不截断，保留原值
- 真正的 image 丢弃发生在 budget-projection 的 `dropUnsafeBlocks`（project.ts L243-299）—— 在 live tail 之外丢弃 image/redacted_thinking

**Charles `_truncate_tool_results`（context.py L1853-1947）**：
- string output: 超 `TOOL_RESULT_CHAR_LIMIT=2000` 截断
- list output 中的 FilePart: content 超 `MAX_FILE_DATA_LENGTH=100_000`（100KB base64）清空保留 path
- list output 中的 ImagePart: image 超 `MAX_IMAGE_DATA_LENGTH=50_000`（50KB base64）清空保留 alt_text
- 截断后追加 `TextPart(text="[truncated: file/image data exceeds limit]")` 标记

**差异分析**：
- Cline file 用 2000 字符截断（保留前 2000 字符），Charles 用 100KB 阈值清空（保留 path 不保留 content）
- Cline image 在 compaction 阶段不截断，在 budget-projection 阶段才丢弃；Charles 在 compaction 阶段直接清空超阈值 image
- Charles 的阈值基于 base64 字符数（100KB/50KB），更贴近实际数据量；Cline 用统一的 2000 字符限制

**影响**：Charles 对大文件/大图片更激进（直接清空），Cline 更保守（截断保留前 2000 字符）。两者都达到"防止撑爆上下文"的目的，但行为不同。

**修复建议**：**不建议修改**。Charles 的阈值设计更适合量化场景（PDF/图表数据量大），Cline 的统一限制更适合代码场景。

### 3.7 文件分层架构差异

**Cline 文件分层**（`sdk/packages/core/src/extensions/context/`）：
- `compaction.ts` — 入口 `createContextCompactionPrepareTurn` + `createCompactionStateAwarePrepareTurn` + telemetry
- `compaction-shared.ts` — 常量 + `findCutIndex` + `summarizeToolActivity` + `buildSummaryRequest` + `buildSummaryMessage` + `truncateToolResultContentForCompaction` + `isCompactionSummaryMessage`
- `basic-compaction.ts` — `runBasicCompaction` + `mergeAdjacentUserTurns` + `PRESERVED_ASSISTANT_TEXT_COUNT` + `isPreservedByCompaction`
- `agentic-compaction.ts` — `runAgenticCompaction` + `buildAgenticSummaryInputBudget` + `generateSummary`
- `budget-projection/project.ts` — `buildBudgetProjection` + `BudgetPolicyIntent` + `ProjectionPolicy`
- `budget-projection/types.ts` — 类型定义
- `budget-projection/index.ts` — 导出
- `session/models/session-compaction.ts` — `SessionCompactionState` schema + `projectSessionCompactionState`

**Charles 文件分层**：
- `agent/context.py` — 全部压缩逻辑（`ContextCompactor` 类 + `CompactionStateManager` 类 + 常量 + `is_compaction_summary_message`）+ 系统提示组装（`SystemPromptBuilder` 类 + `build_charles_system_prompt` 函数）
- `agent/budget_policy.py` — `BudgetPolicyIntent` + `ProjectionPolicy` + `apply_budget_policy` + `estimate_protected_token_budget` + `build_budget_projection`（Phase 33.3 抽出）
- `agent/events.py` — 压缩事件常量 + `make_compaction_*` 辅助函数
- `agent/types.py` — `CompactionStateSnapshot` dataclass

**差异**：Cline 把压缩拆成 8 个文件（含 budget-projection 子目录），Charles 集中在 4 个文件。Charles 的 `context.py` 同时包含系统提示组装和压缩（2666 行），职责边界不如 Cline 清晰。

**修复建议**：**可选重构**。若追求与 Cline 文件分层对齐，可把 `ContextCompactor` + `CompactionStateManager` 从 `context.py` 抽出为 `agent/compaction.py`，把 `SystemPromptBuilder` 留在 `context.py`。但当前结构可工作，重构非必须。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P7.1 范围内涉及以下 5 个文件：
- `agent/context.py`（2666 行）
- `agent/budget_policy.py`（约 700 行）
- `agent/events.py`（约 650 行）
- `agent/types.py`（约 421 行）
- `agent/server.py`（约 1700 行，仅压缩相关部分 L407-415 + L1601-1606）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/context.py` | **1 处** | 0 处 | L275：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`——`SystemPromptBuilder.__init__` 的 `extra_sections` 参数 docstring。该参数本身已废弃（"保留参数签名仅为向后兼容，当前无调用方传入"），docstring 说明其源自 nanobot 风格。**属注释残留，不影响压缩功能**（extra_sections 与 ContextCompactor 无关） |
| `agent/budget_policy.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 均对标 Cline（"对标 Cline BudgetPolicyIntent" / "对标 Cline ProjectionPolicy" / "对标 Cline resolveProjectionPolicy" / "对标 Cline findLatestTypedUserMessageIndex" 等） |
| `agent/events.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。压缩事件常量与 `make_compaction_*` 辅助函数均对标 Cline `emitStatusNotice` |
| `agent/types.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。`CompactionStateSnapshot` dataclass 对标 Cline `CompactionStateManager.project()` |
| `agent/server.py` | **3 处** | 0 处 | L2：`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`；L4：`提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`；L28：`对标 nanobot:` + L29：`- routes/chat.py _sse_generator() + _StreamCollectorHook`。**属模块级 docstring 历史说明**，与压缩功能无关（压缩接入在 L407-415，无 nanobot 引用） |

**P7.1 范围内 nanobot 残留总计：4 处注释残留 + 0 处实现逻辑残留。**

### 4.3 残留性质分析

所有 4 处残留均为 **docstring 注释残留**，性质如下：
- **非实现逻辑残留**：`ContextCompactor` / `CompactionStateManager` / `budget_policy` / `events` / `types` 的实现代码中无任何 nanobot 引用，所有逻辑均对标 Cline
- **非压缩相关残留**：4 处残留中 3 处在 `server.py` 模块级 docstring（描述 SSE 服务端历史演进），1 处在 `context.py` 的 `SystemPromptBuilder` 类（描述 `extra_sections` 废弃参数），均与压缩功能无关
- **历史说明性残留**：残留文字形式为"对标 Cline ... + nanobot ..."或"用 AgentRuntime 替换 nanobot"，是迁移过程中的历史说明，不影响当前功能

### 4.4 范围外残留说明

以下文件的 nanobot 残留**超出 P7.1 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20（已审计） |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20（已审计） |
| `agent/skills/skill_tool.py` L18 | 注释残留 | "nanobot 子 agent 隔离执行"对比说明 | P4.x |
| `agent/providers/qwen.py` 多处 | 注释残留 | 对标 nanobot openai_compat_provider | P1.x |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |

---

## 五、修复建议

### 5.1 低优先级：清理 context.py L275 nanobot 注释残留

**问题**：`agent/context.py` L275 的 `extra_sections` 参数 docstring 含 "nanobot 风格的额外段落" 说明。

**修复建议**：将 L275 改为：
```python
extra_sections: [已废弃] 早期版本的额外段落扩展机制，Cline 无此概念。
                保留参数签名仅为向后兼容，当前无调用方传入。
```

**权衡**：此残留不影响功能，仅是 docstring 历史说明。修改可降低维护者困惑，但不修改也无实际影响。建议在下次触碰该文件时顺手清理。

### 5.2 低优先级：清理 server.py 模块级 docstring nanobot 残留

**问题**：`agent/server.py` L2/L4/L28-29 的模块级 docstring 含 "对标 nanobot routes/chat.py" / "用 AgentRuntime 替换 nanobot" / "对标 nanobot: routes/chat.py _sse_generator()" 说明。

**修复建议**：将模块级 docstring 改为只对标 Cline：
```python
"""SSE 服务端 — 对标 Cline server

提供 /api/chat/stream SSE 端点，基于 AgentRuntime 实现。
保持与现有前端完全兼容的 SSE 事件格式。
...
对标 Cline:
    - sdk/packages/core/src/extensions/tools/executors/web-search.ts
    - SSE 事件流设计
"""
```

**权衡**：此残留属模块级历史说明，不影响功能。修改可降低维护者困惑。建议在下次触碰该文件时顺手清理。

### 5.3 不建议修改：basic 策略实现路径差异

**问题**：Cline basic 策略保留 typed user + `<SYSTEM_NOTICE>` 块；Charles basic 策略产生统一 `compaction_summary` 消息。

**修复建议**：**不建议修改**。Charles 的统一摘要设计更易维护，且 agentic 是默认策略（basic 仅 fallback）。若强行对齐 Cline basic 策略，需引入 `mergeAdjacentUserTurns` + `isPreservedByCompaction` + `markPreservedByCompaction` 等复杂逻辑，增加 300+ 行代码，收益有限。

### 5.4 不建议修改：state-aware 持久化机制差异

**问题**：Cline 用 SHA-256 hash 验证源消息完整性；Charles 用整数偏移。

**修复建议**：**不建议修改**。Charles 的整数偏移 + rollback 清理策略在当前场景下足够。引入 hash 验证需额外维护源消息哈希计算逻辑，对 Python 生态过度设计。Charles 已在 `/rollback` 主动调用 `CompactionStateManager().clear(session_id)` 缓解偏移错位风险。

### 5.5 可选重构：文件分层对齐（非必须）

**问题**：Charles `context.py` 同时包含系统提示组装（`SystemPromptBuilder`）和压缩（`ContextCompactor` + `CompactionStateManager`），2666 行，职责边界不如 Cline 清晰。

**修复建议**：**可选重构**。把 `ContextCompactor` + `CompactionStateManager` + `is_compaction_summary_message` + 压缩常量从 `context.py` 抽出为 `agent/compaction.py`，把 `SystemPromptBuilder` + `build_charles_system_prompt` + `is_charles_provider` 留在 `context.py`。

**权衡**：重构能提升代码可读性，但需更新所有 import 路径（`from agent.context import ContextCompactor` → `from agent.compaction import ContextCompactor`）。当前结构可工作，重构非必须。

---

## 六、验证方法

### 6.1 常量对齐验证

1. 读取 Cline `compaction-shared.ts` L13-23 + L438 + basic-compaction.ts L60，确认 8 个常量值
2. 读取 Charles `context.py` L940-977，确认对应常量值
3. 逐项比对：trigger_ratio=0.9 / maxInput=128000 / preserve_recent_tokens=20000 / summary_max_tokens=1024 / tool_result_char_limit=2000 / file_content_char_limit=2000 / preserved_assistant_text_count=3 / command_summary_char_limit=100

### 6.2 _find_cut_index 算法验证

1. 读取 Cline `compaction-shared.ts` L317-350 `findCutIndex`，确认步骤：从尾部累计 token → 取 `lastTurnStartIndex` → `Math.min(candidate, lastTurnStartIndex)` → 向前调整到 `isSafeCutBoundary`
2. 读取 Charles `context.py` L1994-2057 `_find_cut_index`，确认相同步骤
3. 确认 `_is_safe_cut_boundary`（Charles L1949-1992）与 `isSafeCutBoundary`（Cline L313-315）语义一致：assistant 安全 / turn_start user 安全 / tool_result-only user 不安全 / compaction_summary 不安全

### 6.3 _summarize_tool_activity 验证

1. 读取 Cline `compaction-shared.ts` L535-609 `summarizeToolActivity`，确认按 tool_name 分流到 readFiles/editedFiles/commands
2. 读取 Charles `context.py` L2117-2271 `_summarize_tool_activity`，确认相同分流逻辑
3. 确认 Charles `_summarize_tool_activity_v2`（L2059-2115）优先从 `FileContextTracker` 取文件列表，tracker 无数据时回退到消息扫描

### 6.4 agentic + basic fallback 验证

1. 读取 Cline `compaction.ts` L419-437，确认 try/catch 中 agentic 失败且非 abort 时回退到 basic
2. 读取 Charles `context.py` L1587-1660，确认 `before_model` 中 if model 存在用 agentic，失败 except 回退到 basic
3. 确认双方 AbortedError/AbortError 都不触发 fallback

### 6.5 CompactionStateManager 验证

1. 读取 Cline `compaction.ts` L566-623 `createCompactionStateAwarePrepareTurn` + `session-compaction.ts` L25-181，确认 zod schema + hash 验证
2. 读取 Charles `context.py` L989-1164 `CompactionStateManager`，确认 JSON 持久化 + 整数偏移投影 + 生命周期方法
3. 确认 Charles 在 `/rollback` 时调用 `CompactionStateManager().clear(session_id)`（server.py L1603）

### 6.6 abort_signal 透传验证

1. 读取 Cline `compaction.ts` L40 + L83-94 + L422-427，确认 `abortSignal` 透传 + `isCompactionCancellation` 检查 + abort 不回退
2. 读取 Charles `context.py` L1505 + L1598-1599 + L1606-1629 + L1761-1762，确认 `abort_signal` 透传 + `AbortedError` 不回退
3. 确认 Charles fallback 路径也在关键步骤前检查 `abort_signal.is_set()`（L1761/L1768/L1781/L1811/L1816）

### 6.7 file/image 截断验证

1. 读取 Cline `compaction-shared.ts` L100-124 `truncateToolResultContentForCompaction`，确认 string/text/file 用 2000 字符截断、image 不截断
2. 读取 Charles `context.py` L1853-1947 `_truncate_tool_results`，确认 string 用 2000 字符截断、FilePart 用 100KB 阈值清空、ImagePart 用 50KB 阈值清空
3. 确认 Charles 截断后追加 `[truncated]` 标记（L1937-1939）

### 6.8 nanobot 残留验证

1. Grep `agent/context.py` 搜索 `nanobot`（case-insensitive），确认仅 L275 一处注释残留
2. Grep `agent/budget_policy.py` 搜索 `nanobot`，确认 0 匹配
3. Grep `agent/events.py` 搜索 `nanobot`，确认 0 匹配
4. Grep `agent/types.py` 搜索 `nanobot`，确认 0 匹配
5. Grep `agent/server.py` 搜索 `nanobot`，确认 L2/L4/L28 三处注释残留（与压缩功能无关）

---

## 七、附录

### 7.1 Cline 上下文压缩架构图

```
createContextCompactionPrepareTurn (compaction.ts L248-564)
    ├── 入口: prepareTurn callback
    ├── 触发: requestInputTokens >= maxInputTokens * 0.9
    ├── 策略选择: BUILTIN_COMPACTION_STRATEGIES[strategy]
    │   ├── basic → runBasicCompaction (basic-compaction.ts)
    │   │   ├── 保留 typed user 消息
    │   │   ├── 保留 frozen prior compaction output
    │   │   ├── 保留最新 typed turn 的尾部消息（snap 到 assistant）
    │   │   ├── 保留旧 turn 的 concluding assistant answer
    │   │   ├── mergeAdjacentUserTurns 折叠 dropped 工具活动为 <SYSTEM_NOTICE>
    │   │   └── buildBudgetProjection 截断到 target
    │   └── agentic → runAgenticCompaction (agentic-compaction.ts)
    │       ├── findCutIndex 找安全切割点
    │       ├── buildAgenticSummaryInputBudget 预算投影
    │       ├── buildSummaryRequest 构造 LLM prompt
    │       ├── generateSummary 调用 LLM
    │       ├── ensureFilesSection 确保含 Files 段
    │       └── buildSummaryMessage 生成 compaction_summary 消息
    ├── fallback: agentic 失败且非 abort → 回退 basic
    ├── telemetry: captureCompactionExecuted / captureCompactionSkipped
    └── emitStatusNotice: compacting / compacted / compaction-skipped

createCompactionStateAwarePrepareTurn (compaction.ts L566-623)
    ├── getState() 读取 SessionCompactionState
    ├── projectSessionCompactionState 投影（hash 验证）
    ├── 调用 inner compact
    └── saveState() 保存新 SessionCompactionState

SessionCompactionState (session-compaction.ts)
    ├── zod schema 校验
    ├── source_prefix_hash (SHA-256) 验证源消息未变
    ├── source_last_message_key 兜底 boundary
    └── messages + system_prompt 持久化
```

### 7.2 Charles 上下文压缩架构图

```
ContextCompactor (context.py L1185-2652)
    ├── before_model hook (L1477-1717)
    │   ├── 加载 CompactionState（state-aware）
    │   ├── should_compact 判断（两级触发）
    │   │   ├── 常规: request_tokens >= trigger_tokens (0.9 * maxInput)
    │   │   └── 提前: projected_total >= projection_trigger_tokens (0.72 * maxInput)
    │   ├── emit compaction-started 事件
    │   ├── state_manager.start_compaction()
    │   ├── 策略选择
    │   │   ├── agentic: model 存在 → compact(summarize_func=_llm_summarize)
    │   │   │   ├── _truncate_tool_results 截断
    │   │   │   ├── _find_cut_index 安全切割
    │   │   │   ├── _summarize_tool_activity_v2（优先 FileContextTracker）
    │   │   │   ├── _build_summary_request 构造 LLM prompt
    │   │   │   ├── _llm_summarize 调用 LLM
    │   │   │   ├── _ensure_files_section
    │   │   │   ├── _build_dropped_work_summary_block <SYSTEM_NOTICE>
    │   │   │   └── 生成 compaction_summary 消息
    │   │   └── basic fallback: model 为 None 或 agentic 失败
    │   │       └── compact(summarize_func=None) → _simple_summary
    │   ├── AbortedError 不回退
    │   ├── state_manager.finish_compaction()
    │   ├── state_manager.save()
    │   └── emit compaction-completed 事件
    │
    ├── should_compact (L1276-1367)
    │   ├── 常规触发: request_tokens >= trigger_tokens
    │   └── budget_projection 提前触发: projected >= projection_trigger_tokens
    │
    ├── _project_future_usage (L1369-1475)
    │   ├── apply_budget_policy（按 intent 丢弃 thinking 块）
    │   ├── tools_tokens = sum(tool.name + description + input_schema)
    │   ├── avg_tool_result = mean(最近 10 个 tool_result)
    │   └── projected = current + tools + avg_tool_result
    │
    └── get_stats (L2600-2652)
        └── 返回 budget_projection 统计信息

CompactionStateManager (context.py L989-1164)
    ├── load/save/clear JSON 文件持久化
    ├── start_compaction / finish_compaction / fail_compaction 生命周期
    ├── project() 返回 CompactionStateSnapshot
    └── system_prompt 保留（不参与压缩）

budget_policy.py
    ├── BudgetPolicyIntent 枚举（3 值，对标 Cline）
    ├── ProjectionPolicy 矩阵
    ├── apply_budget_policy 按 intent 丢弃 thinking/unsafe 块
    ├── estimate_protected_token_budget 估算受保护 token
    └── build_budget_projection 预算投影

events.py
    ├── COMPACTION_STARTED / COMPACTION_COMPLETED / COMPACTION_SKIPPED
    ├── COMPACTION_FAILED（Charles 扩展，Cline 无）
    ├── COMPACTION_BUDGET_ADJUSTED
    └── make_compaction_* 辅助函数
```

### 7.3 双方常量集合对比

| 常量 | Cline 值 | Cline 位置 | Charles 值 | Charles 位置 | 一致性 |
|------|---------|-----------|-----------|-------------|--------|
| COMPACTION_TRIGGER_RATIO | 0.9 | compaction-shared.ts L17 | 0.9 | context.py L941 | 完全一致 |
| DEFAULT_MAX_INPUT_TOKENS | 128_000 | compaction-shared.ts L13 | 128000 | context.py L944 | 完全一致 |
| DEFAULT_PRESERVE_RECENT_TOKENS | 20_000 | compaction-shared.ts L19 | 20000 | context.py L947 | 完全一致 |
| DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS | 1_024 | compaction-shared.ts L20 | 1024 | context.py L953 | 完全一致 |
| TOOL_RESULT_CHAR_LIMIT | 2_000 | compaction-shared.ts L21 | 2000 | context.py L962 | 完全一致 |
| FILE_CONTENT_CHAR_LIMIT | 2_000 | compaction-shared.ts L22 | 2000 | context.py L965 | 完全一致 |
| COMMAND_SUMMARY_CHAR_LIMIT | 100 | compaction-shared.ts L438 | 100 | context.py L971 | 完全一致 |
| PRESERVED_ASSISTANT_TEXT_COUNT | 3 | basic-compaction.ts L60 | 3 | context.py L968 | 完全一致 |
| DEFAULT_TARGET_RATIO | 0.7 | compaction-shared.ts L18 | 无 | — | Charles 无对应（Cline 用于 resolveAutoRequestTargetTokens） |
| CONTEXT_WINDOW_INPUT_RATIO | 0.9 | compaction-shared.ts L15 | 无 | — | Charles 无对应（Cline 用于 resolveEffectiveMaxInputTokens） |
| MIN_TRUNCATED_MESSAGE_TOKENS | 8 | compaction-shared.ts L23 | 无 | — | Charles 无对应 |
| LONG_CONVERSATION_TARGET_RATIO | 0.5 | compaction.ts L81 | 无 | — | Charles 无对应 |
| _DEFAULT_PROJECTION_RATIO | 无 | — | 0.8 | context.py L957 | Charles 扩展（提前压缩触发比例） |
| _DEFAULT_TOOL_RESULT_HISTORY_MAX | 无 | — | 10 | context.py L959 | Charles 扩展（tool_result 历史样本数） |
| MAX_FILE_DATA_LENGTH | 无 | — | 100_000 | context.py L976 | Charles 扩展（file base64 截断阈值） |
| MAX_IMAGE_DATA_LENGTH | 无 | — | 50_000 | context.py L977 | Charles 扩展（image base64 截断阈值） |

### 7.4 双方 metadata.kind 对比

| 场景 | Cline metadata.kind | Charles metadata.kind |
|------|--------------------|-----------------------|
| agentic 压缩摘要消息 | `compaction_summary`（compaction-shared.ts L734） | `compaction_summary`（context.py L1838） |
| basic 压缩折叠消息 | `compaction`（basic-compaction.ts L638-648） | `compaction_summary`（与 agentic 相同） |
| preserved 标记 | `compaction: "preserved"`（basic-compaction.ts L385/L394-411） | 无（用 CompactionStateManager.compacted_count 偏移替代） |
| CompactionSummaryMetadata.details 字段 | `{ readFiles, modifiedFiles }`（compaction-shared.ts L26-28） | `{ readFiles, editedFiles, commands }`（context.py L1841-1844） |

**差异说明**：
- Cline basic 策略用 `kind: "compaction"`（非 `compaction_summary`）标记折叠后的首条 typed user 消息，Charles basic 策略用同一 `kind: "compaction_summary"` 标记摘要消息
- Cline `details` 字段名为 `modifiedFiles`，Charles 为 `editedFiles`（语义相同，命名不同）
- Charles `details` 额外含 `commands` 字段（Cline 的 commands 在 `<SYSTEM_NOTICE>` 块中，不在 metadata.details）
