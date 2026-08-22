# -*- coding: utf-8 -*-
"""目录列表工具 — 列出目录下的文件和子目录

支持单层列表和递归列表两种模式。
递归模式跳过 .git/node_modules/__pycache__/.venv 等目录。

工作流程:
    1. LLM 调用 list_files(path="...", recursive=true)
    2. 工具用 pathlib.Path 遍历目录
    3. 非 recursive: 只列一层
    4. recursive: 用 rglob 遍历，跳过常见大目录
    5. 返回 {path, entries: [{name, type, size}]}

安全设计:
    - 单次最多返回 200 个条目
    - 递归模式跳过 .git/node_modules/__pycache__/.venv 等目录
    - 路径不存在时报错
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from collections import deque
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool
from agent.tools.constants import MAX_LIST_ENTRIES
from agent.types import AgentToolContext, AgentToolResult


class ListFilesTool(BaseTool):
    """目录列表工具

    参数:
        path: 目录路径（必填）
        recursive: 是否递归（可选，默认 false）

    构造函数:
        working_dir: 工作目录（可选，用于解析相对路径，默认当前目录）
    """

    # Phase 31.5: 常量统一到 agent.tools.constants — 对标 Cline output-limits.ts
    # 保留类属性作为向后兼容别名，值来自 constants 模块
    _MAX_ENTRIES = MAX_LIST_ENTRIES

    # 递归模式跳过的目录名
    _SKIP_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".idea",
        ".vscode",
        "dist",
        "build",
    }

    # 列表操作超时秒数 — 对标 Cline globbyLevelByLevel 的 10s 超时
    _LIST_TIMEOUT_SECONDS = 10

    def __init__(self, working_dir: str | None = None) -> None:
        """初始化目录列表工具

        Args:
            working_dir: 工作目录，用于解析相对路径，默认为当前目录
        """
        self._working_dir = working_dir or os.getcwd()

    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return (
            "列出目录下的文件和子目录。"
            "参数: path(必填): 目录路径; "
            "recursive(可选): 是否递归，默认 false"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径（必填）",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "是否递归列出（默认 false）",
                },
            },
            "required": ["path"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def _restrict_to_cwd(self, file_path: str) -> str:
        """确保路径在 cwd 内 — 对标 Cline isRestrictedPath + restrictToCwd

        绝对路径直接接受，相对路径基于 working_dir 解析后检查是否逃逸。

        Args:
            file_path: 待校验的路径（相对或绝对）

        Returns:
            规范化后的绝对路径

        Raises:
            ValueError: 路径逃逸到 cwd 之外
        """
        cwd = self._working_dir
        if os.path.isabs(file_path):
            return os.path.normpath(file_path)
        abs_path = os.path.normpath(os.path.join(cwd, file_path))
        rel = os.path.relpath(abs_path, cwd)
        if rel.startswith("..") or os.path.isabs(rel):
            raise ValueError(f"路径 {file_path} 不在当前工作目录 {cwd} 内")
        return abs_path

    def _load_gitignore_patterns(self, dir_path: Path) -> list[str]:
        """读取目录下的 .gitignore 并返回 pattern 列表 — 对标 Cline readGitignorePatterns

        解析规则（对标 Cline list-files.ts L62-97）:
            - 跳过空行和注释（# 开头）
            - 跳过否定模式（! 开头）— 复杂且对目录列表场景非关键
            - 去除目录模式尾部斜杠

        Args:
            dir_path: 要读取 .gitignore 的目录

        Returns:
            fnmatch pattern 列表，读取失败返回空列表
        """
        gitignore = dir_path / ".gitignore"
        if not gitignore.is_file():
            return []
        patterns: list[str] = []
        try:
            for line in gitignore.read_text(encoding="utf-8").splitlines():
                trimmed = line.strip()
                if not trimmed or trimmed.startswith("#"):
                    continue
                if trimmed.startswith("!"):  # 跳过否定模式
                    continue
                # 去除目录模式尾部斜杠
                if trimmed.endswith("/"):
                    trimmed = trimmed[:-1]
                if trimmed:
                    patterns.append(trimmed)
        except (OSError, UnicodeDecodeError):
            pass
        return patterns

    def _match_gitignore(self, rel_path: str, patterns: list[str]) -> bool:
        """检查相对路径是否匹配 gitignore 模式 — 对标 Cline gitignore 过滤

        用 fnmatch 简单匹配，检查:
            1. 完整相对路径
            2. 路径中的各部分（目录名/文件名）

        Args:
            rel_path: 相对于列表根目录的路径（正斜杠分隔）
            patterns: _load_gitignore_patterns 返回的 pattern 列表

        Returns:
            是否匹配任一 pattern
        """
        if not patterns:
            return False
        normalized = rel_path.replace("\\", "/")
        parts = normalized.split("/")
        for pattern in patterns:
            # 匹配完整相对路径
            if fnmatch.fnmatch(normalized, pattern):
                return True
            # 匹配路径中的任意部分（目录名/文件名）
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行目录列表

        安全设计 — 对标 Cline list-files.ts:
            1. 受限路径保护: _restrict_to_cwd 检查路径是否在 cwd 内
            2. 超时保护: asyncio.wait_for 限制列表操作 10s — 对标 Cline 10s 超时
            3. .gitignore 过滤: 递归模式下增量读取各目录 .gitignore 过滤匹配项
        """
        path_str = input.get("path", ".")
        recursive = input.get("recursive", False)

        # 越界检查 — 对标 Cline isRestrictedPath + restrictToCwd
        # 相对路径基于 working_dir 解析，逃逸到 cwd 之外则拒绝
        try:
            abs_path = self._restrict_to_cwd(path_str)
        except ValueError as e:
            return AgentToolResult(
                output={"error": str(e)},
                is_error=True,
            )
        path = Path(abs_path)

        # 校验路径
        if not path.exists():
            return AgentToolResult(
                output={"error": f"路径不存在: {path_str}"},
                is_error=True,
            )

        if not path.is_dir():
            return AgentToolResult(
                output={"error": f"不是目录: {path_str}"},
                is_error=True,
            )

        # 超时保护 — 对标 Cline globbyLevelByLevel 的 10s 超时
        # 用 asyncio.to_thread 包装同步遍历，避免阻塞事件循环
        # 超时后返回已收集的部分结果（对标 Cline "returning partial results"）
        timed_out = False
        entries: list[dict[str, Any]] = []
        try:
            if recursive:
                entries = await asyncio.wait_for(
                    asyncio.to_thread(self._list_recursive, path),
                    timeout=self._LIST_TIMEOUT_SECONDS,
                )
            else:
                entries = await asyncio.wait_for(
                    asyncio.to_thread(self._list_single, path),
                    timeout=self._LIST_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            # 超时返回部分结果 — 对标 Cline "Globbing timed out, returning partial results"
            timed_out = True
        except PermissionError as e:
            return AgentToolResult(
                output={"error": f"权限不足: {e}"},
                is_error=True,
            )
        except Exception as e:
            return AgentToolResult(
                output={"error": f"列出目录失败: {e}"},
                is_error=True,
            )

        # 判断是否达到上限
        truncated = len(entries) >= self._MAX_ENTRIES

        result_output: dict[str, Any] = {
            "path": str(path),
            "entries": entries[:self._MAX_ENTRIES],
            "count": min(len(entries), self._MAX_ENTRIES),
            "truncated": truncated,
        }
        if timed_out:
            result_output["note"] = (
                f"列表操作超过 {self._LIST_TIMEOUT_SECONDS}s 超时，返回部分结果"
            )

        return AgentToolResult(
            output=result_output,
            metadata={
                "path": str(path),
                "recursive": recursive,
                "total": len(entries),
                "timed_out": timed_out,
            },
        )

    def _list_single(self, path: Path) -> list[dict[str, Any]]:
        """列出单层目录内容

        按名称排序，文件和目录混合排列。
        """
        entries: list[dict[str, Any]] = []

        for child in sorted(path.iterdir(), key=lambda p: p.name):
            if len(entries) >= self._MAX_ENTRIES:
                break

            try:
                if child.is_dir():
                    entries.append({
                        "name": child.name,
                        "type": "dir",
                        "size": 0,
                    })
                elif child.is_file():
                    entries.append({
                        "name": child.name,
                        "type": "file",
                        "size": child.stat().st_size,
                    })
            except (PermissionError, OSError):
                # 跳过无权限访问的条目
                continue

        return entries

    def _list_recursive(self, path: Path) -> list[dict[str, Any]]:
        """递归列出目录内容（BFS 广度优先）

        用 collections.deque 实现队列，按层级遍历目录 — 对标 Cline globbyLevelByLevel。
        顶层目录的文件先被列出，再逐层深入子目录，确保在达到上限时优先保留顶层条目。
        增量读取各目录的 .gitignore 过滤匹配项 — 对标 Cline readGitignorePatterns。
        返回相对路径（正斜杠分隔）。

        对标 Cline globbyLevelByLevel:
            - 队列驱动逐层遍历（BFS），而非 os.walk 的深度优先（DFS）
            - 每进入一个目录读取其 .gitignore，增量累积过滤规则
        """
        entries: list[dict[str, Any]] = []
        # BFS 队列: 每项为 (绝对目录路径, 相对目录路径)
        # rel_dir 为 "." 表示当前目录就是根目录
        queue: deque[tuple[Path, str]] = deque()
        queue.append((path, "."))

        while queue and len(entries) < self._MAX_ENTRIES:
            dir_path, rel_dir = queue.popleft()

            # 读取当前目录的 .gitignore — 增量加载，对标 Cline
            patterns = self._load_gitignore_patterns(dir_path)

            # 收集并按名称排序当前目录的子项
            try:
                children = sorted(dir_path.iterdir(), key=lambda p: p.name)
            except (PermissionError, OSError):
                # 跳过无权限访问的目录
                continue

            # 先列出当前目录的文件和子目录条目，再将子目录加入队列（BFS 核心）
            for child in children:
                if len(entries) >= self._MAX_ENTRIES:
                    break

                # 计算相对路径（正斜杠分隔）
                if rel_dir == ".":
                    rel_path = child.name
                else:
                    rel_path = (rel_dir + "/" + child.name).replace("\\", "/")

                # gitignore 匹配检查
                if self._match_gitignore(rel_path, patterns):
                    continue

                try:
                    if child.is_dir():
                        # 跳过 _SKIP_DIRS 中的目录（不列出也不入队）
                        if child.name in self._SKIP_DIRS:
                            continue
                        entries.append({
                            "name": rel_path,
                            "type": "dir",
                            "size": 0,
                        })
                        # 子目录加入队列，后续逐层处理 — BFS 逐层深入
                        queue.append((child, rel_path))
                    elif child.is_file():
                        entries.append({
                            "name": rel_path,
                            "type": "file",
                            "size": child.stat().st_size,
                        })
                except (PermissionError, OSError):
                    # 跳过无权限访问的条目
                    continue

        # BFS 天然按层级排列，各层内已按名称排序，无需全局排序
        return entries
