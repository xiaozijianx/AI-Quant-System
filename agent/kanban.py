# -*- coding: utf-8 -*-
"""任务看板系统 — 对标 Cline kanban

注意：本模块已屏蔽（2026-08-04）。原因：TodoWrite 工具已从代码中移除，
SessionState.todos 无数据源，看板失去意义。server.py 中三个看板端点
（/kanban、/kanban/overview、/kanban/progress）已整体注释，前端入口也已屏蔽。
本模块保留为死代码，若日后恢复 TodoWrite 工具，可取消 server.py 端点和
前端入口的注释后复用。

KanbanManager:
    基于 SessionState.todos 构建看板视图，提供 3 列看板（待办/进行中/已完成）。
    看板是 TodoWrite 工具的可视化层，不维护独立任务状态，避免数据冗余。

设计要点:
    - 不存储独立任务: 直接读取 SessionState.todos，单一数据源
    - 多视图支持: 看板视图（3列）/ 列表视图 / 进度统计
    - 跨会话聚合: 可查询所有会话的看板概览
    - 与 TodoWrite 联动: todos 变更时看板自动更新

与 Cline 对比:
    Cline 的 kanban.ts 主要负责启动外部 kanban npm 工具（看板应用），
    而本系统是 Web 应用，需要内嵌看板视图，因此:
        - 不启动外部进程
        - 直接提供看板数据 API
        - 前端通过 /api/chat/kanban 端点获取看板数据并渲染

典型用途:
    - 用户在 AI 对话页面点击"看板"按钮，查看当前会话的任务进度
    - 看板展示 3 列: 待办 / 进行中 / 已完成
    - 每列显示任务卡片（content + active_form）
    - 顶部显示整体进度（如 5/8 完成）

对标 Cline:
    - apps/cli/src/commands/kanban.ts: launchKanban（外部应用启动）
    - .kanban/config.json: 看板配置
    - 本系统改为内嵌看板视图，提供数据 API
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent.state import (
    AgentMode,
    SessionState,
    TodoItem,
    get_session_state,
    get_todos,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 看板数据结构
# ============================================================================


@dataclass
class KanbanCard:
    """看板卡片 — 对应一个 TodoItem

    Attributes:
        content: 任务描述
        status: 任务状态（pending / in_progress / completed）
        active_form: 当前执行动作描述
        session_id: 所属会话 ID
    """
    content: str
    status: str
    active_form: str
    session_id: str

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "status": self.status,
            "active_form": self.active_form,
            "session_id": self.session_id,
        }


@dataclass
class KanbanColumn:
    """看板列 — 对标 Cline kanban 列

    Attributes:
        id: 列 ID（pending / in_progress / completed）
        title: 列标题（中文）
        cards: 该列下的卡片列表
    """
    id: str
    title: str
    cards: list[KanbanCard]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "cards": [c.to_dict() for c in self.cards],
            "count": len(self.cards),
        }


@dataclass
class KanbanBoard:
    """看板 — 对标 Cline kanban board

    Attributes:
        session_id: 会话 ID
        mode: 当前工作模式（act / plan）
        columns: 3 列看板（待办/进行中/已完成）
        stats: 进度统计
    """
    session_id: str
    mode: AgentMode
    columns: list[KanbanColumn]
    stats: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "columns": [c.to_dict() for c in self.columns],
            "stats": self.stats,
        }


# ============================================================================
# KanbanManager — 看板管理器
# ============================================================================


class KanbanManager:
    """看板管理器 — 基于 SessionState.todos 构建看板视图

    设计要点:
        - 无状态: 不缓存看板数据，每次查询实时构建（todos 是单一数据源）
        - 线程安全: 通过 SessionState 的锁保护
        - 简单 API: get_board / get_overview / get_progress

    用法:
        manager = get_kanban_manager()
        board = manager.get_board(session_id="xxx")
        # board.to_dict() → 前端渲染数据
    """

    def get_board(self, session_id: str) -> KanbanBoard:
        """获取会话的看板视图 — 实时构建

        Args:
            session_id: 会话 ID

        Returns:
            KanbanBoard 实例，包含 3 列卡片和统计信息
        """
        state = get_session_state(session_id)
        return self._build_board(session_id, state)

    def get_progress(self, session_id: str) -> dict[str, int]:
        """获取会话的任务进度统计

        Returns:
            {"total": N, "pending": N, "in_progress": N, "completed": N,
             "completion_rate": 0.0~1.0}
        """
        state = get_session_state(session_id)
        return self._calc_stats(state.todos)

    def get_overview(self) -> dict[str, Any]:
        """获取所有会话的看板概览 — 对标 Cline kanban 多项目视图

        扫描所有持久化的会话状态，返回每个会话的看板摘要。

        Returns:
            {
                "sessions": [
                    {
                        "session_id": "xxx",
                        "mode": "act",
                        "title": "会话标题（第一条用户消息前 50 字符）",
                        "stats": {"total": N, "pending": N, ...},
                        "current_task": "正在执行的任务内容" / None,
                    },
                    ...
                ],
                "total_sessions": N,
                "total_tasks": N,
            }
        """
        from agent.state import _sessions, _lock

        summaries: list[dict[str, Any]] = []
        with _lock:
            session_ids = list(_sessions.keys())

        # 延迟导入会话管理器，避免与 server.py 相互引用
        from agent.server import _session_manager

        for sid in session_ids:
            try:
                state = get_session_state(sid)
                stats = self._calc_stats(state.todos)
                current = state.find_in_progress()
                # 从会话管理器取标题（对应第一条用户消息前 50 字符），无则回退到会话 ID
                info = _session_manager.get_info(sid)
                title = info.title if info and info.title else sid
                summaries.append({
                    "session_id": sid,
                    "mode": state.mode,
                    "title": title,
                    "stats": stats,
                    "current_task": current.content if current else None,
                    "current_action": current.active_form if current else None,
                })
            except Exception as e:
                logger.warning(f"获取会话 {sid} 看板摘要失败: {e}")

        total_tasks = sum(s["stats"]["total"] for s in summaries)
        return {
            "sessions": summaries,
            "total_sessions": len(summaries),
            "total_tasks": total_tasks,
        }

    def _build_board(self, session_id: str, state: SessionState) -> KanbanBoard:
        """构建看板视图"""
        todos = state.todos
        stats = self._calc_stats(todos)

        # 按 status 分组
        pending_cards: list[KanbanCard] = []
        in_progress_cards: list[KanbanCard] = []
        completed_cards: list[KanbanCard] = []

        for todo in todos:
            card = KanbanCard(
                content=todo.content,
                status=todo.status,
                active_form=todo.active_form,
                session_id=session_id,
            )
            if todo.status == "pending":
                pending_cards.append(card)
            elif todo.status == "in_progress":
                in_progress_cards.append(card)
            elif todo.status == "completed":
                completed_cards.append(card)

        columns = [
            KanbanColumn(
                id="pending",
                title="待办",
                cards=pending_cards,
            ),
            KanbanColumn(
                id="in_progress",
                title="进行中",
                cards=in_progress_cards,
            ),
            KanbanColumn(
                id="completed",
                title="已完成",
                cards=completed_cards,
            ),
        ]

        return KanbanBoard(
            session_id=session_id,
            mode=state.mode,
            columns=columns,
            stats=stats,
        )

    def _calc_stats(self, todos: list[TodoItem]) -> dict[str, int]:
        """计算任务统计"""
        total = len(todos)
        pending = sum(1 for t in todos if t.status == "pending")
        in_progress = sum(1 for t in todos if t.status == "in_progress")
        completed = sum(1 for t in todos if t.status == "completed")
        completion_rate = (completed / total) if total > 0 else 0.0
        return {
            "total": total,
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed,
            "completion_rate": round(completion_rate, 4),
        }


# ============================================================================
# 单例管理
# ============================================================================

_kanban_manager: KanbanManager | None = None


def get_kanban_manager() -> KanbanManager:
    """获取全局 KanbanManager 单例"""
    global _kanban_manager
    if _kanban_manager is None:
        _kanban_manager = KanbanManager()
    return _kanban_manager
