# -*- coding: utf-8 -*-
"""工具审批管理 — 对标 Cline tool-approval.ts + auto-approve 机制

管理需要用户审批的工具调用请求，支持:
    1. 创建审批请求（runtime 调用）
    2. 设置审批结果（/api/chat/approve 端点调用）
    3. 查询审批结果（runtime 等待）
    4. 清除审批请求（超时或完成后）

设计要点:
    - 全局 _pending_approvals 字典: tool_call_id → 审批条目
    - 使用 asyncio.Event 挂起 runtime 协程，等待用户审批
    - 审批结果通过 /api/chat/approve 端点设置，唤醒等待的协程
    - 支持 300 秒超时自动拒绝（避免永久挂起）

工作流程:
    1. runtime._prepare_tool_execution 检查 tool.requires_approval
    2. 若需要审批且非 auto_approve，调用 request_approval 创建请求
    3. runtime emit approval_request 事件到前端
    4. runtime await event.wait() 挂起等待
    5. 前端显示 approve/deny 按钮
    6. 用户点击，前端 POST /api/chat/approve
    7. set_approval_result 设置结果并 set event
    8. runtime 被唤醒，读取结果决定是否继续执行工具

对标 Cline:
    - sdk/packages/core/src/runtime/tools/tool-approval.ts
    - sdk/packages/core/src/extensions/tools/presets.ts (auto-approve 配置)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# 审批超时时间（秒）— 对标 Cline 5 分钟超时
APPROVAL_TIMEOUT_SECONDS = 300.0


@dataclass
class ApprovalEntry:
    """审批请求条目 — 对标 Cline ToolApprovalRequest

    Attributes:
        tool_call_id: 工具调用 ID（唯一标识）
        tool_name: 工具名称
        input: 工具输入参数
        session_id: 会话 ID
        event: 用于挂起/唤醒的 asyncio.Event
        result: 审批结果（None=等待中, "approved"=批准, "denied"=拒绝）
        created_at: 创建时间戳
    """
    tool_call_id: str
    tool_name: str
    input: dict[str, Any]
    session_id: str = ""
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: str | None = None  # None / "approved" / "denied"
    created_at: float = field(default_factory=lambda: __import__("time").time())


# 全局待审批字典: tool_call_id → ApprovalEntry
_pending_approvals: dict[str, ApprovalEntry] = {}

# Stage 5.6 (U10): 会话级自动批准记忆 — 对标 Cline autoApprove 三层粒度中的会话级
# session_id → 该会话中已"始终允许"的工具名集合
# runtime 在 _request_tool_approval 入口检查此集合，命中则跳过用户审批
# 会话结束时应调用 clear_session_auto_approved 清空，避免内存泄漏
_session_auto_approved: dict[str, set[str]] = {}

# Stage 9.6 (U10): 全局持久化自动批准记忆 — 对标 Cline globalState 持久化
# 跨会话保留"始终允许此工具"的审批记忆，agent 重启后仍生效。
# 存储格式: agent_config/approval_memory.json
# {
#   "version": 1,
#   "tools": ["read_files", "search_codebase", ...],
#   "updated_at": "2026-07-26T10:00:00Z"
# }
# 查询优先级: 会话级记忆 > 全局持久化记忆 > 默认审批逻辑
_persistent_auto_approved: set[str] | None = None  # 懒加载
_persist_file_path: Path | None = None
_persist_lock = threading.Lock()


def _get_persist_file_path() -> Path:
    """获取持久化记忆文件路径 — Stage 9.6 新增

    默认路径为项目根目录下的 agent_config/approval_memory.json。
    """
    global _persist_file_path
    if _persist_file_path is not None:
        return _persist_file_path
    project_root = Path(__file__).resolve().parent.parent
    _persist_file_path = project_root / "agent_config" / "approval_memory.json"
    return _persist_file_path


def _load_persistent_memory() -> set[str]:
    """从磁盘加载持久化审批记忆 — Stage 9.6 新增

    使用懒加载模式：首次访问时读取 agent_config/approval_memory.json。
    文件不存在或格式错误时返回空 set，不影响系统启动。

    Returns:
        已持久化自动批准的工具名集合
    """
    global _persistent_auto_approved
    if _persistent_auto_approved is not None:
        return _persistent_auto_approved
    path = _get_persist_file_path()
    tools: set[str] = set()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name in data.get("tools", []):
                if isinstance(name, str) and name:
                    tools.add(name)
            logger.info(
                f"Stage 9.6: 已加载持久化审批记忆 ({len(tools)} 个工具): {path}"
            )
        except Exception as e:
            logger.warning(
                f"Stage 9.6: 加载持久化审批记忆失败 ({path}): {e}"
            )
    _persistent_auto_approved = tools
    return tools


def _save_persistent_memory(tools: set[str]) -> bool:
    """将持久化审批记忆写入磁盘 — Stage 9.6 新增

    采用 tmpfile + os.replace 原子写入模式，避免写入过程中崩溃导致数据损坏。
    使用 _persist_lock 保护并发写入。

    Args:
        tools: 待持久化的工具名集合

    Returns:
        是否写入成功
    """
    path = _get_persist_file_path()
    data = {
        "version": 1,
        "tools": sorted(tools),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _persist_lock:
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        logger.info(
            f"Stage 9.6: 持久化审批记忆已写入 ({len(tools)} 个工具): {path}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Stage 9.6: 写入持久化审批记忆失败 ({path}): {e}",
            exc_info=True,
        )
        return False


def mark_auto_approved(session_id: str, tool_name: str) -> None:
    """标记某工具在某会话中为"始终允许" — Stage 5.6 (U10) 新增

    用户在审批卡片勾选"始终允许此工具"后，由 /api/chat/approve 端点调用。
    后续该会话内对同一工具的调用将跳过用户审批。

    Stage 9.6 (U10) 增强: 同时写入全局持久化记忆，跨会话保留。
    用户重启 agent 后，"始终允许"语义仍然生效。

    Args:
        session_id: 会话 ID
        tool_name: 工具名
    """
    if not session_id or not tool_name:
        return
    # 会话级（内存）
    _session_auto_approved.setdefault(session_id, set()).add(tool_name)
    # 全局持久化（磁盘）— Stage 9.6 新增
    persistent = _load_persistent_memory()
    if tool_name not in persistent:
        persistent.add(tool_name)
        _save_persistent_memory(persistent)
    logger.info(
        f"自动批准已记录: session={session_id}, tool={tool_name} "
        f"(同时写入会话级 + 全局持久化)"
    )


def is_auto_approved(session_id: str, tool_name: str) -> bool:
    """检查某工具在某会话中是否已被标记为"始终允许" — Stage 5.6 (U10) 新增

    runtime._request_tool_approval 入口调用此函数，命中则直接返回 None 跳过审批。

    Stage 9.6 (U10) 增强: 查询优先级为 会话级记忆 > 全局持久化记忆。
    会话级记忆命中时直接返回；否则查询持久化记忆（跨会话保留）。

    Args:
        session_id: 会话 ID
        tool_name: 工具名

    Returns:
        True 表示此工具已被自动批准（会话级或持久化级）
    """
    if not session_id or not tool_name:
        return False
    # 会话级优先
    tools = _session_auto_approved.get(session_id)
    if tools and tool_name in tools:
        return True
    # 持久化兜底 — Stage 9.6 新增
    return tool_name in _load_persistent_memory()


def list_auto_approved(session_id: str) -> list[str]:
    """查询某会话中已自动批准的工具列表 — Stage 5.6 (U10) 新增

    供前端展示当前会话的自动批准工具列表。

    Args:
        session_id: 会话 ID

    Returns:
        已自动批准的工具名列表（按字母序）
    """
    tools = _session_auto_approved.get(session_id)
    if not tools:
        return []
    return sorted(tools)


def clear_session_auto_approved(session_id: str) -> int:
    """清空某会话的自动批准记忆 — Stage 5.6 (U10) 新增

    在会话结束/清理时调用，避免长期运行的服务内存累积。
    返回被清除的工具数。

    注意: 仅清空会话级记忆，不影响全局持久化记忆（跨会话保留语义）。

    Args:
        session_id: 会话 ID

    Returns:
        被清除的工具数量
    """
    tools = _session_auto_approved.pop(session_id, None)
    return len(tools) if tools else 0


# ============================================================================
# Stage 9.6 (U10): 持久化审批记忆管理 API — 对标 Cline globalState 管理
# ============================================================================


def list_persistent_auto_approved() -> list[str]:
    """列出所有持久化自动批准的工具 — Stage 9.6 新增

    供前端"审批记忆管理"页面展示。

    Returns:
        已持久化自动批准的工具名列表（按字母序）
    """
    return sorted(_load_persistent_memory())


def remove_persistent_auto_approved(tool_name: str) -> bool:
    """删除单个工具的持久化自动批准记忆 — Stage 9.6 新增

    用户在管理页面单条删除时调用。

    Args:
        tool_name: 工具名

    Returns:
        是否删除成功（工具不存在时返回 False）
    """
    if not tool_name:
        return False
    persistent = _load_persistent_memory()
    if tool_name not in persistent:
        return False
    persistent.discard(tool_name)
    return _save_persistent_memory(persistent)


def clear_persistent_auto_approved() -> int:
    """清空所有持久化自动批准记忆 — Stage 9.6 新增

    用户在管理页面"全部清空"时调用。

    Returns:
        被清除的工具数量
    """
    persistent = _load_persistent_memory()
    count = len(persistent)
    if count == 0:
        return 0
    persistent.clear()
    _save_persistent_memory(persistent)
    return count


def request_approval(
    tool_call_id: str,
    tool_name: str,
    input: dict[str, Any],
    session_id: str = "",
) -> ApprovalEntry:
    """创建审批请求 — Phase 19 新增

    在全局字典中注册审批条目，返回带 asyncio.Event 的条目。
    runtime 通过 await entry.event.wait() 挂起等待用户审批。

    Args:
        tool_call_id: 工具调用 ID
        tool_name: 工具名称
        input: 工具输入参数
        session_id: 会话 ID

    Returns:
        ApprovalEntry 实例，含 event 用于等待
    """
    entry = ApprovalEntry(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        input=input,
        session_id=session_id,
    )
    _pending_approvals[tool_call_id] = entry
    logger.info(f"创建审批请求: tool={tool_name}, tool_call_id={tool_call_id}")
    return entry


def set_approval_result(tool_call_id: str, result: str) -> bool:
    """设置审批结果并唤醒等待的协程 — Phase 19 新增

    由 /api/chat/approve 端点调用。

    Args:
        tool_call_id: 工具调用 ID
        result: 审批结果（"approved" 或 "denied"）

    Returns:
        是否设置成功（未找到对应请求则返回 False）
    """
    entry = _pending_approvals.get(tool_call_id)
    if entry is None:
        logger.warning(f"未找到审批请求: tool_call_id={tool_call_id}")
        return False

    if result not in ("approved", "denied"):
        logger.warning(f"无效的审批结果: {result}")
        return False

    entry.result = result
    entry.event.set()
    logger.info(f"审批结果已设置: tool={entry.tool_name}, result={result}")
    return True


def get_approval_result(tool_call_id: str) -> str | None:
    """获取审批结果 — Phase 19 新增

    Args:
        tool_call_id: 工具调用 ID

    Returns:
        审批结果（"approved" / "denied"），或 None（未找到或未决）
    """
    entry = _pending_approvals.get(tool_call_id)
    return entry.result if entry else None


def clear_approval(tool_call_id: str) -> None:
    """清除审批请求 — Phase 19 新增

    在审批完成（批准/拒绝/超时）后调用，从全局字典中移除。
    """
    _pending_approvals.pop(tool_call_id, None)


def get_pending_approval_meta(tool_call_id: str) -> dict[str, Any] | None:
    """获取待审批请求的元信息 — Stage 5.6 (U10) 新增

    供 /api/chat/approve 端点在审批完成后获取 tool_name 与 session_id，
    以便调用 mark_auto_approved 写入会话级记忆。

    Args:
        tool_call_id: 工具调用 ID

    Returns:
        含 tool_name / session_id 的字典；未找到返回 None
    """
    entry = _pending_approvals.get(tool_call_id)
    if entry is None:
        return None
    return {
        "tool_call_id": entry.tool_call_id,
        "tool_name": entry.tool_name,
        "session_id": entry.session_id,
    }


def list_pending_approvals(session_id: str | None = None) -> list[dict[str, Any]]:
    """列出待审批请求 — Phase 19 新增

    用于状态查询和调试。

    Args:
        session_id: 可选的会话 ID 过滤

    Returns:
        待审批请求列表，每项含 tool_call_id/tool_name/session_id/created_at
    """
    result: list[dict[str, Any]] = []
    for entry in _pending_approvals.values():
        if session_id is not None and entry.session_id != session_id:
            continue
        result.append({
            "tool_call_id": entry.tool_call_id,
            "tool_name": entry.tool_name,
            "session_id": entry.session_id,
            "created_at": entry.created_at,
            "result": entry.result,
        })
    return result


def cancel_pending_approvals_for_session(session_id: str) -> int:
    """取消指定会话的所有待审批请求 — Phase 19 新增

    在会话中止或清除时调用，避免孤儿审批请求。

    Args:
        session_id: 会话 ID

    Returns:
        取消的请求数量
    """
    to_cancel = [
        tool_call_id for tool_call_id, entry in _pending_approvals.items()
        if entry.session_id == session_id
    ]
    for tool_call_id in to_cancel:
        entry = _pending_approvals.get(tool_call_id)
        if entry is not None:
            entry.result = "denied"
            entry.event.set()
    return len(to_cancel)
