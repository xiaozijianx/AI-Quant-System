# -*- coding: utf-8 -*-
"""自动读取 .env 并在 PostgreSQL 中创建 trade_sector_rotation_daily 表.

用法:
    python "CASE-AI量化系统/scripts/init_sector_rotation_table.py"

不需要手动输入密码，脚本会从项目根目录 .env 读取数据库配置。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import dotenv_values

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
# SQL schema 与本脚本同在 scripts/ 下 (scripts/sql/, 自根目录 sql/ 合并而来)
SQL_FILE = Path(__file__).resolve().parent / "sql" / "sector_rotation_schema.sql"


def _load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # 环境变量优先级高于 .env
    for k in ["WUCAI_SQL_HOST", "WUCAI_SQL_PORT", "WUCAI_SQL_USERNAME",
              "WUCAI_SQL_PASSWORD", "WUCAI_SQL_DB"]:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def main() -> int:
    env = _load_env()
    password = env.get("WUCAI_SQL_PASSWORD", "")
    if not password:
        print("错误: .env 中未配置 WUCAI_SQL_PASSWORD", file=sys.stderr)
        return 1

    config = {
        "host":     env.get("WUCAI_SQL_HOST", "localhost"),
        "user":     env.get("WUCAI_SQL_USERNAME", "postgres"),
        "password": password,
        "database": env.get("WUCAI_SQL_DB", "AI-Quant"),
        "port":     int(env.get("WUCAI_SQL_PORT", "5432")),
        "client_encoding": "UTF8",
    }

    if not SQL_FILE.exists():
        print(f"错误: 找不到 SQL 文件 {SQL_FILE}", file=sys.stderr)
        return 1

    sql = SQL_FILE.read_text(encoding="utf-8")

    print(f"连接数据库: {config['host']}:{config['port']}/{config['database']} ...")
    conn = psycopg2.connect(**config)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()
        print("成功: trade_sector_rotation_daily 表已创建/更新")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
