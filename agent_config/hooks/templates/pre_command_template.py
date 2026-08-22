# -*- coding: utf-8 -*-
"""pre-command hook 模板 — Stage 12.4 (P14) 新增

命令执行前 hook 模板，对标 Cline pre-command hook template。

触发时机:
    在 run_commands / exec_tool 工具执行前触发（PreToolUse）。
    可用于拦截危险命令、记录命令日志、限制命令范围等。

使用方法:
    1. 复制本文件到 agent_config/hooks/PreToolUse/ 目录
    2. 重命名为有意义的名字（如 block_dangerous.py）
    3. 取消注释需要的逻辑
    4. 在 frontmatter 中配置 applyTo（如 [run_commands, exec_tool]）

脚本退出码协议:
    - 0 + 无 stdout JSON: 通过，继续执行命令
    - 0 + stdout JSON {"cancel": true, "reason": "..."}: 阻止命令执行
    - 1: 兼容协议，无 stdout JSON 时视为 block
    - 其他: 执行错误（默认不阻止，blocking=true 时阻止）

stdin 输入（JSON 格式）:
    {
        "hook_type": "PreToolUse",
        "session_id": "会话ID",
        "tool_name": "run_commands",
        "tool_call_id": "调用ID",
        "input": {"commands": ["ls -la", "git status"]}
    }
"""
from __future__ import annotations

import json
import re
import sys


# 危险命令模式（正则）
_DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"rm\s+-rf\s+\*",
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/",
    r">\s*/dev/sd",
    r"shutdown",
    r"reboot",
    r"format\s+[a-z]:",
    r"drop\s+database",
    r"drop\s+table",
    r"truncate\s+table",
]


def main() -> None:
    """hook 主入口

    读取 stdin JSON，检查命令是否危险。
    """
    try:
        context = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = context.get("tool_name", "")
    tool_input = context.get("input", {}) or {}

    # 提取命令列表
    commands: list[str] = []
    if tool_name == "run_commands":
        commands = tool_input.get("commands", []) or []
    elif tool_name == "exec_tool":
        command = tool_input.get("command", "")
        if command:
            commands = [command]

    # 示例逻辑: 检查危险命令
    # 取消注释以下代码启用
    # for cmd in commands:
    #     cmd_lower = cmd.strip().lower()
    #     for pattern in _DANGEROUS_PATTERNS:
    #         if re.search(pattern, cmd_lower):
    #             print(json.dumps({
    #                 "cancel": True,
    #                 "reason": f"检测到危险命令: {cmd}（匹配模式: {pattern}）",
    #             }))
    #             sys.exit(0)

    # 示例逻辑 2: 限制命令执行目录
    # 取消注释以下代码启用
    # for cmd in commands:
    #     if "cd /" in cmd or "cd .." in cmd:
    #         print(json.dumps({
    #             "cancel": True,
    #             "reason": f"禁止切换到根目录或上级目录: {cmd}",
    #         }))
    #         sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
