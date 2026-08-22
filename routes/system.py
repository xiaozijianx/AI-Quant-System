# -*- coding: utf-8 -*-
# 系统状态路由 -- REST
"""
GET  /api/system/health             -- 健康检查 (xtdata / DASHSCOPE / state / registry)
GET  /api/system/scheduler/config   -- 调度器开关配置 + 在线状态
POST /api/system/scheduler/config   -- 保存调度器开关配置
POST /api/system/scheduler/control  -- 一键启动 / 停止 scheduler 进程 (action=start|stop)
"""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Body

from lib.paths import setup_sys_path, OUTPUTS_LIVE_STATE, OUTPUTS_RESEARCH
setup_sys_path()

from lib.scheduler_config import (
    load_scheduler_config,
    save_scheduler_config,
    read_heartbeat,
    start_scheduler_process,
    stop_scheduler_process,
)

router = APIRouter()


SCHEDULER_JOBS = [
    {"id": "data_refresh",  "name": "08:30 数据增量",      "time": "08:30",       "enabled_by": "data_refresh"},
    {"id": "morning_brief", "name": "09:00 晨会分析",      "time": "09:00",       "enabled_by": "morning_brief"},
    {"id": "live_engine",   "name": "09:30/14:55 引擎启停", "time": "09:30 / 14:55", "enabled_by": "live_engine"},
]


@router.get("/health")
def health():
    rows = []

    rows.append({"item": "Python 版本", "value": sys.version.split()[0], "status": "OK"})

    try:
        from xtquant import xtdata
        xtdata.connect()
        rows.append({"item": "xtdata 行情", "value": "已连接", "status": "OK"})
    except Exception as e:
        rows.append({"item": "xtdata 行情", "value": str(e)[:60], "status": "ERROR"})

    if os.environ.get("DASHSCOPE_API_KEY"):
        rows.append({"item": "DASHSCOPE_API_KEY", "value": "已配置", "status": "OK"})
    else:
        rows.append({"item": "DASHSCOPE_API_KEY",
                     "value": "未配置 (Charles 不可用)", "status": "WARN"})

    if os.environ.get("QMT_PATH"):
        rows.append({"item": "QMT_PATH",
                     "value": os.environ["QMT_PATH"], "status": "OK"})
    else:
        rows.append({"item": "QMT_PATH",
                     "value": "未配置 (实盘下单不可用)", "status": "WARN"})

    if OUTPUTS_LIVE_STATE.exists():
        import json
        try:
            s = json.loads(OUTPUTS_LIVE_STATE.read_text(encoding="utf-8"))
            rows.append({"item": "live_state.json",
                         "value": f"updated_at={s.get('_updated_at', '?')}", "status": "OK"})
        except Exception as e:
            rows.append({"item": "live_state.json",
                         "value": f"解析失败: {e}", "status": "ERROR"})
    else:
        rows.append({"item": "live_state.json",
                     "value": "不存在 (启动模拟盘后会自动创建)", "status": "WARN"})

    if OUTPUTS_RESEARCH.exists():
        n = len(list(OUTPUTS_RESEARCH.glob("morning_brief_*.html")))
        rows.append({"item": "晨会分析 HTML", "value": f"{n} 份",
                     "status": "OK" if n > 0 else "WARN"})
    else:
        rows.append({"item": "晨会分析 HTML",
                     "value": "目录不存在", "status": "WARN"})

    return rows


@router.get("/scheduler/config")
def scheduler_config_get():
    """返回调度器开关配置、任务列表和在线状态."""
    cfg = load_scheduler_config()
    heartbeat = read_heartbeat()
    return {
        "config": cfg,
        "heartbeat": heartbeat,
        "jobs": [
            {**job, "enabled": bool(cfg.get(job["enabled_by"], True))}
            for job in SCHEDULER_JOBS
        ],
    }


@router.post("/scheduler/config")
def scheduler_config_set(payload: dict = Body(...)):
    """保存调度器开关配置.

    payload 示例:
        {"data_refresh": true, "morning_brief": true, "live_engine": false}
    """
    cfg = load_scheduler_config()
    for key in ("data_refresh", "morning_brief", "live_engine"):
        if key in payload:
            cfg[key] = bool(payload[key])
    cfg = save_scheduler_config(cfg)
    return {"ok": True, "config": cfg}


@router.post("/scheduler/control")
def scheduler_control(action: str):
    """一键启停 scheduler 进程.

    action: start | stop
    """
    action = (action or "").lower()
    if action == "start":
        result = start_scheduler_process()
    elif action == "stop":
        result = stop_scheduler_process()
    else:
        return {"ok": False, "error": f"未知 action: {action}"}
    return {"ok": result.get("ok"), "action": action, **result}
