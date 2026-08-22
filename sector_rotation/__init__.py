# -*- coding: utf-8 -*-
"""板块轮动分析模块.

提供:
- rotation_core:    板块轮动核心计算(与 CASE-B2 口径对齐)
- rotation_store:   数据库读写
- rotation_worker:  后台任务调度与状态持久化
- indicator_notes:  指标中文解释

页面入口: /sector-rotation
API 入口: /api/sector-rotation/*
"""
