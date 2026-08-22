# -*- coding: utf-8 -*-
"""重复工具调用循环检测 — 对标 Cline loop-detection.ts

检测 LLM 是否连续调用同一工具、同一参数，避免死循环。
通过 before_tool hook 接入 AgentRuntime。

核心概念:
    - softThreshold: 软警告阈值（默认 3），达到时提示 LLM 换思路
    - hardThreshold: 硬停止阈值（默认 5），达到时主动中止运行
    - toolCallSignature: 对工具输入排序键后序列化，用于比较是否相同
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.types import LoopDetectionConfig


@dataclass
class LoopDetectionState:
    """循环检测状态"""
    last_tool_name: str = ""
    last_tool_signature: str = ""
    consecutive_identical_count: int = 0


@dataclass
class LoopDetectionVerdict:
    """循环检测结果"""
    kind: str  # "ok" | "soft" | "hard"
    message: str | None = None


def _sort_keys(value: Any) -> Any:
    """递归对 dict 的 key 排序，便于稳定比较"""
    if value is None or not isinstance(value, object):
        return value
    if isinstance(value, list):
        return [_sort_keys(item) for item in value]
    if isinstance(value, dict):
        sorted_dict: dict[str, Any] = {}
        for key in sorted(value.keys()):
            sorted_dict[key] = _sort_keys(value[key])
        return sorted_dict
    return value


def tool_call_signature(input_value: Any) -> str:
    """生成工具调用签名"""
    if input_value is None:
        return "null"
    if isinstance(input_value, str):
        return input_value
    if not isinstance(input_value, (dict, list)):
        return str(input_value)
    try:
        return json.dumps(_sort_keys(input_value), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(input_value)


def check_repeated_tool_call(
    state: LoopDetectionState,
    tool_name: str,
    signature: str,
    config: LoopDetectionConfig,
) -> LoopDetectionVerdict:
    """检查是否重复调用同一工具"""
    if tool_name == state.last_tool_name and signature == state.last_tool_signature:
        state.consecutive_identical_count += 1
    else:
        state.consecutive_identical_count = 1

    state.last_tool_name = tool_name
    state.last_tool_signature = signature

    if state.consecutive_identical_count >= config.hard_threshold:
        return LoopDetectionVerdict(
            kind="hard",
            message=(
                f"Detected {state.consecutive_identical_count} consecutive identical "
                f"calls to `{tool_name}`; stopping to avoid a loop."
            ),
        )
    if state.consecutive_identical_count == config.soft_threshold:
        return LoopDetectionVerdict(
            kind="soft",
            message=(
                f"Detected {state.consecutive_identical_count} consecutive identical "
                f"calls to `{tool_name}`; consider trying a different approach."
            ),
        )
    return LoopDetectionVerdict(kind="ok")


class LoopDetectionTracker:
    """循环检测器 — 对标 Cline LoopDetectionTracker

    用法:
        tracker = LoopDetectionTracker()
        verdict = tracker.inspect({"name": "list_files", "input": {"path": "data"}})
        if verdict.kind == "hard":
            # 停止运行
        elif verdict.kind == "soft":
            # 记录警告，但不阻止
    """

    def __init__(self, config: LoopDetectionConfig | None = None) -> None:
        self.config = config or LoopDetectionConfig()
        self._state = LoopDetectionState()

    def inspect(self, tool_name: str, input_value: Any) -> LoopDetectionVerdict:
        """检查一次工具调用是否构成循环"""
        signature = tool_call_signature(input_value)
        return check_repeated_tool_call(
            self._state, tool_name, signature, self.config
        )

    def reset(self) -> None:
        """重置检测状态"""
        self._state = LoopDetectionState()
