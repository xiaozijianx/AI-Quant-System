# -*- coding: utf-8 -*-
"""自动审批策略 — 对标 Cline autoApprove / tool approval policy

通过 before_approval 钩子实现:
    1. 只读工具自动批准（如 file_read / list_files / search_codebase / web_search 等）
    2. run_commands 中只读命令自动批准，写/危险命令需用户审批或被自动拒绝
    3. 写入类工具（file_write / editor / apply_patch）必须用户审批，不自动批准

规则可通过环境变量 AGENT_AUTO_APPROVAL 开启/关闭:
    - off / 0 / false: 关闭自动审批，所有工具走用户审批流程
    - readonly（默认）: 只读命令自动批准，写操作需审批
    - all: 自动批准所有工具（等价于 auto_approve=True，不推荐用于生产）
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from agent.hooks import BeforeApprovalContext, BeforeApprovalResult

logger = logging.getLogger(__name__)

# 默认策略模式
_DEFAULT_POLICY = "readonly"

# ============================================================================
# 工具级别策略
# ============================================================================

#  inherently 只读的工具：自动批准
READ_ONLY_TOOLS = {
    "file_read",
    "read_files",
    "list_files",
    "search_codebase",
    "use_mcp_tool",
    "fetch_web_content",
    "ask_question",
    "switch_to_plan_mode",
    "switch_to_act_mode",
    "submit_and_exit",
}

# 写入类工具：不自动批准，必须用户审批
WRITE_TOOLS = {
    "file_write",
    "editor",
    "apply_patch",
}

# ============================================================================
# run_commands 命令级别策略
# ============================================================================

# 只读命令模式（支持开头匹配）
_READ_ONLY_COMMAND_PATTERNS = [
    # 文件查看
    r"^(cat|type|head|tail|less|more|wc|stat|file|ls|dir|find|grep|rg|ag|where|which)\b",
    # 路径/环境
    r"^(cd|pwd|echo|printenv|set|env|whoami|date|time)\b",
    # git 只读操作
    r"^git\s+(status|log|diff|show|branch|remote|config\s+--get|rev-parse|ls-files|blame)\b",
    # python 版本/帮助
    r"^python\s+(--version|-V|--help|-h)\b",
    r"^python\s+-m\s+(pip\s+list|pip\s+show|site)\b",
    # pip 只读
    r"^pip\s+(list|show|freeze|search|index)\b",
]

# 危险/写命令模式：自动拒绝
_DENY_COMMAND_PATTERNS = [
    # 删除/格式化
    r"\brm\s+-rf\b",
    r"\bmkfs\.",
    r"\bdd\s+if=.*of=/dev/",
    r"\bformat\s+[a-zA-Z]:",
    r"\bdel\s+/[fq]",
    r"\brmdir\s+/s",
    # 系统控制
    r"\b(shutdown|reboot|halt|poweroff)\b",
    # 重定向/覆盖（> file 或 >> file，但不包括 echo > /dev/null 这类无害操作）
    r"[<>]\s*[a-zA-Z]:\\",
    r"[<>]\s*~",
    r"[<>]\s*\.\\",
    r"[<>]\s*\.\.\\",
]

# 写/修改命令模式：不自动批准，需用户审批（但不自动拒绝）
_WRITE_COMMAND_PATTERNS = [
    r"\b(mv|move|ren|rename|cp|copy|xcopy|robocopy)\b",
    r"\b(rm|del|rmdir|rd)\b",
    r"\b(git\s+(push|pull|fetch|merge|rebase|checkout|reset|revert|clean|commit|tag|clone|init))\b",
    r"\b(pip\s+(install|uninstall|download))\b",
    r"\bpython\s+.*\.py\b",  # 执行任意 python 脚本，可能包含写操作
    r"\bpython\s+-m\s+(?!pip\s+(list|show|freeze|search|index))",  # python -m 非只读 pip
]

_READ_ONLY_REGEX = [re.compile(p, re.IGNORECASE) for p in _READ_ONLY_COMMAND_PATTERNS]
_DENY_REGEX = [re.compile(p, re.IGNORECASE) for p in _DENY_COMMAND_PATTERNS]
_WRITE_REGEX = [re.compile(p, re.IGNORECASE) for p in _WRITE_COMMAND_PATTERNS]


def _classify_command(command: str) -> str:
    """对单条命令进行分类

    Returns:
        "readonly": 只读命令，可自动批准
        "deny": 危险命令，自动拒绝
        "write": 写/修改命令，需用户审批
    """
    stripped = command.strip()
    if not stripped:
        return "readonly"

    # 先检查危险模式
    for pattern in _DENY_REGEX:
        if pattern.search(stripped):
            return "deny"

    # 再检查写模式
    for pattern in _WRITE_REGEX:
        if pattern.search(stripped):
            return "write"

    # 最后检查是否匹配只读模式
    for pattern in _READ_ONLY_REGEX:
        if pattern.match(stripped):
            return "readonly"

    # 无法识别：保守处理为需审批
    return "write"


class AutoApprovalPolicy:
    """自动审批策略 — 作为 before_approval 钩子使用

    用法:
        policy = AutoApprovalPolicy()
        runtime.register_hooks(AgentHooks(before_approval=policy.before_approval))
    """

    def __init__(self, mode: str | None = None) -> None:
        """初始化自动审批策略

        Args:
            mode: 策略模式，None 时从 AGENT_AUTO_APPROVAL 环境变量读取
                  - off: 关闭自动审批
                  - readonly: 只读自动批准（默认）
                  - all: 自动批准所有工具
        """
        self.mode = (mode or os.environ.get("AGENT_AUTO_APPROVAL", _DEFAULT_POLICY)).lower().strip()

    async def before_approval(self, ctx: BeforeApprovalContext) -> BeforeApprovalResult | None:
        """before_approval 钩子入口

        根据工具名和输入参数自动决策，返回:
            - decision="approved": 自动通过
            - decision="denied": 自动拒绝
            - decision=None: 不决策，继续走用户审批流程
        """
        if self.mode == "off" or self.mode in ("0", "false", "no"):
            return None

        if self.mode == "all":
            return BeforeApprovalResult(
                decision="approved",
                reason="自动审批策略：all 模式自动通过所有工具",
            )

        # 工具级别策略
        if ctx.tool_name in READ_ONLY_TOOLS:
            return BeforeApprovalResult(
                decision="approved",
                reason=f"{ctx.tool_name} 为只读工具，自动批准",
            )

        if ctx.tool_name in WRITE_TOOLS:
            # 写入工具不自动批准，走用户审批
            return None

        # run_commands 需要按命令分类判断
        if ctx.tool_name == "run_commands":
            return self._handle_run_commands(ctx.input)

        # 未知工具：保守处理，不自动决策
        return None

    def _handle_run_commands(self, input_data: dict[str, Any]) -> BeforeApprovalResult | None:
        """处理 run_commands 的自动审批

        规则:
            - 所有命令均为只读：自动批准
            - 任一命令为危险命令：自动拒绝
            - 任一命令为写/修改命令：不自动批准，需用户审批
            - 空命令：自动批准
        """
        commands = input_data.get("commands", [])
        if not isinstance(commands, list):
            return None

        for cmd in commands:
            if not isinstance(cmd, str):
                continue
            classification = _classify_command(cmd)
            if classification == "deny":
                return BeforeApprovalResult(
                    decision="denied",
                    reason=f"检测到危险命令，自动拒绝: {cmd}",
                )
            if classification == "write":
                # 写命令不自动批准，但记录日志
                logger.info("run_commands 包含写/未识别命令，需用户审批: %s", cmd)
                return None

        # 全部只读或空
        return BeforeApprovalResult(
            decision="approved",
            reason="所有命令均为只读操作，自动批准",
        )
