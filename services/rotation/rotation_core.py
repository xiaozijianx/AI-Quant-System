# -*- coding: utf-8 -*-
"""轮动核心计算 (板块/概念共用, 按 RotationDimension 参数化).

合并自 sector_rotation/rotation_core.py 与 concept_rotation/rotation_core.py,
两侧逐行一致的函数原样保留; 差异点经 dimension 配置注入, 口径零变化:
- 数据加载层按维度分支 (表结构不同, 见 _load_* 函数族)
- calc_strength_indicators 的窗口/最小长度/索引对齐开关
- detect_phase 的 roc_threshold (两维度量纲不同, 原样保留)
- score 合成: 等权 mean (sector) vs 加权和 (concept)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

from .dimension import RotationDimension, SECTOR, CONCEPT


# ============================================================
# 数据库连接(最小化, 独立配置) -- 两侧原样一致
# ============================================================

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


def _load_env() -> dict:
    """读取项目根目录 .env, 返回键值对."""
    env = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # 环境变量优先级高于 .env
    for k in ["WUCAI_SQL_HOST", "WUCAI_SQL_PORT", "WUCAI_SQL_USERNAME",
              "WUCAI_SQL_PASSWORD", "WUCAI_SQL_DB"]:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


_env = _load_env()
_DB_CONFIG = {
    "host":     _env.get("WUCAI_SQL_HOST", "localhost"),
    "user":     _env.get("WUCAI_SQL_USERNAME", "postgres"),
    "password": _env.get("WUCAI_SQL_PASSWORD", ""),
    "database": _env.get("WUCAI_SQL_DB", "AI-Quant"),
    "port":     int(_env.get("WUCAI_SQL_PORT", "5432")),
    "client_encoding": "UTF8",
}


def get_connection():
    return psycopg2.connect(**_DB_CONFIG)


def execute_query(sql, params=None):
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()


# ============================================================
# 数据加载 (维度分支: 表结构不同)
# ============================================================

def list_items(dim: RotationDimension, level: int = 2) -> List[Dict]:
    """列出全部维度条目 (板块: trade_stock_status 反查; 概念: concept_meta)."""
    if dim.key == "sector":
        field = "sector_1" if level == 1 else "sector_2"
        sql = f"""
            SELECT {field} AS sector_name, COUNT(*) AS member_count
            FROM trade_stock_status
            WHERE {field} IS NOT NULL
            GROUP BY {field}
            ORDER BY {field}
        """
        return execute_query(sql)

    # concept: concept_meta LEFT JOIN concept_stock_tag 最新交易日计数
    sql = """
        SELECT cm.concept_code, cm.concept_name, cm.source_prefix,
               COALESCE(cst.cnt, 0) AS member_count
        FROM concept_meta cm
        LEFT JOIN (
            SELECT concept_code, COUNT(*) AS cnt
            FROM concept_stock_tag
            WHERE trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
            GROUP BY concept_code
        ) cst ON cst.concept_code = cm.concept_code
        WHERE cm.is_active = TRUE AND cm.is_curated = TRUE
        ORDER BY cm.concept_code
    """
    return execute_query(sql)


def get_member_codes(dim: RotationDimension, key: str, level: int = 2) -> List[str]:
    """取条目当前成分股代码列表."""
    if dim.key == "sector":
        field = "sector_1" if level == 1 else "sector_2"
        rows = execute_query(
            f"SELECT stock_code FROM trade_stock_status WHERE {field} = %s ORDER BY stock_code",
            (key,))
        return [r["stock_code"] for r in rows]

    rows = execute_query(
        """
        SELECT stock_code FROM concept_stock_tag
        WHERE concept_code = %s
          AND trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag WHERE concept_code = %s)
        ORDER BY stock_code
        """,
        (key, key))
    return [r["stock_code"] for r in rows]


def load_item_index(dim: RotationDimension, key: str,
                    level: int = 2, end_date: Optional[str] = None) -> pd.DataFrame:
    """加载单条目合成指数 K 线."""
    if dim.key == "sector":
        conditions = ["sector_name = %s", "sector_level = %s"]
        params: list = [key, level]
        if end_date:
            conditions.append("trade_date <= %s")
            params.append(end_date)
        sql = f"""
            SELECT trade_date, open_idx, high_idx, low_idx, close_idx,
                   total_volume, total_amount, change_pct, stock_count
            FROM trade_sector_daily
            WHERE {' AND '.join(conditions)}
            ORDER BY trade_date ASC
        """
        rows = execute_query(sql, params)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.set_index("trade_date", inplace=True)
        df.rename(columns={
            "open_idx": "open", "high_idx": "high",
            "low_idx": "low",   "close_idx": "close",
            "total_volume": "volume", "total_amount": "amount",
        }, inplace=True)
        for col in ["open", "high", "low", "close", "amount", "change_pct"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # concept: concept_daily_full, 额外取 concept_name, stock_count -> member_count
    conditions = ["concept_code = %s"]
    params: list = [key]
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)
    sql = f"""
        SELECT trade_date, concept_name, open_idx, high_idx, low_idx, close_idx,
               total_volume, total_amount, change_pct, stock_count
        FROM concept_daily_full
        WHERE {' AND '.join(conditions)}
        ORDER BY trade_date ASC
    """
    rows = execute_query(sql, params)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.set_index("trade_date", inplace=True)
    df.rename(columns={
        "open_idx": "open", "high_idx": "high",
        "low_idx": "low",   "close_idx": "close",
        "total_volume": "volume", "total_amount": "amount",
        "stock_count": "member_count",
    }, inplace=True)
    for col in ["open", "high", "low", "close", "amount", "change_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_all_items(dim: RotationDimension, level: int = 2,
                   end_date: Optional[str] = None,
                   min_days: Optional[int] = None) -> Dict[str, pd.DataFrame]:
    """批量加载全部满足长度要求的条目指数."""
    if min_days is None:
        min_days = dim.min_days

    if dim.key == "sector":
        conditions = ["sector_level = %s"]
        params: list = [level]
        if end_date:
            conditions.append("trade_date <= %s")
            params.append(end_date)
        sql = f"""
            SELECT sector_name, trade_date, open_idx, high_idx, low_idx, close_idx,
                   total_volume, total_amount, change_pct, stock_count
            FROM trade_sector_daily
            WHERE {' AND '.join(conditions)}
            ORDER BY sector_name, trade_date ASC
        """
        group_col = "sector_name"
        extra_cols = []
    else:
        conditions = []
        params: list = []
        if end_date:
            conditions.append("trade_date <= %s")
            params.append(end_date)
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT concept_code, concept_name, trade_date, open_idx, high_idx, low_idx, close_idx,
                   total_volume, total_amount, change_pct, stock_count
            FROM concept_daily_full
            {where_clause}
            ORDER BY concept_code, trade_date ASC
        """
        group_col = "concept_code"
        extra_cols = ["concept_name"]

    rows = execute_query(sql, params)
    if not rows:
        return {}

    df_all = pd.DataFrame(rows)
    df_all["trade_date"] = pd.to_datetime(df_all["trade_date"])
    numeric_cols = ["open_idx", "high_idx", "low_idx", "close_idx",
                    "total_volume", "total_amount", "change_pct", "stock_count"]
    for col in numeric_cols:
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce")

    result = {}
    for name, group in df_all.groupby(group_col):
        if len(group) < min_days:
            continue
        df = group.set_index("trade_date").rename(columns={
            "open_idx": "open", "high_idx": "high",
            "low_idx": "low", "close_idx": "close",
            "total_volume": "volume", "total_amount": "amount",
            "stock_count": "member_count",
        }).sort_index()
        # concept: 保留 concept_name 列 (原实现行为)
        if extra_cols:
            for c in extra_cols:
                if c in group.columns:
                    df[c] = group[c].values
        result[name] = df

    return result


# ============================================================
# 强度指标与基准 (按 dim 参数化, 口径零变化)
# ============================================================

def build_market_benchmark(panel: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """全部条目等权合成市场基准 (两侧原样一致)."""
    if not panel:
        return pd.DataFrame()
    close_dict = {}
    amount_dict = {}
    for name, df in panel.items():
        if df["close"].iloc[0] > 0:
            close_dict[name] = df["close"] / df["close"].iloc[0]
        amount_dict[name] = df["amount"]
    closes = pd.DataFrame(close_dict)
    amounts = pd.DataFrame(amount_dict)
    return pd.DataFrame({
        "close": closes.mean(axis=1) * 1000,
        "amount": amounts.sum(axis=1),
    })


def calc_strength_indicators(dim: RotationDimension,
                             item_kline: pd.DataFrame,
                             market_kline: pd.DataFrame) -> Dict[str, float]:
    """计算强度三因子: MOM / RS / VOL_RATIO (窗口与键名按 dim).

    - sector: MOM_21 / RS_60 / VOL_RATIO(5/60), 不做索引对齐
    - concept: MOM_10 / RS_20 / VOL_RATIO(5/20), 做 index.intersection 对齐
    """
    if dim.align_index:
        # concept 原实现: 日期索引对齐后再计算
        common = item_kline.index.intersection(market_kline.index)
        if len(common) < dim.min_strength_len:
            return {}
        ind = item_kline.loc[common]
        bench = market_kline.loc[common]
    else:
        # sector 原实现: 直接按长度判断
        if len(item_kline) < dim.min_strength_len or len(market_kline) < dim.min_strength_len:
            return {}
        ind = item_kline
        bench = market_kline

    close = ind["close"]
    amount = ind["amount"]

    mom_w = dim.mom_window
    mom = float(close.iloc[-1] / close.iloc[-(mom_w + 1)] - 1) if len(close) >= mom_w + 1 else np.nan

    rs_w = dim.rs_window
    s_ret = close.pct_change(rs_w).iloc[-1]
    m_ret = bench["close"].pct_change(rs_w).iloc[-1]
    rs = float(s_ret - m_ret) if pd.notna(s_ret) and pd.notna(m_ret) else np.nan

    avg_amt_short = amount.tail(dim.vol_short).mean()
    avg_amt_long = amount.tail(dim.vol_long).mean()
    vol_ratio = float(avg_amt_short / avg_amt_long) if avg_amt_long > 0 else np.nan

    return {f"MOM_{mom_w}": mom, f"RS_{rs_w}": rs, "VOL_RATIO": vol_ratio}


# ============================================================
# 导数指标与 phase 判定 (公共, roc_threshold 按 dim)
# ============================================================

def _zscore(s: pd.Series) -> pd.Series:
    mu = s.mean()
    sd = s.std()
    if sd == 0 or pd.isna(sd):
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _ma_slope(close: pd.Series, ma_window: int = 20, slope_window: int = 10) -> pd.Series:
    """对 MA(close, ma_window) 做最小二乘线性回归, 斜率年化为 % / 年."""
    ma = close.rolling(ma_window).mean()

    def _fit(window: np.ndarray) -> float:
        if np.isnan(window).any():
            return np.nan
        y = window
        x = np.arange(len(y), dtype=float)
        x_mean = x.mean()
        y_mean = y.mean()
        denom = ((x - x_mean) ** 2).sum()
        if denom == 0:
            return np.nan
        slope = ((x - x_mean) * (y - y_mean)).sum() / denom
        if y_mean == 0:
            return np.nan
        return slope * 252.0 / abs(y_mean) * 100

    return ma.rolling(slope_window).apply(_fit, raw=True)


def calc_all_derivatives(dim: RotationDimension, close: pd.Series) -> Dict[str, float]:
    """计算一阶导/二阶导指标 (最小长度按 dim: sector 60 / concept 35)."""
    if len(close) < dim.min_deriv_len:
        return {}

    roc_20 = float(close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else np.nan

    slope_series = _ma_slope(close, 20, 10)
    ma20_slope = float(slope_series.iloc[-1]) if len(slope_series) > 0 else np.nan
    ma20_accel = float(slope_series.iloc[-1] - slope_series.iloc[-6]) if len(slope_series) >= 6 else np.nan

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    macd_hist = float((dif.iloc[-1] - dea.iloc[-1]) * 2)
    hist_prev = float((dif.iloc[-2] - dea.iloc[-2]) * 2) if len(dif) >= 2 else macd_hist
    hist_delta = macd_hist - hist_prev

    return {
        "ROC_20":     roc_20,
        "MA20_SLOPE": ma20_slope,
        "MACD_HIST":  macd_hist,
        "HIST_DELTA": hist_delta,
        "MA20_ACCEL": ma20_accel,
    }


PHASE_DESC = {
    "accel_up":   "主升加速",
    "decel_up":   "高位钝化",
    "accel_down": "主跌",
    "decel_down": "左侧抄底",
    "neutral":    "中性",
}

PHASE_CLASS = {
    "accel_up":   "phase-accel-up",
    "decel_up":   "phase-decel-up",
    "accel_down": "phase-accel-down",
    "decel_down": "phase-decel-down",
    "neutral":    "phase-neutral",
}


def _sign(x: float, threshold: float = 0.0) -> int:
    """返回 +1 / -1 / 0, 与 CASE-B2 inflection_detector._sign 一致."""
    if pd.isna(x):
        return 0
    if x > threshold:
        return 1
    if x < -threshold:
        return -1
    return 0


def detect_phase(dim: RotationDimension, d: Dict[str, float]) -> Dict[str, object]:
    """轮动象限判定: 速度/加速度两组信号投票多数决.

    roc_threshold 按 dim: sector 0.005 / concept 0.5 (量纲不同, 历史口径原样保留)。
    """
    if not d:
        return {"phase": "neutral", "phase_desc": PHASE_DESC["neutral"],
                "vote_velocity": 0, "vote_accel": 0}

    roc_20 = d.get("ROC_20", 0)
    ma20_slope = d.get("MA20_SLOPE", 0)
    ma20_accel = d.get("MA20_ACCEL", 0)
    hist_delta = d.get("HIST_DELTA", 0)

    roc_threshold = dim.roc_threshold
    accel_threshold = 0.0

    # 速度组投票: ROC_20 占 2 票, MA20_SLOPE 占 1 票
    v_score = _sign(roc_20, roc_threshold) * 2 + _sign(ma20_slope, accel_threshold) * 1
    velocity_dir = 1 if v_score > 0 else (-1 if v_score < 0 else 0)

    # 加速度组投票: MA20_ACCEL 占 1 票, MACD_HIST 变化方向占 1 票
    a_score = _sign(ma20_accel, accel_threshold) * 1 + _sign(hist_delta, accel_threshold) * 1
    accel_dir = 1 if a_score > 0 else (-1 if a_score < 0 else 0)

    if velocity_dir > 0 and accel_dir > 0:
        phase = "accel_up"
    elif velocity_dir > 0 and accel_dir < 0:
        phase = "decel_up"
    elif velocity_dir < 0 and accel_dir < 0:
        phase = "accel_down"
    elif velocity_dir < 0 and accel_dir > 0:
        phase = "decel_down"
    else:
        phase = "neutral"

    return {
        "phase":         phase,
        "phase_desc":    PHASE_DESC[phase],
        "phase_class":   PHASE_CLASS[phase],
        "vote_velocity": velocity_dir,
        "vote_accel":    accel_dir,
    }


PHASE_BONUS = {
    "accel_up":   3.0,
    "decel_down": 2.0,
    "decel_up":   0.5,
    "accel_down": -2.0,
    "neutral":    0.0,
}


# ============================================================
# 排名入口 (按 dim)
# ============================================================

def rank_with_phase(dim: RotationDimension,
                    level: int = 2,
                    end_date: Optional[str] = None,
                    lookback_days: Optional[int] = None,
                    top_n: Optional[int] = None) -> pd.DataFrame:
    """计算指定日期的轮动排名 (sector: rank_industries_with_phase; concept: rank_concepts_with_phase)."""
    if lookback_days is None:
        lookback_days = dim.lookback_default

    panel = load_all_items(dim, level=level, end_date=end_date)
    if not panel:
        return pd.DataFrame()

    bench = build_market_benchmark(panel)
    if bench.empty:
        return pd.DataFrame()

    items_meta = {it[f"{dim.key}_name" if dim.key == "sector" else "concept_code"]: it
                  for it in list_items(dim, level=level)}

    mom_z = f"MOM_{dim.mom_window}_z"
    rs_z = f"RS_{dim.rs_window}_z"
    mom_raw = f"MOM_{dim.mom_window}"
    rs_raw = f"RS_{dim.rs_window}"

    rows = {}
    for key, df in panel.items():
        df_window = df.tail(max(lookback_days, dim.min_days))
        if len(df_window) < dim.min_days:
            continue
        bench_window = bench.loc[bench.index.intersection(df_window.index)]

        ind = calc_strength_indicators(dim, df_window, bench_window)
        if not ind:
            continue
        derivs = calc_all_derivatives(dim, df_window["close"])
        phase_info = detect_phase(dim, derivs)

        row_data = {**ind, **derivs, **phase_info}

        if dim.has_concept_meta:
            # concept: 组装 concept_name/source_prefix/member_count
            meta = items_meta.get(key, {})
            row_data.update({
                "concept_name":  meta.get("concept_name", df_window["concept_name"].iloc[-1] if "concept_name" in df_window.columns else key),
                "source_prefix": meta.get("source_prefix", ""),
                "member_count":  meta.get("member_count", 0),
            })
        else:
            # sector: 仅 member_count
            row_data["member_count"] = items_meta.get(key, {}).get("member_count", 0)

        rows[key] = row_data

    df_all = pd.DataFrame.from_dict(rows, orient="index").dropna(
        subset=[mom_raw, rs_raw, "VOL_RATIO"])
    if df_all.empty:
        return df_all

    df_all[mom_z] = _zscore(df_all[mom_raw])
    df_all[rs_z] = _zscore(df_all[rs_raw])
    df_all["VOL_RATIO_z"] = _zscore(df_all["VOL_RATIO"])
    # 因子合成: sector 等权 mean / concept 加权和 (口径与 CASE-B2 对齐)
    if dim.score_equal_weight:
        df_all["score"] = df_all[[mom_z, rs_z, "VOL_RATIO_z"]].mean(axis=1)
    else:
        df_all["score"] = df_all[mom_z] + df_all[rs_z] + dim.vol_weight * df_all["VOL_RATIO_z"]
    df_all = df_all.sort_values("score", ascending=False)
    df_all["rank"] = range(1, len(df_all) + 1)

    df_all["phase_bonus"] = df_all["phase"].map(PHASE_BONUS).fillna(0.0)
    df_all["composite_score"] = df_all["score"] + df_all["phase_bonus"]
    df_all = df_all.sort_values("composite_score", ascending=False)
    df_all["composite_rank"] = range(1, len(df_all) + 1)

    return df_all.head(top_n) if top_n else df_all


# ============================================================
# 维度便捷入口 (供 worker/兼容层调用)
# ============================================================

def rank_sectors_with_phase(level: int = 2,
                            end_date: Optional[str] = None,
                            lookback_days: int = 90,
                            top_n: Optional[int] = None) -> pd.DataFrame:
    """板块轮动排名 (兼容原 sector_rotation.rotation_core.rank_industries_with_phase)."""
    return rank_with_phase(SECTOR, level=level, end_date=end_date,
                           lookback_days=lookback_days, top_n=top_n)


def rank_industries(level: int = 2, lookback_days: int = 90, top_n: int = 10):
    """快捷函数 (兼容原 sector_rotation.rotation_core.rank_industries)."""
    return rank_sectors_with_phase(level=level, lookback_days=lookback_days, top_n=top_n)


def rank_concepts_with_phase(end_date: Optional[str] = None,
                             lookback_days: int = 40,
                             top_n: Optional[int] = None) -> pd.DataFrame:
    """概念轮动排名 (兼容原 concept_rotation.rotation_core.rank_concepts_with_phase)."""
    return rank_with_phase(CONCEPT, level=2, end_date=end_date,
                           lookback_days=lookback_days, top_n=top_n)


def rank_concepts(lookback_days: int = 30, top_n: int = 10):
    """快捷函数 (兼容原 concept_rotation.rotation_core.rank_concepts)."""
    return rank_concepts_with_phase(lookback_days=lookback_days, top_n=top_n)
