#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""示例 PostToolUse 文件 hook — 记录工具调用日志

Phase 28.3 验证用：演示 PostToolUse 类型的文件 hook。
工具执行完成后，将 tool_name / duration_ms / is_error 写入日志文件。

日志路径: agent_config/hooks/.tool_audit.log
启用方式: enable_file_hooks=True（与 PreToolUse 共用 file_hooks_dir）
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    try:
        raw = sys.stdin.read()
        ctx = json.loads(raw) if raw else {}
    except Exception:
        return 0

    tool_name = ctx.get("tool_name", "<unknown>")
    duration_ms = ctx.get("duration_ms", 0)
    is_error = ctx.get("is_error", False)
    run_id = ctx.get("run_id", "")
    iteration = ctx.get("iteration", 0)

    # 日志文件存放在 hooks 目录下
    log_path = Path(__file__).resolve().parent.parent / ".tool_audit.log"

    line = (
        f"[{datetime.now().isoformat(timespec='seconds')}] "
        f"run={run_id} iter={iteration} tool={tool_name} "
        f"duration={duration_ms}ms error={is_error}\n"
    )

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        # 日志写入失败不影响主流程
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
