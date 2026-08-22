# Phase 6.5 AGENTS.md 措辞风格对比

> 对比范围：Cline `sdk/AGENTS.md`（主 workspace 级，109 行）+ `sdk/packages/llms/AGENTS.md`（子包级，39 行）与 Charles `agent_config/rules/AGENTS.md`（56 行）的措辞风格（命令式 vs 描述式）、人称、语气、格式约定（标题层级 / 代码块 / 表格 / 列表）；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md` L1-109（frontmatter + 6 个 ## 段落 + 2 个 ### 子段落 + ```mermaid 图 + ```sh 命令块）
> - `third_party/cline/sdk/packages/llms/AGENTS.md` L1-39（frontmatter + 1 个 ## 段落 + ```text 代码块）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md` L1-56（frontmatter + 1 个 # 标题 + 4 个 ## 段落 + 注脚指针引用，无 ### 子段落、无代码块、无表格）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 措辞风格、人称、语气、格式约定。**核心结论：两者在措辞风格上存在系统性差异（Cline 英文第三人称描述式 + 命令式约束；Charles 中文第二人称命令式 + 业务规则堆叠），这些差异源于双方面向受众的根本不同（Cline 面向人类开发者治理代码库；Charles 面向 LLM 治理投研行为），属合理偏离而非对齐缺口。但计划文件 P6.5 对比表存在 3 处事实错误（6.5.3/6.5.4/6.5.5），需修正。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.5 对比表（L2352-2358）存在**三处事实性错误**：

| 计划项 | 计划标注 | 实测情况 | 偏差说明 |
|--------|---------|---------|---------|
| 6.5.3 表格使用 | Cline 无 / Charles 是 / 形式不同 | Cline 无 / Charles **无** / 双方均无表格 | **计划表标注错误**：Charles AGENTS.md 全文 0 表格行，`agent_config/rules/` 全目录 0 表格行。双方均无表格，实际已对齐，非"形式不同" |
| 6.5.4 标题层级 | Cline `## / ###` / Charles `## / ###` / 已对齐 | Cline `# / ## / ###`（3 级）/ Charles `# / ##`（2 级，**无 ###**） | **计划表标注错误**：Charles AGENTS.md 全文仅 `#`（L7）+ `##`（L12/L19/L40/L49），无任何 `###` 子段落。Cline 有 `###`（L19/L26/L90/L97）。标题层级未对齐 |
| 6.5.5 代码块 | Cline ```bash / Charles ```bash / 已对齐 | Cline ```mermaid + ```sh（**非 ```bash**）/ Charles **无代码块** | **计划表标注错误（双重）**：Cline 实际用 ```mermaid（L28）+ ```sh（L55/L62/L68/L76），无 ```bash；Charles AGENTS.md 全文 0 代码块。双方未对齐 |

### 核心结论

1. **语言（6.5.1）**：Cline 英文，Charles 中文。已确认。属合理的本地化选择——Cline 面向全球开源开发者，Charles 面向中文投研场景。非对齐缺口。
2. **句式（6.5.2）**：Cline 以"简洁陈述句 + 命令式 Don't"为主（"This file applies to..." / "Don't move stateful logic..."）；Charles 以"业务规则堆叠 + 禁止式 + 决策树箭头"为主（"禁止不调用 skills 工具..." / "→ 是: 先调用..."）。两者均含命令式约束，但 Cline 偏描述式陈述，Charles 偏命令式堆叠。
3. **表格使用（6.5.3）**：双方 AGENTS.md 均**无表格**（Cline 0 行、Charles 0 行、`agent_config/rules/` 全目录 0 行）。**计划表"Charles 是"标注错误**。实际双方在表格使用上已对齐（均不用表格）。
4. **标题层级（6.5.4）**：Cline 用 3 级（`#`/`##`/`###`），Charles 用 2 级（`#`/`##`，无 `###`）。**计划表"已对齐"标注错误**。Charles AGENTS.md 段落较扁平，未使用子段落；Cline 在"Package Boundaries"和"Practical Guidance"下使用 `###` 子段落组织内容。
5. **代码块（6.5.5）**：Cline 用 ```mermaid（依赖方向图）+ ```sh（4 处 shell 命令）+ ```text（llms 子包 1 处），Charles **无任何代码块**。**计划表"`bash | `bash | 已对齐"标注错误（双重）**：Cline 不用 ```bash 而用 ```sh；Charles 不用代码块。
6. **人称差异（计划未列出）**：Cline 第三人称/无人称（"This file applies to..." / "Run SDK commands from..."，主语为 "this file"/"this repo" 或祈使句省略主语）；Charles 第二人称（"你是 Charles，专业 AI 投研情报官"，全程隐含"你"为指代对象）。
7. **语气差异（计划未列出）**：Cline 技术参考文档语气（中性、陈述、引用其他 .md 文档）；Charles 指令式业务规则语气（直接、禁止式、决策树引导）。
8. **格式约定差异（计划未列出）**：Cline 用反引号包裹包名（`@cline/shared`）+ 行内 `Rules:` 标签 + 代码注释 `#`；Charles 用粗体内联标签（`**禁止行为**:` / `**硬约束（投研场景特有）**`）+ 箭头分支记号（`→`）+ `注:` 前缀注脚。
9. **nanobot 残留**：P6.5 范围内（Cline sdk/AGENTS.md + sdk/packages/llms/AGENTS.md + Charles agent_config/rules/AGENTS.md）**0 处残留**（注释残留 0、实现逻辑残留 0）。AGENTS.md 是纯文档文件，无代码实现逻辑，残留类型仅可能为"文本残留"。

### 一致性总体评估

- **语言对齐**：**低**（英文 vs 中文）。属合理本地化偏离，非缺陷。
- **句式对齐**：**低-中**（描述式 vs 命令堆叠）。两者均含命令式约束，但主导句式不同。属受众差异导致的合理偏离。
- **人称对齐**：**低**（第三人称/无人称 vs 第二人称）。属受众差异（面向开发者 vs 面向 LLM）。
- **语气对齐**：**低-中**（参考文档 vs 指令规则）。两者均为约束性文档，但 Cline 偏中性参考，Charles 偏强指令。
- **表格使用对齐**：**高**（双方均无）。**计划表标注错误，实际已对齐**。
- **标题层级对齐**：**中**（3 级 vs 2 级）。Charles 未用 `###`，但段落较少无需子段落，属合理简化。
- **代码块对齐**：**低**（mermaid+sh vs 无）。Cline 需要图示和命令示例，Charles 业务规则无需代码块。属内容差异导致的合理偏离。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.5.1 | 语言 | 英文（sdk/AGENTS.md 全文英文，sdk/packages/llms/AGENTS.md 全文英文） | 中文（agent_config/rules/AGENTS.md 全文中文，仅工具名 `skills`/`read_files`/`run_commands`/`web_search`/`search_codebase`/`editor` 为英文标识符） | 低 | 语言不同。属合理本地化选择，非对齐缺口。Charles 在中文叙述中嵌入英文工具名符合代码标识符不翻译惯例 |
| 6.5.2 | 句式 | 简洁陈述句为主 + 命令式 Don't 约束（"This file applies to..." / "Run SDK commands from..." / "Don't move stateful logic..."） | 业务规则堆叠 + 禁止式 + 决策树箭头（"禁止不调用 skills 工具..." / "→ 是: 先调用..." / "1. 任务匹配...?"） | 低-中 | 风格不同。两者均含命令式约束，但 Cline 偏描述式陈述（说明"是什么/怎么做"），Charles 偏命令式堆叠（规定"必须/禁止"） |
| 6.5.3 | 表格使用 | 无（sdk/AGENTS.md 0 表格行，sdk/packages/llms/AGENTS.md 0 表格行） | 无（agent_config/rules/AGENTS.md 0 表格行，`agent_config/rules/` 全目录 0 表格行） | 高 | **计划表"Charles 是"标注错误**。双方均无表格，实际已对齐。Charles 用列表 + 箭头分支替代表格表达决策逻辑 |
| 6.5.4 | 标题层级 | `#`（L7 标题）+ `##`（6 个段落）+ `###`（4 个子段落：Published SDK Packages / Dependency Direction / Keep Boundaries Clean / Refactor Standard） | `#`（L7 标题）+ `##`（4 个段落），**无 `###`** | 中 | **计划表"已对齐"标注错误**。Cline 3 级，Charles 2 级。Charles 段落内容较少（每段 4-10 行），无需 `###` 子段落组织 |
| 6.5.5 | 代码块 | ```mermaid（L28 依赖方向图）+ ```sh（L55/L62/L68/L76 共 4 处 shell 命令）+ llms 子包 ```text（L33） | **无任何代码块**（全文 0 个 ``` 标记） | 低 | **计划表"`bash | `bash | 已对齐"标注错误（双重）**：Cline 用 ```mermaid + ```sh（非 ```bash），Charles 无代码块。Cline 需图示和命令示例，Charles 业务规则纯文字表达 |
| 6.5.6 | 人称（计划未列出） | 第三人称/无人称（"This file applies to..." / "This repo" / 祈使句省略主语 "Run SDK commands..."） | 第二人称（"你是 Charles，专业 AI 投研情报官" / 隐含"你"指代 LLM） | 低 | 人称不同。Cline 面向人类开发者（中性参考），Charles 面向 LLM（直接指代"你"） |
| 6.5.7 | 语气（计划未列出） | 技术参考文档语气（中性、陈述、引用 CONTRIBUTING.md/ARCHITECTURE.md/DOC.md） | 指令式业务规则语气（直接、禁止式、决策树引导、硬约束） | 低-中 | 语气不同。Cline 是"参考手册"风格，Charles 是"行为准则"风格 |
| 6.5.8 | 列表风格（计划未列出） | 无序列表 `-` 为主（包清单、规则清单）+ 有序列表（未使用） | 无序列表 `-`（禁止行为、硬约束）+ 有序列表 `1./2./3./4.`（决策树步骤、工具选择原则） | 中 | Cline 仅用无序列表；Charles 混用无序（约束）+ 有序（决策步骤）。Charles 的有序列表服务于决策树语义 |
| 6.5.9 | 内联标签约定（计划未列出） | `Rules:` 行内标签（L36）+ 反引号包名（`@cline/shared`）+ 代码注释 `#`（L69-71） | `**禁止行为**:` 粗体标签（L33）+ `**硬约束（投研场景特有）**` 粗体带括号范围（L49）+ `注:` 前缀注脚（L56）+ 箭头 `→` 分支记号 | 中 | 标签约定不同。Cline 用普通文本 `Rules:`，Charles 用 Markdown 粗体 `**...**`。Charles 的箭头记号是决策树特有的视觉约定 |
| 6.5.10 | 文档引用方式（计划未列出） | Markdown 链接 `[CONTRIBUTING.md](./CONTRIBUTING.md)`（L9）+ 反引号路径 `packages/llms/AGENTS.md`（L93） | 反引号路径 `rules/general.md`（L56）+ 自然语言注脚 `注: ... 见 rules/general.md（由 rules_loader 自动加载）` | 中 | Cline 用标准 Markdown 链接（可点击），Charles 用纯文本注脚引用（无链接语法）。Charles 的注脚额外说明加载机制（rules_loader 自动加载） |

---

## 三、重点差距详解

### 3.1 计划表 6.5.3/6.5.4/6.5.5 三处事实错误（必须修正）

AGENT_COMPARISON_PLAN_V2.md L2352-2358 的对比表存在三处与实测不符的标注：

**6.5.3 表格使用**：
- 计划标注：Cline 无 / Charles 是 / 形式不同
- 实测：Cline sdk/AGENTS.md 全文 `^\|` 匹配 0 行；Charles agent_config/rules/AGENTS.md 全文 `^\|` 匹配 0 行；`agent_config/rules/` 全目录 `^\|` 匹配 0 行
- 修正：Cline 无 / Charles **无** / **已对齐**（双方均无表格）

**6.5.4 标题层级**：
- 计划标注：Cline `## / ###` / Charles `## / ###` / 已对齐
- 实测：Cline sdk/AGENTS.md 标题清单 `#`（L7）+ `##` ×6（L11/L17/L41/L51/L88/L103）+ `###` ×4（L19/L26/L90/L97）；Charles AGENTS.md 标题清单 `#`（L7）+ `##` ×4（L12/L19/L40/L49），**无 `###`**
- 修正：Cline `# / ## / ###`（3 级）/ Charles `# / ##`（2 级）/ **未对齐**（Charles 无 `###` 子段落）

**6.5.5 代码块**：
- 计划标注：Cline ```bash / Charles ```bash / 已对齐
- 实测：Cline sdk/AGENTS.md 代码块清单 ```mermaid（L28）+ ```sh（L55/L62/L68/L76，共 4 处），**无 ```bash**；Charles AGENTS.md 全文 `^```` 匹配 0 行，**无任何代码块**
- 修正：Cline ```mermaid + ```sh（非 ```bash）/ Charles **无代码块** / **未对齐**（双重差异：语言不同 + Charles 无代码块）

### 3.2 句式风格对比（6.5.2）

**Cline 句式特征**（sdk/AGENTS.md）：

| 句式类型 | 示例（行号） | 占比 |
|---------|-------------|------|
| 描述式陈述 | "This file applies to the SDK workspace rooted at this directory (`sdk/`)."（L13） | 主导 |
| 命令式 Don't | "Don't move stateful logic down into `agents`"（L92）/ "Don't put app-specific behavior into `core`"（L94） | 次要 |
| 命令式祈使 | "Run SDK commands from `sdk/`, not from the legacy repository root."（L15） | 次要 |
| 引用式 | "For onboarding, workspace setup... see [CONTRIBUTING.md](./CONTRIBUTING.md)."（L9） | 次要 |
| 条件式 | "If `dist/` is missing, build the SDK packages before running package tests"（L60） | 少量 |

Cline 句式以**描述式陈述为主**（说明"是什么/在哪儿"），命令式约束为辅（"Don't"/"Run from"），整体偏参考文档风格。

**Charles 句式特征**（agent_config/rules/AGENTS.md）：

| 句式类型 | 示例（行号） | 占比 |
|---------|-------------|------|
| 身份声明 | "你是 Charles，专业 AI 投研情报官。"（L9） | 开篇 |
| 决策树箭头 | "→ 是: 先调用 `skills(skill="...")` 加载该技能 SKILL.md 指令"（L24-25） | 主导 |
| 禁止式 | "禁止不调用 skills 工具而直接 `run_commands` 调用技能目录下的脚本"（L35-36） | 主导 |
| 有序步骤 | "1. 任务匹配某个技能...? 2. 任务是通用文件操作...?"（L23-27） | 次要 |
| 硬约束 | "禁止用 web_search 查本地已有数据的股价、财报"（L51） | 次要 |

Charles 句式以**命令式堆叠为主**（"禁止..."/"→ 是: ..."），描述式陈述为辅，整体偏行为准则风格。

**关键差异**：Cline 的"Don't"是英文开发文档惯用的轻量禁止式（建议性更强）；Charles 的"禁止"是中文业务规则的强禁止式（强制性更强）。两者均含命令式约束，但 Cline 偏"建议性约束"，Charles 偏"强制性约束"。

### 3.3 人称与语气对比（6.5.6 / 6.5.7）

**Cline 人称与语气**：
- 人称：第三人称/无人称。主语为 "This file"（L13）、"This repo"（L13）、"the SDK workspace"（L13），或祈使句省略主语 "Run SDK commands"（L15）、"Do not run"（L15）。全篇无 "you" 第二人称指代。
- 语气：技术参考文档。中性、陈述、引用其他文档（CONTRIBUTING.md/ARCHITECTURE.md/DOC.md）。如 L9 "For onboarding, workspace setup, publishing, and detailed workflow see [CONTRIBUTING.md]" 是典型参考文档引用句式。

**Charles 人称与语气**：
- 人称：第二人称。开篇 L9 "你是 Charles，专业 AI 投研情报官" 直接以"你"指代 LLM。后续 L10 "当任务匹配某个技能时，先通过 skills 工具加载" 省略主语但隐含"你"。L17 "切换模式通过 switch_to_act_mode / switch_to_plan_mode 工具" 同样隐含"你"。
- 语气：指令式业务规则。直接、禁止式、决策树引导。如 L33 "**禁止行为**:" + L35-38 三条禁止项，是典型的强指令语气。

**关键差异**：Cline 的第三人称/无人称面向人类开发者（开发者阅读文档后自行决策）；Charles 的第二人称面向 LLM（直接指令 LLM 行为）。这是双方面向受众根本不同的体现——Cline AGENTS.md 是"开发者参考"，Charles AGENTS.md 是"LLM 行为准则"。

### 3.4 格式约定对比（6.5.4 / 6.5.5 / 6.5.8 / 6.5.9 / 6.5.10）

**标题层级（6.5.4）**：
- Cline 3 级：`#` 标题 → `##` 段落 → `###` 子段落。`###` 用于在"Package Boundaries"下分"Published SDK Packages"/"Dependency Direction"，在"Practical Guidance"下分"Keep Boundaries Clean"/"Refactor Standard"。
- Charles 2 级：`#` 标题 → `##` 段落。无 `###` 子段落。Charles 段落内容较少（决策树段 L19-38 共 20 行、硬约束段 L49-54 共 6 行），无需子段落组织。
- 评估：Charles 未用 `###` 是合理简化（内容量不需要子段落），非对齐缺口。

**代码块（6.5.5）**：
- Cline 5 处代码块：```mermaid（L28-34 依赖方向流程图）+ ```sh ×4（L55-58/L62-64/L68-72/L76-82 安装/构建/测试命令）。llms 子包另含 ```text（L33-35 路由流程）。
- Charles 0 处代码块：全文无 ``` 标记。Charles 的工具名用反引号包裹（`skills`/`read_files`），但未用代码块展示命令或图示。
- 评估：Cline 需要图示（包依赖方向）和命令示例（bun install/build/test），Charles 业务规则纯文字表达无需代码块。属内容差异导致的合理偏离。

**列表风格（6.5.8）**：
- Cline：仅无序列表 `-`（包清单 L21-24、规则清单 L36-39/L45-49/L105-108）。未使用有序列表。
- Charles：无序列表 `-`（禁止行为 L35-38、硬约束 L51-54）+ 有序列表 `1./2./3./4.`（决策树 L23-31、工具选择原则 L43-47）。有序列表服务于决策树步骤语义。
- 评估：Charles 的有序列表是决策树语义的必要表达（步骤顺序重要），Cline 的无序列表用于枚举无序规则。双方列表风格选择合理。

**内联标签约定（6.5.9）**：
- Cline：`Rules:` 普通文本行内标签（L36）+ 反引号包名（`@cline/shared`）+ 代码注释 `#`（L69-71 `# typecheck all packages`）。
- Charles：`**禁止行为**:` Markdown 粗体标签（L33）+ `**硬约束（投研场景特有）**` 粗体带括号范围（L49）+ `注:` 前缀注脚（L56）+ 箭头 `→` 分支记号（L25/L28/L30）。
- 评估：Charles 用粗体强调约束标签，Cline 用普通文本。Charles 的箭头记号是决策树特有的视觉约定，Cline 无对应概念。

**文档引用方式（6.5.10）**：
- Cline：标准 Markdown 链接 `[CONTRIBUTING.md](./CONTRIBUTING.md)`（L9）+ 反引号路径 `packages/llms/AGENTS.md`（L93）。链接可点击跳转。
- Charles：纯文本注脚 `注: 股票代码格式、时间基准、输出规范等通用规则见 rules/general.md（由 rules_loader 自动加载）。`（L56）。无 Markdown 链接语法，但额外说明加载机制（rules_loader 自动加载）。
- 评估：Cline 用标准 Markdown 链接（IDE 可点击），Charles 用纯文本注脚（无链接但含加载机制说明）。Charles 的注脚面向 LLM 理解（说明"谁加载"），Cline 的链接面向开发者导航（可点击）。

### 3.5 Cline sdk/packages/llms/AGENTS.md 子包级风格佐证

Cline 子包级 AGENTS.md（39 行）的措辞风格与主 workspace 级一致：
- 英文、第三人称/无人称
- 描述式陈述为主（"`models.dev` catalog data and AI SDK provider behavior are the default sources of truth"）
- 命令式 Don't 约束（"Do not build a broad Cline-maintained model capability or behavior registry"）
- ```text 代码块（L33-35 路由流程图）
- 无表格、无第二人称

这佐证了 Cline AGENTS.md 风格在跨层级（workspace 级 + 子包级）上的一致性。Charles 仅有 1 个 AGENTS.md（无子包级），无跨层级对比需求。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.5 范围内涉及以下 3 个文件：
- `third_party/cline/sdk/AGENTS.md`（109 行，Cline 源码，作为对比基准，预期无 nanobot 残留）
- `third_party/cline/sdk/packages/llms/AGENTS.md`（39 行，Cline 源码，作为对比基准）
- `agent_config/rules/AGENTS.md`（56 行，Charles 源码，重点检查对象）

### 4.2 检查方法

AGENTS.md 是**纯文档文件**（Markdown），无代码实现逻辑。因此残留类型仅可能为"文本残留"（对应其他阶段的"注释残留"概念），不存在"实现逻辑残留"。检查方式为大小写不敏感搜索 "nanobot" 字符串。

### 4.3 检查结果

| 文件 | 文本残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `third_party/cline/sdk/AGENTS.md` | 0 处 | N/A（纯文档） | 全文无 "nanobot" 字样。Cline 源码本身与 nanobot 无关 |
| `third_party/cline/sdk/packages/llms/AGENTS.md` | 0 处 | N/A（纯文档） | 全文无 "nanobot" 字样 |
| `agent_config/rules/AGENTS.md` | 0 处 | N/A（纯文档） | 全文无 "nanobot" 字样。措辞风格（中文/第二人称/禁止式/决策树箭头）是通用 agent 规则文档模式，非 nanobot 风格残留 |

**P6.5 范围内 nanobot 残留总计：0 处（文本残留 0 + 实现逻辑残留 0）。**

### 4.4 与历史阶段对比

| 阶段 | 检查范围 | 文本/注释残留 | 实现逻辑残留 | 说明 |
|------|---------|--------------|-------------|------|
| P4.20 | 技能系统（loader/registry/skill_tool） | 多处 | 17 处 | 已审计 |
| P5.1 | SystemPromptBuilder（context.py） | 1 处 | 1 个死参数 | 已记录 |
| P6.1 | AGENTS.md frontmatter + rules_loader.py | 0 | 0 | 已确认 |
| P6.4 | AGENTS.md + rules/ 全目录去重 | 0 | 0 | 已确认 |
| **P6.5** | **AGENTS.md 措辞风格（3 个文件）** | **0** | **0** | **本阶段确认** |

**结论**：AGENTS.md 文档层面的 nanobot 残留已彻底清除。Charles AGENTS.md 的措辞风格（中文/第二人称/禁止式/决策树箭头/粗体标签）是面向 LLM 的业务规则文档通用模式，与 nanobot 风格无关联。

### 4.5 范围外残留说明

以下文件的 nanobot 残留**超出 P6.5 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1（已记录） |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20（已审计） |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20（已审计） |

---

## 五、修复建议

### 5.1 优先级 P0（计划文件事实错误，建议修正）

**问题**：AGENT_COMPARISON_PLAN_V2.md L2352-2358 的 P6.5 对比表存在 3 处事实错误（6.5.3/6.5.4/6.5.5）。

**修复**：将 L2352-2358 对比表改为（基于实测）：

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.5.1 | 语言 | 英文 | 中文 | 语言不同（合理本地化） |
| 6.5.2 | 句式 | 简洁陈述 + Don't | 业务规则堆叠 + 禁止式 | 风格不同 |
| 6.5.3 | 表格使用 | 无 | 无 | 双方均无（已对齐） |
| 6.5.4 | 标题层级 | `# / ## / ###`（3 级） | `# / ##`（2 级，无 `###`） | 层级深度不同 |
| 6.5.5 | 代码块 | ```mermaid + ```sh | 无 | Cline 有图示/命令，Charles 无 |

### 5.2 优先级 P1（无需修复，属合理偏离）

以下差异属双方面向受众不同的合理偏离，**不建议修改**：

- **6.5.1 语言不同**：Cline 面向全球开源开发者（英文），Charles 面向中文投研场景（中文）。本地化选择合理。
- **6.5.2 句式不同**：Cline 是开发者参考文档（描述式），Charles 是 LLM 行为准则（命令式）。受众不同导致句式不同。
- **6.5.6 人称不同**：Cline 第三人称面向人类开发者，Charles 第二人称面向 LLM。受众不同导致人称不同。
- **6.5.7 语气不同**：Cline 参考文档语气，Charles 指令规则语气。文档定位不同导致语气不同。
- **6.5.4 标题层级不同**：Charles 段落内容较少（每段 4-10 行），无需 `###` 子段落。属合理简化。
- **6.5.5 代码块不同**：Cline 需要图示（包依赖方向）和命令示例（bun install/build/test），Charles 业务规则纯文字表达。属内容差异。
- **6.5.10 文档引用方式不同**：Cline 用 Markdown 链接（面向开发者点击导航），Charles 用纯文本注脚（面向 LLM 理解加载机制）。受众不同。

### 5.3 优先级 P2（可选优化）

- **6.5.9 内联标签约定统一（可选）**：Charles 用 Markdown 粗体 `**禁止行为**:`，Cline 用普通文本 `Rules:`。若希望视觉风格更接近 Cline，可将 Charles 的粗体标签改为普通文本。但 Charles 的粗体在 LLM 上下文中能更强地强调约束边界，**建议保留**。
- **6.5.10 Charles 注脚引用改用 Markdown 链接（可选）**：Charles L56 `见 rules/general.md` 可改为 `见 [rules/general.md](./general.md)` 以支持 IDE 点击跳转。但 Charles 注脚主要面向 LLM 理解（非开发者点击），且 LLM 不点击链接，**建议保留纯文本**。

### 5.4 优先级 P3（不建议修改）

- **Charles AGENTS.md 增加 `###` 子段落**：Charles 段落内容量不足以支撑 `###` 子段落，强行添加会破坏当前扁平结构。**不建议修改**。
- **Charles AGENTS.md 增加代码块**：Charles 业务规则无命令/图示需求，强行添加代码块会引入不必要内容。**不建议修改**。
- **统一语言**：将 Charles AGENTS.md 改为英文或 Cline 改为中文。两者面向不同受众，**不建议统一**。

---

## 六、验证方法

### 6.1 语言对比验证

```powershell
# 验证 Cline sdk/AGENTS.md 为英文（标题段）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^# Cline SDK"
# 预期: L7 "# Cline SDK — Development Reference"

# 验证 Charles AGENTS.md 为中文（标题段）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^# Charles"
# 预期: L7 "# Charles - AI 投研情报官"
```

### 6.2 表格使用验证

```powershell
# 验证 Cline sdk/AGENTS.md 无表格（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^\|"
# 预期: 无匹配

# 验证 Charles AGENTS.md 无表格（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^\|"
# 预期: 无匹配

# 验证 agent_config/rules/ 全目录无表格（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" -Pattern "^\|"
# 预期: 无匹配
```

### 6.3 标题层级验证

```powershell
# 验证 Cline sdk/AGENTS.md 标题层级（应有 # / ## / ###）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^#{1,6} "
# 预期: # (L7) + ## ×6 (L11/L17/L41/L51/L88/L103) + ### ×4 (L19/L26/L90/L97)

# 验证 Charles AGENTS.md 标题层级（应有 # / ##，无 ###）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^#{1,6} "
# 预期: # (L7) + ## ×4 (L12/L19/L40/L49)，无 ### 匹配

# 验证 Charles AGENTS.md 无 ### 子段落（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^### "
# 预期: 无匹配
```

### 6.4 代码块验证

```powershell
# 验证 Cline sdk/AGENTS.md 代码块类型（应有 mermaid + sh，无 bash）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^```"
# 预期: ```mermaid (L28) + ``` (L34) + ```sh (L55) + ``` (L58) + ```sh (L62) + ``` (L64) + ```sh (L68) + ``` (L72) + ```sh (L76) + ``` (L82)

# 验证 Cline sdk/AGENTS.md 无 ```bash（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^```bash"
# 预期: 无匹配

# 验证 Charles AGENTS.md 无代码块（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^```"
# 预期: 无匹配
```

### 6.5 人称与句式验证

```powershell
# 验证 Cline sdk/AGENTS.md 第三人称/无人称（应无 "you"）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "\byou\b" -CaseSensitive:$false
# 预期: 无匹配

# 验证 Charles AGENTS.md 第二人称（应有 "你是"）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "你是"
# 预期: L9 "你是 Charles，专业 AI 投研情报官"

# 验证 Cline sdk/AGENTS.md 含 Don't 命令式约束
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "Don't"
# 预期: L92 "Don't move stateful logic" + L94 "Don't put app-specific behavior"

# 验证 Charles AGENTS.md 含"禁止"命令式约束
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "禁止"
# 预期: L33/L35/L36/L37/L38（禁止行为段）+ L51/L52/L53/L54（硬约束段）
```

### 6.6 nanobot 残留验证

```powershell
# 验证 Cline sdk/AGENTS.md 无 nanobot（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无匹配

# 验证 Cline sdk/packages/llms/AGENTS.md 无 nanobot（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\llms\AGENTS.md" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无匹配

# 验证 Charles AGENTS.md 无 nanobot（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无匹配
```

---

## 七、附录

### 7.1 Cline sdk/AGENTS.md 措辞风格特征汇总

```
语言:        英文
人称:        第三人称/无人称（This file / This repo / 祈使句省略主语）
语气:        技术参考文档（中性、陈述、引用其他 .md）
句式主导:    描述式陈述（"This file applies to..."）
句式辅助:    命令式 Don't（"Don't move..."）/ 祈使式（"Run SDK commands..."）
标题层级:    # / ## / ###（3 级）
代码块:      ```mermaid（图示）+ ```sh（命令），无 ```bash
表格:        无
列表:        无序 `-` 为主
内联标签:    Rules: 普通文本
文档引用:    [text](path) Markdown 链接
```

### 7.2 Charles agent_config/rules/AGENTS.md 措辞风格特征汇总

```
语言:        中文（工具名保留英文标识符）
人称:        第二人称（"你是 Charles" / 隐含"你"）
语气:        指令式业务规则（直接、禁止式、决策树引导）
句式主导:    命令式堆叠（"禁止..." / "→ 是: ..."）
句式辅助:    身份声明（"你是 Charles"）/ 有序步骤（"1. 任务匹配..."）
标题层级:    # / ##（2 级，无 ###）
代码块:      无
表格:        无
列表:        无序 `-`（约束）+ 有序 1./2./3./4.（决策步骤）
内联标签:    **禁止行为**: / **硬约束（...）** 粗体 + 注: 前缀 + → 箭头
文档引用:    纯文本注脚（"见 rules/general.md（由 rules_loader 自动加载）"）
```

### 7.3 双方措辞风格 Venn 图

```
Cline AGENTS.md 风格          Charles AGENTS.md 风格
┌──────────────────────┐      ┌──────────────────────┐
│ 英文                  │      │ 中文                  │
│ 第三人称/无人称       │      │ 第二人称              │
│ 描述式陈述为主        │      │ 命令式堆叠为主        │
│ Don't 轻量禁止        │      │ 禁止 强禁止           │
│ # / ## / ### (3 级)   │      │ # / ## (2 级)         │
│ ```mermaid + ```sh    │      │ 无代码块              │
│ Rules: 普通文本标签   │      │ **粗体**标签 + → 箭头 │
│ [text](path) 链接     │      │ 纯文本注脚            │
│ 无序 `-` 列表         │      │ 无序 `-` + 有序 1./2. │
└──────────────────────┘      └──────────────────────┘
        │                              │
        └────────交集──────────────────┘
         无表格 / 无序 `-` 列表 / Markdown frontmatter / # + ## 标题
```

### 7.4 计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 6.5.1 语言 | Cline 英文 / Charles 中文 / 语言不同 | **确认准确** | Cline 英文，Charles 中文 |
| 6.5.2 句式 | Cline 简洁陈述 / Charles 业务规则 / 风格不同 | **确认准确** | Cline 描述式陈述为主，Charles 命令式堆叠为主 |
| 6.5.3 表格使用 | Cline 无 / Charles 是 / 形式不同 | **计划表标注错误** | 实际双方均无表格（Charles AGENTS.md 0 行、rules/ 全目录 0 行），已对齐 |
| 6.5.4 标题层级 | Cline `## / ###` / Charles `## / ###` / 已对齐 | **计划表标注错误** | 实际 Cline 3 级（`# / ## / ###`），Charles 2 级（`# / ##`，无 `###`），未对齐 |
| 6.5.5 代码块 | Cline ```bash / Charles ```bash / 已对齐 | **计划表标注错误（双重）** | 实际 Cline 用 ```mermaid + ```sh（非 ```bash），Charles 无代码块，未对齐 |

**计划表标注总结**：5 项中 2 项（6.5.1/6.5.2）标注准确，3 项（6.5.3/6.5.4/6.5.5）标注错误。错误原因可能是计划编写时基于对 Charles AGENTS.md 的预判（误以为含量化表格、误以为用 ```bash 代码块、误以为有 `###` 子段落），未与实际文件内容核对。

**额外发现**（计划表未涵盖）：
- 6.5.6 人称差异（Cline 第三人称/无人称 vs Charles 第二人称）
- 6.5.7 语气差异（Cline 参考文档 vs Charles 指令规则）
- 6.5.8 列表风格差异（Cline 仅无序 vs Charles 无序 + 有序）
- 6.5.9 内联标签约定差异（Cline 普通文本 `Rules:` vs Charles 粗体 `**禁止行为**:` + 箭头 `→`）
- 6.5.10 文档引用方式差异（Cline Markdown 链接 vs Charles 纯文本注脚）
- nanobot 残留：0 处（AGENTS.md 文档层面已彻底清除）

### 7.5 风格差异性质判定

| 差异项 | 性质判定 | 理由 |
|--------|---------|------|
| 语言不同 | 合理本地化偏离 | Cline 面向全球开源，Charles 面向中文投研 |
| 人称不同 | 合理受众偏离 | Cline 面向人类开发者，Charles 面向 LLM |
| 语气不同 | 合理定位偏离 | Cline 是参考手册，Charles 是行为准则 |
| 句式不同 | 合理受众偏离 | Cline 描述供开发者理解，Charles 命令供 LLM 执行 |
| 标题层级不同 | 合理简化偏离 | Charles 段落内容少，无需 `###` |
| 代码块不同 | 合理内容偏离 | Cline 需图示/命令，Charles 纯业务规则 |
| 表格（双方均无） | 已对齐 | 计划表误标为"形式不同" |
| 内联标签不同 | 合理强调偏离 | Charles 粗体在 LLM 上下文中强调约束边界 |
| 文档引用不同 | 合理受众偏离 | Cline 链接供点击，Charles 注脚供 LLM 理解加载机制 |

**总体判定**：P6.5 范围内的所有措辞风格差异（除计划表事实错误外）均属**合理偏离**，源于双方面向受众（人类开发者 vs LLM）和文档定位（参考手册 vs 行为准则）的根本不同。**不建议为追求风格对齐而修改任何一方**。计划表的 3 处事实错误（6.5.3/6.5.4/6.5.5）建议修正，以反映双方实际格式约定。
