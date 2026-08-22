# -*- coding: utf-8 -*-
"""记忆抽取层 — 对齐 Claude Code extractMemories.ts

在每次 query 循环结束（afterRun 钩子）时，用受限子 agent 从本轮新增的对话中抽取
值得长期记住的信息，写入记忆系统。

机制（对齐 extractMemories.ts）：
    1. 游标式：只处理自上次抽取以来新增的模型可见消息
    2. 受限子 agent 工具循环：只读工具 + save_memory 工具（仅写记忆目录）
    3. 主 agent 直写记忆时跳过（互斥）
    4. 每 N 轮节流（异步 fire-and-forget，不阻塞主循环）
    5. 抽取失败只记日志不报错（best-effort）

抽取模型：DeepSeek V4 Flash（memory._llm.create_memory_model）

对标 Claude Code:
    - src/services/extractMemories/extractMemories.ts
    - src/services/extractMemories/prompts.ts
    - src/tools/sub_agent.py（受限子 runtime 模式）
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent.memory import memory_manager as mm
from agent.memory._llm import create_memory_model
from agent.types import (
    AgentMessage,
    AgentModelFinishReason,
    AgentRunResult,
    AgentToolContext,
    AgentToolResult,
    MessageRole,
    ToolLifecycle,
)

logger = logging.getLogger(__name__)

# 抽取子 agent 最大迭代次数 — 对齐 Claude Code maxTurns: 5
_MAX_ITERATIONS = 5

# 记忆写入工具名（用于互斥检测）
_SAVE_MEMORY_TOOL = "save_memory"


# ============================================================================
# save_memory 工具 — 受限写工具，仅写记忆目录
# ============================================================================


class SaveMemoryTool:
    """记忆写入工具 — 仅供抽取子 agent 使用

    通过 memory_manager.save_memory 写记忆文件（自动处理 frontmatter + MEMORY.md 索引）。
    只允许写记忆目录，不提供任意文件写入能力。

    Args:
        memory_dir: 记忆目录
    """

    @property
    def name(self) -> str:
        return _SAVE_MEMORY_TOOL

    @property
    def description(self) -> str:
        return (
            "保存一条记忆到记忆系统。参数: filename(文件名，如 project_xxx.md); "
            "name(记忆名称); description(一句话描述); "
            "type(user/feedback/project/reference); "
            "tags(可选列表); content(正文内容，feedback/project 类型按事实+Why+How to apply 结构)"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "记忆文件名，用下划线命名，.md 结尾"},
                "name": {"type": "string", "description": "记忆名称"},
                "description": {"type": "string", "description": "一句话描述，用于未来判断相关性"},
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "记忆类型",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选标签，如 个股/概念/策略",
                },
                "content": {"type": "string", "description": "记忆正文内容"},
            },
            "required": ["filename", "name", "description", "type", "content"],
        }

    @property
    def lifecycle(self) -> ToolLifecycle:
        return ToolLifecycle(completes_run=False)

    @property
    def read_only(self) -> bool:
        return False

    def __init__(self, memory_dir: Path | str | None = None) -> None:
        self._memory_dir = memory_dir

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """保存一条记忆 — 调用 memory_manager.save_memory"""
        memory = mm.MemoryFile(
            filename=input.get("filename", ""),
            name=input.get("name", ""),
            description=input.get("description", ""),
            type=input.get("type", ""),
            tags=input.get("tags") or [],
            content=input.get("content", ""),
        )
        ok = mm.save_memory(memory, self._memory_dir)
        if not ok:
            return AgentToolResult(
                output={"error": "记忆保存失败（字段缺失或类型非法）"},
                is_error=True,
            )
        return AgentToolResult(
            output={
                "status": "saved",
                "filename": mm._normalize_filename(memory.filename),
            },
        )


# ============================================================================
# 抽取提示词 — 对齐 extractMemories.ts buildExtractAutoOnlyPrompt
# ============================================================================


def build_extract_system_prompt() -> str:
    """构建抽取子 agent 系统提示词（行为指令）"""
    return (
        "你是记忆抽取助手。从给定的最近对话中抽取值得长期记住的信息，"
        "用 save_memory 工具保存到记忆系统。\n\n"
        "记忆类型：\n"
        "- user: 交易者画像（风险偏好、资金管理习惯、股票池偏好、研究习惯）\n"
        "- feedback: 对研报/策略/计划的纠正或确认（写规则+Why+How to apply）\n"
        "- project: 投资决策上下文（对股票/板块/概念/策略的观点、决策及理由、持仓逻辑）\n"
        "- reference: 数据源/指标/工具用法\n\n"
        "不要保存：可从数据库/行情推导的市场数据（价格/财务数字/K线指标）、"
        "临时任务细节、已在规则/技能文档中说明的内容。\n\n"
        "如已有同类记忆，先更新而非新建重复。不要写重复记忆。\n"
        "若没有值得保存的信息，直接结束，不要调用工具。"
    )


def _format_messages(messages: list[AgentMessage]) -> str:
    """把消息列表格式化为可给抽取 agent 阅读的文本

    Args:
        messages: AgentMessage 列表

    Returns:
        格式化文本（仅 user/assistant 的文本内容）
    """
    parts: list[str] = []
    for m in messages:
        if m.role not in (MessageRole.USER, MessageRole.ASSISTANT):
            continue
        texts = []
        for p in m.content:
            from agent.types import TextPart

            if isinstance(p, TextPart) and p.text:
                texts.append(p.text)
        if texts:
            label = "用户" if m.role == MessageRole.USER else "助手"
            parts.append(f"[{label}]")
            parts.append("\n".join(texts))
    return "\n\n".join(parts)


def _build_extract_task(
    new_messages: list[AgentMessage],
    manifest: str,
) -> str:
    """构建抽取任务输入（现有记忆 + 最近对话）

    Args:
        new_messages: 本轮新增的消息
        manifest: 现有记忆 manifest 文本

    Returns:
        任务文本
    """
    lines = [
        "以下是现有记忆索引（了解已有记忆，避免重复）：",
        manifest if manifest else "（暂无记忆）",
        "",
        "以下是最近对话，请从中抽取值得长期记住的信息并保存：",
        "",
        _format_messages(new_messages),
        "",
        "请判断哪些值得保存，用 save_memory 保存。若没有，直接结束。",
    ]
    return "\n".join(lines)


# ============================================================================
# 受限子 agent 工具集构建
# ============================================================================


def _build_extract_tools(memory_dir: Path | str | None) -> list[Any]:
    """构建抽取子 agent 的受限工具集

    只读工具 + save_memory（仅写记忆目录），不提供任意文件写/命令执行。
    """
    from agent.tools.list_files import ListFilesTool
    from agent.tools.read_files import ReadFilesTool
    from agent.tools.search_codebase import SearchCodebaseTool

    working_dir = str(Path.cwd())
    tools: list[Any] = [
        ReadFilesTool(working_dir=working_dir),
        ListFilesTool(working_dir=working_dir),
        SearchCodebaseTool(working_dir=working_dir),
        SaveMemoryTool(memory_dir=memory_dir),
    ]
    return tools


# ============================================================================
# 游标辅助
# ============================================================================


def _new_messages_since(
    messages: list[AgentMessage],
    cursor_id: str | None,
) -> list[AgentMessage]:
    """返回游标之后的新增消息

    Args:
        messages: 完整消息历史
        cursor_id: 上次处理到的消息 id，None 表示全部

    Returns:
        新增消息列表
    """
    if not cursor_id:
        return messages
    found = False
    result: list[AgentMessage] = []
    for m in messages:
        if not found:
            if m.id == cursor_id:
                found = True
            continue
        result.append(m)
    # 游标未找到（如被压缩清理）时回退到全部
    if not found:
        return messages
    return result


def _has_memory_writes_since(
    messages: list[AgentMessage],
    cursor_id: str | None,
    memory_dir: Path | str | None = None,
) -> bool:
    """检测新增消息中是否有主 agent 直接写记忆（互斥用）— 对齐 extractMemories.ts hasMemoryWritesSince

    对齐 Claude Code：主 agent 的 system prompt 含完整保存指令，当它用写文件工具
    （file_write / editor）直接写入记忆目录时，后台抽取是冗余的，应跳过并推进游标，
    使主 agent 与后台抽取每轮互斥。

    Args:
        messages: 完整消息历史
        cursor_id: 游标 id
        memory_dir: 记忆目录，None 时用默认目录

    Returns:
        True 表示主 agent 已直接写记忆，抽取应跳过
    """
    new_msgs = _new_messages_since(messages, cursor_id)
    mem_path = mm.ensure_memory_dir_exists(memory_dir).resolve()
    for m in new_msgs:
        if m.role != MessageRole.ASSISTANT:
            continue
        for p in m.content:
            from agent.types import ToolCallPart

            if not isinstance(p, ToolCallPart):
                continue
            # 兼容：主 agent 若具备 save_memory 工具则视为直写
            if p.tool_name == _SAVE_MEMORY_TOOL:
                return True
            # 对齐 Claude Code isAutoMemPath：file_write/editor 写入记忆目录
            if p.tool_name in ("file_write", "editor"):
                target = p.input.get("file_path") or p.input.get("path")
                if target and str(Path(target).resolve()).startswith(str(mem_path)):
                    return True
    return False


# ============================================================================
# 抽取子 agent 执行
# ============================================================================


async def _run_extraction_agent(
    new_messages: list[AgentMessage],
    memory_dir: Path | str | None,
    manifest: str,
) -> tuple[bool, list[str]]:
    """运行受限抽取子 agent

    Args:
        new_messages: 本轮新增消息
        memory_dir: 记忆目录
        manifest: 现有记忆 manifest

    Returns:
        (是否成功, 实际写入的记忆文件相对路径列表)
    """
    from agent.providers.errors import ProviderError
    from agent.runtime import AgentRuntime, AgentRuntimeConfig

    try:
        model = create_memory_model()
    except Exception as e:
        logger.warning("memory_extract: 创建抽取模型失败: %s", e)
        return False, []

    # 构建受限工具集
    sub_tools = _build_extract_tools(memory_dir)

    # 创建子 runtime — 对标 SubAgentTool._execute
    sub_config = AgentRuntimeConfig(
        model=model,
        system_prompt=build_extract_system_prompt(),
        max_iterations=_MAX_ITERATIONS,
        agent_id=f"memory-extract-{__import__('uuid').uuid4().hex[:8]}",
        agent_role="subagent",
        session_id=None,
    )
    sub_runtime = AgentRuntime(config=sub_config)
    for tool in sub_tools:
        sub_runtime.register_tool(tool)

    task = _build_extract_task(new_messages, manifest)
    try:
        result: AgentRunResult = await sub_runtime.run(task)
    except Exception as e:
        logger.warning("memory_extract: 抽取子 agent 运行失败: %s", e)
        return False, []

    # 统计实际写入的记忆文件（从消息中提取 save_memory 工具调用）
    written: list[str] = []
    for m in result.messages:
        if m.role != MessageRole.ASSISTANT:
            continue
        for p in m.content:
            from agent.types import ToolCallPart

            if isinstance(p, ToolCallPart) and p.tool_name == _SAVE_MEMORY_TOOL:
                fn = p.input.get("filename", "")
                if fn:
                    written.append(mm._normalize_filename(fn))
    return True, written


# ============================================================================
# 抽取器 — 闭包作用域状态（游标/节流/互斥）
# ============================================================================


class MemoryExtractor:
    """记忆抽取器 — 对齐 extractMemories.ts 闭包作用域状态

    成员:
        enabled: 总开关（由外部配置）
        interval: 每 N 轮抽取一次（默认 1）
    """

    def __init__(self, enabled: bool = True, interval: int = 1) -> None:
        self.enabled = enabled
        self.interval = max(1, interval)
        # 闭包作用域状态
        self._cursor_id: str | None = None
        self._in_progress = False
        self._turns_since_last = 0
        self._pending: tuple[list[AgentMessage], Path | str | None] | None = None
        self._in_flight: set[asyncio.Task] = set()

    async def extract(self, result: AgentRunResult) -> None:
        """在 afterRun 钩子调用 — 处理本轮新增消息

        Args:
            result: AgentRunResult（含完整消息历史）
        """
        if not self.enabled:
            return
        messages = result.messages
        if not messages:
            return

        # 互斥：主 agent 已直接写记忆则跳过（对齐 extractMemories.ts hasMemoryWritesSince）
        if _has_memory_writes_since(messages, self._cursor_id, mm.get_memory_dir()):
            logger.debug("memory_extract: 主 agent 已直接写记忆，跳过抽取")
            last = messages[-1]
            if last.id:
                self._cursor_id = last.id
            return

        # 节流：每 N 轮抽取一次
        self._turns_since_last += 1
        if self._turns_since_last < self.interval:
            return
        self._turns_since_last = 0

        # 若已有抽取在跑，暂存上下文，结束后补跑
        if self._in_progress:
            self._pending = (messages, None)
            return

        new_messages = _new_messages_since(messages, self._cursor_id)
        if not new_messages:
            return

        self._in_progress = True
        try:
            memory_dir = mm.get_memory_dir()
            manifest = mm.format_memory_manifest(mm.scan_memory_files(memory_dir))
            ok, written = await _run_extraction_agent(new_messages, memory_dir, manifest)
            # 对齐 extractMemories.ts：仅抽取成功后推进游标，失败保持原游标，
            # 使这些消息在下一次抽取时被重新考虑（而非永久丢弃）。
            last = messages[-1]
            if last.id:
                self._cursor_id = last.id
            if ok and written:
                logger.debug("memory_extract: 保存 %d 条记忆: %s", len(written), written)
            else:
                logger.debug("memory_extract: 本轮未保存记忆")
        except Exception as e:
            logger.warning("memory_extract: 抽取异常: %s", e)
        finally:
            self._in_progress = False
            # 补跑暂存的上下文
            if self._pending is not None:
                pending_messages, _ = self._pending
                self._pending = None
                await self.extract(
                    AgentRunResult(messages=pending_messages)
                )

    def drain(self, timeout_ms: float = 60_000) -> None:
        """等待所有在途抽取任务完成（进程退出前调用）

        Args:
            timeout_ms: 超时毫秒
        """
        if not self._in_flight:
            return
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            pending = list(self._in_flight)
            try:
                loop.run_until_complete(
                    asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=timeout_ms / 1000,
                    )
                )
            except Exception:
                pass
        except RuntimeError:
            pass


# 全局抽取器实例（模块级单例）
_extractor: MemoryExtractor | None = None


def init_memory_extractor(enabled: bool = True, interval: int = 1) -> MemoryExtractor:
    """初始化全局抽取器 — 启动时调用一次

    Args:
        enabled: 总开关
        interval: 每 N 轮抽取一次

    Returns:
        抽取器实例
    """
    global _extractor
    _extractor = MemoryExtractor(enabled=enabled, interval=interval)
    return _extractor


def get_memory_extractor() -> MemoryExtractor | None:
    """获取全局抽取器实例

    Returns:
        抽取器实例；未初始化时返回 None
    """
    return _extractor


async def execute_extract_memories(result: AgentRunResult) -> None:
    """afterRun 钩子入口 — 对齐 extractMemories.ts executeExtractMemories

    Args:
        result: AgentRunResult
    """
    extractor = _extractor
    if extractor is None or not extractor.enabled:
        return
    task = asyncio.create_task(extractor.extract(result))
    extractor._in_flight.add(task)
    task.add_done_callback(extractor._in_flight.discard)