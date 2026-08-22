# Phase S: 会话持久化与锁 对比报告

> 对标源码：
> - `sdk/packages/core/src/services/storage/sqlite-session-store.ts`
> - `sdk/packages/core/src/services/storage/session-store.ts`
> - `sdk/packages/core/src/session/services/file-session-service.ts`
> - `sdk/packages/core/src/session/services/persistence-service.ts`
> - `sdk/packages/core/src/session/stores/session-manifest-store.ts`
> - `sdk/packages/shared/src/db/sqlite-db.ts`（schema 定义）
> - `apps/vscode/src/core/locks/SqliteLockManager.ts`
> - `apps/vscode/src/services/mcp/settingsLock.ts`（文件锁参考实现）
> - `apps/vscode/src/core/storage/state-migrations.ts`
> - `apps/vscode/src/core/storage/disk.ts`
> - `apps/cli/src/session/export.ts` + `apps/cli/src/commands/history.ts`
>
> 当前实现：
> - `agent/session.py`（会话管理 + JSON 持久化）
> - `agent/file_lock.py`（跨进程文件锁）
> - `agent/state.py`（会话状态 todos/mode 持久化）
>
> 对比维度：S1-S14

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 3 项 |
| 弱对齐 | 6 项 |
| 缺失 | 3 项 |
| 额外增强 | 2 项 |
| **对齐度** | **约 64%（含额外增强覆盖度约 78%）** |

说明：
- S1（SQLite vs JSON）属于"合理特化"——量化单机场景下 JSON 文件更轻量、可读性更好，归入弱对齐而非缺失。
- S3/S4/S5 的文件锁机制逻辑上对标 Cline `settingsLock.ts`（同为目录锁），而非 `SqliteLockManager`（基于 SQLite 表）。两者均为跨进程互斥，等价性成立。

---

## 2. 详细对比表

| # | 对比项 | Cline 实现 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| S1 | 存储格式 | SQLite（`sessions.db`，WAL 模式） | session.py L57/L137（每会话一 JSON 文件） | 弱对齐（合理特化） |
| S2 | schema 结构 | 27 字段 sessions 表 + subagent_spawn_queue/schedules/schedule_executions | session.py L65-73（6 字段：session_id/created_at/last_active/title/messages + version） | 弱对齐 |
| S3 | 跨进程锁机制 | `SqliteLockManager`（locks 表）+ `settingsLock.ts`（目录锁） | file_lock.py L57-87（目录锁 mkdir+rename） | 弱对齐（逻辑等价于 settingsLock） |
| S4 | 锁超时 | settingsLock: STALE=10s；SqliteLockManager: STALE=60s；busy_timeout=5s | file_lock.py L50/L72（STALE_MS=10s；timeout_ms=10s） | 弱对齐（stale 与 settingsLock 一致） |
| S5 | 锁 stale 接管 | settingsLock.ts `reclaimStaleLock`（mtime 判断 + rename aside + rmSync） | file_lock.py L196-226（`_is_stale` + `_takeover_stale`，mtime + rename aside + _rmtree） | 完全一致 |
| S6 | state-migrations 版本迁移 | state-migrations.ts（6 个迁移函数）+ sqlite-db.ts `LEGACY_MIGRATIONS`（9 个 ALTER TABLE） | session.py L54/L238-239（仅版本号校验，不兼容跳过） | 缺失 |
| S7 | session-export 导出 | apps/cli/src/session/export.ts（生成自包含 HTML，含工具块/diff/统计/导航） | 无 | 缺失 |
| S8 | session 列表查询 | SqliteSessionStore.list(): SQL `ORDER BY started_at DESC LIMIT ?`；FileAdapter: 读单个 index.json | session.py L199-215（glob 扫目录）+ L325-339（内存索引缓存） | 弱对齐 |
| S9 | session 元信息 | SessionRecord（started_at/ended_at/updated_at/prompt/metadata_json 等） | session.py L65-73（created_at/last_active/message_count/title） | 弱对齐 |
| S10 | 消息增量保存 | session-manifest-store.ts L157-175（全量 writeFileSync）+ file-session-service atomicWriteJson | session.py L157-188（全量 `_atomic_write_json`） | 完全一致（均为全量覆写） |
| S11 | 并发写安全 | SQLite: WAL + busy_timeout；FileAdapter: 仅 atomicWriteJson，无文件锁 | session.py L182-186 + state.py L205-208（FileLock 保护读写） | 额外增强（多进程安全更强） |
| S12 | 数据迁移 | sqlite-db.ts `LEGACY_MIGRATIONS`（ALTER TABLE + 数据回填，如 `UPDATE sessions SET workspace_root = cwd`） | 无（版本不兼容直接跳过） | 缺失 |
| S13 | 备份机制 | 无显式备份（仅 atomicWriteJson/tmp+rename） | 无显式备份（仅 `_atomic_write_json`/tmp+rename） | 完全一致（均无） |
| S14 | session 索引内存缓存 | 无（每次 list() 均查 DB 或读 index 文件） | session.py L122-127/L325-339（`_sorted_index` + `_index_dirty` 缓存） | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #S2：schema 字段缺失较多

**严重度**：P2（量化单 agent 场景下大部分字段非必需）

**Cline 实现**：`sqlite-db.ts` L184-214 定义 sessions 表，含 27 个字段：
- 进程信息：`pid`、`source`、`interactive`
- 运行时信息：`provider`、`model`、`cwd`、`workspace_root`
- 生命周期：`started_at`、`ended_at`、`exit_code`、`status`、`status_lock`
- 团队/子代理：`team_name`、`enable_tools`、`enable_spawn`、`enable_teams`、`parent_session_id`、`parent_agent_id`、`agent_id`、`conversation_id`、`is_subagent`
- 元信息：`prompt`、`metadata_json`、`transcript_path`、`hook_path`、`messages_path`、`updated_at`

另有 3 张辅助表：`subagent_spawn_queue`、`schedules`、`schedule_executions`。

**我的实现**：`session.py` L65-73 `SessionInfo` 仅 5 个业务字段（`session_id`、`created_at`、`last_active`、`message_count`、`title`），加 `version` 共 6 个字段。无进程/运行时/团队/子代理相关字段。

**影响**：
- 无法持久化 provider/model 等运行时上下文，重启后会话恢复不完整（无法知道某会话用哪个模型）
- 不支持子代理（subagent）会话关联，无 `parent_session_id` 链
- 无 `status`/`exit_code`/`ended_at`，无法区分"运行中/已结束/失败"的会话
- 量化场景为单 agent、单进程，团队/子代理字段非必需，但 `status` 和 `provider/model` 缺失影响较大

**修复建议**：
1. 在 `SessionInfo` 中增加 `status`、`provider`、`model`、`ended_at`、`exit_code` 字段
2. 可选增加 `parent_session_id` 以支持未来子代理
3. 不需要复刻全部 27 字段，保留量化场景所需子集即可

**优先级**：P2

---

### 差距 #S6：state-migrations 版本迁移缺失

**严重度**：P1（schema 升级时会导致数据丢失）

**Cline 实现**：
- `state-migrations.ts` 提供 6 个迁移函数：
  - `migrateWorkspaceToGlobalStorage`：将 workspace storage 的 key 迁移到 global storage
  - `migrateTaskHistoryToFile`：任务历史迁移（TODO 占位）
  - `migrateCustomInstructionsToGlobalRules`：customInstructions → `.clinerules` 文件
  - `migrateWelcomeViewCompleted`：根据已有 API key 推导 welcomeViewCompleted
  - `cleanupMcpMarketplaceCatalogFromGlobalState`：清理废弃 key
  - `cleanupOldApiKey`：清理旧版 clineApiKey
- `sqlite-db.ts` L272-337 `LEGACY_MIGRATIONS` 数组：9 个 `ALTER TABLE` 语句为旧表添加新列（如 `workspace_root`、`parent_session_id`、`metadata_json` 等），并对 `workspace_root` 做数据回填（`UPDATE sessions SET workspace_root = cwd WHERE workspace_root IS NULL`）
- `ensureSessionSchema` L348-381 在每次打开 DB 时自动检测列是否存在并执行迁移

**我的实现**：`session.py` L238-239 仅做版本号校验：
```python
if data.get("version") != _SESSION_FILE_VERSION:
    logger.warning(f"会话文件 {path} 版本不兼容，跳过")
    return False
```
`state.py` L234-236 同样仅校验版本。无任何迁移逻辑，版本不匹配直接丢弃旧数据。

**影响**：
- 升级 `_SESSION_FILE_VERSION` 或 `_STATE_FILE_VERSION` 后，所有历史会话/状态文件将无法加载，用户历史对话全部丢失
- 无法平滑演进 schema（每次加字段都得重写迁移或接受数据丢失）
- 量化场景下历史会话（研报、分析记录）丢失影响较大

**修复建议**：实现版本迁移注册表模式：
```python
_SESSION_MIGRATIONS = {
    1: _migrate_v1_to_v2,  # 例如 v1→v2 增加 status 字段
    2: _migrate_v2_to_v3,
}

def _load_session_from_file(self, session_id, path):
    data = json.load(f)
    version = data.get("version", 1)
    while version < _SESSION_FILE_VERSION:
        migrator = _SESSION_MIGRATIONS.get(version)
        if not migrator:
            return False  # 无迁移路径
        data = migrator(data)
        version = data["version"]
    # 后续正常加载
```

**优先级**：P1

---

### 差距 #S7：session-export 导出缺失

**严重度**：P3（量化场景非核心，但用户分享研报对话时有用）

**Cline 实现**：
- `apps/cli/src/session/export.ts`：`generateConversationHTML` 生成自包含 HTML 文件，包含：
  - 消息渲染（user/assistant 头像、角色标签、模型信息）
  - 工具调用块渲染（tool_use + tool_result 配对展示）
  - diff 渲染（edit/write 工具的 old_string/new_string 行级 diff，红绿高亮）
  - 命令块渲染（run_commands 工具）
  - 文件列表渲染（read_files 工具）
  - 统计信息（消息数、总成本、token 数、更新时间）
  - 右侧导航点（dots-nav，按消息位置滚动定位）
- `apps/cli/src/commands/history.ts` L25-39 `exportHistorySession`：CLI 入口，`history export --session-id <id> [--output <path>]`
- `exportSessionAsHTML`：浏览器环境下载（Blob + URL.createObjectURL）

**我的实现**：无任何导出功能。会话仅以 JSON 形式存储在 `agent_data/sessions/`。

**影响**：
- 无法将量化分析对话导出为可分享/可归档的格式
- 用户若需保存研报生成过程记录，需手动复制 JSON

**修复建议**：可选实现简化版 HTML 导出：
1. 复用 `_message_to_dict` 序列化结果
2. 渲染基本消息列表（无需 diff/工具块等复杂渲染）
3. 提供命令行入口或 API 端点

**优先级**：P3

---

### 差距 #S8：list 查询性能差异

**严重度**：P2（大量会话时启动性能）

**Cline 实现**：
- `SqliteSessionStore.list(limit=200)`：SQL `SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT ?`，走 DB 索引，O(log n) + 索引扫描，毫秒级
- `FileSessionPersistenceAdapter.listSessions()`：读单个 `sessions.index.json` 文件，`Object.values` + `sort` + `slice`，单文件读取 + 内存排序

**我的实现**：
- `load_all()` L199-215：启动时 `glob("*.json")` 扫描整个目录，逐个打开解析，O(n) 文件 IO
- `list_sessions()` L325-339：运行时使用 `_sorted_index` 内存缓存，仅 `_index_dirty=True` 时重新排序

**影响**：
- 启动时性能：我有 N 个会话需打开 N 个文件 + N 次 JSON 解析；Cline SQLite 仅一次 DB 打开；Cline FileAdapter 仅读 1 个 index 文件。会话数多时（如 100+），我的启动明显较慢
- 运行时性能：我的内存缓存反而比 Cline 更优（Cline 每次 list 都查 DB 或读文件，我直接返回缓存）

**修复建议**：增加单独的 `sessions.index.json` 索引文件，启动时仅读索引：
```python
def _load_index(self):
    index_path = self._persist_dir / "sessions.index.json"
    if index_path.exists():
        # 仅读索引恢复 SessionInfo 列表，不加载 messages
        ...
    else:
        # 回退到 glob 扫描
        self.load_all()
```

**优先级**：P2

---

### 差距 #S9：session 元信息不完整

**严重度**：P2（影响会话恢复完整度）

**Cline 实现**：`SessionRecord`（sqlite-session-store.ts L83-122）持久化以下元信息：
- 时间：`started_at`、`ended_at`、`updated_at`
- 状态：`status`（running/completed/failed/...）、`status_lock`（乐观锁）、`exit_code`
- 运行时：`provider`、`model`、`cwd`、`workspace_root`
- 进程：`pid`、`source`、`interactive`
- 团队：`team_name`、`enable_tools/spawn/teams`
- 子代理：`parent_session_id`、`parent_agent_id`、`agent_id`、`conversation_id`、`is_subagent`
- 内容：`prompt`、`metadata_json`、`transcript_path`、`hook_path`、`messages_path`

**我的实现**：`SessionInfo`（session.py L65-73）仅 5 字段：
- `session_id`、`created_at`、`last_active`、`message_count`、`title`

**影响**：
- 无 `status`：无法区分活跃/已结束/失败的会话，前端无法做状态过滤
- 无 `provider`/`model`：重启后无法恢复"上次用什么模型"
- 无 `ended_at`/`exit_code`：无会话结束记录
- `title` 自动从首条用户消息提取（L490-499，前 50 字符），Cline 的 title 来自 `SessionHistoryMetadata`（更灵活，可由用户/系统设置）

**修复建议**：与 S2 合并修复，扩展 `SessionInfo` 字段。

**优先级**：P2

---

### 差距 #S12：数据迁移缺失

**严重度**：P1（与 S6 相关但侧重点不同）

**Cline 实现**：
- `sqlite-db.ts` L272-337 `LEGACY_MIGRATIONS`：为旧版 DB 添加新列（`ALTER TABLE sessions ADD COLUMN ...`），并对特定列做数据回填（如 `workspace_root` 从 `cwd` 复制）
- `state-migrations.ts`：跨存储位置迁移（workspace→global）、格式迁移（customInstructions→rules 文件）、废弃数据清理

**我的实现**：无任何数据迁移逻辑。`session.py` L238-239 版本不匹配直接跳过；`state.py` L234-236 同样跳过。

**影响**：
- 升级版本后旧会话文件无法加载，历史对话丢失
- 无法在不动数据的前提下演进 schema
- 量化场景下研报/分析历史有归档价值，丢失影响较大

**修复建议**：与 S6 合并，实现版本迁移注册表（详见 S6 修复建议）。

**优先级**：P1

---

### 差距 #S4：锁超时语义不完全等价

**严重度**：P3（边界场景）

**Cline 实现**：
- `settingsLock.ts` L17-18：`STALE_MS=10_000`，`POLL_MS=25`；等待锁释放通过 `await delay(POLL_MS)` 异步轮询，支持 `AbortSignal` 取消（L151-155 `checkAbort`）
- `SqliteLockManager.ts` L11：`STALE_LOCK_TIMEOUT=60_000`（1 分钟，针对 DB 初始化锁文件）
- SQLite `busy_timeout=5000`（sqlite-db.ts L353）

**我的实现**：
- `file_lock.py` L50-54：`STALE_MS=10_000`，`POLL_MS=25`（与 settingsLock 完全一致）
- `file_lock.py` L72/L117-120：`timeout_ms=10_000` 默认获取超时，超时抛 `TimeoutError`；不支持 `AbortSignal`

**影响**：
- stale 检测阈值与 Cline settingsLock 完全一致（10s）
- 我的 `timeout_ms` 是获取锁的硬超时，超时即抛异常；Cline 用 `AbortSignal` 实现可取消的等待，语义上更灵活（调用方可主动取消而非等死）
- 默认 10s 超时在锁竞争激烈时可能过早失败

**修复建议**：
1. 可选支持 `abort_event: threading.Event` 参数实现可取消等待
2. 当前默认超时 10s 可接受，保持现状

**优先级**：P3

---

## 4. 额外增强项

### 增强 #S11：并发写安全（FileLock 保护）

**我**：`session.py` L182-186 和 `state.py` L205-208 在所有 JSON 读写操作外包裹 `FileLock`，防止多进程并发写同一会话文件导致数据丢失。

**Cline**：
- `SqliteSessionStore`：依赖 SQLite WAL 模式 + `busy_timeout` 提供并发安全
- `FileSessionPersistenceAdapter`（file-session-service.ts L86-88）：仅用 `atomicWriteJson`（tmp+rename），**无文件锁**，依赖单进程假设

**评估**：
- 量化系统存在多进程场景（web 服务进程 + 定时调度进程同时操作会话），我的 FileLock 保护是必要的
- 相比 Cline 的 FileSessionPersistenceAdapter，我的并发安全更强
- 与 Cline SqliteSessionStore 的 SQLite 内置并发控制逻辑等价
- **合理增强，保留**

### 增强 #S14：session 索引内存缓存

**我**：`session.py` L122-127 引入 `_sorted_index` + `_index_dirty` 缓存：
- `update()`/`clear()`/`load_all()` 时标记 `_index_dirty=True`
- `list_sessions()` 仅在 dirty 时重新排序（O(n log n)），否则直接返回缓存副本（O(n)）

**Cline**：
- `SqliteSessionStore.list()`：每次调用都执行 SQL 查询
- `FileSessionPersistenceAdapter.listSessions()`：每次调用都读 index.json + 排序

**评估**：
- 适用于前端轮询 list_sessions 的场景（如每秒一次），避免重复排序
- Cline 未做此优化（可能因 SQLite 查询本身够快）
- **合理增强，保留**

---

## 5. 修复建议

### 短期（P1）
1. **S6/S12 版本迁移机制**：实现版本迁移注册表，支持 `_SESSION_FILE_VERSION` / `_STATE_FILE_VERSION` 升级时平滑迁移旧数据。当前版本不匹配直接丢弃的策略会导致升级时数据丢失。

### 中期（P2）
1. **S2/S9 schema 字段扩展**：在 `SessionInfo` 中增加 `status`、`provider`、`model`、`ended_at`、`exit_code` 字段，提升会话恢复完整度。无需复刻全部 27 字段，保留量化场景所需子集。
2. **S8 list 查询优化**：增加 `sessions.index.json` 索引文件，启动时仅读索引恢复 `SessionInfo`（不加载 messages），按需 `load_session()` 加载完整消息，避免启动时全量扫描。

### 长期（P3）
1. **S7 session-export**：可选实现简化版 HTML 导出，便于用户分享量化分析对话记录。
2. **S4 锁可取消等待**：可选支持 `abort_event` 参数，与 Cline `AbortSignal` 语义对齐。

---

## 6. 验证记录

### 6.1 文件对照
- Cline 源码：
  - `third_party/cline/sdk/packages/core/src/services/storage/sqlite-session-store.ts`（272 行，已逐行读取）
  - `third_party/cline/sdk/packages/core/src/services/storage/session-store.ts`（1 行，仅类型重导出）
  - `third_party/cline/sdk/packages/core/src/session/services/file-session-service.ts`（已读取 L1-229，含 FileSessionPersistenceAdapter）
  - `third_party/cline/sdk/packages/core/src/session/stores/session-manifest-store.ts`（已读取 `persistSessionMessages` L157-187）
  - `third_party/cline/sdk/packages/shared/src/db/sqlite-db.ts`（已读取 schema L184-270 + LEGACY_MIGRATIONS L272-337 + ensureSessionSchema L348-381）
  - `third_party/cline/apps/vscode/src/core/locks/SqliteLockManager.ts`（298 行，已逐行读取）
  - `third_party/cline/apps/vscode/src/services/mcp/settingsLock.ts`（228 行，已逐行读取，与我的 file_lock.py 直接对标）
  - `third_party/cline/apps/vscode/src/core/storage/state-migrations.ts`（233 行，已逐行读取）
  - `third_party/cline/apps/vscode/src/core/storage/disk.ts`（已读取 L1-170，确认无显式备份机制）
  - `third_party/cline/apps/cli/src/session/export.ts`（922 行，已读取，确认 HTML 导出实现）
  - `third_party/cline/apps/cli/src/commands/history.ts`（已读取 `exportHistorySession` L25-39）
  - `third_party/cline/sdk/packages/shared/src/session/records.ts`（已读取 `SessionRuntimeRecordShape` L20-41）
  - `third_party/cline/sdk/packages/core/src/types/sessions.ts`（已读取 `SessionRecord` 定义）

- 我的实现：
  - `agent/session.py`（500 行，已逐行读取）
  - `agent/file_lock.py`（272 行，已逐行读取）
  - `agent/state.py`（376 行，已逐行读取）

### 6.2 数据目录验证
- `agent_data/sessions/`：确认存在 15 个会话文件（`conv_*.json`），格式为 `{version, session_id, created_at, last_active, title, messages}`，与 `SessionInfo` 定义一致
- `agent_data/state/`：确认存在 17 个状态文件（`conv_*.json` + 2 个测试文件），格式为 `{version, todos, mode}`，与 `SessionState.to_dict()` 一致

### 6.3 关键逻辑点验证
- S5 stale 接管：我的 `_takeover_stale`（file_lock.py L213-226）与 Cline `reclaimStaleLock`（settingsLock.ts L107-131）逻辑完全等价——均通过 mtime 判断 stale，rename aside 后删除，避免直接删除导致的竞态
- S10 全量覆写：我的 `_persist_session`（session.py L157-188）与 Cline `persistSessionMessages`（session-manifest-store.ts L157-175）均为每次写入完整 messages 数组，无增量 append
- S13 备份：Cline `disk.ts` 仅 `saveTaskMetadata` 等单文件写入，无 backup 副本逻辑；我的实现同样无备份，仅靠 atomic write 防损坏——两者一致

---

**阶段 S 结论**：会话持久化与锁对齐度约 64%（含额外增强覆盖度约 78%）。核心差距集中在 schema 字段不完整（S2/S9）和版本迁移缺失（S6/S12），前者影响会话恢复完整度，后者在版本升级时会导致历史数据丢失。锁机制（S3/S4/S5）逻辑上与 Cline settingsLock 等价，stale 接管实现完全一致。并发写安全（S11）和索引内存缓存（S14）为合理增强，应保留。session-export（S7）为可选功能，量化场景优先级较低。
