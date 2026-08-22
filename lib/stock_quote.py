# -*- coding: utf-8 -*-
# 个股行情数据层
"""
为「个股行情」页面提供：
    - 日/周/月/年 K 线数据
    - 成交量、涨跌幅
    - MACD 技术指标
    - 财务数据、新闻、研报预期

日线从 lib.backtest_data.load_daily_kline 读取，更高周期由日线 resample 得到。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import numpy as np
import pandas as pd

from lib.stock_utils import normalize_code, _get_db_config


# ============================================================
# 概念查询
# ============================================================

def _load_stock_concepts(stock_code: str, top_count: int = 10, fallback_count: int = 3) -> List[str]:
    """读取股票最新交易日的强相关概念名称列表。

    优先从 concept_stock_relevance（CASE-A4 强相关筛选结果）读取 Top 概念；
    缺失时仅回退少量精选概念，避免 unrelated 概念过多。
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    cfg = _get_db_config()
    conn = psycopg2.connect(**cfg)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. 优先读取强相关概念（按综合分排序）
        cursor.execute(
            """
            SELECT concept_name, total_score
            FROM concept_stock_relevance
            WHERE stock_code = %s
              AND calc_date = (
                  SELECT MAX(calc_date) FROM concept_stock_relevance WHERE stock_code = %s
              )
            ORDER BY rank_in_stock ASC, total_score DESC
            LIMIT %s
            """,
            (stock_code, stock_code, top_count),
        )
        rows = cursor.fetchall()
        if rows:
            return [r["concept_name"] for r in rows if r["concept_name"]]

        # 2. fallback：强相关表缺失时，只取少量精选概念兜底
        cursor.execute(
            """
            SELECT DISTINCT cm.concept_name
            FROM concept_stock_tag cst
            JOIN concept_meta cm ON cm.concept_code = cst.concept_code
            WHERE cst.stock_code = %s
              AND cst.trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
              AND cm.is_active = TRUE AND cm.is_curated = TRUE
            ORDER BY cm.concept_name
            LIMIT %s
            """,
            (stock_code, fallback_count),
        )
        rows = cursor.fetchall()
        return [r["concept_name"] for r in rows if r["concept_name"]]
    finally:
        conn.close()


# ============================================================
# 时间范围与重采样
# ============================================================

_TIMEFRAME_RULES = {
    "daily":   None,
    "weekly":  "W-FRI",
    "monthly": "ME",
}


def _default_date_range(timeframe: str, years: int) -> tuple[str, str]:
    """
    返回足够宽的时间区间，加载数据库中该股票/指数的全部日 K 数据。
    years 参数保留仅用于接口兼容，实际范围由数据库决定；前端 dataZoom 负责默认缩放展示。
    """
    end = datetime.now().date()
    # 1990-01-01 早于 A 股开市时间，可确保取到数据库中最早一条记录
    start = datetime(1990, 1, 1).date()
    return str(start), str(end)


def _load_daily_with_extra(stock_code: str,
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> pd.DataFrame:
    """
    从 trade_stock_daily 读取日 K，包含成交额、换手率等扩展字段。
    返回 DataFrame，索引为日期，列：open/high/low/close/volume/amount/turnover_rate
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conditions = ["stock_code = %s"]
    params = [stock_code]
    if start_date:
        conditions.append("trade_date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    sql = f"""
        SELECT trade_date, open_price, high_price, low_price, close_price,
               volume, amount, turnover_rate
        FROM trade_stock_daily
        WHERE {' AND '.join(conditions)}
        ORDER BY trade_date ASC
    """
    cfg = _get_db_config()
    conn = psycopg2.connect(**cfg)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if not rows:
        raise ValueError(f"PostgreSQL 无数据: {stock_code} ({start_date} ~ {end_date})")

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.set_index("trade_date", inplace=True)
    df.columns = ["open", "high", "low", "close", "volume", "amount", "turnover_rate"]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    valid = (df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)
    df = df.loc[valid]
    if df.empty:
        raise ValueError(f"PostgreSQL 数据全为空: {stock_code}")
    return df


def resample_kline(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """基于日线重采样为周线/月线/年线。"""
    rule = _TIMEFRAME_RULES.get(timeframe)
    if rule is None:
        return df

    # 仅保留有效价格数据
    valid = (df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)
    df = df.loc[valid].copy()

    resampled = df.resample(rule, label="right", closed="right").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })

    # 成交额与换手率：可选字段；指数通常无换手率，不因此丢弃整行
    if "amount" in df.columns:
        resampled["amount"] = df["amount"].resample(rule, label="right", closed="right").sum()
    if "turnover_rate" in df.columns:
        resampled["turnover_rate"] = df["turnover_rate"].resample(rule, label="right", closed="right").mean()

    # 仅当 OHLCV 任一缺失时才丢弃，保留 amount/turnover_rate 为空的行
    resampled = resampled.dropna(subset=["open", "high", "low", "close", "volume"])
    return resampled


# ============================================================
# 技术指标
# ============================================================

def compute_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算 MACD：dif / dea / hist。参数按当前周期单位计算。"""
    close = df["close"].dropna()
    if len(close) < slow + signal:
        return pd.DataFrame(index=df.index, columns=["dif", "dea", "hist"])

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist}, index=df.index)


# ============================================================
# 行情主入口
# ============================================================

def load_quote(code: str, timeframe: str = "daily", years: int = 3) -> Dict:
    """
    加载指定股票/指数的 K 线行情与 MACD。

    返回:
        {
            "ok": True,
            "code": "600519.SH",
            "timeframe": "daily",
            "info": {...},
            "dates": ["2024-01-02", ...],
            "ohlc": [[open, close, low, high], ...],  # ECharts candlestick 格式
            "volume": [v, ...],
            "amount": [a, ...],
            "change_pct": [pct, ...],
            "macd": {"dif": [...], "dea": [...], "hist": [...]},
        }
    """
    from lib.stock_utils import get_stock_info

    norm_code = normalize_code(code)
    if not norm_code:
        return {"ok": False, "message": "股票代码不能为空"}

    if timeframe not in _TIMEFRAME_RULES:
        return {"ok": False, "message": f"不支持的周期: {timeframe}"}

    start, end = _default_date_range(timeframe, max(1, min(years, 10)))

    try:
        df = _load_daily_with_extra(norm_code, start_date=start, end_date=end)
    except Exception as e:
        return {"ok": False, "message": f"加载行情失败: {e}"}

    if timeframe != "daily":
        df = resample_kline(df, timeframe)

    if df.empty:
        return {"ok": False, "message": "无行情数据"}

    # 计算涨跌幅
    df["change_pct"] = df["close"].pct_change() * 100

    # 计算 MACD
    macd_df = compute_macd(df)

    # 组装 ECharts 数据
    dates = df.index.strftime("%Y-%m-%d").tolist()
    ohlc = []
    volume = []
    amount = []
    turnover_rate = []
    change_pct = []

    for idx, row in df.iterrows():
        o = float(row["open"])
        c = float(row["close"])
        h = float(row["high"])
        l = float(row["low"])
        v = float(row["volume"]) if pd.notna(row["volume"]) else 0
        ohlc.append([round(o, 4), round(c, 4), round(l, 4), round(h, 4)])
        volume.append(round(v, 2))

        if "amount" in df.columns and pd.notna(row["amount"]):
            amount.append(round(float(row["amount"]), 2))
        else:
            amount.append(None)

        if "turnover_rate" in df.columns and pd.notna(row["turnover_rate"]):
            turnover_rate.append(round(float(row["turnover_rate"]), 4))
        else:
            turnover_rate.append(None)

        if pd.notna(row["change_pct"]):
            change_pct.append(round(float(row["change_pct"]), 2))
        else:
            change_pct.append(None)

    macd_out = {
        "dif":  [round(float(x), 4) if pd.notna(x) else None for x in macd_df["dif"]],
        "dea":  [round(float(x), 4) if pd.notna(x) else None for x in macd_df["dea"]],
        "hist": [round(float(x), 4) if pd.notna(x) else None for x in macd_df["hist"]],
    }

    info = get_stock_info(norm_code)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    latest_change = float(latest["close"]) - float(prev["close"]) if len(df) > 1 else 0
    latest_pct = (latest_change / float(prev["close"]) * 100) if len(df) > 1 and prev["close"] else 0

    # 补充股票所属概念
    try:
        concepts = _load_stock_concepts(norm_code)
    except Exception:
        concepts = []

    info.update({
        "latest_close": round(float(latest["close"]), 4),
        "latest_change": round(latest_change, 4),
        "latest_change_pct": round(latest_pct, 2),
        "latest_volume": int(latest["volume"]) if pd.notna(latest["volume"]) else 0,
        "latest_amount": round(float(latest["amount"]), 2) if "amount" in df.columns and pd.notna(latest["amount"]) else None,
        "latest_turnover_rate": round(float(latest["turnover_rate"]), 4) if "turnover_rate" in df.columns and pd.notna(latest["turnover_rate"]) else None,
        "data_count": len(df),
        "start_date": dates[0],
        "end_date": dates[-1],
        "concepts": concepts,
    })

    return {
        "ok": True,
        "code": norm_code,
        "timeframe": timeframe,
        "info": info,
        "dates": dates,
        "ohlc": ohlc,
        "volume": volume,
        "amount": amount,
        "turnover_rate": turnover_rate,
        "change_pct": change_pct,
        "macd": macd_out,
    }


# ============================================================
# 财务 / 新闻 / 研报预期
# ============================================================

def _execute_query(sql: str, params: tuple = ()) -> List[Dict]:
    """通用查询，返回字典列表。"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    cfg = _get_db_config()
    conn = psycopg2.connect(**cfg)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()


def _clean_value(v):
    """把 numpy 类型 / NaN / Inf 转成 JSON 友好格式。"""
    if v is None:
        return None
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
    return v


def load_financial(code: str, limit: int = 8) -> List[Dict]:
    """读取季度财务数据。"""
    norm = normalize_code(code)
    rows = _execute_query(
        """
        SELECT report_date, revenue, net_profit, eps, roe, roa, gross_margin,
               net_margin, op_margin, debt_ratio, current_ratio, quick_ratio,
               operating_cashflow, investing_cashflow, financing_cashflow,
               ocf_to_revenue, ocf_to_profit, total_assets, total_equity,
               total_liab, monetary_funds, total_shares, bps, ocfps,
               undist_profit_ps, assets_turn
        FROM trade_stock_financial
        WHERE stock_code = %s
        ORDER BY report_date DESC
        LIMIT %s
        """,
        (norm, max(1, min(limit, 50)))
    )
    out = []
    for r in rows:
        item = {"report_date": str(r["report_date"]) if r["report_date"] else None}
        for k, v in r.items():
            if k == "report_date":
                continue
            item[k] = _clean_value(v)
        out.append(item)
    return out


def load_news(code: str, limit: int = 20) -> List[Dict]:
    """读取个股新闻与情感。"""
    norm = normalize_code(code)
    rows = _execute_query(
        """
        SELECT id, title, summary, source, source_url, published_at,
               sentiment, sentiment_score, is_important
        FROM trade_stock_news
        WHERE stock_code = %s
        ORDER BY published_at DESC NULLS LAST
        LIMIT %s
        """,
        (norm, max(1, min(limit, 50)))
    )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "title": r["title"] or "",
            "summary": r["summary"] or "",
            "source": r["source"] or "",
            "source_url": r["source_url"] or "",
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            "sentiment": r["sentiment"] or "neutral",
            "sentiment_score": _clean_value(r["sentiment_score"]),
            "is_important": bool(r["is_important"]),
        })
    return out


def load_consensus(code: str, limit: int = 20) -> List[Dict]:
    """读取研报一致性预期。"""
    norm = normalize_code(code)
    rows = _execute_query(
        """
        SELECT broker, report_date, rating, target_price,
               eps_forecast_current, eps_forecast_next, revenue_forecast,
               source_file
        FROM trade_report_consensus
        WHERE stock_code = %s
        ORDER BY report_date DESC NULLS LAST
        LIMIT %s
        """,
        (norm, max(1, min(limit, 50)))
    )
    out = []
    for r in rows:
        out.append({
            "broker": r["broker"] or "",
            "report_date": str(r["report_date"]) if r["report_date"] else None,
            "rating": r["rating"] or "",
            "target_price": _clean_value(r["target_price"]),
            "eps_forecast_current": _clean_value(r["eps_forecast_current"]),
            "eps_forecast_next": _clean_value(r["eps_forecast_next"]),
            "revenue_forecast": _clean_value(r["revenue_forecast"]),
            "source_file": r["source_file"] or "",
        })
    return out
