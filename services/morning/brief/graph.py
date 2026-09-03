# -*- coding: utf-8 -*-
# 投资晨会 LangGraph 工作流（内嵌于本工作台）
"""
6 节点并行 DAG:

              START
            /        \
           v          v
    industry_node    concept_industry_node
    (板块强度+拐点)    (概念强度+拐点)
           |               |
           v               v
    industry_picker    concept_picker
    (板块成分股选股)    (概念成分股选股)
           \              /
            v            v
            report_node  (两张独立选股表)
                 |
                 v
            push_node

数据为 PostgreSQL AI-Quant；连接见项目根 .env 中 WUCAI_SQL_*。
个股 K 线来自 trade_stock_daily（前复权，含换手率 turnover_rate；与因子库生成/评价口径一致，
等权与因子包两条选股路径统一同源），板块指数来自 trade_sector_daily。
概念指数来自 concept_daily_full。

命令行（CASE-AI 项目根目录）: python -m morning_brief.graph
"""
from __future__ import annotations
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Annotated, List, Dict, TypedDict
from operator import add
import re

import pandas as pd
from langgraph.graph import END, START, StateGraph

from .pusher import push_all

# 晨报落盘目录（本包内 outputs/reports）
THIS_DIR = Path(__file__).resolve().parent


class MorningState(TypedDict, total=False):
    # === 输入 ===
    trigger_time: str
    industry_level: int
    top_n_industries: int
    top_n_concepts: int
    top_n_stocks: int
    lookback_days: int
    sample_stocks: int
    factor_package_id: str   # 因子包ID (可选, 指定后用因子包选股, 否则等权硬编码)

    # === 中间产出 ===
    industry_rank: list
    concept_industry_rank: list
    industry_picked_stocks: list
    concept_picked_stocks: list
    stock_pool: list
    factor_rank: list

    # === 输出 ===
    report_md: str
    report_html: str
    push_result: dict

    # === 审计日志 ===
    messages: Annotated[list, add]


def industry_node(state: dict) -> dict:
    print("\n" + "=" * 70)
    print("  [节点 1] industry_node -- 申万二级板块强度 + 一二阶导拐点")
    print("=" * 70)

    from .lib.rotation_runner import rank_industries_with_phase
    level   = state.get("industry_level", 2)
    top_n   = state.get("top_n_industries", 5)
    df = rank_industries_with_phase(level=level,
                                     lookback_days=state.get("lookback_days", 90),
                                     top_n=top_n)

    rank_list = []
    for ind_name, row in df.iterrows():
        rank_list.append({
            "industry":   ind_name,
            "rank":       int(row["composite_rank"]),
            "score":      round(float(row["composite_score"]), 3),
            "raw_score":  round(float(row["score"]), 3),
            "MOM_21":     round(float(row["MOM_21"]) * 100, 2),
            "RS_60":      round(float(row["RS_60"]) * 100, 2),
            "VOL_R":      round(float(row["VOL_RATIO"]), 2),
            "phase":      row.get("phase", "neutral"),
            "phase_desc": row.get("phase_desc", "中性"),
            "ROC_20":     round(float(row.get("ROC_20", 0)), 2),
            "members":    int(row["member_count"]),
        })

    print(f"  Top {top_n} 板块 (申万 {'一' if level == 1 else '二'} 级):")
    for r in rank_list:
        print(f"    [{r['rank']:>2}] {r['industry']:<14s} "
              f"score={r['score']:+.2f} ({r['phase_desc']:<6s})  "
              f"MOM21={r['MOM_21']:+5.2f}%  RS60={r['RS_60']:+5.2f}%  "
              f"ROC20={r['ROC_20']:+5.2f}%")

    return {
        "industry_rank": rank_list,
        "messages": [{"role": "industry", "time": datetime.now().strftime("%H:%M:%S"),
                      "content": f"Top {top_n} 板块: " + ", ".join(r["industry"] for r in rank_list)}],
    }


# ============================================================
# 节点 1b: 概念轮动分析 (与行业节点并行)
# ============================================================

def concept_industry_node(state: dict) -> dict:
    print("\n" + "=" * 70)
    print("  [节点 1b] concept_industry_node -- 概念板块强度 + 一二阶导拐点")
    print("=" * 70)

    from .lib.concept_rotation_runner import rank_concepts_with_phase
    top_n   = state.get("top_n_concepts", 5)
    df = rank_concepts_with_phase(lookback_days=state.get("lookback_days", 40),
                                   top_n=top_n)

    rank_list = []
    if not df.empty:
        for code, row in df.iterrows():
            rank_list.append({
                "concept_code": code,
                "concept_name": row.get("concept_name", code),
                "rank":         int(row["composite_rank"]),
                "score":        round(float(row["composite_score"]), 3),
                "raw_score":    round(float(row["score"]), 3),
                "MOM_10":       round(float(row["MOM_10"]) * 100, 2),
                "RS_20":        round(float(row["RS_20"]) * 100, 2),
                "VOL_R":        round(float(row["VOL_RATIO"]), 2),
                "phase":        row.get("phase", "neutral"),
                "phase_desc":   row.get("phase_desc", "中性"),
                "ROC_20":       round(float(row.get("ROC_20", 0)), 2),
                "members":      int(row["member_count"]),
            })
    else:
        print("  [WARN] 概念轮动分析无结果")

    print(f"  Top {len(rank_list)} 概念:")
    for r in rank_list:
        print(f"    [{r['rank']:>2}] {r['concept_name']:<20s} "
              f"score={r['score']:+.2f} ({r['phase_desc']:<6s})  "
              f"MOM10={r['MOM_10']:+5.2f}%  RS20={r['RS_20']:+5.2f}%  "
              f"ROC20={r['ROC_20']:+5.2f}%")

    return {
        "concept_industry_rank": rank_list,
        "messages": [{"role": "concept", "time": datetime.now().strftime("%H:%M:%S"),
                      "content": f"Top {len(rank_list)} 概念: " + ", ".join(r["concept_name"] for r in rank_list)}],
    }


# ============================================================
# 通用因子选股流程
# ============================================================

def _do_factor_pick(candidate_codes: List[str],
                     source_map: Dict[str, str],
                     top_n: int,
                     perspective: str = "industry",
                     lookback_days: int = 200) -> List[Dict]:
    """
    通用因子选股流程:
    1. 过滤可交易股票
    2. 批量计算因子
    3. 行业/概念中性化 + 等权合成 alpha
    4. 返回 Top N 标的列表，并预计算每只选中股票的详情解释

    参数:
        lookback_days: 拉取日 K 长度，默认 200。
                       注意：calc_factors_for_one 要求至少 130 根 K 线，若改小此值需同步调整
                       因子计算的最小数据门槛，否则会出现全部"数据不足"。
    """
    from .lib.factor_runner import (
        filter_tradable, calc_factors_batch, preprocess_factors,
        calc_group_scores, explain_stock, load_stock_basic_batch,
        load_stock_concepts_batch, FACTOR_GROUPS, FACTOR_GROUP_DESC,
    )

    codes = filter_tradable(candidate_codes)
    if len(codes) < 5:
        return []

    factor_df = calc_factors_batch(codes, lookback_days=lookback_days, strict_fundamental=True)
    if len(factor_df) < 5:
        return []

    factor_processed = preprocess_factors(factor_df, industry_map=source_map, neutralize=True)

    # 因子缺失处理
    min_valid_ratio = 0.6
    valid_ratio = factor_processed.notna().mean(axis=1)
    usable = factor_processed[valid_ratio >= min_valid_ratio].copy()
    if len(usable) < 5:
        usable = factor_processed.copy()
    factor_filled = usable.fillna(0.0)

    alpha = factor_filled.mean(axis=1).dropna().sort_values(ascending=False)

    # 预计算可解释性数据：分组得分 + 解释说明
    group_scores = calc_group_scores(factor_processed)
    candidate_codes_for_basic = alpha.head(min(top_n * 3, len(alpha))).index.tolist()
    basic_map = load_stock_basic_batch(candidate_codes_for_basic)
    concepts_map = load_stock_concepts_batch(candidate_codes_for_basic)

    picked = []
    for code in candidate_codes_for_basic:
        explanation = explain_stock(factor_processed, group_scores, code)
        raw = factor_df.loc[code].to_dict()
        zsc = factor_processed.loc[code].to_dict()

        alpha_rank = int((alpha >= alpha[code]).sum())
        perspective_detail = {
            "candidate_count": len(codes),
            "alpha": round(float(alpha[code]), 3),
            "alpha_rank": alpha_rank,
            "raw_factors": {k: round(float(v), 3) for k, v in raw.items() if pd.notna(v)},
            "zscore_factors": {k: round(float(v), 3) for k, v in zsc.items() if pd.notna(v)},
            "group_scores": explanation.get("group_scores", {}),
            "top_group": explanation.get("top_group", ""),
            "top_factors": explanation.get("top_factors", []),
        }

        matched_industries = []
        matched_concepts = []
        if perspective == "industry":
            matched_industries = [source_map.get(code, "未分类")]
        else:
            matched_concepts = [source_map.get(code, "未分类")]

        summary = (
            f"{'板块' if perspective == 'industry' else '概念'}视角："
            f"在 {len(codes)} 只候选股中排名第 {alpha_rank}，"
            f"最强维度为「{explanation.get('top_group', '')}」"
        )

        picked.append({
            "code": code,
            "source": source_map.get(code, "未分类"),
            "alpha": perspective_detail["alpha"],
            "raw_factors": perspective_detail["raw_factors"],
            "perspective": perspective,
            "candidate_pool_size": len(codes),
            "detail": {
                "basic": basic_map.get(code, {"code": code, "name": "", "sector_1": "", "sector_2": ""}),
                "relations": {
                    "top_industries": [],
                    "top_concepts": [],
                    "matched_industries": matched_industries,
                    "matched_concepts": matched_concepts,
                    "all_concepts": concepts_map.get(code, []),
                },
                f"{perspective}_perspective": perspective_detail,
                "summary": summary,
                "factor_group_map": FACTOR_GROUPS,
                "factor_group_desc": FACTOR_GROUP_DESC,
            }
        })
    return picked[:top_n]


def _pick_by_package(candidate_codes: List[str],
                     source_map: Dict[str, str],
                     package_id: str,
                     top_n: int,
                     perspective: str = "industry",
                     lookback_days: int = 200) -> Optional[List[Dict]]:
    """用因子包选股 (替代等权硬编码)

    加载因子包 → 逐候选股拉 K 线构造面板 → 按包内因子/权重合成 alpha → 返回 Top N。
    返回 None 表示因子包不存在或无法使用 (调用方回退等权)。
    """
    from lib.factor_db import get_factor_package
    from lib.factor_engine import score_stocks_by_package
    from .lib.factor_runner import (
        filter_tradable, load_kline_from_db, load_stock_basic_batch, load_stock_concepts_batch,
    )

    pkg = get_factor_package(package_id)
    if not pkg:
        print(f"  [WARN] 因子包 {package_id} 不存在, 回退等权选股")
        return None

    codes = filter_tradable(candidate_codes)
    if len(codes) < 5:
        return []

    # 拉 K 线构造面板 (因子包在因子库侧以"前复权 trade_stock_daily + 换手率"口径训练/评价,
    # 消费端须同源, 否则价格类因子截面排序口径不一致、换手率因子缺失)
    panel = {}
    for code in codes:
        df = load_kline_from_db(code, lookback_days=lookback_days, table="trade_stock_daily")
        if not df.empty:
            panel[code] = df

    scored = score_stocks_by_package(pkg, panel, source_map=source_map, top_n=top_n)
    if not scored:
        return []

    # 预计算详情基础信息 (与等权路径保持一致, 但可解释性用因子包因子值)
    top_codes = [s["code"] for s in scored]
    basic_map = load_stock_basic_batch(top_codes)
    concepts_map = load_stock_concepts_batch(top_codes)

    picked = []
    for rank_idx, s in enumerate(scored):
        code = s["code"]
        alpha = s["alpha"]
        raw = s.get("raw_factors", {})
        zsc = s.get("zscore_factors", {})

        # 最强因子: 取 zscore 绝对值最大的前 3 个
        top_factors = sorted(zsc.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]

        matched_industries = []
        matched_concepts = []
        if perspective == "industry":
            matched_industries = [source_map.get(code, "未分类")]
        else:
            matched_concepts = [source_map.get(code, "未分类")]

        perspective_detail = {
            "candidate_count": len(codes),
            "alpha": round(float(alpha), 3),
            "alpha_rank": rank_idx + 1,
            "raw_factors": raw,
            "zscore_factors": zsc,
            "group_scores": {},
            "top_group": pkg.get("name", ""),
            "top_factors": top_factors,
        }

        summary = (
            f"{'板块' if perspective == 'industry' else '概念'}视角 (因子包: {pkg.get('name','')})："
            f"在 {len(codes)} 只候选股中排名第 {rank_idx + 1}，"
            f"综合 alpha={alpha:+.3f}"
        )

        picked.append({
            "code": code,
            "source": source_map.get(code, "未分类"),
            "alpha": round(float(alpha), 3),
            "raw_factors": raw,
            "perspective": perspective,
            "candidate_pool_size": len(codes),
            "detail": {
                "basic": basic_map.get(code, {"code": code, "name": "", "sector_1": "", "sector_2": ""}),
                "relations": {
                    "top_industries": [],
                    "top_concepts": [],
                    "matched_industries": matched_industries,
                    "matched_concepts": matched_concepts,
                    "all_concepts": concepts_map.get(code, []),
                },
                f"{perspective}_perspective": perspective_detail,
                "summary": summary,
                "factor_group_map": {},
                "factor_group_desc": {},
            }
        })
    return picked[:top_n]


# ============================================================
# 节点 2a: 板块成分股多因子选股
# ============================================================

def industry_picker_node(state: dict) -> dict:
    print("\n" + "=" * 70)
    print("  [节点 2a] industry_picker_node -- Top 板块成分股多因子选股")
    print("=" * 70)

    from .lib.rotation_runner import get_sector_member_codes

    industry_rank = state.get("industry_rank", [])
    level = state.get("industry_level", 2)
    if not industry_rank:
        print("  [SKIP] 无行业排名, 跳过选股")
        return {"industry_picked_stocks": []}

    sample_per = state.get("sample_stocks", 20)
    top_n = state.get("top_n_stocks", 5)

    # 收集候选股 + 行业映射
    candidate_codes: List[str] = []
    industry_map: Dict[str, str] = {}
    for r in industry_rank:
        ind_name = r["industry"]
        codes = get_sector_member_codes(ind_name, level=level)[:sample_per]
        candidate_codes.extend(codes)
        for c in codes:
            industry_map[c] = ind_name
    candidate_codes = sorted(set(candidate_codes))

    print(f"  候选股票池: {len(candidate_codes)} 只 (来自 {len(industry_rank)} 个板块)")

    package_id = state.get("factor_package_id", "")
    if package_id:
        picked = _pick_by_package(
            candidate_codes, industry_map, package_id, top_n,
            perspective="industry", lookback_days=state.get("lookback_days", 200),
        )
        if picked is None:
            picked = _do_factor_pick(candidate_codes, industry_map, top_n, perspective="industry")
    else:
        picked = _do_factor_pick(candidate_codes, industry_map, top_n, perspective="industry")

    print(f"  Top {len(picked)} 选中标的 (板块视角):")
    for p in picked:
        print(f"    {p['code']}  [{p['source']:<8s}]  alpha={p['alpha']:+.3f}  "
              f"MOM_3M={p['raw_factors'].get('MOM_3M', 0):+.2%}  "
              f"ROE={p['raw_factors'].get('ROE', 0):.2f}")

    return {
        "industry_picked_stocks": picked,
        "messages": [{"role": "industry_picker", "time": datetime.now().strftime("%H:%M:%S"),
                      "content": f"板块选股 {len(picked)} 只: " + ", ".join(p["code"] for p in picked)}],
    }


# ============================================================
# 节点 2b: 概念成分股多因子选股
# ============================================================

def concept_picker_node(state: dict) -> dict:
    print("\n" + "=" * 70)
    print("  [节点 2b] concept_picker_node -- Top 概念成分股多因子选股")
    print("=" * 70)

    from .lib.concept_rotation_runner import get_concept_member_codes

    concept_rank = state.get("concept_industry_rank", [])
    if not concept_rank:
        print("  [SKIP] 无概念排名, 跳过选股")
        return {"concept_picked_stocks": []}

    sample_per = state.get("sample_stocks", 20)
    top_n = state.get("top_n_stocks", 5)

    # 收集候选股 + 概念映射
    candidate_codes: List[str] = []
    concept_map: Dict[str, str] = {}
    for r in concept_rank:
        concept_name = r.get("concept_name", "")
        concept_code = r.get("concept_code", "")
        if concept_code:
            codes = get_concept_member_codes(concept_code)[:sample_per]
            candidate_codes.extend(codes)
            for c in codes:
                concept_map[c] = concept_name
    candidate_codes = sorted(set(candidate_codes))

    print(f"  候选股票池: {len(candidate_codes)} 只 (来自 {len(concept_rank)} 个概念)")

    package_id = state.get("factor_package_id", "")
    if package_id:
        picked = _pick_by_package(
            candidate_codes, concept_map, package_id, top_n,
            perspective="concept", lookback_days=state.get("lookback_days", 200),
        )
        if picked is None:
            picked = _do_factor_pick(candidate_codes, concept_map, top_n, perspective="concept")
    else:
        picked = _do_factor_pick(candidate_codes, concept_map, top_n, perspective="concept")

    print(f"  Top {len(picked)} 选中标的 (概念视角):")
    for p in picked:
        print(f"    {p['code']}  [{p['source']:<12s}]  alpha={p['alpha']:+.3f}  "
              f"MOM_3M={p['raw_factors'].get('MOM_3M', 0):+.2%}  "
              f"ROE={p['raw_factors'].get('ROE', 0):.2f}")

    return {
        "concept_picked_stocks": picked,
        "messages": [{"role": "concept_picker", "time": datetime.now().strftime("%H:%M:%S"),
                      "content": f"概念选股 {len(picked)} 只: " + ", ".join(p["code"] for p in picked)}],
    }


def report_node(state: dict) -> dict:
    print("\n" + "=" * 70)
    print("  [节点 3] report_node -- 拼装晨报")
    print("=" * 70)

    today_str = datetime.now().strftime("%Y-%m-%d %A")
    industries = state.get("industry_rank", [])
    concepts = state.get("concept_industry_rank", [])
    industry_picked = state.get("industry_picked_stocks", [])
    concept_picked = state.get("concept_picked_stocks", [])

    md_lines = [
        f"# 投资晨会简报 -- {today_str}",
        "",
    ]

    # --- 板块部分 ---
    if industries:
        md_lines += [
            f"## Top {len(industries)} 强势板块 (申万二级)",
            "",
            "| Rank | 板块 | 综合分 | 拐点信号 | 21日动量 | 60日相对强度 | 20日ROC |",
            "|------|------|--------|----------|----------|--------------|---------|",
        ]
        for r in industries:
            md_lines.append(
                f"| {r['rank']} | **{r['industry']}** | {r['score']:+.2f} | "
                f"{r.get('phase_desc', '中性')} | "
                f"{r['MOM_21']:+.2f}% | {r['RS_60']:+.2f}% | {r.get('ROC_20', 0):+.2f}% |"
            )

    if industry_picked:
        md_lines += ["", f"### 板块视角选中标的 ({len(industry_picked)} 只)", ""]
        md_lines.append("| 代码 | 所属板块 | alpha | 3M动量 | ROE | 净利同比 | 毛利率 |")
        md_lines.append("|------|----------|-------|--------|-----|----------|--------|")
        for p in industry_picked:
            md_lines.append(
                f"| `{p['code']}` | {p['source']} | {p['alpha']:+.3f} | "
                f"{p['raw_factors'].get('MOM_3M', 0):+.2%} | "
                f"{p['raw_factors'].get('ROE', 0):.2f} | "
                f"{p['raw_factors'].get('NetProfit_YoY', 0):.2f}% | "
                f"{p['raw_factors'].get('GrossMargin', 0):.2f}% |"
            )

    # --- 概念部分 ---
    if concepts:
        md_lines += ["", f"## Top {len(concepts)} 强势概念板块", ""]
        md_lines.append("| Rank | 概念 | 综合分 | 拐点信号 | 10日动量 | 20日相对强度 | 20日ROC |")
        md_lines.append("|------|------|--------|----------|----------|--------------|---------|")
        for r in concepts:
            md_lines.append(
                f"| {r['rank']} | **{r['concept_name']}** | {r['score']:+.2f} | "
                f"{r.get('phase_desc', '中性')} | "
                f"{r['MOM_10']:+.2f}% | {r['RS_20']:+.2f}% | {r.get('ROC_20', 0):+.2f}% |"
            )

    if concept_picked:
        md_lines += ["", f"### 概念视角选中标的 ({len(concept_picked)} 只)", ""]
        md_lines.append("| 代码 | 所属概念 | alpha | 3M动量 | ROE | 净利同比 | 毛利率 |")
        md_lines.append("|------|----------|-------|--------|-----|----------|--------|")
        for p in concept_picked:
            md_lines.append(
                f"| `{p['code']}` | {p['source']} | {p['alpha']:+.3f} | "
                f"{p['raw_factors'].get('MOM_3M', 0):+.2%} | "
                f"{p['raw_factors'].get('ROE', 0):.2f} | "
                f"{p['raw_factors'].get('NetProfit_YoY', 0):.2f}% | "
                f"{p['raw_factors'].get('GrossMargin', 0):.2f}% |"
            )

    # --- 盘中应对建议 ---
    all_picked = industry_picked + concept_picked
    md_lines += ["", "## 盘中应对建议", ""]
    if all_picked:
        for p in industry_picked:
            md_lines.append(
                f"- [板块] `{p['code']}` ({p['source']}): "
                f"alpha={p['alpha']:+.3f}, 关注开盘 30 分钟方向"
            )
        for p in concept_picked:
            md_lines.append(
                f"- [概念] `{p['code']}` ({p['source']}): "
                f"alpha={p['alpha']:+.3f}, 关注开盘 30 分钟方向"
            )
    else:
        md_lines.append("- 无候选标的, 今日观望")

    md_lines += ["", "---", "",
                 "> 本简报由 AI 量化团队自动生成, 仅供参考, 不构成投资建议",
                 f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]

    report_md = "\n".join(md_lines)

    report_html = _md_to_html(report_md)

    from lib.paths import OUTPUTS_MORNING_DIR
    output_dir = OUTPUTS_MORNING_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = output_dir / f"morning_brief_{ts}.md"
    html_path = output_dir / f"morning_brief_{ts}.html"
    md_path.write_text(report_md, encoding="utf-8")
    html_path.write_text(report_html, encoding="utf-8")

    print(f"  晨报已落盘:")
    print(f"    Markdown: {md_path}")
    print(f"    HTML:     {html_path}")

    return {
        "report_md":   report_md,
        "report_html": str(html_path),
        "messages": [{"role": "report", "time": datetime.now().strftime("%H:%M:%S"),
                      "content": f"晨报生成 {len(report_md)} 字节"}],
    }


def _md_to_html(md: str) -> str:
    lines = md.splitlines()
    out = ["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>",
           "<title>晨会分析简报</title>",
           "<style>",
           "body{font-family:-apple-system,'Microsoft YaHei',sans-serif;max-width:900px;margin:30px auto;padding:0 24px;color:#2c3e50;line-height:1.7}",
           "h1{border-bottom:3px solid #3498db;padding-bottom:10px}",
           "h2{color:#3498db;margin-top:30px}",
           "table{border-collapse:collapse;width:100%;margin:14px 0}",
           "th{background:#34495e;color:#fff;padding:8px 12px;text-align:left}",
           "td{padding:8px 12px;border:1px solid #dee2e6}",
           "tr:nth-child(even){background:#f8f9fa}",
           "code{background:#e8ecef;padding:2px 6px;border-radius:4px;font-family:'Consolas',monospace}",
           "blockquote{border-left:3px solid #95a5a6;color:#555;padding-left:12px;background:#f1f3f5;padding-top:8px;padding-bottom:8px}",
           "</style></head><body>"]

    in_table = False
    table_rows = []
    for line in lines:
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.match(r"^-+$", c) for c in cells):
                continue
            if not in_table:
                in_table = True
                table_rows = ["<table><thead><tr>"]
                for c in cells:
                    table_rows.append(f"<th>{escape(c)}</th>")
                table_rows.append("</tr></thead><tbody>")
            else:
                table_rows.append("<tr>")
                for c in cells:
                    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(c))
                    rendered = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", rendered)
                    table_rows.append(f"<td>{rendered}</td>")
                table_rows.append("</tr>")
            continue
        else:
            if in_table:
                table_rows.append("</tbody></table>")
                out.extend(table_rows)
                in_table = False
                table_rows = []

        if s.startswith("# "):
            out.append(f"<h1>{escape(s[2:])}</h1>")
        elif s.startswith("## "):
            out.append(f"<h2>{escape(s[3:])}</h2>")
        elif s.startswith("- "):
            li_html = re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(s[2:]))
            out.append(f"<li>{li_html}</li>")
        elif s.startswith("> "):
            out.append(f"<blockquote>{escape(s[2:])}</blockquote>")
        elif s == "---":
            out.append("<hr>")
        elif s == "":
            continue
        else:
            p_html = re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(s))
            out.append(f"<p>{p_html}</p>")

    if in_table:
        table_rows.append("</tbody></table>")
        out.extend(table_rows)

    out.append("</body></html>")
    return "\n".join(out)


def push_node(state: dict) -> dict:
    print("\n" + "=" * 70)
    print("  [节点 4] push_node -- 推送钉钉 / 企业微信 / 飞书")
    print("=" * 70)

    title = f"晨会分析 {datetime.now().strftime('%m-%d')}"
    md = state.get("report_md", "")
    if not md:
        print("  [SKIP] 无内容可推送")
        return {"push_result": {}}

    result = push_all(title=title, content=md)
    return {
        "push_result": result,
        "messages": [{"role": "push", "time": datetime.now().strftime("%H:%M:%S"),
                      "content": f"推送结果: {result}"}],
    }


def build_graph():
    g = StateGraph(MorningState)
    g.add_node("industry",         industry_node)
    g.add_node("concept_industry", concept_industry_node)
    g.add_node("industry_picker",  industry_picker_node)
    g.add_node("concept_picker",   concept_picker_node)
    g.add_node("report",           report_node)
    g.add_node("push",             push_node)

    # 板块和概念从 START 并行出发
    g.add_edge(START, "industry")
    g.add_edge(START, "concept_industry")
    # 板块分支: industry -> industry_picker
    g.add_edge("industry",         "industry_picker")
    # 概念分支: concept_industry -> concept_picker
    g.add_edge("concept_industry", "concept_picker")
    # 两条选股分支都完成后汇入 report
    g.add_edge("industry_picker",  "report")
    g.add_edge("concept_picker",   "report")
    g.add_edge("report", "push")
    g.add_edge("push", END)

    return g.compile()


def main():
    from dotenv import load_dotenv
    from lib.paths import ENV_FILE
    load_dotenv(ENV_FILE)

    import argparse
    parser = argparse.ArgumentParser(description="投资晨会工作流")
    parser.add_argument("--level", type=int, choices=[1, 2], default=2,
                        help="申万级别 (默认 2 二级板块)")
    parser.add_argument("--top-industries", type=int, default=5,
                        help="选 Top N 强势板块 (默认 5)")
    parser.add_argument("--top-concepts", type=int, default=5,
                        help="选 Top N 强势概念 (默认 5)")
    parser.add_argument("--top-stocks", type=int, default=5,
                        help="最终输出 Top N 选股 (默认 5)")
    parser.add_argument("--sample-per-industry", type=int, default=20,
                        help="每个板块/概念选取多少只候选股 (默认 20)")
    parser.add_argument("--lookback", type=int, default=90,
                        help="拉多少日 K 线 (默认 90)")
    args = parser.parse_args()

    print()
    print("#" * 70)
    print("# 投资晨会工作流启动")
    print(f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#" * 70)

    graph = build_graph()
    result = graph.invoke({
        "trigger_time":     datetime.now().isoformat(timespec="seconds"),
        "industry_level":   args.level,
        "top_n_industries": args.top_industries,
        "top_n_concepts":   args.top_concepts,
        "top_n_stocks":     args.top_stocks,
        "lookback_days":    args.lookback,
        "sample_stocks":    args.sample_per_industry,
        "messages":         [],
    })

    print("\n" + "#" * 70)
    print("# 工作流执行完成")
    print("#" * 70)
    print()
    print("--- 节点对话历史 ---")
    for m in result.get("messages", []):
        print(f"  [{m['time']}] {m['role']:<14s} | {m['content']}")
    print()
    print(f"晨报路径 (HTML): {result.get('report_html', '')}")
    print(f"推送结果:        {result.get('push_result', {})}")


if __name__ == "__main__":
    main()
