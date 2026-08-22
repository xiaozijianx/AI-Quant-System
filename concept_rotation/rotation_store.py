# -*- coding: utf-8 -*-
"""概念轮动数据库存储.

负责:
- 将 rotation_core 计算结果写入 trade_concept_rotation_daily
- 读取历史矩阵供热力图展示
- 读取单概念明细供右侧面板展示
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
)


# 表字段与 DataFrame 列的映射
_FIELD_MAP = {
    "rank": "rank",
    "composite_rank": "composite_rank",
    "score": "score",
    "composite_score": "composite_score",
    "phase": "phase",
    "mom10_z": "MOM_10_z",
    "rs20_z": "RS_20_z",
    "vol_ratio_z": "VOL_RATIO_z",
    "roc_20": "ROC_20",
    "ma20_slope": "MA20_SLOPE",
    "ma20_accel": "MA20_ACCEL",
    "macd_hist": "MACD_HIST",
    "hist_delta": "HIST_DELTA",
    "member_count": "member_count",
}

def _to_numeric_or_none(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return None
    try:
        return float(v)
    except Exception:
        return None


def save_day(df: pd.DataFrame, trade_date: str) -> int:
    """将单日概念排名 DataFrame 写入数据库, 幂等写入.

    Args:
        df: rotation_core.rank_concepts_with_phase 返回的 DataFrame
        trade_date: 交易日期, 格式 YYYY-MM-DD

    Returns:
        写入行数
    """
    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    try:
        rows = 0
        for concept_code, row in df.iterrows():
            params = {
                "trade_date":    trade_date,
                "concept_code":  concept_code,
                "concept_name":  row.get("concept_name", concept_code),
                "source_prefix": row.get("source_prefix", ""),
                "rank":          int(row.get("rank", 0)),
                "composite_rank": int(row.get("composite_rank", 0)),
                "score":          _to_numeric_or_none(row.get("score")),
                "composite_score": _to_numeric_or_none(row.get("composite_score")),
                "phase":          row.get("phase", "neutral"),
                "mom10_z":        _to_numeric_or_none(row.get("MOM_10_z")),
                "rs20_z":         _to_numeric_or_none(row.get("RS_20_z")),
                "vol_ratio_z":    _to_numeric_or_none(row.get("VOL_RATIO_z")),
                "roc_20":         _to_numeric_or_none(row.get("ROC_20")),
                "ma20_slope":     _to_numeric_or_none(row.get("MA20_SLOPE")),
                "ma20_accel":     _to_numeric_or_none(row.get("MA20_ACCEL")),
                "macd_hist":      _to_numeric_or_none(row.get("MACD_HIST")),
                "hist_delta":     _to_numeric_or_none(row.get("HIST_DELTA")),
                "member_count":   int(row.get("member_count", 0)) if pd.notna(row.get("member_count")) else None,
            }
            cursor.execute(
                """
                INSERT INTO trade_concept_rotation_daily
                    (trade_date, concept_code, concept_name, source_prefix,
                     rank, composite_rank, score, composite_score, phase,
                     mom10_z, rs20_z, vol_ratio_z, roc_20, ma20_slope,
                     ma20_accel, macd_hist, hist_delta, member_count, updated_at)
                VALUES
                    (%(trade_date)s, %(concept_code)s, %(concept_name)s, %(source_prefix)s,
                     %(rank)s, %(composite_rank)s, %(score)s, %(composite_score)s, %(phase)s,
                     %(mom10_z)s, %(rs20_z)s, %(vol_ratio_z)s, %(roc_20)s, %(ma20_slope)s,
                     %(ma20_accel)s, %(macd_hist)s, %(hist_delta)s, %(member_count)s, NOW())
                ON CONFLICT (trade_date, concept_code)
                DO UPDATE SET
                    concept_name    = EXCLUDED.concept_name,
                    source_prefix   = EXCLUDED.source_prefix,
                    rank            = EXCLUDED.rank,
                    composite_rank  = EXCLUDED.composite_rank,
                    score           = EXCLUDED.score,
                    composite_score = EXCLUDED.composite_score,
                    phase           = EXCLUDED.phase,
                    mom10_z         = EXCLUDED.mom10_z,
                    rs20_z          = EXCLUDED.rs20_z,
                    vol_ratio_z     = EXCLUDED.vol_ratio_z,
                    roc_20          = EXCLUDED.roc_20,
                    ma20_slope      = EXCLUDED.ma20_slope,
                    ma20_accel      = EXCLUDED.ma20_accel,
                    macd_hist       = EXCLUDED.macd_hist,
                    hist_delta      = EXCLUDED.hist_delta,
                    member_count    = EXCLUDED.member_count,
                    updated_at      = NOW()
                """,
                params,
            )
            rows += 1
        conn.commit()
        return rows
    finally:
        cursor.close()
        conn.close()


def get_available_dates(days: int = 60, end_date: Optional[str] = None) -> List[str]:
    """获取表中已存在的最近 N 个交易日(字符串列表).

    参数:
        days: 返回交易日数量
        end_date: 结束日期(YYYY-MM-DD), 为空则取最新日期
    """
    params = []
    conditions = []
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = execute_query(
        f"""
        SELECT DISTINCT trade_date
        FROM trade_concept_rotation_daily
        {where_clause}
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        tuple(params + [days]),
    )
    return [str(r["trade_date"]) for r in rows]


def get_latest_date() -> Optional[str]:
    """获取表中最新日期."""
    dates = get_available_dates(days=1)
    return dates[0] if dates else None


def load_matrix(days: int = 20, top_n: int = 15, end_date: Optional[str] = None) -> pd.DataFrame:
    """读取最近 N 个交易日、每日 Top N 概念的排名矩阵.

    参数:
        days: 回溯交易日数
        top_n: 每日取前 N 名
        end_date: 结束日期(YYYY-MM-DD), 为空则取最新日期

    Returns:
        DataFrame, 列: trade_date, rank, concept_code, concept_name, source_prefix,
                       composite_score, score, phase, ...
    """
    dates = get_available_dates(days=days, end_date=end_date)
    if not dates:
        return pd.DataFrame()

    rows = execute_query(
        """
        SELECT trade_date, concept_code, concept_name, source_prefix,
               rank, composite_rank, score, composite_score, phase,
               mom10_z, rs20_z, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
               macd_hist, hist_delta, member_count
        FROM trade_concept_rotation_daily
        WHERE trade_date IN %s AND composite_rank <= %s
        ORDER BY trade_date DESC, composite_rank ASC
        """,
        (tuple(dates), top_n),
    )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    return df


def get_detail(concept_code: str, trade_date: str) -> Optional[dict]:
    """读取某概念某日期的详细指标."""
    rows = execute_query(
        """
        SELECT trade_date, concept_code, concept_name, source_prefix,
               rank, composite_rank, score, composite_score, phase,
               mom10_z, rs20_z, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
               macd_hist, hist_delta, member_count
        FROM trade_concept_rotation_daily
        WHERE concept_code = %s AND trade_date = %s
        """,
        (concept_code, trade_date),
    )
    if not rows:
        return None
    detail = dict(rows[0])
    phase = detail.get("phase", "neutral")
    detail["phase_desc"] = PHASE_DESC.get(phase, phase)
    detail["phase_class"] = PHASE_CLASS.get(phase, "phase-neutral")
    return detail


def get_concept_history(concept_code: str, days: int = 60) -> pd.DataFrame:
    """读取某概念最近 N 日的历史排名与指标, 用于右侧趋势图."""
    rows = execute_query(
        """
        SELECT trade_date, rank, composite_rank, score, composite_score, phase,
               mom10_z, rs20_z, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
               macd_hist, hist_delta, member_count
        FROM trade_concept_rotation_daily
        WHERE concept_code = %s
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (concept_code, days),
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    return df.sort_values("trade_date")


def get_concept_index(concept_code: str, years: int = 1) -> pd.DataFrame:
    """读取某概念指数近 N 年的日 K 线, 用于右侧走势图."""
    rows = execute_query(
        """
        SELECT trade_date, close_idx, total_amount, change_pct
        FROM concept_daily_full
        WHERE concept_code = %s
          AND trade_date >= CURRENT_DATE - INTERVAL '%s years'
        ORDER BY trade_date ASC
        """,
        (concept_code, years),
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
    for col in ["close_idx", "total_amount", "change_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_top_relevant_stocks(concept_name: str, trade_date: str, limit: int = 5) -> List[dict]:
    """读取与某概念相关性最高的 N 只股票.

    取 calc_date <= trade_date 的最新可用数据, 按 total_score 降序排列.
    """
    rows = execute_query(
        """
        SELECT stock_code, total_score, corr_score, leader_score
        FROM concept_stock_relevance
        WHERE concept_name = %s
          AND calc_date = (
              SELECT MAX(calc_date) FROM concept_stock_relevance
              WHERE concept_name = %s AND calc_date <= %s
          )
        ORDER BY total_score DESC NULLS LAST
        LIMIT %s
        """,
        (concept_name, concept_name, trade_date, limit),
    )
    return [
        {
            "stock_code": str(r["stock_code"]),
            "total_score": float(r["total_score"]) if r["total_score"] is not None else None,
            "corr_score": float(r["corr_score"]) if r["corr_score"] is not None else None,
            "leader_score": float(r["leader_score"]) if r["leader_score"] is not None else None,
        }
        for r in rows
    ]


def delete_all() -> int:
    """删除全部概念轮动数据, 用于全量重建前清理."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM trade_concept_rotation_daily")
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()
