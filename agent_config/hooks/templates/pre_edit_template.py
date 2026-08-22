# -*- coding: utf-8 -*-
"""pre-edit hook 模板 — Stage 12.4 (P14) 新增

文件编辑前 hook 模板，对标 Cline pre-edit hook template。

触发时机:
    在 editor / apply_patch 工具执行前触发（PreToolUse）。
    可用于检查代码风格、文件权限、防止修改关键文件等。

使用方法:
    1. 复制本文件到 agent_config/hooks/PreToolUse/ 目录
    2. 重命名为有意义的名字（如 check_code_style.py）
    3. 取消注释需要的逻辑
    4. 在 frontmatter 中配置 applyTo（如 [editor, apply_patch]）

脚本退出码协议:
    - 0 + 无 stdout JSON: 通过，继续执行
    - 0 + stdout JSON {"cancel": true, "reason": "..."}: 阻止执行
    - 1: 兼容协议，无 stdout JSON 时视为 block（建议用 JSON cancel）
    - 其他: 执行错误（默认不阻止，blocking=true 时阻止）

stdin 输入（JSON 格式）:
    {
        "hook_type": "PreToolUse",
        "session_id": "会话ID",
        "tool_name": "editor",
        "tool_call_id": "调用ID",
        "input": {"file_path": "...", "old_string": "...", "new_string": "..."}
    }

stdout 输出（JSON 格式，可选）:
    {"cancel": true, "reason": "阻止原因"}
    {"contextModification": "要注入到模型上下文的文本"}
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    """hook 主入口

    读取 stdin JSON，根据 input 内容决定是否阻止编辑。
    """
    try:
        context = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # stdin 不是有效 JSON，直接通过
        sys.exit(0)

    tool_name = context.get("tool_name", "")
    tool_input = context.get("input", {}) or {}

    # 示例逻辑 1: 防止修改关键配置文件
    # 取消注释以下代码启用
    # file_path = tool_input.get("file_path", "")
    # protected_files = [".env", "credentials.json", "agent_config/mcp_servers.yaml"]
    # for protected in protected_files:
    #     if protected in file_path:
    #         print(json.dumps({
    #             "cancel": True,
    #             "reason": f"禁止修改关键文件: {protected}",
    #         }))
    #         sys.exit(0)

    # 示例逻辑 2: 检查代码风格（如禁止 tab 缩进）
    # 取消注释以下代码启用
    # if tool_name in ("editor", "apply_patch"):
    #     new_string = tool_input.get("new_string", "")
    #     if "\t" in new_string:
    #         print(json.dumps({
    #             "cancel": True,
    #             "reason": "禁止使用 tab 缩进，请用 4 个空格",
    #         }))
    #         sys.exit(0)

    # 默认通过
    sys.exit(0)


if __name__ == "__main__":
    main()
