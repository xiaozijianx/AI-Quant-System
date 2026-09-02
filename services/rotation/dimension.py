# -*- coding: utf-8 -*-
"""轮动维度配置: 板块/概念两实例, 收敛全部差异点.

每个字段的重构前出处见注释 (sector_rotation/ 与 concept_rotation/ 对应行)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RotationDimension:
    # ---- 维度标识与文案 ----
    key: str                      # "sector" / "concept"
    label: str                    # "板块" / "概念" (文案前缀)
    log_prefix: str               # "[sector_rotation]" / "[concept_rotation]"
    route_prefix: str             # "/api/sector-rotation" / "/api/concept-rotation"
    page_path: str                # "/sector-rotation" / "/concept-rotation"
    settings_namespace: str       # page-settings 的 namespace

    # ---- 数据表 ----
    result_table: str             # 轮动结果表
    daily_table: str              # 日线数据表 (worker 取交易日用)
    relevance_table: str          # 相关股表

    # ---- 强度指标口径 ----
    mom_window: int               # 动量窗口: 21 / 10
    mom_z_col: str                # DB 列名: mom21_z / mom10_z
    rs_window: int                # 相对强度窗口: 60 / 20
    rs_z_col: str                 # DB 列名: rs60_z / rs20_z
    vol_short: int                # 量比短窗: 5 / 5
    vol_long: int                 # 量比长窗: 60 / 20
    min_strength_len: int         # 强度计算最小长度: 65 / 22
    min_deriv_len: int            # 导数计算最小长度: 60 / 35
    min_days: int                 # 批量加载最小天数: 70 / 22

    # ---- phase 判定 ----
    # 注意: sector=0.005 与 concept=0.5 量纲不同(历史口径差异, 原样保留, 禁止统一)。
    # ROC_20 为百分比值(×100), sector 的 0.005 实际为 0.005%, concept 的 0.5 为 0.5%。
    roc_threshold: float

    # ---- score 合成 ----
    # sector: 三因子等权 (mean); concept: MOM + RS + 0.5*VOL 加权。
    score_equal_weight: bool      # True=等权 mean, False=按 vol_weight 加权求和

    # ---- 行为开关 ----
    align_index: bool             # calc_strength_indicators 是否做日期索引对齐
                                  # (concept=True, sector=False, 保持重构前各自口径)
    has_level: bool = False       # sector 特有 level 维度 (前端恒用默认 2)
    has_concept_meta: bool = False  # concept_code/concept_name/source_prefix 三字段

    # ---- worker / 查询 ----
    lookback_default: int = 90    # rank_with_phase 默认 lookback: 90 / 40
    index_years_default: int = 2  # 指数查询默认年数: 2 / 1
    index_years_max: int = 5      # 指数查询年数上限: 5 / 3
    # 概念相关股按 concept_name 查(非 code), 板块按 sector_name+level 查
    relevant_stock_by_name: bool = False
    status_file: str = ""         # data/ 下的状态文件名
    vol_weight: float = 0.5       # 仅 score_equal_weight=False 时生效


SECTOR = RotationDimension(
    key="sector",
    label="板块",
    log_prefix="[sector_rotation]",
    route_prefix="/api/sector-rotation",
    page_path="/sector-rotation",
    settings_namespace="sector_rotation",
    result_table="trade_sector_rotation_daily",
    daily_table="trade_sector_daily",
    relevance_table="sector_stock_relevance",
    mom_window=21, mom_z_col="mom21_z",
    rs_window=60, rs_z_col="rs60_z",
    vol_short=5, vol_long=60,
    min_strength_len=65, min_deriv_len=60, min_days=70,
    roc_threshold=0.005,   # 历史口径原样保留(实际 0.005%, 注释曾写 0.5%, 疑似笔误待用户决策)
    score_equal_weight=True,
    align_index=False,
    has_level=True,
    lookback_default=90,
    index_years_default=2, index_years_max=5,
    relevant_stock_by_name=False,
    status_file="sector_rotation_status.json",
)

CONCEPT = RotationDimension(
    key="concept",
    label="概念",
    log_prefix="[concept_rotation]",
    route_prefix="/api/concept-rotation",
    page_path="/concept-rotation",
    settings_namespace="concept_rotation",
    result_table="trade_concept_rotation_daily",
    daily_table="concept_daily_full",
    relevance_table="concept_stock_relevance",
    mom_window=10, mom_z_col="mom10_z",
    rs_window=20, rs_z_col="rs20_z",
    vol_short=5, vol_long=20,
    min_strength_len=22, min_deriv_len=35, min_days=22,
    roc_threshold=0.5,     # 真实 0.5%
    score_equal_weight=False,
    vol_weight=0.5,
    align_index=True,
    has_level=False,
    lookback_default=40,
    index_years_default=1, index_years_max=3,
    relevant_stock_by_name=True,
    status_file="concept_rotation_status.json",
    has_concept_meta=True,
)
