# -*- coding: utf-8 -*-
# CASE-AI量化系统 路径常量（见 lib/ 旁目录树；唯一 .env 见 ENV_FILE）
import sys
from pathlib import Path

# 工作台根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 页面业务层子目录 (Stage 1-2 重构: 根目录散包已收编至 services/, 引擎类归 lib/)
LIVE_TRADING_DIR    = PROJECT_ROOT / "services" / "live" / "trading"
ALERTING_DIR        = PROJECT_ROOT / "services" / "live" / "alerting"
DRAGON_STRATEGY_DIR = PROJECT_ROOT / "services" / "dragon" / "strategy"
MORNING_BRIEF_DIR   = PROJECT_ROOT / "services" / "morning" / "brief"
PAGES_DIR           = PROJECT_ROOT / "pages"
LIB_DIR             = PROJECT_ROOT / "lib"
CONFIG_DIR          = PROJECT_ROOT / "config"
OUTPUTS_DIR         = PROJECT_ROOT / "outputs"
DATA_DIR            = PROJECT_ROOT / "data"
ML_STRATEGY_DIR     = LIB_DIR / "ml_strategy"

# 复盘归因 (review) 子模块: attribution / parameter_tuning / strategy_lifecycle
# 均已收编至 services/review/, 通过 PROJECT_ROOT 在 sys.path 即可 import services.*
ATTRIBUTION_DIR        = PROJECT_ROOT / "services" / "review" / "attribution"
PARAMETER_TUNING_DIR   = PROJECT_ROOT / "services" / "review" / "parameter_tuning"
STRATEGY_LIFECYCLE_DIR = PROJECT_ROOT / "services" / "review" / "strategy_lifecycle"

# 关键产出
OUTPUTS_LIVE_STATE      = OUTPUTS_DIR / "live_state.json"
OUTPUTS_RESEARCH        = MORNING_BRIEF_DIR / "outputs" / "reports"
OUTPUTS_EVOLVE_REGISTRY = OUTPUTS_DIR / "strategy_registry.json"

# 全项目唯一环境变量文件
ENV_FILE = PROJECT_ROOT / ".env"


def setup_sys_path() -> None:
    """把工作台根目录与 lib/ 加入 sys.path (services/* 与 lib/* 均可按包导入)"""
    for p in (PROJECT_ROOT, LIB_DIR):
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.insert(0, sp)


# 确保 outputs 与 data 目录存在
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
