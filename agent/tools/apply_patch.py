# -*- coding: utf-8 -*-
"""diff 补丁工具 — 对标 Cline createApplyPatchTool

通过 canonical apply_patch 格式修改文件，支持:
    - Update File: 行级替换（按 -/+ 前缀的行做替换）
    - Add File: 新建文件
    - Delete File: 删除文件
    - Move File: 移动/重命名文件 — P2-5 新增

补丁格式:
    *** Begin Patch
    *** Update File: path/to/file
    @@ context line
    -old line
    +new line
    *** Add File: path/to/new_file
    +new content line 1
    +new content line 2
    *** Delete File: path/to/file
    *** Move File: path/to/source -> path/to/destination
    *** End Patch

工作流程（两阶段提交，对标 Cline computePatchChanges + applyChanges）:
    1. LLM 生成 apply_patch 格式的补丁文本
    2. 工具解析补丁块（*** Update File / *** Add File / *** Delete File / *** Move File）
    3. 阶段一（compute）：遍历所有补丁块，读取原文件、计算新内容，收集为 changes 列表。
       任何块解析失败立即抛出 ValueError，此时零文件被修改（原子性回滚）。
    4. 阶段二（apply）：遍历 changes 列表，批量写盘（write/unlink/rename）。
    5. 返回 {results: [{path, operation, success}]}

核心契约：只要有一个 block 解析失败，整个 patch 不产生任何磁盘副作用。

简化实现说明:
    - 支持 Update File（行级替换）、Add File（新建）、Delete File（删除）、Move File（移动/重命名）
    - 不支持完整的 diff3 算法
    - @@ 开头的行为上下文行（不修改）
    - - 开头的行为要删除的行
    - + 开头的行为要新增的行

对标 Cline:
    - sdk/packages/core/src/extensions/tools/apply-patch-tool.ts
    - sdk/packages/core/src/extensions/tools/executors/apply-patch.ts（computePatchChanges/applyChanges）
"""

from __future__ import annotations

import logging
import os
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from agent.tools.base import BaseTool
from agent.types import AgentToolContext, AgentToolResult

logger = logging.getLogger(__name__)


class PatchApplyError(ValueError):
    """patch 应用失败异常 — Stage 12.2 (G4.5) 新增，对标 Cline DiffError

    携带详细的失败位置信息，便于 LLM 看到错误后修正 patch 重试。
    继承自 ValueError 以保持与现有 _apply_block 错误处理兼容。

    Attributes:
        file_path: 失败的文件路径
        line_num: 失败位置的大致行号（1-based，0 表示无法定位）
        expected: 期望的行内容（patch 中的 - 行）
        actual: 实际的行内容（文件中的对应行）
        chunk_index: 失败的 chunk 索引
    """

    def __init__(
        self,
        message: str,
        *,
        file_path: str = "",
        line_num: int = 0,
        expected: str = "",
        actual: str = "",
        chunk_index: int = -1,
    ) -> None:
        self.file_path = file_path
        self.line_num = line_num
        self.expected = expected
        self.actual = actual
        self.chunk_index = chunk_index
        detail_lines = [message]
        if file_path:
            detail_lines.append(f"  file: {file_path}")
        if chunk_index >= 0:
            detail_lines.append(f"  chunk #{chunk_index}")
        if line_num > 0:
            detail_lines.append(f"  line {line_num}")
        if expected:
            detail_lines.append(f"  expected: {expected!r}")
        if actual:
            detail_lines.append(f"  actual:   {actual!r}")
        super().__init__("\n".join(detail_lines))


def _detect_line_ending(text: str) -> str:
    """检测文本的主换行符（\\r\\n 或 \\n）"""
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _normalize_for_edit(text: str, line_ending: str) -> str:
    """将文本统一为 \\n 处理，便于 diff 匹配"""
    if line_ending == "\r\n":
        return text.replace("\r\n", "\n")
    return text


def _restore_line_ending(text: str, line_ending: str) -> str:
    """编辑完成后还原为原始换行符"""
    if line_ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def _read_text_unicode(path: Path) -> str:
    """以 Unicode 字符读取文件 — Stage 12.2 (G4.1) 新增

    对标 Cline 按 Unicode 字符读取（非字节）：
        - 使用 utf-8-sig 自动剥离 BOM
        - 失败时抛 UnicodeDecodeError（上层捕获后转为 PatchApplyError）

    Args:
        path: 文件路径

    Returns:
        文件文本内容（已剥离 BOM）

    Raises:
        UnicodeDecodeError: 文件非 UTF-8 编码（如二进制文件）
    """
    return path.read_text(encoding="utf-8-sig")


def _match_context(context_line: str, file_line: str) -> bool:
    """上下文行模糊匹配 — Stage 12.2 (G4.2) 新增，对标 Cline 模糊匹配

    匹配优先级（任一命中即视为匹配）：
        1. 精确匹配（保留原逻辑）
        2. 忽略尾部空白（rstrip）
        3. 忽略行首缩进差异（tab vs space，用 expandtabs）
        4. Unicode 标点归一化后匹配 — P2-4 新增

    Args:
        context_line: patch 中的上下文行
        file_line: 文件中的对应行

    Returns:
        是否匹配
    """
    # 1. 精确匹配
    if context_line == file_line:
        return True
    # 2. 忽略尾部空白
    if context_line.rstrip() == file_line.rstrip():
        return True
    # 3. 忽略 tab/space 缩进差异
    if context_line.expandtabs() == file_line.expandtabs():
        return True
    # 4. P2-4: Unicode 标点归一化后匹配
    if _normalize_unicode_punctuation(context_line) == _normalize_unicode_punctuation(file_line):
        return True
    return False


def _normalize_unicode_punctuation(text: str) -> str:
    """Unicode 标点归一化 — P2-4 新增

    将 Unicode 标点差异归一化，使全角/半角、不同引号/破折号等标点形式可互相匹配。
    归一化规则:
        1. NFKC 归一化: 全角字符 → 半角（如 Ａ→A, １→1, ：→:）
        2. 引号归一化: " " ' ' → " '
        3. 破折号归一化: — – → -
        4. 省略号归一化: … → ...

    Args:
        text: 原始文本

    Returns:
        归一化后的文本
    """
    # 1. NFKC 归一化 — 全角转半角
    result = unicodedata.normalize("NFKC", text)
    # 2. 引号归一化
    result = result.translate(str.maketrans({
        "\u201c": '"',  # 左双引号 "
        "\u201d": '"',  # 右双引号 "
        "\u2018": "'",  # 左单引号 '
        "\u2019": "'",  # 右单引号 '
        "\u201f": '"',  # 反双引号 ‟
        "\u201b": "'",  # 反单引号 ‛
    }))
    # 3. 破折号归一化
    result = result.translate(str.maketrans({
        "\u2014": "-",  # 长破折号 —
        "\u2013": "-",  # 短破折号 –
    }))
    # 4. 省略号归一化
    result = result.replace("\u2026", "...")
    return result


def _levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串的 Levenshtein 编辑距离 — P2-4 新增，对标 Cline levenshteinDistance

    使用动态规划计算将 s1 转换为 s2 所需的最少单字符编辑（插入/删除/替换）次数。

    Args:
        s1: 第一个字符串
        s2: 第二个字符串

    Returns:
        编辑距离（非负整数）
    """
    rows = len(s2) + 1
    cols = len(s1) + 1
    # 初始化矩阵
    matrix = list(range(cols))
    for i in range(1, rows):
        prev = matrix[0]
        matrix[0] = i
        for j in range(1, cols):
            cur = matrix[j]
            if s2[i - 1] == s1[j - 1]:
                matrix[j] = prev
            else:
                matrix[j] = 1 + min(prev, matrix[j - 1], cur)
            prev = cur
    return matrix[cols - 1]


def _calculate_similarity(s1: str, s2: str) -> float:
    """计算两个字符串的相似度 — P2-4 新增，对标 Cline calculateSimilarity

    相似度 = (较长字符串长度 - 编辑距离) / 较长字符串长度
    返回值范围 [0.0, 1.0]，1.0 表示完全相同。

    Args:
        s1: 第一个字符串
        s2: 第二个字符串

    Returns:
        相似度（0.0 ~ 1.0）
    """
    longer = s1 if len(s1) > len(s2) else s2
    shorter = s2 if len(s1) > len(s2) else s1
    if len(longer) == 0:
        return 1.0
    edit_distance = _levenshtein_distance(shorter, longer)
    return (len(longer) - edit_distance) / len(longer)


# P2-4: Levenshtein 回退匹配的相似度阈值 — 对标 Cline findContext 模糊匹配
_LEVENSHTEIN_SIMILARITY_THRESHOLD = 0.66


class ApplyPatchTool(BaseTool):
    """diff 补丁工具 — 对标 Cline createApplyPatchTool

    参数:
        input: 补丁内容（必填，apply_patch 格式）
        working_dir: 工作目录（可选，用于解析相对路径，默认当前目录）
    """

    def __init__(self, working_dir: str | None = None) -> None:
        self._working_dir = working_dir or os.getcwd()

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "通过 canonical apply_patch 格式修改文件。input 字段为补丁内容，格式: "
            "*** Begin Patch / *** Update File: path / @@ context / -old / +new / "
            "*** Add File: path / *** Move File: source -> destination / *** End Patch。"
            "支持 Update File（行级替换）、Add File（新建）、Delete File（删除）、"
            "Move File（移动/重命名）。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "minLength": 1,
                    "description": "apply_patch 格式的补丁内容",
                },
            },
            "required": ["input"],
        }

    @property
    def read_only(self) -> bool:
        return False

    @property
    def requires_approval(self) -> bool:
        """应用补丁需要用户审批 — Phase 19"""
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
        """执行 diff 补丁 — 对标 Cline createApplyPatchTool.execute()

        两阶段提交（对标 Cline computePatchChanges + applyChanges）：
            阶段一（compute）：遍历所有补丁块，读取原文件、计算新内容，收集为 changes 列表。
                              解析失败的块收集为 warning（不止首个），有 warning 则拒绝应用，
                              此时零文件被修改。
            阶段二（apply）：  遍历 changes 列表，批量写盘（write/unlink）。

        核心契约：只要有一个 block 解析失败，整个 patch 不产生任何磁盘副作用。
        Phase 3.4 (G4.4 后续): 收集所有 warning（不止首个失败），格式化错误信息，
                                 对标 Cline formatSkippedHunkFailure。
        """
        patch_text = input["input"]

        # 解析补丁块
        blocks = self._parse_patch(patch_text)
        if not blocks:
            return AgentToolResult(
                output={"error": "未解析到有效的补丁块（需要 *** Begin Patch ... *** End Patch）"},
                is_error=True,
            )

        # 阶段一：全量解析 + 计算 change，不写盘
        # Phase 3.4: 收集所有 warning（不止首个失败）— 对标 Cline computePatchChanges
        changes: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        # P2 增强：跟踪每个文件的上一次操作，用于检测重复操作
        prev_ops: dict[str, dict[str, Any]] = {}
        # P2 增强：收集重复操作 warning（非阻塞，不阻止操作）
        dup_warnings: list[dict[str, Any]] = []
        for block_idx, block in enumerate(blocks):
            try:
                change = self._apply_block(block, prev_ops=prev_ops)  # 返回 change 字典，不写盘
                changes.append(change)
                # P2 增强：收集重复操作 warning（非阻塞）
                dup_warning = change.pop("_duplicate_warning", None)
                if dup_warning:
                    logger.warning("重复操作检测: %s", dup_warning)
                    dup_warnings.append({
                        "path": block.get("path", ""),
                        "chunk_index": block_idx,
                        "message": dup_warning,
                    })
            except ValueError as e:
                # 收集 warning，继续处理后续 block — 对标 Cline L348-350
                warnings.append({
                    "path": block.get("path", ""),
                    "chunk_index": block_idx,
                    "message": str(e),
                    "context": "",
                })

        # 有 warning 则拒绝应用 — 对标 Cline L348-350 throw DiffError
        if warnings:
            error_msg = self._format_skipped_hunk_failure(warnings)
            return AgentToolResult(
                output={
                    "error": error_msg,
                    "warnings": warnings,
                    "aborted": True,
                },
                is_error=True,
            )

        # 阶段二：全部解析成功，批量写盘
        results = self._apply_changes(changes)
        succeeded = sum(1 for r in results if r.get("success"))
        failed = sum(1 for r in results if not r.get("success"))

        # P2 增强：将重复操作 warning 附加到结果（非阻塞）
        result_output: dict[str, Any] = {"results": results}
        if dup_warnings:
            result_output["duplicate_warnings"] = dup_warnings

        return AgentToolResult(
            output=result_output,
            metadata={
                "total_files": len(results),
                "succeeded": succeeded,
                "failed": failed,
                "duplicate_warnings": len(dup_warnings),
            },
        )

    def _format_skipped_hunk_failure(
        self,
        warnings: list[dict[str, Any]],
    ) -> str:
        """格式化 warning 列表为错误信息 — 对标 Cline formatSkippedHunkFailure

        输出格式:
            Patch could not be applied because N hunk(s) did not match the current file content.
            path1: hunk 1: message1
            Context:
            ...
            path2: hunk 2: message2
        """
        count = len(warnings)
        hunk_text = "hunk" if count == 1 else "hunks"
        lines = [
            f"Patch could not be applied because {count} {hunk_text} "
            f"did not match the current file content."
        ]
        for warning in warnings:
            chunk_idx = warning.get("chunk_index")
            hunk_number = "unknown" if chunk_idx is None else str(chunk_idx + 1)
            lines.append(
                f"{warning['path']}: hunk {hunk_number}: {warning['message']}"
            )
            context = warning.get("context", "")
            if context:
                lines.append(f"Context:\n{context}")
        return "\n".join(lines)

    def _parse_patch(self, patch_text: str) -> list[dict[str, Any]]:
        """解析补丁文本为补丁块列表

        每个块结构:
            {operation: "update"/"add"/"delete", path: "...", lines: [...]}
        """
        lines = patch_text.splitlines()
        blocks: list[dict[str, Any]] = []
        current_block: dict[str, Any] | None = None
        in_patch = False

        for line in lines:
            stripped = line.strip()

            # 检测补丁开始
            if stripped == "*** Begin Patch":
                in_patch = True
                continue

            # 检测补丁结束
            if stripped == "*** End Patch":
                if current_block is not None:
                    blocks.append(current_block)
                    current_block = None
                in_patch = False
                continue

            if not in_patch:
                continue

            # 检测 Update File 块
            if stripped.startswith("*** Update File:"):
                if current_block is not None:
                    blocks.append(current_block)
                file_path = stripped[len("*** Update File:"):].strip()
                current_block = {
                    "operation": "update",
                    "path": file_path,
                    "lines": [],
                }
                continue

            # 检测 Add File 块
            if stripped.startswith("*** Add File:"):
                if current_block is not None:
                    blocks.append(current_block)
                file_path = stripped[len("*** Add File:"):].strip()
                current_block = {
                    "operation": "add",
                    "path": file_path,
                    "lines": [],
                }
                continue

            # 检测 Delete File 块
            if stripped.startswith("*** Delete File:"):
                if current_block is not None:
                    blocks.append(current_block)
                file_path = stripped[len("*** Delete File:"):].strip()
                current_block = {
                    "operation": "delete",
                    "path": file_path,
                    "lines": [],
                }
                continue

            # P2-5: 检测 Move File 块 — 格式: *** Move File: source -> destination
            if stripped.startswith("*** Move File:"):
                if current_block is not None:
                    blocks.append(current_block)
                move_spec = stripped[len("*** Move File:"):].strip()
                # 解析 source -> destination
                if "->" not in move_spec:
                    raise ValueError(
                        f"Move File 块格式错误，缺少 '->' 分隔符: {move_spec}"
                    )
                parts = move_spec.split("->", 1)
                source = parts[0].strip()
                destination = parts[1].strip()
                if not source or not destination:
                    raise ValueError(
                        f"Move File 块格式错误，source 或 destination 为空: {move_spec}"
                    )
                current_block = {
                    "operation": "move",
                    "path": source,  # 兼容 _apply_block 的路径校验
                    "source": source,
                    "destination": destination,
                    "lines": [],
                }
                continue

            # 收集块内的行
            if current_block is not None:
                current_block["lines"].append(line)

        # 处理未结束的块（没有 *** End Patch 的情况）
        if current_block is not None:
            blocks.append(current_block)

        return blocks

    def _apply_block(
        self,
        block: dict[str, Any],
        prev_ops: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """应用单个补丁块 - 阶段一：仅计算 change，不写盘

        对标 Cline patchToChanges()：分发到 _compute_*_change 计算函数，
        返回 change 字典。任何失败抛出 ValueError，由上层 _execute 捕获后
        中止整个 patch，确保零磁盘副作用。

        P2 增强：检查同一文件同一位置的重复操作（连续 INSERT/UPDATE），
        仅记录 warning，不阻止操作。

        Args:
            block: {operation, path, lines}
            prev_ops: 每个文件上一次操作的签名，用于重复检测（可选）

        Returns:
            change 字典: {operation, path, new_content/old_content, ...}
            若检测到重复操作，附加 _duplicate_warning 字段

        Raises:
            ValueError: 任何解析/匹配失败时抛出
        """
        operation = block["operation"]
        path_str = block["path"]
        # 越界检查 — 对标 Cline restrictToCwd
        # 在阶段一（compute）校验路径，越界则抛 ValueError，被上层收集为 warning，
        # 整个 patch 拒绝应用（原子性）
        abs_path = self._restrict_to_cwd(path_str)
        path = Path(abs_path)

        # P2 增强：检测同一文件的连续重复操作（非阻塞 warning）
        dup_warning = None
        if prev_ops is not None:
            dup_warning = self._detect_duplicate_op(block, prev_ops)

        if operation == "update":
            change = self._compute_update_change(path, path_str, block["lines"])
        elif operation == "add":
            change = self._compute_add_change(path, path_str, block["lines"])
        elif operation == "delete":
            change = self._compute_delete_change(path, path_str)
        elif operation == "move":
            # P2-5: Move File 操作 — 需校验 source 和 destination 两个路径
            destination_str = block.get("destination", "")
            change = self._compute_move_change(path, path_str, destination_str)
        else:
            raise ValueError(f"未知操作类型: {operation}")

        # P2 增强：记录当前操作签名，供后续块检测重复
        if prev_ops is not None:
            removed_lines = (
                [l[1:] for l in block["lines"] if l.startswith("-")]
                if operation == "update" else []
            )
            prev_ops[path_str] = {
                "operation": operation,
                "removed_lines": removed_lines,
            }

        # P2 增强：附加重复操作 warning（非阻塞）
        if dup_warning:
            change["_duplicate_warning"] = dup_warning

        return change

    def _detect_duplicate_op(
        self,
        block: dict[str, Any],
        prev_ops: dict[str, dict[str, Any]],
    ) -> str | None:
        """检测同一文件的连续重复操作 — P2 增强

        检查规则（仅记录 warning，不阻止操作）:
            1. 连续两个 INSERT（Add File）操作指向同一文件
            2. 连续两个 UPDATE 操作修改同一内容（removed_lines 相同）

        Args:
            block: 当前补丁块
            prev_ops: 每个文件上一次操作的签名 {path: {operation, removed_lines}}

        Returns:
            warning 字符串，或 None（无重复）
        """
        path_str = block["path"]
        operation = block["operation"]

        prev = prev_ops.get(path_str)
        if prev is None:
            return None

        prev_op = prev.get("operation")

        # 连续两个 INSERT（Add File）指向同一文件
        if operation == "add" and prev_op == "add":
            return f"连续两次 Add File 操作指向同一文件: {path_str}"

        # 连续两个 UPDATE 修改同一内容
        if operation == "update" and prev_op == "update":
            curr_removed = [l[1:] for l in block["lines"] if l.startswith("-")]
            prev_removed = prev.get("removed_lines", [])
            if curr_removed and curr_removed == prev_removed:
                return f"连续两次 Update File 操作修改同一内容: {path_str}"

        return None

    # ------------------------------------------------------------------
    # 阶段一：纯计算函数（不写盘）— 对标 Cline patchToChanges
    # ------------------------------------------------------------------

    def _compute_update_change(
        self, path: Path, path_str: str, lines: list[str]
    ) -> dict[str, Any]:
        """阶段一：计算 Update File 的变更内容，不写盘

        复用原 _apply_update 的行级替换、换行符检测、fuzzy 匹配逻辑，
        但移除所有磁盘写操作。原错误路径（文件不存在/二进制/未找到匹配行）
        改为抛出 ValueError，让上层捕获后中止整个 patch。

        Stage 12.2 (G4.1/G4.2/G4.5) 增强:
            - G4.1: 使用 _read_text_unicode 读取，自动剥离 BOM
            - G4.2: @@ context 行使用 _match_context 模糊匹配（含 tab/space 兼容）
            - G4.5: 失败时抛 PatchApplyError 携带文件名/行号/expected/actual

        Raises:
            PatchApplyError: 文件不存在 / 二进制文件 / 未找到匹配行（含详细位置）
            ValueError: 兼容旧调用方的基类异常（PatchApplyError 继承自 ValueError）
        """
        if not path.exists():
            raise PatchApplyError(
                f"文件不存在: {path_str}",
                file_path=path_str,
            )

        try:
            raw_original = _read_text_unicode(path)
        except UnicodeDecodeError:
            raise PatchApplyError(
                f"无法读取二进制文件: {path_str}",
                file_path=path_str,
            )

        line_ending = _detect_line_ending(raw_original)
        original = _normalize_for_edit(raw_original, line_ending)
        original_lines = original.splitlines(keepends=False)
        result_lines = list(original_lines)
        # 偏移量：由于 result_lines 在替换过程中长度会变化，用 offset 跟踪
        offset = 0

        # 收集连续的 -/+ 块进行替换
        i = 0
        while i < len(lines):
            line = lines[i]

            # 上下文行（@@ 开头或无前缀）— 用于定位
            if line.startswith("@@"):
                context = line[2:].strip()
                # G4.2: 在 result_lines 中用 _match_context 模糊匹配定位
                search_start = offset
                for idx in range(search_start, len(result_lines)):
                    if _match_context(context, result_lines[idx].strip()):
                        offset = idx
                        break
                # 找不到上下文不报错，继续处理
                i += 1
                continue

            # 收集连续的 - 行和 + 行作为一个替换组
            if line.startswith("-"):
                removed_lines: list[str] = []
                added_lines: list[str] = []

                # 收集连续的 - 行
                while i < len(lines) and lines[i].startswith("-"):
                    removed_lines.append(lines[i][1:])
                    i += 1

                # 收集连续的 + 行
                while i < len(lines) and lines[i].startswith("+"):
                    added_lines.append(lines[i][1:])
                    i += 1

                # 在 result_lines 中查找 removed_lines 并替换为 added_lines
                replaced = self._replace_segment(
                    result_lines, offset, removed_lines, added_lines
                )
                if replaced is None:
                    # G4.5: 抛 PatchApplyError 携带详细位置信息
                    expected_first = removed_lines[0] if removed_lines else ""
                    # 尝试取 offset 位置的实际行作为 actual（便于 LLM 对比）
                    actual_line = (
                        result_lines[offset] if offset < len(result_lines) else ""
                    )
                    raise PatchApplyError(
                        "未找到要删除的行",
                        file_path=path_str,
                        line_num=offset + 1,  # 1-based
                        expected=expected_first,
                        actual=actual_line,
                    )
                # 更新 offset 到替换位置之后
                offset = replaced + len(added_lines)
                continue

            # 单独的 + 行（无对应 - 行，纯插入）
            if line.startswith("+"):
                added_lines: list[str] = []
                while i < len(lines) and lines[i].startswith("+"):
                    added_lines.append(lines[i][1:])
                    i += 1
                # 在 offset 位置插入
                for j, add_line in enumerate(added_lines):
                    result_lines.insert(offset + j, add_line)
                offset += len(added_lines)
                continue

            # 其他行（无前缀的上下文行）— 跳过
            i += 1

        # 计算最终内容（不写盘），保留原文件末尾换行行为，并还原原始换行符
        content = "\n".join(result_lines)
        if original.endswith("\n") and not content.endswith("\n"):
            content += "\n"
        content = _restore_line_ending(content, line_ending)

        return {
            "operation": "update",
            "path": path_str,
            "new_content": content,
            "old_content": raw_original,
            "lines_before": len(original_lines),
            "lines_after": len(result_lines),
        }

    def _compute_add_change(
        self, path: Path, path_str: str, lines: list[str]
    ) -> dict[str, Any]:
        """阶段一：计算 Add File 的变更内容，不写盘

        复用原 _apply_add 的内容拼接逻辑，但移除 mkdir + write_text。
        文件已存在时抛出 ValueError。

        Raises:
            ValueError: 文件已存在
        """
        if path.exists():
            raise ValueError(f"文件已存在: {path_str}")

        # 收集 + 行作为文件内容
        content_lines: list[str] = []
        for line in lines:
            if line.startswith("+"):
                content_lines.append(line[1:])
            # 忽略其他行

        content = "\n".join(content_lines)

        return {
            "operation": "add",
            "path": path_str,
            "new_content": content,
            "lines": len(content_lines),
        }

    def _compute_delete_change(
        self, path: Path, path_str: str
    ) -> dict[str, Any]:
        """阶段一：计算 Delete File 的变更内容，不写盘

        复用原 _apply_delete 的存在性检查，但移除 path.unlink()。
        文件不存在时抛出 ValueError。

        Raises:
            ValueError: 文件不存在
        """
        if not path.exists():
            raise ValueError(f"文件不存在: {path_str}")

        # 记录原始内容（用于审计/回滚，二进制文件用空字符串占位）
        try:
            raw_original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_original = ""

        return {
            "operation": "delete",
            "path": path_str,
            "old_content": raw_original,
        }

    def _compute_move_change(
        self,
        source_path: Path,
        source_str: str,
        destination_str: str,
    ) -> dict[str, Any]:
        """阶段一：计算 Move File 的变更内容，不写盘 — P2-5 新增

        将文件从 source 移动到 destination（相当于重命名）。
        校验规则:
            - source 必须存在
            - destination 不能已存在（避免意外覆盖）
            - destination 路径必须在 cwd 内（_restrict_to_cwd）

        阶段二通过 shutil.move 实际执行移动（含跨目录自动创建父目录）。

        Raises:
            ValueError: source 不存在 / destination 已存在 / destination 路径越界
        """
        if not source_path.exists():
            raise ValueError(f"移动源文件不存在: {source_str}")

        # 校验 destination 路径在 cwd 内
        destination_abs = self._restrict_to_cwd(destination_str)
        destination_path = Path(destination_abs)

        if destination_path.exists():
            raise ValueError(f"目标文件已存在，拒绝覆盖: {destination_str}")

        # 记录原始内容（用于审计/回滚，二进制文件用空字符串占位）
        try:
            raw_original = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_original = ""

        return {
            "operation": "move",
            "path": source_str,  # 兼容结果中的 path 字段
            "source": source_str,
            "destination": destination_str,
            "old_content": raw_original,
        }

    # ------------------------------------------------------------------
    # 阶段二：批量写盘函数 — 对标 Cline applyChanges
    # ------------------------------------------------------------------

    def _apply_changes(self, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """阶段二：批量写盘

        遍历 changes 列表，根据 operation 字段执行写盘。
        此阶段不再做任何校验（校验已在阶段一完成），仅机械写盘。
        单个写盘的 IO 异常（如磁盘满、权限不足）记录为失败结果，
        不影响其他 changes 的写盘（尽力而为）。
        """
        results: list[dict[str, Any]] = []
        for change in changes:
            operation = change["operation"]
            path_str = change["path"]
            path = Path(path_str)
            try:
                if operation == "update":
                    path.write_text(change["new_content"], encoding="utf-8")
                    results.append({
                        "path": path_str,
                        "operation": "update",
                        "success": True,
                        "lines_before": change.get("lines_before", 0),
                        "lines_after": change.get("lines_after", 0),
                    })
                elif operation == "add":
                    # 自动创建父目录
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(change["new_content"], encoding="utf-8")
                    results.append({
                        "path": path_str,
                        "operation": "add",
                        "success": True,
                        "lines": change.get("lines", 0),
                    })
                elif operation == "delete":
                    path.unlink()
                    results.append({
                        "path": path_str,
                        "operation": "delete",
                        "success": True,
                    })
                elif operation == "move":
                    # P2-5: Move File 写盘 — shutil.move 支持跨目录移动
                    source_str = change["source"]
                    destination_str = change["destination"]
                    source_abs = self._restrict_to_cwd(source_str)
                    dest_abs = self._restrict_to_cwd(destination_str)
                    dest_path = Path(dest_abs)
                    # 自动创建目标父目录
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(source_abs, dest_abs)
                    results.append({
                        "path": path_str,
                        "operation": "move",
                        "source": source_str,
                        "destination": destination_str,
                        "success": True,
                    })
                else:
                    results.append({
                        "path": path_str,
                        "operation": operation,
                        "success": False,
                        "error": f"未知操作类型: {operation}",
                    })
            except Exception as e:
                results.append({
                    "path": path_str,
                    "operation": operation,
                    "success": False,
                    "error": str(e),
                })
        return results

    def _apply_update(self, path: Path, path_str: str, lines: list[str]) -> dict[str, Any]:
        """应用 Update File 补丁 — 行级替换（单块写盘遗留实现）

        保留原签名与返回结构（result dict 含 success/error），供需要单块
        立即写盘的遗留路径调用。计算逻辑已抽离到 _compute_update_change，
        此处仅做"compute + write"的组合，避免逻辑重复。

        增强实现: 统一换行符、支持 fuzzy 匹配、保留原始换行符。
        """
        try:
            change = self._compute_update_change(path, path_str, lines)
        except ValueError as e:
            return {
                "path": path_str,
                "operation": "update",
                "success": False,
                "error": str(e),
            }

        # 单块立即写盘
        try:
            path.write_text(change["new_content"], encoding="utf-8")
        except Exception as e:
            return {
                "path": path_str,
                "operation": "update",
                "success": False,
                "error": str(e),
            }

        return {
            "path": path_str,
            "operation": "update",
            "success": True,
            "lines_before": change.get("lines_before", 0),
            "lines_after": change.get("lines_after", 0),
        }

    def _replace_segment(
        self,
        result_lines: list[str],
        start: int,
        removed_lines: list[str],
        added_lines: list[str],
    ) -> int | None:
        """在 result_lines 中从 start 开始查找 removed_lines 并替换为 added_lines

        匹配优先级（保留原逻辑，Stage 12.2 G4.2 新增 tab/space 兼容，P2-4 新增 Levenshtein 回退）：
            1. 精确匹配
            2. 忽略首尾空白（strip）
            3. 忽略 tab/space 缩进差异（expandtabs）— Stage 12.2 G4.2 新增
            4. P2-4: Levenshtein 相似度 ≥0.66 回退匹配 + Unicode 标点归一化

        P2-4 回退匹配逻辑:
            当上述精确/模糊匹配均失败时，对文件中每一行计算与目标行
            （removed_lines 首行）的 Levenshtein 相似度，取相似度最高且
            ≥0.66 的位置作为匹配。相似度计算前先做 Unicode 标点归一化，
            使全角/半角、不同引号等标点差异不影响匹配。

        Returns:
            替换起始索引（成功）或 None（未找到）
        """
        n = len(removed_lines)
        if n == 0:
            return None

        # 1. 精确匹配
        for idx in range(start, len(result_lines) - n + 1):
            if result_lines[idx:idx + n] == removed_lines:
                result_lines[idx:idx + n] = added_lines
                return idx

        # 2. fuzzy 匹配：忽略首尾空白
        for idx in range(start, len(result_lines) - n + 1):
            window = result_lines[idx:idx + n]
            if all(window[j].strip() == removed_lines[j].strip() for j in range(n)):
                result_lines[idx:idx + n] = added_lines
                return idx

        # 3. G4.2: fuzzy 匹配 — 忽略 tab/space 缩进差异
        for idx in range(start, len(result_lines) - n + 1):
            window = result_lines[idx:idx + n]
            if all(
                window[j].expandtabs() == removed_lines[j].expandtabs()
                for j in range(n)
            ):
                result_lines[idx:idx + n] = added_lines
                return idx

        # 4. P2-4: Levenshtein 相似度 ≥0.66 回退匹配
        # 对文件中每一行计算与目标行（removed_lines 首行）的相似度，
        # 取最高且 ≥阈值的位置作为匹配。计算前先做 Unicode 标点归一化。
        target_line = _normalize_unicode_punctuation(removed_lines[0])
        if not target_line:
            # 目标行为空时跳过 Levenshtein 回退（避免误匹配空行）
            return None
        best_idx = -1
        best_similarity = 0.0
        for idx in range(start, len(result_lines) - n + 1):
            file_line = _normalize_unicode_punctuation(result_lines[idx])
            similarity = _calculate_similarity(target_line, file_line)
            if similarity > best_similarity:
                best_similarity = similarity
                best_idx = idx
        if best_idx >= 0 and best_similarity >= _LEVENSHTEIN_SIMILARITY_THRESHOLD:
            result_lines[best_idx:best_idx + n] = added_lines
            return best_idx

        return None

    def _apply_add(self, path: Path, path_str: str, lines: list[str]) -> dict[str, Any]:
        """应用 Add File 补丁 — 新建文件（单块写盘遗留实现）

        保留原签名与返回结构（result dict 含 success/error），供需要单块
        立即写盘的遗留路径调用。计算逻辑已抽离到 _compute_add_change，
        此处仅做"compute + write"的组合，避免逻辑重复。

        所有 + 行的内容拼接为文件内容。
        """
        try:
            change = self._compute_add_change(path, path_str, lines)
        except ValueError as e:
            return {
                "path": path_str,
                "operation": "add",
                "success": False,
                "error": str(e),
            }

        # 单块立即写盘（自动创建父目录）
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change["new_content"], encoding="utf-8")
        except Exception as e:
            return {
                "path": path_str,
                "operation": "add",
                "success": False,
                "error": str(e),
            }

        return {
            "path": path_str,
            "operation": "add",
            "success": True,
            "lines": change.get("lines", 0),
        }

    def _apply_delete(self, path: Path, path_str: str) -> dict[str, Any]:
        """应用 Delete File 补丁 — 删除文件（单块写盘遗留实现）

        保留原签名与返回结构（result dict 含 success/error），供需要单块
        立即写盘的遗留路径调用。计算逻辑已抽离到 _compute_delete_change，
        此处仅做"compute + unlink"的组合，避免逻辑重复。
        """
        try:
            change = self._compute_delete_change(path, path_str)
        except ValueError as e:
            return {
                "path": path_str,
                "operation": "delete",
                "success": False,
                "error": str(e),
            }

        # 单块立即删除
        try:
            path.unlink()
        except Exception as e:
            return {
                "path": path_str,
                "operation": "delete",
                "success": False,
                "error": str(e),
            }

        return {
            "path": path_str,
            "operation": "delete",
            "success": True,
        }

    def _apply_move(
        self, path: Path, path_str: str, destination_str: str
    ) -> dict[str, Any]:
        """应用 Move File 补丁 — 移动/重命名文件（单块写盘遗留实现）— P2-5 新增

        保留原签名风格与返回结构（result dict 含 success/error），供需要单块
        立即写盘的遗留路径调用。计算逻辑已抽离到 _compute_move_change，
        此处仅做"compute + shutil.move"的组合，避免逻辑重复。
        """
        try:
            change = self._compute_move_change(path, path_str, destination_str)
        except ValueError as e:
            return {
                "path": path_str,
                "operation": "move",
                "success": False,
                "error": str(e),
            }

        # 单块立即移动（自动创建目标父目录）
        try:
            dest_abs = self._restrict_to_cwd(destination_str)
            dest_path = Path(dest_abs)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), dest_abs)
        except Exception as e:
            return {
                "path": path_str,
                "operation": "move",
                "source": path_str,
                "destination": destination_str,
                "success": False,
                "error": str(e),
            }

        return {
            "path": path_str,
            "operation": "move",
            "source": path_str,
            "destination": destination_str,
            "success": True,
        }
