---
name: sector-rotation
description: "查询申万板块轮动情况(每日排名靠前板块/单板块指标详情/股票所属板块走势)。Use when 用户询问板块轮动/哪些板块强势/板块排名/某板块近期走势/某股票所在板块情况，以及其他可能需要板块数据支撑的场景。"
---

# sector-rotation 技能

查询申万行业板块的轮动情况，数据来自 `trade_sector_rotation_daily`（每日全部板块的轮动指标）和 `trade_sector_daily`（板块指数K线）。数据库存储**全部申万板块**的每日计算结果，不局限于页面展示的前15名，任意申万一级/二级板块均可查询。

## Prerequisites

- PostgreSQL 数据库可用（配置在项目根目录 `.env` 或环境变量 `WUCAI_SQL_*`）
- `trade_sector_rotation_daily` 表已有数据（由 CASE-A3 板块数据准备 + sector_rotation 计算写入）

## Workflow

根据用户意图选择模式：

### 模式A: 板块轮动矩阵（最近哪些板块强势）

当用户问"最近板块轮动情况""哪些板块强势""每日板块排名"时使用。

```bash
python agent_config/skills/sector-rotation/scripts/query_sector_rotation.py --mode matrix --days 20 --top-n 15
```

参数说明：
- `--days`（可选）：回溯交易日数，默认 `20`
- `--top-n`（可选）：每日取前 N 名，默认 `15`
- `--level`（可选）：板块级别，`1`=申万一级，`2`=申万二级（默认）

预期输出：每日 Top N 板块排名列表（日期/排名/板块名/综合分/阶段）。

### 模式B: 单板块详情（给定板块查近期情况）

当用户问"半导体板块最近怎么样""白酒板块走势"时使用。板块名称支持模糊匹配，无需精确的申万二级分类名（如输入"半导"可自动匹配到"半导体"）。

```bash
python agent_config/skills/sector-rotation/scripts/query_sector_rotation.py --mode detail --sector "半导体" --days 60
```

参数说明：
- `--sector`（必填）：板块名称，支持模糊匹配（如 `半导体`、`半导`、`白酒`、`消费电子`、`证券`）
- `--days`（可选）：历史排名回溯天数，默认 `60`
- `--level`（可选）：板块级别，默认 `2`

预期输出：该板块最新交易日的指标明细（综合分/排名/动量Z/相对强度Z/量能比Z/MA斜率/MACD等，**每个指标附带中文描述**）+ 近60日排名走势 + 近2年指数K线（最近60条）+ 相关性最高的5只股票。

### 模式C: 股票反查所属板块（给定股票查其板块情况）

当用户问"贵州茅台所在板块怎么样""XX股票的板块走势"时使用。先查股票所属申万二级板块，再查该板块详情。

```bash
python agent_config/skills/sector-rotation/scripts/query_sector_rotation.py --mode stock --stock 600519.SH --days 60
```

参数说明：
- `--stock`（必填）：股票代码，**支持带或不带交易所后缀**。脚本优先精确匹配，匹配不到时自动去掉后缀用规则查询数据库，让数据库自行匹配完整代码。如 `600519.SH`、`600519`、`000858.SZ`、`000858` 均支持。
- `--days`（可选）：历史回溯天数，默认 `60`
- `--level`（可选）：板块级别，默认 `2`

预期输出：股票所属板块名 + 该板块的完整详情（同模式B）。

## Script Reference

`scripts/query_sector_rotation.py` 是唯一主脚本，通过 `--mode` 参数区分三种查询模式。脚本复用 `sector_rotation.rotation_store` 的查询函数，不依赖 HTTP 服务运行。

**指标字段说明**（模式B/C的 detail.indicators）：
- `mom21_z`：21日动量Z-score（截面标准化，0=全部板块均值，正值=强于均值）
- `rs60_z`：60日相对强度Z-score（截面标准化，0=全部板块均值，正值=强于均值）
- `vol_ratio_z`：量能比Z-score，成交量比率(5日/60日)经截面标准化
- `roc_20`：20日变化率(%)，公式 (close_t - close_t-20) / close_t-20 * 100，一阶导速度类指标
- `ma20_slope`：MA20斜率（年化%/年），对MA20做10日最小二乘线性回归，反映中期趋势速度
- `ma20_accel`：MA20加速度（年化%/年），当前MA20斜率与5日前斜率之差，反映趋势加速度
- `macd_hist`：MACD柱状值，DIF-DEA，速度差的变化，二阶导代理指标
- `hist_delta`：MACD柱变化，当日MACD柱状值相对上一日变化，判断加速或减速

**阶段(phase)含义**：`accel_up`=主升加速、`decel_up`=高位钝化、`accel_down`=主跌、`decel_down`=左侧抄底、`neutral`=中性。

## Error Handling

- **板块无数据**：脚本自动尝试模糊匹配（ILIKE + 子串匹配）。若仍无结果，提示用户确认板块名称（如"半导体"而非"芯片"），可用模式A查看当前有哪些板块上榜。
- **模糊匹配多个板块**：脚本自动取第一个匹配结果，同时在 `candidates` 字段返回所有候选项，LLM 可据此判断是否需要调整查询。
- **股票未找到**：提示用户确认股票代码是否正确。脚本支持带或不带后缀的输入，`600519` 和 `600519.SH` 均能匹配。
- **数据库连接失败**：提示用户检查 PostgreSQL 服务和 `.env` 配置。

**IMPORTANT**: 数据库存储全部申万板块数据，不局限于页面Top15。用户给定的板块只要属于申万分类即可查询，无需在页面Top15范围内。
