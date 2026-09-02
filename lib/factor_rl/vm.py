# -*- coding: utf-8 -*-
"""
lib/factor_rl/vm.py -- StackVM 执行器 (深度复刻 AlphaMaster model_core/vm.py)

栈式执行: 特征 token 压栈, 算子 token 弹 arity 个操作数 -> 计算 -> 压栈。
最终栈必须恰好剩 1 个张量才算合法公式。
输出标准化 _normalize_output:
  - N>1: 截面 zscore (每时间步跨股票), clip [-3,3]
  - N=1: 滚动时序 zscore (窗口 500, 因果), warm-up 期输出 0
恒正感染模型: 防止因子退化为 beta (恒正算子连续使用丢失符号信息)。
"""
from __future__ import annotations

import torch

from .vocab import FORMULA_VOCAB
from .ops import OPERATOR_REGISTRY, POSITIVE_ONLY_OPS, INFECTED_PROPAGATING_OPS, SIGN_RESTORE_OPS


class StackVM:
    def __init__(self):
        self.feat_offset = FORMULA_VOCAB.operator_offset
        self.op_map = {}
        self.arity_map = {}
        for i, name in enumerate(FORMULA_VOCAB.operator_names):
            tid = self.feat_offset + i
            transform, arity = OPERATOR_REGISTRY[name]
            self.op_map[tid] = transform
            self.arity_map[tid] = arity
        # 恒正算子 token id 集合
        self.positive_only_ids = set()
        self.infected_propagating_ids = set()
        self.sign_restore_ids = set()
        for i, name in enumerate(FORMULA_VOCAB.operator_names):
            tid = self.feat_offset + i
            if name in POSITIVE_ONLY_OPS:
                self.positive_only_ids.add(tid)
            if name in INFECTED_PROPAGATING_OPS:
                self.infected_propagating_ids.add(tid)
            if name in SIGN_RESTORE_OPS:
                self.sign_restore_ids.add(tid)

    def execute(self, formula_tokens, feat_tensor):
        """执行 token 序列, 返回因子张量 [N, T] 或 None (非法公式)"""
        stack = []
        for token in formula_tokens:
            if token < self.feat_offset:
                # 特征 token: 压栈
                stack.append(feat_tensor[:, token, :])  # [N, T]
            elif token in self.op_map:
                arity = self.arity_map[token]
                if len(stack) < arity:
                    return None  # 栈不足, 非法
                args = [stack.pop() for _ in range(arity)]
                args.reverse()  # 恢复原始顺序
                try:
                    res = self.op_map[token](*args)
                except Exception:
                    return None
                if torch.isnan(res).any() or torch.isinf(res).any():
                    res = torch.nan_to_num(res, nan=0.0, posinf=1.0, neginf=-1.0)
                stack.append(res)
            else:
                return None
        if len(stack) == 1:
            return self._normalize_output(stack[0])
        return None

    def _normalize_output(self, x: torch.Tensor) -> torch.Tensor:
        """输出标准化: N>1 截面 zscore, N=1 滚动时序 zscore"""
        N, T = x.shape
        if x.std() < 1e-6:
            return x  # 常数因子, 由 engine 拦截
        if N > 1:
            # 截面 zscore (跨股票, 每时间步)
            cs_mean = x.mean(dim=0, keepdim=True)
            cs_std = x.std(dim=0, keepdim=True).clamp_min(1e-8)
            cs_z = (x - cs_mean) / cs_std
            return torch.clamp(cs_z, -3.0, 3.0)
        # N=1: 滚动时序 zscore (窗口 500, 因果)
        _ROLL_WINDOW = 500
        if T < _ROLL_WINDOW:
            # 退化为 expanding zscore (仍因果)
            mean = x.cumsum(dim=1) / torch.arange(1, T + 1, dtype=x.dtype, device=x.device).unsqueeze(0)
            sq = (x * x).cumsum(dim=1) / torch.arange(1, T + 1, dtype=x.dtype, device=x.device).unsqueeze(0)
            var = (sq - mean * mean).clamp_min(0.0)
            std = var.sqrt().clamp_min(1e-8)
            ts_z = (x - mean) / std
            return torch.clamp(ts_z, -3.0, 3.0)
        import torch.nn.functional as F
        padded = F.pad(x, (_ROLL_WINDOW - 1, 0), value=0.0)
        windows = padded.unfold(1, _ROLL_WINDOW, 1)
        ts_mean = windows.mean(dim=2)
        ts_std = windows.std(dim=2).clamp_min(1e-8)
        ts_z = (x - ts_mean) / ts_std
        warmup_mask = torch.arange(T, device=x.device) < (_ROLL_WINDOW - 1)
        ts_z[:, warmup_mask] = 0.0
        return torch.clamp(ts_z, -3.0, 3.0)

    def validate_formula_structure(self, formula_tokens):
        """用感染模型校验公式结构, 返回违规原因列表 (空=合法)"""
        violations = []
        infected_chain = 0
        for token in formula_tokens:
            if token < self.feat_offset:
                # 特征 token: 不改变感染状态 (与原版 AlphaMaster 一致)
                continue
            if token in self.positive_only_ids:
                infected_chain += 1
            elif token in self.infected_propagating_ids:
                if infected_chain > 0:
                    infected_chain += 1
            elif token in self.sign_restore_ids:
                infected_chain = 0
            # 感染链过长
            if infected_chain >= 2:
                violations.append("恒正算子后连续传播算子过多 (感染链>=2)")
                break
        # 末尾处于感染状态
        if infected_chain >= 1:
            violations.append("公式末尾处于恒正感染状态")
        return violations
