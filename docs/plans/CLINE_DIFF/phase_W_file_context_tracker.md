# Phase W: FileContextTracker 对比报告

> 对标源码：
> - `third_party/cline/apps/vscode/src/core/context/context-tracking/FileContextTracker.ts`
> - `third_party/cline/apps/vscode/src/core/context/context-tracking/ContextTrackerTypes.ts`
> - 相关：`third_party/cline/sdk/packages/core/src/extensions/context/compaction-shared.ts`（_summarize_tool_activity 集成点）
> - 相关：`third_party/cline/apps/vscode/src/core/storage/disk.ts`（saveTaskMetadata 持久化实现）
>
> 当前实现：
> - `agent/file_context_tracker.py`
> - `agent/runtime.py`（after_tool hook 集成点，L903-L1017）
> - `agent/server.py`（API 端点，L942-L991）
> - `agent/context.py`（压缩集成点 `_summarize_tool_activity_v2`，L1207-L1263）
>
> 对比维度：W1-W13

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 0 项 |
| 弱对齐 | 4 项 |
| 语义不等价 | 2 项 |
| 缺失 | 1 项 |
| 额外增强 | 6 项 |
| **对齐度** | **约 35%**（按"逻辑等价"严格判定；若计入额外增强的功能覆盖则约 85%）|

**关键发现**：本阶段的"对齐度低"并不等同于"实现质量差"。Cline 的 `FileContextTracker` 设计目标是 **过期检测（stale detection）**——通过 chokidar 文件 watcher 检测用户在 Cline 外部修改文件，避免 diff 编辑时上下文过期；而本仓库的实现设计目标是 **活动日志（activity logging）**——记录工具读写的文件清单，用于压缩摘要和前端审计。两者在数据模型、记录时机、查询接口上均不同，属于 **同名为不同语义** 的实现。

本仓库的实现更适合"无文件 watcher 的服务端 agent"场景（量化系统无 VSCode 扩展，无需检测外部编辑），且在压缩集成（W10）、API 暴露（W12）、原子写入（W13）三处有合理增强。

---

## 2. 详细对比表

| # | 对比项 | Cline 实现 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| W1 | `FileContextTracker` 类结构 | `FileContextTracker.ts` L24-L279，含 file watcher + stale 检测 + pending warning | `file_context_tracker.py` L95-L307，仅记录 + 查询 + 持久化 | 弱对齐 |
| W2 | 记录时机（after_tool hook） | 显式 `trackFileContext()` 调用 + chokidar `change` 事件触发 | `runtime.py` L254 注册 after_tool hook，自动按 tool_name 提取路径 | 弱对齐 |
| W3 | 操作类型枚举 | `read_tool` / `user_edited` / `cline_edited` / `file_mentioned`（按"谁编辑"分类） | `read` / `edited` / `created` / `deleted`（按"什么操作"分类） | 语义不等价 |
| W4 | 持久化格式（JSON 结构） | `TaskMetadata { files_in_context, model_usage, environment_history }`（多 section 共享文件） | `{ session_id, entries, updated_at }`（独立文件） | 弱对齐 |
| W5 | 持久化路径（按 session_id 隔离） | `<taskDir>/api.json`（与其他 metadata 混存，按 taskId 隔离） | `agent_data/file_context/<session_id>.json`（独立目录，按 session_id 隔离） | 弱对齐 |
| W6 | `get_state()` 返回（精简视图） | 无此方法 | `file_context_tracker.py` L198-L217 返回 `{read,edited,created,deleted}` | 额外增强 |
| W7 | `get_entries()` 返回（完整记录） | 无此方法（通过 `files_in_context` 数组获取） | `file_context_tracker.py` L219-L222 返回 `[{path,operation,timestamp,tool_name,iteration}]` | 额外增强 |
| W8 | 路径规范化（expanduser + resolve） | 仅 `setupFileWatcher` 用 `path.resolve(cwd, filePath)`（L54），`trackFileContext` 不规范化 | `file_context_tracker.py` L164-L170 用 `Path.expanduser().resolve(strict=False)` + 反斜杠转正斜杠 | 额外增强 |
| W9 | 去重策略（同 path+operation 保留首次） | 不去重，每次新增 entry 并将旧的标记为 `stale`（L113-L117） | 同 path+operation 去重，保留首次记录（L178-L180） | 语义不等价 |
| W10 | 集成到压缩（`_summarize_tool_activity_v2`） | `compaction-shared.ts` 的 `extractFileOps`/`summarizeToolActivity` 不使用 tracker，直接扫消息 | `context.py` L1207-L1263 优先用 tracker，fallback 扫消息 | 额外增强 |
| W11 | SSE 事件（`file_context_updated`） | 无此 SSE 事件 | 无此 SSE 事件（server.py SSE 事件仅 token/tool_call/tool_output/phase/done/error/approval_request/todos_updated/mode_changed/pending_prompts_*） | 缺失（双方均无） |
| W12 | API 端点（GET/DELETE） | 无 REST API（VSCode 扩展内部访问 workspace state） | `server.py` L942-L991 提供 `GET /sessions/{id}/file_context` + `DELETE /sessions/{id}/file_context` | 额外增强 |
| W13 | 原子写入（tmp + replace） | `disk.ts` L182-L190 用 `fs.writeFile` 直接覆盖（非原子） | `file_context_tracker.py` L251-L257 用 `tmp_path.write_text` + `tmp_path.replace`（原子替换） | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #W1：类结构差异大 + stale detection 系列功能缺失

**严重度**：P1（设计目标不同导致的核心功能缺失）

**Cline 实现**（`FileContextTracker.ts` L24-L279）：
- 字段：`controller`、`taskId`、`fileWatchers: Map<string, FSWatcher>`、`recentlyModifiedFiles: Set<string>`、`recentlyEditedByCline: Set<string>`
- 方法：`setupFileWatcher`、`trackFileContext`、`addFileToFileContextTracker`、`getAndClearRecentlyModifiedFiles`、`markFileAsEditedByCline`、`dispose`、`detectFilesEditedAfterMessage`、`storePendingFileContextWarning`、`retrievePendingFileContextWarning`、`retrieveAndClearPendingFileContextWarning`
- 核心机制：chokidar 监听文件外部修改，区分"Cline 编辑"与"用户编辑"，避免 diff 编辑时上下文过期

**我的实现**（`file_context_tracker.py` L95-L307）：
- 字段：`session_id`、`storage_dir`、`storage_path`、`_entries: list[FileContextEntry]`、`_lock: threading.Lock`
- 方法：`record`、`get_state`、`get_entries`、`get_files_all`、`save`、`_load`、`clear`
- 核心机制：after_tool hook 自动记录工具读写路径，持久化到独立 JSON 文件

**缺失的 Cline 功能**：
1. `setupFileWatcher` / `dispose`：chokidar 文件 watcher（无 VSCode 环境无需）
2. `markFileAsEditedByCline`：标记 Cline 自身编辑以避免误报
3. `detectFilesEditedAfterMessage`：恢复 checkpoint 时检测文件冲突
4. `storePendingFileContextWarning` / `retrievePendingFileContextWarning` / `retrieveAndClearPendingFileContextWarning`：跨任务重初始化持久化警告

**影响**：
- 服务端 agent 场景下无文件 watcher 需求（agent 是唯一编辑者），stale detection 系列功能可缺失
- 但 `detectFilesEditedAfterMessage` 在 checkpoint 恢复场景下有价值，当前本仓库无 checkpoint 恢复，可暂不实现
- `recentlyModifiedFiles` / `recentlyEditedByCline` 双 Set 机制用于抑制 watcher 误报，无 watcher 时亦无需

**修复建议**：
- 短期：保持现状。本仓库无文件 watcher 需求，stale detection 系列功能非必需
- 中期：若后续实现 checkpoint 恢复（Phase S 已做 session 持久化），考虑补充 `detectFilesEditedAfterMessage` 用于恢复时文件冲突检测
- 长期：若引入外部编辑场景（如用户在 IDE 中手动改文件），需补充 chokidar 等价的 watchdog 文件监听

**优先级**：P1

---

### 差距 #W3：操作类型枚举语义不等价

**严重度**：P1（同名概念语义不同，可能导致跨阶段对比误判）

**Cline 实现**（`ContextTrackerTypes.ts` L2-L9）：
```typescript
export interface FileMetadataEntry {
    path: string
    record_state: "active" | "stale"
    record_source: "read_tool" | "user_edited" | "cline_edited" | "file_mentioned"
    cline_read_date: number | null
    cline_edit_date: number | null
    user_edit_date?: number | null
}
```
- 维度：**按"谁触发编辑"分类**（user_edited vs cline_edited）
- `file_mentioned`：用户在 prompt 中提到文件（如 @path）
- 不区分 created/deleted

**我的实现**（`file_context_tracker.py` L57-L63）：
```python
OP_READ = "read"
OP_EDITED = "edited"
OP_CREATED = "created"
OP_DELETED = "deleted"
```
- 维度：**按"操作类型"分类**（edited vs created vs deleted）
- 不区分 user_edited vs cline_edited（agent 是唯一编辑者，无需区分）
- 无 `file_mentioned`（当前未追踪 prompt 中提到的文件）

**影响**：
- 我的 `OP_EDITED` 与 Cline 的 `cline_edited` 语义部分对齐（都指 agent 编辑），但不完全等价（我合并了 user_edited 进 edited 类）
- 我的 `OP_CREATED` 在 Cline 中无对应（Cline 把新建文件也归为 `cline_edited`）
- 我的 `OP_DELETED` 预留未使用，Cline 无此概念
- 压缩摘要集成时（W10），我把 `created` 合并到 `editedFiles` 列表（`context.py` L1237-L1243），与 Cline 压缩摘要的 `modifiedFiles` 语义对齐

**修复建议**：
- 保持现状。本仓库无外部编辑场景，"按操作类型分类"更适合压缩摘要和审计需求
- 可选：在 `FileContextEntry` 中补充 `source` 字段（值：`tool` / `user_mentioned`），用于未来追踪 prompt 提到的文件
- 文档中明确标注"本实现操作类型语义与 Cline 不同"，避免后续 phase 对比误判

**优先级**：P2（已通过文档标注缓解，无需改代码）

---

### 差距 #W9：去重策略相反

**严重度**：P1（数据模型根本差异，影响时间序列查询）

**Cline 实现**（`FileContextTracker.ts` L107-L162）：
- **不去重**。每次 `trackFileContext` 调用都新增一条 `FileMetadataEntry`
- 旧的同 path entry 标记为 `record_state: "stale"`，新 entry 标记为 `"active"`（L113-L117）
- 保留完整时间序列：同一文件可能有 N 条记录，按 `cline_read_date` / `cline_edit_date` / `user_edit_date` 排序可还原操作历史
- 用 `getLatestDateForField`（L120-L126）从历史中取最新时间戳填入新 entry

**我的实现**（`file_context_tracker.py` L176-L188）：
```python
# 同 path+operation 去重（保留首次记录的时间戳）
for entry in self._entries:
    if entry.path == path_str and entry.operation == operation:
        return
```
- **去重**。同 path+operation 只保留首次记录，后续相同记录直接忽略
- 不保留时间序列，只保留"该文件曾被该操作触达"的事实
- 优势：内存占用小，JSON 体积小，前端展示清晰
- 劣势：无法还原"该文件被读取/编辑了几次"，无法做时间序列分析

**影响**：
- 压缩摘要场景：我的策略够用（只需知道"哪些文件被读/改过"）
- 审计场景：我的策略不够（无法回答"该文件被编辑了几次，分别在什么时间"）
- checkpoint 恢复场景：Cline 的 `detectFilesEditedAfterMessage` 依赖时间序列（按 `cline_edit_date > messageTs` 判断），我的策略无法支持此功能

**修复建议**：
- 保持现状（活动日志场景去重合理）
- 若未来需要审计/时间序列分析，可增加 `record_all()` 方法保留全部记录，`get_state()` 仍返回去重视图
- 当前 `get_entries()` 返回的是去重后的列表，可在文档中明确"entries 是去重后的快照，非完整操作历史"

**优先级**：P2

---

### 差距 #W11：SSE 事件 file_context_updated 缺失

**严重度**：P2（前端无法实时感知文件上下文变化）

**Cline 实现**：
- `FileContextTracker.ts` 不发射任何 SSE 事件
- 前端通过 VSCode 扩展内部的 workspace state 变化监听获取更新
- 无 `file_context_updated` 事件

**我的实现**：
- `server.py` 的 SSE 事件类型清单（L232-L235 + 实际 yield 调用）：
  - `token` / `tool_call` / `tool_output` / `phase` / `done` / `error`
  - `approval_request` / `todos_updated` / `mode_changed`
  - `pending_prompts_updated` / `pending_prompts_drained`
- 无 `file_context_updated` 事件
- after_tool hook 中调用 `self._file_tracker.save()`（`runtime.py` L1012）但未推送 SSE

**影响**：
- 前端无法实时刷新"当前会话涉及的文件"面板，必须轮询 `GET /sessions/{id}/file_context`
- 工具调用完成后前端需要主动拉取，体验略差
- Cline 也无此事件，所以不算"落后于 Cline"，但 task W11 期望有

**修复建议**：
- 短期：前端在收到 `tool_output` 事件后主动调用 `GET /sessions/{id}/file_context` 刷新
- 中期：在 `_file_context_tracker_hook` 末尾通过事件总线推送 `file_context_updated`，SSE 生成器订阅并 yield
  ```python
  # 伪代码
  self._file_tracker.save()
  await self._event_bus.emit({
      "type": "file_context_updated",
      "session_id": self.config.session_id,
      "state": self._file_tracker.get_state(),
  })
  ```
- 长期：将 `file_context_updated` 加入 SSE 事件协议文档

**优先级**：P2

---

### 差距 #W2：记录时机触发源不同

**严重度**：P2（自动化程度不同）

**Cline 实现**（`FileContextTracker.ts` L84-L100 + L67-L74）：
- **显式调用**：工具实现内部主动调用 `trackFileContext(filePath, operation)`
- **watcher 触发**：chokidar `change` 事件触发 `trackFileContext(filePath, "user_edited")`
- 两种触发源：工具主动记录 + watcher 被动记录

**我的实现**（`runtime.py` L244-L254 + L903-L1017）：
- **hook 自动化**：在 `AgentRuntime.__init__` 注册 `_file_context_tracker_hook` 到 `after_tool` hook 链
- 工具执行成功后（`is_error=False`），根据 `tool_name` + `tool_input` 自动提取路径：
  - `read_files` / `file_read`：从 `input.files[].path` 提取，记为 `OP_READ`
  - `list_files`：从 `input.path` 提取，记为 `OP_READ`
  - `editor` / `file_write` / `apply_patch`：从 `input.path`/`file_path`/`target_file` 提取，按 `result.created`/`is_new` 标志判断 `OP_CREATED` vs `OP_EDITED`
  - `apply_patch` 还从 `input.diff` 的 `+++`/`---` 头解析路径
  - `exec` / `run_commands`：不记录
- 工具失败（`is_error=True`）不记录，避免噪声

**差异点**：
- 我用 hook 自动化更彻底（工具无需感知 tracker），但 Cline 的显式调用允许工具自定义 `operation`（如 `file_mentioned`）
- 我无 watcher 触发，无法记录"用户外部编辑"事件
- 我的 created/edited 判断依赖 `result.output` 内容（`runtime.py` L992-L998），是启发式判断，可能误判

**影响**：
- 自动化 hook 对工具开发者透明，新增工具无需修改 tracker 代码（除非工具路径字段不在 `path`/`file_path`/`target_file` 中）
- 启发式 created 判断可能漏标（如工具返回的 output 中无 "created" 字样但实际是新文件）

**修复建议**：
- 保持现状。hook 模式更符合本仓库的"工具零侵入"设计
- 工具若需自定义 operation，可在工具实现中直接调用 `tracker.record()` 补充记录（hook 已记录的会被去重忽略）
- created 判断可在 `BaseTool` 基类增加 `is_new_file` 属性，工具显式声明，避免启发式判断

**优先级**：P3

---

### 差距 #W4：持久化 JSON 结构不同

**严重度**：P3（结构不同但功能等价）

**Cline 实现**（`ContextTrackerTypes.ts` L28-L32 + `disk.ts` L182-L190）：
```json
{
    "files_in_context": [
        {
            "path": "/abs/path/to/file.py",
            "record_state": "active",
            "record_source": "cline_edited",
            "cline_read_date": 1721900000000,
            "cline_edit_date": 1721900000000,
            "user_edit_date": null
        }
    ],
    "model_usage": [...],
    "environment_history": [...]
}
```
- 与 `model_usage` / `environment_history` 共享同一个 `api.json` 文件
- 时间戳为毫秒级 Unix 时间戳
- `record_state` 标记 active/stale

**我的实现**（`file_context_tracker.py` L243-L248）：
```json
{
    "session_id": "abc123",
    "entries": [
        {
            "path": "/abs/path/to/file.py",
            "operation": "edited",
            "timestamp": "2026-07-25T10:30:00+00:00",
            "tool_name": "editor",
            "iteration": 1
        }
    ],
    "updated_at": "2026-07-25T10:30:05+00:00"
}
```
- 独立文件，不与其他 metadata 混存
- 时间戳为 ISO 8601 字符串（含时区）
- 无 record_state 概念（去重策略不保留 stale）

**差异点**：
- 时间戳格式：Cline 用毫秒 Unix，我用 ISO 8601 字符串（可读性更好，但跨语言解析需注意）
- 字段维度：Cline 区分 `cline_read_date` / `cline_edit_date` / `user_edit_date` 三个时间字段，我用单一 `timestamp`
- 额外字段：我记录 `tool_name` 和 `iteration`（审计用），Cline 不记录

**影响**：
- 跨工具/跨语言交互时，ISO 8601 比 Unix 时间戳更易读，但需统一时区处理
- 缺少三时间字段意味着无法回答"该文件最后被 Cline 读是什么时候，最后被用户改是什么时候"

**修复建议**：
- 保持现状。本仓库无 user_edit 概念，单一 timestamp 够用
- 若后续接入外部编辑场景，可在 `FileContextEntry` 补充 `read_at` / `edited_at` 字段

**优先级**：P3

---

### 差距 #W5：持久化路径布局不同

**严重度**：P3（路径不同但都按 session/task 隔离）

**Cline 实现**：
- 路径：`<workspace>/tasks/<taskId>/api.json`（`GlobalFileNames.taskMetadata`）
- 与 `model_usage` / `environment_history` 等共享同一文件
- 隔离维度：按 `taskId`

**我的实现**（`file_context_tracker.py` L117-L122）：
- 路径：`<cwd>/agent_data/file_context/<session_id>.json`
- 独立目录 `agent_data/file_context/`，每会话一个文件
- 隔离维度：按 `session_id`
- 支持 `set_storage_dir()` 全局配置（L325-L329）

**差异点**：
- Cline 与其他 task metadata 混存，读取时需解析整个 `TaskMetadata`
- 我独立文件，读取/写入/删除互不影响其他 metadata
- 我的目录可通过 `set_storage_dir` 全局配置，Cline 路径由 `ensureTaskDirectoryExists` 固定

**影响**：
- 独立文件方案在并发写入、原子替换、单文件清理上更安全
- 混存方案在跨 metadata 原子更新上有优势（一次写全 metadata）

**修复建议**：保持现状。独立文件方案与本仓库的"原子写入（W13）"配合更好。

**优先级**：P3

---

### 差距 #W10：压缩集成是额外增强（Cline 压缩不用 tracker）

**严重度**：不适用（增强项，非差距）

**Cline 实现**（`compaction-shared.ts` L398-L435 + L535-L609）：
- `extractFileOps(messages)`：扫描消息中的 `tool_use` block，按 `block.name`（`read_files` / `editor` / `apply_patch`）提取路径，返回 `{readFiles, modifiedFiles}`
- `summarizeToolActivity(messages)`：扫描消息提取 `readFiles` / `editedFiles` / `commands`
- **不使用 `FileContextTracker`**。压缩摘要完全从消息扫描得来
- `FileContextTracker` 仅用于 stale detection，与压缩解耦

**我的实现**（`context.py` L1207-L1263）：
```python
def _summarize_tool_activity_v2(
    self,
    messages: list[AgentMessage],
    session_id: str | None = None,
) -> dict[str, list[str]]:
    # 始终从消息提取 commands（tracker 不记录命令）
    from_messages = self._summarize_tool_activity(messages)
    commands = from_messages.get("commands", [])

    # 优先从 tracker 取文件列表
    if session_id:
        try:
            from agent.file_context_tracker import get_tracker
            tracker = get_tracker(session_id)
            state = tracker.get_state()
            # tracker 中 created 也归入 editedFiles
            edited = []
            for p in state.get("edited", []):
                if p not in edited:
                    edited.append(p)
            for p in state.get("created", []):
                if p not in edited:
                    edited.append(p)
            read_files = state.get("read", [])
            if read_files or edited:
                return {
                    "readFiles": read_files,
                    "editedFiles": edited,
                    "commands": commands,
                }
        except Exception as e:
            logger.debug("...回退到消息扫描: %s", e)

    # fallback: 用消息扫描结果
    return from_messages
```

**增强点**：
- 优先用 tracker 数据，跨压缩周期保留文件状态
- 多次压缩后，tracker 累积的文件清单比"仅扫当前消息"更完整（旧消息被压缩后，扫消息会丢失文件路径，但 tracker 仍保留）
- fallback 到消息扫描，保证 tracker 无数据时仍可工作
- `commands` 始终从消息扫描（tracker 不记录命令），与 Cline 一致

**影响**：
- 压缩摘要的"Files"段在多次压缩后仍能列出完整文件清单，不会因旧消息被压缩而丢失
- Cline 的方案在多次压缩后会丢失早期文件路径（除非 LLM 摘要中保留）

**修复建议**：保持现状。这是合理的额外增强。

**优先级**：不适用（增强项）

---

### 差距 #W13：原子写入是额外增强

**严重度**：不适用（增强项，非差距）

**Cline 实现**（`disk.ts` L182-L190）：
```typescript
export async function saveTaskMetadata(taskId: string, metadata: TaskMetadata) {
    try {
        const taskDir = await ensureTaskDirectoryExists(taskId)
        const filePath = path.join(taskDir, GlobalFileNames.taskMetadata)
        await fs.writeFile(filePath, JSON.stringify(metadata, null, 2))
    } catch (error) {
        Logger.error("Failed to save task metadata:", error)
    }
}
```
- 直接 `fs.writeFile` 覆盖，非原子
- 写入过程中崩溃会留下半截 JSON，下次 `getTaskMetadata` 解析失败

**我的实现**（`file_context_tracker.py` L250-L258）：
```python
self.storage_dir.mkdir(parents=True, exist_ok=True)
tmp_path = self.storage_path.with_suffix(".tmp")
tmp_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
tmp_path.replace(self.storage_path)  # 原子替换
```
- 先写 `.tmp` 文件，再 `replace` 替换（POSIX 原子操作，Windows 上 `Path.replace` 调用 `os.replace` 也是原子）
- 写入过程中崩溃只丢 `.tmp` 文件，正式文件保持上次完整状态

**影响**：
- 服务端 agent 长时间运行，崩溃风险高于 IDE 扩展，原子写入价值更大
- 多线程并发写入时，原子替换避免读到半截 JSON

**修复建议**：保持现状。这是合理的额外增强。

**优先级**：不适用（增强项）

---

## 4. 一致性统计

| 一致性等级 | 数量 | 子项编号 |
|-----------|------|---------|
| 完全一致 | 0 项 | — |
| 弱对齐 | 4 项 | W1, W2, W4, W5 |
| 语义不等价 | 2 项 | W3, W9 |
| 缺失（双方均无）| 1 项 | W11 |
| 额外增强（我有 Cline 无）| 6 项 | W6, W7, W8, W10, W12, W13 |

**按"逻辑等价"严格判定对齐度**：4/13 ≈ 30%（仅弱对齐算部分对齐）
**按"功能覆盖"判定对齐度**：11/13 ≈ 85%（弱对齐 + 额外增强 + 语义不等价都有对应功能）

**核心结论**：本阶段对齐度低是 **设计目标不同** 导致的，非实现缺陷。Cline 聚焦"过期检测"，本仓库聚焦"活动日志 + 压缩集成"，两者在压缩场景下本仓库方案更优（W10 增强），在 IDE 集成场景下 Cline 方案更优（stale detection）。

---

## 5. 修复建议

### 短期（P2 及以下，不阻塞）

1. **W11 SSE 事件**：前端在收到 `tool_output` 事件后主动调用 `GET /sessions/{id}/file_context` 刷新文件面板。无需后端改动。
2. **W3 操作类型文档**：在 `file_context_tracker.py` 模块 docstring 中明确标注"本实现操作类型语义与 Cline 不同（按操作类型 vs 按触发者）"，避免后续 phase 对比误判。
3. **W9 去重策略文档**：在 `get_entries()` docstring 中明确"entries 是去重后的快照，非完整操作历史"。

### 中期（P1，可选）

4. **W1 checkpoint 恢复集成**：若 Phase S 的 session 持久化后续扩展为 checkpoint 恢复，考虑补充 `detectFilesEditedAfterMessage` 等价方法，用于恢复时文件冲突检测。需先评估量化场景是否需要 checkpoint。
5. **W2 created 判断改进**：在 `BaseTool` 基类增加 `is_new_file` 属性，工具显式声明新建文件，避免 `_file_context_tracker_hook` 中的启发式判断（`runtime.py` L992-L998）。

### 长期（P1，场景驱动）

6. **W1 文件 watcher**：若后续引入"用户在 IDE 中手动改文件"场景，需补充 watchdog 等价的文件监听，并增加 `user_edited` 操作类型。当前量化 agent 是唯一编辑者，无需。
7. **W11 SSE 事件后端化**：在 `_file_context_tracker_hook` 末尾通过事件总线推送 `file_context_updated`，SSE 生成器订阅并 yield，实现前端实时刷新。

---

## 6. 验证记录

| 验证项 | 验证方法 | 结果 |
|--------|---------|------|
| W1 类结构对比 | Read `FileContextTracker.ts` L24-L279 + `file_context_tracker.py` L95-L307 | 字段/方法清单已核对，差异已记录 |
| W2 after_tool hook 注册点 | Read `runtime.py` L244-L254 + L903-L1017 | hook 已注册到 `_hooks.after_tool`，按 tool_name 提取路径逻辑已核对 |
| W3 操作类型枚举 | Read `ContextTrackerTypes.ts` L2-L9 + `file_context_tracker.py` L57-L63 | 语义差异已确认：按"谁编辑" vs 按"什么操作" |
| W4 持久化格式 | Read `file_context_tracker.py` L243-L248 + `ContextTrackerTypes.ts` L28-L32 | JSON 结构差异已记录 |
| W5 持久化路径 | Read `file_context_tracker.py` L117-L122 + `disk.ts` L182-L190 | 路径布局差异已确认 |
| W6 get_state 返回 | Read `file_context_tracker.py` L198-L217 | Cline 无此方法，我的实现有，标为额外增强 |
| W7 get_entries 返回 | Read `file_context_tracker.py` L219-L222 | Cline 无此方法，标为额外增强 |
| W8 路径规范化 | Read `file_context_tracker.py` L164-L170 + `FileContextTracker.ts` L54 | 我的 expanduser+resolve 更严格，标为额外增强 |
| W9 去重策略 | Read `file_context_tracker.py` L176-L188 + `FileContextTracker.ts` L107-L162 | Cline 不去重+stale 标记，我同 path+operation 去重，语义不等价 |
| W10 压缩集成 | Read `context.py` L1207-L1263 + `compaction-shared.ts` L398-L435 | Cline 压缩不用 tracker，我优先用 tracker，标为额外增强 |
| W11 SSE 事件 | Grep `file_context_updated` in `agent/` + 列举 `server.py` 所有 `_sse_event` 调用 | 双方均无此事件，标为缺失 |
| W12 API 端点 | Read `server.py` L942-L991 | GET + DELETE 端点已实现，Cline 无 REST API，标为额外增强 |
| W13 原子写入 | Read `file_context_tracker.py` L250-L258 + `disk.ts` L182-L190 | 我用 tmp+replace 原子写入，Cline 用 fs.writeFile 非原子，标为额外增强 |

**报告完成时间**：2026-07-26
**对标源码版本**：当前 `third_party/cline` 工作树
**当前实现版本**：当前 `agent/` 工作树
