# -*- coding: utf-8 -*-
"""文件 hook 执行器 — Phase 28.3 新增，对标 Cline HookProcess

用 subprocess 执行 hook 脚本：
    1. 将 FileHookContext 序列化为 JSON 通过 stdin 传给脚本
    2. 等待脚本执行完成（带超时）
    3. 根据退出码和 stdout 解析 FileHookResult

脚本退出码协议（Stage 5.3+5.4 对齐 Cline hook-factory.ts）：
    - 0:  执行成功；block 由 stdout JSON 的 cancel:true 字段决定
    - 1:  兼容协议（本系统额外增强）：无 stdout JSON 时视为 block
    - 其他: 执行错误，记录日志但不影响主流程（除非 blocking=true）

Stage 5.3 (P4/P18): blocking 默认值 False（fail-open，与 Cline 对齐）。
Stage 5.4 (P8): block 仅由 stdout JSON 的 cancel:true 字段决定；JSON 优先于退出码。
    stdout JSON 支持 Cline 字段名 contextModification 与本系统字段名 context_injection，
    取值优先级 contextModification > context_injection。

stdout JSON 格式（任意 exit code 都会解析）：
    {"cancel": true, "reason": "阻止原因"}
    {"contextModification": "要注入到模型上下文的文本"}
    {"context_injection": "本系统兼容字段，同 contextModification"}

执行方式按脚本扩展名选择：
    - .py:  python <script>
    - .sh:  bash <script>
    - .js:  node <script>
    - .bat: cmd /c <script>
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from agent.file_hooks.registry import HookProcessRegistry
from agent.file_hooks.types import (
    FileHookConfig,
    FileHookContext,
    FileHookResult,
    HookError,
)

logger = logging.getLogger(__name__)


# 脚本扩展名到解释器的映射
_INTERPRETER_MAP: dict[str, list[str]] = {
    ".py": [sys.executable],  # 当前 Python 解释器
    ".sh": ["bash"],
    ".js": ["node"],
    ".bat": ["cmd", "/c"],
}


async def run_hook(
    config: FileHookConfig,
    context: FileHookContext,
    registry: HookProcessRegistry | None = None,
) -> FileHookResult:
    """执行单个文件 hook 脚本

    Stage 12.4 (P12) 增强:
        - 新增可选 registry 参数，注册进程到 HookProcessRegistry
        - abort 时 registry.kill_all() 可统一终止所有 hook 进程
        - 不传 registry 时退化为原有行为（向后兼容）

    Args:
        config: hook 配置（含脚本路径、超时、blocking 等）
        context: hook 执行上下文（JSON 序列化后通过 stdin 传递）
        registry: 可选的进程注册表，用于 abort 时统一 kill

    Returns:
        FileHookResult: 执行结果（continue/block/error）
    """
    script_path = config.script_path
    if not script_path.exists():
        logger.warning("hook 脚本不存在: %s", script_path)
        return FileHookResult(
            action="error",
            reason=f"hook 脚本不存在: {script_path}",
            exit_code=-1,
        )

    # P1-7: hook 执行前检查 abort_signal — 对标 Cline hook 执行前检查 abort
    # 若 registry 已绑定 abort_signal 且已触发，直接返回 error 结果，
    # 避免启动新进程后又因超时等待才退出
    if registry is not None and registry.is_aborted():
        logger.info(
            "hook 脚本因 abort 跳过执行: %s", script_path.name,
        )
        return FileHookResult(
            action="error" if not config.blocking else "block",
            reason="hook 因用户中止而跳过执行",
            exit_code=-1,
        )

    # 构建命令
    cmd = _build_command(script_path)
    if cmd is None:
        return FileHookResult(
            action="error",
            reason=f"不支持的脚本类型: {script_path.suffix}",
            exit_code=-1,
        )

    # 序列化上下文为 JSON
    context_json = json.dumps(context.to_dict(), ensure_ascii=False, default=str)

    # 子进程环境变量：强制 Python 脚本用 utf-8 输出
    # 避免 Windows 默认 cp936 导致中文 stderr 乱码
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # Stage 12.4 (P12): 生成 hook_id 用于 registry 注册
    hook_id = f"{context.session_id or 'default'}/{script_path.name}/{id(config)}"

    try:
        # 在线程池中执行同步 subprocess，避免阻塞事件循环
        # 使用 asyncio.create_subprocess_exec 实现真正的异步
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_path.parent),
            env=env,
        )

        # Stage 12.4 (P12): 注册进程到 registry（若提供）
        if registry is not None:
            await registry.register(hook_id, process)

        # P2-22: 将 process.communicate() 改为逐行读取 stdout/stderr，
        # 实时发射进度事件（每行输出立即记录日志），替代原每 5s 周期性进度反馈。
        # 对标 Cline hook 执行中的实时输出流式采集。
        # 写入 stdin（上下文 JSON）后关闭，让脚本可从 stdin 读取
        try:
            process.stdin.write(context_json.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            # 脚本可能已退出并关闭 stdin，忽略写入失败
            pass

        # 逐行读取 stdout / stderr，实时记录日志
        stdout_task = asyncio.ensure_future(
            _read_stream(process.stdout, "stdout", script_path.name)
        )
        stderr_task = asyncio.ensure_future(
            _read_stream(process.stderr, "stderr", script_path.name)
        )
        try:
            stdout_text, stderr_text = await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task),
                timeout=float(config.timeout),
            )
            # 两个流都读到 EOF 后，等待进程退出以获取 returncode
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            # 超时：取消读取任务并终止进程
            stdout_task.cancel()
            stderr_task.cancel()
            try:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                pass
            logger.warning(
                "hook 脚本执行超时（%ds）: %s",
                config.timeout, script_path.name,
            )
            return FileHookResult(
                action="error" if not config.blocking else "block",
                reason=f"hook 脚本执行超时（{config.timeout}秒）",
                exit_code=-1,
            )
        finally:
            # 确保读取任务被清理（成功路径已 done，cancel 为 no-op）
            if not stdout_task.done():
                stdout_task.cancel()
            if not stderr_task.done():
                stderr_task.cancel()
            # Stage 12.4 (P12): 无论成功/失败/超时，从 registry 注销
            if registry is not None:
                await registry.unregister(hook_id)

        exit_code = process.returncode
        stdout_text = (stdout_text or "").strip()
        stderr_text = (stderr_text or "").strip()

        # Stage 5.4 (P8): 优先解析 stdout JSON — 对标 Cline hook-factory.ts L454-499
        # "If we have valid JSON, honor it regardless of exit code"
        stdout_json = _parse_stdout_json(stdout_text)
        if stdout_json is not None:
            # 有有效 JSON：按 JSON 决定，无视退出码
            # 检查 cancel: true（Cline 字段）或 block: true（本系统兼容字段）
            if stdout_json.get("cancel") is True or stdout_json.get("block") is True:
                reason = (
                    stdout_json.get("reason")
                    or stderr_text
                    or f"hook {script_path.name} blocked execution via JSON cancel"
                )
                logger.info(
                    "hook 脚本 JSON 阻止执行: %s, reason=%s, exit_code=%d",
                    script_path.name, reason, exit_code,
                )
                return FileHookResult(
                    action="block",
                    reason=reason,
                    context_injection="",
                    exit_code=exit_code,
                )
            # 否则 continue，解析 context_injection / contextModification
            # 取值优先级：contextModification > context_injection（向 Cline 对齐）
            context_injection = ""
            ctx_mod = stdout_json.get("contextModification")
            if isinstance(ctx_mod, str) and ctx_mod:
                context_injection = ctx_mod
            else:
                ctx_inj = stdout_json.get("context_injection")
                if isinstance(ctx_inj, str) and ctx_inj:
                    context_injection = ctx_inj
            return FileHookResult(
                action="continue",
                context_injection=context_injection,
                exit_code=exit_code,
            )

        # 无 stdout JSON：按退出码处理
        if exit_code == 0:
            # exit 0 + 无 JSON → continue（无 context_injection）
            return FileHookResult(
                action="continue",
                context_injection="",
                exit_code=exit_code,
            )
        elif exit_code == 1:
            # Stage 5.4 (P8): exit 1 + 无 JSON → block（本系统兼容协议，非 Cline 协议）
            # 保留原 exit 1 = block 兼容性，作为本系统额外增强
            reason = stderr_text or f"hook {script_path.name} blocked execution (exit 1)"
            logger.info(
                "hook 脚本 exit 1 阻止执行（兼容协议，建议改用 JSON cancel:true）: %s, reason=%s",
                script_path.name, reason,
            )
            return FileHookResult(
                action="block",
                reason=reason,
                exit_code=exit_code,
            )
        else:
            # 其他错误码 + 无 JSON → error（结合 5.3 fail-open 默认不阻止）
            error_msg = stderr_text or f"hook 退出码 {exit_code}"
            logger.warning(
                "hook 脚本执行错误: %s, exit_code=%d, stderr=%s",
                script_path.name, exit_code, error_msg[:200],
            )
            # blocking=true 时，错误也视为 block（保留原逻辑）
            action = "block" if config.blocking else "error"
            return FileHookResult(
                action=action,
                reason=error_msg,
                exit_code=exit_code,
            )

    except FileNotFoundError as e:
        # 解释器不存在（如 bash 在 Windows 上可能不存在）
        logger.warning("hook 解释器不存在: %s", e)
        return FileHookResult(
            action="error",
            reason=f"hook 解释器不存在: {e}",
            exit_code=-1,
        )
    except Exception as e:
        logger.exception("hook 脚本执行异常: %s", script_path.name)
        return FileHookResult(
            action="error" if not config.blocking else "block",
            reason=f"hook 执行异常: {e}",
            exit_code=-1,
        )


async def _read_stream(
    stream: asyncio.StreamReader,
    stream_name: str,
    hook_name: str,
) -> str:
    """逐行读取子进程输出流，实时记录日志 — P2-22 新增

    替代 process.communicate() 的一次性读取，改为逐行 readline()，
    每读到一行立即 logger.info 输出，实现实时进度反馈（对标 Cline hook
    执行中的流式输出采集）。

    读到 EOF（空 bytes）时结束，返回所有行拼接的文本。

    Args:
        stream: 子进程的 stdout 或 stderr StreamReader
        stream_name: 流名称（"stdout" / "stderr"），用于日志标识
        hook_name: hook 脚本名（用于日志）

    Returns:
        拼接后的输出文本（行间用 \\n 分隔，不含末尾换行）
    """
    lines: list[str] = []
    while True:
        line_bytes = await stream.readline()
        if not line_bytes:
            break
        # 解码为文本，去除行尾换行符
        decoded = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
        if decoded:
            # 实时发射进度事件：每行输出立即记录日志
            logger.info("hook %s %s: %s", hook_name, stream_name, decoded)
            lines.append(decoded)
    return "\n".join(lines)


def _build_command(script_path: Path) -> list[str] | None:
    """构建脚本执行命令

    按脚本扩展名选择解释器：
        - .py:  [python, script.py]
        - .sh:  [bash, script.sh]
        - .js:  [node, script.js]
        - .bat: [cmd, /c, script.bat]

    Args:
        script_path: 脚本文件路径

    Returns:
        命令列表，或 None（不支持的扩展名）
    """
    ext = script_path.suffix.lower()
    interpreter = _INTERPRETER_MAP.get(ext)
    if interpreter is None:
        return None
    return [*interpreter, str(script_path)]


def _parse_stdout_json(stdout_text: str) -> dict[str, Any] | None:
    """解析 stdout 文本为 JSON 字典 — Stage 5.4 (P8) 新增

    对标 Cline hook-factory.ts L454-499 的 parsedOutput 解析逻辑。
    P2-43: 两阶段鲁棒提取:
        1. 阶段一: 直接 json.loads 整个 stdout（处理纯 JSON 输出）
        2. 阶段二: 正则提取第一个 {...} 块再解析（处理 JSON 前后
           混有日志/调试文本的输出，对标 Cline 鲁棒性解析）

    Args:
        stdout_text: 脚本 stdout 文本（已 strip）

    Returns:
        dict 或 None（两阶段均解析失败或非 dict 时返回 None）
    """
    if not stdout_text:
        return None
    # 阶段一: 直接解析（纯 JSON 输出场景）
    try:
        parsed = json.loads(stdout_text)
        if isinstance(parsed, dict):
            return parsed
        return None
    except (json.JSONDecodeError, ValueError):
        pass
    # 阶段二: 正则提取第一个 {...} JSON 块（混合输出场景）
    # 贪婪匹配从首个 { 到末个 }，覆盖嵌套对象；提取失败则返回 None
    match = re.search(r"\{[\s\S]*\}", stdout_text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
