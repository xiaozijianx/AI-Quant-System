# -*- coding: utf-8 -*-
"""记忆老化层 — 对齐 Claude Code memoryAge.ts

为召回的记忆提供时效标注，让主模型识别记忆可能过时：
    1. memory_age_days: 距上次修改的天数（今天 0，昨天 1，更早 2+；未来时间钳制为 0）
    2. memory_age_str: 人类可读的年龄描述（"today"/"yesterday"/"N days ago"）
    3. memory_freshness_text: 对 >1 天的记忆生成失效提示文本
    4. memory_freshness_note: 包装为 <system-reminder> 标签的失效提示

模型不擅长日期算术，原始 ISO 时间戳不如"47 天前"能触发过时推理，
故在召回注入每条记忆后附加时效提示。

对标 Claude Code:
    - src/memdir/memoryAge.ts
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 一天毫秒数
_DAY_MS = 86_400_000


def memory_age_days(mtime_ms: float) -> int:
    """距上次修改的天数（向下取整）— 对齐 memoryAge.ts memoryAgeDays

    今天 0，昨天 1，更早 2+；未来修改时间（时钟偏差）钳制为 0。

    Args:
        mtime_ms: 修改时间（毫秒时间戳）

    Returns:
        距今天数
    """
    return max(0, int((datetime.now(timezone.utc).timestamp() * 1000 - mtime_ms) // _DAY_MS))


def memory_age_str(mtime_ms: float) -> str:
    """人类可读的年龄描述 — 对齐 memoryAge.ts memoryAge

    模型对"47 天前"比 ISO 时间戳更容易触发过时推理。

    Args:
        mtime_ms: 修改时间（毫秒时间戳）

    Returns:
        年龄描述字符串（today / yesterday / N days ago）
    """
    d = memory_age_days(mtime_ms)
    if d == 0:
        return "today"
    if d == 1:
        return "yesterday"
    return f"{d} days ago"


def memory_freshness_text(mtime_ms: float) -> str:
    """对 >1 天的记忆生成失效提示文本 — 对齐 memoryAge.ts memoryFreshnessText

    新鲜记忆（今天/昨天）返回空字符串——此时提示是噪音。
    用于已有外部包装的调用方（如召回消息注入）。

    Args:
        mtime_ms: 修改时间（毫秒时间戳）

    Returns:
        失效提示文本；记忆 ≤1 天时返回空字符串
    """
    d = memory_age_days(mtime_ms)
    if d <= 1:
        return ""
    return (
        f"This memory is {d} days old. "
        f"Memories are point-in-time observations, not live state — "
        f"claims about code behavior or file:line citations may be outdated. "
        f"Verify against current code before asserting as fact."
    )


def memory_freshness_note(mtime_ms: float) -> str:
    """包装为 <system-reminder> 标签的失效提示 — 对齐 memoryAge.ts memoryFreshnessNote

    用于调用方未提供外部包装的场景（如召回记忆注入到消息）。

    Args:
        mtime_ms: 修改时间（毫秒时间戳）

    Returns:
        <system-reminder> 包装的失效提示；记忆 ≤1 天时返回空字符串
    """
    text = memory_freshness_text(mtime_ms)
    if not text:
        return ""
    return f"<system-reminder>{text}</system-reminder>\n"