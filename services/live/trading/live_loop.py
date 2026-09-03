# -*- coding: utf-8 -*-
# 23-CASE-A: 盘中全自动交易闭环主循环
"""
LiveLoop -- 盘中全自动交易闭环主循环

每隔 N 分钟跑一遍, 完成: 拉行情 -> 评估持仓 -> 跑信号 -> 风控审批 -> 下单 -> 推送

核心架构 (LangGraph 风格, 但简化为顺序循环, 因为每分钟级延迟比 LangGraph 启动开销重要):

    每分钟循环:
        1. health_check()          检查 miniQMT 连接 + 行情数据完整性
        2. update_positions()      拉最新持仓 + 当日盈亏
        3. check_circuit_breaker() 当日亏损是否触发熔断
        4. evaluate_stop_loss()    持仓股是否触发止损
        5. evaluate_signals()      候选股是否出现新信号
        6. risk_check()            风控审批 (Kris 规则)
        7. place_orders()          下单 (本 CASE live_trading.miniqmt_trader_v2)
        8. push_summary()          推送告警 (alert_router)
        9. save_state()            落盘 state (供 CEO 控制台读)

异常处理金字塔:
    L1 数据层异常 -> 跳过本轮, 下轮继续, 不告警 (网络抖动)
    L2 风控否决   -> 不下单, INFO 推送
    L3 订单失败   -> WARN 推送, 重试 1 次
    L4 系统级异常 -> CRITICAL 推送 + 暂停所有交易 (state.trading_status = "HALTED")
    L5 不可恢复   -> FATAL 推送 + 进程退出 + 等人工

注意:
    - 真正的实盘需要接 miniQMT, 在 dry-run 下用模拟数据 (适合教学/演示)
    - 信号评估这里可用 MACD/RSI 占位，实战可替换为自有选股 / 路由输出。
"""

from __future__ import annotations
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lib.paths import PROJECT_ROOT
sys.path.insert(0, str(PROJECT_ROOT))

from services.live.alerting.alert_router import AlertRouter
from lib.stock_utils import get_stock_info
from services.live.trading.state_store import StateStore


# ============================================================
# 数据来源 (dry-run 下用 xtdata + 模拟下单)
# ============================================================

class MarketDataProvider:
    """市场数据提供者 -- xtdata 拉真实数据"""

    def __init__(self):
        self._connected = False

    def connect(self):
        from xtquant import xtdata
        xtdata.connect()
        self._connected = True

    def get_latest_tick(self, stock_code: str) -> dict:
        """拉最新 tick (含 5 档盘口)"""
        from xtquant import xtdata
        if not self._connected:
            self.connect()
        ticks = xtdata.get_full_tick([stock_code])
        return ticks.get(stock_code, {})

    def get_recent_kline(self, stock_code: str, period: str = "5m",
                        count: int = 50) -> Optional[Any]:
        """拉最近 N 根 K 线 (用于算指标)"""
        import pandas as pd
        from xtquant import xtdata
        if not self._connected:
            self.connect()
        try:
            xtdata.download_history_data(stock_code, period=period,
                                         start_time="20250101", incrementally=True)
            data = xtdata.get_market_data_ex(
                field_list=["open", "high", "low", "close", "volume"],
                stock_list=[stock_code], period=period, count=count,
            )
            df = data.get(stock_code)
            if df is None or len(df) == 0:
                return None
            df = df.copy()
            df.index = pd.to_datetime(df.index)
            return df
        except Exception:
            return None


# ============================================================
# 信号评估 (简化版 MACD)
# ============================================================

def evaluate_macd_signal(df) -> str:
    """
    评估 MACD 信号
    返回: "buy" / "sell" / "hold"
    """
    import pandas as pd
    if df is None or len(df) < 30:
        return "hold"
    close = df["close"].astype(float)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()

    # 最新两根: 看是否金叉/死叉
    if len(dif) < 2:
        return "hold"
    prev = dif.iloc[-2] - dea.iloc[-2]
    curr = dif.iloc[-1] - dea.iloc[-1]
    if prev <= 0 and curr > 0:
        return "buy"
    if prev >= 0 and curr < 0:
        return "sell"
    return "hold"


# ============================================================
# 持仓与盈亏更新
# ============================================================

def update_positions_from_market(positions: List[dict],
                                 market: MarketDataProvider) -> List[dict]:
    """拉最新价更新持仓的市值 + 浮动盈亏"""
    updated = []
    for pos in positions:
        code = pos["code"]
        tick = market.get_latest_tick(code)
        cur_price = float(tick.get("lastPrice", pos.get("cost", 0)))
        volume = int(pos["volume"])
        cost = float(pos.get("cost", 0))
        mv = volume * cur_price
        pnl = (cur_price - cost) * volume
        pnl_pct = (cur_price - cost) / cost if cost > 0 else 0
        updated.append({
            **pos,
            "cur_price":   round(cur_price, 3),
            "market_value": round(mv, 2),
            "pnl":         round(pnl, 2),
            "pnl_pct":     round(pnl_pct, 4),
        })
    return updated


def calc_today_pnl(positions: List[dict], capital: float) -> tuple:
    """计算当日总盈亏 (元 + 百分比)"""
    total_pnl = sum(p.get("pnl", 0) for p in positions)
    total_pct = total_pnl / capital if capital > 0 else 0
    return round(total_pnl, 2), round(total_pct, 4)


# ============================================================
# 主循环
# ============================================================

class LiveTradingLoop:
    """
    实盘主循环 (默认 dry-run)

    用法:
        loop = LiveTradingLoop(watch_stocks=["600519.SH", "513100.SH"])
        loop.run_once()         # 跑一次
        loop.run_forever(60)    # 每 60 秒跑一次, 直到 Ctrl+C
    """

    def __init__(self,
                 watch_stocks: List[str],
                 capital: float = 1_000_000,
                 state_file: str = "outputs/live/live_state.json",
                 max_daily_loss_pct: float = -0.02,
                 dry_run: bool = True,
                 signal_evaluator: Optional[Callable[[str, "MarketDataProvider", float], dict]] = None,
                 engine_label: str = "?",
                 on_plan_executed: Optional[Callable[[dict], None]] = None):
        """
        signal_evaluator: 可选的信号评估器, 签名 (code, market, capital) -> dict
            返回字典 {"side": "buy"/"sell"/"hold", "strategy": str, "reason": str (可选)}
            不传 = 沿用默认 5min MACD 金叉/死叉 (兼容历史行为)
        engine_label: 日志标识, 如 "SIM" / "REAL"
        on_plan_executed: 可选回调, 交易计划信号真正成交(生成交易流水)后调用。
            签名 (signal: dict) -> None; 由装配层注入计划系统的成交处理器,
            引擎只负责成交后通知, 不感知计划/数据库细节。
        """
        self.watch_stocks = watch_stocks
        self.capital = capital
        self.dry_run = dry_run
        self.engine_label = engine_label
        self.max_daily_loss_pct = max_daily_loss_pct
        self.signal_evaluator = signal_evaluator
        self.on_plan_executed = on_plan_executed

        self.state_store = StateStore(state_file)
        self.market = MarketDataProvider()
        self.alert = AlertRouter(info_aggregate_seconds=300)

        # 初始化 state
        s = self.state_store.load()
        # 仅在首次创建或 capital 为空时不覆盖已有值, 保留交易后的实际可用资金
        if not s.get("capital"):
            s["capital"] = capital
        # 保留不变的初始本金, 用于计算累计盈亏和百分比
        if "initial_capital" not in s:
            s["initial_capital"] = capital
        # 当日起始资产快照, 用于计算当日盈亏 (首次启动 = 初始本金)
        if "day_start_assets" not in s:
            s["day_start_assets"] = capital
        s["watch_stocks"] = watch_stocks
        s["control"]["dry_run"] = dry_run
        s["control"]["max_daily_loss"] = max_daily_loss_pct
        self.state_store.save(s)

    # ------------------------------------------------------------------
    # 单次循环
    # ------------------------------------------------------------------
    def run_once(self) -> dict:
        """跑一次完整循环"""
        cycle_start = time.time()
        s = self.state_store.load()

        # 0) 检查 control.trading_status
        if s.get("trading_status") == "HALTED":
            self.alert.alert("WARN", "交易已熔断, 跳过本轮", source="loop")
            return {"action": "halted_skip"}
        if s.get("trading_status") == "PAUSED":
            self.alert.alert("INFO", "交易已暂停 (CEO 控制台暂停)", source="loop")
            return {"action": "paused_skip"}

        # 1) health_check
        try:
            self.market.connect()
            s["health"]["miniqmt_connected"] = True
            s["health"]["last_heartbeat"] = datetime.now().isoformat(timespec="seconds")
        except Exception as e:
            s["health"]["miniqmt_connected"] = False
            s["health"]["errors_24h"] = s["health"].get("errors_24h", 0) + 1
            self.alert.alert("CRITICAL", "miniQMT 连接失败",
                             message=str(e), source="health")
            self.state_store.save(s)
            return {"action": "health_fail"}

        # 2) 更新持仓 + 盈亏
        # 累计盈亏 = 当前总资产 - 初始本金 (包含所有已实现 + 未实现盈亏)
        positions = s.get("positions", [])
        if positions:
            positions = update_positions_from_market(positions, self.market)
            s["positions"] = positions
        total_assets = s.get("capital", 0) + sum(
            p.get("market_value", 0) for p in positions
        )
        initial = s.get("initial_capital", self.capital)
        if initial <= 0:
            initial = self.capital
        today_pnl = total_assets - initial
        today_pnl_pct = today_pnl / initial
        s["today_pnl"] = round(today_pnl, 2)
        s["today_pnl_pct"] = round(today_pnl_pct, 4)
        s["pnl_history"] = s.get("pnl_history", [])
        s["pnl_history"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "pnl": s["today_pnl"], "pnl_pct": s["today_pnl_pct"],
        })
        s["pnl_history"] = s["pnl_history"][-500:]

        # 2.5) 应急强制卖出: 最高优先级, 在熔断检查之前立即执行
        # CEO 手动触发的紧急卖出必须不受熔断限制, 执行后重新计算 PnL
        control = s.get("control", {})
        force_clear_all = bool(control.get("force_clear_all", False))
        force_sell_codes = list(control.get("force_sell_codes") or [])
        force_codes = set(force_sell_codes)
        if force_clear_all:
            force_codes.update({p.get("code") for p in positions if p.get("code")})
        if force_codes:
            # 生成强制卖出信号
            force_signals = []
            for code in sorted(force_codes):
                reason = "CEO 控制台: 一键清仓" if force_clear_all and code in force_sell_codes else (
                    "CEO 控制台: 一键清仓" if force_clear_all else "CEO 控制台: 强制卖出"
                )
                force_signals.append({
                    "code": code,
                    "side": "sell",
                    "strategy": "force_sell",
                    "reason": reason,
                    "percent": 1.0,
                })
            control["force_clear_all"] = False
            control["force_sell_codes"] = []
            s["control"] = control
            self.alert.alert(
                "CRITICAL" if force_clear_all else "WARN",
                f"[{self.engine_label}] 应急卖出触发: {len(force_signals)} 只",
                message=", ".join(sorted(force_codes)),
                source="control",
            )
            # 立即执行强制卖出 (不受后续熔断限制)
            s["orders"] = s.get("orders", [])
            for sig in force_signals:
                order_result = self._handle_signal(s, sig)
                if "strategy" not in order_result and sig.get("strategy"):
                    order_result["strategy"] = sig["strategy"]
                if sig.get("reason"):
                    order_result["reason"] = sig.get("reason", "")
                # 只有真正成交(下达委托)的才计入成交流水
                if order_result.get("status") in ("dry_run", "submitted"):
                    s["orders"].append(order_result)
            # 强制卖出后重新计算累计盈亏
            positions = s.get("positions", [])
            if positions:
                positions = update_positions_from_market(positions, self.market)
                s["positions"] = positions
            total_assets = s.get("capital", 0) + sum(
                p.get("market_value", 0) for p in positions
            )
            initial = s.get("initial_capital", self.capital)
            if initial <= 0:
                initial = self.capital
            s["today_pnl"] = round(total_assets - initial, 2)
            s["today_pnl_pct"] = round(s["today_pnl"] / initial, 4) if initial > 0 else 0

        # 3) 熔断检查 (仅对策略/交易计划信号生效, 强制卖出已在上面处理)
        if s.get("today_pnl_pct", 0) <= self.max_daily_loss_pct:
            s["trading_status"] = "HALTED"
            self.alert.alert(
                "CRITICAL", "触发当日亏损熔断",
                message=f"今日累计盈亏 {s['today_pnl_pct']:.2%}, "
                        f"已跌破熔断线 {self.max_daily_loss_pct:.2%}",
                source="circuit_breaker",
            )
            self.state_store.save(s)
            return {"action": "circuit_breaker"}

        new_signals = []

        # 4) 评估信号 (默认对 watch 池每只算 MACD; 注入了 signal_evaluator 则按 evaluator 派发)
        for code in self.watch_stocks:
            if self.signal_evaluator is not None:
                # 外部注入的信号路由器: 由 evaluator 自己决定用哪个策略
                try:
                    result = self.signal_evaluator(code, self.market, self.capital)
                except Exception as e:
                    self.alert.alert("WARN", f"signal_evaluator 异常 {code}",
                                     message=str(e), source="zoe")
                    continue
                if not result:
                    continue
                side = result.get("side", "hold")
                if side == "hold":
                    continue
                sig = {
                    "code":     code,
                    "side":     side,
                    "strategy": result.get("strategy", "unknown"),
                    "reason":   result.get("reason", ""),
                    "percent":  result.get("percent"),
                    # 透传交易计划信号元数据, 供成交后定位并标记条件已触发
                    "_plan_id": result.get("_plan_id"),
                    "_plan_cond_type": result.get("_plan_cond_type"),
                    "_plan_cond_index": result.get("_plan_cond_index"),
                    # 加仓条件的新目标占比: 成交后由计划系统持久化更新目标仓位
                    "_plan_new_target_ratio": result.get("_plan_new_target_ratio"),
                }
            else:
                df = self.market.get_recent_kline(code, period="5m", count=50)
                side = evaluate_macd_signal(df)
                if side == "hold":
                    continue
                sig = {"code": code, "side": side, "strategy": "macd_5min"}
            new_signals.append(sig)

        # 注意: signals / orders / events 都先攒在内存 s 里, 第 6 步统一一次 save 落盘
        # -- 不能用 append_signal / append_order, 否则它们 load->改->save, 会被第 6 步的
        # save(s) 用旧快照整体覆盖回去, 导致 signals / orders 写完即丢
        signal_refs = []  # 本轮新写入 signals 的记录引用, 供成交后回填订单结果
        if new_signals:
            s["signals"] = s.get("signals", [])
            # 去重: 同一 (code, side, strategy) 在 60 秒内只保留一条, 避免试算重复点击产生重复信号
            from datetime import timedelta
            recent_cutoff = datetime.now() - timedelta(seconds=60)
            existing_keys = set()
            for old in s["signals"]:
                try:
                    ts = datetime.fromisoformat(old.get("ts", ""))
                    if ts >= recent_cutoff:
                        key = (old.get("code"), old.get("side"), old.get("strategy", ""))
                        existing_keys.add(key)
                except Exception:
                    pass
            deduped = 0
            deduped_signals = []
            for sig in new_signals:
                key = (sig.get("code"), sig.get("side"), sig.get("strategy", ""))
                if key in existing_keys:
                    deduped += 1
                    continue
                existing_keys.add(key)
                deduped_signals.append(sig)
                sig_entry = {
                    **sig,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                }
                s["signals"].append(sig_entry)
                signal_refs.append(sig_entry)
                self.alert.alert(
                    "INFO", f"[{self.engine_label}] 信号触发 -> {sig['side']} {sig['code']} [{sig.get('strategy','')}]",
                    source="zoe",
                )
            if deduped:
                self.alert.alert("INFO", f"跳过 {deduped} 条重复信号 (60s 内同股同方向同策略)", source="zoe")
            new_signals = deduped_signals  # 下游下单只处理去重后的信号
            s["signals"] = s["signals"][-100:]

        # 5) 风控 + 下单
        s["orders"] = s.get("orders", [])
        for sig, sig_entry in zip(new_signals, signal_refs):
            order_result = self._handle_signal(s, sig)
            # 把触发该订单的策略名一起记录, 便于复盘
            if "strategy" not in order_result and sig.get("strategy"):
                order_result["strategy"] = sig["strategy"]
            # 把本次订单结果回填到对应的 signals 记录: 成功(dry_run/submitted)或
            # 被阻断(rejected_t1/资金不足/无持仓/paused/待确认)及原因, 便于查询复盘
            sig_entry["order_status"] = order_result.get("status")
            if order_result.get("reason"):
                sig_entry["order_reason"] = order_result.get("reason")
            # 只有真正成交(下达委托)的才计入成交流水;
            # 被阻断/拒绝的信号不写 orders, 避免每分钟重复的失败信号把 orders 刷满、挤掉真实成交
            if order_result.get("status") in ("dry_run", "submitted"):
                s["orders"].append({
                    **order_result,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                })
        s["orders"] = s["orders"][-1000:]

        # 6) 落盘 state (本轮所有改动: positions/today_pnl/pnl_history/health/signals/orders/events 一锅端)
        s["events"] = s.get("events", [])
        s["events"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": "loop_cycle",
            "signal_count": len(new_signals),
            "duration_ms": int((time.time() - cycle_start) * 1000),
        })
        s["events"] = s["events"][-200:]
        self.state_store.save(s)

        return {
            "action":      "cycle_done",
            "duration_ms": int((time.time() - cycle_start) * 1000),
            "new_signals": len(new_signals),
        }

    def _add_position_after_buy(self, state: dict, code: str,
                                 quantity: int, price: float,
                                 name: str = "") -> None:
        """买入成交后往 state.positions 添加/增加虚拟持仓 (模拟盘用)。"""
        positions = state.get("positions", [])
        today_str = date.today().isoformat()
        pos = next((p for p in positions if p.get("code") == code), None)
        if pos:
            old_vol = int(pos.get("volume", 0))
            old_cost = float(pos.get("cost", 0))
            new_vol = old_vol + quantity
            new_cost = round((old_cost * old_vol + price * quantity) / new_vol, 4)
            pos["volume"] = new_vol
            pos["cost"] = new_cost
            pos["cur_price"] = price
            pos["market_value"] = round(new_vol * price, 2)
            pos["pnl"] = round((price - new_cost) * new_vol, 2)
            pos["pnl_pct"] = round((price / new_cost - 1) if new_cost > 0 else 0.0, 4)
            # 加仓后更新最近买入日期为今天, 用于 T+1 限制
            pos["buy_date"] = today_str
            # 若之前没有名称, 用新传入名称补齐
            if not pos.get("name") and name:
                pos["name"] = name
        else:
            positions.append({
                "code":         code,
                "name":         name,
                "volume":       quantity,
                "cost":         price,
                "cur_price":    price,
                "market_value": round(quantity * price, 2),
                "pnl":          0.0,
                "pnl_pct":      0.0,
                "buy_date":     today_str,
            })
        state["positions"] = positions

    def _update_positions_after_sell(self, state: dict, code: str,
                                     quantity: int, price: float) -> None:
        """卖出成交后同步减少/移除本地持仓, 让模拟盘/实盘 state.positions 实时反映清仓。"""
        positions = state.get("positions", [])
        if not positions:
            return
        updated = []
        for p in positions:
            if p.get("code") != code:
                updated.append(p)
                continue
            vol = int(p.get("volume", 0))
            remain = max(0, vol - quantity)
            if remain > 0:
                new_p = dict(p)
                new_p["volume"] = remain
                # 用卖出成交价刷新市值和盈亏, 与持仓表展示保持一致
                new_p["market_value"] = round(remain * price, 2)
                cost = float(new_p.get("cost", 0))
                new_p["pnl"] = round((price - cost) * remain, 2)
                updated.append(new_p)
            # remain == 0 时直接剔除, 表示已清仓
        state["positions"] = updated

    def _handle_signal(self, state: dict, signal: dict) -> dict:
        """处理一个信号: 风控 -> 下单 -> 推送"""
        code = signal["code"]
        side = signal["side"]
        tick = self.market.get_latest_tick(code)
        price = float(tick.get("lastPrice", 0))
        if price <= 0:
            # 非盘中时段无实时tick，回退到最新日K收盘价 (试算场景)
            try:
                from lib.backtest_data import load_daily_kline
                from datetime import timedelta
                end_date = date.today().strftime("%Y-%m-%d")
                start_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
                df = load_daily_kline(code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    price = float(df.iloc[-1]["close"])
            except Exception:
                pass
        if price <= 0:
            return {"code": code, "side": side, "status": "rejected",
                    "reason": "拿不到价格", "ts": datetime.now().isoformat()}

        # 仓位比例: 交易计划可能带 percent, 否则按默认单笔不超过总资金 10%
        plan_percent = signal.get("percent")
        positions = state.get("positions", [])
        pos = next((p for p in positions if p.get("code") == code), None)

        if side == "buy":
            ratio = plan_percent if isinstance(plan_percent, (int, float)) and plan_percent > 0 else 0.10
            # 使用 state 中追踪的实际可用资金, 而非初始 capital
            available_cash = state.get("capital", self.capital)
            if available_cash <= 0:
                return {"code": code, "side": side, "status": "rejected",
                        "reason": "可用资金不足", "ts": datetime.now().isoformat()}
            max_amount = available_cash * ratio
            quantity = int(max_amount / price / 100) * 100
            # 如果按仓位比例算不出 1 手, 说明资金不够买 1 手, 拒绝下单
            if quantity < 100:
                return {"code": code, "side": side, "status": "rejected",
                        "reason": f"可用资金不足以买入 1 手 ({price:.2f} 元/股, 需 {price*100:.2f} 元)",
                        "ts": datetime.now().isoformat()}
        else:  # sell
            if pos and int(pos.get("volume", 0) or 0) > 0:
                # A股 T+1 规则: 当日买入的股票不可卖出
                if pos.get("buy_date") == date.today().isoformat():
                    self.alert.alert(
                        "INFO", f"[{self.engine_label}] sell 信号跳过 (T+1限制, 当日买入): {code}",
                        source="loop",
                    )
                    return {"code": code, "side": side, "status": "rejected_t1",
                            "reason": "T+1规则: 当日买入不可卖出",
                            "ts": datetime.now().isoformat()}
                ratio = plan_percent if isinstance(plan_percent, (int, float)) and plan_percent > 0 else 1.0
                quantity = int(int(pos.get("volume", 0)) * ratio / 100) * 100
                if quantity == 0:
                    quantity = int(pos.get("volume", 0))  # 不足一手则全卖
            else:
                # 无持仓但收到 sell 信号：跳过 (可能是策略信号覆盖了监控池中未持有的票)
                self.alert.alert("INFO", f"[{self.engine_label}] sell 信号跳过 (无持仓): {code}", source="loop")
                return {"code": code, "side": side, "status": "skipped_no_position",
                        "reason": "无持仓", "ts": datetime.now().isoformat()}

        amount = quantity * price

        # control.pause_buying 拦截
        if side == "buy" and state.get("control", {}).get("pause_buying"):
            self.alert.alert("INFO", "买入被 CEO 控制台暂停",
                             message=f"{code} {quantity}股 @ {price:.2f}",
                             source="control")
            return {"code": code, "side": side, "quantity": quantity,
                    "price": price, "status": "paused_by_ceo"}

        # 交易计划手动执行: 条件触发但需用户确认, 只记录信号/订单, 不下单
        if signal.get("strategy") == "plan" and not signal.get("_plan_auto_trade", True):
            self.alert.alert("INFO", f"交易计划待确认: {side} {code}",
                             message=f"{quantity}股 @ {price:.2f}, 原因: {signal.get('reason', '')}",
                             source="plan")
            return {"code": code, "side": side, "quantity": quantity,
                    "price": price, "amount": amount, "status": "pending_manual",
                    "reason": signal.get("reason", ""),
                    "ts": datetime.now().isoformat()}

        # 下单 (dry-run / real)
        if self.dry_run:
            self.alert.alert(
                "INFO", f"[DRY-RUN] 下单 {side} {code} {quantity}股 @ {price:.2f}",
                source="trader",
            )
            result = {"code": code, "side": side, "quantity": quantity,
                      "price": price, "amount": amount, "status": "dry_run",
                      "ts": datetime.now().isoformat()}
            if side == "sell":
                self._update_positions_after_sell(state, code, quantity, price)
                # 卖出后可用资金增加
                state["capital"] = state.get("capital", self.capital) + amount
            else:
                # 买入时查询名称写入持仓, 避免前端显示空名称
                name = get_stock_info(code).get("name", "")
                self._add_position_after_buy(state, code, quantity, price, name=name)
                # 买入后可用资金减少 (不用 max(0, ...) 截断, 确保余额精确)
                new_cash = state.get("capital", self.capital) - amount
                if new_cash < 0:
                    # 防御性兜底: 若余额不足应已在前面拒绝, 此处记录异常但不抹成 0
                    self.alert.alert(
                        "WARN", f"买入后余额为负, 请检查资金逻辑: {code} {quantity}股 @ {price:.2f}",
                        source="trader",
                    )
                state["capital"] = round(new_cash, 2)
            # 模拟盘成交(生成交易流水)后通知计划系统标记条件已触发
            self._notify_plan_executed(signal)
            return result

        # 真实下单 (本 CASE 内 live_trading/miniqmt_trader_v2)
        try:
            from services.live.trading.miniqmt_trader_v2 import MiniQMTTraderV2
            trader = MiniQMTTraderV2(
                qmt_path=os.environ["QMT_PATH"],
                account_id=os.environ["ACCOUNT_ID"],
                enable_heartbeat=False,
            )
            trader.connect()
            if side == "buy":
                order_id = trader.buy(code, quantity, price=price,
                                      strategy_name="live_loop")
            else:
                order_id = trader.sell(code, quantity, price=price,
                                       strategy_name="live_loop")
            trader.disconnect()

            if order_id:
                self.alert.alert(
                    "INFO", f"实盘下单成功 {side} {code}",
                    message=f"委托编号 {order_id}, {quantity}股 @ {price:.2f}",
                    source="trader",
                )
                result = {"code": code, "side": side, "quantity": quantity,
                          "price": price, "amount": amount, "status": "submitted",
                          "order_id": order_id, "ts": datetime.now().isoformat()}
            else:
                self.alert.alert("WARN", f"实盘下单失败 {code}", source="trader")
                result = {"code": code, "side": side, "quantity": quantity,
                          "price": price, "status": "failed",
                          "ts": datetime.now().isoformat()}
        except Exception as e:
            self.alert.alert("CRITICAL", f"下单异常 {code}",
                             message=str(e), source="trader")
            result = {"code": code, "side": side, "status": "exception",
                      "reason": str(e), "ts": datetime.now().isoformat()}

        # 成交后同步更新本地持仓与资金 (实盘)
        if result["status"] == "submitted":
            if side == "sell":
                self._update_positions_after_sell(state, code, quantity, price)
                state["capital"] = state.get("capital", self.capital) + amount
            else:
                new_cash = state.get("capital", self.capital) - amount
                if new_cash < 0:
                    self.alert.alert(
                        "WARN", f"买入后余额为负, 请检查资金逻辑: {code} {quantity}股 @ {price:.2f}",
                        source="trader",
                    )
                state["capital"] = round(new_cash, 2)
            # 实盘委托成功后通知计划系统标记条件已触发
            self._notify_plan_executed(signal)
        return result

    def _notify_plan_executed(self, signal: dict) -> None:
        """交易计划信号真正成交(生成交易流水)后, 通知计划系统标记条件已触发。

        仅在信号携带计划元数据(_plan_id)且注册了 on_plan_executed 钩子时生效。
        引擎只负责成交后的通知, 不感知计划/数据库细节; 实际标记逻辑
        由装配层注入的处理器(on_plan_signal_executed)实现。
        """
        if self.on_plan_executed is None or signal.get("_plan_id") is None:
            return
        try:
            self.on_plan_executed(signal)
        except Exception as e:
            self.alert.alert("WARN", "计划条件标记失败",
                             message=str(e), source="plan")

    # ------------------------------------------------------------------
    # 长跑模式
    # ------------------------------------------------------------------
    def run_forever(self, interval_seconds: int = 60):
        """每隔 N 秒跑一次, 直到 Ctrl+C"""
        self.alert.alert("INFO", "实盘主循环启动",
                         message=f"watch={self.watch_stocks}, "
                                 f"interval={interval_seconds}s, dry_run={self.dry_run}",
                         source="loop")
        try:
            while True:
                t0 = time.time()
                result = self.run_once()
                # 等到下一次触发
                elapsed = time.time() - t0
                if elapsed < interval_seconds:
                    time.sleep(interval_seconds - elapsed)
        except KeyboardInterrupt:
            self.alert.alert("INFO", "实盘主循环退出 (Ctrl+C)", source="loop")
            self.alert.shutdown()


# ============================================================
# CLI
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="盘中全自动交易闭环")
    parser.add_argument("--stocks", default="600519.SH,513100.SH",
                        help="监控股票池, 逗号分隔")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--interval", type=int, default=60,
                        help="循环间隔秒, 默认 60")
    parser.add_argument("--once", action="store_true", help="只跑一次")
    parser.add_argument("--state-file", default="outputs/live/live_state.json")
    args = parser.parse_args()

    stocks = [s.strip() for s in args.stocks.split(",") if s.strip()]
    loop = LiveTradingLoop(
        watch_stocks=stocks,
        capital=args.capital,
        state_file=args.state_file,
        dry_run=os.environ.get("TRADER_DRY_RUN", "1") == "1",
    )

    if args.once:
        result = loop.run_once()
        print(f"\n[完成] {result}")
        print(f"\nstate 落盘: {args.state_file}")
    else:
        loop.run_forever(args.interval)


if __name__ == "__main__":
    main()
