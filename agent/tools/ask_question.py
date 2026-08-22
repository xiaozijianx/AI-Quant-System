# -*- coding: utf-8 -*-
"""向用户提问工具 — 对标 Cline createAskQuestionTool

让 Agent 在需要澄清信息时向用户提问，提供 2-5 个选项供用户选择。
通过 context.emit_update 将问题发送到前端展示，并阻塞等待用户回答。

工作流程:
    1. LLM 调用 ask_question(question="...", options=["选项1", "选项2", ...])
    2. 工具通过 context.emit_update 发送 {type: "ask_question", question, options}
    3. 前端展示问题和选项卡片
    4. 工具通过 asyncio.Event 阻塞等待用户回答（带 300s 超时）
    5. 用户通过 POST /api/chat/answer_question 端点提交回答
    6. set_question_answer 唤醒等待中的工具
    7. 返回用户的回答作为工具输出

设计说明:
    - 阻塞等待模式（对标 Cline ask_followup_question）:
      工具不立即返回，而是挂起等待用户回答，确保 LLM 能拿到真实回答
    - 通过全局 _pending_questions 字典管理待回答问题
      （模式同 agent/approval.py 的 _pending_approvals）
    - 300s 超时保护，避免永久挂起
    - 支持中止时清理（cancel_pending_questions_for_session）

对标 Cline:
    - sdk/packages/core/src/extensions/tools/definitions.ts createAskQuestionTool
    - apps/vscode/src/sdk/sdk-interaction-coordinator.ts handleAskQuestion
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)


# 提问超时时间（秒）— 对标 Cline 审批超时 300s
QUESTION_TIMEOUT_SECONDS = 300.0


@dataclass
class PendingQuestion:
    """待回答问题条目 — 对标 Cline pendingAskResolve

    工具调用 ask_question 时创建此条目，注册到全局字典。
    runtime 通过 await entry.event.wait() 挂起等待用户回答。
    用户通过 /api/chat/answer_question 端点提交回答后唤醒。

    Attributes:
        tool_call_id: 工具调用 ID（唯一标识，用于关联回答）
        question: 问题文本
        options: 选项数组
        session_id: 会话 ID
        event: 用于挂起/唤醒的 asyncio.Event
        answer: 用户回答（None=等待中，非 None=已回答）
        created_at: 创建时间戳
    """
    tool_call_id: str
    question: str
    options: list[str]
    session_id: str = ""
    event: asyncio.Event = field(default_factory=asyncio.Event)
    answer: str | None = None
    created_at: float = field(default_factory=lambda: time.time())


# 全局待回答问题字典: tool_call_id → PendingQuestion
# 模式同 agent/approval.py 的 _pending_approvals
_pending_questions: dict[str, PendingQuestion] = {}


def register_pending_question(
    tool_call_id: str,
    question: str,
    options: list[str],
    session_id: str = "",
) -> PendingQuestion:
    """注册待回答问题 — 对标 Cline handleAskQuestion 中 pendingAskResolve = resolve

    在全局字典中注册问题条目，返回带 asyncio.Event 的条目。
    runtime 通过 await entry.event.wait() 挂起等待用户回答。

    Args:
        tool_call_id: 工具调用 ID
        question: 问题文本
        options: 选项数组
        session_id: 会话 ID

    Returns:
        PendingQuestion 实例，含 event 用于等待
    """
    entry = PendingQuestion(
        tool_call_id=tool_call_id,
        question=question,
        options=options,
        session_id=session_id,
    )
    _pending_questions[tool_call_id] = entry
    logger.info(
        f"注册待回答问题: tool_call_id={tool_call_id}, session={session_id}"
    )
    return entry


def set_question_answer(tool_call_id: str, answer: str) -> bool:
    """设置用户回答并唤醒等待的协程 — 对标 Cline resolvePendingFollowup

    由 /api/chat/answer_question 端点调用。

    Args:
        tool_call_id: 工具调用 ID
        answer: 用户的回答文本

    Returns:
        是否设置成功（未找到对应问题则返回 False）
    """
    entry = _pending_questions.get(tool_call_id)
    if entry is None:
        logger.warning(f"未找到待回答问题: tool_call_id={tool_call_id}")
        return False

    entry.answer = answer
    entry.event.set()
    logger.info(
        f"用户回答已设置: tool_call_id={tool_call_id}, "
        f"answer={answer[:80]}..."
    )
    return True


def get_pending_question_meta(tool_call_id: str) -> dict[str, Any] | None:
    """获取待回答问题的元信息

    供 /api/chat/answer_question 端点验证 tool_call_id 有效性。

    Args:
        tool_call_id: 工具调用 ID

    Returns:
        含 question / options / session_id 的字典；未找到返回 None
    """
    entry = _pending_questions.get(tool_call_id)
    if entry is None:
        return None
    return {
        "tool_call_id": entry.tool_call_id,
        "question": entry.question,
        "options": entry.options,
        "session_id": entry.session_id,
    }


def clear_pending_question(tool_call_id: str) -> None:
    """清除待回答问题

    在问题回答完成（或超时/中止）后调用，从全局字典中移除。
    """
    _pending_questions.pop(tool_call_id, None)


def cancel_pending_questions_for_session(session_id: str) -> int:
    """取消指定会话的所有待回答问题 — 对标 Cline cancelPendingApprovals

    在会话中止或清除时调用，避免孤儿问题请求。

    Args:
        session_id: 会话 ID

    Returns:
        取消的问题数量
    """
    to_cancel = [
        tool_call_id for tool_call_id, entry in _pending_questions.items()
        if entry.session_id == session_id
    ]
    for tool_call_id in to_cancel:
        entry = _pending_questions.get(tool_call_id)
        if entry is not None:
            # 设置空回答并唤醒，让等待的协程能退出
            entry.answer = ""
            entry.event.set()
    return len(to_cancel)


def list_pending_questions(session_id: str | None = None) -> list[dict[str, Any]]:
    """列出待回答问题

    用于状态查询和调试。

    Args:
        session_id: 可选的会话 ID 过滤

    Returns:
        待回答问题列表，每项含 tool_call_id/question/options/session_id/created_at
    """
    result: list[dict[str, Any]] = []
    for entry in _pending_questions.values():
        if session_id is not None and entry.session_id != session_id:
            continue
        result.append({
            "tool_call_id": entry.tool_call_id,
            "question": entry.question,
            "options": entry.options,
            "session_id": entry.session_id,
            "created_at": entry.created_at,
            "answered": entry.answer is not None,
        })
    return result


class AskQuestionTool(BaseTool):
    """向用户提问工具 — 对标 Cline createAskQuestionTool

    参数:
        question: 问题文本（必填）
        options: 2-5 个选项数组（必填）
    """

    @property
    def name(self) -> str:
        return "ask_question"

    @property
    def description(self) -> str:
        return (
            "向用户提问以澄清信息。关键约束: "
            "每次只能问一个问题; 问题必须具体明确，避免歧义; "
            "options 必须提供 2-5 个互斥选项; 选项文本应简洁且可区分; "
            "仅在确需用户澄清时调用，能自行判断的事勿打扰用户。"
            "参数: question(必填): 问题文本; "
            "options(必填): 2-5 个选项数组"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "minLength": 1,
                    "description": "问题文本",
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "minItems": 2,
                    "maxItems": 5,
                    "description": "2-5 个选项数组",
                },
            },
            "required": ["question", "options"],
        }

    @property
    def lifecycle(self) -> None:
        # 不是 completes_run — 提问后不结束运行
        return None

    @property
    def read_only(self) -> bool:
        return True

    @property
    def timeout_ms(self) -> int | None:
        # P1-10: 阻塞等待用户回答需要长超时
        # 设为 310s（略大于内部 QUESTION_TIMEOUT_SECONDS=300s），
        # 确保内部超时先触发，runtime 外层超时不会提前 kill 工具
        return int(QUESTION_TIMEOUT_SECONDS * 1000) + 10_000

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行向用户提问 — 对标 Cline createAskQuestionTool.execute()

        阻塞等待模式（对标 Cline ask_followup_question）:
            1. 通过 context.emit_update 发送问题到前端
            2. 注册 PendingQuestion 到全局字典
            3. 通过 asyncio.Event 阻塞等待用户回答
            4. 用户通过 /api/chat/answer_question 提交回答后唤醒
            5. 返回用户的回答作为工具输出

        超时保护:
            - 300 秒未收到回答则返回超时错误
            - 中止信号触发时清理并返回中止提示
        """
        question = input["question"]
        options = input["options"]

        # 工具调用 ID — 用于关联用户的回答
        tool_call_id = context.tool_call_id or ""
        session_id = context.session_id or ""

        if not tool_call_id:
            # 无 tool_call_id 时无法关联回答，退化为非阻塞模式
            # 保持向后兼容（虽然实际不会发生，runtime 总会填充 tool_call_id）
            logger.warning("ask_question 缺少 tool_call_id，退化为非阻塞模式")
            if context.emit_update is not None:
                try:
                    context.emit_update({
                        "type": "ask_question",
                        "question": question,
                        "options": options,
                    })
                except Exception:
                    pass
            return AgentToolResult(
                output={
                    "question": question,
                    "options": options,
                    "status": "已发送问题到前端（无 tool_call_id，无法等待回答）",
                },
                metadata={
                    "tool": "ask_question",
                    "options_count": len(options),
                },
            )

        # 注册待回答问题到全局字典
        entry = register_pending_question(
            tool_call_id=tool_call_id,
            question=question,
            options=options,
            session_id=session_id,
        )

        # 通过 context.emit_update 发送问题到前端
        # 前端展示问题卡片，用户点击选项或输入文本后 POST /api/chat/answer_question
        if context.emit_update is not None:
            try:
                context.emit_update({
                    "type": "ask_question",
                    "tool_call_id": tool_call_id,
                    "question": question,
                    "options": options,
                })
            except Exception:
                # 通知失败不影响等待逻辑
                pass

        # 阻塞等待用户回答 — 对标 Cline pendingAskResolve Promise
        abort_signal = getattr(context, "abort_signal", None)
        try:
            # 组合等待: 用户回答 event 或 abort_signal，任一触发即唤醒
            wait_tasks = [asyncio.ensure_future(entry.event.wait())]
            if abort_signal is not None:
                wait_tasks.append(asyncio.ensure_future(abort_signal.wait()))

            done, pending = await asyncio.wait(
                wait_tasks,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=QUESTION_TIMEOUT_SECONDS,
            )

            # 取消未完成的任务，避免协程泄漏
            for task in pending:
                task.cancel()

            # 超时: 未收到回答
            if not done:
                return AgentToolResult(
                    output={
                        "question": question,
                        "options": options,
                        "status": f"用户未在 {int(QUESTION_TIMEOUT_SECONDS)}s 内回答",
                    },
                    is_error=True,
                    metadata={
                        "tool": "ask_question",
                        "options_count": len(options),
                        "timeout": True,
                    },
                )

            # 检查是否被中止
            if abort_signal is not None and abort_signal.is_set():
                return AgentToolResult(
                    output={
                        "question": question,
                        "options": options,
                        "status": "问题被用户中止",
                    },
                    is_error=True,
                    metadata={
                        "tool": "ask_question",
                        "options_count": len(options),
                        "aborted": True,
                    },
                )

            # 用户已回答
            answer = entry.answer or ""
            return AgentToolResult(
                output={
                    "question": question,
                    "options": options,
                    "answer": answer,
                    "status": "用户已回答",
                },
                metadata={
                    "tool": "ask_question",
                    "options_count": len(options),
                    "answered": True,
                },
            )
        finally:
            # 清理全局字典中的条目
            clear_pending_question(tool_call_id)
