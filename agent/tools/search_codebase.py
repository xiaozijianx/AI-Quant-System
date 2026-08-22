# -*- coding: utf-8 -*-
"""正则代码搜索工具 — 对标 Cline createSearchExecutor

在代码库中执行正则表达式搜索，支持多个并行查询。
优先使用 ripgrep (rg) 进行搜索，如果 rg 不可用则 fallback 到 Python re 模块。

工作流程:
    1. LLM 调用 search_codebase(queries=["def foo", "class Bar.*:"], ...)
    2. 检查 rg 是否可用，优先用 rg 搜索（-i 大小写不敏感，-C 2 上下文行）
    3. rg 不可用或失败时，fallback 到 Python re 搜索（re.IGNORECASE）
    4. 每个匹配返回 {file, line_number, line_content, context}
    5. 单查询最多返回 50 个匹配，单文件最多 20 行
    6. 单行超过 2000 字符时截断（对标 Cline MAX_LINE_CHARS）
    7. 总输出超过 48000 字符时，使用 head+tail 截断策略（对标 Cline MAX_SEARCH_OUTPUT_CHARS）

安全设计:
    - 跳过常见大目录（.git/node_modules/__pycache__/.venv）
    - 单查询匹配上限 50 个，单文件上限 20 行
    - 仅读取文本文件（UTF-8 解码失败则跳过）

对标 Cline:
    - sdk/packages/core/src/extensions/tools/executors/search.ts
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from agent.abort import AbortedError
from agent.tools.base import BaseTool
from agent.tools.constants import (
    MAX_LINE_CHARS,
    MAX_SEARCH_MATCHES_PER_FILE,
    MAX_SEARCH_MATCHES_PER_QUERY,
)
from agent.tools.truncate import truncate_output
from agent.types import AgentToolContext, AgentToolResult


class SearchCodebaseTool(BaseTool):
    """正则代码搜索工具 — 对标 Cline createSearchExecutor

    参数:
        queries: 正则表达式数组（必填）

    构造函数:
        working_dir: 工作目录（可选，默认当前目录）
    """

    # Phase 31.5: 常量统一到 agent.tools.constants — 对标 Cline output-limits.ts
    # 保留类属性作为向后兼容别名，值来自 constants 模块
    _MAX_MATCHES_PER_QUERY = MAX_SEARCH_MATCHES_PER_QUERY
    _MAX_MATCHES_PER_FILE = MAX_SEARCH_MATCHES_PER_FILE

    # 对标 Cline output-limits.ts — 搜索输出字符上限与单行字符上限
    # Cline: MAX_SEARCH_OUTPUT_CHARS = 48_000, MAX_LINE_CHARS = 2_000
    _MAX_OUTPUT_CHARS = 48000
    # P2-7: 引用 constants.MAX_LINE_CHARS 全局常量
    _MAX_LINE_CHARS = MAX_LINE_CHARS

    # 对标 Cline search.ts contextLines — 每条匹配前后各 2 行上下文
    _CONTEXT_LINES = 2

    # rg 子进程超时秒数 — 对标 Cline searchWithRipgrep timeoutMs=5000
    _RG_TIMEOUT_SECONDS = 10

    # 跳过的目录名
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

    # 跳过的文件扩展名（二进制或非文本文件）
    _SKIP_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".zip", ".tar", ".gz", ".rar", ".7z",
        ".exe", ".dll", ".so", ".dylib",
        ".pyc", ".pyo", ".class",
        ".mp3", ".mp4", ".avi", ".mov",
        ".db", ".sqlite", ".sqlite3",
    }

    # rg 可用性缓存（None=未检测，True/False=已检测）— 对标 Cline rgAvailable
    _rg_available: bool | None = None

    def __init__(self, working_dir: str | None = None) -> None:
        """初始化代码搜索工具

        Args:
            working_dir: 工作目录，默认为当前目录
        """
        self._working_dir = working_dir or os.getcwd()

    @property
    def name(self) -> str:
        return "search_codebase"

    @property
    def description(self) -> str:
        return (
            "在代码库中执行正则表达式搜索。支持多个并行查询。"
            "大小写不敏感，每条匹配包含 2 行上下文。"
            "参数: queries(必填): 正则表达式数组，每个查询独立搜索"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "正则表达式数组，每个查询独立搜索",
                },
            },
            "required": ["queries"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行正则代码搜索 — 对标 Cline createSearchExecutor.execute()"""
        queries = input.get("queries", [])

        if not queries:
            return AgentToolResult(
                output={"error": "queries 不能为空"},
                is_error=True,
            )

        # 确定工作目录 — 优先从 context.snapshot 获取，其次用构造函数传入的
        working_dir = self._working_dir
        if context.snapshot is not None and context.snapshot.conversation_id:
            # 保留构造函数传入的 working_dir，不依赖 snapshot
            pass

        root = Path(working_dir)
        if not root.exists() or not root.is_dir():
            return AgentToolResult(
                output={"error": f"工作目录不存在或不是目录: {working_dir}"},
                is_error=True,
            )

        # 预编译正则表达式 — 添加 re.IGNORECASE 对标 Cline -i
        compiled: list[tuple[str, re.Pattern[str]]] = []
        for q in queries:
            try:
                pattern = re.compile(q, re.IGNORECASE)
                compiled.append((q, pattern))
            except re.error as e:
                return AgentToolResult(
                    output={
                        "error": f"正则表达式编译失败: {q}",
                        "detail": str(e),
                    },
                    is_error=True,
                )

        # 检查 rg 可用性 — 对标 Cline checkRipgrepAvailable()
        rg_available = await self._check_rg_available()

        # 收集文件列表（用于 fallback 搜索和统计）
        # rg 路径不需要预收集文件，但 fallback 需要
        files = self._collect_files(root) if not rg_available else []
        total_files_searched = len(files)

        # 对每个查询执行搜索
        all_results: list[dict[str, Any]] = []
        for query_str, pattern in compiled:
            # Phase 28.2: 每个查询开始前检查中止信号
            self._check_aborted(context)

            matches: list[dict[str, Any]] | None = None

            # 优先使用 rg 搜索 — 对标 Cline searchWithRipgrep
            if rg_available:
                matches = await self._search_with_ripgrep(
                    query_str, working_dir, context
                )

            # rg 不可用或失败时，fallback 到 Python re — 保留原有搜索逻辑
            if matches is None:
                if not files:
                    files = self._collect_files(root)
                    total_files_searched = len(files)
                matches = self._search_in_files(query_str, pattern, files)

            all_results.append({
                "query": query_str,
                "match_count": len(matches),
                "matches": matches,
            })

        total_matches = sum(r["match_count"] for r in all_results)

        # 格式化输出为字符串 — 对标 Cline 格式化逻辑
        output_text = self._format_results(all_results, total_files_searched)

        # 应用单行截断 — 对标 Cline MAX_LINE_CHARS
        output_text = self._truncate_lines(output_text)

        # 应用总输出截断 — 对标 Cline capSearchOutput
        output_text = self._cap_output(output_text)

        return AgentToolResult(
            output=output_text,
            metadata={
                "queries_count": len(queries),
                "total_matches": total_matches,
                "files_searched": total_files_searched,
                "working_dir": working_dir,
                "rg_used": rg_available,
            },
        )

    async def _check_rg_available(self) -> bool:
        """检查 ripgrep 是否可用 — 对标 Cline checkRipgrepAvailable()

        结果缓存到类属性 _rg_available，避免每次搜索都检测。
        使用 asyncio.create_subprocess_exec 异步执行 rg --version。
        """
        if SearchCodebaseTool._rg_available is not None:
            return SearchCodebaseTool._rg_available

        try:
            process = await asyncio.create_subprocess_exec(
                "rg", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
                SearchCodebaseTool._rg_available = process.returncode == 0
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                SearchCodebaseTool._rg_available = False
        except (FileNotFoundError, OSError):
            # rg 不在 PATH 中
            SearchCodebaseTool._rg_available = False

        return SearchCodebaseTool._rg_available

    async def _search_with_ripgrep(
        self,
        query: str,
        cwd: str,
        context: AgentToolContext,
    ) -> list[dict[str, Any]] | None:
        """使用 ripgrep 搜索 — 对标 Cline searchWithRipgrep()

        使用 rg --json -i -C 2 进行搜索，解析 JSON 输出。
        返回 None 表示 rg 执行失败，调用方应 fallback 到 Python re。
        返回空列表表示 rg 执行成功但无匹配。
        """
        # 构建 rg 命令 — 对标 Cline:
        #   --json: 每行一个 JSON 对象，便于解析
        #   --context=2: 每条匹配前后各 2 行上下文
        #   -i: 大小写不敏感
        cmd = [
            "rg",
            "--json",
            f"--context={self._CONTEXT_LINES}",
            "-i",
            query,
            cwd,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError):
            return None

        # 使用 abort-aware wait — 对标 exec_tool._wait_process_with_abort
        # 将 communicate / abort_signal.wait / timeout 三者组合等待
        try:
            stdout, _ = await self._wait_process_with_abort(
                process, context, self._RG_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            # rg 超时，终止进程并返回 None 触发 fallback
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            return None
        except AbortedError:
            # abort 时 kill 进程，向上抛出让 runtime 处理中止流程
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            raise

        # rg 退出码: 0=有匹配, 1=无匹配, 2=错误
        # 非 0/1 退出码表示 rg 出错（如无效正则），返回 None 触发 fallback
        if process.returncode not in (0, 1):
            return None

        return self._parse_rg_json_output(
            stdout.decode("utf-8", errors="replace")
        )

    def _parse_rg_json_output(
        self,
        output: str,
    ) -> list[dict[str, Any]] | None:
        """解析 rg --json 输出 — 对标 Cline searchWithRipgrep JSON 解析

        rg --json 每行输出一个 JSON 对象，type 字段区分:
            - match: 匹配行（含 submatches 数组）
            - context: 上下文行
            - summary/end: 搜索摘要和结束标记（忽略）

        每个匹配的 context 字段收集其后的 context 行。
        """
        matches: list[dict[str, Any]] = []
        match_count = 0

        for line in output.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # 跳过无法解析的行
                continue

            msg_type = data.get("type")

            if msg_type == "match":
                # 匹配行 — 对标 Cline match 分支
                match_data = data.get("data", {})
                submatches = match_data.get("submatches", [])
                if not submatches:
                    continue
                if match_count >= self._MAX_MATCHES_PER_QUERY:
                    break

                submatch = submatches[0]
                # rg JSON 中行内容字段可能是 lines 或 line（不同版本）
                line_text = (
                    match_data.get("lines", {}).get("text", "")
                    or match_data.get("line", {}).get("text", "")
                )
                matches.append({
                    "file": match_data.get("path", {}).get("text", ""),
                    "line_number": match_data.get("line_number", 0),
                    "line_content": line_text.rstrip("\n"),
                    "column": (submatch.get("start", 0)) + 1,
                    "context": [],
                })
                match_count += 1

            elif msg_type == "context" and matches:
                # 上下文行 — 对标 Cline context 分支
                # 追加到最近一条匹配的 context 列表
                context_data = data.get("data", {})
                last_match = matches[-1]
                ctx_text = (
                    context_data.get("lines", {}).get("text", "")
                    or context_data.get("line", {}).get("text", "")
                )
                last_match["context"].append({
                    "line_number": context_data.get("line_number", 0),
                    "content": ctx_text.rstrip("\n"),
                    "is_match": False,
                })

        return matches

    async def _wait_process_with_abort(
        self,
        process: asyncio.subprocess.Process,
        context: AgentToolContext | None,
        timeout: int,
    ) -> tuple[bytes, bytes]:
        """等待进程完成 — 对标 exec_tool._wait_process_with_abort

        将 process.communicate() 与 abort_signal.wait() 组合等待，
        任一先完成都立即返回:
            - communicate 先完成: 正常返回 stdout/stderr
            - abort_signal 先完成: 终止进程并抛出 AbortedError
            - 都未在 timeout 内完成: 抛出 asyncio.TimeoutError
        """
        comm_task = asyncio.ensure_future(process.communicate())

        # 若无 abort_signal，退化为带超时的 communicate
        signal = getattr(context, "abort_signal", None) if context else None
        if signal is None:
            stdout, stderr = await asyncio.wait_for(comm_task, timeout=timeout)
            return stdout, stderr

        abort_task = asyncio.ensure_future(signal.wait())

        try:
            done, pending = await asyncio.wait(
                {comm_task, abort_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout,
            )

            # 超时
            if not done:
                raise asyncio.TimeoutError()

            # abort 先触发: 终止进程并抛出
            if abort_task in done:
                comm_task.cancel()
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except Exception:
                    pass
                raise AbortedError("aborted by user")

            # communicate 正常完成
            abort_task.cancel()
            stdout, stderr = comm_task.result()
            return stdout, stderr

        except asyncio.CancelledError:
            comm_task.cancel()
            abort_task.cancel()
            raise

    def _collect_files(self, root: Path) -> list[Path]:
        """收集工作目录下所有可搜索的文本文件

        跳过 _SKIP_DIRS 中的目录和 _SKIP_EXTENSIONS 中的文件扩展名。
        """
        files: list[Path] = []
        for path in root.rglob("*"):
            # 跳过目录
            if path.is_dir():
                continue

            # 检查是否在跳过目录中
            if any(part in self._SKIP_DIRS for part in path.parts):
                continue

            # 跳过非文本文件扩展名
            if path.suffix.lower() in self._SKIP_EXTENSIONS:
                continue

            files.append(path)

        return files

    def _search_in_files(
        self,
        query_str: str,
        pattern: re.Pattern[str],
        files: list[Path],
    ) -> list[dict[str, Any]]:
        """在文件列表中搜索正则匹配 — Python re fallback

        保留原有搜索逻辑，新增上下文行收集（对标 Cline contextLines）。
        单查询最多返回 _MAX_MATCHES_PER_QUERY 个匹配，单文件最多 _MAX_MATCHES_PER_FILE 行。
        """
        matches: list[dict[str, Any]] = []
        match_count = 0

        for file_path in files:
            if match_count >= self._MAX_MATCHES_PER_QUERY:
                break

            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError, OSError):
                # 跳过二进制文件或无权限文件
                continue

            lines = content.splitlines()
            file_matches = 0

            for line_idx, line in enumerate(lines):
                if match_count >= self._MAX_MATCHES_PER_QUERY:
                    break
                if file_matches >= self._MAX_MATCHES_PER_FILE:
                    break

                if pattern.search(line):
                    # 收集上下文行 — 对标 Cline contextLines
                    # 取匹配行前后各 _CONTEXT_LINES 行
                    context_start = max(0, line_idx - self._CONTEXT_LINES)
                    context_end = min(len(lines) - 1, line_idx + self._CONTEXT_LINES)
                    context_lines: list[dict[str, Any]] = []

                    for i in range(context_start, context_end + 1):
                        if i == line_idx:
                            # 跳过匹配行本身，只收集上下文
                            continue
                        context_lines.append({
                            "line_number": i + 1,
                            "content": lines[i],
                            "is_match": False,
                        })

                    matches.append({
                        "file": str(file_path),
                        "line_number": line_idx + 1,
                        "line_content": line,
                        "column": 1,
                        "context": context_lines,
                    })
                    match_count += 1
                    file_matches += 1

        return matches

    def _format_results(
        self,
        results: list[dict[str, Any]],
        files_searched: int,
    ) -> str:
        """格式化搜索结果为字符串 — 对标 Cline 格式化逻辑

        输出格式:
            Found N results for pattern: query
            Searched M files.

            file:line:column
              line_num: context line before
            > line_num: match line
              line_num: context line after

            file:line:column
            ...

            (Showing first N results. Refine your search for more specific results.)
        """
        if not results:
            return f"No results found.\nSearched {files_searched} files."

        parts: list[str] = []

        for result in results:
            query = result["query"]
            matches = result["matches"]
            count = result["match_count"]

            if count == 0:
                parts.append(f"No results found for pattern: {query}")
                parts.append("")
                continue

            parts.append(
                f"Found {count} result{'s' if count != 1 else ''} "
                f"for pattern: {query}"
            )
            if files_searched > 0:
                parts.append(f"Searched {files_searched} files.")
            parts.append("")

            for match in matches:
                file_path = match["file"]
                line_num = match["line_number"]
                column = match.get("column", 1)
                line_content = match["line_content"]
                context_lines = match.get("context", [])

                parts.append(f"{file_path}:{line_num}:{column}")

                # 输出匹配行前的上下文行
                for ctx in context_lines:
                    if ctx["line_number"] < line_num:
                        parts.append(f"  {ctx['line_number']}: {ctx['content']}")

                # 输出匹配行（> 标记对标 Cline）
                parts.append(f"> {line_num}: {line_content}")

                # 输出匹配行后的上下文行
                for ctx in context_lines:
                    if ctx["line_number"] > line_num:
                        parts.append(f"  {ctx['line_number']}: {ctx['content']}")

                parts.append("")

            if count >= self._MAX_MATCHES_PER_QUERY:
                parts.append(
                    f"(Showing first {self._MAX_MATCHES_PER_QUERY} results. "
                    "Refine your search for more specific results.)"
                )
                parts.append("")

        return "\n".join(parts).strip()

    def _truncate_lines(self, text: str) -> str:
        """单行截断 — 对标 Cline MAX_LINE_CHARS

        单行超过 _MAX_LINE_CHARS 字符时截断，添加截断标记。
        防止压缩或 minified 文件的单行撑爆上下文。
        """
        max_chars = self._MAX_LINE_CHARS
        lines = text.splitlines()
        result: list[str] = []

        for line in lines:
            if len(line) > max_chars:
                result.append(line[:max_chars] + " ... [line truncated]")
            else:
                result.append(line)

        return "\n".join(result)

    def _cap_output(self, text: str) -> str:
        """总输出截断 — 对标 Cline capSearchOutput

        总输出超过 _MAX_OUTPUT_CHARS 字符时，使用 head+tail 截断策略:
        前 _MAX_OUTPUT_CHARS/2 + 后 _MAX_OUTPUT_CHARS/2，中间省略。

        对标 Cline search.ts capSearchOutput():
            长匹配的上下文行可能超出单查询上限，保留 head（最早匹配+结果计数）
            和 tail（refine 提示），中间省略并提示缩小 pattern。

        P2-8: 引用公共 truncate_output 截断函数，统一截断策略与标记格式。
        """
        return truncate_output(text, self._MAX_OUTPUT_CHARS)
