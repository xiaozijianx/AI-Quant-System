# Phase 5.18 Skills 段条件注入对比

> 对比范围：Cline 与 Charles 在 Skills 段的**条件注入逻辑**（何时注入 `skills_summary`、何时注入 `always_skills`、无技能时行为）的差异；区分"工具 description 维度"与"System Prompt 段维度"两个注入位置；与 P5.9（skills 概览段内容）/ P5.10（always skills 段内容）/ P4.17 / P4.16 的边界划分；nanobot 残留专项检查（严格区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 纯组装函数，`effectiveRules` 仅含 `rules + MODE_TAG_INSTRUCTIONS + PLAN_MODE_INSTRUCTIONS`，**无 skills 段占位符**）
> - `sdk/packages/shared/src/prompt/system.ts`（`DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT` base 模板，**全文无 Skills 段**）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L714-769（`createSkillsTool`：L754-762 `Object.defineProperty` 动态 description getter，条件 `skills && skills.length > 0` 决定是否追加 `Available skills: ...`）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L75-217（`getConfiguredSkillsFromWatcher` + `createUserInstructionSkillsExecutor` 纯 on-demand 加载，**无 always 预加载路径**）
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L42-48（`SkillConfig` 接口仅 5 字段：name/description/disabled/instructions/frontmatter，**无 `always`**）
> - `apps/vscode/src/shared/skills.ts` L5-17（`SkillMetadata` 接口仅 4 字段：name/description/path/source，**无 `always`**）
> - `docs/customization/skills.mdx` L9（"Unlike rules (which are always active), skills load on-demand" —— Cline 设计哲学）
>
> Charles 源码：
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装函数，`{{CHARLES_RULES}}` 占位符承载 skills 增强层 rule）+ L214-889（`SystemPromptBuilder` 编排器类）
> - `agent/context.py` L304-346（`_load_enhancements` 配置默认 `skills_summary: True` / `always_skills: True`，但总开关 `enabled: False`）+ L520-528（`_build_rules` 增强层注入到 `{{CHARLES_RULES}}`）+ L611-647（`_build_enhancement_rules`：条件生成 `charles-always-skills` / `charles-skills-summary` rule）
> - `agent/skills/registry.py` L183-191（`get_always_skills()`）+ L193-208（`load_always_instructions()`）+ L210-252（`build_summary()`）+ L254-263（`build_summary_as_rule()`）+ L272-285（`load_always_instructions_as_rule()`）
> - `agent/skills/skill_tool.py` L225-253（`_build_description`：条件 `if skills:` 追加 `可用技能: {names}。`）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/skills.py` L203-211（`get_always_skills()` 原型）+ L101-140（`build_skills_summary()` 原型，XML 格式）
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py` L53-57（`# Active Skills` 段条件注入：`if always_skills:`）+ L78-85（`# Skills` 段条件注入：`if skills_summary:`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 Skills 段的**条件注入逻辑**（非段内容本身，内容对比见 P5.9 / P5.10）。**核心结论：在工具 description 维度两者条件注入逻辑已对齐（都有 `skills.length > 0` 条件）；在 System Prompt 段维度两者未对齐 —— Cline 无任何 System Prompt 段注入路径，Charles 通过 `enhancements` 双开关 + 非空校验形成两层条件门控注入 `## charles-skills-summary` / `## charles-always-skills` rule。Charles 的 System Prompt 段注入逻辑是完整的 nanobot 实现逻辑残留。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.18（L2130-2145）的对比表存在**严重事实错误**：

1. **5.18.1 "skills 注入条件: 有技能时/有技能时，已对齐"**：**部分错误**。
   - **工具 description 维度**：已对齐（两者均 `skills.length > 0` 时注入）。
   - **System Prompt 段维度**：**未对齐**。Cline 的 `buildClineSystemPrompt`（cline.ts L110-166）`effectiveRules` 仅含 `rules + MODE_TAG + PLAN_MODE`，**无 skills 段占位符**；Charles 通过 `enhancements.enabled` + `enhancements.skills_summary` + `build_summary() 非空` 三层条件门控注入 `## charles-skills-summary` rule。
   - 应修正为："工具 description 维度已对齐 / System Prompt 段维度未对齐"。

2. **5.18.2 "always skills 注入: always=True/always=True，已对齐"**：**完全错误**。
   - **Cline 不支持 `always` 字段**：`SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillMetadata`（skills.ts L5-17）均无 `always` 字段，`createSkillsTool` 纯 on-demand，**无 always 预加载路径**。
   - **Charles 支持 `always` 字段**：`SkillMetadata.always`（loader.py L70）从 frontmatter 解析（L234），通过 `load_always_instructions()` 预加载（registry.py L193-208），经 `load_always_instructions_as_rule()` 包装为 `## charles-always-skills` rule（registry.py L272-285），由 `_build_enhancement_rules()`（context.py L632-636）注入。
   - 应修正为："Cline 无 always 字段 / Charles 有 always 字段，未对齐"。

3. **5.18.3 "无技能时行为: 不注入/不注入，已对齐"**：**部分正确**。
   - **工具 description 维度**：已对齐（两者 `skills.length === 0` 时均不追加 Available skills 字符串）。
   - **System Prompt 段维度**：**未对齐**。Cline 无此段（无条件注入路径）；Charles 受 `enhancements.enabled` 默认 `False` 控制实际不注入，但代码层面具备注入能力。
   - 应修正为："工具 description 维度已对齐 / System Prompt 段维度未对齐（Cline 无此段，Charles 默认关闭但可启用）"。

### 核心结论

1. **Skills 段注入位置**：
   - **Cline**：**仅工具 description 维度**。`createSkillsTool`（definitions.ts L754-762）通过 `Object.defineProperty` 动态 getter，条件 `skills && skills.length > 0` 决定是否在 base description 末尾追加 `Available skills: {name1}, {name2}, ...`。**System Prompt 中无 skills 段**。
   - **Charles**：**双位置**。
     - 位置 1（与 Cline 对齐）：`skills` 工具 description（skill_tool.py L225-253），条件 `if skills:` 追加 `可用技能: {names}。`。
     - 位置 2（Charles 独有）：System Prompt 增强层 `## charles-skills-summary` rule（context.py L638-642 + registry.py L254-263），三层条件门控注入。

2. **skills_summary 注入条件**：
   - **Cline**：不适用（Cline 无 System Prompt 段注入路径）。工具 description 维度的条件为 `configuredSkills?.filter((s) => !s.disabled).map((s) => s.name)` 非空（definitions.ts L756-759）。
   - **Charles 位置 1**：`list_skills()` 非空（skill_tool.py L246-249）。
   - **Charles 位置 2**：三层条件 AND 关系 ——
     1. `enhancements.enabled == True`（context.py L521，默认 `False`）
     2. `enhancements.skills_summary == True`（context.py L638，默认 `True`）
     3. `self.skills_registry` 非空 AND `build_summary()` 返回非空（context.py L638-642）

3. **always_skills 注入条件**：
   - **Cline**：**无此机制**。`SkillConfig` / `SkillMetadata` 均无 `always` 字段，`createSkillsTool` 纯 on-demand。
   - **Charles**：三层条件 AND 关系 ——
     1. `enhancements.enabled == True`（context.py L521，默认 `False`）
     2. `enhancements.always_skills == True`（context.py L632，默认 `True`）
     3. `self.skills_registry` 非空 AND `load_always_instructions()` 返回非空（context.py L632-636，即至少有一个 `always: true` 的技能）

4. **无技能时行为**：
   - **Cline**：工具 description 返回 base 字符串（无 `Available skills:` 后缀）；System Prompt 中无 skills 段。
   - **Charles 位置 1**：工具 description 返回 base 字符串（无 `可用技能:` 后缀）。
   - **Charles 位置 2**：三层条件中第 3 条不满足（`build_summary()` / `load_always_instructions()` 返回空），不注入对应 rule；若 `enhancements.enabled == False`（默认），所有增强层 rule 均不注入。

5. **Cline 的设计哲学**：`docs/customization/skills.mdx` L9 明确 "Unlike rules (which are always active), skills load on-demand"。Cline 严格区分 rules（始终注入）和 skills（按需加载），**skills 永远不进入 System Prompt**，仅通过 `skills` 工具触发 Level 2 指令加载。

6. **Charles 的设计偏离**：Charles 通过 `enhancements` 配置开关引入 System Prompt 段注入路径，打破了 Cline 的 rules/skills 边界。该路径默认关闭（`enhancements.enabled=False`），但代码层面具备注入能力，源自 nanobot `# Active Skills` / `# Skills` 顶级段注入模式。

7. **nanobot 残留**：
   - **注释残留**：5 处（registry.py L2/L20-22/L100/L184 共 4 处 + context.py L275 `extra_sections` docstring 1 处）。
   - **实现逻辑残留**：2 处完整链路（skills_summary 注入链路 + always_skills 注入链路），均源自 nanobot `agent/context.py` L53-85 的条件注入模式。

### 一致性总体评估

- **工具 description 维度条件注入**：**完全对齐**。两者均 `skills.length > 0` 时注入，无技能时仅返回 base 字符串。
- **System Prompt 段维度条件注入**：**未对齐**。Cline 无此段（无条件注入路径）；Charles 有三层条件门控注入路径（默认关闭）。
- **always_skills 注入**：**未对齐**。Cline 不支持 `always` 字段；Charles 有完整 always 预加载链路。
- **无技能时行为**：**工具维度对齐，System Prompt 段维度未对齐**。
- **计划文件 P5.18 标注**：**3 项全部不准确**，需修正。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.18.1 | skills 注入条件（工具 description 维度） | `skills && skills.length > 0`（definitions.ts L759）。`configuredSkills?.filter((s) => !s.disabled).map((s) => s.name)` 非空时追加 `Available skills: {names}.` | `if skills:`（skill_tool.py L247）。`list_skills()` 非空时追加 `可用技能: {names}。` | 完全对齐 | 两者均"有非禁用技能时注入"，条件等价 |
| 5.18.2 | skills 注入条件（System Prompt 段维度） | **无此路径**。`buildClineSystemPrompt`（cline.ts L110-166）`effectiveRules` 仅含 `rules + MODE_TAG + PLAN_MODE`，无 skills 段占位符 | 三层条件 AND：`enhancements.enabled`（默认 False）+ `enhancements.skills_summary`（默认 True）+ `build_summary()` 非空（context.py L521/L638-642） | 未对齐 | Cline 无 System Prompt 段注入；Charles 有三层门控（默认关闭） |
| 5.18.3 | always_skills 注入条件 | **无此机制**。`SkillConfig` / `SkillMetadata` 均无 `always` 字段；`createSkillsTool` 纯 on-demand | 三层条件 AND：`enhancements.enabled`（默认 False）+ `enhancements.always_skills`（默认 True）+ `load_always_instructions()` 非空（context.py L521/L632-636） | 未对齐 | Cline 不支持 always；Charles 有 always 预加载链路（源自 nanobot） |
| 5.18.4 | 无技能时行为（工具 description） | 返回 base description（无 `Available skills:` 后缀，definitions.ts L762） | 返回 base description（无 `可用技能:` 后缀，skill_tool.py L253） | 完全对齐 | 两者均"无技能时不追加" |
| 5.18.5 | 无技能时行为（System Prompt 段） | **无此段**（无注入路径） | `build_summary()` 返回空时跳过 rule 追加（context.py L640 `if body:`）；`enhancements.enabled=False` 时所有增强层均不注入 | 未对齐 | Cline 无此段；Charles 默认关闭，启用后无技能时不注入 |
| 5.18.6 | 无 always 技能时行为 | **无此机制** | `load_always_instructions()` 返回空时跳过 rule 追加（context.py L634 `if body:`） | 未对齐 | Charles 启用增强层但无 always 技能时，always_skills rule 不注入 |
| 5.18.7 | skills_summary 注入位置 | 仅工具 description（definitions.ts L754-762） | 双位置：工具 description（skill_tool.py L225-253）+ System Prompt `## charles-skills-summary` rule（context.py L638-642） | 未对齐 | Charles 多出 System Prompt 段位置 |
| 5.18.8 | always_skills 注入位置 | **无此机制** | System Prompt `## charles-always-skills` rule（context.py L632-636） | 未对齐 | Charles 独有，Cline 无等价物 |
| 5.18.9 | skills 注入条件门控层数 | 1 层（`skills.length > 0`） | 位置 1: 1 层（`if skills:`）；位置 2: 3 层（`enabled` + `skills_summary` + 非空） | 部分 | 工具维度对齐，System Prompt 段维度 Charles 多 2 层门控 |
| 5.18.10 | always 技能 vs on-demand 区分 | **无区分**。所有 skills 均 on-demand（skills.mdx L9 "skills load on-demand"） | **有区分**。always 技能启动时预加载；on-demand 技能需调用 `skills` 工具加载 | 未对齐 | Cline 设计哲学：skills 永远 on-demand；Charles 打破边界 |
| 5.18.11 | `always` frontmatter 字段 | **不支持**（`SkillConfig` L42-48 无此字段） | **支持**（`SkillMetadata.always`，loader.py L70/L234） | 未对齐 | Charles 独有字段，源自 nanobot |
| 5.18.12 | nanobot 溯源 | **无此机制** | `nanobot/agent/context.py` L53-57（`# Active Skills` 条件注入）+ L78-85（`# Skills` 条件注入）。Charles 复刻条件逻辑，仅包装格式从顶级段改为 rule | 未对齐 | Charles 实现逻辑残留 |

---

## 三、重点差距详细说明

### 3.1 Cline 的 Skills 注入条件逻辑（5.18.1 / 5.18.4）

Cline 的 skills 注入**仅在工具 description 维度**，通过 `createSkillsTool` 的 `Object.defineProperty` 动态 getter 实现（definitions.ts L754-762）：

```typescript
Object.defineProperty(tool, "description", {
    get() {
        const skills = executor.configuredSkills
            ?.filter((s) => !s.disabled)
            .map((s) => s.name);
        if (skills && skills.length > 0) {
            return `${baseDescription} Available skills: ${skills.join(", ")}.`;
        }
        return baseDescription;
    },
});
```

**条件逻辑分析**：
1. `executor.configuredSkills` 必须存在（非 `undefined`）。
2. `.filter((s) => !s.disabled)` 过滤禁用技能。
3. `.map((s) => s.name)` 提取技能名（**仅 name，不读 description**）。
4. `skills && skills.length > 0` 条件门控：
   - **有技能时**：返回 `${baseDescription} Available skills: ${names}.`。
   - **无技能时**：返回 `baseDescription`（无 `Available skills:` 后缀）。

**System Prompt 维度**：`buildClineSystemPrompt`（cline.ts L110-166）的 `effectiveRules` 仅含 `[rules, MODE_TAG_INSTRUCTIONS, mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined]`（L145-151），**无任何 skills 段占位符**。`DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT` 模板全文无 Skills 章节。即 **Cline 的 System Prompt 中永远不包含 skills 清单**。

### 3.2 Charles 的 skills_summary 注入条件逻辑（5.18.2 / 5.18.5）

Charles 的 skills_summary 注入有**两个位置**，条件逻辑不同：

**位置 1：工具 description 维度**（skill_tool.py L225-253 `_build_description`）：

```python
def _build_description(self) -> str:
    base = (...)  # base description 字符串
    try:
        skills = self._registry.list_skills()
        if skills:
            names = ", ".join(s.name for s in skills)
            return f"{base} 可用技能: {names}。"
    except Exception:
        pass
    return base
```

**条件逻辑**：`list_skills()` 非空时追加 `可用技能: {names}。`，否则返回 base。与 Cline 完全等价。

**位置 2：System Prompt 增强层维度**（context.py L638-642）：

```python
if self._enhancements.get("skills_summary") and self.skills_registry:
    body = self.skills_registry.build_summary()
    if body:
        rules.append(("charles-skills-summary", body))
```

**三层条件 AND 关系**：
1. **总开关**：`self._enhancements.get("enabled") == True`（context.py L521，默认 `False`）。
2. **子开关**：`self._enhancements.get("skills_summary") == True`（context.py L638，默认 `True`）。
3. **非空校验**：`self.skills_registry` 非空 AND `build_summary()` 返回非空。

`build_summary()`（registry.py L210-252）的非空条件：
- `list_skills()` 非空（registry.py L229-231：`if not skills: return ""`）。
- `list_skills()` 内部应用白名单过滤（L151-155）和 disabled 过滤（L157）。

**默认行为**：`enhancements.enabled=False`，位置 2 不注入。当前 `agent_config/system_prompt.yaml` 配置 `enabled: false`，实际未注入。

### 3.3 Charles 的 always_skills 注入条件逻辑（5.18.3 / 5.18.6）

Charles 的 always_skills 注入**仅在 System Prompt 增强层维度**（context.py L632-636）：

```python
if self._enhancements.get("always_skills") and self.skills_registry:
    body = self.skills_registry.load_always_instructions()
    if body:
        rules.append(("charles-always-skills", body))
```

**三层条件 AND 关系**：
1. **总开关**：`self._enhancements.get("enabled") == True`（context.py L521，默认 `False`）。
2. **子开关**：`self._enhancements.get("always_skills") == True`（context.py L632，默认 `True`）。
3. **非空校验**：`self.skills_registry` 非空 AND `load_always_instructions()` 返回非空。

`load_always_instructions()`（registry.py L193-208）的非空条件：
- `get_always_skills()`（L183-191）返回非空列表，即至少有一个 `meta.always == True` 的技能。
- 每个always 技能的 `load_instructions(name)` 返回非空。

**实际配置**：`agent_config/skills/read-pdf/SKILL.md` L5 `always: true`（唯一实例）。若启用增强层，always_skills 段会包含 read-pdf 的完整 SKILL.md 指令。

**Cline 对比**：Cline 的 `SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillMetadata`（skills.ts L5-17）**均无 `always` 字段**，`createSkillsTool` 纯 on-demand，无 always 预加载路径。即 **Cline 无 always_skills 注入条件逻辑**。

### 3.4 计划文件 P5.18 标注修正（5.18.1 / 5.18.2 / 5.18.3）

| 计划表项 | 计划表标注 | 实际情况 | 修正建议 |
|---------|----------|---------|---------|
| 5.18.1 skills 注入条件 | "有技能时/有技能时，已对齐" | 工具维度已对齐；System Prompt 段维度未对齐 | "工具维度已对齐 / System Prompt 段维度未对齐" |
| 5.18.2 always skills 注入 | "always=True/always=True，已对齐" | Cline 不支持 always 字段；Charles 有完整 always 预加载链路 | "Cline 无 always 字段 / Charles 有 always 预加载，未对齐" |
| 5.18.3 无技能时行为 | "不注入/不注入，已对齐" | 工具维度已对齐；System Prompt 段维度未对齐 | "工具维度已对齐 / System Prompt 段维度未对齐" |

**错误根源**：P5.18 计划表未区分"工具 description 维度"和"System Prompt 段维度"两个注入位置，且误将 Charles 的 `always` 字段等同于 Cline 的 `alwaysEnabled`（实际两者语义正交，详见 P5.10 §3.6）。本阶段修正这些错误。

### 3.5 Cline 的设计哲学：skills 永远 on-demand（5.18.10）

Cline 文档 `docs/customization/skills.mdx` L9 明确声明：

> "Unlike rules (which are always active), skills load on-demand so they don't consume context when you're working on something unrelated."

这是 Cline 的**核心设计哲学**：
- **rules**：always active，始终注入 System Prompt（通过 `effectiveRules`）。
- **skills**：on-demand，**永远不进入 System Prompt**，仅通过 `skills` 工具触发 Level 2 指令加载。

Cline 的条件注入逻辑严格遵循这一哲学：
- `createSkillsTool` 的 description getter 仅暴露技能**名清单**（`Available skills: name1, name2, ...`），不暴露指令内容。
- 技能指令（SKILL.md body）仅在 LLM 调用 `skills` 工具时通过 `tool_result` 返回，**不预加载到 System Prompt**。

**Charles 打破了这一边界**：通过 `enhancements` 配置开关引入 System Prompt 段注入路径，使部分 skills（`always: true`）的完整指令在启动时预加载到 System Prompt，部分 skills（on-demand）的摘要（name + when_to_use + description）作为 rule 注入。这是 nanobot 的设计模式——nanobot 不严格区分 rules 和 skills，skills 可以通过 `always: true` 标记为"始终激活"。

### 3.6 Charles 与 nanobot 的条件注入逻辑对照（5.18.12）

Charles 的条件注入逻辑是 nanobot 的复刻 + 适配：

| 组件 | nanobot 实现 | Charles 实现 | 残留性质 |
|------|-------------|-------------|---------|
| always_skills 条件注入 | `nanobot/agent/context.py` L53-57：`always_skills = self.skills.get_always_skills()` / `if always_skills:` / `parts.append(f"# Active Skills\n\n{always_content}")` | `agent/context.py` L632-636：`if self._enhancements.get("always_skills") and self.skills_registry:` / `body = self.skills_registry.load_always_instructions()` / `if body: rules.append(...)` | **复刻 + 适配**：从顶级段 `# Active Skills` 改为 `## charles-always-skills` rule（适配 Cline 的 base + rules 两层结构），新增 `enhancements` 双开关门控 |
| skills_summary 条件注入 | `nanobot/agent/context.py` L78-85：`skills_summary = self.skills.build_skills_summary()` / `if skills_summary:` / `parts.append(f"# Skills\n\n{skills_summary}")` | `agent/context.py` L638-642：`if self._enhancements.get("skills_summary") and self.skills_registry:` / `body = self.skills_registry.build_summary()` / `if body: rules.append(...)` | **复刻 + 适配**：从顶级段 `# Skills` 改为 `## charles-skills-summary` rule，新增 `enhancements` 双开关门控 |
| `get_always_skills()` 条件 | `nanobot/agent/skills.py` L203-211：遍历 `list_skills(filter_unavailable=True)`，检查 `skill_meta.get("always") or meta.get("always")` | `agent/skills/registry.py` L183-191：遍历 `self._skills.items()`，检查 `meta.always` | **1:1 复刻**，仅数据结构从 dict 改为 SkillMetadata |
| `build_skills_summary()` 条件 | `nanobot/agent/skills.py` L101-140：遍历技能构建 XML 格式摘要 | `agent/skills/registry.py` L210-252：遍历技能构建 Markdown 列表摘要 | **复刻 + 格式变更**：XML 改为 Markdown，新增 `when_to_use` 字段 |

**关键差异**：nanobot 的条件注入是**始终激活**的（无配置开关），Charles 引入 `enhancements.enabled` + `enhancements.skills_summary` / `enhancements.always_skills` 双开关门控，默认关闭。这是 Charles 对 nanobot 模式的"渐进式对齐 Cline"改造——保留 nanobot 的注入能力，但默认关闭以接近 Cline 的 on-demand 行为。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（5 处，2 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/skills/registry.py` | L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 标题 |
| `agent/skills/registry.py` | L20-22 | `对标 nanobot:\n    - build_skills_summary(): XML 格式技能列表\n    - get_always_skills(): always=True 的技能` | docstring 对标说明（明确标注 always 源自 nanobot） |
| `agent/skills/registry.py` | L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | class docstring 标题 |
| `agent/skills/registry.py` | L184 | `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()` | 方法 docstring（明确标注溯源） |
| `agent/context.py` | L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` | 参数 docstring（与 skills 注入无直接关系，但属 nanobot 风格残留说明） |

**注释残留小结**：
- 5 处注释残留均为 docstring 中的"对标 nanobot"或"nanobot 风格"说明，不影响运行时行为。
- 删除注释残留后，skills 段条件注入功能不变。

### 4.2 实现逻辑残留（2 处完整链路）

#### 4.2.1 skills_summary 条件注入链路（1 处）

**完整链路**：
1. `SkillMetadata.when_to_use` 字段（loader.py L81）—— 数据结构残留（Charles 独有增强，非 nanobot 字段，但用于 build_summary）。
2. `build_summary()`（registry.py L210-252）—— 构建逻辑残留，概念源自 nanobot `build_skills_summary()`（L101-140），格式从 XML 改为 Markdown。
3. `build_summary_as_rule()`（registry.py L254-263）—— 包装逻辑残留。
4. `_build_enhancement_rules()` 中 `charles-skills-summary` rule 生成（context.py L638-642）—— 注入逻辑残留。
5. `_load_enhancements()` 中 `skills_summary` 开关（context.py L322/L340）—— 配置逻辑残留。

**残留判定依据**：
1. **Cline 无等价物**：Cline 的 `buildClineSystemPrompt` 无 skills 段占位符，`effectiveRules` 不含 skills rule。
2. **nanobot 有原型**：nanobot `agent/context.py` L78-85 `# Skills` 段条件注入。
3. **Charles docstring 自证**：`registry.py` L20-22 明确标注 `build_skills_summary()` 源自 nanobot。
4. **实现完整可用**：受 `enhancements.enabled`（默认 False）+ `enhancements.skills_summary`（默认 True）双开关控制，非 dead code。

#### 4.2.2 always_skills 条件注入链路（1 处）

**完整链路**：
1. `SkillMetadata.always` 字段（loader.py L70）—— 数据结构残留。
2. `_parse_skill_file` 中 `always = bool(frontmatter.get("always", False))`（loader.py L234）—— 解析逻辑残留。
3. `get_always_skills()`（registry.py L183-191）—— 查询逻辑残留。
4. `load_always_instructions()`（registry.py L193-208）—— 加载逻辑残留。
5. `load_always_instructions_as_rule()`（registry.py L272-285）—— 包装逻辑残留（含"已自动加载"标注）。
6. `_build_enhancement_rules()` 中 `charles-always-skills` rule 生成（context.py L632-636）—— 注入逻辑残留。
7. `_load_enhancements()` 中 `always_skills` 开关（context.py L323/L340）—— 配置逻辑残留。
8. `agent_config/skills/read-pdf/SKILL.md` L5 `always: true` —— 实际配置残留。

**残留判定依据**：
1. **Cline 无等价物**：Cline 的 `SkillConfig` / `SkillMetadata` 均无 `always` 字段，`createSkillsTool` 纯 on-demand。
2. **nanobot 有原型**：nanobot `agent/skills.py` L203-211 `get_always_skills()` + `agent/context.py` L53-57 `# Active Skills` 段条件注入。
3. **Charles docstring 自证**：`registry.py` L184 明确标注 `get_always_skills()` 溯源 nanobot。
4. **实现完整可用**：受双开关控制，默认关闭但可启用。`agent_config/skills/read-pdf/SKILL.md` 实际配置了 `always: true`。

### 4.3 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（5 处）：仅在 docstring 中引用 "nanobot" 字样，不影响运行时行为。如 `registry.py` L184 `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`""`，这是设计溯源说明，删除后功能不变。

**实现逻辑残留**（2 处完整链路）：skills 段条件注入的完整实现链路，**影响运行时行为**：
- skills_summary 链路：若删除，`## charles-skills-summary` rule 不再注入 System Prompt，Charles 行为向 Cline 对齐（skills 清单仅通过工具 description 暴露）。
- always_skills 链路：若删除，`## charles-always-skills` rule 不再注入 System Prompt，Charles 行为向 Cline 对齐（skills 全部 on-demand）。

**关键区别**：若删除注释残留，功能不变；若删除实现逻辑残留，skills 段不再注入 System Prompt，Charles 行为向 Cline 的 on-demand 设计哲学对齐。

### 4.4 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（nanobot 对标说明） | 5 处 | 低 | 可保留作为设计溯源参考，或统一清理 |
| 实现逻辑残留（skills_summary 链路） | 1 处（含 5 个方法/字段/配置） | **中** | 默认关闭，不影响默认行为；启用后与 Cline 的 on-demand 哲学冲突 |
| 实现逻辑残留（always_skills 链路） | 1 处（含 8 个方法/字段/配置） | **高** | 默认关闭，但 always 字段与 Cline 的 on-demand 哲学根本冲突 |

---

## 五、与 P5.9 / P5.10 / P4.17 / P4.16 的关联和边界

### 5.1 与 P5.9 / P5.10 的关系

P5.9（skills 概览段内容）和 P5.10（always skills 段内容）对比的是 skills 段的**内容**（段落存在性、格式、字段、标注等）；P5.18 对比的是 skills 段的**条件注入逻辑**（何时注入、何时不注入、门控层数）。

| 维度 | P5.9 / P5.10 | P5.18 |
|------|--------------|-------|
| 对比焦点 | 段内容（格式、字段、标注） | 条件注入逻辑（门控层数、AND/OR 关系、默认值） |
| 侧重点 | 段长什么样 | 段何时出现 / 何时消失 |
| 计划文件状态 | P5.9 部分不准确，P5.10 严重错误 | P5.18 严重错误（3 项全部不准确） |
| 一致性结论 | 未对齐（段内容差异） | 未对齐（条件注入逻辑差异） |

### 5.2 与 P4.17 / P4.16 的关系

P4.17（skills_summary 段构建逻辑）和 P4.16（always_skills 段构建逻辑）对比的是 skills 段的**构建逻辑**（数据结构、解析、加载、注入链路）；P5.18 对比的是 skills 段的**条件注入逻辑**（构建逻辑的"是否触发"部分）。

| 维度 | P4.17 / P4.16 | P5.18 |
|------|---------------|-------|
| 对比范围 | 完整构建链路（frontmatter 字段 → 解析 → 加载 → 注入） | 仅条件注入部分（何时触发注入） |
| 侧重层面 | 实现层（数据结构、解析、加载、注入链路） | 条件层（门控层数、AND/OR 关系、默认值） |
| 一致性结论 | 未对齐（16 项 + 13 项全部未对齐） | 未对齐（12 项中 9 项未对齐，3 项工具维度对齐） |

### 5.3 P5.18 对 P4.16 / P4.17 / P5.9 / P5.10 的深化

P5.18 在已有结论的基础上，**深化了以下发现**：

1. **条件注入逻辑的层次分析**：P4.16 / P4.17 仅指出"Charles 有注入链路"，P5.18 明确指出 Charles 的注入条件是**三层 AND 关系**（总开关 + 子开关 + 非空校验），而 Cline 的工具 description 维度仅**一层条件**（`skills.length > 0`）。
2. **工具维度 vs System Prompt 段维度的区分**：P5.9 / P5.10 已指出"Charles 双位置"，P5.18 进一步明确两个位置的**条件逻辑不同**——位置 1 与 Cline 对齐（1 层条件），位置 2 是 Charles 独有（3 层条件门控）。
3. **计划文件 P5.18 标注修正**：P5.18 计划表的 3 项"已对齐"标注全部不准确，本阶段修正为"工具维度对齐 / System Prompt 段维度未对齐"。

---

## 六、修复建议

### 6.1 高优先级（P1）

无。skills 段条件注入默认关闭（`enhancements.enabled=False`），不影响默认运行时行为。当前 `agent_config/system_prompt.yaml` 配置 `enabled: false`，实际未注入 System Prompt。

### 6.2 中优先级（P2）

1. **修正计划文件 P5.18 的错误标注**：
   - 5.18.1 "skills 注入条件"：从"有技能时/有技能时，已对齐"改为"工具维度已对齐 / System Prompt 段维度未对齐"。
   - 5.18.2 "always skills 注入"：从"always=True/always=True，已对齐"改为"Cline 无 always 字段 / Charles 有 always 预加载，未对齐"。
   - 5.18.3 "无技能时行为"：从"不注入/不注入，已对齐"改为"工具维度已对齐 / System Prompt 段维度未对齐"。

2. **评估 skills_summary / always_skills 段的保留必要性**（与 P5.9 §6.2 / P5.10 §6.2 一致）：
   - **保留方案**：若 Charles 需要在 System Prompt 中预暴露技能清单（skills_summary）或预加载 always 技能指令（always_skills），可保留现有条件注入链路，但应在 docstring 中明确说明"这是 Charles 独有增强，Cline 无等价物，源自 nanobot 设计模式"。
   - **移除方案**：若严格对齐 Cline 的 on-demand 设计哲学，应移除 `_build_enhancement_rules()` 中的 `charles-skills-summary` / `charles-always-skills` rule 生成、`_load_enhancements()` 中的 `skills_summary` / `always_skills` 开关、以及相关 registry 方法。
   - **建议**：保留方案更务实（默认关闭，启用时有业务价值），但需修正 docstring 避免"对标 Cline"的误导性表述。

3. **修正 docstring 溯源标注**（registry.py L184）：
   - 当前：`"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`
   - 建议改为：`"""获取 always=True 的技能名称列表 — Charles 独有增强（源自 nanobot 设计模式，Cline 无等价物）`
   - 明确标注这是 Charles 独有增强，避免与 Cline 对标混淆。

### 6.3 低优先级（P3）

4. **nanobot 注释统一**（5 处）：可选择保留作为设计溯源，或统一清理为仅引用 Cline 对标位置。

5. **条件注入逻辑文档化**：在 `SystemPromptBuilder._build_enhancement_rules()` 的 docstring 中明确记录三层条件 AND 关系（总开关 + 子开关 + 非空校验），便于后续维护者理解门控逻辑。

---

## 七、验证方法建议

### 7.1 Cline 无 System Prompt 段注入验证

1. **Cline `effectiveRules` 无 skills 段**：
   ```
   Grep "skills|Skills" third_party/cline/sdk/packages/shared/src/prompt/cline.ts
   ```
   预期：仅在 `MODE_TAG_INSTRUCTIONS` 注释中出现，`effectiveRules` 数组（L145-151）不含 skills 项。

2. **Cline `system.ts` 模板无 Skills 章节**：
   ```
   Grep "Skills|skills" third_party/cline/sdk/packages/shared/src/prompt/system.ts
   ```
   预期：0 命中（base prompt 模板全文无 Skills 章节）。

3. **Cline 工具 description 条件注入验证**：
   ```
   Grep "Available skills|skills.length" third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts
   ```
   预期：命中 L756-760（`skills.length > 0` 条件 + `Available skills:` 追加）。

### 7.2 Charles 双位置条件注入验证

1. **位置 1（工具 description）条件注入**：
   ```python
   from agent.skills.skill_tool import SkillsTool
   from agent.skills.registry import SkillRegistry
   # 无技能场景
   registry = SkillRegistry(skills_dir="nonexistent")
   tool = SkillsTool(registry)
   assert "可用技能:" not in tool.description  # 无技能时不追加
   # 有技能场景
   registry = SkillRegistry(skills_dir="agent_config/skills")
   registry.discover()
   tool = SkillsTool(registry)
   assert "可用技能:" in tool.description  # 有技能时追加
   ```

2. **位置 2（System Prompt 增强层）条件注入**：
   ```python
   # 默认关闭验证
   from agent.context import SystemPromptBuilder
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-skills-summary" not in prompt  # 默认关闭
   assert "## charles-always-skills" not in prompt    # 默认关闭
   
   # 启用后注入验证（修改 agent_config/system_prompt.yaml 启用增强层）
   # enhancements:
   #   enabled: true
   #   skills_summary: true
   #   always_skills: true
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-skills-summary" in prompt  # 启用后注入
   assert "## charles-always-skills" in prompt   # read-pdf always:true
   ```

3. **三层条件 AND 关系验证**：
   ```python
   # 仅总开关关闭
   # enhancements: {enabled: false, skills_summary: true}
   assert "## charles-skills-summary" not in prompt  # 总开关关闭 → 不注入
   
   # 仅子开关关闭
   # enhancements: {enabled: true, skills_summary: false}
   assert "## charles-skills-summary" not in prompt  # 子开关关闭 → 不注入
   
   # 两个开关都开启但无技能
   # enhancements: {enabled: true, skills_summary: true}
   # registry 无技能
   assert "## charles-skills-summary" not in prompt  # 非空校验失败 → 不注入
   ```

### 7.3 Cline 无 always 字段验证

1. **`SkillConfig` 无 `always` 字段**：
   ```
   Grep "always" third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts
   ```
   预期：0 命中（`SkillConfig` L42-48 仅 5 字段）。

2. **`SkillMetadata` 无 `always` 字段**：
   ```
   Grep "always" third_party/cline/apps/vscode/src/shared/skills.ts
   ```
   预期：0 命中（`SkillMetadata` L5-17 仅 4 字段）。

### 7.4 nanobot 残留验证

1. **实现逻辑残留验证**：
   ```
   Grep "build_summary|load_always_instructions|get_always_skills" agent/
   ```
   预期：命中 `agent/skills/registry.py` L183/L193/L210/L272 + `agent/context.py` L632/L638

2. **nanobot 溯源验证**：
   ```
   Grep "get_always_skills|build_skills_summary" third_party/charles_bundle/nanobot-main/
   ```
   预期：命中 `nanobot/agent/skills.py` L203（`get_always_skills` 原型）+ L101（`build_skills_summary` 原型）

3. **实际配置验证**：
   ```
   Grep "^always: true" agent_config/skills/
   ```
   预期：命中 `agent_config/skills/read-pdf/SKILL.md` L5

### 7.5 计划文件错误标注验证

1. **P5.18 计划表"已对齐"标注验证**：
   - 5.18.1：Cline `buildClineSystemPrompt`（cline.ts L110-166）`effectiveRules` 无 skills 段 → "已对齐"错误
   - 5.18.2：Cline `SkillConfig` 无 `always` 字段 → "已对齐"错误
   - 5.18.3：Cline 无 System Prompt 段注入路径 → "已对齐"错误

---

## 八、一致性总评

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| 工具 description 维度条件注入 | **完全对齐** | 两者均 `skills.length > 0` 时注入，无技能时返回 base |
| System Prompt 段维度条件注入 | **未对齐** | Cline 无此路径；Charles 有三层门控（默认关闭） |
| skills_summary 注入条件 | **未对齐**（System Prompt 段维度） | Cline 无此段；Charles 三层 AND 门控 |
| always_skills 注入条件 | **未对齐** | Cline 不支持 always 字段；Charles 有完整预加载链路 |
| 无技能时行为 | **工具维度对齐，System Prompt 段维度未对齐** | 工具维度均不追加；System Prompt 段维度 Cline 无此段，Charles 默认关闭 |
| 条件门控层数 | **未对齐** | Cline 1 层（工具维度）；Charles 位置 1 1 层 + 位置 2 3 层 |
| 计划文件 P5.18 标注 | **错误** | 3 项"已对齐"全部不准确，应为"工具维度对齐 / System Prompt 段维度未对齐" |
| nanobot 残留 | **2 处实现逻辑残留 + 5 处注释残留** | skills_summary + always_skills 条件注入链路源自 nanobot |

**总体结论**：Charles 的 Skills 段条件注入逻辑在**工具 description 维度已与 Cline 完全对齐**（两者均 `skills.length > 0` 时注入），但在 **System Prompt 段维度未对齐** —— Cline 严格遵循"skills 永远 on-demand"的设计哲学，无任何 System Prompt 段注入路径；Charles 通过 `enhancements` 双开关 + 非空校验形成三层条件门控，引入了 `## charles-skills-summary` / `## charles-always-skills` rule 注入路径（默认关闭）。Charles 的 System Prompt 段条件注入逻辑是**完整的 nanobot 实现逻辑残留**（2 处链路），非纯注释残留（5 处）。计划文件 P5.18 的 3 项"已对齐"标注全部不准确，应修正为"工具维度对齐 / System Prompt 段维度未对齐"，与 P4.16 / P4.17 / P5.9 / P5.10 的结论保持一致。
