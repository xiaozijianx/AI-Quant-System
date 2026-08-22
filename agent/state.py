# -*- coding: utf-8 -*-
"""全局会话状态 — 对标 Cline 会话状态管理

管理每个会话（session_id）的全局状态，跨工具共享:
    1. todos: 任务清单（TodoWrite 工具维护）
    2. mode: 当前模式（act / plan，Plan Mode 工具切换）

设计要点:
    - 按 session_id 隔离，不同会话状态独立
    - 线程安全（threading.Lock 保护内部字典）
    - 数据类 dataclass 定义清晰结构
    - 提供 get_session_state() 入口函数

Phase 18 增强（对标 Cline state persistence）:
    - SessionState (todos/mode) 持久化到 agent_data/state/<session_id>.json
    - get_session_state 创建新状态前先尝试从磁盘加载
    - set_todos / set_mode / reset_session_state 同步落盘
    - load_all_states() 启动时恢复所有状态

对标 Cline:
    - sdk/packages/core/src/runtime/orchestration/runtime-builder.ts
      中的 mode 切换和状态管理
    - Claude 的 TodoWrite 工具状态持久化
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 状态文件格式版本
_STATE_FILE_VERSION = 1

# 默认状态持久化目录（相对于项目根目录）
_DEFAULT_STATE_PERSIST_DIR = "agent_data/state"


# ============================================================================
# 状态数据类
# ============================================================================

# 任务状态类型 — 对标 Claude TodoWrite status 字段
TodoStatus = Literal["pending", "in_progress", "completed"]

# Agent 模式类型 — 对标 Cline plan / act 模式
# P2-18: 新增 yolo 模式（自动执行模式，与 act 等价但无需逐步确认）
AgentMode = Literal["act", "plan", "yolo"]


@dataclass
class TodoItem:
    """任务清单项 — 对标 Claude TodoWrite 的 todo item

    增量式更新新增字段:
        - id: 任务 ID（用于 add/update/remove 增量操作，自动生成）
        - priority: 任务优先级（high / medium / low，默认 medium）

    Attributes:
        content: 任务描述（必填）
        status: 任务状态（pending / in_progress / completed）
        active_form: 当前正在执行的动作描述（status=in_progress 时使用）
        id: 任务 ID（用于增量更新，缺省时由工具自动生成）
        priority: 任务优先级（high / medium / low）
    """
    content: str
    status: TodoStatus = "pending"
    active_form: str = ""
    id: str = ""
    priority: str = "medium"

    def to_dict(self) -> dict:
        """转为字典 — 用于事件序列化和前端展示"""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "active_form": self.active_form,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoItem":
        """从字典构建 — 用于从持久化文件恢复 — Phase 18 新增

        向后兼容: 旧持久化数据缺少 id/priority 字段时使用默认值。
        """
        return cls(
            content=data.get("content", ""),
            status=data.get("status", "pending"),
            active_form=data.get("active_form", ""),
            id=data.get("id", ""),
            priority=data.get("priority", "medium"),
        )


@dataclass
class SessionState:
    """会话全局状态 — 跨工具共享

    Attributes:
        todos: 任务清单（TodoWrite 工具维护，替换式更新）
        mode: 当前模式（act / plan，Plan Mode 工具切换）
    """
    todos: list[TodoItem] = field(default_factory=list)
    mode: AgentMode = "act"

    def get_todos_snapshot(self) -> list[dict]:
        """获取 todos 的快照（深拷贝为字典列表）— 用于事件序列化"""
        return [todo.to_dict() for todo in self.todos]

    def has_in_progress(self) -> bool:
        """是否有正在进行的任务"""
        return any(t.status == "in_progress" for t in self.todos)

    def find_in_progress(self) -> TodoItem | None:
        """找到当前 in_progress 的任务"""
        for t in self.todos:
            if t.status == "in_progress":
                return t
        return None

    def to_dict(self) -> dict:
        """转为字典 — 用于持久化 — Phase 18 新增"""
        return {
            "version": _STATE_FILE_VERSION,
            "todos": [t.to_dict() for t in self.todos],
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        """从字典构建 — 用于从持久化文件恢复 — Phase 18 新增"""
        todos = [TodoItem.from_dict(t) for t in data.get("todos", [])]
        mode = data.get("mode", "act")
        # P2-18: 校验集合同步加入 yolo，保证持久化的 yolo 模式能正确恢复
        if mode not in ("act", "plan", "yolo"):
            mode = "act"
        return cls(todos=todos, mode=mode)


# ============================================================================
# Mode Switch Notice — Stage 36.1 (M1) 新增，对标 Cline createModeSwitchNoticeTracker
# ============================================================================


@dataclass
class ModeSwitchNotice:
    """mode 切换通知 — 对标 Cline ModeSwitchNotice

    记录用户从 from_mode 切换到 to_mode，用于在下一条用户消息前
    prepend <mode_notice> 标记，让模型感知切换时刻。

    对标 Cline:
        - sdk/packages/shared/src/prompt/format.ts L48-51 ModeSwitchNotice
        - sdk/packages/shared/src/prompt/format.ts L61-80 createModeSwitchNoticeTracker

    属性:
        from_mode: 切换前的模式（act / plan）
        to_mode: 切换后的模式（act / plan）
    """
    from_mode: str
    to_mode: str


# 全局 pending mode notices: session_id → ModeSwitchNotice
# Stage 36.1 (M1): 按 session_id 隔离，对标 Cline createModeSwitchNoticeTracker
# 每个 session 拥有独立的 pending notice，consume 后清除
_pending_mode_notices: dict[str, ModeSwitchNotice] = {}


# ============================================================================
# 全局会话状态注册表 — 按 session_id 隔离
# ============================================================================

# 全局会话状态字典: session_id → SessionState
_sessions: dict[str, SessionState] = {}

# 线程锁 — 保护 _sessions 字典的并发访问
_lock = threading.Lock()

# 状态持久化目录 — 默认 agent_data/state，可通过 set_state_persist_dir 修改
_state_persist_dir: Path = (
    Path(__file__).resolve().parent.parent / _DEFAULT_STATE_PERSIST_DIR
)


# ============================================================================
# 持久化辅助函数 — Phase 18 新增
# ============================================================================


def set_state_persist_dir(path: str | Path) -> None:
    """设置状态持久化目录 — Phase 18 新增

    应在服务启动前调用，确保所有状态文件都写入指定目录。

    Args:
        path: 持久化目录路径
    """
    global _state_persist_dir
    _state_persist_dir = Path(path)
    _state_persist_dir.mkdir(parents=True, exist_ok=True)


def _state_file_path(session_id: str) -> Path:
    """获取会话状态文件路径 — Phase 18 新增

    防止路径遍历：只使用 session_id 的文件名部分
    """
    safe_name = os.path.basename(session_id)
    return _state_persist_dir / f"{safe_name}.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写入 JSON 文件 — 对标 Cline atomicWriteJson — Phase 18 新增

    先写入 .tmp 文件，再 rename 到目标路径。
    """
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _persist_state(session_id: str) -> None:
    """持久化会话状态到磁盘 — Phase 18 新增

    将 SessionState (todos/mode) 序列化为 JSON 写入本地文件。
    写入失败仅记录日志，不影响内存状态。

    Phase 31.7: 使用跨进程文件锁保护写入 — 对标 Cline
    acquireSettingsLockSync。
    """
    state = _sessions.get(session_id)
    if state is None:
        return
    try:
        _state_persist_dir.mkdir(parents=True, exist_ok=True)
        # Phase 31.7: 跨进程文件锁保护写入
        from agent.file_lock import FileLock
        path = _state_file_path(session_id)
        with FileLock(path):
            _atomic_write_json(path, state.to_dict())
    except Exception as e:
        logger.error(f"持久化会话状态 {session_id} 失败: {e}", exc_info=True)


def _load_state_from_disk(session_id: str) -> SessionState | None:
    """从磁盘加载会话状态 — Phase 18 新增

    Args:
        session_id: 会话 ID

    Returns:
        加载成功的 SessionState，或 None（文件不存在/损坏）

    Phase 31.7: 使用跨进程文件锁保护读取 — 对标 Cline
    acquireSettingsLockSync。
    """
    path = _state_file_path(session_id)
    if not path.exists():
        return None
    try:
        # Phase 31.7: 跨进程文件锁保护读取
        from agent.file_lock import FileLock
        with FileLock(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if data.get("version") != _STATE_FILE_VERSION:
            logger.warning(f"状态文件 {path} 版本不兼容，跳过")
            return None
        return SessionState.from_dict(data)
    except Exception as e:
        logger.error(f"加载状态文件 {path} 失败: {e}", exc_info=True)
        return None


def _remove_state_file(session_id: str) -> None:
    """删除会话状态文件 — Phase 18 新增"""
    path = _state_file_path(session_id)
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.warning(f"删除状态文件 {path} 失败: {e}")


def load_all_states() -> int:
    """加载所有持久化的会话状态 — 启动时调用 — Phase 18 新增

    扫描持久化目录，加载所有 .json 状态文件到内存。
    损坏的文件会被跳过并记录日志。

    Returns:
        成功加载的状态数量
    """
    count = 0
    if not _state_persist_dir.exists():
        return 0
    with _lock:
        for path in _state_persist_dir.glob("*.json"):
            session_id = path.stem
            if session_id in _sessions:
                continue  # 已在内存中
            state = _load_state_from_disk(session_id)
            if state is not None:
                _sessions[session_id] = state
                count += 1
    if count > 0:
        logger.info(f"已从磁盘恢复 {count} 个会话状态")
    return count


# ============================================================================
# 会话状态访问接口 — 保留原有逻辑，增加持久化调用
# ============================================================================


def get_session_state(session_id: str) -> SessionState:
    """获取会话状态（不存在则创建）

    按 session_id 隔离状态，确保不同会话的 todos 和 mode 互不影响。

    Phase 18 增强: 创建新状态前先尝试从磁盘加载，重启后能恢复。

    Args:
        session_id: 会话 ID

    Returns:
        该会话的 SessionState 实例
    """
    with _lock:
        if session_id not in _sessions:
            # Phase 18: 先尝试从磁盘加载
            state = _load_state_from_disk(session_id)
            if state is not None:
                _sessions[session_id] = state
                logger.info(f"从磁盘恢复会话状态: {session_id}")
            else:
                _sessions[session_id] = SessionState()
        return _sessions[session_id]


def reset_session_state(session_id: str) -> None:
    """重置会话状态（清空 todos 并切回 act 模式）

    用于会话结束或用户主动重置。

    Phase 18 增强: 重置后同步落盘（覆盖旧的状态文件）。
    """
    with _lock:
        _sessions[session_id] = SessionState()
        # Phase 18: 同步落盘（写入空状态，覆盖旧文件）
        _persist_state(session_id)


def clear_session_state(session_id: str) -> None:
    """清除会话状态（从注册表中移除）

    Phase 18 增强: 同时删除持久化的状态文件。
    """
    with _lock:
        _sessions.pop(session_id, None)
        # Phase 18: 删除持久化文件
        _remove_state_file(session_id)


def get_mode(session_id: str) -> AgentMode:
    """获取会话当前模式"""
    return get_session_state(session_id).mode


def set_mode(session_id: str, mode: AgentMode) -> AgentMode:
    """设置会话当前模式，返回旧模式

    Phase 18 增强: 设置后同步落盘。
    Stage 36.1 (M1): 若 mode 实际切换（old_mode != mode），记录 pending notice
                     （对标 Cline tracker.record）。本函数对所有调用者一视同仁——
                     只要 mode 实际变化就会记录 notice。不希望记录 notice 的调用方
                     （如模型发起的 switch_to_act_mode，其切换通过 continuation prompt
                     自带 announce）应直接操作 SessionState 而非调用本函数。
    """
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            # 先加载，避免直接创建新状态丢失 todos
            state = _load_state_from_disk(session_id) or SessionState()
            _sessions[session_id] = state
        old_mode = state.mode
        state.mode = mode
        # Phase 18: 同步落盘
        _persist_state(session_id)
        # Stage 36.1 (M1): 在锁内记录 mode 切换 notice，避免竞态
        if old_mode != mode:
            _record_mode_switch_locked(session_id, old_mode, mode)
        return old_mode


# ============================================================================
# Mode Switch Notice Tracker — Stage 36.1 (M1) 新增
# 对标 Cline sdk/packages/shared/src/prompt/format.ts L61-80 createModeSwitchNoticeTracker
# ============================================================================


def _record_mode_switch_locked(
    session_id: str,
    from_mode: str,
    to_mode: str,
) -> None:
    """记录 mode 切换到 pending notice — 必须持有 _lock 时调用

    对标 Cline createModeSwitchNoticeTracker.record，语义完全一致:
        - from === to: 忽略（no-op）
        - 已有 pending 且 pending.from === to: 往返抵消，清除 pending
          （例: plan→act→plan，模式实际未变，模型无需感知）
        - 已有 pending 且 pending.from !== to: 保留原始 from，更新 to
          （例: act→plan→act→yolo 链式切换，保留原始 act 作为 from）
        - 无 pending: 记录新的 pending = {from, to}

    Args:
        session_id: 会话 ID
        from_mode: 切换前模式
        to_mode: 切换后模式
    """
    if from_mode == to_mode:
        return
    pending = _pending_mode_notices.get(session_id)
    if pending is not None:
        if pending.from_mode == to_mode:
            # 往返抵消：plan→act→plan，模式实际未变
            _pending_mode_notices.pop(session_id, None)
        else:
            # 链式切换：保留原始 from，更新 to
            pending.to_mode = to_mode
    else:
        _pending_mode_notices[session_id] = ModeSwitchNotice(
            from_mode=from_mode,
            to_mode=to_mode,
        )


def record_mode_switch(
    session_id: str,
    from_mode: str,
    to_mode: str,
) -> None:
    """记录用户发起的 mode 切换（线程安全版本）

    用于非 set_mode 路径记录 UI 切换（如前端直接调用 API 切换 mode）。
    set_mode 内部已调用 _record_mode_switch_locked，无需重复调用。

    对标 Cline createModeSwitchNoticeTracker.record。
    """
    with _lock:
        _record_mode_switch_locked(session_id, from_mode, to_mode)


def consume_mode_notice(session_id: str) -> ModeSwitchNotice | None:
    """取出并清除 pending mode notice — 对标 Cline tracker.consume

    在包装用户输入前调用，若有 pending notice 则 prepend <mode_notice>
    到用户消息前，让模型感知 mode 切换发生的精确位置。

    Args:
        session_id: 会话 ID

    Returns:
        ModeSwitchNotice 实例（若存在），否则 None
    """
    with _lock:
        return _pending_mode_notices.pop(session_id, None)


def format_mode_switch_notice(notice: ModeSwitchNotice) -> str:
    """格式化 mode 切换通知文本 — 对标 Cline formatModeSwitchNotice

    生成格式（与 Cline 完全一致）:
        <mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>

    对标 Cline:
        - sdk/packages/shared/src/prompt/format.ts L41-46 formatModeSwitchNotice

    Args:
        notice: mode 切换通知

    Returns:
        <mode_notice> XML 文本
    """
    return (
        f'<mode_notice>The user switched from {notice.from_mode} mode '
        f'to {notice.to_mode} mode before sending this message.</mode_notice>'
    )


def get_todos(session_id: str) -> list[TodoItem]:
    """获取会话的任务清单"""
    return get_session_state(session_id).todos


def set_todos(session_id: str, todos: list[TodoItem]) -> list[TodoItem]:
    """设置会话的任务清单（替换式更新），返回旧清单

    Phase 18 增强: 设置后同步落盘。
    """
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            # 先加载，避免直接创建新状态丢失 mode
            state = _load_state_from_disk(session_id) or SessionState()
            _sessions[session_id] = state
        old_todos = state.todos
        state.todos = todos
        # Phase 18: 同步落盘
        _persist_state(session_id)
        return old_todos


# ============================================================================
# 增量式更新辅助 — 用于 todo_write 工具的 add/update/remove 操作
# ============================================================================


def _generate_todo_id() -> str:
    """生成 todo ID — 8 位 hex，会话内足够唯一

    用于增量式 todo_write: add 操作自动为新 todo 项分配 ID，
    LLM 后续可通过该 ID 调用 update/remove。
    """
    return uuid.uuid4().hex[:8]


def update_todos_atomically(
    session_id: str,
    modifier: Callable[[list[TodoItem]], list[TodoItem]],
) -> tuple[list[TodoItem], list[TodoItem]]:
    """原子地 read-modify-write todos — 用于增量操作

    在 _lock 保护下执行: 读取当前 todos → 调用 modifier 计算新 todos →
    写回 state → 持久化。避免 get_todos + set_todos 之间的竞态。

    注意:
        - modifier 接收当前 todos 的浅拷贝，应返回新列表
        - modifier 不应就地修改传入的 TodoItem 对象（会影响 old_todos 快照），
          需要更新某项时请构造新的 TodoItem 实例
        - 若 modifier 返回原列表（未变更），state 仍会被赋值一次（幂等）

    Args:
        session_id: 会话 ID
        modifier: 接收当前 todos 列表，返回新 todos 列表的回调

    Returns:
        (old_todos, new_todos) — 修改前后的 todos（均为浅拷贝）
    """
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            state = _load_state_from_disk(session_id) or SessionState()
            _sessions[session_id] = state
        old_todos = list(state.todos)
        new_todos = modifier(list(state.todos))
        state.todos = new_todos
        _persist_state(session_id)
        return old_todos, new_todos
