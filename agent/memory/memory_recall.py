# -*- coding: utf-8 -*-
"""记忆召回层 — 对齐 Claude Code findRelevantMemories.ts + loadMemoryPrompt

每次 query 构建 system prompt 时：
    1. 扫描记忆目录，生成 manifest（由 memory_manager 提供）
    2. 用 DeepSeek V4 Flash 选择器选出与 query 最相关的主题文件（≤5 个）
    3. 构建独立 memory section 注入 system prompt：
        - 行为指令（4 类记忆、何时访问、什么不存）— 对齐 memdir.ts buildMemoryPrompt
        - MEMORY.md 索引（始终注入，截断）
        - 召回的主题文件内容

4 类记忆语义（量化系统适配）：
    - user:     交易者画像
    - feedback: 对研报/策略/计划的纠正指令
    - project:  投资决策上下文（观点/策略决策及理由/持仓逻辑）
    - reference: 数据源/指标/工具用法

对标 Claude Code:
    - src/memdir/findRelevantMemories.ts
    - src/memdir/memdir.ts
    - src/memdir/memoryTypes.ts
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agent.memory import memory_manager as mm
from agent.memory._llm import complete_text, create_memory_model
from agent.memory.memory_age import memory_freshness_note

logger = logging.getLogger(__name__)

# 召回选择器提示词 — 对齐 Claude Code findRelevantMemories.ts SELECT_MEMORIES_SYSTEM_PROMPT
SELECT_MEMORIES_SYSTEM_PROMPT = (
    "You are selecting memories that will be useful to the AI trading assistant "
    "as it processes a user's query. You will be given the user's query and a list "
    "of available memory files with their filenames and descriptions.\n\n"
    "Return a JSON object with a key \"selected_memories\" that is a list of "
    "filenames for the memories that will clearly be useful (up to 5). "
    "Only include memories you are certain will be helpful based on name and description.\n"
    "- If unsure whether a memory will be useful, do not include it. Be selective and discerning.\n"
    "- If no memories would clearly be useful, return an empty list.\n"
    "- If a list of recently-used tools is provided, do not select memories that are usage "
    "reference or API documentation for those tools (the agent is already exercising them). "
    "DO still select memories containing warnings, gotchas, or known issues about those tools "
    "— active use is exactly when those matter.\n"
)


# ============================================================================
# 行为指令段 — 对齐 memoryTypes.ts，语义按量化系统适配
# ============================================================================

TYPES_SECTION = [
    "## 记忆类型",
    "",
    "记忆系统中有以下几类离散的记忆，你可以保存：",
    "",
    "- **user**（用户画像）：关于交易者的角色、目标、风险偏好、资金管理习惯、"
    "股票池偏好、研究习惯。好的 user 记忆能帮你针对这位交易者定制行为。",
    "",
    "- **feedback**（纠正/反馈）：用户给过的关于如何工作的指示——该避免什么、"
    "该坚持什么。既记录纠正（\"不要这样\"）也记录确认（\"对，就这样\"）。"
    "每条这样写：先写规则本身，再写 **Why:**（用户给的理由，常是过往事故或偏好）"
    "和 **How to apply:**（这条指导在何时/何地生效）。",
    "",
    "- **project**（投资决策上下文）：你对某只股票/板块/概念/策略的观点、"
    "策略决策及理由、已放弃的方案及原因、持仓决策逻辑。保存时把相对日期转成绝对日期，"
    "先写事实或决策，再写 **Why:** 和 **How to apply:**。",
    "",
    "- **reference**（参考/工具用法）：数据源、指标、工具的使用方式，"
    "如 xtdata 取数要点、交易计划 MD 格式、指标含义（如 vol_ratio_z 截面标准化）。",
    "",
]

WHAT_NOT_TO_SAVE_SECTION = [
    "## 什么不值得存进记忆",
    "",
    "- 可用数据库/行情推导的市场数据：价格、财务数字、K线指标、板块排名——"
    "这些在实时行情或数仓里都能查到，存进记忆会迅速过时并污染召回。",
    "- 当前会话的临时任务细节、进行中的工作、临时状态。",
    "- 已在规则文件/技能文档中说明的内容。",
    "",
]

WHEN_TO_ACCESS_SECTION = [
    "## 何时访问记忆",
    "",
    "- 当记忆似乎相关，或用户提到过往对话的工作时。",
    "- 用户明确要求你检查、回忆或记住时，必须访问记忆。",
    "- 记忆可能过时：把它当作\"过去某时刻的真相\"。回答前若记忆与现实冲突，"
    "以你现在观察到的为准，并更新或移除过时的记忆，而不是照旧使用。",
    "",
]


def build_memory_lines(display_name: str, memory_dir: Path) -> str:
    """构建行为指令段（不含 MEMORY.md 内容）— 对齐 memdir.ts buildMemoryLines

    Args:
        display_name: 记忆显示名
        memory_dir: 记忆目录

    Returns:
        行为指令文本
    """
    lines: list[str] = [
        f"# {display_name}",
        "",
        f"你有一个持久的、基于文件的记忆系统位于 `{memory_dir}`。"
        "你可以随时间构建这个记忆系统，让未来的对话对用户、协作方式、"
        "要避免或重复的行为、以及工作背后的背景有完整认知。",
        "",
        "如果用户明确要求你记住某件事，立即以最合适的类型保存。"
        "如果要求你忘记，找到并删除相关条目。",
        "",
        *TYPES_SECTION,
        *WHAT_NOT_TO_SAVE_SECTION,
        "## 如何保存记忆",
        "",
        "保存一条记忆分两步：",
        "",
        f"**Step 1** — 把记忆写入它自己的文件（如 `user_role.md`），使用 frontmatter 格式：",
        "",
        "```markdown",
        "---",
        "name: {{记忆名称}}",
        "description: {{一句话描述——用于未来判断相关性，要具体}}",
        "type: {{user, feedback, project, reference}}",
        "tags: [{{可选标签，如 个股/概念/策略}}]",
        "---",
        "",
        "{{记忆内容——feedback/project 类型按：事实/规则，然后 **Why:** 和 **How to apply:** 行}}",
        "```",
        "",
        f"**Step 2** — 在 `{mm.ENTRYPOINT_NAME}` 中添加指向该文件的指针。"
        f"`{mm.ENTRYPOINT_NAME}` 是索引，不是记忆本身——每行一个条目，"
        "约 150 字符以内：`- [标题](file.md) — 一句话钩子`。它没有 frontmatter。"
        "不要把记忆内容直接写进索引。",
        "",
        f"- `{mm.ENTRYPOINT_NAME}` 总是加载进你的上下文——超过 {mm.MAX_ENTRYPOINT_LINES} 行会被截断，"
        "所以保持索引简洁。",
        "- 保持记忆文件中的 name/description/type 字段与内容最新。",
        "- 按主题而非时间组织记忆。",
        "- 更新或移除错误/过时的记忆。",
        "- 不要写重复记忆。先检查是否有可更新的现有记忆，再写新的。",
        "",
        *WHEN_TO_ACCESS_SECTION,
        "",
    ]
    return "\n".join(lines)


def build_memory_prompt(memory_dir: Path, entrypoint_content: str) -> str:
    """构建包含 MEMORY.md 内容的完整记忆提示 — 对齐 memdir.ts buildMemoryPrompt

    Args:
        memory_dir: 记忆目录
        entrypoint_content: MEMORY.md 索引内容（已截断）

    Returns:
        完整记忆提示文本
    """
    lines = build_memory_lines("memory", memory_dir).splitlines()
    lines.append(f"## {mm.ENTRYPOINT_NAME}")
    lines.append("")
    if entrypoint_content.strip():
        lines.append(entrypoint_content)
    else:
        lines.append(f"你的 {mm.ENTRYPOINT_NAME} 目前为空。保存新记忆后，它们会出现在这里。")
    return "\n".join(lines)


# ============================================================================
# 召回选择 — 对齐 findRelevantMemories.ts
# ============================================================================


def _parse_selected_filenames(raw: str) -> list[str]:
    """解析选择器返回的 JSON，提取选中的文件名列表

    Args:
        raw: 模型返回的原始文本

    Returns:
        文件名列表；解析失败返回空列表
    """
    text = raw.strip()
    # 去掉可能的 markdown 代码围栏
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            selected = data.get("selected_memories")
            if isinstance(selected, list):
                return [str(s) for s in selected if isinstance(s, str)]
    except Exception as e:
        logger.debug("memory_recall: 解析选择结果失败: %s", e)
    return []


async def _select_relevant_memories(
    query: str,
    manifest: str,
    model: object,
    recent_tools: list[str] | None = None,
) -> list[str]:
    """用 DeepSeek V4 Flash 选择与 query 最相关的记忆文件 — 对齐 findRelevantMemories.ts

    Args:
        query: 用户查询
        manifest: 记忆文件 manifest 文本
        model: 记忆专用模型
        recent_tools: 最近用过的工具名列表，用于过滤"正在使用的工具的使用文档"，
                      避免把已在对话中使用的工具参考文档误召回（对齐 Claude Code toolsSection）

    Returns:
        选中的文件名列表
    """
    tools_section = (
        f"\n\nRecently used tools: {', '.join(recent_tools)}" if recent_tools else ""
    )
    user_prompt = (
        f"Query: {query}\n\nAvailable memories:\n{manifest}{tools_section}\n\n"
        'Return JSON: {"selected_memories": ["filename.md", ...]}'
    )
    raw = await complete_text(
        model, SELECT_MEMORIES_SYSTEM_PROMPT, user_prompt, max_tokens=256
    )
    return _parse_selected_filenames(raw)


async def find_relevant_memories(
    query: str,
    memory_dir: Path | str | None = None,
    max_results: int = 5,
    model: object | None = None,
    recent_tools: list[str] | None = None,
) -> list[str]:
    """召回与 query 相关的记忆文件路径 — 对齐 findRelevantMemories.ts

    Args:
        query: 用户查询
        memory_dir: 记忆目录，None 时用默认目录
        max_results: 最多召回数量（≤5）
        model: 记忆专用模型，None 时自动创建
        recent_tools: 最近用过的工具名列表（透传给选择器做过滤）

    Returns:
        相关记忆文件的绝对路径列表
    """
    memories = mm.scan_memory_files(memory_dir)
    if not memories:
        return []

    manifest = mm.format_memory_manifest(memories)
    if model is None:
        try:
            model = create_memory_model()
        except Exception as e:
            logger.warning("memory_recall: 创建记忆模型失败: %s", e)
            return []

    selected = await _select_relevant_memories(query, manifest, model, recent_tools)
    if not selected:
        return []

    # 按 manifest 顺序过滤并限制数量（保持选择器结果，但对齐 manifest 顺序）
    by_filename = {m.filename: m for m in memories}
    result: list[str] = []
    for filename in selected:
        if filename in by_filename:
            result.append(str(by_filename[filename].file_path))
        if len(result) >= max_results:
            break
    return result


# ============================================================================
# 独立 memory section 构建 — 用于注入 system prompt
# ============================================================================


def _read_topic_content(file_path: Path, max_chars: int = 4000) -> str:
    """读取单个主题文件内容（限制长度）

    Args:
        file_path: 记忆文件路径
        max_chars: 最大字符数

    Returns:
        文件内容（截断）
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("memory_recall: 读取记忆文件失败 %s: %s", file_path, e)
        return ""
    if len(content) > max_chars:
        content = content[:max_chars] + "\n...(截断)"
    return content


async def build_memory_section(
    query: str,
    memory_dir: Path | str | None = None,
    model: object | None = None,
) -> str:
    """构建独立 memory section 文本 — 用于注入 system prompt

    结构：
        1. 行为指令（含 MEMORY.md 索引）
        2. 召回的主题文件内容（DeepSeek V4 Flash 选择）

    Args:
        query: 用户查询
        memory_dir: 记忆目录，None 时用默认目录
        model: 记忆专用模型，None 时自动创建

    Returns:
        memory section 文本；记忆未启用或无内容时返回空字符串
    """
    path = mm.ensure_memory_dir_exists(memory_dir)
    entrypoint_content = mm.read_entrypoint(path)

    prompt = build_memory_prompt(path, entrypoint_content)

    parts: list[str] = [prompt]

    # 召回相关主题文件
    try:
        relevant = await find_relevant_memories(query, path, model=model)
    except Exception as e:
        logger.warning("memory_recall: 召回失败: %s", e)
        relevant = []

    for file_path in relevant:
        content = _read_topic_content(Path(file_path))
        if content.strip():
            parts.append(f"\n## 相关记忆：{Path(file_path).name}\n\n{content}")

    return "\n\n".join(parts)


def build_recalled_memories_section(relevant_paths: list[str]) -> str:
    """构建动态召回的主题文件内容段（含时效标注）— 供 before_model 钩子注入

    与 build_memory_section 不同：本函数只包含按 query 召回的主题文件内容，
    不含静态行为指令与 MEMORY.md 索引（那些由 register_rule 注入 system prompt），
    避免重复。

    每条召回记忆附时效标注（对齐 memoryAge.ts memoryFreshnessNote），
    让主模型识别记忆可能过时。

    Args:
        relevant_paths: find_relevant_memories 返回的相关记忆文件绝对路径列表

    Returns:
        召回内容段文本；全部为空时返回空字符串
    """
    parts: list[str] = []
    for fp in relevant_paths:
        path = Path(fp)
        content = _read_topic_content(path)
        if not content.strip():
            continue
        try:
            mtime_ms = path.stat().st_mtime * 1000
        except OSError:
            mtime_ms = 0.0
        freshness = memory_freshness_note(mtime_ms)
        parts.append(f"## 相关记忆：{path.name}\n\n{content}")
        if freshness:
            parts.append(freshness.strip())
    return "\n\n".join(parts)