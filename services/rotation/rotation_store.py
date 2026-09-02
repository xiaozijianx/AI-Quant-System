# -*- coding: utf-8 -*-
"""轮动数据库存储 (板块/概念共用, 按 RotationDimension 参数化).

合并自 sector_rotation/rotation_store.py 与 concept_rotation/rotation_store.py。
差异经 dim 配置注入: 结果表/维度列/冲突键/指标列名; find_sectors 为 sector 特有,
按维度保留分支。
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from .dimension import RotationDimension, SECTOR, CONCEPT
from .rotation_core import (
    PHASE_CLASS,
    PHASE_DESC,
    execute_query,
    get_connection,
    list_items,
)


def _to_numeric_or_none(v):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return None
    try:
        return float(v)
    except Exception:
        return None


# ============================================================
# sector 特有: 模糊匹配板块名称
# ============================================================

def find_sectors(keyword: str, level: int = 2, limit: int = 5) -> list:
    """模糊匹配板块名称, 返回匹配的板块名称列表 (sector 特有, 原样保留).

    匹配优先级:
    1. 精确匹配 (sector_name = keyword)
    2. ILIKE 模糊匹配 (%keyword%)
    3. 从 trade_stock_status 反查所有板块做子串匹配
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
    all_sectors = list_items(SECTOR, level=level)
    matched = []
    for s in all_sectors:
        name = s["sector_name"]
        if keyword in name or name in keyword:
            matched.append({"sector_name": name, "matched_by": "fuzzy"})
            if len(matched) >= limit:
                break
    return matched


# ============================================================
# 按维度的存储类 (实例隔离, 互不共享表结构)
# ============================================================

class RotationStore:
    """单个维度的轮动结果存取 (表名/列名/冲突键经 dim 注入)."""

    def __init__(self, dim: RotationDimension):
        self.dim = dim
        # 指标列映射 (DB 列 -> DataFrame 列)
        self.mom_z = dim.mom_z_col
        self.rs_z = dim.rs_z_col
        self._metric_cols = [self.mom_z, self.rs_z, "vol_ratio_z"]

    # ---- SQL 片段 ----

    def _select_columns(self) -> str:
        """结果表的查询列清单."""
        if self.dim.key == "sector":
            return ("trade_date, sector_name, rank, composite_rank, score, composite_score, phase,\n"
                    f"       {self.mom_z}, {self.rs_z}, vol_ratio_z, roc_20, ma20_slope, ma20_accel,\n"
                    "        macd_hist, hist_delta, member_count")
        return ("trade_date, concept_code, concept_name, source_prefix,\n"
                "               rank, composite_rank, score, composite_score, phase,\n"
                f"               {self.mom_z}, {self.rs_z}, vol_ratio_z, roc_20, ma20_slope, ma20_accel,\n"
                "               macd_hist, hist_delta, member_count")

    def _level_condition(self, level: int = 2) -> tuple:
        """sector 维度的 level 过滤条件 (concept 无)."""
        if self.dim.has_level:
            return ("sector_level = %s", [level])
        return ("", [])

    # ---- 写入 ----

    def save_day(self, df: pd.DataFrame, trade_date: str, level: int = 2) -> int:
        """将单日排名 DataFrame 写入数据库, 幂等写入."""
        if df.empty:
            return 0

        conn = get_connection()
        cursor = conn.cursor()
        try:
            rows = 0
            for key, row in df.iterrows():
                if self.dim.key == "sector":
                    params = self._sector_params(key, row, trade_date, level)
                else:
                    params = self._concept_params(key, row, trade_date)
                cursor.execute(self._upsert_sql(), params)
                rows += 1
            conn.commit()
            return rows
        finally:
            cursor.close()
            conn.close()

    def _sector_params(self, sector_name, row, trade_date, level) -> dict:
        return {
            "trade_date": trade_date,
            "sector_name": sector_name,
            "sector_level": level,
            "rank": int(row.get("rank", 0)),
            "composite_rank": int(row.get("composite_rank", 0)),
            "score": _to_numeric_or_none(row.get("score")),
            "composite_score": _to_numeric_or_none(row.get("composite_score")),
            "phase": row.get("phase", "neutral"),
            self.mom_z: _to_numeric_or_none(row.get(f"MOM_{self.dim.mom_window}_z")),
            self.rs_z: _to_numeric_or_none(row.get(f"RS_{self.dim.rs_window}_z")),
            "vol_ratio_z": _to_numeric_or_none(row.get("VOL_RATIO_z")),
            "roc_20": _to_numeric_or_none(row.get("ROC_20")),
            "ma20_slope": _to_numeric_or_none(row.get("MA20_SLOPE")),
            "ma20_accel": _to_numeric_or_none(row.get("MA20_ACCEL")),
            "macd_hist": _to_numeric_or_none(row.get("MACD_HIST")),
            "hist_delta": _to_numeric_or_none(row.get("HIST_DELTA")),
            "member_count": int(row.get("member_count", 0)) if pd.notna(row.get("member_count")) else None,
        }

    def _concept_params(self, concept_code, row, trade_date) -> dict:
        return {
            "trade_date":    trade_date,
            "concept_code":  concept_code,
            "concept_name":  row.get("concept_name", concept_code),
            "source_prefix": row.get("source_prefix", ""),
            "rank":          int(row.get("rank", 0)),
            "composite_rank": int(row.get("composite_rank", 0)),
            "score":          _to_numeric_or_none(row.get("score")),
            "composite_score": _to_numeric_or_none(row.get("composite_score")),
            "phase":          row.get("phase", "neutral"),
            self.mom_z:       _to_numeric_or_none(row.get(f"MOM_{self.dim.mom_window}_z")),
            self.rs_z:        _to_numeric_or_none(row.get(f"RS_{self.dim.rs_window}_z")),
            "vol_ratio_z":    _to_numeric_or_none(row.get("VOL_RATIO_z")),
            "roc_20":         _to_numeric_or_none(row.get("ROC_20")),
            "ma20_slope":     _to_numeric_or_none(row.get("MA20_SLOPE")),
            "ma20_accel":     _to_numeric_or_none(row.get("MA20_ACCEL")),
            "macd_hist":      _to_numeric_or_none(row.get("MACD_HIST")),
            "hist_delta":     _to_numeric_or_none(row.get("HIST_DELTA")),
            "member_count":   int(row.get("member_count", 0)) if pd.notna(row.get("member_count")) else None,
        }

    def _upsert_sql(self) -> str:
        if self.dim.key == "sector":
            return """
                INSERT INTO trade_sector_rotation_daily
                    (trade_date, sector_name, sector_level, rank, composite_rank,
                     score, composite_score, phase, mom_z, rs_z, vol_ratio_z,
                     roc_20, ma20_slope, ma20_accel, macd_hist, hist_delta, member_count, updated_at)
                VALUES
                    (%(trade_date)s, %(sector_name)s, %(sector_level)s, %(rank)s, %(composite_rank)s,
                     %(score)s, %(composite_score)s, %(phase)s, %(mom_z)s, %(rs_z)s, %(vol_ratio_z)s,
                     %(roc_20)s, %(ma20_slope)s, %(ma20_accel)s, %(macd_hist)s, %(hist_delta)s, %(member_count)s, NOW())
                ON CONFLICT (trade_date, sector_name, sector_level)
                DO UPDATE SET
                    rank = EXCLUDED.rank,
                    composite_rank = EXCLUDED.composite_rank,
                    score = EXCLUDED.score,
                    composite_score = EXCLUDED.composite_score,
                    phase = EXCLUDED.phase,
                    mom_z = EXCLUDED.mom_z,
                    rs_z = EXCLUDED.rs_z,
                    vol_ratio_z = EXCLUDED.vol_ratio_z,
                    roc_20 = EXCLUDED.roc_20,
                    ma20_slope = EXCLUDED.ma20_slope,
                    ma20_accel = EXCLUDED.ma20_accel,
                    macd_hist = EXCLUDED.macd_hist,
                    hist_delta = EXCLUDED.hist_delta,
                    member_count = EXCLUDED.member_count,
                    updated_at = NOW()
            """.replace("mom_z", self.mom_z).replace("rs_z", self.rs_z)

        return """
            INSERT INTO trade_concept_rotation_daily
                (trade_date, concept_code, concept_name, source_prefix,
                 rank, composite_rank, score, composite_score, phase,
                 mom_z, rs_z, vol_ratio_z, roc_20, ma20_slope,
                 ma20_accel, macd_hist, hist_delta, member_count, updated_at)
            VALUES
                (%(trade_date)s, %(concept_code)s, %(concept_name)s, %(source_prefix)s,
                 %(rank)s, %(composite_rank)s, %(score)s, %(composite_score)s, %(phase)s,
                 %(mom_z)s, %(rs_z)s, %(vol_ratio_z)s, %(roc_20)s, %(ma20_slope)s,
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
                mom_z           = EXCLUDED.mom_z,
                rs_z            = EXCLUDED.rs_z,
                vol_ratio_z     = EXCLUDED.vol_ratio_z,
                roc_20          = EXCLUDED.roc_20,
                ma20_slope      = EXCLUDED.ma20_slope,
                ma20_accel      = EXCLUDED.ma20_accel,
                macd_hist       = EXCLUDED.macd_hist,
                hist_delta      = EXCLUDED.hist_delta,
                member_count    = EXCLUDED.member_count,
                updated_at      = NOW()
        """.replace("mom_z", self.mom_z).replace("rs_z", self.rs_z)

    # ---- 读取 ----

    def get_available_dates(self, days: int = 60,
                            end_date: Optional[str] = None,
                            level: int = 2) -> List[str]:
        """获取表中已存在的最近 N 个交易日(字符串列表)."""
        cond, params = self._level_condition(level)
        conditions = [c for c in ([cond] if cond else [])]
        if end_date:
            conditions.append("trade_date <= %s")
            params = params + [end_date]

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = execute_query(
            f"""
            SELECT DISTINCT trade_date
            FROM {self.dim.result_table}
            {where_clause}
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            tuple(params + [days]),
        )
        return [str(r["trade_date"]) for r in rows]

    def get_latest_date(self, level: int = 2) -> Optional[str]:
        """获取表中最新日期."""
        dates = self.get_available_dates(days=1, level=level)
        return dates[0] if dates else None

    def load_matrix(self, days: int = 20, top_n: int = 15,
                    level: int = 2, end_date: Optional[str] = None) -> pd.DataFrame:
        """读取最近 N 个交易日、每日 Top N 的排名矩阵."""
        dates = self.get_available_dates(days=days, end_date=end_date, level=level)
        if not dates:
            return pd.DataFrame()

        cond, params = self._level_condition(level)
        where_extra = f"AND {cond}" if cond else ""
        # 参数顺序与 SQL 占位符顺序一致: trade_date IN %s -> [cond] -> top_n
        rows = execute_query(
            f"""
            SELECT {self._select_columns()}
            FROM {self.dim.result_table}
            WHERE trade_date IN %s {where_extra} AND composite_rank <= %s
            ORDER BY trade_date DESC, composite_rank ASC
            """,
            tuple([tuple(dates)] + params + [top_n]),
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        return df

    def get_detail(self, key: str, trade_date: str, level: int = 2) -> Optional[dict]:
        """读取某条目某日期的详细指标."""
        if self.dim.key == "sector":
            rows = execute_query(
                f"""
                SELECT {self._select_columns()}
                FROM {self.dim.result_table}
                WHERE sector_name = %s AND trade_date = %s AND sector_level = %s
                """,
                (key, trade_date, level),
            )
        else:
            rows = execute_query(
                f"""
                SELECT {self._select_columns()}
                FROM {self.dim.result_table}
                WHERE concept_code = %s AND trade_date = %s
                """,
                (key, trade_date),
            )
        if not rows:
            return None
        detail = dict(rows[0])
        phase = detail.get("phase", "neutral")
        detail["phase_desc"] = PHASE_DESC.get(phase, phase)
        detail["phase_class"] = PHASE_CLASS.get(phase, "phase-neutral")
        return detail

    def get_history(self, key: str, days: int = 60, level: int = 2) -> pd.DataFrame:
        """读取某条目最近 N 日的历史排名与指标."""
        cond, params = self._level_condition(level)
        where_extra = f"AND {cond}" if cond else ""
        key_col = "sector_name" if self.dim.key == "sector" else "concept_code"
        rows = execute_query(
            f"""
            SELECT trade_date, rank, composite_rank, score, composite_score, phase,
                   {self.mom_z}, {self.rs_z}, vol_ratio_z, roc_20, ma20_slope, ma20_accel,
                   macd_hist, hist_delta, member_count
            FROM {self.dim.result_table}
            WHERE {key_col} = %s {where_extra}
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            tuple([key] + params + [days]),
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        return df.sort_values("trade_date")

    def get_item_index(self, key: str, level: int = 2, years: Optional[int] = None) -> pd.DataFrame:
        """读取某条目指数近 N 年的日 K 线."""
        if years is None:
            years = self.dim.index_years_default
        if self.dim.key == "sector":
            rows = execute_query(
                """
                SELECT trade_date, close_idx, total_amount, change_pct
                FROM trade_sector_daily
                WHERE sector_name = %s AND sector_level = %s
                  AND trade_date >= CURRENT_DATE - INTERVAL '%s years'
                ORDER BY trade_date ASC
                """,
                (key, level, years),
            )
        else:
            rows = execute_query(
                """
                SELECT trade_date, close_idx, total_amount, change_pct
                FROM concept_daily_full
                WHERE concept_code = %s
                  AND trade_date >= CURRENT_DATE - INTERVAL '%s years'
                ORDER BY trade_date ASC
                """,
                (key, years),
            )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        for col in ["close_idx", "total_amount", "change_pct"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def get_top_relevant_stocks(self, key: str, trade_date: str,
                                level: int = 2, limit: int = 5) -> List[dict]:
        """读取与某条目相关性最高的 N 只股票."""
        if self.dim.key == "sector":
            # sector: 按 sector_name + level 查, 返回 total_score
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
                (key, level, key, level, trade_date, limit),
            )
            return [
                {
                    "stock_code": str(r["stock_code"]),
                    "total_score": float(r["total_score"]) if r["total_score"] is not None else None,
                }
                for r in rows
            ]

        # concept: 按 concept_name 查(注意: 传入的是 name 非 code), 多返回 corr/leader 两列
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
            (key, key, trade_date, limit),
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

    def delete_all(self, level: int = 2) -> int:
        """删除数据, 用于全量重建前清理 (sector 按级别删, concept 全删)."""
        conn = get_connection()
        cursor = conn.cursor()
        try:
            if self.dim.key == "sector":
                cursor.execute(
                    "DELETE FROM trade_sector_rotation_daily WHERE sector_level = %s",
                    (level,),
                )
            else:
                cursor.execute("DELETE FROM trade_concept_rotation_daily")
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()
            conn.close()


# 维度实例 (路由/worker/兼容层共用)
SECTOR_STORE = RotationStore(SECTOR)
CONCEPT_STORE = RotationStore(CONCEPT)
