# -*- coding: utf-8 -*-
# 个股行情路由
"""
GET /api/stock-quote/search      股票搜索
GET /api/stock-quote/quote       K 线行情（含 MACD）
GET /api/stock-quote/financial   财务数据
GET /api/stock-quote/news        新闻舆情
GET /api/stock-quote/consensus   研报一致性预期
"""

from __future__ import annotations

import math
from typing import List, Dict, Any

from fastapi import APIRouter, Query

from lib.paths import setup_sys_path
setup_sys_path()

from lib.stock_quote import load_quote, load_financial, load_news, load_consensus
from lib.stock_utils import search_stocks

router = APIRouter()


def _clean_nan(obj: Any) -> Any:
    """递归把 NaN/Inf/-Inf 转成 None，保证 JSON 合法。"""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


@router.get("/search")
def stock_search(
    q: str = Query(..., description="搜索关键词：代码或名称"),
    limit: int = Query(15, ge=1, le=50, description="最大返回条数")
):
    """按代码或名称模糊搜索股票。"""
    try:
        results = search_stocks(q, limit)
        return _clean_nan({"ok": True, "query": q, "results": results})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


@router.get("/quote")
def stock_quote(
    code: str = Query(..., description="股票代码"),
    timeframe: str = Query("daily", description="周期: daily/weekly/monthly"),
    years: int = Query(3, ge=1, le=10, description="查询年限（日线默认 1 年，周线/月线按密度放大）")
):
    """返回指定周期的 K 线、成交量、MACD 等行情数据。"""
    try:
        result = load_quote(code, timeframe=timeframe, years=years)
        return _clean_nan(result)
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


@router.get("/financial")
def stock_financial(
    code: str = Query(..., description="股票代码"),
    limit: int = Query(8, ge=1, le=50, description="返回期数")
):
    """返回个股季度财务数据。"""
    try:
        items = load_financial(code, limit)
        return _clean_nan({"ok": True, "code": code, "items": items})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


@router.get("/news")
def stock_news(
    code: str = Query(..., description="股票代码"),
    limit: int = Query(20, ge=1, le=50, description="返回条数")
):
    """返回个股新闻舆情。"""
    try:
        items = load_news(code, limit)
        return _clean_nan({"ok": True, "code": code, "items": items})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


@router.get("/consensus")
def stock_consensus(
    code: str = Query(..., description="股票代码"),
    limit: int = Query(20, ge=1, le=50, description="返回条数")
):
    """返回研报一致性预期。"""
    try:
        items = load_consensus(code, limit)
        return _clean_nan({"ok": True, "code": code, "items": items})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})
