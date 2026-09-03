# -*- coding: utf-8 -*-
# 交易计划管理模块
"""
设计:
    - 交易计划以 Markdown 文件为唯一真相源, 人工/AI 都直接编辑 Markdown
    - 保存 Markdown 时, 后端解析出结构化字段写入数据库
    - 实盘/模拟盘引擎读取数据库中的 active 计划并执行条件判断

存储路径:
    data/trading_plans/{plan_type}/{stock_code}_{trade_date}.md
    plan_type ∈ {sim, live}
"""

from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


# ============================================================
# 路径与数据库配置
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = PROJECT_ROOT / "data" / "trading_plans"
# 复读模拟盘状态文件 (统一由 lib.paths 锚定到 outputs/live/)
from lib.paths import OUTPUTS_LIVE_STATE


def _load_db_config() -> dict:
    """读取项目根目录 .env 中的 PostgreSQL 配置"""
    try:
        from dotenv import dotenv_values
        env = dotenv_values(PROJECT_ROOT / ".env")
    except Exception:
        env = {}
    return {
        "host": env.get("WUCAI_SQL_HOST", "localhost"),
        "user": env.get("WUCAI_SQL_USERNAME", "postgres"),
        "password": env.get("WUCAI_SQL_PASSWORD", ""),
        "database": env.get("WUCAI_SQL_DB", "AI-Quant"),
        "port": int(env.get("WUCAI_SQL_PORT", "5432")),
        "client_encoding": "UTF8",
    }


def _get_connection():
    import psycopg2
    return psycopg2.connect(**_load_db_config())


def _execute_query(sql, params=None):
    """执行 SELECT, 返回 List[Dict]"""
    from psycopg2.extras import RealDictCursor
    conn = _get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _execute_update(sql, params=None):
    """执行 INSERT/UPDATE/DELETE/DDL, 返回受影响行数"""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        cur.close()
        return cur.rowcount
    finally:
        conn.close()


# ============================================================
# 数据库表初始化
# ============================================================

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trading_plan (
    id SERIAL PRIMARY KEY,
    stock_code VARCHAR(12) NOT NULL,
    stock_name VARCHAR(50),
    trade_date DATE NOT NULL,
    plan_type VARCHAR(10) NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    is_auto_trade BOOLEAN DEFAULT FALSE,
    target_ratio_min NUMERIC(5,2),
    target_ratio_max NUMERIC(5,2),
    entry_conditions JSONB DEFAULT '[]'::jsonb,
    take_profit_conditions JSONB DEFAULT '[]'::jsonb,
    stop_loss_conditions JSONB DEFAULT '[]'::jsonb,
    add_position_conditions JSONB DEFAULT '[]'::jsonb,
    md_file_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(stock_code, plan_type, trade_date)
);

COMMENT ON TABLE trading_plan IS '交易计划索引表: Markdown 为真相源, 本表只存解析后的执行字段';
COMMENT ON COLUMN trading_plan.plan_type IS 'sim=模拟盘, live=实盘';
COMMENT ON COLUMN trading_plan.is_active IS '是否生效';
COMMENT ON COLUMN trading_plan.is_auto_trade IS '是否允许引擎按条件自动执行';
"""


def init_trading_plan_table() -> str:
    """初始化 trading_plan 表, 幂等"""
    try:
        _execute_update(_CREATE_TABLE_SQL)
        return "[OK] trading_plan 表已就绪"
    except Exception as e:
        return f"[ERROR] 初始化 trading_plan 表失败: {e}"


# ============================================================
# Markdown 模板
# ============================================================

DEFAULT_PLAN_TEMPLATE = """---
stock_code: "{stock_code}"
stock_name: "{stock_name}"
trade_date: "{trade_date}"
plan_type: "{plan_type}"
is_active: {is_active}
is_auto_trade: {is_auto_trade}
---

# 当前操作建议

## 操作
{action}

## 结论
{conclusion}

## 说明
{detail}

# 仓位计划

## 当前持仓
- 占比: {current_ratio:.2f}%
- 股数: {current_volume} 股
- 成本价: ¥{cost:.2f}
- 市值: ¥{current_value:,.0f}

## 目标占比
- 目标占比: {target_ratio_min:.0f}% - {target_ratio_max:.0f}%
- 对应市值: ¥{target_value_min:,.0f} - ¥{target_value_max:,.0f}
- 目标股数: 约 {target_volume_min:.0f} - {target_volume_max:.0f} 股（按当前价 ¥{cost:.2f} 估算）
- AI 建议: 当前持仓 {current_volume} 股约 {current_ratio:.1f}%，维持不动

当前已持仓，AI 暂不建议加仓，出场触发详见下方「出场计划」。

# 入场计划

## 当前判断
### 暂不入場
- **触发条件**: 价格跌破 ¥{entry_price:.2f}
- **操作**: 买入至目标仓位
- 触发价: ¥{entry_price:.2f}（MA20 ¥{ma20:.2f} × 0.98）
- 监控方式: 盘中实时价格触发，达到即触发
- 说明: 当前已持仓 / 目标仓位已满足，暂不入場；若后续出现回踩机会再按此条件分批买入

# 出场计划

## 止盈

### 止盈 +20% 全清
- **触发条件**: 浮盈高于 20%
- **操作**: 卖出 100%
- 触发价: ¥{take_profit_price:.2f}（成本 ¥{cost:.2f} × 1.20）
- 监控方式: 盘中实时价格触发，达到即触发
- 说明: 成本约 {take_profit_price:.0f} 元止盈，与风控档位止盈线对齐，业绩兑现后一次性离场

## 止损

### 止损：跌破 MA20（留 2% 缓冲）清仓
- **触发条件**: 价格跌破 ¥{ma20_buffer_price:.2f}
- **操作**: 卖出 100%
- 触发价: ¥{ma20_buffer_price:.2f}（MA20 ¥{ma20:.2f} × 0.98）
- 监控方式: 收盘后对比收盘价，若收盘价跌破则次日开盘执行
- 说明: MA20 当前约 {ma20:.0f} 元，跌破代表趋势结构破坏，无条件离场

### 止损：成本下跌 -8% 清仓
- **触发条件**: 浮亏超过 8%
- **操作**: 卖出 100%
- 触发价: ¥{stop_loss_price:.2f}（成本 ¥{cost:.2f} × 0.92）
- 监控方式: 收盘后对比收盘价，跌破即触发
- 说明: 成本约 {stop_loss_price:.0f} 元，与风控档位止损线对齐，硬止损兜底

# 加仓计划

## 当前判断
### 暂不加仓
- **触发条件**: 事件: 股价回踩5日线或关键支撑位企稳
- **操作**: 买入至目标仓位
- 说明: 当前价格偏高 / 已满仓 / 趋势未确认，暂不建议加仓

# 判断逻辑

中线看多，短线防回调。{stock_name} 基本面与技术面综合评估：业绩趋势、行业景气度、技术形态、资金流向、估值水平等共同支撑中线逻辑；但短期涨幅过大、指标超买或接近关键压力位，存在回调消化需求。策略：持有不动，不追高加仓；跌破 MA20（趋势破坏）或成本亏损 -8% 全清止损；浮盈 +20% 全清止盈。

# 风控说明

- 单票最大仓位: {target_ratio_max:.0f}%
- 单日最大亏损: 不超过总资金的 2%
- 触发任一止损条件后无条件清仓，不补仓
- 计划有效期: 长期有效，除非基本面或趋势结构发生根本性变化
"""


def build_default_markdown(
    stock_code: str,
    stock_name: str = "",
    plan_type: str = "sim",
    trade_date: Optional[str] = None,
    current_ratio: float = 0.0,
    current_volume: int = 0,
    current_value: float = 0.0,
    target_ratio_min: float = 0.0,
    target_ratio_max: float = 0.0,
    cost: float = 0.0,
    ma20: float = 0.0,
    capital: float = 1_000_000,
    action: str = "继续持有",
    conclusion: str = "趋势未破但短期严重超买",
    detail: str = "",
    is_active: bool = False,
    is_auto_trade: bool = False,
) -> str:
    """根据持仓信息生成默认交易计划 Markdown"""
    trade_date = trade_date or date.today().isoformat()
    target_value_min = capital * target_ratio_min / 100.0
    target_value_max = capital * target_ratio_max / 100.0
    # 用成本作为当前价估算目标股数；若成本为 0 则 fallback 到 1 避免除零
    ref_price = cost if cost > 0 else 1.0
    target_volume_min = target_value_min / ref_price
    target_volume_max = target_value_max / ref_price
    # 出场计划触发价
    take_profit_price = cost * 1.20 if cost > 0 else 0.0
    ma20_value = ma20 if ma20 > 0 else cost * 0.95
    ma20_buffer_price = ma20_value * 0.98
    stop_loss_price = cost * 0.92 if cost > 0 else 0.0
    # 入场计划触发价：回踩 MA20 缓冲价（与趋势止损同一价位，形成对称）
    entry_price = ma20_buffer_price
    detail = detail or (
        "均线多头排列 + ADX 趋势明确，业绩支撑中线逻辑；但短期 RSI 超买、乖离率偏大、"
        "价格接近布林上轨，回调风险加大，不宜追高加仓。"
    )
    return DEFAULT_PLAN_TEMPLATE.format(
        stock_code=stock_code,
        stock_name=stock_name or stock_code,
        trade_date=trade_date,
        plan_type=plan_type,
        is_active=str(is_active).lower(),
        is_auto_trade=str(is_auto_trade).lower(),
        current_ratio=current_ratio,
        current_volume=current_volume,
        current_value=current_value,
        target_ratio_min=target_ratio_min,
        target_ratio_max=target_ratio_max,
        target_value_min=target_value_min,
        target_value_max=target_value_max,
        target_volume_min=target_volume_min,
        target_volume_max=target_volume_max,
        cost=cost,
        ma20=ma20_value,
        take_profit_price=take_profit_price,
        ma20_buffer_price=ma20_buffer_price,
        stop_loss_price=stop_loss_price,
        entry_price=entry_price,
        action=action,
        conclusion=conclusion,
        detail=detail,
    )


# ============================================================
# Markdown 解析器
# ============================================================

def _split_frontmatter(md: str) -> Tuple[Dict[str, Any], str]:
    """分离 YAML frontmatter 和正文"""
    if not md.startswith("---"):
        return {}, md
    parts = md.split("---", 2)
    if len(parts) < 3:
        return {}, md
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    return meta, parts[2].strip()


def _split_sections(body: str) -> Dict[str, str]:
    """按一级标题 # 分割章节"""
    sections: Dict[str, str] = {}
    current_title = None
    current_lines: List[str] = []
    for line in body.split("\n"):
        if line.startswith("# "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[2:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _extract_sub_sections(section_body: str) -> Dict[str, str]:
    """按二级标题 ## 分割子章节"""
    sub: Dict[str, str] = {}
    current_title = None
    current_lines: List[str] = []
    for line in section_body.split("\n"):
        if line.startswith("## "):
            if current_title is not None:
                sub[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sub[current_title] = "\n".join(current_lines).strip()
    return sub


def _parse_trigger_condition(text: str) -> dict:
    """解析「触发条件」字段, 返回 {trigger_pct, trigger_price, direction} 中的子集。

    注意: 此函数仅用于前端显示格式化, 引擎不直接使用 trigger_pct。
    引擎的触发信号来源是 **触发价**: 字段中的明确价格 + **触发方向**: 字段。

    支持格式（严格按此顺序匹配）:
        浮盈高于 X%     → trigger_pct = +X/100  （前端显示用, 引擎不直接使用）
        浮亏超过 X%     → trigger_pct = -X/100  （前端显示用, 引擎不直接使用）
        价格突破 ¥X.XX  → trigger_price = X.XX, direction = up
        价格跌破 ¥X.XX  → trigger_price = X.XX, direction = down
        价格达到 ¥X.XX  → trigger_price = X.XX（旧格式兼容, 不推荐使用）
    """
    result = {}
    text = text.strip()
    if not text:
        return result

    # 浮盈高于 X%
    m = re.match(r"浮盈高于\s*(\d+(?:\.\d+)?)%", text)
    if m:
        result["trigger_pct"] = float(m.group(1)) / 100.0
        return result

    # 浮亏超过 X%
    m = re.match(r"浮亏超过\s*(\d+(?:\.\d+)?)%", text)
    if m:
        result["trigger_pct"] = -float(m.group(1)) / 100.0
        return result

    # 价格达到/突破/跌破 ¥X.XX
    m = re.match(r"价格(达到|突破|跌破)\s*[¥￥]\s*(\d+(?:\.\d+)?)", text)
    if m:
        verb = m.group(1)
        result["trigger_price"] = float(m.group(2))
        # 方向语义: 价格突破=向上触发(加仓突破压力位), 价格跌破=向下触发
        # 价格达到=中性(不设 direction, 由引擎按条件类型决定方向)
        if verb == "突破":
            result["direction"] = "up"
        elif verb == "跌破":
            result["direction"] = "down"
        return result

    # 未知格式: 保留原始文本供调试
    return result


def _extract_conditions(sub_body: str) -> List[Dict[str, Any]]:
    """
    从子章节体中提取三级标题作为条件。

    每个条件块格式:
        ### {标题}
        - **触发条件**: {浮盈高于 X% | 浮亏超过 X% | 价格达到/跌破 ¥X.XX}
        - **操作**: {买入/卖出} {X%}
        - **触发价**: ¥X.XX（计算依据）
        - **说明**: {理由说明}

    解析器只从带标签的字段读取数据, 不扫描全文自由文本。
    """
    conditions: List[Dict[str, Any]] = []
    current_title = None
    current_lines: List[str] = []

    def _flush():
        if current_title is None:
            return
        body_text = "\n".join(current_lines).strip()
        cond = {"title": current_title, "raw": body_text}

        # 1. 触发条件: 只从「- **触发条件**:」字段解析
        trigger_match = re.search(r"[-*]\s*\*{0,2}触发条件\*{0,2}\s*[:：]\s*(.+)", body_text)
        if trigger_match:
            trigger_text = trigger_match.group(1).strip()
            cond.update(_parse_trigger_condition(trigger_text))

        # 2. 触发价: 从「- 触发价:」字段提取
        price_match = re.search(r"[-*]\s*\*{0,2}触发价\*{0,2}\s*[:：]\s*[¥￥]\s*(\d+(?:\.\d+)?)", body_text)
        if price_match:
            try:
                cond["trigger_price"] = float(price_match.group(1))
            except Exception:
                pass

        # 3. 操作比例: 从「- **操作**: 买入/卖出 X%」字段提取
        #    解析不兜底: 找不到「操作」字段时不设置 action_percent,
        #    由 validate_plan.py 校验并报错, 避免全文搜索数字误提取
        action_match = re.search(r"[-*]\s*\*{0,2}操作\*{0,2}\s*[:：].*?(?:买入|卖出)\s*(\d+)%", body_text)
        if action_match:
            try:
                cond["action_percent"] = float(action_match.group(1)) / 100.0
            except Exception:
                pass

        # 4. 说明: 从「- 说明:」字段提取
        desc_match = re.search(r"[-*]\s*\*{0,2}说明\*{0,2}\s*[:：]\s*(.+)", body_text)
        if desc_match:
            cond["description"] = desc_match.group(1).strip()

        # 5. 新目标占比(加仓计划专用): 从「- 新目标占比: X%」字段提取
        #    表示该加仓条件触发后, 将目标仓位提升至 X%(引擎按新目标计算缺口)
        new_target_match = re.search(
            r"[-*]\s*\*{0,2}新目标占比\*{0,2}\s*[:：]\s*(\d+(?:\.\d+)?)%", body_text
        )
        if new_target_match:
            try:
                cond["new_target_ratio"] = float(new_target_match.group(1)) / 100.0
            except Exception:
                pass

        # 6. 触发方向: 从「- 触发方向: 向上/向下」字段提取
        #    引擎信号方向字段, 优先级最高(覆盖字眼推断的 direction)
        dir_match = re.search(
            r"[-*]\s*\*{0,2}触发方向\*{0,2}\s*[:：]\s*(向上|向下)", body_text
        )
        if dir_match:
            cond["direction"] = "up" if dir_match.group(1) == "向上" else "down"

        conditions.append(cond)

    for line in sub_body.split("\n"):
        if line.startswith("### "):
            _flush()
            current_title = line[4:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)
    _flush()
    return conditions


def _parse_kv_block(text: str) -> Dict[str, Any]:
    """解析 - key: value 块"""
    result: Dict[str, Any] = {}
    for line in text.split("\n"):
        line = line.strip().lstrip("-").strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key in ("占比",):
            result["ratio"] = _parse_percent(val)
        elif key in ("股数",):
            result["volume"] = _parse_int(val)
        elif key in ("市值", "成本"):
            result["value"] = _parse_money(val)
    return result


def _parse_target_ratio(text: str) -> Dict[str, Any]:
    """解析目标占比, 如 '10% - 15%'"""
    result = {"min": None, "max": None, "advice": ""}
    nums = re.findall(r"([+-]?\d+(?:\.\d+)?)%", text)
    if len(nums) >= 1:
        result["min"] = float(nums[0]) / 100.0
    if len(nums) >= 2:
        result["max"] = float(nums[1]) / 100.0
    elif result["min"] is not None:
        result["max"] = result["min"]
    # 解析 AI 建议文案
    advice_match = re.search(r"AI\s*建议[:：]\s*(.+)", text)
    if advice_match:
        result["advice"] = advice_match.group(1).strip()
    return result


def _infer_action(text: str) -> str:
    """根据结论文案推断操作类别, 用于兼容旧模板

    规则优先级:
    1. 优先从结论判断明确方向(清仓/减仓/加仓/持有/观察)
    2. 排除否定语境, 如「不宜加仓」「不追高」「勿补仓」不应识别为买入
    3. 结论模糊时, 再结合详细说明兜底
    """
    if not text:
        return "继续观察"
    t = text.lower()

    # 否定词: 在这些词之后的买入/卖出关键字不算数
    negation_prefixes = ("不宜", "不要", "不", "勿", "禁止", "避免", "别", "无须", "无需")

    def _has_keyword(s: str, keywords: Tuple[str, ...]) -> bool:
        """判断字符串中是否出现关键字, 但排除紧跟在否定词后的命中"""
        for kw in keywords:
            idx = s.find(kw)
            if idx == -1:
                continue
            # 检查关键字前面最近的否定词(允许 0~4 个字符间隔)
            before = s[max(0, idx - 8):idx]
            if any(before.endswith(np) for np in negation_prefixes):
                continue
            return True
        return False

    # 1) 清仓/离场
    if _has_keyword(t, ("清仓", "立刻清仓", "全部卖出", "止盈全清", "止损全清", "无条件离场")):
        return "立刻清仓"
    if _has_keyword(t, ("卖出", "离场")):
        return "清仓卖出"
    # 2) 减仓
    if _has_keyword(t, ("减仓", "降低仓位", "止盈部分", "减仓观望")):
        return "减仓"
    # 3) 加仓/买入/低吸
    if _has_keyword(t, ("加仓", "买入", "补仓", "低吸", "增持", "建仓")):
        return "加仓/买入"
    # 4) 继续持有/观望
    if _has_keyword(t, ("持有", "持仓", "持有不动", "持仓不动", "不动")):
        return "继续持有"
    if _has_keyword(t, ("观望", "观察", "等待", "继续观察")):
        return "继续观察"
    # 5) 兜底: 超买/回调/压力 → 继续观察
    if any(k in t for k in ("超买", "回调", "压力", "震荡", "谨慎", "风险大")):
        return "继续观察"
    return "继续观察"


def _parse_current_opinion(section_body: str) -> Dict[str, Any]:
    """解析「当前操作建议」章节, 抽出操作/结论/说明"""
    result = {"action": "", "conclusion": "", "detail": ""}
    if not section_body:
        return result
    # 去掉 HTML 注释, 避免注释内容被当作结论
    cleaned = re.sub(r"<!--.*?-->", "", section_body, flags=re.DOTALL).strip()
    subs = _extract_sub_sections(cleaned)
    action = subs.get("操作", "").strip()
    conclusion = subs.get("结论", "").strip()
    detail = subs.get("说明", "").strip()
    # 兼容旧模板: 没有 ## 操作 / ## 结论 / ## 说明 时, 尝试从 KV 或第一行解析
    if not action:
        m = re.search(r"[-*]\s*操作[:：]\s*(.+)", cleaned)
        if m:
            action = m.group(1).strip()
    if not conclusion and not detail:
        lines = [l.strip() for l in cleaned.split("\n") if l.strip()]
        if lines:
            conclusion = lines[0]
            detail = "\n".join(lines[1:]).strip()
    # 若仍无操作类别, 从结论推断一个默认值, 避免卡片只有结论没有动作
    if not action:
        action = _infer_action(conclusion + " " + detail)
    result["action"] = action
    result["conclusion"] = conclusion
    result["detail"] = detail
    return result


def _parse_percent(text: str) -> float:
    """解析 '15.47%' -> 0.1547"""
    m = re.search(r"([+-]?\d+(?:\.\d+)?)%", text)
    if not m:
        return 0.0
    return float(m.group(1)) / 100.0


def _is_plan_complete(parsed: dict) -> bool:
    """判断交易计划是否包含全部 5 个核心章节（已移除加仓计划概念）"""
    sections = (parsed or {}).get("sections", {})
    required = ("当前操作建议", "仓位计划", "出场计划", "判断逻辑", "风控说明")
    return all(s in sections and sections[s].strip() for s in required)


def _ensure_triggered_flag(conditions: List[dict]) -> List[dict]:
    """确保每个条件带 triggered 字段(默认 False)。

    triggered 用于"信号只触发一次": 条件被引擎触发并标记为 True 后,
    evaluate_plan 会跳过该条件, 避免同一信号点反复触发(如跌破25买入后,
    价格再涨上去又跌回25不再买入, 只有新的条件价才触发)。
    """
    for c in conditions:
        if isinstance(c, dict):
            c.setdefault("triggered", False)
    return conditions


def _parse_int(text: str) -> int:
    m = re.search(r"\d+", text.replace(",", ""))
    if not m:
        return 0
    return int(m.group(0))


def _parse_money(text: str) -> float:
    """解析 '¥61,190' -> 61190.0"""
    m = re.search(r"[¥￥]?\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return 0.0
    return float(m.group(1).replace(",", ""))


def parse_plan(md_content: str) -> Dict[str, Any]:
    """
    解析交易计划 Markdown, 返回结构化字典。
    结果包含 metadata, sections(原始章节), conditions(可执行条件)。
    """
    meta, body = _split_frontmatter(md_content)
    sections = _split_sections(body)
    # 清理章节中的 HTML 注释, 避免前端显示占位注释
    sections = {k: re.sub(r"<!--.*?-->", "", v, flags=re.DOTALL).strip() for k, v in sections.items()}

    # 当前操作建议解析
    current_opinion = _parse_current_opinion(sections.get("当前操作建议", ""))

    # 仓位计划解析
    position_plan = {}
    pos_section = sections.get("仓位计划", "")
    pos_subs = _extract_sub_sections(pos_section)
    for sub_title, sub_body in pos_subs.items():
        if sub_title.startswith("当前持仓"):
            position_plan["current"] = _parse_kv_block(sub_body)
        elif sub_title.startswith("目标占比"):
            position_plan["target"] = _parse_target_ratio(sub_body)

    # 出场计划解析
    exit_plan = {"take_profit": [], "stop_loss": []}
    exit_section = sections.get("出场计划", "")
    exit_subs = _extract_sub_sections(exit_section)
    for sub_title, sub_body in exit_subs.items():
        if "止盈" in sub_title:
            exit_plan["take_profit"] = [dict(c, side="sell") for c in _extract_conditions(sub_body)]
        elif "止损" in sub_title:
            exit_plan["stop_loss"] = [dict(c, side="sell") for c in _extract_conditions(sub_body)]

    # 加仓计划解析
    add_section = sections.get("加仓计划", "")
    add_conditions = [dict(c, side="buy") for c in _extract_conditions(add_section)]

    # 入场条件(如有独立章节)
    entry_section = sections.get("入场计划", "")
    entry_conditions = [dict(c, side="buy") for c in _extract_conditions(entry_section)]

    return {
        "metadata": meta,
        "sections": sections,
        "current_opinion": current_opinion,
        "position_plan": position_plan,
        "exit_plan": exit_plan,
        "add_position_conditions": add_conditions,
        "entry_conditions": entry_conditions,
    }


# ============================================================
# 交易计划管理器
# ============================================================

class PlanManager:
    """交易计划 CRUD: Markdown 文件 + 数据库索引"""

    def __init__(self):
        PLANS_DIR.mkdir(parents=True, exist_ok=True)

    def _plan_path(self, stock_code: str, plan_type: str, trade_date: str) -> Path:
        d = PLANS_DIR / plan_type
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{stock_code}_{trade_date}.md"

    def _read_md(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _write_md(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    def _find_latest_path(self, stock_code: str, plan_type: str) -> Optional[Path]:
        """查找某股票某类型下日期最新的 Markdown 文件"""
        d = PLANS_DIR / plan_type
        if not d.exists():
            return None
        pattern = f"{stock_code}_*.md"
        candidates = list(d.glob(pattern))
        if not candidates:
            return None
        # 按文件名中的日期倒序, 取最新
        candidates.sort(key=lambda p: p.stem.split("_")[-1], reverse=True)
        return candidates[0]

    def _parsed_to_db_row(self, stock_code: str, plan_type: str, trade_date: str,
                          md_path: Path, parsed: dict) -> Tuple[dict, str]:
        """把解析结果转成数据库行数据和错误信息"""
        meta = parsed.get("metadata") or {}
        position_plan = parsed.get("position_plan") or {}
        exit_plan = parsed.get("exit_plan") or {}
        target = position_plan.get("target") or {}

        row = {
            "stock_code": stock_code,
            "stock_name": meta.get("stock_name", ""),
            "trade_date": trade_date,
            "plan_type": plan_type,
            "is_active": bool(meta.get("is_active", False)),
            "is_auto_trade": bool(meta.get("is_auto_trade", False)),
            "target_ratio_min": target.get("min"),
            "target_ratio_max": target.get("max"),
            "entry_conditions": json.dumps(_ensure_triggered_flag(parsed.get("entry_conditions", []))),
            "take_profit_conditions": json.dumps(_ensure_triggered_flag(exit_plan.get("take_profit", []))),
            "stop_loss_conditions": json.dumps(_ensure_triggered_flag(exit_plan.get("stop_loss", []))),
            "add_position_conditions": json.dumps(_ensure_triggered_flag(parsed.get("add_position_conditions", []))),
            "md_file_path": str(md_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }
        return row, ""

    def save(self, stock_code: str, plan_type: str, trade_date: str,
             md_content: str) -> dict:
        """
        保存 Markdown 并同步解析到数据库。
        返回 {"ok": bool, "message": str, "parsed": dict}
        """
        stock_code = (stock_code or "").strip()
        plan_type = (plan_type or "sim").strip()
        trade_date = (trade_date or date.today().isoformat()).strip()
        if not stock_code:
            return {"ok": False, "message": "stock_code 不能为空"}
        if plan_type not in ("sim", "live"):
            return {"ok": False, "message": "plan_type 必须是 sim 或 live"}

        path = self._plan_path(stock_code, plan_type, trade_date)
        try:
            parsed = parse_plan(md_content)
        except Exception as e:
            return {"ok": False, "message": f"Markdown 解析失败: {e}"}

        # 写 Markdown 文件
        self._write_md(path, md_content)

        # 同步数据库
        row, err = self._parsed_to_db_row(stock_code, plan_type, trade_date, path, parsed)
        if err:
            return {"ok": False, "message": err}

        upsert_sql = """
        INSERT INTO trading_plan (
            stock_code, stock_name, trade_date, plan_type, is_active, is_auto_trade,
            target_ratio_min, target_ratio_max,
            entry_conditions, take_profit_conditions, stop_loss_conditions,
            add_position_conditions, md_file_path, updated_at
        ) VALUES (
            %(stock_code)s, %(stock_name)s, %(trade_date)s, %(plan_type)s,
            %(is_active)s, %(is_auto_trade)s,
            %(target_ratio_min)s, %(target_ratio_max)s,
            %(entry_conditions)s::jsonb, %(take_profit_conditions)s::jsonb,
            %(stop_loss_conditions)s::jsonb, %(add_position_conditions)s::jsonb,
            %(md_file_path)s, NOW()
        )
        ON CONFLICT (stock_code, plan_type, trade_date) DO UPDATE SET
            stock_name = EXCLUDED.stock_name,
            is_active = EXCLUDED.is_active,
            is_auto_trade = EXCLUDED.is_auto_trade,
            target_ratio_min = EXCLUDED.target_ratio_min,
            target_ratio_max = EXCLUDED.target_ratio_max,
            entry_conditions = EXCLUDED.entry_conditions,
            take_profit_conditions = EXCLUDED.take_profit_conditions,
            stop_loss_conditions = EXCLUDED.stop_loss_conditions,
            add_position_conditions = EXCLUDED.add_position_conditions,
            md_file_path = EXCLUDED.md_file_path,
            updated_at = NOW();
        """
        try:
            _execute_update(upsert_sql, row)
        except Exception as e:
            return {"ok": False, "message": f"数据库写入失败: {e}"}

        return {"ok": True, "message": "已保存", "parsed": parsed}

    def get(self, stock_code: str, plan_type: str, trade_date: str) -> Optional[dict]:
        """读取指定交易计划, 返回 {metadata, raw_markdown, parsed}。
        若指定日期不存在, 自动回退到该股票该类型下日期最新的文件。
        """
        path = self._plan_path(stock_code, plan_type, trade_date)
        md = self._read_md(path)
        if md is None:
            latest = self._find_latest_path(stock_code, plan_type)
            if latest is None:
                return None
            md = self._read_md(latest)
            if md is None:
                return None
        parsed = parse_plan(md)
        return {
            "metadata": parsed.get("metadata", {}),
            "raw_markdown": md,
            "parsed": parsed,
        }

    def get_or_create(self, stock_code: str, plan_type: str = "sim",
                      trade_date: Optional[str] = None,
                      force: bool = False,
                      **kwargs) -> dict:
        """如果不存在则生成默认计划并返回; 若 force=True 或旧计划章节缺失则重新生成"""
        trade_date = trade_date or date.today().isoformat()
        existing = self.get(stock_code, plan_type, trade_date)
        if existing and not force and _is_plan_complete(existing.get("parsed", {})):
            return existing
        # 重新生成: 先删除旧文件与数据库记录, 再用最新模板创建
        if existing:
            self.delete(stock_code, plan_type, trade_date)
        md = build_default_markdown(stock_code=stock_code, plan_type=plan_type,
                                    trade_date=trade_date, **kwargs)
        self.save(stock_code, plan_type, trade_date, md)
        return self.get(stock_code, plan_type, trade_date)

    def delete(self, stock_code: str, plan_type: str, trade_date: str) -> dict:
        path = self._plan_path(stock_code, plan_type, trade_date)
        if path.exists():
            path.unlink()
        sql = """
        DELETE FROM trading_plan
        WHERE stock_code = %s AND plan_type = %s AND trade_date = %s
        """
        try:
            _execute_update(sql, (stock_code, plan_type, trade_date))
            return {"ok": True, "message": "已删除"}
        except Exception as e:
            return {"ok": False, "message": f"删除失败: {e}"}

    def list_plans(self, plan_type: Optional[str] = None,
                   is_active: Optional[bool] = None,
                   is_auto_trade: Optional[bool] = None) -> List[dict]:
        """列出交易计划索引, 每只股票只返回最新 trade_date 的一条记录。

        监控页用 stock_code 做字典 key, 若返回多日期记录会被旧记录覆盖,
        因此后端直接按 (stock_code, plan_type) 去重并取最新日期。
        """
        where = ["1=1"]
        params = []
        if plan_type is not None:
            where.append("plan_type = %s")
            params.append(plan_type)
        if is_active is not None:
            where.append("is_active = %s")
            params.append(is_active)
        if is_auto_trade is not None:
            where.append("is_auto_trade = %s")
            params.append(is_auto_trade)
        sql = f"""
        SELECT DISTINCT ON (stock_code, plan_type)
               id, stock_code, stock_name, trade_date, plan_type,
               is_active, is_auto_trade, target_ratio_min, target_ratio_max,
               md_file_path, created_at, updated_at
        FROM trading_plan
        WHERE {' AND '.join(where)}
        ORDER BY stock_code, plan_type, trade_date DESC
        """
        return _execute_query(sql, params)

    def get_active_plan(self, stock_code: str, plan_type: str = "sim") -> Optional[dict]:
        """获取某只股票最近一个生效且允许自动交易的交易计划"""
        sql = """
        SELECT id, stock_code, stock_name, trade_date, plan_type,
               is_active, is_auto_trade, target_ratio_min, target_ratio_max,
               entry_conditions, take_profit_conditions, stop_loss_conditions,
               add_position_conditions, md_file_path
        FROM trading_plan
        WHERE stock_code = %s AND plan_type = %s
          AND is_active = TRUE AND is_auto_trade = TRUE
        ORDER BY trade_date DESC
        LIMIT 1
        """
        rows = _execute_query(sql, (stock_code, plan_type))
        if not rows:
            return None
        row = rows[0]
        for key in ("entry_conditions", "take_profit_conditions",
                    "stop_loss_conditions", "add_position_conditions"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except Exception:
                    row[key] = []
        return row

    def get_effective_plan(self, stock_code: str, plan_type: str = "sim") -> Optional[dict]:
        """获取某只股票最近一个生效的交易计划(不限制是否自动执行), 用于条件评估。"""
        sql = """
        SELECT id, stock_code, stock_name, trade_date, plan_type,
               is_active, is_auto_trade, target_ratio_min, target_ratio_max,
               entry_conditions, take_profit_conditions, stop_loss_conditions,
               add_position_conditions, md_file_path
        FROM trading_plan
        WHERE stock_code = %s AND plan_type = %s
          AND is_active = TRUE
        ORDER BY trade_date DESC
        LIMIT 1
        """
        rows = _execute_query(sql, (stock_code, plan_type))
        if not rows:
            return None
        row = rows[0]
        for key in ("entry_conditions", "take_profit_conditions",
                    "stop_loss_conditions", "add_position_conditions"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except Exception:
                    row[key] = []
        return row

    def get_overview(self, stock_code: str, plan_type: str = "sim") -> Optional[dict]:
        """获取某只股票最近一个交易计划的结构化字段(来自数据库), 用于监控页概览展示。

        与 get_active_plan 区别:
            - get_active_plan 只返回 is_active=TRUE 且 is_auto_trade=TRUE 的计划,
              供执行引擎使用;
            - get_overview 不限制生效状态, 只要数据库里有解析记录就返回,
              供模拟盘/实盘监控页做参考展示。
        返回结构与 parse_plan 生成的 parsed 兼容, 前端可直接复用。
        """
        sql = """
        SELECT id, stock_code, stock_name, trade_date, plan_type,
               is_active, is_auto_trade, target_ratio_min, target_ratio_max,
               entry_conditions, take_profit_conditions, stop_loss_conditions,
               add_position_conditions, md_file_path
        FROM trading_plan
        WHERE stock_code = %s AND plan_type = %s
        ORDER BY trade_date DESC
        LIMIT 1
        """
        rows = _execute_query(sql, (stock_code, plan_type))
        if not rows:
            return None
        row = rows[0]
        for key in ("entry_conditions", "take_profit_conditions",
                    "stop_loss_conditions", "add_position_conditions"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except Exception:
                    row[key] = []
        # 拼装成与 parse_plan 输出一致的结构, 方便前端复用
        return {
            "metadata": {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "trade_date": str(row["trade_date"]),
                "plan_type": row["plan_type"],
                "is_active": row["is_active"],
                "is_auto_trade": row["is_auto_trade"],
            },
            "parsed": {
                "exit_plan": {
                    "take_profit": row.get("take_profit_conditions") or [],
                    "stop_loss": row.get("stop_loss_conditions") or [],
                },
                "add_position_conditions": row.get("add_position_conditions") or [],
                "entry_conditions": row.get("entry_conditions") or [],
            },
        }

    def mark_condition_triggered(self, plan_id: int, cond_type: str,
                                 cond_index: int) -> bool:
        """把某个条件的 triggered 标记为 True, 使其不再被 evaluate_plan 触发。

        用于"信号只触发一次": 条件被引擎触发并成交/生成信号后, 写回数据库标注,
        之后即使价格再次满足该条件(如再次跌破同一价格)也不再触发。
        新的交易计划(save 重新入库)会重置所有 triggered 为 False。

        cond_type: entry / take_profit / stop_loss / add_position
        cond_index: 条件在对应 JSONB 数组中的下标
        """
        col_map = {
            "entry": "entry_conditions",
            "take_profit": "take_profit_conditions",
            "stop_loss": "stop_loss_conditions",
            "add_position": "add_position_conditions",
        }
        col = col_map.get(cond_type)
        if col is None or plan_id is None:
            return False
        try:
            rows = _execute_query(
                f"SELECT {col} FROM trading_plan WHERE id = %s", (plan_id,)
            )
            if not rows:
                return False
            conds = rows[0].get(col) or []
            if isinstance(conds, str):
                conds = json.loads(conds)
            if not isinstance(conds, list) or not (0 <= cond_index < len(conds)):
                return False
            conds[cond_index]["triggered"] = True
            _execute_update(
                f"UPDATE trading_plan SET {col} = %s::jsonb WHERE id = %s",
                (json.dumps(conds, ensure_ascii=False), plan_id),
            )
            return True
        except Exception:
            return False

    def update_target_ratio(self, plan_id: int, new_ratio: float) -> bool:
        """把交易计划的目标仓位上限制更新为新值(小数, 如 0.20)。

        用于加仓条件成交后持久化「新目标占比」: 目标仓位立即生效,
        后续买入/卖出基准、前端展示、风控均基于新目标计算。
        """
        if plan_id is None:
            return False
        try:
            _execute_update(
                "UPDATE trading_plan SET target_ratio_max = %s WHERE id = %s",
                (round(float(new_ratio), 4), plan_id),
            )
            return True
        except Exception:
            return False


# ============================================================
# 交易计划执行: 根据当前价判断触发哪些条件
# ============================================================

def evaluate_plan(plan: dict, current_price: float, position: Optional[dict] = None) -> List[dict]:
    """
    评估交易计划, 返回触发的信号列表。
    每个信号: {"side": "buy"/"sell", "reason": str, "trigger": str, "percent": float}

    评估规则:
      - 所有触发条件最终落地为价格, 引擎只比较价格
      - 触发方向由「字眼」决定, 条件类型只提供默认值:
        - 价格突破 → 向上触发(>=): 入场/加仓向上买入, 止盈向上卖出
        - 价格跌破 → 向下触发(<=): 止损向下卖出, 入场/加仓向下补仓
        - 价格达到 → 无方向字段, 按条件类型默认(止盈=向上, 止损/入场/加仓=向下)
      - 止盈默认向上(>=), 止损默认向下(<=), 入场/加仓默认向下(<=)

    触发价来源优先级:
      1. **触发价**: 字段中的明确价格（最优先）
      2. trigger_pct + cost 计算（兼容旧数据,  engine 自动计算: 止盈价 = cost * (1 + pct), 止损价 = cost * (1 + pct)）
    """
    signals: List[dict] = []
    position = position or {}
    cost = float(position.get("cost", 0) or 0)

    def _get_trigger_price(cond: dict) -> float | None:
        """获取有效的触发价: 优先用 trigger_price, 没有则从 trigger_pct + cost 计算"""
        if "trigger_price" in cond and cond["trigger_price"] is not None:
            return float(cond["trigger_price"])
        if "trigger_pct" in cond and cond["trigger_pct"] is not None and cost > 0:
            return cost * (1.0 + float(cond["trigger_pct"]))
        return None

    # 止盈 (默认向上: 价格涨到/突破触发价卖出; 触发条件写「价格跌破」则向下卖出)
    for i, cond in enumerate(plan.get("take_profit_conditions", []) or []):
        if cond.get("triggered"):
            continue
        tp = _get_trigger_price(cond)
        if tp is None:
            continue
        direction = cond.get("direction", "up")
        triggered = (
            current_price >= tp if direction == "up"
            else current_price <= tp
        )
        if triggered:
            signals.append({
                "side": "sell",
                "reason": f"{cond.get('title', '止盈')} (当前价 {current_price:.2f} "
                          f"{'>=' if direction == 'up' else '<='} 触发价 {tp:.2f})",
                "trigger": "take_profit",
                "percent": cond.get("action_percent", 1.0),
                "cond_index": i,
            })

    # 止损 (默认向下: 价格跌破触发价卖出; 触发条件写「价格突破」则向上卖出)
    for i, cond in enumerate(plan.get("stop_loss_conditions", []) or []):
        if cond.get("triggered"):
            continue
        tp = _get_trigger_price(cond)
        if tp is None:
            continue
        direction = cond.get("direction", "down")
        triggered = (
            current_price <= tp if direction == "down"
            else current_price >= tp
        )
        if triggered:
            signals.append({
                "side": "sell",
                "reason": f"{cond.get('title', '止损')} (当前价 {current_price:.2f} "
                          f"{'<=' if direction == 'down' else '>='} 触发价 {tp:.2f})",
                "trigger": "stop_loss",
                "percent": cond.get("action_percent", 1.0),
                "cond_index": i,
            })

    # 加仓 (默认向下补仓, 触发条件写「价格突破」则向上突破加仓)
    for i, cond in enumerate(plan.get("add_position_conditions", []) or []):
        if cond.get("triggered"):
            continue
        tp = _get_trigger_price(cond)
        if tp is None:
            continue
        direction = cond.get("direction", "down")
        triggered = (
            current_price >= tp if direction == "up"
            else current_price <= tp
        )
        if triggered:
            signals.append({
                "side": "buy",
                "reason": f"{cond.get('title', '加仓')} (当前价 {current_price:.2f} "
                          f"{'>=' if direction == 'up' else '<='} 触发价 {tp:.2f})",
                "trigger": "add_position",
                "percent": cond.get("action_percent", 0.5),
                # 透传新目标占比: 触发后目标仓位提升至该值, 由 make_plan_evaluator 计算买入量
                "new_target_ratio": cond.get("new_target_ratio"),
                "cond_index": i,
            })

    # 入场 (默认向下低吸买入, 触发条件写「价格突破」则向上突破买入)
    for i, cond in enumerate(plan.get("entry_conditions", []) or []):
        if cond.get("triggered"):
            continue
        tp = _get_trigger_price(cond)
        if tp is None:
            continue
        direction = cond.get("direction", "down")
        triggered = (
            current_price >= tp if direction == "up"
            else current_price <= tp
        )
        if triggered:
            signals.append({
                "side": "buy",
                "reason": f"{cond.get('title', '入场')} (当前价 {current_price:.2f} "
                          f"{'>=' if direction == 'up' else '<='} 触发价 {tp:.2f})",
                "trigger": "entry",
                "percent": cond.get("action_percent", 0.5),
                "cond_index": i,
            })

    return signals


# ============================================================
# 兼容性: 让 LiveTradingLoop 可以把 PlanManager 当作 evaluator 使用
# ============================================================

def _load_position_for_evaluator(code: str, state_file=None):
    """为交易计划评估读取当前持仓(成本/数量), 用于浮盈百分比止损/止盈。
    state_file: 可选, 指定状态文件路径, 默认使用模拟盘的 live_state.json"""
    path = Path(state_file) if state_file else OUTPUTS_LIVE_STATE
    try:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            for p in (state.get("positions") or []):
                if p.get("code") == code:
                    return {
                        "volume": int(p.get("volume", 0) or 0),
                        "cost": float(p.get("cost", 0) or 0),
                        "cur_price": float(p.get("cur_price", 0) or 0),
                    }
    except Exception:
        pass
    return {}


def make_plan_evaluator(plan_type: str = "sim", state_file=None):
    """
    返回一个 evaluator(code, market, capital) -> dict,
    供 LiveTradingLoop / StrategyRouter 调用。
    有生效交易计划时按交易计划评估, 否则返回 hold。

    规则:
      - 只要计划处于「生效」状态即评估条件(无论是否自动执行)
      - 自动执行=false 时, 信号会带上 _plan_auto_trade=false,
        由 LiveTradingLoop._handle_signal 决定不下单、只记录待确认
      - 评估时读取当前持仓成本, 使浮盈百分比类止盈/止损能正确触发
      - state_file: 可选, 指定持仓状态文件的路径, 实盘应传入 live_state_real.json
    """
    manager = PlanManager()

    def evaluator(code: str, market, capital: float) -> dict:
        plan = manager.get_effective_plan(code, plan_type)
        if not plan:
            return {"side": "hold", "strategy": "no_plan", "reason": "无生效交易计划"}
        tick = market.get_latest_tick(code)
        price = float(tick.get("lastPrice", 0))
        if price <= 0:
            return {"side": "hold", "strategy": "plan", "reason": "无法获取当前价"}
        position = _load_position_for_evaluator(code, state_file=state_file)
        signals = evaluate_plan(plan, price, position)
        if not signals:
            return {"side": "hold", "strategy": "plan", "reason": "交易计划条件未触发"}
        # 多个信号同时触发时, 按优先级取一个: 止损 > 止盈 > 加仓 > 入场
        priority = {"stop_loss": 0, "take_profit": 1, "add_position": 2, "entry": 3}
        signals.sort(key=lambda x: priority.get(x.get("trigger"), 99))
        sig = signals[0]

        # === 目标仓位检查（上层拦截，不修改引擎） ===
        # 计算当前持仓比例
        volume = int(position.get("volume", 0) or 0)
        cur_price = float(position.get("cur_price", 0) or price)
        current_value = volume * cur_price
        current_ratio = current_value / capital if capital > 0 else 0.0
        target_ratio_max = float(plan.get("target_ratio_max", 0) or 0)

        # 买入信号: 优先使用加仓条件携带的新目标占比, 否则使用计划目标上限
        # 加仓突破场景: 条件块中「新目标占比: 20%」表示触发后目标仓位提升至 20%,
        # 买入量按新目标 × 操作比例计算(如新目标20%、操作50% → 买入 10%仓位)
        if sig["side"] == "buy" and sig.get("trigger") == "add_position" \
                and sig.get("new_target_ratio"):
            target_ratio = float(sig["new_target_ratio"])
        else:
            target_ratio = target_ratio_max

        # 买入信号: 当前仓位已 >= 目标仓位, 不生成买入信号
        if sig["side"] == "buy" and target_ratio > 0 and current_ratio >= target_ratio:
            return {"side": "hold", "strategy": "plan",
                    "reason": f"当前仓位 {current_ratio:.1%} 已达目标仓位 {target_ratio:.1%}"}

        # 买入信号: 将 percent 语义从"可用资金比例"转换为"目标仓位的绝对比例"
        #
        # 语义约定(固定基准, 与当前持仓/缺口无关):
        #   percent = 目标仓位 × X%   例: 目标仓位30%, percent=0.5 → 本次买入目标仓位的50% = 15%仓位
        #   分阶段加仓 30%+30%+40% = 100% → 合计正好买满目标仓位
        #   系统自动限制: 买入不超过目标仓位与当前持仓的缺口
        #
        # 转换公式: cash_percent = min(target_ratio × percent, gap) / available_ratio
        if sig["side"] == "buy" and target_ratio > 0:
            target_qty_ratio = target_ratio * sig.get("percent", 1.0)  # 目标买入仓位(绝对比例)
            gap = target_ratio - current_ratio
            if gap <= 0:
                return {"side": "hold", "strategy": "plan",
                        "reason": f"已达目标仓位 {target_ratio:.1%}"}
            buy_ratio = min(target_qty_ratio, gap)  # 不超过目标仓位上限
            available_ratio = 1.0 - current_ratio
            if available_ratio > 0:
                # 转换为 _handle_signal 能理解的可用资金比例
                sig["percent"] = min(buy_ratio / available_ratio, 1.0)

        # 卖出信号: 将 percent 语义从"持仓股数比例"转换为"目标仓位的绝对比例"
        #
        # 语义约定(固定基准, 与当前持仓/缺口无关):
        #   percent = 目标仓位 × X%   例: 目标仓位30%, percent=0.3 → 本次卖出目标仓位的30% = 9%仓位
        #   分阶段减仓 30%+30%+40% = 100% → 合计正好卖完目标仓位
        #   系统自动限制: 卖出不超过实际持仓(实际持仓不足时按实际持仓卖出)
        #
        # 转换公式: volume_percent = min(target_ratio × percent / current_ratio, 1.0)
        if sig["side"] == "sell":
            sell_target_ratio = target_ratio_max * sig.get("percent", 1.0)  # 目标卖出仓位(绝对比例)
            if current_ratio > 0:
                sig["percent"] = min(sell_target_ratio / current_ratio, 1.0)

        # 信号只触发一次: 不在信号生成时标记, 而是由交易引擎在信号真正成交
        # (生成交易流水)后, 通过 on_plan_executed 钩子回调 on_plan_signal_executed,
        # 把对应条件标记为已触发。信号中透传计划元数据供成交后回溯定位。
        return {
            "side": sig["side"],
            "strategy": "plan",
            "reason": sig["reason"],
            "percent": sig.get("percent", 1.0 if sig["side"] == "sell" else 0.5),
            "_plan_auto_trade": bool(plan.get("is_auto_trade", False)),
            "_plan_signals": signals,
            # 计划信号元数据: 交易引擎成交后原样回传给钩子, 用于定位并标记条件
            "_plan_id": plan.get("id"),
            "_plan_cond_type": sig.get("trigger"),
            "_plan_cond_index": sig.get("cond_index"),
            # 加仓条件的新目标占比: 成交后由处理器持久化更新计划目标仓位
            "_plan_new_target_ratio": sig.get("new_target_ratio"),
        }

    return evaluator


def on_plan_signal_executed(signal: dict) -> None:
    """交易计划信号成交后的处理器: 把对应条件标记为已触发(只触发一次)。

    由装配层(live_simulator)注入为 LiveTradingLoop 的 on_plan_executed 钩子,
    交易引擎在信号真正成交并生成交易流水后调用。之后 evaluate_plan 会跳过
    该条件, 避免同一信号点反复触发(如跌破25买入后, 价格再涨上去又跌回25
    不再买入, 只有新的条件价才触发)。

    加仓条件成交时, 同步把计划目标仓位上限制持久化更新为「新目标占比」,
    与 triggered 标记同一时机(成交后), 未成交(资金不足/待确认)不更新。

    signal 需含 _plan_id / _plan_cond_type / _plan_cond_index 字段
    (由 make_plan_evaluator 在信号中透传), 加仓信号还含 _plan_new_target_ratio。
    """
    plan_id = signal.get("_plan_id")
    cond_type = signal.get("_plan_cond_type")
    cond_index = signal.get("_plan_cond_index")
    if plan_id is None or cond_type not in (
        "entry", "take_profit", "stop_loss", "add_position"
    ) or cond_index is None:
        return
    manager = PlanManager()
    manager.mark_condition_triggered(plan_id, cond_type, cond_index)
    # 加仓成交后: 目标仓位上限制更新为新目标占比
    new_ratio = signal.get("_plan_new_target_ratio")
    if cond_type == "add_position" and new_ratio:
        try:
            manager.update_target_ratio(plan_id, float(new_ratio))
        except Exception:
            pass
