# -*- coding: utf-8 -*-
# 调度器开关配置与心跳持久化
"""
为什么单独一个模块?
    - scheduler.py 是独立进程, 与 Web 工作台(app.py)分进程跑
    - 两者通过 data/scheduler_config.json 解耦:
        Web 只写配置, scheduler 每次 job 执行前重新读取
    - 支持 Web 崩溃/重启后, scheduler 继续按原配置运行
    - 支持 scheduler 自身重启后自动恢复上次开关状态

设计:
    - 配置与心跳分开两个 JSON 文件, 职责清晰
    - 写文件采用 tmp + os.replace 原子替换, 避免 reader 读到半截
    - 心跳带 90 秒超时判断, 崩溃来不及写 false 也能被识别为离线
"""

from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from lib.paths import DATA_DIR, PROJECT_ROOT

# 开关配置文件
CONFIG_FILE = DATA_DIR / "scheduler_config.json"
# 心跳文件
HEARTBEAT_FILE = DATA_DIR / "scheduler_heartbeat.json"

# 默认值
DEFAULT_CONFIG = {
    "data_refresh":  True,
    "morning_brief": True,
    "live_engine":   True,
    "updated_at":    None,
}

# 心跳超时(秒): 超过该时间未刷新则认为 scheduler 离线
HEARTBEAT_TIMEOUT_SECONDS = 90


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ============================================================
# 开关配置读写
# ============================================================

def load_scheduler_config() -> dict:
    """读取 scheduler 开关配置, 文件不存在则初始化默认值."""
    if not CONFIG_FILE.exists():
        save_scheduler_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_scheduler_config(cfg: dict) -> dict:
    """保存 scheduler 开关配置, 返回标准化后的配置."""
    cfg = {k: bool(cfg.get(k, DEFAULT_CONFIG[k])) if isinstance(DEFAULT_CONFIG[k], bool)
           else cfg.get(k, DEFAULT_CONFIG[k])
           for k in DEFAULT_CONFIG}
    cfg["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write_json(CONFIG_FILE, cfg)
    return cfg


def is_job_enabled(job_id: str) -> bool:
    """判断某个定时任务是否启用.

    job_id 取值:
        - data_refresh  : 08:30 数据增量
        - morning_brief : 09:00 晨会分析
        - live_engine   : 09:30/14:55 实盘引擎启停
    """
    if job_id not in DEFAULT_CONFIG:
        return True
    cfg = load_scheduler_config()
    return bool(cfg.get(job_id, True))


# ============================================================
# 心跳读写(用于 Web 判断 scheduler 是否在线)
# ============================================================

def write_heartbeat(running: bool, pid: Optional[int] = None) -> None:
    """写入 scheduler 心跳状态."""
    data = {
        "running":        running,
        "pid":            pid or os.getpid(),
        "boot_at":        getattr(write_heartbeat, "_boot_at", None),
        "last_heartbeat": datetime.now().isoformat(timespec="seconds"),
    }
    _atomic_write_json(HEARTBEAT_FILE, data)


def refresh_heartbeat() -> None:
    """刷新心跳时间戳( scheduler 后台线程调用 )."""
    if not HEARTBEAT_FILE.exists():
        write_heartbeat(running=True)
        return
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        data["last_heartbeat"] = datetime.now().isoformat(timespec="seconds")
        data["pid"] = os.getpid()
        _atomic_write_json(HEARTBEAT_FILE, data)
    except Exception:
        write_heartbeat(running=True)


def set_boot_time() -> None:
    """设置启动时间, 供后续心跳复用."""
    write_heartbeat._boot_at = datetime.now().isoformat(timespec="seconds")


def read_heartbeat() -> dict:
    """读取心跳并判断在线状态.

    返回:
        {
            "online":         bool,
            "running":        bool,
            "pid":            int | None,
            "boot_at":        str | None,
            "last_heartbeat": str | None,
            "seconds_since":  int | None,
        }
    """
    if not HEARTBEAT_FILE.exists():
        return {"online": False, "running": False, "pid": None,
                "boot_at": None, "last_heartbeat": None, "seconds_since": None}
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"online": False, "running": False, "pid": None,
                "boot_at": None, "last_heartbeat": None, "seconds_since": None}

    last = data.get("last_heartbeat")
    if not last:
        seconds_since = None
    else:
        try:
            last_dt = datetime.fromisoformat(last)
            seconds_since = int((datetime.now() - last_dt).total_seconds())
        except Exception:
            seconds_since = None

    online = bool(data.get("running")) and seconds_since is not None \
             and seconds_since <= HEARTBEAT_TIMEOUT_SECONDS

    return {
        "online":         online,
        "running":        bool(data.get("running", False)),
        "pid":            data.get("pid"),
        "boot_at":        data.get("boot_at"),
        "last_heartbeat": last,
        "seconds_since":  seconds_since,
    }


# ============================================================
# scheduler 进程管理(供 Web 页面一键启停)
# ============================================================

def is_process_alive(pid: int) -> bool:
    """判断进程是否存活(跨平台)."""
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def start_scheduler_process() -> dict:
    """在后台启动 scheduler.py 子进程, 返回心跳信息."""
    hb = read_heartbeat()
    pid = hb.get("pid")
    if pid and is_process_alive(pid):
        return {"ok": True, "started": False, "message": "scheduler 已在运行", "heartbeat": hb}

    scheduler_py = PROJECT_ROOT / "scheduler.py"
    if not scheduler_py.exists():
        return {"ok": False, "error": f"找不到 scheduler.py: {scheduler_py}"}

    log_file = DATA_DIR / "scheduler.log"
    try:
        log_handle = open(log_file, "a", encoding="utf-8")
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(
                [sys.executable, str(scheduler_py)],
                cwd=str(PROJECT_ROOT),
                creationflags=creationflags,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        else:
            proc = subprocess.Popen(
                [sys.executable, str(scheduler_py)],
                cwd=str(PROJECT_ROOT),
                start_new_session=True,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )

        # 等待心跳文件写入, 最多 5 秒
        for _ in range(10):
            time.sleep(0.5)
            hb2 = read_heartbeat()
            if hb2.get("pid") == proc.pid and hb2.get("running"):
                return {"ok": True, "started": True, "pid": proc.pid, "heartbeat": hb2}
            # 如果进程已经退出, 说明启动失败(常见原因: apscheduler 未安装)
            if proc.poll() is not None:
                return {"ok": False, "error": "scheduler 进程启动后立即退出, 请检查终端运行 'python scheduler.py' 的报错(常见原因: apscheduler 未安装)"}

        # 心跳未就绪, 但进程还在跑, 保守认为启动中
        return {"ok": True, "started": True, "pid": proc.pid, "heartbeat": read_heartbeat()}
    except Exception as e:
        return {"ok": False, "error": f"启动失败: {e}"}


def stop_scheduler_process() -> dict:
    """根据心跳文件中的 PID 结束 scheduler 进程."""
    hb = read_heartbeat()
    pid = hb.get("pid")
    if not pid or not is_process_alive(pid):
        # 进程已不存在, 强制把心跳标为离线
        write_heartbeat(running=False, pid=pid)
        return {"ok": True, "stopped": False, "message": "scheduler 未运行"}

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
            # 等待 3 秒, 如仍存活则 SIGKILL
            for _ in range(6):
                if not is_process_alive(pid):
                    break
                time.sleep(0.5)
            else:
                os.kill(pid, signal.SIGKILL)

        write_heartbeat(running=False, pid=pid)
        return {"ok": True, "stopped": True, "pid": pid}
    except Exception as e:
        return {"ok": False, "error": f"停止失败: {e}"}
