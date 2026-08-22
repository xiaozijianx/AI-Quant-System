# Phase 6.6 AGENTS.md 条件注入对比

> 对比范围：Cline `rule-conditionals.ts` 的条件评估器注册表（`conditionalEvaluators`）+ `rule-helpers.ts` 的 `getRuleFilesTotalContentWithMetadata` 注入流程 + `external-rules.ts` 的 AGENTS.md 加载入口 + `frontmatter.ts` 解析器，与 Charles `rules_loader.py` 的 `evaluate_rule_conditionals` 四字段评估器 + `load_rules_directory` 注入流程 + `context.py::_build_rules` 编排器的 AGENTS.md 条件注入逻辑逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段与 P5.8（Cline Rules 段对比）+ P6.1（AGENTS.md frontmatter 对比）形成关联：P5.8 已确认 Cline `conditionalEvaluators` 仅注册 `paths` 一个评估器；P6.1 已确认 Cline AGENTS.md 示例 frontmatter 不含 `applyTo` 字段且 `globs`/`alwaysApply` 均为未评估的死字段。本阶段聚焦于"条件注入流程"层面（applyTo / mode / enabled / paths 在 AGENTS.md 加载时是否真正参与过滤决策）。
>
> Cline 源码：
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts` L1-153（`evaluateRuleConditionals` + `conditionalEvaluators` 注册表，**仅注册 `paths`**，`RuleEvaluationContext` 仅含 `paths` 字段）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L206-259（`getRuleFilesTotalContentWithMetadata`：toggle 控制激活 + `evaluateRuleConditionals` 过滤 + fail-open 解析失败保留原文）
> - `apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts` L38-42（AGENTS.md 作为 `agentsRulesFile` 走 `synchronizeRuleToggles` + 同一 `getRuleFilesTotalContentWithMetadata` 流程）
> - `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts` L1-59（`parseYamlFrontmatter`：解析层不区分字段，全部进入 `data` dict）
> - `sdk/AGENTS.md` L1-5（frontmatter：`description` / `globs` / `alwaysApply`，无 `paths` 无 `applyTo`）
> - `sdk/packages/llms/AGENTS.md` L1-5（同上）
>
> Charles 源码：
> - `agent/rules_loader.py` L433-481（`evaluate_rule_conditionals`：评估 `enabled`/`applyTo`/`mode`/`paths` 四字段，其他字段忽略）
> - `agent/rules_loader.py` L369-400（`_evaluate_apply_to_conditional`：agent 模式过滤）
> - `agent/rules_loader.py` L403-430（`_evaluate_business_mode_conditional`：业务模式过滤）
> - `agent/rules_loader.py` L336-366（`_evaluate_paths_conditional`：路径 glob 匹配）
> - `agent/rules_loader.py` L568-683（`load_rules_directory`：toggle 控制 + frontmatter 解析 + `evaluate_rule_conditionals` 过滤 + fail-open）
> - `agent/context.py` L471-497（`_build_rules`：全局 `~/.agent/AGENTS.md` + workspace `agents_path` 走 `_strip_frontmatter` **无条件加载**，不走 `evaluate_rule_conditionals`）
> - `agent/context.py` L541-609（`_load_rules_directory`：rules_dir 下文件（含 `rules/AGENTS.md`）走 `load_rules_directory` **条件评估**）
> - `agent_config/rules/AGENTS.md` L1-5（frontmatter：`description` / `applyTo: [act, plan]` / `alwaysApply: true`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 条件注入逻辑（frontmatter 字段是否真正参与"是否激活"的过滤决策）。**核心结论：Cline `rule-conditionals.ts` 仅评估 `paths` 一个字段，`alwaysApply`/`applyTo`/`globs`/`mode`/`enabled` 均作为 unknown key 被忽略；Charles `evaluate_rule_conditionals` 评估 `enabled`/`applyTo`/`mode`/`paths` 四个字段，是 Cline 的严格超集。AGENTS.md 在双方均无"按 mode 注入"或"按 alwaysApply 注入"的实际条件过滤——Cline 因评估器不识别这些字段而不过滤，Charles 的 AGENTS.md 因 `applyTo: [act, plan]` 覆盖所有 agent 模式而等效"常驻"。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.6（L2362-2379）的对比表存在 **3 处事实错误 + 1 处误导性描述**，与 P5.8 / P6.1 的修正同源（因 P6.6 直接复用了 P5.8/P6.1 的错误前提）：

1. **6.6.1 标注"alwaysApply 注入 always | always | 已对齐"** — **误导性描述**：双方确实"已对齐"，但**对齐方式是"都不评估 alwaysApply"**而非"都评估 alwaysApply 实现 always 注入"。Cline `evaluateRuleConditionals` 不识别 `alwaysApply`（unknown key 忽略，rule-conditionals.ts L89-90）；Charles `evaluate_rule_conditionals` 也不识别 `alwaysApply`（仅处理 `enabled`/`applyTo`/`mode`/`paths`，rules_loader.py L452-481）。AGENTS.md 的"常驻"语义在 Cline 中由"无 paths 字段 → paths 评估器永不触发 → 默认通过"实现，在 Charles 中由"`applyTo: [act, plan]` 覆盖所有 agent 模式"实现。`alwaysApply: true` 在双方均为**死字段**。

2. **6.6.2 标注"applyTo 字段 是 | 是 | 已对齐（Stage P3）"** — **严重事实错误**：Cline **未实现** `applyTo` 评估。Cline `conditionalEvaluators` 注册表（rule-conditionals.ts L74-76）仅注册 `paths`，`applyTo` 作为 unknown key 被 `continue` 忽略（L89-90）。Charles 才真正实现了 `applyTo` 评估（`_evaluate_apply_to_conditional`，rules_loader.py L369-400）。Charles 不是"已对齐"而是"独有增强"。Stage P3 的对齐工作实际是 Charles 单方面扩展，Cline 侧无对应实现。

3. **6.6.3 标注"按 mode 注入 是 | 是 | 已对齐"** — **严重事实错误**：Cline **未实现** mode 注入。Cline `RuleEvaluationContext`（rule-conditionals.ts L14-20）仅含 `paths` 字段，无 `agent_mode`/`business_modes` 概念。Charles 实现 `applyTo`（agent 模式过滤）+ `mode`（业务模式过滤）双层 mode 评估。Charles 不是"已对齐"而是"独有增强"。

4. **6.6.4 标注"globs 匹配 是 | 无 | Charles 缺失"** — **事实错误**：Cline 也**未实现 `globs` 字段评估**。Cline `conditionalEvaluators` 对象（rule-conditionals.ts L74-76）仅注册 `paths`，`globs` 作为 unknown key 被忽略（L89-90）。`globs` 是 Cursor Rules 字段，Cline 解析但**不评估**。Charles 同样不评估 `globs`。两者行为一致，非"Charles 缺失"。Cline 真正用于路径过滤的字段名是 `paths`（与 Charles 评估器字段名对齐）。

### 核心结论

1. **Cline 条件注入仅 `paths` 一个评估器**：`conditionalEvaluators = { paths: evaluatePathsConditional }`（rule-conditionals.ts L74-76）。`alwaysApply`/`applyTo`/`globs`/`mode`/`enabled` 均作为 unknown key 被 `continue` 忽略（L89-90 注释明确"unknown conditional: ignore"）。
2. **Charles 条件注入是 Cline 严格超集**：Charles `evaluate_rule_conditionals`（rules_loader.py L433-481）评估 4 个字段：`enabled`（L452-455）+ `applyTo`（L457-463）+ `mode`（L465-471）+ `paths`（L473-479）。`paths` 与 Cline 对齐，`applyTo`/`mode`/`enabled` 是 Charles 自定义扩展。
3. **AGENTS.md 加载路径双方均有"无条件 + 条件"两条路径**：
   - Cline：AGENTS.md 作为 `agentsRulesFile` 走 `external-rules.ts` → `synchronizeRuleToggles` + `getRuleFilesTotalContentWithMetadata`（toggle 控制 + paths 评估）。AGENTS.md frontmatter 无 `paths` 字段 → paths 评估器永不触发 → 默认通过 → 等效"常驻"。
   - Charles：**双路径**。全局 `~/.agent/AGENTS.md` + workspace `agents_path` 走 `_strip_frontmatter` **无条件加载**（context.py L471-497，`activated=True` 硬编码）；rules_dir 下 `agent_config/rules/AGENTS.md` 走 `load_rules_directory` **条件评估**（applyTo/mode/paths/enabled 过滤）。
4. **`alwaysApply` 在双方均为死字段**：Cline 和 Charles 的 AGENTS.md 都写了 `alwaysApply: true`，但双方的评估器都不识别此字段——它是**纯文档元数据**，对"是否激活"无实际影响。Charles AGENTS.md 的"常驻"语义实际由 `applyTo: [act, plan]`（覆盖所有 agent 模式）实现。
5. **`globs` 在双方均为死字段**：Cline AGENTS.md 示例用 `globs` 但评估器不识别；Charles AGENTS.md 未使用 `globs`，评估器也不识别。Cline 真正用于路径过滤的字段名是 `paths`，Charles 同样用 `paths`，两者在路径过滤字段名上已对齐。
6. **`applyTo` 是 Charles 独有增强**：Charles `_evaluate_apply_to_conditional`（rules_loader.py L369-400）基于 `context.agent_mode` 评估，省略=无条件通过，空数组=fail-closed，命中即激活。Cline 无 agent 模式过滤概念。
7. **`mode` 是 Charles 独有增强**：Charles `_evaluate_business_mode_conditional`（rules_loader.py L403-430）基于 `context.business_modes` 评估业务模式（如 research/trade）。Cline 无业务模式概念。
8. **`enabled` 是 Charles 独有增强**：Charles `evaluate_rule_conditionals` L452-455 检查 `enabled` 字段，`enabled: false` 时直接 fail-closed。Cline 无 frontmatter 内嵌开关。
9. **`paths` 评估已对齐**：双方均实现 glob 匹配（Cline 用 `picomatch(pattern, { dot: true })`；Charles 优先用 `wcmatch.glob.globmatch`，回退到内置正则）、空数组 fail-closed、无候选路径 fail-closed。AGENTS.md frontmatter 无 `paths` 字段，故 AGENTS.md 在双方均不受 paths 过滤。
10. **nanobot 残留**：rules_loader.py **0 处残留**；context.py AGENTS.md 条件注入相关代码 **1 处注释残留 + 0 处实现逻辑残留**（L275 `extra_sections` docstring，与 P5.8 / P6.1 同一处）。

### 一致性总体评估

- **paths 条件评估**：**高**。glob 语义对齐（picomatch vs wcmatch），fail-closed 策略一致。AGENTS.md 在双方均无 paths 字段，不受 paths 过滤。
- **alwaysApply 注入**：**高（都不评估）**。双方 AGENTS.md 的 `alwaysApply: true` 均为死字段，"常驻"由其他机制实现。
- **globs 匹配**：**高（都不评估）**。双方均不评估 `globs`，AGENTS.md 在双方均不受 globs 过滤。
- **applyTo 注入**：**Charles 独有**。Charles 实现 `applyTo` 评估，Cline 未实现。AGENTS.md 在 Charles 受 applyTo 过滤（覆盖所有模式 → 通过），在 Cline 不受 applyTo 过滤（评估器不识别）。
- **mode 注入**：**Charles 独有**。Charles 实现 `mode` 评估，Cline 无业务模式概念。AGENTS.md 在 Charles 不使用 mode 字段（省略=无条件通过），在 Cline 不受 mode 过滤。
- **enabled 注入**：**Charles 独有**。Charles 实现 `enabled` 评估，Cline 未实现。AGENTS.md 在 Charles 不使用 enabled 字段（省略=默认 True），在 Cline 不受 enabled 过滤。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.6.1 | alwaysApply 注入 | **未评估**：`alwaysApply` 作为 unknown key 被忽略（rule-conditionals.ts L89-90），AGENTS.md 的 `alwaysApply: true` 无任何效果 | **未评估**：`evaluate_rule_conditionals` 不识别 `alwaysApply`（仅处理 `enabled`/`applyTo`/`mode`/`paths`，rules_loader.py L452-481），AGENTS.md 的 `alwaysApply: true` 无任何效果 | 高（都不评估） | 计划表标注"已对齐"**误导**：对齐方式是"都不评估"而非"都评估"。AGENTS.md 的"常驻"在 Cline 由"无 paths → paths 评估器不触发 → 默认通过"实现，在 Charles 由"`applyTo: [act, plan]` 覆盖所有模式"实现。`alwaysApply` 是从 Cursor Rules 复制过来的死字段 |
| 6.6.2 | applyTo 字段 | **未实现**：`conditionalEvaluators` 仅注册 `paths`（rule-conditionals.ts L74-76），`applyTo` 作为 unknown key 被忽略（L89-90）。Cline AGENTS.md 示例**无此字段** | **已实现**：`_evaluate_apply_to_conditional`（rules_loader.py L369-400），基于 `context.agent_mode` 评估，省略=无条件通过，空数组=fail-closed，命中即激活。Charles AGENTS.md 用 `applyTo: [act, plan]` 覆盖所有 agent 模式 | Charles 独有 | 计划表标注"已对齐（Stage P3）"**严重错误**。Cline 未实现 applyTo 评估，Charles 是独有增强。Stage P3 的对齐工作实际是 Charles 单方面扩展 |
| 6.6.3 | 按 mode 注入 | **未实现**：`RuleEvaluationContext`（rule-conditionals.ts L14-20）仅含 `paths` 字段，无 `agent_mode`/`business_modes` 概念。Cline AGENTS.md 不按 mode 过滤 | **已实现**：`applyTo`（agent 模式过滤，rules_loader.py L369-400）+ `mode`（业务模式过滤，L403-430）双层 mode 评估。Charles AGENTS.md 用 `applyTo: [act, plan]` 实现 agent 模式覆盖 | Charles 独有 | 计划表标注"已对齐"**严重错误**。Cline 无 mode 注入概念，Charles 独有增强。Charles 的 mode 注入分两层：`applyTo`（act/plan agent 模式）+ `mode`（research/trade 业务模式） |
| 6.6.4 | globs 匹配 | **未评估**：`globs` 作为 unknown key 被忽略（rule-conditionals.ts L89-90）。Cline AGENTS.md 示例用 `globs: "*.ts,*.tsx,..."` 但**写而不读**。Cline 真正评估的路径字段是 `paths` | **未评估**：`evaluate_rule_conditionals` 不识别 `globs`（仅识别 `paths`，rules_loader.py L474）。Charles AGENTS.md 未使用 `globs` | 高（都不评估） | 计划表标注"Charles 缺失"**事实错误**。Cline 也不评估 `globs`，两者行为一致。`globs` 是 Cursor Rules 字段，Cline 和 Charles 均解析但不评估。Charles 在 `paths` 字段上与 Cline 评估器字段名对齐 |
| 6.6.5 | enabled 注入 | **未实现**：`enabled` 作为 unknown key 被忽略（rule-conditionals.ts L89-90）。Cline 无 frontmatter 内嵌开关 | **已实现**：`evaluate_rule_conditionals` L452-455 检查 `enabled` 字段，`enabled: false` 时直接 fail-closed。Charles AGENTS.md 不使用 `enabled`（省略=默认 True） | Charles 独有 | Charles 独有增强。Cline 的开关控制由 toggle（`ClineRulesToggles`）实现，不在 frontmatter 内。Charles 同时支持 toggle（外部控制）+ `enabled`（frontmatter 内嵌控制），toggle 优先级高于 `enabled` |
| 6.6.6 | paths 评估 | `evaluatePathsConditional`（rule-conditionals.ts L39-72）：`picomatch(pattern, { dot: true })` + 空数组 fail-closed + 无候选路径 fail-closed。AGENTS.md 无 `paths` 字段 → 评估器不触发 → 默认通过 | `_evaluate_paths_conditional`（rules_loader.py L336-366）：`wcmatch.glob.globmatch`（回退内置正则）+ 空数组 fail-closed + 无候选路径 fail-closed。AGENTS.md 无 `paths` 字段 → 评估器不触发 → 默认通过 | 高 | glob 语义对齐（picomatch vs wcmatch），fail-closed 策略一致。AGENTS.md 在双方均无 paths 字段，故不受 paths 过滤 |
| 6.6.7 | AGENTS.md 加载路径 | `external-rules.ts` L38-42：AGENTS.md 作为 `agentsRulesFile` 走 `synchronizeRuleToggles` + `getRuleFilesTotalContentWithMetadata`（toggle 控制 + paths 评估） | **双路径**：① 全局 `~/.agent/AGENTS.md` + workspace `agents_path` 走 `_strip_frontmatter` **无条件加载**（context.py L471-497，`activated=True` 硬编码）；② rules_dir 下 `agent_config/rules/AGENTS.md` 走 `load_rules_directory` **条件评估**（context.py L541-609） | 中 | Charles 双路径设计：全局/workspace AGENTS.md 无条件加载（保底常驻），rules_dir 内 AGENTS.md 条件评估（与其他规则文件同流程）。Cline 单路径：AGENTS.md 作为 external-rules 走统一 toggle + paths 评估 |
| 6.6.8 | toggle 控制 | `getRuleFilesTotalContentWithMetadata` L220-222：`toggles[ruleFilePath] === false` 时跳过。toggle key 为**绝对路径** | `load_rules_directory` L613-622：`toggles.get(toggle_key, True) is False` 时跳过。toggle key 为**POSIX 相对路径**（支持绝对路径 fallback） | 高 | Stage 13.3 完成对齐：global + local 双层 toggle 结构一致。toggle 优先级高于 frontmatter 条件评估：toggle=False 时直接跳过，不进入 `evaluate_rule_conditionals` |
| 6.6.9 | fail-open 策略 | `getRuleFilesTotalContentWithMetadata` L233-235：frontmatter 解析失败时保留原文（含 frontmatter），仍注入 | `load_rules_directory` L635-647：frontmatter 解析失败时保留原文（含 frontmatter），仍注入（`activated=True`） | 高 | 双方 fail-open 语义一致：解析失败不阻断注入，让 LLM 看到 author 的意图。Charles 额外记录 `parse_error` 便于调试 |
| 6.6.10 | 未知字段处理 | rule-conditionals.ts L89-90：`if (!evaluator) continue`（unknown conditional 忽略，forward compat） | rules_loader.py L452-481：仅处理 `enabled`/`applyTo`/`mode`/`paths` 四个 key，其他字段隐式忽略 | 高 | 双方 unknown 字段忽略策略一致。Charles 评估器覆盖更多字段，但未知字段（如 `globs`/`alwaysApply`/`description`）在双方均忽略 |

---

## 三、重点差距详解

### 3.1 计划文件 P6.6 的事实错误（必须修正）

AGENT_COMPARISON_PLAN_V2.md L2362-2379 给出的对比表基于"Cline 有 alwaysApply + applyTo + globs 三类条件注入"的错误前提，与 Cline 实际源码不符。

**实际 Cline 源码核实结果**：

| 字段 | Cline rule-conditionals.ts 评估器 | Cline AGENTS.md frontmatter | Charles rules_loader.py 评估器 | Charles AGENTS.md frontmatter | 计划表声明 |
|------|-----------------------------------|----------------------------|-------------------------------|-------------------------------|-----------|
| alwaysApply | **不识别**（unknown key 忽略） | `alwaysApply: true`（死字段） | **不识别**（仅 4 字段） | `alwaysApply: true`（死字段） | "always \| always \| 已对齐" ✗（误导） |
| applyTo | **不识别**（unknown key 忽略） | **无此字段** | **识别**（`_evaluate_apply_to_conditional`） | `applyTo: [act, plan]`（活字段） | "是 \| 是 \| 已对齐" ✗（虚构） |
| mode | **不识别**（无 `business_modes` 概念） | **无此字段** | **识别**（`_evaluate_business_mode_conditional`） | **无此字段**（省略=无条件通过） | "是 \| 是 \| 已对齐" ✗（虚构） |
| globs | **不识别**（unknown key 忽略） | `globs: "*.ts,..."`（死字段） | **不识别**（仅 `paths`） | **无此字段** | "是 \| 无 \| Charles 缺失" ✗（事实错误） |
| paths | **识别**（`evaluatePathsConditional`） | **无此字段** | **识别**（`_evaluate_paths_conditional`） | **无此字段** | 未列入对比表（遗漏） |
| enabled | **不识别**（unknown key 忽略） | **无此字段** | **识别**（L452-455） | **无此字段**（默认 True） | 未列入对比表（遗漏） |

**修正建议**：
- 6.6.1 改为"alwaysApply 注入：Cline 未评估 \| Charles 未评估 \| 高（都不评估，死字段）"
- 6.6.2 改为"applyTo 字段：Cline 未实现 \| Charles 已实现 \| Charles 独有增强"
- 6.6.3 改为"按 mode 注入：Cline 未实现 \| Charles 已实现（applyTo + mode 双层） \| Charles 独有增强"
- 6.6.4 改为"globs 匹配：Cline 未评估 \| Charles 未评估 \| 高（都不评估，死字段）"
- 新增 6.6.5"enabled 注入：Cline 未实现 \| Charles 已实现 \| Charles 独有增强"
- 新增 6.6.6"paths 评估：Cline 已实现 \| Charles 已实现 \| 高（已对齐）"

### 3.2 Cline 评估器注册表（事实核查）

Cline `rule-conditionals.ts` L74-76 的 `conditionalEvaluators` 注册表是本阶段最关键的证据：

```typescript
// rule-conditionals.ts L74-76
const conditionalEvaluators: Record<string, ConditionalEvaluatorWithMatch> = {
    paths: evaluatePathsConditional,   // 仅 paths，无 alwaysApply/applyTo/mode/globs/enabled
}
```

`evaluateRuleConditionals`（L78-103）遍历 frontmatter 所有 key，仅在 `conditionalEvaluators` 注册表中查找到的 key 才触发评估器，其他 key（包括 `alwaysApply`/`applyTo`/`globs`/`mode`/`enabled`/`description`）均走 L89-90 的 `if (!evaluator) continue` 分支被忽略。

Cline `RuleEvaluationContext`（L14-20）仅含 `paths` 一个字段：

```typescript
// rule-conditionals.ts L14-20
export type RuleEvaluationContext = {
    paths?: string[]
}
```

无 `agent_mode`/`business_modes`/`mode` 概念，从数据结构层面证明了 Cline 不支持按 mode 注入。

### 3.3 Charles 评估器覆盖范围（严格超集）

Charles `evaluate_rule_conditionals`（rules_loader.py L433-481）评估 4 个字段，是 Cline 的严格超集：

| 评估器 | Charles 位置 | Cline 对应 | 关系 |
|--------|-------------|-----------|------|
| `_evaluate_apply_to_conditional` | L369-400 | 无 | Charles 独有 |
| `_evaluate_business_mode_conditional` | L403-430 | 无 | Charles 独有 |
| `_evaluate_paths_conditional` | L336-366 | `evaluatePathsConditional` | 已对齐 |
| `enabled` 检查（内联） | L452-455 | 无 | Charles 独有 |

Charles 的 `RuleEvaluationContext`（rules_loader.py L111-123）含 3 个字段：

```python
@dataclass
class RuleEvaluationContext:
    agent_mode: str | None = None
    business_modes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
```

比 Cline 的 `RuleEvaluationContext` 多出 `agent_mode`（对应 `applyTo` 评估）和 `business_modes`（对应 `mode` 评估）两个字段。

### 3.4 AGENTS.md 加载路径差异（Charles 双路径设计）

Charles 的 AGENTS.md 条件注入存在**双路径设计**，这是与 Cline 的关键架构差异：

**路径 1：全局/workspace AGENTS.md 无条件加载**（context.py L471-497）

```python
# context.py L471-483
global_agents_path = Path.home() / ".agent" / "AGENTS.md"
if global_agents_path.exists():
    content = global_agents_path.read_text(encoding="utf-8").strip()
    if content:
        results.append(RuleLoadResult(
            path=global_agents_path,
            body=self._strip_frontmatter(content),
            activated=True,  # 硬编码 True，不走 evaluate_rule_conditionals
        ))
```

全局 `~/.agent/AGENTS.md` 和 workspace `agents_path` AGENTS.md 均走 `_strip_frontmatter` 仅剥离 frontmatter，**不评估任何条件**，`activated=True` 硬编码。这意味着这两个 AGENTS.md 永远注入，不受 applyTo/mode/paths/enabled 过滤。

**路径 2：rules_dir 下 AGENTS.md 条件评估**（context.py L541-609）

```python
# context.py L602-607
directory_results = load_rules_directory(
    self.rules_dir,
    context=context,  # 含 agent_mode + business_modes + paths
    toggles=merged_toggles or None,
    excluded_subdirs=excluded_subdirs,
)
```

`agent_config/rules/AGENTS.md` 作为 rules_dir 下的一个 .md 文件，走 `load_rules_directory` 完整流程：toggle 控制 + frontmatter 解析 + `evaluate_rule_conditionals` 条件评估。其 `applyTo: [act, plan]` 字段会被 `_evaluate_apply_to_conditional` 评估，覆盖所有 agent 模式 → 通过。

**Cline 单路径设计**：Cline AGENTS.md 作为 `agentsRulesFile`（external-rules.ts L38-42）走 `synchronizeRuleToggles` + `getRuleFilesTotalContentWithMetadata` 统一流程，toggle 控制 + paths 评估。AGENTS.md 无 `paths` 字段 → paths 评估器不触发 → 默认通过。

**差异影响**：Charles 的双路径设计意味着同一份 AGENTS.md 内容（若同时存在于 `~/.agent/AGENTS.md` 和 `agent_config/rules/AGENTS.md`）会被注入两次。实际部署中通常只存在一份，但架构上 Charles 比 Cline 多出"全局保底常驻"层。

### 3.5 alwaysApply 死字段溯源

`alwaysApply` 是 Cursor Rules 的字段，Cline 在解析阶段（`parseYamlFrontmatter`）将其存入 `data` dict，但评估阶段（`evaluateRuleConditionals`）不识别此 key。Cline 官方 AGENTS.md 示例（`sdk/AGENTS.md` L4 + `sdk/packages/llms/AGENTS.md` L4）写了 `alwaysApply: true` 但实际无效果——这是从 Cursor Rules 复制过来的遗留字段。

Charles AGENTS.md 同样写了 `alwaysApply: true`（L4），同样不被 `evaluate_rule_conditionals` 识别。Charles 的"常驻"语义实际由 `applyTo: [act, plan]`（L3）覆盖所有 agent 模式实现。`alwaysApply` 在 Charles 也是死字段。

**修正方向**（非本阶段范围，仅记录）：Charles AGENTS.md 可移除 `alwaysApply: true` 行，避免误导。实际常驻由 `applyTo: [act, plan]` 保证。

### 3.6 globs 死字段溯源

`globs` 同样是 Cursor Rules 的字段。Cline AGENTS.md 示例用 `globs: "*.ts,*.tsx,..."`（`sdk/AGENTS.md` L3）但评估器不识别。Cline 真正用于路径过滤的字段名是 `paths`（rule-conditionals.ts L75），与 Charles 评估器字段名对齐。

Charles AGENTS.md 未使用 `globs`（避免死字段），评估器也不识别 `globs`。Charles 在这一点上**比 Cline 自身更自洽**——Cline 自己的 AGENTS.md 写了 `globs` 但评估器不读，Charles 既不写也不读。

### 3.7 与 P5.8 / P6.1 的关联

本阶段的发现与 P5.8（Cline Rules 段对比）+ P6.1（AGENTS.md frontmatter 对比）完全一致，三份报告形成交叉验证：

| 发现点 | P5.8 | P6.1 | P6.6（本阶段） |
|--------|------|------|---------------|
| Cline 仅评估 `paths` | 5.8.3 已确认 | 6.1.7 已确认 | 6.6.2/6.6.3/6.6.4 再次确认 |
| `applyTo` 是 Charles 独有 | 5.8.6 已确认 | 6.1.4 已确认 | 6.6.2 再次确认 |
| `alwaysApply` 双方都不评估 | 5.8.7 已确认 | 6.1.5 已确认 | 6.6.1 再次确认 |
| `globs` 双方都不评估 | 5.8.5 已确认 | 6.1.3 已确认 | 6.6.4 再次确认 |
| Charles 评估器是 Cline 超集 | 5.8.3 已确认 | 6.1.7 已确认 | 6.6.5/6.6.6 再次确认 |

P6.6 的增量贡献在于：
1. 聚焦"条件注入流程"层面（AGENTS.md 加载时是否真正触发条件评估），而非 P5.8 的"Rules 段整体"或 P6.1 的"frontmatter 字段集合"。
2. 首次揭示 Charles 的**双路径 AGENTS.md 加载设计**（全局无条件 + rules_dir 条件评估），这是 P5.8/P6.1 未涉及的角度。
3. 首次系统对比 `enabled` 字段（P5.8/P6.1 未单独列出）。

---

## 四、nanobot 残留检查

本阶段范围内（AGENTS.md 条件注入相关代码）的 nanobot 残留检查结果：

| 文件 | 残留类型 | 残留位置 | 残留内容 | 处理建议 |
|------|---------|---------|---------|---------|
| `agent/rules_loader.py` | — | — | **0 处残留** | 无需处理 |
| `agent/context.py` | 注释残留 | L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` | 与 P5.8 / P6.1 同一处，docstring 描述 `extra_sections` 参数来源。该参数已废弃，保留签名仅为向后兼容。**注释残留，非实现逻辑残留**，不影响功能。可后续清理时一并移除 |
| `agent/context.py` | 实现逻辑残留 | — | **0 处残留** | 条件注入逻辑（`_build_rules` + `_load_rules_directory` + `_strip_frontmatter`）完全基于 Charles 自研 + 对标 Cline，无 nanobot 代码 |

**结论**：AGENTS.md 条件注入相关代码 **1 处注释残留 + 0 处实现逻辑残留**。注释残留为 docstring 中描述参数历史来源的说明性文字，不影响功能正确性，与 P5.8 / P6.1 同一处（L275）。

---

## 五、总结

### 关键差异清单

1. **Cline 条件注入仅 `paths` 一个评估器**（rule-conditionals.ts L74-76），`alwaysApply`/`applyTo`/`globs`/`mode`/`enabled` 均被忽略。
2. **Charles 条件注入是 Cline 严格超集**（rules_loader.py L433-481），评估 `enabled`/`applyTo`/`mode`/`paths` 四字段。
3. **`alwaysApply` 在双方均为死字段**，AGENTS.md 的"常驻"由其他机制实现（Cline 靠"无 paths → 默认通过"，Charles 靠"`applyTo: [act, plan]` 覆盖所有模式"）。
4. **`globs` 在双方均为死字段**，Cline AGENTS.md 写而不读，Charles 不写不读。
5. **`applyTo`/`mode`/`enabled` 是 Charles 独有增强**，Cline 无对应评估器。
6. **`paths` 评估已对齐**（picomatch vs wcmatch），AGENTS.md 在双方均无 paths 字段，不受过滤。
7. **Charles AGENTS.md 双路径加载**（全局无条件 + rules_dir 条件评估），Cline 单路径（external-rules 统一流程）。
8. **nanobot 残留**：1 处注释残留（context.py L275），0 处实现逻辑残留。

### 计划文件修正清单

| 计划表条目 | 原标注 | 修正后 |
|-----------|--------|--------|
| 6.6.1 | always \| always \| 已对齐 | 未评估 \| 未评估 \| 高（都不评估，死字段） |
| 6.6.2 | 是 \| 是 \| 已对齐（Stage P3） | 未实现 \| 已实现 \| Charles 独有增强 |
| 6.6.3 | 是 \| 是 \| 已对齐 | 未实现 \| 已实现（applyTo + mode 双层） \| Charles 独有增强 |
| 6.6.4 | 是 \| 无 \| Charles 缺失 | 未评估 \| 未评估 \| 高（都不评估，死字段） |
| 新增 6.6.5 | — | 未实现 \| 已实现 \| Charles 独有增强（enabled） |
| 新增 6.6.6 | — | 已实现 \| 已实现 \| 高（paths 评估已对齐） |

### 与 P5.8 / P6.1 的关系

本阶段发现与 P5.8（5.8.3/5.8.5/5.8.6/5.8.7）+ P6.1（6.1.3/6.1.4/6.1.5/6.1.7）完全一致，三份报告交叉验证同一组事实：Cline 仅评估 `paths`，Charles 评估 4 字段，`alwaysApply`/`globs` 在双方均为死字段。P6.6 的增量贡献在于揭示 Charles 双路径 AGENTS.md 加载设计 + 系统对比 `enabled` 字段。
