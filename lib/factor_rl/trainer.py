# -*- coding: utf-8 -*-
"""
lib/factor_rl/trainer.py -- AlphaEngine 训练循环 (深度复刻 AlphaMaster model_core/engine.py)

Part A~G 全流程:
  A: 采样 n_new 条新公式 (ConstrainedSampler 约束自回归采样)
  B: 从 Elite Pool 按得分加权采样 n_elite 条历史最优公式 (回放)
  C: 全部公式 -> StackVM 执行 -> RLBacktest 多目标评分
  D: REINFORCE 策略梯度更新 (loss = -log_prob*advantage - entropy_coeff*entropy)
  E: 日志/训练历史/checkpoint 保存
  F: 迁移 hook (Island 模式, 默认单岛关闭)
  G: 熵坍塌检测 -> 重启 (best snapshot 恢复 + 噪声扰动)

数据/评价适配: 本系统为股票池 + 截面 RankIC 系 (见 backtest.py)。
"""
from __future__ import annotations

import copy
import math
import os
import random
import heapq
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import torch
from torch.distributions import Categorical

from .vocab import FORMULA_VOCAB, VOCAB_VERSION
from .alphagpt import AlphaGPT, NewtonSchulzLowRankDecay, StableRankMonitor
from .vm import StackVM
from .sampler import ConstrainedSampler
from .backtest import RLBacktest


class AlphaEngine:
    def __init__(self, config=None):
        self.cfg = config or {}
        self.device = torch.device("cpu")

        # 超参数
        self.batch_size = int(self.cfg.get("batch_size", 192))
        self.train_steps = int(self.cfg.get("train_steps", 2000))
        self.max_formula_len = int(self.cfg.get("max_formula_len", 8))
        self.lr = float(self.cfg.get("lr", 1e-3))
        self.entropy_coeff_max = float(self.cfg.get("entropy_coeff_max", 1.0))
        self.entropy_coeff_power = float(self.cfg.get("entropy_coeff_power", 1.0))
        self.entropy_collapse_thresh = float(self.cfg.get(
            "entropy_collapse_thresh", 0.15 * math.log(FORMULA_VOCAB.size)))
        self.entropy_collapse_steps = int(self.cfg.get("entropy_collapse_steps", 20))
        self.entropy_floor = bool(self.cfg.get("entropy_floor", True))
        self.entropy_floor_thresh = float(self.cfg.get("entropy_floor_thresh", 1.0))
        self.entropy_floor_lambda = float(self.cfg.get("entropy_floor_lambda", 5.0))
        self.max_restarts = int(self.cfg.get("max_restarts", 10))
        self.restart_noise = float(self.cfg.get("restart_noise", 0.25))
        self.full_reset_every = int(self.cfg.get("full_reset_every", 3))
        self.partial_reset_layers = tuple(self.cfg.get(
            "partial_reset_layers", ("ln_f", "mtp_head", "blocks", "token_emb")))
        self.adaptive_noise = bool(self.cfg.get("adaptive_noise", True))
        self.noise_min = float(self.cfg.get("noise_min", 0.15))
        self.noise_max = float(self.cfg.get("noise_max", 0.60))
        self.noise_boost_factor = float(self.cfg.get("noise_boost_factor", 2.0))
        self.stagnation_window = int(self.cfg.get("stagnation_window", 500))

        self.elite_pool_size = int(self.cfg.get("elite_pool_size", 60))
        self.elite_replay_frac = float(self.cfg.get("elite_replay_frac", 0.25))
        self.elite_reward_scale = float(self.cfg.get("elite_reward_scale", 1.2))
        self.elite_decay = bool(self.cfg.get("elite_decay", True))
        self.elite_decay_half_life = int(self.cfg.get("elite_decay_half_life", 300))

        self.reward_ema_baseline = bool(self.cfg.get("reward_ema_baseline", True))
        self.reward_ema_decay = float(self.cfg.get("reward_ema_decay", 0.95))
        self.reward_ema_warmup = int(self.cfg.get("reward_ema_warmup", 10))

        self.use_lord = bool(self.cfg.get("use_lord", True))
        self.checkpoint_interval = int(self.cfg.get("checkpoint_interval", 20))
        self.n_folds = int(self.cfg.get("n_folds", 4) or 4)
        self.wf_gap = int(self.cfg.get("wf_gap", 20) or 20)
        self.random_state = int(self.cfg.get("random_state", 42))

        # 并行公式评估 (复刻原版 ThreadPoolExecutor)
        self.parallel_eval = bool(self.cfg.get("parallel_eval", True))
        self.eval_workers = int(self.cfg.get("eval_workers", min(os.cpu_count() or 4, 8)))
        self._eval_pool = None
        self._eval_workers = 1

        # 奖励
        self.bt = RLBacktest(
            ic_weight=float(self.cfg.get("reward_ic_weight", 1.0)),
            ir_weight=float(self.cfg.get("reward_ir_weight", 0.3)),
            layered_weight=float(self.cfg.get("reward_layered_weight", 0.2)),
            parsimony=float(self.cfg.get("parsimony", 0.001)),
        )

        # 模型
        self.model = AlphaGPT().to(self.device)
        self.opt = torch.optim.AdamW(self.model.parameters(), lr=self.lr)
        self.lord_opt = NewtonSchulzLowRankDecay(
            self.model.named_parameters(), decay_rate=1e-3, num_iterations=5,
            target_keywords=["attention", "qk_norm"])
        self.rank_monitor = StableRankMonitor(self.model)

        # 执行器 / 采样器
        self.vm = StackVM()
        self.sampler = ConstrainedSampler(
            FORMULA_VOCAB.size, FORMULA_VOCAB.operator_offset,
            self.vm.arity_map, self.vm.positive_only_ids)

        # 并行评估线程池
        self._init_parallel_eval()

        # 状态
        self.best_score = -float("inf")
        self.best_formula = None
        self._best_snapshot = None
        self._elite_pool = []  # (val_score, counter, formula_tokens, birth_step)
        self._elite_counter = 0
        self.factor_pool = []  # (val_score, counter, factor_tensor)
        self._factor_pool_counter = 0
        self._reward_ema = None
        self._ema_step = 0
        self.restart_count = 0
        self.low_entropy_streak = 0
        self.stagnation_steps = 0
        self._last_best = -float("inf")
        self.training_history = []
        self._ckpt_hyperparams = None
        self._resume_scope = None

    # ============================================================
    # 重复惩罚 (复刻原版 engine._repetition_penalty: 相邻相同 token 连续段
    # 第 2 个起每个额外重复 +0.3, 同时作用于 reward 与 val_score)
    # ============================================================
    @staticmethod
    def _repetition_penalty(formula) -> float:
        if not formula:
            return 0.0
        penalty, count = 0.0, 1
        for i in range(1, len(formula)):
            if formula[i] == formula[i - 1]:
                count += 1
                if count >= 2:
                    penalty += 0.3
            else:
                count = 1
        return penalty

    # ============================================================
    # Part A: 采样新公式
    # ============================================================
    def _sample_new(self, n_new):
        inp = torch.zeros((n_new, 1), dtype=torch.long)
        stack_depths = torch.zeros(n_new, dtype=torch.long)  # 栈中元素数, 初始 0
        prev_tokens = torch.full((n_new,), -1, dtype=torch.long)
        infected_chain_lens = torch.zeros(n_new, dtype=torch.long)
        lp_all = []
        tok_all = []
        ent_all = []
        for si in range(self.max_formula_len):
            logits, _, _ = self.model(inp)
            logits = self.sampler.apply_mask_to_logits(
                logits, stack_depths, si, self.max_formula_len,
                prev_tokens, infected_chain_lens)
            dist = Categorical(logits=logits)
            a = dist.sample()
            lp_all.append(dist.log_prob(a))
            tok_all.append(a)
            ent_all.append(dist.entropy())
            inp = torch.cat([inp, a.unsqueeze(1)], dim=1)
            # 更新栈深度 / 感染链
            for b in range(n_new):
                tid = int(a[b].item())
                if tid < self.sampler.feat_offset:
                    stack_depths[b] += 1  # 特征压栈
                else:
                    stack_depths[b] += 1 - self.sampler.arity_map[tid]  # 算子弹栈
                infected_chain_lens[b] = self.sampler.update_infection(
                    tid, int(infected_chain_lens[b]))
                prev_tokens[b] = tid
        seqs = torch.stack(tok_all, dim=1)  # [n_new, max_len]
        lp = torch.stack(lp_all, dim=1)     # [n_new, max_len]
        ent = torch.stack(ent_all, dim=1)   # [n_new, max_len]
        return seqs, lp, ent

    # ============================================================
    # Part B: Elite Replay
    # ============================================================
    def _sample_elite(self, n_elite):
        if not self._elite_pool:
            return [], []
        # 计算采样权重: 分数 softmax + 时间衰减
        scores = []
        weights = []
        for val_score, counter, fml, birth in self._elite_pool:
            scores.append(val_score)
            if self.elite_decay:
                age = self._elite_counter - birth
                decay = 0.5 ** (age / self.elite_decay_half_life)
            else:
                decay = 1.0
            weights.append(decay)
        scores = np.array(scores, dtype=float)
        weights = np.array(weights, dtype=float)
        # 非有限分数兜底: 用池内最小有限分替换, 防止 NaN/inf 污染 softmax 概率
        finite = np.isfinite(scores)
        if not finite.all():
            floor = float(np.min(scores[finite])) if finite.any() else 0.0
            scores = np.where(finite, scores, floor)
        # 分数归一化到 [0,1]
        s_min = scores.min()
        s_max = scores.max()
        if s_max - s_min > 1e-8:
            norm_scores = (scores - s_min) / (s_max - s_min)
        else:
            norm_scores = np.ones_like(scores)
        # softmax (温度 0.5), 与原版 AlphaMaster 完全一致: 2.0 ** (norm / temp)。
        # 必须除以 probs 自身的和, 不能加 1e-8 再做分母:
        # 否则 p.sum() 恒偏小 1e-8 量级, 会触发 np.random.choice 抛
        # "probabilities do not sum to 1" (batch=192 下约第 20 步必现)。
        probs = np.power(2.0, np.clip(norm_scores / 0.5, -50.0, 50.0)) * weights
        total = probs.sum()
        if not np.isfinite(total) or total <= 0:
            probs = np.ones_like(probs)
        else:
            probs = probs / total
        # 最终兜底: 概率必须有限、非负
        if not np.isfinite(probs).all() or (probs < 0).any():
            probs = np.ones_like(probs)
            probs = probs / probs.sum()
        # 采样
        idxs = np.random.choice(len(self._elite_pool), size=min(n_elite, len(self._elite_pool)),
                                replace=True, p=probs)
        elite_formulas = [self._elite_pool[i][2] for i in idxs]
        return elite_formulas, idxs

    def _elite_log_prob(self, formulas):
        """对精英公式 teacher-forcing 重算 log_prob"""
        if not formulas:
            return [], []
        n = len(formulas)
        inp = torch.zeros((n, 1), dtype=torch.long)
        lp_all = []
        for si in range(self.max_formula_len):
            logits, _, _ = self.model(inp)
            dist = Categorical(logits=logits)
            # 用真实 token 计算 log_prob
            toks = torch.tensor([f[si] if si < len(f) else 0 for f in formulas],
                                dtype=torch.long)
            lp_all.append(dist.log_prob(toks))
            inp = torch.cat([inp, toks.unsqueeze(1)], dim=1)
        lp = torch.stack(lp_all, dim=1)
        return lp, [f[:self.max_formula_len] for f in formulas]

    # ============================================================
    # 并行公式评估 (复刻原版 ThreadPoolExecutor)
    # ============================================================
    def _init_parallel_eval(self):
        """初始化并行评估线程池"""
        if not self.parallel_eval or self._eval_pool is not None:
            return
        self._eval_workers = max(1, int(self.eval_workers))
        try:
            self._eval_pool = ThreadPoolExecutor(
                max_workers=self._eval_workers,
                thread_name_prefix="rl-eval",
            )
        except Exception:
            self._eval_pool = None
            self._eval_workers = 1

    def _eval_formula_task(self, idx, fml, feat_tensor, future_ret,
                           rebal_period, fold_specs, factor_pool_snapshot):
        """评估单条公式 (线程安全, 只读 self.vm/self.bt, factor_pool 用快照)"""
        with torch.no_grad():
            # 1. StackVM 执行
            res = self.vm.execute(fml, feat_tensor)
            if res is None:
                return idx, -5.0, {"reward": -5.0, "val_score": -5.0, "rank_ic_mean": 0.0,
                                   "rank_ic_ir": 0.0, "layered": 0.0,
                                   "complexity_penalty": 0.0,
                                   "corr_penalty_applied": False, "valid": False}
            # 2. 常数因子拦截
            if res.std() < 1e-4:
                return idx, -2.0, {"reward": -2.0, "val_score": -2.0, "rank_ic_mean": 0.0,
                                   "rank_ic_ir": 0.0, "layered": 0.0,
                                   "complexity_penalty": 0.0,
                                   "corr_penalty_applied": False, "valid": False}
            pool = [p[2] for p in factor_pool_snapshot[-20:]] if factor_pool_snapshot else None
            if fold_specs:
                # 3a. walk-forward 多折: 训练段得分均值进梯度, 验证段得分均值选冠军
                train_scores, val_scores, ic_scores = [], [], []
                for tr_idx, va_idx in fold_specs:
                    ts_s, vs_s, tic = self.bt.evaluate_fold(
                        res, future_ret, tr_idx, va_idx, len(fml), rebal_period, factor_pool=pool)
                    train_scores.append(ts_s)
                    val_scores.append(vs_s)
                    ic_scores.append(tic)
                if not train_scores:
                    return idx, -5.0, {"reward": -5.0, "val_score": -5.0, "rank_ic_mean": 0.0,
                                       "rank_ic_ir": 0.0, "layered": 0.0,
                                       "complexity_penalty": 0.0,
                                       "corr_penalty_applied": False, "valid": False}
                r = {"reward": float(np.mean(train_scores)),
                     "val_score": float(np.mean(val_scores)),
                     "rank_ic_mean": float(np.mean(ic_scores)),
                     "rank_ic_ir": 0.0, "layered": 0.0, "complexity_penalty": 0.0,
                     "corr_penalty_applied": False, "valid": True}
            else:
                # 3b. 全区间单次多目标奖励
                r = self.bt.evaluate(res, future_ret, len(fml), rebal_period, factor_pool=pool)
                r["val_score"] = r["reward"]
                r["valid"] = True
            # 重复惩罚 (只对合法公式, 同步扣减 reward 与 val_score, 复刻原版)
            rep = self._repetition_penalty(fml)
            if rep > 0:
                r["reward"] = r["reward"] - rep
                r["val_score"] = r["val_score"] - rep
            return idx, r["reward"], r

    # ============================================================
    # Part C: 评估
    # ============================================================
    def _evaluate(self, formulas, feat_tensor, future_ret, rebal_period, fold_specs=None):
        """评估公式列表, 返回 (rewards, results)

        fold_specs: 提供时按 walk-forward 折叠逐折评估 (训练段得分进梯度,
                    验证段得分 x OOS 门控选冠军); 缺省时用全区间单次评估 (兼容旧行为)。
        """
        pool_snapshot = list(self.factor_pool)
        if self._eval_pool is not None and len(formulas) > 1:
            futures = [
                self._eval_pool.submit(
                    self._eval_formula_task, i, fml, feat_tensor, future_ret,
                    rebal_period, fold_specs, pool_snapshot,
                )
                for i, fml in enumerate(formulas)
            ]
            outputs = [f.result() for f in futures]
        else:
            outputs = [
                self._eval_formula_task(i, fml, feat_tensor, future_ret,
                                        rebal_period, fold_specs, pool_snapshot)
                for i, fml in enumerate(formulas)
            ]
        outputs.sort(key=lambda x: x[0])
        rewards = [o[1] for o in outputs]
        results = [o[2] for o in outputs]
        return rewards, results

    # ============================================================
    # Part D: REINFORCE 更新
    # ============================================================
    def _update(self, lp_new, adv_new, lp_elite, adv_elite, ent_val):
        policy_loss = 0.0
        for ti in range(lp_new.shape[1]):
            policy_loss = policy_loss + (-lp_new[:, ti] * adv_new).mean()
        if lp_elite is not None and len(lp_elite) > 0 and lp_elite.shape[0] > 0:
            for ti in range(lp_elite.shape[1]):
                policy_loss = policy_loss + (-lp_elite[:, ti] * adv_elite * self.elite_reward_scale).mean()
        # 熵正则 (自适应系数)
        ent_coeff = self.entropy_coeff_max / ((1.0 + ent_val) ** self.entropy_coeff_power)
        loss = policy_loss - ent_coeff * ent_val
        # 熵下限惩罚
        if self.entropy_floor and ent_val < self.entropy_floor_thresh:
            loss = loss + self.entropy_floor_lambda * (self.entropy_floor_thresh - ent_val)
        self.opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
        self.opt.step()
        if self.use_lord:
            self.lord_opt.step()
        return float(loss.item())

    # ============================================================
    # Part G: 熵坍塌检测与重启
    # ============================================================
    def _check_entropy_collapse(self, ent_val):
        if ent_val < self.entropy_collapse_thresh:
            self.low_entropy_streak += 1
        else:
            self.low_entropy_streak = 0
        if self.low_entropy_streak >= self.entropy_collapse_steps:
            # 自适应噪声
            stagnation_ratio = self.stagnation_steps / max(self.stagnation_window, 1)
            raw_noise = self.restart_noise + self.noise_boost_factor * 0.1 * min(stagnation_ratio, 3.0)
            noise = max(self.noise_min, min(self.noise_max, raw_noise))
            if self.restart_count < self.max_restarts:
                self.restart_count += 1
                do_full_reset = (self.restart_count % self.full_reset_every == 0 or ent_val < 0.3)
                if do_full_reset:
                    for layer in self.model.modules():
                        if hasattr(layer, "reset_parameters"):
                            layer.reset_parameters()
                elif self._best_snapshot is not None:
                    self.model.load_state_dict(self._best_snapshot)
                    for nm, p in self.model.named_parameters():
                        if any(k in nm for k in self.partial_reset_layers):
                            p.add_(torch.randn_like(p) * noise)
                else:
                    for p in self.model.parameters():
                        p.add_(torch.randn_like(p) * noise)
                self.opt = torch.optim.AdamW(self.model.parameters(), lr=self.lr)
                self.low_entropy_streak = 0
                return {"restart": True, "restart_count": self.restart_count,
                        "noise": noise, "entropy": ent_val, "full_reset": do_full_reset}
            else:
                # 超过重启上限: 强扰动继续训练
                hard_noise = min(self.noise_max, noise * 2.0)
                if self._best_snapshot is not None:
                    self.model.load_state_dict(self._best_snapshot)
                for p in self.model.parameters():
                    p.add_(torch.randn_like(p) * hard_noise)
                self.opt = torch.optim.AdamW(self.model.parameters(), lr=self.lr)
                self.low_entropy_streak = 0
                return {"restart": True, "restart_count": self.restart_count,
                        "noise": hard_noise, "entropy": ent_val, "full_reset": False,
                        "hard_noise": True}
        return {"restart": False}

    # ============================================================
    # 精英池维护
    # ============================================================
    def _update_elite_pool(self, formulas, rewards, step):
        for fml, r in zip(formulas, rewards):
            try:
                if not np.isfinite(float(r)):
                    continue  # 非有限分数直接跳过, 防止污染精英池/断点文件
            except (TypeError, ValueError):
                continue
            self._elite_counter += 1
            heapq.heappush(self._elite_pool, (r, self._elite_counter, fml, step))
            if len(self._elite_pool) > self.elite_pool_size:
                heapq.heappop(self._elite_pool)

    def _update_factor_pool(self, formulas, results, feat_tensor):
        """更新因子池 (用于相关性惩罚)"""
        for fml, res in zip(formulas, results):
            if not res.get("valid"):
                continue
            if res["rank_ic_mean"] > 0.02:
                f = self.vm.execute(fml, feat_tensor)
                if f is not None:
                    self._factor_pool_counter += 1
                    self.factor_pool.append((res["rank_ic_mean"], self._factor_pool_counter, f))
                    if len(self.factor_pool) > 60:
                        self.factor_pool.sort(key=lambda x: x[0], reverse=True)
                        self.factor_pool = self.factor_pool[:60]

    def _compute_val_rank_ic(self, fml, val_future_ret, feat_tensor):
        """用 StackVM 执行公式, 在验证段计算 RankIC (Walk-Forward OOS 门控)"""
        try:
            res = self.vm.execute(fml, feat_tensor)
            if res is None:
                return None
            # val_future_ret 只在验证段非 NaN (其他位置为 0/mask)
            # 取 val_future_ret 有效的列 (股票) 计算截面 RankIC
            from .backtest import mean_rank_ic
            ic_res = mean_rank_ic(res, val_future_ret, rebal_period=5)
            return ic_res["rank_ic_mean"]
        except Exception:
            return None

    # ============================================================
    # 主训练循环
    # ============================================================
    def train(self, feat_tensor, future_ret, rebal_period=5,
              progress_cb=None, restart_cb=None, elite_cb=None,
              checkpoint_dir=None, resume=False, val_future_ret=None,
              fold_specs=None, resume_scope=None):
        """训练主循环

        feat_tensor: [N, F, T] 特征张量
        future_ret:  [N, T] 未来收益张量
        rebal_period: 调仓周期
        progress_cb: 每步回调 (step, stats)
        restart_cb:  熵坍塌重启回调
        elite_cb:    精英池状态回调
        checkpoint_dir: checkpoint 保存目录
        resume: 是否从 checkpoint_dir 中的最新 checkpoint 续训
        val_future_ret: [N, T] 验证段未来收益 (未启用 walk-forward 折叠时的降级 OOS 门控)
        fold_specs: walk-forward 折叠列表 [(train_idx, val_idx), ...];
                    缺省时按 n_folds/wf_gap 自动构建 (与 AlphaMaster 训练期折叠一致)
        """
        # 数据域指纹 (股票池/日期等), 由 pipeline 注入, 参与续训校验
        self._resume_scope = resume_scope or None
        # 断点续训: 若 resume 且存在 checkpoint, 先校验超参一致再续训;
        # 参数不一致(或目标步数已到断点位置)则忽略断点、从头训练。
        start_step = 0
        if resume and checkpoint_dir and os.path.isdir(checkpoint_dir):
            def _ckpt_step(fname):
                # "ckpt_step_N.pt" -> N (按真实步数排序, 避免文件名词典序误选)
                try:
                    return int(fname.rsplit("ckpt_step_", 1)[-1].split(".pt")[0])
                except (ValueError, IndexError):
                    return -1
            ckpts = [f for f in os.listdir(checkpoint_dir) if f.endswith(".pt")]
            if ckpts:
                latest = os.path.join(checkpoint_dir, max(ckpts, key=_ckpt_step))
                # 只读断点头信息做校验, 不真正加载状态
                ck_hp, ck_step = None, -1
                try:
                    _probe = torch.load(latest, map_location="cpu")
                    ck_hp = _probe.get("hyperparams")
                    ck_step = int(_probe.get("step", -1))
                    del _probe
                except Exception:
                    ck_hp, ck_step = None, -1

                can_resume = True
                ref = self._ref_params()
                if ck_hp is not None and ck_hp != ref:
                    print(f"[RL] 断点续训: 超参与断点不一致, 忽略断点从头训练."
                          f"\n      当前={ref}\n      断点={ck_hp}")
                    can_resume = False
                elif ck_step >= 0 and self.train_steps <= ck_step:
                    # 目标步数已 <= 断点步数: 续训会空跑返回旧结果, 改为从头新训练
                    print(f"[RL] 断点续训: 目标步数({self.train_steps})已达断点步数({ck_step}), "
                          f"从头训练新一轮")
                    can_resume = False

                if can_resume:
                    try:
                        start_step = self.load_checkpoint(latest) + 1
                        self._apply_val_gate_val = val_future_ret
                        print(f"[RL] 断点续训: 加载 {latest} (起步 step={start_step})")
                    except Exception as e:
                        print(f"[RL] 断点续训失败 (从头训练): {e}")
                        self.training_history = []
                        self._elite_pool = []
                        self.factor_pool = []
                        self.best_score = -float("inf")
                        self.best_formula = None
                        self._best_snapshot = None
                        self.restart_count = 0
                        self._elite_counter = 0
                        self._factor_pool_counter = 0
                        start_step = 0
                else:
                    # 从头训练: 清理状态, 保证是全新一轮
                    self.training_history = []
                    self._elite_pool = []
                    self.factor_pool = []
                    self.best_score = -float("inf")
                    self.best_formula = None
                    self._best_snapshot = None
                    self.restart_count = 0
                    self._elite_counter = 0
                    self._factor_pool_counter = 0
                    self._reward_ema = None
                    self._ema_step = 0

        n_new = self.batch_size - max(1, int(self.batch_size * self.elite_replay_frac))
        n_elite = self.batch_size - n_new
        self._val_future_ret = val_future_ret

        # walk-forward 折叠: 缺省时按 n_folds/wf_gap 自动构建 (复刻 AlphaMaster)
        if fold_specs is None and self.n_folds >= 2:
            from .backtest import build_walk_forward_folds
            fold_specs = build_walk_forward_folds(future_ret.shape[1],
                                                  n_folds=self.n_folds, gap=self.wf_gap)
        self._fold_specs = fold_specs

        for step in range(start_step, self.train_steps):
            # Part A: 采样新公式
            seqs_new, lp_new, ent_new = self._sample_new(n_new)
            formulas_new = [list(map(int, seqs_new[b].tolist())) for b in range(n_new)]

            # Part B: Elite Replay
            elite_formulas, _ = self._sample_elite(n_elite)
            lp_elite, formulas_elite = self._elite_log_prob(elite_formulas)

            # Part C: 评估
            all_formulas = formulas_new + formulas_elite
            rewards, results = self._evaluate(
                all_formulas, feat_tensor, future_ret, rebal_period, fold_specs=self._fold_specs)
            rewards_new = rewards[:n_new]
            rewards_elite = rewards[n_new:]
            # 冠军/精英池用验证段得分 (walk-forward OOS 门控后), 梯度用训练段得分
            val_scores = [r.get("val_score", r["reward"]) for r in results]

            # 更新精英池 / 因子池
            self._update_elite_pool(formulas_new, val_scores[:n_new], step)
            self._update_factor_pool(formulas_new, results[:n_new], feat_tensor)

            # 更新 best (带 Walk-Forward OOS 门控)
            for fml, res in zip(all_formulas, results):
                if not res.get("valid"):
                    continue
                candidate_score = res.get("val_score", res["reward"])
                # 未启用折叠时的降级 OOS 门控: 用验证段 RankIC 修正冠军选择
                if self._fold_specs is None and self._val_future_ret is not None:
                    val_ic = self._compute_val_rank_ic(fml, self._val_future_ret, feat_tensor)
                    # OOS 门控: 验证段 IC 显著为负或绝对值过小时, 不选为冠军
                    if res["reward"] >= 0 and val_ic is not None and abs(val_ic) < 0.005:
                        candidate_score = res["reward"] - 0.5  # 验证段 IC 弱则降分
                if candidate_score > self.best_score:
                    self.best_score = candidate_score
                    self.best_formula = fml
                    self._best_snapshot = copy.deepcopy(self.model.state_dict())

            # Part D: REINFORCE 更新
            rewards_arr = np.array(rewards, dtype=float)
            batch_mean = rewards_arr.mean()
            batch_std = rewards_arr.std()
            if batch_std < 0.1:
                batch_std = 0.1
            # EMA baseline
            if self.reward_ema_baseline and self._ema_step >= self.reward_ema_warmup \
                    and self._reward_ema is not None:
                baseline = self._reward_ema
            else:
                baseline = batch_mean
            adv = (rewards_arr - baseline) / (batch_std + 1e-5)
            adv_new = torch.tensor(adv[:n_new], dtype=torch.float32)
            adv_elite = torch.tensor(adv[n_new:], dtype=torch.float32)
            # 更新 EMA
            if self._reward_ema is None:
                self._reward_ema = batch_mean
            else:
                self._reward_ema = self.reward_ema_decay * self._reward_ema + (1 - self.reward_ema_decay) * batch_mean
            self._ema_step += 1

            ent_val = float(ent_new.mean())
            loss_val = self._update(lp_new, adv_new, lp_elite, adv_elite, ent_val)

            # 停滞检测
            if step > 0 and self.best_score <= self._last_best:
                self.stagnation_steps += 1
            else:
                self.stagnation_steps = 0
            self._last_best = self.best_score

            # Part G: 熵坍塌检测
            restart_info = self._check_entropy_collapse(ent_val)
            if restart_info.get("restart") and restart_cb:
                restart_cb(step, restart_info)

            # 记录训练历史
            self.training_history.append({
                "step": step,
                "avg_reward": float(batch_mean),
                "best_score": float(self.best_score),
                "entropy": ent_val,
                "loss": loss_val,
                "elite_pool_size": len(self._elite_pool),
                "unique_formulas": len(set(tuple(f) for f in all_formulas)),
            })

            # 进度回调
            if progress_cb:
                progress_cb(step, {
                    "step": step,
                    "train_steps": self.train_steps,
                    "best_score": float(self.best_score),
                    "avg_reward": float(batch_mean),
                    "entropy": ent_val,
                    "unique_formulas": len(set(tuple(f) for f in all_formulas)),
                    "elite_pool_size": len(self._elite_pool),
                    "restart_count": self.restart_count,
                })

            # 精英池状态回调
            if elite_cb and step % 100 == 0:
                top = sorted(self._elite_pool, key=lambda x: x[0], reverse=True)[:1]
                elite_cb(step, {
                    "pool_size": len(self._elite_pool),
                    "top_score": top[0][0] if top else None,
                    "top_formula": top[0][2] if top else None,
                })

            # checkpoint
            if checkpoint_dir and step % self.checkpoint_interval == 0:
                self.save_checkpoint(step, os.path.join(checkpoint_dir, f"ckpt_step_{step}.pt"))

        return {
            "best_score": self.best_score,
            "best_formula": self.best_formula,
            "training_history": self.training_history,
            "elite_pool_size": len(self._elite_pool),
            "restart_count": self.restart_count,
        }

    # ============================================================
    # Checkpoint
    # ============================================================
    def _ref_params(self) -> dict:
        """当前训练的超参指纹 (train_steps 除外) + 数据域指纹, 用于续训前校验

        除 train_steps 外的全部超参(采样数/公式长度/学习率/熵相关/重启与
        噪声/精英池/奖励权重/IC门控/WF/随机种子等)完全一致时才允许续训;
        任意一项不同即视为新训练, 忽略断点从头开始, 避免"改了参数却继续
        走旧训练" 的混乱行为。
        训练步数 train_steps 单独处理(见 train() 的续训判定): 允许续训时
        加大步数继续训练; 若目标步数已 <= 断点步数则从头开始新一轮。
        数据域(股票池/实际代码集/日期/调仓周期/训练验证比例)也算超参指纹
        的一部分: 换了股票池或日期就视为新数据集, 必须重新训练。
        """
        hp = {
            "batch_size": self.batch_size,
            "max_formula_len": self.max_formula_len,
            "lr": self.lr,
            "entropy_coeff_max": self.entropy_coeff_max,
            "entropy_coeff_power": self.entropy_coeff_power,
            "entropy_collapse_thresh": self.entropy_collapse_thresh,
            "entropy_collapse_steps": self.entropy_collapse_steps,
            "entropy_floor": self.entropy_floor,
            "entropy_floor_thresh": self.entropy_floor_thresh,
            "entropy_floor_lambda": self.entropy_floor_lambda,
            "max_restarts": self.max_restarts,
            "restart_noise": self.restart_noise,
            "full_reset_every": self.full_reset_every,
            "partial_reset_layers": self.partial_reset_layers,
            "adaptive_noise": self.adaptive_noise,
            "noise_min": self.noise_min,
            "noise_max": self.noise_max,
            "noise_boost_factor": self.noise_boost_factor,
            "stagnation_window": self.stagnation_window,
            "elite_pool_size": self.elite_pool_size,
            "elite_replay_frac": self.elite_replay_frac,
            "elite_reward_scale": self.elite_reward_scale,
            "elite_decay": self.elite_decay,
            "elite_decay_half_life": self.elite_decay_half_life,
            "reward_ema_baseline": self.reward_ema_baseline,
            "reward_ema_decay": self.reward_ema_decay,
            "reward_ema_warmup": self.reward_ema_warmup,
            "use_lord": self.use_lord,
            "checkpoint_interval": self.checkpoint_interval,
            "n_folds": self.n_folds,
            "wf_gap": self.wf_gap,
            "random_state": self.random_state,
            # 奖励/评分口径 (直接影响精英池打分, 改了就必须重训)
            "reward_ic_weight": self.bt.ic_weight,
            "reward_ir_weight": self.bt.ir_weight,
            "reward_layered_weight": self.bt.layered_weight,
            "parsimony": self.bt.parsimony,
            "ic_gate_thresh": self.bt.ic_gate_thresh,
            "ic_gate_mult": self.bt.ic_gate_mult,
            "ic_neg_mult": self.bt.ic_neg_mult,
            "corr_thresh": self.bt.corr_thresh,
            "corr_penalty": self.bt.corr_penalty,
        }
        # 数据域指纹 (由 pipeline 注入): 换股票池/改日期/改调仓周期都会使
        # 旧断点失效 -> 续训校验时判为不一致, 从头训练新一轮
        if self._resume_scope:
            hp["resume_scope"] = self._resume_scope
        return hp

    def save_checkpoint(self, step, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ckpt = {
            "step": step,
            "vocab_version": VOCAB_VERSION,
            "hyperparams": self._ref_params(),
            "model_state_dict": self.model.state_dict(),
            "optimizer_state_dict": self.opt.state_dict(),
            "best_score": self.best_score,
            "best_formula": self.best_formula,
            "best_snapshot": self._best_snapshot,
            "factor_pool": [(s, c, f) for s, c, f in self.factor_pool],
            "factor_pool_counter": self._factor_pool_counter,
            "elite_pool": [(s, c, f, b) for s, c, f, b in self._elite_pool],
            "elite_counter": self._elite_counter,
            "restart_count": self.restart_count,
            "training_history": self.training_history,
        }
        tmp = path + ".tmp"
        torch.save(ckpt, tmp)
        os.replace(tmp, path)

    def load_checkpoint(self, path):
        ckpt = torch.load(path, map_location=self.device)
        from .vocab import VocabVersionMismatchError
        FORMULA_VOCAB.verify(ckpt.get("vocab_version", ""))
        self.model.load_state_dict(ckpt["model_state_dict"], strict=False)
        self.opt.load_state_dict(ckpt["optimizer_state_dict"])
        self.best_score = ckpt.get("best_score", -float("inf"))
        self.best_formula = ckpt.get("best_formula")
        self._best_snapshot = ckpt.get("best_snapshot")
        self.factor_pool = list(ckpt.get("factor_pool", []))
        self._factor_pool_counter = ckpt.get("factor_pool_counter", self._factor_pool_counter)
        self._elite_pool = list(ckpt.get("elite_pool", []))
        self._elite_counter = ckpt.get("elite_counter", self._elite_counter)
        self.restart_count = ckpt.get("restart_count", 0)
        self.training_history = list(ckpt.get("training_history", []))
        self._ckpt_hyperparams = ckpt.get("hyperparams")
        return ckpt.get("step", 0)
