# -*- coding: utf-8 -*-
# 晨会分析路由 -- REST + SSE (薄路由)
"""
GET  /api/morning/cache         -- 读最近一次缓存
GET  /api/morning/stock-detail  -- 个股可解释性详情
GET  /api/morning/stream?...    -- SSE 流式跑工作流, 推送进度

业务逻辑已下沉 services/morning/ (Stage 2 路由瘦身), 本文件只做参数绑定与返回。
"""

from fastapi import APIRouter, Query

from services.morning import (
    load_latest_cache,
    get_stock_detail,
    stream_response,
)

router = APIRouter()


@router.get("/cache")
def get_cache():
    """读最近一次晨会缓存"""
    return load_latest_cache()


@router.get("/stock-detail")
def stock_detail(
    code: str = Query(..., description="股票代码"),
    top_industries: int = Query(3, ge=1, le=10),
    top_concepts: int = Query(3, ge=1, le=10),
    sample_per_industry: int = Query(15, ge=5, le=50),
    lookback: int = Query(90, ge=60, le=250),
):
    """
    返回某只推荐股票的详细可解释性信息：
    - 基本信息
    - 所属强相关板块/概念
    - 工作流中计算的因子原始值与标准化得分
    - 分组得分与选中原因
    """
    return get_stock_detail(
        code=code,
        top_industries=top_industries,
        top_concepts=top_concepts,
        sample_per_industry=sample_per_industry,
        lookback=lookback,
    )


@router.get("/stream")
async def stream(
    top_industries: int = Query(3),
    top_concepts: int = Query(3),
    top_stocks: int = Query(5),
    sample_per_industry: int = Query(15),
    lookback: int = Query(90),
    package_id: str = Query(""),
):
    """SSE 流式触发晨会, 边跑边推中间状态"""
    return await stream_response(
        top_industries=top_industries,
        top_concepts=top_concepts,
        top_stocks=top_stocks,
        sample_per_industry=sample_per_industry,
        lookback=lookback,
        package_id=package_id,
    )