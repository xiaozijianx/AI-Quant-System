# -*- coding: utf-8 -*-
"""
routes/factor/library.py -- 因子库路由
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


@router.get("/categories")
def get_categories():
    """获取因子分类列表"""
    try:
        cats = list_categories()
        return {"categories": cats}
    except Exception as e:
        return {"categories": [], "error": str(e)}


@router.get("/stock_pools")
def get_stock_pools():
    """获取可选股票池清单 (评价页面下拉: 活跃/申万行业/概念/常见指数/自定义)"""
    try:
        from lib.factor_evaluator import get_stock_pool_options
        return get_stock_pool_options()
    except Exception as e:
        return {"pool_types": [], "industries": [], "sectors": [], "concepts": [], "indexes": [],
                "error": str(e)}


@router.get("/bases")
def get_bases():
    """获取因子基类列表 (归并/构造用)

    为 fixed 固定基类挂接"可拼装的引擎公式" + 可拼装标记:
      - formula:       该基类对应的可执行公式 (供构建页直接插入)
      - assemblable:   公式能否被表达式引擎直接计算 (true 可点击拼装)
      - skip_reason:   不可拼装时的原因 (无引擎公式 / 公式不合法)

    公式来源优先级:
      1. 因子库中该基类对应具体因子的公式 (base_id 匹配, 支持逗号分隔多基类)
      2. 无库公式时回退到引擎基类映射自动生成 (如 kdj() 等固定参数基类)
    """
    try:
        from lib.factor_engine import BASE_OPERATOR_MAP
        bases = list_bases()
        # 按 base_id 归集因子库中的具体因子 (支持逗号分隔多基类)
        factors = list_factors()
        by_base: Dict[str, list] = {}
        # 同名字典: factor_id == base_id 的因子 (基类自身的直接实例, 公式最准)
        by_same_id: Dict[str, str] = {}
        for f in factors or []:
            bids = [b.strip() for b in (f.get("base_id") or "").split(",") if b.strip()]
            for b in bids:
                by_base.setdefault(b, []).append(f)
            # 若因子ID与基类同名, 记录其公式 (如 close->close(), kdj_d->ts_KDJ_D(...))
            if (f.get("factor_id") or "") == (f.get("base_id") or ""):
                by_same_id[f["factor_id"]] = (f.get("formula") or "").strip()
        enriched = []
        for b in bases:
            item = dict(b)
            if b.get("type") == "fixed":
                formula = ""
                # 固定基类公式优先级:
                #   1. 同名因子公式 (factor_id == base_id, 基类自身的直接实例, 避免被复合因子污染)
                #   2. 引擎基类映射自动生成 (如 bbands() 等固定参数基类)
                #   3. 任意 base_id 含该基类的因子公式 (兜底, 仅供查看)
                formula = by_same_id.get(b["base_id"], "")
                if not formula and b["base_id"] in BASE_OPERATOR_MAP:
                    op, _fields, arity = BASE_OPERATOR_MAP[b["base_id"]]
                    formula = f"{b['base_id']}()" if arity == 0 else f"{b['base_id']}(14)"
                if not formula:
                    cands = by_base.get(b["base_id"], []) or []
                    for f in cands:
                        fm = (f.get("formula") or "").strip()
                        if fm:
                            formula = fm
                            break
                item["formula"] = formula
                if formula:
                    ok, msg = validate_expression(formula)
                    item["assemblable"] = bool(ok)
                    item["skip_reason"] = None if ok else msg
                else:
                    item["assemblable"] = False
                    item["skip_reason"] = "库内无该基类的可执行公式"
            else:
                # periodic: 由前端按周期弹窗生成 baseId(period), 无需挂公式
                item["formula"] = ""
                item["assemblable"] = True
            enriched.append(item)
        return {"bases": enriched, "total": len(enriched)}
    except Exception as e:
        return {"bases": [], "error": str(e)}


@router.get("/list")
def get_factor_list(category: Optional[str] = None,
                    is_custom: Optional[bool] = None,
                    search: Optional[str] = None):
    """获取因子列表"""
    try:
        factors = list_factors(category=category, is_custom=is_custom, search=search)
        return {"factors": factors, "total": len(factors)}
    except Exception as e:
        return {"factors": [], "error": str(e)}


@router.get("/detail/{factor_id}")
def get_factor_detail(factor_id: str):
    """获取因子详情 + 性能历史 + 基类信息"""
    factor = get_factor(factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail=f"因子 {factor_id} 不存在")
    metrics = get_metrics_history(factor_id)
    # 基类信息: 指向参数化基类时查 factor_base; 基础因子 base_id=自己时用因子自身名
    # 多因子组合的 base_id 为逗号分隔, 返回 base_list
    base = None
    base_list = []
    if factor.get("base_id"):
        bids = [b.strip() for b in factor["base_id"].split(",") if b.strip()]
        for bid in bids:
            b = get_base(bid)
            if not b:
                # 可能在 factor_library 中(源头因子是具体因子而非基类)
                src = get_factor(bid)
                if src:
                    b = {"base_id": bid, "name": src.get("name", bid),
                         "type": "factor", "instance_type": src.get("factor_type", "composite")}
                elif bid == factor_id:
                    b = {"base_id": factor_id, "name": factor.get("name", factor_id),
                         "type": "fixed", "instance_type": "basic"}
            if b:
                base_list.append(b)
        # 兼容旧字段: 单一基类时 base=该基类; 多基类时 base=None
        base = base_list[0] if len(base_list) == 1 else None
    return {
        "factor": factor,
        "metrics_history": metrics,
        "base": base,
        "base_list": base_list,
    }


@router.delete("/{factor_id}")
def remove_factor(factor_id: str):
    """删除因子（软删除）"""
    ok = delete_factor(factor_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"因子 {factor_id} 不存在")
    return {"ok": True}


@router.post("/init")
def init_factor_library():
    """初始化因子库（建表 + 导入基础因子）"""
    from lib.factor_init import run_init
    count = run_init()
    return {"ok": True, "total_factors": count}


# ============================================================
# Tab 2: 因子构建
# ============================================================

# 算子描述 (供前端展示)
OPERATORS = [
    {"name": "ts_Delay", "category": "时序", "desc": "滞后n期", "usage": "ts_Delay(Close, 5)",
     "params": "field, n"},
    {"name": "ts_Mean", "category": "时序", "desc": "n期移动平均", "usage": "ts_Mean(Close, 10)",
     "params": "field, n"},
    {"name": "ts_Decay", "category": "时序", "desc": "n期线性衰减加权均值", "usage": "ts_Decay(Close, 10)",
     "params": "field, n"},
    {"name": "ts_DecayExp", "category": "时序", "desc": "n期非线性衰减均值", "usage": "ts_DecayExp(Close, 10)",
     "params": "field, n"},
    {"name": "ts_Max", "category": "时序", "desc": "n期滚动最大值", "usage": "ts_Max(High, 20)",
     "params": "field, n"},
    {"name": "ts_Min", "category": "时序", "desc": "n期滚动最小值", "usage": "ts_Min(Low, 20)",
     "params": "field, n"},
    {"name": "ts_Delta", "category": "时序", "desc": "n期差值", "usage": "ts_Delta(Close, 5)",
     "params": "field, n"},
    {"name": "ts_Stdev", "category": "时序", "desc": "n期滚动标准差", "usage": "ts_Stdev(Close, 20)",
     "params": "field, n"},
    {"name": "ts_Sum", "category": "时序", "desc": "n期滚动求和", "usage": "ts_Sum(Volume, 5)",
     "params": "field, n"},
    {"name": "ts_Kurtosis", "category": "时序", "desc": "n期滚动峰度", "usage": "ts_Kurtosis(Close, 20)",
     "params": "field, n"},
    {"name": "ts_Skewness", "category": "时序", "desc": "n期滚动偏度", "usage": "ts_Skewness(Close, 20)",
     "params": "field, n"},
    {"name": "ts_Median", "category": "时序", "desc": "n期滚动中位数", "usage": "ts_Median(Close, 20)",
     "params": "field, n"},
    {"name": "cs_Rank", "category": "截面", "desc": "截面排名(0~1)", "usage": "cs_Rank(Close)",
     "params": "field"},
    {"name": "cs_Zscore", "category": "截面", "desc": "截面Z-score标准化", "usage": "cs_Zscore(Close)",
     "params": "field"},
    {"name": "cs_TransNorm", "category": "截面", "desc": "截面正态分位数变换", "usage": "cs_TransNorm(Close)",
     "params": "field"},
    # ---- AlphaMaster 映射补充时序算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1) ----
    {"name": "ts_ArgMax", "category": "时序", "desc": "n期窗口内最大值位置(0~1)", "usage": "ts_ArgMax(Close, 20)",
     "params": "field, n"},
    {"name": "ts_ArgMin", "category": "时序", "desc": "n期窗口内最小值位置(0~1)", "usage": "ts_ArgMin(Close, 20)",
     "params": "field, n"},
    {"name": "ts_Scale", "category": "时序", "desc": "因果L1归一化(累积和)", "usage": "ts_Scale(Close)",
     "params": "field"},
    {"name": "ts_Product", "category": "时序", "desc": "n期滑动乘积", "usage": "ts_Product(Close, 5)",
     "params": "field, n"},
    {"name": "ts_DecayLinear", "category": "时序", "desc": "n期线性衰减加权均值", "usage": "ts_DecayLinear(Close, 5)",
     "params": "field, n"},
    # ---- AlphaMaster 映射补充算术算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1) ----
    {"name": "sign", "category": "算术", "desc": "符号函数", "usage": "sign(Close)",
     "params": "field"},
    {"name": "gate", "category": "算术", "desc": "条件门: cond>0取x否则取y", "usage": "gate(cond, x, y)",
     "params": "cond, x, y"},
    {"name": "jump", "category": "算术", "desc": "因果expanding zscore + tanh软化", "usage": "jump(Close)",
     "params": "field"},
    {"name": "max3", "category": "算术", "desc": "3期最大值(含当前及前2期)", "usage": "max3(Close)",
     "params": "field"},
    {"name": "power", "category": "算术", "desc": "带符号乘方: sign(x)*|x|^a", "usage": "power(Close, 2)",
     "params": "field, a"},
    {"name": "signed_log", "category": "算术", "desc": "带符号对数: sign(x)*log1p(|x|)", "usage": "signed_log(Close)",
     "params": "field"},
    {"name": "sqrt", "category": "算术", "desc": "带符号开方: sign(x)*sqrt(|x|)", "usage": "sqrt(Close)",
     "params": "field"},
    {"name": "clip", "category": "算术", "desc": "固定裁剪到[lo,hi]", "usage": "clip(Close, -3, 3)",
     "params": "field, lo, hi"},
    {"name": "sigmoid", "category": "算术", "desc": "sigmoid压缩到(0,1)", "usage": "sigmoid(Close)",
     "params": "field"},
    {"name": "tanh_squash", "category": "算术", "desc": "tanh压缩到(-1,1)", "usage": "tanh_squash(Close)",
     "params": "field"},
    {"name": "if_gt", "category": "算术", "desc": "条件选择: cond>0取x否则取y", "usage": "if_gt(cond, x, y)",
     "params": "cond, x, y"},
    {"name": "winsorize", "category": "算术", "desc": "去极值(裁剪到[lo,hi])", "usage": "winsorize(Close, -3, 3)",
     "params": "field, lo, hi"},
]

# 字段描述 (供前端展示)
FIELDS = [
    {"name": "Open", "desc": "开盘价"},
    {"name": "High", "desc": "最高价"},
    {"name": "Low", "desc": "最低价"},
    {"name": "Close", "desc": "收盘价"},
    {"name": "Volume", "desc": "成交量"},
    {"name": "Amount", "desc": "成交额"},
    {"name": "VWAP", "desc": "成交量加权均价"},
    {"name": "Turnover", "desc": "换手率"},
]


@router.get("/operators")
def get_operators():
    """获取可用算子列表"""
    return {"operators": OPERATORS}


@router.get("/fields")
def get_fields():
    """获取可用字段列表"""
    return {"fields": FIELDS}




@router.post("/save")
def save_custom_factor(body: Dict[str, Any] = Body(...)):
    """保存自定义因子 (支持自动解析标签, 用户可覆盖)

    body: {
        factor_id, name, expression,
        category, direction, description,  # 可选, 未提供时自动解析
        base_id, factor_type               # 可选, 未提供时从表达式自动解析
    }
    """
    factor_id = body.get("factor_id", "").strip()
    name = body.get("name", "").strip()
    expression = body.get("expression", "").strip()
    category = body.get("category", "composite")
    description = body.get("description", "")

    if not factor_id or not name or not expression:
        raise HTTPException(status_code=400, detail="factor_id, name, expression 不能为空")

    # 自动解析标签 (基类/类型/方向), 用户显式提供时优先用用户值
    from lib.factor_engine import analyze_expression_tags
    tags = analyze_expression_tags(expression)
    direction = body.get("direction") or tags["direction"]
    base_id = body.get("base_id")
    if base_id is None:
        base_id = tags["base_id"]
    factor_type = body.get("factor_type") or tags["factor_type"]
    # 评价方式标签: 用户显式提供优先, 未提供时用表达式推断值(technical/signal/financial)
    evaluation_type = body.get("evaluation_type") or tags["factor_type"]

    # 保存到 factor_library
    fid = upsert_factor({
        "factor_id": factor_id,
        "name": name,
        "category": category,
        "direction": direction,
        "formula": expression,
        "description": description,
        "data_source": "日K",
        "origin": "用户自定义",
        "is_custom": True,
        "base_id": base_id,
        "factor_type": factor_type,
        "evaluation_type": evaluation_type,
    })

    # 清理项: 移除 factor_composite 双写 (审计确认 list_composite_factors 前端从未调用,
    # 全部功能读 factor_library; 表与查询函数保留不删以免破坏既有兼容, 仅不再冗余写入)

    return {"ok": True, "factor_id": fid, "tags": tags, "base_id": base_id,
            "factor_type": factor_type, "direction": direction,
            "evaluation_type": evaluation_type}




@router.post("/evaluation_type")
def set_factor_evaluation_type(body: Dict[str, Any] = Body(...)):
    """修改因子评价方式标签 (路由入口显式维护; evaluation_type 传 null 表示清除, 回退公式规则自动推断)

    body: { factor_id: str, evaluation_type: "technical"|"technical_ts"|"signal"|"financial"|"none"|null }
    """
    factor_id = body.get("factor_id", "").strip()
    if not factor_id:
        raise HTTPException(status_code=400, detail="factor_id 不能为空")
    et = body.get("evaluation_type")
    if et is not None:
        et = str(et).strip().lower()
        if et not in ("technical", "technical_ts", "signal", "financial", "none"):
            raise HTTPException(status_code=400, detail=(
                f"非法 evaluation_type: {et}, 可选 technical/technical_ts/signal/financial/none"))
    try:
        ok = update_evaluation_type(factor_id, et)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"因子 {factor_id} 不存在")
    return {"ok": True, "factor_id": factor_id, "evaluation_type": et}


# ============================================================
# Tab 3: 因子挖掘
# ============================================================
