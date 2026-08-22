# -*- coding: utf-8 -*-
# 实盘监控路由 -- REST (模拟盘 / 实盘 双引擎)
"""
模拟盘端点 (sim):
  GET  /api/live/state                 -- 读 live_state.json
  GET  /api/live/sim/status            -- 模拟盘运行状态
  GET  /api/live/sim/state             -- 读 live_state.json
  POST /api/live/sim/start             -- 启动模拟盘
  POST /api/live/sim/stop              -- 停止模拟盘
  POST /api/live/sim/trial_run         -- 模拟盘试算
  POST /api/live/sim/reset_positions   -- 重置模拟盘持仓
  POST /api/live/sim/clear_history     -- 清空模拟盘历史
  GET  /api/live/sim/strategies/config -- 获取模拟盘策略配置
  POST /api/live/sim/strategies/apply  -- 应用模拟盘策略配置
  POST /api/live/sim/stock/bind        -- 模拟盘绑定策略
  POST /api/live/sim/stock/unbind      -- 模拟盘解绑策略
  GET  /api/live/sim/watch_merge       -- 模拟盘合并监控列表
  POST /api/live/sim/force_sell        -- 模拟盘强制卖出
  POST /api/live/sim/control           -- 模拟盘运行控制

实盘端点 (real):
  POST /api/live/real/start            -- 启动实盘引擎
  POST /api/live/real/stop             -- 停止实盘引擎
  GET  /api/live/real/state            -- 读 live_state_real.json
  POST /api/live/real/trial_run        -- 实盘试算
  POST /api/live/real/reset_positions  -- 重置实盘持仓
  POST /api/live/real/clear_history    -- 清空实盘历史
  GET  /api/live/real/strategies/config -- 获取实盘策略配置
  POST /api/live/real/strategies/apply -- 应用实盘策略配置
  POST /api/live/real/stock/bind       -- 实盘绑定策略
  POST /api/live/real/stock/unbind     -- 实盘解绑策略
  GET  /api/live/real/watch_merge      -- 实盘合并监控列表
  POST /api/live/real/force_sell       -- 实盘强制卖出
  POST /api/live/real/control          -- 实盘运行控制

向后兼容 (委托到 SIM_RUNNER):
  GET  /api/live/state                 -- 同 /api/live/sim/state
  POST /api/live/control               -- 同 /api/live/sim/control
  POST /api/live/force_sell            -- 同 /api/live/sim/force_sell
  POST /api/live/status                -- 同 sim 的 trading_status
  GET  /api/live/strategies/config     -- 同 /api/live/sim/strategies/config
  POST /api/live/strategies/config     -- 同 /api/live/sim/strategies/apply
  GET  /api/live/watch_merge           -- 同 /api/live/sim/watch_merge
  GET  /api/live/watch_pool            -- 同 sim 的 watch_pool
  POST /api/live/watch_pool            -- 同 sim 的 watch_pool
  POST /api/live/stock/bind            -- 同 /api/live/sim/stock/bind
  POST /api/live/stock/unbind          -- 同 /api/live/sim/stock/unbind
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Body

from lib.paths import setup_sys_path, OUTPUTS_LIVE_STATE, OUTPUTS_DIR, PROJECT_ROOT, CONFIG_DIR
setup_sys_path()

import yaml as _yaml   # 读写 binding_source.yaml 用

from lib.live_simulator import (
    SIM_RUNNER,
    REAL_RUNNER,
    LiveSimRunner,
    load_strategy_config,
    save_strategy_config,
    load_mock_config,
    merge_watch_codes,
    load_watch_pool,
    save_watch_pool,
)
from lib.strategy_registry import list_groups, list_strategies
from lib.stock_utils import get_stock_info, normalize_code

router = APIRouter()

# 实盘状态文件路径
OUTPUTS_LIVE_STATE_REAL = OUTPUTS_DIR / "live_state_real.json"

# 配置文件路径 (基于 PROJECT_ROOT, 不依赖 CWD)
WATCH_POOL_FILE = str(CONFIG_DIR / "watch_pool.yaml")
WATCH_POOL_REAL_FILE = str(CONFIG_DIR / "watch_pool_real.yaml")
STRATEGIES_FILE = str(CONFIG_DIR / "strategies.yaml")
STRATEGIES_REAL_FILE = str(CONFIG_DIR / "strategies_real.yaml")
MOCK_POSITIONS_FILE = str(CONFIG_DIR / "mock_positions.yaml")
MOCK_POSITIONS_REAL_FILE = str(CONFIG_DIR / "mock_positions_real.yaml")

# ============================================================
# 执行方式模式 (strategy / plan) 持久化
# 说明:
#   - 用于区分某只股票当前使用「策略模式」还是「交易计划模式」
#   - 有交易计划(DB)时强制视为 plan 模式; 无计划时读本地 yaml
#   - 绑定策略时默认视为 strategy 模式
#   - sim 和 real 各自独立文件, 互不干扰
# ============================================================
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


@router.get("/ping")
def live_ping():
    """健康检查：浏览器打开 /api/live/ping 可确认当前进程已加载 live 路由 (含 stock/bind)"""
    return {"ok": True, "module": "live", "hint": "绑定接口: POST /api/live/stock/bind; sim/real 双引擎就绪"}


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


# ------------------------------------------------------------
# 向后兼容: /api/live/state -> 模拟盘 state
# ------------------------------------------------------------
@router.get("/state")
def get_state():
    return _load_state()


# ============================================================
# 模拟盘专用端点: /api/live/sim/*
# ============================================================

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


# ============================================================
# 实盘专用端点: /api/live/real/*
# ============================================================

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


# ============================================================
# 通用实现函数 (被 sim 和 real 端点共用)
# ============================================================

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


# ============================================================
# 向后兼容端点 (委托到模拟盘)
# ============================================================

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


# ============================================================
# 策略路由表 -- registry / config (向后兼容)
# ============================================================

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


# ============================================================
# 绑定来源标签 (用来区分 sim/real)
# ============================================================

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


# ============================================================
# 监控列表合并 + 自选池 (向后兼容)
# ============================================================

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


def _normalize_stock_code(raw: str) -> str:
    """标准化股票代码: 去空格、大写, 6 位裸代码自动补齐交易所后缀"""
    return normalize_code(raw)


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


# ============================================================
# 向后兼容: /api/live/stock/bind 和 /api/live/stock/unbind
# ============================================================

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


# ============================================================
# 实盘账户 (miniQMT) -- 真实持仓 / 资金 / 委托
# ============================================================

# 进程级缓存: trader 实例 + 上次查询时间戳, 避免每 5 秒前端轮询都重连 miniQMT
_REAL_TRADER = None
_REAL_CACHE: Dict[str, Any] = {"asset": {}, "positions": [], "orders": [],
                                "ts": 0.0, "error": None}
_REAL_CACHE_TTL = 5.0   # 秒

# xtquant 委托状态码 -> 中文（与 xtconstant / 常见回报含义对齐）
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


# ============================================================
# AI 信号 → 手动授权下单 (实盘视图用)
#
# 设计:
#   - 实盘引擎 (REAL_RUNNER) 照常跑 (dry_run=False 时连 miniQMT),
#     但实盘 Tab 的信号仍然需要手动授权
#   - buy/sell 信号写到 real 的 state.signals
#   - 模拟盘(Sim)引擎即使跑着也不产生实盘授权信号
#   - approval 状态写到 OUTPUTS_DIR/live_approvals.json
# ============================================================

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
