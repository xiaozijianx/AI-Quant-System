# -*- coding: utf-8 -*-
"""
lib/factor_rl/island.py -- Island 多起点引擎 (深度复刻 AlphaMaster model_core/island_engine.py)

同时维护 N 个独立的 AlphaEngine (island), 每个 island 独立探索不同的公式空间区域。
每隔 migration_interval 步, 汇总所有 island 的 elite, 取 Top-K 注入其他 island (精英迁移),
并同步全局最优到各 island 的 best_snapshot (restart 时从全局最优恢复)。

算法层面多群体演化 (非 Python multiprocessing): CPU 训练下串行轮流训练更高效。
"""
from __future__ import annotations

import copy
import heapq
import os

import torch

from .trainer import AlphaEngine


class IslandAlphaEngine:
    """管理多个 AlphaEngine 组成 island population"""

    def __init__(self, config=None, n_islands: int = 2,
                 migration_interval: int = 100, migration_top_k: int = 5):
        self.cfg = config or {}
        self.n_islands = int(n_islands or 2)
        self.migration_interval = int(migration_interval or 100)
        self.migration_top_k = int(migration_top_k or 5)

        self.islands = []
        for i in range(self.n_islands):
            isl = AlphaEngine(self.cfg)
            # 每个 island 不同随机初始化, 增加多样性
            torch.manual_seed((self.cfg.get("random_state", 42) or 42) + i * 17)
            isl.model = isl.model.__class__()
            isl.opt = torch.optim.AdamW(isl.model.parameters(), lr=isl.lr)
            self.islands.append(isl)

        self.global_best_score = -float("inf")
        self.global_best_formula = None
        self.global_best_island = -1
        self.migration_events = []

    def _migrate_elites(self, step: int):
        """在所有 islands 之间交换 Top-K elite 公式"""
        if self.n_islands < 2:
            return
        all_elites = []
        for isl in self.islands:
            all_elites.extend(isl._elite_pool)

        if len(all_elites) < 2:
            return

        # 去重: 相同公式保留最高分和最新 birth_step
        best_by_formula = {}
        for sc, cnt, toks, birth in all_elites:
            key = str(toks)
            if key not in best_by_formula or sc > best_by_formula[key][0]:
                best_by_formula[key] = (sc, cnt, toks, birth)

        # 按得分排序取 Top-K
        sorted_elites = sorted(best_by_formula.values(), key=lambda x: x[0], reverse=True)
        top_elites = sorted_elites[:self.migration_top_k]

        # 注入到每个 island
        injected = 0
        for isl in self.islands:
            for sc, cnt, toks, birth in top_elites:
                isl._update_elite_pool([list(toks)], [sc], step)
                injected += 1

        self.migration_events.append({
            "step": step,
            "collected": len(all_elites),
            "deduped": len(best_by_formula),
            "injected": injected,
            "top_formula": _decode_tokens(top_elites[0][2]) if top_elites else None,
        })

    def _update_global_best(self):
        for i, isl in enumerate(self.islands):
            if isl.best_score > self.global_best_score:
                self.global_best_score = isl.best_score
                self.global_best_formula = isl.best_formula
                self.global_best_island = i

    def train(self, feat_tensor, future_ret, rebal_period=5,
              progress_cb=None, restart_cb=None, elite_cb=None,
              checkpoint_dir=None, resume=False, val_future_ret=None,
              resume_scope=None):
        """主训练循环: 每个 island 轮流训练一个阶段, 然后迁移 elite"""
        total_steps = self.islands[0].train_steps
        n_phases = max(1, total_steps // self.migration_interval)
        train_steps_per_island = self.migration_interval

        for phase in range(n_phases):
            start = phase * self.migration_interval
            end = min((phase + 1) * self.migration_interval, total_steps)
            steps = end - start

            for i, isl in enumerate(self.islands):
                # 每个 island 独立训练一个阶段
                isl.train_steps = steps
                # 每个 phase 分到不同 checkpoint 子目录, 支持多岛续训
                isl_ckpt_dir = (os.path.join(checkpoint_dir, f"island_{i}")
                                if checkpoint_dir else None)
                isl.train(feat_tensor, future_ret, rebal_period=rebal_period,
                          progress_cb=progress_cb, restart_cb=restart_cb,
                          elite_cb=elite_cb, checkpoint_dir=isl_ckpt_dir,
                          resume=resume, val_future_ret=val_future_ret,
                          resume_scope=resume_scope)
                self._update_global_best()

            # 阶段结束: 迁移 elite
            self._migrate_elites(end)

            # 同步全局最优到每个 island 的 best_snapshot (restart 时从全局最优恢复)
            best_isl_idx = self.global_best_island
            if best_isl_idx >= 0 and best_isl_idx < len(self.islands):
                best_isl = self.islands[best_isl_idx]
                for isl in self.islands:
                    if self.global_best_score > isl.best_score:
                        isl.best_score = self.global_best_score
                        isl.best_formula = copy.deepcopy(self.global_best_formula)
                        if best_isl._best_snapshot is not None:
                            isl._best_snapshot = copy.deepcopy(best_isl._best_snapshot)

        self._update_global_best()

        # 返回全局最优
        best_island = self.islands[self.global_best_island] if self.global_best_island >= 0 else self.islands[0]
        return {
            "best_score": self.global_best_score,
            "best_formula": self.global_best_formula,
            "training_history": self._merge_history(),
            "elite_pool_size": len(best_island._elite_pool),
            "restart_count": sum(isl.restart_count for isl in self.islands),
            "migration_events": self.migration_events,
            "n_islands": self.n_islands,
        }

    def _merge_history(self):
        """合并各岛训练历史 (取全局最优岛的)"""
        best_isl = self.islands[self.global_best_island] if self.global_best_island >= 0 else self.islands[0]
        return best_isl.training_history

    def collect_candidates(self, max_count=100):
        """收集所有岛的候选公式 (token 序列), 供解码"""
        candidates_raw = []
        seen = set()
        if self.global_best_formula:
            candidates_raw.append(self.global_best_formula)
        for isl in self.islands:
            for score, counter, fml, birth in sorted(isl._elite_pool, key=lambda x: x[0], reverse=True):
                candidates_raw.append(fml)
        unique = []
        for fml in candidates_raw:
            key = tuple(fml)
            if key not in seen:
                seen.add(key)
                unique.append(fml)
        return unique[:max_count]


def _decode_tokens(tokens) -> str:
    """token 序列 -> 本系统表达式 (供事件展示)"""
    from .pipeline import _decode_formula
    return _decode_formula(tokens)
