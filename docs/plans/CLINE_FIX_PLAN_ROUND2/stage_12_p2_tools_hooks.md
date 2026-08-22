# Stage 12: P2 工具与文件 Hooks 补全方案

> 生成时间：2026-07-26
> 优先级：P2
> 预估工作量：1.5 周
> 依赖：Stage 9 完成（9.2 subprocess kill on abort 是 G2.3-G2.5 的基础）
>
> 来源：
> - `CLINE_DIFF/SUMMARY_v2.md` §3.2 P2 级剩余差距 #11-#13、#21-#22
> - `CLINE_DIFF/phase_G_builtin_tools_file_cmd_edit.md`（G2.3 / G2.4 / G2.5 / G4.1 / G4.2 / G4.5）
> - `CLINE_DIFF/phase_P_file_hooks.md`（P9 / P11 / P12 / P14 / P16）
>
> 涉及源文件：
> - 我的：`agent/tools/run_commands.py`、`agent/tools/apply_patch.py`、`agent/file_hooks.py`、`agent/runtime.py`、`agent/types.py`
> - Cline：`third_party/cline/sdk/packages/core/src/extensions/tools/executors/`、`third_party/cline/apps/vscode/src/core/hooks/`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 12.1 | run_commands 运行时行为（超时/kill/截断） | G2.3 / G2.4 / G2.5 | P2 | agent/tools/run_commands.py |
| 12.2 | apply_patch 鲁棒性（Unicode/上下文匹配） | G4.1 / G4.2 / G4.5 | P2 | agent/tools/apply_patch.py |
| 12.3 | context-injection before_tool 实际注入 | P9 | P2 | agent/file_hooks.py、agent/runtime.py |
| 12.4 | Hook 基础设施（HookError/HookProcessRegistry/模板） | P11 / P12 / P14 | P2 | agent/file_hooks.py、agent/types.py |
| 12.5 | hook 并发执行 | P16 | P2 | agent/file_hooks.py |

依赖关系：
- 12.1 依赖 9.2（subprocess kill on abort）
- 12.2 / 12.3 / 12.4 / 12.5 互相独立，可并行
- 建议执行顺序：12.1 → 12.2 → 12.4 → 12.3 → 12.5

---

## 12.1 run_commands 运行时行为（G2.3 / G2.4 / G2.5）

### 任务背景

来源 Phase G #G2.3 / G2.4 / G2.5。当前 `run_commands` 工具与 Cline 的 `exec_tool` 在运行时行为上有 3 项差距：

1. **G2.3 超时行为**：当前超时后 kill 子进程并抛 `TimeoutExpired`，但不输出已捕获的 stdout/stderr。Cline 在超时后返回部分输出 + 超时标记。
2. **G2.4 kill 信号**：当前用 `proc.kill()`（SIGKILL on POSIX, TerminateProcess on Windows），未给子进程清理机会。Cline 先 SIGTERM 等 1 秒，再 SIGKILL。
3. **G2.5 输出截断**：当前无输出长度限制，超长输出（如 `python preprocess.py` 输出 100MB 日志）会撑爆上下文。Cline 有 `MAX_OUTPUT_LENGTH=30000` 截断。

### 目标

对齐 Cline 的运行时行为：
1. 超时后返回部分输出 + 超时标记（不抛错）
2. kill 时先 SIGTERM 等 1 秒，再 SIGKILL（POSIX）/ TerminateProcess（Windows）
3. 输出超过 30000 字符时截断，保留首尾各 15000 字符

### 当前实现位置

- `agent/tools/run_commands.py`（`_run_subprocess` 函数、`run_commands` 工具入口）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/executors/exec-tool.ts`（`execTool` 实现）

### 修复步骤建议

1. **G2.3 超时返回部分输出**
   - 当前 `_run_subprocess` 超时时：
     ```python
     try:
         stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
     except asyncio.TimeoutError:
         proc.kill()
         raise TimeoutExpired(...)  # 直接抛错，丢失输出
     ```
   - 改为：
     ```python
     try:
         stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
     except asyncio.TimeoutError:
         await self._graceful_kill(proc)  # G2.4 优雅 kill
         # 读取已捕获的输出（communicate 在超时后仍可获取部分输出）
         stdout = proc.stdout.read() if proc.stdout else ""
         stderr = proc.stderr.read() if proc.stderr else ""
         return RunResult(
             stdout=stdout,
             stderr=stderr,
             exit_code=-1,
             timed_out=True,  # 新增字段
         )
     ```
   - 工具结果以 `is_error=False` 返回（超时不算错误），LLM 可看到部分输出
   - 在 output 中追加 `\n[timeout after {timeout}s]` 标记

2. **G2.4 优雅 kill**
   - 新增 `_graceful_kill(proc)` 方法：
     ```python
     async def _graceful_kill(self, proc: asyncio.subprocess.Process) -> None:
         """先 SIGTERM 等 1 秒，再 SIGKILL"""
         if sys.platform == "win32":
             proc.terminate()  # Windows 无 SIGTERM，用 TerminateProcess
         else:
             proc.send_signal(signal.SIGTERM)
         try:
             await asyncio.wait_for(proc.wait(), timeout=1.0)
         except asyncio.TimeoutError:
             proc.kill()  # 强制 SIGKILL
             await proc.wait()
     ```
   - 替换原有的 `proc.kill()` 直接调用
   - 9.2 的 abort signal 触发时也走 `_graceful_kill`（统一 kill 路径）

3. **G2.5 输出截断**
   - 在 `run_commands` 工具入口处，构造返回结果前截断：
     ```python
     MAX_OUTPUT_LENGTH = 30000
     HALF = MAX_OUTPUT_LENGTH // 2

     def _truncate_output(text: str) -> str:
         if len(text) <= MAX_OUTPUT_LENGTH:
             return text
         head = text[:HALF]
         tail = text[-HALF:]
         omitted = len(text) - MAX_OUTPUT_LENGTH
         return f"{head}\n\n[... {omitted} characters omitted ...]\n\n{tail}"
     ```
   - stdout / stderr 各自独立截断（不合并）
   - 截断后追加 `[output truncated, original length: {len}]` 标记

4. **`RunResult` 类型扩展**
   - 在 `agent/tools/run_commands.py` 中扩展 `RunResult` dataclass：
     ```python
     @dataclass
     class RunResult:
         stdout: str
         stderr: str
         exit_code: int
         timed_out: bool = False  # 新增
         truncated: bool = False  # 新增
     ```
   - 工具入口根据 `timed_out` / `truncated` 标记构造不同的 `ToolResultPart`

### 验证方法

1. **G2.3 超时**：执行 `python -c "import time; time.sleep(60)"`，timeout=2s
   - 确认返回 `timed_out=True`，不抛错
   - 确认 output 中有 `[timeout after 2s]` 标记
2. **G2.4 优雅 kill**：执行捕获 SIGTERM 的脚本，确认收到 SIGTERM 后能清理退出
3. **G2.5 截断**：执行 `python -c "print('x' * 100000)"`，确认输出被截断为首尾各 15000 字符
4. 回归测试：正常命令（如 `ls`）行为不变

### 注意事项

- Windows 上 `proc.terminate()` 等价 `TerminateProcess`（强制结束），无 SIGTERM 概念
- 截断阈值 30000 与 Cline 一致，可通过 `AgentRuntimeConfig` 配置（未来扩展）
- `timed_out=True` 时 `exit_code=-1`（无真实退出码）

---

## 12.2 apply_patch 鲁棒性（G4.1 / G4.2 / G4.5）

### 任务背景

来源 Phase G #G4.1 / G4.2 / G4.5。Stage 1 已实现 apply_patch 原子性回滚（两阶段提交），但在解析阶段仍有 3 项鲁棒性差距：

1. **G4.1 Unicode 处理**：当前 patch 解析按字节读取，Unicode 字符（如中文）被拆分为多字节，导致行号偏移。Cline 按 Unicode 字符读取。
2. **G4.2 上下文匹配**：当前 patch 的 `context` 行用精确匹配，文件中如有微小差异（如空白字符）就匹配失败。Cline 用模糊匹配（忽略尾部空白）。
3. **G4.5 失败信息**：当前 patch 失败时仅返回"匹配失败"，无具体位置。Cline 返回失败行号 + 上下文，便于 LLM 修正。

### 目标

提升 apply_patch 解析鲁棒性：
1. Unicode 字符按字符读取（非字节）
2. context 行用模糊匹配（忽略尾部空白）
3. 失败时返回详细位置信息

### 当前实现位置

- `agent/tools/apply_patch.py`（`_parse_patch` / `_apply_chunk` / `_match_context` 函数）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/executors/apply-patch-tool.ts`

### 修复步骤建议

1. **G4.1 Unicode 字符读取**
   - 当前 `_parse_patch` 用 `bytes` 读取文件，按字节偏移定位
   - 改为用 `str` 读取（`encoding="utf-8"`），按字符偏移定位
   - 文件读取：
     ```python
     # 原有
     with open(file_path, "rb") as f:
         content = f.read()
     # 改为
     with open(file_path, "r", encoding="utf-8") as f:
         content = f.read()
     ```
   - 行号计算基于 `str.splitlines(keepends=True)`，保留行尾
   - 写回时用 `encoding="utf-8"` 保持编码一致

2. **G4.2 模糊匹配**
   - 当前 `_match_context` 用 `==` 精确匹配：
     ```python
     def _match_context(self, context_line: str, file_line: str) -> bool:
         return context_line == file_line
     ```
   - 改为模糊匹配：
     ```python
     def _match_context(self, context_line: str, file_line: str) -> bool:
         # 1. 精确匹配（保留原逻辑）
         if context_line == file_line:
             return True
         # 2. 忽略尾部空白
         if context_line.rstrip() == file_line.rstrip():
             return True
         # 3. 忽略行首缩进差异（tab vs space）
         if context_line.expandtabs() == file_line.expandtabs():
             return True
         return False
     ```
   - 保留原精确匹配逻辑，新增模糊匹配作为兜底
   - 模糊匹配成功时 logger.info 记录（便于调试）

3. **G4.5 失败信息**
   - 当前 `_apply_chunk` 失败时抛 `PatchApplyError("context mismatch")`
   - 改为携带详细信息：
     ```python
     class PatchApplyError(Exception):
         def __init__(self, message: str, *, file_path: str, line_num: int,
                      expected: str, actual: str, chunk_index: int):
             self.file_path = file_path
             self.line_num = line_num
             self.expected = expected
             self.actual = actual
             self.chunk_index = chunk_index
             super().__init__(
                 f"{message}\n"
                 f"  file: {file_path}\n"
                 f"  chunk #{chunk_index}, line {line_num}\n"
                 f"  expected: {expected!r}\n"
                 f"  actual:   {actual!r}"
             )
     ```
   - 失败时 LLM 可看到具体位置和差异，便于修正 patch 重试

4. **patch 解析错误兜底**
   - patch 格式错误（如缺分隔符）时，返回具体解析位置：
     ```python
     raise PatchParseError(
         f"invalid patch format at line {line_num}: {detail}",
         line_num=line_num,
         detail=detail,
     )
     ```
   - 错误信息包含 patch 中的行号和具体问题

5. **保留原有原子性**
   - 上述修改仅影响解析阶段，不影响两阶段提交（Stage 1 已实现）
   - 解析失败仍走"零写盘"路径，不破坏文件

### 验证方法

1. **G4.1 Unicode**：构造含中文的文件，patch 修改中文行，确认行号正确
2. **G4.2 模糊匹配**：
   - 文件中行尾有额外空格，patch context 无空格，确认匹配成功
   - 文件用 tab 缩进，patch context 用空格，确认匹配成功
3. **G4.5 失败信息**：构造 context 不匹配的 patch，确认错误信息包含文件名、行号、expected/actual
4. 回归测试：Stage 1 的原子性测试仍通过

### 注意事项

- Unicode 读取需处理 BOM（用 `encoding="utf-8-sig"` 自动剥离 BOM）
- 模糊匹配可能误匹配（如代码中确实需要区分 tab/space 的场景），保守策略优先
- 错误信息中 `expected` / `actual` 用 `repr()` 显示，避免特殊字符不可见

---

## 12.3 context-injection before_tool 实际注入（P9）

### 任务背景

来源 Phase P #P9。当前文件 Hooks 系统支持 `context-injection` 类型 hook，hook 返回的 `additional_context` 字段**未被实际注入**：
- `file_hooks.py` 执行 hook 后，`additional_context` 字段被解析但未追加到 messages
- LLM 看不到 hook 注入的上下文（如"当前 git 分支为 main"）
- 量化场景下，用户可能配置"调用 read_files 前注入文件历史修改记录"hook，当前不生效

Cline 的 `file-hooks.ts` 中 `beforeTool` hook 返回的 `additionalContext` 被追加为 system message，LLM 在工具调用前能看到。

### 目标

让 context-injection hook 真正生效：
1. hook 返回 `additional_context` 时，作为 system message 追加到 messages
2. 注入在工具调用前（before_tool 阶段）
3. 注入的消息标记 `metadata.kind="hook_context_injection"`，便于后续过滤

### 当前实现位置

- `agent/file_hooks.py`（`FileHooks.run_before_tool` / `HookResult.additional_context`）
- `agent/runtime.py`（`_prepare_tool_execution` 中调用 `run_before_tool`）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/hooks/file-hooks.ts`（`beforeTool` 注入 additionalContext）

### 修复步骤建议

1. **`runtime.py` 调用 hook 后处理 additional_context**
   - 在 `_prepare_tool_execution` 中调用 `run_before_tool` 后：
     ```python
     hook_result = await self._file_hooks.run_before_tool(tool, params, ctx)
     if hook_result.additional_context:
         # 构造 system message
         context_msg = create_text_message(
             MessageRole.SYSTEM,
             hook_result.additional_context,
             metadata={"kind": "hook_context_injection", "hook_name": hook_result.hook_name},
         )
         self._state.messages.append(context_msg)
         await self._emit(make_message_added(self.snapshot(), context_msg))
     ```
   - 注入在工具调用前，LLM 下一轮能看到
   - 保留原有 hook result 处理逻辑（如 `cancel` / `modify_params`）

2. **`HookResult.additional_context` 字段**
   - 当前 `HookResult` 已有 `additional_context: str = ""` 字段（确认存在）
   - hook 实现可填充该字段，runtime 读取并注入
   - 不修改 `HookResult` 结构，仅激活使用

3. **注入消息的 metadata**
   - 注入的 system message 携带 `metadata.kind="hook_context_injection"`
   - 在压缩时该消息可被识别为"hook 注入"，特殊处理（如保留不压缩）
   - `hook_name` 字段记录来源 hook，便于调试

4. **多 hook 注入顺序**
   - 多个 before_tool hook 都返回 `additional_context` 时，按 hook 注册顺序依次注入
   - 每个 hook 注入独立的 system message（不合并）
   - 避免单个 hook 的上下文污染其他 hook

5. **注入消息数量限制**
   - 单次工具调用最多注入 5 条 context-injection 消息（防止 hook 失控）
   - 超过限制时 logger.warning 并丢弃多余注入
   - 不写 fallback：限制是硬性约束

### 验证方法

1. 配置 before_tool hook 返回 `additional_context="当前 git 分支: main"`
2. 调用工具，确认 messages 末尾追加 system message
3. SSE 流中收到 `message_added` 事件，metadata.kind 为 `hook_context_injection`
4. LLM 下一轮调用能看到注入的上下文（如回答中提到 "main 分支"）
5. 多 hook 场景，确认注入顺序与注册顺序一致

### 注意事项

- 注入的消息参与 token 计数，可能触发压缩
- hook 返回空 `additional_context` 时不注入（不创建空消息）
- 注入消息在压缩时优先保留（标记为 `hook_context_injection`）

---

## 12.4 Hook 基础设施（P11 / P12 / P14）

### 任务背景

来源 Phase P #P11 / P12 / P14。当前文件 Hooks 系统缺少 3 项基础设施：

1. **P11 `HookError` 异常类**：当前 hook 抛错被 catch 后仅 logger.warning，无专用异常类型。Cline 有 `HookError` 区分 hook 错误与其他异常。
2. **P12 `HookProcessRegistry`**：当前 hook 进程无注册表管理，无法查询运行中的 hook 进程。Cline 有 registry 统一管理。
3. **P14 hook 模板**：当前无 hook 模板，用户需从零编写。Cline 提供 4 种模板（pre-edit / post-edit / pre-command / context-injection）。

### 目标

补齐 Hook 基础设施：
1. 新增 `HookError` 异常类，区分 hook 错误
2. 新增 `HookProcessRegistry` 管理运行中 hook 进程
3. 提供 4 种 hook 模板，降低用户配置成本

### 当前实现位置

- `agent/file_hooks.py`（`FileHooks` 类、`HookResult` dataclass）
- `agent_config/hooks/`（用户 hook 脚本目录）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/hooks/hook-error.ts`（`HookError` 类）
- Cline `third_party/cline/apps/vscode/src/core/hooks/hook-process-registry.ts`（`HookProcessRegistry`）
- Cline `third_party/cline/apps/vscode/src/core/hooks/templates/`（4 种模板）

### 修复步骤建议

1. **P11 `HookError` 异常类**
   - 在 `agent/file_hooks.py` 中新增：
     ```python
     class HookError(Exception):
         """hook 执行错误"""
         def __init__(self, message: str, *, hook_name: str, exit_code: int | None = None,
                      stderr: str = ""):
             self.hook_name = hook_name
             self.exit_code = exit_code
             self.stderr = stderr
             super().__init__(f"[hook={hook_name}] {message}")
     ```
   - 在 hook 执行失败时抛出 `HookError`（替代通用 `RuntimeError`）
   - `FileHooks.run_before_tool` / `run_after_tool` catch `HookError` 后根据 `blocking` 配置决定是否中止
   - 保留原有 `logger.warning` 日志，额外抛 `HookError` 让上层感知

2. **P12 `HookProcessRegistry`**
   - 在 `agent/file_hooks.py` 中新增：
     ```python
     class HookProcessRegistry:
         """管理运行中的 hook 进程"""
         def __init__(self):
             self._processes: dict[str, asyncio.subprocess.Process] = {}
             self._lock = asyncio.Lock()

         async def register(self, hook_id: str, proc: asyncio.subprocess.Process) -> None:
             async with self._lock:
                 self._processes[hook_id] = proc

         async def unregister(self, hook_id: str) -> None:
             async with self._lock:
                 self._processes.pop(hook_id, None)

         async def list_running(self) -> list[str]:
             async with self._lock:
                 return [hid for hid, p in self._processes.items() if p.returncode is None]

         async def kill_all(self) -> None:
             """abort 时 kill 所有运行中 hook 进程"""
             async with self._lock:
                 for proc in self._processes.values():
                     if proc.returncode is None:
                         proc.kill()
     ```
   - `FileHooks` 持有 `HookProcessRegistry` 实例
   - hook 启动后注册，完成后注销
   - abort signal 触发时调用 `kill_all()`（与 9.2 subprocess kill 联动）

3. **P14 hook 模板**
   - 在 `agent_config/hooks/templates/` 目录下提供 4 种模板：
     - `pre_edit_template.py`：文件编辑前 hook（如检查代码风格）
     - `post_edit_template.py`：文件编辑后 hook（如自动格式化）
     - `pre_command_template.py`：命令执行前 hook（如危险命令拦截）
     - `context_injection_template.py`：上下文注入 hook（如注入 git 状态）
   - 每个模板包含：
     - 标准 `main(params: dict) -> dict` 函数签名
     - 详细的参数和返回值文档
     - 示例逻辑（注释掉，用户取消注释启用）
   - 模板可直接复制到 `agent_config/hooks/` 启用，降低配置门槛

4. **`context_injection_template.py` 示例**
   ```python
   """context-injection hook 模板：注入 git 分支信息"""
   import subprocess

   def main(params: dict) -> dict:
       """params 包含 tool_name, tool_input, context 等
       返回 dict 包含 additional_context, cancel, modify_params 等
       """
       # 获取当前 git 分支
       try:
           branch = subprocess.check_output(
               ["git", "rev-parse", "--abbrev-ref", "HEAD"],
               cwd=params.get("context", {}).get("workspace", "."),
               text=True,
           ).strip()
           additional_context = f"[Hook Context] 当前 git 分支: {branch}"
       except Exception:
           additional_context = ""

       return {
           "additional_context": additional_context,
           "cancel": False,
       }
   ```

5. **Hook 文档**
   - 在每个模板顶部添加详细注释，说明：
     - hook 类型（before_file_edit / after_file_edit / before_command / context_injection）
     - 触发时机
     - params 字段说明
     - 返回值字段说明
     - 常见用例
   - 注释用中文 UTF-8 编码

### 验证方法

1. **P11 HookError**：构造一个抛错的 hook，确认 `HookError` 被抛出，包含 `hook_name` / `exit_code`
2. **P12 Registry**：启动一个长耗时 hook，调用 `list_running()` 确认能查询到，触发 abort 确认被 kill
3. **P14 模板**：复制 `context_injection_template.py` 到 `agent_config/hooks/`，配置 hook 触发，确认注入生效

### 注意事项

- `HookProcessRegistry` 用 `asyncio.Lock` 保证并发安全
- 模板文件用 UTF-8 编码，注释用中文
- 不修改现有 hook 加载逻辑，模板是用户可选启用

---

## 12.5 hook 并发执行（P16）

### 任务背景

来源 Phase P #P16。当前文件 Hooks **串行执行**（`for hook in hooks: await run_hook(hook)`），多个 hook 串行等待。Cline 用 `Promise.all` 并行执行所有 hook。

性能影响：
- 量化场景下，用户配置 5 个 before_tool hook（如 git 检查 / 文件权限 / 代码风格 / 依赖检查 / 环境变量）
- 每个 hook 平均耗时 200ms，串行总耗时 1s
- 并行执行总耗时仅 200ms（最慢 hook 决定）

### 目标

将 hook 执行改为并行：
1. 同类型 hook（如所有 before_tool hook）用 `asyncio.gather` 并行执行
2. 收集所有结果后统一处理（按注册顺序合并）
3. 任一 hook 抛 `HookError` 时根据 `blocking` 配置决定是否中止其他 hook

### 当前实现位置

- `agent/file_hooks.py`（`FileHooks.run_before_tool` / `run_after_tool`，串行 for 循环）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/hooks/file-hooks.ts`（`Promise.all` 并行执行）

### 修复步骤建议

1. **`run_before_tool` 改为并行**
   - 当前：
     ```python
     async def run_before_tool(self, tool, params, ctx):
         results = []
         for hook in self._before_tool_hooks:
             result = await self._run_hook(hook, params, ctx)
             results.append(result)
         return results
     ```
   - 改为：
     ```python
     async def run_before_tool(self, tool, params, ctx):
         if not self._before_tool_hooks:
             return []
         # 并行执行所有 hook
         tasks = [self._run_hook(hook, params, ctx) for hook in self._before_tool_hooks]
         try:
             results = await asyncio.gather(*tasks, return_exceptions=True)
         except Exception:
             raise
         # 处理异常和结果
         processed = []
         for hook, result in zip(self._before_tool_hooks, results):
             if isinstance(result, Exception):
                 if hook.blocking:
                     raise HookError(...) from result
                 else:
                     logger.warning(f"non-blocking hook failed: {result}")
                     processed.append(HookResult(success=False, error=str(result)))
             else:
                 processed.append(result)
         return processed
     ```
   - `return_exceptions=True` 让单个 hook 失败不影响其他 hook
   - 失败后根据 `blocking` 配置决定是否抛错

2. **结果合并顺序**
   - `asyncio.gather` 返回结果顺序与 tasks 顺序一致（即 hook 注册顺序）
   - 多个 hook 返回 `additional_context` 时，按注册顺序合并
   - 多个 hook 返回 `cancel=True` 时，第一个 cancel 生效（其他忽略）
   - 多个 hook 返回 `modify_params` 时，按顺序叠加修改（后到为准）

3. **`run_after_tool` 同样改为并行**
   - 与 `run_before_tool` 相同的并行逻辑
   - after_tool hook 通常无 cancel 语义，仅记录副作用

4. **超时控制**
   - 单个 hook 超时由 hook 自身配置（`hook.timeout_ms`）
   - 并行总时长 = max(各 hook 时长)，不受 hook 数量影响
   - 不增加额外的并行超时（避免与单 hook 超时冲突）

5. **资源限制**
   - 同时运行的 hook 数量限制为 10（防止 hook 失控启动过多进程）
   - 超过限制时 logger.warning 并串行执行超出部分
   - 不写 fallback：超限是配置错误，应让用户感知

### 验证方法

1. 配置 5 个 before_tool hook，每个耗时 200ms
2. 调用工具，确认总耗时约 200ms（并行）而非 1s（串行）
3. 配置 1 个 blocking hook 抛错，1 个 non-blocking hook 抛错，确认 blocking 抛出 HookError，non-blocking 仅 warning
4. 配置 11 个 hook，确认前 10 个并行，第 11 个串行执行

### 注意事项

- `asyncio.gather` 需在 asyncio 事件循环中调用（runtime 已在循环中）
- 并行执行可能改变 hook 副作用顺序（如多个 hook 修改同一文件），需在文档中提示
- 不修改 hook 内部逻辑，仅修改调度方式

---

## 13. 阶段汇总

### 13.1 完成判据

- 12.1：run_commands 超时返回部分输出，输出超长截断
- 12.2：apply_patch 支持 Unicode / 模糊匹配 / 详细错误
- 12.3：context-injection hook 实际注入 system message
- 12.4：HookError / HookProcessRegistry / 4 种模板可用
- 12.5：多个 hook 并行执行，总耗时 = max(单 hook)

### 13.2 风险与回滚

- 12.1 / 12.2 涉及工具核心逻辑，需充分回归测试
- 12.5 并行执行可能改变 hook 副作用顺序，需文档提示
- 12.3 / 12.4 新增功能，风险低

### 13.3 后续衔接

- 12.4 完成后，Stage 14 的 Z3/Z4（事件枚举）可基于 HookError 扩展
- 12.5 完成后，未来可扩展 hook 依赖关系（如 hook B 依赖 hook A 的结果）

---

**Stage 12 结束。建议按 12.1 → 12.2 → 12.4 → 12.3 → 12.5 顺序执行，完成后进入 Stage 13。**
