# -*- coding: utf-8 -*-
# 因子库页面路由
"""
GET  /api/factor/categories          -- 因子分类列表
GET  /api/factor/list                -- 因子列表 (支持筛选)
GET  /api/factor/detail/{factor_id}  -- 因子详情
GET  /api/factor/operators           -- 可用算子列表
GET  /api/factor/fields              -- 可用字段列表
POST /api/factor/save                -- 保存自定义因子
POST /api/factor/evaluate            -- 评价因子 (IC/分层回测)
POST /api/factor/trial               -- 因子表达式试计算 + 合理性诊断 (构建页校验/试算)
POST /api/factor/mine_svd            -- SVD 隐因子挖掘
POST /api/factor/mine_ml             -- ML 因子训练
POST /api/factor/init                -- 初始化因子库
DELETE /api/factor/{factor_id}       -- 删除因子
# 已删除的死代码路由: /construct(旧表达式试算), /generate(基类生成), /multi_factor_eval(旧多因子评价, 被 multi_prep/multi_synth 取代), /synthesize(旧组合优化, 被 multi_prep/multi_synth 取代)
# 引擎函数 run_multi_factor_eval/synth_multi_factor_eval 保留在 lib/factor_engine.py
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

# ============================================================
# JSON 安全清洗 (返回结果中若含 inf/-inf/NaN, Starlette JSONResponse
# 以 allow_nan=False 序列化时会抛 "Out of range float values are not
# JSON compliant", 统一在接口返回前递归替换为非有限浮点为 None)
# ============================================================
import math
from functools import wraps
import numpy as np


def _json_safe(obj):
    """递归清洗: 把 inf/-inf/NaN 浮点替换为 None, 保证 JSON 序列化合规"""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, np.floating):
        f = float(obj)
        return None if not math.isfinite(f) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _json_safe_response(f):
    """响应清洗装饰器: 函数返回前递归替换非有限浮点为 None"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return _json_safe(f(*args, **kwargs))
    return wrapper


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
# Tab 1: 因子库
# ============================================================

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

@router.post("/mine_svd")
def mine_svd_factors(body: Dict[str, Any] = Body(...)):
    """
    SVD 隐因子挖掘
    来源: CASE-QuantStats/2-SVD因子挖掘与分析.py

    body: {
        stock_codes: [...],
        start_date: "2024-01-01",
        end_date: "2025-12-31",
        n_factors: 5
    }
    """
    import numpy as np
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2025-12-31")
    n_factors = body.get("n_factors", 5)
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    # 支持股票池类型 (修复: 原实现只收 stock_codes, 页面直达时无池可用)
    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception:
            pass

    # 股票不足 30 只时, 自动补足活跃股, 保证 SVD 截面分析有效
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
    for code in stock_codes[:100]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > 60:
                panel[code] = df
        except Exception:
            pass

    if len(panel) < 10:
        raise HTTPException(status_code=400, detail=f"有效股票数据不足10只 (当前 {len(panel)} 只)")

    # 构建收益率矩阵 (index=日期, columns=股票)
    returns_df = pd.DataFrame({code: df["close"].pct_change() for code, df in panel.items()})
    returns_df = returns_df.dropna(how="all").fillna(0)

    # 去均值
    returns_mean = returns_df.mean(axis=1)
    R = returns_df.sub(returns_mean, axis=0)

    # SVD 分解
    U, s, Vt = np.linalg.svd(R.values, full_matrices=False)

    # 奇异值衰减
    total_var = (s ** 2).sum()
    cumvar = np.cumsum(s ** 2) / total_var

    # 取前 n_factors 个隐因子
    n = min(n_factors, len(s))
    factors = {}
    for i in range(n):
        exposure = Vt[i]  # 每只股票在该因子上的暴露
        factors[f"svd_factor_{i+1}"] = {
            "singular_value": float(s[i]),
            "variance_explained": float(s[i] ** 2 / total_var),
            "cumulative_variance": float(cumvar[i]),
            "exposure": {code: float(exposure[j]) for j, code in enumerate(returns_df.columns)},
        }

    # ---- 隐因子时序: 因子取值 = U * S (每期各隐因子的状态/载荷) ----
    dates = list(returns_df.index)
    factor_ts = []
    for i in range(n):
        ts = U[:, i] * s[i]
        factor_ts.append({
            "name": f"svd_factor_{i+1}",
            "dates": [str(d)[:10] for d in dates],
            "values": [float(v) for v in ts],
        })

    # ---- 残差分析: 前 n 因子重构收益率, 残差占总方差比例 (越小说明隐因子解释越充分) ----
    R_hat = (U[:, :n] * s[:n]) @ Vt[:n, :]
    residual = R.values - R_hat
    denom = float((R.values ** 2).sum()) or 1e-12
    residual_var_ratio = float((residual ** 2).sum() / denom)
    residual = {
        "residual_var_ratio": round(residual_var_ratio, 6),
        "residual_std": float(np.std(residual)),
        "explained_var_ratio": round(1.0 - residual_var_ratio, 6),
    }

    # ---- 滚动SVD: 区间分 3 段, 每段重做 SVD, 看隐因子结构(前n因子方差占比)是否随时间稳定 ----
    n_dates = len(dates)
    seg_idx = [0, n_dates // 3, 2 * n_dates // 3, n_dates]
    rolling = []
    for k in range(3):
        a, b = seg_idx[k], seg_idx[k + 1]
        if b - a < 2:
            continue
        Rs = R.values[a:b]
        ss = np.linalg.svd(Rs, full_matrices=False)[1]
        tv = float((ss ** 2).sum()) or 1e-12
        cum = np.cumsum(ss ** 2) / tv
        rolling.append({
            "start": str(dates[a])[:10],
            "end": str(dates[b - 1])[:10],
            "top_var": [round(float(ss[i] ** 2 / tv), 6) for i in range(min(n, len(ss)))],
            "top_cum": [round(float(cum[i]), 6) for i in range(min(n, len(cum)))],
        })

    return {
        "n_stocks": len(panel),
        "n_dates": len(returns_df),
        "total_factors_available": len(s),
        "factors": factors,
        "factor_ts": factor_ts,
        "residual": residual,
        "rolling": rolling,
        "variance_curve": [{"index": i, "singular_value": float(s[i]),
                            "cumulative": float(cumvar[i])} for i in range(min(20, len(s)))],
    }


@router.post("/mine_ml")
def mine_ml_factors(body: Dict[str, Any] = Body(...)):
    """
    ML 因子训练 (XGBoost 特征重要性)
    来源: CASE-AI量化系统/ml_strategy/feature_engine.py

    body: {
        stock_codes: [...],
        start_date: "2024-01-01",
        end_date: "2025-12-31",
        target: "forward_return_5d"
    }
    """
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2025-12-31")
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    # 支持股票池类型 (修复: 原实现只收 stock_codes, 页面直达时无池可用)
    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception:
            pass

    # 股票不足 30 只时, 自动补足活跃股, 保证 ML 样本足够
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

    # 收集因子矩阵
    records = []
    for code in stock_codes[:100]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is None or len(df) < 130:
                continue
            # 目标: 未来5日收益
            # 修复: 原实现取 iloc[-1]/iloc[-5]-1 (过去5日收益) 当标签, 即用 t 时刻特征
            #       预测 t 之前已发生的收益, 方向性错误且样本内R²虚高; 现改为:
            #       特征取 t 时刻快照(切片去掉最后5日, 快照点 t = len-6),
            #       标签 = close[t+5]/close[t]-1 = 从 t 往后的5日收益, 方向正确。
            if len(df) > 5:
                feat_df = df.iloc[:-5]                  # 特征时点 t (保证 t+5 在样本内)
                factors = calc_basic_factors(feat_df)
                if not factors:
                    continue
                future_ret = df["close"].iloc[-1] / df["close"].iloc[-6] - 1
                factors["_target"] = float(future_ret)
                factors["_code"] = code
                records.append(factors)
        except Exception:
            pass

    if len(records) < 20:
        raise HTTPException(status_code=400, detail="有效样本不足20条")

    df_records = pd.DataFrame(records)
    target = df_records["_target"]
    features = df_records.drop(columns=["_target", "_code"])

    # XGBoost 训练
    try:
        from xgboost import XGBRegressor
        model = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1)
        model.fit(features, target)
        importance = dict(zip(features.columns, model.feature_importances_))
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
    except ImportError:
        from sklearn.ensemble import RandomForestRegressor
        model = RandomForestRegressor(n_estimators=50, max_depth=4)
        model.fit(features, target)
        importance = dict(zip(features.columns, model.feature_importances_))
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

    return {
        "n_samples": len(records),
        "n_features": len(features.columns),
        "feature_importance": {k: float(v) for k, v in importance.items()},
        "r2_score": float(model.score(features, target)),
    }


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


# ============================================================
# Tab 3.7: RL 因子挖掘 (阶段6.1, 独立引擎, 深度复刻 AlphaMaster)
# ============================================================

@router.post("/mine_rl/stream")
def mine_rl_factors_stream(body: Dict[str, Any] = Body(...)):
    """RL 强化学习因子挖掘 (SSE 流式版, 深度复刻 AlphaMaster)

    事件类型: heartbeat / progress / restart / elite / done / error
      - progress: 每训练步推送 (step/train_steps/best_score/avg_reward/entropy)
      - restart:  熵坍塌重启时推送
      - elite:    精英池状态 (每 100 步)
      - done:     完整结果 (候选 + 训练曲线)
      - error:    异常
    """
    q: "queue.Queue" = queue.Queue()

    def _progress_cb(step: int, stats: Dict[str, Any]) -> None:
        try:
            q.put(("progress", stats))
            from lib.factor_mining_jobs import publish
            publish("rl", "progress", stats)
        except Exception:
            pass

    def _restart_cb(step: int, info: Dict[str, Any]) -> None:
        try:
            q.put(("restart", {"step": step, **info}))
            from lib.factor_mining_jobs import publish
            publish("rl", "restart", {"step": step, **info})
        except Exception:
            pass

    def _elite_cb(step: int, info: Dict[str, Any]) -> None:
        try:
            q.put(("elite", {"step": step, **info}))
            from lib.factor_mining_jobs import publish
            publish("rl", "elite", {"step": step, **info})
        except Exception:
            pass

    def _run() -> None:
        try:
            from lib.factor_mining_jobs import start_job, finish_job
            start_job("rl")
            from lib.factor_rl.pipeline import run_rl_pipeline
            result = run_rl_pipeline(dict(body), progress_cb=_progress_cb,
                                     restart_cb=_restart_cb, elite_cb=_elite_cb)
            # 结果暂存后端 (eval_type=mining, eval_key=rl): 页面切换/关闭后回来可恢复
            try:
                save_eval_result("mining", "rl", result, {
                    "pool_type": body.get("pool_type", ""),
                    "pool_ref": body.get("pool_ref", ""),
                    "method": "rl",
                    "start_date": body.get("start_date", ""),
                    "end_date": body.get("end_date", ""),
                    "rebal_period": body.get("rebal_period", 5),
                })
            except Exception:
                pass
            finish_job("rl", result)
            q.put(("done", result))
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            from lib.factor_mining_jobs import finish_job as _f
            _f("rl", None, detail)
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
            elif kind == "restart":
                yield {"event": "restart", "data": json.dumps(payload)}
            elif kind == "elite":
                yield {"event": "elite", "data": json.dumps(payload)}
            elif kind == "done":
                yield {"event": "done", "data": json.dumps(_json_safe(payload))}
                break
            elif kind == "error":
                yield {"event": "error", "data": json.dumps(payload)}
                break

    return EventSourceResponse(_event_gen())

@router.get("/mining/status")
def factor_mining_status(kind: str = ""):
    """查询后台挖掘任务状态 (GP/RL/LLM增强GP 实时续接)

    页面切换/关闭后，后台线程继续跑；重开页面轮询此接口即可拿到：
      - status: running / done / error
      - progress / result / error / history(最近事件流)
    未来新增挖掘子页只需在 stream 路由里 start_job/publish/finish_job 即可复用。
    """
    from lib.factor_mining_jobs import get_status
    if not kind:
        return {"found": False, "error": "缺少 kind (gp/rl/llm_gp)"}
    st = get_status(kind)
    if st is None:
        return {"found": False}
    return {"found": True, "job": st}


@router.get("/llm_gp/config")
def get_llm_gp_config():
    """读取 LLM 增强 GP 独立大模型配置 (factor_llm_config 表, 单行 id=1)

    独立存储, 与 AI 助手 providers.yaml 完全隔离, 互不读取/互不覆盖。
    api_key 返回掩码 (仅尾4位), 未配置时返回 {configured: false}。
    """
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
    """保存 LLM 增强 GP 独立大模型配置 (factor_llm_config 表, UPSERT 单行 id=1)

    api_key 传空串/掩码值时保留库内原值 (便于只改模型不动密钥)。
    返回掩码后的配置, 供前端回显。
    """
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

