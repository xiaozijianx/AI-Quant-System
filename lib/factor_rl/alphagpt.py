# -*- coding: utf-8 -*-
"""
lib/factor_rl/alphagpt.py -- AlphaGPT 生成模型 (深度复刻 AlphaMaster model_core/alphagpt.py)

Looped Transformer: d_model=96, 3层 x 3循环, nhead=4, FFN=192, SwiGLU, RMSNorm。
自回归生成: 从 zero prefix 开始, 每步取最后一个 token 的 logits 采样下一个 token。
LoRD 低秩正则化: Newton-Schulz 迭代对 attention 参数做低秩衰减。
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from .vocab import FORMULA_VOCAB


class RMSNorm(nn.Module):
    def __init__(self, d_model, eps=1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(d_model))
        self.eps = eps

    def forward(self, x):
        rms = torch.sqrt(torch.mean(x ** 2, dim=-1, keepdim=True) + self.eps)
        return (x / rms) * self.weight


class SwiGLU(nn.Module):
    def __init__(self, d_in, d_ff):
        super().__init__()
        self.w = nn.Linear(d_in, d_ff * 2)
        self.fc = nn.Linear(d_ff, d_in)

    def forward(self, x):
        x_glu = self.w(x)
        x, gate = x_glu.chunk(2, dim=-1)
        x = x * F.silu(gate)
        return self.fc(x)


class LoopedTransformerLayer(nn.Module):
    def __init__(self, d_model, nhead, dim_feedforward, num_loops=3, dropout=0.1):
        super().__init__()
        self.num_loops = num_loops
        self.attention = nn.MultiheadAttention(d_model, nhead, batch_first=True, dropout=dropout)
        self.norm1 = RMSNorm(d_model)
        self.norm2 = RMSNorm(d_model)
        self.ffn = SwiGLU(d_model, dim_feedforward)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, mask=None, is_causal=False):
        for _ in range(self.num_loops):
            x_norm = self.norm1(x)
            attn_out, _ = self.attention(x_norm, x_norm, x_norm, attn_mask=mask)
            x = x + self.dropout(attn_out)
            x_norm = self.norm2(x)
            ffn_out = self.ffn(x_norm)
            x = x + self.dropout(ffn_out)
        return x


class LoopedTransformer(nn.Module):
    def __init__(self, d_model=96, nhead=4, num_layers=3, dim_feedforward=192,
                 num_loops=3, dropout=0.1):
        super().__init__()
        self.layers = nn.ModuleList([
            LoopedTransformerLayer(d_model, nhead, dim_feedforward, num_loops, dropout)
            for _ in range(num_layers)
        ])

    def forward(self, x, mask=None, is_causal=False):
        for layer in self.layers:
            x = layer(x, mask=mask, is_causal=is_causal)
        return x


class MTPHead(nn.Module):
    def __init__(self, d_model, vocab_size, num_tasks=3):
        super().__init__()
        self.head = nn.Linear(d_model, vocab_size)
        self.num_tasks = num_tasks

    def forward(self, x):
        logits = self.head(x)
        return logits, None  # 返回 (logits, task_probs=None) 保持签名兼容


class AlphaGPT(nn.Module):
    def __init__(self):
        super().__init__()
        self.d_model = 96
        self.vocab_size = FORMULA_VOCAB.size
        self._max_seq = 20
        self.token_emb = nn.Embedding(self.vocab_size, self.d_model)
        self.pos_emb = nn.Parameter(torch.zeros(1, 20, self.d_model))
        self.blocks = LoopedTransformer(d_model=96, nhead=4, num_layers=3,
                                        dim_feedforward=192, num_loops=3, dropout=0.1)
        self.ln_f = RMSNorm(96)
        self.mtp_head = MTPHead(96, self.vocab_size, num_tasks=3)

    def forward(self, idx):
        """idx: [Batch, SeqLen] -> (logits, value, task_probs)"""
        T = idx.shape[1]
        x = self.token_emb(idx) + self.pos_emb[:, :T, :]
        mask = nn.Transformer.generate_square_subsequent_mask(T).to(idx.device)
        x = self.blocks(x, mask=mask, is_causal=True)
        x = self.ln_f(x)
        last_emb = x[:, -1, :]  # 只取最后一个 token 的 embedding
        logits, task_probs = self.mtp_head(last_emb)
        return logits, None, task_probs


class NewtonSchulzLowRankDecay:
    """LoRD 低秩正则化: Newton-Schulz 迭代对 attention 参数做低秩衰减"""

    def __init__(self, named_parameters, decay_rate=1e-3, num_iterations=5,
                 target_keywords=None):
        target_keywords = target_keywords or ["attention", "qk_norm"]
        self.params_to_decay = [
            (name, param) for name, param in named_parameters
            if param.ndim == 2 and any(k in name for k in target_keywords)
        ]
        self.decay_rate = decay_rate
        self.num_iterations = num_iterations

    @torch.no_grad()
    def step(self):
        for name, W in self.params_to_decay:
            X = W.float()
            r, c = X.shape
            transposed = False
            if r > c:
                X = X.T
                transposed = True
            X = X / (X.norm() + 1e-8)
            Y = X.clone()
            I = torch.eye(Y.shape[1], device=Y.device)
            for _ in range(self.num_iterations):
                A = Y.T @ Y
                Y = 0.5 * Y @ (3.0 * I - A)
            if transposed:
                Y = Y.T
            W.sub_(self.decay_rate * Y)


class StableRankMonitor:
    """稳定秩监控"""

    def __init__(self, model, target_keywords=None):
        target_keywords = target_keywords or ["in_proj", "out_proj", "qk_norm"]
        self.params = [
            (name, param) for name, param in model.named_parameters()
            if param.ndim == 2 and any(k in name for k in target_keywords)
        ]
        self.history = []

    def compute(self):
        ranks = []
        for name, W in self.params:
            try:
                S = torch.linalg.svdvals(W.float())
                stable_rank = (S.norm() ** 2) / (S[0] ** 2 + 1e-9)
                ranks.append(float(stable_rank))
            except Exception:
                pass
        if ranks:
            avg = sum(ranks) / len(ranks)
            self.history.append(avg)
            return avg
        return None
