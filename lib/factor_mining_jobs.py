# -*- coding: utf-8 -*-
"""
通用后台挖掘任务注册表 (GP / RL / LLM增强GP / 未来扩展)

设计目标:
  - 页面切换/关闭不杀后台线程 (线程独立);
  - 任意时刻、任意页面可查询当前任务状态/进度/结果 (重连/恢复);
  - 同 kind 新任务会替换旧任务 (旧结果仍由 factor_eval_result 持久化, 不丢失);
  - 每个 kind 只保留最近一个任务 (单实例), 天然支持 GP 与 RL 并发 (不同 kind 互不影响)。
"""
import threading
import time
from typing import Any, Dict, Optional

_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_HISTORY_LIMIT = 20000


def start_job(kind: str) -> bool:
    """登记一个新任务 (覆盖同 kind 的旧任务), 返回 True"""
    with _lock:
        _jobs[kind] = {
            "kind": kind,
            "status": "running",       # running / done / error
            "progress": None,
            "result": None,
            "error": None,
            "history": [],
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        return True


def publish(kind: str, event: str, payload: Any) -> None:
    """任务在运行中广播事件 (progress/restart/elite/gene/migration 等)"""
    with _lock:
        j = _jobs.get(kind)
        if not j:
            return
        j["updated_at"] = time.time()
        if event == "progress":
            j["progress"] = payload
        j["history"].append({"event": event, "data": payload})
        if len(j["history"]) > _HISTORY_LIMIT:
            j["history"] = j["history"][-_HISTORY_LIMIT:]


def finish_job(kind: str, result: Optional[Any], error: Optional[str] = None) -> None:
    with _lock:
        j = _jobs.get(kind)
        if not j:
            return
        j["status"] = "error" if error else "done"
        j["result"] = result
        j["error"] = error
        j["updated_at"] = time.time()


def get_status(kind: str) -> Optional[Dict[str, Any]]:
    with _lock:
        j = _jobs.get(kind)
        if not j:
            return None
        return {
            "kind": kind,
            "status": j["status"],
            "progress": j["progress"],
            "result": j["result"],
            "error": j["error"],
            "history": list(j["history"]),
            "started_at": j["started_at"],
            "updated_at": j["updated_at"],
        }


def clear_job(kind: str) -> None:
    with _lock:
        _jobs.pop(kind, None)