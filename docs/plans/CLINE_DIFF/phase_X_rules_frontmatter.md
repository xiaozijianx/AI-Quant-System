# Phase X: Cline Rules / Frontmatter / Workflows 对比报告

> 对标源码：
> - `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts`
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts`
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts`
> - `apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts`
> - `apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts`
> - `apps/vscode/src/core/context/instructions/user-instructions/workflows.ts`
> - `apps/vscode/src/core/context/instructions/user-instructions/skills.ts`
> - `sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts`（热重载）
> - `sdk/packages/shared/src/storage/paths.ts`（多目录扫描路径解析）
>
> 当前实现：`agent/rules_loader.py` + `agent/skills/loader.py` + `agent_config/rules/` + `agent_config/AGENTS.md`
> 对比维度：X1-X14

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 1 项 |
| 弱对齐 | 6 项 |
| 缺失 | 4 项 |
| 额外增强 | 3 项 |
| **对齐度** | **约 40%** |

**核心结论**：
- frontmatter 解析的 fail-open 核心逻辑与 Cline 等价，但 YAML schema 不同（Cline 用 `JSON_SCHEMA`，我用 `safe_load`）。
- 条件评估方面，我的实现有 3 项 Cline 不具备的额外增强（`applyTo` / `mode` / `enabled` frontmatter 字段），但 Cline 的 `rule-conditionals.ts` **仅**实现 `paths` 一种条件。
- 主要差距集中在"生态"层：workflows / external-rules / 热重载 / 多目录（global + workspace）扫描，这些是 VS Code 扩展特性，量化场景部分不需要。
- `toggles` 机制仅实现内存过滤，缺少 Cline 的持久化（stateManager）与磁盘同步（`synchronizeRuleToggles`）。
- skills 加载与 rules 区分的核心设计一致，但缺少 multi-source（project + disk-global + remote）与 override resolution。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| X1 | frontmatter YAML 解析 | frontmatter.ts L38-59 | rules_loader.py L119-169 | 完全一致 |
| X2 | `applyTo` 条件（act/plan 过滤） | **Cline 无此字段** | rules_loader.py L267-298 | 额外增强 |
| X3 | `mode` 条件（业务模式过滤） | **Cline 无此字段** | rules_loader.py L301-328 | 额外增强 |
| X4 | `paths` glob 匹配 | rule-conditionals.ts L39-72（picomatch） | rules_loader.py L191-264（简化正则） | 弱对齐 |
| X5 | `enabled` 字段 | **Cline rules 无此字段**（仅 skills 有 `disabled`） | rules_loader.py L351-353 | 额外增强 |
| X6 | toggles 机制 | rule-helpers.ts L40-104 + cline-rules.ts | rules_loader.py L420-432 | 弱对齐 |
| X7 | cline-rules 加载顺序（优先级） | cline-rules.ts L7-33（global + local 分离） | rules_loader.py L416（单目录排序） | 缺失 |
| X8 | external-rules | external-rules.ts L10-49 | 无 | 缺失 |
| X9 | workflows | workflows.ts L10-31 | 无 | 缺失 |
| X10 | skills 加载（与 rules 区分） | skills.ts L139-270 | skills/loader.py L71-385 | 弱对齐 |
| X11 | 多目录扫描（workspace + global） | paths.ts L376-394 + cline-rules.ts | rules_loader.py L416（单目录） | 弱对齐 |
| X12 | 热重载（文件变更重新加载） | unified-config-file-watcher.ts L94-189 | 无（每次 build 重读） | 缺失 |
| X13 | rule 合并方式（拼接 vs 覆盖） | rule-helpers.ts L250-254 | rules_loader.py L499-527 | 弱对齐 |
| X14 | rule 优先级（后加载覆盖前加载） | rule-helpers.ts L215-248（数组顺序） | rules_loader.py L416（文件名排序） | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #X4：paths glob 匹配引擎不等价

**严重度**：P1（语义不等价，影响路径条件过滤准确性）

**Cline 实现**（`rule-conditionals.ts` L12, L39-72）：
- 使用 `picomatch` 库（L65: `picomatch(pattern, { dot: true })`）
- 支持完整 glob 语义：brace expansion（`{a,b}`）、negation（`!pattern`）、extglob（`+(a)`）、`**` 跨目录、dot 文件匹配
- `dot: true` 选项允许匹配以 `.` 开头的文件/目录

**我的实现**（`rules_loader.py` L191-231）：
- 自实现 `_match_glob` 简化版正则转换
- 仅支持 `*`（单层）、`**`（多层）、`?`（单字符）
- 不支持 brace expansion、negation、extglob
- 不显式处理 dot 文件（正则 `[^/]*` 会匹配 `.hidden` 但行为与 picomatch `dot:true` 不完全等价）

**影响**：
- 复杂 glob 模式（如 `src/{lib,bin}/**/*.py` 或 `!**/*.test.ts`）在我的实现中无法正确匹配
- 量化场景目前规则文件未使用复杂 glob（见 `agent_config/rules/*.md` 均无 `paths` 字段），实际影响有限
- 但当未来需要按路径过滤规则时（如仅对 `live_trading/` 目录启用交易规则），会因 glob 语义差异导致规则激活不符合预期

**修复建议**：
- 短期：引入 `wcmatch` 或 `pathspec` 库（Python 版 picomatch 等价物），替换 `_match_glob`
- 中期：补充 brace expansion 和 negation 支持
- 长期：对齐 `dot: true` 默认行为

**优先级**：P1

---

### 差距 #X6：toggles 机制缺少持久化与磁盘同步

**严重度**：P1（影响用户级开关持久化）

**Cline 实现**：
- `rule-helpers.ts` L40-104 `synchronizeRuleToggles`：扫描目录，为新文件添加默认 toggle=true，删除不存在文件的 toggle
- `cline-rules.ts` L7-33 `refreshClineRulesToggles`：global + local 两层 toggle，持久化到 `stateManager`（global settings + workspace state）
- `rule-helpers.ts` L220 `getRuleFilesTotalContentWithMetadata`：`if (ruleFilePath in toggles && toggles[ruleFilePath] === false)` 跳过禁用规则
- toggle key 为**绝对路径**

**我的实现**（`rules_loader.py` L420-432）：
- `toggles: dict[str, bool]` 由调用方传入（`context.py` L458-468 传入 `rule_toggles`）
- toggle key 支持**相对路径和绝对路径**两种形式（L424: `rel_path if rel_path in toggles else abs_path`）
- 无持久化：每次 build system prompt 时由 `SystemPromptBuilder` 临时构造
- 无磁盘同步：不会自动添加新文件 toggle 或清理已删除文件 toggle
- `context.py` L458-461 还会用 toggle 跳过兼容层已加载的 `task_type.md`，避免重复

**影响**：
- 用户无法通过 UI 持久化禁用某个规则文件（重启后丢失）
- 新增规则文件不会自动出现在 toggle 列表中（但因默认 True，仍会激活，影响可控）
- 删除规则文件后 toggle 残留（无清理逻辑，但无副作用）

**修复建议**：
- 短期：在 `agent/state.py` 或独立 JSON 文件持久化 toggles（key 用相对路径）
- 中期：实现 `synchronize_rule_toggles` 等价函数，扫描目录同步 toggle 列表
- 长期：通过 SSE 事件 + API 端点暴露 toggle 管理（对标 Cline VS Code 扩展 UI）

**优先级**：P1

---

### 差距 #X7：cline-rules 加载顺序（global + local 分离）缺失

**严重度**：P2（影响全局规则与项目规则的分层管理）

**Cline 实现**（`cline-rules.ts` L7-33）：
- 显式分离 global toggles（`globalClineRulesToggles`，存于 global settings）和 local toggles（`localClineRulesToggles`，存于 workspace state）
- global 规则目录：`ensureRulesDirectoryExists()` → `~/.cline/rules/`
- local 规则目录：`<workspace>/.clinerules/`（排除 `workflows/`、`hooks/`、`skills/` 子目录，见 L24-27）
- 两层独立加载，分别管理 toggle

**我的实现**：
- 仅单目录扫描：`agent_config/rules/`（`server.py` L520）
- 无 global 规则目录概念
- 所有规则在同一个目录下，按文件名排序加载

**影响**：
- 无法实现"全局规则 + 项目规则"分层管理（如全局编码规范 + 项目特定交易规则）
- 量化场景目前所有规则都在项目内，影响有限
- 但若未来有多个项目共享规则，需要复制规则文件

**修复建议**：
- 中期：引入 global 规则目录（如 `~/.agent/rules/`），在 `load_for_session` 中合并加载
- 长期：实现 global/local toggle 分离持久化

**优先级**：P2

---

### 差距 #X8：external-rules（.cursorrules / .windsurfrules / AGENTS.md）缺失

**严重度**：P3（量化场景无跨工具规则共享需求）

**Cline 实现**（`external-rules.ts` L10-49）：
- 支持三种外部规则文件，各有独立 toggle：
  - `.windsurfrules`（Windsurf IDE 规则）
  - `.cursorrules` 或 `.cursor/rules/*.mdc`（Cursor IDE 规则，支持两个位置）
  - `AGENTS.md`（通用 agent 规则）
- `combineRuleToggles` 合并 cursor 两个位置的 toggle（L35）
- 每种外部规则有独立 workspace state key（`localCursorRulesToggles` / `localWindsurfRulesToggles` / `localAgentsRulesToggles`）

**我的实现**：
- 无 `.cursorrules` / `.windsurfrules` 加载
- `AGENTS.md` 由 `SystemPromptBuilder._load_agents_file()` 单独加载（`context.py` L176-178），不走 rules_loader 流程
- 不支持 frontmatter 条件过滤 AGENTS.md

**影响**：
- 无法复用其他 IDE 的规则文件（量化场景几乎不需要）
- AGENTS.md 作为顶层指令单独加载，逻辑上合理但与 Cline 的"AGENTS.md 作为 external rule"定位不同

**语义不等价标注**：
- Cline: `AGENTS.md` 是 external-rules 的一种，走 `getRuleFilesTotalContentWithMetadata` 流程，支持 frontmatter 条件过滤
- 我: `AGENTS.md` 是顶层引导文件，单独加载，不支持 frontmatter 条件过滤
- 两种定位都合理，但行为不同

**修复建议**：
- 暂不实现 `.cursorrules` / `.windsurfrules`（量化场景无需求）
- 可选：将 `AGENTS.md` 纳入 rules_loader 流程以支持 frontmatter（但会破坏当前"顶层指令"语义，不建议改）

**优先级**：P3

---

### 差距 #X9：workflows（工作流文件）缺失

**严重度**：P2（影响可复用工作流管理）

**Cline 实现**（`workflows.ts` L10-31）：
- workflows 独立于 rules，存于 `.clinerules/workflows/`（local）和 `~/.cline/workflows/`（global）
- 独立 toggle 体系：`globalWorkflowToggles` + `workflowToggles`（workspace state）
- `rule-helpers.ts` L150-153 `LOCAL_RULE_PATHS` 定义 workflows 子目录路径
- `rule-helpers.ts` L305-334 `ensureLocalClineDirExists` 处理 `.clinerules` 文件 → 目录的迁移
- workflows 与 rules 使用相同的 `getRuleFilesTotalContentWithMetadata` 加载逻辑（含 frontmatter 条件过滤）

**我的实现**：
- 无 workflows 概念
- 所有规则文件平铺在 `agent_config/rules/` 下

**影响**：
- 无法区分"常驻规则"与"按需触发的工作流"
- 量化场景的"五步法研报流程"、"交易计划生成流程"目前通过 skills 实现，未走 workflow 通道
- 实际影响有限（skills 已覆盖工作流场景），但语义不同

**修复建议**：
- 中期：若需要"文件级工作流"（非 skill 级），可引入 `agent_config/workflows/` 目录
- 当前 skills 机制已足够，暂不实现

**优先级**：P2

---

### 差距 #X10：skills 加载缺少 multi-source 与 override resolution

**严重度**：P2（影响技能来源多样性与覆盖）

**Cline 实现**（`skills.ts` L139-270）：
- `discoverSkills`（L220-251）：扫描 project + disk-global + remote 三个来源
  - project: workspace 下的 skills 目录
  - disk-global: `~/.cline/skills/`
  - remote: 企业配置下发的远程技能（`GlobalInstructionsFile[]`）
- `getAvailableSkills`（L256-270）：**反向遍历**实现 override resolution（remote > disk-global > project）
- `loadSkillMetadata`（L171-209）：校验 `name` / `description` 必填，且 `name` 必须与目录名一致
- `parseRemoteSkillEntries`（L105-125）：远程技能 frontmatter 校验，warn on name drift
- `getSkillContent`（L276-312）：支持远程技能（无磁盘 I/O，从 `remoteSkillEntries` 取内容）
- `updateSkillMarkdownDisabledState`（L28-56）：通过修改 SKILL.md frontmatter `disabled` 字段持久化启用状态

**我的实现**（`skills/loader.py` L71-385）：
- `SkillLoader.list_skills`（L95-120）：仅扫描单一 `skills_dir`（workspace）
- 无 global skills 目录扫描
- 无 remote skills 支持
- 无 override resolution（同名技能不会按来源优先级覆盖）
- `_parse_skill_file`（L197-268）：校验较宽松，`name` 缺失时 fallback 到目录名（L207）
- 不校验 `name` 与目录名一致（Cline 会 warn 并返回 null，L194-197）
- `_parse_frontmatter`（L334-384）：有 fallback 简单 YAML 解析（Cline 无 fallback，依赖 js-yaml）
- `load_instructions`（L135-160）：额外追加 scripts 脚本路径块（Cline 无此特性）
- 无 `updateSkillMarkdownDisabledState` 等价函数（无法持久化启用状态到 frontmatter）

**影响**：
- 无法支持企业级技能下发（remote skills）
- 无法支持用户级全局技能（跨项目共享）
- 同名技能无覆盖机制（仅按扫描顺序取第一个）
- 技能启用状态无法持久化到文件（Cline 通过修改 SKILL.md 实现）

**修复建议**：
- 短期：校验 `name` 与目录名一致（对齐 Cline L194-197）
- 中期：引入 global skills 目录扫描（`~/.agent/skills/`），实现 override resolution
- 长期：按需评估 remote skills 需求（量化场景可能不需要企业下发）

**优先级**：P2

---

### 差距 #X11：多目录扫描（workspace + global）缺失

**严重度**：P2（影响规则来源多样性）

**Cline 实现**（`sdk/packages/shared/src/storage/paths.ts` L376-394）：
- `resolveRulesConfigSearchPaths` 返回多目录：
  1. `<workspace>/AGENTS.md`（顶层文件）
  2. `<workspace>/.cline/`（DEPRECATED_CONFIG_DIR，向后兼容）
  3. `<workspace>/.cline/rules/`（CLINE_CONFIG_DIR + RULES_CONFIG_DIRECTORY_NAME）
  4. `resolveGlobalAgentsRulesPath()`（全局 AGENTS.md）
  5. `<workspace>/.cline/`（managedRoot，追加在 L562）
- `cline-rules.ts` L22-27 显式排除 `workflows/`、`hooks/`、`skills/` 子目录

**我的实现**（`rules_loader.py` L392-416）：
- 仅扫描单一 `rules_dir`（`agent_config/rules/`）
- `rglob("*.md")` 递归扫描所有子目录（无排除项）
- AGENTS.md 由 `SystemPromptBuilder` 单独加载，不走 rules_loader

**影响**：
- 无全局规则目录（无法跨项目共享规则）
- 无 AGENTS.md 作为 rule 文件的集成（语义不同，见 X8）
- 递归扫描不排除子目录（若未来在 `rules/` 下建 `skills/` 或 `workflows/` 子目录，会被误扫描为规则）

**修复建议**：
- 短期：在 `load_rules_directory` 中添加 `excluded_subdirs` 参数（对标 Cline L24-27），排除 `skills/`、`workflows/`、`hooks/`
- 中期：引入 global 规则目录扫描
- 长期：对齐 `resolveRulesConfigSearchPaths` 多目录解析

**优先级**：P2

---

### 差距 #X12：热重载（文件变更重新加载）缺失

**严重度**：P2（影响规则编辑时的即时生效）

**Cline 实现**（`unified-config-file-watcher.ts` L94-189）：
- `UnifiedConfigFileWatcher` 类：基于 Node.js `FSWatcher` 监听目录变更
- debounce 75ms（L134: `this.debounceMs = options?.debounceMs ?? 75`）
- 支持多类型配置（rules / workflows / skills）统一监听
- 增量更新：`recordsByType` Map 维护已发现记录，变更时增量刷新
- 事件驱动：`subscribe(listener)` 订阅变更事件，通知调用方重新加载
- `emitParseErrors` 选项控制是否暴露解析错误

**我的实现**：
- 无文件监听机制
- 每次 `SystemPromptBuilder.build()` 调用时重新读取所有规则文件（`rules_loader.py` L436: `file_path.read_text`）
- 无缓存，无增量更新

**语义不等价标注**：
- Cline: 事件驱动 + 增量更新（仅变更文件重新解析），适合长驻进程（VS Code 扩展）
- 我: 每次 build 全量重读（无缓存），适合短请求周期（Web 服务每次请求重建 system prompt）
- 两种模式都能保证"最新数据"，但性能特征不同：
  - Cline: 监听开销 + 增量更新低延迟
  - 我: 无监听开销 + 每次 build 全量 I/O

**影响**：
- 量化场景每次对话请求都会重建 system prompt，全量重读规则文件的 I/O 开销可接受（规则文件少且小）
- 无法在规则文件变更时主动通知前端（Cline 可通过 watcher 事件触发 UI 刷新 toggle 列表）
- 但由于 Web 服务的请求-响应模型，"每次请求读最新文件"已等价于"热重载"

**修复建议**：
- 短期：保持现状（每次 build 重读已满足热重载语义）
- 中期：若规则文件数量增长，引入 mtime 缓存避免无变更文件的重复 I/O
- 长期：按需评估是否需要 watcher（Web 服务场景大概率不需要）

**优先级**：P2

---

### 差距 #X13：rule 合并方式（拼接格式不等价）

**严重度**：P3（影响 system prompt 中规则段的可读性）

**Cline 实现**（`rule-helpers.ts` L246, L250-254）：
- 每个规则格式：`<ruleFilePathRelative>\n<body>`（L246: `` `${ruleFilePathRelative}\n${body.trim()}` ``）
- 拼接分隔符：`\n\n`（L253: `.join("\n\n")`）
- relative path 作为规则标识（如 `.clinerules/general.md`）
- fail-open 时保留原始 frontmatter（L234: `` `${ruleFilePathRelative}\n${raw}` ``）

**我的实现**（`rules_loader.py` L499-527）：
- 每个规则格式：`## 规则: <name>\n\n<body>`（L525: `f"## 规则: {name}\n\n{body}"`）
- 拼接分隔符：`\n\n`（L527: `"\n\n".join(parts)`）
- `name` 用文件 stem（L524: `r.path.stem`），非完整相对路径
- fail-open 时保留原始内容（L455: `body=raw`），但 format 时仍用 stem 作为标题

**语义差异**：
- Cline 用相对路径作为标识（LLM 可见完整路径，便于引用）
- 我用文件名 stem 作为标题（更简洁，但丢失目录信息）
- 我额外加了 `## 规则:` 前缀和 Markdown 标题格式（Cline 无此格式化）

**影响**：
- LLM 看到的规则标识不同（路径 vs 文件名），可能影响规则引用准确性
- 我的格式更结构化（Markdown 标题），可读性更好
- 实际影响小（规则数量少，LLM 能区分）

**修复建议**：
- 可选：在 `## 规则:` 后附加相对路径（如 `## 规则: general (agent_config/rules/general.md)`）
- 当前格式可读性更好，建议保留

**优先级**：P3

---

### 差距 #X14：rule 优先级（加载顺序逻辑不同）

**严重度**：P3（影响同名/同类规则的覆盖语义）

**Cline 实现**：
- `getRuleFilesTotalContentWithMetadata`（`rule-helpers.ts` L215-248）：按 `rulesFilePaths` 数组顺序处理
- 数组顺序由调用方决定（global + local 分别传入）
- **拼接而非覆盖**：所有通过条件过滤的规则都保留，无覆盖语义
- `skills.ts` L256-270 `getAvailableSkills`：**反向遍历**实现覆盖（remote > disk-global > project），但这是 skills 的逻辑，rules 无覆盖

**我的实现**（`rules_loader.py` L416）：
- `sorted([p for p in rules_path.rglob("*.md") if _is_rule_file(p)])`：按文件名排序
- **拼接而非覆盖**：所有激活规则都保留（`format_rules_content` L516-525）
- 无 global/local 分层，无覆盖语义

**语义分析**：
- Cline 和我都采用"拼接"而非"覆盖"（X13 已述）
- 差异在于排序依据：Cline 由调用方控制数组顺序（可表达优先级），我按文件名字母序
- 量化场景规则文件无同名冲突，排序差异无实际影响

**影响**：
- 无法表达"项目规则覆盖全局规则"的优先级语义（但 Cline rules 本身也不覆盖，仅 skills 覆盖）
- 文件名排序可预测（`general.md` < `plan-mode-rules.md` < `research.md` < `trading.md`）

**修复建议**：
- 暂不需要修复（rules 拼接语义一致，排序差异无实际影响）
- 若未来需要优先级，可在 frontmatter 添加 `priority` 字段

**优先级**：P3

---

## 4. 一致性统计

### 按一致性等级分布

| 等级 | 数量 | 子项 |
|------|------|------|
| 完全一致 | 1 | X1 |
| 弱对齐 | 6 | X4, X6, X10, X11, X13, X14 |
| 缺失 | 4 | X7, X8, X9, X12 |
| 额外增强 | 3 | X2, X3, X5 |

### 按严重度分布

| 严重度 | 数量 | 子项 |
|--------|------|------|
| P1 | 2 | X4, X6 |
| P2 | 5 | X7, X9, X10, X11, X12 |
| P3 | 4 | X8, X13, X14（X1 无差距） |

### 对齐度计算

- 完全一致：1 × 1.0 = 1.0
- 弱对齐：6 × 0.5 = 3.0
- 额外增强：3 × 0.5 = 1.5（合理增强，不扣分但也不计为一致）
- 缺失：4 × 0.0 = 0.0
- **对齐度 = (1.0 + 3.0 + 1.5) / 14 ≈ 39%**

---

## 5. 额外增强项

### 增强 #X2：`applyTo` 条件（agent 模式过滤）

**我**：`rules_loader.py` L267-298 `_evaluate_apply_to_conditional`
- frontmatter `applyTo: [plan, act]` 字段，按当前 agent 模式过滤规则
- 省略 → 应用到所有模式；空数组 → 不应用（fail-closed）
- 实际使用：`agent_config/rules/plan-mode-rules.md` 用 `applyTo: [plan]` 仅在 Plan 模式激活

**Cline**：`rule-conditionals.ts` 无此字段，rules 不支持按 agent 模式过滤

**评估**：合理增强。量化场景需要区分 Act/Plan 模式的规则（如 Plan 模式的探索阶段要求），Cline 通过外部 mode-based 工具路由实现，我通过 frontmatter 条件实现，语义更内聚。保留。

---

### 增强 #X3：`mode` 条件（业务模式过滤）

**我**：`rules_loader.py` L301-328 `_evaluate_business_mode_conditional`
- frontmatter `mode: [research, trade]` 字段，按当前业务模式列表过滤规则
- 省略 → 应用到所有业务模式；空数组 → 不应用
- 实际使用：`agent_config/rules/research.md` 用 `mode: [research]`，`trading.md` 用 `mode: [trade]`

**Cline**：无此字段

**评估**：合理增强。量化场景有明确的业务模式划分（研究/交易），Cline 通用编码场景无此需求。保留。

---

### 增强 #X5：`enabled` 字段（frontmatter 级启用开关）

**我**：`rules_loader.py` L351-353
- frontmatter `enabled: false` 直接跳过规则（无需 toggles）
- 默认 `true`

**Cline**：rules 无 frontmatter `enabled` 字段，仅通过 toggles（外部状态）控制启用/禁用；skills 有 frontmatter `disabled` 字段（`skills.ts` L28-56）

**评估**：合理增强。提供 frontmatter 级的静态禁用机制（无需运行时 toggles），适合"永久禁用某规则"场景。与 Cline skills 的 `disabled` 字段设计一致。保留。

---

## 6. 修复建议

### 短期（P1，建议本轮完成）

1. **X4 paths glob 引擎对齐**：引入 `wcmatch.glob` 库替换 `_match_glob`，支持 brace expansion / negation / dot 文件
   - 影响文件：`agent/rules_loader.py` L191-231
   - 依赖：`pip install wcmatch`

2. **X6 toggles 持久化**：在 `agent_config/` 下新增 `rule_toggles.json`，由 `rules_loader.py` 提供加载/保存函数
   - 影响文件：`agent/rules_loader.py`（新增 `load_toggles` / `save_toggles` / `synchronize_toggles` 函数）
   - key 统一用相对路径

### 中期（P2，建议下个阶段）

3. **X7 + X11 多目录扫描**：引入 global 规则目录（`~/.agent/rules/`），在 `load_for_session` 中合并 workspace + global
   - 影响文件：`agent/rules_loader.py`、`agent/server.py`
   - 需新增 `excluded_subdirs` 参数排除 `skills/`、`workflows/`、`hooks/`

4. **X10 skills multi-source**：引入 global skills 目录扫描 + override resolution
   - 影响文件：`agent/skills/loader.py`
   - 对齐 Cline `getAvailableSkills` 反向遍历覆盖逻辑

5. **X9 workflows**：评估是否需要独立 workflows 目录（当前 skills 已覆盖工作流场景，暂缓）

6. **X12 热重载**：保持现状（每次 build 重读已等价热重载），若规则文件增长则引入 mtime 缓存

### 长期（P3，按需评估）

7. **X8 external-rules**：暂不实现 `.cursorrules` / `.windsurfrules`（量化场景无需求）
8. **X13 合并格式**：可选在 `## 规则:` 后附加相对路径
9. **X14 优先级**：暂不需要（rules 拼接语义一致）

---

## 7. 验证记录

### 已验证文件

| 文件 | 路径 | 状态 |
|------|------|------|
| Cline frontmatter | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts` | 已读取，L1-59 |
| Cline rule-conditionals | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts` | 已读取，L1-153 |
| Cline rule-helpers | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` | 已读取，L1-467 |
| Cline cline-rules | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts` | 已读取，L1-34 |
| Cline external-rules | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts` | 已读取，L1-49 |
| Cline workflows | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/workflows.ts` | 已读取，L1-32 |
| Cline skills | `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/skills.ts` | 已读取，L1-313 |
| Cline unified-config-file-watcher | `third_party/cline/sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts` | 已读取，L90-189 |
| Cline paths | `third_party/cline/sdk/packages/shared/src/storage/paths.ts` | 已读取，L376-410 |
| 我的 rules_loader | `agent/rules_loader.py` | 已读取，L1-601 |
| 我的 skills/loader | `agent/skills/loader.py` | 已读取，L1-392 |
| 我的 AGENTS.md | `agent_config/AGENTS.md` | 已读取，L1-46 |
| 我的 rules/general.md | `agent_config/rules/general.md` | 已读取，L1-35 |
| 我的 rules/plan-mode-rules.md | `agent_config/rules/plan-mode-rules.md` | 已读取，L1-41 |
| 我的 rules/research.md | `agent_config/rules/research.md` | 已读取，L1-34 |
| 我的 rules/trading.md | `agent_config/rules/trading.md` | 已读取，L1-40 |
| 集成点 context.py | `agent/context.py` L423-477 `_load_rules` | 已读取 |
| 集成点 server.py | `agent/server.py` L505-539 `_build_system_prompt` | 已读取 |

### 关键交叉验证

1. **Cline rule-conditionals 仅支持 paths**：Grep 搜索 `applyTo` / `apply_to` / `business_mode` / `businessMode` 在 `instructions/` 目录下无匹配，确认 Cline rules frontmatter 仅 `paths` 一种条件。
2. **Cline rules 无 frontmatter `enabled`**：`rule-helpers.ts` 仅通过 `toggles` 控制启用/禁用；`enabled` 字段仅出现在 skills 相关代码（`skills.ts` L45-46 处理 stale `enabled: false`）。
3. **Cline AGENTS.md 是 external rule**：`paths.ts` L24 `AGENTS_RULES_FILE_NAME = "AGENTS.md"`，L386 将 `AGENTS.md` 纳入 rules search paths。
4. **我的 AGENTS.md 是顶层指令**：`context.py` L176-178 `_load_agents_file()` 单独加载，不走 `rules_loader`，不支持 frontmatter 条件过滤。
5. **无热重载机制**：Grep 搜索 `watcher|hot.?reload|file.?watch|mtime|on_modified|watchdog` 在 `agent/` 下仅 `file_lock.py` 有 mtime 用途，与规则无关。
6. **无 external-rules**：Grep 搜索 `cursorrules|windsurfrules|\.clinerules|external.?rule|global.?rule` 在 `agent/` 下无匹配。
7. **无 workflows**：Grep 搜索 `workflow|workflows` 在 `agent/` 下无匹配。

---

**阶段 X 结论**：rules/frontmatter 核心解析逻辑（fail-open + 条件评估）与 Cline 对齐度较高，且额外增强了 `applyTo` / `mode` / `enabled` 三个 frontmatter 条件以适应量化场景的 Act/Plan 模式和业务模式划分。主要差距在"生态"层：workflows / external-rules / 热重载 / 多目录（global + workspace）扫描，这些是 VS Code 扩展特性，量化场景部分不需要。P1 级差距为 paths glob 引擎（picomatch vs 简化正则）和 toggles 持久化机制，建议短期修复。
