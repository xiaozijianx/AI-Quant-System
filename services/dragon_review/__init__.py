# -*- coding: utf-8 -*-
"""services/dragon_review/ -- 龙头复盘业务层编排.

由 routes/dragon_review.py 瘦身迁移 (Stage 2)。路由只做参数解析与返回,
业务编排 (矩阵构建 / 个股详情 / 页码定位 / 可用日期) 统一在本模块导出。
对外 API 契约 (4 个端点) 不变。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 常量 (路由 Query 默认值用)
from services.dragon_review.defaults import (  # noqa: F401
    TOP_N,
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
    DEFAULT_SECTOR_COUNT_WEIGHT,
    DEFAULT_SECTOR_RATIO_WEIGHT,
    DEFAULT_SECTOR_CHANGE_WEIGHT,
    DEFAULT_SECTOR_AMOUNT_WEIGHT,
    DEFAULT_SECTOR_AMOUNT_RATIO_WEIGHT,
    DEFAULT_CONCEPT_COUNT_WEIGHT,
    DEFAULT_CONCEPT_RATIO_WEIGHT,
    DEFAULT_CONCEPT_CHANGE_WEIGHT,
    DEFAULT_CONCEPT_AMOUNT_WEIGHT,
    DEFAULT_CONCEPT_AMOUNT_RATIO_WEIGHT,
    DEFAULT_CONCEPT_MIN_LIMIT_UP,
    DEFAULT_CONCEPT_MIN_STOCK_COUNT,
    DEFAULT_LEADER_STRENGTH_WEIGHT,
    DEFAULT_LEADER_AMOUNT_WEIGHT,
    DEFAULT_LEADER_TURNOVER_WEIGHT,
    DEFAULT_LEADER_POSITION_WEIGHT,
    DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT,
    DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT,
)

# 工具
from services.dragon_review.query import (  # noqa: F401
    _clean_nan,
    _parse_weights,
    _split_concepts,
    _to_float,
    execute_query,
)
# 业务
from services.dragon_review.matrix import _build_matrix  # noqa: F401
from services.dragon_review.query import (  # noqa: F401
    _get_available_dates as _get_available_dates,
    _get_page_for_date as _get_page_for_date,
)
from lib.stock_quote import load_quote
from lib.stock_utils import get_stock_info, normalize_code


# ============================================================
# 端点编排 (路由层只做参数绑定与返回)
# ============================================================

def build_matrix(
    days: int = 5,
    end_date: Optional[str] = None,
    ma_days: int = DEFAULT_VOLUME_MA_DAYS,
    volume_ratio_ma: float = DEFAULT_VOLUME_RATIO_MA,
    volume_ratio_ring: float = DEFAULT_VOLUME_RATIO_RING,
    max_limit_down: int = DEFAULT_MAX_LIMIT_DOWN,
    min_up_down_ratio: float = DEFAULT_MIN_UP_DOWN_RATIO,
    min_rise_ratio: float = DEFAULT_MIN_RISE_RATIO,
    sector_short_lookback: int = DEFAULT_SECTOR_SHORT_LOOKBACK,
    sector_short_return_pct: float = DEFAULT_SECTOR_SHORT_RETURN_PCT,
    sector_long_lookback: int = DEFAULT_SECTOR_LONG_LOOKBACK,
    sector_long_return_pct: float = DEFAULT_SECTOR_LONG_RETURN_PCT,
    sector_max_board_level: int = DEFAULT_SECTOR_MAX_BOARD_LEVEL,
    concept_short_lookback: int = DEFAULT_CONCEPT_SHORT_LOOKBACK,
    concept_short_return_pct: float = DEFAULT_CONCEPT_SHORT_RETURN_PCT,
    concept_long_lookback: int = DEFAULT_CONCEPT_LONG_LOOKBACK,
    concept_long_return_pct: float = DEFAULT_CONCEPT_LONG_RETURN_PCT,
    concept_max_board_level: int = DEFAULT_CONCEPT_MAX_BOARD_LEVEL,
    stock_gain_days: int = DEFAULT_STOCK_GAIN_DAYS,
    stock_gain_limit: float = DEFAULT_STOCK_GAIN_LIMIT,
    amount_weight: float = DEFAULT_AMOUNT_WEIGHT,
    volume_up_weight: float = DEFAULT_VOLUME_UP_WEIGHT,
    concept_similarity_threshold: float = DEFAULT_CONCEPT_SIMILARITY_THRESHOLD,
    sector_weights: Optional[List[float]] = None,
    concept_weights: Optional[List[float]] = None,
    concept_min_limit_up: int = DEFAULT_CONCEPT_MIN_LIMIT_UP,
    concept_min_stock_count: int = DEFAULT_CONCEPT_MIN_STOCK_COUNT,
    leader_weights: Optional[List[float]] = None,
    sector_relevance_weight: float = DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT,
    concept_relevance_weight: float = DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT,
) -> Dict[str, Any]:
    """构建每日龙头复盘矩阵 (异常统一返回 {ok:False, message})."""
    try:
        data = _build_matrix(
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
            sector_weights=sector_weights,
            concept_weights=concept_weights,
            concept_min_limit_up=concept_min_limit_up,
            concept_min_stock_count=concept_min_stock_count,
            leader_weights=leader_weights,
            sector_relevance_weight=sector_relevance_weight,
            concept_relevance_weight=concept_relevance_weight,
        )
        return _clean_nan({"ok": True, **data})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


def get_page_for_date(target_date: str, page_size: int = 5) -> Dict[str, Any]:
    """根据目标日期返回所在的页码."""
    try:
        page = _get_page_for_date(target_date, page_size=page_size)
        return _clean_nan({"ok": True, "page": page})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


def get_stock_detail(code: str, date: str) -> Dict[str, Any]:
    """返回个股基础信息 + 近 30 个交易日简单 K 线 + 近期涨停记录."""
    norm = normalize_code(code)
    if not norm:
        return {"ok": False, "message": "股票代码无效"}

    # 基础信息
    info = get_stock_info(norm)

    # 近 1 年日 K，前端只取最后 30 根
    quote = load_quote(norm, timeframe="daily", years=1)
    if quote and quote.get("ok"):
        # 把最新价/涨跌幅/成交额等行情字段合并到 info，方便前端直接展示
        info.update(quote.get("info", {}))
    else:
        quote = None

    # 近期涨停记录
    rows = execute_query(
        """
        SELECT trade_date, consecutive_days, change_pct, sector_2, concepts
        FROM dragon_limit_up_daily
        WHERE stock_code = %s
        ORDER BY trade_date DESC
        LIMIT 20
        """,
        (norm,),
    )
    limit_up_history = []
    for r in rows:
        limit_up_history.append({
            "date": str(r["trade_date"]),
            "consecutive_days": int(r["consecutive_days"]) if r["consecutive_days"] else 1,
            "change_pct": _to_float(r["change_pct"]),
            "sector_2": r["sector_2"] or "",
            "concepts": _split_concepts(r["concepts"]),
        })

    return _clean_nan({
        "ok": True,
        "code": norm,
        "date": date,
        "info": info,
        "quote": quote,
        "limit_up_history": limit_up_history,
    })


def get_available_dates(days: int = 60) -> Dict[str, Any]:
    """返回 dragon_limit_up_daily 中已有的最近 N 个交易日."""
    return {"dates": _get_available_dates(days=days)}