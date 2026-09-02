# -*- coding: utf-8 -*-
"""龙头复盘数据库查询与数值工具 (自 routes/dragon_review.py 迁移, 逻辑逐字不变)."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from services.dragon_review.defaults import (
    A_STOCK_CONDITION,
    MARKET_INDEX_CODE,
    TOP_N,
    MAIN_BOARD_PREFIXES,
    DEFAULT_CONCEPT_SIMILARITY_THRESHOLD,
    DEFAULT_CONCEPT_MIN_LIMIT_UP,
    DEFAULT_CONCEPT_MIN_STOCK_COUNT,
)


def execute_query(sql, params=None):
    """数据库查询入口 (复用轮动引擎连接工具)."""
    from services.rotation.rotation_core import execute_query as _eq
    return _eq(sql, params)


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


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _is_main_board(stock_code: str) -> bool:
    """判断是否为主板股票（沪市/深市主板）。"""
    prefix = stock_code.split(".")[0]
    return prefix.startswith(MAIN_BOARD_PREFIXES)


def _parse_break_label(label: str) -> Optional[Dict[str, Any]]:
    """解析断板股票标签：code:name(N板) -> {code, name, prev_board}。"""
    label = label.strip()
    if not label:
        return None
    m = re.match(r"^([^:]+):(.+)\((\d+)板\)$", label)
    if m:
        return {
            "code": m.group(1).strip(),
            "name": m.group(2).strip(),
            "prev_board": int(m.group(3)),
        }
    # 兜底：按冒号切分
    parts = label.split(":", 1)
    if len(parts) == 2:
        return {"code": parts[0].strip(), "name": parts[1].strip(), "prev_board": None}
    return {"code": label, "name": label, "prev_board": None}


def _split_concepts(concepts_str: Optional[str]) -> List[str]:
    if not concepts_str:
        return []
    return [c.strip() for c in concepts_str.split(",") if c.strip()]


def _parse_weights(weights_str: Optional[str], default_weights: List[float]) -> List[float]:
    """把逗号分隔的权重字符串解析成浮点列表，缺失时用默认值补齐。"""
    if not weights_str:
        return list(default_weights)
    dim = len(default_weights)
    parts = [p.strip() for p in weights_str.split(",")]
    weights = []
    for p in parts[:dim]:
        try:
            weights.append(float(p))
        except Exception:
            weights.append(0.0)
    # 不足 dim 个补默认值
    while len(weights) < dim:
        weights.append(default_weights[len(weights)])
    return weights[:dim]


def _normalize_weights(weights: List[float]) -> List[float]:
    """权重归一化，使总和为 1；全为 0 时平均分配。"""
    total = sum(weights)
    dim = len(weights)
    if total <= 0:
        return [1.0 / dim] * dim
    return [w / total for w in weights]


def _pct_rank(values: List[float]) -> List[float]:
    """
    计算分位数排名（0 ~ 1），数值越大排名越高。
    返回与输入等长的列表。
    """
    if not values:
        return []
    n = len(values)
    if n == 1:
        return [0.5]
    sorted_idx = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    for rank, idx in enumerate(sorted_idx):
        ranks[idx] = rank / (n - 1)
    return ranks


def _percentile_sorted(values: List[float], p: float) -> float:
    """返回已排序列表的线性插值分位数（p 为 0~1）。"""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    k = (len(values) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(values[int(k)])
    return float(values[lo]) * (hi - k) + float(values[hi]) * (k - lo)


def _compute_composite_scores(
    items: List[Dict],
    weights: List[float],
    min_limit_up: Optional[int] = None,
    min_stock_count: Optional[int] = None,
) -> List[Dict]:
    """
    基于 5 个维度计算复合分数。

    输入 items 每个元素需包含：
        limit_up_count, stock_count, change_pct, amount_per_stock, amount_ratio
    输出每个元素增加：composite_score, composite_rank
    """
    if not items:
        return []

    # 硬门槛过滤
    filtered = []
    for it in items:
        if min_limit_up is not None and it.get("limit_up_count", 0) < min_limit_up:
            continue
        if min_stock_count is not None and it.get("stock_count", 0) < min_stock_count:
            continue
        filtered.append(it)

    if not filtered:
        return []

    # 分别计算 5 个维度的分位数
    count_vals = [it["limit_up_count"] for it in filtered]
    ratio_vals = [it["limit_up_count"] / max(it["stock_count"], 1) for it in filtered]
    change_vals = [it.get("change_pct") or 0.0 for it in filtered]
    amount_vals = [it.get("amount_per_stock") or 0.0 for it in filtered]
    amount_ratio_vals = [it.get("amount_ratio") or 1.0 for it in filtered]

    count_ranks = _pct_rank(count_vals)
    ratio_ranks = _pct_rank(ratio_vals)
    change_ranks = _pct_rank(change_vals)
    amount_ranks = _pct_rank(amount_vals)
    amount_ratio_ranks = _pct_rank(amount_ratio_vals)

    norm_weights = _normalize_weights(weights)
    for i, it in enumerate(filtered):
        it["composite_score"] = (
            norm_weights[0] * ratio_ranks[i]
            + norm_weights[1] * count_ranks[i]
            + norm_weights[2] * change_ranks[i]
            + norm_weights[3] * amount_ranks[i]
            + norm_weights[4] * amount_ratio_ranks[i]
        )

    # 按复合分降序，并写入 rank
    filtered.sort(key=lambda x: -x["composite_score"])
    for i, it in enumerate(filtered, 1):
        it["composite_rank"] = i
    return filtered


# ============================================================
# 数据库查询
# ============================================================

def _get_available_dates(days: int = 60) -> List[str]:
    """从 dragon_limit_up_daily 取最近 N 个交易日（升序）。"""
    rows = execute_query(
        """
        SELECT DISTINCT trade_date
        FROM dragon_limit_up_daily
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (days,),
    )
    return sorted(str(r["trade_date"]) for r in rows)


def _get_page_for_date(target_date: str, page_size: int = 5) -> int:
    """计算目标日期位于第几页（按最近交易日降序分页）。

    若目标日期不存在，返回距离最近日期的页码（优先向后取）。
    """
    rows = execute_query(
        """
        SELECT DISTINCT trade_date
        FROM dragon_limit_up_daily
        ORDER BY trade_date DESC
        """
    )
    if not rows:
        return 1
    dates = [str(r["trade_date"]) for r in rows]
    try:
        idx = dates.index(target_date)
    except ValueError:
        # 找到最近的后一个交易日（日期 <= target_date 的第一个）
        idx = None
        for i, d in enumerate(dates):
            if d <= target_date:
                idx = i
                break
        if idx is None:
            idx = 0
    return (idx // page_size) + 1


def _get_market_amounts(dates: List[str]) -> Dict[str, float]:
    """每日全 A 成交额（按代码规则识别全 A 股，排除指数、基金等，不依赖申万分类）。"""
    if not dates:
        return {}
    # 用区间查询替代 IN，更易命中 trade_date 索引
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        f"""
        SELECT trade_date, SUM(amount) AS total_amount
        FROM trade_stock_daily
        WHERE trade_date >= %s AND trade_date <= %s AND {A_STOCK_CONDITION}
        GROUP BY trade_date
        """,
        (start_date, end_date),
    )
    return {str(r["trade_date"]): _to_float(r["total_amount"]) or 0.0 for r in rows}


def _get_market_index_changes(dates: List[str]) -> Dict[str, float]:
    """每日大盘指数（默认上证指数）涨跌幅，用于放量时排除放量下跌的情况。"""
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT trade_date, close_price
        FROM trade_stock_daily
        WHERE stock_code = %s AND trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date ASC
        """,
        (MARKET_INDEX_CODE, start_date, end_date),
    )
    changes: Dict[str, float] = {}
    prev_close: Optional[float] = None
    for r in rows:
        d = str(r["trade_date"])
        close = _to_float(r["close_price"])
        if close is not None and prev_close is not None and prev_close != 0:
            changes[d] = (close - prev_close) / prev_close * 100.0
        else:
            changes[d] = 0.0
        if close is not None:
            prev_close = close
    return changes


def _get_market_sentiment(dates: List[str]) -> Dict[str, Dict[str, Any]]:
    """每日市场情绪统计：涨停家数、跌停家数、上涨家数、下跌家数。

    trade_stock_daily 没有 change_pct 字段，需用 close_price 相对昨日收盘价计算涨跌幅。
    返回 {date: {"limit_up": int, "limit_down": int, "rise": int, "fall": int, "up_down_ratio": float, "rise_ratio": float}}
    """
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)
    # 多取前一天，保证首日也能算涨跌幅
    query_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    rows = execute_query(
        f"""
        SELECT trade_date, stock_code, close_price
        FROM trade_stock_daily
        WHERE trade_date >= %s AND trade_date <= %s AND {A_STOCK_CONDITION}
        ORDER BY stock_code, trade_date ASC
        """,
        (query_start, end_date),
    )

    # 按股票分组计算每日涨跌幅
    by_date: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "limit_up": 0, "limit_down": 0, "rise": 0, "fall": 0
    })
    prev_close: Dict[str, float] = {}
    for r in rows:
        code = r["stock_code"]
        d = str(r["trade_date"])
        close = _to_float(r["close_price"])
        if close is None or close <= 0:
            continue
        prev = prev_close.get(code)
        if prev is not None and prev > 0:
            change_pct = (close - prev) / prev * 100.0
            if d >= start_date:
                if change_pct >= 9.7:
                    by_date[d]["limit_up"] += 1
                elif change_pct <= -9.7:
                    by_date[d]["limit_down"] += 1
                if change_pct > 0:
                    by_date[d]["rise"] += 1
                elif change_pct < 0:
                    by_date[d]["fall"] += 1
        prev_close[code] = close

    result: Dict[str, Dict[str, Any]] = {}
    for d in dates:
        stats = by_date.get(d, {"limit_up": 0, "limit_down": 0, "rise": 0, "fall": 0})
        limit_up = stats["limit_up"]
        limit_down = stats["limit_down"]
        rise = stats["rise"]
        fall = stats["fall"]
        total = rise + fall
        result[d] = {
            "limit_up": limit_up,
            "limit_down": limit_down,
            "rise": rise,
            "fall": fall,
            "up_down_ratio": (limit_up / max(limit_down, 1)),
            "rise_ratio": (rise / max(total, 1)),
        }
    return result


def _get_market_overview(dates: List[str]) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, Dict[str, Any]]]:
    """一次性获取市场成交额、指数涨跌、情绪统计。

    优先读预计算表 dragon_market_sentiment_daily；缺失时 fallback 到实时计算。
    返回: (market_amounts, market_index_changes, market_sentiment)
    """
    if not dates:
        return {}, {}, {}

    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT trade_date, total_amount, index_change_pct,
               limit_up_count, limit_down_count, rise_count, fall_count,
               up_down_ratio, rise_ratio
        FROM dragon_market_sentiment_daily
        WHERE trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date ASC
        """,
        (start_date, end_date),
    )

    if rows and len(rows) >= len(dates):
        # 预计算数据完整，直接使用
        market_amounts = {}
        market_index_changes = {}
        market_sentiment = {}
        for r in rows:
            d = str(r["trade_date"])
            market_amounts[d] = _to_float(r["total_amount"]) or 0.0
            market_index_changes[d] = _to_float(r["index_change_pct"]) or 0.0
            market_sentiment[d] = {
                "limit_up": int(r["limit_up_count"] or 0),
                "limit_down": int(r["limit_down_count"] or 0),
                "rise": int(r["rise_count"] or 0),
                "fall": int(r["fall_count"] or 0),
                "up_down_ratio": _to_float(r["up_down_ratio"]) or 0.0,
                "rise_ratio": _to_float(r["rise_ratio"]) or 0.0,
            }
        return market_amounts, market_index_changes, market_sentiment

    # fallback：按原逻辑实时计算
    return (
        _get_market_amounts(dates),
        _get_market_index_changes(dates),
        _get_market_sentiment(dates),
    )


def _get_sector_level1_mapping(sector_names: Set[str]) -> Dict[str, str]:
    """二级板块名 -> 申万一级板块名（从 dragon_limit_up_daily 历史记录取众数）。"""
    if not sector_names:
        return {}
    rows = execute_query(
        """
        SELECT sector_2, sector_1, COUNT(*) AS cnt
        FROM dragon_limit_up_daily
        WHERE sector_2 IN %s AND sector_1 IS NOT NULL AND sector_1 != ''
        GROUP BY sector_2, sector_1
        """,
        (tuple(sector_names),),
    )
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        counts[r["sector_2"]][r["sector_1"]] += int(r["cnt"])
    result = {}
    for sector_2, name_counts in counts.items():
        result[sector_2] = max(name_counts.items(), key=lambda x: x[1])[0]
    return result


def _get_sector_daily_stats(dates: List[str]) -> Dict[str, List[Dict]]:
    """取板块每日聚合统计。返回 {date: [stats, ...]}。

    优先读预计算表 dragon_sector_score_raw（已含 amount_per_stock / amount_ratio），
    缺失日期回退到源表 trade_sector_daily 实时计算，保证全板块涨幅对比的完整性。
    """
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)

    # 先读预计算表（含人均成交额与环比，无需再算）
    precomputed = execute_query(
        """
        SELECT trade_date, sector_name, close_idx, limit_up_count, stock_count,
               change_pct, amount_per_stock, amount_ratio
        FROM dragon_sector_score_raw
        WHERE trade_date >= %s AND trade_date <= %s
        """,
        (start_date, end_date),
    )
    result: Dict[str, List[Dict]] = defaultdict(list)
    covered_dates: Set[str] = set()
    for r in precomputed:
        d = str(r["trade_date"])
        covered_dates.add(d)
        result[d].append({
            "name": r["sector_name"],
            "limit_up_count": int(r["limit_up_count"] or 0),
            "stock_count": int(r["stock_count"] or 0),
            "change_pct": _to_float(r["change_pct"]) or 0.0,
            "close_idx": _to_float(r["close_idx"]) or 100.0,
            "amount_per_stock": _to_float(r["amount_per_stock"]) or 0.0,
            "amount_ratio": _to_float(r["amount_ratio"]) or 1.0,
        })

    # 预计算表缺失的日期，从源表实时计算补齐
    missing_dates = [d for d in dates if d not in covered_dates]
    if missing_dates:
        m_start, m_end = min(missing_dates), max(missing_dates)
        rows = execute_query(
            """
            SELECT trade_date, sector_name, change_pct, stock_count,
                   limit_up, total_amount, close_idx
            FROM trade_sector_daily
            WHERE sector_level = 2 AND trade_date >= %s AND trade_date <= %s
            """,
            (m_start, m_end),
        )
        fallback: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            fallback[str(r["trade_date"])].append({
                "name": r["sector_name"],
                "limit_up_count": int(r["limit_up"] or 0),
                "stock_count": int(r["stock_count"] or 0),
                "change_pct": _to_float(r["change_pct"]) or 0.0,
                "total_amount": _to_float(r["total_amount"]) or 0.0,
                "close_idx": _to_float(r["close_idx"]) or 100.0,
            })
        _compute_amount_ratio(fallback)
        for d, items in fallback.items():
            result[d] = items

    return dict(result)


def _get_concept_daily_stats(dates: List[str]) -> Dict[str, List[Dict]]:
    """取概念每日聚合统计。返回 {date: [stats, ...]}。

    优先读预计算表 dragon_concept_score_raw（已含 amount_per_stock / amount_ratio），
    缺失日期回退到源表 concept_daily_full 实时计算，保证全概念涨幅对比的完整性。
    """
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)

    # 先读预计算表（含人均成交额与环比，无需再算）
    precomputed = execute_query(
        """
        SELECT trade_date, concept_code, concept_name, close_idx, limit_up_count,
               stock_count, change_pct, amount_per_stock, amount_ratio
        FROM dragon_concept_score_raw
        WHERE trade_date >= %s AND trade_date <= %s
        """,
        (start_date, end_date),
    )
    result: Dict[str, List[Dict]] = defaultdict(list)
    covered_dates: Set[str] = set()
    for r in precomputed:
        d = str(r["trade_date"])
        covered_dates.add(d)
        result[d].append({
            "name": r["concept_name"],
            "code": r["concept_code"],
            "limit_up_count": int(r["limit_up_count"] or 0),
            "stock_count": int(r["stock_count"] or 0),
            "change_pct": _to_float(r["change_pct"]) or 0.0,
            "close_idx": _to_float(r["close_idx"]) or 100.0,
            "amount_per_stock": _to_float(r["amount_per_stock"]) or 0.0,
            "amount_ratio": _to_float(r["amount_ratio"]) or 1.0,
        })

    # 预计算表缺失的日期，从源表实时计算补齐
    missing_dates = [d for d in dates if d not in covered_dates]
    if missing_dates:
        m_start, m_end = min(missing_dates), max(missing_dates)
        rows = execute_query(
            """
            SELECT trade_date, concept_code, concept_name, change_pct, stock_count,
                   limit_up, total_amount, close_idx
            FROM concept_daily_full
            WHERE trade_date >= %s AND trade_date <= %s
            """,
            (m_start, m_end),
        )
        fallback: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            fallback[str(r["trade_date"])].append({
                "name": r["concept_name"],
                "code": r["concept_code"],
                "limit_up_count": int(r["limit_up"] or 0),
                "stock_count": int(r["stock_count"] or 0),
                "change_pct": _to_float(r["change_pct"]) or 0.0,
                "total_amount": _to_float(r["total_amount"]) or 0.0,
                "close_idx": _to_float(r["close_idx"]) or 100.0,
            })
        _compute_amount_ratio(fallback)
        for d, items in fallback.items():
            result[d] = items

    return dict(result)


def _compute_amount_ratio(items_by_date: Dict[str, List[Dict]]) -> None:
    """
    为每个 (date, entity) 计算成交额环比放大倍数：今日人均成交额 / 昨日人均成交额。
    直接在原数据结构上修改。
    """
    sorted_dates = sorted(items_by_date.keys())
    prev_by_name: Dict[str, float] = {}
    for d in sorted_dates:
        current_by_name: Dict[str, float] = {}
        for it in items_by_date[d]:
            sc = max(it["stock_count"], 1)
            amount_per_stock = it["total_amount"] / sc
            it["amount_per_stock"] = amount_per_stock
            prev_amount = prev_by_name.get(it["name"])
            if prev_amount and prev_amount > 0:
                it["amount_ratio"] = amount_per_stock / prev_amount
            else:
                it["amount_ratio"] = 1.0
            current_by_name[it["name"]] = amount_per_stock
        prev_by_name = current_by_name


def _get_sector_scores(
    dates: List[str],
    weights: List[float],
    top_n: int = TOP_N,
) -> Tuple[Dict[str, List[Dict]], Dict[Tuple[str, str], int], Dict[Tuple[str, str], float]]:
    """
    基于复合打分取每日板块龙头。
    返回: (leaders_by_date, rank_history, close_history)
    """
    if not dates:
        return {}, {}, {}
    stats_by_date = _get_sector_daily_stats(dates)

    leaders: Dict[str, List[Dict]] = {}
    rank_history: Dict[Tuple[str, str], int] = {}
    close_history: Dict[Tuple[str, str], float] = {}
    for d in dates:
        items = stats_by_date.get(d, [])
        # 先记录所有板块的 close_idx（不受打分过滤影响），确保涨幅计算有完整历史数据
        for it in items:
            close_history[(d, it["name"])] = it.get("close_idx", 100.0)
        scored = _compute_composite_scores(items, weights)
        leaders[d] = []
        for it in scored[:top_n]:
            leaders[d].append({
                "name": it["name"],
                "count": it["limit_up_count"],
                "type": "sector",
                "score": round(it["composite_score"], 4),
                "rank": it["composite_rank"],
            })
        for it in scored:
            rank_history[(d, it["name"])] = it["composite_rank"]
    return leaders, rank_history, close_history


def _get_concept_scores(
    dates: List[str],
    weights: List[float],
    min_limit_up: int = DEFAULT_CONCEPT_MIN_LIMIT_UP,
    min_stock_count: int = DEFAULT_CONCEPT_MIN_STOCK_COUNT,
    top_n: int = TOP_N,
) -> Tuple[Dict[str, List[Dict]], Dict[Tuple[str, str], int], Dict[Tuple[str, str], float]]:
    """
    基于复合打分取每日概念龙头，带硬门槛过滤。
    直接使用 concept_daily_full 的全量数据，不再依赖 dragon_concept_board_rank 兜底。
    返回: (leaders_by_date, rank_history, close_history)
    """
    if not dates:
        return {}, {}, {}
    stats_by_date = _get_concept_daily_stats(dates)

    leaders: Dict[str, List[Dict]] = {}
    rank_history: Dict[Tuple[str, str], int] = {}
    close_history: Dict[Tuple[str, str], float] = {}
    for d in dates:
        items = stats_by_date.get(d, [])
        # 先记录所有概念的 close_idx（不受硬门槛过滤影响），确保涨幅计算有完整历史数据
        for it in items:
            close_history[(d, it["name"])] = it.get("close_idx", 100.0)
        scored = _compute_composite_scores(
            items, weights,
            min_limit_up=min_limit_up,
            min_stock_count=min_stock_count,
        )
        leaders[d] = []
        for it in scored[:top_n]:
            leaders[d].append({
                "name": it["name"],
                "code": it.get("code", ""),
                "count": it["limit_up_count"],
                "type": "concept",
                "score": round(it["composite_score"], 4),
                "rank": it["composite_rank"],
            })
        for it in scored:
            rank_history[(d, it["name"])] = it["composite_rank"]
    return leaders, rank_history, close_history


def _get_sector_max_board(dates: List[str]) -> Dict[Tuple[str, str], int]:
    """每个二级板块每日的最高连板数。返回 {(date, sector_name): max_consecutive_days}。"""
    if not dates:
        return {}
    rows = execute_query(
        """
        SELECT trade_date, sector_2, MAX(consecutive_days) AS max_days
        FROM dragon_limit_up_daily
        WHERE trade_date IN %s AND sector_2 IS NOT NULL AND sector_2 != ''
        GROUP BY trade_date, sector_2
        """,
        (tuple(dates),),
    )
    return {(str(r["trade_date"]), r["sector_2"]): int(r["max_days"] or 0) for r in rows}


def _get_concept_max_board(dates: List[str]) -> Dict[Tuple[str, str], int]:
    """每个概念每日的最高连板数。返回 {(date, concept_name): max_consecutive_days}。"""
    if not dates:
        return {}
    rows = execute_query(
        """
        SELECT trade_date, concepts, consecutive_days
        FROM dragon_limit_up_daily
        WHERE trade_date IN %s AND concepts IS NOT NULL AND concepts != ''
        """,
        (tuple(dates),),
    )
    result: Dict[Tuple[str, str], int] = {}
    for r in rows:
        d = str(r["trade_date"])
        days = int(r["consecutive_days"] or 0)
        for c in _split_concepts(r["concepts"]):
            key = (d, c)
            result[key] = max(result.get(key, 0), days)
    return result


def _get_concept_similarity(
    concept_names: Set[str],
    threshold: float = DEFAULT_CONCEPT_SIMILARITY_THRESHOLD,
) -> Dict[Tuple[str, str], float]:
    """计算概念两两之间的成分股重叠度（Jaccard）。
    返回 {(name1, name2): ratio}，其中 ratio = 交集 / 并集。
    只返回 ratio >= threshold 的对。
    """
    if not concept_names:
        return {}
    # 取每个概念最新日期的成分股
    rows = execute_query(
        """
        SELECT concept_code, stock_code
        FROM concept_stock_tag
        WHERE concept_code IN (
            SELECT concept_code FROM concept_meta WHERE concept_name IN %s
        )
        AND trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
        """,
        (tuple(concept_names),),
    )
    # 先拿到 code -> name 映射
    code_name_rows = execute_query(
        "SELECT concept_code, concept_name FROM concept_meta WHERE concept_name IN %s",
        (tuple(concept_names),),
    )
    code_to_name = {r["concept_code"]: r["concept_name"] for r in code_name_rows}
    members: Dict[str, Set[str]] = defaultdict(set)
    for r in rows:
        name = code_to_name.get(r["concept_code"])
        if name:
            members[name].add(r["stock_code"])

    names = list(members.keys())
    result = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = members[names[i]], members[names[j]]
            union = len(a | b)
            if union == 0:
                continue
            ratio = len(a & b) / union
            if ratio >= threshold:
                result[(names[i], names[j])] = ratio
                result[(names[j], names[i])] = ratio
    return result


def _get_stock_amount_history(dates: List[str]) -> Dict[Tuple[str, str], float]:
    """返回 {(date, stock_code): amount}，仅个股。

    只查询窗口内 dragon_limit_up_daily 出现过的股票（页面仅消费候选池代码），
    避免全 A 股全窗口扫描，结果与全量查询在消费范围内逐字节一致。
    """
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT t.trade_date, t.stock_code, t.amount
        FROM trade_stock_daily t
        WHERE t.trade_date >= %s AND t.trade_date <= %s AND t.amount IS NOT NULL
          AND t.stock_code IN (
              SELECT DISTINCT stock_code FROM dragon_limit_up_daily
              WHERE trade_date >= %s AND trade_date <= %s
          )
        """,
        (start_date, end_date, start_date, end_date),
    )
    return {(str(r["trade_date"]), r["stock_code"]): _to_float(r["amount"]) or 0.0 for r in rows}


def _get_stock_close_history(dates: List[str]) -> Dict[Tuple[str, str], float]:
    """返回 {(date, stock_code): close_price}，仅个股。

    只查询窗口内 dragon_limit_up_daily 出现过的股票，避免全 A 股全窗口扫描。
    """
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT t.trade_date, t.stock_code, t.close_price
        FROM trade_stock_daily t
        WHERE t.trade_date >= %s AND t.trade_date <= %s AND t.close_price IS NOT NULL
          AND t.stock_code IN (
              SELECT DISTINCT stock_code FROM dragon_limit_up_daily
              WHERE trade_date >= %s AND trade_date <= %s
          )
        """,
        (start_date, end_date, start_date, end_date),
    )
    return {(str(r["trade_date"]), r["stock_code"]): _to_float(r["close_price"]) or 0.0 for r in rows}


def _get_stock_turnover_history(dates: List[str]) -> Dict[Tuple[str, str], float]:
    """返回 {(date, stock_code): turnover_rate}，仅个股。

    只查询窗口内 dragon_limit_up_daily 出现过的股票，避免全 A 股全窗口扫描。
    """
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT t.trade_date, t.stock_code, t.turnover_rate
        FROM trade_stock_daily t
        WHERE t.trade_date >= %s AND t.trade_date <= %s AND t.turnover_rate IS NOT NULL
          AND t.stock_code IN (
              SELECT DISTINCT stock_code FROM dragon_limit_up_daily
              WHERE trade_date >= %s AND trade_date <= %s
          )
        """,
        (start_date, end_date, start_date, end_date),
    )
    return {(str(r["trade_date"]), r["stock_code"]): _to_float(r["turnover_rate"]) or 0.0 for r in rows}


def _get_board2_sectors(dates: List[str], top_n: int = TOP_N) -> Dict[str, List[Dict]]:
    """每日二板股票最多的 Top N 板块。"""
    if not dates:
        return {}
    rows = execute_query(
        """
        SELECT trade_date, sector_2, COUNT(*) AS cnt
        FROM dragon_limit_up_daily
        WHERE trade_date IN %s AND consecutive_days = 2 AND sector_2 != ''
        GROUP BY trade_date, sector_2
        """,
        (tuple(dates),),
    )
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        grouped[str(r["trade_date"])].append({
            "name": r["sector_2"],
            "count": int(r["cnt"]),
            "type": "sector",
        })
    result = {}
    for d, items in grouped.items():
        items.sort(key=lambda x: (-x["count"], x["name"]))
        result[d] = items[:top_n]
    return result


def _get_board2_concepts(dates: List[str], top_n: int = TOP_N) -> Dict[str, List[Dict]]:
    """每日二板股票最多的 Top N 概念。"""
    if not dates:
        return {}
    rows = execute_query(
        """
        SELECT trade_date, concepts
        FROM dragon_limit_up_daily
        WHERE trade_date IN %s AND consecutive_days = 2 AND concepts != ''
        """,
        (tuple(dates),),
    )
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in rows:
        d = str(r["trade_date"])
        for c in _split_concepts(r["concepts"]):
            counts[(d, c)] += 1
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for (d, c), cnt in counts.items():
        grouped[d].append({"name": c, "count": cnt, "type": "concept"})
    result = {}
    for d, items in grouped.items():
        items.sort(key=lambda x: (-x["count"], x["name"]))
        result[d] = items[:top_n]
    return result


def _get_board_stocks(dates: List[str]) -> Dict[str, Dict[str, List[Dict]]]:
    """每日 3/4/5+ 板个股。返回 {date: {'board3': [...], 'board4': [...], 'board5plus': [...]}}。"""
    if not dates:
        return {}
    rows = execute_query(
        """
        SELECT stock_code, stock_name, trade_date, consecutive_days, sector_2, concepts
        FROM dragon_limit_up_daily
        WHERE trade_date IN %s AND consecutive_days >= 3
        ORDER BY stock_code
        """,
        (tuple(dates),),
    )
    result: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: {
        "board3": [], "board4": [], "board5plus": []
    })
    for r in rows:
        d = str(r["trade_date"])
        cd = int(r["consecutive_days"])
        item = {
            "code": r["stock_code"],
            "name": r["stock_name"] or r["stock_code"],
            "sector_2": r["sector_2"] or "",
            "concepts": _split_concepts(r["concepts"]),
        }
        if cd == 3:
            result[d]["board3"].append(item)
        elif cd == 4:
            result[d]["board4"].append(item)
        else:
            result[d]["board5plus"].append(item)
    return dict(result)


def _get_break_stocks(dates: List[str]) -> Dict[str, List[Dict]]:
    """每日 >=3 板断板股。"""
    if not dates:
        return {}
    rows = execute_query(
        """
        SELECT trade_date, break_3plus_stocks
        FROM dragon_consecutive_stats
        WHERE trade_date IN %s AND break_3plus_count > 0
        """,
        (tuple(dates),),
    )
    result: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        d = str(r["trade_date"])
        labels = (r["break_3plus_stocks"] or "").split(",")
        for label in labels:
            parsed = _parse_break_label(label)
            if parsed:
                result[d].append(parsed)
    return dict(result)


def _get_candidate_pool_amounts(dates: List[str]) -> Dict[str, List[Dict]]:
    """每日候选股池（首板 + 二板）的成交额等信息。"""
    if not dates:
        return {}
    # 用区间查询替代 IN，提升大表 JOIN 效率
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT l.trade_date, l.stock_code, l.stock_name,
               l.sector_2, l.concepts, l.consecutive_days, d.amount
        FROM dragon_limit_up_daily l
        JOIN trade_stock_daily d
          ON l.stock_code = d.stock_code AND l.trade_date = d.trade_date
        WHERE l.trade_date >= %s AND l.trade_date <= %s
          AND l.consecutive_days IN (1, 2)
          AND d.amount IS NOT NULL
        """,
        (start_date, end_date),
    )
    result: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        result[str(r["trade_date"])].append({
            "code": r["stock_code"],
            "name": r["stock_name"] or r["stock_code"],
            "sector_2": r["sector_2"] or "",
            "concepts": _split_concepts(r["concepts"]),
            "board_days": int(r["consecutive_days"] or 1),
            "amount": _to_float(r["amount"]) or 0.0,
        })
    return dict(result)


def _get_all_limit_up_amounts(dates: List[str]) -> Dict[str, List[float]]:
    """每日全部涨停股的成交额列表，用于成交量分的 p5/p95 锚点。"""
    if not dates:
        return {}
    start_date, end_date = min(dates), max(dates)
    rows = execute_query(
        """
        SELECT l.trade_date, d.amount
        FROM dragon_limit_up_daily l
        JOIN trade_stock_daily d
          ON l.stock_code = d.stock_code AND l.trade_date = d.trade_date
        WHERE l.trade_date >= %s AND l.trade_date <= %s
          AND d.amount IS NOT NULL
        """,
        (start_date, end_date),
    )
    result: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        amount = _to_float(r["amount"])
        if amount is not None and amount > 0:
            result[str(r["trade_date"])].append(amount)
    return dict(result)


def _get_prev_day_break_info(
    prev_dates: List[str],
    break_codes: Set[str],
) -> Dict[Tuple[str, str], Dict]:
    """查询断板股前一天的 sector_2 / concepts。"""
    if not prev_dates or not break_codes:
        return {}
    rows = execute_query(
        """
        SELECT trade_date, stock_code, sector_2, concepts
        FROM dragon_limit_up_daily
        WHERE trade_date IN %s AND stock_code IN %s
        """,
        (tuple(prev_dates), tuple(break_codes)),
    )
    return {
        (str(r["trade_date"]), r["stock_code"]): {
            "sector_2": r["sector_2"] or "",
            "concepts": _split_concepts(r["concepts"]),
        }
        for r in rows
    }


def _get_concept_codes(concept_names: Set[str]) -> Dict[str, str]:
    """概念名 -> 概念编码。"""
    if not concept_names:
        return {}
    rows = execute_query(
        """
        SELECT concept_name, concept_code
        FROM concept_meta
        WHERE concept_name IN %s
        """,
        (tuple(concept_names),),
    )
    return {r["concept_name"]: r["concept_code"] for r in rows}


