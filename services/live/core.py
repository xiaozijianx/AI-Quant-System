# -*- coding: utf-8 -*-
"""routes/live.py 的非端点实现层 (Stage 2 迁移, 逻辑逐字不变).

由 services/live/core.py 承载全部业务实现; 路由层(routes/live.py)只保留端点绑定。
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

import yaml as _yaml   # 读写 binding_source.yaml / execution_mode 用

from lib.paths import (
    setup_sys_path,
    OUTPUTS_LIVE_STATE,
    OUTPUTS_DIR,
    PROJECT_ROOT,
    CONFIG_DIR,
)

from lib.live_simulator import (
    SIM_RUNNER,
    REAL_RUNNER,
    load_strategy_config,
    save_strategy_config,
    load_mock_config,
    merge_watch_codes,
    load_watch_pool,
    save_watch_pool,
)
from lib.strategy_registry import list_strategies
from lib.stock_utils import get_stock_info, normalize_code

setup_sys_path()


# 实盘状态文件路径
OUTPUTS_LIVE_STATE_REAL = OUTPUTS_DIR / "live_state_real.json"

# 配置文件路径 (基于 PROJECT_ROOT, 不依赖 CWD)
WATCH_POOL_FILE = str(CONFIG_DIR / "watch_pool.yaml")
WATCH_POOL_REAL_FILE = str(CONFIG_DIR / "watch_pool_real.yaml")
STRATEGIES_FILE = str(CONFIG_DIR / "strategies.yaml")
STRATEGIES_REAL_FILE = str(CONFIG_DIR / "strategies_real.yaml")
MOCK_POSITIONS_FILE = str(CONFIG_DIR / "mock_positions.yaml")
MOCK_POSITIONS_REAL_FILE = str(CONFIG_DIR / "mock_positions_real.yaml")


OUTPUTS_LIVE_STATE_REAL = OUTPUTS_DIR / "live_state_real.json"

WATCH_POOL_FILE = str(CONFIG_DIR / "watch_pool.yaml")
WATCH_POOL_REAL_FILE = str(CONFIG_DIR / "watch_pool_real.yaml")
STRATEGIES_FILE = str(CONFIG_DIR / "strategies.yaml")
STRATEGIES_REAL_FILE = str(CONFIG_DIR / "strategies_real.yaml")
MOCK_POSITIONS_FILE = str(CONFIG_DIR / "mock_positions.yaml")
MOCK_POSITIONS_REAL_FILE = str(CONFIG_DIR / "mock_positions_real.yaml")

EXECUTION_MODE_FILE = PROJECT_ROOT / "config" / "execution_mode.yaml"
EXECUTION_MODE_FILE_REAL = PROJECT_ROOT / "config" / "execution_mode_real.yaml"

def _load_execution_modes(file_path=None) -> Dict[str, str]:
    """读取执行方式 yaml, 返回 {code: mode}"""
    path = Path(file_path) if file_path else EXECUTION_MODE_FILE
    if not path.exists():
        return {}
    try:
        data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        modes = data.get("modes") or {}
        return {normalize_code(str(k)): str(v).strip() for k, v in modes.items()
                if str(v).strip() in ("plan", "strategy")}
    except Exception:
        return {}

def _save_execution_modes(modes: Dict[str, str], file_path=None) -> None:
    """写执行方式 yaml"""
    path = Path(file_path) if file_path else EXECUTION_MODE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {normalize_code(str(k)): str(v).strip() for k, v in (modes or {}).items()
               if str(v).strip() in ("plan", "strategy")}
    text = _yaml.safe_dump({"modes": cleaned}, allow_unicode=True, sort_keys=True)
    path.write_text(text, encoding="utf-8")

def _exec_mode_file_from_strategy(strategy_file: str) -> Path:
    """从策略文件路径推导执行方式文件路径 (sim/real 独立)"""
    return EXECUTION_MODE_FILE_REAL if "real" in str(strategy_file).lower() else EXECUTION_MODE_FILE

def _sync_binding_on_mode(em_file: Path, code: str, mode: str) -> None:
    """根据执行方式同步策略绑定表(per_stock), 保证两表一致:
    - strategy 模式由 bind 接口负责写入绑定, 这里不主动处理
    - plan 模式或清除(候选)时, 该股票不允许有策略绑定, 从 per_stock 移除
    """
    if mode == "strategy":
        return
    real = "real" in str(em_file).lower()
    st_file = STRATEGIES_REAL_FILE if real else STRATEGIES_FILE
    cfg = load_strategy_config(strategy_file=st_file)
    per = dict(cfg.get("per_stock") or {})
    if code not in per:
        return
    per.pop(code, None)
    default = cfg.get("default", "macd_5min")
    valid_names = {s["name"] for s in list_strategies()}
    if default not in valid_names:
        default = "macd_5min"
    save_strategy_config(default, per, strategy_file=st_file)
    runner = REAL_RUNNER if real else SIM_RUNNER
    try:
        runner.apply_strategy_config(default=default, per_stock=per)
    except Exception:
        pass

def _empty_state():
    return {
        "trading_status": "UNKNOWN", "capital": 0, "initial_capital": 0,
        "day_start_assets": 0, "positions": [],
        "today_pnl": 0, "today_pnl_pct": 0,
        "events": [], "signals": [], "orders": [], "pnl_history": [],
        "control": {"pause_buying": False, "force_clear_all": False,
                    "force_sell_codes": [], "max_daily_loss": -0.02,
                    "dry_run": True},
        "health": {"miniqmt_connected": False, "last_heartbeat": None, "errors_24h": 0},
    }

def _load_state():
    """读模拟盘 state 文件"""
    if not OUTPUTS_LIVE_STATE.exists():
        return _empty_state()
    try:
        return json.loads(OUTPUTS_LIVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()

def _save_state(state: dict):
    """写模拟盘 state 文件"""
    state["_updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = OUTPUTS_LIVE_STATE.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, OUTPUTS_LIVE_STATE)

def _load_state_real():
    """读实盘 state 文件"""
    if not OUTPUTS_LIVE_STATE_REAL.exists():
        return _empty_state()
    try:
        return json.loads(OUTPUTS_LIVE_STATE_REAL.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()

def _save_state_real(state: dict):
    """写实盘 state 文件"""
    state["_updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = OUTPUTS_LIVE_STATE_REAL.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, OUTPUTS_LIVE_STATE_REAL)

def _append_event(state: dict, level: str, title: str, source: str = "ceo_console") -> None:
    """往 state.events 追加一条带级别的事件（告警四级分层，供前端徽章用）"""
    ev = {
        "ts":     datetime.now().isoformat(timespec="seconds"),
        "level":  level,
        "title":  title,
        "source": source,
    }
    state.setdefault("events", []).append(ev)
    state["events"] = state["events"][-200:]

_CONTROL_LEVEL = {
    "force_clear_all": "CRITICAL",
    "pause_buying":    "WARN",
    "max_daily_loss":  "INFO",
    "dry_run":         "INFO",
}
_STATUS_LEVEL = {"HALTED": "CRITICAL", "PAUSED": "WARN", "RUNNING": "INFO"}

def _control_impl(payload: dict, state_loader, state_saver):
    """控制字段写入的通用实现"""
    field = payload.get("field")
    value = payload.get("value")
    if not field:
        return {"ok": False, "message": "field 不能为空"}
    s = state_loader()
    s.setdefault("control", {})[field] = value
    level = _CONTROL_LEVEL.get(field, "INFO")
    _append_event(s, level, f"control.{field} = {value}")
    state_saver(s)
    # 一键清仓时给出交易时段提示
    msg = f"control.{field} = {value}"
    if field == "force_clear_all" and value:
        from lib.live_simulator import is_a_share_trading_hour
        if is_a_share_trading_hour():
            msg = "一键清仓已触发，下一轮盘中循环平掉全部持仓"
        else:
            msg = "一键清仓已加入队列，将在下一个交易时段自动执行"
    return {"ok": True, "message": msg}

def _force_sell_impl(payload: dict, runner, state_loader, state_saver, strategy_file: str):
    """单票强制操作的通用实现"""
    code = _normalize_stock_code(str(payload.get("code", "")))
    if not code:
        return {"ok": False, "message": "code 不能为空"}
    s = state_loader()
    positions = s.get("positions", [])
    pos = next((p for p in positions if p.get("code") == code), None)

    # 有实际持仓: 加入强制卖出队列
    if pos and int(pos.get("volume", 0) or 0) > 0:
        ctrl = s.setdefault("control", {})
        codes = list(ctrl.get("force_sell_codes") or [])
        if code not in codes:
            codes.append(code)
        ctrl["force_sell_codes"] = codes
        _append_event(s, "WARN", f"force_sell 加入 {code}", source="ceo_console")
        state_saver(s)
        from lib.live_simulator import is_a_share_trading_hour
        if is_a_share_trading_hour():
            msg = f"{code} 已加入强制卖出队列，下一轮盘中循环执行"
        else:
            msg = f"{code} 已加入强制卖出队列，将在下一个交易时段自动执行"
        return {"ok": True, "message": msg, "codes": codes}

    # 无实际持仓: 检查是否有执行方式或策略绑定 (待入场), 是则清除
    cancelled = []
    _em_file = _exec_mode_file_from_strategy(strategy_file)
    modes = _load_execution_modes(_em_file)
    if code in modes:
        del modes[code]
        _save_execution_modes(modes, _em_file)
        cancelled.append("交易计划")

    # 同时清除策略绑定 (per_stock)
    st = load_strategy_config(strategy_file=strategy_file)
    per_stock = dict(st.get("per_stock", {}) or {})
    if code in per_stock:
        del per_stock[code]
        save_strategy_config(st.get("default", "macd_1d"), per_stock, strategy_file=strategy_file)
        cancelled.append("策略绑定")

    if cancelled:
        # 取消待入场后把该股退回自选监控池 (sim/real 各自的自选池)
        try:
            wp_file = WATCH_POOL_REAL_FILE if "real" in str(strategy_file).lower() else WATCH_POOL_FILE
            wp = load_watch_pool(watch_pool_file=wp_file)
            wp_codes = list(wp.get("codes") or [])
            if code not in wp_codes:
                wp_codes.append(code)
                save_watch_pool(wp_codes, watch_pool_file=wp_file)
        except Exception:
            pass
        _append_event(s, "INFO", f"取消待入场 {code} ({', '.join(cancelled)})", source="ceo_console")
        state_saver(s)
        return {"ok": True, "message": f"已取消 {code} 的{'、'.join(cancelled)}，退回自选监控池"}

    # 完全不在任何地方
    return {"ok": False, "message": f"{code} 不在当前持仓或待入场列表中，无法操作"}

def _stock_bind_impl(payload, source: str):
    """stock bind 的通用实现, source = 'sim' 或 'real'"""
    payload = payload or {}
    code = _normalize_stock_code(str(payload.get("code", "")))
    strategy = str(payload.get("strategy", "")).strip()
    if not code:
        return {"ok": False, "message": "请填写股票代码 (例: 002432.SZ)"}
    if not strategy:
        return {"ok": False, "message": "请选择策略"}

    valid_names = {s["name"] for s in list_strategies()}
    if strategy not in valid_names:
        return {"ok": False, "message": f"未知策略: {strategy}, 有效: {sorted(valid_names)}"}

    # 确定使用的配置文件和 runner
    if source == "real":
        wp_file = WATCH_POOL_REAL_FILE
        st_file = STRATEGIES_REAL_FILE
        runner = REAL_RUNNER
    else:
        wp_file = WATCH_POOL_FILE
        st_file = STRATEGIES_FILE
        runner = SIM_RUNNER

    try:
        if source == "sim":
            # 绑定策略 = 进入待入场, 从自选监控池移除, 保证「自选池」与「策略绑定/持仓」互斥
            wp = load_watch_pool(watch_pool_file=wp_file)
            codes = [c for c in (list(wp.get("codes") or [])) if c != code]
            save_watch_pool(codes, watch_pool_file=wp_file)
        else:
            # source=real: 反向把 code 从 sim watch_pool 拉出来 (兼容旧数据)
            wp_sim = load_watch_pool()
            codes_sim = list(wp_sim.get("codes") or [])
            if code in codes_sim:
                codes_sim = [c for c in codes_sim if c != code]
                save_watch_pool(codes_sim)

            # 绑定 real 策略 = 进入 real 待入场, 从 real 自选池移除 (互斥)
            wp = load_watch_pool(watch_pool_file=wp_file)
            codes = [c for c in (list(wp.get("codes") or [])) if c != code]
            save_watch_pool(codes, watch_pool_file=wp_file)

        cfg = load_strategy_config(strategy_file=st_file)
        per = dict(cfg.get("per_stock") or {})
        per[code] = strategy
        default = cfg.get("default", "macd_5min")
        if default not in valid_names:
            default = "macd_5min"

        msg = runner.apply_strategy_config(default=default, per_stock=per)
        _set_binding_source(code, source)
        # 绑定策略时视为 strategy 模式 (sim/real 独立文件)
        _em_file = _exec_mode_file_from_strategy(st_file)
        modes = _load_execution_modes(_em_file)
        modes[code] = "strategy"
        _save_execution_modes(modes, _em_file)
        return {
            "ok": True,
            "message": f"已添加 {code} ({source}), 策略: {strategy}。{msg}",
            "codes": codes,
            "per_stock": per,
            "default": default,
            "source": source,
            "execution_modes": modes,
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}

def _stock_unbind_impl(payload, runner, watch_pool_file: str, strategy_file: str):
    """stock unbind 的通用实现"""
    payload = payload or {}
    code = _normalize_stock_code(str(payload.get("code", "")))
    if not code:
        return {"ok": False, "message": "请填写股票代码"}

    actions = []
    try:
        wp = load_watch_pool(watch_pool_file=watch_pool_file)
        codes = list(wp.get("codes") or [])
        if code in codes:
            codes = [c for c in codes if c != code]
            save_watch_pool(codes, watch_pool_file=watch_pool_file)
            actions.append(f"已从 watch_pool 移除")

        cfg = load_strategy_config(strategy_file=strategy_file)
        per = dict(cfg.get("per_stock") or {})
        if code in per:
            per.pop(code, None)
            actions.append(f"已解除策略绑定")
        default = cfg.get("default", "macd_5min")
        valid_names = {s["name"] for s in list_strategies()}
        if default not in valid_names:
            default = "macd_5min"
        msg = runner.apply_strategy_config(default=default, per_stock=per)
        _drop_binding_source(code)
        # 解绑时清除执行模式, 让股票回到自选池候选状态 (sim/real 独立文件)
        _em_file = _exec_mode_file_from_strategy(strategy_file)
        modes = _load_execution_modes(_em_file)
        if code in modes:
            modes.pop(code, None)
            _save_execution_modes(modes, _em_file)

        if not actions:
            return {"ok": True,
                    "message": f"{code} 本来就没绑策略 / 不在 watch_pool, 无需操作",
                    "codes": codes, "per_stock": per, "execution_modes": modes}

        return {
            "ok": True,
            "message": f"{code} {' + '.join(actions)}; 引擎已热加载, 不会再对该股出信号. {msg}",
            "codes": codes,
            "per_stock": per,
            "default": default,
            "execution_modes": modes,
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}

def _watch_merge_impl(ui: str, runner, watch_pool_file: str, strategy_file: str, state_loader):
    """watch_merge 的通用实现: 监控列表 = 自选池 + 实时持仓 + 待入场 + 页面输入 + 策略"""
    ui_codes = [normalize_code(c.strip()) for c in (ui or "").split(",") if c.strip()]
    watch_pool_codes = load_watch_pool(watch_pool_file=watch_pool_file).get("codes", [])
    s = state_loader()
    positions_codes = {normalize_code(p.get("code", "")) for p in s.get("positions", [])}
    strategy_codes = {normalize_code(c) for c in (load_strategy_config(strategy_file=strategy_file).get("per_stock", {}) or {})}
    _em_file = _exec_mode_file_from_strategy(strategy_file)
    execution_modes = _load_execution_modes(_em_file)
    trading_codes = positions_codes | strategy_codes | {c for c, m in execution_modes.items() if m in ("plan", "strategy")}
    # 监控列表 = 自选池 + 实时持仓 + 待入场(plan/strategy) + 页面输入 + 策略代码 (去重)
    # 实时持仓以 live_state 为准, 不掺 mock_positions 初始配置
    position_seed = sorted(positions_codes)
    merged = []
    seen = set()

    def _push(c: str) -> None:
        c = normalize_code((c or "").strip())
        if c and c not in seen:
            seen.add(c)
            merged.append(c)

    for c in watch_pool_codes:
        _push(c)
    for c in position_seed:
        _push(c)
    for c in sorted(trading_codes):
        _push(c)
    for c in ui_codes:
        _push(c)
    return {
        "merged": merged,
        "binding_source": _resolve_binding_sources(merged),
        "execution_modes": execution_modes,
        "trading_codes": sorted(trading_codes),
        "sources": {
            "ui_extra":    ui_codes,
            "positions":   sorted(positions_codes),
            "watch_pool":  watch_pool_codes,
            "strategy_keys": sorted(strategy_codes),
        },
    }

BINDING_SOURCE_FILE = PROJECT_ROOT / "config" / "binding_source.yaml"

def _load_binding_sources() -> Dict[str, str]:
    if not BINDING_SOURCE_FILE.exists():
        return {}
    try:
        data = _yaml.safe_load(BINDING_SOURCE_FILE.read_text(encoding="utf-8")) or {}
        sources = data.get("sources") or {}
        return {normalize_code(str(k)): str(v) for k, v in sources.items() if v in ("sim", "real")}
    except Exception:
        return {}

def _save_binding_sources(sources: Dict[str, str]):
    BINDING_SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {normalize_code(str(k)): str(v) for k, v in (sources or {}).items() if v in ("sim", "real")}
    text = _yaml.safe_dump({"sources": cleaned}, allow_unicode=True, sort_keys=True)
    BINDING_SOURCE_FILE.write_text(text, encoding="utf-8")

def _set_binding_source(code: str, source: str):
    """更新单只股票的 source; source 必须是 'sim' / 'real'"""
    if source not in ("sim", "real"):
        return
    data = _load_binding_sources()
    data[normalize_code(code)] = source
    _save_binding_sources(data)

def _drop_binding_source(code: str):
    data = _load_binding_sources()
    norm = normalize_code(code)
    if norm in data:
        data.pop(norm, None)
        _save_binding_sources(data)

def _resolve_binding_sources(merged: list) -> Dict[str, str]:
    """给 mergedList 每个 code 推断 source:
       - binding_source.yaml 里显式记录过的 -> 用记录
       - 在 sim 实时持仓 / sim watch_pool / sim ui 里出现的 -> sim
       - 在 real 持仓 / real watch_pool 里出现的 -> real
       - 都不在 -> sim (默认)
    """
    explicit = _load_binding_sources()
    # sim 仓库
    s = _load_state()
    sim_pos_codes = {normalize_code(p.get("code")) for p in s.get("positions", []) if p.get("code")}
    sim_watch_codes = set(load_watch_pool().get("codes") or [])
    sim_pool = sim_pos_codes | sim_watch_codes
    # real 仓库
    rs = _load_state_real()
    real_pos_codes = {normalize_code(p.get("code")) for p in rs.get("positions", []) if p.get("code")}
    real_watch_codes = set(load_watch_pool(watch_pool_file=WATCH_POOL_REAL_FILE).get("codes") or [])
    real_pool = real_pos_codes | real_watch_codes

    out: Dict[str, str] = {}
    for c in merged:
        if c in explicit:
            out[c] = explicit[c]
        elif c in real_pool and c not in sim_pool:
            out[c] = "real"
        elif c in sim_pool:
            out[c] = "sim"
        else:
            out[c] = "sim"
    return out

def _execution_mode_set_impl(payload: Optional[Dict[str, Any]], file_path: Path):
    """执行方式设置的通用实现 -- 同时维护策略绑定表的一致性:
    执行方式为 plan 或清除时, 该股票不允许带策略绑定(per_stock 同步移除),
    保证「plan 无绑定 / 候选无绑定」的模型一致 """
    payload = payload or {}
    code = _normalize_stock_code(str(payload.get("code", "")))
    mode = str(payload.get("mode", "")).strip().lower()
    if not code:
        return {"ok": False, "message": "code 不能为空"}
    modes = _load_execution_modes(file_path)
    if mode in ("plan", "strategy"):
        modes[code] = mode
        msg = f"{code} 已设为 {mode} 模式"
    else:
        modes.pop(code, None)
        msg = f"{code} 已清除执行模式"
    _save_execution_modes(modes, file_path)
    # 同步策略绑定表: plan/清除 时移除 per_stock 中的绑定
    _sync_binding_on_mode(file_path, code, mode)
    return {"ok": True, "message": msg, "modes": modes}

def _watch_quote_map(codes: List[str]) -> dict:
    """批量拉 watch_pool 代码的最新日 K 行情"""
    if not codes:
        return {}
    try:
        from lib.backtest_data import load_daily_kline
    except Exception:
        return {}
    from datetime import date, timedelta
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
    out = {}
    for code in codes:
        try:
            df = load_daily_kline(code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                continue
            row = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else row
            close = float(row["close"])
            pre_close = float(prev["close"])
            high = float(row.get("high", close))
            low = float(row.get("low", close))
            volume = float(row.get("volume", 0))
            amount = close * volume
            change_pct = (close / pre_close - 1) if pre_close > 0 else 0.0
            change_amt = close - pre_close
            amplitude = (high - low) / pre_close if pre_close > 0 else 0.0
            out[code] = {
                "close": round(close, 4),
                "pre_close": round(pre_close, 4),
                "change_pct": round(change_pct * 100, 2),
                "change_amt": round(change_amt, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "volume": round(volume, 2),
                "amount": round(amount, 4),
                "amplitude": round(amplitude * 100, 2),
            }
        except Exception:
            continue
    return out

def _normalize_stock_code(raw: str) -> str:
    """标准化股票代码: 去空格、大写, 6 位裸代码自动补齐交易所后缀"""
    return normalize_code(raw)

_REAL_TRADER = None
_REAL_CACHE: Dict[str, Any] = {"asset": {}, "positions": [], "orders": [],
                                "ts": 0.0, "error": None}
_REAL_CACHE_TTL = 5.0   # 秒

_ORDER_STATUS_MAP = {
    48: "未知",   49: "未报",   50: "待报",   51: "已报",
    52: "已报待撤", 53: "部成待撤", 54: "部撤",   55: "已撤",
    56: "部成",   57: "已成",   58: "废单",
}
_ORDER_PENDING_STATUS = {49, 50, 51, 52, 53}

def _query_real_orders_dict(trader) -> list:
    """直接走底层 _trader.query_stock_orders, 转 dict"""
    try:
        raw = trader._trader.query_stock_orders(trader._account)
    except Exception:
        return []
    if not raw:
        return []
    out = []
    for o in raw:
        side_code = getattr(o, "order_type", 0)
        status_code = getattr(o, "order_status", 0)
        out.append({
            "order_id":      getattr(o, "order_id", 0),
            "stock_code":    getattr(o, "stock_code", ""),
            "side":          "buy" if side_code == 23 else ("sell" if side_code == 24 else f"type_{side_code}"),
            "order_volume":  getattr(o, "order_volume", 0),
            "traded_volume": getattr(o, "traded_volume", 0),
            "price":         float(getattr(o, "price", 0) or 0),
            "order_status":  status_code,
            "status_text":   _ORDER_STATUS_MAP.get(status_code, f"未知({status_code})"),
            "cancelable":    status_code in _ORDER_PENDING_STATUS,
            "order_time":    getattr(o, "order_time", 0),
            "strategy_name": getattr(o, "strategy_name", ""),
            "order_remark":  getattr(o, "order_remark", ""),
        })
    return out

def _get_real_trader():
    """懒加载 trader 实例; 失败时抛异常 (调用方负责捕获)"""
    global _REAL_TRADER
    if _REAL_TRADER is not None:
        return _REAL_TRADER

    qmt_path = os.environ.get("QMT_PATH", "").strip()
    account_id = os.environ.get("ACCOUNT_ID", "").strip()
    if not qmt_path or not account_id:
        raise RuntimeError("未配置 QMT_PATH / ACCOUNT_ID, 请在 .env 中设置后重启 app")

    setup_sys_path()
    from miniqmt_trader_v2 import MiniQMTTraderV2  # type: ignore
    trader = MiniQMTTraderV2(
        qmt_path=qmt_path,
        account_id=account_id,
        enable_heartbeat=False,
        enable_reconnect=False,
    )
    trader.connect()
    _REAL_TRADER = trader
    return trader

_APPROVALS_FILE = OUTPUTS_DIR / "live_approvals.json"
_APPROVAL_TTL_SEC = 300   # 5 分钟

def _signal_id(sig: dict) -> str:
    """根据信号生成稳定 id (ts + code + side); 同一信号在状态文件里唯一"""
    return f"{sig.get('ts', '')}|{sig.get('code', '')}|{sig.get('side', '')}"

def _load_approvals() -> Dict[str, Any]:
    if not _APPROVALS_FILE.exists():
        return {}
    try:
        return json.loads(_APPROVALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_approvals(data: Dict[str, Any]):
    _APPROVALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _APPROVALS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _APPROVALS_FILE)

def _calc_suggested_quantity(price: float, capital: float) -> int:
    """与 live_loop.py 风控一致: 单笔 <= 总资金 10%, 100 股一手, 不足按 100 试探"""
    if price <= 0:
        return 100
    max_amount = (capital or 0) * 0.10
    qty = int(max_amount / price / 100) * 100
    return qty if qty > 0 else 100

def _signal_age_sec(ts: str) -> float:
    try:
        t = datetime.fromisoformat(ts)
    except Exception:
        return 0.0
    return (datetime.now() - t).total_seconds()

def _find_signal_by_id(sid: str) -> Optional[dict]:
    # 先查实盘 state
    real_state = _load_state_real()
    for sig in (real_state.get("signals") or []):
        if _signal_id(sig) == sid:
            return sig
    # 再查模拟盘 state
    sim_state = _load_state()
    for sig in (sim_state.get("signals") or []):
        if _signal_id(sig) == sid:
            return sig
    return None

