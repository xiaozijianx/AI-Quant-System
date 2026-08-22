# -*- coding: utf-8 -*-
"""检查点管理器 — 对标 Cline checkpoint 机制

在工具执行前保存会话快照，支持回滚到工具执行前的状态。

设计要点:
    - 检查点按 session_id 组织，每个 session 维护一个检查点列表
    - 仅对写操作（requires_approval=True 的工具）保存检查点
    - 检查点存储在内存 + 本地 JSON 文件（与会话持久化一致）
    - 每个检查点保存完整的消息列表快照
    - 回滚时恢复消息列表并清除该检查点之后的所有检查点

工作流程:
    1. before_tool 钩子在写工具执行前调用 save_checkpoint()
    2. 检查点保存当前会话消息列表的深拷贝
    3. 用户通过 /api/chat/rollback 端点请求回滚
    4. rollback_to_checkpoint() 恢复消息列表
    5. runtime 用恢复后的消息列表继续运行

对标 Cline:
    - checkpoint 机制: 在每个工具执行前保存状态快照
    - rollback: 恢复到指定检查点，丢弃后续操作
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """检查点 — 对标 Cline checkpoint

    Attributes:
        checkpoint_id: 检查点唯一 ID
        session_id: 所属会话 ID
        tool_call_id: 触发检查点的工具调用 ID
        tool_name: 工具名称
        created_at: 创建时间
        messages: 会话消息列表的深拷贝快照
        description: 检查点描述
    """
    checkpoint_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    created_at: str
    messages: list[dict[str, Any]]
    description: str = ""


class CheckpointManager:
    """检查点管理器 — 对标 Cline checkpoint manager

    管理会话检查点的创建、查询、回滚和清理。
    检查点同时存储在内存和本地文件中，重启后可恢复。

    用法:
        manager = CheckpointManager(persist_dir=Path("data/checkpoints"))
        # 工具执行前保存检查点
        cp_id = manager.save_checkpoint(
            session_id="sess_001",
            tool_call_id="call_001",
            tool_name="file_write",
            messages=serialized_messages,
            description="写入 config.yaml 前",
        )
        # 用户请求回滚
        manager.rollback_to_checkpoint("sess_001", cp_id)
        checkpoint = manager.get_checkpoint(cp_id)
        restored_messages = checkpoint.messages
    """

    # 单个 session 最多保留的检查点数量
    _MAX_CHECKPOINTS_PER_SESSION = 20

    def __init__(self, persist_dir: Path | str | None = None) -> None:
        """初始化检查点管理器

        Args:
            persist_dir: 持久化目录，默认 agent_data/checkpoints
        """
        if persist_dir is None:
            project_root = Path(__file__).resolve().parent.parent
            persist_dir = project_root / "agent_data" / "checkpoints"
        self._persist_dir = Path(persist_dir)
        self._ensure_persist_dir()
        # 内存缓存: checkpoint_id -> Checkpoint
        self._checkpoints: dict[str, Checkpoint] = {}
        # session_id -> [checkpoint_id, ...]（按创建顺序）
        self._session_index: dict[str, list[str]] = {}

    def _ensure_persist_dir(self) -> None:
        """确保持久化目录存在"""
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def _checkpoint_file_path(self, checkpoint_id: str) -> Path:
        """获取检查点持久化文件路径

        防止路径遍历：只使用 checkpoint_id 的文件名部分
        """
        safe_name = os.path.basename(checkpoint_id)
        return self._persist_dir / f"{safe_name}.json"

    def _atomic_write_json(self, path: Path, data: Any) -> None:
        """原子写入 JSON 文件 — 对标 Cline atomicWriteJson"""
        import json
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def _persist_checkpoint(self, cp: Checkpoint) -> None:
        """持久化单个检查点到磁盘"""
        import dataclasses
        data = dataclasses.asdict(cp)
        path = self._checkpoint_file_path(cp.checkpoint_id)
        try:
            self._atomic_write_json(path, data)
        except Exception as e:
            logger.error(f"持久化检查点 {cp.checkpoint_id} 失败: {e}", exc_info=True)

    def _remove_persisted_checkpoint(self, checkpoint_id: str) -> None:
        """删除持久化的检查点文件"""
        path = self._checkpoint_file_path(checkpoint_id)
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning(f"删除检查点文件 {path} 失败: {e}")

    def save_checkpoint(
        self,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        messages: list[dict[str, Any]],
        description: str = "",
    ) -> str:
        """保存检查点 — 对标 Cline saveCheckpoint

        Args:
            session_id: 会话 ID
            tool_call_id: 工具调用 ID
            tool_name: 工具名
            messages: 当前消息列表的序列化形式（list[dict]）
            description: 检查点描述

        Returns:
            检查点 ID
        """
        checkpoint_id = f"cp_{uuid4().hex[:12]}"
        cp = Checkpoint(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            created_at=datetime.now().isoformat(),
            messages=messages,
            description=description,
        )

        self._checkpoints[checkpoint_id] = cp
        self._session_index.setdefault(session_id, []).append(checkpoint_id)
        self._persist_checkpoint(cp)

        # 超过单 session 上限时清理最旧的
        self._evict_if_needed(session_id)

        logger.info(
            f"CheckpointManager: 已保存检查点 {checkpoint_id} "
            f"(session={session_id}, tool={tool_name}, messages={len(messages)})"
        )
        return checkpoint_id

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """获取单个检查点"""
        return self._checkpoints.get(checkpoint_id)

    def list_checkpoints(self, session_id: str) -> list[str]:
        """列出会话的所有检查点 ID（按创建顺序）"""
        return list(self._session_index.get(session_id, []))

    def rollback_to_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str,
    ) -> bool:
        """回滚到指定检查点 — 对标 Cline rollbackToCheckpoint

        回滚后清除该检查点之后的所有检查点。

        Args:
            session_id: 会话 ID
            checkpoint_id: 检查点 ID

        Returns:
            是否回滚成功
        """
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None or cp.session_id != session_id:
            logger.warning(
                f"CheckpointManager: 检查点 {checkpoint_id} 不存在或会话不匹配"
            )
            return False

        # 清除该检查点之后的所有检查点
        cp_ids = self._session_index.get(session_id, [])
        if checkpoint_id in cp_ids:
            idx = cp_ids.index(checkpoint_id)
            to_remove = cp_ids[idx + 1:]
            for cid in to_remove:
                self._checkpoints.pop(cid, None)
                self._remove_persisted_checkpoint(cid)
            self._session_index[session_id] = cp_ids[: idx + 1]

        logger.info(
            f"CheckpointManager: 已回滚到检查点 {checkpoint_id} "
            f"(session={session_id}, 剩余检查点={len(self._session_index.get(session_id, []))})"
        )
        return True

    def restore_messages_only(
        self,
        checkpoint_id: str,
    ) -> list[dict[str, Any]] | None:
        """仅回滚消息历史，不回滚文件变更 — 对标 Cline message-only rollback

        对标 Cline ClineCheckpointRestore = "task" 模式:
            只恢复 messages 历史，不调用 applyCheckpointToWorktree（不执行 git stash/restore）。

        与 rollback_to_checkpoint 的区别:
            - 不删除任何 checkpoint（包括目标 checkpoint 之后的）
            - 不触发文件回滚（git stash/restore）
            - 同一 checkpoint 可被多次用于仅消息回滚

        Args:
            checkpoint_id: 检查点 ID

        Returns:
            被恢复的消息列表（深拷贝，list[dict] 形式），检查点不存在时返回 None
        """
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            logger.warning(
                f"CheckpointManager: 检查点 {checkpoint_id} 不存在（仅消息回滚）"
            )
            return None

        # 深拷贝消息列表，避免外部修改污染检查点快照
        import copy
        restored = copy.deepcopy(cp.messages)

        logger.info(
            f"CheckpointManager: 已仅消息回滚到检查点 {checkpoint_id} "
            f"(session={cp.session_id}, messages={len(restored)}, 保留所有检查点)"
        )
        return restored

    def get_diff(self, checkpoint_id: str) -> dict[str, Any] | None:
        """返回指定 checkpoint 与同 session 前一个 checkpoint 之间的消息差异 — P2-23 新增

        对标 Cline checkpoint diff 视图。将目标 checkpoint 的消息列表与
        同 session 中紧邻的前一个 checkpoint 做差集对比，返回新增/移除的消息。

        比较策略:
            - 优先用消息 id 做差集（id 相同视为同一条消息）
            - 消息 id 为 None/空时退化为 content 的 MD5 哈希做 key
              （避免 role+content 完全相同的消息被误判为同一条）

        典型场景:
            checkpoint 按工具执行前保存，消息列表单调增长，
            因此 diff 通常表现为 added=新增消息、removed=空。

        Args:
            checkpoint_id: 目标检查点 ID

        Returns:
            diff 字典，包含:
                - checkpoint_id: 目标检查点 ID
                - session_id: 所属会话 ID
                - baseline_checkpoint_id: 基线检查点 ID（前一个，无则为 None）
                - target_created_at / baseline_created_at: 创建时间
                - tool_name / description: 目标检查点的工具名和描述
                - target_message_count / baseline_message_count: 消息数
                - added_count / removed_count: 差异数
                - added: 目标有但基线没有的消息列表
                - removed: 基线有但目标没有的消息列表
            检查点不存在时返回 None
        """
        import hashlib
        import json

        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            logger.warning(
                f"CheckpointManager: 检查点 {checkpoint_id} 不存在（get_diff）"
            )
            return None

        # 找到同 session 中紧邻的前一个 checkpoint 作为基线
        cp_ids = self._session_index.get(cp.session_id, [])
        baseline_cp: Checkpoint | None = None
        if checkpoint_id in cp_ids:
            idx = cp_ids.index(checkpoint_id)
            if idx > 0:
                baseline_cp = self._checkpoints.get(cp_ids[idx - 1])

        baseline_messages = baseline_cp.messages if baseline_cp else []
        target_messages = cp.messages

        def _msg_key(m: dict[str, Any]) -> str:
            """生成消息比较 key — 优先用 id，无 id 时用 content 哈希"""
            mid = m.get("id")
            if mid:
                return f"id:{mid}"
            # 无 id 时用 role + content 文本做哈希，避免完全相同的消息被误判
            content_text = json.dumps(
                m.get("content", []), ensure_ascii=False, sort_keys=True,
            )
            role = m.get("role", "")
            return f"hash:{hashlib.md5(f'{role}|{content_text}'.encode('utf-8')).hexdigest()}"

        baseline_keys = {_msg_key(m) for m in baseline_messages}
        target_keys = {_msg_key(m) for m in target_messages}

        added = [m for m in target_messages if _msg_key(m) not in baseline_keys]
        removed = [m for m in baseline_messages if _msg_key(m) not in target_keys]

        return {
            "checkpoint_id": checkpoint_id,
            "session_id": cp.session_id,
            "baseline_checkpoint_id": baseline_cp.checkpoint_id if baseline_cp else None,
            "target_created_at": cp.created_at,
            "baseline_created_at": baseline_cp.created_at if baseline_cp else None,
            "tool_name": cp.tool_name,
            "description": cp.description,
            "target_message_count": len(target_messages),
            "baseline_message_count": len(baseline_messages),
            "added_count": len(added),
            "removed_count": len(removed),
            "added": added,
            "removed": removed,
        }

    def clear_checkpoints(self, session_id: str) -> int:
        """清除会话的所有检查点

        Returns:
            清除的检查点数量
        """
        cp_ids = self._session_index.pop(session_id, [])
        count = 0
        for cp_id in cp_ids:
            self._checkpoints.pop(cp_id, None)
            self._remove_persisted_checkpoint(cp_id)
            count += 1
        if count > 0:
            logger.info(
                f"CheckpointManager: 已清除会话 {session_id} 的 {count} 个检查点"
            )
        return count

    def delete_by_tool_call_ids(
        self, session_id: str, tool_call_ids: set[str]
    ) -> int:
        """按工具调用 ID 删除该会话对应的消息检查点 — 仅删除匹配项，保留其余

        消息检查点按 tool_call_id 关联（对标 Cline）。上下文回滚时只应删除
        被回滚的提问及其后工具调用所触发的检查点，之前建立的检查点需保留，
        避免误删仍有效的检查点快照。

        Args:
            session_id: 会话 ID
            tool_call_ids: 需要删除的工具调用 ID 集合

        Returns:
            删除的检查点数量
        """
        cp_ids = self._session_index.get(session_id, [])
        removed: list[str] = []
        for cp_id in list(cp_ids):
            cp = self._checkpoints.get(cp_id)
            if cp is not None and cp.tool_call_id in tool_call_ids:
                removed.append(cp_id)
                self._checkpoints.pop(cp_id, None)
                self._remove_persisted_checkpoint(cp_id)
        if removed:
            removed_set = set(removed)
            self._session_index[session_id] = [
                cid for cid in cp_ids if cid not in removed_set
            ]
            logger.info(
                f"CheckpointManager: 已按 tool_call_id 删除会话 {session_id} "
                f"的 {len(removed)} 个检查点"
            )
        return len(removed)

    def _evict_if_needed(self, session_id: str) -> int:
        """清理最旧的检查点（超过上限时）"""
        cp_ids = self._session_index.get(session_id, [])
        if len(cp_ids) <= self._MAX_CHECKPOINTS_PER_SESSION:
            return 0

        to_evict = len(cp_ids) - self._MAX_CHECKPOINTS_PER_SESSION
        evicted = 0
        for _ in range(to_evict):
            if not cp_ids:
                break
            cp_id = cp_ids.pop(0)
            self._checkpoints.pop(cp_id, None)
            self._remove_persisted_checkpoint(cp_id)
            evicted += 1
        if evicted > 0:
            logger.info(
                f"CheckpointManager: 已清理会话 {session_id} 的 {evicted} 个旧检查点"
            )
        return evicted

    def load_all(self) -> int:
        """加载所有持久化的检查点 — 启动时调用

        Returns:
            成功加载的检查点数量
        """
        import json
        count = 0
        for path in self._persist_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cp = Checkpoint(**data)
                self._checkpoints[cp.checkpoint_id] = cp
                self._session_index.setdefault(cp.session_id, []).append(
                    cp.checkpoint_id
                )
                count += 1
            except Exception as e:
                logger.warning(f"加载检查点文件 {path} 失败: {e}")
        if count > 0:
            logger.info(f"CheckpointManager: 已从磁盘恢复 {count} 个检查点")
        return count


# ============================================================================
# 全局实例 — 单例模式
# ============================================================================

_global_manager: CheckpointManager | None = None


def get_checkpoint_manager() -> CheckpointManager:
    """获取全局 CheckpointManager 单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = CheckpointManager()
    return _global_manager


def init_checkpoint_manager(
    persist_dir: Path | str | None = None,
) -> CheckpointManager:
    """初始化全局 CheckpointManager — 服务启动时调用

    Args:
        persist_dir: 持久化目录，默认 agent_data/checkpoints

    Returns:
        初始化后的 CheckpointManager 实例
    """
    global _global_manager
    _global_manager = CheckpointManager(persist_dir=persist_dir)
    return _global_manager


# ============================================================================
# CheckpointHook — 集成到 AgentRuntime 的 hook
# ============================================================================

from agent.hooks import AgentHooks, BeforeToolContext, BeforeToolResult


class CheckpointHook(AgentHooks):
    """Checkpoint hook — 在写工具执行前自动保存检查点

    对标 Cline checkpoint hook：在 requires_approval=True 的工具执行前
    调用 CheckpointManager.save_checkpoint() 保存会话消息快照。

    用法:
        runtime.register_hooks(CheckpointHook(
            session_id="sess_001",
            session_manager=session_manager,
        ))
    """

    def __init__(
        self,
        session_id: str,
        session_manager: Any,
    ) -> None:
        """初始化 CheckpointHook

        Args:
            session_id: 会话 ID
            session_manager: SessionManager 实例，用于获取当前消息列表
        """
        super().__init__()
        self._session_id = session_id
        self._session_manager = session_manager
        # 注册 before_tool hook
        self.before_tool = self._before_tool_hook

    async def _before_tool_hook(
        self,
        ctx: BeforeToolContext,
    ) -> BeforeToolResult | None:
        """before_tool 钩子 — 写工具执行前保存检查点"""
        if ctx.tool is None:
            return None

        # 仅对 requires_approval=True 的工具保存检查点（即写操作）
        requires_approval = getattr(ctx.tool, "requires_approval", False)
        if not requires_approval:
            return None

        try:
            manager = get_checkpoint_manager()
            # 从 session_manager 获取当前消息列表并序列化为 dict
            messages = self._session_manager.get_messages(self._session_id)
            serialized = [_message_to_dict(m) for m in messages]

            manager.save_checkpoint(
                session_id=self._session_id,
                tool_call_id=ctx.tool_call.tool_call_id,
                tool_name=ctx.tool_call.tool_name,
                messages=serialized,
                description=f"before {ctx.tool_call.tool_name} tool",
            )
        except Exception as e:
            # 检查点保存失败不应阻塞工具执行
            logger.warning(f"CheckpointHook: 保存检查点失败: {e}", exc_info=True)

        return None


# ============================================================================
# 消息序列化辅助 — 从 session.py 借鉴（避免循环导入）
# ============================================================================


def _message_to_dict(msg: Any) -> dict[str, Any]:
    """将 AgentMessage 序列化为字典 — 用于检查点持久化

    复用 session.py 中的 _message_to_dict 逻辑，但为避免循环导入在此独立实现。
    """
    # 延迟导入以避免循环
    from agent.types import (
        ReasoningPart,
        TextPart,
        ToolCallPart,
        ToolResultPart,
    )

    content = []
    for part in getattr(msg, "content", []):
        if isinstance(part, TextPart):
            content.append({"type": "text", "text": part.text})
        elif isinstance(part, ReasoningPart):
            content.append({
                "type": "reasoning",
                "text": part.text,
                "redacted": part.redacted,
            })
        elif isinstance(part, ToolCallPart):
            content.append({
                "type": "tool-call",
                "tool_call_id": part.tool_call_id,
                "tool_name": part.tool_name,
                "input": part.input,
            })
        elif isinstance(part, ToolResultPart):
            content.append({
                "type": "tool-result",
                "tool_call_id": part.tool_call_id,
                "tool_name": part.tool_name,
                "output": part.output,
                "is_error": part.is_error,
            })
        else:
            content.append({"type": "unknown", "text": str(part)})

    return {
        "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
        "content": content,
        "id": getattr(msg, "id", None),
        "created_at": msg.created_at.isoformat() if getattr(msg, "created_at", None) else None,
    }
