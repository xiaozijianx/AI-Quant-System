# -*- coding: utf-8 -*-
"""
routes/factor/mining/gp.py -- GP 因子挖掘路由
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
import asyncio
import hashlib
import json
import math
import queue
import threading
import time
from datetime import datetime, date
from collections import OrderedDict

from fastapi import APIRouter, Body, HTTPException
from sse_starlette.sse import EventSourceResponse

from lib.paths import setup_sys_path
setup_sys_path()

# JSON 安全清洗等公共工具统一放在 routes/common.py (Stage 5: 由 factor_common 迁移)
from routes.common import _json_safe, _json_safe_response

from lib.factor_db import (
    init_tables, list_factors, get_factor, upsert_factor, delete_factor,
    save_metrics, get_metrics_history, list_categories,
    list_bases, get_base,
    save_eval_result, get_eval_result,
    save_factor_package, list_factor_packages, get_factor_package, delete_factor_package,
    update_evaluation_type,
)
from lib.factor_engine import (
    validate_expression, evaluate_expression, calc_basic_factors,
    run_layered_backtest, run_ic_timeseries,
    run_ic_timeseries_panel, calc_factor,
    cs_Rank, cs_Zscore, cs_TransNorm,
    ts_Delay, ts_Mean, ts_Decay, ts_DecayExp, ts_Max, ts_Min,
    ts_Delta, ts_Stdev, ts_Sum, ts_Kurtosis, ts_Skewness, ts_Median,
    # 清华评价方法 (Phase 1 融合)
    PerformanceWithCost, build_total_return_panel, groupby_Rank,
    classify_factor_type, evaluate_pattern_factor,
    GetCost, GetTurnover, GetQuantileRet,
    run_single_ic_timeseries,
    # 多因子评价 (融合 网格/机器学习/CASE-C)
    factor_correlation_matrix,
    rank_score_synthesis, marketcap_neutralize,
    financial_report_rebal_dates,
    # 多因子分阶段流程 (阶段B1数据准备 + 阶段B2合成评价)
    prep_multi_factor, synth_multi_factor_eval,
    # 方向语义统一 (字符串/整数 → 1/-1/0)
    direction_to_int,
    # 时序标准化工具 (technical_ts 因子评价/合成共用, 与批量评估同口径)
    ts_rank_normalize, resolve_ts_window,
    # F0 预检与自动匹配规划器 (合成前容错: 可计算/类型判定 + 方法×类型自动匹配)
    preflight_factors, auto_match_factors,
    # F1 组合风险分析 (通用 Barra 风格暴露面板)
    build_barra_style_panels,
    # F2 信号方向得分独立轨 (信号因子 -> 每股综合方向得分)
    build_signal_direction_score_panel,
)

router = APIRouter()


def _run_gp_pipeline(body: Dict[str, Any],
                     progress_cb: Optional[Callable[[int, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """
    GP 遗传规划自动因子挖掘 (因子库外新因子自动生成)
    设计: docs/因子挖掘页面设计方案.md 4.6 (以 QuantGplearn 进化循环为骨架, 复用现有因子引擎)
    来源: lib/factor_gp.py (自写轻量 GP 内核, 不引入 gplearn/sklearn 依赖)

    progress_cb: 每代完成的进度回调 (gen, stats_dict), 供 SSE 流式进度 (阶段3.3); None=不回调

    body: {
        stock_codes: [...], pool_type: "...", pool_ref: "...",
        start_date: "2023-01-01", end_date: "2025-12-31",
        population_size: 150, generations: 40, max_depth: 4,
        rebal_period: 5,           # 调仓周期/持有期
        ts_normalize_window: null, # 时序标准化窗口 (technical_ts 类用, 默认不启用)
        tournament_size: 5,
        p_crossover: 0.9, p_subtree_mutation: 0.02, p_hoist_mutation: 0.01, p_point_mutation: 0.02,
        parsimony: 0.001,
        use_warm_start: true,      # 是否注入库内因子 formula 到初始种群
        train_ratio: 0.7,          # 训练/测试分段比例 (进化在训练段, Top-N 在测试段 OOS 复核)
        marketcap_neutralize: false,  # 市值中性化适应度 (压制规模因子, 用成交额点-in-time代理)
        filter_bare_fields: true,      # 过滤纯裸字段表达式 (无算子调用, 无增量信息)
        neutralize_styles: false,      # 阶段5.2 #6 多因子风格中性化 (华泰 GP 金工系列21):
                                       # 市值扩展为 行业哑变量+过去收益+换手+波动 多列回归取残差 (需 use_gpu)
        style_ret_window: 20,          # 风格中性化: 过去收益窗口 (交易日)
        style_vol_window: 20,          # 风格中性化: 历史波动窗口 (交易日)
        style_use_turnover: true,      # 风格中性化: 是否纳入换手率列
        style_use_industry: true,      # 风格中性化: 是否纳入行业哑变量列 (需申万一级映射)
        corr_thresh: 0.8,             # 候选去冗余阈值 (复刻 QuantGplearn tolerable_corr; None/0=关闭)
        space_level: "L0",            # 搜索空间层级: L0(默认受限子集)/L1(追加新时序算子: DecayExp/CumReturn/Shift/Count/LINEARREG等)/L2(追加基类叶子: 参数化基类+固定参数基类)
        diversity_weight: 0.02,       # 多样性奖励权重 (阶段3.2)
        pca_qd: false,                # 阶段5.2 #7 PCA-QD 多样性引导 (AutoAlpha; PCA特征空间新奇性搜索替代Jaccard, 需GPU)
        n_jobs: 1,                    # 并行评估进程数 (阶段3.3; 默认1=串行)
        wf_folds: 3,                  # 多段 walk-forward 重验证段数 (阶段3.1; 0/1=关闭)
        random_state: 42,
        return_candidates: 20
    }
    """
    from lib.factor_gp import (
        evolve, split_train_test_dates, oos_recheck, trim_panel_to_dates,
        walk_forward_recheck, permutation_significance, formula_parseable_gpu,
    )

    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2023-01-01")
    end_date = body.get("end_date", "2025-12-31")
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    # 支持股票池类型 (同 mine_svd/mine_ml)
    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception:
            pass
    if not stock_codes or len(stock_codes) < 30:
        from lib.factor_evaluator import get_active_stock_pool
        auto_pool = get_active_stock_pool(n=80, min_days=200)
        if stock_codes:
            seen = set(stock_codes)
            for c in auto_pool:
                if c not in seen:
                    stock_codes.append(c)
                    seen.add(c)
        else:
            stock_codes = auto_pool

    # 加载行情面板 (panel 与 prices_panel 同一份: 字段面板用于 evaluate_expression,
    # 价格面板用于 run_ic_timeseries_panel 算未来收益)
    from lib.backtest_data import load_daily_kline
    panel = {}
    for code in stock_codes[:80]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > 130:
                panel[code] = df
        except Exception:
            pass
    if len(panel) < 10:
        raise HTTPException(status_code=400, detail=f"有效股票数据不足10只 (当前 {len(panel)} 只)")

    # ---- 训练/验证/测试 三重分段 (阶段5.1: 进化早停用验证段, OOS 复核只碰测试段) ----
    train_ratio = float(body.get("train_ratio", 0.7))
    val_ratio = float(body.get("val_ratio", 0.15))  # 三重分段: 验证段比例 (0=退化为两段)
    train_start, train_end, val_start, val_end, test_start, test_end = split_train_test_dates(
        panel, start_date, end_date, train_ratio, val_ratio)
    train_panel = trim_panel_to_dates(panel, train_start, train_end)
    if len(train_panel) < 10:
        train_panel = panel  # 训练段过短则退化为全区间
    # 验证段 (仅用于 evolve 早停判断; 空验证段时沿用训练段行为)
    val_panel = trim_panel_to_dates(panel, val_start, val_end) if val_ratio > 0 else {}
    if val_panel and len(val_panel) < 5:
        val_panel = {}  # 验证段过短则禁用三重分段

    # ---- 参数 ----
    population_size = int(body.get("population_size", 150))
    generations = int(body.get("generations", 40))
    max_depth = int(body.get("max_depth", 4))
    rebal_period = int(body.get("rebal_period", 5))
    ts_normalize_window = body.get("ts_normalize_window")
    early_stop_gens = int(body.get("early_stop_gens", 5) or 0)   # 早停耐心(连续无改善代数, 0=关闭)
    tournament_size = int(body.get("tournament_size", 5))
    p_crossover = float(body.get("p_crossover", 0.9))
    p_subtree_mutation = float(body.get("p_subtree_mutation", 0.02))
    p_hoist_mutation = float(body.get("p_hoist_mutation", 0.01))
    p_point_mutation = float(body.get("p_point_mutation", 0.02))
    parsimony = float(body.get("parsimony", 0.001))
    # ---- 阶段 P4: 节点数上限 (对齐 QuantGplearn max_length, 默认 32; <=0 关闭) ----
    max_length = int(body.get("max_length", 32) or 0)
    use_warm_start = bool(body.get("use_warm_start", True))
    random_state = body.get("random_state", 42)
    return_candidates = int(body.get("return_candidates", 20))
    # ---- 市值中性化 / 裸字段过滤 / 去冗余开关 (2026-08-16 P0 + 阶段2.1 落地) ----
    marketcap_neutralize = bool(body.get("marketcap_neutralize", False))
    filter_bare_fields = bool(body.get("filter_bare_fields", True))
    marketcap_proxy_lookback = 20 if marketcap_neutralize else None
    # ---- 阶段5.2 #6 多因子风格中性化 (来源华泰证券 GP 金工系列21, 需 GPU 路径):
    # 市值(成交额代理)扩展为 行业哑变量 + 过去收益 + 换手 + 波动 多列回归取残差 ----
    neutralize_styles = bool(body.get("neutralize_styles", False))
    style_cfg: Optional[Dict[str, Any]] = None
    if neutralize_styles:
        style_cfg = {
            "ret_window": int(body.get("style_ret_window", 20) or 20),
            "vol_window": int(body.get("style_vol_window", 20) or 20),
            "use_turnover": bool(body.get("style_use_turnover", True)),
            "use_industry": bool(body.get("style_use_industry", True)),
        }
        # 风格中性化隐含市值列 (规模风险也纳入风格回归, 与设计"市值扩展为多因子"一致),
        # 确保市值代理窗口有值; 行业哑变量需申万一级映射 (面板内只保留>=3只行业, style_proxy 内剔除参照组)
        marketcap_proxy_lookback = marketcap_proxy_lookback or 20
        if style_cfg["use_industry"]:
            try:
                from lib.stock_classify import load_industry_map
                style_cfg["industry_map"] = load_industry_map(list(panel.keys()))
            except Exception:
                style_cfg["use_industry"] = False  # 行业映射不可用则仅用其余风格列
    corr_thresh = body.get("corr_thresh")
    if corr_thresh is not None:
        corr_thresh = float(corr_thresh)
    else:
        corr_thresh = 0.8  # 默认开启, 复刻原版 tolerable_corr 默认值
    # ---- 阶段5.2 #5 残差正交化 (来源 Auto-Alpha-Finding): 候选去冗余升级为
    # "新因子相对已选池回归取残差判增量", 比纯相关阈值更严格保证增量 alpha ----
    orthogonalize = bool(body.get("orthogonalize", False))
    min_incremental_ic = body.get("min_incremental_ic", 0.01)
    if min_incremental_ic is not None:
        try:
            min_incremental_ic = float(min_incremental_ic)
        except (TypeError, ValueError):
            min_incremental_ic = 0.01
    space_level = str(body.get("space_level") or "L0").upper()
    if space_level not in ("L0", "L1", "L2"):
        space_level = "L0"
    diversity_weight = body.get("diversity_weight")
    if diversity_weight is not None:
        try:
            diversity_weight = float(diversity_weight)
        except (TypeError, ValueError):
            diversity_weight = 0.02
    else:
        diversity_weight = 0.02  # 默认开启小幅多样性奖励 (阶段3.2)
    # ---- 阶段5.2 #7 PCA-QD 多样性引导 (来源 AutoAlpha, arXiv:2002.08245):
    # 把 Jaccard token 新颖性奖励升级为 PCA 特征空间距离奖励(新奇性搜索); 需 GPU 整树求值 ----
    pca_qd = bool(body.get("pca_qd", False))
    # ---- 阶段 P3 max_samples 数据降采样 (可选, 对齐 QuantGplearn):
    # 0<比例<1 时对股票维按比例抽样求值提速, 仅影响搜索阶段; None/<=0/>=1 关闭 ----
    max_samples = body.get("max_samples")
    if max_samples is not None:
        try:
            max_samples = float(max_samples)
        except (TypeError, ValueError):
            max_samples = None
    if max_samples is None or not (0.0 < max_samples < 1.0):
        max_samples = None
    # ---- 阶段5.2 #8 replacement 防早熟 (来源 AutoAlpha): 种群更替段"同质个体替换/排斥",
    # 当新生个体与已入下一代个体 token 相似度过高时, 低适应度者被替换为新变异个体;
    # 阈值 None/0 = 关闭, 保持与历史一致 (0.9 对齐 AutoAlpha 相似度红线) ----
    replacement_thresh = body.get("replacement_thresh")
    if replacement_thresh is not None:
        try:
            replacement_thresh = float(replacement_thresh)
        except (TypeError, ValueError):
            replacement_thresh = 0.0
        if replacement_thresh <= 0 or replacement_thresh >= 1:
            replacement_thresh = None
    else:
        replacement_thresh = None  # 默认关闭
    # ---- 阶段5.2 #8 hierarchical 分层搜索 (来源 AutoAlpha): 粗搜(受限算子L0)→细搜(扩算子L1/L2)
    # 两阶段, 把粗搜 Top-N 候选作为细搜 Warm-Start 基因, 复用现有 evolve 两次调用 ----
    hierarchical = bool(body.get("hierarchical", False))
    # ---- 阶段5.2 #9 适应度合成扩展 (来源 QuantGplearn tensor_fitness / GinkGO):
    # rank_ic(默认) / rank_icir(IC均值/IC标准差, 抗噪) / long_short_sharpe(多空组合夏普) ----
    fitness_mode = str(body.get("fitness_mode") or "rank_ic")
    if fitness_mode not in ("rank_ic", "rank_icir", "long_short_sharpe"):
        fitness_mode = "rank_ic"
    n_jobs = int(body.get("n_jobs", 1) or 1)  # 并行评估进程数 (阶段3.3)
    if n_jobs < 1:
        n_jobs = 1
    wf_folds = int(body.get("wf_folds", 3) or 0)  # 多段 walk-forward 重验证段数 (阶段3.1; 0/1=关闭)
    # ---- GPU 批量评估开关 (阶段4.1; 底层 lib/factor_gpu_evaluator.py, 仅 OOS/WF 批量精评启用) ----
    use_gpu = body.get("use_gpu", False)
    if isinstance(use_gpu, str):
        use_gpu = use_gpu.lower() in ("1", "true", "yes", "on")
    use_gpu = bool(use_gpu)
    # ---- GPU 树间多流并发数 (阶段 P2#8): 仅 use_gpu=True 且 CUDA 生效;
    # 1=退化为原串行, 默认 2; 非法值钳制到 1~64 ----
    gpu_streams = int(body.get("gpu_streams", 2) or 2)
    if gpu_streams < 1:
        gpu_streams = 1
    elif gpu_streams > 64:
        gpu_streams = 64

    # ---- Warm-Start 基因: 库内技术类因子 formula 注入初始种群 ----
    # 阶段5.1.1 途径A: 先排除财务 FN/信号 CDL/超长公式, 再按"可解析成树且可 GPU 化"
    # 白名单筛选, 把通过者解析为 dict 树注入 (与随机树同构, 可 GPU 编译/可交叉拆解)
    warm_start_formulas: List[str] = []
    warm_start_trees: List[Any] = []
    if use_warm_start:
        try:
            all_factors = list_factors()
            warm_candidates = []
            for f in all_factors:
                formula = f.get("formula")
                if not formula or not str(formula).strip():
                    continue
                cat = f.get("category") or ""
                # 只用价量/技术类因子公式作基因 (排除财务 FN 与 CDL 信号)
                s = str(formula)
                if "FN(" in s or "ta_CDL" in s:
                    continue
                if len(s) > 120:  # 跳过超长公式 (复杂度过高不宜作基因)
                    continue
                warm_candidates.append(s)
            warm_candidates = warm_candidates[:int(population_size * 0.3)]
            # 途径A 白名单: 只注入"可解析成树 + gpu_supported 通过"的公式 (解析为树注入)
            for s in warm_candidates:
                tree = formula_parseable_gpu(s)
                if tree is not None:
                    warm_start_trees.append(tree)
                    warm_start_formulas.append(s)
        except Exception:
            warm_start_formulas = []
            warm_start_trees = []

    # ---- 执行进化 (训练段) ----
    # 阶段5.2 #8 hierarchical 分层搜索 (来源 AutoAlpha): 复用 evolve 的两次调用编排。
    # 粗搜(受限算子 L0) → 取粗搜 Top-N 候选 → 细搜(扩算子 space_level)以粗搜候选作 Warm-Start 基因。
    def _run_evolve_once(space_lvl: str,
                         warm_f: List[str],
                         warm_t: List[Any]) -> Dict[str, Any]:
        return evolve(
            train_panel, train_panel,
            population_size=population_size,
            generations=generations,
            max_depth=max_depth,
            rebal_period=rebal_period,
            min_warmup=max(60, min(130, len(next(iter(train_panel.values())).index) // 4)),
            ts_normalize_window=ts_normalize_window,
            early_stop_gens=early_stop_gens,
            tournament_size=tournament_size,
            p_crossover=p_crossover,
            p_subtree_mutation=p_subtree_mutation,
            p_hoist_mutation=p_hoist_mutation,
            p_point_mutation=p_point_mutation,
            parsimony=parsimony,
            max_length=max_length,
            # 阶段5.1.1: 优先注入"已解析的 dict 树"(可GPU化白名单筛选后), 无则回退旧字符串原子路径
            warm_start_formulas=warm_f if use_warm_start and not warm_t else None,
            warm_start_trees=warm_t if use_warm_start else None,
            warm_start_ratio=0.3,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
            filter_bare_fields=filter_bare_fields,
            corr_thresh=corr_thresh,
            space_level=space_lvl,
            diversity_weight=diversity_weight,
            n_jobs=n_jobs,
            progress_cb=progress_cb,
            random_state=random_state,
            verbose=False,
            use_gpu_tensor=use_gpu,
            gpu_streams=gpu_streams,
            val_panel=val_panel or None,
            val_prices_panel=val_panel or None,
            ortho_mode=orthogonalize,
            min_incremental_ic=min_incremental_ic,
            neutralize_styles=neutralize_styles,
            style_cfg=style_cfg,
            pca_qd=pca_qd,
            replacement_thresh=replacement_thresh,
            fitness_mode=fitness_mode,
            max_samples=max_samples,
        )

    hier_coarse: Optional[Dict[str, Any]] = None
    if hierarchical:
        # 粗搜: 受限算子集 L0 (快、覆盖主流结构)
        hier_coarse = _run_evolve_once("L0", warm_start_formulas, warm_start_trees)
        # 细搜 Warm-Start 基因: 取粗搜 Top-N 候选, 解析为树注入 (可 GPU 整树求值)
        coarse_exprs = [c["expr"] for c in hier_coarse.get("candidates", [])[:12]]
        fine_warm_formulas: List[str] = []
        fine_warm_trees: List[Any] = []
        for s in coarse_exprs:
            tree = formula_parseable_gpu(s)
            if tree is not None:
                fine_warm_trees.append(tree)
                fine_warm_formulas.append(s)
        # 细搜: 扩算子 (space_level) 深度探索, 粗搜候选作初始基因
        result = _run_evolve_once(space_level, fine_warm_formulas, fine_warm_trees)
        # 报告粗搜统计, 便于前端展示分层搜索两阶段信息
        result["hierarchical"] = True
        result["hier_coarse_candidates"] = len(hier_coarse.get("candidates", []))
        result["hier_coarse_curve"] = hier_coarse.get("evolution_curve", [])
        result["hier_coarse_best_fitness"] = hier_coarse.get("best_fitness")
        result["hier_fine_warm_count"] = len(fine_warm_trees)
    else:
        # 单次进化 (与历史行为一致)
        result = _run_evolve_once(space_level, warm_start_formulas, warm_start_trees)
        result["hierarchical"] = False

    # ---- 测试段 OOS 复核 (Top-N 候选) ----
    top_exprs = [c["expr"] for c in result.get("candidates", [])[:return_candidates]]
    oos = oos_recheck(
        top_exprs, panel, panel,
        test_start, test_end,
        rebal_period=rebal_period,
        min_warmup=max(30, min(90, len(next(iter(panel.values())).index) // 6)),
        ts_normalize_window=ts_normalize_window,
        marketcap_proxy_lookback=marketcap_proxy_lookback,
        style_cfg=style_cfg,
        use_gpu=use_gpu,
        fitness_mode=fitness_mode,
    )
    oos_map = {o["expr"]: o for o in oos}

    # ---- 多段 walk-forward 重验证 (阶段3.1, OOS 复核增强): 滚动多段测试, 判断候选稳健性 ----
    wf_recheck = []
    if wf_folds >= 2:
        wf_recheck = walk_forward_recheck(
            top_exprs, panel, panel,
            start_date, end_date,
            n_folds=wf_folds,
            rebal_period=rebal_period,
            min_warmup=max(30, min(90, len(next(iter(panel.values())).index) // 6)),
            ts_normalize_window=ts_normalize_window,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
            style_cfg=style_cfg,
            use_gpu=use_gpu,
            fitness_mode=fitness_mode,
        )
    wf_map = {w["expr"]: w for w in wf_recheck}

    # ---- permutation 假发现检验 (阶段5.1, 来源 QuantAlpha): walk_forward 之后的后处理 ----
    # 打乱目标收益日期 N 次得 IC 空分布, 计算候选 p 值/显著性标记 (缓解多重比较假发现)
    perm_n = int(body.get("perm_n", 200) or 0)
    perm_recheck = []
    if perm_n > 0 and top_exprs:
        perm_recheck = permutation_significance(
            top_exprs, panel, panel,
            start_date, end_date,
            n_perm=perm_n,
            rebal_period=rebal_period,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
            style_cfg=style_cfg,
            random_state=random_state,
            use_gpu=use_gpu,
            fitness_mode=fitness_mode,
        )
    perm_map = {p["expr"]: p for p in perm_recheck}

    # 合并测试段 IC 到候选
    candidates = result.get("candidates", [])[:return_candidates]
    for c in candidates:
        oo = oos_map.get(c["expr"])
        if oo:
            c["test_rank_ic"] = oo.get("test_rank_ic")
            c["test_rank_ic_ir"] = oo.get("test_rank_ic_ir")
            c["oos_ok"] = oo.get("oos_ok")
        else:
            c["test_rank_ic"] = None
            c["test_rank_ic_ir"] = None
            c["oos_ok"] = False
        # 方向: RankIC 为负时提示反向 (供前端展示/入库方向选择)
        c["direction"] = 1 if (c.get("rank_ic_mean") or 0) >= 0 else -1
        # 多段 walk-forward 结果 (阶段3.1)
        w = wf_map.get(c["expr"])
        c["wf_ok"] = bool(w["wf_ok"]) if w else None
        c["wf_mean_ic"] = w.get("mean_ic") if w else None
        c["wf_pass_ratio"] = w.get("pass_ratio") if w else None
        c["wf_fold_ics"] = w.get("fold_ics") if w else None
        # permutation 显著性 (阶段5.1)
        pm = perm_map.get(c["expr"])
        c["perm_p_value"] = pm.get("p_value") if pm else None
        c["perm_significant"] = pm.get("significant") if pm else None
        c["perm_null_mean"] = pm.get("null_mean") if pm else None

        # ---- technical / technical_ts 判定 + 双口径指标 (展示层) ----
        # 默认/自动类型: 候选自洽用"尺度不变性探测"(客观), 探测不到/歧义回退关键词启发式
        try:
            from lib.factor_gp import detect_ts_by_scale
            _auto = detect_ts_by_scale(c["expr"], train_panel)
            if _auto is None:
                from lib.factor_engine import _is_technical_ts_expression
                _auto = "technical_ts" if _is_technical_ts_expression(c["expr"]) else "technical"
        except Exception:
            _auto = "technical"
        c["auto_type"] = c.get("chosen_type") or _auto
        c["chosen_type"] = c["auto_type"]
        # TS 口径训练指标 (technical 口径的 rank_ic_mean/icir/layered 已在候选里)
        c["ts_rank_ic_mean"] = None
        c["ts_rank_ic_ir"] = None
        c["ts_layered"] = {}
        c["ts_samples"] = None
        try:
            _ts_win = int(ts_normalize_window) if ts_normalize_window else 250
            _tw_min_warmup = max(60, min(130, len(next(iter(train_panel.values())).index) // 4))
            from lib.factor_gp import fitness_expr
            _fit_ts, _res_ts = fitness_expr(
                c["expr"], train_panel, train_panel,
                rebal_period, _tw_min_warmup, _ts_win,
                marketcap_proxy_lookback, parsimony,
                route_ts_by_type=False)  # 展示层要"显式 TS 口径"指标(对所有候选)
            if _res_ts:
                c["ts_rank_ic_mean"] = _res_ts.get("rank_ic_mean")
                c["ts_rank_ic_ir"] = _res_ts.get("rank_ic_ir")
                c["ts_layered"] = _res_ts.get("layered", {})
                c["ts_samples"] = _res_ts.get("samples")
        except Exception:
            pass

    # ---- 结果持久化 (阶段2.3): 复用 factor_eval_result, eval_type=mining, eval_key=GP配置指纹 ----
    try:
        from lib.factor_db import save_eval_result
        mine_key = "gp"
        save_eval_result("mining", mine_key, {
            "candidates": candidates,
            "dedup_report": result.get("dedup_report"),
            "evolution_curve": result.get("evolution_curve", []),
            "best_expr": result.get("best"),
            "best_fitness": result.get("best_fitness"),
            "n_stocks_train": len(train_panel),
            "n_stocks_test": len(trim_panel_to_dates(panel, test_start, test_end)),
            "train_range": [str(train_start)[:10], str(train_end)[:10]],
            "val_range": ([str(val_start)[:10], str(val_end)[:10]] if val_panel else None),
            "test_range": [str(test_start)[:10], str(test_end)[:10]],
            "warm_start_used": len(warm_start_formulas),
        }, {
            "pool_type": pool_type,
            "pool_ref": pool_ref,
            "start_date": start_date,
            "end_date": end_date,
            "method": "gp",
            "rebal_period": rebal_period,
            "evaluation_type": "technical",
        })
    except Exception:
        pass  # 持久化失败不阻断主流程

    return {
        "n_stocks_train": len(train_panel),
        "n_stocks_test": len(trim_panel_to_dates(panel, test_start, test_end)),
        "train_range": [str(train_start)[:10], str(train_end)[:10]],
        "val_range": ([str(val_start)[:10], str(val_end)[:10]] if val_panel else None),
        "test_range": [str(test_start)[:10], str(test_end)[:10]],
        "warm_start_used": len(warm_start_formulas),
        "candidates": candidates,
        "dedup_report": result.get("dedup_report"),
        "evolution_curve": result.get("evolution_curve", []),
        "best_expr": result.get("best"),
        "best_fitness": result.get("best_fitness"),
        "generations": generations,
        "wf_folds": wf_folds,
        "wf_recheck": wf_recheck,
        "perm_n": perm_n,
        "perm_recheck": perm_recheck,
        "orthogonalize": orthogonalize,
        "min_incremental_ic": min_incremental_ic,
        "pca_qd": result.get("pca_qd", pca_qd),
        "pca_archive_size": result.get("pca_archive_size", 0),
        "replacement_thresh": replacement_thresh,
        "fitness_mode": fitness_mode,
        "max_samples": max_samples,
        "hierarchical": result.get("hierarchical", False),
        "hier_coarse_candidates": result.get("hier_coarse_candidates", 0),
        "hier_coarse_best_fitness": result.get("hier_coarse_best_fitness"),
        "hier_fine_warm_count": result.get("hier_fine_warm_count", 0),
        "params": {
            "population_size": population_size,
            "generations": generations,
            "max_depth": max_depth,
            "rebal_period": rebal_period,
            "ts_normalize_window": ts_normalize_window,
            "tournament_size": tournament_size,
            "p_crossover": p_crossover,
            "p_subtree_mutation": p_subtree_mutation,
            "p_hoist_mutation": p_hoist_mutation,
            "p_point_mutation": p_point_mutation,
            "parsimony": parsimony,
            "max_length": max_length,
            "use_warm_start": use_warm_start,
            "train_ratio": train_ratio,
            "val_ratio": val_ratio,
            "random_state": random_state,
            "marketcap_neutralize": marketcap_neutralize,
            "filter_bare_fields": filter_bare_fields,
            "corr_thresh": corr_thresh,
            "orthogonalize": orthogonalize,
            "min_incremental_ic": min_incremental_ic,
            "neutralize_styles": neutralize_styles,
            "style_cfg": style_cfg,
            "pca_qd": pca_qd,
            "replacement_thresh": replacement_thresh,
            "fitness_mode": fitness_mode,
            "max_samples": max_samples,
            "hierarchical": hierarchical,
            "space_level": space_level,
            "n_jobs": n_jobs,
            "use_gpu": use_gpu,
        },
    }


@router.post("/mine_gp")
@_json_safe_response
def mine_gp_factors(body: Dict[str, Any] = Body(...)):
    """GP 遗传规划自动因子挖掘 (同步版, 返回完整结果)"""
    return _run_gp_pipeline(dict(body), progress_cb=None)


@router.post("/mine_gp/stream")
def mine_gp_factors_stream(body: Dict[str, Any] = Body(...)):
    """GP 遗传规划自动因子挖掘 (SSE 流式版, 阶段3.3)

    与 /mine_gp 相同流程, 但每代完成后推送 progress 事件 (进化曲线实时刷新),
    最终推送 done 事件 (完整结果) 或 error 事件。
    事件类型: heartbeat / progress / done / error
    """
    q: "queue.Queue" = queue.Queue()

    def _progress_cb(gen: int, stats: Dict[str, Any]) -> None:
        try:
            q.put(("progress", stats))
            from lib.factor_mining_jobs import publish
            publish("gp", "progress", stats)
        except Exception:
            pass

    def _run() -> None:
        try:
            from lib.factor_mining_jobs import start_job, finish_job
            start_job("gp")
            result = _run_gp_pipeline(dict(body), progress_cb=_progress_cb)
            finish_job("gp", result)
            q.put(("done", result))
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            from lib.factor_mining_jobs import finish_job as _f
            _f("gp", None, detail)
            q.put(("error", {"error": detail}))

    threading.Thread(target=_run, daemon=True).start()

    def _event_gen():
        while True:
            try:
                kind, payload = q.get(timeout=1.0)
            except queue.Empty:
                yield {"event": "heartbeat", "data": json.dumps({"ts": time.time()})}
                continue
            if kind == "progress":
                yield {"event": "progress", "data": json.dumps(payload)}
            elif kind == "done":
                yield {"event": "done", "data": json.dumps(_json_safe(payload))}
                break
            elif kind == "error":
                yield {"event": "error", "data": json.dumps(payload)}
                break

    return EventSourceResponse(_event_gen())
