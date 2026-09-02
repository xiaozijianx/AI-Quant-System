# -*- coding: utf-8 -*-
# 多因子选股运行器（晨会内嵌）
from __future__ import annotations
import math
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .db_config import execute_query


# ============================================================
# 因子分组定义（用于可解释性输出）
# ============================================================

FACTOR_GROUPS = {
    "趋势动量": ["MOM_1M", "MOM_3M", "MOM_6M", "RSI_14"],
    "质量价值": ["ROE", "NetProfit_YoY", "GrossMargin", "NegDebtRatio"],
    "风险回避": ["REV_5D", "VOL_20", "VOL_60", "BIAS_20"],
    "情绪流动性": ["LIQ_20", "turnover_rate_20"],
}

# 因子分组说明（用于前端展示）
FACTOR_GROUP_DESC = {
    "趋势动量": "价格趋势与相对强度，如月度/季度动量、RSI，反映近期上涨动能",
    "质量价值": "财务质量与估值水平，如 ROE、净利润同比、毛利率、负债率",
    "风险回避": "波动率、回撤、乖离率，用于规避波动过大或短期过热的品种",
    "情绪流动性": "换手率、成交额与流动性，反映市场关注度和交易活跃程度",
}

FINANCIAL_FACTORS = ["ROE", "NetProfit_YoY", "GrossMargin", "NegDebtRatio"]

# 财务因子异常阈值：用于选股前剔除财务数据异常的股票
ROE_VALID_RANGE = (-30.0, 50.0)              # ROE 在 -30% ~ 50% 之间视为正常
GROSS_MARGIN_VALID_RANGE = (-100.0, 100.0)   # 毛利率
DEBT_RATIO_VALID_RANGE = (0.0, 100.0)        # 资产负债率


def load_kline_from_db(stock_code: str, lookback_days: int = 200,
                       table: str = "trade_stock_daily") -> pd.DataFrame:
    """加载单股最近 N 个交易日的日 K 线

    参数:
        table: 数据表名, 默认前复权表 trade_stock_daily(与因子库生成/评价口径一致,
               且含换手率 turnover_rate); 后复权表 trade_stock_daily_back 的
               turnover_rate 全空(采集脚本未自算), 需换手率因子时不可用。
    """
    _ALLOWED_TABLES = {"trade_stock_daily", "trade_stock_daily_back"}
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"不支持的 K 线表: {table}")
    sql = f"""
        SELECT trade_date, open_price, high_price, low_price, close_price,
               volume, amount, turnover_rate
        FROM {table}
        WHERE stock_code = %s
        ORDER BY trade_date DESC
        LIMIT %s
    """
    rows = execute_query(sql, (stock_code, lookback_days))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows[::-1])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.set_index("trade_date", inplace=True)
    df.rename(columns={
        "open_price": "open", "high_price": "high",
        "low_price":  "low",  "close_price": "close",
    }, inplace=True)
    for col in ["open", "high", "low", "close", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    # 换手率(可选列): 数值化 + 合理性过滤(0~100), 与因子库 backtest_data 口径一致
    if "turnover_rate" in df.columns:
        df["turnover_rate"] = pd.to_numeric(df["turnover_rate"], errors="coerce")
        df["turnover_rate"] = df["turnover_rate"].where(
            (df["turnover_rate"] >= 0) & (df["turnover_rate"] <= 100))
    return df


def load_fundamental_from_db(stock_codes: List[str],
                              as_of_date: str,
                              lag_days: int = 120) -> pd.DataFrame:
    """
    截至 as_of_date 时点，返回每只股票最新可用的财务因子值。

    可用规则：report_date + lag_days <= as_of_date，避免未来信息泄露。
    默认 lag_days=120，覆盖 A 股 Q4 年报发布滞后（12-31 截止 -> 次年 4 月底）。

    返回：DataFrame(index=stock_code, columns=[ROE, NetProfit_YoY, GrossMargin, NegDebtRatio])
    """
    if not stock_codes:
        return pd.DataFrame()

    cutoff = pd.to_datetime(as_of_date) - pd.Timedelta(days=lag_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    placeholders = ",".join(["%s"] * len(stock_codes))

    sql = f"""
        SELECT stock_code, report_date, roe, net_profit, gross_margin,
               debt_ratio
        FROM trade_stock_financial
        WHERE stock_code IN ({placeholders})
          AND report_date <= %s
        ORDER BY stock_code, report_date ASC
    """
    params = list(stock_codes) + [cutoff_str]
    rows = execute_query(sql, params)
    if not rows:
        return pd.DataFrame()

    # 按股票分组，只保留最新一期报告
    latest_by_code: Dict[str, dict] = {}
    for r in rows:
        code = r["stock_code"]
        latest_by_code[code] = r

    result_rows = {}
    for code, r in latest_by_code.items():
        result_rows[code] = {
            "ROE":          float(r["roe"]) if r["roe"] is not None else np.nan,
            "GrossMargin":  float(r["gross_margin"]) if r["gross_margin"] is not None else np.nan,
            "NegDebtRatio": -float(r["debt_ratio"]) if r["debt_ratio"] is not None else np.nan,
        }

    # 计算 NetProfit_YoY：需要往前推一年的同期净利润
    for code, r in latest_by_code.items():
        cur_np = float(r["net_profit"]) if r["net_profit"] is not None else np.nan
        cur_dt = pd.to_datetime(r["report_date"])
        last_dt = (cur_dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")

        last_np = np.nan
        for rr in rows:
            if rr["stock_code"] == code and str(rr["report_date"]) == last_dt:
                last_np = float(rr["net_profit"]) if rr["net_profit"] is not None else np.nan
                break

        yoy = np.nan
        if pd.notna(cur_np) and pd.notna(last_np) and abs(last_np) > 1e6:
            yoy = np.clip((cur_np - last_np) / abs(last_np) * 100, -200, 500)
        result_rows[code]["NetProfit_YoY"] = yoy

    df = pd.DataFrame.from_dict(result_rows, orient="index")
    return df


def load_float_shares(stock_codes: List[str]) -> Dict[str, float]:
    """一次性加载流通股本（股）"""
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT stock_code, float_shares
        FROM trade_stock_status
        WHERE stock_code IN ({placeholders})
    """
    rows = execute_query(sql, stock_codes)
    return {
        r["stock_code"]: float(r["float_shares"]) if r["float_shares"] else 0.0
        for r in rows
    }


def load_stock_basic_batch(stock_codes: List[str]) -> Dict[str, Dict[str, str]]:
    """批量加载股票基本信息：名称、申万一级、申万二级"""
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT stock_code, stock_name, sector_1, sector_2
        FROM trade_stock_status
        WHERE stock_code IN ({placeholders})
    """
    rows = execute_query(sql, stock_codes)
    return {
        r["stock_code"]: {
            "code": r["stock_code"],
            "name": r["stock_name"] or "",
            "sector_1": r["sector_1"] or "",
            "sector_2": r["sector_2"] or "",
        }
        for r in rows
    }


def load_stock_concepts_batch(stock_codes: List[str]) -> Dict[str, List[str]]:
    """批量加载每只股票所属的全部概念名称列表"""
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT DISTINCT cst.stock_code, cm.concept_name
        FROM concept_stock_tag cst
        JOIN concept_meta cm ON cm.concept_code = cst.concept_code
        WHERE cst.stock_code IN ({placeholders})
          AND cst.trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
        ORDER BY cst.stock_code, cm.concept_name
    """
    rows = execute_query(sql, stock_codes)
    result: Dict[str, List[str]] = {code: [] for code in stock_codes}
    for r in rows:
        code = r["stock_code"]
        name = r["concept_name"]
        if name and name not in result[code]:
            result[code].append(name)
    return result


def is_fundamental_valid(fundamental: Optional[Dict[str, float]]) -> bool:
    """
    检查财务因子是否在合理范围内，剔除财务异常股票。
    返回 False 表示该股票不应参与选股。
    """
    if not fundamental:
        return False

    roe = fundamental.get("ROE")
    gm = fundamental.get("GrossMargin")
    debt = fundamental.get("NegDebtRatio")

    if pd.notna(roe) and (roe < ROE_VALID_RANGE[0] or roe > ROE_VALID_RANGE[1]):
        return False
    if pd.notna(gm) and (gm < GROSS_MARGIN_VALID_RANGE[0] or gm > GROSS_MARGIN_VALID_RANGE[1]):
        return False
    # NegDebtRatio 是 -debt_ratio，所以正常范围是 -100 ~ 0
    if pd.notna(debt) and (debt < -DEBT_RATIO_VALID_RANGE[1] or debt > -DEBT_RATIO_VALID_RANGE[0]):
        return False

    return True


def _safe_pct_change(prices: pd.Series, periods: int) -> float:
    if len(prices) <= periods:
        return np.nan
    p_now  = prices.iloc[-1]
    p_then = prices.iloc[-1 - periods]
    if p_then <= 0:
        return np.nan
    return p_now / p_then - 1.0


def calc_factors_for_one(df: pd.DataFrame,
                         float_shares: float = 0,
                         fundamental: Optional[Dict[str, float]] = None,
                         strict_fundamental: bool = True) -> Dict[str, float]:
    """
    给定单股日 K（后复权），算 10 个技术因子 + 4 个财务因子。

    参数：
        df:                  日 K DataFrame，含 close / volume / amount
        float_shares:        流通股本（股），用于计算真实换手率
        fundamental:         {ROE, NetProfit_YoY, GrossMargin, NegDebtRatio} 财务因子字典
        strict_fundamental:  True 时剔除财务异常股票
    """
    if df is None or len(df) < 130:
        return {}

    close  = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else None
    amount = df["amount"].astype(float) if "amount" in df.columns else None

    returns = close.pct_change().dropna()
    if len(returns) < 100:
        return {}

    # 财务异常剔除
    if strict_fundamental and not is_fundamental_valid(fundamental):
        return {}

    f = {}

    # ---- 动量 ----
    f["MOM_1M"] = _safe_pct_change(close, 21)
    f["MOM_3M"] = _safe_pct_change(close, 63)
    f["MOM_6M"] = _safe_pct_change(close, 126)

    # ---- 反转（短期，取负号 -- 短期上涨过多易回调）----
    rev_5d = _safe_pct_change(close, 5)
    f["REV_5D"] = -rev_5d if not np.isnan(rev_5d) else np.nan

    # ---- 波动率（年化，取负号 -- 低波动好）----
    vol_20 = returns.tail(20).std() * math.sqrt(250)
    vol_60 = returns.tail(60).std() * math.sqrt(250)
    f["VOL_20"] = -vol_20 if not np.isnan(vol_20) else np.nan
    f["VOL_60"] = -vol_60 if not np.isnan(vol_60) else np.nan

    # ---- 流动性 ----
    if amount is not None and len(amount) >= 20:
        liq_20 = amount.tail(20).mean()
        f["LIQ_20"] = -math.log(max(liq_20, 1.0))
    else:
        f["LIQ_20"] = np.nan

    # ---- 换手率：用流通股本计算真实换手率 (键名正名: 旧 TURN_20 与因子库量比因子混淆, 现用 turnover_rate_20) ----
    turn_20 = np.nan
    if volume is not None and len(volume) >= 20:
        if float_shares > 0:
            # volume 单位是股，float_shares 单位也是股，结果转换为 %
            turn_20 = (volume.tail(20).mean() / float_shares) * 100
        else:
            # 没有股本数据，用 volume / 长期均量 作为相对换手代理
            long_vol = volume.tail(60).mean()
            turn_20 = volume.tail(20).mean() / long_vol if long_vol > 0 else np.nan
    f["turnover_rate_20"] = -turn_20 if not np.isnan(turn_20) else np.nan

    # ---- RSI 14 ----
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi_val = rsi.iloc[-1] if len(rsi) > 0 else np.nan
    f["RSI_14"] = (rsi_val - 50) if not np.isnan(rsi_val) else np.nan

    # ---- BIAS 20（乖离率）----
    ma20 = close.rolling(20).mean().iloc[-1]
    bias_20 = (close.iloc[-1] - ma20) / ma20 if ma20 > 0 else np.nan
    f["BIAS_20"] = -bias_20 if not np.isnan(bias_20) else np.nan

    # ---- 财务因子 ----
    if fundamental:
        f["ROE"] = fundamental.get("ROE", np.nan)
        f["NetProfit_YoY"] = fundamental.get("NetProfit_YoY", np.nan)
        f["GrossMargin"] = fundamental.get("GrossMargin", np.nan)
        f["NegDebtRatio"] = fundamental.get("NegDebtRatio", np.nan)
    else:
        f["ROE"] = np.nan
        f["NetProfit_YoY"] = np.nan
        f["GrossMargin"] = np.nan
        f["NegDebtRatio"] = np.nan

    return f


def calc_factors_batch(stock_codes: List[str],
                       lookback_days: int = 200,
                       as_of_date: Optional[str] = None,
                       use_fundamental: bool = True,
                       fund_lag_days: int = 120,
                       strict_fundamental: bool = True) -> pd.DataFrame:
    """
    批量算因子矩阵。

    参数：
        stock_codes:         股票代码列表
        lookback_days:       拉多少日 K 线
        as_of_date:          财务因子截至日期，默认今天
        use_fundamental:     是否加载财务因子
        fund_lag_days:       财务数据使用滞后天数，默认 120
        strict_fundamental:  是否剔除财务异常股票

    返回：DataFrame, index=股票代码, columns=因子名
    """
    if as_of_date is None:
        as_of_date = date.today().strftime("%Y-%m-%d")

    # 一次性加载所有财务数据
    fund_df = pd.DataFrame()
    if use_fundamental:
        fund_df = load_fundamental_from_db(stock_codes, as_of_date, lag_days=fund_lag_days)
        print(f"  [FUND] 加载财务因子: {len(fund_df)} 只")

    # 一次性加载流通股本
    float_share_map = load_float_shares(stock_codes)

    rows = {}
    fail_codes = []
    for code in stock_codes:
        try:
            df = load_kline_from_db(code, lookback_days=lookback_days)
            if df.empty:
                continue
            float_shares = float_share_map.get(code, 0.0)
            fundamental = fund_df.loc[code].to_dict() if code in fund_df.index else None
            f = calc_factors_for_one(
                df,
                float_shares=float_shares,
                fundamental=fundamental,
                strict_fundamental=strict_fundamental,
            )
            if f:
                rows[code] = f
        except Exception as e:
            # 单只股票异常不中断整批，记录后继续
            fail_codes.append(code)
            print(f"  [FACTOR] {code} 因子计算异常: {e}")

    df_result = pd.DataFrame.from_dict(rows, orient="index")
    print(f"  [FACTOR] {len(df_result)} 只有效, "
          f"{len(stock_codes) - len(df_result) - len(fail_codes)} 只数据不足, "
          f"{len(fail_codes)} 只计算异常")
    return df_result


def winsorize_mad(series: pd.Series, n: float = 3.0) -> pd.Series:
    s = series.copy()
    median = s.median()
    mad = (s - median).abs().median()
    if mad == 0 or np.isnan(mad):
        return s
    upper = median + n * 1.4826 * mad
    lower = median - n * 1.4826 * mad
    return s.clip(lower=lower, upper=upper)


def zscore(series: pd.Series) -> pd.Series:
    s = series.copy()
    mean = s.mean()
    std  = s.std(ddof=1)
    if std == 0 or np.isnan(std):
        return s * 0.0
    return (s - mean) / std


def industry_neutralize(factor_series: pd.Series, industry_map: dict) -> pd.Series:
    df = pd.DataFrame({
        "factor":   factor_series,
        "industry": pd.Series(industry_map),
    })
    df = df.dropna(subset=["industry"])
    return df.groupby("industry")["factor"].transform(zscore)


def preprocess_factors(factor_df: pd.DataFrame,
                        industry_map: Optional[dict] = None,
                        winsorize_n: float = 3.0,
                        neutralize: bool = True) -> pd.DataFrame:
    result = pd.DataFrame(index=factor_df.index)
    for col in factor_df.columns:
        s = factor_df[col].dropna()
        if len(s) == 0:
            result[col] = factor_df[col]
            continue
        s_w = winsorize_mad(s, n=winsorize_n)
        s_z = zscore(s_w)
        if neutralize and industry_map:
            s_z = industry_neutralize(s_z, industry_map)
            s_z = zscore(s_z)
        result[col] = s_z
    return result


# ============================================================
# 因子分组得分（可解释性）
# ============================================================

def calc_group_scores(processed_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算每只股票的四个维度分组得分。
    每组内部因子等权平均，再对组内得分做 Z-score 标准化。
    """
    group_scores = pd.DataFrame(index=processed_df.index)
    for group_name, factors in FACTOR_GROUPS.items():
        valid_factors = [f for f in factors if f in processed_df.columns]
        if not valid_factors:
            group_scores[group_name] = np.nan
            continue
        # 等权平均（NaN 自动 skip）
        group_scores[group_name] = processed_df[valid_factors].mean(axis=1, skipna=True)

    # 对四个组得分再做一次 Z-score，方便横向比较
    for col in group_scores.columns:
        s = group_scores[col].dropna()
        if len(s) > 1 and s.std(ddof=1) > 0:
            group_scores[col] = (group_scores[col] - s.mean()) / s.std(ddof=1)
        else:
            group_scores[col] = 0.0

    return group_scores


def explain_stock(processed_df: pd.DataFrame,
                  group_scores: pd.DataFrame,
                  stock_code: str) -> Dict[str, Any]:
    """
    返回单只股票的可解释性信息。
    """
    if stock_code not in processed_df.index:
        return {}

    factors = processed_df.loc[stock_code].to_dict()
    groups = group_scores.loc[stock_code].to_dict()

    # 找出贡献最大的分组
    top_group = max(groups.items(), key=lambda x: x[1] if pd.notna(x[1]) else -np.inf)

    # 找出正向贡献最大的三个因子
    sorted_factors = sorted(
        [(k, v) for k, v in factors.items() if pd.notna(v)],
        key=lambda x: x[1],
        reverse=True,
    )
    top_factors = sorted_factors[:3]

    return {
        "stock_code": stock_code,
        "top_group": top_group[0],
        "top_group_score": round(top_group[1], 3),
        "group_scores": {k: round(v, 3) for k, v in groups.items()},
        "top_factors": [(k, round(v, 3)) for k, v in top_factors],
    }


def synthesize_alpha(processed_df: pd.DataFrame,
                     group_weights: Optional[Dict[str, float]] = None) -> pd.Series:
    """
    默认等权合成所有有效因子。
    如果传入 group_weights，则按分组维度加权合成。
    """
    if group_weights:
        group_scores = calc_group_scores(processed_df)
        weights = pd.Series(group_weights)
        # 对齐
        common = [g for g in group_scores.columns if g in weights.index]
        if not common:
            return processed_df.mean(axis=1, skipna=True).dropna().sort_values(ascending=False)
        weighted = group_scores[common].mul(weights[common], axis=1).sum(axis=1, skipna=True)
        return weighted.dropna().sort_values(ascending=False)

    return processed_df.mean(axis=1, skipna=True).dropna().sort_values(ascending=False)


# ============================================================
# 可交易过滤（从 trade_stock_status 读）
# ============================================================

def filter_tradable(stock_codes: List[str], min_listed_days: int = 250) -> List[str]:
    if not stock_codes:
        return []

    placeholders = ",".join(["%s"] * len(stock_codes))
    rows = execute_query(
        f"SELECT stock_code, stock_name, list_date FROM trade_stock_status "
        f"WHERE stock_code IN ({placeholders})",
        stock_codes)
    info = {r["stock_code"]: r for r in rows}
    today = date.today()

    keep = []
    for code in stock_codes:
        meta = info.get(code)
        if not meta:
            continue
        name = (meta.get("stock_name") or "")
        if "ST" in name.upper() or "退" in name:
            continue
        listed = meta.get("list_date")
        if listed:
            try:
                ld = listed if isinstance(listed, date) else date.fromisoformat(str(listed))
                if (today - ld).days < min_listed_days:
                    continue
            except Exception:
                pass
        keep.append(code)

    return keep
