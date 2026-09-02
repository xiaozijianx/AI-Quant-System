# -*- coding: utf-8 -*-
# 复盘归因路由 -- REST (薄路由)
"""
POST /api/review/trade_record         -- 加载交割单 (CSV / 模拟盘 state.json) + 成本汇总
POST /api/review/brinson              -- Brinson 三因子归因 (示例数据)
POST /api/review/brinson_real         -- Brinson 三因子归因 (sim/real 真实持仓)
GET  /api/review/wf_strategies        -- 列出 Walk-Forward 可选策略 + 默认参数
POST /api/review/walk_forward         -- Walk-Forward 滚动窗口验证 + 过拟合检测
GET  /api/review/registry             -- 读策略生命周期 registry
POST /api/review/lifecycle_eval       -- 跑生命周期评估
POST /api/review/lifecycle_sim_eval   -- 用模拟盘/实盘真实数据评估

业务实现(实盘 NAV 持久化 / Walk-Forward 元数据与参数解析)已下沉 services/review/。
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body

from lib.paths import (
    setup_sys_path, OUTPUTS_DIR, OUTPUTS_LIVE_STATE, OUTPUTS_EVOLVE_REGISTRY,
)
setup_sys_path()

from services.review.core import (
    REAL_PNL_HISTORY_PATH, _load_real_pnl_history, _save_real_pnl_history, _record_real_pnl_snapshot,
    _WF_STRATEGIES, _wf_strategy_meta, _wf_param_grid_to_text, _coerce_param_value,
    _check_extra, _parse_wf_param_grid,
)

router = APIRouter()

@router.get("/trade_csv_files")
@router.get("/trade_csv_files/")
def trade_csv_files_endpoint():
    """列出 data 目录下所有可用的交割单 CSV (用于前端下拉选择).

    response: {
        "ok":      true,
        "default": "<absolute path>",      # 默认选中那份 (最新区间)
        "files":   [{name, path, label}, ...],
    }
    """
    try:
        from services.review.attribution.trade_record import list_available_csvs, DEFAULT_CSV_PATH
        files = list_available_csvs()
        return {
            "ok":      True,
            "default": str(DEFAULT_CSV_PATH),
            "files":   files,
        }
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}

@router.post("/trade_record")
@router.post("/trade_record/")
def trade_record_endpoint(payload: dict = Body({})):
    """加载交易记录 (CSV 交割单 / 模拟盘 state.json) + 自动算成本汇总.

    body: {
        "source":   "csv" | "sim" (默认 "csv"),
        "csv_path": 可选, 默认走项目内置 data/历史成交*.csv
    }

    response: {
        "ok":           true,
        "source":       "csv",
        "source_label": "CSV (历史成交_xxx.csv)",
        "real_cost":    true,                 # CSV 是真实手续费, sim 是估算
        "rows":         [...],                # 标准化订单明细
        "summary":      {n, commission, stamp_duty, transfer_fee, total_cost, amount, bps}
    }
    """
    source = str(payload.get("source") or "csv").strip()
    try:
        from services.review.attribution.trade_record import (
            load_from_csv, load_from_state_json, add_costs,
            DEFAULT_CSV_PATH, DEFAULT_SIM_STATE,
        )
        if source == "csv":
            csv_path = str(payload.get("csv_path") or DEFAULT_CSV_PATH)
            p = Path(csv_path)
            if not p.exists():
                return {"ok": False, "message": f"CSV 文件不存在: {p.name}"}
            df = load_from_csv(csv_path)
            source_label = f"CSV ({p.name})"
            real_cost = True
        elif source == "sim":
            state_p = Path(DEFAULT_SIM_STATE)
            if not state_p.exists():
                return {"ok": False, "message": "模拟盘 live_state.json 还没生成, 模拟盘可能未启动"}
            df = load_from_state_json(str(state_p))
            df = add_costs(df) if not df.empty else df
            source_label = f"模拟盘 ({state_p.name})"
            real_cost = False
        else:
            return {"ok": False, "message": f"未知数据源: {source}"}

        # CSV 解析失败 (文件存在但内容空 / 格式错) -- 这是真错误
        if df.empty and source == "csv":
            return {"ok": False, "message": "CSV 解析后为空, 请检查文件格式"}

        # sim 模式 + orders 空 -- 不是错误, 跑一笔模拟下单才会有 orders. 返回 ok=True 让前端展示友好提示
        if df.empty and source == "sim":
            return {
                "ok":           True,
                "source":       source,
                "source_label": source_label,
                "real_cost":    real_cost,
                "rows":         [],
                "summary":      {"n": 0, "commission": 0.0, "stamp_duty": 0.0,
                                 "transfer_fee": 0.0, "total_cost": 0.0,
                                 "amount": 0.0, "bps": 0.0},
                "empty_reason": "模拟盘当前没有订单流水 (live_state.json 里 orders 字段为空). "
                                "跑一笔模拟下单后这里会显示订单明细 + 成本核算. "
                                "下方 Brinson 归因用的是当前持仓快照, 不依赖订单流水, 不影响运行.",
            }

        # NaN -> 0 + float 化, 让前端 JSON 不爆
        for col in ("price", "amount", "commission", "stamp_duty",
                    "transfer_fee", "settle_fee", "total_cost"):
            if col in df.columns:
                df[col] = df[col].fillna(0).astype(float)
        rows = df.to_dict(orient="records")

        amount_sum = float(df["amount"].sum()) if "amount" in df else 0.0
        total_cost_sum = float(df["total_cost"].sum()) if "total_cost" in df else 0.0
        summary = {
            "n":            int(len(df)),
            "commission":   float(df["commission"].sum()) if "commission" in df else 0.0,
            "stamp_duty":   float(df["stamp_duty"].sum()) if "stamp_duty" in df else 0.0,
            "transfer_fee": float(df["transfer_fee"].sum()) if "transfer_fee" in df else 0.0,
            "total_cost":   total_cost_sum,
            "amount":       amount_sum,
            "bps":          (total_cost_sum / amount_sum * 10000) if amount_sum > 0 else 0.0,
        }
        return {
            "ok":           True,
            "source":       source,
            "source_label": source_label,
            "real_cost":    real_cost,
            "rows":         rows,
            "summary":      summary,
        }
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}

@router.post("/brinson")
def brinson(payload: dict = Body({})):
    from services.review.attribution.brinson import brinson_attribution

    # demo 数据 (跟 24章 brinson.py demo 一致)
    portfolio_weights = {
        "通信": 0.30, "电子": 0.25, "电力设备": 0.20,
        "国防军工": 0.10, "有色金属": 0.10, "银行": 0.05,
    }
    benchmark_weights = {
        "通信": 0.05, "电子": 0.10, "电力设备": 0.08,
        "国防军工": 0.05, "有色金属": 0.06, "银行": 0.18,
        "食品饮料": 0.15, "医药生物": 0.12, "其他": 0.21,
    }
    benchmark_returns = {
        "通信": 0.097, "电子": 0.056, "电力设备": 0.014,
        "国防军工": 0.008, "有色金属": 0.048, "银行": -0.012,
        "食品饮料": -0.026, "医药生物": 0.001, "其他": -0.008,
    }
    portfolio_returns = {
        "通信": 0.115, "电子": 0.072, "电力设备": 0.020,
        "国防军工": 0.015, "有色金属": 0.060, "银行": 0.005,
    }

    result = brinson_attribution(
        portfolio_weights, benchmark_weights,
        portfolio_returns, benchmark_returns,
    )

    by_industry = []
    if hasattr(result, "by_industry"):
        df = result.by_industry
        for ind, row in df.iterrows():
            by_industry.append({
                "industry":    ind,
                "Wp":          float(row.get("Wp", 0)),
                "Wb":          float(row.get("Wb", 0)),
                "Rp":          float(row.get("Rp", 0)),
                "Rb":          float(row.get("Rb", 0)),
                "allocation":  float(row.get("allocation", 0)),
                "selection":   float(row.get("selection", 0)),
                "interaction": float(row.get("interaction", 0)),
                "total":       float(row.get("total", 0)),
            })

    return {
        "portfolio_return":   result.portfolio_return,
        "benchmark_return":   result.benchmark_return,
        "excess_return":      result.excess_return,
        "allocation_effect":  result.allocation_effect,
        "selection_effect":   result.selection_effect,
        "interaction_effect": result.interaction_effect,
        "by_industry":        by_industry,
    }

@router.post("/brinson_real")
@router.post("/brinson_real/")
def brinson_real(payload: dict = Body({})):
    """真实数据 Brinson 归因 (申万一级 + 沪深300)

    body: {
        "start":     "YYYY-MM-DD" 区间起始 (含, 默认 2026-04-01),
        "end":       "YYYY-MM-DD" 区间结束 (含, 默认今天),
        "benchmark": "沪深300" (V1 只支持这一个),
        "source":    数据源:
                     - "sim"  (默认): 模拟盘 live_state.json 当前持仓快照
                     - "real":        miniQMT 实盘账户当前持仓 (只读)
                     - "csv":         CSV 交割单流水 (mark-to-market 期末市值)
        "csv_path":  source='csv' 时的 CSV 路径 (可选, 默认走 data/历史成交*.csv)
    }
    """
    from datetime import date
    start = str(payload.get("start") or "2026-04-01").strip()
    end = str(payload.get("end") or date.today().isoformat()).strip()
    benchmark = str(payload.get("benchmark") or "沪深300").strip()
    source = str(payload.get("source") or "sim").strip()

    try:
        if source == "csv":
            from lib.brinson_real import compute_brinson_from_trades
            from services.review.attribution.trade_record import DEFAULT_CSV_PATH
            csv_path = str(payload.get("csv_path") or DEFAULT_CSV_PATH)
            return compute_brinson_from_trades(
                csv_path=csv_path, start=start, end=end, benchmark=benchmark,
            )
        from lib.brinson_real import compute_real_brinson
        return compute_real_brinson(start=start, end=end,
                                    benchmark=benchmark, source=source)
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}

@router.post("/industry_map_refresh")
@router.post("/industry_map_refresh/")
def industry_map_refresh(payload: dict = Body({})):
    """强制重建申万一级行业字典 cache (默认 7 天 TTL, 可手动刷新)"""
    try:
        from lib.brinson_real import build_industry_map
        data = build_industry_map(force_refresh=True)
        return {
            "ok": True,
            "built_at":   data.get("built_at"),
            "sw1_count":  data.get("sw1_count"),
            "hs300_count": len(data.get("hs300") or []),
            "message": f"已重建申万一级字典: {data.get('sw1_count')} 个一级行业, "
                       f"沪深300 {len(data.get('hs300') or [])} 只成分股",
        }
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}

@router.get("/wf_strategies")
def wf_strategies():
    """列出 Walk-Forward 可选策略 + 默认参数 (供前端下拉初始化)"""
    out = []
    for key, meta in _WF_STRATEGIES.items():
        out.append({
            "key":            key,
            "label":          meta["label"],
            "description":    meta["description"],
            "param_cols":     list(meta["param_cols"]),
            "param_text_hint": ",".join(meta["param_cols"]),
            "defaults_text":  _wf_param_grid_to_text(key, meta["defaults"]),
            "defaults_count": len(meta["defaults"]),
        })
    return {"ok": True, "strategies": out}

@router.post("/walk_forward")
@router.post("/walk_forward/")
def walk_forward_endpoint(payload: dict = Body({})):
    """Walk-Forward 滚动窗口验证 + 过拟合检测

    body: {
        "code":       "600519.SH" (默认茅台),
        "count":      800           (回望多少根日 K, 默认 800),
        "train":      120           (训练窗口, 默认 120),
        "test":       60            (评估窗口, 默认 60),
        "strategy":   "double_ma" | "bollinger" | "rsi" | "donchian" (默认 double_ma),
        "param_grid": 数组或多行文本 (按所选策略的 param_cols 顺序, 留空用默认),
    }

    返回:
        ok / code / name / params / summary / windows / verdict / verdict_text
        - summary.overfit_score: < 0.3 鲁棒, 0.3~0.7 中度过拟合, > 0.7 严重过拟合
        - summary.is_oos_ratio:  接近 1.0 训练/评估表现一致, < 0.5 严重过拟合
    """
    import time as _time

    code = str(payload.get("code") or "600519.SH").strip()
    strategy = str(payload.get("strategy") or "double_ma").strip()
    if strategy not in _WF_STRATEGIES:
        return {"ok": False,
                "message": f"未知策略 {strategy}, 可选: {list(_WF_STRATEGIES.keys())}"}
    try:
        count = max(int(payload.get("count") or 800), 100)
        train_window = max(int(payload.get("train") or 120), 20)
        test_window = max(int(payload.get("test") or 60), 5)
    except (TypeError, ValueError):
        return {"ok": False, "message": "count/train/test 必须为整数"}
    if count < train_window + test_window:
        return {"ok": False,
                "message": f"count={count} 不足, 至少需要 {train_window + test_window}"}

    param_grid, pg_err = _parse_wf_param_grid(strategy, payload.get("param_grid"))
    if pg_err:
        return {"ok": False, "message": f"param_grid 错误: {pg_err}"}

    # 加载日 K (优先 MySQL, fallback xtdata)
    try:
        from lib.backtest_data import load_daily_kline, get_stock_name
        df_full = load_daily_kline(code)
    except Exception as e:
        return {"ok": False, "message": f"加载 {code} K 线失败: {type(e).__name__}: {e}"}
    if df_full is None or len(df_full) == 0:
        return {"ok": False, "message": f"加载 {code} K 线为空"}
    df = df_full.tail(count).copy()
    if len(df) < train_window + test_window:
        return {"ok": False,
                "message": (f"实际拿到 {len(df)} 行 < 训练 {train_window} + 评估 {test_window}, "
                            f"加大 count 或 减小 train/test")}

    # 解析策略函数
    try:
        import services.review.parameter_tuning.walk_forward as _wf_mod
        from services.review.parameter_tuning.walk_forward import walk_forward_analysis
        strategy_fn = getattr(_wf_mod, _WF_STRATEGIES[strategy]["fn_name"])
    except Exception as e:
        return {"ok": False, "message": f"无法 import walk_forward 模块/策略: {e}"}

    oos_warmup = int(_WF_STRATEGIES[strategy].get("oos_warmup", 0) or 0)

    t0 = _time.time()
    try:
        report = walk_forward_analysis(
            df, strategy_fn, param_grid,
            train_window=train_window, test_window=test_window,
            oos_warmup=oos_warmup,
        )
    except Exception as e:
        return {"ok": False, "message": f"walk-forward 计算失败: {type(e).__name__}: {e}"}
    elapsed = round(_time.time() - t0, 2)

    # 汇总判断
    overfit = float(report.overfit_score)
    if overfit < 0.3:
        verdict = "ok"
        verdict_text = "无明显过拟合, 可考虑进入 paper trading 阶段验证"
    elif overfit < 0.7:
        verdict = "warn"
        verdict_text = ("中度过拟合, 建议: ① 减小参数空间; "
                        "② 加入交易成本; ③ 降低仓位; ④ 扩大样本 (多标的 / 更长历史)")
    else:
        verdict = "danger"
        verdict_text = "严重过拟合, 不应直接实盘. 建议换策略风格 / 扩大样本 / 缩减参数空间"

    windows = []
    for w in report.windows:
        windows.append({
            "window_id":    int(w.window_id),
            "train":        f"{w.train_start} ~ {w.train_end}",
            "test":         f"{w.test_start} ~ {w.test_end}",
            "best_params":  w.best_params,
            "train_sharpe": round(float(w.train_sharpe), 3),
            "test_sharpe":  round(float(w.test_sharpe), 3),
            "train_ret":    round(float(w.train_ret), 4),
            "test_ret":     round(float(w.test_ret), 4),
        })

    try:
        name = get_stock_name(code)
    except Exception:
        name = code

    strategy_meta = _WF_STRATEGIES[strategy]
    return {
        "ok":      True,
        "code":    code,
        "name":    name,
        "params": {
            "count":            count,
            "train_window":     train_window,
            "test_window":      test_window,
            "data_rows":        len(df),
            "first_date":       str(df.index[0])[:10],
            "last_date":        str(df.index[-1])[:10],
            "elapsed_sec":      elapsed,
            "strategy":         strategy,
            "strategy_label":   strategy_meta["label"],
            "strategy_summary": f"{strategy_meta['label']} ({len(param_grid)} 组候选)",
            "param_cols":       list(strategy_meta["param_cols"]),
            "param_grid":       param_grid,
        },
        "summary": {
            "windows":           len(report.windows),
            "avg_train_sharpe":  round(float(report.avg_train_sharpe), 3),
            "avg_test_sharpe":   round(float(report.avg_test_sharpe), 3),
            "is_oos_ratio":      round(float(report.is_oos_ratio), 3),
            "overfit_score":     round(overfit, 3),
        },
        "windows":      windows,
        "verdict":      verdict,
        "verdict_text": verdict_text,
    }

@router.get("/registry")
def get_registry():
    if not OUTPUTS_EVOLVE_REGISTRY.exists():
        return []
    try:
        data = json.loads(OUTPUTS_EVOLVE_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for name, s in data.get("strategies", {}).items():
        kpi = s.get("kpi", {})
        rows.append({
            "name":         name,
            "description":  s.get("description", ""),
            "stage":        s.get("stage", "?"),
            "capital_pct":  s.get("capital_pct", 0),
            "sharpe":       kpi.get("rolling_30d_sharpe", 0),
            "return":       kpi.get("rolling_30d_return", 0),
            "maxdd":        kpi.get("rolling_30d_maxdd", 0),
        })
    return rows

@router.post("/lifecycle_eval")
def lifecycle_eval(payload: dict = Body({})):
    try:
        from services.review.strategy_lifecycle.registry import StrategyRegistry
        reg = StrategyRegistry(str(OUTPUTS_EVOLVE_REGISTRY), total_capital=1_000_000)
        migrations = reg.evaluate_and_migrate()
        if not migrations:
            return {
                "summary": "本轮无迁移 (KPI 未触发阶段变更)",
                "log": "registry.json 里的示例策略 KPI 是预设稳定态 (production 仍达标 / paper "
                       "的 days_since_promotion=0 不到升级条件), 所以重复跑都不会迁移. "
                       "想看真实迁移效果, 用上方「用真实数据评估」-- 那才是接 /live/sim 模拟盘的真实 P&L.",
            }
        lines = [f"本轮触发 {len(migrations)} 个迁移:"]
        for m in migrations:
            lines.append(f"  [{m['name']}] {m['from']} -> {m['to']}")
            lines.append(f"      理由: {m['reason']}")
        return {"summary": f"触发 {len(migrations)} 个迁移", "log": "\n".join(lines)}
    except Exception as e:
        return {"summary": f"[ERROR] {e}", "log": ""}

@router.post("/real_pnl_snapshot")
@router.post("/real_pnl_snapshot/")
def real_pnl_snapshot_endpoint(payload: dict = Body({})):
    """手动触发: 拉一次实盘 total_asset, 写入 outputs/real_pnl_history.json
    body: {"force": bool, 默认 false (当日已有则跳过)}
    """
    force = bool(payload.get("force", False))
    return _record_real_pnl_snapshot(force=force)

@router.get("/real_pnl_history")
def real_pnl_history_get():
    """返回当前 real_pnl_history.json 的全部内容 (供前端展示)"""
    return _load_real_pnl_history()

@router.post("/lifecycle_sim_eval")
@router.post("/lifecycle_sim_eval/")
def lifecycle_sim_eval(payload: dict = Body({})):
    """用模拟盘 (sim) 或实盘 (real) 真实数据算策略 KPI 并给迁移建议

    body: {
        "from_stage": "incubating" | "paper" | "probation" | "production",
                      默认 "paper" (假设组合从 paper 阶段开始观察)
        "source":     "sim" | "real",  默认 "sim"
                      sim:  从 live_state.json 的 pnl_history 算 (模拟盘)
                      real: 从 outputs/real_pnl_history.json 算 (实盘 daily snapshot)
    }

    注意: 不写回 24 章 strategy_registry.json (避免污染 demo), 只返回评估结果.
    """
    import math
    from datetime import datetime as _dt

    from_stage = str(payload.get("from_stage") or "paper").strip().lower()
    valid = {"incubating", "paper", "probation", "production"}
    if from_stage not in valid:
        return {"ok": False, "message": f"非法 from_stage={from_stage}, 必须是 {valid}"}

    source = str(payload.get("source") or "sim").strip().lower()
    if source not in ("sim", "real"):
        return {"ok": False, "message": f"非法 source={source}, 必须是 sim 或 real"}

    # ---- 加载 pnl_history ----
    if source == "sim":
        if not OUTPUTS_LIVE_STATE.exists():
            return {"ok": False, "message": "live_state.json 不存在, 模拟盘可能未启动"}
        try:
            state = json.loads(OUTPUTS_LIVE_STATE.read_text(encoding="utf-8"))
        except Exception as e:
            return {"ok": False, "message": f"读 live_state.json 失败: {e}"}
        pnl_history = state.get("pnl_history") or []
        source_label = "sim_portfolio (live_state.json pnl_history)"
        # sim 的 pnl_history 字段是 pnl_pct (累计收益率), 直接用
        pct_field = "pnl_pct"
    else:
        # real: 读 outputs/real_pnl_history.json
        real_data = _load_real_pnl_history()
        pnl_history = real_data.get("history") or []
        source_label = (f"real_portfolio (real_pnl_history.json daily snapshot, "
                        f"baseline={real_data.get('baseline_total_asset')})")
        pct_field = "cum_pct"

    if len(pnl_history) < 2:
        if source == "real":
            return {
                "ok": False,
                "message": (f"实盘 NAV 历史只有 {len(pnl_history)} 条, 不够算 KPI. "
                            f"请先点「记录实盘快照」按钮多次 (建议每天一次, 至少 20 天后再来评估), "
                            f"或在交易日打开 /live/real 让系统自动累积."),
            }
        return {"ok": False, "message": f"pnl_history 数据点 {len(pnl_history)} 个 < 2, 不够算 KPI"}

    # ---- 按日期 group, 取每日最后一笔 (pnl_history 混合了 daily 收盘 + 1min tick) ----
    daily_by_date: Dict[str, Dict[str, Any]] = {}
    for p in pnl_history:
        ts = str(p.get("ts") or "")
        date_str = ts[:10]   # YYYY-MM-DD
        if not date_str:
            continue
        # 同一天后写覆盖前面 (取最后一笔, 即当日"收盘")
        daily_by_date[date_str] = p
    sorted_dates = sorted(daily_by_date.keys())
    daily_points = [daily_by_date[d] for d in sorted_dates]
    if len(daily_points) < 2:
        return {"ok": False,
                "message": f"按日期 group 后只剩 {len(daily_points)} 天, 不够算 KPI"}

    # 1) 累计收益序列 (pct_field 已经是累计) -> 日收益序列
    cum = [float(p.get(pct_field) or 0) for p in daily_points]
    # daily[i] = (1+cum[i]) / (1+cum[i-1]) - 1, daily[0] = cum[0]
    daily: List[float] = [cum[0]]
    for i in range(1, len(cum)):
        prev = 1 + cum[i - 1]
        if prev <= 0:
            daily.append(0.0)
        else:
            daily.append((1 + cum[i]) / prev - 1.0)

    # 2) KPI 计算
    n = len(daily)
    rolling_return = cum[-1]                   # 区间累计收益
    mean_d = sum(daily) / n
    var_d = sum((x - mean_d) ** 2 for x in daily) / max(n - 1, 1)
    std_d = math.sqrt(var_d) if var_d > 0 else 0.0
    sharpe = (mean_d / std_d * math.sqrt(252)) if std_d > 0 else 0.0

    # 最大回撤 (基于净值 1+cum)
    nav = [1 + c for c in cum]
    peak = nav[0]
    maxdd = 0.0
    for v in nav:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd = dd

    days_since_promotion = n   # 真正的"交易日数" (按 date group 后)

    kpi = {
        "rolling_30d_sharpe":    round(sharpe, 4),
        "rolling_30d_return":    round(rolling_return, 4),
        "rolling_30d_maxdd":     round(maxdd, 4),
        "days_since_promotion":  days_since_promotion,
        "data_points":           n,
        "first_ts":              daily_points[0].get("ts"),
        "last_ts":               daily_points[-1].get("ts"),
        "raw_history_points":    len(pnl_history),
    }

    # 3) 套用 24 章 _decide_next_stage 的判断逻辑 (inline, 不调私有方法)
    next_stage = None
    reason = ""
    blockers: List[str] = []

    if maxdd > 0.20:
        next_stage = "retired"
        reason = f"30 日最大回撤 {maxdd:.1%} > 20%, 强制退役 (任何阶段)"
    elif from_stage == "incubating":
        # incubating -> paper 需要 Walk-Forward 的 IS/OOS 比例 >= 0.70, 这是离线指标,
        # 不能从 sim/real 的 daily NAV 算出来. 请用「Walk-Forward 过拟合检测」子 Tab 跑一次,
        # 看 summary.is_oos_ratio 是否 >= 0.70, 通过后再手动在 from_stage 选 paper.
        blockers.append("incubating -> paper 需先跑「Walk-Forward 过拟合检测」, 看 IS/OOS 比例 >= 0.70")
        reason = ("incubating 阶段需 Walk-Forward IS/OOS 比例 (离线指标, NAV 历史算不出); "
                  "请先去「Walk-Forward 过拟合检测」子 Tab 跑一次, 通过后再用 from_stage=paper 评估")
    elif from_stage == "paper":
        cond_days = days_since_promotion >= 20
        cond_ret = rolling_return > 0
        cond_dd = maxdd < 0.05
        if cond_days and cond_ret and cond_dd:
            next_stage = "probation"
            reason = (f"纸交易 {days_since_promotion} 天 >= 20, 收益 {rolling_return:+.2%} > 0, "
                      f"回撤 {maxdd:.2%} < 5% -- 全部满足, 升 probation")
        else:
            if not cond_days:
                blockers.append(f"days_since_promotion={days_since_promotion} < 20 (还差 {20 - days_since_promotion} 天)")
            if not cond_ret:
                blockers.append(f"rolling_return={rolling_return:+.2%} <= 0")
            if not cond_dd:
                blockers.append(f"rolling_maxdd={maxdd:.2%} >= 5%")
            reason = "paper -> probation 条件未全部满足; 阻塞: " + "; ".join(blockers)
    elif from_stage == "probation":
        cond_days = days_since_promotion >= 20
        cond_sharpe = sharpe > 0.5
        if cond_days and cond_sharpe:
            next_stage = "production"
            reason = f"试用期 {days_since_promotion} 天 >= 20, Sharpe {sharpe:.2f} > 0.5, 升 production"
        else:
            if not cond_days:
                blockers.append(f"days_since_promotion={days_since_promotion} < 20")
            if not cond_sharpe:
                blockers.append(f"sharpe={sharpe:.2f} <= 0.5")
            reason = "probation -> production 条件未满足; 阻塞: " + "; ".join(blockers)
    elif from_stage == "production":
        # production 退役条件: consecutive_low_sharpe_days >= 14
        # sim 模式下: 若整段 sharpe < 0.5, 视为连续低; 数据点 < 14 给提示
        cons_low = (sharpe < 0.5)
        if cons_low and days_since_promotion >= 14:
            next_stage = "retired"
            reason = f"production 阶段 Sharpe {sharpe:.2f} < 0.5 持续 {days_since_promotion} 天 >= 14, 触发退役"
        else:
            if not cons_low:
                blockers.append(f"sharpe={sharpe:.2f} >= 0.5, 不算低")
            elif days_since_promotion < 14:
                blockers.append(f"虽然 sharpe={sharpe:.2f} 偏低, 但仅 {days_since_promotion} 天 < 14")
            reason = "production 阶段未触发退役; " + "; ".join(blockers) if blockers else "production 阶段健康"
    else:
        reason = f"未知阶段 {from_stage}"

    # 4) 权益曲线 (按日 group 后) -- 给前端画图用
    equity_curve = [
        {"ts": p.get("ts"), "nav": round(1 + float(p.get(pct_field) or 0), 6)}
        for p in daily_points
    ]

    return {
        "ok":             True,
        "source":         source_label,
        "source_kind":    source,
        "asof":           _dt.now().isoformat(timespec="seconds"),
        "from_stage":     from_stage,
        "kpi":            kpi,
        "next_stage":     next_stage,
        "stage_changed":  next_stage is not None and next_stage != from_stage,
        "reason":         reason,
        "blockers":       blockers,
        "equity_curve":   equity_curve,
        "thresholds":     {
            "paper_to_probation": {
                "min_days":     20,
                "min_return":   0,
                "max_drawdown": 0.05,
            },
            "probation_to_production": {
                "min_days":     20,
                "min_sharpe":   0.5,
            },
            "production_to_retired": {
                "min_consec_low_sharpe_days": 14,
                "low_sharpe_threshold":       0.5,
            },
            "any_to_retired_strong": {
                "max_drawdown": 0.20,
            },
        },
    }

