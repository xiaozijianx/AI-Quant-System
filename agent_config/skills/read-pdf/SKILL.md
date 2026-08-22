---
name: read-pdf
description: "查询上市公司年报/季报/公告等PDF叙述性内容，支持本地RAG查询；若本地无索引/PDF，自动下载并构建索引。Use when 用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容，以及其他可能需要年报叙述性内容支撑的场景。"
---

# read-pdf 技能

查询上市公司年报/季报/公告中的**叙述性内容**（业务讨论、订单、客户、供应商、风险因素等）。本技能可自动下载年报 PDF 并解析为可检索文本，用户无需提前准备 PDF 文件。

工作方式：优先查询本地 RAG 索引；若本地无索引或 PDF，自动调用下载脚本从巨潮资讯获取年报 PDF，下载后自动构建 RAG 索引并再次查询。

> 结构化财务数字（营收、毛利率等）请改用 `financial-analysis` 技能。

## Prerequisites

- 本地 RAG 索引目录 `data/vector_store/` 可能存在也可能不存在，请勿假设一定有数据。
- 若本地无索引，需要网络可访问巨潮资讯以下载年报 PDF。

## Workflow

执行路径根据用户意图选择：查询年报内容走 Step 1→3（无结果时 Step 2 下载再 Step 3 重查）；用户明确要求下载时跳过 Step 1 直接 Step 2→3。`fetch_report_pdf.py` 内部会自动调用解析脚本，无需手动调用 `parse_pdf_basic.py` 或 `parse_pdf_ocr.py`。

### Step 1: 尝试直接查询本地 RAG 索引

当用户询问年报/公告叙述性内容时，首先执行此步骤（除非用户明确要求下载）。请直接尝试查询，不要假设本地无数据，也不要先用 `read_files` 验证索引是否存在。

```bash
python agent_config/skills/read-pdf/scripts/query_report.py --index_dir data/vector_store --query "<用户问题的核心关键词>" --stock <股票代码>
```

> 注意：RAG 查询涉及加载 embedding 模型、向量索引和 jieba 分词，首次执行或索引较大时可能需要 30~120 秒。调用 `run_commands` 时请显式设置 `timeout: 120`（秒），避免默认 30 秒超时中断。下载年报并构建索引的 `fetch_report_pdf.py` 耗时更长，建议 `timeout: 300`。

参数说明：

- `--index_dir`（必填）：索引目录，固定为 `data/vector_store`
- `--query`（必填）：用户问题的核心关键词，用简洁中文，如 `主营业务构成`、`前五大客户`、`AI服务器进展`
- `--stock`（必填）：股票代码**不带交易所后缀**，如 `600519`、`300750`

预期输出为匹配的文档片段 + 文档名 + 页码。若返回有效结果，请直接引用文档名和页码回答用户，**到此结束，不执行后续步骤**。若无结果或索引不存在，进入 Step 2。

### Step 2: 下载年报 PDF 并构建索引

当 Step 1 查询无结果时，或用户明确要求下载年报时执行此步骤（用户明确要求下载时可跳过 Step 1）。

```bash
python agent_config/skills/read-pdf/scripts/fetch_report_pdf.py --stock <股票代码> --category 年度报告
```

> 注意：下载 PDF、解析文本、构建 FAISS 索引整个过程耗时较长，网络正常情况下通常 1~5 分钟。调用 `run_commands` 时请显式设置 `timeout: 300`（秒）。

参数说明：

- `--stock`（必填）：股票代码**不带交易所后缀**，如 `600519`
- `--category`（可选）：报告类型，默认 `年度报告`，支持 `半年度报告` / `季度报告`

该脚本会自动下载最新年报并调用解析脚本 + 构建索引脚本。终端会实时显示进度：`[1/3] 下载 PDF` → `[2/3] PDF 下载完成` → `[3/3] 更新 RAG 统一索引`。前端工具卡片会实时滚动显示终端输出，等待其完成即可，不需要在命令执行期间反复询问是否完成。

### Step 3: 下载完成后再次查询

Step 2 下载完成后，重复 Step 1 的查询命令。预期输出为匹配的文档片段 + 文档名 + 页码，引用文档名和页码回答用户。

## Script Reference

`scripts/` 目录下的脚本分为两类：

**主脚本（可直接调用）**：

- `query_report.py` — RAG 查询，Step 1 和 Step 3 使用
- `fetch_report_pdf.py` — 下载年报 PDF + 自动构建索引，Step 2 使用

**内部脚本（请勿直接调用，由 `fetch_report_pdf.py` 内部自动调用）**：

- `build_index.py` — 构建 FAISS 索引
- `parse_pdf_basic.py` — PyPDF2 基础文本提取
- `parse_pdf_ocr.py` — 多模态大模型 OCR 解析复杂表格

**脚本调用约定**：

1. 股票代码不带后缀：`query_report.py` 和 `fetch_report_pdf.py` 都用不带后缀的代码（如 `600519`，不是 `600519.SH`）
2. 查询关键词要简洁：用 `主营业务构成` 而非 `公司的主营业务是什么`
3. 索引目录固定：`--index_dir data/vector_store` 是默认位置，请勿修改
4. 下载脚本会自动构建索引：无需单独调用 `build_index.py`

## 年报年份规则

- "XXXX 年年报"指 XXXX 财年报告《XXXX 年年度报告》，通常在次年 4 月发布
- 默认按财务期间理解；只有用户明确说"发布""披露"时才按发布年份理解

最新完整年报为最近一个完整会计年度的年报。

## 数据源选择

根据需要的数据类型选择合适的数据源：

- 最新年报及以前年度的财务数据 → RAG（年报）或 financial-analysis CSV
- 最新季度财务数据 → financial-analysis CSV（含季报）
- 年报中的叙述性内容 → RAG（本技能）
- 结构化财务指标趋势 → financial-analysis CSV

## Error Handling

- **网络错误**：提示用户检查网络后重试。
- **报告不存在**：尝试其他 `--category` 或提示用户确认股票代码。
- **Step 1 查询无结果或索引不存在**：进入 Step 2 下载并构建索引，不要因为没有数据就放弃。

**IMPORTANT**: Do not fabricate data. 若本地无索引或 PDF，请执行 Step 2 下载后再次查询，不要编造内容。请勿直接调用 `parse_pdf_basic.py`、`parse_pdf_ocr.py`、`build_index.py` 等内部脚本。请勿跳过 Step 1 直接执行 Step 2（除非用户明确要求下载）。请勿先用 `read_files` 去读取不确定存在的本地文件来"验证"数据是否存在。
