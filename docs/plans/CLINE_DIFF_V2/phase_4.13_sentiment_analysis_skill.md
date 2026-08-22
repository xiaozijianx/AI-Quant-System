# Phase 4.13 — sentiment-analysis SKILL.md 对比报告

## 1. 任务范围

- Charles 源文件（本报告对象）：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\sentiment-analysis\SKILL.md`（91 行）
- Charles 原始版本（对照）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\sentiment-analysis\SKILL.md`（76 行）
- 脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\sentiment-analysis\scripts\`
  - `news_fetcher.py`（新闻抓取，Step 1 使用）
  - `sentiment_scorer.py`（情感评分，Step 2 使用）
  - `event_detector.py`（事件识别，Step 3 使用）
- Cline 对照样本：
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-ui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-desktop\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-cli\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\opentui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\cline-sdk\SKILL.md`
- `nanobot` 残留扫描：在 `agent_config\skills\sentiment-analysis\` 目录全文搜索 `nanobot`（大小写不敏感），**无任何匹配**；SKILL.md 正文中也无 `nanobot` 字样、无历史注释痕迹。

## 2. Cline 是否有同类技能

**结论：Cline 无财经新闻舆情 / 情感分析 / 事件驱动信号相关 SKILL.md。**

Cline 仓库内的 SKILL.md 共 6 份，全部围绕 Cline 自身的工程化场景：`publish-ui` / `publish-desktop` / `publish-cli`（npm & 桌面 & CLI 发布）、`opentui`（终端 UI 框架）、`cline-sdk`（Agent SDK）、`create-pull-request`（PR 流程）。没有任何新闻抓取、NLP 情感分析、贪婪/恐慌指数、事件驱动交易信号相关技能。

因此本报告转为：**评估 Charles 的 `sentiment-analysis/SKILL.md` 是否符合 Cline 的 SKILL.md 风格规范**，并标注与原 `charles-nanobot` 版本相比的迁移情况。

## 3. Cline 的 SKILL.md 风格规范（归纳自 6 份样本）

| 维度 | Cline 通用规范 |
|------|----------------|
| Frontmatter 字段 | 极简：`name` + `description`；大型技能额外加 `metadata.references`（见 opentui/cline-sdk）。**未见** `when_to_use` / `keywords` / `always` / `capabilities` 等 nanobot 风格字段 |
| description 风格 | 一段英文长句，说明 "Use when ..." 触发场景，避免逗号分隔的关键词列表 |
| 主体语言 | 英文为主；少量中文注释仅出现在引用项目内文件时 |
| 主体结构 | 标题 → 一句话引言 → `## Critical Rules`（可选）→ `## How to Use` / `## Workflow` / `## Release contract` → 编号 Step → `## Final report` / `## Resources` |
| 命令调用 | 使用 ```sh / ```bash 代码块；命令以仓库根目录为相对基准（如 `apps/cli/package.json`、`sdk/packages/ui/package.json`）|
| 行为约束 | 通过 "Always ask before ..." / "Do not guess" 等句子嵌入 Workflow 步骤，**不单独设"禁止行为"章节** |
| 决策树 | opentui/cline-sdk 使用 ASCII 决策树做场景路由；publish-* 系列使用编号 Workflow |
| 文件引用 | 大量使用相对路径指向仓库内文件，路径精确到具体文件名 |
| 前置条件 | 嵌在 `## Prerequisites Check` / `## Release contract` 中，不单独成章 |

## 4. Charles `agent_config` 版 SKILL.md 逐项对比

### 4.1 Frontmatter

Charles agent_config 版（第 1-5 行）：

```yaml
---
name: sentiment-analysis
description: "获取财经新闻、计算情感评分、识别事件驱动信号，用于个股/板块舆情分析"
when_to_use: "用户询问舆情/情感分析/新闻事件影响/事件驱动信号/板块情绪时"
---
```

Charles charles-nanobot 原版（第 1-9 行）：

```yaml
---
name: sentiment-analysis
description: "监控东方财富等新闻源，利用NLP分析市场情绪（贪婪/恐慌），捕捉事件驱动交易机会。在用户请求查看新闻、市场情绪时使用。"
keywords: 舆情, 情感分析, 新闻监控, 市场情绪, 资产重组, 事件驱动, 贪婪, 恐慌, 舆论, 消息面
capabilities:
  - 监控近期新闻舆情
  - 分析市场情绪倾向
  - 识别事件驱动型交易信号
---
```

| 字段 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 | 评估 |
|------|---------------------|------------------------------|------------|------|
| `name` | ✅ `sentiment-analysis` | ✅ `sentiment-analysis` | ✅ 必备 | 一致 |
| `description` | ✅ 简短中文一句话 + 能力列举 | ✅ 较长中文一句话 + 触发场景（含"贪婪/恐慌"等具体术语） | ✅ 必备，但 Cline 习惯 "Use when ..." 句式 | 字段存在，句式不符合 Cline "Use when ..." 风格；相比原版有所精简，丢失了"贪婪/恐慌""东方财富"等关键业务术语 |
| `when_to_use` | ✅ 存在（新增） | ❌ 不存在 | ❌ Cline 无此字段 | **nanobot 风格字段残留**（实现逻辑残留，非注释残留）。原版将触发场景写在 `description` 长句中，agent_config 版拆出独立字段 |
| `keywords` | ❌ 已移除 | ✅ `舆情, 情感分析, ...` | ❌ Cline 无此字段 | 已清理 |
| `capabilities` | ❌ 已移除 | ✅ 列表 3 项 | ❌ Cline 无此字段 | 已清理 |

**结论**：agent_config 版相比 charles-nanobot 原版**已大幅清理 frontmatter**（移除 `keywords` / `capabilities`），但**新增了 `when_to_use`**——这是 nanobot frontmatter 规范的字段，不符合 Cline 极简 `name + description` 规范。原版将触发场景写在 `description` 长句中，agent_config 版将其拆分到 `when_to_use`，方向与 Cline 规范相反（Cline 倾向把触发场景合并进 `description` 的 "Use when ..." 句式）。此外，description 由原版的"监控东方财富等新闻源，利用NLP分析市场情绪（贪婪/恐慌），捕捉事件驱动交易机会"精简为"获取财经新闻、计算情感评分、识别事件驱动信号"，丢失了"东方财富""贪婪/恐慌""交易机会"等关键业务信息。

### 4.2 主体结构

Charles agent_config 版章节顺序（91 行）：

1. `# sentiment-analysis 技能指南`（第 7 行）
2. `## 本技能核心能力`（第 9 行，含工作方式 3 步 + Step 2/3 独立性说明）
3. `## 场景路由`（第 20 行，4 条项目符号路由规则）
4. `## Workflow`（第 29 行）→ `### Step 1: 获取财经新闻数据（必需）` / `### Step 2: 计算情感评分（可选）` / `### Step 3: 识别事件驱动信号（可选）`
5. `## 脚本角色说明`（第 73 行）
6. `## 脚本调用规则`（第 81 行，3 条规则）
7. `## 禁止行为`（第 87 行，3 条禁止项）

Charles charles-nanobot 原版章节顺序（76 行）：

1. `# sentiment-analysis 技能指南`
2. `## 适用场景`（4 条项目符号）
3. `## 数据来源`（3 条：东方财富/公告/央视）
4. `## 依赖技能`（read-pdf / write-report 联动）
5. `## 可用脚本`（markdown 表格：脚本/功能/参数）
6. `## 关键词过滤体系`（利好/利空/政策三类关键词列表）
7. `## 工作流程`（4 步编号列表，无 Step 标题）
8. `## 示例对话`（3 个用户示例 + 步骤）

与 Cline 规范对照：

| Charles agent_config 章节 | Cline 是否常见 | 评估 |
|--------------------------|----------------|------|
| 本技能核心能力 | Cline 通常用标题下一句话引言代替 | 风格略不同，可接受；Step 2/3 独立性说明是 Charles 独有增强 |
| 场景路由 | Cline 用 ASCII 决策树（opentui/cline-sdk）或编号 Step | **形式不同**：Charles 用项目符号列表，Cline 用决策树。功能等价 |
| Workflow / Step 1-3 | ✅ 与 Cline `## Workflow` + 编号 Step 一致 | 已对齐 Cline 风格，且比原版的简单编号列表有显著改进 |
| 脚本角色说明 | Cline 不单独列脚本角色，命令直接嵌在 Step 中 | 偏 nanobot 风格（原版有 `## 可用脚本` 表格） |
| 脚本调用规则 | Cline 通过 "Always ..." 句式嵌入步骤，不单独成章 | 偏 nanobot 风格 |
| 禁止行为 | Cline **无此章节**，行为约束嵌入 Workflow | **nanobot 风格残留** |

**与原版结构差异**：
- 原版章节：`适用场景` → `数据来源` → `依赖技能` → `可用脚本（表格）` → `关键词过滤体系` → `工作流程` → `示例对话`
- agent_config 版**移除了"示例对话"章节**（向 Cline Step 风格靠拢）
- agent_config 版**移除了"可用脚本"表格**，改为 `## 脚本角色说明` 项目符号列表
- agent_config 版**移除了"数据来源"章节**（东方财富/公告/央视三类来源信息丢失）
- agent_config 版**移除了"依赖技能"章节**（read-pdf / write-report 联动说明丢失）
- agent_config 版**移除了"关键词过滤体系"章节**（利好/利空/政策三类关键词列表丢失，但该信息仍保留在 `event_detector.py` 的 `EVENT_KEYWORDS` 字典中）
- agent_config 版**新增了 `## Workflow` + `### Step 1/2/3` 结构**（向 Cline 风格靠拢）
- agent_config 版**新增了 `## 场景路由` / `## 脚本调用规则` / `## 禁止行为`** 章节

**结论**：agent_config 版**已部分对齐 Cline 风格**（引入 `## Workflow` + `### Step` 结构、移除示例对话），但保留 `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 三个章节，属于 nanobot 风格的主体结构残留。同时移除了原版的"数据来源""依赖技能""关键词过滤体系"三个业务信息章节，丢失了部分业务上下文。

### 4.3 脚本调用

| 维度 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 |
|------|---------------------|------------------------------|------------|
| 命令格式 | `python agent_config/skills/sentiment-analysis/scripts/news_fetcher.py --stock <股票代码> --days 30` | `python skills/sentiment-analysis/scripts/news_fetcher.py --stock 002594 --days 7` | 命令以仓库根目录为相对基准 |
| 路径前缀 | ✅ `agent_config/skills/...`（适配新目录结构） | `skills/...`（charles-nanobot 目录结构） | ✅ Charles agent_config 版路径与 Cline 风格一致（相对仓库根） |
| 代码块语言 | ```bash | 无代码块（命令内嵌文本与示例对话） | ```sh / ```bash |
| 参数说明 | ✅ 参数列表 + 必填/可选标注 | 表格形式（脚本/功能/参数） | Cline 通常用列表说明参数 |
| 参数与脚本一致性 | ❌ **SKILL.md 描述的参数与脚本实际参数严重不一致**（详见 4.3.1） | ✅ 原版参数与脚本一致 | Cline 强调命令准确，参数不一致会违反 Cline 风格 |

**结论**：脚本调用部分**形式上已对齐 Cline 风格**——使用 ```bash 代码块、路径相对仓库根、参数有必填/可选标注。相比 charles-nanobot 原版（命令内嵌文本、无代码块）有显著改进。但**存在一个严重的文档与实现不一致问题**：SKILL.md 中描述的 Step 2 / Step 3 命令参数与脚本实际接受的参数完全不匹配，会导致 agent 严格按 SKILL.md 调用时脚本直接报错。

#### 4.3.1 SKILL.md 命令参数与脚本实际参数严重不一致（重要发现）

**SKILL.md 第 52-54 行描述的 Step 2 命令**：
```bash
python agent_config/skills/sentiment-analysis/scripts/sentiment_scorer.py --stock <股票代码>
```

**SKILL.md 第 66-68 行描述的 Step 3 命令**：
```bash
python agent_config/skills/sentiment-analysis/scripts/event_detector.py --stock <股票代码>
```

**`sentiment_scorer.py` 第 203-208 行实际接受的参数**：
```python
parser.add_argument("--news_file", required=True, help="新闻 JSON 文件路径")
parser.add_argument("--output_dir", default="./output", help="输出目录")
parser.add_argument("--model", default="qwen-turbo", help="LLM 模型（默认 qwen-turbo）")
parser.add_argument("--max_news", type=int, default=50, help="最大分析条数（默认 50）")
```

**`event_detector.py` 第 176-181 行实际接受的参数**：
```python
parser.add_argument("--news_file", required=True, help="新闻 JSON 文件路径")
parser.add_argument("--output_dir", default="./output", help="输出目录")
parser.add_argument("--model", default="qwen-turbo", help="LLM 模型")
parser.add_argument("--use_llm", action="store_true", help="使用 LLM 进行精细事件识别")
```

**不一致点**：
1. SKILL.md 的 Step 2 / Step 3 命令使用 `--stock` 参数，但 `sentiment_scorer.py` 和 `event_detector.py` **均不接受 `--stock` 参数**，而是要求 `--news_file`（必填）
2. 脚本的 `--news_file` 参数在 SKILL.md 中**未提及**，该参数应指向 Step 1 `news_fetcher.py` 输出的 JSON 文件（如 `./data/600519_news.json`）
3. SKILL.md 描述的语义（直接传股票代码进行情感评分/事件识别）与脚本实际语义（基于 Step 1 生成的新闻 JSON 文件进行情感评分/事件识别）不符
4. 脚本的 `--output_dir` / `--model` / `--max_news` / `--use_llm` 等可选参数在 SKILL.md 中均未提及

**影响**：若 agent 严格按 SKILL.md 第 52-54 行的命令调用 `sentiment_scorer.py --stock 600519`，脚本会因 `argparse` 收到未知参数 `--stock` 且缺少必填的 `--news_file` 而直接报错退出。Step 3 的 `event_detector.py --stock 600519` 同理。

**与原版对比**：charles-nanobot 原版 SKILL.md 第 33-34 行的参数描述是**正确的**：
- `sentiment_scorer.py`：`--news_file`, `--output_dir`（与脚本一致）
- `event_detector.py`：`--news_file`, `--output_dir`（与脚本一致）

原版示例对话也正确使用了 `--news_file data/002594_news.json`。说明不一致是在 agent_config 迁移时**新引入**的，迁移过程中试图把"工程视角"命令（传 news_file）改写为"用户视角"命令（传 stock），但未同步修改脚本实现，导致文档与实现脱节。

**性质判定**：此为**实现逻辑残留**——SKILL.md 描述的命令形式（`--stock` 直接评分/识别）更接近 nanobot 风格的"用户视角"命令，而脚本实际实现是"基于新闻 JSON 文件"的"工程视角"命令。两者未对齐，属于迁移过程中未完成的逻辑清理。这与 P4.11 `write-report` 的 `--stock` / `--title` vs `--analysis_file` 不一致问题模式完全一致。

#### 4.3.2 news_fetcher.py 参数与 SKILL.md 的次要不一致

| 参数 | SKILL.md 描述 | 脚本实际（news_fetcher.py L210-214） | 一致性 |
|------|--------------|--------------------------------------|--------|
| `--stock` | 必填，不带交易所后缀 | 可选（`default=None`），与 `--keywords` 至少传一个 | ⚠️ SKILL.md 标"必填"，实际为可选（支持仅用 `--keywords` 搜索通用新闻） |
| `--days` | 可选，默认 `30` | 可选，默认 `7` | ❌ 默认值不一致（SKILL.md 说 30，脚本说 7） |
| `--keywords` | **未提及** | 可选，逗号分隔关键词 | ❌ **重要参数遗漏**：原版 SKILL.md 有 `--keywords 资产重组` 用法示例，agent_config 版完全丢失，导致"事件识别"场景下用户问"最近A股有没有资产重组的消息"时 agent 无从下手 |
| `--output_dir` | 未提及 | 可选，默认 `./data` | ⚠️ 未文档化 |
| `--include_cctv` | 未提及 | 可选，是否包含央视新闻 | ⚠️ 未文档化 |

**输出路径不一致**：SKILL.md 第 42 行称 Step 1 输出"新闻列表 JSON 文件（保存到 `data/news_data/`）"，但 `news_fetcher.py` 第 213 行 `--output_dir` 默认值为 `./data`（非 `data/news_data/`），输出文件命名为 `{stock}_news.json`（第 280 行）。SKILL.md 的输出路径描述与脚本实际不符。

### 4.4 形式风格

| 维度 | Charles agent_config | Cline 规范 |
|------|---------------------|------------|
| 语言 | 中文 | 英文为主 |
| 语气 | 偏指令式（"禁止..."、"必须..."） | 偏协作式（"Always ask before..."、"Do not guess"） |
| 长度 | 约 91 行，简洁 | publish-cli 约 266 行，create-pull-request 约 211 行；opentui/cline-sdk 较短 |
| 失败处理 | ✅ Step 1 单列"失败处理"子项，列 2 种错误场景 | ✅ Cline 也常在 Step 内列 "If ... " 失败处理 |
| 示例对话 | ❌ 已移除（原版有 3 个示例对话） | Cline 不用示例对话，用 Step 描述 |
| 场景路由 | ✅ 4 条项目符号路由规则（情感评分/事件识别/完整分析/仅下载） | Cline 用 ASCII 决策树或编号 Step |
| 前置条件 | ✅ 每个 Step 显式列"前置条件"（如 Step 2 前置条件为 Step 1 已获取新闻） | Cline 偶尔在 Step 内提"Before proceeding" |
| 跳过条件 | ✅ Step 2/3 显式列"跳过条件"（Charles 独有增强，强调独立性） | Cline 无显式跳过条件 |

**结论**：中文表达本身不违反 Cline 规范（Cline 无明文规定语言），但与 Cline 6 份样本全英文相比存在风格偏差。Charles agent_config 版**移除了原版的"示例对话"章节**，向 Cline 的 Step 描述风格靠拢，是合理的迁移。每个 Step 显式标注"何时执行/前置条件/命令/参数/预期输出/失败处理/跳过条件"七要素，结构化程度高于原版，但比 Cline 的散文式 Step 描述更机械。Step 2/3 的"跳过条件"是 Charles 独有的良好增强，清晰表达了两个可选 Step 的独立性。

## 5. 残留分类

### 5.1 注释残留

**无。** `agent_config\skills\sentiment-analysis\` 目录全文搜索 `nanobot` 零匹配；SKILL.md 正文中也无 `nanobot` 字样、无历史注释痕迹、无"对标 nanobot"等 docstring 残留。

### 5.2 实现逻辑残留（nanobot 风格残留）

| 残留项 | 位置 | 说明 | 性质 |
|--------|------|------|------|
| `when_to_use` frontmatter 字段 | 第 4 行 | nanobot frontmatter 规范字段，Cline 用 `description` 内 "Use when ..." 句式代替。**注意**：原版 charles-nanobot 无此字段（用 `description` 长句 + `keywords`），agent_config 版迁移时**主动引入**，属 nanobot 风格残留 | 实现逻辑残留 |
| `## 脚本角色说明` 章节 | 第 73-79 行 | nanobot 习惯单独列脚本角色（原版 `## 可用脚本` 表格）；Cline 把脚本信息直接嵌在 Workflow Step 中 | 实现逻辑残留 |
| `## 脚本调用规则` 章节 | 第 81-85 行 | nanobot 习惯单独列调用规则；Cline 用 "Always ..." 句式嵌入步骤 | 实现逻辑残留 |
| `## 禁止行为` 章节 | 第 87-91 行 | nanobot 习惯单独设禁止章节；Cline 无此章节，行为约束嵌入 Workflow（用 "Do not ..." 句式） | 实现逻辑残留 |
| `## 场景路由` 项目符号列表 | 第 20-27 行 | nanobot 用项目符号（原版 `## 适用场景` 项目符号）；Cline 用 ASCII 决策树（opentui/cline-sdk 风格）或编号 Step | 形式风格残留（轻度） |
| SKILL.md 命令参数与脚本不一致（Step 2/3） | 第 52-54 行 / 第 66-68 行 | SKILL.md 描述 `--stock`，脚本实际接受 `--news_file`。nanobot 风格的"用户视角"命令（直接传股票代码）与脚本"工程视角"命令（传新闻 JSON 文件）未对齐 | 实现逻辑残留（重要，阻塞性） |

### 5.3 已正确迁移的部分

| 迁移项 | 原版 → agent_config 版 |
|--------|------------------------|
| Frontmatter 瘦身 | 移除 `keywords` / `capabilities`（原版有，新版无） |
| 引入 Workflow 结构 | 原版 `## 工作流程` 4 步编号列表 → 新版 `## Workflow` + `### Step 1-3` 含七要素 |
| 命令代码块化 | 原版命令内嵌文本与示例对话，新版用 ```bash 代码块 |
| 路径前缀调整 | `skills/...` → `agent_config/skills/...`（适配新目录） |
| 移除示例对话 | 原版有 `## 示例对话`（3 个用户示例），新版移除（向 Cline Step 风格靠拢） |
| 移除可用脚本表格 | 原版 `## 可用脚本` markdown 表格 → 新版 `## 脚本角色说明` 列表（更简洁） |
| 细化失败处理 | 原版无失败处理 → 新版 Step 1 含"失败处理"子项 |
| 细化前置条件 | 原版无前置条件 → 新版每个 Step 含"前置条件"子项 |
| 新增跳过条件 | 新版 Step 2/3 含"跳过条件"子项，明确两 Step 独立性（Charles 独有增强） |
| 新增场景路由 | 新版 `## 场景路由` 4 条路由规则，明确不同用户意图的执行路径 |

### 5.4 功能缺失/不一致（非 nanobot 残留，需关注）

| 缺失/不一致项 | 原版 → agent_config 版 | 影响 |
|---------------|------------------------|------|
| Step 2/3 命令参数错误 | 原版 `--news_file`（正确）→ 新版 `--stock`（错误） | **阻塞性**：agent 按 SKILL.md 调用会报错 |
| `--keywords` 参数遗漏 | 原版有 `--keywords 资产重组` 用法 → 新版完全未提及 | **重要**：丢失"关键词搜索通用新闻"能力，"事件识别"场景受限 |
| `--days` 默认值不一致 | SKILL.md 标默认 30，脚本实际默认 7 | 轻度：agent 按 SKILL.md 传 30 仍可工作，但描述不准 |
| 输出路径不一致 | SKILL.md 标 `data/news_data/`，脚本实际默认 `./data/` | 轻度：agent 不知 Step 1 输出文件的确切路径，无法构造 Step 2/3 的 `--news_file` 参数 |
| 数据来源章节丢失 | 原版 `## 数据来源`（东方财富/公告/央视）→ 新版移除 | 轻度：丢失新闻来源信息，但脚本内部仍支持 |
| 依赖技能章节丢失 | 原版 `## 依赖技能`（read-pdf / write-report 联动）→ 新版移除 | 轻度：丢失技能协作说明，但可在 agent 运行时动态决策 |
| 关键词过滤体系丢失 | 原版 `## 关键词过滤体系`（利好/利空/政策三类）→ 新版移除 | 轻度：信息仍保留在 `event_detector.py` 的 `EVENT_KEYWORDS` 字典中，但 SKILL.md 层面不可见 |
| description 业务术语丢失 | 原版"东方财富/贪婪/恐慌/交易机会" → 新版"财经新闻/情感评分/事件驱动信号" | 轻度：description 更通用但丢失关键业务上下文 |

## 6. 与 Cline 风格的一致性总评

| 维度 | 一致性 | 说明 |
|------|--------|------|
| Frontmatter 字段集 | ⚠️ 部分一致 | `name` + `description` 一致；`when_to_use` 多余且为新增（原版无） |
| 主体结构 | ⚠️ 部分一致 | 引入 `## Workflow` + `### Step 1-3` ✅；保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）⚠️ |
| 脚本调用 | ❌ 形式一致但内容不一致 | 代码块、相对路径、参数标注均符合 Cline 风格 ✅；但 SKILL.md 描述的 Step 2/3 参数与脚本实际参数完全不匹配 ❌；`--keywords` 重要参数遗漏 ❌ |
| 形式风格 | ⚠️ 部分一致 | 中文表达与 Cline 全英文样本有偏差；语气偏指令式；Step 七要素结构化程度高于 Cline 散文式 |
| 行为约束方式 | ⚠️ 部分一致 | 单列 `## 禁止行为`，未嵌入 Workflow；Cline 用 "Do not ..." 嵌入 Step |
| 场景路由 | ⚠️ 部分一致 | 项目符号列表 vs Cline 决策树；功能等价 |
| 目录迁移彻底性 | ✅ 一致 | 脚本路径统一为 `agent_config/skills/...` 前缀 |
| Step 独立性表达 | ✅ 增强 | Step 2/3 显式"跳过条件"是 Charles 独有增强，比 Cline 更清晰地表达可选 Step 的独立性 |

**总体**：Charles `agent_config/skills/sentiment-analysis/SKILL.md` 已完成约 55% 的 Cline 风格迁移，主要差距在：
1. frontmatter 仍保留 `when_to_use`（且为迁移中间态新增，非原版遗留）；
2. 主体仍保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）；
3. **SKILL.md 命令参数与脚本实际参数严重不匹配**（最重要的问题，Step 2/3 的 `--stock` vs `--news_file` 不一致，影响实际可用性）；
4. `--keywords` 重要参数遗漏，丢失原版的"关键词搜索通用新闻"能力；
5. 输出路径与默认值描述不准（`data/news_data/` vs `./data/`、`--days` 默认 30 vs 7）。

与 P4.11 `write-report` 对比：两者迁移程度与残留模式高度一致（均约 55% 迁移，均保留 `when_to_use` + `## 脚本角色说明` + `## 脚本调用规则` + `## 禁止行为`，均存在 SKILL.md 命令参数与脚本实际参数不匹配的阻塞性问题——`--stock` vs `--news_file` / `--analysis_file`），说明这是 Charles 项目层面的统一风格选择与统一迁移缺陷，非个例疏漏。

## 7. 改进建议（仅供参考，不在本任务范围内执行）

1. **修复 SKILL.md Step 2/3 命令参数与脚本不一致（P0，阻塞性）**：
   - 方案 A（改 SKILL.md，推荐）：将 Step 2 命令改为 `python agent_config/skills/sentiment-analysis/scripts/sentiment_scorer.py --news_file data/<股票代码>_news.json`，将 Step 3 命令改为 `python agent_config/skills/sentiment-analysis/scripts/event_detector.py --news_file data/<股票代码>_news.json`，与脚本实际参数对齐。同时在 Step 1 的"预期输出"中明确输出文件路径（如 `data/600519_news.json`），以便 agent 构造 Step 2/3 的 `--news_file` 参数。
   - 方案 B（改脚本）：将 `sentiment_scorer.py` / `event_detector.py` 改为接受 `--stock` 参数，内部自动查找 `data/{stock}_news.json` 文件（需重构脚本逻辑，且无法处理 `--keywords` 搜索的无 stock 场景）。
   - 推荐方案 A，因为脚本当前的"基于新闻 JSON 文件"逻辑更灵活，且原版 charles-nanobot 的参数描述本身就是正确的（`--news_file`），属 agent_config 迁移时引入的回归。

2. **补充 `--keywords` 参数文档（P1）**：在 Step 1 的参数说明中补充 `--keywords`（可选，逗号分隔关键词，如 `资产重组,回购`），并在 `## 场景路由` 中增加"用户询问某类事件（如'最近A股有没有资产重组的消息'）"分支，执行 `news_fetcher.py --keywords 资产重组 --days 3`。原版示例对话有此用法，agent_config 版不应丢失。

3. **修正 `--days` 默认值与输出路径描述（P2）**：
   - 将 Step 1 参数说明中 `--days` 默认值由 `30` 改为 `7`，与脚本 `news_fetcher.py` L212 一致。
   - 将 Step 1"预期输出"中 `data/news_data/` 改为 `data/`（或 `./data/`），与脚本 `--output_dir` 默认值 `./data` 一致。

4. **Frontmatter**：删除 `when_to_use`，把其内容改写为 "Use when ..." 句式合并进 `description`，例如：`description: "Fetch financial news, compute sentiment scores, and identify event-driven signals for stock/sector sentiment analysis. Use when the user asks about sentiment analysis, news impact, event-driven signals, or sector sentiment."`

5. **章节合并**：把 `## 脚本角色说明` 与 `## 脚本调用规则` 合并进 `## Workflow` 的对应 Step，用 "Always ..." 句式表达约束。例如 Step 1 内已说明 `news_fetcher.py` 用途，`## 脚本角色说明` 可移除。

6. **禁止行为嵌入**：把 `## 禁止行为` 的 3 条约束改写为 "Do not ..." 句式，嵌入对应 Step 中。例如"禁止跳过 Step 1"可并入 Step 2/3 的"前置条件"；"禁止用 web_search 替代"可并入 Step 1 的"失败处理"。

7. **恢复业务上下文（可选）**：考虑在 Step 1 或 `## 脚本角色说明` 中补充新闻来源信息（东方财富个股新闻/上市公司公告/央视新闻），以及 `event_detector.py` 支持的事件分类（利好/利空/政策三类），原版 `## 数据来源` 与 `## 关键词过滤体系` 的信息对 agent 理解脚本能力有帮助。

8. **场景路由决策树（可选）**：把 `## 场景路由` 改为 ASCII 决策树，与 opentui/cline-sdk 风格一致。

9. **语言（可选）**：若希望完全对齐 Cline 风格，可将主体改写为英文；但若 Charles 项目其他 SKILL.md 均为中文，保持中文一致性亦可接受。

## 8. 关键文件路径汇总

- Charles agent_config SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\sentiment-analysis\SKILL.md`
- Charles charles-nanobot 原版 SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\sentiment-analysis\SKILL.md`
- Charles 脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\sentiment-analysis\scripts\`
  - `news_fetcher.py`（新闻抓取，参数：`--stock` / `--keywords` / `--days` / `--output_dir` / `--include_cctv`，输出 `{stock}_news.json`）
  - `sentiment_scorer.py`（情感评分，参数：`--news_file`（必填）/ `--output_dir` / `--model` / `--max_news`）
  - `event_detector.py`（事件识别，参数：`--news_file`（必填）/ `--output_dir` / `--model` / `--use_llm`）
- Cline 对照样本目录：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\` 与 `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\`
- 本报告：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_4.13_sentiment_analysis_skill.md`
