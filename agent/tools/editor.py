# -*- coding: utf-8 -*-
"""行级文件编辑工具 — 对标 Cline createEditorTool

提供三种编辑模式:
    1. 插入模式（insert_line）: 在指定行号前插入 new_text
       - 行号 1-based，line_count+1 表示追加到末尾
    2. 替换模式（old_text）: 用 new_text 替换文件中唯一匹配的 old_text
       - old_text 必须在文件中唯一匹配，否则报错
    3. 创建模式: 文件不存在且无 old_text 时，用 new_text 创建文件

工作流程:
    1. LLM 调用 editor(path="...", new_text="...", insert_line=10)
       或 editor(path="...", old_text="...", new_text="...")
    2. 工具读取文件内容（不存在视为空）
    3. 按模式应用编辑
    4. 写入文件并返回 {path, operation, lines_before, lines_after}

安全设计:
    - old_text 替换模式要求唯一匹配，避免误改
    - insert_line 超出范围时报错
    - 自动创建父目录

对标 Cline:
    - sdk/packages/core/src/extensions/tools/create-editor-tool.ts
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult


def _detect_line_ending(text: str) -> str:
    """检测文本的主换行符（\\r\\n 或 \\n）"""
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _normalize_for_edit(text: str, line_ending: str) -> str:
    """将文本统一为 \\n 处理，便于编辑"""
    if line_ending == "\r\n":
        return text.replace("\r\n", "\n")
    return text


def _restore_line_ending(text: str, line_ending: str) -> str:
    """编辑完成后还原为原始换行符"""
    if line_ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def _create_line_diff(
    old_content: str,
    new_content: str,
    max_lines: int = 200,
) -> str:
    """生成行级 diff — 对标 Cline editor.ts L87-149 createLineDiff

    修剪公共前后缀，只输出变更区域。行预算在 removed/added 间分配，
    避免单侧吃满 max_lines。输出 ```diff 代码块格式。

    Args:
        old_content: 编辑前的内容
        new_content: 编辑后的内容
        max_lines: diff 最大行数（含 removed + added）

    Returns:
        ```diff 代码块字符串
    """
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    # 修剪公共前缀
    start = 0
    while (start < len(old_lines) and start < len(new_lines)
           and old_lines[start] == new_lines[start]):
        start += 1

    # 修剪公共后缀
    old_end = len(old_lines)
    new_end = len(new_lines)
    while (old_end > start and new_end > start
           and old_lines[old_end - 1] == new_lines[new_end - 1]):
        old_end -= 1
        new_end -= 1

    # 行预算分配 — 对齐 Cline L122-129
    removed_count = old_end - start
    added_count = new_end - start
    removed_budget = removed_count
    added_budget = added_count
    if removed_count + added_count > max_lines:
        # ceil(max_lines/2) 用 -(-x//2) 实现
        removed_budget = min(
            removed_count,
            max(-(-max_lines // 2), max_lines - added_count),
        )
        added_budget = min(added_count, max_lines - removed_budget)

    # 输出 ```diff 代码块
    out: list[str] = ["```diff"]
    for i in range(start, start + removed_budget):
        out.append(f"-{i + 1}: {old_lines[i]}")
    for i in range(start, start + added_budget):
        out.append(f"+{i + 1}: {new_lines[i]}")

    omitted_removed = removed_count - removed_budget
    omitted_added = added_count - added_budget
    if omitted_removed > 0 or omitted_added > 0:
        out.append(
            f"... diff truncated ({omitted_removed} more removed, "
            f"{omitted_added} more added lines) ..."
        )

    out.append("```")
    return "\n".join(out)


class EditorTool(BaseTool):
    """行级文件编辑工具 — 对标 Cline createEditorTool

    参数:
        path: 文件路径（必填）
        new_text: 新内容（必填）
        old_text: 旧内容（可选，替换模式）
        insert_line: 插入行号（可选，插入模式）
        working_dir: 工作目录（可选，用于解析相对路径，默认当前目录）
    """

    def __init__(self, working_dir: str | None = None) -> None:
        self._working_dir = working_dir or os.getcwd()

    @property
    def name(self) -> str:
        return "editor"

    @property
    def description(self) -> str:
        return (
            "行级文件编辑工具。提供 path(必填)/old_text(可选)/new_text(必填)/insert_line(可选)。"
            "有 insert_line 时在指定行号前插入 new_text（1-based，line_count+1 表示追加到末尾）；"
            "有 old_text 时用 new_text 替换 old_text（old_text 必须唯一匹配）；"
            "文件不存在且无 old_text 时用 new_text 创建文件；"
            "文件已存在且未提供 old_text/insert_line 时返回错误（对齐 Cline 抛错行为）。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "文件路径",
                },
                "old_text": {
                    "type": "string",
                    "description": "要替换的文本（替换模式，必须在文件中唯一匹配）",
                },
                "new_text": {
                    "type": "string",
                    "description": "新内容",
                },
                "insert_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "插入行号（1-based，line_count+1 表示追加到末尾）",
                },
            },
            "required": ["path", "new_text"],
        }

    @property
    def read_only(self) -> bool:
        return False

    @property
    def requires_approval(self) -> bool:
        """行级文件编辑需要用户审批 — Phase 19"""
        return True

    def _restrict_to_cwd(self, file_path: str) -> str:
        """确保文件路径在 cwd 内 — 对标 Cline restrictToCwd

        绝对路径直接接受（对标 Cline editor.ts resolveFilePath 行为），
        相对路径解析后检查是否逃逸到 cwd 之外。

        Args:
            file_path: 待校验的文件路径（相对或绝对）

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
        # rel 以 ".." 开头表示路径逃逸到 cwd 之外
        if rel.startswith("..") or os.path.isabs(rel):
            raise ValueError(f"路径 {file_path} 不在当前工作目录 {cwd} 内")
        return abs_path

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行行级文件编辑 — 对标 Cline createEditorTool.execute()"""
        path_str = input["path"]
        new_text = input["new_text"]
        old_text = input.get("old_text")
        insert_line = input.get("insert_line")

        # 越界检查 — 对标 Cline restrictToCwd
        # 路径逃逸到 cwd 之外时抛 ValueError，由 BaseTool.execute 捕获返回错误
        abs_path = self._restrict_to_cwd(path_str)
        path = Path(abs_path)
        exists = path.exists()

        # 读取现有内容（不存在视为空）
        if exists:
            if not path.is_file():
                return AgentToolResult(
                    output={"error": f"不是文件: {path_str}"},
                    is_error=True,
                )
            try:
                raw_original = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return AgentToolResult(
                    output={"error": f"无法读取二进制文件: {path_str}"},
                    is_error=True,
                )
        else:
            raw_original = ""

        # 检测并统一换行符为 \\n 进行编辑，写入时再还原
        line_ending = _detect_line_ending(raw_original)
        original = _normalize_for_edit(raw_original, line_ending)
        original_lines = original.splitlines(keepends=False)
        lines_before = len(original_lines)

        # 分支: insert_line 模式
        if insert_line is not None:
            return self._do_insert(path, path_str, original, original_lines,
                                   new_text, insert_line, lines_before, line_ending)

        # 分支: old_text 替换模式
        if old_text is not None:
            return self._do_replace(path, path_str, original, original_lines,
                                    old_text, new_text, lines_before, line_ending)

        # 分支: 创建模式（文件不存在且无 old_text）
        if not exists:
            return self._do_create(path, path_str, new_text)

        # 文件已存在但没有提供 old_text 或 insert_line — 对齐 Cline 抛错行为
        # Phase 3.1 (G3.3): 原 _do_overwrite 整体覆盖分支已移除，
        # 改为返回错误，防止 LLM 漏传 old_text 导致整个文件被覆盖。
        # _do_overwrite 函数定义保留以备未来需要显式整体覆盖模式时复用。
        return AgentToolResult(
            output={
                "error": "文件已存在，必须提供 old_text（替换模式）或 insert_line（插入模式）",
                "path": path_str,
                "lines_before": lines_before,
            },
            is_error=True,
        )

    def _do_insert(
        self,
        path: Path,
        path_str: str,
        original: str,
        original_lines: list[str],
        new_text: str,
        insert_line: int,
        lines_before: int,
        line_ending: str,
    ) -> AgentToolResult:
        """插入模式: 在 insert_line 行前插入 new_text

        insert_line 是 1-based，line_count+1 表示追加到末尾。
        """
        total = len(original_lines)

        # 校验 insert_line 范围: 1 到 total+1
        if insert_line < 1 or insert_line > total + 1:
            return AgentToolResult(
                output={
                    "error": f"insert_line {insert_line} 超出范围（1 到 {total + 1}）",
                    "lines_before": total,
                },
                is_error=True,
            )

        # 准备插入内容（按行分割，统一换行符）
        normalized_new_text = _normalize_for_edit(new_text, line_ending)
        insert_lines = normalized_new_text.splitlines(keepends=False)

        # 在 insert_line-1 索引处插入
        insert_idx = insert_line - 1
        new_lines = original_lines[:insert_idx] + insert_lines + original_lines[insert_idx:]

        # 写入文件 — 保留原文件末尾换行行为，并还原原始换行符
        content = "\n".join(new_lines)
        if original.endswith("\n") and not content.endswith("\n"):
            content += "\n"
        content = _restore_line_ending(content, line_ending)

        self._write_file(path, content)
        lines_after = len(new_lines)

        # Phase 3.3 (G3.6): 生成 diff 供 LLM 自我校验 — 对标 Cline editor.ts L198
        diff = _create_line_diff(original, content)
        return AgentToolResult(
            output={
                "path": path_str,
                "operation": "insert",
                "insert_line": insert_line,
                "lines_before": lines_before,
                "lines_after": lines_after,
                "inserted_lines": len(insert_lines),
                "diff": diff,
            },
            metadata={"operation": "insert", "path": path_str},
        )

    def _do_replace(
        self,
        path: Path,
        path_str: str,
        original: str,
        original_lines: list[str],
        old_text: str,
        new_text: str,
        lines_before: int,
        line_ending: str,
    ) -> AgentToolResult:
        """替换模式: 用 new_text 替换文件中唯一匹配的 old_text

        优先使用行级匹配（避免跨行误匹配），old_text 不含换行时退化为字符串替换。
        """
        normalized_old = _normalize_for_edit(old_text, line_ending)
        normalized_new = _normalize_for_edit(new_text, line_ending)

        # 含换行时优先使用行级匹配，更安全
        if "\n" in normalized_old:
            old_lines = normalized_old.splitlines(keepends=False)
            n = len(old_lines)
            matches: list[int] = []
            for idx in range(len(original_lines) - n + 1):
                if original_lines[idx:idx + n] == old_lines:
                    matches.append(idx)

            if len(matches) == 0:
                return AgentToolResult(
                    output={
                        "error": "old_text 在文件中未找到匹配（行级匹配）",
                        "path": path_str,
                        "lines_before": lines_before,
                    },
                    is_error=True,
                )
            if len(matches) > 1:
                return AgentToolResult(
                    output={
                        "error": f"old_text 在文件中匹配 {len(matches)} 处，必须唯一匹配",
                        "path": path_str,
                        "match_count": len(matches),
                        "lines_before": lines_before,
                    },
                    is_error=True,
                )

            start = matches[0]
            new_lines = (
                original_lines[:start]
                + normalized_new.splitlines(keepends=False)
                + original_lines[start + n:]
            )
            content = "\n".join(new_lines)
            if original.endswith("\n") and not content.endswith("\n"):
                content += "\n"
            content = _restore_line_ending(content, line_ending)
            self._write_file(path, content)
            lines_after = len(new_lines)
            # Phase 3.3 (G3.6): 生成 diff 供 LLM 自我校验 — 对标 Cline editor.ts L198
            diff = _create_line_diff(original, content)
            return AgentToolResult(
                output={
                    "path": path_str,
                    "operation": "edit",
                    "lines_before": lines_before,
                    "lines_after": lines_after,
                    "diff": diff,
                },
                metadata={"operation": "edit", "path": path_str},
            )

        # 不含换行时退化为字符串替换，保持原有行为
        count = original.count(normalized_old)
        if count == 0:
            return AgentToolResult(
                output={
                    "error": "old_text 在文件中未找到匹配",
                    "path": path_str,
                    "lines_before": lines_before,
                },
                is_error=True,
            )
        if count > 1:
            return AgentToolResult(
                output={
                    "error": f"old_text 在文件中匹配 {count} 次，必须唯一匹配",
                    "path": path_str,
                    "match_count": count,
                    "lines_before": lines_before,
                },
                is_error=True,
            )

        new_content = original.replace(normalized_old, normalized_new)
        new_content = _restore_line_ending(new_content, line_ending)
        self._write_file(path, new_content)
        lines_after = len(new_content.splitlines(keepends=False))

        # Phase 3.3 (G3.6): 生成 diff 供 LLM 自我校验 — 对标 Cline editor.ts L198
        diff = _create_line_diff(original, new_content)
        return AgentToolResult(
            output={
                "path": path_str,
                "operation": "edit",
                "lines_before": lines_before,
                "lines_after": lines_after,
                "diff": diff,
            },
            metadata={"operation": "edit", "path": path_str},
        )

    def _do_create(
        self,
        path: Path,
        path_str: str,
        new_text: str,
    ) -> AgentToolResult:
        """创建模式: 文件不存在且无 old_text，直接创建"""
        self._write_file(path, new_text)
        lines_after = len(new_text.splitlines(keepends=False))

        # Phase 3.3 (G3.6): 生成 diff 供 LLM 自我校验 — create 模式全部为新增行
        diff = _create_line_diff("", new_text)
        return AgentToolResult(
            output={
                "path": path_str,
                "operation": "create",
                "lines_before": 0,
                "lines_after": lines_after,
                "diff": diff,
            },
            metadata={"operation": "create", "path": path_str},
        )

    def _do_overwrite(
        self,
        path: Path,
        path_str: str,
        original: str,
        new_text: str,
        lines_before: int,
        line_ending: str,
    ) -> AgentToolResult:
        """覆盖模式: 文件已存在但未提供 old_text/insert_line，覆盖写入"""
        content = _normalize_for_edit(new_text, line_ending)
        content = _restore_line_ending(content, line_ending)
        self._write_file(path, content)
        lines_after = len(content.splitlines(keepends=False))

        return AgentToolResult(
            output={
                "path": path_str,
                "operation": "edit",
                "lines_before": lines_before,
                "lines_after": lines_after,
                "note": "文件已存在且未提供 old_text/insert_line，整体覆盖",
            },
            metadata={"operation": "edit", "path": path_str},
        )

    def _write_file(self, path: Path, content: str) -> None:
        """写入文件 — 自动创建父目录，UTF-8 编码"""
        # 自动创建父目录 — 对标 FileWriteTool
        path.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 编码写入（项目约束）
        path.write_text(content, encoding="utf-8")
