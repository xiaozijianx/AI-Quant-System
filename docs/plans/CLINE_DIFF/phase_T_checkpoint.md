# Phase T: Checkpoint 机制 对比报告

> 对标源码：`third_party/cline/apps/vscode/src/core/controller/checkpoints/checkpointRestore.ts` + `third_party/cline/sdk/packages/core/src/hooks/checkpoint-hooks.ts` + `third_party/cline/sdk/packages/core/src/session/checkpoint-restore.ts` + `third_party/cline/sdk/packages/core/src/session/checkpoint-diff.ts` + `third_party/cline/sdk/packages/core/src/types/config.ts`（CoreCheckpointConfig）+ `third_party/cline/sdk/packages/core/src/services/local-runtime-bootstrap.ts`（hook 集成）
> 当前实现：`agent/checkpoint.py`（消息列表快照）+ `agent/file_checkpoint.py`（文件状态快照 shadow-git）+ `agent/server.py`（检查点 API 端点）+ 环境变量 `AGENT_ENABLE_FILE_CHECKPOINT`
> 对比维度：T1-T10

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 2 项 |
| 弱对齐 | 6 项 |
| 缺失 | 0 项 |
| 额外增强 | 2 项 |
| **对齐度** | **约 60%** |

**总体评价**：

我的实现采用"双轨制"——`checkpoint.py` 保存会话消息列表快照（Phase 21），`file_checkpoint.py` 保存工作区文件状态快照（Phase 33.2，对标 Cline shadow-git）。两者互补但分离，与 Cline 的"单轨 + 消息 trim"模型在语义上存在显著差异。

核心差距集中在三处：
1. **创建时机粒度**（T1）：我按"每工具"创建，Cline 按"每轮（root-agent run）"创建，粒度更细但存储开销更大。
2. **git ref 持久化**（T3/T6）：Cline 用 `update-ref` 将 stash commit 写入私有 ref 命名空间 `refs/cline/checkpoints/{sessionId}/{runCount}`，保证 GC-safe；我用悬空 commit（dangling），存在被 `git gc` 回收的风险。
3. **回滚语义**（T5）：Cline 做"全工作区恢复（reset --hard + clean -fd + stash apply）+ 消息 trim + fork 新 session"的完整原子操作；我将文件恢复与消息恢复分离，且文件恢复仅 `git checkout <commit> -- <paths>` 还原指定文件，语义不等价。

合理增强：未跟踪文件处理（T10）我通过 `git add -A` 将未跟踪文件纳入快照，可回滚文件创建操作；Cline 的 `git stash create` 不含未跟踪文件，且 restore 时 `clean -fd` 会删除未跟踪文件（破坏性，无法恢复）。

---

## 2. 详细对比表

| # | 对比项 | Cline 实现 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| T1 | 检查点创建时机 | `checkpoint-hooks.ts` L256-262：`beforeRun` 递增 runCount + `beforeModel`（iteration===1 时创建），每轮 root-agent run 一次 | `checkpoint.py` L363-393 + `file_checkpoint.py` L629-644：`before_tool` hook，每个写工具执行前 | 弱对齐 |
| T2 | 检查点内容 | `checkpoint-hooks.ts` L247-252：仅文件状态快照（stash ref + runCount + createdAt），消息不在 checkpoint 中 | `checkpoint.py` L56：消息列表深拷贝 + `file_checkpoint.py` L100-108：stash_commit + file_paths | 额外增强 |
| T3 | git stash 实现 | `checkpoint-hooks.ts` L217-238：`git stash create <msg>` + `git update-ref refs/cline/checkpoints/{sid}/{run} <ref>`，无 add -A，失败回退 HEAD | `file_checkpoint.py` L339-429：`git add -A` → `git stash create` → `git reset -q`，无 update-ref，无 HEAD 回退 | 弱对齐 |
| T4 | 检查点查询 | `checkpoint-restore.ts` L18-51：`readSessionCheckpointHistory(session)` 从 session.metadata 读取 + `findCheckpointForRun` | `checkpoint.py` L184-190 + `file_checkpoint.py` L256-264 + `server.py` L1159/L1293 API 端点 | 完全一致 |
| T5 | 回滚语义 | `checkpoint-restore.ts` L161-189：`reset --hard` + `clean -fd` + (commit: `reset --hard <ref>` / stash: `stash apply <ref>`) + `trimMessagesToCheckpoint` + fork 新 session | `checkpoint.py` L192-229 恢复消息+清除后续 + `file_checkpoint.py` L228-254 `git checkout <commit> -- <paths>` 仅指定文件 + `server.py` L1240-1254 停止 runtime | 弱对齐 |
| T6 | 持久化 | `checkpoint-hooks.ts` L236-238 + `checkpoint-restore.ts` L18-51：checkpoint 元数据存 session.metadata.checkpoint + git ref 存 refs/cline/checkpoints/...（GC-safe） | `checkpoint.py` L121-129 单文件 JSON + `file_checkpoint.py` L534-553 per-session JSON + FileLock；无 git ref 持久化 | 弱对齐 |
| T7 | 清理机制 | `checkpoint-hooks.ts` L102-121 `deleteCheckpointRefs`（session 删除时清理 git ref）+ `checkpoint-restore.ts` L53-62 restore 时按 runCount 过滤 history | `checkpoint.py` L249-268 FIFO 淘汰（max 20/session）+ `file_checkpoint.py` L266-274 手动 clear_session；均不清理 git stash 对象 | 弱对齐 |
| T8 | 启用开关 | `config.ts` L198-204 + `local-runtime-bootstrap.ts` L419：`checkpoint.enabled`（默认 false，opt-in），单一配置，可自定义 createCheckpoint | `server.py` L417-421 CheckpointHook 始终启用 + `server.py` L427 AGENT_ENABLE_FILE_CHECKPOINT 环境变量控制 FileCheckpointHook | 弱对齐 |
| T9 | shadow-git 仓库 | `checkpoint-hooks.ts` L166-175 + L236：使用用户实际 git 仓库（cwd），无独立 shadow-git 仓库，私有 ref 命名空间隐藏 stash | `file_checkpoint.py` L487-501 使用用户 git 仓库（workspace_root），无独立 shadow-git 仓库，无私有 ref 命名空间 | 完全一致 |
| T10 | 未跟踪文件处理 | `checkpoint-hooks.ts` L217 `git stash create` 无 `--include-untracked`，未跟踪文件不在快照中；`checkpoint-restore.ts` L179 `clean -fd` 删除未跟踪文件（破坏性） | `file_checkpoint.py` L358-367 `git add -A` 在 stash create 前暂存未跟踪文件，纳入快照；restore 时 `checkout <commit> -- <paths>` 可恢复 | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #T1：检查点创建时机粒度不同（每工具 vs 每轮）

**严重度**：P2（功能可用，但粒度与存储开销与 Cline 不一致）

**Cline 实现**：
- `checkpoint-hooks.ts` L256-262：`beforeRun` 钩子在 root-agent run 开始时递增 `runCount`。
- `checkpoint-hooks.ts` L263-289：`beforeModel` 钩子仅在 `iteration === 1`（每轮首次模型调用前）创建 checkpoint。
- 即：每个用户轮次（root-agent run）创建一次 checkpoint，与具体执行了几个工具无关。
- 子 agent（`parentAgentId != null`）跳过 checkpoint 创建（L265-266）。

**我的实现**：
- `checkpoint.py` L363-393（CheckpointHook）：`before_tool` 钩子，在 `requires_approval=True` 的工具执行前保存。
- `file_checkpoint.py` L629-644（create_before_tool_checkpoint_hook）：`before_tool` 钩子，在写工具（editor/apply_patch/file_write/exec 等）执行前保存。
- 即：每个写工具执行前创建一次 checkpoint，一轮可能创建多次。

**影响**：
- 我的粒度更细，可在工具级别回滚（如多步编辑中回滚到中间某步）；Cline 仅支持轮次级回滚。
- 存储开销更大：一轮执行 5 个写工具，我创建 5 个 checkpoint，Cline 仅 1 个。
- 我的 CheckpointHook 不区分 root agent 与 subagent（无 parentAgentId 检查），可能与子 agent 场景冲突。

**修复建议**：
- 短期：保留 per-tool 粒度（更细的回滚能力是合理增强），但为 CheckpointHook 增加 root-agent 判断（参考 Cline L265-266 的 parentAgentId 检查）。
- 中期：可增加"per-run 模式"配置开关，让用户选择粒度。

**优先级**：P2

---

### 差距 #T3：git stash 实现与 ref 持久化缺失

**严重度**：P1（GC 安全性风险，长期运行可能丢失 checkpoint）

**Cline 实现**：
- `checkpoint-hooks.ts` L217：`git stash create <message>`（带描述性 message，便于排查）。
- L226-228：stash create 返回空（工作区无变更）时回退到 `git rev-parse HEAD`，创建 `kind: "commit"` 类型的 checkpoint。
- L236-238：`git update-ref refs/cline/checkpoints/{sessionId}/{runCount} <ref>`，将 stash commit 写入私有 ref 命名空间。
  - 私有 ref 不污染用户 `git stash list`（`refs/stash` 才是 stash list 数据源）。
  - ref 使 stash 对象可达（reachable），不会被 `git gc` 回收（GC-safe）。
- L223-224：stash create 失败时也回退到 HEAD checkpoint。

**我的实现**：
- `file_checkpoint.py` L358-367：`git add -A`（暂存所有变更含未跟踪文件）。
- L376-384：`git stash create`（无 message 参数）。
- L387-395：`git reset -q`（恢复 index 到 HEAD，撤回 `git add -A` 的暂存）。
- L404-408：stash create 返回空时返回空字符串 `""`（标记"无变更"），不回退到 HEAD。
- 无 `git update-ref`：stash commit 是悬空对象（dangling），依赖 git 默认 30 天 reflog 保留期，过期后可能被 `git gc` 回收。

**影响**：
1. **GC 风险**：长时间运行的会话，早期的 stash commit 可能被 `git gc --prune=now` 回收，导致回滚失败（`cat-file -e <ref>^{commit}` 报错）。Cline 的 `update-ref` 使对象永久可达，无此风险。
2. **无 HEAD 回退**：工作区干净时我返回空字符串，回滚时跳过（L448-451）；Cline 仍创建 HEAD checkpoint，记录"该轮无变更"的事实，可用于 diff 比较。
3. **stash list 可见性**：我的悬空 stash 不在 `git stash list` 中（因为未 `stash store`），与 Cline 行为一致；但 Cline 通过私有 ref 显式管理，更规范。
4. **`git add -A` 副作用**：我的三步法在并发场景下有竞态风险（add -A 与 reset 之间若有其他 git 操作会受影响）；Cline 的 `stash create` 是原子操作。

**修复建议**：
- 短期：在 `_git_stash_create` 成功后增加 `git update-ref refs/cline/checkpoints/{session_id}/{tool_call_id} <commit>`，保证 GC-safe；回滚时用 ref 而非裸 commit。
- 中期：增加 HEAD 回退逻辑（工作区无变更时记录 HEAD commit 作为 checkpoint）。
- 长期：考虑用 `git stash create --include-untracked` 替代 `git add -A` + `stash create` 的三步法，避免竞态。

**优先级**：P1

---

### 差距 #T5：回滚语义不等价（分离式 vs 组合式 + 部分 vs 全量）

**严重度**：P1（语义不等价，回滚完整性有缺口）

**Cline 实现**：
- `checkpoint-restore.ts` L161-189（`applyCheckpointToWorktree`）：
  1. `git reset --hard`（丢弃当前工作区所有修改）
  2. `git clean -fd`（删除未跟踪文件和目录）
  3. 若 `kind === "commit"`：`git reset --hard <ref>`（恢复到该 commit）
  4. 若 `kind === "stash"`：`git stash apply <ref>`（应用 stash 恢复工作区）
- `checkpoint-restore.ts` L106-112（`trimMessagesToCheckpoint`）：将消息列表截断到该 runCount 对应的 user message。
- `session-versioning-service.ts` L200-224：restore 时创建 FORKED session（新 sessionId），不修改原 session；`retainCheckpointRefs` 将原 session 的 ref 历史迁移到新 session。
- 即：**文件全量恢复 + 消息截断 + session fork**，三者原子完成。

**我的实现**：
- `checkpoint.py` L192-229（`rollback_to_checkpoint`）：
  - 恢复消息列表（从 checkpoint.messages 深拷贝）。
  - 清除该 checkpoint 之后的所有 checkpoint。
  - 不触碰文件系统。
- `file_checkpoint.py` L228-254（`restore_checkpoint`）：
  - `git checkout <stash_commit> -- <paths>`（仅还原 file_paths 中指定的文件）。
  - file_paths 为空时还原整个工作区（`git checkout <commit> -- .`）。
  - 不做 `git reset --hard`，不做 `git clean -fd`。
- `server.py` L1228-1254（rollback 端点）：
  - 调用 `rollback_to_checkpoint` 恢复消息。
  - 停止活跃 runtime（`runtime.abort`）。
  - 清理压缩状态（`CompactionStateManager().clear`）。
  - 不调用文件回滚。
- 即：**文件恢复与消息恢复分离**，需用户分别调用 `/rollback`（消息）和 `/rollback_file`（文件）；文件恢复仅还原指定文件，非全量。

**影响**：
1. **回滚不完整**：用户调用 `/rollback` 恢复消息后，工具已修改的文件仍停留在修改后状态，需额外调用 `/rollback_file`。Cline 一次调用完成文件 + 消息恢复。
2. **文件恢复部分化**：我的 `git checkout <commit> -- <paths>` 仅还原 file_paths 中的文件。若工具修改了 file_paths 之外的文件（如 run_commands 执行 `rm -rf` 删除了未提取的文件），这些修改无法回滚。Cline 的 `reset --hard + clean -fd` 恢复整个工作区到 stash 时的状态。
3. **原地修改 vs fork**：我原地修改 session（可能丢失"回滚前"状态）；Cline fork 新 session，原 session 保留，支持"撤销回滚"。
4. **未跟踪文件**：我的 restore 不删除工具新建的未跟踪文件（仅 checkout 已跟踪文件）；Cline 的 `clean -fd` 会删除（但 Cline 的 stash 不含未跟踪文件，新建文件无法恢复——这是 Cline 的弱点）。

**修复建议**：
- 短期：在 `/rollback` 端点中联动调用文件回滚（若 AGENT_ENABLE_FILE_CHECKPOINT 启用），实现"消息 + 文件"组合恢复。
- 中期：file_checkpoint 的 restore 改为 `git reset --hard <stash_commit>` + `git clean -fd`（全量恢复），与 Cline 对齐；但保留 file_paths 优化（仅当 file_paths 非空时用 checkout）。
- 长期：考虑 fork session 模式（回滚生成新 session，保留原 session）。

**优先级**：P1

---

### 差距 #T6：git ref 未持久化（GC 风险）

**严重度**：P1（与 T3 相关，长期运行 checkpoint 可能失效）

**Cline 实现**：
- `checkpoint-hooks.ts` L236-238：`git update-ref refs/cline/checkpoints/{sessionId}/{runCount} <ref>` 将 stash commit 注册为私有 ref。
- `checkpoint-restore.ts` L173-177：restore 前用 `git cat-file -e <ref>^{commit}` 验证 commit 存在。
- `session-versioning-service.ts` L219-223：fork session 时 `retainCheckpointRefs` 将 ref 迁移到新 sessionId。
- `persistence-service.ts` L574/L588：session 删除时 `deleteCheckpointRefs` 清理所有 ref。
- 即：**git ref 随 session 生命周期管理**，保证 stash 对象始终可达。

**我的实现**：
- `checkpoint.py` L121-129：每个 checkpoint 持久化为单独 JSON 文件（`cp_*.json`），含 messages 列表。
- `file_checkpoint.py` L534-553：per-session JSON 文件（`<session_id>.json`）含 CheckpointRef 列表，用 FileLock 保护。
- 均不持久化 git ref：stash_commit 字段记录了 commit hash，但 git 端无 ref 引用，对象为悬空状态。

**影响**：
- git 默认 30 天后清理悬空对象（`gc.reflogExpire` / `gc.pruneExpire`），长期运行的会话回滚到早期 checkpoint 时 `git checkout <commit>` 会失败（`fatal: invalid reference`）。
- 进程重启后我的 JSON 元数据可恢复（load_all / _load_session），但若 git 对象已被回收，restore 仍失败。

**修复建议**：
- 短期：`_git_stash_create` 成功后调用 `git update-ref refs/agent/checkpoints/{session_id}/{checkpoint_id} <commit>`，保证可达。
- 中期：session 清理时调用 `git update-ref -d refs/agent/checkpoints/{session_id}/*` 清理 ref。
- 与 T3 修复合并实施。

**优先级**：P1

---

### 差距 #T7：清理机制不对称（有 FIFO 淘汰但无 git ref 清理）

**严重度**：P2（长期运行 git 对象泄漏）

**Cline 实现**：
- `checkpoint-hooks.ts` L102-121（`deleteCheckpointRefs`）：session 删除时遍历 `refs/cline/checkpoints/{sessionId}/` 下所有 ref 并删除（`for-each-ref` + `update-ref -d`）。
- `checkpoint-restore.ts` L53-62（`createRestoredCheckpointMetadata`）：restore 时按 `runCount <= target` 过滤 history，丢弃后续 entry（但未删除对应 git ref）。
- 无基于数量的自动淘汰：history 在 session 生命周期内无限增长。
- `persistence-service.ts` L574/L588：session 删除时统一清理 ref。

**我的实现**：
- `checkpoint.py` L249-268（`_evict_if_needed`）：FIFO 淘汰，单 session 超过 `_MAX_CHECKPOINTS_PER_SESSION = 20` 时删除最旧的 checkpoint（含 JSON 文件）。
- `checkpoint.py` L231-247（`clear_checkpoints`）：手动清除 session 所有 checkpoint。
- `file_checkpoint.py` L266-274（`clear_session`）：手动清除 session 的 file checkpoint 元信息。
- 均不清理 git stash 对象：淘汰/清除后 stash commit 仍为悬空对象，依赖 git gc 回收。

**影响**：
1. **我有 FIFO 淘汰（Cline 无）**：避免 checkpoint 数量无限增长，是合理增强。但 Cline 的 history 无上限，依赖 session 删除时清理。
2. **git 对象泄漏**：淘汰 checkpoint 后 git stash 对象未被清理（悬空），长期运行可能积累大量悬空对象。Cline 的 session 删除清理更彻底。
3. **file_checkpoint 无淘汰**：`FileCheckpointManager` 无自动淘汰机制，session 内 checkpoint 数量无限增长。

**修复建议**：
- 短期：为 `FileCheckpointManager` 增加 FIFO 淘汰机制（参考 checkpoint.py 的 `_evict_if_needed`）。
- 中期：checkpoint 淘汰/清除时同步清理 git ref（若已实施 T3 的 update-ref，则此处 `update-ref -d`）。
- 保留 FIFO 淘汰作为额外增强。

**优先级**：P2

---

### 差距 #T8：启用开关不一致（双开关 vs 单配置）

**严重度**：P2（配置不一致，用户困惑）

**Cline 实现**：
- `config.ts` L198-204（`CoreCheckpointConfig`）：
  - `enabled?: boolean`（默认 false，opt-in）。
  - `createCheckpoint?`（可选自定义实现）。
- `local-runtime-bootstrap.ts` L419-429：`checkpoint.enabled === true` 时注册 `createCheckpointHooks`，否则跳过。
- 单一配置入口，统一控制 checkpoint 行为。

**我的实现**：
- `server.py` L417-421：`CheckpointHook`（消息快照）始终注册，无开关。
- `server.py` L427-446：`FileCheckpointHook`（文件快照）通过 `AGENT_ENABLE_FILE_CHECKPOINT` 环境变量控制（默认关闭）。
- 两个独立开关：消息 checkpoint 强制开启，文件 checkpoint 可选。

**影响**：
1. **消息 checkpoint 无开关**：无法关闭，即使不需要回滚功能也会产生存储开销。Cline 默认关闭 checkpoint。
2. **配置分散**：消息和文件 checkpoint 独立控制，用户需理解两套机制。Cline 单一配置统一管理。
3. **无自定义实现入口**：Cline 支持 `createCheckpoint` 自定义实现（如用快照服务替代 git stash），我无此扩展点。

**修复建议**：
- 短期：为 CheckpointHook 增加环境变量开关（如 `AGENT_ENABLE_MESSAGE_CHECKPOINT`，默认开启保持兼容）。
- 中期：统一为单一配置（如 `AGENT_CHECKPOINT_MODE=message|file|both|off`），简化用户选择。
- 长期：支持自定义 checkpoint 实现（参考 Cline 的 createCheckpoint 回调）。

**优先级**：P2

---

### 差距 #T2（额外增强）：检查点内容含消息快照

**严重度**：信息性（合理增强，但与 Cline 模型不同）

**Cline 实现**：
- `checkpoint-hooks.ts` L247-252：CheckpointEntry 仅含 `ref`（git commit）、`createdAt`、`runCount`、`kind`。
- 消息不在 checkpoint 中：restore 时通过 `trimMessagesToCheckpoint(messages, runCount)` 从当前消息列表截断（L106-112）。
- 即：checkpoint 仅存文件状态，消息靠"截断当前列表"实现。

**我的实现**：
- `checkpoint.py` L56：Checkpoint.messages 存完整的消息列表深拷贝（序列化为 dict）。
- `file_checkpoint.py` L100-108：CheckpointRef 仅存 stash_commit + file_paths（与 Cline 一致）。
- 即：双轨制——消息快照（checkpoint.py）+ 文件快照（file_checkpoint.py）。

**影响**：
1. **存储开销**：我的消息 checkpoint 存完整消息列表（含所有工具输入/输出），单 checkpoint 可能达 MB 级。Cline 仅存 commit hash（40 字节）。
2. **回滚方式不同**：我从快照恢复消息（`_dict_to_message` 重建）；Cline 截断当前消息列表（保留 runCount 之前的部分）。两者效果等价，但我的更直接（不依赖当前消息列表完整性）。
3. **消息+文件分离**：我的两套 checkpoint 独立，需分别回滚；Cline 统一在 restore 时处理。

**修复建议**：
- 保留消息快照作为额外增强（不依赖当前消息列表，更健壮）。
- 但需评估存储开销，可考虑仅存消息索引（runCount）而非完整深拷贝（参考 Cline 的 trim 模式）。

**优先级**：信息性（不强制修复）

---

### 差距 #T10（额外增强）：未跟踪文件处理

**严重度**：信息性（合理增强，优于 Cline）

**Cline 实现**：
- `checkpoint-hooks.ts` L217：`git stash create <message>`，无 `--include-untracked` 参数。
- 效果：未跟踪文件（新建文件）不在 stash 中，回滚时无法恢复。
- `checkpoint-restore.ts` L179：restore 时 `git clean -fd` 删除未跟踪文件和目录。
- 即：**未跟踪文件不被快照，但被清理**——agent 新建的文件会被删除但无法恢复到创建前状态（实际上删除即恢复，因为创建前不存在）。

**我的实现**：
- `file_checkpoint.py` L358-367：`git add -A` 在 stash create 前暂存所有变更（含未跟踪文件）。
- L387-395：`git reset -q` 恢复 index，不影响工作区文件。
- 效果：未跟踪文件被纳入 stash commit，restore 时可通过 `git checkout <commit> -- <path>` 恢复。
- 即：**未跟踪文件被快照**，可恢复到创建时的内容。

**影响**：
- 我的实现可回滚"文件创建"操作（如 agent 新建了 config.yaml，回滚后文件恢复到创建前——即不存在或为旧内容）。
- Cline 的 `clean -fd` 会删除 agent 新建的未跟踪文件（回滚到"不存在"），但无法恢复到"创建前的旧内容"（因为 stash 中没有）。
- 我的 `git add -A` + `reset -q` 三步法有竞态风险（参见 T3），但功能上更完整。

**修复建议**：
- 保留 `git add -A` 作为合理增强。
- 可考虑用 `git stash create --include-untracked` 替代三步法（避免竞态），但需验证 Cline 兼容性。

**优先级**：信息性（不强制修复，保留增强）

---

## 4. 一致性统计

| 一致性等级 | 子项 | 数量 | 占比 |
|-----------|------|------|------|
| 完全一致 | T4, T9 | 2 | 20% |
| 弱对齐 | T1, T3, T5, T6, T7, T8 | 6 | 60% |
| 缺失 | — | 0 | 0% |
| 额外增强 | T2, T10 | 2 | 20% |

**按严重度分布**：

| 严重度 | 子项 | 数量 |
|-------|------|------|
| P1 | T3, T5, T6 | 3 |
| P2 | T1, T7, T8 | 3 |
| 信息性 | T2, T10 | 2 |
| 完全一致 | T4, T9 | 2 |

---

## 5. 修复建议

### 短期（1-2 周内）

1. **T3 + T6：git ref 持久化**（P1）
   - 在 `file_checkpoint.py` 的 `_git_stash_create` 成功后增加 `git update-ref refs/agent/checkpoints/{session_id}/{checkpoint_id} <commit>`。
   - 保证 stash commit GC-safe，避免长期运行后回滚失败。
   - 文件：`agent/file_checkpoint.py` L339-429。

2. **T5：回滚联动**（P1）
   - 在 `server.py` 的 `/rollback` 端点中，若 `AGENT_ENABLE_FILE_CHECKPOINT` 启用，自动调用文件回滚到对应 checkpoint。
   - 实现"消息 + 文件"组合恢复，避免用户需分别调用两个端点。
   - 文件：`agent/server.py` L1193-1266。

3. **T1：root-agent 判断**（P2）
   - 为 `CheckpointHook` 增加 root-agent 判断（参考 Cline `parentAgentId != null` 跳过逻辑），避免子 agent 场景冲突。
   - 文件：`agent/checkpoint.py` L363-393。

### 中期（1-2 月内）

4. **T5：全量文件恢复**（P1）
   - `file_checkpoint.py` 的 `restore_checkpoint` 增加 `git reset --hard` + `git clean -fd` 全量恢复模式（可配置）。
   - 保留 file_paths 部分恢复作为优化路径。
   - 文件：`agent/file_checkpoint.py` L228-254, L431-485。

5. **T7：git ref 清理 + file_checkpoint 淘汰**（P2）
   - session 清理时调用 `git update-ref -d refs/agent/checkpoints/{session_id}/*` 清理 ref。
   - 为 `FileCheckpointManager` 增加 FIFO 淘汰机制。
   - 文件：`agent/file_checkpoint.py` L266-274, `agent/checkpoint.py` L231-247。

6. **T8：统一启用开关**（P2）
   - 为 `CheckpointHook` 增加 `AGENT_ENABLE_MESSAGE_CHECKPOINT` 环境变量（默认开启保持兼容）。
   - 或统一为 `AGENT_CHECKPOINT_MODE=message|file|both|off`。
   - 文件：`agent/server.py` L415-446。

### 长期（3+ 月）

7. **T5：fork session 模式**（P2）
   - 回滚时创建 forked session（新 sessionId），保留原 session，支持"撤销回滚"。
   - 参考 Cline 的 `session-versioning-service.ts` + `retainCheckpointRefs`。
   - 需评估与现有 session 管理的兼容性。

8. **T3：用 `git stash create --include-untracked` 替代三步法**（P2）
   - 避免并发竞态，原子性更好。
   - 但需验证与现有 `git add -A` 行为的等价性。

9. **T8：自定义 checkpoint 实现入口**（P2）
   - 参考 Cline 的 `createCheckpoint` 回调，支持注入自定义快照逻辑（如用快照服务替代 git stash）。

---

## 6. 验证记录

### 已读取的对标文件

| 文件 | 路径 | 用途 |
|------|------|------|
| Cline checkpointRestore controller | `third_party/cline/apps/vscode/src/core/controller/checkpoints/checkpointRestore.ts` | vscode 端 RPC 入口 |
| Cline checkpoint-hooks | `third_party/cline/sdk/packages/core/src/hooks/checkpoint-hooks.ts` | 核心实现：createCheckpointHooks + deleteCheckpointRefs + retainCheckpointRefs |
| Cline checkpoint-restore | `third_party/cline/sdk/packages/core/src/session/checkpoint-restore.ts` | 回滚逻辑：applyCheckpointToWorktree + trimMessagesToCheckpoint |
| Cline checkpoint-diff | `third_party/cline/sdk/packages/core/src/session/checkpoint-diff.ts` | diff 比较：buildCheckpointWorkspaceDiff |
| Cline session-snapshot | `third_party/cline/sdk/packages/core/src/session/session-snapshot.ts` | 快照序列化：CoreSessionCheckpointSnapshot |
| Cline config | `third_party/cline/sdk/packages/core/src/types/config.ts` | 配置：CoreCheckpointConfig |
| Cline local-runtime-bootstrap | `third_party/cline/sdk/packages/core/src/services/local-runtime-bootstrap.ts` L419-429 | hook 集成点 |
| Cline persistence-service | `third_party/cline/sdk/packages/core/src/session/services/persistence-service.ts` L574-588 | session 删除时清理 ref |
| Cline session-versioning-service | `third_party/cline/sdk/packages/core/src/session/session-versioning-service.ts` L219-223 | fork session 时迁移 ref |
| Cline checkpoint-hooks.test | `third_party/cline/sdk/packages/core/src/hooks/checkpoint-hooks.test.ts` | 测试用例验证（per-run 时机、clean 回退 HEAD、subagent 跳过） |

### 已读取的当前实现文件

| 文件 | 路径 | 用途 |
|------|------|------|
| 消息检查点 | `agent/checkpoint.py` | CheckpointManager + CheckpointHook（消息列表快照） |
| 文件检查点 | `agent/file_checkpoint.py` | FileCheckpointManager（shadow-git 文件快照） |
| API 端点 | `agent/server.py` L1155-1383 | /checkpoints, /rollback, /file_checkpoints, /rollback_file |
| hook 注册 | `agent/server.py` L415-446 | CheckpointHook 始终注册 + FileCheckpointHook 环境变量控制 |
| 数据样本 | `agent_data/checkpoints/cp_37a50ec1e593.json` | 实际 checkpoint 数据（含 messages 列表） |

### 关键验证点

1. **T1 时机验证**：Cline 测试 `checkpoint-hooks.test.ts` L64-98 证实 per-run 创建（runCount 1→2，history 长度 1→2）；我的 `checkpoint.py` L372-373 证实 per-tool 创建（before_tool hook + requires_approval 判断）。
2. **T3 stash 验证**：Cline `checkpoint-hooks.ts` L217 证实无 `git add -A`，仅 `git stash create`；我的 `file_checkpoint.py` L358-367 证实三步法（add -A → stash create → reset）。
3. **T5 回滚验证**：Cline `checkpoint-restore.ts` L178-188 证实 `reset --hard` + `clean -fd` + `stash apply`；我的 `file_checkpoint.py` L454-459 证实 `git checkout <commit> -- <paths>`（部分文件）。
4. **T9 shadow-git 验证**：Cline `checkpoint-hooks.ts` L166-175 证实使用用户 cwd（`git rev-parse --is-inside-work-tree`）；我的 `file_checkpoint.py` L487-501 同样使用 workspace_root。
5. **T10 未跟踪验证**：Cline `checkpoint-hooks.ts` L217 证实无 `--include-untracked`；`checkpoint-restore.ts` L179 证实 `clean -fd`；我的 `file_checkpoint.py` L358-367 证实 `git add -A` 包含未跟踪。
