# -*- coding: utf-8 -*-
"""龙头复盘矩阵/标签/候选股构建 (自 routes/dragon_review.py 迁移, 逻辑逐字不变)."""
from __future__ import annotations

import math
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from lib.stock_intraday import load_intraday_summaries

from services.dragon_review.defaults import (
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
from services.dragon_review.query import (
    _to_float,
    _is_main_board,
    _parse_break_label,
    _split_concepts,
    _pct_rank,
    _percentile_sorted,
    _compute_composite_scores,
    _get_available_dates,
    _get_market_overview,
    _get_sector_scores,
    _get_concept_scores,
    _get_board2_sectors,
    _get_board2_concepts,
    _get_board_stocks,
    _get_break_stocks,
    _get_candidate_pool_amounts,
    _get_all_limit_up_amounts,
    _get_sector_max_board,
    _get_concept_max_board,
    _get_stock_amount_history,
    _get_stock_close_history,
    _get_stock_turnover_history,
    _get_concept_codes,
    _get_sector_level1_mapping,
    _get_concept_similarity,
    _get_prev_day_break_info,
    _normalize_weights,
    execute_query,
)

# ============================================================
# 矩阵构建
# ============================================================

def _names(items: List[Dict]) -> Set[str]:
    return {x["name"] for x in items}


def _hot_tags_for_stock(
    stock: Dict,
    hot_sectors: Set[str],
    hot_concepts: Set[str],
) -> List[str]:
    """返回个股命中的热门板块/概念标签列表。"""
    tags = []
    if stock["sector_2"] and stock["sector_2"] in hot_sectors:
        tags.append(stock["sector_2"])
    for c in stock["concepts"]:
        if c in hot_concepts:
            tags.append(c)
    return tags


def _tag_leader_entities(
    entities: List[Dict],
    trade_date: str,
    all_dates: List[str],
    idx_in_all: int,
    prev_entities: Optional[List[Dict]],
    level1_map: Optional[Dict[str, str]],
    rank_history: Dict[Tuple[str, str], int],
    max_board_map: Dict[Tuple[str, str], int],
    entity_close_history: Dict[Tuple[str, str], float],
    short_lookback: int,
    short_return_pct: float,
    long_lookback: int,
    long_return_pct: float,
    max_board_level: int,
    entity_type: str,
    concept_similarity: Optional[Dict[Tuple[str, str], float]] = None,
    concept_similarity_threshold: float = DEFAULT_CONCEPT_SIMILARITY_THRESHOLD,
) -> List[Dict]:
    """给每个龙头板块/概念打上标签：is_low、relation_type。

    - is_low: 短窗涨幅 < short_return_pct 且 长窗涨幅 < long_return_pct，
              且当日板块/概念内最高连板 <= max_board_level
      短窗判断"近期是否急涨"，长窗判断"是否之前涨了很多、近期只是小幅回调"，
      两者同时满足才是真正的低位。
    - relation_type:
        * sector: 与昨日龙头板块是否同一申万一级（inner=主线内发散，cross=跨主线）
        * concept: 与昨日龙头概念亲密度是否 >= DEFAULT_CONCEPT_SIMILARITY
    """
    if prev_entities is None:
        prev_entities = []

    # 昨日龙头实体的一级方向 / 亲密概念集合
    prev_level1_set: Set[str] = set()
    prev_concept_set: Set[str] = set()
    if entity_type == "sector" and level1_map:
        prev_level1_set = {
            level1_map.get(e["name"], "") for e in prev_entities
            if level1_map.get(e["name"])
        }
    elif entity_type == "concept":
        prev_concept_set = {e["name"] for e in prev_entities}

    def _calc_return(name: str, lookback: int) -> Optional[float]:
        """计算近 lookback 个交易日的累计涨幅。

        返回值含义：
        - float: 正常计算出的累计涨幅(%)
        - None: 历史 close_idx 缺失（源表无该日期或该实体数据），
          表示客观无数据，无法判断高位/低位，调用方应标记为"无数据"状态。
        """
        hist_idx = max(0, idx_in_all - lookback)
        hist_date = all_dates[hist_idx]
        prev_close = entity_close_history.get((hist_date, name))
        today_close = entity_close_history.get((trade_date, name))
        # 任一端缺失（None）或为非正值时，返回 None 表示无数据
        if prev_close is None or today_close is None or prev_close <= 0 or today_close <= 0:
            return None
        return (today_close / prev_close - 1) * 100

    result = []
    for e in entities:
        name = e["name"]

        short_ret = _calc_return(name, short_lookback)
        long_ret = _calc_return(name, long_lookback)

        # 无数据判断：短窗或长窗任一端缺失历史数据，标记为"无数据"
        has_no_data = short_ret is None or long_ret is None

        if has_no_data:
            # 无数据：既不是低位也不是高位，不纳入候选股推荐范围
            is_low = False
            data_status = "no_data"
            short_ret_display = None
            long_ret_display = None
        else:
            # 低位判断：短窗涨幅和长窗涨幅均未超限，且最高连板未超限
            is_low = (
                short_ret < short_return_pct
                and long_ret < long_return_pct
                and max_board_map.get((trade_date, name), 0) <= max_board_level
            )
            data_status = "low" if is_low else "high"
            short_ret_display = round(short_ret, 2)
            long_ret_display = round(long_ret, 2)

        # 关系类型：基于与昨日龙头实体的相似度
        if entity_type == "sector" and level1_map:
            level1 = level1_map.get(name, "")
            if level1 and level1 in prev_level1_set:
                relation_type = "inner"
            else:
                relation_type = "cross"
        elif entity_type == "concept" and concept_similarity is not None:
            is_inner = False
            for prev_name in prev_concept_set:
                if concept_similarity.get((name, prev_name), 0.0) >= concept_similarity_threshold:
                    is_inner = True
                    break
            relation_type = "inner" if is_inner else "cross"
        else:
            relation_type = "cross"

        result.append({
            **e,
            "is_low": is_low,
            "data_status": data_status,
            "relation_type": relation_type,
            "max_board": max_board_map.get((trade_date, name), 0),
            "short_return_pct": short_ret_display,
            "long_return_pct": long_ret_display,
        })
    return result


def _build_matrix(
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
    """构建每日龙头复盘矩阵。

    为保证计算所需历史数据，会额外多取历史交易日作为数据窗口。
    参数:
        days:                       回溯显示的交易日数
        end_date:                   截止日期（YYYY-MM-DD），不传则取最新交易日
        ma_days:                    放量判断所用的成交额均线天数
        volume_ratio_ma:            成交额相对均线的放量倍数阈值
        volume_ratio_ring:          成交额相对昨日的环比放量倍数阈值
        max_limit_down:             大盘情绪过滤：最大允许跌停家数
        min_up_down_ratio:          大盘情绪过滤：最小涨跌停比
        min_rise_ratio:             大盘情绪过滤：最小上涨家数占比
        sector_short_lookback:      板块短窗：看近 N 日累计涨幅
        sector_short_return_pct:    板块短窗：累计涨幅超过该百分比视为不在低位
        sector_long_lookback:       板块长窗：看近 N 日累计涨幅
        sector_long_return_pct:     板块长窗：累计涨幅超过该百分比视为不在低位
        sector_max_board_level:     板块内最高连板不超过 N 板
        concept_short_lookback:     概念短窗：看近 N 日累计涨幅
        concept_short_return_pct:   概念短窗：累计涨幅超过该百分比视为不在低位
        concept_long_lookback:      概念长窗：看近 N 日累计涨幅
        concept_long_return_pct:    概念长窗：累计涨幅超过该百分比视为不在低位
        concept_max_board_level:    概念内最高连板不超过 N 板
        stock_gain_days:            个股低位判断：近 N 日涨幅
        stock_gain_limit:           个股低位判断：涨幅不超过该百分比
        amount_weight:              量能分中成交量分权重（0~1），放量分权重 = 1 - amount_weight
        volume_up_weight:           兼容保留，实际未使用
        sector_weights:             板块 5 维权重 [涨停率, 涨停数量, 平均涨幅, 人均成交额, 成交额环比]
        concept_weights:            概念 5 维权重 [涨停率, 涨停数量, 平均涨幅, 人均成交额, 成交额环比]
        concept_min_limit_up:       概念硬门槛：最少涨停家数
        concept_min_stock_count:    概念硬门槛：最少成分股数
        leader_weights:             龙头股 4 维权重 [涨停强度, 量能强度, 换手健康, 位置安全]
        sector_relevance_weight:    龙头股与板块相关性权重
        concept_relevance_weight:   龙头股与概念相关性权重
    """
    t0 = time.time()
    max_price_lookback = max(sector_short_lookback, sector_long_lookback,
                             concept_short_lookback, concept_long_lookback)
    history_days = max(ma_days, max_price_lookback, stock_gain_days, 30)
    # 先取足够多的历史日期，确定 end_date 位置后再切片
    all_dates = _get_available_dates(days=days + history_days + 60)
    t1 = time.time()
    if not all_dates:
        return {"dates": [], "rows": [], "has_more": False}

    # 确定截止日期在 all_dates 中的索引（all_dates 升序）
    if end_date and end_date in all_dates:
        end_idx = all_dates.index(end_date)
    elif end_date:
        # 取不大于 end_date 的最近交易日
        end_idx = None
        for i in range(len(all_dates) - 1, -1, -1):
            if all_dates[i] <= end_date:
                end_idx = i
                break
        if end_idx is None:
            end_idx = len(all_dates) - 1
    else:
        end_idx = len(all_dates) - 1

    start_idx = max(0, end_idx - days + 1)
    display_dates = all_dates[start_idx:end_idx + 1]
    if not display_dates:
        return {"dates": [], "rows": [], "has_more": False}

    # 数据窗口：当前显示日期再往前多取 history_days，用于均线/涨幅计算
    total_available = len(all_dates)
    window_start_idx = max(0, start_idx - history_days)
    all_dates = all_dates[window_start_idx:end_idx + 1]

    # 参数兜底
    sector_weights = sector_weights or [
        DEFAULT_SECTOR_RATIO_WEIGHT,
        DEFAULT_SECTOR_COUNT_WEIGHT,
        DEFAULT_SECTOR_CHANGE_WEIGHT,
        DEFAULT_SECTOR_AMOUNT_WEIGHT,
        DEFAULT_SECTOR_AMOUNT_RATIO_WEIGHT,
    ]
    concept_weights = concept_weights or [
        DEFAULT_CONCEPT_RATIO_WEIGHT,
        DEFAULT_CONCEPT_COUNT_WEIGHT,
        DEFAULT_CONCEPT_CHANGE_WEIGHT,
        DEFAULT_CONCEPT_AMOUNT_WEIGHT,
        DEFAULT_CONCEPT_AMOUNT_RATIO_WEIGHT,
    ]

    # 并行查询第一组：市场成交额/指数、情绪、板块/概念/个股基础数据
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_get_market_overview, all_dates): "market_overview",
            executor.submit(_get_sector_scores, all_dates, sector_weights): "sector_scores",
            executor.submit(_get_concept_scores, all_dates, concept_weights,
                            concept_min_limit_up, concept_min_stock_count): "concept_scores",
            executor.submit(_get_board2_sectors, all_dates): "board2_sectors",
            executor.submit(_get_board2_concepts, all_dates): "board2_concepts",
            executor.submit(_get_board_stocks, all_dates): "board_stocks",
            executor.submit(_get_break_stocks, all_dates): "break_stocks",
            executor.submit(_get_candidate_pool_amounts, all_dates): "candidate_pool_amounts",
            executor.submit(_get_all_limit_up_amounts, all_dates): "all_limit_up_amounts",
        }
        results = {}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()
        market_amounts, market_index_changes, market_sentiment = results["market_overview"]
        leader_sectors, sector_rank_history, sector_close_history = results["sector_scores"]
        leader_concepts, concept_rank_history, concept_close_history = results["concept_scores"]
        board2_sectors = results["board2_sectors"]
        board2_concepts = results["board2_concepts"]
        board_stocks = results["board_stocks"]
        break_stocks = results["break_stocks"]
        candidate_pool_amounts = results["candidate_pool_amounts"]
        all_limit_up_amounts = results["all_limit_up_amounts"]
    t2 = time.time()

    # 并行查询第二组：板块最高连板、成分股成交额/收盘价
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_get_sector_max_board, all_dates): "sector_max_board",
            executor.submit(_get_concept_max_board, all_dates): "concept_max_board",
            executor.submit(_get_stock_amount_history, all_dates): "stock_amount_history",
            executor.submit(_get_stock_close_history, all_dates): "stock_close_history",
            executor.submit(_get_stock_turnover_history, all_dates): "stock_turnover_history",
        }
        results = {}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()
        sector_max_board = results["sector_max_board"]
        concept_max_board = results["concept_max_board"]
        stock_amount_history = results["stock_amount_history"]
        stock_close_history = results["stock_close_history"]
        stock_turnover_history = results["stock_turnover_history"]

    # 为所有概念名补编码（含龙头概念和二板概念）
    all_concept_names: Set[str] = set()
    for items in leader_concepts.values():
        all_concept_names.update(x["name"] for x in items)
    for items in board2_concepts.values():
        all_concept_names.update(x["name"] for x in items)

    # 二级板块 -> 申万一级映射（用于判断跨主线 / 主线内发散）
    all_sector_names: Set[str] = set()
    for items in leader_sectors.values():
        all_sector_names.update(x["name"] for x in items)
    for items in board2_sectors.values():
        all_sector_names.update(x["name"] for x in items)

    # 概念编码、板块映射、概念亲密度三者互相独立，可并行
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_get_concept_codes, all_concept_names): "concept_code_map",
            executor.submit(_get_sector_level1_mapping, all_sector_names): "sector_level1_map",
            executor.submit(_get_concept_similarity, all_concept_names, concept_similarity_threshold): "concept_similarity",
        }
        results = {}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()
        concept_code_map = results["concept_code_map"]
        sector_level1_map = results["sector_level1_map"]
        concept_similarity = results["concept_similarity"]
    t3 = time.time()

    # 断板股前一天的信息（用于判断是否是旧龙头阵营退潮）
    prev_dates = []
    all_break_codes: Set[str] = set()
    for i, d in enumerate(display_dates):
        # 展示窗口第一天，仍可用 all_dates 中的上一个交易日作为“前一天”
        if i == 0:
            idx_in_all = all_dates.index(d)
            prev = all_dates[idx_in_all - 1] if idx_in_all > 0 else None
        else:
            prev = display_dates[i - 1]
        codes = [s["code"] for s in break_stocks.get(d, [])]
        if prev and codes:
            prev_dates.append(prev)
            all_break_codes.update(codes)
    prev_info = _get_prev_day_break_info(prev_dates, all_break_codes)

    rows = []
    for i, d in enumerate(display_dates):
        idx_in_all = all_dates.index(d)

        # 成交额与放量判断：用 all_dates 计算配置天数的均线，避免随页码变化
        amount = market_amounts.get(d, 0.0)
        window = [market_amounts.get(all_dates[j], 0.0) for j in range(max(0, idx_in_all - ma_days + 1), idx_in_all + 1)]
        avg_ma = sum(window) / len(window) if window else 0.0
        prev_amount = market_amounts.get(all_dates[idx_in_all - 1], 0.0) if idx_in_all > 0 else 0.0
        index_change = market_index_changes.get(d, 0.0)
        sentiment = market_sentiment.get(d, {})
        limit_down = sentiment.get("limit_down", 0)
        up_down_ratio = sentiment.get("up_down_ratio", 0.0)
        rise_ratio = sentiment.get("rise_ratio", 0.0)
        # 放量必须满足：均线放量、环比放量、大盘指数当日上涨、市场情绪健康
        is_volume_up = (
            avg_ma > 0 and amount > avg_ma * volume_ratio_ma
            and prev_amount > 0 and amount > prev_amount * volume_ratio_ring
            and index_change > 0
            and limit_down <= max_limit_down
            and up_down_ratio >= min_up_down_ratio
            and rise_ratio >= min_rise_ratio
        )

        # 当天热门集合
        ls = leader_sectors.get(d, [])
        lc = leader_concepts.get(d, [])
        b2s = board2_sectors.get(d, [])
        b2c = board2_concepts.get(d, [])
        hot_sectors = _names(ls) | _names(b2s)
        hot_concepts = _names(lc) | _names(b2c)

        # 热门集合划分：断板股只看昨日龙头板块/概念。
        prev_date = all_dates[idx_in_all - 1] if idx_in_all > 0 else None

        prev_hot_sectors_break: Set[str] = set()
        prev_hot_concepts_break: Set[str] = set()
        if prev_date:
            prev_hot_sectors_break = _names(leader_sectors.get(prev_date, []))
            prev_hot_concepts_break = _names(leader_concepts.get(prev_date, []))

        prev_entities_sectors = leader_sectors.get(prev_date, []) if prev_date else []
        prev_entities_concepts = leader_concepts.get(prev_date, []) if prev_date else []

        # 高标股加热门标签
        bs = board_stocks.get(d, {"board3": [], "board4": [], "board5plus": []})
        board3, board4, board5plus = [], [], []
        for stock in bs["board3"]:
            tags = _hot_tags_for_stock(stock, hot_sectors, hot_concepts)
            board3.append({**stock, "hot_tags": tags, "is_hot": bool(tags)})
        for stock in bs["board4"]:
            tags = _hot_tags_for_stock(stock, hot_sectors, hot_concepts)
            board4.append({**stock, "hot_tags": tags, "is_hot": bool(tags)})
        for stock in bs["board5plus"]:
            tags = _hot_tags_for_stock(stock, hot_sectors, hot_concepts)
            board5plus.append({**stock, "hot_tags": tags, "is_hot": bool(tags)})

        # 断板股：全部显示，前一天属于昨日龙头集合的标亮并写出命中标签
        breaks = []
        for s in break_stocks.get(d, []):
            info = prev_info.get((prev_date, s["code"])) if prev_date else None
            hot_tags = []
            if info:
                if info["sector_2"] and info["sector_2"] in prev_hot_sectors_break:
                    hot_tags.append(info["sector_2"])
                for c in info["concepts"]:
                    if c in prev_hot_concepts_break:
                        hot_tags.append(c)
            breaks.append({**s, "is_hot": bool(hot_tags), "hot_tags": hot_tags})

        # 给每个龙头板块/概念打标签：高/低、内/跨
        ls_tagged = _tag_leader_entities(
            ls, d, all_dates, idx_in_all,
            prev_entities_sectors,
            sector_level1_map, sector_rank_history, sector_max_board,
            sector_close_history,
            sector_short_lookback, sector_short_return_pct,
            sector_long_lookback, sector_long_return_pct,
            sector_max_board_level,
            entity_type="sector",
        )
        lc_tagged = _tag_leader_entities(
            lc, d, all_dates, idx_in_all,
            prev_entities_concepts,
            None, concept_rank_history, concept_max_board,
            concept_close_history,
            concept_short_lookback, concept_short_return_pct,
            concept_long_lookback, concept_long_return_pct,
            concept_max_board_level,
            entity_type="concept",
            concept_similarity=concept_similarity,
            concept_similarity_threshold=concept_similarity_threshold,
        )

        # 轮动信号：大盘放量 且 出现强势且不高位的板块/概念
        # 断板股保留在界面中显示，但不作为轮动信号的触发条件
        # 候选股从「强势且不高位的板块/概念」中选取，且个股本身处于低位
        candidates: List[Dict] = []
        has_low_entity = any(e.get("is_low") for e in ls_tagged + lc_tagged)
        is_rotation_signal = is_volume_up and has_low_entity
        if is_rotation_signal and has_low_entity and prev_date:
            candidates = _build_candidates(
                d, ls_tagged, lc_tagged,
                candidate_pool_amounts.get(d, []),
                all_limit_up_amounts.get(d, []),
                stock_amount_history, stock_close_history, stock_turnover_history,
                all_dates, idx_in_all,
                stock_gain_days, stock_gain_limit,
                amount_weight, volume_up_weight,
                leader_weights=leader_weights,
                sector_relevance_weight=sector_relevance_weight,
                concept_relevance_weight=concept_relevance_weight,
            )

        # 给概念补上编码，方便前端点击；优先用 concept_meta，没有则保留原表编码
        lc_with_code = []
        for item in lc_tagged:
            code = concept_code_map.get(item["name"]) or item.get("code", "")
            lc_with_code.append({**item, "code": code})
        b2c_with_code = []
        for item in b2c:
            code = concept_code_map.get(item["name"]) or item.get("code", "")
            b2c_with_code.append({**item, "code": code})

        rows.append({
            "date": d,
            "market_amount": amount,
            "market_amount_avg_ma": avg_ma,
            "market_index_change": index_change,
            "is_volume_up": is_volume_up,
            "is_rotation_signal": is_rotation_signal,
            "leader_sectors": ls_tagged,
            "leader_concepts": lc_with_code,
            "board2_sectors": b2s,
            "board2_concepts": b2c_with_code,
            "board3": board3,
            "board4": board4,
            "board5plus": board5plus,
            "break_stocks": breaks,
            "candidates": candidates,
        })

    # has_more 表示是否还能继续往更早的日期回溯
    has_more = start_idx > 0
    t4 = time.time()
    print(f"[dragon-review] matrix days={days} end_date={display_dates[-1] if display_dates else None} "
          f"dates_query={t1-t0:.3f}s market={t2-t1:.3f}s "
          f"others={t3-t2:.3f}s build={t4-t3:.3f}s total={t4-t0:.3f}s",
          flush=True)
    # 页面展示按从新到旧排列（最上面是截止日期，越往下越早）
    return {"dates": display_dates[::-1], "rows": rows[::-1], "has_more": has_more}


def _calc_stock_gain_pct(
    code: str,
    trade_date: str,
    gain_days: int,
    stock_close_history: Dict[Tuple[str, str], float],
    all_dates: List[str],
    idx_in_all: int,
) -> Optional[float]:
    """计算个股近 gain_days 个交易日涨幅（当前相对之前）。"""
    prev_idx = idx_in_all - gain_days
    if prev_idx < 0:
        return None
    close_now = stock_close_history.get((trade_date, code))
    close_prev = stock_close_history.get((all_dates[prev_idx], code))
    if not close_now or not close_prev or close_prev == 0:
        return None
    return (close_now - close_prev) / close_prev * 100.0


def _calc_stock_volume_up_ratio(
    code: str,
    trade_date: str,
    stock_amount_history: Dict[Tuple[str, str], float],
    all_dates: List[str],
    idx_in_all: int,
    ma_days: int = 5,
) -> Optional[float]:
    """计算个股今日成交额相对过去 ma_days 日均额的放量倍数。"""
    today_amount = stock_amount_history.get((trade_date, code))
    if not today_amount:
        return None
    window_amounts = []
    for j in range(max(0, idx_in_all - ma_days), idx_in_all):
        d = all_dates[j]
        a = stock_amount_history.get((d, code))
        if a:
            window_amounts.append(a)
    if not window_amounts:
        return None
    avg = sum(window_amounts) / len(window_amounts)
    if avg == 0:
        return None
    return today_amount / avg


def _load_relevance_scores(
    trade_date: str,
    sectors: List[str],
    concepts: List[str],
    stock_codes: List[str],
) -> Dict[Tuple[str, str, str], float]:
    """
    批量加载股票与板块/概念的相关性分数。

    返回: {(entity_type, entity_name, stock_code): total_score}
        entity_type 为 "sector" 或 "concept"
    """
    result: Dict[Tuple[str, str, str], float] = {}
    if not stock_codes:
        return result

    d = date.fromisoformat(trade_date)

    # 1) 板块相关性 (sector_stock_relevance)
    if sectors:
        ph_sectors = ",".join(["%s"] * len(sectors))
        ph_stocks = ",".join(["%s"] * len(stock_codes))
        rows = execute_query(
            f"""
            SELECT sector_name, stock_code, total_score
            FROM sector_stock_relevance
            WHERE sector_name IN ({ph_sectors})
              AND sector_level = 2
              AND stock_code IN ({ph_stocks})
              AND calc_date = (
                  SELECT MAX(calc_date) FROM sector_stock_relevance
                  WHERE calc_date <= %s
              )
            """,
            list(sectors) + list(stock_codes) + [d],
        )
        for r in rows:
            score = _to_float(r["total_score"])
            if score is not None:
                result[("sector", r["sector_name"], r["stock_code"])] = score

    # 2) 概念相关性 (concept_stock_relevance)
    if concepts:
        ph_concepts = ",".join(["%s"] * len(concepts))
        ph_stocks = ",".join(["%s"] * len(stock_codes))
        rows = execute_query(
            f"""
            SELECT concept_name, stock_code, total_score
            FROM concept_stock_relevance
            WHERE concept_name IN ({ph_concepts})
              AND stock_code IN ({ph_stocks})
              AND calc_date = (
                  SELECT MAX(calc_date) FROM concept_stock_relevance
                  WHERE calc_date <= %s
              )
            """,
            list(concepts) + list(stock_codes) + [d],
        )
        for r in rows:
            score = _to_float(r["total_score"])
            if score is not None:
                result[("concept", r["concept_name"], r["stock_code"])] = score

    return result


def _map_relevance_score(raw_relevance: Optional[float]) -> float:
    """
    把原始相关性分数映射为 [0, 1] 的梯度分。

    映射规则：
        raw >= 0.7  -> 1.0
        raw >= 0.6  -> 0.7
        raw >= 0.5  -> 0.5
        raw >= 0.4  -> 0.3
        raw <  0.4  -> 0.1   （含无记录情况，视为相关性低于门槛）

    这样可以把常见的 0.4~0.8 区间拉开区分度，
    同时给低于门槛或无记录的股票一个最小基础分，避免完全归零。
    """
    if raw_relevance is None:
        return 0.1
    if raw_relevance >= 0.7:
        return 1.0
    if raw_relevance >= 0.6:
        return 0.7
    if raw_relevance >= 0.5:
        return 0.5
    if raw_relevance >= 0.4:
        return 0.3
    return 0.1


def _build_candidates(
    trade_date: str,
    leader_sectors: List[Dict],
    leader_concepts: List[Dict],
    candidate_pool_stocks: List[Dict],
    all_limit_up_amounts: List[float],
    stock_amount_history: Dict[Tuple[str, str], float],
    stock_close_history: Dict[Tuple[str, str], float],
    stock_turnover_history: Dict[Tuple[str, str], float],
    all_dates: List[str],
    idx_in_all: int,
    stock_gain_days: int,
    stock_gain_limit: float,
    amount_weight: float,
    volume_up_weight: float,
    leader_weights: Optional[List[float]] = None,
    sector_relevance_weight: float = DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT,
    concept_relevance_weight: float = DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT,
) -> List[Dict]:
    """为每个「强势且处于低位」的龙头板块/概念选出低位启动个股。

    候选股池为首板 + 二板股票。个股先经过近 N 日涨幅过滤，
    再按龙头股 5 维打分（涨停强度、量能强度、换手健康、位置安全、相关性）
    加权综合排序取 Top 3。其中相关性维度按梯度映射，并与前 4 维一起归一化。
    最后按个股去重聚合，在标签中展示该股票命中的所有来源。
    """
    base_weights = _normalize_weights(leader_weights or [
        DEFAULT_LEADER_STRENGTH_WEIGHT,
        DEFAULT_LEADER_AMOUNT_WEIGHT,
        DEFAULT_LEADER_TURNOVER_WEIGHT,
        DEFAULT_LEADER_POSITION_WEIGHT,
    ])

    # 预加载所有候选股与相关板块/概念的相关性分数
    sector_names = [e["name"] for e in leader_sectors if e.get("is_low")]
    concept_names = [e["name"] for e in leader_concepts if e.get("is_low")]
    candidate_codes = [s["code"] for s in candidate_pool_stocks]
    relevance_map = _load_relevance_scores(
        trade_date, sector_names, concept_names, candidate_codes)

    stock_map: Dict[str, Dict] = {}

    def _add_stock(stock: Dict, source_name: str, source_type: str) -> None:
        code = stock["code"]
        if code not in stock_map:
            stock_map[code] = {
                "code": code,
                "name": stock["name"],
                "amount": _to_float(stock.get("amount", 0)) or 0.0,
                "volume_up_ratio": stock.get("volume_up_ratio"),
                "gain_pct": stock.get("gain_pct"),
                "score": stock.get("score", 0.0),
                "leader_score_detail": stock.get("leader_score_detail"),
                "sources": [],
            }
        exists = any(
            s["name"] == source_name and s["type"] == source_type
            for s in stock_map[code]["sources"]
        )
        if not exists:
            stock_map[code]["sources"].append({"name": source_name, "type": source_type})

    def _score_strength(summary: Dict[str, Any]) -> float:
        """涨停强度分：板型 + 首次涨停时间 − 炸板扣分。"""
        if not summary.get("is_limit_up"):
            return 0.0
        limit_type = summary.get("limit_up_type", "")
        if limit_type == "一字板":
            base = 0.9
        elif limit_type == "T字板":
            base = 0.8
        elif limit_type == "实体板":
            base = 0.7
        elif limit_type == "烂板":
            base = 0.4
        else:
            base = 0.2

        # 首次涨停时间越早越好
        first_time = summary.get("first_limit_time")
        time_bonus = 0.0
        if first_time:
            try:
                minutes = first_time.hour * 60 + first_time.minute
                if minutes <= 570:        # 09:30 之前（集合竞价）
                    time_bonus = 0.1
                elif minutes <= 580:      # 09:40 之前
                    time_bonus = 0.08
                elif minutes <= 600:      # 10:00 之前
                    time_bonus = 0.05
                elif minutes <= 630:      # 10:30 之前
                    time_bonus = 0.02
            except Exception:
                pass

        # 炸板扣分：每次 0.1，最多扣 0.3
        break_count = summary.get("break_count", 0) or 0
        break_penalty = min(break_count * 0.1, 0.3)

        return max(0.0, min(1.0, base + time_bonus - break_penalty))

    def _score_absolute_amount(amount: float, all_limit_up_amounts: List[float]) -> float:
        """成交量分：全部涨停股 p5/p95 对数单调映射，成交额越大越高。"""
        if amount <= 0 or not all_limit_up_amounts:
            return 0.0
        vals = sorted(all_limit_up_amounts)
        lo = _percentile_sorted(vals, 0.05)
        hi = _percentile_sorted(vals, 0.95)
        if hi <= lo:
            return 1.0 if amount >= hi else 0.0
        if amount <= lo:
            return 0.0
        if amount >= hi:
            return 1.0
        return (math.log(amount) - math.log(lo)) / (math.log(hi) - math.log(lo))

    def _score_volume_ratio(volume_up_ratio: Optional[float]) -> float:
        """放量分：1.3~2.0 最佳，1.0~1.3 次之，缩量/过大量低分。"""
        if volume_up_ratio is None:
            return 0.5
        if volume_up_ratio < 1.0:
            return 0.4
        if volume_up_ratio < 1.3:
            return 0.75
        if volume_up_ratio <= 2.0:
            return 1.0
        if volume_up_ratio <= 3.0:
            return 0.7
        return 0.4

    def _score_amount(
        amount: float,
        all_limit_up_amounts: List[float],
        volume_up_ratio: Optional[float],
        amount_weight: float,
    ) -> float:
        """量能强度分：amount_weight × 成交量分 + (1-amount_weight) × 放量分。"""
        w = max(0.0, min(1.0, amount_weight))
        return w * _score_absolute_amount(amount, all_limit_up_amounts) + (1.0 - w) * _score_volume_ratio(volume_up_ratio)

    def _score_turnover(turnover_rate: Optional[float]) -> float:
        """换手健康分：4%~12% 最佳，过高或过低都扣分。"""
        if turnover_rate is None:
            return 0.5
        tr = float(turnover_rate)
        if 4.0 <= tr <= 12.0:
            return 1.0
        if 12.0 < tr <= 20.0:
            return 0.7
        if tr > 20.0:
            return 0.4
        if 1.0 <= tr < 4.0:
            return 0.7
        return 0.4

    def _score_position(gain_pct: Optional[float], stock_gain_limit: float) -> float:
        """位置安全分：近 N 日涨幅越小越好。"""
        if gain_pct is None:
            return 0.5
        if gain_pct <= 5.0:
            return 1.0
        if gain_pct <= stock_gain_limit:
            return 1.0 - (gain_pct - 5.0) / max(stock_gain_limit - 5.0, 1.0) * 0.5
        return 0.0

    def _pick_stocks(entity_name: str, entity_type: str, matcher) -> None:
        # 只从「强势且低位」的实体里选股
        entity = None
        pool = leader_sectors if entity_type == "sector" else leader_concepts
        for e in pool:
            if e["name"] == entity_name:
                entity = e
                break
        if not entity or not entity.get("is_low"):
            return

        stocks = [s for s in candidate_pool_stocks if _is_main_board(s["code"]) and matcher(s)]
        if not stocks:
            return

        # 为每只股票补充成交额、放量、涨幅、换手率
        enriched = []
        for s in stocks:
            code = s["code"]
            amount = _to_float(s.get("amount", 0)) or 0.0
            volume_up = _calc_stock_volume_up_ratio(
                code, trade_date, stock_amount_history, all_dates, idx_in_all
            )
            gain = _calc_stock_gain_pct(
                code, trade_date, stock_gain_days, stock_close_history, all_dates, idx_in_all
            )
            turnover_rate = stock_turnover_history.get((trade_date, code))
            enriched.append({
                **s,
                "amount": amount,
                "volume_up_ratio": volume_up,
                "gain_pct": gain,
                "turnover_rate": turnover_rate,
            })

        # 过滤涨幅超过阈值的个股（没有涨幅数据则保留）
        filtered = [
            s for s in enriched
            if s["gain_pct"] is None or s["gain_pct"] <= stock_gain_limit
        ]
        if not filtered:
            return

        # 批量获取日内关键数据
        codes = [s["code"] for s in filtered]
        intraday_map = load_intraday_summaries(codes, trade_date)

        # 5 维打分：强/量/换/位 + 相关性，5 维权重复合在一起归一化
        relevance_weight = sector_relevance_weight if entity_type == "sector" else concept_relevance_weight
        full_weights = _normalize_weights(base_weights + [relevance_weight])

        for s in filtered:
            code = s["code"]
            summary = intraday_map.get(code, {})
            if not summary:
                # 无日内数据时，仅使用日 K 信息构造一个最基础的摘要
                summary = {
                    "is_limit_up": True,
                    "limit_up_type": "实体板",
                    "first_limit_time": None,
                    "break_count": 0,
                }
            strength = _score_strength(summary)
            amount_score = _score_amount(
                s["amount"], all_limit_up_amounts, s.get("volume_up_ratio"), amount_weight
            )
            turnover = _score_turnover(s.get("turnover_rate"))
            position = _score_position(s["gain_pct"], stock_gain_limit)

            # 相关性：梯度映射到 [0, 1]
            rel_key = (entity_type, entity_name, code)
            raw_relevance = relevance_map.get(rel_key)
            relevance_score = _map_relevance_score(raw_relevance)

            s["score"] = (
                full_weights[0] * strength +
                full_weights[1] * amount_score +
                full_weights[2] * turnover +
                full_weights[3] * position +
                full_weights[4] * relevance_score
            )
            s["leader_score_detail"] = {
                "strength": round(strength, 3),
                "amount": round(amount_score, 3),
                "turnover": round(turnover, 3),
                "position": round(position, 3),
                "relevance": round(relevance_score, 3),
                "relevance_raw": round(raw_relevance, 3) if raw_relevance is not None else None,
            }

        filtered.sort(key=lambda x: -x["score"])
        seen: Set[str] = set()
        for s in filtered:
            if s["code"] in seen:
                continue
            seen.add(s["code"])
            _add_stock(s, entity_name, entity_type)
            if len(seen) >= TOP_N:
                break

    # 强势且低位的龙头板块
    for entity in leader_sectors:
        _pick_stocks(
            entity["name"], "sector",
            lambda s, name=entity["name"]: s.get("sector_2") == name
        )

    # 强势且低位的龙头概念
    for entity in leader_concepts:
        _pick_stocks(
            entity["name"], "concept",
            lambda s, name=entity["name"]: name in (s.get("concepts") or [])
        )

    # 按综合打分倒序，让最强势的个股靠前
    candidates = sorted(stock_map.values(), key=lambda x: -x["score"])
    return candidates


