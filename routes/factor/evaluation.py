# -*- coding: utf-8 -*-
"""
routes/factor/evaluation.py -- 因子评价/试算路由
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

import numpy as np

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


@router.post("/evaluate")
@_json_safe_response
def evaluate_factor(body: Dict[str, Any] = Body(...)):
    """
    因子评价: IC时序 + 分层回测 + 清华PerformanceWithCost(含交易成本)
    读取factor_library的formula, 用calc_factor计算因子值, 然后多维度评价

    评价维度 (融合各CASE做法):
      1. IC时序 (来源: CASE-C/synthesizer): IC/RankIC/IR/IC胜率
      2. 分层回测 (来源: CASE-C/layered_backtest): 多空收益/分层收益
      3. PerformanceWithCost (来源: 清华day1_A): 含交易成本的夏普/年化收益/换手率

    body: {
        factor_id:    "rsi_14",                    # 因子库中的因子ID
        stock_codes:  ["000001", ...],             # 可选, 默认80只活跃股
        pool_type:    "active"/"industry"/"sector"/"concept"/"index"/"custom",  # 股票池类型
        pool_ref:     "白酒"/板块名/概念名/"000300"/自定义代码文本,           # 股票池子项
        start_date:   "2024-01-01",                # 可选, 默认近2年
        end_date:     "2025-12-31",                # 可选, 默认今天
        n_layers:     5,                           # 分层数, 默认5
        rebal_period: 21,                          # 调仓周期, 默认21日
        neutralize:   "sector"/"concept"/"industry"/"none"  # 中性化, 默认none
    }
    """
    factor_id = body.get("factor_id", "")
    expression = body.get("expression", "")   # 可选: 未入库临时因子表达式, 提供时覆盖 factor_id 的公式
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2025-12-31")
    n_layers = body.get("n_layers", 5)
    rebal_period = body.get("rebal_period", 21)
    neutralize_type = body.get("neutralize", "none")
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    if not factor_id:
        raise HTTPException(status_code=400, detail="factor_id不能为空")

    # 计算因子面板 + 因子元信息 (支持临时表达式覆盖 factor_id 公式)
    from lib.factor_engine import evaluate_expression, analyze_expression_tags
    def _compute_factor(panel):
        if expression:
            # 未入库临时因子: 直接用表达式计算, 构造临时元信息
            fv = evaluate_expression(expression, panel)
            tags_t = analyze_expression_tags(expression)
            fi = {
                "factor_id": factor_id,
                "formula": expression,
                "category": body.get("category", "composite"),
                # 修复: 未入库临时因子用表达式推断评价方式(含 technical_ts 启发式),
                # 使构建页性能测试对"价格水平/累积量纲"因子自动走时序标准化管线,
                # 而非一律按普通截面 continuous 评价(规模效应失真)。
                "evaluation_type": tags_t.get("factor_type") or "technical",
            }
            return fv, fi
        fv = calc_factor(factor_id, panel)
        return fv, (get_factor(factor_id) or {})

    # ============ 单股模式: 按因子类型路由 (参照多股, 结构差异: 无截面) ============
    # 单只股票无法做截面IC (同一时点只有1个样本), 技术/时序标准化/财务走"时间序列IC";
    # 信号因子走"事件研究"(命中率/条件收益, 逐股天然适用) —— 与多股保持同类型同口径。
    # 修复: 原单股无条件走 ts_ic 且持久化标签写死 technical, 对 signal/financial 语义不当。
    if pool_type == "single":
        from lib.factor_evaluator import _normalize_custom_code
        from lib.backtest_data import load_daily_kline
        code = _normalize_custom_code((pool_ref or "").strip())
        if not code:
            raise HTTPException(status_code=400, detail="单股模式请输入有效股票代码, 如 600519.SH")
        df = load_daily_kline(code, start_date, end_date, prefer="mysql")
        if df is None or len(df) < 150:
            got = 0 if df is None else len(df)
            raise HTTPException(status_code=400, detail=f"单股 {code} 数据不足 (需>=150个交易日, 当前 {got})")
        panel = {code: df}
        try:
            factor_values, factor_info = _compute_factor(panel)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"因子计算失败: {str(e)}")
        ftype = classify_factor_type(factor_info)
        # none 类型: 与多股一致, 明确拒绝而非报"计算失败"
        if ftype == "none":
            raise HTTPException(status_code=400, detail=(
                f"因子 {factor_id} 被标记为不可独立评价(评价方式=none), 不支持单因子评价; "
                "该因子是构造中间字段或待配引擎的因子, 如需评价请到因子详情修改评价方式。"))
        f_series = factor_values[code]
        flat_values = factor_values.values.flatten()
        flat_values = flat_values[~pd.isna(flat_values)]
        data_stats = {
            "count": int(len(flat_values)),
            "nan_ratio": round(float(factor_values.isna().mean().mean()), 4),
            "mean": round(float(factor_values.mean().mean()), 4),
            "std": round(float(factor_values.std().mean()), 4),
            "min": round(float(factor_values.min().min()), 4),
            "max": round(float(factor_values.max().max()), 4),
            "median": round(float(factor_values.median().median()), 4),
        }
        result = {
            "factor_type": "single",           # 前端单股展示模式标记(保持不变)
            "single_pipeline_type": ftype,     # 修复: 实际评价管线类型(technical/technical_ts/signal/financial)
            "factor_info": factor_info,
            "data_stats": data_stats,
            "n_stocks": 1,
            "n_dates": len(df),
            "factor_id": factor_id,
            "stock_code": code,
            "tags": analyze_expression_tags(expression),
        }
        method = "ts_ic"
        if ftype == "signal":
            # 事件信号评价: 单股即"该股历史上信号出现与否的条件收益/命中率"
            pr = evaluate_pattern_factor(
                factor_values, panel, rebal_period=rebal_period,
                direction=direction_to_int(factor_info.get("direction")))
            oh = pr.get("hit_rate", {}).get("overall_hit_rate")
            if oh is None:
                p_grade = "无效"
            elif oh >= 0.55:
                p_grade = "强"
            elif oh >= 0.52:
                p_grade = "有效"
            elif oh >= 0.50:
                p_grade = "弱"
            else:
                p_grade = "无效"
            result.update({"pattern_evaluation": pr,
                           "effectiveness_grade": {"pattern_grade": p_grade}})
            method = "signal"
        else:
            # 技术/时序标准化/财务: 单股时间序列IC
            #   financial: 持有期对齐季报(>=63日, 与多股财务口径一致)
            #   technical_ts: 先对自身历史滚动分位(窗口自适应降窗), 再算时序IC
            rebal_eff = rebal_period
            if ftype == "financial":
                rebal_eff = max(rebal_period, 63)
            elif ftype == "technical_ts":
                n_days = len(df.index)
                ts_win = resolve_ts_window(body.get("ts_normalize_window"), n_days, rebal_eff)
                f_series = ts_rank_normalize(factor_values, ts_win)[code]
                result["ts_normalize_window"] = ts_win
            single_ic = run_single_ic_timeseries(f_series, df, rebal_period=rebal_eff)
            result["single_ic"] = single_ic
            # 单股时序IC有效性分级 (参考: IC均值 + IR)
            ic_mean = single_ic.get("ic_mean")
            ir = single_ic.get("ir")
            if ic_mean is None:
                sgrade = "数据不足"
            elif abs(ic_mean) >= 0.05 and (ir is None or ir >= 0.3):
                sgrade = "有效"
            elif abs(ic_mean) >= 0.03:
                sgrade = "弱"
            else:
                sgrade = "无效"
            result["effectiveness_grade"] = {"single_grade": sgrade}
        # 持久化评价结果 (标量指标 + 完整JSON), 供因子库列表与切页恢复
        self_eval_params = {
            "pool_type": "single", "pool_ref": code,
            "start_date": start_date, "end_date": end_date,
            "method": method, "rebal_period": rebal_period, "n_layers": n_layers,
            "neutralize": neutralize_type,
            "evaluation_type": ftype,  # 修复: 写真实评价管线类型, 不再写死 technical
        }
        try:
            sic = result.get("single_ic") or {}
            save_metrics(factor_id, {
                "eval_date": datetime.now().date(),
                "ic_mean": sic.get("ic_mean"),
                "ic_std": sic.get("ic_std"),
                "ir": sic.get("ir"),
                "rank_ic_mean": sic.get("rank_ic_mean"),
                "rank_ic_ir": sic.get("rank_ic_ir"),
                "ic_positive_ratio": sic.get("ic_positive_ratio"),
                "long_short_return": None, "sharpe": None,
                "max_drawdown": None, "turnover": None,
                "eval_period": f"{start_date}~{end_date}",
            })
            save_eval_result("single", factor_id, result, self_eval_params)
        except Exception:
            pass
        return result

    # 按池类型构建股票池 (支持活跃/申万行业/概念/常见指数/自定义)
    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"股票池构建失败: {str(e)}")

    # 股票不足30只时, 自动补足活跃股
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

    # 计算因子值 (支持临时表达式覆盖 factor_id 公式)
    try:
        factor_values, factor_info = _compute_factor(panel)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"因子计算失败: {str(e)}")

    # 因子数据统计 (描述性统计)
    flat_values = factor_values.values.flatten()
    flat_values = flat_values[~pd.isna(flat_values)]
    data_stats = {
        "count": int(len(flat_values)),
        "nan_ratio": round(float(factor_values.isna().mean().mean()), 4),
        "mean": round(float(factor_values.mean().mean()), 4),
        "std": round(float(factor_values.std().mean()), 4),
        "min": round(float(factor_values.min().min()), 4),
        "max": round(float(factor_values.max().max()), 4),
        "median": round(float(factor_values.median().median()), 4),
    }

    # 因子类型分类 (技术/形态/财务 差异化评价)
    # 允许调用方显式指定评价口径 (technical/technical_ts/...), 用于结果页"重评"按钮
    _eval_override = (body.get("evaluation_type") or "").strip().lower()
    if _eval_override in ("technical", "technical_ts", "signal", "financial", "none"):
        factor_type = _eval_override
    else:
        factor_type = classify_factor_type(factor_info)

    # ============ 事件信号因子: 离散信号型, 走信号评价(命中率/条件收益) ============
    if factor_type == "signal":
        # 单极性0/1信号(新高/新低等)的多空语义由因子方向决定; CDL双极性由值符号决定(函数内自动检测)
        pattern_result = evaluate_pattern_factor(
            factor_values, panel, rebal_period=rebal_period,
            direction=direction_to_int(factor_info.get("direction")))
        oh = pattern_result.get("hit_rate", {}).get("overall_hit_rate")
        if oh is None:
            p_grade = "无效"
        elif oh >= 0.55:
            p_grade = "强"
        elif oh >= 0.52:
            p_grade = "有效"
        elif oh >= 0.50:
            p_grade = "弱"
        else:
            p_grade = "无效"
        result = {
            "factor_type": "signal",
            "pattern_evaluation": pattern_result,
            "factor_info": factor_info,
            "data_stats": data_stats,
            "effectiveness_grade": {"pattern_grade": p_grade},
            "n_stocks": len(panel),
            "n_dates": len(panel[next(iter(panel))].index),
            "factor_id": factor_id,
        }
        # 持久化评价结果 (信号因子无IC/IR, 只存完整JSON)
        try:
            save_metrics(factor_id, {
                "eval_date": datetime.now().date(),
                "ic_mean": None, "ic_std": None, "ir": None,
                "rank_ic_mean": None, "rank_ic_ir": None,
                "ic_positive_ratio": None, "long_short_return": None,
                "sharpe": None, "max_drawdown": None, "turnover": None,
                "eval_period": f"{start_date}~{end_date}",
            })
            save_eval_result("single", factor_id, result, {
                "pool_type": pool_type or "active", "pool_ref": pool_ref,
                "start_date": start_date, "end_date": end_date,
                "method": "signal", "rebal_period": rebal_period, "n_layers": n_layers,
                "neutralize": neutralize_type,
                "evaluation_type": "signal",
            })
        except Exception:
            pass
        return result

    # financial 之外的显式 none 标签: 明确拒绝而非报"计算失败"
    if factor_type == "none":
        raise HTTPException(status_code=400, detail=(
            f"因子 {factor_id} 被标记为不可独立评价(评价方式=none)。"
            "该因子是构造中间字段或待配引擎的因子, 不支持单因子评价; "
            "如需评价请到因子详情将评价方式改为其他类型。"))

    # 财务因子: 季度低频, 调仓周期对齐财报期(默认63日≈一季度), 避免固定21日失真
    if factor_type == "financial":
        rebal_period = max(rebal_period, 63)

    # 加载中性化映射 (支持市值 + 分组维度组合)
    sector_map = None
    concept_map = None
    industry_map = None
    marketcap_map = None
    marketcap_proxy_lookback = None
    mc_on = neutralize_type.startswith("marketcap")
    group = ""
    if neutralize_type.startswith("marketcap_"):
        group = neutralize_type[len("marketcap_"):]
    elif not mc_on:
        group = neutralize_type
    if mc_on:
        # 市值中性化改用"点-in-time 成交额代理"(近20日均额): 静态"当前市值"作用于
        # 历史截面存在时点错配/前视; 成交额当日可得、截面内与市值高度相关、无前视。
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

    # IC时序回测 (基于预计算面板)
    # 财务因子: 按财报期对齐调仓点 (财报数据可用日, 已含滞后避免未来函数), 避免固定周期失真
    # technical_ts 因子: 先对自身历史做滚动分位标准化(默认250日), 再走截面管线
    rebal_dates_arg = None
    if factor_type == "financial":
        from lib.factor_engine import financial_report_rebal_dates
        rebal_dates_arg = financial_report_rebal_dates(
            factor_values, panel, rebal_period=rebal_period, min_warmup=0)
    fv_for_eval = factor_values
    eff_warmup = 130
    ts_norm_window = None
    if factor_type == "technical_ts":
        # 窗口自适应: 数据不足时自动降到可行值, 避免空IC(样本0)/多因子无有效截面
        n_days = len(panel[next(iter(panel))].index) if panel else len(factor_values.index)
        ts_norm_window = resolve_ts_window(body.get("ts_normalize_window"), n_days, rebal_period)
        fv_for_eval = ts_rank_normalize(factor_values, ts_norm_window)
        eff_warmup = max(130, ts_norm_window)
    ic_result = run_ic_timeseries_panel(
        fv_for_eval, panel,
        rebal_period=rebal_period, min_warmup=eff_warmup,
        sector_map=sector_map, concept_map=concept_map, industry_map=industry_map,
        marketcap_map=marketcap_map,
        rebal_dates=rebal_dates_arg,
        n_layers=n_layers,
        marketcap_proxy_lookback=marketcap_proxy_lookback,
    )

    # 多期分层回测 (逐调仓日分层, 汇总为平均分层收益 + 各层累计净值曲线)
    # 修复: 旧实现只取"最新一个截面"做单期分层, 无 layer_cumret, 前端分层累计收益图为空;
    #       现改用 IC 时序循环中同步累积的多期分层结果 (与 CASE-C/layered_backtest 口径一致)。
    layered = ic_result.get("layered") or {}
    layer_result = {
        "layer_returns": layered.get("layer_returns") or {},
        "ic": ic_result.get("rank_ic_mean"),
        "long_short": layered.get("long_short"),
        "layer_cumret": layered.get("layer_cumret") or {},
        "long_short_cumret": layered.get("long_short_cumret") or [],
    }

    # 清华PerformanceWithCost评价 (含交易成本的因子收益评价)
    # 与IC/分层回测互补: IC看预测能力, PerformanceWithCost看实际交易收益
    # 修复: 统一用 fv_for_eval (technical_ts 已时序分位标准化; 其余类型等价原始值),
    #       避免价格水平/累积量纲因子(均线绝对值/OBV/STDDEV等)的 PWC 截面排序被
    #       绝对量纲(价格规模)主导, 与IC/分层口径一致。
    pwc_result = None
    try:
        total_ret_panel = build_total_return_panel(panel)
        if not total_ret_panel.empty and not fv_for_eval.empty:
            pwc_result = PerformanceWithCost(
                fv_for_eval, total_ret_panel,
                delayNum=2, cost=0.002, SDate=0, EDate=-1,
            )
    except Exception:
        pass

    # 清华GetQuantileRet分位数收益 (来源: 清华day1_A, 观察因子收益随分位单调性)
    quantile_result = None
    try:
        if not total_ret_panel.empty and not fv_for_eval.empty:
            quantile_result = GetQuantileRet(
                fv_for_eval, total_ret_panel,
                Q=n_layers, delayNum=2, cost=0.0, SDate=0, EDate=-1,
            )
    except Exception:
        pass

    # 因子基本信息 (从数据库读取)
    factor_info = get_factor(factor_id) or {}

    # 因子数据统计 (描述性统计)
    flat_values = factor_values.values.flatten()
    flat_values = flat_values[~pd.isna(flat_values)]
    data_stats = {
        "count": int(len(flat_values)),
        "nan_ratio": round(float(factor_values.isna().mean().mean()), 4),
        "mean": round(float(factor_values.mean().mean()), 4),
        "std": round(float(factor_values.std().mean()), 4),
        "min": round(float(factor_values.min().min()), 4),
        "max": round(float(factor_values.max().max()), 4),
        "median": round(float(factor_values.median().median()), 4),
    }

    # 有效性评级 (融合CASE-机器学习和CASE-网格的判定标准)
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

    # D5 单因子诊断增强 (2026-08-15, 详见 docs/因子库D组文字化因子处理计划.md 第九节)
    #   1. 多持有期衰减: IC 随持有期 1/5/10/20 日变化
    #   2. 分年度IC稳定性: ic_series 按年聚合
    #   3. 中性化前后IC对比: neutralize 非 none 时, 追加一次"未中性化"截面IC
    #   仅技术类截面评价适用(财务按财报期对齐、signal 无 IC、单股走时序IC, 均不做诊断)
    ic_decay = None
    yearly_ic = None
    neutralize_contrast = None
    if factor_type in ("technical", "technical_ts"):
        from lib.factor_evaluator import compute_ic_decay, compute_yearly_ic
        try:
            ic_decay = compute_ic_decay(fv_for_eval, panel, rebal_period, eff_warmup)
        except Exception:
            pass
        try:
            yearly_ic = compute_yearly_ic(ic_result.get("ic_series") or [])
        except Exception:
            pass
        if neutralize_type != "none":
            try:
                raw_ic = run_ic_timeseries_panel(
                    fv_for_eval, panel, rebal_period=rebal_period, min_warmup=eff_warmup,
                    rebal_dates=rebal_dates_arg, n_layers=n_layers)
                neutralize_contrast = {
                    "neutralize": neutralize_type,
                    "raw_ic_mean": raw_ic.get("ic_mean"),
                    "neutralized_ic_mean": ic_result.get("ic_mean"),
                }
            except Exception:
                pass

    # 财务因子质量指标 (2026-08-16 补充):
    #   fill_ratio = 中位数填充占比: asof+ffill 后仍缺失(无可用财报)的格子, 在多因子合成/
    #   预处理中会被"截面中位数"填充, 此处显式给出该占比, 作为财务因子性能的伴随指标
    #   (填充占比过高说明样本严重不完整, IC 参考意义下降)。
    financial_quality = None
    if factor_type == "financial":
        try:
            missing = float(factor_values.isna().mean().mean())
            financial_quality = {
                "fill_ratio": round(missing, 4),       # 中位数填充占比 = 缺失占比
                "non_null_ratio": round(1 - missing, 4),
                "n_report_dates": len(rebal_dates_arg or []),  # 财报可用日调仓点数
                "rebal_period": rebal_period,
                "note": "财务因子评价前已按财报披露滞后(report_date+分级lag)asof对齐, "
                        "剩余缺失在合成/预处理中会用截面中位数填充, 填充占比即此处缺失占比。",
            }
        except Exception:
            financial_quality = None

    # ---- 方向判定: 在评价完成后才确定 (由全局 IC 均值符号决定) ----
    # 覆盖公式结构解析的初值; 连续型(technical/technical_ts/financial)用 RankIC 均值
    # (缺省回落 IC 均值) 的符号判方向; signal 的信号方向由值符号/模型语义主导, 不在此自动覆盖。
    _eval_tags = analyze_expression_tags(expression or factor_info.get("formula", ""))
    if factor_type != "signal" and isinstance(ic_result, dict):
        _ic_for_dir = ic_result.get("rank_ic_mean")
        if _ic_for_dir is None:
            _ic_for_dir = ic_result.get("ic_mean")
        if _ic_for_dir is not None:
            _eval_tags["direction"] = "positive" if float(_ic_for_dir) >= 0 else "negative"

    result = {
        "ic_timeseries": ic_result,
        "layered_backtest": layer_result,
        "performance_with_cost": pwc_result,
        "quantile_backtest": quantile_result,
        "factor_info": factor_info,
        "data_stats": data_stats,
        "factor_type": factor_type,
        "financial_quality": financial_quality,      # 财务因子: 中位数填充占比/财报调仓点数
        "ts_normalize_window": ts_norm_window,  # technical_ts 因子的时序标准化窗口(其余类型为None)
        "effectiveness_grade": {
            "ic_grade": ic_grade,
            "icir_grade": icir_grade,
        },
        "ic_decay": ic_decay,                  # D5: 多持有期IC衰减
        "yearly_ic": yearly_ic,                # D5: 分年度IC稳定性
        "neutralize_contrast": neutralize_contrast,  # D5: 中性化前后IC对比
        "n_stocks": len(panel),
        "n_dates": len(factor_values.index) if factor_values is not None and not factor_values.empty else 0,
        "factor_id": factor_id,
        "rebal_period_used": rebal_period,  # 财务因子会按财报期对齐(>=63日), 与请求值可能不同
        "tags": _eval_tags,  # 方向已在评价后由全局IC均值符号确定
    }
    # 持久化评价结果 (标量指标到 factor_metrics, 完整JSON到 factor_eval_result)
    ls_ret = None
    try:
        ls_ret = layer_result.get("long_short")
    except Exception:
        pass
    pwc_sharpe = pwc_result.get("sharpe_ratio") if isinstance(pwc_result, dict) else None
    pwc_turnover = pwc_result.get("turnover") if isinstance(pwc_result, dict) else None
    try:
        save_metrics(factor_id, {
            "eval_date": datetime.now().date(),
            "ic_mean": ic_result.get("ic_mean"),
            "ic_std": ic_result.get("ic_std"),
            "ir": ic_result.get("ir"),
            "rank_ic_mean": ic_result.get("rank_ic_mean"),
            "rank_ic_ir": ic_result.get("rank_ic_ir"),
            "ic_positive_ratio": ic_result.get("ic_positive_ratio"),
            "long_short_return": ls_ret,
            "sharpe": pwc_sharpe,
            "max_drawdown": None,
            "turnover": pwc_turnover,
            "eval_period": f"{start_date}~{end_date}",
        })
        save_eval_result("single", factor_id, result, {
            "pool_type": pool_type or "active", "pool_ref": pool_ref,
            "start_date": start_date, "end_date": end_date,
            "method": "single", "rebal_period": rebal_period, "n_layers": n_layers,
            "neutralize": neutralize_type,
            "evaluation_type": factor_type,
        })
    except Exception:
        pass
    return result


@router.post("/trial")
def trial_factor(body: Dict[str, Any] = Body(...)):
    """
    因子表达式试计算 + 合理性诊断 (构建页"校验/试算")

    轻量级校验, 不跑完整IC/分层评价:
      1. 静态校验: 语法 + 白名单 (validate_expression)
      2. 自动解析标签: 基类/类型/方向 (analyze_expression_tags)
      3. 试计算: 少量股票 + 短区间, 验证表达式能否算通、输出是否合理
         (非空率/离散度/信号与连续算子混用), 排查拼装错误

    body: {
        expression:  "因子表达式",
        pool_type:   "active",              # 可选
        pool_ref:    "",                    # 可选
        start_date:  "2024-01-01",          # 可选, 默认近2年
        end_date:    "2025-12-31",          # 可选, 默认今天
    }
    """
    import pandas as pd
    import re
    from datetime import timedelta
    from lib.factor_engine import analyze_expression_tags

    expression = (body.get("expression") or "").strip()
    if not expression:
        raise HTTPException(status_code=400, detail="表达式不能为空")

    warnings: List[str] = []
    suggestions: List[str] = []

    # 1. 静态校验 (语法 + 白名单)
    is_valid, msg = validate_expression(expression)
    if not is_valid:
        return {
            "ok": False, "stage": "syntax",
            "message": f"表达式语法/白名单校验未通过: {msg}",
            "tags": None, "factor_type": None, "data_stats": None,
            "warnings": [f"静态校验未通过: {msg}"],
            "suggestions": ["请检查是否存在未支持的函数/字段名, 或参数个数/名称错误"],
        }

    # 2. 自动解析标签 (基类/类型/方向)
    tags = analyze_expression_tags(expression)
    factor_type = tags.get("factor_type") or "technical"

    # 3. 轻量试计算 (少量股票 + 短区间, 只验证可算性与输出合理性)
    pool_type = body.get("pool_type", "active")
    pool_ref = body.get("pool_ref", "")
    start_date = body.get("start_date", "") or ""
    end_date = body.get("end_date", "") or ""
    today = date.today()
    if not end_date:
        end_date = today.isoformat()
    if not start_date:
        start_date = (today - timedelta(days=365 * 2)).isoformat()

    # 构建小样本股票池 (最多10只)
    codes: List[str] = []
    try:
        from lib.factor_evaluator import get_pool_stocks, get_active_stock_pool
        if pool_type:
            try:
                codes = get_pool_stocks(pool_type, pool_ref, n=10, min_days=130) or []
            except Exception:
                codes = []
        if not codes:
            codes = get_active_stock_pool(n=10, min_days=130) or []
    except Exception:
        codes = []

    from lib.backtest_data import load_daily_kline
    panel: Dict[str, Any] = {}
    for code in codes[:10]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > 60:
                panel[code] = df
        except Exception:
            pass

    if len(panel) < 3:
        return {
            "ok": False, "stage": "data",
            "message": "试计算样本数据不足 (有效股票 < 3 只), 无法验证计算",
            "tags": tags, "factor_type": factor_type, "data_stats": None,
            "warnings": ["样本数据不足, 请检查日期区间或股票池"],
            "suggestions": ["检查开始/结束日期是否合理, 或更换股票池"],
        }

    # 计算因子值 (捕获实际计算异常, 这是试计算的核心目的)
    try:
        fv = evaluate_expression(expression, panel)
    except Exception as e:
        return {
            "ok": False, "stage": "calc",
            "message": f"因子计算报错: {str(e)}",
            "tags": tags, "factor_type": factor_type, "data_stats": None,
            "warnings": [f"试计算失败: {str(e)}"],
            "suggestions": ["检查参数是否正确 (周期过大/字段缺失/混用信号与连续算子)"],
        }

    # 4. 输出统计诊断
    try:
        fnum = fv.astype(float)
    except Exception:
        fnum = fv
    flat = np.asarray(fnum.values, dtype=float).flatten()
    flat = flat[~np.isnan(flat)]
    finite = flat[np.isfinite(flat)]
    data_stats = {
        "count": int(len(finite)),
        "nan_ratio": round(float(1 - len(finite) / max(1, int(np.asarray(fnum.values).size))), 4),
        "mean": round(float(np.mean(finite)), 6) if len(finite) else None,
        "std": round(float(np.std(finite)), 6) if len(finite) else None,
        "min": round(float(np.min(finite)), 6) if len(finite) else None,
        "max": round(float(np.max(finite)), 6) if len(finite) else None,
        "median": round(float(np.median(finite)), 6) if len(finite) else None,
        "n_stocks": len(panel),
        "n_dates": int(len(panel[next(iter(panel))].index)),
    }

    # 5. 合理性诊断
    ok = True
    if len(finite) == 0 or data_stats["nan_ratio"] >= 0.95:
        ok = False
        warnings.append("输出几乎全部为 NaN/Inf (非空率 < 5%), 因子可能周期过大、字段缺失或数据不足")
        suggestions.append("尝试缩短窗口周期, 或检查引用的字段/基类是否存在于行情数据中")
    elif len(finite) < 10:
        ok = False
        warnings.append(f"有效样本过少 (仅 {len(finite)} 个), 难以作为因子使用")
        suggestions.append("尝试缩短窗口周期以增大有效样本")
    else:
        if data_stats["nan_ratio"] > 0.5:
            warnings.append(f"输出非空率仅 {round((1 - data_stats['nan_ratio']) * 100)}%, 缺失较多, 建议缩短窗口或增大样本")
        if data_stats["std"] is not None and abs(data_stats["std"]) < 1e-12:
            ok = False
            warnings.append("输出为标准差≈0 的常量, 因子无区分度 (可能是常数表达式或窗口覆盖全NaN)")
            suggestions.append("检查表达式是否真正引用了行情字段/算子")

    # 信号与连续处理算子的混用诊断 (仅提示, 不阻塞)
    # 修复: 表达式中的连续处理算子用基类名(returns/sma/rsi等, 来自 BASE_OPERATOR_MAP),
    #       而非内部算子名(ts_Mean/ts_Sum等) —— 原匹配 ts_* 名称永远无法命中, 诊断失效。
    expr_lower = expression.lower()
    if "ta_cdl" in expr_lower or factor_type == "signal":
        from lib.factor_engine import BASE_OPERATOR_MAP
        # 连续处理/变换类基类 (排除纯恒等字段引用: close/open/volume/amount/vwap/value 等)
        _ident_fields = {"open", "high", "low", "close", "volume", "amount",
                         "vwap", "value", "idioret", "totalret", "turnover_rate"}
        _cont_ops = [op for op in BASE_OPERATOR_MAP
                     if op not in _ident_fields
                     and re.search(r"\b" + re.escape(op) + r"\s*\(", expr_lower)]
        if _cont_ops:
            warnings.append("检测到信号因子(ta_CDL形态/0-1事件)与连续处理算子 "
                            f"({', '.join(_cont_ops)}) 混用, 平滑/累计可能改变信号语义, 请确认意图")
            suggestions.append("信号类因子建议直接使用或按方向取平均, 避免对0/±100信号做连续平滑")
    if "fn(" in expr_lower and any(k in expr_lower for k in
                                   ("close", "open", "high", "low", "volume", "vwap")):
        warnings.append("财务字段(FN)与价量字段混用, 二者量纲不同, 建议先做标准化或分开合成")

    if ok:
        message = "试计算通过: 表达式可正常计算, 输出分布合理"
    else:
        message = "试计算未通过: 表达式可执行但输出不合理, 请参考下方警告"
    # 评价方式提示: 让用户知道"这个表达式是什么类型的因子 / 该填什么评价方式"。
    #   - technical_ts 由启发式自动识别(价格水平/累积量纲); 其余由公式规则判定。
    #   - 每类都给出判定依据, 用户据此在保存弹窗/因子库详情确认或覆盖评价方式。
    _type_explain = {
        "technical": "截面连续型: 输出为量纲可比的技术指标(动量/波动/比率/乖离/排序等), "
                     "直接做截面IC/分层/PWC评价。若你的表达式其实是均线绝对值/价格水平/"
                     "OBV/AD/STDDEV/VAR 等绝对量纲, 请到因子库详情把评价方式改为 时序标准化(technical_ts)。",
        "technical_ts": "时序标准化截面型(自动识别): 输出为价格水平/累积量纲/绝对波动"
                        "(均线绝对值、价格变换、回归价格、OBV/AD、STDDEV/VAR), 跨股票量纲不可比, "
                        "评价前会对自身历史做滚动分位标准化后再走截面IC/分层。保存后即按此口径评价; "
                        "若误识别(实际是量纲可比指标), 请到因子库详情改回 截面连续型(technical)。",
        "signal": "事件信号型: 输出为离散信号(CDL形态 0/±100、新高/新低 0/1、趋势模式等), "
                  "走命中率/条件收益评价(不走IC/分层)。",
        "financial": "财务因子: 公式引用 FN(财报字段), 走财报期对齐评价(自动按披露滞后避免未来函数)。",
    }
    eval_hint = _type_explain.get(factor_type) or (
        "表达式推断为 technical, 若为价格水平/累积量纲因子请改为 时序标准化(technical_ts)。")
    return {
        "ok": ok,
        "stage": "ok",
        "message": message,
        "tags": tags,
        "factor_type": factor_type,
        "data_stats": data_stats,
        "warnings": warnings,
        "suggestions": suggestions,
        "eval_hint": eval_hint,
        "samples": {
            code: [round(float(x), 6) for x in fnum[code].dropna().tail(5).tolist()]
            for code in list(panel.keys())[:3]
        },
    }


# ============================================================
# 多因子分阶段流程 (阶段B1数据准备 + 阶段B2合成评价)
# ============================================================
# 阶段B1(单因子预评价 + 技术类截面构建与预处理清洗)与合成方式无关,
# 其结果在内存中缓存; 阶段B2按任意合成方式复用缓存, 切换合成方式/调ML参数时
# 无需重跑阶段B1。
# 注: B1 缓存 _MULTI_PREP_CACHE/_MULTI_PREP_CACHE_MAX 定义在 multifactor.py
#     (使用方所在文件), 此处不持有该缓存。

@router.get("/eval_result")
def get_eval_result_api(eval_type: str = "single",
                        eval_key: str = "",
                        pool_type: Optional[str] = None,
                        pool_ref: Optional[str] = None,
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None,
                        method: Optional[str] = None,
                        neutralize: Optional[str] = None,
                        evaluation_type: Optional[str] = None):
    """查询指定因子/组合的历史评价完整结果

    参数:
        eval_type: single / multi
        eval_key:  单因子=因子ID; 多因子=因子组合标识(逗号分隔)
        其余为可选的参数匹配条件, 提供时优先精确匹配同配置结果,
        否则返回该 eval_key 最近一次评价结果。
        evaluation_type: 评价管线口径(technical/technical_ts/signal/financial),
                    同一因子不同管线的结果独立存储, 查询时传入可精确匹配。
    返回: {found, params, result, created_at} 或 {found: false}
    """
    if not eval_key:
        return {"found": False, "error": "缺少 eval_key"}
    params = {}
    if pool_type:
        params["pool_type"] = pool_type
    if pool_ref:
        params["pool_ref"] = pool_ref
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if method:
        params["method"] = method
    if neutralize:
        params["neutralize"] = neutralize
    if evaluation_type:
        params["evaluation_type"] = evaluation_type
    data = get_eval_result(eval_type, eval_key, params or None)
    if not data:
        return {"found": False}
    return {"found": True, **data}


# 引入 pandas 引用 (evaluate_expression 等函数需要)
import pandas as pd


# ============================================================
# Tab 6: 批量性能分析 + 单因子详情评估
# ============================================================

@router.get("/evaluable")
def get_evaluable_factors():
    """获取当前支持自动计算的因子列表 (calc_factor 能覆盖的所有有可执行formula的因子)"""
    import re
    all_factors = list_factors()

    def _is_evaluable(f):
        """判断因子是否可计算: 评价方式标签为none的因子不可评价; formula含函数调用且无中文描述"""
        if (f.get("evaluation_type") or "").strip().lower() == "none":
            return False
        formula = f.get("formula", "")
        if not formula:
            return False
        # 纯文本描述(含中文)不可计算
        if any('\u4e00' <= ch <= '\u9fff' for ch in formula):
            return False
        # 含函数调用语法的表达式可计算
        if '(' in formula:
            return True
        return False

    evaluable = [f for f in all_factors if _is_evaluable(f)]
    return {
        "evaluable": evaluable,
        "count": len(evaluable),
        "total": len(all_factors),
        "not_evaluable_count": len(all_factors) - len(evaluable),
    }


@router.post("/batch_evaluate")
@_json_safe_response
def batch_evaluate(body: Dict[str, Any] = Body(...)):
    """
    批量性能分析: 对所有可计算因子做 IC/IR/分层回测, 结果存入 factor_metrics 表

    body: {
        stock_codes: [...]  (可选, 空则自动选取80只活跃股)
        start_date: "2024-01-01",
        end_date: "2025-12-31",
        rebal_period: 21,
        n_layers: 5
    }
    """
    from lib.factor_evaluator import batch_evaluate_factors

    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date")
    rebal_period = body.get("rebal_period", 21)
    n_layers = body.get("n_layers", 5)

    # 收集进度日志 (同步执行, 进度通过返回值体现)
    logs = []
    def _cb(msg):
        logs.append(msg)

    try:
        result = batch_evaluate_factors(
            stock_codes=stock_codes if stock_codes else None,
            start_date=start_date,
            end_date=end_date,
            rebal_period=rebal_period,
            n_layers=n_layers,
            factor_ids=body.get("factor_ids"),
            limit=body.get("limit"),
            progress_callback=_cb,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"批量评估失败: {str(e)}")

    return {
        "ok": True,
        "n_evaluated": result["n_evaluated"],
        "n_total": result["n_total"],
        "n_stocks": result["n_stocks"],
        "n_rebalances": result["n_rebalances"],
        "eval_date": result["eval_date"],
        "eval_period": result["eval_period"],
        "factor_results": result["factor_results"],
        "logs": logs[-20:],  # 只返回最后20条日志
    }


@router.post("/evaluate_single")
def evaluate_single(body: Dict[str, Any] = Body(...)):
    """
    单因子详细评估: IC时序 + 分层累计收益曲线 + 多空累计收益

    body: {
        factor_id: "MOM_1M",
        stock_codes: [...],
        start_date: "2024-01-01",
        end_date: "2025-12-31",
        n_layers: 5,
        rebal_period: 21
    }
    """
    from lib.factor_evaluator import evaluate_single_factor

    factor_id = body.get("factor_id", "")
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date")
    n_layers = body.get("n_layers", 5)
    rebal_period = body.get("rebal_period", 21)

    if not factor_id:
        raise HTTPException(status_code=400, detail="请指定 factor_id")
    # 股票池为空时自动选取活跃股 (不强制要求手选)
    if not stock_codes:
        from lib.factor_evaluator import get_active_stock_pool
        stock_codes = get_active_stock_pool(n=80, min_days=200)

    try:
        result = evaluate_single_factor(
            factor_id=factor_id,
            stock_codes=stock_codes,
            start_date=start_date,
            end_date=end_date,
            rebal_period=rebal_period,
            n_layers=n_layers,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"评估失败: {str(e)}")

    return result


# ============================================================
# 因子包 (可复用的多因子选股配置): 保存/列表/加载/删除
# ============================================================
