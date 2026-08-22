# -*- coding: utf-8 -*-
"""
lib/factor_rl/ops.py -- RL 因子挖掘算子库 (深度复刻 AlphaMaster model_core/ops.py)

算子命名采用本系统算子名 (ts_Mean/ts_Stdev/cs_Rank 等), 使 RL 生成的表达式
能被本系统引擎 evaluate_expression 求值, 入库后可直接用于多因子选股。
固定窗口算子 (如 ts_Mean_5) 解码时映射为本系统参数化形式 (ts_Mean(x, 5))。

统一契约:
  - 输入/输出均为 torch.Tensor, 形状 [N, T] (N=股票数, T=时间)
  - 全部因果 (无 look-ahead): 时序算子用 unfold 滑动窗口, 左侧补零
  - 数值安全: DIV 加 1e-6, nan_to_num, clamp 防溢出
  - 出口统一 nan_to_num
"""
from __future__ import annotations

import torch
import torch.nn.functional as F

# ============================================================
# 基础工具
# ============================================================

def _ts_delay(x: torch.Tensor, d: int) -> torch.Tensor:
    """因果延迟: 左侧补 d 个 0, 右移 d 位"""
    if d <= 0:
        return x
    pad = torch.zeros(x.shape[0], d, dtype=x.dtype, device=x.device)
    return torch.cat([pad, x[:, :-d]], dim=1)


def _ts_rolling(x: torch.Tensor, d: int) -> torch.Tensor:
    """因果滑动窗口: 返回 [N, T, d], 左侧补零 (无 look-ahead)"""
    if d <= 1:
        return x.unsqueeze(-1)
    pad = torch.zeros(x.shape[0], d - 1, dtype=x.dtype, device=x.device)
    padded = torch.cat([pad, x], dim=1)
    return padded.unfold(1, d, 1)  # [N, T, d]


def _nan_to_num(x: torch.Tensor) -> torch.Tensor:
    return torch.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)


# ============================================================
# 基础算术算子 (arity 1/2/3)
# ============================================================

def op_add(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(a + b)


def op_sub(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(a - b)


def op_mul(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(a * b)


def op_div(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(a / (b + 1e-6))


def op_neg(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(-a)


def op_abs(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(a.abs())


def op_sign(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(torch.sign(a))


def op_gate(cond: torch.Tensor, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    """条件门: cond>0 取 x, 否则取 y"""
    mask = (cond > 0).float()
    return _nan_to_num(mask * x + (1.0 - mask) * y)


def op_jump(a: torch.Tensor) -> torch.Tensor:
    """因果 expanding zscore + tanh 软化 (降低稀疏度)"""
    mean = a.cumsum(dim=1) / torch.arange(1, a.shape[1] + 1, dtype=a.dtype, device=a.device).unsqueeze(0)
    sq = (a * a).cumsum(dim=1) / torch.arange(1, a.shape[1] + 1, dtype=a.dtype, device=a.device).unsqueeze(0)
    var = (sq - mean * mean).clamp_min(0.0)
    std = var.sqrt().clamp_min(1e-8)
    z = (a - mean) / std
    return _nan_to_num(torch.tanh(z - 1.5))


def op_decay(a: torch.Tensor) -> torch.Tensor:
    """归一化指数衰减 (近期权重高)"""
    n = a.shape[1]
    weights = torch.exp(-torch.arange(n, dtype=a.dtype, device=a.device).flip(0) / max(n, 1))
    weights = weights / weights.sum()
    out = torch.zeros_like(a)
    for t in range(n):
        w = weights[n - 1 - t:]
        w = w / w.sum()
        out[:, t] = (a[:, :t + 1] * w).sum(dim=1)
    return _nan_to_num(out)


def op_delay1(a: torch.Tensor) -> torch.Tensor:
    return _ts_delay(a, 1)


def op_max3(a: torch.Tensor) -> torch.Tensor:
    """3 期最大值 (含当前及前 2 期)"""
    return _nan_to_num(_ts_rolling(a, 3).max(dim=-1).values)


# ============================================================
# 时序算子 (带窗, arity 1)
# ============================================================

def _ts_mean(x: torch.Tensor, d: int) -> torch.Tensor:
    return _nan_to_num(_ts_rolling(x, d).mean(dim=-1))


def _ts_std(x: torch.Tensor, d: int) -> torch.Tensor:
    w = _ts_rolling(x, d)
    return _nan_to_num(w.std(dim=-1, unbiased=False).clamp_min(1e-8))


def _ts_rank(x: torch.Tensor, d: int) -> torch.Tensor:
    """窗口内当前值排名归一化到 [0,1] (取窗口内最后一个位置)"""
    w = _ts_rolling(x, d)  # [N, T, d]
    sorted_idx = w.argsort(dim=-1)
    ranks = torch.empty_like(sorted_idx, dtype=torch.float)
    arange = torch.arange(d, device=x.device).float().view(1, 1, d)
    ranks.scatter_(-1, sorted_idx, arange.expand_as(sorted_idx))
    cur_rank = ranks[..., -1]
    return _nan_to_num(cur_rank / max(d - 1, 1))


def _ts_sum(x: torch.Tensor, d: int) -> torch.Tensor:
    return _nan_to_num(_ts_rolling(x, d).sum(dim=-1))


def _ts_max(x: torch.Tensor, d: int) -> torch.Tensor:
    return _nan_to_num(_ts_rolling(x, d).max(dim=-1).values)


def _ts_min(x: torch.Tensor, d: int) -> torch.Tensor:
    return _nan_to_num(_ts_rolling(x, d).min(dim=-1).values)


def _ts_zscore(x: torch.Tensor, d: int) -> torch.Tensor:
    w = _ts_rolling(x, d)
    mean = w.mean(dim=-1, keepdim=True)
    std = w.std(dim=-1, unbiased=False, keepdim=True).clamp_min(1e-8)
    return _nan_to_num((x - mean.squeeze(-1)) / std.squeeze(-1))


def _ts_corr(x: torch.Tensor, y: torch.Tensor, d: int) -> torch.Tensor:
    """双序列窗口相关"""
    wx = _ts_rolling(x, d)
    wy = _ts_rolling(y, d)
    mx = wx.mean(dim=-1, keepdim=True)
    my = wy.mean(dim=-1, keepdim=True)
    cov = ((wx - mx) * (wy - my)).mean(dim=-1)
    sx = wx.std(dim=-1, unbiased=False).clamp_min(1e-8)
    sy = wy.std(dim=-1, unbiased=False).clamp_min(1e-8)
    return _nan_to_num(cov / (sx * sy))


def _ts_covariance(x: torch.Tensor, y: torch.Tensor, d: int) -> torch.Tensor:
    """双序列窗口协方差 (原版 COVARIANCE_10 语义)"""
    wx = _ts_rolling(x, d)
    wy = _ts_rolling(y, d)
    mx = wx.mean(dim=-1, keepdim=True)
    my = wy.mean(dim=-1, keepdim=True)
    cov = ((wx - mx) * (wy - my)).mean(dim=-1)
    return _nan_to_num(cov)


def _ts_quantile(x: torch.Tensor, d: int) -> torch.Tensor:
    """当前值在过去 d 期的分位数 (0~1), 严格小于比例 (与 _ts_rank 语义统一)"""
    w = _ts_rolling(x, d)
    cur = w[..., -1:]
    rank = (w < cur).float().mean(dim=-1)
    return _nan_to_num(rank)


def _ts_skew(x: torch.Tensor, d: int) -> torch.Tensor:
    """d 期偏度 (三阶矩标准化), 捕捉分布非对称性"""
    w = _ts_rolling(x, d)
    m = w.mean(dim=-1, keepdim=True)
    s = ((w - m) ** 2).mean(dim=-1).sqrt().clamp_min(1e-8)
    skew = ((w - m) ** 3).mean(dim=-1) / (s ** 3)
    return _nan_to_num(skew)


def _ema_simple(x: torch.Tensor, span: int) -> torch.Tensor:
    """指数加权移动平均 (因果精确递推, 首值初始化, 与原版 _ema_simple 语义一致)"""
    alpha = 2.0 / (span + 1.0)
    N, T = x.shape
    out = torch.zeros_like(x)
    if T == 0:
        return out
    out[:, 0] = x[:, 0]
    for t in range(1, T):
        out[:, t] = alpha * x[:, t] + (1.0 - alpha) * out[:, t - 1]
    return _nan_to_num(out)


def _op_wma(x: torch.Tensor) -> torch.Tensor:
    """加权移动平均 (权重 3,2,1), 平滑信号 (原版 WMA 语义)"""
    return _nan_to_num((3.0 * x + 2.0 * _ts_delay(x, 1) + 1.0 * _ts_delay(x, 2)) / 6.0)


def _ts_momentum(x: torch.Tensor, d: int) -> torch.Tensor:
    """短期均线 - 长期均线 (原版 MOMENTUM_5/10 语义: 均线差捕捉趋势方向)"""
    return _nan_to_num(_ts_mean(x, d) - _ts_mean(x, 20))


def _ts_argmax(x: torch.Tensor, d: int) -> torch.Tensor:
    """窗口内最大值位置 (归一化到 [0,1], 0=最早, 1=最近)"""
    w = _ts_rolling(x, d)
    idx = w.argmax(dim=-1).float()
    return _nan_to_num(idx / max(d - 1, 1))


def _ts_argmin(x: torch.Tensor, d: int) -> torch.Tensor:
    w = _ts_rolling(x, d)
    idx = w.argmin(dim=-1).float()
    return _nan_to_num(idx / max(d - 1, 1))


def _ts_decay_linear(x: torch.Tensor, d: int) -> torch.Tensor:
    """线性衰减加权平均 (近期权重高): 权重=[1,2,...,d]/sum"""
    weights = torch.arange(1, d + 1, dtype=x.dtype, device=x.device).float()
    weights = weights / weights.sum()
    w = _ts_rolling(x, d)
    return _nan_to_num((w * weights).sum(dim=-1))


def _ts_decay_exp(x: torch.Tensor, d: int) -> torch.Tensor:
    """指数衰减加权平均"""
    weights = torch.exp(-torch.arange(d, dtype=x.dtype, device=x.device).flip(0) / max(d, 1))
    weights = weights / weights.sum()
    w = _ts_rolling(x, d)
    return _nan_to_num((w * weights).sum(dim=-1))


def _ts_scale(x: torch.Tensor) -> torch.Tensor:
    """因果 L1 归一化: x[t]/sum(|x[1..t]|)"""
    abs_sum = x.abs().cumsum(dim=1).clamp_min(1e-8)
    return _nan_to_num(x / abs_sum)


def _ts_product(x: torch.Tensor, d: int) -> torch.Tensor:
    """滑动乘积 (用对数累加避免数值爆炸): exp(sum(log(x+1)))-1"""
    x_safe = x.clamp(min=-0.999)
    log_x = torch.log1p(x_safe)
    log_sum = _ts_rolling(log_x, d).sum(dim=-1).clamp(-10, 10)
    return _nan_to_num(torch.expm1(log_sum))


def _ts_delta(x: torch.Tensor, d: int) -> torch.Tensor:
    return _nan_to_num(x - _ts_delay(x, d))


def _ts_log(x: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(torch.log(x.abs().clamp_min(1e-8)))


# ============================================================
# 一元/二元/三元 数学算子
# ============================================================

def op_power(a: torch.Tensor, p: float = 2.0) -> torch.Tensor:
    """带符号乘方: sign(x)*|x|^p"""
    return _nan_to_num(torch.sign(a) * torch.abs(a) ** p)


def op_max2(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """二元逐元素取大 (原版 MAX, arity=2)"""
    return _nan_to_num(torch.maximum(a, b))


def op_min2(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """二元逐元素取小 (原版 MIN, arity=2)"""
    return _nan_to_num(torch.minimum(a, b))


def op_signed_log(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(torch.sign(a) * torch.log1p(torch.abs(a)))


def op_sqrt(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(torch.sign(a) * torch.sqrt(torch.abs(a)))


def op_clip(a: torch.Tensor, lo: float = -3.0, hi: float = 3.0) -> torch.Tensor:
    return _nan_to_num(a.clamp(lo, hi))


def op_sigmoid(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(torch.sigmoid(a))


def op_tanh_squash(a: torch.Tensor) -> torch.Tensor:
    return _nan_to_num(torch.tanh(a))


def op_if_gt(cond: torch.Tensor, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    mask = (cond > 0).float()
    return _nan_to_num(mask * x + (1.0 - mask) * y)


def op_winsorize(a: torch.Tensor, lo: float = -3.0, hi: float = 3.0) -> torch.Tensor:
    return _nan_to_num(a.clamp(lo, hi))


# ============================================================
# 截面算子 (沿 N 维逐时间步, N=1 时恒等退化)
# ============================================================

def op_cs_rank(x: torch.Tensor) -> torch.Tensor:
    """截面排名 (逐时间步跨股票, 归一化到 [0,1])"""
    if x.shape[0] <= 1:
        return _nan_to_num(x)
    sorted_idx = x.argsort(dim=0)
    ranks = torch.empty_like(sorted_idx, dtype=torch.float)
    arange = torch.arange(x.shape[0], device=x.device).float().unsqueeze(1)
    ranks.scatter_(0, sorted_idx, arange.expand_as(sorted_idx))
    return _nan_to_num(ranks / max(x.shape[0] - 1, 1))


def op_cs_demean(x: torch.Tensor) -> torch.Tensor:
    """截面去均值 (逐时间步)"""
    if x.shape[0] <= 1:
        return _nan_to_num(x)
    mean = x.mean(dim=0, keepdim=True)
    return _nan_to_num(x - mean)


def op_cs_zscore(x: torch.Tensor) -> torch.Tensor:
    """截面 zscore (逐时间步)"""
    if x.shape[0] <= 1:
        return _nan_to_num(x)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=False, keepdim=True).clamp_min(1e-8)
    return _nan_to_num((x - mean) / std)


def op_cs_transnorm(x: torch.Tensor) -> torch.Tensor:
    """截面正态分位数变换 (rank -> norm.ppf)"""
    if x.shape[0] <= 1:
        return _nan_to_num(x)
    r = op_cs_rank(x).clamp(0.001, 0.999)
    from math import sqrt
    return _nan_to_num(torch.erfinv(2.0 * r - 1.0) * sqrt(2.0))


# ============================================================
# 算子注册表 (name -> (transform, arity))
# 算子名采用本系统风格, 解码时映射为本系统参数化表达式
# ============================================================

OPERATOR_REGISTRY = {
    # 基础算术
    "add": (op_add, 2), "sub": (op_sub, 2), "mul": (op_mul, 2), "div": (op_div, 2),
    "neg": (op_neg, 1), "abs": (op_abs, 1), "sign": (op_sign, 1),
    "gate": (op_gate, 3), "jump": (op_jump, 1), "max3": (op_max3, 1),
    "max": (op_max2, 2), "min": (op_min2, 2),
    "delay1": (lambda x: _ts_delay(x, 1), 1),
    "delay4": (lambda x: _ts_delay(x, 4), 1),
    "power": (op_power, 1), "signed_log": (op_signed_log, 1), "sqrt": (op_sqrt, 1),
    "clip": (op_clip, 1), "sigmoid": (op_sigmoid, 1), "tanh_squash": (op_tanh_squash, 1),
    "if_gt": (op_if_gt, 3), "winsorize": (op_winsorize, 1),
    # 时序 (带窗, arity 1)
    "ts_Mean_5": (lambda x: _ts_mean(x, 5), 1),
    "ts_Mean_10": (lambda x: _ts_mean(x, 10), 1),
    "ts_Mean_20": (lambda x: _ts_mean(x, 20), 1),
    "ts_Stdev_5": (lambda x: _ts_std(x, 5), 1),
    "ts_Stdev_10": (lambda x: _ts_std(x, 10), 1),
    "ts_Stdev_20": (lambda x: _ts_std(x, 20), 1),
    "ts_Rank_5": (lambda x: _ts_rank(x, 5), 1),
    "ts_Rank_10": (lambda x: _ts_rank(x, 10), 1),
    "ts_Rank_20": (lambda x: _ts_rank(x, 20), 1),
    "ts_Sum_5": (lambda x: _ts_sum(x, 5), 1),
    "ts_Sum_10": (lambda x: _ts_sum(x, 10), 1),
    "ts_Sum_20": (lambda x: _ts_sum(x, 20), 1),
    "ts_Max_10": (lambda x: _ts_max(x, 10), 1),
    "ts_Max_20": (lambda x: _ts_max(x, 20), 1),
    "ts_Min_10": (lambda x: _ts_min(x, 10), 1),
    "ts_Min_20": (lambda x: _ts_min(x, 20), 1),
    "ts_Delta_5": (lambda x: _ts_delta(x, 5), 1),
    "ts_Decay_5": (lambda x: _ts_decay_exp(x, 5), 1),
    "ts_DecayExp_5": (lambda x: _ts_decay_exp(x, 5), 1),
    "ts_ArgMax_5": (lambda x: _ts_argmax(x, 5), 1),
    "ts_ArgMin_5": (lambda x: _ts_argmin(x, 5), 1),
    "ts_ArgMax_10": (lambda x: _ts_argmax(x, 10), 1),
    "ts_ArgMin_10": (lambda x: _ts_argmin(x, 10), 1),
    "ts_Product_5": (lambda x: _ts_product(x, 5), 1),
    "ts_Scale": (_ts_scale, 1),
    "ts_Log": (_ts_log, 1),
    "ts_Zscore_10": (lambda x: _ts_zscore(x, 10), 1),
    "ts_Zscore_20": (lambda x: _ts_zscore(x, 20), 1),
    "ts_Quantile_10": (lambda x: _ts_quantile(x, 10), 1),
    "ts_Skew_10": (lambda x: _ts_skew(x, 10), 1),
    "momentum_5": (lambda x: _ts_momentum(x, 5), 1),
    "momentum_10": (lambda x: _ts_momentum(x, 10), 1),
    "ts_EMA_5": (lambda x: _ema_simple(x, 5), 1),
    "ts_EMA_20": (lambda x: _ema_simple(x, 20), 1),
    "wma": (_op_wma, 1),
    "delta": (lambda x: _ts_delta(x, 1), 1),
    "ts_DecayLinear_5": (lambda x: _ts_decay_linear(x, 5), 1),
    "ts_Cov_10": (lambda x, y: _ts_covariance(x, y, 10), 2),
    # 时序 (带窗, arity 2)
    "ts_Corr_10": (lambda x, y: _ts_corr(x, y, 10), 2),
    # 截面 (arity 1)
    "cs_Rank": (op_cs_rank, 1),
    "cs_Demean": (op_cs_demean, 1),
    "cs_Zscore": (op_cs_zscore, 1),
    "cs_TransNorm": (op_cs_transnorm, 1),
}

# 恒正算子 (输出值域非负, 连续使用丢失符号信息)
POSITIVE_ONLY_OPS = {"ts_Rank_5", "ts_Rank_10", "ts_Rank_20", "abs", "sigmoid", "cs_Rank",
                     "ts_ArgMax_5", "ts_ArgMin_5", "ts_ArgMax_10", "ts_ArgMin_10",
                     "ts_Quantile_10"}

# 恒正传播算子 (在恒正输入上输出仍恒正)
INFECTED_PROPAGATING_OPS = {
    "ts_Mean_5", "ts_Mean_10", "ts_Mean_20", "ts_Sum_5", "ts_Sum_10", "ts_Sum_20",
    "ts_Max_10", "ts_Max_20", "ts_Min_10", "ts_Min_20", "clip", "sqrt", "power",
    "signed_log", "sigmoid", "tanh_squash", "winsorize", "ts_Decay_5", "ts_DecayExp_5",
    "ts_Product_5", "ts_Scale", "ts_Log", "ts_EMA_5", "ts_EMA_20", "wma",
    "ts_DecayLinear_5",
}

# 符号恢复算子 (能恢复符号信息)
SIGN_RESTORE_OPS = {
    "sub", "div", "neg", "gate", "if_gt", "cs_Demean", "cs_Zscore", "cs_Rank",
    "cs_TransNorm", "ts_Stdev_5", "ts_Stdev_10", "ts_Stdev_20", "ts_Corr_10",
    "ts_Delta_5", "jump", "sign", "max3", "signed_log", "power", "sqrt",
    "ts_Zscore_10", "ts_Zscore_20", "ts_Skew_10", "momentum_5", "momentum_10",
    "delta", "ts_Cov_10",
}

# 算子名称列表 (有序, 供词表派生)
OPERATOR_NAMES = list(OPERATOR_REGISTRY.keys())

# 解码映射: 算子名 -> 本系统参数化表达式模板 (x 为操作数占位)
# 用于把 RL 表达式解码为本系统引擎可求值的形式
DECODE_MAP = {
    "add": "({a} + {b})", "sub": "({a} - {b})", "mul": "({a} * {b})", "div": "({a} / {b})",
    "neg": "((-1) * ({a}))", "abs": "abs({a})", "sign": "sign({a})",
    "gate": "gate({a}, {b}, {c})", "jump": "jump({a})", "max3": "max3({a})",
    "max": "({a} + {b} + abs({a} - {b})) / 2",
    "min": "({a} + {b} - abs({a} - {b})) / 2",
    "delay1": "ts_Shift({a}, 1)", "delay4": "ts_Shift({a}, 4)",
    "power": "power({a}, 2)", "signed_log": "signed_log({a})", "sqrt": "sqrt({a})",
    "clip": "clip({a}, -3, 3)", "sigmoid": "sigmoid({a})", "tanh_squash": "tanh_squash({a})",
    "if_gt": "if_gt({a}, {b}, {c})", "winsorize": "winsorize({a}, -3, 3)",
    "ts_Mean_5": "ts_Mean({a}, 5)", "ts_Mean_10": "ts_Mean({a}, 10)", "ts_Mean_20": "ts_Mean({a}, 20)",
    "ts_Stdev_5": "ts_Stdev({a}, 5)", "ts_Stdev_10": "ts_Stdev({a}, 10)", "ts_Stdev_20": "ts_Stdev({a}, 20)",
    "ts_Rank_5": "ts_Rank({a}, 5)", "ts_Rank_10": "ts_Rank({a}, 10)", "ts_Rank_20": "ts_Rank({a}, 20)",
    "ts_Sum_5": "ts_Sum({a}, 5)", "ts_Sum_10": "ts_Sum({a}, 10)", "ts_Sum_20": "ts_Sum({a}, 20)",
    "ts_Max_10": "ts_Max({a}, 10)", "ts_Max_20": "ts_Max({a}, 20)",
    "ts_Min_10": "ts_Min({a}, 10)", "ts_Min_20": "ts_Min({a}, 20)",
    "ts_Delta_5": "ts_Delta({a}, 5)",
    "ts_Decay_5": "ts_Decay({a}, 5)", "ts_DecayExp_5": "ts_DecayExp({a}, 5)",
    "ts_ArgMax_5": "ts_ArgMax({a}, 5)", "ts_ArgMin_5": "ts_ArgMin({a}, 5)",
    "ts_ArgMax_10": "ts_ArgMax({a}, 10)", "ts_ArgMin_10": "ts_ArgMin({a}, 10)",
    "ts_Product_5": "ts_Product({a}, 5)",
    "ts_Scale": "ts_Scale({a})", "ts_Log": "ts_Log({a})",
    "ts_Zscore_10": "(({a}) - ts_Mean({a}, 10)) / (ts_Stdev({a}, 10) + 1e-6)",
    "ts_Zscore_20": "(({a}) - ts_Mean({a}, 20)) / (ts_Stdev({a}, 20) + 1e-6)",
    "ts_Quantile_10": "ts_Quantile({a}, 10)",
    "ts_Skew_10": "ts_Skewness({a}, 10)",
    "momentum_5": "ts_Mean({a}, 5) - ts_Mean({a}, 20)",
    "momentum_10": "ts_Mean({a}, 10) - ts_Mean({a}, 20)",
    "ts_EMA_5": "ts_EMA({a}, 5)", "ts_EMA_20": "ts_EMA({a}, 20)",
    "wma": "ts_WMA({a}, 3)",
    "delta": "ts_Delta({a}, 1)",
    "ts_DecayLinear_5": "ts_DecayLinear({a}, 5)",
    "ts_Cov_10": "ts_Cov({a}, {b}, 10)",
    "ts_Corr_10": "ts_Corr({a}, {b}, 10)",
    "cs_Rank": "cs_Rank({a})", "cs_Demean": "cs_Demean({a})",
    "cs_Zscore": "cs_Zscore({a})", "cs_TransNorm": "cs_TransNorm({a})",
}
