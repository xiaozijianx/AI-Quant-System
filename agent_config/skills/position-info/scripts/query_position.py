#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询当前持仓信息 + ATR 计算
从 live_state.json / live_state_real.json 读取持仓数据，
从日 K 计算 14 日 ATR（平均真实波幅）。

输出格式：每个字段附带 meaning 中文描述，帮助 LLM 理解数值含义（对标板块轮动技能）。
"""

import sys
import json
from pathlib import Path

import pandas as pd
import numpy as np

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))


# 字段中文含义（输出时附带，帮助 LLM 理解数值方向）
ACCOUNT_MEANINGS = {
    "total_capital": "初始本金（来自 state.initial_capital，引擎启动时设置，交易过程中不变）",
    "total_pnl": "总盈亏（总资产 - 初始本金，包含已实现利润和未实现浮动盈亏）",
    "total_value": "总资产价值（剩余现金 + 持仓市值 = 当前全部资产）",
    "total_market_value": "持仓总市值（所有持仓当前市值之和）",
    "available_capital": "可用资金（state.capital = 剩余现金，引擎实时维护，可用于买入新股票）",
}

POSITION_MEANINGS = {
    "has_position": "是否持有该股（true=持有，false=未持仓）",
    "volume": "持仓股数（0=未持仓）",
    "cost": "持仓均价（均价，未持仓时为0）",
    "cur_price": "最新价（当前行情价）",
    "market_value": "该股市值（volume × cur_price）",
    "pnl": "该股盈亏金额（未持仓时为0）",
    "pnl_pct": "该股盈亏百分比（未持仓时为0）",
    "position_ratio": "该股持仓占总资金比例(%)（未持仓时为0）",
    "atr_14": "14日ATR（平均真实波幅），衡量波动率，用于止损止盈计算",
}


def _calc_atr(code: str, period: int = 14) -> float:
    """从日 K 计算 ATR（Average True Range）"""
    try:
        from lib.backtest_data import load_daily_kline
        df = load_daily_kline(code, start_date=None, end_date=None, prefer="auto")
        if df is None or len(df) < period + 1:
            return 0.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        # True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        atr = float(pd.Series(tr).rolling(period).mean().iloc[-1])
        return round(atr, 4)
    except Exception:
        return 0.0


def _v(value, meaning: str) -> dict:
    """构造带含义的值对象 — 对标板块轮动技能 INDICATOR_MEANINGS 格式"""
    return {"value": value, "meaning": meaning}


def query_position(code: str, plan_type: str = "sim") -> dict:
    """查询指定股票在模拟盘/实盘中的持仓信息，同时返回账户整体概况"""
    from lib.paths import OUTPUTS_DIR

    state_file = OUTPUTS_DIR / (
        "live_state_real.json" if plan_type == "live" else "live_state.json"
    )

    # 账户整体概况（带含义）
    account = {}
    for key, meaning in ACCOUNT_MEANINGS.items():
        account[key] = _v(0.0, meaning)

    # 指定股票的持仓详情（带含义）
    position = {}
    for key, meaning in POSITION_MEANINGS.items():
        position[key] = _v(0.0 if key != "has_position" else False, meaning)

    # ATR 先计算（不依赖 state 文件）
    position["atr_14"] = _v(_calc_atr(code), POSITION_MEANINGS["atr_14"])

    if not state_file.exists():
        return {
            "code": code,
            "plan_type": plan_type,
            "account_summary": account,
            "position": position,
            "note": _v("状态文件不存在，请先启动模拟盘/实盘引擎", "提示信息"),
        }

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        # state.capital = 剩余现金, state.initial_capital = 初始本金
        initial_capital = float(state.get("initial_capital", 0) or 0)
        remaining_cash = float(state.get("capital", 0) or 0)
        account["total_capital"] = _v(initial_capital, ACCOUNT_MEANINGS["total_capital"])

        # 遍历所有持仓，计算持仓市值，同时查找指定股票
        all_positions = state.get("positions", []) or []
        total_mv = 0.0
        for p in all_positions:
            mv = float(p.get("market_value", 0) or 0)
            total_mv += mv

            # 查找指定股票
            if p.get("code", "") == code:
                vol = int(p.get("volume", 0) or 0)
                cost = float(p.get("cost", 0) or 0)
                cur_price = float(p.get("cur_price", 0) or 0)
                pnl_pct = float(p.get("pnl_pct", 0) or 0)
                pnl_amt = float(p.get("pnl", 0) or 0)
                ratio = (mv / initial_capital * 100) if initial_capital > 0 else 0.0
                position["has_position"] = _v(vol > 0, POSITION_MEANINGS["has_position"])
                position["volume"] = _v(vol, POSITION_MEANINGS["volume"])
                position["cost"] = _v(round(cost, 4), POSITION_MEANINGS["cost"])
                position["cur_price"] = _v(round(cur_price, 4), POSITION_MEANINGS["cur_price"])
                position["market_value"] = _v(round(mv, 2), POSITION_MEANINGS["market_value"])
                position["pnl"] = _v(round(pnl_amt, 2), POSITION_MEANINGS["pnl"])
                position["pnl_pct"] = _v(round(pnl_pct, 4), POSITION_MEANINGS["pnl_pct"])
                position["position_ratio"] = _v(round(ratio, 2), POSITION_MEANINGS["position_ratio"])

        # 账户整体数据
        # total_value = 剩余现金 + 持仓市值（这才是真正的总资产）
        total_value = remaining_cash + total_mv
        account["total_value"] = _v(round(total_value, 2), ACCOUNT_MEANINGS["total_value"])
        # total_pnl = 总资产 - 初始本金（这才是真正的总盈亏，包含已实现和未实现）
        account["total_pnl"] = _v(round(total_value - initial_capital, 2), ACCOUNT_MEANINGS["total_pnl"])
        account["total_market_value"] = _v(round(total_mv, 2), ACCOUNT_MEANINGS["total_market_value"])
        # 可用资金 = 状态文件中的剩余现金（引擎实时维护）
        account["available_capital"] = _v(round(remaining_cash, 2), ACCOUNT_MEANINGS["available_capital"])

    except Exception:
        pass

    return {
        "code": code,
        "plan_type": plan_type,
        "account_summary": account,
        "position": position,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "请提供股票代码"}, ensure_ascii=False))
        sys.exit(1)
    code = sys.argv[1].strip()
    plan_type = sys.argv[2].strip() if len(sys.argv) > 2 else "sim"
    result = query_position(code, plan_type)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()