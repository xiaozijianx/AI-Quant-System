# -*- coding: utf-8 -*-
"""
lib/factor_rl/pipeline.py -- RL 因子挖掘高层编排 (适配本系统股票池 + 截面 RankIC)

流程:
  1. 加载股票池 + 行情面板 (复用本系统 load_daily_kline / get_pool_stocks)
  2. 构建 [N, F, T] 特征张量 (FeatureEngine)
  3. 构建未来收益张量 [N, T] (截面未来 rebal_period 日收益)
  4. 训练 RL 引擎 (AlphaEngine.train)
  5. 解码候选公式 (token -> 表达式字符串)
  6. 去冗余 + OOS 复核 (复用本系统 dedup_by_corr / oos_recheck)
  7. 返回候选 (可直接入库)
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch

from .vocab import FORMULA_VOCAB
from .features import FeatureEngine
from .trainer import AlphaEngine


def _decode_formula(tokens) -> str:
    """token 序列 -> 本系统表达式字符串 (中缀, 可被 evaluate_expression 求值)

    用 DECODE_MAP 把 RL 算子名映射为本系统参数化表达式 (如 ts_Mean_5 -> ts_Mean(x, 5))。
    特征叶子用 FEATURE_EXPRS 替换为本系统因子库表达式 (如 RET -> returns(1)), 加括号防优先级错乱。
    """
    names = [FORMULA_VOCAB.token_names[t] if t < FORMULA_VOCAB.size else "?" for t in tokens]
    from .ops import OPERATOR_REGISTRY, DECODE_MAP
    from .features import FEATURE_EXPRS
    stack = []
    for name in names:
        if name in OPERATOR_REGISTRY:
            _, arity = OPERATOR_REGISTRY[name]
            if len(stack) < arity:
                return ""
            args = [stack.pop() for _ in range(arity)]
            args.reverse()
            template = DECODE_MAP.get(name)
            if template is None:
                return ""
            # 用操作数填充模板
            try:
                if arity == 1:
                    stack.append(template.format(a=args[0]))
                elif arity == 2:
                    stack.append(template.format(a=args[0], b=args[1]))
                elif arity == 3:
                    stack.append(template.format(a=args[0], b=args[1], c=args[2]))
                else:
                    stack.append(template.format(a=args[0]))
            except Exception:
                return ""
        else:
            fexpr = FEATURE_EXPRS.get(name)
            stack.append(f"({fexpr})" if fexpr else name)
    if len(stack) == 1:
        return stack[0]
    return ""


def _build_future_returns(panel: dict, codes: list, dates: list,
                          rebal_period: int = 5) -> torch.Tensor:
    """构建未来收益张量 [N, T] (截面未来 rebal_period 日收益)"""
    N = len(codes)
    T = len(dates)
    fut = torch.zeros(N, T, dtype=torch.float32)
    for ni, code in enumerate(codes):
        df = panel.get(code)
        if df is None or "close" not in df.columns:
            continue
        close = df["close"].reindex(dates)
        # 未来 rebal_period 日收益: close[t+rebal]/close[t] - 1
        fwd = close.shift(-rebal_period) / close - 1.0
        fut[ni, :] = torch.tensor(fwd.values, dtype=torch.float32)
    return fut


def run_rl_pipeline(body: dict, progress_cb=None, restart_cb=None, elite_cb=None):
    """RL 因子挖掘主流程

    body: 请求参数 (见 /mine_rl/stream)
    返回: {candidates, training_history, best, ...}
    """
    # ============ 1. 参数解析 ============
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2023-01-01")
    end_date = body.get("end_date", "2025-12-31")
    train_ratio = float(body.get("train_ratio", 0.7))
    val_ratio = float(body.get("val_ratio", 0.15))
    rebal_period = int(body.get("rebal_period", 5))
    random_state = int(body.get("random_state", 42))

    # RL 训练参数
    rl_cfg = {
        "batch_size": int(body.get("batch_size", 64)),
        "train_steps": int(body.get("train_steps", 500)),
        "max_formula_len": int(body.get("max_formula_len", 8)),
        "lr": float(body.get("lr", 1e-3)),
        "entropy_coeff_max": float(body.get("entropy_coeff_max", 1.0)),
        "elite_pool_size": int(body.get("elite_pool_size", 60)),
        "elite_replay_frac": float(body.get("elite_replay_frac", 0.25)),
        "max_restarts": int(body.get("max_restarts", 10)),
        "restart_noise": float(body.get("restart_noise", 0.25)),
        "use_lord": bool(body.get("use_lord", True)),
        "reward_ic_weight": float(body.get("reward_ic_weight", 1.0)),
        "reward_ir_weight": float(body.get("reward_ir_weight", 0.3)),
        "reward_layered_weight": float(body.get("reward_layered_weight", 0.2)),
        "parsimony": float(body.get("parsimony", 0.001)),
        "random_state": random_state,
        "n_folds": int(body.get("n_folds", 3) or 0),
        "wf_gap": int(body.get("wf_gap", 20) or 20),
    }
    corr_thresh = float(body.get("corr_thresh", 0.8))
    return_candidates = int(body.get("return_candidates", 20))
    n_islands = int(body.get("n_islands", 1))
    migration_interval = int(body.get("migration_interval", 100))
    use_gpu = bool(body.get("use_gpu", False))
    n_folds = int(body.get("n_folds", 3) or 0)
    perm_n = int(body.get("perm_n", 0))
    resume = bool(body.get("resume", False))
    checkpoint_dir = body.get("checkpoint_dir")
    if not checkpoint_dir:
        checkpoint_dir = os.path.join("data", "factor_rl_checkpoints")

    np.random.seed(random_state)
    torch.manual_seed(random_state)

    # ============ 2. 加载股票池 + 行情面板 ============
    from lib.factor_evaluator import get_pool_stocks, get_active_stock_pool
    from lib.backtest_data import load_daily_kline

    if stock_codes:
        codes = [c for c in stock_codes if c]
    elif pool_type and pool_type != "active":
        codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
    else:
        codes = get_active_stock_pool(n=80, min_days=200)
    if not codes:
        codes = get_active_stock_pool(n=80, min_days=200)
    if len(codes) < 10:
        codes = get_active_stock_pool(n=80, min_days=100)

    panel = {}
    for c in codes:
        df = load_daily_kline(c, start_date, end_date, prefer="mysql")
        if df is not None and len(df) > 130:
            panel[c] = df
    if len(panel) < 10:
        raise ValueError(f"有效股票数不足 (需>=10, 当前 {len(panel)})")

    # 统一日期轴 (取所有股票日期的并集, 排序)
    all_dates = sorted(set().union(*[set(df.index) for df in panel.values()]))
    # 裁剪到公共区间 (取交集, 保证所有股票都有数据)
    common_dates = set(all_dates)
    for df in panel.values():
        common_dates &= set(df.index)
    dates = sorted(common_dates)
    if len(dates) < 150:
        raise ValueError(f"公共交易日不足 (需>=150, 当前 {len(dates)})")

    codes = [c for c in codes if c in panel]

    # ============ 3. 三段分段 ============
    from lib.factor_gp import split_train_test_dates, trim_panel_to_dates
    n = len(dates)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    train_dates = dates[:train_end]
    val_dates = dates[train_end:val_end]
    test_dates = dates[val_end:]

    # 训练用 train + val (RL 训练段), 测试段用于 OOS 复核
    train_panel = {c: panel[c].reindex(train_dates + val_dates) for c in codes}
    test_panel = {c: panel[c].reindex(test_dates) for c in codes}
    train_dates_all = train_dates + val_dates

    # ============ 4. 构建特征张量 + 未来收益 ============
    fe = FeatureEngine()
    feat_tensor = fe.compute(train_panel, codes, train_dates_all)  # [N, F, T]
    future_ret = _build_future_returns(train_panel, codes, train_dates_all, rebal_period)  # [N, T]

    # 构建验证段未来收益 (Walk-Forward OOS 门控): 只在验证段日期非 NaN
    val_future_ret = None
    if val_dates:
        val_future_ret = torch.full_like(future_ret, float("nan"))
        val_idx = [i for i, d in enumerate(train_dates_all) if d in set(val_dates)]
        if val_idx:
            # 验证段子面板
            val_panel = {c: train_panel[c].reindex(val_dates) for c in codes}
            val_sub = _build_future_returns(val_panel, codes, val_dates, rebal_period)  # [N, len(val)]
            for j, i in enumerate(val_idx):
                if j < val_sub.shape[1]:
                    val_future_ret[:, i] = val_sub[:, j]

    # ============ 5. 训练 RL 引擎 (单岛或多岛) ============
    engine = None
    result = None
    # 数据域指纹: 与超参一起写入断点并用于续训校验。换了股票池/代码/
    # 日期/调仓周期/训练验证比例都视为新数据集, 旧断点失效 -> 从头训练。
    resume_scope = {
        "pool_type": pool_type,
        "pool_ref": pool_ref,
        "codes": tuple(sorted(codes)),
        "start_date": start_date,
        "end_date": end_date,
        "rebal_period": rebal_period,
        "train_ratio": train_ratio,
        "val_ratio": val_ratio,
        "n_stocks": len(codes),
        "n_dates": len(dates),
    }
    if n_islands > 1:
        from .island import IslandAlphaEngine
        isl_engine = IslandAlphaEngine(
            rl_cfg, n_islands=n_islands, migration_interval=migration_interval)
        result = isl_engine.train(
            feat_tensor, future_ret, rebal_period=rebal_period,
            progress_cb=progress_cb, restart_cb=restart_cb, elite_cb=elite_cb,
            checkpoint_dir=checkpoint_dir, resume=resume, val_future_ret=val_future_ret,
            resume_scope=resume_scope,
        )
        engine = isl_engine
    else:
        engine = AlphaEngine(rl_cfg)
        result = engine.train(
            feat_tensor, future_ret, rebal_period=rebal_period,
            progress_cb=progress_cb, restart_cb=restart_cb, elite_cb=elite_cb,
            checkpoint_dir=checkpoint_dir, resume=resume, val_future_ret=val_future_ret,
            resume_scope=resume_scope,
        )

    # ============ 6. 收集候选公式 ============
    # 单岛: 从 engine._elite_pool + best 收集; 多岛: 从 island 汇总
    if n_islands > 1:
        candidates_raw = engine.collect_candidates(max_count=return_candidates * 5)
    else:
        candidates_raw = []
        if engine.best_formula:
            candidates_raw.append(engine.best_formula)
        for score, counter, fml, birth in sorted(engine._elite_pool, key=lambda x: x[0], reverse=True):
            candidates_raw.append(fml)

    # 去重 + 解码为表达式
    seen = set()
    exprs = []
    for fml in candidates_raw:
        key = tuple(fml)
        if key in seen:
            continue
        seen.add(key)
        expr = _decode_formula(fml)
        if expr:
            exprs.append(expr)

    # ============ 7. 收尾筛选管线 (复用本系统 oos/WF/permutation/dedup) ============
    # prices_panel: {code: 日K DataFrame} 供 oos_recheck/dedup_by_corr 使用
    prices_panel = {c: panel[c] for c in codes}
    test_start = str(dates[int(n * (train_ratio + val_ratio))]) if val_ratio > 0 else str(dates[int(n * train_ratio)])

    oos_list = []
    wf_list = []
    perm_list = []
    dedup_report = None
    candidates = []

    if exprs:
        # 7.1 测试段 OOS 复核
        try:
            from lib.factor_gp import oos_recheck
            from lib.factor_evaluator import get_pool_stocks
            oos_list = oos_recheck(
                exprs[:return_candidates * 3], panel, prices_panel,
                test_start, str(dates[-1]),
                rebal_period=rebal_period, min_warmup=60,
                use_gpu=use_gpu, fitness_mode="rank_ic")
        except Exception:
            oos_list = []

        # 7.2 Walk-Forward 重验证
        if n_folds >= 2:
            try:
                from lib.factor_gp import walk_forward_recheck
                wf_list = walk_forward_recheck(
                    exprs[:return_candidates * 3], panel, prices_panel,
                    str(dates[0]), str(dates[-1]),
                    n_folds=n_folds, fold_train_ratio=train_ratio,
                    rebal_period=rebal_period, min_warmup=60,
                    use_gpu=use_gpu, fitness_mode="rank_ic")
            except Exception:
                wf_list = []

        # 7.3 置换显著性检验
        if perm_n > 0:
            try:
                from lib.factor_gp import permutation_significance
                perm_list = permutation_significance(
                    exprs[:return_candidates * 3], panel, prices_panel,
                    str(dates[0]), str(dates[-1]), n_perm=perm_n,
                    rebal_period=rebal_period, use_gpu=use_gpu,
                    fitness_mode="rank_ic")
            except Exception:
                perm_list = []

        # 7.4 组装候选 (先算训练段 RankIC 排序)
        try:
            from lib.factor_rl.backtest import mean_rank_ic
            from lib.factor_engine import evaluate_expression
            temp_candidates = []
            for expr in exprs[:return_candidates * 5]:
                try:
                    fv = evaluate_expression(expr, train_panel)
                    fv_t = torch.tensor(fv.reindex(train_dates_all).values.T, dtype=torch.float32)
                    ic_res = mean_rank_ic(fv_t, future_ret, rebal_period)
                    # 汇总 OOS/WF/permutation 结果
                    oos_info = next((o for o in oos_list if o.get("expr") == expr), {})
                    wf_info = next((w for w in wf_list if w.get("expr") == expr), {})
                    perm_info = next((p for p in perm_list if p.get("expr") == expr), {})
                    temp_candidates.append({
                        "expr": expr,
                        "rank_ic": ic_res["rank_ic_mean"],
                        "rank_ic_ir": ic_res["rank_ic_ir"],
                        "direction": 1 if ic_res["rank_ic_mean"] >= 0 else -1,
                        "test_rank_ic": oos_info.get("test_rank_ic"),
                        "oos_ok": bool(oos_info.get("oos_ok", False)),
                        "wf_ok": bool(wf_info.get("wf_ok", False)),
                        "wf_mean_ic": wf_info.get("mean_ic"),
                        "p_value": perm_info.get("p_value"),
                        "significant": bool(perm_info.get("significant", False)),
                    })
                except Exception:
                    continue
            candidates = temp_candidates
        except Exception:
            candidates = []

        # 7.5 去冗余 (dedup_by_corr)
        if candidates:
            try:
                from lib.factor_gp import dedup_by_corr
                # 为 dedup 准备基本指标 (每候选需 ic_metric 字段)
                for c in candidates:
                    c["rank_ic_mean"] = c["rank_ic"]
                kept, dedup_report = dedup_by_corr(
                    candidates, panel, prices_panel,
                    rebal_period=rebal_period, min_warmup=60,
                    corr_thresh=corr_thresh, ic_metric="rank_ic_mean")
                candidates = kept
            except Exception:
                dedup_report = None

    # 按 RankIC 排序, 取 Top-N
    candidates.sort(key=lambda x: abs(x["rank_ic"] or 0), reverse=True)
    candidates = candidates[:return_candidates]

    return {
        "candidates": candidates,
        "training_history": result["training_history"],
        "best": {
            "score": result["best_score"],
            "formula": _decode_formula(result["best_formula"]) if result.get("best_formula") else "",
        },
        "best_score": result["best_score"],
        "elite_pool_size": result["elite_pool_size"],
        "restart_count": result["restart_count"],
        "n_islands": n_islands,
        "n_stocks": len(codes),
        "n_dates": len(dates),
        "vocab_size": FORMULA_VOCAB.size,
        "feature_count": FORMULA_VOCAB.feature_count,
        "operator_count": len(FORMULA_VOCAB.operator_names),
        "migration_events": result.get("migration_events", []),
        "dedup_report": dedup_report,
    }
