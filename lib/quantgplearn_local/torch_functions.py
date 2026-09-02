"""Torch/GPU backends for QuantGplearn primitive functions.

The legacy NumPy/Pandas functions remain in :mod:`QuantGplearn.functions`.
This module attaches equivalent ``torch_function`` callables to supported
``_Function`` objects so that ``_Program.execute_tensor`` can evaluate GP trees
on CPU or CUDA tensors.

All tensor primitives expect dense panel factors with shape ``[T, N]`` where
``T`` is time and ``N`` is symbol/instrument. Time-series operators work along
``dim=0`` and cross-sectional operators work along ``dim=1``.
"""
from __future__ import annotations

import math
from typing import Callable

import torch

from .functions import _function_map

EPS = 1e-12

GPU_SAFE_FUNCTIONS = [
    "add", "sub", "mul", "div", "sqrt", "log", "abs", "neg", "inv",
    "max", "min", "sin", "cos", "tan", "sig",
    "ts_shift", "ts_delta", "ts_mom", "ts_min", "ts_max", "ts_argmax", "ts_argmin",
    "ts_rank", "ts_sum", "ts_std", "ts_corr", "ts_mean", "ts_zscore", "ts_freq",
    "ts_cdlbodym", "ts_bar_bs", "ts_adx", "ts_aroon", "ts_bopr", "ts_cmo", "ts_ema",
    "ts_macd", "ts_rsi", "ts_stochf", "ts_xs_ratio", "ts_one_ols_k", "ts_one_ols_resid",
    "ts_skew", "ts_kurt", "ts_atr", "ts_hedge", "ts_bband",
    "cs_rank", "cs_zscore", "cs_demean", "cs_scale", "cs_winsorize",
]

GPU_SAFE_PANEL_FUNCTIONS = [
    "add", "sub", "mul", "div", "sqrt", "log", "abs", "neg", "inv",
    "max", "min", "sig",
    "ts_shift", "ts_delta", "ts_mom", "ts_min", "ts_max", "ts_argmax", "ts_argmin",
    "ts_rank", "ts_sum", "ts_std", "ts_corr", "ts_mean", "ts_zscore", "ts_freq",
    "ts_cdlbodym", "ts_bar_bs", "ts_adx", "ts_aroon", "ts_bopr", "ts_cmo", "ts_ema",
    "ts_macd", "ts_rsi", "ts_stochf", "ts_xs_ratio", "ts_one_ols_k", "ts_one_ols_resid",
    "ts_skew", "ts_kurt", "ts_atr", "ts_hedge", "ts_bband",
    "cs_rank", "cs_zscore", "cs_demean", "cs_scale", "cs_winsorize",
]


def _as_tensor(x, like: torch.Tensor | None = None) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        return x
    if like is None:
        return torch.as_tensor(x, dtype=torch.float32)
    return torch.as_tensor(x, dtype=like.dtype, device=like.device)


def _scalar_int(x, default: int = 1) -> int:
    if isinstance(x, torch.Tensor):
        if x.numel() == 0:
            return default
        val = x.detach().flatten()[0].item()
    else:
        val = x
    try:
        if not math.isfinite(float(val)):
            return default
        return max(1, int(round(float(val))))
    except Exception:
        return default


def _nan_like(x: torch.Tensor, *shape: int) -> torch.Tensor:
    return torch.full(shape, float("nan"), dtype=x.dtype, device=x.device)


def _nanmean(x: torch.Tensor, dim=None, keepdim: bool = False):
    mask = torch.isfinite(x)
    safe = torch.where(mask, x, torch.zeros_like(x))
    count = mask.sum(dim=dim, keepdim=keepdim).clamp_min(1)
    return safe.sum(dim=dim, keepdim=keepdim) / count


def _nansum(x: torch.Tensor, dim=None, keepdim: bool = False):
    return torch.where(torch.isfinite(x), x, torch.zeros_like(x)).sum(dim=dim, keepdim=keepdim)


def _nanstd(x: torch.Tensor, dim=None, keepdim: bool = False, unbiased: bool = False):
    mean = _nanmean(x, dim=dim, keepdim=True)
    mask = torch.isfinite(x)
    diff2 = torch.where(mask, (x - mean) ** 2, torch.zeros_like(x))
    count = mask.sum(dim=dim, keepdim=True).clamp_min(1)
    denom = (count - 1).clamp_min(1) if unbiased else count
    var = diff2.sum(dim=dim, keepdim=True) / denom
    out = torch.sqrt(torch.clamp(var, min=0.0))
    if not keepdim and dim is not None:
        out = out.squeeze(dim)
    return out


def _nanmin(x: torch.Tensor, dim=None, keepdim: bool = False):
    fill = torch.where(torch.isfinite(x), x, torch.full_like(x, float("inf")))
    out = fill.amin(dim=dim, keepdim=keepdim)
    return torch.where(torch.isfinite(out), out, torch.full_like(out, float("nan")))


def _nanmax(x: torch.Tensor, dim=None, keepdim: bool = False):
    fill = torch.where(torch.isfinite(x), x, torch.full_like(x, -float("inf")))
    out = fill.amax(dim=dim, keepdim=keepdim)
    return torch.where(torch.isfinite(out), out, torch.full_like(out, float("nan")))


def _pad_front(out: torch.Tensor, d: int, like: torch.Tensor) -> torch.Tensor:
    if d <= 1:
        return out
    return torch.cat([_nan_like(like, d - 1, like.shape[1]), out], dim=0)


def _window(x: torch.Tensor, d) -> tuple[torch.Tensor, int]:
    d = _scalar_int(d)
    d = min(d, max(int(x.shape[0]), 1))
    return x.unfold(0, d, 1), d


def _rank_pct_dim(x: torch.Tensor, dim: int) -> torch.Tensor:
    """Percent rank. Ties use stable ordinal ranks for speed on GPU."""
    mask = torch.isfinite(x)
    x_fill = torch.where(mask, x, torch.full_like(x, float("inf")))
    order = torch.argsort(x_fill, dim=dim, stable=True)
    ranks = torch.argsort(order, dim=dim, stable=True).to(x.dtype) + 1.0
    count = mask.sum(dim=dim, keepdim=True).clamp_min(1).to(x.dtype)
    pct = ranks / count
    return torch.where(mask, pct, torch.full_like(x, float("nan")))


# Elementwise primitives ----------------------------------------------------
def t_add(x, y): return _as_tensor(x, _as_tensor(y)) + _as_tensor(y, _as_tensor(x))
def t_sub(x, y): return _as_tensor(x, _as_tensor(y)) - _as_tensor(y, _as_tensor(x))
def t_mul(x, y): return _as_tensor(x, _as_tensor(y)) * _as_tensor(y, _as_tensor(x))


def t_div(x, y):
    x = _as_tensor(x, _as_tensor(y))
    y = _as_tensor(y, x)
    out = torch.where(torch.abs(y) > 1e-6, x / y, torch.ones_like(x + y))
    return torch.where(torch.isfinite(out), out, torch.ones_like(out))


def t_sqrt(x): return torch.sqrt(torch.abs(_as_tensor(x)))


def t_log(x):
    x = torch.abs(_as_tensor(x))
    out = torch.where(x > 1e-6, torch.log(x), torch.zeros_like(x))
    return torch.where(torch.isfinite(out), out, torch.zeros_like(out))


def t_abs(x): return torch.abs(_as_tensor(x))
def t_neg(x): return -_as_tensor(x)


def t_inv(x):
    x = _as_tensor(x)
    out = torch.where(torch.abs(x) > 1e-6, 1.0 / x, torch.zeros_like(x))
    return torch.where(torch.isfinite(out), out, torch.zeros_like(out))


def t_max(x, y): return torch.maximum(_as_tensor(x, _as_tensor(y)), _as_tensor(y, _as_tensor(x)))
def t_min(x, y): return torch.minimum(_as_tensor(x, _as_tensor(y)), _as_tensor(y, _as_tensor(x)))
def t_sin(x): return torch.sin(_as_tensor(x))
def t_cos(x): return torch.cos(_as_tensor(x))
def t_tan(x): return torch.clamp(torch.tan(_as_tensor(x)), -1e6, 1e6)
def t_sig(x): return torch.sigmoid(torch.clamp(_as_tensor(x), -50, 50))


# Time-series primitives. Input/output shape: [T, N] ------------------------
def t_ts_shift(x, d):
    x = _as_tensor(x)
    d = min(_scalar_int(d), max(int(x.shape[0]), 1))
    out = torch.full_like(x, float("nan"))
    if d < x.shape[0]:
        out[d:] = x[:-d]
    return out


def t_ts_delta(x, d):
    x = _as_tensor(x)
    return x - t_ts_shift(x, d)


def t_ts_mom(x, d):
    x = _as_tensor(x)
    return t_div(x, t_ts_shift(x, d)) - 1.0


def t_ts_mean(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    return _pad_front(_nanmean(win, dim=-1), d, x)


def t_ts_sum(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    valid = torch.isfinite(win).all(dim=-1)
    out = _nansum(win, dim=-1)
    out = torch.where(valid, out, torch.full_like(out, float("nan")))
    return _pad_front(out, d, x)


def t_ts_std(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    out = _nanstd(win, dim=-1, unbiased=True)
    return _pad_front(out, d, x)


def t_ts_min(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    return _pad_front(_nanmin(win, dim=-1), d, x)


def t_ts_max(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    return _pad_front(_nanmax(win, dim=-1), d, x)


def t_ts_argmax(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    fill = torch.where(torch.isfinite(win), win, torch.full_like(win, -float("inf")))
    out = torch.argmax(fill, dim=-1).to(x.dtype)
    valid = torch.isfinite(win).any(dim=-1)
    out = torch.where(valid, out, torch.full_like(out, float("nan")))
    return _pad_front(out, d, x)


def t_ts_argmin(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    fill = torch.where(torch.isfinite(win), win, torch.full_like(win, float("inf")))
    out = torch.argmin(fill, dim=-1).to(x.dtype)
    valid = torch.isfinite(win).any(dim=-1)
    out = torch.where(valid, out, torch.full_like(out, float("nan")))
    return _pad_front(out, d, x)


def t_ts_rank(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    last = win[..., -1:]
    valid = torch.isfinite(win)
    last_valid = torch.isfinite(last)
    count = valid.sum(dim=-1).clamp_min(1).to(x.dtype)
    less = ((win < last) & valid & last_valid).sum(dim=-1).to(x.dtype)
    equal = ((win == last) & valid & last_valid).sum(dim=-1).to(x.dtype)
    out = (less + (equal + 1.0) / 2.0) / count
    out = torch.where(last_valid.squeeze(-1), out, torch.full_like(out, float("nan")))
    return _pad_front(out, d, x)


def t_ts_corr(x, y, d):
    x = _as_tensor(x, _as_tensor(y))
    y = _as_tensor(y, x)
    wx, d = _window(x, d)
    wy, _ = _window(y, d)
    mask = torch.isfinite(wx) & torch.isfinite(wy)
    mx = _nanmean(torch.where(mask, wx, torch.full_like(wx, float("nan"))), dim=-1, keepdim=True)
    my = _nanmean(torch.where(mask, wy, torch.full_like(wy, float("nan"))), dim=-1, keepdim=True)
    cx = torch.where(mask, wx - mx, torch.zeros_like(wx))
    cy = torch.where(mask, wy - my, torch.zeros_like(wy))
    n = mask.sum(dim=-1).clamp_min(1).to(x.dtype)
    cov = (cx * cy).sum(dim=-1) / n
    vx = (cx * cx).sum(dim=-1) / n
    vy = (cy * cy).sum(dim=-1) / n
    out = cov / torch.sqrt(vx * vy + EPS)
    out = torch.where(mask.sum(dim=-1) >= 2, out, torch.full_like(out, float("nan")))
    return _pad_front(out, d, x)


def t_ts_zscore(x, d):
    x = _as_tensor(x)
    return t_div(x - t_ts_mean(x, d), t_ts_std(x, d))


def t_ts_freq(x, d):
    x = _as_tensor(x)
    win, d = _window(x, d)
    last = win[..., -1:]
    out = ((win == last) & torch.isfinite(last)).sum(dim=-1).to(x.dtype)
    out = torch.where(torch.isfinite(last.squeeze(-1)), out, torch.full_like(out, float("nan")))
    return _pad_front(out, d, x)


def t_ts_cdlbodym(open_, close, d):
    body = _as_tensor(close, _as_tensor(open_)) - _as_tensor(open_, _as_tensor(close))
    up = torch.where(body > 0, torch.ones_like(body), torch.zeros_like(body))
    down = torch.where(body < 0, torch.ones_like(body), torch.zeros_like(body))
    return t_div(t_ts_sum(up, d), t_ts_sum(up + down, d))


def t_ts_bar_bs(high, low, d):
    high = _as_tensor(high, _as_tensor(low))
    low = _as_tensor(low, high)
    hd = high - t_ts_shift(high, 1)
    ld = low - t_ts_shift(low, 1)
    big = torch.where((hd > 0) & (ld < 0), torch.ones_like(high), torch.zeros_like(high))
    small = torch.where((hd < 0) & (ld > 0), torch.ones_like(high), torch.zeros_like(high))
    return t_div(t_ts_sum(big, d), t_ts_sum(big + small, d))


def t_ts_aroon(high, low, d):
    d_int = _scalar_int(d)
    return (t_ts_argmax(high, d_int) - t_ts_argmin(low, d_int)) / float(max(d_int, 1))


def t_ts_adx(high, low, close, d):
    high = _as_tensor(high, _as_tensor(low))
    low = _as_tensor(low, high)
    close = _as_tensor(close, high)
    prev_close = t_ts_shift(close, 1)
    tr = torch.maximum(torch.maximum(torch.abs(high - prev_close), torch.abs(low - prev_close)), torch.abs(high - low))
    atr = t_ts_mean(tr, d)
    up = high - t_ts_shift(high, 1)
    down = t_ts_shift(low, 1) - low
    plus_dm = torch.where((up > down) & (up > 0), up, torch.zeros_like(up))
    minus_dm = torch.where((down > up) & (down > 0), down, torch.zeros_like(down))
    plus_di = t_div(t_ts_mean(plus_dm, d), atr)
    minus_di = t_div(t_ts_mean(minus_dm, d), atr)
    return torch.abs(t_div(plus_di - minus_di, plus_di + minus_di))


def t_ts_bopr(open_, high, low, close, d):
    open_ = _as_tensor(open_, _as_tensor(close))
    high = _as_tensor(high, open_)
    low = _as_tensor(low, open_)
    close = _as_tensor(close, open_)
    bop = t_div(close - open_, high - low)
    return t_ts_mean(bop, d)


def t_ts_one_ols_k(x, y, d):
    x = _as_tensor(x, _as_tensor(y))
    y = _as_tensor(y, x)
    d_int = min(_scalar_int(d), max(int(x.shape[0]), 1))
    sx = t_ts_sum(x, d_int)
    sy = t_ts_sum(y, d_int)
    sxy = t_ts_sum(x * y, d_int)
    sx2 = t_ts_sum(x * x, d_int)
    numerator = d_int * sxy - sx * sy
    denominator = d_int * sx2 - sx * sx
    beta = torch.where(torch.abs(denominator) > EPS, numerator / denominator, torch.zeros_like(numerator))
    return torch.where(torch.isfinite(beta), beta, torch.zeros_like(beta))


def t_ts_one_ols_resid(x, y, d):
    x = _as_tensor(x, _as_tensor(y))
    y = _as_tensor(y, x)
    beta = t_ts_one_ols_k(x, y, d)
    intercept = t_ts_mean(y, d) - beta * t_ts_mean(x, d)
    return y - (beta * x + intercept)


def t_ts_stochf(high, low, close, d):
    high = _as_tensor(high, _as_tensor(low))
    low = _as_tensor(low, high)
    close = _as_tensor(close, high)
    low_min = t_ts_min(low, d)
    high_max = t_ts_max(high, d)
    return t_div(close - low_min, high_max - low_min)


def t_ts_cmo(x, d):
    x = _as_tensor(x)
    diff = x - t_ts_shift(x, 1)
    up = torch.where(diff > 0, diff, torch.zeros_like(diff))
    down = torch.where(diff < 0, -diff, torch.zeros_like(diff))
    return t_div(t_ts_sum(up, d) - t_ts_sum(down, d), t_ts_sum(up, d) + t_ts_sum(down, d))


def t_ts_ema(x, d):
    x = _as_tensor(x)
    d_int = min(_scalar_int(d), max(int(x.shape[0]), 1))
    alpha = 2.0 / (d_int + 1.0)
    out = torch.full_like(x, float("nan"))
    ema = torch.full((x.shape[1],), float("nan"), dtype=x.dtype, device=x.device)
    for i in range(x.shape[0]):
        cur = x[i]
        cur_valid = torch.isfinite(cur)
        ema_valid = torch.isfinite(ema)
        ema = torch.where(cur_valid & ema_valid, alpha * cur + (1.0 - alpha) * ema, ema)
        ema = torch.where(cur_valid & (~ema_valid), cur, ema)
        if i >= d_int - 1:
            out[i] = ema
    return out


def t_ts_macd(x, d1, d2, d3):
    short_ma = t_ts_mean(x, d1)
    long_ma = t_ts_mean(x, d2)
    return t_ts_mean(short_ma - long_ma, d3)


def t_ts_rsi(x, d):
    x = _as_tensor(x)
    diff = x - t_ts_shift(x, 1)
    up = torch.where(diff > 0, diff, torch.zeros_like(diff))
    down = torch.where(diff < 0, -diff, torch.zeros_like(diff))
    rs = t_div(t_ts_mean(up, d), t_ts_mean(down, d))
    return 100.0 - 100.0 / (1.0 + rs)


def t_ts_xs_ratio(x, d):
    x = _as_tensor(x)
    directional = torch.abs(x - t_ts_shift(x, d))
    volatility = t_ts_sum(torch.abs(x - t_ts_shift(x, 1)), d)
    return t_div(directional, volatility)


def t_ts_skew(x, d):
    x = _as_tensor(x)
    win, d_int = _window(x, d)
    mean = _nanmean(win, dim=-1, keepdim=True)
    diff = win - mean
    m2 = _nanmean(diff ** 2, dim=-1)
    m3 = _nanmean(diff ** 3, dim=-1)
    if d_int > 2:
        correction = math.sqrt(d_int * (d_int - 1.0)) / (d_int - 2.0)
    else:
        correction = float("nan")
    out = correction * m3 / torch.clamp(m2, min=EPS).pow(1.5)
    out = torch.where(m2 > EPS, out, torch.full_like(out, float("nan")))
    return _pad_front(out, d_int, x)


def t_ts_kurt(x, d):
    x = _as_tensor(x)
    win, d_int = _window(x, d)
    mean = _nanmean(win, dim=-1, keepdim=True)
    diff = win - mean
    m2 = _nanmean(diff ** 2, dim=-1)
    m4 = _nanmean(diff ** 4, dim=-1)
    out = m4 / torch.clamp(m2, min=EPS).pow(2.0) - 3.0
    out = torch.where(m2 > EPS, out, torch.full_like(out, float("nan")))
    return _pad_front(out, d_int, x)


def t_ts_atr(high, low, close, d1, d2):
    high = _as_tensor(high, _as_tensor(low))
    low = _as_tensor(low, high)
    close = _as_tensor(close, high)
    high_max = t_ts_max(high, d1)
    low_min = t_ts_min(low, d1)
    prev_close = t_ts_shift(close, d1)
    tr = torch.maximum(torch.maximum(torch.abs(high_max - prev_close), torch.abs(low_min - prev_close)), high_max - low_min)
    return t_div(t_ts_mean(tr, d2), close)


def t_ts_hedge(x, y, d1, d2):
    # Regression-residual hedge retained for numerical stability. The uploaded
    # sorted top/bottom variant uses d2 as a ratio while the GP metadata supplies
    # d2 as a large integer window, which makes hedge_len exceed the window.
    x = _as_tensor(x, _as_tensor(y))
    y = _as_tensor(y, x)
    beta = t_ts_one_ols_k(y, x, d1)
    resid = x - beta * y
    return t_ts_zscore(resid, d2)


def t_ts_bband(x, d1, d2):
    mult = float(_scalar_int(d2))
    return t_ts_mean(x, d1) + mult * t_ts_std(x, d1)


# Cross-sectional primitives. Input/output shape: [T, N] --------------------
def t_cs_rank(x):
    return _rank_pct_dim(_as_tensor(x), dim=1)


def t_cs_demean(x):
    x = _as_tensor(x)
    return x - _nanmean(x, dim=1, keepdim=True)


def t_cs_zscore(x):
    x = _as_tensor(x)
    mean = _nanmean(x, dim=1, keepdim=True)
    std = _nanstd(x, dim=1, keepdim=True, unbiased=True)
    out = t_div(x - mean, std)
    return torch.where(torch.isfinite(out), out, torch.zeros_like(out))


def t_cs_scale(x):
    x = _as_tensor(x)
    denom = torch.abs(torch.where(torch.isfinite(x), x, torch.zeros_like(x))).sum(dim=1, keepdim=True)
    return torch.where(denom > EPS, x / denom, torch.zeros_like(x))


def t_cs_winsorize(x):
    x = _as_tensor(x)
    try:
        lower = torch.nanquantile(x, 0.05, dim=1, keepdim=True)
        upper = torch.nanquantile(x, 0.95, dim=1, keepdim=True)
        return torch.minimum(torch.maximum(x, lower), upper)
    except Exception:  # pragma: no cover - fallback for older torch builds
        return torch.clamp(x, -1e6, 1e6)


_TORCH_FUNCTIONS: dict[str, Callable] = {
    "add": t_add,
    "sub": t_sub,
    "mul": t_mul,
    "div": t_div,
    "sqrt": t_sqrt,
    "log": t_log,
    "abs": t_abs,
    "neg": t_neg,
    "inv": t_inv,
    "max": t_max,
    "min": t_min,
    "sin": t_sin,
    "cos": t_cos,
    "tan": t_tan,
    "sig": t_sig,
    "ts_shift": t_ts_shift,
    "ts_delta": t_ts_delta,
    "ts_mom": t_ts_mom,
    "ts_min": t_ts_min,
    "ts_max": t_ts_max,
    "ts_argmax": t_ts_argmax,
    "ts_argmin": t_ts_argmin,
    "ts_rank": t_ts_rank,
    "ts_sum": t_ts_sum,
    "ts_std": t_ts_std,
    "ts_corr": t_ts_corr,
    "ts_mean": t_ts_mean,
    "ts_zscore": t_ts_zscore,
    "ts_freq": t_ts_freq,
    "ts_cdlbodym": t_ts_cdlbodym,
    "ts_bar_bs": t_ts_bar_bs,
    "ts_adx": t_ts_adx,
    "ts_aroon": t_ts_aroon,
    "ts_bopr": t_ts_bopr,
    "ts_cmo": t_ts_cmo,
    "ts_ema": t_ts_ema,
    "ts_macd": t_ts_macd,
    "ts_rsi": t_ts_rsi,
    "ts_stochf": t_ts_stochf,
    "ts_xs_ratio": t_ts_xs_ratio,
    "ts_one_ols_k": t_ts_one_ols_k,
    "ts_one_ols_resid": t_ts_one_ols_resid,
    "ts_skew": t_ts_skew,
    "ts_kurt": t_ts_kurt,
    "ts_atr": t_ts_atr,
    "ts_hedge": t_ts_hedge,
    "ts_bband": t_ts_bband,
    "cs_rank": t_cs_rank,
    "cs_zscore": t_cs_zscore,
    "cs_demean": t_cs_demean,
    "cs_scale": t_cs_scale,
    "cs_winsorize": t_cs_winsorize,
}


def register_torch_functions(function_map=None) -> dict[str, Callable]:
    """Attach torch implementations to supported QuantGplearn functions."""
    if function_map is None:
        function_map = _function_map
    for name, torch_func in _TORCH_FUNCTIONS.items():
        if name in function_map:
            setattr(function_map[name], "torch_function", torch_func)
    return _TORCH_FUNCTIONS.copy()


# Register on import so deep-copied _Function objects keep torch_function.
register_torch_functions()
