#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
研报生成器

功能：将五步法分析结果组装为完整的 Markdown 格式深度研报。
包含封面信息、目录、五步分析内容、风险提示和免责声明。

用法：
    python report_generator.py --analysis_file <分析结果JSON> --output_dir <输出目录>
    python report_generator.py --analysis_file outputs/analysis/贵州茅台_analysis.json --output_dir outputs/reports/
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime


# 研报 Markdown 模板
REPORT_TEMPLATE = """# {stock_name} - 深度分析报告

> **分析框架**: 国泰君安"五步法"  
> **生成时间**: {analysis_date}  
> **分析模型**: {model}  
> **数据来源**: 公司财报 (来源页码: {source_pages})

---

## 目录

1. [信息差分析](#1-信息差分析)
2. [逻辑差分析](#2-逻辑差分析)
3. [预期差分析](#3-预期差分析)
4. [催化剂识别](#4-催化剂识别)
5. [投资结论](#5-投资结论)
6. [风险提示](#6-风险提示)
7. [免责声明](#7-免责声明)

---

{steps_content}

---

## 6. 风险提示

- 本报告基于公开财报数据和 AI 分析生成，分析结论可能存在偏差
- 财报数据具有滞后性，不代表公司当前经营状况
- 市场环境变化可能导致分析假设不再成立
- 行业政策调整可能对公司经营产生重大影响
- AI 模型的分析能力有限，无法完全替代专业分析师的判断

---

## 7. 免责声明

本报告由 AI 投研助手 Charles 自动生成，仅供学习和研究参考，**不构成任何投资建议**。

- 报告内容基于公开信息和 AI 分析，不保证信息的准确性和完整性
- 投资者据此操作，风险自担
- 报告作者不对任何投资损失承担责任
- 在做出投资决策前，建议咨询专业投资顾问

---

*报告生成于 {generation_time}*
"""

# 每个步骤的章节模板
STEP_SECTION_TEMPLATE = """## {step_num}. {step_title}

> 数据来源页码: {source_pages}

{analysis}

"""

# 步骤名称到章节标题的映射
STEP_TITLES = {
    "信息差": "信息差分析",
    "逻辑差": "逻辑差分析",
    "预期差": "预期差分析",
    "催化剂": "催化剂识别",
    "结论": "投资结论",
}


def load_analysis(analysis_file: str) -> dict:
    """加载五步法分析结果"""
    with open(analysis_file, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_report(analysis: dict) -> str:
    """
    将分析结果组装为 Markdown 研报。

    Args:
        analysis: 五步法分析结果（来自 five_step_analysis.py 的输出）

    Returns:
        完整的 Markdown 格式研报
    """
    stock_name = analysis["stock_name"]
    analysis_date = analysis["analysis_date"]
    model = analysis["model"]
    all_pages = analysis.get("all_source_pages", [])

    # 生成各步骤章节
    steps_content = ""
    for step_data in analysis["steps"]:
        step_num = step_data["step"]
        step_name = step_data["name"]
        step_title = STEP_TITLES.get(step_name, step_name)
        step_analysis = step_data["analysis"]
        step_pages = step_data.get("source_pages", [])

        section = STEP_SECTION_TEMPLATE.format(
            step_num=step_num,
            step_title=step_title,
            source_pages=", ".join(str(p) for p in step_pages) if step_pages else "未标注",
            analysis=step_analysis,
        )
        steps_content += section

    # 组装完整报告
    report = REPORT_TEMPLATE.format(
        stock_name=stock_name,
        analysis_date=analysis_date,
        model=model,
        source_pages=", ".join(str(p) for p in all_pages) if all_pages else "未标注",
        steps_content=steps_content,
        generation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    return report


def save_report(report: str, stock_name: str, output_dir: str) -> str:
    """
    保存研报到文件。

    Returns:
        报告文件路径
    """
    os.makedirs(output_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{stock_name}_深度研报_{date_str}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath


# 研报 HTML 模板（自包含样式，便于阅读）
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{stock_name} - 深度分析报告</title>
<style>
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    line-height: 1.8;
    color: #2c3e50;
    max-width: 900px;
    margin: 0 auto;
    padding: 24px 32px 60px;
    background: #fff;
  }}
  h1 {{ font-size: 28px; border-bottom: 3px solid #2563eb; padding-bottom: 12px; color: #1e293b; }}
  h2 {{ font-size: 22px; color: #2563eb; border-left: 5px solid #2563eb; padding-left: 10px; margin-top: 36px; }}
  h3 {{ font-size: 18px; color: #1e293b; }}
  .meta {{ background: #f1f5f9; border-radius: 8px; padding: 14px 18px; font-size: 14px; color: #475569; }}
  .meta p {{ margin: 4px 0; }}
  blockquote {{ border-left: 4px solid #cbd5e1; margin: 12px 0; padding: 8px 16px; color: #64748b; background: #f8fafc; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
  th {{ background: #f1f5f9; }}
  code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
  .toc {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 24px; }}
  .toc a {{ color: #2563eb; text-decoration: none; display: block; padding: 2px 0; }}
  hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 28px 0; }}
  .footer {{ margin-top: 40px; color: #94a3b8; font-size: 13px; text-align: center; }}
</style>
</head>
<body>
<h1>{stock_name} - 深度分析报告</h1>
<div class="meta">
  <p><strong>分析框架</strong>: 国泰君安"五步法"</p>
  <p><strong>生成时间</strong>: {analysis_date}</p>
  <p><strong>分析模型</strong>: {model}</p>
  <p><strong>数据来源</strong>: 公司财报 (来源页码: {source_pages})</p>
</div>
<hr>
<div class="toc">
  <strong>目录</strong>
  {toc_html}
</div>
<hr>
{steps_html}
<hr>
<h2 id="risk">6. 风险提示</h2>
<ul>
  <li>本报告基于公开财报数据和 AI 分析生成，分析结论可能存在偏差</li>
  <li>财报数据具有滞后性，不代表公司当前经营状况</li>
  <li>市场环境变化可能导致分析假设不再成立</li>
  <li>行业政策调整可能对公司经营产生重大影响</li>
  <li>AI 模型的分析能力有限，无法完全替代专业分析师的判断</li>
</ul>
<hr>
<h2 id="disclaimer">7. 免责声明</h2>
<p>本报告由 AI 投研助手 Charles 自动生成，仅供学习和研究参考，<strong>不构成任何投资建议</strong>。</p>
<ul>
  <li>报告内容基于公开信息和 AI 分析，不保证信息的准确性和完整性</li>
  <li>投资者据此操作，风险自担</li>
  <li>报告作者不对任何投资损失承担责任</li>
  <li>在做出投资决策前，建议咨询专业投资顾问</li>
</ul>
<hr>
<div class="footer">报告生成于 {generation_time}</div>
</body>
</html>
"""

# 每个步骤的 HTML 章节模板
HTML_STEP_SECTION_TEMPLATE = """<h2 id="step-{step_num}">{step_num}. {step_title}</h2>
<p><em>数据来源页码: {source_pages}</em></p>
{analysis}
"""


def inline(text: str) -> str:
    """行内 Markdown 转 HTML：加粗、行内代码、链接。"""
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html(md_text: str) -> str:
    """将 Markdown 文本转换为简单 HTML（不依赖第三方库）。

    支持标题、无序/有序列表、引用、表格、分隔线、加粗、行内代码等常用语法。
    """
    lines = md_text.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 空行
        if not stripped:
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}$", stripped):
            out.append("<hr>")
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            quote_lines = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(q) for q in quote_lines) + "</blockquote>")
            continue

        # 无序列表
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            items = []
            while i < n:
                s = lines[i].strip()
                mm = re.match(r"^[-*]\s+(.*)$", s)
                if mm:
                    items.append(inline(mm.group(1)))
                    i += 1
                else:
                    break
            out.append("<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue

        # 有序列表
        m = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if m:
            items = []
            while i < n:
                s = lines[i].strip()
                mm = re.match(r"^\d+[.)]\s+(.*)$", s)
                if mm:
                    items.append(inline(mm.group(1)))
                    i += 1
                else:
                    break
            out.append("<ol>" + "".join(f"<li>{it}</li>" for it in items) + "</ol>")
            continue

        # 表格（简单支持：表头 + 分隔行 + 数据行）
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|?$", lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2  # 跳过表头和分隔行
            rows = []
            while i < n:
                s = lines[i].strip()
                if s.startswith("|"):
                    cells = [c.strip() for c in s.strip("|").split("|")]
                    rows.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                    i += 1
                else:
                    break
            thead = "<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header_cells) + "</tr></thead>"
            tbody = "<tbody>" + "".join(rows) + "</tbody>"
            out.append(f"<table>{thead}{tbody}</table>")
            continue

        # 普通段落：合并连续普通行
        para_lines = [inline(line)]
        i += 1
        while i < n:
            s = lines[i].strip()
            if not s or re.match(r"^(#{1,6}\s|[-*]\s|\d+[.)]\s|>|-{3,})", s):
                break
            para_lines.append(inline(lines[i]))
            i += 1
        out.append("<p>" + " ".join(para_lines) + "</p>")

    return "\n".join(out)


def generate_html(analysis: dict) -> str:
    """
    将分析结果组装为 HTML 研报（自包含样式，便于阅读）。

    与 generate_report 消费同一份 analysis JSON，仅渲染模板不同。
    """
    stock_name = analysis["stock_name"]
    analysis_date = analysis["analysis_date"]
    model = analysis["model"]
    all_pages = analysis.get("all_source_pages", [])
    source_pages = ", ".join(str(p) for p in all_pages) if all_pages else "未标注"
    generation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    steps_html = ""
    toc_items = []
    for step_data in analysis["steps"]:
        step_num = step_data["step"]
        step_name = step_data["name"]
        step_title = STEP_TITLES.get(step_name, step_name)
        step_analysis = md_to_html(step_data["analysis"])
        step_pages = step_data.get("source_pages", [])
        src = ", ".join(str(p) for p in step_pages) if step_pages else "未标注"
        steps_html += HTML_STEP_SECTION_TEMPLATE.format(
            step_num=step_num,
            step_title=step_title,
            source_pages=src,
            analysis=step_analysis,
        )
        toc_items.append(f'<a href="#step-{step_num}">{step_num}. {step_title}</a>')
    toc_items.append('<a href="#risk">6. 风险提示</a>')
    toc_items.append('<a href="#disclaimer">7. 免责声明</a>')

    return HTML_TEMPLATE.format(
        stock_name=stock_name,
        analysis_date=analysis_date,
        model=model,
        source_pages=source_pages,
        toc_html="<br>".join(toc_items),
        steps_html=steps_html,
        generation_time=generation_time,
    )


def save_html_report(report: str, stock_name: str, output_dir: str) -> str:
    """保存 HTML 研报到文件。"""
    os.makedirs(output_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{stock_name}_深度研报_{date_str}.html"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="研报生成器")
    parser.add_argument("--analysis_file", required=True, help="五步法分析结果 JSON 文件")
    parser.add_argument("--output_dir", default="./outputs/reports", help="研报输出目录")
    parser.add_argument(
        "--format",
        choices=["md", "html", "both"],
        default="md",
        help="研报输出格式: md=Markdown, html=自包含HTML, both=两种都输出",
    )
    args = parser.parse_args()

    if not os.path.exists(args.analysis_file):
        print(f"[错误] 分析文件不存在: {args.analysis_file}")
        print("[提示] 请先运行 five_step_analysis.py 生成分析结果")
        sys.exit(1)

    print(f"[开始] 生成深度分析研报")

    # 加载分析结果
    analysis = load_analysis(args.analysis_file)
    stock_name = analysis["stock_name"]
    print(f"[信息] 目标公司: {stock_name}")
    print(f"[信息] 分析步骤: {len(analysis['steps'])} 步")
    print(f"[信息] 输出格式: {args.format}")

    # 生成 Markdown 报告
    report_md = generate_report(analysis)
    print(f"[完成] Markdown 研报生成完成，共 {len(report_md)} 字符")

    # 按格式保存
    saved_files = []
    report_length = len(report_md)
    if args.format in ("md", "both"):
        filepath_md = save_report(report_md, stock_name, args.output_dir)
        saved_files.append(filepath_md)
        print(f"[保存] Markdown 研报已保存: {filepath_md}")
    if args.format in ("html", "both"):
        report_html = generate_html(analysis)
        filepath_html = save_html_report(report_html, stock_name, args.output_dir)
        saved_files.append(filepath_html)
        report_length += len(report_html)
        print(f"[保存] HTML 研报已保存: {filepath_html}")

    result = {
        "status": "success",
        "stock_name": stock_name,
        "report_files": saved_files,
        "report_length": report_length,
        "steps_included": len(analysis["steps"]),
        "format": args.format,
    }
    print(f"\n[结果] {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    main()
