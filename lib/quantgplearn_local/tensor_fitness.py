"""GPU-friendly fitness functions for QuantGplearn factor mining."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import torch

EPS = 1e-12


@dataclass
class TensorFitness:
    """Callable fitness wrapper used by GPU GP programs."""

    function: Callable
    name: str
    greater_is_better: bool = True

    @property
    def sign(self) -> int:
        return 1 if self.greater_is_better else -1

    def __call__(self, y, y_pred, sample_weight=None, data=None) -> float:
        return float(self.function(y, y_pred, sample_weight=sample_weight, data=data))


def finite_mask(*xs: torch.Tensor, base_mask: Optional[torch.Tensor] = None) -> torch.Tensor:
    mask = None if base_mask is None else base_mask.bool().clone()
    for x in xs:
        m = torch.isfinite(x)
        mask = m if mask is None else (mask & m)
    if mask is None:
        raise ValueError("at least one tensor is required")
    return mask


def masked_mean(x: torch.Tensor, mask: torch.Tensor, dim=None, keepdim=False):
    safe = torch.where(mask, x, torch.zeros_like(x))
    count = mask.sum(dim=dim, keepdim=keepdim).clamp_min(1)
    return safe.sum(dim=dim, keepdim=keepdim) / count


def masked_std(x: torch.Tensor, mask: torch.Tensor, dim=None, keepdim=False, unbiased=False):
    mean = masked_mean(x, mask, dim=dim, keepdim=True)
    diff2 = torch.where(mask, (x - mean) ** 2, torch.zeros_like(x))
    count = mask.sum(dim=dim, keepdim=True).clamp_min(1)
    denom = (count - 1).clamp_min(1) if unbiased else count
    out = torch.sqrt(torch.clamp(diff2.sum(dim=dim, keepdim=True) / denom, min=0.0))
    if not keepdim and dim is not None:
        out = out.squeeze(dim)
    return out


def clean_factor(x: torch.Tensor, mask: Optional[torch.Tensor] = None, clip: float = 1e6) -> torch.Tensor:
    x = torch.where(torch.isfinite(x), x, torch.full_like(x, float("nan")))
    if mask is not None:
        x = torch.where(mask, x, torch.full_like(x, float("nan")))
    return torch.clamp(x, -clip, clip)


def normalize_by_day(x: torch.Tensor, mask: Optional[torch.Tensor] = None, eps: float = 1e-12) -> torch.Tensor:
    if mask is None:
        mask = torch.isfinite(x)
    else:
        mask = mask & torch.isfinite(x)
    mean = masked_mean(x, mask, dim=1, keepdim=True)
    std = masked_std(x, mask, dim=1, keepdim=True, unbiased=False)
    out = torch.where(std > eps, (x - mean) / std, torch.zeros_like(x))
    return torch.where(mask, out, torch.full_like(out, float("nan")))


def batch_pearsonr(x: torch.Tensor, y: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
    """Compute cross-sectional Pearson correlation for each time row."""
    mask = finite_mask(x, y, base_mask=mask)
    mx = masked_mean(x, mask, dim=1, keepdim=True)
    my = masked_mean(y, mask, dim=1, keepdim=True)
    cx = torch.where(mask, x - mx, torch.zeros_like(x))
    cy = torch.where(mask, y - my, torch.zeros_like(y))
    n = mask.sum(dim=1).clamp_min(1).to(x.dtype)
    cov = (cx * cy).sum(dim=1) / n
    vx = (cx * cx).sum(dim=1) / n
    vy = (cy * cy).sum(dim=1) / n
    corr = cov / torch.sqrt(vx * vy + EPS)
    corr = torch.where(mask.sum(dim=1) >= 2, corr, torch.full_like(corr, float("nan")))
    return corr


def rank_2d(x: torch.Tensor, mask: Optional[torch.Tensor] = None, dim: int = 1) -> torch.Tensor:
    if mask is None:
        mask = torch.isfinite(x)
    else:
        mask = mask & torch.isfinite(x)
    x_fill = torch.where(mask, x, torch.full_like(x, float("inf")))
    order = torch.argsort(x_fill, dim=dim, stable=True)
    ranks = torch.argsort(order, dim=dim, stable=True).to(x.dtype) + 1.0
    return torch.where(mask, ranks, torch.full_like(ranks, float("nan")))


def batch_spearmanr(x: torch.Tensor, y: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
    mask = finite_mask(x, y, base_mask=mask)
    rx = rank_2d(x, mask, dim=1)
    ry = rank_2d(y, mask, dim=1)
    return batch_pearsonr(rx, ry, mask)


def mean_ic(y: torch.Tensor, pred: torch.Tensor, sample_weight=None, data=None) -> float:
    mask = None if data is None else data.mask
    ic = batch_pearsonr(pred, y, mask)
    out = torch.nanmean(ic)
    return 0.0 if not torch.isfinite(out) else float(out.item())


def mean_rank_ic(y: torch.Tensor, pred: torch.Tensor, sample_weight=None, data=None) -> float:
    mask = None if data is None else data.mask
    ic = batch_spearmanr(pred, y, mask)
    out = torch.nanmean(ic)
    return 0.0 if not torch.isfinite(out) else float(out.item())


def icir(y: torch.Tensor, pred: torch.Tensor, sample_weight=None, data=None) -> float:
    mask = None if data is None else data.mask
    ic = batch_pearsonr(pred, y, mask)
    mean = torch.nanmean(ic)
    std = torch.sqrt(torch.nanmean((ic - mean) ** 2))
    out = torch.clamp(mean / (std + EPS), -100.0, 100.0)
    return 0.0 if not torch.isfinite(out) else float(out.item())


def rank_icir(y: torch.Tensor, pred: torch.Tensor, sample_weight=None, data=None) -> float:
    mask = None if data is None else data.mask
    ic = batch_spearmanr(pred, y, mask)
    mean = torch.nanmean(ic)
    std = torch.sqrt(torch.nanmean((ic - mean) ** 2))
    out = torch.clamp(mean / (std + EPS), -100.0, 100.0)
    return 0.0 if not torch.isfinite(out) else float(out.item())


def long_short_sharpe(
    y: torch.Tensor,
    pred: torch.Tensor,
    sample_weight=None,
    data=None,
    quantile: float = 0.3,
    fee: float = 3e-4,
    annualization: float = 365 * 24,
) -> float:
    """GPU proxy objective for long-short factor portfolios.

    This is a fast training proxy, not a replacement for the final Pandas
    backtest. Positions are dollar-neutral each time step: +0.5 gross long and
    -0.5 gross short across selected instruments.
    """
    mask = finite_mask(pred, y, base_mask=None if data is None else data.mask)
    T, N = pred.shape
    valid_per_row = mask.sum(dim=1)
    k = max(1, int(round(N * float(quantile))))
    k = min(k, max(1, N // 2))

    long_scores = torch.where(mask, pred, torch.full_like(pred, -float("inf")))
    short_scores = torch.where(mask, pred, torch.full_like(pred, float("inf")))
    long_idx = torch.topk(long_scores, k=k, dim=1).indices
    short_idx = torch.topk(-short_scores, k=k, dim=1).indices

    weights = torch.zeros_like(pred)
    weights.scatter_(1, long_idx, 0.5 / k)
    weights.scatter_(1, short_idx, -0.5 / k)
    weights = torch.where(mask & (valid_per_row[:, None] >= 2 * k), weights, torch.zeros_like(weights))

    gross_ret = (weights * torch.where(torch.isfinite(y), y, torch.zeros_like(y))).sum(dim=1)
    turnover = torch.zeros(T, device=pred.device, dtype=pred.dtype)
    if T > 1:
        turnover[0] = torch.abs(weights[0]).sum()
        turnover[1:] = torch.abs(weights[1:] - weights[:-1]).sum(dim=1)
    net_ret = gross_ret - turnover * float(fee)
    valid = torch.isfinite(net_ret)
    if valid.sum() < 3:
        return 0.0
    r = net_ret[valid]
    out = r.mean() / (r.std(unbiased=False) + EPS) * math.sqrt(float(annualization))
    return 0.0 if not torch.isfinite(out) else float(out.item())


_FITNESS_MAP = {
    "ic": TensorFitness(mean_ic, "ic", True),
    "pearson": TensorFitness(mean_ic, "ic", True),
    "rank_ic": TensorFitness(mean_rank_ic, "rank_ic", True),
    "spearman": TensorFitness(mean_rank_ic, "rank_ic", True),
    "icir": TensorFitness(icir, "icir", True),
    "rank_icir": TensorFitness(rank_icir, "rank_icir", True),
    "long_short_sharpe": TensorFitness(long_short_sharpe, "long_short_sharpe", True),
    "sharpe": TensorFitness(long_short_sharpe, "long_short_sharpe", True),
}


def get_tensor_fitness(name_or_obj) -> TensorFitness:
    if isinstance(name_or_obj, TensorFitness):
        return name_or_obj
    if name_or_obj not in _FITNESS_MAP:
        raise ValueError(f"Unsupported GPU objective {name_or_obj!r}. Valid: {sorted(_FITNESS_MAP)}")
    return _FITNESS_MAP[name_or_obj]
