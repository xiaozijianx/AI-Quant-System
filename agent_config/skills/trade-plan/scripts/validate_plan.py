# -*- coding: utf-8 -*-
# 交易计划格式验证脚本
# 在阶段C中调用, 确保生成的 Markdown 可以被 parse_plan 正确解析

import json
import re
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib.trading_plan import parse_plan


def validate(md_content: str) -> dict:
    """验证交易计划 Markdown 格式, 返回验证结果"""
    try:
        parsed = parse_plan(md_content)
    except Exception as e:
        return {
            "ok": False,
            "errors": [f"解析异常: {e}"],
        }

    errors: list[str] = []
    warnings: list[str] = []

    # 检查 frontmatter
    meta = parsed.get("metadata", {})
    required_meta = ["stock_code", "stock_name", "trade_date", "plan_type"]
    for field in required_meta:
        if field not in meta or not meta.get(field):
            errors.append(f"frontmatter 缺少必填字段: {field}")

    # 检查必需章节
    required_sections = ["当前操作建议", "仓位计划", "入场计划", "出场计划", "判断逻辑", "风控说明"]
    sections = parsed.get("sections", {})
    for sec in required_sections:
        if sec not in sections or not sections[sec].strip():
            errors.append(f"缺少必需章节: {sec}")

    # 检查出场计划是否有止盈和止损子章节
    exit_plan = parsed.get("exit_plan", {})
    if not exit_plan.get("take_profit"):
        warnings.append("出场计划中无止盈条件")
    if not exit_plan.get("stop_loss"):
        warnings.append("出场计划中无止损条件")

    # 检查入场计划是否有条件
    if not parsed.get("entry_conditions"):
        warnings.append("入场计划中无入场条件")

    # 检查每个条件块是否有有效的触发条件字段
    for cond_type, cond_list in [
        ("入场", parsed.get("entry_conditions", [])),
        ("止盈", parsed.get("exit_plan", {}).get("take_profit", [])),
        ("止损", parsed.get("exit_plan", {}).get("stop_loss", [])),
    ]:
        for cond in cond_list:
            title = cond.get("title", "(无标题)")
            has_trigger = (
                "trigger_pct" in cond
                or "trigger_price" in cond
            )
            if not has_trigger:
                errors.append(
                    f"{cond_type}条件「{title}」: 触发条件格式未识别，"
                    f"必须使用「浮盈高于 X%」「浮亏超过 X%」「价格达到/突破/跌破 ¥X.XX」之一"
                )
            # 操作字段必填: 缺少「操作: 买入/卖出 X%」时无法确定买卖比例
            # 解析不兜底, 缺失即报错(避免说明文字中的数字被误提取)
            if "action_percent" not in cond:
                errors.append(
                    f"{cond_type}条件「{title}」: 缺少「操作」字段，"
                    f"必须写 - **操作**: 买入/卖出 X%"
                )
            # 触发价字段必填: 引擎信号来源, 必须写「- 触发价: ¥X.XX」字段
            # 直接检查字段行本身, 不能依赖解析结果(触发条件字眼也可能解析出 trigger_price)
            raw = cond.get("raw", "")
            if not re.search(r"[-*]\s*\*{0,2}触发价\*{0,2}\s*[:：]", raw):
                errors.append(
                    f"{cond_type}条件「{title}」: 缺少「触发价」字段，"
                    f"必须写 - **触发价**: ¥X.XX（具体价格，引擎信号来源）"
                )
            # 触发方向建议: 有条件但未解析出 direction
            # (仅写「价格达到」/百分比 且漏写「触发方向」字段时, 依赖条件类型默认方向)
            if has_trigger and "direction" not in cond:
                warnings.append(
                    f"{cond_type}条件「{title}」: 未找到「触发方向」字段，"
                    f"建议补充 - **触发方向**: 向上/向下，确保方向明确"
                )

    # 检查仓位计划的目标占比
    position_plan = parsed.get("position_plan", {})
    target = position_plan.get("target", {})
    if target:
        if target.get("min") is None:
            warnings.append("目标占比未解析到 min")
        if target.get("max") is None:
            warnings.append("目标占比未解析到 max")
    else:
        warnings.append("仓位计划中未找到目标占比")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "sections": list(sections.keys()),
            "entry_count": len(parsed.get("entry_conditions", [])),
            "take_profit_count": len(exit_plan.get("take_profit", [])),
            "stop_loss_count": len(exit_plan.get("stop_loss", [])),
        },
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="验证交易计划 Markdown 格式")
    parser.add_argument("--file", type=str, help="从文件读取 Markdown 内容（替代 stdin）")
    args = parser.parse_args()

    raw = ""
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = PROJECT_ROOT / file_path
        if not file_path.exists():
            print(json.dumps({"ok": False, "errors": [f"文件不存在: {file_path}"]}, ensure_ascii=False))
            sys.exit(1)
        raw = file_path.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    if not raw:
        print(json.dumps({"ok": False, "errors": ["请在 stdin 传入 Markdown 内容"]}, ensure_ascii=False))
        sys.exit(1)

    result = validate(raw)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()