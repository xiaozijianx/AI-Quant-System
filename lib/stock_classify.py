# -*- coding: utf-8 -*-
# 股票分类数据加载层 (板块/概念/行业映射)
"""
统一入口, 供因子评价中性化使用:
    - load_sector_map:   申万二级板块 {stock_code: sector_name}
    - load_industry_map: 申万一级行业 {stock_code: industry_name}
    - load_concept_map:  概念板块 {stock_code: concept_name} (主概念)

数据源 (PostgreSQL):
    - trade_stock_status:    stock_code, stock_name, sector_1, sector_2
    - concept_stock_tag + concept_meta: stock_code, concept_code, concept_name

复用 morning_brief/lib/factor_runner.py 的 SQL 逻辑, 统一放到 lib/ 下供全系统调用
"""

from __future__ import annotations
import os
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


def _db_config() -> dict:
    """读 .env 里的 PostgreSQL 配置"""
    return {
        "host":     os.environ.get("WUCAI_SQL_HOST", "localhost"),
        "user":     os.environ.get("WUCAI_SQL_USERNAME", "postgres"),
        "password": os.environ.get("WUCAI_SQL_PASSWORD", ""),
        "database": os.environ.get("WUCAI_SQL_DB", "AI-Quant"),
        "port":     int(os.environ.get("WUCAI_SQL_PORT", "5432")),
        "client_encoding": "UTF8",
    }


def _execute_query(sql: str, params: Optional[list] = None) -> List[Dict]:
    """执行查询, 返回字典列表"""
    conn = psycopg2.connect(**_db_config())
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or [])
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        conn.close()


# ============================================================
# 板块/行业映射 (申万一级=行业, 申万二级=板块)
# ============================================================

def load_sector_map(stock_codes: List[str], level: int = 2) -> Dict[str, str]:
    """加载股票-板块映射 (申万二级)

    参数:
        stock_codes: 股票代码列表
        level:       板块级别 1=申万一级(行业), 2=申万二级(板块)

    返回: {stock_code: sector_name}
    """
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    sector_col = "sector_1" if level == 1 else "sector_2"
    sql = f"""
        SELECT stock_code, {sector_col} AS sector_name
        FROM trade_stock_status
        WHERE stock_code IN ({placeholders})
          AND {sector_col} IS NOT NULL
          AND {sector_col} <> ''
    """
    rows = _execute_query(sql, stock_codes)
    return {r["stock_code"]: r["sector_name"] for r in rows if r.get("sector_name")}


def load_industry_map(stock_codes: List[str]) -> Dict[str, str]:
    """加载股票-行业映射 (申万一级)

    等价于 load_sector_map(level=1), 语义清晰单独提供
    """
    return load_sector_map(stock_codes, level=1)


# ============================================================
# 概念映射 (一只股票可能有多个概念, 取主概念)
# ============================================================

def load_concept_map(stock_codes: List[str],
                     multi_concept: bool = False) -> Dict[str, str]:
    """加载股票-概念映射

    参数:
        stock_codes:  股票代码列表
        multi_concept: False=取主概念(第一个, 按concept_name排序)
                       True=取所有概念, 用逗号拼接

    返回: {stock_code: concept_name}
    """
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT DISTINCT cst.stock_code, cm.concept_name
        FROM concept_stock_tag cst
        JOIN concept_meta cm ON cm.concept_code = cst.concept_code
        WHERE cst.stock_code IN ({placeholders})
          AND cst.trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
          AND cm.concept_name IS NOT NULL
          AND cm.concept_name <> ''
        ORDER BY cst.stock_code, cm.concept_name
    """
    rows = _execute_query(sql, stock_codes)

    # 按股票分组
    grouped: Dict[str, List[str]] = {code: [] for code in stock_codes}
    for r in rows:
        code = r["stock_code"]
        name = r["concept_name"]
        if name and name not in grouped[code]:
            grouped[code].append(name)

    if multi_concept:
        return {code: ",".join(concepts) for code, concepts in grouped.items() if concepts}
    else:
        # 主概念: 取第一个
        return {code: concepts[0] for code, concepts in grouped.items() if concepts}


def load_concept_list_map(stock_codes: List[str]) -> Dict[str, List[str]]:
    """加载股票-概念列表映射 (一只股票多个概念)

    返回: {stock_code: [concept_name1, concept_name2, ...]}
    """
    if not stock_codes:
        return {}
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT DISTINCT cst.stock_code, cm.concept_name
        FROM concept_stock_tag cst
        JOIN concept_meta cm ON cm.concept_code = cst.concept_code
        WHERE cst.stock_code IN ({placeholders})
          AND cst.trade_date = (SELECT MAX(trade_date) FROM concept_stock_tag)
          AND cm.concept_name IS NOT NULL
          AND cm.concept_name <> ''
        ORDER BY cst.stock_code, cm.concept_name
    """
    rows = _execute_query(sql, stock_codes)

    result: Dict[str, List[str]] = {code: [] for code in stock_codes}
    for r in rows:
        code = r["stock_code"]
        name = r["concept_name"]
        if name and name not in result[code]:
            result[code].append(name)
    return result


# ============================================================
# 市值映射 (用于市值/行业中性化 marketcap_neutralize)
# ============================================================

def load_marketcap_map(stock_codes: List[str]) -> Dict[str, float]:
    """加载股票-市值映射 {stock_code: 市值}

    市值 = total_shares × 最近收盘价, 用于市值中性化回归取残差。
    股本取 trade_stock_financial 最新财报的总股本, 收盘价取最近日K;
    无法计算(缺股本或K线)的股票不纳入映射。
    """
    if not stock_codes:
        return {}
    from lib.backtest_data import load_daily_kline
    placeholders = ",".join(["%s"] * len(stock_codes))
    sql = f"""
        SELECT stock_code, total_shares
        FROM trade_stock_financial
        WHERE stock_code IN ({placeholders})
          AND total_shares IS NOT NULL
          AND total_shares > 0
        ORDER BY stock_code, report_date DESC
    """
    rows = _execute_query(sql, stock_codes)
    shares: Dict[str, float] = {}
    for r in rows:
        code = r["stock_code"]
        if code not in shares:
            shares[code] = float(r["total_shares"])
    result: Dict[str, float] = {}
    for code, ts in shares.items():
        try:
            df = load_daily_kline(code, start_date="2020-01-01", prefer="mysql")
        except Exception:
            df = None
        if df is None or df.empty:
            continue
        close = df["close"].dropna()
        if close.empty:
            continue
        result[code] = ts * float(close.iloc[-1])
    return result
