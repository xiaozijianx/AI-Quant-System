# -*- coding: utf-8 -*-
# 龙头战法路由 -- 候选名单 + 一键加入监控池 (薄路由)
"""
GET  /api/dragon/candidates    -- 拉今日龙头候选
POST /api/dragon/bind          -- 一键把候选写入 watch_pool + strategies.per_stock=dragon_picker

业务逻辑已下沉 services/dragon/ (Stage 2 路由瘦身), 本文件只做参数绑定与返回。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query

from services.dragon import build_candidates, bind_candidates

router = APIRouter()


@router.get("/candidates")
def candidates(
    source: str = Query("auto", description="auto / mysql / xtdata / mock"),
    use_xtdata: int = Query(0, description="(旧) 1=等价 source=xtdata"),
    min_change: float = Query(0.05),
    max_price: float = Query(30.0),
    min_vol_ratio: float = Query(2.0),
    require_resonance: int = Query(-1,
        description="v2 板块共振: 1=开 0=关 -1=按 source 自动 (mysql/mock 开, xtdata 关)"),
):
    """返回最近一个真实交易日的龙头候选名单 (按 dragon_score 降序, v2 含板块共振字段)."""
    return build_candidates(
        source=source,
        use_xtdata=use_xtdata,
        min_change=min_change,
        max_price=max_price,
        min_vol_ratio=min_vol_ratio,
        require_resonance=require_resonance,
    )


@router.post("/bind")
def bind(payload: Optional[Dict[str, Any]] = Body(None)):
    """一键把若干候选股加入 watch_pool, 并把策略绑定到 dragon_picker (热加载)"""
    payload = payload or {}
    raw_codes = payload.get("codes") or []
    return bind_candidates(raw_codes)