---
name: financial-analysis
description: "分析上市公司财务指标趋势(毛利率/ROE/负债率等)，支持同行横向对比，包含CSV财务数据下载能力。Use when 用户询问财务指标/毛利率/ROE/负债率/营收趋势/同行对比等结构化数字，以及其他可能需要财务数据支撑的场景。"
---

# financial-analysis 技能

分析上市公司**结构化财务数字**（营收、毛利率、ROE、负债率等指标趋势），支持同行横向对比。本技能可自动下载结构化财务 CSV 数据（财务摘要/利润表/资产负债表/现金流量表），无需用户提前准备文件。

工作方式：优先读取本地 CSV 数据；若本地无 CSV，自动调用下载脚本从东方财富获取；下载后计算核心财务指标（毛利率/净利率/ROE/负债率等）；支持多家公司同行横向对比。

> 年报中的叙述性内容（业务讨论、订单、客户等）请改用 `read-pdf` 技能。

## Prerequisites

- 本地 CSV 数据目录 `data/financial_data/` 可能存在也可能不存在，请勿假设一定有数据。
- 若本地无 CSV，需要网络可访问东方财富以下载数据。

## Workflow

执行路径根据用户意图选择：单股指标走 Step 1→3；下载走 Step 2；同行对比走 Step 1→4（缺失的先 Step 2 补齐）。

### Step 1: 检查本地是否已有 CSV 数据

当用户询问财务指标或同行对比时，首先检查本地数据。请直接检查，不要假设本地有数据。

检查方式：用 `read_files` 读取 `data/financial_data/{股票代码}_financial_abstract.csv`。

- 股票代码格式：不带交易所后缀，如 `600519`（文件名：`600519_financial_abstract.csv`）
- 预期输出：CSV 文件内容（财务摘要表格）

若文件存在，跳过 Step 2，直接进入 Step 3 计算指标或 Step 4 同行对比。若文件不存在，进入 Step 2 下载。

> 同行对比场景：请检查所有涉及的公司的 CSV 文件，缺失哪家就下载哪家。

### Step 2: 下载财务 CSV 数据

当 Step 1 检查发现本地无 CSV 时，或用户明确要求下载时执行此步骤（用户明确要求下载时可跳过 Step 1）。

```bash
python agent_config/skills/financial-analysis/scripts/fetch_financial_csv.py --stock <股票代码>
```

参数说明：

- `--stock`（必填）：股票代码**不带交易所后缀**，如 `600519`

**IMPORTANT**: Do not specify `--output_dir`，脚本默认输出到 `data/financial_data/`，指定该参数会破坏默认路径约定。

预期输出为 4 个 CSV 文件（`_financial_abstract.csv` / `_income_statement.csv` / `_balance_sheet.csv` / `_cash_flow.csv`）。

### Step 3: 计算核心财务指标

本地已有 CSV 数据后（Step 1 成功或 Step 2 下载完成）执行此步骤。

```bash
python agent_config/skills/financial-analysis/scripts/ratio_analysis.py --stock <股票代码> --years 5
```

参数说明：

- `--stock`（必填）：股票代码**不带交易所后缀**，如 `600519`
- `--years`（可选）：分析年数，默认 `5`

预期输出为结构化财务指标表格（毛利率/净利率/ROE/负债率/营收增长率等）。

### Step 4: 同行横向对比（可选）

当用户需要同行对比时执行此步骤。前置条件：所有对比公司的 CSV 数据都已存在，若缺失需先执行 Step 2 下载。

```bash
python agent_config/skills/financial-analysis/scripts/peer_compare.py --stocks <代码1,代码2,...>
```

参数说明：

- `--stocks`（必填）：多个股票代码逗号分隔，**不带交易所后缀**，如 `600519,000858,002594`

预期输出为同行财务指标对比表格。

## Script Reference

`scripts/` 目录下所有脚本都是主脚本，可直接调用：

- `fetch_financial_csv.py` — 下载财务 CSV 数据，Step 2 使用
- `ratio_analysis.py` — 计算核心财务指标，Step 3 使用
- `peer_compare.py` — 同行横向对比，Step 4 使用

**脚本调用约定**：

1. 股票代码不带后缀：所有脚本都用不带后缀的代码（如 `600519`，不是 `600519.SH`）
2. 请勿指定 `--output_dir`：`fetch_financial_csv.py` 默认输出到 `data/financial_data/`
3. CSV 文件名格式：`{代码}_{报表类型}.csv`，如 `600519_financial_abstract.csv`

## 数据来源

- `data/financial_data/{股票代码}_financial_abstract.csv`（东方财富财务摘要）
- `data/financial_data/{股票代码}_income_statement.csv`（利润表）
- `data/financial_data/{股票代码}_balance_sheet.csv`（资产负债表）
- `data/financial_data/{股票代码}_cash_flow.csv`（现金流量表）

## Error Handling

- **网络错误**：提示用户检查网络后重试。
- **股票代码不存在**：提示用户确认代码。
- **Step 1 检查发现文件不存在**：进入 Step 2 下载，请勿假设本地一定有 CSV 数据。

**IMPORTANT**: Do not fabricate data. 若 Step 1 检查失败必须执行 Step 2 下载。请勿用 `read_files` 读 `data/parsed/` 下的切分文件（那是给 RAG 用的）。
