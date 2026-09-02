---
name: write-report
description: "按国泰君安五步法撰写深度分析研报，用于个股深度/季报速评/行业比较/事件驱动/财务异常等场景。Use when 用户要求撰写深度研报/个股分析/季报速评/行业比较/事件驱动分析/财务异常分析时。"
---

# write-report 技能

按国泰君安"五步法"框架撰写深度分析研报：信息差 → 逻辑差 → 预期差 → 催化剂 → 结论+风险闭环。本技能直接在对话中输出 Markdown 格式研报正文，不调用脚本生成；仅当用户明确要求"保存研报文件"时才调用 `report_generator.py`。


## Prerequisites

- 最新完整年报为最近一个完整会计年度的年报（通常在次年 4 月发布）
- 如用户未明确指定报告期，默认分析最新可得年报/财报，请勿默认使用历史报告期

## Workflow

### Step 1: 收集研报所需数据

研报任务开始时执行。根据研报场景，通过 `skills` 工具加载相应能力技能收集数据。

> 必须通过 `skills` 工具加载能力技能获取数据，不要直接用 `read_files` 读取数据文件。可用技能列表见 `skills` 工具描述，根据数据需求匹配相应技能。
> 尽可能全面的使用各个skill获取数据。

**个股深度**（默认场景）需要的数据及对应能力技能：
- 财务指标（毛利率/ROE/负债率等趋势）→ `financial-analysis` 技能
- 年报叙述性内容（业务/订单/客户/风险等）→ `read-pdf` 技能
- 股价走势/成交量（技术面参考）→ `stock-price` 技能
- 所属板块轮动状态（行业景气度参考）→ `sector-rotation` 技能
- 相关概念轮动状态（题材热度参考）→ `concept-rotation` 技能
- 个股舆情/新闻情感分析（市场情绪参考、事件驱动信号识别）→ `sentiment-analysis` 技能
- 宏观情绪与风险指标（市场整体风险偏好参考，辅助估值判断）→ `macro-sentiment` 技能
- 市场预期/催化剂信息（市场热点概览、政策要点综述、个股新闻摘要、机构观点等）→  调用 MCP 网页搜索/提取工具，需要原文时自行读取页面

**季报速评**需要的数据：
- 本地年报/季报 RAG 优先 → `read-pdf` 技能
- 市场预期信息 → 通过 `use_mcp_tool` 调用 MCP 网页搜索/提取工具

**行业比较**需要的数据：
- 同行财务对比 + 估值对比 → `financial-analysis` 技能（peer_compare.py）
- 公司间业务/战略差异 → `compare-reports` 技能
- 各公司所属板块走势对比 → `sector-rotation` 技能

**事件驱动**需要的数据：
- 实时新闻/政策信息（绝对主力）→  调用 MCP 网页搜索工具获取最新新闻/政策
- 舆情/事件驱动信号 → `sentiment-analysis` 技能
- 相关概念轮动状态（题材发酵度）→ `concept-rotation` 技能
- 股价异动 → `stock-price` 技能

**财务异常**需要的数据：
- 财务指标趋势 → `financial-analysis` 技能
- 年报附注深挖 → `read-pdf` 技能

> **交叉验证规则**：所有联网搜索得出的关键事实（公告/政策/新闻要点）必须对照 MCP 搜索工具返回的真实结果与页面原文，确认可追溯来源后再写入研报；不得直接采用未经核实的搜索概述。财报关键数字（毛利率/ROE/负债率等）必须来自本地 `financial-analysis` / `read-pdf` 数据，不得通过网络搜索获取。

预期输出为五步法各步骤所需的数据素材。

### Step 2: 按五步法组织研报

Step 1 数据收集完成后，直接在对话中输出 Markdown 格式研报正文，严格按以下五步组织：

- 信息差：市场还不知道/忽视了什么关键数据？
- 逻辑差：市场看到数据但推理错在哪里？
- 预期差：一致预期 vs 实际偏离多大？可持续吗？
- 催化剂：什么事件/时间节点会触发价值重估？
- 结论+风险闭环：投资建议 + 哪个假设失效会导致结论崩塌？

**关键要求**：

- 每个步骤都要有具体数据支撑，不能空泛
- 结论必须包含风险闭环："如果 XX 假设失效，结论将被推翻"
- 所有财务数据需标注来源

### Step 3: 保存研报文件（可选）

**IMPORTANT**: Do not 调用 `report_generator.py` 生成研报，除非用户明确要求"保存研报文件"。本步骤仅在用户明确要求保存时执行，且前置条件为 Step 2 已在对话中输出完整研报正文。

请将 Step 2 中已在对话输出的研报正文，按 `report_generator.py` 所需的 JSON 结构整理为分析结果文件，再调用脚本生成研报文件。

**先询问用户保存格式**：保存前必须询问用户要哪种格式——`md`（Markdown）/ `html`（自包含 HTML，便于阅读）/ `both`（两种都保存），再据其选择传 `--format` 参数。若用户未指定，默认 `html`。

**JSON 结构要求**（与 Markdown、HTML 两种格式共用同一份 JSON，`report_generator.py` 先生成 Markdown、再按所选格式渲染）：

- `stock_name`：股票名称
- `analysis_date`：分析日期
- `model`：分析模型
- `all_source_pages`（可选）：全部数据来源页码列表（用于报告封面汇总）
- `steps`：五步法各步骤数组，每项含：
  - `step`：步骤序号（1-5）
  - `name`：步骤名，必须取值为 `信息差` / `逻辑差` / `预期差` / `催化剂` / `结论`
  - `analysis`：该步骤正文（直接取自 Step 2 输出的对应章节内容）
  - `source_pages`（可选）：该步骤来源页码列表

```bash
python agent_config/skills/write-report/scripts/report_generator.py --analysis_file <整理后的分析结果JSON> --output_dir outputs/reports/ --format html
```

参数说明：

- `--analysis_file`（必填）：按上述 JSON 结构整理的分析结果文件路径（由你根据 Step 2 正文整理生成。）
- `--output_dir`（可选）：研报输出目录，默认 `./outputs/reports`
- `--format`（可选）：研报输出格式，取值 `md` / `html` / `both`，默认 `md`。`html` 输出自包含样式的 HTML 文件（浏览器直接打开即可阅读），`both` 同时输出 Markdown 与 HTML。

## Script Reference

`scripts/` 目录下的脚本分为两类：

**主脚本（可直接调用）**：

- `report_generator.py` — 保存研报为文件，仅 Step 3 使用（用户明确要求时）

**内部脚本（请勿直接调用）**：

- `five_step_analysis.py` — 五步法分析引擎（调用 LLM 逐步生成分析）。本技能不使用此脚本，研报正文由 agent 直接在对话中输出
- `prompts.py` — 五步法 Prompt 模板，由 `five_step_analysis.py` 内部导入

## Error Handling

- **数据收集不足**：先回到 Step 1 补充缺失数据，再进入 Step 2。
- **用户要求保存研报但 Step 2 正文未整理为 JSON**：将已输出的研报正文按要求 JSON 结构整理为分析结果文件，再调用 `report_generator.py`。

**IMPORTANT**: Do not 停留在"搜索结果总结"阶段，必须输出完整五步法研报。Do not 只说"我将撰写研报"就停止，必须实际输出研报正文。请勿直接调用 `five_step_analysis.py` 或 `prompts.py` 等内部脚本。
