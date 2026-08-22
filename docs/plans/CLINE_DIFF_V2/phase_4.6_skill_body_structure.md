# Phase 4.6 SKILL.md 主体结构对比

> 对比范围：Cline `skills.mdx` 文档定义的 SKILL.md 结构规范 + 6 个 Cline 实际 SKILL.md 示例文件与 Charles 8 个 SKILL.md 文件的主体段落结构（Purpose / Instructions / Workflow / Examples / Notes 等）、段落顺序、段落内容、Markdown 格式、代码块格式、标题层级逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/docs/customization/skills.mdx` 全文 271 行（SKILL.md 结构规范文档，含目录结构、frontmatter 规范、body 写作指南、data-analysis 示例）
> - `third_party/cline/.cline/skills/publish-ui/SKILL.md`（发布类示例，Workflow 模式）
> - `third_party/cline/.cline/skills/publish-desktop/SKILL.md`（发布类示例，Workflow 模式 + 表格）
> - `third_party/cline/.cline/skills/publish-cli/SKILL.md`（发布类示例，Workflow 模式 + Step 0 前置）
> - `third_party/cline/.agents/skills/opentui/SKILL.md`（参考类示例，Decision Tree + Index 模式）
> - `third_party/cline/.agents/skills/create-pull-request/SKILL.md`（流程类示例，Prerequisites + Checklist 模式）
> - `third_party/cline/.agents/skills/cline-sdk/SKILL.md`（参考类示例，Decision Tree + Index 模式）
>
> Charles 源码：
> - `agent_config/skills/web-search/SKILL.md`
> - `agent_config/skills/bond-credit-review/SKILL.md`
> - `agent_config/skills/sentiment-analysis/SKILL.md`
> - `agent_config/skills/stock-price/SKILL.md`
> - `agent_config/skills/compare-reports/SKILL.md`
> - `agent_config/skills/write-report/SKILL.md`
> - `agent_config/skills/financial-analysis/SKILL.md`
> - `agent_config/skills/read-pdf/SKILL.md`

---

## 一、执行摘要

本阶段对比 Cline SKILL.md 结构规范（skills.mdx 文档 + 6 个实际示例）与 Charles 8 个 SKILL.md 文件的主体段落结构。Cline 的 SKILL.md 采用**灵活结构**——文档仅要求 frontmatter（`name` + `description`）+ body（"把重要信息放前面"、"用清晰的章节标题"、"不超过 5k tokens"、"包含真实示例"），6 个实际示例呈现两种模式（Workflow 步骤模式 / Reference 索引模式），章节名称因技能用途而异，无固定模板。Charles 的 8 个 SKILL.md 采用**高度统一的模板化结构**——所有技能均按 `本技能核心能力 → 场景路由 → Workflow → 脚本角色说明 → 脚本调用规则 → 禁止行为` 固定顺序组织，Workflow 内每个 Step 以 H3 子标题 + 结构化字段（何时执行/前置条件/命令/参数/预期输出/失败处理）呈现。

### 核心结论

1. **frontmatter 字段差异**：Cline 文档要求 `name` + `description`（max 1024 字符），部分示例额外使用 `metadata.references`；Charles 统一使用 `name` + `description` + `when_to_use`（Charles 独有字段，Cline 无此字段），read-pdf 额外使用 `always: true`（Charles 独有）。Charles 的 `when_to_use` 将"何时使用"从 `description` 中拆分独立，Cline 则合并于 `description`。
2. **H1 标题格式差异**：Cline 示例使用描述性标题（如 `# Publish UI`、`# Desktop App Release`、`# Create Pull Request`）；Charles 8 个技能统一使用 `# {skill-name} 技能指南` 格式，标题一致性高但信息量略低。
3. **body 结构模式差异**：Cline 呈现两种模式——Workflow 步骤模式（publish-ui/desktop/cli、create-pull-request）和 Reference 索引模式（opentui、cline-sdk），章节名称灵活；Charles 8 个技能全部采用统一模板，章节名称和顺序固定。
4. **Workflow 章节内部结构差异**：Cline 的 Workflow 用编号列表（`1. Gather context.` + 代码块）直接铺陈步骤；Charles 的 Workflow 用 H3 子标题（`### Step N: ...`）分段，每个 Step 内部用结构化字段（**何时执行**/**前置条件**/**命令**/**参数**/**预期输出**/**失败处理**）组织，结构化程度更高。
5. **代码块格式差异**：Cline 混用 ` ```sh `、` ```bash `、` ``` `（plain）三种代码块语言标记；Charles 全部统一使用 ` ```bash `。
6. **表格使用差异**：Cline 频繁使用 Markdown 表格（opentui/cline-sdk 的 Product Index、publish-desktop 的 secrets 表、create-pull-request 的部分列表）；Charles 8 个 SKILL.md **均不使用表格**，全部用 bullet list 或 bold 文本替代。
7. **Charles 独有章节**：`## 本技能核心能力`、`## 场景路由`、`## 脚本角色说明`、`## 脚本调用规则`、`## 禁止行为` 这 5 个章节为 Charles 模板独有，Cline 无对应固定章节。
8. **Cline 独有章节**：`## Critical Rules`、`## Release contract`、`## How to Use This Skill`、`## Quick Decision Trees`、`## Product Index`、`## Resources`、`## Error Handling`、`## Summary Checklist` 等为 Cline 示例中出现的章节，Charles 无对应。
9. **标题层级使用差异**：两者均使用 H1（标题）→ H2（章节）→ H3（子章节）三级。Cline 的 opentui/cline-sdk 在 H3 下用 ` ``` ` 代码块画决策树；Charles 的 H3 仅用于 Workflow Step 分段。
10. **语言差异**：Cline 全英文；Charles 全中文。
11. **nanobot 残留**：**0 处注释残留**，**0 处实现逻辑残留**。8 个 SKILL.md 文件中无任何 `nanobot` 关键词出现。`always: true` frontmatter 字段（read-pdf）虽概念上与 nanobot `get_always_skills()` 相关，但属于 Charles 已实现的主动能扩展，非残留。

### 一致性总体评估

- **frontmatter 基础字段**：**高**。`name` + `description` 两者均必备。
- **body 结构灵活性**：**低**。Cline 灵活无模板，Charles 统一模板化——此为设计哲学差异，非对齐缺陷。
- **Workflow 概念**：**高**。两者均有 `## Workflow` 章节，均用步骤化方式组织执行流程。
- **代码块与 Markdown 规范**：**中**。均使用标准 Markdown，但代码块语言标记不统一（Cline 混用，Charles 统一 bash）。
- **写作指南遵循度**：**高**。Charles 的"重要信息前置"（本技能核心能力开头）、"清晰章节标题"、"包含真实示例"（场景路由中的真实用户问法）均符合 Cline skills.mdx 写作指南。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.6.1 | frontmatter 必备字段 | `name` + `description`（skills.mdx L68-70），`name` 须匹配目录名，`description` max 1024 字符 | `name` + `description`（8/8 技能均具备） | 高 | 基础字段对齐 |
| 4.6.2 | frontmatter 额外字段 | `metadata.references`（opentui/cline-sdk 2/6 使用） | `when_to_use`（8/8 使用）+ `always`（read-pdf 1/8 使用） | 低 | 两者各有独有字段，互不兼容。Charles `when_to_use` 拆分了 Cline `description` 的"何时使用"职责 |
| 4.6.3 | H1 标题格式 | 描述性标题：`# Publish UI`、`# Desktop App Release`、`# CLI Release`、`# OpenTUI Platform Skill`、`# Create Pull Request`、`# Cline SDK Skill` | 统一格式：`# {skill-name} 技能指南`（8/8） | 中 | Charles 一致性高但标题信息量低；Cline 标题更贴合技能用途 |
| 4.6.4 | H1 后引导段落 | 均有 1-3 段引导文字（publish-ui L8、publish-desktop L8-12、create-pull-request L8、opentui L10、cline-sdk L10） | 无独立引导段落，H1 后直接进入 `## 本技能核心能力` | 中 | Cline 风格更自然；Charles 将引导内容合并到"本技能核心能力"章节 |
| 4.6.5 | Purpose 章节 | 无固定章节，引导段落承担（如 publish-desktop L12 "Desktop releases are macOS-only..."） | `## 本技能核心能力`（8/8），含工作方式编号列表 + 适用/不适用内容 | 中 | Charles 结构化程度更高；Cline 更自由。对应写作指南"把重要信息放前面" |
| 4.6.6 | 场景路由章节 | 无对应固定章节（create-pull-request 的 "Gather Context" / "Information Gathering" 部分类似） | `## 场景路由`（8/8），按用户意图列出执行路径（bullet list + bold 场景描述） | — | Charles 独有增强，明确路由逻辑。Cline 无此概念 |
| 4.6.7 | Workflow 章节名 | `## Workflow`（publish-desktop L24、publish-cli L117）或 `## Normal release`（publish-ui L31）或无 Workflow 标题（opentui/cline-sdk） | `## Workflow`（8/8） | 高 | 章节名一致（Charles 全统一，Cline 部分）。Cline 发布类技能用 Workflow，参考类不用 |
| 4.6.8 | Workflow 步骤组织 | 编号列表直接铺陈：`1. Gather context.` + 代码块 + 文字说明（publish-desktop L26-107） | H3 子标题分段：`### Step N: ...`（8/8），每步独立 H3 | 中 | Charles 结构化程度更高；Cline 更紧凑 |
| 4.6.9 | Workflow 步骤内部字段 | 无结构化字段，步骤内用散文 + 代码块描述（publish-cli L121-131） | 统一结构化字段：**何时执行**/**前置条件**/**命令**/**参数**/**预期输出**/**失败处理**（8/8） | — | Charles 独有增强，字段一致性好。Cline 无此结构 |
| 4.6.10 | 步骤前置/跳过条件 | 散文描述（publish-cli L119 "Complete Step 0 first"） | 显式字段：**前置条件**/**跳过条件**（sentiment-analysis Step 2/3、write-report Step 4） | — | Charles 独有增强 |
| 4.6.11 | 代码块语言标记 | 混用 ` ```sh `（publish-ui/desktop/cli）、` ```bash `（create-pull-request）、` ``` `（opentui/cline-sdk 决策树和路径） | 统一 ` ```bash `（8/8，仅用于命令） | 中 | Charles 一致性高。Cline 混用但语义合理（sh 用于 shell、plain 用于非命令） |
| 4.6.12 | 表格使用 | 频繁使用（opentui L29-35/L170-194、cline-sdk L31-37/L177-202、publish-desktop L115-124、create-pull-request 隐含） | **0 表格**（8/8 均不使用） | 低 | Charles 完全不用表格，用 bullet list 替代。Cline 用表格组织参考信息 |
| 4.6.13 | 决策树结构 | ` ``` ` 代码块画 ASCII 决策树（opentui L66-157、cline-sdk L69-162） | 无决策树，用 `## 场景路由` bullet list 替代 | 中 | 两种路由方式等价；Charles 更简洁，Cline 更直观 |
| 4.6.14 | 脚本角色说明章节 | 无对应固定章节（skills.mdx L201-209 描述 scripts/ 用途但不在 SKILL.md body 中固定） | `## 脚本角色说明`（8/8），区分主脚本/内部脚本，列出脚本职责 | — | Charles 独有增强，明确脚本分类 |
| 4.6.15 | 脚本调用规则章节 | 无对应章节 | `## 脚本调用规则`（7/8，write-report 无此章节） | — | Charles 独有增强。write-report 因不直接调用脚本故缺此章节 |
| 4.6.16 | 禁止行为章节 | 无对应固定章节（create-pull-request 的 "Error Handling" L184-199 部分类似） | `## 禁止行为`（8/8），bullet list 列出禁止事项 | — | Charles 独有增强，负面约束明确 |
| 4.6.17 | Resources/外部链接章节 | `## Resources`（opentui L195-200、cline-sdk L203-207），含仓库/文档/Discord 链接 | 无（8/8 均无 Resources 章节） | 低 | Charles 无外部链接章节。Cline 参考类技能有 |
| 4.6.18 | Error Handling 章节 | `## Error Handling`（create-pull-request L184-199），含 Common Issues 编号列表 | 无独立 Error Handling 章节，失败处理内嵌于 Workflow Step 的**失败处理**字段 | 中 | 语义等价。Charles 将错误处理分散到各 Step，Cline 集中一节 |
| 4.6.19 | Checklist 章节 | `## Summary Checklist`（create-pull-request L201-211），含 `- [ ]` 复选框 | 无 | — | Charles 无 checklist。Cline create-pull-request 独有 |
| 4.6.20 | Critical Rules 章节 | `## Critical Rules`（opentui L13-19、cline-sdk L13-22），编号列表 + bold 强调 | 无独立章节，关键约束散布于"本技能核心能力"和"禁止行为" | 中 | 语义等价。Charles 用"禁止行为"集中负面约束 |
| 4.6.21 | Release contract 章节 | `## Release contract`（publish-ui L10、publish-desktop L15、publish-cli L17），bullet list 列出发布约束 | 无（非发布类技能，不适用） | — | Cline 发布类技能独有 |
| 4.6.22 | 引用 bundled 文件 | `[advanced.md](docs/advanced.md)` 链接式引用（skills.mdx L65/L215-220） | 无链接式引用，用 `## 脚本角色说明` 描述脚本 + ` ```bash ` 命令直接调用 | 中 | Cline 用 Markdown 链接引用 docs/；Charles 用命令行直接调用 scripts/ |
| 4.6.23 | 标题层级深度 | H1 → H2 → H3（最大 3 级），部分 H3 下有代码块决策树 | H1 → H2 → H3（最大 3 级），H3 仅用于 Workflow Step | 高 | 层级深度一致 |
| 4.6.24 | Markdown 格式元素 | bullet list、numbered list、bold、blockquote（publish-desktop L10）、table、checkbox（create-pull-request L204-211）、代码块 | bullet list、numbered list、bold、代码块。**无** blockquote、table、checkbox | 中 | Charles 格式元素较少。Cline 更丰富 |
| 4.6.25 | 5k token 限制遵循 | skills.mdx L145 "Keep SKILL.md under 5k tokens"，示例文件长度 100-270 行 | 8 个文件 60-125 行，均远低于 5k tokens | 高 | Charles 更精简 |
| 4.6.26 | 真实示例包含度 | skills.mdx L147 "Include real examples"，示例含真实命令和输出预期 | `## 场景路由` 含真实用户问法示例（如"贵州茅台现在多少钱"），命令含真实参数示例 | 高 | 两者均包含真实示例 |
| 4.6.27 | 段落顺序一致性 | 6 个示例段落顺序因技能用途而异（发布类 vs 参考类 vs 流程类） | 8 个技能段落顺序完全一致（模板化） | — | Charles 一致性极高；Cline 灵活性高。设计哲学差异 |

---

## 三、重点差距详细说明

### 3.1 body 结构模式差异：灵活 vs 模板化（4.6.5 ~ 4.6.9）

**Cline 模式**：skills.mdx 文档不规定固定章节，仅给出写作原则（"把重要信息放前面"、"用清晰的章节标题"、"不超过 5k tokens"、"包含真实示例"）。6 个实际示例呈现两种模式：

- **Workflow 步骤模式**（publish-ui/desktop/cli、create-pull-request）：H1 → 引导段落 → `## Release contract`（约束清单）→ `## Workflow`（编号步骤 + 代码块）→ 可选辅助章节。步骤用编号列表 `1. Gather context.` 直接铺陈，步骤内用散文 + 代码块描述，无结构化字段。

- **Reference 索引模式**（opentui、cline-sdk）：H1 → 引导段落 → `## Critical Rules`（编号规则）→ `## How to Use This Skill`（含 H3 子章节 + 表格）→ `## Quick Decision Trees`（H3 + 代码块决策树）→ `## Product Index`（表格）→ `## Resources`（链接）。

**Charles 模式**：8 个技能全部采用统一模板：

```
# {name} 技能指南
## 本技能核心能力          (Purpose: 工作方式 + 适用/不适用内容)
## 场景路由                (Routing: 按用户意图列执行路径)
## Workflow                (Workflow: H3 Step 分段 + 结构化字段)
  ### Step 1: ...
  ### Step N: ...
## 脚本角色说明            (Scripts: 主脚本/内部脚本分类)
## 脚本调用规则            (Rules: 编号列表)  [7/8]
## [领域专属章节]          (Notes: 数据前提/数据来源/年份规则等)
## 禁止行为                (Constraints: 负面约束清单)
```

**差异性质**：此为**设计哲学差异**，非对齐缺陷。Charles 的模板化结构一致性更高、机器可读性更强、新技能编写门槛更低；Cline 的灵活结构更贴合技能用途、表达力更丰富。两者均符合 Cline skills.mdx 的写作原则。

### 3.2 Workflow Step 内部结构差异（4.6.8 ~ 4.6.10）

**Cline**：Workflow 步骤为编号列表项，步骤内用散文描述 + 代码块。以 publish-desktop 为例：

```markdown
1. Gather context.

```sh
git status --short --branch
git fetch origin --tags
...
```

If there is no `desktop-v*` tag yet, this is the first release...
```

无结构化字段，前置条件和失败处理散布在散文中。

**Charles**：Workflow 步骤为 H3 子标题，步骤内用统一结构化字段。以 stock-price Step 1 为例：

```markdown
### Step 1: 获取 K 线数据

- **何时执行**: 用户询问股价/K线/走势/成交量时
- **前置条件**: MiniQMT 客户端已运行并登录
- **命令**:
  ```bash
  python agent_config/skills/stock-price/scripts/get_kline.py <股票代码> [周期] [条数]
  ```
- **参数**:
  - `<股票代码>` (必填): 带交易所后缀，如 `600519.SH`
  - `[周期]` (可选): 默认 `1d`
- **预期输出**: K 线数据表格
- **失败处理**:
  - 报错 `xtquant not found` → 提示用户安装 xtquant 包
```

**差异性质**：Charles 的结构化字段（何时执行/前置条件/命令/参数/预期输出/失败处理）是一致性增强，使每个 Step 的信息组织方式统一，便于 agent 解析。Cline 的散文式描述更灵活但一致性低。两者语义等价。

### 3.3 frontmatter 字段差异（4.6.1 ~ 4.6.2）

| 字段 | Cline 文档/示例 | Charles 8 技能 | 说明 |
|------|----------------|---------------|------|
| `name` | 必备，须匹配目录名 | 必备，均匹配目录名 | 一致 |
| `description` | 必备，max 1024 字符，含"何时使用" | 必备，仅描述"做什么" | Charles 的 description 不含"何时使用" |
| `when_to_use` | 无此字段 | 必备（8/8），描述"何时使用" | Charles 独有，从 description 拆分 |
| `always` | 无此字段 | read-pdf 使用（1/8） | Charles 独有，标记技能常驻加载 |
| `metadata.references` | opentui/cline-sdk 使用（2/6） | 无 | Cline 独有，标注参考文件 |
| `disabled` / `enabled` | 文档未提及，但 loader 支持 | 8/8 均未使用 | 两者 loader 均支持解析，但 SKILL.md 未声明 |

**差异影响**：Charles 的 `when_to_use` 字段拆分了 Cline `description` 的职责。Cline 文档明确指出 `description` "tells Cline when to use this skill"（skills.mdx L70），即 description 同时承担"做什么"和"何时使用"。Charles 将两者分离。此差异不影响运行时行为（Charles loader 同时读取两个字段用于路由），但与 Cline 文档规范不兼容——若 Charles SKILL.md 放入 Cline 环境，`when_to_use` 字段会被忽略，`description` 因不含触发条件而导致技能无法被正确激活。

### 3.4 代码块语言标记差异（4.6.11）

**Cline**（6 个示例）：
- ` ```sh `：publish-ui、publish-desktop、publish-cli（shell 命令）
- ` ```bash `：create-pull-request（bash 命令）
- ` ``` `（plain）：opentui、cline-sdk（决策树、文件路径，非命令）

**Charles**（8 个技能）：
- ` ```bash `：全部 8 个技能，仅用于 Python 命令调用

**差异性质**：Charles 一致性更高（统一 bash），但存在语义不准确——代码块内容为 `python ...` 命令，标记为 `bash` 可接受但非精确。Cline 的 ` ```sh ` 用于 shell 命令更精确，` ``` ` plain 用于非命令内容（决策树）是合理区分。此差异不影响运行时行为，仅影响 Markdown 渲染语法高亮。

### 3.5 表格使用差异（4.6.12）

**Cline**：6 个示例中 4 个使用表格：
- opentui：3 张表（Reference File Structure L29-35、Frameworks L171-176、Component Categories L188-193）
- cline-sdk：3 张表（Reference File Structure、API Surfaces、Package Map）
- publish-desktop：1 张表（Repo secrets L115-124）
- create-pull-request：隐含表格结构

**Charles**：8 个技能 **0 张表格**。所有可表格化的内容（脚本角色说明、参数说明、数据来源）均用 bullet list 或 bold 文本呈现。

**差异性质**：Charles 完全不用表格是模板风格选择。表格在组织结构化参考信息（如脚本清单、API 对照）时更清晰，bullet list 在组织流程性信息时更自然。Charles 的脚本角色说明用 bullet list 足够清晰，但若参考类技能增多，表格可能更合适。

### 3.6 Charles 领域专属章节差异（4.6.14 ~ 4.6.16）

Charles 8 个技能中 4 个包含领域专属章节（位于"脚本调用规则"和"禁止行为"之间）：

| 技能 | 专属章节 | 内容 |
|------|---------|------|
| compare-reports | `## 数据前提` | RAG 索引存在性要求 |
| financial-analysis | `## 数据来源` | CSV 文件路径清单 |
| write-report | `## 报告期选择规则` | 当前日期 + 默认报告期 |
| read-pdf | `## 年份规则` + `## 数据源选择` + `## 终端监控说明` | 年份理解规则 + 数据类型路由 + 进度监控 |

**差异性质**：这些领域专属章节是 Charles 模板的合理扩展点，用于承载技能特有的约束和说明。Cline 的灵活结构无需此区分——各类信息自由穿插。Charles 通过固定位置（脚本调用规则之后、禁止行为之前）放置领域专属内容，保持了模板一致性。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（0 处）

对 8 个 Charles SKILL.md 文件执行 `nanobot` 关键词搜索（不区分大小写）：

```
Grep "nanobot" agent_config/skills/ -i
```

**搜索结果：No matches found**。

8 个 SKILL.md 文件中均无 `nanobot` 关键词出现，无注释残留、无 docstring 残留、无任何文本残留。

### 4.2 实现逻辑残留（0 处）

**逐项核查结果**：

| 检查项 | Cline SKILL.md | Charles SKILL.md | 残留判定 |
|--------|---------------|-----------------|---------|
| 子 agent 隔离执行语义 | 无（skills.mdx 明确技能在主上下文执行） | 无（8/8 均为主上下文指令注入） | **无残留** |
| 工具集限制（allowed_tools） | 无 frontmatter 字段 | 8/8 均无 `allowed_tools` frontmatter 声明 | **无残留** |
| attempt_completion 返回 | 无 | 无 | **无残留** |
| 独立 runtime | 无 | 无 | **无残留** |

**`always` 字段说明**：

read-pdf/SKILL.md L5 声明 `always: true` frontmatter 字段。该字段概念上与 nanobot `get_always_skills()` 相关（见 P4.1 报告：Charles `registry.py` L184 `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()"""`），但属于 Charles **已实现的主动能扩展**——`always: true` 使 read-pdf 技能在启动时常驻加载，不等待触发。此功能已被 SkillRegistry 主动使用（`get_always_skills()` 方法被调用），非未清理的遗留代码。

**判定**：`always` 字段为 Charles 主动能扩展，**非 nanobot 残留**。概念溯源至 nanobot，但已完全融入 Charles 实现体系并正常运行。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（nanobot 对标说明） | 0 处 | — | 无需处理 |
| 注释残留（use_skill 工具名） | 0 处 | — | 无需处理（SKILL.md 中无此关键词） |
| 实现逻辑残留 | 0 处 | — | 无需处理 |
| 主动能扩展（always 字段） | 1 字段（read-pdf） | — | 非残留，无需处理 |

**说明**：P4.1 报告中发现的 15 处 nanobot 注释残留均位于 Python 源码文件（`__init__.py`、`skill_tool.py`、`registry.py`、`loader.py`）中，不在 SKILL.md 文件内。本阶段针对 SKILL.md 主体结构的 nanobot 残留检查结果为**零残留**。

---

## 五、修复建议

### 5.1 高优先级（P1）

无。SKILL.md 主体结构无阻塞性问题，8 个技能文件结构清晰、一致性好、符合 Cline 写作指南核心原则。

### 5.2 中优先级（P2）

1. **代码块语言标记统一**（8 个 SKILL.md）：当前 ` ```bash ` 包裹的均为 `python ...` 命令。可考虑统一为 ` ```bash `（当前选择，可接受）或更精确的标记。此为风格优化，非功能问题。

2. **description 字段对齐**（8 个 SKILL.md）：若考虑与 Cline 环境兼容，可将 `when_to_use` 内容合并回 `description`（按 Cline 文档 "description tells Cline when to use this skill" 的规范）。但 Charles 当前 `when_to_use` 拆分设计有独立性优势，且 Charles loader 同时读取两字段，**若不跨环境使用可保留现状**。

3. **write-report 缺失"脚本调用规则"章节**（write-report/SKILL.md）：8 个技能中仅 write-report 无 `## 脚本调用规则`（因其研报正文由 agent 直接输出、不调用脚本）。虽有 `## 脚本角色说明` 区分了主脚本/内部脚本，但 `report_generator.py`（Step 4 可选）的调用规则未集中说明。可考虑补充简短的调用规则章节或标注"本技能通常不调用脚本"。

### 5.3 低优先级（P3）

4. **表格引入**（可选）：若未来新增参考类技能（类似 Cline opentui/cline-sdk 的索引型技能），可考虑引入 Markdown 表格组织脚本清单、API 对照等结构化参考信息。当前 8 个技能均为流程型，bullet list 足够。

5. **H1 标题信息量**（8 个 SKILL.md）：当前 `# {skill-name} 技能指南` 格式一致性高但信息量低。可考虑改为描述性标题（如 `# 股价行情查询技能`、`# 年报 PDF 解析技能`），但会降低模板一致性，需权衡。

6. **引导段落补充**（8 个 SKILL.md）：H1 后可直接进入 `## 本技能核心能力`，无独立引导段落。可考虑在 H1 和 H2 之间增加 1-2 句引导文字（如 Cline 示例风格），但 Charles 当前结构已足够紧凑。

---

## 六、验证方法建议

### 6.1 结构一致性验证

1. **章节顺序一致性**：
   ```bash
   # 验证 8 个 SKILL.md 的 H2 章节顺序
   for f in agent_config/skills/*/SKILL.md; do
     echo "=== $f ==="
     grep "^## " "$f"
   done
   ```
   预期：所有技能的 H2 章节以 `## 本技能核心能力` 开头，以 `## 禁止行为` 结尾。

2. **Workflow Step 结构一致性**：
   ```bash
   # 验证每个 Step 都有结构化字段
   for f in agent_config/skills/*/SKILL.md; do
     echo "=== $f ==="
     grep -A 1 "^### Step" "$f" | grep "何时执行"
   done
   ```
   预期：每个 `### Step N` 后均有 `**何时执行**` 字段。

3. **frontmatter 字段一致性**：
   ```bash
   # 验证必备 frontmatter 字段
   for f in agent_config/skills/*/SKILL.md; do
     echo "=== $f ==="
     head -10 "$f" | grep -E "^(name|description|when_to_use):"
   done
   ```
   预期：8/8 技能均有 `name`、`description`、`when_to_use` 三个字段。

### 6.2 nanobot 残留验证

1. **SKILL.md nanobot 残留**：
   ```
   Grep "nanobot" agent_config/skills/ -i -r
   ```
   预期：No matches found（0 处残留）

2. **SKILL.md use_skill 残留**：
   ```
   Grep "use_skill" agent_config/skills/ -r
   ```
   预期：No matches found（SKILL.md 中无此关键词）

3. **always 字段使用范围**：
   ```
   Grep "^always:" agent_config/skills/ -r
   ```
   预期：仅 read-pdf/SKILL.md L5 匹配 `always: true`

### 6.3 Markdown 格式验证

1. **代码块语言标记**：
   ```bash
   # 统计代码块语言标记
   for f in agent_config/skills/*/SKILL.md; do
     echo "=== $f ==="
     grep -c '```bash' "$f"
   done
   ```
   预期：所有代码块均为 ` ```bash `，无 ` ```sh ` 或 ` ``` `（plain）

2. **标题层级**：
   ```bash
   # 验证无 H4+ 标题
   grep -rn "^####" agent_config/skills/*/SKILL.md
   ```
   预期：无匹配（最大层级为 H3）

3. **表格使用**：
   ```bash
   grep -rn "^|" agent_config/skills/*/SKILL.md
   ```
   预期：无匹配（8 个 SKILL.md 均不使用表格）
