# -*- coding: utf-8 -*-
"""数据采集业务层 (自 routes/data_collection.py 迁移, 逻辑逐字不变).

子进程管理 / 状态持久化 / 任务定义(外部 CASE 脚本契约) / SSE 事件循环
全部收编至此; 路由层只保留 /jobs /stream /stop /status 四个端点绑定。
外部脚本路径与 .env 解析逻辑原样保留 (外部 CASE 目录契约不动)。
"""
from __future__ import annotations

import collections
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

from lib.paths import DATA_DIR, PROJECT_ROOT
"""数据采集页面 API.

提供:
- GET  /api/data-collection/jobs        任务列表 + 上次采集时间
- GET  /api/data-collection/status      当前运行状态 + 最近日志
- GET  /api/data-collection/stream      SSE 流式执行指定任务
- POST /api/data-collection/stop        终止当前运行的采集任务
"""

HISTORY_FILE = DATA_DIR / "collection_history.json"

STATUS_FILE = DATA_DIR / "collection_status.json"

LOGS_DIR = DATA_DIR / "collection_logs"

_state_lock = threading.Lock()
_current_job_id: str | None = None
_current_job_name: str = ""
_current_start_time: float | None = None
_current_log_file: Path | None = None
_current_pid: int | None = None
_running: bool = False
_last_status: str = "idle"
_stop_requested: bool = False
_recent_logs: collections.deque = collections.deque(maxlen=1000)

def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写入 JSON 文件, 避免 reader 读到半截."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def _load_status_from_file() -> dict:
    """从 STATUS_FILE 读取持久化状态."""
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _write_status():
    """把当前运行状态写入 STATUS_FILE."""
    with _state_lock:
        status = {
            "running": _running,
            "job_id": _current_job_id,
            "job_name": _current_job_name,
            "start_time": _current_start_time,
            "last_status": _last_status,
            "pid": _current_pid,
            "log_file": str(_current_log_file) if _current_log_file else None,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    _atomic_write_json(STATUS_FILE, status)

def _open_log_file(job_id: str, job_name: str) -> Path:
    """为本次任务创建日志文件并写入头部信息."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOGS_DIR / f"{job_id}_{ts}.log"
    header = f"# 任务: {job_name}\n# 任务ID: {job_id}\n# 开始时间: {ts}\n"
    path.write_text(header, encoding="utf-8")
    return path

def _cleanup_old_logs(keep: int = 20):
    """只保留最近 keep 个日志文件, 避免目录无限增长."""
    try:
        if not LOGS_DIR.exists():
            return
        files = sorted(LOGS_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass

def _clear_state():
    """开始新任务前清空状态."""
    global _current_job_id, _current_job_name, _current_start_time, _current_log_file, _current_pid, _running, _last_status, _stop_requested
    with _state_lock:
        _current_job_id = None
        _current_job_name = ""
        _current_start_time = None
        _current_log_file = None
        _current_pid = None
        _running = False
        _last_status = "idle"
        _stop_requested = False
        _recent_logs.clear()

def _set_running(job_id: str, job_name: str, pid: int | None = None):
    global _current_job_id, _current_job_name, _current_start_time, _current_log_file, _current_pid, _running, _last_status, _stop_requested
    with _state_lock:
        _current_job_id = job_id
        _current_job_name = job_name
        _current_start_time = time.time()
        _current_log_file = _open_log_file(job_id, job_name)
        _current_pid = pid
        _running = True
        _last_status = "running"
        _stop_requested = False
    _write_status()

def _update_pid(pid: int | None):
    """更新当前子进程 PID(任务组切换子任务时调用), 供停止按钮定位进程."""
    global _current_pid
    with _state_lock:
        _current_pid = pid
    _write_status()

def _append_log(line_type: str, text: str):
    with _state_lock:
        _recent_logs.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "type": line_type,
            "text": text,
        })
        log_file = _current_log_file
    # 同时追加到日志文件
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} [{line_type}] {text}\n")
        except Exception:
            pass

def _set_finished(status: str):
    global _running, _last_status
    with _state_lock:
        _running = False
        _last_status = status
    _write_status()
    _cleanup_old_logs()

def _terminate_process(pid: int | None) -> bool:
    """强制终止指定 PID 的进程(Windows 用 TerminateProcess, Unix 用 SIGTERM).

    参数:
        pid: 进程 ID

    返回:
        终止是否成功
    """
    if not pid or pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)
            if not handle:
                return False
            result = kernel32.TerminateProcess(handle, -1)
            kernel32.CloseHandle(handle)
            return result != 0
        else:
            os.kill(pid, signal.SIGTERM)
            return True
    except Exception:
        return False

def _env_dir(name: str, default: str | None = None) -> Path | None:
    """读取环境变量并解析为绝对路径; 相对路径以 PROJECT_ROOT 为基准."""
    raw = (os.environ.get(name) or "").strip()
    if not raw and default:
        raw = default
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p

_DATA_CASE_DIR = _env_dir("DATA_COLLECTION_CASE_DIR", "../CASE-数据采集与存储")

_SECTOR_CASE_DIR = _env_dir(
    "SECTOR_DATA_PREP_DIR",
    os.environ.get("CASE_A_BOARD_DATA_PREP_DIR") or "../CASE-A3-板块数据准备-PostgreSQL",
)
_CONCEPT_CASE_DIR = _env_dir("CONCEPT_DATA_PREP_DIR", "../CASE-A4-概念数据准备-QMT")
_LEADER_CASE_DIR = _env_dir("LEADER_DATA_PREP_DIR", "../CASE-A5-龙头数据准备-PostgreSQL")

JOBS = []

if _DATA_CASE_DIR:
    JOBS.extend([
        {"id": "market",     "name": "行情数据采集",   "description": "A 股日 K / 分钟 K / ETF 行情 (CASE-数据采集与存储)", "script": _DATA_CASE_DIR / "1-行情数据采集-postgresql.py"},
        {"id": "financial",  "name": "财务数据采集",   "description": "财务报表 / 指标 / 业绩预告 (CASE-数据采集与存储)", "script": _DATA_CASE_DIR / "2-财务数据采集-postgresql.py"},
        {"id": "macro",      "name": "宏观数据采集",   "description": "宏观经济指标 / 利率 / 汇率 (CASE-数据采集与存储)",      "script": _DATA_CASE_DIR / "3-宏观数据采集-postgresql.py"},
        {"id": "news",       "name": "新闻事件采集",   "description": "财经新闻 / 公告事件 (CASE-数据采集与存储)",            "script": _DATA_CASE_DIR / "4-新闻事件采集-postgresql.py"},
        {"id": "report",     "name": "研报数据采集",   "description": "券商研报 / 评级 (CASE-数据采集与存储)",                "script": _DATA_CASE_DIR / "5-研报数据采集-postgresql.py"},
        {"id": "calendar",   "name": "财经日历采集",   "description": "经济数据发布日历 (CASE-数据采集与存储)",              "script": _DATA_CASE_DIR / "6-财经日历采集-postgresql.py"},
        {"id": "catalyst",   "name": "关键催化剂采集", "description": "业绩预告 / 分红 / 限售解禁等催化剂 (CASE-数据采集与存储)", "script": _DATA_CASE_DIR / "7-关键催化剂采集-postgresql.py"},
    ])

if _SECTOR_CASE_DIR:
    JOBS.append({"id": "sector", "name": "板块数据准备", "description": "申万板块指数合成 (CASE-A3)", "script": _SECTOR_CASE_DIR / "run_daily.py"})

if _CONCEPT_CASE_DIR:
    JOBS.append({"id": "concept", "name": "概念数据准备", "description": "概念指数合成 / 概念成分股维护 (CASE-A4)", "script": _CONCEPT_CASE_DIR / "run_daily.py"})

if _LEADER_CASE_DIR:
    JOBS.append({"id": "leader", "name": "龙头数据准备", "description": "涨停统计 / 龙头榜单 (CASE-A5)", "script": _LEADER_CASE_DIR / "run_daily.py"})

_GROUP_BASIC_JOBS = ["market", "sector", "concept", "leader"]

_GROUP_AUX_JOBS = ["financial", "macro", "news", "report", "catalyst", "calendar"]

GROUPS = [
    {
        "id": "basic",
        "name": "基础数据一键采集",
        "description": "行情数据、板块数据、概念数据、龙头数据",
        "jobs": _GROUP_BASIC_JOBS,
    },
    {
        "id": "aux",
        "name": "扩展数据一键采集",
        "description": "财务、宏观、新闻、研报、关键催化剂、财经日历",
        "jobs": _GROUP_AUX_JOBS,
    },
    {
        "id": "all",
        "name": "全部数据一键采集",
        "description": "按顺序采集全部数据任务",
        "jobs": "__all__",
    },
]

def _resolve_group_jobs(group: dict) -> list:
    """按任务组配置解析可执行的任务列表(过滤不存在的脚本目录).

    参数:
        group: 任务组配置字典

    返回:
        JOBS 中匹配的任务字典列表; jobs 配置为 "__all__" 时返回全部任务
    """
    ids = group.get("jobs")
    if ids == "__all__":
        return list(JOBS)
    return [j for j in JOBS if j["id"] in (ids or [])]

def _resolve_script(script: Path) -> Path:
    """确保脚本路径存在."""
    return Path(script).resolve()

def _load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_history(history: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def _safe_json_dumps(obj) -> str:
    """把 NaN/Inf 转成 null, 避免前端 JSON.parse 失败."""

    def _clean(item):
        import math

        if isinstance(item, float):
            if math.isnan(item) or math.isinf(item):
                return None
            return item
        if isinstance(item, dict):
            return {k: _clean(v) for k, v in item.items()}
        if isinstance(item, list):
            return [_clean(v) for v in item]
        return item

    return json.dumps(_clean(obj), ensure_ascii=False)

def _run_job(job_id: str, q: queue.Queue) -> None:
    """在后台线程中运行采集脚本, 把输出发到队列并更新全局状态."""
    job = next((j for j in JOBS if j["id"] == job_id), None)
    if not job:
        _append_log("error", f"未知任务: {job_id}")
        _set_finished("error")
        q.put(("error", f"未知任务: {job_id}"))
        q.put(("done", None))
        return

    script_path = _resolve_script(job["script"])
    if not script_path.exists():
        _append_log("error", f"脚本不存在: {script_path}")
        _set_finished("error")
        q.put(("error", f"脚本不存在: {script_path}"))
        q.put(("done", None))
        return

    _clear_state()

    start_ts = time.time()
    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # 强制子进程无缓冲输出, 这样页面能实时看到 print 日志
        env["PYTHONUNBUFFERED"] = "1"
        # Windows 上避免 Ctrl+C 传给子进程
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(script_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
        )

        # 拿到 PID 后再标记运行, 并持久化状态到文件
        _set_running(job_id, job["name"], proc.pid)
        _append_log("start", f"开始执行: {job['name']} (pid={proc.pid})")
        q.put(("start", {"job_id": job_id, "job_name": job["name"], "script": str(script_path), "pid": proc.pid}))

        # 实时读取 stdout
        if proc.stdout:
            for line in proc.stdout:
                line = line.rstrip("\n").rstrip("\r")
                if line:
                    q.put(("log", line))
                    _append_log("log", line)

        returncode = proc.wait()
        elapsed = round(time.time() - start_ts, 2)

        if returncode == 0:
            q.put(("success", {"elapsed": elapsed}))
            _append_log("success", f"执行成功，耗时 {elapsed}s")
            _set_finished("success")
            # 保存历史记录
            history = _load_history()
            history[job_id] = {
                "last_success_at": datetime.now().isoformat(timespec="seconds"),
                "elapsed": elapsed,
            }
            _save_history(history)
        else:
            with _state_lock:
                was_stopped = _stop_requested
            if was_stopped:
                q.put(("error", "任务被手动终止"))
                _append_log("error", f"任务被手动终止 (退出码: {returncode})")
                _set_finished("stopped")
            else:
                q.put(("error", f"进程退出码: {returncode}"))
                _append_log("error", f"进程退出码: {returncode}")
                _set_finished("error")
    except Exception as e:
        q.put(("error", f"执行异常: {e}"))
        _append_log("error", f"执行异常: {e}")
        _set_finished("error")
    finally:
        q.put(("done", None))

def _run_group(group_id: str, q: queue.Queue) -> None:
    """在后台线程中按顺序运行任务组内的多个采集脚本, 输出发到队列并更新全局状态.

    每个子任务执行期间更新 _current_pid, 保证「停止当前任务」能定位到正在运行的脚本进程;
    某个子任务失败或被手动终止时, 中断后续子任务并结束任务组。
    """
    group = next((g for g in GROUPS if g["id"] == group_id), None)
    if not group:
        _append_log("error", f"未知任务组: {group_id}")
        _set_finished("error")
        q.put(("error", f"未知任务组: {group_id}"))
        q.put(("done", None))
        return

    jobs = _resolve_group_jobs(group)
    if not jobs:
        msg = f"任务组 {group['name']} 没有可执行的任务"
        _append_log("error", msg)
        _set_finished("error")
        q.put(("error", msg))
        q.put(("done", None))
        return

    _clear_state()
    _set_running(group_id, group["name"], pid=None)

    group_start = time.time()
    total = len(jobs)
    overall_success = True
    try:
        for idx, job in enumerate(jobs, start=1):
            script_path = _resolve_script(job["script"])
            if not script_path.exists():
                msg = f"脚本不存在: {script_path}"
                _append_log("error", msg)
                q.put(("error", msg))
                _set_finished("error")
                overall_success = False
                break

            sub_start = time.time()
            header = f"[{idx}/{total}] {job['name']}"

            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                cwd=str(script_path.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
            )
            # 更新当前 PID, 让停止按钮能终止正在运行的子脚本
            _update_pid(proc.pid)

            _append_log("start", f"开始执行: {header} (pid={proc.pid})")
            q.put(("start", {"job_id": group_id, "job_name": header, "script": str(script_path), "pid": proc.pid}))

            if proc.stdout:
                for line in proc.stdout:
                    line = line.rstrip("\n").rstrip("\r")
                    if line:
                        q.put(("log", line))
                        _append_log("log", line)

            returncode = proc.wait()
            elapsed = round(time.time() - sub_start, 2)

            if returncode == 0:
                _append_log("success", f"完成: {header} 耗时 {elapsed}s")
                q.put(("success", {"job_name": header, "elapsed": elapsed}))
                # 保存该子任务的历史记录
                history = _load_history()
                history[job["id"]] = {
                    "last_success_at": datetime.now().isoformat(timespec="seconds"),
                    "elapsed": elapsed,
                }
                _save_history(history)
            else:
                with _state_lock:
                    was_stopped = _stop_requested
                if was_stopped:
                    msg = f"任务被手动终止: {header}"
                    _set_finished("stopped")
                else:
                    msg = f"任务失败: {header} (退出码: {returncode})"
                    _set_finished("error")
                _append_log("error", msg)
                q.put(("error", msg))
                overall_success = False
                break

        if overall_success:
            total_elapsed = round(time.time() - group_start, 2)
            _append_log("success", f"任务组全部完成, 共 {total} 个任务, 总耗时 {total_elapsed}s")
            q.put(("success", {"job_name": group["name"], "elapsed": total_elapsed}))
            _set_finished("success")
            # 保存任务组历史记录
            history = _load_history()
            history[f"group:{group_id}"] = {
                "last_success_at": datetime.now().isoformat(timespec="seconds"),
                "elapsed": total_elapsed,
            }
            _save_history(history)
    except Exception as e:
        q.put(("error", f"执行异常: {e}"))
        _append_log("error", f"执行异常: {e}")
        _set_finished("error")
    finally:
        q.put(("done", None))

def _stream_loop(q: queue.Queue) -> Iterator[dict]:
    """SSE 事件循环: 消费任务线程队列并转发事件(含 80ms 日志合并缓冲).

    单任务与任务组共用, 保证事件推送行为一致。
    """
    # log 合并缓冲 (性能优化: 行情采集逐行推送 → 80ms 窗口合并, 事件量降一个数量级)
    # 合并后 data 为数组 ["line1","line2",...], 前端逐条 push 渲染, 显示内容不变
    _log_buf: list[str] = []
    _last_log_flush = time.time()
    _LOG_WINDOW = 0.08

    def _flush_logs() -> Iterator[dict]:
        """将 log 缓冲合并为一条 SSE 事件并清空, 更新 flush 时间戳"""
        nonlocal _log_buf, _last_log_flush
        if _log_buf:
            _last_log_flush = time.time()
            yield {"event": "log", "data": _safe_json_dumps(_log_buf)}
            _log_buf = []

    while True:
        try:
            event_type, payload = q.get(timeout=1.0)
        except queue.Empty:
            # 心跳前先 flush 缓冲, 避免日志滞留
            for _ev in _flush_logs():
                yield _ev
            yield {"event": "heartbeat", "data": _safe_json_dumps({"ts": time.time()})}
            continue

        if event_type == "done":
            for _ev in _flush_logs():
                yield _ev
            yield {"event": "done", "data": _safe_json_dumps({})}
            break

        if event_type == "log":
            # stdout 行进入合并缓冲; 窗口到期或缓冲过大即 flush
            _log_buf.append(payload)
            if time.time() - _last_log_flush >= _LOG_WINDOW or len(_log_buf) >= 200:
                for _ev in _flush_logs():
                    yield _ev
            continue

        # 非 log 事件: 先 flush 缓冲保证顺序, 再转发
        for _ev in _flush_logs():
            yield _ev
        yield {"event": event_type, "data": _safe_json_dumps(payload)}

def _event_stream(job_id: str) -> Iterator[dict]:
    """SSE 事件生成器(单个任务)."""
    # 防止重复启动: 如果已有任务在运行, 直接提示
    with _state_lock:
        if _running:
            msg = f"当前有任务在运行: {_current_job_name}，请等待完成或刷新页面查看状态"
            if _current_job_id == job_id:
                msg = "该任务正在运行中，请等待完成或刷新页面查看状态"
            yield {"event": "error", "data": _safe_json_dumps({"error": msg})}
            yield {"event": "done", "data": _safe_json_dumps({})}
            return

    q: queue.Queue = queue.Queue()

    t = threading.Thread(target=_run_job, args=(job_id, q), daemon=True)
    t.start()

    yield from _stream_loop(q)

def _group_event_stream(group_id: str) -> Iterator[dict]:
    """SSE 事件生成器(任务组: 按顺序执行多个任务)."""
    # 防止重复启动: 如果已有任务在运行, 直接提示
    with _state_lock:
        if _running:
            msg = f"当前有任务在运行: {_current_job_name}，请等待完成或刷新页面查看状态"
            yield {"event": "error", "data": _safe_json_dumps({"error": msg})}
            yield {"event": "done", "data": _safe_json_dumps({})}
            return

    q: queue.Queue = queue.Queue()

    t = threading.Thread(target=_run_group, args=(group_id, q), daemon=True)
    t.start()

    yield from _stream_loop(q)

def _read_log_tail(log_file: Path | str | None, n: int = 300) -> list[dict]:
    """读取日志文件最近 n 行, 解析为前端格式."""
    if not log_file:
        return []
    path = Path(log_file)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines[-n:]:
            # 格式: "YYYY-MM-DDTHH:MM:SS [type] text"
            if line.startswith("#"):
                result.append({"time": "", "type": "log", "text": line})
                continue
            m = line.split(" ", 2)
            if len(m) >= 3 and m[1].startswith("[") and m[1].endswith("]"):
                result.append({
                    "time": m[0],
                    "type": m[1][1:-1],
                    "text": m[2],
                })
            else:
                result.append({"time": "", "type": "log", "text": line})
        return result
    except Exception:
        return []

def _is_process_alive(pid: int | None) -> bool:
    """检查进程是否存活."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

