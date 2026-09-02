# -*- coding: utf-8 -*-
# QuantGP 页面路由: 完全复刻 QuantGplearn 原版 GP 因子挖掘 (独立基线, 零扩充)
"""
GET  /api/factor/quantgp/fields        -- 可喂入的行情字段列表
POST /api/factor/quantgp/mine/stream   -- 运行原版 QuantGplearn 挖掘 (SSE: progress/done/error)
POST /api/factor/quantgp/import        -- 把候选因子翻译+校验+入库 factor_library
POST /api/factor/quantgp/evaluate/stream -- 候选因子批量单因子评价 (SSE: progress/done/error)

设计:
  - 算法层完全使用 third_party/QuantGplearn 原版 GpuSymbolicTransformer, 零改动;
  - 只做两层适配: 数据接入(本系统面板->原版 long-panel) + 结果解析(原版产出->本系统公式/入库);
  - A 档增强 (分段/OOS/Permutation/中性化/TS分位/去冗余) 在外部适配层实现 (mine_quantgp 外层),
    不改第三方源码, 默认关闭不扰乱原版; Walk-forward 与验证段已移除。
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

import json
import math
import queue
import threading
import time

from fastapi import APIRouter, Body, HTTPException
from sse_starlette.sse import EventSourceResponse

from lib.paths import setup_sys_path
setup_sys_path()

from lib.backtest_data import load_daily_kline
from lib.quant_gp import (
    DEFAULT_FEATURES, mine_quantgp, quant_gp_expr_to_formula,
    import_quantgp_candidates, _translate_expr,
)

# Stage 4: 原独立 routes/quant_gp.py 并入因子挖掘子路由包。
# 保留原 /api/factor/quantgp/* API 前缀 (纳入 factor 路由 /api/factor 后由本 prefix 补全)。
router = APIRouter(prefix="/quantgp")


def _json_safe(obj: Any) -> Any:
    """递归清洗 inf/-inf/NaN -> None (Starlette JSONResponse 不允许非有限浮点)"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _load_panel(stock_codes: List[str], start_date: str, end_date: str,
                n: int = 80) -> Dict[str, Any]:
    """加载本系统行情面板 {code: DataFrame}"""
    panel = {}
    for code in stock_codes[:n]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > 60:
                panel[code] = df
        except Exception:
            pass
    if len(panel) < 10:
        raise HTTPException(status_code=400,
                            detail=f"有效股票数据不足10只 (当前 {len(panel)} 只)")
    return panel


@router.get("/fields")
def quantgp_fields():
    """可喂入的行情字段列表 (与 DEFAULT_FEATURES 一致)"""
    return {"fields": DEFAULT_FEATURES}


@router.post("/mine/stream")
def quantgp_mine_stream(body: Dict[str, Any] = Body(...)):
    """运行原版 QuantGplearn 挖掘 (SSE 流式)

    body:
      stock_codes / pool_type / pool_ref / start_date / end_date
      rebal_period
      # 透传原版参数 (默认值交给原版):
      population_size / hall_of_fame / n_components / generations /
      tournament_size / init_depth / init_method / objective /
      const_range / parsimony_coefficient / p_crossover / p_subtree_mutation /
      p_hoist_mutation / p_point_mutation / p_point_replace /
      max_samples / max_length / tolerable_corr / device / random_state
      # C 档原版内置能力 (默认对齐原版):
      stopping_criteria / transformer / normalize / warm_start /
      low_memory / cache_scores / cache_factors
      # A 档外部适配层增强 (默认关闭, 不扰乱原版):
      train_ratio / enable_oos / enable_perm / n_perm / enable_target_ortho / n_rounds
      enable_final_screen / final_ic_threshold / final_corr_threshold /
      final_min_factors_fallback / final_max_factors_in_pool
      enable_fdr / fdr_n_trials / fdr_n_subsample / fdr_cv_folds / fdr_decay_horizons

    事件: progress(每代) / done(结果+翻译后候选+A档报告) / error
    """
    q: "queue.Queue" = queue.Queue()

    def _run() -> None:
        try:
            stock_codes = list(body.get("stock_codes") or [])
            start_date = body.get("start_date", "2023-01-01")
            end_date = body.get("end_date", "2025-12-31")
            rebal_period = int(body.get("rebal_period", 5) or 5)
            pool_type = body.get("pool_type", "")
            pool_ref = body.get("pool_ref", "")

            if pool_type:
                from lib.factor_evaluator import get_pool_stocks
                try:
                    pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=120)
                    if pool_codes:
                        stock_codes = pool_codes
                except Exception:
                    pass
            if not stock_codes or len(stock_codes) < 10:
                from lib.factor_evaluator import get_active_stock_pool
                stock_codes = get_active_stock_pool(n=80, min_days=120)

            panel = _load_panel(stock_codes, start_date, end_date)
            feature_names = list(body.get("feature_names") or DEFAULT_FEATURES)

            # 原版参数透传 (None 忽略)
            qg_params = {
                "population_size": body.get("population_size"),
                "hall_of_fame": body.get("hall_of_fame"),
                "n_components": body.get("n_components"),
                "generations": body.get("generations"),
                "tournament_size": body.get("tournament_size"),
                "init_depth": _parse_init_depth(body.get("init_depth")),
                "init_method": body.get("init_method"),
                "objective": body.get("objective"),
                "const_range": _parse_const_range(body.get("const_range")),
                "parsimony_coefficient": body.get("parsimony_coefficient"),
                "p_crossover": body.get("p_crossover"),
                "p_subtree_mutation": body.get("p_subtree_mutation"),
                "p_hoist_mutation": body.get("p_hoist_mutation"),
                "p_point_mutation": body.get("p_point_mutation"),
                "p_point_replace": body.get("p_point_replace"),
                "max_samples": body.get("max_samples"),
                "max_length": body.get("max_length"),
                "tolerable_corr": body.get("tolerable_corr"),
                "device": body.get("device") or ("cuda" if _cuda_available() else "cpu"),
                "random_state": body.get("random_state", 42),
                # C 档: 原版内置能力透传 (默认值对齐原版, 空值忽略)
                # 注: warm_start(续训) 需同一模型实例多次 fit, 页面每次新建实例不生效, 故不透传
                "stopping_criteria": body.get("stopping_criteria"),
                "transformer": body.get("transformer") or None,
                "normalize": body.get("normalize"),
                "low_memory": body.get("low_memory"),
                "cache_scores": body.get("cache_scores"),
                "cache_factors": body.get("cache_factors"),
            }
            # 原版对象参数整理
            qg_params = {k: v for k, v in qg_params.items() if v is not None}

            # A 档外部适配层参数 (默认关闭; 数据分段/复核/target 正交化在 mine_quantgp 外层实现)
            a_params = {
                "train_ratio": body.get("train_ratio", 1.0),
                "enable_oos": body.get("enable_oos", False),
                "enable_perm": body.get("enable_perm", False),
                "n_perm": body.get("n_perm", 1000),
                "enable_target_ortho": body.get("enable_target_ortho", False),
                "n_rounds": body.get("n_rounds", 1),
                "enable_final_screen": body.get("enable_final_screen", False),
                "final_ic_threshold": body.get("final_ic_threshold", 0.03),
                "final_corr_threshold": body.get("final_corr_threshold", 0.9),
                "final_min_factors_fallback": body.get("final_min_factors_fallback", 8),
                "final_max_factors_in_pool": body.get("final_max_factors_in_pool", 15),
                # 假发现门闸 (QuantAlpha False Discovery Gauntlet, 默认关闭)
                "enable_fdr": body.get("enable_fdr", False),
                "fdr_n_trials": body.get("fdr_n_trials", 96),
                "fdr_n_subsample": body.get("fdr_n_subsample", 20),
                "fdr_cv_folds": body.get("fdr_cv_folds", 3),
                "fdr_decay_horizons": body.get("fdr_decay_horizons"),
            }

            result = mine_quantgp(
                panel, feature_names=feature_names, rebal_period=rebal_period,
                progress_cb=lambda p: q.put(("progress", p)), **qg_params, **a_params)

            # 翻译候选 -> 本系统公式
            translated = []
            for c in result.get("candidates", []):
                f = quant_gp_expr_to_formula(c.get("qg_expr", ""), feature_names)
                translated.append({
                    "qg_expr": c.get("qg_expr"),
                    "formula": f,
                    "score": c.get("score"),
                })

            q.put(("done", {
                "candidates": _json_safe(translated),
                "run_details": _json_safe(result.get("run_details", {})),
                "segments": _json_safe(result.get("segments")),
                "oos_report": _json_safe(result.get("oos_report", [])),
                "perm_report": _json_safe(result.get("perm_report", [])),
                "ortho_info": _json_safe(result.get("ortho_info")),
                "final_screen_report": _json_safe(result.get("final_screen_report")),
                "fdr_report": _json_safe(result.get("fdr_report")),
                "n_stocks": len(panel),
                "generations": body.get("generations"),
                "feature_names": feature_names,
            }))
        except Exception as e:
            q.put(("error", {"error": str(e)}))

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
            elif kind == "done":
                yield {"event": "done", "data": json.dumps(_json_safe(payload))}
                break
            elif kind == "error":
                yield {"event": "error", "data": json.dumps(payload)}
                break

    return EventSourceResponse(_event_gen())


@router.post("/import")
def quantgp_import(body: Dict[str, Any] = Body(...)):
    """把候选因子翻译+校验+入库 factor_library

    body: {
      candidates: [{qg_expr, score}],
      start_date / end_date,
      feature_names?: [...]
    }
    返回 {imported: [...], skipped: [...]}
    """
    candidates = list(body.get("candidates") or [])
    if not candidates:
        raise HTTPException(status_code=400, detail="无候选因子")
    start_date = body.get("start_date", "2023-01-01")
    end_date = body.get("end_date", "2025-12-31")
    feature_names = list(body.get("feature_names") or DEFAULT_FEATURES)

    from lib.factor_evaluator import get_active_stock_pool
    try:
        stock_codes = get_active_stock_pool(n=30, min_days=120)
    except Exception:
        stock_codes = []
    panel = _load_panel(stock_codes or get_active_stock_pool(n=30, min_days=120),
                        start_date, end_date, n=30)

    result = import_quantgp_candidates(
        candidates, panel, feature_names, name_prefix="qgp")
    return _json_safe(result)


@router.post("/evaluate/stream")
def quantgp_evaluate_stream(body: Dict[str, Any] = Body(...)):
    """对候选因子批量跑单因子评价 (SSE 流式, 逐因子返回)

    与单因子评价页一致的口径: IC时序 + 分层回测 + 分位收益 + 清华PerformanceWithCost。
    一次性加载行情面板供全部候选共享, 逐因子计算并评价 (技术/时序标准化按公式类型路由)。

    body: {
      candidates:   [{qg_expr, formula?, score?}],   # formula 缺失时后端重新翻译
      pool_type / pool_ref / stock_codes,             # 股票池 (与挖掘一致, 默认活跃股)
      start_date / end_date / rebal_period / feature_names / n_layers
    }
    事件:
      progress: {index, total, candidate}    # 每个候选因子评价完成即推送
      done:     {n_stocks}                   # 全部完成
      error:    {error}
    candidate: {qg_expr, formula, score,
                ok, reason?,                              # ok=False 时给出跳过原因
                factor_type, direction, ts_normalize_window,
                ic_timeseries, layered_backtest, quantile_backtest,
                performance_with_cost, effectiveness_grade}
    """
    q: "queue.Queue" = queue.Queue()

    def _run() -> None:
        try:
            candidates = list(body.get("candidates") or [])
            if not candidates:
                raise ValueError("无候选因子")
            start_date = body.get("start_date", "2023-01-01")
            end_date = body.get("end_date", "2025-12-31")
            rebal_period = int(body.get("rebal_period", 5) or 5)
            n_layers = int(body.get("n_layers", 5) or 5)
            feature_names = list(body.get("feature_names") or DEFAULT_FEATURES)
            pool_type = body.get("pool_type", "")
            pool_ref = body.get("pool_ref", "")
            stock_codes = list(body.get("stock_codes") or [])

            # 股票池 (与挖掘一致: 指定池优先, 否则活跃股)
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
                try:
                    auto = get_active_stock_pool(n=80, min_days=200)
                    seen = set(stock_codes)
                    for c in auto:
                        if c not in seen:
                            stock_codes.append(c)
                            seen.add(c)
                except Exception:
                    pass

            panel = _load_panel(stock_codes, start_date, end_date, n=80)
            if len(panel) < 10:
                raise ValueError(f"有效股票数据不足10只 (当前 {len(panel)} 只)")

            from lib.factor_engine import (
                evaluate_expression, analyze_expression_tags, validate_expression,
                ts_rank_normalize, resolve_ts_window, build_total_return_panel,
                run_ic_timeseries_panel, PerformanceWithCost, GetQuantileRet,
            )

            n_days = len(next(iter(panel.values())).index)
            total_ret_panel = build_total_return_panel(panel)

            for idx, cand in enumerate(candidates):
                qg_expr = cand.get("qg_expr") or ""
                formula = cand.get("formula") or quant_gp_expr_to_formula(qg_expr, feature_names)
                score = cand.get("score")
                res = {"qg_expr": qg_expr, "formula": formula, "score": score}
                try:
                    if not formula:
                        res.update({"ok": False, "reason": "翻译失败或语法校验不过"})
                        q.put(("progress", {"index": idx, "total": len(candidates), "candidate": res}))
                        continue
                    ok, msg = validate_expression(formula)
                    if not ok:
                        res.update({"ok": False, "reason": f"语法校验不过: {msg}"})
                        q.put(("progress", {"index": idx, "total": len(candidates), "candidate": res}))
                        continue
                    fv = evaluate_expression(formula, panel)
                    if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
                        res.update({"ok": False, "reason": "因子计算为空"})
                        q.put(("progress", {"index": idx, "total": len(candidates), "candidate": res}))
                        continue
                    nn = float(fv.notna().mean().mean())
                    if nn < 0.2:
                        res.update({"ok": False, "reason": f"非空率过低 ({nn:.3f})"})
                        q.put(("progress", {"index": idx, "total": len(candidates), "candidate": res}))
                        continue

                    # 评价方式路由 (与单因子评价页一致): technical_ts 先自身历史滚动分位标准化
                    tags = analyze_expression_tags(formula)
                    factor_type = tags.get("factor_type") or "technical"
                    fv_for_eval = fv
                    eff_warmup = 130
                    ts_norm_window = None
                    if factor_type == "technical_ts":
                        ts_norm_window = resolve_ts_window(None, n_days, rebal_period)
                        fv_for_eval = ts_rank_normalize(fv, ts_norm_window)
                        eff_warmup = max(130, ts_norm_window)

                    ic_result = run_ic_timeseries_panel(
                        fv_for_eval, panel, rebal_period=rebal_period,
                        min_warmup=eff_warmup, n_layers=n_layers)

                    layered = ic_result.get("layered") or {}
                    layer_result = {
                        "layer_returns": layered.get("layer_returns") or {},
                        "long_short": layered.get("long_short"),
                        "layer_cumret": layered.get("layer_cumret") or {},
                        "long_short_cumret": layered.get("long_short_cumret") or [],
                    }

                    pwc_result = None
                    quantile_result = None
                    if not total_ret_panel.empty and not fv_for_eval.empty:
                        pwc_result = PerformanceWithCost(
                            fv_for_eval, total_ret_panel,
                            delayNum=2, cost=0.002, SDate=0, EDate=-1)
                        quantile_result = GetQuantileRet(
                            fv_for_eval, total_ret_panel,
                            Q=n_layers, delayNum=2, cost=0.0, SDate=0, EDate=-1)

                    # 有效性评级 (与 /evaluate 一致口径)
                    ic_mean = abs(ic_result.get("ic_mean", 0) or 0)
                    icir = abs(ic_result.get("ir", 0) or 0)
                    if ic_mean >= 0.05:
                        ic_grade = "强"
                    elif ic_mean >= 0.03:
                        ic_grade = "有效"
                    elif ic_mean >= 0.02:
                        ic_grade = "弱"
                    else:
                        ic_grade = "无效"
                    if icir >= 0.5:
                        icir_grade = "优秀"
                    elif icir >= 0.3:
                        icir_grade = "良好"
                    elif icir >= 0.1:
                        icir_grade = "一般"
                    else:
                        icir_grade = "较弱"

                    # 方向 (与 /evaluate 一致: RankIC 均值符号, 缺省回落 IC 均值)
                    _ic_for_dir = ic_result.get("rank_ic_mean")
                    if _ic_for_dir is None:
                        _ic_for_dir = ic_result.get("ic_mean")
                    if _ic_for_dir is None:
                        direction = "unknown"
                    else:
                        direction = "positive" if float(_ic_for_dir) >= 0 else "negative"

                    res.update({
                        "ok": True,
                        "factor_type": factor_type,
                        "ts_normalize_window": ts_norm_window,
                        "direction": direction,
                        "ic_timeseries": ic_result,
                        "layered_backtest": layer_result,
                        "quantile_backtest": quantile_result,
                        "performance_with_cost": pwc_result,
                        "effectiveness_grade": {"ic_grade": ic_grade, "icir_grade": icir_grade},
                        "n_stocks": len(panel),
                        "n_dates": len(fv.index),
                    })
                except Exception as e:
                    res.update({"ok": False, "reason": f"评价失败: {str(e)}"})
                q.put(("progress", {"index": idx, "total": len(candidates), "candidate": res}))

            q.put(("done", {"n_stocks": len(panel), "total": len(candidates)}))
        except Exception as e:
            q.put(("error", {"error": str(e)}))

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
            elif kind == "done":
                yield {"event": "done", "data": json.dumps(_json_safe(payload))}
                break
            elif kind == "error":
                yield {"event": "error", "data": json.dumps(payload)}
                break

    return EventSourceResponse(_event_gen())


def _parse_init_depth(v: Any) -> Optional[tuple]:
    """解析 init_depth, 支持 [min, max] 或 '2,6' 或 None"""
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return (int(v[0]), int(v[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(v, str):
        try:
            parts = [int(x.strip()) for x in v.split(",")]
            if len(parts) == 2:
                return (parts[0], parts[1])
        except (TypeError, ValueError):
            pass
    return None


def _parse_const_range(v: Any) -> Optional[tuple]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return (float(v[0]), float(v[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(v, str):
        try:
            parts = [float(x.strip()) for x in v.split(",")]
            if len(parts) == 2:
                return (parts[0], parts[1])
        except (TypeError, ValueError):
            pass
    return None


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False
