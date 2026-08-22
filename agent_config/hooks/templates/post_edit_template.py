# -*- coding: utf-8 -*-
"""post-edit hook 模板 — Stage 12.4 (P14) 新增

文件编辑后 hook 模板，对标 Cline post-edit hook template。

触发时机:
    在 editor / apply_patch 工具执行后触发（PostToolUse）。
    可用于自动格式化、运行 lint、更新文档等。

使用方法:
    1. 复制本文件到 agent_config/hooks/PostToolUse/ 目录
    2. 重命名为有意义的名字（如 auto_format.py）
    3. 取消注释需要的逻辑
    4. 在 frontmatter 中配置 applyTo（如 [editor, apply_patch]）

脚本退出码协议:
    - 0 + 无 stdout JSON: 通过
    - 0 + stdout JSON {"cancel": true, "reason": "..."}: 阻止后续工具调用
    - 1: 兼容协议，无 stdout JSON 时视为 block
    - 其他: 执行错误（默认不阻止，blocking=true 时阻止）

stdin 输入（JSON 格式）:
    {
        "hook_type": "PostToolUse",
        "session_id": "会话ID",
        "tool_name": "editor",
        "tool_call_id": "调用ID",
        "input": {"file_path": "..."},
        "result": {"output": {...}, "is_error": false},
        "is_error": false,
        "duration_ms": 120
    }
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    """hook 主入口

    读取 stdin JSON，根据编辑结果执行后处理。
    """
    try:
        context = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = context.get("tool_name", "")
    tool_input = context.get("input", {}) or {}
    is_error = context.get("is_error", False)

    # 工具执行失败时不做后处理
    if is_error:
        sys.exit(0)

    # 示例逻辑 1: 编辑后自动运行 black 格式化 Python 文件
    # 取消注释以下代码启用
    # if tool_name in ("editor", "apply_patch"):
    #     file_path = tool_input.get("file_path", "")
    #     if file_path.endswith(".py"):
    #         try:
    #             subprocess.run(
    #                 ["black", "--quiet", file_path],
    #                 check=False,
    #                 timeout=10,
    #             )
    #         except (FileNotFoundError, subprocess.TimeoutExpired):
    #             # black 不存在或超时，忽略
    #             pass

    # 示例逻辑 2: 编辑后运行 lint 检查
    # 取消注释以下代码启用
    # if tool_name in ("editor", "apply_patch"):
    #     file_path = tool_input.get("file_path", "")
    #     if file_path.endswith(".py"):
    #         try:
    #             result = subprocess.run(
    #                 ["flake8", file_path],
    #                 capture_output=True,
    #                 text=True,
    #                 timeout=10,
    #             )
    #             if result.returncode != 0 and result.stdout:
    #                 # 注入 lint 结果到上下文，让 LLM 知道有 lint 警告
    #                 print(json.dumps({
    #                     "contextModification": f"[lint 警告]\n{result.stdout}",
    #                 }))
    #         except (FileNotFoundError, subprocess.TimeoutExpired):
    #             pass

    sys.exit(0)


if __name__ == "__main__":
    main()
