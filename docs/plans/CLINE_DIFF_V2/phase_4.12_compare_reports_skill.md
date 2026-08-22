# Phase 4.12 — compare-reports SKILL.md 对比报告

## 1. 任务范围

- Charles 源文件：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\compare-reports\SKILL.md`
- Charles 原始版本（对照）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\compare-reports\SKILL.md`
- Charles 实际脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\compare-reports\scripts\`
  - `cross_company.py`（跨公司对比）
  - `cross_period.py`（跨期对比，**SKILL.md 未提及**）
- Cline 对照样本：
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-ui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-desktop\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-cli\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\opentui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\cline-sdk\SKILL.md`
- `nanobot` 残留扫描：在 `agent_config\skills\compare-reports\` 目录全文搜索 `nanobot`，**无任何匹配**。

## 2. Cline 是否有同类技能

**结论：Cline 无财报对比 / 跨公司分析相关 SKILL.md。**

Cline 仓库内的 SKILL.md 共 6 份，全部围绕 Cline 自身的工程化场景：`publish-ui` / `publish-desktop` / `publish-cli`（npm & 桌面 & CLI 发布）、`opentui`（终端 UI 框架）、`cline-sdk`（Agent SDK）、`create-pull-request`（PR 流程）。没有任何年报对比、跨期分析、跨公司研报对比、RAG 检索相关技能。

因此本报告转为：**评估 Charles 的 `compare-reports/SKILL.md` 是否符合 Cline 的 SKILL.md 风格规范**，并标注与原 `charles-nanobot` 版本相比的迁移情况。

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

```yaml
---
name: compare-reports
description: "对比两家/多家公司年报中的叙述性内容差异(业务/战略/风险/客户/供应商等维度)"
when_to_use: "用户要求对比多家公司年报中的业务描述/战略方向/风险因素/客户供应商等叙述性内容时"
---
```

| 字段 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 | 评估 |
|------|---------------------|------------------------------|------------|------|
| `name` | `compare-reports` | `compare-reports` | 必备 | 一致 |
| `description` | 简短中文一句话 + 维度列表 | 较长中文一句话 + 触发场景 | 必备，但 Cline 习惯 "Use when ..." 句式 | 字段存在，句式不符合 Cline "Use when ..." 风格 |
| `when_to_use` | **存在** | 不存在（原版用 `keywords`） | Cline 无此字段 | **nanobot 风格字段残留**（实现逻辑残留，非注释残留） |
| `keywords` | 已移除 | `对比, 比较, 变化, 环比, 同比, ...` | Cline 无此字段 | 已清理 |
| `capabilities` | 已移除 | 列表（对比同一公司跨期 / 对比不同公司研报） | Cline 无此字段 | 已清理 |

**结论**：agent_config 版相比 charles-nanobot 原版**已大幅清理 frontmatter**（移除 `keywords` / `capabilities`），但**新增了 `when_to_use`**——这是 nanobot frontmatter 规范的字段，不符合 Cline 极简 `name + description` 规范。注意原版没有 `when_to_use`，所以这是迁移过程中**主动引入**的 nanobot 风格字段，而非原版残留。

### 4.2 主体结构

Charles agent_config 版章节顺序：
1. `# compare-reports 技能指南`
2. `## 本技能核心能力`（含工作方式 + 适用内容）
3. `## 场景路由`
4. `## Workflow` → `### Step 1: 检查索引` → `### Step 2: 调用对比脚本`
5. `## 脚本角色说明`
6. `## 脚本调用规则`
7. `## 数据前提`
8. `## 禁止行为`

与 Cline 规范对照：

| Charles 章节 | Cline 是否常见 | 评估 |
|--------------|----------------|------|
| 本技能核心能力 | Cline 通常用标题下一句话引言代替 | 风格略不同，可接受 |
| 场景路由 | Cline 用 ASCII 决策树（opentui/cline-sdk）或编号 Step | **形式不同**：Charles 用项目符号列表 + 流程箭头，Cline 用决策树。功能等价 |
| Workflow / Step 1 / Step 2 | 与 Cline `## Workflow` + 编号 Step 一致 | 已对齐 Cline 风格 |
| 脚本角色说明 | Cline 不单独列脚本角色，命令直接嵌在 Step 中 | 偏 nanobot 风格（原版有 `## 可用脚本` 表格） |
| 脚本调用规则 | Cline 通过 "Always ..." 句式嵌入步骤，不单独成章 | 偏 nanobot 风格 |
| 数据前提 | Cline 前置条件嵌在 `## Prerequisites Check` / `## Release contract` 中 | 形式略不同，可接受 |
| 禁止行为 | Cline **无此章节**，行为约束嵌入 Workflow | **nanobot 风格残留**（原版无此章节，但风格上属 nanobot 习惯） |

**与原版结构差异**：
- 原版章节：`适用场景` → `前提条件` → `可用脚本（表格）` → `工作流程` → `示例对话`
- agent_config 版**移除了"示例对话"章节**（向 Cline Step 风格靠拢）
- agent_config 版**移除了"可用脚本"表格**，改为 `## 脚本角色说明` 项目符号列表
- agent_config 版**新增了 `## Workflow` + `### Step 1/Step 2` 结构**（向 Cline 风格靠拢）
- agent_config 版**新增了 `## 场景路由` / `## 脚本调用规则` / `## 数据前提` / `## 禁止行为`** 章节

**结论**：agent_config 版**已部分对齐 Cline 风格**（引入 `## Workflow` + `### Step` 结构、移除示例对话），但保留 `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 三个章节，属于 nanobot 风格的主体结构残留。

### 4.3 脚本调用

| 维度 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 |
|------|---------------------|------------------------------|------------|
| 命令格式 | `python agent_config/skills/compare-reports/scripts/cross_company.py --stocks <代码1,代码2,...> --query "<对比维度>"` | `python skills/compare-reports/scripts/cross_company.py --stocks 688981,600519 --topic "经营状况和盈利能力"` | 命令以仓库根目录为相对基准 |
| 路径前缀 | `agent_config/skills/...`（适配新目录结构） | `skills/...`（charles-nanobot 目录结构） | Charles agent_config 版路径与 Cline 风格一致（相对仓库根） |
| 代码块语言 | ```bash | 无代码块（命令内嵌文本） | ```sh / ```bash |
| 参数说明 | 参数表 + 必填标注 + 调用规则列表 | 表格形式 | Cline 通常用列表说明参数 |
| 参数命名 | `--query`（对比维度） | `--topic`（对比主题） | — |
| 股票代码格式 | 不带交易所后缀（如 `600519,000858`） | 不带后缀 | — |

**关键差异**：

1. **参数命名变更**：原版用 `--topic`，agent_config 版改为 `--query`。这是与原版的不兼容变更，需要确认 `cross_company.py` 实际支持的参数名。
2. **脚本数量缩减**：原版支持 `cross_period.py`（跨期对比）和 `cross_company.py`（跨公司对比）**两个脚本**；agent_config 版**只提到 `cross_company.py` 一个脚本**，但实际目录里 `cross_period.py` 仍然存在。这意味着 agent_config 版**丢失了"跨期对比"能力**——原版可对比同一公司不同时期的财报变化（如 2024 vs 2025），agent_config 版只支持跨公司对比。
3. **适用范围缩减**：原版 description 明确涵盖"对比同一公司不同时期的财报变化"和"横向对比不同公司的研报观点"两类场景；agent_config 版 description 只提"对比两家/多家公司年报"，**移除了跨期对比能力**。

**结论**：脚本调用形式上**已对齐 Cline 风格**（使用 ```bash 代码块、路径相对仓库根、参数有必填标注），但存在**功能缺失**：未提及 `cross_period.py` 脚本，丢失了原版的跨期对比能力。这不是 nanobot 残留问题，而是迁移过程中**功能范围缩减**。

### 4.4 形式风格

| 维度 | Charles agent_config | Cline 规范 |
|------|---------------------|------------|
| 语言 | 中文 | 英文为主 |
| 语气 | 偏指令式（"禁止..."、"必须..."） | 偏协作式（"Always ask before..."、"Do not guess"） |
| 长度 | 约 78 行，简洁 | publish-cli 约 266 行，较详尽 |
| 失败处理 | 单列 "失败处理" 子项，列出 2 种错误场景 | Cline 也常在 Step 内列 "If ... " 失败处理 |
| 示例对话 | 已移除（原版有"中芯国际 vs 贵州茅台"等示例） | Cline 不用示例对话，用 Step 描述 |
| 路径说明 | 原版末尾有"所有路径参数使用相对路径（不带前导 /）" | Cline 在 Step 内说明 "run every command below from the repository root" |

**结论**：中文表达本身不违反 Cline 规范（Cline 无明文规定语言），但与 Cline 6 份样本全英文相比存在风格偏差。Charles agent_config 版**移除了原版的"示例对话"章节**，向 Cline 的 Step 描述风格靠拢，是合理的迁移。但原版的"路径说明"提示也被移除，未在 agent_config 版中体现"从仓库根目录运行"的提示。

## 5. 残留分类

### 5.1 注释残留

**无。** `agent_config\skills\compare-reports\` 目录全文搜索 `nanobot` 零匹配；SKILL.md 正文中也无 `nanobot` 字样、无历史注释痕迹。

### 5.2 实现逻辑残留（nanobot 风格残留）

| 残留项 | 位置 | 说明 |
|--------|------|------|
| `when_to_use` frontmatter 字段 | 第 4 行 | nanobot frontmatter 规范字段，Cline 用 `description` 内 "Use when ..." 句式代替。**注意**：原版 charles-nanobot 未使用此字段，agent_config 版迁移时**主动引入**，属 nanobot 风格残留 |
| `## 脚本角色说明` 章节 | 第 56-60 行 | nanobot 习惯单独列脚本角色；Cline 把脚本信息直接嵌在 Workflow Step 中 |
| `## 脚本调用规则` 章节 | 第 62-66 行 | nanobot 习惯单独列调用规则；Cline 用 "Always ..." 句式嵌入步骤 |
| `## 禁止行为` 章节 | 第 74-78 行 | nanobot 习惯单独设禁止章节；Cline 无此章节，行为约束嵌入 Workflow |

### 5.3 已正确迁移的部分

| 迁移项 | 原版 → agent_config 版 |
|--------|------------------------|
| Frontmatter 瘦身 | 移除 `keywords` / `capabilities` |
| 引入 Workflow 结构 | 原版无 `## Workflow`，新版有 `## Workflow` + `### Step 1` / `### Step 2` |
| 命令代码块化 | 原版命令内嵌文本，新版用 ```bash 代码块 |
| 路径前缀调整 | `skills/...` → `agent_config/skills/...`（适配新目录） |
| 移除示例对话 | 原版有"示例对话"章节，新版移除（向 Cline Step 风格靠拢） |
| 移除"可用脚本"表格 | 原版用表格列脚本，新版改为项目符号列表（向 Cline 风格靠拢） |

### 5.4 功能缺失（非 nanobot 残留，需关注）

| 缺失项 | 原版 → agent_config 版 |
|--------|------------------------|
| 跨期对比能力 | 原版支持 `cross_period.py` 跨期对比（如 2024 vs 2025），agent_config 版未提及此脚本 |
| 适用场景缩减 | 原版 description 涵盖"跨期 + 跨公司"两类，agent_config 版只保留"跨公司" |
| `cross_period.py` 脚本 | 实际目录仍存在，但 SKILL.md 未文档化，agent 无法发现和调用 |

## 6. 与 Cline 风格的一致性总评

| 维度 | 一致性 | 说明 |
|------|--------|------|
| Frontmatter 字段集 | 部分一致 | `name` + `description` 一致；`when_to_use` 多余 |
| 主体结构 | 部分一致 | 引入 `## Workflow` + `### Step` 一致；保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为） |
| 脚本调用 | 一致 | 代码块、相对路径、参数标注均符合 Cline 风格 |
| 形式风格 | 部分一致 | 中文表达与 Cline 全英文样本有偏差；语气偏指令式 |
| 行为约束方式 | 部分一致 | 单列 `## 禁止行为`，未嵌入 Workflow |
| 功能完整性 | 偏差 | 仅文档化 1 个脚本，原版支持 2 个脚本（cross_period 未文档化） |

**总体**：Charles `agent_config/skills/compare-reports/SKILL.md` 已完成约 60% 的 Cline 风格迁移，主要差距在 frontmatter 仍保留 `when_to_use`、主体仍保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）。脚本调用部分已完全对齐 Cline 风格。**额外问题**：相比原版丢失了 `cross_period.py` 跨期对比能力的文档化，建议补充。

## 7. 改进建议（仅供参考，不在本任务范围内执行）

1. **Frontmatter**：删除 `when_to_use`，把其内容改写为 "Use when ..." 句式合并进 `description`，例如：`description: "Compare narrative content differences across multiple companies' annual reports (business/strategy/risk/customers/suppliers). Use when the user asks to compare business descriptions, strategic direction, risk factors, or customer/supplier information across companies."`

2. **章节合并**：把 `## 脚本角色说明` 与 `## 脚本调用规则` 合并进 `## Workflow` 的 Step 2，用 "Always ..." 句式表达约束（如 "Always use stock codes without exchange suffix"）。

3. **禁止行为嵌入**：把 `## 禁止行为` 的 3 条约束改写为 "Do not ..." 句式，嵌入 Step 1 / Step 2 的失败处理中。

4. **补充跨期对比能力**：`agent_config/skills/compare-reports/scripts/cross_period.py` 仍然存在，建议在 SKILL.md 中补充 `cross_period.py` 的文档化，恢复原版的跨期对比能力。可在 `## 场景路由` 增加"同一公司跨期对比"分支，在 `## Workflow` 增加 Step 3 或在 Step 2 中并列两个脚本调用。

5. **参数命名确认**：核对 `cross_company.py` 实际支持的参数名（`--query` 还是 `--topic`），确保 SKILL.md 文档与脚本实现一致。

6. **场景路由决策树**（可选）：把 `## 场景路由` 改为 ASCII 决策树，与 opentui/cline-sdk 风格一致。

7. **语言**（可选）：若希望完全对齐 Cline 风格，可将主体改写为英文；但若 Charles 项目其他 SKILL.md 均为中文，保持中文一致性亦可接受。

## 8. 关键文件路径汇总

- Charles agent_config SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\compare-reports\SKILL.md`
- Charles charles-nanobot 原版 SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\compare-reports\SKILL.md`
- Charles 脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\compare-reports\scripts\`
  - `cross_company.py`（跨公司对比，SKILL.md 已文档化）
  - `cross_period.py`（跨期对比，SKILL.md **未文档化**）
- Cline 对照样本目录：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\` 与 `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\`
- 本报告：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_4.12_compare_reports_skill.md`
