# Phase 4.9 — read-pdf SKILL.md 对比报告

## 1. 任务范围

- Charles 源文件：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\read-pdf\SKILL.md`（124 行）
- Charles 原始版本（对照）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\read-pdf\SKILL.md`（119 行）
- 脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\read-pdf\scripts\`（含 `query_report.py` / `fetch_report_pdf.py` / `build_index.py` / `parse_pdf_basic.py` / `parse_pdf_ocr.py` / `fetch_financial_data.py`）
- Cline 对照样本：
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-ui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-desktop\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-cli\SKILL.md`（266 行，最详尽样本）
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\opentui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\cline-sdk\SKILL.md`
- `nanobot` 残留扫描：在 `agent_config\skills\read-pdf\` 目录（含 SKILL.md 与 scripts/）全文搜索 `nanobot` 与 `use_skill`，**无任何匹配**。

## 2. Cline 是否有同类技能

**结论：Cline 无 PDF / 年报 / 文档处理相关 SKILL.md。**

对 Cline 仓库内全部 6 份 SKILL.md 做 `pdf|annual.report|年报` 关键词搜索，**零匹配**。Cline 的 6 份技能全部围绕自身工程化场景：`publish-ui` / `publish-desktop` / `publish-cli`（npm & 桌面发布）、`opentui`（终端 UI 框架）、`cline-sdk`（Agent SDK）、`create-pull-request`（PR 流程）。没有任何 RAG、PDF 解析、巨潮资讯下载、向量索引、年报叙述性内容检索相关技能。

因此本报告转为：**评估 Charles 的 `read-pdf/SKILL.md` 是否符合 Cline 的 SKILL.md 风格规范**，并标注与原 `charles-nanobot` 版本相比的迁移情况。

## 3. Cline 的 SKILL.md 风格规范（归纳自 6 份样本）

| 维度 | Cline 通用规范 |
|------|----------------|
| Frontmatter 字段 | 极简：`name` + `description`；大型技能额外加 `metadata.references`（见 opentui/cline-sdk）。**未见** `when_to_use` / `keywords` / `always` / `capabilities` 等扩展字段 |
| description 风格 | 一段英文长句，说明 "Use when ..." 触发场景，避免逗号分隔的关键词列表 |
| 主体语言 | 英文为主；少量中文注释仅出现在引用项目内文件时 |
| 主体结构 | 标题 → 一句话引言 → `## Critical Rules`（可选）→ `## How to Use` / `## Workflow` / `## Release contract` → 编号 Step → `## Final report` / `## Resources` |
| 命令调用 | 使用 ```sh / ```bash 代码块；命令以仓库根目录为相对基准（如 `apps/cli/package.json`、`sdk/packages/ui/package.json`）|
| 行为约束 | 通过 "Always ask before ..." / "Do not guess" 等句子嵌入 Workflow 步骤，**不单独设"禁止行为"章节** |
| 决策树 | opentui/cline-sdk 使用 ASCII 决策树做场景路由；publish-* 系列使用编号 Workflow |
| 文件引用 | 大量使用相对路径指向仓库内文件，路径精确到具体文件名 |

## 4. Charles `agent_config` 版 SKILL.md 逐项对比

### 4.1 Frontmatter

Charles agent_config 版（第 1-6 行）：

```yaml
---
name: read-pdf
description: "查询上市公司年报/季报/公告等PDF叙述性内容，支持本地RAG查询；若本地无索引/PDF，自动下载并构建索引"
when_to_use: "用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"
always: true
---
```

Charles charles-nanobot 原版（第 1-9 行）：

```yaml
---
name: read-pdf
description: "基于本地PDF知识库进行RAG问答，也支持从巨潮资讯网下载新的PDF报告并自动更新索引。在用户请求查询研报/年报/公告内容、读取PDF中的财务数据、下载年报时使用。结构化CSV财务数据请用 financial-analysis 技能。"
keywords: 财报, 年报, PDF, 读取, 解析, 财务报表, 资产负债表, 利润表, 现金流, 公告, 阅读, 分析
capabilities:
  - 基于本地PDF知识库进行问答
  - 下载PDF年报/季报并更新索引
  - 从PDF叙述性内容中提取业务/订单/风险信息
---
```

| 字段 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 | 评估 |
|------|---------------------|------------------------------|------------|------|
| `name` | ✅ `read-pdf` | ✅ `read-pdf` | ✅ 必备 | 一致 |
| `description` | ✅ 简短中文一句话 | ✅ 较长中文一句话 + 触发场景 + 与 financial-analysis 的边界 | ✅ 必备，但 Cline 习惯 "Use when ..." 句式 | 字段存在，但句式不符合 Cline "Use when ..." 风格 |
| `when_to_use` | ✅ 存在（agent_config 新增） | ❌ 不存在（原版用 `keywords`） | ❌ Cline 无此字段 | **nanobot 风格字段**：agent_config 用 `when_to_use` 替代原版 `keywords`，仍是 nanobot 风格的"独立触发字段"，不符合 Cline 把触发场景并入 `description` 的规范 |
| `keywords` | ❌ 已移除 | ✅ 逗号分隔关键词列表 | ❌ Cline 无此字段 | 已清理 |
| `capabilities` | ❌ 已移除 | ✅ 列表 | ❌ Cline 无此字段 | 已清理 |
| `always` | ✅ `true`（agent_config 新增） | ❌ 原版无此字段 | ❌ Cline 无此字段 | **Charles 扩展字段**：标记本技能为"always-on"自动加载（对应 P4.1 中 `get_always_skills()` 机制）。**注意**：原版 read-pdf 并无 `always` 字段，agent_config 是**新增**该字段；这与 stock-price（原版有 `always: true`，agent_config 移除）方向相反。属于 Charles 自有功能扩展，非 nanobot 残留，但不符合 Cline 极简 frontmatter 规范 |

**结论**：agent_config 版相比 charles-nanobot 原版**已清理 `keywords` / `capabilities`** 两个 nanobot 字段，但**新增了 `when_to_use` 与 `always: true` 两个字段**。其中：
- `when_to_use` 是 nanobot 风格的独立触发字段（Cline 用 `description` 内 "Use when ..." 句式代替），属风格残留；
- `always: true` 是 Charles 自有的"自动加载"功能标记，原版 read-pdf 并无此字段，属 Charles 扩展而非残留，但同样不符合 Cline 极简 frontmatter 规范。

### 4.2 主体结构

Charles agent_config 版章节顺序（共 9 个章节）：

1. `# read-pdf 技能指南`
2. `## 本技能核心能力`（含工作方式 3 步、适用内容、与 financial-analysis 的边界）
3. `## 场景路由`（项目符号列表，3 种场景）
4. `## Workflow` → `### Step 1: 尝试直接查询本地 RAG 索引` / `### Step 2: 下载年报 PDF 并构建索引` / `### Step 3: 下载完成后再次查询`
5. `## 脚本角色说明`（主脚本 / 内部脚本分类列表）
6. `## 脚本调用规则`（5 条编号规则）
7. `## 年报年份规则`（含"当前日期 2026-07-27"硬编码）
8. `## 数据源选择`（项目符号列表 4 条）
9. `## 终端监控说明`（项目符号列表 3 条）
10. `## 禁止行为`（5 条禁止项）

Charles charles-nanobot 原版章节顺序（共 7 个章节）：

1. `# read-pdf 技能指南`
2. `## 适用场景`（项目符号列表 4 条）
3. `## 年报年份与报告期说明（重要）`（含发布年份/报告期年份说明、本地知识库覆盖范围、数据源选择规则表、用户表述与实际对应关系表、操作原则 3 条）
4. `## 两种解析模式`（模式一 PyPDF2 / 模式二 多模态大模型）
5. `## 可用脚本`（表格列出 6 个脚本及参数）
6. `## 执行流程（必须遵守）`（推荐方式 / 回退方式 / 新增 PDF 处理 + 禁止行 + 相对路径注意）
7. `## 示例对话`（2 个示例）

与 Cline 规范对照：

| Charles 章节 | Cline 是否常见 | 评估 |
|--------------|----------------|------|
| 本技能核心能力 | Cline 通常用标题下一句话引言代替 | 风格略不同，可接受 |
| 场景路由 | Cline 用 ASCII 决策树（opentui/cline-sdk）或编号 Step | **形式不同**：Charles 用项目符号列表，Cline 用决策树。功能等价 |
| Workflow / Step 1-3 | ✅ 与 Cline `## Workflow` + 编号 Step 一致 | **已对齐 Cline 风格**（agent_config 新增，原版无此结构） |
| 脚本角色说明 | Cline 不单独列脚本角色，命令直接嵌在 Step 中 | **偏 nanobot 风格**（原版有 `## 可用脚本` 表格，agent_config 改为列表但仍单独成章） |
| 脚本调用规则 | Cline 通过 "Always ..." 句式嵌入步骤，不单独成章 | **偏 nanobot 风格** |
| 年报年份规则 | Cline 无此章节（Cline 技能不涉及金融年份语义） | Charles 业务特有，原版有更详尽的表格，agent_config 精简为 4 条 |
| 数据源选择 | Cline 无此章节 | Charles 业务特有，原版有表格，agent_config 改为列表 |
| 终端监控说明 | Cline 无此章节 | Charles 独有（描述前端工具卡片实时显示终端输出），属 Charles 平台特性 |
| 禁止行为 | Cline **无此章节**，行为约束嵌入 Workflow | **nanobot 风格残留**（原版有 `禁止: 安装依赖...` 独立行，agent_config 扩展为 5 条禁止项章节） |

**结论**：agent_config 版**已部分对齐 Cline 风格**——引入 `## Workflow` + `### Step 1/2/3` 结构（原版无），并将原版的"执行流程"重写为 Step 形式。但保留 `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 三个 nanobot 风格章节。同时**移除了原版的"示例对话"和"两种解析模式"详尽表格**，向 Cline 的 Step 描述风格靠拢。

### 4.3 脚本调用

| 维度 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 |
|------|---------------------|------------------------------|------------|
| 命令格式 | `python agent_config/skills/read-pdf/scripts/query_report.py --index_dir data/vector_store --query "..." --stock <代码>` | `python skills/read-pdf/scripts/query_report.py --index_dir data/vector_store --query "问题" --stock 688981` | 命令以仓库根目录为相对基准 |
| 路径前缀 | ✅ `agent_config/skills/...`（适配新目录结构） | `skills/...`（charles-nanobot 目录结构） | ✅ Charles agent_config 版路径与 Cline 风格一致（相对仓库根） |
| 代码块语言 | ```bash | 无代码块（命令内嵌文本，如 `python skills/read-pdf/scripts/parse_pdf_basic.py --pdf <PDF路径> --output_dir <输出目录>`） | ```sh / ```bash |
| 参数说明 | ✅ 每步命令下用项目符号列表标注 `--index_dir` (必填) / `--query` (必填) / `--stock` (必填) | 表格形式（`## 可用脚本` 表格列出参数） | Cline 通常用列表说明参数 |
| 内部脚本隔离 | ✅ 明确区分"主脚本"与"内部脚本"，禁止 agent 直接调用 `parse_pdf_basic.py` / `parse_pdf_ocr.py` / `build_index.py` | ❌ 原版把所有脚本平等列为"可用脚本"，agent 可直接调用 | Cline 无此概念，但 Charles 的隔离设计合理 |

**结论**：脚本调用部分**已完全对齐 Cline 风格**——使用 ```bash 代码块、路径相对仓库根（`agent_config/skills/...`）、参数有必填/可选标注。相比 charles-nanobot 原版（命令内嵌文本、无代码块、路径前缀为 `skills/`）有显著改进。此外，agent_config 版**新增了"主脚本 vs 内部脚本"的隔离设计**，明确 `fetch_report_pdf.py` 会自动调用底层解析脚本，agent 不应直接调用内部脚本——这是原版没有的清晰约束，属于合理的工程化改进。

### 4.4 形式风格

| 维度 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 |
|------|---------------------|------------------------------|------------|
| 语言 | 中文 | 中文 | 英文为主 |
| 语气 | 偏指令式（"禁止..."、"必须..."、"不要..."） | 偏指令式（"必须遵守"、"禁止: 安装依赖"） | 偏协作式（"Always ask before..."、"Do not guess"） |
| 长度 | 约 124 行，简洁 | 约 119 行，含详尽表格 | publish-cli 约 266 行，较详尽 |
| 失败处理 | ✅ 每个 Step 内单列"失败处理"子项（Step 1 失败→Step 2；Step 2 失败→提示网络/确认代码） | ✅ 有"回退方式"说明 | ✅ Cline 也常在 Step 内列 "If ... " 失败处理 |
| 示例对话 | ❌ 已移除（原版有 2 个示例对话） | ✅ 2 个示例对话 | Cline 不用示例对话，用 Step 描述 |
| 表格使用 | ❌ 已移除原版的 3 个表格（数据源选择表、用户表述对应表、可用脚本表） | ✅ 3 个表格 | Cline opentui 用表格列 reference 文件结构 |
| 硬编码日期 | ⚠️ 第 101 行 "当前日期 2026-07-27，最新完整年报为 2025 年年报。" | ❌ 无硬编码日期 | Cline 无日期硬编码 |

**结论**：
- 中文表达本身不违反 Cline 规范（Cline 无明文规定语言），但与 Cline 6 份样本全英文相比存在风格偏差。Charles 项目其他 SKILL.md 均为中文，保持中文一致性可接受。
- agent_config 版**移除了原版的"示例对话"和 3 个表格**，向 Cline 的 Step 描述风格靠拢，是合理的迁移。
- **第 101 行硬编码日期 "2026-07-27"** 是潜在的维护隐患——该日期会随时间失效，导致"最新完整年报"判断错误。原版无此硬编码，agent_config 新增。建议改为动态提示或移除具体日期。

## 5. 残留分类

### 5.1 注释残留

**无。** 在 `agent_config\skills\read-pdf\` 目录（含 SKILL.md 与 scripts/ 全部 .py 文件）全文搜索 `nanobot` 与 `use_skill`，**零匹配**。SKILL.md 正文中也无 `nanobot` 字样、无历史注释痕迹、无 `use_skill` 旧工具名残留。

### 5.2 实现逻辑残留（nanobot 风格残留）

| 残留项 | 位置 | 说明 |
|--------|------|------|
| `when_to_use` frontmatter 字段 | 第 4 行 | nanobot 风格的独立触发字段（原版用 `keywords`，agent_config 替换为 `when_to_use`，仍是 nanobot 风格）。Cline 用 `description` 内 "Use when ..." 句式代替 |
| `always: true` frontmatter 字段 | 第 5 行 | **Charles 扩展字段**（原版 read-pdf 无此字段，agent_config 新增）。属 Charles "always-on 自动加载"功能标记，非 nanobot 残留，但不符合 Cline 极简 frontmatter 规范 |
| `## 脚本角色说明` 章节 | 第 73-85 行 | nanobot 习惯单独列脚本角色；Cline 把脚本信息直接嵌在 Workflow Step 中。原版有 `## 可用脚本` 表格，agent_config 改为列表但仍单独成章 |
| `## 脚本调用规则` 章节 | 第 87-93 行 | nanobot 习惯单独列调用规则；Cline 用 "Always ..." 句式嵌入步骤 |
| `## 禁止行为` 章节 | 第 118-124 行 | nanobot 习惯单独设禁止章节；Cline 无此章节，行为约束嵌入 Workflow。原版有 `禁止: 安装依赖...` 独立行，agent_config 扩展为 5 条禁止项 |
| `## 场景路由` 项目符号列表 | 第 22-28 行 | nanobot 用项目符号；Cline 用 ASCII 决策树（opentui/cline-sdk 风格）。功能等价，形式不同 |

### 5.3 已正确迁移的部分

| 迁移项 | 原版 → agent_config 版 |
|--------|------------------------|
| Frontmatter 瘦身 | 移除 `keywords` / `capabilities` 两个 nanobot 字段 |
| 引入 Workflow 结构 | 原版无 `## Workflow`，新版有 `## Workflow` + `### Step 1/2/3` 三步流程 |
| 命令代码块化 | 原版命令内嵌文本，新版用 ```bash 代码块 |
| 路径前缀调整 | `skills/...` → `agent_config/skills/...`（适配新目录） |
| 移除示例对话 | 原版有"示例对话"章节（2 个示例），新版移除（向 Cline Step 风格靠拢） |
| 移除详尽表格 | 原版有 3 个表格（数据源选择、用户表述对应、可用脚本），新版精简为列表或并入 Step |
| 主脚本/内部脚本隔离 | 原版把所有脚本平等列为"可用脚本"，新版明确区分主脚本与内部脚本，禁止 agent 直接调用内部脚本 |
| 三步场景化路由 | 原版"执行流程"分"推荐方式/回退方式"，新版重构为 Step 1（查询）→ Step 2（下载）→ Step 3（再查询）的线性流程，并在"场景路由"中说明何时可跳过 Step 1 |

### 5.4 Charles 独有增强（非残留，非 Cline 对标）

| 增强项 | 位置 | 说明 |
|--------|------|------|
| `always: true` 自动加载 | 第 5 行 | Charles `get_always_skills()` 机制（见 P4.1），标记本技能为 always-on，agent 启动即加载。Cline 无此概念 |
| `## 终端监控说明` | 第 112-116 行 | 描述 Charles 前端工具卡片实时滚动显示终端输出的能力，属 Charles 平台特性 |
| `## 数据源选择` | 第 103-110 行 | 区分 RAG（本技能）与 financial-analysis CSV 的数据边界，属 Charles 业务特有 |
| `## 年报年份规则` | 第 95-101 行 | A 股年报发布年份 vs 报告期年份的语义说明，属 Charles 业务特有 |

## 6. 与 Cline 风格的一致性总评

| 维度 | 一致性 | 说明 |
|------|--------|------|
| Frontmatter 字段集 | ⚠️ 部分一致 | `name` + `description` 一致；`when_to_use`（nanobot 风格）与 `always: true`（Charles 扩展）多余 |
| 主体结构 | ⚠️ 部分一致 | 引入 `## Workflow` + `### Step 1/2/3` ✅；保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）⚠️；新增 Charles 业务特有章节（终端监控 / 数据源选择 / 年份规则）属合理扩展 |
| 脚本调用 | ✅ 一致 | ```bash 代码块、相对仓库根路径、参数必填/可选标注均符合 Cline 风格；主脚本/内部脚本隔离设计为合理增强 |
| 形式风格 | ⚠️ 部分一致 | 中文表达与 Cline 全英文样本有偏差；语气偏指令式；硬编码日期 "2026-07-27" 为维护隐患 |
| 行为约束方式 | ⚠️ 部分一致 | 单列 `## 禁止行为`，未嵌入 Workflow |
| nanobot 残留 | ✅ 无注释残留 | 全目录搜索 `nanobot` / `use_skill` 零匹配 |

**总体**：Charles `agent_config/skills/read-pdf/SKILL.md` 已完成约 60% 的 Cline 风格迁移，主要差距在：
1. frontmatter 仍保留 `when_to_use`（nanobot 风格）与 `always: true`（Charles 扩展）；
2. 主体保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）；
3. 第 101 行硬编码日期 "2026-07-27" 为维护隐患。

脚本调用部分已完全对齐 Cline 风格，且新增的"主脚本/内部脚本隔离"设计为合理的工程化增强。**与 P4.8 stock-price 相比，read-pdf 的迁移程度相近**（均约 60%），但 read-pdf 的 `always: true` 是 Charles 新增字段（原版无），而 stock-price 的 `always` 是原版残留被移除——两者方向相反，需分别理解。

## 7. 改进建议（仅供参考，不在本任务范围内执行）

1. **Frontmatter**：删除 `when_to_use`，把其内容改写为 "Use when ..." 句式合并进 `description`，例如：`description: "Query narrative content (business/orders/customers/suppliers/risk factors) from A-share annual/quarterly reports and announcements via local RAG. Use when the user asks about annual report narrative content; auto-downloads PDF from cninfo and builds index if local data is missing."`
2. **`always: true` 字段**：若保留 Charles 自动加载机制，可在 frontmatter 注释中标注其为 Charles 扩展字段（如 `# always: Charles extension, not Cline spec`），或考虑迁移到 Charles 自有的 manifest 配置中，避免污染 SKILL.md 的 Cline 兼容性。
3. **章节合并**：把 `## 脚本角色说明` 与 `## 脚本调用规则` 合并进 `## Workflow` 的对应 Step，用 "Always ..." 句式表达约束（如 Step 1 中嵌入 "Always use bare stock code without exchange suffix (e.g. 600519, not 600519.SH)"）。
4. **禁止行为嵌入**：把 `## 禁止行为` 的 5 条约束改写为 "Do not ..." 句式，嵌入 Step 1 的失败处理或参数说明中（如 "Do not assume local index exists; do not skip Step 1 unless the user explicitly asks to download"）。
5. **硬编码日期移除**：删除第 101 行 "当前日期 2026-07-27，最新完整年报为 2025 年年报。"，或改为动态提示 "最新完整年报为最近一个已披露的财年年报"。原版无此硬编码，agent_config 新增，属回归风险。
6. **场景路由决策树**（可选）：把 `## 场景路由` 改为 ASCII 决策树，与 opentui/cline-sdk 风格一致。
7. **语言**（可选）：若希望完全对齐 Cline 风格，可将主体改写为英文；但若 Charles 项目其他 SKILL.md 均为中文，保持中文一致性亦可接受。

## 8. 关键文件路径汇总

- Charles agent_config SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\read-pdf\SKILL.md`
- Charles charles-nanobot 原版 SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\read-pdf\SKILL.md`
- Charles 脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\read-pdf\scripts\`（含 `query_report.py` / `fetch_report_pdf.py` / `build_index.py` / `parse_pdf_basic.py` / `parse_pdf_ocr.py` / `fetch_financial_data.py`）
- Cline 对照样本目录：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\` 与 `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\`
- 本报告：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_4.9_read_pdf_skill.md`
