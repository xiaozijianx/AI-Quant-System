# -*- coding: utf-8 -*-
# CASE-AI 量化系统: 定时调度器（数据增量 + 晨会分析 + 实盘时段启停）
"""
TradingScheduler -- A 股交易日自动运行: 数据增量 / 晨会简报 / 模拟盘启停

单独进程的原因:
    - Web (app.py) 与调度解耦：浏览器关了不影响调度，调度挂了不影响 Web。
    - APScheduler + cron。

4 个 cron job（周一到周五，时区 Asia/Shanghai）:
    08:30   job_data_refresh   -> .env 中 CASE_A_BOARD_DATA_PREP_DIR/run_daily.py
    09:00   job_morning_brief  -> 自动生成并推送投资晨会简报
    09:30   job_start_engine   -> 启动模拟盘 LiveSimRunner
    14:55   job_stop_engine    -> 停止主循环

每个任务都可以通过 Web「系统状态」页面独立开关, 配置保存在 data/scheduler_config.json。
主循环状态在 outputs/live_state.json，进程重启可从最近一次 state 恢复。

用法:
    python scheduler.py
    python scheduler.py --simulate
    python scheduler.py --job data | morning | engine | all
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from dotenv import load_dotenv
from lib.paths import ENV_FILE, PROJECT_ROOT, setup_sys_path

load_dotenv(ENV_FILE)

setup_sys_path()

from lib.live_simulator import LiveSimRunner, merge_watch_codes
from lib.scheduler_config import (
    load_scheduler_config,
    is_job_enabled,
    write_heartbeat,
    refresh_heartbeat,
    set_boot_time,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("trading-scheduler")


def _case_a_prep_dir() -> Path | None:
    """CASE-A「板块数据准备」目录（内含 run_daily.py），由 .env CASE_A_BOARD_DATA_PREP_DIR 指定."""
    raw = (os.environ.get("CASE_A_BOARD_DATA_PREP_DIR") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


_CASE_A_DIR = _case_a_prep_dir()
CASE_A_RUN_DAILY = (_CASE_A_DIR / "run_daily.py") if _CASE_A_DIR else None


# ============================================================
# 任务
# ============================================================

def job_data_refresh():
    """08:30: 在项目目录下运行 run_daily.py（若未配置 CASE_A_BOARD_DATA_PREP_DIR 则跳过并打日志）"""
    log.info("[JOB] 数据增量 - 触发")
    if not is_job_enabled("data_refresh"):
        log.info("[JOB] 数据增量 - 已禁用, 跳过")
        return
    if not _CASE_A_DIR:
        log.error(
            "未配置环境变量 CASE_A_BOARD_DATA_PREP_DIR（指向内含 run_daily.py 的目录）；已跳过。"
        )
        return
    if not CASE_A_RUN_DAILY or not CASE_A_RUN_DAILY.exists():
        log.error("找不到 run_daily.py: %s", CASE_A_RUN_DAILY)
        return
    ret = subprocess.run([sys.executable, str(CASE_A_RUN_DAILY)], cwd=str(_CASE_A_DIR))
    log.info("[JOB] 数据增量 - 完成 (returncode=%s)", ret.returncode)


def job_start_engine():
    log.info("[JOB] 启动主循环 - 触发")
    if not is_job_enabled("live_engine"):
        log.info("[JOB] 启动主循环 - 已禁用, 跳过")
        return
    sim = LiveSimRunner()
    if sim.status().get("running"):
        log.info("[JOB] 主循环已在运行, 跳过")
        return
    watch = merge_watch_codes([])
    if not watch:
        log.warning("[JOB] 监控池为空, 不启动")
        return
    msg = sim.start(watch_stocks=watch, dry_run=True, cycle_seconds=60)
    log.info(f"[JOB] 启动主循环 - 完成: {msg.splitlines()[0] if msg else 'OK'}")


def job_stop_engine():
    log.info("[JOB] 停止主循环 - 触发")
    if not is_job_enabled("live_engine"):
        log.info("[JOB] 停止主循环 - 已禁用, 跳过")
        return
    sim = LiveSimRunner()
    if not sim.status().get("running"):
        log.info("[JOB] 主循环未在运行, 跳过")
        return
    msg = sim.stop()
    log.info("[JOB] 停止主循环 - 完成: %s", msg or "OK")


def job_morning_brief():
    """09:00: 自动运行投资晨会工作流并推送简报."""
    log.info("[JOB] 晨会分析 - 触发")
    if not is_job_enabled("morning_brief"):
        log.info("[JOB] 晨会分析 - 已禁用, 跳过")
        return
    try:
        from morning_brief.graph import build_graph
        graph = build_graph()
        result = graph.invoke({
            "trigger_time":     datetime.now().isoformat(timespec="seconds"),
            "industry_level":   2,
            "top_n_industries": 5,
            "top_n_stocks":     10,
            "lookback_days":    90,
            "sample_stocks":    20,
            "messages":         [],
        })
        push_result = result.get("push_result", {})
        log.info("[JOB] 晨会分析 - 完成, 推送结果: %s", push_result)
    except Exception as e:
        log.exception("[JOB] 晨会分析 - 执行失败: %s", e)


# ============================================================
# Stage 8.7 (Z11): file-based cron spec 加载 — 对标 Cline cron spec
# ============================================================
# 设计说明（对标 Cline sdk/packages/core/src/cron/specs/）:
#     Cline 通过 cron spec 文件（yaml）定义定时任务，含 name / schedule / command 等字段，
#     由 CronReconciler 同步到 DB，CronWatcher 监听变更，CronMaterializer 物化队列，
#     CronRunner claim + execute + report。
#
# 本系统不引入 Cline 五组件架构，仅借鉴"file-based spec"理念：
#     - 扫描 agent_config/cron/ 目录下 *.yaml / *.yml 文件
#     - 每个文件定义一个 cron job（name / description / schedule / timezone / command / enabled）
#     - 解析 schedule 字段（标准 cron 表达式 "分 时 日 月 周"）为 APScheduler CronTrigger
#     - 注册到 BlockingScheduler（replace_existing=True 允许覆盖同名硬编码 job）
#
# 与现有 4 个硬编码 job 的关系:
#     - 硬编码 job 继续保留（用户规则：不要修改已正确运行的功能）
#     - yaml spec 可覆盖同名硬编码 job（如 spec name="data_refresh" 覆盖硬编码 data_refresh）
#     - yaml spec 也可新增硬编码之外的 job
#     - agent_config/cron/ 目录不存在时跳过 yaml 加载，不影响硬编码 job
#
# spec 文件示例（agent_config/cron/daily_data_refresh.yaml）:
#     ---
#     name: daily_data_refresh
#     description: 每日盘前数据刷新
#     schedule: "30 8 * * 1-5"     # 周一到周五 08:30
#     timezone: "Asia/Shanghai"
#     command: "python run_daily.py"
#     enabled: true


def _cron_specs_dir() -> Path:
    """返回 cron spec 文件目录 — Stage 8.7 新增

    目录路径: <PROJECT_ROOT>/agent_config/cron/
    """
    return PROJECT_ROOT / "agent_config" / "cron"


def load_cron_specs(specs_dir: Path | None = None) -> list[dict]:
    """加载 cron spec 文件 — Stage 8.7 新增，对标 Cline cron-reconciler

    扫描 specs_dir 下所有 *.yaml / *.yml 文件，解析为 spec 字典列表。
    单个文件解析失败时记录 warning 并跳过该文件（不影响其他文件加载）。

    Args:
        specs_dir: spec 目录路径，None 时使用默认路径 _cron_specs_dir()

    Returns:
        spec 字典列表，每个字典含 name / description / schedule / timezone /
        command / enabled 字段。目录不存在时返回空列表
    """
    specs_path = specs_dir if specs_dir is not None else _cron_specs_dir()
    if not specs_path.exists() or not specs_path.is_dir():
        return []

    try:
        import yaml
    except ImportError:
        log.warning("[CRON-SPEC] PyYAML 未安装，跳过 yaml spec 加载")
        return []

    specs: list[dict] = []
    for spec_file in sorted(specs_path.glob("*.y*ml")):
        try:
            content = spec_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                log.warning("[CRON-SPEC] %s 顶层非 dict，跳过", spec_file.name)
                continue
            # 校验必填字段
            name = data.get("name")
            schedule = data.get("schedule")
            command = data.get("command")
            if not name or not schedule or not command:
                log.warning(
                    "[CRON-SPEC] %s 缺少必填字段（name/schedule/command），跳过",
                    spec_file.name,
                )
                continue
            spec = {
                "name": str(name),
                "description": str(data.get("description", "")),
                "schedule": str(schedule),
                "timezone": str(data.get("timezone", "Asia/Shanghai")),
                "command": str(command),
                "enabled": bool(data.get("enabled", True)),
                "source_file": spec_file.name,
            }
            specs.append(spec)
            log.info(
                "[CRON-SPEC] 加载 %s: name=%s schedule=%s",
                spec_file.name, spec["name"], spec["schedule"],
            )
        except Exception as e:
            log.warning("[CRON-SPEC] 解析 %s 失败: %s", spec_file.name, e)
            continue

    return specs


def _parse_cron_schedule(schedule: str) -> CronTrigger | None:
    """解析 cron 表达式为 CronTrigger — Stage 8.7 新增

    支持标准 5 字段 cron 表达式 "分 时 日 月 周"（如 "30 8 * * 1-5"）。
    解析失败时返回 None（调用方决定是否跳过该 job）。

    Args:
        schedule: 标准 cron 表达式

    Returns:
        CronTrigger 实例，解析失败时返回 None
    """
    fields = schedule.strip().split()
    if len(fields) != 5:
        log.warning("[CRON-SPEC] schedule 字段数不为 5: %s", schedule)
        return None
    try:
        return CronTrigger(
            minute=fields[0],
            hour=fields[1],
            day=fields[2],
            month=fields[3],
            day_of_week=fields[4],
        )
    except Exception as e:
        log.warning("[CRON-SPEC] schedule 解析失败 %s: %s", schedule, e)
        return None


def _make_spec_job_executor(command: str, spec_name: str):
    """构造 spec job 的执行函数 — Stage 8.7 新增

    返回一个无参函数，执行时通过 subprocess 运行 command。
    command 默认在 PROJECT_ROOT 下执行。

    Args:
        command: 要执行的命令（如 "python run_daily.py"）
        spec_name: spec 名称（用于日志标识）

    Returns:
        无参可调用函数，供 sched.add_job 注册
    """
    def _execute():
        log.info("[CRON-SPEC] %s - 触发, command=%s", spec_name, command)
        # 用 shell=True 支持复杂命令（含管道 / 重定向）
        ret = subprocess.run(
            command,
            shell=True,
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
        )
        log.info(
            "[CRON-SPEC] %s - 完成 (returncode=%s)",
            spec_name, ret.returncode,
        )
    return _execute


def register_cron_specs(sched: BlockingScheduler, specs: list[dict]) -> int:
    """将 yaml spec 注册到 BlockingScheduler — Stage 8.7 新增

    对每个 spec:
        1. 跳过 enabled=False 的 spec
        2. 解析 schedule 为 CronTrigger，解析失败跳过
        3. 构造执行函数
        4. 调用 sched.add_job 注册（replace_existing=True 允许覆盖同名硬编码 job）

    Args:
        sched: BlockingScheduler 实例
        specs: load_cron_specs 返回的 spec 字典列表

    Returns:
        成功注册的 spec 数量
    """
    registered = 0
    for spec in specs:
        if not spec["enabled"]:
            log.info("[CRON-SPEC] %s 已禁用，跳过注册", spec["name"])
            continue

        trigger = _parse_cron_schedule(spec["schedule"])
        if trigger is None:
            continue

        executor = _make_spec_job_executor(spec["command"], spec["name"])
        try:
            sched.add_job(
                executor,
                id=spec["name"],
                name=spec.get("description") or spec["name"],
                trigger=trigger,
                timezone=spec["timezone"],
                replace_existing=True,
            )
            log.info(
                "[CRON-SPEC] 注册 job: id=%s schedule=%s tz=%s",
                spec["name"], spec["schedule"], spec["timezone"],
            )
            registered += 1
        except Exception as e:
            log.warning("[CRON-SPEC] 注册 %s 失败: %s", spec["name"], e)
            continue

    return registered


# ============================================================
# 主入口
# ============================================================

def _start_heartbeat_thread():
    """启动后台心跳刷新线程, 每 30 秒更新一次 scheduler_heartbeat.json."""
    set_boot_time()
    write_heartbeat(running=True)

    def _loop():
        while True:
            time.sleep(30)
            try:
                refresh_heartbeat()
            except Exception as e:
                log.warning("[HEARTBEAT] 刷新心跳失败: %s", e)

    t = threading.Thread(target=_loop, daemon=True, name="scheduler-heartbeat")
    t.start()
    return t


def _on_exit():
    """正常退出时标记 scheduler 离线."""
    try:
        write_heartbeat(running=False)
        log.info("[EXIT] 心跳已标记为离线")
    except Exception as e:
        log.warning("[EXIT] 标记离线失败: %s", e)


def main():
    parser = argparse.ArgumentParser(
        description="实盘工作台调度器（与 app.py 共用 .env）",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="模拟模式: 立刻把每个 job 跑一次然后退出",
    )
    parser.add_argument(
        "--job",
        choices=["data", "morning", "engine", "all"],
        default="all",
        help="只注册某一组 job: data | morning | engine | all（默认）",
    )
    args = parser.parse_args()

    # 读取并打印当前开关配置
    cfg = load_scheduler_config()

    if args.simulate:
        log.info("=" * 60)
        log.info("[SIMULATE] 模拟模式")
        log.info("[SIMULATE] 配置: data_refresh=%s morning_brief=%s live_engine=%s",
                 cfg["data_refresh"], cfg["morning_brief"], cfg["live_engine"])
        log.info("=" * 60)
        if args.job in ("data", "all"):
            job_data_refresh()
        if args.job in ("morning", "all"):
            job_morning_brief()
        if args.job in ("engine", "all"):
            job_start_engine()
            job_stop_engine()
        return

    sched = BlockingScheduler(timezone="Asia/Shanghai")

    if args.job in ("data", "all"):
        sched.add_job(
            job_data_refresh,
            id="data_refresh",
            name="08:30 数据增量",
            trigger=CronTrigger(hour=8, minute=30, day_of_week="mon-fri",
                                timezone="Asia/Shanghai"),
        )
        log.info("[REG] 08:30 CASE_A_BOARD_DATA_PREP_DIR -> run_daily.py")

    if args.job in ("morning", "all"):
        sched.add_job(
            job_morning_brief,
            id="morning_brief",
            name="09:00 晨会分析",
            trigger=CronTrigger(hour=9, minute=0, day_of_week="mon-fri",
                                timezone="Asia/Shanghai"),
        )
        log.info("[REG] 09:00 晨会分析")

    if args.job in ("engine", "all"):
        sched.add_job(
            job_start_engine,
            id="start_engine",
            name="09:30 启动主循环",
            trigger=CronTrigger(hour=9, minute=30, day_of_week="mon-fri",
                                timezone="Asia/Shanghai"),
        )
        sched.add_job(
            job_stop_engine,
            id="stop_engine",
            name="14:55 停止主循环",
            trigger=CronTrigger(hour=14, minute=55, day_of_week="mon-fri",
                                timezone="Asia/Shanghai"),
        )
        log.info("[REG] 09:30 / 14:55 引擎启停")

    # Stage 8.7 (Z11): 加载并注册 yaml cron spec — 对标 Cline file-based cron spec
    # agent_config/cron/ 目录不存在时返回空列表，不影响硬编码 job
    # yaml spec 可覆盖同名硬编码 job（replace_existing=True）
    if args.job == "all":
        specs = load_cron_specs()
        if specs:
            registered_count = register_cron_specs(sched, specs)
            log.info("[REG] yaml cron spec: 加载 %d 个, 注册 %d 个", len(specs), registered_count)
        else:
            log.info("[REG] agent_config/cron/ 无 yaml spec 或目录不存在, 跳过")

    # 启动心跳并注册退出清理
    _start_heartbeat_thread()
    atexit.register(_on_exit)

    log.info("=" * 60)
    log.info("[BOOT] 调度器前台运行（Ctrl+C 退出） cwd=%s", PROJECT_ROOT)
    log.info("       当前时间 %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("       配置: data_refresh=%s morning_brief=%s live_engine=%s",
             cfg["data_refresh"], cfg["morning_brief"], cfg["live_engine"])
    log.info("=" * 60)

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("[EXIT] 调度器已退出")


# ============================================================
# Stage 14.2 (Z11): Cron 完整架构入口 — 对标 Cline cron 完整模块
# CronReconciler + CronMaterializer + CronRunner 三件套
# ============================================================


def start_scheduler_with_cron(
    specs_dir: Path | None = None,
    store_path: Path | None = None,
    enable_reconcile_loop: bool = True,
) -> BlockingScheduler:
    """启动带完整 cron 架构的 scheduler — Stage 14.2 新增

    相比 main() 的硬编码 job，此入口:
        1. 初始 reconcile yaml spec 到 scheduler
        2. 启动 daemon 线程定期 reconcile（spec 变更自动生效）
        3. spec 和 job 状态持久化到 cron_store.json

    保留原有 load_cron_specs / register_cron_specs 函数（向后兼容），
    此函数作为推荐入口供需要完整 cron 架构的场景使用。

    Args:
        specs_dir: spec 目录路径，None 时使用默认 _cron_specs_dir()
        store_path: 状态持久化文件路径，None 时使用默认 agent_config/cron_store.json
        enable_reconcile_loop: 是否启动定期 reconcile 线程，False 时仅初始 reconcile

    Returns:
        已启动的 BlockingScheduler 实例
    """
    from agent.cron_materializer import CronMaterializer
    from agent.cron_reconciler import CronReconciler

    specs_path = specs_dir if specs_dir is not None else _cron_specs_dir()
    store_file = store_path if store_path is not None else (PROJECT_ROOT / "agent_config" / "cron_store.json")

    sched = BlockingScheduler(timezone="Asia/Shanghai")
    materializer = CronMaterializer(store_file)
    reconciler = CronReconciler(
        sched=sched,
        specs_dir=specs_path,
        materializer=materializer,
    )

    # 初始 reconcile
    result = reconciler.reconcile()
    log.info(
        "[CRON-ARCH] 初始 reconcile: added=%d, removed=%d, updated=%d",
        len(result["added"]), len(result["removed"]), len(result["updated"]),
    )

    # 启动定期 reconcile 线程（daemon）
    if enable_reconcile_loop:
        import asyncio as _asyncio
        t = threading.Thread(
            target=lambda: _asyncio.run(reconciler.start()),
            daemon=True,
            name="cron-reconciler",
        )
        t.start()
        log.info("[CRON-ARCH] reconcile 线程已启动（interval=60s）")

    return sched


if __name__ == "__main__":
    main()
