# -*- coding: utf-8 -*-
"""概念轮动后台任务调度与状态持久化.

设计原则:
- 页面关闭不影响后端计算
- 状态写入 JSON 文件, 切换页面后可恢复
- 只保留简单状态(进度/消息), 不保留详细日志
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .rotation_core import execute_query, rank_concepts_with_phase
from .rotation_store import delete_all, save_day

# 状态文件路径
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATUS_FILE = DATA_DIR / "concept_rotation_status.json"

_state_lock = threading.Lock()
_running = False
_current_job_type: Optional[str] = None
_current_date: Optional[str] = None
_progress = 0
_total = 0
_last_status = "idle"
_message = ""
_started_at: Optional[str] = None
_stop_requested = False


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写入 JSON 文件, Windows 下兼容文件被占用的情况."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{datetime.now().strftime('%H%M%S%f')}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows 下 os.replace 对正在被读取的文件会报 PermissionError,
    # shutil.move 会退化为 copy+delete, 兼容性好。
    for _ in range(5):
        try:
            shutil.move(str(tmp), str(path))
            return
        except PermissionError:
            time.sleep(0.05)
    # 若仍失败, 直接覆盖写入(兜底)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status() -> None:
    """把当前状态写入 STATUS_FILE."""
    with _state_lock:
        status = {
            "running": _running,
            "job_type": _current_job_type,
            "current_date": _current_date,
            "progress": _progress,
            "total": _total,
            "last_status": _last_status,
            "message": _message,
            "started_at": _started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    _atomic_write_json(STATUS_FILE, status)


def _set_running(job_type: str, total: int, message: str = "") -> None:
    global _running, _current_job_type, _current_date, _progress, _total
    global _last_status, _message, _started_at, _stop_requested
    with _state_lock:
        _running = True
        _current_job_type = job_type
        _current_date = None
        _progress = 0
        _total = total
        _last_status = "running"
        _message = message
        _started_at = datetime.now().isoformat(timespec="seconds")
        _stop_requested = False
    print(f"[concept_rotation] 任务开始: {job_type}, 总数 {total}, 消息: {message}", flush=True)
    _write_status()


def _set_progress(current_date: str, progress: int, message: str = "") -> None:
    global _current_date, _progress, _message
    with _state_lock:
        _current_date = current_date
        _progress = progress
        if message:
            _message = message
    print(f"[concept_rotation] 进度: {progress}/{_total}, 当前日期 {current_date}, 消息: {message}", flush=True)
    _write_status()


def _set_finished(status: str, message: str = "") -> None:
    global _running, _last_status, _message, _current_job_type, _current_date
    with _state_lock:
        _running = False
        _last_status = status
        if message:
            _message = message
        # 保留 job_type / current_date 供前端查看最后一次信息
    print(f"[concept_rotation] 任务结束: {status}, 消息: {message}", flush=True)
    _write_status()


def get_status() -> dict:
    """读取当前运行状态(优先从内存, 内存未加载则读文件)."""
    if not STATUS_FILE.exists():
        return {
            "running": False,
            "job_type": None,
            "current_date": None,
            "progress": 0,
            "total": 0,
            "last_status": "idle",
            "message": "暂无数据, 请点击计算",
            "started_at": None,
            "updated_at": None,
        }
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "running": False,
            "job_type": None,
            "current_date": None,
            "progress": 0,
            "total": 0,
            "last_status": "error",
            "message": "状态文件读取失败",
            "started_at": None,
            "updated_at": None,
        }


def _check_stop() -> bool:
    global _stop_requested
    with _state_lock:
        return _stop_requested


def stop_current_job() -> dict:
    """停止当前运行的任务."""
    global _stop_requested
    with _state_lock:
        if not _running:
            return {"ok": False, "error": "没有正在运行的任务"}
        _stop_requested = True
        job_type = _current_job_type
    _set_finished("stopped", f"任务已停止: {job_type}")
    return {"ok": True, "message": f"已停止任务: {job_type}"}


def _get_trading_dates(days: int = 20, end_date: Optional[str] = None) -> List[str]:
    """从 concept_daily_full 查询最近 N 个交易日."""
    params = []
    conditions = []
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = execute_query(
        f"""
        SELECT DISTINCT trade_date
        FROM concept_daily_full
        {where_clause}
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        tuple(params + [days]),
    )
    return sorted([str(r["trade_date"]) for r in rows], reverse=False)


def _compute_and_save(trade_date: str, top_n: Optional[int] = None) -> int:
    """计算并写入单个交易日数据."""
    try:
        df = rank_concepts_with_phase(
            end_date=trade_date,
            lookback_days=40,
            top_n=top_n,
        )
        if df.empty:
            print(f"[concept_rotation] {trade_date} 计算结果为空, 跳过", flush=True)
            return 0
        rows = save_day(df, trade_date)
        print(f"[concept_rotation] {trade_date} 写入 {rows} 条", flush=True)
        return rows
    except Exception as e:
        print(f"[concept_rotation] {trade_date} 计算失败: {e}", flush=True)
        traceback.print_exc()
        raise


def _run_refresh(trade_date: str) -> None:
    """后台线程: 刷新单个日期. running 状态由 start_refresh 提前写入."""
    try:
        if _check_stop():
            _set_finished("stopped", "任务已停止")
            return
        _set_progress(trade_date, 0, f"正在计算 {trade_date} ...")
        # 短暂让出 GIL, 让前端 API 有机会响应
        time.sleep(0.05)
        rows = _compute_and_save(trade_date)
        if _check_stop():
            _set_finished("stopped", "任务已停止")
            return
        _set_progress(trade_date, 1, f"{trade_date} 计算完成, 写入 {rows} 条")
        _set_finished("success", f"{trade_date} 计算完成, 写入 {rows} 条")
    except Exception as e:
        print(f"[concept_rotation] 单日刷新失败: {e}", flush=True)
        traceback.print_exc()
        _set_finished("error", f"计算失败: {e}")


def _run_rebuild(dates: List[str]) -> None:
    """后台线程: 批量重建指定日期列表.

    单日失败会记录错误并继续计算后续日期, 不会中断整个任务。
    """
    if not dates:
        _set_finished("error", "未找到概念日线数据, 请先运行概念数据准备")
        return

    _set_running("rebuild", total=len(dates),
                 message=f"开始重建最近 {len(dates)} 个交易日")
    failed_dates = []
    try:
        for i, trade_date in enumerate(dates, start=1):
            if _check_stop():
                _set_finished("stopped", "任务已停止")
                return
            _set_progress(trade_date, i - 1, f"正在计算 {trade_date} ({i}/{len(dates)}) ...")
            try:
                _compute_and_save(trade_date)
                _set_progress(trade_date, i, f"{trade_date} 完成 ({i}/{len(dates)})")
            except Exception as e:
                failed_dates.append(trade_date)
                print(f"[concept_rotation] {trade_date} 失败, 继续后续日期: {e}", flush=True)
                _set_progress(trade_date, i, f"{trade_date} 失败 ({i}/{len(dates)}), 继续...")
            # 每算完一天让出 GIL, 避免阻塞前端 API
            time.sleep(0.05)

        if failed_dates:
            _set_finished("error", f"重建完成, 但 {len(failed_dates)} 天失败: {', '.join(failed_dates)}")
        else:
            _set_finished("success", f"重建完成, 共 {len(dates)} 个交易日")
    except Exception as e:
        print(f"[concept_rotation] 批量重建失败: {e}", flush=True)
        traceback.print_exc()
        _set_finished("error", f"重建失败: {e}")


def start_refresh(trade_date: Optional[str] = None) -> dict:
    """启动单日刷新任务."""
    global _running
    with _state_lock:
        if _running:
            return {"ok": False, "error": "已有任务在运行, 请等待完成"}
        _running = True

    if not trade_date:
        dates = _get_trading_dates(days=1)
        if not dates:
            _set_finished("error", "未找到概念日线数据")
            return {"ok": False, "error": "未找到概念日线数据"}
        trade_date = dates[-1]

    # 先写入 running 状态, 再启动线程, 确保前端立即能读到状态
    _set_running("refresh", total=1, message=f"正在计算 {trade_date}")
    t = threading.Thread(target=_run_refresh, args=(trade_date,), daemon=True)
    t.start()
    return {"ok": True, "message": f"已启动单日刷新: {trade_date}"}


def start_rebuild(days: int = 20,
                  end_date: Optional[str] = None) -> dict:
    """启动批量重建任务.

    参数:
        days: 回溯交易日数
        end_date: 结束日期(YYYY-MM-DD), 为空则取最新交易日
    """
    global _running
    with _state_lock:
        if _running:
            return {"ok": False, "error": "已有任务在运行, 请等待完成"}
        _running = True

    # 先查询交易日列表, 确保前端进度条总数准确
    dates = _get_trading_dates(days=days, end_date=end_date)
    if not dates:
        _set_finished("error", "未找到概念日线数据, 请先运行概念数据准备")
        return {"ok": False, "error": "未找到概念日线数据, 请先运行概念数据准备"}

    # 先写入 running 状态, 再启动线程, 确保前端立即能读到状态
    date_range = f"{dates[0]} ~ {dates[-1]}"
    _set_running("rebuild", total=len(dates),
                 message=f"开始重建 {date_range} 共 {len(dates)} 个交易日")
    t = threading.Thread(target=_run_rebuild, args=(dates,), daemon=True)
    t.start()
    return {"ok": True, "message": f"已启动重建 {date_range} 共 {len(dates)} 个交易日"}
