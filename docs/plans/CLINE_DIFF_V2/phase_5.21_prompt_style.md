# Phase 5.21 System Prompt 形式风格对比（标签/措辞）

> 对比范围：Cline `sdk/packages/shared/src/prompt/system.ts`（DEFAULT/YOLO base prompt 模板）+ `cline.ts`（MODE_TAG/PLAN_MODE 指令 + buildClineSystemPrompt 占位符替换）+ `format.ts`（`<user_input>` / `<mode_notice>` 标签生成）+ `runtime/safety/rules.ts`（`formatRulesForSystemPrompt` 规则段格式）+ `extensions/context/basic-compaction.ts`（`<SYSTEM_NOTICE>` 块格式） 与 Charles `agent/prompts/charles_system_prompt.py`（DEFAULT/YOLO base prompt 模板）+ `agent/context.py`（`_build_mode_tag_instructions` / `_build_environment` / `_build_metadata` / `_build_tools_section` / `_build_mcp_servers_section` 等段构建方法）+ `agent/state.py`（`<mode_notice>` 生成）+ `agent/rules_loader.py`（`format_rules_content` 规则段格式）的 XML 标签使用、措辞风格（命令式 vs 描述式）、人称、语气、格式约定差异；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（`DEFAULT_CLINE_SYSTEM_PROMPT` + `YOLO_CLINE_SYSTEM_PROMPT` base 模板，含 `<env>` 块 + `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 占位符）
> - `sdk/packages/shared/src/prompt/cline.ts` L21-45（`MODE_TAG_INSTRUCTIONS` + `PLAN_MODE_INSTRUCTIONS` 指令文本）+ L9（`WORKSPACE_CONFIGURATION_MARKER = "# Workspace Configuration"`）
> - `sdk/packages/shared/src/prompt/format.ts` L5-46（`formatUserInputBlock` 生成 `<user_input mode="...">` + `formatModeSwitchNotice` 生成 `<mode_notice>`）
> - `sdk/packages/core/src/runtime/safety/rules.ts` L10-21（`formatRulesForSystemPrompt` 生成 `# Rules` + `## ${rule.name}` 格式）
> - `sdk/packages/core/src/extensions/context/basic-compaction.ts` L80-92（`buildDroppedWorkSummaryBlock` 生成 `<SYSTEM_NOTICE>` 块）
>
> Charles 源码：
> - `agent/prompts/charles_system_prompt.py` L1-94（`DEFAULT_CHARLES_SYSTEM_PROMPT` + `YOLO_CHARLES_SYSTEM_PROMPT` base 模板，含 `<env>` 块 + `{{CHARLES_RULES}}` + `{{CHARLES_METADATA}}` 占位符）
> - `agent/context.py` L408-452（`_build_metadata` 生成 `# Workspace Configuration` 标记）+ L649-681（`_build_environment` 保留方法，含中文字段名）+ L723-786（`_build_tools_section` 中文工具段）+ L788-834（`_build_mcp_servers_section` 中文 MCP 段）+ L836-856（`_build_mode_tag_instructions` 中文 mode 标签说明）
> - `agent/state.py` L466-484（`format_mode_switch_notice` 生成 `<mode_notice>` 文本）
> - `agent/rules_loader.py` L686-722（`format_rules_content` 生成 `# Rules` + `## ${name}` 格式）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 形式风格（XML 标签、措辞、人称、语气、格式约定）。**核心结论：XML 标签体系已完全对齐（`<env>` / `<user_input mode="...">` / `<mode_notice>` / `<SYSTEM_NOTICE>` 四类标签语义和文本格式一致）；剩余差异集中在措辞语言（Cline 英文 vs Charles 中文）和增强段落命名语言（Charles 工具/MCP 段用中文标题，Cline 无对应概念）**，这些差异属业务本地化设计，非对齐缺口。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.21（L2182-2206）对 Charles 风格的描述存在三处事实错误：

1. **L2192 "文本块: 无"**：错误。Charles base prompt 实际含 `## 通用行为规则` + `## 工具调用规则` 两个 markdown 文本块标题（charles_system_prompt.py L33-43），与 Cline 的隐式段落（无 `##` 标题，仅用 bullet list）形式不同。
2. **L2193 "字段名: 中文（部分）"**：错误。Charles base prompt 模板内的 `<env>` 块字段名全部为英文（`Platform` / `Date` / `IDE` / `Working Directory`，charles_system_prompt.py L49-54），与 Cline 完全一致。仅 `context.py` L649-681 的 `_build_environment` 保留方法用中文字段名（`工作目录` / `平台` / `日期` / `IDE`），但该方法**不在 `build()` 主路径中调用**，仅用于测试/外部兼容。
3. **L2199 "Charles `<charles_metadata>`"**：错误。Charles 已在 L5 阶段对齐 Cline 的 `# Workspace Configuration` 文本标记（context.py L448-452），不再使用 `<charles_metadata>` XML 标签。`<charles_metadata>` 仅作为占位符命名 `{{CHARLES_METADATA}}` 保留（curly braces，非 angle brackets），实际生成的 metadata 块格式与 Cline 完全一致。`context.py` L424 docstring 明确说明"不再使用 `<charles_metadata>` XML 标签"。

### 核心结论

1. **XML 标签体系完全对齐**：`<env>` / `<user_input mode="...">` / `<mode_notice>` / `<SYSTEM_NOTICE>` 四类标签在 Cline 和 Charles 中语义一致、文本格式一致。Charles `<user_input>` 在标签与内容间多 `\n`（server.py L605），属细微排版差异，不影响语义。
2. **metadata 块格式已对齐**（L5 阶段完成）：两者均用 `# Workspace Configuration` 文本标记 + JSON 体，不再使用 XML 标签。
3. **rules 段格式已对齐**：两者均用 `# Rules` 顶级标题 + `## ${name}` 子标题 + body 格式。
4. **措辞语言差异属本地化设计**：Cline 全英文，Charles base prompt 中文 + 增强段中文。但 `mode_notice` 文本（state.py L483-484）和 `<SYSTEM_NOTICE>` 块文本（context.py L2330-2333）Charles 用英文，与 Cline 完全一致——这些是嵌入用户消息的运行时标签，跨语言保持一致便于模型解析。
5. **人称对齐**：两者均用第二人称（Cline "You are Cline" / Charles "你是 Charles"）。
6. **语气对齐**：两者均用命令式（Cline "Always gather..." / Charles "在调用工具前先评估..."）。
7. **格式约定差异**：Charles base prompt 用 `## markdown 标题` 显式分段 + `**bold**` 强调 + 编号列表 `1. **项**: 描述`；Cline base prompt 用隐式段落（无 `##` 标题）+ 大写 `IMPORTANT`/`REMEMBER` 强调 + `-` bullet 列表。两者均用 markdown，但排版风格不同。
8. **nanobot 残留**：**1 处注释残留**（context.py L275 docstring，与 P5.1 同一处），**0 处实现逻辑残留**。System Prompt 风格层面无 nanobot 风格实现逻辑。

### 一致性总体评估

- **XML 标签**：**高**。四类标签完全对齐。
- **metadata/rules 块格式**：**高**。文本标记 + 标题层级一致。
- **人称/语气**：**高**。第二人称 + 命令式一致。
- **措辞语言**：**中**。Cline 英文 vs Charles 中文，属本地化设计。
- **格式约定**：**中**。均用 markdown，但分段方式和强调标记不同。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.21.1 | `<env>` 标签 | `<env>...</env>` 4 字段编号列表（system.ts L7-13） | `<env>...</env>` 4 字段编号列表（charles_system_prompt.py L49-54） | 高 | 标签格式完全一致；字段名全英文一致；字段顺序一致（Platform/Date/IDE/Working Directory） |
| 5.21.2 | `<user_input mode="...">` 标签 | `<user_input mode="${mode}">${input}</user_input>`（format.ts L9） | `<user_input mode="{mode}">\n{message}\n</user_input>`（server.py L605 / runtime.py L2835） | 高 | 标签语义一致；Charles 在标签与内容间多 `\n`，属排版差异 |
| 5.21.3 | `<mode_notice>` 标签 | `<mode_notice>The user switched from ${from} mode to ${to} mode before sending this message.</mode_notice>`（format.ts L45） | `<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>`（state.py L483-484） | 高 | 文本完全一致（英文），跨语言保持一致便于模型解析 |
| 5.21.4 | `<SYSTEM_NOTICE>` 标签 | `<SYSTEM_NOTICE>\nEarlier context was compacted...`（basic-compaction.ts L90） | `<SYSTEM_NOTICE>\nEarlier context was compacted...`（context.py L2330-2333） | 高 | 文本完全一致（英文），结构一致 |
| 5.21.5 | metadata 块标记 | `# Workspace Configuration\n{json}`（cline.ts L9 + L85） | `# Workspace Configuration\n{json}`（context.py L448-452） | 高 | L5 阶段已对齐。计划表标注"L5 差距"已失效 |
| 5.21.6 | rules 段格式 | `# Rules\n\n## ${rule.name}\n${rule.instructions}`（rules.ts L17-20） | `# Rules\n\n## ${name}\n\n{body}`（rules_loader.py L717-722） | 高 | 顶级标题 + 子标题层级一致；Charles 用文件 stem 作标题，Cline 用 rule.name |
| 5.21.7 | 占位符风格 | `{{PLATFORM_NAME}}` / `{{CLINE_RULES}}` / `{{CLINE_METADATA}}` 等双花括号（system.ts L9-36） | `{{PLATFORM_NAME}}` / `{{CHARLES_RULES}}` / `{{CHARLES_METADATA}}` 等双花括号（charles_system_prompt.py L49-57） | 高 | 风格一致；前缀不同（CLINE vs CHARLES），语义对齐 |
| 5.21.8 | 措辞语言 | 全英文（system.ts L1-36） | 中文 base prompt + 中文增强段（charles_system_prompt.py L31-58 + context.py L723-834） | 中 | 本地化设计差异，非对齐缺口。运行时标签（mode_notice/SYSTEM_NOTICE）保持英文一致 |
| 5.21.9 | 人称 | 第二人称 "You are Cline, an AI coding agent"（system.ts L1） | 第二人称 "你是 Charles，专业的 AI 投研情报官"（charles_system_prompt.py L31） | 高 | 均第二人称 |
| 5.21.10 | 语气 | 命令式 "Always gather..." / "Use only..." / "Provide complete..."（system.ts L2-24） | 命令式 "在调用工具前先评估..." / "必须先调用 todo_write..." / "使用绝对路径..."（charles_system_prompt.py L35-40） | 高 | 均命令式 |
| 5.21.11 | 段落标题风格 | 隐式段落（base prompt 无 `##` 标题，仅 bullet list）；rules 段用 `# Rules` + `## name`（rules.ts L18-20）；mode 段用 `# Plan / Act Modes`（cline.ts L21） | 显式段落（base prompt 含 `## 通用行为规则` + `## 工具调用规则`，charles_system_prompt.py L33-43）；rules 段用 `# Rules` + `## name`；mode 段用 `# 用户消息模式标签`（context.py L846） | 中 | rules 段层级一致；base prompt 分段方式不同（Cline 隐式 / Charles 显式 `##`）；mode 段标题语言不同 |
| 5.21.12 | 强调标记 | 大写 `IMPORTANT:` / `REMEMBER,` / `RULES:`（system.ts L28-42） | markdown `**bold**`（charles_system_prompt.py L35-40 `**上下文优先**` / `**任务拆解**`） | 中 | 均用强调，但方式不同（大写 vs bold） |
| 5.21.13 | 列表风格 | `-` bullet（system.ts L16-24）；rules 段 `## name\n${instructions}`（rules.ts L18） | base prompt 用编号 `1. **项**: 描述`（charles_system_prompt.py L35-40）；工具段用 `-` bullet（context.py L746） | 中 | Charles base prompt 用编号列表强调优先级，Cline 用 bullet 列表 |
| 5.21.14 | 字段名语言（`<env>` 块） | 全英文：`Platform` / `Date` / `IDE` / `Working Directory`（system.ts L9-12） | 全英文：`Platform` / `Date` / `IDE` / `Working Directory`（charles_system_prompt.py L50-53） | 高 | 完全一致。仅 `_build_environment` 保留方法用中文（context.py L664-670），但不在 build() 主路径 |
| 5.21.15 | 字段名语言（metadata JSON） | 英文键：`hint` / `associatedRemoteUrls` / `latestGitCommitHash` / `latestGitBranchName`（cline.ts L52-55） | 英文键：`hint` / `associatedRemoteUrls` / `latestGitCommitHash` / `latestGitBranchName`（context.py L434-440） | 高 | 完全一致 |
| 5.21.16 | 标签闭合 | 所有 XML 标签均显式闭合（`</env>` / `</user_input>` / `</mode_notice>` / `</SYSTEM_NOTICE>`） | 所有 XML 标签均显式闭合 | 高 | 一致 |
| 5.21.17 | 标签嵌套 | `<user_input>` 内可嵌 `<mode_notice>`（format.ts L18 注释说明 prepend 场景） | `<user_input>` 内可嵌 `<mode_notice>`（server.py L605 `notice_prefix` + `<user_input>` 拼接） | 高 | 一致 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.21 描述三处事实错误（5.21.5 / 5.21.11 / 5.21.14）

#### 3.1.1 "文本块: 无" 错误（L2192）

计划表 L2192 标注 Charles "文本块: 无"。实际 Charles base prompt 含两个显式 `##` markdown 标题：

```python
# charles_system_prompt.py L31-58
DEFAULT_CHARLES_SYSTEM_PROMPT = """你是 Charles，专业的 AI 投研情报官。...

## 通用行为规则

1. **上下文优先**：...
2. **任务拆解**：...
...

## 工具调用规则

- 一次回复中可调用多个相互独立的工具...
...

<env>
...
</env>

{{CHARLES_RULES}}
{{CHARLES_METADATA}}
"""
```

Cline base prompt 则**无 `##` 标题**，仅用 bullet list 隐式分段（system.ts L1-36）：

```typescript
// system.ts L1-36
export const DEFAULT_CLINE_SYSTEM_PROMPT = `You are Cline, an AI coding agent. ...

Always gather all the necessary context before starting to work on a task. ...

Review each question carefully and answer it with detailed, accurate information.
...

Remember:
- Always adhere to existing code conventions and patterns.
- Use only libraries and frameworks that are confirmed to be in use in the current codebase.
...

Environment you are running in:
<env>
...
</env>

{{CLINE_RULES}}
{{CLINE_METADATA}}`;
```

**差异**：Charles 用显式 `##` 标题分段（更结构化），Cline 用段落 + bullet list（更扁平）。两者均用 markdown，但排版风格不同。这是设计差异非对齐缺口——Charles 的量化业务场景需要更清晰的规则分区（通用行为 vs 工具调用）。

#### 3.1.2 "字段名: 中文（部分）" 错误（L2193）

计划表 L2193 标注 Charles "字段名: 中文（部分）"。实际 Charles base prompt 模板内的 `<env>` 块字段名**全部为英文**（charles_system_prompt.py L49-54），与 Cline 完全一致：

```python
# charles_system_prompt.py L49-54（base prompt 模板，build() 主路径使用）
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

```typescript
// system.ts L7-13（Cline base prompt 模板）
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

中文字段名仅出现在 `context.py` L649-681 的 `_build_environment` 保留方法中：

```python
# context.py L664-670（保留方法，不在 build() 主路径调用）
lines = [
    "<env>",
    f"工作目录: {self.working_dir}",
    f"平台: {plat}",
    f"日期: {today}",
    f"IDE: {self.ide_name}",
]
```

但该方法 docstring 明确说明"新 build() 中 `<env>` 段由 base prompt 模板直接构造，但本方法保留原输出格式（含 git 字段）以维持向后兼容"（context.py L649-653）。实际 `build()` 主路径（L348-391）调用 `build_charles_system_prompt` 纯组装器，使用 base prompt 模板的英文 `<env>` 块，**不调用 `_build_environment`**。

**结论**：Charles `<env>` 字段名与 Cline 完全一致（全英文），计划表标注错误。`_build_environment` 的中文字段名属历史保留代码，不影响实际 system prompt 输出。

#### 3.1.3 "Charles `<charles_metadata>`" 错误（L2199）

计划表 L2199 标注 Charles metadata 标签为 `<charles_metadata>`。实际 Charles 已在 L5 阶段对齐 Cline 的 `# Workspace Configuration` 文本标记（context.py L448-452），**不再使用 `<charles_metadata>` XML 标签**：

```python
# context.py L408-452（_build_metadata 方法，build() 主路径调用）
def _build_metadata(self) -> str:
    """构建工作空间元数据块 — 对标 Cline buildWorkspaceMetadata

    ...
    L5 对齐: 使用 Cline的 `# Workspace Configuration` 文本标记，
             不再使用 `<charles_metadata>` XML 标签。
    ...
    """
    ...
    # L5: 对齐 Cline WORKSPACE_CONFIGURATION_MARKER
    return (
        "# Workspace Configuration\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}"
    )
```

`<charles_metadata>` 仅在 context.py L424 的 docstring 中作为历史说明出现（"不再使用 `<charles_metadata>` XML 标签"），实际生成的 metadata 块格式与 Cline 完全一致：

```
# Workspace Configuration
{
  "workspaces": {
    "/path/to/workspace": {
      "hint": "workspace_name",
      "latestGitCommitHash": "abc1234",
      "latestGitBranchName": "main"
    }
  }
}
```

**结论**：Charles metadata 块格式已与 Cline 完全对齐（L5 阶段完成），计划表标注"L5 差距"已失效。`{{CHARLES_METADATA}}` 占位符命名保留 charles 前缀（与 `{{CLINE_METADATA}}` 对应），但占位符是双花括号 `{{}}`，非 XML 标签 `<charles_metadata>`。

### 3.2 措辞语言差异属本地化设计（5.21.8）

Cline base prompt 全英文，Charles base prompt 中文。这是 Charles 量化投研场景的本地化设计，非对齐缺口：

- **base prompt 身份定义**：Cline "You are Cline, an AI coding agent" / Charles "你是 Charles，专业的 AI 投研情报官"
- **base prompt 行为规则**：Cline "Always gather all the necessary context..." / Charles "在调用工具前先评估已掌握的上下文..."
- **mode 标签说明**：Cline `# Plan / Act Modes`（cline.ts L21）/ Charles `# 用户消息模式标签`（context.py L846）
- **工具段**：Cline 无对应概念（工具由 tool definitions 动态提供）/ Charles `# 工具` + `## 工具使用指引`（context.py L732-785，中文）
- **MCP 段**：Cline 无对应概念 / Charles `# MCP 服务器`（context.py L806，中文）

**关键观察**：运行时嵌入用户消息的标签（`<mode_notice>` / `<SYSTEM_NOTICE>`）Charles 用**英文**，与 Cline 完全一致。这是因为这些标签是跨语言的结构化标记，模型需跨会话一致解析，保持英文避免本地化导致的解析歧义。

| 段落类型 | Cline 语言 | Charles 语言 | 一致性 |
|---------|----------|------------|-------|
| base prompt 身份/规则 | 英文 | 中文 | 本地化差异 |
| `<env>` 块字段名 | 英文 | 英文 | 一致 |
| `<mode_notice>` 文本 | 英文 | 英文 | 一致 |
| `<SYSTEM_NOTICE>` 文本 | 英文 | 英文 | 一致 |
| metadata JSON 键名 | 英文 | 英文 | 一致 |
| rules 段标题（`# Rules`） | 英文 | 英文 | 一致 |
| mode 标签说明段标题 | 英文（`# Plan / Act Modes`） | 中文（`# 用户消息模式标签`） | 本地化差异 |
| 工具/MCP 概览段标题 | 无对应概念 | 中文 | Charles 独有增强 |

### 3.3 格式约定差异（5.21.11 / 5.21.12 / 5.21.13）

#### 3.3.1 段落标题风格

- **Cline**：base prompt 用隐式段落（无 `##` 标题，段落间用空行分隔，bullet list 项用 `-`）；动态段（rules / mode_tag / plan_mode）用 `#` 顶级标题（`# Rules` / `# Plan / Act Modes` / `# Plan Mode`）
- **Charles**：base prompt 用显式 `##` 标题分段（`## 通用行为规则` / `## 工具调用规则`）；动态段用 `#` 顶级标题（`# Rules` / `# 用户消息模式标签`）

**差异**：Charles base prompt 的 `##` 分段更结构化，Cline base prompt 更扁平。两者动态段均用 `#` 顶级标题，层级一致。

#### 3.3.2 强调标记

- **Cline**：用大写关键词强调（`IMPORTANT:` / `REMEMBER,` / `RULES:`，system.ts L28-42）
- **Charles**：用 markdown `**bold**` 强调（`**上下文优先**` / `**任务拆解**` / `**技能触发**`，charles_system_prompt.py L35-40）

两者均用强调，但方式不同。Charles 的 `**bold**` 更符合 markdown 规范，Cline 的大写更醒目。

#### 3.3.3 列表风格

- **Cline**：base prompt 行为规则用 `-` bullet（system.ts L16-24）
- **Charles**：base prompt 行为规则用编号列表 `1. **项**: 描述`（charles_system_prompt.py L35-40）

Charles 用编号列表强调规则的优先级顺序，Cline 用 bullet 列表无序排列。这是设计差异——Charles 量化场景需要明确的规则优先级（上下文优先 > 任务拆解 > 技能触发 > 工具选择 > 绝对路径 > 结果导向）。

### 3.4 `<user_input>` 标签排版细微差异（5.21.2）

Cline `formatUserInputBlock`（format.ts L9）生成的标签**紧贴内容**：

```typescript
return `<user_input mode="${mode}">${input}</user_input>`;
```

Charles `server.py` L605 生成的标签**在标签与内容间加 `\n`**：

```python
wrapped_message = f'{notice_prefix}<user_input mode="{current_mode}">\n{message}\n</user_input>'
```

**影响**：语义一致，但 Charles 的 `\n` 使多行用户输入更易读。属细微排版差异，不影响模型解析。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 System Prompt 形式风格相关文件检查 nanobot 风格残留：
- `agent/context.py`（SystemPromptBuilder + 段构建方法）
- `agent/prompts/charles_system_prompt.py`（base prompt 模板）
- `agent/state.py`（`<mode_notice>` 生成）
- `agent/rules_loader.py`（`format_rules_content` 规则段格式）
- `agent/server.py` / `agent/runtime.py`（`<user_input>` 标签生成）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`（与 P5.1 同一处） |
| `agent/prompts/charles_system_prompt.py` | 0 | 0 | 无残留 |
| `agent/state.py` | 0 | 0 | 无残留 |
| `agent/rules_loader.py` | 0 | 0 | 无残留 |
| `agent/server.py` | 多处注释 | 0 | L2/L4/L28 docstring 提及 nanobot（"对标 Cline server + nanobot routes/chat.py"），属对标说明非残留 |
| `agent/runtime.py` | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（1 处，与 P5.1 同一处）

**位置**：`agent/context.py` L275

```python
def __init__(
    self,
    identity: str = "",
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

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格的"额外段落"概念）和当前状态（已废弃、无调用方）。不影响运行逻辑。与 P5.1 阶段发现的同一处残留，未重复计数。

#### 4.3.2 实现逻辑残留（0 处）

经核查 System Prompt 风格相关全部方法：

- `build_charles_system_prompt`（context.py L78-127）：占位符替换，**无 nanobot 风格实现逻辑**
- `SystemPromptBuilder.build` / `_build_rules` / `_build_metadata` / `_build_enhancement_rules`：**无 nanobot 风格实现逻辑**
- `_build_environment`（context.py L649-681）：保留方法，含中文字段名，但**不在 build() 主路径调用**，属历史保留代码，非 nanobot 残留
- `_build_tools_section` / `_build_mcp_servers_section` / `_build_mode_tag_instructions`：Charles 独有增强段，**无 nanobot 风格实现逻辑**
- `format_rules_content`（rules_loader.py L686-722）：`# Rules` + `## name` 格式对齐 Cline，**无 nanobot 风格实现逻辑**
- `format_mode_switch_notice`（state.py L466-484）：`<mode_notice>` 文本与 Cline 完全一致，**无 nanobot 风格实现逻辑**

**结论**：System Prompt 形式风格层面**无实现逻辑残留**。`extra_sections` 死参数属"死代码"，非 nanobot 风格实现逻辑（其遍历逻辑在 `_build_rules` L530-537，但因默认空 dict 永不执行）。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**System Prompt 形式风格层面无类似的实现逻辑残留**，仅 1 处注释残留（与 P5.1 同一处）。这说明 L5 阶段的重构已彻底清除 System Prompt 风格的 nanobot 风格实现逻辑，XML 标签体系、措辞、格式约定均已对齐 Cline 模式。

### 4.5 注释残留 vs 实现逻辑残留区分

| 残留类型 | 数量 | 性质 | 影响 |
|---------|-----|------|------|
| 注释残留 | 1 处（context.py L275） | docstring 说明 `extra_sections` 历史来源 | 无运行逻辑影响 |
| 实现逻辑残留 | 0 处 | — | — |
| 死代码 | 1 处（context.py L530-537 `_build_rules` 中 `extra_sections` 遍历） | 因默认空 dict 永不执行 | 无实际效果 |

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.21.1 `<env>` 标签**：已对齐，无需修复。
- **5.21.2 `<user_input mode="...">` 标签**：已对齐，`\n` 排版差异属合理偏离，无需修复。
- **5.21.3 `<mode_notice>` 标签**：已对齐，文本完全一致。
- **5.21.4 `<SYSTEM_NOTICE>` 标签**：已对齐，文本完全一致。
- **5.21.5 metadata 块标记**：L5 阶段已对齐，无需修复。
- **5.21.6 rules 段格式**：已对齐。
- **5.21.7 占位符风格**：已对齐。
- **5.21.9 人称**：已对齐。
- **5.21.10 语气**：已对齐。
- **5.21.14 `<env>` 字段名语言**：已对齐。
- **5.21.15 metadata JSON 键名**：已对齐。
- **5.21.16 标签闭合**：已对齐。
- **5.21.17 标签嵌套**：已对齐。

### 5.2 优先级 P1（建议处理）

- **5.21.8 措辞语言**：无需修复，本地化设计差异。Charles 量化投研场景面向中文用户，base prompt 中文措辞属合理本地化。运行时标签（mode_notice/SYSTEM_NOTICE）保持英文一致已正确处理。

- **5.21.11 段落标题风格**：无需修复，设计差异。Charles base prompt 用 `##` 显式分段更结构化，适合量化场景的多规则分区；Cline base prompt 扁平化设计适合通用编码场景。

- **5.21.12 强调标记**：无需修复，设计差异。Charles `**bold**` 符合 markdown 规范，Cline 大写更醒目，两者均有效。

- **5.21.13 列表风格**：无需修复，设计差异。Charles 编号列表强调规则优先级，适合量化场景的有序规则执行。

### 5.3 优先级 P2（可选优化）

- **`_build_environment` 保留方法**（context.py L649-681）：建议在未来 major 版本移除，当前保留不影响功能。该方法的中文字段名（`工作目录` / `平台` / `日期` / `IDE`）容易被误认为 Charles system prompt 的实际 `<env>` 字段名，但实际 build() 主路径使用 base prompt 模板的英文 `<env>` 块。建议在 docstring 中补充说明"此方法输出格式与 base prompt 模板的 `<env>` 块不同，仅用于向后兼容"。

- **nanobot 注释残留**（context.py L275）：与 P5.1 建议一致，建议保留作为历史说明。`extra_sections` 参数和 `_build_rules` L530-537 死代码可在未来 major 版本移除。

### 5.4 优先级 P3（文档修正）

- **计划文件 P5.21 描述错误**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2182-2206：
  - L2192 "文本块: 无" → "文本块: `## 通用行为规则` / `## 工具调用规则`"
  - L2193 "字段名: 中文（部分）" → "字段名: 英文（base prompt 模板，build() 主路径）/ 中文（`_build_environment` 保留方法，未在 build() 调用）"
  - L2199 "Charles `<charles_metadata>`" → "Charles `# Workspace Configuration`（L5 阶段已对齐）"
  - L2199 "L5 差距" → "已对齐"

---

## 六、验证方法

### 6.1 XML 标签验证

```powershell
# 验证 Charles <env> 标签与 Cline 一致（4 字段编号列表，英文字段名）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "<env>"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Pattern "<env>"

# 验证 <user_input mode> 标签生成
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern 'user_input mode'
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\format.ts" -Pattern 'user_input mode'

# 验证 <mode_notice> 文本一致性（应完全相同）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern 'mode_notice>The user switched'
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\format.ts" -Pattern 'mode_notice>The user switched'

# 验证 <SYSTEM_NOTICE> 文本一致性
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern 'SYSTEM_NOTICE>Earlier context'
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\context\basic-compaction.ts" -Pattern 'SYSTEM_NOTICE>Earlier context'
```

### 6.2 metadata 块标记验证

```powershell
# 验证 Charles metadata 块使用 # Workspace Configuration 文本标记（非 <charles_metadata> XML 标签）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "Workspace Configuration"
# 应输出 4 行：L412（docstring 示例）/ L423（docstring 说明）/ L427（docstring 返回值）/ L450（实际生成代码）

# 验证 <charles_metadata> 仅在 docstring 中作为历史说明出现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "charles_metadata"
# 应输出 1 行：L424（docstring "不再使用 `<charles_metadata>` XML 标签"）
```

### 6.3 字段名语言验证

```powershell
# 验证 base prompt 模板的 <env> 字段名全英文（build() 主路径使用）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "Platform:|Date:|IDE:|Working Directory:"
# 应输出 8 行（DEFAULT + YOLO 各 4 字段），全英文

# 验证 _build_environment 保留方法用中文字段名（不在 build() 主路径）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "工作目录:|平台:|日期:|IDE:"
# 应输出 4 行（L666-670），仅 _build_environment 保留方法
```

### 6.4 nanobot 残留验证

```powershell
# 在 System Prompt 风格相关文件中搜索 nanobot
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 应输出 1 行：L275（extra_sections docstring 注释残留）

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
# 应输出 0 行

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "nanobot" -CaseSensitive:$false
# 应输出 0 行

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "nanobot" -CaseSensitive:$false
# 应输出 0 行
```

### 6.5 占位符风格验证

```powershell
# 验证 Charles 占位符风格与 Cline 一致（双花括号，前缀不同）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "\{\{[A-Z_]+\}\}"
# 应输出 12 行（DEFAULT + YOLO 各 6 个占位符）：{{PLATFORM_NAME}} {{CURRENT_DATE}} {{IDE_NAME}} {{CWD}} {{CHARLES_RULES}} {{CHARLES_METADATA}}

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Pattern "\{\{[A-Z_]+\}\}"
# 应输出 12 行（DEFAULT + YOLO 各 6 个占位符）：{{PLATFORM_NAME}} {{CURRENT_DATE}} {{IDE_NAME}} {{CWD}} {{CLINE_RULES}} {{CLINE_METADATA}}
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.21.1 XML 标签风格 | 已对齐 | **已对齐** | `<env>` 完全一致 |
| 5.21.2 metadata 标签 | L5 差距 | **已对齐** | L5 阶段已完成对齐，Charles 用 `# Workspace Configuration` 文本标记，非 `<charles_metadata>` XML 标签。计划表描述错误 |
| 5.21.3 字段名语言 | L1 差距 | **已对齐** | base prompt 模板 `<env>` 字段名全英文，与 Cline 完全一致。仅 `_build_environment` 保留方法用中文，但不在 build() 主路径。计划表描述错误 |
| 5.21.4 措辞语言 | 语言不同 | **本地化差异** | Cline 英文 / Charles 中文，属本地化设计，非对齐缺口 |
| 5.21.5 标签闭合 | 已对齐 | **已对齐** | — |
| 5.21.6 标签嵌套 | 已对齐 | **已对齐** | — |

**计划表标注总结**：6 项中 3 项标注"差距/语言不同"的项实际已对齐或为合理本地化差异，3 项标注"已对齐"的项确认对齐。计划表 P5.21 整体偏保守，未反映 L5 阶段对齐成果，且对 Charles 风格的描述存在三处事实错误（文本块/字段名/metadata 标签）。

---

## 八、补充：四类 XML 标签对齐详情

### 8.1 `<env>` 标签

**Cline**（system.ts L7-13）：
```
Environment you are running in:
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

**Charles**（charles_system_prompt.py L49-54）：
```
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

**差异**：Cline 在 `<env>` 前有引导句"Environment you are running in:"，Charles 无引导句直接放 `<env>` 块。属细微差异，不影响语义。`<env>` 块内部格式完全一致。

### 8.2 `<user_input mode="...">` 标签

**Cline**（format.ts L5-10）：
```typescript
export function formatUserInputBlock(
    input: string,
    mode: "act" | "plan" | "yolo" = "act",
): string {
    return `<user_input mode="${mode}">${input}</user_input>`;
}
```

**Charles**（server.py L605）：
```python
wrapped_message = f'{notice_prefix}<user_input mode="{current_mode}">\n{message}\n</user_input>'
```

**差异**：Charles 在标签与内容间加 `\n`，Cline 紧贴内容。语义一致，排版细微差异。

### 8.3 `<mode_notice>` 标签

**Cline**（format.ts L41-46）：
```typescript
export function formatModeSwitchNotice(
    from: "act" | "plan",
    to: "act" | "plan",
): string {
    return `<mode_notice>The user switched from ${from} mode to ${to} mode before sending this message.</mode_notice>`;
}
```

**Charles**（state.py L466-484）：
```python
def format_mode_switch_notice(notice: ModeSwitchNotice) -> str:
    """生成 <mode_notice> XML 文本"""
    return (
        f'<mode_notice>The user switched from {notice.from_mode} mode '
        f'to {notice.to_mode} mode before sending this message.</mode_notice>'
    )
```

**差异**：文本完全一致（英文）。Charles 函数签名接受 `ModeSwitchNotice` 对象，Cline 接受 `from` / `to` 两个参数，属接口差异非风格差异。

### 8.4 `<SYSTEM_NOTICE>` 标签

**Cline**（basic-compaction.ts L80-92）：
```typescript
function buildDroppedWorkSummaryBlock(
    summary: ToolActivitySummary,
    preservedResponses: string[],
): ContentBlock {
    const responsesSection =
        preservedResponses.length > 0
            ? `\n\nYour recent responses:\n${preservedResponses.join("\n---\n")}`
            : "";
    return {
        type: "text",
        text: `<SYSTEM_NOTICE>\nEarlier context was compacted. Summary of your actions after the request above:\n${formatToolActivitySummary(summary)}${responsesSection}</SYSTEM_NOTICE>`,
    };
}
```

**Charles**（context.py L2296-2368）：
```python
def _build_dropped_work_summary_block(
    self,
    tool_activity: dict[str, list[str]],
    preserved_responses: list[str],
) -> str:
    parts: list[str] = [
        "<SYSTEM_NOTICE>",
        "Earlier context was compacted. Summary of your actions after the request above:",
    ]
    # ... Files read / Files edited / Commands ran / Your recent responses
    parts.append("</SYSTEM_NOTICE>")
    return "\n".join(parts)
```

**差异**：文本结构完全一致（英文）。Charles 用 list 拼接，Cline 用模板字符串，实现方式不同但输出格式一致。
