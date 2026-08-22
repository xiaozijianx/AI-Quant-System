# -*- coding: utf-8 -*-
"""
lib/factor_rl/features.py -- RL 因子挖掘特征集 (深度复刻 AlphaMaster, 适配本系统股票池)

特征定义依  docs/AlphaMaster特征算子与因子库映射方案.md 的 65 特征映射表 (阶段三落地),
顺序与原版 model_core/features.py 的 _FEATURE_DEFS 完全一致 (0..64), 保证词表 token 顺序稳定。

特征 token 派生原则:
  - 每个 AlphaMaster 特征 -> 本系统因子库表达式 (基类+算子自包含形式),
    使 RL 挖出的公式解码后能被本系统 evaluate_expression 求值、被因子库消费。
  - 标度类差异 (原版 RSI/MFI/WILLR 归一化 [-1,1] vs 本系统 0~100) 由特征通道的
    robust 归一化 (median/MAD, clip ±5) 吸收; 公式类差异 (SLOPE20/MA_DIFF/OBV_SLOPE
    为库内近似) 遵循映射方案已批准口径。

特征计算: 统一用本系统 evaluate_expression 在面板上求值, 得到 [日期, 股票] 面板,
再按股票转置为 [N, T] 张量, 逐特征 robust 归一化后堆叠为 [N, F, T]。
"""
from __future__ import annotations

import torch

# ============================================================
# AlphaMaster 65 特征 -> 本系统因子库表达式 (顺序与原版一致)
# ============================================================
# 表达式均为"基类+算子自包含形式", 与 factor_init.py 中已入库因子的 formula 同构
# (可直接 evaluate_expression 求值, 无需依赖因子表)。
FEATURE_SPECS: list = [
    # ---- 趋势类 trend (0-4) ----
    ("RET",           "returns(1)"),
    ("RET5",          "returns(5)"),
    ("RET20",         "returns(20)"),
    ("MA_DIFF",       "bias(10)/bias(30)-1"),
    ("SLOPE20",       "momentum(20)-ts_Shift(momentum(20),10)"),
    # ---- 波动类 volatility (5-8) ----
    ("ATR",           "atr(14)"),
    ("RVOL",          "volatility(20)"),
    ("HL_RANGE",      "(High-Low)/Close"),
    ("VOL_REGIME",    "atr(14)/ts_Mean(atr(14),20)-1"),
    # ---- 反转类 reversal (9-13) ----
    ("DEV",           "bias(20)"),
    ("DEV60",         "bias(60)"),
    ("RSI14",         "rsi(14)"),
    ("PRESSURE",      "(Close-Open)/(High-Low)"),
    ("AC1",           "autocorr(20,1)"),
    # ---- 量能类 volume (14-16) ----
    ("VOL_RATIO",     "volume_ratio(20)"),
    ("VOL_Z",         "(volume_ratio(20)-1)/ts_Stdev(volume_ratio(20),20)"),
    ("PV_CORR",       "price_volume_corr(10)"),
    # ---- 跨截面相对强弱 cross_sectional (17-19) ----
    ("REL_RET5",      "cs_Demean(returns(5))"),
    ("REL_RET20",     "cs_Demean(returns(20))"),
    ("REL_VOL",       "cs_Demean(volatility(20))"),
    # ---- 量能/技术补充 (20-25) ----
    ("VWAP_DEV",      "(Close-VWAP)/VWAP"),
    ("BOLL_POS",      "bbands()"),
    ("BOLL_WIDTH",    "bbands_width()"),
    ("MACD_HIST",     "ts_MACD_HIST(Close,12,26,9)"),
    ("OBV_SLOPE",     "(ts_OBV(Close,Volume)-ts_Mean(ts_OBV(Close,Volume),10))/ts_Mean(ts_OBV(Close,Volume),10)"),
    ("MFI14",         "TALIB_MFI()"),
    # ---- Alpha101 系列 (26-29) ----
    ("WILLR_14",      "willr(14)"),
    ("CCI_14",        "cci(14)"),
    ("ROC_12",        "momentum(12)"),
    ("TYPICAL_DEV",   "typical_dev(20)"),
    # ---- 趋势类补充 (30-32) ----
    ("EMA_RATIO_12_26",  "ema(12)/ema(26)-1"),
    ("TREND_STRENGTH_50","trend_strength(50)"),
    ("PRICE_POS_50",     "price_position(50)"),
    # ---- 动量类 (33-36) ----
    ("TRIX_15",       "trix(15)"),
    ("PPO",           "TALIB_PPO()"),
    ("ULT_OSC",       "TALIB_UO()"),
    ("RET_ACCEL",     "(momentum(10)-ts_Shift(momentum(10),5))-ts_Shift(momentum(10)-ts_Shift(momentum(10),5),5)"),
    # ---- OHLC 波动估计量 (37-40) ----
    ("GK_VOL",        "gk_vol(20)"),
    ("PARKINSON_VOL", "parkinson_vol(20)"),
    ("YANG_ZHANG_VOL","yang_zhang_vol(20)"),
    ("RS_VOL",        "rs_vol(20)"),
    # ---- 量能/流动性 (41-44) ----
    ("AMIHUD_ILLIQ",  "amihud_illiq(20)"),
    ("KYLE_LAMBDA",   "kyle_lambda(20)"),
    ("CMF_20",        "cmf(20)"),
    ("AD_LINE_SLOPE", "ad_line_slope(20)"),
    # ---- 反转/振荡 (45-50) ----
    ("STOCH_K_14",    "ts_KDJ_K(High,Low,Close,9,3)"),
    ("STOCH_D_3",     "ts_KDJ_D(High,Low,Close,9,3)"),
    ("AROON_OSC_25",  "TALIB_AROONOSC()"),
    ("DMI_ADX_14",    "adx(14)"),
    ("DMI_DIFF_14",   "dmi_diff(14)"),
    ("TRIX_SIGNAL",   "trix(15)-ts_Mean(trix(15),9)"),
    # ---- 通道/突破 (51-56) ----
    ("DONCHIAN_POS_20",    "price_position(20)"),
    ("KELTNER_POS_20",     "keltner(20)"),
    ("ICHIMOKU_KIJUN_DEV", "ichimoku_kijun(26)"),
    ("ICHIMOKU_TENKAN_DEV","ichimoku_tenkan(9)"),
    ("SUPERTREND_DIR",     "supertrend(14)"),
    ("SAR_DIST",           "sar_dist()"),
    # ---- 统计类 (57-62) ----
    ("ROLL_SKEW_20",  "ts_Skewness(returns(1),20)"),
    ("ROLL_KURT_20",  "ts_Kurtosis(returns(1),20)"),
    ("HURST_50",      "hurst(50)"),
    ("FRACTAL_DIM_30","fractal_dim(30)"),
    ("AC2",           "autocorr(20,2)"),
    ("RET_ENTROPY_20","ret_entropy(20)"),
    # ---- 跨截面相对强弱补充 (63-64) ----
    ("CS_RANK_RET5",    "cs_Rank(returns(5))"),
    ("CS_ZSCORE_RET20", "cs_Zscore(returns(20))"),
]

# 完整特征名列表 (有序, 供词表派生)
FEATURE_NAMES = [name for name, _expr in FEATURE_SPECS]

# 特征名 -> 本系统表达式 (供 token 解码时替换, 保证 evaluate_expression 可求值)
FEATURE_EXPRS = {name: expr for name, expr in FEATURE_SPECS}

# 基础字段 (保留常量: 恒等叶子, 供需要时直接取面板值; 默认特征集不使用)
BASE_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount", "VWAP",
               "Turnover", "IdioRet", "Value", "TotalRet"]


def _robust_norm(x: torch.Tensor, w: int = 200) -> torch.Tensor:
    """因果滚动 robust 归一化 (median/MAD, clip ±5, warm-up 期输出 0)

    每个时间步 t 只用 [t-w+1..t] 共 w 期数据计算 median/MAD, 彻底消除 look-ahead。
    出口统一 nan_to_num (0), 避免窗口内 NaN 污染下游。
    """
    N, T = x.shape
    if T <= 1:
        return torch.zeros_like(x)
    w = min(w, T)
    pad = torch.zeros(N, w - 1, dtype=x.dtype, device=x.device)
    wnd = torch.cat([pad, x], dim=1).unfold(1, w, 1)  # [N, T, w]
    med = wnd.median(dim=-1).values
    mad = (wnd - med.unsqueeze(-1)).abs().median(dim=-1).values + 1e-6
    out = torch.clamp((x - med) / mad, -5.0, 5.0)
    out = torch.nan_to_num(out, nan=0.0, posinf=5.0, neginf=-5.0)
    # warm-up 期 (t < w-1) 输出 0
    warmup_mask = torch.arange(T, device=x.device) < (w - 1)
    out[:, warmup_mask] = 0.0
    return out


class FeatureEngine:
    """从本系统面板构建 [N, F, T] 特征张量 (65 特征, 深度复刻 AlphaMaster)"""

    def __init__(self, feature_names=None):
        self.feature_names = list(feature_names or FEATURE_NAMES)
        if not self.feature_names:
            raise ValueError("特征名列表为空")

    def compute(self, panel: dict, codes: list, dates: list) -> torch.Tensor:
        """计算特征张量 [N, F, T]

        panel: {code: DataFrame(index=日期, columns=open/high/low/close/volume/...)}
        codes: 股票代码列表 (N)
        dates: 日期列表 (T, 对齐后的统一日期轴)

        每个特征用本系统 evaluate_expression 在面板上求值 -> [日期, 股票] 面板,
        转置为 [N, T] 后逐特征 robust 归一化。单特征失败仅告警并零填充 (不中断训练)。
        """
        from lib.factor_engine import evaluate_expression

        N = len(codes)
        T = len(dates)
        F = len(self.feature_names)
        feat = torch.zeros(N, F, T, dtype=torch.float32)

        # 只计算已定义表达式的特征
        expr_of = {name: expr for name, expr in FEATURE_SPECS}
        for fi, fname in enumerate(self.feature_names):
            expr = expr_of.get(fname)
            if not expr:
                continue
            try:
                fdf = evaluate_expression(expr, panel)  # DataFrame(index=日期, columns=股票代码)
            except Exception as e:
                print(f"[RL] 特征 {fname} 计算失败 (零填充): {e}")
                continue
            if fdf is None or len(fdf) == 0:
                continue
            for ni, code in enumerate(codes):
                if code not in fdf.columns:
                    continue
                vals = fdf[code].reindex(dates).values
                feat[ni, fi, :] = torch.tensor(vals, dtype=torch.float32)

        # robust 归一化 (每个特征独立)
        for fi in range(F):
            feat[:, fi, :] = _robust_norm(feat[:, fi, :])

        return feat