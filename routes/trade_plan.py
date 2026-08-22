# -*- coding: utf-8 -*-
# 交易计划页面 + API 路由
"""
页面:
    GET  /trade-plan/{code}            交易计划详情页

API:
    GET    /api/trade-plan/{code}       读取计划
    POST   /api/trade-plan/{code}       保存 Markdown
    GET    /api/trade-plan/{code}/preview  解析预览
    DELETE /api/trade-plan/{code}       删除计划
    GET    /api/trade-plans             列出计划索引
    POST   /api/trade-plan/{code}/toggle 切换状态
"""

from __future__ import annotations
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from lib.paths import PROJECT_ROOT, setup_sys_path
setup_sys_path()

from lib.stock_utils import normalize_code, get_stock_info
from lib.trading_plan import PlanManager, init_trading_plan_table
from lib.live_simulator import merge_watch_codes, load_mock_config
from lib.paths import OUTPUTS_LIVE_STATE
from lib.backtest_data import load_daily_kline


router = APIRouter()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))
_manager = PlanManager()


# 启动时确保表存在
_init_result = init_trading_plan_table()
print(f"[trade_plan] {_init_result}", flush=True)


def _norm_code(code: str) -> str:
    """统一交易计划路由中的股票代码格式"""
    return normalize_code(code)


# ============================================================
# 页面
# ============================================================

@router.get("/trade-plan", response_class=HTMLResponse)
def trade_plan_root(request: Request):
    """交易计划根路径: 有监控标的则进入第一只详情页, 否则提示先去 /live 添加"""
    codes = merge_watch_codes([])
    if codes:
        first = _norm_code(codes[0])
        return RedirectResponse(url=f"/trade-plan/{first}?plan_type=sim")
    return templates.TemplateResponse(request, "trade_plan.html",
                                      {"active": "trade-plan",
                                       "code": "",
                                       "plan_type": "sim",
                                       "trade_date": date.today().isoformat()})


@router.get("/trade-plan/list", response_class=HTMLResponse)
def trade_plan_list_redirect(request: Request):
    """旧列表页入口统一重定向到新的详情页入口"""
    return RedirectResponse(url="/trade-plan")


@router.get("/trade-plan/{code}", response_class=HTMLResponse)
def trade_plan_page(request: Request, code: str, plan_type: str = "sim"):
    """交易计划详情页"""
    trade_date = date.today().isoformat()
    return templates.TemplateResponse(request, "trade_plan.html",
                                      {"active": "trade-plan",
                                       "code": _norm_code(code),
                                       "plan_type": plan_type,
                                       "trade_date": trade_date})


# ============================================================
# API
# ============================================================

def _today() -> str:
    return date.today().isoformat()


def _load_position_for_plan(code: str, plan_type: str) -> dict:
    """为生成交易计划读取对应持仓: sim 读 live_state.json, live 读 live_state_real.json"""
    from lib.paths import OUTPUTS_DIR
    code = normalize_code(code)

    # sim → outputs/live_state.json, live → outputs/live_state_real.json
    if plan_type == "live":
        state_file = OUTPUTS_DIR / "live_state_real.json"
    else:
        state_file = OUTPUTS_LIVE_STATE

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            for p in state.get("positions", []) or []:
                if normalize_code(str(p.get("code", ""))) == code:
                    return {
                        "volume": int(p.get("volume", 0) or 0),
                        "cost": float(p.get("cost", 0) or 0),
                        "cur_price": float(p.get("cur_price", 0) or 0),
                        "market_value": float(p.get("market_value", 0) or 0),
                        "capital": float(state.get("capital", 1_000_000) or 1_000_000),
                    }
            return {"capital": float(state.get("capital", 1_000_000) or 1_000_000)}
        except Exception:
            pass
    return {"capital": 1_000_000}


def _market_context_for_plan(code: str, position: dict) -> dict:
    """拉取日 K 计算最新价与 MA20, 用于生成真实触发价"""
    result = {"ma20": 0.0, "latest_close": 0.0}
    try:
        # 取最近 60 个交易日计算 MA20
        df = load_daily_kline(code, start_date=None, end_date=None, prefer="auto")
        if df is not None and not df.empty:
            result["latest_close"] = float(df["close"].iloc[-1]) if "close" in df.columns else 0.0
            if len(df) >= 20:
                result["ma20"] = float(df["close"].rolling(20).mean().iloc[-1])
    except Exception:
        pass

    # 若拿不到最新价, 用持仓成本兜底, 避免触发价全为 0
    if result["latest_close"] <= 0:
        result["latest_close"] = position.get("cost", 0) or position.get("cur_price", 0) or 1.0
    if result["ma20"] <= 0:
        result["ma20"] = position.get("cost", 0) or result["latest_close"]
    return result


@router.get("/api/trade-plan/{code}")
def get_plan(code: str, plan_type: str = "sim", trade_date: Optional[str] = None):
    """读取指定交易计划"""
    code = _norm_code(code)
    trade_date = trade_date or _today()
    plan = _manager.get(code, plan_type, trade_date)
    if plan is None:
        return JSONResponse({
            "ok": False,
            "message": "计划不存在",
            "exists": False,
        }, status_code=404)
    return {
        "ok": True,
        "exists": True,
        "code": code,
        "plan_type": plan_type,
        "trade_date": trade_date,
        "metadata": plan["metadata"],
        "raw_markdown": plan["raw_markdown"],
        "parsed": plan["parsed"],
    }


@router.post("/api/trade-plan/{code}")
async def save_plan(request: Request, code: str, plan_type: str = "sim",
                    trade_date: Optional[str] = None):
    """保存交易计划 Markdown"""
    code = _norm_code(code)
    trade_date = trade_date or _today()
    payload = await request.json()
    md_content = payload.get("markdown", "")
    result = _manager.save(code, plan_type, trade_date, md_content)
    return JSONResponse(result)


@router.get("/api/trade-plan/{code}/preview")
def preview_plan(code: str, plan_type: str = "sim", trade_date: Optional[str] = None):
    """仅返回解析后的结构化数据"""
    code = _norm_code(code)
    trade_date = trade_date or _today()
    plan = _manager.get(code, plan_type, trade_date)
    if plan is None:
        return JSONResponse({"ok": False, "message": "计划不存在"}, status_code=404)
    return {
        "ok": True,
        "metadata": plan["metadata"],
        "parsed": plan["parsed"],
    }


@router.delete("/api/trade-plan/{code}")
def delete_plan(code: str, plan_type: str = "sim", trade_date: Optional[str] = None):
    """删除交易计划"""
    code = _norm_code(code)
    trade_date = trade_date or _today()
    result = _manager.delete(code, plan_type, trade_date)
    return JSONResponse(result)


@router.get("/api/trade-plans")
def list_plans(plan_type: Optional[str] = None):
    """列出交易计划索引"""
    rows = _manager.list_plans(plan_type=plan_type)
    return {"ok": True, "items": rows, "count": len(rows)}


@router.get("/api/trade-plan/{code}/execution")
def get_execution_plan(code: str, plan_type: str = "sim"):
    """返回交易计划中可直接用于执行的结构化字段(来自数据库解析结果), 供实盘/模拟盘监控页使用"""
    code = _norm_code(code)
    plan = _manager.get_active_plan(code, plan_type)
    if plan is None:
        return JSONResponse({
            "ok": False,
            "exists": False,
            "message": "无生效交易计划",
        }, status_code=404)
    return {
        "ok": True,
        "exists": True,
        "code": code,
        "plan_type": plan_type,
        "metadata": {
            "stock_code": plan["stock_code"],
            "stock_name": plan["stock_name"],
            "trade_date": plan["trade_date"].isoformat() if hasattr(plan["trade_date"], "isoformat") else str(plan["trade_date"]),
            "is_active": plan["is_active"],
            "is_auto_trade": plan["is_auto_trade"],
            "target_ratio_min": plan["target_ratio_min"],
            "target_ratio_max": plan["target_ratio_max"],
        },
        "conditions": {
            "entry": plan.get("entry_conditions", []),
            "take_profit": plan.get("take_profit_conditions", []),
            "stop_loss": plan.get("stop_loss_conditions", []),
            "add_position": plan.get("add_position_conditions", []),
        },
    }


@router.get("/api/trade-plan/{code}/overview")
def get_plan_overview(code: str, plan_type: str = "sim"):
    """返回交易计划结构化概览(来自数据库解析结果), 供模拟盘/实盘监控页展示。

    与 /execution 的区别:
        - /execution 只返回 is_active 且 is_auto_trade 的计划, 供执行引擎调用;
        - /overview 不限制生效状态, 只要数据库里有解析记录就返回, 用于监控页参考展示。
    """
    code = _norm_code(code)
    overview = _manager.get_overview(code, plan_type)
    if overview is None:
        return JSONResponse({
            "ok": False,
            "exists": False,
            "message": "无交易计划",
        }, status_code=404)
    return {
        "ok": True,
        "exists": True,
        "code": code,
        "plan_type": plan_type,
        "metadata": overview["metadata"],
        "parsed": overview["parsed"],
    }


@router.post("/api/trade-plan/{code}/generate")
async def generate_plan(request: Request, code: str, plan_type: str = "sim",
                        trade_date: Optional[str] = None,
                        force: bool = False):
    """按默认模板生成 Markdown 并解析入库; 生成时会结合真实持仓成本与市场数据计算触发价"""
    code = _norm_code(code)
    trade_date = trade_date or _today()
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except Exception:
        payload = {}
    force = force or bool(payload.get("force", False))

    # 读取持仓 + 市场数据, 让触发价不再是全 0
    position = _load_position_for_plan(code, plan_type)
    market = _market_context_for_plan(code, position)
    stock_info = get_stock_info(code)
    stock_name = stock_info.get("name") or code

    # 计算仓位占比(用于仓位计划)
    capital = position.get("capital", 1_000_000)
    current_value = position.get("market_value", 0)
    current_ratio = (current_value / capital * 100) if capital > 0 else 0.0

    # 若没有真实持仓成本, 用最新收盘价作为参考价, 让止盈/成本止损价仍有意义
    cost = position.get("cost", 0) or market.get("latest_close", 0)
    cur_price = position.get("cur_price", 0) or market.get("latest_close", 0)
    current_value = current_value or (position.get("volume", 0) * cur_price)

    # 非强制重新生成时, 保留原计划的生效/自动执行状态, 避免用户手动点「生效」后被重置
    prev_active, prev_auto = False, False
    if not force:
        prev = _manager.get(code, plan_type, trade_date)
        if prev:
            prev_active = bool(prev.get("metadata", {}).get("is_active", False))
            prev_auto = bool(prev.get("metadata", {}).get("is_auto_trade", False))

    plan = _manager.get_or_create(
        code, plan_type, trade_date, force=force,
        stock_name=stock_name,
        current_ratio=current_ratio,
        current_volume=position.get("volume", 0),
        current_value=current_value,
        target_ratio_min=0.0,
        target_ratio_max=0.0,
        cost=cost,
        ma20=market.get("ma20", 0),
        capital=capital,
        is_active=prev_active,
        is_auto_trade=prev_auto,
    )
    if not plan:
        return JSONResponse({"ok": False, "message": "生成失败"}, status_code=500)
    return {
        "ok": True,
        "exists": True,
        "code": code,
        "plan_type": plan_type,
        "trade_date": trade_date,
        "metadata": plan["metadata"],
        "raw_markdown": plan["raw_markdown"],
        "parsed": plan["parsed"],
    }


@router.post("/api/trade-plan/{code}/toggle")
async def toggle_plan(request: Request, code: str, plan_type: str = "sim",
                      trade_date: Optional[str] = None):
    """切换 is_active / is_auto_trade, 通过重写 Markdown frontmatter 实现"""
    code = _norm_code(code)
    trade_date = trade_date or _today()
    payload = await request.json()
    field = payload.get("field")  # "is_active" 或 "is_auto_trade"
    value = bool(payload.get("value"))

    if field not in ("is_active", "is_auto_trade"):
        return JSONResponse({"ok": False, "message": "field 必须是 is_active 或 is_auto_trade"})

    plan = _manager.get(code, plan_type, trade_date)
    if plan is None:
        return JSONResponse({"ok": False, "message": "计划不存在"}, status_code=404)

    md = plan["raw_markdown"]
    # 简单替换 frontmatter 中的布尔值
    import re
    pattern = rf"({field}:\s*)(true|false)"
    if not re.search(pattern, md, flags=re.IGNORECASE):
        return JSONResponse({"ok": False, "message": f"Markdown 中未找到 {field}"})
    new_md = re.sub(pattern, rf"\g<1>{str(value).lower()}", md, count=1, flags=re.IGNORECASE)
    # 生效即自动执行: 勾选「生效」时强制 is_auto_trade=true
    if field == "is_active" and value:
        if not re.search(r"(is_auto_trade:\s*)(true|false)", new_md, flags=re.IGNORECASE):
            return JSONResponse({"ok": False, "message": "Markdown 中未找到 is_auto_trade"})
        new_md = re.sub(r"(is_auto_trade:\s*)(true|false)",
                        r"\g<1>true", new_md, count=1, flags=re.IGNORECASE)
    result = _manager.save(code, plan_type, trade_date, new_md)
    return JSONResponse(result)
