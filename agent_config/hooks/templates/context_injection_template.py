# -*- coding: utf-8 -*-
"""context-injection hook 模板 — Stage 12.4 (P14) 新增

上下文注入 hook 模板，对标 Cline context-injection hook template。

触发时机:
    在 PreToolUse（工具调用前）触发，通过 contextModification 字段
    注入额外上下文到模型对话中。

    典型用途:
        - 注入当前 git 分支/提交信息
        - 注入当前工作目录的文件列表
        - 注入数据库连接状态
        - 注入市场交易时间/状态

使用方法:
    1. 复制本文件到 agent_config/hooks/PreToolUse/ 目录
    2. 重命名为有意义的名字（如 inject_git_status.py）
    3. 取消注释需要的逻辑
    4. 在 frontmatter 中配置 applyTo（如 [read_files, search_codebase]）

脚本退出码协议:
    - 0 + stdout JSON {"contextModification": "..."}: 注入上下文，继续执行
    - 0 + 无 stdout JSON: 不注入，继续执行
    - 1: 兼容协议，无 stdout JSON 时视为 block
    - 其他: 执行错误（默认不阻止，blocking=true 时阻止）

stdin 输入（JSON 格式）:
    {
        "hook_type": "PreToolUse",
        "session_id": "会话ID",
        "tool_name": "read_files",
        "tool_call_id": "调用ID",
        "input": {"path": "..."}
    }
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def main() -> None:
    """hook 主入口

    读取 stdin JSON，注入额外上下文。
    """
    try:
        context = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # 示例逻辑 1: 注入当前 git 分支信息
    # 取消注释以下代码启用
    # try:
    #     branch = subprocess.check_output(
    #         ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    #         stderr=subprocess.DEVNULL,
    #         timeout=2,
    #     ).decode().strip()
    #     commit = subprocess.check_output(
    #         ["git", "rev-parse", "--short", "HEAD"],
    #         stderr=subprocess.DEVNULL,
    #         timeout=2,
    #     ).decode().strip()
    #     additional_context = f"[Hook Context] 当前 git 分支: {branch}, 提交: {commit}"
    #     print(json.dumps({"contextModification": additional_context}))
    # except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
    #     # git 不可用或非 git 仓库，不注入
    #     pass

    # 示例逻辑 2: 注入当前工作目录的文件列表
    # 取消注释以下代码启用
    # try:
    #     cwd = os.getcwd()
    #     entries = os.listdir(cwd)
    #     file_list = [e for e in entries if not e.startswith(".")]
    #     additional_context = (
    #         f"[Hook Context] 当前目录 {cwd} 包含文件: "
    #         + ", ".join(file_list[:10])
    #     )
    #     print(json.dumps({"contextModification": additional_context}))
    # except OSError:
    #     pass

    # 示例逻辑 3: 注入市场交易时间（量化场景）
    # 取消注释以下代码启用
    # from datetime import datetime
    # now = datetime.now()
    # weekday = now.weekday()  # 0=Monday, 6=Sunday
    # hour = now.hour
    # is_trading_day = weekday < 5  # 周一到周五
    # is_trading_time = is_trading_day and 9 <= hour < 15
    # additional_context = (
    #     f"[Hook Context] 当前时间: {now.strftime('%Y-%m-%d %H:%M')}, "
    #     f"交易日: {'是' if is_trading_day else '否'}, "
    #     f"交易时段: {'是' if is_trading_time else '否'}"
    # )
    # print(json.dumps({"contextModification": additional_context}))

    sys.exit(0)


if __name__ == "__main__":
    main()
