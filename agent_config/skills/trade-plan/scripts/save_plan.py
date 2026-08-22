#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保存交易计划 Markdown 到文件系统并解析入库。

从 stdin 接收 JSON:
{
  "stock_code": "600519.SH",
  "plan_type": "sim",
  "trade_date": "2026-08-01",
  "markdown": "---\n..."
}

写入 data/trading_plans/{plan_type}/{stock_code}_{trade_date}.md
并同步解析到 trading_plan 数据库表。
"""

import sys
import json
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib.trading_plan import PlanManager
from lib.live_simulator import load_watch_pool, save_watch_pool


def _ensure_in_watch_pool(stock_code: str, plan_type: str) -> str:
    """将股票加入对应盘类型的自选监控池, 确保它在交易计划页和引擎中可见。

    模拟盘 → config/watch_pool.yaml
    实盘   → config/watch_pool_real.yaml

    如果已存在则跳过, 不重复添加。
    """
    if plan_type == "live":
        watch_file = PROJECT_ROOT / "config" / "watch_pool_real.yaml"
    else:
        watch_file = PROJECT_ROOT / "config" / "watch_pool.yaml"

    pool = load_watch_pool(watch_pool_file=str(watch_file))
    codes = list(pool.get("codes") or [])
    if stock_code not in codes:
        codes.append(stock_code)
        save_watch_pool(codes, watch_pool_file=str(watch_file))
        return f"已加入{plan_type}盘自选监控池"
    return "已存在自选监控池中"


def save_plan(
    stock_code: str,
    plan_type: str = "sim",
    trade_date: str = "",
    md_content: str = "",
) -> dict:
    """保存交易计划 Markdown 并解析入库, 同时将股票加入自选监控池"""
    manager = PlanManager()
    if not trade_date:
        from datetime import date
        trade_date = date.today().isoformat()
    result = manager.save(stock_code, plan_type, trade_date, md_content)
    if result.get("ok"):
        pool_msg = _ensure_in_watch_pool(stock_code, plan_type)
        result["watch_pool"] = pool_msg
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="保存交易计划 Markdown 到文件系统并解析入库")
    parser.add_argument("--file", type=str, help="从 JSON 文件读取输入（替代 stdin）")
    args = parser.parse_args()

    raw = ""
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = PROJECT_ROOT / file_path
        if not file_path.exists():
            print(json.dumps({"ok": False, "message": f"文件不存在: {file_path}"}, ensure_ascii=False))
            sys.exit(1)
        raw = file_path.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    if not raw:
        print(json.dumps({"ok": False, "message": "请在 stdin 传入 JSON 数据"}, ensure_ascii=False))
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "message": f"JSON 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    stock_code = (data.get("stock_code") or "").strip()
    plan_type = (data.get("plan_type") or "sim").strip()
    trade_date = (data.get("trade_date") or "").strip()
    md_content = data.get("markdown", "")

    if not stock_code:
        print(json.dumps({"ok": False, "message": "缺少 stock_code"}, ensure_ascii=False))
        sys.exit(1)
    if not md_content:
        print(json.dumps({"ok": False, "message": "缺少 markdown 内容"}, ensure_ascii=False))
        sys.exit(1)

    result = save_plan(stock_code, plan_type, trade_date, md_content)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()