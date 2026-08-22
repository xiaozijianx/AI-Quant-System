#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""概念轮动查询脚本.

三种模式:
    matrix  - 查询最近 N 个交易日每日 Top N 概念排名矩阵
    detail  - 查询给定概念(名称或代码)的最新明细 + 历史排名 + 指数K线 + 相关股票
    stock   - 给定股票代码, 先查其高关联度概念, 再查该概念详情

复用 concept_rotation.rotation_store 的查询函数, 不依赖 HTTP 服务。
"""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from concept_rotation.rotation_store import (
    load_matrix,
    get_detail,
    get_concept_history,
    get_concept_index,
    get_top_relevant_stocks,
    get_available_dates,
)
from concept_rotation.rotation_core import execute_query

# 指标中文含义 (输出时附带, 帮助 LLM 理解数值方向)
# Z-score 指标均为截面标准化: 0=全部概念均值, 正值=强于均值, 负值=弱于均值
INDICATOR_MEANINGS = {
    "mom10_z": "10日动量Z-score(截面)，正值表示该概念动量强于全部概念均值",
    "rs20_z": "20日相对强度Z-score(截面)，正值表示超额收益强于全部概念均值",
    "vol_ratio_z": "量能比Z-score(5日/20日均量，截面)，正值表示放量程度强于全部概念均值",
    "roc_20": "20日涨跌幅(%)，正值表示上涨",
    "ma20_slope": "MA20斜率(10日线性回归)，正值表示上升趋势",
    "ma20_accel": "MA20加速度(斜率变化)，正值表示趋势加速",
    "macd_hist": "MACD柱状值(DIF-DEA)，正值表示多头",
    "hist_delta": "MACD柱变化(当日-前日)，正值表示动能增强",
}

def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _int(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _stock_name(code: str) -> str:
    """从 trade_stock_status 查股票名称, 支持带/不带后缀."""
    rows = execute_query(
        "SELECT stock_name FROM trade_stock_status WHERE stock_code = %s",
        (code,))
    if rows and rows[0]["stock_name"]:
        return rows[0]["stock_name"]
    # 精确匹配不到 → 尝试常见后缀
    for suffix in _suffix_order(code):
        rows = execute_query(
            "SELECT stock_name FROM trade_stock_status WHERE stock_code = %s",
            (f"{_normalize_stock_code(code)}{suffix}",))
        if rows and rows[0]["stock_name"]:
            return rows[0]["stock_name"]
    return code


def _normalize_stock_code(raw: str) -> str:
    """提取裸代码 (去掉交易所后缀)."""
    code = raw.strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if code.endswith(suffix):
            return code[: -len(suffix)]
    return code


def _suffix_order(code: str) -> list:
    """根据股票代码首位确定后缀尝试顺序, 避免同名不同后缀匹配错误 (如 000001.SZ vs 000001.SH)."""
    code = code.strip().upper()
    if code and code[0] in ("0", "3"):
        return [".SZ", ".SH", ".BJ"]
    if code and code[0] in ("5", "6"):
        return [".SH", ".SZ", ".BJ"]
    return [".SH", ".SZ", ".BJ"]


def _resolve_concept_code(concept: str) -> tuple:
    """将概念名称解析为 concept_code, 若输入已是代码则直接返回。返回 (code, name)"""
    # 先按 concept_code 精确匹配
    rows = execute_query(
        "SELECT concept_code, concept_name FROM trade_concept_rotation_daily "
        "WHERE concept_code = %s LIMIT 1",
        (concept,))
    if rows:
        return rows[0]["concept_code"], rows[0]["concept_name"]

    # 按概念名称精确匹配
    rows = execute_query(
        "SELECT concept_code, concept_name FROM trade_concept_rotation_daily "
        "WHERE concept_name = %s LIMIT 1",
        (concept,))
    if rows:
        return rows[0]["concept_code"], rows[0]["concept_name"]

    # 模糊匹配名称
    rows = execute_query(
        "SELECT concept_code, concept_name FROM trade_concept_rotation_daily "
        "WHERE concept_name LIKE %s LIMIT 1",
        (f"%{concept}%",))
    if rows:
        return rows[0]["concept_code"], rows[0]["concept_name"]

    return None, None


# ============================================================
# 模式A: 轮动矩阵
# ============================================================

def mode_matrix(days: int, top_n: int) -> dict:
    df = load_matrix(days=days, top_n=top_n)
    if df.empty:
        return {"ok": False, "error": f"最近 {days} 个交易日无概念轮动数据"}

    data = []
    for trade_date, group in df.groupby("trade_date", sort=False):
        concepts = []
        for _, row in group.iterrows():
            concepts.append({
                "rank": _int(row.get("composite_rank")),
                "concept_code": row.get("concept_code", ""),
                "concept": row.get("concept_name", ""),
                "source": row.get("source_prefix", ""),
                "score": _num(row.get("score")),
                "composite_score": _num(row.get("composite_score")),
                "phase": row.get("phase", ""),
            })
        data.append({"date": trade_date, "top_concepts": concepts})

    return {
        "ok": True,
        "mode": "matrix",
        "days": days,
        "top_n": top_n,
        "date_count": len(data),
        "data": data,
    }


# ============================================================
# 模式B: 单概念详情
# ============================================================

def mode_detail(concept: str, days: int) -> dict:
    concept_code, concept_name = _resolve_concept_code(concept)
    if not concept_code:
        return {"ok": False, "error": f"概念 '{concept}' 未找到, 请确认概念名称或代码。可用模式A查看当前上榜概念"}

    dates = get_available_dates(days=1)
    if not dates:
        return {"ok": False, "error": "无可用交易日数据"}
    latest = dates[0]

    detail = get_detail(concept_code, latest)
    if not detail:
        return {"ok": False, "error": f"概念 '{concept_name}'({concept_code}) 在 {latest} 无数据"}

    detail_out = {
        "trade_date": str(detail.get("trade_date", "")),
        "concept_code": detail.get("concept_code", ""),
        "concept_name": detail.get("concept_name", ""),
        "source_prefix": detail.get("source_prefix", ""),
        "rank": _int(detail.get("rank")),
        "composite_rank": _int(detail.get("composite_rank")),
        "score": _num(detail.get("score")),
        "composite_score": _num(detail.get("composite_score")),
        "phase": detail.get("phase", ""),
        "phase_desc": detail.get("phase_desc", ""),
        "member_count": _int(detail.get("member_count")),
        "indicators": {
            "mom10_z": {"value": _num(detail.get("mom10_z")), "meaning": INDICATOR_MEANINGS["mom10_z"]},
            "rs20_z": {"value": _num(detail.get("rs20_z")), "meaning": INDICATOR_MEANINGS["rs20_z"]},
            "vol_ratio_z": {"value": _num(detail.get("vol_ratio_z")), "meaning": INDICATOR_MEANINGS["vol_ratio_z"]},
            "roc_20": {"value": _num(detail.get("roc_20")), "meaning": INDICATOR_MEANINGS["roc_20"]},
            "ma20_slope": {"value": _num(detail.get("ma20_slope")), "meaning": INDICATOR_MEANINGS["ma20_slope"]},
            "ma20_accel": {"value": _num(detail.get("ma20_accel")), "meaning": INDICATOR_MEANINGS["ma20_accel"]},
            "macd_hist": {"value": _num(detail.get("macd_hist")), "meaning": INDICATOR_MEANINGS["macd_hist"]},
            "hist_delta": {"value": _num(detail.get("hist_delta")), "meaning": INDICATOR_MEANINGS["hist_delta"]},
        },
    }

    # 近 N 日历史排名走势
    hist_df = get_concept_history(concept_code, days=days)
    history = []
    if not hist_df.empty:
        for _, r in hist_df.iterrows():
            history.append({
                "date": r.get("trade_date", ""),
                "composite_rank": _int(r.get("composite_rank")),
                "score": _num(r.get("score")),
                "phase": r.get("phase", ""),
            })

    # 概念指数K线 (近1年, 取最近60条)
    idx_df = get_concept_index(concept_code, years=1)
    index_kline = []
    if not idx_df.empty:
        recent = idx_df.tail(60)
        for _, r in recent.iterrows():
            index_kline.append({
                "date": r.get("trade_date", ""),
                "close_idx": _num(r.get("close_idx")),
                "change_pct": _num(r.get("change_pct")),
                "total_amount": _num(r.get("total_amount")),
            })

    # 相关性最高的5只股票
    relevant = []
    for item in get_top_relevant_stocks(concept_name, latest, limit=5):
        relevant.append({
            "code": item.get("stock_code", ""),
            "name": _stock_name(item.get("stock_code", "")),
            "total_score": _num(item.get("total_score")),
            "corr_score": _num(item.get("corr_score")),
            "leader_score": _num(item.get("leader_score")),
        })

    return {
        "ok": True,
        "mode": "detail",
        "concept": concept_name,
        "concept_code": concept_code,
        "latest_date": latest,
        "detail": detail_out,
        "history_days": len(history),
        "history": history,
        "index_kline_count": len(index_kline),
        "index_kline": index_kline,
        "relevant_stocks": relevant,
    }


# ============================================================
# 模式C: 股票 -> 高关联概念 -> 详情
# ============================================================

def mode_stock(stock_code: str, days: int) -> dict:
    # 1. 精确匹配
    rows = _query_stock_concepts(stock_code)
    # 2. 精确匹配不到 → 尝试常见后缀
    if not rows and "." not in stock_code:
        for suffix in _suffix_order(stock_code):
            rows = _query_stock_concepts(f"{stock_code.strip().upper()}{suffix}")
            if rows:
                stock_code = f"{stock_code.strip().upper()}{suffix}"  # 更新为实际匹配的代码
                break

    if not rows:
        return {"ok": False, "error": f"股票 {stock_code} 未在 concept_stock_relevance 中找到高关联概念, 请确认代码是否正确"}

    # 查询所有高相关概念的详情
    concept_details = []
    for r in rows:
        detail_result = mode_detail(r["concept_name"], days=days)
        if detail_result.get("ok"):
            concept_details.append({
                "concept": r["concept_name"],
                "total_score": _num(r.get("total_score")),
                "rank_in_stock": _int(r.get("rank_in_stock")),
                "detail": detail_result.get("detail"),
                "history": detail_result.get("history", []),
                "index_kline": detail_result.get("index_kline", []),
                "relevant_stocks": detail_result.get("relevant_stocks", []),
            })

    return {
        "ok": True,
        "mode": "stock",
        "stock_code": stock_code,
        "stock_name": _stock_name(stock_code),
        "concept_count": len(concept_details),
        "concept_details": concept_details,
    }


def _query_stock_concepts(code: str) -> list:
    """查询股票高关联概念, 返回原始行列表."""
    return execute_query(
        """
        SELECT DISTINCT concept_name, total_score, corr_score, leader_score, rank_in_stock
        FROM concept_stock_relevance
        WHERE stock_code = %s
          AND calc_date = (
              SELECT MAX(calc_date) FROM concept_stock_relevance WHERE stock_code = %s
          )
          AND rank_in_stock <= 5
        ORDER BY total_score DESC NULLS LAST
        LIMIT 5
        """,
        (code, code))


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="概念轮动查询")
    parser.add_argument("--mode", choices=["matrix", "detail", "stock"], default="matrix",
                        help="查询模式: matrix=轮动矩阵, detail=单概念详情, stock=股票反查高关联概念")
    parser.add_argument("--days", type=int, default=20, help="回溯交易日数 (默认20)")
    parser.add_argument("--top-n", type=int, default=15, help="matrix模式每日Top N (默认15)")
    parser.add_argument("--concept", type=str, default="", help="detail模式的概念名称或代码 (如 'AI算力' 或 'BK1234')")
    parser.add_argument("--stock", type=str, default="", help="stock模式的股票代码 (支持带或不带后缀, 如 600519.SH / 600519)")
    args = parser.parse_args()

    if args.mode == "matrix":
        result = mode_matrix(days=args.days, top_n=args.top_n)
    elif args.mode == "detail":
        if not args.concept:
            result = {"ok": False, "error": "detail模式需要 --concept 参数"}
        else:
            result = mode_detail(concept=args.concept, days=args.days)
    else:  # stock
        if not args.stock:
            result = {"ok": False, "error": "stock模式需要 --stock 参数"}
        else:
            result = mode_stock(stock_code=args.stock, days=args.days)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
