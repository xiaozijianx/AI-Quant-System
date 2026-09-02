# -*- coding: utf-8 -*-
"""数据采集页面 API (薄路由).

提供:
- GET  /api/data-collection/jobs        任务列表 + 上次采集时间
- GET  /api/data-collection/status      当前运行状态 + 最近日志
- GET  /api/data-collection/stream      SSE 流式执行指定任务
- POST /api/data-collection/stop        终止当前运行的采集任务

业务逻辑(子进程管理/状态持久化/任务定义/SSE 事件循环)已下沉 services/collection/。
外部脚本路径与 .env 解析逻辑原样保留 (外部 CASE 目录契约不动)。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from services.collection.core import (
    HISTORY_FILE, STATUS_FILE, LOGS_DIR, _state_lock,
    _current_job_id, _current_job_name, _current_start_time, _current_log_file,
    _current_pid, _running, _last_status, _stop_requested,
    _recent_logs, _atomic_write_json, _load_status_from_file, _write_status,
    _open_log_file, _cleanup_old_logs, _clear_state, _set_running,
    _update_pid, _append_log, _set_finished, _terminate_process,
    _env_dir, _DATA_CASE_DIR, _SECTOR_CASE_DIR, _CONCEPT_CASE_DIR,
    _LEADER_CASE_DIR, JOBS, _GROUP_BASIC_JOBS, _GROUP_AUX_JOBS,
    GROUPS, _resolve_group_jobs, _resolve_script, _load_history,
    _save_history, _safe_json_dumps, _run_job, _run_group,
    _stream_loop, _event_stream, _group_event_stream, _read_log_tail,
    _is_process_alive,
)

router = APIRouter()

@router.get("/jobs")
def list_jobs():
    """返回所有任务定义 + 上次成功采集时间 + 任务组定义."""
    history = _load_history()
    jobs = []
    for job in JOBS:
        info = history.get(job["id"], {})
        jobs.append({
            "id": job["id"],
            "name": job["name"],
            "description": job["description"],
            "last_success_at": info.get("last_success_at"),
            "last_elapsed": info.get("elapsed"),
        })

    groups = []
    for group in GROUPS:
        group_jobs = _resolve_group_jobs(group)
        info = history.get(f"group:{group['id']}", {})
        groups.append({
            "id": group["id"],
            "name": group["name"],
            "description": group["description"],
            "jobs": [j["id"] for j in group_jobs],
            "job_count": len(group_jobs),
            "last_success_at": info.get("last_success_at"),
            "last_elapsed": info.get("elapsed"),
        })
    return {"jobs": jobs, "groups": groups}

@router.get("/stream")
def run_stream(
    job_id: str = Query(None, description="任务 ID"),
    group_id: str = Query(None, description="任务组 ID"),
):
    """SSE 流式执行指定采集任务或任务组(任务组按顺序执行多个脚本)."""
    if group_id:
        valid_group_ids = {g["id"] for g in GROUPS}
        if group_id not in valid_group_ids:
            return EventSourceResponse(
                iter([{"event": "error", "data": _safe_json_dumps({"error": f"未知任务组: {group_id}"})}])
            )
        return EventSourceResponse(_group_event_stream(group_id))

    valid_ids = {j["id"] for j in JOBS}
    if not job_id or job_id not in valid_ids:
        return EventSourceResponse(
            iter([{"event": "error", "data": _safe_json_dumps({"error": f"未知任务: {job_id}"})}])
        )
    return EventSourceResponse(_event_stream(job_id))

@router.post("/stop")
def stop_current_job():
    """终止当前正在运行的采集任务.

    终止后由 _run_job 线程检测到进程退出并设置 stopped 状态,
    避免在子线程尚未结束时就把 _running 置为 False 导致重复启动。
    """
    global _stop_requested
    with _state_lock:
        if not _running or not _current_pid:
            return {"ok": False, "error": "没有正在运行的任务"}
        pid = _current_pid
        job_name = _current_job_name

    _stop_requested = True
    success = _terminate_process(pid)
    if success:
        _append_log("error", f"任务被手动终止 (pid={pid})")
        return {"ok": True, "message": f"已终止任务: {job_name} (pid={pid})"}
    else:
        # 终止失败, 进程可能已自然结束; 重置标记, 让任务线程自行收尾
        _stop_requested = False
        return {"ok": False, "error": f"终止失败, 进程可能已结束 (pid={pid})"}

@router.get("/status")
def get_status():
    """返回当前运行状态和最近日志(优先从持久化文件恢复, 支持 app.py 重启)."""
    # 情况 1: 当前 app.py 内存中有运行中的任务, 直接返回内存状态(最实时)
    with _state_lock:
        if _running:
            return {
                "running": True,
                "job_id": _current_job_id,
                "job_name": _current_job_name,
                "start_time": _current_start_time,
                "last_status": _last_status,
                "pid": _current_pid,
                "log_file": str(_current_log_file) if _current_log_file else None,
                "logs": list(_recent_logs)[-300:],
            }

    # 情况 2: app.py 重启过, 从 STATUS_FILE 恢复
    file_status = _load_status_from_file()
    if not file_status:
        return {
            "running": False,
            "job_id": None,
            "job_name": "",
            "start_time": None,
            "last_status": "idle",
            "pid": None,
            "log_file": None,
            "logs": [],
        }

    running = bool(file_status.get("running"))
    pid = file_status.get("pid")

    # 如果文件显示运行中, 检查 PID 是否还活着
    if running and not _is_process_alive(pid):
        running = False
        file_status["running"] = False
        file_status["last_status"] = "finished_or_crashed"
        file_status["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _atomic_write_json(STATUS_FILE, file_status)

    logs = []
    if running:
        # 任务还在后台跑, 从日志文件读最新内容
        logs = _read_log_tail(file_status.get("log_file"), n=300)
    else:
        # 任务已结束, 显示最后日志
        logs = _read_log_tail(file_status.get("log_file"), n=300)

    return {
        "running": running,
        "job_id": file_status.get("job_id"),
        "job_name": file_status.get("job_name"),
        "start_time": file_status.get("start_time"),
        "last_status": file_status.get("last_status"),
        "pid": pid,
        "log_file": file_status.get("log_file"),
        "logs": logs,
    }

