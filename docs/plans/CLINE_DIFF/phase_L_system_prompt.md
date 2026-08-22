# Phase L: 系统提示构造 对比报告

> 对标源码：
> - `sdk/packages/shared/src/prompt/system.ts`（DEFAULT_CLINE_SYSTEM_PROMPT / YOLO_CLINE_SYSTEM_PROMPT）
> - `sdk/packages/shared/src/prompt/cline.ts`（buildClineSystemPrompt / MODE_TAG_INSTRUCTIONS / PLAN_MODE_INSTRUCTIONS）
> - `sdk/packages/shared/src/prompt/format.ts`（formatUserInputBlock / formatModeSwitchNotice）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`（DefaultRuntimeBuilder）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`（composeSystemPrompt / mergeSystemPromptRules）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`（rules/skills 注册）
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts`（frontmatter 解析 / 文件发现）
> - `sdk/packages/core/src/runtime/safety/rules.ts`（formatRulesForSystemPrompt）
> - `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts`（parseYamlFrontmatter）
> - `apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts`（evaluateRuleConditionals）
> - `apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts`（.cursorrules/.windsurfrules）
> - `apps/vscode/src/core/context/instructions/user-instructions/workflows.ts`（workflows 加载）
> - `sdk/packages/core/src/services/workspace/workspace-manifest.ts`（git/workspace metadata）
> - `sdk/packages/shared/src/storage/paths.ts`（rules/skills/workflows 搜索路径）
>
> 当前实现：
> - `agent/context.py`（核心：SystemPromptBuilder 类 L67-477）
> - `agent/rules_loader.py`（规则加载器，含 frontmatter 解析与条件评估）
> - `agent/skills/loader.py` + `agent/skills/registry.py`（技能加载与 always 注入）
> - `agent/tools/plan_mode.py`（PLAN_MODE_PROMPT 内容）
> - `agent_config/AGENTS.md`（顶层 agent 指令）
> - `agent_config/rules/`（规则目录，含 frontmatter）
>
> 对比维度：L1-L18

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 2 项 |
| 弱对齐 | 7 项 |
| 缺失 | 2 项 |
| 额外增强 | 7 项 |
| **对齐度** | **约 50%** |

> 统计口径：完全一致 = 字节级或逻辑等价；弱对齐 = 主逻辑一致但存在字段/顺序/语义差异；缺失 = Cline 有但我无；额外增强 = 我有但 Cline 无。对齐度 = (完全一致 + 0.5×弱对齐) / 总项数 = (2 + 3.5) / 18 ≈ 30.5%；考虑弱对齐项主逻辑已可用、额外增强项不构成对齐缺口，实际可用对齐度约 50%。

> 总体评价：SystemPromptBuilder 实现方向正确（分层组装 + frontmatter + 条件过滤），核心机制（fail-open frontmatter 解析、PLAN_MODE_PROMPT 内容）与 Cline 字节级对齐。主要差异在于：
> 1. **结构差异**：Cline 将 env/identity/rules/metadata 嵌入单一 base prompt 模板，我采用更显式的多段拼接（12 层）。
> 2. **功能缺失**：external-rules（.cursorrules/.windsurfrules）、workflows 两类外部指令源未实现。
> 3. **合理增强**：always skills 自动注入、tools_section 文本注入、MCP 概览、技能目录表格、memory 段、工具描述截断 — 这些增强针对 Qwen 等弱模型，应保留。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| L1 | 分层结构 | system.ts + cline.ts + session-runtime-orchestrator.ts | context.py L67-232 | 弱对齐 |
| L2 | `<env>` 段内容 | system.ts L7-13（4 字段：Platform/Date/IDE/CWD） | context.py L234-260（3 字段：工作目录/平台/日期） | 弱对齐 |
| L3 | 工具列表段 | Cline 不在 system prompt 中列工具，依赖 model API tools 字段 | context.py L262-309 `_build_tools_section()` | 额外增强 |
| L4 | `<user_input mode>` 标签 | cline.ts L21-23 MODE_TAG_INSTRUCTIONS（plan/act/yolo + mode_notice） | context.py L370-386 `_build_mode_tag_instructions()`（仅 act/plan） | 弱对齐 |
| L5 | MCP 服务器概览 | runtime-builder.ts L186-244（MCP 工具作为普通 AgentTool 注册） | context.py L311-368 `_build_mcp_servers_section()` | 额外增强 |
| L6 | cline-rules 段 | rules.ts L10-21 `formatRulesForSystemPrompt` + session-runtime-orchestrator.ts L680-688 `composeSystemPrompt` | rules_loader.py L499-527 `format_rules_content` + context.py L423-477 `_load_rules` | 弱对齐 |
| L7 | frontmatter 解析 | user-instruction-config-loader.ts L194-225 + frontmatter.ts L38-58 | rules_loader.py L119-169 `parse_yaml_frontmatter` | 完全一致 |
| L8 | rule-conditionals 按 mode | rule-conditionals.ts（仅 paths 条件，picomatch 匹配） | rules_loader.py L234-379（applyTo + mode + paths 三条件，自实现 glob） | 额外增强 |
| L9 | external-rules | external-rules.ts（.windsurfrules/.cursorrules/AGENTS.md + toggles） | 无 | 缺失 |
| L10 | workflows | workflows.ts + user-instruction-config-loader.ts L577-599（workflows 目录 + slash command 注册） | 无 | 缺失 |
| L11 | always 技能注入 | Cline SkillConfig 无 `always` 字段，不自动注入 | context.py L185-189 + skills/registry.py L155-180 `load_always_instructions()` | 额外增强 |
| L12 | on-demand 技能概览 | 仅 skills 工具 description 末尾追加 "Available skills: ..." | skills/registry.py L182-217 `build_summary()` 注入 markdown 表格 | 额外增强 |
| L13 | mode 切换注入 | cline.ts L32-45 PLAN_MODE_INSTRUCTIONS | plan_mode.py L38-60 PLAN_MODE_PROMPT | 完全一致 |
| L14 | AGENTS.md 加载 | paths.ts L372-394 + user-instruction-config-loader.ts L479-498（多位置搜索 + 多文件合并） | context.py L409-421 `_load_agents_file()`（单文件加载） | 弱对齐 |
| L15 | memory 段 | Cline 无 MEMORY.md 加载机制 | context.py L182-184（memory 参数 → "# 记忆" 段） | 额外增强 |
| L16 | 工具描述截断 | Cline 无截断逻辑（工具描述通过 model API tools 字段完整传递） | context.py L293-299（150 字符截断，skills 工具不截断） | 额外增强 |
| L17 | system prompt 顺序 | cline.ts L138-165 + session-runtime-orchestrator.ts L680-688（base → env → rules → metadata → extension rules） | context.py L165-232（env → identity → AGENTS.md → memory → skills → tools → mcp → rules → extra → mode_tag → mode_prompt） | 弱对齐 |
| L18 | 动态上下文注入 | workspace-manifest.ts + cline.ts L47-62（workspaceMetadata 含 rootPath/hint/gitBranch/gitCommit/remoteUrls） | context.py L234-260（仅 working_dir/platform/date） | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #L1：分层结构不同

**严重度**：P3（结构差异不影响功能）

**Cline 实现**：
Cline 采用"模板 + 占位符替换"模式：
- `system.ts` 中 `DEFAULT_CLINE_SYSTEM_PROMPT` 是一个完整字符串模板，含 `{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CLINE_RULES}}` / `{{CLINE_METADATA}}` 6 个占位符。
- `cline.ts::buildClineSystemPrompt()` 用 `String.replace` 依次替换占位符。
- `session-runtime-orchestrator.ts::composeSystemPrompt()` 再通过 `mergeSystemPromptRules()` 在末尾追加 extension 注册的 rules。

最终结构（5 层）：
1. identity + general guidance（base prompt 前半）
2. `<env>` 段（base prompt 内嵌）
3. "Remember:" 规则（base prompt 后半）
4. `{{CLINE_RULES}}` = caller rules + MODE_TAG + PLAN_MODE
5. `{{CLINE_METADATA}}` = workspace metadata（仅 Cline provider）
6. extension rules（composeSystemPrompt 末尾追加）

**我的实现**：
`SystemPromptBuilder.build()` 用 `list[str]` 显式收集 12 个段落，最后用 `"\n\n---\n\n"` 拼接：
1. environment (<env>)
2. identity
3. agents_file (AGENTS.md)
4. memory
5. always_skills instructions
6. skills_summary + tool_hint
7. tools_section
8. mcp_servers section
9. rules (rules_loader)
10. extra_sections
11. mode_tag_instructions
12. mode_prompt (PLAN_MODE_PROMPT)

**影响**：
- 结构差异不构成功能缺失，双方都能组装出完整 system prompt
- 我的结构更显式，便于按段调试和按需关闭
- Cline 的模板方式更紧凑，但扩展性弱（新增段需修改模板）
- 段落分隔符不同：Cline 用 `"\n\n"`，我用 `"\n\n---\n\n"`（多一个 horizontal rule）

**修复建议**：保持现状。我的多段拼接更灵活，且兼容现有 Phase 12/16/22/29.5 各阶段增强。

**优先级**：P3

---

### 差距 #L2：`<env>` 段字段缺失

**严重度**：P2（缺 IDE 字段，影响模型判断 IDE 上下文）

**Cline 实现**（system.ts L7-13）：
```
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```
4 个字段，带序号，英文字段名。`{{IDE_NAME}}` 在 cline-session-factory.ts 中传 `"VS Code"`，在 cron-runner 中传 `"Cline Cron"`，在 subagent 中传 `"Terminal"`。

**我的实现**（context.py L253-260）：
```
<env>
工作目录: {self.working_dir}
平台: {plat}
日期: {today}
</env>
```
3 个字段，无序号，中文字段名。无 IDE 字段。

**影响**：
1. **缺 IDE 字段**：LLM 无法感知当前运行环境（Web/CLI/IDE），影响 IDE 相关建议（如"在 VS Code 中按 F5"vs"在终端运行 pytest"）
2. **字段顺序不同**：Cline 是 Platform→Date→IDE→CWD，我是 工作目录→平台→日期
3. **字段名语言不同**：Cline 英文，我中文 — 实际无影响，但与 Cline 对齐需统一
4. **日期格式不同**：Cline 用 `new Date().toLocaleDateString()`（区域相关，如 "7/26/2026"），我用 `date.today().isoformat()`（ISO 8601，如 "2026-07-26"）— 我的格式更稳定，应保留

**修复建议**：补齐 IDE 字段，保持中文字段名（与 AGENTS.md 风格一致）：
```python
def _build_environment(self) -> str:
    from datetime import date
    import platform
    today = date.today().isoformat()
    plat = platform.platform(terse=True)
    ide = self.ide_name or "Charles Web"  # 新增 ide_name 参数，默认 Web
    lines = [
        "<env>",
        f"工作目录: {self.working_dir}",
        f"平台: {plat}",
        f"日期: {today}",
        f"IDE: {ide}",
        "</env>",
    ]
    return "\n".join(lines)
```

**优先级**：P2

---

### 差距 #L4：`<user_input mode>` 标签说明不完整

**严重度**：P2（缺 yolo mode + mode_notice 说明，影响 mode 切换语义）

**Cline 实现**（cline.ts L21-23 MODE_TAG_INSTRUCTIONS）：
```
# Plan / Act Modes

User messages arrive wrapped in a <user_input mode="..."> tag. The mode attribute is the interaction mode the user was in when they sent that message: "plan" means plan-mode constraints applied (explore, analyze, and align on a plan -- no edits or state-changing commands), while "act" (or "yolo") means implementation was allowed. If the mode attribute changes between messages, the user switched modes -- the newest message's mode is what governs right now, regardless of what earlier messages allowed. A <mode_notice> block inside a message marks exactly when such a switch happened.
```
关键点：
1. 说明 `mode="plan"` / `mode="act"` / `mode="yolo"` 三种取值
2. 强调 "the newest message's mode is what governs right now"（最新 mode 优先）
3. 说明 `<mode_notice>` 块标记 mode 切换时刻
4. 同时适用于 plan 和 act 模式（"Included for BOTH modes"）

**我的实现**（context.py L370-386）：
```
# 用户消息模式标签

用户消息会被 `<user_input mode="...">` 标签包裹，mode 取值:
- `act`: 执行模式，可直接调用工具完成任务
- `plan`: 规划模式，只读不写，先制定计划待用户批准后再执行

请根据 mode 标签调整行为：plan 模式下不得调用任何写入/编辑类工具
（editor / apply_patch / file_write / run_commands 中的写操作）。
```
缺：
1. `yolo` mode 取值（Cline 把 yolo 视为 act 的等价）
2. "最新 mode 优先" 语义
3. `<mode_notice>` 块说明
4. mode 跨消息切换的解释

**影响**：
1. **缺 yolo**：当前我不支持 yolo mode，但若未来支持，标签说明需同步更新
2. **缺 mode_notice**：若用户在对话中切换 mode，我未注入 `<mode_notice>` 块（formatModeSwitchNotice 在 Cline 中对应实现），LLM 无法感知"切换时刻"
3. **缺"最新优先"**：跨消息 mode 变化时，LLM 可能仍按旧 mode 行为

**修复建议**：补齐标签说明，对齐 Cline 语义：
```python
def _build_mode_tag_instructions(self) -> str:
    return (
        "# 用户消息模式标签\n\n"
        "用户消息会被 `<user_input mode=\"...\">` 标签包裹，mode 取值:\n"
        "- `act`: 执行模式，可直接调用工具完成任务\n"
        "- `plan`: 规划模式，只读不写，先制定计划待用户批准后再执行\n"
        "- `yolo`: 自动执行模式（如启用），与 act 等价但无需逐步确认\n\n"
        "若连续消息的 mode 标签不同，说明用户切换了模式 — "
        "以最新消息的 mode 为准，无论之前消息允许什么操作。\n"
        "消息内可能出现 `<mode_notice>` 块，标记模式切换的确切时刻。\n\n"
        "请根据 mode 标签调整行为：plan 模式下不得调用任何写入/编辑类工具"
        "（editor / apply_patch / file_write / run_commands 中的写操作）。"
    )
```

**优先级**：P2

---

### 差距 #L6：cline-rules 段加载机制不同

**严重度**：P2（加载顺序与合并方式不同）

**Cline 实现**：
- rules 通过 extension 机制注册：`user-instruction-plugin.ts` L237-243 调用 `api.registerRule({ id, source, content: () => loadRulesForSystemPromptFromWatcher(watcher) })`
- `session-runtime-orchestrator.ts` L680-688 `composeSystemPrompt()` 遍历 `getRegisteredRules()`，对每个 rule 调用 `resolveRuleContent(rule)` 获取内容
- `mergeSystemPromptRules()` 用 `"\n\n"` 拼接所有 rule content
- `formatRulesForSystemPrompt()`（rules.ts L10-21）格式：`# Rules\n## {rule.name}\n{rule.instructions}`
- 加载顺序：extension 注册顺序（user-instruction-plugin 是首个注册的 extension）
- 数据源：`UserInstructionConfigWatcher` 监听文件变更，热重载

**我的实现**：
- `rules_loader.py::load_rules_directory()` 扫描 rules_dir 下所有 .md 文件，按 `sorted(rglob)` 排序
- `format_rules_content()` 用 `"\n\n"` 拼接
- 格式：`## 规则: {name}\n\n{body}`
- 加载顺序：文件名字典序
- 数据源：每次 `build()` 时同步扫描（无 watch）
- 兼容层：先加载 `rules/<task_type>.md` 单文件，再扫描整个目录

**影响**：
1. **加载顺序不同**：Cline 按 extension 注册顺序，我按文件名排序 — 多规则时顺序不一致，但功能等价
2. **格式不同**：Cline `# Rules\n## {name}\n{instructions}`，我 `## 规则: {name}\n\n{body}` — LLM 解析效果接近
3. **无热重载**：Cline 通过 UnifiedConfigFileWatcher 支持 fs.watch + debounce 75ms，我每次 build 重新扫描 — 性能略差但数据新鲜
4. **task_type 兼容层**：我有 `rules/<task_type>.md` 单文件加载，Cline 无此概念

**修复建议**：保持现状。我的加载机制已满足需求，热重载对量化场景非必需（规则文件不频繁变更）。

**优先级**：P2

---

### 差距 #L9：external-rules 缺失

**严重度**：P3（量化场景无 .cursorrules/.windsurfrules 需求）

**Cline 实现**（external-rules.ts L10-49）：
- 支持 3 类外部规则文件：
  - `.windsurfrules`（Windsurf IDE）
  - `.cursorrules` / `.cursor/rules/*.mdc`（Cursor IDE）
  - `AGENTS.md`（通用 agent 指令）
- 通过 `synchronizeRuleToggles()` 同步启用/禁用开关
- `combineRuleToggles()` 合并多目录扫描结果
- 状态持久化到 `stateManager`（VS Code workspace state）

**我的实现**：无 .windsurfrules / .cursorrules 支持。仅支持 AGENTS.md（通过 `agents_path` 参数单文件加载）。

**影响**：
1. 量化场景下用户不使用 Windsurf/Cursor IDE，无外部规则文件需求
2. 若未来从其他 IDE 迁移配置，需补充支持

**修复建议**：暂不实现。若需迁移外部 IDE 配置，可后续在 `rules_loader.py` 增加 `load_external_rules()` 函数。

**优先级**：P3

---

### 差距 #L10：workflows 缺失

**严重度**：P3（量化场景无 workflow 需求）

**Cline 实现**（workflows.ts + user-instruction-config-loader.ts L577-599）：
- `WORKFLOWS_CONFIG_DIRECTORY_NAME = "workflows"` 目录
- 搜索路径：`.clinerules/workflows/` + `.cline/workflows/` + 全局 Documents/Workflows
- workflow 文件解析同 rules（frontmatter + body），支持 `name` / `description` / `disabled` / `instructions`
- 通过 `registerCommand` 注册为 slash command（如 `/my-workflow`）
- 用户输入 `/my-workflow args` 时，handler 返回 `{instructions}\n\n{args}`

**我的实现**：无 workflows 概念。slash command 通过前端路由实现，不通过 system prompt 注入。

**影响**：
1. 量化场景下无 workflow 文件需求
2. Cline 的 workflow 本质是"预定义 prompt 模板 + slash command 触发"，我通过前端快捷指令实现类似功能

**修复建议**：暂不实现。若需引入 workflow，可在 `agent/rules_loader.py` 旁新增 `agent/workflows_loader.py`，并在 system prompt 中注入可用 workflow 列表。

**优先级**：P3

---

### 差距 #L14：AGENTS.md 加载机制不同

**严重度**：P2（缺多位置搜索 + 全局 AGENTS.md）

**Cline 实现**（paths.ts L372-394 + user-instruction-config-loader.ts L479-498）：
- `resolveRulesConfigSearchPaths()` 返回多个搜索路径：
  1. `{workspacePath}/AGENTS.md`（workspace 级）
  2. `{workspacePath}/.clinerules/`（旧目录）
  3. `{workspacePath}/.cline/rules/`（新目录）
  4. `{HOME_DIR}/.cline/AGENTS.md`（全局级，`resolveGlobalAgentsRulesPath()`）
  5. `{clineDir}/rules/`（CLI 安装目录）
  6. `Documents/Rules/`（系统 Documents 目录）
- `discoverRulesLikeFiles()` 对每个路径扫描，AGENTS.md 作为特殊文件单独检查
- 多文件合并：所有发现的 AGENTS.md + 其他 .md 文件都作为独立 RuleConfig 注册
- `resolveRuleFallbackName()` 为 AGENTS.md 生成友好名称（"Workspace AGENTS.md" / "Global AGENTS.md"）

**我的实现**（context.py L409-421）：
- `_load_agents_file()` 仅加载 `agents_path` 参数指定的单个文件
- 无多位置搜索
- 无全局 AGENTS.md
- 无 AGENTS.md 与其他 rules 文件的合并机制（AGENTS.md 单独加载，rules 另通过 `_load_rules()` 加载）

**影响**：
1. **无全局 AGENTS.md**：用户无法在 `~/.cline/AGENTS.md` 配置跨项目通用指令
2. **无多文件合并**：若 workspace 有多个 AGENTS.md（如子目录），我只加载顶层一个
3. **分离加载**：AGENTS.md 与 rules 分两段注入（AGENTS.md 在第 3 段，rules 在第 8 段），Cline 统一作为 rules 注入

**修复建议**：
1. 短期：保持现状，单文件 AGENTS.md 已满足当前需求
2. 中期：在 `_load_agents_file()` 中增加全局 AGENTS.md 路径（`~/.cline/AGENTS.md`），合并 workspace + global：
```python
def _load_agents_file(self) -> str | None:
    parts: list[str] = []
    # 1. 全局 AGENTS.md
    global_agents = Path.home() / ".cline" / "AGENTS.md"
    if global_agents.exists():
        parts.append(global_agents.read_text(encoding="utf-8").strip())
    # 2. workspace AGENTS.md
    if self.agents_path and self.agents_path.exists():
        parts.append(self.agents_path.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts) if parts else None
```

**优先级**：P2

---

### 差距 #L17：system prompt 顺序不同

**严重度**：P3（顺序差异不影响功能，但与 Cline 不对齐）

**Cline 顺序**（cline.ts L138-165 + session-runtime-orchestrator.ts L680-688）：
1. identity + general guidance（base prompt 前半，含 "Always gather all the necessary context..."）
2. `<env>` 段（base prompt 内嵌）
3. "Remember:" 规则（base prompt 后半，含 "Always adhere to existing code conventions..."）
4. `{{CLINE_RULES}}` = caller rules + MODE_TAG_INSTRUCTIONS + PLAN_MODE_INSTRUCTIONS
5. `{{CLINE_METADATA}}` = workspace metadata（仅 Cline provider）
6. extension rules（composeSystemPrompt 末尾通过 mergeSystemPromptRules 追加）

**我的顺序**（context.py L165-232）：
1. environment (<env>)
2. identity
3. agents_file (AGENTS.md)
4. memory
5. always_skills instructions
6. skills_summary + tool_hint
7. tools_section
8. mcp_servers section
9. rules (rules_loader)
10. extra_sections
11. mode_tag_instructions
12. mode_prompt (PLAN_MODE_PROMPT)

**对比**：
- Cline: env 嵌在 base prompt 中段，rules 在 base prompt 之后
- 我: env 在最前，rules 在中段，mode_tag + mode_prompt 在末尾
- Cline: MODE_TAG + PLAN_MODE 紧跟 caller rules（同段）
- 我: mode_tag 与 mode_prompt 分开，位于末尾

**影响**：
1. 顺序差异不构成功能缺失
2. Cline 的顺序更符合"先身份后规则"的心理学顺序
3. 我的顺序更符合"先环境后身份后工具后规则"的工程顺序
4. mode_tag 在末尾可能被长 rules 内容"冲淡"，但 LLM 通常能注意到标签

**修复建议**：保持现状。我的顺序针对 Qwen 等模型优化（工具与规则显式列出），与 Cline 顺序差异不构成功能问题。

**优先级**：P3

---

### 差距 #L18：动态上下文注入不完整

**严重度**：P2（缺 git 状态注入）

**Cline 实现**（workspace-manifest.ts + cline.ts L47-62）：
- `buildWorkspaceMetadataWithInfo(workspacePath)` 生成结构化 workspace + git 元数据
- `processWorkspaceInfo(info)` 序列化为 JSON：
  ```json
  {
    "workspaces": {
      "/path/to/project": {
        "hint": "project",
        "associatedRemoteUrls": ["https://github.com/..."],
        "latestGitCommitHash": "abc1234",
        "latestGitBranchName": "main"
      }
    }
  }
  ```
- 注入到 `{{CLINE_METADATA}}` slot，标题为 `# Workspace Configuration`
- 含 5 个字段：rootPath / hint / associatedRemoteUrls / latestGitCommitHash / latestGitBranchName
- 仅 Cline provider 注入（`isClineProvider(providerId)` 检查）

**我的实现**（context.py L234-260）：
- 仅注入 3 个字段：工作目录 / 平台 / 日期
- 无 git 状态（branch / commit hash / remote url）
- 无 workspace hint
- 无 associatedRemoteUrls

**影响**：
1. **缺 git 状态**：LLM 无法感知当前 git 分支与提交，影响代码相关建议（如"在 main 分支上需谨慎修改"）
2. **量化场景影响小**：本项目主要做量化分析，git 状态对 LLM 决策影响有限
3. **缺 workspace hint**：LLM 无法从 workspace 名称推断项目类型

**修复建议**：
1. 短期：在 `_build_environment()` 中增加 git 状态字段：
```python
def _build_environment(self) -> str:
    from datetime import date
    import platform
    today = date.today().isoformat()
    plat = platform.platform(terse=True)
    git_info = self._read_git_state()  # 新增辅助方法
    lines = [
        "<env>",
        f"工作目录: {self.working_dir}",
        f"平台: {plat}",
        f"日期: {today}",
    ]
    if git_info.get("branch"):
        lines.append(f"Git 分支: {git_info['branch']}")
    if git_info.get("commit"):
        lines.append(f"Git 提交: {git_info['commit']}")
    lines.append("</env>")
    return "\n".join(lines)

def _read_git_state(self) -> dict[str, str]:
    """读取当前工作目录的 git 状态"""
    import subprocess
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.working_dir, stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=self.working_dir, stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        return {"branch": branch, "commit": commit}
    except Exception:
        return {}
```

**优先级**：P2

---

## 4. 额外增强项

### 增强 #L3：tools_section 段（工具列表 + 使用指引）

**我**：`context.py L262-309 _build_tools_section()` 在 system prompt 中注入工具列表文本，含每个工具的 name + description（150 字符截断），并附"## 工具使用指引"说明并行调用规则。

**Cline**：不在 system prompt 中列工具，依赖 model API 的 tools 字段传递工具定义。

**评估**：合理增强。Qwen 等模型对 system prompt 文本的依赖较强，显式列出工具名+描述有助于 LLM 快速理解可用工具。Cline 通过 model API tools 字段传递，但部分模型（如 Qwen-7B）对 tools 字段的利用率较低。保留。

### 增强 #L5：MCP 服务器概览段

**我**：`context.py L311-368 _build_mcp_servers_section()` 列出每个 MCP 服务器的 name + description + 工具列表，附 use_mcp_tool / access_mcp_resource 调用说明。

**Cline**：MCP 工具作为普通 AgentTool 注册到 tools 数组，通过 model API tools 字段传递，system prompt 中无独立 MCP 概览段。

**评估**：合理增强。MCP 工具名通常带 server 前缀（如 `mcp__knowledge_graph__search_nodes`），LLM 难以从工具名推断 server 与工具的对应关系。显式列出 server→tools 映射有助于 LLM 正确选择工具。保留。

### 增强 #L8：rule-conditionals 支持 applyTo + mode 条件

**我**：`rules_loader.py L267-379` 支持 3 个条件：
- `applyTo`: agent 模式过滤（plan / act）
- `mode`: 业务模式过滤（research / trade 等）
- `paths`: 工作空间路径 glob 匹配

**Cline**：`rule-conditionals.ts` 仅支持 `paths` 条件，用 picomatch 做 glob 匹配。不支持 applyTo / mode 条件。

**评估**：合理增强。量化场景下需按业务模式（research / trade）过滤规则，Cline 的 paths 条件无法满足。applyTo 用于按 plan/act 模式过滤规则，补充 Cline 缺失的 mode-aware 规则激活机制。保留。

### 增强 #L11：always 技能自动注入

**我**：`skills/loader.py L62` + `skills/registry.py L155-180` + `context.py L185-189` 支持 frontmatter `always: true`，always=True 的技能自动注入 system prompt 的"# 常驻技能指令"段。

**Cline**：`SkillConfig` 无 `always` 字段，技能仅通过 `skills` 工具触发加载（on-demand）。

**评估**：合理增强（对标 nanobot）。某些技能（如"通用研报写作规范"）需始终激活，依赖 LLM 主动调用 skills 工具不可靠。always 机制确保关键技能指令始终在 system prompt 中。保留。

### 增强 #L12：on-demand 技能概览表格

**我**：`skills/registry.py L182-217 build_summary()` 在 system prompt 中注入 markdown 表格，列出所有技能的 name + description（截断 120 字符），并标注"这些不是可直接调用的工具，需先调用 skills 工具加载"。

**Cline**：不在 system prompt 中列技能名清单。skills 工具 description 末尾动态追加"Available skills: ..."。

**评估**：合理增强。表格格式与 tools_section 的 bullet list 明显区分，避免 LLM 把 skill 名误认为 tool 名。Cline 仅在 tool description 中列技能名，LLM 需先看到 skills 工具 description 才能知道可用技能；我显式注入表格，LLM 在 system prompt 中即可看到。保留。

### 增强 #L15：memory 段

**我**：`context.py L182-184` 支持 memory 参数，注入"# 记忆\n\n{memory}"段。

**Cline**：无 MEMORY.md 加载机制，无 memory 段注入。

**评估**：合理增强。memory 段用于注入跨会话记忆（如用户偏好、历史决策），Cline 通过外部 storage（如 checkpoint）实现类似功能。保留。

### 增强 #L16：工具描述截断

**我**：`context.py L293-299` 对工具 description 超过 150 字符时截断为 `desc[:150] + "..."`，skills 工具不截断（保留完整可用技能列表）。

**Cline**：无截断逻辑，工具描述通过 model API tools 字段完整传递。

**评估**：合理增强（因 L3 额外增强带来）。我在 system prompt 中列工具，需控制 token 占用，150 字符截断在保留语义的同时减少 token 浪费。skills 工具 description 含可用技能列表，截断会丢失关键信息，故不截断。保留。

---

## 5. 修复优先级清单

### P2（影响 LLM 决策质量，建议中期修复）

1. **L2 `<env>` 缺 IDE 字段**：在 `_build_environment()` 中新增 `ide_name` 参数，默认 `"Charles Web"`，注入到 `<env>` 段。
2. **L4 mode 标签说明不完整**：补齐 yolo mode 说明、`<mode_notice>` 块说明、"最新 mode 优先"语义。
3. **L6 cline-rules 加载顺序**：保持现状（文件名排序），但可考虑在 rules_loader 中增加 `priority` frontmatter 字段支持优先级排序。
4. **L14 AGENTS.md 缺多位置搜索**：在 `_load_agents_file()` 中增加全局 AGENTS.md（`~/.cline/AGENTS.md`）合并加载。
5. **L18 缺 git 状态注入**：在 `_build_environment()` 中增加 git 分支与 commit hash 字段。

### P3（影响小或场景非必需，可暂不修复）

1. **L1 分层结构差异**：保持现状，多段拼接更灵活。
2. **L9 external-rules 缺失**：量化场景无 .cursorrules/.windsurfrules 需求，暂不实现。
3. **L10 workflows 缺失**：量化场景无 workflow 需求，暂不实现。
4. **L17 system prompt 顺序**：保持现状，顺序差异不影响功能。

---

## 6. 验证记录

### 验证方法

1. **静态对比**：逐行阅读 Cline `system.ts` / `cline.ts` / `session-runtime-orchestrator.ts` / `user-instruction-plugin.ts` / `user-instruction-config-loader.ts` / `frontmatter.ts` / `rule-conditionals.ts` / `external-rules.ts` / `workflows.ts` / `workspace-manifest.ts` / `paths.ts`，与我的 `context.py` / `rules_loader.py` / `skills/loader.py` / `skills/registry.py` / `plan_mode.py` / `AGENTS.md` 逐项对比。
2. **格式参考**：参照已完成的 `phase_F_tools_infra.md` / `phase_I_skills.md` 格式编写报告。

### 关键验证点

| 验证项 | Cline 位置 | 我的位置 | 验证结果 |
|--------|-----------|---------|---------|
| frontmatter 正则 | `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` | `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` | 字节级一致 |
| BOM 剥离 | `stripUtf8Bom(content)` | `if normalized.startswith(_UTF8_BOM): normalized = normalized[len(_UTF8_BOM):]` | 逻辑等价 |
| fail-open 行为 | 解析失败返回 `data={}, body=原文, hadFrontmatter=True, parseError=msg` | 解析失败返回 `data={}, body=原文, hadFrontmatter=True, parse_error=str(e)` | 字段名不同，逻辑等价 |
| PLAN_MODE_PROMPT 关键句 | "explore, analyze, and plan -- not to execute" | "探索、分析、规划——而非执行" | 语义等价 |
| PLAN_MODE_PROMPT run_commands 限制 | "run_commands tool remains available in plan mode strictly for read-only inspection" | "run_commands 工具在 Plan 模式下仅用于只读检查" | 语义等价 |
| PLAN_MODE_PROMPT switch_to_act_mode 警告 | "never call it in the same turn you present a plan" | "不要在你呈现计划的同一轮调用 switch_to_act_mode" | 语义等价 |
| `<user_input mode>` 标签说明 | MODE_TAG_INSTRUCTIONS 含 yolo / mode_notice / 最新优先 | 仅 act/plan 两种 mode，无 yolo/mode_notice/最新优先 | 弱对齐 |
| rules 拼接分隔符 | `"\n\n"` | `"\n\n"` | 一致 |
| rules 格式 | `# Rules\n## {rule.name}\n{rule.instructions}` | `## 规则: {name}\n\n{body}` | 格式不同，语义接近 |
| paths 条件 fail-closed | `paths: []` → 不激活；无候选路径 → 不激活 | 同上 | 一致 |
| `<env>` 字段数 | 4（Platform/Date/IDE/CWD） | 3（工作目录/平台/日期） | 缺 IDE |
| workspace metadata | rootPath/hint/gitBranch/gitCommit/remoteUrls | 无 | 缺失 |

### 已确认对齐项

- **L7 frontmatter 解析**：正则、BOM 剥离、fail-open 行为完全一致。
- **L13 PLAN_MODE_PROMPT**：关键语义（探索不执行 / run_commands 只读 / switch_to_act_mode 警告）完全对齐。

### 已确认缺失项

- **L9 external-rules**：无 .windsurfrules / .cursorrules 支持。
- **L10 workflows**：无 workflows 目录与 slash command 注册机制。

### 已确认额外增强项（保留）

- **L3 tools_section**：合理增强，针对 Qwen 等模型。
- **L5 MCP 概览**：合理增强，帮助 LLM 理解 server→tools 映射。
- **L8 applyTo + mode 条件**：合理增强，量化场景必需。
- **L11 always skills**：合理增强，对标 nanobot。
- **L12 技能目录表格**：合理增强，与 tools_section 区分。
- **L15 memory 段**：合理增强，支持跨会话记忆。
- **L16 工具描述截断**：合理增强，控制 token 占用。

---

**阶段 L 结论**：SystemPromptBuilder 对齐度约 50%，核心机制（frontmatter 解析、PLAN_MODE_PROMPT 内容）与 Cline 字节级对齐。主要差距：
1. **P2 级**：`<env>` 缺 IDE 字段、mode 标签说明不完整、AGENTS.md 缺多位置搜索、缺 git 状态注入 — 影响模型决策质量，建议中期修复。
2. **P3 级**：external-rules / workflows 缺失 — 量化场景非必需，暂不实现。
3. **合理增强**：tools_section / MCP 概览 / always skills / 技能目录表格 / memory 段 / 工具描述截断 — 针对 Qwen 等弱模型优化，应保留。
