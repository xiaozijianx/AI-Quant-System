# -*- coding: utf-8 -*-
"""
lib/factor_rl/ -- RL 因子挖掘引擎 (深度复刻 AlphaMaster model_core)

定位: 与 GP 主线、LLM 增强 GP 互不并列的独立引擎, 独立子 Tab (miningSubTab==='rl')。
复刻原则: 深度复刻 AlphaMaster 的核心算法与工程机制
  (REINFORCE 策略梯度 + Looped Transformer 自回归生成 + 约束采样 + StackVM 执行
   + 多目标奖励 + Elite Replay + 熵坍塌重启 + checkpoint 断点续训)。
本地设施仅在语义等价时复用 (数据加载 / 截面 RankIC 评价 / 三段分段 / 去冗余 / 入库),
不等价则按 AlphaMaster 原样实现。

数据/评价适配 (本系统为股票池 + 截面 RankIC):
  - 数据维度: 本系统 [T 日期, N 股票, F 特征] 面板 -> 构建 [N, F, T] 张量
  - 目标收益: 截面未来 rebal_period 日收益 (复用本系统 future_returns 口径)
  - 奖励: 截面 RankIC 系 (mean_rank_ic + rank_ic_ir + 分层单调性)
  - 特征: 从本系统字段/因子派生特征集
  - 算子: 从本系统算子表派生词表
"""
