# -*- coding: utf-8 -*-
# GPU 整树张量求值器: torch 算子后端 (数值对齐 factor_engine 的 pandas 语义)
"""
设计: 复刻 QuantGplearn 的 GPU 计算架构(整树在 [T,N] 张量上执行, 一次面板传输),
但每个算子的数值语义与 lib/factor_engine.py 的 pandas DSL 对齐(而非照搬
QuantGplearn torch_functions 的 nanmean/unfold-pad 语义)。

对齐要点 (与 factor_engine 逐算子核对):
  - rolling 窗口: 预热区(t<window-1)用"前缀部分窗口"(对齐 pandas min_periods),
    完整窗口区用 unfold 固定窗口; 窗口内 NaN 跳过(对齐 pandas rolling skipna=True);
  - 非NaN数 < min_periods 时结果为 NaN;
  - cs_* 按行(截面)计算, NaN 跳过;
  - cs_Rank 用平均秩百分比(对齐 pandas rank(axis=1, pct=True, method='average'));
  - cs_TransNorm 用正态分位变换(erf 反函数, 对齐 scipy norm.ppf)。

依赖: torch (Agu-2 环境已装 CUDA 版 2.6.0+cu124)。
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

import numpy as np
import torch

EPS = 1e-12

_TORCH = None


def _t():
    global _TORCH
    if _TORCH is None:
        import torch as _m
        _TORCH = _m
    return _TORCH


# ============================================================
# 通用滚动窗口辅助 (对齐 pandas rolling)
# ============================================================

def _pad_nan_like(x: torch.Tensor, pad: int) -> torch.Tensor:
    """前向补 pad 行 NaN (与 x 同 N 列)"""
    if pad <= 0:
        return x
    front = torch.full((pad, x.shape[1]), float("nan"), dtype=x.dtype, device=x.device)
    return torch.cat([front, x], dim=0)


def _rolling_map(x: torch.Tensor, window: int, min_periods: int,
                 fn_full: Callable[[torch.Tensor], torch.Tensor],
                 fn_prefix: Optional[Callable[[torch.Tensor], torch.Tensor]] = None,
                 prefix_kind: Optional[str] = None) -> torch.Tensor:
    """通用滚动窗口算子 (对齐 pandas rolling 语义)

    参数:
        x:          [T, N] 输入张量
        window:     窗口大小
        min_periods: 最少非NaN数, 不足则结果 NaN
        fn_full:    对完整窗口 [M, N, window] 沿最后维聚合 (跳过NaN)
        fn_prefix:  对预热区前缀窗口聚合; None 时用 fn_full 的掩码版(取到 window 为止)
        prefix_kind: 阶段6.3 加速: 预热区前缀聚合的向量化类型
                     ("sum"/"mean"/"max"/"min"), 用 cumsum/cummax/cummin 一次性计算,
                     避免逐时刻 Python 循环 (结果与原逐时刻循环逐位一致);
                     None 时走通用 fn_prefix/逐时刻循环路径。
    返回: [T, N]
    """
    t = _t()
    T, N = x.shape
    if T == 0:
        return x
    window = max(1, min(int(window), T))
    min_periods = max(1, min(int(min_periods), window))
    out = torch.full((T, N), float("nan"), dtype=x.dtype, device=x.device)

    # ---- 完整窗口区 (t >= window-1): 一次性 unfold ----
    if T >= window:
        win = x.unfold(0, window, 1)                # [T-window+1, N, window]
        vals = fn_full(win)                          # [T-window+1, N]
        # 非NaN计数不足 min_periods -> NaN
        cnt = (~torch.isnan(win)).sum(dim=2)
        vals = torch.where(cnt >= min_periods, vals, torch.full_like(vals, float("nan")))
        out[window - 1:, :] = vals

    # ---- 预热区 (t < window-1): 前缀部分窗口 (对齐 pandas min_periods 前缀聚合) ----
    kmax = min(window - 1, T)
    if kmax > 0:
        if prefix_kind == "sum":
            # cumsum: NaN 视作 0 (对齐 rolling.sum skipna)
            cnt = (~torch.isnan(x[:kmax])).cumsum(dim=0)
            acc = torch.cumsum(torch.nan_to_num(x[:kmax], nan=0.0), dim=0)
            out[:kmax] = torch.where(cnt >= min_periods, acc,
                                     torch.full_like(acc, float("nan")))
        elif prefix_kind == "mean":
            # cumsum/cumcount: NaN 视作 0 (对齐 rolling.mean skipna)
            cnt = (~torch.isnan(x[:kmax])).cumsum(dim=0)
            acc = torch.cumsum(torch.nan_to_num(x[:kmax], nan=0.0), dim=0)
            m = acc / cnt.clamp_min(1)
            out[:kmax] = torch.where(cnt >= min_periods, m,
                                     torch.full_like(m, float("nan")))
        elif prefix_kind == "max":
            # cummax: NaN 视作 -inf (对齐 rolling.max skipna, NaN 永不成为最大值)
            cnt = (~torch.isnan(x[:kmax])).cumsum(dim=0)
            cm = torch.cummax(torch.nan_to_num(x[:kmax], nan=float("-inf")), dim=0).values
            out[:kmax] = torch.where(cnt >= min_periods, cm,
                                     torch.full_like(cm, float("nan")))
        elif prefix_kind == "min":
            # cummin: NaN 视作 +inf (对齐 rolling.min skipna, NaN 永不成为最小值)
            cnt = (~torch.isnan(x[:kmax])).cumsum(dim=0)
            cm = torch.cummin(torch.nan_to_num(x[:kmax], nan=float("inf")), dim=0).values
            out[:kmax] = torch.where(cnt >= min_periods, cm,
                                     torch.full_like(cm, float("nan")))
        else:
            # 通用前缀聚合 (未向量化的聚合器用原逐时刻循环)
            for t_idx in range(kmax):
                seg = x[:t_idx + 1, :]               # [t_idx+1, N]
                cnt = (~torch.isnan(seg)).sum(dim=0)
                if int((cnt >= min_periods).sum()) == 0:
                    continue
                if fn_prefix is not None:
                    v = fn_prefix(seg)
                else:
                    v = fn_full(seg.unsqueeze(0).transpose(1, 2)).squeeze(0)  # 复用 fn_full 的列向量语义
                    v = v.squeeze(-1)
                v = v.squeeze(0) if v.ndim > 1 else v
                out[t_idx, :] = torch.where(cnt >= min_periods, v, torch.full_like(v, float("nan")))
    return out


# ============================================================
# 基础算术 (元素级, 与 factor_engine 语义一致)
# ============================================================

def t_add(a, b):
    return a + b


def t_sub(a, b):
    return a - b


def t_mul(a, b):
    return a * b


def t_div(a, b):
    """除零/除NaN安全: 分母为0时置 NaN (对齐 pandas 除零行为)"""
    out = a / b
    return torch.where(torch.isinf(out) | torch.isnan(out), torch.full_like(out, float("nan")), out)


def t_abs(x):
    return torch.abs(x)


def t_gate(c, a, b):
    """三目门控: cond>0 取 a, 否则取 b (对齐 factor_engine.gate / RL op_gate)"""
    return torch.where(c > 0, a, b)


def t_if_gt(c, a, b):
    """三目条件选择: cond>0 取 a, 否则取 b (与 gate 同语义, 保留 AlphaMaster if_gt 命名)"""
    return torch.where(c > 0, a, b)


# ============================================================
# 时序算子 (带窗, 对齐 factor_engine pandas rolling 语义)
# ============================================================

def t_ts_Delay(x, n):
    """滞后 n 期 (df.shift(n)): 前 n 行 NaN"""
    n = int(n)
    out = torch.full_like(x, float("nan"))
    if n < x.shape[0]:
        out[n:, :] = x[:-n, :]
    return out


def _ts_mean_full(win):
    """win: [M, N, window] -> 沿最后维均值 (跳过NaN)"""
    t = _t()
    mask = ~torch.isnan(win)
    safe = torch.where(mask, win, torch.zeros_like(win))
    cnt = mask.sum(dim=2).clamp_min(1)
    return safe.sum(dim=2) / cnt


def t_ts_Mean(x, n):
    """n 期移动平均 (df.rolling(n, min_periods=1).mean(), 跳 NaN)"""
    return _rolling_map(x, n, 1, _ts_mean_full, prefix_kind="mean")


def _ts_sum_full(win):
    mask = ~torch.isnan(win)
    return torch.where(mask, win, torch.zeros_like(win)).sum(dim=2)


def t_ts_Sum(x, n):
    """n 期滚动求和 (df.rolling(n, min_periods=1).sum())"""
    return _rolling_map(x, n, 1, _ts_sum_full, prefix_kind="sum")


def _ts_max_full(win):
    mask = ~torch.isnan(win)
    return torch.where(mask, win, torch.full_like(win, -float("inf"))).amax(dim=2)


def _ts_min_full(win):
    mask = ~torch.isnan(win)
    return torch.where(mask, win, torch.full_like(win, float("inf"))).amin(dim=2)


def t_ts_Max(x, n):
    return _rolling_map(x, n, 1, _ts_max_full, prefix_kind="max")


def t_ts_Min(x, n):
    return _rolling_map(x, n, 1, _ts_min_full, prefix_kind="min")


def _ts_std_full(win, ddof: int = 1):
    """沿窗口最后维标准差 (ddof=1, 对齐 pandas rolling.std / QuantGplearn unbiased)"""
    mask = ~torch.isnan(win)
    cnt = mask.sum(dim=2).clamp_min(1)
    mean = torch.where(mask, win, torch.zeros_like(win)).sum(dim=2) / cnt
    diff = torch.where(mask, win - mean.unsqueeze(2), torch.zeros_like(win))
    denom = (cnt - ddof).clamp_min(1)
    var = (diff ** 2).sum(dim=2) / denom
    return torch.sqrt(var.clamp_min(0.0))


def t_ts_Stdev(x, n):
    """n 期滚动标准差 (df.rolling(n, min_periods=2).std(), ddof=1)"""
    return _rolling_map(x, n, 2, _ts_std_full)


def _ts_median_full(win):
    """win: [M, N, window] -> 沿最后维中位数 (非NaN值, 偶数取平均; 对齐 pandas)

    全 torch 实现 (阶段 P2#5, 去掉 numpy 往返):
      torch.sort 将 NaN 排到末尾, 前 cnt 个为有效值; 中位索引取
      (cnt-1)//2 与 cnt//2, 奇数窗口两者相同(下中位), 偶数窗口取两者平均
      (对齐 pandas rolling.median); cnt==0 (全 NaN) 置 NaN。
    """
    flat = win.reshape(-1, win.shape[2])
    cnt = (~torch.isnan(flat)).sum(dim=1)                       # [M] 每行有效值个数
    flat_sorted = torch.sort(flat, dim=1, stable=True).values   # [M, window] NaN 排末尾
    idx_lo = ((cnt - 1).clamp(min=0)) // 2                      # [M] 下中位索引
    idx_hi = (cnt.clamp(min=1)) // 2                            # [M] 上中位索引
    med = 0.5 * (flat_sorted.gather(1, idx_lo.unsqueeze(1)).squeeze(1)
                 + flat_sorted.gather(1, idx_hi.unsqueeze(1)).squeeze(1))
    med = torch.where(cnt == 0, torch.full_like(med, float("nan")), med)
    return med.reshape(win.shape[0], win.shape[1])


def t_ts_Median(x, n):
    """n 期滚动中位数 (df.rolling(n, min_periods=1).median())"""
    return _rolling_map(x, n, 1, _ts_median_full)


def t_ts_Delta(x, n):
    """n 期差值 (df - df.shift(n))"""
    return x - t_ts_Delay(x, n)


def t_ts_MOM(x, n):
    """n 期价格动量 (talib.MOM = price - price[n]前, 即 Delta 语义; 对齐引擎 ts_MOM)"""
    return t_ts_Delta(x, n)


def t_ts_PctChange(x, n):
    """n 期百分比变化率 (df.pct_change(n))"""
    prev = t_ts_Delay(x, n)
    return (x - prev) / prev


def t_ts_ROC(x, n):
    """n 期变化率 * 100 (df.pct_change(n) * 100)"""
    return t_ts_PctChange(x, n) * 100.0


def t_ts_Shift(x, n):
    return t_ts_Delay(x, n)


def t_ts_CumReturn(x, n):
    """n 期累计收益 = 当前 / 前n期 - 1 (df / df.shift(n) - 1)"""
    return x / t_ts_Delay(x, n) - 1.0


def t_ts_Bias(x, n):
    """n 期乖离率 = (x - MA) / MA (对齐 df.rolling mean, 分母0置NaN)"""
    ma = t_ts_Mean(x, n)
    return (x - ma) / torch.where(ma.abs() > EPS, ma, torch.full_like(ma, float("nan")))


def t_ts_VolRatio(x, n):
    """n 期量比 = 当前 / n期均值 (分母0置NaN)"""
    ma = t_ts_Mean(x, n)
    return x / torch.where(ma.abs() > EPS, ma, torch.full_like(ma, float("nan")))


def t_ts_HistVol(x, n):
    """n 期历史波动率 = std(日收益, n) * sqrt(252)"""
    ret = t_ts_PctChange(x, 1)
    return t_ts_Stdev(ret, n) * float(np.sqrt(252.0))


def t_ts_Log(x):
    """自然对数 (df.replace(0, nan) 后 np.log)"""
    safe = torch.where(x.abs() > EPS, x, torch.full_like(x, float("nan")))
    return torch.log(torch.abs(safe))


def t_ts_Identity(x):
    return x


def t_ts_Count(x, n):
    """n 期滚动非空计数 (df.rolling(n, min_periods=1).count())"""
    def _cnt_full(win):
        return (~torch.isnan(win)).sum(dim=2).to(x.dtype)

    def _cnt_prefix(seg):
        return (~torch.isnan(seg)).sum(dim=0).to(x.dtype)
    return _rolling_map(x, n, 1, _cnt_full, _cnt_prefix)


def t_ts_Rank(x, n):
    """n 期滚动排名 pct (df.rolling(n, min_periods=2).rank(pct=True), 平均秩)"""
    def _rank_full(win):
        return _rolling_rank_pct(win)

    def _rank_prefix(seg):
        return _rolling_rank_pct(seg.unsqueeze(0).transpose(1, 2))
    return _rolling_map(x, n, 2, _rank_full, _rank_prefix)


def _rolling_rank_pct(win):
    """win: [M, N, window] -> 每个窗口末位值的平均秩百分比 (对齐 pandas rolling.rank pct)"""
    t = _t()
    last = win[..., -1:]                      # [M, N, 1] 当前值
    mask = ~torch.isnan(win)
    last_valid = ~torch.isnan(last)
    cnt = mask.sum(dim=2).clamp_min(1).to(win.dtype)
    less = ((win < last) & mask & last_valid).sum(dim=2).to(win.dtype)
    equal = ((win == last) & mask & last_valid).sum(dim=2).to(win.dtype)
    # pandas rank(method='average'): 平均秩 = less + (equal+1)/2
    avg_rank = less + (equal + 1.0) / 2.0
    out = avg_rank / cnt
    return torch.where(last_valid.squeeze(2), out, torch.full_like(out, float("nan")))


def t_ts_VAR(x, n):
    """n 期方差 = std^2"""
    return t_ts_Stdev(x, n) ** 2


def _ts_skew_full(win):
    t = _t()
    mask = ~torch.isnan(win)
    cnt = mask.sum(dim=2).clamp_min(1)
    mean = torch.where(mask, win, torch.zeros_like(win)).sum(dim=2) / cnt
    diff = torch.where(mask, win - mean.unsqueeze(2), torch.zeros_like(win))
    m2 = (diff ** 2).sum(dim=2) / cnt
    m3 = (diff ** 3).sum(dim=2) / cnt
    out = m3 / (m2.clamp_min(EPS) ** 1.5)
    return torch.where(m2 > EPS, out, torch.full_like(out, float("nan")))


def t_ts_Skewness(x, n):
    """n 期滚动偏度 (df.rolling(n, min_periods=3).skew()) — 近似(未做样本修正)"""
    return _rolling_map(x, n, 3, _ts_skew_full)


def _ts_kurt_full(win):
    t = _t()
    mask = ~torch.isnan(win)
    cnt = mask.sum(dim=2).clamp_min(1)
    mean = torch.where(mask, win, torch.zeros_like(win)).sum(dim=2) / cnt
    diff = torch.where(mask, win - mean.unsqueeze(2), torch.zeros_like(win))
    m2 = (diff ** 2).sum(dim=2) / cnt
    m4 = (diff ** 4).sum(dim=2) / cnt
    out = m4 / (m2.clamp_min(EPS) ** 2.0) - 3.0
    return torch.where(m2 > EPS, out, torch.full_like(out, float("nan")))


def t_ts_Kurtosis(x, n):
    """n 期滚动峰度 (df.rolling(n, min_periods=4).kurt()) — 近似(未做样本修正)"""
    return _rolling_map(x, n, 4, _ts_kurt_full)


def t_ts_Decay(x, n):
    """n 期线性衰减加权均值 (df.rolling, 权重 = arange(n,0,-1)/n, 前缀预热)"""
    n = int(n)
    weights = np.arange(n, 0, -1, dtype=np.float64) / n
    return _rolling_weighted_mean(x, n, weights)


def t_ts_DecayExp(x, n):
    """n 期非线性衰减均值 (权重 = |norm.ppf 分位| 归一化, 对齐 factor_engine ts_DecayExp)"""
    n = int(n)
    from scipy.stats import norm
    raw_w = np.array([norm.ppf((n - j) / n) if 0 < (n - j) / n < 1 else 0.0
                      for j in range(n)], dtype=np.float64)
    weights = np.abs(raw_w)
    if weights.sum() == 0:
        return t_ts_Mean(x, n)
    weights = weights / weights.sum()
    return _rolling_weighted_mean(x, n, weights)


def _rolling_weighted_mean(x: torch.Tensor, n: int, weights: np.ndarray) -> torch.Tensor:
    """滚动前缀权重加权均值 (对齐 factor_engine._rolling_decay_weights_mean)

    语义: 每个时点 t 的窗口为最近 min(t+1, n) 个观测, 权重取 weights 前缀并按前缀和归一;
    窗口内存在 NaN 时结果记 NaN (与 factor_engine np.dot 的 NaN 传播一致)。
    """
    t = _t()
    T, N = x.shape
    n = min(n, T)
    if n <= 0:
        return torch.full_like(x, float("nan"))
    w = torch.tensor(weights[:n], dtype=x.dtype, device=x.device)
    prefix_sum = torch.cumsum(w, dim=0)
    out = torch.full_like(x, float("nan"))

    # 预热区 (t < n-1): 前缀加权累计 (逐列 NaN 传播, 对齐引擎 _rolling_decay_weights_mean)
    for t_idx in range(min(n - 1, T)):
        seg = x[:t_idx + 1, :]                     # [t_idx+1, N]
        wseg = w[:t_idx + 1]
        # 每列窗口内是否含 NaN -> 该列结果 NaN (对齐 np.dot 传播, 不跨列污染)
        has_nan_col = torch.isnan(seg).any(dim=0)  # [N]
        num = (seg * wseg.unsqueeze(1)).sum(dim=0) / prefix_sum[t_idx]
        out[t_idx, :] = torch.where(has_nan_col, torch.full_like(num, float("nan")), num)

    # 完整窗口区 (t >= n-1): 加权和 (与 factor_engine 卷积同向: 最旧乘 weights[0])
    if T > n - 1:
        win = x.unfold(0, n, 1)                    # [T-n+1, N, n], win[...,0]=最旧
        denom = prefix_sum[-1]
        vals = (win * w.unsqueeze(0).unsqueeze(0)).sum(dim=2) / denom
        # 窗口内任一 NaN -> NaN (对齐 np.dot 传播)
        has_nan = torch.isnan(win).any(dim=2)
        vals = torch.where(has_nan, torch.full_like(vals, float("nan")), vals)
        out[n - 1:, :] = vals
    return out


def t_ts_LINEARREG(x, n):
    """n 期线性回归拟合值 (对齐 factor_engine ts_LINEARREG talib) — 最小二乘"""
    return _ts_linreg(x, n)[0]


def t_ts_LINEARREG_SLOPE(x, n):
    return _ts_linreg(x, n)[1]


def t_ts_LINEARREG_INTERCEPT(x, n):
    return _ts_linreg(x, n)[2]


def t_ts_LINEARREG_ANGLE(x, n):
    slope = _ts_linreg(x, n)[1]
    return torch.atan(slope)


def _ts_linreg(x: torch.Tensor, n: int):
    """对每个滚动窗口做 时间索引 -> 值 的 OLS, 返回 (yhat, slope, intercept)

    对齐 factor_engine ts_LINEARREG 系列: 回归轴 x = 1..n (时间顺序), NaN 跳过。
    """
    t = _t()
    T, N = x.shape
    n = max(2, min(int(n), T))
    idx = torch.arange(1, n + 1, dtype=x.dtype, device=x.device)   # [n]
    xmean = idx.mean()
    xc = idx - xmean
    xvar = (xc ** 2).sum()

    def _fit_full(win):
        # win: [M, N, n]
        mask = ~torch.isnan(win)
        cnt = mask.sum(dim=2).clamp_min(1)
        ymean = torch.where(mask, win, torch.zeros_like(win)).sum(dim=2) / cnt
        yc = torch.where(mask, win - ymean.unsqueeze(2), torch.zeros_like(win))
        xc_b = xc.unsqueeze(0).unsqueeze(0)
        slope = (yc * xc_b).sum(dim=2) / xvar
        intercept = ymean - slope * xmean
        yhat = slope.unsqueeze(2) * idx.unsqueeze(0).unsqueeze(0) + intercept.unsqueeze(2)
        yhat = torch.where(mask, yhat, torch.full_like(yhat, float("nan")))
        return yhat, slope, intercept

    # 用 _rolling_map 但需要同时返回多个量; 直接手动循环完整窗口区
    yhat_out = torch.full_like(x, float("nan"))
    slope_out = torch.full_like(x, float("nan"))
    inter_out = torch.full_like(x, float("nan"))
    if T >= n:
        win = x.unfold(0, n, 1)
        mask = ~torch.isnan(win)
        cnt = mask.sum(dim=2).clamp_min(1)
        ymean = torch.where(mask, win, torch.zeros_like(win)).sum(dim=2) / cnt
        yc = torch.where(mask, win - ymean.unsqueeze(2), torch.zeros_like(win))
        xc_b = xc.unsqueeze(0).unsqueeze(0)
        slope = (yc * xc_b).sum(dim=2) / xvar
        intercept = ymean - slope * xmean
        # 需 cnt>=2 才有效
        valid = cnt >= 2
        slope = torch.where(valid, slope, torch.full_like(slope, float("nan")))
        intercept = torch.where(valid, intercept, torch.full_like(intercept, float("nan")))
        yhat = slope.unsqueeze(2) * idx.unsqueeze(0).unsqueeze(0) + intercept.unsqueeze(2)
        # 取末位拟合值
        yhat_out[n - 1:, :] = torch.where(mask[..., -1], yhat[..., -1], torch.full_like(yhat[..., -1], float("nan")))
        slope_out[n - 1:, :] = slope
        inter_out[n - 1:, :] = intercept
    return yhat_out, slope_out, inter_out


def t_ts_LINEARREG_R2(x, n):
    """n 期线性回归 R2 (对齐 factor_engine ts_LINEARREG_R2: 对时间趋势1..n回归的决定系数)"""
    t = _t()
    T, N = x.shape
    n = max(2, min(int(n), T))
    idx = torch.arange(1, n + 1, dtype=x.dtype, device=x.device)
    out = torch.full_like(x, float("nan"))
    if T >= n:
        win = x.unfold(0, n, 1)                    # [T-n+1, N, n]
        mask = ~torch.isnan(win)
        cnt = mask.sum(dim=2).clamp_min(1)
        ymean = torch.where(mask, win, torch.zeros_like(win)).sum(dim=2) / cnt
        yc = torch.where(mask, win - ymean.unsqueeze(2), torch.zeros_like(win))
        xc = idx - idx.mean()
        xvar = (xc ** 2).sum()
        slope = (yc * xc.unsqueeze(0).unsqueeze(0)).sum(dim=2) / xvar
        intercept = ymean - slope * idx.mean()
        yhat = slope.unsqueeze(2) * idx.unsqueeze(0).unsqueeze(0) + intercept.unsqueeze(2)
        yhat = torch.where(mask, yhat, torch.zeros_like(yhat))
        ss_res = ((torch.where(mask, win, torch.zeros_like(win)) - yhat) ** 2).sum(dim=2)
        ss_tot = (yc ** 2).sum(dim=2)
        r2 = 1.0 - ss_res / torch.where(ss_tot > EPS, ss_tot, torch.full_like(ss_tot, float("nan")))
        valid = (cnt >= 2) & (ss_tot > EPS)
        out[n - 1:, :] = torch.where(valid, r2, torch.full_like(r2, float("nan")))
    return out


# ============================================================
# 截面算子 (按行/截面, 对齐 factor_engine cs_*)
# ============================================================

def _cs_nanmean(x: torch.Tensor, dim: int = 1) -> torch.Tensor:
    mask = ~torch.isnan(x)
    safe = torch.where(mask, x, torch.zeros_like(x))
    cnt = mask.sum(dim=dim, keepdim=True)
    mean = safe.sum(dim=dim, keepdim=True) / cnt.clamp_min(1)
    # 全 NaN 行 -> NaN (对齐 pandas mean(axis=1))
    return torch.where(cnt >= 1, mean, torch.full_like(mean, float("nan")))


def _cs_nanstd(x: torch.Tensor, dim: int = 1, ddof: int = 1) -> torch.Tensor:
    mean = _cs_nanmean(x, dim)
    diff = torch.where(~torch.isnan(x), x - mean, torch.zeros_like(x))
    cnt = (~torch.isnan(x)).sum(dim=dim, keepdim=True).clamp_min(1)
    denom = (cnt - ddof).clamp_min(1)
    return torch.sqrt((diff ** 2).sum(dim=dim, keepdim=True) / denom)


def t_cs_Demean(x):
    """截面去均值 (df.sub(df.mean(axis=1)))"""
    return x - _cs_nanmean(x, dim=1)


def t_cs_Zscore(x):
    """截面 Z-score (df.sub(mean).div(std), ddof=1)"""
    mean = _cs_nanmean(x, dim=1)
    std = _cs_nanstd(x, dim=1, ddof=1)
    out = (x - mean) / torch.where(std.abs() > EPS, std, torch.full_like(std, float("nan")))
    return torch.where(~torch.isnan(x), out, torch.full_like(out, float("nan")))


def t_cs_Rank(x):
    """截面排名 pct (df.rank(axis=1, pct=True), 平均秩)"""
    return _cs_rank_pct(x)


def _cs_rank_pct(x: torch.Tensor) -> torch.Tensor:
    """逐行(截面)平均秩百分比 (对齐 pandas rank(axis=1, pct=True, method='average'))

    实现:
      1) 升序稳定排序, 得排序后值 xs 与映射 order(排序位置->原始列);
      2) 在排序位置上对并列(精确相等)值做平均秩;
      3) 用 rank_ord(原始列->排序位置) 逆映射回原始列, 除以非NaN计数得 pct。
    """
    t = _t()
    T, N = x.shape
    mask = ~torch.isnan(x)
    cnt = mask.sum(dim=1, keepdim=True).clamp_min(1).to(x.dtype)
    # 升序排序: NaN 填 inf 排末尾 (不影响非NaN的相对顺序)
    x_fill = torch.where(mask, x, torch.full_like(x, float("inf")))
    order = torch.argsort(x_fill, dim=1, stable=True)     # [T, N] 排序位置->原始列
    xs = torch.gather(x_fill, 1, order)                    # 排序后值
    eq = xs[:, 1:] == xs[:, :-1]                           # 相邻完全相等
    tie_start = torch.cat([torch.ones((T, 1), dtype=torch.bool, device=x.device), ~eq], dim=1)
    group_id = tie_start.cumsum(dim=1) - 1                 # [T, N] 排序位置的组号
    # 组内平均秩: 排序位置 k 的有序秩为 k+1; 对同组取均值
    arange = torch.arange(N, device=x.device, dtype=x.dtype).expand(T, N)
    ones = torch.ones_like(arange)
    group_sum = torch.zeros_like(arange)
    group_cnt = torch.zeros_like(arange)
    group_sum.scatter_add_(1, group_id, arange + 1.0)
    group_cnt.scatter_add_(1, group_id, ones)
    avg_by_group = group_sum / group_cnt.clamp_min(1)   # [T, N] 组号->平均秩
    avg_sorted = avg_by_group.gather(1, group_id)       # [T, N] 排序位置->平均秩
    # 逆映射: 原始列 j 的秩 = avg_sorted[ rank_ord[j] ]
    rank_ord = torch.empty_like(order, dtype=torch.long)
    arange_l = torch.arange(N, device=x.device).expand(T, N)
    rank_ord.scatter_(1, order, arange_l)                  # rank_ord[i, order[i,k]] = k
    out = torch.gather(avg_sorted, 1, rank_ord) / cnt
    return torch.where(mask, out, torch.full_like(out, float("nan")))


def t_cs_TransNorm(x):
    """截面排名 -> 正态分位数变换 (rank pct -> clip[0.001,0.999] -> norm.ppf)"""
    t = _t()
    pct = _cs_rank_pct(x)
    pct = torch.clamp(pct, 0.001, 0.999)
    # 正态分位: 用 erf 反函数 (对齐 scipy norm.ppf)
    out = _norm_ppf(pct)
    return torch.where(~torch.isnan(pct), out, torch.full_like(out, float("nan")))


def _norm_ppf(p: torch.Tensor) -> torch.Tensor:
    """标准正态分位数 (ppf), 用 erfinv: ppf(p) = sqrt(2) * erfinv(2p-1)"""
    t = _t()
    from math import sqrt
    return float(sqrt(2.0)) * torch.erfinv(2.0 * p - 1.0)


# ============================================================
# Talib 指标族 torch 算子 (对齐 factor_engine 的 talib 语义)
#
# 对齐要点 (逐指标与 talib 核对):
#   - 严格窗口: 窗口内任一 NaN -> 结果 NaN (talib 不跳过 NaN);
#   - 首个干净窗口: 前导 NaN 时, 递归指标(EMA/RSI/ATR/ADX/KAMA) 延迟到
#     首个"连续 n 个非 NaN"的窗口作种子, 之后常系数递推, 遇 NaN 传播;
#   - 窗口类指标(SMA/WMA/CCI/WILLR/BOLL 等) 由 _rolling_map(x, n, n, ...)
#     实现"严格窗口"(min_periods=n, 前缀预热区全 NaN);
#   - mama / HT_DCPERIOD / HT_DCPHASE / HT_TRENDMODE 为 Hilbert 变换族,
#     未 GPU 化, 由调用方检测后 fallback 到 evaluate_expression 原路径。
# ============================================================

def _first_clean_window(x: torch.Tensor, n: int):
    """每列首个"严格干净窗口"(窗口内全非NaN)的种子信息
    返回 (s, seed, valid):
      s:    [N] 该窗口对应的输出行 (t = n-1+m)
      seed: [N] 窗口内均值
      valid:[N] 是否存在干净窗口 (否则该列结果全 NaN)
    """
    t = _t()
    T, N = x.shape
    n = max(1, min(int(n), T))
    nan = torch.full((N,), float("nan"), dtype=x.dtype, device=x.device)
    if T < n:
        return (torch.full((N,), T - 1, dtype=torch.long, device=x.device),
                nan, torch.zeros(N, dtype=torch.bool, device=x.device))
    nn = (~torch.isnan(x)).to(x.dtype)
    cnt = nn.unfold(0, n, 1).sum(dim=2)          # [T-n+1, N] 窗口内非NaN数
    clean = cnt >= n
    any_clean = clean.any(dim=0)                 # [N]
    m_first = torch.argmax(clean.to(x.dtype), dim=0)   # [N] 首个干净窗口的 m (0-based)
    s = n - 1 + m_first                          # [N] 输出行
    win = x.unfold(0, n, 1)                      # [T-n+1, N, n]
    mf = m_first.unsqueeze(0).unsqueeze(2).expand(-1, -1, n)
    wf = win.gather(0, mf)[0]                    # [N, n] 每列首个干净窗口
    seed = torch.nanmean(wf, dim=1)              # 窗口干净, 均值不含NaN
    seed = torch.where(any_clean, seed, nan)
    return s, seed, any_clean


def _first_non_nan(x: torch.Tensor) -> torch.Tensor:
    """每列首个非 NaN 行号 (全 NaN 列 = T)"""
    t = _t()
    T, N = x.shape
    nn = (~torch.isnan(x)).to(x.dtype)
    has = nn.any(dim=0)
    first = torch.argmax(nn, dim=0)
    return torch.where(has, first, torch.full_like(first, T))


def _mask_first_per_col(x: torch.Tensor, lookback: int,
                        s0: Optional[torch.Tensor] = None) -> torch.Tensor:
    """每列把前 s0_j+lookback 行置 NaN (talib 剥除前导NaN后按 lookback 输出掩码)
    s0_j = 原始输入该列首个非 NaN 行 (若未传, 取 x 自身首个非 NaN 行);
    输出仅从 s0_j+lookback 起有效。传 s0 以避免计算后序列自带的前导NaN被重复计入。
    """
    t = _t()
    T, N = x.shape
    if lookback <= 0:
        return x
    if s0 is None:
        s0 = _first_non_nan(x)
    row = torch.arange(T, device=x.device).unsqueeze(1)       # [T,1]
    keep = row >= (s0 + lookback).unsqueeze(0)
    return torch.where(keep, x, torch.full_like(x, float("nan")))


def _linear_recurrence(x: torch.Tensor, alpha: float, s: torch.Tensor,
                       seed: torch.Tensor) -> torch.Tensor:
    """常系数线性递推 (对齐 talib 递归指标): out[i] = alpha*x[i] + (1-alpha)*out[i-1]
    每列从 s_j 起以 seed_j 起步; i < s_j 为 NaN; 之后遇 NaN 传播。
    用 cumsum 向量化: out[i] = b^(i-s_j)*seed_j + alpha*b^i*(S[i]-S[s_j]),
    其中 b=1-alpha, S[i]=cumsum(xm/b^k), xm 在 s_j 之前置 0 (避免前导NaN污染)。
    """
    t = _t()
    T, N = x.shape
    b = 1.0 - alpha
    idx = torch.arange(T, dtype=x.dtype, device=x.device).unsqueeze(1)   # [T,1]
    s_col = s.to(x.dtype).unsqueeze(0)                                    # [1,N]
    active = idx >= s_col                                                 # [T,N]
    xm = torch.where(active, x, torch.zeros_like(x))
    bp = b ** idx                                                         # [T,1]
    z = xm / bp
    S = torch.cumsum(z, dim=0)
    S_s = S.gather(0, s.clamp(max=T - 1).unsqueeze(0))[0]                 # [N]
    out = (b ** (idx - s_col)) * seed.unsqueeze(0) + alpha * bp * (S - S_s.unsqueeze(0))
    return torch.where(active, out, torch.full_like(out, float("nan")))


def _strict_max(x, n):
    return _rolling_map(x, n, n, _ts_max_full, prefix_kind="max")


def _strict_min(x, n):
    return _rolling_map(x, n, n, _ts_min_full, prefix_kind="min")


def _strict_sum(x, n):
    return _rolling_map(x, n, n, _ts_sum_full, prefix_kind="sum")


def t_ts_SMA(x, n):
    """简单移动平均 (对齐 talib.SMA: 严格窗口, 前 n-1 个 NaN)"""
    n = max(1, min(int(n), x.shape[0]))
    return _rolling_map(x, n, n, _ts_mean_full, prefix_kind="mean")


def t_ts_EMA(x, n):
    """指数移动平均 (对齐 talib.EMA: 首个干净窗口均值作种子, 之后递归, NaN 传播)"""
    n = max(1, min(int(n), x.shape[0]))
    s, seed, valid = _first_clean_window(x, n)
    s2 = torch.where(valid, s, torch.full_like(s, x.shape[0] - 1))
    out = _linear_recurrence(x, 2.0 / (n + 1.0), s2, seed)
    return torch.where(valid.unsqueeze(0), out, torch.full_like(out, float("nan")))


def _wma_full(win):
    """加权移动平均窗口: 权重 (1,2,...,n), win[...,0] 最旧 (对齐 talib.WMA: 最近值权重 n)"""
    w = win.shape[2]
    weights = torch.arange(1, w + 1, dtype=win.dtype, device=win.device)
    return (win * weights.unsqueeze(0).unsqueeze(0)).sum(dim=2) / (w * (w + 1) / 2.0)


def t_ts_WMA(x, n):
    """加权移动平均 (对齐 talib.WMA: 权重 n..1, 严格窗口)"""
    n = max(1, min(int(n), x.shape[0]))
    return _rolling_map(x, n, n, _wma_full)


def t_ts_DEMA(x, n):
    """双指数移动平均 = 2*EMA - EMA(EMA) (对齐 talib.DEMA, 首个有效 2n-2)"""
    n = max(1, min(int(n), x.shape[0]))
    e1 = t_ts_EMA(x, n)
    e2 = t_ts_EMA(e1, n)
    return 2.0 * e1 - e2


def t_ts_TEMA(x, n):
    """三指数移动平均 = 3*E1 - 3*E2 + E3 (对齐 talib.TEMA, 首个有效 3n-3)"""
    n = max(1, min(int(n), x.shape[0]))
    e1 = t_ts_EMA(x, n)
    e2 = t_ts_EMA(e1, n)
    e3 = t_ts_EMA(e2, n)
    return 3.0 * e1 - 3.0 * e2 + e3


def t_ts_TRIMA(x, n):
    """三角移动平均 (对齐 talib.TRIMA: 两个 SMA 组合, 奇偶周期不同)"""
    n = max(1, min(int(n), x.shape[0]))
    if n % 2 == 1:
        p = (n + 1) // 2
        return t_ts_SMA(t_ts_SMA(x, p), p)
    else:
        p1 = n // 2
        p2 = p1 + 1
        return t_ts_SMA(t_ts_SMA(x, p1), p2)


def t_ts_RSI(x, n):
    """RSI (对齐 talib.RSI: Wilder 平滑, 首段均值种子, 首个有效 n)"""
    t = _t()
    n = max(1, min(int(n), x.shape[0]))
    T, N = x.shape
    diff = t_ts_Delta(x, 1)                       # diff[0]=NaN
    gain = torch.where(torch.isnan(diff), torch.full_like(diff, float("nan")),
                       torch.clamp(diff, min=0.0))
    loss = torch.where(torch.isnan(diff), torch.full_like(diff, float("nan")),
                       torch.clamp(-diff, min=0.0))
    s, seed_g, valid_g = _first_clean_window(gain, n)
    # loss 与 gain 具有相同的 NaN 掩码, 用同一干净窗口位置求 loss 的均值种子
    _, seed_l, _ = _first_clean_window(loss, n)
    s2 = torch.where(valid_g, s, torch.full_like(s, T - 1))
    avg_gain = _linear_recurrence(gain, 1.0 / n, s2, seed_g)
    avg_loss = _linear_recurrence(loss, 1.0 / n, s2, seed_l)
    rs = torch.where(avg_loss.abs() > EPS, avg_gain / avg_loss,
                     torch.full_like(avg_loss, float("inf")))
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = torch.where(torch.isnan(avg_gain) | torch.isnan(avg_loss),
                      torch.full_like(rsi, float("nan")), rsi)
    return torch.where(valid_g.unsqueeze(0), rsi, torch.full_like(rsi, float("nan")))


def _ts_mean_dev_full(win):
    """窗口内平均绝对偏差: mean(|x - 窗口均值|)"""
    m = _ts_mean_full(win)
    return _ts_mean_full(torch.abs(win - m.unsqueeze(2)))


def t_ts_CCI(h, l, c, n=14):
    """顺势指标 (对齐 talib.CCI: (tp-SMA)/(0.015*mean_dev))"""
    n = max(1, min(int(n), c.shape[0]))
    tp = (h + l + c) / 3.0
    sma = t_ts_SMA(tp, n)
    md = _rolling_map(tp, n, n, _ts_mean_dev_full)
    return (tp - sma) / (0.015 * md)


def t_ts_WILLR(h, l, c, n=14):
    """威廉指标 (对齐 talib.WILLR: -100*(hh-c)/(hh-ll), 前导NaN区为NaN, hh==ll 取 0)"""
    n = max(1, min(int(n), c.shape[0]))
    hh = _strict_max(h, n)
    ll = _strict_min(l, n)
    denom = hh - ll
    out = -100.0 * (hh - c) / denom
    # denom==0 (hh==ll) -> 0 (talib), denom NaN (窗口未填满/前导NaN) -> NaN
    out = torch.where(torch.isnan(denom), torch.full_like(out, float("nan")),
                      torch.where(denom.abs() > EPS, out, torch.zeros_like(out)))
    return out


def t_ts_ATR(h, l, c, n=14):
    """平均真实波幅 (对齐 talib.ATR: 真实波幅 Wilder 平滑, 种子=TR[1..n], 首个有效 n)"""
    n = max(1, min(int(n), c.shape[0]))
    T, N = c.shape
    prev_c = t_ts_Delay(c, 1)                     # prev_c[0]=NaN
    tr = torch.maximum(torch.maximum(h - l, torch.abs(h - prev_c)), torch.abs(l - prev_c))
    tr = torch.where(torch.isnan(prev_c), torch.full_like(tr, float("nan")), tr)  # tr[0]=NaN
    s, seed, valid = _first_clean_window(tr, n)
    s2 = torch.where(valid, s, torch.full_like(s, T - 1))
    avg = _linear_recurrence(tr, 1.0 / n, s2, seed)
    return torch.where(valid.unsqueeze(0), avg, torch.full_like(avg, float("nan")))


def t_ts_TRANGE(h, l, c):
    """真实波幅 (对齐 talib.TRANGE: 输出从索引1起, TR[0]=NaN)"""
    prev_c = t_ts_Delay(c, 1)
    tr = torch.maximum(torch.maximum(h - l, torch.abs(h - prev_c)), torch.abs(l - prev_c))
    return torch.where(torch.isnan(prev_c), torch.full_like(tr, float("nan")), tr)


def t_ts_NATR(h, l, c, n=14):
    """归一化真实波幅 (对齐 talib.NATR = ATR/close*100)"""
    atr = t_ts_ATR(h, l, c, n)
    return 100.0 * atr / c


def t_ts_MACD_DIF(x, fast=12, slow=26, signal=9):
    """MACD DIF (对齐 talib.MACD: 快慢EMA同起点, 快线种子=慢窗口尾部均值, 输出从 s0+slow+signal-2 起)

    talib 默认兼容模式:
      - 慢EMA种子 = 首个 slow 个价格均值; 快EMA种子 = 慢窗口中最后 fast 个价格均值;
      - 两者从同一 bar (compacted slow-1) 起以各自 k 递推;
      - DIF = fastEMA - slowEMA, 输出从 compacted slow+signal-2 起 (剥除前导NaN后)。
    """
    t = _t()
    fast = max(1, int(fast)); slow = max(1, int(slow)); signal = max(1, int(signal))
    if slow < fast:
        fast, slow = slow, fast
    y, L, s0 = _ht_compact(x)
    T, N = x.shape
    fastK = 2.0 / (float(fast) + 1.0)
    slowK = 2.0 / (float(slow) + 1.0)
    # 种子 (compacted): slow 窗口均值 与 其尾部 fast 均值
    slow_seed = torch.nanmean(y[0:slow], dim=0)             # [N]
    fast_seed = torch.nanmean(y[slow - fast:slow], dim=0)   # [N]
    s = torch.full((N,), slow - 1, dtype=torch.long, device=x.device)
    fastEMA = _linear_recurrence(y, fastK, s, fast_seed)
    slowEMA = _linear_recurrence(y, slowK, s, slow_seed)
    dif = fastEMA - slowEMA
    # 输出从 compacted slow+signal-2 起, 映射回绝对索引
    out = torch.full_like(x, float("nan"))
    start_i = slow + signal - 2
    iar = torch.arange(T, device=x.device).unsqueeze(1)     # [T,1]
    abs_row = s0.unsqueeze(0) + iar                         # [T,N]
    valid = (iar >= start_i) & (iar < L.unsqueeze(0)) & (abs_row < T)
    if bool(valid.any().item()):
        col_idx = torch.arange(N, device=x.device).unsqueeze(0).expand(T, N)[valid]
        out[abs_row[valid], col_idx] = dif[valid]
    return out


def _ts_stoch_raw(h, l, c, fastk):
    """原始随机K: 100*(c-ll)/(hh-ll), hh==ll 取 0 (对齐 talib.STOCH/STOCHF fastk)"""
    hh = _strict_max(h, fastk)
    ll = _strict_min(l, fastk)
    denom = hh - ll
    raw = 100.0 * (c - ll) / denom
    return torch.where(denom.abs() > EPS, raw, torch.zeros_like(raw))


def t_ts_KDJ_K(h, l, c, fastk=9, slowk=3, slowd=3):
    """KDJ K值 (对齐 talib.STOCH[0]: K=SMA(fastK,slowk), 输出从 s0+fastk+slowk+slowd-3 起)"""
    raw = _ts_stoch_raw(h, l, c, fastk)
    k = t_ts_SMA(raw, slowk)
    # talib STOCH 输出从剥除前导NaN后的 lookback 起 (含 slowd 的平滑lookback)
    return _mask_first_per_col(k, fastk + slowk + slowd - 3, _first_non_nan(c))


def _ts_pop_std_full(win):
    """窗口总体标准差 (ddof=0, 对齐 talib.BBANDS 内部)"""
    m = _ts_mean_full(win)
    return torch.sqrt((torch.abs(win - m.unsqueeze(2)) ** 2).sum(dim=2) / win.shape[2])


def t_ts_BOLL_POS(x, n=20, nbdev=2):
    """布林带位置 (对齐 talib.BOLL_POS: (c-lower)/(upper-lower), 带宽<=0 取 NaN)"""
    n = max(1, min(int(n), x.shape[0]))
    mid = t_ts_SMA(x, n)
    sd = _rolling_map(x, n, n, _ts_pop_std_full)
    upper = mid + nbdev * sd
    lower = mid - nbdev * sd
    bw = upper - lower
    return (x - lower) / torch.where(bw > 0, bw, torch.full_like(bw, float("nan")))


def t_ts_Amplitude(h, l, c, n):
    """n期振幅 = (最高-最低)/均价 (对齐引擎 ts_Amplitude: pandas rolling min_periods=1)"""
    n = max(1, min(int(n), c.shape[0]))
    hh = t_ts_Max(h, n)
    ll = t_ts_Min(l, n)
    cm = t_ts_Mean(c, n)
    return (hh - ll) / torch.where(cm.abs() > EPS, cm, torch.full_like(cm, float("nan")))


def _pairwise_window_stats(wa, wb):
    """wa/wb: [M, N, w] -> (cov, va, vb, cnt), 全部 ddof=1 (分母 cnt-1, 对齐 pandas)"""
    t = _t()
    mask = ~(torch.isnan(wa) | torch.isnan(wb))
    cnt = mask.sum(dim=2).clamp_min(1)
    ma = torch.where(mask, wa, torch.zeros_like(wa)).sum(dim=2) / cnt
    mb = torch.where(mask, wb, torch.zeros_like(wb)).sum(dim=2) / cnt
    ca = torch.where(mask, wa - ma.unsqueeze(2), torch.zeros_like(wa))
    cb = torch.where(mask, wb - mb.unsqueeze(2), torch.zeros_like(wb))
    denom = (cnt - 1).clamp_min(1)
    cov = (ca * cb).sum(dim=2) / denom
    va = (ca * ca).sum(dim=2) / denom
    vb = (cb * cb).sum(dim=2) / denom
    return cov, va, vb, cnt


def _corr_from_stats(cov, va, vb):
    """由 (cov, va, vb) 求相关系数: 零方差窗口 -> NaN (对齐 pandas corr)"""
    t = _t()
    denom = va * vb
    corr = cov / torch.sqrt(denom.clamp_min(0.0))
    return torch.where(denom > 0.0, corr, torch.full_like(corr, float("nan")))


def t_ts_Corr(a, b, n):
    """n期滚动相关系数 (对齐引擎 ts_Corr: pandas rolling(n, min_periods=2).corr, 成对跳过NaN)"""
    t = _t()
    T, N = a.shape
    n = max(2, min(int(n), T))
    out = torch.full_like(a, float("nan"))
    if T >= n:
        cov, va, vb, cnt = _pairwise_window_stats(a.unfold(0, n, 1), b.unfold(0, n, 1))
        corr = _corr_from_stats(cov, va, vb)
        out[n - 1:] = torch.where(cnt >= 2, corr, torch.full_like(corr, float("nan")))
    for t_idx in range(min(n - 1, T)):
        sa = a[:t_idx + 1]; sb = b[:t_idx + 1]
        cov, va, vb, cnt = _pairwise_window_stats(sa.unsqueeze(0).transpose(1, 2),
                                                  sb.unsqueeze(0).transpose(1, 2))
        cov = cov.squeeze(0); va = va.squeeze(0); vb = vb.squeeze(0); cnt = cnt.squeeze(0)
        corr = _corr_from_stats(cov, va, vb)
        out[t_idx] = torch.where(cnt >= 2, corr, torch.full_like(corr, float("nan")))
    return out


def _rolling_cov(a, b, n):
    """n期滚动协方差 (对齐 pandas rolling(n, min_periods=2).cov, ddof=1)"""
    t = _t()
    T, N = a.shape
    n = max(2, min(int(n), T))
    out = torch.full_like(a, float("nan"))
    if T >= n:
        cov, _, _, cnt = _pairwise_window_stats(a.unfold(0, n, 1), b.unfold(0, n, 1))
        out[n - 1:] = torch.where(cnt >= 2, cov, torch.full_like(cov, float("nan")))
    for t_idx in range(min(n - 1, T)):
        sa = a[:t_idx + 1]; sb = b[:t_idx + 1]
        cov, _, _, cnt = _pairwise_window_stats(sa.unsqueeze(0).transpose(1, 2),
                                                sb.unsqueeze(0).transpose(1, 2))
        cov = cov.squeeze(0); cnt = cnt.squeeze(0)
        out[t_idx] = torch.where(cnt >= 2, cov, torch.full_like(cov, float("nan")))
    return out


def _rolling_var(x, n):
    return _rolling_cov(x, x, n)


def t_ts_Reversal(x, n):
    """反转 = n期收益率 (对齐引擎 reversal: 直接映射 ts_PctChange, 正收益语义)"""
    return t_ts_PctChange(x, n)


def _scatter_compact(outc, L, s0, out):
    """把 compacted 面板 outc 映射回绝对索引: out[s0_j + i] = outc[i] (i < L_j)
    outc/out: [T,N], L/s0: [N]。用高级索引避免 clamp 碰撞。"""
    t = _t()
    T, N = out.shape
    iar = torch.arange(T, device=out.device).unsqueeze(1)      # [T,1]
    abs_row = s0.unsqueeze(0) + iar                            # [T,N]
    valid = (iar < L.unsqueeze(0)) & (abs_row < T)
    if not bool(valid.any().item()):
        return out
    col_idx = torch.arange(N, device=out.device).unsqueeze(0).expand(T, N)[valid]
    out[abs_row[valid], col_idx] = outc[valid]
    return out


def t_ts_OBV(c, v):
    """能量潮 (对齐 talib.OBV: 剥除前导NaN后 OBV[s0]=vol[s0], 再按涨跌累积)"""
    t = _t()
    cc, L, s0 = _ht_compact(c)
    vc, _, _ = _ht_compact(v)
    T, N = c.shape
    diff = t_ts_Delta(cc, 1)                       # diff[0]=NaN
    sign = torch.where(diff > 0, torch.ones_like(diff),
                       torch.where(diff < 0, -torch.ones_like(diff), torch.zeros_like(diff)))
    contrib = torch.where(torch.isnan(diff), torch.zeros_like(diff), sign * vc)
    contrib[0] = vc[0]                             # OBV[0]=volume[0] (compacted)
    outc = torch.cumsum(contrib, dim=0)
    return _scatter_compact(outc, L, s0, torch.full_like(c, float("nan")))


def t_ts_AD(h, l, c, v):
    """累积派发线 (对齐 talib.AD: 剥除前导NaN后从首个有效行累积, 前导NaN区为NaN)"""
    t = _t()
    hc, L, s0 = _ht_compact(h)
    lc, _, _ = _ht_compact(l)
    cc, _, _ = _ht_compact(c)
    vc, _, _ = _ht_compact(v)
    T, N = c.shape
    denom = hc - lc
    mfm = torch.where(denom.abs() > EPS, ((cc - lc) - (hc - cc)) / denom, torch.zeros_like(cc))
    outc = torch.cumsum(mfm * vc, dim=0)
    return _scatter_compact(outc, L, s0, torch.full_like(c, float("nan")))


def t_ts_ADOSC(h, l, c, v, fast=3, slow=10):
    """累积/派发震荡 (对齐 talib.ADOSC: 内部AD累积, 双EMA种子=首个AD值, 输出从 s0+slow-1 起)"""
    ad = t_ts_AD(h, l, c, v)
    s0 = _first_non_nan(ad)
    T, N = ad.shape
    fastk = 2.0 / (float(fast) + 1.0)
    slowk = 2.0 / (float(slow) + 1.0)
    seed = ad.gather(0, s0.clamp(max=T - 1).unsqueeze(0))[0]   # 首个有效AD值
    fe = _linear_recurrence(ad, fastk, s0, seed)
    se = _linear_recurrence(ad, slowk, s0, seed)
    osc = fe - se
    return _mask_first_per_col(osc, int(slow) - 1)


def t_ts_MFI(h, l, c, v, n=14):
    """资金流向指标 (对齐 talib.MFI: 100*pos/(pos+neg), 首个有效 n)"""
    t = _t()
    n = max(1, min(int(n), c.shape[0]))
    tp = (h + l + c) / 3.0
    mf = tp * v
    diff = t_ts_Delta(tp, 1)                      # diff[0]=NaN (首日不参与)
    pos = torch.where(torch.isnan(diff), torch.full_like(diff, float("nan")),
                      torch.where(diff > 0, mf, torch.zeros_like(mf)))
    neg = torch.where(torch.isnan(diff), torch.full_like(diff, float("nan")),
                      torch.where(diff < 0, mf, torch.zeros_like(mf)))
    ps = _strict_sum(pos, n)
    ns = _strict_sum(neg, n)
    denom = ps + ns
    out = torch.where(denom.abs() > EPS, 100.0 * ps / denom, torch.full_like(denom, float("nan")))
    # talib: neg_sum==0 -> 100; pos_sum==0 -> 0
    out = torch.where((ns.abs() <= EPS) & (ps.abs() > EPS), torch.full_like(out, 100.0),
                      torch.where((ps.abs() <= EPS) & (ns.abs() > EPS), torch.zeros_like(out), out))
    return out


def t_ts_STOCHF_K(h, l, c, fastk=5, fastd=3):
    """快速随机K值 (对齐 talib.STOCHF[0]=FASTK 未平滑, 输出从 s0+fastk+fastd-2 起)"""
    raw = _ts_stoch_raw(h, l, c, fastk)
    return _mask_first_per_col(raw, fastk + fastd - 2, _first_non_nan(c))


def t_ts_STOCHRSI_K(c, n=14, fastk=3, fastd=3):
    """随机RSI K值 (对齐 talib.STOCHRSI[0]=FASTK: RSI 后按 fastk 窗口 stoch, 未平滑,
    输出从 s0+n+fastk+fastd-2 起)"""
    n = max(1, min(int(n), c.shape[0]))
    fastk = max(1, min(int(fastk), c.shape[0]))
    rsi = t_ts_RSI(c, n)                          # 首个有效 s0+n
    rmin = _strict_min(rsi, fastk)
    rmax = _strict_max(rsi, fastk)
    denom = rmax - rmin
    raw = 100.0 * (rsi - rmin) / torch.where(denom.abs() > EPS, denom,
                                             torch.full_like(denom, float("nan")))
    # 平坦窗口 -> 0 (talib STOCHF 的 TA_IS_ZERO 守卫)
    raw = torch.where(denom.abs() > EPS, raw, torch.zeros_like(raw))
    return _mask_first_per_col(raw, n + fastk + fastd - 2, _first_non_nan(c))


def _aroon_side(x, n=25, use_max=True):
    """AROON 单侧 (对齐 talib.AROON: 窗口 [t-n..t] 含当前, 并列极值取最新)
    use_max=True  -> Aroon Up  (最高high追踪, talib 用 >=)
    use_max=False -> Aroon Down(最低low追踪,  talib 用 <=)
    输出从 s0+n 起 (talib 剥除前导NaN后首个输出 at n)"""
    t = _t()
    T, N = x.shape
    w = n + 1
    out = torch.full_like(x, float("nan"))
    if T < w:
        return out
    win = x.unfold(0, w, 1)                       # [M, N, w]
    mask = ~torch.isnan(win)
    valid = mask.sum(dim=2) >= w                  # 严格窗口
    fill = -float("inf") if use_max else float("inf")
    xf = torch.where(mask, win, torch.full_like(win, fill))
    # 并列取最新极值 (talib 扫描中后出现的覆盖): 翻转后 argmax/argmin
    if use_max:
        pos_flip = torch.argmax(torch.flip(xf, dims=[2]), dim=2)
    else:
        pos_flip = torch.argmin(torch.flip(xf, dims=[2]), dim=2)
    pos_fwd = (w - 1) - pos_flip                  # 原窗口内位置 (0=最旧)
    bars_since = (w - 1) - pos_fwd                # 距当前行的回溯数
    out[w - 1:] = torch.where(valid, 100.0 * (n - bars_since) / n,
                              torch.full_like(out[w - 1:], float("nan")))
    return out


def t_ts_AROON_UP(h, l, n=25):
    """阿隆上轨 (对齐引擎 ts_AROON_UP = talib.AROON[0] = Aroon Down, 最低low追踪)"""
    return _aroon_side(l, n, use_max=False)


def t_ts_AROON_DOWN(h, l, n=25):
    """阿隆下轨 (对齐引擎 ts_AROON_DOWN = talib.AROON[1] = Aroon Up, 最高high追踪)"""
    return _aroon_side(h, n, use_max=True)


def t_ts_AROONOSC(h, l, n=25):
    """阿隆震荡 = AroonUp - AroonDown (对齐 talib.AROONOSC)"""
    return _aroon_side(h, n, use_max=True) - _aroon_side(l, n, use_max=False)


def t_ts_ADXR(h, l, c, n=14):
    """ADX评级 (对齐 talib.ADXR: (ADX[i]+ADX[i-(n-1)])/2, 首个有效 3n-2)"""
    adx = t_ts_ADX(h, l, c, n)
    return (adx + t_ts_Delay(adx, n - 1)) / 2.0


def _talib_wilder_seed(win, alpha):
    """talib Wilder 平滑种子: 前 n-1 个之和/n 作初值, 再平滑一步到窗口末行
    win: [N, n] 首个严格干净窗口 (行 [s-n+1..s])
    返回 [N] 该列 s 行的平滑初值 (对齐 ta_ADX/ta_ATR 的累加种子逻辑)
    """
    n = win.shape[1]
    avg0 = win[:, :-1].sum(dim=1) / n          # sum(x[V..V+n-2])/n
    return (1.0 - alpha) * avg0 + alpha * win[:, -1]


def _first_clean_window_wilder(x, n):
    """每列首个严格干净窗口的 talib Wilder 种子
    返回 (s, seed, valid): s 窗口末行, seed 该行的 Wilder 平滑初值
    """
    t = _t()
    T, N = x.shape
    n = max(1, min(int(n), T))
    nan = torch.full((N,), float("nan"), dtype=x.dtype, device=x.device)
    if T < n:
        return (torch.full((N,), T - 1, dtype=torch.long, device=x.device),
                nan, torch.zeros(N, dtype=torch.bool, device=x.device))
    nn = (~torch.isnan(x)).to(x.dtype)
    cnt = nn.unfold(0, n, 1).sum(dim=2)
    clean = cnt >= n
    any_clean = clean.any(dim=0)
    m_first = torch.argmax(clean.to(x.dtype), dim=0)
    s = n - 1 + m_first
    win = x.unfold(0, n, 1)
    mf = m_first.unsqueeze(0).unsqueeze(2).expand(-1, -1, n)
    wf = win.gather(0, mf)[0]                  # [N, n]
    seed = _talib_wilder_seed(wf, 1.0 / n)
    seed = torch.where(any_clean, seed, nan)
    return s, seed, any_clean


def t_ts_ADX(h, l, c, n=14):
    """ADX 平均趋向指标 (对齐 talib.ADX: TR/DM+/- 用 Wilder 累加种子平滑 -> DI -> DX -> ADX,
    首个有效 s0+2n-1)"""
    t = _t()
    n = max(1, min(int(n), c.shape[0]))
    T, N = c.shape
    alpha = 1.0 / n
    prev_c = t_ts_Delay(c, 1)
    tr = torch.maximum(torch.maximum(h - l, torch.abs(h - prev_c)), torch.abs(l - prev_c))
    tr = torch.where(torch.isnan(prev_c), torch.full_like(tr, float("nan")), tr)  # tr[0]=NaN
    up = h - t_ts_Delay(h, 1)                     # high 变化 (up[0]=NaN)
    dn = t_ts_Delay(l, 1) - l                     # low 反向变化 (dn[0]=NaN)
    plus_dm = torch.where((up > dn) & (up > 0), up, torch.zeros_like(up))
    minus_dm = torch.where((dn > up) & (dn > 0), dn, torch.zeros_like(dn))
    nanmask = torch.isnan(up) | torch.isnan(dn)
    plus_dm = torch.where(nanmask, torch.full_like(up, float("nan")), plus_dm)
    minus_dm = torch.where(nanmask, torch.full_like(up, float("nan")), minus_dm)
    # talib Wilder 累加种子 -> 常系数递推 (alpha=1/n)
    s_t, seed_t, valid_t = _first_clean_window_wilder(tr, n)
    s_p, seed_p, valid_p = _first_clean_window_wilder(plus_dm, n)
    s_m, seed_m, valid_m = _first_clean_window_wilder(minus_dm, n)
    tr_s = _linear_recurrence(tr, alpha, torch.where(valid_t, s_t, T - 1), seed_t)
    p_s = _linear_recurrence(plus_dm, alpha, torch.where(valid_p, s_p, T - 1), seed_p)
    m_s = _linear_recurrence(minus_dm, alpha, torch.where(valid_m, s_m, T - 1), seed_m)
    di_plus = 100.0 * p_s / tr_s
    di_minus = 100.0 * m_s / tr_s
    sum_di = di_plus + di_minus
    dx = 100.0 * torch.abs(di_plus - di_minus) / torch.where(sum_di.abs() > EPS,
                                                             sum_di, torch.full_like(sum_di, float("nan")))
    # ADX = DX 的 Wilder 平滑 (种子 = 前 n 个 DX 均值, 对齐 talib)
    s_a, seed_a, valid_a = _first_clean_window(dx, n)
    adx = _linear_recurrence(dx, alpha, torch.where(valid_a, s_a, T - 1), seed_a)
    return torch.where(valid_a.unsqueeze(0), adx, torch.full_like(adx, float("nan")))


def t_ts_ULTOSC(h, l, c, p1=7, p2=14, p3=28):
    """终极震荡指标 (对齐 talib.ULTOSC: 100*(4*A/B+2*C/D+E/F)/7, 首个有效 p3)"""
    prev_c = t_ts_Delay(c, 1)
    ll = torch.minimum(l, prev_c)
    hh = torch.maximum(h, prev_c)
    bp = torch.where(torch.isnan(prev_c), torch.full_like(c, float("nan")), c - ll)
    tr = torch.where(torch.isnan(prev_c), torch.full_like(c, float("nan")), hh - ll)
    a = t_ts_SMA(bp, p1); B = t_ts_SMA(tr, p1)
    C = t_ts_SMA(bp, p2); D = t_ts_SMA(tr, p2)
    E = t_ts_SMA(bp, p3); F = t_ts_SMA(tr, p3)
    return 100.0 * (4.0 * a / B + 2.0 * C / D + E / F) / 7.0


def t_ts_AVGPRICE(o, h, l, c):
    """均价 (对齐 talib.AVGPRICE)"""
    return (o + h + l + c) / 4.0


def t_ts_MEDPRICE(h, l):
    """中位价 (对齐 talib.MEDPRICE)"""
    return (h + l) / 2.0


def t_ts_TYPPRICE(h, l, c):
    """典型价格 (对齐 talib.TYPPRICE)"""
    return (h + l + c) / 3.0


def t_ts_WCLPRICE(h, l, c):
    """加权收盘价 (对齐 talib.WCLPRICE)"""
    return (h + l + 2.0 * c) / 4.0


def t_ts_PPO(x, fast=12, slow=26, matype=0):
    """价格震荡百分比 (对齐 talib.PPO: (MA(fast)-MA(slow))/MA(slow)*100, matype=0 为 SMA,
    输出从 s0+slow-1 起)"""
    # matype=0 -> SMA (talib 默认); 其余 matype 当前仅按 SMA 处理
    ef = t_ts_SMA(x, fast)
    es = t_ts_SMA(x, slow)
    return 100.0 * (ef - es) / es


def t_ts_BETA(c, n=20):
    """Beta系数: 个股收益率对截面均值收益率的滚动beta (对齐引擎 ts_BETA)"""
    ret = t_ts_PctChange(c, 1)
    mkt = _cs_nanmean(ret, dim=1).expand(-1, ret.shape[1])   # 截面均值 (每行相同)
    cov = _rolling_cov(ret, mkt, n)
    var_m = _rolling_var(mkt, n)
    return cov / torch.where(var_m.abs() > EPS, var_m, torch.full_like(var_m, float("nan")))


def t_ts_RESVOL(c, n=250):
    """Barra 残差波动率 (对齐引擎 ts_RESVOL): Beta(市场=截面均值)回归残差收益的年化标准差
    复用 t_ts_BETA 计算 beta, 残差 = 收益 - beta×市场收益, 再滚动 std(窗口 n, min_periods=2) × sqrt(252)"""
    ret = t_ts_PctChange(c, 1)
    mkt = _cs_nanmean(ret, dim=1).expand(-1, ret.shape[1])
    beta = t_ts_BETA(c, n)
    resid = ret - beta * mkt
    return t_ts_Stdev(resid, n) * float(np.sqrt(252.0))


def t_ts_CORREL(c, n=20):
    """相关系数: 个股收益率对截面均值收益率的滚动相关系数 (对齐引擎 ts_CORREL)
    对齐 pandas rolling(n, min_periods=2).corr: 仅在两序列的配对观测上计算。"""
    ret = t_ts_PctChange(c, 1)
    mkt = _cs_nanmean(ret, dim=1).expand(-1, ret.shape[1])
    return t_ts_Corr(ret, mkt, n)


def t_ts_KAMA(x, n):
    """考夫曼自适应移动平均 (对齐 talib.KAMA: ER -> 平滑系数 -> 递推, 种子=前一行价 x[i0-1],
    首个有效 s0+n)"""
    t = _t()
    n = max(2, min(int(n), x.shape[0]))
    T, N = x.shape
    out = torch.full_like(x, float("nan"))
    if T <= n:
        return out
    fastest = 2.0 / (2.0 + 1.0)
    slowest = 2.0 / (30.0 + 1.0)
    nn = (~torch.isnan(x)).to(x.dtype)
    cnt = nn.unfold(0, n + 1, 1).sum(dim=2)        # [T-n, N] 窗口 [i-n..i]
    clean = cnt >= n + 1
    any_clean = clean.any(dim=0)
    m0 = torch.argmax(clean.to(x.dtype), dim=0)    # [N] 首个干净窗口起始行
    i0 = n + m0                                    # [N] KAMA 起始输出行
    # talib 种子 = 前一行价格 x[i0-1] (prevKAMA 初值)
    x_seed = x.gather(0, (i0 - 1).clamp(min=0, max=T - 1).unsqueeze(0))[0]
    cur = torch.where(any_clean, x_seed, torch.full_like(x_seed, float("nan")))
    num = torch.abs(x - t_ts_Delay(x, n))
    num = torch.where(torch.isnan(num), torch.zeros_like(num), num)
    diff = torch.abs(x - t_ts_Delay(x, 1))
    diff = torch.where(torch.isnan(diff), torch.zeros_like(diff), diff)
    vol = _strict_sum(diff, n)                     # [T, N] 窗口 [i-n+1..i] 的 |diff| 和
    start = int(i0.min().item()) if any_clean.any() else T
    for i in range(start, T):
        ii = i0 <= i                               # [N] 该列是否已开始
        er = torch.where(vol[i].abs() > EPS, num[i] / vol[i], torch.zeros_like(num[i]))
        sc = (er * (fastest - slowest) + slowest) ** 2
        cur = torch.where(ii, cur + sc * (x[i] - cur), cur)
        out[i] = torch.where(ii, cur, torch.full_like(cur, float("nan")))
    return out


def t_ts_SAR(h, l, af=0.02, max_af=0.2):
    """抛物线SAR (对齐 talib.SAR: 剥除前导NaN后按 talib 逻辑递归, 映射回绝对索引)

    talib 逻辑:
      - 首两根有效K线: -DM1>0 且 +DM1<-DM1 -> 初始空头, 否则多头;
      - 首个输出 = 首根K线的 opposite 极值 (多->L[0], 空->H[0]);
      - 每根K线判断穿破翻转, SAR=ep 并夹到 [prevHigh,newHigh]/[prevLow,newLow],
        或沿用旧SAR; 之后 sar=fma(af, ep-sar, sar) 再夹取。
    """
    t = _t()
    T, N = h.shape
    out = torch.full_like(h, float("nan"))
    if T < 2:
        return out
    hc, L, s0 = _ht_compact(h)
    lc, _, _ = _ht_compact(l)
    af = float(af); max_af = float(max_af)
    if af > max_af:
        af = max_af
    maxL = int(L.max().item())
    if maxL < 2:
        return out
    # 初始方向: 基于 compacted 第0、1根K线 (对齐 ta_SAR 的 TA_MINUS_DM)
    diffP = hc[1] - hc[0]
    diffM = lc[0] - lc[1]
    is_short = (diffM > 0) & (diffP < diffM)       # -DM1>0 且 +DM1<-DM1
    is_long = ~is_short
    # 初始状态: ep = H[1](多)/L[1](空); sar = L[0](多)/H[0](空)
    ep = torch.where(is_long, hc[1], lc[1])
    sar = torch.where(is_long, lc[0], hc[0])
    # talib "cheat": 首个迭代的 prevHigh/prevLow = 当前 bar (H[1]/L[1])
    cur_af = torch.full((N,), af, dtype=h.dtype, device=h.device)
    prev_high = hc[1].clone()
    prev_low = lc[1].clone()
    row_idx = torch.arange(N, device=h.device)
    for i in range(1, maxL):
        act = i < L
        new_high = torch.where(act, hc[i], prev_high)
        new_low = torch.where(act, lc[i], prev_low)
        is_long_cur = is_long
        # 穿破翻转 (多头: low<=sar -> 转空; 空头: high>=sar -> 转多)
        switch = is_long_cur & (new_low <= sar)
        switch = switch | ((~is_long_cur) & (new_high >= sar))
        flip = switch & act
        # 输出值: 翻转时 sar=ep 并夹取, 否则沿用旧 sar
        ov_long = torch.maximum(torch.maximum(ep, prev_high), new_high)
        ov_short = torch.minimum(torch.minimum(ep, prev_low), new_low)
        ov = torch.where(is_long_cur, ov_long, ov_short)
        out_val = torch.where(flip, ov, sar)
        # 写入输出 (compacted 行 i -> 绝对行 s0+i, 仅 active 列)
        abs_row = s0 + i
        out[abs_row[act], row_idx[act]] = out_val[act]
        # ---- 状态更新 ----
        old_ep = ep
        made_long = is_long_cur & ~switch & (new_high > old_ep)
        made_short = (~is_long_cur) & ~switch & (new_low < old_ep)
        made = made_long | made_short
        # ep: 不翻转创新高(多)/新低(空) 更新; 翻转后 ep = newLow(多转空)/newHigh(空转多)
        ep = torch.where(is_long_cur & ~switch & (new_high > old_ep), new_high, ep)
        ep = torch.where((~is_long_cur) & ~switch & (new_low < old_ep), new_low, ep)
        ep = torch.where(flip, torch.where(is_long_cur, new_low, new_high), ep)
        # af: 翻转归零; 不翻转创新高/新低 -> +=afstep (上限 max_af)
        cur_af = torch.where(flip, torch.full_like(cur_af, af), cur_af)
        cur_af = torch.where(made, torch.clamp(cur_af + af, max=max_af), cur_af)
        # sar: fma(af, ep-sar_out, sar_out) 再按新方向夹取
        # 翻转时 talib 先输出覆盖值(夹取后的ep), 再以该覆盖值作 sar 基数递推
        new_sar = out_val + cur_af * (ep - out_val)
        is_long = torch.where(flip, ~is_long_cur, is_long_cur)
        # 多头: sar=min(new, prevLow, newLow); 空头: sar=max(new, prevHigh, newHigh)
        sar = torch.where(is_long,
                          torch.minimum(torch.minimum(new_sar, prev_low), new_low),
                          torch.maximum(torch.maximum(new_sar, prev_high), new_high))
        prev_high = new_high
        prev_low = new_low
    return out


# ============================================================
# Hilbert 变换族算子 (mama / HT_DCPERIOD / HT_DCPHASE / HT_TRENDMODE)
#
# 对齐要点 (逐指标与 talib 核对):
#   - talib 会先剥除每列前导 NaN, 在 compacted 序列上以 compacted 索引奇偶
#     做 Hilbert 变换(已验证奇/偶前导 NaN 均逐位对齐), 输出映射回绝对索引;
#   - 递归状态(奇偶循环缓冲/相位/周期等)逐列独立, 时间步用 Python 循环、
#     列方向向量化(与 KAMA/SAR 同策略);
#   - mama/HT_DCPERIOD 首个有效 compacted 索引 = 32,
#     HT_DCPHASE/HT_TRENDMODE = 63; 中间含 NaN 沿递归传播(对齐 talib);
#   - HT_TRENDMODE 输出恒为 0/1 (int 语义), warmup 段为 0。
# ============================================================

def _ht_compact(x):
    """按列剥除前导 NaN, 返回 (y, L, s0):
      y:  [T, N] compacted 面板 (越界行 NaN)
      L:  [N] 每列有效长度 (全NaN列=0)
      s0: [N] 每列首个非NaN索引 (全NaN列=T)
    """
    t = _t()
    T, N = x.shape
    nn = (~torch.isnan(x)).to(x.dtype)              # [T, N]
    has = nn.any(dim=0)                             # [N]
    s0 = torch.argmax(nn, dim=0)                    # [N] 首个非NaN行 (全NaN=0)
    s0 = torch.where(has, s0, torch.full_like(s0, T))
    L = T - s0                                      # [N] 有效长度
    iar = torch.arange(T, device=x.device).unsqueeze(1)   # [T,1]
    abs_row = s0.unsqueeze(0) + iar                 # [T,N]
    valid = abs_row < T                             # [T,N]
    y = x.gather(0, abs_row.clamp(max=T - 1))       # [T,N]
    y = torch.where(valid, y, torch.full_like(y, float("nan")))
    return y, L, s0


def _ht_core_torch(y, L, warm):
    """Hilbert 变换核心 (向量化跨列, compacted 空间共享奇偶/hIdx)
    逐列复刻 talib C 逻辑 (与 talib 逐位对齐)。
    返回 dict: detrender/Q1/jI/jQ/Q2/I2/tempReal2/period/smoothed 各 [T, N]。
    """
    t = _t()
    T, N = y.shape
    dtype = y.dtype
    device = y.device
    a = 0.0962
    b = 0.5769
    rad2deg = 180.0 / (4.0 * np.arctan(1.0))
    z = torch.zeros(N, dtype=dtype, device=device)
    zz = torch.zeros(3, N, dtype=dtype, device=device)
    nan = torch.full((N,), float("nan"), dtype=dtype, device=device)
    detrender_O = zz.clone(); detrender_E = zz.clone()
    Q1_O = zz.clone(); Q1_E = zz.clone()
    jI_O = zz.clone(); jI_E = zz.clone()
    jQ_O = zz.clone(); jQ_E = zz.clone()
    prev_detrender_O = z.clone(); prev_detrender_E = z.clone()
    prev_detrender_in_O = z.clone(); prev_detrender_in_E = z.clone()
    prev_Q1_O = z.clone(); prev_Q1_E = z.clone()
    prev_Q1_in_O = z.clone(); prev_Q1_in_E = z.clone()
    prev_jI_O = z.clone(); prev_jI_E = z.clone()
    prev_jI_in_O = z.clone(); prev_jI_in_E = z.clone()
    prev_jQ_O = z.clone(); prev_jQ_E = z.clone()
    prev_jQ_in_O = z.clone(); prev_jQ_in_E = z.clone()
    period = z.clone(); prevQ2 = z.clone(); prevI2 = z.clone()
    Im = z.clone(); Re = z.clone()
    I1ForOddPrev2 = z.clone(); I1ForOddPrev3 = z.clone()
    I1ForEvenPrev2 = z.clone(); I1ForEvenPrev3 = z.clone()
    out = {k: torch.full((T, N), float("nan"), dtype=dtype, device=device)
           for k in ("detrender", "Q1", "jI", "jQ", "Q2", "I2", "tempReal2",
                     "period", "smoothed")}
    hIdx = 0
    for i in range(warm, T):
        active = i < L                               # [N]
        sm = 0.1 * (y[i - 3] + 2.0 * y[i - 2] + 3.0 * y[i - 1] + 4.0 * y[i])
        sm = torch.where(active, sm, z)              # 非 active 列置 0, 避免污染
        adjustedPrevPeriod = 0.075 * period + 0.54
        out["smoothed"][i] = torch.where(active, sm, nan)
        if i % 2 == 0:
            # ---- even 分支 ----
            ht = a * sm
            old = detrender_E[hIdx].clone()
            detrender_E[hIdx] = ht
            det = -old + ht - prev_detrender_E + b * prev_detrender_in_E
            prev_detrender_E = b * prev_detrender_in_E
            prev_detrender_in_E = sm
            det = det * adjustedPrevPeriod
            ht = a * det
            old = Q1_E[hIdx].clone()
            Q1_E[hIdx] = ht
            Q1 = -old + ht - prev_Q1_E + b * prev_Q1_in_E
            prev_Q1_E = b * prev_Q1_in_E
            prev_Q1_in_E = det
            Q1 = Q1 * adjustedPrevPeriod
            ht = a * I1ForEvenPrev3
            old = jI_E[hIdx].clone()
            jI_E[hIdx] = ht
            jI = -old + ht - prev_jI_E + b * prev_jI_in_E
            prev_jI_E = b * prev_jI_in_E
            prev_jI_in_E = I1ForEvenPrev3
            jI = jI * adjustedPrevPeriod
            ht = a * Q1
            old = jQ_E[hIdx].clone()
            jQ_E[hIdx] = ht
            jQ = -old + ht - prev_jQ_E + b * prev_jQ_in_E
            prev_jQ_E = b * prev_jQ_in_E
            prev_jQ_in_E = Q1
            jQ = jQ * adjustedPrevPeriod
            hIdx += 1
            if hIdx == 3:
                hIdx = 0
            Q2 = 0.2 * (Q1 + jI) + 0.8 * prevQ2
            I2 = 0.2 * (I1ForEvenPrev3 - jQ) + 0.8 * prevI2
            I1ForOddPrev3 = I1ForOddPrev2
            I1ForOddPrev2 = det
            tempReal2 = torch.where(I1ForEvenPrev3 != 0.0,
                                    torch.atan(Q1 / I1ForEvenPrev3) * rad2deg, z)
        else:
            # ---- odd 分支 ----
            ht = a * sm
            old = detrender_O[hIdx].clone()
            detrender_O[hIdx] = ht
            det = -old + ht - prev_detrender_O + b * prev_detrender_in_O
            prev_detrender_O = b * prev_detrender_in_O
            prev_detrender_in_O = sm
            det = det * adjustedPrevPeriod
            ht = a * det
            old = Q1_O[hIdx].clone()
            Q1_O[hIdx] = ht
            Q1 = -old + ht - prev_Q1_O + b * prev_Q1_in_O
            prev_Q1_O = b * prev_Q1_in_O
            prev_Q1_in_O = det
            Q1 = Q1 * adjustedPrevPeriod
            ht = a * I1ForOddPrev3
            old = jI_O[hIdx].clone()
            jI_O[hIdx] = ht
            jI = -old + ht - prev_jI_O + b * prev_jI_in_O
            prev_jI_O = b * prev_jI_in_O
            prev_jI_in_O = I1ForOddPrev3
            jI = jI * adjustedPrevPeriod
            ht = a * Q1
            old = jQ_O[hIdx].clone()
            jQ_O[hIdx] = ht
            jQ = -old + ht - prev_jQ_O + b * prev_jQ_in_O
            prev_jQ_O = b * prev_jQ_in_O
            prev_jQ_in_O = Q1
            jQ = jQ * adjustedPrevPeriod
            Q2 = 0.2 * (Q1 + jI) + 0.8 * prevQ2
            I2 = 0.2 * (I1ForOddPrev3 - jQ) + 0.8 * prevI2
            I1ForEvenPrev3 = I1ForEvenPrev2
            I1ForEvenPrev2 = det
            tempReal2 = torch.where(I1ForOddPrev3 != 0.0,
                                    torch.atan(Q1 / I1ForOddPrev3) * rad2deg, z)
        # ---- 周期调整 (对齐 C) ----
        Re = 0.2 * (I2 * prevI2 + Q2 * prevQ2) + 0.8 * Re
        Im = 0.2 * (I2 * prevQ2 - Q2 * prevI2) + 0.8 * Im
        prevQ2 = Q2
        prevI2 = I2
        tempReal = period
        period = torch.where((Im != 0.0) & (Re != 0.0),
                             360.0 / (torch.atan(Im / Re) * rad2deg), period)
        tempReal2b = 1.5 * tempReal
        period = torch.minimum(period, tempReal2b)
        tempReal2b = 0.67 * tempReal
        period = torch.maximum(period, tempReal2b)
        period = torch.clamp(period, min=6.0, max=50.0)
        period = 0.2 * period + 0.8 * tempReal
        out["detrender"][i] = torch.where(active, det, nan)
        out["Q1"][i] = torch.where(active, Q1, nan)
        out["jI"][i] = torch.where(active, jI, nan)
        out["jQ"][i] = torch.where(active, jQ, nan)
        out["Q2"][i] = torch.where(active, Q2, nan)
        out["I2"][i] = torch.where(active, I2, nan)
        out["tempReal2"][i] = torch.where(active, tempReal2, nan)
        out["period"][i] = torch.where(active, period, nan)
    return out


def t_ts_MAMA(x, fast=0.5, slow=0.05):
    """MESA自适应移动平均 (对齐 talib.MAMA: Hilbert+动态Alpha, 首个有效 32)
    与引擎 ts_MAMA 一致只取 MAMA 输出 (FAMA 不需要)。
    """
    t = _t()
    T, N = x.shape
    fast = max(0.01, min(float(fast), 0.99))
    slow = max(0.01, min(float(slow), 0.99))
    y, L, s0 = _ht_compact(x)
    core = _ht_core_torch(y, L, 12)
    tempReal2 = core["tempReal2"]
    out = torch.full_like(x, float("nan"))
    m = torch.zeros(N, dtype=x.dtype, device=x.device)
    prevPhase = torch.zeros(N, dtype=x.dtype, device=x.device)
    row_idx = torch.arange(N, device=x.device)
    for i in range(12, T):
        active = i < L
        tr = prevPhase - tempReal2[i]
        prevPhase = tempReal2[i]
        tr = torch.clamp(tr, min=1.0)
        alpha = torch.where(tr > 1.0, torch.clamp(fast / tr, min=slow),
                            torch.full_like(tr, fast))
        m = alpha * y[i] + (1 - alpha) * m
        if i >= 32:
            row = (s0 + i).clamp(max=T - 1)
            out[row, row_idx] = torch.where(active, m, out[row, row_idx])
    return out


def t_ts_HT_DCPERIOD(x):
    """希尔伯特变换主导周期 (对齐 talib.HT_DCPERIOD, 首个有效 32)"""
    t = _t()
    T, N = x.shape
    y, L, s0 = _ht_compact(x)
    core = _ht_core_torch(y, L, 12)
    period = core["period"]
    out = torch.full_like(x, float("nan"))
    smoothPeriod = torch.zeros(N, dtype=x.dtype, device=x.device)
    row_idx = torch.arange(N, device=x.device)
    for i in range(12, T):
        active = i < L
        smoothPeriod = 0.33 * period[i] + 0.67 * smoothPeriod
        if i >= 32:
            row = (s0 + i).clamp(max=T - 1)
            out[row, row_idx] = torch.where(active, smoothPeriod, out[row, row_idx])
    return out


def _ht_fourier(smoothPrice, spIdx, smoothPeriod):
    """平滑价格环的傅里叶实部/虚部 (对齐 C 的 DCPhase 前段)
    smoothPrice:  [50, N] 环缓冲
    spIdx:        当前槽 (共享标量)
    smoothPeriod: [N] 当前平滑周期
    返回 (realPart, imagPart) 各 [N]
    """
    t = _t()
    N = smoothPrice.shape[1]
    dtype = smoothPrice.dtype
    device = smoothPrice.device
    DCPeriodInt = torch.floor(smoothPeriod + 0.5).to(torch.int64)   # [N]
    ks = torch.arange(50, device=device).unsqueeze(1)               # [50,1]
    sp = torch.full((1, N), spIdx, dtype=torch.int64, device=device)
    idx = (sp - ks) % 50                                            # [50,N]
    col = torch.arange(N, device=device).unsqueeze(0).expand(50, N)
    v = smoothPrice[idx, col]                                       # [50,N]
    tr = ks.to(dtype) * (np.arctan(1.0) * 8.0) / DCPeriodInt.to(dtype).unsqueeze(0)
    mask = ks < DCPeriodInt.unsqueeze(0)
    realPart = torch.where(mask, torch.sin(tr) * v, torch.zeros_like(v)).sum(dim=0)
    imagPart = torch.where(mask, torch.cos(tr) * v, torch.zeros_like(v)).sum(dim=0)
    return realPart, imagPart


def _ht_dcphase_step(DCPhase, realPart, imagPart, smoothPeriod, rad2deg):
    """单步 DCPhase 更新 (DCPHASE/TRENDMODE 共享, 对齐 C)"""
    t = _t()
    cond1 = imagPart.abs() > 0.0
    cond2 = (~cond1) & (imagPart.abs() <= 0.01)
    newp = torch.where(cond1, torch.atan(realPart / imagPart) * rad2deg, DCPhase)
    adj = torch.where(realPart < 0.0, DCPhase - 90.0,
                      torch.where(realPart > 0.0, DCPhase + 90.0, DCPhase))
    DCPhase = torch.where(cond1, newp, torch.where(cond2, adj, DCPhase))
    DCPhase = DCPhase + 90.0 + 360.0 / smoothPeriod
    DCPhase = torch.where(imagPart < 0.0, DCPhase + 180.0, DCPhase)
    DCPhase = torch.where(DCPhase > 315.0, DCPhase - 360.0, DCPhase)
    return DCPhase


def t_ts_HT_DCPHASE(x):
    """希尔伯特变换主导相位 (对齐 talib.HT_DCPHASE, 首个有效 63)"""
    t = _t()
    T, N = x.shape
    y, L, s0 = _ht_compact(x)
    core = _ht_core_torch(y, L, 37)
    period = core["period"]
    smoothed = core["smoothed"]
    rad2deg = 180.0 / (4.0 * np.arctan(1.0))
    out = torch.full_like(x, float("nan"))
    smoothPeriod = torch.zeros(N, dtype=x.dtype, device=x.device)
    smoothPrice = torch.zeros(50, N, dtype=x.dtype, device=x.device)
    DCPhase = torch.zeros(N, dtype=x.dtype, device=x.device)
    row_idx = torch.arange(N, device=x.device)
    spIdx = 0
    for i in range(37, T):
        active = i < L
        smoothPeriod = 0.33 * period[i] + 0.67 * smoothPeriod
        smoothPrice[spIdx] = smoothed[i]
        realPart, imagPart = _ht_fourier(smoothPrice, spIdx, smoothPeriod)
        DCPhase = _ht_dcphase_step(DCPhase, realPart, imagPart, smoothPeriod, rad2deg)
        if i >= 63:
            row = (s0 + i).clamp(max=T - 1)
            out[row, row_idx] = torch.where(active, DCPhase, out[row, row_idx])
        spIdx += 1
        if spIdx > 49:
            spIdx = 0
    return out


def t_ts_HT_TRENDMODE(x):
    """希尔伯特变换趋势模式 (对齐 talib.HT_TRENDMODE: 0/1, warmup 0, 首个有效 63)"""
    t = _t()
    T, N = x.shape
    y, L, s0 = _ht_compact(x)
    core = _ht_core_torch(y, L, 37)
    period = core["period"]
    smoothed = core["smoothed"]
    rad2deg = 180.0 / (4.0 * np.arctan(1.0))
    deg2rad = 1.0 / rad2deg
    out = torch.zeros_like(x)                       # warmup 0 (talib int 0/1)
    smoothPeriod = torch.zeros(N, dtype=x.dtype, device=x.device)
    smoothPrice = torch.zeros(50, N, dtype=x.dtype, device=x.device)
    DCPhase = torch.zeros(N, dtype=x.dtype, device=x.device)
    prevDCPhase = torch.zeros(N, dtype=x.dtype, device=x.device)
    sine = torch.zeros(N, dtype=x.dtype, device=x.device)
    prevSine = torch.zeros(N, dtype=x.dtype, device=x.device)
    leadSine = torch.zeros(N, dtype=x.dtype, device=x.device)
    prevLeadSine = torch.zeros(N, dtype=x.dtype, device=x.device)
    iTrend1 = torch.zeros(N, dtype=x.dtype, device=x.device)
    iTrend2 = torch.zeros(N, dtype=x.dtype, device=x.device)
    iTrend3 = torch.zeros(N, dtype=x.dtype, device=x.device)
    daysInTrend = torch.zeros(N, dtype=torch.int64, device=x.device)
    row_idx = torch.arange(N, device=x.device)
    ks = torch.arange(50, device=x.device).unsqueeze(1)            # [50,1]
    ii = torch.full((1, N), 0, dtype=torch.int64, device=x.device)
    spIdx = 0
    for i in range(37, T):
        active = i < L
        smoothPeriod = 0.33 * period[i] + 0.67 * smoothPeriod
        smoothPrice[spIdx] = smoothed[i]
        prevDCPhase = DCPhase
        realPart, imagPart = _ht_fourier(smoothPrice, spIdx, smoothPeriod)
        DCPhase = _ht_dcphase_step(DCPhase, realPart, imagPart, smoothPeriod, rad2deg)
        prevSine = sine
        prevLeadSine = leadSine
        sine = torch.sin(DCPhase * deg2rad)
        leadSine = torch.sin((DCPhase + 45.0) * deg2rad)
        # 趋势线: sum_{k<DCPeriodInt} y[i-k] 再除以周期取平均 (对齐 C 的 iTrend 均值)
        DCPeriodInt = torch.floor(smoothPeriod + 0.5).to(torch.int64)  # [N]
        ii.fill_(i)
        idx_t = ii - ks                                          # [50,N]
        vmask = (idx_t >= 0) & (ks < DCPeriodInt.unsqueeze(0))
        yy = torch.where(vmask, y[idx_t.clamp(min=0), row_idx.unsqueeze(0).expand(50, N)],
                         torch.zeros_like(y[idx_t.clamp(min=0), row_idx.unsqueeze(0).expand(50, N)]))
        trsum = yy.sum(dim=0)
        avg = trsum / DCPeriodInt.to(x.dtype).clamp_min(1)
        trendline = (4.0 * avg + 3.0 * iTrend1 + 2.0 * iTrend2 + iTrend3) / 10.0
        iTrend3 = iTrend2
        iTrend2 = iTrend1
        iTrend1 = avg
        # 趋势判定 (对齐 C)
        trend = torch.ones(N, dtype=x.dtype, device=x.device)
        cross = ((sine > leadSine) & (prevSine <= prevLeadSine)) | \
                ((sine < leadSine) & (prevSine >= prevLeadSine))
        daysInTrend = torch.where(cross, torch.zeros_like(daysInTrend), daysInTrend)
        trend = torch.where(cross, torch.zeros_like(trend), trend)
        daysInTrend = daysInTrend + 1
        trend = torch.where(daysInTrend.to(x.dtype) < 0.5 * smoothPeriod,
                            torch.zeros_like(trend), trend)
        tempReal = DCPhase - prevDCPhase
        condp = (smoothPeriod != 0.0) & \
                (tempReal > 0.67 * 360.0 / smoothPeriod) & \
                (tempReal < 1.5 * 360.0 / smoothPeriod)
        trend = torch.where(condp, torch.zeros_like(trend), trend)
        tempReal = smoothPrice[spIdx]
        condt = (trendline != 0.0) & \
                ((tempReal - trendline).abs() / trendline.abs() >= 0.015)
        trend = torch.where(condt, torch.ones_like(trend), trend)
        if i >= 63:
            row = (s0 + i).clamp(max=T - 1)
            out[row, row_idx] = torch.where(active, trend, out[row, row_idx])
        spIdx += 1
        if spIdx > 49:
            spIdx = 0
    return out


# ============================================================
# AlphaMaster 映射补充算子 GPU 化 (阶段6.3 加速: 补齐 L0 搜索空间 GPU 覆盖率)
# 语义对齐 factor_engine 的 AlphaMaster 补充算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1):
#   - 一元算术算子 (sign/jump/max3/power/signed_log/sqrt/clip/sigmoid/tanh_squash/winsorize)
#     以默认参数被单参调用 (引擎 eval 表达式形式: power(child) 等), 数值对齐 pandas;
#   - 带窗时序算子 (ts_ArgMax/ts_ArgMin/ts_Product/ts_DecayLinear) 与无窗时序算子 (ts_Scale)
#     对齐引擎 pandas rolling/expanding 语义 (min_periods=1 前缀预热 / NaN 跳过)。
# ============================================================

def t_sign(x):
    """符号函数 (np.sign: NaN -> NaN; torch.sign(NaN)=0 需显式还原)"""
    return torch.where(torch.isnan(x), torch.full_like(x, float("nan")), torch.sign(x))


def t_jump(x):
    """因果 expanding zscore + tanh 软化 (对齐 factor_engine jump: 降低稀疏度)
    语义: expanding(mean/std, skipna, ddof=1), std=0 置 NaN, z=(x-mean)/std, tanh(z-1.5)。
    """
    t = _t()
    mask = ~torch.isnan(x)
    cnt = mask.cumsum(dim=0).to(x.dtype)                # 前缀非NaN计数
    xm = torch.where(mask, x, torch.zeros_like(x))
    s = xm.cumsum(dim=0)                                # 前缀和 (NaN 视作 0)
    mean = s / cnt.clamp_min(1)
    sumsq = (xm ** 2).cumsum(dim=0)                     # 前缀平方和
    var = (sumsq - cnt * mean ** 2) / (cnt - 1.0).clamp_min(1.0)
    std = torch.sqrt(var.clamp_min(0.0))
    std = torch.where(std.abs() > EPS, std, torch.full_like(std, float("nan")))  # replace(0, nan)
    std = torch.where(cnt >= 2, std, torch.full_like(std, float("nan")))         # ddof=1 需>=2样本
    z = (x - mean) / std
    return torch.tanh(z - 1.5)


def t_max3(x):
    """3 期滚动最大值 (含当前及前2期; 对齐 factor_engine max3 = rolling(3, min_periods=1).max())"""
    return _rolling_map(x, 3, 1, _ts_max_full, prefix_kind="max")


def t_power(x, a: float = 2.0):
    """带符号乘方: sign(x)*|x|^a (对齐 factor_engine power 默认 a=2.0)"""
    return torch.sign(x) * torch.abs(x) ** a


def t_signed_log(x):
    """带符号对数: sign(x)*log1p(|x|) (对齐 factor_engine signed_log)"""
    return torch.sign(x) * torch.log1p(torch.abs(x))


def t_sqrt(x):
    """带符号开方: sign(x)*sqrt(|x|) (对齐 factor_engine sqrt)"""
    return torch.sign(x) * torch.sqrt(torch.abs(x))


def t_clip(x, lo: float = -3.0, hi: float = 3.0):
    """固定裁剪 (对齐 factor_engine clip 默认 lo=-3, hi=3; clamp 传播 NaN)"""
    return torch.clamp(x, lo, hi)


def t_sigmoid(x):
    """sigmoid 压缩到 (0,1) (对齐 factor_engine sigmoid)"""
    return 1.0 / (1.0 + torch.exp(-x))


def t_tanh_squash(x):
    """tanh 压缩到 (-1,1) (对齐 factor_engine tanh_squash)"""
    return torch.tanh(x)


def t_winsorize(x, lo: float = -3.0, hi: float = 3.0):
    """去极值(算子形态): 裁剪到 [lo,hi] (对齐 factor_engine winsorize 默认 lo=-3, hi=3)"""
    return torch.clamp(x, lo, hi)


def _ts_argpos(x: torch.Tensor, n: int, want_max: bool) -> torch.Tensor:
    """滚动窗口内最大/最小位置 (归一化 [0,1], 0=最早, 1=最近)

    对齐 factor_engine ts_ArgMax/ts_ArgMin:
      - rolling(n, min_periods=1): 预热区用前缀窗口, 全窗口区用固定 n 窗口;
      - np.argmax/argmin 的 NaN 语义: NaN 视为最大/最小 (占位为 ±inf 使其被选中);
      - 归一化分母 = max(len-1, 1), len 为实际窗口长度;
      - 窗口内无非NaN (计数<min_periods=1) -> NaN (对齐 pandas rolling 计数规则)。
    """
    t = _t()
    T, N = x.shape
    n = max(1, min(int(n), T))
    fill = float("inf") if want_max else -float("inf")
    xf = torch.where(torch.isnan(x), torch.full_like(x, fill), x)
    out = torch.full((T, N), float("nan"), dtype=x.dtype, device=x.device)

    # 完整窗口区 (t >= n-1): 一次性 unfold
    if T >= n:
        win = xf.unfold(0, n, 1)                        # [T-n+1, N, n]
        idx = torch.argmax(win, dim=2) if want_max else torch.argmin(win, dim=2)
        cnt = (~torch.isnan(x.unfold(0, n, 1))).sum(dim=2)  # 非NaN计数 (用原值 x 而非 xf)
        denom = float(max(n - 1, 1))
        vals = idx.to(x.dtype) / denom
        out[n - 1:, :] = torch.where(cnt >= 1, vals, torch.full_like(vals, float("nan")))

    # 预热区 (t < n-1): 前缀窗口, 分母随实际窗口长度变化
    for t_idx in range(min(n - 1, T)):
        seg = xf[:t_idx + 1, :]                         # [t_idx+1, N]
        idx = torch.argmax(seg, dim=0) if want_max else torch.argmin(seg, dim=0)
        cnt = (~torch.isnan(x[:t_idx + 1])).sum(dim=0)  # 非NaN计数 (用原值 x 而非 xf)
        denom = float(max(t_idx, 1))
        vals = idx.to(x.dtype) / denom
        out[t_idx, :] = torch.where(cnt >= 1, vals, torch.full_like(vals, float("nan")))
    return out


def t_ts_ArgMax(x, n):
    """n 期窗口内最大值的位置 (归一化 [0,1]; 对齐 factor_engine ts_ArgMax)"""
    return _ts_argpos(x, int(n), want_max=True)


def t_ts_ArgMin(x, n):
    """n 期窗口内最小值的位置 (归一化 [0,1]; 对齐 factor_engine ts_ArgMin)"""
    return _ts_argpos(x, int(n), want_max=False)


def t_ts_Product(x, n):
    """n 期滑动乘积 (对数累加避免数值爆炸: exp(sum(log1p(clip(x,-0.999)))).clip(-10,10) - 1
    对齐 factor_engine ts_Product: 滚动和跳过 NaN, min_periods=1 前缀预热)
    """
    x_safe = torch.clamp(x, min=-0.999)
    log_x = torch.log1p(x_safe)
    log_sum = _rolling_map(log_x, n, 1, _ts_sum_full, prefix_kind="sum")
    log_sum = torch.clamp(log_sum, -10.0, 10.0)
    return torch.expm1(log_sum)


def t_ts_DecayLinear(x, n):
    """n 期线性衰减加权平均 (近期权重高): 权重 = [1,2,...,n]/sum
    对齐 factor_engine ts_DecayLinear (复用 _rolling_weighted_mean: 最旧乘 weights[0]=最小权重,
    最近乘 weights[-1]=最大权重; 窗口内任一 NaN 传播 NaN)
    """
    n = int(n)
    weights = np.arange(1, n + 1, dtype=np.float64)
    weights = weights / weights.sum()
    return _rolling_weighted_mean(x, n, weights)


def t_ts_Scale(x):
    """沿时间轴缩放到单位 L1 范数 (因果累积和): x[t]/sum(|x[1..t]|)
    对齐 factor_engine ts_Scale: pandas cumsum 跳过 NaN (NaN 位置输出 NaN, 后续继续累计),
    abs_sum 为 0 时置 NaN。
    """
    t = _t()
    nan = torch.full_like(x, float("nan"))
    # cumsum 把 NaN 视作 0 累计, 再在 NaN 位置还原 NaN (对齐 pandas cumsum 输出)
    abs_sum = torch.cumsum(torch.where(torch.isnan(x), torch.zeros_like(x), x.abs()), dim=0)
    abs_sum = torch.where(torch.isnan(x), nan, abs_sum)
    abs_sum = torch.where(abs_sum.abs() > EPS, abs_sum, nan)   # replace(0, nan)
    return x / abs_sum


# ============================================================
# 因子侧 3.2: AlphaMaster 补充技术类参数化基类 (能挪进来的挪进来)
# 对齐 factor_engine 对应 ts_* 算子语义; 已纳入 GP_BASE_LEAF L2 基类叶子
# ============================================================

def t_ts_PricePosition(x, n):
    """n 期区间位置 = (Close - min_n) / (max_n - min_n) (对齐 factor_engine ts_PricePosition:
    rolling min/max min_periods=1, span 为 0 置 NaN)"""
    mn = _rolling_map(x, n, 1, _ts_min_full, prefix_kind="min")
    mx = _rolling_map(x, n, 1, _ts_max_full, prefix_kind="max")
    span = torch.where((mx - mn) == 0, torch.full_like(mx, float("nan")), mx - mn)
    return (x - mn) / span


def t_ts_Autocorr(x, n, lag=1):
    """n 期收益的 lag 阶自相关 (对齐 factor_engine ts_Autocorr: pct_change 后
    rolling(n, min_periods=2) 窗口内 np.corrcoef(w[:-lag], w[lag:]), 窗口含 NaN 输出 NaN,
    常数序列 (分母为 0) 输出 NaN)"""
    ret = t_ts_PctChange(x, 1)
    t = _t()
    T, N = ret.shape
    n = max(2, min(int(n), T))
    lag = max(1, int(lag))
    out = torch.full((T, N), float("nan"), dtype=ret.dtype, device=ret.device)
    if n - lag >= 2 and T >= n:
        win = ret.unfold(0, n, 1)              # [T-n+1, N, n]
        a = win[..., :n - lag]                 # 滞后阶左半
        b = win[..., lag:]                     # 滞后阶右半
        cnt = (~torch.isnan(win)).sum(-1)
        has_nan = torch.isnan(win).any(-1)
        ma = a.mean(-1, keepdim=True)
        mb = b.mean(-1, keepdim=True)
        ca = a - ma
        cb = b - mb
        cov = (ca * cb).sum(-1)
        va = (ca * ca).sum(-1)
        vb = (cb * cb).sum(-1)
        corr = cov / torch.sqrt(va * vb)
        valid = (cnt >= 2) & (~has_nan) & (va > 0) & (vb > 0)
        out[n - 1:] = torch.where(valid, corr, torch.full_like(corr, float("nan")))
    return out


def t_ts_TypicalDev(o, h, l, c, n):
    """典型价 (H+L+C)/3 偏离其 n 期 MA (对齐 factor_engine ts_TypicalDev:
    (typical - MA) / MA, MA 为 0 置 NaN, rolling min_periods=1)"""
    typical = (h + l + c) / 3.0
    ma = _rolling_map(typical, n, 1, _ts_mean_full, prefix_kind="mean")
    denom = torch.where(ma == 0, torch.full_like(ma, float("nan")), ma)
    return (typical - ma) / denom


def _shift_fillna(x):
    """x.shift(1).fillna(x) 的 torch 实现

    pandas 的 fillna(x) 会把所有 NaN 空位 (含首行移位空位, 以及因源数据
    本身含 NaN 而产生的空位) 都用同位置原值填充, 即 prev[k] = x[k-1] (非 NaN 时)
    否则 x[k]。仅用 cat([x[:1], x[:-1]]) 只覆盖首行, 需再按 NaN 掩码回填。
    """
    prev = torch.cat([x[:1], x[:-1]], dim=0)
    return torch.where(torch.isnan(prev), x, prev)


def t_ts_DmiDiff(h, l, c, n):
    """DMI 差值 DI+ - DI- (对齐 factor_engine ts_DmiDiff: shift 首值用自身,
    TR 取三差最大值, TR 均值 0 置 NaN, DI 差 clip(-1,1), rolling min_periods=1)"""
    prev_h = _shift_fillna(h)
    prev_l = _shift_fillna(l)
    prev_c = _shift_fillna(c)
    dm_pos = (h - prev_h).clamp_min(0)
    dm_neg = (prev_l - l).clamp_min(0)
    tr = torch.maximum(torch.maximum(h - l, (h - prev_c).abs()), (l - prev_c).abs())
    tr_mean = _rolling_map(tr, n, 1, _ts_mean_full, prefix_kind="mean")
    denom = torch.where(tr_mean == 0, torch.full_like(tr_mean, float("nan")), tr_mean)
    di_pos = _rolling_map(dm_pos, n, 1, _ts_mean_full, prefix_kind="mean") / denom
    di_neg = _rolling_map(dm_neg, n, 1, _ts_mean_full, prefix_kind="mean") / denom
    return (di_pos - di_neg).clamp(-1, 1)


def _pandas_ewm_keep(x, span):
    """pandas ewm(span, adjust=False, ignore_na=False).mean() 的精确 torch 实现

    状态机对齐 pandas/_libs/window/aggregations.pyx 的 ewm 函数 (normalize=True):
      - s(即 old_wt) 每步乘 b=(1-alpha), 观测后复位 1; NaN 步只乘不复位
      - 观测: y = (s*y + nw*cur)/(s+nw); com==1 (span=3) 特判 nw=1-s;
        y==cur 常数序列跳过加权更新 (避免数值误差, 仍复位 s)
      - NaN: y 保持; 首个有效观测前 y 为 NaN (NaN 传播)
    torch 无关联扫描, 采用"时间维循环 + N 维向量化"。
    """
    t = _t()
    alpha = 2.0 / (span + 1.0)
    b = 1.0 - alpha
    com = (span - 1.0) / 2.0
    is_com1 = abs(com - 1.0) < 1e-12
    T, N = x.shape
    out = torch.full_like(x, float("nan"))
    if T == 0:
        return out
    y = torch.full((N,), float("nan"), dtype=x.dtype, device=x.device)
    s = torch.ones((N,), dtype=x.dtype, device=x.device)
    for i in range(T):
        cur = x[i]
        nan_mask = torch.isnan(cur)
        obs = ~nan_mask
        y_ok = ~torch.isnan(y)
        # 每步乘 b (仅 y 非 NaN 时, 与 pandas `if weighted == weighted` 一致)
        s = torch.where(y_ok, s * b, s)
        # y==cur 常数序列: pandas 跳过加权更新 (但仍复位 s)
        const_mask = y_ok & obs & (y == cur)
        if is_com1:
            nw = 1.0 - s
            y_new = (s * y + nw * cur) / (s + nw)
        else:
            y_new = (s * y + alpha * cur) / (s + alpha)
        update = y_ok & obs & ~const_mask
        y = torch.where(update, y_new, y)
        # y 为 NaN 且观测 → 首个有效值 y=cur
        y = torch.where(y_ok, y, torch.where(obs, cur, y))
        # 观测后 s 复位 1
        s = torch.where(obs, torch.ones_like(s), s)
        out[i] = y
    return out


def t_ts_Trix(x, n):
    """TRIX: 三重 ewm(span=n, adjust=False) 后的单步变化率 (对齐 factor_engine ts_Trix:
    e3.shift(1).fillna(e3), 分母 prev.abs() 0 置 NaN)"""
    n = max(1, min(int(n), x.shape[0]))
    e1 = _pandas_ewm_keep(x, n)
    e2 = _pandas_ewm_keep(e1, n)
    e3 = _pandas_ewm_keep(e2, n)
    prev = _shift_fillna(e3)               # shift(1).fillna(e3)
    denom = torch.where(prev.abs() == 0, torch.full_like(prev, float("nan")), prev.abs())
    return (e3 - prev) / denom


def t_ts_AmihudIlliq(x, v, n):
    """Amihud 非流动性 = log1p(mean(|ret|/volume, n)) (对齐 factor_engine ts_AmihudIlliq:
    volume 0 置 NaN, rolling min_periods=1, 结果 clip 下界 0)"""
    ret = t_ts_PctChange(x, 1).abs()
    vol_safe = torch.where(v == 0, torch.full_like(v, float("nan")), v)
    illiq = ret / vol_safe
    m = _rolling_map(illiq, n, 1, _ts_mean_full, prefix_kind="mean")
    return torch.log1p(m.clamp_min(0))


def t_ts_KyleLambda(x, v, n):
    """Kyle lambda 近似 = cov(|ret|, sign(ret)*vol) / var(sign(ret)*vol) 窗口内
    (对齐 factor_engine ts_KyleLambda: cov 样本 ddof=1, var 总体 ddof=0, var<=1e-9 置 NaN,
    窗口含 NaN 置 NaN; min_periods=2)"""
    t = _t()
    T, N = x.shape
    n = max(2, min(int(n), T))
    ret = t_ts_PctChange(x, 1)
    abs_ret = ret.abs()
    signed_vol = torch.sign(ret) * v
    out = torch.full((T, N), float("nan"), dtype=x.dtype, device=x.device)
    if T >= n:
        win_abs = abs_ret.unfold(0, n, 1)
        win_sv = signed_vol.unfold(0, n, 1)
        has_nan = torch.isnan(win_abs).any(-1) | torch.isnan(win_sv).any(-1)
        cnt = (~torch.isnan(win_abs)).sum(-1)
        ma = win_abs.mean(-1, keepdim=True)
        ms = win_sv.mean(-1, keepdim=True)
        ca = win_abs - ma
        cs = win_sv - ms
        cov = (ca * cs).sum(-1) / (n - 1)      # 样本协方差 ddof=1 (对齐 np.cov)
        var = (cs * cs).sum(-1) / n            # 总体方差 ddof=0 (对齐 np.var)
        kyle = cov / var
        valid = (cnt >= 2) & (~has_nan) & (var > 1e-9)
        out[n - 1:] = torch.where(valid, kyle, torch.full_like(kyle, float("nan")))
    return out


def t_ts_CMF(h, l, c, v, n):
    """Chaikin Money Flow = sum(MFV,n)/sum(vol,n) (对齐 factor_engine ts_CMF:
    (H-L) 为 0 置 NaN, 分母 sum 0 置 NaN, clip(-1,1), rolling min_periods=1)"""
    hl = torch.where((h - l) == 0, torch.full_like(h, float("nan")), h - l)
    mf_mul = ((c - l) - (h - c)) / hl
    mfv_sum = _rolling_map(mf_mul * v, n, 1, _ts_sum_full, prefix_kind="sum")
    vol_sum = _rolling_map(v, n, 1, _ts_sum_full, prefix_kind="sum")
    denom = torch.where(vol_sum == 0, torch.full_like(vol_sum, float("nan")), vol_sum)
    return (mfv_sum / denom).clamp(-1, 1)


def _ts_slope_full(win):
    """沿窗口最后维的线性回归斜率, NaN 传播语义 (对齐 factor_engine ts_ADLineSlope 的 _slope:
    窗口内任一 NaN 结果即 NaN; 回归轴为 0..n-1 的等距时间索引, 斜率与原点无关)"""
    t = _t()
    mask = ~torch.isnan(win)
    any_nan = (~mask).any(dim=2)
    w_len = win.shape[2]
    idx = torch.arange(1, w_len + 1, dtype=win.dtype, device=win.device)
    xmean = idx.mean()
    xc = idx - xmean
    xvar = (xc ** 2).sum()
    safe = torch.where(mask, win, torch.zeros_like(win))
    cnt = mask.sum(dim=2).clamp_min(1)
    ymean = safe.sum(dim=2) / cnt
    yc = torch.where(mask, win - ymean.unsqueeze(2), torch.zeros_like(win))
    slope = (yc * xc.unsqueeze(0).unsqueeze(0)).sum(dim=2) / xvar
    return torch.where(any_nan, torch.full_like(slope, float("nan")), slope)


def t_ts_ADLineSlope(o, h, l, c, v, n):
    """A/D line 斜率 = cumsum(MFV) 的 n 期线性回归斜率 (对齐 factor_engine ts_ADLineSlope:
    (H-L) 0 置 NaN, cumsum 跳过 NaN 且原 NaN 位置保持 NaN,
    rolling(n, min_periods=2) 斜率, 窗口含 NaN 结果 NaN)"""
    hl = torch.where((h - l) == 0, torch.full_like(h, float("nan")), h - l)
    mf_mul = ((c - l) - (h - c)) / hl
    raw = mf_mul * v
    ad_line = torch.cumsum(torch.nan_to_num(raw, nan=0.0), dim=0)
    ad_line = torch.where(torch.isnan(raw), torch.full_like(ad_line, float("nan")), ad_line)
    return _rolling_map(ad_line, n, 2, _ts_slope_full)


# ============================================================
# RL 因子挖掘收尾补充算子 (阶段 P0 收尾: RL 解码表达式用到的 18 个 ts_* GPU 补齐)
# 语义逐条对齐 factor_engine 对应 ts_* 函数 (窗口 / min_periods / NaN / clip 等)
# ============================================================

def _ts_log_ratio2(x: torch.Tensor, denom: torch.Tensor) -> torch.Tensor:
    """log(x/denom)^2, denom==0 置 NaN (对齐 pandas replace(0,nan) 后 np.log 的语义)"""
    safe = torch.where(denom != 0.0, denom, torch.full_like(denom, float("nan")))
    return torch.log(x / safe) ** 2


def _ts_rs_bar(h: torch.Tensor, l: torch.Tensor, c: torch.Tensor, o: torch.Tensor) -> torch.Tensor:
    """Rogers-Satchell 波动项: ln(H/C)*ln(H/O)+ln(L/C)*ln(L/O) (各分母 0 置 NaN)"""
    sc = torch.where(c != 0.0, c, torch.full_like(c, float("nan")))
    so = torch.where(o != 0.0, o, torch.full_like(o, float("nan")))
    return (torch.log(h / sc) * torch.log(h / so)
            + torch.log(l / sc) * torch.log(l / so))


def _ts_vol_est_log1p(bar: torch.Tensor, n: int) -> torch.Tensor:
    """波动率估计量公共出口: rolling(n, min_periods=1).mean() -> log1p(sqrt(clip0))
    对齐引擎各波动率估计量: gk_mean.clip(lower=0).apply(np.sqrt) 后 np.log1p"""
    m = _rolling_map(bar, n, 1, _ts_mean_full, prefix_kind="mean")
    return torch.log1p(m.clamp_min(0.0).sqrt())


def t_ts_GKVol(o, h, l, c, n=20):
    """Garman-Klass 波动率估计量: 0.5*ln(H/L)^2 - (2ln2-1)*ln(C/O)^2, 滚动均值取sqrt"""
    n = max(1, min(int(n), c.shape[0]))
    ln2 = np.log(2.0)
    hl = _ts_log_ratio2(h, l)
    co = _ts_log_ratio2(c, o)
    gk_bar = (0.5 * hl - (2 * ln2 - 1) * co).clamp_min(0.0)
    return _ts_vol_est_log1p(gk_bar, n)


def t_ts_ParkinsonVol(h, l, n=20):
    """Parkinson 波动率估计量: (1/(4ln2))*(ln(H/L))^2, 滚动均值取sqrt"""
    n = max(1, min(int(n), h.shape[0]))
    ln2 = np.log(2.0)
    pk_bar = (1.0 / (4 * ln2)) * _ts_log_ratio2(h, l)
    return _ts_vol_est_log1p(pk_bar, n)


def t_ts_YangZhangVol(o, h, l, c, n=20):
    """Yang-Zhang 波动率估计量 (等权简化): (overnight + open + RS)/3, 滚动均值取sqrt"""
    n = max(1, min(int(n), o.shape[0]))
    pc = _shift_fillna(c)                       # close.shift(1).fillna(close)
    overnight = _ts_log_ratio2(o, pc)
    open_bar = _ts_log_ratio2(o, c)
    rs_bar = _ts_rs_bar(h, l, c, o)
    yz_bar = (overnight + open_bar + rs_bar) / 3.0
    return _ts_vol_est_log1p(yz_bar, n)


def t_ts_RSVol(o, h, l, c, n=20):
    """Rogers-Satchell 波动率估计量: ln(H/C)*ln(H/O)+ln(L/C)*ln(L/O), 滚动均值取sqrt"""
    n = max(1, min(int(n), o.shape[0]))
    rs_bar = _ts_rs_bar(h, l, c, o)
    return _ts_vol_est_log1p(rs_bar, n)


def _ts_trend_strength_full(win):
    """win: [M, N, w] -> 每窗口的 SLOPE_n * R^2 (NaN 传播, 对齐引擎 _slope_r2)"""
    t = _t()
    w = win.shape[2]
    idx = torch.arange(w, dtype=win.dtype, device=win.device)
    xm = idx.mean()
    xc = idx - xm
    wmean = win.mean(dim=2)                      # NaN 传播 (对齐 numpy w.mean())
    slope = ((win - wmean.unsqueeze(2)) * xc.unsqueeze(0).unsqueeze(0)).sum(dim=2) / (xc ** 2).sum()
    pred = wmean.unsqueeze(2) + slope.unsqueeze(2) * xc.unsqueeze(0).unsqueeze(0)
    ss_res = ((win - pred) ** 2).sum(dim=2)
    ss_tot = ((win - wmean.unsqueeze(2)) ** 2).sum(dim=2)
    r2 = torch.where(ss_tot > 1e-9, 1.0 - ss_res / ss_tot, torch.zeros_like(ss_tot))
    return slope / (wmean + 1e-9) * torch.clamp(r2, 0.0, 1.0)


def t_ts_TrendStrength(x, n=50):
    """趋势强度 = SLOPE_n * R^2 (斜率按价位归一乘拟合优度; 对齐引擎 ts_TrendStrength
    rolling(n, min_periods=2).apply, 预热区用短窗口, 窗口含 NaN 结果 NaN)"""
    n = max(2, min(int(n), x.shape[0]))
    return _rolling_map(x, n, 2, _ts_trend_strength_full)


def _ts_hurst_full(win):
    """win: [M, N, w] -> Hurst (R/S 法: log(R/S)/log(w), 映射到 [-1,1], 对齐引擎 _hurst)"""
    t = _t()
    w = win.shape[2]
    wmean = win.mean(dim=2)                      # NaN 传播
    centered = win - wmean.unsqueeze(2)
    cumdev = torch.cumsum(centered, dim=2)
    R = cumdev.max(dim=2).values - cumdev.min(dim=2).values
    S = torch.std(win, dim=2, unbiased=False)    # np.std 默认 ddof=0
    h = torch.log(R / S) / float(np.log(w))
    raw = 2.0 * h - 1.0
    # Python min/max 的 NaN 口径: min(1.0, nan) 返回 1.0 -> 窗口含 NaN 时结果恒 1.0
    # (对齐引擎 _hurst 的 max(-1.0, min(1.0, v)) 在 NaN 下的真实行为, torch.clamp 需显式还原)
    out = torch.where(torch.isnan(raw), torch.ones_like(raw), torch.clamp(raw, -1.0, 1.0))
    out = torch.where((R < 1e-9) | (S < 1e-9), torch.zeros_like(out), out)
    return out


def t_ts_Hurst(x, n=50):
    """Hurst 指数 (R/S法简化): 收益的 rolling(n, min_periods=2).apply(_hurst)"""
    ret = t_ts_PctChange(x, 1)
    n = max(2, min(int(n), ret.shape[0]))
    return _rolling_map(ret, n, 2, _ts_hurst_full)


def _ts_fractal_dim_full(win):
    """win: [M, N, w] -> 分形维: (max-min)/(mean_abs_diff*sqrt(w)), 映射到 [-1,1]"""
    t = _t()
    w = win.shape[2]
    rng = win.max(dim=2).values - win.min(dim=2).values
    mad = (win[:, :, 1:] - win[:, :, :-1]).abs().mean(dim=2)
    frac = rng / (mad * float(np.sqrt(w)) + 1e-9)
    raw = frac / 3.0 * 2.0 - 1.0
    # 与 t_ts_Hurst 同款: 对齐引擎 _fd 的 Python min/max NaN 口径 (窗口含 NaN 结果恒 1.0)
    return torch.where(torch.isnan(raw), torch.ones_like(raw), torch.clamp(raw, -1.0, 1.0))


def t_ts_FractalDim(x, n=30):
    """分形维: close 的 rolling(n, min_periods=2).apply(_fd), 窗口含 NaN 结果 NaN"""
    n = max(2, min(int(n), x.shape[0]))
    return _rolling_map(x, n, 2, _ts_fractal_dim_full)


def _ts_ret_entropy_full(win):
    """win: [M, N, w] -> 收益符号三分箱香农熵 (对齐引擎 _entropy: NaN 元素在三箱内均不计数)"""
    t = _t()
    p_pos = (win > 0).to(win.dtype).mean(dim=2)
    p_neg = (win < 0).to(win.dtype).mean(dim=2)
    p_zero = (win == 0).to(win.dtype).mean(dim=2)
    h = torch.zeros_like(p_pos)
    for p in (p_pos, p_neg, p_zero):
        h = h - torch.where(p > 0, p * torch.log(p), torch.zeros_like(p))
    return torch.clamp(h / float(np.log(3.0)), 0.0, 1.0)


def t_ts_RetEntropy(x, n=20):
    """收益符号的 n 期滚动香农熵 (三分箱: 正/负/零), 归一化到 [0,1]"""
    ret = t_ts_PctChange(x, 1)
    n = max(2, min(int(n), ret.shape[0]))
    return _rolling_map(ret, n, 2, _ts_ret_entropy_full)


def t_ts_KeltnerPos(c, h, l, n=20):
    """Keltner 通道位置: (close-lower)/(upper-lower), mid=EMA_n, range=EMA_n(EMA14(TR))
    对齐引擎 ts_KeltnerPos (pandas ewm(span, adjust=False), TR 首行含当前K线)"""
    n = max(1, min(int(n), c.shape[0]))
    mid = _pandas_ewm_keep(c, n)
    pc = _shift_fillna(c)                         # close.shift(1).fillna(close)
    tr = torch.maximum(torch.maximum(h - l, (h - pc).abs()), (l - pc).abs())
    atr = _pandas_ewm_keep(tr, 14)
    rng = _pandas_ewm_keep(atr, n)
    upper = mid + 2.0 * rng
    lower = mid - 2.0 * rng
    denom = torch.where((upper - lower) == 0.0, torch.full_like(upper, float("nan")), upper - lower)
    return ((c - lower) / denom).clamp(0.0, 1.0)


def _ts_ichimoku_dev(h, l, n):
    """Ichimoku 基准/转换线偏离: (high - (max(h,n)+min(l,n))/2) / 该中线, 中线 0 置 NaN"""
    hh = _rolling_map(h, n, 1, _ts_max_full, prefix_kind="max")
    ll = _rolling_map(l, n, 1, _ts_min_full, prefix_kind="min")
    kijun = (hh + ll) / 2.0
    denom = torch.where(kijun == 0.0, torch.full_like(kijun, float("nan")), kijun)
    return (h - kijun) / denom


def t_ts_IchimokuKijun(h, l, n=26):
    """close(实为high) 相对 Kijun-sen(26期高低价中值) 偏离 (对齐引擎 ts_IchimokuKijun)"""
    return _ts_ichimoku_dev(h, l, int(n))


def t_ts_IchimokuTenkan(h, l, n=9):
    """close(实为high) 相对 Tenkan-sen(9期高低价中值) 偏离 (对齐引擎 ts_IchimokuTenkan)"""
    return _ts_ichimoku_dev(h, l, int(n))


def t_ts_SuperTrend(h, l, c, n=14):
    """SuperTrend 方向标志 {-1, 0, +1} (对齐引擎 ts_SuperTrend 简化递推:
    atr=rolling(n, min_periods=1).mean(), band=mid±1.5*atr, c 穿越前一时点带则翻转方向)"""
    t = _t()
    n = max(1, min(int(n), c.shape[0]))
    T, N = c.shape
    pc = _shift_fillna(c)
    tr = torch.maximum(torch.maximum(h - l, (h - pc).abs()), (l - pc).abs())
    atr = _rolling_map(tr, n, 1, _ts_mean_full, prefix_kind="mean")
    mid = (h + l) / 2.0
    upper = mid + 1.5 * atr
    lower = mid - 1.5 * atr
    out = torch.zeros_like(c)                     # 引擎 direction[0] = 0
    if T > 1:
        direction = torch.zeros(N, dtype=c.dtype, device=c.device)
        prev_upper = upper[0].clone()
        prev_lower = lower[0].clone()
        for t_idx in range(1, T):
            flip_up = c[t_idx] > prev_upper
            flip_down = c[t_idx] < prev_lower
            direction = direction.clone()
            direction[flip_up] = 1.0
            direction[flip_down] = -1.0
            out[t_idx] = direction
            prev_upper = upper[t_idx]
            prev_lower = lower[t_idx]
    return out


def t_ts_Cov(a, b, n):
    """n期滚动协方差 (对齐引擎 ts_Cov: pandas rolling(n, min_periods=2).cov, ddof=1)"""
    return _rolling_cov(a, b, n)


def _ts_quantile_full(win, q):
    """win: [M, N, w] -> 滚动分位数 (pandas rolling.quantile 线性插值口径, NaN 跳过)"""
    t = _t()
    flat = win.reshape(-1, win.shape[2])
    mask = ~torch.isnan(flat)
    cnt = mask.sum(dim=1).to(flat.dtype).clamp_min(1)
    xf = torch.where(mask, flat, torch.full_like(flat, float("inf")))
    s = torch.sort(xf, dim=1, stable=True).values    # NaN 用 inf 占位排末尾
    pos = (cnt - 1.0) * float(q)                     # 线性插值位置
    lo = torch.floor(pos).clamp(min=0).to(torch.long)
    hi = torch.ceil(pos).to(torch.long)
    hi = torch.minimum(hi, (cnt - 1.0).to(torch.long))
    v_lo = s.gather(1, lo.unsqueeze(1)).squeeze(1)
    v_hi = s.gather(1, hi.unsqueeze(1)).squeeze(1)
    wh = pos - pos.floor()
    out = v_lo * (1.0 - wh) + v_hi * wh
    return out.reshape(win.shape[0], win.shape[1])


def t_ts_Quantile(x, n, q=0.5):
    """n期滚动分位数 (对齐引擎 ts_Quantile: pandas rolling(n, min_periods=2).quantile(q),
    q=0.5 即中位数)"""
    n = max(2, min(int(n), x.shape[0]))
    return _rolling_map(x, n, 2, lambda win: _ts_quantile_full(win, float(q)))


def t_ts_MACD_HIST(x, fast=12, slow=26, signal=9):
    """MACD 柱状图 = DIF - 信号线 (对齐 talib.MACD[2]: 快慢EMA 同 t_ts_MACD_DIF 的 compacted
    递推; 信号线种子 = 首 signal 个 DIF 均值, 之后按 k=2/(signal+1) 递推; 输出起点同 DIF)"""
    t = _t()
    fast = max(1, int(fast)); slow = max(1, int(slow)); signal = max(1, int(signal))
    if slow < fast:
        fast, slow = slow, fast
    y, L, s0 = _ht_compact(x)
    T, N = x.shape
    fastK = 2.0 / (float(fast) + 1.0)
    slowK = 2.0 / (float(slow) + 1.0)
    slow_seed = torch.nanmean(y[0:slow], dim=0)
    fast_seed = torch.nanmean(y[slow - fast:slow], dim=0)
    s = torch.full((N,), slow - 1, dtype=torch.long, device=x.device)
    fastEMA = _linear_recurrence(y, fastK, s, fast_seed)
    slowEMA = _linear_recurrence(y, slowK, s, slow_seed)
    dif = fastEMA - slowEMA
    # 信号线: 种子 = 首 signal 个 DIF 均值 (对齐 ta_MACD prevSignal 累计)
    signalK = 2.0 / (float(signal) + 1.0)
    sig_seed = torch.nanmean(dif[slow - 1:slow - 1 + signal], dim=0)
    s_sig = torch.full((N,), slow + signal - 2, dtype=torch.long, device=x.device)
    dea = _linear_recurrence(dif, signalK, s_sig, sig_seed)
    hist = dif - dea
    # 输出从 compacted slow+signal-2 起, 映射回绝对索引 (与 t_ts_MACD_DIF 同起点)
    out = torch.full_like(x, float("nan"))
    start_i = slow + signal - 2
    iar = torch.arange(T, device=x.device).unsqueeze(1)     # [T,1]
    abs_row = s0.unsqueeze(0) + iar                         # [T,N]
    valid = (iar >= start_i) & (iar < L.unsqueeze(0)) & (abs_row < T)
    if bool(valid.any().item()):
        col_idx = torch.arange(N, device=x.device).unsqueeze(0).expand(T, N)[valid]
        out[abs_row[valid], col_idx] = hist[valid]
    return out


def t_ts_KDJ_D(h, l, c, fastk=9, slowk=3, slowd=3):
    """KDJ D值 (对齐 talib.STOCH[1]: K=SMA(rawK,slowk), D=SMA(K,slowd),
    输出从 s0+fastk+slowk+slowd-3 起; 仿 t_ts_KDJ_K)"""
    raw = _ts_stoch_raw(h, l, c, fastk)
    k = t_ts_SMA(raw, slowk)
    d = t_ts_SMA(k, slowd)
    return _mask_first_per_col(d, fastk + slowk + slowd - 3, _first_non_nan(c))


def t_ts_BOLL_WIDTH(x, n=20, nbdev=2):
    """布林带宽度 = (upper-lower)/mid (对齐引擎 ts_BOLL_WIDTH: talib.BBANDS 口径,
    |mid|<=1e-9 置 NaN)"""
    n = max(1, min(int(n), x.shape[0]))
    mid = t_ts_SMA(x, n)
    sd = _rolling_map(x, n, n, _ts_pop_std_full)
    upper = mid + nbdev * sd
    lower = mid - nbdev * sd
    mid_safe = torch.where(mid.abs() > 1e-9, mid, torch.full_like(mid, float("nan")))
    return (upper - lower) / mid_safe


def t_ts_SAR_DIST(c, h, l, af=0.02, max_af=0.2):
    """close 相对抛物线SAR的归一化距离 = (close - SAR) / close (对齐引擎 ts_SAR_DIST:
    SAR 用现有 t_ts_SAR, close==0 置 NaN)"""
    sar = t_ts_SAR(h, l, af, max_af)
    close_safe = torch.where(c != 0.0, c, torch.full_like(c, float("nan")))
    return (c - sar) / close_safe


# ============================================================
# 算子注册表 (供编译/求值器查找)
# ============================================================

# 一元/二元/三元算术算子 (按名称)
TORCH_ARITH: Dict[str, Callable] = {
    "add": t_add, "sub": t_sub, "mul": t_mul, "div": t_div, "abs": t_abs,
    # RL 解码三目算子 (阶段 P0: cond>0 取 a, 否则取 b)
    "gate": t_gate, "if_gt": t_if_gt,
    # AlphaMaster 映射补充一元算子 (阶段6.3: 补齐 GPU 覆盖率)
    "sign": t_sign, "jump": t_jump, "max3": t_max3, "power": t_power,
    "signed_log": t_signed_log, "sqrt": t_sqrt, "clip": t_clip,
    "sigmoid": t_sigmoid, "tanh_squash": t_tanh_squash, "winsorize": t_winsorize,
}

# 带窗时序算子: (torch函数, min_periods)
TORCH_TS: Dict[str, Callable] = {
    "ts_Delay": t_ts_Delay, "ts_Mean": t_ts_Mean, "ts_Decay": t_ts_Decay,
    "ts_Max": t_ts_Max, "ts_Min": t_ts_Min, "ts_Delta": t_ts_Delta,
    "ts_Stdev": t_ts_Stdev, "ts_Sum": t_ts_Sum, "ts_Median": t_ts_Median,
    "ts_PctChange": t_ts_PctChange, "ts_ROC": t_ts_ROC, "ts_Bias": t_ts_Bias,
    "ts_VolRatio": t_ts_VolRatio, "ts_HistVol": t_ts_HistVol, "ts_Rank": t_ts_Rank,
    "ts_Skewness": t_ts_Skewness, "ts_Kurtosis": t_ts_Kurtosis,
    "ts_DecayExp": t_ts_DecayExp, "ts_CumReturn": t_ts_CumReturn,
    "ts_Shift": t_ts_Shift, "ts_Count": t_ts_Count, "ts_VAR": t_ts_VAR,
    "ts_LINEARREG": t_ts_LINEARREG, "ts_LINEARREG_SLOPE": t_ts_LINEARREG_SLOPE,
    "ts_LINEARREG_ANGLE": t_ts_LINEARREG_ANGLE,
    "ts_LINEARREG_INTERCEPT": t_ts_LINEARREG_INTERCEPT,
    "ts_LINEARREG_R2": t_ts_LINEARREG_R2,
    # ---- L2 基类叶子算子 (数值对齐 factor_engine 的 talib 语义) ----
    # 移动平均族 (参数化基类 sma/ema/wma/dema/tema/trima/kama)
    "ts_SMA": t_ts_SMA, "ts_EMA": t_ts_EMA, "ts_WMA": t_ts_WMA,
    "ts_DEMA": t_ts_DEMA, "ts_TEMA": t_ts_TEMA,
    "ts_TRIMA": t_ts_TRIMA, "ts_KAMA": t_ts_KAMA, "ts_SAR": t_ts_SAR,
    # 摆动指标族 (固定参数基类 rsi/adx/cci/willr/atr)
    "ts_RSI": t_ts_RSI, "ts_ADX": t_ts_ADX, "ts_ADXR": t_ts_ADXR,
    "ts_CCI": t_ts_CCI, "ts_WILLR": t_ts_WILLR, "ts_ATR": t_ts_ATR,
    "ts_NATR": t_ts_NATR, "ts_TRANGE": t_ts_TRANGE,
    # 复合指标族 (固定参数基类 macd/kdj/bbands)
    "ts_MACD_DIF": t_ts_MACD_DIF, "ts_KDJ_K": t_ts_KDJ_K,
    "ts_BOLL_POS": t_ts_BOLL_POS,
    # 周期性基类 (参数化: amplitude/price_volume_corr/reversal)
    "ts_Amplitude": t_ts_Amplitude, "ts_Corr": t_ts_Corr,
    "ts_Reversal": t_ts_Reversal,
    # TALIB 族 (固定参数基类叶子)
    "ts_OBV": t_ts_OBV, "ts_AD": t_ts_AD, "ts_ADOSC": t_ts_ADOSC,
    "ts_MFI": t_ts_MFI, "ts_STOCHF_K": t_ts_STOCHF_K,
    "ts_STOCHRSI_K": t_ts_STOCHRSI_K, "ts_AROON_UP": t_ts_AROON_UP,
    "ts_AROON_DOWN": t_ts_AROON_DOWN, "ts_AROONOSC": t_ts_AROONOSC,
    "ts_ULTOSC": t_ts_ULTOSC, "ts_AVGPRICE": t_ts_AVGPRICE,
    "ts_MEDPRICE": t_ts_MEDPRICE, "ts_TYPPRICE": t_ts_TYPPRICE,
    "ts_WCLPRICE": t_ts_WCLPRICE, "ts_PPO": t_ts_PPO,
    "ts_BETA": t_ts_BETA, "ts_CORREL": t_ts_CORREL,
    # 阶段5.1.1 补充 (审计发现因子库用到, GPU 曾缺失): 动量 / Barra 残差波动
    "ts_MOM": t_ts_MOM, "ts_RESVOL": t_ts_RESVOL,
    # AlphaMaster 映射补充带窗时序算子 (阶段6.3: 补齐 GPU 覆盖率)
    "ts_ArgMax": t_ts_ArgMax, "ts_ArgMin": t_ts_ArgMin,
    "ts_Product": t_ts_Product, "ts_DecayLinear": t_ts_DecayLinear,
    # 因子侧 3.2: AlphaMaster 补充技术类参数化基类 (能挪进来的挪进来, 已纳入 GP_BASE_LEAF)
    "ts_PricePosition": t_ts_PricePosition, "ts_Autocorr": t_ts_Autocorr,
    "ts_TypicalDev": t_ts_TypicalDev, "ts_DmiDiff": t_ts_DmiDiff,
    "ts_Trix": t_ts_Trix, "ts_AmihudIlliq": t_ts_AmihudIlliq,
    "ts_KyleLambda": t_ts_KyleLambda, "ts_CMF": t_ts_CMF,
    "ts_ADLineSlope": t_ts_ADLineSlope,
    # Hilbert 变换族 (mama / TALIB_HT_DCPERIOD / TALIB_HT_DCPHASE / TALIB_HT_TRENDMODE)
    "ts_MAMA": t_ts_MAMA, "ts_HT_DCPERIOD": t_ts_HT_DCPERIOD,
    "ts_HT_DCPHASE": t_ts_HT_DCPHASE, "ts_HT_TRENDMODE": t_ts_HT_TRENDMODE,
    # ---- RL 因子挖掘收尾补充 (阶段 P0: RL 解码表达式用到的 18 个 ts_* GPU 补齐) ----
    "ts_MACD_HIST": t_ts_MACD_HIST, "ts_KDJ_D": t_ts_KDJ_D,
    "ts_BOLL_WIDTH": t_ts_BOLL_WIDTH, "ts_SAR_DIST": t_ts_SAR_DIST,
    "ts_Quantile": t_ts_Quantile, "ts_Cov": t_ts_Cov,
    "ts_TrendStrength": t_ts_TrendStrength, "ts_GKVol": t_ts_GKVol,
    "ts_ParkinsonVol": t_ts_ParkinsonVol, "ts_YangZhangVol": t_ts_YangZhangVol,
    "ts_RSVol": t_ts_RSVol, "ts_RetEntropy": t_ts_RetEntropy,
    "ts_KeltnerPos": t_ts_KeltnerPos, "ts_IchimokuKijun": t_ts_IchimokuKijun,
    "ts_IchimokuTenkan": t_ts_IchimokuTenkan, "ts_SuperTrend": t_ts_SuperTrend,
    "ts_Hurst": t_ts_Hurst, "ts_FractalDim": t_ts_FractalDim,
}

# 无窗时序算子
TORCH_TS_RAW: Dict[str, Callable] = {
    "ts_Log": t_ts_Log, "ts_Identity": t_ts_Identity,
    # AlphaMaster 映射补充无窗时序算子 (阶段6.3: 补齐 GPU 覆盖率)
    "ts_Scale": t_ts_Scale,
}

# 截面算子
TORCH_CS: Dict[str, Callable] = {
    "cs_Rank": t_cs_Rank, "cs_Demean": t_cs_Demean,
    "cs_Zscore": t_cs_Zscore, "cs_TransNorm": t_cs_TransNorm,
}

# 基类叶子 -> 引擎算子/字段 的映射以 factor_engine.BASE_OPERATOR_MAP 为唯一数据源
# (name -> (ts_算子, [所需字段], 参数个数)), 求值器按此绑定字段并调用 TORCH_TS 算子;
# 全部 L2 基类叶子 (含 mama/HT_DCPERIOD/HT_DCPHASE/HT_TRENDMODE 等 Hilbert 族) 均已 GPU 化,
# 不再 fallback 到 evaluate_expression 原路径。
