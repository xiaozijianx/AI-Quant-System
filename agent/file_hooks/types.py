# -*- coding: utf-8 -*-
"""文件 hook 类型定义 — Phase 28.3 新增，对标 Cline HookProcess

定义文件 hook 系统的核心数据结构：
    - FileHookType: hook 类型枚举（PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete）
    - FileHookConfig: 单个 hook 脚本的配置（从 frontmatter 解析）
    - FileHookContext: 执行 hook 时传给脚本的上下文（JSON 序列化后通过 stdin 传递）
    - FileHookResult: hook 执行结果（block/continue/context_injection）

文件 hook 与 Python 内建 hook 的区别：
    - Python hook: 在 agent 进程内执行，可访问内存状态，性能高
    - 文件 hook: 在独立子进程中执行，隔离性好，用户无需改源码即可扩展

hook 类型与 Python hook 点的映射：
    - PreToolUse      → before_tool
    - PostToolUse     → after_tool
    - UserPromptSubmit → prepare_turn_input
    - TaskStart       → before_run
    - TaskComplete    → after_run

脚本 frontmatter 格式（YAML）：
    ---
    description: 拦截危险命令
    applyTo: [run_commands, exec]   # 仅对指定工具生效（PreToolUse/PostToolUse 专用）
    blocking: false                 # 是否阻塞主流程（默认 False 与 Cline fail-open 对齐；
                                    # true 时脚本错误也会中止工具执行）
    timeout: 30                     # 执行超时秒数（默认 30）
    ---

脚本退出码协议（Stage 5.3+5.4 对齐 Cline hook-factory.ts）：
    - 0:  执行成功；block 由 stdout JSON 的 cancel:true 字段决定
    - 1:  兼容协议（本系统额外增强）：无 stdout JSON 时视为 block，stderr 作为 reason
    - 其他: 执行错误，记录日志但不影响主流程（除非 blocking=true）

Stage 5.3 (P4/P18): blocking 默认值改为 False（fail-open，与 Cline 对齐），
    脚本错误不阻止主流程，仅 stdout JSON 的 cancel:true 或显式 blocking=true 才阻止。

Stage 5.4 (P8): block 仅由 stdout JSON 的 cancel:true 字段决定，退出码仅表示
    执行成功/失败。stdout JSON 支持 Cline 字段名 contextModification 与本系统
    字段名 context_injection，取值优先级 contextModification > context_injection。

stdout JSON 格式（可选，任意 exit code 都会解析）：
    {"cancel": true, "reason": "阻止原因"}
    {"contextModification": "要注入到模型上下文的文本"}
    {"context_injection": "本系统兼容字段，同 contextModification"}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FileHookType(str, Enum):
    """文件 hook 类型 — 对标 Cline HookType

    映射到 Python 内建 hook 点：
        PreToolUse       → before_tool
        PostToolUse      → after_tool
        UserPromptSubmit → prepare_turn_input
        TaskStart        → before_run
        TaskComplete     → after_run
        TaskResume       → before_run（恢复会话时，对标 Cline agent_resume）
        TaskCancel       → after_run（被 abort 时，对标 Cline agent_abort）
        Notification     → 通知类 hook（对标 Cline Notification，无对应 Python hook 点，
                          由 integration 按需触发，不强制映射）
        PreCompact       → 压缩前 hook（对标 Cline PreCompact，对应 compaction 前
                          的上下文准备阶段，由 ContextCompactor 在压缩前触发）
    """
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    TASK_START = "TaskStart"
    TASK_COMPLETE = "TaskComplete"
    # Phase 31.6: 新增 TaskResume / TaskCancel — 对标 Cline hooks/README.md L26-37
    TASK_RESUME = "TaskResume"
    TASK_CANCEL = "TaskCancel"
    # P2-21: 新增 Notification / PreCompact — 对标 Cline HookType 同名类型
    NOTIFICATION = "Notification"
    PRE_COMPACT = "PreCompact"


# hook 类型到 Python hook 点的映射
HOOK_TYPE_MAPPING = {
    FileHookType.PRE_TOOL_USE: "before_tool",
    FileHookType.POST_TOOL_USE: "after_tool",
    FileHookType.USER_PROMPT_SUBMIT: "prepare_turn_input",
    FileHookType.TASK_START: "before_run",
    FileHookType.TASK_COMPLETE: "after_run",
    # Phase 31.6: TaskResume/TaskCancel 复用 before_run/after_run Python hook 点
    # 在 integration.py 中根据 context.is_resume / context.is_cancel 区分触发
    FileHookType.TASK_RESUME: "before_run",
    FileHookType.TASK_CANCEL: "after_run",
    # P2-21: Notification / PreCompact 暂不映射到固定 Python hook 点，
    # 由调用方按需触发（Notification 由通知系统触发，PreCompact 由压缩器触发）；
    # 不写入映射避免被 integration.py 误绑定到错误 hook 点。
}


@dataclass
class FileHookConfig:
    """文件 hook 配置 — 从脚本 frontmatter 解析

    Attributes:
        script_path: 脚本文件绝对路径
        hook_type: hook 类型
        description: 人类可读的描述（frontmatter）
        apply_to: 适用工具名列表（PreToolUse/PostToolUse 专用），
                  空列表表示对所有工具生效
        blocking: 是否阻塞主流程（默认 False 与 Cline fail-open 对齐；
                  true 时脚本错误也会中止工具执行）
        timeout: 执行超时秒数（默认 30）
    """
    script_path: Path
    hook_type: FileHookType
    description: str = ""
    apply_to: list[str] = field(default_factory=list)
    # Stage 5.3 (P4/P18): 默认 False — 对标 Cline fail-open 语义
    blocking: bool = False
    timeout: int = 30

    def applies_to_tool(self, tool_name: str) -> bool:
        """检查此 hook 是否对指定工具生效

        Args:
            tool_name: 工具名

        Returns:
            True 表示对此工具生效（apply_to 为空时对所有工具生效）
        """
        if not self.apply_to:
            return True
        return tool_name in self.apply_to


@dataclass
class FileHookContext:
    """文件 hook 执行上下文 — 序列化为 JSON 通过 stdin 传给脚本

    不同 hook 类型使用不同字段：
        - PreToolUse/PostToolUse: tool_name, tool_call_id, input, result
        - UserPromptSubmit: user_input
        - TaskStart/TaskComplete: 无额外字段
        - TaskResume: previous_state（对标 Cline taskResume.previousState）
        - TaskCancel: completion_status（对标 Cline taskCancel.completionStatus）

    所有类型都包含通用字段：session_id, run_id, iteration, hook_type
    """
    hook_type: str
    session_id: str = ""
    run_id: str = ""
    iteration: int = 0
    # PreToolUse / PostToolUse
    tool_name: str = ""
    tool_call_id: str = ""
    input: Any = None
    # PostToolUse only
    result: Any = None
    is_error: bool = False
    duration_ms: int = 0
    # UserPromptSubmit
    user_input: str = ""
    # Phase 31.6: TaskResume — 对标 Cline taskResume.previousState
    # 包含 last_message_ts / message_count / conversation_history_deleted
    previous_state: dict[str, Any] | None = None
    # Phase 31.6: TaskCancel — 对标 Cline taskCancel.completionStatus
    # 如 "aborted" / "failed" / "completed"
    completion_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转为字典用于 JSON 序列化"""
        return {
            "hook_type": self.hook_type,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "iteration": self.iteration,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "input": self.input,
            "result": self.result,
            "is_error": self.is_error,
            "duration_ms": self.duration_ms,
            "user_input": self.user_input,
            "previous_state": self.previous_state,
            "completion_status": self.completion_status,
        }


@dataclass
class FileHookResult:
    """文件 hook 执行结果 — Phase 28.3 新增

    Attributes:
        action: 执行动作
            - "continue": 通过，继续主流程
            - "block": 阻止，中止工具执行或运行
            - "error": 脚本执行出错，不影响主流程（除非 blocking=true）
        reason: 动作原因（block 时的拒绝理由，error 时的错误信息）
        context_injection: 要注入到模型上下文的文本（continue 时可选）
        exit_code: 脚本退出码
    """
    action: str = "continue"
    reason: str = ""
    context_injection: str = ""
    exit_code: int = 0


class HookError(Exception):
    """文件 hook 执行错误 — Stage 12.4 (P11) 新增，对标 Cline HookError

    区分 hook 执行错误与其他系统异常，便于上层（integration.py）根据
    blocking 配置决定是否中止主流程。

    Attributes:
        hook_name: hook 脚本名（用于日志和调试）
        exit_code: 脚本退出码（-1 表示未执行或异常终止）
        stderr: 脚本 stderr 输出（用于错误诊断）
    """

    def __init__(
        self,
        message: str,
        *,
        hook_name: str = "",
        exit_code: int | None = None,
        stderr: str = "",
    ) -> None:
        self.hook_name = hook_name
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"[hook={hook_name}] {message}")


# 默认 hook 超时秒数
DEFAULT_HOOK_TIMEOUT = 30

# 支持的脚本扩展名（按优先级排序）
SUPPORTED_SCRIPT_EXTENSIONS = (".py", ".sh", ".js", ".bat")
