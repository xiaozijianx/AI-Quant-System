---
name: concept-rotation
description: "查询概念轮动情况(每日排名靠前概念/单概念指标详情/股票高关联概念走势)。Use when 用户询问概念轮动/哪些概念热门/概念排名/某概念近期走势/某股票相关概念情况，以及其他可能需要概念数据支撑的场景。"
---

# concept-rotation 技能

查询概念板块的轮动情况，数据来自 `trade_concept_rotation_daily`（每日全部概念的轮动指标）和 `concept_daily_full`（概念指数K线）。数据库存储**全部概念**的每日计算结果，不局限于页面展示的前15名，任意概念均可查询。

## Prerequisites

- PostgreSQL 数据库可用（配置在项目根目录 `.env` 或环境变量 `WUCAI_SQL_*`）
- `trade_concept_rotation_daily` 表已有数据（由 CASE-A4 概念数据准备 + concept_rotation 计算写入）

## Workflow

根据用户意图选择模式：

### 模式A: 概念轮动矩阵（最近哪些概念热门）

当用户问"最近概念轮动情况""哪些概念热门""每日概念排名"时使用。

```bash
python agent_config/skills/concept-rotation/scripts/query_concept_rotation.py --mode matrix --days 20 --top-n 15
```

参数说明：
- `--days`（可选）：回溯交易日数，默认 `20`
- `--top-n`（可选）：每日取前 N 名，默认 `15`

预期输出：每日 Top N 概念排名列表（日期/排名/概念名/概念代码/来源/综合分/阶段）。

### 模式B: 单概念详情（给定概念查近期情况）

当用户问"AI算力概念最近怎么样""半导体概念走势"时使用。支持概念名称或概念代码，名称支持模糊匹配（如输入"算力"可自动匹配到含"算力"的概念）。

```bash
python agent_config/skills/concept-rotation/scripts/query_concept_rotation.py --mode detail --concept "AI算力" --days 20
```

参数说明：
- `--concept`（必填）：概念名称（如 `AI算力`、`半导体`、`新能源汽车`）或概念代码，支持模糊匹配
- `--days`（可选）：历史排名回溯天数，默认 `20`（概念轮动周期较短，20日足够）

预期输出：该概念最新交易日的指标明细（综合分/排名/动量Z/相对强度Z/量能比Z/MA斜率/MACD等，**每个指标附带中文描述**）+ 近20日排名走势 + 近1年指数K线（最近60条）+ 相关性最高的5只股票。

### 模式C: 股票反查高关联概念（给定股票查其相关概念情况）

当用户问"贵州茅台相关概念怎么样""XX股票涉及哪些热门概念"时使用。先查该股票高关联度概念（concept_stock_relevance 中 rank_in_stock ≤ 5 的最相关概念），再查该概念详情。

```bash
python agent_config/skills/concept-rotation/scripts/query_concept_rotation.py --mode stock --stock 600519.SH --days 20
```

参数说明：
- `--stock`（必填）：股票代码，**支持带或不带交易所后缀**。脚本优先精确匹配，匹配不到时自动尝试常见后缀。如 `600519.SH`、`600519`、`000858.SZ`、`000858` 均支持。
- `--days`（可选）：历史回溯天数，默认 `20`

预期输出：该股票所有高关联概念（rank_in_stock ≤ 5）的完整详情，每个概念包含明细指标、排名走势、指数K线和高相关股票。

## Script Reference

`scripts/query_concept_rotation.py` 是唯一主脚本，通过 `--mode` 参数区分三种查询模式。脚本复用 `concept_rotation.rotation_store` 的查询函数，不依赖 HTTP 服务运行。

**指标字段说明**（模式B/C的 detail.indicators）：
- `mom10_z`：10日动量Z-score（截面标准化，0=全部概念均值，正值=强于均值）
- `rs20_z`：20日相对强度Z-score（截面标准化，0=全部概念均值，正值=强于均值）
- `vol_ratio_z`：量能比Z-score，成交量比率(5日/20日)经截面标准化
- `roc_20`：20日变化率(%)，公式 (close_t - close_t-20) / close_t-20 * 100，一阶导速度类指标
- `ma20_slope`：MA20斜率（年化%/年），对MA20做10日最小二乘线性回归，反映中期趋势速度
- `ma20_accel`：MA20加速度（年化%/年），当前MA20斜率与5日前斜率之差，反映趋势加速度
- `macd_hist`：MACD柱状值，DIF-DEA，速度差的变化，二阶导代理指标
- `hist_delta`：MACD柱变化，当日MACD柱状值相对上一日变化，判断加速或减速

**阶段(phase)含义**：`accel_up`=主升加速、`decel_up`=高位钝化、`accel_down`=主跌、`decel_down`=左侧抄底、`neutral`=中性。

**相关股票字段**（模式B/C的 relevant_stocks）：
- `total_score`：综合相关性得分
- `corr_score`：相关性得分
- `leader_score`：龙头得分

## Error Handling

- **概念未找到**：脚本自动尝试模糊匹配（名称 LIKE + 代码匹配）。若仍无结果，提示用户确认概念名称，可用模式A查看当前上榜概念。
- **股票未找到高关联概念**：提示用户确认股票代码是否正确。脚本支持带或不带后缀的输入，`600519` 和 `600519.SH` 均能匹配。
- **数据库连接失败**：提示用户检查 PostgreSQL 服务和 `.env` 配置。

**IMPORTANT**: 数据库存储全部概念数据，不局限于页面Top15。用户给定的概念只要在概念分类中即可查询。模式B支持概念名称和代码两种输入，优先精确匹配，其次模糊匹配。
