# Phase 4.17 skills_summary 段对比

> 对比范围：Cline 与 Charles 在 skills_summary 段（向 LLM 暴露技能清单的摘要段）的实现差异，重点对比段位置（System Prompt 增强层 vs 工具 description）、格式（列表 vs 逗号分隔字符串）、内容字段（name + description + when_to_use 三元组 vs 仅 name）、token 预算、动态构建机制；nanobot 残留专项检查（严格区分"注释残留"与"实现逻辑残留"）。
>
> 本阶段深入对比 P4.1 已发现的"Charles 工具 description 与 Cline 工具 description 等价（仅列 name）"和 P4.16 发现的"Charles 独有 System Prompt 增强层注入"在 skills_summary 维度的具体差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L714-769（`createSkillsTool`，含 `Object.defineProperty` 动态 description + `Available skills: ...` 末尾拼接）
> - `sdk/packages/core/src/extensions/tools/types.ts` L155-179（`SkillsExecutorSkillMetadata` 接口 4 字段：id / name / description / disabled + `SkillsExecutorWithMetadata` 含 `configuredSkills` getter）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L75-93（`getConfiguredSkillsFromWatcher` 含 description 字段）+ L208-215（`configuredSkills` getter 返回元数据列表）+ L95-104（`listAvailableSkillNames` 仅返回 name 列表）
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L42-48（`SkillConfig` 接口仅 5 字段：name / description / instructions / disabled / keywords，无 when_to_use）
>
> Charles 源码：
> - `agent/skills/registry.py` L210-252（`build_summary()`：Markdown 列表 `- {name} ({when_to_use}): {desc}`）+ L254-263（`build_summary_as_rule()`：包装为 `## charles-skills-summary` rule）+ L265-270（`build_tool_hint()`：返回 None）
> - `agent/skills/skill_tool.py` L80-81 + L225-253（`_build_description()`：工具 description 末尾拼接 `可用技能: {names}`，与 Cline 等价）
> - `agent/skills/loader.py` L79-81（`SkillMetadata.when_to_use` 字段定义）+ L281-282（frontmatter `when_to_use` 字段解析）
> - `agent/context.py` L304-346（`_load_enhancements` 配置默认 `skills_summary: True`）+ L520-528（`_build_rules` 增强层注入）+ L638-642（`_build_enhancement_rules` 中 `charles-skills-summary` rule 生成）
> - `agent_config/system_prompt.yaml` L7（`skills_summary: true` 子开关默认值）
> - `agent_config/skills/*/SKILL.md` L4（8 个技能配置 `when_to_use` 字段）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/skills.py` L101-140（`build_skills_summary()` 原型：XML 格式 `<skills><skill available="..."><name>...</name><description>...</description><location>...</location></skill></skills>`）
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py` L78-85（`# Skills` 段注入 system prompt）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在"skills_summary 段"（向 LLM 暴露可用技能清单的摘要信息）的实现。**核心结论：Cline 不存在独立的 skills_summary 段；Charles 存在两处暴露点——工具 description（与 Cline 等价，仅 name）和 System Prompt 增强层 `## charles-skills-summary` rule（Charles 独有，含 name + when_to_use + description 三元组）。** 后者源自 nanobot `build_skills_summary()` 设计模式，是完整的 nanobot 实现逻辑残留（格式从 XML 改为 Markdown 列表）。

### 核心结论

1. **skills_summary 段位置**：
   - **Cline**：仅在 `skills` 工具 description 中暴露技能清单（definitions.ts L754-766），追加 `Available skills: name1, name2, ...` 逗号分隔字符串。**无 System Prompt 独立段**。
   - **Charles**：双位置暴露——
     - 位置 1（与 Cline 等价）：`skills` 工具 description（skill_tool.py L225-253），追加 `可用技能: name1, name2, ...`。
     - 位置 2（Charles 独有）：System Prompt 增强层 `## charles-skills-summary` rule（registry.py L254-263 + context.py L638-642），Markdown 列表格式。

2. **格式**：
   - **Cline**：逗号分隔字符串 `Available skills: pdf, commit, review-pr.`，附加在工具 description 末尾。
   - **Charles 位置 1**：逗号分隔字符串 `可用技能: write-report, read-pdf, ...。`，与 Cline 等价。
   - **Charles 位置 2**：Markdown 列表，每行一项 `- {name} ({when_to_use}): {desc}`（registry.py L250）。

3. **内容字段**：
   - **Cline**：仅 `name`（definitions.ts L758 `.map((s) => s.name)`）。虽然 `configuredSkills` 元数据含 `description` 字段（types.ts L164），但工具 description getter 不读取 description。
   - **Charles 位置 1**：仅 `name`（skill_tool.py L248 `", ".join(s.name for s in skills)`）。
   - **Charles 位置 2**：`name` + `when_to_use` + `description` 三元组（registry.py L250）。

4. **when_to_use 字段**：
   - **Cline**：**不支持**。`SkillConfig` 接口（user-instruction-config-loader.ts L42-48）和 `SkillMetadata` 接口（apps/vscode/src/shared/skills.ts L1-17）均无 `when_to_use` 字段。
   - **Charles**：**支持**。`SkillMetadata.when_to_use`（loader.py L81），从 frontmatter 解析（loader.py L281-282）。8 个实际技能配置了该字段（agent_config/skills/*/SKILL.md L4）。

5. **token 预算**：
   - **Cline**：极小——仅 name 列表追加到工具 description，每技能约 2-3 tokens。无 System Prompt 占用。
   - **Charles 位置 1**：与 Cline 等价。
   - **Charles 位置 2**：较大——每技能约 30-50 tokens（registry.py L10 docstring 声称 ~100 tokens/技能，含 name + when_to_use + description 三段）。8 个技能约 240-400 tokens 注入 System Prompt。

6. **动态构建**：
   - **Cline**：`Object.defineProperty(tool, "description", { get() {...} })`（definitions.ts L754-766），每次 runtime 读取 description 时重新求值。
   - **Charles 位置 1**：`@property description` 调用 `_build_description()`（skill_tool.py L80-81），每次访问重新求值。
   - **Charles 位置 2**：`SystemPromptBuilder.build()` → `_build_rules()` → `_build_enhancement_rules()` → `registry.build_summary()`（context.py L638-642），每次构建 System Prompt 时重新加载。

7. **默认行为**：
   - **Cline**：工具 description 始终包含 `Available skills: ...`（只要有可用技能）。
   - **Charles 位置 1**：始终包含 `可用技能: ...`。
   - **Charles 位置 2**：**默认关闭**（`enhancements.enabled=False`，context.py L322）。需在 `agent_config/system_prompt.yaml` 显式启用 `enhancements.enabled: true` 且 `enhancements.skills_summary: true` 才注入。当前配置文件不存在，实际未注入。

8. **nanobot 残留**：
   - **注释残留**：3 处（registry.py L2 / L20-22 / L100），均为 docstring 中"对标 nanobot build_skills_summary()"溯源说明。
   - **实现逻辑残留**：1 处（完整链路），`build_summary()` + `build_summary_as_rule()` + `context.py` L638-642 注入逻辑。概念源自 nanobot（"构建技能摘要注入 system prompt"），但格式从 XML 改为 Markdown 列表，并新增 `when_to_use` 字段（Charles 独有增强，nanobot 和 Cline 均无）。

### 一致性总体评估

- **工具 description 暴露**：**高**。Cline 和 Charles 均在工具 description 末尾追加 name 列表，格式和语义等价。
- **System Prompt skills_summary 段**：**未对齐**。Cline 无此段，Charles 有 `## charles-skills-summary` rule（默认关闭）。
- **when_to_use 字段**：**未对齐**。Cline 不支持，Charles 支持（仅位置 2 使用）。
- **token 预算**：**未对齐**。Cline 无 System Prompt 占用，Charles 位置 2 占用 240-400 tokens（启用时）。
- **动态构建机制**：**等价**。均为每次访问重新求值。

### 与计划表标注的差异说明

AGENT_COMPARISON_PLAN_V2.md P4.17 计划表存在以下不准确标注（本报告修正）：

| 计划表标注 | 实际情况 | 修正 |
|----------|---------|------|
| 4.17.1 "summary 列数: 2 列 (Cline) vs 3 列 (Charles)" | Cline 无 skills_summary 段；工具 description 仅 name（1 列） | 修正为"Cline 1 列（仅 name，工具 description）/ Charles 位置 1 等价 + 位置 2 三元组" |
| 4.17.2 "summary 内容: name + description (Cline)" | Cline 工具 description 仅 name；`configuredSkills` 元数据含 description 但工具 description getter 不读取 | 修正为"Cline 工具 description 仅 name / Charles 位置 2 含 name + when_to_use + description" |
| 4.17.3 "与 skills 工具 description 去重: 已对齐" | Charles 位置 1（工具 description）与 Cline 等价；位置 2（System Prompt rule）是 Charles 独有，Cline 无对应物 | 修正为"工具 description 维度已对齐；System Prompt skills_summary 段是 Charles 独有" |
| 4.17.5 "always 技能标记: 是/是 已对齐" | 两者均**不**在 summary 中标记 always 技能（Cline 无 always 概念；Charles build_summary 不区分 always/on-demand） | 修正为"两者均不标记 always 技能（语义不同：Cline 无 always，Charles 列出但不区分）" |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.17.1 | skills_summary 段位置 | **仅工具 description**（definitions.ts L754-766 `Available skills: ...`）。无 System Prompt 独立段 | **双位置**：工具 description（skill_tool.py L249，与 Cline 等价）+ System Prompt 增强层 `## charles-skills-summary` rule（registry.py L254-263 + context.py L638-642） | 未对齐 | Charles 多出一个 System Prompt 段 |
| 4.17.2 | 段格式 | 逗号分隔字符串 `Available skills: pdf, commit, review-pr.`（L760） | 工具 description：逗号分隔字符串（同 Cline）；System Prompt 段：Markdown 列表 `- {name} ({when_to_use}): {desc}`（L250） | 部分 | 工具 description 等价；System Prompt 段 Charles 独有 |
| 4.17.3 | 段内容字段 | 仅 `name`（L758 `.map((s) => s.name)`）。`configuredSkills` 含 description 但未使用 | 工具 description：仅 `name`；System Prompt 段：`name` + `when_to_use` + `description` 三元组 | 未对齐 | Cline 工具 description 1 字段；Charles System Prompt 段 3 字段 |
| 4.17.4 | when_to_use 字段 | **不支持**。`SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillMetadata`（skills.ts L1-17）均无此字段 | **支持**。`SkillMetadata.when_to_use`（loader.py L81），从 frontmatter 解析（L281-282）。8 个实际技能配置 | 未对齐 | Charles 独有字段 |
| 4.17.5 | description 字段使用 | `configuredSkills` 元数据含 description（types.ts L164），但工具 description getter 不读取 | 工具 description 不读取 description；System Prompt 段读取 `skill.description`（registry.py L241） | 未对齐 | Charles System Prompt 段使用 description |
| 4.17.6 | 禁用技能过滤 | 是。`.filter((s) => !s.disabled)`（L757） | 是。`list_skills()` 过滤 disabled（registry.py L157） | 高 | 已对齐 |
| 4.17.7 | always 技能标记 | 无 always 概念（详见 P4.16） | **不标记**。`build_summary()` 遍历 `list_skills()` 返回的所有技能，不区分 always/on-demand（registry.py L240-250） | 弱对齐 | 两者均不标记；但 Cline 因无 always 概念，Charles 因实现未区分 |
| 4.17.8 | 段标题 | 无（工具 description 末尾追加） | 工具 description：无标题；System Prompt 段：`# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）`（registry.py L234） | 未对齐 | Charles System Prompt 段有引导语 |
| 4.17.9 | 段引导语 | 无 | 工具 description：含基础指引（base 字符串）；System Prompt 段：含强制调用 skills 工具的引导语（L236-238） | 未对齐 | Charles System Prompt 段引导更详细 |
| 4.17.10 | description 截断 | 无截断（仅 name） | description 截断 120 字符 + `...`（registry.py L242-243）；when_to_use 截断 60 字符（L247-248） | 未对齐 | Charles System Prompt 段有截断逻辑 |
| 4.17.11 | 换行处理 | 无（仅 name 字符串） | description 和 when_to_use 均替换 `\n` 为空格（L244 / L249） | 未对齐 | Charles 防止单行内换行破坏 Markdown 格式 |
| 4.17.12 | 动态构建机制 | `Object.defineProperty` getter（L754-766），每次 runtime 读取 description 时重新求值 | 工具 description：`@property` + `_build_description()`（skill_tool.py L80-81）；System Prompt 段：每次 `build()` 调用 `build_summary()`（context.py L640） | 高 | 等价（均为每次访问重新求值） |
| 4.17.13 | token 预算 | 极小。每技能约 2-3 tokens（仅 name），追加到工具 description（非 System Prompt） | 工具 description：同 Cline；System Prompt 段：每技能约 30-50 tokens（含 name + when_to_use + description），8 个技能约 240-400 tokens | 未对齐 | Charles System Prompt 段有显著 token 成本 |
| 4.17.14 | 默认行为 | 工具 description 始终包含 name 列表（只要有可用技能） | 工具 description：同 Cline；System Prompt 段：**默认关闭**（`enhancements.enabled=False`，context.py L322） | 部分 | Charles System Prompt 段默认不注入 |
| 4.17.15 | 配置开关 | 无（工具 description 始终生效） | 双开关：`enhancements.enabled`（总开关，默认 False）+ `enhancements.skills_summary`（子开关，默认 True，context.py L322 / L340） | 未对齐 | Charles System Prompt 段受配置控制 |
| 4.17.16 | 段在 System Prompt 中的位置 | 无此段 | `{{CHARLES_RULES}}` 占位符内，位于 effectiveRules 末尾（在 tools-overview / mcp-overview / always-skills 之后，memory 之前，context.py L620-646 顺序） | 未对齐 | Charles 在 rules 段尾部 |
| 4.17.17 | 与工具 description 去重 | 不适用（仅工具 description 一处） | **无独立去重机制**。System Prompt 段列出所有技能 name；工具 description 也列出所有技能 name。LLM 在两处看到相同 name 列表 | 弱对齐 | Charles 存在信息冗余 |
| 4.17.18 | 实际配置 | 无 when_to_use 配置 | 8 个技能配置 when_to_use：bond-credit-review / write-report / sentiment-analysis / financial-analysis / read-pdf / web-search / stock-price / compare-reports（agent_config/skills/*/SKILL.md L4） | 未对齐 | Charles 实际启用 when_to_use 字段 |
| 4.17.19 | build_tool_hint() 方法 | 无此方法 | 存在但返回 None（registry.py L265-270），注释说明"skills 工具的 description 和 tools section 已经包含足够指引" | — | Charles 有方法但未使用 |
| 4.17.20 | nanobot 溯源 | 无 build_summary 函数 | `nanobot/agent/skills.py` L101-140 `build_skills_summary()` 原型（XML 格式）；Charles `build_summary()` 改为 Markdown 列表 + 新增 when_to_use | 未对齐 | Charles System Prompt 段是 nanobot 实现逻辑残留 |

---

## 三、重点差距详细说明

### 3.1 Cline 不存在独立的 skills_summary 段（4.17.1 / 4.17.3）

这是本阶段最关键的差异。**Cline 不向 System Prompt 注入任何技能清单摘要段**；技能清单仅通过 `skills` 工具的 description 末尾追加 name 列表暴露给 LLM。

**Cline 的暴露路径**：

```typescript
// definitions.ts L754-766
Object.defineProperty(tool, "description", {
    get() {
        const skills = executor.configuredSkills
            ?.filter((s) => !s.disabled)
            .map((s) => s.name);                    // ← 仅读取 name
        if (skills && skills.length > 0) {
            return `${baseDescription} Available skills: ${skills.join(", ")}.`;
        }
        return baseDescription;
    },
    ...
});
```

**关键点**：
1. `configuredSkills` 元数据（types.ts L158-167）包含 `id` / `name` / `description` / `disabled` 四字段。
2. 但工具 description getter（L758）**仅读取 `s.name`**，不读取 `s.description`。
3. 输出格式：`Available skills: pdf, commit, review-pr.`（逗号分隔 + 句号结尾）。
4. **无 System Prompt 独立段**：Cline 的 `effectiveRules` 不包含技能清单 rule，`buildClineSystemPrompt` 不注入技能摘要。

**对比意义**：Cline 的设计哲学是"技能清单仅作为工具 description 的附属信息"，让 LLM 通过工具签名发现可用技能。这与 Cline 的 on-demand 加载模型一致——LLM 看到工具 description 中的技能名后，调用 `skills` 工具加载详细指令，不在 System Prompt 中预注入摘要。

### 3.2 Charles 的双位置暴露（4.17.1 / 4.17.2）

Charles 在两处暴露技能清单：

**位置 1：工具 description（与 Cline 等价）**

```python
# skill_tool.py L225-253
def _build_description(self) -> str:
    base = (
        "执行一个已配置的技能。..."
    )
    try:
        skills = self._registry.list_skills()
        if skills:
            names = ", ".join(s.name for s in skills)    # ← 仅读取 name
            return f"{base} 可用技能: {names}。"
    except Exception:
        pass
    return base
```

与 Cline 等价：仅 name 列表，逗号分隔，追加到 base description。

**位置 2：System Prompt 增强层 `## charles-skills-summary` rule（Charles 独有）**

```python
# registry.py L210-252
def build_summary(self) -> str:
    skills = self.list_skills()
    if not skills:
        return ""
    lines = [
        "# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）",
        "",
        "当用户任务与某个技能匹配时，你必须先调用 skills 工具加载该技能指令...",
        "如果技能指令中包含下载脚本而本地数据不存在，禁止假设数据存在或编造数据...",
        "",
    ]
    for skill in skills:
        desc = skill.description or "(无描述)"
        if len(desc) > 120:
            desc = desc[:120] + "..."
        desc = desc.replace("\n", " ")
        when_to_use = skill.when_to_use or "(见 SKILL.md)"
        if len(when_to_use) > 60:
            when_to_use = when_to_use[:60] + "..."
        when_to_use = when_to_use.replace("\n", " ")
        lines.append(f"- {skill.name} ({when_to_use}): {desc}")    # ← 三元组
    return "\n".join(lines)

# registry.py L254-263
def build_summary_as_rule(self) -> str:
    summary = self.build_summary()
    if not summary:
        return ""
    return f"## charles-skills-summary\n\n{summary}"
```

**关键点**：
1. 工具 description（位置 1）与 Cline 完全等价——仅 name，逗号分隔。
2. System Prompt 段（位置 2）是 Charles 独有——Markdown 列表，每行 `- {name} ({when_to_use}): {desc}`。
3. System Prompt 段含引导语（L236-238）：强制 LLM 调用 skills 工具加载指令，禁止假设数据存在。
4. System Prompt 段有截断逻辑（description 120 字符 / when_to_use 60 字符）。
5. System Prompt 段默认关闭（`enhancements.enabled=False`）。

### 3.3 when_to_use 字段是 Charles 独有增强（4.17.4 / 4.17.5）

**Cline 不支持 when_to_use 字段**：
- `SkillConfig` 接口（user-instruction-config-loader.ts L42-48）仅 5 字段：`name` / `description` / `instructions` / `disabled` / `keywords`。
- `SkillMetadata` 接口（apps/vscode/src/shared/skills.ts L1-17）仅 4 字段：`name` / `description` / `source` / `disabled`。
- 无 `when_to_use` 字段定义。

**Charles 支持 when_to_use 字段**：
- `SkillMetadata.when_to_use`（loader.py L81）：`when_to_use: str = ""`，注释"Phase P5: 何时使用此技能 — 供 skills_summary 表格的'何时使用'列填充"。
- frontmatter 解析（loader.py L281-282）：`when_to_use = str(frontmatter.get("when_to_use", ""))`。
- 8 个实际技能配置了该字段（agent_config/skills/*/SKILL.md L4），如：
  - `read-pdf/SKILL.md` L4：`when_to_use: "用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"`
  - `stock-price/SKILL.md` L4：`when_to_use: "用户询问股价/涨跌幅/K线/成交量/近期走势时"`

**字段用途**：仅在 `build_summary()`（位置 2 System Prompt 段）中使用，工具 description（位置 1）不使用。

**字段溯源**：注释标注"对标 Cline SKILL.md frontmatter 的 description 字段中隐含的'何时使用'语义"（loader.py L80），但实际 Cline 无此字段， Charles 的"对标"表述不准确。该字段是 Charles 独有增强，灵感可能来自 Cline description 字段的语义拆分（将"何时使用"与"技能描述"分离）。

### 3.4 token 预算差异（4.17.13）

**Cline**：
- 工具 description：每技能约 2-3 tokens（仅 name + 逗号分隔符）。
- 10 个技能约 20-30 tokens。
- **不占用 System Prompt**（工具 description 由 runtime 在请求时注入 tools 数组，不计入 System Prompt）。

**Charles**：
- 工具 description：同 Cline（约 20-30 tokens，不占用 System Prompt）。
- System Prompt 段（启用时）：
  - 每技能约 30-50 tokens（含 name + when_to_use + description 三段，加 Markdown 列表标记）。
  - 8 个技能约 240-400 tokens。
  - registry.py L10 docstring 声称"~100 tokens/技能"，实际因含 when_to_use 可能略低。
  - **占用 System Prompt**（注入 `{{CHARLES_RULES}}` 占位符）。

**对比意义**：Charles 的 System Prompt 段在启用时会显著增加 System Prompt 长度（240-400 tokens），可能影响上下文窗口预算。这是 Charles 选择默认关闭该段的原因之一。Cline 的方案更节省 token，但信息密度较低（LLM 仅看到 name，需调用工具才能了解技能用途）。

### 3.5 动态构建机制等价（4.17.12）

**Cline**：
```typescript
// definitions.ts L754-766
Object.defineProperty(tool, "description", {
    get() {
        const skills = executor.configuredSkills
            ?.filter((s) => !s.disabled)
            .map((s) => s.name);
        // ...
    },
    enumerable: true,
    configurable: true,
});
```

`Object.defineProperty` 定义 getter，每次 runtime 读取 `tool.description` 时重新求值。runtime 在构建每个模型请求时读取工具 description，因此技能增删（通过 watcher）会立即反映到下一次请求。

**Charles**：
```python
# skill_tool.py L80-81
@property
def description(self) -> str:
    return self._build_description()

# registry.py L210-252
def build_summary(self) -> str:
    skills = self.list_skills()    # 每次调用重新加载
    # ...

# context.py L638-642
if self._enhancements.get("skills_summary") and self.skills_registry:
    body = self.skills_registry.build_summary()    # 每次构建 System Prompt 重新加载
    if body:
        rules.append(("charles-skills-summary", body))
```

`@property` 装饰器 + `build_summary()` 每次调用 `list_skills()` 重新加载。`SystemPromptBuilder.build()` 每次构建 System Prompt 时调用 `_build_enhancement_rules()` → `build_summary()`。

**等价性**：两者均为"每次访问重新求值"，无缓存。技能增删立即反映到下一次请求。**实现范式不同**（TypeScript `Object.defineProperty` vs Python `@property`），但语义等价。

### 3.6 Charles System Prompt 段的引导语（4.17.9）

Charles 的 `build_summary()` 在技能列表前插入两行引导语（registry.py L236-238）：

```
当用户任务与某个技能匹配时，你必须先调用 skills 工具加载该技能指令，然后严格按照指令执行。
如果技能指令中包含下载脚本而本地数据不存在，禁止假设数据存在或编造数据，必须立即执行脚本获取。
```

**目的**：
1. 强制 LLM 调用 `skills` 工具加载指令（对齐 Cline 的"blocking requirement"语义）。
2. 禁止 LLM 跳过 skills 工具直接调用技能目录下的脚本（Charles 业务约束）。
3. 禁止 LLM 在数据不存在时编造数据（量化场景的严谨性约束）。

**Cline 无此引导语**：Cline 的引导语在工具 description 的 base 字符串中（definitions.ts L725-731），不在 System Prompt 段中。

---

## 四、nanobot 残留专项检查

### 4.1 实现逻辑残留（1 处，核心残留）

Charles 的 System Prompt skills_summary 段是**完整的 nanobot 实现逻辑残留**，非纯注释残留。溯源对比如下：

| 组件 | nanobot 实现 | Charles 实现 | 残留性质 |
|------|-------------|-------------|---------|
| 摘要构建函数 | `nanobot/agent/skills.py` L101-140 `build_skills_summary()`：遍历 `list_skills(filter_unavailable=False)`，构建 XML `<skills><skill available="..."><name>...</name><description>...</description><location>...</location></skill></skills>` | `agent/skills/registry.py` L210-252 `build_summary()`：遍历 `list_skills()`，构建 Markdown 列表 `- {name} ({when_to_use}): {desc}` | **概念复刻 + 格式适配**：从 XML 改为 Markdown 列表；新增 when_to_use 字段（Charles 独有，nanobot 无） |
| System Prompt 注入 | `nanobot/agent/context.py` L78-85：`parts.append(f"# Skills\n\nThe following skills extend your capabilities...\n\n{skills_summary}")` | `agent/skills/registry.py` L254-263 `build_summary_as_rule()` + `agent/context.py` L638-642：包装为 `## charles-skills-summary` rule，经 `{{CHARLES_RULES}}` 注入 | **复刻 + 适配**：从 `# Skills` 独立段改为 `## charles-skills-summary` rule（适配 Cline 的 base + rules 两层结构） |
| 摘要字段 | nanobot：`name` + `description` + `location`（路径）+ `available`（依赖检查）+ `requires`（缺失依赖） | Charles：`name` + `when_to_use` + `description`（无 location / available / requires） | **字段调整**：Charles 移除 location / available / requires（无依赖检查机制），新增 when_to_use（Charles 独有增强） |
| 依赖检查 | nanobot：`_check_requirements(skill_meta)` 检查 bins / env，标记 `available="true/false"` | Charles：**无依赖检查**。所有技能均视为可用（disabled 过滤后） | **功能缺失**：Charles 不支持 nanobot 的 requires 字段 |
| 段标题 | nanobot：`# Skills`（顶级段） | Charles：`## charles-skills-summary`（rule 标题） | **降级**：从 System Prompt 顶级段降为 rule（受 `{{CHARLES_RULES}}` 占位符约束） |

**残留判定依据**：
1. **Cline 无等价物**：Cline 的 `SkillConfig` / `SkillMetadata` 均无 when_to_use 字段，`user-instruction-plugin.ts` 无 build_summary 函数，`createSkillsTool` 仅在工具 description 追加 name 列表。
2. **nanobot 有原型**：nanobot `build_skills_summary()`（L101-140）+ `# Skills` 段注入（context.py L78-85）是完整实现。
3. **Charles docstring 自证**：`registry.py` L20-22 docstring 明确标注"对标 nanobot: build_skills_summary(): XML 格式技能列表"。
4. **实现完整可用**：Charles 的 skills_summary 段非 dead code，受配置开关控制，默认关闭但可启用。8 个实际技能配置了 when_to_use 字段。
5. **概念链路完整**：`build_summary()` → `build_summary_as_rule()` → `_build_enhancement_rules()` → `{{CHARLES_RULES}}` 注入 → System Prompt，完整链路可用。

### 4.2 注释残留（3 处，1 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/skills/registry.py` | L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 标题（同时引用 Cline 和 nanobot） |
| `agent/skills/registry.py` | L20-22 | `对标 nanobot:\n    - build_skills_summary(): XML 格式技能列表\n    - get_always_skills(): always=True 的技能` | docstring 对标说明（明确标注 build_skills_summary 源自 nanobot） |
| `agent/skills/registry.py` | L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | class docstring 标题 |

**注释残留小结**：
- 3 处注释残留全部集中在 `agent/skills/registry.py`，均为 docstring 中的"对标 nanobot"说明。
- `agent/context.py` 中无 nanobot 注释残留（context.py 的 skills_summary 注入逻辑用 Cline 风格的 `effectiveRules` + `enhancements` 包装，无 nanobot 字面引用）。
- `agent/skills/loader.py` 的 nanobot 注释残留已在 P4.2 报告中详述，本阶段不重复。
- `agent/skills/skill_tool.py` L18 的 nanobot 注释（"这与 nanobot 的'子 agent 隔离执行'有本质区别"）已在 P4.1 报告中详述，本阶段不重复。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 实现逻辑残留（skills_summary 段） | 1 处（含 2 个方法 + 1 个字段 + 1 个配置开关 + 1 个注入路径） | **中** | skills_summary 段默认关闭，不影响默认运行时行为；但概念源自 nanobot，与 Cline 的"工具 description only"设计哲学冲突 |
| 注释残留（nanobot 对标说明） | 3 处 | 低 | 可保留作为设计溯源参考，或统一清理 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（3 处）：仅在 docstring 中引用 "nanobot" 字样，不影响运行时行为。如 `registry.py` L20-22 `对标 nanobot: build_skills_summary(): XML 格式技能列表`，这是设计溯源说明，删除后功能不变。

**实现逻辑残留**（1 处）：skills_summary 段的完整实现链路，**影响运行时行为**：
- `SkillMetadata.when_to_use` 字段（loader.py L81）—— 数据结构残留（Charles 独有，非源自 nanobot，但服务于 nanobot 风格的 summary 段）
- `_parse_skill_file` 中 `when_to_use = str(frontmatter.get("when_to_use", ""))`（loader.py L281-282）—— 解析逻辑残留
- `build_summary()` 方法（registry.py L210-252）—— 构建逻辑残留（概念源自 nanobot，格式适配）
- `build_summary_as_rule()` 方法（registry.py L254-263）—— 包装逻辑残留（Charles 适配，无 nanobot 等价物）
- `_build_enhancement_rules()` 中 `charles-skills-summary` rule 生成（context.py L638-642）—— 注入逻辑残留
- `_load_enhancements()` 中 `skills_summary` 开关（context.py L323 / L340）—— 配置逻辑残留
- `agent_config/skills/*/SKILL.md` L4（8 个技能的 `when_to_use` 字段）—— 实际配置残留

**关键区别**：若删除注释残留，功能不变；若删除实现逻辑残留，skills_summary 段不再注入 System Prompt，Charles 行为向 Cline 对齐（技能清单仅通过工具 description 暴露，仅 name）。

### 4.5 when_to_use 字段的残留性质

`when_to_use` 字段是 Charles 独有增强，**非直接源自 nanobot**（nanobot 的 `build_skills_summary()` 使用 `name` + `description` + `location` + `available` + `requires` 五字段，无 `when_to_use`）。但该字段**服务于 nanobot 风格的 summary 段**——若移除 nanobot 风格的 System Prompt summary 段，`when_to_use` 字段将失去主要用途（仅在工具 description 中不使用）。

因此，`when_to_use` 字段属于"**为 nanobot 风格 summary 段服务的 Charles 独有增强**"，其残留性质为"实现逻辑残留的配套字段"，建议与 summary 段一同评估保留或移除。

---

## 五、修复建议

### 5.1 高优先级（P1）

无。skills_summary 段默认关闭（`enhancements.enabled=False`），不影响默认运行时行为。且 `agent_config/system_prompt.yaml` 不存在，实际未注入 System Prompt。

### 5.2 中优先级（P2）

1. **修正 docstring 溯源标注**（registry.py L20-22）：
   - 当前：`对标 nanobot: build_skills_summary(): XML 格式技能列表`
   - 问题：Charles 的 `build_summary()` 实际是 Markdown 列表格式，非 XML；且新增了 `when_to_use` 字段（nanobot 无）。docstring 标注不准确，可能误导读者认为 Charles 1:1 复刻 nanobot XML 格式。
   - 建议改为：`设计参考: nanobot build_skills_summary()（概念复刻，格式从 XML 改为 Markdown 列表，新增 when_to_use 字段为 Charles 独有增强）`
   - 明确标注格式差异和 Charles 独有增强，避免与 nanobot 1:1 复刻混淆。

2. **修正 loader.py L80 注释**（when_to_use 字段溯源）：
   - 当前：`# 对标 Cline SKILL.md frontmatter 的 description 字段中隐含的"何时使用"语义`
   - 问题：Cline 无 when_to_use 字段，"对标 Cline"表述不准确。该字段是 Charles 独有增强，灵感可能来自 Cline description 字段的语义拆分，但非直接对标。
   - 建议改为：`# Charles 独有增强：何时使用此技能，供 skills_summary 段的"何时使用"列填充。Cline 和 nanobot 均无此字段。`

3. **评估 skills_summary 段的保留必要性**：
   - **保留方案**：若 Charles 需要在 System Prompt 中向 LLM 暴露技能的"何时使用"信息（提升技能匹配准确率），可保留 skills_summary 段。但应在 docstring 中明确说明"这是 Charles 独有增强，概念源自 nanobot，Cline 无等价物"。
   - **移除方案**：若严格对齐 Cline 的"工具 description only"设计哲学，应移除 `build_summary()` / `build_summary_as_rule()` 方法、`_build_enhancement_rules()` 中的 `charles-skills-summary` rule 生成、`_load_enhancements()` 中的 `skills_summary` 开关、`SkillMetadata.when_to_use` 字段及其 frontmatter 解析、以及 8 个 SKILL.md 的 `when_to_use` 配置。
   - **建议**：保留方案更务实（when_to_use 字段对量化场景的技能匹配有业务价值），但需修正 docstring 避免"对标 Cline/nanobot"的误导性表述。

4. **解决信息冗余问题**（4.17.17）：
   - Charles 位置 1（工具 description）和位置 2（System Prompt 段）均列出技能 name，存在信息冗余。
   - 建议在位置 2 中移除 name 字段（仅保留 when_to_use + description），或在位置 1 中移除 name 列表（仅保留位置 2 的详细信息）。
   - 或在位置 2 的引导语中明确说明"详细技能列表见下方，简要列表见 skills 工具"，让 LLM 理解两处信息的层级关系。

### 5.3 低优先级（P3）

5. **nanobot 注释统一**（3 处）：可选择保留作为设计溯源，或统一清理为仅引用 Cline 对标位置。

6. **skills_summary 段 token 成本监控**（4.17.13）：若启用 skills_summary 段，应在 `SystemPromptBuilder` 中记录该段的 token 占用，便于调试 System Prompt 过长问题。当前 `estimate_tokens()`（context.py L897-910）已支持 token 估算，但未针对 skills_summary 段单独统计。

7. **build_tool_hint() 方法清理**（4.17.19）：`build_tool_hint()` 方法返回 None 且注释说明"不再重复"（registry.py L265-270），但方法本身存在。若确认无调用方，可移除以减少代码噪音。

8. **补充 nanobot 的依赖检查功能**（4.4 表格"功能缺失"）：nanobot 的 `build_skills_summary()` 含 `available` / `requires` 字段检查技能依赖（bins / env）。Charles 不支持依赖检查。若需要（如某些技能依赖特定 Python 包或环境变量），可参考 nanobot `_check_requirements()` 实现。

---

## 六、验证方法建议

### 6.1 Cline 无 skills_summary 段验证

1. **Cline 工具 description 仅 name**：
   ```
   Grep "s\.name|\.name" third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts
   ```
   预期：命中 L758 `.map((s) => s.name)`，无 `.map((s) => s.description)` 或类似

2. **Cline 无 build_summary 函数**：
   ```
   Grep "build_summary|buildSummary|skills_summary|skillsSummary" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中（Cline 无此函数）

3. **Cline SkillConfig 无 when_to_use 字段**：
   ```
   Grep "when_to_use|whenToUse" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中

### 6.2 Charles skills_summary 段验证

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
   assert "何时使用" not in summary  # 引导语不含此词
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
   预期：命中 8 个 SKILL.md 文件（bond-credit-review / write-report / sentiment-analysis / financial-analysis / read-pdf / web-search / stock-price / compare-reports）

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
   ```
   预期：命中 L2 / L20-22 / L100（3 处 docstring）

### 6.5 计划表标注修正验证

1. **Cline 工具 description 不含 description 字段**：
   ```
   Grep "s\.description|\.description" third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts
   ```
   预期：0 命中（工具 description getter 不读取 description 字段）

2. **Cline 无 System Prompt skills_summary 段**：
   ```
   Grep "skills_summary|skillsSummary|charles-skills-summary" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中

---

## 七、与 P4.1 / P4.16 发现的衔接

P4.1（skills 工具）和 P4.16（always_skills 段）已分别发现 Charles 的工具 description 与 Cline 等价、Charles 独有 System Prompt 增强层。本阶段（P4.17）在 skills_summary 维度深入对比，**确认并细化了以下发现**：

| P4.1 / P4.16 发现 | P4.17 深化 |
|------------------|-----------|
| Charles 工具 description 与 Cline 等价（仅 name，P4.1 §4.1.4 / §4.1.19） | 确认工具 description 维度完全对齐；Charles 的 skills_summary 信息暴露在**第二位置**（System Prompt 段），与 Cline 的"仅工具 description"设计哲学不同 |
| Charles 独有 System Prompt 增强层（P4.16 §3.3） | 确认 skills_summary 段的完整注入链路（L210 build_summary → L254 build_summary_as_rule → context.py L638-642 注入 → `{{CHARLES_RULES}}` 占位符） |
| Charles always_skills 段是 nanobot 实现逻辑残留（P4.16 §4.1） | 确认 skills_summary 段同样是 nanobot 实现逻辑残留（概念源自 nanobot `build_skills_summary()`），但格式从 XML 改为 Markdown 列表，并新增 when_to_use 字段（Charles 独有增强） |
| Cline skills 全部 on-demand（P4.16 §3.2 引用 skills.mdx L9） | 确认 Cline 不仅 on-demand 加载指令，连技能清单也仅通过工具 description 暴露（不预注入 System Prompt） |
| Charles skills_summary 段受 enhancements 开关控制（P4.16 §3.4） | 确认 skills_summary 段同样受 `enhancements.enabled`（默认 False）+ `enhancements.skills_summary`（默认 True）双开关控制，默认关闭 |

**本阶段新增发现**（P4.1 / P4.16 未覆盖）：
1. **Cline 的工具 description getter 不读取 description 字段**：虽然 `configuredSkills` 元数据含 description（types.ts L164），但工具 description getter（L758）仅 `.map((s) => s.name)`，description 字段未被使用。计划表 4.17.2 标注"Cline summary 内容: name + description"不准确。
2. **Charles 的 when_to_use 字段是 Charles 独有增强**：非源自 nanobot（nanobot 无此字段），也非源自 Cline（Cline 无此字段）。该字段服务于 skills_summary 段的"何时使用"列，若移除 skills_summary 段，该字段失去主要用途。
3. **Charles skills_summary 段的引导语**（registry.py L236-238）：强制 LLM 调用 skills 工具 + 禁止编造数据，是 Charles 业务约束（量化场景严谨性），Cline 和 nanobot 均无此引导语。
4. **Charles skills_summary 段的截断逻辑**（registry.py L242-248）：description 120 字符 + when_to_use 60 字符截断，防止单技能摘要过长。Cline 无截断逻辑（因仅 name）。
5. **信息冗余问题**（§3.6 / 4.17.17）：Charles 位置 1（工具 description）和位置 2（System Prompt 段）均列出技能 name，LLM 在两处看到相同信息，存在冗余。Cline 仅一处暴露，无冗余。
6. **build_tool_hint() 方法存在但未使用**（registry.py L265-270）：返回 None，注释说明"不再重复"，但方法本身存在。可能是历史遗留的 dead code。
