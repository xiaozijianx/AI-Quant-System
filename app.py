# -*- coding: utf-8 -*-
# 25-AI量化系统 主入口 -- FastAPI + 挂载 Gradio (投研对话)
"""
单进程统一服务:
    FastAPI       -- 主框架 + REST + SSE
    Tailwind CSS  -- 前端 (CDN)
    Alpine.js     -- 前端交互 (CDN)
    Plotly.js     -- 图表 (CDN)
    Gradio        -- 仅用于投研对话, 挂载到 /chat (复用 pages/tab1_chat.py)

URL 结构:
    /                -- 默认重定向到 /live
    /chat/*          -- Gradio 投研对话
    /morning         -- 晨会分析 HTML (读库)
    /live            -- 实盘监控 HTML
    /backtest        -- 回测 HTML
    /review          -- 复盘归因 HTML (Brinson + Walk-Forward + 生命周期)
    /system          -- 系统状态 HTML (组件健康 / scheduler 一键启停)
    /data-collection -- 数据采集 HTML (手动触发各 CASE 脚本 / SSE 日志 / 强制停止)
    /api/*           -- REST API
    /static/*        -- 静态资源 (CSS/JS)

启动:
    python app.py        -- 默认 7865 端口
"""

import os
import socket
import sys
from pathlib import Path

# Windows UTF-8
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 抑制 Windows ProactorEventLoop 退出时 "Event loop is closed" 的 unraisable exception。
# Ctrl+C 退出时事件循环已关闭，但 GC 仍在清理 subprocess transport，触发该错误。
# 该错误不影响功能（程序已退出），仅是 stderr 噪音。
_orig_unraisablehook = sys.unraisablehook

def _suppress_event_loop_closed(args, /):
    exc = args.exc_value
    if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
        return
    _orig_unraisablehook(args)

sys.unraisablehook = _suppress_event_loop_closed

# 加载唯一 .env（路径见 lib.paths.ENV_FILE）
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
# 固定进程工作目录为项目根，确保所有相对路径（agent_config/...）解析到内层目录
os.chdir(THIS_DIR)
from dotenv import load_dotenv
from lib.paths import ENV_FILE, setup_sys_path
load_dotenv(ENV_FILE)
setup_sys_path()

import gradio as gr
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse

from routes import morning, live, review, system as sys_route, backtest, dragon, data_collection, sector_rotation, concept_rotation, stock_quote, dragon_review, trade_plan, factor, page_settings
from agent.server import router as agent_chat_router
from lib.live_simulator import SIM_RUNNER as _LIVE_SIM  # Stage 2: 切断路由横向耦合
from lib.live_simulator import merge_watch_codes


# ============================================================
# Gradio 投研对话 -- 仅 Tab 1, 不带原来的多 Tab 外壳
# ============================================================

def build_chat_only_gradio():
    """只挂 Charles 投研对话, 不要顶部导航 (导航交给 FastAPI)"""
    from pages import tab1_chat
    with gr.Blocks(
        title="投研对话",
        theme=gr.themes.Soft(
            primary_hue="indigo",
            font=[gr.themes.GoogleFont("Inter"), "Microsoft YaHei", "sans-serif"],
        ),
        analytics_enabled=False,
        css="""
.gradio-container { max-width: 100% !important; padding: 16px !important; }
""",
    ) as app:
        tab1_chat.build_tab()
    return app


# ============================================================
# FastAPI 主应用
# ============================================================

api = FastAPI(title="AI 量化系统", docs_url="/api/docs", redoc_url=None)

# 静态资源
api.mount("/static", StaticFiles(directory=str(THIS_DIR / "static")), name="static")

# Jinja2 模板
templates = Jinja2Templates(directory=str(THIS_DIR / "templates"))
# Stage 5: 全站静态资源 cache-busting 统一版本号 (单一来源, 模板内一律用 ?v={{ app_ver }})
templates.env.globals["app_ver"] = "20260902"

# REST 路由
api.include_router(morning.router,        prefix="/api/morning",        tags=["morning"])
api.include_router(live.router,           prefix="/api/live",           tags=["live"])
api.include_router(review.router,         prefix="/api/review",         tags=["review"])
api.include_router(sys_route.router,      prefix="/api/system",         tags=["system"])
api.include_router(backtest.router,       prefix="/api/backtest",       tags=["backtest"])
api.include_router(dragon.router,         prefix="/api/dragon",         tags=["dragon"])
api.include_router(data_collection.router, prefix="/api/data-collection", tags=["data-collection"])
api.include_router(sector_rotation.router,  prefix="/api/sector-rotation",  tags=["sector-rotation"])
api.include_router(concept_rotation.router, prefix="/api/concept-rotation", tags=["concept-rotation"])
api.include_router(stock_quote.router,      prefix="/api/stock-quote",      tags=["stock-quote"])
api.include_router(dragon_review.router,    prefix="/api/dragon-review",    tags=["dragon-review"])
api.include_router(trade_plan.router,                                            tags=["trade-plan"])
api.include_router(factor.router,             prefix="/api/factor",               tags=["factor"])
api.include_router(page_settings.router,      prefix="/api/page-settings",        tags=["page-settings"])
api.include_router(agent_chat_router,                                             tags=["chat"])


# ------------- 页面路由 -------------

@api.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/live")


@api.get("/chat", response_class=HTMLResponse)
def page_chat(request: Request):
    return templates.TemplateResponse(request, "chat.html",
                                      {"active": "chat"})


@api.get("/ai-chat", response_class=HTMLResponse)
def page_ai_chat(request: Request):
    return templates.TemplateResponse(request, "ai-chat.html",
                                      {"active": "ai-chat"})


@api.get("/morning", response_class=HTMLResponse)
def page_morning(request: Request):
    return templates.TemplateResponse(request, "morning.html",
                                      {"active": "morning"})


@api.get("/live", response_class=HTMLResponse)
def page_live():
    # 默认进模拟盘 (后台一直跑, 看着安全); 实盘走 /live/real
    return RedirectResponse(url="/live/sim")


@api.get("/live/sim", response_class=HTMLResponse)
def page_live_sim(request: Request):
    return templates.TemplateResponse(request, "live.html",
                                      {"active": "live",
                                       "view_mode": "sim"})


@api.get("/live/real", response_class=HTMLResponse)
def page_live_real(request: Request):
    return templates.TemplateResponse(request, "live.html",
                                      {"active": "live",
                                       "view_mode": "real"})


@api.get("/backtest", response_class=HTMLResponse)
def page_backtest(request: Request):
    return templates.TemplateResponse(request, "backtest.html",
                                      {"active": "backtest"})


@api.get("/review", response_class=HTMLResponse)
def page_review(request: Request):
    return templates.TemplateResponse(request, "review.html",
                                      {"active": "review"})


@api.get("/system", response_class=HTMLResponse)
def page_system(request: Request):
    return templates.TemplateResponse(request, "system.html",
                                      {"active": "system"})


@api.get("/data-collection", response_class=HTMLResponse)
def page_data_collection(request: Request):
    return templates.TemplateResponse(request, "data_collection.html",
                                      {"active": "data-collection"})


@api.get("/sector-rotation", response_class=HTMLResponse)
def page_sector_rotation(request: Request):
    # 板块/概念轮动共用统一模板 rotation.html, 维度差异经 SECTOR 配置注入
    from services.rotation.dimension import SECTOR
    return templates.TemplateResponse(request, "rotation.html",
                                      {"active": "sector-rotation", "rotation": SECTOR})


@api.get("/concept-rotation", response_class=HTMLResponse)
def page_concept_rotation(request: Request):
    from services.rotation.dimension import CONCEPT
    return templates.TemplateResponse(request, "rotation.html",
                                      {"active": "concept-rotation", "rotation": CONCEPT})


@api.get("/stock-quote", response_class=HTMLResponse)
def page_stock_quote(request: Request, code: str = "000001.SH"):
    return templates.TemplateResponse(request, "stock_quote.html",
                                      {"active": "stock-quote", "code": code})


@api.get("/dragon-review", response_class=HTMLResponse)
def page_dragon_review(request: Request):
    return templates.TemplateResponse(request, "dragon_review.html",
                                      {"active": "dragon-review"})


@api.get("/factor", response_class=HTMLResponse)
def page_factor(request: Request):
    return templates.TemplateResponse(request, "factor.html",
                                      {"active": "factor"})


# ------------- 交易计划页面 (Stage 2: 页面路由统一归位 app.py) -------------

@api.get("/trade-plan", response_class=HTMLResponse)
def page_trade_plan(request: Request):
    """交易计划根路径: 有监控标的则进入第一只详情页, 否则提示先去 /live 添加"""
    from datetime import date
    from lib.live_simulator import merge_watch_codes
    from lib.stock_utils import normalize_code
    codes = merge_watch_codes([])
    if codes:
        first = normalize_code(codes[0])
        return RedirectResponse(url=f"/trade-plan/{first}?plan_type=sim")
    return templates.TemplateResponse(request, "trade_plan.html",
                                      {"active": "trade-plan",
                                       "code": "",
                                       "plan_type": "sim",
                                       "trade_date": date.today().isoformat()})


@api.get("/trade-plan/list", response_class=HTMLResponse)
def page_trade_plan_list(request: Request):
    """旧列表页入口统一重定向到新的详情页入口"""
    return RedirectResponse(url="/trade-plan")


@api.get("/trade-plan/{code}", response_class=HTMLResponse)
def page_trade_plan_detail(request: Request, code: str, plan_type: str = "sim"):
    """交易计划详情页"""
    from datetime import date
    from lib.stock_utils import normalize_code
    return templates.TemplateResponse(request, "trade_plan.html",
                                      {"active": "trade-plan",
                                       "code": normalize_code(code),
                                       "plan_type": plan_type,
                                       "trade_date": date.today().isoformat()})


# ------------- 挂载 Gradio 到 /gradio-chat/ (供 /chat 页面 iframe 嵌入) -------------

gradio_app = build_chat_only_gradio()
api = gr.mount_gradio_app(api, gradio_app, path="/gradio-chat")


# ------------- 启动时自动开启模拟盘 engine -------------
# 注意: 不能用 @api.on_event("startup") -- gradio mount 之后 hook 会被包装丢掉.
# 走 main() 里同步调一次: _SIM.start() 内部是后台线程, 不阻塞 uvicorn.

def _auto_start_sim():
    """程序启动后自动跑模拟盘 (dry_run=True), 不需要用户手动点启动.
    监控池为空 (无 mock 持仓 / watch_pool / per_stock) 时跳过, 等用户添加股票后再手动启动."""
    try:
        merged = merge_watch_codes([])
        if not merged:
            print("[live] 监控池为空, 跳过自动启动模拟盘 -- 添加股票后请手动启动", flush=True)
            return
        msg = _LIVE_SIM.start(watch_stocks=merged, dry_run=True, cycle_seconds=60)
        print(f"[live] 自动启动模拟盘:\n{msg}", flush=True)
    except Exception as e:
        print(f"[live] 自动启动模拟盘失败 (不影响 web 运行): {type(e).__name__}: {e}", flush=True)


# ============================================================
# 启动
# ============================================================

def _find_free_port(start_port: int, host: str = "127.0.0.1", max_tries: int = 50) -> int:
    """从 start_port 起找空闲端口 (Windows 不能用 SO_REUSEADDR)"""
    for offset in range(max_tries):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"在 {start_port}-{start_port+max_tries-1} 找不到空闲端口")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI 量化交易系统 (FastAPI + Gradio)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("DASHBOARD_PORT", 7865)))
    # 默认 127.0.0.1: 仅本机访问, uvicorn 启动日志显示 127.0.0.1, 浏览器可直接点开;
    # 需要 LAN 上其他设备 (手机 / 同事电脑) 访问时, 启动加 `--host 0.0.0.0`.
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址, 默认 127.0.0.1 (仅本机); LAN 共享用 0.0.0.0")
    parser.add_argument("--no-auto-port", action="store_true")
    args = parser.parse_args()

    desired_port = args.port
    actual_port = desired_port
    if not args.no_auto_port:
        actual_port = _find_free_port(desired_port, host=args.host)
        if actual_port != desired_port:
            print(f"[INFO] 端口 {desired_port} 已被占用, 自动切换到 {actual_port}")

    # banner 上显示的地址: 0.0.0.0 在浏览器里点不开, 统一展示成 127.0.0.1 引导用户;
    # uvicorn 启动日志会按 args.host 真实显示 (0.0.0.0 / 127.0.0.1).
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host

    print()
    print("=" * 70)
    print("  AI 量化交易系统启动 (FastAPI + Tailwind + Alpine + Gradio)")
    print("=" * 70)
    print(f"  Web UI:    http://{display_host}:{actual_port}  (默认进入 /live)")
    print(f"  API docs:  http://{display_host}:{actual_port}/api/docs")
    print(f"  Gradio:    http://{display_host}:{actual_port}/gradio-chat/  (内嵌于 /chat)")
    if args.host in ("0.0.0.0", "::"):
        print(f"  LAN 共享:  已绑定所有网卡, 局域网内可用本机 IP 访问")
    print(f"  默认 dry-run, 不会真下单")
    print("=" * 70)
    print()

    # Phase 24: 启动时捕获 telemetry 服务激活事件 — 对标 Cline captureCliExtensionActivated
    try:
        from agent.telemetry import capture_service_activated
        capture_service_activated()
    except Exception as e:
        print(f"[WARN] Telemetry 初始化失败: {e}")

    # 启动时确保因子库相关表存在 (幂等, 防止新增表/字段未建导致查询报错)
    try:
        from lib.factor_db import init_tables
        init_tables()
    except Exception as e:
        print(f"[WARN] 因子库建表失败: {e}")

    # 注: 不再在 app.py 启动时自动启动模拟盘。
    # 模拟盘由用户在 /live 页面手动启动; 实盘引擎由 scheduler.py 的 live_engine 任务在 9:30/14:55 调度。
    # _auto_start_sim() 函数保留, 如需恢复自动启动可取消下面注释。
    # _auto_start_sim()

    uvicorn.run(api, host=args.host, port=actual_port,
                log_level="info", access_log=False)


if __name__ == "__main__":
    main()
