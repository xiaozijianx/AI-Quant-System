# Phase 6.1 AGENTS.md frontmatter 对比

> 对比范围：Cline `sdk/AGENTS.md` + `sdk/packages/llms/AGENTS.md` 示例文件的 frontmatter 字段，与 Charles `agent_config/rules/AGENTS.md` 的 frontmatter 字段逐项对标；并对比 Cline `frontmatter.ts` 的 `parseYamlFrontmatter` 解析器 + `rule-conditionals.ts` 的条件评估器，与 Charles `agent/rules_loader.py` 的 `parse_yaml_frontmatter` + `evaluate_rule_conditionals` 实现差异；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md` L1-5（frontmatter：`description` / `globs` / `alwaysApply`）
> - `third_party/cline/sdk/packages/llms/AGENTS.md` L1-5（frontmatter：`description` / `globs` / `alwaysApply`）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts` L1-59（`parseYamlFrontmatter` + `FrontmatterParseResult` 类型）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts` L1-103（`evaluateRuleConditionals` + `conditionalEvaluators` 注册表，**仅注册 `paths`**）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts` L1-34（`refreshClineRulesToggles`，toggle 同步入口）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md` L1-5（frontmatter：`description` / `applyTo` / `alwaysApply`）
> - `agent/rules_loader.py` L49-181（`parse_yaml_frontmatter` + `FrontmatterParseResult` dataclass）+ L433-481（`evaluate_rule_conditionals`，评估 `enabled`/`applyTo`/`mode`/`paths`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md frontmatter 字段集合与解析/评估实现。**核心结论：frontmatter 解析器与分隔符已完全对齐（正则逐字符相同），但 frontmatter 字段集合存在显著差异，且计划文件 P6.1 对 Cline 字段集合的描述存在事实错误。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.1（L2243-2250）列出的 Cline frontmatter 参考为：
```yaml
---
description: <规则描述>
globs: ["**/*.ts"]
applyTo: [act, plan]
alwaysApply: true
---
```

**此参考与 Cline 实际源码不符，存在两处事实错误**：

1. **`applyTo` 字段虚构**：Cline 实际的 `sdk/AGENTS.md`（L1-5）和 `sdk/packages/llms/AGENTS.md`（L1-5）frontmatter **均不含 `applyTo` 字段**。Cline 的 `rule-conditionals.ts` L74-76 的 `conditionalEvaluators` 注册表**仅注册 `paths` 一个评估器**，`applyTo` 既不出现在 Cline 任何 AGENTS.md 示例中，也不被评估器识别。计划表中 6.1.4 标注"Cline: 是"是错误的。Grep 全 Cline 代码库 `applyTo` 仅命中 `applyToStartSessionInput`（remote-config 集成方法，与 frontmatter 无关）。
2. **`globs` 字段未被评估**：Cline AGENTS.md 示例确实使用 `globs` 字段，但 `rule-conditionals.ts` 的评估器**只识别 `paths`，不识别 `globs`**。这意味着 Cline 自己 AGENTS.md 里的 `globs` 字段是**未评估的死字段**（forward-compat 注释明确说"unknown conditional keys are ignored"）。Cline 真正用于路径过滤的字段名是 `paths`，而非 `globs`。

### 核心结论

1. **frontmatter 解析器已对齐**：Cline `parseYamlFrontmatter`（frontmatter.ts L38-58）与 Charles `parse_yaml_frontmatter`（rules_loader.py L131-181）的正则**逐字符完全相同**：`^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$`。
2. **frontmatter 分隔符已对齐**：双方均使用 `---` 三横线作为 YAML frontmatter 边界。
3. **BOM 处理已对齐**：Cline 调 `stripUtf8Bom`，Charles 内联 `if normalized.startswith(_UTF8_BOM)` 剥离，语义等价。
4. **fail-open 策略已对齐**：双方对"无 frontmatter"和"解析失败"均采用 fail-open（保留原文整体加载）。
5. **YAML schema 存在差异**：Cline 用 `yaml.load(..., { schema: yaml.JSON_SCHEMA })`（严格 JSON-only schema，不支持 `yes/no/null` 等 YAML 原生类型），Charles 用 `yaml.safe_load(...)`（DEFAULT_SAFE_SCHEMA，支持更多 YAML 类型）。对 `alwaysApply: true` 等 JSON 兼容值无影响，但对 `enabled: yes` 等非 JSON 值会产生解析差异。
6. **顶层类型校验 Charles 更严格**：Charles 显式 `isinstance(data, dict)` 校验，非 dict 时 fail-open 记录 parse_error；Cline 仅做 TypeScript 类型断言 `as Record<string, unknown>`，无运行时校验（YAML 为 list/string 时会静默通过，存在潜在 bug）。
7. **条件评估器 Charles 是 Cline 超集**：Cline 仅评估 `paths`；Charles 评估 `enabled`/`applyTo`/`mode`/`paths` 四个字段。Charles 的 `applyTo`（agent 模式过滤）和 `mode`（业务模式过滤）是 Charles 自定义扩展，Cline 无对应概念。
8. **`alwaysApply` 在双方均未被评估**：Cline 和 Charles 的 AGENTS.md 都写了 `alwaysApply: true`，但双方的评估器都不识别此字段——它是**纯文档元数据**，对"是否激活"无实际影响。Charles AGENTS.md 的"常驻"语义实际由 `applyTo: [act, plan]`（覆盖所有 agent 模式）实现，而非 `alwaysApply`。
9. **nanobot 残留**：P6.1 范围内（AGENTS.md + rules_loader.py）**0 处残留**（注释残留 0、实现逻辑残留 0）。其他模块的残留超出本阶段范围。

### 一致性总体评估

- **frontmatter 解析机制**：**高**。正则、BOM 处理、fail-open 策略完全对齐。
- **frontmatter 字段集合**：**中**。双方都有 `description`/`alwaysApply`，但 Cline 用 `globs`（死字段）、Charles 用 `applyTo`（活字段），字段集合不同。
- **条件评估器**：**中**。Charles 是 Cline 超集，扩展了 `applyTo`/`mode`/`enabled`，但 Cline 的 `paths` Charles 也支持。
- **YAML schema**：**中-低**。Cline JSON_SCHEMA vs Charles safe_load，对边界值行为不同。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.1.1 | frontmatter 存在 | 是（sdk/AGENTS.md L1-5） | 是（agent_config/rules/AGENTS.md L1-5） | 高 | 已对齐。双方 AGENTS.md 均以 `---` 开头的 YAML frontmatter 块 |
| 6.1.2 | description 字段 | 是（`description: Development reference for the Cline SDK workspace.`） | 是（`description: Charles 投研情报官主规则 — 所有模式和业务场景下常驻应用`） | 高 | 已对齐。双方均用 `description` 作为规则描述字段 |
| 6.1.3 | globs 字段 | 是（`globs: "*.ts,*.tsx,*.js,*.jsx,*.json,*.md"`，但 `rule-conditionals.ts` **不评估** `globs`，仅评估 `paths`） | 无 | 中 | Charles 缺失 `globs`。但需注意：Cline 的 `globs` 是**未评估的死字段**，Cline 真正用于路径过滤的字段是 `paths`。Charles rules_loader.py 支持 `paths`（与 Cline 评估器对齐），只是 AGENTS.md 未使用 |
| 6.1.4 | applyTo 字段 | **否**（Cline AGENTS.md 示例**无此字段**；`rule-conditionals.ts` 评估器**不识别** `applyTo`。计划表标注"Cline: 是"有误） | 是（`applyTo: [act, plan]`，被 `rules_loader.py` L458-463 的 `_evaluate_apply_to_conditional` 评估） | 中 | Charles 自定义扩展。Cline 无 agent 模式过滤概念，Charles 扩展了 `applyTo` 实现 act/plan 模式过滤。**计划表 6.1.4 标注"Cline: 是 / 已对齐"是事实错误** |
| 6.1.5 | alwaysApply 字段 | 是（`alwaysApply: true`，但**不被评估器评估**，纯文档元数据） | 是（`alwaysApply: true`，同样**不被 rules_loader.py 评估**，纯文档元数据） | 高 | 已对齐（双方均为未评估元数据）。Charles 的"常驻"语义实际由 `applyTo: [act, plan]` 覆盖所有模式实现，`alwaysApply` 是冗余字段 |
| 6.1.6 | frontmatter 分隔符 | `---`（frontmatter.ts L44 正则 `^---\r?\n...`） | `---`（rules_loader.py L51 正则 `^---\r?\n...`） | 高 | 完全一致。双方均用三横线 `---` 作为 YAML frontmatter 起止边界 |
| 6.1.7 | frontmatter 解析 | `parseYamlFrontmatter`（frontmatter.ts L38-58），正则 `/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/`，`yaml.load(content, { schema: yaml.JSON_SCHEMA })` | `parse_yaml_frontmatter`（rules_loader.py L131-181），正则 `r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$"`，`yaml.safe_load(content)` | 中-高 | 正则**逐字符完全相同**。差异：YAML schema 不同（Cline JSON_SCHEMA 严格、Charles safe_load 宽松）；顶层类型校验 Charles 更严格（显式 isinstance dict 检查，Cline 仅类型断言） |
| 6.1.8 | frontmatter 移除 | 正则 match group(2) 作为 `body` 返回（frontmatter.ts L51 `[yamlContent, body] = match`） | 正则 match group(2) 作为 `body` 返回（rules_loader.py L157 `yaml_content, body = match.group(1), match.group(2)`） | 高 | 完全一致。双方均用正则第二捕获组作为去 frontmatter 后的正文 |

---

## 三、重点差距详解

### 3.1 计划文件 P6.1 的事实错误（必须修正）

AGENT_COMPARISON_PLAN_V2.md L2243-2250 给出的 Cline frontmatter 参考包含 `applyTo: [act, plan]`，并据此在 L2266 的对比表中标注 6.1.4 为"Cline: 是 / 已对齐"。

**实际 Cline 源码核实结果**：

| 字段 | Cline sdk/AGENTS.md 实际 | Cline sdk/packages/llms/AGENTS.md 实际 | Cline rule-conditionals.ts 评估器 | 计划表声明 |
|------|-------------------------|----------------------------------------|-----------------------------------|-----------|
| description | 有 | 有 | 不评估（元数据） | "是" ✓ |
| globs | 有 | 有 | **不评估**（仅评估 `paths`） | "是"（但未说明是死字段） |
| applyTo | **无** | **无** | **不识别** | "是" ✗（虚构） |
| alwaysApply | 有 | 有 | **不评估** | "是" ✓ |

**修正建议**：计划表 6.1.4 应改为"Cline: 否（无此字段）/ Charles: 是（自定义扩展）/ 关键差异：Charles 扩展"。

### 3.2 globs vs paths 字段命名陷阱

这是本阶段最易误判的点：

- **Cline AGENTS.md 示例**用 `globs` 作为 frontmatter 键（`globs: "*.ts,*.tsx,..."`）
- **Cline 评估器**（rule-conditionals.ts L74-76）只识别 `paths`，不识别 `globs`
- 因此 Cline 自己 AGENTS.md 里的 `globs` 字段是**写但不读的死字段**

```typescript
// rule-conditionals.ts L74-76
const conditionalEvaluators: Record<string, ConditionalEvaluatorWithMatch> = {
    paths: evaluatePathsConditional,   // 仅 paths，无 globs
}
```

Charles 的处理更一致：`rules_loader.py` L474 评估 `paths`（与 Cline 评估器字段名对齐），AGENTS.md 未使用 `globs`（避免死字段）。Charles 在这一点上**比 Cline 自身更自洽**。

### 3.3 YAML schema 差异（边界值行为不同）

| 输入值 | Cline (JSON_SCHEMA) | Charles (safe_load) | 影响 |
|--------|---------------------|---------------------|------|
| `alwaysApply: true` | bool `true` | bool `True` | 无（JSON 兼容） |
| `alwaysApply: yes` | str `"yes"` | bool `True` | **有差异** |
| `enabled: no` | str `"no"` | bool `False` | **有差异** |
| `applyTo: [act, plan]` | `["act","plan"]` | `["act","plan"]` | 无（JSON 兼容） |
| `description: foo` | str `"foo"` | str `"foo"` | 无 |

当前双方 AGENTS.md frontmatter 均使用 JSON 兼容值（`true`/列表/字符串），故**实际无运行时差异**。但若未来有人写 `alwaysApply: yes`，Cline 解析为字符串（条件评估时 `enabled is False` 判断失效），Charles 解析为布尔（行为符合预期）。Charles 的 safe_load 在此场景更宽松。

### 3.4 顶层类型校验差异

**Charles（rules_loader.py L163-170）**：
```python
data = yaml.safe_load(yaml_content) or {}
if not isinstance(data, dict):
    # 顶层非 dict 视为解析失败，fail-open
    return FrontmatterParseResult(
        body=normalized, had_frontmatter=True,
        parse_error=f"frontmatter top-level must be a mapping, got {type(data).__name__}",
    )
```

**Cline（frontmatter.ts L52-54）**：
```typescript
const data = (yaml.load(yamlContent, { schema: yaml.JSON_SCHEMA }) as Record<string, unknown>) || {}
return { data, body, hadFrontmatter: true }
```

Cline 的 `as Record<string, unknown>` 是 TypeScript 编译期类型断言，**运行时无校验**。若 YAML 内容为 `- foo\n- bar`（顶层 list），Cline 会将 list 作为 `data` 返回，后续 `Object.entries(frontmatter)` 在 `evaluateRuleConditionals` 中会遍历 list 索引（潜在 bug）。Charles 显式校验并 fail-open，**更健壮**。

### 3.5 条件评估器范围对比

| 评估字段 | Cline rule-conditionals.ts | Charles rules_loader.py | 说明 |
|---------|---------------------------|------------------------|------|
| `paths` | ✓（L39-72 `evaluatePathsConditional`，用 picomatch） | ✓（L336-366 `_evaluate_paths_conditional`，用 wcmatch/正则回退） | 双方均支持。Charles P7.1 已对齐 picomatch 语义 |
| `applyTo` | ✗（不识别） | ✓（L369-400 `_evaluate_apply_to_conditional`） | Charles 扩展（agent 模式过滤） |
| `mode` | ✗（不识别） | ✓（L403-430 `_evaluate_business_mode_conditional`） | Charles 扩展（业务模式过滤） |
| `enabled` | ✗（不识别） | ✓（L453-455 `enabled` 开关） | Charles 扩展（显式禁用开关） |
| `globs` | ✗（不识别，AGENTS.md 写但评估器忽略） | ✗（不识别） | 双方均不评估。Cline AGENTS.md 有此字段（死字段），Charles 无 |
| `alwaysApply` | ✗（不识别） | ✗（不识别） | 双方均不评估。双方 AGENTS.md 均有此字段（死字段） |

Charles 的条件评估器是 Cline 的**严格超集**：Cline 支持的 `paths` Charles 完全支持；Charles 额外支持 `applyTo`/`mode`/`enabled` 三个业务扩展字段。

### 3.6 Charles AGENTS.md 的"常驻"语义来源

Charles AGENTS.md frontmatter：
```yaml
---
description: Charles 投研情报官主规则 — 所有模式和业务场景下常驻应用
applyTo: [act, plan]
alwaysApply: true
---
```

实际生效路径分析：
- `alwaysApply: true` → **不被评估**（rules_loader.py 无此字段处理逻辑），纯文档说明
- `applyTo: [act, plan]` → **被评估**（`_evaluate_apply_to_conditional` L398 检查 `context.agent_mode in patterns`），act/plan 覆盖所有 agent 模式，故"常驻"
- description 文案"所有模式和业务场景下常驻应用"中的"业务场景"对应 `mode` 字段，但 AGENTS.md **未写 `mode` 字段** → `mode` 省略 → `_evaluate_business_mode_conditional` L416 返回 `True`（无条件通过）→ 对所有业务模式生效

结论：Charles AGENTS.md 的"常驻"语义由 `applyTo: [act, plan]`（覆盖 agent 模式）+ `mode` 省略（覆盖业务模式）共同实现，`alwaysApply: true` 是**冗余的文档装饰**。这与 Cline AGENTS.md 的 `alwaysApply: true`（同样是死字段）行为一致——双方都靠"不写路径/模式限定字段"实现常驻，而非靠 `alwaysApply` 字段。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.1 范围内仅涉及以下 2 个文件：
- `agent_config/rules/AGENTS.md`（56 行）
- `agent/rules_loader.py`（1053 行）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent_config/rules/AGENTS.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样（case-insensitive 搜索）。frontmatter 与正文均为 Charles 原生设计 |
| `agent/rules_loader.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 与注释均对标 Cline（"对标 Cline frontmatter.ts" / "对标 Cline parseYamlFrontmatter" / "对标 Cline evaluateRuleConditionals"），无 nanobot 对标引用 |

**P6.1 范围内 nanobot 残留总计：0 处（注释 0 + 实现逻辑 0）。**

### 4.3 范围外残留说明

以下文件的 nanobot 残留**超出 P6.1 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1（已记录） |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20（已审计） |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20（已审计） |
| `agent/skills/skill_tool.py` L18 | 注释残留 | "nanobot 子 agent 隔离执行"对比说明 | P4.x |
| `agent/providers/qwen.py` 多处 | 注释残留 | 对标 nanobot openai_compat_provider | P1.x |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |

---

## 五、修复建议

### 5.1 高优先级：修正计划文件事实错误

**问题**：AGENT_COMPARISON_PLAN_V2.md L2243-2250 的 Cline frontmatter 参考包含 `applyTo: [act, plan]`，L2266 对比表 6.1.4 标注"Cline: 是 / 已对齐"。

**修复**：将 L2243-2250 的 Cline frontmatter 参考改为（基于 sdk/AGENTS.md 实际内容）：
```yaml
---
description: <规则描述>
globs: "*.ts,*.tsx,*.js,*.jsx,*.json,*.md"
alwaysApply: true
---
```
将 L2266 对比表 6.1.4 改为：

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.1.4 | applyTo 字段 | 否（无此字段，评估器不识别） | 是（自定义扩展，被评估） | Charles 扩展（Cline 无 agent 模式过滤概念） |

同时建议在 6.1.3 备注说明"Cline `globs` 字段未被评估器评估（死字段），Cline 真正评估的路径字段是 `paths`"。

### 5.2 中优先级：Charles AGENTS.md `alwaysApply` 字段语义澄清

**问题**：Charles AGENTS.md 的 `alwaysApply: true` 是不被评估的死字段，可能误导维护者认为"常驻由 alwaysApply 控制"。实际常驻由 `applyTo: [act, plan]` + `mode` 省略实现。

**修复建议（可选，非必须）**：在 AGENTS.md frontmatter 上方或 rules_loader.py docstring 中补充注释说明"`alwaysApply` 为文档元数据，实际激活由 `applyTo`/`mode`/`paths` 条件评估决定"。或移除 `alwaysApply` 字段以避免歧义（但会与 Cline AGENTS.md 字段集合不一致）。

**权衡**：保留 `alwaysApply` 可保持与 Cline AGENTS.md 的字段集合相似度（双方都有此死字段），但需文档澄清；移除则更干净但牺牲字段对齐。建议**保留 + 文档澄清**。

### 5.3 低优先级：YAML schema 对齐（不建议修改）

**问题**：Cline 用 `yaml.JSON_SCHEMA`（严格），Charles 用 `yaml.safe_load`（宽松）。对当前 frontmatter 值无实际影响，但对未来边界值（`yes`/`no`/`null`）行为不同。

**修复建议**：**不建议修改**。Charles 的 `safe_load` 更符合 Python 生态惯例，且 Charles 对 `enabled: yes` 等值的解析更符合用户直觉。Cline 的 `JSON_SCHEMA` 是 TypeScript/Node 生态的选择，Python 生态无需跟随。此差异属合理的语言生态差异，非差距。

### 5.4 低优先级：顶层类型校验（Charles 已优于 Cline）

**问题**：Cline `parseYamlFrontmatter` 无运行时 dict 校验（仅类型断言），Charles 显式校验。

**修复建议**：**无需修改**。Charles 在此点已优于 Cline，无需降级对齐。保留 Charles 的更健壮实现。

---

## 六、验证方法

### 6.1 frontmatter 字段对比验证

1. 读取 Cline `sdk/AGENTS.md` L1-5，确认 frontmatter 字段为 `description` / `globs` / `alwaysApply`（无 `applyTo`）
2. 读取 Cline `sdk/packages/llms/AGENTS.md` L1-5，确认同样字段集合
3. 读取 Charles `agent_config/rules/AGENTS.md` L1-5，确认 frontmatter 字段为 `description` / `applyTo` / `alwaysApply`（无 `globs`）
4. Grep Cline 代码库 `applyTo`（排除 `applyToStartSessionInput`），确认无 frontmatter `applyTo` 字段使用

### 6.2 frontmatter 解析器对比验证

1. 对比 Cline `frontmatter.ts` L44 正则与 Charles `rules_loader.py` L51 正则，确认逐字符相同
2. 对比 BOM 处理：Cline `stripUtf8Bom`（L42）vs Charles `_UTF8_BOM` 常量剥离（L149-151）
3. 对比 fail-open 策略：Cline L47-48（无 match 返回原文）+ L55-57（解析失败返回原文）vs Charles L154-155（无 match）+ L176-181（解析失败）

### 6.3 条件评估器对比验证

1. 读取 Cline `rule-conditionals.ts` L74-76，确认 `conditionalEvaluators` 仅注册 `paths`
2. 读取 Charles `rules_loader.py` L433-481，确认 `evaluate_rule_conditionals` 评估 `enabled`/`applyTo`/`mode`/`paths` 四个字段
3. 确认双方均不评估 `globs`/`alwaysApply`

### 6.4 nanobot 残留验证

1. Grep `agent_config/rules/AGENTS.md` 搜索 `nanobot`（case-insensitive），确认 0 匹配
2. Grep `agent/rules_loader.py` 搜索 `nanobot`（case-insensitive），确认 0 匹配

### 6.5 计划文件错误验证

1. 读取 `AGENT_COMPARISON_PLAN_V2.md` L2243-2250，确认其 Cline frontmatter 参考包含 `applyTo: [act, plan]`
2. 对比 Cline `sdk/AGENTS.md` 实际 frontmatter，确认无 `applyTo` 字段
3. 确认计划表 6.1.4（L2266）标注"Cline: 是 / 已对齐"与实际不符

---

## 七、附录

### 7.1 Cline sdk/AGENTS.md frontmatter 实际内容

```yaml
---
description: Development reference for the Cline SDK workspace.
globs: "*.ts,*.tsx,*.js,*.jsx,*.json,*.md"
alwaysApply: true
---
```

### 7.2 Charles agent_config/rules/AGENTS.md frontmatter 实际内容

```yaml
---
description: Charles 投研情报官主规则 — 所有模式和业务场景下常驻应用
applyTo: [act, plan]
alwaysApply: true
---
```

### 7.3 双方 frontmatter 字段集合 Venn 图

```
Cline AGENTS.md 字段集合        Charles AGENTS.md 字段集合
┌─────────────────────┐        ┌─────────────────────┐
│ description         │        │ description         │
│ globs     (死字段)  │        │ applyTo   (活字段)  │
│ alwaysApply(死字段) │        │ alwaysApply(死字段) │
└─────────────────────┘        └─────────────────────┘
        │                              │
        └────────交集──────────────────┘
         description / alwaysApply

Cline 独有: globs (AGENTS.md 写但评估器不读)
Charles 独有: applyTo (AGENTS.md 写且评估器读)
双方共有死字段: alwaysApply (双方都写但都不评估)
```

### 7.4 双方评估器支持字段对比

```
Cline rule-conditionals.ts 评估字段:  { paths }
Charles rules_loader.py 评估字段:     { paths, applyTo, mode, enabled }

Charles = Cline ∪ { applyTo, mode, enabled }  (Charles 是严格超集)
```
