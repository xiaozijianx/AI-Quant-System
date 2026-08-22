# Phase 7.5 会话持久化对比

> 对比范围：Cline `sdk/packages/core/src/services/storage/sqlite-session-store.ts` + `sdk/packages/core/src/session/services/file-session-service.ts` + `sdk/packages/core/src/session/services/persistence-service.ts` + `sdk/packages/core/src/session/stores/session-manifest-store.ts` + `sdk/packages/core/src/session/models/session-row.ts` + `sdk/packages/core/src/session/models/session-manifest.ts` + `sdk/packages/core/src/session/session-snapshot.ts` + `sdk/packages/core/src/session/session-versioning-service.ts` + `sdk/packages/shared/src/db/sqlite-db.ts`（SCHEMA_STATEMENTS + LEGACY_MIGRATIONS + ensureSessionSchema）+ `apps/vscode/src/core/locks/SqliteLockManager.ts` + `sdk/packages/shared/src/storage/paths.ts`（resolveDbDataDir / resolveSessionDataDir），对比 Charles `agent/session.py`（`SessionManager` + `SessionInfo` + `_migrate_session_data` + `_message_to_dict` / `_dict_to_message` + `_ensure_json_serializable`）+ `agent/state.py`（`SessionState` + `load_all_states`）+ `agent/file_lock.py`（`FileLock`）+ `agent/server.py` L82-178（启动恢复 + 会话 API）；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/services/storage/sqlite-session-store.ts` L1-272（`SqliteSessionStore` 类：create / update / updateStatus / get / list / delete）
> - `third_party/cline/sdk/packages/core/src/session/services/file-session-service.ts` L1-284（`FileSessionPersistenceAdapter` + `FileSessionService`：sessions.index.json + subagent-spawn-queue.json + atomicWriteJson）
> - `third_party/cline/sdk/packages/core/src/session/services/persistence-service.ts` L1-610（`UnifiedSessionPersistenceService`：createRootSessionWithArtifacts + updateSessionStatus + withOccRetry + reconcileDeadRunningSession + listSessions + deleteSession）
> - `third_party/cline/sdk/packages/core/src/session/stores/session-manifest-store.ts` L1-120（`SessionManifestStore`：writeSessionManifest + readSessionManifestTitle + initializeMessagesFile）
> - `third_party/cline/sdk/packages/core/src/session/models/session-row.ts` L1-80（`SessionRow` 接口 26+ 字段）
> - `third_party/cline/sdk/packages/core/src/session/models/session-manifest.ts` L1-30（`SessionManifestSchema` zod 校验）
> - `third_party/cline/sdk/packages/core/src/session/session-snapshot.ts` L117-177（`createCoreSessionSnapshot` + `coreSessionSnapshotToRecord`）
> - `third_party/cline/sdk/packages/core/src/session/session-versioning-service.ts` L1-60（`SessionVersioningService` + checkpoint restore）
> - `third_party/cline/sdk/packages/shared/src/db/sqlite-db.ts` L180-381（`SCHEMA_STATEMENTS` + `LEGACY_MIGRATIONS` + `ensureSessionSchema` + `loadSqliteDb` + `withSqliteBusyRetry`）
> - `third_party/cline/apps/vscode/src/core/locks/SqliteLockManager.ts` L1-298（`SqliteLockManager`：locks 表 + instance/folder lock + stale lock 清理）
> - `third_party/cline/sdk/packages/shared/src/storage/paths.ts` L124-170（`resolveDbDataDir` → `data/db/`、`resolveSessionDataDir` → `data/sessions/`）
>
> Charles 源码：
> - `agent/session.py` L1-739（`_SESSION_FILE_VERSION=2` + `_migrate_session_v1_to_v2` + `_SESSION_MIGRATIONS` + `_migrate_session_data` + `SessionInfo` + `SessionManager` + `_message_to_dict` + `_part_to_dict` + `_dict_to_message` + `_dict_to_part` + `_ensure_json_serializable`）
> - `agent/state.py` L1-360（`_STATE_FILE_VERSION=1` + `SessionState` + `TodoItem` + `load_all_states` + `clear_session_state`）
> - `agent/file_lock.py` L1-272（`FileLock` + `STALE_MS=10_000` + `POLL_MS=25` + `with_file_lock`）
> - `agent/server.py` L82-178（`_session_manager = SessionManager()` 全局单例 + `load_all()` 启动恢复 + `load_all_states()` 状态恢复）+ L1054-1070（`/sessions` GET 列表）+ L1072-1085（`/sessions/{session_id}` DELETE 清空）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的会话持久化机制。**核心结论：计划文件 P7.5 列出的 7 项对比项中 7.5.1-7.5.4 已对齐（存储格式刻意差异化、版本迁移/跨进程锁/列表查询功能对齐），7.5.5-7.5.6 为 Charles 主动权衡（可读性高、性能中），7.5.7 标注正确（Charles 缺失 session-export）。但 Cline 在 OCC 乐观锁、stale 会话回收、子 agent spawn 队列、SessionManifest zod 校验、SessionVersioningService checkpoint 恢复、SQLite busy retry 6 个增强点上 Charles 均无对应实现——这些缺失在量化单进程场景下可接受，多进程/团队协作场景下需补齐。**

### 计划文件核实结果

AGENT_COMPARISON_PLAN_V2.md L2604-2627 的 P7.5 对比表标注 7.5.1-7.5.7。经源码核实：

| 计划项 | 计划标注 | 实际核实 | 一致性 |
|--------|---------|---------|--------|
| 7.5.1 存储格式 | SQLite vs JSON | Cline SQLite `sessions.db`（sqlite-db.ts L184-214 SCHEMA_STATEMENTS）+ JSON manifest（file-session-service.ts L19-22 FileSessionIndex）/ Charles JSON `<id>.json` + `sessions.index.json`（session.py L58/L211/L282） | 中（刻意差异化） |
| 7.5.2 版本迁移 | 已对齐 | Cline `LEGACY_MIGRATIONS` 数组（sqlite-db.ts L272-337）+ `ensureSessionSchema` ALTER TABLE（L348-381）/ Charles `_SESSION_MIGRATIONS` dict（session.py L91-93）+ `_migrate_session_data` 函数链（L96-115） | 高 |
| 7.5.3 跨进程锁 | 已对齐（Stage 31.7） | Cline `SqliteLockManager`（SqliteLockManager.ts L7-298）locks 表 + 文件锁初始化 / Charles `FileLock`（file_lock.py L57-252）mkdir+rename 目录锁 | 中-高（机制不同，功能对齐） |
| 7.5.4 session 列表查询 | 已对齐（Stage 31.8） | Cline SQLite `SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT ?`（sqlite-session-store.ts L248-261）+ `reconcileDeadSessions`（persistence-service.ts L537-555）/ Charles `_sorted_index` 内存缓存 + `_index_dirty` flag（session.py L194-195/L564-578） | 高 |
| 7.5.5 可读性 | 低 vs 高 | Cline SQLite 二进制 + JSON manifest（需工具查看）/ Charles 纯 JSON 文本（可直接 cat 查看） | 高（Charles 增强） |
| 7.5.6 性能 | 高 vs 中 | Cline SQLite 索引 + WAL 模式 + busy_timeout（sqlite-db.ts L352-353）/ Charles JSON 全文件读写 + 内存索引缓存 | 中（Charles 弱，量化场景可接受） |
| 7.5.7 session-export | 是 vs 无 | Cline `createCoreSessionSnapshot` + `coreSessionSnapshotToRecord`（session-snapshot.ts L117-177）+ `SessionVersioningService`（session-versioning-service.ts L1-60）/ Charles 无对应（仅 `/sessions` GET 返回列表） | 低（Charles 缺失） |

### 核心结论

1. **存储格式刻意差异化**：Cline 采用 SQLite + JSON manifest 混合存储（元信息在 SQLite，消息和 manifest 在 JSON 文件）；Charles 采用纯 JSON 文件存储（元信息和消息合并在 `<id>.json`，索引在 `sessions.index.json`）。Charles 设计更简单直接，符合量化单进程场景。
2. **版本迁移机制对齐**：Cline 用 `LEGACY_MIGRATIONS` 数组定义 `ALTER TABLE` 迁移；Charles 用 `_SESSION_MIGRATIONS` dict 定义函数式迁移。两者均支持逐版本升级，Charles 当前仅 v1→v2 一条迁移路径，Cline 有 12 条 legacy migration。
3. **跨进程锁机制不同但功能对齐**：Cline 用 SQLite `locks` 表（instance/folder 锁）+ 文件锁保护 DB 初始化；Charles 用 `FileLock` 目录锁（mkdir+rename 原子操作）保护单个会话文件读写。两者均支持 stale 锁检测和强制接管。
4. **session 列表查询机制不同**：Cline 用 SQLite `ORDER BY started_at DESC LIMIT ?` + `reconcileDeadSessions` 回收僵尸会话；Charles 用 `_sorted_index` 内存缓存 + `_index_dirty` flag 避免重复排序。Charles 更简单但无僵尸会话回收。
5. **Charles 缺失 6 个 Cline 增强特性**：(a) OCC 乐观锁 `withOccRetry` + `expectedStatusLock`（persistence-service.ts L40/L187-204）；(b) stale 会话回收 `reconcileDeadRunningSession`（L439-508）；(c) 子 agent spawn 队列 `FileSpawnQueue`（file-session-service.ts L34-38/L231-267）；(d) SessionManifest zod schema 校验（session-manifest.ts L6-28）；(e) SessionVersioningService checkpoint 恢复（session-versioning-service.ts）；(f) SQLite busy retry `withSqliteBusyRetry`（sqlite-db.ts L71-84）。
6. **session-export 缺失**：Cline 有完整的 `createCoreSessionSnapshot` → `coreSessionSnapshotToRecord` → `SessionVersioningService` 链路，支持会话快照导出和基于 checkpoint 的版本恢复；Charles 仅返回会话列表和单会话消息，无快照导出和版本恢复能力。
7. **数据模型字段差异**：Cline `SessionRow` 有 26+ 字段（含 pid/source/workspaceRoot/teamName/enableTools/enableSpawn/enableTeams/parentSessionId/parentAgentId/agentId/conversationId/isSubagent/statusLock/hookPath/messagesPath 等）；Charles `SessionInfo` 仅 9 字段（session_id/created_at/last_active/message_count/title/status/provider/model/ended_at/exit_code）。Charles 缺失多进程协作相关字段，符合单进程量化场景。
8. **nanobot 残留**：P7.5 范围内（session.py + server.py + state.py + file_lock.py）共 **5 处注释残留、0 处实现逻辑残留**。残留均为 docstring 中"对标 nanobot ..."的历史说明，不影响功能。

### 一致性总体评估

- **存储格式**：**中**。刻意差异化，Cline SQLite+JSON 混合，Charles 纯 JSON。功能对齐但性能特性不同。
- **版本迁移**：**高**。双方均有版本迁移机制，Charles 函数式迁移更灵活，Cline ALTER TABLE 更贴近 SQL 生态。
- **跨进程锁**：**中-高**。Cline SQLite locks 表 + 文件锁，Charles 目录锁。功能对齐，机制不同。
- **session 列表查询**：**高**。双方均有高效的列表查询，Charles 内存缓存更适合小规模场景，Cline SQLite 索引更适合大规模场景。
- **可读性**：**高（Charles 增强）**。Charles JSON 可直接查看，Cline SQLite 需工具。
- **性能**：**中（Charles 弱）**。Cline SQLite WAL + 索引性能高，Charles JSON 全文件读写性能中。量化场景（会话数 < 1000）可接受。
- **session-export**：**低（Charles 缺失）**。Cline 有完整快照导出链路，Charles 无对应。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.5.1 | 存储格式 | SQLite `sessions.db`（sqlite-db.ts L184-214 `SCHEMA_STATEMENTS` 定义 sessions/subagent_spawn_queue/schedules/schedule_executions 4 表）+ JSON manifest（file-session-service.ts L19-22 `FileSessionIndex` + session-manifest.ts L6-28 `SessionManifestSchema`）；存储位置 `data/db/sessions.db` + `data/sessions/<id>/manifest.json` + `data/sessions/<id>/messages.json`（paths.ts L132-170） | JSON 文件 `agent_data/sessions/<session_id>.json`（session.py L58/L205-211）+ 索引 `agent_data/sessions/sessions.index.json`（L280-282）；元信息和消息合并存储 | 中（刻意差异化） | Cline 元信息在 SQLite（支持复杂查询），消息在 JSON 文件（支持流式追加）；Charles 元信息和消息合并存储，简化实现。Charles 单文件更易备份和迁移 |
| 7.5.2 | 版本迁移 | `LEGACY_MIGRATIONS` 数组（sqlite-db.ts L272-337）定义 12 条 `ALTER TABLE` 迁移（sessions 表 10 列 + schedules 表 3 列）；`ensureSessionSchema`（L348-381）检测列存在性后执行 ALTER；workspace_root 列追加后 `UPDATE sessions SET workspace_root = cwd` 回填 | `_SESSION_MIGRATIONS` dict（session.py L91-93）`{1: _migrate_session_v1_to_v2}`；`_migrate_session_data`（L96-115）while 循环逐版本应用迁移函数；`_migrate_session_v1_to_v2`（L69-88）补齐 status/provider/model/ended_at/exit_code 字段 + setdefault 兜底 | 高 | 已对齐。双方均支持逐版本迁移。差异：(a) Cline 用 SQL ALTER TABLE，Charles 用 dict 函数链；(b) Cline 12 条迁移，Charles 当前仅 1 条；(c) Charles 迁移函数返回新 dict，Cline 直接修改表结构 |
| 7.5.3 | 跨进程锁 | `SqliteLockManager`（SqliteLockManager.ts L7-298）：SQLite `locks` 表（id/held_by/lock_type/lock_target/locked_at）+ UNIQUE(lock_type, lock_target) 约束 + 3 索引；instance/folder 两类锁；`cleanupStaleLockSync`（L90-116）1 分钟 stale 超时；DB 初始化用 `.lock` 文件 + `fs.openSync(lockFile, "wx")` 独占创建 | `FileLock`（file_lock.py L57-252）：目录锁 `{file_path}.lock` + staging 目录 + `os.replace` 原子 rename；`STALE_MS = 10_000`（10 秒，L50）；`_try_acquire`（L153-194）mkdir staging + 写 owner marker + rename；`_takeover_stale`（L213-226）rename aside 后删除 | 中-高（功能对齐） | 已对齐（Stage 31.7）。双方均支持跨进程互斥 + stale 锁检测 + 强制接管。差异：(a) Cline 用 SQLite 表存储锁状态，Charles 用目录存在性；(b) Cline stale 超时 1 分钟，Charles 10 秒；(c) Cline 支持 instance/folder 两类锁，Charles 仅文件级锁 |
| 7.5.4 | session 列表查询 | SQLite `SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT ?`（sqlite-session-store.ts L248-261）+ `listSessions`（persistence-service.ts L510-535）调用 `reconcileDeadSessions`（L537-555）回收僵尸会话 + `readSessionManifestTitle` 异步读取 manifest 标题 | `list_sessions`（session.py L564-578）：`_index_dirty=True` 时 `sorted(self._info.values(), key=lambda x: x.last_active, reverse=True)` 排序，否则返回 `_sorted_index` 缓存副本 | 高 | 已对齐（Stage 31.8）。差异：(a) Cline 用 SQL ORDER BY + LIMIT，Charles 用内存 sorted；(b) Cline 有僵尸会话回收（检测 pid 是否存活），Charles 无（单进程场景不需要）；(c) Cline 异步读 manifest 标题，Charles 标题直接在 SessionInfo 中 |
| 7.5.5 | 可读性 | SQLite 二进制 `sessions.db` 需 `sqlite3` CLI 或工具查看；JSON manifest 可读但分散在 `data/sessions/<id>/` 多文件 | JSON 文件 `agent_data/sessions/<id>.json` 可直接用文本编辑器/cat 查看；`sessions.index.json` 单文件含所有会话元信息 | 高（Charles 增强） | Charles 增强。JSON 文件可直接查看，便于调试和手动修复。Cline SQLite 二进制需工具，但支持复杂查询 |
| 7.5.6 | 性能 | SQLite WAL 模式（sqlite-db.ts L352 `PRAGMA journal_mode = WAL`）+ `busy_timeout = 5000`（L353）+ `withSqliteBusyRetry`（L71-84）3 次重试 + 50ms 指数退避 + 索引（idx_locks_* / idx_schedule_*）；`listSessions` scanLimit = `min(limit * 5, 2000)`（persistence-service.ts L512） | JSON 全文件读写 + `_atomic_write_json`（session.py L213-223）先写 .tmp 再 rename + `_sorted_index` 内存缓存避免重复排序；`load_all` 优先读索引文件（L370-374），索引缺失时 glob 扫描（L377-389） | 中（Charles 弱） | Charles 弱。Cline SQLite 索引 + WAL 高并发性能优；Charles JSON 全文件读写，会话数多时性能下降。量化场景（会话数 < 1000）可接受 |
| 7.5.7 | session-export | `createCoreSessionSnapshot`（session-snapshot.ts L117-177）构造 `CoreSessionSnapshot`（version/sessionId/source/status/createdAt/updatedAt/endedAt/exitCode/interactive/workspace/model/capabilities/lineage/team/prompt/metadata/artifacts/messages/usage/aggregateUsage/checkpoint）；`coreSessionSnapshotToRecord`（L179+）转 `SessionRecord`；`SessionVersioningService`（session-versioning-service.ts L1-60）支持基于 checkpoint 的版本恢复 | 无对应。仅 `/sessions` GET（server.py L1054-1070）返回会话列表（session_id/title/message_count/created_at/last_active），`/sessions/{session_id}` DELETE 清空会话；无快照导出 API | 低（Charles 缺失） | Charles 缺失。Cline 支持完整会话快照导出（含消息/usage/checkpoint/lineage）和基于 checkpoint 的版本恢复；Charles 仅支持列表和清空，无快照导出和版本恢复 |

---

## 三、重点差距详解

### 3.1 存储格式架构差异（刻意差异化，非缺陷）

**Cline 混合存储架构**：
- 元信息在 SQLite `sessions.db`（`data/db/sessions.db`）：26+ 字段的 `sessions` 表（sqlite-db.ts L184-214），支持 `ORDER BY` / `WHERE` / `LIMIT` 复杂查询
- 消息在 JSON 文件（`data/sessions/<id>/messages.json`）：`SessionManifestStore.initializeMessagesFile` + `persistSessionMessages` 流式追加
- Manifest 在 JSON 文件（`data/sessions/<id>/manifest.json`）：`SessionManifestSchema` zod 校验（session-manifest.ts L6-28）
- 索引在 JSON 文件（`data/sessions/sessions.index.json`）：`FileSessionIndex`（file-session-service.ts L19-22）
- Spawn 队列在 JSON 文件（`data/sessions/subagent-spawn-queue.json`）：`FileSpawnQueue`（L34-38）

**Charles 纯 JSON 存储架构**：
- 元信息 + 消息合并存储在 `agent_data/sessions/<session_id>.json`（session.py L240-253）：`_persist_session` 一次性写入 version/session_id/created_at/last_active/title/status/provider/model/ended_at/exit_code/messages
- 索引在 `agent_data/sessions/sessions.index.json`（L280-282）：`_persist_index` 仅存 SessionInfo（不含 messages）
- 状态在 `agent_data/state/<session_id>.json`（state.py L47）：todos/mode 持久化

**差异分析**：
- Cline 元信息与消息分离，支持单独查询元信息（不加载消息），适合大规模会话场景
- Charles 元信息与消息合并，每次 `_persist_session` 写入完整数据，会话消息多时写入开销大
- Cline 有 SessionManifest zod 严格校验，Charles 无 schema 校验（仅 version 字段检查）
- Charles 单文件设计更易备份和迁移，Cline 多文件设计更灵活但管理复杂

### 3.2 版本迁移机制对齐（功能对齐，实现不同）

**Cline `LEGACY_MIGRATIONS`（sqlite-db.ts L272-337）**：
```typescript
const LEGACY_MIGRATIONS: Array<{table: string; column: string; sql: string}> = [
    {table: "sessions", column: "workspace_root", sql: "ALTER TABLE sessions ADD COLUMN workspace_root TEXT;"},
    {table: "sessions", column: "parent_session_id", sql: "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT;"},
    // ... 12 条迁移
];
function ensureSessionSchema(db, options) {
    for (const migration of LEGACY_MIGRATIONS) {
        if (!getColumns(migration.table).has(migration.column)) {
            db.exec(migration.sql);
            if (migration.column === "workspace_root") {
                db.exec("UPDATE sessions SET workspace_root = cwd WHERE ...");
            }
        }
    }
}
```

**Charles `_SESSION_MIGRATIONS`（session.py L69-115）**：
```python
def _migrate_session_v1_to_v2(data: dict) -> dict:
    data.setdefault("status", "active")
    data.setdefault("provider", "")
    data.setdefault("model", "")
    data.setdefault("ended_at", None)
    data.setdefault("exit_code", None)
    data["version"] = 2
    return data

_SESSION_MIGRATIONS: dict[int, callable] = {1: _migrate_session_v1_to_v2}

def _migrate_session_data(data: dict) -> dict | None:
    version = data.get("version", 1)
    while version < _SESSION_FILE_VERSION:
        migrator = _SESSION_MIGRATIONS.get(version)
        if migrator is None:
            return None
        data = migrator(data)
        version = data.get("version", version + 1)
    return data
```

**差异分析**：
- Cline 用 SQL `ALTER TABLE` + `UPDATE` 回填，Charles 用 dict `setdefault` 兜底
- Cline 12 条迁移（10 列 sessions + 3 列 schedules），Charles 1 条迁移（v1→v2 补 5 字段）
- Cline 检测列存在性（`PRAGMA table_info`），Charles 检测 version 字段
- Charles 迁移失败返回 None 跳过文件，Cline 迁移失败抛异常

### 3.3 跨进程锁机制差异（功能对齐，机制不同）

**Cline `SqliteLockManager`（SqliteLockManager.ts L7-298）**：
- SQLite `locks` 表：`(id, held_by, lock_type, lock_target, locked_at)` + `UNIQUE(lock_type, lock_target)`
- 两类锁：`instance`（实例注册）+ `folder`（文件夹锁）
- `registerFolderLock`：`INSERT OR IGNORE` + 检查 changes
- `cleanupStaleLockSync`：1 分钟 stale 超时（`STALE_LOCK_TIMEOUT = 1 * 60 * 1000`）
- DB 初始化用 `.lock` 文件 + `fs.openSync(lockFile, "wx")` 独占创建 + `sleepSync` 重试
- `cleanupOrphanedFolderLocks`：清理孤儿 folder 锁（held_by 不在 instance 锁中）

**Charles `FileLock`（file_lock.py L57-252）**：
- 目录锁：`{file_path}.lock` 目录 + staging 目录 + `os.replace` 原子 rename
- 单一文件级锁（无 instance/folder 区分）
- `_try_acquire`：mkdir staging + 写 owner marker + rename staging→lock_dir
- `_is_stale`：10 秒 stale 超时（`STALE_MS = 10_000`）
- `_takeover_stale`：rename aside 后 rmtree
- 无孤儿锁清理（单进程场景不需要）

**差异分析**：
- Cline 用 SQLite 表存储锁状态，支持复杂查询（如 `getInstanceByPort`）；Charles 用目录存在性，仅支持文件级锁
- Cline stale 超时 1 分钟（容忍长时间操作），Charles 10 秒（快速检测崩溃）
- Cline 支持 instance/folder 两类锁 + 孤儿锁清理，Charles 仅文件级锁
- Charles `_try_acquire` 用 staging 目录 + rename 实现原子性，Cline `registerFolderLock` 用 `INSERT OR IGNORE`

### 3.4 session 列表查询机制差异

**Cline `listSessions`（persistence-service.ts L510-535）**：
```typescript
async listSessions(limit = 200): Promise<SessionRow[]> {
    const requestedLimit = Math.max(1, Math.floor(limit));
    const scanLimit = Math.min(requestedLimit * 5, 2000);
    await this.reconcileDeadSessions(scanLimit);  // 回收僵尸会话
    const rows = (await this.adapter.listSessions({limit: scanLimit})).slice(0, requestedLimit);
    const manifestTitles = await Promise.all(rows.map(row => 
        this.manifestStore.readSessionManifestTitle(row.sessionId)  // 异步读 manifest 标题
    ));
    return rows.map((row, index) => ({...row, metadata: resolved}));
}
```

**Charles `list_sessions`（session.py L564-578）**：
```python
def list_sessions(self) -> list[SessionInfo]:
    if self._index_dirty:
        self._sorted_index = sorted(
            self._info.values(),
            key=lambda x: x.last_active,
            reverse=True,
        )
        self._index_dirty = False
    return list(self._sorted_index)
```

**差异分析**：
- Cline 用 SQL `ORDER BY started_at DESC LIMIT ?`，Charles 用 Python `sorted` + 内存缓存
- Cline 有 `reconcileDeadSessions` 回收僵尸会话（检测 pid 存活），Charles 无（单进程不需要）
- Cline 异步读 manifest 标题（`readSessionManifestTitle`），Charles 标题直接在 SessionInfo 中
- Cline `scanLimit = min(limit * 5, 2000)` 多扫描以补偿 reconcile 过滤，Charles 直接全量排序
- Charles `_index_dirty` flag 避免重复排序，适合频繁调用（如前端轮询）

### 3.5 OCC 乐观锁缺失（Charles 缺失，多进程场景需补齐）

**Cline `withOccRetry` + `expectedStatusLock`（persistence-service.ts L40/L187-204）**：
```typescript
const OCC_MAX_RETRIES = 4;
async updateSessionStatus(sessionId, status, exitCode) {
    const result = await withOccRetry(
        () => this.adapter.getSession(sessionId),
        async (row) => this.adapter.updateSession({
            sessionId, status,
            expectedStatusLock: row.statusLock,  // 乐观锁
        }),
        OCC_MAX_RETRIES,
    );
}
```
- `statusLock` 字段：每次更新 +1，`expectedStatusLock` 不匹配时返回 `updated: false`
- `withOccRetry`：最多 4 次重试，每次重新读取最新 statusLock
- 防止多进程并发更新同一会话状态导致丢失更新

**Charles 缺失**：
- `SessionInfo` 无 `statusLock` 字段
- `set_session_status`（session.py L505-527）直接修改内存 + 落盘，无乐观锁保护
- `FileLock` 保护单文件写入，但无法防止"读取-修改-写入"竞态（如 A 进程读取后 B 进程写入，A 进程再写入覆盖 B）

**影响分析**：
- 单进程场景：无影响（内存状态单点）
- 多进程场景（如 web 进程 + scheduler 进程并发）：可能丢失状态更新
- 量化场景当前为单进程，可接受；未来扩展多进程时需补齐

### 3.6 stale 会话回收缺失（Charles 缺失，单进程场景可接受）

**Cline `reconcileDeadRunningSession`（persistence-service.ts L439-508）**：
- 检测 `idle` / `running` / `pending` 状态的会话，检查 `pid` 是否存活（`process.kill(pid, 0)`）
- pid 已死时标记为 `failed` + `endedAt` + `exitCode=1` + `metadata.terminal_marker = "failed_external_process_exit"`
- `listSessions` 调用 `reconcileDeadSessions` 自动回收
- 防止崩溃进程留下"僵尸 running"会话污染列表

**Charles 缺失**：
- 无 pid 字段，无法检测进程存活
- 无 `reconcileDeadSessions` 逻辑
- 会话状态由 `set_session_status` 主动设置，崩溃后会话可能停留在 `active` 状态

**影响分析**：
- 单进程场景：进程崩溃后重启，所有会话状态重置，无僵尸会话问题
- 多进程场景：进程崩溃后其会话可能停留在 `active`，需手动清理
- 量化场景当前为单进程，可接受

### 3.7 子 agent spawn 队列缺失（Charles 缺失，团队协作场景需补齐）

**Cline `FileSpawnQueue`（file-session-service.ts L34-38/L231-267）**：
- `subagent-spawn-queue.json` 持久化 spawn 请求队列
- `enqueueSpawnRequest`：rootSessionId + parentAgentId + task + systemPrompt
- `claimSpawnRequest`：rootSessionId + parentAgentId 匹配 + `consumedAt` 标记
- `TeamChildSessionManager`（persistence-service.ts L61-67）管理子 agent 生命周期

**Charles 缺失**：
- 无 spawn 队列概念
- 无 `TeamChildSessionManager` 对应实现
- 量化场景无子 agent 协作需求，可接受

### 3.8 session-export 完整链路缺失（Charles 缺失）

**Cline session-export 链路**：
1. `createCoreSessionSnapshot`（session-snapshot.ts L117-177）：构造 `CoreSessionSnapshot` 含 version/sessionId/source/status/createdAt/updatedAt/endedAt/exitCode/interactive/workspace/model/capabilities/lineage/team/prompt/metadata/artifacts/messages/usage/aggregateUsage/checkpoint
2. `coreSessionSnapshotToRecord`（L179+）：转 `SessionRecord` 用于恢复
3. `SessionVersioningService`（session-versioning-service.ts L1-60）：基于 checkpoint 的版本恢复，含 `SessionCheckpointRestoreContext` + `SessionCheckpointRestoreResult`
4. `applyCheckpointToWorktree` + `trimMessagesBeforeCheckpoint`：checkpoint 恢复时联动文件系统

**Charles 缺失**：
- 无 `CoreSessionSnapshot` 对应
- 无 `SessionVersioningService` 对应
- Charles 的 `/rollback` 端点（server.py L1500-1619）仅支持回滚到 checkpoint，不支持完整快照导出
- Charles 的 checkpoint 机制（`agent/checkpoint.py`）仅保存消息快照，不含 usage/lineage/capabilities 等元信息

**影响分析**：
- 量化场景无需会话快照导出，可接受
- 若需会话迁移/审计/分享，需补齐快照导出能力

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（5 处，不影响功能）

| 文件 | 行号 | 残留内容 | 类型 | 影响 |
|------|------|---------|------|------|
| `agent/session.py` | L2 | `"""会话管理 — 对标 Cline session persistence + nanobot session_key` | docstring | 无（历史说明） |
| `agent/session.py` | L22-23 | `对标 nanobot: - session_key 参数，内存存储` | docstring | 无（历史说明，实际实现用 session_id） |
| `agent/server.py` | L2 | `"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py` | docstring | 无（历史说明） |
| `agent/server.py` | L4 | `提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。` | docstring | 无（历史说明，AgentRuntime 已替换 nanobot） |
| `agent/server.py` | L28-29 | `对标 nanobot: - routes/chat.py _sse_generator() + _StreamCollectorHook` | docstring | 无（历史说明） |

### 4.2 实现逻辑残留检查

| 检查项 | 检查方法 | 结果 | 说明 |
|--------|---------|------|------|
| `session_key` 参数 | Grep `session_key` in `agent/` | 仅 2 处注释（session.py L2/L23），无代码使用 | Charles 实际用 `session_id`（Cline 风格），非 `session_key`（nanobot 风格） |
| `from nanobot` 导入 | Grep `from nanobot\|import nanobot` in `agent/` | 0 匹配 | 无 nanobot 模块依赖 |
| `_StreamCollectorHook` 使用 | Grep `_StreamCollectorHook` in `agent/` | 仅 1 处注释（server.py L29），无代码使用 | Charles 用 `AgentRuntime` + `asyncio.Queue` 替代 |
| `nanobot.` 调用 | Grep `nanobot\.` in `agent/`（排除注释） | 0 匹配 | 无 nanobot 对象调用 |
| nanobot 配置文件 | Grep `nanobot` in `agent_config/` | 未检查（超出 P7.5 范围） | P7.5 范围内无残留 |

### 4.3 残留处理建议

- **注释残留**：**不建议修改**。这 5 处注释是历史迁移说明，记录了 Charles 从 nanobot 迁移到 Cline 架构的演进过程，对未来维护有参考价值。
- **实现逻辑残留**：**无**。Charles 完全使用 `session_id`（Cline 风格），无 `session_key`（nanobot 风格）的代码逻辑。

---

## 五、修复建议与可选重构

### 5.1 必须修复（无）

P7.5 范围内无必须修复的缺陷。Charles 的会话持久化机制在量化单进程场景下功能完整。

### 5.2 建议增强（多进程场景）

**问题**：Charles 缺失 OCC 乐观锁（7.5.3），多进程并发更新同一会话状态可能丢失更新。

**修复建议**：
1. 在 `SessionInfo` 增加 `status_lock: int = 0` 字段
2. 在 `set_session_status` / `set_runtime_info` 中实现 OCC：
   ```python
   def set_session_status(self, session_id, status, exit_code=None, expected_lock=None):
       info = self._info.get(session_id)
       if info is None:
           return
       if expected_lock is not None and info.status_lock != expected_lock:
           raise ConcurrentModificationError(...)
       info.status = status
       info.status_lock += 1
       self._persist_session(session_id)
   ```
3. API 层增加重试逻辑（最多 4 次）

**权衡**：当前量化场景为单进程，无并发更新风险。若未来扩展为多进程（如 web + scheduler），需补齐。

### 5.3 可选增强：stale 会话回收（多进程场景）

**问题**：Charles 无 `reconcileDeadRunningSession`，进程崩溃后会话可能停留 `active` 状态。

**修复建议**：
1. 在 `SessionInfo` 增加 `pid: int = 0` 字段
2. 在 `list_sessions` 中调用 `_reconcile_dead_sessions`：检测 pid 存活，已死的标记为 `failed`
3. 用 `psutil.pid_exists(pid)` 检测进程存活

**权衡**：单进程场景不需要，多进程场景建议补齐。

### 5.4 可选增强：session-export（审计/迁移场景）

**问题**：Charles 无 `createCoreSessionSnapshot` 对应，无法导出完整会话快照。

**修复建议**：
1. 在 `SessionManager` 增加 `export_snapshot(session_id) -> dict` 方法
2. 返回含 version/sessionId/status/createdAt/updatedAt/messages/provider/model 的完整快照
3. 在 `server.py` 增加 `GET /api/chat/sessions/{session_id}/export` 端点

**权衡**：量化场景无导出需求，可接受缺失。若需审计或会话迁移，建议补齐。

### 5.5 可选重构：SessionManifest zod 校验对齐（非必须）

**问题**：Charles 无 schema 校验，仅 `version` 字段检查，加载损坏文件时可能产生不一致状态。

**修复建议**：
1. 引入 `pydantic` 或 `dataclass` + 手动校验
2. 在 `_load_session_from_file` 中用 schema 校验加载的 dict
3. 校验失败时跳过文件并记录日志

**权衡**：当前 `try/except` + `data.get` 兜底已足够，引入 schema 校验增加依赖。非必须。

---

## 六、验证方法

### 6.1 存储格式验证

1. 读取 Cline `sqlite-db.ts` L184-214 `SCHEMA_STATEMENTS`，确认 4 表（sessions/subagent_spawn_queue/schedules/schedule_executions）+ 2 索引
2. 读取 Cline `file-session-service.ts` L19-22 `FileSessionIndex`，确认 JSON 索引格式
3. 读取 Cline `paths.ts` L132-170，确认 `resolveSessionDataDir` → `data/sessions/` + `resolveDbDataDir` → `data/db/`
4. 读取 Charles `session.py` L58/L205-211/L280-282，确认 `agent_data/sessions/<id>.json` + `sessions.index.json` 格式

### 6.2 版本迁移验证

1. 读取 Cline `sqlite-db.ts` L272-337 `LEGACY_MIGRATIONS`，确认 12 条迁移
2. 读取 Cline `sqlite-db.ts` L348-381 `ensureSessionSchema`，确认 `PRAGMA table_info` 检测 + ALTER TABLE
3. 读取 Charles `session.py` L69-93 `_migrate_session_v1_to_v2` + `_SESSION_MIGRATIONS`，确认函数式迁移
4. 读取 Charles `session.py` L96-115 `_migrate_session_data`，确认 while 循环逐版本应用

### 6.3 跨进程锁验证

1. 读取 Cline `SqliteLockManager.ts` L7-298，确认 `locks` 表 + instance/folder 锁 + `cleanupStaleLockSync` 1 分钟超时
2. 读取 Cline `SqliteLockManager.ts` L34-80 `initializeDatabaseWithLockSync`，确认 `.lock` 文件 + `fs.openSync(lockFile, "wx")` 独占创建
3. 读取 Charles `file_lock.py` L57-252 `FileLock`，确认目录锁 + staging + `os.replace` 原子 rename
4. 读取 Charles `file_lock.py` L50 `STALE_MS = 10_000`，确认 10 秒 stale 超时
5. 读取 Charles `session.py` L257-260/L408，确认 `_persist_session` + `_load_session_from_file` 使用 `FileLock`

### 6.4 session 列表查询验证

1. 读取 Cline `sqlite-session-store.ts` L248-261 `list`，确认 `SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT ?`
2. 读取 Cline `persistence-service.ts` L510-535 `listSessions`，确认 `reconcileDeadSessions` + `readSessionManifestTitle`
3. 读取 Charles `session.py` L564-578 `list_sessions`，确认 `_index_dirty` flag + `sorted` 内存缓存
4. 读取 Charles `session.py` L194-195，确认 `_sorted_index` + `_index_dirty` 初始化

### 6.5 OCC 乐观锁缺失验证

1. 读取 Cline `persistence-service.ts` L40 `OCC_MAX_RETRIES = 4`，确认 4 次重试
2. 读取 Cline `persistence-service.ts` L187-204 `updateSessionStatus`，确认 `withOccRetry` + `expectedStatusLock`
3. 读取 Cline `file-session-service.ts` L142-211 `updateSession`，确认 `expectedStatusLock` 检查 + `nextStatusLock` 递增
4. 读取 Charles `session.py` L505-527 `set_session_status`，确认无 `statusLock` 字段，无 OCC 重试

### 6.6 stale 会话回收缺失验证

1. 读取 Cline `persistence-service.ts` L439-508 `reconcileDeadRunningSession`，确认 `isPidAlive` + `terminal_marker` 标记
2. 读取 Cline `persistence-service.ts` L537-555 `reconcileDeadSessions`，确认扫描 idle/running/pending 状态
3. Grep Charles `session.py` 搜索 `reconcile` / `pid` / `isPidAlive`，确认 0 匹配

### 6.7 session-export 缺失验证

1. 读取 Cline `session-snapshot.ts` L117-177 `createCoreSessionSnapshot`，确认 20+ 字段快照构造
2. 读取 Cline `session-versioning-service.ts` L1-60，确认 `SessionVersioningService` + `SessionCheckpointRestoreContext`
3. Grep Charles `session.py` + `server.py` 搜索 `export` / `snapshot`，确认无对应实现
4. 读取 Charles `server.py` L1054-1070 `/sessions` GET，确认仅返回列表（无快照导出）

### 6.8 nanobot 残留验证

1. Grep `agent/session.py` 搜索 `nanobot`（case-insensitive），确认 L2/L22-23 两处注释残留
2. Grep `agent/server.py` 搜索 `nanobot`，确认 L2/L4/L28-29 三处注释残留
3. Grep `agent/state.py` 搜索 `nanobot`，确认 0 匹配
4. Grep `agent/file_lock.py` 搜索 `nanobot`，确认 0 匹配
5. Grep `agent/` 搜索 `session_key`，确认仅 session.py L2/L23 注释，无代码使用
6. Grep `agent/` 搜索 `from nanobot\|import nanobot`，确认 0 匹配
7. Grep `agent/` 搜索 `_StreamCollectorHook`，确认仅 server.py L29 注释，无代码使用

---

## 七、附录

### 7.1 Cline 会话持久化架构图

```
SqliteSessionStore (sqlite-session-store.ts)
    ├── SQLite sessions.db (data/db/sessions.db)
    │   ├── sessions 表 (26+ 字段)
    │   ├── subagent_spawn_queue 表
    │   ├── schedules 表
    │   └── schedule_executions 表
    ├── ensureSessionSchema
    │   ├── SCHEMA_STATEMENTS (4 表 + 2 索引)
    │   └── LEGACY_MIGRATIONS (12 条 ALTER TABLE)
    └── withSqliteBusyRetry (3 次重试 + 50ms 指数退避)

FileSessionService (file-session-service.ts)
    ├── FileSessionPersistenceAdapter
    │   ├── sessions.index.json (FileSessionIndex)
    │   ├── subagent-spawn-queue.json (FileSpawnQueue)
    │   └── atomicWriteJson (tmp + rename)
    └── 继承 UnifiedSessionPersistenceService

UnifiedSessionPersistenceService (persistence-service.ts)
    ├── createRootSessionWithArtifacts
    │   ├── adapter.upsertSession (SQLite INSERT)
    │   ├── manifestStore.initializeMessagesFile
    │   └── manifestStore.writeSessionManifest
    ├── updateSessionStatus
    │   └── withOccRetry (4 次) + expectedStatusLock
    ├── listSessions
    │   ├── reconcileDeadSessions (pid 检测)
    │   ├── adapter.listSessions (SELECT ORDER BY)
    │   └── readSessionManifestTitle (异步)
    ├── deleteSession (cascade + 清理 artifacts)
    └── TeamChildSessionManager (子 agent 生命周期)

SqliteLockManager (SqliteLockManager.ts)
    ├── locks 表 (instance/folder 两类锁)
    ├── registerFolderLock (INSERT OR IGNORE)
    ├── cleanupStaleLockSync (1 分钟 stale)
    └── cleanupOrphanedFolderLocks

SessionSnapshot (session-snapshot.ts)
    ├── createCoreSessionSnapshot (20+ 字段)
    └── coreSessionSnapshotToRecord

SessionVersioningService (session-versioning-service.ts)
    ├── SessionCheckpointRestoreContext
    ├── applyCheckpointToWorktree
    └── trimMessagesBeforeCheckpoint
```

### 7.2 Charles 会话持久化架构图

```
SessionManager (session.py)
    ├── 内存状态
    │   ├── _messages: dict[str, list[AgentMessage]]
    │   ├── _info: dict[str, SessionInfo]
    │   ├── _sorted_index: list[SessionInfo] (Stage 31.8 缓存)
    │   └── _index_dirty: bool
    ├── 持久化
    │   ├── agent_data/sessions/<session_id>.json (元信息 + 消息)
    │   ├── agent_data/sessions/sessions.index.json (索引)
    │   └── _atomic_write_json (tmp + os.replace)
    ├── 版本迁移
    │   ├── _SESSION_FILE_VERSION = 2
    │   ├── _SESSION_MIGRATIONS = {1: _migrate_session_v1_to_v2}
    │   └── _migrate_session_data (while 循环)
    ├── 加载
    │   ├── load_all (优先索引，回退 glob)
    │   ├── _load_index (索引快路径)
    │   └── _load_session_from_file (按需加载)
    ├── 更新
    │   ├── update (同步落盘 + 索引)
    │   ├── set_session_status (status/ended_at/exit_code)
    │   └── set_runtime_info (provider/model)
    ├── 查询
    │   ├── list_sessions (_index_dirty 排序)
    │   ├── get_messages
    │   └── get_info
    └── 清理
        ├── clear (删文件 + 更新索引)
        └── _evict_if_needed (LRU 清理)

FileLock (file_lock.py)
    ├── 目录锁 {file_path}.lock
    ├── _try_acquire (mkdir staging + rename)
    ├── _is_stale (10 秒 mtime 检测)
    └── _takeover_stale (rename aside + rmtree)

SessionState (state.py)
    ├── agent_data/state/<session_id>.json
    ├── _STATE_FILE_VERSION = 1
    ├── SessionState (todos/mode)
    ├── load_all_states (glob 扫描)
    └── clear_session_state (删文件)

server.py 启动恢复
    ├── _session_manager.load_all() (会话恢复)
    └── load_all_states() (状态恢复)
```

### 7.3 数据模型字段对比

| 字段 | Cline SessionRow | Charles SessionInfo | 说明 |
|------|-----------------|---------------------|------|
| sessionId / session_id | ✅ string | ✅ str | 会话 ID |
| source | ✅ string | ❌ | Cline 标识会话来源（cli/vscode/api） |
| pid | ✅ number | ❌ | Cline 进程 ID（用于 stale 检测） |
| startedAt / created_at | ✅ string (ISO) | ✅ float (timestamp) | 时间格式不同 |
| endedAt / ended_at | ✅ string \| null | ✅ float \| None | 时间格式不同 |
| exitCode / exit_code | ✅ number \| null | ✅ int \| None | 退出码 |
| status | ✅ SessionStatus | ✅ str | active/completed/failed/aborted |
| statusLock | ✅ number | ❌ | Cline OCC 乐观锁 |
| interactive | ✅ boolean | ❌ | Cline 交互模式标志 |
| provider | ✅ string | ✅ str | 模型供应商 |
| model | ✅ string | ✅ str | 模型名 |
| cwd | ✅ string | ❌ | Cline 工作目录 |
| workspaceRoot | ✅ string | ❌ | Cline 工作区根 |
| teamName | ✅ string \| null | ❌ | Cline 团队名 |
| enableTools | ✅ boolean | ❌ | Cline 工具启用标志 |
| enableSpawn | ✅ boolean | ❌ | Cline spawn 启用标志 |
| enableTeams | ✅ boolean | ❌ | Cline 团队启用标志 |
| parentSessionId | ✅ string \| null | ❌ | Cline 父会话 ID |
| parentAgentId | ✅ string \| null | ❌ | Cline 父 agent ID |
| agentId | ✅ string \| null | ❌ | Cline agent ID |
| conversationId | ✅ string \| null | ❌ | Cline 对话 ID |
| isSubagent | ✅ boolean | ❌ | Cline 子 agent 标志 |
| prompt | ✅ string \| null | ❌ | Cline 初始 prompt |
| metadata | ✅ Record \| null | ❌ | Cline 元数据（含 title） |
| hookPath | ✅ string | ❌ | Cline hook 脚本路径 |
| messagesPath | ✅ string \| null | ❌ | Cline 消息文件路径 |
| updatedAt | ✅ string | ❌（用 last_active） | Cline 更新时间 |
| title | ❌（在 metadata.title） | ✅ str | Charles 独立字段 |
| message_count | ❌（运行时计算） | ✅ int | Charles 独立字段 |
| last_active | ❌（用 updatedAt） | ✅ float | Charles 独立字段 |

**字段对比结论**：Cline `SessionRow` 26+ 字段，Charles `SessionInfo` 9 字段。Charles 缺失的 17+ 字段主要为多进程协作（pid/source/parentSessionId/parentAgentId/agentId/conversationId/isSubagent）、团队（teamName/enableSpawn/enableTeams）、工作区（cwd/workspaceRoot）、OCC（statusLock）相关，符合量化单进程场景的简化设计。
