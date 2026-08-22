# Stage 11: P2 上下文与压缩补全方案

> 生成时间：2026-07-26
> 优先级：P2
> 预估工作量：1 周
> 依赖：Stage 10 完成（推荐，10.1 metadata 链路与 10.4 ControlledStopError 是前置）
>
> 来源：
> - `CLINE_DIFF/SUMMARY_v2.md` §3.2 P2 级剩余差距 #7-#10
> - `CLINE_DIFF/phase_J_context_compaction.md`（J7 / J12 / J13 / J18）
>
> 涉及源文件：
> - 我的：`agent/context.py`、`agent/compaction.py`、`agent/budget_policy.py`、`agent/runtime.py`、`agent/types.py`
> - Cline：`third_party/cline/sdk/packages/core/src/extensions/context/compaction*.ts`、`third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 11.1 | `_summarize_tool_activity` 行号范围 | J7 | P2 | agent/compaction.py |
| 11.2 | agentic 失败 fallback 透传 abort signal | J12 | P2 | agent/compaction.py、agent/runtime.py |
| 11.3 | `CompactionStateManager` 状态投影 | J13 | P2 | agent/compaction.py、agent/types.py |
| 11.4 | `_truncate_tool_results` 处理 file/image | J18 | P2 | agent/compaction.py |

依赖关系：
- 11.1 / 11.2 / 11.4 互相独立，可并行
- 11.3 依赖 10.1（metadata 链路）和 10.4（ControlledStopError）
- 建议执行顺序：11.1 → 11.4 → 11.2 → 11.3

---

## 11.1 `_summarize_tool_activity` 行号范围（J7）

### 任务背景

来源 Phase J #J7。当前 `_summarize_tool_activity` 函数生成工具活动摘要（用于压缩前的上下文摘要），输出格式为：
```
- read_files (path/to/file.py)
- run_commands (python preprocess.py)
- editor (path/to/file.py)
```

但**未包含行号范围**，导致：
- LLM 无法定位工具操作的具体位置
- 压缩后 LLM 看到"读了 file.py"，但不知道读了哪些行
- 量化场景下，LLM 可能需要根据行号定位因子计算逻辑，缺行号导致定位失败

Cline 的 `compaction-summarizer.ts` 中工具活动摘要包含行号范围：
```
- read_files (path/to/file.py#L10-50)
- editor (path/to/file.py#L100-150, replaced 20 lines)
```

### 目标

为工具活动摘要添加行号范围：
1. `read_files` 工具记录读取的行号范围
2. `editor` 工具记录编辑的行号范围 + 替换行数
3. `apply_patch` 工具记录 patch 影响的行号范围
4. `run_commands` 工具无行号（输出命令本身）

### 当前实现位置

- `agent/compaction.py`（`_summarize_tool_activity` 函数）
- `agent/tools/read_files.py`（工具结果格式）
- `agent/tools/editor.py`（工具结果格式）
- `agent/tools/apply_patch.py`（工具结果格式）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction-summarizer.ts`（`summarizeToolActivity`）

### 修复步骤建议

1. **`_summarize_tool_activity` 解析工具结果**
   - 当前函数仅从 `ToolResultPart` 中提取 `tool_name` 和 `input`，需扩展提取 `output` 中的行号信息
   - 不同工具的 output 格式不同，需分别处理：
     - `read_files`：output 包含 `cat -n` 风格行号（Stage 3.2 已实现），正则提取首末行号
     - `editor`：output 包含 diff，正则提取 `@@ -start,len +start,len @@`
     - `apply_patch`：output 包含修改的文件列表，需从 patch 内容提取行号

2. **`read_files` 行号提取**
   - output 格式（Stage 3.2 已实现）：`     1\tcontent\n     2\tcontent\n...`
   - 正则：`^\s*(\d+)\t` 匹配首行，最后匹配行匹配末行
   - 摘要格式：`- read_files (path/to/file.py#L{start}-{end})`
   - 多文件读取时，每个文件独立显示行号范围

3. **`editor` 行号提取**
   - output 格式（Stage 3.3 已实现）：````diff\n@@ -{start},{len} +{start},{len} @@\n...`
   - 正则：`@@ -(\d+),(\d+) \+(\d+),(\d+) @@`
   - 摘要格式：`- editor (path/to/file.py#L{start}-{end}, replaced {len} lines)`
   - `start` / `end` 用 new chunk 的行号（修改后的位置）

4. **`apply_patch` 行号提取**
   - apply_patch 工具的 output 是 patch 应用结果，需解析 patch 内容
   - 每个 hunk 的 `@@ -start,len +start,len @@` 提取行号
   - 多文件 patch 时，按文件分组显示
   - 摘要格式：`- apply_patch (3 files modified: file1.py#L10-50, file2.py#L30-80, file3.py#L1-20)`

5. **`run_commands` 保持原样**
   - 命令工具无行号概念，保留现有格式：`- run_commands (python preprocess.py)`

6. **解析失败兜底**
   - 行号提取失败时（output 格式异常），保留原格式不报错
   - 不写 fallback：解析逻辑用 try/except 包裹，失败时仅 logger.warning

### 验证方法

1. 调用 `read_files` 读取文件前 50 行，触发压缩，确认摘要为 `- read_files (path#L1-50)`
2. 调用 `editor` 修改文件第 100-150 行，触发压缩，确认摘要为 `- editor (path#L100-150, replaced 50 lines)`
3. 调用 `apply_patch` 修改 3 个文件，确认摘要包含所有文件的行号范围
4. output 格式异常（手动构造畸形 output），确认解析失败时不报错，保留原格式

### 注意事项

- 行号范围基于**工具实际操作的行**，非整个文件
- 多次调用同一工具时，每次独立显示（不合并）
- 行号范围不影响摘要长度（仅追加 `#L10-50` 后缀）

---

## 11.2 agentic 失败 fallback 透传 abort signal（J12）

### 任务背景

来源 Phase J #J12。当前 agentic 压缩（调用 LLM 生成摘要）失败时，fallback 到非 agentic 压缩（简单截断）。但 fallback 路径**未透传 abort signal**：
- 用户在 agentic 压缩过程中点"停止"
- agentic 压缩抛 `AbortedError`，被 catch 后触发 fallback
- fallback 路径（非 agentic 截断）继续执行，无 abort 检查
- 用户中止后仍走完整个 fallback 流程，浪费时间

Cline 的 `compaction-runner.ts` 中 fallback 路径也订阅 abort signal，触发时立即返回。

### 目标

让 fallback 路径也响应 abort signal：
1. fallback 函数签名增加 `signal: asyncio.Event` 参数
2. fallback 关键步骤前检查 `signal.is_set()`
3. 触发时抛 `AbortedError`，与 agentic 路径行为一致

### 当前实现位置

- `agent/compaction.py`（`compact_messages` agentic 路径 + fallback 路径）
- `agent/runtime.py`（`_compact_context` 调用）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction-runner.ts`（fallback 路径订阅 abort）

### 修复步骤建议

1. **fallback 函数签名扩展**
   - 当前 `fallback_compact(messages: list, target_tokens: int) -> list`
   - 改为 `fallback_compact(messages: list, target_tokens: int, signal: asyncio.Event | None = None) -> list`
   - `signal=None` 时保持原行为（向后兼容，无 abort 检查）

2. **关键步骤前检查 abort**
   - 在 fallback 函数的循环中（如截断消息的 for 循环）：
     ```python
     for msg in messages:
         if signal and signal.is_set():
             raise AbortedError("compaction fallback aborted by user")
         # 截断逻辑...
     ```
   - 不在每个消息都检查（性能考虑），每 N 个消息检查一次（N=10）

3. **`compact_messages` 透传 signal**
   - 在 `compact_messages` 的 fallback 调用处：
     ```python
     try:
         result = agentic_compact(...)
     except AbortedError:
         raise  # abort 不触发 fallback，直接抛出
     except Exception as e:
         logger.warning(f"agentic compaction failed, fallback: {e}")
         result = fallback_compact(messages, target_tokens, signal=signal)
     ```
   - **关键**：`AbortedError` 不触发 fallback，直接向上抛出
   - 其他异常（如 LLM API 错误）才走 fallback

4. **`AbortedError` 异常类**
   - 在 `agent/types.py` 中确认 `AbortedError` 已定义（Stage 7 应已引入）
   - 若未定义，新增：
     ```python
     class AbortedError(Exception):
         """用户主动中止"""
         pass
     ```

5. **runtime 层 catch AbortedError**
   - 在 `agent/runtime.py::_compact_context` 中：
     ```python
     try:
         new_messages = compact_messages(messages, target_tokens, signal=self._abort_signal)
     except AbortedError:
         # 用户中止压缩，run 整体中止
         self.abort("compaction aborted by user")
         raise
     ```
   - 中止后整个 run 也中止（与 Cline 行为一致）

### 验证方法

1. 模拟 agentic 压缩失败（mock LLM 抛错），确认走 fallback
2. fallback 过程中触发 abort，确认 fallback 立即停止
3. agentic 过程中触发 abort，确认不走 fallback，直接抛 AbortedError
4. 无 abort 时，确认 fallback 正常完成（回归测试）

### 注意事项

- `AbortedError` 与 `ControlledStopError`（Stage 10.4）是不同语义，前者是用户中止，后者是 hook 拦截
- fallback 检查频率不宜过高（影响性能），每 10 条消息检查一次足够
- 不修改 agentic 路径的 abort 处理（已正确实现）

---

## 11.3 `CompactionStateManager` 状态投影（J13）

### 任务背景

来源 Phase J #J13。当前 `CompactionStateManager` 类管理压缩过程的状态（如原消息列表、压缩后消息列表、被丢弃的消息等），但**缺失 `system_prompt` 字段**和**投影函数**：
- 压缩时 system_prompt 被丢弃，无法在压缩后恢复
- 缺少 `project()` 函数将压缩状态映射到 `AgentRuntimeStateSnapshot`，前端无法显示压缩进度

Cline 的 `compaction-state-manager.ts` 包含 `system_prompt` 字段和 `project()` 方法。

### 目标

为 `CompactionStateManager` 补齐：
1. `system_prompt: str` 字段，记录压缩时的 system prompt
2. `project()` 方法，返回 `CompactionStateSnapshot` 供前端显示
3. snapshot 包含：原消息数、压缩后消息数、被丢弃消息数、压缩耗时、是否成功

### 当前实现位置

- `agent/compaction.py`（`CompactionStateManager` 类）
- `agent/types.py`（`AgentRuntimeStateSnapshot` 类型，需扩展）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction-state-manager.ts`（`CompactionStateManager` 类）

### 修复步骤建议

1. **`CompactionStateManager` 增加 `system_prompt` 字段**
   - 在 `__init__` 中增加：
     ```python
     def __init__(self, ...):
         # 原有字段...
         self.system_prompt: str = ""
     ```
   - 在 `start_compaction(messages, system_prompt)` 方法中保存 system_prompt
   - 压缩完成后保留 system_prompt（不丢弃）
   - 压缩后的 messages 列表前仍需追加 system_prompt（由 runtime 处理）

2. **新增 `project()` 方法**
   - 在 `CompactionStateManager` 中新增：
     ```python
     def project(self) -> CompactionStateSnapshot:
         """返回压缩状态快照，供前端显示"""
         return CompactionStateSnapshot(
             original_count=len(self.original_messages),
             compacted_count=len(self.compacted_messages),
             discarded_count=len(self.discarded_messages),
             elapsed_ms=self._elapsed_ms,
             status=self._status,  # "pending" / "running" / "completed" / "failed"
             system_prompt_preserved=bool(self.system_prompt),
         )
     ```
   - 快照是只读的，前端可定期查询显示进度

3. **`CompactionStateSnapshot` 类型**
   - 在 `agent/types.py` 中新增：
     ```python
     @dataclass(frozen=True)
     class CompactionStateSnapshot:
         original_count: int
         compacted_count: int
         discarded_count: int
         elapsed_ms: int
         status: str
         system_prompt_preserved: bool
     ```
   - `frozen=True` 保证不可变，与 `AgentRuntimeStateSnapshot` 语义一致

4. **`AgentRuntimeStateSnapshot` 集成**
   - 在 `AgentRuntimeStateSnapshot` 中增加 `compaction: CompactionStateSnapshot | None` 字段
   - 默认 `None`（无压缩活动时）
   - 压缩进行中由 `CompactionStateManager.project()` 填充
   - 前端从 `run_started` / `message_added` 等事件中读取 snapshot.compaction 显示进度

5. **system_prompt 恢复**
   - 在 `compact_messages` 完成后，runtime 重新构造 messages：
     ```python
     new_messages = compact_messages(old_messages, target_tokens, ...)
     # 保留 system_prompt（不参与压缩）
     self._state.system_prompt = manager.system_prompt
     ```
   - system_prompt 不写入 messages 列表（与 Cline 行为一致，作为独立字段）

6. **压缩事件携带 snapshot**
   - 在 `compaction-started` / `compaction-completed` / `compaction-failed` / `compaction-skipped` 事件中携带 `CompactionStateSnapshot`
   - 前端从事件中读取状态显示进度条
   - 保留现有事件结构，仅增加 `snapshot` 字段

### 验证方法

1. 触发压缩，确认 `CompactionStateManager.system_prompt` 保存了原 system_prompt
2. 压缩完成后，确认 `self._state.system_prompt` 仍为原值（不丢失）
3. 调用 `project()`，确认返回 `CompactionStateSnapshot` 包含正确字段
4. 前端从事件中读取 snapshot，确认显示压缩进度

### 注意事项

- `system_prompt` 不参与压缩（始终保留），仅 messages 列表被压缩
- `project()` 是只读操作，不修改内部状态
- `CompactionStateSnapshot` 不可变（frozen），避免前端误改

---

## 11.4 `_truncate_tool_results` 处理 file/image（J18）

### 任务背景

来源 Phase J #J18。当前 `_truncate_tool_results` 函数在上下文超限时截断工具结果，但**仅处理 `string` 类型的 content**，未处理 `file` / `image` 类型：
- `ToolResultPart.content` 可能是 `list[TextPart | ImagePart | FilePart]`（Stage 2.2 已支持）
- file / image 类型用 `len(content)` 判断长度，结果为 1（始终"很短"），从不被截断
- 导致 file / image 大量堆积时上下文超限，但截断逻辑未生效

Cline 的 `compaction-truncator.ts` 中对 file / image 类型有专门处理：
- file：base64 内容超过阈值时丢弃，保留文件名和路径
- image：分辨率过大时降采样，或直接丢弃保留 alt 描述

### 目标

让 `_truncate_tool_results` 处理 file/image 类型：
1. file 类型：超阈值时丢弃 base64 内容，保留文件名和路径
2. image 类型：超阈值时丢弃图像数据，保留 alt 描述
3. 截断后在 content 中追加 `[truncated]` 标记

### 当前实现位置

- `agent/compaction.py`（`_truncate_tool_results` 函数）
- `agent/types.py`（`FilePart` / `ImagePart` 类型，Stage 2.2 已有）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction-truncator.ts`（`truncateToolResults`）

### 修复步骤建议

1. **`_truncate_tool_results` 扩展 content 类型判断**
   - 当前函数遍历 `ToolResultPart.content`：
     ```python
     for part in content:
         if isinstance(part, TextPart):
             # 截断 string
         # 缺 file/image 处理
     ```
   - 扩展为：
     ```python
     for part in content:
         if isinstance(part, TextPart):
             # 原有 string 截断逻辑
         elif isinstance(part, FilePart):
             # 新增 file 截断逻辑
         elif isinstance(part, ImagePart):
             # 新增 image 截断逻辑
     ```

2. **file 截断逻辑**
   - `FilePart` 字段：`file_name` / `file_path` / `file_data`（base64）
   - 阈值：单文件 base64 超过 `MAX_FILE_DATA_LENGTH = 100_000` 字符时截断
   - 截断策略：
     ```python
     if len(part.file_data) > MAX_FILE_DATA_LENGTH:
         truncated_part = FilePart(
             file_name=part.file_name,
             file_path=part.file_path,
             file_data="",  # 清空 base64
             truncated=True,
             truncate_reason="file_data_exceeds_limit",
         )
     ```
   - 保留 `file_name` / `file_path`，让 LLM 知道文件存在但内容被丢弃
   - 增加 `truncated` / `truncate_reason` 字段（需扩展 `FilePart` 类型）

3. **image 截断逻辑**
   - `ImagePart` 字段：`image_data`（base64）/ `alt_text` / `mime_type`
   - 阈值：单图 base64 超过 `MAX_IMAGE_DATA_LENGTH = 50_000` 字符时截断
   - 截断策略：
     ```python
     if len(part.image_data) > MAX_IMAGE_DATA_LENGTH:
         truncated_part = ImagePart(
             image_data="",
             alt_text=part.alt_text or "[image truncated]",
             mime_type=part.mime_type,
             truncated=True,
             truncate_reason="image_data_exceeds_limit",
         )
     ```
   - 保留 `alt_text`，让 LLM 知道图像存在但数据被丢弃

4. **`FilePart` / `ImagePart` 类型扩展**
   - 在 `agent/types.py` 中为两个类型增加可选字段：
     ```python
     @dataclass
     class FilePart:
         file_name: str
         file_path: str
         file_data: str
         truncated: bool = False  # 新增
         truncate_reason: str = ""  # 新增

     @dataclass
     class ImagePart:
         image_data: str
         alt_text: str
         mime_type: str
         truncated: bool = False  # 新增
         truncate_reason: str = ""  # 新增
     ```
   - 默认值 `False` / `""` 保证向后兼容

5. **截断后标记**
   - 在 `ToolResultPart` 中追加一个 `TextPart` 标记：
     ```python
     if any(getattr(p, 'truncated', False) for p in content):
         content.append(TextPart(text="[truncated: file/image data exceeds limit]"))
     ```
   - 让 LLM 知道部分内容被截断

6. **截断阈值配置**
   - 阈值作为模块常量，未来可由 `AgentRuntimeConfig` 配置
   - 当前固定值：file 100KB，image 50KB（base64 字符数）
   - 不写 fallback：超阈值必须截断

### 验证方法

1. 构造 `FilePart` 含 200KB base64 数据，调用 `_truncate_tool_results`
2. 确认 `file_data=""`，`truncated=True`，`truncate_reason="file_data_exceeds_limit"`
3. 确认 `ToolResultPart.content` 末尾追加 `[truncated]` 标记
4. 构造 `ImagePart` 含 80KB base64 数据，确认同样被截断
5. 小尺寸 file/image 不被截断（回归测试）

### 注意事项

- 截断阈值基于 base64 字符数（非字节数），base64 后约为原大小的 1.33 倍
- `truncated` 字段需在前端 UI 中显示（如"⚠ 内容已截断"图标）
- 不修改 TextPart 的截断逻辑（保留原行为）

---

## 12. 阶段汇总

### 12.1 完成判据

- 11.1：工具活动摘要包含行号范围
- 11.2：fallback 路径响应 abort signal
- 11.3：`CompactionStateManager` 含 system_prompt + project()
- 11.4：file/image 类型在截断时被正确处理

### 12.2 风险与回滚

- 11.1 行号解析依赖工具 output 格式，格式变化时解析失败（兜底保留原格式）
- 11.2 / 11.3 涉及压缩核心逻辑，需充分回归测试
- 11.4 类型字段扩展向后兼容，风险低

### 12.3 后续衔接

- 11.3 完成后，Stage 14 的 Z3/Z4（事件枚举）可基于 `CompactionStateSnapshot` 扩展
- 11.4 完成后，Stage 12 的 G4.1-G4.5（apply_patch 鲁棒性）可基于截断标记扩展

---

**Stage 11 结束。建议按 11.1 → 11.4 → 11.2 → 11.3 顺序执行，完成后进入 Stage 12。**
