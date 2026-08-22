# -*- coding: utf-8 -*-
# 晨会分析路由 -- REST + SSE
"""
GET  /api/morning/cache         -- 读最近一次缓存
GET  /api/morning/stream?...    -- SSE 流式跑工作流, 推送进度
"""

from __future__ import annotations
import asyncio
import json
import math
import queue
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from lib.paths import setup_sys_path, OUTPUTS_DIR
setup_sys_path()

import numpy as np

router = APIRouter()


def _clean_nan(obj):
    """递归把 float('nan') / inf / -inf 转成 None, 保证 JSON 合法."""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


def _safe_json_dumps(obj, **kwargs) -> str:
    return json.dumps(_clean_nan(obj), **kwargs)

# 缓存目录
CACHE_DIR = OUTPUTS_DIR.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
def _load_latest_cache() -> dict:
    fp = CACHE_DIR / "morning_latest.json"
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(state: dict):
    cache = {
        "saved_at":              datetime.now().isoformat(timespec="seconds"),
        "industry_rank":         state.get("industry_rank", []),
        "concept_industry_rank": state.get("concept_industry_rank", []),
        "industry_picked_stocks": state.get("industry_picked_stocks", []),
        "concept_picked_stocks":  state.get("concept_picked_stocks", []),
        "messages":              state.get("messages", []),
        "report_html":           state.get("report_html", ""),
    }
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    (CACHE_DIR / f"morning_{ts}.json").write_text(
        _safe_json_dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    (CACHE_DIR / "morning_latest.json").write_text(
        _safe_json_dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------
@router.get("/cache")
def get_cache():
    """读最近一次晨会缓存"""
    cache = _load_latest_cache()
    if not cache:
        return {"error": "暂无缓存. 先点 '一键触发晨会' 跑一次"}
    return cache


def _load_stock_basic(code: str) -> dict:
    """读取股票基本信息"""
    from morning_brief.lib.db_config import execute_query
    rows = execute_query(
        "SELECT stock_code, stock_name, sector_1, sector_2 FROM trade_stock_status WHERE stock_code = %s",
        (code,)
    )
    if not rows:
        return {}
    r = rows[0]
    return {
        "code": r["stock_code"],
        "name": r["stock_name"] or "",
        "sector_1": r["sector_1"] or "",
        "sector_2": r["sector_2"] or "",
    }


def _build_source_map(rank_list: list, member_fn, sample: int, key_name: str) -> tuple:
    """构建候选池与 source 映射"""
    pool = []
    source_map = {}
    for r in rank_list:
        source = r[key_name]
        codes = member_fn(r)[:sample]
        pool.extend(codes)
        for c in codes:
            source_map[c] = source
    # 去重，保留第一次出现的 source
    seen = set()
    unique_pool = []
    for c in pool:
        if c not in seen:
            seen.add(c)
            unique_pool.append(c)
    return unique_pool, source_map


def _calc_perspective(target_code: str,
                       pool_codes: list,
                       source_map: dict,
                       lookback_days: int) -> Optional[dict]:
    """计算某股票在特定候选池（板块视角 or 概念视角）下的因子与解释"""
    from morning_brief.lib.factor_runner import (
        filter_tradable, calc_factors_batch, preprocess_factors,
        calc_group_scores, explain_stock,
    )
    if target_code not in pool_codes:
        return None
    codes = filter_tradable(pool_codes)
    if target_code not in codes:
        return None
    factor_df = calc_factors_batch(codes, lookback_days=lookback_days, strict_fundamental=True)
    if factor_df.empty or target_code not in factor_df.index:
        return None
    processed = preprocess_factors(factor_df, industry_map=source_map, neutralize=True)

    # 与 graph.py 中 _do_factor_pick 保持一致：
    # 先按有效覆盖率过滤，缺失值填 0 后等权合成 alpha，保证详情页排名与晨会选股一致。
    min_valid_ratio = 0.6
    valid_ratio = processed.notna().mean(axis=1)
    usable = processed[valid_ratio >= min_valid_ratio].copy()
    if len(usable) < 5:
        usable = processed.copy()
    factor_filled = usable.fillna(0.0)

    alpha = factor_filled.mean(axis=1).dropna().sort_values(ascending=False)
    group_scores = calc_group_scores(processed)
    explanation = explain_stock(processed, group_scores, target_code)

    raw = factor_df.loc[target_code].to_dict()
    zsc = processed.loc[target_code].to_dict()
    return {
        "candidate_count": len(codes),
        "alpha": round(float(alpha.get(target_code, np.nan)), 3) if target_code in alpha.index else None,
        "alpha_rank": int((alpha >= alpha.get(target_code)).sum()) if target_code in alpha.index else None,
        "raw_factors": {k: round(float(v), 3) for k, v in raw.items() if pd.notna(v)},
        "zscore_factors": {k: round(float(v), 3) for k, v in zsc.items() if pd.notna(v)},
        "group_scores": explanation.get("group_scores", {}),
        "top_group": explanation.get("top_group", ""),
        "top_factors": explanation.get("top_factors", []),
    }


@router.get("/stock-detail")
def stock_detail(
    code: str = Query(..., description="股票代码"),
    top_industries: int = Query(3, ge=1, le=10),
    top_concepts: int = Query(3, ge=1, le=10),
    sample_per_industry: int = Query(15, ge=5, le=50),
    lookback: int = Query(90, ge=60, le=250),
):
    """
    返回某只推荐股票的详细可解释性信息：
    - 基本信息
    - 所属强相关板块/概念
    - 工作流中计算的因子原始值与标准化得分
    - 分组得分与选中原因
    """
    from morning_brief.lib.rotation_runner import (
        rank_industries_with_phase, get_sector_member_codes,
    )
    from morning_brief.lib.concept_rotation_runner import (
        rank_concepts_with_phase, get_concept_member_codes,
    )
    import pandas as pd

    basic = _load_stock_basic(code)
    if not basic:
        return {"ok": False, "error": f"未找到股票 {code} 的基本信息"}

    # 当前强势板块/概念
    industries = rank_industries_with_phase(
        level=2, lookback_days=lookback, top_n=top_industries
    )
    concepts = rank_concepts_with_phase(
        lookback_days=max(lookback, 30), top_n=top_concepts
    )

    industry_rank = []
    if not industries.empty:
        for name, row in industries.iterrows():
            industry_rank.append({
                "industry": name,
                "rank": int(row["composite_rank"]),
                "score": round(float(row["composite_score"]), 3),
            })

    concept_rank = []
    if not concepts.empty:
        for code_idx, row in concepts.iterrows():
            concept_rank.append({
                "concept_code": code_idx,
                "concept_name": row.get("concept_name", code_idx),
                "rank": int(row["composite_rank"]),
                "score": round(float(row["composite_score"]), 3),
            })

    # 构建候选池
    industry_pool, industry_map = _build_source_map(
        industry_rank,
        lambda r: get_sector_member_codes(r["industry"], level=2),
        sample_per_industry,
        "industry",
    )
    concept_pool, concept_map = _build_source_map(
        concept_rank,
        lambda r: get_concept_member_codes(r["concept_code"]),
        sample_per_industry,
        "concept_name",
    )

    # 计算两个视角：因子计算需要至少 130 根 K 线，详情口径固定用 200 天，
    # 与 graph.py 中 _do_factor_pick 保持一致，避免预计算 detail 与 API 回退结果不一致。
    DETAIL_LOOKBACK_DAYS = 200
    industry_detail = _calc_perspective(code, industry_pool, industry_map, DETAIL_LOOKBACK_DAYS)
    concept_detail = _calc_perspective(code, concept_pool, concept_map, DETAIL_LOOKBACK_DAYS)

    # 汇总关联关系：若目标股出现在候选池中，则其来源板块/概念即为强相关项
    matched_industries = sorted({industry_map[code]}) if code in industry_pool else []
    matched_concepts = sorted({concept_map[code]}) if code in concept_pool else []

    # 生成一句话解释
    reasons = []
    if industry_detail:
        reasons.append(
            f"板块视角：在 {industry_detail['candidate_count']} 只候选股中排名第 "
            f"{industry_detail['alpha_rank']}，最强维度为「{industry_detail['top_group']}」"
        )
    if concept_detail:
        reasons.append(
            f"概念视角：在 {concept_detail['candidate_count']} 只候选股中排名第 "
            f"{concept_detail['alpha_rank']}，最强维度为「{concept_detail['top_group']}」"
        )
    summary = "；".join(reasons) if reasons else "该股票不在当前 Top 板块/概念的成分股中，未被选股流程覆盖。"

    from morning_brief.lib.factor_runner import (
        FACTOR_GROUPS, FACTOR_GROUP_DESC, load_stock_concepts_batch,
    )

    all_concepts = load_stock_concepts_batch([code]).get(code, [])

    return _clean_nan({
        "ok": True,
        "basic": basic,
        "relations": {
            "top_industries": industry_rank,
            "top_concepts": concept_rank,
            "matched_industries": matched_industries,
            "matched_concepts": matched_concepts,
            "all_concepts": all_concepts,
        },
        "industry_perspective": industry_detail,
        "concept_perspective": concept_detail,
        "summary": summary,
        "factor_group_map": FACTOR_GROUPS,
        "factor_group_desc": FACTOR_GROUP_DESC,
    })


# ------------------------------------------------------------
NODE_LABELS = {
    "industry":         "[1/6] industry -- 读库算板块强度与拐点（默认申万二级）",
    "concept_industry": "[2/6] concept_industry -- 读库算概念强度与拐点",
    "industry_picker":  "[3/6] industry_picker -- Top 板块成分股多因子选股",
    "concept_picker":   "[4/6] concept_picker -- Top 概念成分股多因子选股",
    "report":           "[5/6] report -- 拼装晨报 HTML",
    "push":             "[6/6] push -- 推送到钉钉/微信",
}
NODE_EST = {
    "industry":         "读 PostgreSQL 板块/指数表并排名",
    "concept_industry": "读 PostgreSQL 概念指数表并排名",
    "industry_picker":  "读个股日 K 算因子（板块视角）",
    "concept_picker":   "读个股日 K 算因子（概念视角）",
    "report":           "~1 秒",
    "push":             "~1 秒",
}
NODE_ORDER = ["industry", "concept_industry", "industry_picker", "concept_picker", "report", "push"]


@router.get("/stream")
async def stream(
    top_industries: int = Query(3),
    top_concepts: int = Query(3),
    top_stocks: int = Query(5),
    sample_per_industry: int = Query(15),
    lookback: int = Query(90),
    package_id: str = Query(""),
):
    """SSE 流式触发晨会, 边跑边推中间状态"""

    initial_state = {
        "trigger_time":     datetime.now().isoformat(timespec="seconds"),
        "top_n_industries": top_industries,
        "top_n_concepts":   top_concepts,
        "top_n_stocks":     top_stocks,
        "sample_stocks":    sample_per_industry,
        "lookback_days":    lookback,
        "factor_package_id": package_id,
        "messages":         [],
    }

    accumulated_state = dict(initial_state)
    accumulated_state["messages"] = []
    chunk_queue: "queue.Queue" = queue.Queue()

    def worker():
        try:
            from morning_brief.graph import build_graph
            graph = build_graph()
            for chunk in graph.stream(initial_state, stream_mode="updates"):
                chunk_queue.put(("update", chunk))
            chunk_queue.put(("done", None))
        except Exception as e:
            chunk_queue.put(("error", e))

    th = threading.Thread(target=worker, daemon=True)
    th.start()

    async def event_gen():
        current_node = NODE_ORDER[0]
        started_at = time.time()

        # 立刻发一次
        yield {
            "event": "progress",
            "data": _safe_json_dumps({
                "current_node": current_node,
                "estimate":     NODE_EST.get(current_node, ""),
                "message":      "准备启动 6 节点工作流（板块 + 概念并行）",
            }),
        }

        last_progress_at = time.time()
        while True:
            # 拿一条 chunk (不阻塞太久, 1 秒内即返回)
            try:
                kind, payload = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: chunk_queue.get(timeout=1.0)
                )
            except queue.Empty:
                kind, payload = None, None

            if kind == "update":
                chunk = payload
                node_name = list(chunk.keys())[0]
                delta = chunk[node_name]

                # 累积
                for k, v in delta.items():
                    if k == "messages" and isinstance(v, list):
                        accumulated_state.setdefault("messages", []).extend(v)
                    else:
                        accumulated_state[k] = v

                # 推断下一个节点
                if node_name in NODE_ORDER:
                    idx = NODE_ORDER.index(node_name)
                    if idx + 1 < len(NODE_ORDER):
                        current_node = NODE_ORDER[idx + 1]

                yield {
                    "event": "node_done",
                    "data": _safe_json_dumps({
                        "node":                    node_name,
                        "node_label":              NODE_LABELS.get(node_name, node_name),
                        "industry_rank":           accumulated_state.get("industry_rank", []),
                        "concept_industry_rank":   accumulated_state.get("concept_industry_rank", []),
                        "industry_picked_stocks":  accumulated_state.get("industry_picked_stocks", []),
                        "concept_picked_stocks":   accumulated_state.get("concept_picked_stocks", []),
                        "messages":                accumulated_state.get("messages", []),
                    }),
                }
                last_progress_at = time.time()
                continue

            if kind == "done":
                # 落盘缓存
                try:
                    _save_cache(accumulated_state)
                except Exception:
                    pass
                yield {
                    "event": "done",
                    "data": _safe_json_dumps({
                        "industry_rank":           accumulated_state.get("industry_rank", []),
                        "concept_industry_rank":   accumulated_state.get("concept_industry_rank", []),
                        "industry_picked_stocks":  accumulated_state.get("industry_picked_stocks", []),
                        "concept_picked_stocks":   accumulated_state.get("concept_picked_stocks", []),
                        "messages":                accumulated_state.get("messages", []),
                        "report_html":             accumulated_state.get("report_html", ""),
                    }),
                }
                break

            if kind == "error":
                yield {
                    "event": "error_event",
                    "data": _safe_json_dumps({
                        "error": f"{type(payload).__name__}: {payload}",
                    }),
                }
                break

            # 心跳 (每 1.5 秒)
            now = time.time()
            if now - last_progress_at > 1.5:
                last_progress_at = now
                yield {
                    "event": "progress",
                    "data": _safe_json_dumps({
                        "current_node": current_node,
                        "estimate":     NODE_EST.get(current_node, ""),
                        "message":      f"已运行 {now - started_at:.1f} 秒",
                    }),
                }

    return EventSourceResponse(event_gen())
