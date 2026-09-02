# -*- coding: utf-8 -*-
"""
routes/common.py -- 全站路由公共工具

由 factor_common.py 升级全站化: JSON 安全清洗等工具统一放这里,
各页面路由(含 factor 子路由)共享, 避免每处重复定义。
factor_common.py 保留为兼容 re-export 入口, 后续各路由逐步改为直接引用本文件。
"""
from __future__ import annotations

from functools import wraps
import math

import numpy as np


def _json_safe(obj):
    """递归清洗: 把 inf/-inf/NaN 浮点替换为 None, 保证 JSON 序列化合规"""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, np.floating):
        f = float(obj)
        return None if not math.isfinite(f) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _json_safe_response(f):
    """响应清洗装饰器: 函数返回前递归替换非有限浮点为 None"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return _json_safe(f(*args, **kwargs))
    return wrapper
