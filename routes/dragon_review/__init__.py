# -*- coding: utf-8 -*-
"""龙头复盘页面 API (薄路由).

提供:
- GET /api/dragon-review/matrix        每日龙头复盘矩阵（一行一天）
- GET /api/dragon-review/page-for-date 目标日期所在页码
- GET /api/dragon-review/stock-detail  个股详情（含近 30 日 K 线）
- GET /api/dragon-review/available-dates  有数据的交易日

业务逻辑已下沉 services/dragon_review/ (Stage 2 路由瘦身), 本文件只做参数绑定与返回。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from services.dragon_review import (
    build_matrix,
    get_available_dates,
    get_page_for_date,
    get_stock_detail,
    _parse_weights,
    # 默认常量 (Query 默认值与权重解析缺省)
    DEFAULT_VOLUME_MA_DAYS,
    DEFAULT_VOLUME_RATIO_MA,
    DEFAULT_VOLUME_RATIO_RING,
    DEFAULT_MAX_LIMIT_DOWN,
    DEFAULT_MIN_UP_DOWN_RATIO,
    DEFAULT_MIN_RISE_RATIO,
    DEFAULT_SECTOR_SHORT_LOOKBACK,
    DEFAULT_SECTOR_SHORT_RETURN_PCT,
    DEFAULT_SECTOR_LONG_LOOKBACK,
    DEFAULT_SECTOR_LONG_RETURN_PCT,
    DEFAULT_SECTOR_MAX_BOARD_LEVEL,
    DEFAULT_CONCEPT_SHORT_LOOKBACK,
    DEFAULT_CONCEPT_SHORT_RETURN_PCT,
    DEFAULT_CONCEPT_LONG_LOOKBACK,
    DEFAULT_CONCEPT_LONG_RETURN_PCT,
    DEFAULT_CONCEPT_MAX_BOARD_LEVEL,
    DEFAULT_STOCK_GAIN_DAYS,
    DEFAULT_STOCK_GAIN_LIMIT,
    DEFAULT_AMOUNT_WEIGHT,
    DEFAULT_VOLUME_UP_WEIGHT,
    DEFAULT_CONCEPT_SIMILARITY_THRESHOLD,
    DEFAULT_CONCEPT_MIN_LIMIT_UP,
    DEFAULT_CONCEPT_MIN_STOCK_COUNT,
    DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT,
    DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT,
    DEFAULT_SECTOR_RATIO_WEIGHT,
    DEFAULT_SECTOR_COUNT_WEIGHT,
    DEFAULT_SECTOR_CHANGE_WEIGHT,
    DEFAULT_SECTOR_AMOUNT_WEIGHT,
    DEFAULT_SECTOR_AMOUNT_RATIO_WEIGHT,
    DEFAULT_CONCEPT_RATIO_WEIGHT,
    DEFAULT_CONCEPT_COUNT_WEIGHT,
    DEFAULT_CONCEPT_CHANGE_WEIGHT,
    DEFAULT_CONCEPT_AMOUNT_WEIGHT,
    DEFAULT_CONCEPT_AMOUNT_RATIO_WEIGHT,
    DEFAULT_LEADER_STRENGTH_WEIGHT,
    DEFAULT_LEADER_AMOUNT_WEIGHT,
    DEFAULT_LEADER_TURNOVER_WEIGHT,
    DEFAULT_LEADER_POSITION_WEIGHT,
)

router = APIRouter()


@router.get("/matrix")
def matrix(
    days: int = Query(5, ge=1, le=60),
    end_date: Optional[str] = Query(None, description="截止日期 YYYY-MM-DD，不传则取最新交易日"),
    ma_days: int = Query(DEFAULT_VOLUME_MA_DAYS, ge=5, le=60),
    volume_ratio_ma: float = Query(DEFAULT_VOLUME_RATIO_MA, ge=1.0, le=2.0),
    volume_ratio_ring: float = Query(DEFAULT_VOLUME_RATIO_RING, ge=1.0, le=2.0),
    max_limit_down: int = Query(DEFAULT_MAX_LIMIT_DOWN, ge=0, le=1000),
    min_up_down_ratio: float = Query(DEFAULT_MIN_UP_DOWN_RATIO, ge=0.0, le=50.0),
    min_rise_ratio: float = Query(DEFAULT_MIN_RISE_RATIO, ge=0.0, le=1.0),
    sector_short_lookback: int = Query(DEFAULT_SECTOR_SHORT_LOOKBACK, ge=1, le=60),
    sector_short_return_pct: float = Query(DEFAULT_SECTOR_SHORT_RETURN_PCT, ge=1.0, le=100.0),
    sector_long_lookback: int = Query(DEFAULT_SECTOR_LONG_LOOKBACK, ge=1, le=120),
    sector_long_return_pct: float = Query(DEFAULT_SECTOR_LONG_RETURN_PCT, ge=1.0, le=200.0),
    sector_max_board_level: int = Query(DEFAULT_SECTOR_MAX_BOARD_LEVEL, ge=1, le=10),
    concept_short_lookback: int = Query(DEFAULT_CONCEPT_SHORT_LOOKBACK, ge=1, le=60),
    concept_short_return_pct: float = Query(DEFAULT_CONCEPT_SHORT_RETURN_PCT, ge=1.0, le=100.0),
    concept_long_lookback: int = Query(DEFAULT_CONCEPT_LONG_LOOKBACK, ge=1, le=120),
    concept_long_return_pct: float = Query(DEFAULT_CONCEPT_LONG_RETURN_PCT, ge=1.0, le=200.0),
    concept_max_board_level: int = Query(DEFAULT_CONCEPT_MAX_BOARD_LEVEL, ge=1, le=10),
    stock_gain_days: int = Query(DEFAULT_STOCK_GAIN_DAYS, ge=1, le=30),
    stock_gain_limit: float = Query(DEFAULT_STOCK_GAIN_LIMIT, ge=0.0, le=100.0),
    amount_weight: float = Query(DEFAULT_AMOUNT_WEIGHT, ge=0.0, le=1.0),
    volume_up_weight: float = Query(DEFAULT_VOLUME_UP_WEIGHT, ge=0.0, le=1.0),
    concept_similarity_threshold: float = Query(DEFAULT_CONCEPT_SIMILARITY_THRESHOLD, ge=0.0, le=1.0),
    sector_weights: Optional[str] = Query(None, description="板块 5 维权重，逗号分隔：涨停率,涨停数量,平均涨幅,人均成交额,成交额环比"),
    concept_weights: Optional[str] = Query(None, description="概念 5 维权重，逗号分隔：涨停率,涨停数量,平均涨幅,人均成交额,成交额环比"),
    concept_min_limit_up: int = Query(DEFAULT_CONCEPT_MIN_LIMIT_UP, ge=0, le=50),
    concept_min_stock_count: int = Query(DEFAULT_CONCEPT_MIN_STOCK_COUNT, ge=1, le=1000),
    leader_weights: Optional[str] = Query(None, description="龙头股 4 维权重，逗号分隔：涨停强度,量能强度,换手健康,位置安全"),
    sector_relevance_weight: float = Query(DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT, ge=0.0, le=1.0),
    concept_relevance_weight: float = Query(DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT, ge=0.0, le=1.0),
):
    """返回每日龙头复盘矩阵（支持截止日期+回溯天数与放量/低位/概念亲密度参数配置）。"""
    sector_w = _parse_weights(sector_weights, [
        DEFAULT_SECTOR_RATIO_WEIGHT,
        DEFAULT_SECTOR_COUNT_WEIGHT,
        DEFAULT_SECTOR_CHANGE_WEIGHT,
        DEFAULT_SECTOR_AMOUNT_WEIGHT,
        DEFAULT_SECTOR_AMOUNT_RATIO_WEIGHT,
    ])
    concept_w = _parse_weights(concept_weights, [
        DEFAULT_CONCEPT_RATIO_WEIGHT,
        DEFAULT_CONCEPT_COUNT_WEIGHT,
        DEFAULT_CONCEPT_CHANGE_WEIGHT,
        DEFAULT_CONCEPT_AMOUNT_WEIGHT,
        DEFAULT_CONCEPT_AMOUNT_RATIO_WEIGHT,
    ])
    leader_w = _parse_weights(leader_weights, [
        DEFAULT_LEADER_STRENGTH_WEIGHT,
        DEFAULT_LEADER_AMOUNT_WEIGHT,
        DEFAULT_LEADER_TURNOVER_WEIGHT,
        DEFAULT_LEADER_POSITION_WEIGHT,
    ])
    return build_matrix(
        days=days, end_date=end_date,
        ma_days=ma_days,
        volume_ratio_ma=volume_ratio_ma,
        volume_ratio_ring=volume_ratio_ring,
        max_limit_down=max_limit_down,
        min_up_down_ratio=min_up_down_ratio,
        min_rise_ratio=min_rise_ratio,
        sector_short_lookback=sector_short_lookback,
        sector_short_return_pct=sector_short_return_pct,
        sector_long_lookback=sector_long_lookback,
        sector_long_return_pct=sector_long_return_pct,
        sector_max_board_level=sector_max_board_level,
        concept_short_lookback=concept_short_lookback,
        concept_short_return_pct=concept_short_return_pct,
        concept_long_lookback=concept_long_lookback,
        concept_long_return_pct=concept_long_return_pct,
        concept_max_board_level=concept_max_board_level,
        stock_gain_days=stock_gain_days,
        stock_gain_limit=stock_gain_limit,
        amount_weight=amount_weight,
        volume_up_weight=volume_up_weight,
        concept_similarity_threshold=concept_similarity_threshold,
        sector_weights=sector_w,
        concept_weights=concept_w,
        concept_min_limit_up=concept_min_limit_up,
        concept_min_stock_count=concept_min_stock_count,
        leader_weights=leader_w,
        sector_relevance_weight=sector_relevance_weight,
        concept_relevance_weight=concept_relevance_weight,
    )


@router.get("/page-for-date")
def page_for_date(
    date: str = Query(..., description="目标日期 YYYY-MM-DD"),
    page_size: int = Query(5, ge=1, le=60),
):
    """根据目标日期返回所在的页码，便于前端直接跳转。"""
    return get_page_for_date(target_date=date, page_size=page_size)


@router.get("/stock-detail")
def stock_detail(
    code: str = Query(..., description="股票代码"),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
):
    """返回个股基础信息 + 近 30 个交易日简单 K 线 + 近期涨停记录。"""
    return get_stock_detail(code=code, date=date)


@router.get("/available-dates")
def available_dates(days: int = Query(60, ge=1, le=250)):
    """返回 dragon_limit_up_daily 中已有的最近 N 个交易日。"""
    return get_available_dates(days=days)