# -*- coding: utf-8 -*-
"""跨进程文件锁 — 对标 Cline acquireSettingsLockSync

Cline 源码位置: sdk/packages/core/src/extensions/mcp/config-loader.ts L263-340

设计原理:
    使用目录创建作为跨进程原子操作（os.mkdir 在所有平台都是原子的）。
    锁目录 `{file_path}.lock` 存在表示锁被持有，不存在表示锁空闲。

    获取流程:
        1. 创建 staging 目录 `{lock_dir}.tmp.{token}`
        2. 在 staging 内写入 owner marker 标识持有者
        3. 原子 rename staging → lock_dir（POSIX 原子，Windows 大多数情况原子）
        4. rename 成功表示获取锁，失败表示锁被他人持有

    释放流程:
        1. 删除 owner marker
        2. rmdir lock_dir

    Stale 接管:
        锁目录存在超过 STALE_MS 毫秒视为持有者崩溃，
        强制 rename aside 后删除，防止永久死锁。

用法:
    from agent.file_lock import FileLock

    lock = FileLock("/path/to/session.json")
    with lock:
        data = read_json()
        data["key"] = "value"
        write_json(data)

对标 Cline:
    - SETTINGS_LOCK_STALE_MS = 10_000
    - SETTINGS_LOCK_POLL_MS = 25
    - tryAcquireSettingsLock / releaseSettingsLock
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any


# 锁目录最长存活时间（毫秒），超过此时间视为 stale 锁，强制接管
# 对标 Cline SETTINGS_LOCK_STALE_MS = 10_000
STALE_MS = 10_000

# 轮询等待锁释放的间隔（毫秒）
# 对标 Cline SETTINGS_LOCK_POLL_MS = 25
POLL_MS = 25


class FileLock:
    """跨进程文件锁 — 对标 Cline acquireSettingsLockSync

    使用目录创建作为原子操作实现跨进程互斥。
    支持上下文管理器（with 语句）和显式 acquire/release。

    属性:
        file_path: 被保护的文件路径
        lock_dir: 锁目录路径（{file_path}.lock）
        timeout_ms: 获取锁的超时时间（毫秒），超时抛 TimeoutError
    """

    def __init__(
        self,
        file_path: str | Path,
        timeout_ms: int = 10_000,
    ) -> None:
        """初始化文件锁

        Args:
            file_path: 被保护的文件路径
            timeout_ms: 获取锁的超时时间（毫秒），默认 10 秒
        """
        self.file_path = Path(file_path)
        self.lock_dir = self.file_path.parent / f"{self.file_path.name}.lock"
        self.timeout_ms = timeout_ms
        self._token: str = ""
        self._owner_file: Path | None = None
        self._acquired: bool = False

    def acquire(self) -> None:
        """获取锁 — 对标 Cline acquireSettingsLockSync

        阻塞直到获取锁或超时。超时抛 TimeoutError。

        流程:
            1. 生成唯一 token 标识本次获取
            2. 轮询尝试 try_acquire
            3. 检测 stale 锁并强制接管
            4. 超时抛 TimeoutError
        """
        self._token = f"{os.getpid()}.{int(time.time() * 1000)}.{uuid.uuid4().hex[:8]}"
        deadline = time.time() + (self.timeout_ms / 1000.0)
        poll_interval = POLL_MS / 1000.0

        while True:
            # 尝试获取锁
            if self._try_acquire():
                self._acquired = True
                return

            # 检测 stale 锁
            if self._is_stale():
                self._takeover_stale()
                # 接管后再次尝试获取
                if self._try_acquire():
                    self._acquired = True
                    return

            # 检查超时
            if time.time() >= deadline:
                raise TimeoutError(
                    f"获取文件锁超时 ({self.timeout_ms}ms): {self.lock_dir}"
                )

            # 等待重试
            time.sleep(poll_interval)

    def release(self) -> None:
        """释放锁 — 对标 Cline releaseSettingsLock

        删除 owner marker 和锁目录。
        如果锁目录已被其他进程接管（owner marker 不匹配），不删除。
        """
        if not self._acquired:
            return

        try:
            # 删除 owner marker
            if self._owner_file is not None and self._owner_file.exists():
                try:
                    self._owner_file.unlink()
                except FileNotFoundError:
                    pass  # 已被其他进程清理

            # 删除锁目录（仅当 owner marker 已删除时）
            if self.lock_dir.exists():
                try:
                    self.lock_dir.rmdir()
                except OSError:
                    # 目录非空或已被其他进程接管，忽略
                    pass
        finally:
            self._acquired = False
            self._owner_file = None

    def _try_acquire(self) -> bool:
        """尝试原子获取锁 — 对标 Cline tryAcquireSettingsLock

        通过 mkdir + rename 实现原子获取:
            1. 创建 staging 目录
            2. 写入 owner marker
            3. rename staging → lock_dir
            4. rename 成功表示获取锁

        Returns:
            True 表示获取成功，False 表示锁被他人持有
        """
        # 确保父目录存在
        self.lock_dir.parent.mkdir(parents=True, exist_ok=True)

        staging_dir = self.lock_dir.parent / f"{self.lock_dir.name}.tmp.{self._token}"
        # 清理可能残留的 staging 目录
        if staging_dir.exists():
            self._rmtree(staging_dir)

        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
            owner_file = staging_dir / f"owner.{self._token}"
            owner_file.write_text(self._token, encoding="utf-8")

            # 原子 rename staging → lock_dir
            # Windows: os.replace 是原子的（Python 3.3+）
            # POSIX: os.rename 在同目录下是原子的
            os.replace(str(staging_dir), str(self.lock_dir))
            self._owner_file = self.lock_dir / f"owner.{self._token}"
            return True
        except FileExistsError:
            # lock_dir 已存在，锁被他人持有
            # 清理 staging 目录
            if staging_dir.exists():
                self._rmtree(staging_dir)
            return False
        except OSError:
            # 其他错误（如权限不足），清理 staging
            if staging_dir.exists():
                self._rmtree(staging_dir)
            return False

    def _is_stale(self) -> bool:
        """检查锁是否过期 — 对标 Cline stale 检测

        通过锁目录的 mtime 判断是否过期。

        Returns:
            True 表示锁已过期（超过 STALE_MS）
        """
        if not self.lock_dir.exists():
            return False
        try:
            mtime_ms = self.lock_dir.stat().st_mtime * 1000
            now_ms = time.time() * 1000
            return (now_ms - mtime_ms) > STALE_MS
        except OSError:
            return False

    def _takeover_stale(self) -> None:
        """强制接管 stale 锁 — 对标 Cline stale 接管

        将 stale 锁目录 rename aside 后删除，防止永久死锁。
        """
        if not self.lock_dir.exists():
            return
        takeover_dir = self.lock_dir.parent / f"{self.lock_dir.name}.stale.{self._token}"
        try:
            os.replace(str(self.lock_dir), str(takeover_dir))
            self._rmtree(takeover_dir)
        except OSError:
            # 接管失败，忽略（其他进程可能已接管）
            pass

    def _rmtree(self, path: Path) -> None:
        """递归删除目录（容错）"""
        try:
            for child in path.iterdir():
                if child.is_dir():
                    self._rmtree(child)
                else:
                    try:
                        child.unlink()
                    except FileNotFoundError:
                        pass
            try:
                path.rmdir()
            except OSError:
                pass
        except FileNotFoundError:
            pass

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


def with_file_lock(
    file_path: str | Path,
    timeout_ms: int = 10_000,
) -> FileLock:
    """创建文件锁上下文管理器 — 便捷工厂函数

    用法:
        with with_file_lock("session.json") as lock:
            # 在锁保护下操作文件
            ...

    Args:
        file_path: 被保护的文件路径
        timeout_ms: 获取锁的超时时间（毫秒）

    Returns:
        FileLock 实例（未获取状态，进入 with 时获取）
    """
    return FileLock(file_path=file_path, timeout_ms=timeout_ms)
