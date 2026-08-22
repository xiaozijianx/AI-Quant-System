# Phase 5.9 Skills 概览段对比

> 对比范围：Cline 与 Charles 在 "Skills 概览段"（System Prompt 中向 LLM 暴露技能清单的段落）的实现差异。本阶段聚焦于"段落位置"维度——Skills 概览段是否存在于 System Prompt 中、位于第几段、与 tool description 的关系；以及内容格式（2 列 vs 3 列）、禁用过滤、段落标题等 9 项逐项对标。与 P4.17 (skills_summary 段) 形成"段落级 vs 构建逻辑级"的双维度对照。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 纯组装函数，含 6 个占位符 + effectiveRules 拼接，**无 skills 占位符**）
> - `sdk/packages/shared/src/prompt/system.ts`（`DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT` base 模板，**全文无 Skills 段**）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L714-769（`createSkillsTool`：`Object.defineProperty` 动态 description + `Available skills: ...` 末尾拼接）
> - `sdk/packages/core/src/extensions/tools/types.ts` L155-179（`SkillsExecutorSkillMetadata` 接口 4 字段：id / name / description / disabled）
>
> Charles 源码：
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装函数，6 个占位符 `{{CHARLES_RULES}}` 等）+ L214-889（`SystemPromptBuilder` 编排器类）+ L611-647（`_build_enhancement_rules`：生成 `charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` / `charles-skills-summary` / `charles-memory` 五个 rule）+ L520-528（`_build_rules` 增强层注入到 `{{CHARLES_RULES}}` 占位符末尾）
> - `agent/skills/registry.py` L210-252（`build_summary()`：Markdown 列表 `- {name} ({when_to_use}): {desc}` 三元组）+ L254-263（`build_summary_as_rule()`：包装为 `## charles-skills-summary` rule）
> - `agent/prompts/charles_system_prompt.py`（`DEFAULT_CHARLES_SYSTEM_PROMPT` 模板，含 `{{CHARLES_RULES}}` 占位符）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/skills.py` L101-140（`build_skills_summary()` 原型：XML 格式 `<skills><skill available="..."><name>...</name><description>...</description><location>...</location></skill></skills>`）
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py` L78-85（`# Skills` 段注入 system prompt，作为顶级段而非 rule）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 "Skills 概览段" 的实现。**核心结论：Cline 的 System Prompt 中不存在独立的 Skills 概览段——技能清单仅通过 `skills` 工具 description 末尾追加 `Available skills: name1, name2, ...` 暴露给 LLM；Charles 默认与 Cline 对齐（无独立段），但提供受配置开关控制的 System Prompt 增强层 `## charles-skills-summary` rule（默认关闭），启用后注入三元组 Markdown 列表（name + when_to_use + description）。**

### 核心结论

1. **段落存在性**：
   - **Cline**：**不存在** System Prompt 中的 Skills 概览段。`buildClineSystemPrompt`（cline.ts L110-166）的 6 个占位符中无 skills 专用占位符；`DEFAULT_CLINE_SYSTEM_PROMPT` 模板全文无 Skills 章节；`effectiveRules` 仅含 `rules + MODE_TAG_INSTRUCTIONS + PLAN_MODE_INSTRUCTIONS`，无 skills 段。
   - **Charles**：**条件存在**。默认行为与 Cline 对齐（`enhancements.enabled=False`，不注入）；启用 `agent_config/system_prompt.yaml` 的 `enhancements.enabled: true` + `enhancements.skills_summary: true` 后，作为 rule 追加到 `{{CHARLES_RULES}}` 占位符末尾。

2. **段落位置**：
   - **Cline**：技能清单仅出现在 `skills` 工具的 description 中（definitions.ts L754-766），由 `Object.defineProperty` 动态生成。**不占用 System Prompt token**。
   - **Charles**：双位置——
     - 位置 1（与 Cline 等价）：`skills` 工具 description（skill_tool.py `_build_description()`）
     - 位置 2（Charles 独有）：System Prompt 增强层 `## charles-skills-summary` rule（registry.py L254-263 + context.py L638-642），位于 `{{CHARLES_RULES}}` 占位符内 effectiveRules 末尾（在 `charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` 之后，`charles-memory` 之前）

3. **内容格式**：
   - **Cline**：逗号分隔字符串 `Available skills: pdf, commit, review-pr.`（仅 `name`），追加到工具 description 末尾。可视为"1 列"格式。
   - **Charles 位置 1**：与 Cline 等价（仅 `name`）。
   - **Charles 位置 2**：Markdown 列表，每行一项 `- {name} ({when_to_use}): {desc}`，三字段三元组（可视为"3 列"格式）。计划表标注"2 列 vs 3 列"不准确——Cline 实际为"1 列"（仅 name），Charles 位置 2 为"3 列"。

4. **when_to_use 字段**：
   - **Cline**：不支持。`SkillConfig` / `SkillsExecutorSkillMetadata` 接口均无此字段。
   - **Charles**：支持（`SkillMetadata.when_to_use`，loader.py L81），仅在位置 2 使用。8 个 SKILL.md 配置了该字段。

5. **禁用技能过滤**：
   - **Cline**：是。`.filter((s) => !s.disabled)`（definitions.ts L757）。
   - **Charles**：是。`list_skills()` 过滤 disabled（registry.py L157）。两位置均经过滤。

6. **段落标题与引导语**：
   - **Cline**：无段落标题，仅工具 description 内追加 `Available skills: ...`。
   - **Charles 位置 1**：无段落标题（与 Cline 等价）。
   - **Charles 位置 2**：含 `# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）` 标题 + 两行引导语（强制调用 skills 工具 + 禁止编造数据）。

7. **默认行为**：
   - **Cline**：工具 description 始终包含 `Available skills: ...`（只要有可用技能）。
   - **Charles 位置 1**：始终包含（同 Cline）。
   - **Charles 位置 2**：默认关闭（`enhancements.enabled=False`，context.py L322）。当前 `agent_config/system_prompt.yaml` 不存在，实际未注入。

8. **nanobot 残留**：
   - **注释残留**：4 处（registry.py L2 / L20-22 / L100 共 3 处 + context.py L275 的 `extra_sections` docstring 1 处）。
   - **实现逻辑残留**：1 处完整链路（`build_summary()` → `build_summary_as_rule()` → `_build_enhancement_rules()` L638-642 → `{{CHARLES_RULES}}` 注入），概念源自 nanobot `build_skills_summary()`，格式从 XML 改为 Markdown 列表，新增 `when_to_use` 字段（Charles 独有增强）。

### 一致性总体评估

- **段落位置（System Prompt vs tool description）**：**未对齐**。Cline 无 System Prompt 段；Charles 有受配置开关控制的 System Prompt 增强层（默认关闭）。
- **默认行为**：**已对齐**。Charles 默认关闭 enhancements 时与 Cline 行为一致（技能清单仅通过工具 description 暴露）。
- **工具 description 维度**：**高**。Cline 和 Charles 位置 1 完全等价（仅 name，逗号分隔，disabled 过滤）。
- **System Prompt 段维度（启用时）**：**未对齐**。Charles 位置 2 为三元组 Markdown 列表，Cline 无对应物。
- **段落顺序**：**已对齐**（默认关闭时两者均无 System Prompt 段；启用时 Charles 位置 2 在 rules 末尾，与 nanobot `# Skills` 顶级段降级为 rule 一致）。

### 与计划表标注的差异说明

AGENT_COMPARISON_PLAN_V2.md P5.9 计划表存在以下不准确标注（本报告修正）：

| 计划表标注 | 实际情况 | 修正 |
|----------|---------|------|
| 5.9.1 "表格列数: 2 列 (Cline) vs 3 列 (Charles)" | Cline 无 System Prompt 段；工具 description 仅 name（1 列） | 修正为"Cline 1 列（仅 name，工具 description）/ Charles 位置 1 等价 + 位置 2 三元组（3 列）" |
| 5.9.2 "技能名: 是/是 已对齐" | 工具 description 维度已对齐；System Prompt 段是 Charles 独有 | 修正为"工具 description 维度已对齐；System Prompt 段 Charles 独有" |
| 5.9.3 "description: 是/是 已对齐" | Cline 工具 description 不读取 description 字段（仅 name）；Charles 位置 2 使用 description | 修正为"Cline 工具 description 不使用 description / Charles 位置 2 使用 description" |
| 5.9.4 "when_to_use: 无/是 Charles 额外" | 准确 | 维持原标注 |
| 5.9.5 "禁用技能过滤: 是/是 已对齐" | 准确 | 维持原标注 |
| 5.9.6 "段落位置: 第 7 段/第 7 段 已对齐" | Cline **无** System Prompt 段（不存在第 7 段）；Charles 位置 2 在 `{{CHARLES_RULES}}` 末尾 | 修正为"Cline 无 System Prompt 段 / Charles 位置 2 在 rules 末尾（默认关闭）" |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.9.1 | 表格列数 | **1 列**（仅 `name`）。工具 description getter（definitions.ts L758）`.map((s) => s.name)`，不读取 description。`configuredSkills` 元数据含 description（types.ts L163）但未使用 | **位置 1: 1 列**（仅 `name`，与 Cline 等价）；**位置 2: 3 列**（`name` + `when_to_use` + `description`，registry.py L250） | 未对齐 | Charles 位置 2 多出 when_to_use 列；计划表"2 列 vs 3 列"标注不准确 |
| 5.9.2 | 技能名 | 是。工具 description 末尾追加 `Available skills: {name1}, {name2}, ...`（L760） | 位置 1: 是（与 Cline 等价）；位置 2: 是（registry.py L250 `- {skill.name} ...`） | 高（位置 1）/ 未对齐（位置 2） | 工具 description 维度已对齐；System Prompt 段是 Charles 独有 |
| 5.9.3 | description | **不使用**。工具 description getter 仅 `.map((s) => s.name)`，不读取 `s.description` | 位置 1: 不使用；位置 2: 使用（`skill.description or "(无描述)"`，registry.py L241，截断 120 字符） | 未对齐 | Cline 元数据含 description 但工具 description 不读取；Charles 位置 2 读取 |
| 5.9.4 | when_to_use | **不支持**。`SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillsExecutorSkillMetadata`（types.ts L157-166）均无此字段 | **支持**。`SkillMetadata.when_to_use`（loader.py L81），从 frontmatter 解析（L281-282），8 个 SKILL.md 配置 | 未对齐 | Charles 独有增强，仅位置 2 使用 |
| 5.9.5 | 禁用技能过滤 | 是。`.filter((s) => !s.disabled)`（definitions.ts L757） | 是。`list_skills()` 过滤 disabled（registry.py L157 `[s for s in all_skills if not s.disabled]`） | 高 | 已对齐。两位置均经过滤 |
| 5.9.6 | 段落位置 | **无 System Prompt 段**。`buildClineSystemPrompt`（cline.ts L110-166）6 个占位符无 skills 专用；`DEFAULT_CLINE_SYSTEM_PROMPT` 模板无 Skills 章节；`effectiveRules` 仅含 `rules + MODE_TAG + PLAN_MODE` | **位置 1: 工具 description**（与 Cline 等价）；**位置 2: System Prompt 增强层**，位于 `{{CHARLES_RULES}}` 占位符内 effectiveRules 末尾，作为 `## charles-skills-summary` rule（context.py L638-642），在 `charles-always-skills` 之后、`charles-memory` 之前 | 未对齐 | Cline 无 System Prompt 段；Charles 位置 2 在 rules 末尾（默认关闭）。计划表"第 7 段/第 7 段"标注不准确 |
| 5.9.7 | 段落标题 | 无（工具 description 内追加，无标题） | 位置 1: 无标题；位置 2: `# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）`（registry.py L234） | 未对齐 | Charles 位置 2 含引导性标题 |
| 5.9.8 | 段引导语 | 无（工具 description 内仅 base 字符串含基础指引） | 位置 1: 含基础指引（base 字符串）；位置 2: 含两行强制引导语（registry.py L236-238）：强制调用 skills 工具 + 禁止编造数据 | 未对齐 | Charles 位置 2 引导语更详细，含业务约束 |
| 5.9.9 | 默认行为 | 工具 description 始终包含 name 列表（只要有可用技能） | 位置 1: 始终包含（同 Cline）；位置 2: **默认关闭**（`enhancements.enabled=False`，context.py L322），需显式启用 | 部分 | Charles 位置 2 默认不注入 |

---

## 三、重点差距详细说明

### 3.1 Cline 不存在 System Prompt 中的 Skills 概览段（5.9.6）

这是本阶段最关键的差异。**Cline 的 System Prompt 中不包含任何 Skills 概览段**；技能清单仅通过 `skills` 工具的 description 末尾追加 name 列表暴露给 LLM。

**Cline System Prompt 结构**（cline.ts L138-164）：

```typescript
const basePrompt = mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT;
const effectiveRules = [
    rules,
    MODE_TAG_INSTRUCTIONS,
    mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined,
]
    .filter(Boolean)
    .join("\n\n");

return basePrompt
    .replace("{{PLATFORM_NAME}}", platform)
    .replace("{{CWD}}", workspaceRoot)
    .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
    .replace("{{IDE_NAME}}", ide)
    .replace("{{CLINE_METADATA}}", isCline ? buildWorkspaceMetadata(...) : "")
    .replace("{{CLINE_RULES}}", effectiveRules);
```

**关键点**：
1. 6 个占位符：`{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CLINE_METADATA}}` / `{{CLINE_RULES}}`，**无 skills 专用占位符**。
2. `DEFAULT_CLINE_SYSTEM_PROMPT` 模板全文 Grep `skill|Skills` 0 命中——base prompt 中无 Skills 章节。
3. `effectiveRules` 仅含三段：用户 rules + MODE_TAG + PLAN_MODE，**无 skills 段**。
4. skills 信息暴露路径：`createSkillsTool` 通过 `Object.defineProperty` 在工具 description 末尾追加 `Available skills: ...`。

**对比意义**：Cline 的设计哲学是"技能清单仅作为工具 description 的附属信息"，让 LLM 通过工具签名发现可用技能。这与 Cline 的 on-demand 加载模型一致——LLM 看到工具 description 中的技能名后，调用 `skills` 工具加载详细指令，不在 System Prompt 中预注入摘要。

### 3.2 Charles 的双位置暴露与段落位置（5.9.6）

Charles 在两处暴露技能清单：

**位置 1：工具 description（与 Cline 等价）**

```python
# skill_tool.py _build_description()
skills = self._registry.list_skills()
if skills:
    names = ", ".join(s.name for s in skills)    # ← 仅 name
    return f"{base} 可用技能: {names}。"
```

与 Cline 完全等价：仅 name，逗号分隔，追加到 base description。

**位置 2：System Prompt 增强层 `## charles-skills-summary` rule（Charles 独有）**

```python
# registry.py L210-252
def build_summary(self) -> str:
    skills = self.list_skills()
    # ...
    lines = [
        "# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）",
        "",
        "当用户任务与某个技能匹配时，你必须先调用 skills 工具加载该技能指令...",
        "如果技能指令中包含下载脚本而本地数据不存在，禁止假设数据存在或编造数据...",
        "",
    ]
    for skill in skills:
        # ... 截断 + 换行处理
        lines.append(f"- {skill.name} ({when_to_use}): {desc}")    # ← 三元组
    return "\n".join(lines)

# registry.py L254-263
def build_summary_as_rule(self) -> str:
    summary = self.build_summary()
    if not summary:
        return ""
    return f"## charles-skills-summary\n\n{summary}"

# context.py L638-642
if self._enhancements.get("skills_summary") and self.skills_registry:
    body = self.skills_registry.build_summary()
    if body:
        rules.append(("charles-skills-summary", body))
```

**段落位置**：位置 2 注入到 `{{CHARLES_RULES}}` 占位符内，作为 `## charles-skills-summary` rule。在 `_build_enhancement_rules()`（context.py L611-647）中，5 个增强层 rule 的顺序为：
1. `charles-tools-overview`
2. `charles-mcp-overview`
3. `charles-always-skills`
4. **`charles-skills-summary`** ← 本阶段关注
5. `charles-memory`

即 Skills 概览段位于 effectiveRules 末尾的第 4 个增强层 rule，整体在 `{{CHARLES_RULES}}` 占位符内。

**关键点**：
1. 位置 1（工具 description）与 Cline 完全等价——仅 name，逗号分隔。
2. 位置 2（System Prompt 段）是 Charles 独有——Markdown 列表，每行三元组。
3. 位置 2 含强制引导语（强制调用 skills 工具 + 禁止编造数据），是 Charles 业务约束（量化场景严谨性）。
4. 位置 2 默认关闭（`enhancements.enabled=False`）。

### 3.3 表格列数差异（5.9.1 / 5.9.3 / 5.9.4）

**Cline 工具 description 实际为"1 列"**（仅 name）：

```typescript
// definitions.ts L756-758
const skills = executor.configuredSkills
    ?.filter((s) => !s.disabled)
    .map((s) => s.name);                    // ← 仅 name，不读取 description
```

虽然 `SkillsExecutorSkillMetadata`（types.ts L157-166）含 `id` / `name` / `description` / `disabled` 四字段，但工具 description getter（L758）**仅 `.map((s) => s.name)`**，description 字段未被使用。

**Charles 位置 2 为"3 列"**（name + when_to_use + description）：

```python
# registry.py L250
lines.append(f"- {skill.name} ({when_to_use}): {desc}")
```

**计划表"2 列 vs 3 列"标注不准确**：Cline 工具 description 实际为 1 列（仅 name），非 2 列（name + description）。Charles 位置 2 为 3 列。

### 3.4 when_to_use 字段是 Charles 独有增强（5.9.4）

**Cline 不支持 when_to_use 字段**：
- `SkillConfig` 接口（user-instruction-config-loader.ts L42-48）仅 5 字段：`name` / `description` / `instructions` / `disabled` / `keywords`。
- `SkillsExecutorSkillMetadata` 接口（types.ts L157-166）仅 4 字段：`id` / `name` / `description` / `disabled`。
- 无 `when_to_use` 字段定义。

**Charles 支持 when_to_use 字段**：
- `SkillMetadata.when_to_use`（loader.py L81）：`when_to_use: str = ""`，注释"Phase P5: 何时使用此技能 — 供 skills_summary 表格的'何时使用'列填充"。
- frontmatter 解析（loader.py L281-282）：`when_to_use = str(frontmatter.get("when_to_use", ""))`。
- 8 个实际技能配置了该字段（agent_config/skills/*/SKILL.md L4），如：
  - `read-pdf/SKILL.md` L4：`when_to_use: "用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"`
  - `stock-price/SKILL.md` L4：`when_to_use: "用户询问股价/涨跌幅/K线/成交量/近期走势时"`

**字段用途**：仅在位置 2（System Prompt 段）中使用，工具 description（位置 1）不使用。

**字段溯源**：注释标注"对标 Cline SKILL.md frontmatter 的 description 字段中隐含的'何时使用'语义"（loader.py L80），但实际 Cline 无此字段，Charles 的"对标"表述不准确。该字段是 Charles 独有增强，灵感可能来自 Cline description 字段的语义拆分（将"何时使用"与"技能描述"分离）。

### 3.5 禁用技能过滤已对齐（5.9.5）

**Cline**：
```typescript
// definitions.ts L756-758
const skills = executor.configuredSkills
    ?.filter((s) => !s.disabled)         // ← disabled 过滤
    .map((s) => s.name);
```

**Charles**：
```python
# registry.py L140-158
def list_skills(self) -> list[SkillMetadata]:
    # ...
    all_skills = [s for s in all_skills if not s.disabled]   # ← disabled 过滤
    return all_skills
```

**等价性**：两者均在生成技能清单前过滤 `disabled=True` 的技能。Charles 的 `list_skills()` 是 `build_summary()` 和 `_build_description()` 的共同数据源，确保两位置均经过滤。

### 3.6 段落标题与引导语差异（5.9.7 / 5.9.8）

**Cline**：无段落标题，工具 description 内仅 base 字符串含基础指引（"When users ask you to perform tasks, check if any available skills match..."，definitions.ts L726-731）。

**Charles 位置 2**：含完整段落标题 + 两行强制引导语（registry.py L234-238）：

```
# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）

当用户任务与某个技能匹配时，你必须先调用 skills 工具加载该技能指令，然后严格按照指令执行。
如果技能指令中包含下载脚本而本地数据不存在，禁止假设数据存在或编造数据，必须立即执行脚本获取。
```

**目的**：
1. 标题明确说明"这些不是可直接调用的工具"——防止 LLM 误把技能名当工具名调用。
2. 强制 LLM 调用 `skills` 工具加载指令（对齐 Cline 的 "blocking requirement" 语义）。
3. 禁止 LLM 跳过 skills 工具直接调用技能目录下的脚本（Charles 业务约束）。
4. 禁止 LLM 在数据不存在时编造数据（量化场景的严谨性约束）。

**对比意义**：Charles 的引导语是业务增强（量化场景需要严格约束 LLM 行为），Cline 和 nanobot 均无此详细引导语。这是 Charles 独有的业务约束，非 nanobot 残留。

---

## 四、nanobot 残留专项检查

### 4.1 实现逻辑残留（1 处，核心残留）

Charles 的 System Prompt Skills 概览段（位置 2）是**完整的 nanobot 实现逻辑残留**，非纯注释残留。溯源对比如下：

| 组件 | nanobot 实现 | Charles 实现 | 残留性质 |
|------|-------------|-------------|---------|
| 摘要构建函数 | `nanobot/agent/skills.py` L101-140 `build_skills_summary()`：遍历 `list_skills(filter_unavailable=False)`，构建 XML `<skills><skill available="..."><name>...</name><description>...</description><location>...</location></skill></skills>` | `agent/skills/registry.py` L210-252 `build_summary()`：遍历 `list_skills()`，构建 Markdown 列表 `- {name} ({when_to_use}): {desc}` | **概念复刻 + 格式适配**：从 XML 改为 Markdown 列表；新增 when_to_use 字段（Charles 独有，nanobot 无） |
| System Prompt 注入 | `nanobot/agent/context.py` L78-85：`parts.append(f"# Skills\n\nThe following skills extend your capabilities...\n\n{skills_summary}")`，作为**顶级段**注入 | `agent/skills/registry.py` L254-263 `build_summary_as_rule()` + `agent/context.py` L638-642：包装为 `## charles-skills-summary` rule，经 `{{CHARLES_RULES}}` 注入，作为 **rule** 而非顶级段 | **复刻 + 适配**：从 `# Skills` 顶级段降级为 `## charles-skills-summary` rule（适配 Cline 的 base + rules 两层结构） |
| 摘要字段 | nanobot：`name` + `description` + `location`（路径）+ `available`（依赖检查）+ `requires`（缺失依赖） | Charles：`name` + `when_to_use` + `description`（无 location / available / requires） | **字段调整**：Charles 移除 location / available / requires（无依赖检查机制），新增 when_to_use（Charles 独有增强） |
| 依赖检查 | nanobot：`_check_requirements(skill_meta)` 检查 bins / env，标记 `available="true/false"` | Charles：**无依赖检查**。所有技能均视为可用（disabled 过滤后） | **功能缺失**：Charles 不支持 nanobot 的 requires 字段 |
| 段标题 | nanobot：`# Skills`（顶级段） | Charles：`# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）`（rule 内的子标题） | **降级**：从 System Prompt 顶级段降为 rule 内子标题 |

**残留判定依据**：
1. **Cline 无等价物**：Cline 的 `buildClineSystemPrompt`（cline.ts L110-166）6 个占位符无 skills 专用；`DEFAULT_CLINE_SYSTEM_PROMPT` 模板全文无 Skills 章节；`createSkillsTool` 仅在工具 description 追加 name 列表。
2. **nanobot 有原型**：nanobot `build_skills_summary()`（L101-140）+ `# Skills` 段注入（context.py L78-85）是完整实现。
3. **Charles docstring 自证**：`registry.py` L20-22 docstring 明确标注"对标 nanobot: build_skills_summary(): XML 格式技能列表"。
4. **实现完整可用**：Charles 的 Skills 概览段（位置 2）非 dead code，受配置开关控制，默认关闭但可启用。8 个实际技能配置了 when_to_use 字段。
5. **概念链路完整**：`build_summary()` → `build_summary_as_rule()` → `_build_enhancement_rules()` → `{{CHARLES_RULES}}` 注入 → System Prompt，完整链路可用。

### 4.2 注释残留（4 处，2 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/skills/registry.py` | L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 标题（同时引用 Cline 和 nanobot） |
| `agent/skills/registry.py` | L20-22 | `对标 nanobot:\n    - build_skills_summary(): XML 格式技能列表\n    - get_always_skills(): always=True 的技能` | docstring 对标说明（明确标注 build_skills_summary 源自 nanobot） |
| `agent/skills/registry.py` | L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | class docstring 标题 |
| `agent/context.py` | L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` | docstring 标注 `extra_sections` 参数的历史来源（nanobot 风格） |

**注释残留小结**：
- 3 处集中在 `agent/skills/registry.py`，均为 docstring 中的"对标 nanobot"说明。
- 1 处在 `agent/context.py` L275，是 `extra_sections` 死参数的 docstring 标注（与 Skills 概览段无直接关联，但属同一文件的 nanobot 注释残留）。
- `agent/context.py` 的 Skills 概览段注入逻辑（L638-642）用 Cline 风格的 `effectiveRules` + `enhancements` 包装，无 nanobot 字面引用。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 实现逻辑残留（Skills 概览段位置 2） | 1 处（含 2 个方法 + 1 个字段 + 1 个配置开关 + 1 个注入路径） | **中** | Skills 概览段默认关闭，不影响默认运行时行为；但概念源自 nanobot，与 Cline 的"工具 description only"设计哲学冲突 |
| 注释残留（nanobot 对标说明） | 4 处（registry.py 3 处 + context.py 1 处） | 低 | 可保留作为设计溯源参考，或统一清理 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（4 处）：仅在 docstring 中引用 "nanobot" 字样，不影响运行时行为。如 `registry.py` L20-22 `对标 nanobot: build_skills_summary(): XML 格式技能列表`，这是设计溯源说明，删除后功能不变。

**实现逻辑残留**（1 处）：Skills 概览段位置 2 的完整实现链路，**影响运行时行为**（启用时）：
- `SkillMetadata.when_to_use` 字段（loader.py L81）—— 数据结构残留（Charles 独有，非直接源自 nanobot，但服务于 nanobot 风格的 summary 段）
- `_parse_skill_file` 中 `when_to_use = str(frontmatter.get("when_to_use", ""))`（loader.py L281-282）—— 解析逻辑残留
- `build_summary()` 方法（registry.py L210-252）—— 构建逻辑残留（概念源自 nanobot，格式适配）
- `build_summary_as_rule()` 方法（registry.py L254-263）—— 包装逻辑残留（Charles 适配，无 nanobot 等价物）
- `_build_enhancement_rules()` 中 `charles-skills-summary` rule 生成（context.py L638-642）—— 注入逻辑残留
- `_load_enhancements()` 中 `skills_summary` 开关（context.py L323 / L340）—— 配置逻辑残留
- `agent_config/skills/*/SKILL.md` L4（8 个技能的 `when_to_use` 字段）—— 实际配置残留

**关键区别**：若删除注释残留，功能不变；若删除实现逻辑残留，Skills 概览段位置 2 不再注入 System Prompt，Charles 行为向 Cline 对齐（技能清单仅通过工具 description 暴露，仅 name）。

### 4.5 when_to_use 字段的残留性质

`when_to_use` 字段是 Charles 独有增强，**非直接源自 nanobot**（nanobot 的 `build_skills_summary()` 使用 `name` + `description` + `location` + `available` + `requires` 五字段，无 `when_to_use`）。但该字段**服务于 nanobot 风格的 summary 段**——若移除 nanobot 风格的 System Prompt summary 段，`when_to_use` 字段将失去主要用途（仅在工具 description 中不使用）。

因此，`when_to_use` 字段属于"**为 nanobot 风格 summary 段服务的 Charles 独有增强**"，其残留性质为"实现逻辑残留的配套字段"，建议与 summary 段一同评估保留或移除。

---

## 五、修复建议

### 5.1 高优先级（P0）

无。Skills 概览段位置 2 默认关闭（`enhancements.enabled=False`），不影响默认运行时行为。且 `agent_config/system_prompt.yaml` 不存在，实际未注入 System Prompt。

### 5.2 中优先级（P1）

1. **修正 docstring 溯源标注**（registry.py L20-22）：
   - 当前：`对标 nanobot: build_skills_summary(): XML 格式技能列表`
   - 问题：Charles 的 `build_summary()` 实际是 Markdown 列表格式，非 XML；且新增了 `when_to_use` 字段（nanobot 无）。docstring 标注不准确，可能误导读者认为 Charles 1:1 复刻 nanobot XML 格式。
   - 建议改为：`设计参考: nanobot build_skills_summary()（概念复刻，格式从 XML 改为 Markdown 列表，新增 when_to_use 字段为 Charles 独有增强）`

2. **修正 loader.py L80 注释**（when_to_use 字段溯源）：
   - 当前：`# 对标 Cline SKILL.md frontmatter 的 description 字段中隐含的"何时使用"语义`
   - 问题：Cline 无 when_to_use 字段，"对标 Cline"表述不准确。
   - 建议改为：`# Charles 独有增强：何时使用此技能，供 Skills 概览段的"何时使用"列填充。Cline 和 nanobot 均无此字段。`

3. **评估 Skills 概览段位置 2 的保留必要性**：
   - **保留方案**：若 Charles 需要在 System Prompt 中向 LLM 暴露技能的"何时使用"信息（提升技能匹配准确率），可保留位置 2。但应在 docstring 中明确说明"这是 Charles 独有增强，概念源自 nanobot，Cline 无等价物"。
   - **移除方案**：若严格对齐 Cline 的"工具 description only"设计哲学，应移除 `build_summary()` / `build_summary_as_rule()` 方法、`_build_enhancement_rules()` 中的 `charles-skills-summary` rule 生成、`_load_enhancements()` 中的 `skills_summary` 开关、`SkillMetadata.when_to_use` 字段及其 frontmatter 解析、以及 8 个 SKILL.md 的 `when_to_use` 配置。
   - **建议**：保留方案更务实（when_to_use 字段对量化场景的技能匹配有业务价值），但需修正 docstring 避免"对标 Cline/nanobot"的误导性表述。

4. **解决信息冗余问题**（位置 1 与位置 2）：
   - Charles 位置 1（工具 description）和位置 2（System Prompt 段）均列出技能 name，启用位置 2 时存在信息冗余。
   - 建议在位置 2 中移除 name 字段（仅保留 when_to_use + description），或在位置 1 中移除 name 列表（仅保留位置 2 的详细信息）。
   - 或在位置 2 的引导语中明确说明"详细技能列表见下方，简要列表见 skills 工具"，让 LLM 理解两处信息的层级关系。

### 5.3 低优先级（P2）

5. **nanobot 注释统一**（4 处）：可选择保留作为设计溯源，或统一清理为仅引用 Cline 对标位置。其中 `context.py` L275 的 `extra_sections` 死参数 docstring 可与死参数本身一同在未来 major 版本移除。

6. **Skills 概览段 token 成本监控**：若启用位置 2，应在 `SystemPromptBuilder` 中记录该段的 token 占用，便于调试 System Prompt 过长问题。当前 `estimate_tokens()`（context.py L897-910）已支持 token 估算，但未针对 Skills 概览段单独统计。

7. **build_tool_hint() 方法清理**（registry.py L265-270）：`build_tool_hint()` 方法返回 None 且注释说明"不再重复"，但方法本身存在。若确认无调用方，可移除以减少代码噪音。

8. **补充 nanobot 的依赖检查功能**（功能缺失）：nanobot 的 `build_skills_summary()` 含 `available` / `requires` 字段检查技能依赖（bins / env）。Charles 不支持依赖检查。若需要（如某些技能依赖特定 Python 包或环境变量），可参考 nanobot `_check_requirements()` 实现。

---

## 六、验证方法建议

### 6.1 Cline 无 System Prompt Skills 概览段验证

1. **Cline buildClineSystemPrompt 无 skills 占位符**：
   ```
   Grep "skill|Skills" third_party/cline/sdk/packages/shared/src/prompt/cline.ts
   ```
   预期：0 命中（cline.ts 中无 skills 相关占位符或段）

2. **Cline base prompt 模板无 Skills 章节**：
   ```
   Grep "skill|Skills" third_party/cline/sdk/packages/shared/src/prompt/system.ts
   ```
   预期：0 命中（DEFAULT_CLINE_SYSTEM_PROMPT / YOLO_CLINE_SYSTEM_PROMPT 模板中无 Skills 章节）

3. **Cline 工具 description 仅 name**：
   ```
   Grep "s\.name|\.name" third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts
   ```
   预期：命中 L758 `.map((s) => s.name)`，无 `.map((s) => s.description)` 或类似

4. **Cline 无 build_summary 函数**：
   ```
   Grep "build_summary|buildSummary|skills_summary|skillsSummary" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中（Cline 无此函数）

5. **Cline SkillConfig 无 when_to_use 字段**：
   ```
   Grep "when_to_use|whenToUse" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中

### 6.2 Charles Skills 概览段验证

1. **Charles 工具 description 仅 name（位置 1）**：
   ```python
   from agent.skills.skill_tool import SkillsTool
   from agent.skills.registry import SkillRegistry
   registry = SkillRegistry(skills_dir="agent_config/skills")
   registry.discover()
   tool = SkillsTool(registry)
   desc = tool.description
   assert "可用技能:" in desc
   assert "write-report" in desc
   # 验证 description 中不含 when_to_use
   assert "何时使用" not in desc
   ```

2. **Charles System Prompt 段含三元组（位置 2）**：
   ```python
   from agent.skills.registry import SkillRegistry
   registry = SkillRegistry(skills_dir="agent_config/skills")
   registry.discover()
   summary = registry.build_summary()
   assert "# 技能目录" in summary
   assert "write-report" in summary
   # 验证三元组格式
   assert "- write-report (" in summary  # name + (when_to_use)
   assert "):" in summary  # ): description
   ```

3. **Charles 默认关闭验证**：
   ```python
   from agent.context import SystemPromptBuilder
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-skills-summary" not in prompt  # 默认关闭
   ```

4. **Charles 启用后注入验证**：
   ```python
   # 创建 agent_config/system_prompt.yaml 启用增强层
   # enhancements:
   #   enabled: true
   #   skills_summary: true
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-skills-summary" in prompt
   assert "write-report" in prompt
   assert "read-pdf" in prompt
   ```

5. **段落位置验证**（位置 2 在 rules 末尾，charles-always-skills 之后）：
   ```python
   # 启用 enhancements 后
   prompt = builder.build()
   # 验证顺序: charles-always-skills 在 charles-skills-summary 之前
   idx_always = prompt.find("## charles-always-skills")
   idx_summary = prompt.find("## charles-skills-summary")
   idx_memory = prompt.find("## charles-memory")
   assert 0 < idx_always < idx_summary < idx_memory
   ```

### 6.3 when_to_use 字段验证

1. **SkillMetadata.when_to_use 字段存在**：
   ```python
   from agent.skills.loader import SkillMetadata
   meta = SkillMetadata(name="test")
   assert hasattr(meta, "when_to_use")
   assert meta.when_to_use == ""  # 默认空字符串
   ```

2. **frontmatter 解析 when_to_use**：
   ```python
   from agent.skills.loader import SkillLoader
   loader = SkillLoader(skills_dir="agent_config/skills")
   skills = loader.list_skills()
   for s in skills:
       if s.name == "read-pdf":
           assert s.when_to_use != ""
           assert "年报" in s.when_to_use or "公告" in s.when_to_use
           break
   ```

3. **8 个技能配置 when_to_use**：
   ```
   Grep "^when_to_use:" agent_config/skills/
   ```
   预期：命中 8 个 SKILL.md 文件

### 6.4 nanobot 残留验证

1. **实现逻辑残留验证**：
   ```
   Grep "build_summary|build_summary_as_rule|charles-skills-summary" agent/
   ```
   预期：命中 `agent/skills/registry.py` L210/L254 + `agent/context.py` L638-642

2. **nanobot 溯源验证**：
   ```
   Grep "build_skills_summary" third_party/charles_bundle/nanobot-main/
   ```
   预期：命中 `nanobot/agent/skills.py` L101（原型）+ `nanobot/agent/context.py` L78（注入）

3. **注释残留验证**：
   ```
   Grep "nanobot" agent/skills/registry.py
   Grep "nanobot" agent/context.py
   ```
   预期：registry.py 命中 L2 / L20-22 / L100（3 处 docstring）；context.py 命中 L275（1 处 docstring，`extra_sections` 死参数标注）

### 6.5 计划表标注修正验证

1. **Cline 工具 description 不含 description 字段**：
   ```
   Grep "s\.description|\.description" third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts
   ```
   预期：0 命中（工具 description getter 不读取 description 字段）

2. **Cline 无 System Prompt Skills 概览段**：
   ```
   Grep "skills_summary|skillsSummary|charles-skills-summary" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中

---

## 七、与 P4.17 skills_summary 段对比的关联

P4.17（skills_summary 段）与本阶段（P5.9 Skills 概览段）形成"构建逻辑级 vs 段落级"的双维度对照：

| 维度 | P4.17（skills_summary 段） | P5.9（Skills 概览段） |
|------|--------------------------|---------------------|
| 对比视角 | **构建逻辑级**：聚焦 `build_summary()` 函数的实现细节（字段、格式、截断、动态构建） | **段落级**：聚焦 Skills 概览段在 System Prompt 中的位置、存在性、段落顺序 |
| 核心问题 | Charles 如何构建 skills_summary 内容（3 列 vs 2 列、when_to_use 字段） | Charles 是否在 System Prompt 中有 Skills 概览段（位置 1 vs 位置 2） |
| 对比维度 | 字段、格式、截断、动态构建、token 预算 | 段落存在性、段落位置、段落标题、引导语 |
| 共同结论 | Cline 无 System Prompt skills_summary 段；Charles 有受配置开关控制的 System Prompt 增强层（默认关闭） | 同左 |
| nanobot 残留 | 实现逻辑残留 1 处（完整链路）+ 注释残留 3 处 | 实现逻辑残留 1 处（同一链路）+ 注释残留 4 处（含 context.py L275） |

**衔接关系**：
- P4.17 §3.1 已确认"Cline 不存在独立的 skills_summary 段"；本阶段（P5.9）从段落位置维度进一步确认：Cline 的 `buildClineSystemPrompt` 6 个占位符无 skills 专用，`DEFAULT_CLINE_SYSTEM_PROMPT` 模板无 Skills 章节。
- P4.17 §3.2 已确认 Charles 的双位置暴露；本阶段进一步明确位置 2 在 `{{CHARLES_RULES}}` 占位符内的具体段落顺序（在 `charles-always-skills` 之后、`charles-memory` 之前）。
- P4.17 §4.1 已确认 skills_summary 段是 nanobot 实现逻辑残留；本阶段从段落降级角度补充：nanobot 的 `# Skills` 顶级段在 Charles 中降级为 `## charles-skills-summary` rule（适配 Cline 的 base + rules 两层结构）。

**本阶段新增发现**（P4.17 未覆盖）：
1. **段落顺序明确**：位置 2 在 `{{CHARLES_RULES}}` 占位符内 effectiveRules 末尾，作为 5 个增强层 rule 的第 4 个（在 `charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` 之后，`charles-memory` 之前）。
2. **计划表"第 7 段/第 7 段"标注不准确**：Cline 无 System Prompt 段，不存在"第 7 段"；Charles 位置 2 在 rules 末尾（默认关闭）。
3. **段落标题与引导语是 Charles 业务增强**：`# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）` 标题 + 两行强制引导语（强制调用 skills 工具 + 禁止编造数据），是 Charles 量化场景的业务约束，Cline 和 nanobot 均无此详细引导语。
4. **context.py L275 的 nanobot 注释残留**：`extra_sections` 死参数的 docstring 标注（与 Skills 概览段无直接关联，但属同一文件的 nanobot 注释残留），P4.17 未提及，本阶段补充。

---

## 八、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.9.1 表格列数 | 2 列 (Cline) vs 3 列 (Charles) | **修正**：1 列 (Cline 工具 description) / 位置 1 等价 + 位置 2 三元组 (Charles) | Cline 工具 description 仅 name（1 列），非 2 列 |
| 5.9.2 技能名 | 是/是 已对齐 | **部分修正**：工具 description 维度已对齐；System Prompt 段 Charles 独有 | 位置 1 等价；位置 2 是 Charles 独有 |
| 5.9.3 description | 是/是 已对齐 | **修正**：Cline 工具 description 不使用 description / Charles 位置 2 使用 | Cline 工具 description getter 仅读取 name |
| 5.9.4 when_to_use | 无/是 Charles 额外 | **准确** | Charles 独有增强，仅位置 2 使用 |
| 5.9.5 禁用技能过滤 | 是/是 已对齐 | **准确** | 两者均过滤 disabled |
| 5.9.6 段落位置 | 第 7 段/第 7 段 已对齐 | **修正**：Cline 无 System Prompt 段 / Charles 位置 2 在 rules 末尾（默认关闭） | Cline 不存在"第 7 段"；Charles 位置 2 受配置开关控制 |

**计划表标注总结**：6 项中 2 项标注准确（5.9.4 / 5.9.5），4 项标注需修正（5.9.1 / 5.9.2 / 5.9.3 / 5.9.6）。计划表 P5.9 整体未反映"Cline 无 System Prompt Skills 概览段"这一核心事实，将 Cline 的工具 description 暴露误标为"System Prompt 第 7 段"。
