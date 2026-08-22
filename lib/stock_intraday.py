# -*- coding: utf-8 -*-
"""龙头股日内关键数据层。

为龙头复盘选股提供涨停质量字段：
    - 首次/最后涨停时间
    - 炸板次数
    - 板型（一字板/T字板/实体板/烂板/未封板）
    - 换手率、振幅、成交额、OHLC

策略：
    1. 优先从 dragon_stock_intraday 表读取已采集数据。
    2. 缺失时通过 miniQMT xtdata 拉取当日 1 分钟 K 线，提取字段后入库。
    3. 原始分钟线不入库，减少存储压力。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from lib.stock_utils import _get_db_config, normalize_code


# 涨停阈值与主板过滤阈值保持一致
LIMIT_UP_PCT = 9.7


def _connect():
    import psycopg2
    cfg = _get_db_config()
    return psycopg2.connect(**cfg)


def _execute_query(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = _connect()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()


def _execute_update(sql: str, params: tuple = ()) -> int:
    import psycopg2

    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _execute_many(sql: str, params_list: List[tuple]) -> int:
    import psycopg2

    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.executemany(sql, params_list)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _limit_price(yesterday_close: float, limit_pct: float = 10.0) -> float:
    """根据昨日收盘价计算理论涨停价（主板 10%）。"""
    return round(yesterday_close * (1 + limit_pct / 100), 2)


def _classify_limit_up(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    limit_price: float,
    break_count: int,
) -> str:
    """根据 OHLC 和炸板次数判定板型。"""
    tol = 0.01
    reached_limit = high_price >= limit_price - tol
    closed_limit = abs(close_price - limit_price) <= tol

    if not reached_limit:
        return "未封板"
    if not closed_limit:
        return "未封板"

    # 一字板：开盘=收盘=最高=最低=涨停价
    if abs(open_price - limit_price) <= tol and abs(low_price - limit_price) <= tol:
        return "一字板"

    # T字板：开盘=收盘=最高=涨停价，但最低价明显低于涨停价
    if abs(open_price - limit_price) <= tol and abs(high_price - limit_price) <= tol and low_price < limit_price - tol:
        return "T字板"

    # 烂板：炸板次数较多或振幅很大
    if break_count >= 2:
        return "烂板"

    return "实体板"


def _analyze_minute_data(
    minute_df,
    yesterday_close: float,
    limit_pct: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """从 1 分钟 DataFrame 提取涨停关键字段。

    minute_df 列需包含：time, open, high, low, close, volume, amount
    """
    if minute_df is None or minute_df.empty:
        return None

    limit_price = _limit_price(yesterday_close, limit_pct)
    tol = 0.01

    first_limit_time: Optional[time] = None
    last_limit_time: Optional[time] = None
    break_count = 0
    in_limit = False

    for _, row in minute_df.iterrows():
        t = row["time"] if "time" in row else row.name
        high = float(row.get("high", 0) or 0)
        close = float(row.get("close", 0) or 0)

        # 判断该分钟是否触及涨停
        reached = high >= limit_price - tol
        if reached and first_limit_time is None:
            first_limit_time = _to_time(t)

        # 判断该分钟收盘是否封住涨停
        closed_limit = abs(close - limit_price) <= tol
        if closed_limit:
            last_limit_time = _to_time(t)

        # 炸板次数：从封板状态变为未封板状态
        if in_limit and not closed_limit:
            break_count += 1
        in_limit = closed_limit

    open_price = float(minute_df.iloc[0]["open"])
    high_price = float(minute_df["high"].max())
    low_price = float(minute_df["low"].min())
    close_price = float(minute_df.iloc[-1]["close"])
    volume = int(minute_df["volume"].sum())
    amount = float(minute_df["amount"].sum()) if "amount" in minute_df.columns else None
    amplitude = (high_price - low_price) / yesterday_close * 100 if yesterday_close else 0.0

    limit_up_type = _classify_limit_up(open_price, high_price, low_price, close_price, limit_price, break_count)

    return {
        "is_limit_up": close_price >= limit_price - tol,
        "limit_up_type": limit_up_type,
        "first_limit_time": first_limit_time,
        "last_limit_time": last_limit_time,
        "break_count": break_count,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "volume": volume,
        "amount": amount,
        "amplitude": amplitude,
    }


def _to_time(t) -> Optional[time]:
    """把分钟线时间索引转成 time 对象。"""
    if t is None:
        return None
    # pandas NaT 会被 isinstance(t, datetime) 误判，需先排除
    try:
        if pd.isna(t):
            return None
    except Exception:
        pass
    if isinstance(t, time):
        return t
    if isinstance(t, datetime):
        return t.time()
    if isinstance(t, str):
        # 支持 "0930" 或 "09:30"
        s = t.replace(":", "")
        if len(s) == 4:
            return time(int(s[:2]), int(s[2:]))
        if len(s) == 6:
            return time(int(s[:2]), int(s[2:4]), int(s[4:]))
    return None


def _fetch_from_xtdata(stock_code: str, trade_date: str) -> Optional[Dict[str, Any]]:
    """通过 miniQMT 拉取单日分钟数据并提取涨停字段。"""
    try:
        from xtquant import xtdata
    except ImportError:
        return None

    try:
        xtdata.connect()
    except Exception:
        pass

    sd = trade_date.replace("-", "")
    ed = sd
    try:
        xtdata.download_history_data(stock_code, period="1m", start_time=sd, end_time=ed)
    except Exception:
        pass

    md = xtdata.get_market_data(
        field_list=["open", "high", "low", "close", "volume", "amount"],
        stock_list=[stock_code],
        period="1m",
        start_time=sd,
        end_time=ed,
        dividend_type="front",
        fill_data=True,
    )
    if not md or "close" not in md or stock_code not in md["close"].index:
        return None

    # 组装 DataFrame
    minute_df = pd.DataFrame({
        "open": md["open"].loc[stock_code],
        "high": md["high"].loc[stock_code],
        "low": md["low"].loc[stock_code],
        "close": md["close"].loc[stock_code],
        "volume": md["volume"].loc[stock_code],
    })
    if "amount" in md:
        minute_df["amount"] = md["amount"].loc[stock_code]
    minute_df.index = pd.to_datetime(minute_df.index, format="%Y%m%d%H%M%S", errors="coerce")
    # 把时间解析失败的 NaT 索引行也清掉
    minute_df = minute_df[minute_df.index.notna()]
    minute_df = minute_df.dropna(subset=["close"])
    if minute_df.empty:
        return None

    # 取昨日收盘价用于计算涨停价
    prev_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_rows = _execute_query(
        "SELECT close_price FROM trade_stock_daily WHERE stock_code = %s AND trade_date <= %s ORDER BY trade_date DESC LIMIT 1",
        (stock_code, prev_date),
    )
    yesterday_close = float(prev_rows[0]["close_price"]) if prev_rows else float(minute_df.iloc[0]["open"])

    return _analyze_minute_data(minute_df, yesterday_close)


def load_intraday_summaries(
    stock_codes: List[str],
    trade_date: str,
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """批量获取股票日内关键数据，优先读库，缺失时通过 QMT 补采。

    Args:
        stock_codes: 股票代码列表（需已标准化为带后缀格式）
        trade_date:  交易日期 YYYY-MM-DD
        force_refresh: 是否强制重新下载

    Returns:
        {stock_code: summary_dict, ...}
    """
    if not stock_codes:
        return {}

    normalized = [normalize_code(c) for c in stock_codes]
    normalized = [c for c in normalized if c]
    if not normalized:
        return {}

    # 1. 先读库
    existing: Dict[str, Dict[str, Any]] = {}
    if not force_refresh:
        rows = _execute_query(
            """
            SELECT stock_code, is_limit_up, limit_up_type, first_limit_time,
                   last_limit_time, break_count, close_order_amount, close_order_volume,
                   turnover_rate, amount, amplitude, open_price, high_price, low_price,
                   close_price, change_pct
            FROM dragon_stock_intraday
            WHERE trade_date = %s AND stock_code IN %s
            """,
            (trade_date, tuple(normalized)),
        )
        for r in rows:
            existing[r["stock_code"]] = dict(r)

    # 2. 缺失的补采
    missing = [c for c in normalized if c not in existing]
    fetched: Dict[str, Dict[str, Any]] = {}
    for code in missing:
        summary = _fetch_from_xtdata(code, trade_date)
        if summary:
            # 补充日 K 中已有的字段（trade_stock_daily 无 change_pct，需从 dragon_limit_up_daily 取）
            daily_rows = _execute_query(
                """
                SELECT turnover_rate, amount
                FROM trade_stock_daily
                WHERE stock_code = %s AND trade_date = %s
                """,
                (code, trade_date),
            )
            if daily_rows:
                dr = daily_rows[0]
                if summary.get("turnover_rate") is None and dr.get("turnover_rate") is not None:
                    summary["turnover_rate"] = float(dr["turnover_rate"])
                if summary.get("amount") is None and dr.get("amount") is not None:
                    summary["amount"] = float(dr["amount"])
            if summary.get("change_pct") is None:
                lu_rows = _execute_query(
                    """
                    SELECT change_pct
                    FROM dragon_limit_up_daily
                    WHERE stock_code = %s AND trade_date = %s
                    """,
                    (code, trade_date),
                )
                if lu_rows and lu_rows[0].get("change_pct") is not None:
                    summary["change_pct"] = float(lu_rows[0]["change_pct"])
            fetched[code] = summary

    # 3. 入库
    if fetched:
        insert_sql = """
            INSERT INTO dragon_stock_intraday (
                stock_code, trade_date, is_limit_up, limit_up_type, first_limit_time,
                last_limit_time, break_count, close_order_amount, close_order_volume,
                turnover_rate, amount, amplitude, open_price, high_price, low_price,
                close_price, change_pct
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                is_limit_up = EXCLUDED.is_limit_up,
                limit_up_type = EXCLUDED.limit_up_type,
                first_limit_time = EXCLUDED.first_limit_time,
                last_limit_time = EXCLUDED.last_limit_time,
                break_count = EXCLUDED.break_count,
                close_order_amount = EXCLUDED.close_order_amount,
                close_order_volume = EXCLUDED.close_order_volume,
                turnover_rate = EXCLUDED.turnover_rate,
                amount = EXCLUDED.amount,
                amplitude = EXCLUDED.amplitude,
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                change_pct = EXCLUDED.change_pct
        """
        params_list = []
        for code, s in fetched.items():
            params_list.append((
                code,
                trade_date,
                s.get("is_limit_up"),
                s.get("limit_up_type"),
                s.get("first_limit_time"),
                s.get("last_limit_time"),
                s.get("break_count", 0),
                s.get("close_order_amount"),
                s.get("close_order_volume"),
                s.get("turnover_rate"),
                s.get("amount"),
                s.get("amplitude"),
                s.get("open_price"),
                s.get("high_price"),
                s.get("low_price"),
                s.get("close_price"),
                s.get("change_pct"),
            ))
        _execute_many(insert_sql, params_list)

    existing.update(fetched)
    return existing
