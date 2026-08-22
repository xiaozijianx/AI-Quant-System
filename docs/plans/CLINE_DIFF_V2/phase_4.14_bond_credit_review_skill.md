# Phase 4.14 — bond-credit-review SKILL.md 对比报告

## 1. 任务范围

- Charles 源文件：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\bond-credit-review\SKILL.md`
- Charles 原始版本（对照）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\bond-credit-review\SKILL.md`
- Charles 原始示例文档（参考）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\bond-credit-review\references\examples.md`
- Charles 实际脚本目录：**不存在**。`agent_config\skills\bond-credit-review\` 目录下仅有 `SKILL.md` 一个文件，**无 `scripts\` 子目录**，SKILL.md 中描述的 `agent_config/skills/bond-credit-review/scripts/bond_credit_review.py` **实际不存在**。
- Cline 对照样本：
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-ui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-desktop\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-cli\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\opentui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\cline-sdk\SKILL.md`
- `nanobot` 残留扫描：在 `agent_config\skills\bond-credit-review\` 目录全文搜索 `nanobot`（大小写不敏感），**无任何匹配**；SKILL.md 正文中也无 `nanobot` 字样。

## 2. Cline 是否有同类技能

**结论：Cline 无债券信用评估 / 信用审查类 SKILL.md。**

Cline 仓库内的 SKILL.md 共 6 份，全部围绕 Cline 自身的工程化场景：`publish-ui` / `publish-desktop` / `publish-cli`（npm & 桌面 & CLI 发布）、`opentui`（终端 UI 框架）、`cline-sdk`（Agent SDK）、`create-pull-request`（PR 流程）。没有任何城投债/产业债信用评估、财务指标分析、评级机构引用、风险点识别相关技能。

因此本报告转为：**评估 Charles 的 `bond-credit-review/SKILL.md` 是否符合 Cline 的 SKILL.md 风格规范**，并标注与原 `charles-nanobot` 版本相比的迁移情况。

## 3. Cline 的 SKILL.md 风格规范（归纳自 6 份样本）

| 维度 | Cline 通用规范 |
|------|----------------|
| Frontmatter 字段 | 极简：`name` + `description`；大型技能额外加 `metadata.references`（见 opentui/cline-sdk）。**未见** `when_to_use` / `keywords` / `always` / `capabilities` 等 nanobot 风格字段 |
| description 风格 | 一段英文长句，说明 "Use when ..." 触发场景，避免逗号分隔的关键词列表 |
| 主体语言 | 英文为主；少量中文注释仅出现在引用项目内文件时 |
| 主体结构 | 标题 → 一句话引言 → `## Critical Rules`（可选）→ `## How to Use` / `## Workflow` / `## Release contract` / `## Prerequisites Check` → 编号 Step → `## Final report` / `## Resources` |
| 命令调用 | 使用 ```sh / ```bash 代码块；命令以仓库根目录为相对基准（如 `apps/cli/package.json`）|
| 行为约束 | 通过 "Always ask before ..." / "Do not guess" / "IMPORTANT: ..." 等句子嵌入 Workflow 步骤，**不单独设"禁止行为"章节** |
| 决策树 | opentui/cline-sdk 使用 ASCII 决策树做场景路由；publish-* 系列使用编号 Workflow |
| 文件引用 | 大量使用相对路径指向仓库内文件，路径精确到具体文件名 |
| 模板/产出物 | create-pull-request 明确要求"strictly match the template structure"，强调模板严格匹配 |

## 4. Charles `agent_config` 版 SKILL.md 逐项对比

### 4.1 Frontmatter

Charles agent_config 版：
```yaml
---
name: bond-credit-review
description: "城投/产业债信用基本面审查，输出信用评分、风险点清单和投资建议"
when_to_use: "用户要求分析城投债/产业债信用资质/信用评分/风险点/投资建议时"
---
```

Charles charles-nanobot 原版：
```yaml
---
name: bond-credit-review
description: "帮投资经理评估某只债券的信用风险，判断是否值得投资。当客户主动问某只债券能不能买、新债发行需要快速出信用评估、存量债券的发行人信用评级发生变动时使用。"
---
```

| 字段 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 | 评估 |
|------|---------------------|------------------------------|------------|------|
| `name` | `bond-credit-review` | `bond-credit-review` | 必备 | 一致 |
| `description` | 精简中文一句话 + 能力声明 | 较长中文一句话 + 触发场景（"当...时使用"） | 必备，但 Cline 习惯 "Use when ..." 句式 | 字段存在；agent_config 版比原版更精简，但**移除了原版 description 中的触发场景**（迁移到 `when_to_use`），句式不符合 Cline "Use when ..." 风格 |
| `when_to_use` | **存在** | 不存在 | Cline 无此字段 | **nanobot 风格字段残留**（实现逻辑残留，非注释残留）。原版无此字段，agent_config 版**主动引入** |
| `keywords` | 已移除（原版亦无） | 不存在 | Cline 无此字段 | 一致 |
| `capabilities` | 已移除（原版亦无） | 不存在 | Cline 无此字段 | 一致 |

**结论**：agent_config 版相比 charles-nanobot 原版**主动引入了 `when_to_use` 字段**——原版 description 已包含 "当...时使用" 触发场景，agent_config 版将触发场景从 description 拆分到 `when_to_use` 字段中。这是迁移过程中**主动引入**的 nanobot 风格字段，不符合 Cline 极简 `name + description` 规范。

### 4.2 主体结构

Charles agent_config 版章节顺序：
1. `# bond-credit-review 技能指南`
2. `## 本技能核心能力`（含工作方式 + 适用范围）
3. `## 场景路由`
4. `## Workflow` → `### Step 1: 收集发行人数据` / `### Step 2: 调用信用审查脚本` / `### Step 3: 输出信用审查报告`
5. `## 脚本角色说明`
6. `## 脚本调用规则`
7. `## 禁止行为`

Charles charles-nanobot 原版章节顺序：
1. `# 债券信用评估`（标题与技能 name 不一致）
2. `## 操作流程`（编号列表 6 步，含"XX 城投"、"AA 评级"、"资产负债率(62%)"等具体示例数据）
3. `## 关键规则` → `### 必须遵守` / `### 禁止事项`
4. `## 参考文档`（含 `references/examples.md` 引用 + 中诚信/联合资信评级机构 + 财政部/各省财政厅官网）

与 Cline 规范对照：

| Charles 章节 | Cline 是否常见 | 评估 |
|--------------|----------------|------|
| 本技能核心能力 | Cline 通常用标题下一句话引言代替（如 publish-cli L8） | 风格略不同，可接受 |
| 场景路由 | Cline 用 ASCII 决策树（opentui/cline-sdk）或编号 Step | **形式不同**：Charles 用项目符号列表 + 流程箭头，Cline 用决策树。功能等价 |
| Workflow / Step 1-3 | 与 Cline `## Workflow` + 编号 Step 一致 | 已对齐 Cline 风格 |
| 脚本角色说明 | Cline 不单独列脚本角色，命令直接嵌在 Step 中（create-pull-request 把 `gh` 命令直接嵌在 Step 内） | 偏 nanobot 风格（原版无此章节，但 nanobot 习惯单独列） |
| 脚本调用规则 | Cline 通过 "Always ..." 句式嵌入步骤，不单独成章 | 偏 nanobot 风格 |
| 禁止行为 | Cline **无此章节**，行为约束嵌入 Workflow（create-pull-request 用 "IMPORTANT: ..." / "Always ask before ..." 嵌入 Step） | **nanobot 风格残留**（原版有 `### 禁止事项`，风格上属 nanobot 习惯） |

**与原版结构差异**：
- 原版章节：`# 债券信用评估` → `## 操作流程` → `## 关键规则`（含必须遵守 / 禁止事项）→ `## 参考文档`
- agent_config 版**完全重写**：移除 `## 操作流程` / `## 关键规则` / `## 参考文档`，新增 `## 本技能核心能力` / `## 场景路由` / `## Workflow` / `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 共 6 个章节
- agent_config 版**移除了"参考文档"章节**（原版有 `references/examples.md` 引用 + 评级机构 + 财政数据来源）
- agent_config 版**移除了"示例数据"**（原版"操作流程"含"XX 城投"、"AA 评级"、"资产负债率(62%)"等具体指标示例）
- agent_config 版**新增了 `## Workflow` + `### Step 1-3` 结构**（向 Cline 风格靠拢）
- agent_config 版**新增了"脚本调用"概念**（原版无任何脚本调用，纯描述性"操作流程"）
- agent_config 版**标题改为技能 name**：原版 `# 债券信用评估` → agent_config 版 `# bond-credit-review 技能指南`（与 frontmatter name 一致，符合 Cline 习惯）

**结论**：agent_config 版**已部分对齐 Cline 风格**（引入 `## Workflow` + `### Step 1-3` 结构、标题对齐技能 name、移除示例数据），但保留 `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 三个章节，属于 nanobot 风格的主体结构残留。同时**完全移除了"参考文档"章节**，丢失了原版的输出格式范例引用和数据来源说明。

### 4.3 脚本调用

**重要发现**：SKILL.md 描述的脚本 `agent_config/skills/bond-credit-review/scripts/bond_credit_review.py` **实际不存在**！`agent_config\skills\bond-credit-review\` 目录下仅有 `SKILL.md` 一个文件，**无 `scripts\` 子目录**。

| 维度 | Charles agent_config | Charles charles-nanobot 原版 | Cline 规范 |
|------|---------------------|------------------------------|------------|
| 命令格式 | `python agent_config/skills/bond-credit-review/scripts/bond_credit_review.py --bond <债券代码或名称> --type <城投/产业>` | **无命令**（操作流程为 6 步描述性步骤） | 命令以仓库根目录为相对基准 |
| 路径前缀 | `agent_config/skills/...`（适配新目录结构） | — | Charles agent_config 版路径形式与 Cline 风格一致 |
| 代码块语言 | ```bash | 无代码块 | ```sh / ```bash |
| 参数说明 | 参数表 + 必填标注 + 调用规则列表 | 无参数 | Cline 通常用列表说明参数 |
| 参数命名 | `--bond`（必填）+ `--type`（必填，`城投`/`产业`） | — | — |
| 脚本实际存在 | **❌ 不存在** | — | Cline 强调"strictly match"，脚本不存在严重违反 Cline 风格 |

**关键差异**：

1. **原版无脚本调用**：charles-nanobot 原版完全无脚本调用，"操作流程"为 6 步描述性步骤（查询评级 → 下载年报 → 查询财政数据 → 横向对比 → 综合判断 → 输出结论）。这是纯 LLM 执行的流程，agent 直接在对话中按步骤操作。

2. **agent_config 版主动引入脚本调用，但脚本未实现**：agent_config 版新增 `bond_credit_review.py` 脚本调用，但**该脚本实际不存在**——`agent_config/skills/bond-credit-review/scripts/` 目录不存在。这是**比 write-report 参数不一致更严重的阻塞性问题**。

3. **参数设计**：`--bond`（债券代码或名称）+ `--type`（`城投` 或 `产业`）。参数设计合理，限定城投/产业两类，与 description 中"城投/产业债信用基本面审查"一致。

**影响**：若 agent 严格按 SKILL.md Step 2 调用 `python agent_config/skills/bond-credit-review/scripts/bond_credit_review.py --bond 600519 --type 城投`，会因脚本文件不存在而直接报错（FileNotFoundError 或 Python 找不到模块）。这是**阻塞性问题**，使技能无法实际执行。

**性质判定**：此为**实现逻辑残留**——agent_config 版 SKILL.md 描述了脚本调用形式（向 Cline 的"命令式 Step"风格靠拢），但脚本未实现。可能是迁移过程中**计划但未实现**的功能，或是**描述了应当存在但尚未创建的脚本**。原版本身是纯描述性流程，agent_config 版主动引入脚本调用属于"过度设计 + 未完成实现"。

### 4.4 形式风格

| 维度 | Charles agent_config | Cline 规范 |
|------|---------------------|------------|
| 语言 | 中文 | 英文为主 |
| 语气 | 偏指令式（"禁止..."、"必须..."） | 偏协作式（"Always ask before..."、"Do not guess"） |
| 长度 | 约 74 行，简洁 | publish-cli 约 266 行，create-pull-request 约 211 行，较详尽 |
| 示例数据 | 已移除（原版"操作流程"含"XX 城投"、"AA 评级"、"资产负债率(62%)"等具体指标） | Cline 不用示例数据，用抽象 Step 描述 |
| 参考文档引用 | 已移除（原版有 `references/examples.md` + 评级机构 + 财政数据来源） | Cline 有 `## Resources` 引用相关文档（如 create-pull-request 引用 `.github/pull_request_template.md`） |
| 输出格式范例 | 已移除（原版 examples.md 含完整输出格式：主体概况/财务分析/区域分析/横向对比/主要风险/建议） | Cline 强调"strictly match the template structure"，需要明确输出模板 |

**结论**：agent_config 版**移除了原版的示例数据**（如"XX 城投"、"AA 评级"、"资产负债率(62%)"等），向 Cline 的抽象 Step 描述风格靠拢，是合理的迁移。但同时也**移除了"参考文档"章节**——原版引用 `references/examples.md` 提供输出格式范例，agent_config 版无此类引用，agent 无法参考具体输出格式。Cline 通常用 `## Resources` 章节或 Step 内 "strictly match the template" 引用相关文档，agent_config 版在这一点上**未对齐 Cline 风格**。

## 5. 残留分类

### 5.1 注释残留

**无。** `agent_config\skills\bond-credit-review\` 目录全文搜索 `nanobot` 零匹配；SKILL.md 正文中也无 `nanobot` 字样、无历史注释痕迹、无"对标 nanobot"等 docstring 残留。

### 5.2 实现逻辑残留（nanobot 风格残留）

| 残留项 | 位置 | 说明 | 性质 |
|--------|------|------|------|
| `when_to_use` frontmatter 字段 | 第 4 行 | nanobot frontmatter 规范字段，Cline 用 `description` 内 "Use when ..." 句式代替。**注意**：原版 charles-nanobot 无此字段，agent_config 版**主动引入** | 实现逻辑残留 |
| `## 脚本角色说明` 章节 | 第 59-63 行 | nanobot 习惯单独列脚本角色；Cline 把脚本信息直接嵌在 Workflow Step 中（如 create-pull-request 把 `gh` 命令嵌在 Step 内） | 实现逻辑残留 |
| `## 脚本调用规则` 章节 | 第 65-68 行 | nanobot 习惯单独列调用规则；Cline 用 "Always ..." 句式嵌入步骤 | 实现逻辑残留 |
| `## 禁止行为` 章节 | 第 70-74 行 | nanobot 习惯单独设禁止章节（原版有 `### 禁止事项`）；Cline 无此章节，行为约束嵌入 Workflow（用 "IMPORTANT: ..." / "Do not ..." 句式） | 实现逻辑残留 |
| `## 场景路由` 项目符号列表 | 第 20-26 行 | nanobot 用项目符号列表；Cline 用 ASCII 决策树（opentui/cline-sdk 风格）或编号 Step | 形式风格残留（轻度） |

### 5.3 已正确迁移的部分

| 迁移项 | 原版 → agent_config 版 |
|--------|------------------------|
| 引入 Workflow 结构 | 原版无 `## Workflow`，新版有 `## Workflow` + `### Step 1-3`（对齐 Cline） |
| 命令代码块化 | 原版无命令，新版用 ```bash 代码块（虽然脚本不存在） |
| 路径前缀 | `agent_config/skills/...`（适配新目录结构） |
| 移除示例数据 | 原版"操作流程"含"XX 城投"、"AA 评级"等示例数据，新版移除（向 Cline 抽象 Step 风格靠拢） |
| 标题改为技能 name | 原版 `# 债券信用评估` → 新版 `# bond-credit-review 技能指南`（与 frontmatter name 一致，符合 Cline 习惯） |
| description 精简 | 原版较长（含触发场景），新版精简为"城投/产业债信用基本面审查，输出信用评分、风险点清单和投资建议"（虽然触发场景被拆到 `when_to_use`） |
| Frontmatter 字段保持精简 | 原版仅 `name` + `description`，agent_config 版仅新增 `when_to_use`，未引入 `keywords`/`capabilities` 等 dead metadata |

### 5.4 功能缺失（非 nanobot 残留，需关注）

| 缺失项 | 原版 → agent_config 版 | 影响 |
|--------|------------------------|------|
| 脚本实现 | agent_config 版描述 `bond_credit_review.py`，但脚本未实现，`scripts/` 目录不存在 | **阻塞性**：技能无法实际执行 |
| 参考文档章节 | 原版 `## 参考文档` 引用 `references/examples.md` + 评级机构 + 财政数据来源，agent_config 版无 | agent 无法参考输出格式与数据来源 |
| 输出格式范例 | 原版 examples.md 含完整输出格式（主体概况/财务分析/区域分析/横向对比/主要风险/建议），agent_config 版无 | agent 输出格式不可控，与原版规范不一致 |
| 具体数据维度 | 原版"操作流程"列出资产负债率(62%)/经营性现金流(+3.2亿)/有息负债规模(85亿)/一般公共预算收入/政府性基金收入/地方债务率等具体指标，agent_config 版仅抽象说"财务数据 + 区域经济数据" | agent 可能遗漏关键指标 |
| 评级机构引用 | 原版"参考文档"列出中诚信/联合资信等评级机构，agent_config 版无 | agent 可能不知道应查询哪些评级机构 |
| 横向对比能力 | 原版 Step 4 "与同评级(AA)、同地区的其他城投平台比较资产负债率和现金流指标"，agent_config 版无此步骤 | 丢失原版的横向对比维度 |
| 评级交叉验证 | 原版"必须交叉验证至少两个评级机构的评级结果"，agent_config 版无此约束 | 评级信息可能单一来源 |

## 6. 与 Cline 风格的一致性总评

| 维度 | 一致性 | 说明 |
|------|--------|------|
| Frontmatter 字段集 | ⚠️ 部分一致 | `name` + `description` 一致；`when_to_use` 多余（且为迁移中间态新增，非原版遗留） |
| 主体结构 | ⚠️ 部分一致 | 引入 `## Workflow` + `### Step 1-3` ✅；保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）⚠️ |
| 脚本调用 | ❌ 形式一致但脚本不存在 | 代码块、相对路径、参数标注均符合 Cline 风格 ✅；但 SKILL.md 描述的脚本路径 `agent_config/skills/bond-credit-review/scripts/bond_credit_review.py` **实际不存在** ❌ |
| 形式风格 | ⚠️ 部分一致 | 中文表达与 Cline 全英文样本有偏差；语气偏指令式（"禁止..."）vs Cline 协作式（"Do not..."） |
| 行为约束方式 | ⚠️ 部分一致 | 单列 `## 禁止行为`，未嵌入 Workflow；Cline 用 "IMPORTANT: ..." / "Do not ..." 嵌入 Step |
| 模板/产出物约束 | ❌ 缺失 | 无输出格式范例（原版 examples.md 已删除，未在 SKILL.md 中补充）；Cline 强调"strictly match the template" |
| 参考文档引用 | ❌ 缺失 | 无 `## Resources` 章节；原版的 `## 参考文档`（评级机构 + 财政数据来源）已删除 |
| 功能完整性 | ❌ 严重偏差 | 脚本未实现；丢失原版的输出格式范例、具体数据维度、评级机构引用、横向对比能力、评级交叉验证约束 |

**总体**：Charles `agent_config/skills/bond-credit-review/SKILL.md` 已完成约 45% 的 Cline 风格迁移，主要差距在：

1. frontmatter 仍保留 `when_to_use`（且为迁移中间态新增）；
2. 主体仍保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）；
3. **SKILL.md 描述的脚本实际不存在**（最重要的问题，影响实际可用性）；
4. **丢失了原版的关键能力**：输出格式范例、具体数据维度、评级机构引用、横向对比能力、评级交叉验证约束；
5. 缺少 Cline 风格的模板约束与参考文档引用。

## 7. 改进建议（仅供参考，不在本任务范围内执行）

1. **修复脚本不存在问题（P0，阻塞性）**：
   - 方案 A（实现脚本）：创建 `agent_config/skills/bond-credit-review/scripts/bond_credit_review.py`，接受 `--bond` + `--type` 参数，返回信用评分 + 风险点 + 投资建议。需要实现评级查询、财务指标提取、横向对比等逻辑。
   - 方案 B（移除脚本调用，回归原版风格）：将 SKILL.md 改为描述性 Workflow（类似原版的"操作流程"），移除 Step 2 的脚本调用与 `## 脚本角色说明` / `## 脚本调用规则` 章节，让 agent 直接在对话中按 Step 执行信用审查。
   - **推荐方案 B**，因为原版就是描述性流程，agent_config 版主动引入脚本调用但未实现，属于"过度设计 + 未完成实现"。回归描述性流程既对齐原版语义，又避免脚本缺失的阻塞。

2. **Frontmatter**：删除 `when_to_use`，把其内容改写为 "Use when ..." 句式合并进 `description`，例如：`description: "Review credit fundamentals of urban investment / industrial bonds and output credit score, risk points, and investment recommendations. Use when the user asks to analyze credit quality, credit score, risk points, or investment advice for urban investment or industrial bonds."`

3. **章节合并**：若采用方案 B，则 `## 脚本角色说明` 与 `## 脚本调用规则` 自然消失；若采用方案 A，则把这两个章节合并进 `## Workflow` 的 Step 2，用 "Always ..." 句式表达约束（如 "Always specify `--type` as `城投` or `产业`"）。

4. **禁止行为嵌入**：把 `## 禁止行为` 的 3 条约束改写为 "Do not ..." 句式，嵌入对应 Step 中（如 Step 1 嵌入"Do not skip data collection"，Step 2 嵌入"Do not assume data exists"）。

5. **恢复输出格式范例**（P1）：参考原版 `references/examples.md`，在 SKILL.md Step 3 或新增 `## 输出格式` 章节中列出信用评估结论的输出格式（主体概况/财务分析/区域分析/横向对比/主要风险/建议），与 Cline create-pull-request "strictly match the template" 风格一致。

6. **恢复具体数据维度**（P1）：参考原版"操作流程"，在 Step 1 中列出具体需要收集的指标（资产负债率/经营性现金流/有息负债规模/一般公共预算收入/政府性基金收入/地方债务率），避免 agent 遗漏关键指标。

7. **恢复横向对比与评级交叉验证**（P1）：在 Step 2 中增加"与同评级、同地区的其他城投平台比较"步骤；在 `## 禁止行为` 或 Step 1 中增加"必须交叉验证至少两个评级机构的评级结果"约束。

8. **恢复参考文档章节**（P2）：参考原版 `## 参考文档`，新增 `## Resources` 章节列出评级机构（中诚信/联合资信）、发行人年报来源、地方财政数据来源（财政部/各省财政厅官网），与 Cline `## Resources` 风格一致。

9. **场景路由决策树**（可选）：把 `## 场景路由` 改为 ASCII 决策树，与 opentui/cline-sdk 风格一致。

10. **语言**（可选）：若希望完全对齐 Cline 风格，可将主体改写为英文；但若 Charles 项目其他 SKILL.md 均为中文，保持中文一致性亦可接受。

## 8. 关键文件路径汇总

- Charles agent_config SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\bond-credit-review\SKILL.md`
- Charles charles-nanobot 原版 SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\bond-credit-review\SKILL.md`
- Charles charles-nanobot 原版示例文档：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\bond-credit-review\references\examples.md`
- Charles 脚本目录：**不存在**（`agent_config\skills\bond-credit-review\scripts\` 目录未创建，`bond_credit_review.py` 未实现）
- Cline 对照样本目录：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\` 与 `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\`
- Cline 最贴近对照（create-pull-request，"产出文档型"技能）：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
- 本报告：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_4.14_bond_credit_review_skill.md`
