# -*- coding: utf-8 -*-
"""文件状态快照 checkpoint — 对标 Cline shadow-git checkpoint 机制

Phase 33.2 新增。与 agent/checkpoint.py 中的 CheckpointManager（消息列表快照）互补：
    - checkpoint.py: 保存会话消息列表快照，用于回滚对话状态
    - file_checkpoint.py: 保存工作区文件状态快照，用于回滚文件修改

在执行写工具（editor / apply_patch / file_write / 文件修改类 run_commands）前，
用 `git stash create` 捕获工作区当前状态生成 stash commit，
工具执行后若需回滚可调用 `git checkout <commit> -- <paths>` 还原指定文件。

适用场景:
    1. agent 误改文件，用户希望一键回滚到工具执行前
    2. 多步编辑失败后恢复到中间某个安全点
    3. 调试时对比工具前后的文件差异

设计要点:
    - 仅在 git 仓库内生效；非 git 目录跳过 checkpoint（返回 None）
    - 仅对真正修改文件的工具创建 checkpoint，避免无谓开销
    - stash commit 是悬空对象（dangling），不污染 stash 列表
    - 默认仅还原被工具修改的文件，避免覆盖用户在工具外手动修改的内容
    - checkpoint 元信息持久化到 agent_data/file_checkpoints/<session_id>.json，
      支持跨进程访问（用 file_lock 保护）
    - 通过 AGENT_ENABLE_FILE_CHECKPOINT=1 环境变量启用，默认关闭以保持现有性能

对标 Cline:
    - apps/vscode/src/core/checkpoint/ （shadow-git checkpoint 机制）
    - Cline 通过 git stash create + git checkout 实现工作区快照和回滚
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义
# ============================================================================

# 默认 checkpoint 持久化目录（相对于项目根目录）
# 与 agent/checkpoint.py 的 agent_data/checkpoints 分开存放
_DEFAULT_CHECKPOINT_PERSIST_DIR = "agent_data/file_checkpoints"

# 写工具名集合 — 这些工具会修改文件，执行前需要创建 checkpoint
WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "editor",
    "apply_patch",
    "file_write",
    "write_files",  # 兼容别名
    "exec",  # exec 工具可能调用写命令
})

# run_commands 工具名（需要按命令内容判断是否修改文件）
RUN_COMMANDS_TOOL_NAMES: frozenset[str] = frozenset({
    "run_commands",
    "run_command",
    "bash",
    "shell",
})

# 可能修改文件的命令子串（启发式判断，避免对 read-only 命令也创建 checkpoint）
_FILE_MODIFYING_COMMAND_PATTERNS: tuple[str, ...] = (
    "write", "edit", "patch", "rm ", "mv ", "mkdir", "rmdir",
    "echo ", "> ", ">>", "tee", "sed -i", "awk -i",
    "cp ", "scp ", "rsync",
    "git add", "git rm", "git mv", "git checkout", "git reset --hard",
    "pip install", "npm install", "yarn add",
)


# ============================================================================
# 数据类
# ============================================================================


@dataclass
class CheckpointRef:
    """checkpoint 引用 — 对标 Cline CheckpointRef

    Attributes:
        checkpoint_id: 唯一标识（用于 API 查询和回滚）
        session_id: 所属会话 ID
        tool_call_id: 触发 checkpoint 的工具调用 ID
        tool_name: 触发 checkpoint 的工具名
        stash_commit: git stash create 返回的 commit hash
        workspace_root: 工作区根目录（绝对路径）
        file_paths: 该工具可能修改的文件路径列表（相对 workspace_root），
                    回滚时仅还原这些文件
        created_at: 创建时间戳（unix 秒）
        description: 人类可读描述（如 "before editor tool"）
    """
    checkpoint_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    stash_commit: str
    workspace_root: str
    file_paths: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointRef":
        return cls(
            checkpoint_id=data["checkpoint_id"],
            session_id=data["session_id"],
            tool_call_id=data.get("tool_call_id", ""),
            tool_name=data.get("tool_name", ""),
            stash_commit=data["stash_commit"],
            workspace_root=data["workspace_root"],
            file_paths=list(data.get("file_paths", [])),
            created_at=float(data.get("created_at", time.time())),
            description=data.get("description", ""),
        )


# ============================================================================
# 文件 checkpoint 管理器 — 对标 Cline shadow-git checkpoint
# ============================================================================


class FileCheckpointManager:
    """文件状态快照管理器 — 对标 Cline shadow-git checkpoint

    用法:
        manager = FileCheckpointManager(persist_dir="agent_data/checkpoints")
        # 写工具执行前
        ref = manager.save_checkpoint(
            session_id="sess-1",
            tool_call_id="call-1",
            tool_name="editor",
            tool_input={"path": "src/main.py", "new_string": "..."},
            workspace_root="/path/to/project",
        )
        # 需要回滚时
        manager.restore_checkpoint(ref.checkpoint_id)

    实现说明:
        - save_checkpoint 用 `git stash create` 生成悬空 commit，不修改 stash 列表
        - restore_checkpoint 用 `git checkout <commit> -- <paths>` 还原指定文件
          （file_paths 为空时还原整个工作区）
        - 非 git 仓库跳过 checkpoint（log debug 后返回 None）
        - 元信息持久化到 agent_data/checkpoints/<session_id>.json，用 file_lock 保护
    """

    def __init__(self, persist_dir: str | Path | None = None) -> None:
        """初始化 checkpoint 管理器

        Args:
            persist_dir: 持久化目录，默认 agent_data/checkpoints/
        """
        if persist_dir is None:
            project_root = Path(__file__).resolve().parent.parent
            persist_dir = project_root / _DEFAULT_CHECKPOINT_PERSIST_DIR
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        # 内存缓存: session_id -> list[CheckpointRef]
        self._cache: dict[str, list[CheckpointRef]] = {}

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def save_checkpoint(
        self,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        workspace_root: str | Path,
        description: str = "",
    ) -> CheckpointRef | None:
        """工具执行前保存工作区快照 — 对标 Cline beforeTool checkpoint

        Args:
            session_id: 会话 ID
            tool_call_id: 工具调用 ID
            tool_name: 工具名（用于判断是否为写工具）
            tool_input: 工具输入参数（用于提取可能修改的文件路径）
            workspace_root: 工作区根目录
            description: 人类可读描述

        Returns:
            CheckpointRef 或 None（非 git 仓库 / 非写工具 / git 失败时）
        """
        # 仅对写工具创建 checkpoint
        if not self._is_write_tool(tool_name, tool_input):
            return None

        workspace_root = Path(workspace_root).resolve()
        stash_commit = self._git_stash_create(workspace_root)
        if stash_commit is None:
            return None

        file_paths = self._extract_file_paths(tool_name, tool_input)
        checkpoint_id = self._generate_checkpoint_id(session_id, tool_call_id)

        # Stage 6.4 新增：将 stash commit 注册到私有 ref，保证 GC-safe
        # 对标 Cline checkpoint-hooks.ts L236-238 git update-ref
        # refs/agent/checkpoints/{session_id}/{checkpoint_id} <commit>
        # 私有 ref 不污染用户 git stash list（仅 refs/stash 影响 stash list）
        if stash_commit:  # 空字符串表示无变更，无需 ref
            ref_name = self._checkpoint_ref_name(session_id, checkpoint_id)
            if not self._git_update_ref(workspace_root, ref_name, stash_commit):
                # update-ref 失败不阻塞 checkpoint 创建，仅记录告警
                # stash commit 仍为悬空对象，回滚仍可用（30 天内）
                logger.warning(
                    "FileCheckpoint: update-ref 失败，stash commit 仍为悬空对象: %s",
                    stash_commit[:8],
                )

        ref = CheckpointRef(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            stash_commit=stash_commit,
            workspace_root=str(workspace_root),
            file_paths=file_paths,
            description=description or f"before {tool_name} tool",
        )

        self._cache.setdefault(session_id, []).append(ref)
        self._persist_session(session_id)
        logger.info(
            "FileCheckpoint: 已保存 checkpoint %s (session=%s, tool=%s, commit=%s, files=%d)",
            checkpoint_id, session_id, tool_name, stash_commit[:8], len(file_paths),
        )
        return ref

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        full_restore: bool = False,
    ) -> bool:
        """回滚到指定 checkpoint — 对标 Cline restoreCheckpoint

        Stage 6.5 新增 full_restore 参数，对标 Cline applyCheckpointToWorktree
        的 reset --hard + clean -fd + stash apply 全量恢复模式。

        Args:
            checkpoint_id: checkpoint ID
            full_restore: True 时用 git reset --hard + clean -fd 全量恢复
                          （对标 Cline applyCheckpointToWorktree，破坏性）
                          False 时仅还原 file_paths 中的文件（默认，安全）

        Returns:
            是否回滚成功
        """
        ref = self._find_checkpoint(checkpoint_id)
        if ref is None:
            logger.warning("FileCheckpoint: checkpoint %s 不存在", checkpoint_id)
            return False

        workspace_root = Path(ref.workspace_root)
        if not workspace_root.exists():
            logger.error("FileCheckpoint: 工作区目录不存在: %s", workspace_root)
            return False

        if full_restore:
            # 全量恢复模式 — 对标 Cline applyCheckpointToWorktree
            success = self._git_full_restore(workspace_root, ref.stash_commit)
        else:
            # 部分恢复模式（原逻辑）— 仅还原 file_paths 中的文件
            success = self._git_checkout_files(workspace_root, ref.stash_commit, ref.file_paths)
        if success:
            logger.info(
                "FileCheckpoint: 已回滚 checkpoint %s (mode=%s, files=%d)",
                checkpoint_id,
                "full" if full_restore else "partial",
                len(ref.file_paths),
            )
        return success

    def list_checkpoints(self, session_id: str) -> list[CheckpointRef]:
        """列出会话的所有 checkpoint"""
        if session_id not in self._cache:
            self._load_session(session_id)
        return list(self._cache.get(session_id, []))

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointRef | None:
        """获取单个 checkpoint"""
        return self._find_checkpoint(checkpoint_id)

    def clear_session(self, session_id: str) -> None:
        """清除会话的所有 checkpoint 元信息和 git ref — Stage 6.4 增加 ref 清理

        Stage 6.4 新增：先收集 ref 调用 git update-ref -d 清理私有 ref，
        对标 Cline deleteCheckpointRefs，避免 ref 残留导致 git 仓库对象膨胀。
        """
        # 先收集需要清理的 ref（在删除缓存前）
        refs = self._cache.get(session_id, [])
        if refs:
            # 按 workspace_root 分组清理 ref
            workspace_groups: dict[str, list[str]] = {}
            for ref in refs:
                if ref.stash_commit:  # 空字符串 commit 无 ref，跳过
                    ref_name = self._checkpoint_ref_name(session_id, ref.checkpoint_id)
                    workspace_groups.setdefault(ref.workspace_root, []).append(ref_name)
            for workspace_root, ref_names in workspace_groups.items():
                for ref_name in ref_names:
                    self._git_delete_ref(Path(workspace_root), ref_name)

        # 原逻辑：删除内存缓存和持久化文件
        self._cache.pop(session_id, None)
        path = self._session_file_path(session_id)
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning("FileCheckpoint: 删除 session 文件失败: %s", e)

    # ------------------------------------------------------------------
    # 内部方法 — git 操作
    # ------------------------------------------------------------------

    def _is_write_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
    ) -> bool:
        """判断工具是否会修改文件"""
        if tool_name in WRITE_TOOL_NAMES:
            return True
        if tool_name in RUN_COMMANDS_TOOL_NAMES:
            return self._command_modifies_files(tool_input)
        return False

    def _command_modifies_files(self, tool_input: dict[str, Any] | None) -> bool:
        """启发式判断 run_commands 命令是否会修改文件"""
        if not tool_input:
            return False
        command = (
            tool_input.get("command")
            or tool_input.get("cmd")
            or ""
        )
        if not isinstance(command, str) or not command:
            return False
        cmd_lower = command.lower()
        return any(pattern in cmd_lower for pattern in _FILE_MODIFYING_COMMAND_PATTERNS)

    def _extract_file_paths(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
    ) -> list[str]:
        """从工具输入中提取可能修改的文件路径（相对 workspace_root）

        不同工具的文件路径字段:
            - editor / file_write: path / file_path
            - apply_patch: path / patches[].path
            - run_commands: 无法精确提取，返回空列表（回滚时还原整个工作区）
        """
        if not tool_input:
            return []

        paths: list[str] = []
        for key in ("path", "file_path", "file"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
                break

        # apply_patch 的 patches 列表
        patches = tool_input.get("patches")
        if isinstance(patches, list):
            for patch in patches:
                if isinstance(patch, dict):
                    patch_path = patch.get("path") or patch.get("file_path")
                    if isinstance(patch_path, str) and patch_path and patch_path not in paths:
                        paths.append(patch_path)

        return paths

    def _git_stash_create(self, workspace_root: Path) -> str | None:
        """执行 git stash create 生成悬空 commit

        采用三步法捕获所有工作区状态（含未跟踪文件）：
            1. git add -A           # 临时暂存所有变更（含未跟踪文件）
            2. git stash create     # 创建悬空 commit（不修改 stash 列表）
            3. git reset -q         # 恢复 index 到 HEAD（撤回暂存）

        这样可捕获 agent 新建的未跟踪文件，让回滚能撤销文件创建操作。

        Returns:
            commit hash 或 None（非 git 仓库 / git 失败时）；
            空字符串表示工作区无变更（回滚时无操作）
        """
        try:
            # 先验证是 git 仓库
            if not self._is_git_repo(workspace_root):
                return None

            # 步骤 1: 暂存所有变更（含未跟踪文件）
            add_result = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if add_result.returncode != 0:
                logger.debug(
                    "FileCheckpoint: git add -A 失败: %s",
                    add_result.stderr.strip()[:200],
                )
                return None

            # 步骤 2: 创建悬空 commit
            create_result = subprocess.run(
                ["git", "stash", "create"],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )

            # 步骤 3: 无论步骤 2 是否成功都恢复 index
            subprocess.run(
                ["git", "reset", "-q"],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )

            if create_result.returncode != 0:
                logger.debug(
                    "FileCheckpoint: git stash create 失败: %s",
                    create_result.stderr.strip()[:200],
                )
                return None

            commit = create_result.stdout.strip()
            if not commit:
                # 工作区干净，无变更可 stash；返回一个特殊的"HEAD"标记，回滚时无操作
                logger.debug("FileCheckpoint: 工作区无变更，stash create 返回空")
                return ""

            return commit
        except subprocess.TimeoutExpired:
            logger.warning("FileCheckpoint: git stash create 超时")
            # 超时后尝试恢复 index
            try:
                subprocess.run(
                    ["git", "reset", "-q"],
                    cwd=str(workspace_root),
                    capture_output=True,
                    timeout=15,
                )
            except Exception:
                pass
            return None
        except FileNotFoundError:
            logger.warning("FileCheckpoint: 未找到 git 命令")
            return None
        except Exception as e:
            logger.warning("FileCheckpoint: git stash create 异常: %s", e)
            return None

    def _git_checkout_files(
        self,
        workspace_root: Path,
        stash_commit: str,
        file_paths: list[str],
    ) -> bool:
        """执行 git checkout <commit> -- <paths> 还原文件

        Args:
            workspace_root: 工作区根目录
            stash_commit: stash commit hash（空字符串表示无变更，跳过还原）
            file_paths: 要还原的文件路径列表（相对 workspace_root），
                        为空时还原整个工作区

        Returns:
            是否还原成功
        """
        if not stash_commit:
            # 工作区原本无变更，无需还原
            logger.debug("FileCheckpoint: stash_commit 为空，跳过还原")
            return True

        try:
            cmd = ["git", "checkout", stash_commit, "--"]
            if file_paths:
                cmd.extend(file_paths)
            else:
                # 还原整个工作区（用 . 表示）
                cmd.append(".")

            result = subprocess.run(
                cmd,
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                logger.error(
                    "FileCheckpoint: git checkout 失败: %s",
                    result.stderr.strip()[:200],
                )
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("FileCheckpoint: git checkout 超时")
            return False
        except FileNotFoundError:
            logger.warning("FileCheckpoint: 未找到 git 命令")
            return False
        except Exception as e:
            logger.error("FileCheckpoint: git checkout 异常: %s", e)
            return False

    def _is_git_repo(self, workspace_root: Path) -> bool:
        """判断目录是否为 git 仓库"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    def _git_full_restore(
        self,
        workspace_root: Path,
        stash_commit: str,
    ) -> bool:
        """全量恢复工作区 — Stage 6.5 新增，对标 Cline applyCheckpointToWorktree

        依次执行:
            1. git reset --hard（丢弃当前工作区所有修改）
            2. git clean -fd（删除未跟踪文件和目录）
            3. git stash apply <commit>（应用 stash 恢复工作区）

        警告: 破坏性操作，会丢弃用户在工具外手动修改的文件。

        Args:
            workspace_root: 工作区根目录
            stash_commit: stash commit hash（空字符串表示无变更，跳过）

        Returns:
            是否恢复成功
        """
        if not stash_commit:
            logger.debug("FileCheckpoint: stash_commit 为空，跳过全量恢复")
            return True
        try:
            # 步骤 1: reset --hard
            r1 = subprocess.run(
                ["git", "reset", "--hard"],
                cwd=str(workspace_root),
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if r1.returncode != 0:
                logger.error("FileCheckpoint: git reset --hard 失败: %s", r1.stderr.strip()[:200])
                return False
            # 步骤 2: clean -fd
            r2 = subprocess.run(
                ["git", "clean", "-fd"],
                cwd=str(workspace_root),
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if r2.returncode != 0:
                logger.error("FileCheckpoint: git clean -fd 失败: %s", r2.stderr.strip()[:200])
                return False
            # 步骤 3: stash apply
            r3 = subprocess.run(
                ["git", "stash", "apply", stash_commit],
                cwd=str(workspace_root),
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            if r3.returncode != 0:
                logger.error("FileCheckpoint: git stash apply 失败: %s", r3.stderr.strip()[:200])
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("FileCheckpoint: 全量恢复超时")
            return False
        except Exception as e:
            logger.error("FileCheckpoint: 全量恢复异常: %s", e)
            return False

    # ------------------------------------------------------------------
    # Stage 6.4: git 私有 ref 管理 — 对标 Cline refs/cline/checkpoints/{sid}/{run}
    # ------------------------------------------------------------------

    def _checkpoint_ref_name(
        self,
        session_id: str,
        checkpoint_id: str,
    ) -> str:
        """生成 git 私有 ref 路径 — Stage 6.4 新增

        对标 Cline refs/cline/checkpoints/{sid}/{run}。用 refs/agent/checkpoints/
        命名空间与 Cline 区分，避免与用户 stash list（refs/stash）冲突。

        Args:
            session_id: 会话 ID
            checkpoint_id: checkpoint ID

        Returns:
            ref 路径字符串，如 refs/agent/checkpoints/sess1/ckpt_xxx
        """
        safe_session = os.path.basename(session_id)
        safe_ckpt = os.path.basename(checkpoint_id)
        return f"refs/agent/checkpoints/{safe_session}/{safe_ckpt}"

    def _git_update_ref(
        self,
        workspace_root: Path,
        ref_name: str,
        commit: str,
    ) -> bool:
        """执行 git update-ref 将 commit 注册为私有 ref — Stage 6.4 新增

        对标 Cline checkpoint-hooks.ts L236-238 的 git update-ref 调用。
        保证 stash commit 永久可达，避免被 git gc 回收（默认 30 天清理悬空对象）。

        Args:
            workspace_root: 工作区根目录
            ref_name: ref 路径（如 refs/agent/checkpoints/sess1/ckpt_xxx）
            commit: stash commit hash

        Returns:
            是否成功
        """
        try:
            result = subprocess.run(
                ["git", "update-ref", ref_name, commit],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                logger.debug(
                    "FileCheckpoint: git update-ref 失败: %s",
                    result.stderr.strip()[:200],
                )
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("FileCheckpoint: git update-ref 超时")
            return False
        except FileNotFoundError:
            logger.warning("FileCheckpoint: 未找到 git 命令")
            return False
        except Exception as e:
            logger.warning("FileCheckpoint: git update-ref 异常: %s", e)
            return False

    def _git_delete_ref(
        self,
        workspace_root: Path,
        ref_name: str,
    ) -> bool:
        """执行 git update-ref -d 删除私有 ref — Stage 6.4 新增

        对标 Cline deleteCheckpointRefs，session 结束时清理 ref，
        避免长期积累导致 git 仓库对象膨胀。

        Args:
            workspace_root: 工作区根目录
            ref_name: ref 路径

        Returns:
            是否成功
        """
        try:
            result = subprocess.run(
                ["git", "update-ref", "-d", ref_name],
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug("FileCheckpoint: git update-ref -d 失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 内部方法 — 持久化
    # ------------------------------------------------------------------

    def _session_file_path(self, session_id: str) -> Path:
        """获取会话 checkpoint 文件路径"""
        safe_name = os.path.basename(session_id)
        return self._persist_dir / f"{safe_name}.json"

    def _generate_checkpoint_id(self, session_id: str, tool_call_id: str) -> str:
        """生成唯一 checkpoint ID"""
        timestamp = int(time.time() * 1000)
        return f"ckpt_{session_id[:8]}_{tool_call_id[:8]}_{timestamp}"

    def _find_checkpoint(self, checkpoint_id: str) -> CheckpointRef | None:
        """在所有 session 的 checkpoint 中查找"""
        # 先尝试从所有已加载 session 查找
        for refs in self._cache.values():
            for ref in refs:
                if ref.checkpoint_id == checkpoint_id:
                    return ref
        # 兜底：扫描磁盘上的所有 session 文件
        for path in self._persist_dir.glob("*.json"):
            session_id = path.stem
            if session_id not in self._cache:
                self._load_session(session_id)
            for ref in self._cache.get(session_id, []):
                if ref.checkpoint_id == checkpoint_id:
                    return ref
        return None

    def _persist_session(self, session_id: str) -> None:
        """持久化会话的 checkpoint 列表到磁盘 — 使用跨进程文件锁保护"""
        import json
        from agent.file_lock import FileLock

        refs = self._cache.get(session_id, [])
        path = self._session_file_path(session_id)
        data = {
            "version": 1,
            "session_id": session_id,
            "checkpoints": [ref.to_dict() for ref in refs],
        }
        try:
            with FileLock(path):
                tmp_path = path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
        except Exception as e:
            logger.error("FileCheckpoint: 持久化 session %s 失败: %s", session_id, e)

    def _load_session(self, session_id: str) -> None:
        """从磁盘加载会话 checkpoint 列表"""
        import json
        from agent.file_lock import FileLock

        path = self._session_file_path(session_id)
        if not path.exists():
            return
        try:
            with FileLock(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            refs = [CheckpointRef.from_dict(r) for r in data.get("checkpoints", [])]
            self._cache[session_id] = refs
        except Exception as e:
            logger.warning("FileCheckpoint: 加载 session %s 失败: %s", session_id, e)


# ============================================================================
# 全局实例 + 工具函数 — 对标 Cline checkpoint service 单例
# ============================================================================

_global_manager: FileCheckpointManager | None = None


def get_checkpoint_manager() -> FileCheckpointManager:
    """获取全局 FileCheckpointManager 单例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = FileCheckpointManager()
    return _global_manager


def set_checkpoint_manager(manager: FileCheckpointManager | None) -> None:
    """替换全局 FileCheckpointManager（用于测试注入）"""
    global _global_manager
    _global_manager = manager


def init_checkpoint_manager(
    persist_dir: str | Path | None = None,
) -> FileCheckpointManager:
    """初始化全局 FileCheckpointManager — 服务启动时调用

    Args:
        persist_dir: 持久化目录，默认 agent_data/file_checkpoints

    Returns:
        初始化后的 FileCheckpointManager 实例
    """
    global _global_manager
    _global_manager = FileCheckpointManager(persist_dir=persist_dir)
    return _global_manager


def create_before_tool_checkpoint_hook(
    session_id: str,
    workspace_root: str | Path,
):
    """创建 before_tool hook，在写工具执行前自动保存 checkpoint

    返回一个异步 hook 函数，可注册到 AgentRuntime._hooks.before_tool。

    用法:
        from agent.checkpoint import create_before_tool_checkpoint_hook
        runtime.register_hooks(AgentHooks(
            before_tool=create_before_tool_checkpoint_hook(
                session_id="sess-1",
                workspace_root="/path/to/project",
            ),
        ))
    """
    from agent.hooks import BeforeToolContext, BeforeToolResult

    async def hook(ctx: BeforeToolContext) -> BeforeToolResult | None:
        if ctx.tool is None:
            return None
        manager = get_checkpoint_manager()
        try:
            manager.save_checkpoint(
                session_id=session_id,
                tool_call_id=ctx.tool_call.tool_call_id,
                tool_name=ctx.tool_call.tool_name,
                tool_input=ctx.input if isinstance(ctx.input, dict) else None,
                workspace_root=workspace_root,
            )
        except Exception as e:
            # checkpoint 失败不应阻塞工具执行
            logger.warning("FileCheckpoint: before_tool hook 异常: %s", e)
        return None

    return hook
