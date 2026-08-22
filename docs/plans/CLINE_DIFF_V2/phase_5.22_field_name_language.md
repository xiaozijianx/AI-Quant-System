# Phase 5.22 System Prompt 字段名语言对比

> 对比范围：Cline `system.ts`（base prompt 模板）+ `cline.ts`（占位符替换 + workspace metadata 构建）与 Charles `charles_system_prompt.py`（base prompt 模板）+ `context.py`（`build_charles_system_prompt` 纯组装器 + `SystemPromptBuilder._build_metadata` / `_build_tools_section` / `_build_mcp_servers_section` / `_build_environment` / `_build_mode_tag_instructions` / `_build_enhancement_rules` 等编排器方法）的 System Prompt 中字段名语言（英文 vs 中文）、标签语言、占位符语言的逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（DEFAULT + YOLO 双 base prompt 模板，含 `<env>` 段、`{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}` / `{{CLINE_RULES}}` / `{{CLINE_METADATA}}` 6 个占位符）
> - `sdk/packages/shared/src/prompt/cline.ts` L47-86（`processWorkspaceInfo` + `buildWorkspaceMetadata`：metadata JSON 字段名 `workspaces` / `hint` / `associatedRemoteUrls` / `latestGitCommitHash` / `latestGitBranchName` + `# Workspace Configuration` 文本标记）+ L110-166（`buildClineSystemPrompt` 占位符替换 + `MODE_TAG_INSTRUCTIONS` / `PLAN_MODE_INSTRUCTIONS` 注入 effectiveRules）
>
> Charles 源码：
> - `agent/prompts/charles_system_prompt.py` L1-94（DEFAULT + YOLO 双 base prompt 模板，含 `<env>` 段、6 个占位符；模板主体内容为中文，但 env 字段名为英文）
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装器，占位符替换）+ L408-452（`_build_metadata`：metadata JSON 字段名 + `# Workspace Configuration` 标记）+ L649-681（`_build_environment` 废弃方法，中文字段名）+ L723-786（`_build_tools_section`：中文标题与正文）+ L788-834（`_build_mcp_servers_section`：中文标题与正文）+ L836-856（`_build_mode_tag_instructions`：中文标题与正文）+ L611-647（`_build_enhancement_rules`：英文 rule title + 中文 body）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 中**字段名语言**（英文 vs 中文）的逐项一致性，覆盖 env / metadata / tools / skills / rules 五大字段类别。**核心结论：Charles 生产路径在 env 字段名、metadata 字段名、占位符命名上已与 Cline 完全对齐（英文）；剩余语言差异集中在增强层方法（`_build_tools_section` / `_build_mcp_servers_section` / `_build_mode_tag_instructions`）的中文标题、`_build_environment` 废弃方法的中文 env 字段名、以及 base prompt 模板主体文本（身份描述、规则段标题）的中文措辞。** 这些差异属于 Cline（英文优先、面向通用编码场景）与 Charles（中文优先、面向量化投研场景）的合理场景偏离，非对齐缺口；但 `_build_environment` 废弃方法的中文字段名被计划文件误判为生产路径差异，需要修正。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.22（L2207-2217）的对比表存在 **2 处事实错误 + 1 处误导性描述**，需逐项修正：

1. **5.22.1 标注"env 字段名 — Charles 中文 — L1 差距"** — **事实错误**：Charles 生产路径 `charles_system_prompt.py` L49-54 的 env 字段名为英文（`Platform` / `Date` / `IDE` / `Working Directory`），与 Cline `system.ts` L8-13 完全一致。计划表描述的"中文字段名（平台/日期/工作目录）"来自 `context.py::_build_environment()` 废弃方法（L664-680），该方法在生产路径中**不被调用**（仅 `tests/test_stage4_context_prompt.py` 调用），不构成 L1 差距。此误判与 Phase 5.4（env 段对比）属同一来源、同一性质。

2. **5.22.4 标注"skills 字段名 — Charles 中文（部分）— 语言不同"** — **误导性描述**：Charles 增强层 `_build_enhancement_rules`（context.py L611-647）返回的 5 个 rule title 均为**英文**（`charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` / `charles-skills-summary` / `charles-memory`），与 Cline 通过 extension/tool 系统注册 skills 工具的英文命名一致。中文部分出现在 rule body 内（如 SKILL.md 指令、技能摘要文本），但 body 内容为业务文案，**非字段名**。计划表将"body 内容文案语言"误判为"字段名语言"。

3. **5.22.5 标注"rules 字段名 — Charles 中文 — 语言不同"** — **事实错误**：Charles rules 段输出格式（`rules_loader.py::format_rules_content` L686-722）使用 `## {file_stem}\n\n{body}` + 顶部 `# Rules` 一级标题。`# Rules` 标题为**英文**（对齐 Cline 的 rules 概念命名），`{file_stem}` 为文件名 stem（如 `general` / `research` / `trading` / `plan-mode-rules` / `AGENTS` — 全部英文命名），body 内容为中文（来自 `agent_config/rules/*.md` 文件正文）。计划表将"body 内容文案语言"误判为"字段名语言"。实际 rules 段的**字段名**（标题 + stem）全部为英文。

### 核心结论

1. **env 字段名已对齐**（生产路径）：Cline `system.ts` 与 Charles `charles_system_prompt.py` 的 `<env>` 段字段名（Platform / Date / IDE / Working Directory）完全一致，均英文。占位符 `{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}` 完全一致。
2. **metadata 字段名已对齐**：Cline `buildWorkspaceMetadata` 与 Charles `_build_metadata` 的 JSON 字段名（`workspaces` / `hint` / `latestGitCommitHash` / `latestGitBranchName` / `associatedRemoteUrls`）完全一致，均英文。文本标记 `# Workspace Configuration` 完全一致。
3. **tools 字段名为 Charles 独有增强**（默认关闭）：Cline 不在 system prompt 写工具列表（通过 tool definitions 动态提供）。Charles `_build_tools_section` 增强层（默认 `enabled: false`）使用中文标题（`# 工具` / `## 工具使用指引` / `## 工具 vs 技能 决策树` 等），但增强层关闭时不在 system prompt 中出现。Charles 字段名差异不与 Cline 构成对齐缺口（Cline 无对应概念）。
4. **skills 字段名为 Charles 独有增强**（默认关闭）：Cline 不在 system prompt 写 skills 概览（通过 extension 注册为 `skills` 工具）。Charles `_build_enhancement_rules` 的 5 个 rule title 均为英文（`charles-tools-overview` 等），body 为中文业务文案。增强层关闭时不出现。
5. **rules 字段名部分对齐**：占位符 `{{CLINE_RULES}}` vs `{{CHARLES_RULES}}` 均英文（命名前缀不同，语义对齐）。Charles 输出格式 `# Rules` + `## {stem}` 标题均为英文；body 内容为中文（来自中文 rules 文件正文）。Cline 输出格式 `${ruleFilePathRelative}\n${body}` 无 `##` 标题，body 内容为用户规则文件原文（语言由用户决定）。
6. **占位符语言已对齐**：6 个占位符全部为大写英文 + 双花括号包裹（`{{...}}`），命名前缀不同（`CLINE_*` vs `CHARLES_*`），语义对齐。
7. **标签语言已对齐**：`<env>` / `</env>` XML 标签均英文小写，与 Cline 一致；`<user_input mode="...">` / `<mode_notice>` 标签均英文小写（MODE_TAG_INSTRUCTIONS 中描述）。
8. **nanobot 残留**：System Prompt 字段名相关代码 **0 处实现逻辑残留**，**1 处注释残留**（`context.py` L275 `extra_sections` docstring，与 Phase 5.1 / 5.4 / 5.8 同一处）。base prompt 模板与字段名本身无 nanobot 残留。

### 一致性总体评估

- **env 字段名（生产路径）**：**高**。`charles_system_prompt.py` 与 `system.ts` 完全一致。
- **metadata 字段名**：**高**。JSON 字段名 + 文本标记完全一致。
- **占位符命名**：**高**。6 个占位符结构完全一致，仅前缀不同。
- **标签语言**：**高**。`<env>` / `<user_input>` / `<mode_notice>` 均英文小写。
- **tools / skills 字段名（增强层）**：**N/A**（Charles 独有，Cline 无对应概念）。增强层 rule title 为英文，body 为中文业务文案。
- **rules 字段名**：**中-高**。占位符、`# Rules` 顶部标题、文件 stem 均英文；body 内容语言由用户规则文件决定（Charles 默认中文，Cline 由用户写入语言决定）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.22.1 | env 字段名 | `Platform` / `Date` / `IDE` / `Working Directory`（system.ts L9-12，英文） | **生产路径**：`Platform` / `Date` / `IDE` / `Working Directory`（charles_system_prompt.py L50-53，英文）<br>**废弃方法**：`工作目录` / `平台` / `日期` / `IDE` / `Git 分支` / `Git 提交` / `Git 远端`（context.py L666-678，中文） | 高（生产路径） | 计划表标注"Charles 中文 / L1 差距"**事实错误**。生产路径已对齐为英文；废弃方法 `_build_environment` 使用中文字段名，但生产路径不调用此方法。废弃方法差异属 P1 工程优化（建议删除或改造），非对齐缺口 |
| 5.22.2 | metadata 字段名 | JSON 键：`workspaces` / `hint` / `associatedRemoteUrls` / `latestGitCommitHash` / `latestGitBranchName`（cline.ts L50-56 + L75-80，英文）+ 文本标记 `# Workspace Configuration`（cline.ts L9，英文） | JSON 键：`workspaces` / `hint` / `latestGitCommitHash` / `latestGitBranchName` / `associatedRemoteUrls`（context.py L432-440，英文）+ 文本标记 `# Workspace Configuration`（context.py L450，英文） | 高 | 完全一致。Charles L5 重构已对齐 Cline L5（移除 `<charles_metadata>` XML 标签，改用 `# Workspace Configuration` 文本标记） |
| 5.22.3 | tools 字段名 | **无对应概念**：Cline 不在 system prompt 写工具列表，工具通过 tool definitions 动态注册给 LLM | 增强层（默认关闭）`_build_tools_section`（context.py L723-786）：标题 `# 工具` / `## 工具使用指引` / `## 工具 vs 技能 决策树` / `## 任务拆解（强制）` / `## 重要：输出内容 ≠ 完成任务`（中文）；工具列表项格式 `- {name}: {desc}`（name 为英文工具名） | N/A | Charles 独有增强。rule title `charles-tools-overview` 为英文（context.py L625），body 标题为中文。增强层关闭时不出现。语言差异属合理场景偏离（中文量化投研场景），非字段名对齐缺口 |
| 5.22.4 | skills 字段名 | **无对应概念**：Cline 通过 extension 注册 `skills` 工具，不在 system prompt 写 skills 概览 | 增强层（默认关闭）`_build_enhancement_rules`（context.py L611-647）返回 5 个 rule，title 均为英文：`charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` / `charles-skills-summary` / `charles-memory`（L625 / L630 / L636 / L642 / L645）；body 内容为中文业务文案（来自 SKILL.md / skills_registry.build_summary()） | N/A | 计划表标注"Charles 中文（部分）/ 语言不同"**误导**。rule title 为英文，body 为中文业务文案。Cline 无对应概念，不存在"字段名语言"对齐问题。增强层关闭时不出现 |
| 5.22.5 | rules 字段名 | 占位符 `{{CLINE_RULES}}`（system.ts L35，英文）+ 输出格式 `${ruleFilePathRelative}\n${body}`（rule-helpers.ts L246，无 `##` 标题，label 为相对路径如 `.clinerules/general.md`，英文路径） | 占位符 `{{CHARLES_RULES}}`（charles_system_prompt.py L56，英文）+ 输出格式 `# Rules\n\n## {stem}\n\n{body}`（rules_loader.py L716-722，`# Rules` 顶部标题 + `## {stem}` 二级标题，stem 为英文文件名如 `general` / `research` / `trading`；body 为中文规则正文） | 中-高 | 计划表标注"Charles 中文 / 语言不同"**事实错误**。占位符、`# Rules` 顶部标题、`## {stem}` 二级标题均为英文；仅 body 内容为中文（来自中文 rules 文件）。Cline 的 body 语言由用户规则文件决定，非"字段名语言"差异 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.22 误判来源：废弃方法 vs 生产路径（5.22.1）

计划文件 L2211 标注 "env 字段名 — Charles 中文 — L1 差距"，其描述基于 Charles `context.py::_build_environment()` 废弃方法（L649-681）的输出格式：

```python
# context.py L664-680（废弃方法，生产路径不调用）
lines = [
    "<env>",
    f"工作目录: {self.working_dir}",   # 中文
    f"平台: {plat}",                    # 中文
    f"日期: {today}",                   # 中文
    f"IDE: {self.ide_name}",            # 英文（IDE 是国际通用缩写）
]
if git_info.get("branch"):
    lines.append(f"Git 分支: {git_info['branch']}")    # 中文
if git_info.get("commit"):
    lines.append(f"Git 提交: {git_info['commit']}")    # 中文
if git_info.get("remote"):
    lines.append(f"Git 远端: {git_info['remote']}")    # 中文
lines.append("</env>")
```

实际生产路径 `charles_system_prompt.py` L49-54 的 env 段：

```
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

**与 Cline `system.ts` L7-13 完全一致**（仅缺 `Environment you are running in:` 引导句，已在 Phase 5.4 报告中记录）。

**核查结论**：
- 计划表描述的"中文字段名"来源是 `context.py::_build_environment()` 废弃方法，**不是生产路径**。
- `build_charles_system_prompt`（生产路径纯组装器，L78-127）只做占位符替换，不构造 env 字段名。
- `SystemPromptBuilder.build`（生产路径编排器，L348-391）调用 `build_charles_system_prompt` 完成 base 模板组装，不调用 `_build_environment`。
- `_build_environment` 仅被 `tests/test_stage4_context_prompt.py` L133 / L143 / L304 / L322 调用，生产路径不调用。
- 此误判与 Phase 5.4（env 段对比）报告 §6.1 属同一来源、同一性质 —— 计划文件 P5.4 同样将废弃方法的中文字段名误判为生产路径差异。

### 3.2 metadata 字段名完全对齐（5.22.2）

Cline `cline.ts::buildWorkspaceMetadata`（L64-86）与 Charles `context.py::_build_metadata`（L408-452）在 metadata 字段名上完全一致：

| 字段名 | Cline（cline.ts L50-56 + L75-80） | Charles（context.py L432-440） | 一致性 |
|--------|----------------------------------|-------------------------------|--------|
| 顶层包装 | `workspaces` | `workspaces` | 一致 |
| 工作空间标识 | `[rootPath]: {...}` | `[self.working_dir]: {...}` | 一致 |
| hint | `hint: workspaceName \|\| rootPath.split("/").at(-1) \|\| rootPath` | `hint: workspace_name`（workspace_name = ide_name \|\| working_dir.split("/")[-1] \|\| working_dir） | 一致 |
| git 提交 | `latestGitCommitHash` | `latestGitCommitHash` | 一致 |
| git 分支 | `latestGitBranchName` | `latestGitBranchName` | 一致 |
| git 远端 | `associatedRemoteUrls: [url]`（数组） | `associatedRemoteUrls: [url]`（数组） | 一致 |
| 文本标记 | `# Workspace Configuration`（cline.ts L9 WORKSPACE_CONFIGURATION_MARKER） | `# Workspace Configuration`（context.py L450） | 一致 |
| JSON 缩进 | 2 空格（`JSON.stringify(..., null, 2)`） | 2 空格（`json.dumps(..., indent=2)`） | 一致 |

**结论**：metadata 字段名完全对齐，无语言差异。Charles L5 重构（详见 Phase 5.6 报告）已移除原 `<charles_metadata>` XML 标签，改用 Cline 的 `# Workspace Configuration` 文本标记。

### 3.3 tools 字段名：Charles 独有增强层（5.22.3）

**Cline 设计**：Cline 不在 system prompt 写工具列表。工具通过 tool definitions（JSON Schema）动态注册给 LLM，LLM 在每次请求时从 tool definitions 中读取工具名和参数 schema。Cline base prompt（system.ts L1-36）中无 `# Tools` 或类似段落。

**Charles 设计**：Charles 通过 `_build_tools_section`（context.py L723-786）构建工具概览段，作为可选增强层（受 `agent_config/system_prompt.yaml` 的 `enhancements.enabled` 控制，默认 `false`）。当增强层开启时，工具段写入 system prompt 的 rules 段尾部（通过 `_build_enhancement_rules` 返回 `("charles-tools-overview", body)` rule，追加到 `effectiveRules`）。

**字段名语言对比**：

| 元素 | 语言 | 示例 |
|------|------|------|
| rule title（`charles-tools-overview`） | 英文 | context.py L625 |
| 段落标题 `# 工具` | 中文 | context.py L732 |
| 子标题 `## 工具使用指引` | 中文 | context.py L750 |
| 子标题 `## 工具 vs 技能 决策树（重要）` | 中英混合 | context.py L756 |
| 子标题 `## 任务拆解（强制）` | 中文 | context.py L774 |
| 子标题 `## 重要：输出内容 ≠ 完成任务` | 中文 | context.py L780 |
| 工具列表项 `- {name}: {desc}` | name 英文，desc 中文 | context.py L746 |
| skills 工具描述 | 中文 | context.py L737-742 |

**评估**：
- Cline 无对应概念，不存在"字段名语言"对齐问题。
- Charles 增强层默认关闭，关闭时与 Cline 行为一致（不在 system prompt 写工具列表）。
- 中文标题属合理场景偏离（中文量化投研场景，LLM 通常为中文模型如 qwen / deepseek）。
- rule title `charles-tools-overview` 为英文，保持与 Cline extension/tool 系统的英文命名风格一致。

### 3.4 skills 字段名：Charles 独有增强层（5.22.4）

**Cline 设计**：Cline 通过 `userInstructionPlugin` extension 注册 `skills` 工具（runtime-builder.ts L411-435），skills 指令在工具调用时按需注入（`skills` tool execute 返回 SKILL.md 内容），**不写入 system prompt**。

**Charles 设计**：Charles 通过 `_build_enhancement_rules`（context.py L611-647）返回 5 个 rule，作为可选增强层（默认关闭）。当增强层开启时，以下 rule 追加到 `effectiveRules` 末尾：

```python
# context.py L611-647
rules: list[tuple[str, str]] = []

if self._enhancements.get("tools_section"):
    rules.append(("charles-tools-overview", body))     # 英文 title

if self._enhancements.get("mcp_section"):
    rules.append(("charles-mcp-overview", body))        # 英文 title

if self._enhancements.get("always_skills") and self.skills_registry:
    rules.append(("charles-always-skills", body))       # 英文 title

if self._enhancements.get("skills_summary") and self.skills_registry:
    rules.append(("charles-skills-summary", body))      # 英文 title

if self._enhancements.get("memory") and self.memory:
    rules.append(("charles-memory", self.memory))       # 英文 title
```

**字段名语言对比**：

| 元素 | 语言 | 示例 |
|------|------|------|
| rule title（5 个） | **全部英文** | `charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` / `charles-skills-summary` / `charles-memory` |
| `charles-always-skills` body | 中文（来自 SKILL.md `always` 段） | `skills_registry.load_always_instructions()` 返回中文指令 |
| `charles-skills-summary` body | 中文（技能名 + 描述） | `skills_registry.build_summary()` 返回中文摘要 |
| `charles-memory` body | 中文（用户记忆上下文） | `self.memory` 文本 |

**评估**：
- 计划表标注"Charles 中文（部分）/ 语言不同"**误导**。rule title（即"字段名"语义）全部为英文，body 为中文业务文案。
- Cline 无对应概念（skills 通过 extension 注册为工具），不存在"字段名语言"对齐问题。
- Charles 增强层默认关闭，关闭时与 Cline 行为一致（skills 不写入 system prompt）。
- body 中文文案属合理场景偏离（中文量化投研场景）。

### 3.5 rules 字段名：占位符与标题对齐，body 语言由用户决定（5.22.5）

**占位符对比**：

| 元素 | Cline | Charles | 一致性 |
|------|-------|---------|--------|
| 占位符 | `{{CLINE_RULES}}`（system.ts L35） | `{{CHARLES_RULES}}`（charles_system_prompt.py L56） | 一致（前缀不同，语义对齐） |
| 段落位置 | base prompt 第 6 段，`<env>` 之后、`{{CLINE_METADATA}}` 之前 | base prompt 第 6 段，`<env>` 之后、`{{CHARLES_METADATA}}` 之前 | 一致 |
| DEFAULT / YOLO 一致 | 是（system.ts L35 + L67） | 是（charles_system_prompt.py L56 + L89） | 一致 |

**输出格式对比**：

| 元素 | Cline（rule-helpers.ts L246） | Charles（rules_loader.py L716-722） | 一致性 |
|------|-------------------------------|-------------------------------------|--------|
| 顶部标题 | 无 | `# Rules`（英文） | Charles 多出顶部标题（增强） |
| 单条 rule label | `${ruleFilePathRelative}`（相对文件路径，如 `.clinerules/general.md`，英文路径） | `## {file_stem}`（文件 stem，如 `general`，英文 stem） | 格式不同，label 语言一致（英文） |
| 单条 rule body | 规则文件正文（语言由用户决定） | 规则文件正文（语言由用户决定） | 一致 |

**Charles rules 文件 stem 列表**（`agent_config/rules/` 目录）：

| 文件 | stem | 语言 |
|------|------|------|
| `AGENTS.md` | `AGENTS` | 英文（国际通用命名） |
| `general.md` | `general` | 英文 |
| `plan-mode-rules.md` | `plan-mode-rules` | 英文 |
| `research.md` | `research` | 英文 |
| `trading.md` | `trading` | 英文 |

**body 内容语言**：
- Charles `agent_config/rules/*.md` 文件正文均为中文（如 `# 通用规则` / `## 输出格式` / `## 时间基准` / `## 工具调用规范` / `## 股票代码格式`）。
- Cline `.clinerules/*.md` 文件正文语言由用户决定（Cline 官方文档示例为英文）。

**评估**：
- 计划表标注"Charles 中文 / 语言不同"**事实错误**。占位符、`# Rules` 顶部标题、`## {stem}` 二级标题均为英文。
- body 内容语言由用户规则文件决定，非"字段名语言"差异。Charles 默认中文 body 属合理场景偏离（中文量化投研场景）。
- Charles 的 `# Rules` 顶部标题 + `## {stem}` 二级标题结构对 LLM 更友好（明确边界），属 Charles 增强，非对齐缺口。

### 3.6 base prompt 模板主体措辞语言（计划表外补充）

虽不在 P5.22 计划项内，但与本阶段"字段名语言"主题相关，补充说明：

| 元素 | Cline（system.ts） | Charles（charles_system_prompt.py） | 说明 |
|------|-------------------|-------------------------------------|------|
| 身份描述 | `You are Cline, an AI coding agent.`（英文） | `你是 Charles，专业的 AI 投研情报官。`（中文） | 场景差异（通用编码 vs 量化投研） |
| 通用规则标题 | 无独立标题（融入段落） | `## 通用行为规则` / `## 工具调用规则`（中文） | Charles 显式分段 |
| 规则要点 | `Always adhere to existing code conventions...`（英文） | `1. **上下文优先**：...`（中文） | 场景差异 |
| REMEMBER / IMPORTANT 提示 | `REMEMBER, be helpful and proactive!`（英文） | YOLO 模板用 `重要:`（中文） | 场景差异 |

**评估**：base prompt 主体措辞为中文属 Charles 合理场景偏离（面向中文量化投研用户、LLM 通常为中文模型）。Cline base prompt 为英文属其通用编码场景定位。**非字段名语言对齐缺口**，不在 P5.22 计划项范围内。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 System Prompt 字段名语言相关文件检查 nanobot 风格残留：
- `agent/prompts/charles_system_prompt.py`（全文 94 行，base prompt 模板，含 `<env>` 字段名 + 占位符）
- `agent/context.py` 字段名相关代码：
  - `build_charles_system_prompt`（L78-127，纯组装器，占位符替换）
  - `_build_metadata`（L408-452，metadata JSON 字段名 + 文本标记）
  - `_build_environment`（L649-681，废弃方法，中文字段名）
  - `_build_tools_section`（L723-786，工具段中文标题）
  - `_build_mcp_servers_section`（L788-834，MCP 段中文标题）
  - `_build_mode_tag_instructions`（L836-856，mode 标签说明中文标题）
  - `_build_enhancement_rules`（L611-647，增强层英文 rule title）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/prompts/charles_system_prompt.py` | 0 | 0 | 无残留。模板字段名、占位符、`<env>` 标签均对标 Cline `system.ts`，无 nanobot 风格实现 |
| `agent/context.py`（字段名相关代码） | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`（与 Phase 5.1 / 5.4 / 5.8 同一处，非字段名相关） |

### 4.3 残留详情

#### 4.3.1 注释残留（1 处，与 Phase 5.1 / 5.4 / 5.8 同一处）

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

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。不影响运行逻辑。此残留已在 Phase 5.1 / 5.4 / 5.8 报告中记录，本阶段不重复计入字段名独立残留。**与字段名语言无直接关系**（`extra_sections` 是已废弃的"额外段落"参数，非 env / metadata / tools / skills / rules 字段名相关）。

#### 4.3.2 实现逻辑残留（0 处）

经核查 System Prompt 字段名相关全部代码：

- `build_charles_system_prompt`（L78-127）：纯组装器，6 个占位符替换与 Cline `buildClineSystemPrompt` 完全对齐，无 nanobot 风格实现。
- `_build_metadata`（L408-452）：metadata JSON 字段名与 Cline `buildWorkspaceMetadata` 完全对齐，文本标记 `# Workspace Configuration` 与 Cline `WORKSPACE_CONFIGURATION_MARKER` 完全对齐，无 nanobot 风格实现。
- `_build_environment`（L649-681）：废弃方法，中文字段名 + git 字段塞进 env 段。虽与 Cline 设计不一致，但这是早期 Stage 4 实现的 Cline 对标残留（非 nanobot 风格 —— nanobot 的 env 段也是英文且不含 git 字段），且生产路径不调用。**非 nanobot 实现逻辑残留**。
- `_build_tools_section`（L723-786）：Charles 独有增强层，中文标题属场景偏离，非 nanobot 风格实现。
- `_build_mcp_servers_section`（L788-834）：Charles 独有增强层，中文标题属场景偏离，非 nanobot 风格实现。
- `_build_mode_tag_instructions`（L836-856）：对标 Cline `MODE_TAG_INSTRUCTIONS`，中文描述属场景偏离，非 nanobot 风格实现。
- `_build_enhancement_rules`（L611-647）：5 个 rule title 均为英文（`charles-tools-overview` 等），与 Cline extension/tool 系统的英文命名风格一致，非 nanobot 风格实现。

**结论**：System Prompt 字段名相关代码 **无 nanobot 实现逻辑残留**，仅 1 处与 Phase 5.1 / 5.4 / 5.8 共享的注释残留。说明 A1 重构 + L5 重构已彻底清除字段名相关的 nanobot 风格实现逻辑。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**System Prompt 字段名相关代码无类似的实现逻辑残留**，仅 1 处与 Phase 5.1 共享的注释残留 + 1 个死参数（`extra_sections`）。这说明 System Prompt 字段名层面的重构（A1 纯组装器拆分 + L5 metadata 标签对齐）比技能系统更彻底。

### 4.5 注释残留 vs 实现逻辑残留汇总

| 类别 | 数量 | 位置 | 严重程度 | 与字段名关系 |
|---|---|---|---|---|
| 注释残留（字段名相关） | 0 | — | 无 | — |
| 实现逻辑残留（字段名相关） | 0 | — | 无 | — |
| 注释残留（共享，extra_sections） | 1 | context.py L275 | 低 | 无直接关系 |
| 实现逻辑残留（extra_sections 死参数） | 0 | — | 无 | 无直接关系 |

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.22.1 env 字段名（生产路径）**：已对齐为英文，无需修复。
- **5.22.2 metadata 字段名**：已对齐为英文，无需修复。
- **5.22.3 tools 字段名**：Charles 独有增强层，Cline 无对应概念，无需修复。增强层默认关闭，与 Cline 行为一致。
- **5.22.4 skills 字段名**：rule title 已为英文，body 中文属合理场景偏离。增强层默认关闭，无需修复。
- **5.22.5 rules 字段名**：占位符、`# Rules` 顶部标题、`## {stem}` 二级标题均为英文，body 语言由用户决定。无需修复。

### 5.2 优先级 P1（建议处理）

#### P1-1: 删除或改造废弃的 `_build_environment()` 方法

**影响范围**：`agent/context.py` L649-681

**问题**：该方法使用中文字段名（工作目录 / 平台 / 日期 / IDE / Git 分支 / Git 提交 / Git 远端）+ 无编号 + git 字段塞进 env 段，与生产路径（`charles_system_prompt.py` 英文模板）不一致，且被 `tests/test_stage4_context_prompt.py` L133 / L143 / L304 / L322 调用。该方法的存在导致：
- 计划文件 P5.4 / P5.22 描述过时（误以为生产路径使用中文）
- 测试验证的是废弃方法而非生产路径
- 维护成本高（两套 env 段实现）

**修复方案**：
1. **方案 A（推荐）**：删除 `_build_environment()` 方法，同步修改 `tests/test_stage4_context_prompt.py` 中 4 处调用，改为验证 `build_charles_system_prompt()` 替换后的 env 段输出。
2. **方案 B**：保留方法但改写为调用生产路径（`build_charles_system_prompt` 替换 base 模板中的 env 占位符），输出与生产路径一致的英文格式。

**理由**：用户规则"之前完成正确的功能，尽量不要修改"——生产路径已正确，废弃方法属于历史遗留，删除或改造不影响生产功能。此建议与 Phase 5.4 报告 §7.2 P1-1 属同一项，不重复计入。

### 5.3 优先级 P2（可选优化）

#### P2-1: 清理 `extra_sections` 参数的 nanobot 注释

**影响范围**：`agent/context.py` L275、L292、L530-537

**问题**：`extra_sections` 参数已废弃（docstring 明确说"当前无调用方传入"），但保留参数签名和 `_build_rules` 中的处理逻辑（L530-537），且 docstring 提到 nanobot。

**修复方案**：
1. 移除 `__init__` 的 `extra_sections` 参数（需确认无外部调用方）
2. 移除 `_build_rules` 中 L530-537 的 `extra_sections` 处理逻辑
3. 移除 L275 docstring 中的 nanobot 注释

**理由**：用户规则"代码中不要有 fallback"+"不要 gold-plate"，废弃参数应及时清理。但需先确认无外部调用方（如测试代码或其他模块）。此建议与 Phase 5.1 / 5.4 / 5.8 报告属同一项，不重复计入。

### 5.4 优先级 P3（文档修正）

#### P3-1: 更新计划文件 P5.22 对比表

**影响范围**：`AGENT_COMPARISON_PLAN_V2.md` L2207-2217

**问题**：计划文件 P5.22 的对比表存在 2 处事实错误 + 1 处误导性描述：

| 计划项 | 计划表标注 | 实际状态 | 修正建议 |
|--------|----------|---------|---------|
| 5.22.1 env 字段名 | Charles 中文 / L1 差距 | **已对齐（生产路径英文）** | 改为"已对齐；废弃方法 `_build_environment` 中文，但生产路径不调用" |
| 5.22.2 metadata 字段名 | 已对齐 | **已对齐** | 保持 |
| 5.22.3 tools 字段名 | 已对齐 | **N/A（Charles 独有增强层）** | 改为"N/A — Cline 无对应概念，Charles 增强层默认关闭" |
| 5.22.4 skills 字段名 | Charles 中文（部分）/ 语言不同 | **rule title 英文，body 中文（增强层默认关闭）** | 改为"rule title 英文，body 中文业务文案；增强层默认关闭" |
| 5.22.5 rules 字段名 | Charles 中文 / 语言不同 | **占位符、顶部标题、stem 均英文；body 中文** | 改为"占位符 + 标题英文；body 语言由用户规则文件决定" |

---

## 六、验证方法

### 6.1 env 字段名英文化验证（生产路径）

```powershell
# 验证 Charles 生产路径 env 段字段名为英文（对齐 Cline）
python -c "
from agent.prompts.charles_system_prompt import DEFAULT_CHARLES_SYSTEM_PROMPT, YOLO_CHARLES_SYSTEM_PROMPT
assert 'Platform:' in DEFAULT_CHARLES_SYSTEM_PROMPT
assert 'Date:' in DEFAULT_CHARLES_SYSTEM_PROMPT
assert 'IDE:' in DEFAULT_CHARLES_SYSTEM_PROMPT
assert 'Working Directory:' in DEFAULT_CHARLES_SYSTEM_PROMPT
assert '平台' not in DEFAULT_CHARLES_SYSTEM_PROMPT
assert '工作目录' not in DEFAULT_CHARLES_SYSTEM_PROMPT
assert 'Platform:' in YOLO_CHARLES_SYSTEM_PROMPT
print('OK: env 段字段名为英文（生产路径）')
"
```

### 6.2 metadata 字段名对齐验证

```powershell
# 验证 Charles metadata JSON 字段名与 Cline 一致（英文）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern 'latestGitCommitHash|latestGitBranchName|associatedRemoteUrls|"workspaces"|"hint"'
# 预期: 多行匹配（_build_metadata 方法 L432-440）

# 验证文本标记与 Cline 一致
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern 'Workspace Configuration'
# 预期: L450 一行匹配
```

### 6.3 占位符对齐验证

```powershell
# 验证 Charles 占位符与 Cline 数量和语义一致（名称前缀不同）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern '\{\{[A-Z_]+\}\}'
# 预期: 6 个占位符 {{PLATFORM_NAME}} {{CURRENT_DATE}} {{IDE_NAME}} {{CWD}} {{CHARLES_RULES}} {{CHARLES_METADATA}}

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Pattern '\{\{[A-Z_]+\}\}'
# 预期: 6 个占位符 {{PLATFORM_NAME}} {{CURRENT_DATE}} {{IDE_NAME}} {{CWD}} {{CLINE_RULES}} {{CLINE_METADATA}}
```

### 6.4 增强层 rule title 英文验证

```powershell
# 验证 Charles 增强层 rule title 为英文
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern 'charles-(tools|mcp|always|skills|memory)'
# 预期: L625 / L630 / L636 / L642 / L645 共 5 行匹配（全部英文 title）
```

### 6.5 废弃方法中文字段名验证

```powershell
# 验证废弃方法 _build_environment 使用中文字段名（不用于生产路径）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern '工作目录|平台|日期|Git 分支|Git 提交|Git 远端'
# 预期: L666-678 共 7 行匹配（仅废弃方法内）

# 验证生产路径不调用 _build_environment
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern '_build_environment\('
# 预期: 仅 L649 方法定义，无内部调用（生产路径 build() 不调用此方法）
```

### 6.6 rules 段标题英文验证

```powershell
# 验证 Charles rules 输出格式顶部标题为英文
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern '# Rules'
# 预期: L721 一行匹配（"# Rules\n\n" 顶部标题）

# 验证 rules 文件 stem 为英文
Get-ChildItem -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" | ForEach-Object { $_.BaseName }
# 预期: AGENTS / general / plan-mode-rules / research / trading（全部英文）
```

### 6.7 nanobot 残留验证

```powershell
# 在 charles_system_prompt.py 中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无输出

# 在 context.py 中搜索 nanobot（应 1 处注释残留，与 Phase 5.1 同一处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: L275 docstring 1 处
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.22.1 env 字段名 | Charles 中文 / L1 差距 | **已对齐（生产路径英文）**（计划表错误） | 生产路径 `charles_system_prompt.py` env 字段名为英文，与 Cline 一致。计划表描述的"中文"来自废弃方法 `_build_environment`，生产路径不调用。误判来源与 Phase 5.4 同 |
| 5.22.2 metadata 字段名 | 已对齐 | **已对齐** | JSON 字段名 + 文本标记完全一致，均英文 |
| 5.22.3 tools 字段名 | 已对齐 | **N/A（Charles 独有增强层）** | Cline 无对应概念（工具通过 tool definitions 动态注册）。Charles 增强层默认关闭，rule title 英文，body 中文标题属场景偏离。非对齐缺口 |
| 5.22.4 skills 字段名 | Charles 中文（部分）/ 语言不同 | **rule title 英文，body 中文**（计划表误导） | 5 个 rule title 全部英文（`charles-tools-overview` 等）。body 中文为业务文案，非字段名。Cline 无对应概念，增强层默认关闭 |
| 5.22.5 rules 字段名 | Charles 中文 / 语言不同 | **占位符 + 标题英文，body 中文**（计划表错误） | 占位符 `{{CHARLES_RULES}}` 英文；`# Rules` 顶部标题英文；`## {stem}` 二级标题英文（stem 为英文文件名）。body 中文来自中文 rules 文件正文，非字段名语言差异 |

**计划表标注总结**：5 项中 2 项标注错误（5.22.1 / 5.22.5），1 项误导性描述（5.22.4），1 项标注不准确（5.22.3 标"已对齐"但实际 N/A），1 项确认对齐（5.22.2）。计划表 P5.22 整体偏保守，将"body 内容文案语言"误判为"字段名语言"，未反映 L5 重构后 Charles 字段名已与 Cline 英文对齐的成果。误判根源与 Phase 5.4 同：计划表描述基于废弃方法 `_build_environment` 的中文输出，而非生产路径 `charles_system_prompt.py` 的英文模板。

---

## 附录：检查覆盖声明

- Cline `system.ts`：100% 完整审阅（68 行，DEFAULT + YOLO 双模板，含 `<env>` 段字段名 + 6 个占位符）
- Cline `cline.ts`：100% 完整审阅（166 行，重点 L47-86 metadata 字段名 + L110-166 占位符替换）
- Charles `charles_system_prompt.py`：100% 完整审阅（94 行，DEFAULT + YOLO 双模板）
- Charles `context.py` 字段名相关代码：100% 审阅（L78-127 纯组装器 + L408-452 metadata + L611-647 增强层 + L649-681 废弃 env 方法 + L723-786 工具段 + L788-834 MCP 段 + L836-856 mode 标签说明）
- Charles `agent_config/rules/*.md`：100% 审阅 5 个文件的 stem 与 frontmatter
- nanobot 残留检索：`agent/context.py` + `agent/prompts/charles_system_prompt.py` 全量 Grep，共 1 处命中（L275 注释残留，与 Phase 5.1 / 5.4 / 5.8 同一处）
- 计划文件 P5.22 段：L2207-2217 完整审阅，与实际代码交叉验证

本报告未修改任何源码，仅输出审计报告文件。
