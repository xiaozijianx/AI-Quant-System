#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务CSV数据获取工具

功能:
通过 akshare 获取上市公司结构化财务报表数据（利润表、资产负债表、现金流量表）
以及东方财富财务摘要，保存为CSV文件供 financial-analysis 技能分析使用。

输出规则:
    --output_dir 指定输出根目录，脚本会自动在根目录下创建 financial_data/ 子目录。
    例如 --output_dir data 会输出到 data/financial_data/。
    通常只需传 --stock，不需要传 --output_dir。

用法:
    python fetch_financial_csv.py --stock 600519
    python fetch_financial_csv.py --stock 600519.SH
    python fetch_financial_csv.py --stock 600519 --output_dir data
"""

import argparse
import json
import os

import pandas as pd


def fetch_financial_statements(stock_code: str, output_dir: str) -> dict:
    """
    通过 akshare 获取三大财务报表 + 财务摘要数据。

    Args:
        stock_code: 股票代码（如 600519，可带或不带 .SH/.SZ/.BJ 后缀）
        output_dir: 输出目录

    Returns:
        获取结果摘要
    """
    import akshare as ak

    os.makedirs(output_dir, exist_ok=True)
    results = {}

    # 新浪财经三大报表
    report_types = {
        "资产负债表": "balance_sheet",
        "利润表": "income_statement",
        "现金流量表": "cash_flow",
    }

    for cn_name, en_name in report_types.items():
        print(f"[获取] {cn_name}: {stock_code}")
        try:
            df = ak.stock_financial_report_sina(stock=stock_code, symbol=cn_name)
            if df is not None and len(df) > 0:
                csv_path = os.path.join(output_dir, f"{stock_code}_{en_name}.csv")
                df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                results[cn_name] = {
                    "status": "success",
                    "rows": len(df),
                    "file": csv_path,
                }
                print(f"  -> {len(df)} 条记录，已保存: {csv_path}")
            else:
                results[cn_name] = {"status": "empty"}
                print(f"  -> 无数据")
        except Exception as e:
            results[cn_name] = {"status": "error", "message": str(e)}
            print(f"  -> 错误: {e}")

    # 东方财富财务摘要（更丰富的字段）
    print(f"[获取] 财务摘要(东方财富): {stock_code}")
    try:
        symbol_prefix = "SH" if stock_code.startswith("6") else "SZ"
        em_symbol = f"{symbol_prefix}{stock_code}"
        df_abstract = ak.stock_financial_abstract(symbol=em_symbol)
        if df_abstract is not None and len(df_abstract) > 0:
            csv_path = os.path.join(output_dir, f"{stock_code}_financial_abstract.csv")
            df_abstract.to_csv(csv_path, index=False, encoding="utf-8-sig")
            results["财务摘要"] = {
                "status": "success",
                "rows": len(df_abstract),
                "file": csv_path,
            }
            print(f"  -> {len(df_abstract)} 条记录，已保存: {csv_path}")
    except Exception as e:
        results["财务摘要"] = {"status": "error", "message": str(e)}
        print(f"  -> 错误: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="财务CSV数据获取工具")
    parser.add_argument("--stock", required=True, help="股票代码(如 600519 或 600519.SH)")
    parser.add_argument(
        "--output_dir",
        default="data",
        help="输出根目录（脚本会自动在其下创建 financial_data/ 子目录，默认 data）",
    )
    args = parser.parse_args()

    # 标准化股票代码: 去掉 .SH/.SZ/.BJ 后缀
    stock_code = args.stock.upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "").strip()
    if stock_code != args.stock:
        print(f"[代码标准化] {args.stock} -> {stock_code}")

    fin_dir = os.path.join(args.output_dir, "financial_data")
    results = fetch_financial_statements(stock_code, fin_dir)

    print(f"\n[完成] {json.dumps(results, ensure_ascii=False, indent=2, default=str)}")
    return results


if __name__ == "__main__":
    main()
