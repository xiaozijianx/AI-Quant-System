# -*- coding: utf-8 -*-
"""事件追踪系统 — 对标 Cline telemetry

TelemetryService:
    集中管理事件追踪，支持多个 sink（适配器）并行上报。
    每个 sink 是独立的输出通道（日志、文件、远程端点）。

设计要点:
    - 单例模式: 全局只有一个 TelemetryService 实例
    - 多 sink 并行: 事件依次派发给所有已注册的 sink
    - 异步非阻塞: sink 写入失败不影响主流程
    - 上下文富化: 支持全局 metadata（版本、平台等）和会话级 identify

与 AgentRuntime 集成:
    通过 hooks 系统接入，无需侵入 runtime 主循环:
        - before_run: 记录 run_started 事件
        - after_run: 记录 run_finished / run_failed 事件
        - before_tool: 记录 tool_started 事件
        - after_tool: 记录 tool_finished 事件（含耗时、成功/失败）

事件类型:
    - run.started: 运行开始
    - run.finished: 运行完成
    - run.failed: 运行失败
    - turn.started: 轮次开始
    - turn.finished: 轮次完成
    - tool.started: 工具调用开始
    - tool.finished: 工具调用完成
    - model.requested: LLM 请求发出
    - model.responded: LLM 响应返回
    - approval.requested: 工具审批请求
    - approval.resolved: 工具审批结果

对标 Cline:
    - apps/cli/src/utils/telemetry.ts: getCliTelemetryService / captureCliExtensionActivated
    - @cline/core ITelemetryService: captureEvent / addAdapter / identifyAccount
    - 事件流: runtime hooks → TelemetryService.captureEvent → sinks
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ============================================================================
# Stage 5.8 (Z13): 隐私合规 — opt-out + PII 脱敏
# 对标 Cline global-settings.ts / OpenTelemetryProvider.ts / core-events.ts
# ============================================================================


# 错误消息最大长度 — 对标 Cline MAX_ERROR_MESSAGE_LENGTH = 500
_MAX_ERROR_MESSAGE_LENGTH = 500

# 通用属性字符串字段最大长度（扩展 _truncate_preview 为通用 sanitize）
_MAX_PROPERTY_STRING_LENGTH = 500

# Stage 5.8 (Z13): PII 脱敏正则 — 对标 Cline OpenTelemetryProvider.ts 的属性安全处理
# 注意：银行卡号正则需结合字段名判断，避免误伤时间戳毫秒数等长数字
# 顺序很关键：长模式（身份证 18 位）必须先于短模式（手机号 11 位）执行，
# 否则手机号正则会先吃掉身份证号中的 11 位连续数字子串，导致身份证整体无法被识别
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 身份证：18 位数字 + 末位 X/x（先匹配，避免被手机号正则误吃）
    (re.compile(r"\d{17}[\dXx]"), "[ID_CARD]"),
    # 手机号：1[3-9] + 9 位数字（中国大陆手机号）
    (re.compile(r"1[3-9]\d{9}"), "[PHONE]"),
    # 邮箱
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
]


def _redact_pii(text: str) -> str:
    """对文本中的 PII 信息脱敏 — Stage 5.8 (Z13) 新增

    对标 Cline OpenTelemetryProvider.ts L252-337 的属性展平安全处理。
    替换手机号、邮箱、身份证为占位符。

    Args:
        text: 待脱敏的文本

    Returns:
        脱敏后的文本
    """
    if not text:
        return text
    result = text
    for pattern, placeholder in _PII_PATTERNS:
        result = pattern.sub(placeholder, result)
    return result


def _read_telemetry_opt_out() -> bool:
    """读取 telemetry opt-out 配置 — Stage 5.8 (Z13) 新增

    对标 Cline global-settings.ts:42,155-177 的 telemetryOptOut 字段。
    优先级：环境变量 AGENT_TELEMETRY_OPT_OUT > 配置文件 agent_config/telemetry.yaml
    的 opt_out 字段 > 默认 False

    Returns:
        True 表示用户已 opt-out，应跳过非必需事件
    """
    # 1. 环境变量优先
    env_val = os.environ.get("AGENT_TELEMETRY_OPT_OUT", "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        return True
    if env_val in ("0", "false", "no", "off"):
        return False
    # 2. 配置文件 agent_config/telemetry.yaml
    try:
        config_path = Path("agent_config/telemetry.yaml")
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8")
            # 简单解析 opt_out: true/false 行（避免引入 PyYAML 依赖）
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if line.startswith("opt_out:"):
                    val = line.split(":", 1)[1].strip().lower()
                    return val in ("true", "yes", "1", "on")
    except Exception:
        pass
    # 3. 默认 False
    return False

from agent.hooks import (
    AfterRunContext,
    AfterToolContext,
    BeforeToolContext,
    RunLifecycleContext,
)
from agent.types import AgentRuntimeStateSnapshot, TelemetryEventType

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 持久化文件版本
_TELEMETRY_FILE_VERSION = 1

# 默认持久化目录（相对于项目根目录）
_DEFAULT_TELEMETRY_DIR = "agent_data/telemetry"

# 内存缓冲区最大事件数（防止无限增长）
_MAX_BUFFER_SIZE = 5000

# 单次写入文件最大事件数
_FLUSH_BATCH_SIZE = 200


# ============================================================================
# 事件数据结构
# ============================================================================


@dataclass
class TelemetryEvent:
    """遥测事件 — 对标 Cline TelemetryEvent

    Attributes:
        event: 事件类型（如 run.started / tool.finished）
        ts: 事件时间戳（ISO 8601 字符串）
        session_id: 会话 ID
        run_id: 运行 ID（同一次 AgentRuntime.run 调用共享）
        iteration: 轮次序号（可选）
        properties: 事件属性（具体数据，如工具名、耗时、错误信息等）
        event_id: 事件唯一 ID（用于去重和追踪）
        distinct_id: Stage 14.3 (Z3) 新增 — 关联标识符（UUID v4），
            用于关联同一逻辑流程的多个事件（如 run.started 和 run.finished
            共享同一 distinct_id）。调用方显式传入时复用，None 时自动生成。
            对标 Cline TelemetryEvent.distinctId。
    """
    event: str
    ts: str
    session_id: str = ""
    run_id: str = ""
    iteration: int | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    # Stage 14.3 (Z3): distinct_id 关联标识 — 对标 Cline distinctId
    # 默认 None，由 capture() 自动生成 UUID v4（保证每个事件都有唯一标识）；
    # 调用方可显式传入（如复用 run_id / tool_call_id）以关联多个事件
    distinct_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        """转为字典 — 用于序列化"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TelemetryEvent":
        """从字典构建 — 用于反序列化"""
        return cls(
            event=data.get("event", ""),
            ts=data.get("ts", ""),
            session_id=data.get("session_id", ""),
            run_id=data.get("run_id", ""),
            iteration=data.get("iteration"),
            properties=data.get("properties", {}),
            event_id=data.get("event_id", uuid.uuid4().hex[:16]),
            # Stage 14.3 (Z3): 反序列化时回填 distinct_id（兼容旧数据）
            distinct_id=data.get("distinct_id", str(uuid.uuid4())),
        )


# ============================================================================
# Sinks（适配器）— 对标 Cline TelemetryLoggerSink
# ============================================================================


class TelemetrySink:
    """遥测事件 sink 基类 — 对标 Cline TelemetryLoggerSink

    子类需实现 write(event) 方法。
    sink 应当是线程安全且非阻塞的，写入失败仅记录日志。

    Stage 8.6 (Z2) 增强: 新增 metric instrument 空方法（默认 no-op），
    为未来接入 OpenTelemetrySink（OTLP 上报）预留接口。
    对标 Cline OpenTelemetryAdapter.ts:60-80 的 recordCounter / recordHistogram / recordGauge。
    现有 LoggerSink / FileSink / MemorySink 不重写这些方法，自动继承 no-op 行为，
    不影响现有事件流。生产部署接入可观测性平台时，新增的 OpenTelemetrySink 重写
    这些方法即可对接 OTLP metric 通道。
    """

    name: str = "base"

    def write(self, event: TelemetryEvent) -> None:
        """写入事件 — 子类必须实现"""
        raise NotImplementedError

    def record_counter(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """计数器 metric — Stage 8.6 新增，对标 Cline recordCounter

        默认 no-op，由具体 sink（如未来的 OpenTelemetrySink）覆盖。
        用于累计型指标，如工具调用次数、token 用量、错误数。

        Args:
            name: metric 名称（如 "tool.calls" / "tokens.input"）
            value: 计数值（int 或 float）
            attributes: metric 属性（如 {"tool_name": "exec_tool"}）
        """
        pass

    def record_histogram(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """直方图 metric — Stage 8.6 新增，对标 Cline recordHistogram

        默认 no-op，由具体 sink（如未来的 OpenTelemetrySink）覆盖。
        用于分布型指标，如工具耗时分布、响应延迟分布。

        Args:
            name: metric 名称（如 "tool.duration_ms"）
            value: 测量值（int 或 float）
            attributes: metric 属性（如 {"tool_name": "exec_tool"}）
        """
        pass

    def record_gauge(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """仪表盘 metric — Stage 8.6 新增，对标 Cline recordGauge

        默认 no-op，由具体 sink（如未来的 OpenTelemetrySink）覆盖。
        用于瞬时值指标，如当前内存占用、活跃会话数、缓存命中率。

        Args:
            name: metric 名称（如 "sessions.active"）
            value: 当前值（int 或 float）
            attributes: metric 属性（如 {"instance": "prod-1"}）
        """
        pass

    def flush(self) -> None:
        """刷新缓冲区 — 默认无操作，有缓冲区的子类应重写"""
        pass

    def close(self) -> None:
        """关闭 sink — 释放资源"""
        pass


class LoggerSink(TelemetrySink):
    """日志 sink — 将事件写入 logger

    用途: 开发调试，将遥测事件打到标准日志输出
    """

    name = "logger"

    def __init__(self, log_level: int = logging.DEBUG) -> None:
        self._log_level = log_level

    def write(self, event: TelemetryEvent) -> None:
        try:
            logger.log(
                self._log_level,
                f"[telemetry] {event.event} session={event.session_id} "
                f"run={event.run_id} props={event.properties}",
            )
        except Exception:
            pass


class FileSink(TelemetrySink):
    """文件 sink — 将事件追加到 JSONL 文件（每行一个事件）

    用途: 持久化遥测事件，用于后续分析和审计

    设计:
        - 内存缓冲: 事件先存入 deque，达到阈值或定期 flush 到磁盘
        - 原子写入: 使用临时文件 + rename 避免写入过程中崩溃导致文件损坏
        - 滚动策略: 按日期分文件（telemetry_YYYYMMDD.jsonl）
    """

    name = "file"

    def __init__(
        self,
        persist_dir: str | Path,
        max_buffer_size: int = _MAX_BUFFER_SIZE,
        flush_batch_size: int = _FLUSH_BATCH_SIZE,
    ) -> None:
        """初始化文件 sink

        Args:
            persist_dir: 持久化目录
            max_buffer_size: 内存缓冲区最大事件数
            flush_batch_size: 单次写入文件最大事件数
        """
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._max_buffer_size = max_buffer_size
        self._flush_batch_size = flush_batch_size
        self._buffer: deque[TelemetryEvent] = deque(maxlen=max_buffer_size)
        self._lock = threading.Lock()
        self._current_date: str = ""

    def write(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._buffer.append(event)
            # 缓冲区达到批次阈值时自动 flush
            if len(self._buffer) >= self._flush_batch_size:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        """写入缓冲区中的所有事件到文件（调用方需持锁）

        Phase 25 修复: 原实现用 os.replace(tmp, file) 会覆盖主文件，
        导致每次 flush 丢失之前已写入的事件。改为直接以追加模式写入主文件，
        保证 JSONL 文件持续累积。os.replace 仅用于多进程场景的原子写，
        但本系统单进程，追加写更安全且符合 JSONL 日志语义。
        """
        if not self._buffer:
            return
        # 按日期分组写入
        events_by_date: dict[str, list[TelemetryEvent]] = {}
        while self._buffer:
            ev = self._buffer.popleft()
            date_str = ev.ts[:10] if ev.ts else datetime.now().strftime("%Y-%m-%d")
            events_by_date.setdefault(date_str, []).append(ev)

        for date_str, events in events_by_date.items():
            file_path = self._persist_dir / f"telemetry_{date_str.replace('-', '')}.jsonl"
            try:
                # 追加模式写入主文件 — 不破坏已有内容，符合 JSONL 日志语义
                # Stage 5.8 (Z13): 增加 default=str 防 circular reference / 非可序列化对象
                with open(file_path, "a", encoding="utf-8") as f:
                    for ev in events:
                        f.write(json.dumps(ev.to_dict(), ensure_ascii=False, default=str) + "\n")
            except Exception as e:
                logger.warning(f"FileSink 写入失败: {e}")
                # 写入失败的事件丢弃（避免无限重试）

    def close(self) -> None:
        self.flush()


class MemorySink(TelemetrySink):
    """内存 sink — 保留最近 N 个事件，供 API 查询

    用途: 前端实时查看最近事件，无需读文件
    """

    name = "memory"

    def __init__(self, capacity: int = 500) -> None:
        self._capacity = capacity
        self._events: deque[TelemetryEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def write(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)

    def get_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[TelemetryEvent]:
        """查询事件 — 支持按会话和类型过滤"""
        with self._lock:
            events = list(self._events)
        # 倒序（最新在前）
        events.reverse()
        result: list[TelemetryEvent] = []
        for ev in events:
            if session_id and ev.session_id != session_id:
                continue
            if event_type and ev.event != event_type:
                continue
            result.append(ev)
            if len(result) >= limit:
                break
        return result

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# ============================================================================
# TelemetryService — 对标 Cline ITelemetryService
# ============================================================================


class TelemetryService:
    """遥测服务 — 对标 Cline ITelemetryService

    单例服务，管理所有 sink，提供事件捕获接口。

    用法:
        service = get_telemetry_service()
        service.add_sink(FileSink(persist_dir="agent_data/telemetry"))
        service.capture("run.started", session_id="xxx", run_id="yyy",
                        properties={"agent_id": "..."})

    通过 hooks 系统集成到 AgentRuntime:
        runtime.register_hooks(AgentHooks(
            before_run=telemetry_hooks.before_run,
            after_run=telemetry_hooks.after_run,
            before_tool=telemetry_hooks.before_tool,
            after_tool=telemetry_hooks.after_tool,
        ))
    """

    def __init__(self) -> None:
        self._sinks: list[TelemetrySink] = []
        self._lock = threading.Lock()
        # 全局元数据（版本、平台等）— 对标 Cline metadata
        self._global_metadata: dict[str, Any] = {
            "cline_type": "python",
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
            "platform": os.name,
        }
        # 账户上下文 — 对标 Cline identifyAccount
        self._account: dict[str, Any] = {}
        # 内置 MemorySink（始终存在，供 API 查询）
        self._memory_sink = MemorySink(capacity=500)
        self._sinks.append(self._memory_sink)
        self._closed: bool = False
        # Stage 5.8 (Z13): opt-out 标志 — 对标 Cline telemetryOptOut
        self._opted_out: bool = _read_telemetry_opt_out()

    def add_sink(self, sink: TelemetrySink) -> None:
        """添加 sink — 对标 Cline addAdapter"""
        with self._lock:
            self._sinks.append(sink)

    def remove_sink(self, name: str) -> bool:
        """按名称移除 sink"""
        with self._lock:
            for i, sink in enumerate(self._sinks):
                if sink.name == name:
                    try:
                        sink.close()
                    except Exception:
                        pass
                    self._sinks.pop(i)
                    return True
            return False

    def list_sinks(self) -> list[dict[str, Any]]:
        """列出所有已注册的 sink"""
        with self._lock:
            return [{"name": s.name, "type": type(s).__name__} for s in self._sinks]

    def identify(self, account: dict[str, Any]) -> None:
        """设置账户上下文 — 对标 Cline identifyAccount

        后续所有事件都会携带账户信息（如 user_id、email）。
        """
        with self._lock:
            self._account.update(account)

    def capture(
        self,
        event: str,
        session_id: str = "",
        run_id: str = "",
        iteration: int | None = None,
        properties: dict[str, Any] | None = None,
        distinct_id: str | None = None,
    ) -> None:
        """捕获事件 — 对标 Cline captureEvent

        Stage 5.8 (Z13) 增强:
            - opt-out 时直接返回（对标 Cline OptedOutTelemetryService no-op）
            - 属性值经 _sanitize_value 处理：PII 脱敏 + 截断 + 循环引用检测

        Stage 14.3 (Z3) 增强:
            - 新增 distinct_id 参数，用于关联同一逻辑流程的多个事件。
              调用方显式传入时复用（如 run.started 和 run.finished 共享同一
              distinct_id），None 时由 TelemetryEvent 默认值自动生成 UUID v4。

        Args:
            event: 事件类型（如 run.started / tool.finished）— 可传 TelemetryEventType
                枚举常量或字符串字面量（向后兼容）
            session_id: 会话 ID
            run_id: 运行 ID
            iteration: 轮次序号
            properties: 事件属性
            distinct_id: 关联标识符（UUID v4），None 时自动生成
        """
        if self._closed:
            return
        # Stage 5.8 (Z13): opt-out 检查 — 对标 Cline isTelemetryOptedOutGlobally
        if self._opted_out:
            return
        self._dispatch_event(
            event, session_id, run_id, iteration, properties, distinct_id,
        )

    def capture_required(
        self,
        event: str,
        session_id: str = "",
        run_id: str = "",
        iteration: int | None = None,
        properties: dict[str, Any] | None = None,
        distinct_id: str | None = None,
    ) -> None:
        """捕获必需事件 — Stage 5.8 (Z13) 新增，对标 Cline captureRequired

        绕过 opt-out 检查，用于 opt-out 事件本身、必需的错误事件等。
        对标 Cline TelemetryService.ts:75-80 的 captureRequired 方法。

        Stage 14.3 (Z3) 增强:
            - 新增 distinct_id 参数，与 capture() 行为一致。

        Args:
            event: 事件类型 — 可传 TelemetryEventType 枚举常量或字符串字面量
            session_id: 会话 ID
            run_id: 运行 ID
            iteration: 轮次序号
            properties: 事件属性
            distinct_id: 关联标识符（UUID v4），None 时自动生成
        """
        if self._closed:
            return
        self._dispatch_event(
            event, session_id, run_id, iteration, properties, distinct_id,
        )

    def _dispatch_event(
        self,
        event: str,
        session_id: str,
        run_id: str,
        iteration: int | None,
        properties: dict[str, Any] | None,
        distinct_id: str | None,
    ) -> None:
        """内部事件派发 — Stage 5.8 (Z13) 抽取，供 capture / capture_required 复用

        Stage 14.3 (Z3) 增强: 接收 distinct_id 并填充到 TelemetryEvent，
        None 时由 TelemetryEvent 默认值自动生成 UUID v4。
        Stage 14.3 (Z4) 增强: 兼容 TelemetryEventType 枚举入参，Python 3.10 下
        str(Enum) 返回 'ClassName.MEMBER' 而非 value，故显式取 .value。
        """
        # 合并全局元数据 + 账户上下文 + 事件属性
        merged_props = {**self._global_metadata}
        if self._account:
            merged_props["account"] = self._account
        if properties:
            merged_props.update(properties)

        # Stage 5.8 (Z13): 属性安全处理 — PII 脱敏 + 截断 + 循环引用检测
        # 对标 Cline OpenTelemetryProvider.ts L252-337 的属性展平安全处理
        merged_props = _sanitize_value(merged_props)

        # Stage 14.3 (Z4): 枚举转字符串 — Python 3.10 str(Enum) 返回 'Class.MEMBER' 格式，
        # 必须显式取 .value 才能得到 "telemetry.opt_out" 这样的字符串值
        if isinstance(event, Enum):
            event_str = event.value
        else:
            event_str = str(event)

        # Stage 14.3 (Z3): 构造事件时填充 distinct_id
        # distinct_id 为 None 时，TelemetryEvent 默认值会生成 UUID v4
        event_kwargs: dict[str, Any] = {
            "event": event_str,
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "run_id": run_id,
            "iteration": iteration,
            "properties": merged_props,
        }
        if distinct_id is not None:
            event_kwargs["distinct_id"] = distinct_id

        ev = TelemetryEvent(**event_kwargs)

        # 派发给所有 sink（非阻塞，sink 内部应处理异常）
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.write(ev)
            except Exception as e:
                logger.warning(f"TelemetrySink {sink.name} 写入失败: {e}")

    def is_opted_out(self) -> bool:
        """查询当前 opt-out 状态 — Stage 5.8 (Z13) 新增

        对标 Cline isTelemetryOptedOutGlobally。

        Returns:
            True 表示已 opt-out
        """
        return self._opted_out

    # ========================================================================
    # Metric instrument 派发 — Stage 8.6 (Z2) 新增
    # ========================================================================
    # 对标 Cline OpenTelemetryAdapter.ts:60-80 的 recordCounter / recordHistogram / recordGauge
    # 遍历所有 sink 调用对应 metric 方法。现有 LoggerSink / FileSink / MemorySink
    # 未重写这些方法，自动继承 TelemetrySink 的 no-op 行为，不影响现有事件流。
    # 生产部署接入可观测性平台时，新增 OpenTelemetrySink 重写这些方法即可对接 OTLP。

    def record_counter(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """计数器 metric 派发 — Stage 8.6 新增，对标 Cline recordCounter

        opt-out 时直接返回（与 capture 行为一致）。

        Args:
            name: metric 名称（如 "tool.calls"）
            value: 计数值
            attributes: metric 属性
        """
        if self._closed or self._opted_out:
            return
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.record_counter(name, value, attributes)
            except Exception as e:
                logger.warning(f"TelemetrySink {sink.name} record_counter 失败: {e}")

    def record_histogram(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """直方图 metric 派发 — Stage 8.6 新增，对标 Cline recordHistogram

        opt-out 时直接返回（与 capture 行为一致）。

        Args:
            name: metric 名称（如 "tool.duration_ms"）
            value: 测量值
            attributes: metric 属性
        """
        if self._closed or self._opted_out:
            return
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.record_histogram(name, value, attributes)
            except Exception as e:
                logger.warning(f"TelemetrySink {sink.name} record_histogram 失败: {e}")

    def record_gauge(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """仪表盘 metric 派发 — Stage 8.6 新增，对标 Cline recordGauge

        opt-out 时直接返回（与 capture 行为一致）。

        Args:
            name: metric 名称（如 "sessions.active"）
            value: 当前值
            attributes: metric 属性
        """
        if self._closed or self._opted_out:
            return
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.record_gauge(name, value, attributes)
            except Exception as e:
                logger.warning(f"TelemetrySink {sink.name} record_gauge 失败: {e}")

    def set_opt_out(self, value: bool) -> None:
        """运行时切换 opt-out 状态 — Stage 5.8 (Z13) 新增

        对标 Cline setTelemetryOptOutGlobally。切换为 True 时，
        调用 capture_required 记录 opt-out 事件本身（必需事件，绕过 opt-out）。

        Args:
            value: True 启用 opt-out，False 关闭
        """
        old = self._opted_out
        self._opted_out = bool(value)
        if self._opted_out and not old:
            # 记录 opt-out 事件本身 — 对标 Cline captureTelemetryOptOut
            # Stage 14.3 (Z4): 用枚举常量替代字符串字面量
            self.capture_required(
                event=TelemetryEventType.TELEMETRY_OPT_OUT,
                properties={"reason": "user_request"},
            )
            logger.info("Telemetry opt-out 已启用（运行时切换）")
        elif not self._opted_out and old:
            logger.info("Telemetry opt-out 已关闭（运行时切换）")

    def query_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查询最近事件 — 通过 MemorySink 提供"""
        events = self._memory_sink.get_events(
            session_id=session_id, event_type=event_type, limit=limit
        )
        return [ev.to_dict() for ev in events]

    def flush(self) -> None:
        """刷新所有 sink 的缓冲区"""
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.flush()
            except Exception as e:
                logger.warning(f"TelemetrySink {sink.name} flush 失败: {e}")

    def close(self) -> None:
        """关闭服务 — 释放所有 sink 资源"""
        if self._closed:
            return
        self._closed = True
        self.flush()
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.close()
            except Exception as e:
                logger.warning(f"TelemetrySink {sink.name} close 失败: {e}")


# ============================================================================
# 单例管理 — 对标 Cline telemetrySingleton
# ============================================================================

_telemetry_service: TelemetryService | None = None
_singleton_lock = threading.Lock()

# 持久化目录（默认 agent_data/telemetry，可通过 set_telemetry_dir 修改）
_telemetry_persist_dir: Path = (
    Path(__file__).resolve().parent.parent / _DEFAULT_TELEMETRY_DIR
)


def set_telemetry_dir(path: str | Path) -> None:
    """设置遥测持久化目录 — 应在服务启动前调用"""
    global _telemetry_persist_dir
    _telemetry_persist_dir = Path(path)
    _telemetry_persist_dir.mkdir(parents=True, exist_ok=True)


def get_telemetry_service() -> TelemetryService:
    """获取全局 TelemetryService 单例 — 对标 Cline getCliTelemetryService"""
    global _telemetry_service
    if _telemetry_service is None:
        with _singleton_lock:
            if _telemetry_service is None:
                service = TelemetryService()
                # 默认添加 LoggerSink 和 FileSink
                service.add_sink(LoggerSink())
                try:
                    service.add_sink(FileSink(persist_dir=_telemetry_persist_dir))
                except Exception as e:
                    logger.warning(f"FileSink 初始化失败: {e}")
                _telemetry_service = service
                logger.info(
                    f"TelemetryService 已初始化, persist_dir={_telemetry_persist_dir}"
                )
    return _telemetry_service


def dispose_telemetry_service() -> None:
    """关闭并释放 TelemetryService — 对标 Cline disposeCliTelemetryService"""
    global _telemetry_service
    with _singleton_lock:
        if _telemetry_service is not None:
            _telemetry_service.close()
            _telemetry_service = None


# ============================================================================
# TelemetryHooks — 将 TelemetryService 集成到 AgentRuntime 的钩子
# ============================================================================


class TelemetryHooks:
    """遥测钩子集合 — 通过 hooks 系统将 AgentRuntime 事件路由到 TelemetryService

    用法:
        telemetry_hooks = TelemetryHooks(session_id="xxx")
        runtime.register_hooks(AgentHooks(
            before_run=telemetry_hooks.before_run,
            after_run=telemetry_hooks.after_run,
            before_tool=telemetry_hooks.before_tool,
            after_tool=telemetry_hooks.after_tool,
        ))

    设计要点:
        - 每个会话独立的 TelemetryHooks 实例（携带 session_id）
        - 钩子方法是同步的（hooks 系统会自动包装异步调用）
        - 钩子不修改 runtime 行为，只记录事件
        - before_tool / after_tool 配对记录工具耗时
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._service = get_telemetry_service()
        # 记录正在执行的工具（tool_call_id → start_ts）
        self._tool_starts: dict[str, float] = {}
        # Stage 14.3 (Z3): 记录每次 run 的 distinct_id（run_id → distinct_id）
        # before_run 时生成，after_run 时复用，保证 run.started 和 run.finished
        # 共享同一 distinct_id，便于在 OTLP 后端按 distinct_id 关联
        self._run_distinct_ids: dict[str, str] = {}

    def before_run(self, ctx: RunLifecycleContext) -> None:
        """运行开始 — 记录 run.started 事件

        Stage 14.3 (Z3): 生成 distinct_id 并缓存，after_run 复用。
        """
        snap = ctx.snapshot
        run_id = snap.run_id or ""
        # 生成 distinct_id，与 after_run 共享
        distinct_id = str(uuid.uuid4())
        if run_id:
            self._run_distinct_ids[run_id] = distinct_id

        self._service.capture(
            event=TelemetryEventType.RUN_STARTED,
            session_id=self._session_id,
            run_id=run_id,
            properties={
                "agent_id": snap.agent_id,
                "agent_role": snap.agent_role,
                "conversation_id": snap.conversation_id,
                "parent_agent_id": snap.parent_agent_id,
                "max_iterations": getattr(snap, "max_iterations", None),
            },
            distinct_id=distinct_id,
        )

    def after_run(self, ctx: AfterRunContext) -> None:
        """运行结束 — 记录 run.finished 或 run.failed 事件

        Stage 14.3 (Z3): 复用 before_run 生成的 distinct_id。
        """
        snap = ctx.snapshot
        result = ctx.result
        run_id = snap.run_id or ""
        # 复用 before_run 生成的 distinct_id（若已缓存）
        distinct_id = self._run_distinct_ids.pop(run_id, None) or str(uuid.uuid4())

        # Stage 14.3 (Z4): 用枚举常量替代字符串字面量
        event_type = (
            TelemetryEventType.RUN_FAILED
            if result.status == "failed"
            else TelemetryEventType.RUN_FINISHED
        )
        properties: dict[str, Any] = {
            "status": result.status,
            "iterations": snap.iteration,
            "output_length": len(result.output_text) if result.output_text else 0,
            "messages_count": len(result.messages),
        }
        # 用量信息
        if result.usage:
            properties["usage"] = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.input_tokens + result.usage.output_tokens,
            }
        # 错误信息
        if result.error:
            properties["error"] = str(result.error)

        self._service.capture(
            event=event_type,
            session_id=self._session_id,
            run_id=run_id,
            iteration=snap.iteration,
            properties=properties,
            distinct_id=distinct_id,
        )

    def before_tool(self, ctx: BeforeToolContext) -> None:
        """工具执行开始 — 记录 tool.started 事件

        对标 Cline beforeTool 钩子，记录工具调用元信息。
        同时记录开始时间戳，供 after_tool 计算耗时。

        Stage 14.3 (Z3): 用 tool_call_id 作为 distinct_id，before_tool 和
        after_tool 共享，便于关联同一工具调用的两个事件。
        """
        snap = ctx.snapshot
        tool_call = ctx.tool_call
        tool = ctx.tool
        tool_name = tool.name if tool else tool_call.tool_name

        # 记录开始时间
        self._tool_starts[tool_call.tool_call_id] = time.time()

        self._service.capture(
            event=TelemetryEventType.TOOL_STARTED,
            session_id=self._session_id,
            run_id=snap.run_id or "",
            iteration=snap.iteration,
            properties={
                "tool_name": tool_name,
                "tool_call_id": tool_call.tool_call_id,
                "input_preview": _truncate_preview(ctx.input),
            },
            # Stage 14.3 (Z3): 工具调用前后共享 distinct_id
            distinct_id=tool_call.tool_call_id,
        )

    def after_tool(self, ctx: AfterToolContext) -> None:
        """工具执行完成 — 记录 tool.finished 事件

        对标 Cline afterTool 钩子，记录工具调用结果和耗时。

        Stage 14.3 (Z3): 复用 before_tool 的 distinct_id（tool_call_id）。
        """
        snap = ctx.snapshot
        tool_call = ctx.tool_call
        tool = ctx.tool
        tool_name = tool.name if tool else tool_call.tool_name
        result = ctx.result

        # 计算耗时
        start_ts = self._tool_starts.pop(tool_call.tool_call_id, None)
        duration_ms = ctx.duration_ms
        if start_ts is not None:
            duration_ms = int((time.time() - start_ts) * 1000)

        self._service.capture(
            event=TelemetryEventType.TOOL_FINISHED,
            session_id=self._session_id,
            run_id=snap.run_id or "",
            iteration=snap.iteration,
            properties={
                "tool_name": tool_name,
                "tool_call_id": tool_call.tool_call_id,
                "duration_ms": duration_ms,
                "is_error": result.is_error,
                "output_preview": _truncate_preview(result.output),
            },
            # Stage 14.3 (Z3): 复用 before_tool 的 distinct_id
            distinct_id=tool_call.tool_call_id,
        )


def _truncate_preview(value: Any, max_chars: int = 500) -> str:
    """截断预览值 — 防止事件过大"""
    try:
        if isinstance(value, str):
            text = value
        elif isinstance(value, dict):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
    except Exception:
        text = str(value)
    if len(text) > max_chars:
        return text[:max_chars] + "...(截断)"
    return text


def _sanitize_value(
    value: Any,
    max_chars: int = _MAX_PROPERTY_STRING_LENGTH,
    _seen: set[int] | None = None,
) -> Any:
    """通用属性安全处理 — Stage 5.8 (Z13) 新增

    对标 Cline OpenTelemetryProvider.ts L252-337 的属性展平安全处理：
        - 字符串：先 PII 脱敏，再截断到 max_chars
        - dict：递归 sanitize 每个值；检测循环引用
        - list：递归 sanitize 每个元素；检测循环引用
        - 其他：原值返回

    Args:
        value: 待处理的值
        max_chars: 字符串最大长度
        _seen: 内部使用的循环引用检测集合（递归传递）

    Returns:
        处理后的值（PII 已脱敏，长字符串已截断，循环引用已替换为 "[Circular]"）
    """
    if _seen is None:
        _seen = set()

    if isinstance(value, str):
        redacted = _redact_pii(value)
        if len(redacted) > max_chars:
            return redacted[:max_chars] + "...(截断)"
        return redacted

    if isinstance(value, dict):
        # 循环引用检测
        obj_id = id(value)
        if obj_id in _seen:
            return "[Circular]"
        _seen.add(obj_id)
        try:
            return {k: _sanitize_value(v, max_chars, _seen) for k, v in value.items()}
        finally:
            _seen.discard(obj_id)

    if isinstance(value, list):
        obj_id = id(value)
        if obj_id in _seen:
            return "[Circular]"
        _seen.add(obj_id)
        try:
            return [_sanitize_value(item, max_chars, _seen) for item in value]
        finally:
            _seen.discard(obj_id)

    return value


# ============================================================================
# 捕获辅助函数 — 对标 Cline captureExtensionActivated
# ============================================================================


_activated: bool = False
_activation_lock = threading.Lock()


def capture_service_activated(account: dict[str, Any] | None = None) -> None:
    """捕获服务激活事件 — 对标 Cline captureCliExtensionActivated

    服务启动时调用一次，记录启动时间和环境信息。
    多次调用安全（仅第一次实际发送事件）。
    """
    global _activated
    with _activation_lock:
        if _activated:
            return
        _activated = True
    service = get_telemetry_service()
    if account:
        service.identify(account)
    # Stage 5.8 (Z13): 服务激活事件是必需事件（用于统计活跃安装），
    # 不应被 opt-out 吞掉 — 对标 Cline captureRequired
    # Stage 14.3 (Z4): 用枚举常量替代字符串字面量
    service.capture_required(
        event=TelemetryEventType.SERVICE_ACTIVATED,
        properties={
            "startup_time": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        },
    )


# ============================================================================
# Stage 14.1 (Z2): OTLP HTTP Exporter — 对标 Cline OtlpHttpExporter
# 通过 HTTP POST 上报 metric 到 OTLP 兼容后端（Prometheus / Jaeger / Grafana）
# ============================================================================


class OtlpHttpExporter(TelemetrySink):
    """OTLP HTTP exporter — Stage 14.1 (Z2) 新增

    上报 metric 到 OTLP 兼容后端（如 OpenTelemetry Collector）。
    通过 HTTP POST 发送 OTLP JSON 格式数据，定期批量上报。

    设计要点:
        - 缓冲区用 asyncio.Lock 保护，线程安全
        - 定期 flush（默认 10 秒），避免频繁网络请求
        - 错误隔离: 上报失败仅 warning，不影响主流程
        - 不写 fallback: 网络不可达时数据丢失（用户需监控 exporter 健康）

    配置 (agent_config/telemetry.yaml):
        otlp:
          enabled: false  # 默认关闭，用户显式启用
          endpoint: "http://localhost:4318/v1/metrics"
          headers:
            Content-Type: "application/json"
          resource_attrs:
            service.name: "agent"
          batch_interval_seconds: 10.0
    """

    name = "otlp_http"

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        resource_attrs: dict[str, str] | None = None,
        batch_interval_seconds: float = 10.0,
    ) -> None:
        """初始化 OTLP HTTP exporter

        Args:
            endpoint: OTLP 接收端点 URL（如 http://localhost:4318/v1/metrics）
            headers: HTTP 请求头（如 Content-Type / Authorization）
            resource_attrs: 资源属性（如 service.name / service.version）
            batch_interval_seconds: 批量上报间隔（秒），默认 10
        """
        self._endpoint = endpoint
        self._headers = headers or {"Content-Type": "application/json"}
        self._resource_attrs = resource_attrs or {}
        self._batch_interval = batch_interval_seconds
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._flush_task: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def write(self, event: TelemetryEvent) -> None:
        """写入事件到缓冲区（TelemetrySink 接口实现）

        Stage 14.3 (Z3) 增强: 将 distinct_id 作为 attribute 写入 datapoint，
        便于在 Grafana 中按 distinct_id 过滤关联事件。
        """
        # 事件转为 metric datapoint 格式
        datapoint = {
            "name": f"agent.event.{event.event}",
            "gauge": {
                "dataPoints": [{
                    "attributes": [
                        {"key": "session_id", "value": {"stringValue": event.session_id}},
                        {"key": "run_id", "value": {"stringValue": event.run_id}},
                        # Stage 14.3 (Z3): distinct_id 作为关联标识 attribute
                        {"key": "distinct_id", "value": {"stringValue": event.distinct_id}},
                    ],
                    "value": {"intValue": 1},
                }],
            },
        }
        with self._lock:
            self._buffer.append(datapoint)

    def record_counter(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """计数器 metric — 缓冲到批量上报队列"""
        datapoint = self._build_metric_datapoint(name, value, attributes)
        with self._lock:
            self._buffer.append({
                "name": name,
                "sum": {"dataPoints": [datapoint], "aggregationTemporality": 2},
            })

    def record_histogram(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """直方图 metric — 缓冲到批量上报队列"""
        datapoint = self._build_metric_datapoint(name, value, attributes)
        with self._lock:
            self._buffer.append({
                "name": name,
                "histogram": {"dataPoints": [datapoint]},
            })

    def record_gauge(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """仪表盘 metric — 缓冲到批量上报队列"""
        datapoint = self._build_metric_datapoint(name, value, attributes)
        with self._lock:
            self._buffer.append({
                "name": name,
                "gauge": {"dataPoints": [datapoint]},
            })

    def _build_metric_datapoint(
        self,
        name: str,
        value: int | float,
        attributes: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """构建 OTLP metric datapoint"""
        attrs = []
        if attributes:
            for k, v in attributes.items():
                attrs.append({"key": str(k), "value": {"stringValue": str(v)}})
        return {
            "attributes": attrs,
            "value": {"doubleValue": float(value)},
        }

    def flush(self) -> None:
        """同步 flush — 触发异步上报"""
        if not self._buffer:
            return
        # 在事件循环中调度异步 flush
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_flush(), self._loop)
        else:
            # 无事件循环时同步执行（用于测试）
            try:
                asyncio.run(self._async_flush())
            except Exception as e:
                logger.warning(f"OTLP flush 失败: {e}")

    async def _async_flush(self) -> None:
        """异步批量上报缓冲区数据"""
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()

        payload = self._to_otlp_json(batch)
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._endpoint,
                    json=payload,
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"OTLP export 失败: HTTP {resp.status}, "
                            f"response={await resp.text()}"
                        )
        except Exception as e:
            logger.warning(f"OTLP export 错误: {e}")

    def _to_otlp_json(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        """转换为 OTLP JSON 格式 — 对标 Cline OtlpHttpExporter.toOtlpJson"""
        return {
            "resourceMetrics": [{
                "resource": {
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in self._resource_attrs.items()
                    ],
                },
                "scopeMetrics": [{
                    "scope": {"name": "agent", "version": "1.0.0"},
                    "metrics": batch,
                }],
            }],
        }

    async def start_flush_loop(self) -> None:
        """启动定期 flush 任务 — 应在事件循环中调用"""
        self._loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(self._batch_interval)
            await self._async_flush()

    def close(self) -> None:
        """关闭 exporter — flush 剩余数据"""
        self.flush()


# ============================================================================
# Stage 14.1 (Z2): TelemetryService 从 yaml 加载 OTLP exporter
# ============================================================================


def load_telemetry_from_yaml(config_path: Path | str) -> TelemetryService:
    """从 yaml 配置加载 TelemetryService — Stage 14.1 新增

    配置文件格式 (agent_config/telemetry.yaml):
        otlp:
          enabled: false
          endpoint: "http://localhost:4318/v1/metrics"
          headers:
            Content-Type: "application/json"
          resource_attrs:
            service.name: "agent"
          batch_interval_seconds: 10.0

    Args:
        config_path: yaml 配置文件路径

    Returns:
        TelemetryService 实例（已注册 OTLP sink 若 enabled=true）
    """
    import yaml

    service = get_telemetry_service()
    config_file = Path(config_path)
    if not config_file.exists():
        return service

    try:
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"加载 telemetry.yaml 失败: {e}")
        return service

    if not isinstance(config, dict):
        return service

    otlp_config = config.get("otlp", {})
    if not otlp_config.get("enabled", False):
        return service

    endpoint = otlp_config.get("endpoint", "")
    if not endpoint:
        logger.warning("OTLP 配置 enabled=true 但 endpoint 为空，跳过")
        return service

    exporter = OtlpHttpExporter(
        endpoint=endpoint,
        headers=otlp_config.get("headers"),
        resource_attrs=otlp_config.get("resource_attrs"),
        batch_interval_seconds=otlp_config.get("batch_interval_seconds", 10.0),
    )
    service.add_sink(exporter)
    logger.info(f"Stage 14.1: OTLP exporter 已加载, endpoint={endpoint}")

    return service
