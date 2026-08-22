# -*- coding: utf-8 -*-
# 个股行情 / 回测 通用股票代码工具
"""
提供股票代码标准化、模糊搜索、基础信息查询等函数。
数据来自 PostgreSQL:
    - trade_stock_status   股票名称/行业/股本
    - trade_stock_daily    日 K 线
"""

from __future__ import annotations

import re
from typing import List, Dict, Optional


def normalize_code(code: str) -> str:
    """
    股票代码标准化。
    输入示例: '600519' / '600519.SH' / '000001' / '茅台' 等数字代码
    输出规则:
        600/601/603/605/688/689/900/11 开头 -> .SH
        000/001/002/003/200/300/301/39 开头 -> .SZ
        4/8/82/83/87/88/89/92 开头        -> .BJ
    """
    s = (code or "").strip().upper()
    if not s:
        return ""
    if "." in s:
        return s

    # 只取前 6 位数字部分（指数代码如 000001 也是 6 位）
    m = re.match(r"^(\d+)", s)
    if not m:
        return s
    digits = m.group(1)

    # 常见上证指数代码（000001 上证指数、000300 沪深300 等）虽以 000 开头，但后缀为 .SH
    SH_INDEX_CODES = {"000001", "000016", "000300", "000688", "000905",
                      "000852", "000010", "000009"}
    if digits in SH_INDEX_CODES:
        return f"{digits}.SH"
    if digits.startswith(("4", "8", "82", "83", "87", "88", "89", "92")):
        return f"{digits}.BJ"
    if digits.startswith(("60", "68", "90", "11", "50", "51")):
        return f"{digits}.SH"
    if digits.startswith(("00", "20", "30", "39")):
        return f"{digits}.SZ"
    # 未知规则原样返回，让调用方决定
    return s


def _get_db_config() -> dict:
    """复用 .env 中的 PostgreSQL 配置（app.py 已提前 load_dotenv）。"""
    import os
    return {
        "host":     os.environ.get("WUCAI_SQL_HOST", "localhost"),
        "user":     os.environ.get("WUCAI_SQL_USERNAME", "postgres"),
        "password": os.environ.get("WUCAI_SQL_PASSWORD", ""),
        "database": os.environ.get("WUCAI_SQL_DB", "AI-Quant"),
        "port":     int(os.environ.get("WUCAI_SQL_PORT", "5432")),
        "client_encoding": "UTF8",
    }


def search_stocks(q: str, limit: int = 15) -> List[Dict[str, str]]:
    """
    按代码或名称模糊搜索股票。

    以 trade_stock_status（申万分类表）为基准搜索，速度快且支持中文名称匹配；
    通过 EXISTS 过滤掉在 trade_stock_daily 中无有效 K 线数据（close_price > 0）的股票，
    避免出现"搜到但点击加载报错没有数据"的问题。
    """
    import psycopg2
    from psycopg2.extras import RealDictCursor

    query = (q or "").strip()
    if not query:
        return []

    cfg = _get_db_config()
    conn = psycopg2.connect(**cfg)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 标准化输入，用于精确匹配排序（如 600519 -> 600519.SH）
        norm = normalize_code(query)
        # 模糊匹配直接用原始输入：不做 normalize+replace，避免
        # 输入 "688" 被转成 "688.SH" 再替换成 "688_SH" 后，
        # LIKE 的 _ 通配符导致匹配不到 "688086.SH" 等真实代码
        code_pattern = query

        sql = """
            SELECT s.stock_code, s.stock_name, s.sector_1, s.sector_2
            FROM trade_stock_status s
            WHERE (s.stock_code ILIKE %s OR s.stock_name ILIKE %s)
              AND EXISTS (
                  SELECT 1 FROM trade_stock_daily d
                  WHERE d.stock_code = s.stock_code AND d.close_price > 0
              )
            ORDER BY
                CASE WHEN s.stock_code = %s THEN 0 ELSE 1 END,
                CASE WHEN s.stock_code ILIKE %s THEN 0 ELSE 1 END,
                s.stock_code
            LIMIT %s
        """
        like_code = f"%{code_pattern}%"
        like_name = f"%{query}%"
        cursor.execute(sql, (like_code, like_name, norm, f"{code_pattern}%", limit))
        rows = cursor.fetchall()

        return [{
            "code": r["stock_code"],
            "name": r["stock_name"] or "",
            "sector_1": r["sector_1"] or "",
            "sector_2": r["sector_2"] or "",
        } for r in rows]
    finally:
        conn.close()


def get_stock_info(code: str) -> Dict[str, Optional[str]]:
    """读取单只股票基础信息（名称、行业、股本等）。"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    norm = normalize_code(code)
    if not norm:
        return {}

    cfg = _get_db_config()
    conn = psycopg2.connect(**cfg)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT stock_code, stock_name, list_date, total_shares, float_shares,
                   sector_1, sector_2, sector_3
            FROM trade_stock_status
            WHERE stock_code = %s
            LIMIT 1
            """,
            (norm,)
        )
        row = cursor.fetchone()
        if not row:
            # 兜底：trade_stock_status 无记录（如指数、ETF、未纳入申万分类的股票）
            # 补全字段为 None，避免前端访问 undefined；K 线/概念等模块各自兜底
            return {
                "code": norm,
                "name": "",
                "list_date": "",
                "total_shares": None,
                "float_shares": None,
                "sector_1": "",
                "sector_2": "",
                "sector_3": "",
            }
        return {
            "code": row["stock_code"],
            "name": row["stock_name"] or "",
            "list_date": str(row["list_date"]) if row["list_date"] else "",
            "total_shares": row["total_shares"],
            "float_shares": row["float_shares"],
            "sector_1": row["sector_1"] or "",
            "sector_2": row["sector_2"] or "",
            "sector_3": row["sector_3"] or "",
        }
    finally:
        conn.close()
