# -*- coding: utf-8 -*-
"""文件上下文追踪器 — Phase 29.3 新增，对标 Cline FileContextTracker

记录会话期间所有被工具读取/编辑/创建/删除的文件路径，并持久化到磁盘。

设计目标:
    1. 替代 ContextCompactor._summarize_tool_activity 的临时消息扫描，
       压缩摘要直接从 tracker 取数（更准确，且能跨压缩周期保留）
    2. 前端通过 /api/agent/file_context/<session_id> 端点查看当前会话涉及的文件
    3. 后续 budget-projection（Phase 29.4）可基于 tracker 数据估算未来 token 占用

数据结构（持久化到 agent_data/file_context/<session_id>.json）:
    {
        "session_id": "abc123",
        "entries": [
            {
                "path": "/abs/path/to/file.py",
                "operation": "read",      # read / edited / created / deleted
                "timestamp": "2026-07-25T10:30:00+08:00",
                "tool_name": "read_files", # 触发的工具名（可选）
                "iteration": 1            # 触发时的迭代轮次（可选）
            },
            ...
        ]
    }

对外暴露的精简视图（get_state() 返回）:
    {
        "read": [path1, path2, ...],      # 读取过的文件（去重，按时间排序）
        "edited": [...],                  # 编辑过的文件
        "created": [...],                 # 创建的文件
        "deleted": [...]                  # 删除的文件
    }

语义差异说明（Stage 6.8 标注）:
    本实现与 Cline FileContextTracker 的设计目标不同:
        - Cline: 聚焦"过期检测"（stale detection），通过 chokidar 文件 watcher
          检测用户在 Cline 外部修改文件，避免 diff 编辑时上下文过期
        - 本仓库: 聚焦"活动日志"（activity logging），记录工具读写文件清单，
          用于压缩摘要和前端审计

    操作类型语义差异（W3）:
        - Cline: 按"谁触发编辑"分类（read_tool/user_edited/cline_edited/file_mentioned）
        - 本仓库: 按"什么操作"分类（read/edited/created/deleted）
        - 原因: 本仓库无文件 watcher，agent 是唯一编辑者，无需区分 user/cline 编辑
        - 影响: 本仓库的 edited 合并了 Cline 的 user_edited + cline_edited；
          created/deleted 在 Cline 中归为 cline_edited

    去重策略差异（W9）:
        - Cline: 不去重，旧 entry 标记 stale，保留完整时间序列
        - 本仓库: 同 path+operation 去重，保留首次记录
        - 原因: 压缩摘要场景只需"哪些文件被读/改过"，无需时间序列
        - 影响: 本仓库无法回答"该文件被编辑了几次"，但 JSON 体积更小

    保持现状的理由:
        - 服务端 agent 无外部编辑场景，stale detection 系列功能非必需
        - 去重策略更适合压缩摘要和前端审计需求
        - 操作类型按"什么操作"分类更直观
        - 若未来引入外部编辑场景，可补充 source 字段和 watchdog 文件监听

Cline 参考位置:
    - third_party/cline/apps/vscode/src/core/context/context-tracking/FileContextTracker.ts
    - third_party/cline/apps/vscode/src/core/context/context-tracking/ContextTrackerTypes.ts
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 操作类型枚举
# ============================================================================

# 文件操作类型常量 — 对标 Cline FileContextEntryOperation
# 语义差异（Stage 6.8 标注）:
#   - Cline 按"谁触发编辑"分类（read_tool/user_edited/cline_edited/file_mentioned）
#   - 本仓库按"什么操作"分类（read/edited/created/deleted）
#   - 本仓库无 file_mentioned（未追踪 prompt 中提到的文件）
#   - 本仓库无 user_edited（无文件 watcher，agent 是唯一编辑者）
#   - Cline 的 created 归为 cline_edited，本仓库单独分类
OP_READ = "read"          # 读取（read_files / list_files 等）— 对标 Cline read_tool
OP_EDITED = "edited"      # 编辑已存在文件（editor / apply_patch / file_write 覆盖）— 对标 Cline cline_edited
OP_CREATED = "created"    # 创建新文件（file_write 新建）— Cline 归为 cline_edited
OP_DELETED = "deleted"    # 删除文件（暂未使用，预留给未来 file_delete 工具）— Cline 无此概念

VALID_OPERATIONS = {OP_READ, OP_EDITED, OP_CREATED, OP_DELETED}


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class FileContextEntry:
    """单条文件操作记录 — 对标 Cline FileContextEntry

    语义差异（Stage 6.8 标注）:
        - Cline FileMetadataEntry 含 record_state（active/stale）+ record_source
        - 本仓库无 record_state（去重策略不保留 stale）
        - 本仓库 source 字段预留，当前未使用（未来可追踪 prompt 提到的文件）

    Attributes:
        path: 文件绝对路径（已规范化）
        operation: 操作类型（read/edited/created/deleted）
        timestamp: ISO 格式时间戳（含时区）
        tool_name: 触发工具名（可选，用于审计）
        iteration: 触发时的迭代轮次（可选）
        source: 记录来源（预留，当前未使用；未来可为 "tool"/"user_mentioned"）
    """
    path: str
    operation: str
    timestamp: str = ""
    tool_name: str = ""
    iteration: int = 0
    source: str = ""  # Stage 6.8 预留

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# FileContextTracker — 单会话追踪器
# ============================================================================

class FileContextTracker:
    """文件上下文追踪器 — 单个会话独立一个实例

    用法:
        tracker = FileContextTracker(session_id="abc123")
        tracker.record("/path/to/file.py", "read", tool_name="read_files")
        state = tracker.get_state()  # {"read": [...], "edited": [...], ...}
        tracker.save()  # 持久化到磁盘
    """

    def __init__(
        self,
        session_id: str,
        storage_dir: Path | str | None = None,
    ) -> None:
        """初始化追踪器

        Args:
            session_id: 会话 ID（用作持久化文件名）
            storage_dir: 持久化目录，默认 agent_data/file_context/
        """
        self.session_id = session_id or "default"
        if storage_dir is None:
            # 默认路径：项目根目录下的 agent_data/file_context/
            # 相对路径，由调用方决定 cwd
            storage_dir = Path("agent_data") / "file_context"
        self.storage_dir = Path(storage_dir)
        self.storage_path = self.storage_dir / f"{self.session_id}.json"

        self._entries: list[FileContextEntry] = []
        self._lock = threading.Lock()

        # 启动时尝试加载已有数据
        self._load()

    # ------------------------------------------------------------------
    # 记录接口
    # ------------------------------------------------------------------

    def record(
        self,
        path: str | Path,
        operation: str,
        tool_name: str = "",
        iteration: int = 0,
        timestamp: str | None = None,
    ) -> None:
        """记录一次文件操作

        Args:
            path: 文件路径（绝对或相对，会尝试规范化）
            operation: 操作类型（read/edited/created/deleted）
            tool_name: 触发工具名（可选）
            iteration: 触发时的迭代轮次（可选）
            timestamp: 自定义时间戳（ISO 格式），None 时取当前时间

        Notes:
            - 同一 path+operation 不会重复记录（按 path 去重）
            - 操作类型非法时记录 warning 并忽略
        """
        if operation not in VALID_OPERATIONS:
            logger.warning(
                "未知文件操作类型: %s（path=%s），合法值: %s",
                operation, path, VALID_OPERATIONS,
            )
            return

        # 规范化路径：尝试 resolve 为绝对路径，统一用正斜杠
        # resolve() 失败时（如不存在的路径）回退到原字符串
        try:
            path_obj = Path(path)
            # expanduser 解析 ~，resolve 转绝对路径（strict=False 允许不存在）
            resolved = path_obj.expanduser().resolve(strict=False)
            path_str = str(resolved).replace("\\", "/")
        except Exception:
            path_str = str(path).replace("\\", "/")

        # 时间戳默认取当前 UTC 时间
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

        with self._lock:
            # 同 path+operation 去重（保留首次记录的时间戳）
            # 语义差异（Stage 6.8 标注）:
            #   - Cline 不去重，旧 entry 标记 record_state="stale"，新 entry 标记 "active"
            #   - 本仓库去重，仅保留"该文件曾被该操作触达"的事实
            #   - 本仓库策略: JSON 体积小，前端展示清晰，适合压缩摘要场景
            #   - Cline 策略: 保留完整时间序列，支持按时间戳查询，适合 stale detection
            for entry in self._entries:
                if entry.path == path_str and entry.operation == operation:
                    return

            self._entries.append(FileContextEntry(
                path=path_str,
                operation=operation,
                timestamp=timestamp,
                tool_name=tool_name,
                iteration=iteration,
            ))
            logger.debug(
                "FileContextTracker record: %s %s (tool=%s iter=%d)",
                operation, path_str, tool_name, iteration,
            )

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, list[str]]:
        """获取精简视图 — 对标 Cline FileContextState

        Returns:
            {"read": [...], "edited": [...], "created": [...], "deleted": [...]}
            每个列表按记录时间排序（早记录在前），路径去重
        """
        with self._lock:
            result: dict[str, list[str]] = {
                OP_READ: [],
                OP_EDITED: [],
                OP_CREATED: [],
                OP_DELETED: [],
            }
            for entry in self._entries:
                bucket = result.get(entry.operation, [])
                if entry.path not in bucket:
                    bucket.append(entry.path)
                result[entry.operation] = bucket
            return result

    def get_entries(self) -> list[dict[str, Any]]:
        """获取完整记录列表（含时间戳和工具名）— 供前端展示和审计

        注意（Stage 6.8 标注）: entries 是去重后的快照，非完整操作历史。
        同一文件同一操作仅保留首次记录，无法还原"该文件被编辑了几次"。
        如需完整时间序列，可参考 Cline 的 stale 标记策略改造。
        """
        with self._lock:
            return [e.to_dict() for e in self._entries]

    def get_files_all(self) -> list[str]:
        """获取所有涉及过的文件路径（合并所有操作类型，去重）"""
        with self._lock:
            seen: list[str] = []
            for entry in self._entries:
                if entry.path not in seen:
                    seen.append(entry.path)
            return seen

    # ------------------------------------------------------------------
    # 持久化接口
    # ------------------------------------------------------------------

    def save(self) -> bool:
        """持久化到磁盘

        Returns:
            True 表示保存成功，False 表示失败（目录创建或写入异常）
        """
        with self._lock:
            data = {
                "session_id": self.session_id,
                "entries": [e.to_dict() for e in self._entries],
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.storage_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self.storage_path)  # 原子替换
            return True
        except Exception as e:
            logger.warning(
                "FileContextTracker 保存失败: session=%s, path=%s, error=%s",
                self.session_id, self.storage_path, e,
            )
            return False

    def _load(self) -> None:
        """从磁盘加载（若文件存在）"""
        if not self.storage_path.exists():
            return

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            entries_data = data.get("entries", [])
            with self._lock:
                self._entries = [
                    FileContextEntry(
                        path=e.get("path", ""),
                        operation=e.get("operation", ""),
                        timestamp=e.get("timestamp", ""),
                        tool_name=e.get("tool_name", ""),
                        iteration=e.get("iteration", 0),
                        source=e.get("source", ""),  # Stage 6.8 新增
                    )
                    for e in entries_data
                    if e.get("operation") in VALID_OPERATIONS and e.get("path")
                ]
            logger.debug(
                "FileContextTracker 加载 %d 条记录: session=%s",
                len(self._entries), self.session_id,
            )
        except Exception as e:
            logger.warning(
                "FileContextTracker 加载失败（将重置）: session=%s, error=%s",
                self.session_id, e,
            )
            with self._lock:
                self._entries = []

    def clear(self) -> None:
        """清空内存记录并删除持久化文件"""
        with self._lock:
            self._entries = []
        try:
            if self.storage_path.exists():
                self.storage_path.unlink()
        except Exception as e:
            logger.warning("FileContextTracker 删除持久化文件失败: %s", e)


# ============================================================================
# 全局 Tracker 注册表 — 按 session_id 缓存实例
# ============================================================================

class _TrackerRegistry:
    """全局 Tracker 注册表 — 按 session_id 缓存实例，避免重复加载

    线程安全。AgentRuntime 和 server.py 共享同一实例。
    """

    def __init__(self) -> None:
        self._trackers: dict[str, FileContextTracker] = {}
        self._lock = threading.Lock()
        # 全局存储目录（可由外部通过 set_storage_dir 修改）
        self._storage_dir: Path | None = None

    def set_storage_dir(self, path: Path | str) -> None:
        """设置全局存储目录（影响后续 get_tracker 创建的新实例）"""
        with self._lock:
            self._storage_dir = Path(path)
            # 已缓存的 tracker 不受影响（每个 tracker 在创建时确定 storage_dir）

    def get_tracker(
        self,
        session_id: str,
        storage_dir: Path | str | None = None,
    ) -> FileContextTracker:
        """获取或创建 session 对应的 tracker

        Args:
            session_id: 会话 ID
            storage_dir: 自定义存储目录，None 时使用注册表全局设置或默认路径

        Returns:
            FileContextTracker 实例（已加载历史记录）
        """
        sid = session_id or "default"
        with self._lock:
            if sid in self._trackers:
                return self._trackers[sid]

            effective_dir = storage_dir or self._storage_dir
            tracker = FileContextTracker(
                session_id=sid,
                storage_dir=effective_dir,
            )
            self._trackers[sid] = tracker
            return tracker

    def remove_tracker(self, session_id: str) -> None:
        """从缓存中移除（不删除持久化文件）"""
        sid = session_id or "default"
        with self._lock:
            self._trackers.pop(sid, None)

    def clear_all(self) -> None:
        """清空所有缓存的 tracker（不删除持久化文件）"""
        with self._lock:
            self._trackers.clear()


# 模块级单例
_registry = _TrackerRegistry()


def get_tracker(session_id: str) -> FileContextTracker:
    """获取 session 对应的 FileContextTracker — 模块级便捷函数

    Args:
        session_id: 会话 ID

    Returns:
        FileContextTracker 实例（首次调用时自动创建并加载历史记录）
    """
    return _registry.get_tracker(session_id)


def set_storage_dir(path: Path | str) -> None:
    """设置全局存储目录 — 模块级便捷函数"""
    _registry.set_storage_dir(path)


def clear_tracker_cache(session_id: str | None = None) -> None:
    """清空 tracker 缓存 — 模块级便捷函数

    Args:
        session_id: 指定 session 时仅清空该 session，None 时清空全部
    """
    if session_id is None:
        _registry.clear_all()
    else:
        _registry.remove_tracker(session_id)


__all__ = [
    "FileContextTracker",
    "FileContextEntry",
    "get_tracker",
    "set_storage_dir",
    "clear_tracker_cache",
    "OP_READ",
    "OP_EDITED",
    "OP_CREATED",
    "OP_DELETED",
    "VALID_OPERATIONS",
]
