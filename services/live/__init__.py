# -*- coding: utf-8 -*-
"""services/live/ -- 实盘监控业务层

由 routes/live.py 路由瘦身迁移而来 (Stage 2)。所有业务实现
(状态读写 / 执行方式 / 绑定来源 / 通用 impl / 实盘账户 / AI 授权)
统一收编到此包, 路由层只做参数解析与调用。对外 API 契约不变。
"""