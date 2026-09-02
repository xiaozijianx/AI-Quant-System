# -*- coding: utf-8 -*-
"""
routes/factor/mining/rl.py -- RL 因子挖掘路由

三层结构：因子库 -> 因子挖掘 -> RL。
"""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Dict

from fastapi import APIRouter, Body
from sse_starlette.sse import EventSourceResponse

# JSON 安全清洗等公共工具统一放在 routes/common.py (Stage 5: 由 factor_common 迁移)
from routes.common import _json_safe
from lib.factor_db import save_eval_result

router = APIRouter()


@router.post("/mine_rl/stream")
def mine_rl_factors_stream(body: Dict[str, Any] = Body(...)):
    """RL 强化学习因子挖掘 (SSE 流式版, 深度复刻 AlphaMaster)"""
    q: "queue.Queue" = queue.Queue()

    def _progress_cb(step: int, stats: Dict[str, Any]) -> None:
        try:
            q.put(("progress", stats))
            from lib.factor_mining_jobs import publish
            publish("rl", "progress", stats)
        except Exception:
            pass

    def _restart_cb(step: int, info: Dict[str, Any]) -> None:
        try:
            q.put(("restart", {"step": step, **info}))
            from lib.factor_mining_jobs import publish
            publish("rl", "restart", {"step": step, **info})
        except Exception:
            pass

    def _elite_cb(step: int, info: Dict[str, Any]) -> None:
        try:
            q.put(("elite", {"step": step, **info}))
            from lib.factor_mining_jobs import publish
            publish("rl", "elite", {"step": step, **info})
        except Exception:
            pass

    def _run() -> None:
        try:
            from lib.factor_mining_jobs import start_job, finish_job
            start_job("rl")
            from lib.factor_rl.pipeline import run_rl_pipeline
            result = run_rl_pipeline(dict(body), progress_cb=_progress_cb,
                                     restart_cb=_restart_cb, elite_cb=_elite_cb)
            try:
                save_eval_result("mining", "rl", result, {
                    "pool_type": body.get("pool_type", ""),
                    "pool_ref": body.get("pool_ref", ""),
                    "method": "rl",
                    "start_date": body.get("start_date", ""),
                    "end_date": body.get("end_date", ""),
                    "rebal_period": body.get("rebal_period", 5),
                })
            except Exception:
                pass
            finish_job("rl", result)
            q.put(("done", result))
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            from lib.factor_mining_jobs import finish_job as _f
            _f("rl", None, detail)
            q.put(("error", {"error": detail}))

    threading.Thread(target=_run, daemon=True).start()

    def _event_gen():
        while True:
            try:
                kind, payload = q.get(timeout=1.0)
            except queue.Empty:
                yield {"event": "heartbeat", "data": json.dumps({"ts": time.time()})}
                continue
            if kind == "progress":
                yield {"event": "progress", "data": json.dumps(payload)}
            elif kind == "restart":
                yield {"event": "restart", "data": json.dumps(payload)}
            elif kind == "elite":
                yield {"event": "elite", "data": json.dumps(payload)}
            elif kind == "done":
                yield {"event": "done", "data": json.dumps(_json_safe(payload))}
                break
            elif kind == "error":
                yield {"event": "error", "data": json.dumps(payload)}
                break

    return EventSourceResponse(_event_gen())
