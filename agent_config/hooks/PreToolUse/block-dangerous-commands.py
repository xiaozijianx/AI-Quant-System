#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""示例 PreToolUse 文件 hook — 拦截危险命令

Phase 28.3 验证用：演示文件 hook 系统的 block 协议。
当 run_commands 工具的 input.commands 含 rm -rf / 时，返回 exit code 1 阻止执行。

启用方式（在 AgentRuntimeConfig 中）:
    enable_file_hooks=True
    file_hooks_dir="agent_config/hooks"

输入: 从 stdin 读取 JSON FileHookContext
输出: exit code 0（通过）或 1（阻止，stderr 作为 reason）
"""

import json
import sys


def main() -> int:
    try:
        raw = sys.stdin.read()
        ctx = json.loads(raw) if raw else {}
    except Exception:
        # 解析失败时放行，不影响主流程
        return 0

    tool_name = ctx.get("tool_name", "")
    if tool_name != "run_commands":
        return 0

    tool_input = ctx.get("input", {}) or {}
    commands = tool_input.get("commands", []) or []

    # 检测危险命令
    dangerous_patterns = ["rm -rf /", "rm -rf ~", "format c:", "del /f /s /q c:\\"]
    for cmd in commands:
        if isinstance(cmd, str):
            cmd_lower = cmd.lower()
            for pattern in dangerous_patterns:
                if pattern in cmd_lower:
                    sys.stderr.write(
                        f"危险命令被文件 hook 拦截: {cmd}（命中规则: {pattern}）"
                    )
                    return 1

    # 通过时可选输出 context_injection（JSON 格式）
    # 例: print(json.dumps({"context_injection": "已通过危险命令检查"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
