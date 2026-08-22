# -*- coding: utf-8 -*-
"""批量命令执行工具 — 对标 Cline RunCommandsInputSchema + bash.ts

接收命令数组，并行执行，每条命令独立返回结果。
结构化命令数组的优势:
    - LLM 更易生成（结构化数组）
    - 单条失败不影响其他命令
    - 每条命令独立 timeout 和 exit_code
    - token 效率高（避免重复工具调用开销）

工作流程:
    1. LLM 调用 run_commands(commands=["cmd1", "cmd2", ...])
    2. 工具用 asyncio.gather 并行执行所有命令（对标 Cline Promise.all）
    3. 每条命令独立超时控制（默认 30 秒，对标 Cline bash.ts DEFAULT_TIMEOUT）
    4. 返回 {results: [{command, stdout, stderr, exit_code}, ...]}

安全设计:
    - 危险命令模式拦截（rm -rf /, mkfs, dd 等）— Charles 合理增强
    - 单次最多 10 条命令
    - 单条命令输出上限 48000 字符（head+tail 截断，对标 Cline）
    - PYTHONUNBUFFERED=1 确保实时输出（项目约束）

对标 Cline:
    - sdk/packages/core/src/extensions/tools/schemas.ts RunCommandsInputSchema
    - sdk/packages/core/src/extensions/tools/executors/bash.ts
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any

from agent.abort import AbortedError
from agent.tools.base import BaseTool
from agent.tools.constants import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    MAX_COMMANDS,
    MAX_COMMAND_TIMEOUT_SECONDS,
    MAX_OUTPUT_PER_COMMAND,
    MAX_STDERR_PER_COMMAND,
)
from agent.tools.truncate import truncate_output
from agent.types import AgentToolContext, AgentToolResult


class RunCommandsTool(BaseTool):
    """批量命令执行工具 — 对标 Cline run_commands tool

    参数:
        commands: 命令字符串数组（必填，最多 10 条）
    """

    # Phase 31.5: 常量统一到 agent.tools.constants — 对标 Cline output-limits.ts
    # 保留类属性作为向后兼容别名，值来自 constants 模块
    _MAX_COMMANDS = MAX_COMMANDS
    _MAX_OUTPUT_PER_COMMAND = MAX_OUTPUT_PER_COMMAND
    _MAX_STDERR_PER_COMMAND = MAX_STDERR_PER_COMMAND
    _DEFAULT_TIMEOUT = DEFAULT_COMMAND_TIMEOUT_SECONDS
    _MAX_TIMEOUT = MAX_COMMAND_TIMEOUT_SECONDS

    # 危险命令模式 — Charles 合理增强，对标 Cline 危险命令拦截
    # 用于 _guard_command 安全检查，匹配则拒绝执行
    _DENY_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+~",
        r"rm\s+-rf\s+\*",
        r"mkfs\.",
        r"dd\s+if=.*of=/dev/",
        r">\s*/dev/sd",
        r"shutdown",
        r"reboot",
        r"format\s+[a-z]:",
    ]

    def __init__(self, working_dir: str | None = None) -> None:
        self._working_dir = working_dir or os.getcwd()

    @property
    def name(self) -> str:
        return "run_commands"

    @property
    def description(self) -> str:
        return (
            "批量执行命令行命令。每条命令独立执行并返回 stdout/stderr/exit_code。"
            "适合运行 Python 脚本、系统命令等。"
            "参数: commands(必填): 命令字符串数组，并行执行，例如 [\"ls -la\", \"git status\"]，最多 10 条; "
            "timeout(可选): 单条命令超时秒数，默认 30 秒，最大 600 秒。"
            "RAG 查询/PDF 下载/索引构建等长任务务必设置 timeout=120~300，避免默认 30 秒超时中断。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要执行的命令数组，并行执行",
                    "maxItems": 10,
                },
                "timeout": {
                    "type": "number",
                    "description": f"单条命令超时时间（秒），默认 {self._DEFAULT_TIMEOUT} 秒，最大 {self._MAX_TIMEOUT} 秒。RAG/下载/索引构建等长任务建议设为 120~300 秒。",
                    "minimum": 1,
                    "maximum": self._MAX_TIMEOUT,
                },
            },
            "required": ["commands"],
        }

    @property
    def timeout_ms(self) -> int | None:
        # 工具级超时 = MAX_COMMAND_TIMEOUT_SECONDS（600秒），与最大命令级超时对齐
        # 原因: 原来返回 DEFAULT_TIMEOUT*1000（30秒），与命令级 timeout 参数冲突，
        #   即使 LLM 设了 timeout=120，runtime 仍会在 30s 后杀掉整个调用，
        #   导致命令已完成但工具报超时。
        # 现在工具级超时设为 600 秒（最大命令级超时），确保不会 premature kill：
        #   - 简单命令: 命令级超时（默认30s）先生效，工具级超时不会触发
        #   - 长任务: LLM 设 timeout=120~600，命令级超时先生效
        #   - 安全兜底: 600 秒后仍未完成则强制超时
        return self._MAX_TIMEOUT * 1000

    @property
    def requires_approval(self) -> bool:
        """执行命令需要用户审批 — Phase 19"""
        return True

    async def _execute(
        self,
        input: dict[str, Any],
        context: AgentToolContext,
    ) -> AgentToolResult:
        """执行批量命令 — 对标 Cline run_commands.execute()

        P1-11: 多条命令用 asyncio.gather 并行执行（对标 Cline Promise.all）
        单条命令失败不影响其他命令，结果按 index 顺序返回。
        """
        commands = input.get("commands", [])

        if not commands:
            return AgentToolResult(
                output={"error": "commands 不能为空"},
                is_error=True,
            )

        if len(commands) > self._MAX_COMMANDS:
            return AgentToolResult(
                output={
                    "error": f"命令数超过上限 {self._MAX_COMMANDS}",
                    "received": len(commands),
                },
                is_error=True,
            )

        # 准备环境变量 — PYTHONUNBUFFERED=1 确保实时输出（项目约束）
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        # 获取命令级超时（秒），默认使用工具级默认值
        timeout_seconds = input.get("timeout")
        if timeout_seconds is None:
            timeout_seconds = self._DEFAULT_TIMEOUT
        else:
            timeout_seconds = float(timeout_seconds)
            timeout_seconds = max(1.0, min(timeout_seconds, self._MAX_TIMEOUT))

        # P1-11: 并行执行所有命令 — 对标 Cline Promise.all
        # 单条失败不影响其他命令，结果按 index 顺序收集
        # 中止信号在每条命令内部检查（_wait_process_with_abort_stream）
        async def _run_one(idx: int, cmd: str) -> dict[str, Any]:
            # 安全检查 — 危险命令拦截（Charles 合理增强）
            guard_error = self._guard_command(cmd)
            if guard_error:
                return {
                    "index": idx,
                    "command": cmd,
                    "error": guard_error,
                    "exit_code": -1,
                }
            return await self._execute_single(cmd, env, idx, context, timeout_seconds)

        # 启动所有命令并行执行
        tasks = [
            asyncio.ensure_future(_run_one(idx, cmd))
            for idx, cmd in enumerate(commands)
        ]

        # gather 等待所有命令完成，return_exceptions=True 确保单条失败不影响其他
        # 对标 Cline Promise.allSettled 语义（单条失败不传播异常）
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果：异常转为错误字典，正常结果直接收集
        results: list[dict[str, Any]] = []
        for idx, item in enumerate(gathered):
            if isinstance(item, BaseException):
                # AbortedError 向上传播（用户中止应立即生效）
                if isinstance(item, AbortedError):
                    raise item
                # CancelledError 或其他 BaseException 转为错误结果
                # （CancelledError 可能来自超时后 wait_task 被取消的场景）
                results.append({
                    "index": idx,
                    "command": commands[idx],
                    "error": f"命令执行异常: {type(item).__name__}: {item}",
                    "exit_code": -1,
                })
            else:
                results.append(item)

        return AgentToolResult(
            output={"results": results},
            metadata={
                "total_commands": len(commands),
                "succeeded": sum(1 for r in results if r.get("exit_code") == 0),
                "failed": sum(1 for r in results if r.get("exit_code") != 0),
            },
        )

    async def _execute_single(
        self,
        command: str,
        env: dict[str, str],
        index: int,
        context: AgentToolContext | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """执行单条命令 — 对标 Cline bash.ts executor

        Phase 28.2: 通过 asyncio.wait 将进程通信与 abort_signal 组合等待，
        实现长耗时命令的即时中止。

        Stage 12.1 (G2.3/G2.4/G2.5):
            - G2.3 超时不再抛错，返回部分输出 + timed_out 标记
            - G2.4 超时/中止时走 _graceful_kill（先 SIGTERM 等 1 秒，再 SIGKILL）
            - G2.5 输出截断改为首尾各一半，并标记 truncated

        实时终端输出:
            - 长耗时命令（如 read-pdf 下载/索引构建）执行期间，
              通过 context.emit_update 实时推送 stdout/stderr 到前端
            - 前端显示"终端输出"面板，让用户像 TRAE 一样监控进度
        """
        emit_update = getattr(context, "emit_update", None) if context else None
        command_id = f"cmd_{index}_{id(asyncio.current_task())}"
        process: asyncio.subprocess.Process | None = None
        stdout_task: asyncio.Task | None = None
        stderr_task: asyncio.Task | None = None

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=env,
                # P2-6: Linux 下创建独立进程组（setsid），使 killpg 可杀整个进程树；
                # Windows 下此参数被忽略，进程树 kill 改用 taskkill /T /F
                start_new_session=True,
            )

            # 实时流式读取 stdout/stderr，同时累积完整输出
            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []

            async def _read_stream(stream: asyncio.StreamReader | None, is_stderr: bool) -> None:
                """实时读取子进程输出流并推送前端"""
                if stream is None:
                    return
                while True:
                    try:
                        line = await stream.readline()
                        if not line:
                            break
                        if is_stderr:
                            stderr_chunks.append(line)
                        else:
                            stdout_chunks.append(line)
                        # 实时推送到前端
                        if emit_update is not None:
                            try:
                                text = line.decode("utf-8", errors="replace")
                                emit_update({
                                    "terminal_output": {
                                        "command_id": command_id,
                                        "command": command,
                                        "index": index,
                                        "text": text,
                                        "is_stderr": is_stderr,
                                        "finished": False,
                                    }
                                })
                            except Exception:
                                pass
                    except Exception:
                        break

            stdout_task = asyncio.ensure_future(_read_stream(process.stdout, False))
            stderr_task = asyncio.ensure_future(_read_stream(process.stderr, True))

            # 等待进程结束或超时/中止
            timed_out = await self._wait_process_with_abort_stream(
                process, context, command_id, command, index, emit_update,
                timeout_seconds=timeout_seconds or self._DEFAULT_TIMEOUT,
            )

            # 确保读取任务完成
            try:
                await asyncio.wait_for(asyncio.gather(stdout_task, stderr_task), timeout=5.0)
            except asyncio.TimeoutError:
                stdout_task.cancel()
                stderr_task.cancel()

            stdout = b"".join(stdout_chunks)
            stderr = b"".join(stderr_chunks)

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # 推送命令结束标记
            if emit_update is not None:
                try:
                    emit_update({
                        "terminal_output": {
                            "command_id": command_id,
                            "command": command,
                            "index": index,
                            "text": "",
                            "is_stderr": False,
                            "finished": True,
                            "exit_code": process.returncode if process.returncode is not None else -1,
                            "timed_out": timed_out,
                        }
                    })
                except Exception:
                    pass

            # G2.5 输出截断 — 首尾各一半，保留头部和尾部
            stdout_text, stdout_truncated = self._truncate_output(
                stdout_text, self._MAX_OUTPUT_PER_COMMAND
            )
            stderr_text, stderr_truncated = self._truncate_output(
                stderr_text, self._MAX_STDERR_PER_COMMAND
            )

            result: dict[str, Any] = {
                "index": index,
                "command": command,
                "stdout": stdout_text,
                "stderr": stderr_text if stderr_text.strip() else "",
                "exit_code": process.returncode if process.returncode is not None else -1,
                "timed_out": timed_out,
                "truncated": stdout_truncated or stderr_truncated,
            }

            # G2.3 超时标记：在 output 中追加 [timeout after Ns]
            if timed_out:
                used_timeout = timeout_seconds if timeout_seconds is not None else self._DEFAULT_TIMEOUT
                result["stdout"] = (
                    (stdout_text + "\n") if stdout_text else ""
                ) + f"[timeout after {used_timeout}s]"
                result["exit_code"] = -1

            return result

        except AbortedError:
            # 中止异常向上传播，由 runtime 统一处理状态
            # 但先确保子进程被清理（避免僵尸进程）
            try:
                if 'process' in locals() and process.returncode is None:
                    await self._graceful_kill(process)
            except Exception:
                pass
            raise
        except Exception as e:
            return {
                "index": index,
                "command": command,
                "error": f"命令执行失败: {e}",
                "exit_code": -1,
            }
        finally:
            # 确保子进程资源在 event loop 关闭前被清理，避免 Windows ProactorEventLoop
            # 退出时因 transport __del__ 调用 closed loop 而报 RuntimeError。
            await self._cleanup_process(process, stdout_task, stderr_task)

    async def _graceful_kill(self, process: asyncio.subprocess.Process) -> None:
        """优雅终止子进程 — Stage 12.1 (G2.4) 新增，对标 Cline 优雅 kill

        先发送 SIGTERM（Windows 上为 TerminateProcess）等待 1 秒，
        若进程仍未结束则发送 SIGKILL 强制终止。

        P2-6 增强: 改为进程树 kill，确保子进程（如 shell 派生的子进程）一并终止:
            - Linux 优雅步: os.killpg(os.getpgid(pid), SIGTERM) 对整个进程组发信号
            - Linux 强制步: os.killpg(os.getpgid(pid), SIGKILL) 强制杀进程组
            - Windows 强制步: taskkill /T /F /PID 杀整个进程树
            （Windows 优雅步仍用 process.terminate()，无原生优雅树 kill）

        设计要点:
            - POSIX: SIGTERM 让子进程有机会清理（如 flush 缓冲、关闭连接）
            - Windows: 无 SIGTERM 概念，proc.terminate() 等价 TerminateProcess
            - 1 秒等待是 Cline 的默认值，平衡清理时间与响应速度
            - 强制 kill 后再 wait 避免 zombie 进程
            - start_new_session=True 确保子进程在独立进程组中（_execute_single 中设置）

        Args:
            process: asyncio 子进程对象
        """
        try:
            if sys.platform == "win32":
                # Windows 无 SIGTERM，terminate() 调用 TerminateProcess（仅父进程）
                process.terminate()
            else:
                # P2-6: Linux 优雅步 — 对整个进程组发 SIGTERM（进程树 kill）
                self._kill_process_tree(process, force=False)
        except ProcessLookupError:
            # 进程已退出，无需处理
            return

        try:
            await asyncio.wait_for(process.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            # 1 秒后仍未结束，强制 kill 整个进程树
            try:
                self._kill_process_tree(process, force=True)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    def _kill_process_tree(self, process: asyncio.subprocess.Process, force: bool = True) -> None:
        """进程树 kill — P2-6 新增，对标 Cline 进程树终止

        杀死进程及其所有子进程，避免子进程（如 shell 派生的子进程）成为孤儿进程。

        平台实现:
            - Windows: taskkill /T /F /PID <pid>
                /T = 终止指定进程及其子进程（树）
                /F = 强制终止（对应 force=True）
            - Linux: os.killpg(os.getpgid(pid), signal.SIGKILL/SIGTERM)
                依赖 _execute_single 中 start_new_session=True 创建的独立进程组
                force=True 发 SIGKILL，force=False 发 SIGTERM

        Args:
            process: asyncio 子进程对象
            force: True=强制终止(SIGKILL/taskkill /F)，False=优雅终止(SIGTERM)
        """
        pid = process.pid
        if sys.platform == "win32":
            # Windows: taskkill /T /F /PID 杀整个进程树
            import subprocess
            cmd = ["taskkill", "/T", "/PID", str(pid)]
            if force:
                cmd.insert(1, "/F")
            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                # taskkill 失败时回退到 process.terminate()/kill()
                try:
                    if force:
                        process.kill()
                    else:
                        process.terminate()
                except ProcessLookupError:
                    pass
        else:
            # Linux: 对整个进程组发信号（进程树 kill）
            try:
                pgid = os.getpgid(pid)
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.killpg(pgid, sig)
            except ProcessLookupError:
                # 进程/进程组已不存在
                pass

    async def _cleanup_process(
        self,
        process: asyncio.subprocess.Process | None,
        stdout_task: asyncio.Task | None,
        stderr_task: asyncio.Task | None,
    ) -> None:
        """清理子进程资源 — 避免 Windows ProactorEventLoop 退出时 transport 泄漏

        在 _execute_single 的 finally 中调用，确保：
        1. 取消并等待 stdout/stderr 读取任务；
        2. 若子进程仍在运行则强制终止并 wait；
        3. 显式关闭底层 transport，释放 Proactor pipe 资源。
        """
        if stdout_task is not None and not stdout_task.done():
            stdout_task.cancel()
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()

        try:
            if stdout_task is not None or stderr_task is not None:
                await asyncio.gather(
                    stdout_task if stdout_task is not None else asyncio.sleep(0),
                    stderr_task if stderr_task is not None else asyncio.sleep(0),
                    return_exceptions=True,
                )
        except Exception:
            pass

        if process is not None and process.returncode is None:
            try:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                pass

        # 显式关闭 transport，避免 event loop 关闭后 GC 触发 __del__ 报错
        transport = getattr(process, "_transport", None)
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    def _truncate_output(self, text: str, limit: int) -> tuple[str, bool]:
        """输出截断 — Stage 12.1 (G2.5) 新增，对标 Cline 首尾各一半截断

        超过 limit 时保留首尾各一半（limit/2），中间用省略标记连接。
        相比仅保留头部，首尾各一半能让 LLM 看到命令的开头输出和最终错误信息。

        P2-8: 实际截断逻辑委托给公共 truncate_output 函数，统一截断策略与标记格式。
        保留 (text, bool) 返回签名以兼容现有调用方。

        Args:
            text: 原始输出文本
            limit: 字符上限

        Returns:
            (截断后的文本, 是否被截断)
        """
        if len(text) <= limit:
            return text, False
        return truncate_output(text, limit), True

    async def _wait_process_with_abort(
        self,
        process: asyncio.subprocess.Process,
        context: AgentToolContext | None,
    ) -> tuple[bytes, bytes, bool]:
        """等待进程完成（同步读取输出版本）— 供外部直接调用兼容使用

        当前 _execute_single 已改用流式读取，此方法保留给需要 capture_output 的场景。
        """
        comm_task = asyncio.ensure_future(process.communicate())

        # 若无 abort_signal，退化为带超时的 communicate
        sig = getattr(context, "abort_signal", None) if context else None
        if sig is None:
            try:
                stdout, stderr = await asyncio.wait_for(
                    comm_task, timeout=self._DEFAULT_TIMEOUT
                )
                return stdout, stderr, False
            except asyncio.TimeoutError:
                # G2.3/G2.4: 超时优雅 kill 后返回部分输出
                await self._graceful_kill(process)
                stdout, stderr = await comm_task
                return stdout, stderr, True

        abort_task = asyncio.ensure_future(sig.wait())

        try:
            done, pending = await asyncio.wait(
                {comm_task, abort_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=self._DEFAULT_TIMEOUT,
            )

            # 超时：G2.3/G2.4 优雅 kill 后返回部分输出
            if not done:
                abort_task.cancel()
                await self._graceful_kill(process)
                stdout, stderr = await comm_task
                return stdout, stderr, True

            # abort 先触发：终止进程并抛出
            if abort_task in done:
                comm_task.cancel()
                try:
                    await self._graceful_kill(process)
                except Exception:
                    pass
                raise AbortedError("aborted by user")

            # communicate 正常完成
            abort_task.cancel()
            stdout, stderr = comm_task.result()
            return stdout, stderr, False

        except asyncio.CancelledError:
            comm_task.cancel()
            abort_task.cancel()
            raise

    async def _wait_process_with_abort_stream(
        self,
        process: asyncio.subprocess.Process,
        context: AgentToolContext | None,
        command_id: str,
        command: str,
        index: int,
        emit_update: Any,
        timeout_seconds: float | None = None,
    ) -> bool:
        """等待进程完成（流式输出版本）— 实时终端监控

        stdout/stderr 已由独立任务实时读取，这里只等待进程退出，
        同时处理 abort_signal 和超时。

        Args:
            timeout_seconds: 命令超时时间（秒），None 则使用默认值

        Returns:
            timed_out: 是否超时
        """
        timeout = timeout_seconds if timeout_seconds is not None else self._DEFAULT_TIMEOUT
        wait_task = asyncio.ensure_future(process.wait())

        # 若无 abort_signal，退化为带超时的 wait
        sig = getattr(context, "abort_signal", None) if context else None
        if sig is None:
            try:
                await asyncio.wait_for(wait_task, timeout=timeout)
                return False
            except asyncio.TimeoutError:
                # G2.3/G2.4: 超时优雅 kill
                await self._graceful_kill(process)
                try:
                    await wait_task
                except Exception:
                    pass
                return True

        abort_task = asyncio.ensure_future(sig.wait())

        try:
            done, pending = await asyncio.wait(
                {wait_task, abort_task},
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout,
            )

            # 超时：G2.3/G2.4 优雅 kill
            if not done:
                abort_task.cancel()
                await self._graceful_kill(process)
                try:
                    await wait_task
                except Exception:
                    pass
                return True

            # abort 先触发：终止进程并抛出
            if abort_task in done:
                wait_task.cancel()
                try:
                    await self._graceful_kill(process)
                except Exception:
                    pass
                raise AbortedError("aborted by user")

            # 进程正常完成
            abort_task.cancel()
            return False

        except asyncio.CancelledError:
            wait_task.cancel()
            abort_task.cancel()
            raise

    def _guard_command(self, command: str) -> str | None:
        """安全检查 — Charles 合理增强，对标 Cline 危险命令拦截

        检查命令是否匹配危险模式，匹配则拒绝执行。
        """
        cmd = command.strip().lower()
        for pattern in self._DENY_PATTERNS:
            if re.search(pattern, cmd):
                return "命令被安全检查阻止（检测到危险模式）"
        return None
