# -*- coding: utf-8 -*-
"""
routes/factor/multifactor.py -- 多因子分析/因子包路由
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

import pandas as pd

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


# ============================================================
# 多因子分阶段流程 (阶段B1数据准备 + 阶段B2合成评价)
# ============================================================
# 阶段B1(单因子预评价 + 技术类截面构建与预处理清洗)与合成方式无关,
# 其结果在内存中缓存; 阶段B2按任意合成方式复用缓存, 切换合成方式/调ML参数时
# 无需重跑阶段B1。

# 多因子阶段B1预处理结果的内存缓存 (切换合成方式时复用, 服务重启后需重新执行阶段B1)
_MULTI_PREP_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_MULTI_PREP_CACHE_MAX = 20


def _multi_prep_cache_key(body: Dict[str, Any]) -> str:
    """根据多因子公共输入参数生成缓存键

    阶段B1产出去合成方式无关, 仅依赖这些输入; 任一输入变化则需重新执行阶段B1。
    """
    src = {
        "factor_ids": sorted(body.get("factor_ids", [])),
        "pool_type": body.get("pool_type", ""),
        "pool_ref": body.get("pool_ref", ""),
        # 显式传入的股票代码集也纳入缓存键: 不走 pool 直接传 codes 时, 不同代码集
        # 不应命中同一缓存 (修复: 原键未含 stock_codes 存在碰撞风险)
        "stock_codes": sorted(body.get("stock_codes") or []),
        "start_date": body.get("start_date", "2024-01-01"),
        "end_date": body.get("end_date", "2025-12-31"),
        "rebal_period": body.get("rebal_period", 21),
        "neutralize": body.get("neutralize", "none"),
        # technical_ts 因子的时序标准化窗口影响B1截面(分位化口径), 需纳入缓存键
        "ts_normalize_window": int(body.get("ts_normalize_window") or 250),
    }
    raw = json.dumps(src, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


@router.post("/multi_prep")
@_json_safe_response
def multi_factor_prep(body: Dict[str, Any] = Body(...)):
    """多因子阶段B1: 数据准备 (共用固定)

    单因子预评价 + 构建并预处理技术类截面, 产出清洗诊断, 并缓存预处理数据。
    返回 prep_id, 供阶段B2(multi_synth)按任意合成方式复用, 切换合成方式无需重跑。

    body: {
        factor_ids, pool_type, pool_ref, start_date, end_date,
        rebal_period, n_layers, top_n_list, neutralize,
        ts_normalize_window (technical_ts 因子的时序标准化窗口, 默认250)
    }
    """
    factor_ids = body.get("factor_ids", [])
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2025-12-31")
    rebal_period = body.get("rebal_period", 21)
    n_layers = body.get("n_layers", 5)
    top_n_list = body.get("top_n_list", [5, 10, 20]) or [10]
    neutralize_type = body.get("neutralize", "none")

    if not factor_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个因子")

    key = _multi_prep_cache_key(body)
    if key in _MULTI_PREP_CACHE:
        _MULTI_PREP_CACHE.move_to_end(key)
        entry = _MULTI_PREP_CACHE[key]
        return {
            "prep_id": key, "cached": True,
            "single_results": entry["single_results"],
            "prep_diagnostics": entry["prep_diagnostics"],
            "technical_ids": entry["technical_ids"],
            "other_ids": entry["other_ids"],
            "signal_ids": entry.get("signal_ids", []),
            "n_stocks": entry["n_stocks"],
            "ts_normalize_window": entry.get("ts_normalize_window", 250),
            "preflight": entry.get("preflight"),
        }

    # ===== F0 预检: 每个选中因子 存在/可计算/类型 一次性静态检查 (只标记, 不阻塞) =====
    # 不可计算(文字化)/不可独立评价(none)的因子只列原因, 不参与单因子评价与合成
    preflight = preflight_factors(factor_ids)
    preflight_map = {p["factor_id"]: p for p in preflight["factors"]}
    factor_infos = {}
    for fid in factor_ids:
        factor_infos[fid] = get_factor(fid) or {}

    # 因子分类 (仅预检通过的因子进入后续流程)
    # technical_ts 因子参与多因子合成(先做时序分位标准化, 与截面因子量纲统一后合成)
    # financial 因子在 F2 起进连续合成(财报可用日 asof 对齐后量纲统一参与合成)
    # signal 因子走信号方向得分独立轨, 不进连续合成截面
    # 窗口在 panel 构建后按数据长度自适应解析 (见 _resolve_ts_window)
    ts_window_req = int(body.get("ts_normalize_window") or 250)
    technical_ids = []
    other_ids = []
    signal_ids = []
    for fid in preflight["ok_ids"]:
        ftype = classify_factor_type(factor_infos[fid])
        if ftype in ("technical", "technical_ts", "financial"):
            technical_ids.append(fid)
        else:
            other_ids.append(fid)
        if ftype == "signal":
            signal_ids.append(fid)

    # 修复: 组合含财务因子时, 调仓持有期与单因子财务评价口径对齐(>=63日≈一季度),
    # 避免季度低频因子在21日固定周期上产生重叠IC样本(自相关偏高)而误判性能;
    # 单因子财务评价已强制 rebal>=63, 多因子合成保持同口径 (12.8.5-a)。
    if any(classify_factor_type(factor_infos[f]) == "financial"
           for f in preflight["ok_ids"]):
        rebal_period = max(rebal_period, 63)

    # 构建股票池
    stock_codes = body.get("stock_codes", [])
    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"股票池构建失败: {str(e)}")
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

    # technical_ts 窗口自适应: 数据不足时自动降到可行值 (避免"无有效截面样本")
    n_days = len(panel[next(iter(panel))].index)
    ts_window = resolve_ts_window(ts_window_req, n_days, rebal_period)

    # 中性化映射 (支持市值 + 分组维度组合, 分组维度行业/板块/概念三选一)
    sector_map = concept_map = industry_map = None
    marketcap_map = None
    marketcap_proxy_lookback = None
    # 解析 neutralize: "marketcap_industry"=市值+行业, "marketcap"=仅市值, "industry"=仅行业, "none"=无
    mc_on = neutralize_type.startswith("marketcap")
    group = ""
    if neutralize_type.startswith("marketcap_"):
        group = neutralize_type[len("marketcap_"):]
    elif not mc_on:
        group = neutralize_type
    if mc_on:
        # 市值中性化改用"点-in-time 成交额代理"(近20日均额, 无前视)
        marketcap_proxy_lookback = 20
    if group == "sector":
        try:
            from lib.stock_classify import load_sector_map
            sector_map = load_sector_map(list(panel.keys()))
        except Exception:
            pass
    elif group == "concept":
        try:
            from lib.stock_classify import load_concept_map
            concept_map = load_concept_map(list(panel.keys()))
        except Exception:
            pass
    elif group == "industry":
        try:
            from lib.stock_classify import load_industry_map
            industry_map = load_industry_map(list(panel.keys()))
        except Exception:
            pass

    # ===== 阶段A: 单因子预评价 (每个选中因子按类型; 预检不通过者仅列原因) =====
    single_results = []
    for fid in factor_ids:
        pf = preflight_map.get(fid, {})
        if pf.get("status") in ("skip", "error"):
            # 不可计算/不可独立评价因子: 不评价, 仅显式列出原因 (不静默吞错)
            single_results.append({
                "factor_id": fid,
                "name": factor_infos[fid].get("name", fid),
                "factor_type": classify_factor_type(factor_infos[fid]),
                "status": pf.get("status"),
                "reason": pf.get("reason", ""),
            })
            continue
        try:
            fv = calc_factor(fid, panel)
        except Exception as e:
            single_results.append({
                "factor_id": fid, "name": factor_infos[fid].get("name", fid),
                "factor_type": classify_factor_type(factor_infos[fid]),
                "error": str(e),
            })
            continue
        info = factor_infos[fid]
        ftype = classify_factor_type(info)
        first_code = next(iter(panel))
        n = len(panel[first_code].index)
        flat = fv.values.flatten()
        flat = flat[~pd.isna(flat)]
        data_stats = {
            "count": int(len(flat)),
            "nan_ratio": round(float(fv.isna().mean().mean()), 4),
            "mean": round(float(fv.mean().mean()), 4),
        }
        if ftype == "signal":
            pr = evaluate_pattern_factor(
                fv, panel, rebal_period=rebal_period,
                direction=direction_to_int(info.get("direction")))
            single_results.append({
                "factor_id": fid, "name": info.get("name", fid),
                "factor_type": ftype, "data_stats": data_stats,
                "pattern_evaluation": pr,
            })
        elif ftype == "technical_ts":
            # 时序标准化截面评价: 先对自身近N日历史做滚动分位, 再走截面IC/分层管线
            icr = run_ic_timeseries_panel(
                ts_rank_normalize(fv, ts_window), panel,
                rebal_period=rebal_period, min_warmup=max(130, ts_window),
                sector_map=sector_map, concept_map=concept_map, industry_map=industry_map,
                marketcap_map=marketcap_map,
                marketcap_proxy_lookback=marketcap_proxy_lookback,
            )
            single_results.append({
                "factor_id": fid, "name": info.get("name", fid),
                "factor_type": ftype, "data_stats": data_stats,
                "ic_result": icr,
                "ts_normalize_window": ts_window,
            })
        elif ftype == "financial":
            reb = financial_report_rebal_dates(fv, panel, rebal_period=max(rebal_period, 63), min_warmup=0)
            icr = run_ic_timeseries_panel(
                fv, panel, rebal_period=max(rebal_period, 63), min_warmup=130,
                sector_map=sector_map, concept_map=concept_map, industry_map=industry_map,
                marketcap_map=marketcap_map,
                rebal_dates=reb,
                marketcap_proxy_lookback=marketcap_proxy_lookback,
            )
            # 财务因子质量: 中位数填充占比 = asof+ffill 后缺失占比 (合成/预处理会用截面中位数填充)
            _fq = None
            try:
                _miss = float(fv.isna().mean().mean())
                _fq = {
                    "fill_ratio": round(_miss, 4),
                    "non_null_ratio": round(1 - _miss, 4),
                    "n_report_dates": len(reb or []),
                }
            except Exception:
                _fq = None
            single_results.append({
                "factor_id": fid, "name": info.get("name", fid),
                "factor_type": ftype, "data_stats": data_stats,
                "ic_result": icr,
                "financial_quality": _fq,
            })
        else:
            icr = run_ic_timeseries_panel(
                fv, panel, rebal_period=rebal_period, min_warmup=130,
                sector_map=sector_map, concept_map=concept_map, industry_map=industry_map,
                marketcap_map=marketcap_map,
                marketcap_proxy_lookback=marketcap_proxy_lookback,
            )
            single_results.append({
                "factor_id": fid, "name": info.get("name", fid),
                "factor_type": ftype, "data_stats": data_stats,
                "ic_result": icr,
            })

    # ===== 阶段B1: 连续因子截面构建 + 预处理清洗 =====
    # technical_ts 因子先做时序分位标准化(与截面因子量纲统一)再入截面
    # financial 因子财报可用日 asof 对齐后逐日前向填充, 直接入截面 (F2)
    has_ts_factor = any(
        classify_factor_type(factor_infos[f]) == "technical_ts" for f in technical_ids)
    factor_panels = {}
    calc_errors = []
    for fid in technical_ids:
        try:
            fv = calc_factor(fid, panel)
            if fv is not None and not fv.empty:
                if classify_factor_type(factor_infos[fid]) == "technical_ts":
                    fv = ts_rank_normalize(fv, ts_window)
                factor_panels[fid] = fv
        except Exception as e:
            calc_errors.append(f"{fid}: {e}")

    # ===== F2 信号方向得分独立轨: 信号因子 -> 每股综合方向得分面板 =====
    # 信号因子是离散稀疏(0/1 或 -1/0/+1), 不能直接进连续合成截面;
    # 按方向语义转成方向得分, 多因子取平均成综合得分, 再与连续合成汇总。
    signal_score_info = {"score_panel": None, "per_factor": {}, "signal_ids": []}
    if signal_ids:
        signal_panels = {}
        for fid in signal_ids:
            try:
                fv = calc_factor(fid, panel)
                if fv is not None and not fv.empty:
                    signal_panels[fid] = fv
            except Exception:
                pass
        signal_score_info = build_signal_direction_score_panel(signal_panels, factor_infos)

    # 连续合成截面: 连续因子不足2个时, 若存在信号因子则回退"信号组合轨"
    # (把综合信号方向得分当作单一连续因子入截面, 走同一条合成/评价管线, 只选信号也能分析)
    prep = {"error": "无有效连续因子"}
    if len(factor_panels) >= 2:
        prep = prep_multi_factor(
            factor_panels, panel, rebal_period=rebal_period,
            min_warmup=max(130, ts_window) if has_ts_factor else 130,
            sector_map=sector_map, concept_map=concept_map,
            industry_map=industry_map, marketcap_map=marketcap_map,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
        )
    elif factor_panels:
        prep = {"error": "连续因子不足2个, 无法多因子合成 (所选因子将仅做单因子评价)"}
    elif signal_score_info["score_panel"] is not None:
        # 仅选信号因子: 信号组合轨 (综合方向得分当单一连续因子)
        prep = prep_multi_factor(
            {"__signal_combo__": signal_score_info["score_panel"]}, panel,
            rebal_period=rebal_period, min_warmup=130, min_factors=1,
            sector_map=sector_map, concept_map=concept_map,
            industry_map=industry_map, marketcap_map=marketcap_map,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
        )
        if "error" not in prep:
            prep["signal_only"] = True

    if "error" in prep:
        return {
            "prep_id": key, "cached": False,
            "single_results": single_results,
            "prep_diagnostics": None,
            "technical_ids": technical_ids,
            "other_ids": other_ids,
            "n_stocks": len(panel),
            "prep_error": prep["error"],
            "preflight": preflight,
        }

    # 缓存阶段B1结果 (供阶段B2复用)
    direction_map = {}
    for fid in factor_panels:
        direction_map[fid] = direction_to_int(factor_infos[fid].get("direction"))
    entry = {
        "single_results": single_results,
        "prep_diagnostics": prep["prep_diagnostics"],
        "prep": prep,
        "factor_panels": factor_panels,
        "prices_panel": panel,  # F1 组合风险分析: 构建 Barra 风格面板用
        "signal_score_info": signal_score_info,  # F2 信号方向得分独立轨
        "technical_ids": technical_ids,
        "other_ids": other_ids,
        "signal_ids": signal_ids,
        "direction_map": direction_map,
        "factor_infos": factor_infos,
        "preflight": preflight,
        "n_stocks": len(panel),
        "pool_type": pool_type or "active",
        "pool_ref": pool_ref,
        "start_date": start_date,
        "end_date": end_date,
        "rebal_period": rebal_period,
        "n_layers": n_layers,
        "top_n_list": top_n_list,
        "neutralize_type": neutralize_type,
        "ts_normalize_window": ts_window,
    }
    _MULTI_PREP_CACHE[key] = entry
    _MULTI_PREP_CACHE.move_to_end(key)
    while len(_MULTI_PREP_CACHE) > _MULTI_PREP_CACHE_MAX:
        _MULTI_PREP_CACHE.popitem(last=False)

    return {
        "prep_id": key, "cached": False,
        "single_results": single_results,
        "prep_diagnostics": prep["prep_diagnostics"],
        "technical_ids": technical_ids,
        "other_ids": other_ids,
        "signal_ids": signal_ids,
        "n_stocks": len(panel),
        "ts_normalize_window": ts_window,
        "preflight": preflight,
        "signal_only": bool(prep.get("signal_only")),
    }


@router.post("/multi_synth")
@_json_safe_response
def multi_factor_synth(body: Dict[str, Any] = Body(...)):
    """多因子阶段B2: 基于阶段B1缓存做指定合成方式的合成 + 组合评价

    切换合成方式 / 调整ML参数时, 复用阶段B1(prep)缓存, 无需重跑数据准备。

    body: {
        prep_id: "..." (multi_prep 返回),
        method: "equal"/"ic_weighted"/"rank_score"/"lasso"/"ml_reg"/"ml_cls"
                /"markowitz"/"optuna"/"sharpe"/"pca",
        ic_lookback, n_layers, top_n_list,
        ml_params: {model_type, learning_rate, n_estimators, max_depth,
                    subsample, colsample_bytree, reg_alpha, reg_lambda},
        synth_cfg: {
            screening: {enable, ic_thresh, min_non_null, min_rebal_coverage},
            redundancy: {enable, corr_thresh},
            direction: {auto},
            pca: {n_components, explained_var},
            optuna: {n_trials},
            ml: {importance_feedback, min_importance, purged_cv, n_splits, gap}
        }
    }
    """
    prep_id = body.get("prep_id", "")
    method = body.get("method", "equal")
    ic_lookback = body.get("ic_lookback", 5)
    n_layers = body.get("n_layers", 5)
    top_n_list = body.get("top_n_list", [5, 10, 20]) or [10]
    ml_params = body.get("ml_params") or {}
    synth_cfg = body.get("synth_cfg") or {}

    if prep_id not in _MULTI_PREP_CACHE:
        raise HTTPException(status_code=400, detail="阶段B1预处理缓存已失效, 请先重新执行数据准备")
    entry = _MULTI_PREP_CACHE[prep_id]
    _MULTI_PREP_CACHE.move_to_end(prep_id)

    # ===== F0 自动匹配: 方法×因子类型 可用性判定 + 不兼容因子自动排除 + 降级建议 =====
    # 依据 METHOD_FACTOR_COMPAT: 连续轨因子不满足方法 accepts 时移出合成(保留单因子评价);
    # requires_cov 但连续因子不足时降级等权并警告; 均不抛错, 保证"任意因子点击不崩溃"。
    signal_only = bool(entry["prep"].get("signal_only"))
    auto_match = auto_match_factors(method, list(entry["technical_ids"]),
                                    entry.get("factor_infos") or {})
    if signal_only:
        # 仅信号因子: 综合信号方向得分作为合成因子走同一条管线, 直接放行 (〇·九 信号轨兜底)
        auto_match = {**auto_match, "usable": True, "synthesis_ids": [],
                      "excluded": [],
                      "warning": "仅信号因子模式: 综合信号方向得分作为单一合成因子评价"}
    if "error" in entry["prep"]:
        # 阶段B1本身无有效截面(如技术类连续因子不足): 明确告知, 不执行合成
        return {
            "factor_ids": [*entry["technical_ids"], *entry["other_ids"]],
            "technical_ids": entry["technical_ids"],
            "other_ids": entry["other_ids"],
            "single_results": entry["single_results"],
            "multi_result": {"error": entry["prep"]["error"]},
            "n_stocks": entry["n_stocks"],
            "pool_type": entry["pool_type"],
            "auto_match": auto_match,
        }
    if not auto_match["usable"]:
        # 致命级: 无有效连续因子可合成 (5.3 错误分级) —— 返回明确信息而非崩溃
        return {
            "factor_ids": [*entry["technical_ids"], *entry["other_ids"]],
            "technical_ids": entry["technical_ids"],
            "other_ids": entry["other_ids"],
            "single_results": entry["single_results"],
            "multi_result": {"error": auto_match["warning"] or "无有效连续因子可合成"},
            "n_stocks": entry["n_stocks"],
            "pool_type": entry["pool_type"],
            "auto_match": auto_match,
        }

    # 兼容性自动匹配后, 实际参与合成的因子 (排除被移出的不兼容因子)
    synth_method = auto_match["degraded_method"] or method
    synthesis_ids = auto_match["synthesis_ids"]
    if auto_match["excluded"]:
        # 被排除因子从预处理截面中剔除后, 其余因子正常合成 (优雅降级)
        prep = dict(entry["prep"])
        keep = set(synthesis_ids)
        prep["preprocessed_crosses"] = {
            t: pre[[c for c in pre.columns if c in keep]]
            for t, pre in entry["prep"]["preprocessed_crosses"].items()
        }
    else:
        prep = entry["prep"]

    # F1: 构建 Barra 风格暴露面板 (通用风险标尺, 不依赖用户是否选中 Barra 因子)
    barra_style_panels = None
    try:
        if "prices_panel" in entry and entry["prices_panel"]:
            barra_style_panels = build_barra_style_panels(entry["prices_panel"])
    except Exception:
        pass  # 构建失败仅跳过风险分析, 不影响主评价
    # 组合中性化开关从 synth_cfg 读取 (默认关)
    neutralize_port = bool((synth_cfg or {}).get("neutralize_port", False))
    # F2: 信号方向得分独立轨 (信号因子 -> 每股综合方向得分, 最后与连续合成汇总)
    signal_score_info = entry.get("signal_score_info") or {}
    signal_score_panel = signal_score_info.get("score_panel")
    signal_meta = signal_score_info.get("per_factor") or {}

    multi_result = synth_multi_factor_eval(
        prep, method=synth_method, ic_lookback=ic_lookback,
        n_layers=n_layers, top_n_list=top_n_list,
        direction_map=entry["direction_map"], ml_params=ml_params, cost=0.002,
        synth_cfg=synth_cfg,
        barra_style_panels=barra_style_panels,
        neutralize_port=neutralize_port,
        signal_score_panel=signal_score_panel,
        signal_meta=signal_meta,
    )

    result = {
        "factor_ids": [*entry["technical_ids"], *entry["other_ids"]],
        "technical_ids": entry["technical_ids"],
        "other_ids": entry["other_ids"],
        "single_results": entry["single_results"],
        "multi_result": multi_result,
        "n_stocks": entry["n_stocks"],
        "pool_type": entry["pool_type"],
        "auto_match": auto_match,
        "preflight": entry.get("preflight"),
    }
    # 持久化前先清洗 inf/-inf/NaN (PostgreSQL JSONB 同样不接受非有限浮点)
    result = _json_safe(result)
    # 持久化多因子评价完整结果 (供前端切页后恢复)
    try:
        multi_eval_key = ",".join(sorted(result["factor_ids"]))
        # 修复: 按组合构成生成 evaluation_type, 不再写死 technical。
        #   单类型组合(全 technical/全 signal/全 financial 等)记该类型;
        #   混合类型组合记 "multi_<type1>+<type2>..." 复合标签, 便于按管线维度查询。
        _fis = entry.get("factor_infos") or {}
        _types = set()
        for _fid in result["factor_ids"]:
            _t = classify_factor_type(_fis.get(_fid) or {})
            if _t and _t != "none":
                _types.add(_t)
        _eval_type = (_types.pop() if len(_types) == 1
                      else "multi_" + "+".join(sorted(_types)) if _types else "technical")
        save_eval_result("multi", multi_eval_key, result, {
            "pool_type": entry["pool_type"], "pool_ref": entry["pool_ref"],
            "start_date": entry["start_date"], "end_date": entry["end_date"],
            "method": method, "rebal_period": entry["rebal_period"],
            "n_layers": n_layers, "neutralize": entry["neutralize_type"],
            "evaluation_type": _eval_type,
        })
    except Exception:
        pass  # 持久化失败不影响本次评价返回

    return result


# ============================================================
# 历史评价结果查询 (供前端切页后恢复)
# ============================================================

@router.post("/package")
def save_package(body: Dict[str, Any] = Body(...)):
    """保存因子包 (配置 + 状态快照 + ML模型路径)

    body: {
        package_id: str (可选, 缺省自动生成),
        name: str (必填, 因子包名称),
        factor_ids: [str],
        method: str,
        synth_cfg: dict, ml_params: dict,
        pool_type, pool_ref, start_date, end_date,
        rebal_period, n_layers, top_n_list, neutralize,
        weights: dict, direction: dict, ml_model_path: str, pca_model_path: str,
        result_snapshot: dict (可选),
    }
    返回: {package_id, name}
    """
    import uuid
    package_id = body.get("package_id") or f"pkg_{uuid.uuid4().hex[:12]}"
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写因子包名称")

    factor_ids = body.get("factor_ids") or []
    method = body.get("method") or "equal"
    synth_cfg = body.get("synth_cfg") or {}
    ml_params = body.get("ml_params") or {}
    weights = body.get("weights")
    direction = body.get("direction")
    ml_model_path = body.get("ml_model_path")
    pca_model_path = body.get("pca_model_path")

    # 若提供 prep_id 且缓存有效, 用全历史数据计算最终使用参数 (仅在保存因子包时计算,
    # 避免每次合成评价都重训全量模型/拟合PCA; 评价用滚动, 保存用全历史)。
    prep_id = body.get("prep_id")
    ts_window_pkg = None
    if prep_id and prep_id in _MULTI_PREP_CACHE:
        entry = _MULTI_PREP_CACHE[prep_id]
        # 训练端实际使用的时序标准化窗口(含自适应降窗)一并存入包, 供消费端同口径复现
        ts_window_pkg = entry.get("ts_normalize_window")
        try:
            from lib.factor_engine import build_final_use_from_prep, _normalize_synth_cfg
            cfg = _normalize_synth_cfg(synth_cfg)
            auto_dir = cfg["direction"].get("auto", True)
            fu = build_final_use_from_prep(
                entry["prep"], method, factor_ids, entry["direction_map"],
                auto_dir, cfg, ml_params,
            )
            factor_ids = fu.get("final_factor_ids") or factor_ids
            weights = fu.get("final_weights")
            direction = fu.get("final_direction")
            ml_model_path = fu.get("ml_model_path")
            pca_model_path = fu.get("pca_model_path")
        except Exception:
            pass  # 计算失败则回退使用前端传入的字段
        # F2 仅信号因子: 合成因子 "__signal_combo__" 映射回真实信号因子ID
        if "__signal_combo__" in factor_ids:
            sig_ids = entry.get("signal_ids") or []
            factor_ids = [f for f in factor_ids if f != "__signal_combo__"] + sig_ids
    # 无缓存时回退前端传入的窗口 (与多因子分析页 ts_normalize_window 输入一致)
    if not ts_window_pkg:
        ts_window_pkg = body.get("ts_normalize_window") or 250

    pkg = {
        "package_id": package_id,
        "name": name,
        "factor_ids": factor_ids,
        "method": method,
        "synth_cfg": synth_cfg,
        "ml_params": ml_params,
        "pool_type": body.get("pool_type"),
        "pool_ref": body.get("pool_ref"),
        "start_date": body.get("start_date"),
        "end_date": body.get("end_date"),
        "rebal_period": body.get("rebal_period"),
        "n_layers": body.get("n_layers"),
        "top_n_list": body.get("top_n_list"),
        "neutralize": body.get("neutralize"),
        "ts_normalize_window": ts_window_pkg,
        "weights": weights,
        "direction": direction,
        "ml_model_path": ml_model_path,
        "pca_model_path": pca_model_path,
        "result_snapshot": body.get("result_snapshot"),
        "portfolio_risk_snapshot": body.get("portfolio_risk_snapshot"),  # F3 组合风险快照
    }
    # F3 一致性校验: 因子包内因子与合成方法自动匹配, 保存时即给出兼容性提示 (不阻塞保存)
    try:
        infos = {fid: (get_factor(fid) or {}) for fid in factor_ids}
        cm = auto_match_factors(method, factor_ids, infos)
        pkg["consistency_check"] = {
            "method": method,
            "usable": bool(cm["usable"]),
            "excluded": cm.get("excluded") or [],
            "warning": cm.get("warning"),
        }
    except Exception:
        pkg["consistency_check"] = {"method": method, "usable": True,
                                    "excluded": [], "warning": None}
    try:
        saved_id = save_factor_package(pkg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存因子包失败: {str(e)}")
    return {"package_id": saved_id, "name": name, "consistency_check": pkg["consistency_check"]}


@router.get("/packages")
def list_packages():
    """列出所有因子包"""
    try:
        return {"packages": list_factor_packages()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询因子包失败: {str(e)}")


@router.get("/package/{package_id}")
def get_package(package_id: str):
    """加载单个因子包 (附 F3 因子×方法一致性校验, 不阻塞加载)"""
    pkg = get_factor_package(package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="因子包不存在")
    try:
        factor_ids = pkg.get("factor_ids") or []
        infos = {fid: (get_factor(fid) or {}) for fid in factor_ids}
        cm = auto_match_factors(pkg.get("method") or "equal", factor_ids, infos)
        pkg["consistency_check"] = {
            "method": pkg.get("method"),
            "usable": bool(cm["usable"]),
            "excluded": cm.get("excluded") or [],
            "warning": cm.get("warning"),
        }
    except Exception:
        pkg["consistency_check"] = {"method": pkg.get("method"), "usable": True,
                                    "excluded": [], "warning": None}
    return pkg


@router.delete("/package/{package_id}")
def remove_package(package_id: str):
    """删除因子包"""
    ok = delete_factor_package(package_id)
    if not ok:
        raise HTTPException(status_code=404, detail="因子包不存在")
    return {"deleted": True, "package_id": package_id}

