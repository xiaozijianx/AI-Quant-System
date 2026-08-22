# -*- coding: utf-8 -*-
"""连续错误追踪器 — 对标 Cline mistake-tracker.ts

检测 LLM 是否连续犯同类错误，避免在参数错误/权限拒绝/执行失败等场景下无限重试。
与 loop_detection.py 互补:
    - LoopDetectionTracker: 检测"同一工具同一参数连续调用"（防止卡循环）
    - MistakeTracker:       检测"连续同类错误"（防止犯同类错误），按 mistake_type 分类计数

核心概念:
    - mistake_type: 错误分类（param_error/tool_not_found/permission_denied/exec_error/timeout）
    - max_per_type: 单类型软阈值（默认 3），达到时向 LLM 注入结构化恢复提示
    - max_total:    总错误硬阈值（默认 5），达到时主动中止运行
    - guidance:     软阈值触发的恢复提示，注入到下一轮 LLM 上下文
"""

from __future__ import annotations

from dataclasses import dataclass, field


class MistakeType:
    """错误类型常量 — 对标 Cline MistakeReason 的细化版"""

    PARAM_ERROR = "param_error"            # 参数错误（schema 校验失败、类型错误、字段缺失）
    TOOL_NOT_FOUND = "tool_not_found"      # 工具不存在
    PERMISSION_DENIED = "permission_denied"  # 权限拒绝/审批被拒
    EXEC_ERROR = "exec_error"              # 工具执行错误（业务异常）
    TIMEOUT = "timeout"                    # 超时


@dataclass
class MistakeRecord:
    """单次错误记录"""
    iteration: int
    mistake_type: str
    tool_name: str
    details: str


@dataclass
class MistakeOutcome:
    """record() 返回值 — 对标 Cline MistakeOutcome

    action 取值:
        - "continue":                继续运行，无需特殊处理
        - "continue_with_guidance":  继续运行，但需把 guidance 注入下一轮 LLM 上下文
        - "stop":                    中止运行，message 为停止原因
    """
    action: str
    guidance: str | None = None
    message: str | None = None


@dataclass
class MistakeTrackerConfig:
    """MistakeTracker 配置"""
    max_per_type: int = 3   # 单类型软阈值
    max_total: int = 5      # 总错误硬阈值


# 错误文本关键词到 mistake_type 的映射（按优先级排序，先匹配先返回）
_ERROR_PATTERNS: list[tuple[str, str]] = [
    ("not found", MistakeType.TOOL_NOT_FOUND),
    ("no tool", MistakeType.TOOL_NOT_FOUND),
    ("unknown tool", MistakeType.TOOL_NOT_FOUND),
    ("permission", MistakeType.PERMISSION_DENIED),
    ("denied", MistakeType.PERMISSION_DENIED),
    ("approval", MistakeType.PERMISSION_DENIED),
    ("not approved", MistakeType.PERMISSION_DENIED),
    ("timeout", MistakeType.TIMEOUT),
    ("timed out", MistakeType.TIMEOUT),
    ("schema", MistakeType.PARAM_ERROR),
    ("validation", MistakeType.PARAM_ERROR),
    ("invalid param", MistakeType.PARAM_ERROR),
    ("missing field", MistakeType.PARAM_ERROR),
    ("type error", MistakeType.PARAM_ERROR),
    ("expected", MistakeType.PARAM_ERROR),
]


def classify_mistake(error_text: str) -> str:
    """从错误文本推断 mistake_type

    Args:
        error_text: 工具结果中的错误文本

    Returns:
        mistake_type 字符串（见 MistakeType 常量）
    """
    text = (error_text or "").lower()
    for pattern, mistake_type in _ERROR_PATTERNS:
        if pattern in text:
            return mistake_type
    return MistakeType.EXEC_ERROR


# 每个 mistake_type 的恢复建议
_RECOVERY_HINTS: dict[str, str] = {
    MistakeType.PARAM_ERROR: (
        "参数错误。请检查工具 schema: 确认字段名、类型、是否必填。"
        "若 LLM 不确定参数结构，应先调用 list_files/read_files 查看相关文件，"
        "或检查工具描述中的 input_schema 字段。"
    ),
    MistakeType.TOOL_NOT_FOUND: (
        "工具不存在。请检查工具名拼写，或查看 system prompt 中的可用工具列表。"
        "若工具已被禁用，请改用其他工具完成相同任务。"
    ),
    MistakeType.PERMISSION_DENIED: (
        "权限被拒。危险工具需要用户审批，请简化命令或换用更安全的替代方案。"
        "若是 run_commands，避免使用 rm/format/del 等危险命令。"
    ),
    MistakeType.EXEC_ERROR: (
        "执行错误。请检查命令是否正确、文件路径是否存在、依赖是否安装。"
        "建议先 list_files 确认路径，或 read_files 查看文件内容后再操作。"
    ),
    MistakeType.TIMEOUT: (
        "超时。请简化任务或拆分为多个小步骤。"
        "若是 run_commands，避免长时间运行的命令，或分批执行。"
    ),
}


class MistakeTracker:
    """连续错误追踪器 — 对标 Cline MistakeTracker

    用法:
        tracker = MistakeTracker()
        outcome = tracker.record(
            iteration=3,
            mistake_type=MistakeType.PARAM_ERROR,
            tool_name="list_files",
            details="field 'path' expected string, got int",
        )
        if outcome.action == "stop":
            raise RuntimeError(outcome.message)
        elif outcome.action == "continue_with_guidance":
            # 把 outcome.guidance 注入下一轮 LLM 上下文
            ...

    设计说明:
        - 按 mistake_type 分类计数，每类独立软阈值
        - 总错误数达到硬阈值时中止
        - 成功调用时调用 reset() 清空计数
        - 软阈值触发时返回 guidance（恢复提示），由调用方注入 LLM 上下文
    """

    def __init__(self, config: MistakeTrackerConfig | None = None) -> None:
        self.config = config or MistakeTrackerConfig()
        self._counts: dict[str, int] = {}  # mistake_type -> 连续计数
        self._total: int = 0
        self._history: list[MistakeRecord] = []
        # 已触发软阈值的类型集合，避免同一类型反复注入 guidance
        self._soft_triggered: set[str] = set()

    def record(
        self,
        iteration: int,
        mistake_type: str,
        tool_name: str,
        details: str,
        force_at_limit: bool = False,
    ) -> MistakeOutcome:
        """记录一次错误并返回决策

        Args:
            iteration: 当前迭代轮次
            mistake_type: 错误类型（见 MistakeType 常量）
            tool_name: 工具名
            details: 错误详情文本
            force_at_limit: 强制达到硬阈值上限（对标 Cline RecordMistakeInput.forceAtLimit），
                           用于循环检测硬阈值联动场景：直接将 _total 设为 max_total，
                           跳过递增逻辑，让 MistakeTracker 立即返回 stop 决策

        Returns:
            MistakeOutcome: 决策结果（continue/continue_with_guidance/stop）
        """
        # Stage 5.2 (M4): force_at_limit 路径 — 对标 Cline mistake-tracker.ts L90
        # `const next = input.forceAtLimit && max ? max : this.consecutiveMistakes + 1`
        # 直接将 _total 设为 max_total，跳过递增；仍记录到 _history 便于审计
        if force_at_limit:
            self._total = self.config.max_total
            # 同步将当前 mistake_type 计数也提到 max_per_type 以上，便于 _build_stop_message 汇总
            self._counts[mistake_type] = max(
                self._counts.get(mistake_type, 0) + 1,
                self.config.max_per_type,
            )
        else:
            self._counts[mistake_type] = self._counts.get(mistake_type, 0) + 1
            self._total += 1
        self._history.append(
            MistakeRecord(iteration, mistake_type, tool_name, details[:200])
        )

        # 硬阈值：总错误数达到上限，中止运行
        if self._total >= self.config.max_total:
            return MistakeOutcome(
                action="stop",
                message=self._build_stop_message(),
            )

        # 软阈值：单类型达到上限，注入恢复提示
        per_type_count = self._counts[mistake_type]
        if per_type_count >= self.config.max_per_type and mistake_type not in self._soft_triggered:
            self._soft_triggered.add(mistake_type)
            guidance = self._build_guidance(mistake_type, tool_name, per_type_count)
            return MistakeOutcome(
                action="continue_with_guidance",
                guidance=guidance,
            )

        return MistakeOutcome(action="continue")

    def reset(self) -> None:
        """重置所有计数（成功调用后或新会话开始时调用）"""
        self._counts.clear()
        self._total = 0
        self._history.clear()
        self._soft_triggered.clear()

    @property
    def value(self) -> int:
        """返回总错误计数 — 对标 Cline MistakeTracker.value"""
        return self._total

    @property
    def history(self) -> list[MistakeRecord]:
        """返回错误历史（只读视图）"""
        return list(self._history)

    def _build_guidance(self, mistake_type: str, tool_name: str, count: int) -> str:
        """构造恢复提示 — 对标 Cline appendRecoveryNotice"""
        hint = _RECOVERY_HINTS.get(mistake_type, "请检查工具调用参数和执行环境。")
        return (
            f"[MistakeTracker 恢复提示] 检测到工具 `{tool_name}` 连续 {count} 次"
            f"犯 `{mistake_type}` 类型错误。{hint}"
        )

    def _build_stop_message(self) -> str:
        """构造停止消息 — 对标 Cline buildMistakeLimitStopMessage"""
        parts = [
            f"已中止：连续错误总数达到 {self._total}/{self.config.max_total} 上限。"
        ]
        if self._history:
            last = self._history[-1]
            parts.append(
                f"最近一次错误: iteration={last.iteration} "
                f"tool={last.tool_name} type={last.mistake_type} "
                f"details={last.details}"
            )
        # 按类型汇总
        if self._counts:
            summary = ", ".join(
                f"{k}={v}" for k, v in sorted(self._counts.items())
            )
            parts.append(f"错误分布: {summary}")
        parts.append("会话状态已保留，可发新消息从最新状态继续。")
        return " ".join(parts)
