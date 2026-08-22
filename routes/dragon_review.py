# -*- coding: utf-8 -*-
"""龙头复盘页面 API.

提供:
- GET /api/dragon-review/matrix        每日龙头复盘矩阵（一行一天）
- GET /api/dragon-review/stock-detail  个股详情（含近 30 日 K 线）
- GET /api/dragon-review/available-dates  有数据的交易日

数据源：CASE-A5 龙头数据表 + trade_stock_daily。
"""
from __future__ import annotations

import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Query

from lib.paths import setup_sys_path

setup_sys_path()

from sector_rotation.rotation_core import execute_query
from lib.stock_quote import load_quote
from lib.stock_utils import get_stock_info, normalize_code
from lib.stock_intraday import load_intraday_summaries

router = APIRouter()

TOP_N = 3
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
DEFAULT_VOLUME_MA_DAYS = 20
DEFAULT_VOLUME_RATIO_MA = 1.2
DEFAULT_VOLUME_RATIO_RING = 1.15
MARKET_INDEX_CODE = "000001.SH"

# 全 A 股代码识别条件（SQL 片段，与 CASE-A5 precompute.py 保持一致）：
#   - 沪市 A 股: 60/68/90 开头 .SH（90 为沪市 B 股）
#   - 深市 A 股: 00/30/20 开头 .SZ（20 为深市 B 股）
#   - 北交所:    4/8/92 开头 .BJ
# 排除指数（000xxx.SH 上证/中证指数、399xxx.SZ 深证指数、98xx 北证指数）、
#       ETF/基金（15/16/18.SZ、50/51/52/53/55/56/58.SH）、可转债（11/12/13 开头）
# 不依赖 trade_stock_status（申万分类），确保无分类的新股也能计入大盘统计
A_STOCK_CONDITION = """
    (
        (stock_code LIKE '60%%' AND stock_code LIKE '%%.SH')
        OR (stock_code LIKE '68%%' AND stock_code LIKE '%%.SH')
        OR (stock_code LIKE '90%%' AND stock_code LIKE '%%.SH')
        OR (stock_code LIKE '00%%' AND stock_code LIKE '%%.SZ')
        OR (stock_code LIKE '30%%' AND stock_code LIKE '%%.SZ')
        OR (stock_code LIKE '20%%' AND stock_code LIKE '%%.SZ')
        OR (stock_code LIKE '4%%' AND stock_code LIKE '%%.BJ')
        OR (stock_code LIKE '8%%' AND stock_code LIKE '%%.BJ')
        OR (stock_code LIKE '92%%' AND stock_code LIKE '%%.BJ')
    )
"""

# 板块低位过滤默认值：短周期判断"近期是否急涨"，长周期判断"是否涨了大波后小幅回调"
DEFAULT_SECTOR_SHORT_LOOKBACK = 10     # 板块短窗：看近 N 个交易日累计涨幅
DEFAULT_SECTOR_SHORT_RETURN_PCT = 15.0 # 板块短窗：累计涨幅超过该百分比视为不在低位
DEFAULT_SECTOR_LONG_LOOKBACK = 30      # 板块长窗：看近 N 个交易日累计涨幅
DEFAULT_SECTOR_LONG_RETURN_PCT = 30.0  # 板块长窗：累计涨幅超过该百分比视为不在低位
DEFAULT_SECTOR_MAX_BOARD_LEVEL = 3     # 板块内最高连板不超过 N 板

# 概念低位过滤默认值：短周期判断"近期是否急涨"，长周期判断"是否涨了大波后小幅回调"
DEFAULT_CONCEPT_SHORT_LOOKBACK = 10    # 概念短窗：看近 N 个交易日累计涨幅
DEFAULT_CONCEPT_SHORT_RETURN_PCT = 8.0 # 概念短窗：累计涨幅超过该百分比视为不在低位
DEFAULT_CONCEPT_LONG_LOOKBACK = 30     # 概念长窗：看近 N 个交易日累计涨幅
DEFAULT_CONCEPT_LONG_RETURN_PCT = 20.0 # 概念长窗：累计涨幅超过该百分比视为不在低位
DEFAULT_CONCEPT_MAX_BOARD_LEVEL = 3    # 概念内最高连板不超过 N 板

# 个股低位过滤默认值
DEFAULT_STOCK_GAIN_DAYS = 5           # 个股低位判断：近 N 日涨幅
DEFAULT_STOCK_GAIN_LIMIT = 20.0       # 个股低位判断：涨幅不超过 %
DEFAULT_AMOUNT_WEIGHT = 0.6           # 量能分中“成交量分”的权重，放量分权重 = 1 - 该值
DEFAULT_VOLUME_UP_WEIGHT = 0.4        # 兼容保留，实际使用 1 - amount_weight
DEFAULT_CONCEPT_SIMILARITY_THRESHOLD = 0.4  # 概念亲密度阈值（百分比）

# ============================================================
# 龙头板块/概念复合打分权重默认值
# ============================================================
# 5 个维度：涨停率、涨停数量、平均涨幅、人均成交额、成交额环比放大倍数
DEFAULT_SECTOR_COUNT_WEIGHT = 0.25
DEFAULT_SECTOR_RATIO_WEIGHT = 0.30
DEFAULT_SECTOR_CHANGE_WEIGHT = 0.25
DEFAULT_SECTOR_AMOUNT_WEIGHT = 0.10
DEFAULT_SECTOR_AMOUNT_RATIO_WEIGHT = 0.10

DEFAULT_CONCEPT_COUNT_WEIGHT = 0.25
DEFAULT_CONCEPT_RATIO_WEIGHT = 0.30
DEFAULT_CONCEPT_CHANGE_WEIGHT = 0.25
DEFAULT_CONCEPT_AMOUNT_WEIGHT = 0.10
DEFAULT_CONCEPT_AMOUNT_RATIO_WEIGHT = 0.10

DEFAULT_CONCEPT_MIN_LIMIT_UP = 2      # 概念最少涨停家数（过滤极小概念）
DEFAULT_CONCEPT_MIN_STOCK_COUNT = 10  # 概念最少成分股数

# 大盘情绪过滤默认值
DEFAULT_MAX_LIMIT_DOWN = 10           # 最大跌停家数
DEFAULT_MIN_UP_DOWN_RATIO = 3.0       # 最小涨跌停比（涨停家数 / 跌停家数）
DEFAULT_MIN_RISE_RATIO = 0.5          # 最小上涨家数占比

# 龙头股 4 维打分权重默认值（封单质量已合并进涨停强度）
DEFAULT_LEADER_STRENGTH_WEIGHT = 0.45   # 涨停强度（含板型、首次涨停时间、炸板扣分）
DEFAULT_LEADER_AMOUNT_WEIGHT = 0.30     # 量能强度
DEFAULT_LEADER_TURNOVER_WEIGHT = 0.15   # 换手健康
DEFAULT_LEADER_POSITION_WEIGHT = 0.10   # 位置安全

# 龙头股相关性权重：与板块/概念的联动程度
DEFAULT_LEADER_SECTOR_RELEVANCE_WEIGHT = 0.10   # 板块相关性（申万二级）
DEFAULT_LEADER_CONCEPT_RELEVANCE_WEIGHT = 0.10  # 概念相关性


# ============================================================
# 工具函数
# ============================================================

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


# ============================================================
# API 路由
# ============================================================

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
    try:
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
            sector_weights=sector_w,
            concept_weights=concept_w,
            concept_min_limit_up=concept_min_limit_up,
            concept_min_stock_count=concept_min_stock_count,
            leader_weights=leader_w,
            sector_relevance_weight=sector_relevance_weight,
            concept_relevance_weight=concept_relevance_weight,
        )
        return _clean_nan({"ok": True, **data})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


@router.get("/page-for-date")
def page_for_date(
    date: str = Query(..., description="目标日期 YYYY-MM-DD"),
    page_size: int = Query(5, ge=1, le=60),
):
    """根据目标日期返回所在的页码，便于前端直接跳转。"""
    try:
        page = _get_page_for_date(date, page_size=page_size)
        return _clean_nan({"ok": True, "page": page})
    except Exception as e:
        return _clean_nan({"ok": False, "message": f"{type(e).__name__}: {e}"})


@router.get("/stock-detail")
def stock_detail(
    code: str = Query(..., description="股票代码"),
    date: str = Query(..., description="日期 YYYY-MM-DD"),
):
    """返回个股基础信息 + 近 30 个交易日简单 K 线 + 近期涨停记录。"""
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


@router.get("/available-dates")
def available_dates(days: int = Query(60, ge=1, le=250)):
    """返回 dragon_limit_up_daily 中已有的最近 N 个交易日。"""
    return {"dates": _get_available_dates(days=days)}
