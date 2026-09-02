# -*- coding: utf-8 -*-
"""
routes/factor/mining/llm_gp.py -- LLM 增强 GP 因子挖掘路由

当前已迁移：/llm_gp/config 获取与保存。
待迁移：/mine_llm_gp/stream 及辅助函数。
"""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from sse_starlette.sse import EventSourceResponse

# JSON 安全清洗等公共工具统一放在 routes/common.py (Stage 5: 由 factor_common 迁移)
from routes.common import _json_safe, _json_safe_response
from lib.factor_db import list_factors, save_eval_result

router = APIRouter()


@router.get("/llm_gp/config")
def get_llm_gp_config():
    """读取 LLM 增强 GP 独立大模型配置 (factor_llm_config 表, 单行 id=1)"""
    from lib.factor_db import get_llm_config, _mask_key
    cfg = get_llm_config()
    if not cfg:
        return {"configured": False}
    return {
        "configured": True,
        "api_key": _mask_key(cfg.get("api_key") or ""),
        "base_url": cfg.get("base_url"),
        "model": cfg.get("model"),
        "temperature": cfg.get("temperature"),
        "max_tokens": cfg.get("max_tokens"),
    }


@router.post("/llm_gp/config")
@_json_safe_response
def save_llm_gp_config(body: Dict[str, Any] = Body(...)):
    """保存 LLM 增强 GP 独立大模型配置 (factor_llm_config 表, UPSERT 单行 id=1)"""
    from lib.factor_db import save_llm_config
    return save_llm_config(dict(body))


def _load_llm_gp_warm_formulas() -> List[str]:
    """取库内价量/技术类因子公式作 LLM 增强 GP 的 Warm-Start 基因

    与 GP 主线同口径: 排除财务 FN / 缠论 CDL / 超长公式 (复杂度过高不宜作基因)。
    """
    out: List[str] = []
    try:
        for f in list_factors():
            formula = f.get("formula")
            if not formula or not str(formula).strip():
                continue
            s = str(formula)
            if "FN(" in s or "ta_CDL" in s:
                continue
            if len(s) > 120:
                continue
            out.append(s)
    except Exception:
        out = []
    return out


def _run_llm_gp_pipeline(body: Dict[str, Any],
                         progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
                         gene_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
                         migration_cb: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """
    LLM 增强 GP 挖掘 (独立引擎, 阶段6.2)
    来源: 东吴证券金工《AI因子挖掘的双路径实践与Skill沉淀》
    四支柱: ① LLM 子表达式基因供给 ② 分岛进化 ③ 周期性 LLM 注入 ④ 低相关筛选(<0.70)

    body: {
        stock_codes/pool_type/pool_ref/start_date/end_date (同 GP),
        n_islands: 4, island_pop_size: 60, generations: 40, max_depth: 4,
        rebal_period: 5, ts_normalize_window: null,
        tournament_size: 5, p_crossover: 0.9,
        p_subtree_mutation: 0.02, p_hoist_mutation: 0.01, p_point_mutation: 0.02,
        parsimony: 0.001,
        migration_interval: 10, migrate_count: 6, migration_topology: "ring",
        inject_interval: 10, genes_per_inject: 12, max_inject_rounds: 3, gene_enabled: true,
        space_level: "L0", random_state: 42, use_warm_start: true,
        corr_thresh: 0.70,          # 东吴口径低相关筛选阈值
        filter_bare_fields: true, marketcap_neutralize: false,
        train_ratio: 0.7, val_ratio: 0.15, return_candidates: 20
    }
    大模型配置独立 (factor_llm_config 表), 不复用 AI 助手 providers.yaml。
    """
    from lib.factor_llm_gp import run_llm_gp_evolution, load_llm_config
    from lib.factor_gp import split_train_test_dates, oos_recheck, trim_panel_to_dates

    llm_cfg = load_llm_config()
    if not llm_cfg:
        raise HTTPException(status_code=400, detail="未配置 LLM 增强 GP 大模型, 请先在子页内配置 (api_key / model)")

    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2023-01-01")
    end_date = body.get("end_date", "2025-12-31")
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    # 支持股票池类型 (同 mine_svd/mine_ml/mine_gp)
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

    # 加载行情面板 (panel 与 prices_panel 同一份, 同 GP)
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

    # ---- 训练/测试两段分段 (LLM 增强 GP 无早停, 不设验证段, 训练数据尽量充足) ----
    train_ratio = float(body.get("train_ratio", 0.7))
    val_ratio = float(body.get("val_ratio", 0.0))
    train_start, train_end, val_start, val_end, test_start, test_end = split_train_test_dates(
        panel, start_date, end_date, train_ratio, val_ratio)
    train_panel = trim_panel_to_dates(panel, train_start, train_end)
    if len(train_panel) < 10:
        train_panel = panel  # 训练段过短则退化为全区间

    # ---- 参数 ----
    n_islands = int(body.get("n_islands", 4))
    island_pop_size = int(body.get("island_pop_size", 60))
    generations = int(body.get("generations", 40))
    max_depth = int(body.get("max_depth", 4))
    rebal_period = int(body.get("rebal_period", 5))
    ts_normalize_window = body.get("ts_normalize_window")
    tournament_size = int(body.get("tournament_size", 5))
    p_crossover = float(body.get("p_crossover", 0.9))
    p_subtree_mutation = float(body.get("p_subtree_mutation", 0.02))
    p_hoist_mutation = float(body.get("p_hoist_mutation", 0.01))
    p_point_mutation = float(body.get("p_point_mutation", 0.02))
    parsimony = float(body.get("parsimony", 0.001))
    # ---- 阶段 P4: 节点数上限 (对齐 QuantGplearn max_length, 默认 32; <=0 关闭) ----
    max_length = int(body.get("max_length", 32) or 0)
    migration_interval = int(body.get("migration_interval", 10))
    migrate_count = int(body.get("migrate_count", 6))
    migration_topology = str(body.get("migration_topology", "ring") or "ring")
    inject_interval = int(body.get("inject_interval", 10))
    genes_per_inject = int(body.get("genes_per_inject", 12))
    max_inject_rounds = int(body.get("max_inject_rounds", 3))
    gene_enabled = bool(body.get("gene_enabled", True))
    space_level = str(body.get("space_level") or "L0").upper()
    if space_level not in ("L0", "L1", "L2"):
        space_level = "L0"
    random_state = body.get("random_state", 42)
    use_warm_start = bool(body.get("use_warm_start", True))
    corr_thresh = body.get("corr_thresh")
    if corr_thresh is None:
        corr_thresh = 0.70  # 东吴口径: 低相关筛选阈值
    else:
        corr_thresh = float(corr_thresh)
    filter_bare_fields = bool(body.get("filter_bare_fields", True))
    marketcap_neutralize = bool(body.get("marketcap_neutralize", False))
    marketcap_proxy_lookback = 20 if marketcap_neutralize else None
    return_candidates = int(body.get("return_candidates", 20))
    min_warmup = max(60, min(130, len(next(iter(train_panel.values())).index) // 4))
    # ---- 三路并行 (阶段6.2 并行化): 岛间并行(默认开启) + 个体并行(n_jobs) + 树内向量化(GPU) ----
    n_jobs = int(body.get("n_jobs", 1) or 1)          # 个体并行评估进程数 (1=串行; >1 多进程加速)
    if n_jobs < 1:
        n_jobs = 1
    use_gpu = body.get("use_gpu", False)              # 树内向量化: GPU 整树张量求值 (需 CUDA 可用)
    if isinstance(use_gpu, str):
        use_gpu = use_gpu.lower() in ("1", "true", "yes", "on")
    use_gpu = bool(use_gpu)
    # ---- GPU 树间多流并发数 (阶段 P2#8 同步 LLM-GP): 仅 use_gpu=True 且 CUDA 生效;
    # 1=退化为原串行, 默认 2; 非法值钳制到 1~64 (与 GP 主线同口径) ----
    gpu_streams = int(body.get("gpu_streams", 2) or 2)
    if gpu_streams < 1:
        gpu_streams = 1
    elif gpu_streams > 64:
        gpu_streams = 64
    island_parallel = body.get("island_parallel", True)  # 岛间并行: 各岛评估合并统一任务池并行
    if isinstance(island_parallel, str):
        island_parallel = island_parallel.lower() in ("1", "true", "yes", "on")
    island_parallel = bool(island_parallel)

    warm_start_formulas = _load_llm_gp_warm_formulas() if use_warm_start else []

    # ---- 多岛进化 (训练段) + 流式回调 ----
    result = run_llm_gp_evolution(
        train_panel, train_panel,
        n_islands=n_islands,
        island_pop_size=island_pop_size,
        generations=generations,
        max_depth=max_depth,
        rebal_period=rebal_period,
        min_warmup=min_warmup,
        ts_normalize_window=ts_normalize_window,
        marketcap_proxy_lookback=marketcap_proxy_lookback,
        parsimony=parsimony,
        max_length=max_length,
        tournament_size=tournament_size,
        p_crossover=p_crossover,
        p_subtree_mutation=p_subtree_mutation,
        p_hoist_mutation=p_hoist_mutation,
        p_point_mutation=p_point_mutation,
        migration_interval=migration_interval,
        migrate_count=migrate_count,
        migration_topology=migration_topology,
        inject_interval=inject_interval,
        genes_per_inject=genes_per_inject,
        max_inject_rounds=max_inject_rounds,
        gene_enabled=gene_enabled,
        space_level=space_level,
        random_state=random_state,
        warm_start_formulas=warm_start_formulas,
        corr_thresh=corr_thresh,
        filter_bare_fields=filter_bare_fields,
        llm_config=llm_cfg,
        use_gpu_tensor=use_gpu,
        gpu_streams=gpu_streams,
        n_jobs=n_jobs,
        island_parallel=island_parallel,
        gene_cb=gene_cb,
        migration_cb=migration_cb,
        progress_cb=progress_cb,
    )

    # ---- 测试段 OOS 复核 (Top-N 候选) ----
    top_exprs = [c["expr"] for c in result.get("candidates", [])[:return_candidates]]
    oos = oos_recheck(
        top_exprs, panel, panel,
        test_start, test_end,
        rebal_period=rebal_period,
        min_warmup=max(30, min(90, len(next(iter(panel.values())).index) // 6)),
        ts_normalize_window=ts_normalize_window,
        marketcap_proxy_lookback=marketcap_proxy_lookback,
    )
    oos_map = {o["expr"]: o for o in oos}
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

    return {
        "n_stocks_train": len(train_panel),
        "n_stocks_test": len(trim_panel_to_dates(panel, test_start, test_end)),
        "train_range": [str(train_start)[:10], str(train_end)[:10]],
        "test_range": [str(test_start)[:10], str(test_end)[:10]],
        "warm_start_used": len(warm_start_formulas),
        "candidates": candidates,
        "dedup_report": result.get("dedup_report"),
        "island_curves": result.get("island_curves", []),
        "evolution_curve": result.get("evolution_curve", []),
        "gene_rounds": result.get("gene_rounds", []),
        "migration_events": result.get("migration_events", []),
        "best_expr": result.get("best"),
        "best_fitness": result.get("best_fitness"),
        "n_islands": n_islands,
        "generations": generations,
        "space_level": space_level,
        "params": {
            "n_islands": n_islands,
            "island_pop_size": island_pop_size,
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
            "migration_interval": migration_interval,
            "migrate_count": migrate_count,
            "migration_topology": migration_topology,
            "inject_interval": inject_interval,
            "genes_per_inject": genes_per_inject,
            "max_inject_rounds": max_inject_rounds,
            "gene_enabled": gene_enabled,
            "space_level": space_level,
            "use_warm_start": use_warm_start,
            "corr_thresh": corr_thresh,
            "filter_bare_fields": filter_bare_fields,
            "n_jobs": n_jobs,
            "use_gpu": use_gpu,
            "island_parallel": island_parallel,
            "train_ratio": train_ratio,
            "val_ratio": val_ratio,
            "random_state": random_state,
        },
    }


@router.post("/mine_llm_gp/stream")
def mine_llm_gp_factors_stream(body: Dict[str, Any] = Body(...)):
    """LLM 增强 GP 挖掘 (SSE 流式版, 阶段6.2 独立引擎)

    事件类型: heartbeat / progress(多岛每代) / llm_gene(LLM 基因轮) / migration(岛间迁移) / done / error
    """
    q: "queue.Queue" = queue.Queue()

    def _progress_cb(stats: Dict[str, Any]) -> None:
        try:
            q.put(("progress", stats))
            from lib.factor_mining_jobs import publish
            publish("llm_gp", "progress", stats)
        except Exception:
            pass

    def _gene_cb(round_info: Dict[str, Any]) -> None:
        try:
            q.put(("llm_gene", round_info))
            from lib.factor_mining_jobs import publish
            publish("llm_gp", "gene", round_info)
        except Exception:
            pass

    def _migration_cb(ev: Dict[str, Any]) -> None:
        try:
            q.put(("migration", ev))
            from lib.factor_mining_jobs import publish
            publish("llm_gp", "migration", ev)
        except Exception:
            pass

    def _run() -> None:
        try:
            from lib.factor_mining_jobs import start_job, finish_job
            start_job("llm_gp")
            result = _run_llm_gp_pipeline(dict(body), _progress_cb, _gene_cb, _migration_cb)
            # 结果暂存后端 (eval_type=mining, eval_key=llm_gp)
            try:
                save_eval_result("mining", "llm_gp", result, {
                    "pool_type": body.get("pool_type", ""),
                    "pool_ref": body.get("pool_ref", ""),
                    "method": "llm_gp",
                    "start_date": body.get("start_date", ""),
                    "end_date": body.get("end_date", ""),
                })
            except Exception:
                pass
            finish_job("llm_gp", result)
            q.put(("done", result))
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            from lib.factor_mining_jobs import finish_job as _f
            _f("llm_gp", None, detail)
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
                yield {"event": "progress", "data": json.dumps(_json_safe(payload))}
            elif kind == "llm_gene":
                yield {"event": "llm_gene", "data": json.dumps(_json_safe(payload))}
            elif kind == "migration":
                yield {"event": "migration", "data": json.dumps(_json_safe(payload))}
            elif kind == "done":
                yield {"event": "done", "data": json.dumps(_json_safe(payload))}
                break
            elif kind == "error":
                yield {"event": "error", "data": json.dumps(payload)}
                break

    return EventSourceResponse(_event_gen())
