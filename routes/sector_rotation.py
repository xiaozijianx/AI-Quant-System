# -*- coding: utf-8 -*-
"""板块轮动页面 API.

提供:
- GET  /api/sector-rotation/status     当前任务状态
- GET  /api/sector-rotation/matrix     板块轮动热力图数据
- GET  /api/sector-rotation/detail     单板块某日明细
- POST /api/sector-rotation/refresh    刷新某日数据
- POST /api/sector-rotation/rebuild    重建最近 N 日数据
- POST /api/sector-rotation/stop       停止当前任务
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from sector_rotation.indicator_notes import get_note
from lib.stock_utils import get_stock_info
from sector_rotation.rotation_store import (
    get_available_dates,
    get_detail,
    get_sector_history,
    get_sector_index,
    get_top_relevant_stocks,
    load_matrix,
)
from sector_rotation.rotation_worker import (
    get_status,
    start_refresh,
    start_rebuild,
    stop_current_job,
)

router = APIRouter()


@router.get("/status")
def status():
    """返回当前后台任务状态."""
    return get_status()


@router.get("/matrix")
def matrix(days: int = Query(20, ge=1, le=120),
           top_n: int = Query(15, ge=1, le=50),
           level: int = Query(2, ge=1, le=2),
           end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD, 为空则取最新交易日")):
    """返回指定结束日期前 N 个交易日、每日 Top N 板块的排名矩阵."""
    df = load_matrix(days=days, top_n=top_n, level=level, end_date=end_date)
    if df.empty:
        return {
            "dates": [],
            "ranks": list(range(1, top_n + 1)),
            "cells": [],
            "has_data": False,
        }

    dates = sorted(df["trade_date"].unique().tolist())
    ranks = sorted(df["composite_rank"].unique().tolist())

    # 构造前端方便渲染的单元格列表
    cells = []
    for _, row in df.iterrows():
        cells.append({
            "date": row["trade_date"],
            "rank": int(row["composite_rank"]),
            "sector": row["sector_name"],
            "score": float(row["score"]) if row["score"] is not None else None,
            "composite_score": float(row["composite_score"]) if row["composite_score"] is not None else None,
            "phase": row["phase"],
        })

    return {
        "dates": dates,
        "ranks": ranks,
        "cells": cells,
        "has_data": True,
    }


@router.get("/detail")
def detail(sector: str = Query(..., description="板块名称"),
           date: str = Query(..., description="日期 YYYY-MM-DD"),
           level: int = Query(2, ge=1, le=2),
           history_days: int = Query(60, ge=5, le=250)):
    """返回某板块某日期的明细 + 近期历史."""
    row = get_detail(sector, date, level=level)
    if not row:
        return {"ok": False, "error": "未找到数据"}

    # 数值字段转原生类型
    float_fields = [
        "score", "composite_score",
        "mom21_z", "rs60_z", "vol_ratio_z",
        "roc_20", "ma20_slope", "ma20_accel", "macd_hist", "hist_delta",
    ]
    int_fields = ["rank", "composite_rank", "member_count"]
    detail_data = {}
    for k, v in row.items():
        if k in float_fields and v is not None:
            detail_data[k] = float(v)
        elif k in int_fields and v is not None:
            detail_data[k] = int(v)
        else:
            detail_data[k] = v

    # 指标注释
    notes = {}
    for field in detail_data.keys():
        notes[field] = get_note(field)

    # 历史走势
    hist_df = get_sector_history(sector, level=level, days=history_days)
    history = []
    if not hist_df.empty:
        for _, r in hist_df.iterrows():
            history.append({
                "date": r["trade_date"],
                "rank": int(r["rank"]) if r["rank"] is not None else None,
                "composite_rank": int(r["composite_rank"]) if r["composite_rank"] is not None else None,
                "score": float(r["score"]) if r["score"] is not None else None,
                "composite_score": float(r["composite_score"]) if r["composite_score"] is not None else None,
                "phase": r["phase"],
            })

    # 相关性最高的 5 只股票
    relevant_stocks = []
    for item in get_top_relevant_stocks(sector, date, level=level, limit=5):
        info = get_stock_info(item["stock_code"])
        relevant_stocks.append({
            "code": item["stock_code"],
            "name": info.get("name", ""),
            "total_score": item["total_score"],
        })

    return {
        "ok": True,
        "detail": detail_data,
        "notes": notes,
        "history": history,
        "relevant_stocks": relevant_stocks,
    }


@router.get("/sector-index")
def sector_index(sector: str = Query(..., description="板块名称"),
                 level: int = Query(2, ge=1, le=2),
                 years: int = Query(2, ge=1, le=5)):
    """返回某板块指数近 N 年的日 K 线."""
    df = get_sector_index(sector, level=level, years=years)
    if df.empty:
        return {"ok": False, "error": "未找到板块指数数据"}
    return {
        "ok": True,
        "dates": df["trade_date"].tolist(),
        "close": df["close_idx"].tolist(),
        "amount": df["total_amount"].tolist(),
        "change_pct": df["change_pct"].tolist(),
    }


@router.get("/available-dates")
def available_dates(days: int = Query(60, ge=1, le=250),
                    level: int = Query(2, ge=1, le=2)):
    """返回表中已有的最近 N 个交易日."""
    return {"dates": get_available_dates(level=level, days=days)}


@router.post("/refresh")
def refresh(date: str = Query(None, description="日期 YYYY-MM-DD, 为空则取最新交易日"),
            level: int = Query(2, ge=1, le=2)):
    """启动单日刷新任务."""
    return start_refresh(trade_date=date, level=level)


@router.post("/rebuild")
def rebuild(days: int = Query(20, ge=1, le=250),
            level: int = Query(2, ge=1, le=2),
            end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD, 为空则取最新交易日")):
    """启动批量重建任务."""
    return start_rebuild(days=days, level=level, end_date=end_date)


@router.post("/stop")
def stop():
    """停止当前任务."""
    return stop_current_job()
