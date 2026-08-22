# -*- coding: utf-8 -*-
"""记忆存储层 — 对齐 Claude Code memdir 实现

管理持久化文件式记忆系统：
    1. 记忆目录 agent_config/memory/
    2. MEMORY.md 作为索引（entrypoint，无 frontmatter，每行一个指针）
    3. 每个主题文件带 frontmatter（name/description/type/tags/updated/when_to_access）
    4. 4 类记忆：user / feedback / project / reference
    5. 扫描目录生成 manifest（对齐 memoryScan.ts）
    6. MEMORY.md 截断（对齐 memdir.ts：200 行 / 25KB）

4 类记忆语义（量化系统适配）：
    - user:     交易者画像（风险偏好、资金管理习惯、股票池偏好、研究习惯）
    - feedback: 对研报/策略/计划的纠正指令（"财报数字不走网络搜索"等）
    - project:  投资决策上下文（对某股票/板块/概念的观点、策略决策及理由、持仓决策逻辑）
    - reference: 数据源/指标/工具用法（xtdata 取数要点、交易计划 MD 格式、指标含义）

不存原则（量化适配）：不存"可用数据库/行情推导的市场数据"（价格、财务数字、K线指标），
只存决策、观点、理由、启发、偏好。

对标 Claude Code:
    - src/memdir/memdir.ts
    - src/memdir/memoryScan.ts
    - src/memdir/memoryTypes.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# 常量 — 对齐 Claude Code memdir.ts / memoryScan.ts
# ============================================================================

# 4 类记忆类型
MEMORY_TYPES = ["user", "feedback", "project", "reference"]

# 索引文件名（entrypoint）
ENTRYPOINT_NAME = "MEMORY.md"

# 索引截断上限 — 对齐 Claude Code MAX_ENTRYPOINT_LINES / MAX_ENTRYPOINT_BYTES
MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000

# 扫描文件上限 — 对齐 Claude Code MAX_MEMORY_FILES
MAX_MEMORY_FILES = 200

# 主题文件 frontmatter 读取行数上限 — 对齐 Claude Code FRONTMATTER_MAX_LINES
FRONTMATTER_MAX_LINES = 30

# 默认记忆目录
DEFAULT_MEMORY_DIR = Path("agent_config") / "memory"


def parse_memory_type(raw: Any) -> str | None:
    """解析 frontmatter 的 type 字段为合法记忆类型 — 对齐 memoryTypes.ts parseMemoryType

    非法或缺失值返回 None（legacy 文件无 type 字段保持可用，未知类型优雅降级）。

    Args:
        raw: frontmatter 中的 type 原始值

    Returns:
        合法记忆类型或 None
    """
    if not isinstance(raw, str):
        return None
    return raw if raw in MEMORY_TYPES else None


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class MemoryHeader:
    """记忆文件头信息 — 对齐 memoryScan.ts MemoryHeader

    Attributes:
        filename: 相对记忆目录的文件名（含子目录相对路径）
        file_path: 文件绝对路径
        mtime_ms: 修改时间（毫秒时间戳）
        description: frontmatter 中的 description
        type: 记忆类型（user/feedback/project/reference）
        tags: frontmatter 中的 tags 列表（量化适配，用于主题召回）
    """

    filename: str
    file_path: Path
    mtime_ms: float
    description: str | None = None
    type: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class MemoryFile:
    """记忆文件完整内容 — 用于写入

    Attributes:
        filename: 相对记忆目录的文件名（含子目录相对路径）
        name: 记忆名称（frontmatter name）
        description: 一句话描述（frontmatter description）
        type: 记忆类型（user/feedback/project/reference）
        tags: 标签列表（frontmatter tags）
        when_to_access: 可选的访问条件说明
        content: 正文内容（markdown）
    """

    filename: str
    name: str
    description: str
    type: str
    tags: list[str] = field(default_factory=list)
    when_to_access: str = ""
    content: str = ""


# ============================================================================
# 路径与目录
# ============================================================================


def get_memory_dir() -> Path:
    """获取记忆目录路径 — 默认 agent_config/memory/

    Returns:
        记忆目录 Path（相对项目根目录）
    """
    return DEFAULT_MEMORY_DIR


def ensure_memory_dir_exists(memory_dir: Path | str | None = None) -> Path:
    """确保记忆目录存在（幂等）— 对齐 memdir.ts ensureMemoryDirExists

    Args:
        memory_dir: 记忆目录，None 时用默认目录

    Returns:
        记忆目录 Path
    """
    path = Path(memory_dir) if memory_dir else get_memory_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("memory_manager: 创建记忆目录失败 %s: %s", path, e)
    return path


# ============================================================================
# 扫描 & manifest — 对齐 memoryScan.ts
# ============================================================================


def _read_frontmatter_header(file_path: Path) -> dict[str, Any]:
    """读取文件前几行的 frontmatter（仅头信息，不读全文）

    Args:
        file_path: 记忆文件路径

    Returns:
        frontmatter 数据 dict；解析失败或不含 frontmatter 时返回空 dict
    """
    try:
        # 只读取前 FRONTMATTER_MAX_LINES 行，避免大文件全量读取
        with open(file_path, encoding="utf-8") as f:
            head_lines = [f.readline() for _ in range(FRONTMATTER_MAX_LINES)]
        head = "".join(head_lines).strip()
        from agent.rules_loader import parse_yaml_frontmatter

        result = parse_yaml_frontmatter(head)
        return result.data if result.had_frontmatter else {}
    except Exception as e:
        logger.debug("memory_manager: 读取 frontmatter 失败 %s: %s", file_path, e)
        return {}


def scan_memory_files(memory_dir: Path | str | None = None) -> list[MemoryHeader]:
    """扫描记忆目录下所有 .md 文件（排除 MEMORY.md），读取 frontmatter — 对齐 memoryScan.ts

    Returns:
        MemoryHeader 列表，按修改时间倒序，最多 MAX_MEMORY_FILES 个
    """
    path = ensure_memory_dir_exists(memory_dir)
    headers: list[MemoryHeader] = []
    try:
        for file_path in path.rglob("*.md"):
            if file_path.name == ENTRYPOINT_NAME:
                continue
            header = _build_header(file_path, path)
            if header is not None:
                headers.append(header)
    except OSError as e:
        logger.warning("memory_manager: 扫描记忆目录失败 %s: %s", path, e)
        return []

    headers.sort(key=lambda h: h.mtime_ms, reverse=True)
    return headers[:MAX_MEMORY_FILES]


def _build_header(file_path: Path, memory_dir: Path) -> MemoryHeader | None:
    """构建单个记忆文件头 — 对齐 memoryScan.ts readFileInRange + parseFrontmatter

    Args:
        file_path: 记忆文件路径
        memory_dir: 记忆目录（用于计算相对文件名）

    Returns:
        MemoryHeader 或 None（构建失败时）
    """
    try:
        stat = file_path.stat()
        fm = _read_frontmatter_header(file_path)
        return MemoryHeader(
            filename=file_path.relative_to(memory_dir).as_posix(),
            file_path=file_path,
            mtime_ms=stat.st_mtime * 1000,
            description=fm.get("description") or None,
            type=parse_memory_type(fm.get("type")),
            tags=_parse_tags(fm.get("tags")),
        )
    except OSError as e:
        logger.debug("memory_manager: 构建记忆头失败 %s: %s", file_path, e)
        return None


def _parse_tags(raw: Any) -> list[str]:
    """解析 frontmatter tags 字段为字符串列表

    Args:
        raw: frontmatter tags 原始值

    Returns:
        字符串列表；非列表或空时返回空列表
    """
    if isinstance(raw, list):
        return [str(t) for t in raw if isinstance(t, str) and t.strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def format_memory_manifest(memories: list[MemoryHeader]) -> str:
    """格式化记忆头为文本 manifest — 对齐 memoryScan.ts formatMemoryManifest

    每行一个文件：`[type] filename (ISO时间): description`

    Args:
        memories: MemoryHeader 列表

    Returns:
        拼接后的 manifest 文本
    """
    lines: list[str] = []
    for m in memories:
        tag = f"[{m.type}] " if m.type else ""
        # 对齐 memoryScan.ts formatMemoryManifest：用 UTC ISO 时间戳（new Date(mtimeMs).toISOString()）
        ts = datetime.fromtimestamp(m.mtime_ms / 1000, tz=timezone.utc).isoformat()
        if m.description:
            lines.append(f"- {tag}{m.filename} ({ts}): {m.description}")
        else:
            lines.append(f"- {tag}{m.filename} ({ts})")
    return "\n".join(lines)


# ============================================================================
# 索引（MEMORY.md）读写 — 对齐 memdir.ts
# ============================================================================


def truncate_entrypoint_content(content: str) -> tuple[str, bool]:
    """截断 MEMORY.md 内容到行数与字节上限 — 对齐 memdir.ts truncateEntrypointContent

    先按行截断（自然边界），再按字节截断（在最后一个换行处截，避免切到行中间）。

    Args:
        content: MEMORY.md 原始内容

    Returns:
        (截断后的内容, 是否发生了截断)
    """
    trimmed = content.strip()
    content_lines = trimmed.split("\n")
    line_count = len(content_lines)
    byte_count = len(trimmed)

    was_truncated = False
    if line_count > MAX_ENTRYPOINT_LINES:
        trimmed = "\n".join(content_lines[:MAX_ENTRYPOINT_LINES])
        was_truncated = True

    if len(trimmed) > MAX_ENTRYPOINT_BYTES:
        cut_at = trimmed.rfind("\n", 0, MAX_ENTRYPOINT_BYTES)
        trimmed = trimmed[: cut_at if cut_at > 0 else MAX_ENTRYPOINT_BYTES]
        was_truncated = True

    return trimmed, was_truncated


def read_entrypoint(memory_dir: Path | str | None = None) -> str:
    """读取 MEMORY.md 索引内容（已截断）— 对齐 memdir.ts buildMemoryPrompt 读取逻辑

    Args:
        memory_dir: 记忆目录，None 时用默认目录

    Returns:
        截断后的索引内容；文件不存在或为空时返回空字符串
    """
    path = Path(memory_dir) if memory_dir else get_memory_dir()
    entry_path = path / ENTRYPOINT_NAME
    if not entry_path.exists():
        return ""
    try:
        raw = entry_path.read_text(encoding="utf-8")
        content, _ = truncate_entrypoint_content(raw)
        return content
    except OSError as e:
        logger.warning("memory_manager: 读取索引失败 %s: %s", entry_path, e)
        return ""


def update_entrypoint(
    memory_dir: Path | str | None,
    filename: str,
    title: str,
    hook: str,
) -> None:
    """在 MEMORY.md 索引中新增或更新一条指针 — 对齐 memdir 两步写入法的 Step 2

    指针格式：`- [Title](file.md) — one-line hook`，无 frontmatter。
    若已存在同名指针则更新，否则追加到末尾。

    Args:
        memory_dir: 记忆目录
        filename: 记忆文件相对路径（如 project_dongfang.md）
        title: 索引中显示的标题
        hook: 一句话钩子（用于召回复盘）
    """
    path = ensure_memory_dir_exists(memory_dir)
    entry_path = path / ENTRYPOINT_NAME
    line = f"- [{title}]({filename}) — {hook}"

    existing = ""
    if entry_path.exists():
        try:
            existing = entry_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("memory_manager: 读取索引失败 %s: %s", entry_path, e)
            existing = ""

    lines = existing.splitlines() if existing else []
    # 是否已存在指向同一文件名的指针
    prefix = f"- [{title}]({filename})"
    replaced = False
    new_lines: list[str] = []
    for ln in lines:
        if ln.startswith(prefix):
            new_lines.append(line)
            replaced = True
        else:
            new_lines.append(ln)

    if not replaced:
        new_lines.append(line)

    try:
        entry_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        logger.debug("memory_manager: 更新索引 %s <- %s", ENTRYPOINT_NAME, filename)
    except OSError as e:
        logger.warning("memory_manager: 更新索引失败 %s: %s", entry_path, e)


# ============================================================================
# 写入 — 对齐 memdir 两步写入法（Step 1 写主题文件 + Step 2 更新索引）
# ============================================================================


def _build_memory_file_content(memory: MemoryFile) -> str:
    """构建记忆文件完整内容（frontmatter + 正文）

    Args:
        memory: 记忆文件数据

    Returns:
        完整 markdown 文本
    """
    fm_lines = [
        "---",
        f"name: {memory.name}",
        f"description: {memory.description}",
        f"type: {memory.type}",
    ]
    if memory.tags:
        tags_str = ", ".join(memory.tags)
        fm_lines.append(f"tags: [{tags_str}]")
    if memory.when_to_access:
        fm_lines.append(f"when_to_access: {memory.when_to_access}")
    fm_lines.append(f"updated: {datetime.now().strftime('%Y-%m-%d')}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(memory.content.strip())
    return "\n".join(fm_lines)


def save_memory(
    memory: MemoryFile,
    memory_dir: Path | str | None = None,
) -> bool:
    """保存一条记忆（写主题文件 + 更新 MEMORY.md 索引）— 对齐 memdir 两步写入法

    自动将派生的文件名规范化（去除路径分隔符等非法字符）。

    Args:
        memory: 记忆文件数据
        memory_dir: 记忆目录，None 时用默认目录

    Returns:
        是否写入成功
    """
    if not memory.filename or not memory.name or not memory.content.strip():
        logger.warning("memory_manager: 缺少必要字段，跳过保存")
        return False

    type_ = parse_memory_type(memory.type)
    if type_ is None:
        logger.warning("memory_manager: 非法记忆类型 %r，跳过保存", memory.type)
        return False

    path = ensure_memory_dir_exists(memory_dir)
    # 规范化文件名：确保 .md 后缀，去除路径分隔符
    filename = _normalize_filename(memory.filename)
    file_path = path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)

    content = _build_memory_file_content(memory)
    try:
        file_path.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.warning("memory_manager: 写入记忆文件失败 %s: %s", file_path, e)
        return False

    # Step 2：更新索引
    update_entrypoint(path, filename, memory.name, memory.description)
    return True


def _normalize_filename(filename: str) -> str:
    """规范化记忆文件名 — 确保 .md 后缀并去除路径分隔符

    Args:
        filename: 原始文件名

    Returns:
        规范化后的文件名
    """
    # 去除路径分隔符，防止越权写入
    safe = filename.replace("\\", "_").replace("/", "_")
    if not safe.endswith(".md"):
        safe += ".md"
    return safe