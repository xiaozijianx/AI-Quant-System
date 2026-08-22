# Phase 5.8 Cline Rules 段对比

> 对比范围：Cline `cline-rules.ts` + `frontmatter.ts` + `rule-conditionals.ts` + `rule-helpers.ts` + `external-rules.ts` + `workflows.ts` 与 Charles `rules_loader.py` + `context.py::_build_rules` + `agent_config/rules/` 目录的规则目录扫描、frontmatter 解析、rule-conditionals 按 mode 加载、external-rules、workflows 等 10 项逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts` L1-34（`refreshClineRulesToggles`：global + local 双层 toggle 同步，排除 `.clinerules/{workflows,hooks,skills}` 子目录）
> - `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts` L1-59（`parseYamlFrontmatter`：stripUtf8Bom + 正则匹配 + `yaml.load(JSON_SCHEMA)` + fail-open）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts` L1-153（`evaluateRuleConditionals`：**仅评估 `paths` 字段**，`RuleEvaluationContext.paths`，`picomatch(pattern, { dot: true })` + `extractPathLikeStrings` 启发式路径提取）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L1-467（`synchronizeRuleToggles` + `getRuleFilesTotalContentWithMetadata`：toggle key 为**绝对路径**，rule 输出格式为 `${ruleFilePathRelative}\n${body}` 无 `##` 标题）
> - `apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts` L1-49（`refreshExternalRulesToggles`：扫描 `.cursorrules` / `.cursor/rules/*.mdc` / `.windsurfrules` / `AGENTS.md`）
> - `apps/vscode/src/core/context/instructions/user-instructions/workflows.ts` L1-32（`refreshWorkflowToggles`：`.clinerules/workflows/` 子目录独立 toggle 槽）
> - `apps/vscode/src/core/storage/disk.ts` L17-41（`GlobalFileNames`：`clineRules: ".clinerules"` / `workflows: ".clinerules/workflows"` / `cursorRulesFile: ".cursorrules"` / `agentsRulesFile: "AGENTS.md"`）
> - `sdk/packages/shared/src/prompt/cline.ts` L145-151（`effectiveRules = [rules, MODE_TAG, PLAN_MODE].filter(Boolean).join("\n\n")` 拼接）
> - `docs/customization/cline-rules.mdx`（Cline Rules 官方文档：`paths` 是当前唯一支持的 conditional；unknown 字段忽略；无 frontmatter 始终激活）
>
> Charles 源码：
> - `agent/rules_loader.py` L1-1053（`parse_yaml_frontmatter` + `evaluate_rule_conditionals` + `load_rules_directory` + `format_rules_content` + `synchronize_rule_toggles` + Stage 13.3 local toggle 分离）
> - `agent/context.py` L454-609（`SystemPromptBuilder._build_rules` 编排器方法 + `_load_rules_directory` 兼容层）
> - `agent_config/rules/` 目录（含 `AGENTS.md` / `general.md` / `plan-mode-rules.md` / `research.md` / `trading.md` 5 个规则文件）
> - `agent_config/rule_toggles.json`（global toggle 持久化文件，key 为 POSIX 相对路径）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Rules 段（用户规则文件加载与条件评估）实现。**核心结论：Charles 已通过 Stage 7.1 + 7.2 + 7.4 + 13.3 四个阶段重构完成对齐，与 Cline 在 frontmatter 解析、paths 条件评估、toggle 持久化、excluded_subdirs 过滤 4 个维度达到高一致性；且 Charles 在 conditional 评估维度比 Cline 更丰富（多出 `applyTo` agent 模式 / `mode` 业务模式 / `enabled` 开关三类评估器）**；剩余差异主要在于规则目录路径、AGENTS.md 位置、external-rules 支持、workflows 子目录处理、rule 输出格式等技术细节。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.8（L1934-1962）的对比表存在 **3 处事实错误 + 1 处误导性描述**，需逐项修正：

1. **5.8.3 标注"rule-conditionals 按 mode 加载 — Charles 缺失"** — **严重事实错误**：Charles 实际实现了 4 个 conditional 评估器（`applyTo` + `mode` + `paths` + `enabled`，rules_loader.py L433-481），**比 Cline 多出 3 个**。Cline 仅实现 `paths` 一个评估器（rule-conditionals.ts L74-76）。Charles 不是"缺失"而是"超越"。

2. **5.8.5 标注"globs 匹配 — Charles 缺失"** — **事实错误**：Cline 也**未实现 `globs` 字段评估**。Cline `conditionalEvaluators` 对象（rule-conditionals.ts L74-76）仅注册 `paths` 一个 key，`globs` 作为 unknown key 被 `continue` 忽略（L89-90）。`globs` 是 Cursor Rules 字段，Cline 解析但**不评估**。Charles 同样解析但不评估。两者行为一致，非"Charles 缺失"。

3. **5.8.6 标注"applyTo 字段 plan/act — Charles 缺失"** — **严重事实错误**：Charles 实际实现 `_evaluate_apply_to_conditional`（rules_loader.py L369-400），基于 `context.agent_mode` 评估 `applyTo: [plan, act]` 字段。Cline **未实现** `applyTo` 评估——`applyTo` 在 Cline 中仅作为 frontmatter 元数据存储于 `data` dict，**不参与条件判断**。Charles 不是"缺失"而是"独有增强"。

4. **5.8.7 标注"alwaysApply 字段 — 已对齐"** — **误导性描述**：两者确实"已对齐"，但**对齐方式是"都不评估"**而非"都评估"。Cline `evaluateRuleConditionals` 不识别 `alwaysApply`（unknown key 忽略，rule-conditionals.ts L89-90）；Charles `evaluate_rule_conditionals` 也不识别 `alwaysApply`（仅处理 `enabled` / `applyTo` / `mode` / `paths` 四个 key，rules_loader.py L452-481）。Charles AGENTS.md 中 `alwaysApply: true` 字段被解析但**实际无任何效果**——这是从 Cursor Rules 复制过来的死字段。

### 核心结论

1. **规则目录扫描已对齐**（路径不同）：Cline 用 `.clinerules/`（workspace） + `~/Documents/Cline/Rules`（global）；Charles 用 `agent_config/rules/`（workspace） + `~/.agent/AGENTS.md`（global，单文件而非目录）。
2. **frontmatter 解析已对齐**：两者均实现 stripUtf8Bom + 正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` + YAML safe_load + fail-open，正则完全一致。
3. **paths 条件评估已对齐**：两者均实现 glob 匹配（Cline 用 picomatch；Charles 优先用 wcmatch，回退到内置正则）、空数组 fail-closed、无候选路径 fail-closed。
4. **Charles conditional 评估更丰富**（独有增强）：Charles 多出 `applyTo`（agent 模式过滤）+ `mode`（业务模式过滤）+ `enabled`（frontmatter 内嵌开关）三类评估器，Cline 均无。
5. **toggle 持久化已对齐**（Stage 13.3 完成对齐）：两者均实现 global + local 双层 toggle（Cline 用 stateManager 的 `globalClineRulesToggles` + `localClineRulesToggles`；Charles 用 `rule_toggles.json` + `sessions/<id>/rule_toggles.local.json`）。
6. **excluded_subdirs 已对齐**（Stage 7.4 完成对齐）：Cline 通过 `excludedPaths: [[".clinerules", "workflows"], [".clinerules", "hooks"], [".clinerules", "skills"]]` 参数排除（cline-rules.ts L23-27）；Charles 通过 `excluded_subdirs=["workflows", "hooks", "skills"]` 参数排除（context.py L554）。
7. **external-rules 未实施**（合理偏离）：Charles 不扫描 `.cursorrules` / `.windsurfrules` / `.cursor/rules/` 等外部规则文件格式。Charles 专注 Python 量化投研场景，无跨工具规则兼容需求。
8. **workflows 子目录处理差异**：Cline 把 `.clinerules/workflows/` 作为独立 toggle 槽加载（workflows.ts）；Charles 通过 `excluded_subdirs` 直接排除，不作为规则加载。
9. **rule 输出格式差异**：Cline 用 `${ruleFilePathRelative}\n${body}` 格式（文件相对路径作为 label，无 `##` 标题）；Charles 用 `## {file_stem}\n\n{body}` 格式（文件 stem 作为 markdown `##` 标题）+ 顶部 `# Rules` 总标题。
10. **nanobot 残留**：rules_loader.py **0 处残留**；context.py rules 相关代码 **1 处注释残留 + 0 处实现逻辑残留**（L275 `extra_sections` docstring，与 Phase 5.1 同一处）。

### 一致性总体评估

- **frontmatter 解析**：**高**。正则、BOM 剥离、fail-open 策略、YAML safe_load 完全一致。
- **paths 条件评估**：**高**。glob 语义对齐（picomatch vs wcmatch），fail-closed 策略一致。
- **toggle 持久化**：**高**。global + local 双层结构对齐，Stage 13.3 完成对齐。
- **conditional 评估**：**Charles 增强**。Charles 多出 `applyTo` / `mode` / `enabled` 三类评估器，Cline 无对应实现。
- **external-rules / workflows**：**中**。Charles 不实施 external-rules（合理偏离）；workflows 子目录处理方式不同（Cline 加载为独立 toggle 槽，Charles 直接排除）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.8.1 | rules 目录 | `.clinerules/`（workspace，disk.ts L29） + `~/Documents/Cline/Rules/`（global，disk.ts L62-69） | `agent_config/rules/`（workspace，context.py L531） + `~/.agent/AGENTS.md`（global 单文件，context.py L472） | 中 | 路径不同。Cline global 是目录（多文件），Charles global 是单文件。Charles workspace rules_dir 含 AGENTS.md，Cline workspace AGENTS.md 在根目录（不在 `.clinerules/` 内） |
| 5.8.2 | frontmatter 解析 | `parseYamlFrontmatter`（frontmatter.ts L38-59）：stripUtf8Bom + 正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` + `yaml.load(JSON_SCHEMA)` + fail-open | `parse_yaml_frontmatter`（rules_loader.py L131-181）：stripUtf8Bom + 正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` + `yaml.safe_load` + fail-open + 顶层非 dict 视为解析失败 | 高 | 正则完全一致，BOM 剥离一致，fail-open 策略一致。Charles 多出顶层类型校验（非 dict 时 fail-open），属增强 |
| 5.8.3 | rule-conditionals 按 mode 加载 | **仅评估 `paths`**（rule-conditionals.ts L74-76），`conditionalEvaluators = { paths: evaluatePathsConditional }`。`applyTo` / `mode` / `enabled` / `alwaysApply` / `globs` 等 key 均作为 unknown 被忽略（L89-90 `continue`） | **评估 4 个字段**：`enabled`（L452-455） + `applyTo`（L457-463） + `mode`（L465-471） + `paths`（L473-479），其他字段忽略 | Charles 增强 | 计划表标注"Charles 缺失"**严重错误**。Charles 比 Cline 多出 3 个评估器：`applyTo`（agent 模式过滤）+ `mode`（业务模式过滤）+ `enabled`（frontmatter 内嵌开关） |
| 5.8.4 | external-rules | `refreshExternalRulesToggles`（external-rules.ts L10-49）：扫描 `.cursorrules`（`cursorRulesFile`）+ `.cursor/rules/*.mdc`（`cursorRulesDir`）+ `.windsurfrules`（`windsurfRules`）+ `AGENTS.md`（`agentsRulesFile`）4 类外部规则 | 无（不实施） | 低 | Charles 不扫描 Cursor / Windsurf / AGENTS.md 外部规则文件。合理偏离：Charles 专注 Python 量化投研，无跨工具规则兼容需求 |
| 5.8.5 | globs 匹配 | **未实现**：`globs` 作为 unknown key 被忽略（rule-conditionals.ts L89-90） | **未实现**：`globs` 字段被解析但未注册评估器 | 高 | 计划表标注"Charles 缺失"**事实错误**。两者行为一致：`globs` 是 Cursor Rules 字段，Cline 和 Charles 均解析但不评估 |
| 5.8.6 | applyTo 字段（plan/act） | **未实现**：`applyTo` 作为 unknown key 被忽略（rule-conditionals.ts L89-90） | **已实现**：`_evaluate_apply_to_conditional`（rules_loader.py L369-400），基于 `context.agent_mode` 评估，省略=无条件通过，空数组=fail-closed，命中即激活 | Charles 独有 | 计划表标注"Charles 缺失"**严重错误**。Charles 实现 applyTo 评估，Cline 未实现。Charles AGENTS.md 中 `applyTo: [act, plan]` 字段实际有效 |
| 5.8.7 | alwaysApply 字段 | **未实现**：`alwaysApply` 作为 unknown key 被忽略 | **未实现**：`evaluate_rule_conditionals` 不识别 `alwaysApply`，仅处理 `enabled` / `applyTo` / `mode` / `paths` | 高（都不实现） | 计划表标注"已对齐"**误导**：对齐方式是"都不评估"而非"都评估"。Charles AGENTS.md 中 `alwaysApply: true` 字段被解析但**无任何效果**——从 Cursor Rules 复制过来的死字段 |
| 5.8.8 | rule_toggles | `synchronizeRuleToggles`（rule-helpers.ts L40-104）：key 为**绝对路径**，持久化于 `stateManager` 的 `globalClineRulesToggles`（global）+ `localClineRulesToggles`（local），通过 `setGlobalState` / `setWorkspaceState` 写入 | `synchronize_rule_toggles`（rules_loader.py L889-957）：key 为 **POSIX 相对路径**，持久化于 `rule_toggles.json`（global）+ `sessions/<id>/rule_toggles.local.json`（local），通过 JSON 文件写入 | 高 | Stage 13.3 完成对齐：global + local 双层结构一致。key 格式不同（绝对路径 vs 相对路径），存储介质不同（stateManager vs JSON 文件），语义对齐 |
| 5.8.9 | rule name | `ruleFilePathRelative`（rule-helpers.ts L218 + L246）：输出格式 `${ruleFilePathRelative}\n${body}`，使用**相对文件路径**作为 label（如 `.clinerules/general.md`），无 `##` 标题 | `r.path.stem`（rules_loader.py L716-717）：输出格式 `## {stem}\n\n{body}`，使用**文件 stem**（如 `general`）作为 markdown `##` 标题 | 中 | 计划表标注"Cline watcher.name"**不准确**：Cline 用相对路径字符串，非 watcher.name。Charles 用 stem + `##` 标题。输出结构差异显著：Cline 无 markdown 标题层级，Charles 有 `# Rules` 顶部标题 + `## {stem}` 二级标题 |
| 5.8.10 | 段落位置 | base prompt 第 6 段（system.ts L35）：`{{CLINE_RULES}}`，位于 `<env>` 段之后、`{{CLINE_METADATA}}` 之前 | base prompt 第 6 段（charles_system_prompt.py L56 + L89）：`{{CHARLES_RULES}}`，位于 `<env>` 段之后、`{{CHARLES_METADATA}}` 之前 | 高 | 完全一致。两者均位于 `<env>` 之后、metadata 之前，DEFAULT / YOLO 双模板均遵循此顺序 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.8 三处事实错误（5.8.3 + 5.8.5 + 5.8.6）

AGENT_COMPARISON_PLAN_V2.md L1952-1955 的对比表存在系统性误判，将 Charles 实际已实现或比 Cline 更丰富的功能标注为"Charles 缺失"。逐项核查源码：

**5.8.3 rule-conditionals 按 mode 加载**（计划表标注"Charles 缺失"）：

```typescript
// Cline rule-conditionals.ts L74-76 — 仅注册 paths 一个评估器
const conditionalEvaluators: Record<string, ConditionalEvaluatorWithMatch> = {
	paths: evaluatePathsConditional,
}

// L87-91 — unknown key 被忽略
for (const [key, value] of Object.entries(frontmatter)) {
	const evaluator = conditionalEvaluators[key]
	if (!evaluator) {
		continue // unknown conditional: ignore
	}
	...
}
```

```python
# Charles rules_loader.py L433-481 — 评估 4 个字段
def evaluate_rule_conditionals(frontmatter, context):
    matched_conditions: dict[str, list[str]] = {}

    # 1. enabled 开关（L452-455）—— Charles 独有
    enabled = frontmatter.get("enabled", True)
    if enabled is not None and enabled is False:
        return False, {}

    # 2. applyTo 条件（L457-463）—— Charles 独有
    if "applyTo" in frontmatter:
        passed, matched = _evaluate_apply_to_conditional(...)

    # 3. mode 条件（L465-471）—— Charles 独有
    if "mode" in frontmatter:
        passed, matched = _evaluate_business_mode_conditional(...)

    # 4. paths 条件（L473-479）—— 与 Cline 对齐
    if "paths" in frontmatter:
        passed, matched = _evaluate_paths_conditional(...)

    return True, matched_conditions
```

**核查结论**：Cline 仅实现 `paths` 一个评估器，`applyTo` / `mode` / `enabled` / `alwaysApply` / `globs` 等 key 均作为 unknown 被 `continue` 忽略。Charles 实现 4 个评估器，**比 Cline 多 3 个**。计划表标注"Charles 缺失"严重错误。

**5.8.5 globs 匹配**（计划表标注"Charles 缺失"）：

Cline `conditionalEvaluators` 对象（rule-conditionals.ts L74-76）的 key 集合为 `{ paths }`，`globs` 不在其中，作为 unknown key 走 L89-90 `continue` 分支被忽略。Charles `evaluate_rule_conditionals`（rules_loader.py L433-481）的 if 链覆盖 `{ enabled, applyTo, mode, paths }`，`globs` 同样不在其中，被 if 链跳过。两者行为完全一致：**解析但都不评估 `globs` 字段**。`globs` 是 Cursor Rules 的字段，Cline 和 Charles 均未实施。计划表标注"Charles 缺失"错误。

**5.8.6 applyTo 字段**（计划表标注"Charles 缺失"）：

Cline `conditionalEvaluators` 不含 `applyTo` key（rule-conditionals.ts L74-76），`applyTo` 作为 unknown 被忽略。Charles `_evaluate_apply_to_conditional`（rules_loader.py L369-400）实现完整评估逻辑：

```python
# rules_loader.py L369-400
def _evaluate_apply_to_conditional(frontmatter_value, context):
    if frontmatter_value is None:
        return True, []  # 省略 → 无条件通过
    if not _is_non_empty_string_array(frontmatter_value):
        if isinstance(frontmatter_value, list) and len(frontmatter_value) == 0:
            return False, []  # 空数组 → fail-closed
        return True, []  # 类型无效 → fail-open
    if context.agent_mode is None:
        return False, []  # 上下文无 agent mode → fail-closed
    patterns = [p.strip() for p in frontmatter_value if p.strip()]
    if context.agent_mode in patterns:
        return True, [context.agent_mode]
    return False, []
```

Charles AGENTS.md frontmatter `applyTo: [act, plan]` 字段实际被评估并激活。Cline 中相同字段被忽略。计划表标注"Charles 缺失"严重错误——Charles 实现，Cline 未实现。

### 3.2 alwaysApply 字段：从 Cursor Rules 复制的死字段（5.8.7）

Charles `agent_config/rules/AGENTS.md` L1-5 frontmatter：

```yaml
---
description: Charles 投研情报官主规则 — 所有模式和业务场景下常驻应用
applyTo: [act, plan]
alwaysApply: true
---
```

核查 Charles `evaluate_rule_conditionals`（rules_loader.py L433-481）的 if 链：仅识别 `enabled` / `applyTo` / `mode` / `paths` 四个 key，**不识别 `alwaysApply`**。该字段被解析进 `frontmatter.data` dict 后，**在评估阶段被完全跳过**——无任何效果。

核查 Cline `evaluateRuleConditionals`（rule-conditionals.ts L78-103）的 `conditionalEvaluators` 对象：仅注册 `paths`，**不识别 `alwaysApply`**。该字段在 Cline 中同样被解析后跳过。

**核查结论**：`alwaysApply` 是 Cursor Rules 的字段（用于 Cursor UI 中的规则应用模式选择），Cline 和 Charles 均**仅解析不评估**。Charles AGENTS.md 中 `alwaysApply: true` 字段是从 Cursor Rules 模板复制过来的死字段，建议移除以避免误导。

### 3.3 AGENTS.md 位置差异（5.8.1）

Cline 和 Charles 对 AGENTS.md 文件的位置处理策略不同：

**Cline 方案**：
- workspace AGENTS.md：位于 workspace 根目录 `./AGENTS.md`（disk.ts L38 `agentsRulesFile: "AGENTS.md"`），通过 `external-rules.ts` 的 `refreshExternalRulesToggles` 加载（external-rules.ts L39-42）
- global AGENTS.md：位于 `~/.agents/AGENTS.md`（docs/customization/cline-rules.mdx L29 + L40）
- AGENTS.md **不在** `.clinerules/` 目录内，作为独立 external rule 处理

**Charles 方案**：
- workspace AGENTS.md：位于 `agent_config/rules/AGENTS.md`（context.py L531 `rules_dir = project_root / "agent_config" / "rules"`），与其它规则文件同目录
- global AGENTS.md：位于 `~/.agent/AGENTS.md`（context.py L472 `Path.home() / ".agent" / "AGENTS.md"`），单文件
- workspace AGENTS.md 通过 `_build_rules` L486-496 兼容层单独加载（`agents_path` 参数），同时通过 `_load_rules_directory` L602-608 作为 rules_dir 内文件被 `load_rules_directory` 扫描加载——存在**双重加载风险**，Charles 通过 `_load_rules_directory` L572-582 的 `task_type.md` 兼容层 toggle 机制禁用已兼容加载的文件避免重复

**差异影响**：
- Cline：AGENTS.md 与 `.clinerules/` 规则分离，分别走 external-rules 和 cline-rules 通道，互不干扰
- Charles：AGENTS.md 与其它规则文件混在 `rules_dir` 内，通过 `load_rules_directory` 统一扫描；`agents_path` 参数仅为向后兼容保留（新架构下 AGENTS.md 应位于 rules_dir）

**评估**：Charles 方案简化了目录结构（所有规则集中一处），但失去了 Cline 对"跨工具标准 AGENTS.md"与"工具特定 .clinerules"的分离能力。合理偏离，非对齐缺口。

### 3.4 rule 输出格式差异（5.8.9）

Cline 和 Charles 对激活规则的输出格式不同：

**Cline 格式**（rule-helpers.ts L246）：
```typescript
return { contentPart: `${ruleFilePathRelative}\n${body.trim()}`, activatedRule }
```
输出示例：
```
.cinerules/general.md
This file is the secret sauce...

.cinerules/coding.md
Use TypeScript for all new files...
```

**Charles 格式**（rules_loader.py L716-722）：
```python
name = r.path.stem
parts.append(f"## {name}\n\n{body}")
return "# Rules\n\n" + "\n\n".join(parts)
```
输出示例：
```
# Rules

## general

This file is the secret sauce...

## coding

Use TypeScript for all new files...
```

**差异分析**：
- Cline：用**相对文件路径**作为 label（如 `.clinerules/general.md`），无 markdown 标题层级，LLM 看到的是"路径 + 正文"扁平结构
- Charles：用**文件 stem**作为 markdown `##` 二级标题（如 `general`），顶部统一加 `# Rules` 一级标题，LLM 看到的是层级化 markdown 结构
- Charles 注释（rules_loader.py L700）声称"对齐 Cline ## name 格式"，但实际 Cline 并不使用 `##` 标题

**评估**：Charles 的 markdown 层级结构对 LLM 更友好（明确的标题边界），但与 Cline 输出格式不字节一致。属合理设计差异，非对齐缺口。建议在 docstring 中修正"对齐 Cline"措辞为"Charles 优化的输出格式"。

### 3.5 workflows 子目录处理差异

Cline 和 Charles 对 workflows 子目录的处理策略截然不同：

**Cline 方案**：workflows 作为**独立 toggle 槽**加载
- `workflows.ts` L10-32：`refreshWorkflowToggles` 单独同步 workflows toggle
- `cline-rules.ts` L23-27：在 cline-rules toggle 同步时**排除** `.clinerules/workflows`，避免双重加载
- workflows 通过 `globalWorkflowToggles` + `workflowToggles` 双层 toggle 独立管理
- workflow 文件作为独立的"工作流"概念加载，与普通 rules 分离

**Charles 方案**：workflows 直接**排除**，不作为规则加载
- `context.py` L554：`excluded_subdirs = ["workflows", "hooks", "skills"]`
- workflows 子目录的 `.md` 文件**不被加载**到 Rules 段
- Charles 不实施"工作流"概念，仅把 workflows 作为排除目录

**差异影响**：
- Cline：workflows 是一类特殊规则，有独立 UI toggle 和加载通道
- Charles：workflows 是被忽略的子目录，无任何处理

**评估**：Charles 不实施 workflows 概念属合理偏离——Charles 专注 Python 量化投研，无 Cline 那样的 multi-step workflow 自动化需求。但 `excluded_subdirs` 列表中包含 `"workflows"` 说明 Charles 仍保留目录结构兼容性（用户可在 `agent_config/rules/workflows/` 放置文件，但不会被加载），避免与未来可能的 workflow 实现冲突。

### 3.6 Charles 独有增强：mtime 缓存与 task_type 兼容层

Charles 实现了两个 Cline 没有的优化：

**Stage 7.4 mtime 缓存**（rules_loader.py L524-556）：
- 模块级 `_RULES_MTIME_CACHE: dict[str, tuple[int, str, FrontmatterParseResult]]` 缓存
- key 为文件绝对路径，value 为 `(mtime_ns, raw_text, parse_result)` 三元组
- 仅缓存"文件内容 + frontmatter 解析结果"，不缓存"条件评估结果"（条件每次重算）
- 设计对标 Cline `UnifiedConfigFileWatcher` 的增量更新，但实现机制不同：Cline 用 `fs.watch` + 75ms debounce 事件驱动，Charles 用 mtime 轮询（Web 请求-响应模型，每次 build 重读已等价"热重载"）

**task_type 兼容层**（context.py L541-609）：
- `_load_rules_directory` L572-582：先加载 `rules/<task_type>.md` 作为兼容层入口
- 加载后通过 `merged_toggles[rules_file.relative_to(self.rules_dir).as_posix()] = False` 禁用该文件的重复扫描
- 兼容旧接口（`task_type` 参数从 server 层传入），新架构下应直接通过 frontmatter `mode` 字段过滤
- Cline 无此兼容层——Cline 直接扫描 `.clinerules/` 全目录，无 task_type 概念

**评估**：mtime 缓存属性能优化（合理增强）；task_type 兼容层属历史包袱（向后兼容），建议在 major 版本移除。

---

## 四、nanobot 殙留专项检查

### 4.1 检查范围

针对 Rules 段相关文件检查 nanobot 风格残留：
- `agent/rules_loader.py`（全文 1053 行，含 `parse_yaml_frontmatter` + `evaluate_rule_conditionals` + `load_rules_directory` + `format_rules_content` + `synchronize_rule_toggles` + Stage 13.3 local toggle）
- `agent/context.py` rules 相关方法（`_build_rules` L454-539 + `_load_rules_directory` L541-609 + `_build_enhancement_rules` L611-647）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/rules_loader.py` | 0 | 0 | 无残留。所有逻辑均对标 Cline frontmatter.ts / rule-conditionals.ts / rule-helpers.ts，无 nanobot 风格实现 |
| `agent/context.py`（rules 部分） | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`（与 Phase 5.1 同一处） |

### 4.3 残留详情

#### 4.3.1 注释残留（1 处，与 Phase 5.1 同一处）

**位置**：`agent/context.py` L275

```python
def __init__(
    self,
    ...
    extra_sections: dict[str, str] | None = None,
    ...
) -> None:
    """初始化系统提示组装器

    Args:
        ...
        extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                        保留参数签名仅为向后兼容，当前无调用方传入。
        ...
    """
```

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。不影响运行逻辑。此残留已在 Phase 5.1 报告中记录，本阶段不重复计入 Rules 段独立残留。

#### 4.3.2 实现逻辑残留（0 处）

经核查 `rules_loader.py` 全部 1053 行：

- `parse_yaml_frontmatter`（L131-181）：完全对标 Cline `parseYamlFrontmatter`，正则一致，fail-open 策略一致，无 nanobot 风格实现
- `evaluate_rule_conditionals`（L433-481）：4 个评估器（enabled / applyTo / mode / paths）均为 Charles 主动实现的对齐增强，无 nanobot 风格条件评估
- `load_rules_directory`（L568-683）：对标 Cline `getRuleFilesTotalContentWithMetadata`，无 nanobot 风格目录扫描
- `format_rules_content`（L686-722）：使用 `## {stem}` markdown 标题格式，无 nanobot 风格输出
- `synchronize_rule_toggles`（L889-957）：对标 Cline `synchronizeRuleToggles`，无 nanobot 风格 toggle 持久化
- Stage 13.3 local toggle 分离（L965-1053）：对标 Cline `globalClineRulesToggles` + `localClineRulesToggles` 双层结构，无 nanobot 风格实现

经核查 `context.py` rules 相关方法：

- `_build_rules`（L454-539）：编排器方法，按 7 步顺序加载（global AGENTS.md → workspace AGENTS.md → rules_dir → MODE_TAG → PLAN_MODE → enhancements → extra_sections），其中第 7 步 `extra_sections` 遍历为死代码（默认空 dict 不执行），无 nanobot 风格实现
- `_load_rules_directory`（L541-609）：兼容层方法，含 `task_type.md` 兼容加载 + `synchronize_rule_toggles` 调用 + `load_rules_directory` 调用，无 nanobot 风格实现
- `_build_enhancement_rules`（L611-647）：Charles 独有增强层（tools_section / mcp_section / always_skills / skills_summary），无 nanobot 风格实现

**结论**：Rules 段实现**无 nanobot 实现逻辑残留**，仅 1 处与 Phase 5.1 共享的注释残留。说明 Stage 7.x + 13.3 重构已彻底清除 Rules 段的 nanobot 风格实现逻辑。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**Rules 段实现无类似的实现逻辑残留**，仅 1 处与 Phase 5.1 共享的注释残留 + 1 个死参数（`extra_sections`）。这说明 Rules 段的重构（Stage 7.1 / 7.2 / 7.4 / 13.3）比技能系统更彻底，已完全对标 Cline 实现。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.8.2 frontmatter 解析**：已对齐，无需修复。
- **5.8.3 rule-conditionals**：Charles 比 Cline 更丰富，无需修复。
- **5.8.5 globs 匹配**：两者行为一致（都不评估），无需修复。
- **5.8.6 applyTo 字段**：Charles 已实现，Cline 未实现，无需修复。
- **5.8.8 rule_toggles**：已对齐，无需修复。
- **5.8.10 段落位置**：已对齐，无需修复。

### 5.2 优先级 P1（建议处理）

- **5.8.7 alwaysApply 死字段**：建议移除 `agent_config/rules/AGENTS.md` frontmatter 中的 `alwaysApply: true` 字段。该字段被解析但无任何效果，从 Cursor Rules 模板复制而来，可能误导用户认为有"始终应用"语义。移除不影响功能（无评估器依赖此字段）。

- **5.8.9 rule 输出格式 docstring 修正**：`rules_loader.py` L700 注释"对齐 Cline ## name 格式"不准确——Cline 实际用相对文件路径作为 label，无 `##` 标题。建议修正为"Charles 优化的输出格式：使用文件 stem 作为 markdown `##` 标题，对 LLM 更友好"。

### 5.3 优先级 P2（可选优化）

- **5.8.1 AGENTS.md 位置统一**：当前 workspace AGENTS.md 位于 `agent_config/rules/AGENTS.md`（与其它规则文件混放），global AGENTS.md 位于 `~/.agent/AGENTS.md`。建议未来 major 版本统一为 Cline 风格：workspace AGENTS.md 位于项目根 `./AGENTS.md`，global AGENTS.md 位于 `~/.agents/AGENTS.md`，与 `agent_config/rules/` 分离。当前结构通过 `agents_path` 参数兼容，不影响功能。

- **5.8.4 external-rules**：Charles 不实施 external-rules（`.cursorrules` / `.windsurfrules` 等）属合理偏离。若未来有跨工具规则兼容需求，可参考 Cline `external-rules.ts` 实现。当前无需处理。

- **workflows 子目录**：Charles 当前通过 `excluded_subdirs` 排除 workflows 子目录，不实施 workflow 概念。若未来有 multi-step workflow 自动化需求，可参考 Cline `workflows.ts` 实现独立 toggle 槽。当前无需处理。

- **task_type 兼容层移除**：`context.py` L572-582 的 `task_type.md` 兼容加载层属历史包袱，建议在 major 版本移除，统一通过 frontmatter `mode` 字段过滤。

### 5.4 优先级 P3（文档修正）

- **计划文件 P5.8 对比表修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L1952-1955：
  - 5.8.3：将"Charles 缺失"改为"**Charles 增强**"（Charles 实现 4 个评估器，Cline 仅实现 `paths`）
  - 5.8.5：将"Charles 缺失"改为"**两者一致**"（都不评估 `globs`，Cursor Rules 字段）
  - 5.8.6：将"Charles 缺失"改为"**Charles 独有**"（Charles 实现 applyTo 评估，Cline 未实现）
  - 5.8.7：将"已对齐"改为"**已对齐（都不评估）**"（避免误导为"都实现"）
  - 5.8.9：将"Cline watcher.name"改为"Cline 相对文件路径"（Cline 用 `ruleFilePathRelative`，非 watcher.name）

---

## 六、验证方法

### 6.1 frontmatter 解析对齐验证

```powershell
# 验证 Charles frontmatter 正则与 Cline 一致
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern '\^---\\r\?\\n'
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\frontmatter.ts" -Pattern '\^---\\r\?\\n'
# 两者均应输出同一正则：^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$
```

### 6.2 conditional 评估器对比验证

```powershell
# 验证 Cline 仅注册 paths 评估器
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\rule-conditionals.ts" -Pattern "conditionalEvaluators"
# 预期: const conditionalEvaluators = { paths: evaluatePathsConditional }

# 验证 Charles 注册 4 个评估器
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern 'if "(enabled|applyTo|mode|paths)" in frontmatter'
# 预期: 4 行匹配
```

### 6.3 alwaysApply 死字段验证

```powershell
# 验证 Charles 不评估 alwaysApply
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "alwaysApply"
# 预期: 0 行匹配（rules_loader.py 完全不引用 alwaysApply）

# 验证 AGENTS.md frontmatter 含 alwaysApply 字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "alwaysApply"
# 预期: 1 行匹配（frontmatter 中 alwaysApply: true）
```

### 6.4 nanobot 残留验证

```powershell
# 在 rules_loader.py 中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无输出

# 在 context.py rules 相关方法中搜索 nanobot（应 1 处注释残留，与 Phase 5.1 同一处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: L275 docstring 1 处
```

### 6.5 toggle 持久化对齐验证

```powershell
# 验证 Charles global + local toggle 双层结构
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "global|local"
# 预期: 多行匹配（_default_toggles_store_path / _local_toggles_store_path / load_merged_toggles）

# 验证 Cline global + local toggle 双层结构
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\cline-rules.ts" -Pattern "global|local"
# 预期: globalClineRulesToggles + localClineRulesToggles
```

### 6.6 excluded_subdirs 对齐验证

```powershell
# 验证 Charles 排除 workflows/hooks/skills
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern 'excluded_subdirs\s*=\s*\["workflows"'
# 预期: 1 行匹配（L554）

# 验证 Cline 排除 .clinerules/{workflows,hooks,skills}
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\cline-rules.ts" -Pattern "workflows|hooks|skills"
# 预期: L24-26 三行匹配（[".clinerules", "workflows"] / [".clinerules", "hooks"] / [".clinerules", "skills"]）
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.8.1 rules 目录 | 路径不同 | **路径不同**（合理偏离） | Cline `.clinerules/` + `~/Documents/Cline/Rules/`；Charles `agent_config/rules/` + `~/.agent/AGENTS.md` |
| 5.8.2 frontmatter 解析 | 已对齐 | **已对齐** | 正则、BOM 剥离、fail-open 策略完全一致 |
| 5.8.3 rule-conditionals | Charles 缺失 | **Charles 增强**（计划表错误） | Charles 实现 4 个评估器（enabled/applyTo/mode/paths），Cline 仅实现 paths |
| 5.8.4 external-rules | Charles 不实施 | **Charles 不实施**（合理偏离） | Charles 无跨工具规则兼容需求 |
| 5.8.5 globs 匹配 | Charles 缺失 | **两者一致**（计划表错误） | 两者均不评估 globs，Cursor Rules 字段 |
| 5.8.6 applyTo 字段 | Charles 缺失 | **Charles 独有**（计划表错误） | Charles 实现 applyTo 评估，Cline 未实现 |
| 5.8.7 alwaysApply 字段 | 已对齐 | **已对齐（都不评估）**（误导性描述） | 两者均解析但不评估 alwaysApply，Charles AGENTS.md 中该字段为死字段 |
| 5.8.8 rule_toggles | 已对齐 | **已对齐** | Stage 13.3 完成 global + local 双层对齐 |
| 5.8.9 rule name | Cline watcher.name vs Charles 文件 stem | **Cline 相对路径 vs Charles 文件 stem**（计划表不准确） | Cline 用 `ruleFilePathRelative`（相对文件路径），非 watcher.name；Charles 用 `path.stem` + `##` 标题 |
| 5.8.10 段落位置 | 已对齐 | **已对齐** | 两者均位于 `<env>` 之后、metadata 之前 |

**计划表标注总结**：10 项中 4 项标注错误（5.8.3 / 5.8.5 / 5.8.6 / 5.8.9），1 项误导性描述（5.8.7），3 项确认对齐（5.8.2 / 5.8.8 / 5.8.10），2 项合理偏离（5.8.1 / 5.8.4）。计划表 P5.8 整体偏保守且对 Charles 实际实现存在系统性误判，未反映 Stage 7.x + 13.3 重构成果，且将 Charles 独有增强误标为"缺失"。
