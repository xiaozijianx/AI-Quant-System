---
name: sentiment-analysis
description: "获取财经新闻、计算情感评分、识别事件驱动信号，用于个股/板块舆情分析。Use when 用户询问舆情/情感分析/新闻事件影响/事件驱动信号/板块情绪，以及其他可能需要舆情数据支撑的场景。"
---

# sentiment-analysis 技能

财经新闻舆情分析，包括情感评分和事件识别两个独立能力。

工作方式：首先获取财经新闻数据（必需）；基于新闻数据计算情感评分（可选，看用户是否需要情感分析）；基于新闻数据识别事件驱动信号（可选，看用户是否需要事件分析）。Step 2 和 Step 3 是**独立的**，可根据用户需求只执行其中一个。

## Prerequisites

- 本技能需要网络可访问新闻数据源
- 本地新闻数据目录 `data/news_data/` 可能存在也可能不存在，请勿假设一定有数据

## Workflow

Step 1（获取新闻）是必需的前置步骤。Step 2（情感评分）和 Step 3（事件识别）是独立的，根据用户需求选择执行其中一个或两个。用户明确要求下载新闻时只执行 Step 1。

### Step 1: 获取财经新闻数据（必需）

所有舆情分析任务的第一步。请勿跳过此步骤直接执行 Step 2 或 Step 3。

```bash
python agent_config/skills/sentiment-analysis/scripts/news_fetcher.py --stock <股票代码> --days 30
```

参数说明：

- `--stock`（可选）：股票代码**不带交易所后缀**，如 `600519`。与 `--keywords` 至少指定其一
- `--keywords`（可选）：关键词，逗号分隔（如 `资产重组,回购`）。与 `--stock` 至少指定其一
- `--days`（可选）：获取最近 N 天新闻，默认 `7`
- `--output_dir`（可选）：输出目录，默认 `./data`
- `--include_cctv`（可选）：是否包含央视新闻（政策面参考）

预期输出为新闻列表 JSON 文件（保存到 `--output_dir` 目录，默认 `./data/`，文件名为 `<股票代码>_news.json` 或 `<关键词>_news.json`）。

### Step 2: 计算情感评分（可选）

当用户需要情感分析/舆情评分时执行此步骤。前置条件：Step 1 已获取新闻数据。若用户只需要事件识别，可跳过此步直接执行 Step 3。

```bash
python agent_config/skills/sentiment-analysis/scripts/sentiment_scorer.py --news_file <新闻JSON文件>
```

参数说明：

- `--news_file`（必填）：新闻 JSON 文件路径（Step 1 输出）
- `--output_dir`（可选）：输出目录，默认 `./output`
- `--model`（可选）：LLM 模型，默认 `qwen-turbo`
- `--max_news`（可选）：最大分析条数，默认 `50`

预期输出为情感评分报告（正面/负面/中性占比 + 情感分数）。

### Step 3: 识别事件驱动信号（可选）

当用户需要事件驱动分析时执行此步骤。前置条件：Step 1 已获取新闻数据。若用户只需要情感评分，可跳过此步。

```bash
python agent_config/skills/sentiment-analysis/scripts/event_detector.py --news_file <新闻JSON文件>
```

参数说明：

- `--news_file`（必填）：新闻 JSON 文件路径（Step 1 输出）
- `--output_dir`（可选）：输出目录，默认 `./output`
- `--model`（可选）：LLM 模型，默认 `qwen-turbo`
- `--use_llm`（可选）：启用 LLM 精细事件识别（较慢但更准确）

预期输出为事件驱动信号报告（事件类型 + 影响评估 + 相关新闻）。

## Script Reference

`scripts/` 目录下所有脚本都是主脚本，可直接调用：

- `news_fetcher.py` — 获取财经新闻数据，Step 1 使用（必需）
- `sentiment_scorer.py` — 计算情感评分，Step 2 使用（可选）
- `event_detector.py` — 识别事件驱动信号，Step 3 使用（可选）

**脚本调用约定**：

1. 股票代码不带后缀：Step 1 的 `news_fetcher.py` 用不带后缀的代码，如 `600519`
2. Step 1 是必需的：无论用户需要情感评分还是事件识别，都必须先执行 Step 1 获取新闻
3. Step 2 和 Step 3 独立：可根据用户需求只执行其中一个，不需要按顺序执行
4. Step 2/3 使用新闻文件：`sentiment_scorer.py` 和 `event_detector.py` 通过 `--news_file` 参数接收 Step 1 输出的新闻 JSON 文件，不再使用 `--stock`

## Error Handling

- **网络错误**：提示用户检查网络后重试。
- **无新闻数据**：提示用户尝试其他股票代码或扩大时间范围。
- **Step 1 失败**：必须重试或提示用户，请勿假设本地一定有新闻数据。

**IMPORTANT**: Do not 跳过 Step 1 直接执行 Step 2 或 Step 3（需要新闻数据作为输入）。Do not 用网络搜索替代本技能，本技能有专门的新闻获取和情感分析脚本。
