# -*- coding: utf-8 -*-
"""页面/前端状态持久化路由 -- 前端状态统一存后端, 前后端解耦

设计原则: 各种类型的数据都不保存在前端, 而是统一持久化到后端, 前端只做展示。
这样无论打开哪个实例(不同端口), 只要后端是同一个服务, 都能读到同一份参数配置。

提供:
- GET  /api/page-settings/{namespace}   -- 读取某命名空间的已保存状态 (无则返回 data: null)
- POST /api/page-settings/{namespace}   -- 保存某命名空间的完整状态 (JSON body)

存储位置: agent_data/ui_settings/<namespace>.json
  - 与 agent_data/sessions(对话)、agent_data/state(会话状态) 同级, 多实例共享
  - 采用临时文件 + 原子替换写入, 避免多实例并发读写损坏 JSON
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Body

from lib.paths import PROJECT_ROOT

router = APIRouter()

# 存储根目录: 项目根目录下 agent_data/ui_settings
SETTINGS_DIR = PROJECT_ROOT / "agent_data" / "ui_settings"

# 命名空间只允许字母数字、下划线、中划线、点, 防止路径穿越
_NS_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _settings_path(namespace: str) -> Path:
    """根据命名空间解析存储文件路径 (自动过滤非法字符)."""
    ns = _NS_RE.sub("", namespace)
    return SETTINGS_DIR / f"{ns}.json"


@router.get("/{namespace}")
def get_page_settings(namespace: str):
    """读取某命名空间的已保存状态, 无则返回 data: null."""
    p = _settings_path(namespace)
    if not p.exists():
        return {"namespace": namespace, "data": None}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # 文件损坏时视为无状态, 避免前端抛错
        return {"namespace": namespace, "data": None}
    return {"namespace": namespace, "data": data}


@router.post("/{namespace}")
def save_page_settings(namespace: str, payload: dict = Body(...)):
    """保存某命名空间的完整状态 (前端每次整体覆盖).

    多实例共享 + 并发安全: 每个进程用独立临时名(进程ID+随机数)写入后 os.replace
    原子替换目标文件。Windows 下目标文件被其他线程/进程占用时 replace 会抛
    WinError 5, 此处短重试; 仍失败则静默丢弃本次写入(UI 状态是"最后写入者胜",
    文件始终是某次写入的完整 JSON, 丢弃一次可接受, 下次保存会覆盖)。
    """
    p = _settings_path(namespace)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{p.stem}-", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        # 短重试: 覆盖 Windows 并发 rename 瞬时冲突
        for _attempt in range(5):
            try:
                os.replace(tmp_path, p)
                break
            except OSError:
                time.sleep(0.02)
        else:
            # 重试仍失败: 清理临时文件, 静默丢弃本次写入 (不阻断前端)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
    except BaseException:
        # 写入过程异常: 清理临时文件
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise
    return {"namespace": namespace, "ok": True}
