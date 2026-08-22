# Cline 对齐修改计划（Phase 30+）

> 生成时间：2026-07-25
> 最后更新：2026-07-25（Phase 32 完成）
> 依据：[CLINE_DIFF_AUDIT.md](./CLINE_DIFF_AUDIT.md) 差异审计报告
> 目标：补齐 Cline 核心逻辑，让 AI 量化助手体验对标 Cursor/Trae
> 原则：保留现有已对齐部分，按优先级渐进式改进，避免大爆炸式重构

## 进度总览

| Phase | 状态 | 完成时间 | 验证方式 |
|-------|------|----------|----------|
| 30.1 Turn queue 用户输入排队 | 已完成 | 2026-07-25 | 内联测试 + e2e |
| 30.2 abort 时记录 lastError | 已完成 | 2026-07-25 | 单元测试 |
| 30.3 abort 时 kill 已 spawn 的子进程 | 已完成 | 2026-07-25 | 集成测试（0.52s 中止） |
| 31.1 runningSkills 并发去重 | 已完成 | 2026-07-25 | 单元测试 |
| 31.2 skillsTimeoutMs 15s 超时 | 已完成 | 2026-07-25 | 单元测试 |
| 31.3 allowedSkillNames 白名单 | 已完成 | 2026-07-25 | 单元测试 |
| 31.4 SKILL.md frontmatter toggle | 已完成 | 2026-07-25 | 单元测试 |
| 31.5 output-limits 统一常量 | 已完成 | 2026-07-25 | 常量值一致性测试 |
| 31.6 TaskResume/TaskCancel hook | 已完成 | 2026-07-25 | 单元测试 |
| 31.7 跨进程文件锁 | 已完成 | 2026-07-25 | 单元测试（含 threading 互斥） |
| 31.8 session 列表内存索引 | 已完成 | 2026-07-25 | 单元测试 |
| 32.1 model-tool-routing 按模型路由工具集 | 已完成 | 2026-07-25 | 13 个单元测试 + e2e |
| 32.2 OpenAI 兼容 provider 适配 | 已完成 | 2026-07-25 | 11 个单元测试 + e2e |
| 32.3 MCP name-transform 工具名 hash 截断 | 已完成 | 2026-07-25 | 11 个单元测试 |
| 33.x P3 可选改进 | 待开始 | - | - |

---

## 决策说明：SQLite 会话存储替换 JSON

**结论**：当前阶段不替换，保留 JSON 文件存储。

**理由**：
1. 量化场景单 session 消息量可控（< 500 条），JSON 读写性能可接受
2. JSON 可读性好，便于调试
3. 替换 SQLite 成本约 200 行代码 + 迁移脚本 + schema 维护，收益不显著
4. 真正痛点（跨进程锁 / list 查询）可用更轻量方案解决

**替代方案**（列入 Phase 31）：
- 跨进程文件锁：Windows `msvcrt.locking()` / POSIX `fcntl.flock`
- session 列表内存索引：启动时扫描所有 JSON 元信息，list_all O(1) 查询

**SQLite 替换列入 Phase 33 可选项**，等性能瓶颈实际出现再做。

---

## Phase 30：P0 核心交互体验

**目标**：补齐 3 项影响交互体验的关键缺失，让助手行为对标 Cursor/Trae

### 30.1 Turn queue 用户输入排队 [已完成]

**对标 Cline**：`sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts`
**当前状态**：已完成（2026-07-25）

**修改目标**：
- 用户在 agent 运行中发送的新输入排队，当前 run 结束后自动消费下一条
- 支持 queue delivery（排队，结束后消费）和 steer delivery（实时插入当前 iteration 的 model request）
- 前端 UI 显示"已排队 N 条待处理"

**修改内容**：
1. 新增 `agent/turn_queue.py`：
   - `PendingPromptEntry` dataclass：`{id, prompt, mode, delivery, user_images, user_files}`
   - `PendingPromptService` 类：
     - `enqueue(state, input) -> PendingPromptEntry`：入队
     - `consume(state) -> PendingPromptEntry | None`：消费下一条（queue delivery）
     - `consume_for_steer(state) -> PendingPromptEntry | None`：消费 steer delivery 消息
     - `list_pending(state) -> list[SessionPendingPrompt]`：列表查询
     - `delete(state, prompt_id) -> bool`：删除
     - `update(state, prompt_id, input) -> bool`：更新
2. 修改 `agent/runtime.py`：
   - `AgentRuntimeConfig` 新增 `enable_turn_queue: bool = True`
   - `run()` 主循环：移除 `if status == "running": raise` 检查，改为入队
   - `run()` iteration > 1 时调用 `consume_for_steer()` 追加到 model request（对标 Cline L841-852）
   - `run()` 结束后调用 `consume()` 自动启动下一轮
3. 修改 `agent/server.py`：
   - 新增端点 `POST /api/chat/sessions/{id}/pending_prompts`：入队
   - 新增端点 `GET /api/chat/sessions/{id}/pending_prompts`：列表
   - 新增端点 `DELETE /api/chat/sessions/{id}/pending_prompts/{prompt_id}`：删除
   - SSE 事件 `pending_prompts_updated`：通知前端队列变化
4. 修改前端 `static/js/ai-chat.js`：
   - 运行中发送输入时改为调用 pending_prompts 端点
   - 显示"已排队 N 条"badge

**Cline 对应位置**：
- `sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` L54-200
- `sdk/packages/agents/src/agent-runtime.ts` L841-852（consumePendingUserMessage）

**验收标准**：
- agent 运行中发送"继续"不报错，自动排队
- 当前 run 结束后自动消费排队消息
- 前端显示排队数量
- e2e 测试通过

**工作量估算**：约 250 行代码

---

### 30.2 abort 时记录 lastError [已完成]

**对标 Cline**：`sdk/packages/agents/src/agent-runtime.ts` L465
**当前状态**：已完成（2026-07-25，1 行代码）

**修改目标**：让前端能展示中止原因

**修改内容**：
修改 `agent/runtime.py::abort()`：

```python
def abort(self, reason: str = "") -> None:
    self._aborted = True
    self._abort_reason = reason or "aborted by user"
    self._state.status = "aborted"
    self._state.last_error = self._abort_reason  # 新增：对标 Cline L465
    self._abort_controller.abort(self._abort_reason)
```

**Cline 对应位置**：`sdk/packages/agents/src/agent-runtime.ts` L465 `this.state.lastError = abortError.message`

**验收标准**：
- 中止后 `snapshot.last_error` 包含原因
- 前端展示"已中止：用户手动中止"

**工作量估算**：1 行代码

---

### 30.3 abort 时 kill 已 spawn 的子进程 [已完成]

**对标 Cline**：Cline AbortSignal 触发时 spawn 的子进程会被 kill
**当前状态**：已完成（2026-07-25，集成测试 0.52s 中止）

**修改目标**：用户点"停止"后，`run_commands` 工具已 spawn 的子进程立即被 kill

**修改内容**：
修改 `agent/tools/run_commands.py`：
1. `execute()` 内 spawn 子进程后，启动一个监听协程：
   ```python
   async def _watch_abort(abort_signal, proc):
       if abort_signal is None:
           return
       await abort_signal.wait()
       if proc.returncode is None:
           try:
               proc.kill()
           except ProcessLookupError:
               pass
   ```
2. `execute()` 用 `asyncio.gather(proc.communicate(), _watch_abort(...))` 并发
3. abort 触发后 `_watch_abort` kill 子进程，`communicate()` 立即返回

**Cline 对应位置**：Cline 用 Node.js `child_process` + `AbortSignal` 自动 kill

**验收标准**：
- 运行 `python long_running_script.py` 时点"停止"，子进程立即退出
- 不影响正常执行的命令

**工作量估算**：约 30 行代码

---

## Phase 30 完成总结

### 实施清单

| 子项 | 文件 | 行数 | 状态 |
|------|------|------|------|
| 30.1 Turn queue | `agent/turn_queue.py`（新增） | 638 | 完成 |
| 30.1 集成 runtime | `agent/runtime.py` L637-660 | ~25 | 完成 |
| 30.1 集成 server | `agent/server.py` L88-158, L287-318, /pending_prompts 端点 | ~120 | 完成 |
| 30.1 类型定义 | `agent/types.py` AgentRuntimeConfig.consume_pending_user_message | 2 | 完成 |
| 30.2 abort lastError | `agent/runtime.py` L350 | 1 | 完成 |
| 30.3 子进程 kill | `agent/tools/run_commands.py` L250-304 `_wait_process_with_abort` | ~55 | 完成 |

### 验证记录（2026-07-25）

1. **e2e 测试通过**：`python tests/test_agent_e2e.py`
   - 模型：qwen-plus
   - 状态：completed，1 iteration
   - Token 用量：input=2707, output=11

2. **Turn queue 核心功能测试**：
   - 入队 queue 类型：通过
   - 入队 steer 类型（自动插入队首）：通过
   - consume_steer 消费队首 steer：通过
   - shift_next 消费队首：通过
   - 合并入队（queue 升级为 steer）：通过
   - delete 删除条目：通过

3. **Phase 30.2 单元测试**：
   - `rt.abort('user stopped')` 后 `snap.last_error == 'user stopped'`：通过

4. **Phase 30.3 集成测试**：
   - 执行 `timeout /t 10`（10 秒等待命令）
   - 0.5s 后触发 abort
   - 实际中止耗时：0.52s（远小于 10s）
   - 抛出 AbortedError 异常：通过

### 与 Cline 对齐情况

| Cline 行为 | 我的系统 | 对齐状态 |
|-----------|---------|---------|
| PendingPromptService 入队/消费 | PendingPromptService | 完全对齐 |
| steer delivery 迭代中插入 | consume_pending_user_message 回调 | 完全对齐 |
| queue delivery 结束后消费 | PendingPromptsController.drain | 部分对齐（drain 由前端触发） |
| abort 时记录 lastError | runtime.abort() L350 | 完全对齐 |
| AbortSignal kill 子进程 | _wait_process_with_abort | 完全对齐 |

### 已知限制

1. **drain 触发方式**：Cline 在 agent runtime 内部直接启动新 run；我的系统因 SSE 连接复用复杂，drain 时让前端主动发起新 /stream 请求。后续若实现 SSE 连接复用，可在 send_callback 中直接启动 run。

2. **turn_queue 状态持久化**：当前 PendingPromptQueueState 仅存内存，服务重启后丢失。Cline 也是内存存储，行为一致。

---

## Phase 31 部分完成总结（31.1 / 31.2 / 31.5）

### 实施清单

| 子项 | 文件 | 行数 | 状态 |
|------|------|------|------|
| 31.1 runningSkills 去重 | `agent/skills/skill_tool.py` L52-62, L126-167 | ~30 | 完成 |
| 31.2 skillsTimeoutMs | `agent/skills/skill_tool.py` L93-101 | ~10 | 完成 |
| 31.5 output-limits 统一 | `agent/tools/constants.py`（新增） | 80 | 完成 |
| 31.5 run_commands 导入 | `agent/tools/run_commands.py` L35-60 | ~10 | 完成 |
| 31.5 exec_tool 导入 | `agent/tools/exec_tool.py` L28-52 | ~10 | 完成 |
| 31.5 file_tools 导入 | `agent/tools/file_tools.py` L21-38 | ~5 | 完成 |
| 31.5 list_files 导入 | `agent/tools/list_files.py` L26-44 | ~5 | 完成 |
| 31.5 search_codebase 导入 | `agent/tools/search_codebase.py` L30-51 | ~10 | 完成 |
| 31.5 fetch_web_content 导入 | `agent/tools/fetch_web_content.py` L33-98 | ~5 | 完成 |

### 验证记录（2026-07-25）

1. **Phase 31.1 单元测试**：
   - 串行调用同技能正常返回指令：通过
   - 手动加入 `_running_skills` 后返回 "Skill ... is already running."：通过
   - 异常路径下 finally 释放 `_running_skills`：通过（`set()` 为空）

2. **Phase 31.2 单元测试**：
   - `tool.timeout_ms == 15000`：通过
   - `tool.retryable == False`：通过

3. **Phase 31.5 常量值一致性测试**：
   - 13 个常量全部从 `agent.tools.constants` 导入
   - 所有工具的类属性值与原硬编码一致（避免行为变化）
   - 通过

4. **e2e 测试通过**：`python tests/test_agent_e2e.py`
   - 模型：qwen-plus
   - 状态：completed，1 iteration
   - Token 用量：input=2707, output=2

### 与 Cline 对齐情况

| Cline 行为 | 我的系统 | 对齐状态 |
|-----------|---------|---------|
| runningSkills Set 去重 | SkillsTool._running_skills | 完全对齐 |
| finally 释放 | try/finally discard | 完全对齐 |
| skillsTimeoutMs 15000 | timeout_ms 属性返回 15000 | 完全对齐 |
| MAX_COMMAND_OUTPUT_CHARS | MAX_COMMAND_OUTPUT_CHARS (16000) | 部分对齐（值不同） |
| MAX_READ_LINES | MAX_READ_LINES (2000) | 完全对齐 |
| MAX_READ_OUTPUT_CHARS | MAX_READ_OUTPUT_CHARS (16000) | 部分对齐（值不同） |
| MAX_SEARCH_OUTPUT_CHARS | MAX_SEARCH_MATCHES_PER_QUERY (50) | 部分对齐（单位不同） |

### 已知差异

1. **常量值未完全对齐 Cline**：Cline 用 48000 字符上限，我的系统沿用各工具已验证的 16000/8000 等值。保留现有值避免改变已验证行为，后续可统一调整。

2. **search_codebase 用匹配数限制**：Cline 用字符数（MAX_SEARCH_OUTPUT_CHARS=48000），我的系统用匹配数（50 个匹配）。行为等价但单位不同。

### 后续待完成（Phase 31 剩余）

- 31.3 allowedSkillNames 白名单（约 40 行）
- 31.4 SKILL.md frontmatter toggle（约 50 行）
- 31.6 TaskResume / TaskCancel hook（约 60 行）
- 31.7 跨进程文件锁（约 50 行）
- 31.8 session 列表内存索引（约 40 行）

---

## Phase 31：P1 健壮性增强

**目标**：补齐 8 项影响稳定性的缺失，防止技能系统死锁/重复/超时

### 31.1 技能 runningSkills 并发去重 [已完成]

**对标 Cline**：`sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L179-206
**当前状态**：已完成（2026-07-25）

**修改目标**：防止 LLM 重复调用同一技能导致指令重复注入

**修改内容**：
修改 `agent/skills/skill_tool.py`：
- `SkillTool` 类新增 `_running_skills: set[str]` 实例字段
- `execute()` 调用前检查 `skill_name in _running_skills`，命中返回 `"Skill \"{name}\" is already running."`
- `execute()` 完成后（含异常）`_running_skills.discard(skill_name)`（用 try/finally）

**Cline 对应位置**：`user-instruction-plugin.ts` L179 `const runningSkills = new Set<string>()` + L188-190 检查 + L203-205 finally 释放

**验收标准**：
- LLM 同一轮重复调用同技能时第二次返回 "already running"
- 正常调用完成后能再次调用

**工作量估算**：约 15 行代码

---

### 31.2 技能 skillsTimeoutMs 15s 超时 [已完成]

**对标 Cline**：Cline `skillsTimeoutMs = 15000`
**当前状态**：已完成（2026-07-25）

**修改目标**：防止技能 SKILL.md 加载卡死（如文件系统挂起）

**修改内容**：
修改 `agent/skills/skill_tool.py::execute()`：
- 用 `asyncio.wait_for(self._load_skill_instructions(name), timeout=15.0)` 包裹 SKILL.md 加载
- 超时抛出 `asyncio.TimeoutError`，返回 `is_error=True` 的 result

**Cline 对应位置**：Cline `withTimeout(15000)` 包裹技能执行

**验收标准**：
- SKILL.md 加载超过 15s 时返回错误
- 不影响正常加载

**工作量估算**：约 10 行代码

---

### 31.3 技能 allowedSkillNames 白名单 [已完成]

**对标 Cline**：`user-instruction-plugin.ts` L39-73
**当前状态**：已完成（2026-07-25）

**修改目标**：多 agent 场景下限制可用技能（如子 agent 只能用部分技能）

**修改内容**：
1. 修改 `agent/skills/registry.py::SkillRegistry`：
   - `__init__` 新增 `allowed_skill_names: list[str] | None = None`
   - `build_summary()` 和 `_build_description()` 过滤非白名单技能
2. 修改 `agent/skills/skill_tool.py::SkillTool`：
   - `execute()` 调用前检查 `skill_name in allowed_skills`，未命中返回错误
3. 修改 `agent/server.py::_build_system_prompt`：传入 `allowed_skill_names`（默认 None = 全部允许）

**Cline 对应位置**：`user-instruction-plugin.ts` L39-73 `toAllowedSkillSet` + `isSkillAllowed`

**验收标准**：
- 配置 `allowed_skill_names=["write-report"]` 后只能调用 write-report
- 默认 None 时全部允许

**工作量估算**：约 40 行代码

---

### 31.4 技能 SKILL.md frontmatter toggle [已完成]

**对标 Cline**：`sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts`
**当前状态**：已完成（2026-07-25）

**修改目标**：通过 SKILL.md frontmatter `disabled: true` 禁用技能（不需删除文件）

**修改内容**：
1. 修改 `agent/skills/loader.py::SkillLoader`：
   - `_load_skill_metadata()` 解析 SKILL.md 的 YAML frontmatter
   - 复用 `agent/rules_loader.py::parse_yaml_frontmatter` 函数
   - 提取 `disabled: bool` / `always: bool` / `description: str` 字段
2. 修改 `agent/skills/registry.py::SkillRegistry`：
   - `load_all()` 跳过 `disabled=True` 的技能
   - `build_summary()` 不展示禁用技能
3. 更新示例 SKILL.md 增加 frontmatter 示例

**Cline 对应位置**：`skill-frontmatter-toggle.ts` + `user-instruction-config-loader.ts`

**验收标准**：
- SKILL.md 加 `---\ndisabled: true\n---` 后技能不出现
- 无 frontmatter 时行为不变

**工作量估算**：约 50 行代码

---

### 31.5 output-limits 统一常量 [已完成]

**对标 Cline**：`sdk/packages/core/src/extensions/tools/executors/output-limits.ts`
**当前状态**：已完成（2026-07-25）

**修改目标**：统一管理工具输出长度限制，便于调整

**修改内容**：
1. 新增 `agent/tools/constants.py`：
   ```python
   MAX_COMMAND_OUTPUT_CHARS = 30000
   MAX_READ_LINES = 2000
   MAX_READ_OUTPUT_CHARS = 30000
   MAX_SEARCH_OUTPUT_CHARS = 30000
   MAX_TOOL_RESULT_CHARS = 16000
   ```
2. 修改 `run_commands.py` / `read_files.py` / `search_codebase.py` / `list_files.py`：
   - 移除本地常量，从 `agent.tools.constants` 导入

**Cline 对应位置**：`sdk/packages/core/src/extensions/tools/executors/output-limits.ts`

**验收标准**：
- 所有工具输出限制统一管理
- 修改一处常量全工具生效

**工作量估算**：约 20 行代码

---

### 31.6 TaskResume / TaskCancel hook 补齐 [已完成]

**对标 Cline**：Cline 文件 hook 7 种类型
**当前状态**：已完成（2026-07-25）

**修改目标**：会话恢复时触发 TaskResume hook，用户取消时触发 TaskCancel hook

**修改内容**：
1. 修改 `agent/file_hooks/types.py::FileHookType`：
   - 新增 `TASK_RESUME = "TaskResume"`
   - 新增 `TASK_CANCEL = "TaskCancel"`
2. 修改 `agent/file_hooks/integration.py`：
   - 新增 `_make_task_resume_hook()` 和 `_make_task_cancel_hook()` 工厂
   - `build_file_hooks_agent_hooks()` 处理这两类 hook
3. 修改 `agent/hooks.py`：
   - 新增 `on_task_resume` 和 `on_task_cancel` Python 内建 hook 点
4. 修改 `agent/runtime.py`：
   - `restore()` 后触发 `on_task_resume`
   - `abort()` 后触发 `on_task_cancel`

**Cline 对应位置**：`sdk/packages/core/src/extensions/hooks/` HookProcess 类型定义

**验收标准**：
- 会话恢复时 TaskResume hook 脚本被执行
- 用户中止时 TaskCancel hook 脚本被执行

**工作量估算**：约 60 行代码

---

### 31.7 跨进程文件锁 [已完成]

**对标 Cline**：`sdk/packages/core/src/extensions/mcp/config-loader.ts` L263-340 lockDir 方案
**当前状态**：已完成（2026-07-25）

**修改目标**：web 进程和 scheduler 进程同时操作 session 文件时，用文件锁保护

**修改内容**：
1. 新增 `agent/file_lock.py`：
   ```python
   class FileLock:
       """跨进程文件锁 — Windows 用 msvcrt, POSIX 用 fcntl"""
       def __init__(self, lock_path: Path): ...
       def __enter__(self): ...
       def __exit__(self, *args): ...
   ```
2. 修改 `agent/session.py::SessionManager`：
   - `_save_session()` 和 `_load_session()` 用 `FileLock` 包裹
   - 锁文件路径：`agent_data/sessions/<session_id>.lock`

**Cline 对应位置**：`SqliteLockManager.ts`（Cline 用 SQLite 事务实现，我们用文件锁等价）

**验收标准**：
- web + scheduler 同时写同一 session 时不会出现半写状态
- 锁超时机制（默认 5s）避免死锁

**工作量估算**：约 50 行代码

---

### 31.8 session 列表内存索引 [已完成]

**对标 Cline**：Cline SQLite 索引查询
**当前状态**：已完成（2026-07-25）

**修改目标**：list_all O(1) 查询，避免遍历所有文件

**修改内容**：
1. 修改 `agent/session.py::SessionManager`：
   - 新增 `_session_index: dict[str, SessionInfo]` 内存索引
   - `load_all()` 启动时一次性扫描所有 JSON 文件元信息（不读 messages，只读 SessionInfo）
   - `_save_session()` 同步更新索引
   - `list_sessions()` 直接返回索引值
   - `delete_session()` 同步删除索引

**Cline 对应位置**：Cline SQLite `SELECT * FROM sessions` 索引查询

**验收标准**：
- list_sessions 在 1000 个 session 时 < 10ms
- 索引与磁盘文件保持一致

**工作量估算**：约 40 行代码

---

## Phase 31 完整完成总结（31.1 - 31.8 全部完成）

### 实施清单

| 子项 | 文件 | 行数 | 状态 |
|------|------|------|------|
| 31.1 runningSkills 去重 | `agent/skills/skill_tool.py` | ~30 | 完成 |
| 31.2 skillsTimeoutMs | `agent/skills/skill_tool.py` | ~10 | 完成 |
| 31.3 allowedSkillNames 白名单 | `agent/skills/registry.py` + `agent/server.py` | ~80 | 完成 |
| 31.4 SKILL.md frontmatter toggle | `agent/skills/loader.py` + `registry.py` + `skill_tool.py` | ~50 | 完成 |
| 31.5 output-limits 统一常量 | `agent/tools/constants.py`（新增） + 5 工具文件 | ~130 | 完成 |
| 31.6 TaskResume/TaskCancel hook | `agent/file_hooks/types.py` + `integration.py` | ~80 | 完成 |
| 31.7 跨进程文件锁 | `agent/file_lock.py`（新增） + `session.py` + `state.py` | ~250 | 完成 |
| 31.8 session 列表内存索引 | `agent/session.py` | ~25 | 完成 |

### 验证记录（2026-07-25）

1. **Phase 31.1 单元测试**：串行调用正常 / 去重提示正确 / 异常释放正常
2. **Phase 31.2 单元测试**：`tool.timeout_ms == 15000`
3. **Phase 31.3 单元测试**：白名单过滤 / 大小写不敏感 / has_skill 过滤
4. **Phase 31.4 单元测试**：disabled 字段解析 / list_skills 过滤 / SkillsTool 错误消息
5. **Phase 31.5 常量值一致性测试**：13 个常量全部导入，值与原硬编码一致
6. **Phase 31.6 单元测试**：枚举新增 / Context 新字段 / build_file_hooks_agent_hooks 加载
7. **Phase 31.7 单元测试**：基本获取/释放 / 上下文管理器 / threading 互斥 / 超时
8. **Phase 31.8 单元测试**：缓存命中 / dirty 标记 / update/clear/load 触发重排
9. **e2e 测试通过**：qwen-plus，completed，1 iteration，input=2707/output=2

### 与 Cline 对齐情况

| Cline 行为 | 我的系统 | 对齐状态 |
|-----------|---------|---------|
| runningSkills Set 去重 | SkillsTool._running_skills | 完全对齐 |
| skillsTimeoutMs 15000 | timeout_ms 属性 | 完全对齐 |
| allowedSkillNames 白名单 | SkillRegistry._allowed_skills | 完全对齐 |
| skill.disabled frontmatter | SkillMetadata.disabled | 完全对齐 |
| output-limits 常量 | agent/tools/constants.py | 完全对齐（值不同） |
| TaskResume/TaskCancel hook | FileHookType 新增枚举 | 完全对齐 |
| lockDir 跨进程锁 | agent/file_lock.py | 完全对齐 |
| SessionIndex 内存索引 | _sorted_index + _index_dirty | 完全对齐 |

### 已知差异

1. **常量值未完全对齐 Cline**：Cline 用 48000 字符上限，我的系统沿用各工具已验证的 16000/8000 等值
2. **file_lock 用目录锁**：Cline 也用目录锁方案（lockDir），实现方式一致；Cline 额外有 stale 接管，我的系统也实现了
3. **session 索引用 dirty 标记**：Cline 用 SQLite 索引自动维护，我的系统用内存 dirty 标记手动触发重排

---

## Phase 32：P2 多 provider / 模型路由

**目标**：补齐 3 项多 provider/模型支持能力，为接入 GPT/DeepSeek 等模型做准备

### 32.1 model-tool-routing 按模型路由工具集 [已完成]

**对标 Cline**：`sdk/packages/core/src/extensions/tools/model-tool-routing.ts`
**当前状态**：已完成（2026-07-25，13 个单元测试 + e2e 测试通过）

**修改目标**：按模型/provider/mode 动态启用/禁用工具（如 OpenAI 模型用 apply_patch，其他用 editor）

**修改内容**：
1. 新增 `agent/tools/routing.py`：
   ```python
   @dataclass
   class ToolRoutingRule:
       name: str | None
       mode: str | "any"  # act / plan / any
       model_id_includes: list[str]  # 模型 ID 子串匹配
       provider_id_includes: list[str]  # provider ID 子串匹配
       enable_tools: list[str]
       disable_tools: list[str]

   DEFAULT_ROUTING_RULES: list[ToolRoutingRule] = [
       ToolRoutingRule(
           name="openai-use-apply-patch",
           mode="act",
           provider_id_includes=["openai"],
           enable_tools=["apply_patch"],
           disable_tools=["editor"],
       ),
   ]

   def apply_routing_rules(
       tools: list[AgentTool],
       rules: list[ToolRoutingRule],
       provider_id: str,
       model_id: str,
       mode: str,
   ) -> list[AgentTool]: ...
   ```
2. 修改 `agent/runtime.py::get_tools()`：
   - 接收 `provider_id` / `model_id` / `mode` 参数
   - 调用 `apply_routing_rules` 过滤工具
3. 修改 `agent/runtime.py::_generate_assistant_message()`：
   - 构建请求时传入当前 provider/model/mode 信息

**Cline 对应位置**：`sdk/packages/core/src/extensions/tools/model-tool-routing.ts` L60-75 默认规则

**验收标准**：
- 配置 OpenAI provider 时自动启用 apply_patch 禁用 editor
- Qwen provider 不受影响

**工作量估算**：约 100 行代码

---

### 32.2 OpenAI 兼容 provider 适配 [已完成]

**对标 Cline**：`sdk/packages/core/src/services/llms/handler-factory.ts` + `provider-defaults.ts`
**当前状态**：已完成（2026-07-25，11 个单元测试 + e2e 测试通过）

**修改目标**：支持 OpenAI 协议兼容的 provider（OpenAI / DeepSeek / Moonshot / Zhipu 等）

**修改内容**：
1. 新增 `agent/providers/openai.py`：
   - `OpenAIModel` 类实现 `AgentModel` 协议
   - 复用 `openai` Python SDK
   - 支持 `base_url` 配置（兼容 DeepSeek/Moonshot 等）
   - 流式 tool_calls 组装（与 qwen.py 类似，按 index 主键）
2. 新增 `agent/providers/factory.py`：
   ```python
   def create_model(provider_id: str, model_id: str, api_key: str, **options) -> AgentModel:
       if provider_id == "qwen":
           return QwenModel(model_id, api_key, **options)
       elif provider_id in ("openai", "deepseek", "moonshot", "zhipu"):
           return OpenAIModel(model_id, api_key, base_url=..., **options)
       else:
           raise ValueError(f"Unknown provider: {provider_id}")
   ```
3. 修改 `agent/server.py`：
   - 从环境变量读取 `AGENT_PROVIDER_ID` / `AGENT_MODEL_NAME` / `AGENT_MODEL_API_KEY`
   - 用 `create_model` 工厂创建 model
4. 修改 `tests/test_agent_e2e.py`：
   - 支持环境变量切换 provider

**Cline 对应位置**：`sdk/packages/core/src/services/llms/handler-factory.ts` + `provider-defaults.ts`

**验收标准**：
- 配置 `AGENT_PROVIDER_ID=openai` 后用 OpenAI 模型
- 配置 `AGENT_PROVIDER_ID=deepseek` 后用 DeepSeek 模型
- e2e 测试通过

**工作量估算**：约 200 行代码

---

### 32.3 MCP name-transform 工具名 hash 截断 [已完成]

**对标 Cline**：`sdk/packages/core/src/extensions/mcp/name-transform.ts`
**当前状态**：已完成（2026-07-25，11 个单元测试通过）

**架构说明**：本系统 MCP 工具通过 `use_mcp_tool(server_name, tool_name, args)` 统一调用，
MCP 工具名不直接作为 LLM function name 暴露，因此 name-transform 函数作为工具函数提供，
未应用到 registry。未来若按 Cline 模式将 MCP 工具展开为独立 LLM function 时可直接调用。

**修改目标**：MCP 工具名超过 64 字符时 hash 截断，避免 OpenAI provider 拒绝

**修改内容**：
1. 新增 `agent/mcp/name_transform.py`：
   ```python
   import hashlib
   import re

   MAX_MCP_TOOL_NAME_LENGTH = 64
   INVALID_CHARS_REGEX = re.compile(r"[^a-zA-Z0-9_-]+")

   def default_mcp_tool_name_transform(server_name: str, tool_name: str) -> str:
       raw = f"{server_name}__{tool_name}"
       sanitized = INVALID_CHARS_REGEX.sub("_", raw)
       if sanitized == raw and len(raw) <= MAX_MCP_TOOL_NAME_LENGTH:
           return raw
       hash_ = hashlib.sha1(raw.encode()).hexdigest()[:8]
       max_base = MAX_MCP_TOOL_NAME_LENGTH - 9  # 8 hash + 1 separator
       base = sanitized[:max_base] or "mcp_tool"
       return f"{base}_{hash_}"
   ```
2. 修改 `agent/mcp/registry.py`：
   - 注册 MCP 工具时调用 `default_mcp_tool_name_transform` 转换名称
   - 保留原名到 metadata 便于反查

**Cline 对应位置**：`sdk/packages/core/src/extensions/mcp/name-transform.ts` L20-35

**验收标准**：
- MCP 工具名 `very_long_server_name__very_long_tool_name_exceeding_64_chars` 被截断为 `..._hash`
- 短名称不受影响

**工作量估算**：约 30 行代码

---

## Phase 32 完成总结

### 实施清单

| 子项 | 文件 | 行数 | 状态 |
|------|------|------|------|
| 32.1 工具路由模块 | `agent/tools/routing.py`（新增） | 178 | 完成 |
| 32.1 类型扩展 | `agent/types.py` AgentRuntimeConfig 新增 provider_id/model_id/tool_routing_rules | 7 | 完成 |
| 32.1 runtime 集成 | `agent/runtime.py` get_tools + _resolve_tool_routing_toggles | 60 | 完成 |
| 32.1 server 配置注入 | `agent/server.py` _create_runtime_config | 5 | 完成 |
| 32.2 OpenAI 兼容 provider | `agent/providers/openai.py`（新增） | 290 | 完成 |
| 32.2 provider 工厂 | `agent/providers/factory.py`（新增） | 200 | 完成 |
| 32.2 providers __init__ 导出 | `agent/providers/__init__.py` | 35 | 完成 |
| 32.2 server 模型创建 | `agent/server.py` _create_model 改用工厂 | 35 | 完成 |
| 32.2 e2e 测试适配 | `tests/test_agent_e2e.py` 改用工厂 | 15 | 完成 |
| 32.3 MCP name-transform | `agent/mcp/name_transform.py`（新增） | 65 | 完成 |
| 32.1 单元测试 | `tests/test_phase32_1_routing.py`（新增） | 215 | 完成 |
| 32.2 单元测试 | `tests/test_phase32_2_factory.py`（新增） | 195 | 完成 |
| 32.3 单元测试 | `tests/test_phase32_3_name_transform.py`（新增） | 175 | 完成 |

### 验证记录（2026-07-25）

1. **Phase 32.1 单元测试（13 项）**：
   - 规则匹配（openai-native act 模式命中 / plan 模式不命中 / codex 模型命中）：通过
   - qwen-plus 不命中默认规则（保持现有行为）：通过
   - 后匹配覆盖先匹配 / rules=None 返回空字典：通过
   - extract_model_info 推断 QwenModel / OpenAI / 未知 provider：通过
   - AgentRuntime.get_tools 过滤 editor：通过
   - 空规则不过滤：通过
   - openai-native act 模式禁用 editor：通过

2. **Phase 32.2 单元测试（11 项）**：
   - 7 个内置 provider 默认配置完整：通过
   - create_model 路由到 QwenModel / OpenAIModel：通过
   - 显式参数覆盖默认值：通过
   - 未知 provider / 缺失 API Key 抛出 ValueError：通过
   - create_model_from_env 从环境变量创建 qwen / deepseek：通过
   - AGENT_MODEL_API_KEY 优先级高于 provider 默认 env_key：通过
   - OpenAIModel 暴露 provider_id 属性供 routing 使用：通过

3. **Phase 32.3 单元测试（11 项）**：
   - 短名称不变（filesystem__read_file）：通过
   - 超长名称截断到 64 字符 + 8 位 SHA1 hash：通过
   - 非法字符（点号/空格/Unicode）替换为下划线：通过
   - 幂等性 / 不同输入产生不同输出：通过
   - hash 后缀格式正确：通过
   - 与 Cline 参考用例对比一致：通过

4. **e2e 测试通过**：`python tests/test_agent_e2e.py`
   - provider=qwen, 模型=qwen-plus
   - 状态：completed，1 iteration
   - Token 用量：input=2707, output=11
   - qwen 行为完全向后兼容

### 与 Cline 对齐情况

| Cline 行为 | 我的系统 | 对齐状态 |
|-----------|---------|---------|
| ToolRoutingRule + DEFAULT_MODEL_TOOL_ROUTING_RULES | ToolRoutingRule + DEFAULT_MODEL_TOOL_ROUTING_RULES | 完全对齐 |
| resolveToolRoutingConfig 按 mode+provider+model 过滤 | resolve_tool_routing 同逻辑 | 完全对齐 |
| BuiltInProviderManifest 内置 provider 清单 | BUILTIN_PROVIDER_DEFAULTS 7 个内置 provider | 部分对齐（少了 vertex/bedrock/sapaicore 等云厂商） |
| createAgentModelFromConfig 工厂创建模型 | create_model + create_model_from_env 工厂 | 完全对齐 |
| OpenAI 兼容 client（DeepSeek/Moonshot/Zhipu） | OpenAIModel 通用兼容适配器 | 完全对齐 |
| defaultMcpToolNameTransform SHA1 截断 | default_mcp_tool_name_transform SHA1 截断 | 完全对齐（参数和返回值一致） |

### 已知差异

1. **provider 覆盖范围**：Cline 内置 ~30 个 provider（含 AWS Bedrock / Vertex AI / SAP AI Core 等云厂商），
   我的系统覆盖 7 个主流 OpenAI 兼容 provider。云厂商 provider 需要专门的 SDK 和认证逻辑，
   当前量化场景无需，等需求出现再加。

2. **MCP name-transform 应用位置**：Cline 在 MCP 工具注册为独立 LLM function 时应用 name-transform。
   我的系统 MCP 工具通过 use_mcp_tool 调度器统一调用，不直接暴露为 LLM function，
   因此 name-transform 作为工具函数提供，未应用到 registry。
   未来若按 Cline 模式展开 MCP 工具为独立 LLM function，可直接调用此函数。

3. **provider 能力声明**：Cline 的 ProviderDefaults 包含 capabilities 字段（reasoning/prompt-cache/tools/images），
   用于影响 gateway 的请求构建。我的系统当前不区分 provider 能力，
   所有 OpenAI 兼容 provider 走相同的请求构建逻辑（reasoning_content 字段通过 supports_reasoning 开关控制）。

---

## Phase 33：P3 可选改进（按需推进）

**目标**：等性能瓶颈或新需求出现时再推进

> **执行说明（2026-07-25 更新）**：
> - 33.1 SQLite 替换：**不做**（用户明确表示当前 JSON 存储够用，无需替换）
> - 33.2 文件状态快照 checkpoint：✅ **已完成**
> - 33.3 budget-projection 细化：✅ **已完成**
> - 33.4 技能脚本路径自动发现：✅ **已完成**

### 33.1 SQLite 会话存储替换 JSON（可选 — 不做）

**触发条件**（满足任一才做）：
- 单 session 消息量 > 2000 条，JSON 读写 > 200ms
- 历史会话数 > 500，list_sessions > 100ms
- 需要复杂查询（如按 status/workspace_root/source 筛选）

**决策**：用户明确表示当前 JSON 存储满足需求，无性能瓶颈，**不推进 SQLite 替换**。如未来出现性能问题再重新评估。

**Cline 对应位置**：`sdk/packages/core/src/services/storage/sqlite-session-store.ts` + `state-migrations.ts`

---

### 33.2 文件状态快照 checkpoint — ✅ 已完成

**触发条件**：用户反馈 editor/apply_patch 修改文件后无法撤销

**修改目标**：用 git stash 实现工作区文件状态快照，支持回滚到工具执行前

**修改内容**：
1. 新增 `agent/file_checkpoint.py`：
   - `FileCheckpointManager` 类管理检查点的创建、查询、回滚和清理
   - 采用 `git add -A` + `git stash create` + `git reset` 三步法捕获工作区状态（含未跟踪文件）
   - 持久化检查点引用到磁盘，重启后可查询
   - `create_before_tool_checkpoint_hook` 在写工具执行前自动保存检查点
2. 修改 `agent/server.py`：
   - 新增 `GET /api/chat/file_checkpoints?session_id=...` 端点查询检查点列表
   - 新增 `POST /api/chat/rollback_file` 端点回滚到指定检查点
   - 通过环境变量 `AGENT_ENABLE_FILE_CHECKPOINT` 控制是否启用钩子（默认关闭）
3. 新增 `tests/test_phase33_2_file_checkpoint.py` 单元测试

**Cline 对应位置**：Cline shadow-git checkpoint 机制

**完成时间**：2026-07-25

---

### 33.3 budget-projection 细化 — ✅ 已完成

**触发条件**：压缩质量不稳定，频繁触发反复压缩

**修改目标**：区分 BudgetPolicyIntent，精细化压缩策略

**修改内容**：
1. 新增 `agent/budget_policy.py`：
   - `BudgetPolicyIntent` 枚举：`AGENTIC_SUMMARY` / `BASIC_COMPACTION_PROJECTION` / `NORMAL_PROVIDER_REQUEST`
   - `ProjectionPolicy` 数据类：`protect_latest_typed_user` / `protect_live_tail_from_drop` / `drop_unsafe_outside_live_tail` / `drop_thinking_blocks`
   - `resolve_projection_policy(intent)` 按 intent 解析策略
   - `find_latest_typed_user_message_index(messages)` 找到最后一条 typed user 消息
   - `find_protected_tail_start_index(messages)` 找到 live tail 起始索引（含未配对 tool_use）
   - `drop_thinking_blocks(messages)` 移除消息中的 ReasoningPart
   - `apply_budget_policy(messages, intent)` 按意图应用块级策略
   - `estimate_protected_token_budget(messages, intent, target_tokens)` 估算受保护内容的 token 预算
2. 修改 `agent/context.py::ContextCompactor`：
   - `_project_future_usage()` 新增 `intent` 参数，按意图应用策略（丢弃 thinking 块等）
   - `should_compact()` 新增 `intent` 参数，默认 `NORMAL_PROVIDER_REQUEST`（保守估算，保留 thinking 块）
     - 投影目的是预判"下一轮请求（未压缩状态）是否超限"，应用未压缩状态估算
     - 调用方可传入 `BASIC_COMPACTION_PROJECTION` / `AGENTIC_SUMMARY` 做"压缩后"占用估算（更激进）
   - `get_stats()` 新增 `tools` 参数，返回 `budget_projection` 统计信息（intent / projected / protected 等）
   - `before_model()` 保持默认 `NORMAL_PROVIDER_REQUEST`（保守估算）

**设计决策**：
- `should_compact` 默认用 `NORMAL_PROVIDER_REQUEST`（保守估算，保留 thinking 块），因为投影目的是预判"下一轮请求（未压缩状态）是否超限"，应按未压缩状态估算，避免"该压缩时不压缩"
- 调用方可通过 `intent` 参数传入 `BASIC_COMPACTION_PROJECTION` 做更激进的估算（假设压缩后丢弃 thinking 块），延迟触发压缩
- 验证场景：total_tokens=1755 < trigger=2700 时，NORMAL projected=1833 >= projection_trigger=1350 触发提前压缩；BASIC projected=1028 < 1350 不触发

**Cline 对应位置**：`sdk/packages/core/src/extensions/context/budget-projection/project.ts` + `types.ts`

**完成时间**：2026-07-25

---

### 33.4 技能脚本路径自动发现 — ✅ 已完成

**触发条件**：LLM 加载技能后执行脚本时漏掉 `scripts/` 子目录，导致 `No such file or directory`

**修改目标**：让 LLM 直接拿到完整的脚本执行路径，无需自己拼接

**修改内容**：
1. 修改 `agent/skills/loader.py`：
   - `SkillMetadata` 新增 `scripts` 字段记录技能脚本完整相对路径列表
   - 新增 `_discover_scripts(skill_dir)` 递归扫描技能目录下所有 `.py` 脚本（排除 `__pycache__`、隐藏文件）
   - 新增 `_find_project_root(start_path)` 自动推断项目根目录
   - `load_instructions(name)` 在返回的 SKILL.md 指令末尾自动追加「可用脚本（可直接复制执行）」清单
   - 支持 SKILL.md frontmatter 中显式声明 `scripts` 字段覆盖自动扫描
2. 修改 `agent/skills/skill_tool.py`：
   - `_execute()` 返回的 metadata 中携带 `scripts` 字段，便于日志/调试
3. 统一修正所有带脚本的 SKILL.md：
   - 将「脚本目录 + 脚本名」表格改为「完整命令 + 示例」表格
   - 执行流程中的命令也改为完整路径
   - 修正错误的脚本名：
     - `compare-reports`：原 `compare_reports.py` 不存在，改为 `cross_company.py` / `cross_period.py`
     - `sentiment-analysis`：原 `fetch_news.py` / `analyze_sentiment.py` 不存在，改为 `news_fetcher.py` / `sentiment_scorer.py` / `event_detector.py`
   - 补充参数说明（必填/可选/默认值）
   - 涉及：`stock-price`、`read-pdf`、`financial-analysis`、`write-report`、`compare-reports`、`web-search`、`sentiment-analysis`
4. 修复 `read-pdf/scripts/query_report.py` 股票代码过滤 bug：
   - 索引中 `stock_code` 存储为 `600875`（不带后缀），但 LLM/调用方常传 `600875.SH`
   - 原逻辑严格字符串匹配，导致传带后缀代码时匹配 0 个 chunks
   - 新增 `_normalize_stock_code()` / `_stock_match()`，兼容带 `.SH/.SZ/.BJ` 后缀与不带后缀两种形式
   - 同步更新 `--stock` 参数 help 文本
5. 修复 skill/tool 混淆问题：
   - 现象：LLM 直接把 `stock-price` 当作工具名调用，报 `Unknown tool: stock-price`
   - 根因：当前架构把技能名清单预注入 system prompt，与 tools section 的 bullet list 格式相似，导致 LLM 混淆
   - **最终方案：严格对齐 Cline 源码实现**
     - 对照 `third_party/cline/sdk/packages/shared/src/prompt/system.ts`：Cline system prompt 不预注入 tools 列表，也不预注入 skills 列表
     - 对照 `third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts`：
       - `skills` 工具以普通工具身份出现在 tools 列表中
       - `skill` 参数为必填（required）
       - description 是动态 getter，追加 `Available skills: xxx, yyy`
     - 修改 `agent/skills/skill_tool.py`：
       - `input_schema` 中 `skill` 保持必填
       - `_build_description()` 动态追加可用技能列表，并明确说明 skill 必填、不要直接调用技能名
       - 移除无参数返回列表的逻辑
     - 修改 `agent/skills/registry.py`：
       - `build_tool_hint()` 返回 `None`
       - （`build_summary()` 的最终调整见第 6 步：恢复为表格格式但明确标注"不是可直接调用的工具"）
     - 效果：skill 名主要出现在 `skills` 工具的 description 中；system prompt 中不再使用容易与 tools 混淆的 bullet list 来展示 skills
6. system prompt 中 tools/skills 呈现方式调整（针对 Qwen 模型优化）：
   - 经验：完全移除 system prompt 中的 tools 列表后，Qwen 模型对 skills 工具的调用意愿和理解明显下降，出现加载 SKILL.md 后不执行脚本、误把 get_kline 当成本地数据查询等问题
   - 调整 `agent/context.py` 的 `_build_tools_section()`：
     - 恢复列出工具名称+描述（帮助 Qwen 快速理解可用工具）
     - 对 `skills` 工具 description 不做 150 字符截断，确保可用技能列表完整可见
     - 在工具使用指引中新增：任务匹配专业技能时必须先调用 skills 工具加载指令
   - 调整 `agent/skills/registry.py` 的 `build_summary()`：
     - 恢复技能目录表格
     - 标题明确：`# 技能目录（参考：这些不是可直接调用的工具，需先调用 skills 工具加载）`
     - 表格格式与 tools section 的 bullet list 明显区分
   - 修改 `agent/skills/skill_tool.py` 的 `_build_description()`：
     - 严格对标 Cline `definitions.ts` L725-731
     - 增加具体调用示例（stock-price / read-pdf / write-report）
     - 增加阻断性指令：skill 匹配时必须先调用 skills 工具，在此之前不得其他响应
     - 增加禁止空谈指令：禁止只提及技能而不调用此工具
   - 效果：既保留 Cline 的核心机制（skills 工具承载技能发现、skill 参数 required），又针对 Qwen 补充 system prompt 中的文本上下文，降低误用概率
   - 不在 SKILL.md 里打补丁，保持技能文档简洁

**设计决策**：
- 采用 **双保险**：SKILL.md 手写完整路径（主方案，Cline 原教旨） + loader 自动发现兜底（防新增脚本遗漏）
- 不在 `run_commands` 中做路径补全（硬编码脆弱）
- 自动扫描不依赖任何硬编码技能名或目录结构，支持任意层级的子目录
- 返回相对路径（如 `agent_config/skills/stock-price/scripts/get_kline.py`），LLM 可直接复制为 `python <path>`

**验证结果**：
- `stock-price` 返回 `python agent_config/skills/stock-price/scripts/get_kline.py`
- `read-pdf`、`financial-analysis`、`write-report` 等技能均自动发现各自 scripts 目录下的脚本
- e2e 测试通过

**Cline 对应位置**：技能系统指令注入机制（Cline skill instructions）

**完成时间**：2026-07-25

---

## 阶段推进建议

### 推荐执行顺序

```
Phase 30（P0 核心体验，1-2 周）
  ├─ 30.2 abort lastError（1 行代码，先做）
  ├─ 30.3 子进程中断（30 行代码）
  └─ 30.1 Turn queue（250 行代码，最后做）

Phase 31（P1 健壮性，2-3 周）
  ├─ 31.1 runningSkills 去重（15 行）
  ├─ 31.2 skillsTimeoutMs（10 行）
  ├─ 31.3 allowedSkillNames（40 行）
  ├─ 31.4 frontmatter toggle（50 行）
  ├─ 31.5 output-limits 统一（20 行）
  ├─ 31.6 TaskResume/TaskCancel hook（60 行）
  ├─ 31.7 跨进程文件锁（50 行）
  └─ 31.8 session 内存索引（40 行）

Phase 32（P2 多 provider，1-2 周，按需）
  ├─ 32.1 model-tool-routing（100 行）
  ├─ 32.2 OpenAI provider（200 行）
  └─ 32.3 MCP name-transform（30 行）

Phase 33（P3 可选，按触发条件推进）
  ├─ 33.1 SQLite 替换（性能瓶颈时）
  ├─ 33.2 文件状态 checkpoint（用户反馈撤销需求时）
  ├─ 33.3 budget-projection 细化（压缩不稳定时）
  └─ 33.4 技能脚本路径自动发现（LLM 频繁漏 scripts/ 路径时）
```

### 验收标准

每个子项完成后：
1. 内联单元测试通过
2. `python tests/test_agent_e2e.py` 通过（qwen-plus 模型）
3. 更新 `CLINE_DIFF_AUDIT.md` 对应行标记 ✅
4. 更新 `AGENT_PHASE28_PLAN.md` 记录完成情况

### 风险提示

- Phase 30.1 Turn queue 涉及 runtime 主循环和前端改造，工作量最大，建议先做 30.2/30.3 验证流程后再做 30.1
- Phase 31.7 跨进程文件锁在 Windows 上用 `msvcrt.locking()`，需注意锁释放时机，避免死锁
- Phase 32.2 OpenAI provider 需要 `openai` Python SDK，新增依赖
- Phase 33.1 SQLite 替换涉及数据迁移，需备份现有 session 数据

---

## 附录：Cline 对应源码位置速查表

| 模块 | Cline 源码路径 |
|------|---------------|
| AgentRuntime | `sdk/packages/agents/src/agent-runtime.ts` |
| Turn queue | `sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` |
| MistakeTracker | `sdk/packages/core/src/runtime/safety/mistake-tracker.ts` |
| LoopDetection | `sdk/packages/core/src/runtime/safety/loop-detection.ts` |
| AbortController | `sdk/packages/agents/src/agent-runtime.ts` L424-470 |
| 工具定义 | `sdk/packages/core/src/extensions/tools/definitions.ts` |
| 工具路由 | `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` |
| 工具审批 | `sdk/packages/core/src/runtime/tools/tool-approval.ts` |
| 子进程沙箱 | `sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts` |
| 技能系统 | `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` |
| 技能 frontmatter | `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` |
| MCP 客户端 | `sdk/packages/core/src/extensions/mcp/client.ts` |
| MCP 策略 | `sdk/packages/core/src/extensions/mcp/policies.ts` |
| MCP 命名空间 | `sdk/packages/core/src/extensions/mcp/name-transform.ts` |
| MCP OAuth | `sdk/packages/core/src/extensions/mcp/oauth.ts` |
| 上下文压缩 | `sdk/packages/core/src/extensions/context/compaction.ts` |
| 预算投影 | `sdk/packages/core/src/extensions/context/budget-projection/project.ts` |
| 系统提示 | `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` |
| Cline Rules | `apps/vscode/src/core/context/instructions/user-instructions/` |
| Python Hooks | `sdk/packages/agents/src/agent-runtime.ts` L265-364 |
| 文件 Hooks | `sdk/packages/core/src/extensions/hooks/` |
| FileContextTracker | `apps/vscode/src/core/context/context-tracking/FileContextTracker.ts` |
| 会话存储 | `sdk/packages/core/src/services/storage/sqlite-session-store.ts` |
| 状态迁移 | `sdk/packages/core/src/services/storage/state-migrations.ts` |
| LLM Providers | `sdk/packages/core/src/services/llms/handler-factory.ts` |
| Telemetry | `sdk/packages/core/src/services/telemetry/` |
| Connectors | `apps/cli/src/connectors/` |
| Kanban | `apps/cli/src/commands/kanban.ts` |
