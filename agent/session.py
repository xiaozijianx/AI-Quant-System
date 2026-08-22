# -*- coding: utf-8 -*-
"""会话管理 — 对标 Cline session persistence

管理每个对话会话的消息历史，支持:
    1. 获取会话历史消息
    2. 更新会话历史
    3. 清空会话
    4. 列出所有会话
    5. 本地 JSON 持久化（Phase 18 新增）

Phase 18 增强（对标 Cline file-session-service）:
    - 每个会话单独一个 JSON 文件: agent_data/sessions/<session_id>.json
    - 原子写入：先写 .tmp 再 rename，避免写入过程中崩溃导致数据损坏
    - 启动时调用 load_all() 自动恢复所有会话
    - 消息序列化/反序列化：AgentMessage <-> dict

会话历史同时存储在内存和本地文件，重启后通过 load_all() 恢复。

对标 Cline:
    - sdk/packages/core/src/session/services/file-session-service.ts
    - sdk/packages/core/src/session/services/persistence-service.ts
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.types import (
    AgentMessage,
    MessageRole,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 持久化文件格式版本
# Stage 6.2 升级到 2（追加 status/provider/model/ended_at/exit_code 字段）
_SESSION_FILE_VERSION = 2

# 默认持久化目录（相对于项目根目录）
_DEFAULT_PERSIST_DIR = "agent_data/sessions"


# ============================================================================
# Stage 6.1: 会话文件版本迁移注册表 — 对标 Cline LEGACY_MIGRATIONS + ensureSessionSchema
# ============================================================================
# key 为"源版本号"，value 为"将该版本迁移到下一版本"的函数
# 升级 _SESSION_FILE_VERSION 时，在此追加迁移函数
# 迁移函数接收旧 dict，返回新 dict（含更新后的 version 字段）


def _migrate_session_v1_to_v2(data: dict) -> dict:
    """v1 → v2 迁移：补齐 status/provider/model/ended_at/exit_code 字段

    对标 Cline sqlite-db.ts LEGACY_MIGRATIONS 的 ALTER TABLE + UPDATE 回填。
    旧 v1 文件无这些字段，加载时通过 .get(default) 兜底，但显式补齐字段
    可让后续写入直接含完整字段，避免每次加载都走兜底路径。

    Args:
        data: v1 格式的会话 dict

    Returns:
        v2 格式的会话 dict
    """
    data.setdefault("status", "active")
    data.setdefault("provider", "")
    data.setdefault("model", "")
    data.setdefault("ended_at", None)
    data.setdefault("exit_code", None)
    data["version"] = 2
    return data


_SESSION_MIGRATIONS: dict[int, callable] = {
    1: _migrate_session_v1_to_v2,
}


def _migrate_session_data(data: dict) -> dict | None:
    """将会话数据从其自带版本迁移到 _SESSION_FILE_VERSION

    对标 Cline ensureSessionSchema 的列检测+迁移逻辑。
    逐版本应用迁移函数，无对应迁移路径时返回 None。

    Args:
        data: 从 JSON 加载的原始 dict

    Returns:
        迁移后的 dict；无迁移路径时返回 None（调用方应跳过该文件）
    """
    version = data.get("version", 1)
    while version < _SESSION_FILE_VERSION:
        migrator = _SESSION_MIGRATIONS.get(version)
        if migrator is None:
            return None
        data = migrator(data)
        version = data.get("version", version + 1)
    return data


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class SessionInfo:
    """会话元信息 — 对标 Cline SessionRecord（量化场景子集）

    Stage 6.2 补齐字段：status/provider/model/ended_at/exit_code
    保留原 5 字段向后兼容，新字段均带默认值，旧文件加载时用默认值兜底。
    """
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    message_count: int = 0
    title: str = ""
    # Stage 6.2 新增字段 — 对标 Cline SessionRecord
    status: str = "active"            # active/completed/failed/aborted
    provider: str = ""                # 模型供应商标识（如 openai/dashscope）
    model: str = ""                   # 模型名（如 qwen-max）
    ended_at: float | None = None     # 会话结束时间戳，None 表示未结束
    exit_code: int | None = None      # 会话退出码，None 表示未结束


# ============================================================================
# 会话管理器 — 对标 Cline UnifiedSessionPersistenceService
# ============================================================================


class SessionManager:
    """会话管理器 — 管理对话历史 + 本地 JSON 持久化

    Phase 18 增强（对标 Cline file-session-service）:
        - update() 时同步落盘到 agent_data/sessions/<session_id>.json
        - clear() 时删除持久化文件
        - load_all() 启动时恢复所有会话
        - 原子写入：先写 .tmp 再 rename

    用法:
        manager = SessionManager()
        manager.load_all()  # 启动时恢复
        messages = manager.get_messages("session-1")
        manager.update("session-1", new_messages)  # 自动落盘
        manager.clear("session-1")  # 自动删除文件
    """

    def __init__(
        self,
        max_sessions: int = 50,
        max_messages_per_session: int = 100,
        persist_dir: str | Path | None = None,
    ) -> None:
        """初始化会话管理器

        Args:
            max_sessions: 最大会话数（超过时清理最旧的）
            max_messages_per_session: 每个会话最大消息数（超过时触发压缩）
            persist_dir: 持久化目录路径，默认 agent_data/sessions/
        """
        self._messages: dict[str, list[AgentMessage]] = {}
        self._info: dict[str, SessionInfo] = {}
        self._max_sessions = max_sessions
        self._max_messages = max_messages_per_session

        # Phase 18: 持久化目录
        if persist_dir is None:
            project_root = Path(__file__).resolve().parent.parent
            persist_dir = project_root / _DEFAULT_PERSIST_DIR
        self._persist_dir = Path(persist_dir)
        self._ensure_persist_dir()

        # Phase 31.8: 会话列表内存索引缓存 — 对标 Cline SessionIndex
        # 缓存按 last_active 降序排序的 SessionInfo 列表，
        # update/clear/load 时标记 _index_dirty=True，
        # list_sessions 时仅在 dirty 时重新排序，避免重复 O(n log n) 排序。
        self._sorted_index: list[SessionInfo] = []
        self._index_dirty: bool = True

    # ------------------------------------------------------------------
    # 持久化辅助方法 — Phase 18 新增
    # ------------------------------------------------------------------

    def _ensure_persist_dir(self) -> None:
        """确保持久化目录存在"""
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def _session_file_path(self, session_id: str) -> Path:
        """获取会话持久化文件路径

        防止路径遍历：只使用 session_id 的文件名部分
        """
        safe_name = os.path.basename(session_id)
        return self._persist_dir / f"{safe_name}.json"

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        """原子写入 JSON 文件 — 对标 Cline atomicWriteJson

        先写入 .tmp 文件，再 rename 到目标路径，
        避免写入过程中崩溃导致数据损坏。
        Windows 上 os.replace 是原子操作。
        """
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def _persist_session(self, session_id: str) -> None:
        """持久化单个会话到磁盘 — Phase 18 新增

        将会话元信息和消息列表序列化为 JSON 写入本地文件。
        写入失败仅记录日志，不影响内存状态。

        Phase 31.7: 使用跨进程文件锁保护写入 — 对标 Cline
        acquireSettingsLockSync。防止多进程同时写入同一会话文件
        导致数据丢失（如 web 进程 + scheduler 进程并发写）。
        """
        info = self._info.get(session_id)
        if info is None:
            return
        messages = self._messages.get(session_id, [])

        data = {
            "version": _SESSION_FILE_VERSION,
            "session_id": session_id,
            "created_at": info.created_at,
            "last_active": info.last_active,
            "title": info.title,
            # Stage 6.2 新增字段 — 对标 Cline SessionRecord
            "status": info.status,
            "provider": info.provider,
            "model": info.model,
            "ended_at": info.ended_at,
            "exit_code": info.exit_code,
            "messages": [_message_to_dict(m) for m in messages],
        }

        try:
            # Phase 31.7: 跨进程文件锁保护写入
            from agent.file_lock import FileLock
            path = self._session_file_path(session_id)
            with FileLock(path):
                self._atomic_write_json(path, data)
        except Exception as e:
            logger.error(f"持久化会话 {session_id} 失败: {e}", exc_info=True)

        # Stage 6.3: 同步更新索引文件，保证索引与会话文件一致
        self._persist_index()

    def _remove_persisted_session(self, session_id: str) -> None:
        """删除持久化的会话文件 — Phase 18 新增"""
        path = self._session_file_path(session_id)
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning(f"删除会话文件 {path} 失败: {e}")

    # ------------------------------------------------------------------
    # Stage 6.3: 索引文件支持 — 对标 Cline sessions.index.json
    # ------------------------------------------------------------------

    def _index_file_path(self) -> Path:
        """获取会话索引文件路径 — Stage 6.3 新增，对标 Cline sessions.index.json"""
        return self._persist_dir / "sessions.index.json"

    def _persist_index(self) -> None:
        """持久化会话索引到 sessions.index.json — Stage 6.3 新增

        索引内容为所有 SessionInfo 的精简 dict（不含 messages），
        保证单文件小且读取快。用 FileLock 保护写入，避免多进程并发写冲突。
        """
        from agent.file_lock import FileLock
        index_path = self._index_file_path()
        data = {
            "version": _SESSION_FILE_VERSION,
            "sessions": [
                {
                    "session_id": info.session_id,
                    "created_at": info.created_at,
                    "last_active": info.last_active,
                    "message_count": info.message_count,
                    "title": info.title,
                    "status": info.status,
                    "provider": info.provider,
                    "model": info.model,
                    "ended_at": info.ended_at,
                    "exit_code": info.exit_code,
                }
                for info in self._info.values()
            ],
        }
        try:
            with FileLock(index_path):
                self._atomic_write_json(index_path, data)
        except Exception as e:
            logger.error(f"持久化会话索引失败: {e}", exc_info=True)

    def _load_index(self) -> bool:
        """从 sessions.index.json 加载会话索引 — Stage 6.3 新增，启动时调用

        仅恢复 SessionInfo（不加载 messages），按需 load_session() 加载消息。

        Returns:
            True 表示索引加载成功，False 表示索引不存在或损坏（需回退 glob 扫描）
        """
        from agent.file_lock import FileLock
        index_path = self._index_file_path()
        if not index_path.exists():
            return False
        try:
            with FileLock(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            for s in data.get("sessions", []):
                session_id = s.get("session_id")
                if not session_id:
                    continue
                # 仅当内存中无该会话时才创建（避免覆盖已加载的完整数据）
                if session_id in self._info:
                    continue
                info = SessionInfo(
                    session_id=session_id,
                    created_at=s.get("created_at", time.time()),
                    last_active=s.get("last_active", time.time()),
                    message_count=s.get("message_count", 0),
                    title=s.get("title", ""),
                    status=s.get("status", "active"),
                    provider=s.get("provider", ""),
                    model=s.get("model", ""),
                    ended_at=s.get("ended_at"),
                    exit_code=s.get("exit_code"),
                )
                self._info[session_id] = info
                # messages 不加载，按需 load_session() 获取
                self._messages.setdefault(session_id, [])
            self._index_dirty = True
            return True
        except Exception as e:
            logger.warning(f"加载会话索引失败，将回退到 glob 扫描: {e}")
            return False

    def load_all(self) -> int:
        """加载所有持久化的会话 — 启动时调用 — Phase 18 新增

        Stage 6.3 优化：优先读取 sessions.index.json 索引（仅恢复 SessionInfo，
        不加载 messages），索引不存在或损坏时回退到 glob 扫描逐文件加载。

        Returns:
            成功加载的会话数量
        """
        # 优先尝试索引加载（快路径）
        if self._load_index():
            count = len(self._info)
            if count > 0:
                logger.info(f"已从索引恢复 {count} 个会话元信息（messages 按需加载）")
            return count
        # 回退到 glob 扫描（原逻辑，作为索引缺失时的兜底）
        count = 0
        for path in self._persist_dir.glob("*.json"):
            # 跳过索引文件，避免误当作会话文件解析
            if path.name == "sessions.index.json":
                continue
            session_id = path.stem
            if self._load_session_from_file(session_id, path):
                count += 1
        if count > 0:
            logger.info(f"已从磁盘恢复 {count} 个会话")
        # glob 加载完成后补写索引，下次启动走快路径
        if count > 0:
            self._persist_index()
        return count

    def _load_session_from_file(self, session_id: str, path: Path) -> bool:
        """从文件加载单个会话 — Phase 18 新增

        Args:
            session_id: 会话 ID
            path: 会话文件路径

        Returns:
            是否加载成功

        Phase 31.7: 使用跨进程文件锁保护读取 — 对标 Cline
        acquireSettingsLockSync。防止读取时其他进程正在写入导致
        读到不完整数据。
        """
        try:
            # Phase 31.7: 跨进程文件锁保护读取
            from agent.file_lock import FileLock
            with FileLock(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            # Stage 6.1: 版本校验改为尝试迁移，迁移失败再跳过
            # 对标 Cline ensureSessionSchema 的列检测+迁移逻辑
            data_version = data.get("version", 1)
            if data_version != _SESSION_FILE_VERSION:
                migrated = _migrate_session_data(data)
                if migrated is None:
                    logger.warning(
                        f"会话文件 {path} 版本 {data_version} 无迁移路径，跳过"
                    )
                    return False
                data = migrated

            messages = [_dict_to_message(m) for m in data.get("messages", [])]
            info = SessionInfo(
                session_id=session_id,
                created_at=data.get("created_at", time.time()),
                last_active=data.get("last_active", time.time()),
                title=data.get("title", ""),
                message_count=len(messages),
                # Stage 6.2: 读取新增字段（用 .get 兜底旧文件无此字段的情况）
                status=data.get("status", "active"),
                provider=data.get("provider", ""),
                model=data.get("model", ""),
                ended_at=data.get("ended_at"),
                exit_code=data.get("exit_code"),
            )
            self._messages[session_id] = messages
            self._info[session_id] = info
            # Phase 31.8: 标记索引缓存为 dirty
            self._index_dirty = True
            return True
        except Exception as e:
            logger.error(f"加载会话文件 {path} 失败: {e}", exc_info=True)
            return False

    def load_session(self, session_id: str) -> bool:
        """加载单个会话（按需加载）— Phase 18 新增，Stage 6.3 增强按需加载

        Stage 6.3 优化：从索引恢复的会话仅有 SessionInfo 无 messages，
        首次访问 messages 时从磁盘加载完整数据。

        如果会话已在内存中且有 messages 则跳过，否则从磁盘加载。

        Args:
            session_id: 会话 ID

        Returns:
            是否加载成功（已在内存中也算成功）
        """
        # 已在内存且有 messages（非从索引恢复的空壳）则跳过
        if session_id in self._info and self._messages.get(session_id):
            return True
        path = self._session_file_path(session_id)
        if not path.exists():
            return False
        return self._load_session_from_file(session_id, path)

    # ------------------------------------------------------------------
    # 原有方法 — 保留逻辑，增加持久化调用
    # ------------------------------------------------------------------

    def get_messages(self, session_id: str) -> list[AgentMessage]:
        """获取会话的历史消息

        对标 Cline file-session-service: 会话恢复时完整加载该会话的消息历史。
        索引快路径(load_all -> _load_index)恢复的会话只有 SessionInfo 无 messages，
        访问前需按需从磁盘加载，否则服务重启后 get_messages 返回空，
        导致回到旧对话继续提问时上下文丢失、无法接续。
        """
        # 内存中无消息但会话元信息存在(索引恢复)时，从磁盘加载完整消息历史
        if session_id in self._info and not self._messages.get(session_id):
            self.load_session(session_id)
        return list(self._messages.get(session_id, []))

    def update(self, session_id: str, messages: list[AgentMessage]) -> None:
        """更新会话的历史消息

        Phase 18 增强: 更新后同步落盘到本地 JSON 文件。
        """
        # 如果是新会话，创建信息
        if session_id not in self._info:
            self._info[session_id] = SessionInfo(
                session_id=session_id,
                title=_extract_title(messages),
            )
            # 检查会话数量限制
            self._evict_if_needed()

        # 更新消息和信息
        self._messages[session_id] = list(messages)
        info = self._info[session_id]
        info.last_active = time.time()
        info.message_count = len(messages)
        if not info.title and messages:
            info.title = _extract_title(messages)

        # Phase 31.8: 标记索引缓存为 dirty
        self._index_dirty = True

        # Phase 18: 同步落盘
        self._persist_session(session_id)

    def set_session_status(
        self,
        session_id: str,
        status: str,
        exit_code: int | None = None,
    ) -> None:
        """更新会话状态 — Stage 6.2 新增，对标 Cline SessionRecord.status

        Args:
            session_id: 会话 ID
            status: 新状态（active/completed/failed/aborted）
            exit_code: 退出码（仅在 ended 状态时设置）
        """
        info = self._info.get(session_id)
        if info is None:
            return
        info.status = status
        if status in ("completed", "failed", "aborted"):
            info.ended_at = time.time()
            if exit_code is not None:
                info.exit_code = exit_code
        self._index_dirty = True
        self._persist_session(session_id)

    def set_runtime_info(
        self,
        session_id: str,
        provider: str,
        model: str,
    ) -> None:
        """记录会话使用的模型供应方 — Stage 6.2 新增，对标 Cline SessionRecord.provider/model

        Args:
            session_id: 会话 ID
            provider: 模型供应商标识（如 openai/dashscope）
            model: 模型名（如 qwen-max）
        """
        info = self._info.get(session_id)
        if info is None:
            return
        info.provider = provider
        info.model = model
        self._persist_session(session_id)

    def clear(self, session_id: str) -> None:
        """清空指定会话

        Phase 18 增强: 同时删除持久化的会话文件。
        Stage 6.3 增强: 同步更新索引文件，保证索引与会话文件一致。
        """
        self._messages.pop(session_id, None)
        self._info.pop(session_id, None)
        # Phase 31.8: 标记索引缓存为 dirty
        self._index_dirty = True
        # Phase 18: 删除持久化文件
        self._remove_persisted_session(session_id)
        # Stage 6.3: 同步更新索引文件
        self._persist_index()

    def list_sessions(self) -> list[SessionInfo]:
        """列出所有会话，按最后活跃时间降序

        Phase 31.8: 使用内存索引缓存 — 对标 Cline SessionIndex。
        仅在 _index_dirty=True 时重新排序，否则直接返回缓存列表的副本。
        避免频繁调用 list_sessions（如前端轮询）时重复 O(n log n) 排序。
        """
        if self._index_dirty:
            self._sorted_index = sorted(
                self._info.values(),
                key=lambda x: x.last_active,
                reverse=True,
            )
            self._index_dirty = False
        return list(self._sorted_index)

    def get_info(self, session_id: str) -> SessionInfo | None:
        """获取会话信息"""
        return self._info.get(session_id)

    def _evict_if_needed(self) -> None:
        """清理最旧的会话（如果超过最大数量）"""
        if len(self._info) <= self._max_sessions:
            return

        # 找到最旧的会话
        oldest = min(self._info.values(), key=lambda x: x.last_active)
        logger.info(f"清理旧会话: {oldest.session_id}")
        self.clear(oldest.session_id)


# ============================================================================
# 消息序列化/反序列化 — AgentMessage <-> dict — Phase 18 新增
# ============================================================================


def _message_to_dict(msg: AgentMessage) -> dict[str, Any]:
    """将 AgentMessage 序列化为字典 — 用于 JSON 持久化

    对标 Cline normalizeStoredMessagesForPersistence
    """
    return {
        "role": msg.role.value,
        "content": [_part_to_dict(p) for p in msg.content],
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "id": msg.id,
        "metadata": _ensure_json_serializable(msg.metadata),
        "model_info": _ensure_json_serializable(msg.model_info) if msg.model_info else None,
        "metrics": _ensure_json_serializable(msg.metrics) if msg.metrics else None,
    }


def _part_to_dict(part: Any) -> dict[str, Any]:
    """将消息片段序列化为字典"""
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    if isinstance(part, ReasoningPart):
        return {
            "type": "reasoning",
            "text": part.text,
            "redacted": part.redacted,
            "metadata": _ensure_json_serializable(part.metadata),
        }
    if isinstance(part, ToolCallPart):
        return {
            "type": "tool-call",
            "tool_call_id": part.tool_call_id,
            "tool_name": part.tool_name,
            "input": _ensure_json_serializable(part.input),
            "metadata": _ensure_json_serializable(part.metadata),
        }
    if isinstance(part, ToolResultPart):
        return {
            "type": "tool-result",
            "tool_call_id": part.tool_call_id,
            "tool_name": part.tool_name,
            "output": _ensure_json_serializable(part.output),
            "is_error": part.is_error,
            "metadata": _ensure_json_serializable(part.metadata),
        }
    # 未知类型，转为字符串
    return {"type": "unknown", "text": str(part)}


def _dict_to_message(data: dict[str, Any]) -> AgentMessage:
    """从字典反序列化为 AgentMessage"""
    role_str = data.get("role", "user")
    try:
        role = MessageRole(role_str)
    except ValueError:
        role = MessageRole.USER

    content = [_dict_to_part(p) for p in data.get("content", [])]

    # 解析创建时间
    created_at_str = data.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except Exception:
            created_at = datetime.now(timezone.utc)
    else:
        created_at = datetime.now(timezone.utc)

    return AgentMessage(
        role=role,
        content=content,
        created_at=created_at,
        id=data.get("id", ""),
        metadata=data.get("metadata", {}) or {},
        model_info=data.get("model_info"),
        metrics=data.get("metrics"),
    )


def _dict_to_part(data: dict[str, Any]) -> Any:
    """从字典反序列化为消息片段"""
    part_type = data.get("type", "")
    if part_type == "text":
        return TextPart(text=data.get("text", ""))
    if part_type == "reasoning":
        return ReasoningPart(
            text=data.get("text", ""),
            redacted=data.get("redacted", False),
            metadata=data.get("metadata", {}) or {},
        )
    if part_type == "tool-call":
        return ToolCallPart(
            tool_call_id=data.get("tool_call_id", ""),
            tool_name=data.get("tool_name", ""),
            input=data.get("input", {}) or {},
            metadata=data.get("metadata", {}) or {},
        )
    if part_type == "tool-result":
        return ToolResultPart(
            tool_call_id=data.get("tool_call_id", ""),
            tool_name=data.get("tool_name", ""),
            output=data.get("output"),
            is_error=data.get("is_error", False),
            metadata=data.get("metadata", {}) or {},
        )
    # 未知类型，作为文本处理
    return TextPart(text=data.get("text", str(data)))


def _ensure_json_serializable(obj: Any) -> Any:
    """确保对象可 JSON 序列化 — 对标 Cline sanitizeMetadata

    不可序列化的对象转为字符串，保证持久化不会失败。
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _ensure_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ensure_json_serializable(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _extract_title(messages: list[AgentMessage]) -> str:
    """从消息中提取会话标题（取第一条用户消息的前 50 字符）"""
    for msg in messages:
        if msg.role == MessageRole.USER:
            text = ""
            for part in msg.content:
                if isinstance(part, TextPart):
                    text += part.text
            if text:
                return text[:50].strip()
    return "新对话"
