# Phase 5.10 Always Skills 指令段对比

> 对比范围：Cline System Prompt 中"Always Skills 指令段"是否存在、内容来源、注入方式、段位置、标注格式；Charles `## charles-always-skills` rule 段的完整注入链路；nanobot 风格残留专项检查（区分注释残留与实现逻辑残留）；与 P4.16 always_skills 段对比的关联和深化。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 纯组装函数，effectiveRules 仅含 rules + MODE_TAG + PLAN_MODE，无 always skills 段）
> - `sdk/packages/shared/src/prompt/system.ts` L1-65（`DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT` 模板，无 always skills 占位符）
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L42-48（`SkillConfig` 接口仅 5 字段：name/description/disabled/instructions/frontmatter，无 `always`）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L75-217（`getConfiguredSkillsFromWatcher` + `createUserInstructionSkillsExecutor` 纯 on-demand 加载，无 always 预加载路径）
> - `apps/vscode/src/shared/skills.ts` L5-17（`SkillMetadata` 接口仅 4 字段：name/description/path/source，无 `always`）
> - `apps/vscode/src/core/context/instructions/user-instructions/skills.ts` L84-125（`ValidatedRemoteSkill.alwaysEnabled` 仅作透传，L239-244 映射到 SkillMetadata 时丢弃）
> - `sdk/packages/shared/src/remote-config/schema.ts` L128-147（`alwaysEnabled` 仅用于 remote MCP / globalInstructionsFile，非 skills 预加载语义）
> - `docs/customization/skills.mdx` L9（"Unlike rules (which are always active), skills load on-demand"）
>
> Charles 源码：
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装函数）+ L214-889（`SystemPromptBuilder` 编排器类）
> - `agent/context.py` L304-346（`_load_enhancements` 配置默认 `always_skills: True`，但总开关 `enabled: False`）+ L520-528（`_build_rules` 增强层注入）+ L611-647（`_build_enhancement_rules` 中 `charles-always-skills` rule 生成）
> - `agent/skills/registry.py` L183-191（`get_always_skills()`）+ L193-208（`load_always_instructions()`）+ L272-285（`load_always_instructions_as_rule()` 包装为 rule，含"已自动加载"标注）
> - `agent/skills/loader.py` L70（`SkillMetadata.always: bool = False`）+ L234（`always = bool(frontmatter.get("always", False))` frontmatter 解析）
> - `agent/prompts/charles_system_prompt.py` L29-58（`DEFAULT_CHARLES_SYSTEM_PROMPT` 模板，`{{CHARLES_RULES}}` 占位符承载 always_skills rule）
> - `agent_config/system_prompt.yaml` L1-10（增强层配置，`enabled: false` 默认关闭）
> - `agent_config/skills/read-pdf/SKILL.md` L5（`always: true` 实际配置，唯一实例）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 System Prompt 中"Always Skills 指令段"的实现。**核心结论：Cline 的 System Prompt 中不存在 Always Skills 指令段，Cline 的 skills 永远是 on-demand 加载（通过 `skills` 工具触发）；Charles 的 System Prompt 中存在 `## charles-always-skills` rule 段，将 `always: true` 技能的完整 Level 2 指令在启动时预加载到 System Prompt，并标注"已自动加载"。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.10（L1983-2001）的对比表存在**严重事实错误**：

1. **5.10.1 "always 预加载"标注为"是/是，已对齐"**：**错误**。Cline **不存在** always 预加载机制，`SkillConfig` / `SkillMetadata` 接口均无 `always` 字段，`createSkillsTool` 纯 on-demand。Charles 才有 always 预加载。应为"否/是，未对齐"。
2. **5.10.2 "已自动加载"标注"无/是，Charles 额外"**：**部分正确**。Cline 确实无此标注，但原因是 Cline 根本没有 always skills 段；Charles 确实有此标注（registry.py L283 "以下常驻技能指令已自动加载，无需调用 skills 工具即可生效"）。
3. **5.10.3 "Level 2 内容"标注"SKILL.md 正文 / SKILL.md 正文，已对齐"**：**误导性**。Cline 不预加载任何 SKILL.md 正文到 System Prompt；Charles 预加载 always 技能的 SKILL.md 正文。两者内容来源相同（SKILL.md body），但**是否注入 System Prompt** 完全相反。
4. **5.10.4 "段落位置"标注"第 8 段 / 第 8 段，已对齐"**：**错误**。Cline System Prompt 中**不存在** always skills 段（无第 8 段）；Charles 的 always skills 段位于 `{{CHARLES_RULES}}` 占位符内，作为 effectiveRules 末尾的 rule 之一。
5. **Cline 实现描述"always=True 的技能 Level 2 Instructions 预加载"**：**完全错误**。Cline 的 `SkillConfig` 不支持 `always` 字段，无 always 预加载机制。

### 核心结论

1. **Always Skills 指令段是否存在**：**Cline 不存在**，**Charles 存在**（`## charles-always-skills` rule 段）。Cline 的 `SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillMetadata`（skills.ts L5-17）均无 `always` 字段；Charles 的 `SkillMetadata.always` 字段从 frontmatter 解析，并通过 `load_always_instructions_as_rule()` 包装为 rule 注入。

2. **always 标记语义**：**语义完全不同**。
   - **Cline `alwaysEnabled`**：仅出现在**远程企业配置**（`GlobalInstructionsFileSchema` / `RemoteMCPServerSchema`），语义是"用户不可在 UI toggle off"（强制启用策略），**与预加载无关**。Cline 的 `SkillConfig` frontmatter 不支持 `always` 字段。
   - **Charles `always`**：从 SKILL.md frontmatter 解析，语义是"启动时预加载完整 Level 2 指令到 System Prompt"，**与禁用策略无关**。

3. **always 技能注入方式**：
   - **Cline**：无注入。所有 skills 指令仅通过 `skills` 工具的 `tool_result` 在对话中按需加载。
   - **Charles**：通过 `SystemPromptBuilder._build_enhancement_rules()`（context.py L632-636）调用 `SkillRegistry.load_always_instructions()` 获取拼接后的指令文本，包装为 `## charles-always-skills` rule，追加到 `effectiveRules` 末尾，经 `{{CHARLES_RULES}}` 占位符注入到 System Prompt。

4. **always 段标注格式**：
   - **Cline**：无此段，无标注。
   - **Charles**：段开头标注"以下常驻技能指令已自动加载，无需调用 skills 工具即可生效:"（registry.py L283），明确告知 LLM 这些指令已预加载，无需再调用 `skills` 工具。

5. **always 段在 System Prompt 中的位置**：
   - **Cline**：无此段。
   - **Charles**：`{{CHARLES_RULES}}` 占位符内，位于 effectiveRules 末尾（在 charles-tools-overview / charles-mcp-overview 之后，charles-skills-summary / charles-memory 之前，context.py L620-646）。

6. **nanobot 残留**：**Charles 的 always_skills 段是完整的 nanobot 实现逻辑残留**，非纯注释残留。溯源到 nanobot `agent/skills.py` L203-211 `get_always_skills()` + `agent/context.py` L53-57 `# Active Skills` 段注入。Charles 的实现是对 nanobot 机制的 1:1 复刻（仅包装格式从 `# Active Skills` 改为 `## charles-always-skills` rule，并增加"已自动加载"标注）。

### 一致性总体评估

- **Always Skills 段存在性**：**未对齐**。Cline 无此段，Charles 有此段。
- **always 标记语义**：**未对齐**。Cline 的 `alwaysEnabled` 是禁用策略，Charles 的 `always` 是预加载策略，两者语义正交。
- **注入方式**：**未对齐**。Cline 无注入，Charles 通过 rule 注入。
- **段位置**：**未对齐**。Cline 无此段，Charles 在 effectiveRules 末尾。
- **标注格式**：**未对齐**。Cline 无标注，Charles 有"已自动加载"标注。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.10.1 | always 预加载机制 | **不存在**。`SkillConfig`（user-instruction-config-loader.ts L42-48）和 `SkillMetadata`（skills.ts L5-17）均无 `always` 字段；`createSkillsTool` 纯 on-demand（definitions.ts L714-769） | **存在**。`SkillMetadata.always` 字段（loader.py L70）从 frontmatter 解析（L234），通过 `load_always_instructions()` 预加载完整指令（registry.py L193-208） | 未对齐 | 计划文件标注"已对齐"错误。Charles 独有，源自 nanobot |
| 5.10.2 | "已自动加载"标注 | **无此标注**（无此段） | **存在**。`load_always_instructions_as_rule()` 在段开头注入"以下常驻技能指令已自动加载，无需调用 skills 工具即可生效:"（registry.py L283） | 未对齐 | Charles 额外标注，提示 LLM 不要重复调用 skills 工具 |
| 5.10.3 | Level 2 内容来源 | **不注入 System Prompt**。SKILL.md body 仅在 LLM 调用 `skills` 工具时通过 `tool_result` 返回（definitions.ts L714-769） | **SKILL.md body**（去 frontmatter）+ 自动追加的 `## 可用脚本` 段（loader.py L176-184）。多个 always 技能用 `\n\n---\n\n` 分隔（registry.py L208） | 未对齐 | 内容来源相同（SKILL.md body），但是否注入 System Prompt 完全相反 |
| 5.10.4 | 段落位置 | **无此段**。System Prompt 中无 always skills 段 | `{{CHARLES_RULES}}` 占位符内，effectiveRules 末尾。顺序：tools-overview → mcp-overview → **always-skills** → skills-summary → memory（context.py L620-646） | 未对齐 | 计划文件标注"第 8 段/第 8 段，已对齐"错误。Cline 无此段，Charles 在 rules 段尾部 |
| 5.10.5 | always 段开关控制 | **无此段，无开关** | **双开关**：`enhancements.enabled`（总开关，默认 False）+ `enhancements.always_skills`（子开关，默认 True）。总开关关闭时所有增强层关闭（context.py L338-343） | 未对齐 | Charles 默认关闭，需显式开启 |
| 5.10.6 | always 段包装格式 | **无此段** | `## charles-always-skills\n\n以下常驻技能指令已自动加载，无需调用 skills 工具即可生效:\n\n{instructions}`（registry.py L281-285） | 未对齐 | Charles rule 格式 |
| 5.10.7 | `always` frontmatter 字段 | **不支持**。SKILL.md frontmatter 仅支持 `name` / `description` / `disabled` / `enabled`（user-instruction-config-loader.ts L42-48） | **支持**。`always: bool = False`（loader.py L70），从 frontmatter 解析（L234 `bool(frontmatter.get("always", False))`） | 未对齐 | Charles 独有字段 |
| 5.10.8 | `alwaysEnabled` 语义 | **禁用策略**：仅用于远程企业配置（`GlobalInstructionsFileSchema` / `RemoteMCPServerSchema`），表示"用户不可在 UI toggle off"。`parseRemoteSkillEntries` 透传但 `discoverSkills` 映射到 SkillMetadata 时丢弃 | **预加载策略**：`always: true` 表示"启动时预加载完整指令到 System Prompt"。与禁用策略无关 | 未对齐 | 语义正交，不可混用 |
| 5.10.9 | always 技能注入时机 | **不注入**（无此机制） | **System Prompt 构建时**。`SystemPromptBuilder._build_rules()` → `_build_enhancement_rules()`（context.py L632-636）每次构建 System Prompt 时重新加载 | 未对齐 | Charles 每轮重新注入 |
| 5.10.10 | always 技能 vs on-demand 技能 | **无区别**。所有 skills 均 on-demand，通过 `skills` 工具触发。skills.mdx L9 明确："Unlike rules (which are always active), skills load on-demand" | **有区别**。always 技能在 System Prompt 启动时生效；on-demand 技能需 LLM 调用 `skills` 工具后才注入 | 未对齐 | 设计哲学差异 |
| 5.10.11 | 实际配置中的 always 技能 | **无此字段** | `agent_config/skills/read-pdf/SKILL.md` L5 `always: true`（唯一实际配置） | 未对齐 | Charles 实际启用 1 个 always 技能 |
| 5.10.12 | nanobot 溯源 | **无此机制** | `nanobot/agent/skills.py` L203-211 `get_always_skills()` + `nanobot/agent/context.py` L53-57 `# Active Skills` 段注入。Charles 1:1 复刻，仅包装格式从 `# Active Skills` 改为 `## charles-always-skills` rule | 未对齐 | nanobot 实现逻辑残留 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.10 事实错误修正（5.10.1 / 5.10.4）

AGENT_COMPARISON_PLAN_V2.md P5.10（L1983-2001）的对比表与 P4.16 的结论**自相矛盾**：

| 对比项 | P5.10 计划表标注 | P4.16 实际结论 | 谁正确 |
|--------|----------------|---------------|--------|
| 5.10.1 always 预加载 | "是/是，已对齐" | "Cline 不存在，Charles 存在，未对齐"（P4.16 4.16.1/4.16.6） | **P4.16 正确** |
| 5.10.2 "已自动加载"标注 | "无/是，Charles 额外" | "Cline 无此段无标注，Charles 有标注"（P4.16 4.16.9） | 部分正确（Cline 无标注的原因是根本无此段） |
| 5.10.3 Level 2 内容 | "SKILL.md 正文/SKILL.md 正文，已对齐" | "Cline 不注入，Charles 注入"（P4.16 4.16.13） | **P4.16 正确** |
| 5.10.4 段落位置 | "第 8 段/第 8 段，已对齐" | "Cline 无此段，Charles 在 effectiveRules 末尾"（P4.16 4.16.10） | **P4.16 正确** |

**错误根源**：P5.10 计划文件可能误将 Cline 的 `alwaysEnabled`（远程企业配置的强制启用策略）等同于 Charles 的 `always`（本地 SKILL.md 的预加载策略），从而错误标注"已对齐"。实际上两者**语义正交、实现位置不同、适用范围不同**，详见 P4.16 §3.1。

**本阶段结论**：**P5.10 计划表的 4 项"已对齐"标注全部错误，应为"未对齐"**。Cline 无 Always Skills 指令段，Charles 有此段（源自 nanobot）。

### 3.2 Cline 的设计哲学：skills 永远 on-demand（5.10.10）

Cline 文档 `docs/customization/skills.mdx` L9 明确声明：

> "Unlike rules (which are always active), skills load on-demand so they don't consume context when you're working on something unrelated."

这是 Cline 的**核心设计哲学**：
- **rules**：always active，始终注入 System Prompt（通过 `effectiveRules`）
- **skills**：on-demand，仅当 LLM 调用 `skills` 工具时才加载 Level 2 指令

Cline 严格区分 rules 和 skills 的加载模型：
- rules 的 frontmatter 有 `alwaysApply` 字段（rules.mdx），控制是否始终注入
- skills 的 frontmatter **无 `always` 字段**，永远通过 `skills` 工具触发

**Charles 打破了这一边界**：将 rules 的 `alwaysApply` 概念引入 skills，创造出 `always: true` 的 skill 字段，使部分 skills 也能"始终注入"。这是 nanobot 的设计模式——nanobot 不严格区分 rules 和 skills，skills 可以通过 `always: true` 标记为"始终激活"。

### 3.3 Charles 的 Always Skills 段注入流程详解（5.10.1 / 5.10.9）

Charles 的 Always Skills 段注入流程如下：

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

**`load_always_instructions_as_rule()` 的完整输出格式**（registry.py L272-285）：

```markdown
## charles-always-skills

以下常驻技能指令已自动加载，无需调用 skills 工具即可生效:

### 技能: read-pdf

{read-pdf SKILL.md body 完整内容}

---

### 技能: {另一个 always 技能}

{另一个 always 技能的 SKILL.md body}
```

**关键点**：
1. Always Skills 段作为 **rule** 注入，不是独立的 System Prompt 段。
2. 注入位置在 `{{CHARLES_RULES}}` 占位符内，位于 effectiveRules 末尾。
3. Always Skills 段在 `charles-tools-overview` / `charles-mcp-overview` 之后，`charles-skills-summary` / `charles-memory` 之前（context.py L620-646 顺序）。
4. 每次构建 System Prompt 时都会重新加载 always 技能指令（无缓存）。
5. 受 `enhancements.enabled`（默认 False）和 `enhancements.always_skills`（默认 True）双开关控制——**默认情况下 Always Skills 段不注入**（因总开关默认关闭）。
6. 段开头有"已自动加载"标注（registry.py L283），明确告知 LLM 这些指令已预加载，无需再调用 `skills` 工具。

### 3.4 Charles 的 Always Skills 段默认关闭（5.10.5）

Charles 的 `SystemPromptBuilder._load_enhancements()`（context.py L304-346）读取 `agent_config/system_prompt.yaml` 配置：

```yaml
# agent_config/system_prompt.yaml L4-10
enhancements:
  enabled: false       # 总开关默认关闭
  tools_section: true
  skills_summary: true
  always_skills: true  # 子开关默认 True
  mcp_section: true
  memory: true
```

**默认行为**：`enhancements.enabled` 为 `False`，所有增强层（含 always_skills）均关闭。即**默认情况下 Charles 的 System Prompt 中不包含 `## charles-always-skills` 段**。

**启用条件**：需在 `agent_config/system_prompt.yaml` 中显式设置 `enhancements.enabled: true` 且 `enhancements.always_skills: true`。

**实际影响**：当前 `agent_config/system_prompt.yaml` 配置文件存在（L1-10），但 `enabled: false`，因此 Charles 的 always_skills 段**实际未注入** System Prompt。但这不影响代码层面的差异分析——Charles 具备注入能力，Cline 不具备。

### 3.5 "已自动加载"标注的意义（5.10.2）

Charles 在 always_skills 段开头注入的"以下常驻技能指令已自动加载，无需调用 skills 工具即可生效:"标注（registry.py L283）具有重要的运行时意义：

1. **避免指令重复加载**：告知 LLM 这些 always 技能的指令已在 System Prompt 中，无需再调用 `skills` 工具加载。
2. **明确技能状态**：区分 always 技能（已预加载）和 on-demand 技能（需调用 `skills` 工具加载）。
3. **降低 token 浪费**：防止 LLM 误调用 `skills` 工具加载已预加载的技能，避免指令重复注入对话上下文。

**Cline 无此标注**：因为 Cline 根本没有 always skills 段，所有 skills 都需要通过 `skills` 工具加载，LLM 不需要区分 always 和 on-demand。

**残留问题**：尽管 Charles 有"已自动加载"标注，但 `SkillsTool._build_description()` 在可用技能列表中**未过滤掉 always 技能**（skill_tool.py 中 `list_skills()` 不排除 always 技能）。这导致 LLM 仍可能在可用列表中看到 always 技能名并调用 `skills` 工具，触发 `runningSkills` 去重机制（skill_tool.py L176-181）返回 "already running" 提示。这是 P4.16 §3.5 已发现的指令重复问题，本阶段不重复。

### 3.6 Cline `alwaysEnabled` 与 Charles `always` 的语义正交（5.10.8）

这是本阶段最关键的差异。两者虽然字面相似，但**语义完全不同、适用范围不同、实现位置不同**，不可混用。

**Cline `alwaysEnabled`**：
- **定义位置**：`sdk/packages/shared/src/remote-config/schema.ts` L140-147（`GlobalInstructionsFileSchema`）+ L128-137（`RemoteMCPServerSchema`）。仅用于**远程企业配置**（`RemoteConfig`），不下发到本地 SKILL.md frontmatter。
- **语义**：`schema.ts` L142 注释 "When this is enabled, the user cannot turn off this rule or workflow" —— **强制启用策略**，用户无法在 UI 中关闭。
- **实现**：`rule-helpers.ts` L271 `const isEnabled = rule.alwaysEnabled || remoteToggles[rule.name] !== false` —— `alwaysEnabled=true` 时**跳过 toggle 检查**，强制纳入 rules 内容。但这是 **rules 系统的机制**（globalRules / globalWorkflows），不是 skills 系统。
- **skills 系统的处理**：`parseRemoteSkillEntries`（skills.ts L105-125）将 `entry.alwaysEnabled` 透传到 `ValidatedRemoteSkill`，但 `discoverSkills`（L239-244）映射到 `SkillMetadata` 时**丢弃该字段**（`SkillMetadata` 接口无定义，skills.ts L5-17 仅 4 字段）。即 Cline 的 `alwaysEnabled` 对 skills **仅作元数据透传，不触发任何预加载行为**。

**Charles `always`**：
- **定义位置**：`agent/skills/loader.py` L70 `always: bool = False`，从 SKILL.md frontmatter 解析（L234）。
- **语义**：`registry.py` L186-187 docstring "always=True 的技能会在启动时自动加载指令到 system prompt，而不需要 LLM 通过 use_skill 工具触发" —— **预加载策略**。
- **实现**：`registry.py` L183-191 `get_always_skills()` 返回 always=True 的技能名列表 → L193-208 `load_always_instructions()` 加载完整指令并拼接 → L272-285 `load_always_instructions_as_rule()` 包装为 rule（含"已自动加载"标注）→ `context.py` L632-636 注入 System Prompt。
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
| "已自动加载"标注 | 无 | 有（registry.py L283） |

---

## 四、nanobot 残留专项检查

### 4.1 实现逻辑残留（1 处，核心残留）

Charles 的 Always Skills 段是**完整的 nanobot 实现逻辑残留**，非纯注释残留。溯源对比如下：

| 组件 | nanobot 实现 | Charles 实现 | 残留性质 |
|------|-------------|-------------|---------|
| `get_always_skills()` | `nanobot/agent/skills.py` L203-211：遍历 `list_skills()`，检查 `skill_meta.get("always") or meta.get("always")`，返回技能名列表 | `agent/skills/registry.py` L183-191：遍历 `self._skills.items()`，检查 `meta.always`，返回技能名列表 | **1:1 复刻**，仅数据结构从 dict 改为 SkillMetadata |
| 指令加载 | `nanobot/agent/skills.py` `load_skills_for_context(always_skills)`（context.py L55 调用） | `agent/skills/registry.py` L193-208 `load_always_instructions()`：加载每个技能指令，用 `\n\n---\n\n` 拼接 | **1:1 复刻**，仅拼接分隔符可能不同 |
| System Prompt 注入 | `nanobot/agent/context.py` L53-57：`parts.append(f"# Active Skills\n\n{always_content}")` | `agent/skills/registry.py` L272-285 `load_always_instructions_as_rule()` + `agent/context.py` L632-636：包装为 `## charles-always-skills` rule（含"已自动加载"标注），经 `{{CHARLES_RULES}}` 注入 | **复刻 + 适配**：从 `# Active Skills` 独立段改为 `## charles-always-skills` rule（适配 Cline 的 base + rules 两层结构），并增加"已自动加载"标注 |
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
- `load_always_instructions_as_rule()`（registry.py L272-285）—— 包装逻辑残留（含"已自动加载"标注）
- `_build_enhancement_rules()` 中 `charles-always-skills` rule 生成（context.py L632-636）—— 注入逻辑残留
- `_load_enhancements()` 中 `always_skills` 开关（context.py L323/L340）—— 配置逻辑残留
- `agent_config/skills/read-pdf/SKILL.md` L5 `always: true` —— 实际配置残留

**关键区别**：若删除注释残留，功能不变；若删除实现逻辑残留，always_skills 段不再注入 System Prompt，Charles 行为向 Cline 对齐（skills 全部 on-demand）。

---

## 五、与 P4.16 always_skills 段对比的关联和深化

### 5.1 P4.16 与 P5.10 的关系

P4.16（always_skills 段对比）和 P5.10（Always Skills 指令段对比）均对比 Cline 与 Charles 的 always skills 机制，但侧重点不同：

| 维度 | P4.16 | P5.10 |
|------|-------|-------|
| 对比范围 | always_skills 段的整体实现（含 frontmatter 字段、`alwaysEnabled` 语义、注入流程、token 成本、nanobot 溯源） | Always Skills **指令段**在 System Prompt 中的存在性、内容、注入方式、段位置、标注格式 |
| 侧重层面 | 实现层（数据结构、解析、加载、注入链路） | System Prompt 层（段存在性、段位置、标注格式、与 on-demand 的区分） |
| 计划文件状态 | 计划表标注正确（未对齐） | 计划表标注错误（标注"已对齐"，实际未对齐） |
| 一致性结论 | 未对齐（16 项全部未对齐） | 未对齐（12 项全部未对齐） |

### 5.2 P5.10 对 P4.16 的深化

P5.10 在 P4.16 已有结论的基础上，**深化了以下发现**：

| P4.16 发现 | P5.10 深化 |
|-----------|-----------|
| always_skills 段是否存在（4.16.1） | **修正计划文件 P5.10 的"已对齐"错误标注**，确认 Cline 无此段，Charles 有此段 |
| always 段包装格式（4.16.9） | **聚焦"已自动加载"标注的运行时意义**（避免指令重复加载、明确技能状态、降低 token 浪费） |
| always 段在 System Prompt 中的位置（4.16.10） | **修正计划文件 P5.10 的"第 8 段/第 8 段，已对齐"错误标注**，确认 Cline 无此段，Charles 在 effectiveRules 末尾 |
| Level 2 内容（4.16.13） | **修正计划文件 P5.10 的"SKILL.md 正文/SKILL.md 正文，已对齐"误导性标注**，确认 Cline 不注入，Charles 注入 |
| always 技能 vs on-demand 技能（4.16.11） | **强调 Cline 的设计哲学**（skills.mdx L9 "skills load on-demand"），Charles 打破了 rules/skills 边界 |

### 5.3 P5.10 新增发现（P4.16 未覆盖）

1. **计划文件 P5.10 事实错误**：P5.10 计划表的 4 项"已对齐"标注全部错误，与 P4.16 结论自相矛盾。本阶段修正了这些错误。
2. **"已自动加载"标注的运行时意义**：P4.16 仅列出标注文本，P5.10 深入分析了标注的三个运行时意义（避免指令重复加载、明确技能状态、降低 token 浪费）。
3. **Cline `alwaysEnabled` 在 skills 系统中的处理**：P5.10 再次确认 `parseRemoteSkillEntries` 透传 `alwaysEnabled` 但 `discoverSkills` 映射到 `SkillMetadata` 时丢弃，强调 Cline 的 `alwaysEnabled` 对 skills 无预加载行为。
4. **Charles 默认关闭的实际影响**：P5.10 确认 `agent_config/system_prompt.yaml` 存在但 `enabled: false`，always_skills 段实际未注入 System Prompt。

---

## 六、修复建议

### 6.1 高优先级（P1）

无。always_skills 段默认关闭（`enhancements.enabled=False`），不影响默认运行时行为。当前 `agent_config/system_prompt.yaml` 配置 `enabled: false`，实际未注入 System Prompt。

### 6.2 中优先级（P2）

1. **修正计划文件 P5.10 的错误标注**：
   - 5.10.1 "always 预加载"：从"是/是，已对齐"改为"否/是，未对齐"
   - 5.10.2 "已自动加载"标注：从"无/是，Charles 额外"改为"无/有，未对齐"（明确 Cline 无此段是根本原因）
   - 5.10.3 "Level 2 内容"：从"SKILL.md 正文/SKILL.md 正文，已对齐"改为"不注入/注入，未对齐"
   - 5.10.4 "段落位置"：从"第 8 段/第 8 段，已对齐"改为"无此段/effectiveRules 末尾，未对齐"

2. **评估 always_skills 段的保留必要性**（与 P4.16 §5.2 一致）：
   - **保留方案**：若 Charles 需要预加载某些技能指令（如 read-pdf 用于高频年报查询），可保留 always_skills 段，但应在 docstring 中明确说明"这是 Charles 独有增强，Cline 无等价物，源自 nanobot 设计模式"。
   - **移除方案**：若严格对齐 Cline 的 on-demand 设计哲学，应移除 `SkillMetadata.always` 字段、`get_always_skills()` / `load_always_instructions()` / `load_always_instructions_as_rule()` 方法、`_build_enhancement_rules()` 中的 `charles-always-skills` rule 生成、`_load_enhancements()` 中的 `always_skills` 开关、以及 `agent_config/skills/read-pdf/SKILL.md` 的 `always: true` 配置。
   - **建议**：保留方案更务实（read-pdf 预加载有业务价值），但需修正 docstring 避免"对标 Cline"的误导性表述。

3. **修正 docstring 溯源标注**（registry.py L184）：
   - 当前：`"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`
   - 建议改为：`"""获取 always=True 的技能名称列表 — Charles 独有增强（源自 nanobot 设计模式，Cline 无等价物）`
   - 明确标注这是 Charles 独有增强，避免与 Cline 对标混淆。

### 6.3 低优先级（P3）

4. **nanobot 注释统一**（4 处）：可选择保留作为设计溯源，或统一清理为仅引用 Cline 对标位置。

5. **always_skills 段 token 成本监控**（与 P4.16 §5.3 一致）：若启用 always_skills 段，应在 `SystemPromptBuilder` 中记录 always 技能指令的 token 占用，便于调试 System Prompt 过长问题。

---

## 七、验证方法建议

### 7.1 Always Skills 段存在性验证

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

### 7.2 Cline `alwaysEnabled` 语义验证

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
   预期：0 命中（`SkillConfig` L42-48 + `SkillMetadata` L5-17 均无此字段）

### 7.3 Charles Always Skills 段注入验证

1. **默认关闭验证**：
   ```python
   from agent.context import SystemPromptBuilder
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-always-skills" not in prompt  # 默认关闭
   ```

2. **启用后注入验证**：
   ```python
   # 修改 agent_config/system_prompt.yaml 启用增强层
   # enhancements:
   #   enabled: true
   #   always_skills: true
   builder = SystemPromptBuilder(skills_registry=registry)
   prompt = builder.build()
   assert "## charles-always-skills" in prompt
   assert "已自动加载" in prompt  # 标注文本
   assert "read-pdf" in prompt  # read-pdf SKILL.md 配置了 always: true
   ```

3. **"已自动加载"标注验证**：
   ```python
   from agent.skills.registry import SkillRegistry
   registry = SkillRegistry(skills_dir="agent_config/skills")
   registry.discover()
   rule = registry.load_always_instructions_as_rule()
   assert "以下常驻技能指令已自动加载" in rule  # registry.py L283
   assert "无需调用 skills 工具即可生效" in rule
   ```

### 7.4 nanobot 残留验证

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

### 7.5 计划文件错误标注验证

1. **P5.10 计划表"已对齐"标注验证**：
   - 5.10.1：Cline `SkillConfig` 无 `always` 字段 → Cline 无 always 预加载 → "已对齐"错误
   - 5.10.4：Cline `buildClineSystemPrompt`（cline.ts L110-166）无 always skills 段 → "第 8 段/第 8 段，已对齐"错误

---

## 八、一致性总评

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| Always Skills 段存在性 | **未对齐** | Cline 无此段，Charles 有此段（源自 nanobot） |
| always 标记语义 | **未对齐** | Cline `alwaysEnabled` 是禁用策略，Charles `always` 是预加载策略，语义正交 |
| 注入方式 | **未对齐** | Cline 无注入，Charles 通过 rule 注入 |
| 段位置 | **未对齐** | Cline 无此段，Charles 在 effectiveRules 末尾 |
| 标注格式 | **未对齐** | Cline 无标注，Charles 有"已自动加载"标注 |
| 计划文件 P5.10 标注 | **错误** | 4 项"已对齐"全部错误，应为"未对齐" |

**总体结论**：Charles 的 Always Skills 指令段是**完整的 nanobot 实现逻辑残留**，与 Cline 的 on-demand 设计哲学冲突。Cline 的 System Prompt 中不存在 Always Skills 指令段，Charles 的 System Prompt 中存在 `## charles-always-skills` rule 段（含"已自动加载"标注），但默认关闭（`enhancements.enabled=False`）。计划文件 P5.10 的"已对齐"标注全部错误，应修正为"未对齐"，与 P4.16 结论保持一致。
