# -*- coding: utf-8 -*-
"""公共输出截断工具 — P2-8 新增，对标 Cline head+tail 截断策略

提供统一的 head+tail 截断函数，供 read_files / search_codebase /
run_commands / web_tool 等工具引用，避免各工具重复实现截断逻辑。

设计说明:
    - Cline 源码位置: sdk/packages/core/src/extensions/tools/executors/output-limits.ts
    - 超过上限时保留首尾各一半（max_chars/2），中间用省略标记连接
    - 相比仅保留头部，首尾各一半能让 LLM 看到输出的开头和结尾（含错误信息）
"""


def truncate_output(text: str, max_chars: int = 48000) -> str:
    """head+tail 截断策略 — 对标 Cline

    超过 max_chars 时保留首尾各一半（max_chars/2），中间用省略标记连接。
    未超过则原样返回。

    Args:
        text: 原始输出文本
        max_chars: 字符上限，默认 48000

    Returns:
        截断后的文本（可能含中间省略标记）
    """
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n\n[...输出已截断，原始长度 {len(text)} 字符...]\n\n" + text[-half:]
