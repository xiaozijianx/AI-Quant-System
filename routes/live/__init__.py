# -*- coding: utf-8 -*-
# 实盘监控路由 -- REST (模拟盘 / 实盘 双引擎)
"""
模拟盘端点 (sim) / 实盘端点 (real) / 向后兼容端点 (委托到 SIM_RUNNER)。
业务实现已下沉 services/live/core.py (Stage 2 路由瘦身), 本文件只保留端点绑定。

向后兼容说明与端点清单见原版 (git HEAD routes/live.py)。
"""
from __future__ import annotations
from datetime import datetime  # noqa: F401  (approvals_approve 内 datetime.now 用)
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

# 引擎单例 re-export (兼容既有 from routes.live import SIM_RUNNER 引用:
# app.py / routes/backtest.py / routes/dragon.py)
from lib.live_simulator import (
    SIM_RUNNER,
    REAL_RUNNER,
    load_strategy_config,
    load_watch_pool,
    save_watch_pool,
    merge_watch_codes,
    load_mock_config,
)
from lib.strategy_registry import list_groups, list_strategies
from lib.stock_utils import get_stock_info

from services.live.core import (
    OUTPUTS_LIVE_STATE_REAL, WATCH_POOL_FILE, WATCH_POOL_REAL_FILE, STRATEGIES_FILE,
    STRATEGIES_REAL_FILE, MOCK_POSITIONS_FILE, MOCK_POSITIONS_REAL_FILE, EXECUTION_MODE_FILE,
    EXECUTION_MODE_FILE_REAL, _load_execution_modes, _save_execution_modes, _exec_mode_file_from_strategy,
    _sync_binding_on_mode, _empty_state, _load_state, _save_state,
    _load_state_real, _save_state_real, _append_event, _CONTROL_LEVEL,
    _STATUS_LEVEL, _control_impl, _force_sell_impl, _stock_bind_impl,
    _stock_unbind_impl, _watch_merge_impl, BINDING_SOURCE_FILE, _load_binding_sources,
    _save_binding_sources, _set_binding_source, _drop_binding_source, _resolve_binding_sources,
    _execution_mode_set_impl, _watch_quote_map, _normalize_stock_code, _REAL_TRADER,
    _REAL_CACHE, _REAL_CACHE_TTL, _ORDER_STATUS_MAP, _ORDER_PENDING_STATUS,
    _query_real_orders_dict, _get_real_trader, _APPROVALS_FILE, _APPROVAL_TTL_SEC,
    _signal_id, _load_approvals, _save_approvals, _calc_suggested_quantity,
    _signal_age_sec, _find_signal_by_id,
)

router = APIRouter()

@router.get("/ping")
def live_ping():
    """健康检查：浏览器打开 /api/live/ping 可确认当前进程已加载 live 路由 (含 stock/bind)"""
    return {"ok": True, "module": "live", "hint": "绑定接口: POST /api/live/stock/bind; sim/real 双引擎就绪"}

@router.get("/state")
def get_state():
    return _load_state()

@router.get("/sim/status")
def sim_status():
    return SIM_RUNNER.status()

@router.get("/sim/state")
def sim_state():
    return _load_state()

@router.post("/sim/start")
def sim_start(payload: dict = Body(...)):
    watch = payload.get("watch_stocks", "")
    if isinstance(watch, list):
        ui_codes = [str(c).strip() for c in watch if str(c).strip()]
    else:
        ui_codes = [c.strip() for c in str(watch or "").split(",") if c.strip()]
    merged = merge_watch_codes(ui_codes)
    if not merged:
        return {
            "ok": False,
            "message": "监控池为空: 请在自选监控池、mock 持仓、策略路由 per_stock 或「额外监控」中至少保留一只股票",
        }
    dry_run = bool(payload.get("dry_run", True))
    cycle_seconds = int(payload.get("cycle_seconds", 60))
    if cycle_seconds < 1:
        cycle_seconds = 60
    msg = SIM_RUNNER.start(watch_stocks=merged, dry_run=dry_run, cycle_seconds=cycle_seconds)
    return {"ok": "OK" in msg, "message": msg}

@router.post("/sim/stop")
def sim_stop(payload: dict = Body({})):
    msg = SIM_RUNNER.stop()
    return {"ok": True, "message": msg}

@router.post("/sim/trial_run")
@router.post("/sim/trial_run/")
def sim_trial_run(payload: Optional[Dict[str, Any]] = Body(None)):
    """非交易时段也强制让引擎跑一次 (按最近一根 K 线生成信号)"""
    return SIM_RUNNER.trial_run()

@router.post("/sim/reset_positions")
def sim_reset_positions(payload: dict = Body({})):
    """重置模拟盘持仓, 同时清空自选监控池 (彻底重来; 后续保存交易计划会按需重新加入自选池)"""
    msg = SIM_RUNNER.reset_positions()
    # 重置时一并清空自选池, 避免残留"计划/持仓已被重置但仍挂在自选池"的股票
    try:
        pool = load_watch_pool(watch_pool_file=WATCH_POOL_FILE)
        codes = list(pool.get("codes") or [])
        if codes:
            save_watch_pool([], watch_pool_file=WATCH_POOL_FILE)
            msg += f" | 已清空自选监控池 {len(codes)} 只"
    except Exception:
        pass
    return {"ok": "OK" in msg, "message": msg}

@router.post("/sim/clear_history")
def sim_clear_history(payload: dict = Body({})):
    """清空 events / signals / orders / pnl_history (持仓不动)"""
    msg = SIM_RUNNER.clear_history()
    return {"ok": "OK" in msg, "message": msg}

@router.get("/sim/strategies/config")
def sim_strategies_config_get():
    """读模拟盘策略配置"""
    return load_strategy_config(strategy_file=STRATEGIES_FILE)

@router.post("/sim/strategies/apply")
def sim_strategies_apply(payload: dict = Body(...)):
    """应用模拟盘策略配置"""
    default = payload.get("default", "macd_5min")
    per_stock = payload.get("per_stock", {}) or {}

    valid_names = {s["name"] for s in list_strategies()}
    invalid = [s for s in [default, *per_stock.values()] if s not in valid_names]
    if invalid:
        return {"ok": False,
                "message": f"未知策略: {invalid}, 有效策略: {sorted(valid_names)}"}

    msg = SIM_RUNNER.apply_strategy_config(default=default, per_stock=per_stock)
    return {"ok": True, "message": msg}

@router.post("/sim/stock/bind")
@router.post("/sim/stock/bind/")
def sim_stock_bind(payload: Optional[Dict[str, Any]] = Body(None)):
    """模拟盘绑定策略 (写 watch_pool.yaml + strategies.yaml)"""
    return _stock_bind_impl(payload, source="sim")

@router.post("/sim/stock/unbind")
@router.post("/sim/stock/unbind/")
def sim_stock_unbind(payload: Optional[Dict[str, Any]] = Body(None)):
    """模拟盘解绑策略"""
    return _stock_unbind_impl(payload, runner=SIM_RUNNER,
                              watch_pool_file=WATCH_POOL_FILE,
                              strategy_file=STRATEGIES_FILE)

@router.get("/sim/watch_merge")
def sim_watch_merge(ui: str = ""):
    """模拟盘合并监控列表"""
    return _watch_merge_impl(ui, runner=SIM_RUNNER,
                             watch_pool_file=WATCH_POOL_FILE,
                             strategy_file=STRATEGIES_FILE,
                             state_loader=_load_state)

@router.post("/sim/force_sell")
def sim_force_sell(payload: dict = Body(...)):
    """模拟盘强制卖出"""
    return _force_sell_impl(payload, runner=SIM_RUNNER,
                            state_loader=_load_state, state_saver=_save_state,
                            strategy_file=STRATEGIES_FILE)

@router.post("/sim/control")
def sim_control(payload: dict = Body(...)):
    """模拟盘运行控制"""
    return _control_impl(payload, state_loader=_load_state, state_saver=_save_state)

@router.get("/real/status")
def real_status():
    return REAL_RUNNER.status()

@router.get("/real/state")
def real_state():
    return _load_state_real()

@router.post("/real/start")
def real_start(payload: dict = Body(...)):
    """启动实盘引擎"""
    watch = payload.get("watch_stocks", "")
    if isinstance(watch, list):
        ui_codes = [str(c).strip() for c in watch if str(c).strip()]
    else:
        ui_codes = [c.strip() for c in str(watch or "").split(",") if c.strip()]
    merged = merge_watch_codes(
        ui_codes,
        watch_pool_codes=load_watch_pool(watch_pool_file=WATCH_POOL_REAL_FILE).get("codes", []),
        strategy_codes=list((load_strategy_config(strategy_file=STRATEGIES_REAL_FILE).get("per_stock") or {}).keys()),
        mock_cfg_file=MOCK_POSITIONS_REAL_FILE,
    )
    if not merged:
        return {
            "ok": False,
            "message": "监控池为空: 请在自选监控池、策略路由 per_stock 中至少保留一只股票",
        }
    cycle_seconds = int(payload.get("cycle_seconds", 60))
    if cycle_seconds < 1:
        cycle_seconds = 60
    msg = REAL_RUNNER.start(watch_stocks=merged, dry_run=False, cycle_seconds=cycle_seconds)
    return {"ok": "OK" in msg, "message": msg}

@router.post("/real/stop")
def real_stop(payload: dict = Body({})):
    msg = REAL_RUNNER.stop()
    return {"ok": True, "message": msg}

@router.post("/real/trial_run")
@router.post("/real/trial_run/")
def real_trial_run(payload: Optional[Dict[str, Any]] = Body(None)):
    """实盘试算"""
    return REAL_RUNNER.trial_run()

@router.post("/real/reset_positions")
def real_reset_positions(payload: dict = Body({})):
    """重置实盘持仓"""
    msg = REAL_RUNNER.reset_positions()
    return {"ok": "OK" in msg, "message": msg}

@router.post("/real/clear_history")
def real_clear_history(payload: dict = Body({})):
    """清空实盘历史"""
    msg = REAL_RUNNER.clear_history()
    return {"ok": "OK" in msg, "message": msg}

@router.get("/real/strategies/config")
def real_strategies_config_get():
    """读实盘策略配置"""
    return load_strategy_config(strategy_file=STRATEGIES_REAL_FILE)

@router.post("/real/strategies/apply")
def real_strategies_apply(payload: dict = Body(...)):
    """应用实盘策略配置"""
    default = payload.get("default", "macd_5min")
    per_stock = payload.get("per_stock", {}) or {}

    valid_names = {s["name"] for s in list_strategies()}
    invalid = [s for s in [default, *per_stock.values()] if s not in valid_names]
    if invalid:
        return {"ok": False,
                "message": f"未知策略: {invalid}, 有效策略: {sorted(valid_names)}"}

    msg = REAL_RUNNER.apply_strategy_config(default=default, per_stock=per_stock)
    return {"ok": True, "message": msg}

@router.post("/real/stock/bind")
@router.post("/real/stock/bind/")
def real_stock_bind(payload: Optional[Dict[str, Any]] = Body(None)):
    """实盘绑定策略 (写 watch_pool_real.yaml + strategies_real.yaml)"""
    return _stock_bind_impl(payload, source="real")

@router.post("/real/stock/unbind")
@router.post("/real/stock/unbind/")
def real_stock_unbind(payload: Optional[Dict[str, Any]] = Body(None)):
    """实盘解绑策略"""
    return _stock_unbind_impl(payload, runner=REAL_RUNNER,
                              watch_pool_file=WATCH_POOL_REAL_FILE,
                              strategy_file=STRATEGIES_REAL_FILE)

@router.get("/real/watch_merge")
def real_watch_merge(ui: str = ""):
    """实盘合并监控列表"""
    return _watch_merge_impl(ui, runner=REAL_RUNNER,
                             watch_pool_file=WATCH_POOL_REAL_FILE,
                             strategy_file=STRATEGIES_REAL_FILE,
                             state_loader=_load_state_real)

@router.post("/real/force_sell")
def real_force_sell(payload: dict = Body(...)):
    """实盘强制卖出"""
    return _force_sell_impl(payload, runner=REAL_RUNNER,
                            state_loader=_load_state_real, state_saver=_save_state_real,
                            strategy_file=STRATEGIES_REAL_FILE)

@router.post("/real/control")
def real_control(payload: dict = Body(...)):
    """实盘运行控制"""
    return _control_impl(payload, state_loader=_load_state_real, state_saver=_save_state_real)

@router.get("/real/watch_pool")
def real_watch_pool_get():
    """读实盘自选池"""
    return load_watch_pool(watch_pool_file=WATCH_POOL_REAL_FILE)

@router.post("/real/watch_pool")
def real_watch_pool_set(payload: Optional[Dict[str, Any]] = Body(None)):
    """写实盘自选池 (watch_pool_real.yaml)"""
    payload = payload or {}
    try:
        raw = payload.get("codes", "")
        if isinstance(raw, list):
            codes = [str(c).strip() for c in raw if str(c).strip()]
        else:
            codes = [
                c.strip()
                for c in str(raw or "").replace("，", ",").replace("\n", ",").split(",")
                if c.strip()
            ]
        codes = [_normalize_stock_code(c) for c in codes]
        save_watch_pool(codes, watch_pool_file=WATCH_POOL_REAL_FILE)
        return {"ok": True, "message": f"[OK] 实盘监控列表已保存, 共 {len(codes)} 只", "codes": codes}
    except Exception as e:
        return {"ok": False, "message": str(e), "codes": []}

@router.get("/real/watch_quotes")
def real_watch_quotes_get(codes: str = ""):
    """返回实盘自选池代码的最新日K行情"""
    if codes:
        code_list = [_normalize_stock_code(c) for c in codes.split(",") if c.strip()]
    else:
        code_list = load_watch_pool(watch_pool_file=WATCH_POOL_REAL_FILE).get("codes", []) or []
    return {"quotes": _watch_quote_map(code_list)}

@router.post("/control")
def control(payload: dict = Body(...)):
    """向后兼容: 模拟盘运行控制"""
    return sim_control(payload)

@router.post("/force_sell")
def force_sell(payload: dict = Body(...)):
    """向后兼容: 模拟盘强制卖出"""
    return sim_force_sell(payload)

@router.post("/status")
def set_status(payload: dict = Body(...)):
    """向后兼容: 修改模拟盘 trading_status"""
    status = payload.get("status")
    if status not in ("RUNNING", "PAUSED", "HALTED"):
        return {"ok": False, "message": "status 必须是 RUNNING/PAUSED/HALTED"}
    s = _load_state()
    s["trading_status"] = status
    level = _STATUS_LEVEL.get(status, "INFO")
    _append_event(s, level, f"trading_status -> {status}")
    _save_state(s)
    return {"ok": True, "message": f"trading_status = {status}"}

@router.get("/strategies/registry")
def strategies_registry():
    """列出所有可注册策略 (按分组)  -- sim/real 共用"""
    return {
        "groups": list_groups(),
        "flat":   list_strategies(),
    }

@router.get("/strategies/config")
def strategies_config_get():
    """向后兼容: 读模拟盘策略配置"""
    return sim_strategies_config_get()

@router.post("/strategies/config")
def strategies_config_set(payload: dict = Body(...)):
    """向后兼容: 应用模拟盘策略配置"""
    return sim_strategies_apply(payload)

@router.get("/watch_merge")
def watch_merge(ui: str = ""):
    """向后兼容: 模拟盘合并监控列表"""
    return sim_watch_merge(ui)

@router.get("/execution_mode")
def execution_mode_get():
    """读取模拟盘执行方式模式表 (向后兼容)"""
    return {"modes": _load_execution_modes()}

@router.post("/execution_mode")
def execution_mode_set(payload: Optional[Dict[str, Any]] = Body(None)):
    """设置/清除模拟盘某只股票的执行方式模式 (向后兼容)"""
    return _execution_mode_set_impl(payload, EXECUTION_MODE_FILE)

@router.get("/sim/execution_mode")
def sim_execution_mode_get():
    """读取模拟盘执行方式模式表"""
    return {"modes": _load_execution_modes(EXECUTION_MODE_FILE)}

@router.post("/sim/execution_mode")
def sim_execution_mode_set(payload: Optional[Dict[str, Any]] = Body(None)):
    """设置/清除模拟盘某只股票的执行方式模式"""
    return _execution_mode_set_impl(payload, EXECUTION_MODE_FILE)

@router.get("/real/execution_mode")
def real_execution_mode_get():
    """读取实盘执行方式模式表"""
    return {"modes": _load_execution_modes(EXECUTION_MODE_FILE_REAL)}

@router.post("/real/execution_mode")
def real_execution_mode_set(payload: Optional[Dict[str, Any]] = Body(None)):
    """设置/清除实盘某只股票的执行方式模式"""
    return _execution_mode_set_impl(payload, EXECUTION_MODE_FILE_REAL)

@router.get("/stock_names")
def stock_names_get(codes: str = ""):
    """批量查询股票名称 -- sim/real 共用"""
    out = {}
    missing = []
    for c in str(codes or "").split(","):
        c = c.strip()
        if not c:
            continue
        try:
            info = get_stock_info(c)
            name = info.get("name", "")
            out[c] = name
            if not name:
                missing.append(c)
        except Exception:
            out[c] = ""
            missing.append(c)

    # fallback 1: 从交易计划表中读 stock_name
    if missing:
        try:
            from lib.trading_plan import _execute_query
            placeholders = ",".join(["%s"] * len(missing))
            rows = _execute_query(
                f"""SELECT stock_code, stock_name
                    FROM trading_plan
                    WHERE stock_code IN ({placeholders})
                    ORDER BY updated_at DESC""",
                tuple(missing)
            )
            for r in rows:
                code = r.get("stock_code")
                name = r.get("stock_name", "")
                if code and name and not out.get(code):
                    out[code] = name
            missing = [c for c in missing if not out.get(c)]
        except Exception:
            pass

    # fallback 2: 用 xtdata 兜底
    if missing:
        try:
            from xtquant import xtdata
            for c in missing:
                try:
                    info = xtdata.get_instrument_detail(c)
                    if info and info.get("InstrumentName"):
                        out[c] = info["InstrumentName"]
                except Exception:
                    pass
        except Exception:
            pass

    return {"names": out}

@router.get("/watch_quotes")
def watch_quotes_get(codes: str = ""):
    """返回指定代码的最新日 K 行情; codes 为空时返回 watch_pool 全部 -- sim/real 共用"""
    if codes:
        code_list = [_normalize_stock_code(c) for c in codes.split(",") if c.strip()]
    else:
        code_list = load_watch_pool().get("codes", []) or []
    return {"quotes": _watch_quote_map(code_list)}

@router.get("/watch_pool")
def watch_pool_get():
    """向后兼容: 读模拟盘 watch_pool"""
    return load_watch_pool()

@router.post("/watch_pool")
def watch_pool_set(payload: Optional[Dict[str, Any]] = Body(None)):
    """向后兼容: 写模拟盘 watch_pool.yaml"""
    payload = payload or {}
    try:
        raw = payload.get("codes", "")
        if isinstance(raw, list):
            codes = [str(c).strip() for c in raw if str(c).strip()]
        else:
            codes = [
                c.strip()
                for c in str(raw or "").replace("，", ",").replace("\n", ",").split(",")
                if c.strip()
            ]
        codes = [_normalize_stock_code(c) for c in codes]
        save_watch_pool(codes)
        return {"ok": True, "message": f"[OK] 监控列表已保存, 共 {len(codes)} 只", "codes": codes}
    except Exception as e:
        return {"ok": False, "message": str(e), "codes": []}

@router.post("/stock/bind")
@router.post("/stock/bind/")
def stock_bind(payload: Optional[Dict[str, Any]] = Body(None)):
    """向后兼容: 添加股票并绑定策略 (默认 sim)"""
    payload = payload or {}
    source = str(payload.get("source", "sim")).strip().lower()
    if source not in ("sim", "real"):
        source = "sim"
    if source == "real":
        return real_stock_bind(payload)
    return sim_stock_bind(payload)

@router.post("/stock/unbind")
@router.post("/stock/unbind/")
def stock_unbind(payload: Optional[Dict[str, Any]] = Body(None)):
    """向后兼容: 解绑策略 (默认 sim)"""
    return sim_stock_unbind(payload)

@router.get("/real_account")
def real_account():
    """实盘视图用: 拉 miniQMT 真实账户 + 持仓 + 当日委托 (5 秒进程级缓存)"""
    import time as _time
    now = _time.time()
    age = now - (_REAL_CACHE.get("ts") or 0)
    if _REAL_CACHE.get("ts") and age < _REAL_CACHE_TTL:
        return {
            "connected": _REAL_CACHE.get("error") is None,
            "error":     _REAL_CACHE.get("error"),
            "asset":     _REAL_CACHE.get("asset") or {},
            "positions": _REAL_CACHE.get("positions") or [],
            "orders":    _REAL_CACHE.get("orders") or [],
            "cached_age_sec": round(age, 2),
        }

    try:
        trader = _get_real_trader()
        asset = trader.query_asset() or {}
        positions = trader.query_positions() or []
        orders = _query_real_orders_dict(trader)
        _REAL_CACHE.update({"asset": asset, "positions": positions,
                            "orders": orders, "ts": now, "error": None})
        return {
            "connected": True, "error": None,
            "asset": asset, "positions": positions, "orders": orders,
            "cached_age_sec": 0.0,
        }
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _REAL_CACHE.update({"asset": {}, "positions": [], "orders": [],
                            "ts": now, "error": err})
        return {
            "connected": False, "error": err,
            "asset": {}, "positions": [], "orders": [],
            "cached_age_sec": 0.0,
        }

@router.post("/real_order/cancel")
def real_order_cancel(payload: Optional[Dict[str, Any]] = Body(None)):
    """撤销 miniQMT 上指定委托"""
    payload = payload or {}
    raw_id = payload.get("order_id")
    try:
        order_id = int(raw_id)
    except (TypeError, ValueError):
        return {"ok": False, "message": f"order_id 必须是整数, 收到: {raw_id!r}"}

    try:
        trader = _get_real_trader()
        result = trader.cancel(order_id)
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}

    _REAL_CACHE["ts"] = 0.0

    if result == 0:
        return {"ok": True, "message": f"已提交撤单请求: 编号 {order_id}"}
    return {"ok": False, "message": f"撤单失败: 编号 {order_id}, miniQMT 返回 {result}"}

@router.get("/approvals")
def approvals_list():
    """实盘视图调用: 把实盘 engine 的最近 buy/sell 信号 + approval 状态 + 风控建议数量 一起返回。

    返回:
      {
        "items": [...],
        "sim_items": [...],    # 模拟盘信号 (仅展示, 不授权)
        "ttl_sec": 300,
        "capital": <float>,
      }
    """
    # 实盘信号 (从 real state 文件读)
    real_state = _load_state_real()
    real_signals = real_state.get("signals") or []
    real_capital = float(real_state.get("capital") or load_mock_config().get("capital") or 1_000_000)

    # 模拟盘信号 (仅展示, 前端可以显示但不可授权)
    sim_state = _load_state()
    sim_signals = sim_state.get("signals") or []

    approvals = _load_approvals()

    # 持仓最新价 -- 用于风控数量估算
    pos_price = {p.get("code"): float(p.get("cur_price") or 0)
                 for p in (real_state.get("positions") or [])}

    # === 实盘账户的 持仓 / 可用现金 (用 cache, 不强制刷新) ===
    real_positions_map = {}
    real_cash = 0.0
    if _REAL_CACHE.get("ts"):
        for p in (_REAL_CACHE.get("positions") or []):
            real_positions_map[p.get("stock_code")] = p
        real_cash = float((_REAL_CACHE.get("asset") or {}).get("cash") or 0)

    def _eligibility(side: str, code: str, qty: int, price_hint: float):
        if not _REAL_CACHE.get("ts"):
            return True, ""
        if side == "sell":
            pos = real_positions_map.get(code)
            if not pos:
                return False, f"实盘无 {code} 持仓, 无法卖"
            can_use = int(pos.get("can_use_volume") or 0)
            if can_use < qty:
                return False, f"可用 {can_use} < 建议 {qty} (T+1 冻结)"
        else:
            need = qty * (price_hint or 0)
            if price_hint > 0 and real_cash > 0 and need > real_cash:
                return False, f"现金 {real_cash:,.0f} < 需 {need:,.0f}"
        return True, ""

    def _build_items(signals, capital, pos_price):
        items = []
        recent = [s for s in signals if s.get("side") in ("buy", "sell")][-30:]
        for sig in reversed(recent):
            sid = _signal_id(sig)
            rec = approvals.get(sid) or {}
            age = _signal_age_sec(sig.get("ts", ""))
            status = rec.get("status") or "pending"
            if status == "pending" and age > _APPROVAL_TTL_SEC:
                status = "expired"
            price = pos_price.get(sig.get("code"), 0.0)
            qty = _calc_suggested_quantity(price, capital)
            eligible, eligible_reason = _eligibility(sig.get("side"), sig.get("code"), qty, price)
            items.append({
                "id":         sid,
                "ts":         sig.get("ts", ""),
                "code":       sig.get("code", ""),
                "side":       sig.get("side", ""),
                "strategy":   sig.get("strategy", ""),
                "reason":     sig.get("reason", ""),
                "suggested_quantity": qty,
                "suggested_price":    price,
                "status":     status,
                "processed_ts": rec.get("processed_ts"),
                "order":      rec.get("order"),
                "error":      rec.get("error"),
                "age_sec":    round(age, 1),
                "eligible":         eligible,
                "eligible_reason":  eligible_reason,
            })
        return items

    items = _build_items(real_signals, real_capital, pos_price)
    sim_items = _build_items(sim_signals, float(sim_state.get("capital") or 1_000_000), pos_price)

    return {
        "items": items,
        "sim_items": sim_items,
        "ttl_sec": _APPROVAL_TTL_SEC,
        "capital": real_capital,
    }

@router.post("/approvals/approve")
def approvals_approve(payload: Optional[Dict[str, Any]] = Body(None)):
    """授权下单: 通过 miniQMT 真实下单, 状态写入 approvals.json."""
    payload = payload or {}
    sid = str(payload.get("id", "")).strip()
    if not sid:
        return {"ok": False, "message": "id 不能为空"}

    sig = _find_signal_by_id(sid)
    if sig is None:
        return {"ok": False, "message": f"找不到信号 (可能已过期被清理): {sid}"}

    approvals = _load_approvals()
    if approvals.get(sid, {}).get("status") in ("approved", "rejected"):
        return {"ok": False, "message": f"信号已处理过 (status={approvals[sid].get('status')})"}
    if _signal_age_sec(sig.get("ts", "")) > _APPROVAL_TTL_SEC:
        return {"ok": False, "message": f"信号已过期 (>{_APPROVAL_TTL_SEC}s), 请等待新信号"}

    code = sig.get("code", "")
    side = sig.get("side", "")
    if side not in ("buy", "sell"):
        return {"ok": False, "message": f"信号方向异常: {side}"}

    # 数量: 用户传了就用, 否则按风控算
    state = _load_state_real()
    capital = float(state.get("capital") or load_mock_config().get("capital") or 1_000_000)
    pos_price = {p.get("code"): float(p.get("cur_price") or 0)
                 for p in (state.get("positions") or [])}
    price_hint = pos_price.get(code, 0.0)
    quantity = int(payload.get("quantity") or _calc_suggested_quantity(price_hint, capital))
    price = float(payload.get("price") or 0)   # 0 -> 市价

    # === 实盘前置校验 ===
    real_acc = _REAL_CACHE if _REAL_CACHE.get("ts") else None
    if side == "sell":
        positions = (real_acc or {}).get("positions") or []
        match = next((p for p in positions if p.get("stock_code") == code), None)
        if not match:
            return {"ok": False, "message": f"实盘持仓里没有 {code}, 无法卖出 (T+1 限制)"}
        can_use = int(match.get("can_use_volume") or 0)
        if can_use < quantity:
            return {"ok": False,
                    "message": f"可用持仓不足: {code} 可用 {can_use} 股 < 建议 {quantity} 股 (其余被 T+1 冻结)"}
    elif side == "buy":
        cash = float((real_acc or {}).get("asset", {}).get("cash") or 0)
        if cash > 0 and price_hint > 0 and quantity * price_hint > cash:
            return {"ok": False,
                    "message": f"可用现金不足: 需要 ~{quantity * price_hint:,.0f} 元, 实盘可用 {cash:,.0f} 元"}

    # 调 miniQMT 真实下单
    err = None
    order = None
    try:
        trader = _get_real_trader()
        if side == "buy":
            order_id = trader.buy(code, quantity, price=price,
                                  strategy_name=sig.get("strategy", ""),
                                  remark="manual_approval")
        else:
            order_id = trader.sell(code, quantity, price=price,
                                   strategy_name=sig.get("strategy", ""),
                                   remark="manual_approval")
        if order_id is None or order_id < 0:
            err = f"miniQMT 返回 order_id={order_id} (常见原因: 未连接 / 风控拦截 / 余额不足)"
        else:
            order = {"order_id": order_id, "code": code, "side": side,
                     "quantity": quantity, "price": price}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"

    approvals[sid] = {
        "status":       "approved" if err is None else "rejected",
        "processed_ts": datetime.now().isoformat(timespec="seconds"),
        "order":        order,
        "error":        err,
    }
    _save_approvals(approvals)

    if err:
        return {"ok": False, "message": f"下单失败: {err}", "error": err}
    return {"ok": True, "message": f"已授权下单 {side} {code} {quantity}股", "order": order}

@router.post("/approvals/reject")
def approvals_reject(payload: Optional[Dict[str, Any]] = Body(None)):
    """拒绝信号: 标记不下单, 状态落盘"""
    payload = payload or {}
    sid = str(payload.get("id", "")).strip()
    if not sid:
        return {"ok": False, "message": "id 不能为空"}

    approvals = _load_approvals()
    if approvals.get(sid, {}).get("status") in ("approved", "rejected"):
        return {"ok": False, "message": f"信号已处理过 (status={approvals[sid].get('status')})"}

    approvals[sid] = {
        "status":       "rejected",
        "processed_ts": datetime.now().isoformat(timespec="seconds"),
        "order":        None,
        "error":        None,
    }
    _save_approvals(approvals)
    return {"ok": True, "message": "已拒绝该信号"}

