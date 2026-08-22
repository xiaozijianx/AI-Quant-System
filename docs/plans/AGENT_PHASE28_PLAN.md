# AGENT_PHASE28_PLAN.md — Cline 对齐重构计划（Phase 28+）

> 本文件承载 Phase 28 之后的全部重构计划。原 `AGENT_MIGRATION_PLAN.md`（Phase 1-27）
> 已 2900+ 行，作为历史归档保留，不再追加新章节。两文件互相引用。

## 一、现状基线（Phase 1-27 已完成摘要）

| Phase | 主题 | 关键产出 |
|-------|------|---------|
| 1-9 | 基础架构搭建 | 类型系统、AgentRuntime、Qwen Provider、工具系统、技能系统、系统提示、前端集成 |
| 10-15 | 第二轮重构 | Sub-agent 化、结构化工具、TodoWrite/Plan Mode、上下文压缩、AGENTS.md Cline 化、前端 Cursor 风格 |
| 16-25 | 第三轮重构（Cline 完整对齐） | SystemPromptBuilder 分层、Cline 核心工具迁移、会话持久化、工具审批、Sub-agent 工具集配置、Checkpoint、MCP、Hooks、Telemetry/Connectors/Kanban |
| 26 | Cline 真实逻辑对齐修复 | P0-1~P0-8 + P1-1/P1-2 全部完成：tool_call 按 index 组装、invalidToolCalls、schema 规范化、LoopDetectionTracker、usage delta 零值过滤、tool result 不强制序列化、completion_policy、restore() |
| 27 | 技能系统目录与执行架构重构 | 子 agent 隔离 → Cline 原生 skills 指令注入；数据/脚本迁移到项目根目录；脚本路径固定；read_files 相对路径修复；报告期选择规则；web_search 依赖修复 |

**整体对齐度**：约 70%。核心 loop、技能指令注入、上下文压缩、系统提示分层、9 个内建 hooks、循环检测已对齐 Cline。

---

## 二、与 Cline 的差异矩阵

### 模块 A：AgentRuntime 主循环

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 主循环结构 | `while iteration < maxIterations` | `runtime.py::run()` | 已对齐 |
| `completion_policy` | `requireCompletionTool` + `completionGuard` | `CompletionPolicy` dataclass | 已对齐 |
| `restore(messages)` | agent-runtime.ts L487-503 | 已实现 | 已对齐 |
| `invalid_tool_calls` 反馈 | agent-runtime.ts L1031-1058 | `_extract_invalid_tool_calls` | 已对齐 |
| `_PendingToolAssembly` by index | agent-runtime.ts L965-1000 | runtime.py L617-628 | 已对齐 |
| `normalize_input_for_schema` | agent-runtime.ts L1365-1367 | 已实现 | 已对齐 |
| `usage_delta` 零值过滤 | agent-runtime.ts L302-347 | `_compute_usage_delta` | 已对齐 |
| `tool-result` 不强制序列化 | agent-runtime.ts L1541-1549 | `ToolResultPart.output` 保留原类型 | 已对齐 |
| `MistakeTracker` 同类错误分类 | mistake-tracker.ts | 仅 `_check_repeated_tool_failures` 内联 | **缺失** |
| `AbortController.signal` 透传 | agent-runtime.ts L454-470 | `_aborted` 布尔仅循环边界检查 | **待改造** |
| `turn-queue` 用户输入排队 | pending-prompt-service.ts | 无 | **缺失** |
| `agent-event-bridge` 事件桥接 | agent-event-bridge.ts | SSE 直接 emit | 简化版 |

### 模块 B：流式工具调用组装

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 主 key = `toolCallId ?? tool_${index}` | agent-runtime.ts L965-1000 | runtime.py L617-628 | 已对齐 |
| Qwen `tool_call_id` 不稳定修复 | N/A | qwen.py 按 index 维护 map | 已对齐 |
| `invalidToolCalls` 写入 metadata | agent-runtime.ts L1031-1058 | 已实现 | 已对齐 |
| 流式 `input_text` 增量 JSON parse | stream 过程中持续尝试 | 需确认是否增量 parse | 待验证 |

### 模块 C：工具系统

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 工具基类 | `createTool()` 工厂 + `AgentTool` 接口 | `BaseTool` + `AgentTool` Protocol | 等价 |
| Schema 运行时校验 | `zodToJsonSchema` + `validateWithZod` | 手写 JSON Schema 无校验 | **弱** |
| `lifecycle.completesRun` | 内建 | `ToolLifecycle.completes_run` | 已对齐 |
| per-tool `timeoutMs`/`retryable`/`maxRetries` | 内建 | 仅全局 `default_tool_timeout_ms` | **弱** |
| `withTimeout` 包裹 | 内建 | 无 | **缺失** |
| `tool-approval` + `toolPolicies` | tool-approval.ts | `approval.py` + `before_approval` hook | 形式不同但等价 |
| `subprocess-sandbox` | subprocess-sandbox.ts | 无 | **缺失** |
| `model-tool-routing` 按模型路由工具集 | model-tool-routing.ts | 无 | **缺失** |

### 模块 D：技能系统

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 工具名 `skills` | definitions.ts L719 | skill_tool.py | 已对齐 |
| XML 返回格式 | user-instruction-plugin.ts L202 | 完全相同 | 已对齐 |
| 不创建子 agent（主上下文注入） | 是 | 是 | 已对齐 |
| description 动态含技能列表 | `Object.defineProperty` | `_build_description()` | 已对齐 |
| `runningSkills` 并发去重 | Set<string> | 无 | **缺失** |
| `withTimeout` 15s | `skillsTimeoutMs` | 无 | **缺失** |
| `allowedSkillNames` 白名单 | 是 | 无 | **缺失** |
| zod `SkillsInputSchema` | 是 | 手写 | 弱 |
| 遗留 `sub_agent.py`/`sub_agent_worker.py`/`server.py::_handle_sub_agent_event` | N/A | ~2000 行死代码 | **待清理** |

### 模块 E：上下文管理与压缩

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 触发比例 0.9 / maxInput 128000 | compaction.ts | context.py Phase 16 | 已对齐 |
| `preserve_recent_tokens` 20000 | 是 | 是 | 已对齐 |
| `_find_cut_index` 安全切割 | compaction-shared.ts | 是 | 已对齐 |
| `_summarize_tool_activity` | 是 | 是 | 已对齐 |
| `PRESERVED_ASSISTANT_TEXT_COUNT` | 是 | 是 | 已对齐 |
| agentic + basic fallback | 是 | 是 | 已对齐 |
| state-aware 持久化 | 是 | `CompactionStateManager` | 已对齐 |
| `budget-projection` 提前压缩 | budget-projection/ | 无 | **缺失** |
| `FileContextTracker` 持久化文件状态 | FileContextTracker.ts | 仅压缩时临时扫描 | **缺失** |
| `compact-session` CLI 调试工具 | compact-session.ts | 无 | **缺失** |

### 模块 F：系统提示构造

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 分层组装 | runtime-builder.ts | SystemPromptBuilder 11 层 | 已对齐 |
| `<env>` 段 | 是 | Phase 16 | 已对齐 |
| 工具列表段 | 是 | Phase 16 | 已对齐 |
| `<user_input mode>` 标签 | 是 | Phase 16 | 已对齐 |
| MCP 服务器概览 | 是 | Phase 22 | 已对齐 |
| `cline-rules` 段 + frontmatter + rule-conditionals | cline-rules.ts + frontmatter.ts + rule-conditionals.ts | 仅读单个 AGENTS.md | **弱** |
| `always`/`on-demand` 技能分层 | 是 | 是 | 已对齐 |
| `mode` 切换（plan/act） | session-runtime.ts | `plan_mode.py` + SessionState.mode | 已对齐 |

### 模块 G：Hooks 生命周期

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 9 个内建 Python hooks | agent.ts L265-364 | hooks.py | 已对齐 |
| `before_approval` hook | `toolPolicies` config | hook 形式 | 形式不同但等价 |
| 文件 hook（PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete/TaskResume/TaskCancel） | HookProcess.ts 跑外部脚本 | 无 | **缺失** |
| `hook-factory` + 模板 | hook-factory.ts + templates.ts | 无 | **缺失** |
| `HookError`/`HookProcessRegistry` | 是 | 无 | **缺失** |
| `shell-escape` | 是 | 无 | **缺失** |
| hook context-injection 语义 | 是 | 无 | **缺失** |

### 模块 H：循环检测与中止

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| `LoopDetectionTracker` 软/硬阈值 | loop-detection.ts | loop_detection.py Phase 26 | 已对齐 |
| `MistakeTracker` 同类错误分类 | mistake-tracker.ts | 无 | **缺失** |
| `AbortController.signal` 透传 | 是 | `_aborted` 布尔 | **待改造** |
| safety rules 引擎 | rules.ts | 无 | **缺失** |

### 模块 I：MCP 集成

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| MCP 客户端 + 工具注册 | extensions/mcp/ | agent/mcp/ Phase 22 | 已对齐 |
| OAuth 认证 | oauth.ts | 无 | **缺失**（量化场景用不到） |
| `policies.ts` 工具策略 | 是 | 无 | **缺失** |
| `plugin-server-registration` | 是 | 无 | **缺失** |
| `name-transform` 命名空间 | 是 | 无 | **缺失** |
| `config-loader` | `.cline/mcp_settings.json` | `agent_config/mcp_servers.yaml` | 格式不同 |

### 模块 J：会话持久化与 Checkpoint

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 会话存储 | SQLite + 磁盘 JSON | 纯 JSON 文件 | **弱** |
| `state-migrations` 版本迁移 | state-migrations.ts | 无 | **缺失** |
| Checkpoint（文件状态快照） | shadow-git 磁盘快照 | checkpoint.py 简化版（消息快照） | **弱** |
| `SqliteLockManager` 跨进程锁 | SqliteLockManager.ts | 无 | **缺失** |
| session-export | export.ts | 无 | **缺失** |

### 模块 K：子 agent / Sub-agent

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| `spawn_agent` 工具创建独立 runtime | spawn-agent-tool.ts | 无（Phase 27 已移除技能子 agent） | **缺失** |
| `subAgentTools` 配置 | 是 | `_DEFAULT_SUB_AGENT_TOOLS` 硬编码 | 弱 |
| `AgentConfigLoader` yaml 加载 | AgentConfigLoader.ts | 无 | **缺失** |
| `multi-agent` 协作 | multi-agent.ts | 无 | **缺失** |
| `projections` 事件投影 | 是 | 旧 `sub_agent_event` SSE 冒泡（待清理） | 形式不同 |
| 遗留 `sub_agent.py` ~1650 行 | N/A | 仍在仓库 | **待清理** |

### 模块 L：指令注入 / Cline Rules / AGENTS.md

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| AGENTS.md 加载 | 是 | 是 | 已对齐 |
| frontmatter 解析 | frontmatter.ts | 无 | **缺失** |
| `rule-conditionals` 按 mode 加载 | rule-conditionals.ts | 无 | **缺失** |
| `external-rules`（.cursorrules 等） | external-rules.ts | 无 | **缺失** |
| `workflows` 工作流文件 | workflows.ts | 无 | **缺失** |
| SKILL.md 加载 | 是 | 是 | 已对齐 |

### 模块 M：审批机制

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| `autoApprove` 全局开关 | 是 | Phase 19 | 已对齐 |
| `toolPolicies` per-tool 配置 | 是 | `tool_policies` dict | 已对齐 |
| `requestToolApproval` config | 是 | `before_approval` hook | 形式不同但等价 |
| UI 审批对话框 | VSCode 原生 | SSE + 前端弹窗 | 等价 |

### 模块 N：连接器 / Telemetry / Kanban

| 子项 | Cline | 当前实现 | 状态 |
|---|---|---|---|
| 连接器（Slack/TG/Discord/Linear/GChat/WhatsApp） | apps/cli/src/connectors/ | connectors.py 骨架 | **未落地** |
| `OpenTelemetryAdapter` | services/telemetry/ | telemetry.py 骨架 | **未落地** |
| `TelemetryLoggerSink` | 是 | 无 | **缺失** |
| Kanban 看板 | apps/cli/src/commands/kanban.ts | kanban.py 骨架 | **未落地** |
| `FeatureFlagsService` | FeatureFlagsService.ts | 无 | **缺失** |

---

## 三、整体差异总结

### 已对齐 Cline 的部分（约 70%）
- 类型系统、消息结构、AgentRuntime 主循环
- 流式工具调用组装（按 index）+ invalidToolCalls
- completion_policy、restore、abort 标志
- 技能系统主上下文指令注入（skills 工具 + XML 返回）
- 上下文压缩（agentic + basic + state-aware）
- 系统提示分层构造
- 9 个内建 hooks
- 循环检测（LoopDetectionTracker）
- 工具审批（autoApprove + toolPolicies）

### 关键缺失（按重要性排序）

| 优先级 | 缺失项 | 影响 |
|---|---|---|
| P0 | 文件 hook 系统（PreToolUse 等） | 用户无法不改源码扩展 agent |
| P0 | `MistakeTracker` 同类错误分类 | 错误循环检测粗糙，可能误杀 |
| P0 | `AbortController` 透传到 stream/工具 | 用户点"停止"无法立即中断 |
| P1 | zod schema 运行时校验 | 工具参数类型错只能靠 try/except |
| P1 | 工具 `timeoutMs`/`retryable`/`maxRetries` | 单工具无法定制超时/重试 |
| P1 | `FileContextTracker` 持久化文件状态 | 压缩摘要质量、UI 文件状态缺失 |
| P1 | `budget-projection` 提前压缩 | 压缩滞后，可能反复触发 |
| P1 | frontmatter + rule-conditionals | 无法按 mode 加载不同规则 |
| P2 | `spawn_agent` 子 agent 工具 | 无法做任务委派（量化场景价值中等） |
| P2 | `subprocess-sandbox` | run_commands 无沙箱保护 |
| P2 | SQLite 会话存储 + `SqliteLockManager` | 多进程并发不安全 |
| P2 | 遗留 sub_agent 代码 ~2000 行 | 维护负担 |
| P3 | `model-tool-routing` | 按模型路由工具集 |
| P3 | `turn-queue` 用户输入排队 | 运行中再次输入处理粗糙 |
| P3 | MCP OAuth/policies | 量化场景用不到 OAuth |
| P3 | connectors/telemetry/kanban 落地 | 骨架在但未集成 |

---

## 四、Phase 28：P0 关键缺失（必做）

### 28.1 `MistakeTracker` 同类错误分类

- **现状**：`agent/runtime.py::_check_repeated_tool_failures()` 只统计连续失败次数，不区分错误类型。
- **修改计划**：
  1. 新增 `agent/mistake_tracker.py`，实现 `MistakeTracker` 类
  2. 按 mistake_type 分类计数：`param_error`/`tool_not_found`/`permission_denied`/`exec_error`/`timeout`
  3. 每类独立软阈值（默认 3）/硬阈值（默认 5）
  4. 软阈值触发时向 LLM 注入结构化提示（含错误类型 + 已失败次数 + 建议）
  5. 硬阈值触发时 abort 并标记 `MistakeLimitExceeded`
  6. 注册为 `after_tool` hook
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts`
  - `third_party/cline/sdk/packages/core/src/runtime/safety/rules.ts`
- **验证方式**：
  - dummy model 连续 3 次传错参数给 `list_files`，确认软阈值提示被注入
  - 连续 5 次后确认 runtime abort，status=`failed`，last_error 含 `MistakeLimitExceeded`
- **依赖文件**：`agent/mistake_tracker.py`（新增）、`agent/runtime.py`、`agent/hooks.py`

### 28.2 `AbortController` 等价物

- **现状**：`agent/runtime.py::_aborted` 布尔标志，仅在循环顶端 `_throw_if_aborted()` 检查。模型 stream 中途用户点"停止"无法立即中断 HTTP 流；长 IO 工具（如 `run_commands` 跑回测）无法中途取消。
- **修改计划**：
  1. 新增 `agent/abort.py`，定义 `AbortController` 类（含 `signal: asyncio.Event` + `reason: str` + `abort()` 方法）
  2. `AgentRuntime` 持有 `AbortController` 实例，替换 `_aborted` 布尔
  3. `model.stream()` 内部循环每个 event 检查 `signal.is_set()`，命中则 raise `AbortedError`
  4. `BaseTool._execute()` 接收 `abort_signal` 参数（通过 `AgentToolContext` 透传）；长 IO 工具（`run_commands`/`read_files`/`web_search`）在关键 await 点检查
  5. `agent/server.py` 的 SSE "stop" 端点调用 `controller.abort()` 而非设 `_aborted=True`
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L454-470（abort 实现）
  - `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L588-593（throwIfAborted）
  - `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L796-809（stream 中检查）
- **验证方式**：
  - dummy model 模拟慢流（每 event sleep 100ms），运行中调用 `controller.abort()`，确认 200ms 内 raise `AbortedError` 而非等到 stream 结束
  - `run_commands` 跑 `time.sleep 10` 时 abort，确认 500ms 内终止子进程
- **依赖文件**：`agent/abort.py`（新增）、`agent/runtime.py`、`agent/types.py`（`AgentToolContext` 加字段）、`agent/providers/qwen.py`、`agent/tools/run_commands.py`、`agent/tools/read_files.py`、`agent/server.py`

### 28.3 文件 hook 系统 [已完成]

- **现状**：`agent/hooks.py` 只有 Python 内部 hook，用户无法在不改源码的情况下注入自定义逻辑。
- **修改计划**：
  1. 新增 `agent/file_hooks/` 模块（含 `__init__.py`/`loader.py`/`runner.py`/`types.py`）
  2. 扫描 `agent_config/hooks/{PreToolUse,PostToolUse,UserPromptSubmit,TaskStart,TaskComplete,TaskResume,TaskCancel}/` 下可执行脚本（.sh/.py/.js）
  3. 每个脚本带 frontmatter（`description`/`applyTo`/`blocking`）
  4. 用 subprocess 跑脚本，stdin 传 JSON 上下文（tool_name/input/result/session_id 等），stdout 解析返回值
  5. 返回值支持：`block`（中止运行）/`continue`（继续）/`context-injection`（注入文本到模型上下文）
  6. 集成到现有 hook 调用点：`_call_before_tool_hooks`/`_call_after_tool_hooks`/`_call_prepare_turn_input_hooks` 等
  7. 新增 `agent_config/hooks/README.md` 模板说明（参考 Cline `templates/`）
- **Cline 参考位置**：
  - `third_party/cline/apps/vscode/src/core/hooks/HookProcess.ts`（核心执行器）
  - `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts`（工厂）
  - `third_party/cline/apps/vscode/src/core/hooks/templates.ts`（模板）
  - `third_party/cline/apps/vscode/src/core/hooks/hooks-utils.ts`（工具函数）
  - `third_party/cline/apps/vscode/src/core/hooks/shell-escape.ts`（shell 转义）
  - `third_party/cline/apps/vscode/src/core/hooks/HookError.ts`/`HookProcessRegistry.ts`
  - 测试夹具：`third_party/cline/apps/vscode/src/core/hooks/__tests__/fixtures/hooks/`
- **验证方式**：
  - 在 `agent_config/hooks/PreToolUse/` 放一个 `block-rm.sh`，确认 `run_commands` 调用 `rm -rf` 时被 block
  - 放一个 `inject-context.py`，确认其 stdout 文本被注入到下一轮 LLM 上下文
  - hook 脚本超时（默认 30s）时返回 `error` 不挂死主流程
- **依赖文件**：`agent/file_hooks/`（新增整目录）、`agent/hooks.py`、`agent/runtime.py`、`agent_config/hooks/`（新增示例目录）

**[2026-07-25 完成实现]**：
- 新增文件：
  - `agent/file_hooks/types.py`：`FileHookType`/`FileHookConfig`/`FileHookContext`/`FileHookResult` 数据结构
  - `agent/file_hooks/loader.py`：扫描 `agent_config/hooks/{hook_type}/` 目录并解析 frontmatter
  - `agent/file_hooks/runner.py`：subprocess 执行脚本，stdin 传 JSON 上下文，按退出码解析结果（0=continue / 1=block / 其他=error），支持超时和 `PYTHONIOENCODING=utf-8` 防 Windows 编码乱码
  - `agent/file_hooks/integration.py`：桥接层，`build_file_hooks_agent_hooks()` 把文件 hook 包装为 Python 内建 hook（before_tool/after_tool/prepare_turn_input/before_run/after_run）
- 修改文件：
  - `agent/types.py`：`AgentRuntimeConfig` 新增 `enable_file_hooks: bool` 和 `file_hooks_dir: str | None` 字段
  - `agent/runtime.py`：`AgentRuntime.__init__` 中根据配置调用 `_load_file_hooks()` 注册文件 hook 到 Python hook 点
- 新增示例：
  - `agent_config/hooks/PreToolUse/block-dangerous-commands.py`：拦截 `rm -rf /` 等危险命令
  - `agent_config/hooks/PostToolUse/log-tool-result.py`：工具调用日志写入 `.tool_audit.log`
- hook 类型到 Python hook 点映射：
  - PreToolUse → before_tool（block 时 skip=True）
  - PostToolUse → after_tool（block 时 stop=True）
  - UserPromptSubmit → prepare_turn_input（block 时 stop=True，continue+injection 时附加到输入）
  - TaskStart → before_run（block 时 stop=True）
  - TaskComplete → after_run（block 仅记录日志，不影响已完成任务）
- 验证结果：
  - 加载 2 个示例 hook，安全命令 action=continue，危险命令 action=block 且 reason 中文正常
  - 启用文件 hook 后 `before_tool` 数量=2（循环检测 + PreToolUse），`after_tool` 数量=1（PostToolUse）
  - 未启用文件 hook 时 runtime 仍正常初始化（向后兼容）
  - 现有 e2e 测试通过（qwen-plus，1 次迭代，status=completed）

---

## 五、Phase 29：P1 工具系统强化

### 29.1 zod-style 运行时 schema 校验

- **现状**：`agent/tools/base.py` 手写 JSON Schema 只供 LLM 参考，运行时不校验。LLM 传错类型时只能靠工具内部 try/except 兜底，错误信息不友好。
- **修改计划**：
  1. 引入 `jsonschema` 库（轻量，无 pydantic 依赖）
  2. `BaseTool` 新增 `_validate_input(input)` 方法，用 `jsonschema.validate(input, self.input_schema)`
  3. 校验失败返回结构化错误：`AgentToolResult(output={"error": "schema validation failed", "field": "<path>", "expected": "<type>", "got": "<value>"}, is_error=True)`
  4. 错误信息含字段路径（如 `commands[0].command`），便于 LLM 自我纠正
  5. 在 `BaseTool.execute()` 入口调用 `_validate_input`，子类无需重复
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts`（`validateWithZod` 调用点）
  - `third_party/cline/sdk/packages/core/src/extensions/tools/schemas.ts`（zod schema 定义）
- **验证方式**：
  - LLM 传 `list_files(path=123)` 时返回 `field=path, expected=string, got=123`
  - LLM 传 `run_commands(commands="not a list")` 时返回 `field=commands, expected=array`
- **依赖文件**：`agent/tools/base.py`、`requirements.txt`（加 `jsonschema>=4.0`）

### 29.2 per-tool timeout/retry

- **现状**：`agent/types.py::AgentRuntimeConfig` 只有全局 `default_tool_timeout_ms`，单个工具无法定制。
- **修改计划**：
  1. `AgentToolDefinition` 增加 `timeout_ms: int | None`/`retryable: bool`/`max_retries: int` 字段
  2. `BaseTool` 暴露这三个 property（默认 `None`/`False`/`0`）
  3. `AgentRuntime._execute_tool_calls()` 用 `asyncio.wait_for(tool.execute(...), timeout=timeout_ms)` 包裹
  4. 超时 raise `asyncio.TimeoutError`，返回 `AgentToolResult(output={"error": "tool timeout after Xms"}, is_error=True)`
  5. `retryable=True` 时按 `max_retries` 重试，每次重试间隔指数退避（200ms * 2^n）
  6. 现有工具按需配置：`run_commands` retryable=False timeout=300000；`web_search` retryable=True max_retries=2 timeout=30000
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts`（`createTool({timeoutMs, retryable, maxRetries})`）
  - `withTimeout` 实现见 definitions.ts L742-750（skills 工具用法）
- **验证方式**：
  - dummy tool sleep 5s + timeout=1s，确认 1s 后返回 timeout 错误
  - dummy tool 第 1 次失败第 2 次成功 + retryable=True max_retries=2，确认最终成功
- **依赖文件**：`agent/types.py`、`agent/tools/base.py`、`agent/runtime.py::_execute_tool_calls`

### 29.3 `FileContextTracker` 持久化文件状态 [已完成]

- **现状**：`agent/context.py::ContextCompactor._summarize_tool_activity()` 在压缩时临时扫消息列表，无持久化文件状态。
- **修改计划**：
  1. 新增 `agent/file_context_tracker.py`，实现 `FileContextTracker` 类
  2. 在 `read_files`/`editor`/`apply_patch`/`file_write` 工具执行后调用 `tracker.record(path, operation, timestamp)`
  3. 持久化到 `agent_data/file_context/<session_id>.json`，结构：`{"read": [...], "edited": [...], "created": [...], "deleted": [...]}`
  4. `ContextCompactor._summarize_tool_activity()` 复用 tracker 数据（而非扫消息）
  5. 前端可通过新 SSE 事件 `file_context_updated` 实时展示当前会话涉及的文件
  6. `agent/server.py` 新增 `/api/agent/file_context/<session_id>` 端点
- **Cline 参考位置**：
  - `third_party/cline/apps/vscode/src/core/context/context-tracking/FileContextTracker.ts`
  - `third_party/cline/apps/vscode/src/core/context/context-tracking/ContextTrackerTypes.ts`
- **验证方式**：
  - 跑一轮会话含 3 次 read_files + 1 次 editor，确认 JSON 文件含 3 个 read + 1 个 edited
  - 触发压缩后摘要的 Files 段从 tracker 读取
- **依赖文件**：`agent/file_context_tracker.py`（新增）、`agent/tools/read_files.py`/`editor.py`/`apply_patch.py`/`file_tools.py`、`agent/context.py`、`agent/server.py`

**[2026-07-25 完成实现]**：
- 新增文件：`agent/file_context_tracker.py`
  - `FileContextTracker` 类：按 session_id 隔离，`record(path, operation, tool_name, iteration)` 记录操作，`get_state()` 返回精简视图（read/edited/created/deleted），`get_entries()` 返回完整记录列表
  - 持久化到 `agent_data/file_context/<session_id>.json`，原子替换写入（tmp + replace），启动时自动加载
  - 全局 `_TrackerRegistry` 单例 + `get_tracker(session_id)` / `set_storage_dir(path)` / `clear_tracker_cache(session_id)` 便捷函数
  - 路径规范化：`expanduser + resolve(strict=False)` + 统一正斜杠
  - 同 path+operation 去重（保留首次时间戳）
- 修改文件：
  - `agent/runtime.py`：`__init__` 中根据 `config.session_id` 获取 tracker，注册 `_file_context_tracker_hook` 作为 after_tool hook
    - hook 内根据 `tool_name` 提取路径：read_files→files[].path、list_files→path、editor/file_write/apply_patch→path/file_path/target_file（apply_patch 还从 diff 头解析 +++/--- 路径）
    - 自动判断 created vs edited（根据 result.output 的 created/is_new 标志）
    - 每次工具调用后 `tracker.save()` 持久化
  - `agent/context.py`：
    - `compact()` 新增 `session_id` 参数
    - 新增 `_summarize_tool_activity_v2(messages, session_id)`：优先从 tracker 取文件列表（created 归入 editedFiles），无数据时回退到 `_summarize_tool_activity`（消息扫描）
    - `_llm_summarize` 新增 `session_id` 参数，用 `functools.partial` 在 `before_model` 中绑定
    - `before_model` 调用 `compact()` 时传入 `session_id`
  - `agent/server.py`：新增 GET/DELETE `/api/chat/sessions/{session_id}/file_context` 端点
- 验证结果：
  - tracker 基本 API（record/save/load/get_state/get_entries/get_files_all）单元测试通过
  - runtime 启用 session_id 时 tracker 自动初始化，无 session_id 时 tracker=None（向后兼容）
  - `_summarize_tool_activity_v2` 优先级测试通过（有 tracker 用 tracker，无则 fallback）
  - API 端点 GET 返回 state+entries+total，DELETE 清空内存和持久化文件
  - 现有 e2e 测试通过（qwen-plus，1 次迭代，status=completed）

### 29.4 `budget-projection` 提前压缩 [已完成]

- **现状**：`ContextCompactor.should_compact()` 只看当前消息 token 数，超过阈值才压缩。下一轮注入 tool_result 后可能立刻又超限，导致反复压缩。
- **修改计划**：
  1. `ContextCompactor` 新增 `_project_future_usage(messages, tools)` 方法
  2. 估算 = 当前消息 token + 工具描述 token + 预期下一轮 tool_result 平均 token（基于历史均值）
  3. 阈值改为 `trigger_ratio * 0.8`（即 0.72）触发"提前压缩"
  4. 提前压缩日志标记 `compaction_reason=budget_projection`
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/index.ts`
  - `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/project.ts`
  - `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/types.ts`
- **验证方式**：
  - 构造 messages token=90000 + tools token=15000 + 历史 tool_result 均值=20000，确认 trigger_tokens=115200*0.8=92160 时触发提前压缩
- **依赖文件**：`agent/context.py`

**[2026-07-25 完成实现]**：
- 修改文件：`agent/context.py`
  - 新增模块常量：`_DEFAULT_PROJECTION_RATIO=0.8`、`_DEFAULT_TOOL_RESULT_HISTORY_MAX=10`
  - `ContextCompactor.__init__` 新增 3 个参数：`enable_budget_projection=True`、`projection_ratio=0.8`、`tool_result_history_max=10`
  - 新增 `_projection_trigger_tokens`（= `trigger_tokens * projection_ratio`）和 `_last_compaction_reason` 实例字段
  - `should_compact()` 新增 `tools` 参数，支持两级触发策略：
    1. 常规触发：`current_tokens >= trigger_tokens` → reason=`threshold_exceeded`
    2. 提前触发：`projected_total >= projection_trigger_tokens` → reason=`budget_projection`
  - 新增 `_project_future_usage(messages, tools, current_tokens=None)` 方法：
    - 投影公式：`projected = current + tools_description_tokens + avg_tool_result_tokens`
    - tools_tokens：遍历 tools 估算 name + description + input_schema JSON 字符数
    - avg_tool_result：从最近 N 个 ToolResultPart 提取 output 估算 token 均值（N=tool_result_history_max）
    - 无历史样本时 avg=0（保守策略，避免误触发）
  - `before_model` 中调用 `should_compact(messages, tools=ctx.request.tools)`，日志带 `compaction_reason`
  - 顶部 import 补充 `AgentToolDefinition` 和 `ToolResultPart`
- 验证结果：
  - 6 个内联测试场景全部通过：常规触发、提前压缩触发、不触发、禁用 budget_projection、带 tool_result 的投影计算
  - 现有 e2e 测试通过（qwen-plus，1 次迭代，status=completed）

### 29.5 frontmatter + rule-conditionals [已完成]

- **现状**：`SystemPromptBuilder._load_agents_file()` 只读单个 AGENTS.md，无 frontmatter 解析、无按 mode 过滤。
- **修改计划**：
  1. 拆分 `agent_config/AGENTS.md` 为 `agent_config/rules/*.md`（每个规则一个文件）
  2. 每个规则文件支持 YAML frontmatter：`---\napplyTo: [plan, act]\nmode: [research, trade]\ndescription: ...\n---`
  3. 新增 `agent/rules_loader.py`：解析 frontmatter + 按 session mode 过滤
  4. `SystemPromptBuilder._load_rules()` 改为调用 `rules_loader.load_for_mode(session_id, mode)`
  5. 保留 `AGENTS.md` 作为兼容入口（无 frontmatter 时整体加载）
- **Cline 参考位置**：
  - `third_party/cline/apps/vscode/src/core/instructions/user-instructions/frontmatter.ts`
  - `third_party/cline/apps/vscode/src/core/instructions/user-instructions/rule-conditionals.ts`
  - `third_party/cline/apps/vscode/src/core/instructions/user-instructions/rule-helpers.ts`
  - `third_party/cline/apps/vscode/src/core/instructions/user-instructions/cline-rules.ts`
- **验证方式**：
  - 创建 `rules/trading.md` frontmatter `mode: [trade]`，确认 plan 模式不加载、trade 模式加载
  - AGENTS.md 仍能整体加载（向后兼容）
- **依赖文件**：`agent/rules_loader.py`（新增）、`agent/context.py`、`agent_config/rules/`（新增目录）、`agent_config/AGENTS.md`（保留）

**[2026-07-25 完成实现]**：
- 新增文件：`agent/rules_loader.py`
  - `parse_yaml_frontmatter(markdown)` — 对标 Cline frontmatter.ts，fail-open 策略（YAML 解析失败时保留原文）
  - `evaluate_rule_conditionals(frontmatter, context)` — 对标 Cline evaluateRuleConditionals，支持 4 类条件：
    - `enabled`: bool，false 时跳过规则
    - `applyTo: [act/plan]`: agent 模式过滤（agent_mode=None 时 fail-closed）
    - `mode: [research/trade]`: 业务模式过滤（business_modes 空时 fail-closed）
    - `paths: [glob patterns]`: 工作空间路径 glob 匹配（无候选路径 fail-closed）
  - 内置轻量 glob 匹配（支持 `*`/`**`/`?`，无 picomatch 依赖）
  - `load_rules_directory(rules_dir, context, toggles)` — 递归扫描 .md 文件，对每个文件解析 frontmatter + 评估条件，返回 `RuleLoadResult` 列表
  - `format_rules_content(results)` — 拼接 activated=True 的规则正文为 system prompt 文本
  - `load_for_session(rules_dir, session_id, business_modes, paths, toggles)` — 便捷入口，自动从 session_id 查询 agent_mode（session_id=None 时默认 'act'）
- 修改文件：
  - `agent/context.py`：
    - `SystemPromptBuilder.__init__` 新增 3 个参数：`business_modes`/`rule_paths`/`rule_toggles`
    - `_load_rules(task_type)` 重构为两层加载策略：
      1. 兼容层：读 `rules_dir/<task_type>.md` 单文件（无 frontmatter 时整体加载）
      2. rules_loader 层：扫描整个 `rules_dir`，按 frontmatter 条件过滤
      3. 通过 toggles 跳过兼容层已加载的文件，避免重复
  - `agent/server.py::_build_system_prompt`：注入 `rules_dir=agent_config/rules/`
- 新增示例规则文件（`agent_config/rules/`）：
  - `general.md`：无 frontmatter，所有模式/业务场景下加载（向后兼容示例）
  - `research.md`：`applyTo: [act, plan]` + `mode: [research]`，仅研究业务模式加载
  - `trading.md`：`applyTo: [act, plan]` + `mode: [trade]`，仅交易业务模式加载
  - `plan-mode-rules.md`：`applyTo: [plan]`，仅 Plan 模式下加载
- 验证结果：
  - 11 个内联测试场景全部通过：frontmatter 解析、fail-open、applyTo/mode/paths/enabled 条件评估、真实 rules 目录加载、toggles 禁用、SystemPromptBuilder 集成（plan+research / act+trade 模式切换）
  - 现有 e2e 测试通过（qwen-plus，1 次迭代，status=completed）

---

## 六、Phase 30：清理与架构调整

### 30.1 删除遗留 sub-agent 代码

- **现状**：Phase 27 已将技能执行改为 Cline 原生指令注入，但遗留代码仍在：
  - `agent/skills/sub_agent.py`（~1650 行）
  - `agent/skills/sub_agent_worker.py`
  - `agent/server.py` L623-753 `_handle_sub_agent_event` 及 `sub_agent_event` 事件分支
- **修改计划**：
  1. 全局搜索 `SubAgentFactory`/`SubAgentProcessRuntime`/`sub_agent_event`/`_handle_sub_agent_event`/`use_skill`（旧工具名）确认无引用
  2. 删除 `agent/skills/sub_agent.py`、`agent/skills/sub_agent_worker.py`
  3. 删除 `agent/server.py` 中 `_handle_sub_agent_event` 函数 + `sub_agent_event` 事件分支 + 相关 SSE 包装
  4. 清理 `agent/skills/__pycache__/` 中的 `sub_agent*.cpython-*.pyc`
  5. 更新 `agent/skills/__init__.py` 移除 sub_agent 导出
- **Cline 参考位置**：N/A（这是清理你自己的遗留代码）
- **验证方式**：
  - `python tests/test_agent_e2e.py` 通过
  - `python tests/test_skill_e2e.py` 通过（验证 skills 工具仍工作）
  - `grep -r "SubAgentFactory\|sub_agent_event" agent/` 无结果
- **依赖文件**：`agent/skills/sub_agent.py`（删除）、`agent/skills/sub_agent_worker.py`（删除）、`agent/server.py`、`agent/skills/__init__.py`

### 30.2 拆分 `agent/runtime.py` 为 stateless + stateful

- **现状**：`agent/runtime.py` 一个 `AgentRuntime` 类混合了无状态 loop（`_generate_assistant_message`/`_execute_tool_calls`/`_call_before_model_hooks`）和有状态编排（`run`/`snapshot`/`restore`/hooks 注册/工具注册）。这与 Cline `@cline/agents`（stateless）+ `@cline/core`（stateful）的分层不一致。
- **修改计划**：
  1. 抽出 `agent/agent_loop.py`，实现 `run_agent_loop(model, request, tools, hooks, abort_controller) -> AsyncIterator[AgentEvent]`
  2. 该函数无状态：接收所有依赖，返回事件流，不持有 messages/iteration/usage
  3. `agent/runtime.py::AgentRuntime` 保留为 stateful 编排：持有 messages/state/hooks/tools，调用 `run_agent_loop` 并消费事件流更新状态
  4. hooks 注册/工具注册/snapshot/restore 留在 `AgentRuntime`
  5. 单元测试可直接调用 `run_agent_loop` 验证 loop 逻辑，无需构造完整 `AgentRuntime`
- **Cline 参考位置**：
  - stateless：`third_party/cline/sdk/packages/agents/src/agent-runtime.ts`（整个 `@cline/agents` 包）
  - stateful：`third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`
  - `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime.ts`
- **验证方式**：
  - `python tests/test_agent_e2e.py` 通过（验证行为不变）
  - 新增 `tests/test_agent_loop.py` 直接调用 `run_agent_loop` 验证 loop 逻辑
- **依赖文件**：`agent/agent_loop.py`（新增）、`agent/runtime.py`、`tests/test_agent_e2e.py`

### 30.3 简化原 PLAN 文件

- **现状**：`AGENT_MIGRATION_PLAN.md` 已 2900+ 行 12 章，Phase 1-27 大部分已完成。新内容已写入本文件（`AGENT_PHASE28_PLAN.md`）。
- **修改计划**：
  1. 原 `AGENT_MIGRATION_PLAN.md` 顶部追加 `> 历史归档` 标注，指向 `AGENT_PHASE28_PLAN.md`
  2. 不删除原文（保留为"为什么这么改"的回溯依据）
  3. 后续所有新计划只追加到 `AGENT_PHASE28_PLAN.md`
- **依赖文件**：`AGENT_MIGRATION_PLAN.md`、`AGENT_PHASE28_PLAN.md`

---

## 七、Phase 31：P2 量化场景定制

### 31.1 `spawn_agent` 等价物（任务委派）

- **场景**：让子 agent 跑长时间研报生成、回测验证，主 agent 继续响应用户。当前 Phase 27 移除了技能子 agent，但完全无子 agent 也丢失了任务委派能力。
- **修改计划**：
  1. 新增 `agent/spawn_agent_tool.py`，工具名 `spawn_agent`
  2. 输入：`task`（必填）/`agent_role`（可选，如 "researcher"/"backtester"）/`tools`（可选，工具名列表）
  3. 创建独立 `AgentRuntime`，注入子 agent system prompt（含主 agent 上下文摘要）
  4. 默认工具集：`read_files`/`run_commands`/`web_search`/`skills`/`attempt_completion`（不含 `spawn_agent` 防递归）
  5. 子 agent 事件投影到主 SSE 流（前缀 `sub_agent:`）
  6. 子 agent 调用 `attempt_completion` 后返回结果作为 `spawn_agent` 的 tool_result
  7. 子 agent 默认 max_iterations=20（独立计数）
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts`
  - `third_party/cline/sdk/packages/core/src/extensions/tools/team/delegated-agent.ts`
  - `third_party/cline/sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts`
  - `third_party/cline/sdk/packages/core/src/extensions/tools/team/configured-agent-tool.ts`
  - `third_party/cline/sdk/packages/core/src/extensions/tools/team/AgentConfigLoader.ts`（apps/vscode 下）
- **验证方式**：
  - 主 agent 调用 `spawn_agent(task="分析贵州茅台2025年年报")`，确认子 agent 跑完研报后结果回流
  - 子 agent 调用 `spawn_agent` 应被拒绝（防递归）
- **依赖文件**：`agent/spawn_agent_tool.py`（新增）、`agent/server.py`、`agent/runtime.py`

### 31.2 `subprocess-sandbox`

- **现状**：`agent/tools/run_commands.py` 直接 subprocess，无 cwd/env/资源限制。
- **修改计划**：
  1. `run_commands` 工具增加 `cwd`/`env`/`timeout`/`stdin` 参数
  2. Windows 用 Job Object 限制子进程 CPU/内存；Linux 用 `preexec_fn` 设 `resource.setrlimit`
  3. 维护危险命令黑名单：`rm -rf /`/`format`/`del /f /s /q C:\`/`mkfs` 等
  4. 黑名单命中时返回 `AgentToolResult(output={"error": "command blocked by sandbox", "pattern": "<matched>"}, is_error=True)`
  5. 默认 cwd=session 工作目录，env 继承但屏蔽 `DASHSCOPE_API_KEY` 等敏感变量
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts`
- **验证方式**：
  - `run_commands(commands=["rm -rf /"])` 被黑名单 block
  - `run_commands(commands=["sleep 100"], timeout=5)` 5s 后被 kill
  - 子进程 env 不含 `DASHSCOPE_API_KEY`
- **依赖文件**：`agent/tools/run_commands.py`、`agent/sandbox.py`（新增）

### 31.3 SQLite 会话存储 + 锁

- **现状**：`agent/session.py` 用纯 JSON 文件存会话，scheduler 进程和 web 进程同时操作时可能竞争。
- **修改计划**：
  1. 新增 `agent/storage/sqlite_session_store.py`，用 `sqlite3` 标准库
  2. schema：`sessions(id, created_at, updated_at, data_json)` + 索引 `idx_created_at`
  3. `SqliteLockManager` 用 `BEGIN EXCLUSIVE` 实现跨进程锁
  4. `agent/session.py::SessionStore` 改为委托 SQLite 实现（保留 JSON 作为导出格式）
  5. 数据库文件 `agent_data/sessions.db`
  6. 自动迁移：检测到旧 `.json` 文件时一次性导入
- **Cline 参考位置**：
  - `third_party/cline/sdk/packages/core/src/services/storage/sqlite-session-store.ts`
  - `third_party/cline/apps/vscode/src/core/locks/SqliteLockManager.ts`
  - `third_party/cline/sdk/packages/core/src/services/storage/session-store.ts`（接口）
- **验证方式**：
  - scheduler 和 web 同时启动，确认无 "database is locked" 错误
  - 旧 JSON 会话自动迁移到 SQLite
  - 查询最近 10 个会话 < 50ms
- **依赖文件**：`agent/storage/sqlite_session_store.py`（新增）、`agent/session.py`、`agent/storage/__init__.py`（新增）

---

## 八、Phase 32：P3 锦上添花（按需）

### 32.1 `model-tool-routing`（按模型路由工具集）

- **场景**：某些模型不支持并行 tool_call（如部分开源模型），需禁用并行提示；某些模型不支持 `reasoning_content`，需禁用 ReasoningPart 展示。
- **修改计划**：`AgentRuntimeConfig` 增加 `model_tool_routing: dict[str, list[str]]`（key=模型名，value=启用工具名列表）；`get_tools()` 按当前模型过滤。
- **Cline 参考**：`third_party/cline/sdk/packages/core/src/extensions/tools/model-tool-routing.ts`

### 32.2 `turn-queue`（用户输入排队）

- **场景**：agent 运行中用户再次输入，Cline 排队等当前轮结束后处理；当前实现是丢弃或阻塞。
- **修改计划**：新增 `agent/turn_queue.py`；`AgentRuntime` 持有 `asyncio.Queue`；当前轮结束前自动处理队列中的下一输入。
- **Cline 参考**：`third_party/cline/sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts`

### 32.3 MCP `policies`（per-tool auto-approve）

- **修改计划**：`agent/mcp/registry.py` 增加 `policies.yaml` 配置；按 server_name + tool_name 配置 auto-approve。
- **Cline 参考**：`third_party/cline/sdk/packages/core/src/extensions/mcp/policies.ts`

### 32.4 `compact-session` CLI 调试工具

- **修改计划**：新增 `scripts/compact_session.py`，离线压缩指定会话历史文件，便于调试 ContextCompactor。
- **Cline 参考**：`third_party/cline/sdk/packages/core/src/extensions/context/compact-session-script.test.ts`

### 32.5 `FeatureFlagsService`（远程功能开关）

- **修改计划**：新增 `agent/feature_flags.py`；从 `agent_config/feature_flags.yaml` 加载；支持运行时热更新。
- **Cline 参考**：`third_party/cline/sdk/packages/core/src/services/feature-flags/FeatureFlagsService.ts`

### 32.6 connectors 落地（飞书/钉钉研报推送）

- **场景**：研报生成完成后自动推送到飞书/钉钉群。
- **修改计划**：`agent/connectors.py` 实现飞书/钉钉适配器；`after_run` hook 触发推送。
- **Cline 参考**：`third_party/cline/apps/cli/src/connectors/adapters/`

### 32.7 telemetry 落地（token 消耗追踪）

- **修改计划**：`agent/telemetry.py` 实现 `TelemetryLoggerSink`；记录每次 LLM 调用的 token 数/耗时/模型名；导出到 `agent_data/telemetry/<date>.jsonl`。
- **Cline 参考**：`third_party/cline/sdk/packages/core/src/services/telemetry/TelemetryLoggerSink.ts` + `TelemetryService.ts`

---

## 九、Phase 28-32 依赖关系

```
Phase 28（P0 必做）
  ├── 28.1 MistakeTracker        ── 独立，无依赖
  ├── 28.2 AbortController        ── 独立，无依赖
  └── 28.3 文件 hook 系统         ── 独立，无依赖

Phase 29（P1 工具系统强化）
  ├── 29.1 zod schema 校验       ── 独立
  ├── 29.2 per-tool timeout/retry ── 依赖 29.1（schema 校验失败不应重试）
  ├── 29.3 FileContextTracker    ── 独立
  ├── 29.4 budget-projection     ── 依赖 29.3（用 tracker 数据估算）
  └── 29.5 frontmatter rules     ── 独立

Phase 30（清理与架构调整）
  ├── 30.1 删除遗留 sub-agent    ── 独立（建议先做，减少噪音）
  ├── 30.2 拆分 runtime.py       ── 建议在 28/29 完成后做（避免冲突）
  └── 30.3 简化原 PLAN           ── 独立

Phase 31（P2 量化场景定制）
  ├── 31.1 spawn_agent           ── 建议在 30.2 后做（依赖 loop 拆分）
  ├── 31.2 subprocess-sandbox    ── 独立
  └── 31.3 SQLite 会话存储       ── 独立

Phase 32（P3 按需）
  └── 各子项独立，按业务需要选做
```

---

## 十、推荐实施顺序

1. **Phase 30.1 删除遗留 sub-agent 代码**（先清理噪音，~30 分钟）
2. **Phase 28.1 MistakeTracker**（独立且影响主流程稳定性）
3. **Phase 28.2 AbortController**（用户高频痛点）
4. **Phase 29.1 zod schema 校验**（基础设施）
5. **Phase 29.2 per-tool timeout/retry**（依赖 29.1）
6. **Phase 28.3 文件 hook 系统**（扩展性关键，工作量较大）
7. **Phase 29.3 FileContextTracker**（为 29.4 铺路）
8. **Phase 29.4 budget-projection**（依赖 29.3）
9. **Phase 29.5 frontmatter rules**（独立，可并行）
10. **Phase 30.3 简化原 PLAN**（持续维护）
11. **Phase 30.2 拆分 runtime.py**（28/29 完成后）
12. **Phase 31 各项**（按业务节奏）
13. **Phase 32 各项**（按需）

---

## 十一、参考索引：Cline SDK 关键文件路径

> 所有路径相对 `e:/jikeAI/code/CASE-AI量化系统/third_party/cline/`

### shared 包
- `sdk/packages/shared/src/agent.ts` — Agent 协议、hooks 接口、AgentRuntimeConfig

### agents 包（stateless loop）
- `sdk/packages/agents/src/agent-runtime.ts` — 主循环、流式组装、tool 执行
- `sdk/packages/agents/src/index.ts` — 包出口

### core 包（stateful 编排）
- `sdk/packages/core/src/ClineCore.ts` — Cline 核心类
- `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` — 会话编排
- `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` — 系统提示构造
- `sdk/packages/core/src/runtime/safety/loop-detection.ts` — 循环检测
- `sdk/packages/core/src/runtime/safety/mistake-tracker.ts` — 错误追踪
- `sdk/packages/core/src/runtime/safety/rules.ts` — 安全规则
- `sdk/packages/core/src/runtime/tools/tool-approval.ts` — 工具审批
- `sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts` — 子进程沙箱
- `sdk/packages/core/src/runtime/host/local/agent-event-bridge.ts` — 事件桥接
- `sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` — 输入排队
- `sdk/packages/core/src/extensions/tools/definitions.ts` — 默认工具定义（含 createSkillsTool）
- `sdk/packages/core/src/extensions/tools/schemas.ts` — zod schema
- `sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts` — 子 agent 工具
- `sdk/packages/core/src/extensions/tools/team/delegated-agent.ts` — 委派 agent
- `sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts` — 子 agent prompt
- `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` — 技能/规则加载
- `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` — 配置加载器
- `sdk/packages/core/src/extensions/context/compaction.ts` — 上下文压缩入口
- `sdk/packages/core/src/extensions/context/agentic-compaction.ts` — LLM 摘要
- `sdk/packages/core/src/extensions/context/basic-compaction.ts` — 基础摘要
- `sdk/packages/core/src/extensions/context/compaction-shared.ts` — 共享工具
- `sdk/packages/core/src/extensions/context/budget-projection/` — 预算投影
- `sdk/packages/core/src/extensions/mcp/` — MCP 集成
- `sdk/packages/core/src/hooks/` — hook 内部实现
- `sdk/packages/core/src/services/storage/sqlite-session-store.ts` — SQLite 会话存储
- `sdk/packages/core/src/services/telemetry/` — 遥测
- `sdk/packages/core/src/services/feature-flags/` — 功能开关

### apps/vscode（VSCode 扩展，文件 hook 等宿主逻辑）
- `apps/vscode/src/core/hooks/HookProcess.ts` — 文件 hook 执行器
- `apps/vscode/src/core/hooks/hook-factory.ts` — hook 工厂
- `apps/vscode/src/core/hooks/templates.ts` — hook 模板
- `apps/vscode/src/core/hooks/shell-escape.ts` — shell 转义
- `apps/vscode/src/core/instructions/user-instructions/frontmatter.ts` — frontmatter 解析
- `apps/vscode/src/core/instructions/user-instructions/rule-conditionals.ts` — 条件规则
- `apps/vscode/src/core/instructions/user-instructions/cline-rules.ts` — cline rules 加载
- `apps/vscode/src/core/context/context-tracking/FileContextTracker.ts` — 文件追踪
- `apps/vscode/src/core/locks/SqliteLockManager.ts` — SQLite 锁
- `apps/vscode/src/core/storage/state-migrations.ts` — 状态迁移

### apps/cli（CLI 版本，连接器等）
- `apps/cli/src/connectors/adapters/` — Slack/TG/Discord/Linear/GChat/WhatsApp 适配器
- `apps/cli/src/session/export.ts` — 会话导出
