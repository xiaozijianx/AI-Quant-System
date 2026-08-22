# Phase 3.15 todo_write 实现细节对比

> 对比范围：Cline `team_task` 多 agent 任务管理工具（Cline 无专门 todo_write 工具）与 Charles `TodoWriteTool` 单 agent 任务清单工具的实现细节差异。
>
> **关键前提**：Cline 源码中**没有专门的 todo_write 工具**（`sdk/packages/core/src/extensions/tools/executors/` 下无 todo 相关文件，`definitions.ts` 无 todo 工具定义）。Cline 最接近的功能是 `team/team-tools.ts` 中的 `team_task` 工具，但二者设计目标不同：
> - Charles `todo_write`：单 agent 任务清单跟踪，对标 **Claude TodoWrite**（非 Cline）
> - Cline `team_task`：多 agent 协作的任务分配系统，支持依赖、分配、阻塞
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/team/team-tools.ts` L391-485（`team_task` 工厂）
> - `sdk/packages/shared/src/team/schema.ts` L97-124（`TeamTaskInputSchema` + superRefine）
> - `sdk/packages/shared/src/team/schema.ts` L23-28（`TeamTaskStatusSchema`）
> - `sdk/packages/shared/src/team/types.ts` L9-31（`TeamTaskStatus` / `TeamTask` / `TeamTaskListItem`）
> - `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` L934-1010（createTask / claimTask / completeTask / blockTask）
> - `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` L598-627（listTaskItems）
>
> Charles 源码：
> - `agent/tools/todo_write.py`（TodoWriteTool 完整实现）
> - `agent/state.py` L55-133（TodoStatus / TodoItem / SessionState）
> - `agent/state.py` L488-508（get_todos / set_todos）
> - `agent/kanban.py`（KanbanManager 可视化层）
> - `agent/runtime.py` L2150-2201（_make_emit_update 事件转发）
> - `agent/server.py` L895-907 / L935-970（SSE 事件分发）

---

## 一、执行摘要

Cline 与 Charles 在"任务清单"这一功能上采用了**两种完全不同的设计范式**，根本原因是设计目标不同：

1. **Charles 的 `todo_write` 对标 Claude TodoWrite**（文件头 L2 明确标注"对标 Claude TodoWrite + Cline 任务规划"），是**单 agent 的任务清单跟踪工具**：
   - **替换式更新**：LLM 每次调用传入完整清单，整体替换 `SessionState.todos`
   - **强制单一 in_progress**：清单中最多一项 in_progress，符合单 agent 串行执行模型
   - **无 id 机制**：todo item 只有 content/status/active_form 三个字段，通过数组索引定位
   - **持久化**：状态落盘到 `agent_data/state/<session_id>.json`（Phase 18 增强）

2. **Cline 的 `team_task` 是多 agent 协作的任务分配系统**，服务于 `MultiAgentTeamRuntime`：
   - **增量式更新**：基于 action（create/list/claim/complete/block），每次调用只修改一个 task
   - **允许多个 in_progress**：多个 agent 可并行认领不同 task，无单一 in_progress 约束
   - **自动生成 id**：`task_0001` 格式自增计数器，支持通过 taskId 引用
   - **依赖与阻塞**：支持 `dependsOn` 依赖链、`blocked` 状态、`assignee` 分配

3. **关键差异点**：
   - **功能定位不同**：Charles 是单 agent 任务跟踪（对标 Claude），Cline 是多 agent 协作（自有设计），二者不是同一功能的两种实现
   - **merge 策略相反**：Charles 替换式（全量），Cline 增量式（单次单操作）
   - **id 机制差异**：Charles 无 id（简单），Cline 有自动 id（支持引用）
   - **状态约束差异**：Charles 强制单一 in_progress（串行模型），Cline 允许多个 in_progress（并行模型）
   - **状态数差异**：Charles 3 个（pending/in_progress/completed），Cline 4 个（多一个 `blocked`）

4. **nanobot 残留**：P3.15 核心文件中 **`todo_write.py` / `state.py`（TodoItem 定义段）/ `kanban.py` 均为 0 处残留**，已完全清理。仅 `tools/__init__.py` L2 有 1 处模块级 docstring 残留（"对标 Cline extensions/tools 和 nanobot agent/tools"），属注释残留，与 P3.1 发现的同一处残留，不在 todo_write 专属范围内。

5. **一致性总体评估**：**低**（设计目标不同，非缺陷）。Charles 的 `todo_write` 是 Claude TodoWrite 的实现，与 Cline 的 `team_task` 是不同的功能定位，不应视为"对齐缺失"。若强行对齐 Cline 的 action-based 增量模式，反而会破坏 Charles 单 agent 串行任务的简洁性。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现（team_task） | Charles 实现（todo_write） | 一致性等级 | 说明 |
|---|--------|------------------------|---------------------------|-----------|------|
| 3.15.1 | 功能定位 | 多 agent 协作任务分配系统 | 单 agent 任务清单跟踪（对标 Claude TodoWrite） | 低（设计目标不同） | 非同一功能的两种实现，不可直接对齐 |
| 3.15.2 | 对标来源 | Cline 自有设计（team 多 agent 系统） | Claude TodoWrite（文件头 L2 明确标注） | — | Charles 明确对标 Claude 而非 Cline |
| 3.15.3 | 输入 schema 顶层结构 | `{action, title?, description?, dependsOn?, assignee?, status?, taskId?, summary?, reason?}` | `{todos: array}` | 低（范式不同） | Cline action-based，Charles array-based |
| 3.15.4 | 输入 schema 校验 | Zod schema + `superRefine` 按行动作校验必填字段 | 手动校验（content 非空 / status 合法 / in_progress ≤ 1） | 中 | 两者都校验，Cline 用 Zod，Charles 手写 |
| 3.15.5 | todo 项字段 | `id/title/description/status/createdAt/updatedAt/createdBy/assignee?/dependsOn/summary?`（10 字段） | `content/status/active_form`（3 字段） | 低 | Charles 极简，Cline 丰富（多 agent 需要） |
| 3.15.6 | todo 项 id | 自动生成 `task_0001` 格式（`++taskCounter`） | **无 id** | 低 | Charles 通过数组索引定位，Cline 通过 taskId 引用 |
| 3.15.7 | 状态枚举 | `pending / in_progress / blocked / completed`（4 个） | `pending / in_progress / completed`（3 个） | 中 | Charles 缺 `blocked`（单 agent 不需要阻塞概念） |
| 3.15.8 | 单一 in_progress 约束 | **无约束**（多个 agent 可并行认领） | **强制 ≤ 1**（`in_progress_count > 1` 报错） | 低（设计差异） | Charles 串行模型 vs Cline 并行模型 |
| 3.15.9 | merge 策略 | **增量式**（action-based，每次一个 task） | **替换式**（全量替换 `state.todos`） | 低（范式相反） | Charles 对标 Claude TodoWrite 的替换式语义 |
| 3.15.10 | 依赖链支持 | `dependsOn: string[]` + `assertDependenciesResolved` + `getUnresolvedDependencies` | **无** | 低 | Charles 单 agent 不需要任务间依赖 |
| 3.15.11 | 任务分配 | `assignee` 字段 + `claimTask` action | **无** | 低 | Charles 单 agent 无分配需求 |
| 3.15.12 | 排序 | 无显式排序（按 Map 插入顺序） | 无显式排序（按 LLM 传入数组顺序） | 高 | 两者都保持插入顺序 |
| 3.15.13 | 错误处理 | Zod `safeParse` + `requireTask` + `assertDependenciesResolved`，抛 Error | 手动校验返回 `AgentToolResult(is_error=True)`，含 hint/valid_values | 中（范式差异） | Cline 抛异常由 runtime 捕获，Charles 返回结构化错误 |
| 3.15.14 | UI 事件通知 | `emitEvent({type: TeamTaskUpdated, task})` | `context.emit_update({"todos_updated": [...]})` → TOOL_UPDATED 事件 → SSE | 中 | 机制不同但都支持实时通知 |
| 3.15.15 | 事件类型粒度 | 细粒度枚举（TeamTaskUpdated / TeamTaskCompleted / RunStarted 等 17 种） | 粗粒度单事件（`todos_updated`） | 中 | Cline 多 agent 需要更多事件类型 |
| 3.15.16 | 状态持久化 | 内存（`MultiAgentTeamRuntime.tasks` Map，无落盘） | 落盘 `agent_data/state/<session_id>.json`（Phase 18） | 高（Charles 更强） | Charles 支持重启恢复，Cline team 状态易失 |
| 3.15.17 | 会话隔离 | 按 `teamId` 隔离（多 agent 共享一个 team） | 按 `session_id` 隔离（每会话独立 todos） | 中 | 隔离维度不同，符合各自场景 |
| 3.15.18 | 工具描述生成 | 静态字符串（`description: "Manage shared team tasks..."`） | `@property description` 动态返回 | 高（Charles 更灵活） | Charles property 机制天然支持动态 |
| 3.15.19 | read_only 标记 | 无显式字段（由 toolPolicies 控制） | `read_only = True`（仅改会话内状态，可并行） | 中 | Charles 显式声明只读 |
| 3.15.20 | 可视化层 | 无独立可视化层（team_status 工具返回快照） | `KanbanManager`（`agent/kanban.py`）3 列看板视图 | 高（Charles 更丰富） | Charles 有专门看板 API |
| 3.15.21 | 任务计数统计 | `taskCounts: Record<TeamTaskStatus, number>`（4 状态计数） | `stats: {total, completed, in_progress, pending}`（3 状态计数） | 高 | 两者都返回统计，字段结构略异 |
| 3.15.22 | 返回值结构 | `TeamTaskToolResult`（discriminatedUnion，按 action 分支） | `AgentToolResult.output`（含 old_todos/new_todos/stats/hint） | 中 | Cline 按 action 分支返回，Charles 统一结构 |
| 3.15.23 | 历史溯源（old_todos） | **无**（增量式不需要返回旧状态） | **有**（`old_todos` 字段，替换式需要对比） | — | 范式差异决定，非缺陷 |
| 3.15.24 | hint 提示 | `nextStep` 字段（claim action 返回固定提示） | `hint` 字段（动态生成：继续执行/下一项/全部完成） | 中 | Charles 的 hint 更智能 |
| 3.15.25 | 工具注册位置 | `team-tools.ts` 的 `createTeamTools()` 工厂数组 | `create_default_tools()` L93 `TodoWriteTool(session_id=sid)` | 中 | Charles 在默认工具集，Cline 在 team 扩展 |

**一致性总评**：25 项中，高一致性 5 项、中一致性 11 项、低一致性 9 项。低一致性项主要集中在设计目标差异（单 agent vs 多 agent、替换式 vs 增量式、无 id vs 有 id），**均为设计选择而非缺陷**。

---

## 三、重点差距详细说明

### 差距 1：功能定位根本不同（3.15.1 / 3.15.2）

**Charles `todo_write`**（`todo_write.py` L2）：
```python
"""任务清单工具 — 对标 Claude TodoWrite + Cline 任务规划
```
明确对标 **Claude TodoWrite**，是单 agent 的任务清单跟踪工具。文件头 L21 虽然提到"对标 Cline sdk-packages/core/src/extensions/tools/team/spawn-agent-tool.ts 中子 agent 任务跟踪"，但实际实现与 `spawn-agent-tool.ts`（子 agent 生成工具）无直接代码对应关系，属概念借鉴。

**Cline `team_task`**（`team-tools.ts` L393-399）：
```typescript
name: "team_task",
description:
    "Manage shared team tasks with action-specific payloads. " +
    "create requires title and description, with optional dependsOn and assignee. " +
    "list accepts optional status, assignee. " +
    "claim requires taskId. complete requires taskId and summary. block requires taskId and reason. " +
    "Do not include fields from other actions.",
```
是 `MultiAgentTeamRuntime` 的任务管理接口，服务于多 agent 协作场景（lead agent 分配任务给 teammate）。

**影响**：
- 两者**不是同一功能的两种实现**，不应要求 Charles 对齐 Cline 的 action-based 模式。
- Charles 的替换式更新（对标 Claude）更适合单 agent 串行任务跟踪，LLM 一次性规划完整清单。
- Cline 的增量式更新更适合多 agent 并行协作，每个 agent 独立操作单个 task。

**建议**：保留 Charles 现状。Charles 的 `todo_write` 是 Claude TodoWrite 的忠实实现，与 Cline `team_task` 是互补关系而非竞争关系。

### 差距 2：merge 策略相反（3.15.9 / 3.15.23）

**Charles 替换式更新**（`todo_write.py` L161-162）：
```python
# 替换式更新
old_todos = set_todos(self._session_id, new_todos)
```
`set_todos()`（`state.py` L493-508）直接替换 `state.todos`，返回 `old_todos` 用于对比。LLM 每次调用必须传入**完整清单**，即使是微小修改也要重传全部 todos。

**Cline 增量式更新**（`multi-agent.ts` L934-1010）：
```typescript
createTask(input: CreateTeamTaskInput): TeamTask {
    const taskId = `task_${String(++this.taskCounter).padStart(4, "0")}`;
    // ... 添加到 this.tasks Map
}
claimTask(taskId: string, agentId: string): TeamTask {
    const task = this.requireTask(taskId);
    task.status = "in_progress";
    // ... 修改单个 task
}
```
每次调用只执行一个 action（create/claim/complete/block），通过 `taskId` 定位单个 task 修改。

**影响**：
- Charles 的替换式语义更简单（LLM 无需记住 taskId），但 token 开销更大（每次重传全部 todos）。
- Cline 的增量式语义更精确（只传变更项），但需要 LLM 维护 taskId 上下文。
- Charles 的 `old_todos` 返回值让 LLM 能看到变更前后对比，Cline 无此需求（增量式天然知道变更项）。

**建议**：保留 Charles 替换式语义。这是 Claude TodoWrite 的标准行为，与 Claude 模型训练数据一致，LLM 调用更自然。

### 差距 3：id 机制差异（3.15.6）

**Charles 无 id**（`state.py` L62-72）：
```python
@dataclass
class TodoItem:
    content: str
    status: TodoStatus = "pending"
    active_form: str = ""
```
TodoItem 只有 3 个字段，无 id。LLM 通过 content 文本隐式定位任务。

**Cline 自动生成 id**（`multi-agent.ts` L935）：
```typescript
const taskId = `task_${String(++this.taskCounter).padStart(4, "0")}`;
```
格式为 `task_0001`、`task_0002`，通过 `++taskCounter` 自增。后续 claim/complete/block 操作通过 `taskId` 引用。

**影响**：
- Charles 的无 id 设计更简洁，适合替换式更新（LLM 每次重传全部，不需要 id 关联）。
- Cline 的 id 设计是增量式更新的必要条件（LLM 需要 taskId 才能定位修改单个 task）。
- 若 Charles 改为增量式，则必须引入 id 机制；但 Charles 选择替换式，无需 id。

**建议**：保留 Charles 无 id 设计。id 是增量式更新的伴随需求，Charles 替换式不需要。

### 差距 4：状态约束差异（3.15.7 / 3.15.8）

**Charles 强制单一 in_progress**（`todo_write.py` L122-132）：
```python
in_progress_count = sum(1 for t in todos_input if t.get("status") == "in_progress")
if in_progress_count > 1:
    return AgentToolResult(
        output={
            "error": "清单中最多一项 status=in_progress",
            "received_in_progress_count": in_progress_count,
            "hint": "请将其他进行中的任务先标记为 pending 或 completed",
        },
        is_error=True,
    )
```
符合单 agent 串行执行模型：一次只做一个任务。

**Cline 允许多个 in_progress**：
`team_task` 无此校验。`claimTask()`（`multi-agent.ts` L956-973）直接将 task.status 设为 `in_progress`，不检查已有 in_progress 数量。多个 teammate 可并行认领不同 task。

**Cline 多一个 `blocked` 状态**（`schema.ts` L23-28）：
```typescript
const TeamTaskStatusSchema = z.enum([
    "pending",
    "in_progress",
    "blocked",
    "completed",
]);
```
`blocked` 状态通过 `blockTask()` action 设置，表示任务被阻塞（如依赖未解决、外部阻塞）。Charles 单 agent 不需要阻塞概念（任务要么在做、要么没做、要么做完）。

**影响**：
- Charles 的单一 in_progress 约束是单 agent 串行模型的核心保障，防止 LLM 同时"开始"多个任务。
- Cline 的多 in_progress 允许是多 agent 并行的必要条件。
- Charles 缺 `blocked` 状态是合理简化，单 agent 场景下"阻塞"等价于"暂停（保持 in_progress 但不执行）"或"回退为 pending"。

**建议**：保留 Charles 现状。单一 in_progress 是单 agent 任务跟踪的关键约束，`blocked` 状态在单 agent 场景无实际价值。

### 差距 5：UI 事件通知机制差异（3.15.14 / 3.15.15）

**Charles 事件链路**（`todo_write.py` L165-172 → `runtime.py` L2181-2197 → `server.py` L962-965）：
```
工具调用 context.emit_update({"todos_updated": [...]})
  → runtime._make_emit_update() 构造 TOOL_UPDATED 事件
    → emitter.emit_sync(event) 同步发射
      → server._handle_status_notice() 监听 TOOL_UPDATED
        → yield _sse_event("todos_updated", {"todos": todos_data})
          → 前端 SSE 接收
```
单事件类型 `todos_updated`，前端通过 SSE 实时渲染 TodoList 卡片。

**Cline 事件链路**（`multi-agent.ts` L949-952）：
```typescript
this.emitEvent({
    type: TeamMessageType.TeamTaskUpdated,
    task: { ...task },
});
```
`TeamMessageType` 枚举有 17 种事件类型（`types.ts` L214-234），包括 `TeamTaskUpdated` / `TeamTaskCompleted` / `RunStarted` / `RunCompleted` 等，事件粒度更细。

**影响**：
- Charles 的单事件 `todos_updated` 足够单 agent 场景（前端只需知道清单变了，重绘即可）。
- Cline 的 17 种事件是多 agent 协作的必要复杂度（需要区分 task 创建/认领/完成/阻塞、run 启动/完成/失败等）。
- Charles 的事件链路更简洁（4 跳），Cline 的事件链路更丰富（但文档未明确前端如何消费 17 种事件）。

**建议**：保留 Charles 单事件设计。单 agent 场景下 `todos_updated` 已覆盖所有需求，引入更多事件类型增加复杂度无收益。

### 差距 6：状态持久化差异（3.15.16）

**Charles 落盘持久化**（`state.py` L493-508）：
```python
def set_todos(session_id: str, todos: list[TodoItem]) -> list[TodoItem]:
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            state = _load_state_from_disk(session_id) or SessionState()
            _sessions[session_id] = state
        old_todos = state.todos
        state.todos = todos
        # Phase 18: 同步落盘
        _persist_state(session_id)
        return old_todos
```
持久化到 `agent_data/state/<session_id>.json`，支持服务重启后恢复 todos 状态（`load_all_states()` 启动时加载）。

**Cline 内存态**：
`MultiAgentTeamRuntime.tasks` 是 `Map<string, TeamTask>`，无落盘逻辑。team 状态在 runtime 销毁后丢失。

**影响**：
- Charles 的持久化能力**强于 Cline**，适合 Web 应用场景（服务可能重启）。
- Cline 的内存态适合 CLI 场景（一次任务一次运行，无需跨会话恢复）。
- Charles 的持久化是 Phase 18 增强，对标"Claude 的 TodoWrite 工具状态持久化"（`state.py` L23 注释）。

**建议**：保留 Charles 持久化能力。这是 Web 应用场景的实际需求，是 Charles 相对 Cline 的功能增强。

---

## 四、nanobot 残留检查

针对 P3.15 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.15 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/todo_write.py` | **0** | 无 | 已完全清理，文件头对标"Claude TodoWrite + Cline 任务规划"，无 nanobot 引用 |
| `agent/state.py`（TodoItem 定义段 L55-133） | **0** | 无 | TodoItem / SessionState 定义无 nanobot 引用 |
| `agent/kanban.py` | **0** | 无 | 看板可视化层无 nanobot 引用，对标"Cline kanban" |
| `agent/runtime.py`（_make_emit_update 段 L2150-2201） | **0** | 无 | emit_update 事件转发逻辑无 nanobot 引用 |
| `agent/server.py`（_handle_status_notice 段 L935-970） | **0** | 无 | SSE 事件分发逻辑无 nanobot 引用 |
| `agent/tools/__init__.py` | **1** | 注释残留 | L2 docstring：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools` |

### 4.2 残留分类

#### 注释残留（1 处，与 P3.1 同一处）

**位置**：`agent/tools/__init__.py` L2
```python
"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools
```

**性质**：模块级 docstring 中的历史溯源说明，标注 Charles 工具系统同时对标了 Cline extensions/tools 和历史 nanobot agent/tools。不影响运行时行为，不影响 todo_write 工具功能。此残留与 P3.1 发现的是同一处，属工具系统模块级注释，非 todo_write 专属残留。

**处理建议**：将 L2 改为 `"""工具系统 — 对标 Cline extensions/tools`，移除 `和 nanobot agent/tools` 段落。属于 P2 级别清理，与 P3.1 建议一致，可在后续清理批次中统一处理。

#### 实现逻辑残留（0 处）

P3.15 核心文件中**未发现任何从 nanobot 直接移植的实现逻辑**：

- `TodoWriteTool` 类设计对标 Claude TodoWrite（`todo_write.py` L2 明确标注"对标 Claude TodoWrite"）。
- `TodoItem` dataclass 对标 Claude TodoWrite 的 todo item（`state.py` L63 标注"对标 Claude TodoWrite 的 todo item"）。
- `TodoStatus` 类型对标 Claude TodoWrite status 字段（`state.py` L54 标注"对标 Claude TodoWrite status 字段"）。
- `set_todos()` 的持久化逻辑是 Phase 18 增强，对标"Claude 的 TodoWrite 工具状态持久化"（`state.py` L23 注释）。
- `KanbanManager` 对标 Cline kanban（`kanban.py` L2 标注"对标 Cline kanban"），但实现改为内嵌 API（不启动外部进程）。
- `_make_emit_update()` 对标 Cline agent-runtime.ts L1498-1506 的 emitUpdate（`runtime.py` L2160 标注）。

### 4.3 P3.15 范围外但相关的 nanobot 残留

以下文件有 nanobot 残留，但属于 P3.x 其他小阶段的对比范围，不在 P3.15 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|---------------|-----------|
| `agent/tools/exec_tool.py` | 12 | P3.x（exec_tool 专项，注意该工具已废弃） |
| `agent/tools/file_tools.py` | 7 | P3.x（FileWriteTool 专项） |
| `agent/tools/web_tool.py` | 7 | P3.x（WebSearchTool 专项） |
| `agent/session.py` | 2 | P1.x（会话管理） |
| `agent/server.py`（模块级 docstring） | 2 | P1.x（SSE 服务端） |

这些残留全部为 docstring / 行内注释，属历史溯源标注，不影响 todo_write 工具的对比结论。

---

## 五、修复建议

### 建议 1：清理 `__init__.py` L2 的 nanobot 注释残留 [P2]

**文件**：`agent/tools/__init__.py`
**位置**：L2
**修改**：
- 当前：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools`
- 建议：`"""工具系统 — 对标 Cline extensions/tools`

**理由**：统一为"对标 Cline"溯源风格，与 `todo_write.py`（已清理，对标 Claude TodoWrite）、`base.py`（已清理）保持一致。不影响功能。此建议与 P3.1 建议 1 重复，属同一处清理。

### 建议 2：保留替换式更新语义 [P0 不变]

**理由**：
- Charles 的 `todo_write` 对标 Claude TodoWrite，替换式更新是 Claude 的标准行为。
- Claude 模型训练数据中包含 TodoWrite 的替换式调用模式，LLM 调用更自然。
- 单 agent 串行场景下，替换式语义更简单（LLM 无需维护 taskId 上下文）。
- 强行改为 Cline 的 action-based 增量模式会破坏与 Claude 模型的兼容性。

### 建议 3：保留无 id 设计 [P0 不变]

**理由**：
- id 是增量式更新的伴随需求（需要 taskId 定位单个 task）。
- Charles 选择替换式更新，LLM 每次重传全部 todos，无需 id 关联。
- 引入 id 会增加 schema 复杂度，且 LLM 需要维护 id 上下文，与替换式语义冲突。

### 建议 4：保留单一 in_progress 约束 [P0 不变]

**理由**：
- 单 agent 串行执行模型的核心保障：一次只做一个任务。
- 防止 LLM 同时"开始"多个任务导致执行流程混乱。
- Cline 允许多个 in_progress 是多 agent 并行的需求，Charles 单 agent 不需要。

### 建议 5：不引入 blocked 状态 [P3 不修复]

**理由**：
- `blocked` 状态在单 agent 场景无实际价值。
- 单 agent 遇到阻塞时，可保持 `in_progress`（暂停执行）或回退为 `pending`（稍后再做）。
- 引入 `blocked` 会增加状态机复杂度，且 LLM 难以正确判断何时标记 blocked。

### 建议 6：保留持久化能力 [P0 不变]

**理由**：
- Charles 的 Web 应用场景需要服务重启后恢复 todos 状态。
- 持久化是 Phase 18 增强的实际需求，对标"Claude 的 TodoWrite 工具状态持久化"。
- Cline 的内存态适合 CLI 场景，Charles 不应退化为内存态。

### 建议 7：保留 KanbanManager 可视化层 [P0 不变]

**理由**：
- Charles 是 Web 应用，需要内嵌看板视图（`kanban.py` L14-19 明确说明）。
- Cline 的 kanban.ts 启动外部 npm 工具，不适合 Web 场景。
- `KanbanManager` 直接读取 `SessionState.todos`，不维护独立状态，无数据冗余。

---

## 六、验证方法建议

### 验证方法 1：输入 schema 等价性检查

对比 Charles `todo_write` 的 `input_schema` 与 Cline `team_task` 的 `TeamTaskInputSchema`，确认二者结构差异：

```powershell
# Charles 侧 schema（todo_write.py L67-96）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\todo_write.py" -Pattern "input_schema|todos|content|status|active_form"

# Cline 侧 schema（schema.ts L97-124）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\team\schema.ts" -Pattern "TeamTaskInputSchema|action|title|taskId"
```

**预期**：Charles 是 `{todos: array}`，Cline 是 `{action, title?, taskId?, ...}`，结构完全不同（范式差异）。

### 验证方法 2：状态约束检查

确认 Charles 的单一 in_progress 约束与 Cline 的无约束差异：

```powershell
# Charles 侧约束（todo_write.py L122-132）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\todo_write.py" -Pattern "in_progress_count|最多一项"

# Cline 侧无约束（multi-agent.ts L956-973 claimTask）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\team\multi-agent.ts" -Pattern "claimTask|in_progress"
```

**预期**：Charles 有 `in_progress_count > 1` 校验，Cline 的 `claimTask` 直接设 `status = "in_progress"` 无计数校验。

### 验证方法 3：id 生成机制检查

确认 Charles 无 id、Cline 有自动 id：

```powershell
# Charles 侧 TodoItem 无 id 字段（state.py L62-72）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "class TodoItem|content|status|active_form|id"

# Cline 侧 task id 生成（multi-agent.ts L935）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\team\multi-agent.ts" -Pattern "taskCounter|task_"
```

**预期**：Charles TodoItem 无 `id` 字段，Cline 有 `task_${String(++this.taskCounter).padStart(4, "0")}`。

### 验证方法 4：事件通知链路检查

确认 Charles 的事件链路完整（工具 → runtime → server → SSE）：

```powershell
# 工具侧 emit_update（todo_write.py L165-172）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\todo_write.py" -Pattern "emit_update|todos_updated"

# runtime 侧事件转发（runtime.py L2181-2197）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "TOOL_UPDATED|emit_update|emit_sync"

# server 侧 SSE 分发（server.py L962-965）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "todos_updated|_sse_event"
```

**预期**：三跳链路完整，`todos_updated` 从工具经 runtime 到达 SSE。

### 验证方法 5：nanobot 残留扫描

```powershell
# P3.15 核心文件扫描（应全部为 0，仅 __init__.py L2 有 1 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\todo_write.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\kanban.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\__init__.py" -Pattern "nanobot" -CaseSensitive:$false
```

**预期**：`todo_write.py` / `state.py` / `kanban.py` 为 0 处，`__init__.py` 为 1 处（L2 docstring）。

### 验证方法 6：持久化落盘检查

确认 Charles 的 todos 状态会落盘到 `agent_data/state/<session_id>.json`：

```powershell
# set_todos 调用 _persist_state（state.py L493-508）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "set_todos|_persist_state|_load_state_from_disk"
```

**预期**：`set_todos()` 内部调用 `_persist_state(session_id)` 实现同步落盘。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/shared/src/team/types.ts` | L9-13 | `TeamTaskStatus` 类型（4 状态：pending/in_progress/blocked/completed） |
| `sdk/packages/shared/src/team/types.ts` | L15-26 | `TeamTask` 接口（10 字段：id/title/description/status/createdAt/updatedAt/createdBy/assignee?/dependsOn/summary?） |
| `sdk/packages/shared/src/team/types.ts` | L28-31 | `TeamTaskListItem` 接口（extends TeamTask + isReady + blockedBy） |
| `sdk/packages/shared/src/team/types.ts` | L214-234 | `TeamMessageType` 枚举（17 种事件类型） |
| `sdk/packages/shared/src/team/schema.ts` | L23-28 | `TeamTaskStatusSchema` Zod enum（4 状态） |
| `sdk/packages/shared/src/team/schema.ts` | L81-95 | `TEAM_TASK_REQUIRED_FIELDS_BY_ACTION` + `TEAM_TASK_IGNORED_FIELDS_BY_ACTION` |
| `sdk/packages/shared/src/team/schema.ts` | L97-124 | `TeamTaskInputSchema` Zod object + superRefine 按行动作校验 |
| `sdk/packages/shared/src/team/schema.ts` | L297-325 | `TeamTaskToolResultSchema` discriminatedUnion（按 action 分支） |
| `sdk/packages/core/src/extensions/tools/team/team-tools.ts` | L391-485 | `team_task` 工具工厂（create/list/claim/complete/block 分支） |
| `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | L934-953 | `createTask()` 实现（自动生成 task_xxxx id） |
| `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | L956-973 | `claimTask()` 实现（设 status=in_progress，无计数约束） |
| `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | L975-991 | `blockTask()` 实现（设 status=blocked） |
| `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | L993-1010 | `completeTask()` 实现（设 status=completed） |
| `sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | L598-627 | `listTaskItems()` 实现（过滤 + isReady 计算） |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/todo_write.py` | L1-23 | 文件头 docstring（对标 Claude TodoWrite + Cline 任务规划） |
| `agent/tools/todo_write.py` | L34-52 | `TodoWriteTool` 类定义 + `__init__(session_id)` |
| `agent/tools/todo_write.py` | L58-64 | `description` 属性（动态返回） |
| `agent/tools/todo_write.py` | L67-96 | `input_schema` 属性（`{todos: array}` + item schema） |
| `agent/tools/todo_write.py` | L98-101 | `read_only = True`（仅改会话内状态） |
| `agent/tools/todo_write.py` | L103-207 | `_execute()` 实现（校验 + 替换式更新 + emit_update + hint） |
| `agent/tools/todo_write.py` | L122-132 | 单一 in_progress 约束校验 |
| `agent/tools/todo_write.py` | L134-149 | content 非空 + status 合法性校验 |
| `agent/tools/todo_write.py` | L151-159 | 构造 TodoItem 列表 |
| `agent/tools/todo_write.py` | L161-172 | 替换式更新 + emit_update 通知 |
| `agent/tools/todo_write.py` | L174-207 | 统计 + hint 生成 + 返回 AgentToolResult |
| `agent/state.py` | L54-55 | `TodoStatus` 类型（3 状态：pending/in_progress/completed） |
| `agent/state.py` | L61-89 | `TodoItem` dataclass（3 字段：content/status/active_form + to_dict/from_dict） |
| `agent/state.py` | L92-133 | `SessionState` dataclass（todos + mode + 序列化） |
| `agent/state.py` | L488-490 | `get_todos(session_id)` 读取 |
| `agent/state.py` | L493-508 | `set_todos(session_id, todos)` 替换式更新 + 持久化落盘 |
| `agent/kanban.py` | L1-31 | 文件头 docstring（对标 Cline kanban，改为内嵌 API） |
| `agent/kanban.py` | L55-76 | `KanbanCard` dataclass（对应 TodoItem） |
| `agent/kanban.py` | L131-170 | `KanbanManager` 类（基于 SessionState.todos 构建看板视图） |
| `agent/runtime.py` | L2150-2201 | `_make_emit_update()` 构造 emit_update 回调（TOOL_UPDATED 事件） |
| `agent/server.py` | L895-907 | STATUS_NOTICE / TOOL_UPDATED 事件 → _handle_status_notice 分发 |
| `agent/server.py` | L935-970 | `_handle_status_notice()` SSE 事件分发（todos_updated / mode_changed / approval_request） |
| `agent/tools/__init__.py` | L93 | `TodoWriteTool(session_id=sid)` 装配点 |
| `agent/tools/__init__.py` | L121 | `"TodoWriteTool"` 导出 |

---

## 八、结论

P3.15 todo_write 实现细节对比的核心结论：

1. **功能定位根本不同**：Charles 的 `todo_write` 对标 **Claude TodoWrite**（单 agent 任务清单跟踪），Cline 的 `team_task` 是多 agent 协作任务分配系统。二者不是同一功能的两种实现，不应视为"对齐缺失"。Cline 源码中**没有专门的 todo_write 工具**（`executors/` 下无 todo 文件，`definitions.ts` 无 todo 定义）。

2. **核心设计差异（均为设计选择，非缺陷）**：
   - **merge 策略**：Charles 替换式（全量，对标 Claude）vs Cline 增量式（action-based，多 agent 需要）
   - **id 机制**：Charles 无 id（替换式不需要）vs Cline 自动生成 `task_xxxx`（增量式需要 taskId 引用）
   - **状态约束**：Charles 强制单一 in_progress（单 agent 串行）vs Cline 允许多个 in_progress（多 agent 并行）
   - **状态数**：Charles 3 个（无 blocked）vs Cline 4 个（有 blocked，多 agent 阻塞场景）

3. **Charles 在两点上强于 Cline**（应予保留）：
   - **状态持久化**：Charles 落盘到 `agent_data/state/<session_id>.json`，支持服务重启恢复；Cline team 状态纯内存态，易失。
   - **可视化层**：Charles 有 `KanbanManager` 3 列看板 API；Cline 无独立可视化层（`team_status` 仅返回快照数据）。

4. **事件通知机制等价**：两者都支持实时 UI 通知。Charles 链路为 `emit_update → TOOL_UPDATED → SSE todos_updated`（单事件），Cline 为 `emitEvent → TeamMessageType.TeamTaskUpdated`（17 种事件枚举）。Charles 单事件足够单 agent 场景。

5. **nanobot 残留**：P3.15 核心文件中 `todo_write.py` / `state.py`（TodoItem 段）/ `kanban.py` / `runtime.py`（emit_update 段）/ `server.py`（SSE 分发段）**均为 0 处残留**，已完全清理。仅 `tools/__init__.py` L2 有 1 处模块级 docstring 残留（与 P3.1 同一处），属 P2 级别清理任务。

6. **修复建议**：P3.15 范围内**无需阻塞性修复**。所有低一致性项均为设计目标差异（单 agent vs 多 agent、替换式 vs 增量式），保留 Charles 现状即可。唯一建议是清理 `__init__.py` L2 的 nanobot 注释残留（P2 级别，与 P3.1 建议 1 重复）。

**整体一致性等级**：**低**（设计目标不同，非缺陷）。Charles 的 `todo_write` 是 Claude TodoWrite 的忠实实现，与 Cline `team_task` 是互补关系而非竞争关系，不应要求对齐 Cline 的 action-based 增量模式。
