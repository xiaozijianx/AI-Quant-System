# Phase 7.13 Cline Rules / Frontmatter / Workflows 对比

> 对比范围：Cline `apps/vscode/src/core/context/instructions/user-instructions/` 下 6 个文件（cline-rules.ts / frontmatter.ts / rule-conditionals.ts / rule-helpers.ts / external-rules.ts / workflows.ts）共 836 行 TypeScript，与 Charles `agent/rules_loader.py`（1053 行）+ `agent/context.py` rules 相关方法（`_build_rules` + `_load_rules_directory` + `_build_enhancement_rules`，约 200 行）+ `agent_config/rules/` 目录的整体"规则加载 / frontmatter 解析 / 条件评估 / workflows 处理"链路逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段为整体对比报告，与 Phase 6 的 P5.8（Cline Rules 段细节对比，10 项）/ P6.1（AGENTS.md frontmatter 对比，8 项）/ P6.6（AGENTS.md 条件注入对比，8 项）形成交叉关联：细节已在上述三阶段完成逐项核查，本阶段聚焦整体维度汇总与差异收敛，不重复细节核查过程。
>
> Cline 源码：
> - `apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts` L1-34（`refreshClineRulesToggles`：global + local 双层 toggle 同步入口，排除 `.clinerules/{workflows,hooks,skills}` 子目录）
> - `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts` L1-59（`parseYamlFrontmatter` + `FrontmatterParseResult` 类型，stripUtf8Bom + 正则 + JSON_SCHEMA + fail-open）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts` L1-153（`evaluateRuleConditionals` + `conditionalEvaluators` 注册表 + `extractPathLikeStrings` 启发式路径提取）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L1-467（`synchronizeRuleToggles` + `getRuleFilesTotalContentWithMetadata` + `createRuleFile` + `deleteRuleFile` + `combineRuleToggles`）
> - `apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts` L1-49（`refreshExternalRulesToggles`：cursor/windsurf/agents 三类外部规则扫描）
> - `apps/vscode/src/core/context/instructions/user-instructions/workflows.ts` L1-32（`refreshWorkflowToggles`：独立 workflows toggle 槽同步）
>
> Charles 源码：
> - `agent/rules_loader.py` L1-1053（`parse_yaml_frontmatter` + `evaluate_rule_conditionals` + `load_rules_directory` + `format_rules_content` + `synchronize_rule_toggles` + Stage 13.3 local toggle 分离 + Stage 7.4 mtime 缓存）
> - `agent/context.py` L454-609（`SystemPromptBuilder._build_rules` 编排器 + `_load_rules_directory` 兼容层）
> - `agent_config/rules/` 目录（含 AGENTS.md / general.md / plan-mode-rules.md / research.md / trading.md 5 个规则文件）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的"规则加载 / frontmatter 解析 / 条件评估 / workflows 处理"整体链路。**核心结论：Charles 已通过 Stage 7.1 / 7.2 / 7.4 / 13.3 四个阶段重构完成对齐，整体链路在 frontmatter 解析、paths 条件评估、toggle 持久化、excluded_subdirs 过滤 4 个核心维度达到高一致性；且 Charles 在 conditional 评估维度比 Cline 更丰富（多出 `applyTo` agent 模式 / `mode` 业务模式 / `enabled` 开关三类评估器）；Charles 不实施 external-rules 与 workflows 独立 toggle 槽，属合理偏离（量化场景无跨工具规则兼容与 multi-step workflow 自动化需求）。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P7.13（L2829-2837）的对比表存在 **3 处事实错误**，与 P5.8 / P6.1 / P6.6 的修正同源（P7.13 直接复用了 P5.8 的错误前提）：

1. **7.13.3 标注"rule-conditionals — Charles 缺失"** — **严重事实错误**：Charles 实际实现了 4 个 conditional 评估器（`enabled` + `applyTo` + `mode` + `paths`，rules_loader.py L433-481），**比 Cline 多出 3 个**。Cline `conditionalEvaluators` 注册表（rule-conditionals.ts L74-76）仅注册 `paths` 一个评估器。Charles 不是"缺失"而是"超越"——是 Cline 的严格超集。

2. **7.13.6 标注"globs 匹配 — Charles 缺失"** — **事实错误**：Cline 也**未实现 `globs` 字段评估**。Cline `conditionalEvaluators` 对象（rule-conditionals.ts L74-76）仅注册 `paths`，`globs` 作为 unknown key 被 `continue` 忽略（L89-90）。`globs` 是 Cursor Rules 字段，Cline 解析但**不评估**。Charles 同样解析但不评估。两者行为一致，非"Charles 缺失"。

3. **7.13.7 标注"applyTo 字段 — Charles 缺失"** — **严重事实错误**：Charles 实际实现 `_evaluate_apply_to_conditional`（rules_loader.py L369-400），基于 `context.agent_mode` 评估 `applyTo: [plan, act]` 字段。Cline **未实现** `applyTo` 评估——`applyTo` 在 Cline 中仅作为 unknown key 被忽略。Charles 不是"缺失"而是"独有增强"。

### 核心结论

1. **整体链路高一致性**：Charles 的"目录扫描 → frontmatter 解析 → 条件评估 → toggle 过滤 → 输出格式化"五步链路与 Cline 在架构层面完全对齐，仅在路径常量、存储介质、输出格式等技术细节上存在差异。

2. **frontmatter 解析完全对齐**：正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` 逐字符相同，stripUtf8Bom + fail-open 策略一致，YAML schema 存在差异（Cline 用 JSON_SCHEMA 严格、Charles 用 safe_load 宽松）但对当前 JSON 兼容 frontmatter 值无影响。

3. **conditional 评估 Charles 是 Cline 严格超集**：Cline 仅评估 `paths`；Charles 评估 `enabled` / `applyTo` / `mode` / `paths` 四字段。Charles 多出 3 个评估器是业务场景驱动的合理扩展（agent 模式过滤 + 业务模式过滤 + 显式禁用开关）。

4. **toggle 持久化双层结构对齐**（Stage 13.3 完成）：global + local 双层 toggle 结构一致，存储介质不同（Cline 用 stateManager 的 `globalClineRulesToggles` / `localClineRulesToggles`；Charles 用 `rule_toggles.json` / `sessions/<id>/rule_toggles.local.json` JSON 文件）。

5. **excluded_subdirs 已对齐**（Stage 7.4 完成）：Cline 通过 `excludedPaths: [[".clinerules", "workflows"], [".clinerules", "hooks"], [".clinerules", "skills"]]` 排除；Charles 通过 `excluded_subdirs=["workflows", "hooks", "skills"]` 排除，行为一致。

6. **external-rules 合理不实施**：Charles 不扫描 `.cursorrules` / `.windsurfrules` / `.cursor/rules/` 等外部规则文件格式。Charles 专注 Python 量化投研场景，无跨工具规则兼容需求。

7. **workflows 子目录处理差异**：Cline 把 `.clinerules/workflows/` 作为独立 toggle 槽加载（`refreshWorkflowToggles`）；Charles 通过 `excluded_subdirs` 直接排除，不作为规则加载。Charles 不实施 workflow 概念，但保留目录结构兼容性。

8. **rule 输出格式差异**：Cline 用 `${ruleFilePathRelative}\n${body}` 扁平格式（相对文件路径作为 label，无 markdown 标题）；Charles 用 `## {file_stem}\n\n{body}` 层级格式（文件 stem 作为 markdown `##` 标题）+ 顶部 `# Rules` 总标题。Charles 格式对 LLM 更友好。

9. **Charles 独有增强**：Stage 7.4 mtime 缓存（模块级 `_RULES_MTIME_CACHE`，减少无变更文件的重复 I/O 与 frontmatter 解析开销）+ task_type 兼容层（`rules/<task_type>.md` 兼容加载入口，向后兼容历史接口）+ Stage 13.3 local toggle 分离（per-session 独立 toggle 文件）。

10. **nanobot 残留**：rules_loader.py **0 处残留**（注释 0 + 实现逻辑 0）；context.py rules 相关代码 **1 处注释残留 + 0 处实现逻辑残留**（L275 `extra_sections` docstring，与 P5.1 / P5.8 / P6.1 / P6.6 共享同一处）。Stage 7.x + 13.3 重构已彻底清除 Rules 段的 nanobot 风格实现逻辑。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| frontmatter 解析 | 高 | 正则、BOM 剥离、fail-open 策略完全一致；YAML schema 差异对当前值无影响 |
| 条件评估（paths） | 高 | glob 语义对齐（picomatch vs wcmatch），fail-closed 策略一致 |
| 条件评估（applyTo/mode/enabled） | Charles 独有 | Charles 实现 3 个扩展评估器，Cline 无对应概念 |
| toggle 持久化 | 高 | global + local 双层结构对齐（Stage 13.3 完成） |
| excluded_subdirs | 高 | workflows/hooks/skills 三类子目录排除对齐（Stage 7.4 完成） |
| external-rules | 低（合理偏离） | Charles 不实施跨工具规则兼容，量化场景无需求 |
| workflows 独立 toggle 槽 | 低（合理偏离） | Charles 直接排除 workflows 子目录，不实施 workflow 概念 |
| rule 输出格式 | 中 | Cline 扁平格式 vs Charles 层级 markdown，对齐差距合理 |
| mtime 缓存 | Charles 增强 | Cline 用 fs.watch 事件驱动，Charles 用 mtime 轮询（Web 请求-响应模型适配） |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.13.1 | cline-rules 加载 | `refreshClineRulesToggles`（cline-rules.ts L7-34）：global + local 双层 toggle 同步，workspace 路径 `.clinerules/`，排除 `.clinerules/{workflows,hooks,skills}` | `synchronize_rule_toggles` + `load_rules_directory`（rules_loader.py L568-683 + L889-957）：global + local 双层 toggle 同步，workspace 路径 `agent_config/rules/`，`excluded_subdirs=["workflows","hooks","skills"]` | 高 | 路径常量不同（`.clinerules/` vs `agent_config/rules/`），核心行为对齐。详细对比见 P5.8.1 / P5.8.8 |
| 7.13.2 | frontmatter 解析 | `parseYamlFrontmatter`（frontmatter.ts L38-59）：stripUtf8Bom + 正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` + `yaml.load(JSON_SCHEMA)` + fail-open | `parse_yaml_frontmatter`（rules_loader.py L131-181）：stripUtf8Bom + 同正则 + `yaml.safe_load` + fail-open + 顶层 dict 校验 | 高 | 正则**逐字符相同**，fail-open 策略一致。Charles 多出顶层 dict 校验（更健壮）。详细对比见 P5.8.2 / P6.1.7 |
| 7.13.3 | rule-conditionals | `conditionalEvaluators = { paths: evaluatePathsConditional }`（rule-conditionals.ts L74-76），**仅评估 `paths`**，其他字段作为 unknown key 被忽略（L89-90） | `evaluate_rule_conditionals`（rules_loader.py L433-481），评估 `enabled` + `applyTo` + `mode` + `paths` 四字段 | Charles 增强 | 计划表标注"Charles 缺失"**严重错误**。Charles 是 Cline 严格超集，多出 3 个评估器。详细对比见 P5.8.3 / P6.6.2 / P6.6.3 / P6.6.5 |
| 7.13.4 | external-rules | `refreshExternalRulesToggles`（external-rules.ts L10-49）：扫描 `.cursorrules` / `.cursor/rules/*.mdc` / `.windsurfrules` / `AGENTS.md` 4 类外部规则 | 无（不实施） | 低（合理偏离） | Charles 不扫描 Cursor / Windsurf / AGENTS.md 外部规则文件格式。合理偏离：量化场景无跨工具规则兼容需求 |
| 7.13.5 | workflows | `refreshWorkflowToggles`（workflows.ts L10-32）：`.clinerules/workflows/` 作为独立 toggle 槽（`globalWorkflowToggles` + `workflowToggles`）加载 | 无（直接通过 `excluded_subdirs` 排除，不加载） | 低（合理偏离） | Cline 把 workflows 作为独立 toggle 槽加载；Charles 直接排除不处理。Charles 不实施 workflow 概念 |
| 7.13.6 | globs 匹配 | **未实现**：`globs` 作为 unknown key 被忽略（rule-conditionals.ts L89-90），Cline AGENTS.md 示例 `globs: "*.ts,*.tsx,..."` 字段是**死字段** | **未实现**：`evaluate_rule_conditionals` 不识别 `globs`（仅识别 `paths`），Charles AGENTS.md 未使用 `globs` | 高（都不评估） | 计划表标注"Charles 缺失"**事实错误**。两者行为一致：`globs` 是 Cursor Rules 字段，Cline 和 Charles 均解析但不评估。详细对比见 P5.8.5 / P6.1.3 / P6.6.4 |
| 7.13.7 | applyTo 字段 | **未实现**：`applyTo` 作为 unknown key 被忽略（rule-conditionals.ts L89-90），Cline AGENTS.md 示例**无此字段** | **已实现**：`_evaluate_apply_to_conditional`（rules_loader.py L369-400），基于 `context.agent_mode` 评估，省略=无条件通过，空数组=fail-closed，命中即激活 | Charles 独有 | 计划表标注"Charles 缺失"**严重错误**。Charles 实现 applyTo 评估，Cline 未实现。详细对比见 P5.8.6 / P6.1.4 / P6.6.2 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P7.13 三处事实错误（7.13.3 + 7.13.6 + 7.13.7）

P7.13 对比表（L2829-2837）直接复用了 P5.8 的错误前提，将 Charles 实际已实现或比 Cline 更丰富的功能标注为"Charles 缺失"。错误根因与 P5.8 / P6.1 / P6.6 完全同源，本阶段不重复核查源码细节（详见 P5.8.3 / P5.8.5 / P5.8.6 / P6.1.3 / P6.1.4 / P6.6.2 / P6.6.4 的源码对比）。

**核查结论汇总**：
- **7.13.3 rule-conditionals**：Cline `conditionalEvaluators` 注册表（rule-conditionals.ts L74-76）仅注册 `paths` 一个评估器，`applyTo` / `mode` / `enabled` / `alwaysApply` / `globs` 等 key 均作为 unknown 走 L89-90 `continue` 分支被忽略。Charles `evaluate_rule_conditionals`（rules_loader.py L433-481）评估 4 个字段，**比 Cline 多 3 个**。
- **7.13.6 globs 匹配**：Cline 和 Charles 均不评估 `globs`，两者行为完全一致。`globs` 是 Cursor Rules 字段。
- **7.13.7 applyTo 字段**：Charles 实现 `_evaluate_apply_to_conditional`（rules_loader.py L369-400），Cline 未实现。Charles AGENTS.md 中 `applyTo: [act, plan]` 字段实际被评估并激活，Cline 中相同字段被忽略。

### 3.2 整体链路对比（与 P5.8 / P6.1 / P6.6 的差异收敛）

本节聚焦整体链路维度的差异收敛，不重复细节核查过程：

**链路对齐矩阵**：

| 链路节点 | Cline 实现 | Charles 实现 | 对齐状态 |
|---------|-----------|-------------|---------|
| 1. 目录扫描 | `readDirectoryRecursive`（rule-helpers.ts L13-35），`.clinerules/` + 排除 workflows/hooks/skills | `Path.rglob("*.md")` + `_is_path_in_excluded_subdir`（rules_loader.py L494-521 + L602-606），`agent_config/rules/` + 排除 workflows/hooks/skills | 高（Stage 7.4 完成对齐） |
| 2. frontmatter 解析 | `parseYamlFrontmatter`（frontmatter.ts L38-59），正则 + JSON_SCHEMA + fail-open | `parse_yaml_frontmatter`（rules_loader.py L131-181），同正则 + safe_load + fail-open + 顶层 dict 校验 | 高（正则逐字符相同） |
| 3. 条件评估 | `evaluateRuleConditionals`（rule-conditionals.ts L78-103），仅 `paths` 评估器 | `evaluate_rule_conditionals`（rules_loader.py L433-481），4 字段评估器 | Charles 增强 |
| 4. toggle 过滤 | `toggles[ruleFilePath] === false` 跳过（rule-helpers.ts L220-222），key 为绝对路径 | `toggles.get(toggle_key, True) is False` 跳过（rules_loader.py L613-622），key 为 POSIX 相对路径 | 高（Stage 13.3 完成对齐） |
| 5. 输出格式化 | `${ruleFilePathRelative}\n${body}` 扁平拼接（rule-helpers.ts L246） | `## {file_stem}\n\n{body}` + 顶部 `# Rules` 层级（rules_loader.py L716-722） | 中（设计差异） |
| 6. toggle 持久化 | `stateManager` global + workspace 双层（cline-rules.ts L15-28） | `rule_toggles.json` + `sessions/<id>/rule_toggles.local.json` 双层（rules_loader.py L827-1053） | 高（Stage 13.3 完成对齐） |
| 7. mtime 缓存 | `UnifiedConfigFileWatcher` fs.watch + 75ms debounce 事件驱动 | `_RULES_MTIME_CACHE` 模块级 mtime 轮询（rules_loader.py L524-556） | Charles 增强（Web 请求-响应模型适配） |

**与 Phase 6 的交叉关联**：
- P5.8 已完成 10 项细节对比（rules 目录 / frontmatter 解析 / rule-conditionals / external-rules / globs / applyTo / alwaysApply / rule_toggles / rule name / 段落位置）
- P6.1 已完成 8 项 AGENTS.md frontmatter 对比（frontmatter 存在 / description / globs / applyTo / alwaysApply / 分隔符 / 解析器 / 移除）
- P6.6 已完成 8 项 AGENTS.md 条件注入对比（alwaysApply 注入 / applyTo 字段 / 按 mode 注入 / globs 匹配 / enabled 注入 / paths 评估 / 加载路径 / toggle 控制）

**本阶段（P7.13）增量贡献**：
- 汇总整体链路矩阵（7 个节点），避免读者跨阶段拼凑
- 修正计划表 3 处事实错误（与 P5.8 / P6.1 / P6.6 同源）
- 提供整体一致性评估表（9 个维度）
- 整合 nanobot 残留专项检查（区分注释残留与实现逻辑残留）

### 3.3 external-rules 合理不实施（7.13.4）

Cline `external-rules.ts` L10-49 实现 `refreshExternalRulesToggles`，扫描 4 类外部规则文件：

| 外部规则 | Cline 路径 | 用途 |
|---------|-----------|------|
| Cursor rules | `.cursorrules`（单文件） + `.cursor/rules/*.mdc`（目录） | Cursor IDE 规则兼容 |
| Windsurf rules | `.windsurfrules`（单文件） | Windsurf IDE 规则兼容 |
| AGENTS.md | `AGENTS.md`（项目根） | 跨工具标准 AGENTS 协议 |

**Charles 不实施原因**：
1. **量化场景无跨工具规则兼容需求**：Charles 专注 Python 量化投研，不与 Cursor / Windsurf 等 IDE 共存
2. **AGENTS.md 已通过 rules_dir 内置**：Charles 的 `agent_config/rules/AGENTS.md` 与其它规则文件同目录，通过 `load_rules_directory` 统一扫描加载，无需独立 external-rules 通道
3. **架构简化**：避免维护 4 类外部规则文件的扫描 + toggle 同步逻辑

**评估**：合理偏离，非对齐缺口。Charles 的规则加载链路更简洁，专注自身场景。

### 3.4 workflows 子目录处理差异（7.13.5）

Cline 和 Charles 对 workflows 子目录的处理策略截然不同：

**Cline 方案**：workflows 作为**独立 toggle 槽**加载
- `workflows.ts` L10-32：`refreshWorkflowToggles` 单独同步 workflows toggle
- `cline-rules.ts` L23-27：在 cline-rules toggle 同步时**排除** `.clinerules/workflows`，避免双重加载
- workflows 通过 `globalWorkflowToggles`（global）+ `workflowToggles`（workspace）双层 toggle 独立管理
- workflow 文件作为独立的"工作流"概念加载，与普通 rules 分离，用于 multi-step workflow 自动化场景

**Charles 方案**：workflows 直接**排除**，不作为规则加载
- `context.py` L554：`excluded_subdirs = ["workflows", "hooks", "skills"]`
- workflows 子目录的 `.md` 文件**不被加载**到 Rules 段
- Charles 不实施"工作流"概念，仅把 workflows 作为排除目录

**差异影响**：
- Cline：workflows 是一类特殊规则，有独立 UI toggle 和加载通道，支持 multi-step workflow 自动化
- Charles：workflows 是被忽略的子目录，无任何处理

**评估**：Charles 不实施 workflows 概念属合理偏离——Charles 专注 Python 量化投研，无 Cline 那样的 multi-step workflow 自动化需求。但 `excluded_subdirs` 列表中包含 `"workflows"` 说明 Charles 仍保留目录结构兼容性（用户可在 `agent_config/rules/workflows/` 放置文件，但不会被加载），避免与未来可能的 workflow 实现冲突。

### 3.5 Charles 独有增强：mtime 缓存与 task_type 兼容层

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

### 3.6 rule 输出格式差异

Cline 和 Charles 对激活规则的输出格式不同（与 P5.8.9 同源，本阶段整体视角再确认）：

**Cline 格式**（rule-helpers.ts L246）：
```typescript
return { contentPart: `${ruleFilePathRelative}\n${body.trim()}`, activatedRule }
```
输出示例（扁平结构，相对路径作为 label，无 markdown 标题）：
```
.clinerules/general.md
This file is the secret sauce...

.clinerules/coding.md
Use TypeScript for all new files...
```

**Charles 格式**（rules_loader.py L716-722）：
```python
name = r.path.stem
parts.append(f"## {name}\n\n{body}")
return "# Rules\n\n" + "\n\n".join(parts)
```
输出示例（层级 markdown 结构，文件 stem 作为 `##` 标题，顶部统一 `# Rules`）：
```
# Rules

## general

This file is the secret sauce...

## coding

Use TypeScript for all new files...
```

**差异分析**：
- Cline：用**相对文件路径**作为 label，无 markdown 标题层级，LLM 看到的是"路径 + 正文"扁平结构
- Charles：用**文件 stem**作为 markdown `##` 二级标题，顶部统一加 `# Rules` 一级标题，LLM 看到的是层级化 markdown 结构
- Charles 注释（rules_loader.py L700）声称"对齐 Cline ## name 格式"，但实际 Cline 并不使用 `##` 标题

**评估**：Charles 的 markdown 层级结构对 LLM 更友好（明确的标题边界），但与 Cline 输出格式不字节一致。属合理设计差异，非对齐缺口。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 Rules 段相关文件检查 nanobot 风格残留：
- `agent/rules_loader.py`（全文 1053 行，含 `parse_yaml_frontmatter` + `evaluate_rule_conditionals` + `load_rules_directory` + `format_rules_content` + `synchronize_rule_toggles` + Stage 13.3 local toggle + Stage 7.4 mtime 缓存）
- `agent/context.py` rules 相关方法（`_build_rules` L454-539 + `_load_rules_directory` L541-609 + `_build_enhancement_rules` L611-647）

### 4.2 检查方法

使用 Grep 工具对 `agent/rules_loader.py` 和 `agent/context.py` 进行 case-insensitive 搜索 `nanobot`，并区分：
- **注释残留**：仅出现在 docstring / 注释中，不影响运行逻辑
- **实现逻辑残留**：出现在实际代码逻辑中，影响运行行为

### 4.3 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/rules_loader.py` | 0 | 0 | 无残留。所有逻辑均对标 Cline frontmatter.ts / rule-conditionals.ts / rule-helpers.ts，无 nanobot 风格实现 |
| `agent/context.py`（rules 部分） | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`（与 P5.1 / P5.8 / P6.1 / P6.6 同一处） |

### 4.4 残留详情

#### 4.4.1 注释残留（1 处，与 P5.1 / P5.8 / P6.1 / P6.6 同一处）

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

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。不影响运行逻辑。此残留已在 P5.1 / P5.8 / P6.1 / P6.6 报告中多次记录，本阶段不重复计入 Rules 段独立残留，仅作整体确认。

#### 4.4.2 实现逻辑残留（0 处）

经核查 `rules_loader.py` 全部 1053 行：

- `parse_yaml_frontmatter`（L131-181）：完全对标 Cline `parseYamlFrontmatter`，正则一致，fail-open 策略一致，无 nanobot 风格实现
- `evaluate_rule_conditionals`（L433-481）：4 个评估器（enabled / applyTo / mode / paths）均为 Charles 主动实现的对齐增强，无 nanobot 风格条件评估
- `load_rules_directory`（L568-683）：对标 Cline `getRuleFilesTotalContentWithMetadata`，无 nanobot 风格目录扫描
- `format_rules_content`（L686-722）：使用 `## {stem}` markdown 标题格式，无 nanobot 风格输出
- `synchronize_rule_toggles`（L889-957）：对标 Cline `synchronizeRuleToggles`，无 nanobot 风格 toggle 持久化
- Stage 7.4 mtime 缓存（L524-556）：Charles 独有性能优化，对标 Cline `UnifiedConfigFileWatcher` 增量更新语义
- Stage 13.3 local toggle 分离（L965-1053）：对标 Cline `globalClineRulesToggles` + `localClineRulesToggles` 双层结构

经核查 `context.py` rules 相关方法：

- `_build_rules`（L454-539）：编排器方法，按 7 步顺序加载（global AGENTS.md → workspace AGENTS.md → rules_dir → MODE_TAG → PLAN_MODE → enhancements → extra_sections），其中第 7 步 `extra_sections` 遍历为死代码（默认空 dict 不执行），无 nanobot 风格实现
- `_load_rules_directory`（L541-609）：兼容层方法，含 `task_type.md` 兼容加载 + `synchronize_rule_toggles` 调用 + `load_rules_directory` 调用，无 nanobot 风格实现
- `_build_enhancement_rules`（L611-647）：Charles 独有增强层（tools_section / mcp_section / always_skills / skills_summary），无 nanobot 风格实现

**结论**：Rules 段实现**无 nanobot 实现逻辑残留**，仅 1 处与 P5.1 共享的注释残留。说明 Stage 7.x + 13.3 重构已彻底清除 Rules 段的 nanobot 风格实现逻辑。

### 4.5 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**Rules 段实现无类似的实现逻辑残留**，仅 1 处与 P5.1 共享的注释残留 + 1 个死参数（`extra_sections`）。这说明 Rules 段的重构（Stage 7.1 / 7.2 / 7.4 / 13.3）比技能系统更彻底，已完全对标 Cline 实现。

### 4.6 范围外残留说明

以下文件的 nanobot 残留**超出 P7.13 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20（已审计） |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20（已审计） |
| `agent/skills/skill_tool.py` L18 | 注释残留 | "nanobot 子 agent 隔离执行"对比说明 | P4.x |
| `agent/providers/qwen.py` 多处 | 注释残留 | 对标 nanobot openai_compat_provider | P1.x |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |
| `agent/skills/__init__.py` L2/L23 | 注释残留 | 对标 nanobot SkillsLoader | P4.x |
| `agent/tools/__init__.py` L2 | 注释残留 | 对标 nanobot agent/tools | P3.x |

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **7.13.1 cline-rules 加载**：已对齐，无需修复。
- **7.13.2 frontmatter 解析**：已对齐，无需修复。
- **7.13.3 rule-conditionals**：Charles 比 Cline 更丰富，无需修复。
- **7.13.6 globs 匹配**：两者行为一致（都不评估），无需修复。
- **7.13.7 applyTo 字段**：Charles 已实现，Cline 未实现，无需修复。

### 5.2 优先级 P1（建议处理）

- **rule 输出格式 docstring 修正**：`rules_loader.py` L700 注释"对齐 Cline ## name 格式"不准确——Cline 实际用相对文件路径作为 label，无 `##` 标题。建议修正为"Charles 优化的输出格式：使用文件 stem 作为 markdown `##` 标题，对 LLM 更友好"。

- **alwaysApply 死字段**（与 P5.8 / P6.1 / P6.6 同源）：建议移除 `agent_config/rules/AGENTS.md` frontmatter 中的 `alwaysApply: true` 字段。该字段被解析但无任何效果，从 Cursor Rules 模板复制而来，可能误导用户认为有"始终应用"语义。移除不影响功能（无评估器依赖此字段）。

### 5.3 优先级 P2（可选优化）

- **external-rules**（7.13.4）：Charles 不实施 external-rules（`.cursorrules` / `.windsurfrules` 等）属合理偏离。若未来有跨工具规则兼容需求，可参考 Cline `external-rules.ts` 实现。当前无需处理。

- **workflows 独立 toggle 槽**（7.13.5）：Charles 当前通过 `excluded_subdirs` 排除 workflows 子目录，不实施 workflow 概念。若未来有 multi-step workflow 自动化需求，可参考 Cline `workflows.ts` 实现独立 toggle 槽。当前无需处理。

- **task_type 兼容层移除**：`context.py` L572-582 的 `task_type.md` 兼容加载层属历史包袱，建议在 major 版本移除，统一通过 frontmatter `mode` 字段过滤。

- **AGENTS.md 位置统一**（与 P5.8.1 同源）：当前 workspace AGENTS.md 位于 `agent_config/rules/AGENTS.md`（与其它规则文件混放），global AGENTS.md 位于 `~/.agent/AGENTS.md`。建议未来 major 版本统一为 Cline 风格：workspace AGENTS.md 位于项目根 `./AGENTS.md`，global AGENTS.md 位于 `~/.agents/AGENTS.md`，与 `agent_config/rules/` 分离。当前结构通过 `agents_path` 参数兼容，不影响功能。

### 5.4 优先级 P3（文档修正）

- **计划文件 P7.13 对比表修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2829-2837：
  - 7.13.3：将"Charles 缺失"改为"**Charles 增强**"（Charles 实现 4 个评估器，Cline 仅实现 `paths`）
  - 7.13.6：将"Charles 缺失"改为"**两者一致**"（都不评估 `globs`，Cursor Rules 字段）
  - 7.13.7：将"Charles 缺失"改为"**Charles 独有**"（Charles 实现 applyTo 评估，Cline 未实现）

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

### 6.3 excluded_subdirs 对齐验证

```powershell
# 验证 Charles 排除 workflows/hooks/skills
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern 'excluded_subdirs\s*=\s*\["workflows"'
# 预期: 1 行匹配（L554）

# 验证 Cline 排除 .clinerules/{workflows,hooks,skills}
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\cline-rules.ts" -Pattern "workflows|hooks|skills"
# 预期: L24-26 三行匹配
```

### 6.4 toggle 持久化对齐验证

```powershell
# 验证 Charles global + local toggle 双层结构
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "global|local"
# 预期: 多行匹配（_default_toggles_store_path / _local_toggles_store_path / load_merged_toggles）

# 验证 Cline global + local toggle 双层结构
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\cline-rules.ts" -Pattern "global|local"
# 预期: globalClineRulesToggles + localClineRulesToggles
```

### 6.5 nanobot 残留验证

```powershell
# 在 rules_loader.py 中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无输出

# 在 context.py rules 相关方法中搜索 nanobot（应 1 处注释残留，与 P5.1 / P5.8 / P6.1 / P6.6 同一处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: L275 docstring 1 处
```

### 6.6 workflows 子目录处理差异验证

```powershell
# 验证 Charles 直接排除 workflows
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern '"workflows"'
# 预期: L554 excluded_subdirs 列表中包含 "workflows"

# 验证 Cline workflows 独立 toggle 槽
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\context\instructions\user-instructions\workflows.ts" -Pattern "WorkflowToggles"
# 预期: refreshWorkflowToggles + globalWorkflowToggles + workflowToggles
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 7.13.1 cline-rules 加载 | 已对齐 | **已对齐** | 路径常量不同，核心行为对齐。详见 P5.8.1 / P5.8.8 |
| 7.13.2 frontmatter 解析 | 已对齐 | **已对齐** | 正则、BOM 剥离、fail-open 策略完全一致。详见 P5.8.2 / P6.1.7 |
| 7.13.3 rule-conditionals | Charles 缺失 | **Charles 增强**（计划表错误） | Charles 实现 4 个评估器（enabled/applyTo/mode/paths），Cline 仅实现 paths。详见 P5.8.3 / P6.6.2 / P6.6.3 / P6.6.5 |
| 7.13.4 external-rules | Charles 不实施 | **Charles 不实施**（合理偏离） | Charles 无跨工具规则兼容需求 |
| 7.13.5 workflows | Charles 不实施 | **Charles 不实施**（合理偏离） | Cline 把 workflows 作为独立 toggle 槽加载；Charles 直接排除不处理 |
| 7.13.6 globs 匹配 | Charles 缺失 | **两者一致**（计划表错误） | 两者均不评估 globs，Cursor Rules 字段。详见 P5.8.5 / P6.1.3 / P6.6.4 |
| 7.13.7 applyTo 字段 | Charles 缺失 | **Charles 独有**（计划表错误） | Charles 实现 applyTo 评估，Cline 未实现。详见 P5.8.6 / P6.1.4 / P6.6.2 |

**计划表标注总结**：7 项中 3 项标注错误（7.13.3 / 7.13.6 / 7.13.7，与 P5.8 / P6.1 / P6.6 同源），2 项确认对齐（7.13.1 / 7.13.2），2 项合理偏离（7.13.4 / 7.13.5）。计划表 P7.13 整体偏保守且对 Charles 实际实现存在系统性误判，未反映 Stage 7.x + 13.3 重构成果，且将 Charles 独有增强误标为"缺失"。

---

## 八、附录：与 Phase 6 交叉关联对照表

| Phase 6 子阶段 | 对比维度 | 与 P7.13 的关系 | P7.13 增量贡献 |
|---------------|---------|---------------|--------------|
| P5.8 Cline Rules 段对比 | 10 项细节（rules 目录 / frontmatter / rule-conditionals / external-rules / globs / applyTo / alwaysApply / rule_toggles / rule name / 段落位置） | P7.13 整体汇总，不重复细节 | 整体链路矩阵 + 一致性评估表 + nanobot 残留整合 |
| P6.1 AGENTS.md frontmatter 对比 | 8 项细节（frontmatter 存在 / description / globs / applyTo / alwaysApply / 分隔符 / 解析器 / 移除） | P7.13 整体汇总，不重复细节 | YAML schema 差异整体视角 |
| P6.6 AGENTS.md 条件注入对比 | 8 项细节（alwaysApply / applyTo / mode / globs / enabled / paths / 加载路径 / toggle） | P7.13 整体汇总，不重复细节 | conditional 评估器超集关系整体确认 |

**本阶段（P7.13）定位**：
- **不重复** P5.8 / P6.1 / P6.6 已完成的逐项源码核查
- **聚焦** 整体链路矩阵（7 节点）+ 一致性评估表（9 维度）+ nanobot 残留整合
- **修正** 计划表 3 处事实错误（与上述三阶段同源）
- **提供** 整体视角的修复建议优先级排序

---

## 九、附录：整体链路源码对照

### 9.1 Cline 整体链路调用关系

```
refreshClineRulesToggles (cline-rules.ts L7-34)
  ├─ synchronizeRuleToggles (rule-helpers.ts L40-104)
  │   ├─ readDirectoryRecursive (rule-helpers.ts L13-35)
  │   │   └─ excludedPaths: [[".clinerules","workflows"], [".clinerules","hooks"], [".clinerules","skills"]]
  │   └─ stateManager.setGlobalState / setWorkspaceState
  ├─ getRuleFilesTotalContentWithMetadata (rule-helpers.ts L206-259)
  │   ├─ parseYamlFrontmatter (frontmatter.ts L38-59)
  │   │   └─ stripUtf8Bom + 正则 + yaml.load(JSON_SCHEMA) + fail-open
  │   ├─ evaluateRuleConditionals (rule-conditionals.ts L78-103)
  │   │   └─ conditionalEvaluators = { paths: evaluatePathsConditional }
  │   │       └─ picomatch(pattern, { dot: true })
  │   └─ 输出: `${ruleFilePathRelative}\n${body.trim()}`
  └─ refreshExternalRulesToggles (external-rules.ts L10-49)
      └─ 扫描 .cursorrules / .cursor/rules/*.mdc / .windsurfrules / AGENTS.md

refreshWorkflowToggles (workflows.ts L10-32)
  ├─ synchronizeRuleToggles (复用 rule-helpers.ts)
  └─ 独立 toggle 槽: globalWorkflowToggles + workflowToggles
```

### 9.2 Charles 整体链路调用关系

```
SystemPromptBuilder._build_rules (context.py L454-539)
  ├─ 1. global AGENTS.md: ~/.agent/AGENTS.md → _strip_frontmatter 无条件加载
  ├─ 2. workspace AGENTS.md: agents_path → _strip_frontmatter 无条件加载
  ├─ 3. rules_dir: _load_rules_directory (context.py L541-609)
  │   ├─ synchronize_rule_toggles (rules_loader.py L889-957)
  │   │   ├─ _is_path_in_excluded_subdir (rules_loader.py L494-521)
  │   │   │   └─ excluded_subdirs=["workflows","hooks","skills"]
  │   │   └─ save_toggles → rule_toggles.json / sessions/<id>/rule_toggles.local.json
  │   ├─ load_rules_directory (rules_loader.py L568-683)
  │   │   ├─ _read_with_mtime_cache (rules_loader.py L524-556)
  │   │   │   └─ _RULES_MTIME_CACHE 模块级缓存
  │   │   ├─ parse_yaml_frontmatter (rules_loader.py L131-181)
  │   │   │   └─ stripUtf8Bom + 同正则 + yaml.safe_load + fail-open + 顶层 dict 校验
  │   │   ├─ evaluate_rule_conditionals (rules_loader.py L433-481)
  │   │   │   ├─ enabled 开关 (L452-455) — Charles 独有
  │   │   │   ├─ applyTo 条件 (L457-463) — Charles 独有
  │   │   │   ├─ mode 条件 (L465-471) — Charles 独有
  │   │   │   └─ paths 条件 (L473-479) — 与 Cline 对齐
  │   │   │       └─ _match_glob (wcmatch 优先 + 正则回退)
  │   │   └─ toggle 过滤 (L613-622)
  │   └─ task_type 兼容层 (L572-582) — Charles 独有
  ├─ 4. MODE_TAG_INSTRUCTIONS (注入 mode 标签说明)
  ├─ 5. PLAN_MODE_INSTRUCTIONS (仅 plan 模式注入)
  ├─ 6. 增强层 (按配置开关)
  └─ 7. extra_sections (已废弃，死代码)
      └─ format_rules_content (rules_loader.py L686-722)
          └─ 输出: `# Rules\n\n## {file_stem}\n\n{body}` 层级 markdown
```

### 9.3 链路节点对齐状态

| 节点 | Cline | Charles | 对齐状态 |
|------|-------|---------|---------|
| 入口 | `refreshClineRulesToggles` | `SystemPromptBuilder._build_rules` + `synchronize_rule_toggles` | 高（架构对齐） |
| 目录扫描 | `readDirectoryRecursive` | `Path.rglob("*.md")` + `_is_path_in_excluded_subdir` | 高（Stage 7.4 对齐） |
| frontmatter 解析 | `parseYamlFrontmatter` | `parse_yaml_frontmatter` | 高（正则逐字符相同） |
| 条件评估 | `evaluateRuleConditionals`（1 评估器） | `evaluate_rule_conditionals`（4 评估器） | Charles 增强 |
| toggle 过滤 | `toggles[ruleFilePath] === false` | `toggles.get(toggle_key, True) is False` | 高（Stage 13.3 对齐） |
| toggle 持久化 | stateManager global + workspace | JSON 文件 global + local | 高（Stage 13.3 对齐） |
| 输出格式化 | 扁平拼接 | 层级 markdown | 中（设计差异） |
| mtime 缓存 | `UnifiedConfigFileWatcher` fs.watch | `_RULES_MTIME_CACHE` mtime 轮询 | Charles 增强 |
| external-rules | `refreshExternalRulesToggles` | 无 | 低（合理偏离） |
| workflows | `refreshWorkflowToggles` 独立 toggle 槽 | `excluded_subdirs` 直接排除 | 低（合理偏离） |
