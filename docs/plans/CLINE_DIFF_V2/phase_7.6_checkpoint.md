# Phase 7.6 Checkpoint 机制对比

> 对比范围：Cline `sdk/packages/core/src/hooks/checkpoint-hooks.ts`（shadow-git 核心）+ `sdk/packages/core/src/session/checkpoint-restore.ts`（消息切片 + 工作区恢复）+ `sdk/packages/core/src/session/checkpoint-diff.ts`（diff 视图）+ `sdk/packages/core/src/session/session-snapshot.ts`（快照读写）+ `apps/vscode/src/sdk/SdkController.ts` `restoreCheckpoint`（三模式入口）+ `apps/vscode/src/sdk/sdk-checkpoints.ts`（runCount 计算）+ `apps/vscode/src/core/controller/checkpoints/checkpointRestore.ts`（VSCode 控制器）+ `sdk/packages/core/src/hub/server/handlers/session-handlers.ts`（hub 端点）+ `docs/core-workflows/checkpoints.mdx`（文档）；对比 Charles `agent/checkpoint.py`（消息快照 CheckpointManager）+ `agent/file_checkpoint.py`（文件快照 FileCheckpointManager + shadow-git）+ `agent/server.py` L1454-1772（`/checkpoints` `/rollback` `/file_checkpoints` `/rollback_file` 端点 + 联动回滚）+ `agent/types.py` L740-742（checkpoint 事件常量）+ `agent/runtime.py`（hook 注册）；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/hooks/checkpoint-hooks.ts` L1-291（`createCheckpointHooks` + `createCheckpoint` + `deleteCheckpointRefs` + `retainCheckpointRefs` + `runGit`）
> - `third_party/cline/sdk/packages/core/src/session/checkpoint-restore.ts` L1-189（`createCheckpointRestorePlan` + `applyCheckpointToWorktree` + `trimMessagesToCheckpoint` + `trimMessagesBeforeCheckpoint` + `findCheckpointForRun` + `readSessionCheckpointHistory`）
> - `third_party/cline/sdk/packages/core/src/session/checkpoint-diff.ts` L1-150（`createCheckpointComparePlan` + `buildCheckpointWorkspaceDiff` + `compareCheckpointToWorkspace`）
> - `third_party/cline/sdk/packages/core/src/session/session-snapshot.ts` L1-180（`CoreSessionCheckpointSnapshot` + `readCheckpointSnapshot`）
> - `third_party/cline/apps/vscode/src/sdk/SdkController.ts` L1416-1507（`restoreCheckpoint` 三模式入口）
> - `third_party/cline/apps/vscode/src/sdk/sdk-checkpoints.ts` L1-63（`isVisibleCheckpointUserMessage` + `getCheckpointRunCountForMessage` + `findVisibleCheckpointUserMessageByRun`）
> - `third_party/cline/apps/vscode/src/core/controller/checkpoints/checkpointRestore.ts` L1-23（VSCode 控制器入口）
> - `third_party/cline/sdk/packages/core/src/hub/server/handlers/session-handlers.ts` L196-203/L346-350/L408-510（hub `session.restore` 端点）
> - `third_party/cline/docs/core-workflows/checkpoints.mdx` L1-94（用户文档）
>
> Charles 源码：
> - `agent/checkpoint.py` L1-447（`Checkpoint` dataclass + `CheckpointManager` + `CheckpointHook` + `_message_to_dict`）
> - `agent/file_checkpoint.py` L1-860（`CheckpointRef` dataclass + `FileCheckpointManager` + `create_before_tool_checkpoint_hook`）
> - `agent/server.py` L410-450（`CheckpointHook` + `FileCheckpointHook` 注册）+ L1454-1772（4 个 checkpoint API 端点 + `_try_rollback_file_for_message_checkpoint` 联动）
> - `agent/types.py` L740-742（`CHECKPOINT_CREATED` / `CHECKPOINT_RESTORED` 事件常量）
> - `agent/runtime.py` L1279-1290（`before_tool` hook 注册点）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Checkpoint 机制。**核心结论：计划文件 P7.6 列出的 6 项对比项中 5 项已对齐（git ref 持久化 / 回滚联动 / `/rollback` / `/rollback_file` / 消息快照），仅 7.6.1 "Checkpoint 存储" 实现不同（Cline 单一 shadow-git 系统，Charles 双轨消息快照 + 文件快照）；Charles 未实现 Cline 的 checkpoint diff 对比视图与"仅消息回滚"独立模式，但补齐了原子性联动回滚（文件回滚失败时中止消息回滚）和消息回滚后清理压缩状态两项增强。**

### 计划文件核实结果

AGENT_COMPARISON_PLAN_V2.md L2641-2648 的 P7.6 对比表标注 7.6.1 "实现不同"、7.6.2-7.6.6 全部"已对齐"。经源码核实：

| 计划项 | 计划标注 | 实际核实 | 一致性 |
|--------|---------|---------|--------|
| 7.6.1 Checkpoint 存储 | 实现不同 | Cline 单一 shadow-git stash commit + 私有 ref `refs/cline/checkpoints/{sid}/{run}`（checkpoint-hooks.ts L236）；Charles 双轨：消息快照 JSON（`checkpoint.py` L121-129）+ 文件快照 shadow-git stash commit + 私有 ref `refs/agent/checkpoints/{sid}/{ckpt}`（`file_checkpoint.py` L637） | 中（架构不同，功能等价） |
| 7.6.2 git ref 持久化 | 已对齐（Stage 6.4） | Cline `update-ref refs/cline/checkpoints/{sid}/{run} <commit>`（checkpoint-hooks.ts L236-238）+ `deleteCheckpointRefs` 批量清理（L102-121）；Charles `_git_update_ref` + `_git_delete_ref`（file_checkpoint.py L639-715），ref 命名空间 `refs/agent/checkpoints/` 与 Cline 区分 | 高 |
| 7.6.3 回滚联动 | 已对齐（Stage T5） | Cline `applyCheckpointToWorktree`（checkpoint-restore.ts L161-189）：`reset --hard` + `clean -fd` + `stash apply`；Charles `_try_rollback_file_for_message_checkpoint`（server.py L1622-1654）联动消息回滚 + 文件回滚，文件失败时中止消息回滚（原子性） | 高（增强：原子性保证） |
| 7.6.4 `/rollback` 端点 | 已对齐 | Cline `session.restore` hub 端点（session-handlers.ts L408-510）+ VSCode `restoreCheckpoint`（SdkController.ts L1416）；Charles `POST /rollback`（server.py L1500-1619） | 高 |
| 7.6.5 `/rollback_file` 端点 | 已对齐 | Cline `restoreType: "workspace"` 单独模式（SdkController.ts L1418）；Charles `POST /rollback_file`（server.py L1716-1771）独立端点 | 高 |
| 7.6.6 消息快照 | 已对齐 | Cline `trimMessagesToCheckpoint` 按 runCount 切片（checkpoint-restore.ts L106-112）；Charles `CheckpointManager` 保存消息列表深拷贝（checkpoint.py L140-182） | 中-高（机制不同） |

### 核心结论

1. **架构差异 — 单一 vs 双轨**：Cline 是单一 shadow-git checkpoint 系统（一个 stash commit 同时承担"文件状态快照"和"按 runCount 回滚消息"两个职责）；Charles 是双轨系统（`checkpoint.py` 保存消息列表深拷贝 JSON，`file_checkpoint.py` 用 shadow-git stash commit 保存文件状态）。Charles 的双轨设计更清晰但维护成本更高。
2. **触发时机差异**：Cline 在 `beforeModel` hook 中 iteration=1 时触发（每个 run 一次，即每个用户 turn 一次）；Charles 在 `before_tool` hook 中写工具执行前触发（每个写工具一次）。Charles 粒度更细（每个写工具一个 checkpoint），Cline 粒度更粗（每个 turn 一个 checkpoint）。
3. **git ref 命名空间对齐**：Cline `refs/cline/checkpoints/{sessionId}/{runCount}`，Charles `refs/agent/checkpoints/{sessionId}/{checkpointId}`。命名空间不同但机制完全一致（私有 ref + `update-ref` + `update-ref -d` 清理）。
4. **回滚模式对齐（部分）**：Cline 三种独立模式（`workspace` 仅文件 / `task` 仅消息 / `taskAndWorkspace` 联动）；Charles 两种端点（`/rollback` 联动 + `/rollback_file` 仅文件）。**Charles 缺少独立的"仅消息回滚"端点**（Cline 的 `task` 模式 Charles 无直接对应）。
5. **Charles 增强 — 原子性联动回滚**：Charles `/rollback` 先尝试文件回滚，失败时中止消息回滚（server.py L1538-1573），保证"文件+消息"原子性。Cline 的 `taskAndWorkspace` 模式分别调用 `applyCheckpointToWorktree` 和消息切片，无原子性保证（文件回滚失败不阻止消息回滚）。
6. **Charles 增强 — 回滚后清理压缩状态**：Charles `/rollback` 成功后调用 `CompactionStateManager().clear(session_id)` 清理上下文压缩状态（server.py L1601-1606），避免摘要与回滚后的历史不一致。Cline 无对应清理（依赖 `SessionCompactionState` 的 hash 验证自动失效）。
7. **Charles 缺失 — checkpoint diff 对比视图**：Cline 有完整 `checkpoint-diff.ts`（L1-150）实现 diff 对比（`git diff --name-only` + `git show <ref>:<path>` + `fs.readFile` 双向读取），VSCode 前端有 "Compare" 按钮。Charles 未实现 diff 对比，前端仅有 "Restore" 按钮无 "Compare"。
8. **持久化粒度差异**：Cline 把 checkpoint 元信息写入 `session.metadata.checkpoint`（集中式，一个 session 一份 metadata）；Charles 消息 checkpoint 写入 `agent_data/checkpoints/<cp_id>.json`（每个 checkpoint 一个文件，分散式），文件 checkpoint 写入 `agent_data/file_checkpoints/<session_id>.json`（每个 session 一个文件）。
9. **消息回滚机制差异**：Cline 用 `runCount` 索引消息列表切片（`trimMessagesToCheckpoint` 按 user message 计数找边界）；Charles 用深拷贝消息列表直接恢复（`Checkpoint.messages` 字段保存完整快照）。Cline 节省存储但依赖消息索引稳定，Charles 浪费存储但抗消息变动。
10. **nanobot 残留**：P7.6 范围内（checkpoint.py + file_checkpoint.py + server.py checkpoint 部分 + types.py + runtime.py）共 **0 处注释残留 + 0 处实现逻辑残留**。server.py 模块级 docstring（L2/L4/L28）有 3 处 nanobot 残留，但属 P7.1 范围已审计，与 checkpoint 功能无关。

### 一致性总体评估

- **git ref 持久化机制**：**高**。双方都用 `git update-ref` 把 stash commit 注册为私有 ref，命名空间不同但机制一致。
- **回滚联动**：**高**。双方都支持"文件+消息"联动回滚，Charles 额外提供原子性保证。
- **回滚端点**：**高**。`/rollback` + `/rollback_file` 端点语义对齐 Cline `restoreType: taskAndWorkspace` + `workspace`。
- **消息快照**：**中-高**。双方都保存消息快照，但 Cline 用 runCount 索引切片，Charles 用深拷贝直接恢复。
- **Checkpoint 存储**：**中**。Cline 单一 shadow-git，Charles 双轨（消息 JSON + 文件 shadow-git），架构不同但功能等价。
- **Checkpoint diff**：**低**。Cline 有完整 diff 实现，Charles 未实现。
- **触发时机**：**中**。Cline 每个 turn 一次（beforeModel），Charles 每个写工具一次（before_tool），粒度不同。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.6.1 | Checkpoint 存储 | 单一 shadow-git：`git stash create` 生成 stash commit（checkpoint-hooks.ts L217）+ `git update-ref refs/cline/checkpoints/{sid}/{run} <commit>`（L236-238）；失败时 fallback 到 `git rev-parse HEAD`（kind: "commit"）（L190-212）；元信息存入 `session.metadata.checkpoint = { latest, history }`（L281-287） | 双轨：(a) 消息快照 `CheckpointManager` 保存消息列表深拷贝到 `agent_data/checkpoints/<cp_id>.json`（checkpoint.py L121-129）；(b) 文件快照 `FileCheckpointManager` 用 `git stash create` + `git update-ref refs/agent/checkpoints/{sid}/{ckpt} <commit>`（file_checkpoint.py L639-683）；元信息分别存入独立 JSON 文件 | 中 | 架构不同但功能等价。Cline 单一系统更简洁，Charles 双轨更清晰但维护成本高。差异：(a) Cline stash create 失败 fallback 到 HEAD commit，Charles 无 fallback（失败返回 None）；(b) Cline 元信息集中存 session.metadata，Charles 分散存独立 JSON；(c) Cline stash create 传 message 参数 `cline checkpoint session=... run=...`，Charles 不传 message |
| 7.6.2 | git ref 持久化 | `update-ref refs/cline/checkpoints/{sessionId}/{runCount} <commit>`（checkpoint-hooks.ts L236-238）；`deleteCheckpointRefs` 用 `for-each-ref --format=%(refname) refs/cline/checkpoints/{sid}/` + `update-ref -d` 批量清理（L102-121）；`retainCheckpointRefs` 在 session restore 时保留旧 ref（L123-138） | `_git_update_ref` 执行 `git update-ref <ref_name> <commit>`（file_checkpoint.py L639-683）；`_git_delete_ref` 执行 `git update-ref -d <ref_name>`（L685-715）；`clear_session` 先收集 ref 再按 workspace_root 分组清理（L296-322） | 高 | 已对齐（Stage 6.4）。差异：(a) ref 命名空间 Cline `refs/cline/checkpoints/`，Charles `refs/agent/checkpoints/`；(b) Cline `deleteCheckpointRefs` 用 `for-each-ref` 批量扫描，Charles 在 `clear_session` 中从内存缓存收集 ref 名逐个删除（无 `for-each-ref` 扫描）；(c) Cline 有 `retainCheckpointRefs` 用于 session restore 时保留旧 ref，Charles 无对应（session restore 机制不同） |
| 7.6.3 | 回滚联动 | `applyCheckpointToWorktree`（checkpoint-restore.ts L161-189）：`git rev-parse --is-inside-work-tree` 验证 + `git cat-file -e <ref>^{commit}` 验证 + `git reset --hard` + `git clean -fd` + (commit: `git reset --hard <ref>` / stash: `git stash apply <ref>`)；`restoreType: "taskAndWorkspace"` 时同时调用 `applyCheckpointToWorktree` + `trimMessagesToCheckpoint`（SdkController.ts L1417-1418） | `/rollback` 端点（server.py L1500-1619）：先调 `_try_rollback_file_for_message_checkpoint` 用 `tool_call_id` 找文件 checkpoint 并 `restore_checkpoint`（L1548-1550），文件回滚成功后才 `manager.rollback_to_checkpoint` 回滚消息（L1576），最后停止活跃 runtime + 清理压缩状态（L1593-1606） | 高 | 已对齐（Stage T5）。差异：(a) Charles 提供原子性保证（文件回滚失败中止消息回滚），Cline 无原子性保证（文件回滚失败不阻止消息回滚）；(b) Cline `applyCheckpointToWorktree` 用 `reset --hard` + `clean -fd` + `stash apply` 三步法，Charles `restore_checkpoint(full_restore=True)` 用相同三步法（file_checkpoint.py L551-612），完全对齐；(c) Charles 额外清理压缩状态（Cline 无对应）；(d) Charles 额外停止活跃 runtime（Cline 在 `cancelTask` 中处理） |
| 7.6.4 | `/rollback` 端点 | `session.restore` hub 端点（session-handlers.ts L408-510）：接收 `sessionId` + `checkpointRunCount` + `restore: { messages, workspace }`；VSCode `restoreCheckpoint`（SdkController.ts L1416-1507）封装三种 `restoreType` | `POST /rollback`（server.py L1500-1619）：接收 `session_id` + `checkpoint_id`；执行文件联动回滚 + 消息回滚 + runtime abort + 压缩状态清理 | 高 | 已对齐。差异：(a) Cline 用 `checkpointRunCount`（整数）索引，Charles 用 `checkpoint_id`（字符串）索引；(b) Cline 三种 `restoreType` 在一个端点内分支，Charles 拆为两个端点（`/rollback` 联动 + `/rollback_file` 仅文件）；(c) Cline restore 后新建 session（`restoreActiveSession`），Charles 在原 session 上恢复消息 |
| 7.6.5 | `/rollback_file` 端点 | `restoreType: "workspace"` 单独模式（SdkController.ts L1418）：仅 `applyCheckpointToWorktree` 不触动消息 | `POST /rollback_file`（server.py L1716-1771）：接收 `session_id` + `checkpoint_id`；仅调 `manager.restore_checkpoint(checkpoint_id)` 不触动消息 | 高 | 已对齐。差异：(a) Cline 在 `restoreCheckpoint` 内分支处理，Charles 独立端点；(b) Charles 默认 `full_restore=False`（仅还原 file_paths 中的文件），Cline 默认全量恢复（`reset --hard` + `clean -fd` + `stash apply`）；(c) Charles 可通过 `full_restore=True` 参数对齐 Cline 行为（file_checkpoint.py L271-276） |
| 7.6.6 | 消息快照 | `trimMessagesToCheckpoint`（checkpoint-restore.ts L106-112）：按 `runCount` 找到对应 user message 索引，切片 `messages.slice(0, index + 1)`；不保存消息内容，依赖消息列表稳定 | `CheckpointManager.save_checkpoint`（checkpoint.py L140-182）：保存消息列表深拷贝 `messages: list[dict]` 到 `Checkpoint.messages` 字段 + 持久化 JSON；`rollback_to_checkpoint` 直接恢复 `cp.messages` | 中-高 | 已对齐（功能）。差异：(a) Cline 用 runCount 索引切片（节省存储，依赖消息稳定），Charles 用深拷贝直接恢复（浪费存储，抗消息变动）；(b) Cline 消息边界用 `isVisibleCheckpointUserMessage` 判定（跳过 `recovery_notice`），Charles 消息边界用 `tool_call_id` 关联；(c) Cline 支持 `trimMessagesBeforeCheckpoint`（切片到 index 之前），Charles 无对应（回滚后清除该 checkpoint 之后的所有 checkpoint，checkpoint.py L216-223） |

---

## 三、重点差距详解

### 3.1 单一 shadow-git vs 双轨架构（架构差异，非缺陷）

这是本阶段最显著的架构差异：

**Cline 单一 shadow-git 架构**（checkpoint-hooks.ts + checkpoint-restore.ts）：
- 一个 stash commit 同时承担"文件状态快照"和"按 runCount 回滚消息"两个职责
- checkpoint 元信息存入 `session.metadata.checkpoint = { latest: CheckpointEntry, history: CheckpointEntry[] }`
- `CheckpointEntry = { ref, createdAt, runCount, kind: "stash" | "commit" }`
- 回滚时用 `runCount` 索引消息列表找边界（`trimMessagesToCheckpoint`），同时用 `ref` 恢复工作区（`applyCheckpointToWorktree`）
- 优点：单一数据源，消息回滚与文件回滚天然对齐
- 缺点：每个 checkpoint 都要 `git stash create`，非 git 仓库完全失效（fallback 到 HEAD commit）

**Charles 双轨架构**（checkpoint.py + file_checkpoint.py）：
- 消息快照（`CheckpointManager`）：保存消息列表深拷贝 JSON，不依赖 git
- 文件快照（`FileCheckpointManager`）：用 `git stash create` + 私有 ref，仅 git 仓库生效
- 两个系统通过 `tool_call_id` 关联（消息 checkpoint 和文件 checkpoint 都按 `tool_call_id` 索引）
- 联动回滚时用 `_try_rollback_file_for_message_checkpoint` 按 `tool_call_id` 查找文件 checkpoint
- 优点：消息回滚不依赖 git（非 git 仓库也能用），职责分离清晰
- 缺点：两个系统需维护一致性，联动逻辑更复杂

**影响分析**：
- Cline 在非 git 仓库时 fallback 到 HEAD commit（`kind: "commit"`），仍能回滚消息（按 runCount 切片）+ 回滚文件到 HEAD
- Charles 在非 git 仓库时消息 checkpoint 正常工作（JSON 持久化），文件 checkpoint 跳过（返回 None）
- Charles 的双轨设计在"仅消息回滚"场景下更高效（不触发 git 操作），但在"联动回滚"场景下需额外的 `tool_call_id` 关联查找

**修复建议**：**不建议修改**。Charles 的双轨设计在非 git 仓库场景下更健壮（消息 checkpoint 不依赖 git），且职责分离更清晰。若强行合并为单一 shadow-git 系统，会丢失非 git 仓库的消息回滚能力。

### 3.2 触发时机差异（beforeModel vs before_tool）

**Cline 触发时机**（checkpoint-hooks.ts L256-289）：
- `beforeRun` hook：`runCount += 1`（每个 run 自增）
- `beforeModel` hook：在 `iteration === 1` 时创建 checkpoint（每个 turn 第一次 LLM 调用前）
- 粒度：每个用户 turn 一个 checkpoint（一个 turn 内多个工具调用共享一个 checkpoint）

**Charles 触发时机**（checkpoint.py L363-393 + file_checkpoint.py L843-858）：
- `before_tool` hook：在写工具执行前创建 checkpoint
- `CheckpointHook` 仅对 `requires_approval=True` 的工具触发（checkpoint.py L372-374）
- `FileCheckpointHook` 对 `WRITE_TOOL_NAMES` + 修改文件的 `RUN_COMMANDS_TOOL_NAMES` 触发（file_checkpoint.py L328-352）
- 粒度：每个写工具一个 checkpoint（一个 turn 内 3 个写工具产生 3 个 checkpoint）

**影响分析**：
- Cline 粒度更粗：一个 turn 一个 checkpoint，回滚到 turn 开始前（包括该 turn 所有工具的修改都回滚）
- Charles 粒度更细：每个写工具一个 checkpoint，可回滚到某个工具执行前（保留之前工具的修改）
- Charles 更细粒度的好处：用户可回滚到"第 2 个工具执行前"，保留第 1 个工具的修改
- Charles 更细粒度的代价：checkpoint 数量更多，存储和 git 操作开销更大

**修复建议**：**不建议修改**。Charles 的细粒度设计在量化场景下更有价值（用户可能想保留某些工具的修改只回滚特定工具），且通过 `AGENT_ENABLE_FILE_CHECKPOINT` 环境变量可关闭文件 checkpoint 控制开销。

### 3.3 回滚模式差异（三模式 vs 两端点）

**Cline 三种回滚模式**（SdkController.ts L1416-1418 + checkpoints.mdx L50-64）：
| 模式 | restoreType | 文件回滚 | 消息回滚 | 场景 |
|------|------------|---------|---------|------|
| Restore Files | `workspace` | 是 | 否 | 代码改坏了，保留对话 |
| Restore Task Only | `task` | 否 | 是 | 对话跑偏了，保留代码 |
| Restore Files & Task | `taskAndWorkspace` | 是 | 是 | 全部重来 |

**Charles 两种回滚端点**（server.py L1500-1619 + L1716-1771）：
| 端点 | 文件回滚 | 消息回滚 | 场景 |
|------|---------|---------|------|
| `POST /rollback` | 是（联动） | 是 | 全部重来（对标 taskAndWorkspace） |
| `POST /rollback_file` | 是 | 否 | 代码改坏了（对标 workspace） |
| **缺失** | 否 | 是 | **无独立端点**（对标 task） |

**影响分析**：
- Charles 缺少"仅消息回滚"独立端点（Cline 的 `task` 模式 Charles 无直接对应）
- 用户若想"仅回滚消息保留代码"，在 Charles 中无直接 API 支持
- 但 Charles 的 `/rollback` 端点在 `AGENT_ENABLE_FILE_CHECKPOINT` 关闭时（默认）实际上只回滚消息（文件回滚跳过），相当于 Cline 的 `task` 模式

**修复建议**：**可选增强**。若需完全对齐 Cline 三模式，可在 `/rollback` 端点增加 `restore_type` 参数（`workspace` / `task` / `taskAndWorkspace`），根据参数决定是否触发文件回滚。但当前通过 `AGENT_ENABLE_FILE_CHECKPOINT` 开关已能间接实现"仅消息回滚"（关闭文件 checkpoint 时 `/rollback` 自然只回滚消息），增强非必须。

### 3.4 Checkpoint diff 对比视图（Charles 缺失）

**Cline checkpoint-diff.ts**（L1-150）：
- `listChangedPaths`：`git diff --name-only -z <ref> --` + `git ls-files --others --exclude-standard -z` 列出变更文件
- `readCheckpointFile`：`git show <ref>:<relativePath>` 读 checkpoint 版本文件内容
- `readWorktreeFile`：`fs.readFile` 读工作区当前版本文件内容
- `buildCheckpointWorkspaceDiff`：并行读取所有变更文件的两侧内容，过滤出实际有差异的文件
- `compareCheckpointToWorkspace`：完整 diff 流程入口
- VSCode 前端有 "Compare" 按钮调用此 API（checkpoints.mdx L42-46）

**Charles**：
- 无 checkpoint diff 实现
- 无 `git diff --name-only` / `git show <ref>:<path>` 调用
- 前端仅有 "Restore" 按钮无 "Compare" 按钮
- `/file_checkpoints` 端点返回 `file_paths` 列表但无两侧文件内容

**影响分析**：
- Cline 的 diff 视图让用户在回滚前能预览变更，避免误回滚
- Charles 用户只能看到 `file_paths` 列表，无法预览具体变更内容
- Charles 的 `/file_checkpoints` 端点返回 `file_paths` 但不返回文件内容差异

**修复建议**：**可选增强**。若需对齐 Cline diff 视图，可在 `FileCheckpointManager` 增加 `compare_to_workspace(checkpoint_id)` 方法，调用 `git diff --name-only <stash_commit> --` + `git show <stash_commit>:<path>` + `open(path).read()` 生成 diff。但当前 Charles 已有 `file_paths` 列表，前端可调用 `/api/chat/file_checkpoints` 获取列表后让用户自行用外部 diff 工具对比。增强非必须。

### 3.5 消息回滚机制差异（runCount 索引 vs 深拷贝恢复）

**Cline 消息回滚**（checkpoint-restore.ts L79-112）：
- `findCheckpointMessageIndex`：遍历消息列表，跳过 `recovery_notice`，按 user message 计数找 `runCount` 对应的索引
- `trimMessagesToCheckpoint`：`messages.slice(0, index + 1)` 切片
- 不保存消息内容，依赖消息列表稳定（消息不可被修改/删除/插入）
- 优点：节省存储（不保存消息副本）
- 缺点：若消息列表被修改（如压缩），索引可能错位

**Charles 消息回滚**（checkpoint.py L140-182 + L192-229）：
- `save_checkpoint`：保存消息列表深拷贝 `messages: list[dict]` 到 `Checkpoint.messages` 字段
- `rollback_to_checkpoint`：直接恢复 `cp.messages` + 清除该 checkpoint 之后的所有 checkpoint
- 优点：抗消息变动（压缩/插入/删除不影响回滚）
- 缺点：浪费存储（每个 checkpoint 保存完整消息列表副本）

**影响分析**：
- Cline 的 runCount 索引机制在压缩后可能错位（但 Cline 用 `SessionCompactionState.source_prefix_hash` 验证源消息完整性，错位时返回 undefined 不投影）
- Charles 的深拷贝机制在压缩后仍能正确回滚（恢复的是压缩前的消息快照），但 Charles 在 `/rollback` 时主动调用 `CompactionStateManager().clear(session_id)` 清理压缩状态，避免摘要与回滚后的历史不一致
- Charles 的深拷贝机制在长会话场景下存储开销大（20 个 checkpoint × 每个几百条消息 = 上万条消息副本）

**修复建议**：**不建议修改**。Charles 的深拷贝 + 压缩状态清理策略在当前场景下足够。改用 runCount 索引机制需引入 hash 验证逻辑（对标 Cline `SessionCompactionState`），对 Python 生态过度设计。Charles 的 `_MAX_CHECKPOINTS_PER_SESSION = 20` 限制了存储开销（checkpoint.py L83）。

### 3.6 持久化粒度差异

**Cline 持久化粒度**（checkpoint-hooks.ts L275-287 + session-snapshot.ts L53）：
- checkpoint 元信息写入 `session.metadata.checkpoint = { latest, history }`
- `CheckpointMetadata = { latest: CheckpointEntry, history: CheckpointEntry[] }`
- 一个 session 一份 metadata，checkpoint 历史集中存储
- 优点：一次读取获取全部 checkpoint 历史
- 缺点：metadata 文件可能过大（长会话 checkpoint 历史多）

**Charles 持久化粒度**（checkpoint.py L105-129 + file_checkpoint.py L721-785）：
- 消息 checkpoint：每个 checkpoint 一个 JSON 文件 `agent_data/checkpoints/<cp_id>.json`
- 文件 checkpoint：每个 session 一个 JSON 文件 `agent_data/file_checkpoints/<session_id>.json`（含所有 checkpoint）
- 优点：消息 checkpoint 独立文件，删除单个 checkpoint 不影响其他
- 缺点：消息 checkpoint 文件多（20 个 checkpoint = 20 个文件），加载时需遍历目录

**影响分析**：
- Cline 集中式存储更适合 session metadata 已持久化的场景（checkpoint 作为 metadata 的一部分）
- Charles 分散式存储更适合 session metadata 不直接持久化的场景（checkpoint 独立于 session）
- Charles 的文件 checkpoint 用 `FileLock` 保护跨进程访问（file_checkpoint.py L761-765），Cline 无显式文件锁（依赖 session metadata 的原子写入）

**修复建议**：**不建议修改**。两种粒度各有优劣，当前实现均能工作。

### 3.7 stash create 实现细节差异

**Cline `git stash create`**（checkpoint-hooks.ts L214-228）：
- 传 message 参数：`git stash create "cline checkpoint session=... run=..."`
- stash create 失败时 fallback 到 `git rev-parse HEAD`（kind: "commit"）
- stash create 返回空（工作区无变更）时也 fallback 到 HEAD commit
- 不执行 `git add -A`（stash create 默认只捕获已跟踪文件的变更，未跟踪文件不捕获）

**Charles `git stash create`**（file_checkpoint.py L387-477）：
- 不传 message 参数：`git stash create`
- stash create 失败返回 None（无 fallback）
- stash create 返回空字符串表示工作区无变更（不 fallback 到 HEAD，回滚时无操作）
- 三步法：`git add -A`（暂存所有变更含未跟踪文件）→ `git stash create` → `git reset -q`（恢复 index）
- 优点：捕获未跟踪文件（agent 新建的文件也能回滚）

**影响分析**：
- Cline 不捕获未跟踪文件（stash create 默认不包含 untracked files），若 agent 创建新文件后回滚，新文件不会被删除
- Charles 通过 `git add -A` 捕获未跟踪文件，agent 创建新文件后回滚能删除新文件
- Charles 的三步法更完整但开销更大（额外的 `git add -A` + `git reset -q`）
- Cline 的 fallback 到 HEAD commit 保证了非 git 仓库或 stash create 失败时仍能回滚到 HEAD

**修复建议**：**不建议修改**。Charles 的三步法更适合量化场景（agent 经常创建新文件如报告/图表），Cline 的 fallback 机制更健壮。两者各有优势。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P7.6 范围内涉及以下 5 个文件：
- `agent/checkpoint.py`（447 行）
- `agent/file_checkpoint.py`（860 行）
- `agent/server.py` L1454-1772（checkpoint API 端点部分，约 320 行）
- `agent/types.py` L740-742（checkpoint 事件常量）
- `agent/runtime.py` L1279-1290（before_tool hook 注册点）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/checkpoint.py` | **0 处** | 0 处 | 全文无 "nanobot" 字样。所有 docstring 均对标 Cline（"对标 Cline checkpoint" / "对标 Cline checkpoint manager" / "对标 Cline saveCheckpoint" / "对标 Cline rollbackToCheckpoint" / "对标 Cline checkpoint hook"） |
| `agent/file_checkpoint.py` | **0 处** | 0 处 | 全文无 "nanobot" 字样。所有 docstring 均对标 Cline（"对标 Cline shadow-git checkpoint 机制" / "对标 Cline CheckpointRef" / "对标 Cline shadow-git checkpoint" / "对标 Cline beforeTool checkpoint" / "对标 Cline checkpoint-hooks.ts L236-238 git update-ref" / "对标 Cline deleteCheckpointRefs" / "对标 Cline applyCheckpointToWorktree"） |
| `agent/server.py` L1454-1772 | **0 处** | 0 处 | checkpoint API 端点部分（L1454-1772）无 "nanobot" 字样。所有注释均对标 Cline（"Phase 21: 检查点 API — 对标 Cline checkpoint / rollback" / "对标 Cline checkpoint-restore.ts 的'消息+文件'原子性恢复" / "对标 Cline applyCheckpointToWorktree 的'消息+文件'组合恢复" / "Phase 33.2: 文件状态快照 checkpoint API — 对标 Cline shadow-git checkpoint"） |
| `agent/types.py` L740-742 | **0 处** | 0 处 | `CHECKPOINT_CREATED = "checkpoint.created"` / `CHECKPOINT_RESTORED = "checkpoint.restored"` 注释为"Checkpoint 事件 — 对标 Cline checkpoint 事件组"，无 nanobot 引用 |
| `agent/runtime.py` L1279-1290 | **0 处** | 0 处 | `before_tool` hook 注册点无 nanobot 引用（注释为"对标 Cline loop-detection beforeTool hook"） |

**P7.6 范围内 nanobot 残留总计：0 处注释残留 + 0 处实现逻辑残留。**

### 4.3 范围外残留说明

`agent/server.py` 模块级 docstring（L2/L4/L28）有 3 处 nanobot 残留：
- L2：`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`
- L4：`提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`
- L28：`对标 nanobot:`

**此残留属 P7.1 范围已审计**（见 phase_7.1_context_compression.md 第 4.2 节），与 checkpoint 功能无关（checkpoint 端点在 L1454-1772，无 nanobot 引用）。此处仅列出供参考，不在本阶段修复。

---

## 五、修复建议

### 5.1 不建议修改：单一 shadow-git vs 双轨架构

**问题**：Cline 单一 shadow-git 系统，Charles 双轨（消息 JSON + 文件 shadow-git）。

**修复建议**：**不建议修改**。Charles 的双轨设计在非 git 仓库场景下更健壮（消息 checkpoint 不依赖 git），且职责分离更清晰。若强行合并为单一 shadow-git 系统，会丢失非 git 仓库的消息回滚能力。

### 5.2 不建议修改：触发时机差异（beforeModel vs before_tool）

**问题**：Cline 在 `beforeModel` iteration=1 时触发（每个 turn 一次），Charles 在 `before_tool` 写工具时触发（每个写工具一次）。

**修复建议**：**不建议修改**。Charles 的细粒度设计在量化场景下更有价值（用户可能想保留某些工具的修改只回滚特定工具）。改用 Cline 的 per-turn 粒度会丢失细粒度回滚能力。

### 5.3 可选增强：增加"仅消息回滚"端点

**问题**：Charles 缺少独立的"仅消息回滚"端点（Cline 的 `restoreType: "task"` 模式 Charles 无直接对应）。

**修复建议**：**可选增强**。在 `/rollback` 端点增加 `restore_type` 参数（`workspace` / `task` / `taskAndWorkspace`），根据参数决定是否触发文件回滚。或新增 `POST /rollback_message` 端点仅回滚消息。

**权衡**：当前通过 `AGENT_ENABLE_FILE_CHECKPOINT` 开关已能间接实现"仅消息回滚"（关闭文件 checkpoint 时 `/rollback` 自然只回滚消息），增强非必须。若前端需要更细粒度控制，可考虑增加。

### 5.4 可选增强：实现 checkpoint diff 对比视图

**问题**：Charles 未实现 checkpoint diff 对比视图，前端无 "Compare" 按钮。

**修复建议**：**可选增强**。在 `FileCheckpointManager` 增加 `compare_to_workspace(checkpoint_id)` 方法：
1. `git diff --name-only -z <stash_commit> --` 列出变更文件
2. `git show <stash_commit>:<path>` 读 checkpoint 版本
3. `open(path).read()` 读工作区版本
4. 返回 `[{ file_path, left_content, right_content }]`

并新增 `GET /api/chat/file_checkpoints/diff?checkpoint_id=xxx` 端点。

**权衡**：当前 Charles 已有 `file_paths` 列表，前端可调用 `/api/chat/file_checkpoints` 获取列表后让用户自行用外部 diff 工具对比。增强非必须，但能提升用户体验。

### 5.5 不建议修改：消息回滚机制差异（runCount 索引 vs 深拷贝恢复）

**问题**：Cline 用 runCount 索引切片（节省存储），Charles 用深拷贝直接恢复（抗消息变动）。

**修复建议**：**不建议修改**。Charles 的深拷贝 + 压缩状态清理策略在当前场景下足够。改用 runCount 索引机制需引入 hash 验证逻辑（对标 Cline `SessionCompactionState`），对 Python 生态过度设计。`_MAX_CHECKPOINTS_PER_SESSION = 20` 已限制存储开销。

### 5.6 不建议修改：stash create 实现细节差异

**问题**：Cline 不捕获未跟踪文件 + fallback 到 HEAD，Charles 捕获未跟踪文件 + 无 fallback。

**修复建议**：**不建议修改**。Charles 的三步法（`git add -A` + `git stash create` + `git reset -q`）更适合量化场景（agent 经常创建新文件如报告/图表）。Cline 的 fallback 机制更健壮但不捕获未跟踪文件。两者各有优势。

---

## 六、验证方法

### 6.1 git ref 持久化验证

1. 读取 Cline `checkpoint-hooks.ts` L236-238，确认 `git update-ref refs/cline/checkpoints/{sessionId}/{runCount} <commit>`
2. 读取 Charles `file_checkpoint.py` L639-683 `_git_update_ref`，确认 `git update-ref refs/agent/checkpoints/{session_id}/{checkpoint_id} <commit>`
3. 确认 ref 命名空间不同（`cline` vs `agent`）但机制一致

### 6.2 回滚联动验证

1. 读取 Cline `checkpoint-restore.ts` L161-189 `applyCheckpointToWorktree`，确认三步法：`reset --hard` + `clean -fd` + `stash apply`
2. 读取 Charles `file_checkpoint.py` L551-612 `_git_full_restore`，确认相同三步法
3. 读取 Charles `server.py` L1538-1573，确认文件回滚失败时中止消息回滚（原子性保证）
4. 读取 Charles `server.py` L1601-1606，确认回滚后清理压缩状态

### 6.3 `/rollback` 端点验证

1. 读取 Cline `session-handlers.ts` L408-510 `handleSessionRestore`，确认接收 `sessionId` + `checkpointRunCount` + `restore: { messages, workspace }`
2. 读取 Charles `server.py` L1500-1619 `rollback_to_checkpoint`，确认接收 `session_id` + `checkpoint_id`
3. 确认 Charles `/rollback` 联动文件回滚 + 消息回滚 + runtime abort + 压缩状态清理

### 6.4 `/rollback_file` 端点验证

1. 读取 Cline `SdkController.ts` L1418，确认 `restoreType: "workspace"` 仅 `applyCheckpointToWorktree` 不触动消息
2. 读取 Charles `server.py` L1716-1771 `rollback_file_checkpoint`，确认仅调 `manager.restore_checkpoint` 不触动消息
3. 确认 Charles 默认 `full_restore=False`（仅还原 file_paths），可通过参数对齐 Cline 全量恢复

### 6.5 消息快照验证

1. 读取 Cline `checkpoint-restore.ts` L79-112 `findCheckpointMessageIndex` + `trimMessagesToCheckpoint`，确认按 runCount 索引切片
2. 读取 Charles `checkpoint.py` L140-182 `save_checkpoint`，确认保存消息列表深拷贝
3. 读取 Charles `checkpoint.py` L192-229 `rollback_to_checkpoint`，确认直接恢复 `cp.messages` + 清除后续 checkpoint

### 6.6 checkpoint diff 验证（Charles 缺失）

1. 读取 Cline `checkpoint-diff.ts` L76-90 `listChangedPaths`，确认 `git diff --name-only -z <ref> --` + `git ls-files --others --exclude-standard -z`
2. 读取 Cline `checkpoint-diff.ts` L53-63 `readCheckpointFile`，确认 `git show <ref>:<relativePath>`
3. 确认 Charles 无对应实现（Grep `agent/file_checkpoint.py` 搜索 `diff` / `compare` / `show`，无匹配）

### 6.7 nanobot 残留验证

1. Grep `agent/checkpoint.py` 搜索 `nanobot`（case-insensitive），确认 0 匹配
2. Grep `agent/file_checkpoint.py` 搜索 `nanobot`，确认 0 匹配
3. Grep `agent/server.py` L1454-1772 搜索 `nanobot`，确认 0 匹配
4. Grep `agent/types.py` L740-742 搜索 `nanobot`，确认 0 匹配
5. Grep `agent/runtime.py` L1279-1290 搜索 `nanobot`，确认 0 匹配

---

## 七、附录

### 7.1 Cline Checkpoint 架构图

```
createCheckpointHooks (checkpoint-hooks.ts L155-291)
    ├── beforeRun hook: runCount += 1 (L256-262)
    ├── beforeModel hook (L263-289):
    │   ├── iteration=1 时触发
    │   ├── createCheckpoint() (L177-253):
    │   │   ├── ensureGitRepository() 验证 git 仓库
    │   │   ├── git stash create "cline checkpoint session=... run=..."
    │   │   ├── 失败 fallback 到 git rev-parse HEAD (kind: "commit")
    │   │   ├── git update-ref refs/cline/checkpoints/{sid}/{run} <commit>
    │   │   └── 返回 CheckpointEntry { ref, createdAt, runCount, kind }
    │   ├── readSessionMetadata() 读取现有 metadata
    │   ├── upsertCheckpointHistory() 更新 history
    │   └── writeSessionMetadata() 写回 metadata
    │
    ├── deleteCheckpointRefs (L102-121):
    │   ├── git for-each-ref --format=%(refname) refs/cline/checkpoints/{sid}/
    │   └── git update-ref -d <ref> (批量)
    │
    └── retainCheckpointRefs (L123-138):
        └── git update-ref refs/cline/checkpoints/{sid}/{runCount} <ref> (session restore 时保留)

applyCheckpointToWorktree (checkpoint-restore.ts L161-189)
    ├── git rev-parse --is-inside-work-tree (验证 git 仓库)
    ├── git cat-file -e <ref>^{commit} (验证 commit 存在)
    ├── git reset --hard (丢弃工作区修改)
    ├── git clean -fd (删除未跟踪文件)
    └── commit: git reset --hard <ref> / stash: git stash apply <ref>

restoreCheckpoint (SdkController.ts L1416-1507)
    ├── restoreType: "workspace" → 仅 applyCheckpointToWorktree
    ├── restoreType: "task" → 仅 trimMessagesToCheckpoint + 新建 session
    └── restoreType: "taskAndWorkspace" → workspace + task

checkpoint-diff.ts (L1-150)
    ├── listChangedPaths: git diff --name-only -z <ref> -- + git ls-files --others --exclude-standard -z
    ├── readCheckpointFile: git show <ref>:<relativePath>
    ├── readWorktreeFile: fs.readFile(<absolutePath>)
    └── buildCheckpointWorkspaceDiff: 并行读取两侧内容，过滤有差异文件
```

### 7.2 Charles Checkpoint 架构图

```
消息 Checkpoint (checkpoint.py L60-293)
    ├── CheckpointManager
    │   ├── save_checkpoint (L140-182):
    │   │   ├── 生成 cp_<uuid> ID
    │   │   ├── 创建 Checkpoint dataclass (messages 深拷贝)
    │   │   ├── _persist_checkpoint 写入 agent_data/checkpoints/<cp_id>.json
    │   │   └── _evict_if_needed 超限清理 (MAX=20)
    │   ├── rollback_to_checkpoint (L192-229):
    │   │   ├── 验证 checkpoint 存在 + session 匹配
    │   │   ├── 清除该 checkpoint 之后的所有 checkpoint
    │   │   └── 返回 True (消息列表由调用方恢复)
    │   ├── clear_checkpoints (L231-247): 清除 session 所有 checkpoint
    │   └── load_all (L270-292): 启动时从磁盘恢复
    │
    └── CheckpointHook (L333-393)
        └── before_tool: requires_approval=True 时 save_checkpoint

文件 Checkpoint (file_checkpoint.py L133-860)
    ├── FileCheckpointManager
    │   ├── save_checkpoint (L175-240):
    │   │   ├── _is_write_tool 判断 (WRITE_TOOL_NAMES + RUN_COMMANDS)
    │   │   ├── _git_stash_create 三步法:
    │   │   │   ├── git add -A (暂存所有变更含未跟踪)
    │   │   │   ├── git stash create (生成悬空 commit)
    │   │   │   └── git reset -q (恢复 index)
    │   │   ├── _git_update_ref refs/agent/checkpoints/{sid}/{ckpt} <commit>
    │   │   ├── _extract_file_paths 提取文件路径
    │   │   └── _persist_session 写入 agent_data/file_checkpoints/<sid>.json
    │   ├── restore_checkpoint (L242-284):
    │   │   ├── full_restore=False: _git_checkout_files (git checkout <commit> -- <paths>)
    │   │   └── full_restore=True: _git_full_restore (reset --hard + clean -fd + stash apply)
    │   ├── clear_session (L296-322): 先收集 ref 调 git update-ref -d 清理，再删缓存
    │   └── _git_update_ref / _git_delete_ref (L639-715)
    │
    └── create_before_tool_checkpoint_hook (L824-858)
        └── before_tool: 写工具执行前 save_checkpoint

server.py 端点 (L1454-1772)
    ├── GET /checkpoints (L1458-1497): 列出消息 checkpoint
    ├── POST /rollback (L1500-1619):
    │   ├── _try_rollback_file_for_message_checkpoint (L1622-1654):
    │   │   └── 按 tool_call_id 找文件 checkpoint 并 restore_checkpoint
    │   ├── manager.rollback_to_checkpoint 回滚消息
    │   ├── _session_manager.update 恢复消息列表
    │   ├── runtime.abort 停止活跃 runtime
    │   └── CompactionStateManager().clear 清理压缩状态
    ├── DELETE /checkpoints (L1657-1672): 清除消息 checkpoint
    ├── GET /file_checkpoints (L1681-1713): 列出文件 checkpoint
    └── POST /rollback_file (L1716-1771): 仅回滚文件
```

### 7.3 双方回滚模式对比

| 场景 | Cline restoreType | Charles 端点 | 文件回滚 | 消息回滚 | 一致性 |
|------|-------------------|-------------|---------|---------|--------|
| 代码改坏了，保留对话 | `workspace` | `POST /rollback_file` | 是 | 否 | 高 |
| 对话跑偏了，保留代码 | `task` | **无独立端点**（关闭 `AGENT_ENABLE_FILE_CHECKPOINT` 时 `/rollback` 间接实现） | 否 | 是 | 中 |
| 全部重来 | `taskAndWorkspace` | `POST /rollback` | 是 | 是 | 高 |
| 预览变更后决定是否回滚 | `compareCheckpointToWorkspace` | **未实现** | — | — | 低 |

### 7.4 双方 git ref 命名空间对比

| 属性 | Cline | Charles |
|------|-------|---------|
| ref 前缀 | `refs/cline/checkpoints/` | `refs/agent/checkpoints/` |
| ref 路径格式 | `{prefix}{sessionId}/{runCount}` | `{prefix}{sessionId}/{checkpointId}` |
| 索引键 | `runCount`（整数，自增） | `checkpointId`（字符串，含时间戳） |
| 批量清理 | `for-each-ref` 扫描 + `update-ref -d` | 从内存缓存收集 + `update-ref -d` |
| session restore 时保留 | `retainCheckpointRefs` | 无对应（session restore 机制不同） |

### 7.5 双方 stash create 对比

| 属性 | Cline | Charles |
|------|-------|---------|
| 命令 | `git stash create "cline checkpoint session=... run=..."` | `git stash create`（无 message） |
| 未跟踪文件捕获 | 否（stash create 默认不捕获 untracked） | 是（先 `git add -A` 再 stash create） |
| 失败 fallback | `git rev-parse HEAD`（kind: "commit"） | 无（返回 None） |
| 空工作区处理 | fallback 到 HEAD commit | 返回空字符串（回滚时无操作） |
| index 恢复 | 不需要（未执行 `git add`） | `git reset -q` 恢复 index |
| 超时处理 | 无（依赖 execFile 默认超时） | 15s 超时 + 尝试恢复 index |
