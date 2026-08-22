#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF报告下载工具

功能:
通过巨潮资讯网搜索并下载上市公司年报/季报/公告PDF,
下载完成后自动调用 preprocess.py 更新RAG统一索引,
使新PDF立即可通过 query_report.py 查询。

用法:
    python fetch_report_pdf.py --stock 600519
    python fetch_report_pdf.py --stock 600519 --category 年度报告
    python fetch_report_pdf.py --stock 600519 --category 年度报告 --max_download 1
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests


CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_DOWNLOAD_BASE = "http://static.cninfo.com.cn/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
}

CATEGORY_MAP = {
    "年度报告": "category_ndbg_szsh",
    "半年度报告": "category_bndbg_szsh",
    "一季度报告": "category_yjdbg_szsh",
    "三季度报告": "category_sjdbg_szsh",
    "业绩预告": "category_yjygjxz_szsh",
}


def _get_cninfo_orgid(stock_code: str) -> str:
    """通过巨潮 API 查询股票对应的机构ID"""
    url = "http://www.cninfo.com.cn/new/information/topSearch/query"
    data = {"keyWord": stock_code, "maxSecNum": 10, "maxListNum": 5}
    try:
        resp = requests.post(url, data=data, headers=HEADERS, timeout=10)
        result = resp.json()
        items = result if isinstance(result, list) else result.get("keyBoardList", [])
        for item in items:
            if item.get("code") == stock_code:
                return item.get("orgId", "")
        if items:
            return items[0].get("orgId", "")
    except Exception:
        pass
    return ""


def search_cninfo_reports(
    stock_code: str,
    category: str = "年度报告",
    start_date: str = "",
    end_date: str = "",
    max_results: int = 10,
) -> list:
    """搜索巨潮资讯网上的公告/报告"""
    org_id = _get_cninfo_orgid(stock_code)
    category_code = CATEGORY_MAP.get(category, "category_ndbg_szsh")

    se_date = ""
    if start_date and end_date:
        se_date = f"{start_date}~{end_date}"

    data = {
        "pageNum": 1,
        "pageSize": max_results,
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{stock_code},{org_id}" if org_id else stock_code,
        "searchkey": "",
        "secid": "",
        "category": category_code,
        "trade": "",
        "seDate": se_date,
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }

    print(f"[搜索] 巨潮资讯网: {stock_code} - {category}")
    try:
        resp = requests.post(CNINFO_QUERY_URL, data=data, headers=HEADERS, timeout=15)
        result = resp.json()
        announcements = result.get("announcements", [])
        if not announcements:
            print("  -> 未找到相关公告")
            return []

        reports = []
        for ann in announcements:
            title = ann.get("announcementTitle", "").replace("<em>", "").replace("</em>", "")
            reports.append({
                "title": title,
                "date": ann.get("announcementTime", ""),
                "url": CNINFO_DOWNLOAD_BASE + ann.get("adjunctUrl", ""),
                "type": ann.get("announcementType", ""),
                "sec_name": ann.get("secName", ""),
                "sec_code": ann.get("secCode", ""),
            })

        for r in reports:
            if r["date"] and isinstance(r["date"], (int, float)):
                r["date"] = pd.Timestamp(r["date"], unit="ms").strftime("%Y-%m-%d")

        print(f"  -> 找到 {len(reports)} 份报告")
        return reports

    except Exception as e:
        print(f"  -> 搜索失败: {e}")
        return []


def download_pdf_report(url: str, save_path: str) -> bool:
    """下载单个 PDF 报告（带进度输出）"""
    try:
        print(f"[1/3] 开始下载 PDF...")
        sys.stdout.flush()
        resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        if resp.status_code == 200:
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int(downloaded * 100 / total_size)
                            if pct != last_pct and pct % 10 == 0:
                                print(f"  -> 下载进度: {pct}% ({downloaded / (1024 * 1024):.1f}MB / {total_size / (1024 * 1024):.1f}MB)")
                                sys.stdout.flush()
                                last_pct = pct
            size_mb = os.path.getsize(save_path) / (1024 * 1024)
            print(f"[2/3] PDF 下载完成: {os.path.basename(save_path)} ({size_mb:.1f}MB)")
            sys.stdout.flush()
            return True
        else:
            print(f"  -> 下载失败: HTTP {resp.status_code}")
            sys.stdout.flush()
            return False
    except Exception as e:
        print(f"  -> 下载异常: {e}")
        sys.stdout.flush()
        return False


def run_preprocess(project_root: str) -> dict:
    """下载完成后自动更新统一索引（实时输出进度）"""
    preprocess_script = os.path.join(project_root, "preprocess.py")
    if not os.path.exists(preprocess_script):
        print("[索引更新] 未找到 preprocess.py，跳过自动索引更新")
        return {"status": "skipped", "reason": "preprocess.py not found"}

    print("[3/3] 开始更新 RAG 统一索引，这可能需要几分钟...")
    sys.stdout.flush()
    try:
        process = subprocess.Popen(
            [sys.executable, "preprocess.py"],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output_lines: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    print(f"  [索引] {line}")
                    sys.stdout.flush()
                    output_lines.append(line)
        process.wait(timeout=600)
        if process.returncode == 0:
            print("[3/3] RAG 统一索引更新完成")
            sys.stdout.flush()
            return {"status": "success"}
        else:
            stderr_text = "\n".join(output_lines[-20:])
            print(f"[索引更新] 失败: {stderr_text[:500]}")
            sys.stdout.flush()
            return {"status": "error", "stderr": stderr_text[:500]}
    except subprocess.TimeoutExpired:
        print("[索引更新] 超时（超过600秒），但部分索引可能已更新")
        sys.stdout.flush()
        return {"status": "timeout"}
    except Exception as e:
        print(f"[索引更新] 异常: {e}")
        sys.stdout.flush()
        return {"status": "error", "message": str(e)}


def fetch_pdf_reports(
    stock_code: str,
    output_dir: str,
    category: str = "年度报告",
    keyword: str = "",
    max_download: int = 1,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """从巨潮资讯网搜索并下载 PDF 报告"""
    os.makedirs(output_dir, exist_ok=True)

    reports = search_cninfo_reports(
        stock_code,
        category=category,
        start_date=start_date,
        end_date=end_date,
        max_results=max_download * 3,
    )

    if not reports:
        return {"status": "no_reports", "downloaded": 0}

    if keyword:
        reports = [r for r in reports if keyword in r["title"]]
    reports = [r for r in reports if "摘要" not in r["title"] and "取消" not in r["title"]]

    downloaded = []
    for i, report in enumerate(reports[:max_download]):
        safe_title = report["title"].replace("/", "_").replace("\\", "_")
        safe_title = safe_title.replace(":", "").replace("*", "").replace("?", "")
        safe_title = safe_title.replace('"', "").replace("<", "").replace(">", "").replace("|", "")
        filename = f"{report['sec_code']}_{safe_title}.pdf"
        save_path = os.path.join(output_dir, filename)

        if os.path.exists(save_path):
            print(f"  -> 已存在，跳过: {filename}")
            downloaded.append(save_path)
            continue

        print(f"[下载] ({i+1}/{min(len(reports), max_download)}) {report['title']}")
        if download_pdf_report(report["url"], save_path):
            downloaded.append(save_path)

        time.sleep(1)

    meta_path = os.path.join(output_dir, f"{stock_code}_report_list.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)

    return {
        "status": "success",
        "total_found": len(reports),
        "downloaded": len(downloaded),
        "files": downloaded,
        "meta_file": meta_path,
    }


def main():
    parser = argparse.ArgumentParser(description="PDF报告下载工具")
    parser.add_argument("--stock", required=True, help="股票代码（如 600519）")
    parser.add_argument(
        "--category",
        default="年度报告",
        choices=["年度报告", "半年度报告", "一季度报告", "三季度报告", "业绩预告"],
        help="PDF报告类别",
    )
    parser.add_argument("--keyword", default="", help="PDF标题过滤关键词")
    parser.add_argument("--max_download", type=int, default=1, help="最大PDF下载数量")
    parser.add_argument("--start_date", default="", help="起始日期（如 2024-01-01）")
    parser.add_argument("--end_date", default="", help="结束日期（如 2025-12-31）")
    parser.add_argument("--output_dir", default="data/reports", help="PDF输出目录")
    args = parser.parse_args()

    # 标准化股票代码: 去掉 .SH/.SZ/.BJ 后缀
    stock_code = args.stock.upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "").strip()
    if stock_code != args.stock:
        print(f"[代码标准化] {args.stock} -> {stock_code}")

    # 自动更新统一索引
    # 脚本路径: agent_config/skills/read-pdf/scripts/fetch_report_pdf.py
    # 项目根目录为脚本向上4级（即 CASE-AI量化系统/，所有数据均存放在其 data/ 子目录下）
    project_root = Path(__file__).resolve().parents[4]

    # 将输出目录统一到项目根目录的 data/ 下，避免 agent 工作目录不同导致 PDF 和索引不在同一处
    output_dir = args.output_dir
    if not Path(output_dir).is_absolute():
        output_dir = str(project_root / output_dir)

    results = fetch_pdf_reports(
        stock_code,
        output_dir,
        category=args.category,
        keyword=args.keyword,
        max_download=args.max_download,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    index_result = run_preprocess(str(project_root))
    results["index_update"] = index_result

    print(f"\n[完成] {json.dumps(results, ensure_ascii=False, indent=2, default=str)}")
    return results


if __name__ == "__main__":
    main()
