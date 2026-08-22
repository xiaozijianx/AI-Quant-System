# -*- coding: utf-8 -*-
"""外部连接器系统 — 对标 Cline connectors + dispatchConnectorHook

Connectors 是 AgentRuntime 与外部系统的桥接层:
    1. 监听 agent 事件（运行/工具/审批）
    2. 将事件派发到外部命令（shell）
    3. 支持授权决策（外部脚本可批准/拒绝工具调用）

设计要点:
    - 配置驱动: 通过 agent_config/connectors.yaml 配置外部命令
    - 异步派发: 不阻塞主流程，命令失败仅记录日志
    - JSON-RPC 风格: 事件 payload 通过 stdin 传给外部命令，stdout 解析为决策结果
    - 与 hooks 集成: ConnectorManager 提供 hooks 适配器

与 Cline 对比:
    Cline 的 connectors 是 Slack/Discord/Telegram 等聊天平台适配器，
    本系统是 AI 量化系统智能助手，无需集成聊天平台，
    因此将 connectors 简化为"外部命令派发器"，保留核心设计:
        - dispatchConnectorHook: 派发事件到 shell 命令
        - authorizeConnectorEvent: 调用外部命令做授权决策
        - ConnectorConfig: 连接器配置（命令 + 触发事件 + 启用状态）

典型用途:
    - 工具执行前调用外部脚本做安全审计（before_tool 事件）
    - 运行结束时发送通知到企业微信/钉钉（after_run 事件）
    - 工具审批时调用外部策略引擎自动决策（before_approval 事件）

对标 Cline:
    - apps/cli/src/connectors/hooks.ts: dispatchConnectorHook / authorizeConnectorEvent
    - apps/cli/src/connectors/base.ts: ConnectorBase 抽象类
    - apps/cli/src/connectors/types.ts: ConnectCommandDefinition
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent.hooks import (
    AfterRunContext,
    AfterToolContext,
    BeforeApprovalContext,
    BeforeApprovalResult,
    BeforeToolContext,
    RunLifecycleContext,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 默认连接器配置文件路径（相对于项目根目录）
_DEFAULT_CONNECTORS_CONFIG = "agent_config/connectors.yaml"

# 外部命令执行超时（秒）
_DEFAULT_COMMAND_TIMEOUT = 30

# 授权命令执行超时（秒）— 应较短，避免阻塞用户
_APPROVAL_COMMAND_TIMEOUT = 10


# ============================================================================
# 配置数据结构
# ============================================================================


@dataclass
class ConnectorConfig:
    """连接器配置 — 对标 Cline ConnectCommandDefinition

    Attributes:
        name: 连接器名称（唯一标识）
        command: 要执行的外部命令（shell 字符串）
        events: 监听的事件列表（如 ["run.started", "run.finished", "tool.started"]）
        enabled: 是否启用
        description: 描述
        timeout: 命令执行超时（秒）
        is_approval: 是否是授权连接器（用于 before_approval 事件，返回 allow/deny 决策）
    """
    name: str
    command: str
    events: list[str] = field(default_factory=list)
    enabled: bool = True
    description: str = ""
    timeout: int = _DEFAULT_COMMAND_TIMEOUT
    is_approval: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "events": self.events,
            "enabled": self.enabled,
            "description": self.description,
            "timeout": self.timeout,
            "is_approval": self.is_approval,
        }


# ============================================================================
# 事件 payload — 对标 Cline ConnectorHookEvent
# ============================================================================


@dataclass
class ConnectorEvent:
    """连接器事件 — 对标 Cline ConnectorHookEvent

    Attributes:
        connector: 连接器名称
        event: 事件类型（如 run.started / tool.finished）
        payload: 事件数据
        ts: 时间戳（ISO 8601）
    """
    connector: str
    event: str
    payload: dict[str, Any]
    ts: str

    def to_dict(self) -> dict:
        return {
            "connector": self.connector,
            "event": self.event,
            "payload": self.payload,
            "ts": self.ts,
        }


# ============================================================================
# ConnectorManager — 连接器注册表 + 事件派发
# ============================================================================


class ConnectorManager:
    """连接器管理器 — 对标 Cline connectors/registry.ts

    职责:
        1. 加载 connectors.yaml 配置
        2. 维护已注册的连接器
        3. 派发事件到匹配的连接器
        4. 调用授权连接器做决策

    用法:
        manager = get_connector_manager()
        manager.load_config()

        # 派发事件（异步，非阻塞）
        await manager.dispatch_event("tool.started", {
            "session_id": "xxx",
            "tool_name": "editor",
            "input": {...},
        })

        # 授权决策（同步等待结果）
        decision = await manager.authorize({
            "tool_name": "run_commands",
            "input": {"command": "rm -rf /"},
        })
        if decision["action"] == "deny":
            raise PermissionError("被连接器拒绝")
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        """初始化连接器管理器

        Args:
            config_path: 配置文件路径，默认 agent_config/connectors.yaml
        """
        if config_path is None:
            project_root = Path(__file__).resolve().parent.parent
            config_path = project_root / _DEFAULT_CONNECTORS_CONFIG
        self._config_path = Path(config_path)
        self._connectors: dict[str, ConnectorConfig] = {}
        self._loaded: bool = False

    def load_config(self) -> int:
        """加载配置文件 — 对标 Cline 加载 connectors 配置

        Returns:
            已启用的连接器数量
        """
        self._connectors.clear()
        if not self._config_path.exists():
            logger.info(f"连接器配置文件不存在: {self._config_path}，跳过加载")
            self._loaded = True
            return 0

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"加载连接器配置失败: {e}", exc_info=True)
            self._loaded = True
            return 0

        connectors_raw = data.get("connectors", []) or []
        enabled_count = 0
        for item in connectors_raw:
            try:
                cfg = ConnectorConfig(
                    name=item.get("name", "").strip(),
                    command=item.get("command", ""),
                    events=item.get("events", []) or [],
                    enabled=item.get("enabled", True),
                    description=item.get("description", ""),
                    timeout=item.get("timeout", _DEFAULT_COMMAND_TIMEOUT),
                    is_approval=item.get("is_approval", False),
                )
                if not cfg.name or not cfg.command:
                    logger.warning(f"连接器配置缺少 name 或 command，跳过: {item}")
                    continue
                self._connectors[cfg.name] = cfg
                if cfg.enabled:
                    enabled_count += 1
            except Exception as e:
                logger.warning(f"解析连接器配置失败: {e}: {item}")

        self._loaded = True
        logger.info(
            f"已加载 {len(self._connectors)} 个连接器（{enabled_count} 个启用）"
        )
        return enabled_count

    def list_connectors(self) -> list[ConnectorConfig]:
        """列出所有连接器"""
        return list(self._connectors.values())

    def get_connector(self, name: str) -> ConnectorConfig | None:
        """按名称获取连接器"""
        return self._connectors.get(name)

    def reload(self) -> int:
        """重新加载配置"""
        return self.load_config()

    async def dispatch_event(
        self,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        """派发事件到所有匹配的连接器 — 对标 Cline dispatchConnectorHook

        匹配规则: 连接器 enabled=True 且 events 包含该事件类型

        Args:
            event: 事件类型（如 run.started / tool.finished）
            payload: 事件数据
        """
        if not self._loaded:
            self.load_config()

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()

        # 找到所有匹配的连接器
        matching = [
            cfg for cfg in self._connectors.values()
            if cfg.enabled and not cfg.is_approval and event in cfg.events
        ]
        if not matching:
            return

        # 异步并发派发（不阻塞主流程）
        tasks = []
        for cfg in matching:
            connector_event = ConnectorEvent(
                connector=cfg.name,
                event=event,
                payload=payload,
                ts=ts,
            )
            tasks.append(self._run_command(cfg, connector_event))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for cfg, result in zip(matching, results):
            if isinstance(result, Exception):
                logger.warning(
                    f"连接器 {cfg.name} 派发事件 {event} 失败: {result}"
                )

    async def authorize(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """调用授权连接器做决策 — 对标 Cline authorizeConnectorEvent

        遍历所有 is_approval=True 且 enabled=True 的连接器，
        依次调用其命令，任一返回 deny 即拒绝。

        Args:
            payload: 授权请求数据（tool_name, input, session_id 等）

        Returns:
            决策结果 {"action": "allow" | "deny", "reason": "...", "connector": "..."}
        """
        if not self._loaded:
            self.load_config()

        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()

        approval_connectors = [
            cfg for cfg in self._connectors.values()
            if cfg.enabled and cfg.is_approval
        ]
        if not approval_connectors:
            return {"action": "allow"}

        for cfg in approval_connectors:
            connector_event = ConnectorEvent(
                connector=cfg.name,
                event="session.authorize",
                payload=payload,
                ts=ts,
            )
            try:
                result = await self._run_command(
                    cfg, connector_event, timeout=_APPROVAL_COMMAND_TIMEOUT
                )
                # 解析 stdout 作为决策结果
                decision = self._parse_approval_decision(result, cfg.name)
                if decision["action"] == "deny":
                    return decision
            except Exception as e:
                logger.warning(
                    f"授权连接器 {cfg.name} 执行失败: {e}，跳过"
                )
                continue

        return {"action": "allow"}

    async def _run_command(
        self,
        cfg: ConnectorConfig,
        event: ConnectorEvent,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """执行外部命令 — 对标 Cline runSubprocessEvent

        通过 stdin 传递事件 payload（JSON），收集 stdout/stderr/exit_code。

        Args:
            cfg: 连接器配置
            event: 连接器事件
            timeout: 超时覆盖（秒）

        Returns:
            {"exit_code": int, "stdout": str, "stderr": str, "parsed_json": Any}
        """
        timeout_val = timeout if timeout is not None else cfg.timeout
        payload_json = json.dumps(event.to_dict(), ensure_ascii=False)

        # 构建命令（在 Windows 上需 shell=True）
        # 使用 asyncio.create_subprocess_shell 以兼容 Windows
        try:
            proc = await asyncio.create_subprocess_shell(
                cfg.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )
        except Exception as e:
            logger.error(f"启动连接器命令失败 [{cfg.name}]: {e}")
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "parsed_json": None,
            }

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=payload_json.encode("utf-8")),
                timeout=timeout_val,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                f"连接器命令超时 [{cfg.name}] ({timeout_val}s)，已终止"
            )
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"timeout after {timeout_val}s",
                "parsed_json": None,
            }

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else -1

        # 尝试解析 stdout 为 JSON（用于授权连接器）
        parsed_json = None
        if stdout.strip():
            try:
                parsed_json = json.loads(stdout)
            except json.JSONDecodeError:
                pass

        if exit_code != 0:
            logger.warning(
                f"连接器命令退出码非零 [{cfg.name}]: code={exit_code}, "
                f"stderr={stderr.strip()[:200]}"
            )

        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "parsed_json": parsed_json,
        }

    def _parse_approval_decision(
        self,
        result: dict[str, Any],
        connector_name: str,
    ) -> dict[str, Any]:
        """解析授权命令的决策结果 — 对标 Cline ConnectorAuthorizationDecisionSchema

        期望 stdout 是 JSON: {"action": "allow" | "deny", "reason": "..."}
        非 JSON 或解析失败默认 allow（不阻塞）
        """
        parsed = result.get("parsed_json")
        if not isinstance(parsed, dict):
            return {"action": "allow", "connector": connector_name}

        action = parsed.get("action", "allow")
        if action not in ("allow", "deny"):
            action = "allow"
        return {
            "action": action,
            "reason": parsed.get("reason", ""),
            "message": parsed.get("message", ""),
            "connector": connector_name,
        }


# ============================================================================
# 单例管理
# ============================================================================

_connector_manager: ConnectorManager | None = None


def get_connector_manager() -> ConnectorManager:
    """获取全局 ConnectorManager 单例"""
    global _connector_manager
    if _connector_manager is None:
        _connector_manager = ConnectorManager()
        _connector_manager.load_config()
    return _connector_manager


# ============================================================================
# ConnectorHooks — 将 ConnectorManager 集成到 AgentRuntime 的钩子
# ============================================================================


class ConnectorHooks:
    """连接器钩子集合 — 通过 hooks 系统将 AgentRuntime 事件路由到外部命令

    用法:
        connector_hooks = ConnectorHooks(session_id="xxx")
        runtime.register_hooks(AgentHooks(
            before_run=connector_hooks.before_run,
            after_run=connector_hooks.after_run,
            before_tool=connector_hooks.before_tool,
            after_tool=connector_hooks.after_tool,
            before_approval=connector_hooks.before_approval,
        ))

    设计要点:
        - 每个会话独立的 ConnectorHooks 实例
        - 钩子是异步的（dispatch_event 内部用 asyncio.gather 并发派发）
        - before_approval 同步等待授权连接器决策
        - 钩子不修改 runtime 行为（除非授权连接器拒绝）
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._manager = get_connector_manager()

    async def before_run(self, ctx: RunLifecycleContext) -> None:
        """运行开始 — 派发 run.started 事件"""
        snap = ctx.snapshot
        await self._manager.dispatch_event(
            event="run.started",
            payload={
                "session_id": self._session_id,
                "run_id": snap.run_id,
                "agent_id": snap.agent_id,
                "agent_role": snap.agent_role,
                "conversation_id": snap.conversation_id,
            },
        )

    async def after_run(self, ctx: AfterRunContext) -> None:
        """运行结束 — 派发 run.finished 事件"""
        snap = ctx.snapshot
        result = ctx.result
        await self._manager.dispatch_event(
            event="run.finished",
            payload={
                "session_id": self._session_id,
                "run_id": snap.run_id,
                "status": result.status,
                "iterations": snap.iteration,
                "messages_count": len(result.messages),
                "error": str(result.error) if result.error else None,
            },
        )

    async def before_tool(self, ctx: BeforeToolContext) -> None:
        """工具执行前 — 派发 tool.started 事件"""
        snap = ctx.snapshot
        tool_call = ctx.tool_call
        tool = ctx.tool
        tool_name = tool.name if tool else tool_call.tool_name
        await self._manager.dispatch_event(
            event="tool.started",
            payload={
                "session_id": self._session_id,
                "run_id": snap.run_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call.tool_call_id,
                "input": _safe_serialize(ctx.input),
            },
        )

    async def after_tool(self, ctx: AfterToolContext) -> None:
        """工具执行后 — 派发 tool.finished 事件"""
        snap = ctx.snapshot
        tool_call = ctx.tool_call
        tool = ctx.tool
        tool_name = tool.name if tool else tool_call.tool_name
        result = ctx.result
        await self._manager.dispatch_event(
            event="tool.finished",
            payload={
                "session_id": self._session_id,
                "run_id": snap.run_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call.tool_call_id,
                "duration_ms": ctx.duration_ms,
                "is_error": result.is_error,
                "output": _safe_serialize(result.output),
            },
        )

    async def before_approval(self, ctx: BeforeApprovalContext) -> BeforeApprovalResult:
        """工具审批前 — 调用授权连接器做决策

        对标 Cline authorizeConnectorEvent，外部脚本可自动批准/拒绝工具调用。
        决策为 deny 时返回拒绝结果，否则返回 None（继续走默认审批流程）。
        """
        decision = await self._manager.authorize(
            payload={
                "session_id": self._session_id,
                "tool_name": ctx.tool_name,
                "tool_call_id": ctx.tool_call_id,
                "input": _safe_serialize(ctx.input),
            }
        )
        if decision.get("action") == "deny":
            return BeforeApprovalResult(
                decision="denied",
                reason=decision.get("reason") or f"被连接器 {decision.get('connector', '')} 拒绝",
            )
        if decision.get("action") == "allow" and decision.get("connector"):
            # 明确 allow 决策（来自真实连接器，非默认 allow）— 自动批准
            return BeforeApprovalResult(
                decision="approved",
                reason=f"被连接器 {decision['connector']} 自动批准",
            )
        return BeforeApprovalResult()


def _safe_serialize(value: Any, max_chars: int = 2000) -> Any:
    """安全序列化 — 确保值可 JSON 序列化，超长截断"""
    try:
        if isinstance(value, (str, int, float, bool, type(None))):
            if isinstance(value, str) and len(value) > max_chars:
                return value[:max_chars] + "...(截断)"
            return value
        if isinstance(value, dict):
            text = json.dumps(value, ensure_ascii=False, default=str)
            if len(text) > max_chars:
                return text[:max_chars] + "...(截断)"
            return json.loads(text)
        if isinstance(value, list):
            return [_safe_serialize(v, max_chars) for v in value[:50]]
        return str(value)[:max_chars]
    except Exception:
        return str(value)[:max_chars]
