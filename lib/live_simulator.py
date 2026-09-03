# -*- coding: utf-8 -*-
# 模拟盘 / 实盘 runner -- 后台线程跑 LiveTradingLoop
"""
设计:
    - 启动: 后台 daemon 线程跑 LiveTradingLoop.run_once() 循环 (默认每 60 秒)
    - 持仓: 从 config/mock_positions.yaml 读取
    - 模式: dry_run (默认, 模拟下单) / 实盘 (连真实 miniQMT, 慎用!)
    - 策略: 从 config/strategies.yaml 读路由表, 注入 StrategyRouter 到 loop
    - 行情: xtdata 真实数据

数据写到 outputs/live/live_state.json, dashboard 5 秒轮询自动刷新
"""

from __future__ import annotations
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from lib.stock_utils import normalize_code
from lib.paths import (
    OUTPUTS_DIR, CONFIG_DIR, OUTPUTS_LIVE_STATE, OUTPUTS_LIVE_STATE_REAL,
)


CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "mock_positions.yaml"
STRATEGY_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "strategies.yaml"
WATCH_POOL_FILE = Path(__file__).resolve().parent.parent / "config" / "watch_pool.yaml"


# ============================================================
# 策略路由配置 -- 读 / 写 strategies.yaml
# ============================================================

def load_strategy_config(strategy_file=None):
    """读 strategies.yaml -- 返回 {default, per_stock}
    strategy_file: 可选, 覆盖默认路径"""
    path = Path(strategy_file) if strategy_file else STRATEGY_CONFIG_FILE
    if not path.exists():
        return {"default": "macd_5min", "per_stock": {}}
    try:
        import yaml
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {
            "default":   cfg.get("default", "macd_5min"),
            "per_stock": cfg.get("per_stock", {}) or {},
        }
    except Exception as e:
        print(f"[WARN] 读 {path.name} 失败: {e}")
        return {"default": "macd_5min", "per_stock": {}}


def save_strategy_config(default: str, per_stock: dict, strategy_file=None) -> None:
    """写 strategies.yaml -- 前端 '应用策略配置' 调
    strategy_file: 可选, 覆盖默认路径"""
    path = Path(strategy_file) if strategy_file else STRATEGY_CONFIG_FILE
    import yaml
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# 实盘监控 -- 策略路由表 (由 /live 页面写入)\n"
            "# 修改后, 在页面点 '应用策略配置' 即可热加载, 无需重启\n"
            "# MACD: macd_5min=5分钟K(日内) / macd_1d=日K(12/26/9); 另有 dual_ma_5min / ma20_hold / multi_factor_top / dragon_picker / grid_classic\n\n"
        )
        body = yaml.safe_dump(
            {"default": default, "per_stock": dict(per_stock or {})},
            allow_unicode=True, sort_keys=False, default_flow_style=False,
        )
        path.write_text(header + body, encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"无法写入 {path}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"写入 {path.name} 失败: {e}") from e


# ============================================================
# 自选监控池 watch_pool.yaml -- 无持仓也会拉行情、算信号、可触发买入
# ============================================================

def load_watch_pool(watch_pool_file=None):
    """读 watch_pool.yaml -- 返回 {codes: [str,...]}
    watch_pool_file: 可选, 覆盖默认路径"""
    path = Path(watch_pool_file) if watch_pool_file else WATCH_POOL_FILE
    if not path.exists():
        return {"codes": []}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        codes = data.get("codes", []) or []
        return {"codes": [normalize_code(str(c)) for c in codes if str(c).strip()]}
    except Exception as e:
        print(f"[WARN] 读 {path.name} 失败: {e}")
        return {"codes": []}


def save_watch_pool(codes: List[str], watch_pool_file=None) -> None:
    """写 watch_pool.yaml
    watch_pool_file: 可选, 覆盖默认路径"""
    path = Path(watch_pool_file) if watch_pool_file else WATCH_POOL_FILE
    import yaml
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# 监控代码列表 -- 与持仓、per_stock 合并为最终监控列表 (去重)\n"
            "# 也可通过页面「添加股票并绑定策略」写入\n\n"
        )
        body = yaml.safe_dump(
            {"codes": [normalize_code(c) for c in (codes or []) if str(c).strip()]},
            allow_unicode=True, sort_keys=False, default_flow_style=False,
        )
        path.write_text(header + body, encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"无法写入 {path}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"写入 {path.name} 失败: {e}") from e


def make_combined_evaluator(router, plan_type: str = "sim", state_file=None, exec_mode_file=None):
    """组合评估器: 根据执行方式 yaml 决定用交易计划还是策略路由。

    - 执行方式 = "plan" → 只用交易计划, 无触发则 hold (不 fallback 到策略)
    - 执行方式 = "strategy" → 只用策略路由 (有显式策略绑定)
    - 执行方式 未设置 → hold (不产生信号): 自选池候选 / 纯持仓不买不卖,
      想恢复交易需重新绑定策略或交易计划

    返回: evaluator(code, market, capital) -> dict
    state_file: 可选, 交易计划评估时读取持仓的状态文件路径
    exec_mode_file: 执行方式 yaml 文件路径, 不传则根据 plan_type 自动推断
    """
    from lib.trading_plan import make_plan_evaluator
    from lib.paths import CONFIG_DIR as _cfg_dir
    import yaml as _yaml

    plan_evaluator = make_plan_evaluator(plan_type=plan_type, state_file=state_file)
    # sim/real 独立: plan_type="live" → execution_mode_real.yaml, 否则 execution_mode.yaml
    if exec_mode_file is not None:
        _exec_mode_file = Path(exec_mode_file)
    elif plan_type == "live":
        _exec_mode_file = _cfg_dir / "execution_mode_real.yaml"
    else:
        _exec_mode_file = _cfg_dir / "execution_mode.yaml"

    def _load_modes() -> dict:
        try:
            if not _exec_mode_file.exists():
                return {}
            data = _yaml.safe_load(_exec_mode_file.read_text(encoding="utf-8")) or {}
            raw = data.get("modes", {}) or {}
            # 标准化代码, 与 routes/live.py 中 _load_execution_modes 保持一致
            return {normalize_code(str(k)): str(v).strip() for k, v in raw.items()
                    if str(v).strip() in ("plan", "strategy")}
        except Exception:
            return {}

    def evaluator(code: str, market, capital: float) -> dict:
        modes = _load_modes()
        exec_mode = modes.get(code, "")

        if exec_mode == "plan":
            # 交易计划模式: 只用交易计划, 无触发则无信号, 不 fallback 到策略
            try:
                plan_result = plan_evaluator(code, market, capital)
            except Exception as e:
                plan_result = {"side": "hold", "strategy": "plan", "reason": f"计划评估异常: {e}"}
            return plan_result
        elif exec_mode == "strategy":
            # 策略模式: 只用策略路由 (有显式策略绑定)
            if router is not None:
                try:
                    return router(code, market, capital)
                except Exception as e:
                    return {"side": "hold", "strategy": "router", "reason": f"策略路由异常: {e}"}
            return {"side": "hold", "strategy": "none", "reason": "无策略路由"}
        else:
            # 无执行方式 (自选池候选 / 纯持仓): 不产生信号, 不买也不卖
            # 想恢复交易需重新绑定策略或交易计划
            return {"side": "hold", "strategy": "none", "reason": "未绑定策略或交易计划"}

    return evaluator


def merge_watch_codes(
    ui_codes: Optional[List[str]] = None,
    watch_pool_codes: Optional[List[str]] = None,
    strategy_codes: Optional[List[str]] = None,
    mock_cfg_file: Optional[str] = None,
) -> List[str]:
    """
    合并监控代码 (去重, 顺序: 页面输入 -> 持仓 -> 自选池 -> 策略路由里的代码)

    ui_codes: 运行控制里「额外监控」逗号分隔解析后的列表, 可为空
    watch_pool_codes / strategy_codes / mock_cfg_file: 可选, 覆盖默认路径
    """
    ui_codes = ui_codes or []
    seen = set()
    out: List[str] = []

    def push(c: str) -> None:
        c = normalize_code((c or "").strip())
        if not c or c in seen:
            return
        seen.add(c)
        out.append(c)

    for c in ui_codes:
        push(c)
    mock = load_mock_config(mock_cfg_file)
    for p in mock.get("positions", []):
        push(str(p.get("code", "")))
    wp_codes = watch_pool_codes if watch_pool_codes is not None else load_watch_pool().get("codes", [])
    for c in wp_codes:
        push(c)
    st_codes = strategy_codes if strategy_codes is not None else list((load_strategy_config().get("per_stock") or {}).keys())
    for c in st_codes:
        push(str(c).strip())
    return out


# ============================================================
# A 股交易时段判断 -- 9:30-11:30 + 13:00-15:00, 仅工作日
# 用于跳过非盘中循环 (避免在收盘后/周末仍触发信号)
# ============================================================

def is_a_share_trading_hour(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    # 工作日 (周一到周五)
    if now.weekday() >= 5:
        return False
    t = now.time()
    from datetime import time as dt_time
    return ((dt_time(9, 30) <= t <= dt_time(11, 30))
            or (dt_time(13, 0) <= t <= dt_time(15, 0)))


def load_mock_config(config_file=None):
    """读 mock_positions.yaml -- 学员可改这个文件改持仓
    config_file: 可选, 覆盖默认路径"""
    path = Path(config_file) if config_file else CONFIG_FILE
    if not path.exists():
        return {"capital": 1_000_000, "positions": []}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[WARN] 读 {path.name} 失败: {e}")
        return {"capital": 1_000_000, "positions": []}


def _latest_close_map(codes: List[str]) -> dict:
    """批量拉每只票的「最新一根日 K close」, 给 build_positions 当 cur_price.

    背景: 模拟盘 worker 在非交易时段会跳过 (不拉 tick), 所以持仓 cur_price 会卡
    在初始值; 之前直接拿 cost 当初始价 -> 表里浮盈/亏永远 0, 与「4-1 持有至今」
    的真实涨跌脱节. 现在启动 / 重置持仓时, 用 MySQL/xtdata 日 K 的最新 close
    刷新一次, 即便不在盘中, 用户也能看到真实的持有期浮盈.

    返回: {code: latest_close}; 拿不到的 code 不出现 -> 调用方回退到 cost
    """
    if not codes:
        return {}
    try:
        from lib.backtest_data import load_daily_kline
    except Exception as e:
        print(f"[WARN] _latest_close_map: import backtest_data 失败 -> {e}", flush=True)
        return {}
    out = {}
    # 拉近 30 天日 K 取最新一根 close, 区间宽一点容错节假日 / 周末
    from datetime import date, timedelta
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=45)).strftime("%Y-%m-%d")
    for code in codes:
        try:
            df = load_daily_kline(code, start_date=start_date, end_date=end_date)
        except Exception as e:
            print(f"[WARN] 拉 {code} 最新 close 失败: {e}", flush=True)
            continue
        if df is None or df.empty:
            continue
        out[code] = float(df.iloc[-1]["close"])
    return out


def build_positions_from_config(config_file=None) -> List[dict]:
    """从 config 构建标准化的 positions list (每只补齐当前价/市值/盈亏字段)

    cur_price 取自最新一根日 K close (容错: 拿不到回退到 cost), 这样:
      - 持仓表里的浮盈/亏 = (最新 close - cost) * volume, 反映真实持有期表现
      - calc_today_pnl 基于 position.pnl 求和 -> today_pnl 和持仓表对得上
      - 盘中真实 tick 来了, live_loop 会继续覆盖 cur_price (无副作用)

    config_file: 持仓配置文件路径, 不传默认 config/mock_positions.yaml
    """
    cfg = load_mock_config(config_file)
    raw_positions = cfg.get("positions", []) or []
    codes = [p.get("code", "") for p in raw_positions if p.get("code")]
    close_map = _latest_close_map(codes)

    positions = []
    for p in raw_positions:
        code = p.get("code", "")
        cost = float(p.get("cost", 0))
        volume = int(p.get("volume", 0))
        cur_price = float(close_map.get(code, cost))
        market_value = volume * cur_price
        pnl = (cur_price - cost) * volume
        pnl_pct = (cur_price / cost - 1) if cost > 0 else 0.0
        positions.append({
            "code":         code,
            "name":         p.get("name", ""),
            "volume":       volume,
            "cost":         cost,
            "cur_price":    round(cur_price, 4),
            "market_value": round(market_value, 2),
            "pnl":          round(pnl, 2),
            "pnl_pct":      round(pnl_pct, 4),
        })
    return positions


# ============================================================
# 历史订单回填 -- 模块级函数 (start() 自动调 + cli 也能单跑)
# ============================================================

def seed_historical_orders(force: bool = False, state_file=None, mock_cfg_file=None, strategy_file=None) -> str:
    """从 SIM_HISTORY_START_DATE 至今, 按每只票路由策略跑一遍回测引擎,
    把 trades (已撮合成交) 转成 orders 写入指定的 state 文件.

    设计:
        - 不启动主循环, 不连券商, 纯历史日 K + 回测引擎跑出来的"假装下单"
        - 仅 state.orders 为空 (或 force=True) 才写, 避免重复
        - 每个 trade -> 1 个 order (含 ts/code/side/qty/price/amount), status="dry_run"
        - 调用方:
            1) LiveSimRunner.start() 启动时自动调 (与 signals/pnl 回放并列)
            2) cli 单跑: python lib/live_simulator.py --backfill-orders
        - 复用 run_backtest -- 撮合规则一致 (T+1, 整手, 手续费), 不另搭一套撮合

    Args:
        force: True=强制覆盖已有 orders
        state_file: 状态文件路径, 不传默认 outputs/live/live_state.json (向后兼容 cli)
        mock_cfg_file: 持仓配置文件路径, 不传默认 config/mock_positions.yaml (向后兼容 cli)
        strategy_file: 策略配置文件路径, 不传默认 config/strategies.yaml (向后兼容 cli)

    Returns:
        日志字符串 (打印 + 给前端 status 看)
    """
    from lib.paths import OUTPUTS_LIVE_STATE
    import json

    _state_path = Path(state_file) if state_file else OUTPUTS_LIVE_STATE
    if not _state_path.exists():
        return f"[ERR] {_state_path.name} 不存在, 先启动一次引擎 (启动会创建空 state)"

    s = json.loads(_state_path.read_text(encoding="utf-8"))
    if s.get("orders") and not force:
        return f"[INFO] orders 已有 {len(s.get('orders'))} 条, 跳过回填 (--force 强制覆盖)"

    cfg = load_mock_config(mock_cfg_file)
    positions = cfg.get("positions") or []
    if not positions:
        return "[ERR] mock_positions.yaml 没有持仓配置"

    strat_cfg = load_strategy_config(strategy_file=strategy_file)
    per_stock = strat_cfg.get("per_stock") or {}
    default_strat = strat_cfg.get("default", "macd_1d")

    start_date = os.environ.get("SIM_HISTORY_START_DATE", "2026-04-01")
    from datetime import date
    end_date = date.today().strftime("%Y-%m-%d")

    try:
        from lib.backtest_engine import run_backtest
    except Exception as e:
        return f"[ERR] import backtest_engine 失败: {e}"

    new_orders: List[dict] = []
    detail_lines: List[str] = []
    for p in positions:
        code = str(p.get("code", "")).strip()
        name = p.get("name", "")
        if not code:
            continue
        strat = per_stock.get(code) or default_strat
        try:
            r = run_backtest(stock_code=code, strategy_name=strat,
                             start_date=start_date, end_date=end_date)
        except Exception as e:
            detail_lines.append(f"  [SKIP] {code}/{strat}: {type(e).__name__}: {e}")
            continue
        if not r or not r.get("ok"):
            detail_lines.append(f"  [SKIP] {code}/{strat}: {r.get('message', '?') if r else 'no result'}")
            continue
        trades = r.get("trades") or []
        n_added = 0
        for idx, t in enumerate(trades):
            d = t.get("date")
            side = t.get("side")
            qty = int(t.get("size", 0))
            px = float(t.get("price", 0))
            if not d or side not in ("buy", "sell") or qty <= 0 or px <= 0:
                continue
            new_orders.append({
                "ts":       f"{d}T15:00:00",
                "code":     code,
                "name":     name,
                "side":     side,
                "quantity": qty,
                "price":    round(px, 4),
                "amount":   round(qty * px, 2),
                "status":   "dry_run",
                "order_id": f"seed_{code}_{idx}",
                "strategy": strat,
                "reason":   t.get("reason", ""),
            })
            n_added += 1
        detail_lines.append(f"  [OK] {code}/{strat}: 写入 {n_added} 笔成交")

    if not new_orders:
        return ("[WARN] 所有股票区间内都没产生成交 (策略全程 hold), orders 仍为空\n"
                + "\n".join(detail_lines))

    new_orders.sort(key=lambda x: x["ts"])

    # 重新读一遍 + 写回 (避免读到写之间被主循环改动)
    s = json.loads(_state_path.read_text(encoding="utf-8"))
    s["orders"] = new_orders
    s["_updated_at"] = datetime.now().isoformat(timespec="seconds")

    tmp = _state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _state_path)

    n_run_ok = sum(1 for d in detail_lines if d.startswith("  [OK]"))
    n_with_trade = sum(1 for d in detail_lines
                       if d.startswith("  [OK]") and not d.endswith("写入 0 笔成交"))
    return (f"[OK] 历史订单回填: 共写入 {len(new_orders)} 笔 "
            f"({start_date} ~ {end_date}, "
            f"{n_run_ok}/{len(positions)} 只票运行成功, {n_with_trade} 只产生成交)\n"
            + "\n".join(detail_lines))


class LiveSimRunner:
    """模拟盘/实盘控制器 (支持多实例, sim 和 real 各独立)

    参数:
        plan_type:       "sim" 或 "live", 决定交易计划类型
        state_file:      状态文件路径 (如 outputs/live/live_state.json)
        strategy_file:   策略配置文件路径 (如 config/strategies.yaml)
        watch_pool_file: 自选监控池文件路径 (如 config/watch_pool.yaml)
        mock_config_file: 初始持仓配置文件路径 (如 config/mock_positions.yaml)
        dry_run_default: 默认是否模拟下单
    """

    def __init__(
        self,
        plan_type: str = "sim",
        state_file: Optional[str] = None,
        strategy_file: Optional[str] = None,
        watch_pool_file: Optional[str] = None,
        mock_config_file: Optional[str] = None,
        dry_run_default: bool = True,
    ):
        self.plan_type = plan_type
        self.dry_run_default = dry_run_default

        from lib.paths import OUTPUTS_LIVE_STATE
        PROJECT_DIR = Path(__file__).resolve().parent.parent
        CONFIG_DIR = PROJECT_DIR / "config"

        # 状态文件
        self._state_file = Path(state_file) if state_file else OUTPUTS_LIVE_STATE
        # 策略配置
        self._strategy_file = Path(strategy_file) if strategy_file else (CONFIG_DIR / "strategies.yaml")
        # 自选监控池
        self._watch_pool_file = Path(watch_pool_file) if watch_pool_file else (CONFIG_DIR / "watch_pool.yaml")
        # mock 持仓
        self._mock_config_file = Path(mock_config_file) if mock_config_file else (CONFIG_DIR / "mock_positions.yaml")
        # 执行方式文件 (sim/real 独立)
        if plan_type == "live":
            self._exec_mode_file = CONFIG_DIR / "execution_mode_real.yaml"
        else:
            self._exec_mode_file = CONFIG_DIR / "execution_mode.yaml"

        self._thread: Optional[threading.Thread] = None
        self._stop_flag = False
        self._loop = None
        self._cycle_count = 0
        self._last_cycle_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._dry_run = dry_run_default
        self._router = None        # StrategyRouter -- 启动后才创建
        self._last_watch_stocks: Optional[List[str]] = None  # 最近一次启动时的合并监控列表

    # ------------------------------------------------------------------
    # 实例专属配置读写 (而非模块级全局函数)
    # ------------------------------------------------------------------
    def _load_mock_cfg(self) -> dict:
        return load_mock_config(self._mock_config_file)

    def _load_strat_cfg(self) -> dict:
        return load_strategy_config(strategy_file=self._strategy_file)

    def _save_strat_cfg(self, default: str, per_stock: dict) -> None:
        save_strategy_config(default, per_stock, strategy_file=self._strategy_file)

    def _load_watch_cfg(self) -> dict:
        return load_watch_pool(watch_pool_file=self._watch_pool_file)

    def _save_watch_cfg(self, codes: List[str]) -> None:
        save_watch_pool(codes, watch_pool_file=self._watch_pool_file)

    # ------------------------------------------------------------------
    def status(self) -> dict:
        running = self._thread is not None and self._thread.is_alive()
        return {
            "running":        running,
            "cycle_count":    self._cycle_count,
            "last_cycle_at":  self._last_cycle_at,
            "last_error":     self._last_error,
            "dry_run":        self._dry_run,
            "watch_stocks":   list(self._last_watch_stocks or []),
        }

    # ------------------------------------------------------------------
    def start(self, watch_stocks: List[str], cycle_seconds: int = 60,
              dry_run: bool = True, init_positions: bool = False) -> str:
        """启动后台循环

        Args:
            watch_stocks: 监控股票池
            cycle_seconds: 循环周期 (秒)
            dry_run: True=模拟下单, False=真实下单 (慎用!)
            init_positions: 是否用 config 初始化持仓 (默认 False, 保留已有持仓;
                            仅在首次启动无持仓或显式要求重置时从 mock_positions.yaml 初始化)
        """
        if self._thread is not None and self._thread.is_alive():
            return "[INFO] 引擎已在运行, 请先停止"

        from lib.paths import setup_sys_path
        setup_sys_path()
        from services.live.trading.live_loop import LiveTradingLoop
        from lib.strategy_registry import StrategyRouter

        cfg = load_mock_config(self._mock_config_file)
        capital = float(cfg.get("capital", 1_000_000))

        # 创建策略路由器 (从实例专属 strategies.yaml 读路由表)
        strat_cfg = load_strategy_config(strategy_file=self._strategy_file)
        self._router = StrategyRouter(
            per_stock=strat_cfg.get("per_stock", {}),
            default=strat_cfg.get("default", "macd_5min"),
        )

        try:
            self._last_watch_stocks = list(watch_stocks)
            combined_evaluator = make_combined_evaluator(
                self._router, plan_type=self.plan_type,
                state_file=str(self._state_file),
                exec_mode_file=str(self._exec_mode_file),
            )
            # 成交钩子: 交易计划信号真正成交后, 由计划系统标记条件已触发(只触发一次)
            from lib.trading_plan import on_plan_signal_executed
            self._loop = LiveTradingLoop(
                watch_stocks=watch_stocks,
                capital=capital,
                state_file=str(self._state_file),
                dry_run=dry_run,
                signal_evaluator=combined_evaluator,
                engine_label="SIM" if self.plan_type == "sim" else ("REAL" if self.plan_type == "live" else self.plan_type.upper()),
                on_plan_executed=on_plan_signal_executed,
            )
            self._dry_run = dry_run
        except Exception as e:
            return f"[ERROR] 创建 LiveTradingLoop 失败: {e}"

        # 初始化持仓
        # - init_positions=True: 显式要求重置 (如点击"重置持仓"按钮)
        # - 无已有持仓: 首次启动, 从 mock_positions.yaml 初始化
        # - 有已有持仓且未要求重置: 保留 live_state.json 中的真实交易结果
        s = self._loop.state_store.load()
        s["trading_status"] = "RUNNING"
        existing_positions = s.get("positions") or []
        if init_positions or not existing_positions:
            s["positions"] = build_positions_from_config(str(self._mock_config_file))
            # 初始化持仓后, 从总资金中扣除持仓成本, 得到实际可用现金
            total_cost = sum(
                float(p.get("cost", 0)) * int(p.get("volume", 0))
                for p in (s.get("positions") or [])
            )
            s["capital"] = max(0, capital - total_cost)
        # 重算累计盈亏: 总资产 - 初始本金 (已实现+未实现全部纳入)
        try:
            total_assets = s.get("capital", 0) + sum(
                float(p.get("market_value", 0)) for p in (s.get("positions") or [])
            )
            initial = s.get("initial_capital", capital)
            if initial <= 0:
                initial = capital
            s["today_pnl"] = round(total_assets - initial, 2)
            s["today_pnl_pct"] = round(s["today_pnl"] / initial, 4) if initial > 0 else 0
        except Exception as e:
            print(f"[WARN] 启动时重算 today_pnl 失败: {e}", flush=True)
        self._loop.state_store.save(s)

        # 历史信号回放: 信号表为空时, 把每只监控股票从 SIM_HISTORY_START_DATE
        # 至今的策略 buy/sell 信号回放进 state.signals, 用户首次打开就能看到历史
        # 失败不阻塞 start (回测引擎/MySQL/数据缺失都属于非致命)
        try:
            self._seed_historical_signals_if_empty(watch_stocks)
        except Exception as e:
            print(f"[WARN] 历史信号回放失败 (不影响主流程): {e}", flush=True)

        # 历史订单回填: orders 表为空时, 跑一遍回测引擎拿成交 trades, 写入 state.orders
        # 让 /review 流水卡有数据可看 (信号是"建议", 订单是"执行", 两者都要有)
        try:
            log = seed_historical_orders(
                force=False,
                state_file=str(self._state_file),
                mock_cfg_file=str(self._mock_config_file) if self._mock_config_file else None,
                strategy_file=str(self._strategy_file) if self._strategy_file else None,
            )
            print(log, flush=True)
        except Exception as e:
            print(f"[WARN] 历史订单回填失败 (不影响主流程): {e}", flush=True)

        # 历史资金曲线回放: 资金曲线没"今天之前的点"时, 把 [start_date, 昨天] 每个交易日
        # 按 mock_positions buy-and-hold 算的总资产% 写进 state.pnl_history,
        # 让"资金曲线"图启动就能看到 4-1 至今的趋势, 而不是只有今天那一段
        try:
            self._seed_historical_pnl_curve_if_empty()
        except Exception as e:
            print(f"[WARN] 历史资金曲线回放失败 (不影响主流程): {e}", flush=True)

        # 启动 worker
        self._stop_flag = False
        self._cycle_count = 0
        self._last_error = None

        def worker():
            while not self._stop_flag:
                if not is_a_share_trading_hour():
                    # 非交易时段跳过, 显示是否有待处理的强制卖出
                    pending = False
                    try:
                        s = self._loop.state_store.load()
                        ctrl = s.get("control", {})
                        pending = bool(ctrl.get("force_clear_all", False)) or bool(ctrl.get("force_sell_codes"))
                    except Exception:
                        pass
                    tag = " (非盘中, 跳过)"
                    if pending:
                        tag += ", 有强制卖出待执行"
                    self._last_cycle_at = f"{datetime.now().strftime('%H:%M:%S')}{tag}"
                else:
                    try:
                        self._loop.run_once()
                        self._cycle_count += 1
                        self._last_cycle_at = datetime.now().strftime("%H:%M:%S")
                        self._last_error = None
                    except Exception as e:
                        self._last_error = f"{type(e).__name__}: {e}"
                for _ in range(cycle_seconds):
                    if self._stop_flag:
                        break
                    time.sleep(1)

        self._thread = threading.Thread(target=worker, daemon=True,
                                         name="LiveSimRunner")
        self._thread.start()

        mode_str = "模拟模式 (dry-run, 不连券商)" if dry_run else "实盘模式 (真实下单!)"
        # 路由表摘要 (前 5 条)
        route_preview = ", ".join(
            f"{c}->{n}" for c, n in list(self._router.per_stock.items())[:5]
        ) or "(空)"
        return (f"[OK] 已启动 -- {mode_str}\n"
                f"     合并后监控 {len(watch_stocks)} 只: {watch_stocks}, 周期={cycle_seconds}s, "
                f"初始持仓 {len(s.get('positions', []))} 只, 总资金 {capital:,.0f}\n"
                f"     默认策略={self._router.default}, 路由表预览: {route_preview}\n"
                f"     dashboard 每 5 秒自动刷新")

    # ------------------------------------------------------------------
    def stop(self) -> str:
        if self._thread is None:
            return "[INFO] 模拟盘未启动"
        self._stop_flag = True
        self._thread.join(timeout=5)
        msg = f"[OK] 已停止 -- 共跑了 {self._cycle_count} 轮"
        self._thread = None
        return msg

    # ------------------------------------------------------------------
    def trial_run(self) -> dict:
        """非交易时段也强制跑一次, 给用户看「现在各策略给的方向」.

        返回值:
            {
                "ok":        True/False,
                "message":   总结 (用户提示用)
                "summary":   {"buy": n, "sell": n, "hold": n, "total": n},
                "diagnoses": [{"code", "strategy", "side", "reason"}, ...]
            }

        实现说明:
            - 调 loop.run_once() 走完整流程 (含风控/下单), 信号写进 state.signals 表
            - 试算会真实修改持仓/资金状态, 需恢复时点击「重置持仓」按钮
            - 同时单独再跑一遍 router 收集每只股票的方向 (buy/sell/hold), 含 hold 也返回
              这样用户能直观看到「为什么没有信号 == 6 只全 hold」
            - 必须先 start() 过, 否则 self._loop 还没创建
        """
        if self._loop is None:
            return {
                "ok": False,
                "message": "[ERROR] 模拟盘未启动 (self._loop is None), 请先点「启动循环」",
                "summary": {}, "diagnoses": [],
            }

        # 先跑完整 loop (会写 signals/orders, 触发风控, 修改持仓/资金)
        # 跑之前先捕获强制卖出标记 (run_once 会清空, 后续诊断需要用)
        import json as _json
        _pre_state = _json.loads(self._state_file.read_text(encoding="utf-8"))
        _pre_ctrl = _pre_state.get("control", {})
        _pre_force_clear = bool(_pre_ctrl.get("force_clear_all", False))
        _pre_force_codes = list(_pre_ctrl.get("force_sell_codes") or [])
        try:
            self._loop.run_once()
            self._cycle_count += 1
            self._last_cycle_at = datetime.now().strftime("%H:%M:%S") + " (试算)"
            self._last_error = None
            loop_msg = f"[OK] 已试算 1 轮 (累计循环 {self._cycle_count})"
        except Exception as e:
            self._last_error = f"{type(e).__name__}: {e}"
            return {
                "ok": False,
                "message": f"[ERROR] 试算失败: {self._last_error}",
                "summary": {}, "diagnoses": [],
            }

        # 再跑一次 router (仅诊断, 不写盘) 用于把 hold 也告诉用户
        diagnoses: List[dict] = []
        summary = {"buy": 0, "sell": 0, "hold": 0, "error": 0, "total": 0}
        try:
            cfg = self._load_mock_cfg()
            capital = float(cfg.get("capital", 1_000_000))
            watch = list(self._last_watch_stocks or merge_watch_codes(
                watch_pool_codes=self._load_watch_cfg().get("codes", []),
                strategy_codes=list((self._load_strat_cfg().get("per_stock") or {}).keys()),
                mock_cfg_file=str(self._mock_config_file),
            ))
            # 合并强制卖出信号: 不在 router 评估范围内, 需要单独注入到诊断结果
            force_diagnoses = {}
            if _pre_force_clear:
                _all_pos_codes = {p.get("code") for p in (_pre_state.get("positions") or [])}
                for code in _all_pos_codes:
                    force_diagnoses[code] = {"strategy": "force_sell", "side": "sell",
                                              "reason": "CEO 控制台: 一键清仓"}
            else:
                for code in _pre_force_codes:
                    force_diagnoses[code] = {"strategy": "force_sell", "side": "sell",
                                              "reason": "CEO 控制台: 强制卖出"}

            combined = make_combined_evaluator(self._router, plan_type=self.plan_type, state_file=str(self._state_file), exec_mode_file=str(self._exec_mode_file))
            for code in watch:
                # 强制卖出优先: 不在 router 评估范围内, 直接注入诊断
                if code in force_diagnoses:
                    fd = force_diagnoses[code]
                    side = fd["side"]
                    summary[side] = summary.get(side, 0) + 1
                    summary["total"] += 1
                    diagnoses.append({"code": code, "strategy": fd["strategy"],
                                      "side": side, "reason": fd["reason"]})
                    continue
                try:
                    r = combined(code, self._loop.market, capital)
                except Exception as e:
                    r = {"side": "error", "strategy": "?",
                         "reason": f"{type(e).__name__}: {e}"}
                side = r.get("side", "hold")
                summary[side] = summary.get(side, 0) + 1
                summary["total"] += 1
                diagnoses.append({
                    "code":     code,
                    "strategy": r.get("strategy", "?"),
                    "side":     side,
                    "reason":   r.get("reason", ""),
                })
        except Exception as e:
            # 诊断失败不影响主流程
            print(f"[WARN] trial_run diagnose error: {e}", flush=True)

        msg = (f"{loop_msg} -- 监控 {summary['total']} 只: "
               f"buy={summary['buy']}, sell={summary['sell']}, "
               f"hold={summary['hold']}"
               + (f", error={summary['error']}" if summary.get("error") else ""))
        return {
            "ok": True,
            "message": msg,
            "summary": summary,
            "diagnoses": diagnoses,
        }

    # ------------------------------------------------------------------
    def apply_strategy_config(self, default: str, per_stock: dict) -> str:
        """热加载策略路由表 (写盘 + 同步给已运行的 router)"""
        self._save_strat_cfg(default, per_stock)
        if self._router is not None:
            self._router.update(per_stock=per_stock, default=default)
            return (f"[OK] 路由表已热加载 -- 默认={default}, "
                    f"per_stock={len(per_stock or {})} 条 (已写盘)")
        return (f"[OK] 路由表已写盘 -- 默认={default}, per_stock={len(per_stock or {})} 条 "
                f"(引擎未启动, 下次启动生效)")

    # ------------------------------------------------------------------
    def _seed_historical_pnl_curve_if_empty(self) -> None:
        """启动时把 [SIM_HISTORY_START_DATE, 昨天] 的每日资金曲线点回放进 state.pnl_history.

        - 仅在 pnl_history 里没有"早于今天"的点时跑 (今天的盘中分时数据保留不动)
        - 用 mock_positions (vol/cost) + 每日 close 算每天的"总资产 vs 初始资金"百分比:
            asset_d = sum(vol_i * close_i[d]) + cash
            pnl_pct = (asset_d - capital) / capital
            cash = capital - sum(vol_i * cost_i)   (一直不动, 因为我们目前没成交)
        - ts 取当日 15:00:00 (与历史信号 ts 同格), 与今天的盘中分时点拼成完整曲线
        - 失败不影响启动
        """
        s = self._loop.state_store.load()
        hist = s.get("pnl_history") or []
        from datetime import date
        today_str = date.today().strftime("%Y-%m-%d")
        # 是否已有"今天之前"的点 -> 有就不再补 (避免重启重复 seed)
        has_pre_today = any((p.get("ts", "") < today_str) for p in hist)
        if has_pre_today:
            return

        cfg = self._load_mock_cfg()
        capital = float(cfg.get("capital", 1_000_000))
        positions_cfg = cfg.get("positions", []) or []
        if not positions_cfg:
            return

        # 现金 = 初始资金 - 持仓 cost 占用 (假定区间内无成交, sim 引擎非盘中没跑)
        cost_used = sum(int(p.get("volume", 0)) * float(p.get("cost", 0))
                        for p in positions_cfg)
        cash = capital - cost_used

        try:
            from lib.backtest_data import load_daily_kline
        except Exception as e:
            print(f"[WARN] pnl_history seed: import backtest_data 失败 -> {e}", flush=True)
            return

        start_date = os.environ.get("SIM_HISTORY_START_DATE", "2026-04-01")

        # 1) 拉每只票从 start_date 至今的日 K close
        # 2) 取所有日期的并集 (按交易日齐对齐), 没数据的日 forward fill
        import pandas as pd
        close_dfs = {}
        for p in positions_cfg:
            code = p.get("code", "")
            try:
                df = load_daily_kline(code, start_date=start_date, end_date=today_str)
            except Exception as e:
                print(f"[WARN] pnl_history seed: 拉 {code} 失败: {e}", flush=True)
                continue
            if df is None or df.empty:
                continue
            close_dfs[code] = df["close"]

        if not close_dfs:
            return

        # 合并, ffill 防节假日空档 (虽然交易日都有, 容错)
        all_closes = pd.concat(close_dfs, axis=1).sort_index().ffill()

        new_points: List[dict] = []
        for ts, row in all_closes.iterrows():
            d_str = ts.strftime("%Y-%m-%d")
            # 只回放 < today (今天用真实盘中数据)
            if d_str >= today_str:
                continue
            mv = 0.0
            for p in positions_cfg:
                code = p.get("code", "")
                vol = int(p.get("volume", 0))
                px = row.get(code)
                if px is None or pd.isna(px):
                    continue
                mv += vol * float(px)
            asset = cash + mv
            pnl = asset - capital
            pct = pnl / capital if capital > 0 else 0.0
            # ts 用 14:59:00 而非 15:00:00 -- 避免踩在 plotly rangebreak [15, 9.5] 边界
            # 上被当作非交易时段过滤掉
            new_points.append({
                "ts":      f"{d_str}T14:59:00",
                "pnl":     round(pnl, 2),
                "pnl_pct": round(pct, 4),
            })

        if not new_points:
            return

        # 把回放点拼到 pnl_history 前面 (今天的分时点保持原顺序)
        merged = new_points + hist
        # 与 update_pnl 一致, 末位保留 500 条
        s = self._loop.state_store.load()
        s["pnl_history"] = merged[-500:]
        self._loop.state_store.save(s)
        print(f"[OK] 历史资金曲线回放: 写入 {len(new_points)} 个交易日点 "
              f"({start_date} ~ 昨天)", flush=True)

    # ------------------------------------------------------------------
    def _seed_historical_signals_if_empty(self, watch_stocks: List[str]) -> None:
        """启动时把 [SIM_HISTORY_START_DATE, today] 的策略信号回放进 state.signals

        - 仅在 state.signals 当前为空时跑 (避免重启后重复回放)
        - 调 backtest_engine.run_backtest 拿每只股票按其路由策略跑出的所有 buy/sell
          (撮合规则一致, 但本方法不写 trades, 只把信号 ts/code/side/strategy/reason
          按时间升序 append 到 state.signals)
        - 起始日期: 环境变量 SIM_HISTORY_START_DATE (默认 2026-04-01, 与 mock_positions
          初始持仓的 cost 日对齐)
        """
        # 已有信号 -> 不重放, 避免每次重启都重复
        s = self._loop.state_store.load()
        if s.get("signals"):
            return
        if not watch_stocks:
            return

        from datetime import date
        start_date = os.environ.get("SIM_HISTORY_START_DATE", "2026-04-01")
        end_date = date.today().strftime("%Y-%m-%d")

        # 延迟 import: 避免 backtest 依赖在不需要时强制加载
        try:
            from lib.backtest_engine import run_backtest
        except Exception as e:
            print(f"[WARN] 历史回放: import backtest_engine 失败 -> {e}", flush=True)
            return

        all_sigs: List[dict] = []
        for code in watch_stocks:
            strat = (self._router.per_stock.get(code) if self._router else None) \
                    or (self._router.default if self._router else "macd_1d")
            try:
                r = run_backtest(stock_code=code, strategy_name=strat,
                                 start_date=start_date, end_date=end_date)
            except Exception as e:
                print(f"[WARN] 历史回放 {code}/{strat} 异常: {e}", flush=True)
                continue
            if not r or not r.get("ok"):
                continue
            for sig in r.get("signals", []) or []:
                side = sig.get("side")
                if side not in ("buy", "sell"):
                    continue
                # 信号在 K_i 收盘出 -> 用日 K 收盘时刻 15:00:00 作为 ts (与盘中 ts 同格)
                d = sig.get("date")
                if not d:
                    continue
                all_sigs.append({
                    "ts":       f"{d}T15:00:00",
                    "code":     code,
                    "side":     side,
                    "strategy": strat,
                    "reason":   sig.get("reason", ""),
                })

        if not all_sigs:
            return

        all_sigs.sort(key=lambda x: x["ts"])
        # 与 append_signal 一致, 末位保留 100 条
        s = self._loop.state_store.load()
        s["signals"] = (s.get("signals") or []) + all_sigs
        s["signals"] = s["signals"][-100:]
        self._loop.state_store.save(s)
        print(f"[OK] 历史信号回放: 写入 {len(all_sigs)} 条 "
              f"({start_date} ~ {end_date}, {len(watch_stocks)} 只)", flush=True)

    # ------------------------------------------------------------------
    def clear_history(self) -> str:
        """清空 events / signals / orders / pnl_history (持仓不动)
        用于清掉之前测试遗留的非盘中脏数据
        """
        import json
        if not self._state_file.exists():
            return f"[ERROR] {self._state_file.name} 不存在"
        try:
            s = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            s = {}
        cleared = (len(s.get("events", [])) + len(s.get("signals", []))
                   + len(s.get("orders", [])) + len(s.get("pnl_history", [])))
        s["events"]      = []
        s["signals"]     = []
        s["orders"]      = []
        s["pnl_history"] = []
        s["today_pnl"]   = 0
        s["today_pnl_pct"] = 0
        s["_updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._state_file)
        return f"[OK] {self._state_file.name} 已清空 {cleared} 条历史 (events/signals/orders/pnl), 持仓保留"

    # ------------------------------------------------------------------
    def reset_positions(self) -> str:
        """重新读 config 并覆盖 state.positions (不动 events / signals / orders)"""
        import json
        if not self._state_file.exists():
            return f"[ERROR] {self._state_file.name} 不存在, 先启动一次"
        try:
            s = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            s = {}
        new_positions = build_positions_from_config(str(self._mock_config_file))
        s["positions"] = new_positions
        cfg = load_mock_config(self._mock_config_file)
        capital = float(cfg.get("capital", 1_000_000))
        # 记录初始本金 (重置时覆盖, 确保与配置一致)
        s["initial_capital"] = capital
        # 重置持仓后, 从总资金中扣除持仓成本, 得到实际可用现金
        total_cost = sum(
            float(p.get("cost", 0)) * int(p.get("volume", 0))
            for p in new_positions
        )
        s["capital"] = max(0, capital - total_cost)
        # 重置当日起始资产为当前总资产 (重置后 today_pnl = 0)
        total_assets = s["capital"] + sum(
            float(p.get("cost", 0)) * int(p.get("volume", 0))
            for p in new_positions
        )
        s["day_start_assets"] = total_assets
        s["today_pnl"] = 0.0
        s["today_pnl_pct"] = 0.0
        s["_updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._state_file)

        # 为所有持仓代码显式设置 execution_mode = "strategy"，确保卖出后仍显示在待入场
        _exec_mode_file = self._exec_mode_file
        try:
            import yaml as _yaml
            _exec_mode_file.parent.mkdir(parents=True, exist_ok=True)
            modes = {normalize_code(p.get("code", "")): "strategy" for p in new_positions if p.get("code")}
            _exec_mode_file.write_text(
                _yaml.safe_dump({"modes": modes}, allow_unicode=True),
                encoding="utf-8",
            )
        except Exception:
            pass

        return f"[OK] 重置持仓 -- 共 {len(new_positions)} 只, 来源 {self._mock_config_file.name}"


# ============================================================
# 引擎单例 (模拟盘 + 实盘各一个)
# ============================================================

# 模拟盘引擎单例
SIM_RUNNER = LiveSimRunner(
    plan_type="sim",
    state_file=str(OUTPUTS_LIVE_STATE),
    strategy_file=str(CONFIG_DIR / "strategies.yaml"),
    watch_pool_file=str(CONFIG_DIR / "watch_pool.yaml"),
    mock_config_file=str(CONFIG_DIR / "mock_positions.yaml"),
    dry_run_default=True,
)

# 实盘引擎单例
REAL_RUNNER = LiveSimRunner(
    plan_type="live",
    state_file=str(OUTPUTS_LIVE_STATE_REAL),
    strategy_file=str(CONFIG_DIR / "strategies_real.yaml"),
    watch_pool_file=str(CONFIG_DIR / "watch_pool_real.yaml"),
    mock_config_file=str(CONFIG_DIR / "mock_positions_real.yaml"),
    dry_run_default=False,
)

# ============================================================
# cli -- 不启动主循环, 只跑历史订单回填 (用法见 --help)
# ============================================================
if __name__ == "__main__":
    import argparse
    import sys
    # 直接跑 python lib/live_simulator.py 时, lib 不在 sys.path -- 把项目根加进去
    _PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    from lib.paths import setup_sys_path
    setup_sys_path()

    parser = argparse.ArgumentParser(
        description="LiveSimRunner cli -- 历史订单回填工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("用法:\n"
                "  python lib/live_simulator.py --backfill-orders\n"
                "        把 SIM_HISTORY_START_DATE (默认 2026-04-01) 至今的策略成交\n"
                "        写到 outputs/live/live_state.json/orders, 让 /review 流水卡有数据\n"
                "  python lib/live_simulator.py --backfill-orders --force\n"
                "        即使 orders 已有也强制覆盖 (重生成)\n"))
    parser.add_argument("--backfill-orders", action="store_true",
                        help="跑一遍回测引擎, 把成交流水写入 live_state.json/orders")
    parser.add_argument("--force", action="store_true",
                        help="即使 orders 已有也强制覆盖")
    args = parser.parse_args()

    if args.backfill_orders:
        log = seed_historical_orders(force=args.force)
        print(log)
        sys.exit(0)

    parser.print_help()
