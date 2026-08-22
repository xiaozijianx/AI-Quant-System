# Phase 5.15 Enhancement 段对比

> 对比范围：Cline 与 Charles 的 System Prompt 中 "Enhancement 段"（可选增强层）是否存在、内容、注入方式、配置开关；区分注释残留与实现逻辑残留；nanobot 风格残留专项检查。
>
> 本阶段聚焦 Charles 独有的 "Enhancement 段"（通过 `agent_config/system_prompt.yaml` 控制的可选增强层，包含 tools_section / mcp_section / always_skills / skills_summary / memory 五个子段）在 Cline 中的对应实现，深入到配置加载、rule 生成、注入链路级别。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（buildClineSystemPrompt 纯组装器，effectiveRules 仅含 rules + MODE_TAG + PLAN_MODE，无 Enhancement 机制）
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（DEFAULT_CLINE_SYSTEM_PROMPT / YOLO_CLINE_SYSTEM_PROMPT 模板，仅 `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 两个占位符，无 Enhancement 占位符）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L680-689（composeSystemPrompt 编排器，遍历 contributionRegistry.getRegisteredRules()，无 enhancement 配置开关）
>
> Charles 源码：
> - `agent/context.py` L14-20（模块 docstring 描述增强层）+ L232-238（SystemPromptBuilder 类 docstring 描述增强层）+ L300-302（`__init__` 调用 `_load_enhancements`）+ L304-346（`_load_enhancements` 配置加载）+ L520-528（`_build_rules` 注入增强层）+ L611-647（`_build_enhancement_rules` 生成增强层 rule 列表）+ L723-786（`_build_tools_section`）+ L788-834（`_build_mcp_servers_section`）
> - `agent_config/system_prompt.yaml` L1-10（增强层配置文件，默认 `enabled: false`）
> - `agent/prompts/charles_system_prompt.py` L29-91（base prompt 模板，无 Enhancement 占位符，增强层走 `{{CHARLES_RULES}}` 通道）
> - `agent/skills/registry.py` L215（build_summary docstring 提到 enhancements.skills_summary）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`（nanobot 原生无独立 Enhancement 段配置机制）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 中 "Enhancement 段"（可选增强层）的存在性、内容、注入方式、配置开关。**核心结论：Cline 完全没有 Enhancement 段机制；Charles 独有该机制，但默认 `enabled: false`，与 Cline 默认行为对齐。Charles 的 Enhancement 段是一个可选的增强层，包含 5 个子段（tools_section / mcp_section / always_skills / skills_summary / memory），通过 YAML 配置文件控制开关，开启后作为 rule 追加到 `{{CHARLES_RULES}}` 内部末尾。**

### 核心结论

1. **存在性差异**：
   - **Cline**：**完全无 Enhancement 段机制**。base prompt 模板仅有 `{{CLINE_RULES}}` 和 `{{CLINE_METADATA}}` 两个占位符；`buildClineSystemPrompt` 的 effectiveRules 仅包含 `[rules, MODE_TAG_INSTRUCTIONS, PLAN_MODE_INSTRUCTIONS]`，无 tools_section / skills_summary / always_skills / mcp_section / memory 等增强层；`composeSystemPrompt` 编排器无配置开关控制增强层。Cline 的工具列表通过 tool 通道（function calling schema）传递，MCP 概览通过 extension 注册的工具描述传递，skills 通过 `skills` 工具按需加载，记忆段无独立机制。
   - **Charles**：**有 Enhancement 段机制（可选，默认关闭）**。通过 `agent_config/system_prompt.yaml` 的 `enhancements` 配置块控制，默认 `enabled: false`。开启后将 5 个子段作为 rule 追加到 `{{CHARLES_RULES}}` 内部末尾。

2. **内容差异**：
   - **Cline**：N/A（无 Enhancement 段）
   - **Charles**：5 个子段
     - `tools_section`：工具列表 + 使用指引 + 工具 vs 技能决策树 + 任务拆解强制规则（context.py L723-786）
     - `mcp_section`：MCP 服务器概览 + 工具列表（context.py L788-834）
     - `always_skills`：`always=True` 技能的指令（context.py L632-636，调用 `skills_registry.load_always_instructions()`）
     - `skills_summary`：技能目录摘要（context.py L638-642，调用 `skills_registry.build_summary()`）
     - `memory`：记忆段文本（context.py L644-645，直接使用 `self.memory`）

3. **注入方式差异**：
   - **Cline**：N/A（无 Enhancement 段）
   - **Charles**：Enhancement 段作为 rule 追加到 `{{CHARLES_RULES}}` 内部末尾。具体链路：`_build_rules()` L520-528 调用 `_build_enhancement_rules()` 生成 `[(title, body), ...]` 列表，每个 body 包装为 `RuleLoadResult(path=Path(f"__enhancements__/{title}.md"), body=body)`，最终由 `format_rules_content(results)` 统一添加 `##` 标题后拼接到 Rules 段。

4. **配置开关差异**：
   - **Cline**：无配置开关（无 Enhancement 段）
   - **Charles**：`agent_config/system_prompt.yaml` 的 `enhancements` 配置块
     - `enabled: false`（总开关，默认关闭）
     - `tools_section: true`（子开关，总开关关闭时强制 false）
     - `skills_summary: true`、`always_skills: true`、`mcp_section: true`、`memory: true`（同上）
     - 配置文件不存在或解析失败时，返回全部 false 的默认值

5. **段落位置勘误**：计划表 L2095 标注"段落位置 第 12 段"，但实际 Charles system prompt 顶层段仅 3 段（base + rules + metadata），Enhancement 段是 Rules 段内部的子段（第 6 项，位于 PLAN_MODE 之后、extra_sections 之前），不是独立的顶层第 12 段。

6. **nanobot 残留**：Enhancement 段对比层面 **1 处注释残留**（`agent/context.py` L275 `extra_sections` docstring 提到 "nanobot 风格"），**0 处实现逻辑残留**。该注释残留与 P5.2 / P5.11 阶段发现的是同一处（`extra_sections` 参数的 nanobot 注释），非 Enhancement 机制本身的残留。Enhancement 机制本身（`_load_enhancements` / `_build_enhancement_rules` / `_build_tools_section` / `_build_mcp_servers_section`）无任何 nanobot 注释或实现逻辑残留。

### 一致性总体评估

- **Enhancement 段存在性**：**Charles 额外**（Cline 无，Charles 有可选机制）
- **默认启用状态**：**对齐**（Cline 无该机制相当于始终不启用；Charles 默认 `enabled: false`，行为等价）
- **配置开关粒度**：**Charles 额外**（Charles 有 1 个总开关 + 5 个子开关，Cline 无配置需求）
- **注入方式**：**Charles 额外**（Charles 作为 rule 追加到 `{{CHARLES_RULES}}`，Cline 无此注入）
- **段落位置**：**Charles 额外**（Charles Enhancement 是 Rules 段内部子段，Cline 无此子段）
- **nanobot 残留**：1 处注释残留（与 P5.2/P5.11 同一处），0 处实现逻辑残留

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.15.1 | Enhancement 段存在性 | **无**。base prompt 仅 `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 两个占位符（system.ts L35-36 / L67-68）；effectiveRules 仅 `[rules, MODE_TAG, PLAN_MODE]`（cline.ts L145-151）；无 tools_section / skills_summary / always_skills / mcp_section / memory 机制 | **有**（可选）。`_build_enhancement_rules()`（context.py L611-647）生成 5 个子段，`_build_rules()` L520-528 注入 | Charles 额外 | 计划表 L2093 标注"Charles 额外"准确 |
| 5.15.2 | 默认启用状态 | N/A（无 Enhancement 段） | `enabled: false`（system_prompt.yaml L5）。`_load_enhancements()` L338 读取 `cfg.get("enabled", False)`，默认 false；配置文件不存在时返回全部 false 的默认值（L327-328） | 对齐 | 计划表 L2094 标注"false 合理增强"准确。Charles 默认关闭，与 Cline 无该机制的行为等价 |
| 5.15.3 | 段落位置 | N/A | Rules 段内部第 6 项（位于 PLAN_MODE 之后、extra_sections 之前）。`_build_rules()` L520-528 将增强层 rule 追加到 results 列表，最终由 `format_rules_content()` 统一格式化到 `{{CHARLES_RULES}}` 内 | Charles 额外 | 计划表 L2095 标注"第 12 段"与实际不符；实际是 Rules 段内部子段，非顶层第 12 段 |
| 5.15.4 | 配置开关机制 | 无配置开关 | `agent_config/system_prompt.yaml` 的 `enhancements` 配置块（L4-10）。1 个总开关 `enabled` + 5 个子开关（tools_section / skills_summary / always_skills / mcp_section / memory）。总开关关闭时所有子开关强制 false（L342） | Charles 额外 | Charles 独有的配置驱动机制，Cline 无配置需求 |
| 5.15.5 | tools_section 子段 | 无。工具列表通过 tool 通道（function calling schema）传递，不写入 system prompt | `_build_tools_section()`（context.py L723-786）：工具名 + 描述 + 使用指引 + 工具 vs 技能决策树 + 任务拆解强制规则 + 输出≠完成提醒 | Charles 额外 | Charles 将工具元数据写入 system prompt，Cline 走 tool schema 通道 |
| 5.15.6 | mcp_section 子段 | 无。MCP 工具通过 extension 注册为 tool，工具描述走 tool schema 通道 | `_build_mcp_servers_section()`（context.py L788-834）：MCP 服务器名 + transport + 描述 + 工具列表 | Charles 额外 | Charles 将 MCP 概览写入 system prompt，Cline 走 tool schema 通道 |
| 5.15.7 | always_skills 子段 | 无。Cline skills 按 LLM 需求通过 `skills` 工具加载，无 "always 预加载" 概念 | `skills_registry.load_always_instructions()`（context.py L632-636）：加载 `always=True` 技能的 SKILL.md 指令注入 system prompt | Charles 额外 | always 预加载是 nanobot 风格机制（详见 P4.20），Charles 通过 enhancement 开关控制是否启用 |
| 5.15.8 | skills_summary 子段 | 无。Cline skills 元数据通过 `skills` 工具的 description 暴露，无独立摘要段 | `skills_registry.build_summary()`（context.py L638-642）：生成技能目录摘要（名称 + 描述 + when_to_use）注入 system prompt | Charles 额外 | Charles 将技能目录写入 system prompt，Cline 走 tool description 通道 |
| 5.15.9 | memory 子段 | 无独立 memory 段。Cline 无记忆持久化机制 | `self.memory`（context.py L644-645）：直接将记忆文本作为 rule 注入 | Charles 额外 | Charles 独有的记忆段机制 |
| 5.15.10 | 注入路径 | N/A | `__enhancements__/{title}.md`（context.py L525）。作为 RuleLoadResult 追加到 results，由 `format_rules_content()` 统一添加 `## {title}` 标题 | Charles 额外 | 注入路径与 MODE_TAG（`__mode__/`）、extra_sections（`__extra__/`）并列 |
| 5.15.11 | 配置文件 fallback | N/A | `_load_enhancements()` L327-346：配置文件不存在时返回全部 false 默认值；解析失败时 catch Exception 返回默认值并 logger.debug | Charles 额外 | 配置文件缺失时优雅降级为全部关闭，与 Cline 默认行为对齐 |

---

## 三、重点差距详细说明

### 3.1 Cline 完全无 Enhancement 段机制（5.15.1 / 5.15.5 / 5.15.6 / 5.15.7 / 5.15.8 / 5.15.9）

Cline 的 system prompt 构建链路中，**完全没有 Enhancement 段机制**。具体体现在三个层面：

#### 层面一：base prompt 模板无 Enhancement 占位符

Cline 的 `DEFAULT_CLINE_SYSTEM_PROMPT`（system.ts L1-36）和 `YOLO_CLINE_SYSTEM_PROMPT`（system.ts L38-68）都只有两个动态占位符：

```typescript
// system.ts L35-36（DEFAULT 模板末尾）
{{CLINE_RULES}}
{{CLINE_METADATA}}`;
```

**无** `{{TOOLS_SECTION}}`、`{{SKILLS_SUMMARY}}`、`{{ALWAYS_SKILLS}}`、`{{MCP_SECTION}}`、`{{MEMORY}}` 等 Enhancement 占位符。

#### 层面二：effectiveRules 无 Enhancement 内容

Cline 的 `buildClineSystemPrompt`（cline.ts L145-151）构建的 effectiveRules 仅包含三项：

```typescript
const effectiveRules = [
    rules,
    MODE_TAG_INSTRUCTIONS,
    mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined,
]
    .filter(Boolean)
    .join("\n\n");
```

**无** tools_section、skills_summary、always_skills、mcp_section、memory 等增强层内容。

#### 层面三：编排器无 Enhancement 配置开关

Cline 的 `composeSystemPrompt`（session-runtime-orchestrator.ts L680-689）遍历 `contributionRegistry.getRegisteredRules()` 收集扩展 rule，但**无** enhancement 配置开关，**无** YAML 配置文件，**无** `_load_enhancements` 等价方法。

#### Cline 的等价机制（走 tool 通道，非 system prompt 通道）

Cline 的工具元数据、MCP 概览、skills 信息**不写入 system prompt**，而是通过以下通道传递：

| Charles Enhancement 子段 | Cline 等价机制 | 通道 |
|--------------------------|---------------|------|
| tools_section | 工具的 name + description + input_schema | function calling tool schema |
| mcp_section | MCP 工具注册为普通 tool，走 tool schema | function calling tool schema |
| always_skills | 无等价（Cline skills 按 LLM 需求通过 `skills` 工具加载） | tool 调用 |
| skills_summary | skills 工具的 description 暴露技能列表 | function calling tool schema |
| memory | 无等价（Cline 无记忆持久化机制） | 无 |

**关键差异**：Cline 走 tool schema 通道（LLM 通过 function calling 接口获取工具元数据）；Charles 走 system prompt 通道（工具元数据写入 system prompt 文本）。两种通道各有优劣：tool schema 通道更结构化、token 占用更可控；system prompt 通道更灵活、可注入使用指引和决策树等长文本。

### 3.2 Charles 的 Enhancement 段机制（5.15.1 / 5.15.4 / 5.15.10 / 5.15.11）

Charles 的 Enhancement 段是一个完整的可选增强层机制，包含配置加载、rule 生成、注入三个环节：

#### 环节一：配置加载（`_load_enhancements`，context.py L304-346）

```python
def _load_enhancements(self) -> dict[str, bool]:
    default = {
        "enabled": False,
        "tools_section": True,
        "skills_summary": True,
        "always_skills": True,
        "mcp_section": True,
        "memory": True,
    }
    if not self.config_path.exists():
        return default
    try:
        import yaml
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        cfg = data.get("enhancements", {})
        if not isinstance(cfg, dict):
            return default
        enabled = bool(cfg.get("enabled", False))
        result: dict[str, bool] = {"enabled": enabled}
        for key in ("tools_section", "skills_summary", "always_skills", "mcp_section", "memory"):
            # 总开关关闭时，所有子开关强制 false
            result[key] = enabled and bool(cfg.get(key, True))
        return result
    except Exception as e:
        logger.debug("SystemPromptBuilder: 读取增强层配置失败（已忽略）: %s", e)
        return default
```

**关键设计**：
- 默认 `enabled: false`，与 Cline 无该机制的行为对齐
- 总开关关闭时，所有子开关强制 false（`enabled and bool(cfg.get(key, True))`）
- 配置文件不存在或解析失败时，返回全部 false 的默认值（优雅降级）
- 子开关默认值为 `True`（即开启总开关后，所有子段默认全部启用）

#### 环节二：rule 生成（`_build_enhancement_rules`，context.py L611-647）

```python
def _build_enhancement_rules(self) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    if self._enhancements.get("tools_section"):
        body = self._build_tools_section()
        if body:
            rules.append(("charles-tools-overview", body))
    if self._enhancements.get("mcp_section"):
        body = self._build_mcp_servers_section()
        if body:
            rules.append(("charles-mcp-overview", body))
    if self._enhancements.get("always_skills") and self.skills_registry:
        body = self.skills_registry.load_always_instructions()
        if body:
            rules.append(("charles-always-skills", body))
    if self._enhancements.get("skills_summary") and self.skills_registry:
        body = self.skills_registry.build_summary()
        if body:
            rules.append(("charles-skills-summary", body))
    if self._enhancements.get("memory") and self.memory:
        rules.append(("charles-memory", self.memory))
    return rules
```

**关键设计**：
- 返回 `[(rule_title, rule_body), ...]` 列表，body 为纯正文（不含 `##` 标题，由 `format_rules_content` 统一添加）
- 每个子段独立检查开关 + 检查 body 非空，避免空 rule 注入
- always_skills 和 skills_summary 依赖 `skills_registry` 非空
- memory 依赖 `self.memory` 非空

#### 环节三：注入链路（`_build_rules`，context.py L520-528）

```python
# 6. 增强层（按配置开关）
if self._enhancements.get("enabled"):
    for title, body in self._build_enhancement_rules():
        if body:
            results.append(RuleLoadResult(
                path=Path(f"__enhancements__/{title}.md"),
                body=body,
                activated=True,
            ))
```

**关键设计**：
- 注入位置在 `_build_rules()` 的第 6 步（位于 PLAN_MODE 之后、extra_sections 之前）
- 每个增强层 rule 包装为 `RuleLoadResult(path=Path(f"__enhancements__/{title}.md"), body=body, activated=True)`
- 最终由 `format_rules_content(results)` 统一格式化为 `# Rules\n## {title}\n{body}` 格式，拼接到 `{{CHARLES_RULES}}` 内

### 3.3 段落位置勘误（5.15.3）

计划表 L2095 标注 Charles Enhancement 段位置为"第 12 段"，但实际 Charles system prompt 顶层段仅 3 段：

```
[C-1] Base Prompt（身份 + 通用规则 + 工具调用规则 + <env>）
[C-2] {{CHARLES_RULES}} → effectiveRules（AGENTS.md + rules_dir + MODE_TAG + PLAN_MODE? + enhancements? + extra_sections?）
[C-3] {{CHARLES_METADATA}} → workspace metadata
```

Enhancement 段是 Rules 段（`{{CHARLES_RULES}}`）内部的子段，具体是 `_build_rules()` 的第 6 步：

```
_build_rules() 组装顺序:
  1. 全局 AGENTS.md（~/.agent/AGENTS.md）
  2. workspace agents_path（兼容旧接口）
  3. workspace rules_dir
  4. MODE_TAG_INSTRUCTIONS
  5. PLAN_MODE_INSTRUCTIONS（仅 plan 模式）
  6. 增强层（enhancements，按配置开关）    ← Enhancement 段位置
  7. 额外段落（extra_sections，已废弃）
```

因此 Enhancement 段不是独立的顶层第 12 段，而是 Rules 段内部的第 6 项子段。"第 12 段"可能是基于将 Rules 段内部所有子段拆分计数后的累计编号，但这一计数方式与 Cline system prompt 顶层段的计数方式不一致。

### 3.4 默认关闭的合理性（5.15.2）

Charles 的 Enhancement 段默认 `enabled: false`，这一设计与 Cline 的对齐性体现在：

| 维度 | Cline（无 Enhancement 段） | Charles（Enhancement 默认关闭） | 行为等价性 |
|------|--------------------------|-------------------------------|-----------|
| system prompt 中的工具列表 | 无（走 tool schema） | 无（enhancement 关闭） | 等价 |
| system prompt 中的 MCP 概览 | 无（走 tool schema） | 无（enhancement 关闭） | 等价 |
| system prompt 中的 skills 摘要 | 无（走 tool description） | 无（enhancement 关闭） | 等价 |
| system prompt 中的 always skills 指令 | 无（走 skills 工具按需加载） | 无（enhancement 关闭） | 等价 |
| system prompt 中的 memory 段 | 无 | 无（enhancement 关闭） | 等价 |

**结论**：Charles Enhancement 段默认关闭时，其 system prompt 行为与 Cline 完全等价（均不在 system prompt 中注入工具/MCP/skills/memory 元数据）。开启 Enhancement 段是 Charles 的合理增强，用于在量化投研场景下提供更丰富的工具使用指引和决策树。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（1 处，1 个文件，与 P5.2/P5.11 同一处）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/context.py` | L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` | docstring 参数说明 |

**注释残留说明**：
- 该残留是 `extra_sections` 参数的 docstring，**不是 Enhancement 机制的残留**。
- `extra_sections` 是 `SystemPromptBuilder.__init__()` 的一个已废弃参数（context.py L255 / L292），与 Enhancement 机制（`_enhancements` / `_build_enhancement_rules`）是**不同的代码路径**：
  - `extra_sections` 走 `_build_rules()` L530-537，注入路径为 `__extra__/{title}.md`
  - Enhancement 走 `_build_rules()` L520-528，注入路径为 `__enhancements__/{title}.md`
- 该注释残留与 P5.2 阶段 4.1 节、P5.11 阶段 4.1 节发现的是同一处，本阶段不重复修复建议。

### 4.2 实现逻辑残留（0 处）

**Enhancement 段对比层面的实现逻辑残留：无**。

逐项验证：
- **`_load_enhancements()` 配置加载**（context.py L304-346）：从 YAML 文件读取配置，无 nanobot 残留。配置文件格式（`enhancements.enabled` / `enhancements.tools_section` 等）是 Charles 独有设计，无 nanobot 对应物。
- **`_build_enhancement_rules()` rule 生成**（context.py L611-647）：生成 5 个子段的 rule 列表，无 nanobot 残留。子段命名（`charles-tools-overview` / `charles-mcp-overview` / `charles-always-skills` / `charles-skills-summary` / `charles-memory`）使用 `charles-` 前缀，无 nanobot 命名。
- **`_build_tools_section()` 工具概览**（context.py L723-786）：构建工具列表 + 使用指引 + 决策树，无 nanobot 残留。
- **`_build_mcp_servers_section()` MCP 概览**（context.py L788-834）：构建 MCP 服务器列表，无 nanobot 残留。
- **`always_skills` 子段**（context.py L632-636）：调用 `skills_registry.load_always_instructions()`。虽然 `always` 预加载机制本身是 nanobot 风格残留（详见 P4.20），但该机制的 nanobot 残留属于技能系统层面（SkillMetadata.always 字段 + SkillRegistry 方法），不属于 Enhancement 段层面的残留。Enhancement 段只是消费方，通过配置开关控制是否启用 always_skills 子段。
- **`skills_summary` 子段**（context.py L638-642）：调用 `skills_registry.build_summary()`。同上，`when_to_use` 字段的 nanobot 残留属于技能系统层面（详见 P4.20），不属于 Enhancement 段层面。
- **`memory` 子段**（context.py L644-645）：直接使用 `self.memory` 文本，无 nanobot 残留。
- **注入链路**（context.py L520-528）：将增强层 rule 追加到 results，注入路径 `__enhancements__/{title}.md`，无 nanobot 残留。
- **配置文件**（system_prompt.yaml L1-10）：YAML 格式配置，注释为中文，无 nanobot 残留。
- **base prompt 模板**（charles_system_prompt.py L29-91）：无 Enhancement 占位符，增强层走 `{{CHARLES_RULES}}` 通道，无 nanobot 残留。

### 4.3 Enhancement 机制与 nanobot 的关联说明

需区分两个层次：

**层次一：Enhancement 段机制本身（无 nanobot 残留）**
- `_load_enhancements()` / `_build_enhancement_rules()` / 注入链路：Charles 独有设计，无 nanobot 对应物，无 nanobot 残留。
- 配置文件 `system_prompt.yaml`：Charles 独有设计，无 nanobot 残留。

**层次二：Enhancement 子段消费的技能系统机制（有 nanobot 残留，但属于 P4.20 范畴）**
- `always_skills` 子段消费 `skills_registry.load_always_instructions()`，该方法的 `always` 预加载机制是 nanobot 风格残留（P4.20 P0-1）。
- `skills_summary` 子段消费 `skills_registry.build_summary()`，该方法消费的 `when_to_use` 字段是 nanobot 风格残留（P4.20 P0-2）。

**结论**：Enhancement 段机制本身无 nanobot 残留；其消费的技能系统机制（always / when_to_use）有 nanobot 残留，但属于 P4.20 范畴，本阶段不重复修复建议。

### 4.4 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（docstring 提到 nanobot） | 1 处（context.py L275，与 P5.2/P5.11 同一处） | 低 | 可保留作为设计溯源参考，或统一清理（与 P5.2 P2-1 一致） |
| 实现逻辑残留（Enhancement 段层面） | 0 处 | 无 | 无需处理 |
| 关联残留（子段消费的技能系统机制） | 间接（always_skills / skills_summary 子段消费 nanobot 风格机制） | 中 | 由 P4.20 P0-1 / P0-2 统一处理 |

### 4.5 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（1 处）：context.py L275 docstring 中提到"nanobot 风格的额外段落"，这是 `extra_sections` 参数的设计溯源说明，与 Enhancement 机制无关，删除后功能不变。

**实现逻辑残留**（0 处）：Enhancement 段对比层面无 nanobot 实现逻辑残留。具体来说：
- Enhancement 配置加载机制：Charles 独有设计，无 nanobot 复刻
- Enhancement rule 生成机制：Charles 独有设计，无 nanobot 复刻
- Enhancement 注入链路：Charles 独有设计，无 nanobot 复刻
- Enhancement 子段内容（tools_section / mcp_section / memory）：Charles 独有设计，无 nanobot 复刻
- Enhancement 子段消费的技能系统机制（always_skills / skills_summary）：间接关联 P4.20 范畴的 nanobot 残留，非 Enhancement 段本身残留

**关联说明**：`extra_sections` 参数的 nanobot 注释残留与 P5.2 / P5.11 阶段发现的是同一处（context.py L275），本阶段不重复修复建议，统一在 P5.2 的 P2-1 修复建议中处理。

---

## 五、Enhancement 段机制完整性矩阵

### 5.1 Cline Enhancement 机制清单

| 机制编号 | 机制名称 | 存在性 | 位置 | 说明 |
|---------|---------|--------|------|------|
| ENH-C-1 | Enhancement 段配置开关 | **无** | — | Cline 无 enhancement 配置 |
| ENH-C-2 | Enhancement 段配置加载 | **无** | — | Cline 无 `_load_enhancements` 等价方法 |
| ENH-C-3 | Enhancement 段 rule 生成 | **无** | — | Cline 无 `_build_enhancement_rules` 等价方法 |
| ENH-C-4 | tools_section 子段 | **无** | — | 工具元数据走 tool schema 通道 |
| ENH-C-5 | mcp_section 子段 | **无** | — | MCP 工具走 tool schema 通道 |
| ENH-C-6 | always_skills 子段 | **无** | — | Cline skills 按 LLM 需求加载，无 always 预加载 |
| ENH-C-7 | skills_summary 子段 | **无** | — | skills 元数据走 tool description 通道 |
| ENH-C-8 | memory 子段 | **无** | — | Cline 无记忆持久化机制 |
| ENH-C-9 | Enhancement 注入链路 | **无** | — | Cline 无 enhancement rule 注入 |

### 5.2 Charles Enhancement 机制清单

| 机制编号 | 机制名称 | 存在性 | 位置 | 说明 |
|---------|---------|--------|------|------|
| ENH-S-1 | Enhancement 段配置开关 | 存在 | system_prompt.yaml L4-10 | 1 个总开关 + 5 个子开关，默认全部关闭 |
| ENH-S-2 | Enhancement 段配置加载 | 存在 | context.py L304-346 | `_load_enhancements()`，配置缺失时优雅降级 |
| ENH-S-3 | Enhancement 段 rule 生成 | 存在 | context.py L611-647 | `_build_enhancement_rules()`，返回 `[(title, body), ...]` |
| ENH-S-4 | tools_section 子段 | 存在 | context.py L723-786 | `_build_tools_section()`，含工具列表 + 决策树 |
| ENH-S-5 | mcp_section 子段 | 存在 | context.py L788-834 | `_build_mcp_servers_section()`，含 MCP 服务器列表 |
| ENH-S-6 | always_skills 子段 | 存在 | context.py L632-636 | 调用 `skills_registry.load_always_instructions()` |
| ENH-S-7 | skills_summary 子段 | 存在 | context.py L638-642 | 调用 `skills_registry.build_summary()` |
| ENH-S-8 | memory 子段 | 存在 | context.py L644-645 | 直接使用 `self.memory` 文本 |
| ENH-S-9 | Enhancement 注入链路 | 存在 | context.py L520-528 | 作为 rule 追加到 `__enhancements__/{title}.md` |
| ENH-S-10 | extra_sections 参数（已废弃） | 存在（dead code） | context.py L255 / L292 / L530-537 | nanobot 风格残留，当前无调用方传入，与 Enhancement 机制是不同代码路径 |

### 5.3 机制存在性对比矩阵

| 机制类型 | Cline | Charles | 差异 |
|---------|-------|---------|------|
| Enhancement 配置开关 | 无 | 有（system_prompt.yaml） | Charles 额外 |
| Enhancement 配置加载 | 无 | 有（`_load_enhancements`） | Charles 额外 |
| Enhancement rule 生成 | 无 | 有（`_build_enhancement_rules`） | Charles 额外 |
| tools_section 子段 | 无（走 tool schema） | 有（`_build_tools_section`） | Charles 额外，通道不同 |
| mcp_section 子段 | 无（走 tool schema） | 有（`_build_mcp_servers_section`） | Charles 额外，通道不同 |
| always_skills 子段 | 无（无 always 预加载） | 有（`load_always_instructions`） | Charles 额外，消费 nanobot 风格机制 |
| skills_summary 子段 | 无（走 tool description） | 有（`build_summary`） | Charles 额外，通道不同 |
| memory 子段 | 无 | 有（`self.memory`） | Charles 额外 |
| Enhancement 注入链路 | 无 | 有（`__enhancements__/{title}.md`） | Charles 额外 |
| extra_sections 参数 | 无 | 有（已废弃，dead code） | Charles 独有，nanobot 风格残留 |

---

## 六、修复建议

### 6.1 高优先级（P1）

#### P1-1: 评估 Enhancement 段机制的保留必要性（5.15.1 / 5.15.4）

**问题**：Charles 独有的 Enhancement 段机制是合理增强还是冗余设计？

**影响范围**：
- `agent/context.py` L304-346（`_load_enhancements`）+ L611-647（`_build_enhancement_rules`）+ L520-528（注入链路）+ L723-786（`_build_tools_section`）+ L788-834（`_build_mcp_servers_section`）
- `agent_config/system_prompt.yaml` L1-10（配置文件）

**评估结论**：**建议保留**。理由：
1. **默认关闭，与 Cline 行为对齐**：`enabled: false` 时 Charles system prompt 行为与 Cline 完全等价。
2. **量化投研场景的合理增强**：开启后注入的工具使用指引、技能决策树、任务拆解强制规则等，针对量化投研工作流（read-pdf / stock-price / financial-analysis 等技能）提供场景化指引，Cline 的通用 tool schema 通道无法表达这些长文本指引。
3. **配置驱动，无硬编码**：通过 YAML 配置文件控制开关，用户可按需启用，不影响默认行为。

**建议**：在 `_load_enhancements()` 方法的 docstring 中明确标注"Charles 独有增强层，Cline 无此机制；默认关闭，开启后注入工具/技能/MCP/记忆段到 system prompt"。

### 6.2 中优先级（P2）

#### P2-1: 勘误计划表的"第 12 段"标注（3.3）

**影响范围**：`AGENT_COMPARISON_PLAN_V2.md` L2095（5.15.3 项"段落位置"列）

**修复方案**：将"第 12 段"改为"Rules 段内部第 6 项子段（位于 PLAN_MODE 之后、extra_sections 之前）"。

**理由**：实际 Charles system prompt 顶层段仅 3 段（base + rules + metadata），Enhancement 段是 Rules 段内部的子段，非顶层第 12 段。

#### P2-2: 清理 extra_sections 已废弃参数的 nanobot 注释（4.1）

**影响范围**：`agent/context.py` L275（docstring）+ L255（参数签名）+ L292（初始化）+ L530-537（消费逻辑）

**修复方案**：
1. 若确认无调用方传入 `extra_sections`（docstring 已声明"当前无调用方传入"），可移除该参数及其消费逻辑（L530-537）。
2. 若保留参数以向后兼容，修正 docstring 移除"nanobot 风格"描述，改为"已废弃，保留参数签名仅为向后兼容"。

**理由**：本项与 P5.2 / P5.11 阶段 P2-1 修复建议一致，统一处理。该残留与 Enhancement 机制无关，是 `extra_sections` 参数的独立问题。

### 6.3 低优先级（P3）

#### P3-1: 补充 Enhancement 段机制的架构文档（5.15.1 / 5.15.4）

**问题**：Charles Enhancement 段机制与 Cline 的架构差异未在代码文档中明确说明。

**修复方案**：在 `SystemPromptBuilder` 类 docstring 中补充：
- "Charles 独有 Enhancement 段机制（Cline 无此机制），通过 `agent_config/system_prompt.yaml` 控制开关"
- "默认 `enabled: false`，与 Cline 行为对齐；开启后注入 tools_section / mcp_section / always_skills / skills_summary / memory 五个子段到 Rules 末尾"
- "Cline 的工具/MCP/skills 元数据走 tool schema 通道，Charles Enhancement 段走 system prompt 通道，两种通道各有优劣"

**理由**：明确架构差异有助于后续开发者理解 Charles Enhancement 段的设计取舍。

#### P3-2: 评估 always_skills / skills_summary 子段与 P4.20 修复的联动（4.3）

**问题**：P4.20 阶段建议移除 `always` 预加载机制和 `when_to_use` 字段，若执行该修复，Enhancement 段的 `always_skills` 和 `skills_summary` 子段将受影响。

**影响范围**：
- `always_skills` 子段（context.py L632-636）：若移除 `always` 机制，`load_always_instructions()` 方法将无数据返回，子段自动失效（body 为空，不注入）。
- `skills_summary` 子段（context.py L638-642）：若移除 `when_to_use` 字段，`build_summary()` 输出将不再包含 `when_to_use` 列，但子段仍可正常工作（仅输出 name + description）。

**修复方案**：
- 若 P4.20 P0-1（移除 always 机制）执行：同步移除 Enhancement 配置中的 `always_skills` 子开关（system_prompt.yaml L8）+ `_build_enhancement_rules` 中的 always_skills 分支（context.py L632-636）。
- 若 P4.20 P0-2（移除 when_to_use 字段）执行：`skills_summary` 子段无需改动，`build_summary()` 会自动适配。

**理由**：Enhancement 段是消费方，技能系统的 nanobot 残留修复需同步考虑 Enhancement 段的联动影响。

---

## 七、验证方法建议

### 7.1 Cline Enhancement 机制缺失验证

1. **Cline base prompt 无 Enhancement 占位符**：
   ```
   Grep "TOOLS_SECTION|SKILLS_SUMMARY|ALWAYS_SKILLS|MCP_SECTION|MEMORY" third_party/cline/sdk/packages/shared/src/prompt/system.ts
   # 预期：0 命中
   ```

2. **Cline effectiveRules 无 Enhancement 内容**：
   ```
   Grep "tools_section|skills_summary|always_skills|mcp_section|memory" third_party/cline/sdk/packages/shared/src/prompt/cline.ts
   # 预期：0 命中
   ```

3. **Cline 编排器无 Enhancement 配置开关**：
   ```
   Grep "enhancement|_load_enhancements" third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts
   # 预期：0 命中
   ```

### 7.2 Charles Enhancement 机制存在性验证

1. **Charles 配置文件存在且默认关闭**：
   ```
   Read agent_config/system_prompt.yaml
   # 预期：enhancements.enabled: false
   ```

2. **Charles Enhancement 加载逻辑存在**：
   ```
   Grep "_load_enhancements|_build_enhancement_rules" agent/context.py
   # 预期：命中 L304（定义）+ L302（调用）+ L611（定义）+ L522（调用）
   ```

3. **Charles Enhancement 子段构建方法存在**：
   ```
   Grep "_build_tools_section|_build_mcp_servers_section" agent/context.py
   # 预期：命中 L723（tools_section 定义）+ L788（mcp_section 定义）
   ```

4. **Charles Enhancement 注入路径**：
   ```
   Grep "__enhancements__" agent/context.py
   # 预期：命中 L525（注入路径）
   ```

### 7.3 nanobot 残留验证

1. **Enhancement 段层面 nanobot 残留**：
   ```
   Grep "nanobot" agent/context.py
   # 预期：命中 1 处（L275 extra_sections docstring，与 Enhancement 机制无关）
   ```

2. **Enhancement 机制本身无 nanobot 残留**：
   ```
   Grep "nanobot" agent_config/system_prompt.yaml
   # 预期：0 命中
   ```

3. **charles_system_prompt.py 无 nanobot 残留**：
   ```
   Grep "nanobot" agent/prompts/charles_system_prompt.py
   # 预期：0 命中
   ```

### 7.4 Enhancement 段默认关闭行为验证

```python
# 验证默认关闭时 system prompt 不含增强层内容
from agent.context import SystemPromptBuilder
builder = SystemPromptBuilder(working_dir=".", ide_name="test")
prompt = builder.build()
# 预期：prompt 中不含 "# 工具" / "# MCP 服务器" / "charles-tools-overview" 等增强层标题
assert "# 工具" not in prompt
assert "# MCP 服务器" not in prompt
assert "charles-tools-overview" not in prompt
```

### 7.5 Enhancement 段开启行为验证

```python
# 验证开启后 system prompt 含增强层内容（需有 tools / skills_registry / memory）
from agent.context import SystemPromptBuilder
builder = SystemPromptBuilder(
    working_dir=".",
    ide_name="test",
    tools=[...],  # 非空工具列表
    memory="测试记忆",
    config_path="agent_config/system_prompt.yaml",  # 临时修改为 enabled: true
)
# 需先修改 system_prompt.yaml 的 enabled: true
prompt = builder.build()
# 预期：prompt 中含 "# 工具" / "charles-tools-overview" 等增强层标题
```

---

## 八、与 P5.1 / P5.2 / P5.11 及其他阶段的衔接

### 8.1 与 P5.1 的衔接

| P5.1 发现 | P5.15 衔接 |
|----------|----------|
| 两者均采用 base + rules + metadata 三层骨架 | 确认 Charles Enhancement 段是 Rules 段内部的子段，非独立的第 4 层 |
| Charles 的 `_build_enhancement_rules` 将 always-skills + skills-summary 作为 rules 追加 | 本阶段深入分析了 Enhancement 段的 5 个子段（tools_section / mcp_section / always_skills / skills_summary / memory），P5.1 仅提及 2 个 |
| skills 注入机制差异（Charles 作为 rules 注入 vs Cline 通过 extension 注册为工具） | 本阶段确认 Cline 完全无 Enhancement 段机制，Charles 的 skills 注入是 Enhancement 段的子段之一，受配置开关控制 |

### 8.2 与 P5.2 的衔接

| P5.2 发现 | P5.15 衔接 |
|----------|----------|
| Charles 段落清单含 Enhancement 段（可选） | 本阶段确认 Enhancement 段的位置是 Rules 段内部第 6 项子段，非顶层独立段 |
| `extra_sections` 参数是 nanobot 风格已废弃残留 | 本阶段确认 `extra_sections` 与 Enhancement 机制是不同代码路径（`__extra__/` vs `__enhancements__/`），nanobot 注释残留与 Enhancement 机制无关 |

### 8.3 与 P5.11 的衔接

| P5.11 发现 | P5.15 衔接 |
|----------|----------|
| Charles 缺失 Cline 的 `composeSystemPrompt()` 扩展 rule 合并机制 | 本阶段确认 Charles 的 Enhancement 段不是 Cline 扩展 rule 机制的等价实现，而是 Charles 独有的配置驱动增强层 |
| `extra_sections` 参数是 nanobot 风格 dead code | 本阶段再次确认该残留，与 P5.11 结论一致，统一在 P5.2 P2-1 处理 |

### 8.4 与 P4.20 的衔接

| P4.20 发现 | P5.15 衔接 |
|----------|----------|
| `always` 预加载机制是 nanobot 风格残留（P0-1） | Enhancement 段的 `always_skills` 子段消费该机制，若 P4.20 P0-1 执行需同步移除 `always_skills` 子段（P3-2） |
| `when_to_use` 字段是 nanobot 风格残留（P0-2） | Enhancement 段的 `skills_summary` 子段消费该字段，若 P4.20 P0-2 执行 `skills_summary` 子段自动适配（无需改动） |

### 8.5 本阶段新增发现（P5.1 / P5.2 / P5.11 未覆盖）

1. **Enhancement 段的 5 个子段完整清单**（5.15.5 - 5.15.9）：P5.1 仅提及 always-skills + skills-summary 两个子段，本阶段完整列出 5 个子段（tools_section / mcp_section / always_skills / skills_summary / memory）。
2. **Enhancement 段的配置开关机制**（5.15.4）：P5.1 / P5.2 仅提及"受配置开关控制"，本阶段深入到 YAML 配置文件结构（1 个总开关 + 5 个子开关）和加载逻辑（`_load_enhancements` 的优雅降级）。
3. **Enhancement 段的注入路径**（5.15.10）：确认注入路径为 `__enhancements__/{title}.md`，与 MODE_TAG（`__mode__/`）、extra_sections（`__extra__/`）并列。
4. **Cline 的等价机制通道差异**（3.1）：Cline 工具/MCP/skills 元数据走 tool schema 通道，Charles Enhancement 段走 system prompt 通道，两种通道各有优劣。
5. **段落位置"第 12 段"勘误**（3.3）：计划表 L2095 标注与实际不符，实际是 Rules 段内部第 6 项子段。
6. **Enhancement 段与 P4.20 修复的联动影响**（P3-2）：P4.20 的 nanobot 残留修复需同步考虑 Enhancement 段的 always_skills / skills_summary 子段。

---

## 附录：检查覆盖声明

- **Cline 源码**：
  - `sdk/packages/shared/src/prompt/cline.ts`（L1-166）：100% 完整审阅（buildClineSystemPrompt 纯组装器，effectiveRules 无 Enhancement 内容）
  - `sdk/packages/shared/src/prompt/system.ts`（L1-68）：100% 完整审阅（DEFAULT / YOLO 模板，无 Enhancement 占位符）
  - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`（L680-689 关键段落）：通过 P5.11 已审阅，本阶段引用结论（composeSystemPrompt 无 Enhancement 配置开关）

- **Charles 源码**：
  - `agent/context.py`（L1-2666）：100% 完整审阅（含 SystemPromptBuilder + ContextCompactor，确认 Enhancement 机制完整链路）
  - `agent/prompts/charles_system_prompt.py`（L1-94）：100% 完整审阅（base prompt 模板，无 Enhancement 占位符）
  - `agent_config/system_prompt.yaml`（L1-10）：100% 完整审阅（Enhancement 配置文件）
  - `agent/skills/registry.py`（L215 关键 docstring）：关键段落审阅（build_summary 与 enhancements 的关联说明）

- **nanobot 溯源**：
  - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`：通过 P5.2 已审阅，本阶段引用结论（nanobot 原生无独立 Enhancement 段配置机制）

- **11 项对比项**（5.15.1 - 5.15.11）：100% 逐项核对

本报告未修改任何源码，仅输出审计报告文件。
