# -*- coding: utf-8 -*-
# 概念轮动运行器（晨会内嵌）
"""
ConceptRotationRunner -- 整合"静态强度排名 + 一二阶导拐点检测", 给 graph.py 用

复制源: CASE-B2-概念轮动分析-PostgreSQL
主接口:
    rank_concepts_with_phase(lookback_days=40, top_n=5) -> pd.DataFrame
    get_concept_member_codes(concept_code) -> List[str]
"""
from __future__ import annotations
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .db_config import execute_query


# ============================================================
# 概念清单 + 成分股
# ============================================================

def list_concepts() -> List[Dict]:
    """列出所有已筛选的活跃概念"""
    sql = """
        SELECT cm.concept_code, cm.concept_name, cm.source_prefix,
               COALESCE(tag_counts.cnt, 0) AS member_count
        FROM concept_meta cm
        LEFT JOIN (
            SELECT concept_code, COUNT(*) AS cnt
            FROM concept_stock_tag
            WHERE trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
            GROUP BY concept_code
        ) tag_counts ON cm.concept_code = tag_counts.concept_code
        WHERE cm.is_active = TRUE AND cm.is_curated = TRUE
        ORDER BY cm.concept_code
    """
    return execute_query(sql)


def get_concept_member_codes(concept_code: str) -> List[str]:
    """取某概念最新交易日的成分股代码列表"""
    rows = execute_query(
        "SELECT stock_code FROM concept_stock_tag "
        "WHERE concept_code = %s "
        "  AND trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag "
        "                     WHERE concept_code = %s) "
        "ORDER BY stock_code",
        (concept_code, concept_code))
    return [r["stock_code"] for r in rows]


def load_concept_index(concept_code: str,
                        end_date: Optional[str] = None) -> pd.DataFrame:
    """从 concept_daily_full 加载单概念的合成指数 K 线"""
    conditions = ["concept_code = %s"]
    params: list = [concept_code]
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    sql = f"""
        SELECT trade_date, concept_name,
               open_idx, high_idx, low_idx, close_idx,
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
    }, inplace=True)
    for col in ["open", "high", "low", "close", "amount", "change_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_all_concepts(end_date: Optional[str] = None,
                       min_days: int = 20) -> Dict[str, pd.DataFrame]:
    result = {}
    for c in list_concepts():
        df = load_concept_index(c["concept_code"], end_date=end_date)
        if not df.empty and len(df) >= min_days:
            result[c["concept_code"]] = df
    return result


def build_market_benchmark(concept_panel: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """全部概念等权 -> 市场基准"""
    if not concept_panel:
        return pd.DataFrame()
    closes  = pd.DataFrame()
    amounts = pd.DataFrame()
    for code, df in concept_panel.items():
        if df["close"].iloc[0] > 0:
            closes[code] = df["close"] / df["close"].iloc[0]
        amounts[code] = df["amount"]
    return pd.DataFrame({
        "close":  closes.mean(axis=1) * 1000,
        "amount": amounts.sum(axis=1),
    })


# ============================================================
# 静态强度因子
# ============================================================

def calc_strength_indicators(concept_kline: pd.DataFrame,
                              market_kline: pd.DataFrame) -> Dict[str, float]:
    if len(concept_kline) < 22 or len(market_kline) < 22:
        return {}
    close = concept_kline["close"]
    amount = concept_kline["amount"]

    mom_10 = float(close.iloc[-1] / close.iloc[-11] - 1) if len(close) >= 11 else np.nan

    s_ret = close.pct_change(20).iloc[-1]
    m_ret = market_kline["close"].pct_change(20).iloc[-1]
    rs_20 = float(s_ret - m_ret) if pd.notna(s_ret) and pd.notna(m_ret) else np.nan

    avg_amt_5  = amount.tail(5).mean()
    avg_amt_20 = amount.tail(20).mean()
    vol_ratio = float(avg_amt_5 / avg_amt_20) if avg_amt_20 > 0 else np.nan

    return {"MOM_10": mom_10, "RS_20": rs_20, "VOL_RATIO": vol_ratio}


def _zscore(s: pd.Series) -> pd.Series:
    mu = s.mean()
    sd = s.std()
    if sd == 0 or pd.isna(sd):
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


# ============================================================
# 一阶导 + 二阶导
# ============================================================

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


def calc_all_derivatives(close: pd.Series) -> Dict[str, float]:
    """计算概念一阶导/二阶导指标, 与 concept_rotation/rotation_core.py 口径对齐.

    概念数据周期短, 最小长度从板块的 60 天放宽到 35 天。
    """
    if len(close) < 35:
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


def _sign(x: float, threshold: float = 0.0) -> int:
    """返回 +1 / -1 / 0, 与 concept_rotation/rotation_core.py 对齐."""
    if pd.isna(x):
        return 0
    if x > threshold:
        return 1
    if x < -threshold:
        return -1
    return 0


def detect_phase(d: Dict[str, float]) -> Dict[str, object]:
    """概念轮动象限判定: 速度/加速度两组信号投票多数决.

    与 concept_rotation/rotation_core.py 保持完全一致。
    """
    if not d:
        return {"phase": "neutral", "phase_desc": PHASE_DESC["neutral"],
                "vote_velocity": 0, "vote_accel": 0}

    roc_20 = d.get("ROC_20", 0)
    ma20_slope = d.get("MA20_SLOPE", 0)
    ma20_accel = d.get("MA20_ACCEL", 0)
    hist_delta = d.get("HIST_DELTA", 0)

    roc_threshold = 0.5    # 0.5%
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
        "vote_velocity": velocity_dir,
        "vote_accel":    accel_dir,
    }


# ============================================================
# 综合视图
# ============================================================

PHASE_BONUS = {
    "accel_up":   3.0,
    "decel_down": 2.0,
    "decel_up":   0.5,
    "accel_down": -2.0,
    "neutral":    0.0,
}


def rank_concepts_with_phase(end_date: Optional[str] = None,
                              lookback_days: int = 40,
                              top_n: int = 10) -> pd.DataFrame:
    """
    给 graph.py 调用的主接口: 一次性返回 Top N 概念, 含静态强度 + 拐点 phase

    返回 DataFrame, index=concept_code, columns=[
        concept_name, composite_score, composite_rank, score, rank,
        MOM_10, RS_20, VOL_RATIO,
        phase, phase_desc, ROC_20, MA20_SLOPE, MACD_HIST, MA20_ACCEL,
        member_count
    ]
    """
    panel = load_all_concepts(end_date=end_date)
    if not panel:
        return pd.DataFrame()

    bench = build_market_benchmark(panel)
    if bench.empty:
        return pd.DataFrame()

    concepts_meta = {c["concept_code"]: c for c in list_concepts()}

    min_bars = 22
    rows = {}
    for code, df in panel.items():
        df_window = df.tail(max(lookback_days, min_bars))
        if len(df_window) < min_bars:
            continue
        bench_window = bench.loc[bench.index.intersection(df_window.index)]

        ind = calc_strength_indicators(df_window, bench_window)
        if not ind:
            continue
        derivs = calc_all_derivatives(df_window["close"])
        phase_info = detect_phase(derivs)

        meta = concepts_meta.get(code, {})
        rows[code] = {
            **ind,
            **derivs,
            **phase_info,
            "concept_name": meta.get("concept_name", code),
            "member_count": meta.get("member_count", 0),
        }

    df_all = pd.DataFrame.from_dict(rows, orient="index").dropna(
        subset=["MOM_10", "RS_20", "VOL_RATIO"])
    if df_all.empty:
        return df_all

    df_all["MOM_10_z"]    = _zscore(df_all["MOM_10"])
    df_all["RS_20_z"]     = _zscore(df_all["RS_20"])
    df_all["VOL_RATIO_z"] = _zscore(df_all["VOL_RATIO"])
    df_all["score"]       = df_all["MOM_10_z"] + df_all["RS_20_z"] + 0.5 * df_all["VOL_RATIO_z"]
    df_all = df_all.sort_values("score", ascending=False)
    df_all["rank"] = range(1, len(df_all) + 1)

    df_all["phase_bonus"]     = df_all["phase"].map(PHASE_BONUS).fillna(0.0)
    df_all["composite_score"] = df_all["score"] + df_all["phase_bonus"]
    df_all = df_all.sort_values("composite_score", ascending=False)
    df_all["composite_rank"]  = range(1, len(df_all) + 1)

    return df_all.head(top_n) if top_n else df_all
