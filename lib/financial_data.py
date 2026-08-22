# -*- coding: utf-8 -*-
# 财务数据加载层 (面板化 + 延迟避免未来函数)
"""
统一入口, 供因子引擎 FN(field) 函数调用:
    - load_financial_field: 加载单个财务字段的面板数据
    - load_financial_panel: 加载并按 panel 对齐 (ffill 到日频)

数据源 (PostgreSQL trade_stock_financial 表):
    字段: stock_code, report_date, revenue, net_profit, eps, roe, roa,
          gross_margin, net_margin, debt_ratio, current_ratio, quick_ratio,
          operating_cashflow, total_assets, total_equity, total_liab,
          monetary_funds, total_shares, ...

参考清华 gl23_day2_fin:
    - fin_Delay: 按财报期 shift 避免未来函数
    - getTargetMatrix: 表格数据转面板矩阵, ffill 对齐

设计:
    1. 查询 trade_stock_financial 得到 (stock_code, report_date, field_value)
    2. 用 report_date + lag_days 作为"数据可用日" (避免未来函数)
       A股Q4年报滞后约120天, 默认 lag_days=120
    3. 按 stock_code 分组, 重建索引到 report_date+lag_days
    4. 调用方用 panel.dates reindex + ffill 对齐到日K
"""

from __future__ import annotations
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor


def _db_config() -> dict:
    """读 .env 里的 PostgreSQL 配置"""
    return {
        "host":     os.environ.get("WUCAI_SQL_HOST", "localhost"),
        "user":     os.environ.get("WUCAI_SQL_USERNAME", "postgres"),
        "password": os.environ.get("WUCAI_SQL_PASSWORD", ""),
        "database": os.environ.get("WUCAI_SQL_DB", "AI-Quant"),
        "port":     int(os.environ.get("WUCAI_SQL_PORT", "5432")),
        "client_encoding": "UTF8",
    }


# ============================================================
# 字段白名单 (防止 SQL 注入, 字段名直接拼 SQL)
# ============================================================

_FINANCIAL_FIELDS = {
    "revenue", "net_profit", "eps", "roe", "roa",
    "gross_margin", "net_margin", "debt_ratio",
    "current_ratio", "quick_ratio",
    "operating_cashflow", "investing_cashflow", "financing_cashflow",
    "total_assets", "total_equity", "total_liab",
    "monetary_funds", "total_shares",
    "ocf_to_revenue", "ocf_to_profit",
    # 与factor_engine.py的_FN_FIELDS保持同步
    "op_margin", "assets_turn", "ocfps", "bps",
}


def _validate_field(field: str) -> str:
    """验证字段名在白名单中, 返回安全的字段名"""
    if field not in _FINANCIAL_FIELDS:
        raise ValueError(f"未知财务字段: {field}, 支持: {sorted(_FINANCIAL_FIELDS)}")
    return field


# ============================================================
# 面板数据加载
# ============================================================

# ============================================================
# 财报披露延迟 (按报告期类型分级, 避免未来函数)
#   年报(12月期) 120天: A股年报最迟次年4月底披露
#   半年报(6月期) 90天: 最迟8月底
#   一季报/三季报(3月/9月期) 45天: 最迟4月底/10月底
#   其余月份(少见) 按90天保守处理
# ============================================================

def _report_lag_days(report_dates) -> np.ndarray:
    """按报告期类型返回每条的披露滞后天数 (向量化)"""
    months = np.asarray(pd.DatetimeIndex(report_dates).month)
    lag = np.full(months.shape, 90, dtype=int)
    lag[months == 12] = 120
    lag[months == 6] = 90
    lag[(months == 3) | (months == 9)] = 45
    return lag


# 进程级缓存: {field: DataFrame}, 避免重复查询
_FIN_PANEL_CACHE: Dict[str, pd.DataFrame] = {}


def load_financial_field(field: str,
                         stock_codes: Optional[List[str]] = None,
                         lag_days: Optional[int] = None) -> pd.DataFrame:
    """加载单个财务字段的面板数据

    参数:
        field:       财务字段名 (eps/roe/net_profit/total_assets/revenue...)
        stock_codes: 股票代码列表, None=全部
        lag_days:    财报发布延迟天数 (避免未来函数)。
                     None=按报告期类型自动分级 (年报120/半年报90/季报45, 推荐);
                     传入整数则统一使用该滞后 (旧口径, 兼容)。

    返回: DataFrame
        index = report_date + lag_days (数据可用日)
        columns = stock_code
        values = field_value
    """
    field = _validate_field(field)

    # 缓存key: 全部股票的数据可缓存, 指定股票子集不缓存
    cache_key = f"{field}_lag{'auto' if lag_days is None else lag_days}"
    if stock_codes is None and cache_key in _FIN_PANEL_CACHE:
        return _FIN_PANEL_CACHE[cache_key].copy()

    # SQL 查询
    conditions = [f"{field} IS NOT NULL"]
    params: list = []
    if stock_codes:
        placeholders = ",".join(["%s"] * len(stock_codes))
        conditions.append(f"stock_code IN ({placeholders})")
        params.extend(stock_codes)

    sql = f"""
        SELECT stock_code, report_date, {field} AS val
        FROM trade_stock_financial
        WHERE {' AND '.join(conditions)}
        ORDER BY stock_code, report_date ASC
    """

    conn = psycopg2.connect(**_db_config())
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame()

    # 构建 DataFrame
    df = pd.DataFrame(rows)
    df["report_date"] = pd.to_datetime(df["report_date"])
    # 数据可用日 = 财报期 + 分级滞后天数 (避免未来函数)
    if lag_days is None:
        df["lag_days"] = _report_lag_days(df["report_date"])
        df["available_date"] = df["report_date"] + pd.to_timedelta(df["lag_days"], unit="D")
    else:
        df["available_date"] = df["report_date"] + pd.Timedelta(days=lag_days)
    df["val"] = pd.to_numeric(df["val"], errors="coerce")

    # 透视: index=available_date, columns=stock_code, values=val
    panel = df.pivot_table(
        index="available_date",
        columns="stock_code",
        values="val",
        aggfunc="last",  # 同一日期同一股票取最后一条
    )
    panel = panel.sort_index()

    # 按股票逐列去重日期 (同一available_date可能有多条, 保留最新report_date的)
    # pivot_table aggfunc=last 已处理

    # 缓存 (仅全部股票的情况)
    if stock_codes is None:
        _FIN_PANEL_CACHE[cache_key] = panel

    return panel.copy()


def load_financial_panel(field: str,
                         dates: pd.DatetimeIndex,
                         stock_codes: List[str],
                         lag_days: Optional[int] = None) -> pd.DataFrame:
    """加载财务字段并按日K面板对齐 (ffill)

    参数:
        field:       财务字段名
        dates:       日K日期索引 (DatetimeIndex)
        stock_codes: 股票代码列表
        lag_days:    披露滞后天数; None=按报告期类型自动分级 (推荐)

    返回: DataFrame (index=dates, columns=stock_codes)
          季度财务数据 ffill 到日频, 已考虑披露延迟
    """
    # 加载原始面板 (index=available_date, columns=stock_code)
    raw_panel = load_financial_field(field, stock_codes=stock_codes, lag_days=lag_days)

    if raw_panel.empty:
        # 返回空面板, 形状与目标一致
        return pd.DataFrame(index=dates, columns=stock_codes, dtype=float)

    # 对齐到日K日期: reindex + ffill
    # 只保留 available_date <= 当前日期 的数据 (避免未来函数)
    result = raw_panel.reindex(columns=stock_codes)
    # 用 asof 方式对齐: 对每个日期, 取 <= 该日期的最后一条
    result = result.reindex(result.index.union(dates)).sort_index().ffill()
    result = result.reindex(dates)

    return result


# ============================================================
# 清华 fin_Delay 实现: 按财报期 shift N 期
# ============================================================

def fin_Delay(fin_panel: pd.DataFrame, n: int = 1) -> pd.DataFrame:
    """按财报期延迟 N 期 (避免未来函数)

    清华 gl23_day2_fin 的 fin_Delay: 取前 N 期财报数据, 而不是前 N 个交易日。

    实现: 面板已 ffill 到日频, 按"财报生效点"(值发生变化的日期)识别每个财报块,
    把第 j 个财报块的值替换为第 j-n 个财报块的值 (等价于按财报期 shift N 期),
    最早的 N 个财报块置 NaN。

    修复: 旧实现用 fin_panel.shift(n*63) 近似"一个季度63个交易日",
    与披露滞后(120/90/45天)叠加造成双重延迟; 现改为精确按财报期 shift。
    """
    if n <= 0:
        return fin_panel
    out = fin_panel.copy()
    for col in fin_panel.columns:
        s = fin_panel[col]
        if s.notna().sum() == 0:
            continue
        # 财报生效点: 非空且与上一行不同的位置
        starts = s[(s.notna()) & (s.ne(s.shift()))]
        block_vals = starts.values
        block_ids = (s.notna() & s.ne(s.shift())).cumsum() - 1  # 生效块编号 0..k-1
        shifted = pd.Series(np.nan, index=s.index, dtype=float)
        for j, v in enumerate(block_vals):
            if j - n >= 0:
                shifted[block_ids == j] = block_vals[j - n]
        out[col] = shifted
    return out


def clear_financial_cache():
    """清空财务数据缓存"""
    _FIN_PANEL_CACHE.clear()
