# Phase 2.12 Budget Projection 预算投影对比报告

## 1. 执行摘要

Cline 与 Charles 在 Budget Projection（预算投影）机制上存在一个关键的"概念错位"：双方都实现了同名同结构的 `BudgetPolicyIntent` / `ProjectionPolicy` / `buildBudgetProjection` 内核，但**该内核在两侧承担的角色不同**。

- **Cline**：`budget-projection` 模块（`extensions/context/budget-projection/`）是**压缩执行阶段**的内部工具——当压缩已被触发后，由 `basic-compaction.ts` 和 `agentic-compaction.ts` 调用 `buildBudgetProjection` 决定"在 target_tokens 内保留哪些块、丢弃哪些块、截断哪些文本"。Cline 的压缩**触发**只用 `requestInputTokens >= maxInputTokens * 0.9` 阈值，无"提前压缩"机制。
- **Charles**：`budget_policy.py` 完整移植了 Cline 的 `buildBudgetProjection` 4 步流水线（drop_thinking → drop_unsafe → truncate_text → closure_removal），**同时**在 `context.py` 中新增了一个 Cline 不存在的 `_project_future_usage` 机制作为"提前压缩触发器"——通过 `enable_budget_projection=True` + `projection_ratio=0.8`，当 `projected_total >= trigger_tokens * 0.8` 时提前触发压缩，并用 `_last_compaction_reason` 字段区分 `budget_projection` 与 `threshold_exceeded` 两种触发来源。

此外，Cline 提供独立的 `compact-session` CLI 工具（`scripts/compact-session.ts`）用于离线压缩会话；Charles 未实现等价 CLI，压缩仅能在运行时通过 `before_model` 钩子触发。`FileContextTracker` 双方均有实现，但属于文件路径追踪的独立模块，与预算投影无直接耦合，仅在 Charles `compact()` 中作为文件列表来源被引用。

nanobot 残留检查结论：在 `agent/context.py` L275 发现 1 处 nanobot 残留，**为注释残留**（`extra_sections` 参数的废弃说明），**未发现实现逻辑残留**。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.12 章节定义的 14 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.12.1 | BudgetPolicyIntent 枚举 | `budget-projection/types.ts` L3-6 — `agentic_summary` / `basic_compaction_projection` / `normal_provider_request` 三值 | `budget_policy.py` L42-52 — `BudgetPolicyIntent(str, Enum)` 三值同名 | 枚举值与语义完全一致；Cline 用 TS 字面量联合类型，Charles 用 `str, Enum` | 强对齐 |
| 2.12.2 | ProjectionPolicy 字段 | `budget-projection/project.ts` L17-22 — `protectLatestTypedUser` / `protectLiveTailFromDrop` / `dropUnsafeOutsideLiveTail` / `dropThinkingBlocks` 四字段 | `budget_policy.py` L55-68 — `ProjectionPolicy` dataclass 同名四字段（snake_case） | 字段名命名风格不同（camelCase vs snake_case），语义完全一致 | 强对齐 |
| 2.12.3 | resolve_projection_policy 逻辑 | `project.ts` L24-42 — switch(intent)，agentic_summary/basic_compaction_projection 返回全 True，normal_provider_request 返回 drop_unsafe=False/drop_thinking=False | `budget_policy.py` L71-100 — if(intent in (AGENTIC_SUMMARY, BASIC_COMPACTION_PROJECTION)) 返回全 True，else 返回 drop_unsafe=False/drop_thinking=False | 策略矩阵完全一致；Cline 用 switch，Charles 用 if | 强对齐 |
| 2.12.4 | find_latest_typed_user_message_index | `project.ts` L81-91 — 从尾向前找 role=user 且非 isToolResultOnlyUserMessage | `budget_policy.py` L116-131 — 同逻辑，倒序遍历找 role=USER 且非 is_tool_result_only_user_message | 算法一致；Charles 额外导出 `find_first_typed_user_message_index`（L134-140）对齐 Cline `findFirstTypedUserMessageIndex`（L93-103，未导出） | 强对齐 |
| 2.12.5 | find_protected_tail_start_index | `project.ts` L141-168 — 收集所有 tool_result 的 tool_use_id，从尾向前找第一条含未配对 tool_use 的消息 | `budget_policy.py` L154-183 — 收集所有 ToolResultPart 的 tool_call_id，从尾向前找第一条含未配对 ToolCallPart 的消息 | 算法一致；字段名不同（tool_use_id/tool_call_id） | 强对齐 |
| 2.12.6 | drop_thinking_blocks | `project.ts` L301-327 — 移除 `block.type === "thinking"`，记录 dropped_block 动作 | `budget_policy.py` L186-247 — 移除 `ReasoningPart`，记录 dropped_block 动作（Stage 7.7 增强 actions/original_indexes 参数） | Cline 处理 `thinking` 块；Charles 处理 `ReasoningPart`（含 `text` + `redacted` 字段）；审计动作结构等价 | 强对齐 |
| 2.12.7 | apply_budget_policy | `project.ts` 内嵌于 `buildBudgetProjection` L483-672（无独立函数） | `budget_policy.py` L250-293 — 独立函数 `apply_budget_policy(messages, intent, actions, prune_empty)` | Charles 抽取为独立函数，支持 `prune_empty=False` 关闭空消息裁剪；Cline 无独立函数，逻辑内嵌于 buildBudgetProjection step 1 | 弱对齐（Charles 多了独立 API） |
| 2.12.8 | estimate_protected_token_budget | Cline 无此独立函数；protected token 估算分散在 `buildBudgetProjection` L520-525（latest_typed_user_index + protected_tail_start_index 计算）和 basic-compaction.ts L482-488（typed prompts + frozen + keptExtra 累加） | `budget_policy.py` L296-357 — 独立函数返回 dict 含 total_tokens/protected_tokens/available_for_truncation/latest_typed_user_index/protected_tail_start_index | Charles 提供独立 API 供 `get_stats()` 调用；Cline 无对外暴露的等价 API | 弱对齐（Charles 多了对外 API） |
| 2.12.9 | _project_future_usage 公式 | Cline **无此机制** — 压缩触发只用 `requestInputTokens >= requestTriggerTokens`（compaction.ts L312） | `context.py` L1369-1475 — `projected = current_tokens + tools_tokens + avg_tool_result`，avg_tool_result 取最近 N 个 tool_result 均值 | **Charles 独有**：基于未来一轮 tool_result 注入的提前压缩投影；Cline 无此概念 | 缺失（Charles 新增） |
| 2.12.10 | projection_ratio 默认值 | Cline 无此参数 | `context.py` L957 — `_DEFAULT_PROJECTION_RATIO = 0.8`，`_projection_trigger_tokens = trigger_tokens * 0.8` | **Charles 独有**：0.8 表示 trigger_tokens 的 80% 即触发提前压缩；Cline 无等价参数 | 缺失（Charles 新增） |
| 2.12.11 | tool_result_history_max | Cline 无此参数 | `context.py` L959 — `_DEFAULT_TOOL_RESULT_HISTORY_MAX = 10`，`_project_future_usage` 倒序取最近 10 个 tool_result 样本 | **Charles 独有**：限制历史样本数避免遍历全量消息；Cline 无等价参数 | 缺失（Charles 新增） |
| 2.12.12 | 提前压缩触发条件 | Cline 无此触发路径；仅有 `shouldCompact = requestInputTokens >= requestTriggerTokens`（compaction.ts L312） | `context.py` L1341-1365 — `enable_budget_projection and tools is not None` 且 `projected_total >= self._projection_trigger_tokens` 时触发，记 `_last_compaction_reason = "budget_projection"` | **Charles 独有**：双层触发——常规阈值 + 提前投影；Cline 单层阈值 | 缺失（Charles 新增） |
| 2.12.13 | compaction_reason 标记 | `compaction.ts` L385-386 — `statusReason = mode === "manual" ? "manual_compaction" : "auto_compaction"`；telemetry 通过 `captureCompactionExecuted` 上报 strategy/mode，**无 budget_projection 维度** | `context.py` L1272, L1337, L1364 — `_last_compaction_reason` 取值 `threshold_exceeded` / `budget_projection` / `unknown`；`get_stats()` 在 `budget_projection.last_compaction_reason` 字段返回 | **Charles 独有**：区分触发来源；Cline 只区分 manual/auto | 缺失（Charles 新增） |
| 2.12.14 | 无历史样本时行为 | Cline 无 `_project_future_usage`，无此场景 | `context.py` L1462-1466 — `if tool_result_samples: avg = sum // len; else: avg_tool_result = 0`（保守策略，避免误触发） | **Charles 独有**：无样本时 avg=0 不触发提前压缩；Cline 无等价场景 | 缺失（Charles 新增） |

## 3. 重点差距详细说明

### 差距 1：Budget Projection 在两侧承担的角色不同（对应对比项 2.12.9-2.12.14）

**Cline 设计**：`budget-projection` 模块是**压缩执行阶段**的内部工具。压缩触发链路为：

1. `compaction.ts::createContextCompactionPrepareTurn` 返回的 `prepareTurn` 回调在每次 LLM 请求前被调用
2. 计算 `requestInputTokens`（含 system_prompt + messages + tools）
3. `shouldCompact = requestInputTokens >= maxInputTokens * COMPACTION_TRIGGER_RATIO`（L312，单层阈值 0.9）
4. 触发后，根据 `strategy`（basic/agentic）调用 `runBasicCompaction` 或 `runAgenticCompaction`
5. 这两个 runner 内部调用 `buildBudgetProjection` 决定在 `targetTokens` 内保留什么、丢弃什么

Cline 的 `budget-projection` **不参与触发决策**，只参与"已决定压缩后"的内容选择。Cline 无 `_project_future_usage`、无 `projection_ratio`、无 `tool_result_history_max`、无 `_last_compaction_reason`。

**Charles 设计**：Charles 在 `context.py` 中新增了一个 Cline 不存在的"提前压缩"机制：

1. `should_compact()` 第一层：`request_tokens >= _trigger_tokens`（与 Cline 一致，记 `threshold_exceeded`）
2. `should_compact()` 第二层（L1341-1365）：`enable_budget_projection and tools is not None` 时调用 `_project_future_usage(messages, tools, total_tokens, intent)`：
   - 公式：`projected = current_tokens + tools_tokens + avg_tool_result`
   - `tools_tokens` = 每个 tool 的 name + description + input_schema JSON 估算
   - `avg_tool_result` = 最近 `tool_result_history_max`（默认 10）个 ToolResultPart 的 output token 均值
   - 无历史样本时 `avg_tool_result = 0`（保守策略）
3. 若 `projected_total >= _projection_trigger_tokens`（= `_trigger_tokens * projection_ratio`，默认 0.8），触发压缩并记 `_last_compaction_reason = "budget_projection"`

Charles 同时在 `budget_policy.py` 中完整移植了 Cline 的 `buildBudgetProjection` 4 步流水线（step 1: drop_thinking + prune_empty → step 2: drop_unsafe + prune_empty → step 3: truncate_text 从尾到头 → step 4: collect_closure + remove_messages_at 从头丢闭包），但该流水线**未被 Charles 的 compact() 实际调用**——Charles 的 `compact()` 仍走 Phase 16 重构后的 `_find_cut_index + _summarize_tool_activity + _simple_summary/LLM summary` 路径，与 Cline `runBasicCompaction` 的"typed prompts + frozen + keptExtra + buildBudgetProjection safety valve"路径不同。

**影响**：
- Charles 的提前压缩机制是**有意的增强**，避免"下一轮 tool_result 注入后立即超限"的尴尬场景。这是 Cline 未实现的设计。
- Charles 的 `build_budget_projection` 4 步流水线虽然忠实移植，但与 `compact()` 的实际压缩路径解耦，仅作为 `get_stats()` 的统计信息和 `apply_budget_policy` 的工具函数被引用。Cline 的 `buildBudgetProjection` 则是 `runBasicCompaction` 的核心安全阀（basic-compaction.ts L606-619）。

### 差距 2：compact-session CLI 工具缺失（不在对比表内，但属于任务要求）

**Cline 设计**：`sdk/packages/core/scripts/compact-session.ts` 是独立的 CLI 工具，用于离线压缩会话历史：

- 调用方式：`bun -F @cline/core test:compaction -- <session-directory> [options]`
- 支持 `--strategy basic/agentic/both` 选择压缩策略
- 支持 `--provider`/`--model`/`--api-key-env`/`--base-url`/`--max-input-tokens`/`--max-output-tokens`/`--preserve-recent-tokens`/`--output` 参数
- 读取目录下的 `messages.json` 或唯一 `*.messages.json` 文件
- 调用 `createContextCompactionPrepareTurn` 执行压缩，输出压缩后消息 JSON
- 由 `compact-session-script.test.ts` 提供冒烟测试（basic 不需要 API key，agentic 需要）

**Charles 设计**：未实现等价 CLI 工具。压缩仅能在运行时通过 `ContextCompactor.before_model` 钩子触发，或手动调用 `compactor.compact(messages)`。无离线压缩会话的能力。

**影响**：Charles 无法对持久化的会话历史进行离线压缩测试与调优，调试压缩策略时必须启动完整 runtime。

### 差距 3：FileContextTracker 与 Budget Projection 的耦合点不同（不在对比表内，但属于任务要求）

**Cline 设计**：`FileContextTracker` 位于 `apps/vscode/src/core/context/context-tracking/FileContextTracker.ts`（独立模块），追踪文件读写历史，与 budget-projection 模块无直接耦合。`basic-compaction.ts` 与 `agentic-compaction.ts` 通过 `extractFileOps(messages)` 从消息中扫描文件操作，不依赖 FileContextTracker。

**Charles 设计**：`file_context_tracker.py`（Phase 29.3 新增）对标 Cline FileContextTracker，但在 `compact()` 中作为**文件列表来源**被引用（context.py L1788-1790）：

```python
tool_activity = self._summarize_tool_activity_v2(old_messages, session_id)
```

`_summarize_tool_activity_v2` 优先从 `FileContextTracker` 获取文件列表（跨压缩周期保留），无数据时回退到从消息扫描。Charles 在 docstring 中明确说明"本实现与 Cline FileContextTracker 的设计目标不同"（L36）。

**影响**：Charles 的 FileContextTracker 与压缩路径有耦合，跨压缩周期保留文件状态；Cline 的 FileContextTracker 仅用于 UI 展示，压缩路径独立扫描消息。

### 差距 4：压缩策略选择（agentic vs basic）的回退路径不同（不在对比表内，但属于任务要求）

**Cline 设计**（compaction.ts L416-438）：
- `strategy = userCompaction?.strategy ?? "agentic"`（默认 agentic）
- agentic 失败时（非 abort 错误）自动 fallback 到 basic：`result = await BUILTIN_COMPACTION_STRATEGIES.basic(builtinOptions)`
- 日志记录 `executedStrategy = "basic"`（telemetry 上报实际执行策略）
- basic 与 agentic 都调用 `buildBudgetProjection` 作为安全阀

**Charles 设计**（context.py L1719-1813）：
- `compact()` 接受 `summarize_func` 参数，None 时用 `_simple_summary`（basic 路径）
- `summarize_func` 抛异常时（非 AbortedError）fallback 到 `_simple_summary`（L1805-1807）
- `before_model` 中传入 `self._summarize_with_llm` 作为 `summarize_func`，model 为 None 时不传（走 basic）
- Charles 的 basic 路径**不调用** `build_budget_projection`，而是走 `_find_cut_index + _simple_summary` 路径

**影响**：Charles 的 basic 压缩路径与 Cline 的 `runBasicCompaction` 实现差异较大——Cline basic 路径有完整的 typed prompts + frozen + keptExtra + older_final 选择逻辑 + buildBudgetProjection 安全阀；Charles basic 路径只有简单的 cut_index 切割 + 文本拼接摘要。

## 4. nanobot 残留检查

### 检查范围

在 `agent/context.py` 与 `agent/budget_policy.py` 中检查 nanobot 残留。`budget_policy.py` 无任何 nanobot 残留（纯 Cline 对标实现）。`context.py` 发现 1 处 nanobot 残留。

### 注释残留分类

#### 类型 A：废弃标注

形式：`[已废弃] nanobot 风格`

出现在：
- `agent/context.py` L275（`SystemPromptBuilder.__init__` 的 `extra_sections` 参数 docstring："extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。"）

**性质**：明确标注已废弃的参数说明，属于**有意的废弃保留**，与 Budget Projection 机制无关（属于 SystemPromptBuilder 的参数），不影响运行时行为。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。Budget Projection 相关的全部代码均基于 Cline 对标设计：

- `agent/budget_policy.py` 全文对标 Cline `budget-projection/types.ts` + `project.ts`，无 nanobot 代码
- `agent/context.py` 的 `_project_future_usage` / `should_compact` / `before_model` 中的 budget-projection 分支为 Charles 独有增强，无 nanobot 代码
- `agent/file_context_tracker.py` 对标 Cline `FileContextTracker.ts`，无 nanobot 代码

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

参考 Cline `basic-compaction.ts` L606-619，在 Charles `compact()` 的 `_find_cut_index + _simple_summary` 路径之后，调用 `build_budget_projection(messages, target_tokens, BASIC_COMPACTION_PROJECTION)` 作为安全阀，确保压缩后消息不超过 `trigger_tokens`。

**收益**：Charles 的 `build_budget_projection` 4 步流水线（已忠实移植）能真正生效，避免"压缩后仍超限"的边缘情况。

**改动范围**：`context.py::compact()` 末尾增加 `build_budget_projection` 调用，处理 `BudgetProjectionResult.status == "failed"` 时的日志告警。

**注意**：保留现有 `_simple_summary` 路径作为主压缩逻辑，`build_budget_projection` 仅作为安全阀（与 Cline basic-compaction.ts 用法一致）。

### P2（低优先级，改善可观测性）

**建议 2：在 `before_model` 中区分 `budget_projection` 触发的事件**

参考 Charles 已有的 `_last_compaction_reason` 字段，在 `make_compaction_started` 事件中传入 `reason="budget_projection"`（当 `_last_compaction_reason == "budget_projection"` 时），让前端能区分"阈值触发"与"提前投影触发"。

**收益**：前端 UI 能展示更精确的压缩原因，便于用户理解为什么在 token 用量未达 90% 时就触发了压缩。

**改动范围**：`context.py::before_model` L1565-1577 的 `make_compaction_started` 调用，`reason` 字段改为 `self._last_compaction_reason or "auto_compaction"`。

### P3（可选，工具补齐）

**建议 3：实现 compact-session CLI 工具**

参考 Cline `scripts/compact-session.ts`，新增 `scripts/compact_session.py`，支持：
- 读取会话 JSON 文件（messages + system_prompt）
- 选择 basic/agentic 策略
- 调用 `ContextCompactor.compact()` 执行压缩
- 输出压缩后消息 JSON

**收益**：支持离线压缩测试与调优，无需启动完整 runtime。

## 6. 验证方法建议

### 验证方法 1：BudgetPolicyIntent 策略矩阵对比

构造 3 种 intent 场景（agentic_summary / basic_compaction_projection / normal_provider_request），分别调用 Cline `resolveProjectionPolicy(intent)` 与 Charles `resolve_projection_policy(intent)`，对比返回的 4 个字段值。

**预期**：3 种 intent 返回的策略矩阵完全一致（agentic_summary 与 basic_compaction_projection 返回全 True，normal_provider_request 返回 drop_unsafe=False/drop_thinking=False）。

### 验证方法 2：buildBudgetProjection 4 步流水线对比

构造含以下元素的测试消息列表：
- 含 thinking/reasoning 块的 assistant 消息
- 含 image/redacted_thinking 块的消息
- 含 tool_use + tool_result 配对的消息
- 含未配对 tool_use 的尾部消息
- 含超长文本的消息

分别调用 Cline `buildBudgetProjection({messages, targetTokens, policyIntent, estimateMessageTokens})` 与 Charles `build_budget_projection(messages, target_tokens, intent, estimate_tokens_fn)`，对比：
- `status`（ok/failed）
- `actions` 列表（kind/path/reason）
- `live_tail_handling`
- `estimated_tokens`
- `warnings`

**预期**：4 步流水线（drop_thinking → drop_unsafe → truncate_text → closure_removal）的输出在两侧等价，仅字段命名风格不同（camelCase vs snake_case）。

### 验证方法 3：提前压缩触发验证（Charles 独有）

构造场景：
- `max_input_tokens=128000`, `trigger_ratio=0.9` → `_trigger_tokens=115200`
- `projection_ratio=0.8` → `_projection_trigger_tokens=92160`
- 当前消息 token 数 = 80000（< 115200，不触发常规阈值）
- tools 定义 token 数 = 5000
- 最近 10 个 tool_result 平均 token 数 = 8000
- `projected = 80000 + 5000 + 8000 = 93000 >= 92160` → 触发提前压缩

验证 `_last_compaction_reason == "budget_projection"`，且 `get_stats()["budget_projection"]["last_compaction_reason"]` 返回 `"budget_projection"`。

**预期**：Charles 在 token 用量 80% 时即触发压缩（因投影预测下一轮将超 90%）；Cline 在同一场景下不触发压缩（无提前投影机制）。

### 验证方法 4：无历史 tool_result 样本时的行为（Charles 独有）

构造场景：
- 全新会话，无任何 tool_result 消息
- `tools` 非空
- 当前消息 token 数接近 `_projection_trigger_tokens`

验证 `_project_future_usage` 返回的 `avg_tool_result = 0`，`projected = current + tools + 0`，不会因无样本而误触发提前压缩。

**预期**：Charles 在无历史样本时采取保守策略（avg=0），仅当 `current + tools >= projection_trigger` 时才触发；Cline 无此场景。

### 验证方法 5：nanobot 残留扫描

执行 `grep -r "nanobot" agent/context.py agent/budget_policy.py agent/file_context_tracker.py` 确认残留数量与类型。

**预期**：仅 `context.py` L275 一处废弃标注，无实现逻辑残留。
