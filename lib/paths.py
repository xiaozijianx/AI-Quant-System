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

# 关键产出 (按域分子目录, 与页面分层一致)
OUTPUTS_LIVE_DIR    = OUTPUTS_DIR / "live"        # 实盘/模拟引擎状态
OUTPUTS_REVIEW_DIR  = OUTPUTS_DIR / "review"      # 复盘归因 (策略注册表/WF实验)
OUTPUTS_DRAGON_DIR  = OUTPUTS_DIR / "dragon"      # 龙头回测产物
OUTPUTS_CACHE_DIR   = OUTPUTS_DIR / "cache"       # 引擎缓存 (行业映射等)
OUTPUTS_MORNING_DIR = OUTPUTS_DIR / "morning"     # 晨会报告

OUTPUTS_LIVE_STATE      = OUTPUTS_LIVE_DIR / "live_state.json"
OUTPUTS_LIVE_STATE_REAL = OUTPUTS_LIVE_DIR / "live_state_real.json"
OUTPUTS_APPROVALS       = OUTPUTS_LIVE_DIR / "live_approvals.json"
OUTPUTS_REAL_PNL        = OUTPUTS_LIVE_DIR / "real_pnl_history.json"
OUTPUTS_EVOLVE_REGISTRY = OUTPUTS_REVIEW_DIR / "strategy_registry.json"
OUTPUTS_INDUSTRY_CACHE  = OUTPUTS_CACHE_DIR / "sw1_industry_map.json"
OUTPUTS_RESEARCH        = OUTPUTS_MORNING_DIR

# 全项目唯一环境变量文件
ENV_FILE = PROJECT_ROOT / ".env"


def setup_sys_path() -> None:
    """把工作台根目录与 lib/ 加入 sys.path (services/* 与 lib/* 均可按包导入)"""
    for p in (PROJECT_ROOT, LIB_DIR):
        sp = str(p)
        if p.exists() and sp not in sys.path:
            sys.path.insert(0, sp)


# 确保 outputs 及其按域子目录存在
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
for _sub in (OUTPUTS_LIVE_DIR, OUTPUTS_REVIEW_DIR, OUTPUTS_DRAGON_DIR,
             OUTPUTS_CACHE_DIR, OUTPUTS_MORNING_DIR):
    _sub.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
