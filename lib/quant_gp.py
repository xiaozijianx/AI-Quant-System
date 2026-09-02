# -*- coding: utf-8 -*-
# QuantGP: 完全复刻 QuantGplearn 原版 GP 因子挖掘 (独立基线, 零扩充)
"""
定位:
  - 完全复刻 QuantGplearn 原版行为 (搜索空间/建树/遗传/执行/适应度/收尾),
    不做任何简化/优化/扩充; 仅在"数据输入"与"结果输出"两个边界做本系统适配。
  - 算法内核使用本地化复制包 lib/quantgplearn_local (字节级一致复制原版, 见 docs/QuantGP页面增强功能梳理.md 3.6),
    原版 third_party/QuantGplearn 保留作对照基线。
  - 数据输入: 本系统 {股票:DataFrame} 行情面板 -> 原版 long-panel 格式 (MultiIndex [datetime, symbol] + 特征列 + target)。
  - 结果输出: 原版产出因子 -> 翻译为本系统 formula -> 校验 -> 入库 factor_library
    (base_id 由 analyze_expression_tags 递归解析, QuantGplearn 产出均为复合因子)。

复刻范围 (本文件仅做适配, 本地化包当前零改动):
  - 完全使用 GpuSymbolicTransformer 原版, 参数原样透传;
  - A 档增强 (分段/OOS/Permutation/target 正交化+多轮) 全部在 mine_quantgp 外层适配,
    基于原版 ProgramEvaluator/TensorFitness 机制, 不改本地化包, 默认关闭不扰乱原版;
  - Walk-forward / 验证段 / 中性化 / 时序标准化 / 增量去冗余(ortho_dedup) 已移除
    (机制与训练/测试区分或参考 case 不符, 理由见设计文档 2.3/2.5/2.6)。
"""
from __future__ import annotations

import re
import hashlib
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# QuantGplearn 本地化复制包 (lib/quantgplearn_local):
# 仅含本项目实际用到的 8 个文件, 不再引用第三方 third_party/QuantGplearn (见 docs/QuantGP页面增强功能梳理.md 3.6)


def _load_quantgplearn():
    """延迟导入原版 GpuSymbolicTransformer (避免页面无关路径也触发导入)"""
    from lib.quantgplearn_local.gpu_transformer import GpuSymbolicTransformer
    from lib.quantgplearn_local.tensor_data import TensorPanelData
    return GpuSymbolicTransformer, TensorPanelData


# 本系统行情字段 -> 原版特征列 (小写列名, 与 load_daily_kline 输出一致)
# QuantGplearn 特征用 X1..Xn 索引, feature_names 只需与本系统列名一致即可
DEFAULT_FEATURES: List[str] = [
    "open", "high", "low", "close", "volume", "amount", "turnover_rate",
]

# 小写行情列名 -> 本系统 evaluate_expression 引擎字段名 (引擎 _SAFE_FIELDS 为大写)
_FIELD_TO_ENGINE: Dict[str, str] = {
    "open": "Open", "high": "High", "low": "Low", "close": "Close",
    "volume": "Volume", "amount": "Amount", "vwap": "VWAP",
    "turnover_rate": "Turnover",
}


# ============================================================
# 一、数据接入层: 本系统面板 -> 原版 long-panel + target
# ============================================================

def panel_to_long_panel(panel: Dict[str, pd.DataFrame],
                        feature_names: Optional[Sequence[str]] = None,
                        rebal_period: int = 5) -> Tuple[pd.DataFrame, List[str]]:
    """把本系统 {股票:DataFrame} 行情面板转换为原版 long-panel DataFrame

    panel: {code: DataFrame(index=日期, columns=open/high/low/close/volume/...)}
    返回 (long_df, feature_names)
      long_df: MultiIndex [datetime, symbol] + 特征列 + target 列
               (target = close 前移 rebal_period 期收益率, 供原版算 IC/ICIR)
    """
    features = list(feature_names) if feature_names else list(DEFAULT_FEATURES)
    frames = []
    for code, df in panel.items():
        if df is None or len(df) == 0:
            continue
        d = df.copy()
        # 保留可用特征列 (缺列置 NaN, 原版 mask 会处理)
        for f in features:
            if f not in d.columns:
                d[f] = np.nan
        d = d[features].copy()
        d.index.name = "datetime"  # 统一日期索引名, 保证 reset_index 后生成正确的 datetime 列 (原索引名可能是 trade_date 等)
        d["symbol"] = code
        frames.append(d)
    if not frames:
        raise ValueError("面板为空, 无法构造 long-panel")
    # concat 后统一 reset_index: datetime 由原索引生成 (frames 未重复加 datetime 列)
    long_df = pd.concat(frames, axis=0)
    long_df = long_df.reset_index(drop=False)
    if "datetime" not in long_df.columns:
        long_df["datetime"] = long_df.index
    long_df.rename(columns={long_df.index.name: "datetime"}, inplace=True)
    # target: close 前移 rebal_period 期收益率 (fwd_return = close[t+rebal]/close[t] - 1)
    close_wide = long_df.pivot_table(index="datetime", columns="symbol", values="close")
    fwd = close_wide.shift(-rebal_period) / close_wide - 1.0
    fwd_long = fwd.stack().rename("target").reset_index()
    # 合并 target 到 long_df
    long_df = long_df.merge(fwd_long, on=["datetime", "symbol"], how="left")
    # 设 MultiIndex [datetime, symbol] 并排序 (原版 from_panel_df 要求)
    long_df = long_df.set_index(["datetime", "symbol"]).sort_index()
    return long_df, features


def build_quantgp_input(panel: Dict[str, pd.DataFrame],
                        feature_names: Optional[Sequence[str]] = None,
                        rebal_period: int = 5):
    """构造原版 GpuSymbolicTransformer.fit_panel 所需的输入

    返回 (X, target_col):
      X: long-panel DataFrame (MultiIndex [datetime, symbol] + 特征列 + target 列)
      target_col: "target"
    """
    X, _ = panel_to_long_panel(panel, feature_names, rebal_period)
    return X, "target"


# ============================================================
# 二、原版求值封装 (GpuSymbolicTransformer 原样透传, 零改造)
# ============================================================

def mine_quantgp(panel: Dict[str, pd.DataFrame],
                 feature_names: Optional[Sequence[str]] = None,
                 rebal_period: int = 5,
                 progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
                 poll_interval: float = 0.5,
                 train_ratio: float = 1.0,
                 enable_oos: bool = False,
                 enable_perm: bool = False,
                 n_perm: int = 1000,
                 enable_target_ortho: bool = False,
                 n_rounds: int = 1,
                 enable_final_screen: bool = False,
                 final_ic_threshold: float = 0.03,
                 final_corr_threshold: float = 0.9,
                 final_min_factors_fallback: int = 8,
                 final_max_factors_in_pool: int = 15,
                 enable_fdr: bool = False,
                 fdr_n_trials: int = 96,
                 fdr_n_subsample: int = 20,
                 fdr_cv_folds: int = 3,
                 fdr_decay_horizons: Optional[Sequence[int]] = None,
                 **params) -> Dict[str, Any]:
    """运行原版 QuantGplearn GP 因子挖掘 (完整复刻, 零扩充)

    params: 透传给 GpuSymbolicTransformer 的任意参数
            (population_size/hall_of_fame/n_components/generations/tournament_size/
             init_depth/init_method/function_set/objective/const_range/
             parsimony_coefficient/p_crossover/p_subtree_mutation/p_hoist_mutation/
             p_point_mutation/p_point_replace/max_samples/max_length/tolerable_corr/
             device/random_state 等)

    progress_cb: 可选回调, fit_panel 每完成一代时调用一次
                 progress_cb({"gen": int, "best_fitness": float, "avg_fitness": float,
                              "best_length": int, "avg_length": int, "time": float})
                 实现方式: 并发线程只读原版 run_details_ (原版每代都会 append),
                 不改动 QuantGplearn 源码。

    A 档增强 (外部适配层, 全部基于原版机制, 默认关闭, 不扰乱原版):
      train_ratio:    训练段占比 (默认 1.0 = 原版全量 fit; <1 时启用训练/测试两段分段)
      enable_oos:     训练段 fit 后, 用测试段重算候选 IC/ICIR/RankIC 做样本外复核
      enable_perm:    permutation 显著性检验 (打乱测试段 target 行, 经验 p 值)
      n_perm:         permutation 打乱次数 (默认 1000, 对齐 QuantAlpha 原版)
      enable_target_ortho: 完全复刻 Auto-Alpha-Finding 的 target 正交化:
                          用已有 qgp_* 因子池对 target 逐截面回归取残差, 再让 GP 在
                          残差 target 上挖掘 → 挖出的因子与池正交 (保证增量 alpha)。
      n_rounds:       多轮迭代轮数 (Auto-Alpha MINING_ROUNDS, 默认 1): 每轮 fit 后
                      把本轮新因子加入池, 下一轮重新正交化 target 再 fit (顺序正交化)。
      enable_final_screen: 完全复刻 Auto-Alpha-Finding 的收尾筛选 (alpha_miner.py mine() 收尾段):
                      用已有池 + 新候选, 按 |IC| 降序贪婪挑选 (与已选因子全时段相关 < 阈值),
                      再按 |IC| 阈值过滤, 不足兜底取前 N, 超上限取前 M; 筛掉冗余候选。
      final_ic_threshold:         |IC| 阈值 (Auto-Alpha IC_THRESHOLD_IS, 默认 0.03)
      final_corr_threshold:       候选去冗余相关阈值 (Auto-Alpha max_corr, 默认 0.9)
      final_min_factors_fallback: 通过 |IC| 阈值候选不足时的兜底数量 (Auto-Alpha MIN_FACTORS_FALLBACK, 默认 8)
      final_max_factors_in_pool:  最终候选数量上限 (Auto-Alpha MAX_FACTORS_IN_POOL, 默认 15)
      enable_fdr:     假发现门闸 (完全复刻 saulius.io QuantAlpha 的 False Discovery Gauntlet):
                      Permutation(1000) + Deflated Sharpe + Subsample + Decay + CV Consistency
                      -> Verdict (ROBUST/MARGINAL/UNSTABLE)。在测试段(perm/subsample/decay)+
                      训练段(CV consistency)上只读评估已训练好的候选, 不改训练/不改第三方。
      fdr_n_trials:   Deflated Sharpe 试验次数 (QuantAlpha 默认 96 个个体)
      fdr_n_subsample: Subsample 随机对半次数 (QuantAlpha 默认 20)
      fdr_cv_folds:   CV consistency 训练段 expanding folds 数 (QuantAlpha 默认 3)
      fdr_decay_horizons: Decay 分析 horizon 列表 (QuantAlpha 默认 [1,2,5,10,20])
      注: 市值中性化 / 时序标准化 / 增量去冗余(ortho_dedup) 已移除
          (前者专业评价交给因子评价页; 后者机制与 Auto-Alpha 不符, 见设计文档 2.5/2.6)。

    返回 {best_programs, best_scores, candidates(翻译后), run_details,
          segments(数据分段), oos_report, perm_report, ortho_info, final_screen_report,
          fdr_report}
    """
    GpuSymbolicTransformer, _ = _load_quantgplearn()

    # ---- A 档: 数据分段 (train_ratio<1 才切, 默认 1.0 = 原版全量行为) ----
    # 只切训练/测试两段 (验证段已移除, 无任何用途); 测试段专供 OOS/Permutation 复核
    segments: Optional[Dict[str, str]] = None
    fit_panel = panel
    if train_ratio is not None and float(train_ratio) < 1.0:
        try:
            ts, te, ss, se = _segment_dates(panel, float(train_ratio))
            if ss > ts:  # 测试段非空才启用分段
                fit_panel = trim_panel_dates(panel, ts, te)
                segments = {"train_start": ts, "train_end": te,
                            "test_start": ss, "test_end": se}
        except Exception:
            segments = None  # 分段失败回退全量 (原版行为)

    # 构造参数 (去掉 None, 原版默认值保留)
    kwargs = {k: v for k, v in params.items() if v is not None}
    # feature_names 显式指定 (未传时 fit_panel 会用排除 target 后的全部列)
    if feature_names is not None:
        kwargs.setdefault("feature_names", list(feature_names))

    # ---- A 档: target 正交化池 (仅 qgp_* 因子, Auto-Alpha smart_factor_pool 语义) ----
    pool_formulas: List[str] = []
    if enable_target_ortho:
        try:
            pool_formulas = _load_qgp_pool_formulas()
        except Exception:
            pool_formulas = []

    # ---- 多轮迭代挖掘 (Auto-Alpha MINING_ROUNDS: 每轮新因子加入池, 顺序正交化) ----
    n_rounds = max(1, int(n_rounds or 1))
    n_gens = int(params.get("generations") or 10)
    all_best_programs: List[Any] = []
    all_best_scores: List[Any] = []
    all_candidates: List[Dict[str, Any]] = []
    merged_run: Dict[str, List[Any]] = {"generation": [], "best_fitness": [],
                                        "average_fitness": [], "best_length": [],
                                        "average_length": [], "generation_time": []}
    oos_report: List[Dict[str, Any]] = []
    perm_report: List[Dict[str, Any]] = []
    seen_exprs: set = set()
    ortho_info: Dict[str, Any] = {"enabled": bool(enable_target_ortho),
                                  "n_rounds": n_rounds,
                                  "pool_before": len(pool_formulas),
                                  "pool_after": 0, "rounds": []}

    for r in range(n_rounds):
        # 每轮重建输入; 启用正交化时用当前池对 target 整体回归取残差 (Auto-Alpha 机制)
        X, target_col = build_quantgp_input(fit_panel, feature_names, rebal_period)
        round_pool = list(pool_formulas)
        if enable_target_ortho and round_pool:
            try:
                X = orthogonalize_target(X, fit_panel, round_pool)
            except Exception:
                pass  # 正交化失败则本轮用原始 target (不阻塞挖掘)
        model = GpuSymbolicTransformer(**kwargs)

        # 并发监控线程: 只读本轮 model.run_details_ (每代 append), gen 全局续接 r*n_gens+i
        stop_flag = threading.Event()
        sent_gens: List[int] = []

        def _push_progress(i: int, rd: Dict[str, Any]) -> None:
            """推送第 i 代进度 (全局 gen = r*n_gens + i, 多轮曲线连续)"""
            try:
                progress_cb({
                    "gen": int(r * n_gens + rd["generation"][i]),
                    "best_fitness": float(rd["best_fitness"][i]),
                    "avg_fitness": float(rd["average_fitness"][i]),
                    "best_length": int(rd["best_length"][i]),
                    "avg_length": float(rd["average_length"][i]),
                    "time": float(rd["generation_time"][i]),
                })
            except Exception:
                pass

        if progress_cb is not None:
            def _monitor() -> None:
                while not stop_flag.is_set():
                    rd = getattr(model, "run_details_", None)
                    if rd is not None:
                        gens = rd.get("generation", [])
                        for i in range(len(gens)):
                            if i in sent_gens:
                                continue
                            _push_progress(i, rd)
                            sent_gens.append(i)
                    time.sleep(poll_interval)
            threading.Thread(target=_monitor, daemon=True).start()

        try:
            # 用 fit_panel 训练 (原版); progress_cb 由监控线程在线程中轮询 run_details_
            model.fit_panel(X, target_col=target_col)
        finally:
            stop_flag.set()
        # 结束前最终补齐: 把监控线程因轮询间隔可能漏掉的最后几代也推送
        if progress_cb is not None:
            try:
                rd = getattr(model, "run_details_", None)
                if rd is not None:
                    for i in range(len(rd.get("generation", []))):
                        if i not in sent_gens:
                            _push_progress(i, rd)
            except Exception:
                pass

        # 合并本轮 run_details (gen 全局续接, 供进化曲线跨轮连续展示)
        rd = dict(getattr(model, "run_details_", {}) or {})
        gens = rd.get("generation", [])
        for i in range(len(gens)):
            merged_run["generation"].append(int(r * n_gens + gens[i]))
            for k in ("best_fitness", "average_fitness", "best_length",
                      "average_length", "generation_time"):
                vals = rd.get(k, [])
                merged_run[k].append(vals[i] if i < len(vals) else None)

        # 收集本轮候选 (qg_expr 去重)
        round_cands: List[Dict[str, Any]] = []
        for p, score in zip(list(model._best_programs), list(model._best_scores)):
            qg_expr = p.generate_my_output() if hasattr(p, "generate_my_output") else str(p)
            if qg_expr in seen_exprs:
                continue
            seen_exprs.add(qg_expr)
            round_cands.append({"qg_expr": qg_expr,
                                "score": float(score) if score is not None else None})
            all_best_programs.append(p)
            all_best_scores.append(score)
        all_candidates.extend(round_cands)

        # 顺序正交化: 本轮新因子 (翻译为本系统公式) 加入池, 供下一轮 target 正交化
        if enable_target_ortho:
            for cand in round_cands:
                try:
                    fml = quant_gp_expr_to_formula(cand["qg_expr"], feature_names)
                    if fml and fml not in pool_formulas:
                        pool_formulas.append(fml)
                except Exception:
                    pass

        # A 档复核: 每轮 model 在测试段复核各自候选 (报告带 round 标记)
        if segments is not None:
            try:
                test_panel = trim_panel_dates(panel, segments["test_start"], segments["test_end"])
                # 段内有效交易日数 (而非股票数), 决定 OOS/permutation 是否可算
                test_n_days = len(next(iter(test_panel.values())).index) if test_panel else 0
                if enable_oos and test_n_days >= 5:
                    rr = oos_recheck_quantgp(model, test_panel, feature_names, rebal_period)
                    for item in rr:
                        item["round"] = r + 1
                    oos_report.extend(rr)
                if enable_perm and test_n_days >= 40:
                    pr = permutation_significance_quantgp(
                        model, test_panel, rebal_period, n_perm=int(n_perm or 1000))
                    for item in pr:
                        item["round"] = r + 1
                    perm_report.extend(pr)
            except Exception:
                pass  # 任一 A 档复核失败不影响主流程

        ortho_info["rounds"].append({"round": r + 1, "pool_size": len(round_pool),
                                     "n_candidates": len(round_cands)})
    ortho_info["pool_after"] = len(pool_formulas)

    # ---- A 档: 收尾筛选 (完全复刻 Auto-Alpha-Finding, 可选, 在训练段上筛选候选) ----
    final_screen_report: Optional[Dict[str, Any]] = None
    if enable_final_screen:
        try:
            # Auto-Alpha 收尾筛选始终加载既有池 (独立于正交化开关): 与既有池因子做相关去冗余
            screen_pool = list(pool_formulas)
            if not screen_pool:
                screen_pool = _load_qgp_pool_formulas()
            all_candidates, final_screen_report = final_screen_quantgp(
                all_candidates, fit_panel, feature_names, rebal_period,
                pool_formulas=screen_pool,
                ic_threshold=float(final_ic_threshold if final_ic_threshold is not None else 0.03),
                corr_threshold=float(final_corr_threshold if final_corr_threshold is not None else 0.9),
                min_factors_fallback=int(final_min_factors_fallback if final_min_factors_fallback else 8),
                max_factors_in_pool=int(final_max_factors_in_pool if final_max_factors_in_pool else 15),
            )
            # 同步过滤 best_programs/best_scores 与候选对齐 (仅保留收尾筛选幸存者)
            kept_exprs = {c["qg_expr"] for c in all_candidates}
            kept_pairs = [(p, s) for p, s in zip(all_best_programs, all_best_scores)
                          if (_program_expr(p) in kept_exprs)]
            if kept_pairs:
                all_best_programs = [p for p, _ in kept_pairs]
                all_best_scores = [s for _, s in kept_pairs]
        except Exception:
            final_screen_report = None  # 筛选失败不影响主流程

    # ---- A 档: 假发现门闸 (完全复刻 saulius.io QuantAlpha, 可选, 只读评估) ----
    fdr_report: Optional[List[Dict[str, Any]]] = None
    if enable_fdr and segments is not None:
        try:
            test_panel = trim_panel_dates(panel, segments["test_start"], segments["test_end"])
            fdr_report = fdr_gauntlet_quantgp(
                model, test_panel, fit_panel, feature_names, rebal_period,
                n_perm=int(n_perm or 1000),
                n_trials=int(fdr_n_trials or 96),
                n_subsample=int(fdr_n_subsample or 20),
                decay_horizons=list(fdr_decay_horizons) if fdr_decay_horizons else None,
                cv_folds=int(fdr_cv_folds or 3),
                random_state=params.get("random_state"),
            )
        except Exception:
            fdr_report = None  # 门闸失败不影响主流程

    return {
        "best_programs": all_best_programs,
        "best_scores": all_best_scores,
        "run_details": merged_run,
        "candidates": all_candidates,
        "segments": segments,
        "oos_report": oos_report,
        "perm_report": perm_report,
        "ortho_info": ortho_info,
        "final_screen_report": final_screen_report,
        "fdr_report": fdr_report,
    }


# ============================================================
# 三、表达式翻译器: QuantGplearn 公式 -> 本系统公式
# ============================================================

# 算子名映射: 原版小写名 -> 本系统 evaluate_expression 命名
# 本系统 _SAFE_FUNCTIONS 用 ts_Mean/ts_Stdev/ts_Rank/cs_Rank 等 (驼峰),
# 原版用 ts_mean/ts_std/ts_rank/cs_rank 等 (小写)。
# 注意: 本系统算术算子为符号形式 (add→+, sub→-, mul→*, div→/), 无 add/div 函数;
#       一元 neg/inv 本系统无对应符号, 翻译时映射到等价式或跳过。
_OP_NAME_MAP: Dict[str, str] = {
    # 时序
    "ts_shift": "ts_Delay", "ts_delta": "ts_Delta", "ts_mom": "ts_ROC",
    "ts_min": "ts_Min", "ts_max": "ts_Max", "ts_argmax": "ts_ArgMax",
    "ts_argmin": "ts_ArgMin", "ts_rank": "ts_Rank", "ts_sum": "ts_Sum",
    "ts_std": "ts_Stdev", "ts_corr": "ts_Corr", "ts_mean": "ts_Mean",
    "ts_zscore": "ts_ZScore", "ts_freq": "ts_Freq", "ts_skew": "ts_Skewness",
    "ts_kurt": "ts_Kurtosis", "ts_ema": "ts_EMA", "ts_rsi": "ts_RSI",
    "ts_atr": "ts_ATR", "ts_adx": "ts_ADX", "ts_cmo": "ts_CMO",
    "ts_bband": "ts_BOLL", "ts_aroon": "ts_AROON", "ts_stochf": "ts_STOCHF",
    "ts_macd": "ts_MACD_DIF", "ts_hedge": "ts_Hedge", "ts_bopr": "ts_BOPR",
    "ts_xs_ratio": "ts_XSRatio", "ts_cdlbodym": "ts_CDLBodyM",
    "ts_bar_bs": "ts_BarBS", "ts_one_ols_k": "ts_OneOlsK",
    "ts_one_ols_resid": "ts_OneOlsResid",
    # 截面
    "cs_rank": "cs_Rank", "cs_zscore": "cs_Zscore",
    "cs_demean": "cs_Demean", "cs_scale": "cs_Scale",
    "cs_winsorize": "cs_Winsorize",
}
# 算术函数 -> 符号 (本系统无 add/sub/mul/div 函数, 用中缀符号)
_ARITH_SYMBOL: Dict[str, str] = {
    "add": "+", "sub": "-", "mul": "*", "div": "/",
}
# 一元函数映射 (本系统函数形式; None 表示无对应, 翻译时保持原名交 validate 判断)
_UNARY_FUNCS: Dict[str, Optional[str]] = {
    "sqrt": "sqrt", "log": "log", "abs": "abs",
    "sig": "sigmoid",
    # neg/inv 本系统无对应函数, 用符号等价 (由 _translate_node 处理)
    "neg": None, "inv": None,
    # max/min 原版为二元逐元素算子, 由 _translate_node 映射为 np.maximum/np.minimum
    # sin/cos/tan 本系统无对应 -> 保持原名, validate 拒绝则跳过
    "sin": None, "cos": None, "tan": None,
}


def _translate_expr(qg_expr: str, feature_names: List[str]) -> Optional[str]:
    """把 QuantGplearn 的 generate_my_output 字符串翻译为本系统公式

    输入形如: add(ts_mean(X0, 5), ts_rsi(X1, 14))
    X{i} 为特征索引 (1-based: X1=feature_names[0])。
    - 算术算子 add/sub/mul/div 转为中缀符号 (a+b 等);
    - ts_*/cs_* 函数名映射到本系统驼峰命名;
    - neg(x) -> (-x), inv(x) -> (1/x);
    - 无法映射的算子保持原名, 由调用方 validate 判断后跳过。
    """
    expr = (qg_expr or "").strip()
    if not expr:
        return None
    # 特征索引 X{i} -> 字段名
    def _feat(m: "re.Match") -> str:
        try:
            idx = int(m.group(1)) - 1
        except (TypeError, ValueError):
            return m.group(0)
        if 0 <= idx < len(feature_names):
            return feature_names[idx]
        return m.group(0)
    expr = re.sub(r"X(\d+)", _feat, expr)
    return _translate_node(expr)


def _translate_node(s: str) -> Optional[str]:
    """递归翻译一个表达式节点 (叶子 或 函数调用)

    叶子字段名: 小写行情列名 -> 大写引擎字段名 (open->Open 等)。
    """
    s = s.strip()
    if not s:
        return s
    # 叶子: 字段名 / 数字 (无函数调用)
    if not re.search(r"[a-zA-Z_][a-zA-Z0-9_]*\s*\(", s):
        # 单个 token: 字段名/数字
        t = s.strip()
        if t in _FIELD_TO_ENGINE:
            return _FIELD_TO_ENGINE[t]
        return t
    # 函数调用 name(args): 用括号配对提取最外层调用
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$", s, re.DOTALL)
    if not m:
        return s  # 无法解析, 原样返回 (validate 判断)
    name = m.group(1)
    args_raw = m.group(2)
    args = []
    for a in _split_args(args_raw):
        t = _translate_node(a)
        if t is None:
            return None
        args.append(t)
    # 算术二元 -> 中缀
    if name in _ARITH_SYMBOL and len(args) == 2:
        return f"({args[0]}{_ARITH_SYMBOL[name]}{args[1]})"
    # 元素级最大/最小 (原版 t_max/t_min 为二元逐元素算子; 本系统内置 max/min 不支持
    # 两个 DataFrame 逐元素比较, 翻译为 np.maximum/np.minimum, 其已在本系统 _SAFE_NAMES 可用)
    if name in ("max", "min") and len(args) == 2:
        fn = "np.maximum" if name == "max" else "np.minimum"
        return f"{fn}({args[0]}, {args[1]})"
    # neg/inv -> 符号等价
    if name == "neg" and len(args) == 1:
        return f"(-{args[0]})"
    if name == "inv" and len(args) == 1:
        return f"(1/{args[0]})"
    # 其他函数: 映射名字 (无对应则保持原名, validate 决定去留)
    new_name = _OP_NAME_MAP.get(name, _UNARY_FUNCS.get(name, name))
    return f"{new_name}({', '.join(args)})"


def _split_args(s: str) -> List[str]:
    """按逗号切分函数参数 (顶层逗号, 不进入嵌套括号)"""
    parts = []
    depth = 0
    cur = []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur or not parts:
        parts.append("".join(cur).strip())
    return parts


def quant_gp_expr_to_formula(qg_expr: str, feature_names: List[str]) -> Optional[str]:
    """对外接口: 翻译 + 语法校验 (validate_expression)

    校验失败返回 None。
    """
    formula = _translate_expr(qg_expr, feature_names)
    if not formula:
        return None
    try:
        from lib.factor_engine import validate_expression
        ok, _ = validate_expression(formula)
        if not ok:
            return None
    except Exception:
        return None
    return formula


# ============================================================
# 四、base_id 解析 + 入库 factor_library
# ============================================================

def _calc_non_null_ratio(formula: str, panel: Dict[str, pd.DataFrame]) -> Optional[float]:
    """试算公式非空率 (≥0.2 视为可计算/有效)"""
    try:
        from lib.factor_engine import evaluate_expression
        fv = evaluate_expression(formula, panel)
        if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
            return None
        return float(fv.notna().mean().mean())
    except Exception:
        return None


def import_quantgp_candidates(candidates: List[Dict[str, Any]],
                              panel: Dict[str, pd.DataFrame],
                              feature_names: List[str],
                              name_prefix: str = "qgp") -> Dict[str, Any]:
    """把翻译后的候选因子入库 factor_library

    candidates: [{qg_expr, score, formula(可选)}]
    每个候选:
      1. 翻译为本系统 formula;
      2. validate_expression + evaluate_expression 非空率 ≥ 0.2 校验;
      3. analyze_expression_tags 解析 base_id/factor_type;
      4. upsert_factor 入库 (factor_type=composite, evaluation_type 推断)。

    返回 {imported: [...], skipped: [{expr, reason}]}
    """
    from lib.factor_db import upsert_factor
    from lib.factor_engine import analyze_expression_tags

    imported = []
    skipped = []
    seen_formulas = set()

    for cand in candidates:
        qg_expr = cand.get("qg_expr") or ""
        formula = cand.get("formula") or quant_gp_expr_to_formula(qg_expr, feature_names)
        if not formula:
            skipped.append({"expr": qg_expr, "reason": "翻译失败或校验不过"})
            continue
        # 非空率校验
        nn = _calc_non_null_ratio(formula, panel)
        if nn is None or nn < 0.2:
            skipped.append({"expr": qg_expr, "reason": f"非空率过低 ({nn})"})
            continue
        # 去重 (按公式规范化哈希)
        fhash = hashlib.md5(formula.encode("utf-8")).hexdigest()[:12]
        if fhash in seen_formulas:
            skipped.append({"expr": qg_expr, "reason": "与已入库公式重复"})
            continue
        seen_formulas.add(fhash)
        # 解析标签
        tags = analyze_expression_tags(formula)
        factor_id = f"{name_prefix}_{fhash}"
        factor = {
            "factor_id": factor_id,
            "name": formula[:60],
            "category": "技术",
            "sub_category": None,
            "direction": tags.get("direction") or "positive",
            "formula": formula,
            "description": f"QuantGP 原版挖掘候选 (score={cand.get('score')})",
            "data_source": "quantgp",
            "period": "",
            "origin": "quantgp",
            "is_custom": True,
            "base_id": tags.get("base_id"),
            "factor_type": "composite",
            "evaluation_type": tags.get("factor_type") or "technical",
        }
        try:
            upsert_factor(factor)
            imported.append({**factor, "score": cand.get("score")})
        except Exception as e:
            skipped.append({"expr": qg_expr, "reason": f"入库失败: {e}"})

    return {"imported": imported, "skipped": skipped}


# ============================================================
# 五、A 档增强: 数据分段 / OOS / Permutation / 中性化 / 正交化去冗余
#     (全部在 mine_quantgp 外层适配, 基于原版 ProgramEvaluator + TensorFitness 机制,
#      不改动 QuantGplearn 源码; 默认关闭, 不扰乱原版行为)
# ============================================================

def trim_panel_dates(panel: Dict[str, pd.DataFrame],
                     start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """把 {code: DataFrame} 面板裁剪到 [start_date, end_date] 区间 (A 档分段/复核用)"""
    from lib.factor_gp import trim_panel_to_dates
    return trim_panel_to_dates(panel, start_date, end_date)


def _segment_dates(panel: Dict[str, pd.DataFrame],
                   train_ratio: float) -> Tuple[str, str, str, str]:
    """按比例切分训练/测试两段, 返回 4 个日期
    (train_start, train_end, test_start, test_end)

    验证段已移除 (无任何用途); 测试段专供 OOS/Permutation 复核。
    区间取自面板第一只股票的完整日期序列 (与自研 GP 分段口径一致)。
    """
    from lib.factor_gp import split_train_test_dates
    first = next(iter(panel))
    idx = panel[first].index
    start_date, end_date = idx.min(), idx.max()
    ts, te, _vs, _ve, ss, se = split_train_test_dates(
        panel, str(start_date), str(end_date), float(train_ratio), 0.0)
    return ts, te, ss, se


def _make_tensor_data(model, panel: Dict[str, pd.DataFrame],
                      feature_names: Optional[Sequence[str]],
                      rebal_period: int):
    """构造原版 TensorPanelData (含 target), 供 OOS/WF/permutation/去冗余复用

    面板先裁剪并转 long-panel (含 fwd_return target 列), 再走原版
    from_panel_df 转稠密张量 [T,N,F]。返回 None 表示段内数据不足。
    """
    _, TensorPanelData = _load_quantgplearn()
    X, _ = panel_to_long_panel(panel, feature_names, rebal_period)
    if len(X) == 0:
        return None
    feats = list(getattr(model, "feature_names_", None) or feature_names or [])
    data = TensorPanelData.from_panel_df(
        X, feature_names=feats, target_col="target",
        time_index=getattr(model, "time_series_index", "datetime"),
        security_index=getattr(model, "security_index", "symbol"),
        device=str(getattr(model, "device", "cpu")),
        dtype=getattr(model, "dtype", None),
    )
    return data


def _load_qgp_pool_formulas() -> List[str]:
    """从因子库读取 QuantGplearn 历史产出 (qgp_* 前缀) 因子公式, 作为 target 正交化池

    对应 Auto-Alpha-Finding 的 smart_factor_pool.json (历史已保留因子池)。
    """
    try:
        from lib.factor_db import list_factors
        qgp = list_factors(search="qgp_") or []
        return [f.get("formula") for f in qgp if f.get("formula")]
    except Exception:
        return []


def orthogonalize_target(X: pd.DataFrame,
                         panel: Dict[str, pd.DataFrame],
                         pool_formulas: List[str],
                         min_samples: int = 5) -> pd.DataFrame:
    """严格复刻 Auto-Alpha-Finding (sw0843) 的 target 残差正交化

    Auto-Alpha 原始实现 (alpha_miner.py, mine()):
      is_df['target'] = is_df.groupby('time_key')['ret_1d_fwd'].transform(lambda x: x - x.mean())
      y = is_df['target'].values
      X_exist = np.hstack([evaluate_formula(is_df, f).values.reshape(-1,1) for f in existing_factors])
      reg = LinearRegression().fit(X_exist, y)
      y = y - reg.predict(X_exist)   # 目标收益对已有因子池整体回归取残差
    即: ① target 先逐日截面去均值; ② 池因子长表拼成 X_exist; ③ 整体 OLS 拟合 y ~ X_exist
    取残差; 之后 GP 在残差 target 上挖掘 → 挖出的因子与池正交 (增量 alpha)。

    本函数在 build_quantgp_input 之后、fit_panel 之前调用 (数据准备层, 零改动第三方)。

    X: long-panel (MultiIndex [datetime, symbol]) 含 target 列 (build_quantgp_input 产出)
    panel: {code: DataFrame} 原始面板 (evaluate_expression 求池因子用)
    返回: 新 long-panel (仅 target 列被替换为残差; 池为空/求值失败时返回原 X)
    """
    from lib.factor_engine import evaluate_expression
    # 1. 池因子在本次面板上求值 (宽表 (date, symbol)), 转长列并对齐 X 的 MultiIndex
    #    (Auto-Alpha 的 evaluate_formula 对 NaN/Inf 填 0, 这里同样将池因子 NaN 填 0)
    pool_cols: List[pd.Series] = []
    for f in pool_formulas:
        try:
            fv = evaluate_expression(f, panel)
            if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
                continue
            s = fv.stack().astype(float).fillna(0.0)  # 池因子 NaN -> 0 (对齐 Auto-Alpha)
            s.index = s.index.set_names(["datetime", "symbol"])
            s = s.reindex(X.index)
            if s.notna().sum() > 0:
                pool_cols.append(s)
        except Exception:
            continue
    if not pool_cols:
        return X
    # 2. target 逐日截面去均值 (Auto-Alpha: groupby(time_key) transform mean)
    y = X["target"].astype(float)
    y = y - y.groupby(level=0).transform("mean")
    # 3. 整体 OLS 拟合 y ~ 池因子长列, 取残差 (Auto-Alpha: LinearRegression().fit/predict)
    yv = y.to_numpy(dtype=float)
    Xm = np.column_stack([c.to_numpy(dtype=float) for c in pool_cols])
    valid = np.isfinite(yv) & np.all(np.isfinite(Xm), axis=1)
    if int(valid.sum()) < min_samples:
        return X
    from sklearn.linear_model import LinearRegression
    reg = LinearRegression().fit(Xm[valid], yv[valid])
    resid = np.full(len(yv), np.nan)
    resid[valid] = yv[valid] - reg.predict(Xm[valid])
    # 4. 用残差替换 target 列
    out = X.copy()
    out["target"] = resid
    return out


def final_screen_quantgp(candidates: List[Dict[str, Any]],
                         panel: Dict[str, pd.DataFrame],
                         feature_names: Optional[Sequence[str]],
                         rebal_period: int = 5,
                         pool_formulas: Optional[List[str]] = None,
                         ic_threshold: float = 0.03,
                         corr_threshold: float = 0.9,
                         min_factors_fallback: int = 8,
                         max_factors_in_pool: int = 15,
                         ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """完全复刻 Auto-Alpha-Finding (alpha_miner.py mine() 收尾段) 的收尾筛选

    原始逻辑 (alpha_miner.py mine() 收尾):
      all_candidates = existing_pool + new_formulas   (公式字符串集合)
      scored = [(f, ic, vals)]                        # ic = 池化 Spearman 秩相关 vs ret_1d_fwd
      scored_sorted = sorted(by |ic| 降序)
      selected = []                                   # 按 |ic| 降序贪婪挑选
      for f, ic, vals in scored_sorted:
          max_corr = max(selected 中 |pearson(vals, sv)|)   # 与已选因子值全时段相关
          if max_corr < corr_threshold: selected.append((f, ic))   # 默认 0.9
      survivors = [(f, ic) for f, ic in selected if |ic| >= ic_threshold]   # 默认 0.03
      if len(survivors) < min_factors_fallback:        # 不足兜底取前 N (默认 8)
          survivors = 按 |ic| 取前 min_factors_fallback
      else:                                            # 否则取前 M (默认 15)
          survivors = 按 |ic| 取前 max_factors_in_pool
      save_pool(survivors)                             # 幸存者写回因子池

    本函数在训练段 (panel) 上对候选 (含既有池) 做同样的收尾筛选:
      - 候选公式翻译为本系统公式, 在面板上求值 (宽表) -> 长列, 对齐 target (前向收益);
      - ic 用池化 Spearman 秩相关 (对齐 Auto-Alpha calculate_ic, 非逐日截面均值);
      - 相关去冗余用池化 Pearson 相关系数 (对齐原版 np.corrcoef);
      - 返回幸存候选 (candidates 中未被筛掉的子集) + 筛选报告。

    返回 (kept_candidates, screen_report):
      kept_candidates: 收尾筛选幸存的新候选 (原候选 dict 列表)
      screen_report: {enabled, n_total, n_kept, ic_threshold, corr_threshold,
                      min_factors_fallback, max_factors_in_pool,
                      scored: [{formula, ic, max_corr, kept, reason}]}
    """
    from scipy.stats import spearmanr
    from lib.factor_engine import evaluate_expression

    # 1. 构造训练段 long-panel (含 target 前向收益), 供 IC 计算与因子值对齐
    X, _ = build_quantgp_input(panel, feature_names, rebal_period)
    if len(X) == 0:
        return candidates, {"enabled": True, "n_total": len(candidates),
                            "n_kept": len(candidates), "scored": []}

    # 2. 求值工具: 公式 -> 长列 (MultiIndex [datetime, symbol], NaN/Inf -> 0 对齐原版 evaluate_formula)
    def _eval_long(formula: str):
        try:
            fv = evaluate_expression(formula, panel)
            if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
                return None
            s = fv.stack().astype(float)
            s.index = s.index.set_names(["datetime", "symbol"])
            s = s.reindex(X.index)
            return s.fillna(0.0).clip(lower=-1e6, upper=1e6)
        except Exception:
            return None

    target = X["target"].astype(float)

    # 3. 收集打分项: 既有池 (参与去冗余) + 新候选 (candidates 携带 qg_expr)
    scored: List[Dict[str, Any]] = []  # {formula, ic, vals, cand_idx}
    pool_set = set(pool_formulas or [])
    for f in pool_set:
        vals = _eval_long(f)
        if vals is None:
            continue
        mask = target.notna() & vals.notna()
        ic = float(spearmanr(vals[mask], target[mask])[0]) if mask.sum() >= 5 else float("nan")
        scored.append({"formula": f, "ic": 0.0 if np.isnan(ic) else ic, "vals": vals, "cand_idx": None})
    for idx, cand in enumerate(candidates):
        formula = cand.get("formula") or quant_gp_expr_to_formula(cand.get("qg_expr", ""), feature_names or [])
        if not formula:
            continue
        vals = _eval_long(formula)
        if vals is None:
            continue
        mask = target.notna() & vals.notna()
        ic = float(spearmanr(vals[mask], target[mask])[0]) if mask.sum() >= 5 else float("nan")
        scored.append({"formula": formula, "ic": 0.0 if np.isnan(ic) else ic, "vals": vals, "cand_idx": idx})
    if not scored:
        return candidates, {"enabled": True, "n_total": len(candidates),
                            "n_kept": len(candidates), "scored": []}

    # 4. 按 |ic| 降序贪婪挑选 + 相关去冗余 (池化 Pearson, 与已选因子全时段相关 < 阈值)
    scored_sorted = sorted(scored, key=lambda x: abs(x["ic"]), reverse=True)
    selected: List[Dict[str, Any]] = []
    selected_vals: List[pd.Series] = []
    for item in scored_sorted:
        if not selected:
            item["max_corr"] = 0.0
            item["corr_rejected"] = False
            selected.append(item)
            selected_vals.append(item["vals"])
        else:
            max_corr = 0.0
            for sv in selected_vals:
                corr = float(np.corrcoef(item["vals"], sv)[0, 1])
                if np.isnan(corr):
                    corr = 0.0
                max_corr = max(max_corr, abs(corr))
            item["max_corr"] = max_corr
            if max_corr < corr_threshold:
                item["corr_rejected"] = False
                selected.append(item)
                selected_vals.append(item["vals"])
            else:
                item["corr_rejected"] = True

    # 5. |IC| 阈值 -> 兜底/上限
    survivors = [it for it in selected if abs(it["ic"]) >= ic_threshold]
    if len(survivors) < min_factors_fallback:
        survivors = sorted(scored, key=lambda x: abs(x["ic"]), reverse=True)[:min_factors_fallback]
        fallback_used = True
    else:
        survivors = sorted(survivors, key=lambda x: abs(x["ic"]), reverse=True)[:max_factors_in_pool]
        fallback_used = False
    survivor_formulas = {it["formula"] for it in survivors}

    # 6. 回填报告 reason, 提取幸存新候选
    kept_candidates: List[Dict[str, Any]] = []
    kept_idx = set()
    for it in scored:
        kept = it["formula"] in survivor_formulas
        if kept and it["cand_idx"] is not None:
            kept_idx.add(it["cand_idx"])
    kept_candidates = [c for i, c in enumerate(candidates) if i in kept_idx]

    report_items = []
    for it in scored:
        kept = it["formula"] in survivor_formulas
        if kept:
            reason = "通过"
        elif it.get("corr_rejected"):
            reason = "与已选因子高相关"
        elif abs(it["ic"]) < ic_threshold:
            reason = "|IC|低于阈值"
        else:
            reason = "超出上限"
        report_items.append({"formula": it["formula"], "ic": round(it["ic"], 4),
                             "max_corr": round(it.get("max_corr", 0.0), 4),
                             "kept": kept, "reason": reason})

    report = {
        "enabled": True,
        "n_total": len(scored),
        "n_kept": len(kept_candidates),
        "ic_threshold": ic_threshold,
        "corr_threshold": corr_threshold,
        "min_factors_fallback": min_factors_fallback,
        "max_factors_in_pool": max_factors_in_pool,
        "fallback_used": fallback_used,
        "scored": report_items,
    }
    return kept_candidates, report


def _evaluate_factor_tensor(model, program, data):
    """用原版 ProgramEvaluator 计算候选因子值 [T,N]

    与训练同一套机制: execute_tensor -> transformer -> clean_factor ->
    normalize_by_day (取决于 model.normalize)。
    """
    from lib.quantgplearn_local.evaluator import ProgramEvaluator
    ev = ProgramEvaluator(
        data, model._metric, transformer=getattr(model, "_transformer", None),
        cache_scores=False, cache_factors=False,
        normalize=getattr(model, "normalize", True))
    return ev.evaluate_factor(program)


def _candidate_metrics(model, program, data) -> Dict[str, Any]:
    """用原版 TensorFitness 计算候选在 data 上的全套指标 (IC/RankIC/ICIR/RankICIR)

    返回 {ic, rank_ic, icir, rank_icir} (无效值置 None)。
    """
    from lib.quantgplearn_local.tensor_fitness import mean_ic, mean_rank_ic, icir, rank_icir
    f = _evaluate_factor_tensor(model, program, data)
    if data.target is None:
        return {"ic": None, "rank_ic": None, "icir": None, "rank_icir": None}
    out: Dict[str, Any] = {}
    for name, fn in (("ic", mean_ic), ("rank_ic", mean_rank_ic),
                     ("icir", icir), ("rank_icir", rank_icir)):
        try:
            v = float(fn(data.target, f, data=data))
        except Exception:
            v = float("nan")
        out[name] = v if np.isfinite(v) else None
    return out


def _program_expr(p) -> str:
    """取程序的原版表达式字符串"""
    return p.generate_my_output() if hasattr(p, "generate_my_output") else str(p)


def oos_recheck_quantgp(model, test_panel: Dict[str, pd.DataFrame],
                        feature_names: Optional[Sequence[str]],
                        rebal_period: int = 5) -> List[Dict[str, Any]]:
    """A 档 OOS 复核: 在测试段用原版机制重算候选指标, 判断是否过拟合

    因子值来自原版 transform 机制 (与训练同一套 evaluate_factor/clean/normalize),
    指标用原版 TensorFitness (mean_ic/mean_rank_ic/icir/rank_icir)。

    返回 [{qg_expr, ic, rank_ic, icir, rank_icir, oos_ok}]:
        oos_ok: 测试段 RankIC 有效 (候选在样本外可计算)。
    """
    data = _make_tensor_data(model, test_panel, feature_names, rebal_period)
    if data is None or data.target is None:
        return []
    out: List[Dict[str, Any]] = []
    for p in getattr(model, "_best_programs", []) or []:
        m = _candidate_metrics(model, p, data)
        out.append({"qg_expr": _program_expr(p), **m,
                    "oos_ok": m.get("rank_ic") is not None})
    return out


def permutation_significance_quantgp(model, test_panel: Dict[str, pd.DataFrame],
                                     rebal_period: int = 5,
                                     n_perm: int = 1000,
                                     random_state: Optional[int] = None) -> List[Dict[str, Any]]:
    """A 档 permutation 显著性检验 (原版机制): 打乱测试段 target 行, 空分布 RankIC + p 值

    候选因子值只 evaluate 一次, 之后每次 permutation 只打乱目标收益 target 的
    行(日期)顺序、重算逐日截面 RankIC 均值 (与训练同口径 mean_rank_ic)。

    返回 [{qg_expr, real_ic, null_mean, null_std, p_value, significant}]:
        real_ic:    真实 (未打乱) RankIC
        p_value:    (1 + #{|null_ic| >= |real_ic|}) / (1 + n_perm)
        significant: p_value < 0.05 (双侧)
    """
    if not test_panel or n_perm < 1:
        return []
    first = next(iter(test_panel))
    if len(test_panel[first].index) < 40:
        return []
    data = _make_tensor_data(model, test_panel,
                             list(getattr(model, "feature_names_", None) or DEFAULT_FEATURES),
                             rebal_period)
    if data is None or data.target is None:
        return []
    import torch as _t
    from lib.quantgplearn_local.tensor_fitness import mean_rank_ic
    # 生成器需与数据同设备 (cuda 时不能复用默认 CPU 生成器)
    gen = None
    if random_state is not None:
        gen = _t.Generator(device=str(data.device)).manual_seed(random_state)
    target = data.target
    n_rows = target.shape[0]
    out: List[Dict[str, Any]] = []
    for p in getattr(model, "_best_programs", []) or []:
        qg_expr = _program_expr(p)
        f = _evaluate_factor_tensor(model, p, data)
        try:
            real_ic = float(mean_rank_ic(target, f, data=data))
        except Exception:
            real_ic = float("nan")
        if not np.isfinite(real_ic):
            out.append({"qg_expr": qg_expr, "real_ic": None, "null_mean": None,
                        "null_std": None, "p_value": None, "significant": None})
            continue
        null_ics = np.empty(n_perm, dtype=np.float64)
        for k in range(n_perm):
            perm_idx = _t.randperm(n_rows, generator=gen, device=target.device)
            t_perm = target.index_select(0, perm_idx)
            try:
                null_ics[k] = float(mean_rank_ic(t_perm, f, data=data))
            except Exception:
                null_ics[k] = float("nan")
        valid = null_ics[~np.isnan(null_ics)]
        null_mean = float(np.mean(valid)) if len(valid) else None
        null_std = float(np.std(valid)) if len(valid) > 1 else None
        denom = int(np.sum(np.abs(valid) >= abs(real_ic)))
        p_value = (1.0 + denom) / (1.0 + n_perm)
        out.append({
            "qg_expr": qg_expr,
            "real_ic": round(real_ic, 6),
            "null_mean": round(null_mean, 6) if null_mean is not None else None,
            "null_std": round(null_std, 6) if null_std is not None else None,
            "p_value": round(p_value, 6),
            "significant": bool(p_value < 0.05),
        })
    return out


def _daily_rank_ic_series(data, factor) -> np.ndarray:
    """计算逐日截面 RankIC 序列 (与训练同口径 batch_spearmanr)

    返回 [T] float ndarray (无效日置 NaN)。供 Deflated Sharpe / Subsample /
    Decay / CV 各检验复用, 保证与 mean_rank_ic 完全同口径。
    """
    import torch as _t
    from lib.quantgplearn_local.tensor_fitness import batch_spearmanr
    ic = batch_spearmanr(factor, data.target, mask=data.mask)
    out = ic.detach().cpu().numpy() if _t.is_tensor(ic) else np.asarray(ic)
    return out.astype(np.float64)


def _deflated_sharpe(ic_series: np.ndarray, n_trials: int,
                     annualization: float = 252.0) -> Dict[str, Any]:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014), 用逐日 RankIC 序列映射

    原版是组合净 Sharpe 的 deflate; 这里把 RankIC 序列当"日度收益代理":
      SR_hat   = mean(ic) / std(ic) * sqrt(annualization)      (日度 IC 的年化 Sharpe 代理)
      SR_0     = 纯噪声下 N 次试验的期望最大 Sharpe (E[max z], 经验公式)
      gamma3   = ic 序列偏度, gamma4 = 峰度
      DSR      = Z[ (SR_hat - SR_0) * sqrt(n-1) / sqrt(1 - gamma3*SR_hat + (gamma4-1)/4*SR_hat^2) ]
    返回 {sharpe, sr_0, deflated_sharpe, p_value, passed} (无效返回 None/passed=False)
    """
    import scipy.stats as ss
    from scipy.stats import norm
    ic = ic_series[np.isfinite(ic_series)]
    if len(ic) < 5 or float(np.std(ic)) == 0:
        return {"sharpe": None, "sr_0": None, "deflated_sharpe": None,
                "p_value": None, "passed": False}
    mu = float(np.mean(ic))
    sd = float(np.std(ic))
    sharpe = mu / sd * float(np.sqrt(annualization))
    n = len(ic)
    gamma3 = float(ss.skew(ic))
    gamma4 = float(ss.kurtosis(ic, fisher=False))
    # 纯噪声下 N 次独立试验期望最大标准正态 z (Bailey & Lopez de Prado 经验式)
    # E[max z ~ N] ≈ (1-gamma_eul)*Phi^{-1}(1-1/N) + gamma_eul*Phi^{-1}(1-1/(N*e))
    gamma_eul = 0.5772156649
    if n_trials <= 1:
        sr_0 = 0.0
    else:
        z1 = norm.ppf(1.0 - 1.0 / n_trials)
        z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        sr_0 = (1.0 - gamma_eul) * z1 + gamma_eul * z2
    num = (sharpe - sr_0) * float(np.sqrt(n - 1))
    denom = float(np.sqrt(1.0 - gamma3 * sharpe + (gamma4 - 1.0) / 4.0 * sharpe ** 2))
    if not np.isfinite(denom) or denom <= 0:
        dsr = 0.0
    else:
        dsr = float(num / denom)
    p_value = float(norm.cdf(dsr))
    # DSR 为负 -> 即使考虑试验次数也不显著; DSR>0 且 p>0.95 才通过 (单侧, deflate 后显著)
    passed = bool(dsr > 0.0 and p_value > 0.95)
    return {"sharpe": round(sharpe, 4), "sr_0": round(sr_0, 4),
            "deflated_sharpe": round(dsr, 4), "p_value": round(p_value, 4),
            "passed": passed}


def _subsample_stability(data, factor, n_splits: int = 20,
                         random_state: Optional[int] = None) -> Dict[str, Any]:
    """标的子样本稳定性 (原版 Instrument Subsample Stability): 随机对半标的 n_splits 次

    每次把 N 只标的随机对半, 在每半上重算逐日 RankIC 均值, 统计两半 RankIC 均为正
    的比例 (>=50% 稳定)。返回 {stability, positive_pairs, total} (无效返回 None)。
    """
    import torch as _t
    from lib.quantgplearn_local.tensor_fitness import batch_spearmanr
    # 生成器需与数据同设备 (cuda 时不能复用默认 CPU 生成器)
    gen = None
    if random_state is not None:
        gen = _t.Generator(device=str(data.device)).manual_seed(random_state)
    n_sym = int(data.n_symbols)
    if n_sym < 8 or n_splits < 1:
        return {"stability": None, "positive_pairs": 0, "total": 0}
    positive = 0
    total = 0
    for _ in range(n_splits):
        perm = _t.randperm(n_sym, generator=gen, device=data.device)
        half = perm[: n_sym // 2]
        mask = data.mask.index_select(1, half)
        f_sub = factor.index_select(1, half)
        t_sub = data.target.index_select(1, half)
        ic = batch_spearmanr(f_sub, t_sub, mask=mask)
        ic_arr = ic.detach().cpu().numpy() if _t.is_tensor(ic) else np.asarray(ic)
        ic_arr = ic_arr.astype(np.float64)
        half1_ok = bool(np.nanmean(ic_arr) > 0) if np.isfinite(np.nanmean(ic_arr)) else False
        # 对另一半
        other = perm[n_sym // 2:]
        if other.numel() == 0:
            continue
        mask2 = data.mask.index_select(1, other)
        f2 = factor.index_select(1, other)
        t2 = data.target.index_select(1, other)
        ic2 = batch_spearmanr(f2, t2, mask=mask2)
        ic2_arr = ic2.detach().cpu().numpy() if _t.is_tensor(ic2) else np.asarray(ic2)
        ic2_arr = ic2_arr.astype(np.float64)
        half2_ok = bool(np.nanmean(ic2_arr) > 0) if np.isfinite(np.nanmean(ic2_arr)) else False
        total += 1
        if half1_ok and half2_ok:
            positive += 1
    stability = float(positive / total) if total else None
    return {"stability": round(stability, 4) if stability is not None else None,
            "positive_pairs": positive, "total": total}


def _decay_analysis(model, test_panel, feature_names, horizons, rebal_period=5,
                    program=None) -> Dict[str, Any]:
    """Decay Analysis: 在 [1,2,5,10,20] 等 horizon 上重算候选 RankIC

    真实信号随预测期延长平滑衰减, 噪声信号非单调杂乱。返回
    {horizons: [...], rank_ic: [...], monotonic_decay} (无效返回空)。
    注: 每个 horizon 用独立 rebal_period 构造 TensorPanelData, 因子值不变 (与训练同机制)。
    """
    out_ic: List[Optional[float]] = []
    for h in horizons:
        try:
            h = int(h)
            if h < 1:
                out_ic.append(None)
                continue
            data_h = _make_tensor_data(model, test_panel, feature_names, h)
            if data_h is None or data_h.target is None:
                out_ic.append(None)
                continue
            f = _evaluate_factor_tensor(model, program, data_h)
            ics = _daily_rank_ic_series(data_h, f)
            val = float(np.nanmean(ics)) if np.isfinite(np.nanmean(ics)) else None
            out_ic.append(val)
        except Exception:
            out_ic.append(None)
    valid = [v for v in out_ic if v is not None]
    monotonic = False
    if len(valid) >= 2 and abs(valid[0]) > 1e-9:
        # 真实信号: |RankIC| 随 horizon 单调递减 (平滑衰减)
        absv = [abs(v) for v in valid]
        monotonic = bool(all(absv[i] >= absv[i + 1] for i in range(len(absv) - 1)))
    return {"horizons": [int(h) for h in horizons], "rank_ic": out_ic,
            "monotonic_decay": monotonic}


def _cv_consistency(model, train_panel, feature_names, n_folds: int = 3,
                    rebal_period: int = 5, program=None) -> Dict[str, Any]:
    """CV Consistency: 训练段内 expanding folds 各折验证段 RankIC 为正的比例

    对齐原版 "3 expanding folds of purged time-series CV": 把训练段按时间切 n_folds
    个 expanding 验证子段, 每个子段用同一候选因子求值算 RankIC, 统计正的比例
    (>=75% 判定稳健)。返回 {positive_ratio, n_folds, positive} (无效返回 None)。
    注意: 只在训练段内部折叠, 不碰测试段, 不污染 OOS 口径。
    """
    if not train_panel or n_folds < 2:
        return {"positive_ratio": None, "n_folds": n_folds, "positive": 0}
    first = next(iter(train_panel))
    dates = train_panel[first].index
    if len(dates) < n_folds * 10:
        return {"positive_ratio": None, "n_folds": n_folds, "positive": 0}
    boundaries = np.linspace(0, len(dates), n_folds + 1, dtype=int)
    positive = 0
    checked = 0
    for i in range(n_folds):
        # expanding 验证子段: 用 [start, boundary[i+1]] 作为该折验证段
        seg_start = dates[0]
        seg_end = dates[min(int(boundaries[i + 1]) - 1, len(dates) - 1)]
        try:
            seg_panel = trim_panel_dates(train_panel, str(seg_start), str(seg_end))
            if len(next(iter(seg_panel.values())).index) < 10:
                continue
            data_seg = _make_tensor_data(model, seg_panel, feature_names, rebal_period)
            if data_seg is None or data_seg.target is None:
                continue
            f = _evaluate_factor_tensor(model, program, data_seg)
            ics = _daily_rank_ic_series(data_seg, f)
            val = float(np.nanmean(ics)) if np.isfinite(np.nanmean(ics)) else None
            if val is None:
                continue
            checked += 1
            if val > 0:
                positive += 1
        except Exception:
            continue
    ratio = float(positive / checked) if checked else None
    return {"positive_ratio": round(ratio, 4) if ratio is not None else None,
            "n_folds": checked, "positive": positive}


def fdr_gauntlet_quantgp(model, test_panel, train_panel, feature_names,
                         rebal_period: int = 5,
                         n_perm: int = 1000,
                         n_trials: int = 96,
                         n_subsample: int = 20,
                         decay_horizons: Optional[List[int]] = None,
                         cv_folds: int = 3,
                         random_state: Optional[int] = None) -> List[Dict[str, Any]]:
    """A 档假发现门闸 (完全复刻 saulius.io QuantAlpha 的 False Discovery Gauntlet)

    原版对最终 best model 跑 5 项互补检验 + 预设阈值分级:
      Permutation (1000 次) / Deflated Sharpe (N 次试验) / Subsample stability /
      Decay analysis / CV consistency -> Verdict: ROBUST / MARGINAL / UNSTABLE

    本函数对已训练好的 _best_programs 在"测试段 (perm/subsample/decay) + 训练段
    (CV consistency)"上做只读评估, 不修改 QuantGplearn 源码、不改训练段、不改候选。

    返回 [每个候选一个 dict]:
      {qg_expr,
       perm:{real_ic, p_value, significant},
       deflated_sharpe:{sharpe, sr_0, deflated_sharpe, p_value, passed},
       subsample:{stability, positive_pairs, total},
       decay:{horizons, rank_ic, monotonic_decay},
       cv:{positive_ratio, n_folds, positive},
       verdict: ROBUST / MARGINAL / UNSTABLE (任一检验失败置 None)}
    """
    if not test_panel or not train_panel:
        return []
    first_t = next(iter(test_panel))
    first_r = next(iter(train_panel))
    if len(test_panel[first_t].index) < 40 or len(train_panel[first_r].index) < 30:
        return []
    horizons = [int(h) for h in (decay_horizons or [1, 2, 5, 10, 20])]
    data = _make_tensor_data(model, test_panel,
                             list(getattr(model, "feature_names_", None) or DEFAULT_FEATURES),
                             rebal_period)
    if data is None or data.target is None:
        return []
    import torch as _t
    from lib.quantgplearn_local.tensor_fitness import mean_rank_ic
    # 生成器需与数据同设备 (cuda 时不能复用默认 CPU 生成器)
    gen = None
    if random_state is not None:
        gen = _t.Generator(device=str(data.device)).manual_seed(random_state)
    n_rows = data.target.shape[0]
    out: List[Dict[str, Any]] = []
    for p in getattr(model, "_best_programs", []) or []:
        qg_expr = _program_expr(p)
        f = _evaluate_factor_tensor(model, p, data)
        # 1) Permutation (1000 次, 对齐原版)
        try:
            real_ic = float(mean_rank_ic(data.target, f, data=data))
        except Exception:
            real_ic = float("nan")
        if not np.isfinite(real_ic):
            out.append({"qg_expr": qg_expr, "perm": None, "deflated_sharpe": None,
                        "subsample": None, "decay": None, "cv": None, "verdict": None})
            continue
        null_ics = np.empty(n_perm, dtype=np.float64)
        for k in range(n_perm):
            perm_idx = _t.randperm(n_rows, generator=gen, device=data.device)
            t_perm = data.target.index_select(0, perm_idx)
            try:
                null_ics[k] = float(mean_rank_ic(t_perm, f, data=data))
            except Exception:
                null_ics[k] = float("nan")
        valid_null = null_ics[~np.isnan(null_ics)]
        denom = int(np.sum(np.abs(valid_null) >= abs(real_ic)))
        p_perm = (1.0 + denom) / (1.0 + n_perm)
        perm = {"real_ic": round(real_ic, 6), "p_value": round(p_perm, 6),
                "significant": bool(p_perm < 0.05)}
        # 2) Deflated Sharpe (用测试段逐日 RankIC 序列 + 试验次数)
        ics = _daily_rank_ic_series(data, f)
        dsr = _deflated_sharpe(ics, n_trials)
        # 3) Subsample stability (测试段, 随机对半标的)
        sub = _subsample_stability(data, f, n_splits=n_subsample, random_state=random_state)
        # 4) Decay analysis (测试段, 多 horizon)
        dec = _decay_analysis(model, test_panel, feature_names, horizons, rebal_period, program=p)
        # 5) CV consistency (训练段 expanding folds)
        cv = _cv_consistency(model, train_panel, feature_names, n_folds=cv_folds,
                             rebal_period=rebal_period, program=p)
        # Verdict (对齐原版预设阈值)
        verdict: Optional[str] = None
        cv_ratio = cv.get("positive_ratio")
        sub_stab = sub.get("stability")
        dsr_passed = dsr.get("passed")
        perm_sig = perm.get("significant")
        if (cv_ratio is not None and sub_stab is not None and dsr_passed is not None
                and perm_sig is not None and dsr.get("sharpe") is not None):
            # ROBUST: CV>=75% 且 perm p<0.05 且 subsample>50% 且 deflated 后仍显著
            if (cv_ratio >= 0.75 and perm_sig and sub_stab > 0.50 and dsr_passed):
                verdict = "ROBUST"
            # MARGINAL: CV>=50% 且 perm p<0.10
            elif cv_ratio >= 0.50 and float(perm.get("p_value")) < 0.10:
                verdict = "MARGINAL"
            else:
                verdict = "UNSTABLE"
        out.append({
            "qg_expr": qg_expr,
            "perm": perm,
            "deflated_sharpe": dsr,
            "subsample": sub,
            "decay": dec,
            "cv": cv,
            "verdict": verdict,
        })
    return out



