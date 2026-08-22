# Phase 7.2 Budget Projection 预算投影对比报告

## 1. 执行摘要

Cline 与 Charles 在 Budget Projection（预算投影）机制上的对标**整体已落地**：双方都实现了同名的 `BudgetPolicyIntent` 枚举、`ProjectionPolicy` 字段集、`resolve_projection_policy` 策略矩阵、`find_latest_typed_user_message_index` / `find_protected_tail_start_index` / `drop_thinking_blocks` / `apply_budget_policy` 等核心函数，且 `buildBudgetProjection` 4 步流水线（drop_thinking → drop_unsafe → truncate_text → closure_removal）在两侧算法等价。

但双侧对"预算投影"概念的**职责划分存在显著错位**：

- **Cline**：`budget-projection` 模块（`extensions/context/budget-projection/`）仅作为**压缩执行阶段**的内部工具——当压缩已被触发后，由 `basic-compaction.ts`（L606-619）与 `agentic-compaction.ts`（L53-58）调用 `buildBudgetProjection` 决定"在 targetTokens 内保留哪些块、丢弃哪些块、截断哪些文本"。Cline 的压缩**触发**只用 `requestInputTokens >= maxInputTokens * COMPACTION_TRIGGER_RATIO`（compaction.ts L312，单层 0.9 阈值），**无提前压缩机制**。
- **Charles**：`budget_policy.py` 完整移植了 Cline 的 `buildBudgetProjection` 4 步流水线，**同时**在 `context.py::_project_future_usage` 中新增了一个 Cline 不存在的"提前压缩触发器"——通过 `enable_budget_projection=True` + `projection_ratio=0.8`，当 `projected_total >= trigger_tokens * 0.8` 时提前触发压缩，并用 `_last_compaction_reason` 字段区分 `budget_projection` 与 `threshold_exceeded` 两种触发来源。

进一步差异：
1. `apply_budget_policy`（7.2.7）与 `estimate_protected_token_budget`（7.2.8）在 Charles 中是**独立导出函数**，Cline 中对应逻辑内嵌于 `buildBudgetProjection`，未对外暴露——Charles 多了对外 API。
2. `_project_future_usage`（7.2.9）、`projection_ratio`（7.2.10）、提前压缩触发（7.2.11）、`compaction_reason` 区分（7.2.12）在 Cline 中**均无对应实现**——这 4 项是 Charles 独有增强，**不构成对齐缺口**，属于设计差异。
3. Charles 的 `build_budget_projection` 4 步流水线**未被 `compact()` 实际调用**——Charles 的 `compact()` 仍走 `_find_cut_index + _simple_summary` 路径，4 步流水线仅作为 `get_stats()` 统计与 `apply_budget_policy` 工具函数被引用；而 Cline 的 `buildBudgetProjection` 是 `runBasicCompaction` 的核心安全阀。

nanobot 残留检查结论：在 Budget Projection 直接相关代码（`agent/budget_policy.py` + `agent/context.py::_project_future_usage` / `should_compact` / `get_stats`）中**未发现 nanobot 残留**；间接相关的 `agent/context.py` L275 有 1 处 nanobot 注释残留（类型 A：废弃标注，与 Budget Projection 无关），**未发现实现逻辑残留**。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P7.2 章节定义的 12 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 7.2.1 | BudgetPolicyIntent 枚举 | `budget-projection/types.ts` L3-6 — `"agentic_summary"` / `"basic_compaction_projection"` / `"normal_provider_request"` 字面量联合类型 | `budget_policy.py` L42-52 — `BudgetPolicyIntent(str, Enum)` 三值同名（snake_case 值与 Cline 字面量一致） | 枚举值与语义完全一致；Cline 用 TS 字面量联合类型（编译期校验），Charles 用 `str, Enum` | 强对齐 |
| 7.2.2 | ProjectionPolicy 字段 | `budget-projection/project.ts` L17-22 — `protectLatestTypedUser` / `protectLiveTailFromDrop` / `dropUnsafeOutsideLiveTail` / `dropThinkingBlocks` 四字段 | `budget_policy.py` L55-68 — `ProjectionPolicy` dataclass 同名四字段（snake_case） | 字段名命名风格不同（camelCase vs snake_case），语义完全一致；两者均默认 `False` | 强对齐 |
| 7.2.3 | resolve_projection_policy 逻辑 | `project.ts` L24-42 — `switch(intent)`，agentic_summary / basic_compaction_projection 返回全 True，normal_provider_request 返回 drop_unsafe=False / drop_thinking=False | `budget_policy.py` L71-100 — `if intent in (AGENTIC_SUMMARY, BASIC_COMPACTION_PROJECTION)` 返回全 True，else 返回 drop_unsafe=False / drop_thinking=False | 策略矩阵完全一致；Cline 用 switch，Charles 用 if | 强对齐 |
| 7.2.4 | find_latest_typed_user_message_index | `project.ts` L81-91 — 从尾向前找 `role === "user"` 且非 `isToolResultOnlyUserMessage` | `budget_policy.py` L116-131 — 同逻辑，倒序遍历找 `role=USER` 且非 `is_tool_result_only_user_message` | 算法一致；Charles 额外导出 `find_first_typed_user_message_index`（L134-140）对齐 Cline 内部 `findFirstTypedUserMessageIndex`（L93-103，未导出） | 强对齐 |
| 7.2.5 | find_protected_tail_start_index | `project.ts` L141-168 — 收集所有 `tool_result` 的 `tool_use_id`，从尾向前找第一条含未配对 `tool_use` 的消息 | `budget_policy.py` L154-183 — 收集所有 `ToolResultPart` 的 `tool_call_id`，从尾向前找第一条含未配对 `ToolCallPart` 的消息 | 算法一致；字段名不同（`tool_use_id` / `tool_call_id`） | 强对齐 |
| 7.2.6 | drop_thinking_blocks | `project.ts` L301-327 — 移除 `block.type === "thinking"`，记录 `dropped_block` 动作（含 `originalSize` / `finalSize`） | `budget_policy.py` L186-247 — 移除 `ReasoningPart`，记录 `dropped_block` 动作（Stage 7.7 增强 `actions` / `original_indexes` 参数） | Cline 处理 `thinking` 块；Charles 处理 `ReasoningPart`（含 `text` + `redacted` 字段）；审计动作结构等价 | 强对齐 |
| 7.2.7 | apply_budget_policy | Cline **无独立函数**；逻辑内嵌于 `buildBudgetProjection` L510-519（step 1: dropThinking + pruneEmpty） | `budget_policy.py` L250-293 — 独立函数 `apply_budget_policy(messages, intent, actions, prune_empty)` | Charles 抽取为独立函数，支持 `prune_empty=False` 关闭空消息裁剪；Cline 无独立函数 | 弱对齐（Charles 多了独立 API） |
| 7.2.8 | estimate_protected_token_budget | Cline **无此独立函数**；protected token 估算分散在 `buildBudgetProjection` L520-525（latest_typed_user_index + protected_tail_start_index 计算）与 `basic-compaction.ts` L482-488（typed prompts + frozen + keptExtra 累加） | `budget_policy.py` L296-357 — 独立函数返回 dict 含 `total_tokens` / `protected_tokens` / `available_for_truncation` / `latest_typed_user_index` / `protected_tail_start_index` | Charles 提供独立 API 供 `get_stats()` 调用；Cline 无对外暴露的等价 API | 弱对齐（Charles 多了对外 API） |
| 7.2.9 | _project_future_usage 公式 | Cline **无此机制** — 压缩触发只用 `requestInputTokens >= requestTriggerTokens`（compaction.ts L312） | `context.py` L1369-1475 — `projected = current_tokens + tools_tokens + avg_tool_result`，avg_tool_result 取最近 `tool_result_history_max`（默认 10）个 ToolResultPart 的 output token 均值 | **Charles 独有**：基于未来一轮 tool_result 注入的提前压缩投影；Cline 无此概念 | 缺失（Charles 新增） |
| 7.2.10 | projection_ratio 默认值 | Cline **无此参数** | `context.py` L957 — `_DEFAULT_PROJECTION_RATIO = 0.8`，`_projection_trigger_tokens = _trigger_tokens * 0.8` | **Charles 独有**：0.8 表示 trigger_tokens 的 80% 即触发提前压缩；Cline 无等价参数 | 缺失（Charles 新增） |
| 7.2.11 | 提前压缩触发条件 | Cline **无此触发路径**；仅有 `shouldCompact = requestInputTokens >= requestTriggerTokens`（compaction.ts L312，单层 0.9 阈值） | `context.py` L1341-1365 — `enable_budget_projection and tools is not None` 且 `projected_total >= self._projection_trigger_tokens` 时触发，记 `_last_compaction_reason = "budget_projection"` | **Charles 独有**：双层触发——常规阈值 + 提前投影；Cline 单层阈值 | 缺失（Charles 新增） |
| 7.2.12 | compaction_reason 标记 | `compaction.ts` L385-386 — `statusReason = mode === "manual" ? "manual_compaction" : "auto_compaction"`；telemetry 通过 `captureCompactionExecuted` 上报 strategy / mode，**无 budget_projection 维度** | `context.py` L1272 / L1337 / L1364 — `_last_compaction_reason` 取值 `threshold_exceeded` / `budget_projection` / `unknown`；`get_stats()` 在 `budget_projection.last_compaction_reason` 字段返回 | **Charles 独有**：区分触发来源；Cline 只区分 manual / auto | 缺失（Charles 新增） |

## 3. 重点差距详细说明

### 差距 1：Budget Projection 在两侧承担的职责不同（对应对比项 7.2.7-7.2.12）

**Cline 设计**：`budget-projection` 模块是**压缩执行阶段**的内部工具。压缩触发链路为：

1. `compaction.ts::createContextCompactionPrepareTurn` 返回的 `prepareTurn` 回调在每次 LLM 请求前被调用
2. 计算 `requestInputTokens`（含 system_prompt + messages + tools）
3. `shouldCompact = requestInputTokens >= maxInputTokens * COMPACTION_TRIGGER_RATIO`（L312，单层 0.9 阈值）
4. 触发后，根据 `strategy`（basic / agentic）调用 `runBasicCompaction` 或 `runAgenticCompaction`
5. 这两个 runner 内部调用 `buildBudgetProjection` 决定在 `targetTokens` 内保留什么、丢弃什么：
   - `basic-compaction.ts` L606-619：`buildBudgetProjection({messages: keptMessages, targetTokens: projectionTargetTokens, policyIntent: "basic_compaction_projection", ...})`
   - `agentic-compaction.ts` L53-58：`buildBudgetProjection({messages, targetTokens, policyIntent: "agentic_summary", ...})`

Cline 的 `budget-projection` **不参与触发决策**，只参与"已决定压缩后"的内容选择。Cline 无 `_project_future_usage`、无 `projection_ratio`、无 `tool_result_history_max`、无 `_last_compaction_reason`。

**Charles 设计**：Charles 在 `context.py` 中新增了一个 Cline 不存在的"提前压缩"机制：

1. `should_compact()` 第一层（L1336-1338）：`request_tokens >= _trigger_tokens`（与 Cline 一致，记 `threshold_exceeded`）
2. `should_compact()` 第二层（L1341-1365）：`enable_budget_projection and tools is not None` 时调用 `_project_future_usage(messages, tools, total_tokens, intent)`：
   - 公式：`projected = current_tokens + tools_tokens + avg_tool_result`
   - `tools_tokens` = 每个 tool 的 `name + description + input_schema` JSON 估算
   - `avg_tool_result` = 最近 `tool_result_history_max`（默认 10）个 `ToolResultPart` 的 output token 均值
   - 无历史样本时 `avg_tool_result = 0`（保守策略，避免误触发）
3. 若 `projected_total >= _projection_trigger_tokens`（= `_trigger_tokens * projection_ratio`，默认 0.8），触发压缩并记 `_last_compaction_reason = "budget_projection"`

Charles 同时在 `budget_policy.py` 中完整移植了 Cline 的 `buildBudgetProjection` 4 步流水线（step 1: drop_thinking + prune_empty → step 2: drop_unsafe + prune_empty → step 3: truncate_text 从尾到头 → step 4: collect_closure + remove_messages_at 从头丢闭包），但该流水线**未被 Charles 的 `compact()` 实际调用**——Charles 的 `compact()` 仍走 Phase 16 重构后的 `_find_cut_index + _summarize_tool_activity + _simple_summary` / LLM summary 路径，与 Cline `runBasicCompaction` 的"typed prompts + frozen + keptExtra + buildBudgetProjection safety valve"路径不同。

**影响**：
- Charles 的提前压缩机制是**有意的增强**，避免"下一轮 tool_result 注入后立即超限"的尴尬场景。这是 Cline 未实现的设计。
- Charles 的 `build_budget_projection` 4 步流水线虽然忠实移植，但与 `compact()` 的实际压缩路径解耦，仅作为 `get_stats()` 的统计信息和 `apply_budget_policy` 的工具函数被引用。Cline 的 `buildBudgetProjection` 则是 `runBasicCompaction` 的核心安全阀。

### 差距 2：apply_budget_policy 与 estimate_protected_token_budget 的对外 API 形态不同（对应对比项 7.2.7、7.2.8）

**Cline 设计**：

- `apply_budget_policy` 无独立函数，逻辑内嵌于 `buildBudgetProjection` L510-519（step 1）：
  ```typescript
  if (policy.dropThinkingBlocks) {
      const prunedThinking = pruneEmptyMessages(
          dropThinkingBlocks(messages, originalIndexes, actions),
          originalIndexes,
          actions,
          "unsafe_to_truncate",
      );
      messages = prunedThinking.messages;
      originalIndexes = prunedThinking.originalIndexes;
  }
  ```
- `estimate_protected_token_budget` 无独立函数，protected token 估算分散在 `buildBudgetProjection` L520-525（`latestTypedUserIndex` + `protectedTailStartIndex` 计算）和 `basic-compaction.ts` L482-488（typed prompts + frozen + keptExtra 累加）。

**Charles 设计**：

- `apply_budget_policy`（`budget_policy.py` L250-293）是独立导出函数，签名 `apply_budget_policy(messages, intent, actions=None, prune_empty=True)`，支持 `prune_empty=False` 关闭空消息裁剪（保留空消息以维持索引对齐）。
- `estimate_protected_token_budget`（`budget_policy.py` L296-357）是独立导出函数，返回 dict 含 5 个字段，供 `get_stats()` 在 `budget_projection` 子字段中返回给前端。

**差异分析**：

| 维度 | Cline | Charles |
|------|-------|---------|
| apply_budget_policy | 内嵌于 buildBudgetProjection step 1 | 独立导出函数 |
| estimate_protected_token_budget | 分散在两处，无对外 API | 独立导出函数，返回 dict |
| 调用方 | buildBudgetProjection 内部 | `_project_future_usage`（间接）+ `get_stats`（直接） |

**影响**：Charles 的独立 API 设计便于在 `get_stats()` 中向前端暴露预算投影信息，但与 `compact()` 路径解耦，导致 4 步流水线未在实际压缩中生效。

### 差距 3：build_budget_projection 4 步流水线的调用路径不同（不在对比表内，但属于任务要求）

**Cline 设计**：`buildBudgetProjection` 是 `runBasicCompaction`（basic-compaction.ts L606-619）与 `runAgenticCompaction`（agentic-compaction.ts L53-58）的核心安全阀——压缩主流程（typed prompts + frozen + keptExtra）完成后，调用 `buildBudgetProjection` 确保最终消息列表不超过 `targetTokens`，若仍超限则 `status === "failed"` 但仍返回降级结果。

**Charles 设计**：`build_budget_projection`（`budget_policy.py` L662-840）忠实移植了 Cline 的 4 步流水线，但**未被 `compact()` 实际调用**。`compact()` 仍走 `_find_cut_index + _simple_summary` / LLM summary 路径（context.py L1719-1813），无 `build_budget_projection` 安全阀。

**影响**：Charles 的 `build_budget_projection` 4 步流水线虽然算法正确，但实际不参与压缩——压缩后消息可能仍超 `trigger_tokens`，无降级处理。Cline 的 `buildBudgetProjection` 则确保压缩后必然 ≤ `targetTokens`（或在保护项过多时返回 `failed` 状态）。

## 4. nanobot 残留检查

### 检查范围

在 Budget Projection 直接相关代码（`agent/budget_policy.py` + `agent/context.py` 中 `_project_future_usage` / `should_compact` / `get_stats` / `before_model` 的 budget-projection 分支）中检查 nanobot 残留。`budget_policy.py` 全文无 nanobot 残留（纯 Cline 对标实现）。`context.py` 在 budget-projection 相关代码段中无 nanobot 残留，但在文件其他位置发现 1 处 nanobot 注释残留。

### 注释残留分类

#### 类型 A：废弃标注

形式：`[已废弃] nanobot 风格`

出现在：
- `agent/context.py` L275（`SystemPromptBuilder.__init__` 的 `extra_sections` 参数 docstring）："extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。"

**性质**：明确标注已废弃的参数说明，属于**有意的废弃保留**，与 Budget Projection 机制无关（属于 SystemPromptBuilder 的参数），不影响运行时行为。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。Budget Projection 相关的全部代码均基于 Cline 对标设计：

- `agent/budget_policy.py` 全文对标 Cline `budget-projection/types.ts` + `project.ts`，无 nanobot 代码
- `agent/context.py` 的 `_project_future_usage` / `should_compact` / `before_model` 中的 budget-projection 分支为 Charles 独有增强，无 nanobot 代码
- `agent/context.py::get_stats` 的 `budget_projection` 统计字段为 Charles 独有增强，无 nanobot 代码

### 残留风险评估

| 残留类型 | 文件数 | 风险等级 | 处理建议 |
|---------|--------|---------|---------|
| 类型 A（废弃标注） | 1 | 低 | 可在下个版本删除废弃参数 `extra_sections` |

## 5. 修复建议

### P0（高优先级，影响正确性）

无。Charles 的 budget-projection 实现功能完整：
- `build_budget_projection` 4 步流水线忠实对标 Cline
- `_project_future_usage` 提前压缩机制是**有意的增强**，不是 bug
- `_last_compaction_reason` 区分触发来源，便于调试

### P1（中优先级，影响一致性）

**建议 1：让 `compact()` 调用 `build_budget_projection` 作为安全阀**

参考 Cline `basic-compaction.ts` L606-619，在 Charles `compact()` 的 `_find_cut_index + _simple_summary` 路径之后，调用 `build_budget_projection(messages, target_tokens, BudgetPolicyIntent.BASIC_COMPACTION_PROJECTION)` 作为安全阀，确保压缩后消息不超过 `trigger_tokens`。

**收益**：Charles 的 `build_budget_projection` 4 步流水线（已忠实移植）能真正生效，避免"压缩后仍超限"的边缘情况。

**改动范围**：`context.py::compact()` 末尾增加 `build_budget_projection` 调用，处理 `BudgetProjectionResult.status == "failed"` 时的日志告警。

**注意**：保留现有 `_simple_summary` 路径作为主压缩逻辑，`build_budget_projection` 仅作为安全阀（与 Cline basic-compaction.ts 用法一致）。

### P2（低优先级，改善可观测性）

**建议 2：在 `before_model` 中区分 `budget_projection` 触发的事件**

参考 Charles 已有的 `_last_compaction_reason` 字段，在 `make_compaction_started` 事件中传入 `reason="budget_projection"`（当 `_last_compaction_reason == "budget_projection"` 时），让前端能区分"阈值触发"与"提前投影触发"。

**收益**：前端 UI 能展示更精确的压缩原因，便于用户理解为什么在 token 用量未达 90% 时就触发了压缩。

**改动范围**：`context.py::before_model` 中 `make_compaction_started` 调用，`reason` 字段改为 `self._last_compaction_reason or "auto_compaction"`。

## 6. 验证方法建议

### 验证方法 1：BudgetPolicyIntent 策略矩阵对比

构造 3 种 intent 场景（`agentic_summary` / `basic_compaction_projection` / `normal_provider_request`），分别调用 Cline `resolveProjectionPolicy(intent)` 与 Charles `resolve_projection_policy(intent)`，对比返回的 4 个字段值。

**预期**：3 种 intent 返回的策略矩阵完全一致：
- `agentic_summary` 与 `basic_compaction_projection` 返回全 True（4 个字段均为 True）
- `normal_provider_request` 返回 `protect_latest_typed_user=True` / `protect_live_tail_from_drop=True` / `drop_unsafe_outside_live_tail=False` / `drop_thinking_blocks=False`

### 验证方法 2：buildBudgetProjection 4 步流水线对比

构造含以下元素的测试消息列表：
- 含 `thinking` / `ReasoningPart` 块的 assistant 消息
- 含 `image` / `redacted_thinking` 块的消息
- 含 `tool_use` + `tool_result` 配对的消息
- 含未配对 `tool_use` 的尾部消息
- 含超长文本的消息

分别调用 Cline `buildBudgetProjection({messages, targetTokens, policyIntent, estimateMessageTokens})` 与 Charles `build_budget_projection(messages, target_tokens, intent, estimate_tokens_fn)`，对比：
- `status`（ok / failed）
- `actions` 列表（kind / path / reason）
- `live_tail_handling` / `liveTailHandling`
- `estimated_tokens` / `estimatedTokens`
- `warnings`

**预期**：4 步流水线（drop_thinking → drop_unsafe → truncate_text → closure_removal）的输出在两侧等价，仅字段命名风格不同（camelCase vs snake_case）。

### 验证方法 3：提前压缩触发验证（Charles 独有，对应对比项 7.2.11）

构造场景：
- `max_input_tokens=128000`, `trigger_ratio=0.9` → `_trigger_tokens=115200`
- `projection_ratio=0.8` → `_projection_trigger_tokens=92160`
- 当前消息 token 数 = 80000（< 115200，不触发常规阈值）
- tools 定义 token 数 = 5000
- 最近 10 个 tool_result 平均 token 数 = 8000
- `projected = 80000 + 5000 + 8000 = 93000 >= 92160` → 触发提前压缩

验证 `_last_compaction_reason == "budget_projection"`，且 `get_stats()["budget_projection"]["last_compaction_reason"]` 返回 `"budget_projection"`。

**预期**：Charles 在 token 用量 80% 时即触发压缩（因投影预测下一轮将超 90%）；Cline 在同一场景下不触发压缩（无提前投影机制）。

### 验证方法 4：无历史 tool_result 样本时的行为（Charles 独有，对应对比项 7.2.9）

构造场景：
- 全新会话，无任何 tool_result 消息
- `tools` 非空
- 当前消息 token 数接近 `_projection_trigger_tokens`

验证 `_project_future_usage` 返回的 `avg_tool_result = 0`，`projected = current + tools + 0`，不会因无样本而误触发提前压缩。

**预期**：Charles 在无历史样本时采取保守策略（avg=0），仅当 `current + tools >= projection_trigger` 时才触发；Cline 无此场景。

### 验证方法 5：nanobot 残留扫描

执行 `grep -r "nanobot" agent/budget_policy.py agent/context.py` 确认残留数量与类型。

**预期**：仅 `context.py` L275 一处废弃标注（与 Budget Projection 无关），Budget Projection 相关代码段无 nanobot 残留。
