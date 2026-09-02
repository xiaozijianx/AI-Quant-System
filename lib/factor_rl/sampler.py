# -*- coding: utf-8 -*-
"""
lib/factor_rl/sampler.py -- ConstrainedSampler 约束采样器 (深度复刻 AlphaMaster model_core/engine.py)

保证 100% 采样出合法公式:
  1. 栈深度约束: 通过 delta (特征 +1, 算子 1-arity) 追踪栈深度, 用"未来步数 x 最大弹栈/压栈数"
     的上下界约束, 保证最终栈恰好为 1。
  2. 恒正感染约束: 感染链 >= 2 禁传播算子, >= 3 强制恢复或结束, 防止因子退化为 beta。
"""
from __future__ import annotations

import torch
from torch.distributions import Categorical

from .vocab import FORMULA_VOCAB
from .ops import OPERATOR_REGISTRY, POSITIVE_ONLY_OPS, INFECTED_PROPAGATING_OPS, SIGN_RESTORE_OPS


class ConstrainedSampler:
    def __init__(self, vocab_size, feat_offset, arity_map, positive_only_ids):
        self.vocab_size = vocab_size
        self.feat_offset = feat_offset
        self.arity_map = arity_map
        self.positive_only_ids = positive_only_ids
        # delta: 特征 +1, 算子 1-arity
        self.delta = torch.zeros(vocab_size, dtype=torch.long)
        for tid in range(vocab_size):
            if tid < feat_offset:
                self.delta[tid] = 1  # 特征压栈
            else:
                self.delta[tid] = 1 - arity_map[tid]  # 算子弹栈
        # 感染相关 token id 集合
        self.infected_propagating_ids = set()
        self.sign_restore_ids = set()
        for i, name in enumerate(FORMULA_VOCAB.operator_names):
            tid = feat_offset + i
            if name in INFECTED_PROPAGATING_OPS:
                self.infected_propagating_ids.add(tid)
            if name in SIGN_RESTORE_OPS:
                self.sign_restore_ids.add(tid)

    def valid_mask(self, stack_depth, remaining, prev_token, infected_chain_len):
        """生成合法 token 掩码 (True=合法)

        stack_depth: 当前栈中元素数 (初始 0, 第一个 token 必须是特征压栈)。
        remaining: 当前步之后剩余步数 (最后一步为 0)。
        约束:
          - 特征 token: 压栈, new_depth = stack_depth + 1
          - 算子 token: 需栈中元素数 >= arity, new_depth = stack_depth + 1 - arity
          - new_depth >= 1 (栈不能为空)
          - 未来 remaining 步最多弹 2*remaining 个 / 压 1*remaining 个, 最终栈必须恰好为 1
        """
        mask = torch.ones(self.vocab_size, dtype=torch.bool)
        for tid in range(self.vocab_size):
            if tid < self.feat_offset:
                # 特征 token: 压栈
                new_depth = stack_depth + 1
            else:
                # 算子 token: 需栈中元素数 >= arity
                arity = self.arity_map[tid]
                if stack_depth < arity:
                    mask[tid] = False  # 栈中元素不足
                    continue
                new_depth = stack_depth + 1 - arity
            if new_depth < 1:
                mask[tid] = False  # 栈不能为空
                continue
            # 未来 remaining 步的栈深度上下界 (每步最多弹 2 个 / 压 1 个)
            min_future = new_depth - 2 * remaining
            max_future = new_depth + remaining
            if 1 < min_future or 1 > max_future:
                mask[tid] = False  # 无法收束到栈=1
                continue
            # 恒正感染约束
            if infected_chain_len >= 2 and tid in self.infected_propagating_ids:
                mask[tid] = False
            if infected_chain_len >= 3:
                if tid in self.infected_propagating_ids or tid in self.positive_only_ids:
                    mask[tid] = False
        return mask

    def update_infection(self, token, infected_chain_len):
        """更新感染链长度 (与原版 AlphaMaster 一致):
        特征 token 不改变感染状态; 恒正算子 +1; 恢复算子归 0; 传播算子已感染时 +1"""
        if token < self.feat_offset:
            return infected_chain_len
        if token in self.positive_only_ids:
            return infected_chain_len + 1
        if token in self.infected_propagating_ids:
            if infected_chain_len > 0:
                return infected_chain_len + 1
            return 0
        if token in self.sign_restore_ids:
            return 0
        return infected_chain_len

    def apply_mask_to_logits(self, logits, stack_depths, step, max_len,
                             prev_tokens, infected_chain_lens):
        """对每个 batch 样本施加合法掩码, 非法 token logits 置 -1e9"""
        remaining = max_len - step - 1
        masked = logits.clone()
        for b in range(logits.shape[0]):
            m = self.valid_mask(stack_depths[b], remaining, prev_tokens[b], infected_chain_lens[b])
            masked[b, ~m] = -1e9
        return masked
