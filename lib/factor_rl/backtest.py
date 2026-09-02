# -*- coding: utf-8 -*-
"""
lib/factor_rl/backtest.py -- RL 因子挖掘多目标奖励 (适配本系统截面 RankIC 系)

奖励口径 (见 RL 因子挖掘引擎实施方案.md 5.4):
    reward = w_ic * mean_rank_ic + w_ir * rank_ic_ir + w_layered * 分层单调性
             - parsimony * 公式长度

分量:
  - mean_rank_ic: 截面 RankIC 均值 (主指标)
  - rank_ic_ir:   IC 均值 / IC 标准差 (稳定性)
  - 分层单调性:   分层回测的 Q5-Q1 单调性得分
  - 复杂度惩罚:   parsimony * 公式长度 (防过拟合)

辅助机制 (复刻 AlphaMaster):
  - IC 门控: |IC| < 阈值奖励打折; IC < 0 不判死 (方向由 direction 表达)
  - 重复惩罚: 相邻重复 token 惩罚
  - 相关性惩罚: 与因子池已有因子相关 > 阈值乘 0.8
"""
from __future__ import annotations

import numpy as np
import torch


def _spearman_rank(x: torch.Tensor, dim: int = 0) -> torch.Tensor:
    """逐列 (dim=0) 计算排名 (用于截面 RankIC)"""
    sorted_idx = x.argsort(dim=dim)
    ranks = torch.empty_like(sorted_idx, dtype=torch.float)
    if x.dim() == 1:
        # 1D 输入: 直接排名
        arange = torch.arange(x.shape[0], device=x.device).float()
        ranks.scatter_(0, sorted_idx, arange)
    else:
        arange = torch.arange(x.shape[dim], device=x.device).float().unsqueeze(1)
        ranks.scatter_(dim, sorted_idx, arange)
    return ranks


def _rank_masked(x: torch.Tensor, valid: torch.Tensor) -> torch.Tensor:
    """逐列 (每时间步) 只对 valid 元素排名, 返回 [N, T] 秩 (0..N-1)

    invalid 位置填入 -inf 参与 argsort (排到末位, 不影响有效元素的名次),
    返回秩后由调用方按 valid 掩码做均值/协方差的加权聚合。
    """
    x_safe = torch.where(valid, x, torch.tensor(float("-inf"), device=x.device))
    sorted_idx = torch.argsort(x_safe, dim=0)  # [N, T]
    ranks = torch.empty_like(sorted_idx, dtype=torch.float)
    arange = torch.arange(x.shape[0], device=x.device).float().unsqueeze(1)
    ranks.scatter_(0, sorted_idx, arange.expand_as(sorted_idx))
    return ranks


def mean_rank_ic(factor: torch.Tensor, future_ret: torch.Tensor,
                 rebal_period: int = 5) -> dict:
    """计算截面 RankIC 系 (向量化: 全时间步一次排秩, 避免逐日 Python 循环)

    factor:     [N, T] 因子张量
    future_ret: [N, T] 未来 rebal_period 日收益张量 (已对齐)
    rebal_period: 调仓周期
    返回: {rank_ic_mean, rank_ic_ir, ic_series}
    """
    N, T = factor.shape
    if N < 3 or T < 5:
        return {"rank_ic_mean": 0.0, "rank_ic_ir": 0.0, "ic_series": []}

    valid = ~(torch.isnan(factor) | torch.isnan(future_ret))  # [N, T]
    count = valid.sum(dim=0).float()  # [T]
    f_r = _rank_masked(factor, valid)     # [N, T] 秩
    r_r = _rank_masked(future_ret, valid)  # [N, T] 秩

    # 只对有效元素做中心化 (无效位置先映射为均值 -> 中心化后为 0, 不贡献任何统计量)
    mf = (torch.where(valid, f_r, torch.zeros_like(f_r)).sum(dim=0)) / count  # [T]
    mr = (torch.where(valid, r_r, torch.zeros_like(r_r)).sum(dim=0)) / count
    Fc = torch.where(valid, f_r, mf.unsqueeze(0)) - mf.unsqueeze(0)
    Rc = torch.where(valid, r_r, mr.unsqueeze(0)) - mr.unsqueeze(0)

    # 总体 Pearson (与逐日循环口径完全一致: 除以 count 而非 count-1)
    cov = (Fc * Rc * valid).sum(dim=0) / count
    sx = ((Fc * Fc * valid).sum(dim=0) / count).clamp_min(1e-12).sqrt()
    sy = ((Rc * Rc * valid).sum(dim=0) / count).clamp_min(1e-12).sqrt()
    ic_t = torch.where(count >= 3, cov / (sx * sy + 1e-12), torch.zeros_like(cov))

    ic_list = ic_t.tolist()
    valid_ic = ic_t[count >= 3]
    if valid_ic.numel() == 0:
        return {"rank_ic_mean": 0.0, "rank_ic_ir": 0.0, "ic_series": []}
    ic_mean = float(valid_ic.mean().item())
    ic_std = float(valid_ic.std(unbiased=True).item()) if valid_ic.numel() > 1 else 0.0
    ic_ir = ic_mean / ic_std if ic_std > 1e-8 else 0.0
    return {
        "rank_ic_mean": ic_mean,
        "rank_ic_ir": ic_ir,
        "ic_series": ic_list,
    }


def layered_monotonicity(factor: torch.Tensor, future_ret: torch.Tensor,
                         n_layers: int = 5) -> float:
    """分层单调性得分: Q5-Q1 分层收益的单调性 (向量化)

    按因子值的分位数把每个时间步的截面分成 n_layers 层, 计算各层平均未来收益,
    汇总所有时间步后, 求"层序号 vs 层平均收益"的 Spearman 相关 (单调性)。

    向量化做法:
      - torch.nanquantile 一次性求每列 (每时间步) 的 n_layers+1 个分位边界
      - 广播比较得到每个元素所属层 -> 逐层掩码聚合平均收益 (仅 n_layers 次小循环)
      - 只保留"所有层非空 且 有效样本 >= n_layers*2"的时间步
    与原逐日循环实现对稠密数据结果一致 (每期各层均非空时), 且无逐日 Python 循环。
    """
    N, T = factor.shape
    if N < n_layers * 2 or T < 5:
        return 0.0

    device = factor.device
    valid = ~(torch.isnan(factor) | torch.isnan(future_ret))
    count = valid.sum(dim=0).float()  # [T]
    # 无效位置填 NaN (供 nanquantile 忽略), 参与比较时自动落入低层 (后被 valid 门控排除)
    f_masked = torch.where(valid, factor, torch.tensor(float("nan"), device=device))
    qvec = torch.linspace(0.0, 1.0, n_layers + 1, device=device)
    qvals = torch.nanquantile(f_masked, qvec, dim=0)  # [n_layers+1, T]

    # 层归属: f >= 第 li 个下界 (累加) - 1, clamp 到 [0, n_layers-1]
    lb = qvals[:-1].unsqueeze(0)  # [1, n_layers, T]
    bins = (factor.unsqueeze(1) >= lb).sum(dim=1) - 1  # [N, T]
    bins = bins.clamp(0, n_layers - 1)

    layer_means = torch.zeros(n_layers, T, dtype=torch.float32, device=device)
    cnt_layer = torch.zeros(n_layers, T, dtype=torch.float32, device=device)
    for li in range(n_layers):
        m = (bins == li) & valid
        cnt_layer[li] = m.sum(dim=0).float()
        layer_means[li] = torch.where(m, future_ret, torch.zeros_like(future_ret)).sum(dim=0) \
            / cnt_layer[li].clamp_min(1.0)

    # 保留"所有层均非空 且 有效样本 >= n_layers*2"的时间步
    keep_t = (cnt_layer.min(dim=0).values >= 1.0) & (count >= n_layers * 2)
    if keep_t.sum().item() == 0:
        return 0.0
    mean_layers = layer_means[:, keep_t].mean(dim=1)  # [n_layers]
    # Spearman: 层序号 vs 层平均收益 (用秩相关, 与 scipy spearmanr 语义一致)
    xr = torch.arange(n_layers, dtype=torch.float32, device=device)
    rr = _spearman_rank(mean_layers).float()
    xc = xr - xr.mean()
    rc = rr - rr.mean()
    denom = (xc.norm() * rc.norm()).clamp_min(1e-8)
    corr = float(((xc * rc).sum() / denom).item())
    if corr != corr:  # NaN 防御
        return 0.0
    return corr


def build_walk_forward_folds(T: int, n_folds: int = 4, gap: int = 20):
    """构建 walk-forward 折叠 (逐位复刻原版 engine._build_walk_forward_folds)

    原版逻辑:
      fold_size = T // n_folds
      当 total_required = fold_size*n_folds + gap*(n_folds-1) > T 时,
        把 gap 缩小到 (T - fold_size*n_folds) // n_folds
      然后 k = 1..n_folds-1 生成 n_folds-1 折:
        train = [(k-1)*fold_size, k*fold_size)
        val   = [k*fold_size + gap, min(val_start + fold_size, T))
      数据不足时退化为全量单折。
    """
    if n_folds < 2 or T < 2:
        return [(list(range(T)), [])]
    fold_size = T // n_folds
    if fold_size < 2:
        return [(list(range(T)), [])]
    total_required = fold_size * n_folds + gap * (n_folds - 1)
    if total_required > T:
        gap = max(0, (T - fold_size * n_folds) // n_folds)
    folds = []
    for k in range(1, n_folds):
        train_start = (k - 1) * fold_size
        train_end = k * fold_size
        val_start = train_end + gap
        val_end = min(val_start + fold_size, T)
        if val_start >= T or val_end <= val_start:
            break
        folds.append((list(range(train_start, train_end)), list(range(val_start, val_end))))
    if not folds:
        return [(list(range(T)), [])]
    return folds


class RLBacktest:
    """RL 因子挖掘多目标奖励计算器 (适配截面 RankIC 系)"""

    def __init__(self, ic_weight=1.0, ir_weight=0.3, layered_weight=0.2,
                 parsimony=0.001, ic_gate_thresh=0.01, ic_gate_mult=1.15,
                 ic_neg_mult=0.75, corr_thresh=0.85, corr_penalty=0.8):
        self.ic_weight = ic_weight
        self.ir_weight = ir_weight
        self.layered_weight = layered_weight
        self.parsimony = parsimony
        self.ic_gate_thresh = ic_gate_thresh
        self.ic_gate_mult = ic_gate_mult
        self.ic_neg_mult = ic_neg_mult
        self.corr_thresh = corr_thresh
        self.corr_penalty = corr_penalty

    def evaluate(self, factor: torch.Tensor, future_ret: torch.Tensor,
                 formula_len: int, rebal_period: int = 5,
                 factor_pool=None) -> dict:
        """评估单条公式的奖励

        factor:     [N, T] 因子张量 (已由 vm 标准化)
        future_ret: [N, T] 未来收益张量
        formula_len: 公式 token 长度 (复杂度惩罚)
        factor_pool: 已有因子池 (相关性惩罚用), 元素为 [N, T] 张量
        返回: {reward, rank_ic_mean, rank_ic_ir, layered, complexity_penalty, ...}
        """
        # 1. 截面 RankIC 系
        ic_res = mean_rank_ic(factor, future_ret, rebal_period)
        rank_ic = ic_res["rank_ic_mean"]
        rank_ic_ir = ic_res["rank_ic_ir"]

        # 2. 分层单调性
        layered = layered_monotonicity(factor, future_ret, n_layers=5)

        # 3. 基础奖励
        reward = (self.ic_weight * rank_ic
                  + self.ir_weight * rank_ic_ir
                  + self.layered_weight * layered)

        # 4. IC 门控 (方向性)
        if abs(rank_ic) > self.ic_gate_thresh:
            if rank_ic > 0:
                reward *= self.ic_gate_mult
            else:
                reward *= self.ic_neg_mult

        # 5. 复杂度惩罚
        complexity_penalty = self.parsimony * formula_len
        reward -= complexity_penalty

        # 6. 相关性惩罚 (与因子池已有因子相关 > 阈值乘 0.8)
        corr_penalty_applied = False
        if factor_pool:
            for pf in factor_pool:
                if pf.shape != factor.shape:
                    continue
                valid = ~(torch.isnan(factor) | torch.isnan(pf))
                if valid.sum() < 3:
                    continue
                fv = factor[valid]
                pv = pf[valid]
                fr = _spearman_rank(fv)
                pr = _spearman_rank(pv)
                fr = fr - fr.mean()
                pr = pr - pr.mean()
                denom = (fr.norm() * pr.norm()).clamp_min(1e-8)
                corr = float((fr * pr).sum() / denom)
                if abs(corr) > self.corr_thresh:
                    reward *= self.corr_penalty
                    corr_penalty_applied = True
                    break

        return {
            "reward": reward,
            "rank_ic_mean": rank_ic,
            "rank_ic_ir": rank_ic_ir,
            "layered": layered,
            "complexity_penalty": complexity_penalty,
            "corr_penalty_applied": corr_penalty_applied,
        }

    def evaluate_fold(self, factor: torch.Tensor, future_ret: torch.Tensor,
                      train_idx, val_idx, formula_len: int, rebal_period: int = 5,
                      factor_pool=None):
        """单折 walk-forward 评估, 返回 (train_score, val_score, train_ic_mean)

        - train_score: 训练段多目标奖励 (进 REINFORCE 梯度)
        - val_score:   验证段奖励 x OOS 门控 (选冠军 / 精英池排序)
        - train_ic_mean: 训练段 RankIC 均值 (供因子池去冗余统计)

        OOS 门控复刻原版 MT5Backtest (val_sortino 替换为 val RankIC):
          val_ic <= 0 -> x max(0.1, 0.5 + val_ic*0.4)
          val_ic > 0  -> x min(1.2, 1.0 + val_ic*0.1)
        """
        if len(train_idx) < 5:
            return -5.0, -5.0, 0.0
        tr = self.evaluate(factor[:, train_idx], future_ret[:, train_idx],
                           formula_len, rebal_period, factor_pool)
        train_score = tr["reward"]
        train_ic = tr["rank_ic_mean"]
        if not val_idx or len(val_idx) < 5:
            return train_score, train_score, train_ic
        va = self.evaluate(factor[:, val_idx], future_ret[:, val_idx],
                           formula_len, rebal_period, factor_pool)
        val_ic = va["rank_ic_mean"]
        if val_ic <= 0:
            gate = max(0.1, 0.5 + val_ic * 0.4)
        else:
            gate = min(1.2, 1.0 + val_ic * 0.1)
        return train_score, va["reward"] * gate, train_ic
