# -*- coding: utf-8 -*-
"""概念轮动页面 API.

提供:
- GET  /api/concept-rotation/status     当前任务状态
- GET  /api/concept-rotation/matrix     概念轮动热力图数据
- GET  /api/concept-rotation/detail     单概念某日明细
- GET  /api/concept-rotation/concept-index  单概念指数 K 线
- GET  /api/concept-rotation/available-dates  表中已有日期
- POST /api/concept-rotation/refresh    刷新某日数据
- POST /api/concept-rotation/rebuild    重建最近 N 日数据
- POST /api/concept-rotation/stop       停止当前任务

实现迁移至 services/rotation/ 统一引擎 (与板块轮动共用), 对外契约不变。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from lib.stock_utils import get_stock_info
from services.rotation.dimension import CONCEPT
from services.rotation.indicator_notes import get_note_concept as get_note
from services.rotation.rotation_store import CONCEPT_STORE
from services.rotation.rotation_worker import CONCEPT_WORKER

router = APIRouter()


@router.get("/status")
def status():
    """返回当前后台任务状态."""
    return CONCEPT_WORKER.get_status()


@router.get("/matrix")
def matrix(days: int = Query(20, ge=1, le=120),
           top_n: int = Query(15, ge=1, le=50),
           end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD, 为空则取最新交易日")):
    """返回指定结束日期前 N 个交易日、每日 Top N 概念的排名矩阵."""
    df = CONCEPT_STORE.load_matrix(days=days, top_n=top_n, end_date=end_date)
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
            "concept_code": row["concept_code"],
            "concept_name": row["concept_name"],
            "source_prefix": row.get("source_prefix", ""),
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
def detail(concept_code: str = Query(..., description="概念编码"),
           date: str = Query(..., description="日期 YYYY-MM-DD"),
           history_days: int = Query(60, ge=5, le=250)):
    """返回某概念某日期的明细 + 近期历史."""
    row = CONCEPT_STORE.get_detail(concept_code, date)
    if not row:
        return {"ok": False, "error": "未找到数据"}

    # 数值字段转原生类型
    float_fields = [
        "score", "composite_score",
        CONCEPT.mom_z_col, CONCEPT.rs_z_col, "vol_ratio_z",
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
    hist_df = CONCEPT_STORE.get_history(concept_code, days=history_days)
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

    # 相关性最高的 5 只股票 (concept 按名称查, 多返回 corr/leader)
    relevant_stocks = []
    concept_name = detail_data.get("concept_name", concept_code)
    for item in CONCEPT_STORE.get_top_relevant_stocks(concept_name, date, limit=5):
        info = get_stock_info(item["stock_code"])
        relevant_stocks.append({
            "code": item["stock_code"],
            "name": info.get("name", ""),
            "total_score": item["total_score"],
            "corr_score": item["corr_score"],
            "leader_score": item["leader_score"],
        })

    return {
        "ok": True,
        "detail": detail_data,
        "notes": notes,
        "history": history,
        "relevant_stocks": relevant_stocks,
    }


@router.get("/concept-index")
def concept_index(concept_code: str = Query(..., description="概念编码"),
                  years: int = Query(1, ge=1, le=3)):
    """返回某概念指数近 N 年的日 K 线."""
    df = CONCEPT_STORE.get_item_index(concept_code, years=years)
    if df.empty:
        return {"ok": False, "error": "未找到概念指数数据"}
    return {
        "ok": True,
        "dates": df["trade_date"].tolist(),
        "close": df["close_idx"].tolist(),
        "amount": df["total_amount"].tolist(),
        "change_pct": df["change_pct"].tolist(),
    }


@router.get("/available-dates")
def available_dates(days: int = Query(60, ge=1, le=250)):
    """返回表中已有的最近 N 个交易日."""
    return {"dates": CONCEPT_STORE.get_available_dates(days=days)}


@router.post("/refresh")
def refresh(date: str = Query(None, description="日期 YYYY-MM-DD, 为空则取最新交易日")):
    """启动单日刷新任务."""
    return CONCEPT_WORKER.start_refresh(trade_date=date)


@router.post("/rebuild")
def rebuild(days: int = Query(20, ge=1, le=250),
            end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD, 为空则取最新交易日")):
    """启动批量重建任务."""
    return CONCEPT_WORKER.start_rebuild(days=days, end_date=end_date)


@router.post("/stop")
def stop():
    """停止当前任务."""
    return CONCEPT_WORKER.stop_current_job()
