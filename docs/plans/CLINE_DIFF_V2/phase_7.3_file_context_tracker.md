# Phase 7.3 FileContextTracker 文件上下文追踪对比报告

## 1. 执行摘要

Cline 与 Charles 在 FileContextTracker（文件上下文追踪）机制上存在**"同名为不同语义"**的根本性设计差异：双方都实现了名为 `FileContextTracker` 的类，但承担的角色完全不同。

- **Cline**：`FileContextTracker.ts`（279 行）设计目标是**过期检测（stale detection）**——通过 chokidar 文件 watcher 监听工作区文件外部修改，区分"Cline 自身编辑"与"用户外部编辑"，避免 diff 编辑时上下文过期。持久化与 `model_usage` / `environment_history` 共享同一 `api.json`（按 taskId 隔离），保留完整时间序列（旧 entry 标 `stale`，新 entry 标 `active`）。配套 9 个单元测试覆盖 read/edit/mention/stale/watcher/dispose 等场景。
- **Charles**：`agent/file_context_tracker.py`（464 行）设计目标是**活动日志（activity logging）**——通过 `after_tool` hook 自动从工具调用提取路径并记录，用于压缩摘要和前端审计。无文件 watcher（服务端 agent 是唯一编辑者），同 path+operation 去重保留首次记录。额外提供 `_TrackerRegistry` 全局注册表、`get_state()`/`get_entries()` 查询 API、原子写入（tmp + replace）、SSE `file_context_updated` 事件推送、`GET/DELETE /sessions/{id}/file_context` REST 端点等 Cline 不存在的增强。

**任务要求的三个关注点结论**：
1. **已读取文件记录**：双方均支持。Cline 用 `record_source="read_tool"` + `cline_read_date` 时间戳记录；Charles 用 `operation="read"` + `tool_name` + `iteration` 记录。Charles 额外记录触发工具名和迭代轮次（Cline 不记录）。
2. **文件变更追踪**：**Cline 强、Charles 弱**。Cline 通过 chokidar watcher 追踪"用户在 Cline 外部修改文件"（`user_edited`），并区分 `cline_edited`；Charles 无 watcher，仅追踪工具触发的操作，无法感知外部修改。但 Charles 服务端场景下 agent 是唯一编辑者，无外部修改场景。
3. **文件重复读取检测**：**Cline 强、Charles 弱**。Cline 不去重，每次读取都新增 entry（旧 entry 标 stale），可还原"该文件被读了几次"完整时间序列；Charles 同 path+operation 去重保留首次记录，无法回答"读取次数"，但 JSON 体积更小、前端展示更清晰。

nanobot 残留检查结论：在 P7.3 对比范围内（`file_context_tracker.py` / `runtime.py` 的 tracker hook / `context.py` 的 `_summarize_tool_activity_v2` / `server.py` 的 file_context 端点）**未发现任何 nanobot 残留**（含注释与实现逻辑）。`agent/file_context_tracker.py` 全文 `grep nanobot` 无匹配，是纯 Cline 对标实现。`agent/context.py` L275 有一处 nanobot 注释残留，但属于 `SystemPromptBuilder.extra_sections` 参数的废弃说明，与文件上下文追踪无关。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P7.3 章节定义的 4 个对比项 + 任务要求的 3 个细分关注点展开：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 7.3.1 | FileContextTracker 类结构 | `FileContextTracker.ts` L24-279 — 含 file watcher + stale 检测 + pending warning，10 个方法 | `file_context_tracker.py` L134-356 — 仅 record + query + persist，7 个方法 | Charles 缺失 watcher/stale/pending warning 系列；新增 registry/查询 API | 弱对齐 |
| 7.3.2 | 持久化文件状态 | `disk.ts::saveTaskMetadata` 写入 `<taskDir>/api.json`，与 `model_usage`/`environment_history` 混存；`FileMetadataEntry` 含 `record_state`/`record_source`/`cline_read_date`/`cline_edit_date`/`user_edit_date` 五字段 | `file_context_tracker.py::save` L286-313 写入 `agent_data/file_context/<session_id>.json`，独立文件；`FileContextEntry` 含 `path`/`operation`/`timestamp`/`tool_name`/`iteration`/`source` 六字段 | Cline 多 section 共享 + 完整时间序列（stale 标记）；Charles 独立文件 + 去重快照 | 弱对齐 |
| 7.3.3 | 压缩摘要质量 | `compaction-shared.ts::extractFileOps`/`summarizeToolActivity` **不使用 tracker**，直接扫消息提取文件操作 | `context.py::_summarize_tool_activity_v2` L2060-2115 **优先用 tracker**（跨压缩周期保留），fallback 扫消息 | Cline 压缩路径与 tracker 解耦；Charles 压缩路径与 tracker 耦合，跨压缩周期更准确 | Charles 增强 |
| 7.3.4 | UI 文件状态 | VSCode 扩展内部通过 `taskMetadata.files_in_context` 直接访问（无 REST API） | `server.py` L1088-1137 提供 `GET /sessions/{id}/file_context` + `DELETE /sessions/{id}/file_context`；runtime.py L1229-1234 推送 `file_context_updated` SSE 事件 | Cline 仅扩展内部访问；Charles 提供完整 REST API + SSE 实时推送 | Charles 增强 |
| 7.3.5 | 已读取文件记录（细分） | `record_source="read_tool"` + `cline_read_date: number` 时间戳；不记录工具名 | `operation="read"` + `timestamp`（ISO 字符串）+ `tool_name` + `iteration` | Charles 额外记录触发工具名和迭代轮次，便于审计；Cline 仅记录时间戳 | 弱对齐（Charles 多审计字段） |
| 7.3.6 | 文件变更追踪（细分） | `setupFileWatcher` chokidar 监听外部修改 → `user_edited`；`markFileAsEditedByCline` 区分 Cline 自身编辑；`detectFilesEditedAfterMessage` 检测 checkpoint 恢复冲突 | **无文件 watcher**；`_file_context_tracker_hook` 仅追踪工具触发的 `read`/`edited`/`created`/`deleted` | Charles 无法感知外部修改（服务端场景无此需求）；无 checkpoint 恢复冲突检测 | 缺失（设计目标不同） |
| 7.3.7 | 文件重复读取检测（细分） | 不去重，每次读取新增 entry（旧 entry 标 `stale`，新 entry 标 `active`），保留完整时间序列 | 同 path+operation 去重，仅保留首次记录（`file_context_tracker.py` L222-224） | Cline 可回答"该文件被读了几次"；Charles 无法回答，但 JSON 体积更小 | 语义不等价 |

## 3. 重点差距详细说明

### 差距 1：设计目标根本不同——stale detection vs activity logging（对应对比项 7.3.1 / 7.3.6 / 7.3.7）

**Cline 设计**（`FileContextTracker.ts` L10-23 docstring 明确说明）：

> "This class is responsible for tracking file operations that may result in stale context. If a user modifies a file outside of Cline, the context may become stale and need to be updated."

核心机制：
1. `setupFileWatcher(filePath)` L41-78：用 chokidar 监听文件，`awaitWriteFinish` 100ms 稳定阈值
2. `watcher.on("change")` L67-74：若 `recentlyEditedByCline.has(filePath)` 则视为 Cline 自身编辑（删除标记，不上报）；否则加入 `recentlyModifiedFiles` 并记 `user_edited`
3. `addFileToFileContextTracker` L107-162：新增 entry 标 `active`，同 path 的旧 entry 标 `stale`（L113-117），保留完整时间序列
4. `detectFilesEditedAfterMessage` L193-230：checkpoint 恢复时检测哪些文件在 messageTs 之后被编辑
5. `storePendingFileContextWarning` / `retrievePendingFileContextWarning` / `retrieveAndClearPendingFileContextWarning` L235-278：跨任务重初始化持久化警告（用 `pendingFileContextWarning_${taskId}` 动态 key 存 workspace state）

**Charles 设计**（`file_context_tracker.py` L36-59 docstring 明确说明）：

> "本实现与 Cline FileContextTracker 的设计目标不同: Cline 聚焦'过期检测'（stale detection）...本仓库: 聚焦'活动日志'（activity logging），记录工具读写文件清单，用于压缩摘要和前端审计"

核心机制：
1. `record(path, operation, tool_name, iteration, timestamp)` L173-236：after_tool hook 调用，按工具名提取路径
2. 同 path+operation 去重（L222-224）：`for entry in self._entries: if entry.path == path_str and entry.operation == operation: return`
3. **无 chokidar / 无 watcher / 无 `recentlyModifiedFiles` / 无 `recentlyEditedByCline` / 无 `detectFilesEditedAfterMessage` / 无 pending warning 系列**

**影响**：
- Charles 无法感知"用户在 agent 外部修改文件"——但服务端量化 agent 场景下 agent 是唯一编辑者，无此需求，stale detection 系列功能可缺失
- Charles 无法回答"该文件被读了几次"——压缩摘要场景只需"哪些文件被读/改过"，无需时间序列，去重策略更合适
- Charles 无 checkpoint 恢复冲突检测——当前本仓库无 checkpoint 恢复机制，可暂不实现

### 差距 2：操作类型枚举语义不等价（对应对比项 7.3.1）

**Cline**（`ContextTrackerTypes.ts` L5）按"谁触发编辑"分类：
```typescript
record_source: "read_tool" | "user_edited" | "cline_edited" | "file_mentioned"
```
- `read_tool`：Cline 通过工具读取
- `user_edited`：用户在 Cline 外部编辑（chokidar 检测）
- `cline_edited`：Cline 自身编辑
- `file_mentioned`：用户在 prompt 中 @mention 文件（`mentions/index.ts` L190/225/253 调用 `trackFileContext(mentionPath, "file_mentioned")`）

**Charles**（`file_context_tracker.py` L90-93）按"什么操作"分类：
```python
OP_READ = "read"          # 读取（read_files / list_files 等）— 对标 Cline read_tool
OP_EDITED = "edited"      # 编辑已存在文件 — 对标 Cline cline_edited
OP_CREATED = "created"    # 创建新文件 — Cline 归为 cline_edited
OP_DELETED = "deleted"    # 删除文件 — Cline 无此概念
```

**语义映射**：
| Charles operation | Cline record_source | 说明 |
|------------------|--------------------|------|
| `read` | `read_tool` | 一致 |
| `edited` | `cline_edited` | Charles 合并了 Cline 的 `user_edited` + `cline_edited`（无 watcher 无法区分） |
| `created` | `cline_edited` | Cline 将新建文件归为 `cline_edited`；Charles 单独分类 |
| `deleted` | （无） | Charles 预留给未来 `file_delete` 工具；Cline 无此概念 |
| （无） | `user_edited` | Charles 无 watcher，不追踪外部编辑 |
| （无） | `file_mentioned` | Charles 不追踪 prompt 中提到的文件 |

**影响**：Charles 不追踪 `file_mentioned`——用户在 prompt 中 @mention 的文件不会被记录到 tracker。Cline 通过 `mentions/index.ts` 解析 @mention 并调用 `trackFileContext(mentionPath, "file_mentioned")`，使这些文件进入 `files_in_context`。Charles 当前无 @mention 解析机制，prompt 中提到的文件不进入 tracker。

### 差距 3：持久化格式与隔离策略不同（对应对比项 7.3.2）

**Cline**：`getTaskMetadata(taskId)` / `saveTaskMetadata(taskId, metadata)` 读写 `<taskDir>/api.json`，该文件包含三个 section：
```typescript
interface TaskMetadata {
    files_in_context: FileMetadataEntry[]
    model_usage: ModelMetadataEntry[]
    environment_history: EnvironmentMetadataEntry[]
}
```
- 优势：单文件聚合 task 全部 metadata，便于整体迁移
- 劣势：`disk.ts` L182-190 用 `fs.writeFile` 直接覆盖（非原子），并发写入有风险

**Charles**：`save()` L286-313 写入 `agent_data/file_context/<session_id>.json`，独立文件：
```json
{
    "session_id": "abc123",
    "entries": [{path, operation, timestamp, tool_name, iteration, source}, ...],
    "updated_at": "2026-07-25T10:30:00+00:00"
}
```
- 优势：原子写入（`tmp_path.write_text` + `tmp_path.replace` L301-306），并发安全；独立文件不与 model_usage 等混存
- 劣势：与 Cline 的 `TaskMetadata` 多 section 聚合不同，跨 section 关联查询需多文件 join

### 差距 4：压缩路径与 tracker 的耦合点不同（对应对比项 7.3.3）

**Cline**：`basic-compaction.ts` 与 `agentic-compaction.ts` 通过 `extractFileOps(messages)` 从消息中扫描文件操作，**不依赖 FileContextTracker**。Cline 的 FileContextTracker 仅用于 UI 展示和 stale detection，与压缩路径解耦。

**Charles**：`context.py::_summarize_tool_activity_v2` L2082-2108 优先从 tracker 取文件列表：
```python
if session_id:
    tracker = get_tracker(session_id)
    state = tracker.get_state()
    edited = state.get("edited", []) + state.get("created", [])  # created 归入 edited
    read_files = state.get("read", [])
    if read_files or edited:
        return {"readFiles": read_files, "editedFiles": edited, "commands": commands}
# fallback: 用消息扫描结果
return from_messages
```

**影响**：Charles 的 tracker 跨压缩周期保留文件状态——即使消息被压缩丢弃，tracker 仍记录"该文件曾被读/改过"，压缩摘要更准确。Cline 每次压缩都从当前消息重新扫描，若文件操作消息已被压缩丢弃，则该文件不会出现在摘要中。这是 Charles 的有意增强。

### 差距 5：Charles 缺失的 Cline 功能清单（对应对比项 7.3.4）

Charles 未实现的 Cline FileContextTracker 方法（共 6 个）：

| Cline 方法 | 用途 | Charles 是否需要 |
|-----------|------|----------------|
| `setupFileWatcher` | chokidar 监听文件外部修改 | 不需要（服务端无外部编辑） |
| `markFileAsEditedByCline` | 标记 Cline 编辑避免误报 | 不需要（无 watcher 无需区分） |
| `detectFilesEditedAfterMessage` | checkpoint 恢复时检测冲突 | 暂不需要（无 checkpoint 恢复） |
| `storePendingFileContextWarning` | 跨任务重初始化持久化警告 | 暂不需要（无 checkpoint 恢复） |
| `retrievePendingFileContextWarning` | 读取持久化警告 | 暂不需要 |
| `retrieveAndClearPendingFileContextWarning` | 读取并清除持久化警告 | 暂不需要 |

### 差距 6：Charles 额外增强的 Cline 不存在功能（对应对比项 7.3.4）

Charles 新增的 Cline FileContextTracker 不存在的方法/机制（共 7 项）：

| Charles 增强 | 位置 | 说明 |
|-------------|------|------|
| `get_state()` | L242-261 | 返回 `{read, edited, created, deleted}` 精简视图，Cline 无等价方法 |
| `get_entries()` | L263-271 | 返回完整记录列表含 timestamp/tool_name/iteration，Cline 通过 `files_in_context` 数组获取但无独立 API |
| `get_files_all()` | L273-280 | 合并所有操作类型去重返回，Cline 无等价方法 |
| `_TrackerRegistry` | L363-417 | 全局按 session_id 缓存实例，AgentRuntime 和 server.py 共享同一实例；Cline 每次 `new FileContextTracker(controller, taskId)` |
| 原子写入 | L299-307 | `tmp_path.write_text` + `tmp_path.replace`；Cline `disk.ts` 用 `fs.writeFile` 非原子 |
| SSE `file_context_updated` 事件 | `runtime.py` L1229-1234 | after_tool hook 后推送实时事件，前端无需轮询；Cline 无 SSE 事件 |
| REST API `GET/DELETE /sessions/{id}/file_context` | `server.py` L1088-1137 | 前端通过 HTTP 访问；Cline 仅 VSCode 扩展内部访问 workspace state |

## 4. nanobot 残留检查

### 检查范围

在 P7.3 对比范围内的 4 个文件中检查 nanobot 残留：
- `agent/file_context_tracker.py`（464 行，FileContextTracker 主体）
- `agent/runtime.py` 的 `_file_context_tracker_hook`（L1116-1241）+ 初始化（L282-289）
- `agent/context.py` 的 `_summarize_tool_activity_v2`（L2060-2115）
- `agent/server.py` 的 file_context 端点（L1088-1137）

### 注释残留分类

#### P7.3 范围内：无残留

`agent/file_context_tracker.py` 全文 `grep nanobot` **零匹配**，docstring 与注释均对标 Cline `FileContextTracker.ts` / `ContextTrackerTypes.ts`，无 nanobot 风格代码或注释。

`agent/runtime.py` 的 `_file_context_tracker_hook`（L1116-1241）与初始化（L282-289）注释均为 Phase 29.3 / Stage 6.7 / Stage 6.8 标注，无 nanobot 残留。

`agent/context.py` 的 `_summarize_tool_activity_v2`（L2060-2115）注释为 Phase 29.3 标注，无 nanobot 残留。

`agent/server.py` 的 file_context 端点（L1088-1137）注释为 Phase 29.3 标注，无 nanobot 残留。

#### P7.3 范围外（仅供记录，不属于本阶段处理）

`agent/context.py` L275 有一处 nanobot 注释残留：
```
extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                保留参数签名仅为向后兼容，当前无调用方传入。
```
**性质**：属于 `SystemPromptBuilder.__init__` 的 `extra_sections` 参数废弃说明，与文件上下文追踪无关，属于 Phase 5（SystemPromptBuilder）范畴。已在 phase_2.12 报告中记录。

### 实现逻辑残留检查结论

**未发现任何实现逻辑残留**。P7.3 范围内的全部代码均基于 Cline 对标设计或 Charles 有意增强：

- `agent/file_context_tracker.py`：纯 Cline 对标 + Charles 增强（registry/查询 API/原子写入），无 nanobot 代码
- `agent/runtime.py::_file_context_tracker_hook`：after_tool hook 自动提取路径，无 nanobot 代码
- `agent/context.py::_summarize_tool_activity_v2`：tracker 优先 + 消息 fallback，无 nanobot 代码
- `agent/server.py` 的 file_context 端点：FastAPI 路由，无 nanobot 代码

### 残留风险评估

| 残留类型 | 文件数 | 风险等级 | 处理建议 |
|---------|--------|---------|---------|
| 注释残留（P7.3 范围内） | 0 | 无 | 无需处理 |
| 注释残留（P7.3 范围外，context.py L275） | 1 | 低 | 属于 Phase 5 范畴，可在下个版本删除废弃参数 `extra_sections` |
| 实现逻辑残留 | 0 | 无 | 无需处理 |

## 5. 修复建议

### P0（高优先级，影响正确性）

无。Charles 的 FileContextTracker 实现功能完整且符合服务端场景需求：
- 已读取文件记录、文件变更追踪（工具触发）、文件去重策略均已实现
- stale detection 系列功能缺失是**有意的场景适配**（服务端无外部编辑），不是 bug
- 压缩路径与 tracker 耦合是**有意的增强**（跨压缩周期保留文件状态），不是 bug

### P1（中优先级，影响一致性）

**建议 1：补充 `file_mentioned` 追踪（若未来引入 @mention 解析）**

参考 Cline `mentions/index.ts` L190/225/253，在 Charles 的 prompt 解析层（若未来实现 @mention）调用 `tracker.record(path, OP_READ, tool_name="mention", ...)` 或新增 `OP_MENTIONED` 操作类型。

**收益**：使 tracker 能记录"用户在 prompt 中提到的文件"，与 Cline `file_mentioned` 对齐。

**改动范围**：
- `file_context_tracker.py`：新增 `OP_MENTIONED = "mentioned"` 常量，加入 `VALID_OPERATIONS`
- prompt 解析层（未来实现）：解析 @mention 后调用 `tracker.record`

**注意**：当前 Charles 无 @mention 解析机制，此建议为前瞻性规划，不急于实施。

### P2（低优先级，改善可观测性）

**建议 2：在 `get_state()` 中暴露去重前的原始记录数**

当前 `get_state()` 返回去重后的文件列表，无法知道"该文件被读了 5 次"。可在 `get_state()` 返回值中新增 `raw_count` 字段：
```python
{
    "read": [path1, path2],
    "edited": [path3],
    "created": [],
    "deleted": [],
    "raw_count": {"read": 7, "edited": 3, "created": 0, "deleted": 0}  # 去重前的总操作次数
}
```

**收益**：前端可展示"该文件被读取 7 次"的统计信息，弥补去重策略丢失的时间序列信息。

**改动范围**：`file_context_tracker.py::get_state()` L242-261，新增 `raw_count` 统计。

**注意**：由于 Charles 采用去重策略，`raw_count` 只能反映"去重前的 entry 数"，而非"完整时间序列的操作次数"（因为同 path+operation 在去重阶段就被跳过，未进入 `_entries`）。若需完整时间序列，需参考 Cline 的 stale 标记策略改造。

### P3（可选，工具补齐）

**建议 3：补充单元测试覆盖**

参考 Cline `FileContextTracker.test.ts` 的 9 个测试用例，为 Charles `file_context_tracker.py` 补充等价测试：
1. `test_record_read_tool` — 对标 Cline "should add a record when a file is read by a tool"
2. `test_record_edited` — 对标 "should add a record when a file is edited by Cline"
3. `test_record_created` — Charles 独有（Cline 归为 cline_edited）
4. `test_dedup_same_path_operation` — Charles 独有（Cline 不去重）
5. `test_get_state` — Charles 独有（Cline 无 get_state）
6. `test_get_entries` — Charles 独有
7. `test_save_load_roundtrip` — 对标持久化
8. `test_clear` — Charles 独有
9. `test_registry_cache` — Charles 独有（_TrackerRegistry）

**收益**：确保 FileContextTracker 的去重、持久化、registry 缓存等核心逻辑有测试覆盖。

**改动范围**：新增 `tests/test_file_context_tracker.py`（当前 `tests/test_stage6_persistence.py` 已有部分覆盖，可扩展）。

## 6. 验证方法建议

### 验证方法 1：已读取文件记录对比

构造场景：依次调用 `read_files` 工具读取 `/path/a.py` 和 `/path/b.py`。

分别检查 Cline `taskMetadata.files_in_context` 与 Charles `tracker.get_state()["read"]`：

**预期**：
- Cline：`files_in_context` 含 2 条 `record_source="read_tool"` 的 active entry，`cline_read_date` 为时间戳
- Charles：`get_state()["read"]` 返回 `["/path/a.py", "/path/b.py"]`，`get_entries()` 含 2 条记录，每条含 `tool_name="read_files"` 和 `iteration`

### 验证方法 2：文件重复读取检测对比

构造场景：连续两次调用 `read_files` 读取同一文件 `/path/a.py`。

分别检查两侧的记录数：

**预期**：
- Cline：`files_in_context` 含 2 条 `/path/a.py` entry，第 1 条 `record_state="stale"`，第 2 条 `record_state="active"`，可还原"读了 2 次"
- Charles：`_entries` 仅含 1 条 `/path/a.py` 的 `read` 记录（第 2 次被去重跳过），`get_state()["read"]` 返回 `["/path/a.py"]`，无法回答"读了 2 次"

### 验证方法 3：文件变更追踪对比（外部修改）

构造场景：agent 工具读取 `/path/a.py` 后，**外部进程修改该文件**。

**预期**：
- Cline：chokidar watcher 触发 `change` 事件，`recentlyModifiedFiles` 加入 `/path/a.py`，新增 `record_source="user_edited"` entry，`getAndClearRecentlyModifiedFiles()` 返回 `["/path/a.py"]`
- Charles：无 watcher，tracker 无任何变化；`get_state()` 仍只显示 `read` 操作，无 `user_edited` 记录

### 验证方法 4：压缩摘要质量对比（跨压缩周期）

构造场景：
1. 第 1 轮：调用 `read_files` 读取 `/path/a.py`，调用 `editor` 编辑 `/path/b.py`
2. 触发压缩，旧消息被摘要替换
3. 第 2 轮：再次触发压缩

检查第 2 次压缩时的文件列表来源：

**预期**：
- Cline：第 2 次压缩时 `extractFileOps(messages)` 从当前消息扫描，若第 1 轮的 tool_result 已被压缩丢弃，则 `/path/a.py` 和 `/path/b.py` 不会出现在摘要中
- Charles：第 2 次压缩时 `_summarize_tool_activity_v2` 优先从 tracker 取数，`get_state()` 返回 `{read: ["/path/a.py"], edited: ["/path/b.py"]}`，文件列表跨压缩周期保留

### 验证方法 5：持久化原子性对比

构造场景：并发调用 `save()`（多线程场景）。

**预期**：
- Cline：`disk.ts::saveTaskMetadata` 用 `fs.writeFile` 直接覆盖，并发写入可能丢失数据或写入损坏 JSON
- Charles：`save()` 用 `tmp_path.write_text` + `tmp_path.replace` 原子替换，并发写入安全（最后一次写入胜出，JSON 不会损坏）

### 验证方法 6：nanobot 残留扫描

执行 `grep -rn "nanobot" agent/file_context_tracker.py agent/runtime.py agent/context.py agent/server.py` 确认残留数量与类型。

**预期**：仅 `agent/context.py` L275 一处废弃标注（属于 Phase 5 范畴，与文件上下文追踪无关），P7.3 范围内零残留。
