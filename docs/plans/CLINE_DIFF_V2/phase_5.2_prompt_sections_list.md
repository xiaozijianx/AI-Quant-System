# Phase 5.2 System Prompt 段落清单对比

> 对比范围：Cline 与 Charles 的 System Prompt 段落清单完整性、段落顺序、段落存在性；区分注释残留与实现逻辑残留；nanobot 风格残留专项检查。
>
> 本阶段聚焦 System Prompt 的"段落级"结构对比，不深入段落内部文本（Base Prompt 文本细节留待 P5.3，工具说明段细节留待 P5.4+，各增强层段细节已在 P4.16/P4.17 等覆盖）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（DEFAULT_CLINE_SYSTEM_PROMPT + YOLO_CLINE_SYSTEM_PROMPT 模板）
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（buildClineSystemPrompt 纯组装器 + effectiveRules 拼装）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L103-116（mergeSystemPromptRules 合并扩展 rule）+ L680-689（composeSystemPrompt 编排器）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L238-242（registerRule 注册 user-instructions:rules）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`（runtime 构建，不含 system prompt 文本组装）
>
> Charles 源码：
> - `agent/prompts/charles_system_prompt.py` L29-91（DEFAULT_CHARLES_SYSTEM_PROMPT + YOLO_CHARLES_SYSTEM_PROMPT 模板）
> - `agent/context.py` L78-127（build_charles_system_prompt 纯组装器）+ L214-391（SystemPromptBuilder 编排器）+ L454-539（_build_rules 段拼装）+ L611-647（_build_enhancement_rules 增强层段）
> - `agent/rules_loader.py` L686-700（format_rules_content 统一 ## 标题格式）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`（nanobot 原生 system prompt 组装，含 # Active Skills / # Skills Summary 等段）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 段落清单。**核心结论：两者的段落清单在"骨架层"（base + rules + metadata）已对齐，但在"扩展层"差异显著——Cline 的 System Prompt 文本中仅含 base + rules + metadata 三段，无独立的 MCP/Skills/Always Skills/Memory 概览段；Charles 通过 enhancement 增强层机制将 tools-overview / mcp-overview / always-skills / skills-summary / memory 五个可选段注入到 rules 内。**

### 核心结论

1. **骨架对齐**：两者均采用 "base prompt（含 identity + 通用规则 + `<env>`）+ dynamic rules + workspace metadata" 的三层骨架，占位符数量与语义对齐（Cline `{{CLINE_RULES}}` / `{{CLINE_METADATA}}` ↔ Charles `{{CHARLES_RULES}}` / `{{CHARLES_METADATA}}`）。

2. **扩展层差异**：
   - **Cline**：System Prompt 文本中**不存在** MCP 概览段、Skills 概览段、Always Skills 段、Memory 段。MCP/Skills 以 tool definitions 形式（独立于 system prompt 文本）传递给 LLM；Cline 无 always 机制、无独立 memory 段。
   - **Charles**：通过 `enhancements` 配置开关（默认全部关闭），可选注入 `charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` / `charles-skills-summary` / `charles-memory` 五个段到 `{{CHARLES_RULES}}` 内。

3. **Custom Instructions 段**：**Charles 缺失**。Cline 通过 `composeSystemPrompt()`（session-runtime-orchestrator.ts L680-689）将扩展注册的 rule（`cline-user-instructions:rules`）合并到 System Prompt 末尾；Charles 无等价的扩展 rule 注册机制，所有 rules 在 `_build_rules()` 中静态加载。

4. **段落顺序**：两者在 rules 内部的子段顺序存在差异。Cline effectiveRules 顺序为 `[caller rules, MODE_TAG, PLAN_MODE?]`；Charles `_build_rules` 顺序为 `[AGENTS.md, rules_dir, MODE_TAG, PLAN_MODE?, enhancements...]`，其中 enhancements 内部顺序为 `[tools-overview, mcp-overview, always-skills, skills-summary, memory]`。

5. **段落总数**：Cline 实际 System Prompt 文本段数 = 3（base + rules + metadata）；Charles 实际段数 = 3（base + rules + metadata），但 rules 内部子段数最多可达 9（4 个基础 + 5 个 enhancement），最少 4（4 个基础，enhancement 全关）。

6. **nanobot 残留**：System Prompt 组装层面仅 **1 处注释残留**（context.py L275 `extra_sections` 参数 docstring 提到 "nanobot 风格"），**0 处实现逻辑残留**。charles_system_prompt.py 无 nanobot 残留。enhancement 增强层机制本身是 Charles 独有设计，非 nanobot 残留（但 `charles-always-skills` 段的 always 机制溯源到 nanobot，已在 P4.16 详述）。

### 一致性总体评估

- **骨架结构（base + rules + metadata）**：**对齐**
- **占位符设计**：**对齐**（2 个占位符，rules 在前 metadata 在后）
- **base prompt 内嵌段（identity + 规则 + `<env>`）**：**对齐**
- **rules 内部基础子段（用户规则 + MODE_TAG + PLAN_MODE）**：**对齐**
- **rules 内部扩展子段（tools/mcp/always/skills/memory）**：**未对齐**（Cline 无，Charles 有 enhancement 机制）
- **Custom Instructions 扩展 rule 机制**：**未对齐**（Cline 有 composeSystemPrompt 扩展合并，Charles 无）
- **段落总数**：**部分对齐**（骨架段数相同，rules 内部子段数不同）

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.2.1 | Base prompt 段 | **存在**。`DEFAULT_CLINE_SYSTEM_PROMPT`（system.ts L1-36）/ `YOLO_CLINE_SYSTEM_PROMPT`（L38-68），含 identity + 通用规则 + `<env>` 占位 | **存在**。`DEFAULT_CHARLES_SYSTEM_PROMPT`（charles_system_prompt.py L31-58）/ `YOLO_CHARLES_SYSTEM_PROMPT`（L62-91），含 identity + 通用行为规则 + 工具调用规则 + `<env>` 占位 | 对齐 | 骨架对齐；Charles 额外内嵌"工具调用规则"段（在 base 内，非独立段） |
| 5.2.2 | `<env>` 段 | **存在**。内嵌在 base prompt 中（system.ts L7-13），4 个占位符 `{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}` | **存在**。内嵌在 base prompt 中（charles_system_prompt.py L49-54），同样 4 个占位符 | 对齐 | 占位符名称与语义完全一致 |
| 5.2.3 | 工具说明段（自动生成） | **存在但不在 system prompt 文本中**。工具以 `tools` 参数（AgentTool[] 定义）形式独立传递给 LLM，非 system prompt 文本段 | **存在两种形态**：(1) 工具以 `tools` 参数独立传递（与 Cline 一致）；(2) 可选 enhancement `charles-tools-overview` 段作为 rule 注入 system prompt 文本（context.py L622-625） | 部分对齐 | Cline 仅 tool definitions 形式；Charles 额外有 system prompt 文本形式的 tools-overview 段（默认关闭） |
| 5.2.4 | metadata 段 | **存在**。`{{CLINE_METADATA}}` 占位符替换为 `# Workspace Configuration` + JSON（cline.ts L158-163，仅 isCline provider 注入） | **存在**。`{{CHARLES_METADATA}}` 占位符替换为 `# Workspace Configuration` + JSON（context.py L408-452，所有 Charles provider 注入） | 对齐 | 标记文本一致（`# Workspace Configuration`）；注入条件不同（Cline 仅 isCline，Charles 全部 provider） |
| 5.2.5 | MCP 服务器概览段 | **不存在于 system prompt 文本**。MCP 服务器以 tool definitions 形式独立传递给 LLM（runtime-builder.ts L453-457 加载 MCP tools） | **存在**。enhancement `charles-mcp-overview` 段（context.py L627-630），作为 rule 注入 `{{CHARLES_RULES}}`，默认关闭 | 未对齐 | Charles 独有 enhancement 段；Cline 无 system prompt 文本形式的 MCP 概览 |
| 5.2.6 | Cline Rules 段 | **存在**。`{{CLINE_RULES}}` 占位符替换为 effectiveRules（cline.ts L145-151）：caller rules + MODE_TAG + PLAN_MODE? | **存在**。`{{CHARLES_RULES}}` 占位符替换为 `_build_rules()` 输出（context.py L454-539）：AGENTS.md + rules_dir + MODE_TAG + PLAN_MODE? + enhancements? | 对齐 | 骨架对齐；Charles 在 rules 内额外加载 AGENTS.md 和 enhancements |
| 5.2.7 | Skills 概览段 | **不存在于 system prompt 文本**。Skills 以 on-demand 方式通过 `skills` 工具加载（definitions.ts L714-769），system prompt 中无 skills 概览段 | **存在**。enhancement `charles-skills-summary` 段（context.py L638-642），调用 `SkillRegistry.build_summary()` 生成 3 列表格，作为 rule 注入 `{{CHARLES_RULES}}`，默认关闭 | 未对齐 | Charles 独有 enhancement 段；Cline 无 system prompt 文本形式的 skills 概览（详见 P4.17） |
| 5.2.8 | Always Skills 指令段 | **不存在**。Cline 无 always 预加载机制，`SkillConfig` / `SkillMetadata` 均无 `always` 字段（详见 P4.16） | **存在**。enhancement `charles-always-skills` 段（context.py L632-636），调用 `SkillRegistry.load_always_instructions()` 加载 `always: true` 技能指令，作为 rule 注入 `{{CHARLES_RULES}}`，默认关闭 | 未对齐 | Charles 独有，源自 nanobot 设计模式（详见 P4.16）；计划表标注"已对齐"与实际不符 |
| 5.2.9 | Custom Instructions 段 | **存在**。通过 `composeSystemPrompt()`（session-runtime-orchestrator.ts L680-689）将扩展注册的 rule（如 `cline-user-instructions:rules`，user-instruction-plugin.ts L238-242）合并到 system prompt 末尾 | **缺失**。Charles 无等价的扩展 rule 注册机制，所有 rules 在 `_build_rules()` 中静态加载，无运行时动态注册入口 | 未对齐 | Charles 缺失扩展 rule 合并机制；这是架构层差异 |
| 5.2.10 | Memory 段 | **不存在于 system prompt 文本**。Cline system prompt 中无独立 memory 段，memory 相关内容（若有）通过 rules 或 extension contributions 注入 | **存在**。enhancement `charles-memory` 段（context.py L644-645），将 `self.memory` 文本作为 rule 注入 `{{CHARLES_RULES}}`，默认关闭 | 未对齐 | Charles 独有 enhancement 段；Cline 无独立 memory 段 |
| 5.2.11 | Mode 段（plan/act/yolo） | **存在**。`PLAN_MODE_INSTRUCTIONS`（cline.ts L32-45）作为 effectiveRules 第三项注入（cline.ts L148），仅 plan 模式注入 | **存在**。`_load_mode_prompt()` 加载 plan 模式提示（context.py L511-518 + L858-872），作为 rule 注入，仅 plan 模式注入 | 对齐 | 两者均仅 plan 模式注入 PLAN_MODE_INSTRUCTIONS |
| 5.2.12 | `<user_input mode>` 标签说明段 | **存在**。`MODE_TAG_INSTRUCTIONS`（cline.ts L21-23）作为 effectiveRules 第二项注入（cline.ts L147），始终注入 | **存在**。`_build_mode_tag_instructions()`（context.py L836-856）生成 mode 标签说明，作为 rule 注入（context.py L503-509），始终注入 | 对齐 | 两者均始终注入；Charles 文本为中文，Cline 为英文 |
| 5.2.13 | Enhancement 段（可选） | **不存在**。Cline 无 enhancement 配置开关机制，扩展内容通过 `composeSystemPrompt()` 动态注册 | **存在**。`_load_enhancements()`（context.py L304-346）读取 `agent_config/system_prompt.yaml`，控制 5 个子段开关，总开关 `enabled` 默认 False | 未对齐 | Charles 独有 enhancement 机制；Cline 用扩展 rule 注册替代 |
| 5.2.14 | 段落总数 | System prompt 文本段 = 3（base + rules + metadata）；含子段 effectiveRules = 2-3 项 | System prompt 文本段 = 3（base + rules + metadata）；含子段 rules = 4-9 项（4 基础 + 0-5 enhancement） | 部分对齐 | 骨架段数相同（3）；rules 内部子段数不同 |

---

## 三、重点差距详细说明

### 3.1 Cline System Prompt 实际段落结构（5.2.1 / 5.2.3 / 5.2.5 / 5.2.7 / 5.2.8 / 5.2.10）

Cline 的 System Prompt 文本结构远比计划表描述的 12 段简单。实际只有 **3 个顶层段**：

```
[Base Prompt 段]
  - identity（"You are Cline..."）
  - 通用规则（"Always gather..." / "Remember..." 等）
  - <env> 段（4 个占位符）
[{{CLINE_RULES}} 段 → effectiveRules]
  - caller rules（.clinerules 等，由调用方传入）
  - MODE_TAG_INSTRUCTIONS（始终注入）
  - PLAN_MODE_INSTRUCTIONS（仅 plan 模式注入）
[{{CLINE_METADATA}} 段 → workspace metadata]
  - # Workspace Configuration + JSON（仅 isCline provider）
[扩展 rule 段 → composeSystemPrompt 追加]
  - cline-user-instructions:rules（由 user-instruction-plugin 注册）
```

**关键澄清**：
- **工具说明段**（5.2.3）：不在 system prompt 文本中，以 `tools` 参数（AgentTool[] 定义）独立传递给 LLM。
- **MCP 概览段**（5.2.5）：不在 system prompt 文本中，MCP tools 以 tool definitions 形式传递。
- **Skills 概览段**（5.2.7）：不在 system prompt 文本中，skills 通过 `skills` 工具 on-demand 加载。
- **Always Skills 段**（5.2.8）：Cline 无 always 机制，system prompt 中无此段。
- **Memory 段**（5.2.10）：Cline system prompt 中无独立 memory 段。
- **Custom Instructions 段**（5.2.9）：通过 `composeSystemPrompt()` 合并扩展 rule，非独立段。

### 3.2 Charles System Prompt 实际段落结构（5.2.5 / 5.2.7 / 5.2.8 / 5.2.10 / 5.2.13）

Charles 的 System Prompt 文本结构同样只有 **3 个顶层段**，但 `{{CHARLES_RULES}}` 内部子段更丰富：

```
[Base Prompt 段]
  - identity（"你是 Charles..."）
  - 通用行为规则（6 条）
  - 工具调用规则（4 条）
  - <env> 段（4 个占位符）
[{{CHARLES_RULES}} 段 → _build_rules() 输出]
  1. 全局 AGENTS.md（~/.agent/AGENTS.md）
  2. workspace AGENTS.md（若显式传入 agents_path）
  3. rules_dir 内容（agent_config/rules/）
  4. MODE_TAG_INSTRUCTIONS（始终注入）
  5. PLAN_MODE_INSTRUCTIONS（仅 plan 模式注入）
  --- 以下为 enhancement 增强层（默认全部关闭）---
  6. charles-tools-overview（工具概览，若 tools_section=true）
  7. charles-mcp-overview（MCP 概览，若 mcp_section=true）
  8. charles-always-skills（always 技能指令，若 always_skills=true）
  9. charles-skills-summary（技能摘要 3 列表格，若 skills_summary=true）
  10. charles-memory（记忆段，若 memory=true 且 self.memory 非空）
[{{CHARLES_METADATA}} 段 → workspace metadata]
  - # Workspace Configuration + JSON（所有 Charles provider）
```

**关键点**：
- Charles 的 enhancement 段（tools/mcp/always/skills/memory）**作为 rule 注入到 `{{CHARLES_RULES}}` 内**，不是独立的顶层段。
- enhancement 段顺序固定（context.py L620-646）：tools → mcp → always → skills → memory。
- 所有 enhancement 段受 `enhancements.enabled` 总开关控制（默认 False），总开关关闭时全部不注入。
- `agent_config/system_prompt.yaml` 不存在时使用默认配置（全部关闭），实际运行时 enhancement 段均未注入。

### 3.3 Custom Instructions 段缺失（5.2.9）

这是本阶段发现的核心架构差异之一。

**Cline 的 Custom Instructions 机制**：
- `session-runtime-orchestrator.ts` L680-689 `composeSystemPrompt()` 遍历 `contributionRegistry.getRegisteredRules()`，将扩展注册的 rule 内容合并到 system prompt 末尾。
- `user-instruction-plugin.ts` L238-242 通过 `api.registerRule()` 注册 `cline-user-instructions:rules`，content 由 `loadRulesForSystemPromptFromWatcher(options.watcher)` 动态加载。
- `mergeSystemPromptRules()`（L103-116）将 base system prompt 与扩展 rules 用 `\n\n` 拼接：`${base}\n\n${additional}`。
- 这是 Cline 的**扩展点机制**：第三方扩展可在运行时动态注册 rule，无需修改 system prompt 组装代码。

**Charles 的缺失**：
- `SystemPromptBuilder._build_rules()`（context.py L454-539）静态加载所有 rules（AGENTS.md + rules_dir + MODE_TAG + PLAN_MODE + enhancements）。
- 无 `registerRule()` 等价的动态注册接口。
- 无 `composeSystemPrompt()` 等价的扩展合并层。
- 所有 rules 在编译时确定，运行时无法动态扩展。

**影响**：Charles 无法在不修改 `SystemPromptBuilder` 代码的前提下，通过扩展插件动态注入新的 rule 段。这在需要插件化扩展 system prompt 的场景下是架构短板。

### 3.4 计划表"已对齐"标注的勘误（5.2.5 / 5.2.7 / 5.2.8 / 5.2.10）

计划表（AGENT_COMPARISON_PLAN_V2.md L1790-1805）对部分项的"已对齐"标注与源码实际不符：

| 项 | 计划标注 | 实际情况 | 勘误说明 |
|---|---------|---------|---------|
| 5.2.5 MCP 概览段 | 已对齐 | **未对齐** | Cline system prompt 文本中无 MCP 概览段（MCP 以 tool definitions 形式传递）；Charles 有 enhancement `charles-mcp-overview` 段。两者形态不同 |
| 5.2.7 Skills 概览段 | 已对齐 | **未对齐** | Cline system prompt 文本中无 skills 概览段（skills on-demand）；Charles 有 enhancement `charles-skills-summary` 段。两者形态不同 |
| 5.2.8 Always Skills 段 | 已对齐 | **未对齐** | Cline 无 always 机制（P4.16 已确认）；Charles 有 enhancement `charles-always-skills` 段。两者存在性不同 |
| 5.2.10 Memory 段 | 顺序偏移 | **未对齐** | Cline system prompt 中无独立 memory 段；Charles 有 enhancement `charles-memory` 段。两者存在性不同 |

**勘误原因**：计划表可能将"tool definitions 形式"与"system prompt 文本段形式"等同看待，但本报告严格区分两者——system prompt 文本段指 `system` 参数中的文本内容，tool definitions 指 `tools` 参数中的 JSON Schema 定义。

### 3.5 段落顺序对比（5.2.10 / 5.2.11 / 5.2.12）

计划表标注 Memory / Mode / `<user_input mode>` 段存在"顺序偏移"，但实际源码中这些段的顺序关系与计划描述不同：

**Cline effectiveRules 顺序**（cline.ts L145-151）：
1. caller rules（.clinerules）
2. MODE_TAG_INSTRUCTIONS（= `<user_input mode>` 标签说明 + Mode 语义）
3. PLAN_MODE_INSTRUCTIONS（= Mode 段，仅 plan 模式）

**Charles `_build_rules` 顺序**（context.py L469-539）：
1. 全局 AGENTS.md
2. workspace AGENTS.md
3. rules_dir 内容
4. MODE_TAG_INSTRUCTIONS（= `<user_input mode>` 标签说明 + Mode 语义）
5. PLAN_MODE_INSTRUCTIONS（= Mode 段，仅 plan 模式）
6. enhancement 段（tools → mcp → always → skills → memory）

**顺序对比**：
- MODE_TAG 和 PLAN_MODE 在两者中**顺序一致**（均在用户 rules 之后）。
- Charles 的 Memory 段（enhancement）在 rules 内部末尾，Cline 无独立 Memory 段，不存在"顺序偏移"而是"存在性差异"。
- 计划表将 Mode 段和 `<user_input mode>` 段拆分为两项（5.2.11 / 5.2.12），但实际两者对应同一段（MODE_TAG_INSTRUCTIONS 是 `<user_input mode>` 标签说明 + Mode 语义；PLAN_MODE_INSTRUCTIONS 是 plan 模式契约），在源码中是同一个 rule 项。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（1 处，1 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/context.py` | L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` | docstring 参数说明 |

**注释残留说明**：
- `extra_sections` 参数是 `SystemPromptBuilder.__init__()` 的一个已废弃参数（context.py L255 / L292）。
- docstring 明确标注"nanobot 风格的额外段落"，说明该参数源自 nanobot 设计模式。
- 参数保留仅为向后兼容，`_build_rules()` 中 L530-537 仍有消费逻辑（将 `extra_sections` 包装为 `__extra__/{title}.md` rule），但"当前无调用方传入"。
- 这是纯注释残留，删除 docstring 中的"nanobot 风格"描述不影响功能。

### 4.2 实现逻辑残留（0 处）

**System Prompt 段落清单层面的实现逻辑残留：无**。

逐项验证：
- **base prompt 模板**（charles_system_prompt.py）：无 nanobot 残留。模板结构对齐 Cline（identity + 规则 + `<env>` + `{{RULES}}` + `{{METADATA}}`），仅文本为中文。
- **`build_charles_system_prompt()` 纯组装器**（context.py L78-127）：无 nanobot 残留。逻辑对齐 Cline `buildClineSystemPrompt()`（占位符替换）。
- **`SystemPromptBuilder` 编排器**（context.py L214-391）：无 nanobot 残留。编排逻辑（_build_rules + _build_metadata + select_base_template + 调用纯组装器）对齐 Cline orchestrator。
- **`_build_rules()` 段拼装**（context.py L454-539）：无 nanobot 残留。加载顺序（AGENTS.md → rules_dir → MODE_TAG → PLAN_MODE → enhancements）是 Charles 独有设计，但非 nanobot 复刻。
- **`_build_enhancement_rules()` 增强层**（context.py L611-647）：enhancement 机制本身是 Charles 独有设计（通过 YAML 配置开关控制段注入），非 nanobot 残留。但其中 `charles-always-skills` 段调用的 `load_always_instructions()` 溯源到 nanobot（已在 P4.16 详述，本阶段不重复）。
- **`extra_sections` 参数消费**（context.py L530-537）：虽然 docstring 标注"nanobot 风格"，但实现逻辑是将 extra_sections 包装为 rule 注入，这与 enhancement 机制设计一致，且"当前无调用方传入"，属于 dead code 性质，非活跃的 nanobot 实现残留。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（docstring 提到 nanobot） | 1 处（context.py L275） | 低 | 可保留作为设计溯源参考，或统一清理 |
| 实现逻辑残留（段落清单层面） | 0 处 | 无 | 无需处理 |
| 关联残留（always_skills 段溯源 nanobot） | 已在 P4.16 详述 | 高 | 见 P4.16 修复建议，本阶段不重复 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（1 处）：context.py L275 docstring 中提到"nanobot 风格的额外段落"，这是设计溯源说明，删除后功能不变。

**实现逻辑残留**（0 处）：System Prompt 段落清单层面无 nanobot 实现逻辑残留。具体来说：
- base prompt 模板：对齐 Cline，无 nanobot 复刻
- 纯组装器：对齐 Cline，无 nanobot 复刻
- 编排器：对齐 Cline，无 nanobot 复刻
- rules 拼装：Charles 独有设计（AGENTS.md + enhancements），非 nanobot 复刻
- enhancement 机制：Charles 独有设计（YAML 配置开关），非 nanobot 复刻

**关联说明**：`charles-always-skills` enhancement 段调用的 `load_always_instructions()` 方法溯源到 nanobot `get_always_skills()`（P4.16 已详述），但这是 skills 系统层面的实现逻辑残留，不是 System Prompt 段落清单层面的残留。本报告在 5.2.8 项中标注"Charles 独有，源自 nanobot 设计模式"以保持溯源链完整，但残留判定和修复建议遵循 P4.16 结论。

---

## 五、段落清单完整性矩阵

### 5.1 Cline 段落清单（实际 System Prompt 文本）

| 段编号 | 段名称 | 存在性 | 位置 | 注入条件 |
|--------|--------|--------|------|---------|
| C-1 | Base Prompt（identity + 通用规则 + `<env>`） | 存在 | system.ts L1-36 / L38-68 | 始终存在 |
| C-2 | `{{CLINE_RULES}}` → effectiveRules | 存在 | cline.ts L145-151 / L164 | 始终存在（至少含 MODE_TAG） |
| C-2.1 | └ caller rules（.clinerules） | 存在 | effectiveRules[0] | 调用方传入时存在 |
| C-2.2 | └ MODE_TAG_INSTRUCTIONS | 存在 | effectiveRules[1] | 始终注入 |
| C-2.3 | └ PLAN_MODE_INSTRUCTIONS | 存在 | effectiveRules[2] | 仅 plan 模式注入 |
| C-3 | `{{CLINE_METADATA}}` → workspace metadata | 存在 | cline.ts L158-163 | 仅 isCline provider 注入 |
| C-4 | 扩展 rule（composeSystemPrompt 追加） | 存在 | orchestrator.ts L680-689 | 扩展注册时存在 |
| — | 工具说明段 | **不在 system prompt 文本** | tools 参数 | 始终存在（独立传递） |
| — | MCP 概览段 | **不在 system prompt 文本** | tools 参数 | MCP 注册时存在（独立传递） |
| — | Skills 概览段 | **不在 system prompt 文本** | skills 工具 on-demand | LLM 调用 skills 工具时存在 |
| — | Always Skills 段 | **不存在** | — | Cline 无 always 机制 |
| — | Memory 段 | **不在 system prompt 文本** | — | 无独立 memory 段 |

### 5.2 Charles 段落清单（实际 System Prompt 文本）

| 段编号 | 段名称 | 存在性 | 位置 | 注入条件 |
|--------|--------|--------|------|---------|
| S-1 | Base Prompt（identity + 通用行为规则 + 工具调用规则 + `<env>`） | 存在 | charles_system_prompt.py L31-58 / L62-91 | 始终存在 |
| S-2 | `{{CHARLES_RULES}}` → _build_rules() 输出 | 存在 | context.py L454-539 / L117 | 始终存在（至少含 MODE_TAG） |
| S-2.1 | └ 全局 AGENTS.md | 存在 | _build_rules L471-483 | 文件存在时注入 |
| S-2.2 | └ workspace AGENTS.md | 存在 | _build_rules L486-496 | agents_path 传入且文件存在时注入 |
| S-2.3 | └ rules_dir 内容 | 存在 | _build_rules L498-500 | rules_dir 存在时注入 |
| S-2.4 | └ MODE_TAG_INSTRUCTIONS | 存在 | _build_rules L503-509 | 始终注入 |
| S-2.5 | └ PLAN_MODE_INSTRUCTIONS | 存在 | _build_rules L511-518 | 仅 plan 模式注入 |
| S-2.6 | └ charles-tools-overview（enhancement） | 存在 | _build_enhancement_rules L622-625 | enhancements.enabled=true 且 tools_section=true |
| S-2.7 | └ charles-mcp-overview（enhancement） | 存在 | _build_enhancement_rules L627-630 | enhancements.enabled=true 且 mcp_section=true |
| S-2.8 | └ charles-always-skills（enhancement） | 存在 | _build_enhancement_rules L632-636 | enhancements.enabled=true 且 always_skills=true 且 skills_registry 非空 |
| S-2.9 | └ charles-skills-summary（enhancement） | 存在 | _build_enhancement_rules L638-642 | enhancements.enabled=true 且 skills_summary=true 且 skills_registry 非空 |
| S-2.10 | └ charles-memory（enhancement） | 存在 | _build_enhancement_rules L644-645 | enhancements.enabled=true 且 memory=true 且 self.memory 非空 |
| S-2.11 | └ extra_sections（已废弃） | 存在（dead code） | _build_rules L530-537 | extra_sections 传入时注入（当前无调用方） |
| S-3 | `{{CHARLES_METADATA}}` → workspace metadata | 存在 | context.py L408-452 / L123 | 所有 Charles provider 注入 |
| — | 工具说明段 | **不在 system prompt 文本**（默认） | tools 参数 / enhancement S-2.6 | 默认独立传递；enhancement 开启时额外注入 system prompt |
| — | Custom Instructions 段（扩展 rule） | **不存在** | — | Charles 无扩展 rule 注册机制 |

### 5.3 段落存在性对比矩阵

| 段类型 | Cline system prompt 文本 | Charles system prompt 文本 | 差异 |
|--------|--------------------------|----------------------------|------|
| Base Prompt | 有 | 有 | 对齐（Charles 额外含工具调用规则） |
| `<env>` | 有（内嵌 base） | 有（内嵌 base） | 对齐 |
| Rules（用户规则） | 有（effectiveRules） | 有（_build_rules） | 对齐 |
| MODE_TAG | 有（effectiveRules） | 有（_build_rules） | 对齐 |
| PLAN_MODE | 有（effectiveRules） | 有（_build_rules） | 对齐 |
| Workspace metadata | 有（{{CLINE_METADATA}}） | 有（{{CHARLES_METADATA}}） | 对齐 |
| 扩展 rule 合并 | 有（composeSystemPrompt） | **无** | Charles 缺失 |
| 工具概览段 | 无（tool definitions 形式） | 有（enhancement，默认关闭） | 形态不同 |
| MCP 概览段 | 无（tool definitions 形式） | 有（enhancement，默认关闭） | 形态不同 |
| Skills 概览段 | 无（on-demand 加载） | 有（enhancement，默认关闭） | 形态不同 |
| Always Skills 段 | 无（无 always 机制） | 有（enhancement，默认关闭） | 存在性不同 |
| Memory 段 | 无（无独立段） | 有（enhancement，默认关闭） | 存在性不同 |

---

## 六、修复建议

### 6.1 高优先级（P1）

#### P1-1: 评估 Custom Instructions 扩展 rule 机制的补建必要性（5.2.9）

**问题**：Charles 缺失 Cline 的 `composeSystemPrompt()` 扩展 rule 合并机制，无法在运行时动态注册 rule。

**影响范围**：
- `agent/context.py` L214-391（SystemPromptBuilder 类，无 register_rule 接口）

**修复方案**：
- **保留方案**（推荐）：Charles 当前所有 rules 静态加载，满足现有业务需求。若未来无插件化扩展 system prompt 的场景，可不补建。
- **补建方案**：若需对齐 Cline 的扩展能力，可在 `SystemPromptBuilder` 中新增 `register_rule(id, content_provider)` 接口和 `_compose_system_prompt()` 方法，将注册的 rules 追加到 `_build_rules()` 输出末尾。

**建议**：保留方案更务实（Charles 当前无扩展插件系统），但应在 docstring 中明确标注"Charles 不支持运行时动态注册 rule，与 Cline composeSystemPrompt 机制不一致"。

### 6.2 中优先级（P2）

#### P2-1: 清理 extra_sections 已废弃参数的 nanobot 注释（4.1）

**影响范围**：`agent/context.py` L275（docstring）+ L255（参数签名）+ L292（初始化）+ L530-537（消费逻辑）

**修复方案**：
1. 若确认无调用方传入 `extra_sections`（docstring 已声明"当前无调用方传入"），可移除该参数及其消费逻辑（L530-537）。
2. 若保留参数以向后兼容，修正 docstring 移除"nanobot 风格"描述，改为"已废弃，保留参数签名仅为向后兼容"。

**理由**：用户规则"代码中不要有 fallback"和"生成的注释用中文"，docstring 中"nanobot 风格"是历史溯源，可统一清理。

#### P2-2: 勘误计划表的"已对齐"标注（3.4）

**影响范围**：`AGENT_COMPARISON_PLAN_V2.md` L1796-1801（5.2.5 / 5.2.7 / 5.2.8 / 5.2.10 项）

**修复方案**：
- 5.2.5 MCP 概览段：从"已对齐"改为"未对齐"（Cline 无 system prompt 文本段，Charles 有 enhancement 段）
- 5.2.7 Skills 概览段：从"已对齐"改为"未对齐"（Cline on-demand，Charles 有 enhancement 段）
- 5.2.8 Always Skills 段：从"已对齐"改为"未对齐"（Cline 无 always 机制，Charles 有 enhancement 段）
- 5.2.10 Memory 段：从"顺序偏移"改为"未对齐"（Cline 无独立 memory 段，Charles 有 enhancement 段）

**理由**：计划表将"tool definitions 形式"与"system prompt 文本段形式"等同看待，导致标注不准确。本报告严格区分两者。

### 6.3 低优先级（P3）

#### P3-1: 统一 Mode 段与 `<user_input mode>` 段的拆分粒度（3.5）

**问题**：计划表将 Mode 段（5.2.11）和 `<user_input mode>` 标签说明段（5.2.12）拆分为两项，但实际源码中两者对应同一段（MODE_TAG_INSTRUCTIONS 同时包含 mode 标签说明和 Mode 语义）。

**修复方案**：在后续阶段的对齐中，可将 5.2.11 和 5.2.12 合并为"MODE_TAG_INSTRUCTIONS 段"一项，避免拆分粒度不一致。

#### P3-2: enhancement 段顺序文档化（5.2.13）

**问题**：Charles enhancement 段顺序（tools → mcp → always → skills → memory）在代码中固定（context.py L620-646），但无文档记录设计依据。

**修复方案**：在 `SystemPromptBuilder` 类 docstring 或 `_build_enhancement_rules()` 方法 docstring 中补充 enhancement 段顺序的设计依据（如"tools 段在最前因 LLM 需优先了解可用工具；memory 段在最后因属辅助上下文"）。

---

## 七、验证方法建议

### 7.1 段落存在性验证

1. **Cline system prompt 段数验证**：
   ```
   # 验证 Cline system prompt 文本仅含 3 个顶层段
   Grep "DEFAULT_CLINE_SYSTEM_PROMPT" third_party/cline/sdk/packages/shared/src/prompt/system.ts
   # 预期：base prompt 内嵌 <env>，末尾有 {{CLINE_RULES}} 和 {{CLINE_METADATA}} 两个占位符
   ```

2. **Charles system prompt 段数验证**：
   ```
   # 验证 Charles system prompt 文本仅含 3 个顶层段
   Grep "DEFAULT_CHARLES_SYSTEM_PROMPT" agent/prompts/charles_system_prompt.py
   # 预期：base prompt 内嵌 <env>，末尾有 {{CHARLES_RULES}} 和 {{CHARLES_METADATA}} 两个占位符
   ```

3. **Cline 无 enhancement 机制验证**：
   ```
   Grep "enhancement|enhancements" third_party/cline/sdk/packages/shared/src/prompt/
   Grep "enhancement|enhancements" third_party/cline/sdk/packages/core/src/runtime/orchestration/
   # 预期：0 命中（Cline 无 enhancement 配置开关机制）
   ```

4. **Charles enhancement 机制验证**：
   ```
   Grep "_enhancements|_build_enhancement_rules" agent/context.py
   # 预期：命中 context.py L302/L304/L321/L338/L343/L521/L611-647
   ```

### 7.2 Custom Instructions 段缺失验证

1. **Cline 有 composeSystemPrompt 机制**：
   ```
   Grep "composeSystemPrompt|mergeSystemPromptRules" third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts
   # 预期：命中 L103（mergeSystemPromptRules 定义）+ L680（composeSystemPrompt 方法）+ L795（调用点）
   ```

2. **Charles 无等价机制**：
   ```
   Grep "composeSystemPrompt|mergeSystemPromptRules|registerRule" agent/context.py
   # 预期：0 命中（Charles 无扩展 rule 注册/合并机制）
   ```

### 7.3 nanobot 残留验证

1. **System Prompt 组装层面 nanobot 残留**：
   ```
   Grep "nanobot" agent/context.py
   Grep "nanobot" agent/prompts/charles_system_prompt.py
   # 预期：context.py 命中 1 处（L275 extra_sections docstring）；charles_system_prompt.py 命中 0 处
   ```

2. **Cline runtime-builder 无 nanobot 残留**：
   ```
   Grep "nanobot" third_party/cline/sdk/packages/core/src/runtime/orchestration/runtime-builder.ts
   # 预期：0 命中
   ```

### 7.4 段落顺序验证

1. **Cline effectiveRules 顺序验证**：
   ```
   # cline.ts L145-151
   # 预期顺序：[rules, MODE_TAG_INSTRUCTIONS, PLAN_MODE_INSTRUCTIONS?]
   ```

2. **Charles _build_rules 顺序验证**：
   ```
   # context.py L469-539
   # 预期顺序：[全局AGENTS.md, workspace AGENTS.md, rules_dir, MODE_TAG, PLAN_MODE?, enhancements?]
   ```

3. **Charles enhancement 段顺序验证**：
   ```
   # context.py L620-646
   # 预期顺序：[tools-overview, mcp-overview, always-skills, skills-summary, memory]
   ```

### 7.5 enhancement 默认关闭验证

```python
from agent.context import SystemPromptBuilder
builder = SystemPromptBuilder(skills_registry=registry)
prompt = builder.build()
# 预期：prompt 中不含 "## charles-tools-overview" / "## charles-mcp-overview" /
#       "## charles-always-skills" / "## charles-skills-summary" / "## charles-memory"
# 因为 enhancements.enabled 默认 False
```

---

## 八、与 P5.1 及其他阶段的衔接

### 8.1 与 P5.1 的衔接

P5.1（System Prompt 组装架构对比）聚焦组装架构（纯组装器 vs 编排器分层），本阶段（P5.2）在架构对齐的基础上深入段落清单级别，**确认并细化了以下发现**：

| P5.1 发现 | P5.2 深化 |
|----------|----------|
| 两者均采用 base + rules + metadata 三层骨架 | 确认三层骨架的段落清单完整性：Cline 3 段，Charles 3 段（骨架对齐） |
| Charles 有 enhancement 增强层机制 | 确认 enhancement 包含 5 个子段（tools/mcp/always/skills/memory），默认全部关闭 |
| Cline 有 composeSystemPrompt 扩展合并 | 确认 Charles 缺失该机制（5.2.9 Custom Instructions 段缺失） |

### 8.2 与 P4.16 / P4.17 的衔接

| P4.16 / P4.17 发现 | P5.2 衔接 |
|-------------------|----------|
| P4.16：Charles always_skills 段是 nanobot 实现逻辑残留 | 本阶段在段落清单层面确认：always_skills 段作为 enhancement 注入 `{{CHARLES_RULES}}`，是 Charles rules 内部的第 3 个 enhancement 子段（S-2.8） |
| P4.17：Charles skills-summary 段是 Charles 独有增强 | 本阶段在段落清单层面确认：skills-summary 段作为 enhancement 注入 `{{CHARLES_RULES}}`，是 Charles rules 内部的第 4 个 enhancement 子段（S-2.9） |

### 8.3 本阶段新增发现（P5.1 / P4.16 / P4.17 未覆盖）

1. **Custom Instructions 段缺失**（5.2.9）：Charles 无 `composeSystemPrompt()` 扩展 rule 合并机制，无法运行时动态注册 rule。
2. **enhancement 段顺序固定**（5.2.13）：tools → mcp → always → skills → memory，无配置化调整能力。
3. **计划表"已对齐"标注勘误**（3.4）：5.2.5 / 5.2.7 / 5.2.8 / 5.2.10 四项的"已对齐"标注与源码实际不符。
4. **Mode 段与 `<user_input mode>` 段的拆分粒度问题**（3.5）：计划表拆分为两项，实际源码为同一段。
5. **extra_sections 已废弃参数的 nanobot 注释残留**（4.1）：context.py L275，1 处注释残留。

---

## 附录：检查覆盖声明

- **Cline 源码**：
  - `sdk/packages/shared/src/prompt/system.ts`（L1-68）：100% 完整审阅
  - `sdk/packages/shared/src/prompt/cline.ts`（L1-166）：100% 完整审阅
  - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`（L103-116 / L680-689）：100% 完整审阅
  - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`（L1-740）：100% 完整审阅
  - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`（L238-242）：关键段落审阅

- **Charles 源码**：
  - `agent/prompts/charles_system_prompt.py`（L1-94）：100% 完整审阅
  - `agent/context.py`（L1-2666）：100% 完整审阅（含 SystemPromptBuilder + ContextCompactor）
  - `agent/rules_loader.py`（L686-700 关键方法）：关键段落审阅

- **nanobot 溯源**：
  - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`：通过 P4.16 已审阅，本阶段引用结论

- **14 项对比项**（5.2.1 - 5.2.14）：100% 逐项核对

本报告未修改任何源码，仅输出审计报告文件。
