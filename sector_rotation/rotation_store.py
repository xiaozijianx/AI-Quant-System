# -*- coding: utf-8 -*-
"""板块轮动数据库存储.

负责:
- 将 rotation_core 计算结果写入 trade_sector_rotation_daily
- 读取历史矩阵供热力图展示
- 读取单板块明细供右侧面板展示
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from .rotation_core import (
    PHASE_CLASS,
    PHASE_DESC,
    execute_query,
    get_connection,
    list_sectors,
)


# 表字段与 DataFrame 列的映射
_FIELD_MAP = {
    "rank": "rank",
    "composite_rank": "composite_rank",
    "score": "score",
    "composite_score": "composite_score",
    "phase": "phase",
    "mom21_z": "MOM_21_z",
    "rs60_z": "RS_60_z",
    "vol_ratio_z": "VOL_RATIO_z",
    "roc_20": "ROC_20",
    "ma20_slope": "MA20_SLOPE",
    "ma20_accel": "MA20_ACCEL",
    "macd_hist": "MACD_HIST",
    "hist_delta": "HIST_DELTA",
    "member_count": "member_count",
}

def find_sectors(keyword: str, level: int = 2, limit: int = 5) -> list:
    """模糊匹配板块名称，返回匹配的板块名称列表。

    匹配优先级：
    1. 精确匹配 (sector_name = keyword)
    2. ILIKE 模糊匹配 (%keyword%)
    3. 从 trade_stock_status 反查所有板块做子串匹配

    Returns:
        [{"sector_name": str, "matched_by": str}, ...]
    """
    # 1. 精确匹配
    rows = execute_query(
        """
        SELECT DISTINCT sector_name
        FROM trade_sector_rotation_daily
        WHERE sector_name = %s AND sector_level = %s
        """,
        (keyword, level),
    )
    if rows:
        return [{"sector_name": r["sector_name"], "matched_by": "exact"} for r in rows]

    # 2. ILIKE 模糊匹配
    rows = execute_query(
        """
        SELECT DISTINCT sector_name
        FROM trade_sector_rotation_daily
        WHERE sector_name ILIKE %s AND sector_level = %s
        LIMIT %s
        """,
        (f"%{keyword}%", level, limit),
    )
    if rows:
        return [{"sector_name": r["sector_name"], "matched_by": "fuzzy"} for r in rows]

    # 3. 从 trade_stock_status 反查全部板块做子串匹配
    all_sectors = list_sectors(level=level)
    matched = []
    for s in all_sectors:
        name = s["sector_name"]
        if keyword in name or name in keyword:
            matched.append({"sector_name": name, "matched_by": "fuzzy"})
            if len(matched) >= limit:
                break
    return matched


def _to_numeric_or_none(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return None
    try:
        return float(v)
    except Exception:
        return None


def save_day(df: pd.DataFrame, trade_date: str, level: int = 2) -> int:
    """将单日板块排名 DataFrame 写入数据库, 幂等写入.

    Args:
        df: rotation_core.rank_industries_with_phase 返回的 DataFrame
        trade_date: 交易日期, 格式 YYYY-MM-DD
        level: 板块级别

    Returns:
        写入行数
    """
    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    try:
        rows = 0
        for sector_name, row in df.iterrows():
            params = {
                "trade_date": trade_date,
                "sector_name": sector_name,
                "sector_level": level,
                "rank": int(row.get("rank", 0)),
                "composite_rank": int(row.get("composite_rank", 0)),
                "score": _to_numeric_or_none(row.get("score")),
                "composite_score": _to_numeric_or_none(row.get("composite_score")),
                "phase": row.get("phase", "neutral"),
                "mom21_z": _to_numeric_or_none(row.get("MOM_21_z")),
                "rs60_z": _to_numeric_or_none(row.get("RS_60_z")),
                "vol_ratio_z": _to_numeric_or_none(row.get("VOL_RATIO_z")),
                "roc_20": _to_numeric_or_none(row.get("ROC_20")),
                "ma20_slope": _to_numeric_or_none(row.get("MA20_SLOPE")),
                "ma20_accel": _to_numeric_or_none(row.get("MA20_ACCEL")),
                "macd_hist": _to_numeric_or_none(row.get("MACD_HIST")),
                "hist_delta": _to_numeric_or_none(row.get("HIST_DELTA")),
                "member_count": int(row.get("member_count", 0)) if pd.notna(row.get("member_count")) else None,
            }
            cursor.execute(
                """
                INSERT INTO trade_sector_rotation_daily
                    (trade_date, sector_name, sector_level, rank, composite_rank,
                     score, composite_score, phase, mom21_z, rs60_z, vol_ratio_z,
                     roc_20, ma20_slope, ma20_accel, macd_hist, hist_delta, member_count, updated_at)
                VALUES
                    (%(trade_date)s, %(sector_name)s, %(sector_level)s, %(rank)s, %(composite_rank)s,
                     %(score)s, %(composite_score)s, %(phase)s, %(mom21_z)s, %(rs60_z)s, %(vol_ratio_z)s,
                     %(roc_20)s, %(ma20_slope)s, %(ma20_accel)s, %(macd_hist)s, %(hist_delta)s, %(member_count)s, NOW())
                ON CONFLICT (trade_date, sector_name, sector_level)
                DO UPDATE SET
                    rank = EXCLUDED.rank,
                    composite_rank = EXCLUDED.composite_rank,
                    score = EXCLUDED.score,
                    composite_score = EXCLUDED.composite_score,
                    phase = EXCLUDED.phase,
                    mom21_z = EXCLUDED.mom21_z,
                    rs60_z = EXCLUDED.rs60_z,
                    vol_ratio_z = EXCLUDED.vol_ratio_z,
                    roc_20 = EXCLUDED.roc_20,
                    ma20_slope = EXCLUDED.ma20_slope,
                    ma20_accel = EXCLUDED.ma20_accel,
                    macd_hist = EXCLUDED.macd_hist,
                    hist_delta = EXCLUDED.hist_delta,
                    member_count = EXCLUDED.member_count,
                    updated_at = NOW()
                """,
                params,
            )
            rows += 1
        conn.commit()
        return rows
    finally:
        cursor.close()
        conn.close()


def get_available_dates(level: int = 2, days: int = 60, end_date: Optional[str] = None) -> List[str]:
    """获取表中已存在的最近 N 个交易日(字符串列表).

    参数:
        level: 板块级别
        days: 返回交易日数量
        end_date: 结束日期(YYYY-MM-DD), 为空则取最新日期
    """
    params = [level]
    conditions = ["sector_level = %s"]
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    where_clause = "WHERE " + " AND ".join(conditions)
    rows = execute_query(
        f"""
        SELECT DISTINCT trade_date
        FROM trade_sector_rotation_daily
        {where_clause}
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        tuple(params + [days]),
    )
    return [str(r["trade_date"]) for r in rows]


def get_latest_date(level: int = 2) -> Optional[str]:
    """获取表中最新日期."""
    dates = get_available_dates(level=level, days=1)
    return dates[0] if dates else None


def load_matrix(days: int = 20, top_n: int = 15, level: int = 2, end_date: Optional[str] = None) -> pd.DataFrame:
    """读取最近 N 个交易日、每日 Top N 板块的排名矩阵.

    参数:
        days: 回溯交易日数
        top_n: 每日取前 N 名
        level: 板块级别
        end_date: 结束日期(YYYY-MM-DD), 为空则取最新日期

    Returns:
        DataFrame, 列: trade_date, rank, sector_name, composite_score, score, phase, ...
    """
    dates = get_available_dates(level=level, days=days, end_date=end_date)
    if not dates:
        return pd.DataFrame()

    rows = execute_query(
        """
        SELECT trade_date, sector_name, rank, composite_rank, score, composite_score, phase,
               mom21_z, rs60_z, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
               macd_hist, hist_delta, member_count
        FROM trade_sector_rotation_daily
        WHERE sector_level = %s AND trade_date IN %s AND composite_rank <= %s
        ORDER BY trade_date DESC, composite_rank ASC
        """,
        (level, tuple(dates), top_n),
    )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    # 按 composite_rank 给出行顺序, 这里 rank 已经是按 score 排的
    return df


def get_detail(sector_name: str, trade_date: str, level: int = 2) -> Optional[dict]:
    """读取某板块某日期的详细指标."""
    rows = execute_query(
        """
        SELECT trade_date, sector_name, rank, composite_rank, score, composite_score, phase,
               mom21_z, rs60_z, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
               macd_hist, hist_delta, member_count
        FROM trade_sector_rotation_daily
        WHERE sector_name = %s AND trade_date = %s AND sector_level = %s
        """,
        (sector_name, trade_date, level),
    )
    if not rows:
        return None
    detail = dict(rows[0])
    phase = detail.get("phase", "neutral")
    detail["phase_desc"] = PHASE_DESC.get(phase, phase)
    detail["phase_class"] = PHASE_CLASS.get(phase, "phase-neutral")
    return detail


def get_sector_history(sector_name: str, level: int = 2, days: int = 60) -> pd.DataFrame:
    """读取某板块最近 N 日的历史排名与指标, 用于右侧趋势图."""
    rows = execute_query(
        """
        SELECT trade_date, rank, composite_rank, score, composite_score, phase,
               mom21_z, rs60_z, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
               macd_hist, hist_delta, member_count
        FROM trade_sector_rotation_daily
        WHERE sector_name = %s AND sector_level = %s
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (sector_name, level, days),
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    return df.sort_values("trade_date")


def get_sector_index(sector_name: str, level: int = 2, years: int = 2) -> pd.DataFrame:
    """读取某板块指数近 N 年的日 K 线, 用于右侧走势图."""
    rows = execute_query(
        """
        SELECT trade_date, close_idx, total_amount, change_pct
        FROM trade_sector_daily
        WHERE sector_name = %s AND sector_level = %s
          AND trade_date >= CURRENT_DATE - INTERVAL '%s years'
        ORDER BY trade_date ASC
        """,
        (sector_name, level, years),
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    for col in ["close_idx", "total_amount", "change_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_top_relevant_stocks(sector_name: str, trade_date: str, level: int = 2, limit: int = 5) -> List[dict]:
    """读取与某板块相关性最高的 N 只股票.

    取 calc_date <= trade_date 的最新可用数据, 按 total_score 降序排列.
    """
    rows = execute_query(
        """
        SELECT stock_code, total_score
        FROM sector_stock_relevance
        WHERE sector_name = %s AND sector_level = %s
          AND calc_date = (
              SELECT MAX(calc_date) FROM sector_stock_relevance
              WHERE sector_name = %s AND sector_level = %s AND calc_date <= %s
          )
        ORDER BY total_score DESC NULLS LAST
        LIMIT %s
        """,
        (sector_name, level, sector_name, level, trade_date, limit),
    )
    return [
        {
            "stock_code": str(r["stock_code"]),
            "total_score": float(r["total_score"]) if r["total_score"] is not None else None,
        }
        for r in rows
    ]


def delete_level(level: int = 2) -> int:
    """删除某级别全部数据, 用于全量重建前清理."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM trade_sector_rotation_daily WHERE sector_level = %s",
            (level,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()
