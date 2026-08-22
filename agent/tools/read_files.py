# -*- coding: utf-8 -*-
"""批量文件读取工具 — 对标 Cline ReadFilesInputSchema

支持一次读取多个文件，每个文件可指定行范围。
相比单文件 file_read:
    - 一次可读多个文件（减少 tool_call 次数）
    - 支持 start_line/end_line 行范围
    - 自动检测 UTF-8 编码
    - 结构化数组输出，便于 LLM 解析

工作流程:
    1. LLM 调用 read_files(files=[{path: "...", start_line: 1, end_line: 100}, ...])
    2. 工具按顺序读取每个文件
    3. 对每个文件应用行范围（可选）
    4. 返回 {results: [{path, content, lines, start_line, end_line}, ...]}

安全设计:
    - 单次最多 10 个文件
    - 单文件输出上限 16000 字符
    - 拒绝读取二进制文件

对标 Cline:
    - sdk/packages/core/src/extensions/tools/schemas.ts ReadFilesInputSchema
    - sdk/packages/core/src/extensions/tools/schemas.ts ReadFileRequestSchema
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool
from agent.tools.constants import MAX_LINE_CHARS
from agent.tools.truncate import truncate_output
from agent.types import AgentToolContext, AgentToolResult


class ReadFilesTool(BaseTool):
    """批量文件读取工具 — 对标 Cline read_files tool

    参数:
        files: 文件读取请求数组（必填，最多 10 个）
               每项含:
               - path: 文件路径（必填，支持相对项目根目录或绝对路径）
               - start_line: 起始行（1-based，可选，默认 1）
               - end_line: 结束行（1-based，可选，默认到文件末尾）

    构造函数:
        working_dir: 工作目录（可选，用于解析相对路径，默认当前目录）
    """

    # 单次最多文件数 — 防止 LLM 滥用
    _MAX_FILES = 10

    # 层 1: 单文件行数上限 — 对标 Cline MAX_READ_LINES (output-limits.ts L41)
    # 超过则 head 1000 + tail 1000，中间省略
    _MAX_LINES_PER_FILE = 2000

    # 层 2: 单行字符上限 — 对标 Cline MAX_LINE_CHARS (output-limits.ts L44)
    # 超过则截断并追加 [line truncated] 标记
    # P2-7: 引用 constants.MAX_LINE_CHARS 全局常量
    _MAX_LINE_CHARS = MAX_LINE_CHARS

    # 层 3: 单文件输出字符上限 — 对标 Cline MAX_READ_OUTPUT_CHARS (output-limits.ts L47)
    # 超过则 head 24000 + tail 24000
    _MAX_OUTPUT_CHARS_PER_FILE = 48000

    # 向后兼容别名 — 值对齐 Cline (原 16000，现 48000)
    _MAX_CHARS_PER_FILE = _MAX_OUTPUT_CHARS_PER_FILE

    # P2 增强：大文件预检查阈值 — 超过此大小提前警告（10MB）
    _LARGE_FILE_THRESHOLD = 10 * 1024 * 1024

    @property
    def name(self) -> str:
        return "read_files"

    def __init__(self, working_dir: str | None = None) -> None:
        """初始化批量文件读取工具

        Args:
            working_dir: 工作目录，用于解析相对路径，默认为当前目录
        """
        self._working_dir = working_dir or os.getcwd()

    @property
    def description(self) -> str:
        return (
            "批量读取文件内容。支持一次读取多个文件，每个文件可指定行范围。"
            "相对路径会基于工作目录解析。"
            "参数: files(必填): 文件读取请求数组，每项必须包含 path(必填)，例如 [{\"path\": \"README.md\"}, {\"path\": \"main.py\", \"start_line\": 1, \"end_line\": 50}]，最多 10 个文件"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "文件路径（相对工作目录或绝对路径）",
                            },
                            "start_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "起始行（1-based，可选，默认 1）",
                            },
                            "end_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "结束行（1-based，可选，默认到文件末尾）",
                            },
                        },
                        "required": ["path"],
                    },
                    "description": "文件读取请求数组",
                    "maxItems": 10,
                },
            },
            "required": ["files"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行批量文件读取 — 对标 Cline read_files.execute()

        并行读取 — 对标 Cline Promise.all:
            多个文件用 asyncio.gather 并发读取，IO 等待重叠，减少总耗时。
            单文件 _read_single_file 改为 async，内部用 asyncio.to_thread
            包装阻塞 IO，真正实现并行。
        """
        files = input.get("files", [])

        if not files:
            return AgentToolResult(
                output={"error": "files 不能为空"},
                is_error=True,
            )

        if len(files) > self._MAX_FILES:
            return AgentToolResult(
                output={
                    "error": f"文件数超过上限 {self._MAX_FILES}",
                    "received": len(files),
                },
                is_error=True,
            )

        # Phase 28.2: 并行读取前检查中止信号
        self._check_aborted(context)

        # 并行读取所有文件 — 对标 Cline Promise.all
        # return_exceptions=True 确保单个文件异常不影响其他文件
        tasks = [
            self._read_single_file(req, idx)
            for idx, req in enumerate(files)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常：_read_single_file 内部已 catch 大部分异常并返回 error dict，
        # 此处兜底捕获未预期异常（如 asyncio.CancelledError 之外的系统异常）
        results: list[dict[str, Any]] = []
        for idx, result in enumerate(raw_results):
            if isinstance(result, Exception):
                results.append({
                    "index": idx,
                    "path": files[idx].get("path", "") if isinstance(files[idx], dict) else "",
                    "error": f"读取失败: {result}",
                })
            else:
                results.append(result)

        return AgentToolResult(
            output={"results": results},
            metadata={
                "total_files": len(files),
                "succeeded": sum(1 for r in results if "error" not in r),
                "failed": sum(1 for r in results if "error" in r),
            },
        )

    async def _read_single_file(self, req: dict[str, Any], index: int) -> dict[str, Any]:
        """读取单个文件 — 对标 Cline ReadFileRequestSchema 处理

        3 层截断策略 — 对标 Cline output-limits.ts:
            层 1: 单文件最多 _MAX_LINES_PER_FILE 行（超过则 head + tail）
                  对标 Cline MAX_READ_LINES (output-limits.ts L41)
            层 2: 单行最多 _MAX_LINE_CHARS 字符（超过则截断并标记）
                  对标 Cline MAX_LINE_CHARS (output-limits.ts L44)
            层 3: 单文件输出最多 _MAX_OUTPUT_CHARS_PER_FILE 字符（超过则 head + tail）
                  对标 Cline MAX_READ_OUTPUT_CHARS (output-limits.ts L47)

        并行读取:
            用 asyncio.to_thread 包装阻塞 IO，支持 asyncio.gather 并行调度。
        """
        path_str = req.get("path", "")
        raw_start_line = req.get("start_line")
        raw_end_line = req.get("end_line")
        start_line = raw_start_line or 1
        end_line = raw_end_line

        if not path_str:
            return {
                "index": index,
                "path": "",
                "error": "path 不能为空",
            }

        # P2 增强：行号参数校验（offset 不能为负数，limit 不能为 0）
        if raw_start_line is not None and raw_start_line < 1:
            return {
                "index": index,
                "path": path_str,
                "error": f"start_line 不能为负数或零: {raw_start_line}",
            }
        if raw_end_line is not None and raw_end_line < 1:
            return {
                "index": index,
                "path": path_str,
                "error": f"end_line 不能为负数或零: {raw_end_line}",
            }
        if (
            raw_start_line is not None
            and raw_end_line is not None
            and raw_end_line < raw_start_line
        ):
            return {
                "index": index,
                "path": path_str,
                "error": f"end_line ({raw_end_line}) 不能小于 start_line ({raw_start_line})",
            }

        path = Path(path_str)
        # 相对路径基于工作目录解析，避免依赖运行时当前目录
        if not path.is_absolute():
            path = Path(self._working_dir) / path

        if not path.exists():
            return {
                "index": index,
                "path": path_str,
                "error": f"文件不存在: {path_str}",
            }

        if not path.is_file():
            return {
                "index": index,
                "path": path_str,
                "error": f"不是文件: {path_str}",
            }

        # P2 增强：文件大小预检查 — 超过阈值时提前警告
        size_warning = ""
        try:
            file_size = path.stat().st_size
            if file_size > self._LARGE_FILE_THRESHOLD:
                size_mb = file_size / (1024 * 1024)
                size_warning = (
                    f"文件较大 ({size_mb:.1f}MB)，建议使用 start_line/end_line 分段读取"
                )
        except OSError:
            # 获取文件大小失败不影响后续读取
            pass

        try:
            # 用 asyncio.to_thread 包装阻塞 IO — 支持并行调度
            raw = await asyncio.to_thread(path.read_bytes)
            if not raw:
                return {
                    "index": index,
                    "path": path_str,
                    "content": "",
                    "lines": 0,
                    "start_line": 0,
                    "end_line": 0,
                    "note": "空文件",
                }

            # 尝试 UTF-8 解码
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return {
                    "index": index,
                    "path": path_str,
                    "error": f"无法读取二进制文件: {path_str}",
                }

            # 行范围读取
            all_lines = text.splitlines()
            total = len(all_lines)

            if start_line < 1:
                start_line = 1
            if start_line > total:
                return {
                    "index": index,
                    "path": path_str,
                    "error": f"start_line {start_line} 超出文件总行数 ({total})",
                }

            start_idx = start_line - 1
            end_idx = end_line if end_line else total
            end_idx = min(end_idx, total)

            # 构建 (行号, 行内容) 列表，保留实际行号便于 cat -n 输出
            numbered_lines: list[tuple[int, str]] = [
                (start_line + i, all_lines[start_idx + i])
                for i in range(end_idx - start_idx)
            ]

            # 层 1: 行数截断 — 对标 Cline MAX_READ_LINES
            # 超过 _MAX_LINES_PER_FILE 行时，取 head 1000 + tail 1000，中间省略
            lines_truncated = False
            omitted_lines = 0
            if len(numbered_lines) > self._MAX_LINES_PER_FILE:
                half = self._MAX_LINES_PER_FILE // 2  # 1000
                head_part = numbered_lines[:half]
                tail_part = numbered_lines[-half:]
                omitted_lines = len(numbered_lines) - self._MAX_LINES_PER_FILE
                numbered_lines = head_part + tail_part
                lines_truncated = True

            # 层 2: 单行字符截断 — 对标 Cline MAX_LINE_CHARS
            # 超过 _MAX_LINE_CHARS 字符时，截断并追加 [line truncated] 标记
            processed_lines: list[tuple[int, str]] = []
            for line_num, line in numbered_lines:
                if len(line) > self._MAX_LINE_CHARS:
                    processed_lines.append(
                        (line_num, line[:self._MAX_LINE_CHARS] + " [line truncated]")
                    )
                else:
                    processed_lines.append((line_num, line))

            # Phase 3.2 (G1.6): 输出 cat -n 风格行号 — 对标 Cline file-read.ts L161-170
            # 行号右对齐，宽度按最大行号位数计算，格式 "{行号} | {行内容}"
            # 行号使用实际行号，不是从 1 开始
            if processed_lines:
                max_line_num = processed_lines[-1][0]
                max_width = len(str(max_line_num))
                lines_with_num = [
                    f"{str(ln).rjust(max_width)} | {line}"
                    for ln, line in processed_lines
                ]
                content = "\n".join(lines_with_num)
            else:
                content = ""

            # 层 3: 总字符截断 — 对标 Cline MAX_READ_OUTPUT_CHARS
            # 超过 _MAX_OUTPUT_CHARS_PER_FILE 字符时，head 24000 + tail 24000
            # P2-8: 引用公共 truncate_output 截断函数
            char_truncated = False
            if len(content) > self._MAX_OUTPUT_CHARS_PER_FILE:
                content = truncate_output(content, self._MAX_OUTPUT_CHARS_PER_FILE)
                char_truncated = True

            result: dict[str, Any] = {
                "index": index,
                "path": path_str,
                "content": content,
                "lines": total,
                "start_line": start_line,
                "end_line": end_idx,
            }

            # P2 增强：附加大文件警告
            if size_warning:
                result["warning"] = size_warning

            if lines_truncated:
                half = self._MAX_LINES_PER_FILE // 2
                result["note"] = (
                    f"行数已截断：省略 {omitted_lines} 行"
                    f"（显示前 {half} 行和后 {half} 行）"
                )
            if char_truncated:
                result["note"] = f"内容已截断到 {self._MAX_OUTPUT_CHARS_PER_FILE} 字符"

            if end_idx < total:
                result["has_more"] = True
                result["next_start_line"] = end_idx + 1

            return result

        except PermissionError as e:
            return {
                "index": index,
                "path": path_str,
                "error": f"权限不足: {e}",
            }
        except Exception as e:
            return {
                "index": index,
                "path": path_str,
                "error": f"读取失败: {e}",
            }
