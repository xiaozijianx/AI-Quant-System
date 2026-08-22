# Stage 9: P1 紧急补全方案

> 生成时间：2026-07-26
> 优先级：P1
> 预估工作量：1 周
> 依赖：无（基于 Stage 1-8 已完成的基础设施）
>
> 来源：
> - `CLINE_DIFF/SUMMARY_v2.md` §3.1 P1 级剩余差距 6 项
> - `CLINE_DIFF/phase_Q_mcp.md`（Q8）
> - `CLINE_DIFF/phase_N_abort.md`（N12）
> - `CLINE_DIFF/phase_S_persistence.md`（S6 / S12）
> - `CLINE_DIFF/phase_T_checkpoint.md`（T3 / T5 / T6）
> - `CLINE_DIFF/phase_U_approval.md`（U10）
>
> 涉及源文件：
> - 我的：`agent/mcp_manager.py`、`agent/tools/exec_tool.py`、`agent/tools/run_commands.py`、`agent/persistence/session_store.py`、`agent/persistence/checkpoint.py`、`agent/approval.py`、`agent/server.py`、`agent/runtime.py`、`agent_config/`
> - Cline：`third_party/cline/sdk/packages/core/src/extensions/mcp/`、`third_party/cline/sdk/packages/core/src/runtime/abort/`、`third_party/cline/sdk/packages/core/src/services/storage/sqlite-session-store.ts`、`third_party/cline/apps/vscode/src/core/controller/checkpoints/`、`third_party/cline/sdk/packages/core/src/runtime/tools/tool-approval.ts`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 9.1 | MCP per-tool policies `auto_approve` 对接 approval 流程 | Q8 | P1 | agent/mcp_manager.py、agent/approval.py、agent/server.py |
| 9.2 | 子进程 kill on abort（run_commands 订阅 abort_signal） | N12 | P1 | agent/tools/run_commands.py、agent/tools/exec_tool.py、agent/runtime.py |
| 9.3 | 会话版本迁移机制 | S6 / S12 | P1 | agent/persistence/session_store.py、agent/persistence/migrations/ |
| 9.4 | Checkpoint git ref 持久化（ refs/cline/checkpoints/...） | T3 / T6 | P1 | agent/persistence/checkpoint.py |
| 9.5 | Checkpoint 回滚联动（消息+文件分离式恢复） | T5 | P1 | agent/persistence/checkpoint.py、agent/server.py |
| 9.6 | 审批记忆跨会话持久化 | U10 | P1 | agent/approval.py、agent/persistence/ |

依赖关系：
- 9.1 / 9.2 / 9.3 / 9.6 互相独立，可并行
- 9.4 是 9.5 的前置条件（回滚需要先有 git ref）
- 建议执行顺序：9.1 → 9.2 → 9.6 → 9.3 → 9.4 → 9.5

---

## 9.1 MCP per-tool policies `auto_approve` 对接 approval 流程（Q8）

### 任务背景

来源 Phase Q #Q8。Stage 3.8 中我已为 MCP 引入 `tool_policies` 配置段，支持 `enabled: false` 关闭单个工具，但 `auto_approve: true` 字段当前仅作为元数据存储，**未对接 approval 流程**：当 MCP 工具被调用时，无论 `auto_approve` 是 true 还是 false，都走默认的审批逻辑（依赖 `requires_approval` 属性）。

Cline 的 `tool-approval.ts` 中 `auto_approve: true` 表示该工具被标记为"始终允许"，调用时**跳过用户审批**直接执行；`auto_approve: false` 或未设置时走默认审批逻辑。这是 per-tool 粒度的审批策略，与全局 `requires_approval` 互补。

当前我的实现导致：用户在 `mcp_servers.yaml` 配置了 `auto_approve: true` 的工具，仍会被审批流程拦截，需要用户每次确认，违背了 `auto_approve` 的设计意图。

### 目标

让 MCP `tool_policies.<tool>.auto_approve: true` 真正生效：
1. 工具调用前查询该 tool 的 `auto_approve` 策略
2. `auto_approve: true` 时跳过 approval 流程直接执行
3. `auto_approve: false` 或未设置时走默认审批逻辑（保留现有行为）

### 当前实现位置

- `agent/mcp_manager.py`（`McpManager.get_tool_policies` / `McpManager._tool_policy_for`）
- `agent/approval.py`（`ApprovalDecider.should_approve` / `ApprovalDecision`）
- `agent/runtime.py`（`_prepare_tool_execution` 中审批分支）
- `agent_config/mcp_servers.yaml`（`tool_policies` 段）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/tools/tool-approval.ts`（`shouldAutoApprove` / `ToolPolicies`）
- Cline `third_party/cline/sdk/packages/core/src/extensions/mcp/mcp-policy-loader.ts`

### 修复步骤建议

1. **扩展 `ApprovalDecider` 接口**
   - 在 `agent/approval.py` 的 `ApprovalDecider.should_approve` 方法签名中增加 `tool_policies: dict[str, Any] | None = None` 参数（保留原参数，向后兼容）
   - 在方法开头检查 `tool_policies.get("auto_approve")`：
     - `True` → 返回 `ApprovalDecision(approved=True, reason="auto_approve_policy", persistent=False)`
     - `False` 或未设置 → 走原审批逻辑
   - 不写 fallback：若 `tool_policies` 字段缺失或类型错误，让异常自然抛出（与用户规则一致）

2. **`McpManager` 暴露 per-tool policy 查询接口**
   - 在 `agent/mcp_manager.py` 增加 `McpManager.get_tool_policy(server_name: str, tool_name: str) -> dict` 方法
   - 从已加载的 `tool_policies` 配置中查询指定工具的策略，未配置时返回空 dict
   - 保留原有 `get_tool_policies`（返回全部策略）方法不变

3. **`AgentRuntime._prepare_tool_execution` 注入 tool_policies**
   - 在审批分支调用 `should_approve` 前，先判断工具来源：
     - MCP 工具（`tool.source == "mcp"`）：调用 `mcp_manager.get_tool_policy(server, tool)` 获取策略
     - 内置工具：传 `None`（走原逻辑）
   - 将策略传入 `should_approve(..., tool_policies=policy)`
   - 保留原有 `requires_approval` 短路逻辑：`requires_approval=False` 时仍跳过审批

4. **审批记忆优先级**
   - 已有的"会话级始终允许"记忆（Stage 5.6）优先级高于 `auto_approve`
   - 即：用户显式选择"始终允许"后，无论 `auto_approve` 配置如何都直接放行
   - `auto_approve` 仅在无会话级记忆时生效

### 验证方法

1. 在 `agent_config/mcp_servers.yaml` 为某 MCP 工具配置 `tool_policies: { <tool>: { auto_approve: true } }`
2. 调用该工具，确认无审批弹窗，直接执行
3. 配置 `auto_approve: false`，调用该工具，确认走原审批流程
4. 移除 `tool_policies` 配置，确认走原审批流程（向后兼容）
5. 用户选择"始终允许"后，将 `auto_approve` 改为 `false`，确认仍跳过审批（用户记忆优先）

### 注意事项

- `auto_approve` 仅对 MCP 工具生效，内置工具不读取该配置
- `auto_approve: true` 不写入审批记忆持久化文件，仅作为运行时策略
- 配置变更需重启会话生效（与现有 MCP 配置加载逻辑一致）

---

## 9.2 子进程 kill on abort（N12）

### 任务背景

来源 Phase N #N12。当用户中止 agent 运行时，`AgentRuntime.abort()` 会设置 `_aborted=True` 并触发 abort signal，但当前 `run_commands` 工具启动的子进程**未订阅 abort signal**，导致：
- 用户点"停止"后，agent 主循环已退出，但子进程（如 `python preprocess.py`）仍在后台运行
- 子进程继续占用 CPU / 内存 / 文件句柄，可能导致下一个 run 启动时资源冲突
- 量化场景下常见长耗时数据采集脚本，中止后子进程继续运行会污染数据

Cline 的 `exec_tool.ts` 中 `_wait_process_with_abort` 在 abort signal 触发时立即 `proc.kill()`，确保子进程随主循环一同退出。

### 目标

让 `run_commands` / `exec_tool` 启动的子进程在 abort signal 触发时立即被 kill：
1. 子进程启动后注册 abort callback
2. abort 触发时调用 `proc.kill()`（Windows 用 `proc.terminate()`，Linux/Mac 用 `proc.kill(SIGTERM)`）
3. 子进程退出后释放资源，主循环可立即返回

### 当前实现位置

- `agent/tools/run_commands.py`（`_run_subprocess` 函数，使用 `subprocess.Popen`）
- `agent/tools/exec_tool.py`（`exec_tool` 函数，调用 `_run_subprocess`）
- `agent/runtime.py`（`abort()` 方法、`_aborted` 标志、abort_signal 实现）
- `agent/types.py`（`AgentToolContext.signal` 字段）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/executors/exec-tool.ts`（`_waitProcessWithAbort`）
- Cline `third_party/cline/sdk/packages/core/src/runtime/abort/abort-controller.ts`

### 修复步骤建议

1. **扩展 `AgentToolContext` 传递 abort_signal**
   - 当前 `AgentToolContext.signal` 已存在（`asyncio.Event` 类型），但 `run_commands` 未订阅
   - 确认 `_prepare_tool_execution` 中构造 `AgentToolContext` 时正确传入 abort signal
   - 保留原有 `signal` 字段语义，不修改其他工具的使用方式

2. **`_run_subprocess` 增加 abort 监听**
   - 在 `agent/tools/run_commands.py` 的 `_run_subprocess` 函数中：
     - 子进程启动后，启动一个异步 task 监听 `context.signal`
     - 监听 task 内 `await context.signal.wait()`，触发后调用 `proc.kill()`（Windows）或 `proc.terminate()`（POSIX）
     - 主流程 `await asyncio.create_subprocess_exec(...)` 完成后取消监听 task
   - 使用 `asyncio.wait([proc.wait(), signal.wait()], return_when=FIRST_COMPLETED)` 模式实现二选一等待
   - 保留原有 `proc.wait()` 调用逻辑，仅在 abort 时强制 kill

3. **跨平台 kill 语义**
   - Windows: `proc.kill()` 等价 `TerminateProcess`，立即结束
   - POSIX: `proc.kill()` 发送 SIGKILL，立即结束
   - 不区分 SIGTERM/SIGKILL（Cline 也直接 kill），简化实现
   - kill 后等待 `proc.wait()` 返回，确保僵尸进程回收

4. **超时与 abort 的优先级**
   - 现有 `timeout` 参数触发时，调用 `proc.kill()` 后抛 `TimeoutExpired`
   - abort 触发时，调用 `proc.kill()` 后抛 `RuntimeError("aborted")`（或返回部分输出）
   - 两者同时触发时，谁先到谁生效，不互相阻塞

5. **输出捕获**
   - abort 触发后，已捕获的 stdout/stderr 仍需返回（供前端显示部分输出）
   - 在 `_run_subprocess` 返回值中增加 `aborted: bool` 字段，标记是否被 abort 中断
   - 工具结果以 `is_error=True` + `error="aborted by user"` 返回，让 LLM 知道执行被中止

### 验证方法

1. 启动 agent，调用 `run_commands` 执行 `python -c "import time; time.sleep(60)"`
2. 在 agent 运行期间点击"停止"按钮
3. 确认：
   - agent 主循环立即退出（status="aborted"）
   - 任务管理器中 `python.exe` 进程已结束
   - SSE 流中包含已捕获的部分输出
4. 不点停止，等待命令自然结束，确认正常流程不受影响（回归测试）

### 注意事项

- `asyncio.create_subprocess_exec` 在 Windows 上有 ProactorEventLoop 限制，确认当前 event loop policy 兼容
- `proc.kill()` 后 `proc.wait()` 必须调用，否则留下僵尸进程
- 不修改 `exec_tool` 工具的对外接口（`tool.execute` 签名不变）

---

## 9.3 会话版本迁移机制（S6 / S12）

### 任务背景

来源 Phase S #S6 / S12。当前会话持久化使用 JSON 文件存储（`agent_config/sessions/<session_id>.json`），文件顶部有 `version` 字段标识格式版本。当 agent 升级引入新字段或字段语义变更时，旧版本会话文件加载会失败或行为异常。

当前实现**无版本迁移机制**：升级后旧会话文件直接被新代码读取，字段缺失时用默认值，字段类型变更时直接抛错。量化场景下用户可能跨版本恢复历史会话（如查 1 个月前的研报生成记录），无迁移会导致历史会话不可读。

Cline 的 `sqlite-session-store.ts` 中实现了 `MIGRATIONS` 注册表 + `runMigrations` 函数，按版本号顺序执行迁移函数。

### 目标

实现会话文件的版本迁移机制：
1. 加载会话时检查 `version` 字段
2. 当前版本 > 文件版本时，按顺序执行迁移函数链
3. 迁移完成后更新 `version` 字段并写回文件
4. 迁移失败时抛错并保留原文件（不破坏数据）

### 当前实现位置

- `agent/persistence/session_store.py`（`SessionStore.load` / `SessionStore.save` / `SESSION_VERSION` 常量）
- `agent/persistence/__init__.py`
- `agent_config/sessions/`（会话文件目录）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/storage/sqlite-session-store.ts`（`MIGRATIONS` 数组、`runMigrations` 函数）
- Cline `third_party/cline/sdk/packages/core/src/services/storage/migrations/`（独立迁移脚本目录）

### 修复步骤建议

1. **定义迁移注册表**
   - 在 `agent/persistence/` 下新建 `migrations/` 目录
   - 新建 `agent/persistence/migrations/__init__.py` 暴露 `MIGRATIONS` 列表
   - 每个迁移是一个 `(from_version: int, to_version: int, migrate_fn: Callable[[dict], dict])` 元组
   - `migrate_fn` 接收原数据 dict，返回迁移后 dict，抛错时不捕获

2. **迁移函数示例（v1 → v2）**
   - 新建 `agent/persistence/migrations/v1_to_v2.py`：
     ```python
     def migrate(data: dict) -> dict:
         """v1 → v2: 为 messages 中的 ToolCallPart 补 input_value 字段"""
         for msg in data.get("messages", []):
             for part in msg.get("content", []):
                 if part.get("type") == "tool_call" and "input_value" not in part:
                     part["input_value"] = part.get("input_text", "")
         return data
     ```
   - 在 `MIGRATIONS` 列表中注册 `(1, 2, migrate)`

3. **`SessionStore.load` 接入迁移**
   - 加载文件后检查 `version` 字段
   - 若 `version < SESSION_VERSION`：从 `MIGRATIONS` 中筛选 `from_version >= version` 的迁移，按 `from_version` 升序执行
   - 每次迁移后更新内存中的 `version` 字段
   - 全部迁移成功后写回文件（持久化新版本号）
   - 迁移失败时抛 `SessionMigrationError`，不写回文件（保护原数据）

4. **`SessionStore.save` 写入当前版本号**
   - 保存时强制设置 `version = SESSION_VERSION`
   - 防止手动编辑文件后版本号丢失

5. **备份机制（可选）**
   - 迁移前将原文件复制为 `<session_id>.json.v<old_version>.bak`
   - 备份保留最近 3 次迁移，超过自动清理
   - 该机制简单实现，不写 fallback：备份失败时迁移仍继续（备份非关键路径）

### 验证方法

1. 手动构造 v1 版本的会话文件（缺 `input_value` 字段）
2. 调用 `SessionStore.load(session_id)`，确认：
   - 迁移函数被调用
   - 返回的 dict 中 `version=2`，`messages` 内 `ToolCallPart` 有 `input_value` 字段
   - 文件已写回，`version=2`
3. 构造畸形数据（如 `messages` 不是 list），确认抛 `SessionMigrationError` 且原文件未变
4. 升级 `SESSION_VERSION` 到 3 但不注册 v2→v3 迁移，确认加载时报错（缺迁移函数）

### 注意事项

- 迁移函数必须幂等（多次执行结果一致），防止意外重复执行
- `SESSION_VERSION` 当前值需要先确定（看现有文件版本号），假设为 1
- 迁移函数禁止调用外部 IO（如读其他文件），保持纯函数语义
- 备份机制仅对迁移触发，正常 save 不备份

---

## 9.4 Checkpoint git ref 持久化（T3 / T6）

### 任务背景

来源 Phase T #T3 / T6。当前 Checkpoint 机制在每次 run 开始时创建 shadow git commit（在 `.cline_checkpoints/<session_id>/` 仓库内），commit SHA 存储在会话 JSON 的 `checkpoints` 列表中。问题：
- shadow git commit 是**悬空 commit**（无 ref 引用），长期运行后会被 `git gc` 自动回收
- 默认 `git gc` 阈值为 2 周后回收 unreachable commit，导致 2 周前的 checkpoint 无法回滚
- 量化场景下用户可能需要回滚到 1 个月前的状态（如复盘某次策略上线前的代码）

Cline 的 `shadow-git.ts` 中使用 `git update-ref refs/cline/checkpoints/{sessionId}/{runCount} <sha>` 为每个 checkpoint 创建 ref，确保不被 GC 回收。

### 目标

为每个 checkpoint 创建 git ref，使其不被 `git gc` 回收：
1. shadow git commit 创建后，立即 `git update-ref` 创建对应 ref
2. ref 命名规范：`refs/cline/checkpoints/{session_id}/{run_count}`
3. checkpoint 删除时同步删除 ref（`git update-ref -d`）
4. 会话 JSON 中仍存储 SHA（向后兼容），但 ref 是真权威

### 当前实现位置

- `agent/persistence/checkpoint.py`（`CheckpointManager.create_checkpoint` / `restore_checkpoint` / `delete_checkpoint`）
- `agent/persistence/session_store.py`（`checkpoints` 字段存储）
- shadow git 仓库位置：`.cline_checkpoints/<session_id>/`

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/controller/checkpoints/shadow-git.ts`（`saveCheckpoint` 创建 ref）
- Cline `shadow-git.ts`（`deleteCheckpoint` 删除 ref）

### 修复步骤建议

1. **`CheckpointManager.create_checkpoint` 增加 ref 创建**
   - 在原有 `git commit-tree` / `git commit` 调用后，立即执行：
     ```python
     ref_name = f"refs/cline/checkpoints/{session_id}/{run_count}"
     subprocess.run(["git", "update-ref", ref_name, sha], cwd=shadow_repo, check=True)
     ```
   - 保留原 SHA 写入会话 JSON 的逻辑（向后兼容）
   - ref 创建失败时抛错（不写 fallback），让上层感知

2. **`CheckpointManager.delete_checkpoint` 同步删除 ref**
   - 删除会话 JSON 中的 checkpoint 记录前，先 `git update-ref -d <ref_name>`
   - ref 不存在时 git 返回非零，用 `check=False` 容忍（已 GC 或手动删除的情况）
   - 保留原删除会话记录的逻辑

3. **`CheckpointManager.list_checkpoints` 优先从 ref 查询**
   - 增加 `list_refs()` 方法：`git for-each-ref refs/cline/checkpoints/{session_id}/ --format "%(refname:short) %(objectname)"`
   - 与会话 JSON 中的记录做交叉验证：
     - JSON 有 ref 无：SHA 已失效，从 JSON 删除
     - ref 有 JSON 无：孤儿 ref，删除 ref
   - 该交叉验证作为 `list_checkpoints` 的可选行为，默认开启

4. **session_id 中的特殊字符处理**
   - session_id 含 `/` 时 ref 名非法，需做转义（如 `/` → `_`）
   - 增加 `_escape_session_id(session_id) -> str` 辅助函数
   - 转义规则简单：非 `[a-zA-Z0-9_-]` 字符替换为 `_`

5. **shadow git 仓库初始化时配置 `gc.reflogExpire`**
   - 在 shadow git 仓库初始化时执行：
     ```python
     subprocess.run(["git", "config", "gc.reflogExpire", "never"], cwd=shadow_repo, check=True)
     subprocess.run(["git", "config", "gc.reflogExpireUnreachable", "never"], cwd=shadow_repo, check=True)
     ```
   - 防止 reflog 过期导致 ref 被清理

### 验证方法

1. 创建一个 checkpoint，确认 `git for-each-ref refs/cline/checkpoints/<session_id>/` 列出对应 ref
2. 手动 `git gc --prune=now --aggressive`，确认 ref 仍存在（不被回收）
3. 删除 checkpoint，确认 ref 同步删除
4. 用含 `/` 的 session_id 测试，确认转义正确
5. 模拟 JSON 与 ref 不一致场景，调用 `list_checkpoints`，确认交叉验证逻辑生效

### 注意事项

- ref 创建必须与 commit 在同一事务内（commit 成功后立即 update-ref，失败时需 rollback commit）
- Windows 上 git 命令路径需正确（依赖系统 git，非 libgit2）
- 不修改 shadow git 仓库的目录结构（仅增加 ref）

---

## 9.5 Checkpoint 回滚联动（T5）

### 任务背景

来源 Phase T #T5。当前 Checkpoint 回滚仅恢复**消息快照**（将 `messages` 字段覆盖到当前会话），未恢复**工作区文件**。导致：
- 用户回滚到 checkpoint-3 后，消息历史是 checkpoint-3 时的状态，但工作区文件仍是当前状态
- 消息与文件不一致，LLM 看到的上下文与实际代码不匹配，可能产生错误决策
- 量化场景下，策略代码已变更但消息显示旧版本讨论，LLM 可能基于过时上下文生成新代码

Cline 的 `checkpoint-restore.ts` 实现完整的回滚：消息 + 工作区文件 + 未跟踪文件，确保两者一致。

### 目标

实现 Checkpoint 回滚的完整联动：
1. 用户触发 `/rollback <checkpoint_id>` 时：
   - 恢复消息快照（保留现有逻辑）
   - 恢复工作区文件到 checkpoint 时的状态
   - 恢复未跟踪文件（如新建的文件，被删除）
2. 回滚后通知前端刷新文件树
3. 回滚失败时全部回退（消息和文件都不变）

### 当前实现位置

- `agent/persistence/checkpoint.py`（`CheckpointManager.restore_checkpoint`，仅恢复 messages）
- `agent/server.py`（无 `/rollback` 端点，需新增）
- `static/js/ai-chat.js`（无回滚 UI，需新增）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/controller/checkpoints/checkpoint-restore.ts`（`restoreCheckpoint` 完整实现）
- Cline `checkpoint-restore.ts`（`restoreFiles` / `restoreUntracked`）

### 修复步骤建议

1. **`CheckpointManager.restore_checkpoint` 扩展**
   - 在原有消息恢复逻辑后，增加文件恢复逻辑：
     ```python
     # 1. 恢复跟踪文件（git checkout）
     subprocess.run(["git", "checkout", "-f", sha, "--", "."], cwd=workspace, check=True)
     # 2. 恢复未跟踪文件（从 shadow git 的 "untracked" commit 检出）
     subprocess.run(["git", "checkout", untracked_sha, "--", "."], cwd=workspace, check=True)
     # 3. 删除 checkpoint 之后新建的未跟踪文件（diff 当前 untracked 与目标 untracked）
     # ... 见步骤 2
     ```
   - 保留原消息恢复逻辑在前，文件恢复在后（消息恢复失败时不触动文件）
   - 文件恢复失败时回滚消息（抛错前还原原消息状态）

2. **未跟踪文件管理**
   - `create_checkpoint` 时已有未跟踪文件快照（保存到 shadow git 的 `untracked` commit）
   - 回滚时需要：
     - 删除当前工作区中"目标 checkpoint 之后"新建的未跟踪文件
     - 检出目标 checkpoint 的未跟踪文件
   - 实现：对比当前 untracked list 与目标 untracked list，删除差集（当前有但目标没有的）

3. **新增 `/rollback` API 端点**
   - 在 `agent/server.py` 增加 `POST /api/agent/sessions/<session_id>/rollback` 端点
   - 入参：`{"checkpoint_id": "..."}` 或 `{"run_count": 3}`
   - 返回：`{"status": "ok", "rolled_back_to": "..."}`
   - 失败时返回 500 + 错误信息

4. **前端回滚 UI**
   - 在 chat 历史中每个 checkpoint 标记旁增加"回滚到此点"按钮
   - 点击后弹确认框，确认后调用 `/rollback` 端点
   - 成功后刷新页面（重新加载会话消息 + 文件树）
   - 保留现有 checkpoint 列表 UI，仅增加按钮

5. **工作区脏检查**
   - 回滚前检查工作区是否有未提交修改（非 checkpoint 系统管理的内容）
   - 有脏修改时弹框确认（"工作区有未保存修改，回滚将丢失，确认继续？"）
   - 用户确认后强制回滚（`git checkout -f` 覆盖本地修改）

### 验证方法

1. 创建 checkpoint-1，修改文件 A，创建文件 B，创建 checkpoint-2，修改文件 A，删除文件 B
2. 回滚到 checkpoint-1：
   - 确认文件 A 内容是 checkpoint-1 时的内容
   - 确认文件 B 已恢复（checkpoint-1 时存在）
   - 确认消息历史是 checkpoint-1 时的状态
3. 回滚失败测试：手动删除 shadow git 仓库，调用回滚，确认返回 500 且工作区不变
4. 工作区脏检查：手动修改某文件不 commit，触发回滚，确认弹框提示

### 注意事项

- 回滚是**破坏性操作**，必须用户显式确认
- 回滚后无法再回到回滚前的状态（除非有更新的 checkpoint），UI 需明确提示
- 文件恢复用 `git checkout -f`，会丢失未提交修改，必须先做脏检查
- 依赖 9.4 的 git ref 持久化（否则旧 checkpoint 可能已被 GC）

---

## 9.6 审批记忆跨会话持久化（U10）

### 任务背景

来源 Phase U #U10。Stage 5.6 已实现会话级审批记忆（"始终允许此工具"复选框），但记忆**仅存储在内存中**，会话结束（关闭浏览器或 agent 重启）后丢失。

用户痛点：
- 每次重启 agent 后，第一次调用 `read_files` 等工具仍需重新审批
- 量化场景常用工具固定（`read_files` / `search_codebase` / `exec_tool`），每次重启审批繁琐
- 用户希望"始终允许"的语义是**永久允许**，而非"本次会话允许"

Cline 的 `tool-approval.ts` 中审批记忆持久化到 `globalState`（VSCode 全局状态），跨会话保留。

### 目标

将审批记忆持久化到磁盘，跨会话保留：
1. 用户选择"始终允许此工具"时，写入持久化文件
2. agent 启动时加载该文件，恢复审批记忆
3. 提供"重置审批记忆" API，用户可清除
4. 记忆粒度：(tool_name, parameter_hash) 二元组，参数变化时仍需重新审批

### 当前实现位置

- `agent/approval.py`（`ApprovalDecider._session_memory: dict`，内存存储）
- `agent/runtime.py`（`_prepare_tool_execution` 调用 `should_approve`）
- `agent_config/`（无审批记忆文件，需新增）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/tools/tool-approval.ts`（`ApprovalMemory` 类 + globalState 持久化）
- Cline `tool-approval.ts`（`shouldApprove` 查询持久化记忆）

### 修复步骤建议

1. **定义持久化文件格式**
   - 路径：`agent_config/approval_memory.json`
   - 格式：
     ```json
     {
       "version": 1,
       "entries": [
         {
           "tool_name": "read_files",
           "parameter_hash": "sha256:abc123...",
           "approved_at": "2026-07-26T10:00:00Z",
           "scope": "global"
         }
       ]
     }
     ```
   - `parameter_hash` 用 sha256(param_json) 前 16 位，避免长哈希
   - `scope` 字段预留（当前仅 `global`，未来支持 `session` 级别）

2. **`ApprovalDecider` 扩展**
   - 在 `__init__` 中加载 `approval_memory.json` 到 `self._persistent_memory: list[dict]`
   - 保留原 `self._session_memory`（会话级，运行时临时），两者并存
   - 查询顺序：`session_memory` > `persistent_memory` > 默认审批逻辑
   - `should_approve` 返回 `ApprovalDecision(approved=True, reason="persistent_memory")` 时跳过弹窗

3. **用户选择"始终允许"时写入持久化**
   - 在审批回调中，用户选择"始终允许"时：
     - 计算参数 hash
     - 构造 entry dict
     - 追加到 `self._persistent_memory` 并立即写回文件
   - 文件写入用 `tmpfile + os.replace` 模式保证原子性
   - 保留原会话级记忆写入逻辑（同时写入两者）

4. **新增 `/api/agent/approval_memory` API**
   - `GET /api/agent/approval_memory`：返回当前持久化记忆列表
   - `DELETE /api/agent/approval_memory`：清空所有记忆
   - `DELETE /api/agent/approval_memory/<tool_name>`：清空指定工具的记忆
   - 在 `agent/server.py` 注册路由

5. **前端"重置审批记忆"入口**
   - 在设置页面增加"审批记忆管理"区块
   - 列出所有持久化记忆条目，支持单条删除和全部清空
   - 保留现有审批弹窗 UI，仅增加管理入口

6. **参数 hash 计算**
   - 新建 `agent/approval.py` 中 `_compute_param_hash(params: dict) -> str` 函数
   - 用 `json.dumps(params, sort_keys=True, ensure_ascii=False)` 标准化后 sha256
   - 工具参数变化时 hash 不同，需重新审批（防止"始终允许 read_files 路径 A"后 path B 也被自动放行）

### 验证方法

1. 启动 agent，调用 `read_files`，选择"始终允许"
2. 确认 `agent_config/approval_memory.json` 已创建并包含该条目
3. 重启 agent，再次调用 `read_files`（同参数），确认无审批弹窗
4. 调用 `read_files`（不同参数），确认弹窗（参数变了）
5. 调用 `DELETE /api/agent/approval_memory`，确认文件清空，再次调用工具需审批

### 注意事项

- 记忆文件可能被多进程并发访问（多个 agent 实例），用文件锁保护
- 参数 hash 计算需保证幂等（相同参数哈希相同）
- `exec_tool` 的命令参数（如 `python preprocess.py`）也算参数，不同命令需独立审批
- 不修改现有"会话级"记忆逻辑（仅追加持久化层）

---

## 10. 阶段汇总

### 10.1 完成判据

- 9.1：MCP `auto_approve: true` 工具调用无审批弹窗
- 9.2：用户中止后子进程立即退出（任务管理器验证）
- 9.3：跨版本会话文件可加载，字段补齐
- 9.4：checkpoint ref 在 `git gc` 后仍存在
- 9.5：回滚后消息与文件状态一致
- 9.6：重启 agent 后"始终允许"记忆仍生效

### 10.2 风险与回滚

- 每个 sub-stage 修改独立 commit，便于单独回滚
- 9.3 迁移机制有备份，失败可恢复
- 9.4 / 9.5 涉及 git 操作，建议先在测试仓库验证
- 9.6 持久化文件可手动删除回滚到无记忆状态

### 10.3 后续衔接

- 9.1 完成后，Stage 13 的 R5（capabilities 透传）可基于 per-tool policy 框架扩展
- 9.2 完成后，Stage 12 的 G2.3-G2.5（run_commands 运行时行为）可基于 abort 订阅扩展
- 9.3 完成后，未来任何会话格式变更都需注册迁移函数
- 9.6 完成后，Stage 10 的 A7（AgentToolContext.metadata）可基于持久化框架扩展

---

**Stage 9 结束。建议按 9.1 → 9.2 → 9.6 → 9.3 → 9.4 → 9.5 顺序执行，完成后进入 Stage 10。**
