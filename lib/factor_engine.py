# -*- coding: utf-8 -*-
# 因子计算引擎
"""
合并各 CASE 因子计算逻辑:
    - WorldQuant ts_* 算子 (来源: qinghua/day2_M.ipynb)
    - 因子预处理三件套 (来源: CASE-C/preprocessor.py)
    - IC/IR 评价 (来源: CASE-C/synthesizer.py)
    - 分层回测 (来源: CASE-C/layered_backtest.py)
    - 表达式安全解析 (用于因子构建页面)
"""

from __future__ import annotations
import math
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import numpy as np
import pandas as pd
import torch

# ML 模型落盘目录 (因子包复用: 其他页面加载模型直接预测, 无需重训)
ML_MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "factor_packages" / "models"


# ============================================================
# 一、WorldQuant ts_* 时序算子 (来源: qinghua/day2_M.ipynb)
# ============================================================

def ts_Delay(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """滞后 n 期"""
    return df.shift(n)


def ts_Mean(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期等权移动平均"""
    return df.rolling(n, min_periods=1).mean()


def _rolling_decay_weights_mean(df: pd.DataFrame, n: int, weights: np.ndarray) -> pd.DataFrame:
    """滚动"前缀权重"加权均值 (min_periods=1 预热, 窗口内任一NaN记NaN)

    语义与原 rolling.apply 版本完全一致 (口径不变, 仅提速):
      - 每个时点 t 的窗口为最近 min(t+1, n) 个观测 (按时间先后),
        权重取 weights 的前缀并按前缀和归一;
      - 窗口内存在 NaN 时结果记 NaN (np.dot 的 NaN 传播语义);
      - 预热区 (t < n-1) 用"前缀加权累计"计算, 全窗口区 (t >= n-1) 用卷积计算,
        避免逐窗口 Python 循环, 显著提升计算性能。

    参数:
        df:      DataFrame (index=日期, columns=股票代码)
        n:       窗口大小
        weights: 长度 n 的权重向量 (位置0对应窗口内最旧值)
    返回: 与 df 同形的加权均值 DataFrame
    """
    m, c = df.shape
    if m == 0 or c == 0:
        return df.copy()
    vals = df.to_numpy(dtype=float)
    valid = ~np.isnan(vals)
    vc = np.where(valid, vals, 0.0)          # NaN补0便于卷积
    weights = np.asarray(weights, dtype=float)
    prefix_sum = np.cumsum(weights)          # prefix_sum[t] = 前 t+1 个权重之和
    out = np.full_like(vals, np.nan, dtype=float)

    # 预热区 (t < n-1): 窗口 = 前 t+1 个观测, 权重 = weights[:t+1], 用前缀加权累计
    kmax = min(n - 1, m)
    if kmax > 0:
        # NaN 传播除法会产生 invalid 警告 (窗口全NaN时 num/prefix), 属预期行为, 抑制以免刷日志
        with np.errstate(invalid="ignore"):
            for t in range(kmax):
                win = vals[: t + 1, :]           # (t+1, c) 含NaN
                num = win.T @ weights[: t + 1]   # (c,), NaN传播语义与原np.dot一致
                out[t, :] = num / prefix_sum[t]

    # 全窗口区 (t >= n-1): 最近 n 个观测的加权和用卷积计算
    if m > n - 1:
        wrev = weights[::-1].copy()          # 反转后卷积: 第t位 = 截至t的n窗口加权和
        ones = np.ones(n)
        denom = prefix_sum[n - 1]
        for col in range(c):
            conv = np.convolve(vc[:, col], wrev)[:m]
            cnt = np.convolve(valid[:, col].astype(float), ones)[:m]
            with np.errstate(invalid="ignore"):
                seg = conv / denom
            # 窗口内任一 NaN -> NaN (与 rolling.apply 的 np.dot 传播一致)
            seg = np.where(cnt == n, seg, np.nan)
            out[n - 1:, col] = seg[n - 1:]
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def ts_Decay(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期线性衰减加权均值 (近期权重高)"""
    weights = np.arange(n, 0, -1, dtype=float) / n
    return _rolling_decay_weights_mean(df, n, weights)


def ts_DecayExp(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期非线性衰减均值 (权重取正态分位数)"""
    from scipy.stats import norm
    raw_w = np.array([norm.ppf((n - j) / n) if 0 < (n - j) / n < 1 else 0.0
                      for j in range(n)])
    weights = np.abs(raw_w)
    if weights.sum() == 0:
        return df.rolling(n, min_periods=1).mean()
    weights = weights / weights.sum()
    return _rolling_decay_weights_mean(df, n, weights)


def ts_Max(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动最大值"""
    return df.rolling(n, min_periods=1).max()


def ts_Min(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动最小值"""
    return df.rolling(n, min_periods=1).min()


def ts_Delta(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期差值"""
    return df - df.shift(n)


def ts_Stdev(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动标准差"""
    return df.rolling(n, min_periods=2).std()


def ts_Sum(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动求和"""
    return df.rolling(n, min_periods=1).sum()


def ts_Kurtosis(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动峰度"""
    return df.rolling(n, min_periods=4).kurt()


def ts_Skewness(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动偏度"""
    return df.rolling(n, min_periods=3).skew()


def ts_Median(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n 期滚动中位数"""
    return df.rolling(n, min_periods=1).median()


# ============================================================
# 二、截面算子 (来源: qinghua + 华泰规划)
# ============================================================

def cs_Rank(df: pd.DataFrame) -> pd.DataFrame:
    """截面排名 (0~1)"""
    return df.rank(axis=1, pct=True)


def cs_Demean(df: pd.DataFrame) -> pd.DataFrame:
    """截面去均值 (每行减去行均值, 用于IdioRet等特异质收益计算)"""
    return df.sub(df.mean(axis=1), axis=0)


# 兼容别名: cs_Mean 历史命名与语义不符(实际为去均值), 保留以兼容旧公式引用;
# 新公式请使用语义正确的 cs_Demean。
cs_Mean = cs_Demean


def cs_Zscore(df: pd.DataFrame) -> pd.DataFrame:
    """截面 Z-score 标准化"""
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)


def cs_TransNorm(df: pd.DataFrame) -> pd.DataFrame:
    """截面排名 -> 正态分位数变换"""
    from scipy.stats import norm
    ranked = df.rank(axis=1, pct=True)
    # 避免刚好 0 或 1 导致 norm.ppf 返回 inf
    ranked = ranked.clip(lower=0.001, upper=0.999)
    return ranked.map(lambda x: norm.ppf(x) if pd.notna(x) else np.nan)


def cs_Scale(df: pd.DataFrame) -> pd.DataFrame:
    """截面绝对和归一: 每行除以该行 |x| 之和 (对齐 QuantGP 原版 t_cs_scale)"""
    denom = df.abs().sum(axis=1).replace(0, np.nan)
    return df.div(denom, axis=0)


def cs_MinMaxScale(df: pd.DataFrame) -> pd.DataFrame:
    """截面 min-max 缩放到 [0,1] (对齐 AlphaMaster CS_SCALE; RL 专用, 不改变原 cs_Scale)"""
    mn = df.min(axis=1)
    mx = df.max(axis=1)
    span = mx - mn
    out = df.sub(mn, axis=0)
    out = out.div(span.replace(0, np.nan), axis=0)
    out = out.where(span != 0, 0.5)
    return out


def cs_Winsorize(df: pd.DataFrame) -> pd.DataFrame:
    """截面分位去极值: 每行裁剪到 [5%, 95%] (对齐 QuantGP 原版 t_cs_winsorize)"""
    lower = df.quantile(0.05, axis=1)
    upper = df.quantile(0.95, axis=1)
    return df.clip(lower=lower, upper=upper, axis=0)


# ============================================================
# 二-bis-bis、时序标准化工具 (technical_ts 类因子评价/合成共用)
# ============================================================
# 量纲不可比因子(价格水平/累积量纲/绝对波动)在截面排序前需先对自身历史做
# 滚动分位, 转成[0,1]的"自身历史分位"再走截面管线; 路由层(routes/factor.py)
# 与批量评估(lib/factor_evaluator.py)统一从这里导入, 保证口径一致。

def ts_rank_normalize(fv: pd.DataFrame, window: int) -> pd.DataFrame:
    """时序标准化: 因子值 -> 自身近N日历史的滚动分位[0,1]
    含当日(当日收盘信息可知, 无前视); min_periods 取窗口一半且不低于20日"""
    return fv.rolling(window, min_periods=max(20, window // 2)).rank(pct=True)


def resolve_ts_window(requested, n_days: int, rebal_period: int = 21) -> int:
    """时序标准化窗口自适应

    问题: 默认窗口250日要求数据长度 > 250 + 调仓周期才能产生调仓点; 股票池数据
    不足(如仅200+交易日)时会得到空IC/多因子"无有效截面样本"。
    解决: 当请求窗口超过可用数据能容纳的可行上限时, 自动降到可行值(保证至少
    若干调仓点), 评价结果返回实际使用窗口供前端展示。
    """
    req = int(requested or 250)
    if req <= 0:
        req = 250
    # 可行上限: 窗口须 < n_days - rebal_period*k (k为期望调仓点数), 保守取4
    max_ok = max(20, n_days - rebal_period * 4)
    return min(req, max_ok)


# ============================================================
# 二-bis、基础计算函数 (非Talib, 封装pandas操作为面板函数)
# ============================================================
# 以下函数统一接受 DataFrame(index=日期, columns=股票代码), 返回同形状DataFrame

def ts_PctChange(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期百分比变化率 (收益率)"""
    return df.pct_change(n)


def ts_ROC(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期变化率 ROC = (当前价/N期前价 - 1) * 100"""
    return df.pct_change(n) * 100


def ts_Bias(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期乖离率 = (价格 - MA) / MA"""
    ma = df.rolling(n, min_periods=1).mean()
    return (df - ma) / ma.replace(0, np.nan)


def ts_Shift(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """平移n期 (等价于ts_Delay, 兼容不同写法)"""
    return df.shift(n)


def ts_ShiftZero(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """左侧补 0 的平移 (与 RL StackVM _ts_delay 一致, 只将前 n 行置 0)"""
    out = df.shift(n)
    if n > 0 and len(out) > 0:
        out.iloc[:n] = 0.0
    return out


def ts_RobustNorm(df: pd.DataFrame, w: int = 200) -> pd.DataFrame:
    """RL 特征 robust 归一化 (median/MAD, clip ±5, warm-up 期输出 0)

    与 lib/factor_rl/features.py 的 _robust_norm 使用完全相同的 torch 实现,
    从而保证 RL 训练时的特征值与最终表达式求值结果一致。
    """
    if df is None or len(df) == 0:
        return df.copy()
    arr = df.to_numpy(dtype=np.float32)
    T, N = arr.shape
    w = int(max(1, min(w, T)))
    x = torch.tensor(arr.T, dtype=torch.float32)  # [N, T]
    if T <= 1:
        return pd.DataFrame(np.zeros_like(arr), index=df.index, columns=df.columns)
    pad = torch.zeros(N, w - 1, dtype=x.dtype, device=x.device)
    wnd = torch.cat([pad, x], dim=1).unfold(1, w, 1)  # [N, T, w]
    med = wnd.median(dim=-1).values
    mad = (wnd - med.unsqueeze(-1)).abs().median(dim=-1).values + 1e-6
    out = torch.clamp((x - med) / mad, -5.0, 5.0)
    out = torch.nan_to_num(out, nan=0.0, posinf=5.0, neginf=-5.0)
    warmup_mask = torch.arange(T, device=x.device) < (w - 1)
    out[:, warmup_mask] = 0.0
    return pd.DataFrame(out.numpy().T, index=df.index, columns=df.columns)


def ts_OutputNorm(df: pd.DataFrame, w: int = 500) -> pd.DataFrame:
    """RL StackVM 输出标准化 (与 lib/factor_rl/vm.py _normalize_output 完全一致)

    - N>1: 截面 zscore (每时间步跨股票), clip [-3,3]
    - N=1: 滚动时序 zscore (窗口 500, 因果), warm-up 期输出 0
    """
    if df is None or len(df) == 0:
        return df.copy()
    arr = df.to_numpy(dtype=np.float32)
    T, N = arr.shape
    x = torch.tensor(arr.T, dtype=torch.float32)  # [N, T]
    if x.std() < 1e-6:
        return df.copy()
    if N > 1:
        cs_mean = x.mean(dim=0, keepdim=True)
        cs_std = x.std(dim=0, keepdim=True).clamp_min(1e-8)  # 与原版一致: unbiased=True
        out = torch.clamp((x - cs_mean) / cs_std, -3.0, 3.0)
    else:
        if T < w:
            cnt = torch.arange(1, T + 1, dtype=x.dtype, device=x.device).view(1, T)
            mean = x.cumsum(dim=1) / cnt
            sq = (x * x).cumsum(dim=1) / cnt
            var = (sq - mean * mean).clamp_min(0.0)
            std = var.sqrt().clamp_min(1e-8)
            out = torch.clamp((x - mean) / std, -3.0, 3.0)
        else:
            pad = torch.zeros(N, w - 1, dtype=x.dtype, device=x.device)
            padded = torch.cat([pad, x], dim=1)
            windows = padded.unfold(1, w, 1)
            ts_mean = windows.mean(dim=2)
            ts_std = windows.std(dim=2).clamp_min(1e-8)  # 与原版一致: unbiased=True
            out = (x - ts_mean) / ts_std
            warmup_mask = torch.arange(T, device=x.device) < (w - 1)
            out[:, warmup_mask] = 0.0
            out = torch.clamp(out, -3.0, 3.0)
    return pd.DataFrame(out.numpy().T, index=df.index, columns=df.columns)


def _rl_to_tensor(df: pd.DataFrame) -> torch.Tensor:
    """DataFrame [T,N] -> Tensor [N,T] float32 (与 RL FeatureEngine 一致)"""
    return torch.tensor(df.to_numpy(dtype=np.float32).T, dtype=torch.float32)


def _rl_to_df(x: torch.Tensor, df: pd.DataFrame) -> pd.DataFrame:
    """Tensor [N,T] -> DataFrame [T,N]"""
    return pd.DataFrame(x.numpy().T, index=df.index, columns=df.columns)


def _rl_unary(df: pd.DataFrame, fn_name: str, *args):
    """调用 RL StackVM 的一元算子并转回 DataFrame"""
    from lib.factor_rl import ops as rl_ops
    fn = getattr(rl_ops, fn_name)
    return _rl_to_df(fn(_rl_to_tensor(df), *args), df)


def ts_RLMean(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_mean", n)


def ts_RLStdev(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_std", n)


def ts_RLSum(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_sum", n)


def ts_RLMax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_max", n)


def ts_RLMin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_min", n)


def ts_RLRank(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_rank", n)


def ts_RLQuantile(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_quantile", n)


def ts_RLZscore(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_zscore", n)


def ts_RLSkew(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_skew", n)


def ts_RLArgMax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_argmax", n)


def ts_RLArgMin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_argmin", n)


def ts_RLProduct(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_product", n)


def ts_RLDecayLinear(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_decay_linear", n)


def ts_RLDecayExp(df: pd.DataFrame, n: int, alpha: float = 0.5) -> pd.DataFrame:
    return _rl_unary(df, "_ts_decay_exp", n, alpha)


def ts_RLScale(df: pd.DataFrame) -> pd.DataFrame:
    return _rl_unary(df, "_ts_scale")


def ts_RLLog(df: pd.DataFrame) -> pd.DataFrame:
    return _rl_unary(df, "_ts_log")


def ts_RLDelta(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return _rl_unary(df, "_ts_delta", n)


def ts_RLWMA(df: pd.DataFrame) -> pd.DataFrame:
    return _rl_unary(df, "_op_wma")


def ts_RLEMA(df: pd.DataFrame, span: int) -> pd.DataFrame:
    return _rl_unary(df, "_ema_simple", span)


def ts_RLJump(df: pd.DataFrame) -> pd.DataFrame:
    return _rl_unary(df, "op_jump")


def ts_RLCorr(df1: pd.DataFrame, df2: pd.DataFrame, n: int) -> pd.DataFrame:
    from lib.factor_rl import ops as rl_ops
    return _rl_to_df(rl_ops._ts_corr(_rl_to_tensor(df1), _rl_to_tensor(df2), n), df1)


def ts_RLCov(df1: pd.DataFrame, df2: pd.DataFrame, n: int) -> pd.DataFrame:
    from lib.factor_rl import ops as rl_ops
    return _rl_to_df(rl_ops._ts_covariance(_rl_to_tensor(df1), _rl_to_tensor(df2), n), df1)


def cs_RankRL(df: pd.DataFrame) -> pd.DataFrame:
    from lib.factor_rl import ops as rl_ops
    return _rl_to_df(rl_ops.op_cs_rank(_rl_to_tensor(df)), df)


def cs_ZscoreRL(df: pd.DataFrame) -> pd.DataFrame:
    from lib.factor_rl import ops as rl_ops
    return _rl_to_df(rl_ops.op_cs_zscore(_rl_to_tensor(df)), df)


def cs_TransNormRL(df: pd.DataFrame) -> pd.DataFrame:
    from lib.factor_rl import ops as rl_ops
    return _rl_to_df(rl_ops.op_cs_transnorm(_rl_to_tensor(df)), df)


def ts_Winsorize(df: pd.DataFrame, w: int = 20, lo: float = 0.05, hi: float = 0.95) -> pd.DataFrame:
    """时序滚动分位裁剪 (对齐 AlphaMaster WINSORIZE, 与 RL StackVM 一致)"""
    if df is None or len(df) == 0:
        return df.copy()
    arr = df.to_numpy(dtype=np.float32)
    T, N = arr.shape
    w = int(max(1, min(w, T)))
    if T <= 1:
        return df.copy()
    x = torch.tensor(arr.T, dtype=torch.float32)  # [N, T]
    pad = torch.zeros(N, w - 1, dtype=x.dtype, device=x.device)
    wnd = torch.cat([pad, x], dim=1).unfold(1, w, 1).float()  # [N, T, w]
    lower = torch.quantile(wnd, lo, dim=-1).to(x.dtype)
    upper = torch.quantile(wnd, hi, dim=-1).to(x.dtype)
    span = upper - lower
    safe_lower = torch.where(span < 1e-9, x, lower)
    safe_upper = torch.where(span < 1e-9, x, upper)
    out = torch.clamp(x, safe_lower, safe_upper)
    out = torch.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return pd.DataFrame(out.numpy().T, index=df.index, columns=df.columns)


def ts_CumReturn(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期累计收益 = 价格/前n期价格 - 1"""
    return df / df.shift(n) - 1


def ts_VolRatio(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期量比 = 当前期 / n期均值"""
    return df / df.rolling(n, min_periods=1).mean().replace(0, np.nan)


def ts_Amplitude(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期振幅 = (最高-最低) / 均价"""
    h = high_df.rolling(n, min_periods=1).max()
    l = low_df.rolling(n, min_periods=1).min()
    c = close_df.rolling(n, min_periods=1).mean()
    return (h - l) / c.replace(0, np.nan)


def ts_PricePosition(close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期区间位置 = (Close - min(Close,n)) / (max(Close,n) - min(Close,n))
    对应 price_position 参数化基类 (见 AlphaMaster特征算子与因子库映射方案.md 3.4)"""
    mn = close_df.rolling(n, min_periods=1).min()
    mx = close_df.rolling(n, min_periods=1).max()
    span = (mx - mn).replace(0, np.nan)
    return (close_df - mn) / span


def ts_Corr(df1: pd.DataFrame, df2: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期滚动相关系数"""
    return df1.rolling(n, min_periods=2).corr(df2)


def ts_BETA(close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """n期Beta系数: 个股收益率对市场(截面均值收益率)的滚动beta

    注: 本面板无独立市场指数, 以当日全部股票收益率的截面均值作为市场代理。
    """
    ret = close_df.pct_change()
    mkt = ret.mean(axis=1)
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        s = ret[code]
        var_mkt = mkt.rolling(n, min_periods=2).var().replace(0, np.nan)
        result[code] = s.rolling(n, min_periods=2).cov(mkt) / var_mkt
    return result


def ts_CORREL(close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """n期相关系数: 个股收益率对市场(截面均值收益率)的滚动相关系数

    注: 以当日全部股票收益率的截面均值作为市场代理。
    """
    ret = close_df.pct_change()
    mkt = ret.mean(axis=1)
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        result[code] = ret[code].rolling(n, min_periods=2).corr(mkt)
    return result


def ts_HistVol(close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期历史波动率(年化) = std(日收益率, n) * sqrt(252)"""
    returns = close_df.pct_change()
    return returns.rolling(n, min_periods=2).std() * np.sqrt(252)


# ============================================================
# AlphaMaster 映射补充波动率估计量算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.3.2)
# 语义复刻 AlphaMaster features.py, 适配本系统 DataFrame 面板
# ============================================================

def ts_GKVol(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
             close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Garman-Klass 波动率估计量: 0.5*(ln(H/L))^2 - (2ln2-1)*(ln(C/O))^2, 滚动均值取sqrt"""
    ln2 = np.log(2.0)
    hl = np.log(high_df / low_df.replace(0, np.nan)) ** 2
    co = np.log(close_df / open_df.replace(0, np.nan)) ** 2
    gk_bar = (0.5 * hl - (2 * ln2 - 1) * co).clip(lower=0)
    gk_mean = gk_bar.rolling(n, min_periods=1).mean()
    return np.log1p(gk_mean.clip(lower=0).apply(np.sqrt))


def ts_ParkinsonVol(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Parkinson 波动率估计量: (1/(4ln2))*(ln(H/L))^2, 滚动均值取sqrt"""
    ln2 = np.log(2.0)
    pk_bar = (1.0 / (4 * ln2)) * (np.log(high_df / low_df.replace(0, np.nan)) ** 2)
    pk_mean = pk_bar.rolling(n, min_periods=1).mean()
    return np.log1p(pk_mean.clip(lower=0).apply(np.sqrt))


def ts_YangZhangVol(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
                    close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Yang-Zhang 波动率估计量(等权简化): (overnight + open + RS)/3, 滚动均值取sqrt"""
    pc = close_df.shift(1).fillna(close_df)
    overnight = np.log(open_df / pc.replace(0, np.nan)) ** 2
    open_bar = np.log(open_df / close_df.replace(0, np.nan)) ** 2
    rs_bar = (np.log(high_df / close_df.replace(0, np.nan)) * np.log(high_df / open_df.replace(0, np.nan))
              + np.log(low_df / close_df.replace(0, np.nan)) * np.log(low_df / open_df.replace(0, np.nan)))
    yz_bar = (overnight + open_bar + rs_bar) / 3.0
    yz_mean = yz_bar.rolling(n, min_periods=1).mean()
    return np.log1p(yz_mean.clip(lower=0).apply(np.sqrt))


def ts_RSVol(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
             close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Rogers-Satchell 波动率估计量: ln(H/C)*ln(H/O)+ln(L/C)*ln(L/O), 滚动均值取sqrt"""
    rs_bar = (np.log(high_df / close_df.replace(0, np.nan)) * np.log(high_df / open_df.replace(0, np.nan))
              + np.log(low_df / close_df.replace(0, np.nan)) * np.log(low_df / open_df.replace(0, np.nan)))
    rs_mean = rs_bar.rolling(n, min_periods=1).mean()
    return np.log1p(rs_mean.clip(lower=0).apply(np.sqrt))


def ts_TrendStrength(close_df: pd.DataFrame, n: int = 50) -> pd.DataFrame:
    """趋势强度 = SLOPE_n * R^2 (线性回归斜率按价位归一, 乘拟合优度)"""
    def _slope_r2(w):
        if len(w) < 2:
            return np.nan
        x = np.arange(len(w), dtype=float)
        xm = x.mean()
        slope = ((w - w.mean()) * (x - xm)).sum() / ((x - xm) ** 2).sum()
        pred = w.mean() + slope * (x - xm)
        ss_res = ((w - pred) ** 2).sum()
        ss_tot = ((w - w.mean()) ** 2).sum()
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
        return slope / (w.mean() + 1e-9) * max(0.0, min(1.0, r2))
    return close_df.rolling(n, min_periods=2).apply(_slope_r2, raw=True)


def ts_Trix(close_df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    """TRIX: 三重EMA平滑后的单步变化率"""
    e1 = close_df.ewm(span=n, adjust=False).mean()
    e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean()
    prev = e3.shift(1).fillna(e3)
    return (e3 - prev) / (prev.abs().replace(0, np.nan))


def ts_Autocorr(close_df: pd.DataFrame, n: int = 20, lag: int = 1) -> pd.DataFrame:
    """n期收益的lag阶自相关"""
    ret = close_df.pct_change()
    return ret.rolling(n, min_periods=2).apply(
        lambda w: (np.corrcoef(w[:-lag], w[lag:])[0, 1] if len(w) > lag else np.nan), raw=True)


def ts_TypicalDev(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
                  close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """典型价(H+L+C)/3 偏离其MA_n"""
    typical = (high_df + low_df + close_df) / 3.0
    ma = typical.rolling(n, min_periods=1).mean()
    return (typical - ma) / ma.replace(0, np.nan)


def ts_DmiDiff(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
               n: int = 14) -> pd.DataFrame:
    """DMI差值 = DI+ - DI- (趋势方向)"""
    prev_h = high_df.shift(1).fillna(high_df)
    prev_l = low_df.shift(1).fillna(low_df)
    prev_c = close_df.shift(1).fillna(close_df)
    dm_pos = (high_df - prev_h).clip(lower=0)
    dm_neg = (prev_l - low_df).clip(lower=0)
    # 逐列计算真实波幅 TR = max(H-L, |H-prevC|, |L-prevC|)
    tr = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        h = high_df[code].values
        l = low_df[code].values
        c = close_df[code].values
        pc = prev_c[code].values
        tr[code] = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr_mean = tr.rolling(n, min_periods=1).mean().replace(0, np.nan)
    di_pos = dm_pos.rolling(n, min_periods=1).mean() / tr_mean
    di_neg = dm_neg.rolling(n, min_periods=1).mean() / tr_mean
    return (di_pos - di_neg).clip(-1, 1)


def ts_AmihudIlliq(close_df: pd.DataFrame, volume_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Amihud 非流动性: mean(|ret|/volume, n)"""
    ret = close_df.pct_change().abs()
    illiq = ret / volume_df.replace(0, np.nan)
    return np.log1p(illiq.rolling(n, min_periods=1).mean().clip(lower=0))


def ts_KyleLambda(close_df: pd.DataFrame, volume_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Kyle lambda 近似: cov(|ret|, sign(ret)*volume) / var(sign(ret)*volume)"""
    ret = close_df.pct_change()
    abs_ret = ret.abs()
    signed_vol = np.sign(ret) * volume_df
    def _kyle(w_abs, w_sv):
        if len(w_abs) < 2:
            return np.nan
        cov = np.cov(w_abs, w_sv)[0, 1]
        var = np.var(w_sv)
        return cov / var if var > 1e-9 else np.nan
    # 用 numpy 滚动窗口, 避免 rolling.apply 的 index 对齐问题
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        a = abs_ret[code].values
        s = signed_vol[code].values
        out = np.full(len(a), np.nan)
        for i in range(n - 1, len(a)):
            w_abs = a[i - n + 1:i + 1]
            w_sv = s[i - n + 1:i + 1]
            out[i] = _kyle(w_abs, w_sv)
        result[code] = out
    return result


def ts_CMF(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
           volume_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Chaikin Money Flow: sum(MFV, n)/sum(volume, n), MFV=((C-L)-(H-C))/(H-L)*volume"""
    hl = (high_df - low_df).replace(0, np.nan)
    mf_mul = ((close_df - low_df) - (high_df - close_df)) / hl
    mfv = mf_mul * volume_df
    cmf = mfv.rolling(n, min_periods=1).sum() / volume_df.rolling(n, min_periods=1).sum().replace(0, np.nan)
    return cmf.clip(-1, 1)


def ts_ADLineSlope(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
                   close_df: pd.DataFrame, volume_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """A/D line 斜率: cumsum(MFV) 的 n 期线性回归斜率"""
    hl = (high_df - low_df).replace(0, np.nan)
    mf_mul = ((close_df - low_df) - (high_df - close_df)) / hl
    ad_line = (mf_mul * volume_df).cumsum()
    def _slope(w):
        if len(w) < 2:
            return np.nan
        x = np.arange(len(w), dtype=float)
        return ((w - w.mean()) * (x - x.mean())).sum() / ((x - x.mean()) ** 2).sum()
    return ad_line.rolling(n, min_periods=2).apply(_slope, raw=True)


def ts_Hurst(close_df: pd.DataFrame, n: int = 50) -> pd.DataFrame:
    """Hurst 指数 (R/S法简化): log(R/S)/log(n), 映射到[-1,1]"""
    ret = close_df.pct_change()
    def _hurst(w):
        if len(w) < 2:
            return np.nan
        centered = w - w.mean()
        cumdev = np.cumsum(centered)
        R = cumdev.max() - cumdev.min()
        S = np.std(w)
        if R < 1e-9 or S < 1e-9:
            return 0.0
        h = np.log(R / S) / np.log(len(w))
        return max(-1.0, min(1.0, 2 * h - 1))
    return ret.rolling(n, min_periods=2).apply(_hurst, raw=True)


def ts_FractalDim(close_df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """分形维: (max-min)/(mean_abs_diff*sqrt(n)), 映射到[-1,1]"""
    def _fd(w):
        if len(w) < 2:
            return np.nan
        rng = w.max() - w.min()
        mad = np.mean(np.abs(np.diff(w)))
        frac = rng / (mad * np.sqrt(len(w)) + 1e-9)
        return max(-1.0, min(1.0, frac / 3.0 * 2.0 - 1.0))
    return close_df.rolling(n, min_periods=2).apply(_fd, raw=True)


def ts_RetEntropy(close_df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """收益符号的n期滚动香农熵(三分箱: 正/负/零), 归一化到[0,1]"""
    ret = close_df.pct_change()
    def _entropy(w):
        if len(w) < 2:
            return np.nan
        p_pos = np.mean(w > 0)
        p_neg = np.mean(w < 0)
        p_zero = np.mean(w == 0)
        h = 0.0
        for p in (p_pos, p_neg, p_zero):
            if p > 0:
                h -= p * np.log(p)
        return max(0.0, min(1.0, h / np.log(3)))
    return ret.rolling(n, min_periods=2).apply(_entropy, raw=True)


def ts_KeltnerPos(close_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
                  n: int = 20) -> pd.DataFrame:
    """Keltner 通道位置: (close-lower)/(upper-lower), mid=EMA20, range=EMA20(ATR14)"""
    mid = close_df.ewm(span=n, adjust=False).mean()
    prev_c = close_df.shift(1).fillna(close_df)
    # 逐列计算真实波幅 TR = max(H-L, |H-prevC|, |L-prevC|)
    tr = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        h = high_df[code].values
        l = low_df[code].values
        c = close_df[code].values
        pc = prev_c[code].values
        tr[code] = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = tr.ewm(span=14, adjust=False).mean()
    rng = atr.ewm(span=n, adjust=False).mean()
    upper = mid + 2 * rng
    lower = mid - 2 * rng
    return ((close_df - lower) / (upper - lower).replace(0, np.nan)).clip(0, 1)


def ts_IchimokuKijun(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int = 26) -> pd.DataFrame:
    """close 相对 Kijun-sen(26期高低价中值) 偏离"""
    kijun = (high_df.rolling(n, min_periods=1).max() + low_df.rolling(n, min_periods=1).min()) / 2.0
    return (high_df - kijun) / kijun.replace(0, np.nan)


def ts_IchimokuTenkan(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """close 相对 Tenkan-sen(9期高低价中值) 偏离"""
    tenkan = (high_df.rolling(n, min_periods=1).max() + low_df.rolling(n, min_periods=1).min()) / 2.0
    return (high_df - tenkan) / tenkan.replace(0, np.nan)


def ts_SuperTrend(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
                  n: int = 14) -> pd.DataFrame:
    """SuperTrend 方向标志 {-1, +1} (简化递推)"""
    prev_c = close_df.shift(1).fillna(close_df)
    # 逐列计算真实波幅 TR = max(H-L, |H-prevC|, |L-prevC|)
    tr = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        h = high_df[code].values
        l = low_df[code].values
        c = close_df[code].values
        pc = prev_c[code].values
        tr[code] = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = tr.rolling(n, min_periods=1).mean()
    mid = (high_df + low_df) / 2.0
    upper = mid + 1.5 * atr
    lower = mid - 1.5 * atr
    # 用 numpy 数组实现递推, 避免 Series 对齐问题
    close_arr = close_df.values
    upper_arr = upper.values
    lower_arr = lower.values
    direction = np.zeros_like(close_arr, dtype=float)
    prev_upper = upper_arr[0]
    prev_lower = lower_arr[0]
    for t in range(1, len(close_arr)):
        flip_up = close_arr[t] > prev_upper
        flip_down = close_arr[t] < prev_lower
        new_dir = direction[t - 1].copy()
        new_dir[flip_up] = 1.0
        new_dir[flip_down] = -1.0
        direction[t] = new_dir
        prev_upper = upper_arr[t]
        prev_lower = lower_arr[t]
    return pd.DataFrame(direction, index=close_df.index, columns=close_df.columns)


def ts_BarraMomentum(close_df: pd.DataFrame, window: int = 504, skip: int = 21) -> pd.DataFrame:
    """Barra动量因子: 剔除最近skip日后, 近window日加权累计超额收益

    Barra CNE5 口径: 动量 = Σ w_i × 超额收益_{t-i} (i 覆盖 window 日, 剔除最近 skip 日)
    超额收益 = 个股日收益 - 市场日收益(截面均值代理, 与 ts_BETA 同口径)
    权重: 几何衰减(半衰期约 window/4), 越近期权重越大; 剔除最近 skip 日避免短期反转污染
    实现: 先对超额收益 shift(skip) 剔除近期(用 t-skip 之前的数据), 再逐股做窗口卷积加权和
    """
    ret = close_df.pct_change()
    mkt = ret.mean(axis=1)
    excess = ret.sub(mkt, axis=0)
    # 权重: 索引0=最旧(权重最小) ... 索引window-1=最新(权重最大), 半衰期约 window/4
    age = np.arange(window, 0, -1, dtype=float)
    w = 0.5 ** (age / max(window / 4.0, 21.0))
    w = w / w.sum()
    w_rev = w[::-1]  # 反转后与卷积对齐: 最新数据乘最大权重
    # 剔除最近 skip 日: shift(skip) 使 t 日用的是 t-skip 及更早的超额收益
    shifted = excess.shift(skip).fillna(0.0)
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for c in close_df.columns:
        s = shifted[c].values
        full = np.convolve(s, w_rev, mode="full")[:len(s)]
        result[c] = full
    return result


def ts_RESVOL(close_df: pd.DataFrame, window: int = 250) -> pd.DataFrame:
    """Barra残差波动率: Beta(市场=截面均值)回归残差收益的年化标准差

    Barra CNE5 口径: 残差波动 = std(个股收益 - beta×市场收益, 近window日) × sqrt(252)
    复用 ts_BETA 计算 beta, 与 BARRA_BETA 同口径; 残差越大说明风格之外的个股特质波动越大
    """
    ret = close_df.pct_change()
    mkt = ret.mean(axis=1)
    beta = ts_BETA(close_df, window)
    resid = ret.sub(beta.mul(mkt, axis=0), axis=0)
    return resid.rolling(window, min_periods=2).std() * np.sqrt(252)


def ts_ChanTopFractal(high_df: pd.DataFrame, low_df: pd.DataFrame) -> pd.DataFrame:
    """缠论顶分型: 当前K线高点高于两侧且低点高于两侧 (0/1)

    确认日对齐: 顶分型需右侧K线(未来一根)确认, 信号日对齐到确认日(T+1),
    即第T日的信号用的是T-1日的分型(由T日K线确认), 避免未来函数。
    """
    top = (high_df > high_df.shift(1)) & (high_df > high_df.shift(-1)) & \
          (low_df > low_df.shift(1)) & (low_df > low_df.shift(-1))
    return top.shift(1).astype(float)


def ts_ChanBottomFractal(high_df: pd.DataFrame, low_df: pd.DataFrame) -> pd.DataFrame:
    """缠论底分型: 当前K线低点低于两侧且高点低于两侧 (0/1)

    确认日对齐: 与 ts_ChanTopFractal 同, 信号日对齐到确认日(T+1), 避免未来函数。
    """
    bottom = (low_df < low_df.shift(1)) & (low_df < low_df.shift(-1)) & \
             (high_df < high_df.shift(1)) & (high_df < high_df.shift(-1))
    return bottom.shift(1).astype(float)


def ts_ChanStroke(high_df: pd.DataFrame, low_df: pd.DataFrame) -> pd.DataFrame:
    """缠论笔方向: 顶底分型交替、间隔>=4根K线、同型保留极值, 输出 -1/0/+1

    简化约定(与计划一致):
      - 不做K线包含合并(仅简单OHLC比较)
      - 分型已做确认日对齐(T+1), 无未来函数
      - 输出 = 最近已确认分型的指向: bottom分型后为上升笔(+1), top分型后为下降笔(-1), 尚无分型为0
    """
    top_raw = (high_df > high_df.shift(1)) & (high_df > high_df.shift(-1)) & \
              (low_df > low_df.shift(1)) & (low_df > low_df.shift(-1))
    bot_raw = (low_df < low_df.shift(1)) & (low_df < low_df.shift(-1)) & \
              (high_df < high_df.shift(1)) & (high_df < high_df.shift(-1))
    top_c = top_raw.shift(1).fillna(False).astype(bool)
    bot_c = bot_raw.shift(1).fillna(False).astype(bool)
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values
        l = low_df[code].values
        t = top_c[code].values
        b = bot_c[code].values
        n = len(h)
        out = np.zeros(n)
        pivots = []          # 已确认的交替分型: (type, idx)
        pending = None       # 当前同型候选: (type, idx, price)
        for i in range(n):
            # 处理分型候选(同型取更极端: 顶取更高, 底取更低)
            if t[i]:
                if pending is not None and pending[0] == 'top':
                    if h[i] > pending[2]:
                        pending = ('top', i, h[i])
                else:
                    pending = ('top', i, h[i])
            if b[i]:
                if pending is not None and pending[0] == 'bottom':
                    if l[i] < pending[2]:
                        pending = ('bottom', i, l[i])
                else:
                    pending = ('bottom', i, l[i])
            # 与最后已确认分型类型不同且间隔>=4根时确认新分型
            if pending is not None:
                ptype, pidx, _ = pending
                if not pivots:
                    pivots.append((ptype, pidx))
                    pending = None
                else:
                    last_type, last_idx = pivots[-1]
                    if ptype != last_type and pidx - last_idx >= 4:
                        pivots.append((ptype, pidx))
                        pending = None
            # 当日笔方向: 由最近确认分型决定
            if pivots:
                out[i] = 1.0 if pivots[-1][0] == 'bottom' else -1.0
        result[code] = out
    return result


def ts_DragonDayChange(close_df: pd.DataFrame) -> pd.DataFrame:
    """龙头涨幅分: 当日涨幅分段打分 (来源: dragon_strategy/dragon_picker.py calc_dragon_score)

    涨幅 5%-9% 线性加权(5%->0.5, 8%->0.8, 9%->0.9, 封顶1.0); >9% 减分(接近涨停难买, 记 0.5)
    首日(无前收)为 NaN, 无打分
    """
    chg = close_df.pct_change()
    score = np.where(chg > 0.09, 0.5, np.clip(chg * 10.0, 0.0, 1.0))
    return pd.DataFrame(score, index=close_df.index, columns=close_df.columns)


def ts_Log(df: pd.DataFrame) -> pd.DataFrame:
    """自然对数 (对齐 GPU t_ts_Log: |x|<=EPS 置 NaN, 负值取绝对值后求对数,
    避免对 0/负值求 log 产生 invalid 警告与 NaN 扩散)"""
    EPS = 1e-12
    return np.log(np.abs(df.where(df.abs() > EPS)))


def ts_Count(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期滚动非空计数"""
    return df.rolling(n, min_periods=1).count()


def ts_Rank(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期滚动排名(0~1)"""
    return df.rolling(n, min_periods=2).rank(pct=True)


def ts_Cov(df1: pd.DataFrame, df2: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期滚动协方差"""
    return df1.rolling(n, min_periods=2).cov(df2)


def ts_Quantile(df: pd.DataFrame, n: int, q: float = 0.5) -> pd.DataFrame:
    """n期滚动分位数"""
    return df.rolling(n, min_periods=2).quantile(q)


def ts_Identity(df: pd.DataFrame) -> pd.DataFrame:
    """恒等变换(原样返回字段), 用于把 Open/High/Low/Close 等基础行情字段注册为可实例化的基类"""
    return df


# ============================================================
# QuantGP 复刻缺失算子补充 (对应原版 GPU_SAFE_PANEL_FUNCTIONS)
# 语义对齐 third_party/QuantGplearn/QuantGplearn/torch_functions.py 的同名算子,
# 实现风格与本系统既有 ts_* 算子完全一致 (DataFrame(index=日期, columns=股票) + rolling + min_periods 预热);
# 均为纯算子, 不进入 BASE_OPERATOR_MAP, 不新增基类记录与 factor_type 分类。
# ============================================================

def ts_ZScore(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期滚动Z-score标准化 = (x - MA) / STD (对应原版 ts_zscore)"""
    mean = df.rolling(n, min_periods=1).mean()
    std = df.rolling(n, min_periods=2).std().replace(0, np.nan)
    return df.sub(mean).div(std)


def ts_Freq(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期窗口内与当前值相等的个数 (对应原版 ts_freq)"""
    def _cnt(w):
        if len(w) == 0 or pd.isna(w[-1]):
            return np.nan
        return float(np.sum(w == w[-1]))
    return df.rolling(n, min_periods=1).apply(_cnt, raw=True)


def ts_CDLBodyM(open_df: pd.DataFrame, close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期阳线占比 = 阳线数 / (阳线+阴线)数 (对应原版 ts_cdlbodym)"""
    body = close_df - open_df
    up = (body > 0).astype(float)
    down = (body < 0).astype(float)
    num = up.rolling(n, min_periods=1).sum()
    den = (up + down).rolling(n, min_periods=1).sum().replace(0, np.nan)
    return num / den


def ts_BarBS(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期外扩K线占比: 高点抬升且低点下移的K线 / (外扩+内敛) (对应原版 ts_bar_bs)"""
    hd = high_df - high_df.shift(1)
    ld = low_df - low_df.shift(1)
    big = ((hd > 0) & (ld < 0)).astype(float)
    small = ((hd < 0) & (ld > 0)).astype(float)
    num = big.rolling(n, min_periods=1).sum()
    den = (big + small).rolling(n, min_periods=1).sum().replace(0, np.nan)
    return num / den


def ts_AROON(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期Aroon方向强度 = (最高价位置-最低价位置)/n, 位置为窗口内0起索引 (对应原版 ts_aroon)"""
    def _pos_hi(w):
        if len(w) == 0:
            return np.nan
        return float(np.argmax(np.where(np.isfinite(w), w, -np.inf)))
    def _pos_lo(w):
        if len(w) == 0:
            return np.nan
        return float(np.argmin(np.where(np.isfinite(w), w, np.inf)))
    hp = high_df.rolling(n, min_periods=1).apply(_pos_hi, raw=True)
    lp = low_df.rolling(n, min_periods=1).apply(_pos_lo, raw=True)
    return (hp - lp) / float(max(n, 1))


def ts_BOPR(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
            close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期力量平衡均值 = mean((Close-Open)/(High-Low), n) (对应原版 ts_bopr)"""
    span = (high_df - low_df).replace(0, np.nan)
    bop = (close_df - open_df) / span
    return bop.rolling(n, min_periods=1).mean()


def ts_OneOlsK(x_df: pd.DataFrame, y_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期一元OLS回归斜率 = (nΣxy-ΣxΣy) / (nΣx²-(Σx)²), n取窗口内有效样本数 (对应原版 ts_one_ols_k)"""
    sx = x_df.rolling(n, min_periods=1).sum()
    sy = y_df.rolling(n, min_periods=1).sum()
    sxy = (x_df * y_df).rolling(n, min_periods=1).sum()
    sx2 = (x_df * x_df).rolling(n, min_periods=1).sum()
    cnt = x_df.rolling(n, min_periods=1).count()
    num = cnt * sxy - sx * sy
    den = (cnt * sx2 - sx * sx).replace(0, np.nan)
    return num / den


def ts_OneOlsResid(x_df: pd.DataFrame, y_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期一元OLS回归残差 = y - (斜率*x + 截距) (对应原版 ts_one_ols_resid)"""
    beta = ts_OneOlsK(x_df, y_df, n)
    intercept = y_df.rolling(n, min_periods=1).mean() - beta * x_df.rolling(n, min_periods=1).mean()
    return y_df - (beta * x_df + intercept)


def ts_STOCHF(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期快速随机指标 = (Close-min(Low,n)) / (max(High,n)-min(Low,n)) (对应原版 ts_stochf)"""
    low_min = low_df.rolling(n, min_periods=1).min()
    high_max = high_df.rolling(n, min_periods=1).max()
    span = (high_max - low_min).replace(0, np.nan)
    return (close_df - low_min) / span


def ts_CMO(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期钱德动量振荡 CMO = (Σ涨-Σ跌)/(Σ涨+Σ跌) (对应原版 ts_cmo)"""
    diff = df.diff()
    su = diff.clip(lower=0).rolling(n, min_periods=1).sum()
    sd = (-diff).clip(lower=0).rolling(n, min_periods=1).sum()
    return (su - sd) / (su + sd).replace(0, np.nan)


def ts_XSRatio(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期效率比 = |x[t]-x[t-n]| / Σ|x[t]-x[t-1]| (对应原版 ts_xs_ratio)"""
    directional = (df - df.shift(n)).abs()
    volatility = df.diff().abs().rolling(n, min_periods=1).sum()
    return directional / volatility.replace(0, np.nan)


def ts_Hedge(x_df: pd.DataFrame, y_df: pd.DataFrame, n: int, n_zscore: int) -> pd.DataFrame:
    """n期回归残差对冲Z-score = Z( x - beta*y, n_zscore ), beta=OLS(y~x) (对应原版 ts_hedge)"""
    beta = ts_OneOlsK(y_df, x_df, n)
    resid = x_df - beta * y_df
    return ts_ZScore(resid, n_zscore)


def ts_BOLL(df: pd.DataFrame, n: int, mult: float) -> pd.DataFrame:
    """n期布林带上轨 = MA(n) + mult*STD(n) (对应原版 ts_bband, mult为常数参数)"""
    mean = df.rolling(n, min_periods=1).mean()
    std = df.rolling(n, min_periods=2).std()
    return mean + float(mult) * std


# ============================================================
# AlphaMaster 映射补充算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1)
# 语义复刻 AlphaMaster ops.py, 适配本系统 DataFrame 面板 (index=日期, columns=股票代码)
# ============================================================

def ts_ArgMax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期窗口内最大值的位置(归一化到[0,1], 0=最早, 1=最近)"""
    return df.rolling(n, min_periods=1).apply(
        lambda w: (np.argmax(w) / max(len(w) - 1, 1)) if len(w) > 0 else np.nan, raw=True)


def ts_ArgMin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期窗口内最小值的位置(归一化到[0,1], 0=最早, 1=最近)"""
    return df.rolling(n, min_periods=1).apply(
        lambda w: (np.argmin(w) / max(len(w) - 1, 1)) if len(w) > 0 else np.nan, raw=True)


def ts_Scale(df: pd.DataFrame) -> pd.DataFrame:
    """沿时间轴缩放到单位L1范数(因果累积和): x[t]/sum(|x[1..t]|)"""
    abs_sum = df.abs().cumsum().replace(0, np.nan)
    return df / abs_sum


def ts_Product(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期滑动乘积(用对数累加避免数值爆炸): exp(sum(log(x+1)))-1"""
    x_safe = df.clip(lower=-0.999)
    log_x = np.log1p(x_safe)
    log_sum = log_x.rolling(n, min_periods=1).sum().clip(-10, 10)
    return np.expm1(log_sum)


def ts_DecayLinear(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """n期线性衰减加权平均(近期权重高): 权重=[1,2,...,n]/sum"""
    weights = np.arange(1, n + 1, dtype=float)
    weights = weights / weights.sum()
    return _rolling_decay_weights_mean(df, n, weights)


def sign(df: pd.DataFrame) -> pd.DataFrame:
    """符号函数"""
    return np.sign(df)


def gate(cond: pd.DataFrame, x: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    """条件门: cond>0 取 x, 否则取 y"""
    mask = (cond > 0).astype(float)
    return mask * x + (1.0 - mask) * y


def jump(df: pd.DataFrame) -> pd.DataFrame:
    """因果expanding zscore + tanh软化(降低稀疏度)"""
    mean = df.expanding(min_periods=1).mean()
    std = df.expanding(min_periods=1).std().replace(0, np.nan)
    z = (df - mean) / std
    return np.tanh(z - 1.5)


def max3(df: pd.DataFrame) -> pd.DataFrame:
    """3期最大值(含当前及前2期)"""
    return df.rolling(3, min_periods=1).max()


def power(df: pd.DataFrame, a: float = 2.0) -> pd.DataFrame:
    """带符号乘方: sign(x)*|x|^a"""
    return np.sign(df) * np.abs(df) ** a


def signed_log(df: pd.DataFrame) -> pd.DataFrame:
    """带符号对数: sign(x)*log1p(|x|)"""
    return np.sign(df) * np.log1p(np.abs(df))


def sqrt(df: pd.DataFrame) -> pd.DataFrame:
    """带符号开方: sign(x)*sqrt(|x|)"""
    return np.sign(df) * np.sqrt(np.abs(df))


def log(df: pd.DataFrame) -> pd.DataFrame:
    """自然对数 (元素级, 对齐 QuantGP 原版 t_log: |x|<=1e-6 置 0, 负值取绝对值后求对数,
    避免对 0/负值求 log 产生 invalid 警告与 NaN 扩散)"""
    EPS = 1e-6
    x = np.abs(df)
    out = np.where(x > EPS, np.log(x), 0.0)
    out = np.where(np.isfinite(out), out, 0.0)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def clip(df: pd.DataFrame, lo: float = -3.0, hi: float = 3.0) -> pd.DataFrame:
    """固定裁剪"""
    return df.clip(lo, hi)


def sigmoid(df: pd.DataFrame) -> pd.DataFrame:
    """sigmoid压缩到(0,1)"""
    return 1.0 / (1.0 + np.exp(-df))


def sigmoid_squash(df: pd.DataFrame) -> pd.DataFrame:
    """AlphaMaster SIGMOID: 2*sigmoid(x)-1, 输出 [-1,1]"""
    out = 2.0 / (1.0 + np.exp(-df)) - 1.0
    return pd.DataFrame(np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=-1.0),
                        index=df.index, columns=df.columns)


def tanh_squash(df: pd.DataFrame) -> pd.DataFrame:
    """tanh压缩到(-1,1)"""
    return np.tanh(df)


def if_gt(cond: pd.DataFrame, x: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    """条件选择: cond>0 取 x, 否则取 y (与gate同语义, 保留AlphaMaster命名)"""
    mask = (cond > 0).astype(float)
    return mask * x + (1.0 - mask) * y


def winsorize(df: pd.DataFrame, lo: float = -3.0, hi: float = 3.0) -> pd.DataFrame:
    """去极值(算子形态): 裁剪到[lo,hi]"""
    return df.clip(lo, hi)


# ============================================================
# 二-ter、Talib技术指标封装 (单股票遍历, 输出面板块)
# ============================================================
# 以下函数遍历每只股票, 调用talib计算, 返回面板DataFrame
# talib接受numpy数组, 返回numpy数组; 我们封装为面板操作

def _apply_talib_single(func, *args, **kwargs):
    """对单只股票数据调用talib函数的辅助函数"""
    return func(*args, **kwargs)


def _talib_panel_apply(talib_func, field_dfs: list, output_idx: int = 0, **kwargs) -> pd.DataFrame:
    """通用Talib面板计算: 遍历股票, 调用talib函数, 返回面板

    参数:
        talib_func:  talib函数对象 (如 talib.DEMA)
        field_dfs:   输入字段DataFrame列表 [close_df, high_df, ...]
        output_idx:  多返回值时取第几个 (默认0)
        **kwargs:    talib函数参数 (如 timeperiod=14)
    返回: DataFrame (index=日期, columns=股票代码)

    性能优化: 各字段矩阵在循环外一次性预提取 (含缺列对齐补NaN),
    避免循环内逐股票重复列查找与类型转换。
    """
    import talib  # noqa: F401  保证 talib 可用
    ref_df = field_dfs[0]
    cols = list(ref_df.columns)
    # 预提取全部字段矩阵 (m × c), 缺列的对齐为 NaN
    arrs = [df.reindex(columns=cols).to_numpy(dtype=float) for df in field_dfs]
    result = pd.DataFrame(index=ref_df.index, columns=cols, dtype=float)
    for i, code in enumerate(cols):
        arrays = [arr[:, i] for arr in arrs]
        out = talib_func(*arrays, **kwargs)
        if isinstance(out, (tuple, list)):
            out = out[output_idx]
        result[code] = out
    return result


# ============================================================
# Talib技术指标批量封装 (用_talib_panel_apply减少重复代码)
# ============================================================

def ts_DEMA(close_df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """双指数移动平均"""
    import talib
    return _talib_panel_apply(talib.DEMA, [close_df], timeperiod=n)


def ts_TEMA(close_df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """三指数移动平均"""
    import talib
    return _talib_panel_apply(talib.TEMA, [close_df], timeperiod=n)


def ts_KAMA(close_df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """考夫曼自适应移动平均"""
    import talib
    return _talib_panel_apply(talib.KAMA, [close_df], timeperiod=n)


def ts_TRIMA(close_df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """三角移动平均"""
    import talib
    return _talib_panel_apply(talib.TRIMA, [close_df], timeperiod=n)


def ts_MAMA(close_df: pd.DataFrame, fast: float = 0.5, slow: float = 0.05) -> pd.DataFrame:
    """MESA自适应移动平均"""
    import talib
    return _talib_panel_apply(talib.MAMA, [close_df], fastlimit=fast, slowlimit=slow)


def ts_SAR(high_df: pd.DataFrame, low_df: pd.DataFrame,
           af: float = 0.02, max_af: float = 0.2) -> pd.DataFrame:
    """抛物线SAR"""
    import talib
    return _talib_panel_apply(talib.SAR, [high_df, low_df], acceleration=af, maximum=max_af)


def ts_SAR_DIST(close_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame,
                af: float = 0.02, max_af: float = 0.2) -> pd.DataFrame:
    """close 相对抛物线SAR的归一化距离 = (close - SAR) / close
    (AlphaMaster SAR_DIST 映射, 见 AlphaMaster特征算子与因子库映射方案.md 3.2)"""
    import talib
    sar = _talib_panel_apply(talib.SAR, [high_df, low_df], acceleration=af, maximum=max_af)
    close_safe = close_df.replace(0, np.nan)
    return (close_df - sar) / close_safe


def ts_MOM(close_df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """动量指标"""
    import talib
    return _talib_panel_apply(talib.MOM, [close_df], timeperiod=n)


def ts_PPO(close_df: pd.DataFrame, fast: int = 12, slow: int = 26, matype: int = 0) -> pd.DataFrame:
    """价格震荡百分比"""
    import talib
    return _talib_panel_apply(talib.PPO, [close_df], fastperiod=fast, slowperiod=slow, matype=matype)


def ts_STOCHF_K(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
                fastk: int = 5, slowk: int = 3) -> pd.DataFrame:
    """快速随机K值"""
    import talib
    return _talib_panel_apply(talib.STOCHF, [high_df, low_df, close_df], output_idx=0,
                              fastk_period=fastk, fastd_period=slowk)


def ts_AROON_UP(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    """阿隆上轨"""
    import talib
    return _talib_panel_apply(talib.AROON, [high_df, low_df], output_idx=0, timeperiod=n)


def ts_AROON_DOWN(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    """阿隆下轨"""
    import talib
    return _talib_panel_apply(talib.AROON, [high_df, low_df], output_idx=1, timeperiod=n)


def ts_AROONOSC(high_df: pd.DataFrame, low_df: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    """阿隆震荡"""
    import talib
    return _talib_panel_apply(talib.AROONOSC, [high_df, low_df], timeperiod=n)


def ts_MFI(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
           volume_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """资金流向指标"""
    import talib
    return _talib_panel_apply(talib.MFI, [high_df, low_df, close_df, volume_df], timeperiod=n)


def ts_ULTOSC(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
              p1: int = 7, p2: int = 14, p3: int = 28) -> pd.DataFrame:
    """终极震荡指标"""
    import talib
    return _talib_panel_apply(talib.ULTOSC, [high_df, low_df, close_df],
                              timeperiod1=p1, timeperiod2=p2, timeperiod3=p3)


def ts_ADXR(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
            n: int = 14) -> pd.DataFrame:
    """ADX评级"""
    import talib
    return _talib_panel_apply(talib.ADXR, [high_df, low_df, close_df], timeperiod=n)


def ts_TRANGE(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """真实波幅"""
    import talib
    return _talib_panel_apply(talib.TRANGE, [high_df, low_df, close_df])


def ts_AD(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
          volume_df: pd.DataFrame) -> pd.DataFrame:
    """累积派发线"""
    import talib
    return _talib_panel_apply(talib.AD, [high_df, low_df, close_df, volume_df])


def ts_ADOSC(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
             volume_df: pd.DataFrame, fast: int = 3, slow: int = 10) -> pd.DataFrame:
    """累积震荡指标"""
    import talib
    return _talib_panel_apply(talib.ADOSC, [high_df, low_df, close_df, volume_df],
                              fastperiod=fast, slowperiod=slow)


def ts_AVGPRICE(open_df: pd.DataFrame, high_df: pd.DataFrame,
                low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """均价"""
    import talib
    return _talib_panel_apply(talib.AVGPRICE, [open_df, high_df, low_df, close_df])


def ts_MEDPRICE(high_df: pd.DataFrame, low_df: pd.DataFrame) -> pd.DataFrame:
    """中价"""
    import talib
    return _talib_panel_apply(talib.MEDPRICE, [high_df, low_df])


def ts_TYPPRICE(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """典型价"""
    import talib
    return _talib_panel_apply(talib.TYPPRICE, [high_df, low_df, close_df])


def ts_WCLPRICE(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """加权收盘价"""
    import talib
    return _talib_panel_apply(talib.WCLPRICE, [high_df, low_df, close_df])


def ts_VAR(close_df: pd.DataFrame, n: int = 5, nbdev: float = 1.0) -> pd.DataFrame:
    """方差"""
    import talib
    return _talib_panel_apply(talib.VAR, [close_df], timeperiod=n, nbdev=nbdev)


def ts_LINEARREG(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """线性回归"""
    import talib
    return _talib_panel_apply(talib.LINEARREG, [close_df], timeperiod=n)


def ts_LINEARREG_SLOPE(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """线性回归斜率"""
    import talib
    return _talib_panel_apply(talib.LINEARREG_SLOPE, [close_df], timeperiod=n)


def ts_LINEARREG_ANGLE(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """线性回归角度"""
    import talib
    return _talib_panel_apply(talib.LINEARREG_ANGLE, [close_df], timeperiod=n)


def ts_LINEARREG_INTERCEPT(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """线性回归截距"""
    import talib
    return _talib_panel_apply(talib.LINEARREG_INTERCEPT, [close_df], timeperiod=n)


def ts_LINEARREG_R2(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """线性回归R2 (talib缺失此函数, 手动实现: 对时间趋势1..n回归的决定系数)"""
    x = np.arange(n, dtype=float)

    def _r2(window):
        if window.shape[0] < 2:
            return np.nan
        w = window.astype(float)
        xw = x[:w.shape[0]]
        slope, intercept = np.polyfit(xw, w, 1)
        yhat = slope * xw + intercept
        ss_res = float(np.sum((w - yhat) ** 2))
        ss_tot = float(np.sum((w - np.mean(w)) ** 2))
        if ss_tot == 0:
            return np.nan
        return 1 - ss_res / ss_tot

    return close_df.rolling(n, min_periods=2).apply(_r2, raw=True)


def ts_HT_DCPERIOD(close_df: pd.DataFrame) -> pd.DataFrame:
    """希尔伯特主导周期"""
    import talib
    return _talib_panel_apply(talib.HT_DCPERIOD, [close_df])


def ts_HT_DCPHASE(close_df: pd.DataFrame) -> pd.DataFrame:
    """希尔伯特主导相位"""
    import talib
    return _talib_panel_apply(talib.HT_DCPHASE, [close_df])


def ts_HT_TRENDMODE(close_df: pd.DataFrame) -> pd.DataFrame:
    """希尔伯特趋势模式"""
    import talib
    return _talib_panel_apply(talib.HT_TRENDMODE, [close_df])


# ============================================================
# Talib K线形态批量封装 (61种CDL指标)
# ============================================================

def _make_cdl_func(cdl_name: str):
    """工厂函数: 生成K线形态封装函数"""
    import talib
    talib_func = getattr(talib, cdl_name)

    def cdl_func(open_df: pd.DataFrame, high_df: pd.DataFrame,
                 low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
        return _talib_panel_apply(talib_func, [open_df, high_df, low_df, close_df])
    cdl_func.__name__ = f"ta_{cdl_name}"
    return cdl_func


# 批量生成K线形态函数 (注册到模块命名空间)
_CDL_PATTERNS = [
    "CDL2CROWS", "CDL3BLACKCROWS", "CDL3INSIDE", "CDL3LINESTRIKE",
    "CDL3OUTSIDE", "CDL3STARSINSOUTH", "CDL3WHITESOLDIERS",
    "CDLABANDONEDBABY", "CDLADVANCEBLOCK", "CDLBELTHOLD",
    "CDLBREAKAWAY", "CDLCLOSINGMARUBOZU", "CDLCONCEALBABYSWALL",
    "CDLCOUNTERATTACK", "CDLDARKCLOUDCOVER", "CDLDOJI",
    "CDLDOJISTAR", "CDLDRAGONFLYDOJI", "CDLENGULFING",
    "CDLEVENINGDOJISTAR", "CDLEVENINGSTAR", "CDLGAPSIDESIDEWHITE",
    "CDLGRAVESTONEDOJI", "CDLHAMMER", "CDLHANGINGMAN",
    "CDLHARAMI", "CDLHARAMICROSS", "CDLHIGHWAVE",
    "CDLHIKKAKE", "CDLHIKKAKEMOD", "CDLHOMINGPIGEON",
    "CDLIDENTICAL3CROWS", "CDLINNECK", "CDLINVERTEDHAMMER",
    "CDLKICKING", "CDLKICKINGBYLENGTH", "CDLLADDERBOTTOM",
    "CDLLONGLEGGEDDOJI", "CDLLONGLINE", "CDLMARUBOZU",
    "CDLMATCHINGLOW", "CDLMATHOLD", "CDLMORNINGDOJISTAR",
    "CDLMORNINGSTAR", "CDLONNECK", "CDLPIERCING",
    "CDLRICKSHAWMAN", "CDLRISEFALL3METHODS", "CDLSEPARATINGLINES",
    "CDLSHOOTINGSTAR", "CDLSHORTLINE", "CDLSPINNINGTOP",
    "CDLSTALLEDPATTERN", "CDLSTICKSANDWICH", "CDLTAKURI",
    "CDLTASUKIGAP", "CDLTHRUSTING", "CDLTRISTAR",
    "CDLUNIQUE3RIVER", "CDLUPSIDEGAP2CROWS", "CDLXSIDEGAP3METHODS",
]

# 动态生成并注册到 globals()
for _cdl_name in _CDL_PATTERNS:
    _func = _make_cdl_func(_cdl_name)
    globals()[_func.__name__] = _func


def ts_RSI(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """RSI相对强弱指标"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        vals = close_df[code].values.astype(float)
        result[code] = talib.RSI(vals, timeperiod=n)
    return result


def ts_ADX(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """ADX平均趋向指标"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.ADX(h, l, c, timeperiod=n)
    return result


def ts_CCI(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """CCI顺势指标"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.CCI(h, l, c, timeperiod=n)
    return result


def ts_WILLR(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """威廉指标"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.WILLR(h, l, c, timeperiod=n)
    return result


def ts_ATR(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """ATR真实波幅"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.ATR(h, l, c, timeperiod=n)
    return result


def ts_OBV(close_df: pd.DataFrame, volume_df: pd.DataFrame) -> pd.DataFrame:
    """OBV能量潮指标"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        v = volume_df[code].values.astype(float)
        result[code] = talib.OBV(c, v)
    return result


def ts_SMA(close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """简单移动平均"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        result[code] = talib.SMA(c, timeperiod=n)
    return result


def ts_EMA(close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """指数移动平均"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        result[code] = talib.EMA(c, timeperiod=n)
    return result


def ts_WMA(close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """加权移动平均"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        result[code] = talib.WMA(c, timeperiod=n)
    return result


def ts_MACD_DIF(close_df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD的DIF线 (快线-慢线)"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        dif, _, _ = talib.MACD(c, fastperiod=fast, slowperiod=slow, signalperiod=signal)
        result[code] = dif
    return result


def ts_MACD_DEA(close_df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD的DEA线 (信号线)"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        _, dea, _ = talib.MACD(c, fastperiod=fast, slowperiod=slow, signalperiod=signal)
        result[code] = dea
    return result


def ts_MACD_HIST(close_df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD的柱状图 (DIF-DEA)"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        _, _, hist = talib.MACD(c, fastperiod=fast, slowperiod=slow, signalperiod=signal)
        result[code] = hist
    return result


def ts_KDJ_K(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
             fastk: int = 9, slowk: int = 3) -> pd.DataFrame:
    """KDJ的K值"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        k, _ = talib.STOCH(h, l, c, fastk_period=fastk, slowk_period=slowk, slowk_matype=0,
                           slowd_period=slowk, slowd_matype=0)
        result[code] = k
    return result


def ts_KDJ_D(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame,
             fastk: int = 9, slowk: int = 3) -> pd.DataFrame:
    """KDJ的D值"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        _, d = talib.STOCH(h, l, c, fastk_period=fastk, slowk_period=slowk, slowk_matype=0,
                           slowd_period=slowk, slowd_matype=0)
        result[code] = d
    return result


def ts_BOLL_POS(close_df: pd.DataFrame, n: int = 20, nbdev: int = 2) -> pd.DataFrame:
    """布林带位置 = (价格-下轨) / (上轨-下轨)"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        upper, middle, lower = talib.BBANDS(c, timeperiod=n, nbdevup=nbdev, nbdevdn=nbdev)
        band_width = upper - lower
        band_width = np.where(band_width > 0, band_width, np.nan)
        result[code] = (c - lower) / band_width
    return result


def ts_BOLL_WIDTH(close_df: pd.DataFrame, n: int = 20, nbdev: int = 2) -> pd.DataFrame:
    """布林带宽度 = (上轨-下轨) / 中轨 (AlphaMaster BOLL_WIDTH 映射, 见 AlphaMaster特征算子与因子库映射方案.md 3.2)"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        upper, middle, lower = talib.BBANDS(c, timeperiod=n, nbdevup=nbdev, nbdevdn=nbdev)
        mid_safe = np.where(np.abs(middle) > 1e-9, middle, np.nan)
        result[code] = (upper - lower) / mid_safe
    return result


def ts_STOCHRSI_K(close_df: pd.DataFrame, n: int = 14, fastk: int = 3, slowk: int = 3) -> pd.DataFrame:
    """STOCHRSI的K值"""
    import talib
    result = pd.DataFrame(index=close_df.index, columns=close_df.columns, dtype=float)
    for code in close_df.columns:
        c = close_df[code].values.astype(float)
        k, _ = talib.STOCHRSI(c, timeperiod=n, fastk_period=fastk, fastd_period=slowk)
        result[code] = k
    return result


def ts_NATR(high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """归一化ATR = ATR/Close * 100"""
    import talib
    result = pd.DataFrame(index=high_df.index, columns=high_df.columns, dtype=float)
    for code in high_df.columns:
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.NATR(h, l, c, timeperiod=n)
    return result


# ============================================================
# 二-quater、Talib K线形态封装 (离散信号, 返回0/100)
# ============================================================

def ta_CDLHAMMER(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """锤形线"""
    import talib
    result = pd.DataFrame(index=open_df.index, columns=open_df.columns, dtype=float)
    for code in open_df.columns:
        o = open_df[code].values.astype(float)
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.CDLHAMMER(o, h, l, c)
    return result


def ta_CDLDOJI(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """十字星"""
    import talib
    result = pd.DataFrame(index=open_df.index, columns=open_df.columns, dtype=float)
    for code in open_df.columns:
        o = open_df[code].values.astype(float)
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.CDLDOJI(o, h, l, c)
    return result


def ta_CDLENGULFING(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """吞没形态"""
    import talib
    result = pd.DataFrame(index=open_df.index, columns=open_df.columns, dtype=float)
    for code in open_df.columns:
        o = open_df[code].values.astype(float)
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.CDLENGULFING(o, h, l, c)
    return result


def ta_CDLSTAR(open_df: pd.DataFrame, high_df: pd.DataFrame, low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """早晨/黄昏之星"""
    import talib
    result = pd.DataFrame(index=open_df.index, columns=open_df.columns, dtype=float)
    for code in open_df.columns:
        o = open_df[code].values.astype(float)
        h = high_df[code].values.astype(float)
        l = low_df[code].values.astype(float)
        c = close_df[code].values.astype(float)
        result[code] = talib.CDLSTARS(o, h, l, c)
    return result


# ============================================================
# 二-quater-bis、Talib K线形态批量封装 (动态生成, 减少重复代码)
# ============================================================
# 除上述4个手写函数外, 其余CDL形态通过工厂模式动态生成
# 命名规则: ta_CDLXXX(Open, High, Low, Close) -> talib.CDLXXX(o, h, l, c)

def _make_cdl_func(talib_func_name: str) -> Callable:
    """工厂函数: 生成ta_CDL*面板计算函数

    参数:
        talib_func_name: talib中的函数名, 如 "CDL3INSIDE"
    返回: 函数 ta_CDLXXX(open_df, high_df, low_df, close_df) -> DataFrame
    """
    def _cdl_func(open_df: pd.DataFrame, high_df: pd.DataFrame,
                  low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
        import talib
        talib_fn = getattr(talib, talib_func_name)
        result = pd.DataFrame(index=open_df.index, columns=open_df.columns, dtype=float)
        for code in open_df.columns:
            o = open_df[code].values.astype(float)
            h = high_df[code].values.astype(float)
            l = low_df[code].values.astype(float)
            c = close_df[code].values.astype(float)
            result[code] = talib_fn(o, h, l, c)
        return result
    _cdl_func.__name__ = f"ta_{talib_func_name}"
    _cdl_func.__doc__ = f"Talib {talib_func_name} K线形态"
    return _cdl_func


# talib中所有CDL形态函数名 (除已手写的4个: CDLHAMMER/CDLDOJI/CDLENGULFING/CDLSTAR)
_TALIB_CDL_NAMES = [
    "CDL2CROWS", "CDL3BLACKCROWS", "CDL3INSIDE", "CDL3LINESTRIKE",
    "CDL3OUTSIDE", "CDL3STARSINSOUTH", "CDL3WHITESOLDIERS",
    "CDLABANDONEDBABY", "CDLADVANCEBLOCK", "CDLBELTHOLD", "CDLBREAKAWAY",
    "CDLCLOSINGMARUBOZU", "CDLCONCEALBABYSWALL", "CDLCOUNTERATTACK",
    "CDLDARKCLOUDCOVER", "CDLDRAGONFLYDOJI",
    "CDLEVENINGSTAR", "CDLGAPSIDESIDEWHITE", "CDLGRAVESTONEDOJI",
    "CDLHANGINGMAN", "CDLHARAMI", "CDLHIKKAKE", "CDLHIKKAKEMOD",
    "CDLHOMINGPIGEON", "CDLIDENTICAL3CROWS", "CDLINNECK",
    "CDLINVERTEDHAMMER", "CDLKICKING", "CDLLADDERBOTTOM",
    "CDLLONGLEGGEDDOJI", "CDLLONGLINE", "CDLMARUBOZU", "CDLMATCHINGLOW",
    "CDLMATHOLD", "CDLMORNINGDOJISTAR", "CDLMORNINGSTAR", "CDLONNECK",
    "CDLPIERCING", "CDLRICKSHAWMAN", "CDLRISEFALL3METHODS",
    "CDLSEPARATINGLINES", "CDLSHOOTINGSTAR", "CDLSHORTLINE",
    "CDLSPINNINGTOP", "CDLSTALLEDPATTERN", "CDLSTICKSANDWICH",
    "CDLTAKURI", "CDLTASUKIGAP", "CDLTHRUSTING", "CDLTRISTAR",
    "CDLUNIQUE3RIVER", "CDLUPSIDEGAP2CROWS", "CDLXSIDEGAP3METHODS",
]

# 动态生成并注册到模块全局命名空间
for _cdl_name in _TALIB_CDL_NAMES:
    _func = _make_cdl_func(_cdl_name)
    globals()[f"ta_{_cdl_name}"] = _func


def ta_CDLDOWNSIDEGAP3METHODS(open_df: pd.DataFrame, high_df: pd.DataFrame,
                              low_df: pd.DataFrame, close_df: pd.DataFrame) -> pd.DataFrame:
    """向下跳空三法 (看跌持续, talib缺失此函数, 手动实现)

    形态: 处于下跌趋势中,
      第1根: 长阴线
      第2根: 阴线且向下跳空(其最高 < 第1根收盘)
      第3根: 阳线, 开盘位于缺口内(高于第2根收盘、低于第1根收盘), 但收盘跌破第2根收盘
    返回: 命中=-100, 未命中=0 (与talib形态符号约定一致)
    """
    o, h, l, c = open_df, high_df, low_df, close_df
    body = (c - o).abs()
    body_avg = body.rolling(10, min_periods=1).mean()
    is_black = c < o
    is_white = c > o
    # 第1根长阴
    day1 = is_black & (body > body_avg * 1.1)
    # 第2根阴线且跳空向下 (最高低于第1根收盘)
    day2 = is_black & (h < c.shift(1))
    # 第3根阳线, 开盘在缺口内, 收盘低于第2根收盘
    day3 = is_white & (o > c.shift(1)) & (o < c.shift(2)) & (c < c.shift(1))
    pattern = day1.shift(2) & day2.shift(1) & day3
    return pattern.astype(int) * -100


# ============================================================
# 二-quinquies、财务数据引用函数
# ============================================================

# 财务数据缓存 (避免重复查询数据库)
_FN_CACHE = {}


def FN(field: str, panel: Optional[Dict[str, pd.DataFrame]] = None,
       lag_days: Optional[int] = None) -> pd.DataFrame:
    """财务字段引用函数
    从财务数据库读取字段, 按日期对齐到日K(ffill), 返回面板DataFrame

    field: 财务字段名 (eps/roe/net_profit/total_assets/revenue...)
    panel: 可选, 传入则按panel的index/columns对齐
    lag_days: 财报披露滞后天数。None=按报告期类型自动分级(年报120/半年报90/季报45,
              评价/回测用, 避免未来函数); 传 0=不延迟(因子包实际使用用:
              数据表里已有=当前已知道, 直接用最新财报)。

    实现:
      1. 调用 lib.financial_data.load_financial_field 读取原始面板
         原始面板 index=report_date+滞后天数(数据可用日)
      2. 若传入 panel, 调用 load_financial_panel 按 asof 方式对齐到日K日期
         (对每个日期取 <=该日期 的最后一条, 严格避免未来函数)
    """
    from lib.financial_data import load_financial_field, load_financial_panel

    # 无 panel 时返回原始面板 (index=数据可用日)
    if panel is None:
        return load_financial_field(field, lag_days=lag_days)

    # 有 panel 时按日K对齐
    first_code = next(iter(panel))
    dates = panel[first_code].index
    codes = list(panel.keys())
    return load_financial_panel(field, dates=dates, stock_codes=codes, lag_days=lag_days)


def fin_Delay(fin_df: pd.DataFrame, n: int = 1) -> pd.DataFrame:
    """财报延迟n期 (避免未来函数, 按财报期shift)
    fin_df: FN返回的DataFrame
    n: 往前推几期

    参考: 清华 gl23_day2_fin 的 fin_Delay, 按财报期 shift 而非按交易日 shift
    实现: 调用 lib.financial_data.fin_Delay
    """
    from lib.financial_data import fin_Delay as _fin_delay
    return _fin_delay(fin_df, n)


# ============================================================
# 三、因子预处理 (来源: CASE-C/preprocessor.py)
# ============================================================

def winsorize_mad(series: pd.Series, n: float = 3.0) -> pd.Series:
    """MAD 去极值"""
    s = series.copy()
    median = s.median()
    mad = (s - median).abs().median()
    if mad == 0 or np.isnan(mad):
        return s
    upper = median + n * 1.4826 * mad
    lower = median - n * 1.4826 * mad
    return s.clip(lower=lower, upper=upper)


def winsorize_panel_cross_section(factor_df: pd.DataFrame, n: float = 3.0) -> pd.DataFrame:
    """对因子面板做逐截面(每个日期, 跨股票)的 MAD 去极值

    与单因子IC评价/多因子合成的截面去极值方式保持一致 (来源: CASE-C/preprocessor.py)。
    用于在 factor 源头对低频/含极端值的因子(如财务因子 PE=-287)去极值,
    使展示的因子值、data_stats 与后续IC/分层评价口径一致。
    """
    out = factor_df.copy()
    for idx in out.index:
        row = out.loc[idx]
        out.loc[idx] = winsorize_mad(row, n=n)
    return out


def zscore(series: pd.Series) -> pd.Series:
    """Z-score 标准化"""
    s = series.copy()
    mean = s.mean()
    std = s.std(ddof=1)
    if std == 0 or np.isnan(std):
        return s * 0.0
    return (s - mean) / std


def industry_neutralize(factor_series: pd.Series, industry_map: dict) -> pd.Series:
    """行业内 Z-score 中性化"""
    df = pd.DataFrame({
        "factor": factor_series,
        "industry": [industry_map.get(idx, "unknown") for idx in factor_series.index]
    })
    result = pd.Series(index=factor_series.index, dtype=float)
    for ind, group in df.groupby("industry"):
        result.loc[group.index] = zscore(group["factor"])
    return result


def group_neutralize(factor_series: pd.Series, group_map: dict, method: str = "zscore") -> pd.Series:
    """通用分组中性化 (板块/概念/行业通用)

    factor_series: 因子值 (index=股票代码)
    group_map:     {stock_code: group_name} 分组映射
    method:        "zscore" 或 "rank"
    """
    df = pd.DataFrame({
        "factor": factor_series,
        "group": [group_map.get(idx, "unknown") for idx in factor_series.index]
    })
    result = pd.Series(index=factor_series.index, dtype=float)
    for grp, group in df.groupby("group"):
        if method == "rank":
            # 分组内排名 (参考清华groupby_Rank)
            result.loc[group.index] = group["factor"].rank(pct=True)
        else:
            result.loc[group.index] = zscore(group["factor"])
    return result


def sector_neutralize(factor_series: pd.Series, sector_map: dict, method: str = "zscore") -> pd.Series:
    """板块中性化 (用户重点要求, 数据来自板块数据库)"""
    return group_neutralize(factor_series, sector_map, method)


def concept_neutralize(factor_series: pd.Series, concept_map: dict, method: str = "zscore") -> pd.Series:
    """概念中性化 (用户重点要求, 数据来自概念数据库)"""
    return group_neutralize(factor_series, concept_map, method)


def preprocess_factors(factor_df: pd.DataFrame,
                       industry_map: Optional[dict] = None,
                       neutralize: bool = True,
                       sector_map: Optional[dict] = None,
                       concept_map: Optional[dict] = None,
                       method: str = "zscore",
                       marketcap_map: Optional[dict] = None) -> pd.DataFrame:
    """
    因子预处理: 去极值 + 中性化(市值/分组回归取残差) + Z-score
    factor_df:    index=股票代码, columns=因子名
    industry_map: 行业映射 (可选)
    sector_map:   板块映射 (可选)
    concept_map:  概念映射 (可选)
    marketcap_map: 市值映射 (可选, 与分组维度可叠加)
    method:       保留参数 (回归取残差下不再区分 zscore/rank, 向后兼容)
    """
    result = factor_df.copy()
    group_map = sector_map or concept_map or industry_map
    for col in result.columns:
        result[col] = winsorize_mad(result[col])
        if neutralize:
            if marketcap_map is not None or group_map is not None:
                result[col] = neutralize_regression(result[col], group_map, marketcap_map)
            else:
                result[col] = zscore(result[col])
            # 中性化后再做一次全市场 Z-score, 让所有分组可比 (对齐 CASE-C/preprocessor.py)
            result[col] = zscore(result[col])
        else:
            result[col] = zscore(result[col])
    return result


# ============================================================
# 四、IC/IR 评价 (来源: CASE-C/synthesizer.py)
# ============================================================

def calc_ic(factor_series: pd.Series, future_return: pd.Series,
            method: str = "spearman") -> float:
    """计算单期 IC (信息系数)"""
    df = pd.DataFrame({"f": factor_series, "r": future_return}).dropna()
    if len(df) < 10:
        return np.nan
    return df["f"].corr(df["r"], method=method)


def calc_ir(ic_series: pd.Series) -> float:
    """IR = IC 均值 / IC 标准差"""
    if len(ic_series) < 2:
        return np.nan
    mean = ic_series.mean()
    std = ic_series.std(ddof=1)
    return mean / std if std > 0 else np.nan


# ============================================================
# 四-bis、清华PerformanceWithCost评价 (来源: qinghua/day1_A.ipynb)
# ============================================================
# 含交易成本的因子评价: 夏普/年化收益/换手率, 融合清华case做法
# 与IC/IR评价互补: IC看预测能力, PerformanceWithCost看实际交易收益

def groupby_Rank(factor_series: pd.Series, group_map: dict) -> pd.Series:
    """分组内排名 (参考清华day2_M的groupby_Rank)

    用于行业/板块/概念内排名中性化, 比Z-score更鲁棒

    参数:
        factor_series: 因子值 (index=股票代码)
        group_map:     {stock_code: group_name} 分组映射
    返回: 分组内百分位排名 (0~1)
    """
    df = pd.DataFrame({
        "factor": factor_series,
        "group": [group_map.get(idx, "unknown") for idx in factor_series.index]
    })
    result = pd.Series(index=factor_series.index, dtype=float)
    for grp, group in df.groupby("group"):
        result.loc[group.index] = group["factor"].rank(pct=True)
    return result


def GetCost(position_df: pd.DataFrame, cost: float = 0.002) -> pd.DataFrame:
    """计算交易成本 (来源: 清华day1_A的GetCost)

    交易成本 = cost × |持仓变化|
    持仓变化 = 当期持仓 - 前一期持仓 的绝对值

    参数:
        position_df: 持仓矩阵 (index=日期, columns=股票), 已标准化
        cost:        单边交易成本率 (默认0.2%)
    返回: 每日交易成本矩阵 (同形状)
    """
    position_change = position_df.diff().abs()
    # 第一期无前值, 成本为0
    position_change.iloc[0] = 0
    return position_change * cost


def GetTurnover(position_df: pd.DataFrame) -> float:
    """计算换手率 (来源: 清华day1_A的GetTurnover)

    与原版一致: 相对换手率 = 持仓变化绝对值之和 / 前期持仓绝对值之和, 再按日期取均值
      a = |position - ts_Delay(position, 1)| 按行求和 (当日持仓变动)
      b = |ts_Delay(position, 1)| 按行求和 (前一交易日持仓水平)
      turnover = mean(a / b)

    参数:
        position_df: 持仓矩阵 (index=日期, columns=股票)
    返回: 平均日换手率 (相对值)
    """
    if len(position_df) < 2:
        return 0.0
    a = (position_df - ts_Delay(position_df, 1)).abs().sum(axis=1)
    b = ts_Delay(position_df, 1).abs().sum(axis=1)
    b[b == 0] = np.nan
    z = a / b
    c = z.mean()
    return round(float(c), 3) if pd.notna(c) else 0.0


def PerformanceWithCost(f1: pd.DataFrame,
                        TotalRet: pd.DataFrame,
                        delayNum: int = 2,
                        cost: float = 0.002,
                        SDate: int = 0,
                        EDate: int = -1) -> Dict[str, Any]:
    """含交易成本的因子评价 (来源: 清华day1_A的PerformanceWithCost)

    评价流程:
      1. 因子标准化: 截面正态分位数变换 (pn_TransNorm)
      2. 延迟delayNum期: 避免使用未来数据 (T日因子 T+delayNum日交易)
      3. 计算因子收益: factorRet = 标准化因子 × 日收益率
      4. 方向判断: 若因子均值为负则反向 (保证做多)
      5. 扣除交易成本: GetCost
      6. 计算夏普/年化收益

    参数:
        f1:       因子值面板 (index=日期, columns=股票)
        TotalRet: 日收益率面板 (index=日期, columns=股票)
        delayNum: 延迟天数 (默认2, T日因子T+2日交易)
        cost:     单边交易成本率 (默认0.2%)
        SDate:    评价开始索引 (默认0)
        EDate:    评价结束索引 (默认-1=到最后)
    返回: {sharpe_ratio, annual_return, turnover, strategy_return, direction}
    """
    # 对齐索引和列
    common_cols = f1.columns.intersection(TotalRet.columns)
    common_idx = f1.index.intersection(TotalRet.index)
    if len(common_cols) == 0 or len(common_idx) == 0:
        return {"sharpe_ratio": None, "annual_return": None, "turnover": None,
                "strategy_return": [], "direction": 1}

    f1 = f1.loc[common_idx, common_cols]
    TotalRet = TotalRet.loc[common_idx, common_cols]

    # 1. 因子标准化: 截面正态分位数变换
    f1_stand = cs_TransNorm(f1.round(4))

    # 2. 延迟delayNum期
    f1_stand_D2 = ts_Delay(f1_stand, delayNum)

    # 3. 因子收益 = 延迟标准化因子 × 日收益率
    factorRet = f1_stand_D2 * TotalRet

    # 4. 方向判断: 若因子收益均值为负则反向
    mean_ret = factorRet.mean(axis=1).mean()
    dire = 1 if mean_ret >= 0 else -1
    factorRet = factorRet * dire

    # 5. 扣除交易成本
    Cost = GetCost(f1_stand_D2, cost)
    factorRet = factorRet - Cost

    # 6. 截取评价区间
    if EDate == -1:
        EDate = len(factorRet)
    factorRet = factorRet.iloc[SDate:EDate]

    if len(factorRet) == 0:
        return {"sharpe_ratio": None, "annual_return": None, "turnover": None,
                "strategy_return": [], "direction": dire}

    # 因子收益时间序列 (截面均值)
    factorRetLine = factorRet.mean(axis=1)

    # 夏普比率 (清华: 均值/标准差 × 15, 近似月频年化)
    std_ret = factorRetLine.std()
    sr = float(factorRetLine.mean() / std_ret * 15) if std_ret > 0 else 0.0

    # 年化收益 (清华: 均值 × 250)
    ar = float(factorRetLine.mean() * 250)

    # 换手率
    turnover = GetTurnover(f1_stand_D2)

    return {
        "sharpe_ratio": round(sr, 3),
        "annual_return": round(ar, 3),
        "turnover": round(turnover, 4),
        "strategy_return": [
            {"date": str(idx.date()), "value": float(v) if pd.notna(v) else 0.0}
            for idx, v in factorRetLine.items()
        ],
        "direction": dire,
    }


def GetQuantileRet(f1: pd.DataFrame,
                   TotalRet: pd.DataFrame,
                   Q: int = 5,
                   delayNum: int = 2,
                   cost: float = 0.0,
                   SDate: int = 0,
                   EDate: int = -1) -> Dict[str, Any]:
    """分位数收益 (来源: 清华day1_A的GetQuantileRet)

    与PerformanceWithCost共用同一套标准化/延迟/方向/扣成本逻辑,
    差别在于把因子按截面分位点分成 Q 组, 分别计算各组的年化因子收益,
    用于观察因子收益是否随分位单调递增 (正/负向的直观体现).

    参数:
        f1:       因子值面板 (index=日期, columns=股票)
        TotalRet: 日收益率面板 (index=日期, columns=股票)
        Q:        分位数组数 (默认5)
        delayNum: 延迟天数 (默认2, T日因子T+2日交易)
        cost:     单边交易成本率 (默认0, 与清华原始一致可单独观察毛收益)
        SDate:    开始索引 (默认0)
        EDate:    结束索引 (默认-1=到最后)
    返回: {quantile_returns: [q1年化收益, ..., qQ年化收益], direction}
    """
    common_cols = f1.columns.intersection(TotalRet.columns)
    common_idx = f1.index.intersection(TotalRet.index)
    if len(common_cols) == 0 or len(common_idx) == 0:
        return {"quantile_returns": [], "direction": 1}

    f1 = f1.loc[common_idx, common_cols]
    TotalRet = TotalRet.loc[common_idx, common_cols]

    # 因子标准化 (截面正态分位数变换)
    f_stand = cs_TransNorm(f1.round(4))
    f_stand_D = ts_Delay(f_stand, delayNum)

    # 因子收益 = 延迟标准化因子 × 日收益率
    factorRet = f_stand_D * TotalRet

    # 方向自动判断 (与PerformanceWithCost一致, 保证做多)
    dire = 1 if factorRet.mean(axis=1).mean() >= 0 else -1
    factorRet = factorRet * dire

    # 扣除交易成本
    Cost = GetCost(f_stand_D, cost)
    factorRet = factorRet - Cost

    # 截取评价区间
    if EDate == -1:
        EDate = len(factorRet)
    factorRet = factorRet.iloc[SDate:EDate]
    f_cut = f1.iloc[SDate:EDate]

    n = len(f_cut.index)
    if n == 0:
        return {"quantile_returns": [], "direction": dire}

    # 按截面分位点分成 Q 组 (对齐清华: 每天按轴=1分位点切分)
    quantile_returns = []
    for v in range(Q):
        low = f_cut.quantile(v / Q, axis=1)
        up = f_cut.quantile((v + 1) / Q, axis=1)
        # 组内掩码: 满足 [low, up) 的列保留, 其余置 NaN
        mask = pd.DataFrame(1.0, index=f_cut.index, columns=f_cut.columns)
        mask[f_cut.lt(low, axis=0)] = np.nan
        mask[f_cut.ge(up, axis=0)] = np.nan
        group_ret = (factorRet.loc[f_cut.index] * mask).mean(axis=1)
        # 年化收益 = 日截面均值均值 × 250 (与PerformanceWithCost一致)
        avg = group_ret.mean()
        quantile_returns.append(round(float(avg) * 250, 4) if pd.notna(avg) else 0.0)

    return {"quantile_returns": quantile_returns, "direction": dire}


def build_total_return_panel(panel: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """从日K面板构建日收益率面板 (供PerformanceWithCost使用)

    参数:
        panel: {stock_code: DataFrame}, 每只股票的日K (含 close)
    返回: DataFrame (index=日期, columns=股票代码, values=日收益率)
    """
    first_code = next(iter(panel))
    dates = panel[first_code].index

    returns_dict = {}
    for code, df in panel.items():
        if "close" in df.columns:
            returns_dict[code] = df["close"].astype(float).pct_change()

    if not returns_dict:
        return pd.DataFrame()

    ret_df = pd.DataFrame(returns_dict)
    ret_df = ret_df.reindex(dates)
    return ret_df


# ============================================================
# 五、因子合成 (来源: CASE-C/synthesizer.py)
# ============================================================

def equal_weight_synthesis(factor_df: pd.DataFrame) -> pd.Series:
    """等权合成"""
    return factor_df.mean(axis=1)


def ic_weighted_synthesis(factor_df: pd.DataFrame, ic_dict: dict) -> pd.Series:
    """IC 加权合成"""
    weights = pd.Series(ic_dict)
    weights = weights.reindex(factor_df.columns).fillna(0)
    if weights.abs().sum() == 0:
        return factor_df.mean(axis=1)
    weights_norm = weights / weights.abs().sum()
    return (factor_df * weights_norm).sum(axis=1)


def lasso_synthesis(X_train: pd.DataFrame, y_train: pd.Series,
                    X_predict: pd.DataFrame, alpha: float = 0.01) -> pd.Series:
    """Lasso 回归合成"""
    from sklearn.linear_model import Lasso
    model = Lasso(alpha=alpha, max_iter=5000)
    mask = ~(X_train.isna().any(axis=1) | y_train.isna())
    model.fit(X_train[mask], y_train[mask])
    return pd.Series(model.predict(X_predict), index=X_predict.index)


# ============================================================
# 六、分层回测 (来源: CASE-C/layered_backtest.py)
# ============================================================

def run_layered_backtest(factor_values: pd.Series,
                         future_returns: pd.Series,
                         n_layers: int = 5) -> Dict[str, Any]:
    """
    简化版分层回测（单期）

    参数:
        factor_values:   index=股票, value=因子值
        future_returns:  index=股票, value=未来收益
        n_layers:        分层数

    返回: {layer_returns, ic, long_short}
    """
    df = pd.DataFrame({"f": factor_values, "r": future_returns}).dropna()
    if len(df) < n_layers * 5:
        return {"layer_returns": {}, "ic": np.nan, "long_short": np.nan}

    df["layer"] = pd.qcut(df["f"], n_layers, labels=False, duplicates="drop")
    layer_mean = df.groupby("layer")["r"].mean().to_dict()
    ic = df["f"].corr(df["r"], method="spearman")
    layers = sorted(layer_mean.keys())
    long_short = layer_mean[layers[-1]] - layer_mean[layers[0]] if len(layers) >= 2 else np.nan

    return {
        "layer_returns": {int(k): float(v) for k, v in layer_mean.items()},
        "ic": float(ic) if pd.notna(ic) else None,
        "long_short": float(long_short) if pd.notna(long_short) else None,
    }


# ============================================================
# 六-bis、多因子评价 (融合 网格/机器学习/CASE-C 三大case)
# ============================================================

def rank_score_synthesis(factor_df: pd.DataFrame,
                         direction_map: Optional[dict] = None) -> pd.Series:
    """多因子排名打分合成 (来源: CASE-网格与多因子/factor_engine.py score_stocks)

    对每个因子做横截面排名归一化(0~1), 反向因子翻转, 再等权(或按方向)加权求和。

    参数:
        factor_df:      index=股票代码, columns=因子名, value=因子值(原始或预处理后)
        direction_map:  {factor_id: 1/-1/0} 因子方向, 1为正(值越大越好), -1为负, 0为双向
    返回: 综合得分 Series (index=股票代码)
    """
    score = pd.Series(index=factor_df.index, dtype=float)
    weight_sum = 0.0
    for col in factor_df.columns:
        # 横截面排名归一化 0~1
        rank = factor_df[col].rank(pct=True)
        direction = 1
        if direction_map:
            direction = direction_map.get(col, 1) or 1
        # 反向因子翻转: 值越小越好, 排名取反
        if direction < 0:
            rank = 1 - rank
        if score.isna().all():
            score = rank * 1.0
        else:
            score = score.add(rank, fill_value=0.0)
        weight_sum += 1.0
    if weight_sum > 0:
        score = score / weight_sum
    return score


def factor_correlation_matrix(factor_df: pd.DataFrame,
                              method: str = "spearman") -> Dict[str, Any]:
    """计算技术类因子两两相关性矩阵 (来源: 机器学习case 因子筛选思路)

    参数:
        factor_df: index=股票代码, columns=因子名
        method:    "spearman" / "pearson"
    返回: {corr_matrix: {factor: {factor: value}}, pairs: [{f1,f2,corr}]}
    """
    if factor_df.shape[1] < 2:
        return {"corr_matrix": {}, "pairs": []}
    corr = factor_df.corr(method=method)
    corr_dict = {c: {cc: (None if pd.isna(corr.loc[c, cc]) else round(float(corr.loc[c, cc]), 4))
                     for cc in corr.columns} for c in corr.index}
    pairs = []
    for i, f1 in enumerate(corr.index):
        for f2 in corr.columns[i + 1:]:
            v = corr.loc[f1, f2]
            if pd.notna(v):
                pairs.append({"f1": f1, "f2": f2, "corr": round(float(v), 4)})
    pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
    return {"corr_matrix": corr_dict, "pairs": pairs}


# 成交额面板缓存 (供市值代理逐截面复用, 避免每期重复扫描全市场构建面板)
_AMOUNT_PANEL_CACHE: "OrderedDict[tuple, Optional[pd.DataFrame]]" = OrderedDict()
_AMOUNT_PANEL_CACHE_MAX = 10


def _amount_panel(prices_panel: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    """构建全市场成交额面板 (index=日期并集, columns=股票代码, 缺行补NaN) 并缓存

    同一面板对象逐截面复用, 由 _panel_cache_key 保证内容变化时不命中旧缓存。
    """
    key = _panel_cache_key(prices_panel)
    if key is not None:
        hit = _AMOUNT_PANEL_CACHE.get(key)
        if hit is not None:
            _AMOUNT_PANEL_CACHE.move_to_end(key)
            return hit
    rows = {}
    for code, df in prices_panel.items():
        if "amount" in df.columns:
            rows[code] = pd.to_numeric(df["amount"], errors="coerce")
    amt = pd.DataFrame(rows) if rows else None  # 外连接(索引并集), 缺行补NaN
    if key is not None:
        _AMOUNT_PANEL_CACHE[key] = amt
        if len(_AMOUNT_PANEL_CACHE) > _AMOUNT_PANEL_CACHE_MAX:
            _AMOUNT_PANEL_CACHE.popitem(last=False)
    return amt


def build_marketcap_proxy_map(prices_panel: Dict[str, pd.DataFrame],
                              date: pd.Timestamp,
                              lookback: int = 20) -> Dict[str, float]:
    """构建某个截面日期的"市值代理"映射 (点-in-time, 无前视)

    修复背景: 旧实现用"最新总股本 × 当前收盘价"的静态单值映射作用于全部历史截面,
    存在时点错配(用今天的市值去中性化历史截面)。
    本函数改用截面当日可得的数据构造代理 —— 近 lookback 个交易日成交额均值
    (参考: CASE-机器学习因子挖掘 用 close×volume 滚动均值做市值代理),
    成交额与市值在截面内高度相关、且当日可得, 逐截面构造无前视、无性能压力。

    参数:
        prices_panel: {stock_code: DataFrame(含 amount 列, index=日期)}
        date:         截面日期
        lookback:     成交额滚动窗口 (交易日)
    返回: {stock_code: 代理值}, 无成交额数据的股票不纳入。

    性能优化: 一次性构建成交额面板并缓存, 按日期切片后逐列取近N日均值,
    替代逐股循环, 多截面调用时不再重复扫描全市场。
    """
    amt = _amount_panel(prices_panel)
    if amt is None or len(amt) == 0:
        return {}
    try:
        sub = amt.loc[:date]
    except Exception:
        return {}
    if len(sub) == 0:
        return {}
    # 逐列取近 lookback 个非空值均值: 与原逐股实现 df.loc[:date].dropna().tail().mean() 口径完全一致
    means = sub.apply(lambda s: s.dropna().tail(lookback).mean())
    return {code: float(v) for code, v in means.items() if pd.notna(v) and v > 0}


def marketcap_neutralize(factor_series: pd.Series,
                         marketcap_map: Optional[dict] = None,
                         industry_map: Optional[dict] = None) -> pd.Series:
    """市值/行业中性化 (来源: CASE-机器学习因子挖掘/feature_engine.py neutralice)

    用 行业哑变量 + ln(市值) 做回归, 取残差作为中性化后的因子值。
    若缺少市值或行业数据, 回退为普通 Z-score。

    参数:
        factor_series: 因子值 (index=股票代码)
        marketcap_map: {stock_code: 市值(float)}, 可选
        industry_map:  {stock_code: 行业(float)}, 可选
    返回: 中性化后 Series
    """
    if not marketcap_map or not industry_map:
        # 数据不足, 回退为 z-score
        return zscore(factor_series)
    df = pd.DataFrame({"factor": factor_series})
    mc = pd.Series([marketcap_map.get(i, np.nan) for i in factor_series.index],
                   index=factor_series.index)
    ind = pd.Series([industry_map.get(i, "unknown") for i in factor_series.index],
                    index=factor_series.index)
    # mc<=0 置 NaN, 避免对非正值求 log 产生 invalid 警告 (市值应恒为正)
    df["lnmc"] = np.log(mc.where(mc > 0))
    df["industry"] = ind
    df = df.dropna(subset=["factor", "lnmc"])
    if len(df) < 10:
        return zscore(factor_series)
    try:
        import statsmodels.api as sm
    except ImportError:
        return zscore(factor_series)
    try:
        X = pd.get_dummies(df["industry"], prefix="ind", drop_first=False)
        X = pd.concat([X, df["lnmc"]], axis=1)
        X = sm.add_constant(X)
        y = df["factor"]
        model = sm.OLS(y, X).fit()
        residual = y - model.predict(X)
        out = pd.Series(index=factor_series.index, dtype=float)
        out.loc[residual.index] = residual
        # 残差标准化
        out = zscore(out)
        return out
    except Exception:
        return zscore(factor_series)


def neutralize_regression(factor_series: pd.Series,
                          group_map: Optional[dict] = None,
                          marketcap_map: Optional[dict] = None) -> pd.Series:
    """通用中性化: 分组哑变量(行业/板块/概念) + ln(市值) 回归取残差

    与机器学习case的 neutralize 一致, 扩展为可任意组合分组维度与市值:
      - 仅分组:     factor ~ 分组哑变量 取残差
      - 仅市值:     factor ~ ln(市值) 取残差
      - 分组+市值:  factor ~ 分组哑变量 + ln(市值) 取残差 (机器学习case标准做法)

    残差即"剔除了这些维度影响后"的因子值, 中性化后再统一 Z-score。
    """
    if not group_map and not marketcap_map:
        return zscore(factor_series)
    df = pd.DataFrame({"factor": factor_series})
    X_parts = []
    if group_map:
        df["group"] = [group_map.get(i, "unknown") for i in factor_series.index]
        X_parts.append(pd.get_dummies(df["group"], prefix="g", drop_first=False))
    if marketcap_map:
        mc = pd.Series([marketcap_map.get(i, np.nan) for i in factor_series.index],
                       index=factor_series.index)
        # mc<=0 置 NaN, 避免对非正值求 log 产生 invalid 警告 (市值应恒为正)
        X_parts.append(np.log(mc.where(mc > 0)).rename("lnmc"))
    if not X_parts:
        return zscore(factor_series)
    X = pd.concat(X_parts, axis=1)
    df = pd.concat([df, X], axis=1).dropna(subset=["factor"] + list(X.columns))
    if len(df) < 10:
        return zscore(factor_series)
    try:
        # 中性化: 分组哑变量 + ln(市值) 线性回归取残差
        # 常数项用 numpy 显式拼接 (与 sm.add_constant 等价), 彻底去掉 statsmodels 依赖:
        # Agu-2 生产环境未安装 statsmodels, 原实现 import 失败会静默回退 zscore,
        # 导致"分组/市值中性化"从未真正生效; 最小二乘残差在回归列空间上是唯一的,
        # 与 OLS 数学等价 (秩亏时取最小范数解, 残差不变)。
        y = df["factor"].to_numpy(dtype=float)
        Xmat = np.column_stack([np.ones(len(df)), X.loc[df.index].to_numpy(dtype=float)])
        coef, *_ = np.linalg.lstsq(Xmat, y, rcond=None)
        residual = y - Xmat @ coef
        out = pd.Series(index=factor_series.index, dtype=float)
        out.loc[df.index] = residual
        return out
    except Exception:
        return zscore(factor_series)


def _cross_section_future_return(prices_panel: Dict[str, pd.DataFrame],
                                 dates_idx: pd.DatetimeIndex,
                                 date_idx: int,
                                 rebal_period: int,
                                 n: int) -> pd.Series:
    """计算某调仓日的截面未来收益 (t 到 t+rebal_period)

    参数:
        prices_panel: {stock_code: DataFrame(index=日期, close)}
        dates_idx:    基准交易日历 (首只股票)
        date_idx:     调仓日位置索引
        rebal_period: 持有期
        n:            总长度
    返回: Series (index=股票代码, value=未来收益)

    修复: 旧实现按位置 iloc[date_idx] 取价, 停牌缺行股票的日期会与基准日历错位;
          现改为按日期对齐 (dates_idx 的日期在每股 index 上查找)。
    """
    end = min(date_idx + rebal_period, n - 1)
    d0 = dates_idx[date_idx]
    d1 = dates_idx[end]
    ret = {}
    for code, df in prices_panel.items():
        if d0 in df.index and d1 in df.index:
            p0 = df.at[d0, "close"]
            p1 = df.at[d1, "close"]
            if pd.notna(p0) and p0 > 0 and pd.notna(p1):
                ret[code] = p1 / p0 - 1
    return pd.Series(ret)


def _preprocess_cross_section(cross: pd.DataFrame,
                              sector_map: Optional[dict],
                              concept_map: Optional[dict],
                              industry_map: Optional[dict],
                              marketcap_map: Optional[dict],
                              winsorize_n: float = 3.0,
                              fill_na: bool = False) -> pd.DataFrame:
    """对单个截面的因子值做预处理(逐列): 去极值 + 中性化(市值/分组回归取残差) + z-score

    中性化支持市值与分组维度(行业/板块/概念)组合: 分组哑变量 + ln(市值) 回归取残差,
    两者可叠加(与机器学习case一致), 也可只开其一或都不开(仅Z-score)。

    参数:
        cross:        index=股票代码, columns=因子名 (原始因子值)
        winsorize_n:  MAD 去极值倍数 (默认 3.0; ML 方法按机器学习case用 5.0)
        fill_na:      是否用列中位数填充缺失值 (机器学习case标准, 默认 False 对齐 CASE-C)

    返回: 预处理后的 DataFrame (index=股票代码, columns=因子名)
    """
    pre = cross.copy()
    for col in pre.columns:
        pre[col] = winsorize_mad(pre[col], n=winsorize_n)
        if fill_na:
            # 缺失值用列中位数填充 (对齐 feature_engine.preprocess_features)
            pre[col] = pre[col].fillna(pre[col].median())
        # 分组维度: sector/concept/industry 三选一 (调用方只传其一)
        group_map = sector_map or concept_map or industry_map
        if marketcap_map is not None or group_map is not None:
            # 统一回归取残差: 分组哑变量 + ln(市值) 一起回归 (可叠加, 与机器学习case一致)
            pre[col] = neutralize_regression(pre[col], group_map, marketcap_map)
        else:
            pre[col] = zscore(pre[col])
        # 中性化后再做一次全市场 Z-score, 让所有分组可比 (对齐 CASE-C/preprocessor.py)
        if marketcap_map is not None or group_map is not None:
            pre[col] = zscore(pre[col])
    return pre


def _ml_fit_model(X_train: pd.DataFrame, y_train: pd.Series,
                  ml_params: Optional[dict] = None):
    """训练 ML 回归模型 (来源: 机器学习case + 网格ML增强)

    支持三种模型: XGBoost / LightGBM / RandomForest, 参数可配置。
    请求的模型 import 失败时按 xgboost -> lightgbm -> rf 顺序回退。
    用于多因子合成的 walk-forward: 用历史截面特征拟合未来收益, 预测当期综合因子。
    """
    params = ml_params or {}
    model_type = str(params.get("model_type", "xgboost")).lower()
    n_estimators = int(params.get("n_estimators", 100))
    max_depth = int(params.get("max_depth", 3))
    learning_rate = float(params.get("learning_rate", 0.05))
    subsample = float(params.get("subsample", 0.8))
    colsample = float(params.get("colsample_bytree", 0.8))
    reg_alpha = float(params.get("reg_alpha", 0.1))
    reg_lambda = float(params.get("reg_lambda", 1.0))

    if model_type == "lightgbm":
        try:
            from lightgbm import LGBMRegressor
            return LGBMRegressor(
                n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate, num_leaves=max(2, min(2 ** max_depth, 31)),
                subsample=subsample, colsample_bytree=colsample,
                reg_alpha=reg_alpha, reg_lambda=reg_lambda,
                random_state=42, verbose=-1,
            ).fit(X_train, y_train)
        except ImportError:
            pass
    elif model_type == "rf":
        try:
            from sklearn.ensemble import RandomForestRegressor
            return RandomForestRegressor(
                n_estimators=n_estimators, max_depth=max(2, max_depth),
                min_samples_leaf=20, random_state=42,
            ).fit(X_train, y_train)
        except ImportError:
            pass
    # 默认 / 回退: XGBoost
    try:
        from xgboost import XGBRegressor
        return XGBRegressor(
            n_estimators=n_estimators, max_depth=max_depth,
            learning_rate=learning_rate, subsample=subsample,
            colsample_bytree=colsample, reg_alpha=reg_alpha,
            reg_lambda=reg_lambda, random_state=42,
        ).fit(X_train, y_train)
    except ImportError:
        from lightgbm import LGBMRegressor
        return LGBMRegressor(
            n_estimators=n_estimators, max_depth=max_depth,
            learning_rate=learning_rate, subsample=subsample,
            colsample_bytree=colsample, reg_alpha=reg_alpha,
            reg_lambda=reg_lambda, random_state=42, verbose=-1,
        ).fit(X_train, y_train)


def _extract_feature_importance(model, feature_names: List[str]) -> dict:
    """提取 ML 模型的特征重要性 (归一化到总和为1), 返回 {factor_id: importance}

    兼容 XGBoost/LightGBM/RandomForest (均有 feature_importances_)。
    """
    try:
        imp = np.asarray(model.feature_importances_, dtype=float)
    except Exception:
        return None
    if imp is None or len(imp) == 0:
        return None
    s = imp.sum()
    if s <= 0:
        return None
    imp = imp / s
    out = {}
    for name, v in zip(feature_names, imp):
        out[str(name)] = round(float(v), 6)
    # 按重要性降序
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def _synthesize_cross_section(cross: pd.DataFrame,
                              method: str,
                              sector_map: Optional[dict],
                              concept_map: Optional[dict],
                              industry_map: Optional[dict],
                              marketcap_map: Optional[dict],
                              direction_map: Optional[dict],
                              ic_weights: Optional[dict] = None) -> pd.Series:
    """对单个截面的因子值做预处理 + 合成, 得到综合因子值 (index=股票代码)

    参数:
        cross:         index=股票代码, columns=因子名 (原始因子值)
        method:        合成方法 equal/ic_weighted/rank_score
        ic_weights:    {factor_id: 权重} 用于 ic_weighted
    返回: 综合因子值 Series
    """
    pre = _preprocess_cross_section(cross, sector_map, concept_map, industry_map, marketcap_map)

    valid = pre.dropna(how="any")
    if len(valid) < 5:
        return pd.Series(dtype=float)

    if method == "rank_score":
        score = rank_score_synthesis(valid, direction_map)
    elif method == "ic_weighted" and ic_weights:
        score = ic_weighted_synthesis(valid, ic_weights)
    else:
        score = equal_weight_synthesis(valid)
    return score


def _synthesize_preprocessed(pre: pd.DataFrame,
                             method: str,
                             direction_map: Optional[dict],
                             ic_weights: Optional[dict] = None) -> pd.Series:
    """对已预处理/清洗后的截面做合成, 得到综合因子值 (index=股票代码)

    与 _synthesize_cross_section 的区别: 传入的 pre 已经完成预处理清洗,
    这里不再重复预处理, 直接按方法合成。用于多因子分阶段流程(B1预处理缓存后复用)。

    修复(C4): 旧实现要求所有因子非空(dropna(how="any"))才参与合成, 加入缺失较多的
    因子后大量股票被静默排除; 现放宽为允许部分缺失(dropna(how="all")),
    排名/加权合成对缺失因子按"不贡献"处理(pandas add/mean 默认 skipna)。
    ML/Lasso 等模型方法仍需要完整特征, 在调用方单独处理。
    """
    valid = pre.dropna(how="all")
    if len(valid) < 5:
        return pd.Series(dtype=float)
    if method == "rank_score":
        return rank_score_synthesis(valid, direction_map)
    elif method == "ic_weighted" and ic_weights:
        return ic_weighted_synthesis(valid, ic_weights)
    else:
        return equal_weight_synthesis(valid)


def prep_multi_factor(factor_panels: Dict[str, pd.DataFrame],
                      prices_panel: Dict[str, pd.DataFrame],
                      rebal_period: int = 21,
                      min_warmup: int = 130,
                      sector_map: Optional[dict] = None,
                      concept_map: Optional[dict] = None,
                      industry_map: Optional[dict] = None,
                      marketcap_map: Optional[dict] = None,
                      marketcap_proxy_lookback: Optional[int] = None,
                      min_factors: int = 2) -> Dict[str, Any]:
    """阶段B1: 多因子数据准备 (共用固定, 与合成方式无关)

    构建调仓日序列 -> 逐期构建截面 -> 预处理清洗(统一 3倍MAD + 中位数填充 + 中性化)
    产出所有依赖合成方式之前的数据, 供后续任一合成方式复用。

    参数:
        min_factors: 每期截面最少因子数 (默认2=需要合成; F2 仅信号模式传1,
                     综合信号方向得分作为单一合成因子)。

    返回:
        {
            "rebal_dates": List[int],
            "dates_idx":   pd.DatetimeIndex,
            "preprocessed_crosses": {t: DataFrame(已清洗截面)},
            "future_returns":       {t: Series(未来收益, 与合成方式无关)},
            "factor_stats": List[dict],   # 每因子的清洗后分布/残缺诊断
            "coverage_by_date": List[dict],
            "n_rebalances": int,
        }
    """
    first_code = next(iter(prices_panel))
    dates_idx = prices_panel[first_code].index
    n = len(dates_idx)
    if n < 50:
        return {"error": "价格数据过短, 无法多因子评价"}

    rebal_dates = list(range(min_warmup, n - rebal_period - 1, rebal_period))

    preprocessed_crosses = {}   # t -> 已清洗截面 DataFrame
    future_returns = {}         # t -> 未来收益 Series
    date_coverage = []          # 每期 {date, factor_id, count, total}

    for t in rebal_dates:
        date = dates_idx[t]
        cross = {}
        for fid, panel in factor_panels.items():
            if date in panel.index:
                cross[fid] = panel.loc[date]
        if len(cross) < min_factors:
            continue
        cross_df = pd.DataFrame(cross)
        # 市值代理 (点-in-time): 每期用截面当日可得的近N日成交额均值, 替代静态市值快照
        mc_map = marketcap_map
        if marketcap_proxy_lookback:
            mc_map = build_marketcap_proxy_map(prices_panel, date,
                                               lookback=marketcap_proxy_lookback)
        # 统一清洗: 3倍MAD去极值 + 中位数填充缺失 + 中性化 (对齐项目约定, 与合成方式无关)
        pre = _preprocess_cross_section(cross_df, sector_map, concept_map,
                                        industry_map, mc_map,
                                        winsorize_n=3.0, fill_na=True)
        fut = _cross_section_future_return(prices_panel, dates_idx, t, rebal_period, n)
        if len(fut) < 10:
            continue
        preprocessed_crosses[t] = pre
        future_returns[t] = fut
        # 记录该期每因子的非空数量 (用于残缺诊断)
        for fid in pre.columns:
            date_coverage.append({
                "date": str(date.date()),
                "factor_id": fid,
                "count": int(pre[fid].notna().sum()),
                "total": int(len(pre)),
            })

    if not preprocessed_crosses:
        return {"error": "多因子数据准备无有效截面样本"}

    # 每因子的清洗后统计诊断
    n_rebal = len(preprocessed_crosses)
    factor_stats_list = []
    factor_ids = list(preprocessed_crosses[next(iter(preprocessed_crosses))].columns)
    for fid in factor_ids:
        total_cells = 0
        nan_count = 0
        vals = []
        rebal_ok = 0
        for t, pre in preprocessed_crosses.items():
            s = pre[fid]
            total_cells += int(len(s))
            nan_count += int(s.isna().sum())
            if s.notna().sum() >= 5:
                rebal_ok += 1
            vals.append(s.dropna())
        if vals:
            allv = pd.concat(vals)
            count = int(allv.notna().sum())
            factor_stats_list.append({
                "factor_id": fid,
                "count": count,
                "nan_ratio": round(float(nan_count / total_cells), 4) if total_cells else 0.0,
                "non_null_rate": round(float(1 - nan_count / total_cells), 4) if total_cells else 0.0,
                "mean": round(float(allv.mean()), 4) if count else None,
                "std": round(float(allv.std()), 4) if count > 1 else None,
                "min": round(float(allv.min()), 4) if count else None,
                "max": round(float(allv.max()), 4) if count else None,
                "rebal_coverage": round(float(rebal_ok / n_rebal), 4) if n_rebal else 0.0,
            })

    return {
        "rebal_dates": rebal_dates,
        "dates_idx": dates_idx,
        "preprocessed_crosses": preprocessed_crosses,
        "future_returns": future_returns,
        "factor_stats": factor_stats_list,
        "coverage_by_date": date_coverage,
        "n_rebalances": n_rebal,
        "prep_diagnostics": {
            "factor_stats": factor_stats_list,
            "coverage_by_date": date_coverage,
            "n_rebalances": n_rebal,
        },
    }


# ============================================================
# 六-ter、因子筛选/去冗余/方向/权重优化/PCA/ML分类 (清华+机器学习case)
# ============================================================

# 多因子合成可配置参数默认值 (全部可从前端覆盖)
DEFAULT_SYNTH_CFG = {
    "screening": {
        "enable": True,
        "ic_thresh": 0.02,          # IC阈值: |平均IC|低于此值的因子被淘汰
        "min_non_null": 0.5,        # 最小非空率
        "min_rebal_coverage": 0.5,  # 最小调仓覆盖率
    },
    "redundancy": {
        "enable": True,
        "corr_thresh": 0.8,         # 相关性阈值: |corr|高于此值的因子去冗余
    },
    "direction": {
        "auto": True,               # 是否自动判断因子方向(按历史IC符号; 仅对未指定方向的因子生效)
        "override_manual": False,   # True 时: 开启自动判断后连手工配置的方向也交由历史IC决定
                                    # (用于手工方向不确定的场景; 仅 auto=True 时生效)
    },
    "pca": {
        "n_components": None,       # 主成分个数, None=按解释方差自动
        "explained_var": 0.9,       # 累计解释方差阈值
    },
    "optuna": {
        "n_trials": 15,             # Optuna 搜索次数
    },
    "ml": {
        "importance_feedback": False, # 特征重要性→筛选反馈(默认关闭: 先展示, 由前端点击按钮触发)
        "min_importance": 0.02,       # 特征重要性保留阈值
        "purged_cv": True,            # purged 时序K折CV评估
        "n_splits": 5,
        "gap": 5,
        "retrain_every": 4,           # ML 模型每 N 个调仓期用累积历史重训一次(避免冻结模型失效)
    },
}


def _normalize_synth_cfg(synth_cfg: Optional[dict]) -> Dict[str, Any]:
    """规范化合成配置: 用默认值填充未提供的项"""
    import copy
    cfg = copy.deepcopy(DEFAULT_SYNTH_CFG)
    if synth_cfg:
        for k, v in synth_cfg.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ============================================================
# F0 合成方法与因子类型兼容性声明 (2026-08-15, 详见 docs/因子库F阶段-综合多因子分析设计文档.md 〇·九)
#   accepts:      可参与连续合成的因子类型 (signal 因子恒走独立轨, 不在此列)
#   requires_cov: 是否需要因子协方差矩阵(连续因子不足/协方差不可算时降级等权+警告)
# 说明: F2 起财务(financial)因子进连续合成(财报可用日 asof 对齐后量纲统一参与合成);
#       signal 因子走"信号方向得分"独立轨, 最后与连续合成汇总, 不进本表。
# ============================================================
METHOD_FACTOR_COMPAT = {
    "equal":        {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "ic_weighted":  {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "rank_score":   {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "lasso":        {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "ml_reg":       {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "ml_cls":       {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "markowitz":    {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": True},
    "optuna":       {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": True},
    "sharpe":       {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": False},
    "pca":          {"accepts": ("technical", "technical_ts", "financial"), "requires_cov": True},
}


# ============================================================
# F0 预检与自动匹配规划器 (2026-08-15, 详见 docs/因子库F阶段-综合多因子分析设计文档.md 五·1/〇·九)
#   preflight_factors:  合成前静态预检(存在/可计算/类型判定), 只标记不阻塞
#   auto_match_factors: 方法×类型自动匹配(按 METHOD_FACTOR_COMPAT 判定可用性/排除/降级)
# 原则: 任何因子特例都不应让多因子流程崩溃; 不兼容因子自动移出合成并显式列原因。
# ============================================================

def preflight_factors(factor_ids: List[str]) -> Dict[str, Any]:
    """F0 预检: 对每个选中因子做合成前的静态检查 (不阻塞, 只标记)

    检查项:
      1. 是否存在 (factor_library 有记录)
      2. 是否可计算 (formula 非空、无中文描述, 即非文字化因子)
      3. evaluation_type 判定 (technical/technical_ts/financial/signal/none)

    返回:
      {
        "factors": [{factor_id, name, factor_type, status: ok|skip|error, reason}],
        "ok_ids": [], "skip_ids": [], "error_ids": [], "summary": "..."
      }
    """
    from lib.factor_db import get_factor
    factors = []
    ok_ids, skip_ids, error_ids = [], [], []
    for fid in factor_ids:
        info = get_factor(fid) or {}
        name = info.get("name") or fid
        if not info:
            error_ids.append(fid)
            factors.append({"factor_id": fid, "name": name, "factor_type": "unknown",
                            "status": "error", "reason": "因子库中不存在该因子"})
            continue
        ftype = classify_factor_type(info)
        formula = str(info.get("formula") or "").strip()
        has_cn = any('\u4e00' <= ch <= '\u9fff' for ch in formula)
        if not formula or has_cn:
            error_ids.append(fid)
            factors.append({"factor_id": fid, "name": name, "factor_type": ftype,
                            "status": "error",
                            "reason": "因子无有效公式或为文字化描述, 无法计算"})
            continue
        if ftype == "none":
            skip_ids.append(fid)
            factors.append({"factor_id": fid, "name": name, "factor_type": ftype,
                            "status": "skip",
                            "reason": "该因子为不可独立评价类型(none), 仅作单因子展示"})
            continue
        ok_ids.append(fid)
        factors.append({"factor_id": fid, "name": name, "factor_type": ftype,
                        "status": "ok", "reason": ""})
    summary = (f"预检通过 {len(ok_ids)} 个, 跳过 {len(skip_ids)} 个, "
               f"异常 {len(error_ids)} 个")
    return {"factors": factors, "ok_ids": ok_ids, "skip_ids": skip_ids,
            "error_ids": error_ids, "summary": summary}


def auto_match_factors(method: str, continuous_ids: List[str],
                       factor_infos: Dict[str, Any]) -> Dict[str, Any]:
    """F0 方法×类型自动匹配规划器: 判定合成方法可用性, 自动排除不兼容因子, 给出降级建议

    依据 METHOD_FACTOR_COMPAT 中该方法的 accepts/requires_cov 声明:
      1. 连续轨中不属于 accepts 的因子 -> 自动移出合成(excluded), 不报错
      2. requires_cov 且剩余连续因子 < 2 -> 降级等权 + 警告
      3. 无剩余连续因子 -> usable=False, 提示补充连续因子或改用信号组合轨

    返回:
      {
        "method": method,
        "accepted_types": [...],
        "requires_cov": bool,
        "synthesis_ids": [...],      # 实际参与合成的连续因子
        "excluded": [{factor_id, factor_type, reason}],
        "usable": bool,
        "degraded_method": None|"equal",
        "warning": "..."|None,
      }
    """
    compat = METHOD_FACTOR_COMPAT.get(method)
    if compat is None:
        return {"method": method, "accepted_types": [], "requires_cov": False,
                "synthesis_ids": [], "excluded": [], "usable": False,
                "degraded_method": None, "warning": f"未知合成方法 {method}, 无法合成"}
    accepted_types = compat["accepts"]
    requires_cov = compat["requires_cov"]
    excluded = []
    synthesis_ids = []
    for fid in continuous_ids:
        ftype = classify_factor_type(factor_infos.get(fid) or {})
        if ftype in accepted_types:
            synthesis_ids.append(fid)
        else:
            excluded.append({
                "factor_id": fid,
                "factor_type": ftype,
                "reason": (f"合成方法 {method} 不支持 {ftype} 类型因子, "
                           f"已自动移出连续合成(保留单因子评价)"),
            })
    warning = None
    degraded_method = None
    if not synthesis_ids:
        return {"method": method, "accepted_types": list(accepted_types),
                "requires_cov": requires_cov, "synthesis_ids": [],
                "excluded": excluded, "usable": False, "degraded_method": None,
                "warning": "无有效连续因子可合成, 请补充连续型因子或改用信号组合轨"}
    if requires_cov and len(synthesis_ids) < 2:
        degraded_method = "equal"
        warning = (f"合成方法 {method} 需要因子协方差矩阵, 但有效连续因子仅 "
                   f"{len(synthesis_ids)} 个, 已自动降级为等权合成")
    return {"method": method, "accepted_types": list(accepted_types),
            "requires_cov": requires_cov, "synthesis_ids": synthesis_ids,
            "excluded": excluded, "usable": True,
            "degraded_method": degraded_method, "warning": warning}


# ============================================================
# F1 组合风险分析 (2026-08-15, 详见 docs/因子库F阶段-综合多因子分析设计文档.md 四/〇·六阶段二)
#   通用 Barra 风险阶段: 不依赖用户是否选中 Barra 因子, 每次多因子合成后自动附加。
#   build_barra_style_panels: 由日K直接计算 6 个价量 Barra 风格暴露面板 (通用风险标尺)
#   analyze_portfolio_risk:   组合风格暴露度量 + 风险分解 + 归因 + 组合中性化(可选)
# 说明: 财务类 Barra 风格(BTOP/PROFIT/GROWTH/LEVERAGE)依赖财报数据, 不在此通用标尺内。
# ============================================================

# Barra 风格面板标识与中文标签 (价量可计算子集)
BARRA_STYLE_LABELS = {
    "SIZE": "规模",
    "BETA": "Beta",
    "MOMENTUM": "动量",
    "RESVOL": "残差波动",
    "NONLINEAR_MV": "非线性市值",
    "LIQUIDITY": "流动性",
}


def build_barra_style_panels(prices_panel: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """F1 通用基础设施: 计算 Barra 风格暴露面板 (与因子库 BARRA_* 同算子口径)

    仅取可由日K直接计算的 6 个价量风格 (财务类风格需财报数据, 不在通用风险标尺内):
      SIZE=ln(20日均额)  BETA=250日Beta(市场=截面均值)  MOMENTUM=504日Barra动量
      RESVOL=250日残差波动  NONLINEAR_MV=ln(20日均额)^3  LIQUIDITY=-ln(21日换手均值)

    返回: {style: DataFrame(index=日期, columns=股票代码, values=风格暴露)}
    """
    field_dfs = _build_field_dfs(prices_panel)
    styles: Dict[str, pd.DataFrame] = {}
    close = field_dfs.get("Close")
    amount = field_dfs.get("Amount")
    turn = field_dfs.get("Turnover")
    if amount is not None:
        log_amt = ts_Log(ts_Mean(amount, 20))
        styles["SIZE"] = log_amt
        styles["NONLINEAR_MV"] = log_amt ** 3
    if close is not None:
        styles["BETA"] = ts_BETA(close, 250)
        styles["MOMENTUM"] = ts_BarraMomentum(close, 504)
        styles["RESVOL"] = ts_RESVOL(close, 250)
    if turn is not None:
        styles["LIQUIDITY"] = -ts_Log(ts_Mean(turn, 21))
    return styles


def _cs_winsorize_zscore(s: pd.Series) -> pd.Series:
    """截面稳健标准化: 3倍MAD去极值(与因子预处理同约定)后 Z-score
    输入为单期截面 Series(index=股票代码), 输出标准化后 Series"""
    s = s.astype(float)
    med = s.median()
    mad = (s - med).abs().median()
    if pd.isna(mad) or mad <= 0:
        mad = s.std()
    if pd.isna(mad) or mad <= 0:
        return s.fillna(0.0) * 0.0
    scale = 1.4826 * mad
    lo, hi = med - 3 * scale, med + 3 * scale
    s = s.clip(lo, hi)
    std = s.std()
    if pd.isna(std) or std <= 0:
        return s.fillna(0.0) * 0.0
    return (s - s.mean()) / std


# ============================================================
# F2 信号方向得分独立轨 (2026-08-15, 详见 docs/因子库F阶段-综合多因子分析设计文档.md 〇·五/〇·七)
#   信号(signal)因子是离散 0/1 或 -1/0/+1、稀疏, 不能直接进 IC 加权/协方差类合成。
#   方案: 按信号方向语义转成"方向得分"(每股 -1~+1), 与连续合成分开计算, 最后汇总。
#   - 双极性(CDL 0/±100): 值>0 看涨(+1)、值<0 看跌(-1)、0 无信号
#   - 单极性(0/1 事件): 按 factor direction 判多空 (1=看涨事件, -1=看跌事件)
#   多信号因子时取平均, 得到每股综合信号方向得分 (与 evaluate_pattern_factor 同方向语义)。
# ============================================================

def _signal_score_panel(fv: pd.DataFrame, direction: int) -> pd.DataFrame:
    """单个信号因子 -> 方向得分面板 (值 ∈ {-1,0,1}, 缺失保持 NaN)
    direction 仅对单极性(0/1)因子生效; 双极性按值符号

    修复: 原 (fv>0)-(fv<0) 会把 NaN 判为 0-0=0, 与"缺失保持NaN"的注释不符;
         现用 .where(fv.notna()) 保留 NaN, 供综合得分按"非空计数"仅非空平均。
    """
    flat = fv.values.flatten()
    flat = flat[~pd.isna(flat)]
    has_negative = bool((flat < -1e-9).any()) if len(flat) else False
    # (v>0) - (v<0): 双极性 1/-1/0; 单极性仅 1/0 (v<0 恒 False); NaN 保持 NaN
    score = ((fv > 0).astype(float) - (fv < 0).astype(float)).where(fv.notna())
    if not has_negative and direction < 0:
        # 单极性看跌事件(如20日新低): 事件发生(1) → 得分 -1
        score = -score
    return score


def build_signal_direction_score_panel(signal_panels: Dict[str, pd.DataFrame],
                                       factor_infos: Dict[str, Any]) -> Dict[str, Any]:
    """F2 信号方向得分独立轨: 多个信号因子 -> 每股综合信号方向得分面板

    返回:
      {
        "score_panel":  DataFrame(index=日期, columns=股票, values=综合方向得分∈[-1,1]),
        "per_factor":   {fid: {direction, bipolar, score_panel}},
        "signal_ids":   [...],
      }
    """
    if not signal_panels:
        return {"score_panel": None, "per_factor": {}, "signal_ids": []}
    per_factor = {}
    score_panels = []
    for fid, fv in signal_panels.items():
        info = factor_infos.get(fid) or {}
        direction = direction_to_int(info.get("direction"))
        sp = _signal_score_panel(fv, direction)
        flat = fv.values.flatten()
        flat = flat[~pd.isna(flat)]
        bipolar = bool((flat < -1e-9).any()) if len(flat) else False
        per_factor[fid] = {
            "direction": direction,
            "bipolar": bipolar,
            "score_panel": sp,
        }
        score_panels.append(sp)
    # 综合 = 多因子得分逐股等权平均 (仅非空平均; 全空保持 NaN)
    # 修复: 原 sum/n 在任一信号因子某格缺失(NaN)时整格变 NaN, 未实现"仅非空平均";
    #       现按"非空因子计数"动态加权: 某股某日只有部分信号可用时, 用可用信号的平均
    #       作为综合得分(与消费端 score_stocks_by_package 的 sig 平均同口径)。
    # 实现: 累加"非空得分"与"非空计数", 再相除(0/0 -> NaN), 完全显式、无 pandas 版本依赖。
    acc = score_panels[0].fillna(0.0).astype(float).copy()
    cnt = score_panels[0].notna().astype(float)
    for sp in score_panels[1:]:
        acc = acc.add(sp.fillna(0.0).astype(float))
        cnt = cnt.add(sp.notna().astype(float))
    combined = acc / cnt.replace(0.0, np.nan)
    return {"score_panel": combined, "per_factor": per_factor,
            "signal_ids": list(signal_panels.keys())}


def analyze_portfolio_risk(composite_cross: Dict[int, pd.Series],
                           future_returns: Dict[int, pd.Series],
                           barra_style_panels: Dict[str, pd.DataFrame],
                           dates_idx: pd.DatetimeIndex,
                           rebal_dates: List[int],
                           top_n_list: List[int],
                           neutralize_port: bool = False) -> Dict[str, Any]:
    """F1 组合风险分析 (清华风险阶段, 通用后处理)

    基于合成后的综合因子(composite_cross)选出的 Top-N 组合, 对组合做:
      1. 风格暴露度量: 组合 vs 基准(全体等权) 在各 Barra 风格上的平均暴露差
      2. 因子协方差:   截面回归估计风格因子收益(OLS+ridge), 时序协方差年化
      3. 风险分解:     组合方差 = 风格风险 + 特质风险 (占总风险比例 + 年化波动)
      4. 归因:         组合超额收益 = 风格贡献(暴露差×因子收益) + alpha(特质贡献)
      5. 组合中性化(可选): 调整权重使风格暴露贴近基准, 报告中性化前后暴露与收益影响

    参数:
        composite_cross:  {t: Series(综合因子值, index=股票代码)}  (合成主循环产出)
        future_returns:   {t: Series(未来收益, index=股票代码)}
        barra_style_panels: build_barra_style_panels 的返回
        dates_idx:        调仓日 DatetimeIndex
        rebal_dates:      调仓日索引列表
        top_n_list:       Top-N 列表
        neutralize_port:  是否执行组合中性化(默认关)
    """
    if not composite_cross:
        return {"error": "无合成截面, 无法做组合风险分析"}
    styles = [k for k in BARRA_STYLE_LABELS if k in barra_style_panels]
    if len(styles) < 2:
        return {"error": "Barra 风格面板不足, 无法做组合风险分析"}

    # 调仓期长 (用于年化折算)
    rebal_len = 21
    if len(rebal_dates) >= 2:
        _diffs = np.diff(np.asarray(rebal_dates, dtype=float))
        rebal_len = int(round(float(np.median(_diffs))))
    ann_factor = 252.0 / max(rebal_len, 1)

    # 收集每期数据
    period_rows = []          # 每期 {t, date, X, f, resid, w_n(optional), port/bench 暴露与收益}
    factor_ret_ts: Dict[str, list] = {st: [] for st in styles}
    for t in sorted(composite_cross.keys()):
        comp = composite_cross[t]
        fut = future_returns[t]
        date = dates_idx[t]
        stocks = comp.index.intersection(fut.index)
        if len(stocks) < 10:
            continue
        # 构建风格暴露矩阵 X (n_stocks × n_styles), 逐风格截面稳健标准化
        X = pd.DataFrame(index=stocks)
        for st in styles:
            panel = barra_style_panels[st]
            if date in panel.index:
                row = panel.loc[date].reindex(stocks)
                X[st] = _cs_winsorize_zscore(row)
            else:
                X[st] = 0.0
        X = X.dropna(how="all")
        if len(X) < 10:
            continue
        # 截面对齐 (X 与 fut 都按 stocks)
        fut_a = fut.reindex(X.index)
        # 截面回归估计风格因子收益: f = inv(X'X + λI) X' fut (ridge 保证可逆)
        Xv = X.values.astype(float)
        yv = fut_a.values.astype(float)
        ok = np.isfinite(Xv).all(axis=1) & np.isfinite(yv)
        if ok.sum() < 10:
            continue
        Xv, yv = Xv[ok], yv[ok]
        lam = 0.01 * np.eye(Xv.shape[1])
        XtX = Xv.T @ Xv + lam
        try:
            f_vec = np.linalg.solve(XtX, Xv.T @ yv)
        except np.linalg.LinAlgError:
            continue
        resid = yv - Xv @ f_vec
        # 特质波动: 该期残差平方和 (池化到全期方差估计)
        idio_var_period = float(np.mean(resid ** 2))
        # 基准: 全体等权
        bench_exp = pd.Series(Xv.mean(axis=0), index=X.columns)
        # 中性化基准权重 (全体等权): w_bench = 1/n
        w_bench = pd.Series(1.0 / len(Xv), index=X.index)

        for st, fi in zip(styles, f_vec):
            factor_ret_ts[st].append(float(fi))

        for n_top in top_n_list:
            top = comp.sort_values(ascending=False).head(n_top).index
            top = [c for c in top if c in X.index]
            if not top:
                continue
            w = pd.Series(0.0, index=X.index)
            w[top] = 1.0 / len(top)
            # 组合中性化: 调整 δ 使 X'w_n = X'w_bench (贴近基准风格暴露)
            w_n = None
            port_exp_n = None
            if neutralize_port:
                diff = (Xv.T @ (w.values - w_bench.values))   # (n_styles,) 暴露差
                # δ = -X (X'X + λI)^{-1} diff, 使 X'(w+δ) ≈ X'w_bench (股票级调整)
                delta = -Xv @ np.linalg.solve(XtX, diff)      # (n_stocks,)
                w_n = w.copy()
                w_n = w_n + pd.Series(delta, index=X.index)
                port_exp_n = pd.Series(Xv.T @ w_n.values, index=X.columns)
            port_exp = pd.Series(Xv.T @ w.values, index=X.columns)
            bench_ret = float(np.mean(yv))
            port_ret = float(np.mean(yv[[c in top for c in X.index]])) if top else None
            period_rows.append({
                "t": t, "date": dates_idx[t],
                "n_top": n_top, "top": top,
                "port_exp": port_exp, "bench_exp": bench_exp,
                "port_exp_n": port_exp_n,
                "port_ret": port_ret, "bench_ret": bench_ret,
                "w": w, "w_n": w_n,
                "fut_vec": yv,   # 与 X.index 对齐的未来收益 (中性化收益影响用)
                "idio_var": idio_var_period,
                "f_vec": pd.Series(f_vec, index=X.columns),
            })
        # 注: 上面循环把每期每 top 各加一行; 为记录每期暴露需按 top 聚合。
        # 聚合放在下方统一按 n_top 收集。

    if not period_rows:
        return {"error": "组合风险分析无有效截面样本"}

    # 按 top 聚合每期数据
    by_top: Dict[int, list] = {n: [] for n in top_n_list}
    for row in period_rows:
        by_top[row["n_top"]].append(row)

    # 风格因子协方差矩阵 (年化)
    cov_f = pd.DataFrame(index=styles, columns=styles, dtype=float)
    fr_mat = np.column_stack([factor_ret_ts[st] for st in styles])
    if fr_mat.shape[0] >= 2:
        cov = np.cov(fr_mat, rowvar=False) * ann_factor
    else:
        cov = np.eye(len(styles)) * 1e-6
    for i, st in enumerate(styles):
        for j, st2 in enumerate(styles):
            cov_f.loc[st, st2] = float(cov[i, j])

    out_top = {}
    for n_top in top_n_list:
        rows = by_top[n_top]
        if not rows:
            continue
        # 平均组合/基准/超额暴露
        port_exp_avg = pd.Series(0.0, index=styles)
        bench_exp_avg = pd.Series(0.0, index=styles)
        style_contrib = pd.Series(0.0, index=styles)
        excess_rets = []
        idio_vars = []
        neutral_ret_impact = []
        for r in rows:
            port_exp_avg = port_exp_avg.add(r["port_exp"].reindex(styles).fillna(0.0), fill_value=0.0)
            bench_exp_avg = bench_exp_avg.add(r["bench_exp"].reindex(styles).fillna(0.0), fill_value=0.0)
            excess = (r["port_exp"].reindex(styles).fillna(0.0)
                      - r["bench_exp"].reindex(styles).fillna(0.0))
            # 风格贡献 = Σ_k 暴露差_k × 因子收益_k (同期)
            style_contrib = style_contrib.add(excess * r["f_vec"].reindex(styles).fillna(0.0), fill_value=0.0)
            if r["port_ret"] is not None:
                excess_rets.append(r["port_ret"] - r["bench_ret"])
            idio_vars.append(r["idio_var"])
            if r["w_n"] is not None and r["port_ret"] is not None:
                # 中性化后组合收益 = w_n · 当期未来收益 (fut_vec 与 X.index 对齐)
                port_ret_n = float(np.dot(np.asarray(r["w_n"].values, dtype=float),
                                          np.asarray(r["fut_vec"], dtype=float)))
                neutral_ret_impact.append(port_ret_n - r["port_ret"])
        port_exp_avg = port_exp_avg / len(rows)
        bench_exp_avg = bench_exp_avg / len(rows)
        style_contrib = style_contrib / len(rows)
        excess_avg = port_exp_avg - bench_exp_avg
        mean_excess_ret = float(np.mean(excess_rets)) if excess_rets else 0.0
        style_contrib_total = float(style_contrib.sum())
        alpha = mean_excess_ret - style_contrib_total
        # 风格风险 = 超额暴露' CovF 超额暴露 (年化); 特质风险 = 平均特质方差
        e_vec = excess_avg.values
        style_var = float(np.asarray([e_vec]).dot(cov).dot(np.asarray([e_vec]).T)[0, 0])
        idio_var = float(np.mean(idio_vars)) * ann_factor if idio_vars else 0.0
        total_var = style_var + idio_var
        total_vol = float(np.sqrt(max(total_var, 0.0)))
        style_pct = float(style_var / total_var) if total_var > 0 else 0.0
        idio_pct = float(idio_var / total_var) if total_var > 0 else 0.0

        neu = None
        if neutralize_port:
            before = {st: round(float(port_exp_avg.get(st, 0.0)), 4) for st in styles}
            # 中性化后实际风格暴露 (w_n·X 的平均, 贴基准但保留 ridge 微差)
            port_exp_n_avg = pd.Series(0.0, index=styles)
            for r in rows:
                if r["port_exp_n"] is not None:
                    port_exp_n_avg = port_exp_n_avg.add(
                        r["port_exp_n"].reindex(styles).fillna(0.0), fill_value=0.0)
            port_exp_n_avg = port_exp_n_avg / len(rows)
            after = {st: round(float(port_exp_n_avg.get(st, 0.0)), 4) for st in styles}
            neu = {
                "enabled": True,
                "before_style_exposure": before,
                "after_style_exposure": after,
                "return_impact": round(float(np.mean(neutral_ret_impact)), 6) if neutral_ret_impact else 0.0,
                "note": "中性化后组合风格暴露贴近基准(全体等权), 风格赌注被压平",
            }

        out_top[n_top] = {
            "avg_style_exposure": {st: round(float(port_exp_avg.get(st, 0.0)), 4) for st in styles},
            "bench_style_exposure": {st: round(float(bench_exp_avg.get(st, 0.0)), 4) for st in styles},
            "excess_style_exposure": {st: round(float(excess_avg.get(st, 0.0)), 4) for st in styles},
            "risk_decomposition": {
                "total_var_annual": round(total_var, 6),
                "style_risk_annual": round(style_var, 6),
                "idio_risk_annual": round(idio_var, 6),
                "style_pct": round(style_pct, 4),
                "idio_pct": round(idio_pct, 4),
                "total_vol_annual": round(total_vol, 4),
            },
            "attribution": {
                "mean_excess_return": round(mean_excess_ret, 6),
                "style_contribution": round(style_contrib_total, 6),
                "alpha": round(alpha, 6),
                "style_detail": {st: round(float(style_contrib.get(st, 0.0)), 6) for st in styles},
            },
            "neutralization": neu,
        }

    return {
        "styles": styles,
        "style_labels": {st: BARRA_STYLE_LABELS.get(st, st) for st in styles},
        "per_top_n": out_top,
        "factor_cov": {st: {st2: round(float(cov_f.loc[st, st2]), 6) for st2 in styles} for st in styles},
        "factor_returns_series": {
            st: [round(float(v), 6) for v in factor_ret_ts[st]] for st in styles
        },
        "n_rebalances": len(period_rows) // max(len(top_n_list), 1),
        "neutralize_port": bool(neutralize_port),
        "note": ("Barra 风格暴露为价量可计算子集(规模/Beta/动量/残差波动/非线性市值/流动性), "
                 "作为通用风险标尺, 不依赖用户是否选中 Barra 因子; 组合中性化为可选开关。"),
    }


def direction_to_int(direction) -> int:
    """统一因子方向语义: 数据库存字符串, 合成需要整数。

    约定: direction 表示"公式输出值"的期望方向 ——
      1  = 正向(公式输出越大越好)
      -1 = 负向(公式输出越小越好)
      0  = 未指定/中性(交由自动方向按历史IC符号判断)

    兼容: 整数(1/-1/0)原样返回; None/空串/未知值返回 0。
    """
    if isinstance(direction, bool):
        return 0
    if isinstance(direction, (int, float, np.integer, np.floating)):
        v = int(direction)
        return v if v in (1, -1) else 0
    s = str(direction or "").strip().lower()
    return {"positive": 1, "negative": -1}.get(s, 0)


def _auto_direction(factor_ids: List[str], hist_ic: Dict[str, List[float]],
                    direction_map: Optional[dict], auto: bool = True,
                    override_manual: bool = False) -> Dict[str, int]:
    """因子方向: 手工 direction_map 优先, 否则按给定历史IC符号自动判断

    hist_ic 应传入"截至当前期"的历史 IC 序列 (walk-forward), 避免未来函数。
    当历史 IC 不足时回退为默认正向(1)。

    override_manual=True 时(且 auto=True): 手工配置的方向也被自动判断覆盖,
    用于手工方向不确定的场景; 默认 False 保持"手工优先, 自动补缺"。
    """
    out = {}
    for fid in factor_ids:
        manual = direction_map.get(fid, 0) if direction_map else 0
        use_auto = bool(auto) and (override_manual or manual == 0)
        if use_auto:
            hist = [v for v in hist_ic.get(fid, []) if pd.notna(v)]
            mean_ic = float(np.mean(hist)) if hist else 0.0
            out[fid] = 1 if mean_ic >= 0 else -1
        else:
            out[fid] = 1 if manual >= 0 else -1
    return out


def _screen_factors(all_ids: List[str], factor_full_ic: Dict[str, List[float]],
                    factor_non_null: Dict[str, List[int]], cfg: Dict[str, Any]):
    """因子筛选: 基于 IC阈值 + 非空率 + 调仓覆盖率 淘汰无效因子"""
    sc = cfg["screening"]
    if not sc.get("enable", True):
        return list(all_ids), {"enabled": False, "selected": list(all_ids), "dropped": []}
    ic_thresh = sc.get("ic_thresh", 0.02)
    min_non_null = sc.get("min_non_null", 0.5)
    min_coverage = sc.get("min_rebal_coverage", 0.5)
    n_rebal = max((len(v) for v in factor_full_ic.values()), default=1)
    selected, dropped = [], []
    for fid in all_ids:
        hist = [v for v in factor_full_ic.get(fid, []) if pd.notna(v)]
        if not hist:
            dropped.append({"factor_id": fid, "reason": "无有效IC样本"})
            continue
        mean_abs_ic = float(np.mean([abs(v) for v in hist]))
        nn = factor_non_null.get(fid, [])
        non_null_rate = float(np.mean([1 if c > 0 else 0 for c in nn])) if nn else 0.0
        coverage = len(hist) / max(n_rebal, 1)
        if mean_abs_ic < ic_thresh:
            dropped.append({"factor_id": fid, "reason": f"|IC|={mean_abs_ic:.4f}<{ic_thresh}",
                            "abs_ic": round(mean_abs_ic, 4)})
        elif non_null_rate < min_non_null:
            dropped.append({"factor_id": fid, "reason": f"非空率={non_null_rate:.2f}<{min_non_null}"})
        elif coverage < min_coverage:
            dropped.append({"factor_id": fid, "reason": f"覆盖率={coverage:.2f}<{min_coverage}"})
        else:
            selected.append(fid)
    return selected, {"enabled": True, "ic_thresh": ic_thresh, "selected": selected, "dropped": dropped}


def _multi_period_correlation(preprocessed_crosses: Dict[int, pd.DataFrame],
                              factor_ids: List[str]):
    """跨期平均相关性: 对每个调仓截面算两两Spearman相关, 再跨期取平均 (清华 CorrValue)"""
    if len(factor_ids) < 2:
        return {"corr_matrix": {}, "pairs": []}, {"corr_matrix": {}, "pairs": [], "n_cross_sections": 0}
    acc = {f1: {f2: [] for f2 in factor_ids} for f1 in factor_ids}
    n_sec = 0
    for t in sorted(preprocessed_crosses):
        pre = preprocessed_crosses[t]
        cols = [f for f in factor_ids if f in pre.columns]
        if len(cols) < 2:
            continue
        corr = pre[cols].corr(method="spearman")
        for i, f1 in enumerate(cols):
            for f2 in cols[i + 1:]:
                v = corr.loc[f1, f2]
                if pd.notna(v):
                    acc[f1][f2].append(float(v))
                    acc[f2][f1].append(float(v))
        n_sec += 1
    corr_dict = {}
    pairs = []
    for f1 in factor_ids:
        corr_dict[f1] = {}
        for f2 in factor_ids:
            vals = acc[f1][f2]
            corr_dict[f1][f2] = round(float(np.mean(vals)), 4) if vals else None
        for f2 in factor_ids:
            if f1 >= f2:
                continue
            v = corr_dict[f1][f2]
            if v is not None:
                pairs.append({"f1": f1, "f2": f2, "corr": v})
    pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
    report = {"corr_matrix": corr_dict, "pairs": pairs, "n_cross_sections": n_sec}
    return report, report


def _redundancy_remove(selected: List[str], corr_data: dict,
                       factor_full_ic: Dict[str, List[float]], cfg: Dict[str, Any]):
    """相关性去冗余: 对|corr|>阈值的冗余组, 保留|IC|更高的因子"""
    rd = cfg["redundancy"]
    corr_thresh = rd.get("corr_thresh", 0.8)
    if not rd.get("enable", True):
        return list(selected), {"enabled": False, "selected": list(selected), "removed": []}
    if len(selected) < 2:
        return list(selected), {"enabled": True, "selected": list(selected), "removed": []}

    def _abs_ic(fid):
        hist = [v for v in factor_full_ic.get(fid, []) if pd.notna(v)]
        return float(np.mean([abs(v) for v in hist])) if hist else 0.0

    corr_matrix = corr_data.get("corr_matrix", {})
    order = sorted(selected, key=_abs_ic, reverse=True)
    final, dropped = [], set()
    removed = []
    for fid in order:
        if fid in dropped:
            continue
        final.append(fid)
        for other in selected:
            if other == fid or other in dropped:
                continue
            c = corr_matrix.get(fid, {}).get(other)
            if c is not None and abs(c) > corr_thresh:
                dropped.add(other)
                removed.append({"factor_id": other, "corr_with": fid, "corr": c,
                                "abs_ic": round(_abs_ic(other), 4)})
    return final, {"enabled": True, "corr_thresh": corr_thresh, "selected": final, "removed": removed}


def _apply_direction(pre: pd.DataFrame, factor_ids: List[str], direction: dict) -> pd.DataFrame:
    """按因子方向翻转因子列 (负方向因子取负), 用于等权等线性合成"""
    out = pre.copy()
    for fid in factor_ids:
        if fid in out.columns and direction.get(fid, 1) < 0:
            out[fid] = -out[fid]
    return out


def _factor_period_returns(preprocessed_crosses: Dict[int, pd.DataFrame],
                           future_returns: Dict[int, pd.Series],
                           factor_ids: List[str], q: int = 5) -> pd.DataFrame:
    """计算每因子的跨期收益序列 (每调仓日按分位做多空收益), 供权重优化使用"""
    rets = {fid: [] for fid in factor_ids}
    for t in sorted(preprocessed_crosses):
        pre = preprocessed_crosses[t]
        fut = future_returns[t]
        for fid in factor_ids:
            if fid not in pre.columns:
                rets[fid].append(np.nan)
                continue
            df = pd.DataFrame({"f": pre[fid], "r": fut}).dropna()
            if len(df) < max(20, q * 4):
                rets[fid].append(np.nan)
                continue
            layer = pd.qcut(df["f"], q, labels=False, duplicates="drop")
            if layer.nunique() < 2:
                rets[fid].append(np.nan)
                continue
            rets[fid].append(float(df.loc[layer == layer.max(), "r"].mean()
                                    - df.loc[layer == layer.min(), "r"].mean()))
    return pd.DataFrame(rets)


def markowitz_weight_synthesis(preprocessed_crosses: Dict[int, pd.DataFrame],
                               future_returns: Dict[int, pd.Series],
                               factor_ids: List[str]):
    """Markowitz 最大夏普权重 (对因子跨期收益序列做均值-方差优化, 清华 Markowitz_opt)"""
    rets = _factor_period_returns(preprocessed_crosses, future_returns, factor_ids)
    r = rets.dropna(axis=0, how="any")
    if len(r) < 5 or len(r.columns) < 2:
        return None
    mu = r.mean()
    cov = r.cov()
    try:
        import scipy.optimize as sco
    except ImportError:
        return None

    def _neg_sharpe(w):
        p = float(np.dot(mu, w))
        var = float(np.dot(w.T, np.dot(cov, w)))
        if var <= 0:
            return 1e9
        return -p / np.sqrt(var)

    n = len(mu)
    w0 = np.ones(n) / n
    bnds = tuple((0, 1) for _ in range(n))
    cons = ({"type": "eq", "fun": lambda w: np.sum(w) - 1},)
    res = sco.minimize(_neg_sharpe, w0, method="SLSQP", bounds=bnds, constraints=cons)
    if not res.success:
        return None
    w = res.x
    if np.sum(w) <= 0:
        return None
    return pd.Series(w / np.sum(w), index=mu.index)


def optuna_weight_synthesis(preprocessed_crosses: Dict[int, pd.DataFrame],
                            future_returns: Dict[int, pd.Series],
                            factor_ids: List[str], n_trials: int = 15):
    """Optuna 贝叶斯搜索因子权重 (最大化样本内组合IC, 清华 objective/study)

    传入的 preprocessed_crosses/future_returns 应为"截至当期之前"的历史数据 (walk-forward),
    本函数仅在这些历史数据内优化权重, 不引入未来函数。
    """
    try:
        import optuna
    except ImportError:
        return None
    ts = sorted(preprocessed_crosses.keys())
    if len(ts) < 6:
        return None

    def _combo_ic(w):
        ics = []
        for t in ts:
            pre = preprocessed_crosses[t]
            fut = future_returns[t]
            cols = [f for f in factor_ids if f in pre.columns]
            if len(cols) < 2:
                continue
            wv = pd.Series({f: w[i] for i, f in enumerate(factor_ids)}, dtype=float)
            score = (pre[cols] * wv.reindex(cols).fillna(0)).sum(axis=1)
            df = pd.DataFrame({"s": score, "r": fut}).dropna()
            if len(df) < 20:
                continue
            ics.append(df["s"].corr(df["r"], method="spearman"))
        return float(np.nanmean(ics)) if ics else 0.0

    def _objective(trial):
        ws = [trial.suggest_float(f"w{i}", 0, 1) for i in range(len(factor_ids))]
        s = sum(ws) or 1.0
        return _combo_ic([w / s for w in ws])

    study = optuna.create_study(direction="maximize")
    study.optimize(_objective, n_trials=n_trials)
    w = np.array([study.best_params[f"w{i}"] for i in range(len(factor_ids))], dtype=float)
    if np.sum(w) <= 0:
        return None
    return pd.Series(w / np.sum(w), index=factor_ids)


def sharpe_weight_synthesis(factor_hist_ic: Dict[str, List[float]],
                            factor_ids: List[str]):
    """夏普加权: 权重 = IR(IC均值/IC标准差), 归一化 (清华 夏普加权思路)

    factor_hist_ic 应为"截至当期之前"的历史 IC 序列 (walk-forward), 避免未来函数。
    """
    w = {}
    for fid in factor_ids:
        hist = [v for v in factor_hist_ic.get(fid, []) if pd.notna(v)]
        if len(hist) < 2:
            w[fid] = 0.0
        else:
            std = float(np.std(hist, ddof=1))
            w[fid] = float(np.mean(hist)) / std if std > 0 else 0.0
    s = pd.Series(w)
    if s.abs().sum() <= 0:
        return None
    return s / s.abs().sum()


def pca_synthesis(pre: pd.DataFrame, factor_ids: List[str],
                  direction: dict, cfg: Dict[str, Any]) -> pd.Series:
    """PCA 主成分合成: 取前k个主成分按解释方差加权, 用因子方向修正符号"""
    from sklearn.decomposition import PCA
    X = pre.dropna(how="any")
    if len(X) < 5:
        return pd.Series(dtype=float)
    pca_cfg = cfg["pca"]
    n_comp = pca_cfg.get("n_components")
    expl = pca_cfg.get("explained_var", 0.9)
    pca = PCA()
    pca.fit(X)
    cum = np.cumsum(pca.explained_variance_ratio_)
    k = n_comp if n_comp else int(np.searchsorted(cum, expl) + 1)
    k = max(1, min(int(k), X.shape[1]))
    comps = pca.components_[:k].copy()
    signs = np.array([direction.get(f, 1) for f in X.columns])
    for i in range(k):
        if np.dot(comps[i], signs) < 0:
            comps[i] = -comps[i]
    loadings = pca.explained_variance_ratio_[:k]
    loadings = loadings / loadings.sum()
    T = pca.transform(X)[:, :k]
    score = np.zeros(len(X))
    for i in range(k):
        score += loadings[i] * T[:, i]
    return pd.Series(score, index=X.index)


def _ml_cls_fit_model(X_train: pd.DataFrame, y_train: pd.Series,
                      ml_params: Optional[dict] = None):
    """训练 ML 分类模型 (预测涨跌概率, 来源: 机器学习case), 输出 predict_proba[:,1]"""
    params = ml_params or {}
    model_type = str(params.get("model_type", "xgboost")).lower()
    n_estimators = int(params.get("n_estimators", 100))
    max_depth = int(params.get("max_depth", 3))
    learning_rate = float(params.get("learning_rate", 0.05))
    subsample = float(params.get("subsample", 0.8))
    colsample = float(params.get("colsample_bytree", 0.8))
    if model_type == "lightgbm":
        try:
            from lightgbm import LGBMClassifier
            return LGBMClassifier(
                n_estimators=n_estimators, max_depth=max_depth, learning_rate=learning_rate,
                num_leaves=max(2, min(2 ** max_depth, 31)), subsample=subsample,
                colsample_bytree=colsample, random_state=42, verbose=-1,
            ).fit(X_train, y_train)
        except ImportError:
            pass
    if model_type == "rf":
        try:
            from sklearn.ensemble import RandomForestClassifier
            return RandomForestClassifier(
                n_estimators=n_estimators, max_depth=max(2, max_depth),
                min_samples_leaf=20, random_state=42,
            ).fit(X_train, y_train)
        except ImportError:
            pass
    try:
        from xgboost import XGBClassifier
        return XGBClassifier(
            n_estimators=n_estimators, max_depth=max_depth, learning_rate=learning_rate,
            subsample=subsample, colsample_bytree=colsample, random_state=42,
        ).fit(X_train, y_train)
    except ImportError:
        from lightgbm import LGBMClassifier
        return LGBMClassifier(
            n_estimators=n_estimators, max_depth=max_depth, learning_rate=learning_rate,
            num_leaves=max(2, min(2 ** max_depth, 31)), subsample=subsample,
            colsample_bytree=colsample, random_state=42, verbose=-1,
        ).fit(X_train, y_train)


def _purged_kfold_cv(X: pd.DataFrame, y: pd.Series, model_type: str = "xgboost",
                     n_splits: int = 5, gap: int = 5, params: Optional[dict] = None):
    """Purged时序K折交叉验证 (训练/验证间留gap防泄漏), 返回平均AUC (机器学习case)"""
    from sklearn.metrics import roc_auc_score
    idx = np.arange(len(X))
    fold_size = int(len(idx) / n_splits)
    if fold_size < 1:
        return None
    aucs = []
    for i in range(n_splits):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < n_splits - 1 else len(idx)
        test_idx = idx[test_start:test_end]
        train_idx = idx[: max(0, test_start - gap)]
        if len(train_idx) < 30:
            continue
        X_tr = X.iloc[train_idx]
        X_te = X.iloc[test_idx]
        y_tr = y.iloc[train_idx]
        y_te = y.iloc[test_idx]
        if y_tr.nunique() < 2:
            continue
        m = _ml_cls_fit_model(X_tr, y_tr, {**(params or {}), "model_type": model_type})
        p = m.predict_proba(X_te)[:, 1]
        if y_te.nunique() > 1:
            aucs.append(roc_auc_score(y_te, p))
    return float(np.mean(aucs)) if aucs else None


def _dump_ml_model(model, feature_cols: List[str], method: str) -> str:
    """把训练好的 ML 模型 + 特征列顺序落盘为 joblib, 返回文件路径 (供因子包复用)

    保存时同时记录特征列顺序, 其他页面加载后按此列序取因子即可直接 predict, 无需重训。
    """
    import joblib
    ML_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    import uuid
    fname = f"ml_{method}_{uuid.uuid4().hex[:8]}.joblib"
    path = ML_MODEL_DIR / fname
    joblib.dump({"model": model, "feature_cols": feature_cols, "method": method}, path)
    return str(path)


def _load_ml_model(path: str):
    """加载落盘的 ML 模型, 返回 (model, feature_cols, method)"""
    import joblib
    data = joblib.load(path)
    return data["model"], data["feature_cols"], data["method"]


def _dump_pca_model(pca, loadings: np.ndarray, k: int, feature_cols: List[str]) -> str:
    """落盘 PCA 对象 + 主成分数 + 主成分权重 + 特征列顺序, 返回路径 (供因子包复用)

    保存 PCA 拟合结果, 其他页面加载后对新截面做 transform 投影即可, 无需重新 fit。
    """
    import joblib
    ML_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    import uuid
    fname = f"pca_{uuid.uuid4().hex[:8]}.joblib"
    path = ML_MODEL_DIR / fname
    joblib.dump({"pca": pca, "loadings": loadings, "k": k, "feature_cols": feature_cols}, path)
    return str(path)


def _load_pca_model(path: str):
    """加载落盘的 PCA 对象, 返回 (pca, loadings, k, feature_cols)"""
    import joblib
    data = joblib.load(path)
    return data["pca"], data["loadings"], data["k"], data["feature_cols"]


def _stack_history(preprocessed_crosses: Dict[int, pd.DataFrame],
                   future_returns: Dict[int, pd.Series],
                   factor_ids: List[str]):
    """把全历史截面 + 未来收益堆叠成 (X_all, y_all), 供全历史拟合使用"""
    xs, ys = [], []
    for t in sorted(preprocessed_crosses):
        pre = preprocessed_crosses[t]
        fut = future_returns[t]
        cols = [f for f in factor_ids if f in pre.columns]
        if len(cols) < 2:
            continue
        xs.append(pre[cols])
        ys.append(fut.reindex(pre.index))
    if not xs:
        return None, None
    return pd.concat(xs, axis=0), pd.concat(ys, axis=0)


def _build_final_use_params(method: str, factor_ids: List[str],
                            factor_full_ic: Dict[str, List[float]],
                            preprocessed_crosses: Dict[int, pd.DataFrame],
                            future_returns: Dict[int, pd.Series],
                            direction_map: Optional[dict], auto_dir: bool,
                            cfg: Dict[str, Any], ml_params: Optional[dict]) -> Dict[str, Any]:
    """构建因子包的"最终使用参数" (全历史确定一次, 非 walk-forward)

    与 walk-forward 评价分离: 评价用滚动判断稳定性, 使用则用全部历史数据确定一次
    最终方向/权重/模型, 供其他页面直接选股复用, 不再滚动。

    返回: {
        final_factor_ids: 筛选/去冗余后的最终因子清单,
        final_direction:  全历史 IC 符号确定的方向,
        final_weights:    全历史确定的权重 (线性方法), 或 None,
        ml_model_path:    全历史重训的 ML 模型路径, 或 None,
        pca_model_path:   全历史拟合的 PCA 对象路径, 或 None,
    }
    """
    from sklearn.decomposition import PCA

    final_direction = _auto_direction(
        factor_ids, factor_full_ic, direction_map, auto_dir,
        override_manual=bool(cfg["direction"].get("override_manual", False)))
    final_weights = None
    ml_model_path = None
    pca_model_path = None

    if method in ("markowitz", "optuna", "sharpe"):
        if method == "sharpe":
            w = sharpe_weight_synthesis(factor_full_ic, factor_ids)
        elif method == "markowitz":
            w = markowitz_weight_synthesis(preprocessed_crosses, future_returns, factor_ids)
        else:
            w = optuna_weight_synthesis(preprocessed_crosses, future_returns, factor_ids,
                                        n_trials=cfg["optuna"].get("n_trials", 15))
        if w is not None:
            final_weights = {k: round(float(v), 6) for k, v in w.items()}

    elif method == "ic_weighted":
        w = {}
        for fid in factor_ids:
            hist = [v for v in factor_full_ic.get(fid, []) if pd.notna(v)]
            w[fid] = float(np.mean(hist)) if hist else 0.0
        s = pd.Series(w)
        if s.abs().sum() > 0:
            final_weights = {k: round(float(v), 6) for k, v in (s / s.abs().sum()).items()}

    elif method == "lasso":
        X_all, y_all = _stack_history(preprocessed_crosses, future_returns, factor_ids)
        if X_all is not None and len(X_all) >= 60:
            try:
                from sklearn.linear_model import Lasso
                mask = ~(X_all.isna().any(axis=1) | y_all.isna())
                if mask.sum() >= 60:
                    model = Lasso(alpha=0.01, max_iter=5000)
                    model.fit(X_all[mask], y_all[mask])
                    final_weights = {fid: round(float(c), 6) for fid, c in zip(factor_ids, model.coef_)}
            except Exception:
                final_weights = None

    elif method in ("ml_reg", "ml_cls"):
        X_all, y_all = _stack_history(preprocessed_crosses, future_returns, factor_ids)
        if X_all is not None and len(X_all) >= 100:
            mask = ~(X_all.isna().any(axis=1) | y_all.isna())
            if mask.sum() >= 100:
                try:
                    if method == "ml_cls":
                        model = _ml_cls_fit_model(X_all[mask], (y_all[mask] > 0).astype(int), ml_params)
                    else:
                        model = _ml_fit_model(X_all[mask], y_all[mask], ml_params)
                    ml_model_path = _dump_ml_model(model, factor_ids, method)
                except Exception:
                    ml_model_path = None

    elif method == "pca":
        X_all, _ = _stack_history(preprocessed_crosses, future_returns, factor_ids)
        if X_all is not None:
            X = X_all.dropna(how="any")
            if len(X) >= 5:
                pca_cfg = cfg["pca"]
                n_comp = pca_cfg.get("n_components")
                expl = pca_cfg.get("explained_var", 0.9)
                pca = PCA()
                pca.fit(X)
                cum = np.cumsum(pca.explained_variance_ratio_)
                k = n_comp if n_comp else int(np.searchsorted(cum, expl) + 1)
                k = max(1, min(int(k), X.shape[1]))
                # 用最终方向修正主成分符号
                comps = pca.components_[:k].copy()
                signs = np.array([final_direction.get(f, 1) for f in X.columns])
                for i in range(k):
                    if np.dot(comps[i], signs) < 0:
                        comps[i] = -comps[i]
                pca.components_[:k] = comps
                loadings = pca.explained_variance_ratio_[:k]
                loadings = loadings / loadings.sum()
                try:
                    pca_model_path = _dump_pca_model(pca, loadings, k, list(X.columns))
                except Exception:
                    pca_model_path = None

    return {
        "final_factor_ids": list(factor_ids),
        "final_direction": {k: int(v) for k, v in final_direction.items()},
        "final_weights": final_weights,
        "ml_model_path": ml_model_path,
        "pca_model_path": pca_model_path,
    }


def build_final_use_from_prep(prep: Dict[str, Any], method: str, factor_ids: List[str],
                              direction_map: Optional[dict], auto_dir: bool,
                              cfg: Dict[str, Any], ml_params: Optional[dict]) -> Dict[str, Any]:
    """根据阶段B1预处理缓存, 用全历史数据确定因子包最终使用参数

    仅在用户点击"保存因子包"时调用, 与 synth_multi_factor_eval 内的 walk-forward 评价
    分离: 评价用滚动判断稳定性, 保存因子包则用全部历史截面一次性确定方向/权重/模型。
    factor_ids 为筛选/去冗余后的最终因子清单。
    """
    preprocessed_crosses = prep.get("preprocessed_crosses", {})
    future_returns = prep.get("future_returns", {})
    # 全历史每因子IC (与 synth_multi_factor_eval 阶段A 的 factor_full_ic 一致)
    factor_full_ic = {fid: [] for fid in factor_ids}
    for t in sorted(preprocessed_crosses):
        pre = preprocessed_crosses[t]
        fut = future_returns[t]
        for fid in factor_ids:
            if fid in pre.columns:
                f_ic = calc_ic(pre[fid], fut)
                factor_full_ic[fid].append(f_ic if pd.notna(f_ic) else np.nan)
            else:
                factor_full_ic[fid].append(np.nan)
    return _build_final_use_params(method, factor_ids, factor_full_ic,
                                   preprocessed_crosses, future_returns,
                                   direction_map, auto_dir, cfg, ml_params)


def synth_multi_factor_eval(prep: Dict[str, Any],
                            method: str = "equal",
                            ic_lookback: int = 5,
                            n_layers: int = 5,
                            top_n_list: Optional[List[int]] = None,
                            direction_map: Optional[dict] = None,
                            ml_params: Optional[dict] = None,
                            cost: float = 0.002,
                            synth_cfg: Optional[dict] = None,
                            barra_style_panels: Optional[Dict[str, pd.DataFrame]] = None,
                            neutralize_port: bool = False,
                            signal_score_panel: Optional[pd.DataFrame] = None,
                            signal_meta: Optional[dict] = None) -> Dict[str, Any]:
    """阶段B2: 基于已准备(prep)数据做指定合成方式的合成 + 组合评价

    复用 prep_multi_factor 产出的已清洗截面与未来收益, 因此切换合成方式/调ML参数
    时无需重跑阶段B1。walk-forward IC 权重、ML 滚动训练均在此阶段内完成。

    参数:
        prep:      prep_multi_factor 的返回值
        method:    equal / ic_weighted / rank_score / lasso / ml_reg / ml_cls
                   / markowitz / optuna / sharpe / pca
        synth_cfg: 可配置参数(dict), 含 screening/redundancy/direction/pca/optuna/ml
        barra_style_panels: F1 组合风险分析用的 Barra 风格暴露面板 (build_barra_style_panels
                            产出), 传入时自动在结果中附加 portfolio_risk 风险分析;
                            不传则跳过(仅做合成评价, 不附加风险阶段)。
        neutralize_port: 是否执行组合中性化(可选开关, 默认关)
        signal_score_panel: F2 信号方向得分独立轨综合面板 (build_signal_direction_score_panel
                            产出), 传入时在每期连续合成综合因子上叠加信号方向得分(次级倾斜);
                            仅信号因子(signal_only)时综合因子即信号得分, 无需再叠加。
        signal_meta:      信号因子元信息 {fid: {direction, bipolar}}, 供结果展示。
    """
    cfg = _normalize_synth_cfg(synth_cfg)
    # F2: 仅信号因子(signal_only)时综合因子即信号方向得分, 单一因子无需筛选/去冗余
    signal_only = bool(prep.get("signal_only"))
    if signal_only:
        cfg["screening"]["enable"] = False
        cfg["redundancy"]["enable"] = False
    dates_idx = prep["dates_idx"]
    preprocessed_crosses = prep["preprocessed_crosses"]
    future_returns = prep["future_returns"]
    if top_n_list is None:
        top_n_list = [10]

    all_factor_ids = list(preprocessed_crosses[next(iter(preprocessed_crosses))].columns)

    # ===== 阶段A: 每因子全历史IC序列 (用于筛选/方向/去冗余/夏普加权) =====
    factor_full_ic = {fid: [] for fid in all_factor_ids}
    factor_non_null = {fid: [] for fid in all_factor_ids}
    for t in sorted(preprocessed_crosses):
        pre = preprocessed_crosses[t]
        fut = future_returns[t]
        for fid in all_factor_ids:
            if fid not in pre.columns:
                factor_full_ic[fid].append(np.nan)
                factor_non_null[fid].append(0)
                continue
            f_ic = calc_ic(pre[fid], fut)
            factor_full_ic[fid].append(f_ic if pd.notna(f_ic) else np.nan)
            factor_non_null[fid].append(int(pre[fid].notna().sum()))

    # 因子筛选 (IC阈值 + 非空率 + 覆盖率)
    screened, screening_report = _screen_factors(all_factor_ids, factor_full_ic, factor_non_null, cfg)

    # 跨期平均相关性矩阵 (多截面相关取平均)
    corr_avg, corr_report = _multi_period_correlation(preprocessed_crosses, all_factor_ids)

    # 相关性去冗余 (保留|IC|更高的因子)
    factor_ids, redundancy_report = _redundancy_remove(screened, corr_avg, factor_full_ic, cfg)

    # 方向初始值: 仅手工 direction_map 生效; 自动方向改为循环内 walk-forward 逐期判断 (避免未来函数)
    auto_dir = cfg["direction"].get("auto", True)
    override_manual = bool(cfg["direction"].get("override_manual", False))
    direction = _auto_direction(factor_ids, {}, direction_map, auto_dir,
                                override_manual=override_manual)

    if not factor_ids:
        return {"error": "因子筛选后无有效因子可合成",
                "screening": screening_report, "redundancy": redundancy_report}

    # ===== 阶段B: 合成主循环 (walk-forward) =====
    ic_series = []          # [(date, ic)]
    factor_hist_ic = {fid: [] for fid in factor_ids}
    composite_cross = {}    # t -> 综合因子 Series
    futs = {}               # t -> 未来收益 Series

    # ML 状态 (阶段内累积, walk-forward)
    ml_history_x = []
    ml_history_y = []
    ml_model = None
    ml_last_train_t = None   # 最近一次训练的调仓期索引 (周期性重训用)
    ml_feature_cols = list(factor_ids)
    ml_feature_importance = None
    ml_purged_auc = None
    ml_importance_feedback_report = None

    # F2 信号方向得分独立轨: 汇总用 (非 signal_only 且存在信号综合面板时记录每期信号得分)
    signal_track = {} if (signal_score_panel is not None and not signal_only) else None

    # 权重优化方法改为 walk-forward: 每期用"截至当期之前"的历史数据求权重 (避免未来函数)
    last_weights = None   # 记录最后一期权重, 供返回展示
    for t in sorted(preprocessed_crosses.keys()):
        date = dates_idx[t]
        pre = preprocessed_crosses[t]
        fut = future_returns[t]

        # walk-forward 方向判断 (用截至当期之前的历史IC, 避免未来函数)
        if auto_dir:
            direction = _auto_direction(factor_ids, factor_hist_ic, direction_map, auto_dir,
                                        override_manual=override_manual)

        # walk-forward IC 权重 (用历史 ic_lookback 期)
        ic_weights = None
        if method == "ic_weighted":
            ic_weights = {}
            for fid in factor_ids:
                hist = [v for v in factor_hist_ic[fid][-ic_lookback:] if pd.notna(v)]
                ic_weights[fid] = float(np.mean(hist)) if hist else 0.0
            if not any(abs(v) > 0 for v in ic_weights.values()):
                ic_weights = None

        # walk-forward 权重优化 (markowitz/optuna/sharpe): 只用截至当期之前的历史数据
        wf_weights = None
        if method in ("markowitz", "optuna", "sharpe"):
            if method == "sharpe":
                wf_weights = sharpe_weight_synthesis(factor_hist_ic, factor_ids)
            else:
                hist_ts = [tt for tt in sorted(preprocessed_crosses.keys()) if tt < t]
                if len(hist_ts) >= 5:
                    hist_crosses = {tt: preprocessed_crosses[tt] for tt in hist_ts}
                    hist_futs = {tt: future_returns[tt] for tt in hist_ts}
                    if method == "markowitz":
                        wf_weights = markowitz_weight_synthesis(hist_crosses, hist_futs, factor_ids)
                    else:  # optuna
                        wf_weights = optuna_weight_synthesis(hist_crosses, hist_futs, factor_ids,
                                                             n_trials=cfg["optuna"].get("n_trials", 15))
            if wf_weights is not None:
                last_weights = wf_weights

        valid_cols = ml_feature_cols if method in ("ml_reg", "ml_cls") else factor_ids
        # C4 修复: ML/Lasso 需要完整特征输入, 保持"全部非空"子集;
        #          线性/排名合成放宽为"允许部分缺失"(只要不全空), 缺失因子按不贡献处理。
        if method in ("ml_reg", "ml_cls", "lasso"):
            valid = pre[valid_cols].dropna(how="any")
        else:
            valid = pre[valid_cols].dropna(how="all")
        if len(valid) < 5:
            for fid in factor_ids:
                factor_hist_ic[fid].append(np.nan)
            continue

        # ===== 合成 =====
        if method in ("ml_reg", "ml_cls"):
            X_hist = pd.concat(ml_history_x, axis=0) if ml_history_x else None
            y_hist = pd.concat(ml_history_y, axis=0) if ml_history_y else None
            if X_hist is not None:
                # 统一列顺序为 ml_feature_cols, 保证训练与预测列序一致 (避免 XGBoost feature_names mismatch)
                X_hist = X_hist.reindex(columns=ml_feature_cols)
            if X_hist is not None and len(X_hist) >= 100:
                mask = ~(X_hist.isna().any(axis=1) | y_hist.isna())
                # 周期性重训: 首次训练后每 retrain_every 期用累积历史重训 (walk-forward,
                # 训练数据仍严格只含"截至当期之前"的样本), 避免模型对后期市场状态陈旧。
                retrain_every = max(int(cfg["ml"].get("retrain_every", 4)), 1)
                need_train = (ml_model is None) or (
                    ml_last_train_t is not None and (t - ml_last_train_t) >= retrain_every)
                if mask.sum() >= 100 and need_train:
                    if method == "ml_cls":
                        y_bin = (y_hist[mask] > 0).astype(int)
                        ml_model = _ml_cls_fit_model(X_hist[mask], y_bin, ml_params=ml_params)
                        if cfg["ml"].get("purged_cv", True) and len(y_bin) >= 100:
                            # C3 修复: 配置 gap 单位是"行", 但历史按调仓期堆叠, 一期截面有几十行;
                            #   gap 至少取"平均每期截面行数", 否则训练标签窗口(21日收益)与
                            #   测试特征窗口重叠, AUC 偏乐观 (原 gap=5 是日频场景的参数)。
                            _gap = int(cfg["ml"].get("gap", 5))
                            if ml_history_x:
                                avg_rows = max(len(X_hist) // max(len(ml_history_x), 1), 1)
                                _gap = max(_gap, int(avg_rows))
                            ml_purged_auc = _purged_kfold_cv(
                                X_hist[mask], y_bin,
                                model_type=str((ml_params or {}).get("model_type", "xgboost")).lower(),
                                n_splits=cfg["ml"].get("n_splits", 5),
                                gap=_gap, params=ml_params)
                        comp = pd.Series(ml_model.predict_proba(valid[ml_feature_cols])[:, 1],
                                         index=valid.index)
                    else:
                        ml_model = _ml_fit_model(X_hist[mask], y_hist[mask], ml_params=ml_params)
                        comp = pd.Series(ml_model.predict(valid[ml_feature_cols]), index=valid.index)
                    ml_last_train_t = t
                    # 特征重要性 + 反馈筛选 (训练完成后剔除低重要度因子并重训一次)
                    ml_feature_importance = _extract_feature_importance(ml_model, ml_feature_cols)
                    if cfg["ml"].get("importance_feedback", True) and ml_feature_importance:
                        min_imp = cfg["ml"].get("min_importance", 0.02)
                        kept = [f for f, imp in ml_feature_importance.items() if imp >= min_imp]
                        if kept and len(kept) < len(ml_feature_cols):
                            ml_importance_feedback_report = {
                                "min_importance": min_imp,
                                "kept": kept,
                                "dropped": [f for f in ml_feature_cols if f not in kept],
                            }
                            ml_feature_cols = kept
                            X_ok = X_hist[mask][kept]
                            y_ok = y_hist[mask]
                            if method == "ml_cls":
                                ml_model = _ml_cls_fit_model(X_ok, (y_ok > 0).astype(int), ml_params=ml_params)
                                comp = pd.Series(ml_model.predict_proba(valid[kept])[:, 1], index=valid.index)
                            else:
                                ml_model = _ml_fit_model(X_ok, y_ok, ml_params=ml_params)
                                comp = pd.Series(ml_model.predict(valid[kept]), index=valid.index)
                elif mask.sum() >= 100:
                    # 未到重训周期: 用已有模型预测
                    if method == "ml_cls":
                        comp = pd.Series(ml_model.predict_proba(valid[ml_feature_cols])[:, 1],
                                         index=valid.index)
                    else:
                        comp = pd.Series(ml_model.predict(valid[ml_feature_cols]), index=valid.index)
                else:
                    comp = equal_weight_synthesis(valid)
            else:
                comp = equal_weight_synthesis(valid)
        elif method == "lasso":
            X_hist = pd.concat(ml_history_x, axis=0) if ml_history_x else None
            y_hist = pd.concat(ml_history_y, axis=0) if ml_history_y else None
            if X_hist is not None and len(X_hist) >= 60:
                mask = ~(X_hist.isna().any(axis=1) | y_hist.isna())
                if mask.sum() >= 60:
                    try:
                        comp = lasso_synthesis(X_hist[mask], y_hist[mask], valid)
                    except Exception:
                        comp = equal_weight_synthesis(valid)
                else:
                    comp = equal_weight_synthesis(valid)
            else:
                comp = equal_weight_synthesis(valid)
        elif method == "equal":
            pre_dir = _apply_direction(pre[factor_ids], factor_ids, direction)
            # C4 修复: 等权合成允许部分缺失 (pandas mean 默认 skipna), 仅剔除全空行
            comp = equal_weight_synthesis(pre_dir.dropna(how="all"))
        elif method in ("markowitz", "optuna", "sharpe"):
            cols = [f for f in factor_ids if f in pre.columns]
            if wf_weights is not None and len(cols) >= 2:
                wv = wf_weights.reindex(cols).fillna(0)
                if wv.abs().sum() > 0:
                    comp = (pre[cols] * wv).sum(axis=1).reindex(valid.index).dropna()
                else:
                    comp = equal_weight_synthesis(valid)
            else:
                comp = equal_weight_synthesis(valid)
        elif method == "pca":
            comp = pca_synthesis(pre[factor_ids], factor_ids, direction, cfg)
        else:
            comp = _synthesize_preprocessed(pre[factor_ids], method, direction, ic_weights)

        if comp.empty:
            for fid in factor_ids:
                factor_hist_ic[fid].append(np.nan)
            continue

        # ===== F2 信号方向得分独立轨汇总: 在连续合成综合因子上叠加信号方向得分 (次级倾斜) =====
        # 信号得分与连续综合值都做截面标准化后按 0.5 倾斜系数叠加, 使信号因子参与选股又不主导。
        # signal_only 时综合因子即信号得分本身, 无需再叠加。
        if signal_track is not None and date in signal_score_panel.index:
            sig = signal_score_panel.loc[date].reindex(comp.index)
            sig_std = (sig - sig.mean()) / (sig.std() + 1e-9)
            comp_std = (comp - comp.mean()) / (comp.std() + 1e-9)
            comp = comp_std + 0.5 * sig_std.fillna(0.0)
            signal_track[t] = sig

        if len(fut) < 10:
            for fid in factor_ids:
                factor_hist_ic[fid].append(np.nan)
            continue

        ic = calc_ic(comp, fut)
        if pd.notna(ic):
            ic_series.append((date, ic))
        for fid in factor_ids:
            if fid in pre.columns:
                f_ic = calc_ic(pre[fid], fut)
                factor_hist_ic[fid].append(f_ic if pd.notna(f_ic) else np.nan)
            else:
                factor_hist_ic[fid].append(np.nan)

        composite_cross[t] = comp
        futs[t] = fut

        # 累积当前截面到历史训练集 (用当期未来收益作为标签, 列序与 ml_feature_cols 一致)
        if method in ("ml_reg", "ml_cls"):
            ml_history_x.append(pre[ml_feature_cols])
            ml_history_y.append(fut.reindex(pre.index))
        elif method == "lasso":
            ml_history_x.append(pre[factor_ids])
            ml_history_y.append(fut.reindex(pre.index))

    if not ic_series:
        return {"error": "多因子评价无有效IC样本",
                "screening": screening_report, "redundancy": redundancy_report}

    # ===== IC 汇总 =====
    ic_vals = [v for _, v in ic_series]
    ic_series_out = [{"date": str(d.date()), "ic": round(float(v), 4)} for d, v in ic_series]
    ic_mean = float(np.mean(ic_vals))
    ic_std = float(np.std(ic_vals, ddof=1)) if len(ic_vals) > 1 else 0.0
    ic_ir = ic_mean / ic_std if ic_std > 0 else None
    ic_win = float(np.mean([1 if v > 0 else 0 for v in ic_vals]))

    # ===== 分层回测 (多期合并) =====
    layer_rows = []
    for t, comp in composite_cross.items():
        lr = run_layered_backtest(comp, futs[t], n_layers=n_layers)
        layer_rows.append(lr)
    layer_agg = {}
    for lr in layer_rows:
        for k, v in lr.get("layer_returns", {}).items():
            layer_agg.setdefault(k, []).append(v)
    layer_returns = {int(k): round(float(np.mean(v)), 6) for k, v in layer_agg.items()}
    layered = {
        "layer_returns": layer_returns,
        "long_short": round(float(_long_short_from_layers(layer_returns)), 6) if layer_returns else None,
    }

    # ===== Top-N 组合回测 =====
    # 调仓期长从 prep 的调仓日序列推算 (相邻调仓日差的中位数), 用于绩效年化折算;
    # 推算失败时回退默认 21 交易日。
    rebal_dates_all = prep.get("rebal_dates") or []
    if len(rebal_dates_all) >= 2:
        _diffs = np.diff(np.asarray(rebal_dates_all, dtype=float))
        rebal_len = int(round(float(np.median(_diffs))))
    else:
        rebal_len = 21
    portfolio = _multifactor_topn_backtest(
        composite_cross, futs, prep or {}, dates_idx,
        sorted(preprocessed_crosses.keys()), rebal_period=max(rebal_len, 1),
        top_n_list=top_n_list, cost=cost,
    )

    # ===== F1 组合风险分析 (通用后处理, 传入 Barra 风格面板时自动附加) =====
    portfolio_risk = None
    if barra_style_panels and composite_cross:
        try:
            portfolio_risk = analyze_portfolio_risk(
                composite_cross, futs, barra_style_panels,
                dates_idx, sorted(preprocessed_crosses.keys()),
                top_n_list, neutralize_port=neutralize_port,
            )
        except Exception:
            # 风险分析失败不影响主评价结果 (容错: 仅不附加风险阶段)
            portfolio_risk = {"error": "组合风险分析计算异常, 已跳过"}

    result = {
        "method": method,
        "n_rebalances": len(ic_series),
        "eval_period": f"{dates_idx[0].date()} ~ {dates_idx[-1].date()}",
        "screening_caveat": (
            "因子筛选/去冗余基于全历史IC(选择前视: 用整段样本IC决定哪些因子进合成), "
            "属评价口径(评估这组因子的相对表现), 展示指标可能偏乐观; "
            "方向/权重/ML训练均为walk-forward(无前视)。若需严格口径, "
            "请在合成配置中关闭筛选或改用单因子评价逐一验证。"
        ),
        "coverage_note": ("模型类方法(ml_reg/ml_cls/lasso/pca)仅在全因子非空的股票子集上评估; "
                          "线性/排名合成(equal/rank_score/ic_weighted/markowitz/optuna/sharpe)允许部分缺失因子, "
                          "缺失因子按不贡献处理(rank_score 的缺失因子得0分且分母仍按全因子数, "
                          "部分缺失股票得分略偏低)。"
                          if method in ("ml_reg", "ml_cls", "lasso", "pca") else
                          "线性/排名合成允许部分缺失因子, 缺失因子按不贡献处理。"),
        "ic_series": ic_series_out,
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_ir": round(ic_ir, 4) if ic_ir is not None else None,
        "ic_win_rate": round(ic_win, 4),
        "layered": layered,
        "portfolio": portfolio,
        "correlation": corr_report,          # 跨期平均相关性
        "screening": screening_report,        # 因子筛选报告
        "redundancy": redundancy_report,      # 去冗余报告
        "direction_used": {k: direction.get(k, 1) for k in factor_ids},
        "selected_factor_ids": factor_ids,
        "weights": {k: round(float(v), 6) for k, v in last_weights.items()} if last_weights is not None else None,
        "ml_feature_importance": ml_feature_importance,
        "ml_purged_auc": round(ml_purged_auc, 4) if ml_purged_auc is not None else None,
        "ml_importance_feedback": ml_importance_feedback_report,
        "portfolio_risk": portfolio_risk,
        "neutralize_port": bool(neutralize_port),
        "signal_track": (
            {
                "signal_only": signal_only,
                "per_factor": {
                    fid: {"direction": (signal_meta or {}).get(fid, {}).get("direction", 0),
                          "bipolar": bool((signal_meta or {}).get(fid, {}).get("bipolar", False))}
                    for fid in (signal_meta or {})
                },
                "score_series": [
                    {"date": str(dates_idx[t].date()),
                     "mean_score": round(float(v.mean()), 4),
                     "signal_rate": round(float((v != 0).mean()), 4)}
                    for t, v in (signal_track or {}).items()
                ],
            }
            if (signal_track is not None or signal_only) else None
        ),
    }
    return result


def run_multi_factor_eval(factor_panels: Dict[str, pd.DataFrame],
                          prices_panel: Dict[str, pd.DataFrame],
                          rebal_period: int = 21,
                          method: str = "equal",
                          min_warmup: int = 130,
                          ic_lookback: int = 5,
                          n_layers: int = 5,
                          top_n_list: Optional[List[int]] = None,
                          sector_map: Optional[dict] = None,
                          concept_map: Optional[dict] = None,
                          industry_map: Optional[dict] = None,
                          marketcap_map: Optional[dict] = None,
                          direction_map: Optional[dict] = None,
                          cost: float = 0.002,
                          synth_cfg: Optional[dict] = None,
                          marketcap_proxy_lookback: Optional[int] = None) -> Dict[str, Any]:
    """多因子评价主流程 (融合 网格/机器学习/CASE-C 三大case)

    组合包装: 先做阶段B1数据准备(prep_multi_factor), 再按指定合成方式做
    阶段B2合成+评价(synth_multi_factor_eval)。与分阶段流程共用同一套逻辑,
    保持向后兼容。

    参数:
        factor_panels: {factor_id: DataFrame(index=日期, columns=股票代码)}
        prices_panel:  {stock_code: DataFrame(index=日期, close)}
        rebal_period:  调仓周期(持有期)
        method:        equal / ic_weighted / rank_score / lasso / ml_reg / ml_cls
                       / markowitz / optuna / sharpe / pca
        ic_lookback:   ic_weighted 用历史IC的滚动期数
        top_n_list:    Top-N 集中度回测的 N 列表
        synth_cfg:     可配置参数(筛选/去冗余/方向/PCA/Optuna/ML), 见 DEFAULT_SYNTH_CFG
    """
    prep = prep_multi_factor(
        factor_panels, prices_panel, rebal_period=rebal_period,
        min_warmup=min_warmup, sector_map=sector_map, concept_map=concept_map,
        industry_map=industry_map, marketcap_map=marketcap_map,
        marketcap_proxy_lookback=marketcap_proxy_lookback,
    )
    if "error" in prep:
        return prep
    return synth_multi_factor_eval(
        prep, method=method, ic_lookback=ic_lookback, n_layers=n_layers,
        top_n_list=top_n_list, direction_map=direction_map,
        ml_params=None, cost=cost, synth_cfg=synth_cfg,
    )


def _long_short_from_layers(layer_returns: dict) -> float:
    """多层收益的多空收益 (最高层 - 最低层)"""
    if not layer_returns:
        return np.nan
    keys = sorted(layer_returns.keys())
    if len(keys) < 2:
        return np.nan
    return layer_returns[keys[-1]] - layer_returns[keys[0]]


def _multifactor_topn_backtest(composite_cross: Dict[int, pd.Series],
                               future_returns: Dict[int, pd.Series],
                               prices_panel: Dict[str, pd.DataFrame],
                               dates_idx: pd.DatetimeIndex,
                               rebal_dates: List[int],
                               rebal_period: int,
                               top_n_list: List[int],
                               cost: float = 0.002) -> Dict[str, Any]:
    """多因子 Top-N 组合回测 (等权, 含交易成本)

    返回: {
        nav: {date: {top_n: 净值}},       # 等权组合净值曲线
        metrics: {top_n: {total/annual/sharpe/max_dd/calmar/win_rate/turnover}},
        benchmark: {date: 基准净值},      # 样本等权基准
    }
    """
    # 基准: 每个调仓日全体股票等权未来收益
    nav = {}
    for n_top in top_n_list:
        nav[n_top] = {}
    bench_nav = {}
    bench_val = 1.0
    nav_vals = {n_top: {t: 1.0 for t in rebal_dates} for n_top in top_n_list}
    prev_hold = {n_top: [] for n_top in top_n_list}

    for t in rebal_dates:
        if t not in composite_cross or t not in future_returns:
            continue
        comp = composite_cross[t]
        fut = future_returns[t]
        # 基准: 全体等权
        bench_ret = fut.mean()
        bench_val *= (1 + bench_ret)
        bench_nav[t] = bench_val

        for n_top in top_n_list:
            top = comp.sort_values(ascending=False).head(n_top).index.tolist()
            top_ret = fut.reindex(top).mean()
            # 已持有部分换仓成本 (简化: 按换仓比例 * cost)
            turn = 1.0
            if prev_hold[n_top]:
                new_set = set(top)
                old_set = set(prev_hold[n_top])
                turn = len(new_set - old_set) / max(len(new_set), 1)
            nav_vals[n_top][t] = (1 + top_ret) * (1 - turn * cost)
            prev_hold[n_top] = top

    # 净值累乘 + 日期标签
    for n_top in top_n_list:
        cum = 1.0
        for t in rebal_dates:
            if t in nav_vals[n_top]:
                cum *= nav_vals[n_top][t]
                nav[n_top][str(dates_idx[t].date())] = cum
    bench_curve = {str(dates_idx[t].date()): bench_nav[t] for t in bench_nav}

    # 绩效指标
    metrics = {}
    for n_top in top_n_list:
        vals = list(nav[n_top].values())
        metrics[n_top] = _nav_metrics(vals, len(vals), rebal_period=rebal_period)
    bench_metrics = _nav_metrics(list(bench_curve.values()), len(bench_curve),
                                 rebal_period=rebal_period)

    return {
        "nav": nav,
        "benchmark": bench_curve,
        "metrics": {str(n): m for n, m in metrics.items()},
        "benchmark_metrics": bench_metrics,
    }


def _nav_metrics(nav_vals: List[float], n_periods: int,
                 rebal_period: int = 21) -> Dict[str, Any]:
    """根据净值序列计算绩效指标 (累计/年化/夏普/回撤/卡玛/月度胜率)

    nav_vals: 每个调仓期一个净值点 (每期 = rebal_period 个交易日)
    rebal_period: 调仓周期 (交易日/期), 用于年化折算。
      年化 = (1+累计收益)^(252 / (期数×每期交易日)) - 1
      夏普 = 期收益均值/期收益标准差 × sqrt(252 / 每期交易日)
    修复: 旧实现把期数当"天"直接套 252, 导致年化高估约幂21倍、夏普高估约√21倍。
    """
    if not nav_vals or nav_vals[-1] <= 0:
        return {
            "total": None, "annual": None, "sharpe": None,
            "max_dd": None, "calmar": None, "win_rate": None,
        }
    total = nav_vals[-1] - 1.0
    per = max(int(rebal_period), 1)
    total_days = max(n_periods, 1) * per
    annual = (nav_vals[-1] ** (252.0 / total_days)) - 1.0
    # 每期收益
    rets = [nav_vals[i] / nav_vals[i - 1] - 1 for i in range(1, len(nav_vals))] if len(nav_vals) > 1 else []
    sharpe = None
    if len(rets) > 1:
        m = float(np.mean(rets))
        s = float(np.std(rets, ddof=1))
        if s > 0:
            sharpe = m / s * np.sqrt(252.0 / per)
    # 最大回撤
    peak = nav_vals[0]
    max_dd = 0.0
    for v in nav_vals:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    max_dd = abs(max_dd)
    calmar = annual / max_dd if max_dd > 0 and annual is not None else None
    win_rate = float(np.mean([1 if r > 0 else 0 for r in rets])) if rets else None
    return {
        "total": round(float(total), 4),
        "annual": round(float(annual), 4) if annual is not None else None,
        "sharpe": round(float(sharpe), 4) if sharpe is not None else None,
        "max_dd": round(float(max_dd), 4),
        "calmar": round(float(calmar), 4) if calmar is not None else None,
        "win_rate": round(float(win_rate), 4) if win_rate is not None else None,
    }


# ============================================================
# 二-e、表达式 → 是否"价格水平/累积量纲"因子 (technical_ts 判定)
# ============================================================
# 技术因子中, 均线绝对值(ts_SMA/EMA/WMA...)/价格变换(ts_LINEARREG...)/回归价格/
# OBV/AD/STDDEV/VAR 等输出为跨股票不可比的"绝对量纲"(价格水平/累积量/绝对波动),
# 评价前需先对自身历史做滚动分位(technical_ts), 否则截面IC/分层只是"规模效应"。
# 此处用公式启发式粗判(供 构建页试算/保存自动打标/未入库表达式评价 使用):
#   命中 → 提示并自动标记 technical_ts (仅建议与路由, 用户仍可在因子库详情手动覆盖);
#   未命中 → 维持 technical (保守, 漏判不改变现状, 详情中仍可手工改)。

# 归一化/比率化/动量/比较 算子: 命中说明公式已做量纲归一或逐项比较, 不算纯水平因子
_TS_NORMALIZED_OPS = [
    "returns(", "momentum(", "pct_change", "ts_roc(", "ts_delta(", "ts_pctchange(",
    "bias(", "rsi(", "kdj", "cci(", "willr(", "atr(", "n_atr", "volatility(",
    "vol_ratio", "ts_boll_pos", "price_position", "amplitude(", "body_ratio",
    "shadow_ratio", "ts_mfi(", "stochrsi", "ultosc", "aroon", "adx", "adxr",
    "ts_histvol", "ts_betamomentum", "price_volume_corr", "ts_corr(", "ts_correl(",
    "ts_cov(", "ts_resvol", "ts_log(", "ts_rank(", "ts_quantile", "ts_normalize",
    "ma_bull", "obv_slope", "ts_decay", "normalize", "zscore", "rank(",
    "cross(", "abs(", "sign(", "reversal", "/", ">", "<",
]
# 价格水平/累积量纲/绝对波动/保留量纲的滤波·聚合·延迟·恒等 算子:
# 命中说明输出仍为绝对量纲(价格/量/累积/绝对波动, 或对这些量的线性平滑/聚合/滞后/恒等),
# 跨股票不可比, 需时序标准化(technical_ts)。判断顺序在 _NORMALIZED_OPS 之后,
# 即"先看是否已归一(False), 再看是否绝对量纲(True)"——保证相对量纲表达式不被误判。
_TS_LEVEL_OPS = [
    "ts_ad(", "ts_avgprice(", "ts_linearreg(", "ts_linearreg_intercept(",
    "ts_medprice(", "ts_obv(", "ts_stdev(", "ts_stddev(", "ts_typprice(",
    "ts_var(", "ts_wclprice(", "ts_sma(", "ts_ema(", "ts_wma(", "ts_dema(",
    "ts_tema(", "ts_kama(", "ts_trima(", "ts_mama(", "ts_sar(", "ts_natr(",
    "ts_ma(",
    # 补齐: 保留量的时间域滤波/聚合/延迟/恒等/去均值算子 (输出仍是绝对量纲)
    "ts_mean(", "ts_median(", "ts_sum(", "ts_product(", "ts_count(",
    "ts_delay(", "ts_shift(", "ts_demean(", "ts_identity(", "ts_cumreturn(",
    "ts_argmax(", "ts_argmin(", "ts_linearreg_slope(",
    "dema(", "ema(", "kama(", "mama(", "sar(", "sma(", "tema(", "trima(", "wma(", "ma(",
    "close(", "open(", "high(", "low(", "amount(", "volume(", "vwap(",
]


def _is_technical_ts_expression(expr: Optional[str]) -> bool:
    """粗判表达式是否为"价格水平/累积量纲"因子 (technical_ts)

    判定顺序:
      1. 含归一化/比率/动量/比较算子 → 量纲可比, 判 False (technical)
      2. 含价格水平/累积量纲算子 → 判 True (technical_ts)
      3. 其他 → False (保守)
    与 2026-08-16 对因子库 256 因子全量核对一致: 命中 20 个显式 technical_ts 中的 19 个
    (仅 TALIB_LINREG_R2 的 R2 为无量纲, 漏判无碍); 对真实 technical 因子零误判。
    """
    if not expr:
        return False
    formula = str(expr).lower()
    for kw in _TS_NORMALIZED_OPS:
        if kw in formula:
            return False
    for kw in _TS_LEVEL_OPS:
        if kw in formula:
            return True
    return False


# 行情字段名 → 对应字段基类 (行情字段也是固定参数基类, 复合因子引用它们也构成依赖)
_FIELD_TO_BASE = {
    "Open": "open", "High": "high", "Low": "low", "Close": "close",
    "Volume": "volume", "Amount": "amount", "VWAP": "vwap",
    "Turnover": "turnover_rate",
    "IdioRet": "idioret", "Value": "value", "TotalRet": "totalret",
}


def _extract_dependency_bases(expr: str) -> list:
    """递归提取表达式依赖的全部基类名(去重, 保持出现顺序).

    与 evaluate_expression 的求值命名空间完全对齐, 识别三类 token:
      1) 基类名直接作为函数调用: rsi(  sma(  atr(  macd(  ...  (BASE_OPERATOR_MAP 键)
      2) ts_* 算子调用: 当某算子是某基类(BASE_OPERATOR_MAP 值)的唯一实现时反查计入;
         多基类共用的算子(如 ts_Identity)不反查, 交给裸字段映射处理。
      3) 裸行情字段: 映射到对应字段基类(open/close/volume...), 字段本身也是固定参数基类。
    算子不是基类, 只有能反查/映射到 factor_base 成员的 token 才计入; 解析途径可能不唯一,
    只要解析结果是基础类表成员即可。
    """
    import ast as _ast

    bases = []
    seen = set()

    def _add(b):
        if b and b not in seen:
            seen.add(b)
            bases.append(b)

    # 算子名 → [基类名] 反查索引 (BASE_OPERATOR_MAP 值: (算子函数, 字段列表, 参数个数))
    op_to_bases = {}
    for bid, (fn, _fields, _n) in BASE_OPERATOR_MAP.items():
        op_to_bases.setdefault(fn, []).append(bid)

    try:
        tree = _ast.parse((expr or "").strip(), mode="eval")
    except SyntaxError:
        return bases

    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
            nm = node.func.id
            if nm in BASE_OPERATOR_MAP:
                # 基类名直接调用
                _add(nm)
            else:
                # ts_* 算子 → 反查唯一实现它的基类 (多基类共用如 ts_Identity 不反查)
                bl = op_to_bases.get(nm)
                if bl and len(set(bl)) == 1:
                    _add(bl[0])
        elif isinstance(node, _ast.Name):
            nm = node.id
            if nm in BASE_OPERATOR_MAP:
                _add(nm)
            elif nm in _FIELD_TO_BASE:
                _add(_FIELD_TO_BASE[nm])
    return bases


def analyze_expression_tags(expr: str) -> Dict[str, Any]:
    """从因子表达式自动解析标签 (基类/类型/方向)

    规则 (与 classify_factor_type 保持一致):
      - base_id:     提取表达式中引用的基类实例名 (来自 BASE_OPERATOR_MAP), 逗号分隔
      - factor_type: 含 FN( 判定 financial; 含 ta_CDL 判定 signal;
                     命中价格水平/累积量纲启发式(见 _is_technical_ts_expression)判定 technical_ts;
                     否则 technical
      - direction:   以 -1* 或负号开头的表达式默认反向(negative), 否则正向(positive)
    返回: {"base_id", "factor_type", "direction"}
    """
    expr_lower = (expr or "").lower()
    # 1. 提取表达式依赖的全部基类 (递归解析: 基类名调用 / ts_*算子反查 / 裸行情字段基类)
    #    与求值命名空间一致, 保证"能求值则必能解析出基础类集"
    base_ids: List[str] = _extract_dependency_bases(expr)
    # 2. 类型 (evaluation_type 默认推断, 保存后用户可在前端改)
    #    technical_ts 无法从"因子库标签"区分, 但可由公式启发式粗判: 均线绝对值/价格变换/
    #    回归价格/OBV/AD/STDDEV/VAR 等纯水平/累积量纲因子评价前需先时序分位标准化。
    #    命中即自动标记 technical_ts (建议口径), 用户仍可在因子库详情中手动覆盖。
    if "fn(" in expr_lower:
        factor_type = "financial"
    elif "ta_cdl" in expr_lower:
        factor_type = "signal"
    elif _is_technical_ts_expression(expr):
        factor_type = "technical_ts"
    else:
        factor_type = "technical"
    # 3. 方向: 约定为"公式输出值的期望方向"。公式中内嵌负号的表达式输出已取反,
    #    此处不再按负号推断(避免保存时 direction 与公式负号叠加导致合成双重取负);
    #    默认 positive(公式输出越大越好), 用户可在保存时手动覆盖。
    direction = "positive"
    return {
        "base_id": ",".join(base_ids) if base_ids else None,
        "factor_type": factor_type,
        "direction": direction,
    }


def classify_factor_type(factor_info: Dict[str, Any]) -> str:
    """根据因子元信息判断因子类型, 用于差异化评价 (路由入口)

    路由优先级 (2026-08-15 路由改造):
      1. factor_library.evaluation_type 显式标签 (用户可维护, 最高优先)
           technical     截面连续型 (IC/分层/PWC管线)
           technical_ts  时序标准化截面型 (先对自身历史滚动分位, 再走截面管线)
           signal        事件信号型 (原pattern正名; 含CDL/新高新低/趋势模式等离散事件)
           financial     财报期对齐型
           none          不可独立评价 (构造中间字段/待配引擎)
      2. 标签为空时回退公式规则推断 (仅兜底, 服务历史数据与旧自定义因子)
    """
    et = (factor_info.get("evaluation_type") or "").strip().lower()
    if et:
        # 兼容旧值 pattern -> signal (同一评价框架的正名)
        return "signal" if et == "pattern" else et
    return _infer_factor_type_by_formula(factor_info)


def _infer_factor_type_by_formula(factor_info: Dict[str, Any]) -> str:
    """公式规则推断因子类型 (evaluation_type 为空时的兜底, 不再作为主路由)

    规则:
      technical  技术指标(连续型): 价量/动量/波动/均线/WQ/交互
      signal     K线形态(离散信号型): CDL形态等 0/±100 (原pattern)
      financial  财务因子(季度低频): 基本面/财务
    """
    fid = (factor_info.get("factor_id") or "").lower()
    formula = (factor_info.get("formula") or "").lower()
    category = factor_info.get("category") or ""
    # 1. K线形态: factor_id以CDL_开头 或 公式含ta_CDL (均线乖离虽在pattern类但为连续型, 不命中)
    if fid.startswith("cdl_") or "ta_cdl" in formula:
        return "signal"
    # 2. 财务因子: 公式含FN( 或 类别为fundamental (季度低频, 需财报期对齐)
    #    注: DB中category存中文"基本面", 兼容中英两种取值
    if "fn(" in formula or category in ("fundamental", "基本面"):
        return "financial"
    # 3. 其余为技术指标(连续型), 走统一IC/分层/PerformanceWithCost流程
    return "technical"


def evaluate_pattern_factor(factor_values: pd.DataFrame,
                            prices_panel: Dict[str, pd.DataFrame],
                            rebal_period: int = 21,
                            direction: int = 0) -> Dict[str, Any]:
    """事件信号因子评价 (离散信号型, 2026-08-15 由 pattern 正名并扩展)

    支持两类信号因子:
      1. 双极性因子(CDL形态, 0/±100): 值>0看涨、值<0看跌 (talib约定, direction忽略)
      2. 单极性0/1因子(新高/新低/趋势模式等): 1=事件发生, 多空语义由 direction 决定
         direction=1 看涨事件(如20日新高), -1 看跌事件(如20日新低), 0 双向未知(只看信号超额)

    评价口径:
      1. 信号频率: 有信号占比, 看涨/看跌占比
      2. 命中率: 看涨后N日收益为正、看跌后N日收益为负、整体方向正确的比例
      3. 条件收益: 有信号 vs 无信号 的平均未来N日收益 及 信号收益差

    参数:
        factor_values: index=日期, columns=股票代码, values=因子值
        prices_panel:  {code: df} 日K面板
        rebal_period:  信号评价窗口(未来N日收益)
        direction:     因子方向 1/-1/0(仅单极性0/1因子使用; 从 factor_library.direction 解析)
    """
    # 检测因子值是否为单极性(仅 0 和正值, 无负值): 单极性时多空语义交给 direction
    flat = factor_values.values.flatten()
    flat = flat[~pd.isna(flat)]
    has_negative = bool((flat < -1e-9).any()) if len(flat) else False
    # 双极性(含负值): 按值符号判多空(CDL约定); 单极性: 按 direction 判多空
    use_sign = has_negative

    bull_correct, bull_total = 0, 0
    bear_correct, bear_total = 0, 0
    ret_signal: list = []
    ret_no_signal: list = []
    signal_count, total_count = 0, 0

    for code, df in prices_panel.items():
        if code not in factor_values.columns:
            continue
        f = factor_values[code]
        # 以因子值 f 的 index 为基准遍历 (f 由字段面板 reindex 到统一日期, 长度可能与 df 不同)
        # 避免 df 比 f 长时按 len(df) 遍历导致 f.iloc 越界
        close = df["close"].reindex(f.index)
        for i in range(len(f)):
            if i + rebal_period >= len(f):
                break
            fi = f.iloc[i]
            if pd.isna(fi):
                continue
            total_count += 1
            ret_f = close.iloc[i + rebal_period] / close.iloc[i] - 1.0
            if abs(fi) < 1e-9:  # 无信号
                ret_no_signal.append(ret_f)
                continue
            signal_count += 1
            ret_signal.append(ret_f)
            if use_sign:
                # 双极性: 值符号判多空 (CDL ±100)
                is_bull = fi > 0
            else:
                # 单极性 0/1: direction 判多空; direction=0 时归入"看涨"桶仅作统计展示
                is_bull = direction >= 0
            if is_bull:  # 看涨
                bull_total += 1
                if ret_f > 0:
                    bull_correct += 1
            else:  # 看跌
                bear_total += 1
                if ret_f < 0:
                    bear_correct += 1

    def _ratio(a: int, b: int):
        return round(float(a / b), 4) if b else None

    bull_hit = _ratio(bull_correct, bull_total)
    bear_hit = _ratio(bear_correct, bear_total)
    overall_hit = _ratio(bull_correct + bear_correct, bull_total + bear_total)
    signal_ratio = _ratio(signal_count, total_count) if total_count else None
    bull_ratio = _ratio(bull_total, signal_count) if signal_count else None
    bear_ratio = _ratio(bear_total, signal_count) if signal_count else None

    cond_signal = float(np.mean(ret_signal)) if ret_signal else None
    cond_nosig = float(np.mean(ret_no_signal)) if ret_no_signal else None
    signal_alpha = (cond_signal - cond_nosig) if (cond_signal is not None and cond_nosig is not None) else None

    return {
        "factor_type": "signal",
        # 信号极性模式: sign=双极性(值符号判多空, CDL类); direction=单极性(由direction判多空)
        "polarity_mode": "sign" if use_sign else "direction",
        "direction": int(direction) if not use_sign else 0,
        "signal_frequency": {
            "signal_ratio": signal_ratio,
            "bull_ratio": bull_ratio,
            "bear_ratio": bear_ratio,
            "signal_count": int(signal_count),
            "bull_count": int(bull_total),
            "bear_count": int(bear_total),
            "total_count": int(total_count),
        },
        "hit_rate": {
            "bull_hit_rate": bull_hit,
            "bear_hit_rate": bear_hit,
            "overall_hit_rate": overall_hit,
        },
        "conditional_return": {
            "signal_return": cond_signal,
            "no_signal_return": cond_nosig,
            "signal_alpha": signal_alpha,
        },
        "rebal_period": rebal_period,
    }


# 正名别名: evaluate_signal_factor (语义更准确; 旧名保留兼容既有调用)
evaluate_signal_factor = evaluate_pattern_factor


def run_ic_timeseries(prices_panel: Dict[str, pd.DataFrame],
                      calc_factor_fn: Callable,
                      rebal_period: int = 21,
                      min_warmup: int = 130,
                      industry_map: Optional[dict] = None) -> Dict[str, Any]:
    """
    IC 时序回测: 对指定因子计算多期 IC 序列

    参数:
        prices_panel:  {stock_code: DataFrame (含 close/volume/amount)}
        calc_factor_fn: 函数, 输入 df 返回 {factor_name: value}
        rebal_period:  调仓周期
        min_warmup:    最小预热天数
        industry_map:  行业映射

    返回: {ic_series, ic_mean, ic_std, ir, rank_ic_series, ...}
    """
    first_code = next(iter(prices_panel))
    n = len(prices_panel[first_code].index)
    rebal_dates = list(range(min_warmup, n - rebal_period, rebal_period))

    ic_list = []
    rank_ic_list = []
    dates = []

    for end_idx in rebal_dates:
        date_t = prices_panel[first_code].index[end_idx]
        # 计算因子截面
        rows = {}
        for code, df in prices_panel.items():
            if date_t not in df.index or end_idx < min_warmup:
                continue
            sub = df.loc[:date_t]
            f = calc_factor_fn(sub)
            if f:
                rows[code] = f
        if len(rows) < 30:
            continue
        factor_df = pd.DataFrame.from_dict(rows, orient="index")

        # 预处理
        factor_processed = preprocess_factors(factor_df, industry_map, neutralize=bool(industry_map))

        # 未来收益 (按日期对齐: 修复停牌缺行导致的 iloc 位置错位)
        date_fut = prices_panel[first_code].index[min(end_idx + rebal_period, n - 1)]
        future_ret = {}
        for code, df in prices_panel.items():
            if date_t not in df.index or date_fut not in df.index:
                continue
            p_now = df.at[date_t, "close"]
            p_future = df.at[date_fut, "close"]
            if pd.notna(p_now) and p_now > 0 and pd.notna(p_future):
                future_ret[code] = p_future / p_now - 1.0
        future_ret = pd.Series(future_ret)

        # 多因子合成 (等权)
        alpha = factor_processed.mean(axis=1).dropna()

        ic = calc_ic(alpha, future_ret, method="pearson")
        rank_ic = calc_ic(alpha, future_ret, method="spearman")
        ic_list.append(ic)
        rank_ic_list.append(rank_ic)
        dates.append(date_t)

    ic_arr = np.array([x for x in ic_list if not np.isnan(x)])
    rank_ic_arr = np.array([x for x in rank_ic_list if not np.isnan(x)])

    return {
        "ic_series": [{"date": str(d), "ic": float(v) if pd.notna(v) else None}
                       for d, v in zip(dates, ic_list)],
        "rank_ic_series": [{"date": str(d), "ic": float(v) if pd.notna(v) else None}
                            for d, v in zip(dates, rank_ic_list)],
        "ic_mean": float(ic_arr.mean()) if len(ic_arr) else None,
        "ic_std": float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else None,
        "ir": float(ic_arr.mean() / ic_arr.std(ddof=1)) if len(ic_arr) > 1 and ic_arr.std(ddof=1) > 0 else None,
        "rank_ic_mean": float(rank_ic_arr.mean()) if len(rank_ic_arr) else None,
        "rank_ic_ir": (float(rank_ic_arr.mean() / rank_ic_arr.std(ddof=1))
                       if len(rank_ic_arr) > 1 and rank_ic_arr.std(ddof=1) > 0 else None),
        "ic_positive_ratio": float((ic_arr > 0).mean()) if len(ic_arr) else None,
        "samples": len(ic_arr),
    }


def run_ic_timeseries_panel(factor_values: pd.DataFrame,
                            prices_panel: Dict[str, pd.DataFrame],
                            rebal_period: int = 21,
                            min_warmup: int = 130,
                            sector_map: Optional[dict] = None,
                            concept_map: Optional[dict] = None,
                            industry_map: Optional[dict] = None,
                            marketcap_map: Optional[dict] = None,
                            rebal_dates: Optional[List[int]] = None,
                            n_layers: int = 5,
                            marketcap_proxy_lookback: Optional[int] = None,
                            ts_normalize_window: Optional[int] = None) -> Dict[str, Any]:
    """基于预计算面板的IC时序回测 + 多期分层回测 (配合calc_factor使用)

    参数:
        factor_values: 预计算的因子面板 (index=日期, columns=股票代码)
        prices_panel:  {stock_code: DataFrame}
        rebal_period:  调仓周期
        min_warmup:    最小预热天数
        sector_map:    板块映射 (优先)
        concept_map:   概念映射
        industry_map:  行业映射
        marketcap_map: 市值映射 (静态, 与分组维度可叠加做回归中性化; 旧口径)
        rebal_dates:   自定义调仓日(位置索引列表, 可选)。传入后忽略 min_warmup 的
                       固定周期采样, 按给定调仓日计算IC (用于财务因子按财报期对齐)
        n_layers:      分层回测层数 (每期按因子值分 n_layers 组)
        marketcap_proxy_lookback: 市值代理窗口 (交易日)。非 None 时忽略静态 marketcap_map,
                       每期用截面当日可得的"近N日成交额均值"构造点-in-time 市值代理
                       (修复: 静态"当前市值"作用于历史截面的时点错配/前视)。
        ts_normalize_window: 时序标准化窗口 (technical_ts 类因子使用, 默认None不启用)。
                       非None时每只股票的因子值先对自身近N日历史做滚动分位排名
                       (含当日, 当日收盘信息可知, 无前视), 转为[0,1]的"自身历史分位"
                       后再走截面管线——用于价格水平/累积量纲/绝对波动类因子
                       (均线绝对值/OBV/STDDEV等), 其原始截面排序只是规模效应。
                       min_warmup 会自动提高到不低于该窗口。

    返回额外包含 "layered": {
        layer_returns: 各层未来收益的跨期平均 ({层号: 平均收益}),
        long_short:    多空(最高层-最低层)跨期平均收益,
        layer_cumret:  各层累计净值曲线 ({层号: [{date, cumret}]}),
        long_short_cumret: 多空累计净值曲线 ([{date, cumret}]),
    }
    """
    first_code = next(iter(prices_panel))
    n = len(prices_panel[first_code].index)
    base_index = prices_panel[first_code].index

    # 时序标准化 (technical_ts): 因子值 -> 自身近N日历史的滚动分位[0,1]
    fv_panel = factor_values
    if ts_normalize_window:
        fv_panel = factor_values.rolling(
            ts_normalize_window,
            min_periods=max(20, ts_normalize_window // 2),
        ).rank(pct=True)
        min_warmup = max(min_warmup, ts_normalize_window)

    if rebal_dates is None:
        rebal_dates = list(range(min_warmup, n - rebal_period, rebal_period))

    ic_list = []
    rank_ic_list = []
    dates = []
    layer_returns_list: List[Optional[dict]] = []   # 与 dates 对齐 (无有效分层期记 None)
    long_short_list: List[Optional[float]] = []     # 与 dates 对齐

    for end_idx in rebal_dates:
        if end_idx >= len(fv_panel.index):
            continue

        # 从面板中取当前截面
        factor_row = fv_panel.iloc[end_idx]
        factor_df = pd.DataFrame({"factor": factor_row}).dropna()

        if len(factor_df) < 30:
            continue

        # 截面日期 (基准日历) 与市值代理 (点-in-time)
        date_t = base_index[end_idx]
        mc_map = marketcap_map
        if marketcap_proxy_lookback:
            mc_map = build_marketcap_proxy_map(prices_panel, date_t,
                                               lookback=marketcap_proxy_lookback)

        # 预处理 (截面)
        factor_processed = preprocess_factors(
            factor_df,
            industry_map=industry_map,
            sector_map=sector_map,
            concept_map=concept_map,
            marketcap_map=mc_map,
            neutralize=bool(sector_map or concept_map or industry_map or mc_map is not None)
        )
        alpha = factor_processed["factor"]

        # 未来收益 (按日期对齐: 修复停牌缺行导致的 iloc 位置错位)
        date_fut = base_index[min(end_idx + rebal_period, n - 1)]
        future_ret = {}
        for code in alpha.index:
            df = prices_panel.get(code)
            if df is None or date_t not in df.index or date_fut not in df.index:
                continue
            p_now = df.at[date_t, "close"]
            p_future = df.at[date_fut, "close"]
            if pd.notna(p_now) and p_now > 0 and pd.notna(p_future):
                future_ret[code] = p_future / p_now - 1.0
        future_ret = pd.Series(future_ret)

        ic = calc_ic(alpha, future_ret, method="pearson")
        rank_ic = calc_ic(alpha, future_ret, method="spearman")
        ic_list.append(ic)
        rank_ic_list.append(rank_ic)
        dates.append(date_t)

        # 同期分层回测 (累计成多期曲线, 与 CASE-C/layered_backtest 口径一致)
        lr = run_layered_backtest(alpha, future_ret, n_layers=n_layers)
        if lr.get("layer_returns"):
            layer_returns_list.append(lr["layer_returns"])
            ls = lr.get("long_short")
            long_short_list.append(float(ls) if ls is not None and pd.notna(ls) else None)
        else:
            layer_returns_list.append(None)
            long_short_list.append(None)

    ic_arr = np.array([x for x in ic_list if not np.isnan(x)])
    rank_ic_arr = np.array([x for x in rank_ic_list if not np.isnan(x)])

    # ===== 多期分层汇总 (平均分层收益 + 各层累计净值曲线) =====
    layered: Dict[str, Any] = {"layer_returns": {}, "long_short": None,
                               "layer_cumret": {}, "long_short_cumret": []}
    valid_layers = [lr for lr in layer_returns_list if lr]
    if valid_layers:
        # 各层平均收益
        agg: Dict[int, List[float]] = {}
        for lr in valid_layers:
            for k, v in lr.items():
                agg.setdefault(int(k), []).append(float(v))
        layer_returns = {int(k): round(float(np.mean(v)), 6) for k, v in sorted(agg.items())}
        layered["layer_returns"] = layer_returns
        if len(layer_returns) >= 2:
            ks = sorted(layer_returns.keys())
            layered["long_short"] = round(layer_returns[ks[-1]] - layer_returns[ks[0]], 6)
        # 各层累计净值曲线 (与 dates 对齐; 无分层期按 0 收益衔接, 保持曲线时间轴连续)
        n_layers_actual = max(max(lr.keys()) for lr in valid_layers) + 1
        for layer in range(n_layers_actual):
            rets = [lr.get(layer, 0.0) for lr in layer_returns_list if lr is not None]
            sub_dates = [d for d, lr in zip(dates, layer_returns_list) if lr is not None]
            if not rets:
                continue
            cum = np.cumprod([1 + r for r in rets]) - 1
            layered["layer_cumret"][layer] = [
                {"date": str(d), "cumret": float(c)} for d, c in zip(sub_dates, cum)
            ]
        # 多空累计净值曲线
        ls_full = [0.0 if v is None else v for v in long_short_list]
        if len(ls_full) > 0:
            cum = np.cumprod([1 + r for r in ls_full]) - 1
            layered["long_short_cumret"] = [
                {"date": str(d), "cumret": float(c)} for d, c in zip(dates, cum)
            ]

    return {
        "ic_series": [{"date": str(d), "ic": float(v) if pd.notna(v) else None}
                       for d, v in zip(dates, ic_list)],
        "rank_ic_series": [{"date": str(d), "ic": float(v) if pd.notna(v) else None}
                            for d, v in zip(dates, rank_ic_list)],
        "ic_mean": float(ic_arr.mean()) if len(ic_arr) else None,
        "ic_std": float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else None,
        "ir": float(ic_arr.mean() / ic_arr.std(ddof=1)) if len(ic_arr) > 1 and ic_arr.std(ddof=1) > 0 else None,
        "rank_ic_mean": float(rank_ic_arr.mean()) if len(rank_ic_arr) else None,
        "rank_ic_ir": (float(rank_ic_arr.mean() / rank_ic_arr.std(ddof=1))
                       if len(rank_ic_arr) > 1 and rank_ic_arr.std(ddof=1) > 0 else None),
        "ic_positive_ratio": float((ic_arr > 0).mean()) if len(ic_arr) else None,
        "samples": len(ic_arr),
        "layered": layered,
    }


def financial_report_rebal_dates(factor_values: pd.DataFrame,
                                 prices_panel: Dict[str, pd.DataFrame],
                                 rebal_period: int = 63,
                                 min_warmup: int = 0) -> List[int]:
    """财务因子按财报期对齐的调仓日 (位置索引)

    财务因子为季度低频数据, 因子值仅在财报"数据可用日"(report_date+lag)发生变化。
    因此调仓点应取财报数据可用日, 而非固定周期采样, 避免在无新信息的区间反复采样
    导致 IC 时序过度稀疏/阶梯状。财报滞后(report_date+lag_days)已由 FN 与
    load_financial_panel 内置, 保证取值不泄漏未来信息。

    参数:
        factor_values: 预计算的财务因子面板 (index=日期已对齐 prices_panel)
        prices_panel:  {stock_code: DataFrame}
        rebal_period:  未来收益调仓窗口 (默认63日≈一季度)
        min_warmup:    最小预热天数 (财务因子无需滚动预热, 默认0)

    返回: 财报数据可用日在 prices_panel 中的位置索引列表 (升序)
    """
    first_code = next(iter(prices_panel))
    prices_idx = prices_panel[first_code].index
    n = len(prices_idx)
    # 因子值发生变化的日期 = 财报数据可用日 (含滞后, 已避免未来函数)
    diff = factor_values.diff().abs().sum(axis=1)
    change_dates = set(diff[diff > 0].index)
    # 首个有有效值的日期 (因子首次从 NaN 变为可用, diff 无法识别 NaN->值 的跳变)
    first_available = factor_values.notna().any(axis=1)
    first_available = first_available[first_available].index
    if len(first_available):
        change_dates.add(first_available[0])
    result = []
    for d in change_dates:
        try:
            loc = prices_idx.get_loc(d)
        except (KeyError, TypeError):
            continue
        if min_warmup <= loc <= n - 1 - rebal_period:
            result.append(loc)
    return sorted(result)


def run_single_ic_timeseries(factor_series: pd.Series,
                             prices: pd.DataFrame,
                             rebal_period: int = 21,
                             window: int = 60,
                             min_warmup: int = 130) -> Dict[str, Any]:
    """单股时间序列IC评价 (来源: 机器学习CASE 茅台 calc_rank_ic 的滚动窗口版)

    单只股票无法做截面IC (同一时点只有1个样本), 改走时间序列IC:
      对每个调仓时点 t, 用过去 window 个交易日的 (因子值, 未来rebal日收益) 对
      计算 Pearson IC 与 Spearman RankIC, 得到 IC 时序序列及均值/IR/胜率.

    参数:
        factor_series: 单股因子值时间序列 (index=日期)
        prices:        单股日K DataFrame (需含 close)
        rebal_period:  调仓周期 (未来收益天数)
        window:        滚动窗口大小 (过去多少个交易日算一次IC)
        min_warmup:    最小预热期 (跳过前期数据不足的时点)
    返回: {ic_series, rank_ic_series, ic_mean, ic_std, ir,
            rank_ic_mean, rank_ic_ir, ic_positive_ratio, samples}
    """
    close = prices["close"].astype(float)
    # 构造对齐序列: r_t = close[t+rebal]/close[t] - 1
    f_series = factor_series.reindex(close.index)
    fut = close.shift(-rebal_period) / close - 1.0
    df = pd.DataFrame({"f": f_series, "r": fut}).dropna()
    if len(df) < window + 5:
        return {"ic_series": [], "rank_ic_series": [], "ic_mean": None,
                "ic_std": None, "ir": None, "rank_ic_mean": None,
                "rank_ic_ir": None, "ic_positive_ratio": None, "samples": 0}

    ic_list, rank_list, dates = [], [], []
    idx = df.index
    # 从 min_warmup 起, 每 rebal_period 取一个时点, 用滚动窗口算IC
    for t in range(min_warmup, len(df), rebal_period):
        win = df.iloc[max(0, t - window):t]
        if len(win) < 30 or win["f"].nunique() < 5:
            continue
        ic = win["f"].corr(win["r"], method="pearson")
        rank = win["f"].corr(win["r"], method="spearman")
        if not np.isnan(ic):
            ic_list.append(ic)
            rank_list.append(rank)
            dates.append(idx[t - 1])

    ic_arr = np.array([x for x in ic_list if not np.isnan(x)])
    rank_arr = np.array([x for x in rank_list if not np.isnan(x)])

    return {
        "ic_series": [{"date": str(d), "ic": float(v) if pd.notna(v) else None}
                      for d, v in zip(dates, ic_list)],
        "rank_ic_series": [{"date": str(d), "ic": float(v) if pd.notna(v) else None}
                           for d, v in zip(dates, rank_list)],
        "ic_mean": float(ic_arr.mean()) if len(ic_arr) else None,
        "ic_std": float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else None,
        "ir": float(ic_arr.mean() / ic_arr.std(ddof=1)) if len(ic_arr) > 1 and ic_arr.std(ddof=1) > 0 else None,
        "rank_ic_mean": float(rank_arr.mean()) if len(rank_arr) else None,
        "rank_ic_ir": (float(rank_arr.mean() / rank_arr.std(ddof=1))
                       if len(rank_arr) > 1 and rank_arr.std(ddof=1) > 0 else None),
        "ic_positive_ratio": float((ic_arr > 0).mean()) if len(ic_arr) else None,
        "samples": len(ic_arr),
    }


# ============================================================
# 七、表达式安全解析 (用于因子构建页面)
# ============================================================

# 允许的函数名白名单
# 自动收集本模块中所有已定义的 ts_* 时序算子 与 ta_* 动态K线形态函数,
# 避免 Talib 指标因子(如 TALIB_MOM/PPO/DEMA/SAR)因算子未登记而无法计算。
_SAFE_FUNCTIONS = {
    # 原有cs_*截面算子
    "cs_Rank", "cs_Mean", "cs_Demean", "cs_Zscore", "cs_TransNorm",
    "cs_Scale", "cs_MinMaxScale", "cs_Winsorize",
    "cs_RankRL", "cs_ZscoreRL", "cs_TransNormRL",
    # 新增财务数据引用
    "FN", "fin_Delay",
    # AlphaMaster 映射补充算子 (非 ts_* 前缀, 需手动登记, 见 AlphaMaster特征算子与因子库映射方案.md 3.1)
    "sign", "gate", "jump", "max3", "power", "signed_log", "sqrt", "log",
    "clip", "sigmoid", "sigmoid_squash", "tanh_squash", "if_gt", "winsorize",
}
# 自动登记所有 ts_* / ta_* 函数 (含动态生成的 ta_CDL*)
_SAFE_FUNCTIONS.update(
    name for name, obj in globals().items()
    if callable(obj) and (name.startswith("ts_") or name.startswith("ta_"))
)

# 允许的字段名白名单
# 注: PE/PB/ROE 已移除 —— 日K中不存在这些列, 保留会导致校验通过但求值报错;
#     估值类因子请用表达式构造 (如 Close / FN(eps))。
_SAFE_FIELDS = {
    "Open", "High", "Low", "Close", "Volume", "Amount", "VWAP",
    "Turnover",
    # 清华WQ复杂因子用到的派生字段 (在_build_field_dfs中计算)
    "IdioRet", "Value", "TotalRet",
}

# 财务字段白名单 (FN函数的参数, 在表达式FN(roe)中作为字符串注入)
# 来源: lib/financial_data.py 的 _FINANCIAL_FIELDS + factor_init.py 中用到的额外字段
_FN_FIELDS = {
    "revenue", "net_profit", "eps", "roe", "roa",
    "gross_margin", "net_margin", "debt_ratio",
    "current_ratio", "quick_ratio",
    "operating_cashflow", "investing_cashflow", "financing_cashflow",
    "total_assets", "total_equity", "total_liab",
    "monetary_funds", "total_shares",
    "ocf_to_revenue", "ocf_to_profit",
    "op_margin", "assets_turn", "ocfps", "bps",
}

# 允许的运算符和内置函数
_SAFE_NAMES = {
    "abs": abs, "max": max, "min": min, "pow": pow, "round": round,
    "np": np, "pd": pd,
    # 允许 np.maximum/np.minimum 中的 maximum/minimum (K线形态影线比因子的元素级取大取小)
    "maximum": np.maximum, "minimum": np.minimum,
}


# ============================================================
# 基类实例展开: 把 "基类名(参数)" 映射为具体引擎算子调用
# 使因子表达式支持 rsi(14)/adx(14)/momentum(5) 等基类实例形式
# ============================================================
# 键: 基类ID (小写, 用于表达式函数名)
# 值: (算子函数, 算子所需字段列表, 参数个数)
#   算子函数签名包含 (字段面板..., 参数...)
# 实现: 在 evaluate_expression 中, 将基类名注册为可调用函数,
#       调用时展开为对应算子并注入已构建的字段面板。
BASE_OPERATOR_MAP = {
    # ---- periodic: 需指定周期 ----
    "returns":           ("ts_PctChange", ["Close"], 1),
    "momentum":          ("ts_ROC", ["Close"], 1),
    "amplitude":         ("ts_Amplitude", ["High", "Low", "Close"], 1),
    "volume_ratio":      ("ts_VolRatio", ["Volume"], 1),
    "volatility":        ("ts_HistVol", ["Close"], 1),
    "price_volume_corr": ("ts_Corr", ["Close", "Volume"], 1),
    "bias":              ("ts_Bias", ["Close"], 1),
    "price_position":    ("ts_PricePosition", ["Close"], 1),
    # 注: 原 "turnover" 键(实为 ts_VolRatio 量比)已删除 —— 与 volume_ratio 键完全重复;
    #     真换手率由 "turnover_rate" 键承载(映射 Turnover 行情字段, 固定不参数化)。
    "turnover_rate":     ("ts_Identity", ["Turnover"], 0),
    "sma":               ("ts_SMA", ["Close"], 1),
    "ema":               ("ts_EMA", ["Close"], 1),
    "dema":              ("ts_DEMA", ["Close"], 1),
    "tema":              ("ts_TEMA", ["Close"], 1),
    "wma":               ("ts_WMA", ["Close"], 1),
    "kama":              ("ts_KAMA", ["Close"], 1),
    "trima":             ("ts_TRIMA", ["Close"], 1),
    "mama":              ("ts_MAMA", ["Close"], 1),
    "sar":               ("ts_SAR", ["High", "Low"], 1),
    "sar_dist":          ("ts_SAR_DIST", ["Close", "High", "Low"], 0),
    # ---- fixed 可调参数 (实例为复合因子) ----
    "rsi":               ("ts_RSI", ["Close"], 1),
    "adx":               ("ts_ADX", ["High", "Low", "Close"], 1),
    "cci":               ("ts_CCI", ["High", "Low", "Close"], 1),
    "willr":             ("ts_WILLR", ["High", "Low", "Close"], 1),
    "atr":               ("ts_ATR", ["High", "Low", "Close"], 1),
    "reversal":          ("ts_PctChange", ["Close"], 1),
    # ---- fixed 固定参数 (实例为复合因子, 参数个数固定) ----
    "macd":              ("ts_MACD_DIF", ["Close"], 0),
    "kdj":               ("ts_KDJ_K", ["High", "Low", "Close"], 0),
    "bbands":            ("ts_BOLL_POS", ["Close"], 0),
    "bbands_width":      ("ts_BOLL_WIDTH", ["Close"], 0),
    # ---- TALIB 族具体技术基础因子 (fixed basic, 固定标准参数, 实例即基础因子) ----
    # 供 GP 基类叶子引用 (如 TALIB_MFI()), 展开为对应 ts_* 算子并绑定所需字段;
    # 已在 factor_base 登记为基类, 作固定参数叶子 (None=用引擎默认参数)。
    "TALIB_MFI":         ("ts_MFI", ["High", "Low", "Close", "Volume"], 0),
    "TALIB_OBV":         ("ts_OBV", ["Close", "Volume"], 0),
    "TALIB_AD":          ("ts_AD", ["High", "Low", "Close", "Volume"], 0),
    "TALIB_ADOSC":       ("ts_ADOSC", ["High", "Low", "Close", "Volume"], 0),
    "TALIB_NATR":        ("ts_NATR", ["High", "Low", "Close"], 0),
    "TALIB_TRANGE":      ("ts_TRANGE", ["High", "Low", "Close"], 0),
    "TALIB_STOCHF":      ("ts_STOCHF_K", ["High", "Low", "Close"], 0),
    "TALIB_STOCHRSI":    ("ts_STOCHRSI_K", ["Close"], 0),
    "TALIB_AROON":       ("ts_AROON_UP", ["High", "Low"], 0),
    "TALIB_AROONOSC":    ("ts_AROONOSC", ["High", "Low"], 0),
    "TALIB_ADXR":        ("ts_ADXR", ["High", "Low", "Close"], 0),
    "TALIB_UO":          ("ts_ULTOSC", ["High", "Low", "Close"], 0),
    "TALIB_AVGPRICE":    ("ts_AVGPRICE", ["Open", "High", "Low", "Close"], 0),
    "TALIB_MEDPRICE":    ("ts_MEDPRICE", ["High", "Low"], 0),
    "TALIB_TYPPRICE":    ("ts_TYPPRICE", ["High", "Low", "Close"], 0),
    "TALIB_WCLPRICE":    ("ts_WCLPRICE", ["High", "Low", "Close"], 0),
    "TALIB_HT_DCPERIOD": ("ts_HT_DCPERIOD", ["Close"], 0),
    "TALIB_HT_DCPHASE":  ("ts_HT_DCPHASE", ["Close"], 0),
    "TALIB_HT_TRENDMODE": ("ts_HT_TRENDMODE", ["Close"], 0),
    "TALIB_PPO":         ("ts_PPO", ["Close"], 0),
    "TALIB_BETA":        ("ts_BETA", ["Close"], 0),
    "TALIB_CORREL":      ("ts_CORREL", ["Close"], 0),
    # ---- 最基础行情字段 (恒等变换, 可实例化为自身) ----
    "open":              ("ts_Identity", ["Open"], 0),
    "high":              ("ts_Identity", ["High"], 0),
    "low":               ("ts_Identity", ["Low"], 0),
    "close":             ("ts_Identity", ["Close"], 0),
    "volume":            ("ts_Identity", ["Volume"], 0),
    "amount":            ("ts_Identity", ["Amount"], 0),
    "vwap":              ("ts_Identity", ["VWAP"], 0),
    # ---- 派生字段 (供清华WQ复杂因子引用, 在_build_field_dfs中计算) ----
    "value":             ("ts_Identity", ["Value"], 0),
    "idioret":           ("ts_Identity", ["IdioRet"], 0),
    "totalret":          ("ts_Identity", ["TotalRet"], 0),
    # ---- AlphaMaster 映射补充参数化基类 (见 AlphaMaster特征算子与因子库映射方案.md 3.3.2) ----
    "trend_strength":    ("ts_TrendStrength", ["Close"], 1),
    "gk_vol":            ("ts_GKVol", ["Open", "High", "Low", "Close"], 1),
    "parkinson_vol":     ("ts_ParkinsonVol", ["High", "Low"], 1),
    "yang_zhang_vol":    ("ts_YangZhangVol", ["Open", "High", "Low", "Close"], 1),
    "rs_vol":            ("ts_RSVol", ["Open", "High", "Low", "Close"], 1),
    "autocorr":          ("ts_Autocorr", ["Close"], 1),
    "typical_dev":       ("ts_TypicalDev", ["Open", "High", "Low", "Close"], 1),
    "dmi_diff":          ("ts_DmiDiff", ["High", "Low", "Close"], 1),
    "trix":              ("ts_Trix", ["Close"], 1),
    "amihud_illiq":      ("ts_AmihudIlliq", ["Close", "Volume"], 1),
    "kyle_lambda":       ("ts_KyleLambda", ["Close", "Volume"], 1),
    "cmf":               ("ts_CMF", ["High", "Low", "Close", "Volume"], 1),
    "ad_line_slope":     ("ts_ADLineSlope", ["Open", "High", "Low", "Close", "Volume"], 1),
    "hurst":             ("ts_Hurst", ["Close"], 1),
    "fractal_dim":       ("ts_FractalDim", ["Close"], 1),
    "ret_entropy":       ("ts_RetEntropy", ["Close"], 1),
    "keltner":           ("ts_KeltnerPos", ["Close", "High", "Low"], 1),
    "ichimoku_kijun":    ("ts_IchimokuKijun", ["High", "Low"], 1),
    "ichimoku_tenkan":   ("ts_IchimokuTenkan", ["High", "Low"], 1),
    "supertrend":        ("ts_SuperTrend", ["High", "Low", "Close"], 1),
}

# 基类映射中算子求值顺序号 (保持与 ts_* 算子定义一致)
BASE_OPERATOR_FUNC = {}


def _expanded_field_list(field_dfs: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """返回评估时使用的字段面板 (基类展开用)"""
    return field_dfs


def _make_base_callable(base_id: str, field_dfs: Dict[str, pd.DataFrame]):
    """为单个基类生成可调用函数, 供 evaluate_expression 注入命名空间

    调用形式: base_callable(参数...)  ->  展开为算子(字段面板..., 参数...)
    例如 rsi(14) -> ts_RSI(Close面板, 14)
    """
    if base_id not in BASE_OPERATOR_MAP:
        return None
    fn_name, fields, _nparams = BASE_OPERATOR_MAP[base_id]
    fn = globals().get(fn_name)
    if fn is None:
        return None
    field_list = [field_dfs[f] for f in fields if f in field_dfs]

    def base_callable(*args):
        # 算子需要的字段数 = fields 长度 (已在上面按字段构建)
        return fn(*field_list, *args)

    # 特殊基类: reversal = -ts_PctChange (取负)
    if base_id == "reversal":
        def base_callable(*args):
            return -fn(*field_list, *args)
    # 特殊基类: atr 归一化 = ts_ATR / Close
    if base_id == "atr":
        def base_callable(*args):
            close = field_dfs.get("Close")
            r = fn(*field_list, *args)
            if close is not None:
                return r / close.replace(0, np.nan)
            return r
    return base_callable


def validate_expression(expr: str) -> tuple[bool, str]:
    """
    验证因子表达式是否安全
    返回 (is_valid, message)
    """
    if not expr or not expr.strip():
        return False, "表达式不能为空"

    # 检查危险字符
    if re.search(r"[;{}\[\]]", expr):
        return False, "表达式包含非法字符"

    # 检查 import / exec / eval 等 (Python内置均为小写, 不使用IGNORECASE避免误伤Open等字段名)
    # 注意: open 同时是合法基类名(开盘价), namespace中已用基类函数替换内置open, 且__builtins__已清空,
    #       因此 open 作为基类调用是安全的, 需从危险关键字中放行。
    _danger = [w for w in ("import", "exec", "eval", "file", "os", "sys", "subprocess")
               if w not in BASE_OPERATOR_MAP]
    if _danger and re.search(r"\b(" + "|".join(_danger) + r")\b", expr):
        return False, "表达式包含危险关键字"
    # open 仅在非基类调用形式(如 open(...) 使用了内置open)时拦截, 这里由后续标识符白名单兜底

    # 提取所有标识符
    identifiers = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr))

    for ident in identifiers:
        if ident in _SAFE_FUNCTIONS:
            continue
        if ident in _SAFE_FIELDS:
            continue
        if ident in _FN_FIELDS:
            continue
        if ident in _SAFE_NAMES:
            continue
        # 基类实例: 允许基类名作为函数名 (rsi/adx/momentum等)
        if ident in BASE_OPERATOR_MAP:
            continue
        # 数字常量
        if ident in ("True", "False", "None"):
            continue
        # 如果是纯数字
        if ident.isdigit():
            continue
        return False, f"未知标识符: {ident}"

    return True, "OK"


# ============================================================
# _build_field_dfs 结果缓存 (LRU, 上限20条)
# 批量评价 / 多因子合成 / 组合风险分析会以"同一 panel 对象"反复调用本函数构建
# 字段面板, 每次重复构建约 8 字段 × N 股票 的 DataFrame 拷贝, 缓存可显著降低批量耗时。
# 缓存键 = 面板对象id + 结构指纹(股票集/日期跨度/每股末行数据), 并在值中持有面板
# 强引用, 防止面板被回收后 id 复用造成误命中; 面板构建后即视为只读, 不原地修改。
# ============================================================
_FIELD_DFS_CACHE: "OrderedDict[tuple, tuple]" = OrderedDict()
_FIELD_DFS_CACHE_MAX = 20


def _panel_cache_key(panel: Dict[str, pd.DataFrame]) -> Optional[tuple]:
    """生成面板缓存键 (对象id + 结构指纹)

    指纹包含: 排序股票集 / 首只股票日期跨度 / 每股末行数据字节哈希。
    末行哈希可捕捉复权切换、数据更新等"同结构不同内容"变化, 避免误命中旧缓存。
    全部为 O(股票数) 轻量计算, 远小于逐字段重建面板的开销。
    """
    if not panel:
        return None
    codes = sorted(panel.keys())
    ref = panel[codes[0]]
    span = (str(ref.index[0]), str(ref.index[-1]), len(ref))
    tails = []
    for c in codes:
        dfc = panel[c]
        if len(dfc):
            try:
                tail_hash = hash(dfc.iloc[-1].astype(float).to_numpy().tobytes())
            except Exception:
                tail_hash = None
            tails.append((len(dfc), tail_hash))
        else:
            tails.append((0, None))
    return (id(panel), tuple(codes), span, tuple(tails))


def _build_field_dfs(panel: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """从面板数据构建字段DataFrame (index=日期, columns=股票代码)

    VWAP字段特殊处理: 若数据中无vwap列, 自动从 amount/volume 计算
    派生字段(清华WQ复杂因子用):
      IdioRet  截面去均值日收益率 (特异质收益的简单代理)
      TotalRet 日收益率面板 (清华原版语义, 非累计指数)
      Value    成交额(amount)代理, 作为市值/成交额规模字段

    性能优化: 同面板对象的结果做 LRU 缓存 (见 _FIELD_DFS_CACHE), 批量评价时
    同一 panel 会被多个因子反复构建字段面板, 缓存避免重复构建。
    """
    key = _panel_cache_key(panel)
    if key is not None:
        hit = _FIELD_DFS_CACHE.get(key)
        if hit is not None:
            _FIELD_DFS_CACHE.move_to_end(key)
            return hit[0]

    first_code = next(iter(panel))
    dates = panel[first_code].index

    field_dfs = {}
    for field in _SAFE_FIELDS:
        if field in ("IdioRet", "TotalRet", "Value"):
            continue  # 派生字段在下方统一计算
        cols = {}
        for code, df in panel.items():
            col_map = {
                "Open": "open", "High": "high", "Low": "low", "Close": "close",
                "Volume": "volume", "Amount": "amount", "VWAP": "vwap",
                # 修复: 日K实际列名为 turnover_rate (原映射 "turnover" 取不到数据)
                "Turnover": "turnover_rate",
            }
            src_col = col_map.get(field, field.lower())
            if src_col in df.columns:
                cols[code] = df[src_col].astype(float)
            elif field == "VWAP" and "amount" in df.columns and "volume" in df.columns:
                # VWAP自动计算: 成交额 / 成交量
                vol = df["volume"].astype(float)
                amt = df["amount"].astype(float)
                cols[code] = amt / vol.replace(0, np.nan)
        if cols:
            field_dfs[field] = pd.DataFrame(cols).reindex(dates)

    # 派生字段: 基于 Close / Amount 计算
    close_df = field_dfs.get("Close")
    if close_df is not None:
        # IdioRet: 截面去均值日收益率 (行向去均值)
        ret = close_df.pct_change()
        field_dfs["IdioRet"] = ret.sub(ret.mean(axis=1), axis=0)
        # TotalRet: 日收益率面板 (与清华原版语义一致: TotalRet 为日收益率,
        # IndexRet=TotalRet.mean(1), IdioRet=TotalRet-IndexRet;
        # 原实现 (1+ret).cumprod() 累计指数为语义错位, 已修正 2026-08-15)
        field_dfs["TotalRet"] = ret
    amount_df = field_dfs.get("Amount")
    if amount_df is not None:
        # Value: 用成交额作为规模/市值代理
        field_dfs["Value"] = amount_df

    # 缓存结果: 值同时持有面板强引用, 保证面板在缓存期内不被回收、id 不复用
    if key is not None:
        _FIELD_DFS_CACHE[key] = (field_dfs, panel)
        if len(_FIELD_DFS_CACHE) > _FIELD_DFS_CACHE_MAX:
            _FIELD_DFS_CACHE.popitem(last=False)
    return field_dfs


class _SafeDF(pd.DataFrame):
    """除零安全 DataFrame 子类: 重写 / 除法, 结果中出现 ±Inf(除零)时置为 NaN

    背景: 表达式引擎用 eval 执行公式, div 节点渲染为原生 '/' 运算符, 无法直接拦截;
    除零会产生 ±Inf, 后续归约(如 cs_Zscore 内部 df.std(axis=1))会触发 numpy
    "invalid value encountered in reduce" 警告, 且 Inf 会污染相关系数等统计量。
    通过在 evaluate_expression 中把字段面板包装为本子类, 使公式内任意位置的除法
    (含 ts_* 中间结果)均把 ±Inf 归一为 NaN —— 与 GPU 路径 t_div 的除零保护语义一致。
    其余行为完全继承 pandas.DataFrame, 不改动任何 ts_*/cs_* 算子原有逻辑。
    """

    @property
    def _constructor(self):
        # 保证 rolling/shift/sub 等算子结果仍为本子类, 除法保护可覆盖中间结果
        return _SafeDF

    @property
    def _constructor_sliced(self):
        return pd.Series

    def __truediv__(self, other):
        out = super().__truediv__(other)
        if hasattr(out, "replace"):
            return out.replace([np.inf, -np.inf], np.nan)
        return out

    def __rtruediv__(self, other):
        out = super().__rtruediv__(other)
        if hasattr(out, "replace"):
            return out.replace([np.inf, -np.inf], np.nan)
        return out


def evaluate_expression(expr: str, panel: Dict[str, pd.DataFrame],
                        financial_lag_days: Optional[int] = None) -> pd.DataFrame:
    """
    安全解析并计算因子表达式

    参数:
        expr:   因子表达式, 如 "-1*ts_Decay((ts_Decay(Close,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)"
        panel:  {stock_code: DataFrame}, 每只股票的日K (含 Open/High/Low/Close/Volume/Amount)
        financial_lag_days: 财报披露滞后天数 (传给 FN)。None=按报告期类型自动分级(评价/回测,
                避免未来函数); 0=不延迟(因子包实际使用: 表里有=当前已知道)。

    返回: DataFrame, index=日期, columns=股票代码, values=因子值
    """
    is_valid, msg = validate_expression(expr)
    if not is_valid:
        raise ValueError(f"表达式不合法: {msg}")

    # 构建字段 DataFrame (index=日期, columns=股票代码)
    field_dfs = _build_field_dfs(panel)

    if not field_dfs:
        raise ValueError("面板数据中无可用字段")

    # 除零保护: 把字段面板包装为 _SafeDF, 使公式内任意 '/' 除法在除零时置 NaN,
    # 避免 ±Inf 进入归约触发 numpy "invalid value encountered in reduce" 警告
    # (与 GPU 路径 t_div 语义一致; 不改动算子逻辑, 仅拦截除法结果)
    field_dfs = {f: (_SafeDF(d) if isinstance(d, pd.DataFrame) else d)
                 for f, d in field_dfs.items()}

    # 构建命名空间
    namespace = {**_SAFE_NAMES}
    # _SAFE_FUNCTIONS 是函数名集合, 从 globals 取出实际函数对象注入命名空间
    for fn_name in _SAFE_FUNCTIONS:
        if fn_name == "FN":
            # FN函数需要panel参数, 包装为自动传入panel的版本 (同时透传财务滞后口径)
            namespace[fn_name] = lambda field: FN(field, panel=panel, lag_days=financial_lag_days)
        else:
            namespace[fn_name] = globals()[fn_name]

    # 加入字段
    for field, df in field_dfs.items():
        namespace[field] = df

    # 注入财务字段名作为字符串 (使FN(roe)等表达式可执行)
    for fn_field in _FN_FIELDS:
        namespace[fn_field] = fn_field

    # 注入基类实例可调用函数 (rsi(14)/adx(14)/momentum(5) 等)
    for base_id in BASE_OPERATOR_MAP:
        callable_fn = _make_base_callable(base_id, field_dfs)
        if callable_fn is not None:
            namespace[base_id] = callable_fn

    # 执行表达式
    result = eval(expr, {"__builtins__": {}}, namespace)

    if not isinstance(result, (pd.DataFrame, pd.Series)):
        raise ValueError(f"表达式结果类型错误: {type(result)}, 需要 DataFrame 或 Series")

    return result


def calc_factor(factor_id: str, panel: Dict[str, pd.DataFrame],
                financial_lag_days: Optional[int] = None) -> pd.DataFrame:
    """统一因子计算入口 - 读取factor_library的formula并执行

    流程:
      1. 从数据库读取因子信息(formula)
      2. 直接通过表达式引擎计算(公式为基类+算子自包含形式, 无需依赖)
      3. 返回面板DataFrame (index=日期, columns=股票代码)

    参数:
        factor_id: 因子ID
        panel:     {stock_code: DataFrame}
        financial_lag_days: 财报披露滞后天数 (传给表达式引擎FN)。
                None=自动分级(评价/回测, 避免未来函数); 0=不延迟(因子包实际使用)。
    """
    from lib.factor_db import get_factor

    factor = get_factor(factor_id)
    if not factor:
        raise ValueError(f"因子 {factor_id} 不存在")

    formula = factor.get("formula", "")
    if not formula:
        raise ValueError(f"因子 {factor_id} 无formula, 无法计算")

    # 所有因子公式均为基类+算子自包含形式, 直接由表达式引擎求值
    result = evaluate_expression(formula, panel, financial_lag_days=financial_lag_days)

    # 财务因子: 原始财务值含极端值(如 PE=-287), 在源头上做逐截面去极值,
    # 与case预处理流程一致, 使展示的因子值/data_stats 与IC/分层评价口径统一
    if classify_factor_type(factor) == "financial":
        result = winsorize_panel_cross_section(result)

    return result


def score_stocks_by_package(package: Dict[str, Any],
                            panel: Dict[str, pd.DataFrame],
                            source_map: Optional[dict] = None,
                            top_n: int = 5) -> List[Dict[str, Any]]:
    """用因子包对给定股票面板做截面选股 (供晨会等其他页面复用因子包)

    因子包保存的是"最终使用参数"(全历史确定): 因子清单 + 合成方式 + 最终权重/方向 +
    ML模型/PCA对象路径。本函数取最新截面因子值, 预处理(去极值+Z-score)后按包内配置
    合成综合得分, 返回 Top N 标的。不再做 walk-forward 滚动。

    参数:
        package:    factor_package 完整配置
                    (含 factor_ids/method/weights/direction/ml_model_path/pca_model_path)
        panel:      {stock_code: DataFrame(含 open/high/low/close/volume/amount, index=日期)}
        source_map: {stock_code: 板块/概念名} 用于展示, 可选
        top_n:      返回前 N 名
    返回: [{code, source, alpha, raw_factors, zscore_factors}] 按 alpha 降序
    """
    factor_ids = list(package.get("factor_ids") or [])
    method = package.get("method") or "equal"
    weights = package.get("weights") or {}
    direction = package.get("direction") or {}
    ml_model_path = package.get("ml_model_path")
    pca_model_path = package.get("pca_model_path")

    if not factor_ids or not panel:
        return []

    # 加载落盘模型/PCA对象 (若方法对应)
    ml_model = None
    ml_feature_cols = None
    ml_method = None
    if method in ("ml_reg", "ml_cls") and ml_model_path:
        try:
            ml_model, ml_feature_cols, ml_method = _load_ml_model(ml_model_path)
        except Exception:
            ml_model = None

    pca_obj = None
    pca_loadings = None
    pca_k = None
    pca_feature_cols = None
    if method == "pca" and pca_model_path:
        try:
            pca_obj, pca_loadings, pca_k, pca_feature_cols = _load_pca_model(pca_model_path)
        except Exception:
            pca_obj = None

    need_cols = factor_ids
    if ml_model is not None and ml_feature_cols:
        need_cols = ml_feature_cols
    elif pca_obj is not None and pca_feature_cols:
        need_cols = pca_feature_cols

    # 1. 计算因子最新截面 (index=股票代码)
    #    与训练端(多因子B1)对齐: technical_ts 因子先做时序分位标准化(量纲统一)再取最新截面,
    #    否则价格水平类因子(均线/价格变换/OBV等)会被绝对量纲主导, 与评价端口径不一致;
    #    signal 因子走"信号方向得分独立轨"(_signal_score_panel, 与评价端 F2 同口径),
    #    不进连续截面, 避免把离散 0/±1 信号当连续因子 zscore。
    from lib.factor_db import get_factor
    _finfo = {}
    for fid in need_cols:
        try:
            _finfo[fid] = get_factor(fid) or {}
        except Exception:
            _finfo[fid] = {}
    _rebal = int(package.get("rebal_period") or 21)
    # 优先用包内保存的训练窗口(含自适应降窗), 与训练端口径严格一致;
    # 旧包未存该字段(ts_normalize_window=0/None)时回退按数据长度自适应解析。
    _ts_win_pkg = int(package.get("ts_normalize_window") or 0) or None
    continuous_ids, signal_ids = [], []
    for fid in need_cols:
        if classify_factor_type(_finfo[fid]) == "signal":
            signal_ids.append(fid)
        else:
            continuous_ids.append(fid)

    # 1a. 连续因子最新截面 (technical_ts 先时序分位标准化)
    #    财务因子按"实际使用口径"加载: 表里已有财报=当前已知道, 不叠加披露滞后
    #    (评价/回测才需要滞后避免未来函数; 这里只是取"当前已知"的最新值)。
    cross = {}
    for fid in continuous_ids:
        try:
            _f_lag = 0 if classify_factor_type(_finfo[fid]) == "financial" else None
            fv = calc_factor(fid, panel, financial_lag_days=_f_lag)  # DataFrame(index=日期, columns=股票代码)
        except Exception:
            continue
        if fv is None or fv.empty:
            continue
        if classify_factor_type(_finfo[fid]) == "technical_ts":
            if _ts_win_pkg:
                win = _ts_win_pkg
            else:
                win = resolve_ts_window(250, len(fv), _rebal)
            fv = ts_rank_normalize(fv, win)
        cross[fid] = fv.iloc[-1]

    # 1b. 信号因子 -> 每股综合方向得分 (多信号平均, 与评价端 build_signal_direction_score_panel 同口径)
    sig_score = None
    sig_panels = []
    for fid in signal_ids:
        try:
            fv = calc_factor(fid, panel)
        except Exception:
            continue
        if fv is None or fv.empty:
            continue
        _d = direction_to_int(_finfo[fid].get("direction"))
        sig_panels.append(_signal_score_panel(fv, _d).iloc[-1])
    if sig_panels:
        # 多信号严格等权平均 + 仅非空平均 (与 build_signal_direction_score_panel 修复同口径)
        sig_score = pd.concat(sig_panels, axis=1).mean(axis=1, skipna=True)
        sig_score = sig_score.dropna()

    # 2. 连续因子截面预处理: 与训练侧对齐 (复用 _preprocess_cross_section, 含去极值/中位数填充/中性化/Z-score)
    if not cross:
        # 无连续因子 (仅信号模式): 综合方向得分即选股信号 (评价端 signal_only 口径)
        if sig_score is None or len(sig_score) < 5:
            return []
        alpha = sig_score
        cross_df = pd.DataFrame(index=alpha.index)
        pre = pd.DataFrame(index=alpha.index)
    else:
        cross_df = pd.DataFrame(cross)
        neutralize = package.get("neutralize") or "none"
        sector_map = concept_map = industry_map = marketcap_map = None
        # 解析 neutralize: "marketcap_industry"=市值+行业, "marketcap"=仅市值, "industry"=仅行业, "none"=无
        mc_on = neutralize.startswith("marketcap")
        group = ""
        if neutralize.startswith("marketcap_"):
            group = neutralize[len("marketcap_"):]
        elif not mc_on:
            group = neutralize
        if mc_on:
            from lib.stock_classify import load_marketcap_map
            marketcap_map = load_marketcap_map(list(cross_df.index))
        if group == "sector":
            from lib.stock_classify import load_sector_map
            sector_map = load_sector_map(list(cross_df.index))
        elif group == "concept":
            from lib.stock_classify import load_concept_map
            concept_map = load_concept_map(list(cross_df.index))
        elif group == "industry":
            from lib.stock_classify import load_industry_map
            industry_map = load_industry_map(list(cross_df.index))
        pre = _preprocess_cross_section(
            cross_df, sector_map, concept_map, industry_map, marketcap_map,
            winsorize_n=3.0, fill_na=True,
        )

    # 3. 合成综合得分 (连续因子部分; 仅信号模式 alpha 已在第2步取信号方向得分)
    if cross:
        if ml_model is not None and ml_feature_cols:
            # ML: 用落盘模型直接预测, 无需重训 (特征仅含连续因子, 与训练端一致)
            X = pre.reindex(columns=ml_feature_cols).fillna(0.0)
            if ml_method == "ml_cls":
                alpha = pd.Series(ml_model.predict_proba(X)[:, 1], index=X.index)
            else:
                alpha = pd.Series(ml_model.predict(X), index=X.index)
        elif pca_obj is not None and pca_feature_cols:
            # PCA: 用落盘 PCA 对象投影到主成分, 按解释方差加权求和
            X = pre.reindex(columns=pca_feature_cols).fillna(0.0)
            T = pca_obj.transform(X)[:, :pca_k]
            alpha = pd.Series(np.dot(T, pca_loadings), index=X.index)
        elif method == "rank_score":
            # 排名打分: 与评价流程 rank_score_synthesis 一致 (方向在函数内部按 direction 处理)
            valid = pre.dropna(how="any")
            alpha = rank_score_synthesis(valid, direction) if len(valid) >= 5 else pd.Series(dtype=float)
        else:
            # 线性合成:
            # - 有最终权重 (ic_weighted/lasso/sharpe/markowitz) 时, 权重是在"未按 direction
            #   翻转的因子"上拟合/计算的, 符号已含方向, 直接线性组合, 不再二次翻号
            #   (避免负向因子双重取反);
            # - 无权重 (等权) 时, 按 direction 翻转后等权, 与评价流程 equal 一致。
            if weights:
                w = pd.Series(weights).reindex(pre.columns).fillna(0.0)
                if w.abs().sum() > 0:
                    alpha = (pre * w).sum(axis=1)
                else:
                    alpha = pre.mean(axis=1)
            else:
                comp = pre.copy()
                for fid in comp.columns:
                    if direction.get(fid, 1) < 0:
                        comp[fid] = -comp[fid]
                alpha = comp.mean(axis=1)

    # 3b. 混合模式: 在连续合成综合因子上叠加信号方向得分 (与评价端 F2 一致:
    #     各自截面标准化后按 0.5 倾斜系数叠加, 使信号因子参与选股又不主导)
    if (cross and sig_score is not None and len(sig_score) >= 5
            and alpha is not None and not alpha.empty):
        sig_a = sig_score.reindex(alpha.index)
        alpha_std = (alpha - alpha.mean()) / (alpha.std() + 1e-9)
        sig_std = (sig_a - sig_a.mean()) / (sig_a.std() + 1e-9)
        alpha = alpha_std + 0.5 * sig_std.fillna(0.0)

    if alpha is None or alpha.empty:
        return []

    # 4. 排序取 Top N
    alpha = alpha.dropna().sort_values(ascending=False)
    picked = []
    has_cross = len(cross_df.columns) > 0
    has_pre = len(pre.columns) > 0
    for code in alpha.head(top_n).index:
        picked.append({
            "code": code,
            "source": (source_map or {}).get(code, "未分类"),
            "alpha": round(float(alpha[code]), 3),
            "raw_factors": {k: round(float(v), 3) for k, v in cross_df.loc[code].items() if pd.notna(v)} if has_cross else {},
            "zscore_factors": {k: round(float(v), 3) for k, v in pre.loc[code].items() if pd.notna(v)} if has_pre else {},
        })
    return picked


# ============================================================
# 八、基础因子计算 (来源: CASE-C/factor_lib.py + 主系统 feature_engine)
# ============================================================

def calc_basic_factors(df: pd.DataFrame) -> Dict[str, float]:
    """
    计算单只股票的基础因子值 (截面快照)
    来源: CASE-C/factor_lib.py

    df: 单只股票日K (含 close/volume/amount), 按时间升序
    返回: {factor_name: value}
    """
    if df is None or len(df) < 130:
        return {}

    close = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)
    amount = df["amount"].astype(float) if "amount" in df.columns else pd.Series(dtype=float)
    returns = close.pct_change().dropna()

    if len(returns) < 100:
        return {}

    factors = {}

    # 动量类
    def _safe_pct(prices: pd.Series, periods: int) -> float:
        if len(prices) <= periods:
            return np.nan
        p_now = prices.iloc[-1]
        p_then = prices.iloc[-1 - periods]
        if p_then <= 0:
            return np.nan
        return p_now / p_then - 1.0

    factors["MOM_1M"] = _safe_pct(close, 21)
    factors["MOM_3M"] = _safe_pct(close, 63)
    factors["MOM_6M"] = _safe_pct(close, 126)

    # 反转类
    factors["REV_5D"] = -_safe_pct(close, 5)

    # 波动率类 (取负, 低波好)
    if len(returns) >= 20:
        factors["VOL_20"] = -returns.iloc[-20:].std() * math.sqrt(252)
    if len(returns) >= 60:
        factors["VOL_60"] = -returns.iloc[-60:].std() * math.sqrt(252)

    # 流动性类 (取负)
    if len(amount) >= 20 and amount.iloc[-20:].mean() > 0:
        factors["LIQ_20"] = -math.log(amount.iloc[-20:].mean())
    if len(volume) >= 20 and volume.iloc[-20:].mean() > 0:
        total_share = volume.iloc[-20:].mean()  # 近似
        if total_share > 0:
            # 量比系列: 与因子库 vol_ratio_20/vol_ratio_20_low 同口径 (旧 TURN_20/VOL_RATIO_20 键已废弃)
            vol_ratio_val = volume.iloc[-1] / total_share
            factors["vol_ratio_20"] = vol_ratio_val
            factors["vol_ratio_20_low"] = -vol_ratio_val

    # 换手率类 (真实换手率字段, 可选列; 与 factor_library 的 turnover_rate/turnover_rate_20 同口径)
    if "turnover_rate" in df.columns:
        tr_series = pd.to_numeric(df["turnover_rate"], errors="coerce")
        if tr_series.notna().sum() > 0:
            tr_last = tr_series.iloc[-1]
            if pd.notna(tr_last) and tr_last > 0:
                factors["turnover_rate"] = float(tr_last)
            if tr_series.notna().sum() >= 20:
                tr_ma20 = tr_series.tail(20).mean()
                if pd.notna(tr_ma20) and tr_ma20 > 0:
                    factors["turnover_rate_20"] = -float(tr_ma20)

    # 技术指标类
    if len(close) >= 14:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        factors["RSI_14"] = rsi.iloc[-1] - 50 if pd.notna(rsi.iloc[-1]) else np.nan

    if len(close) >= 20:
        ma20 = close.rolling(20).mean()
        if ma20.iloc[-1] and ma20.iloc[-1] > 0:
            factors["BIAS_20"] = -(close.iloc[-1] / ma20.iloc[-1] - 1)

    # ATR
    if len(df) >= 14 and "high" in df.columns and "low" in df.columns:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14, min_periods=1).mean()
        if close.iloc[-1] > 0 and atr.iloc[-1] > 0:
            factors["ATR_NORM_14"] = -atr.iloc[-1] / close.iloc[-1]

    # MACD
    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        factors["MACD_DIF"] = dif.iloc[-1] / close.iloc[-1] if close.iloc[-1] > 0 else np.nan

    return {k: float(v) for k, v in factors.items() if pd.notna(v)}
