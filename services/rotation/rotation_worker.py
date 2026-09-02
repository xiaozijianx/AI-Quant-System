# -*- coding: utf-8 -*-
"""轮动后台任务调度与状态持久化 (板块/概念共用, 按维度实例隔离).

合并自 sector_rotation/rotation_worker.py 与 concept_rotation/rotation_worker.py。
- 每维度一个 RotationWorker 实例: 独立锁/独立状态文件, 互不阻塞
  (保持原两包各自全局状态的隔离语义)
- _atomic_write_json 统一采用 concept 版 Windows 兼容实现
  (shutil.move + PermissionError 重试), 对 sector 是纯健壮性升级, 无口径影响

设计原则(原样保留):
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

from .dimension import RotationDimension, SECTOR, CONCEPT
from .rotation_core import execute_query, rank_with_phase
from .rotation_store import RotationStore, SECTOR_STORE, CONCEPT_STORE

# 状态文件目录 (项目根 data/)
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写入 JSON 文件 (Windows 兼容: shutil.move + PermissionError 重试)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{datetime.now().strftime('%H%M%S')}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for _ in range(5):
        try:
            shutil.move(str(tmp), str(path))
            return
        except PermissionError:
            time.sleep(0.02)
    # 兜底: 直接覆写 (极端情况下可能非原子)
    try:
        path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
        tmp.unlink(missing_ok=True)
    except Exception:
        pass


class RotationWorker:
    """单维度后台任务 worker (状态/锁/状态文件按维度隔离)."""

    def __init__(self, dim: RotationDimension, store: RotationStore):
        self.dim = dim
        self.store = store
        self.status_file = DATA_DIR / dim.status_file
        self._state_lock = threading.Lock()
        self._running = False
        self._current_job_type: Optional[str] = None
        self._current_date: Optional[str] = None
        self._progress = 0
        self._total = 0
        self._last_status = "idle"
        self._message = ""
        self._started_at: Optional[str] = None
        self._stop_requested = False

    # ---- 状态读写 ----

    def _write_status(self) -> None:
        with self._state_lock:
            status = {
                "running": self._running,
                "job_type": self._current_job_type,
                "current_date": self._current_date,
                "progress": self._progress,
                "total": self._total,
                "last_status": self._last_status,
                "message": self._message,
                "started_at": self._started_at,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        _atomic_write_json(self.status_file, status)

    def _set_running(self, job_type: str, total: int, message: str = "") -> None:
        with self._state_lock:
            self._running = True
            self._current_job_type = job_type
            self._current_date = None
            self._progress = 0
            self._total = total
            self._last_status = "running"
            self._message = message
            self._started_at = datetime.now().isoformat(timespec="seconds")
            self._stop_requested = False
        print(f"{self.dim.log_prefix} 任务开始: {job_type}, 总数 {total}, 消息: {message}", flush=True)
        self._write_status()

    def _set_progress(self, current_date: str, progress: int, message: str = "") -> None:
        with self._state_lock:
            self._current_date = current_date
            self._progress = progress
            if message:
                self._message = message
        print(f"{self.dim.log_prefix} 进度: {progress}/{self._total}, 当前日期 {current_date}, 消息: {message}", flush=True)
        self._write_status()

    def _set_finished(self, status: str, message: str = "") -> None:
        with self._state_lock:
            self._running = False
            self._last_status = status
            if message:
                self._message = message
            # 保留 job_type / current_date 供前端查看最后一次信息
        print(f"{self.dim.log_prefix} 任务结束: {status}, 消息: {message}", flush=True)
        self._write_status()

    def get_status(self) -> dict:
        """读取当前运行状态(优先从内存, 内存未加载则读文件)."""
        if not self.status_file.exists():
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
            return json.loads(self.status_file.read_text(encoding="utf-8"))
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

    # ---- 任务控制 ----

    def _check_stop(self) -> bool:
        with self._state_lock:
            return self._stop_requested

    def stop_current_job(self) -> dict:
        """停止当前运行的任务."""
        with self._state_lock:
            if not self._running:
                return {"ok": False, "error": "没有正在运行的任务"}
            self._stop_requested = True
            job_type = self._current_job_type
        self._set_finished("stopped", f"任务已停止: {job_type}")
        return {"ok": True, "message": f"已停止任务: {job_type}"}

    # ---- 交易日与计算 ----

    def _get_trading_dates(self, days: int = 20, end_date: Optional[str] = None) -> List[str]:
        """从日线数据表查询最近 N 个交易日."""
        params = []
        conditions = []
        if end_date:
            conditions.append("trade_date <= %s")
            params.append(end_date)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        rows = execute_query(
            f"""
            SELECT DISTINCT trade_date
            FROM {self.dim.daily_table}
            {where_clause}
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            tuple(params + [days]),
        )
        return sorted([str(r["trade_date"]) for r in rows], reverse=False)

    def _compute_and_save(self, trade_date: str, level: int = 2, top_n: Optional[int] = None) -> int:
        """计算并写入单个交易日数据."""
        try:
            df = rank_with_phase(
                self.dim,
                level=level,
                end_date=trade_date,
                lookback_days=self.dim.lookback_default,
                top_n=top_n,
            )
            if df.empty:
                print(f"{self.dim.log_prefix} {trade_date} 计算结果为空, 跳过", flush=True)
                return 0
            rows = self.store.save_day(df, trade_date, level=level if self.dim.has_level else 2)
            print(f"{self.dim.log_prefix} {trade_date} 写入 {rows} 条", flush=True)
            return rows
        except Exception as e:
            print(f"{self.dim.log_prefix} {trade_date} 计算失败: {e}", flush=True)
            traceback.print_exc()
            raise

    def _run_refresh(self, trade_date: str, level: int = 2) -> None:
        """后台线程: 刷新单个日期. running 状态由 start_refresh 提前写入."""
        try:
            if self._check_stop():
                self._set_finished("stopped", "任务已停止")
                return
            self._set_progress(trade_date, 0, f"正在计算 {trade_date} ...")
            # 短暂让出 GIL, 让前端 API 有机会响应
            time.sleep(0.05)
            rows = self._compute_and_save(trade_date, level=level)
            if self._check_stop():
                self._set_finished("stopped", "任务已停止")
                return
            self._set_progress(trade_date, 1, f"{trade_date} 计算完成, 写入 {rows} 条")
            self._set_finished("success", f"{trade_date} 计算完成, 写入 {rows} 条")
        except Exception as e:
            print(f"{self.dim.log_prefix} 单日刷新失败: {e}", flush=True)
            traceback.print_exc()
            self._set_finished("error", f"计算失败: {e}")

    def _run_rebuild(self, dates: List[str], level: int = 2) -> None:
        """后台线程: 批量重建指定日期列表.

        单日失败会记录错误并继续计算后续日期, 不会中断整个任务。
        """
        if not dates:
            self._set_finished("error", f"未找到{self.dim.label}日线数据, 请先运行{self.dim.label}数据准备")
            return

        self._set_running("rebuild", total=len(dates),
                          message=f"开始重建最近 {len(dates)} 个交易日")
        failed_dates = []
        try:
            for i, trade_date in enumerate(dates, start=1):
                if self._check_stop():
                    self._set_finished("stopped", "任务已停止")
                    return
                self._set_progress(trade_date, i - 1, f"正在计算 {trade_date} ({i}/{len(dates)}) ...")
                try:
                    self._compute_and_save(trade_date, level=level)
                    self._set_progress(trade_date, i, f"{trade_date} 完成 ({i}/{len(dates)})")
                except Exception as e:
                    failed_dates.append(trade_date)
                    print(f"{self.dim.log_prefix} {trade_date} 失败, 继续后续日期: {e}", flush=True)
                    self._set_progress(trade_date, i, f"{trade_date} 失败 ({i}/{len(dates)}), 继续...")
                # 每算完一天让出 GIL, 避免阻塞前端 API
                time.sleep(0.05)

            if failed_dates:
                self._set_finished("error", f"重建完成, 但 {len(failed_dates)} 天失败: {', '.join(failed_dates)}")
            else:
                self._set_finished("success", f"重建完成, 共 {len(dates)} 个交易日")
        except Exception as e:
            print(f"{self.dim.log_prefix} 批量重建失败: {e}", flush=True)
            traceback.print_exc()
            self._set_finished("error", f"重建失败: {e}")

    def start_refresh(self, trade_date: Optional[str] = None, level: int = 2) -> dict:
        """启动单日刷新任务."""
        with self._state_lock:
            if self._running:
                return {"ok": False, "error": "已有任务在运行, 请等待完成"}
            self._running = True

        if not trade_date:
            dates = self._get_trading_dates(days=1)
            if not dates:
                self._set_finished("error", f"未找到{self.dim.label}日线数据")
                return {"ok": False, "error": f"未找到{self.dim.label}日线数据"}
            trade_date = dates[-1]

        # 先写入 running 状态, 再启动线程, 确保前端立即能读到状态
        self._set_running("refresh", total=1, message=f"正在计算 {trade_date}")
        t = threading.Thread(target=self._run_refresh, args=(trade_date, level), daemon=True)
        t.start()
        return {"ok": True, "message": f"已启动单日刷新: {trade_date}"}

    def start_rebuild(self, days: int = 20, level: int = 2,
                      end_date: Optional[str] = None) -> dict:
        """启动批量重建任务."""
        with self._state_lock:
            if self._running:
                return {"ok": False, "error": "已有任务在运行, 请等待完成"}
            self._running = True

        # 先查询交易日列表, 确保前端进度条总数准确
        dates = self._get_trading_dates(days=days, end_date=end_date)
        if not dates:
            self._set_finished("error", f"未找到{self.dim.label}日线数据, 请先运行{self.dim.label}数据准备")
            return {"ok": False, "error": f"未找到{self.dim.label}日线数据, 请先运行{self.dim.label}数据准备"}

        # 先写入 running 状态, 再启动线程, 确保前端立即能读到状态
        date_range = f"{dates[0]} ~ {dates[-1]}"
        self._set_running("rebuild", total=len(dates),
                          message=f"开始重建 {date_range} 共 {len(dates)} 个交易日")
        t = threading.Thread(target=self._run_rebuild, args=(dates, level), daemon=True)
        t.start()
        return {"ok": True, "message": f"已启动重建 {date_range} 共 {len(dates)} 个交易日"}


# 维度实例 (路由与兼容层共用)
SECTOR_WORKER = RotationWorker(SECTOR, SECTOR_STORE)
CONCEPT_WORKER = RotationWorker(CONCEPT, CONCEPT_STORE)
