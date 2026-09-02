# -*- coding: utf-8 -*-
"""
services/rotation/ -- 板块/概念轮动统一引擎

由 sector_rotation/ 与 concept_rotation/ 两个子包合并而来 (Stage 1 去重复)。
两维度约 90% 代码相同, 差异全部显式收敛到 RotationDimension 维度配置:

- 位置/文案: label / route_prefix / page_path / status_file / log_prefix
- 数据表: result_table / daily_table / relevance_table
- 指标口径: mom/rs 窗口与列名 / vol 窗口 / 最小长度 / lookback / score 合成权重
- 行为开关: align_index (concept 对齐日期索引, sector 不对齐, 保持各自重构前口径)
           has_level (sector 特有 level 维度)

对外契约不变:
- API 路径 /api/sector-rotation/* 与 /api/concept-rotation/* 不变
- /api/sector-rotation/detail?sector= / sector-index?sector=
  与 /api/concept-rotation/detail?concept_code= / concept-index?concept_code=
  的参数名与响应结构不变 (dragon_review 页跨页依赖)
- 旧包 sector_rotation/ 与 concept_rotation/ 保留为兼容 re-export 入口,
  外部引用 (routes/dragon_review.py、agent_config/skills/*) 无需立即改动
"""
