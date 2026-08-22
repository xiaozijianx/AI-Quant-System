# -*- coding: utf-8 -*-
"""概念轮动核心计算.

本模块从 CASE-B2 概念轮动分析口径对齐, 独立运行, 不依赖 morning_brief。
计算所需数据来自 PostgreSQL 的 concept_daily_full / concept_stock_tag / concept_meta 表。

与板块轮动的核心差异:
    - 概念无 level 层级, 主键为 concept_code
    - 显示名使用 concept_name, 同名概念用 source_prefix 区分
    - 数据周期短, 强度指标窗口更短(MOM_10/RS_20/VOL_RATIO 5/20)
    - 最小数据条数要求更低(22 天)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor


# ============================================================
# 数据库连接(最小化, 独立配置)
# ============================================================

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


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
# 数据加载
# ============================================================

def list_concepts() -> List[Dict]:
    """列出所有活跃且已精选的概念.

    返回 [{concept_code, concept_name, source_prefix, member_count}, ...]
    """
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
    """取某概念最新交易日的成分股代码列表."""
    rows = execute_query(
        """
        SELECT stock_code FROM concept_stock_tag
        WHERE concept_code = %s
          AND trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag
                             WHERE concept_code = %s)
        ORDER BY stock_code
        """,
        (concept_code, concept_code),
    )
    return [r["stock_code"] for r in rows]


def load_concept_index(concept_code: str,
                       end_date: Optional[str] = None) -> pd.DataFrame:
    """从 concept_daily_full 加载单概念的合成指数 K 线."""
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
        "stock_count": "member_count",
    }, inplace=True)
    for col in ["open", "high", "low", "close", "amount", "change_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_all_concepts(end_date: Optional[str] = None,
                      min_days: int = 22) -> Dict[str, pd.DataFrame]:
    """一次性批量加载全部满足长度要求的概念指数.

    优化点: 一次批量查询, 按 concept_code 分组构造 DataFrame,
    避免每个概念一次 SQL。
    """
    conditions = []
    params: list = []
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT concept_code, concept_name, trade_date,
               open_idx, high_idx, low_idx, close_idx,
               total_volume, total_amount, change_pct, stock_count
        FROM concept_daily_full
        {where_clause}
        ORDER BY concept_code, trade_date ASC
    """
    rows = execute_query(sql, tuple(params) if params else None)
    if not rows:
        return {}

    df_all = pd.DataFrame(rows)
    df_all["trade_date"] = pd.to_datetime(df_all["trade_date"])
    numeric_cols = ["open_idx", "high_idx", "low_idx", "close_idx",
                    "total_volume", "total_amount", "change_pct", "stock_count"]
    for col in numeric_cols:
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce")

    result = {}
    for concept_code, group in df_all.groupby("concept_code"):
        if len(group) < min_days:
            continue
        df = group.set_index("trade_date").rename(columns={
            "open_idx": "open", "high_idx": "high",
            "low_idx": "low", "close_idx": "close",
            "total_volume": "volume", "total_amount": "amount",
            "stock_count": "member_count",
        }).sort_index()
        # 保留 concept_name 供后续使用
        df["concept_name"] = group["concept_name"].iloc[0]
        result[concept_code] = df

    return result


# ============================================================
# 强度指标与基准
# ============================================================

def build_market_benchmark(concept_panel: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """全部概念等权合成市场基准."""
    if not concept_panel:
        return pd.DataFrame()
    close_dict = {}
    amount_dict = {}
    for code, df in concept_panel.items():
        if df["close"].iloc[0] > 0:
            close_dict[code] = df["close"] / df["close"].iloc[0]
        amount_dict[code] = df["amount"]
    closes = pd.DataFrame(close_dict)
    amounts = pd.DataFrame(amount_dict)
    return pd.DataFrame({
        "close": closes.mean(axis=1) * 1000,
        "amount": amounts.sum(axis=1),
    })


def calc_strength_indicators(concept_kline: pd.DataFrame,
                             market_kline: pd.DataFrame) -> Dict[str, float]:
    """计算概念强度三因子: MOM_10 / RS_20 / VOL_RATIO(5/20).

    概念更短线, 窗口比板块更短。
    """
    min_need = 22
    common = concept_kline.index.intersection(market_kline.index)
    if len(common) < min_need:
        return {}
    ind = concept_kline.loc[common]
    bench = market_kline.loc[common]
    close = ind["close"]
    amount = ind["amount"]

    mom_10 = float(close.iloc[-1] / close.iloc[-11] - 1) if len(close) >= 11 else np.nan

    s_ret = close.pct_change(20).iloc[-1]
    m_ret = bench["close"].pct_change(20).iloc[-1]
    rs_20 = float(s_ret - m_ret) if pd.notna(s_ret) and pd.notna(m_ret) else np.nan

    avg_amt_5 = amount.tail(5).mean()
    avg_amt_20 = amount.tail(20).mean()
    vol_ratio = float(avg_amt_5 / avg_amt_20) if avg_amt_20 > 0 else np.nan

    return {"MOM_10": mom_10, "RS_20": rs_20, "VOL_RATIO": vol_ratio}


# ============================================================
# 导数指标与 phase 判定
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


def calc_all_derivatives(close: pd.Series) -> Dict[str, float]:
    """计算概念一阶导/二阶导指标, 与 CASE-B2 口径对齐.

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


def detect_phase(d: Dict[str, float]) -> Dict[str, object]:
    """概念轮动象限判定: 速度/加速度两组信号投票多数决.

    与板块轮动的 detect_phase 保持一致, 阈值适配概念波动特征。
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
# 排名入口
# ============================================================

def rank_concepts_with_phase(end_date: Optional[str] = None,
                             lookback_days: int = 40,
                             top_n: Optional[int] = None) -> pd.DataFrame:
    """计算指定日期的概念轮动排名."""
    panel = load_all_concepts(end_date=end_date)
    if not panel:
        return pd.DataFrame()

    bench = build_market_benchmark(panel)
    if bench.empty:
        return pd.DataFrame()

    concepts_meta = {c["concept_code"]: c for c in list_concepts()}

    rows = {}
    for code, df in panel.items():
        df_window = df.tail(max(lookback_days, 22))
        if len(df_window) < 22:
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
            "concept_name":  meta.get("concept_name", df_window["concept_name"].iloc[-1] if "concept_name" in df_window.columns else code),
            "source_prefix": meta.get("source_prefix", ""),
            "member_count":  meta.get("member_count", 0),
        }

    df_all = pd.DataFrame.from_dict(rows, orient="index").dropna(
        subset=["MOM_10", "RS_20", "VOL_RATIO"])
    if df_all.empty:
        return df_all

    df_all["MOM_10_z"]    = _zscore(df_all["MOM_10"])
    df_all["RS_20_z"]     = _zscore(df_all["RS_20"])
    df_all["VOL_RATIO_z"] = _zscore(df_all["VOL_RATIO"])
    # 因子合成: MOM_10_z + RS_20_z + 0.5 * VOL_RATIO_z, 与 CASE-B2 概念口径对齐
    df_all["score"] = df_all["MOM_10_z"] + df_all["RS_20_z"] + 0.5 * df_all["VOL_RATIO_z"]
    df_all = df_all.sort_values("score", ascending=False)
    df_all["rank"] = range(1, len(df_all) + 1)

    df_all["phase_bonus"] = df_all["phase"].map(PHASE_BONUS).fillna(0.0)
    df_all["composite_score"] = df_all["score"] + df_all["phase_bonus"]
    df_all = df_all.sort_values("composite_score", ascending=False)
    df_all["composite_rank"] = range(1, len(df_all) + 1)

    return df_all.head(top_n) if top_n else df_all


def rank_concepts(lookback_days: int = 30, top_n: int = 10):
    return rank_concepts_with_phase(lookback_days=lookback_days, top_n=top_n)
