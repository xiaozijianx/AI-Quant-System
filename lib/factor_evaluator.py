# -*- coding: utf-8 -*-
# 因子批量性能评估模块
"""
对 factor_library 中已导入的因子做批量性能分析:
    1. 选取成交活跃的真实个股池 (过滤指数代码)
    2. 一次性加载股票池日K面板
    3. 在多个调仓日计算因子截面值 + 未来收益
    4. 计算单因子 IC/RankIC/IR/IC胜率/分层回测/多空收益
    5. 将结果持久化到 factor_metrics 表

依赖:
    - lib/factor_engine.py: calc_basic_factors (计算 12 个基础因子截面值)
    - lib/factor_db.py:     save_metrics (写入性能指标)
    - lib/backtest_data.py: load_daily_kline (加载日K)

calc_basic_factors 返回的因子 key 与 factor_library.factor_id 的映射:
    MOM_1M / MOM_3M / MOM_6M / REV_5D / VOL_20 / VOL_60 / LIQ_20 / TURN_20
    RSI_14 / BIAS_20  -- 名称一致
    ATR_NORM_14 -> atr_norm_14  (大小写不一致)
    MACD_DIF    -> macd_dif     (大小写不一致)
    VOL_RATIO_20 -> vol_ratio_20 (factor_init 中无此 ID, 跳过)
"""

from __future__ import annotations
import math
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from lib.factor_db import save_metrics, list_factors
from lib.factor_engine import calc_basic_factors, preprocess_factors


# ============================================================
# 一、calc_basic_factors 返回 key -> factor_library.factor_id 映射
# ============================================================

# calc_basic_factors 能计算的因子 key (来自 factor_engine.py)
# 注: 旧量比命名因子(TURN_20/turnover_ratio/turnover_change_5d)已硬删除,
#     由 vol_ratio_20/vol_ratio_20_low/vol_ratio_change_5d 取代
_CALCABLE_KEYS = [
    "MOM_1M", "MOM_3M", "MOM_6M",
    "REV_5D",
    "VOL_20", "VOL_60",
    "LIQ_20", "vol_ratio_20", "vol_ratio_20_low",
    "RSI_14", "BIAS_20",
    "ATR_NORM_14", "MACD_DIF",
]

# key -> factor_id 映射 (处理大小写不一致)
_KEY_TO_FACTOR_ID = {
    "MOM_1M": "MOM_1M",
    "MOM_3M": "MOM_3M",
    "MOM_6M": "MOM_6M",
    "REV_5D": "REV_5D",
    "VOL_20": "VOL_20",
    "VOL_60": "VOL_60",
    "LIQ_20": "LIQ_20",
    "vol_ratio_20": "vol_ratio_20",
    "vol_ratio_20_low": "vol_ratio_20_low",
    "RSI_14": "RSI_14",
    "BIAS_20": "BIAS_20",
    "ATR_NORM_14": "atr_norm_14",
    "MACD_DIF": "macd_dif",
}


def get_calcable_factor_ids() -> List[str]:
    """返回当前可通过 calc_basic_factors 计算的 factor_id 列表"""
    return list(_KEY_TO_FACTOR_ID.values())


# ============================================================
# 二、获取成交活跃的真实个股池
# ============================================================

def get_active_stock_pool(n: int = 80,
                          min_days: int = 200,
                          recent_days: int = 30) -> List[str]:
    """
    从 trade_stock_daily 选取最近成交活跃的真实个股 (过滤指数)

    过滤规则:
        - 排除指数代码: 以 000/399/880 开头且属于指数的 (简化: 排除 0000xx.SH / 399xxx.SZ / 880xxx.SH)
        - 保留: 6xxxxx.SH(沪市) / 0xxxxx.SZ(深市主板) / 3xxxxx.SZ(创业板) / 688xxx.SH(科创板) / 8xxxxx.BJ(北交所)

    参数:
        n:           返回股票数量
        min_days:    全历史最少交易日数 (保证有足够历史做性能分析)
        recent_days: 统计成交活跃度的近 N 天
    """
    import psycopg2
    from lib.factor_db import _db_config

    today = date.today()
    start = pd.Timestamp(today) - pd.Timedelta(days=recent_days * 2)
    start_str = start.strftime("%Y-%m-%d")

    # 第一步: 查近 recent_days 天成交额 top N*3, 只查真实个股 (排除指数)
    # 沪市: 6%.SH (主板+科创板)  深市: 0%.SZ(主板) / 300%.SZ / 301%.SZ(创业板)  北交所: 8%.BJ/4%.BJ
    # 注意: 不能用 3%.SZ, 会匹配到 399xxx 深市指数; LIKE 模式作为参数传入避免 % 冲突
    sql_active = """
        SELECT stock_code, SUM(volume) AS total_vol
        FROM trade_stock_daily
        WHERE trade_date >= %s
          AND (
            stock_code LIKE %s
            OR stock_code LIKE %s
            OR stock_code LIKE %s
            OR stock_code LIKE %s
            OR stock_code LIKE %s
            OR stock_code LIKE %s
          )
        GROUP BY stock_code
        ORDER BY total_vol DESC
        LIMIT %s
    """
    conn = psycopg2.connect(**_db_config())
    try:
        cur = conn.cursor()
        cur.execute(sql_active, (start_str,
                                  '6%.SH', '0%.SZ', '300%.SZ', '301%.SZ', '8%.BJ', '4%.BJ',
                                  n * 3))
        candidates = [row[0] for row in cur.fetchall()]
        cur.close()

        if not candidates:
            return []

        # 第二步: 查这些候选的全历史交易日数, 过滤 >= min_days
        placeholders = ",".join(["%s"] * len(candidates))
        sql_days = f"""
            SELECT stock_code, COUNT(*) AS total_days
            FROM trade_stock_daily
            WHERE stock_code IN ({placeholders})
            GROUP BY stock_code
        """
        cur = conn.cursor()
        cur.execute(sql_days, candidates)
        days_map = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
    finally:
        conn.close()

    # 过滤: 真实个股 + 历史天数 >= min_days
    pool = []
    for code in candidates:
        if _is_real_stock(code) and days_map.get(code, 0) >= min_days:
            pool.append(code)
        if len(pool) >= n:
            break
    return pool


def _is_real_stock(code: str) -> bool:
    """判断是否为真实个股 (排除指数/基金等)"""
    if "." not in code:
        return False
    pure, market = code.split(".", 1)
    # 沪市个股: 6 开头 (主板) / 688 开头 (科创板)
    if market == "SH":
        return pure.startswith("6")
    # 深市个股: 000/001/002/003 开头 (主板+中小板) / 300/301 开头 (创业板)
    if market == "SZ":
        return pure[:3] in ("000", "001", "002", "003", "300", "301")
    # 北交所: 8/4 开头
    if market == "BJ":
        return pure.startswith("8") or pure.startswith("4")
    return False


# ============================================================
# 二-bis、多种股票池推荐 (活跃/申万行业/概念/常见指数/自定义)
# ============================================================

# 常见指数 -> 中证指数代码 (akshare index_stock_cons_csindex 抓取成分股)
_INDEX_POOLS = [
    {"code": "000016", "name": "上证50"},
    {"code": "000300", "name": "沪深300"},
    {"code": "000905", "name": "中证500"},
    {"code": "000852", "name": "中证1000"},
]


def _query_rows(sql: str, params: Optional[list] = None) -> List[tuple]:
    """执行SQL查询, 返回原始行列表 (元组)"""
    import psycopg2
    from lib.factor_db import _db_config
    conn = psycopg2.connect(**_db_config())
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def _normalize_custom_code(token: str) -> str:
    """把用户输入的股票代码规范化为带市场后缀格式 (600519 -> 600519.SH)"""
    token = token.strip().upper()
    if "." in token:
        pure, market = token.split(".", 1)
        if market in ("SH", "SZ", "BJ"):
            return f"{pure}.{market}"
        return ""
    if token.isdigit():
        if token.startswith("6"):
            return f"{token}.SH"
        if token.startswith(("0", "3")):
            return f"{token}.SZ"
        if token.startswith(("8", "4")):
            return f"{token}.BJ"
    return ""


def _parse_custom_codes(text: str) -> List[str]:
    """解析用户自定义输入的股票代码 (逗号/分号/换行/空格分隔)"""
    import re as _re
    codes = []
    for token in _re.split(r"[,，;；\s\n]+", str(text)):
        code = _normalize_custom_code(token)
        if code and code not in codes:
            codes.append(code)
    return codes


def _query_history_days(codes: List[str]) -> Dict[str, int]:
    """查询每只股票的全历史交易日数"""
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    sql = (f"SELECT stock_code, COUNT(*) AS d FROM trade_stock_daily "
           f"WHERE stock_code IN ({placeholders}) GROUP BY stock_code")
    rows = _query_rows(sql, codes)
    return {r[0]: r[1] for r in rows}


def _rank_by_volume(codes: List[str], recent_days: int = 30) -> List[str]:
    """按近期成交额从高到低排序股票"""
    if not codes:
        return []
    placeholders = ",".join(["%s"] * len(codes))
    start = (pd.Timestamp(date.today()) - pd.Timedelta(days=recent_days * 2)).strftime("%Y-%m-%d")
    sql = (f"SELECT stock_code, SUM(volume) AS v FROM trade_stock_daily "
           f"WHERE trade_date >= %s AND stock_code IN ({placeholders}) "
           f"GROUP BY stock_code ORDER BY v DESC")
    rows = _query_rows(sql, [start] + codes)
    return [r[0] for r in rows]


def _resolve_pool_codes(codes: List[str], n: int, min_days: int) -> List[str]:
    """统一处理池成分: 过滤历史天数>=min_days, 按近期成交额排序取前n"""
    if not codes:
        return []
    unique = list(dict.fromkeys(codes))
    days_map = _query_history_days(unique)
    valid = [c for c in unique if days_map.get(c, 0) >= min_days]
    if not valid:
        return []
    return _rank_by_volume(valid)[:n]


def get_stock_pool_options() -> Dict[str, Any]:
    """返回可选的股票池清单 (供前端下拉三级联动)

    返回: {
        pool_types: [ {pool_type, label} ],   # 顶级类型
        industries: [ {ref, count} ],         # 申万一级行业列表
        concepts:   [ {ref, count} ],         # 热门概念列表
        indexes:    [ {ref, label} ],         # 常见指数列表
    }
    """
    # 1. 申万一级行业 (按成分数量排序)
    industries = []
    try:
        rows = _query_rows(
            "SELECT sector_1 AS ref, COUNT(*) AS cnt FROM trade_stock_status "
            "WHERE sector_1 IS NOT NULL AND sector_1 <> '' "
            "GROUP BY sector_1 ORDER BY cnt DESC LIMIT 50", None)
        industries = [{"ref": r[0], "count": r[1]} for r in rows]
    except Exception:
        pass
    # 2. 板块 (板块-股票强相关口径, 取相关性匹配表最新一期)
    sectors = []
    try:
        rows = _query_rows(
            "SELECT sector_name AS ref, COUNT(*) AS cnt "
            "FROM sector_stock_relevance "
            "WHERE calc_date = (SELECT MAX(calc_date) FROM sector_stock_relevance) "
            "GROUP BY sector_name ORDER BY cnt DESC LIMIT 200", None)
        sectors = [{"ref": r[0], "count": r[1]} for r in rows]
    except Exception:
        pass
    # 3. 概念 (概念-股票强相关口径, 每只股票保留 Top-K 强相关概念)
    concepts = []
    try:
        rows = _query_rows(
            "SELECT concept_name AS ref, COUNT(*) AS cnt "
            "FROM concept_stock_relevance "
            "WHERE calc_date = (SELECT MAX(calc_date) FROM concept_stock_relevance) "
            "  AND rank_in_stock <= 5 "
            "GROUP BY concept_name ORDER BY cnt DESC LIMIT 300", None)
        concepts = [{"ref": r[0], "count": r[1]} for r in rows]
    except Exception:
        pass
    # 4. 常见指数
    indexes = [{"ref": p["code"], "label": p["name"]} for p in _INDEX_POOLS]
    # 5. 顶级类型 (single=单股模式, 走时间序列IC, 来源: 机器学习CASE 茅台)
    pool_types = [
        {"pool_type": "active", "label": "成交活跃股(自动)"},
        {"pool_type": "industry", "label": "申万行业"},
        {"pool_type": "sector", "label": "板块"},
        {"pool_type": "concept", "label": "概念"},
        {"pool_type": "index", "label": "常见指数"},
        {"pool_type": "custom", "label": "自定义代码"},
        {"pool_type": "single", "label": "单股模式(时间序列IC)"},
    ]
    return {
        "pool_types": pool_types,
        "industries": industries,
        "sectors": sectors,
        "concepts": concepts,
        "indexes": indexes,
    }


def get_pool_stocks(pool_type: str, ref: str = "", n: int = 80,
                    min_days: int = 200) -> List[str]:
    """根据池类型 + 子项引用构建股票池代码列表

    参数:
        pool_type: active/industry/concept/index/custom
        ref:       子项引用 (行业名/概念名/指数代码/自定义代码文本)
        n:         返回股票数量
        min_days:  最少历史交易日数
    """
    if pool_type == "active":
        return get_active_stock_pool(n=n, min_days=min_days)
    if pool_type == "industry":
        rows = _query_rows(
            "SELECT stock_code FROM trade_stock_status WHERE sector_1 = %s", [ref])
        return _resolve_pool_codes([r[0] for r in rows], n, min_days)
    if pool_type == "sector":
        # 板块: 板块-股票强相关匹配 (最近一期, 取板块内强相关个股)
        rows = _query_rows(
            "SELECT DISTINCT stock_code FROM sector_stock_relevance "
            "WHERE sector_name = %s "
            "AND calc_date = (SELECT MAX(calc_date) FROM sector_stock_relevance) "
            "AND rank_in_sector <= 50",
            [ref])
        return _resolve_pool_codes([r[0] for r in rows], n, min_days)
    if pool_type == "concept":
        # 概念: 概念-股票强相关匹配 (最近一期, 每股票 Top-K 强相关概念)
        rows = _query_rows(
            "SELECT DISTINCT stock_code FROM concept_stock_relevance "
            "WHERE concept_name = %s "
            "AND calc_date = (SELECT MAX(calc_date) FROM concept_stock_relevance) "
            "AND rank_in_stock <= 5",
            [ref])
        return _resolve_pool_codes([r[0] for r in rows], n, min_days)
    if pool_type == "index":
        return _get_index_stocks(ref, n=n, min_days=min_days)
    if pool_type == "custom":
        return _parse_custom_codes(ref)
    return []


def _get_index_stocks(index_code: str, n: int = 80, min_days: int = 200) -> List[str]:
    """通过 akshare 拉取常见指数成分股 (中证指数网, 需联网)"""
    import akshare as ak
    df = ak.index_stock_cons_csindex(symbol=index_code)
    codes = []
    for _, row in df.iterrows():
        pure = str(row.get("成分券代码", "")).strip()
        exchange = str(row.get("交易所", ""))
        if not pure:
            continue
        if "上海" in exchange:
            suffix = "SH"
        elif "深圳" in exchange:
            suffix = "SZ"
        else:
            suffix = "BJ"
        code = f"{pure}.{suffix}"
        if _is_real_stock(code) and code not in codes:
            codes.append(code)
    return _resolve_pool_codes(codes, n, min_days)


# ============================================================
# 三、批量性能评估核心
# ============================================================

def _has_computable_formula(f: Dict[str, Any]) -> bool:
    """公式本身可计算: formula 非空、无中文描述、含函数调用语法
    (D组文字公式因子缺引擎, 不满足此条件)"""
    formula = f.get("formula") or ""
    if not formula:
        return False
    if any('\u4e00' <= ch <= '\u9fff' for ch in formula):
        return False
    return '(' in formula


def _is_evaluable_factor(f: Dict[str, Any]) -> bool:
    """判断因子是否可计算 (与 routes/factor.py 的 /evaluable 判定一致):
    显式 evaluation_type=none 的因子不可评价(构造中间字段/待配引擎);
    其余要求 formula 非空、无中文描述、含函数调用语法。"""
    if (f.get("evaluation_type") or "").strip().lower() == "none":
        return False
    return _has_computable_formula(f)


# ============================================================
# D5 单因子诊断增强 (2026-08-15, 详见 docs/因子库D组文字化因子处理计划.md 第九节)
#   1. 多持有期衰减: 同一因子值在调仓日对未来 1/5/10/20 日收益的 IC 均值
#   2. 分年度IC稳定性: 对 ic_series 按年聚合(均值/标准差/正IC占比)
#   3. 中性化前后IC对比: 由 routes/factor.py /evaluate 在 neutralize 非 none 时
#      追加一次"未中性化"的 IC 计算, 与本函数无关(见路线代码)
# ============================================================

def compute_ic_decay(factor_values: pd.DataFrame,
                     prices_panel: Dict[str, pd.DataFrame],
                     rebal_period: int = 21,
                     min_warmup: int = 130,
                     horizons: tuple = (1, 5, 10, 20)) -> List[Dict[str, Any]]:
    """多持有期IC衰减: 在固定调仓日上, 用同一因子值分别对 1/5/10/20 日未来收益算 IC

    用途: 判断因子预测力的衰减速度, 辅助选择最优调仓/持有周期。
    口径: 与 run_ic_timeseries_panel 一致(截面IC), 仅持有期 h 不同。
    """
    first_code = next(iter(prices_panel))
    n = len(prices_panel[first_code].index)
    rebal_indices = list(range(min_warmup, n - rebal_period, rebal_period))
    out: List[Dict[str, Any]] = []
    for h in horizons:
        ics: List[float] = []
        rics: List[float] = []
        for end_idx in rebal_indices:
            if end_idx + h >= n:
                continue
            date_t = prices_panel[first_code].index[end_idx]
            fvals = factor_values.iloc[end_idx] if end_idx < len(factor_values) else pd.Series(dtype=float)
            fut: Dict[str, float] = {}
            for code, df in prices_panel.items():
                if code not in fvals.index:
                    continue
                if date_t not in df.index or end_idx + h >= len(df):
                    continue
                p_now = float(df["close"].iloc[end_idx])
                p_fut = float(df["close"].iloc[end_idx + h])
                if p_now > 0 and p_fut == p_fut and p_fut > 0:
                    fut[code] = p_fut / p_now - 1.0
            fut_s = pd.Series(fut)
            aligned = pd.DataFrame({"f": fvals, "r": fut_s}).dropna()
            if len(aligned) < 10:
                continue
            ics.append(aligned["f"].corr(aligned["r"], method="pearson"))
            rics.append(aligned["f"].corr(aligned["r"], method="spearman"))
        ic_arr = np.array([x for x in ics if pd.notna(x)])
        ric_arr = np.array([x for x in rics if pd.notna(x)])
        out.append({
            "horizon": int(h),
            "ic_mean": float(ic_arr.mean()) if len(ic_arr) else None,
            "rank_ic_mean": float(ric_arr.mean()) if len(ric_arr) else None,
            "n_samples": len(ic_arr),
        })
    return out


def compute_yearly_ic(ic_series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """分年度IC稳定性: 按年聚合 IC 均值/标准差/正IC占比

    参数: ic_series 为 run_ic_timeseries_panel 返回的 [{"date","ic"}, ...]
    """
    from collections import OrderedDict
    yearly: "OrderedDict[str, List[float]]" = OrderedDict()
    for pt in ic_series or []:
        d = pt.get("date")
        ic = pt.get("ic")
        if not d or ic is None or pd.isna(ic):
            continue
        yearly.setdefault(str(d)[:4], []).append(float(ic))
    out: List[Dict[str, Any]] = []
    for y, arr in yearly.items():
        a = np.array(arr)
        out.append({
            "year": y,
            "ic_mean": float(a.mean()),
            "ic_std": float(a.std(ddof=1)) if len(a) > 1 else None,
            "positive_ratio": float((a > 0).mean()),
            "n": len(a),
        })
    return out


def batch_evaluate_factors(
    stock_codes: Optional[List[str]] = None,
    start_date: str = "2024-01-01",
    end_date: Optional[str] = None,
    rebal_period: int = 21,
    n_layers: int = 5,
    min_warmup: int = 130,
    min_stocks_per_date: int = 30,
    factor_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    批量评估因子性能指标 (动态覆盖技术/财务/形态三类可计算公式因子)

    修复背景: 旧实现只硬编码覆盖 12 个 calc_basic_factors 因子, 与 Tab4/5 的公式引擎
    (calc_factor) 口径不一致, 300+ 因子库绝大多数无法批量评估;
    现改为从 factor_library 动态取可计算因子, 按类型分别评价:
        technical: 滚动截面 IC 时序 + 多期分层 (run_ic_timeseries_panel)
        financial: 财报期对齐调仓 + IC 时序
        pattern:   信号频率/命中率/条件收益 (evaluate_pattern_factor)

    参数:
        stock_codes:          股票池 (None 时自动选取 80 只活跃股)
        start_date:           回测开始日期
        end_date:             回测结束日期 (None=今天)
        rebal_period:         调仓周期 (日)
        n_layers:             分层数
        min_warmup:           最小预热天数
        min_stocks_per_date:  每个调仓日最少有效股票数
        factor_ids:           可选, 只评估指定因子; None=全部可评估因子
        limit:                可选, 最多评估前 N 个因子 (控制耗时)
        progress_callback:    进度回调函数

    返回: {
        factor_results: {factor_id: {status, factor_type, ic_mean, ir, ..., hit_rate?}},
        n_stocks, n_rebalances, eval_date, eval_period, n_evaluated, n_total
    }
    """
    def _log(msg):
        if progress_callback:
            progress_callback(msg)

    if end_date is None:
        end_date = date.today().strftime("%Y-%m-%d")

    # 1. 动态取可评估因子清单 (技术/财务/形态三类)
    from lib.factor_db import list_factors, save_metrics
    from lib.factor_engine import (
        calc_factor, classify_factor_type,
        run_ic_timeseries_panel, evaluate_pattern_factor,
        financial_report_rebal_dates,
        ts_rank_normalize, resolve_ts_window,
    )
    _log("加载因子库并筛选可计算公式因子...")
    # evaluation_type=none 的因子不参与计算, 但在结果中显式列出(不再静默跳过);
    # D组文字公式因子(缺引擎)仍静默跳过
    none_factors = {}      # fid -> 不可评价原因文案
    all_factors = []
    for f in list_factors():
        if (f.get("evaluation_type") or "").strip().lower() == "none":
            none_factors[f["factor_id"]] = (
                "构造中间字段, 无独立评价意义 (evaluation_type=none, 可在因子详情中修改标签)")
            continue
        if _has_computable_formula(f):
            all_factors.append(f)
    if factor_ids:
        wanted = set(factor_ids)
        all_factors = [f for f in all_factors if f["factor_id"] in wanted]
        none_factors = {fid: r for fid, r in none_factors.items() if fid in wanted}
    if limit:
        all_factors = all_factors[:int(limit)]
    _log(f"本次批量覆盖 {len(all_factors)} 个可评估因子, 另有 {len(none_factors)} 个不可评价因子(none)将显式列出")

    # 2. 股票池
    if stock_codes is None:
        _log("选取成交活跃的个股池...")
        stock_codes = get_active_stock_pool(n=80, min_days=min_warmup + rebal_period)
    _log(f"股票池: {len(stock_codes)} 只")

    # 3. 加载日K面板 (一次加载, 全部因子复用)
    from lib.backtest_data import load_daily_kline
    _log("加载日K数据...")
    panel: Dict[str, pd.DataFrame] = {}
    for i, code in enumerate(stock_codes):
        if (i + 1) % 10 == 0:
            _log(f"  加载进度 {i+1}/{len(stock_codes)}")
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > min_warmup + rebal_period:
                panel[code] = df
        except Exception:
            pass
    _log(f"有效股票: {len(panel)} 只")

    if len(panel) < min_stocks_per_date:
        raise ValueError(f"有效股票数据不足 {min_stocks_per_date} 只, 无法做截面分析")

    first_code = next(iter(panel))
    eval_date_str = panel[first_code].index[-1].strftime("%Y-%m-%d")
    eval_period = f"{start_date}~{end_date}"

    # 4. 逐因子按类型评价 (与 Tab4 单因子评价同口径)
    factor_results: Dict[str, Any] = {}
    n_rebalances_total = 0
    for i, fi in enumerate(all_factors):
        fid = fi["factor_id"]
        ftype = classify_factor_type(fi)
        _log(f"  [{i+1}/{len(all_factors)}] {fid} ({ftype})")
        try:
            fv = calc_factor(fid, panel)
            if fv is None or fv.empty:
                factor_results[fid] = {"status": "no_data", "factor_type": ftype}
                continue
        except Exception as e:
            factor_results[fid] = {"status": "error", "factor_type": ftype,
                                   "error": str(e)[:200]}
            _log(f"    [WARN] 计算失败: {e}")
            continue

        if ftype == "signal":
            # 形态因子: 离散信号, 用信号统计 (命中率/条件收益), 无 IC/分层
            # 单极性0/1信号(新高/新低等)多空语义由因子方向决定; CDL双极性由值符号决定
            try:
                from lib.factor_engine import direction_to_int
                pr = evaluate_pattern_factor(
                    fv, panel, rebal_period=rebal_period,
                    direction=direction_to_int(fi.get("direction")))
            except Exception as e:
                factor_results[fid] = {"status": "error", "factor_type": ftype,
                                       "error": str(e)[:200]}
                continue
            hit = pr.get("hit_rate", {}).get("overall_hit_rate")
            sig = pr.get("signal_frequency", {}).get("signal_ratio")
            metrics = {
                "eval_date": eval_date_str,
                "ic_mean": None, "ic_std": None, "ir": None,
                "rank_ic_mean": None, "rank_ic_ir": None,
                "ic_positive_ratio": None, "long_short_return": None,
                "sharpe": None, "max_drawdown": None, "turnover": None,
                "eval_period": eval_period,
            }
            try:
                save_metrics(fid, metrics)
            except Exception:
                pass
            factor_results[fid] = {
                "status": "ok", "factor_type": ftype,
                "overall_hit_rate": hit,
                "signal_ratio": sig,
                "signal_alpha": pr.get("conditional_return", {}).get("signal_alpha"),
                "rebal_period": rebal_period,
            }
            continue

        # 技术/财务/时序标准化: IC 时序 + 分层
        reb = None
        eff_rebal = rebal_period
        fv_for_eval = fv
        eff_warmup = min_warmup
        ts_window_used = None
        if ftype == "financial":
            eff_rebal = max(rebal_period, 63)
            reb = financial_report_rebal_dates(fv, panel, rebal_period=eff_rebal, min_warmup=0)
        elif ftype == "technical_ts":
            # 时序标准化截面评价: 量纲不可比因子(价格水平/累积量纲/绝对波动)
            # 先对自身近N日历史做滚动分位(含当日, 无前视), 再走截面IC/分层管线;
            # 窗口按数据长度自适应(数据不足时自动降窗, 避免空IC/无有效截面)
            n_days = len(panel[next(iter(panel))].index)
            ts_window_used = resolve_ts_window(250, n_days, eff_rebal)
            fv_for_eval = ts_rank_normalize(fv, ts_window_used)
            eff_warmup = max(min_warmup, ts_window_used)
        try:
            icr = run_ic_timeseries_panel(
                fv_for_eval, panel, rebal_period=eff_rebal, min_warmup=eff_warmup,
                rebal_dates=reb, n_layers=n_layers,
            )
        except Exception as e:
            factor_results[fid] = {"status": "error", "factor_type": ftype,
                                   "error": str(e)[:200]}
            _log(f"    [WARN] 评价失败: {e}")
            continue

        if icr.get("ic_mean") is None:
            factor_results[fid] = {"status": "no_data", "factor_type": ftype}
            continue

        ls = (icr.get("layered") or {}).get("long_short")
        n_rebalances_total = max(n_rebalances_total, int(icr.get("samples") or 0))
        metrics = {
            "eval_date": eval_date_str,
            "ic_mean": icr.get("ic_mean"),
            "ic_std": icr.get("ic_std"),
            "ir": icr.get("ir"),
            "rank_ic_mean": icr.get("rank_ic_mean"),
            "rank_ic_ir": icr.get("rank_ic_ir"),
            "ic_positive_ratio": icr.get("ic_positive_ratio"),
            "long_short_return": ls,
            "sharpe": None, "max_drawdown": None, "turnover": None,
            "eval_period": eval_period,
        }
        try:
            save_metrics(fid, metrics)
        except Exception:
            pass
        factor_results[fid] = {
            "status": "ok", "factor_type": ftype,
            "ic_mean": icr.get("ic_mean"),
            "ic_std": icr.get("ic_std"),
            "ir": icr.get("ir"),
            "rank_ic_mean": icr.get("rank_ic_mean"),
            "rank_ic_ir": icr.get("rank_ic_ir"),
            "ic_positive_ratio": icr.get("ic_positive_ratio"),
            "long_short_return": ls,
            "n_samples": icr.get("samples"),
            "rebal_period": eff_rebal,
            "ic_series": icr.get("ic_series", []),
        }
        if ts_window_used:
            # 标识时序标准化口径, 供前端展示"时序分位化后截面评价"
            factor_results[fid]["ts_normalize_window"] = ts_window_used

    # evaluation_type=none 的因子显式列出 (不参与计算, 与"计算失败/无数据"区分)
    for fid, reason in none_factors.items():
        factor_results[fid] = {
            "status": "not_evaluable", "factor_type": "none",
            "reason": reason,
        }

    n_evaluated = sum(1 for v in factor_results.values() if v.get("status") == "ok")
    _log(f"完成! 共评估 {n_evaluated}/{len(all_factors)} 个因子"
         f" (另有 {len(none_factors)} 个不可评价因子已列出)")

    return {
        "factor_results": factor_results,
        "n_stocks": len(panel),
        "n_rebalances": n_rebalances_total,
        "eval_date": eval_date_str,
        "eval_period": eval_period,
        "stock_codes": list(panel.keys()),
        "n_evaluated": n_evaluated,
        "n_total": len(all_factors) + len(none_factors),
    }


# ============================================================
# 四、单因子详细评估 (供前端详情页)
# ============================================================

def evaluate_single_factor(factor_id: str,
                           stock_codes: List[str],
                           start_date: str = "2024-01-01",
                           end_date: Optional[str] = None,
                           rebal_period: int = 21,
                           n_layers: int = 5,
                           min_warmup: int = 130) -> Dict[str, Any]:
    """
    单因子详细评估: IC 时序 + 分层回测累计收益曲线

    返回: {
        ic_series, rank_ic_series, ic_mean, ic_std, ir, rank_ic_mean,
        layer_cumret (各层累计收益曲线), long_short_series, metrics
    }
    """
    if end_date is None:
        end_date = date.today().strftime("%Y-%m-%d")

    # 反查 calc_key
    calc_key = None
    for k, fid in _KEY_TO_FACTOR_ID.items():
        if fid == factor_id:
            calc_key = k
            break
    if calc_key is None:
        raise ValueError(f"因子 {factor_id} 暂不支持自动计算 (不在 calc_basic_factors 范围内)")

    from lib.backtest_data import load_daily_kline
    # 股票池不足 30 只时, 自动选取成交活跃的个股补足, 保证截面分析有效
    if not stock_codes or len(stock_codes) < 30:
        auto_pool = get_active_stock_pool(n=80, min_days=min_warmup + rebal_period)
        if stock_codes:
            # 合并用户输入与自动池, 去重, 用户输入优先
            seen = set(stock_codes)
            for c in auto_pool:
                if c not in seen:
                    stock_codes.append(c)
                    seen.add(c)
        else:
            stock_codes = auto_pool

    panel = {}
    for code in stock_codes[:80]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > min_warmup + rebal_period:
                panel[code] = df
        except Exception:
            pass

    if len(panel) < 30:
        raise ValueError(f"有效股票数据不足 30 只 (当前 {len(panel)} 只, 建议扩大股票池或延长回测区间)")

    first_code = next(iter(panel))
    n = len(panel[first_code].index)
    rebal_indices = list(range(min_warmup, n - rebal_period, rebal_period))

    ic_list = []
    rank_ic_list = []
    dates = []
    layer_returns_list = []
    long_short_list = []

    for end_idx in rebal_indices:
        rows = {}
        for code, df in panel.items():
            if len(df) <= end_idx + 1:
                continue
            sub = df.iloc[: end_idx + 1]
            f = calc_basic_factors(sub)
            if f and calc_key in f:
                rows[code] = f
        if len(rows) < n_layers * 5:
            continue

        factor_df = pd.DataFrame.from_dict(rows, orient="index")
        factor_processed = preprocess_factors(factor_df)

        future_ret = {}
        for code, df in panel.items():
            if end_idx + rebal_period < len(df):
                p_now = df["close"].iloc[end_idx]
                p_future = df["close"].iloc[end_idx + rebal_period]
                if p_now > 0:
                    future_ret[code] = p_future / p_now - 1.0
        future_ret = pd.Series(future_ret)

        factor_values = factor_processed[calc_key].dropna() if calc_key in factor_processed.columns else pd.Series(dtype=float)
        aligned = pd.DataFrame({"f": factor_values, "r": future_ret}).dropna()
        if len(aligned) < n_layers * 5:
            continue

        ic = aligned["f"].corr(aligned["r"], method="pearson")
        rank_ic = aligned["f"].corr(aligned["r"], method="spearman")
        ic_list.append(ic)
        rank_ic_list.append(rank_ic)
        dates.append(str(panel[first_code].index[end_idx].date()))

        # 分层
        try:
            aligned["layer"] = pd.qcut(aligned["f"], n_layers, labels=False, duplicates="drop")
            layer_mean = aligned.groupby("layer")["r"].mean().to_dict()
            layers_sorted = sorted(layer_mean.keys())
            layer_returns_list.append({int(k): float(v) for k, v in layer_mean.items()})
            if len(layers_sorted) >= 2:
                long_short_list.append(float(layer_mean[layers_sorted[-1]] - layer_mean[layers_sorted[0]]))
            else:
                long_short_list.append(np.nan)
        except Exception:
            layer_returns_list.append({})
            long_short_list.append(np.nan)

    ic_arr = np.array([x for x in ic_list if pd.notna(x)])
    rank_ic_arr = np.array([x for x in rank_ic_list if pd.notna(x)])
    ls_arr = np.array([x for x in long_short_list if pd.notna(x)])

    # 各层累计收益曲线
    layer_cumret = {}
    if layer_returns_list:
        n_layers_actual = max(max(d.keys()) if d else 0 for d in layer_returns_list) + 1
        for layer in range(n_layers_actual):
            rets = [d.get(layer, 0.0) for d in layer_returns_list]
            cum = np.cumprod([1 + r for r in rets]) - 1
            layer_cumret[layer] = [
                {"date": d, "cumret": float(c)}
                for d, c in zip(dates, cum)
            ]

    # 多空累计收益
    long_short_cumret = []
    if len(ls_arr) > 0:
        ls_full = [x if not np.isnan(x) else 0.0 for x in long_short_list]
        cum = np.cumprod([1 + r for r in ls_full]) - 1
        long_short_cumret = [
            {"date": d, "cumret": float(c)}
            for d, c in zip(dates, cum)
        ]

    return {
        "factor_id": factor_id,
        "ic_series": [{"date": d, "ic": float(v) if pd.notna(v) else None}
                      for d, v in zip(dates, ic_list)],
        "rank_ic_series": [{"date": d, "ic": float(v) if pd.notna(v) else None}
                           for d, v in zip(dates, rank_ic_list)],
        "ic_mean": float(ic_arr.mean()) if len(ic_arr) else None,
        "ic_std": float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else None,
        "ir": float(ic_arr.mean() / ic_arr.std(ddof=1)) if len(ic_arr) > 1 and ic_arr.std(ddof=1) > 0 else None,
        "rank_ic_mean": float(rank_ic_arr.mean()) if len(rank_ic_arr) else None,
        "rank_ic_ir": (float(rank_ic_arr.mean() / rank_ic_arr.std(ddof=1))
                       if len(rank_ic_arr) > 1 and rank_ic_arr.std(ddof=1) > 0 else None),
        "ic_positive_ratio": float((ic_arr > 0).mean()) if len(ic_arr) else None,
        "long_short_mean": float(ls_arr.mean()) if len(ls_arr) else None,
        "layer_cumret": layer_cumret,
        "long_short_cumret": long_short_cumret,
        "n_samples": len(ic_arr),
        "n_stocks": len(panel),
    }
