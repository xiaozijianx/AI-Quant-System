# -*- coding: utf-8 -*-
"""routes/review.py 的非端点实现层 (Stage 2 迁移, 逻辑逐字不变).

实盘 NAV 历史持久化 / Walk-Forward 策略元数据与参数解析等业务实现收编至此;
路由层(routes/review.py)只保留端点绑定。
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

from lib.paths import (
    setup_sys_path,
    OUTPUTS_DIR,
    OUTPUTS_LIVE_STATE,
    OUTPUTS_EVOLVE_REGISTRY,
    OUTPUTS_REAL_PNL,
)

setup_sys_path()
REAL_PNL_HISTORY_PATH: Path = OUTPUTS_REAL_PNL

def _load_real_pnl_history() -> dict:
    if not REAL_PNL_HISTORY_PATH.exists():
        return {"baseline_total_asset": None, "history": []}
    try:
        return json.loads(REAL_PNL_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"baseline_total_asset": None, "history": []}

def _save_real_pnl_history(data: dict) -> None:
    REAL_PNL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REAL_PNL_HISTORY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def _record_real_pnl_snapshot(force: bool = False) -> dict:
    """拉一次 real 账户 total_asset, 写入 real_pnl_history.json (每日最多一条)

    Args:
        force: True 强制写, 即使今天已有记录 (覆盖); False 当日已有则跳过

    Returns:
        {"ok": bool, "message": str, "baseline": float|None,
         "today_total": float|None, "today_pct": float|None,
         "data_points": int}
    """
    import os as _os
    qmt_path = _os.getenv("QMT_PATH")
    account_id = _os.getenv("ACCOUNT_ID")
    if not qmt_path or not account_id:
        return {"ok": False, "message": "QMT_PATH / ACCOUNT_ID 未配置 (.env)"}

    try:
        setup_sys_path()
        from miniqmt_trader_v2 import MiniQMTTraderV2  # type: ignore
        trader = MiniQMTTraderV2(
            qmt_path=qmt_path, account_id=account_id,
            enable_heartbeat=False, enable_reconnect=False,
        )
        trader.connect()
        asset = trader.query_asset() or {}
    except Exception as e:
        return {"ok": False, "message": f"miniQMT 连接/查询失败: {type(e).__name__}: {e}"}

    total_asset = float(asset.get("total_asset") or 0)
    if total_asset <= 0:
        return {"ok": False, "message": f"total_asset = {total_asset}, 实盘账户为空或未连接"}

    data = _load_real_pnl_history()
    history = data.get("history") or []

    today = datetime.now().strftime("%Y-%m-%d")
    today_records = [h for h in history if str(h.get("ts", ""))[:10] == today]

    # baseline: 第一次记录时锁定
    if data.get("baseline_total_asset") is None:
        data["baseline_total_asset"] = total_asset
        baseline = total_asset
    else:
        baseline = float(data["baseline_total_asset"])

    cum_pct = (total_asset - baseline) / baseline if baseline > 0 else 0.0
    new_record = {
        "ts": datetime.now().strftime("%Y-%m-%dT15:00:00"),
        "total_asset": round(total_asset, 2),
        "cum_pct": round(cum_pct, 6),
    }

    if today_records and not force:
        # 当日已有记录, 不重复写
        msg = f"今天 {today} 已有快照, 跳过 (用 force=true 覆盖)"
    else:
        if today_records and force:
            history = [h for h in history if str(h.get("ts", ""))[:10] != today]
        history.append(new_record)
        history.sort(key=lambda x: str(x.get("ts", "")))
        data["history"] = history
        _save_real_pnl_history(data)
        msg = (f"已记录 {today} 快照: total_asset={total_asset:.2f}, "
               f"baseline={baseline:.2f}, cum={cum_pct*100:+.2f}%")

    return {
        "ok": True,
        "message": msg,
        "baseline": round(baseline, 2),
        "today_total": round(total_asset, 2),
        "today_pct": round(cum_pct, 6),
        "data_points": len(data.get("history") or []),
    }

_WF_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "double_ma": {
        "fn_name":     "double_ma_strategy",
        "label":       "双均线 (趋势跟踪)",
        "description": "短均线上穿长均线买入, 下穿卖出. 适合趋势行情, 横盘易过拟合.",
        "param_cols":  ["ma_short", "ma_long"],
        "defaults": [
            {"ma_short": 5,  "ma_long": 20},
            {"ma_short": 5,  "ma_long": 30},
            {"ma_short": 10, "ma_long": 30},
            {"ma_short": 10, "ma_long": 60},
            {"ma_short": 20, "ma_long": 60},
            {"ma_short": 20, "ma_long": 120},
        ],
        "bounds": {
            "ma_short": {"type": "int", "min": 2, "max": 200},
            "ma_long":  {"type": "int", "min": 3, "max": 500},
        },
        "extra_check": "ma_short < ma_long",
    },
    "bollinger": {
        "fn_name":     "bollinger_reversion_strategy",
        "label":       "布林带反转 (均值回归)",
        "description": "收盘触下轨买入 (超卖), 触上轨卖出 (超买). 适合震荡, 单边趋势会被反向打脸.",
        "param_cols":  ["window", "std_n"],
        "defaults": [
            {"window": 10, "std_n": 1.5},
            {"window": 20, "std_n": 2.0},
            {"window": 20, "std_n": 2.5},
            {"window": 30, "std_n": 2.0},
            {"window": 50, "std_n": 2.0},
        ],
        "bounds": {
            "window": {"type": "int",   "min": 5,   "max": 200},
            "std_n":  {"type": "float", "min": 0.5, "max": 5.0},
        },
    },
    "rsi": {
        "fn_name":     "rsi_reversion_strategy",
        "label":       "RSI 反转 (均值回归)",
        "description": "RSI 跌破 oversold 买入, 涨破 overbought 卖出. 经典超买超卖, 强趋势失效.",
        "param_cols":  ["rsi_period", "oversold", "overbought"],
        "defaults": [
            {"rsi_period": 6,  "oversold": 20, "overbought": 80},
            {"rsi_period": 14, "oversold": 30, "overbought": 70},
            {"rsi_period": 14, "oversold": 25, "overbought": 75},
            {"rsi_period": 21, "oversold": 30, "overbought": 70},
        ],
        "bounds": {
            "rsi_period": {"type": "int",   "min": 2,  "max": 100},
            "oversold":   {"type": "float", "min": 5,  "max": 50},
            "overbought": {"type": "float", "min": 50, "max": 95},
        },
        "extra_check": "oversold < overbought",
    },
    "donchian": {
        "fn_name":     "donchian_breakout_strategy",
        "label":       "唐奇安通道突破 (海龟)",
        "description": "突破 N 日新高买入, 跌破 M 日新低卖出 (M <= N). 趋势好, 横盘连续假突破.",
        "param_cols":  ["entry_lookback", "exit_lookback"],
        "defaults": [
            {"entry_lookback": 10, "exit_lookback": 5},
            {"entry_lookback": 20, "exit_lookback": 10},
            {"entry_lookback": 20, "exit_lookback": 5},
            {"entry_lookback": 55, "exit_lookback": 20},
        ],
        "bounds": {
            "entry_lookback": {"type": "int", "min": 3, "max": 250},
            "exit_lookback":  {"type": "int", "min": 2, "max": 250},
        },
        "extra_check": "exit_lookback <= entry_lookback",
    },
    "ml_prob": {
        "fn_name":     "ml_prob_strategy",
        "label":       "ML 概率因子 (XGBoost)",
        "description": "50+ 技术因子 + XGBoost 滚动训练, 涨概率 > buy_th 买 / < sell_th 卖. 比简单技术策略 OOS 衰减小.",
        "param_cols":  ["train_days", "retrain_interval", "buy_th", "sell_th"],
        "defaults": [
            {"train_days": 80,  "retrain_interval": 20, "buy_th": 0.55, "sell_th": 0.45},
            {"train_days": 120, "retrain_interval": 20, "buy_th": 0.60, "sell_th": 0.40},
            {"train_days": 120, "retrain_interval": 40, "buy_th": 0.55, "sell_th": 0.45},
            {"train_days": 180, "retrain_interval": 20, "buy_th": 0.60, "sell_th": 0.40},
        ],
        "bounds": {
            "train_days":       {"type": "int",   "min": 40,   "max": 500},
            "retrain_interval": {"type": "int",   "min": 1,    "max": 120},
            "buy_th":           {"type": "float", "min": 0.50, "max": 0.95},
            "sell_th":          {"type": "float", "min": 0.05, "max": 0.50},
        },
        "extra_check": "sell_th < buy_th",
        # ml_prob 内部含滚动训练: 评估阶段需要回看 ~200 行做 warmup, 否则 test_window 内
        # 一个预测都跑不出来, OOS 会被错误地算成 0. (200 行 = 最大 train_days 180 + buffer)
        "oos_warmup": 200,
    },
}

def _wf_strategy_meta(strategy: str) -> Dict[str, Any]:
    """取策略 meta, 未知策略抛 KeyError"""
    if strategy not in _WF_STRATEGIES:
        raise KeyError(strategy)
    return _WF_STRATEGIES[strategy]

def _wf_param_grid_to_text(strategy: str, grid: List[dict]) -> str:
    """把 param_grid 列表序列化成 textarea 文本 (每行逗号分隔, 顺序按 param_cols)"""
    cols = _wf_strategy_meta(strategy)["param_cols"]
    lines = []
    for item in grid:
        vals = [item.get(c) for c in cols]
        lines.append(",".join(str(v) for v in vals))
    return "\n".join(lines)

def _coerce_param_value(col: str, raw_v: str, bounds: Dict[str, Any]) -> tuple:
    """按 bounds[col] 把字符串转成 int/float, 并校验范围. 返回 (value, err_msg)"""
    spec = bounds.get(col, {"type": "float"})
    typ = spec.get("type", "float")
    try:
        v = int(raw_v) if typ == "int" else float(raw_v)
    except ValueError:
        return None, f"{col} 应为 {typ} 类型, 当前 '{raw_v}'"
    if "min" in spec and v < spec["min"]:
        return None, f"{col}={v} 小于下限 {spec['min']}"
    if "max" in spec and v > spec["max"]:
        return None, f"{col}={v} 大于上限 {spec['max']}"
    return v, ""

def _check_extra(strategy: str, item: Dict[str, Any]) -> str:
    """跨字段约束 (e.g. ma_short < ma_long). 通过返回 '', 否则返回错误文本."""
    rule = _wf_strategy_meta(strategy).get("extra_check")
    if not rule:
        return ""
    if rule == "ma_short < ma_long":
        if not (item["ma_short"] < item["ma_long"]):
            return f"需满足 ma_short < ma_long, 当前 ({item['ma_short']},{item['ma_long']})"
    elif rule == "oversold < overbought":
        if not (item["oversold"] < item["overbought"]):
            return f"需满足 oversold < overbought, 当前 ({item['oversold']},{item['overbought']})"
    elif rule == "exit_lookback <= entry_lookback":
        if not (item["exit_lookback"] <= item["entry_lookback"]):
            return f"需满足 exit_lookback <= entry_lookback, 当前 ({item['entry_lookback']},{item['exit_lookback']})"
    elif rule == "sell_th < buy_th":
        if not (item["sell_th"] < item["buy_th"]):
            return f"需满足 sell_th < buy_th, 当前 (buy_th={item['buy_th']}, sell_th={item['sell_th']})"
    return ""

def _parse_wf_param_grid(strategy: str, raw) -> tuple:
    """把前端送来的 param_grid 规范化为 List[dict] (字段顺序按 strategy.param_cols).

    支持两种格式:
        1. 数组对象: [{"ma_short": 5, "ma_long": 20}, ...]
        2. 文本行 (textarea): "5,20\n10,30"  -- 每行用逗号/Tab 分隔, 顺序按 param_cols

    raw 为空/None 时返回该策略的默认 grid.
    返回 (param_grid, error_message); 成功时 error 为空串.
    """
    try:
        meta = _wf_strategy_meta(strategy)
    except KeyError:
        return [], f"未知策略: {strategy}"
    cols = meta["param_cols"]
    bounds = meta.get("bounds", {})

    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return [dict(d) for d in meta["defaults"]], ""

    # 文本格式 (textarea)
    if isinstance(raw, str):
        items = []
        for ln_idx, ln in enumerate(raw.splitlines(), start=1):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = [p.strip() for p in ln.replace("\t", ",").split(",") if p.strip()]
            if len(parts) != len(cols):
                return [], (f"第 {ln_idx} 行字段数 {len(parts)} != {len(cols)} "
                            f"(应为 '{','.join(cols)}'): {ln}")
            item: Dict[str, Any] = {}
            for col, raw_v in zip(cols, parts):
                v, err = _coerce_param_value(col, raw_v, bounds)
                if err:
                    return [], f"第 {ln_idx} 行 {err}"
                item[col] = v
            err = _check_extra(strategy, item)
            if err:
                return [], f"第 {ln_idx} 行 {err}"
            items.append(item)
        if not items:
            return [dict(d) for d in meta["defaults"]], ""
        raw = items

    # 数组对象格式
    if not isinstance(raw, list):
        return [], "param_grid 应为数组或多行文本"
    out = []
    for i, src in enumerate(raw):
        if not isinstance(src, dict):
            return [], f"param_grid[{i}] 不是 dict"
        item: Dict[str, Any] = {}
        for col in cols:
            if col not in src:
                return [], f"param_grid[{i}] 缺少字段 {col}"
            v, err = _coerce_param_value(col, str(src[col]), bounds)
            if err:
                return [], f"param_grid[{i}] {err}"
            item[col] = v
        err = _check_extra(strategy, item)
        if err:
            return [], f"param_grid[{i}] {err}"
        out.append(item)
    if not out:
        return [], "param_grid 不能为空"
    if len(out) > 30:
        return [], f"param_grid 最多 30 组 (当前 {len(out)} 组)"
    return out, ""

