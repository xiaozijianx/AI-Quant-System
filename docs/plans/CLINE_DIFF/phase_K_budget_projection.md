# Phase K: Budget Projection 对比报告

> 对标源码：
> - `sdk/packages/core/src/extensions/context/budget-projection/index.ts`
> - `sdk/packages/core/src/extensions/context/budget-projection/project.ts`
> - `sdk/packages/core/src/extensions/context/budget-projection/types.ts`
> - （关联）`sdk/packages/core/src/extensions/context/compaction.ts`、`basic-compaction.ts`、`agentic-compaction.ts`、`compaction-shared.ts`
>
> 当前实现：
> - `agent/budget_policy.py`
> - `agent/context.py::_project_future_usage` + `ContextCompactor.should_compact`
>
> 对比维度：K1-K14

---

## 0. 关键发现前置说明

在进入逐项对比前，需先澄清一个**重要的概念错位**，否则后续 K8-K14 的判定会失真：

- **Cline 的 `budget-projection/project.ts` 中并没有 `_project_future_usage`/`projection_ratio`/`tool_result_history_max`/`projection_trigger_tokens` 等概念**。Cline 的 `buildBudgetProjection` 是一个**预算裁剪（budget trimming）** 操作：给定 `targetTokens`，对消息序列做"丢 thinking → 丢不安全块 → 截断文本 → 丢整条消息"四级裁剪，输出一个能塞进预算的新消息列表。它**不估算未来 token 用量**，也**不基于投影触发提前压缩**。
- **Cline 的压缩触发是单级**：`shouldCompact = requestInputTokens >= maxInputTokens * COMPACTION_TRIGGER_RATIO (0.9)`（见 `compaction.ts:312`），不存在"投影后超限即提前压缩"的第二级触发。
- 我的实现中 `_project_future_usage` + `projection_ratio` + `tool_result_history_max` + `_projection_trigger_tokens` + `compaction_reason` 是**在 Cline 设计之外自建的一套"未来用量投影 + 提前压缩"机制**。

因此：
- K1-K7 可与 Cline `project.ts`/`types.ts` 直接对比（这些是 Cline 真正存在的能力）；
- K8-K14 在 Cline 中**没有对应实现**，应判定为"额外增强"，而非"对齐差距"。AGENT_CLINE_COMPARISON_PLAN.md 第 500-505 行将这些项的 Cline 位置标注为 `project.ts`/`index.ts`，经源码核对并不存在对应函数，本报告据实修正。

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 5 项 |
| 弱对齐 | 2 项 |
| 缺失 | 0 项 |
| 额外增强 | 7 项 |
| **对齐度** | **约 71%（按 K1-K7 有 Cline 对应的 7 项计：5 完全一致 + 2 弱对齐）** |

> 说明：K8-K14 为本系统在 Cline 设计之外新增的"未来用量投影 + 提前压缩"机制，Cline 无对应实现，统一计为"额外增强"，不计入对齐度分母。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| K1 | `BudgetPolicyIntent` 枚举 | types.ts:3-6 | budget_policy.py:41-51 | 完全一致 |
| K2 | `ProjectionPolicy` 字段 | project.ts:17-22 | budget_policy.py:54-67 | 完全一致 |
| K3 | `resolve_projection_policy` 逻辑 | project.ts:24-42 | budget_policy.py:70-99 | 完全一致 |
| K4 | `find_latest_typed_user_message_index` | project.ts:81-91 | budget_policy.py:115-130 | 完全一致 |
| K5 | `find_protected_tail_start_index`（live tail 起始，含未配对 tool_use） | project.ts:141-168 | budget_policy.py:153-182 | 完全一致 |
| K6 | `drop_thinking_blocks`（移除 ReasoningPart） | project.ts:301-327 + pruneEmptyMessages L217-241 | budget_policy.py:185-211 | 弱对齐（无 action 跟踪、无空消息裁剪） |
| K7 | `apply_budget_policy`（块级策略应用） | project.ts:483-672 `buildBudgetProjection`（4 步流水线） | budget_policy.py:214-240（仅 1 步） | 弱对齐（仅实现 4 步中的第 1 步） |
| K8 | `estimate_protected_token_budget`（受保护内容 token 估算） | Cline 无对应独立函数 | budget_policy.py:243-304 | 额外增强 |
| K9 | `_project_future_usage` 公式（current + tools_tokens + avg_tool_result_tokens） | Cline 无对应概念 | context.py:785-891 | 额外增强 |
| K10 | `projection_ratio` 默认值（0.8 是否一致） | Cline 无对应概念 | context.py:545 `_DEFAULT_PROJECTION_RATIO = 0.8` | 额外增强（自定值，非 Cline 标准） |
| K11 | `tool_result_history_max`（历史样本数） | Cline 无对应概念 | context.py:547 `_DEFAULT_TOOL_RESULT_HISTORY_MAX = 10` | 额外增强（自定值，非 Cline 标准） |
| K12 | 提前压缩触发条件（projected >= projection_trigger_tokens） | Cline 无对应概念（仅单级触发） | context.py:759-781（两级触发） | 额外增强 |
| K13 | `compaction_reason` 标记（budget_projection vs threshold_exceeded） | Cline 用 `policyIntent`（telemetry），无 compaction_reason 字段 | context.py:755, 780 `_last_compaction_reason` | 额外增强（语义不等价于 Cline policyIntent） |
| K14 | 无历史样本时行为（avg=0 保守策略） | Cline 无对应概念 | context.py:878-882 | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #K6：drop_thinking_blocks 行为差异（无 action 跟踪 + 无空消息裁剪）

**严重度**：P2（功能等价但缺少审计与边界处理）

**Cline 实现**（project.ts:301-327 + 217-241）：
```typescript
function dropThinkingBlocks(messages, originalIndexes, actions) {
  return messages.map((message, messageIndex) => {
    const content = message.content.filter((block, blockIndex) => {
      if (block.type !== "thinking") return true;
      changed = true;
      actions.push({
        kind: "dropped_block",
        path: { messageIndex: originalIndexes[messageIndex], blockIndex },
        reason: "unsafe_to_truncate",
        originalSize: safeJsonSize(block),
        finalSize: 0,
      });
      return false;
    });
    return changed ? { ...message, content } : message;
  });
}
// 调用后紧跟 pruneEmptyMessages(...) 移除 content.length === 0 的消息
```
- 过滤 `block.type === "thinking"` 的块；
- 每删一块都向 `actions` 数组 push 一条 `dropped_block` 审计记录（含 originalSize/finalSize）；
- 调用方在 `buildBudgetProjection` 内紧接着 `pruneEmptyMessages`，移除因 thinking 全删而变成空 content 的消息。

**我的实现**（budget_policy.py:185-211）：
```python
def drop_thinking_blocks(messages):
    result = []
    for message in messages:
        new_content = [p for p in message.content if not isinstance(p, ReasoningPart)]
        new_message = AgentMessage(role=message.role, content=new_content, ...)
        result.append(new_message)
    return result
```
- 过滤 `isinstance(part, ReasoningPart)` 的块（语义等价于 Cline 的 `thinking`）；
- **不记录 action**，无审计轨迹；
- **不裁剪空消息**：若一条 assistant 消息只有 ReasoningPart，过滤后 content 为空但消息仍保留在列表中（保留索引对齐，注释中说明"保留空内容消息以维持索引对齐"）。

**影响**：
1. **审计缺失**：无法回放"哪些块被丢弃、节省了多少 token"，调试与遥测能力弱于 Cline；
2. **空消息残留**：可能导致后续 token 估算仍计入空消息的固定开销（role/metadata 部分），轻微高估；
3. **索引对齐策略差异**：Cline 通过 `originalIndexes` 映射维持审计索引，并主动 `pruneEmptyMessages`；我通过保留空消息维持索引，下游消费者需容忍空 content。

**修复建议**：
- 短期：为 `drop_thinking_blocks` 增加可选 `actions: list[dict]` 参数，记录丢弃块的原大小/最终大小，与 Cline `BudgetAction` 对齐；
- 中期：补一个 `prune_empty_messages` 辅助函数，在 `apply_budget_policy` 末尾按需调用，与 Cline `pruneEmptyMessages` 对齐。

**优先级**：P2

---

### 差距 #K7：apply_budget_policy 仅实现 Cline buildBudgetProjection 4 步流水线的第 1 步

**严重度**：P1（块级策略不完整，与 Cline 行为不等价）

**Cline 实现**（project.ts:483-672 `buildBudgetProjection`）：
```
1. dropThinkingBlocks          → 丢弃 thinking 块（若 policy.dropThinkingBlocks）
2. dropUnsafeBlocks            → 丢弃 image/redacted_thinking 块（若 policy.dropUnsafeOutsideLiveTail 且非受保护）
3. truncateMessageText         → 逐条截断文本到 targetChars（从尾到头，跳过受保护消息）
4. collectMessageClosure + removeMessagesAt → 丢整条消息闭包（tool_use/tool_result 配对，从头开始丢）
```
- 4 步流水线协同，最终输出一个能塞进 `targetTokens` 的消息列表；
- 每步都向 `actions` 数组写审计记录；
- 返回 `BudgetProjectionResult`（含 `status`/`messages`/`actions`/`liveTailHandling`/`estimatedTokens`/`warnings`）。

**我的实现**（budget_policy.py:214-240）：
```python
def apply_budget_policy(messages, intent):
    policy = resolve_projection_policy(intent)
    result = list(messages)
    if policy.drop_thinking_blocks:
        result = drop_thinking_blocks(result)
    return result
```
- **仅执行第 1 步**（drop_thinking_blocks）；
- **未实现第 2 步**（drop_unsafe_outside_live_tail：丢弃 image/redacted_thinking）；
- **未实现第 3 步**（truncateMessageText：按 targetTokens 逐条截断文本）；
- **未实现第 4 步**（collectMessageClosure + removeMessagesAt：丢整条消息闭包）；
- 返回纯 `list[AgentMessage]`，无 `actions`/`warnings`/`liveTailHandling` 等元信息。

**影响**：
1. **裁剪能力缺口**：当真实超预算时，我的 `apply_budget_policy` 无法把消息裁剪到 target 内，只能依赖 `context.py::ContextCompactor` 的 `_simple_summary`/agentic 摘要路径兜底；
2. **不安全块未处理**：`image`/`redacted_thinking` 块（对应我的 `ReasoningPart(redacted=True)` 等）不会被主动丢弃，可能在压缩后被原样传给 LLM；
3. **无 tool_use/tool_result 闭包丢弃**：无法安全移除成对的工具调用消息，工具密集型对话压缩比不上 Cline；
4. **接口形态不等价**：Cline 是 `buildBudgetProjection(options) → BudgetProjectionResult`，我是 `apply_budget_policy(messages, intent) → list[AgentMessage]`，调用方无法拿到审计信息。

**注意**：本差距在 Phase J（context compaction）已部分覆盖——我的截断/丢弃逻辑分散在 `ContextCompactor._truncate_tool_results`、`_find_cut_index`、`_simple_summary` 等方法中，但**没有按 Cline 的 4 步流水线集中实现**，且未对接 `budget-projection` 的策略矩阵。

**修复建议**：
- 中期：在 `budget_policy.py` 中新增 `build_budget_projection(messages, target_tokens, intent, estimate_tokens_fn) → BudgetProjectionResult`，按 Cline 4 步流水线实现，并补 `drop_unsafe_blocks`/`truncate_message_text`/`collect_message_closure`/`remove_messages_at` 辅助函数；
- 中期：让 `ContextCompactor` 在 basic 摘要路径中调用 `build_budget_projection`，替换分散的截断逻辑；
- 长期：补 `BudgetAction`/`BudgetProjectionWarning` 数据类，输出审计轨迹。

**优先级**：P1

---

### 差距 #K13：compaction_reason 字段与 Cline policyIntent 语义不等价（同名异义）

**严重度**：P3（仅影响遥测/日志语义，不影响压缩行为）

**Cline 实现**：
- 通过 `policyIntent: "agentic_summary" | "basic_compaction_projection"` 字段标记**压缩策略类型**（在 `agentic-compaction.ts:56,275`、`basic-compaction.ts:609,689` 传入 `buildBudgetProjection`）；
- 通过 `CoreCompactionBudgetPolicyIntent` 类型参与 telemetry（`core-events.ts:808`）；
- **无 `compaction_reason` 字段**区分"阈值触发"还是"投影触发"——因为 Cline 根本没有"投影触发"这一级。

**我的实现**（context.py:755, 780）：
```python
if total_tokens >= self._trigger_tokens:
    self._last_compaction_reason = "threshold_exceeded"
    return True
...
if projected_total >= self._projection_trigger_tokens:
    self._last_compaction_reason = "budget_projection"
    return True
```
- `_last_compaction_reason` 取值 `"threshold_exceeded"` / `"budget_projection"`，标记**触发来源**；
- 在 `get_stats` 中作为 `last_compaction_reason` 暴露（context.py:1718）。

**影响**：
- 字段语义与 Cline `policyIntent` 不同维度（Cline 标"用什么策略压缩"，我标"为什么触发压缩"），不应混淆；
- 若后续要对接 Cline 风格 telemetry，需额外引入 `policyIntent` 字段。

**修复建议**：保留 `_last_compaction_reason`（自研增强），但**不要将其视为 Cline `policyIntent` 的等价物**；若做 telemetry 对齐，应单独补 `policyIntent` 字段。

**优先级**：P3

---

### 备注：K8-K12、K14 均为"额外增强"，无差距需修复

以下 7 项是本系统在 Cline 设计之外自建的能力，Cline 无对应实现，因此**不存在"对齐差距"，仅有"自洽性"考量**：

- **K8 `estimate_protected_token_budget`**（budget_policy.py:243-304）：返回 `total_tokens/protected_tokens/available_for_truncation/latest_typed_user_index/protected_tail_start_index` 五元组，供调用方决策可截断预算。设计合理，复用了 K4/K5 的索引查找。
- **K9 `_project_future_usage` 公式**（context.py:785-891）：`projected = current_tokens + tools_tokens + avg_tool_result`。公式自洽，但 `tools_tokens` 估算偏粗（仅 name+description+input_schema JSON 字符数，未对齐 Cline `estimateRequestInputTokens` 的 system+tools 完整估算）。
- **K10 `projection_ratio = 0.8`**（context.py:545）：自定值，使 `_projection_trigger_tokens = max_input_tokens * 0.9 * 0.8 = 0.72 * max_input_tokens`。无 Cline 对照，但 0.72 留有 28% 余量给下一轮 tool_result，合理。
- **K11 `tool_result_history_max = 10`**（context.py:547）：自定值，最近 10 条 tool_result 采样均值。无 Cline 对照，10 条样本足够平滑偶发尖峰。
- **K12 提前压缩触发**（context.py:759-781）：`projected_total >= _projection_trigger_tokens` 时触发。这是本系统独有的"二级触发"，Cline 无对应概念。
- **K14 无历史样本时 avg=0**（context.py:878-882）：保守策略，避免首轮无样本时误触发提前压缩。设计合理。

**潜在风险（非差距，仅提示）**：
- K9 `tools_tokens` 估算与 Cline `estimateRequestInputTokens`（含 system prompt + 完整 tools JSON 序列化）口径不一致，可能导致投影值偏低；若后续要对齐 Cline 的 `requestInputTokens` 概念，需统一估算口径。
- K10 `projection_ratio` 与 K2 `trigger_ratio`（0.9）相乘的语义需在文档中明确：`0.9 * 0.8 = 0.72` 是相对 `max_input_tokens` 的提前触发点，而非相对 `trigger_tokens` 的额外折扣。

---

## 4. 一致性统计

### 4.1 按"是否与 Cline 对应"分组

| 分组 | 项数 | 子项 |
|------|------|------|
| 有 Cline 对应（K1-K7） | 7 | K1, K2, K3, K4, K5, K6, K7 |
| 无 Cline 对应（额外增强） | 7 | K8, K9, K10, K11, K12, K13, K14 |

### 4.2 按"一致性等级"分组

| 一致性 | 项数 | 子项 |
|--------|------|------|
| 完全一致 | 5 | K1, K2, K3, K4, K5 |
| 弱对齐 | 2 | K6, K7 |
| 缺失 | 0 | — |
| 额外增强 | 7 | K8, K9, K10, K11, K12, K13, K14 |

### 4.3 对齐度计算

- **分子**：完全一致 5 项
- **分母**：有 Cline 对应的 7 项（K1-K7）
- **对齐度**：5/7 ≈ **71%**

若把 7 项额外增强也视作"广义对齐"（即不与 Cline 冲突即算），则 14 项中 12 项可接受（5 完全一致 + 7 额外增强），广义对齐度 ≈ 86%。

---

## 5. 修复建议

### 5.1 短期（P2，可在一两次提交内完成）

1. **为 `drop_thinking_blocks` 增加 action 跟踪**（差距 #K6）
   - 新增可选参数 `actions: list[dict] | None = None`；
   - 每删一块 push `{kind: "dropped_block", path: {message_index, block_index}, reason: "unsafe_to_truncate", original_size, final_size: 0}`；
   - 与 Cline `BudgetAction` 字段对齐，便于后续接 telemetry。

2. **修正 context.py:28 docstring 笔误**
   - 当前注释写 `COMPACTION_TRIGGER_RATIO (0.8)`，实际值为 `0.9`（context.py:529）；
   - 改为 `COMPACTION_TRIGGER_RATIO (0.9)`，避免误导。

3. **在 `apply_budget_policy` 文档中明确"仅 step 1"**
   - 当前 docstring 说"不截断文本（那是 build_budget_projection 的职责）"，但 `build_budget_projection` 并不存在；
   - 改为"本函数仅执行块级丢弃（step 1: drop_thinking），截断/丢消息由 ContextCompactor 承担"，避免后续维护者误解。

### 5.2 中期（P1，需 1-2 个 phase）

1. **实现完整的 `build_budget_projection`**（差距 #K7）
   - 在 `budget_policy.py` 新增 `build_budget_projection(messages, target_tokens, intent, estimate_tokens_fn) -> BudgetProjectionResult`；
   - 按 Cline 4 步流水线实现：dropThinking → dropUnsafe → truncateText → dropMessageClosure；
   - 补 `drop_unsafe_blocks`（处理 image/redacted_thinking 等价物）、`truncate_message_text`、`collect_message_closure`、`remove_messages_at`、`prune_empty_messages` 辅助函数；
   - 补 `BudgetAction`/`BudgetProjectionWarning`/`BudgetProjectionResult` 数据类。

2. **让 `ContextCompactor` basic 路径调用 `build_budget_projection`**
   - 替换 `_simple_summary` 中分散的截断逻辑；
   - 通过 `policyIntent="basic_compaction_projection"` 接入；
   - agentic 路径用 `policyIntent="agentic_summary"` 接入 `buildAgenticSummaryInputBudget` 等价物。

3. **统一 `tools_tokens` 估算口径**（K9 风险点）
   - 当前 `_project_future_usage` 仅估算 `name + description + input_schema`；
   - 若要对齐 Cline `estimateRequestInputTokens`，需补 system prompt token 与 tools 完整 JSON 序列化 token。

### 5.3 长期（P3，对齐 telemetry）

1. **补 `policyIntent` 字段**
   - 在 `ContextCompactor` 中记录最近一次压缩的 `policyIntent`（`agentic_summary`/`basic_compaction_projection`），与 `_last_compaction_reason` 并存；
   - 为后续对接 Cline 风格 telemetry 事件做准备。

2. **补 `LiveTailHandling` 等价枚举**
   - Cline 用 `included_verbatim`/`included_degraded`/`summarized_as_context`/`omitted_with_warning`/`preserved_out_of_band` 标记 live tail 处理结果；
   - 我的实现无此字段，可在 `build_budget_projection` 完成后补上，便于上层判断压缩质量。

3. **补 `BudgetProjectionWarning` 输出**
   - Cline 在 `targetTokens <= 0` 时输出 `budget_impossible`，在保护内容无法裁剪到目标时输出 `budget_unachievable_with_protections`；
   - 我的实现无此类警告，可在 `build_budget_projection` 中补齐。

---

## 6. 验证记录

### 6.1 已核对文件

| 文件 | 路径 | 用途 |
|------|------|------|
| Cline types.ts | `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/types.ts` | K1/K2 枚举与接口定义 |
| Cline project.ts | `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/project.ts` | K3-K7 核心逻辑 |
| Cline index.ts | `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/index.ts` | 导出清单 |
| Cline project.test.ts | 同目录 `project.test.ts` | 验证 Cline 行为预期（image/redacted 丢弃、live tail 保护） |
| Cline compaction.ts | `third_party/cline/sdk/packages/core/src/extensions/context/compaction.ts` | 确认 Cline 单级触发（L307/L312） |
| Cline compaction-shared.ts | 同目录 `compaction-shared.ts` | 确认 `COMPACTION_TRIGGER_RATIO = 0.9`（L17） |
| Cline agentic-compaction.ts | 同目录 `agentic-compaction.ts` | 确认 `policyIntent: "agentic_summary"`（L56） |
| Cline basic-compaction.ts | 同目录 `basic-compaction.ts` | 确认 `policyIntent: "basic_compaction_projection"`（L609） |
| 我的 budget_policy.py | `agent/budget_policy.py` | K1-K8 实现 |
| 我的 context.py | `agent/context.py` | K9-K14 实现（L485-547, 672-783, 785-891） |

### 6.2 关键源码定位（行号核对）

- Cline `BudgetPolicyIntent` 枚举：types.ts:3-6
- Cline `ProjectionPolicy` 接口：project.ts:17-22
- Cline `resolveProjectionPolicy`：project.ts:24-42
- Cline `findLatestTypedUserMessageIndex`：project.ts:81-91
- Cline `findProtectedTailStartIndex`：project.ts:141-168
- Cline `dropThinkingBlocks`：project.ts:301-327
- Cline `buildBudgetProjection`（4 步流水线）：project.ts:483-672
- Cline 单级触发 `shouldCompact = requestInputTokens >= requestTriggerTokens`：compaction.ts:312
- Cline `COMPACTION_TRIGGER_RATIO = 0.9`：compaction-shared.ts:17
- 我的 `BudgetPolicyIntent`：budget_policy.py:41-51
- 我的 `ProjectionPolicy`：budget_policy.py:54-67
- 我的 `resolve_projection_policy`：budget_policy.py:70-99
- 我的 `find_latest_typed_user_message_index`：budget_policy.py:115-130
- 我的 `find_protected_tail_start_index`：budget_policy.py:153-182
- 我的 `drop_thinking_blocks`：budget_policy.py:185-211
- 我的 `apply_budget_policy`：budget_policy.py:214-240
- 我的 `estimate_protected_token_budget`：budget_policy.py:243-304
- 我的 `_project_future_usage`：context.py:785-891
- 我的 `should_compact` 两级触发：context.py:716-783
- 我的 `_DEFAULT_PROJECTION_RATIO = 0.8`：context.py:545
- 我的 `_DEFAULT_TOOL_RESULT_HISTORY_MAX = 10`：context.py:547
- 我的 `_last_compaction_reason`：context.py:755, 780

### 6.3 验证方法

- **K1-K5 完全一致判定依据**：逐行对比 Cline project.ts 与 budget_policy.py，逻辑分支与返回值语义一致（snake_case ↔ camelCase 仅命名差异）；
- **K6 弱对齐判定依据**：核心过滤逻辑等价，但 Cline 有 `actions.push(...)` + `pruneEmptyMessages`，我无；
- **K7 弱对齐判定依据**：Cline `buildBudgetProjection` 含 4 步（dropThinking/dropUnsafe/truncateText/dropClosure），我 `apply_budget_policy` 仅 1 步（dropThinking）；
- **K8-K14 额外增强判定依据**：在 Cline `budget-projection/` 三份源码与 `compaction.ts`/`compaction-shared.ts` 中均未检索到 `project_future_usage`/`projection_ratio`/`tool_result_history_max`/`projection_trigger_tokens`/`compaction_reason` 等关键字（见 Grep 结果：No matches found）；
- **Cline `projectSessionCompactionState`（session-compaction.ts:152）** 经核对是"将已保存的压缩状态投影到当前消息序列"，与"未来 token 用量投影"无关，不构成 K9 的 Cline 对应物。

### 6.4 待办追踪

| 差距 | 优先级 | 建议归属 phase |
|------|--------|----------------|
| #K6 action 跟踪 + 空消息裁剪 | P2 | 短期（随下次 budget_policy 修改） |
| #K7 完整 build_budget_projection 流水线 | P1 | 中期专项 phase |
| #K13 policyIntent 字段补齐 | P3 | 长期 telemetry 对齐 phase |
| context.py:28 docstring 笔误（0.8 → 0.9） | P2 | 短期随手修 |
