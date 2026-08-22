# Phase G: 内置工具(文件/命令/编辑) 对比报告

> 对标源码：`sdk/packages/core/src/extensions/tools/executors/file-read.ts` + `bash.ts` + `editor.ts` + `apply-patch.ts` + `apply-patch-parser.ts` + `output-limits.ts` + `schemas.ts` + `definitions.ts`
> 当前实现：`agent/tools/read_files.py` + `run_commands.py` + `editor.py` + `apply_patch.py` + `constants.py`
> 对比维度：G1-G4（共 31 子项）

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 10 项 |
| 弱对齐 | 15 项 |
| 缺失 | 5 项 |
| 额外增强 | 1 项 |
| **对齐度** | **约 60%** |

**总体评价**：四类内置工具的核心 schema 与基础行为与 Cline 对齐，但存在多处语义不等价的关键差距：
- `run_commands` 串行执行 vs Cline 并行执行（G2.2）
- `editor` 文件已存在且无 `old_text` 时我允许覆盖，Cline 抛错（G3.3，**语义不等价**）
- `apply_patch` 缺少原子性回滚（G4.4，**P0 级**）
- `read_files` / `editor` 均不输出行号与 diff，LLM 失去定位与校验能力（G1.6 / G3.6）

---

## 2. 详细对比表

### G1: `read_files` vs `file-read.ts`

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| G1.1 | 输入 schema（files 数组结构） | schemas.ts L42-104 | read_files.py L78-109 | 弱对齐 |
| G1.2 | start_line/end_line 语义（1-based） | schemas.ts L19-40 | read_files.py L91-100 | 完全一致 |
| G1.3 | 最大行数限制 | output-limits.ts L41-47 | constants.py L55-59 | 弱对齐 |
| G1.4 | 二进制文件检测 | file-read.ts L21-27 L254-258 | read_files.py L200-208 | 弱对齐 |
| G1.5 | 编码检测 | file-read.ts L52-56 | read_files.py L200-202 | 完全一致 |
| G1.6 | 行号格式输出（cat -n 风格） | file-read.ts L103-105 L161-170 | 无 | 缺失 |
| G1.7 | 大文件分页 | file-read.ts L176-188 | read_files.py L248-250 | 弱对齐 |
| G1.8 | 错误信息格式 | definitions.ts L320-327 | read_files.py L173-185 L254-264 | 弱对齐 |

### G2: `run_commands` vs `bash.ts`

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| G2.1 | 输入 schema（commands 数组） | schemas.ts L125-170 | run_commands.py L91-104 | 弱对齐 |
| G2.2 | 命令执行模式（parallel vs sequential） | definitions.ts L191-330 | run_commands.py L144-160 | 缺失 |
| G2.3 | 单命令超时 | definitions.ts L460 L196-200 | run_commands.py L107-108 L271-281 | 弱对齐 |
| G2.4 | 子进程 kill on abort | bash.ts L159-181 | run_commands.py L251-305 | 弱对齐 |
| G2.5 | 输出截断 | output-limits.ts L17-38 bash.ts L86-124 | constants.py L27-33 run_commands.py L213-223 | 弱对齐 |
| G2.6 | 环境变量继承 | bash.ts L138 | run_commands.py L139-140 | 完全一致 |
| G2.7 | 工作目录 | bash.ts L137 | run_commands.py L76-77 | 完全一致 |
| G2.8 | exit_code 返回 | bash.ts L21-29 L217-236 definitions.ts L215-222 | run_commands.py L225-231 | 弱对齐 |
| G2.9 | shell 元字符处理 | bash.ts L291-307 definitions.ts L122-150 | run_commands.py L184-190 | 弱对齐 |
| G2.10 | 危险命令拦截 | 无（依赖外部 tool-approval） | run_commands.py L64-74 L307-316 | 额外增强 |

### G3: `editor` vs `editor.ts`

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| G3.1 | 输入 schema | schemas.ts L192-221 helpers.ts L20-33 | editor.py L80-105 | 弱对齐 |
| G3.2 | old_text 唯一性检查 | editor.ts L181-191 | editor.py L254-316 | 完全一致 |
| G3.3 | old_text 为空时插入（语义不等价） | editor.ts L254-261 | editor.py L164-169 L353-377 | 缺失（语义不等价） |
| G3.4 | 文件不存在时创建 | editor.ts L151-159 L254-256 | editor.py L164-166 L333-351 | 完全一致 |
| G3.5 | 行号计算（1-based） | editor.ts L202-224 | editor.py L188-204 | 完全一致 |
| G3.6 | diff 生成 | editor.ts L87-149 L198 | 无 | 缺失 |
| G3.7 | 原子写入 | editor.ts L196 | editor.py L379-384 | 完全一致 |
| G3.8 | 备份机制 | 无 | 无 | 完全一致 |

### G4: `apply_patch` vs `apply-patch.ts`

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| G4.1 | patch 格式 | apply-patch-parser.ts L7-16 | apply_patch.py L144-218 | 弱对齐 |
| G4.2 | 解析器容错 | apply-patch-parser.ts L58-83 L99-136 | apply_patch.py L144-218 | 弱对齐 |
| G4.3 | 多文件 patch | apply-patch.ts L215-254 apply-patch-parser.ts L148-152 | apply_patch.py L120-142 | 完全一致 |
| G4.4 | 部分成功回滚 | apply-patch.ts L333-384 apply-patch-parser.ts L347-431 | apply_patch.py L128-141 | 缺失 |
| G4.5 | 上下文行匹配 | apply-patch-parser.ts L347-431 | apply_patch.py L365-396 | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #G1.6：行号格式输出缺失

**严重度**：P1（影响 LLM 后续编辑定位）

**Cline 实现**：`file-read.ts` L52-56 默认 `includeLineNumbers: true`，L103-105 计算行号前缀宽度，L161-170 输出格式 `${lineNumber.padStart(maxLineNumWidth)} | ${text}`，例如：
```
  1 | first line
  2 | second line
```
行号右对齐，与 `cat -n` 风格一致，便于 LLM 在后续 `editor` / `apply_patch` 调用中精确定位行号。

**我的实现**：`read_files.py` L236-243 只返回 `content` 纯文本，不含行号。仅返回 `start_line` / `end_line` 元数据。

**影响**：
- LLM 读取文件后无法直接看到行号，后续 `insert_line` / `start_line` 调用需自行数行，易出错
- 与 Cline 的 `editor` 工具的 `old_text` 定位、`apply_patch` 的 `@@` 上下文匹配形成连锁影响
- Cline 在 `definitions.ts` L255 的工具描述中明确告知 LLM "page through long files with start_line/end_line"，依赖行号输出建立心智模型

**修复建议**：在 `_read_single_file` 输出 content 时按 Cline 格式注入行号前缀：
```python
max_width = len(str(end_idx))
lines_with_num = [
    f"{str(start_line + i).rjust(max_width)} | {line}"
    for i, line in enumerate(selected_lines)
]
content = "\n".join(lines_with_num)
```
注意：需保留 `has_more` / `next_start_line` 字段以便分页。

**优先级**：P1

---

### 差距 #G2.2：命令执行模式（并行 vs 串行）—— 语义不等价

**严重度**：P1（性能与语义双重差异）

**Cline 实现**：`definitions.ts` L191 `executeShellCommands` 使用 `Promise.all(commands.map(...))` 并行执行所有命令。工具描述（L419 / L433）明确要求 "Include multiple commands in the same call when they are independent and safe to run concurrently"，即设计上假定命令间无依赖。

**我的实现**：`run_commands.py` L144-160 使用 `for idx, cmd in enumerate(commands)` 串行执行，前一条完成后才执行下一条。

**影响**：
- **性能**：N 条独立命令的执行时间，Cline = max(t1..tn)，我 = sum(t1..tn)。10 条 30s 命令，Cline 30s，我 300s。
- **语义**：Cline 假定命令独立，LLM 据此组织调用；我的串行执行允许 LLM 提交有依赖的命令序列（如 `cd build && make`），但与 Cline 的 LLM 提示不一致，可能导致 LLM 困惑。
- **abort 行为**：Cline 并行时 abort 一次性终止所有；我串行时 abort 只终止当前命令，后续命令不再执行（行为更可预测）。

**修复建议**：
- 短期：保持串行（更安全，符合量化场景的命令依赖习惯），但在工具描述中明确说明 "命令按顺序执行，前一条完成后才执行下一条"，避免 LLM 误用。
- 长期：可选改为并行 + 显式依赖标注（如 `depends_on` 字段），但对量化场景收益有限。

**优先级**：P1

---

### 差距 #G2.3：单命令超时默认值差异

**严重度**：P1（影响 agent 响应性）

**Cline 实现**：`definitions.ts` L460 `timeoutMs = config.bashTimeoutMs ?? 30000`（30 秒），L196-200 每条命令用 `withTimeout(executor(...), timeoutMs)` 包裹。工具级超时为 `timeoutMs * 2`（60 秒）。

**我的实现**：`run_commands.py` L60 `_DEFAULT_TIMEOUT = 60`（60 秒），L61 `_MAX_TIMEOUT = 600`（600 秒 = 10 分钟）。L107-108 `timeout_ms` 属性返回 `_MAX_TIMEOUT * 1000`（600000ms）。L271-281 `_wait_process_with_abort` 使用 `_MAX_TIMEOUT` 作为超时。

**影响**：
- 默认超时 600s 过于宽松，单条卡死命令会让 agent 卡顿 10 分钟才触发超时
- Cline 30s 默认值更符合交互式 agent 的响应性要求
- 量化场景下部分回测/数据收集命令确实需要长时间，但应显式配置而非默认 600s

**修复建议**：
- 将 `_DEFAULT_TIMEOUT` 调整为 60s（已合理），但 `timeout_ms` 属性应使用 `_DEFAULT_TIMEOUT` 而非 `_MAX_TIMEOUT`
- 保留 `_MAX_TIMEOUT` 作为单条命令的硬上限
- 长命令应由 LLM 显式后台化（`nohup ... &`），与 Cline L435 提示一致

**优先级**：P1

---

### 差距 #G2.4：子进程 kill on abort（进程树 vs 单进程）

**严重度**：P2（影响 abort 后的资源清理）

**Cline 实现**：`bash.ts` L159-175 `killProcessTree` 函数：
- Windows: `spawn("taskkill", ["/pid", pid, "/T", "/F"])` 杀整个进程树
- Unix: `process.kill(-childPid, "SIGKILL")` 杀进程组（`detached: true` 创建独立进程组）
- 配合 `context.signal.addEventListener("abort", abortHandler)` 实现即时终止

**我的实现**：`run_commands.py` L251-305 `_wait_process_with_abort`：
- L266 `asyncio.ensure_future(process.communicate())` + L274 `signal.wait()` 组合等待
- L288-295 abort 触发时 `process.kill()` + `asyncio.wait_for(process.wait(), timeout=2.0)`
- 只杀单进程，不杀子进程

**影响**：
- 执行 `python script.py` 时若 script 内部 `subprocess.Popen` 启动了子进程，abort 后子进程会变成孤儿继续运行
- 量化场景下常见 `subprocess` 调用外部工具（如 `tushare`、`akshare` 数据拉取），孤儿进程会持续占用网络/数据库连接
- Windows 下 `process.kill()` 等价于 `TerminateProcess`，不杀子进程

**修复建议**：在 Windows 下使用 `taskkill /pid {pid} /T /F`，Unix 下使用 `os.killpg(os.getpgid(pid), signal.SIGKILL)`（需 `start_new_session=True` 创建进程组）：
```python
process = await asyncio.create_subprocess_shell(
    command, ..., start_new_session=True  # Unix 进程组
)
# abort 时:
if os.name == "nt":
    subprocess.run(["taskkill", "/pid", str(process.pid), "/T", "/F"], ...)
else:
    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
```

**优先级**：P2

---

### 差距 #G2.5：输出截断策略（头尾保留 vs 只保留头）

**严重度**：P2（影响错误诊断）

**Cline 实现**：
- `output-limits.ts` L17-18 `MAX_COMMAND_OUTPUT_CHARS = 48000`
- `bash.ts` L86-124 `createRollingCollector`：前一半 `head` 完整保留，后一半 `tail` 滚动保留最新，中间丢弃
- L20-38 `truncateCommandOutput`：显式头尾保留 + 中间插入 `[... output truncated: N chars total ...]` 提示
- 设计理由（L8-14）：build/test 失败信息通常在输出末尾，必须保留 tail

**我的实现**：
- `constants.py` L29 `MAX_OUTPUT_PER_COMMAND = 8000`，L33 `MAX_STDERR_PER_COMMAND = 2000`
- `run_commands.py` L213-223：`stdout_text[:MAX]` 只保留头部，尾部直接丢弃
- 截断提示追加在末尾：`... (stdout 已截断，原始长度 N 字符)`

**影响**：
- 长输出命令（如 `pytest -v`、`pip install`）的错误堆栈通常在末尾，我的实现会丢失关键错误信息
- 阈值过小（8000 vs 48000），中等长度输出就被截断
- stderr 2000 字符阈值更小，编译错误常被截断

**修复建议**：
- 改为头尾保留策略：`head = text[:max/2]; tail = text[-max/2:]`
- 阈值上调至 30000-48000（与 Cline 对齐或略小）
- stderr 阈值上调至 8000-16000

**优先级**：P2

---

### 差距 #G3.3：old_text 为空时行为（覆盖 vs 报错）—— 语义不等价

**严重度**：P1（安全风险，可能误覆盖文件）

**Cline 实现**：`editor.ts` L254-261：
```typescript
if (!(await fileExists(filePath))) {
    return createFile(filePath, input.new_text, encoding);  // 文件不存在则创建
}
if (input.old_text == null) {
    throw new Error(
        "Parameter `old_text` is required when editing an existing file without `insert_line`",
    );  // 文件存在且无 old_text/insert_line → 抛错
}
```
即：文件存在时**必须**提供 `old_text` 或 `insert_line`，否则拒绝执行。

**我的实现**：`editor.py` L164-169：
```python
# 分支: 创建模式（文件不存在且无 old_text）
if not exists:
    return self._do_create(path, path_str, new_text)

# 文件已存在但没有提供 old_text 或 insert_line — 视为整体覆盖
return self._do_overwrite(path, path_str, original, new_text, lines_before, line_ending)
```
L353-377 `_do_overwrite` 直接用 `new_text` 覆盖整个文件。

**影响**：
- **数据丢失风险**：LLM 若误调用 `editor(path="existing.py", new_text="new content")`（漏传 `old_text`），我会直接覆盖整个文件，Cline 会拒绝
- Cline 的严格设计是安全护栏，防止 LLM 的常见错误（忘记 `old_text`）
- 我的"整体覆盖"分支虽在 `note` 字段标注，但 LLM 可能忽略，且无法撤销
- 量化场景下策略文件、配置文件被误覆盖会造成实际损失

**修复建议**：对齐 Cline 的严格行为，移除 `_do_overwrite` 分支，文件已存在且无 `old_text`/`insert_line` 时返回错误：
```python
if not exists:
    return self._do_create(path, path_str, new_text)

return AgentToolResult(
    output={
        "error": "文件已存在，必须提供 old_text（替换模式）或 insert_line（插入模式）",
        "path": path_str,
        "lines_before": lines_before,
    },
    is_error=True,
)
```
若需保留整体覆盖能力，应要求 LLM 显式传 `old_text=""` 或新增 `mode: "overwrite"` 字段。

**优先级**：P1

---

### 差距 #G3.6：diff 生成缺失

**严重度**：P1（影响 LLM 自我校验）

**Cline 实现**：`editor.ts` L87-149 `createLineDiff`：
- 修剪公共前缀/后缀，只输出变更区域
- 行预算在 removed/added 间分配（L122-129），避免单侧吃满
- 输出 ```diff 代码块格式：`-{lineNum}: {oldLine}` / `+{lineNum}: {newLine}`
- L198 `replaceInFile` 返回 `Edited ${filePath}\n${diff}`
- L223 `insertInFile` 返回 `Inserted content at line ${N} in ${filePath}`

**我的实现**：`editor.py` 各分支只返回 `{path, operation, lines_before, lines_after}`，无 diff 内容。

**影响**：
- LLM 执行编辑后无法直观看到实际变更，难以自我校验
- 后续 turn 中 LLM 可能重复编辑或误判编辑结果
- `lines_before` / `lines_after` 仅数字，信息密度远低于 diff
- Cline 的 diff 输出是 LLM "理解自己做了什么"的关键反馈通道

**修复建议**：在 `_do_replace` / `_do_insert` / `_do_overwrite` 返回结果中加入 `diff` 字段，实现简化版 `createLineDiff`：
```python
def _create_line_diff(old: str, new: str, max_lines: int = 200) -> str:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    # 修剪公共前后缀
    start = 0
    while start < len(old_lines) and start < len(new_lines) and old_lines[start] == new_lines[start]:
        start += 1
    # ... 输出 -N: old / +N: new
```

**优先级**：P1

---

### 差距 #G4.1：patch 格式（Move to / End of File 缺失）

**严重度**：P2（影响功能完整性）

**Cline 实现**：`apply-patch-parser.ts` L7-16 定义完整标记集：
- `*** Move to: ` —— 在 `*** Update File:` 后立即跟随，表示文件重命名（L159-163 解析，L305-314 应用：写新路径 + 删旧路径）
- `*** End of File` —— 标记上下文匹配到文件末尾（L514-517 在 `peek` 中处理，L421-428 `findContext` 用 `eof` 参数优先匹配尾部）

**我的实现**：`apply_patch.py` L175-208 只识别 `*** Update File` / `*** Add File` / `*** Delete File`，不识别 `*** Move to` 和 `*** End of File`。

**影响**：
- 无法执行文件重命名（LLM 必须拆成 "新建 + 删除" 两步）
- `*** End of File` 标记的 patch 会在我的解析器中被当作普通行收集，可能导致匹配失败
- 量化场景下文件重命名较少，但缺 `*** End of File` 会导致尾部插入场景出错

**修复建议**：
- 短期：在 `_parse_patch` 中检测 `*** Move to:` 和 `*** End of File`，至少跳过不报错
- 长期：实现 Move 语义（写新路径 + 删旧路径）和 EOF 上下文匹配

**优先级**：P2

---

### 差距 #G4.2：解析器容错（Unicode 规范化 + sentinel 自动补全缺失）

**严重度**：P2（影响 patch 鲁棒性）

**Cline 实现**：
- `apply-patch-parser.ts` L58-83 `canonicalize`：将 Unicode 标点规范化（en-dash → `-`、smart quotes → `"`、U+202F → 空格等），NFC 归一化，处理转义引号。在 L207-225 上下文匹配时对文件行和 patch 行都做 canonicalize。
- `apply-patch.ts` L99-136 `normalizePatchInput`：若缺少 `*** Begin Patch` / `*** End Patch` sentinel，自动补全；若只有其一，抛 `DiffError`。
- L77-97 `trimWrapperLines`：剥离 `%%bash` / `apply_patch` / `EOF` / ` ``` ` 等 legacy shell wrapper。

**我的实现**：`apply_patch.py` L144-218 `_parse_patch`：
- 仅做 `line.strip()`，无 Unicode 规范化
- L159-168 检测 `*** Begin Patch` / `*** End Patch`，但 L215-216 处理未闭合块时直接 append（无 sentinel 也能解析）
- 不识别 shell wrapper，wrapper 行会被当作普通行收集

**影响**：
- LLM 生成含 smart quote（如 `"` `"`）或 en-dash（`–`）的 patch 时，我的解析器无法匹配文件中的 ASCII 版本，导致替换失败
- LLM 用 `apply_patch <<"EOF" ... EOF` wrapper 时，我的解析器会把 wrapper 行当 patch 内容
- 中文文件名/内容中含全角标点时匹配失败率上升

**修复建议**：
- 实现 `canonicalize` 等价函数（Python `unicodedata.normalize("NFC", ...)` + 标点映射表）
- 在上下文匹配前对文件行和 patch 行都做 canonicalize
- 检测并剥离 `%%bash` / `apply_patch` / ` ``` ` wrapper 行

**优先级**：P2

---

### 差距 #G4.4：部分成功回滚缺失 —— P0 级

**严重度**：P0（数据完整性风险）

**Cline 实现**：`apply-patch.ts` L333-353 `computePatchChanges`：
1. **先解析所有 chunk**：`new PatchParser(lines, currentFiles).parse()`
2. **检查 warnings**：L348-350 若 `patch.warnings.length > 0`，抛 `DiffError(formatSkippedHunkFailure(warnings))`，**不写任何文件**
3. **再应用**：L372 `applyChanges` 才实际写盘

即 **all-or-nothing**：任一 chunk 上下文匹配失败，整个 patch 拒绝应用，文件保持原状。`findContext`（L347-431）在无法精确匹配时记录 warning 而非跳过。

**我的实现**：`apply_patch.py` L128-141：
```python
for block in blocks:
    result_item = self._apply_block(block)  # 立即写盘
    results.append(result_item)
```
每个 block 立即应用并写盘，不回滚。`_apply_update` L324-330 在某段 `-` 行找不到时返回 `{success: False, error: ...}`，但**已应用的前续块不会回滚**。

**影响**：
- 3 文件 patch 中第 2 个文件匹配失败：前 1 个文件已改，第 3 个文件未处理 → 仓库处于不一致状态
- 量化策略文件批量修改时，部分成功可能导致策略半更新，回测结果不可信
- Cline 的原子性是 patch 工具的核心安全保证，缺失会导致 LLM 难以恢复

**修复建议**：改为两阶段提交：
```python
async def _execute(self, input, context):
    blocks = self._parse_patch(input["input"])
    
    # 阶段 1: 计算所有变更（不写盘）
    changes = []
    for block in blocks:
        change = self._compute_change(block)  # 返回 (path, old_content, new_content)
        if change is None:
            return AgentToolResult(
                output={"error": f"块 {block['path']} 匹配失败，整个 patch 未应用"},
                is_error=True,
            )
        changes.append(change)
    
    # 阶段 2: 全部成功后写盘
    for path, _, new_content in changes:
        path.write_text(new_content, encoding="utf-8")
```
需注意：阶段 1 中已读取的文件内容在阶段 2 写盘前可能被外部修改，可通过文件锁或 mtime 校验缓解。

**优先级**：P0

---

### 差距 #G4.5：上下文行匹配（模糊匹配 weaker）

**严重度**：P2（影响 patch 成功率）

**Cline 实现**：`apply-patch-parser.ts` L347-431 `findContext` 四级匹配：
1. **精确 canonical 匹配**（L360-367）：`canonicalize(segment) === canonicalContext`，fuzz=0
2. **trimEnd 匹配**（L374-387）：仅去尾部空白，fuzz=1
3. **trim 匹配**（L389-402）：去首尾空白，fuzz=100
4. **相似度匹配**（L404-416）：Levenshtein 距离计算 similarity >= 0.66，fuzz=1000

L312-320 `calculateSimilarity` 用 Levenshtein 距离量化相似度。L421-428 EOF 场景特殊处理（fuzz+10000）。

**我的实现**：`apply_patch.py` L365-396 `_replace_segment` 两级匹配：
1. **精确匹配**（L384-387）：`result_lines[idx:idx+n] == removed_lines`
2. **strip 匹配**（L390-394）：`window[j].strip() == removed_lines[j].strip()` for all j

无 trimEnd、无 Levenshtein 相似度、无 EOF 特殊处理。

**影响**：
- 文件含尾随空格而 patch 未精确还原时，Cline 的 trimEnd 匹配可成功，我需退到 strip 匹配（更激进）
- 缩进微调、标点变化（如 `,` vs `，`）导致精确匹配失败时，Cline 的相似度匹配可兜底，我直接失败
- 相似度匹配能让 LLM 知道 "接近但不够"，通过 warning 上下文反馈，我只返回 "未找到"

**修复建议**：
- 增加 trimEnd 匹配层级
- 实现 Levenshtein 相似度（Python 可用 `difflib.SequenceMatcher.ratio()` 替代，更高效）
- 阈值 0.66 与 Cline 对齐
- 失败时返回 similarity 分数，便于 LLM 调整 patch

**优先级**：P2

---

### 差距 #G1.1：schema 容错（union/alias/orphan range 缺失）

**严重度**：P2（影响 LLM 兼容性）

**Cline 实现**：`schemas.ts` L86-104 `ReadFilesInputUnionSchema` 接受多种输入形态：
- `{files: [...]}` 标准形式
- 单字符串、字符串数组
- `{file_paths: [...]}` / `{paths: [...]}` 别名
- 每项支持 `file_path` / `filePath` 别名（L73-81 `LooseReadFileRequestSchema`）

`helpers.ts` L80-135 `coalesceOrphanReadRanges` 处理 LLM 把 `start_line`/`end_line` 误 emit 为独立数组元素的常见错误。

**我的实现**：`read_files.py` L78-109 只接受 `{files: [{path, start_line, end_line}]}` 标准形式，无别名、无 union、无 orphan 合并。

**影响**：
- 不同模型（GPT-4 / Claude / Qwen）对 schema 的遵循度不同，缺少别名会直接报 schema 校验失败
- `coalesceOrphanReadRanges` 处理的是真实模型行为，缺失会导致 "range 与 path 分离" 的输入被拒绝

**修复建议**：在 `_execute` 入口做输入归一化：
- 接受 `file_paths` / `paths` 别名
- 单字符串自动包装为 `[{path: str}]`
- 实现 orphan range 合并

**优先级**：P2

---

### 差距 #G1.3：最大行数限制数值差异

**严重度**：P3（影响配置一致性）

**Cline 实现**：`output-limits.ts` L41-47：
- `MAX_READ_LINES = 2000`（单次读取行数上限）
- `MAX_READ_OUTPUT_CHARS = 48000`（单次读取字符上限）
- `MAX_LINE_CHARS = 2000`（单行字符上限，超出则 `[line truncated]`）

**我的实现**：`constants.py` L55-59：
- `MAX_READ_LINES = 2000`（仅常量定义，`read_files.py` 未引用）
- `MAX_READ_OUTPUT_CHARS = 16000`
- 无 `MAX_LINE_CHARS`
- `read_files.py` L52-55 自定义 `_MAX_CHARS_PER_FILE = 16000`，无行数限制

**影响**：
- 单文件读取上限不一致（16000 vs 48000 字符），大文件分页粒度不同
- 无单行截断，minified 文件（如压缩 JS）的单行可能撑爆上下文
- `MAX_READ_LINES` 常量已定义但未在 `read_files.py` 中使用，是死代码

**修复建议**：
- `read_files.py` 引入 `MAX_READ_LINES` 限制行数
- 上调 `MAX_READ_OUTPUT_CHARS` 至 48000（与 Cline 对齐）
- 新增 `MAX_LINE_CHARS = 2000`，超长行截断并标注 `[line truncated]`

**优先级**：P3

---

### 差距 #G1.4：二进制文件检测（图片支持缺失）

**严重度**：P3（量化场景图片需求低）

**Cline 实现**：`file-read.ts` L21-27 `IMAGE_MEDIA_TYPES` 识别 `.gif/.png/.jpg/.jpeg/.webp`，L231-252 图片文件返回 base64 + `image` 类型（需 `context.metadata.modelSupportsImages`）。L254-258 超过 100MB 的文本文件拒绝流式读取。

**我的实现**：`read_files.py` L200-208 仅尝试 UTF-8 decode，失败则返回 "无法读取二进制文件"。无图片识别、无 base64 返回、无大文件硬上限。

**影响**：
- 不支持读取图片（如 K 线图、财报截图）作为多模态输入
- 超大文本文件（如日志）会全量读入内存后才报错
- 量化场景下图片读取需求有限（主要是 PDF 已由独立工具处理）

**修复建议**：暂不实现图片支持（多模态场景未启用）。可选增加大文件硬上限（100MB）提前拒绝。

**优先级**：P3

---

## 4. 额外增强项

### 增强 #G2.10：危险命令拦截

**我的实现**：`run_commands.py` L64-74 `_DENY_PATTERNS` 包含 9 个危险模式：
- `rm -rf /` / `rm -rf ~` / `rm -rf *`
- `mkfs.`
- `dd if=.*of=/dev/`
- `> /dev/sd`
- `shutdown` / `reboot`
- `format [a-z]:`

L307-316 `_guard_command` 在每条命令执行前用 `re.search` 检查，匹配则拒绝执行。

**Cline 实现**：`bash.ts` 无内置黑名单，依赖外部 `tool-approval` 策略配置。

**评估**：合理增强。量化场景下 agent 直接操作文件系统，黑名单是最后一道防线。Cline 的设计假定 host（如 VSCode 插件）会配置 approval 策略，我的内嵌黑名单更适合独立运行场景。保留。

**注意事项**：
- 黑名单无法覆盖所有危险命令（如 `:(){ :|:& };:` fork bomb），应配合 `requires_approval=True` 双保险
- 正则匹配可能误报（如 `rm -rf /home/user/backup` 会匹配 `rm\s+-rf\s+/`），需优化模式（如要求 `rm -rf /` 后跟非字母字符）

---

## 5. 一致性统计

### 按工具分布

| 工具 | 完全一致 | 弱对齐 | 缺失 | 额外增强 | 对齐度 |
|------|---------|--------|------|---------|--------|
| G1 read_files | 2 | 5 | 1 | 0 | 约 56% |
| G2 run_commands | 2 | 6 | 1 | 1 | 约 60% |
| G3 editor | 4 | 1 | 2 | 0 | 约 63% |
| G4 apply_patch | 1 | 3 | 1 | 0 | 约 50% |
| **合计** | **9** | **15** | **5** | **1** | **约 60%** |

### 按严重度分布

| 严重度 | 数量 | 占比 |
|--------|------|------|
| P0 | 1 项（G4.4） | 3% |
| P1 | 5 项（G1.6, G2.2, G2.3, G3.3, G3.6） | 16% |
| P2 | 7 项（G2.4, G2.5, G3.1, G4.1, G4.2, G4.5, G1.1） | 23% |
| P3 | 2 项（G1.3, G1.4） | 6% |
| 完全一致 | 10 项 | 32% |
| 弱对齐（非差距） | 8 项 | 26% |

### 关键语义不等价项

| # | 项 | Cline 行为 | 我的行为 | 风险 |
|---|----|-----------|---------|------|
| G2.2 | 命令执行模式 | 并行（Promise.all） | 串行（for 循环） | 性能 + LLM 预期 |
| G3.3 | 文件存在无 old_text | 抛错拒绝 | 整体覆盖 | 数据丢失 |
| G4.4 | patch 部分失败 | 全部回滚 | 部分写入 | 仓库不一致 |

---

## 6. 修复建议

### 短期（P0-P1，建议本阶段完成）

1. **G4.4 apply_patch 原子性回滚**（P0）：改为两阶段提交，先计算所有变更，全部成功后写盘。这是数据安全的硬要求。
2. **G3.3 editor 覆盖行为对齐**（P1）：移除 `_do_overwrite` 分支，文件存在且无 `old_text`/`insert_line` 时返回错误，与 Cline 严格行为一致。
3. **G3.6 editor diff 生成**（P1）：实现 `createLineDiff`，在编辑结果中返回 diff，让 LLM 能自我校验。
4. **G1.6 read_files 行号输出**（P1）：按 Cline `${lineNum} | ${text}` 格式注入行号，便于 LLM 后续定位。
5. **G2.3 run_commands 超时调整**（P1）：`timeout_ms` 属性使用 `_DEFAULT_TIMEOUT`（60s）而非 `_MAX_TIMEOUT`（600s），避免单条命令卡死 agent。
6. **G2.2 run_commands 执行模式**（P1）：保持串行但在工具描述中明确说明，避免 LLM 误用。

### 中期（P2，下阶段完成）

1. **G2.4 进程树 kill**：Windows 用 `taskkill /T /F`，Unix 用 `os.killpg`，确保 abort 后无孤儿进程。
2. **G2.5 输出头尾截断**：改为 head + tail 保留策略，阈值上调至 30000+。
3. **G4.1 patch Move to / End of File**：至少识别并跳过，长期实现完整语义。
4. **G4.2 Unicode 规范化**：实现 `canonicalize` 等价函数，提升 patch 鲁棒性。
5. **G4.5 模糊匹配增强**：增加 trimEnd 层级和 Levenshtein 相似度匹配。
6. **G1.1 schema 容错**：接受 `file_paths`/`paths` 别名，实现 orphan range 合并。
7. **G3.1 editor 大小检查**：新增 `INPUT_ARG_CHAR_LIMIT=6000` 检查，防止超大 old_text/new_text 超时。

### 长期（P3，可选）

1. **G1.3 output-limits 统一**：`MAX_READ_OUTPUT_CHARS` 上调至 48000，新增 `MAX_LINE_CHARS=2000`。
2. **G1.4 图片支持**：多模态启用后实现 base64 返回。
3. **G4.1 Move to 完整实现**：文件重命名语义（写新路径 + 删旧路径）。

---

## 7. 验证记录

### 验证方法

1. **源码逐行对照**：已 Read 全部 9 个 Cline 源码文件 + 5 个我的实现文件，逐行核对每个对比项。
2. **schema 对照**：Cline `schemas.ts` 中的 zod schema 与我的 `input_schema` dict 逐字段对比。
3. **常量对照**：`output-limits.ts` 与 `constants.py` 数值逐一核对。
4. **行为对照**：对每个工具的执行路径（happy path + error path）进行逻辑级比对，重点关注 abort/timeout/截断/回滚等边界。

### 关键发现

1. **G3.3 是语义不等价而非简单缺失**：Cline 主动拒绝（安全护栏），我主动覆盖（便利特性）。这是设计哲学差异，需明确选择 Cline 的严格路径。
2. **G2.2 并行 vs 串行是设计选择差异**：Cline 假定命令独立，我假定命令可能有依赖。两者各有道理，但需在工具描述中明确，避免 LLM 困惑。
3. **G4.4 是唯一的 P0**：apply_patch 非原子性是数据完整性风险，必须优先修复。
4. **CRLF 处理对齐良好**：`editor.py` 的 `_detect_line_ending` / `_normalize_for_edit` / `_restore_line_ending` 三件套与 Cline `editor.ts` L79-85 `detectLineEnding` / `normalizeLineEndings` 逻辑等价，是少数完全对齐的细节。
5. **abort 机制对齐良好**：`_wait_process_with_abort` 的 `asyncio.wait` + `signal.wait()` 组合与 Cline `AbortController` + `addEventListener("abort")` 语义等价，仅 kill 范围不同（G2.4）。

### 未验证项

- 实际运行相同输入对比输出（需构造测试用例，本阶段未执行）
- 二进制文件边界（如恰好含 UTF-8 BOM 的文件）
- 超大文件流式读取内存占用对比

---

**阶段 G 结论**：四类内置工具的对齐度约 60%，核心 schema 与基础行为一致，但存在 1 个 P0 级数据安全差距（G4.4 patch 非原子）、5 个 P1 级功能/语义差距。最关键的语义不等价项是 G3.3（editor 覆盖 vs 报错）和 G2.2（串行 vs 并行），需明确选择对齐方向。CRLF 处理、abort 机制、old_text 唯一性检查等细节对齐良好。建议优先完成短期 6 项修复（P0-P1），可将对齐度提升至约 80%。
