# Phase 4.15 — web-search SKILL.md 对比报告

## 1. 任务范围

- Charles 源文件：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\web-search\SKILL.md`（75 行）
- Charles 脚本目录：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\web-search\scripts\`（含 `search_market.py`，基于通义千问 DashScope `enable_search` 能力）
- Charles 原始版本（对照）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\skills\web-search\SKILL.md` — **不存在**。`third_party\charles_bundle\charles-nanobot\` 目录下仅有 `AGENTS.md` / `TOOLS.md` / `agent.py` / `config.json` 四个文件，无 `skills\` 子目录。因此本报告无法进行"原版 vs agent_config 版"的迁移前后对比，仅进行"agent_config 版 vs Cline 风格规范"的对标。
- Cline 对照样本：
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-ui\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-cli\SKILL.md`（266 行，最详尽样本）
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\publish-desktop\SKILL.md`
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\opentui\SKILL.md`（含 ASCII 决策树）
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\cline-sdk\SKILL.md`（含 ASCII 决策树）
  - `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\create-pull-request\SKILL.md`
- 关联工具：Charles 同时存在一个名为 `web_search`（下划线）的**内置工具**（`agent\tools\web_tool.py` L37，基于 DuckDuckGo），与本报告对比的 `web-search`（连字符）**技能**是两个不同的对象，后文详述。
- `nanobot` 残留扫描：在 `agent_config\skills\web-search\` 目录（含 SKILL.md 与 scripts\search_market.py）全文搜索 `nanobot`，**零匹配**；搜索 `use_skill`，**零匹配**。

## 2. Cline 是否有同类技能

**结论：Cline 无网络搜索 / 财经新闻 / 政策法规 / 行业动态相关 SKILL.md。**

对 Cline 仓库内全部 6 份 SKILL.md 做 `web|search|news|finance|stock` 关键词搜索，**零匹配**。Cline 的 6 份技能全部围绕自身工程化场景：`publish-ui` / `publish-desktop` / `publish-cli`（npm & 桌面发布）、`opentui`（终端 UI 框架）、`cline-sdk`（Agent SDK）、`create-pull-request`（PR 流程）。没有任何联网搜索、财经新闻聚合、政策法规检索相关技能。

此外，Cline 在工具层面也**不提供独立的网络搜索工具**（详见 P3.21 `phase_3.21_web_tool.md`）：Cline 的 `DefaultToolName` 枚举仅含 `search_codebase` / `fetch_web_content` 等 9 个工具，无 `web_search`。Cline 的联网搜索能力通过 MCP 服务器接入（如 Brave Search MCP / Tavily MCP）。

因此本报告转为：**评估 Charles 的 `web-search/SKILL.md` 是否符合 Cline 的 SKILL.md 风格规范**，并标注与 Charles 内置 `web_search` 工具的关系。

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

## 4. Charles agent_config 版 SKILL.md 逐项对比

### 4.1 Frontmatter

Charles agent_config 版（第 1-5 行）：

```yaml
---
name: web-search
description: "联网搜索财经新闻、政策法规、行业动态等实时信息"
when_to_use: "用户询问实时新闻/政策法规/行业动态/市场热点/公告通知等需要联网获取的信息时"
---
```

| 字段 | Charles agent_config | Cline 规范 | 评估 |
|------|---------------------|------------|------|
| `name` | `web-search`（连字符） | 必备，且需与目录名一致 | 一致（目录名同为 `web-search`） |
| `description` | 简短中文一句话 | 必备，但 Cline 习惯 "Use when ..." 句式 | 字段存在，但句式不符合 Cline "Use when ..." 风格 |
| `when_to_use` | 存在（中文触发场景描述） | Cline 无此字段 | **nanobot 风格字段**：独立触发字段，不符合 Cline 把触发场景并入 `description` 的规范。与 `read-pdf` / `stock-price` / `write-report` / `compare-reports` 等同批技能的 `when_to_use` 字段一致，属同批残留 |
| `keywords` | 不存在 | Cline 无此字段 | 已清理（或从未存在，因无原版对照） |
| `capabilities` | 不存在 | Cline 无此字段 | 已清理（或从未存在） |
| `always` | 不存在 | Cline 无此字段 | 本技能未标记 always-on，与 `read-pdf`（`always: true`）不同 |

**结论**：frontmatter 已极简化，仅保留 `name` + `description` + `when_to_use` 三字段。相比 `read-pdf`（有 `always: true`）和 `write-report`（有 `when_to_use`），本技能的 frontmatter 更接近 Cline 极简规范，**仅 `when_to_use` 一项为 nanobot 风格残留**。

### 4.2 主体结构

Charles agent_config 版章节顺序（共 8 个章节）：

1. `# web-search 技能指南`
2. `## 本技能核心能力`（含工作方式 3 步、适用内容、不适用内容边界）
3. `## 场景路由`（项目符号列表，4 种场景）
4. `## Workflow` → `### Step 1: 调用搜索脚本` / `### Step 2: 整理搜索结果`
5. `## 脚本角色说明`（1 个主脚本）
6. `## 脚本调用规则`（3 条编号规则）
7. `## 禁止行为`（4 条禁止项）

与 Cline 规范对照：

| Charles 章节 | Cline 是否常见 | 评估 |
|--------------|----------------|------|
| 本技能核心能力 | Cline 通常用标题下一句话引言代替 | 风格略不同，可接受 |
| 场景路由 | Cline 用 ASCII 决策树（opentui/cline-sdk）或编号 Step | **形式不同**：Charles 用项目符号列表，Cline 用决策树。功能等价 |
| Workflow / Step 1-2 | 与 Cline `## Workflow` + 编号 Step 一致 | **已对齐 Cline 风格** |
| 脚本角色说明 | Cline 不单独列脚本角色，命令直接嵌在 Step 中 | **偏 nanobot 风格**（单独成章列脚本角色） |
| 脚本调用规则 | Cline 通过 "Always ..." 句式嵌入步骤，不单独成章 | **偏 nanobot 风格** |
| 禁止行为 | Cline **无此章节**，行为约束嵌入 Workflow | **nanobot 风格残留** |

**结论**：主体结构**已部分对齐 Cline 风格**——引入 `## Workflow` + `### Step 1/2` 结构。但保留 `## 脚本角色说明` / `## 脚本调用规则` / `## 禁止行为` 三个 nanobot 风格章节。与同批 `read-pdf` / `stock-price` / `write-report` 的结构一致，属同批技能的统一风格。

### 4.3 脚本调用

| 维度 | Charles agent_config | Cline 规范 |
|------|---------------------|------------|
| 命令格式 | `python agent_config/skills/web-search/scripts/search_market.py --query "<搜索关键词>" --num 10` | 命令以仓库根目录为相对基准 |
| 路径前缀 | `agent_config/skills/...`（相对仓库根） | 一致 |
| 代码块语言 | ```bash | ```sh / ```bash |
| 参数说明 | 每步命令下用项目符号列表标注 `--query` (必填) / `--num` (可选) | Cline 通常用列表说明参数 |
| 失败处理 | Step 1 内单列"失败处理"子项（网络错误/无结果） | Cline 也常在 Step 内列 "If ... " 失败处理 |

**结论**：脚本调用部分**已完全对齐 Cline 风格**——使用 ```bash 代码块、路径相对仓库根（`agent_config/skills/...`）、参数有必填/可选标注、失败处理嵌入 Step 内。

**注意**：SKILL.md 的 Step 1 命令为 `search_market.py --query ... --num 10`，但 `search_market.py` 脚本实际接受 `--type` 参数（stock/news/policy/general，见脚本 L31-58 的 `SEARCH_PROMPTS`），SKILL.md 未暴露 `--type` 参数。这是文档与脚本的能力偏差，但不属于本报告的 Cline 对标范围。

### 4.4 形式风格

| 维度 | Charles agent_config | Cline 规范 |
|------|---------------------|------------|
| 语言 | 中文 | 英文为主 |
| 语气 | 偏指令式（"禁止..."、"不要..."） | 偏协作式（"Always ask before..."、"Do not guess"） |
| 长度 | 约 75 行，简洁 | publish-cli 约 266 行，较详尽；publish-ui 约 153 行 |
| 失败处理 | 每个 Step 内单列"失败处理"子项 | Cline 也常在 Step 内列 "If ... " 失败处理 |
| 示例对话 | 无 | Cline 不用示例对话，用 Step 描述 |
| 表格使用 | 无 | Cline opentui 用表格列 reference 文件结构 |
| 硬编码日期 | 无 | Cline 无日期硬编码 |

**结论**：
- 中文表达本身不违反 Cline 规范（Cline 无明文规定语言），但与 Cline 6 份样本全英文相比存在风格偏差。Charles 项目其他 SKILL.md 均为中文，保持中文一致性可接受。
- 本技能**无硬编码日期**（与 `read-pdf` L101 / `write-report` L94 的 "2026-07-27" 硬编码日期不同），维护性更好。
- 长度约 75 行，是 Charles 同批技能中最简洁的一份（`read-pdf` 124 行、`stock-price` 65 行、`write-report` 104 行）。

## 5. 残留分类

### 5.1 注释残留

**无 `nanobot` / `use_skill` 注释残留。** 在 `agent_config\skills\web-search\` 目录（含 SKILL.md 与 scripts\search_market.py）全文搜索 `nanobot` 与 `use_skill`，**零匹配**。SKILL.md 正文中无 `nanobot` 字样、无历史注释痕迹、无 `use_skill` 旧工具名残留。

### 5.2 实现逻辑残留（nanobot 风格残留）

| 残留项 | 位置 | 说明 |
|--------|------|------|
| `when_to_use` frontmatter 字段 | 第 4 行 | nanobot 风格的独立触发字段。Cline 用 `description` 内 "Use when ..." 句式代替 |
| `## 脚本角色说明` 章节 | 第 58-62 行 | nanobot 习惯单独列脚本角色；Cline 把脚本信息直接嵌在 Workflow Step 中 |
| `## 脚本调用规则` 章节 | 第 64-68 行 | nanobot 习惯单独列调用规则；Cline 用 "Always ..." 句式嵌入步骤 |
| `## 禁止行为` 章节 | 第 70-75 行 | nanobot 习惯单独设禁止章节；Cline 无此章节，行为约束嵌入 Workflow |
| `## 场景路由` 项目符号列表 | 第 25-32 行 | nanobot 用项目符号；Cline 用 ASCII 决策树（opentui/cline-sdk 风格）。功能等价，形式不同 |

### 5.3 命名不一致问题（`web_search` vs `web-search`）

**重要发现**：SKILL.md 正文中 4 处引用 `web_search`（下划线），但本技能名为 `web-search`（连字符）。

| 行号 | 内容 | 引用对象分析 |
|------|------|-------------|
| 第 68 行 | `3. **不要用 web_search 查股价/财报**: 这些有专门技能` | 指 Charles 内置 `web_search` 工具（`web_tool.py` L37） |
| 第 72 行 | `- 禁止用 \`web_search\` 查询股价/K线数据（用 \`stock-price\` 技能）` | 指 Charles 内置 `web_search` 工具 |
| 第 73 行 | `- 禁止用 \`web_search\` 查询财务指标（用 \`financial-analysis\` 技能）` | 指 Charles 内置 `web_search` 工具 |
| 第 74 行 | `- 禁止用 \`web_search\` 查询年报内容（用 \`read-pdf\` 技能）` | 指 Charles 内置 `web_search` 工具 |

**背景**：Charles 系统中同时存在两个网络搜索相关对象：
1. **`web_search` 工具**（`agent\tools\web_tool.py` L37）：内置工具，基于 DuckDuckGo（`ddgs` 库），返回标题+URL+摘要的原始搜索结果。系统 prompt（`context.py` L765-766）引导 LLM 直接调用此工具进行联网搜索。
2. **`web-search` 技能**（本 SKILL.md）：用户指令技能，基于通义千问 DashScope `enable_search` 能力（`search_market.py` L4），返回 LLM 总结后的结构化搜索结果。LLM 需先调用 `skills(skill="web-search")` 加载本 SKILL.md，再按指令调用 `search_market.py`。

**判定**：这 4 处 `web_search` 引用**并非 nanobot 残留**，而是对 Charles 内置 `web_search` 工具的正确引用。但其出现在 `web-search` 技能的 `## 禁止行为` 章节中，存在**语义混淆风险**：
- `web-search`（连字符，技能）与 `web_search`（下划线，工具）仅一字符之差，LLM 或人类读者容易混淆；
- `## 禁止行为` 章节本应约束"本技能（web-search）的使用边界"，但实际内容约束的是"web_search 工具的使用边界"，对象错位；
- 系统 prompt（`context.py` L766）已包含相同约束"股价/财报等本地已有数据禁止 web_search"，本 SKILL.md 的禁止行为属于重复约束。

**建议**：将 `## 禁止行为` 的 4 条约束改写为针对本技能自身的边界声明，例如"本技能（web-search）不适用于股价/K线数据查询，请改用 `stock-price` 技能"，避免与 `web_search` 工具混淆。

### 5.4 已正确迁移的部分

| 迁移项 | 评估 |
|--------|------|
| Frontmatter 瘦身 | 仅保留 `name` + `description` + `when_to_use`，无 `keywords` / `capabilities` / `allowed_tools` 等 nanobot 扩展字段 |
| 引入 Workflow 结构 | 有 `## Workflow` + `### Step 1/2` 两步流程 |
| 命令代码块化 | 使用 ```bash 代码块 |
| 路径前缀 | `agent_config/skills/...`（相对仓库根） |
| 无示例对话 | 与 Cline Step 描述风格一致 |
| 无硬编码日期 | 维护性良好 |
| 无 nanobot 注释 | 全目录搜索零匹配 |

### 5.5 Charles 独有增强（非残留，非 Cline 对标）

| 增强项 | 位置 | 说明 |
|--------|------|------|
| `## 场景路由` 4 种场景 | 第 25-32 行 | 区分实时新闻/政策法规/行业动态/个股新闻 4 种搜索场景，属 Charles 量化业务特有 |
| `search_market.py` 的 `--type` 参数 | 脚本 L31-58 | 支持 stock/news/policy/general 4 种搜索类型，每类有专用系统提示词。**注意**：SKILL.md 未暴露此参数，属文档缺失 |
| DashScope enable_search 后端 | 脚本 L4 | 与 `web_search` 工具的 DuckDuckGo 后端不同，提供 LLM 增强搜索能力 |

## 6. 与 Cline 风格的一致性总评

| 维度 | 一致性 | 说明 |
|------|--------|------|
| Frontmatter 字段集 | 部分一致 | `name` + `description` 一致；`when_to_use`（nanobot 风格）多余 |
| 主体结构 | 部分一致 | 引入 `## Workflow` + `### Step 1/2` 一致；保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为） |
| 脚本调用 | 一致 | ```bash 代码块、相对仓库根路径、参数必填/可选标注均符合 Cline 风格 |
| 形式风格 | 部分一致 | 中文表达与 Cline 全英文样本有偏差；语气偏指令式；无硬编码日期（优于 read-pdf/write-report） |
| 行为约束方式 | 部分一致 | 单列 `## 禁止行为`，未嵌入 Workflow；且禁止对象为 `web_search` 工具而非本技能自身，存在语义混淆 |
| nanobot 残留 | 无注释残留 | 全目录搜索 `nanobot` / `use_skill` 零匹配 |
| 命名一致性 | 存在偏差 | `web_search`（工具）与 `web-search`（技能）共存，SKILL.md 引用 `web_search` 时易混淆 |

**总体**：Charles `agent_config/skills/web-search/SKILL.md` 已完成约 65% 的 Cline 风格迁移，是同批技能中较简洁的一份。主要差距在：
1. frontmatter 仍保留 `when_to_use`（nanobot 风格）；
2. 主体保留 3 个 nanobot 风格章节（脚本角色说明 / 脚本调用规则 / 禁止行为）；
3. `## 禁止行为` 章节约束对象为 `web_search` 工具而非本技能自身，存在语义混淆。

**与同批技能对比**：
- 迁移程度：`web-search`（约 65%）≈ `read-pdf`（约 60%）≈ `stock-price`（约 65%）> `write-report`（约 55%）。
- 简洁度：`web-search`（75 行）< `read-pdf`（124 行）< `write-report`（104 行），是同批最简洁的。
- 维护性：`web-search` 无硬编码日期，优于 `read-pdf`（L101 "2026-07-27"）和 `write-report`（L94 "2026-07-27"）。
- 独有问题：`web-search` 是同批中唯一存在"技能名（连字符）与工具名（下划线）仅一字符之差"的技能，需特别注意命名混淆风险。

## 7. 改进建议（仅供参考，不在本任务范围内执行）

1. **Frontmatter**：删除 `when_to_use`，把其内容改写为 "Use when ..." 句式合并进 `description`，例如：`description: "Search real-time financial news, regulations, industry trends, market hotspots, and announcements via Qwen enable_search. Use when the user asks about real-time news/policies/industry dynamics/market hotspots/announcements that require internet access."`

2. **`## 禁止行为` 改写**：将 4 条约束的对象从 `web_search` 工具改为本技能自身，避免命名混淆。例如：
   - "禁止用本技能查询股价/K线数据（用 `stock-price` 技能）"
   - "禁止用本技能查询财务指标（用 `financial-analysis` 技能）"
   - "禁止用本技能查询年报内容（用 `read-pdf` 技能）"
   - 或直接删除此章节（系统 prompt `context.py` L766 已包含相同约束）

3. **章节合并**：把 `## 脚本角色说明` 与 `## 脚本调用规则` 合并进 `## Workflow` 的对应 Step，用 "Always ..." 句式表达约束（如 Step 1 中嵌入 "Always use concise keywords separated by spaces, e.g. `贵州茅台 业绩`"）。

4. **`--type` 参数暴露**：`search_market.py` 支持 `--type stock/news/policy/general` 4 种搜索类型，每类有专用系统提示词，但 SKILL.md 的 Step 1 命令未暴露此参数。建议在 Step 1 参数列表中补充 `--type` (可选) 说明，让 LLM 能根据场景路由选择合适的搜索类型。

5. **场景路由决策树**（可选）：把 `## 场景路由` 改为 ASCII 决策树，与 opentui/cline-sdk 风格一致。

6. **与 `web_search` 工具的关系说明**（可选）：在 `## 本技能核心能力` 中补充一句说明本技能（基于 DashScope LLM 增强）与 `web_search` 工具（基于 DuckDuckGo 原始结果）的差异，帮助 LLM 在两者间正确选择。

## 8. 关键文件路径汇总

- Charles agent_config SKILL.md：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\web-search\SKILL.md`
- Charles 脚本：`e:\jikeAI\code\CASE-AI量化系统\agent_config\skills\web-search\scripts\search_market.py`
- Charles 内置 web_search 工具：`e:\jikeAI\code\CASE-AI量化系统\agent\tools\web_tool.py`（L37 `return "web_search"`，基于 DuckDuckGo）
- Charles 系统 prompt 引用：`e:\jikeAI\code\CASE-AI量化系统\agent\context.py` L760 / L766（引导 LLM 调用 `web_search` 工具）
- Charles 自动审批白名单：`e:\jikeAI\code\CASE-AI量化系统\agent\approval_policy.py` L39（`web_search` 在只读自动批准白名单中）
- Cline 对照样本目录：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.cline\skills\` 与 `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.agents\skills\`
- Cline 无 web_search 工具的依据：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_3.21_web_tool.md`（P3.21 已确认 Cline `DefaultToolName` 枚举无 `web_search`）
- charles-nanobot 原版目录（无 web-search 技能）：`e:\jikeAI\code\CASE-AI量化系统\third_party\charles_bundle\charles-nanobot\`（仅含 `AGENTS.md` / `TOOLS.md` / `agent.py` / `config.json`）
- 本报告：`e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_4.15_web_search_skill.md`
