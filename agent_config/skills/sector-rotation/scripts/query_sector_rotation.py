#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块轮动查询脚本.

三种模式:
    matrix  - 查询最近 N 个交易日每日 Top N 板块排名矩阵
    detail  - 查询给定板块的最新明细 + 历史排名 + 指数K线 + 相关股票
    stock   - 给定股票代码, 先查其所属申万二级板块, 再查该板块详情

复用 sector_rotation.rotation_store 的查询函数, 不依赖 HTTP 服务。
"""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path

# 添加项目根目录到 sys.path (scripts/ -> sector-rotation/ -> skills/ -> agent_config/ -> 项目根)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from sector_rotation.rotation_store import (
    load_matrix,
    get_detail,
    get_sector_history,
    get_sector_index,
    get_top_relevant_stocks,
    get_available_dates,
    find_sectors,
)
from sector_rotation.rotation_core import execute_query

# 指标中文含义 (输出时附带, 帮助 LLM 理解数值方向)
# Z-score 指标均为截面标准化: 0=全部板块均值, 正值=强于均值, 负值=弱于均值
INDICATOR_MEANINGS = {
    "mom21_z": "21日动量Z-score(截面)，正值表示该板块动量强于全部板块均值",
    "rs60_z": "60日相对强度Z-score(截面)，正值表示超额收益强于全部板块均值",
    "vol_ratio_z": "量能比Z-score(5日/60日均量，截面)，正值表示放量程度强于全部板块均值",
    "roc_20": "20日涨跌幅(%)，正值表示上涨",
    "ma20_slope": "MA20斜率(10日线性回归)，正值表示上升趋势",
    "ma20_accel": "MA20加速度(斜率变化)，正值表示趋势加速",
    "macd_hist": "MACD柱状值(DIF-DEA)，正值表示多头",
    "hist_delta": "MACD柱变化(当日-前日)，正值表示动能增强",
}

def _num(v):
    """数值安全转换, NaN/None -> None"""
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
    # 精确匹配不到 → 尝试常见后缀 (避免 LIKE 匹配到同名不同后缀的代码, 如 000001)
    for suffix in _suffix_order(code):
        rows = execute_query(
            "SELECT stock_name FROM trade_stock_status WHERE stock_code = %s",
            (f"{_normalize_stock_code(code)}{suffix}",))
        if rows and rows[0]["stock_name"]:
            return rows[0]["stock_name"]
    return code


def _normalize_stock_code(raw: str) -> str:
    """提取裸代码 (去掉交易所后缀).

    例如: '600519.SH' -> '600519', '000858' -> '000858'.
    """
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


# ============================================================
# 模式A: 轮动矩阵
# ============================================================

def mode_matrix(days: int, top_n: int, level: int) -> dict:
    df = load_matrix(days=days, top_n=top_n, level=level)
    if df.empty:
        return {"ok": False, "error": f"最近 {days} 个交易日无板块轮动数据"}

    data = []
    for trade_date, group in df.groupby("trade_date", sort=False):
        sectors = []
        for _, row in group.iterrows():
            sectors.append({
                "rank": _int(row.get("composite_rank")),
                "sector": row.get("sector_name", ""),
                "score": _num(row.get("score")),
                "composite_score": _num(row.get("composite_score")),
                "phase": row.get("phase", ""),
            })
        data.append({"date": trade_date, "top_sectors": sectors})

    return {
        "ok": True,
        "mode": "matrix",
        "days": days,
        "top_n": top_n,
        "level": level,
        "date_count": len(data),
        "data": data,
    }


# ============================================================
# 模式B: 单板块详情
# ============================================================

def mode_detail(sector: str, days: int, level: int) -> dict:
    dates = get_available_dates(level=level, days=1)
    if not dates:
        return {"ok": False, "error": "无可用交易日数据"}
    latest = dates[0]

    # 精确匹配
    detail = get_detail(sector, latest, level=level)
    fuzzy_matched = False
    actual_sector = sector
    candidates = None

    if not detail:
        # 模糊匹配
        matches = find_sectors(sector, level=level)
        if matches:
            actual_sector = matches[0]["sector_name"]
            fuzzy_matched = matches[0]["matched_by"] == "fuzzy"
            detail = get_detail(actual_sector, latest, level=level)
            if len(matches) > 1:
                candidates = [m["sector_name"] for m in matches]

    if not detail:
        return {"ok": False, "error": f"板块 '{sector}' 在 {latest} 无数据, 请确认板块名称是否为申万二级分类"}

    detail_out = {
        "trade_date": str(detail.get("trade_date", "")),
        "sector_name": detail.get("sector_name", ""),
        "rank": _int(detail.get("rank")),
        "composite_rank": _int(detail.get("composite_rank")),
        "score": _num(detail.get("score")),
        "composite_score": _num(detail.get("composite_score")),
        "phase": detail.get("phase", ""),
        "phase_desc": detail.get("phase_desc", ""),
        "member_count": _int(detail.get("member_count")),
        "indicators": {
            "mom21_z": {"value": _num(detail.get("mom21_z")), "meaning": INDICATOR_MEANINGS["mom21_z"]},
            "rs60_z": {"value": _num(detail.get("rs60_z")), "meaning": INDICATOR_MEANINGS["rs60_z"]},
            "vol_ratio_z": {"value": _num(detail.get("vol_ratio_z")), "meaning": INDICATOR_MEANINGS["vol_ratio_z"]},
            "roc_20": {"value": _num(detail.get("roc_20")), "meaning": INDICATOR_MEANINGS["roc_20"]},
            "ma20_slope": {"value": _num(detail.get("ma20_slope")), "meaning": INDICATOR_MEANINGS["ma20_slope"]},
            "ma20_accel": {"value": _num(detail.get("ma20_accel")), "meaning": INDICATOR_MEANINGS["ma20_accel"]},
            "macd_hist": {"value": _num(detail.get("macd_hist")), "meaning": INDICATOR_MEANINGS["macd_hist"]},
            "hist_delta": {"value": _num(detail.get("hist_delta")), "meaning": INDICATOR_MEANINGS["hist_delta"]},
        },
    }

    # 近 N 日历史排名走势
    hist_df = get_sector_history(actual_sector, level=level, days=days)
    history = []
    if not hist_df.empty:
        for _, r in hist_df.iterrows():
            history.append({
                "date": r.get("trade_date", ""),
                "composite_rank": _int(r.get("composite_rank")),
                "score": _num(r.get("score")),
                "phase": r.get("phase", ""),
            })

    # 指数K线 (近2年, 取最近60条避免输出过大)
    idx_df = get_sector_index(actual_sector, level=level, years=2)
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
    for item in get_top_relevant_stocks(actual_sector, latest, level=level, limit=5):
        relevant.append({
            "code": item.get("stock_code", ""),
            "name": _stock_name(item.get("stock_code", "")),
            "total_score": _num(item.get("total_score")),
        })

    result = {
        "ok": True,
        "mode": "detail",
        "sector": sector,
        "actual_sector": actual_sector,
        "latest_date": latest,
        "level": level,
        "fuzzy_matched": fuzzy_matched,
        "detail": detail_out,
        "history_days": len(history),
        "history": history,
        "index_kline_count": len(index_kline),
        "index_kline": index_kline,
        "relevant_stocks": relevant,
    }
    if candidates:
        result["candidates"] = candidates
    return result


# ============================================================
# 模式C: 股票 -> 所属板块 -> 详情
# ============================================================

def mode_stock(stock_code: str, days: int, level: int) -> dict:
    # 1. 精确匹配 (传入什么就查什么)
    rows = execute_query(
        "SELECT stock_name, stock_code, sector_1, sector_2 FROM trade_stock_status WHERE stock_code = %s",
        (stock_code,))
    # 2. 精确匹配不到 → 尝试常见后缀 (避免 LIKE 匹配到同名不同后缀的代码, 如 000001)
    if not rows and "." not in stock_code:
        for suffix in _suffix_order(stock_code):
            rows = execute_query(
                "SELECT stock_name, stock_code, sector_1, sector_2 FROM trade_stock_status WHERE stock_code = %s",
                (f"{stock_code.strip().upper()}{suffix}",))
            if rows:
                break
    if not rows:
        return {"ok": False, "error": f"股票 {stock_code} 未在 trade_stock_status 中找到, 请确认代码是否正确"}

    info = rows[0]
    sector_field = "sector_2" if level == 2 else "sector_1"
    sector = info.get(sector_field)
    if not sector:
        return {"ok": False, "error": f"股票 {stock_code} ({info.get('stock_name','')}) 未分配申万{'二' if level == 2 else '一'}级板块"}

    result = mode_detail(sector, days=days, level=level)
    result["mode"] = "stock"
    result["stock_code"] = stock_code
    result["stock_name"] = info.get("stock_name", "")
    result["sector"] = sector
    result["matched_stock_code"] = info.get("stock_code", "")
    return result


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="板块轮动查询")
    parser.add_argument("--mode", choices=["matrix", "detail", "stock"], default="matrix",
                        help="查询模式: matrix=轮动矩阵, detail=单板块详情, stock=股票反查所属板块")
    parser.add_argument("--days", type=int, default=20, help="回溯交易日数 (matrix默认20, detail/stock历史默认60)")
    parser.add_argument("--top-n", type=int, default=15, help="matrix模式每日Top N (默认15)")
    parser.add_argument("--sector", type=str, default="", help="detail模式的板块名称 (申万二级, 如 半导体/白酒)")
    parser.add_argument("--stock", type=str, default="", help="stock模式的股票代码 (带后缀, 如 600519.SH)")
    parser.add_argument("--level", type=int, choices=[1, 2], default=2, help="板块级别 1=申万一级 2=申万二级")
    args = parser.parse_args()

    if args.mode == "matrix":
        result = mode_matrix(days=args.days, top_n=args.top_n, level=args.level)
    elif args.mode == "detail":
        if not args.sector:
            result = {"ok": False, "error": "detail模式需要 --sector 参数"}
        else:
            hist_days = args.days if args.days != 20 else 60
            result = mode_detail(sector=args.sector, days=hist_days, level=args.level)
    else:  # stock
        if not args.stock:
            result = {"ok": False, "error": "stock模式需要 --stock 参数"}
        else:
            hist_days = args.days if args.days != 20 else 60
            result = mode_stock(stock_code=args.stock, days=hist_days, level=args.level)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
