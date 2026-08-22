# Phase 6.8 AGENTS.md rule name 对比

> 对比范围：Cline `formatRulesForSystemPrompt` + `parseRuleConfigFromMarkdown` + `resolveRuleFallbackName` 的 rule name 生成逻辑，与 Charles `format_rules_content` 的 rule name 生成逻辑逐项对标；区分注释残留与实现逻辑残留的 nanobot 专项检查。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/runtime/safety/rules.ts` L10-21（`formatRulesForSystemPrompt`，渲染 `## ${rule.name}`）
> - `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L50-55（`RuleConfig.name` 类型定义）+ L313-338（`parseRuleConfigFromMarkdown`，name 优先级：frontmatter `name` → fallbackName）+ L261-282（`resolveRuleFallbackName`，fallback 逻辑：AGENTS.md 特殊处理）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L206-259（`getRuleFilesTotalContentWithMetadata`，VSCode 路径用 `ruleFilePathRelative` 作为内容头）
> - `third_party/cline/sdk/packages/shared/src/remote-config/materializer.ts` L71-77（远程规则用 `## ${rule.name}`）
>
> Charles 源码：
> - `agent/rules_loader.py` L686-722（`format_rules_content`，`name = r.path.stem`）
> - `agent/context.py` L454-539（`_build_rules`，组装 RuleLoadResult 列表后委托 `format_rules_content` 渲染）
> - `agent_config/rules/AGENTS.md` L1-5（frontmatter：无 `name` 字段）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 AGENTS.md / 规则文件加载后，渲染到 system prompt 时的 **rule name（即 `## ` 标题）来源**。**核心结论：Cline 的 rule name 是三级优先级（frontmatter `name` → AGENTS.md 特殊名 → 文件 stem），Charles 仅用文件 stem 一级。计划文件 P6.8 的描述基本准确，但"Cline: watcher.name"的表述过于简化，未反映 frontmatter `name` 优先级和 AGENTS.md 特殊处理。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.8（L2405-2414）描述：
- **Cline 实现**：rule name = watcher 提供的 `rule.name`
- **Charles 实现**：rule name = 文件 stem（L3-new 差距）

**此描述基本方向正确，但遗漏两个关键细节**：

1. **Cline `rule.name` 不是单一来源**：`rule.name` 由 `parseRuleConfigFromMarkdown`（user-instruction-config-loader.ts L325-326）按优先级生成：
   ```typescript
   const name = parseStringField(data.name, "name", false) ?? fallbackName.trim();
   ```
   优先级为：① frontmatter `name` 字段 → ② `resolveRuleFallbackName` 返回值。`watcher.name` 只是最终结果，其源头包含 frontmatter 与 fallback 两级。

2. **AGENTS.md 特殊处理**：`resolveRuleFallbackName`（L261-282）对 `AGENTS.md` 文件有专门分支：
   - 工作区根目录的 AGENTS.md → `"Workspace AGENTS.md"`
   - 全局 AGENTS.md（`~/.cline/...` 或 `resolveGlobalAgentsRulesPath()`）→ `"Global AGENTS.md"`
   - 其他位置的 AGENTS.md → 文件 stem `"AGENTS"`
   - 非 AGENTS.md 文件 → 文件 stem（如 `my-rule.md` → `"my-rule"`）

   Charles 对所有文件统一用 `r.path.stem`，AGENTS.md 渲染为 `"AGENTS"`（无 "Workspace"/"Global" 前缀，无 `.md` 扩展名）。

### 核心结论

1. **`## ` 标题格式已对齐**：Cline SDK core 路径（`formatRulesForSystemPrompt`）与 Charles 均用 `## ${name}\n${body}` 格式渲染每条规则。
2. **rule name 优先级 Charles 是 Cline 子集**：Cline 三级优先级（frontmatter name → AGENTS.md 特殊名 → 文件 stem），Charles 仅一级（文件 stem）。Charles 缺失 frontmatter `name` 覆盖能力与 AGENTS.md 特殊命名。
3. **AGENTS.md 渲染名差异**：Cline 将工作区 AGENTS.md 渲染为 `## Workspace AGENTS.md`、全局 AGENTS.md 渲染为 `## Global AGENTS.md`；Charles 统一渲染为 `## AGENTS`。这是用户可感知的 system prompt 文本差异。
4. **VSCode 路径与 SDK 路径不同**：Cline VSCode app 路径（`rule-helpers.ts` 的 `getRuleFilesTotalContentWithMetadata`）用 `ruleFilePathRelative`（相对路径含扩展名，如 `subdir/rule.md`）作为**纯文本头**（非 `## ` 标题），与 SDK core 路径和 Charles 均不同。此路径为 VSCode 扩展专用，SDK / Charles 不走此路径。
5. **frontmatter `name` 字段在双方 AGENTS.md 均未使用**：Cline sdk/AGENTS.md 和 Charles agent_config/rules/AGENTS.md 的 frontmatter 都**不含 `name` 字段**，故实际命中的是 fallback 路径。但 Charles 的 rules_loader.py 即使 frontmatter 写了 `name` 也不会读取（不支持此字段）。
6. **nanobot 残留**：P6.8 范围内 rules_loader.py 与 AGENTS.md **0 处残留**；context.py 有 **1 处注释残留**（L275 docstring，已由 P5.1 记录，非本阶段引入）。实现逻辑残留 0 处。

### 一致性总体评估

- **`## ` 标题格式**：**高**。双方均用 `## ${name}` markdown 二级标题。
- **rule name 来源**：**中**。Charles 是 Cline 的简化子集，缺失 frontmatter `name` 覆盖和 AGENTS.md 特殊命名。
- **AGENTS.md 命名**：**低-中**。Cline "Workspace AGENTS.md" / "Global AGENTS.md" vs Charles "AGENTS"，存在可感知文本差异。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.8.1 | rule name 来源 | SDK core: `rule.name`（= frontmatter `name` ?? fallbackName）；VSCode: `ruleFilePathRelative`；Remote: `rule.name` | `r.path.stem`（文件 stem） | 中 | Charles 仅用文件 stem 一级。Cline SDK core 支持三级优先级，VSCode 路径用相对路径。计划表"Cline: watcher.name"过于简化 |
| 6.8.2 | frontmatter `name` 字段支持 | 支持（`parseRuleConfigFromMarkdown` L325-326，frontmatter `name` 优先于 fallback） | 不支持（`format_rules_content` L716 直接用 `r.path.stem`，不读 frontmatter `name`） | 低 | **L3-new 差距**：Charles 缺失 frontmatter `name` 覆盖能力。若用户在规则文件 frontmatter 写 `name: my-custom-name`，Cline 会用 "my-custom-name"，Charles 仍用文件 stem |
| 6.8.3 | AGENTS.md 特殊命名 | `resolveRuleFallbackName` L261-282：工作区 AGENTS.md → "Workspace AGENTS.md"；全局 AGENTS.md → "Global AGENTS.md"；其他 AGENTS.md → stem "AGENTS" | 无特殊处理，统一 `r.path.stem` = "AGENTS" | 低 | **可感知差异**：Cline system prompt 中 AGENTS.md 规则标题为 `## Workspace AGENTS.md` / `## Global AGENTS.md`，Charles 为 `## AGENTS`。多个 AGENTS.md（全局+工作区）同时存在时，Cline 可区分，Charles 标题重复 |
| 6.8.4 | 非 AGENTS.md 规则文件命名 | 文件 stem（`basename(filePath, extname)`，L267） | 文件 stem（`r.path.stem`，L716） | 高 | 已对齐。如 `my-rule.md` → "my-rule" |
| 6.8.5 | `## ` 标题格式 | SDK core: `## ${rule.name}\n${rule.instructions}`（rules.ts L18）；Remote: `## ${rule.name}`（materializer.ts L74） | `## ${name}\n\n${body}`（rules_loader.py L717） | 高 | 已对齐。双方均用 markdown 二级标题。Charles 在标题与正文间多一个空行（`\n\n`），Cline SDK core 用单 `\n`，属细微格式差异 |
| 6.8.6 | `# Rules` 总标题 | SDK core: `\n\n# Rules\n${renderedRules}`（rules.ts L20）；Charles: `# Rules\n\n${parts}`（rules_loader.py L722） | 高 | 已对齐。双方均用 `# Rules` 一级标题作为规则段开头 |
| 6.8.7 | VSCode 路径命名格式 | `getRuleFilesTotalContentWithMetadata` 用 `${ruleFilePathRelative}\n${body}`（rule-helpers.ts L234/L246），相对路径含扩展名，无 `## ` 标题 | 不适用（Charles 无 VSCode 路径） | 不适用 | Cline VSCode 路径为扩展专用，与 SDK core / Charles 路径完全不同。此差异不在 Charles 对标范围 |
| 6.8.8 | 功能等价性 | 是 | 是 | 高 | 合理差异。双方 rule name 均能唯一标识规则并渲染为 `## ` 标题，功能等价 |

---

## 三、重点差距详解

### 3.1 Cline rule name 三级优先级机制

Cline SDK core 路径的 rule name 由 `parseRuleConfigFromMarkdown`（user-instruction-config-loader.ts L313-338）生成，优先级如下：

```typescript
// user-instruction-config-loader.ts L325-329
const name =
    parseStringField(data.name, "name", false) ?? fallbackName.trim();
if (!name) {
    throw new Error("Missing rule name.");
}
```

**优先级 1：frontmatter `name` 字段**
- 若 frontmatter 含 `name: my-custom-name`，则 `rule.name = "my-custom-name"`
- 测试验证（user-instruction-config-loader.test.ts L117-125）：frontmatter `name: rule-a` → `rule.name = "rule-a"`

**优先级 2：fallbackName（由 `resolveRuleFallbackName` 提供）**

```typescript
// user-instruction-config-loader.ts L261-282
function resolveRuleFallbackName(context, workspacePath) {
    const fileName = basename(context.filePath);
    if (fileName.toLowerCase() !== AGENTS_RULES_FILE_NAME.toLowerCase()) {
        return basename(context.filePath, extname(context.filePath));  // 文件 stem
    }
    // AGENTS.md 特殊处理
    if (workspacePath && resolve(context.filePath) === resolve(workspacePath, AGENTS_RULES_FILE_NAME)) {
        return "Workspace AGENTS.md";
    }
    if (resolve(context.filePath) === resolve(resolveGlobalAgentsRulesPath())) {
        return "Global AGENTS.md";
    }
    return basename(context.filePath, extname(context.filePath));  // stem "AGENTS"
}
```

fallback 按文件位置分三种：
| 文件类型 | 位置 | fallback name |
|---------|------|---------------|
| 非 AGENTS.md | 任意 | 文件 stem（如 `my-rule.md` → `my-rule`） |
| AGENTS.md | 工作区根（`<workspace>/AGENTS.md`） | `"Workspace AGENTS.md"` |
| AGENTS.md | 全局（`resolveGlobalAgentsRulesPath()`） | `"Global AGENTS.md"` |
| AGENTS.md | 其他位置 | `"AGENTS"`（stem） |

### 3.2 Charles rule name 单级机制

Charles `format_rules_content`（rules_loader.py L686-722）对所有规则文件统一处理：

```python
# rules_loader.py L709-717
for r in results:
    if not r.activated:
        continue
    body = r.body.strip()
    if not body:
        continue
    # 使用文件 stem 作为 rule 标题（对齐 Cline ## name 格式）
    name = r.path.stem
    parts.append(f"## {name}\n\n{body}")
```

Charles 不读 frontmatter `name` 字段，也不区分 AGENTS.md 与普通规则文件。所有规则的 name = `r.path.stem`。

### 3.3 AGENTS.md 命名差异的实际影响

Charles context.py L471-496 加载两个 AGENTS.md 文件：
1. **全局 AGENTS.md**（`~/.agent/AGENTS.md`，L472-483）→ `r.path.stem = "AGENTS"`
2. **工作区 AGENTS.md**（`self.agents_path`，L486-496）→ `r.path.stem = "AGENTS"`

当两个 AGENTS.md 同时存在时，Charles system prompt 会出现两个 `## AGENTS` 标题：

```
# Rules

## AGENTS

<全局 AGENTS.md 正文>

## AGENTS

<工作区 AGENTS.md 正文>
```

Cline 在相同场景下会渲染为：

```
# Rules

## Global AGENTS.md

<全局 AGENTS.md 正文>

## Workspace AGENTS.md

<工作区 AGENTS.md 正文>
```

**影响**：Charles 的重复 `## AGENTS` 标题可能让 LLM 难以区分两个规则文件的来源，且不符合 markdown 标题唯一性惯例。Cline 的 "Global"/"Workspace" 前缀提供了明确的来源标识。

### 3.4 frontmatter `name` 字段支持差异的实际影响

当前双方 AGENTS.md frontmatter 均不含 `name` 字段，故此差异**当前无运行时影响**。但存在以下场景会触发差异：

| 场景 | Cline 行为 | Charles 行为 |
|------|-----------|-------------|
| 规则文件 `research.md`，frontmatter 无 `name` | `## research` | `## research` |
| 规则文件 `research.md`，frontmatter `name: 研究场景规则` | `## 研究场景规则` | `## research`（忽略 frontmatter） |
| 规则文件 `123-rules.md`，frontmatter `name: 数字命名规则` | `## 数字命名规则` | `## 123-rules` |

Charles 用户若在 frontmatter 写 `name` 字段期望覆盖文件名，会被静默忽略，存在"写了不生效"的预期落差。

### 3.5 Cline VSCode 路径的差异说明（非 Charles 对标范围）

Cline 存在两条 rule 加载路径：

1. **SDK core 路径**（`sdk/packages/core/src/runtime/safety/rules.ts`）：
   - 用 `formatRulesForSystemPrompt` 渲染
   - rule name = `rule.name`（三级优先级）
   - 格式：`## ${rule.name}\n${rule.instructions}`
   - 用于 SDK / Hub / CLI 等非 VSCode 场景

2. **VSCode app 路径**（`apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts`）：
   - 用 `getRuleFilesTotalContentWithMetadata` 渲染
   - rule name = `ruleFilePathRelative`（相对路径含扩展名，如 `subdir/rule.md`）
   - 格式：`${ruleFilePathRelative}\n${body}`（纯文本头，非 `## ` 标题）
   - 用于 VSCode 扩展

Charles 走的是 SDK core 等价路径（`format_rules_content` 用 `## ` 标题），与 Cline SDK core 路径对齐。VSCode 路径的差异不在 Charles 对标范围。

### 3.6 计划文件 P6.8 描述准确性评估

| 计划表项 | 计划描述 | 实际核实 | 准确性 |
|---------|---------|---------|--------|
| 6.8.1 rule name 来源 | Cline: watcher.name；Charles: 文件 stem；L3-new 差距 | Cline: `rule.name`（frontmatter name ?? fallback）；Charles: 文件 stem | 方向正确，但 watcher.name 过于简化 |
| 6.8.2 功能等价性 | 是 / 是 | 双方均能渲染 `## ` 标题，功能等价 | 准确 |

**修正建议**：计划表 6.8.1 的"Cline: watcher.name"应改为"Cline: frontmatter name ?? fallbackName（含 AGENTS.md 特殊命名）"，以反映三级优先级机制。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.8 范围内涉及以下 3 个文件：
- `agent/rules_loader.py`（1053 行，rule name 生成主逻辑）
- `agent/context.py`（2666 行，rule 组装与 system prompt 构建）
- `agent_config/rules/AGENTS.md`（56 行，规则文件示例）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/rules_loader.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样（case-insensitive 搜索）。docstring 与注释均对标 Cline（"对标 Cline frontmatter.ts" / "对标 Cline parseYamlFrontmatter" / "对标 Cline getRuleFilesTotalContentWithMetadata" / "对标 Cline formatRulesForSystemPrompt"），无 nanobot 对标引用 |
| `agent/context.py` | 1 处 | 0 处 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`。此为**注释残留**（参数说明文档），非实现逻辑残留。已由 P5.1 记录在案，非本阶段引入 |
| `agent_config/rules/AGENTS.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。frontmatter 与正文均为 Charles 原生设计 |

**P6.8 范围内 nanobot 残留总计：1 处（注释 1 + 实现逻辑 0）。**

### 4.3 残留详情：context.py L275

```python
# context.py L275（SystemPromptBuilder.__init__ docstring）
extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                保留参数签名仅为向后兼容，当前无调用方传入。
```

**残留类型**：注释残留（docstring 描述）

**分析**：
- 此注释描述 `extra_sections` 参数的历史来源（nanobot 风格），并明确标注"已废弃"+"Cline 无此概念"+"保留仅为向后兼容"
- 参数本身在 `__init__` 中仍被接收（L292 `self.extra_sections = extra_sections or {}`），并在 `_build_rules` L530-537 仍有使用代码
- 但注释明确表示"当前无调用方传入"，且使用路径已被 `[已废弃]` 标记
- 这是**注释残留**而非**实现逻辑残留**：`extra_sections` 的使用逻辑是 Charles 自身的兼容层，不是 nanobot 的逻辑

**归属**：已由 P5.1 记录，非本阶段引入，不在本阶段修复范围。

---

## 五、修复建议

### 5.1 中优先级：AGENTS.md 命名对齐（建议修复）

**问题**：Charles 对 AGENTS.md 统一用 `r.path.stem = "AGENTS"`，当全局与工作区 AGENTS.md 同时存在时，system prompt 出现重复 `## AGENTS` 标题。Cline 用 "Workspace AGENTS.md" / "Global AGENTS.md" 区分。

**修复建议**：在 `format_rules_content`（rules_loader.py L686-722）中增加 AGENTS.md 特殊命名逻辑：

```python
def format_rules_content(results: list[RuleLoadResult]) -> str:
    parts: list[str] = []
    for r in results:
        if not r.activated:
            continue
        body = r.body.strip()
        if not body:
            continue
        # AGENTS.md 特殊命名（对标 Cline resolveRuleFallbackName）
        if r.path.name.lower() == "agents.md":
            # 全局 AGENTS.md（~/.agent/AGENTS.md）
            if str(r.path.parent).lower() == str(Path.home() / ".agent").lower():
                name = "Global AGENTS.md"
            else:
                name = "Workspace AGENTS.md"
        else:
            name = r.path.stem
        parts.append(f"## {name}\n\n{body}")
    if not parts:
        return ""
    return "# Rules\n\n" + "\n\n".join(parts)
```

**权衡**：此修复会改变 system prompt 文本（`## AGENTS` → `## Workspace AGENTS.md`），可能影响已有对话的 LLM 上下文。但收益是消除重复标题、对齐 Cline 命名、提升 LLM 对规则来源的识别能力。**建议在下次 system prompt 重构时一并修复**。

### 5.2 低优先级：frontmatter `name` 字段支持（可选）

**问题**：Charles `format_rules_content` 不读 frontmatter `name` 字段，用户在 frontmatter 写 `name: 自定义名` 会被静默忽略。Cline 支持此字段作为 rule name 覆盖。

**修复建议**：在 `RuleLoadResult` 中增加 `name` 字段，`load_rules_directory` 解析 frontmatter 时提取 `name`，`format_rules_content` 优先用 `r.name` ?? `r.path.stem`。

**权衡**：当前 Charles AGENTS.md 和规则文件均未使用 frontmatter `name` 字段，此修复属**前瞻性增强**，非必要。若未来需要支持中文规则名或自定义规则标识，可再实施。**当前不建议修复**（避免过度工程）。

### 5.3 不修复：context.py L275 nanobot 注释残留

**问题**：context.py L275 docstring 含 "nanobot 风格的额外段落" 注释残留。

**修复建议**：**不修复**。此残留已由 P5.1 记录在案，归属 P5.x 阶段管辖。本阶段不重复处理。建议在 P5.1 后续修复时统一清理 nanobot 注释残留（涉及多个文件，参见 P4.20 nanobot 残留审计报告）。

### 5.4 不修复：`## ` 标题后空行差异

**问题**：Cline SDK core 用 `## ${name}\n${instructions}`（单换行），Charles 用 `## ${name}\n\n${body}`（双换行，多一个空行）。

**修复建议**：**不修复**。markdown 渲染中 `\n` 与 `\n\n` 在 `## ` 标题后视觉效果相同（标题与正文间自动有空行）。此差异对 LLM 理解无影响，属无害的格式风格差异。

---

## 六、验证方法

### 6.1 Cline rule name 来源验证

1. 读取 Cline `rules.ts` L17-20，确认 `formatRulesForSystemPrompt` 用 `## ${rule.name}` 渲染
2. 读取 Cline `user-instruction-config-loader.ts` L325-326，确认 `parseRuleConfigFromMarkdown` 的 name 优先级为 `frontmatter name ?? fallbackName`
3. 读取 Cline `user-instruction-config-loader.ts` L261-282，确认 `resolveRuleFallbackName` 对 AGENTS.md 的三种特殊命名分支
4. 读取 Cline 测试文件 `user-instruction-config-loader.test.ts` L117-125，确认 frontmatter `name: rule-a` → `rule.name = "rule-a"`

### 6.2 Charles rule name 来源验证

1. 读取 Charles `rules_loader.py` L716，确认 `format_rules_content` 用 `name = r.path.stem`
2. 确认 Charles 不读 frontmatter `name` 字段（Grep `rules_loader.py` 搜索 `data.get("name"` / `frontmatter.get("name"`，无命中）
3. 读取 Charles `context.py` L472-496，确认全局 AGENTS.md 和工作区 AGENTS.md 均通过 `r.path.stem` 渲染为 "AGENTS"

### 6.3 AGENTS.md 命名差异验证

1. 确认 Cline `resolveRuleFallbackName` L273-274：工作区 AGENTS.md → "Workspace AGENTS.md"
2. 确认 Cline `resolveRuleFallbackName` L277-278：全局 AGENTS.md → "Global AGENTS.md"
3. 确认 Charles `format_rules_content` L716：所有文件统一 `r.path.stem`，AGENTS.md → "AGENTS"
4. 构造场景：全局 + 工作区 AGENTS.md 同时存在，对比双方 system prompt 中 `## ` 标题差异

### 6.4 nanobot 残留验证

1. Grep `agent/rules_loader.py` 搜索 `nanobot`（case-insensitive），确认 0 匹配
2. Grep `agent/context.py` 搜索 `nanobot`（case-insensitive），确认仅 L275 一处注释残留
3. Grep `agent_config/rules/AGENTS.md` 搜索 `nanobot`（case-insensitive），确认 0 匹配

### 6.5 计划文件描述验证

1. 读取 `AGENT_COMPARISON_PLAN_V2.md` L2405-2414，确认 P6.8 描述"Cline: watcher.name"
2. 对比 Cline 实际 `parseRuleConfigFromMarkdown` L325-326，确认 `rule.name` 实际来源为 `frontmatter name ?? fallbackName`
3. 确认计划描述"watcher.name"是最终结果而非源头，遗漏 frontmatter 优先级和 AGENTS.md 特殊处理

---

## 七、附录

### 7.1 Cline rule name 三级优先级流程图

```
Cline SDK core 路径 rule.name 生成：

parseRuleConfigFromMarkdown(content, fallbackName)
    │
    ├─ frontmatter 有 name 字段？
    │   ├─ 是 → rule.name = frontmatter.name
    │   └─ 否 → rule.name = fallbackName
    │
    └─ fallbackName = resolveRuleFallbackName(context, workspacePath)
        │
        ├─ 文件名 != AGENTS.md？
        │   └─ 返回文件 stem（如 my-rule.md → "my-rule"）
        │
        ├─ 文件名 == AGENTS.md？
        │   ├─ 位于工作区根 → 返回 "Workspace AGENTS.md"
        │   ├─ 位于全局路径 → 返回 "Global AGENTS.md"
        │   └─ 其他位置    → 返回 stem "AGENTS"

formatRulesForSystemPrompt(rules)
    │
    └─ 渲染为 `## ${rule.name}\n${rule.instructions}`
```

### 7.2 Charles rule name 单级流程图

```
Charles 路径 rule.name 生成：

format_rules_content(results)
    │
    └─ 对每个 RuleLoadResult r：
        │
        ├─ name = r.path.stem（统一文件 stem）
        │   ├─ AGENTS.md → "AGENTS"
        │   ├─ my-rule.md → "my-rule"
        │   └─ 不读 frontmatter name 字段
        │
        └─ 渲染为 `## ${name}\n\n${body}`
```

### 7.3 双方 AGENTS.md 渲染对比（全局 + 工作区同时存在）

```
Cline system prompt（SDK core 路径）：
# Rules

## Global AGENTS.md
<全局 AGENTS.md 正文>

## Workspace AGENTS.md
<工作区 AGENTS.md 正文>

## my-rule
<my-rule.md 正文>


Charles system prompt：
# Rules

## AGENTS
<全局 AGENTS.md 正文>

## AGENTS
<工作区 AGENTS.md 正文>

## my-rule
<my-rule.md 正文>
```

### 7.4 Cline 三条 rule 加载路径对比

| 路径 | 文件 | rule name 来源 | 渲染格式 | 适用场景 |
|------|------|---------------|---------|---------|
| SDK core | `rules.ts` `formatRulesForSystemPrompt` | `rule.name`（frontmatter name ?? fallback） | `## ${rule.name}\n${instructions}` | SDK / Hub / CLI |
| VSCode app | `rule-helpers.ts` `getRuleFilesTotalContentWithMetadata` | `ruleFilePathRelative`（相对路径含扩展名） | `${ruleFilePathRelative}\n${body}`（纯文本头） | VSCode 扩展 |
| Remote | `materializer.ts` | `rule.name`（远程配置 schema） | `## ${rule.name}\n\n${contents}` | 远程规则下发 |

Charles 走 SDK core 等价路径，与 Cline SDK core 对齐。
