# Phase 4.16 always_skills 段对比

> 对比范围：Cline System Prompt 中是否存在 always_skills 段、`alwaysEnabled` / `always` 标记的语义、always 技能指令注入到 System Prompt 的方式与时机、always 技能与 on-demand 技能的区别；nanobot 风格残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段深入对比 P4.2/P4.3 已发现的"Charles always 机制是 nanobot 风格残留、Cline 无 always 预加载"这一差异，聚焦 System Prompt 注入层面的实现细节。
>
> Cline 源码：
> - `sdk/packages/shared/src/remote-config/schema.ts` L123-147（`RemoteMCPServerSchema.alwaysEnabled` + `GlobalInstructionsFileSchema.alwaysEnabled` 定义）
> - `sdk/packages/shared/src/remote-config/materializer.ts` L69-79（`buildRulesMarkdown` 中 `_Always enabled_` 标记注入）
> - `apps/vscode/src/core/context/instructions/user-instructions/skills.ts` L84-125（`ValidatedRemoteSkill.alwaysEnabled` + `parseRemoteSkillEntries` 仅作透传不写入 SkillMetadata）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L261-297（`getRemoteRulesTotalContentWithMetadata` 中 `rule.alwaysEnabled || remoteToggles[rule.name] !== false` 强制启用逻辑）
> - `apps/vscode/src/shared/skills.ts` L1-17（`SkillMetadata` 接口仅 4 字段，无 `always`）
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L42-48（`SkillConfig` 接口仅 5 字段，无 `always`）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L75-217（`getConfiguredSkillsFromWatcher` + `createUserInstructionSkillsExecutor` 无 always 预加载路径）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L362-435（skills 工具注册流程无 always 预加载）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L714-769（`createSkillsTool` 纯 on-demand 加载）
>
> Charles 源码：
> - `agent/skills/loader.py` L70（`SkillMetadata.always: bool = False`）+ L234（`always = bool(frontmatter.get("always", False))` frontmatter 解析）
> - `agent/skills/registry.py` L183-191（`get_always_skills()`）+ L193-208（`load_always_instructions()`）+ L272-285（`load_always_instructions_as_rule()`）
> - `agent/context.py` L304-346（`_load_enhancements` 配置默认 `always_skills: True`）+ L520-528（`_build_rules` 增强层注入）+ L611-647（`_build_enhancement_rules` 中 `charles-always-skills` rule 生成）
> - `agent/prompts/charles_system_prompt.py` L29-58（`DEFAULT_CHARLES_SYSTEM_PROMPT` 模板，`{{CHARLES_RULES}}` 占位符承载 always_skills rule）
> - `agent_config/skills/read-pdf/SKILL.md` L5（`always: true` 实际配置）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/skills.py` L203-211（`get_always_skills()` 原型）
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py` L53-57（`# Active Skills` 段注入）
> - `third_party/charles_bundle/nanobot-main/nanobot/skills/memory/SKILL.md` L4（`always: true`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 System Prompt 中"always_skills 段"的实现。**核心结论：Cline 的 System Prompt 中不存在 always_skills 段，Cline 的 skills 永远是 on-demand 加载（通过 `skills` 工具触发）；Charles 的 System Prompt 中存在 `## charles-always-skills` rule 段，将 `always: true` 技能的完整指令在启动时预加载到 System Prompt。** 这一差异是 P4.2/P4.3 已发现的"Charles always 机制是 nanobot 风格残留"在 System Prompt 注入层面的具体体现。

### 核心结论

1. **always_skills 段是否存在**：**Cline 不存在**，**Charles 存在**（`## charles-always-skills` rule）。Cline 的 `SkillConfig` / `SkillMetadata` 均无 `always` 字段；Charles 的 `SkillMetadata.always` 字段从 frontmatter 解析，并通过 `load_always_instructions_as_rule()` 包装为 rule 注入。

2. **always 标记语义**：**语义完全不同**。
   - **Cline `alwaysEnabled`**：仅出现在**远程企业配置**（`GlobalInstructionsFileSchema` / `RemoteMCPServerSchema`），语义是"用户不可在 UI toggle off"（强制启用策略），**与预加载无关**。Cline 的 `SkillConfig` frontmatter 不支持 `always` 字段，`SkillMetadata` 接口也不含 `alwaysEnabled`。
   - **Charles `always`**：从 SKILL.md frontmatter 解析，语义是"启动时预加载完整指令到 System Prompt"（Level 2 预加载），**与禁用策略无关**。

3. **always 技能注入方式**：
   - **Cline**：无注入。所有 skills 指令仅通过 `skills` 工具的 `tool_result` 在对话中按需加载，返回 `<command-instructions>` XML 格式，主 agent 在后续轮次中执行。
   - **Charles**：通过 `SystemPromptBuilder._build_enhancement_rules()`（context.py L632-636）调用 `SkillRegistry.load_always_instructions()` 获取拼接后的指令文本，包装为 `## charles-always-skills` rule，追加到 `effectiveRules` 末尾，经 `{{CHARLES_RULES}}` 占位符注入到 System Prompt。

4. **always 技能注入时机**：
   - **Cline**：不注入（无此机制）。
   - **Charles**：在 `SystemPromptBuilder.build()` 调用 `_build_rules()` 时注入（context.py L520-528），即**每次构建 System Prompt 时**（每轮对话或每次 session 恢复）都会重新加载 always 技能指令并注入。受 `enhancements.enabled` 和 `enhancements.always_skills` 双开关控制（默认 `enabled=False`，所有增强层关闭）。

5. **always 技能与 on-demand 技能的区别**：
   - **Cline**：**无区别**——所有 skills 都是 on-demand，均通过 `skills` 工具触发加载，Cline 文档（skills.mdx L9）明确声明"Unlike rules (which are always active), skills load on-demand"。
   - **Charles**：always 技能在 System Prompt 启动时即生效（LLM 无需调用 `skills` 工具即可看到指令）；on-demand 技能仅在 LLM 调用 `skills` 工具后才注入指令到对话上下文。两者共存：always 技能的指令既出现在 System Prompt 的 `## charles-always-skills` 段，也可能出现在 `skills` 工具的可用列表中（LLM 仍可调用，但会触发 `runningSkills` 去重，返回 "already running" 提示）。

6. **nanobot 残留**：**Charles 的 always_skills 段是完整的 nanobot 实现逻辑残留**，非纯注释残留。溯源到 nanobot `agent/skills.py` L203-211 `get_always_skills()` + `agent/context.py` L53-57 `# Active Skills` 段注入。Charles 的实现是对 nanobot 机制的 1:1 复刻（仅包装格式从 `# Active Skills` 改为 `## charles-always-skills` rule）。

### 一致性总体评估

- **always_skills 段存在性**：**未对齐**。Cline 无此段，Charles 有此段。
- **always 标记语义**：**未对齐**。Cline 的 `alwaysEnabled` 是禁用策略，Charles 的 `always` 是预加载策略，两者语义正交。
- **注入方式**：**未对齐**。Cline 无注入，Charles 通过 rule 注入。
- **注入时机**：**未对齐**。Cline 无注入，Charles 在 System Prompt 构建时注入。
- **always vs on-demand 区分**：**未对齐**。Cline 不区分（全部 on-demand），Charles 区分（always 预加载 + on-demand 工具触发）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.16.1 | always_skills 段是否存在 | **不存在**。System Prompt 中无 always_skills 段；`SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillMetadata`（skills.ts L5-10）均无 `always` 字段 | **存在**。`## charles-always-skills` rule 段（registry.py L272-285），通过 `{{CHARLES_RULES}}` 占位符注入 System Prompt | 未对齐 | Charles 独有，源自 nanobot |
| 4.16.2 | `always` frontmatter 字段 | **不支持**。SKILL.md frontmatter 仅支持 `name` / `description` / `disabled` / `enabled`（user-instruction-config-loader.ts L42-48） | **支持**。`always: bool = False`（loader.py L70），从 frontmatter 解析（L234 `bool(frontmatter.get("always", False))`） | 未对齐 | Charles 独有字段 |
| 4.16.3 | `alwaysEnabled` 语义 | **禁用策略**：仅用于远程企业配置（`GlobalInstructionsFileSchema` / `RemoteMCPServerSchema`），表示"用户不可在 UI toggle off"。`rule-helpers.ts` L271 `rule.alwaysEnabled || remoteToggles[rule.name] !== false` 强制启用 | **预加载策略**：`always: true` 表示"启动时预加载完整指令到 System Prompt"。与禁用策略无关 | 未对齐 | 语义正交，不可混用 |
| 4.16.4 | `alwaysEnabled` 适用范围 | **仅 remote skill / remote rule / remote MCP**。`parseRemoteSkillEntries`（skills.ts L105-125）仅处理 `GlobalInstructionsFile[]`；本地 SKILL.md 的 `SkillConfig` 无此字段 | **所有 skill**。任何 SKILL.md 均可声明 `always: true`（如 `agent_config/skills/read-pdf/SKILL.md` L5） | 未对齐 | Cline 远程专属，Charles 本地通用 |
| 4.16.5 | `alwaysEnabled` 是否写入 SkillMetadata | **不写入**。`parseRemoteSkillEntries` 返回 `ValidatedRemoteSkill`（含 `alwaysEnabled`），但 `discoverSkills`（skills.ts L239-244）映射到 `SkillMetadata` 时丢弃该字段（接口无定义） | **写入**。`SkillMetadata.always` 字段（loader.py L70）持久化 | 未对齐 | Cline 仅运行时透传，Charles 持久化 |
| 4.16.6 | always 技能指令注入到 System Prompt | **不注入**。skills 指令仅通过 `skills` 工具的 `tool_result` 按需加载（definitions.ts L714-769） | **注入**。`load_always_instructions()`（registry.py L193-208）拼接所有 always 技能指令，包装为 `## charles-always-skills` rule（L272-285），经 `{{CHARLES_RULES}}` 注入 | 未对齐 | 核心差异 |
| 4.16.7 | always 技能注入时机 | **不注入**（无此机制） | **System Prompt 构建时**。`SystemPromptBuilder._build_rules()` → `_build_enhancement_rules()`（context.py L632-636）每次构建 System Prompt 时重新加载 | 未对齐 | Charles 每轮重新注入 |
| 4.16.8 | always 段开关控制 | **无此段，无开关** | **双开关**：`enhancements.enabled`（总开关，默认 False）+ `enhancements.always_skills`（子开关，默认 True）。总开关关闭时所有增强层关闭（context.py L338-343） | 未对齐 | Charles 默认关闭，需显式开启 |
| 4.16.9 | always 段包装格式 | **无此段** | `## charles-always-skills\n\n以下常驻技能指令已自动加载，无需调用 skills 工具即可生效:\n\n{instructions}`（registry.py L281-285） | 未对齐 | Charles rule 格式 |
| 4.16.10 | always 段在 System Prompt 中的位置 | **无此段** | `{{CHARLES_RULES}}` 占位符内，位于 effectiveRules 末尾（在 MODE_TAG / PLAN_MODE / tools-overview / mcp-overview 之后，skills-summary / memory 之前，context.py L620-646） | 未对齐 | Charles 在 rules 段尾部 |
| 4.16.11 | always 技能 vs on-demand 技能 | **无区别**。所有 skills 均 on-demand，通过 `skills` 工具触发（definitions.ts L714-769）。skills.mdx L9 明确："Unlike rules (which are always active), skills load on-demand" | **有区别**。always 技能在 System Prompt 启动时生效；on-demand 技能需 LLM 调用 `skills` 工具后才注入。always 技能仍出现在 `skills` 工具的可用列表中（LLM 可调用但会触发 runningSkills 去重） | 未对齐 | 设计哲学差异 |
| 4.16.12 | always 技能去重机制 | **无此机制** | **无独立去重**。always 技能注入 System Prompt 后，若 LLM 再次调用 `skills` 工具加载同一技能，`SkillsTool._running_skills`（skill_tool.py L73）会返回 "already running" 提示，但这是工具层去重，非 always 段去重 | 弱对齐 | Charles 工具层有去重，always 段无去重 |
| 4.16.13 | always 技能指令内容 | **无此机制** | 完整 SKILL.md body（去 frontmatter）+ 自动追加的 `## 可用脚本` 段（loader.py L176-184）。多个 always 技能用 `\n\n---\n\n` 分隔（registry.py L208） | 未对齐 | Charles 注入完整指令 |
| 4.16.14 | always 技能 token 占用 | **无此机制** | 每个 always 技能的完整指令（<5k tokens/技能，loader.py L160 注释）注入 System Prompt。多个 always 技能累积可能显著增加 System Prompt 长度 | 未对齐 | Charles 有 token 成本 |
| 4.16.15 | 实际配置中的 always 技能 | **无此字段** | `agent_config/skills/read-pdf/SKILL.md` L5 `always: true`（唯一实际配置）。nanobot 原生 `skills/memory/SKILL.md` L4 也有 `always: true` | 未对齐 | Charles 实际启用 1 个 always 技能 |
| 4.16.16 | nanobot 溯源 | **无此机制** | `nanobot/agent/skills.py` L203-211 `get_always_skills()` + `nanobot/agent/context.py` L53-57 `# Active Skills` 段注入。Charles 1:1 复刻，仅包装格式从 `# Active Skills` 改为 `## charles-always-skills` rule | 未对齐 | nanobot 实现逻辑残留 |

---

## 三、重点差距详细说明

### 3.1 Cline 的 `alwaysEnabled` 与 Charles 的 `always` 语义正交（4.16.3 / 4.16.4）

这是本阶段最关键的差异。两者虽然字面相似，但**语义完全不同、适用范围不同、实现位置不同**，不可混用。

**Cline `alwaysEnabled`**：

- **定义位置**：`sdk/packages/shared/src/remote-config/schema.ts` L140-147（`GlobalInstructionsFileSchema`）+ L128-137（`RemoteMCPServerSchema`）。仅用于**远程企业配置**（`RemoteConfig`），不下发到本地 SKILL.md frontmatter。
- **语义**：`schema.ts` L142 注释 "When this is enabled, the user cannot turn off this rule or workflow" —— **强制启用策略**，用户无法在 UI 中关闭。
- **实现**：`rule-helpers.ts` L271 `const isEnabled = rule.alwaysEnabled || remoteToggles[rule.name] !== false` —— `alwaysEnabled=true` 时**跳过 toggle 检查**，强制纳入 rules 内容。但这是 **rules 系统的机制**（globalRules / globalWorkflows），不是 skills 系统。
- **skills 系统的处理**：`parseRemoteSkillEntries`（skills.ts L105-125）将 `entry.alwaysEnabled` 透传到 `ValidatedRemoteSkill`，但 `discoverSkills`（L239-244）映射到 `SkillMetadata` 时**丢弃该字段**（`SkillMetadata` 接口无定义，skills.ts L5-10 仅 4 字段）。即 Cline 的 `alwaysEnabled` 对 skills **仅作元数据透传，不触发任何预加载行为**。

**Charles `always`**：

- **定义位置**：`agent/skills/loader.py` L70 `always: bool = False`，从 SKILL.md frontmatter 解析（L234）。
- **语义**：`registry.py` L186-187 docstring "always=True 的技能会在启动时自动加载指令到 system prompt，而不需要 LLM 通过 use_skill 工具触发" —— **预加载策略**。
- **实现**：`registry.py` L183-191 `get_always_skills()` 返回 always=True 的技能名列表 → L193-208 `load_always_instructions()` 加载完整指令并拼接 → L272-285 `load_always_instructions_as_rule()` 包装为 rule → `context.py` L632-636 注入 System Prompt。
- **与禁用策略无关**：Charles 的 `always` 不影响 `disabled` 字段，always 技能仍可通过 `skills` 工具调用（但会触发 runningSkills 去重）。

**语义对比表**：

| 维度 | Cline `alwaysEnabled` | Charles `always` |
|------|----------------------|-----------------|
| 定义位置 | `RemoteConfig` schema（远程企业配置） | SKILL.md frontmatter（本地技能配置） |
| 适用对象 | globalRules / globalWorkflows / remoteMCP（非 skills） | 所有 skills |
| 语义 | 用户不可 toggle off（强制启用） | 启动时预加载指令到 System Prompt |
| skills 系统影响 | 无（`SkillMetadata` 不含此字段，丢弃） | 有（`SkillMetadata.always` 持久化，触发预加载） |
| 注入 System Prompt | 不注入（仅影响 toggle 行为） | 注入（`## charles-always-skills` rule） |
| 用户可配置 | 否（企业配置下发） | 是（SKILL.md frontmatter `always: true`） |

### 3.2 Cline 的设计哲学：skills 永远 on-demand（4.16.11）

Cline 文档 `docs/skills.mdx` L9 明确声明：

> "Unlike rules (which are always active), skills load on-demand"

这是 Cline 的**核心设计哲学**：
- **rules**：always active，始终注入 System Prompt（通过 `effectiveRules`）
- **skills**：on-demand，仅当 LLM 调用 `skills` 工具时才加载指令

Cline 严格区分 rules 和 skills 的加载模型：
- rules 的 frontmatter 有 `alwaysApply` 字段（rules.mdx），控制是否始终注入
- skills 的 frontmatter **无 `always` 字段**，永远通过 `skills` 工具触发

**Charles 打破了这一边界**：将 rules 的 `alwaysApply` 概念引入 skills，创造出 `always: true` 的 skill 字段，使部分 skills 也能"始终注入"。这是 nanobot 的设计模式——nanobot 不严格区分 rules 和 skills，skills 可以通过 `always: true` 标记为"始终激活"。

### 3.3 Charles 的 always_skills 段注入流程详解（4.16.6 / 4.16.7 / 4.16.10）

Charles 的 always_skills 段注入流程如下：

```
SystemPromptBuilder.build()
  └─ _build_rules(task_type)                          # context.py L454-539
      └─ _build_enhancement_rules()                   # context.py L611-647
          └─ if enhancements.always_skills and skills_registry:
                body = skills_registry.load_always_instructions()  # context.py L634
                rules.append(("charles-always-skills", body))      # context.py L636
      └─ format_rules_content(results)                # rules_loader.py
          └─ 每条 rule 添加 ## 标题，拼接为 # Rules 段
  └─ build_charles_system_prompt(rules_text=rules_text, ...)  # context.py L382-391
      └─ prompt.replace("{{CHARLES_RULES}}", rules_text)      # context.py L117
```

**关键点**：
1. always_skills 段作为 **rule** 注入，不是独立的 System Prompt 段。
2. 注入位置在 `{{CHARLES_RULES}}` 占位符内，位于 effectiveRules 末尾。
3. always_skills 段在 `charles-tools-overview` / `charles-mcp-overview` 之后，`charles-skills-summary` / `charles-memory` 之前（context.py L620-646 顺序）。
4. 每次构建 System Prompt 时都会重新加载 always 技能指令（无缓存）。
5. 受 `enhancements.enabled`（默认 False）和 `enhancements.always_skills`（默认 True）双开关控制——**默认情况下 always_skills 段不注入**（因总开关默认关闭）。

### 3.4 Charles 的 always_skills 段默认关闭（4.16.8）

Charles 的 `SystemPromptBuilder._load_enhancements()`（context.py L304-346）读取 `agent_config/system_prompt.yaml` 配置：

```python
# context.py L319-326
default = {
    "enabled": False,         # 总开关默认关闭
    "tools_section": True,
    "skills_summary": True,
    "always_skills": True,    # 子开关默认 True
    "mcp_section": True,
    "memory": True,
}
```

**默认行为**：`enhancements.enabled` 为 `False`，所有增强层（含 always_skills）均关闭。即**默认情况下 Charles 的 System Prompt 中不包含 `## charles-always-skills` 段**。

**启用条件**：需在 `agent_config/system_prompt.yaml` 中显式设置 `enhancements.enabled: true` 且 `enhancements.always_skills: true`。

**实际影响**：当前 `agent_config/system_prompt.yaml` 不存在（Glob 搜索无结果），因此 Charles 使用默认配置，always_skills 段**实际未注入** System Prompt。但这不影响代码层面的差异分析——Charles 具备注入能力，Cline 不具备。

### 3.5 always 技能与 on-demand 技能在 Charles 中的共存问题（4.16.12）

Charles 的 always 技能在 System Prompt 中预加载后，仍会出现在 `skills` 工具的可用列表中（`SkillsTool._build_description()` L225-253 调用 `list_skills()` 不过滤 always 技能）。这导致一个潜在问题：

1. LLM 看到 System Prompt 中的 always 技能指令（已预加载）
2. LLM 同时在 `skills` 工具 description 中看到该技能名（可用列表）
3. LLM 可能调用 `skills(skill="read-pdf")` 加载该技能
4. `SkillsTool._execute` 检查 `runningSkills`（skill_tool.py L176-181），若该技能未在运行中则正常加载，返回 `<command-instructions>` XML（指令重复注入对话上下文）

**结果**：always 技能的指令可能同时出现在 System Prompt 和对话上下文中，造成**指令重复**。Charles 的 `runningSkills` 去重仅防止"同一技能并发调用"，不防止"System Prompt 已注入 + 工具再次加载"。

**Cline 无此问题**：Cline 的 skills 全部 on-demand，System Prompt 中无预加载指令，LLM 只能通过 `skills` 工具加载。

---

## 四、nanobot 残留专项检查

### 4.1 实现逻辑残留（1 处，核心残留）

Charles 的 always_skills 段是**完整的 nanobot 实现逻辑残留**，非纯注释残留。溯源对比如下：

| 组件 | nanobot 实现 | Charles 实现 | 残留性质 |
|------|-------------|-------------|---------|
| `get_always_skills()` | `nanobot/agent/skills.py` L203-211：遍历 `list_skills()`，检查 `skill_meta.get("always") or meta.get("always")`，返回技能名列表 | `agent/skills/registry.py` L183-191：遍历 `self._skills.items()`，检查 `meta.always`，返回技能名列表 | **1:1 复刻**，仅数据结构从 dict 改为 SkillMetadata |
| 指令加载 | `nanobot/agent/skills.py` `load_skills_for_context(always_skills)`（context.py L55 调用） | `agent/skills/registry.py` L193-208 `load_always_instructions()`：加载每个技能指令，用 `\n\n---\n\n` 拼接 | **1:1 复刻**，仅拼接分隔符可能不同 |
| System Prompt 注入 | `nanobot/agent/context.py` L53-57：`parts.append(f"# Active Skills\n\n{always_content}")` | `agent/skills/registry.py` L272-285 `load_always_instructions_as_rule()` + `agent/context.py` L632-636：包装为 `## charles-always-skills` rule，经 `{{CHARLES_RULES}}` 注入 | **复刻 + 适配**：从 `# Active Skills` 独立段改为 `## charles-always-skills` rule（适配 Cline 的 base + rules 两层结构） |
| frontmatter 字段 | `nanobot/skills/memory/SKILL.md` L4 `always: true` | `agent_config/skills/read-pdf/SKILL.md` L5 `always: true` | **1:1 复刻** |

**残留判定依据**：
1. **Cline 无等价物**：Cline 的 `SkillConfig` / `SkillMetadata` 均无 `always` 字段，`user-instruction-plugin.ts` 无 always 预加载路径，`createSkillsTool` 纯 on-demand。
2. **nanobot 有原型**：nanobot `get_always_skills()` + `# Active Skills` 段注入是完整实现。
3. **Charles docstring 自证**：`registry.py` L184 `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`""`，明确标注溯源。
4. **实现完整可用**：Charles 的 always_skills 段非 dead code，受配置开关控制，默认关闭但可启用。`agent_config/skills/read-pdf/SKILL.md` 实际配置了 `always: true`。

### 4.2 注释残留（4 处，2 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/skills/registry.py` | L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 标题 |
| `agent/skills/registry.py` | L20-22 | `对标 nanobot:\n    - build_skills_summary(): XML 格式技能列表\n    - get_always_skills(): always=True 的技能` | docstring 对标说明（明确标注 always 源自 nanobot） |
| `agent/skills/registry.py` | L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | class docstring 标题 |
| `agent/skills/registry.py` | L184 | `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()` | 方法 docstring（明确标注溯源） |

**注释残留小结**：
- 4 处注释残留全部集中在 `agent/skills/registry.py`，均为 docstring 中的"对标 nanobot"说明。
- `agent/context.py` 中无 nanobot 注释残留（context.py 的 always_skills 注入逻辑用 Cline 风格的 `effectiveRules` + `enhancements` 包装，无 nanobot 字面引用）。
- `agent/skills/loader.py` 的 nanobot 注释残留已在 P4.2 报告中详述，本阶段不重复。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 实现逻辑残留（always_skills 段） | 1 处（含 3 个方法 + 1 个字段 + 1 个配置） | **高** | always_skills 段与 Cline 的 on-demand 设计哲学冲突，建议评估是否保留 |
| 注释残留（nanobot 对标说明） | 4 处 | 低 | 可保留作为设计溯源参考，或统一清理 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（4 处）：仅在 docstring 中引用 "nanobot" 字样，不影响运行时行为。如 `registry.py` L184 `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`""`，这是设计溯源说明，删除后功能不变。

**实现逻辑残留**（1 处）：always_skills 段的完整实现链路，**影响运行时行为**：
- `SkillMetadata.always` 字段（loader.py L70）—— 数据结构残留
- `_parse_skill_file` 中 `always = bool(frontmatter.get("always", False))`（loader.py L234）—— 解析逻辑残留
- `get_always_skills()`（registry.py L183-191）—— 查询逻辑残留
- `load_always_instructions()`（registry.py L193-208）—— 加载逻辑残留
- `load_always_instructions_as_rule()`（registry.py L272-285）—— 包装逻辑残留
- `_build_enhancement_rules()` 中 `charles-always-skills` rule 生成（context.py L632-636）—— 注入逻辑残留
- `_load_enhancements()` 中 `always_skills` 开关（context.py L323/L340）—— 配置逻辑残留
- `agent_config/skills/read-pdf/SKILL.md` L5 `always: true` —— 实际配置残留

**关键区别**：若删除注释残留，功能不变；若删除实现逻辑残留，always_skills 段不再注入 System Prompt，Charles 行为向 Cline 对齐（skills 全部 on-demand）。

---

## 五、修复建议

### 5.1 高优先级（P1）

无。always_skills 段默认关闭（`enhancements.enabled=False`），不影响默认运行时行为。且 `agent_config/system_prompt.yaml` 不存在，实际未注入 System Prompt。

### 5.2 中优先级（P2）

1. **评估 always_skills 段的保留必要性**：
   - **保留方案**：若 Charles 需要预加载某些技能指令（如 read-pdf 用于高频年报查询），可保留 always_skills 段，但应在 docstring 中明确说明"这是 Charles 独有增强，Cline 无等价物，源自 nanobot 设计模式"。
   - **移除方案**：若严格对齐 Cline 的 on-demand 设计哲学，应移除 `SkillMetadata.always` 字段、`get_always_skills()` / `load_always_instructions()` / `load_always_instructions_as_rule()` 方法、`_build_enhancement_rules()` 中的 `charles-always-skills` rule 生成、`_load_enhancements()` 中的 `always_skills` 开关、以及 `agent_config/skills/read-pdf/SKILL.md` 的 `always: true` 配置。
   - **建议**：保留方案更务实（read-pdf 预加载有业务价值），但需修正 docstring 避免"对标 Cline"的误导性表述。

2. **修正 docstring 溯源标注**（registry.py L184）：
   - 当前：`"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`
   - 建议改为：`"""获取 always=True 的技能名称列表 — Charles 独有增强（源自 nanobot 设计模式，Cline 无等价物）`
   - 明确标注这是 Charles 独有增强，避免与 Cline 对标混淆。

3. **解决 always 技能指令重复问题**（4.16.12 / 3.5）：
   - always 技能预加载到 System Prompt 后，`SkillsTool._build_description()` 应在可用列表中过滤掉 always 技能（或标注"已预加载"），避免 LLM 重复调用 `skills` 工具加载同一技能。
   - 或在 `SkillsTool._execute()` 中检查技能是否已 always 预加载，若是则返回提示"该技能指令已在 System Prompt 中预加载，无需重复调用"。

### 5.3 低优先级（P3）

4. **nanobot 注释统一**（4 处）：可选择保留作为设计溯源，或统一清理为仅引用 Cline 对标位置。

5. **always_skills 段 token 成本监控**（4.16.14）：若启用 always_skills 段，应在 `SystemPromptBuilder` 中记录 always 技能指令的 token 占用，便于调试 System Prompt 过长问题。当前 `estimate_tokens()`（context.py L897-910）已支持 token 估算，但未针对 always_skills 段单独统计。

---

## 六、验证方法建议

### 6.1 always_skills 段存在性验证

1. **Cline 无 always_skills 段**：
   ```
   Grep "always_skills|alwaysSkills|charles-always-skills" third_party/cline/sdk/packages/core/src/
   ```
   预期：0 命中（Cline 无此概念）

2. **Charles 有 always_skills 段**：
   ```
   Grep "charles-always-skills|load_always_instructions|get_always_skills" agent/
   ```
   预期：命中 `agent/skills/registry.py` + `agent/context.py`

### 6.2 Cline `alwaysEnabled` 语义验证

1. **`alwaysEnabled` 仅在 remote-config schema**：
   ```
   Grep "alwaysEnabled" third_party/cline/sdk/packages/shared/src/remote-config/
   ```
   预期：命中 `schema.ts`（定义）+ `materializer.ts`（`_Always enabled_` 标记）+ `runtime.test.ts`（测试）

2. **`alwaysEnabled` 不在 SkillConfig / SkillMetadata**：
   ```
   Grep "alwaysEnabled" third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts
   Grep "alwaysEnabled" third_party/cline/apps/vscode/src/shared/skills.ts
   ```
   预期：0 命中（`SkillConfig` L42-48 + `SkillMetadata` L5-10 均无此字段）

3. **`alwaysEnabled` 在 skills.ts 中仅透传**：
   ```
   Grep "alwaysEnabled" third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/skills.ts
   ```
   预期：命中 L92（`ValidatedRemoteSkill.alwaysEnabled`）+ L120（`alwaysEnabled: entry.alwaysEnabled` 透传），不触发预加载

### 6.3 Charles always_skills 段注入验证

1. **默认关闭验证**：
   ```python
   from agent.context import SystemPromptBuilder
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-always-skills" not in prompt  # 默认关闭
   ```

2. **启用后注入验证**：
   ```python
   # 创建 agent_config/system_prompt.yaml 启用增强层
   # enhancements:
   #   enabled: true
   #   always_skills: true
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-always-skills" in prompt
   assert "read-pdf" in prompt  # read-pdf SKILL.md 配置了 always: true
   ```

3. **always 技能指令内容验证**：
   ```python
   from agent.skills.registry import SkillRegistry
   registry = SkillRegistry(skills_dir="agent_config/skills")
   registry.discover()
   always_instructions = registry.load_always_instructions()
   assert "read-pdf" in always_instructions
   assert "本技能核心能力" in always_instructions  # read-pdf SKILL.md body 内容
   ```

### 6.4 nanobot 残留验证

1. **实现逻辑残留验证**：
   ```
   Grep "get_always_skills|load_always_instructions|load_always_instructions_as_rule" agent/
   ```
   预期：命中 `agent/skills/registry.py` L183/L193/L272

2. **nanobot 溯源验证**：
   ```
   Grep "get_always_skills" third_party/charles_bundle/nanobot-main/
   ```
   预期：命中 `nanobot/agent/skills.py` L203（原型）

3. **实际配置验证**：
   ```
   Grep "^always: true" agent_config/skills/
   ```
   预期：命中 `agent_config/skills/read-pdf/SKILL.md` L5

### 6.5 always vs on-demand 区分验证

1. **Cline 全部 on-demand**：
   - 验证 `createSkillsTool`（definitions.ts L714-769）是唯一的 skill 指令加载入口
   - 验证 `user-instruction-plugin.ts` 中无"预加载 skill 指令到 System Prompt"的代码路径
   - 验证 `runtime-builder.ts` L362-435 中 skills 工具注册流程无 always 预加载

2. **Charles always + on-demand 共存**：
   - 验证 always 技能（read-pdf）的指令出现在 System Prompt 的 `## charles-always-skills` 段
   - 验证 on-demand 技能（如 stock-price）的指令不出现在 System Prompt 中，仅通过 `skills` 工具加载
   - 验证 always 技能仍出现在 `skills` 工具的可用列表中（`SkillsTool._build_description()`）

---

## 七、与 P4.2/P4.3 发现的衔接

P4.2（SkillLoader）和 P4.3（SkillRegistry）已发现 Charles 的 always 机制是 nanobot 风格残留，本阶段（P4.16）在 System Prompt 注入层面深入对比，**确认并细化了以下发现**：

| P4.2/P4.3 发现 | P4.16 深化 |
|---------------|-----------|
| Charles `always` 字段源自 nanobot（P4.2 §4 / P4.3 §3.3） | 确认 always_skills 段的完整注入链路（L70 字段 → L234 解析 → L183-208 加载 → L272-285 包装 → context.py L632-636 注入） |
| Cline `alwaysEnabled` 仅用于 remote skill（P4.3 §3.3） | 确认 Cline `alwaysEnabled` 是禁用策略（rule-helpers.ts L271），与 Charles 预加载策略语义正交 |
| Charles always 预加载是 nanobot 实现逻辑残留（P4.3 §3.3） | 确认 nanobot `get_always_skills()`（L203-211）+ `# Active Skills` 段注入（context.py L53-57）是 Charles 1:1 复刻原型 |
| Cline skills 全部 on-demand（P4.3 §3.3 引用 skills.mdx L9） | 确认 Cline `createSkillsTool` 是唯一加载入口，无 always 预加载路径 |
| Charles always_skills 段受 enhancements 开关控制（P4.3 §3.3） | 确认默认关闭（`enhancements.enabled=False`），`agent_config/system_prompt.yaml` 不存在，实际未注入 |

**本阶段新增发现**（P4.2/P4.3 未覆盖）：
1. always_skills 段的默认关闭行为（`enhancements.enabled=False`，实际未注入）
2. always 技能与 on-demand 技能在 Charles 中的指令重复问题（§3.5）
3. always_skills 段在 System Prompt 中的具体位置（`{{CHARLES_RULES}}` 内，effectiveRules 末尾，tools-overview / mcp-overview 之后，skills-summary / memory 之前）
4. Cline `alwaysEnabled` 在 `parseRemoteSkillEntries` 中仅透传不写入 `SkillMetadata`（skills.ts L239-244 丢弃字段）
5. always_skills 段的 token 成本（每个 always 技能 <5k tokens，多个累积可能显著增加 System Prompt 长度）
