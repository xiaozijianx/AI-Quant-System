# Phase 4.7 SKILL.md 形式风格对比

> 对比范围：Cline `skills.mdx` 文档中描述的 SKILL.md 形式风格指南 + Cline 内置示例（data-analysis）与 Charles `agent_config/skills/*/SKILL.md`（8 个技能）的形式风格差异；语言风格（命令式 vs 描述式）、人称（you/we/agent）、语气、格式约定（列表 vs 段落）、标签使用、条件语句风格、错误处理说明风格 7 个维度逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/docs/customization/skills.mdx` 全文 271 行（SKILL.md 编写指南 + data-analysis 示例 + frontmatter 规范 + 章节命名建议）
> - Cline 仓库无实际 SKILL.md 示例文件（仅有文档示例）
>
> Charles 源码（8 个技能，全部位于 `agent_config/skills/`）：
> - `bond-credit-review/SKILL.md`（74 行）
> - `compare-reports/SKILL.md`（78 行）
> - `financial-analysis/SKILL.md`（111 行）
> - `read-pdf/SKILL.md`（124 行）
> - `sentiment-analysis/SKILL.md`（91 行）
> - `stock-price/SKILL.md`（65 行）
> - `web-search/SKILL.md`（75 行）
> - `write-report/SKILL.md`（104 行）
>
> 历史参考源码（用于 nanobot 残留溯源，位于 `third_party/charles_bundle/charles-nanobot/skills/`）：
> - 9 个 SKILL.md（含 biz-skill-creator，Charles 当前实现已移除该技能）

---

## 一、执行摘要

本阶段对比 Cline 文档定义的 SKILL.md 形式风格指南与 Charles 当前 8 个 SKILL.md 的实际形式风格。两者在**YAML frontmatter 必备字段（name + description）**、**kebab-case 命名**、**Markdown 结构**、**包含真实示例**等基础约定上**已对齐**。剩余差异主要体现在**风格范式取向**：Cline 走"通用、灵活、自然语言"路线（文档指南用第二人称 you，SKILL.md 正文建议短段落 + 列表混用，章节命名自由），Charles 走"领域专用、模板化、强指令"路线（无第二人称，固定 6 段式章节骨架，每 Step 用统一字段模板，专设"禁止行为"章节）。

### 核心结论

1. **基础约定完全一致**：两者均用 YAML frontmatter + Markdown 正文，`name` 用 kebab-case 且与目录名严格匹配，`description` 控制在 1024 字符内。
2. **frontmatter 字段差异**：Cline 仅规定 `name` + `description` 两字段；Charles 在此基础上**新增 `when_to_use`**（8 个技能全部含此字段，Cline 无此概念），并保留 `always: true`（read-pdf，Cline 文档未提及但 Cline 源码支持）。
3. **语言风格差异**：Cline 文档示例偏向**命令式 + 描述式混合**（"Read a sample..." / "Use when deploying..."）；Charles 当前实现偏向**结构化描述式 + 强指令式**（"本技能用于..." / "禁止..."）。
4. **人称差异**：Cline 文档指南大量使用**第二人称 you**（"You can also invoke..." / "Keep SKILL.md under 5k tokens"）；Charles 当前实现**完全不使用 you/你/我**，统一用第三人称"agent / 用户 / 本技能"。
5. **格式约定差异**：Cline 倡导"短段落 + 列表混用，章节命名自由（如 '## Error Handling' / '## Configuration'）"；Charles 采用**固定 6 段式骨架**（本技能核心能力 → 场景路由 → Workflow → 脚本角色说明 → 脚本调用规则 → 禁止行为），所有技能章节顺序完全一致。
6. **条件语句风格差异**：Cline 用叙述性条件（"If your request matches..."）；Charles 用**场景路由表 + Step 字段模板**（"何时执行 / 前置条件 / 跳过条件 / 失败处理"）。
7. **错误处理风格差异**：Cline 文档仅建议"用 '## Error Handling' 章节标题"未规定具体格式；Charles 用**箭头映射**（"网络错误 → 提示用户检查网络后重试"）+ **集中"禁止行为"章节**。
8. **nanobot 残留**：**0 处字面残留**（Grep "nanobot" 在 8 个 SKILL.md 中无匹配），**0 处 nanobot 风格结构残留**（已移除"示例对话"/"keywords"/"capabilities"/"可用脚本"表格等 nanobot 风格特征）。Charles 当前 SKILL.md 风格为**独立设计**，既不同于 Cline 通用指南，也不同于 nanobot 历史版本。

### 一致性总体评估

- **基础约定**（frontmatter + Markdown + kebab-case）：**高**
- **章节结构**：**低**（Charles 模板化 vs Cline 自由式，但 Charles 内部一致性极高）
- **语言风格**：**中**（命令式/描述式取向不同，但都符合"清晰可执行"原则）
- **人称使用**：**低**（Cline you vs Charles 第三人称，但 Charles 选择更符合中文技术文档惯例）
- **错误处理**：**中**（Charles 更系统化，Cline 更灵活）

---

## 二、逐项对比表

| # | 对比项 | Cline 风格指南 | Charles 当前实现 | 一致性等级 | 说明 |
|---|--------|---------------|------------------|-----------|------|
| 4.7.1 | frontmatter 必备字段 | `name` + `description`（skills.mdx L68-70） | `name` + `description` + `when_to_use`（8 个技能全部含三字段） | 高 | name/description 对齐；when_to_use 为 Charles 独有 |
| 4.7.2 | frontmatter 可选字段 | 无明确规定 | `always: true`（read-pdf L5） | 高 | Cline 文档未提及但 Cline 源码支持 always 字段，语义一致 |
| 4.7.3 | name 命名规范 | kebab-case，与目录名严格匹配（skills.mdx L69/L101-115） | 全部 kebab-case，全部与目录名严格匹配 | 高 | 完全一致 |
| 4.7.4 | description 长度 | ≤1024 字符（skills.mdx L70） | 最长 65 字符（financial-analysis），远低于上限 | 高 | 完全一致 |
| 4.7.5 | description 内容风格 | "action verbs + trigger phrases + 文件类型/工具/领域"（skills.mdx L121-141） | "动作 + 触发场景"（如"分析上市公司财务指标趋势...支持同行横向对比，包含CSV财务数据下载能力"） | 高 | 语义对齐，Charles 不分多句但仍含动作 + 触发场景 |
| 4.7.6 | 章节命名自由度 | 自由（建议 "## Error Handling" / "## Configuration" 等英文标题，skills.mdx L91） | 固定 6 段式中文标题（本技能核心能力 / 场景路由 / Workflow / 脚本角色说明 / 脚本调用规则 / 禁止行为） | 低 | Charles 高度模板化，Cline 高度自由。Charles 内部一致性极高（8 个技能章节顺序完全相同） |
| 4.7.7 | 章节语言 | 英文 | 中文（仅 "Workflow" 保留英文） | 低 | 本地化差异，符合 Charles 中文场景 |
| 4.7.8 | SKILL.md 大小 | <5k tokens（skills.mdx L145） | 最大 124 行（read-pdf），估算 <2k tokens | 高 | 远低于上限 |
| 4.7.9 | 语言风格 — 命令式 vs 描述式 | 命令式 + 描述式混合（"Read a sample of the file" / "Use when deploying..."） | 描述式 + 强指令式（"本技能用于..." / "禁止..." / "必须..."） | 中 | 取向不同但都清晰可执行 |
| 4.7.10 | 人称使用 | 第二人称 you（"You can also invoke..." / "Keep SKILL.md under 5k tokens"） | 第三人称（"agent 可直接调用" / "用户询问..." / "本技能用于..."） | 低 | Charles 不用 you/你/我，更符合中文技术文档惯例 |
| 4.7.11 | 语气 | 教学式/建议式（"Good names:" / "Avoid:" / "Skills transform Cline..."） | 强指令式/规则式（"禁止..." / "必须..." / 专设"禁止行为"章节） | 中 | Charles 防御性更强 |
| 4.7.12 | 格式约定 — 列表 vs 段落 | 短段落 + 列表混用（skills.mdx L91 "Use clear section headers"） | 列表为主，段落仅用于"本技能核心能力"开篇 | 中 | Charles 更结构化 |
| 4.7.13 | 表格使用 | 文档中频繁用表格（skills.mdx L19-23/L225-230）；SKILL.md 示例无表格 | 仅 write-report 用表格（五步法框架 + 五种研报场景）；其他技能无表格 | 中 | Charles 表格使用更克制 |
| 4.7.14 | 代码块使用 | 文档示例用 ```bash / ```python / ```yaml（skills.mdx L123/L216/L260） | 命令用 ```bash 代码块（所有 Step 的"命令"字段） | 高 | 完全一致 |
| 4.7.15 | 条件语句风格 | 叙述性条件（"If your request matches..." / "If your skill needs more content..."） | 场景路由表 + Step 字段模板（"何时执行 / 前置条件 / 跳过条件 / 失败处理"） | 低 | Charles 更系统化，Cline 更自然 |
| 4.7.16 | 错误处理说明风格 | 仅建议章节标题"## Error Handling"（skills.mdx L91），未规定格式 | 箭头映射（"网络错误 → 提示用户检查网络后重试"）+ 集中"禁止行为"章节 | 中 | Charles 更显式 |
| 4.7.17 | "禁止行为"章节 | 无此概念（散落在各处 Avoid/禁止） | 8 个技能全部含 `## 禁止行为` 集中章节（3-5 条禁令） | — | Charles 独有增强 |
| 4.7.18 | Step 编号风格 | `## 1. Understand the Data` / `## 2. Ask Clarifying Questions`（数字标题，skills.mdx L246/L251） | `### Step 1: 收集发行人数据` / `### Step 2: 调用信用审查脚本`（Step 前缀 + 冒号） | 中 | 编号语义一致，格式不同 |
| 4.7.19 | Step 内部结构 | 自由（示例用列表枚举子步骤） | 固定字段模板（**何时执行** / **前置条件** / **命令** / **参数** / **预期输出** / **失败处理** / **跳过条件**） | 低 | Charles 高度模板化，Cline 高度自由 |
| 4.7.20 | 示例对话 | 无"示例对话"章节（文档示例用代码块展示 SKILL.md 内容） | 无"示例对话"章节（已移除 nanobot 风格） | 高 | Charles 已清理 nanobot 风格 |
| 4.7.21 | "脚本角色说明"章节 | 无此概念（Cline 文档用 "## Bundling Supporting Files" 描述文件用途） | 8 个技能全部含 `## 脚本角色说明` 章节，区分"主脚本"和"内部脚本" | — | Charles 独有增强，对金融领域脚本调度有用 |
| 4.7.22 | "脚本调用规则"章节 | 无此概念 | 8 个技能全部含 `## 脚本调用规则` 章节（3-5 条规则） | — | Charles 独有增强 |
| 4.7.23 | 引用 bundled 文件 | `[advanced.md](docs/advanced.md)` 相对路径（skills.mdx L65/L216） | 无 docs/ 引用（Charles 用 scripts/ 子目录，无跨文件引用） | 中 | Charles 不使用 docs/ 引用模式 |
| 4.7.24 | "important information first" 原则 | 强调（skills.mdx L91 "Put the important information first"） | 遵循（"本技能核心能力"开篇即说明能力 + 工作方式 + 适用范围） | 高 | 完全一致 |
| 4.7.25 | 真实示例 | 强调（skills.mdx L147 "Include real examples"） | 部分遵循（场景路由用 "如'贵州茅台毛利率趋势'" 等真实示例；但无完整输入输出示例） | 中 | Charles 偏抽象，Cline 偏具体 |
| 4.7.26 | 进度提示 | 无此概念 | read-pdf 含 `## 终端监控说明` 章节（"前端工具卡片内会实时滚动显示终端输出"） | — | Charles 独有增强，针对本地 IDE 场景 |
| 4.7.27 | 报告期/年份规则 | 无此概念 | read-pdf 含 `## 年报年份规则` / write-report 含 `## 报告期选择规则`（明确"2025年年报指2025财年"） | — | Charles 独有增强，针对金融领域 |
| 4.7.28 | 数据源选择 | 无此概念 | read-pdf 含 `## 数据源选择` / financial-analysis 含 `## 数据来源` / compare-reports 含 `## 数据前提` | — | Charles 独有增强，针对多技能协作场景 |

---

## 三、重点差距详细说明

### 3.1 frontmatter 字段差异（4.7.1 + 4.7.2）

**Cline 规范**（skills.mdx L68-70）：

```yaml
---
name: my-skill
description: Brief description of what this skill does and when to use it.
---
```

仅规定 `name` + `description` 两字段。`description` 字段同时承担"做什么"和"何时使用"两个语义（"what this skill does and when to use it"）。

**Charles 实现**：

```yaml
---
name: financial-analysis
description: "分析上市公司财务指标趋势(毛利率/ROE/负债率等)，支持同行横向对比，包含CSV财务数据下载能力"
when_to_use: "用户询问财务指标/毛利率/ROE/负债率/营收趋势/同行对比等结构化数字时"
---
```

Charles 将 Cline 的 `description` 拆分为两个字段：
- `description`：仅描述"做什么"（动作 + 对象 + 能力）
- `when_to_use`：仅描述"何时使用"（触发场景）

**差异影响**：
- Cline 的 `description` 同时被 `use_skill` 工具的 description getter 用于技能匹配（user-instruction-plugin.ts L208-215 返回 `[{id, name, description, disabled}]`）；Charles 的 SkillsTool `_build_description()`（skill_tool.py L225-253）也仅读取 `description` 字段拼接。
- Charles 的 `when_to_use` 字段**未被 SkillsTool 实际使用**（Grep 全局确认），仅作为 SKILL.md 文档自描述。这与 Cline"全部信息塞入 description 以提升匹配率"的设计不同。
- **判定**：非 nanobot 残留（nanobot 版本无 `when_to_use` 字段），属于 Charles 独立设计。

**`always: true` 字段**：
- Cline 文档（skills.mdx）未提及 `always` 字段，但 Cline 源码 `user-instruction-plugin.ts` 中 `SkillsExecutorSkillMetadata` 类型支持 `alwaysOn` 概念（用于 always-on skills）。
- Charles `read-pdf/SKILL.md` L5 保留 `always: true`，`stock-price/SKILL.md`（charles-nanobot 版本）也曾有此字段但 Charles 当前实现已移除。
- **判定**：`always` 字段为 Cline/nanobot 共有概念，Charles 保留 1 处（read-pdf），非残留。

### 3.2 章节结构差异（4.7.6 + 4.7.19）

**Cline 风格**：自由式。文档建议"Use clear section headers like '## Error Handling' or '## Configuration' so Cline can scan for relevant sections"（skills.mdx L91），但未规定具体章节列表。data-analysis 示例仅用 `## 1. Understand the Data` / `## 2. Ask Clarifying Questions` / `## 3. Perform Analysis` 三个数字标题。

**Charles 风格**：固定 6 段式骨架。8 个技能章节顺序完全一致：

| 顺序 | 章节标题 | 出现频率 |
|------|---------|---------|
| 1 | `## 本技能核心能力` | 8/8 |
| 2 | `## 场景路由` | 8/8 |
| 3 | `## Workflow` | 8/8 |
| 4 | `## 脚本角色说明` | 8/8 |
| 5 | `## 脚本调用规则` | 8/8 |
| 6 | `## 禁止行为` | 8/8 |
| 附加 | `## 数据来源` / `## 数据前提` / `## 数据源选择` / `## 年报年份规则` / `## 终端监控说明` / `## 报告期选择规则` | 按需 |

**Step 内部结构**也高度模板化：

```markdown
### Step N: <动作描述>

- **何时执行**: <触发条件>
- **前置条件**: <依赖条件>
- **跳过条件**: <可选，跳过分支>
- **命令**:
  ```bash
  python agent_config/skills/<skill>/scripts/<script>.py <args>
  ```
- **参数**:
  - `--xxx` (必填): <说明>
  - `--yyy` (可选): <说明>
- **预期输出**: <输出描述>
- **成功处理**: <可选，成功分支>
- **失败处理**:
  - <错误1> → <应对1>
  - <错误2> → <应对2>
```

**差异影响**：
- Charles 模板化设计**优势**：内部一致性极高，agent 加载新技能时心智负担低，易于维护。
- Charles 模板化设计**劣势**：灵活性低，不适合 Cline 通用场景（如纯指令型技能、无脚本技能）。
- Cline 自由式设计**优势**：适应各种技能形态（指令型、脚本型、文档型）。
- Cline 自由式设计**劣势**：跨技能一致性低，agent 需要每次重新理解章节布局。
- **判定**：风格取向差异，非缺陷。Charles 模板化更适合其金融领域专用场景。

### 3.3 人称差异（4.7.10）

**Cline 文档指南**：大量使用第二人称 you：

- "You can also invoke enabled skills..."（skills.mdx L29）
- "You can also create skills manually..."（skills.mdx L89）
- "Put the important information first in your SKILL.md"（skills.mdx L91）
- "Keep SKILL.md under 5k tokens"（skills.mdx L145）
- "Include real examples"（skills.mdx L147）

**Cline SKILL.md 示例正文**（data-analysis）：不直接用人称，用"ask the user"等动词短语。

**Charles 当前实现**：**完全不使用 you/你/我**。统一用：

- 第三人称"agent"："agent 可直接调用" / "agent 不要直接调用" / "agent 自主决策"
- 第三人称"用户"："用户询问..." / "用户明确要求下载时" / "用户意图"
- 自指"本技能"："本技能用于..." / "本技能是查询股价的唯一正确途径"
- 无人称陈述句："禁止..." / "必须..." / "执行 Step 1"

**差异影响**：
- Cline you 风格更亲切、教学式，适合面向开发者编写 SKILL.md 的文档场景。
- Charles 第三人称风格更客观、规则式，适合面向 agent 执行的指令场景。
- 中文技术文档惯例本就不用"你/我"，Charles 选择符合本地化习惯。
- **判定**：风格取向差异，非缺陷。

### 3.4 条件语句风格差异（4.7.15）

**Cline 风格**：叙述性条件，散落在正文中：

- "If your request matches a skill's description, Cline activates it..."（skills.mdx L25）
- "If your skill needs more content, split it into separate files..."（skills.mdx L145）
- "When you send a message, Cline sees a list of available skills..."（skills.mdx L25）

**Charles 风格**：场景路由表 + Step 字段模板。

**场景路由**章节示例（financial-analysis）：

```markdown
## 场景路由

根据用户意图选择执行路径:

- **用户询问单股财务指标**（如"贵州茅台毛利率趋势"）: 执行 Step 1（检查本地）→ 有数据直接 Step 3（计算指标）/ 无数据 Step 2（下载）→ Step 3
- **用户明确要求下载财务数据**（如"帮我下载贵州茅台财务数据"）: 跳过 Step 1，直接 Step 2（下载）
- **用户要求同行对比**（如"贵州茅台和五粮液对比"）: 执行 Step 1（检查本地，多家公司都要检查）→ 有数据直接 Step 4（同行对比）/ 无数据 Step 2（下载缺失的）→ Step 4
- **用户只需要同行对比不需要单股指标**: 可跳过 Step 3，直接 Step 4（前提是本地已有数据）
```

**Step 字段**示例（financial-analysis Step 1）：

```markdown
- **何时执行**: 用户询问财务指标或同行对比时，首先检查本地数据
- **前置条件**: 无（直接检查，不要假设本地有数据）
- **检查方式**: 用 `read_files` 读取 `data/financial_data/{股票代码}_financial_abstract.csv`
- **预期输出**: CSV 文件内容（财务摘要表格）
- **成功处理**: 若文件存在，跳过 Step 2，直接进入 Step 3 计算指标或 Step 4 同行对比
- **失败处理**: 若文件不存在，进入 Step 2 下载
```

**差异影响**：
- Charles 场景路由表**优势**：所有条件分支集中展示，agent 决策时一目了然。
- Charles Step 字段模板**优势**：每个 Step 的"何时/前置/跳过/失败"四要素齐备，无遗漏。
- Cline 叙述性条件**优势**：自然流畅，适合简单技能。
- Cline 叙述性条件**劣势**：复杂分支容易遗漏边界条件。
- **判定**：Charles 风格更严谨，Cline 风格更自然。两者都符合"清晰可执行"原则。

### 3.5 错误处理说明风格差异（4.7.16 + 4.7.17）

**Cline 风格**：文档仅建议"Use clear section headers like '## Error Handling'"（skills.mdx L91），未规定具体格式。data-analysis 示例无错误处理章节。

**Charles 风格**：双层错误处理说明。

**第一层 — Step 内"失败处理"字段**（箭头映射）：

```markdown
- **失败处理**:
  - 网络错误 → 提示用户检查网络后重试
  - 股票代码不存在 → 提示用户确认代码
```

8 个技能中共 7 个使用此格式（bond-credit-review Step 2 无失败处理字段，因其不调用网络脚本）。

**第二层 — 集中"禁止行为"章节**：

8 个技能全部含 `## 禁止行为` 章节，3-5 条禁令。示例（read-pdf）：

```markdown
## 禁止行为

- 禁止假设本地一定有 `data/vector_store/` 索引或 PDF 文件
- 禁止因为没有数据就放弃或编造数据
- 禁止先用 `read_files` 去读取不确定存在的本地文件来"验证"数据是否存在
- 禁止跳过 Step 1 直接执行 Step 2（除非用户明确要求下载）
- 禁止直接调用 `parse_pdf_basic.py`、`parse_pdf_ocr.py`、`build_index.py` 等内部脚本
```

**差异影响**：
- Charles 双层错误处理**优势**：Step 内应对具体错误，章节级禁令防止 agent 误操作。
- Charles 双层错误处理**劣势**：部分禁令重复（如"禁止假设本地一定有数据"在 Step 失败处理和禁止行为章节都出现）。
- Cline 单层错误处理**优势**：简洁，避免重复。
- Cline 单层错误处理**劣势**：易遗漏边界条件。
- **判定**：Charles 风格更防御性强，适合其金融领域高一致性要求场景。

### 3.6 nanobot 风格特征清理情况

对比 charles-nanobot 历史版本与 Charles 当前实现，确认以下 nanobot 风格特征已全部清理：

| nanobot 风格特征 | nanobot 版本（9 个技能） | Charles 当前版本（8 个技能） | 清理状态 |
|-----------------|------------------------|----------------------------|---------|
| `keywords` frontmatter 字段 | 7/9 技能含此字段 | 0/8 | **已清理** |
| `capabilities` frontmatter 字段 | 7/9 技能含此字段 | 0/8 | **已清理** |
| `## 示例对话` 章节 | 7/9 技能含此章节 | 0/8 | **已清理** |
| `## 可用脚本` 表格 | 7/9 技能含此表格 | 0/8（改为 `## 脚本角色说明`） | **已清理** |
| `## 前提条件` / `## 前置条件` 独立章节 | 4/9 技能含此章节 | 0/8（改为 Step 内"前置条件"字段） | **已清理** |
| `## 依赖技能` 章节 | 1/9（sentiment-analysis） | 0/8 | **已清理** |
| `## 关键词过滤体系` 章节 | 1/9（sentiment-analysis） | 0/8 | **已清理** |
| `biz-skill-creator` 技能 | 1 个 | 0 个 | **已清理**（技能本身移除） |
| `preprocess.py` 引用 | 多处（read-pdf/compare-reports） | 0 处（SKILL.md 中无引用，仅 scripts 内部调用） | **已清理** |
| `## 关键要求` 章节 | 1/9（write-report） | 0/8（拆分为"## 本技能核心能力"和 Step 内"关键要求"字段） | **已清理** |
| `## 操作流程` 章节 | 1/9（bond-credit-review） | 0/8（改为 `## Workflow`） | **已清理** |
| `## 关键规则` 章节 | 1/9（bond-credit-review） | 0/8（改为 `## 禁止行为` + `## 脚本调用规则`） | **已清理** |
| `## 参考文档` 章节 | 1/9（bond-credit-review） | 0/8 | **已清理** |
| `## 国泰君安"五步法"框架` 表格 | 1/9（write-report） | 0/8（改为 Step 2 内嵌说明） | **已清理** |

**保留的 nanobot 风格特征**（已重新设计，非残留）：

| 特征 | nanobot 版本 | Charles 当前版本 | 保留原因 |
|------|-------------|-----------------|---------|
| `always: true` frontmatter 字段 | stock-price + read-pdf | read-pdf（1 处） | Cline 源码也支持 always-on 概念，非 nanobot 独有 |
| `## 适用场景` 章节 | 7/9 技能 | 0/8（改为 `## 本技能核心能力` 含"适用范围"子项） | 已重新设计，非保留 |
| Step 编号 | 无统一编号 | `### Step 1:` / `### Step 2:` 等 | Charles 独立设计 |

---

## 四、nanobot 残留专项检查

### 4.1 字面残留（0 处）

Grep 搜索 `nanobot`（不区分大小写）在 `agent_config/skills/` 目录下：

```
Grep -i "nanobot" e:\jikeAI\code\CASE-AI量化系统\agent_config\skills
→ No matches found
```

**8 个 SKILL.md 文件均无 "nanobot" 字面残留**。此结果与 Phase 4.1 中 `agent/skills/` Python 模块的 15 处注释残留形成对比——SKILL.md 内容文件已完全清理 nanobot 关键词，而 Python 代码注释中仍保留"对标 nanobot"等说明。

### 4.2 风格结构残留（0 处）

逐项核查 nanobot 历史版本的标志性风格特征：

| 检查项 | nanobot 风格 | Charles 当前风格 | 残留判定 |
|--------|-------------|-----------------|---------|
| `keywords` frontmatter 字段 | 有 | 无（8/8 移除） | **无残留** |
| `capabilities` frontmatter 字段 | 有 | 无（8/8 移除） | **无残留** |
| `## 示例对话` 章节 | 有（"用户: ..."格式） | 无（8/8 移除） | **无残留** |
| `## 可用脚本` 表格 | 有（"脚本 / 功能 / 参数"三列） | 无（改为 `## 脚本角色说明` 列表） | **无残留** |
| `## 依赖技能` 章节 | 有（sentiment-analysis 引用 read-pdf/write-report） | 无 | **无残留** |
| `## 前提条件` 独立章节 | 有 | 无（改为 Step 内"前置条件"字段） | **无残留** |
| `preprocess.py` 引用 | 多处 | 无（SKILL.md 中无引用） | **无残留** |
| `biz-skill-creator` 技能 | 有 | 无（技能本身移除） | **无残留** |

### 4.3 实现逻辑残留（0 处）

| 检查项 | nanobot 实现 | Charles 实现 | 残留判定 |
|--------|-------------|-------------|---------|
| 子 agent 创建 | nanobot SkillsLoader 不创建子 agent | Charles SkillsTool 不创建子 agent（对齐 Cline） | **无残留** |
| `keywords` 字段读取逻辑 | nanobot frontmatter 解析 keywords | Charles loader.py 不解析 keywords（仅解析 name/description/when_to_use/always/disabled） | **无残留** |
| `capabilities` 字段读取逻辑 | nanobot frontmatter 解析 capabilities | Charles loader.py 不解析 capabilities | **无残留** |
| `## 示例对话` 渲染逻辑 | nanobot 将示例对话作为 SKILL.md 正文一部分 | Charles 当前 SKILL.md 无此章节 | **无残留** |

### 4.4 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 字面残留（"nanobot" 关键词） | 0 处 | — | 无需处理 |
| 风格结构残留（nanobot 标志性特征） | 0 处 | — | 无需处理 |
| 实现逻辑残留 | 0 处 | — | 无需处理 |

**SKILL.md 文件层面 nanobot 残留完全清理**。与 Phase 4.1 发现的 Python 代码注释残留（15 处）形成对比：SKILL.md 作为面向 agent 的内容文件，已在历史重构中完全脱离 nanobot 风格；Python 代码作为面向开发者的实现文件，仍保留"对标 nanobot"溯源注释。

---

## 五、修复建议

### 5.1 高优先级（P1）

无。SKILL.md 形式风格无阻塞性问题。

### 5.2 中优先级（P2）

1. **`when_to_use` 字段使用对齐**（8 个 SKILL.md）：
   - 当前 `when_to_use` 字段仅作为 SKILL.md 自描述，未被 SkillsTool `_build_description()` 读取。
   - 建议 Charles SkillsTool 在 `_build_description()`（skill_tool.py L225-253）中将 `when_to_use` 拼接到工具 description 中，提升 LLM 技能匹配率。当前 LLM 看到的 description 仅含 `description` 字段，可能错过 `when_to_use` 中的触发场景关键词。
   - 或考虑合并 `description` + `when_to_use` 为单字段（对齐 Cline "what + when" 一体设计），减少冗余。

2. **Step 内"失败处理"字段补全**（bond-credit-review Step 2）：
   - bond-credit-review Step 2（L39-50）无"失败处理"字段，建议补充：
     - `债券代码不存在 → 提示用户确认代码`
     - `数据缺失 → 回到 Step 1 补充数据收集`

### 5.3 低优先级（P3）

3. **章节命名本地化一致性**（8 个 SKILL.md）：
   - 当前 `## Workflow` 保留英文，其他章节用中文。可考虑改为 `## 工作流程` 或保留英文但统一所有章节为英文。当前混用不影响功能，但风格一致性略低。

4. **"禁止行为"与 Step 失败处理去重**（部分技能）：
   - 部分技能的"禁止行为"章节与 Step 内"失败处理"字段有语义重叠（如"禁止假设本地一定有数据" vs "失败处理：若文件不存在，进入 Step 2 下载"）。可保留重叠（防御性设计），或合并以减少冗余。

5. **真实完整示例补充**（针对简单技能）：
   - Cline 强调"Include real examples"（skills.mdx L147），Charles 场景路由中虽有用 "如'贵州茅台毛利率趋势'" 等触发示例，但无完整输入 → 命令 → 输出示例。可考虑在 `## 脚本调用规则` 章节后增加 `## 完整示例` 章节（不必恢复 nanobot 的"示例对话"格式，可用"输入 → 命令 → 输出"三段式）。当前无此需求可暂不实现。

6. **`always: true` 字段使用澄清**（read-pdf L5）：
   - read-pdf 保留 `always: true`，stock-price 在 charles-nanobot 版本曾有此字段但 Charles 当前已移除。建议确认 always-on 技能的选取标准（为何 read-pdf always 但 stock-price 不 always），并在 SKILL.md 编写规范中说明。

---

## 六、验证方法建议

### 6.1 frontmatter 字段验证

```python
import os
import yaml

skills_dir = "agent_config/skills"
for skill_name in os.listdir(skills_dir):
    skill_md = os.path.join(skills_dir, skill_name, "SKILL.md")
    if not os.path.exists(skill_md):
        continue
    with open(skill_md, encoding="utf-8") as f:
        content = f.read()
    # 提取 frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        frontmatter = yaml.safe_load(content[3:end])
        assert "name" in frontmatter, f"{skill_name}: missing name"
        assert frontmatter["name"] == skill_name, f"{skill_name}: name mismatch"
        assert "description" in frontmatter, f"{skill_name}: missing description"
        assert len(frontmatter["description"]) <= 1024, f"{skill_name}: description too long"
        # Charles 独有字段
        assert "when_to_use" in frontmatter, f"{skill_name}: missing when_to_use"
```

### 6.2 章节结构一致性验证

```python
expected_sections = [
    "## 本技能核心能力",
    "## 场景路由",
    "## Workflow",
    "## 脚本角色说明",
    "## 脚本调用规则",
    "## 禁止行为",
]

for skill_name in os.listdir(skills_dir):
    # ... 读取 SKILL.md
    for section in expected_sections:
        assert section in content, f"{skill_name}: missing section {section}"
```

### 6.3 nanobot 残留验证

```bash
# 字面残留
Grep -i "nanobot" agent_config/skills/
# 预期：No matches found

# 风格结构残留
Grep "^(keywords|capabilities):" agent_config/skills/
# 预期：No matches found

Grep "## 示例对话|## 可用脚本|## 依赖技能|## 前提条件" agent_config/skills/
# 预期：No matches found
```

### 6.4 人称使用验证

```python
# Charles 当前实现不应使用 you/你/我
for skill_name in os.listdir(skills_dir):
    # ... 读取 SKILL.md
    # Cline 文档用 you，Charles 不用
    assert " you " not in content.lower(), f"{skill_name}: contains 'you'"
    # 中文"你/我"也不应出现（除了"用户"中的"户"）
    # 注意：此验证较严格，可放宽
```

---

## 七、附录：8 个 Charles SKILL.md 章节结构汇总

| 技能 | 行数 | 固定 6 段 | 附加章节 |
|------|------|----------|---------|
| bond-credit-review | 74 | ✓ | — |
| compare-reports | 78 | ✓ | `## 数据前提` |
| financial-analysis | 111 | ✓ | `## 数据来源` |
| read-pdf | 124 | ✓ | `## 年报年份规则` / `## 数据源选择` / `## 终端监控说明` |
| sentiment-analysis | 91 | ✓ | — |
| stock-price | 65 | ✓ | — |
| web-search | 75 | ✓ | — |
| write-report | 104 | ✓ | `## 报告期选择规则` |

所有 8 个技能均包含完整的固定 6 段式骨架（本技能核心能力 / 场景路由 / Workflow / 脚本角色说明 / 脚本调用规则 / 禁止行为），附加章节按需添加，章节顺序完全一致。
