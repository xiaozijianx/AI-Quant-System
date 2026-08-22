# Stage 6: P2 持久化与历史管理方案

> 覆盖范围：会话持久化（Phase S）、Checkpoint 机制（Phase T）、FileContextTracker（Phase W）
> 对标源码：Cline sdk/packages/core/src/services/storage/、apps/vscode/src/core/controller/checkpoints/、apps/vscode/src/core/context/context-tracking/
> 当前实现：agent/session.py、agent/file_lock.py、agent/checkpoint.py、agent/file_checkpoint.py、agent/file_context_tracker.py、agent/server.py、agent/runtime.py、static/js/ai-chat.js
> 优先级：P2（不阻塞主流程，但影响数据完整性、长期运行稳定性、用户体验）

---

## 总览

| 子任务 | 标题 | 来源 | 优先级 | 涉及文件 |
|--------|------|------|--------|----------|
| 6.1 | 会话版本迁移机制 | S6/S12 | P1 | agent/session.py |
| 6.2 | 会话 schema 字段补齐 | S2/S9 | P2 | agent/session.py |
| 6.3 | 会话 list 查询性能优化 | S8 | P2 | agent/session.py |
| 6.4 | Checkpoint git ref 持久化 | T3/T6 | P1 | agent/file_checkpoint.py |
| 6.5 | Checkpoint 回滚语义对齐 | T5 | P1 | agent/server.py、agent/file_checkpoint.py |
| 6.6 | Checkpoint 启用开关统一 | T8 | P2 | agent/server.py |
| 6.7 | FileContextTracker SSE 事件 | W11 | P2 | agent/file_context_tracker.py、agent/server.py、agent/runtime.py、static/js/ai-chat.js |
| 6.8 | FileContextTracker 操作类型语义对齐 | W3/W9 | P2 | agent/file_context_tracker.py |

---

## 6.1 会话版本迁移机制

### 任务背景

来源 Phase S #S6 / #S12。当前 `agent/session.py` 在加载会话文件时仅做版本号校验，版本不匹配直接丢弃数据：

```python
# agent/session.py L238-239
if data.get("version") != _SESSION_FILE_VERSION:
    logger.warning(f"会话文件 {path} 版本不兼容，跳过")
    return False
```

`_SESSION_FILE_VERSION = 1`（L54）。一旦未来升级 schema（如 6.2 补齐字段时升版本号），所有历史会话文件将无法加载，用户历史对话（研报、分析记录）全部丢失，无法平滑演进。

Cline 通过两层迁移机制保证 schema 升级不丢数据：
- `state-migrations.ts` 提供 6 个跨存储位置/格式的迁移函数（workspace→global、customInstructions→rules 文件等）
- `sqlite-db.ts` L272-337 `LEGACY_MIGRATIONS` 数组用 `ALTER TABLE` 为旧表添加新列，并对 `workspace_root` 做数据回填（`UPDATE sessions SET workspace_root = cwd WHERE workspace_root IS NULL`）
- `sqlite-db.ts` L348-381 `ensureSessionSchema` 在每次打开 DB 时自动检测列是否存在并执行迁移

### 目标

在 `agent/session.py` 实现版本迁移注册表模式，支持 `_SESSION_FILE_VERSION` 升级时平滑迁移旧数据，保留历史会话可加载。不照搬 Cline 的 SQL ALTER TABLE（我方用 JSON 而非 SQLite），而是用 Python 函数对 dict 做字段补齐/格式转换。

### 当前实现位置

- `agent/session.py:54` — `_SESSION_FILE_VERSION = 1`
- `agent/session.py:217-257` — `_load_session_from_file` 方法，L238-239 为版本校验逻辑
- `agent/session.py:172-179` — `_persist_session` 中 data dict 构建（写入 version 字段）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/db/sqlite-db.ts:272-337` — `LEGACY_MIGRATIONS` 数组定义
- Cline `third_party/cline/sdk/packages/shared/src/db/sqlite-db.ts:348-381` — `ensureSessionSchema` 自动检测+迁移
- Cline `third_party/cline/apps/vscode/src/core/storage/state-migrations.ts:1-80` — 跨存储迁移函数示例

### 修复步骤建议

**步骤 1：在 `agent/session.py` 常量区（L54 附近）增加迁移注册表**

在 `_SESSION_FILE_VERSION` 定义后增加迁移函数注册表。每个迁移函数接收旧 dict，返回新 dict（含更新后的 version 字段）：

```python
# 会话文件版本迁移注册表 — 对标 Cline LEGACY_MIGRATIONS + ensureSessionSchema
# key 为"源版本号"，value 为"将该版本迁移到下一版本"的函数
# 升级 _SESSION_FILE_VERSION 时，在此追加迁移函数
_SESSION_MIGRATIONS: dict[int, callable] = {
    # 示例（6.2 任务落地时启用）：
    # 1: _migrate_session_v1_to_v2,
}
```

**步骤 2：实现迁移函数骨架**

在文件中（建议在 `_load_session_from_file` 之前）增加迁移执行函数。保留原版本校验逻辑作为兜底：

```python
def _migrate_session_data(data: dict) -> dict | None:
    """将会话数据从其自带版本迁移到 _SESSION_FILE_VERSION

    对标 Cline ensureSessionSchema 的列检测+迁移逻辑。
    逐版本应用迁移函数，无对应迁移路径时返回 None。

    Args:
        data: 从 JSON 加载的原始 dict

    Returns:
        迁移后的 dict；无迁移路径时返回 None（调用方应跳过该文件）
    """
    version = data.get("version", 1)
    while version < _SESSION_FILE_VERSION:
        migrator = _SESSION_MIGRATIONS.get(version)
        if migrator is None:
            return None
        data = migrator(data)
        version = data.get("version", version + 1)
    return data
```

**步骤 3：在 `_load_session_from_file` 中调用迁移**

修改 L238-239 的版本校验逻辑，保留原"版本不兼容跳过"语义作为迁移失败兜底：

```python
# 原逻辑：版本不匹配直接跳过
# 新逻辑：尝试迁移，迁移失败再跳过
data_version = data.get("version", 1)
if data_version != _SESSION_FILE_VERSION:
    migrated = _migrate_session_data(data)
    if migrated is None:
        logger.warning(f"会话文件 {path} 版本 {data_version} 无迁移路径，跳过")
        return False
    data = migrated
```

后续 L242-254 的 messages 解析和 SessionInfo 构建逻辑保持不变。

### 验证方法

1. 单元验证：手动构造一个 version=1 的旧格式 dict，调用 `_migrate_session_data`，确认返回的 dict 含 `version=_SESSION_FILE_VERSION` 且字段完整。
2. 集成验证：在 `agent_data/sessions/` 放一个 version 字段为旧值的会话文件，重启服务后调用 `GET /api/chat/sessions`，确认该会话被加载（而非跳过）且日志无"版本不兼容"告警。
3. 回归验证：现有 version=1 的会话文件正常加载，无字段丢失。

### 注意事项

- 不能死板照搬 Cline 的 SQL ALTER TABLE，我方用 JSON 持久化，迁移函数直接操作 dict 即可。
- 保留原 `_load_session_from_file` 的所有读取/锁逻辑，仅在版本校验处插入迁移调用。
- 当前 `_SESSION_FILE_VERSION=1` 暂无实际迁移函数，注册表为空，行为与现状等价；6.2 任务落地时添加 v1→v2 迁移函数。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback（迁移失败明确返回 None）。
- `agent/state.py` 也有类似的版本校验（L234-236），可参考本任务模式后续对齐，但本任务仅修改 `agent/session.py`。

---

## 6.2 会话 schema 字段补齐

### 任务背景

来源 Phase S #S2 / #S9。当前 `SessionInfo` 仅 5 个业务字段：

```python
# agent/session.py L65-73
@dataclass
class SessionInfo:
    """会话元信息"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    message_count: int = 0
    title: str = ""
```

Cline `SessionRecord`（sqlite-session-store.ts L83-122）持久化 27 字段，包括生命周期（`status`/`ended_at`/`exit_code`）、运行时（`provider`/`model`/`cwd`/`workspace_root`）、团队/子代理等。我的实现缺少 `status`/`provider`/`model`/`ended_at`/`exit_code`，导致：
- 无法区分"运行中/已结束/失败"的会话，前端无法做状态过滤
- 重启后无法恢复"上次用什么模型"
- 无会话结束记录

### 目标

在 `SessionInfo` 中补齐 `status`、`provider`、`model`、`ended_at`、`exit_code` 字段，并同步更新持久化/加载逻辑。不复刻全部 27 字段，保留量化场景所需子集（无团队/子代理需求）。

### 当前实现位置

- `agent/session.py:65-73` — `SessionInfo` dataclass 定义
- `agent/session.py:172-179` — `_persist_session` 中 data dict 构建（仅写入 5 字段 + version）
- `agent/session.py:243-249` — `_load_session_from_file` 中 SessionInfo 构建（仅读取 5 字段）
- `agent/session.py:285-311` — `update` 方法（更新 last_active/message_count/title）
- `agent/session.py:341-343` — `get_info` 方法

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/storage/sqlite-session-store.ts:83-122` — `SessionRecord` 定义（27 字段）
- Cline `third_party/cline/sdk/packages/shared/src/db/sqlite-db.ts:184-214` — sessions 表 schema（含 status/ended_at/exit_code/provider/model）
- Cline `third_party/cline/sdk/packages/shared/src/db/sqlite-db.ts:272-337` — `LEGACY_MIGRATIONS` 为旧表添加新列的迁移

### 修复步骤建议

**步骤 1：扩展 `SessionInfo` dataclass（L65-73）**

保留原有 5 字段，追加新字段（均带默认值，向后兼容旧文件）：

```python
@dataclass
class SessionInfo:
    """会话元信息 — 对标 Cline SessionRecord（量化场景子集）"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    message_count: int = 0
    title: str = ""
    # 以下为 Stage 6.2 新增字段 — 对标 Cline SessionRecord
    status: str = "active"        # active/completed/failed/aborted
    provider: str = ""            # 模型供应商标识（如 openai/dashscope）
    model: str = ""               # 模型名（如 qwen-max）
    ended_at: float | None = None  # 会话结束时间戳，None 表示未结束
    exit_code: int | None = None   # 会话退出码，None 表示未结束
```

**步骤 2：扩展 `_persist_session` 的 data dict（L172-179）**

在原有字段后追加新字段写入：

```python
data = {
    "version": _SESSION_FILE_VERSION,
    "session_id": session_id,
    "created_at": info.created_at,
    "last_active": info.last_active,
    "title": info.title,
    # Stage 6.2 新增字段
    "status": info.status,
    "provider": info.provider,
    "model": info.model,
    "ended_at": info.ended_at,
    "exit_code": info.exit_code,
    "messages": [_message_to_dict(m) for m in messages],
}
```

**步骤 3：扩展 `_load_session_from_file` 的 SessionInfo 构建（L243-249）**

保留原字段读取，追加新字段读取（用 `.get()` 兜底旧文件无此字段的情况）：

```python
info = SessionInfo(
    session_id=session_id,
    created_at=data.get("created_at", time.time()),
    last_active=data.get("last_active", time.time()),
    title=data.get("title", ""),
    message_count=len(messages),
    status=data.get("status", "active"),
    provider=data.get("provider", ""),
    model=data.get("model", ""),
    ended_at=data.get("ended_at"),
    exit_code=data.get("exit_code"),
)
```

**步骤 4：增加会话状态管理方法**

在 `SessionManager` 中（建议在 `update` 方法之后）增加状态更新方法：

```python
def set_session_status(
    self,
    session_id: str,
    status: str,
    exit_code: int | None = None,
) -> None:
    """更新会话状态 — 对标 Cline SessionRecord.status 更新

    Args:
        session_id: 会话 ID
        status: 新状态（active/completed/failed/aborted）
        exit_code: 退出码（仅在 ended 状态时设置）
    """
    info = self._info.get(session_id)
    if info is None:
        return
    info.status = status
    if status in ("completed", "failed", "aborted"):
        info.ended_at = time.time()
        if exit_code is not None:
            info.exit_code = exit_code
    self._index_dirty = True
    self._persist_session(session_id)

def set_runtime_info(
    self,
    session_id: str,
    provider: str,
    model: str,
) -> None:
    """记录会话使用的模型供应方 — 对标 Cline SessionRecord.provider/model"""
    info = self._info.get(session_id)
    if info is None:
        return
    info.provider = provider
    info.model = model
    self._persist_session(session_id)
```

**步骤 5：在 `update` 方法（L285-311）中可选填充 provider/model**

保留原 update 逻辑，在更新 last_active 后不动 provider/model（由 `set_runtime_info` 显式设置）。

### 验证方法

1. 字段持久化验证：创建会话后调用 `set_session_status` 和 `set_runtime_info`，检查 `agent_data/sessions/<id>.json` 文件含完整字段。
2. 向后兼容验证：保留一个旧格式（仅 5 字段）的会话文件，重启服务后确认能加载，新字段取默认值（status="active"、provider="" 等）。
3. 前端列表验证：`GET /api/chat/sessions` 返回的 SessionInfo 列表含新字段，前端可按 status 过滤。

### 注意事项

- 保留原 `update`/`clear`/`list_sessions` 等方法逻辑，仅追加字段和方法，不改动原有控制流。
- 6.1 的迁移机制落地后，可在 v1→v2 迁移函数中为旧文件补 `status="active"` 等默认值；本任务先保证新写入文件含新字段，旧文件靠 `.get(default)` 兜底。
- 不复刻 Cline 的 `parent_session_id`/`team_name` 等团队/子代理字段（量化场景单 agent 无需求）。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback。

---

## 6.3 会话 list 查询性能优化

### 任务背景

来源 Phase S #S8。当前启动时 `load_all()` 用 `glob("*.json")` 扫描整个目录并逐个打开解析 JSON，O(n) 文件 IO：

```python
# agent/session.py L199-215
def load_all(self) -> int:
    count = 0
    for path in self._persist_dir.glob("*.json"):
        session_id = path.stem
        if self._load_session_from_file(session_id, path):
            count += 1
    ...
```

每个会话文件含完整 messages 列表（可能 MB 级），N 个会话需 N 次文件打开 + N 次 JSON 解析。会话数多时（如 100+）启动明显较慢。

Cline `FileSessionPersistenceAdapter.listSessions()` 读单个 `sessions.index.json` 文件，`Object.values` + `sort` + `slice`，单文件读取 + 内存排序，启动开销恒定。

### 目标

增加 `sessions.index.json` 索引文件，启动时仅读索引恢复 `SessionInfo` 列表（不加载 messages），按需 `load_session()` 加载完整消息。保留现有 `_sorted_index` 内存缓存（L122-127）作为运行时优化。

### 当前实现位置

- `agent/session.py:199-215` — `load_all()` glob 扫描
- `agent/session.py:217-257` — `_load_session_from_file` 加载完整 messages
- `agent/session.py:259-275` — `load_session` 按需加载单个会话
- `agent/session.py:122-127` — `_sorted_index` + `_index_dirty` 内存缓存
- `agent/session.py:325-339` — `list_sessions()` 内存缓存查询
- `agent/session.py:133-143` — `_ensure_persist_dir` + `_session_file_path`

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/session/services/file-session-service.ts` — `FileSessionPersistenceAdapter` 读单个 `sessions.index.json` 实现 listSessions
- Cline `third_party/cline/sdk/packages/core/src/session/services/persistence-service.ts` — 索引文件维护逻辑

### 修复步骤建议

**步骤 1：增加索引文件路径辅助方法**

在 `_session_file_path`（L137-143）之后增加索引文件路径方法：

```python
def _index_file_path(self) -> Path:
    """获取会话索引文件路径 — 对标 Cline sessions.index.json"""
    return self._persist_dir / "sessions.index.json"
```

**步骤 2：增加索引读写方法**

在 `_persist_session`（L157-188）之后增加索引持久化方法。索引仅存 SessionInfo 字段（不含 messages），保证单文件小且读取快：

```python
def _persist_index(self) -> None:
    """持久化会话索引到 sessions.index.json — 对标 Cline index.json

    索引内容为所有 SessionInfo 的精简 dict（不含 messages）。
    用 FileLock 保护写入，避免多进程并发写冲突。
    """
    from agent.file_lock import FileLock
    index_path = self._index_file_path()
    data = {
        "version": _SESSION_FILE_VERSION,
        "sessions": [
            {
                "session_id": info.session_id,
                "created_at": info.created_at,
                "last_active": info.last_active,
                "message_count": info.message_count,
                "title": info.title,
                "status": info.status,
                "provider": info.provider,
                "model": info.model,
                "ended_at": info.ended_at,
                "exit_code": info.exit_code,
            }
            for info in self._info.values()
        ],
    }
    try:
        with FileLock(index_path):
            self._atomic_write_json(index_path, data)
    except Exception as e:
        logger.error(f"持久化会话索引失败: {e}", exc_info=True)
```

**步骤 3：增加索引加载方法**

```python
def _load_index(self) -> bool:
    """从 sessions.index.json 加载会话索引 — 启动时调用

    仅恢复 SessionInfo（不加载 messages），按需 load_session() 加载消息。
    Returns:
        True 表示索引加载成功，False 表示索引不存在或损坏（需回退 glob 扫描）
    """
    from agent.file_lock import FileLock
    index_path = self._index_file_path()
    if not index_path.exists():
        return False
    try:
        with FileLock(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        for s in data.get("sessions", []):
            session_id = s.get("session_id")
            if not session_id:
                continue
            # 仅当内存中无该会话时才创建（避免覆盖已加载的完整数据）
            if session_id in self._info:
                continue
            info = SessionInfo(
                session_id=session_id,
                created_at=s.get("created_at", time.time()),
                last_active=s.get("last_active", time.time()),
                message_count=s.get("message_count", 0),
                title=s.get("title", ""),
                status=s.get("status", "active"),
                provider=s.get("provider", ""),
                model=s.get("model", ""),
                ended_at=s.get("ended_at"),
                exit_code=s.get("exit_code"),
            )
            self._info[session_id] = info
            # messages 不加载，按需 load_session() 获取
            self._messages.setdefault(session_id, [])
        self._index_dirty = True
        return True
    except Exception as e:
        logger.warning(f"加载会话索引失败，将回退到 glob 扫描: {e}")
        return False
```

**步骤 4：修改 `load_all`（L199-215）优先用索引**

保留原 glob 扫描逻辑作为兜底（索引不存在或损坏时回退）：

```python
def load_all(self) -> int:
    """加载所有持久化的会话 — 启动时调用

    优先读取 sessions.index.json 索引（仅恢复 SessionInfo，不加载 messages），
    索引不存在或损坏时回退到 glob 扫描逐文件加载。
    """
    # 优先尝试索引加载
    if self._load_index():
        count = len(self._info)
        if count > 0:
            logger.info(f"已从索引恢复 {count} 个会话元信息（messages 按需加载）")
        return count
    # 回退到 glob 扫描（原逻辑）
    count = 0
    for path in self._persist_dir.glob("*.json"):
        if path.name == "sessions.index.json":
            continue
        session_id = path.stem
        if self._load_session_from_file(session_id, path):
            count += 1
    if count > 0:
        logger.info(f"已从磁盘恢复 {count} 个会话")
    # glob 加载完成后补写索引，下次启动走快路径
    if count > 0:
        self._persist_index()
    return count
```

**步骤 5：在 `_persist_session`（L157-188）末尾同步更新索引**

保留原会话文件写入逻辑，在末尾追加索引同步：

```python
# 原写入逻辑完成后，同步更新索引
self._persist_index()
```

**步骤 6：在 `clear`（L313-323）末尾同步更新索引**

```python
# 原删除持久化文件逻辑完成后，同步更新索引
self._persist_index()
```

**步骤 7：修改 `load_session`（L259-275）支持按需加载**

保留原逻辑（已在内存则跳过），确保从索引恢复的会话首次访问 messages 时从磁盘加载：

```python
def load_session(self, session_id: str) -> bool:
    """加载单个会话（按需加载）

    若会话已在内存中且有 messages 则跳过，
    否则从磁盘加载完整 messages。
    """
    # 已在内存且有 messages（非从索引恢复的空壳）则跳过
    if session_id in self._info and self._messages.get(session_id):
        return True
    path = self._session_file_path(session_id)
    if not path.exists():
        return False
    return self._load_session_from_file(session_id, path)
```

### 验证方法

1. 启动性能验证：在 `agent_data/sessions/` 准备 50+ 会话文件，对比优化前后启动时间（应从 O(n) 文件 IO 降为 1 次索引读取）。
2. 索引正确性验证：创建/更新/删除会话后，检查 `sessions.index.json` 内容与 `agent_data/sessions/` 实际文件一致。
3. 按需加载验证：从索引恢复后调用 `get_messages(sid)`，确认 messages 按需加载（首次调用触发磁盘读取）。
4. 兼容性验证：删除 `sessions.index.json` 后重启，确认回退到 glob 扫描并能重建索引。

### 注意事项

- 保留原 `load_all` 的 glob 扫描逻辑作为兜底，不删除。
- 保留 `_sorted_index` + `_index_dirty` 内存缓存（L122-127），索引加载后仍走该缓存。
- 索引文件用 FileLock 保护，与会话文件锁机制一致（对标 Cline FileLock）。
- glob 扫描时跳过 `sessions.index.json`，避免误把它当作会话文件解析。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback（索引损坏时回退 glob 是明确逻辑，不算 fallback）。

---

## 6.4 Checkpoint git ref 持久化

### 任务背景

来源 Phase T #T3 / #T6。当前 `agent/file_checkpoint.py` 的 `_git_stash_create` 用三步法（`git add -A` → `git stash create` → `git reset -q`）生成悬空 commit（dangling），无 `git update-ref`：

```python
# agent/file_checkpoint.py L376-384
create_result = subprocess.run(
    ["git", "stash", "create"],
    cwd=str(workspace_root),
    ...
)
```

git 默认 30 天后清理悬空对象（`gc.reflogExpire` / `gc.pruneExpire`），长期运行的会话回滚到早期 checkpoint 时 `git checkout <commit>` 会失败（`fatal: invalid reference`）。

Cline `checkpoint-hooks.ts` L236-238 将 stash commit 写入私有 ref 命名空间 `refs/cline/checkpoints/{sessionId}/{runCount}`，使对象永久可达（GC-safe），且不污染用户 `git stash list`。

### 目标

在 `_git_stash_create` 成功后调用 `git update-ref refs/agent/checkpoints/{session_id}/{checkpoint_id} <commit>`，保证 stash commit GC-safe。回滚时仍用裸 commit（兼容现有逻辑），但元信息中可记录 ref 路径供清理使用。

### 当前实现位置

- `agent/file_checkpoint.py:339-429` — `_git_stash_create` 三步法实现
- `agent/file_checkpoint.py:376-384` — `git stash create` 调用
- `agent/file_checkpoint.py:404-410` — stash create 返回 commit hash 或空字符串
- `agent/file_checkpoint.py:175-226` — `save_checkpoint` 调用 `_git_stash_create` 并构建 CheckpointRef
- `agent/file_checkpoint.py:84-125` — `CheckpointRef` dataclass（含 stash_commit 字段）
- `agent/file_checkpoint.py:266-274` — `clear_session` 清理元信息（不清理 git ref）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/hooks/checkpoint-hooks.ts:217-238` — `git stash create` + `git update-ref refs/cline/checkpoints/{sid}/{run} <ref>`
- Cline `third_party/cline/sdk/packages/core/src/hooks/checkpoint-hooks.ts:102-121` — `deleteCheckpointRefs` session 删除时清理 ref
- Cline `third_party/cline/sdk/packages/core/src/session/checkpoint-restore.ts:173-177` — restore 前用 `git cat-file -e <ref>^{commit}` 验证 commit 存在

### 修复步骤建议

**步骤 1：增加 ref 路径生成方法**

在 `FileCheckpointManager` 的内部方法区（L505 附近，`_session_file_path` 之前）增加：

```python
def _checkpoint_ref_name(
    self,
    session_id: str,
    checkpoint_id: str,
) -> str:
    """生成 git 私有 ref 路径 — 对标 Cline refs/cline/checkpoints/{sid}/{run}

    用 refs/agent/checkpoints/ 命名空间与 Cline 区分，
    避免与用户 stash list（refs/stash）冲突。

    Args:
        session_id: 会话 ID
        checkpoint_id: checkpoint ID

    Returns:
        ref 路径字符串，如 refs/agent/checkpoints/sess1/ckpt_xxx
    """
    safe_session = os.path.basename(session_id)
    safe_ckpt = os.path.basename(checkpoint_id)
    return f"refs/agent/checkpoints/{safe_session}/{safe_ckpt}"
```

**步骤 2：在 `_git_stash_create`（L339-429）成功路径中调用 update-ref**

保留原三步法逻辑不变，仅在 L404-410 的 commit hash 非空分支中追加 update-ref 调用。由于 `_git_stash_create` 当前无 checkpoint_id 参数，需调整签名或在 `save_checkpoint` 中调用。

推荐方案：在 `save_checkpoint`（L175-226）中获得 stash_commit 后调用 update-ref，保留 `_git_stash_create` 的单一职责（仅生成 commit）。

修改 `save_checkpoint`（L201-220 附近）：

```python
workspace_root = Path(workspace_root).resolve()
stash_commit = self._git_stash_create(workspace_root)
if stash_commit is None:
    return None

file_paths = self._extract_file_paths(tool_name, tool_input)
checkpoint_id = self._generate_checkpoint_id(session_id, tool_call_id)

# Stage 6.4 新增：将 stash commit 注册到私有 ref，保证 GC-safe
# 对标 Cline checkpoint-hooks.ts L236-238 git update-ref
if stash_commit:  # 空字符串表示无变更，无需 ref
    ref_name = self._checkpoint_ref_name(session_id, checkpoint_id)
    if not self._git_update_ref(workspace_root, ref_name, stash_commit):
        # update-ref 失败不阻塞 checkpoint 创建，仅记录告警
        # stash commit 仍为悬空对象，回滚仍可用（30 天内）
        logger.warning(
            "FileCheckpoint: update-ref 失败，stash commit 仍为悬空对象: %s",
            stash_commit[:8],
        )

ref = CheckpointRef(
    checkpoint_id=checkpoint_id,
    session_id=session_id,
    tool_call_id=tool_call_id,
    tool_name=tool_name,
    stash_commit=stash_commit,
    workspace_root=str(workspace_root),
    file_paths=file_paths,
    description=description or f"before {tool_name} tool",
)
```

**步骤 3：增加 `_git_update_ref` 方法**

在 `_git_stash_create`（L429）之后增加：

```python
def _git_update_ref(
    self,
    workspace_root: Path,
    ref_name: str,
    commit: str,
) -> bool:
    """执行 git update-ref 将 commit 注册为私有 ref — 对标 Cline update-ref

    保证 stash commit 永久可达，避免被 git gc 回收。
    私有 ref 不污染用户 git stash list（仅 refs/stash 影响 stash list）。

    Args:
        workspace_root: 工作区根目录
        ref_name: ref 路径（如 refs/agent/checkpoints/sess1/ckpt_xxx）
        commit: stash commit hash

    Returns:
        是否成功
    """
    try:
        result = subprocess.run(
            ["git", "update-ref", ref_name, commit],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            logger.debug(
                "FileCheckpoint: git update-ref 失败: %s",
                result.stderr.strip()[:200],
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("FileCheckpoint: git update-ref 超时")
        return False
    except FileNotFoundError:
        logger.warning("FileCheckpoint: 未找到 git 命令")
        return False
    except Exception as e:
        logger.warning("FileCheckpoint: git update-ref 异常: %s", e)
        return False
```

**步骤 4：在 `clear_session`（L266-274）中清理 git ref**

保留原删除元信息文件逻辑，追加 git ref 清理。需遍历该 session 的所有 CheckpointRef 调用 `git update-ref -d`：

```python
def clear_session(self, session_id: str) -> None:
    """清除会话的所有 checkpoint 元信息和 git ref — 对标 Cline deleteCheckpointRefs"""
    # 先收集需要清理的 ref（在删除缓存前）
    refs = self._cache.get(session_id, [])
    # 按 workspace_root 分组清理 ref
    if refs:
        workspace_groups: dict[str, list[str]] = {}
        for ref in refs:
            if ref.stash_commit:  # 空字符串 commit 无 ref，跳过
                ref_name = self._checkpoint_ref_name(session_id, ref.checkpoint_id)
                workspace_groups.setdefault(ref.workspace_root, []).append(ref_name)
        for workspace_root, ref_names in workspace_groups.items():
            for ref_name in ref_names:
                self._git_delete_ref(Path(workspace_root), ref_name)

    # 原逻辑：删除内存缓存和持久化文件
    self._cache.pop(session_id, None)
    path = self._session_file_path(session_id)
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.warning("FileCheckpoint: 删除 session 文件失败: %s", e)
```

**步骤 5：增加 `_git_delete_ref` 方法**

```python
def _git_delete_ref(
    self,
    workspace_root: Path,
    ref_name: str,
) -> bool:
    """执行 git update-ref -d 删除私有 ref — 对标 Cline deleteCheckpointRefs

    Args:
        workspace_root: 工作区根目录
        ref_name: ref 路径

    Returns:
        是否成功
    """
    try:
        result = subprocess.run(
            ["git", "update-ref", "-d", ref_name],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug("FileCheckpoint: git update-ref -d 失败: %s", e)
        return False
```

### 验证方法

1. ref 创建验证：创建 checkpoint 后在 workspace 执行 `git for-each-ref refs/agent/checkpoints/`，确认 ref 存在且指向 stash commit。
2. GC 安全验证：创建 checkpoint 后执行 `git gc --prune=now --aggressive`，再调用 `git cat-file -e <commit>^{commit}`，确认 commit 仍存在（未被回收）。
3. 回滚兼容验证：ref 创建后调用 `/api/chat/rollback_file`，确认 `git checkout <commit> -- <paths>` 仍正常工作（裸 commit 和 ref 都可用）。
4. 清理验证：调用 `clear_session` 后执行 `git for-each-ref refs/agent/checkpoints/<sid>/`，确认 ref 已删除。

### 注意事项

- 保留原 `_git_stash_create` 三步法逻辑不变，仅在外部追加 update-ref 调用。
- update-ref 失败不阻塞 checkpoint 创建（stash commit 仍可用，仅 30 天内有效），这是明确逻辑而非 fallback。
- ref 命名空间用 `refs/agent/checkpoints/` 而非 Cline 的 `refs/cline/checkpoints/`，与项目命名风格一致。
- 空字符串 commit（工作区无变更）无需创建 ref，跳过即可。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback。

---

## 6.5 Checkpoint 回滚语义对齐

### 任务背景

来源 Phase T #T5。当前 `/rollback` 端点（消息回滚）和 `/rollback_file` 端点（文件回滚）分离，用户需分别调用：

```python
# agent/server.py L1193-1266 /rollback 端点
# 仅恢复消息列表，不调用文件回滚
cp = manager.rollback_to_checkpoint(session_id, checkpoint_id)
restored_messages = [_dict_to_message(m) for m in cp.messages]
_session_manager.update(session_id, restored_messages)
runtime.abort("rollback to checkpoint")
CompactionStateManager().clear(session_id)
```

且文件回滚（`agent/file_checkpoint.py` L228-254 `restore_checkpoint`）仅 `git checkout <commit> -- <paths>` 还原指定文件，非全量恢复。

Cline `checkpoint-restore.ts` L161-189 `applyCheckpointToWorktree` 做全量恢复：`git reset --hard` + `git clean -fd` + `git stash apply <ref>`，并配合 `trimMessagesToCheckpoint`（L106-112）截断消息列表，三者原子完成。

### 目标

在 `/rollback` 端点中联动调用文件回滚（若 `AGENT_ENABLE_FILE_CHECKPOINT` 启用），实现"消息 + 文件"组合恢复。短期保留按 file_paths 部分恢复的优化路径（避免覆盖用户在工具外手动修改的文件），中期可扩展全量恢复模式。

### 当前实现位置

- `agent/server.py:1193-1266` — `/rollback` 端点（仅消息回滚）
- `agent/server.py:1240-1254` — 停止 runtime + 清理压缩状态
- `agent/server.py:1328-1369` — `/rollback_file` 端点（仅文件回滚）
- `agent/checkpoint.py:192-229` — `rollback_to_checkpoint` 消息恢复
- `agent/file_checkpoint.py:228-254` — `restore_checkpoint` 文件恢复
- `agent/file_checkpoint.py:431-485` — `_git_checkout_files` 部分文件还原

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/session/checkpoint-restore.ts:161-189` — `applyCheckpointToWorktree`（reset --hard + clean -fd + stash apply）
- Cline `third_party/cline/sdk/packages/core/src/session/checkpoint-restore.ts:106-112` — `trimMessagesToCheckpoint` 消息截断
- Cline `third_party/cline/sdk/packages/core/src/session/session-versioning-service.ts:200-224` — fork session 模式（长期目标，本任务不实现）

### 修复步骤建议

**步骤 1：在 `/rollback` 端点（L1193-1266）中联动文件回滚**

保留原消息回滚逻辑，在消息恢复成功后、返回响应前，追加文件回滚调用。仅当 `AGENT_ENABLE_FILE_CHECKPOINT` 启用时触发：

```python
@router.post("/rollback")
async def rollback_to_checkpoint(request: Request):
    """回滚到检查点 — Phase 21 新增，Stage 6.5 增加文件联动

    回滚后:
        1. 从检查点恢复会话消息列表
        2. 清除该检查点之后的所有检查点
        3. 若 AGENT_ENABLE_FILE_CHECKPOINT 启用，联动回滚文件状态
        4. 前端重新加载会话消息
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "message": "请求体不是有效的 JSON"}

    session_id = body.get("session_id", "")
    checkpoint_id = body.get("checkpoint_id", "")

    if not session_id or not checkpoint_id:
        return {"status": "error", "message": "session_id 和 checkpoint_id 不能为空"}

    from agent.checkpoint import get_checkpoint_manager
    from agent.session import _dict_to_message
    manager = get_checkpoint_manager()

    # 执行消息回滚（原逻辑）
    cp = manager.rollback_to_checkpoint(session_id, checkpoint_id)
    if cp is None:
        return {"status": "error", "message": "检查点不存在或会话不匹配"}

    # 恢复会话消息列表（原逻辑）
    try:
        restored_messages = [_dict_to_message(m) for m in cp.messages]
        _session_manager.update(session_id, restored_messages)
        logger.info(
            f"Phase 21: 会话 {session_id} 已回滚到检查点 {checkpoint_id} "
            f"(恢复 {len(restored_messages)} 条消息)"
        )
    except Exception as e:
        logger.error(f"Phase 21: 恢复会话消息失败: {e}", exc_info=True)
        return {"status": "error", "message": f"恢复会话消息失败: {e}"}

    # 停止该会话正在运行的 runtime（原逻辑）
    runtime = _active_runtimes.pop(session_id, None)
    if runtime is not None:
        try:
            runtime.abort("rollback to checkpoint")
            logger.info(f"Phase 21: 已中止会话 {session_id} 的活跃 runtime")
        except Exception as e:
            logger.warning(f"Phase 21: 中止 runtime 时出错: {e}")

    # 清理该会话的上下文压缩状态（原逻辑）
    try:
        CompactionStateManager().clear(session_id)
        logger.info(f"Phase 21: 已清理会话 {session_id} 的压缩状态")
    except Exception as e:
        logger.warning(f"Phase 21: 清理压缩状态失败: {e}")

    # Stage 6.5 新增：联动文件回滚 — 对标 Cline applyCheckpointToWorktree
    # 仅当 AGENT_ENABLE_FILE_CHECKPOINT 启用时触发
    # 用消息检查点的 tool_call_id 查找对应的文件 checkpoint
    file_rollback_result = None
    if os.environ.get("AGENT_ENABLE_FILE_CHECKPOINT", "").lower() in ("1", "true", "yes"):
        try:
            file_rollback_result = _try_rollback_file_for_message_checkpoint(
                session_id, cp.tool_call_id,
            )
        except Exception as e:
            logger.warning(f"Stage 6.5: 联动文件回滚失败: {e}")

    return {
        "status": "ok",
        "message": f"已回滚到检查点（工具 {cp.tool_name} 执行前）",
        "checkpoint": {
            "checkpoint_id": cp.checkpoint_id,
            "tool_name": cp.tool_name,
            "created_at": cp.created_at,
            "description": cp.description,
            "message_count": len(cp.messages),
        },
        "file_rollback": file_rollback_result,
    }
```

**步骤 2：增加联动文件回滚辅助函数**

在 `/rollback` 端点之前（L1193 之前）增加辅助函数。用消息检查点的 `tool_call_id` 查找文件 checkpoint（两者按同一 tool_call_id 关联）：

```python
def _try_rollback_file_for_message_checkpoint(
    session_id: str,
    tool_call_id: str,
) -> dict | None:
    """联动文件回滚 — 根据 tool_call_id 查找文件 checkpoint 并回滚

    对标 Cline applyCheckpointToWorktree 的"消息+文件"组合恢复。
    消息检查点和文件检查点都按 tool_call_id 索引，可关联查找。

    Args:
        session_id: 会话 ID
        tool_call_id: 触发检查点的工具调用 ID

    Returns:
        回滚结果 dict，None 表示无对应文件 checkpoint
    """
    from agent.file_checkpoint import get_checkpoint_manager
    file_manager = get_checkpoint_manager()
    # 列出该 session 所有文件 checkpoint，找 tool_call_id 匹配的
    refs = file_manager.list_checkpoints(session_id)
    target_ref = None
    for ref in refs:
        if ref.tool_call_id == tool_call_id:
            target_ref = ref
            break
    if target_ref is None:
        return None
    ok = file_manager.restore_checkpoint(target_ref.checkpoint_id)
    return {
        "rolled_back": ok,
        "checkpoint_id": target_ref.checkpoint_id,
        "file_count": len(target_ref.file_paths),
    }
```

**步骤 3：（可选中期优化）为 `restore_checkpoint` 增加全量恢复模式**

保留原 `git checkout <commit> -- <paths>` 部分恢复作为默认，增加 `full_restore` 参数支持 Cline 的 `reset --hard + clean -fd` 全量恢复。本步骤为可选，默认不启用全量恢复（避免破坏用户在工具外手动修改的文件）：

```python
def restore_checkpoint(
    self,
    checkpoint_id: str,
    full_restore: bool = False,
) -> bool:
    """回滚到指定 checkpoint — 对标 Cline restoreCheckpoint

    Args:
        checkpoint_id: checkpoint ID
        full_restore: True 时用 git reset --hard + clean -fd 全量恢复
                      （对标 Cline applyCheckpointToWorktree，破坏性）
                      False 时仅还原 file_paths 中的文件（默认，安全）

    Returns:
        是否回滚成功
    """
    ref = self._find_checkpoint(checkpoint_id)
    if ref is None:
        logger.warning("FileCheckpoint: checkpoint %s 不存在", checkpoint_id)
        return False

    workspace_root = Path(ref.workspace_root)
    if not workspace_root.exists():
        logger.error("FileCheckpoint: 工作区目录不存在: %s", workspace_root)
        return False

    if full_restore:
        # 全量恢复模式 — 对标 Cline reset --hard + clean -fd + stash apply
        success = self._git_full_restore(workspace_root, ref.stash_commit)
    else:
        # 部分恢复模式（原逻辑）— 仅还原 file_paths 中的文件
        success = self._git_checkout_files(workspace_root, ref.stash_commit, ref.file_paths)

    if success:
        logger.info(
            "FileCheckpoint: 已回滚 checkpoint %s (mode=%s, files=%d)",
            checkpoint_id,
            "full" if full_restore else "partial",
            len(ref.file_paths),
        )
    return success
```

**步骤 4：增加 `_git_full_restore` 方法（可选）**

```python
def _git_full_restore(
    self,
    workspace_root: Path,
    stash_commit: str,
) -> bool:
    """全量恢复工作区 — 对标 Cline applyCheckpointToWorktree

    依次执行:
        1. git reset --hard（丢弃当前工作区所有修改）
        2. git clean -fd（删除未跟踪文件和目录）
        3. git stash apply <commit>（应用 stash 恢复工作区）

    警告: 破坏性操作，会丢弃用户在工具外手动修改的文件。

    Args:
        workspace_root: 工作区根目录
        stash_commit: stash commit hash（空字符串表示无变更，跳过）

    Returns:
        是否恢复成功
    """
    if not stash_commit:
        logger.debug("FileCheckpoint: stash_commit 为空，跳过全量恢复")
        return True
    try:
        # 步骤 1: reset --hard
        r1 = subprocess.run(
            ["git", "reset", "--hard"],
            cwd=str(workspace_root),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if r1.returncode != 0:
            logger.error("FileCheckpoint: git reset --hard 失败: %s", r1.stderr.strip()[:200])
            return False
        # 步骤 2: clean -fd
        r2 = subprocess.run(
            ["git", "clean", "-fd"],
            cwd=str(workspace_root),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if r2.returncode != 0:
            logger.error("FileCheckpoint: git clean -fd 失败: %s", r2.stderr.strip()[:200])
            return False
        # 步骤 3: stash apply
        r3 = subprocess.run(
            ["git", "stash", "apply", stash_commit],
            cwd=str(workspace_root),
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if r3.returncode != 0:
            logger.error("FileCheckpoint: git stash apply 失败: %s", r3.stderr.strip()[:200])
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("FileCheckpoint: 全量恢复超时")
        return False
    except Exception as e:
        logger.error("FileCheckpoint: 全量恢复异常: %s", e)
        return False
```

### 验证方法

1. 联动验证：启用 `AGENT_ENABLE_FILE_CHECKPOINT`，执行一个写工具修改文件，调用 `/rollback`，确认消息和文件同时回滚（检查文件内容恢复到工具执行前）。
2. 无文件 checkpoint 兼容验证：未启用 `AGENT_ENABLE_FILE_CHECKPOINT` 时调用 `/rollback`，确认仅消息回滚，`file_rollback` 字段为 None，无异常。
3. tool_call_id 关联验证：确认联动回滚能正确定位到与消息检查点同一 tool_call_id 的文件 checkpoint。
4. 全量恢复验证（若启用）：调用 `restore_checkpoint(cp_id, full_restore=True)`，确认工作区完全恢复到 stash 时状态（含未跟踪文件被 clean）。
5. 部分恢复验证（默认）：调用 `restore_checkpoint(cp_id)`，确认仅 file_paths 中的文件被还原，其他文件不动。

### 注意事项

- 保留原 `/rollback` 端点的所有逻辑（消息恢复、runtime 停止、压缩状态清理），仅在返回前追加文件联动。
- 默认用部分恢复（`full_restore=False`），避免破坏用户在工具外手动修改的文件；全量恢复为可选模式。
- 不实现 Cline 的 fork session 模式（长期目标，本任务范围外）。
- 联动失败不阻塞消息回滚（消息已恢复成功），仅记录告警并在响应中返回 `file_rollback` 状态。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback。

---

## 6.6 Checkpoint 启用开关统一

### 任务背景

来源 Phase T #T8。当前 checkpoint 启用开关分散：

```python
# agent/server.py L417-421 CheckpointHook（消息快照）始终注册，无开关
from agent.checkpoint import CheckpointHook
runtime.register_hooks(CheckpointHook(
    session_id=session_id,
    session_manager=_session_manager,
))

# agent/server.py L427 FileCheckpointHook（文件快照）通过环境变量控制
if os.environ.get("AGENT_ENABLE_FILE_CHECKPOINT", "").lower() in ("1", "true", "yes"):
    ...
```

问题：
1. 消息 checkpoint 无开关，无法关闭，即使不需要回滚功能也会产生存储开销
2. 配置分散，用户需理解两套机制
3. Cline 用单一 `checkpoint.enabled` 配置统一控制（默认 false，opt-in）

### 目标

统一用 `AGENT_ENABLE_FILE_CHECKPOINT` 环境变量控制两类 checkpoint 的启用。为消息 checkpoint 增加开关（默认开启保持向后兼容），文件 checkpoint 保持现状。短期不引入新的 `AGENT_CHECKPOINT_MODE` 复合配置，避免增加用户配置复杂度。

### 当前实现位置

- `agent/server.py:415-421` — `CheckpointHook` 始终注册
- `agent/server.py:423-447` — `FileCheckpointHook` 通过 `AGENT_ENABLE_FILE_CHECKPOINT` 控制
- `agent/checkpoint.py:333-393` — `CheckpointHook` 类
- `agent/file_checkpoint.py:610-644` — `create_before_tool_checkpoint_hook`

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/types/config.ts:198-204` — `CoreCheckpointConfig`（enabled 默认 false）
- Cline `third_party/cline/sdk/packages/core/src/services/local-runtime-bootstrap.ts:419-429` — `checkpoint.enabled === true` 时注册 hook

### 修复步骤建议

**步骤 1：为消息 checkpoint 增加环境变量开关**

修改 `agent/server.py` L415-421 的 `CheckpointHook` 注册逻辑，保留默认开启行为，增加 `AGENT_ENABLE_MESSAGE_CHECKPOINT` 环境变量控制（未设置或非 "false"/"0"/"no" 时启用，保持向后兼容）：

```python
# Phase 21: 注册 CheckpointHook — 写工具执行前保存会话快照
# Stage 6.6: 增加 AGENT_ENABLE_MESSAGE_CHECKPOINT 开关，默认开启保持兼容
# 对标 Cline checkpoint.enabled 配置（Cline 默认 false，我方默认 true 保持兼容）
if os.environ.get("AGENT_ENABLE_MESSAGE_CHECKPOINT", "true").lower() not in ("0", "false", "no"):
    from agent.checkpoint import CheckpointHook
    runtime.register_hooks(CheckpointHook(
        session_id=session_id,
        session_manager=_session_manager,
    ))
else:
    logger.info(f"Stage 6.6: 消息 checkpoint 已通过 AGENT_ENABLE_MESSAGE_CHECKPOINT 关闭")
```

**步骤 2：保留 `FileCheckpointHook` 现有开关逻辑**

`agent/server.py` L423-447 的 `FileCheckpointHook` 注册逻辑保持不变（`AGENT_ENABLE_FILE_CHECKPOINT` 默认关闭）。仅补充注释说明与消息 checkpoint 的关系：

```python
# Phase 33.2: 注册 FileCheckpointHook — 写工具执行前保存工作区文件状态快照
# 对标 Cline shadow-git checkpoint，用 git stash create 捕获工作区状态
# 通过 AGENT_ENABLE_FILE_CHECKPOINT=1 环境变量启用，默认关闭以保持现有性能
# 与 AGENT_ENABLE_MESSAGE_CHECKPOINT 独立：消息 checkpoint 默认开启，文件 checkpoint 默认关闭
# 启用后可在 /api/chat/file_checkpoints 端点查询，/api/chat/rollback_file 回滚
if os.environ.get("AGENT_ENABLE_FILE_CHECKPOINT", "").lower() in ("1", "true", "yes"):
    ...  # 原逻辑不变
```

**步骤 3：（可选）增加复合配置说明**

在 `agent/server.py` 的环境变量读取区（建议在文件头部常量区或 `_register_runtime_hooks` 函数文档中）增加配置说明注释：

```python
# Stage 6.6: Checkpoint 启用开关说明
# ============================================
# AGENT_ENABLE_MESSAGE_CHECKPOINT: 消息快照 checkpoint 开关
#   - 默认: 开启（保持向后兼容）
#   - 设为 "0"/"false"/"no" 关闭
#   - 关闭后 /rollback 端点无法回滚消息（无 checkpoint 可用）
#
# AGENT_ENABLE_FILE_CHECKPOINT: 文件状态快照 checkpoint 开关
#   - 默认: 关闭（保持现有性能，避免无 git 仓库场景报错）
#   - 设为 "1"/"true"/"yes" 开启
#   - 开启后 /rollback_file 端点可回滚文件，且 /rollback 端点联动文件回滚（见 Stage 6.5）
#
# 两者独立控制，可组合使用:
#   - 都开启: 完整回滚能力（消息 + 文件）
#   - 仅消息（默认）: 回滚对话历史，不回滚文件
#   - 仅文件: 不常见，仅回滚文件修改
#   - 都关闭: 无回滚能力，最高性能
```

### 验证方法

1. 默认行为验证：不设置任何环境变量，确认消息 checkpoint 启用（写工具执行后 `/checkpoints` 返回非空），文件 checkpoint 关闭（`/file_checkpoints` 返回空）。
2. 关闭消息 checkpoint 验证：设置 `AGENT_ENABLE_MESSAGE_CHECKPOINT=false`，执行写工具后 `/checkpoints` 返回空。
3. 开启文件 checkpoint 验证：设置 `AGENT_ENABLE_FILE_CHECKPOINT=1`，执行写工具后 `/file_checkpoints` 返回非空。
4. 组合验证：同时设置两者，确认两类 checkpoint 都启用。
5. 回归验证：现有不设置环境变量的行为与优化前一致（消息 checkpoint 启用、文件 checkpoint 关闭）。

### 注意事项

- 保留 `FileCheckpointHook` 现有注册逻辑不变，仅修改 `CheckpointHook` 注册处。
- `AGENT_ENABLE_MESSAGE_CHECKPOINT` 默认开启（"true"），保持向后兼容，避免现有用户升级后突然失去回滚能力。
- 不引入 `AGENT_CHECKPOINT_MODE=message|file|both|off` 复合配置（增加用户配置复杂度，两个独立布尔开关更清晰）。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback。

---

## 6.7 FileContextTracker SSE 事件

### 任务背景

来源 Phase W #W11。当前工具执行后 `_file_context_tracker_hook` 仅调用 `self._file_tracker.save()` 持久化，不推送 SSE 事件：

```python
# agent/runtime.py L1010-1012
# 持久化 tracker 状态（每次工具调用后写盘，保证崩溃不丢数据）
self._file_tracker.save()
```

前端无法实时感知文件上下文变化，必须轮询 `GET /sessions/{id}/file_context`。`server.py` 的 SSE 事件清单（L232-235 `_sse_event` 调用）无 `file_context_updated` 事件，`ai-chat.js` 的 `_handleSSEEvent`（L483-515）也无对应 case。

注：Cline 也无此 SSE 事件（双方均缺失），本任务为体验增强而非对齐 Cline。

### 目标

在 `_file_context_tracker_hook` 末尾通过 SSE 事件队列推送 `file_context_updated` 事件，SSE 生成器订阅并 yield 给前端，前端实时刷新文件面板。事件载荷为 `tracker.get_state()` 精简视图。

### 当前实现位置

- `agent/runtime.py:903-1017` — `_file_context_tracker_hook` after_tool hook
- `agent/runtime.py:1012` — `self._file_tracker.save()` 持久化调用
- `agent/runtime.py:247-254` — `_file_tracker` 初始化 + hook 注册
- `agent/server.py:232-235` — `_sse_event` 函数
- `agent/server.py:625-900` — SSE 事件生成器（stream_chat 函数，含多个 yield 调用）
- `agent/server.py:820-830` — 现有 SSE 事件 yield 示例（todos_updated/mode_changed）
- `static/js/ai-chat.js:460-481` — `readSSEStream` 解析 SSE 数据
- `static/js/ai-chat.js:483-515` — `_handleSSEEvent` 事件分发

### 目标源代码位置

- Cline 无对应 SSE 事件（双方均缺失），本任务为体验增强
- 参考 Cline `third_party/cline/apps/vscode/src/core/context/context-tracking/FileContextTracker.ts` 的 tracker 设计
- 参考现有 SSE 事件实现：`agent/server.py:820-830`（todos_updated/mode_changed 推送模式）

### 修复步骤建议

**步骤 1：在 `AgentRuntime` 中增加 SSE 事件回调机制**

当前 `stream_chat` 函数（server.py L625-900）直接 yield SSE 事件，runtime 通过 hooks 间接交互。为支持 runtime 主动推送事件，需在 `AgentRuntime` 增加事件回调。

修改 `agent/runtime.py` 的 `__init__`（L247 附近），增加事件回调字段：

```python
# Stage 6.7 新增：SSE 事件回调列表 — runtime 主动推送事件给前端
# 由 server.py 的 stream_chat 函数注册回调，runtime 在 hook 中调用
self._sse_event_callbacks: list = []
```

增加回调注册方法（建议在 `register_hooks` 方法附近）：

```python
def register_sse_event_callback(self, callback) -> None:
    """注册 SSE 事件回调 — Stage 6.7 新增

    callback 签名: async def callback(event_type: str, data: dict) -> None
    server.py 的 stream_chat 函数注册回调，将事件放入 asyncio.Queue，
    SSE 生成器从队列读取并 yield。

    Args:
        callback: 异步事件回调函数
    """
    self._sse_event_callbacks.append(callback)
```

**步骤 2：在 `_file_context_tracker_hook`（L1010-1017）末尾推送事件**

保留原 `save()` 调用，追加 SSE 事件推送：

```python
            # 持久化 tracker 状态（每次工具调用后写盘，保证崩溃不丢数据）
            # 工具调用不是高频操作，性能影响可接受
            self._file_tracker.save()

            # Stage 6.7 新增：推送 file_context_updated SSE 事件
            # 对标 Cline 的实时事件推送，前端无需轮询 GET /file_context
            state = self._file_tracker.get_state()
            await self._emit_sse_event("file_context_updated", {
                "session_id": self.config.session_id,
                "state": state,
            })
```

**步骤 3：增加 `_emit_sse_event` 辅助方法**

在 `AgentRuntime` 中（建议在 `_file_context_tracker_hook` 之后）增加：

```python
async def _emit_sse_event(self, event_type: str, data: dict) -> None:
    """向所有注册的 SSE 回调推送事件 — Stage 6.7 新增

    回调失败不影响主流程（仅记录 debug 日志）。

    Args:
        event_type: 事件类型（如 file_context_updated）
        data: 事件数据
    """
    if not self._sse_event_callbacks:
        return
    for callback in self._sse_event_callbacks:
        try:
            await callback(event_type, data)
        except Exception as e:
            logger.debug("SSE 事件回调异常（已忽略）: %s", e)
```

**步骤 4：在 `server.py` 的 `stream_chat` 中注册回调并消费事件**

修改 `stream_chat` 函数（L625-900），在 runtime 创建后注册 SSE 回调，回调将事件放入 `asyncio.Queue`，SSE 生成器循环中从队列读取并 yield。

具体实现需根据现有 `stream_chat` 结构调整，伪代码如下：

```python
import asyncio

# 在 stream_chat 函数中，runtime 创建后
sse_queue = asyncio.Queue()

async def _runtime_sse_callback(event_type: str, data: dict) -> None:
    """runtime SSE 事件回调 — 将事件放入队列供 SSE 生成器消费"""
    await sse_queue.put({"type": event_type, **data})

runtime.register_sse_event_callback(_runtime_sse_callback)

# 在 SSE 生成器主循环中（yield token 等事件的位置），
# 增加从 sse_queue 非阻塞读取逻辑
async def _drain_sse_queue():
    """排空 SSE 队列，返回事件列表"""
    events = []
    while not sse_queue.empty():
        try:
            event = sse_queue.get_nowait()
            events.append(event)
        except asyncio.QueueEmpty:
            break
    return events

# 在每次 yield token/tool_call 等事件前后，调用 _drain_sse_queue() 并 yield
# 例如:
for event in await _drain_sse_queue():
    yield _sse_event(event["type"], event)
```

注：由于 `stream_chat` 的具体结构较复杂（含 token 流、工具调用、审批等），实际实现时需在关键事件循环点插入队列消费逻辑。建议在 `yield _sse_event("tool_output", ...)`（L740 附近）之后插入，因为 file_context_updated 事件由 after_tool hook 触发，发生在 tool_output 之后。

**步骤 5：在 `ai-chat.js` 的 `_handleSSEEvent`（L483-515）增加事件处理**

保留原事件分发逻辑，增加 `file_context_updated` case：

```javascript
_handleSSEEvent(data) {
    switch (data.type) {
        case 'phase':
            this._onPhase(data.phase);
            break;
        case 'token':
            this._onToken(data.text);
            break;
        case 'plan':
            this._onPlanEvent(data.text);
            break;
        case 'tool_call':
            this._onToolCall(data);
            break;
        case 'tool_output':
            this._onToolOutput(data);
            break;
        case 'todos_updated':
            this._onTodosUpdated(data.todos);
            break;
        case 'mode_changed':
            this._onModeChanged(data);
            break;
        case 'approval_request':
            this._onApprovalRequest(data);
            break;
        case 'file_context_updated':
            // Stage 6.7 新增：文件上下文更新事件
            this._onFileContextUpdated(data.state);
            break;
        case 'done':
            break;
        case 'error':
            this._addBlock({ type: 'error', text: data.text });
            break;
    }
},

_onFileContextUpdated(state) {
    // 文件上下文更新回调 — 刷新文件面板
    // state 结构: {read: [...], edited: [...], created: [...], deleted: [...]}
    // 触发文件面板刷新事件，由文件面板组件监听
    document.dispatchEvent(new CustomEvent('file-context-updated', {
        detail: { state: state }
    }));
    // 同时缓存最新状态，供面板打开时直接渲染
    this._lastFileContext = state;
},
```

### 验证方法

1. 事件推送验证：执行一个写工具（如 editor），在 SSE 流中确认收到 `file_context_updated` 事件，载荷含 `state.read`/`state.edited` 等字段。
2. 前端刷新验证：打开文件上下文面板，执行工具后确认面板自动刷新（无需手动刷新或轮询）。
3. 回归验证：未注册回调时（如非流式调用），`_emit_sse_event` 不抛异常，主流程正常。
4. 性能验证：工具调用频繁时，SSE 事件不阻塞主流程（回调异常仅记 debug 日志）。
5. 兼容验证：旧前端（未处理 `file_context_updated`）收到事件时静默忽略（switch default 无匹配 case 不报错）。

### 注意事项

- 保留原 `_file_context_tracker_hook` 的所有记录逻辑，仅在 `save()` 后追加事件推送。
- SSE 回调机制用列表+循环模式，支持多个回调（未来可扩展其他事件）。
- 回调失败不影响主流程（仅 debug 日志），避免 tracker 异常阻塞工具执行。
- `stream_chat` 的具体修改需根据现有结构调整，本方案给出伪代码框架，实际实现时需 Read 完整 `stream_chat` 函数后插入队列消费逻辑。
- 前端用 `CustomEvent` 分发，与现有组件解耦，文件面板组件监听 `file-context-updated` 事件。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback。

---

## 6.8 FileContextTracker 操作类型语义对齐

### 任务背景

来源 Phase W #W3 / #W9。当前 `FileContextTracker` 的操作类型枚举与 Cline 语义不等价，去重策略相反：

**操作类型差异（W3）：**
```python
# agent/file_context_tracker.py L57-63 — 按"什么操作"分类
OP_READ = "read"
OP_EDITED = "edited"
OP_CREATED = "created"
OP_DELETED = "deleted"
```
```typescript
// ContextTrackerTypes.ts L2-9 — 按"谁触发编辑"分类
record_source: "read_tool" | "user_edited" | "cline_edited" | "file_mentioned"
```
- 我方按操作类型（edited/created/deleted）分类，Cline 按触发者（user_edited/cline_edited）分类
- 我方无 `file_mentioned`（用户在 prompt 中提到文件）
- Cline 不区分 created/deleted（新建文件也归为 `cline_edited`）

**去重策略差异（W9）：**
```python
# agent/file_context_tracker.py L176-180 — 同 path+operation 去重，保留首次
for entry in self._entries:
    if entry.path == path_str and entry.operation == operation:
        return
```
```typescript
// FileContextTracker.ts L107-162 — 不去重，旧 entry 标记 stale
// 保留完整时间序列，可还原操作历史
```
- 我方去重，仅保留"该文件曾被该操作触达"的事实
- Cline 不去重，保留完整时间序列，支持按时间戳查询

### 目标

评估是否对齐 Cline 语义。结论：**保持现状，标注语义差异**。理由：
1. 我方无文件 watcher（服务端 agent 是唯一编辑者），无需区分 user_edited/cline_edited
2. 去重策略更适合压缩摘要场景（只需知道"哪些文件被读/改过"）
3. 操作类型按"什么操作"分类更适合前端审计需求

本任务在代码文档中明确标注语义差异，避免后续 phase 对比误判，并可选补充 `source` 字段为未来扩展预留。

### 当前实现位置

- `agent/file_context_tracker.py:57-63` — 操作类型常量定义
- `agent/file_context_tracker.py:70-88` — `FileContextEntry` dataclass
- `agent/file_context_tracker.py:134-192` — `record` 方法（含去重逻辑 L176-180）
- `agent/file_context_tracker.py:198-217` — `get_state` 精简视图
- `agent/file_context_tracker.py:219-222` — `get_entries` 完整记录
- `agent/file_context_tracker.py:1-38` — 模块 docstring

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/context/context-tracking/ContextTrackerTypes.ts:2-9` — `FileMetadataEntry`（record_source 枚举）
- Cline `third_party/cline/apps/vscode/src/core/context/context-tracking/FileContextTracker.ts:107-162` — `trackFileContext` 不去重 + stale 标记

### 修复步骤建议

**步骤 1：在模块 docstring（L1-38）补充语义差异说明**

保留原 docstring，在"Cline 参考位置"之前增加语义差异说明段落：

```python
"""文件上下文追踪器 — Phase 29.3 新增，对标 Cline FileContextTracker

记录会话期间所有被工具读取/编辑/创建/删除的文件路径，并持久化到磁盘。

...

语义差异说明（Stage 6.8 标注）:
    本实现与 Cline FileContextTracker 的设计目标不同:
        - Cline: 聚焦"过期检测"（stale detection），通过 chokidar 文件 watcher
          检测用户在 Cline 外部修改文件，避免 diff 编辑时上下文过期
        - 本仓库: 聚焦"活动日志"（activity logging），记录工具读写文件清单，
          用于压缩摘要和前端审计

    操作类型语义差异（W3）:
        - Cline: 按"谁触发编辑"分类（read_tool/user_edited/cline_edited/file_mentioned）
        - 本仓库: 按"什么操作"分类（read/edited/created/deleted）
        - 原因: 本仓库无文件 watcher，agent 是唯一编辑者，无需区分 user/cline 编辑
        - 影响: 本仓库的 edited 合并了 Cline 的 user_edited + cline_edited；
          created/deleted 在 Cline 中归为 cline_edited

    去重策略差异（W9）:
        - Cline: 不去重，旧 entry 标记 stale，保留完整时间序列
        - 本仓库: 同 path+operation 去重，保留首次记录
        - 原因: 压缩摘要场景只需"哪些文件被读/改过"，无需时间序列
        - 影响: 本仓库无法回答"该文件被编辑了几次"，但 JSON 体积更小

    保持现状的理由:
        - 服务端 agent 无外部编辑场景，stale detection 系列功能非必需
        - 去重策略更适合压缩摘要和前端审计需求
        - 操作类型按"什么操作"分类更直观
        - 若未来引入外部编辑场景，可补充 source 字段和 watchdog 文件监听

Cline 参考位置:
    - third_party/cline/apps/vscode/src/core/context/context-tracking/FileContextTracker.ts
    - third_party/cline/apps/vscode/src/core/context/context-tracking/ContextTrackerTypes.ts
"""
```

**步骤 2：在操作类型常量（L57-63）处补充注释**

保留原常量定义，增加与 Cline 的语义对照注释：

```python
# 文件操作类型常量 — 对标 Cline FileContextEntryOperation
# 语义差异（Stage 6.8 标注）:
#   - Cline 按"谁触发编辑"分类（read_tool/user_edited/cline_edited/file_mentioned）
#   - 本仓库按"什么操作"分类（read/edited/created/deleted）
#   - 本仓库无 file_mentioned（未追踪 prompt 中提到的文件）
#   - 本仓库无 user_edited（无文件 watcher，agent 是唯一编辑者）
#   - Cline 的 created 归为 cline_edited，本仓库单独分类
OP_READ = "read"          # 读取（read_files / list_files 等）— 对标 Cline read_tool
OP_EDITED = "edited"      # 编辑已存在文件（editor / apply_patch / file_write 覆盖）— 对标 Cline cline_edited
OP_CREATED = "created"    # 创建新文件（file_write 新建）— Cline 归为 cline_edited
OP_DELETED = "deleted"    # 删除文件（暂未使用，预留给未来 file_delete 工具）— Cline 无此概念

VALID_OPERATIONS = {OP_READ, OP_EDITED, OP_CREATED, OP_DELETED}
```

**步骤 3：在 `record` 方法（L134-192）的去重逻辑处补充注释**

保留原去重逻辑（L176-180）不变，增加注释说明与 Cline 的差异：

```python
with self._lock:
    # 同 path+operation 去重（保留首次记录的时间戳）
    # 语义差异（Stage 6.8 标注）:
    #   - Cline 不去重，旧 entry 标记 record_state="stale"，新 entry 标记 "active"
    #   - 本仓库去重，仅保留"该文件曾被该操作触达"的事实
    #   - 本仓库策略: JSON 体积小，前端展示清晰，适合压缩摘要场景
    #   - Cline 策略: 保留完整时间序列，支持按时间戳查询，适合 stale detection
    for entry in self._entries:
        if entry.path == path_str and entry.operation == operation:
            return
    ...
```

**步骤 4：在 `get_entries` 方法（L219-222）补充注释**

```python
def get_entries(self) -> list[dict[str, Any]]:
    """获取完整记录列表（含时间戳和工具名）— 供前端展示和审计

    注意（Stage 6.8 标注）: entries 是去重后的快照，非完整操作历史。
    同一文件同一操作仅保留首次记录，无法还原"该文件被编辑了几次"。
    如需完整时间序列，可参考 Cline 的 stale 标记策略改造。
    """
    with self._lock:
        return [e.to_dict() for e in self._entries]
```

**步骤 5：（可选）为 `FileContextEntry` 预留 `source` 字段**

保留原 dataclass 字段，增加 `source` 字段为未来扩展预留（如追踪 prompt 提到的文件）。当前默认为空，不影响现有逻辑：

```python
@dataclass
class FileContextEntry:
    """单条文件操作记录 — 对标 Cline FileContextEntry

    语义差异（Stage 6.8 标注）:
        - Cline FileMetadataEntry 含 record_state（active/stale）+ record_source
        - 本仓库无 record_state（去重策略不保留 stale）
        - 本仓库 source 字段预留，当前未使用（未来可追踪 prompt 提到的文件）

    Attributes:
        path: 文件绝对路径（已规范化）
        operation: 操作类型（read/edited/created/deleted）
        timestamp: ISO 格式时间戳（含时区）
        tool_name: 触发工具名（可选，用于审计）
        iteration: 触发时的迭代轮次（可选）
        source: 记录来源（预留，当前未使用；未来可为 "tool"/"user_mentioned"）
    """
    path: str
    operation: str
    timestamp: str = ""
    tool_name: str = ""
    iteration: int = 0
    source: str = ""  # Stage 6.8 预留
```

同步修改 `to_dict`（自动含 source，因用 asdict）、`_load`（L266-296 增加 source 读取）：

```python
# _load 方法中
self._entries = [
    FileContextEntry(
        path=e.get("path", ""),
        operation=e.get("operation", ""),
        timestamp=e.get("timestamp", ""),
        tool_name=e.get("tool_name", ""),
        iteration=e.get("iteration", 0),
        source=e.get("source", ""),  # Stage 6.8 新增
    )
    for e in entries_data
    if e.get("operation") in VALID_OPERATIONS and e.get("path")
]
```

### 验证方法

1. 文档验证：Read 修改后的 `file_context_tracker.py`，确认 docstring 和各处注释含语义差异说明，无 emoji，UTF-8 编码无乱码。
2. 功能回归验证：执行工具后调用 `GET /sessions/{id}/file_context`，确认 entries 和 state 返回正常，`source` 字段为空字符串（预留未用）。
3. 持久化兼容验证：旧格式 JSON 文件（无 source 字段）加载后 `source` 为空字符串，无异常。
4. 压缩摘要回归验证：触发上下文压缩，确认 `_summarize_tool_activity_v2` 仍正常从 tracker 取数（source 字段不影响）。

### 注意事项

- 本任务以文档标注为主，不改变现有功能逻辑（去重策略、操作类型分类保持现状）。
- `source` 字段为可选预留，当前不主动赋值，避免影响现有数据格式。
- 保留原 `record`/`get_state`/`get_entries`/`save`/`_load` 等方法逻辑，仅追加注释和可选字段。
- 不实现 Cline 的 stale 标记机制（本仓库无 watcher，stale 无意义）。
- 不实现 `file_mentioned` 操作类型（当前未追踪 prompt 中提到的文件，未来可扩展）。
- 中文注释 UTF-8 编码，无 emoji，不写 fallback。

---

## 附录：跨任务依赖关系

```
6.1 (版本迁移) ← 6.2 (schema 字段补齐)
    6.2 升级 _SESSION_FILE_VERSION 后，6.1 的迁移注册表需追加 v1→v2 迁移函数

6.2 (schema 字段) ← 6.3 (list 查询优化)
    6.3 的 sessions.index.json 索引需包含 6.2 新增的 status/provider/model 等字段

6.4 (git ref 持久化) ← 6.5 (回滚语义对齐)
    6.5 联动文件回滚依赖 6.4 的 ref 保证 stash commit 未被 GC 回收

6.5 (回滚语义) ← 6.6 (启用开关统一)
    6.5 的联动文件回滚受 6.6 的 AGENT_ENABLE_FILE_CHECKPOINT 开关控制

6.7 (SSE 事件) 独立，无前置依赖
6.8 (操作类型语义) 独立，仅文档标注
```

## 附录：实施顺序建议

1. **第一批（P1，数据完整性）**：6.1 → 6.2 → 6.4 → 6.5
2. **第二批（P2，性能与体验）**：6.3 → 6.6 → 6.7
3. **第三批（P2，文档对齐）**：6.8

每批内任务可并行，跨批存在依赖需顺序执行。
