# -*- coding: utf-8 -*-
# 数据库配置 -- PostgreSQL AI-Quant，读取 CASE-AI 项目根目录 .env（与其它模块同一路径）
"""
环境变量: WUCAI_SQL_HOST / WUCAI_SQL_PORT / WUCAI_SQL_USERNAME / WUCAI_SQL_PASSWORD / WUCAI_SQL_DB
数据表: trade_stock_daily(前复权日K, 主用, 含换手率) / trade_stock_daily_back(后复权日K, 换手率全空) / trade_sector_daily(板块指数) / trade_stock_status(股票状态) / trade_stock_financial(财务数据)
"""
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import dotenv_values

from lib.paths import ENV_FILE
_env = dotenv_values(ENV_FILE)

DB_CONFIG = {
    "host":     _env.get("WUCAI_SQL_HOST", "localhost"),
    "user":     _env.get("WUCAI_SQL_USERNAME", "postgres"),
    "password": _env.get("WUCAI_SQL_PASSWORD", ""),
    "database": _env.get("WUCAI_SQL_DB", "AI-Quant"),
    "port":     int(_env.get("WUCAI_SQL_PORT", "5432")),
    "client_encoding": "UTF8",
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def execute_query(sql, params=None):
    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params or ())
        return cursor.fetchall()
    finally:
        conn.close()
