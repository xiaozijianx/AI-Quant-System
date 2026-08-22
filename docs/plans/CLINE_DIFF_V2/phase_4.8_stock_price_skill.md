# Phase 4.8 — stock-price SKILL.md 对比报告

## 1. 任务范围

- Charles 源文件：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\stock-price\SKILL.md`
- Charles 原始版本（对照）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\stock-price\SKILL.md`
- 脚本文件：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\stock-price\scripts\get_kline.py`
- Cline 对照样本：
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-ui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-desktop\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-cli\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\opentui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\cline-sdk\SKILL.md`
- `nanobot` 残留扫描：在 `agent_config\skills\stock-price\` 目录全文搜索 `nanobot`，**无任何匹配**。

## 2. Cline 是否有同类技能

**结论：Cline 无股票/金融相关 SKILL.md。**

Cline 仓库内的 SKILL.md 共 6 份，全部围绕 Cline 自身的工程化场景：`publish-ui` / `publish-desktop` / `publish-cli`（npm & 桌面发布）、`opentui`（终端 UI 框架）、`cline-sdk`（Agent SDK）、`create-pull-request`（PR 流程）。没有任何金融数据、行情、K 线、MiniQMT、xtquant 相关技能。

因此本报告转为：**评估 Charles 的 `stock-price/SKILL.md` 是否符合 Cline 的 SKILL.md 风格规范**，并标注与原 `charles-nanobot` 版本相比的迁移情况。

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

## 4. Charles `agent_config` 版 SKILL.md 逐项对比

### 4.1 Frontmatter

```yaml
---
name: stock-price
description: "通过MiniQMT获取A股实时行情和K线数据"
when_to_use: "用户询问股价/涨跌幅/K线/成交量/近期走势时"
---
```

| 字段 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 | 评估 |
|------|---------------------|------------------------------|------------|------|
| `name` | ✅ `stock-price` | ✅ `stock-price` | ✅ 必备 | 一致 |
| `description` | ✅ 简短中文一句话 | ✅ 较长中文一句话 + 触发场景 | ✅ 必备，但 Cline 习惯 "Use when ..." 句式 | 字段存在，但句式不符合 Cline "Use when ..." 风格 |
| `when_to_use` | ✅ 存在 | ❌ 不存在（原版用 `keywords`） | ❌ Cline 无此字段 | **nanobot 风格字段残留**（实现逻辑残留，非注释残留） |
| `keywords` | ❌ 已移除 | ✅ `股价, 行情, ...` | ❌ Cline 无此字段 | 已清理 |
| `always` | ❌ 已移除 | ✅ `true` | ❌ Cline 无此字段 | 已清理 |
| `capabilities` | ❌ 已移除 | ✅ 列表 | ❌ Cline 无此字段 | 已清理 |

**结论**：agent_config 版相比 charles-nanobot 原版**已大幅清理 frontmatter**（移除 `keywords` / `always` / `capabilities`），但**保留了 `when_to_use`**，这是 nanobot frontmatter 规范的残留，不符合 Cline 极简 `name + description` 规范。建议把 `when_to_use` 的内容合并到 `description` 中，采用 "Use when ..." 句式。

### 4.2 主体结构

Charles agent_config 版章节顺序：
1. `# stock-price 技能指南`
2. `## 本技能核心能力`（含前置条件）
3. `## 场景路由`
4. `## Workflow` → `### Step 1: 获取 K 线数据`
5. `## 脚本角色说明`
6. `## 脚本调用规则`
7. `## 禁止行为`

与 Cline 规范对照：

| Charles 章节 | Cline 是否常见 | 评估 |
|--------------|----------------|------|
| 本技能核心能力 | Cline 通常用标题下一句话引言代替 | 风格略不同，可接受 |
| 场景路由 | Cline 用 ASCII 决策树（opentui/cline-sdk）或编号 Step | **形式不同**：Charles 用项目符号列表，Cline 用决策树。功能等价 |
| Workflow / Step 1 | ✅ 与 Cline `## Workflow` + 编号 Step 一致 | 已对齐 Cline 风格 |
| 脚本角色说明 | Cline 不单独列脚本角色，命令直接嵌在 Step 中 | 偏 nanobot 风格（原版有 `## 可用脚本` 表格） |
| 脚本调用规则 | Cline 通过 "Always ..." 句式嵌入步骤，不单独成章 | 偏 nanobot 风格 |
| 禁止行为 | Cline **无此章节**，行为约束嵌入 Workflow | **nanobot 风格残留**（原版有 `禁止：安装依赖...`） |

**结论**：agent_config 版**已部分对齐 Cline 风格**（引入 `## Workflow` + `### Step 1` 结构），但保留 `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 三个章节，属于 nanobot 风格的主体结构残留。

### 4.3 脚本调用

| 维度 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 |
|------|---------------------|------------------------------|------------|
| 命令格式 | `python agent_config/skills/stock-price/scripts/get_kline.py <股票代码> [周期] [条数]` | `python skills/stock-price/scripts/get_kline.py <代码> [周期] [条数]` | 命令以仓库根目录为相对基准 |
| 路径前缀 | ✅ `agent_config/skills/...`（适配新目录结构） | `skills/...`（charles-nanobot 目录结构） | ✅ Charles agent_config 版路径与 Cline 风格一致（相对仓库根） |
| 代码块语言 | ```bash | 无代码块（命令内嵌文本） | ```sh / ```bash |
| 参数说明 | ✅ 参数表 + 必填/可选标注 | 表格形式 | Cline 通常用列表说明参数 |

**结论**：脚本调用部分**已对齐 Cline 风格**——使用 ```bash 代码块、路径相对仓库根、参数有必填/可选标注。相比 charles-nanobot 原版（命令内嵌文本、无代码块）有显著改进。

### 4.4 形式风格

| 维度 | Charles agent_config | Cline 规范 |
|------|---------------------|------------|
| 语言 | 中文 | 英文为主 |
| 语气 | 偏指令式（"禁止..."、"必须..."） | 偏协作式（"Always ask before..."、"Do not guess"） |
| 长度 | 约 65 行，简洁 | publish-cli 约 266 行，较详尽 |
| 失败处理 | ✅ 单列 "失败处理" 子项，列出 3 种错误场景 | ✅ Cline 也常在 Step 内列 "If ... " 失败处理 |
| 示例对话 | ❌ 已移除（原版有"茅台现在什么价"等示例） | Cline 不用示例对话，用 Step 描述 | 

**结论**：中文表达本身不违反 Cline 规范（Cline 无明文规定语言），但与 Cline 6 份样本全英文相比存在风格偏差。Charles agent_config 版**移除了原版的"示例对话"章节**，向 Cline 的 Step 描述风格靠拢，是合理的迁移。

## 5. 残留分类

### 5.1 注释残留
**无。** 目录内全文搜索 `nanobot` 零匹配；SKILL.md 正文中也无 `nanobot` 字样、无历史注释痕迹。

### 5.2 实现逻辑残留（nanobot 风格残留）

| 残留项 | 位置 | 说明 |
|--------|------|------|
| `when_to_use` frontmatter 字段 | 第 4 行 | nanobot frontmatter 规范字段，Cline 用 `description` 内 "Use when ..." 句式代替 |
| `## 脚本角色说明` 章节 | 第 49-53 行 | nanobot 习惯单独列脚本角色；Cline 把脚本信息直接嵌在 Workflow Step 中 |
| `## 脚本调用规则` 章节 | 第 55-59 行 | nanobot 习惯单独列调用规则；Cline 用 "Always ..." 句式嵌入步骤 |
| `## 禁止行为` 章节 | 第 61-65 行 | nanobot 习惯单独设禁止章节；Cline 无此章节，行为约束嵌入 Workflow |
| `## 场景路由` 项目符号列表 | 第 18-26 行 | nanobot 用项目符号；Cline 用 ASCII 决策树（opentui/cline-sdk 风格） |

### 5.3 已正确迁移的部分

| 迁移项 | 原版 → agent_config 版 |
|--------|------------------------|
| Frontmatter 瘦身 | 移除 `keywords` / `always` / `capabilities` |
| 引入 Workflow 结构 | 原版无 `## Workflow`，新版有 `## Workflow` + `### Step 1` |
| 命令代码块化 | 原版命令内嵌文本，新版用 ```bash 代码块 |
| 路径前缀调整 | `skills/...` → `agent_config/skills/...`（适配新目录） |
| 移除示例对话 | 原版有"示例对话"章节，新版移除（向 Cline Step 风格靠拢） |
| 移除"禁止：安装依赖..."独立行 | 改写为 `## 禁止行为` 章节，部分保留约束 |

## 6. 与 Cline 风格的一致性总评

| 维度 | 一致性 | 说明 |
|------|--------|------|
| Frontmatter 字段集 | ⚠️ 部分一致 | `name` + `description` 一致；`when_to_use` 多余 |
| 主体结构 | ⚠️ 部分一致 | 引入 `## Workflow` ✅；保留 3 个 nanobot 风格章节 ⚠️ |
| 脚本调用 | ✅ 一致 | 代码块、相对路径、参数标注均符合 Cline 风格 |
| 形式风格 | ⚠️ 部分一致 | 中文表达与 Cline 全英文样本有偏差；语气偏指令式 |
| 行为约束方式 | ⚠️ 部分一致 | 单列 `## 禁止行为`，未嵌入 Workflow |

**总体**：Charles `agent_config/skills/stock-price/SKILL.md` 已完成约 60% 的 Cline 风格迁移，主要差距在 frontmatter 仍保留 `when_to_use`、主体仍保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）。脚本调用部分已完全对齐 Cline 风格。

## 7. 改进建议（仅供参考，不在本任务范围内执行）

1. **Frontmatter**：删除 `when_to_use`，把其内容改写为 "Use when ..." 句式合并进 `description`，例如：`description: "Fetch A-share real-time quotes and K-line data via MiniQMT. Use when the user asks about stock price, change ratio, K-line, volume, or recent trend."`
2. **章节合并**：把 `## 脚本角色说明` 与 `## 脚本调用规则` 合并进 `## Workflow` 的 Step 1，用 "Always ..." 句式表达约束。
3. **禁止行为嵌入**：把 `## 禁止行为` 的 3 条约束改写为 "Do not ..." 句式，嵌入 Step 1 的失败处理或参数说明中。
4. **场景路由决策树**（可选）：把 `## 场景路由` 改为 ASCII 决策树，与 opentui/cline-sdk 风格一致。
5. **语言**（可选）：若希望完全对齐 Cline 风格，可将主体改写为英文；但若 Charles 项目其他 SKILL.md 均为中文，保持中文一致性亦可接受。

## 8. 关键文件路径汇总

- Charles agent_config SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\stock-price\SKILL.md`
- Charles charles-nanobot 原版 SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\stock-price\SKILL.md`
- Charles 脚本：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\stock-price\scripts\get_kline.py`
- Cline 对照样本目录：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\` 与 `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\`
- 本报告：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_4.8_stock_price_skill.md`
