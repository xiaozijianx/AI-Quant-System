# -*- coding: utf-8 -*-
"""
routes/factor/mining/common.py -- 因子挖掘公共路由

目前包含各挖掘引擎共用的任务状态查询。
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/mining/status")
def factor_mining_status(kind: str = ""):
    """查询后台挖掘任务状态 (GP/RL/LLM增强GP 实时续接)

    页面切换/关闭后，后台线程继续跑；重开页面轮询此接口即可拿到：
      - status: running / done / error
      - progress / result / error / history(最近事件流)
    """
    from lib.factor_mining_jobs import get_status
    if not kind:
        return {"found": False, "error": "缺少 kind (gp/rl/llm_gp)"}
    st = get_status(kind)
    if st is None:
        return {"found": False}
    return {"found": True, "job": st}
