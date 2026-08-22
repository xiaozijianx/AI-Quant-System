# Stage 8: P3 长期评估项方案

> 生成时间：2026-07-26
> 优先级：P3（按需评估后实施）
> 预估工作量：按需（多数为"不实施"或"部分实施"）
> 依赖：stage_1-7 中相关基础设施已落地
>
> 来源：
> - `CLINE_DIFF/phase_V_subagent.md`（V1-V10 Sub-agent）
> - `CLINE_DIFF/phase_Y_plugin_marketplace.md`（Y1-Y7 Plugin/Marketplace）
> - `CLINE_DIFF/phase_Z_telemetry_hub.md`（Z2/Z9/Z10/Z11 OpenTelemetry/Hub/Cron）
> - `CLINE_DIFF/phase_F_tools_infra.md`（F11/F12 subprocess-sandbox/tool presets）
> - `CLINE_DIFF/phase_L_system_prompt.md`（L9/L10 external-rules/workflows）
> - `CLINE_DIFF/phase_I_skills.md`（I17/I18/I19 多技能目录/热重载/marketplace）
>
> 涉及源文件：
> - 我的：`agent/runtime.py`、`agent/skills/skill_tool.py`、`agent/telemetry.py`、`agent/tools/routing.py`、`agent/rules_loader.py`、`scheduler.py`
> - Cline：`third_party/cline/sdk/packages/core/src/extensions/tools/team/`、`third_party/cline/sdk/packages/core/src/extensions/plugin/`、`third_party/cline/sdk/packages/core/src/hub/`、`third_party/cline/sdk/packages/core/src/cron/`、`third_party/cline/sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts`、`third_party/cline/sdk/packages/core/src/extensions/tools/presets.ts`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 决策建议 | 涉及文件 |
|--------|------|------|----------|----------|
| 8.1 | Sub-agent 评估与决策 | V1-V10 | 不实施 | agent/runtime.py、agent/skills/skill_tool.py |
| 8.2 | Plugin/Marketplace 不实施说明 | Y1-Y7 | 不实施 | 无（无对应实现） |
| 8.3 | Hub 远程运行时不实施说明 | Z9/Z10 | 不实施 | 无（无对应实现） |
| 8.4 | subprocess-sandbox 评估 | F11 | 不实施 | agent/runtime.py、agent/tools/base.py |
| 8.5 | tool presets 评估 | F12 | 部分实施（仅文档化） | agent/tools/routing.py、agent/tools/constants.py |
| 8.6 | OpenTelemetry OTLP 评估 | Z2 | 部分实施（生产部署后） | agent/telemetry.py |
| 8.7 | Cron 调度实现评估 | Z11 | 部分实施（基于已有 scheduler.py 增强） | scheduler.py、agent/telemetry.py |
| 8.8 | workflows/external-rules 评估 | L9/L10 | 不实施 | agent/rules_loader.py、agent/context.py |

阶段定位：本阶段为 P3 长期评估项，绝大多数子项为"主动选择不实施"或"按需实施"，不强求与 Cline 对齐。每个小阶段需结合量化场景实际需求评估，给出明确的实施/不实施/部分实施决策。

依赖关系：
- 各小阶段相互独立，可并行评估
- 8.7（Cron）与 8.6（OpenTelemetry）若实施，需先评估对 stage_5（安全稳定性）和 stage_4（上下文）的影响
- 8.5（tool presets）若实施，需在 stage_3（工具技能）完成后

---

## 8.1 Sub-agent 评估与决策（V1-V10）

### 任务背景

来源 Phase V #V1-V10。Cline 通过 `spawn_agent` / `configured-agent-tool` / `multi-agent` 三层体系提供完整的子 agent / 多 Agent 协作能力，包括：spawn_agent 工具、delegated-agent 工厂、subagent-prompts 构造、configured-agent-tool（预配置 agent）、AgentTeam + AgentTeamsRuntime（多 agent 协作）、projections（事件投影）、AgentConfigLoader（yaml 配置加载）、子 agent 工具集限制、独立 max_iterations、事件冒泡。

我的实现在 Phase 27 主动移除了技能子 agent，仅保留 `parent_agent_id` 字段、`EventEmitter.subscribe` 基础设施、`AgentRuntimeConfig.max_iterations` 三个底层字段为未来接入预留。`agent/skills/skill_tool.py` 明确注释"不创建子 agent，而是在主 agent 上下文中返回 skill 指令文本"，这是有意的设计选择。

### 目标

**决策：不实施。**

保留现状，不实现 spawn_agent 工具链。`parent_agent_id` / `EventEmitter` / `max_iterations` 三个底层字段继续保留为未来接入预留，但不主动实施 V1-V10 中任何子项。理由见评估维度。

### 当前实现位置

- `agent/runtime.py:181` — `_RuntimeState.parent_agent_id` 字段保留
- `agent/runtime.py:203` — `AgentRuntimeConfig.max_iterations=50`（默认 50）
- `agent/runtime.py:215-217` — `AgentRuntime.__init__` 中 `EventEmitter()` 实例化
- `agent/runtime.py:313-315` — `subscribe(listener)` 方法（事件冒泡基础设施）
- `agent/runtime.py:517-518` — `max_iterations` 检查逻辑
- `agent/types.py:319` — `AgentRuntimeConfig.parent_agent_id` 字段
- `agent/types.py:390` — `AgentToolContext.parent_agent_id` 字段
- `agent/telemetry.py:540` — 上报 `parent_agent_id` 字段
- `agent/skills/skill_tool.py:7` — 注释明确"不创建子 agent"
- `agent/skills/skill_tool.py:110` — "不创建子 agent，直接返回 skill 指令字符串"

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts:117-202` — `createSpawnAgentTool`，输入 schema 仅 2 字段（systemPrompt + task），`timeoutMs: 300000`（5 分钟），`retryable: false`
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/team/delegated-agent.ts:137-146` — `createDelegatedAgent` 工厂，返回独立 `SessionRuntime`，通过 `subscribeEvents(onEvent)` 转发事件
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts:23-41` — `buildSubAgentSystemPrompt`，区分 subagent（overridePrompt 完全替换）和 teammate（rules 拼接）
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/team/configured-agent-tool.ts:152-253` — `createConfiguredAgentTools`，从 yaml 加载预定义 agent 注册为工具
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/team/multi-agent.ts:176-466` — `AgentTeam` + `AgentTeamsRuntime`，1852 行，含任务依赖/邮箱/运行队列/心跳/重试/故障恢复/Outcome
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/team/projections.ts:45-283` — `buildTeamProgressSummary` + `toTeamProgressLifecycleEvent`
- Cline `third_party/cline/apps/vscode/src/core/task/tools/subagent/AgentConfigLoader.ts:157-354` — 单例 yaml 加载，chokidar 热重载

### 评估维度

- **量化场景需求度**：低。量化任务以"数据 → 因子 → 回测 → 报告"流水线为主，单 agent + SkillsTool 已能覆盖。多 agent 协作的复杂度（任务依赖、邮箱、运行队列、故障恢复）与量化场景的简单流水线不匹配。
- **实现成本**：高。完整实现 V1-V10 需新增约 2000+ 行 Python 代码（spawn_agent 工具 + delegated 工厂 + prompts 构造 + multi-agent 协作 + projections + config loader）。其中 V5（multi-agent.ts 1852 行）的 Python 等价实现成本极高。
- **替代方案**：
  1. **SkillsTool（已实现）**：专业化指令注入，覆盖 80% 的"专家 agent"需求，无子 agent 上下文切换开销
  2. **asyncio.gather（语言原生）**：并行多任务（如同时分析 10 只股票），无需多 agent 协作原语
  3. **Plan Mode + 多轮对话（已实现）**：分治复杂任务，单 agent 上下文连续
- **触发实施的条件**：
  1. 出现"需要并行分析 50+ 只股票"且 asyncio.gather 性能不足
  2. 出现"需要 lead agent 调度多个长时运行 teammate"的协作场景
  3. 出现"需要 yaml 配置专家 agent 工具"且 SkillsTool 无法满足
  4. 出现"单次 prompt 过长需通过分治降低"且 context compaction 无法满足

### 修复步骤建议（如决定实施）

若未来触发条件出现，按以下优先级分阶段实施：

**阶段一（最小可用 spawn_agent）**：
1. 新增 `agent/delegated.py`，实现 `create_delegated_agent(kind, prompt, tools, parent_agent_id, max_iterations, on_event)` 工厂函数（对标 V2）
2. 新增 `agent/tools/spawn_agent.py`，实现 `SpawnAgentTool`，输入 schema `{system_prompt: str, task: str}`，`timeout_ms=300000`，`retryable=False`（对标 V1）
3. 在 `createSubAgentTools` 工厂中显式过滤 `spawn_agent` 自身防止递归（对标 V8）
4. 在 `onSubAgentStart` / `onSubAgentEnd` 回调中包装子 agent 事件，SSE 层增加 `parent_agent_id` 字段标识冒泡来源（对标 V10）

**阶段二（yaml 配置 agent）**：
5. 新增 `AgentConfigLoader`，加载 `agent_config/agents/` 下 yaml frontmatter（name/description/systemPrompt/tools/maxIterations），与现有 `SkillLoader` 共享 frontmatter 解析逻辑（对标 V7 + V4）

**跳过项**：
- V3（subagent-prompts）：无 IDE 集成，`overridePrompt` 等价于直接传 prompt
- V5/V6（multi-agent + projections）：量化场景过度设计

### 验证方法

**不实施时的验证**：
1. 运行 `python tests/test_agent_e2e.py`，确认无 spawn_agent 工具注册
2. `grep -r "spawn_agent\|create_delegated_agent" agent/`，确认无子 agent 实现
3. 确认 `parent_agent_id` 字段在 runtime/types/telemetry 三处保留

**如实施后的验证**：
1. 新增 `tests/test_spawn_agent.py`，构造 spawn_agent 工具调用，验证子 agent 独立 max_iterations 计数
2. 验证子 agent 事件冒泡到父 agent 的 SSE 流，含 `parent_agent_id` 字段
3. 验证 spawn_agent 工具集不包含 spawn_agent 自身（防递归）

### 注意事项

- 不能死板照搬 CLINE_DIFF 计划，需结合实际业务判断：量化场景下子 agent 属于过度设计，不应主动实施
- 保留原函数逻辑：`parent_agent_id` / `EventEmitter` / `max_iterations` 三个底层字段继续保留，不删除
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：如实施 spawn_agent，工具执行失败直接抛错，不降级为主 agent 执行
- Phase 27 主动移除技能子 agent 是有意的设计选择，不应回退

---

## 8.2 Plugin/Marketplace 不实施说明（Y1-Y7）

### 任务背景

来源 Phase Y #Y1-Y7。Cline 通过 `extensions/plugin/` 目录（7 个文件，约 2449 行 TypeScript）提供完整的第三方插件扩展能力，包括：plugin-config-loader（路径解析 + package.json 声明识别）、plugin-loader（jiti 动态加载 + manifest 校验）、plugin-sandbox（Node 子进程隔离 + RPC）、plugin-targeting（provider/model 过滤）、marketplace 安装/卸载/列表（远程 catalog.json）。

我的实现完全无插件系统，无 marketplace。扩展能力通过 `agent/skills/`（本地 SKILL.md）、`agent/mcp/`（MCP server 配置）、`agent/tools/`（工具基类）、`agent/providers/`（多 provider 工厂）已覆盖。

### 目标

**决策：不实施。**

不在量化场景引入 plugin/marketplace 系统。扩展能力继续通过已有的 skills / mcp / tools / providers 体系提供。理由见评估维度。

### 当前实现位置

- 无 plugin 相关实现
- 替代实现：
  - `agent/skills/loader.py` — 本地 SKILL.md 加载（Phase I 对比）
  - `agent/mcp/registry.py` — MCP server 注册（Phase Q 对比）
  - `agent/tools/base.py` — 工具基类（Phase F 对比）
  - `agent/providers/factory.py` — 多 provider 工厂（Phase R 对比）
  - `agent_config/mcp_servers.yaml` — MCP server 配置
  - `agent_config/strategies.yaml` — 策略注册表
  - `lib/strategy_registry.py` — 策略注册机制

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-config-loader.ts` — 路径解析三层来源 + package.json 声明识别 + skill 目录收集 + `resolveAndLoadAgentPlugins` 统一入口
- Cline `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-loader.ts` — `loadAgentPluginFromPath` + `validatePluginExport` + `validatePluginManifest`
- Cline `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-module-import.ts` — jiti 加载器（682 行），含静态分析 import/require、依赖预检、workspace alias、Bun 兼容
- Cline `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-sandbox.ts` — `loadSandboxedPlugins` + `SubprocessSandbox` RPC + 超时配置 + 并发 reinit 保护（648 行）
- Cline `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-targeting.ts:1-32` — `matchesPluginManifestTargeting`，空数组=匹配所有、保守不匹配策略
- Cline `apps/vscode/src/core/controller/marketplace/` — install/uninstall/getCatalog/listInstalled/listLocal/toggle 共 7 个 RPC 入口

### 评估维度

- **量化场景需求度**：无。Cline plugin/marketplace 面向"开发者社区贡献扩展"场景（GitHub 公开 catalog、第三方工具/规则/插件分发），目标用户是泛开发任务人群。本系统是单一团队的 A 股量化交易研究/执行平台，扩展以内部代码迭代为主，不存在社区分发需求。
- **实现成本**：极高。Cline 该模块合计约 2449 行 TypeScript，核心难点（jiti 动态加载、SubprocessSandbox RPC、bootstrap 文件解析、workspace alias 解析）在 Python 下无 1:1 等价物。最小可用实现至少需要：路径发现（~200 行）+ importlib 加载 + manifest 校验（~300 行）+ 简化 sandbox（multiprocessing + pickle RPC，~400 行）+ 远程 catalog（~150 行），合计 1000+ 行 Python，且持续维护成本高。
- **替代方案**：
  1. **agent/skills/（已实现）**：本地 SKILL.md 加载，覆盖"专业化指令注入"需求
  2. **agent/mcp/（已实现）**：MCP server 配置，覆盖"第三方数据源 connector"需求
  3. **agent_config/strategies.yaml + lib/strategy_registry.py（已实现）**：策略注册表，覆盖"策略扩展"需求
  4. **agent/providers/（已实现）**：多 provider 工厂，覆盖"LLM provider 切换"需求
- **触发实施的条件**：
  1. 非核心团队（如策略研究员）需上传策略包而不污染主仓库
  2. 多用户共享部署需按用户启用扩展
  3. 形成内部"策略插件市场"需求
  4. 接入第三方行情/资讯 API 需隔离（且 MCP 不满足）

### 修复步骤建议（如决定实施）

**阶段一（最小路径发现 + manifest 校验）**：
1. 新增 `agent/plugins/loader.py`，实现 `discover_plugin_paths(workspace_path)` 扫描 `agent_config/plugins/` 目录
2. 新增 `agent/plugins/manifest.py`，实现 `validate_plugin_manifest(plugin)` 校验 `name` / `capabilities` / `providerIds` / `modelIds` 字段
3. 用 `importlib.util.module_from_spec` 加载 Python 模块，跳过 jiti 等价物
4. 跳过 sandbox（用 venv 隔离替代）

**阶段二（targeting）**：
5. 实现 `matches_plugin_manifest_targeting(manifest, targeting)`，对标 `plugin-targeting.ts:8-32`

**跳过项**：
- plugin-sandbox：Python 子进程沙箱性能/稳定性远不如 Node，用 venv 隔离替代
- marketplace：远程 catalog 引入供应链风险，量化场景禁用

### 验证方法

**不实施时的验证**：
1. `grep -r "plugin\|marketplace" agent/`，确认仅注释引用 Cline 文件名，无实际实现
2. 确认 `agent/skills/`、`agent/mcp/`、`agent/providers/` 已覆盖扩展需求
3. 运行 `python tests/test_agent_e2e.py`，确认无 plugin 加载逻辑

**如实施后的验证**：
1. 新增 `tests/test_plugin_loader.py`，构造测试插件，验证 manifest 校验 + 加载
2. 验证 targeting 过滤按 provider/model 正确激活/禁用插件

### 注意事项

- 不能死板照搬计划：量化交易系统对"第三方可执行代码"天然敏感，plugin sandbox 即便实现也应以"内部 git 仓库 + code review + venv 隔离"替代公网市场
- 保留原函数逻辑：本任务无原函数需保留，但需确保已有的 skills/mcp/providers 不受影响
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：如实施 plugin 加载，单个插件失败应收集到 failures 列表而非降级
- 安全考量：远程市场拉取引入供应链风险（npm 包劫持、catalog 篡改），沙箱逃逸在金融场景下的损失不可逆

---

## 8.3 Hub 远程运行时不实施说明（Z9/Z10）

### 任务背景

来源 Phase Z #Z9/Z10。Cline 通过 `hub/` 目录提供 Hub 远程运行时能力，包括：Hub client（`NodeHubClient` WebSocket 客户端，含自动重连、指数退避、本地 Hub 故障恢复）、Hub server（WebSocket 服务器 + 多种传输 + Handler 分发 + 会话事件投影）、Hub daemon（`spawnDetachedHubServer` detached 子进程 + ETXTBSY 重试 + 兼容性检测 + 预热）。

用途：多客户端共享一个 agent 运行时（如 VS Code + CLI + 移动端同时连接），detached daemon 支持 agent 运行时独立于客户端进程存活。

我的实现完全无 Hub，agent 运行时在 Web 服务器进程内（`agent/server.py`），单用户 Web 应用形态。

### 目标

**决策：不实施。**

不在量化场景引入 Hub 远程运行时。agent 运行时继续在 Web 服务器进程内运行，单用户 Web 应用形态满足量化研究/交易需求。理由见评估维度。

### 当前实现位置

- 无 Hub 相关实现
- `agent/server.py` — agent 运行时内嵌于 FastAPI Web 服务器
- `agent/runtime.py:196` — `AgentRuntime` 类，每个会话独立实例

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/hub/client/index.ts:292-794` — `NodeHubClient` 类，`connect()` 超时 8s，`command()` 等待 reply，`subscribe()` 按 session 过滤，指数退避（250ms ~ 5000ms）+ 50% 抖动
- Cline `third_party/cline/sdk/packages/core/src/hub/daemon/index.ts:217-489` — `spawnDetachedHubServer` + `spawnDetachedHubServerWithRetry`（ETXTBSY 重试 100/250/500/1000/2000ms）+ `ensureDetachedHubServer`（discovery 记录 + 兼容性检测 + 8s 超时）+ `prewarmDetachedHubServer` + `retireLegacySharedHub`
- Cline `third_party/cline/sdk/packages/core/src/hub/server/` — WebSocket 服务器 + 多传输 + Handler 分发（session/approval/run/capability/client/connector）+ 会话事件投影 + Hub 通知 + 调度事件

### 评估维度

- **量化场景需求度**：无。本系统为单用户 Web 应用（`app.py` + FastAPI），用户通过浏览器交互，不需要多客户端共享运行时。量化研究/交易流程为单人操作，无 detached daemon 需求。
- **实现成本**：高。完整实现 Hub client + server + daemon 需新增约 3000+ 行 Python 代码（WebSocket 客户端 + 服务器 + Handler 分发 + detached 进程管理 + 兼容性检测）。其中 daemon 的 Windows 兼容性（detached 子进程 + windowsHide）在 Python 下实现复杂。
- **替代方案**：
  1. **FastAPI WebSocket（已实现）**：`agent/server.py` 已通过 FastAPI 提供 SSE 流，无需独立 Hub
  2. **多会话管理（已实现）**：`agent/session.py` 支持多会话，每个会话独立 `AgentRuntime` 实例
  3. **定时调度（已实现）**：`scheduler.py` 用 APScheduler 实现 detached 调度，覆盖"独立于 Web 服务器运行"需求
- **触发实施的条件**：
  1. 需要多客户端同时连接同一 agent 运行时（如 Web + 移动端 + CLI）
  2. 需要 agent 运行时独立于 Web 服务器进程存活（如 Web 重启不影响长时任务）
  3. 需要远程访问 agent（跨机器）

### 修复步骤建议（如决定实施）

**阶段一（简化 Hub server）**：
1. 新增 `agent/hub/server.py`，基于 FastAPI WebSocket 实现 Hub server（复用现有 FastAPI 基础设施）
2. 实现 session-handlers / run-handlers / approval-handlers 分发
3. 实现 session-event-projector 将 AgentRuntime 事件投影为 Hub 事件

**阶段二（Hub client）**：
4. 新增 `agent/hub/client.py`，基于 `websockets` 库实现客户端
5. 实现自动重连（指数退避 + 抖动）
6. 实现 `command()` 等待 reply 模式

**跳过项**：
- Hub daemon：Windows 下 detached 子进程管理复杂，且 `scheduler.py` 已覆盖"独立于 Web 服务器运行"需求

### 验证方法

**不实施时的验证**：
1. `grep -r "hub\|HubClient\|HubServer" agent/`，确认无 Hub 实现
2. 确认 `agent/server.py` 的 FastAPI SSE 流满足单用户交互需求
3. 确认 `scheduler.py` 的 detached 调度满足"独立运行"需求

**如实施后的验证**：
1. 新增 `tests/test_hub_server.py`，构造多客户端连接，验证事件广播
2. 验证 Hub client 断线重连
3. 验证 session 事件投影正确

### 注意事项

- 不能死板照搬计划：Cline Hub 设计面向"多客户端 + 多 IDE"场景，量化场景为单用户 Web 应用，Hub 属于过度设计
- 保留原函数逻辑：本任务无原函数需保留，但需确保 `agent/server.py` 的 FastAPI SSE 流不受影响
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：如实施 Hub，连接失败应直接报错，不降级为单机模式
- Windows 兼容性：detached 子进程在 Windows 下需 `subprocess.CREATE_NEW_PROCESS_GROUP` + `DETACHED_PROCESS` 标志，实现复杂

---

## 8.4 subprocess-sandbox 评估（F11）

### 任务背景

来源 Phase F #F11。Cline 通过 `subprocess-sandbox.ts` 用 Node.js 子进程隔离执行工具，主要用于插件安全隔离（`plugin-sandbox.ts` 通过 `SubprocessSandbox` 加载第三方插件）。子进程通过 stdin/stdout JSON-RPC 协议通信，支持 `call`（请求-响应）/ `event`（事件推送）两种消息类型，含超时配置（`importTimeoutMs` / `hookTimeoutMs` / `contributionTimeoutMs`）。

我的实现工具直接在主进程 asyncio 事件循环中执行（`agent/runtime.py`），无进程隔离。

### 目标

**决策：不实施。**

不在量化场景引入 subprocess-sandbox。工具继续在主进程执行，通过 `requires_approval` / `read_only` 字段控制工具行为。理由见评估维度。

### 当前实现位置

- `agent/runtime.py:1505` — `asyncio.wait_for` 工具超时包裹（对标 F7 withTimeout）
- `agent/tools/base.py:71` — `lifecycle.completesRun` 字段（对标 F3）
- `agent/tools/base.py:76` — `timeout_ms` per-tool 字段（对标 F5）
- `agent/tools/base.py:81-88` — `retryable` + `max_retries` 字段（对标 F6）
- `agent/tools/base.py:91` — `read_only` 字段（额外增强，标记无副作用工具）
- `agent/tools/base.py:96` — `requires_approval` 字段（额外增强，标记需审批工具）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts:1-100` — `SubprocessSandbox` 类，`bootstrapFile` / `bootstrapScript` 双模式，`call(method, args, {timeoutMs})` RPC，`PendingRequest` 含 `timeout` 句柄
- Cline `third_party/cline/sdk/packages/core/src/runtime/tools/subprocess-sandbox.ts:73-100` — `resolveSubprocessRuntimeExecutable`，解析 `CLINE_JS_RUNTIME_PATH_ENV` / `BUN_EXEC_PATH` / `NODE` 环境变量
- Cline `third_party/cline/sdk/packages/core/src/extensions/plugin/plugin-sandbox.ts` — `loadSandboxedPlugins` 通过 `SubprocessSandbox` 加载插件，含并发 reinit 保护

### 评估维度

- **量化场景需求度**：低。subprocess-sandbox 主要服务于插件隔离场景（Phase Y 已决策不实施）。量化场景下工具均为内部代码（read_files / exec_tool / web_tool 等），无第三方代码执行需求。
- **实现成本**：高。Python 等价实现需 `multiprocessing.Process` + pickle RPC，但：
  1. Python 多进程开销大（启动慢、内存占用高）
  2. asyncio 与 multiprocessing 集成复杂（需 `asyncio.get_child_watcher()` 或 `asyncio.to_thread`）
  3. 工具执行结果需跨进程序列化，部分对象（如文件句柄、数据库连接）无法序列化
- **替代方案**：
  1. **requires_approval 字段（已实现）**：敏感工具（如 exec_tool）需用户审批，覆盖安全控制需求
  2. **read_only 字段（已实现）**：无副作用工具可并行执行，覆盖并发控制需求
  3. **timeout_ms per-tool（已实现）**：工具超时控制，覆盖资源占用需求
  4. **venv 隔离**：如需隔离第三方代码，用 venv 替代子进程沙箱
- **触发实施的条件**：
  1. 需要执行不可信第三方代码（如插件系统实施后）
  2. 工具执行可能崩溃主进程（如调用不稳定 native 库）
  3. 需要工具级资源限制（CPU/内存配额）

### 修复步骤建议（如决定实施）

**阶段一（最小 sandbox）**：
1. 新增 `agent/tools/sandbox.py`，实现 `SubprocessSandbox` 类，基于 `multiprocessing.Process` + `multiprocessing.Queue` 实现 RPC
2. 实现 `call(method, args, timeout_ms)` 接口，超时后终止子进程
3. 实现 `event` 消息推送（子进程 → 主进程）

**阶段二（工具集成）**：
4. 在 `BaseTool` 增加 `sandbox: bool` 字段，标记是否需沙箱执行
5. `AgentRuntime._execute_tool` 检查 `sandbox` 字段，若为 True 则通过 `SubprocessSandbox.call` 执行

**跳过项**：
- `resolveSubprocessRuntimeExecutable`：Python 无需解析 Node/Bun 运行时

### 验证方法

**不实施时的验证**：
1. `grep -r "SubprocessSandbox\|subprocess_sandbox" agent/`，确认无 sandbox 实现
2. 确认 `requires_approval` / `read_only` / `timeout_ms` 字段已覆盖安全/并发/超时控制
3. 运行 `python tests/test_agent_e2e.py`，确认工具在主进程执行

**如实施后的验证**：
1. 新增 `tests/test_subprocess_sandbox.py`，构造崩溃工具，验证子进程崩溃不影响主进程
2. 验证 sandbox 工具超时后子进程被终止
3. 验证 sandbox 工具结果正确序列化回主进程

### 注意事项

- 不能死板照搬计划：subprocess-sandbox 主要服务于插件隔离，Phase Y 已决策不实施插件，故 sandbox 无独立价值
- 保留原函数逻辑：`requires_approval` / `read_only` / `timeout_ms` 字段继续保留，不删除
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：如实施 sandbox，子进程启动失败应直接报错，不降级为主进程执行
- Python 多进程在 Windows 下需 `if __name__ == "__main__":` 保护，集成复杂

---

## 8.5 tool presets 评估（F12）

### 任务背景

来源 Phase F #F12。Cline 通过 `presets.ts` 定义工具集预设，包括 `act` / `plan` / `search` / `minimal` / `yolo` 五种预设，每种预设是一组 `enableXxx` 布尔开关。`resolveToolPresetName(mode)` 按 mode 返回预设名，`createDefaultToolsWithPreset(presetName, options)` 按预设创建工具集。`createToolPoliciesWithPreset("yolo")` 生成 yolo 模式的自动审批策略。

我的实现通过 `model-tool-routing` + `SessionState.mode` 动态过滤工具（Phase 32.1），无预设概念。mode 为 `act` / `plan` 两种，通过 `agent/tools/routing.py` 的规则匹配启用/禁用工具。

### 目标

**决策：部分实施（仅文档化，不引入预设机制）。**

保留现有 mode-based 路由机制，不引入 Cline 的 preset 概念。但在 `agent/tools/constants.py` 中文档化各 mode 的工具集预期，便于排查。理由见评估维度。

### 当前实现位置

- `agent/tools/routing.py:35-62` — `ToolRoutingRule` dataclass，含 `mode` / `model_id_includes` / `model_id_excludes` / `tool_enabled` 字段
- `agent/tools/routing.py:62` — 示例规则 `mode="act"`，按 model_id 子串匹配启用/禁用工具
- `agent/tools/constants.py` — 工具常量（部分统一，对标 F14 output-limits）
- `agent/tools/plan_mode.py` — PLAN_MODE_PROMPT 内容（对标 L13）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/presets.ts:20-109` — `ToolPresets` 常量，5 种预设（act/plan/search/minimal/yolo），每种含 10 个 `enableXxx` 开关
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/presets.ts:116-126` — `resolveToolPresetName({mode})`，plan → "plan"，yolo → "yolo"，其余 → "act"
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/presets.ts:137-158` — `createToolPoliciesWithPreset("yolo")`，生成 `*` + 所有默认工具的 `autoApprove: true` 策略
- Cline `third_party/cline/sdk/packages/core/src/extensions/tools/presets.ts:175-190` — `createDefaultToolsWithPreset(presetName, options)`，按预设配置创建工具集

### 评估维度

- **量化场景需求度**：低。量化场景仅使用 `act` / `plan` 两种 mode，现有 mode-based 路由已覆盖工具过滤需求。Cline 的 `search` / `minimal` / `yolo` 预设在量化场景无对应需求：
  - `search`：代码探索预设，量化场景用 `search_codebase` 工具即可
  - `minimal`：最小工具集，量化场景需完整工具集
  - `yolo`：自动执行无审批，量化场景涉及实盘交易，禁用 yolo
- **实现成本**：低。若实施仅需在 `agent/tools/constants.py` 新增 `TOOL_PRESETS` 常量 + `resolve_tool_preset(mode)` 函数，约 50 行 Python。但需同步改造 `AgentRuntime` 工具注册逻辑，工作量中等。
- **替代方案**：
  1. **mode-based 路由（已实现）**：`agent/tools/routing.py` 按 mode + model_id 动态过滤工具，比静态预设更灵活
  2. **SessionState.mode（已实现）**：会话级 mode 切换，Plan Mode 下自动禁用写入工具
  3. **requires_approval 字段（已实现）**：敏感工具审批控制，比 yolo 自动审批更安全
- **触发实施的条件**：
  1. 需要快速切换"只读模式"/"完整模式"/"最小模式"且 mode-based 路由配置过于复杂
  2. 需要支持 yolo 模式（自动审批所有工具）且现有 approval_policy 无法满足
  3. 需要为新场景（如"回测模式"）定义专用工具集

### 修复步骤建议（如决定实施）

**阶段一（文档化预设）**：
1. 在 `agent/tools/constants.py` 新增 `TOOL_PRESETS` 字典，文档化各 mode 的工具集预期：
```python
# 工具预设 — 对标 Cline ToolPresets，但仅文档化，不引入预设机制
# 实际工具过滤由 agent/tools/routing.py 的 mode-based 路由实现
TOOL_PRESETS = {
    "act": {
        "read_files": True, "search_codebase": True, "exec_tool": True,
        "web_tool": True, "editor": True, "apply_patch": True,
        "skills": True, "ask_question": True, "todo_write": True,
    },
    "plan": {
        "read_files": True, "search_codebase": True, "exec_tool": True,
        "web_tool": True, "editor": False, "apply_patch": False,
        "skills": True, "ask_question": True, "todo_write": True,
    },
}
```

**阶段二（如需 yolo 模式）**：
2. 在 `agent/approval_policy.py` 新增 `yolo` 策略，自动审批所有 `requires_approval=True` 的工具
3. 在 `agent/tools/routing.py` 增加 `yolo` mode 规则

**跳过项**：
- `search` / `minimal` 预设：量化场景无需求
- `createDefaultToolsWithPreset`：现有 `AgentRuntime.register_tool` 已支持按需注册

### 验证方法

**部分实施时的验证**：
1. 确认 `agent/tools/constants.py` 中 `TOOL_PRESETS` 字典与实际 mode-based 路由行为一致
2. 运行 `python tests/test_agent_e2e.py`，确认 Plan Mode 下 editor/apply_patch 被禁用
3. `grep -r "TOOL_PRESETS" agent/`，确认仅文档化引用，未用于实际工具过滤

**如完整实施后的验证**：
1. 新增 `tests/test_tool_presets.py`，验证 `resolve_tool_preset("plan")` 返回 plan 预设
2. 验证 yolo 模式下所有工具自动审批

### 注意事项

- 不能死板照搬计划：Cline 预设是静态配置，我的 mode-based 路由是动态规则，更灵活，不应回退为静态预设
- 保留原函数逻辑：`agent/tools/routing.py` 的 `ToolRoutingRule` 继续使用，`TOOL_PRESETS` 仅作文档
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：如实施 yolo 模式，approval_policy 直接审批，不降级为询问用户
- yolo 模式涉及实盘交易安全，需在 `agent_config/execution_mode.yaml` 中显式启用，不默认开启

---

## 8.6 OpenTelemetry OTLP 评估（Z2）

### 任务背景

来源 Phase Z #Z2。Cline 通过 `OpenTelemetryAdapter.ts`（338 行）实现完整的 OpenTelemetry SDK 适配器，支持 `MeterProvider`（counter/histogram/gauge）、`LoggerProvider`（log record）、OTLP HTTP exporter（endpoint/headers/insecure 配置）、`flattenProperties`（递归展平嵌套属性，含循环引用检测、最大深度限制、数组截断）。配套 `OpenTelemetryProvider.ts`（579 行）创建 Provider 并管理生命周期，支持 `console` 和 `otlp` 两种 exporter，`OptedOutTelemetryService` 实现 opt-out no-op 服务。

我的实现 `agent/telemetry.py` 仅有 `LoggerSink` / `FileSink` / `MemorySink` 三个本地 sink，无 OTLP 远程上报，无 metric instrument。

### 目标

**决策：部分实施（生产部署后评估）。**

当前本地 sink（LoggerSink + FileSink + MemorySink）满足开发调试需求，暂不实施 OTLP 上报。待生产部署接入可观测性平台（如 Jaeger / Grafana / Datadog）时再实施 `OpenTelemetrySink`。当前阶段先在 `TelemetrySink` 基类增加 metric instrument 空方法（默认 no-op），为未来实施预留接口。理由见评估维度。

### 当前实现位置

- `agent/telemetry.py:132-151` — `TelemetrySink` 基类，仅 `write(event)` / `flush()` / `close()` 三个方法
- `agent/telemetry.py:154-173` — `LoggerSink`，仅实现 `write(event)`
- `agent/telemetry.py:176-253` — `FileSink`，JSONL 持久化
- `agent/telemetry.py:253-300` — `MemorySink`，内存缓存（额外增强，Cline 无此 API）
- `agent/telemetry.py:302-447` — `TelemetryService`，多 sink 派发 + 全局单例
- `agent/telemetry.py:633-646` — `_truncate_preview`，仅截断工具输入/输出预览
- `agent_data/telemetry/telemetry_20260724.jsonl` — FileSink 持久化文件

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryAdapter.ts:24-58` — `OpenTelemetryAdapter` 类，构造参数含 `meterProvider` / `loggerProvider` / `enabled` / `distinctId` / `commonProperties`
- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryAdapter.ts:60-80` — `emit` / `emitRequired` / `recordCounter` / `recordHistogram` / `recordGauge` 方法
- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryAdapter.ts:226-337` — `buildAttributes` + `flattenProperties`，递归展平嵌套属性，循环引用检测（`WeakSet` + `[Circular]`），最大深度 `maxDepth=10`，数组截断 `maxArraySize=100`
- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryProvider.ts:148-337` — `MeterProvider` / `LoggerProvider` / `TracerProvider` 创建，`console` 和 `otlp` 两种 exporter，`PeriodicExportingMetricReader` / `BatchLogRecordProcessor` / `BatchSpanProcessor` 配置

### 评估维度

- **量化场景需求度**：中。生产部署时接入可观测性平台有价值（如 token 用量监控、工具耗时分布、缓存命中率），但当前本地 sink 满足开发调试需求。量化场景处理金融数据，可观测性对故障排查有帮助。
- **实现成本**：中。Python 有 `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-exporter-otlp` 官方包，实现 `OpenTelemetrySink` 约 200 行 Python。但需同步实现 `flattenProperties` 等价物（循环引用检测 + 深度限制 + 数组截断），约 100 行。
- **替代方案**：
  1. **FileSink（已实现）**：JSONL 持久化，满足离线分析需求
  2. **MemorySink + query_events（已实现）**：API 查询最近事件，满足前端实时展示需求
  3. **LoggerSink（已实现）**：日志输出，满足开发调试需求
  4. **外部日志收集**：如需集中可观测性，可用 Filebeat + Logstash + Elasticsearch 收集 JSONL 文件
- **触发实施的条件**：
  1. 生产部署接入可观测性平台（Jaeger / Grafana / Datadog / Honeycomb）
  2. 需要 metric instrument（counter/histogram/gauge）监控 token 用量、工具耗时
  3. 需要分布式追踪（跨服务调用链路）
  4. 合规要求遥测数据集中存储

### 修复步骤建议（如决定实施）

**阶段一（metric instrument 接口预留，P3）**：
1. 在 `agent/telemetry.py:132-151` 的 `TelemetrySink` 基类增加 metric 空方法（默认 no-op）：
```python
class TelemetrySink:
    def write(self, event: TelemetryEvent) -> None:
        raise NotImplementedError
    def record_counter(self, name: str, value: int | float,
                       attributes: dict | None = None) -> None:
        """计数器 metric — 默认 no-op，由具体 sink 覆盖"""
        pass
    def record_histogram(self, name: str, value: int | float,
                         attributes: dict | None = None) -> None:
        """直方图 metric — 默认 no-op，由具体 sink 覆盖"""
        pass
    def record_gauge(self, name: str, value: int | float,
                     attributes: dict | None = None) -> None:
        """仪表盘 metric — 默认 no-op，由具体 sink 覆盖"""
        pass
    def flush(self) -> None: ...
    def close(self) -> None: ...
```
2. 在 `TelemetryService` 增加 `record_counter` / `record_histogram` / `record_gauge` 方法，遍历 sinks 调用

**阶段二（OpenTelemetrySink，生产部署后）**：
3. `pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp`
4. 新增 `agent/telemetry/otel_sink.py`，实现 `OpenTelemetrySink(TelemetrySink)`：
   - 构造参数：`endpoint` / `headers` / `insecure` / `service_name`
   - 创建 `MeterProvider` + `LoggerProvider` + `TracerProvider`
   - 实现 `write` / `record_counter` / `record_histogram` / `record_gauge` / `flush` / `close`
5. 实现 `_flatten_properties(value, max_depth=10, max_array_size=100)` 工具函数：
   - 循环引用检测：`seen: set[int]` + `id(obj)` 标记
   - 最大深度限制：`depth > max_depth` 返回 `"[MaxDepthExceeded]"`
   - 数组截断：`len > max_array_size` 截断并标记 `_truncated` / `_original_length`
   - `Date` → `isoformat()`，`Error` → `message`
6. 在 `agent/server.py` 启动时根据配置注册 `OpenTelemetrySink`

**跳过项**：
- `OptedOutTelemetryService`：opt-out 机制在 stage_5 的 Z13 隐私机制中实施
- `TracerProvider`：分布式追踪在量化场景暂无需求（单服务）

### 验证方法

**阶段一验证**：
1. 运行 `python tests/test_agent_e2e.py`，确认 `TelemetrySink.record_counter` 默认 no-op 不报错
2. 验证 `TelemetryService.record_counter` 遍历 sinks 调用，LoggerSink 输出日志

**阶段二验证（如实施）**：
1. 新增 `tests/test_otel_sink.py`，构造 `OpenTelemetrySink`，验证 counter/histogram/gauge 上报
2. 验证 `_flatten_properties` 处理循环引用、深度超限、数组截断
3. 启动本地 Jaeger（`docker run -p 16686:16686 jaegertracing/all-in-one`），验证遥测数据上报

### 注意事项

- 不能死板照搬计划：当前本地 sink 满足需求，不应主动引入 OTLP 依赖（`opentelemetry-*` 包体积大）
- 保留原函数逻辑：`LoggerSink` / `FileSink` / `MemorySink` 继续保留，`OpenTelemetrySink` 作为可选 sink 添加
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`OpenTelemetrySink` 初始化失败应直接报错，不降级为本地 sink
- 循环引用检测必须用 `id(obj)` 而非对象本身（Python 对象不可哈希）
- 生产部署前需评估 OTLP endpoint 的网络可达性（防火墙、代理）

---

## 8.7 Cron 调度实现评估（Z11）

### 任务背景

来源 Phase Z #Z11。Cline 通过 `cron/` 目录（含 service / runner / schedule / specs / store / events / reports 子模块）提供完整的 file-based cron 调度能力。`CronService` 顶层调度器组装 5 个组件：`SqliteCronStore`（SQLite 持久化）、`CronReconciler`（磁盘 → DB 同步）、`CronWatcher`（文件系统监听）、`CronMaterializer`（队列物化）、`CronRunner`（claim + execute + report）。支持 spec 文件、事件驱动触发、资源限流、运行报告。

我的实现已有 `scheduler.py`（独立进程），基于 `apscheduler.schedulers.blocking.BlockingScheduler` + `CronTrigger` 实现 A 股交易日定时任务：08:30 数据刷新、09:00 晨会简报、09:30 启动模拟盘、14:55 停止主循环。配置保存在 `data/scheduler_config.json`，每个任务可独立开关。`requirements.txt` 已包含 `apscheduler>=3.10.0`。

### 目标

**决策：部分实施（基于已有 scheduler.py 增强，不引入 Cline 完整架构）。**

保留现有 `scheduler.py` 的 APScheduler 实现作为核心调度器，不引入 Cline 的 `SqliteCronStore` / `CronReconciler` / `CronWatcher` / `CronMaterializer` / `CronRunner` 五组件架构。但补充以下增强：
1. 支持 file-based spec（yaml 配置文件，对标 Cline cron spec）
2. 支持 spec 文件热重载（对标 `CronWatcher`，但用 `watchdog` 库）
3. 支持运行记录持久化（对标 `SqliteCronStore`，但用 SQLite 轻量实现）
4. 支持事件驱动触发（对标 `CronEventIngress`）

理由见评估维度。

### 当前实现位置

- `e:\jikeAI\code\CASE-AI量化系统\scheduler.py:1-80` — `TradingScheduler`，独立进程，APScheduler + CronTrigger
- `e:\jikeAI\code\CASE-AI量化系统\scheduler.py:41-42` — `from apscheduler.schedulers.blocking import BlockingScheduler` + `from apscheduler.triggers.cron import CronTrigger`
- `e:\jikeAI\code\CASE-AI量化系统\scheduler.py:10-14` — 4 个 cron job（08:30 数据 / 09:00 晨会 / 09:30 启动 / 14:55 停止）
- `e:\jikeAI\code\CASE-AI量化系统\data\scheduler_config.json` — 任务开关配置
- `e:\jikeAI\code\CASE-AI量化系统\data\scheduler_heartbeat.json` — 心跳记录
- `e:\jikeAI\code\CASE-AI量化系统\lib\scheduler_config.py` — 配置加载/心跳/启停辅助
- `e:\jikeAI\code\CASE-AI量化系统\requirements.txt:28` — `apscheduler>=3.10.0`

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/cron/service/cron-service.ts:50-163` — `CronService` 类，组装 5 组件，`start()` / `stop()` / `dispose()` 生命周期，`listSpecs` / `listRuns` / `reconcileNow` / `ingestEvent` API
- Cline `third_party/cline/sdk/packages/core/src/cron/store/sqlite-cron-store.ts` — SQLite 持久化（cron.db），存储 spec / run / event log
- Cline `third_party/cline/sdk/packages/core/src/cron/specs/cron-reconciler.ts` — 磁盘 → DB 同步（cron spec 文件 → DB 记录）
- Cline `third_party/cline/sdk/packages/core/src/cron/specs/cron-watcher.ts` — 文件系统监听（debounce），spec 变更自动 reconcile
- Cline `third_party/cline/sdk/packages/core/src/cron/runner/cron-materializer.ts` — 队列物化（spec 按时间表生成 run 记录）
- Cline `third_party/cline/sdk/packages/core/src/cron/runner/cron-runner.ts` — claim + execute + report（租约 + 并发控制）
- Cline `third_party/cline/sdk/packages/core/src/cron/events/cron-event-ingress.ts` — 事件入口（外部事件触发 cron）

### 评估维度

- **量化场景需求度**：高。量化场景典型用途包括：
  1. 每日盘前数据预加载（08:30）— 已实现
  2. 定时生成研究报告（盘后 16:00）— 部分实现
  3. 周期性投资组合再平衡（每周一 09:00）— 未实现
  4. 盘后 P&L 汇总（每日 16:30）— 未实现
  5. 定时风控检查（盘中每小时）— 未实现
  6. 事件驱动触发（如市场异动触发风控）— 未实现
- **实现成本**：中。已有 `scheduler.py` + APScheduler 基础，补充 file-based spec + 热重载 + 运行记录 + 事件驱动约需 400-500 行 Python。若完整对齐 Cline 五组件架构则需 1500+ 行，ROI 低。
- **替代方案**：
  1. **scheduler.py + APScheduler（已实现）**：A 股交易日 4 个 cron job，满足核心定时需求
  2. **Windows Task Scheduler / Linux cron**：外部调度器调用 agent API，但配置分散不易管理
  3. **APScheduler jobstores**：APScheduler 内置 `SQLAlchemyJobStore`，可持久化 job 到 SQLite，无需自研 `SqliteCronStore`
- **触发实施的条件**：
  1. 需要新增定时任务且 `scheduler.py` 硬编码 job 难以维护
  2. 需要事件驱动触发任务（如市场异动）
  3. 需要任务运行历史记录与重试
  4. 需要多实例部署且任务需分布式锁

### 修复步骤建议（如决定实施）

**阶段一（file-based spec，P3）**：
1. 在 `agent_config/cron/` 目录下创建 yaml spec 文件，每个文件定义一个 cron job：
```yaml
# agent_config/cron/daily_data_refresh.yaml
name: daily_data_refresh
description: 每日盘前数据刷新
schedule: "30 8 * * 1-5"  # 周一到周五 08:30
timezone: "Asia/Shanghai"
command: "python run_daily.py"
enabled: true
```
2. 在 `scheduler.py` 新增 `load_cron_specs(specs_dir)` 函数，扫描 yaml 文件并注册到 `BlockingScheduler`
3. 保留现有 4 个硬编码 job 作为 fallback（若 yaml spec 缺失则用硬编码）

**阶段二（运行记录持久化）**：
4. 引入 APScheduler `SQLAlchemyJobStore`，持久化 job 到 `data/cron.db`
5. 新增 `lib/cron_store.py`，记录运行历史（run_id / spec_id / started_at / finished_at / status / error）
6. 新增 API `/api/cron/runs` 查询运行历史

**阶段三（spec 热重载）**：
7. `pip install watchdog`
8. 新增 `lib/cron_watcher.py`，监听 `agent_config/cron/` 目录变更，debounce 75ms 后重新加载 spec
9. 通过 `scheduler.reschedule_job(job_id, trigger=new_trigger)` 热更新 job

**跳过项**：
- `CronMaterializer`：APScheduler 内置 trigger 自动计算下次运行时间，无需物化队列
- `CronRunner` 的 claim + lease：单实例部署无需分布式锁
- `CronEventIngress`：事件驱动触发暂无需求，待 stage_5 的 Z13 实施后再评估

### 验证方法

**阶段一验证**：
1. 在 `agent_config/cron/` 创建测试 spec 文件，运行 `python scheduler.py`
2. 验证 spec 文件被正确加载并注册到 APScheduler
3. 修改 spec 的 `schedule` 字段，重启 `scheduler.py`，验证新 schedule 生效

**阶段二验证**：
1. 运行 `python scheduler.py`，手动触发 job（`python scheduler.py --job data`）
2. 查询 `data/cron.db`，验证运行记录持久化
3. 调用 `GET /api/cron/runs`，验证 API 返回运行历史

**阶段三验证**：
1. 运行 `python scheduler.py`
2. 修改 `agent_config/cron/daily_data_refresh.yaml` 的 `schedule` 字段
3. 等待 75ms debounce，验证日志输出 "cron spec reloaded"
4. 查询 APScheduler job，验证 schedule 已更新（无需重启）

### 注意事项

- 不能死板照搬计划：已有 `scheduler.py` + APScheduler 满足核心需求，不应重写为 Cline 五组件架构
- 保留原函数逻辑：`scheduler.py` 的 4 个硬编码 job 继续保留，作为 yaml spec 缺失时的 fallback（注：此处 fallback 是指配置缺失时用硬编码，不是代码降级逻辑）
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：spec 解析失败应记录日志并跳过该 job，不降级为硬编码
- A 股交易日历：cron schedule 需结合 `lib/stock_utils.py` 的交易日判断，非交易日不执行
- Windows 兼容性：`watchdog` 在 Windows 下需 `ReadDirectoryChangesW`，已内置支持
- 时区：所有 schedule 必须显式指定 `timezone: "Asia/Shanghai"`，避免跨时区部署问题

---

## 8.8 workflows/external-rules 评估（L9/L10）

### 任务背景

来源 Phase L #L9/L10。Cline 通过 `external-rules.ts` 支持外部规则文件（`.windsurfrules` / `.cursorrules` / `.cursor/rules/*.mdc` / `AGENTS.md`），通过 `synchronizeRuleToggles()` 同步启用/禁用开关，状态持久化到 VS Code workspace state。通过 `workflows.ts` + `user-instruction-config-loader.ts:577-599` 支持 workflows 目录（`.clinerules/workflows/` + `.cline/workflows/` + 全局 `Documents/Workflows`），workflow 文件解析同 rules（frontmatter + body），通过 `registerCommand` 注册为 slash command（如 `/my-workflow`）。

我的实现仅支持 `AGENTS.md`（通过 `agents_path` 参数单文件加载），无 `.windsurfrules` / `.cursorrules` 支持，无 workflows 概念。slash command 通过前端路由实现，不通过 system prompt 注入。

### 目标

**决策：不实施。**

不在量化场景引入 external-rules 和 workflows。规则继续通过 `agent_config/rules/` 目录的 frontmatter md 文件管理，slash command 继续通过前端路由实现。理由见评估维度。

### 当前实现位置

- `agent/rules_loader.py:62-100` — `FrontmatterParseResult` / `RuleLoadResult` / `RuleEvaluationContext` dataclass
- `agent/rules_loader.py:119-177` — `parse_yaml_frontmatter` 函数（对标 L7，与 Cline 字节级一致）
- `agent/rules_loader.py:234-379` — `_evaluate_paths_conditional` / `_evaluate_apply_to_conditional` / `_evaluate_business_mode_conditional` / `evaluate_rule_conditionals`（额外增强，支持 applyTo + mode + paths 三条件）
- `agent/rules_loader.py:392-499` — `load_rules_directory` 扫描 rules_dir 下所有 .md 文件
- `agent/rules_loader.py:499-530` — `format_rules_content` + `get_activated_rules_summary`
- `agent/context.py:409-421` — `_load_agents_file()` 加载 `agents_path` 单文件
- `agent_config/AGENTS.md` — 顶层 agent 指令
- `agent_config/rules/` — 规则目录（general.md / plan-mode-rules.md / research.md / trading.md）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts:10-49` — `refreshExternalRulesToggles`，同步 windsurf/cursor/agents 三类规则开关
- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/workflows.ts:10-32` — `refreshWorkflowToggles`，同步 global + local workflow 开关
- Cline `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts:577-599` — workflows 目录搜索路径 + frontmatter 解析
- Cline `third_party/cline/sdk/packages/shared/src/storage/paths.ts:372-394` — `resolveRulesConfigSearchPaths()` 多位置搜索（workspace + .clinerules + .cline/rules + 全局 + Documents/Rules）

### 评估维度

- **量化场景需求度**：无。
  - **external-rules**：量化场景下用户不使用 Windsurf/Cursor IDE，无外部规则文件需求。若未来从其他 IDE 迁移配置，可后续补充。
  - **workflows**：Cline 的 workflow 本质是"预定义 prompt 模板 + slash command 触发"，我通过前端快捷指令实现类似功能。量化场景下规则通过 `agent_config/rules/` 目录管理，无需 workflow 文件。
- **实现成本**：低。
  - **external-rules**：约 50 行 Python，在 `rules_loader.py` 新增 `load_external_rules(working_dir)` 扫描 `.windsurfrules` / `.cursorrules` 文件
  - **workflows**：约 100 行 Python，新增 `agent/workflows_loader.py` + system prompt 注入
- **替代方案**：
  1. **agent_config/rules/（已实现）**：frontmatter md 文件，支持 applyTo + mode + paths 三条件过滤（额外增强，Cline 仅支持 paths）
  2. **AGENTS.md（已实现）**：顶层 agent 指令
  3. **前端快捷指令（已实现）**：通过 Web UI 路由实现 slash command，不通过 system prompt 注入
  4. **always skills（已实现）**：`agent_config/skills/` 下 `always: true` 的技能自动注入 system prompt
- **触发实施的条件**：
  1. 从 Windsurf/Cursor IDE 迁移配置，需读取 `.windsurfrules` / `.cursorrules` 文件
  2. 需要预定义 workflow 模板且前端快捷指令无法满足
  3. 需要跨项目共享 workflow 且 `agent_config/rules/` 无法满足

### 修复步骤建议（如决定实施）

**external-rules（如需迁移）**：
1. 在 `agent/rules_loader.py` 新增 `load_external_rules(working_dir: Path) -> list[RuleLoadResult]`：
```python
def load_external_rules(working_dir: Path) -> list[RuleLoadResult]:
    """加载外部 IDE 规则文件 — 对标 Cline external-rules.ts"""
    external_files = [
        working_dir / ".windsurfrules",
        working_dir / ".cursorrules",
        working_dir / ".cursor" / "rules",  # 目录
    ]
    results: list[RuleLoadResult] = []
    for f in external_files:
        if f.is_file():
            results.append(_load_single_rule_file(f))
        elif f.is_dir():
            results.extend(load_rules_directory(f))
    return results
```
2. 在 `agent/context.py` 的 `_load_rules()` 中合并 `load_rules_directory()` + `load_external_rules()`

**workflows（如需实施）**：
3. 新增 `agent/workflows_loader.py`，扫描 `agent_config/workflows/` 目录下 md 文件
4. 解析 frontmatter（name / description / disabled / instructions）+ body
5. 在 `agent/context.py` 注入可用 workflow 列表到 system prompt
6. 在 `agent/server.py` 注册 `/api/workflows/<name>` 端点，返回 workflow instructions

**跳过项**：
- `synchronizeRuleToggles`：无 VS Code workspace state，开关通过 frontmatter `disabled` 字段管理
- `combineRuleToggles`：无多目录合并需求

### 验证方法

**不实施时的验证**：
1. `grep -r "windsurfrules\|cursorrules\|workflows" agent/`，确认无 external-rules / workflows 实现
2. 确认 `agent_config/rules/` 目录下规则文件被正确加载
3. 运行 `python tests/test_agent_e2e.py`，确认 system prompt 含 rules 段

**如实施后的验证**：
1. 在工作目录创建 `.windsurfrules` 文件，验证被加载到 system prompt
2. 在 `agent_config/workflows/` 创建测试 workflow，验证 `/api/workflows/<name>` 返回 instructions

### 注意事项

- 不能死板照搬计划：量化场景下规则通过 `agent_config/rules/` 管理，无 IDE 迁移需求，external-rules 无价值
- 保留原函数逻辑：`rules_loader.py` 的 `load_rules_directory` / `evaluate_rule_conditionals` 继续保留，`load_external_rules` 作为可选补充
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：external-rules 文件不存在时返回空列表，不降级为硬编码规则
- `agent_config/rules/` 的 frontmatter 已支持 `applyTo` + `mode` + `paths` 三条件（额外增强），Cline 的 external-rules 仅支持 toggle 开关，不应回退

---

## 附录：决策汇总表

| 小阶段 | 来源 | 决策 | 量化场景需求度 | 实现成本 | 触发条件 |
|--------|------|------|---------------|----------|----------|
| 8.1 Sub-agent | V1-V10 | 不实施 | 低 | 高 | 并行分析 50+ 股票且 asyncio 不足 |
| 8.2 Plugin/Marketplace | Y1-Y7 | 不实施 | 无 | 极高 | 非核心团队需上传策略包 |
| 8.3 Hub | Z9/Z10 | 不实施 | 无 | 高 | 多客户端共享运行时 |
| 8.4 subprocess-sandbox | F11 | 不实施 | 低 | 高 | 需执行不可信第三方代码 |
| 8.5 tool presets | F12 | 部分实施（文档化） | 低 | 低 | 需快速切换工具集且 mode 路由复杂 |
| 8.6 OpenTelemetry OTLP | Z2 | 部分实施（生产后） | 中 | 中 | 生产部署接入可观测性平台 |
| 8.7 Cron 调度 | Z11 | 部分实施（基于已有增强） | 高 | 中 | 需 file-based spec + 热重载 + 运行记录 |
| 8.8 workflows/external-rules | L9/L10 | 不实施 | 无 | 低 | 从 Windsurf/Cursor 迁移配置 |

## 附录：实施优先级建议

若触发条件出现，按以下优先级实施：

1. **8.7 Cron 调度增强**（P3，量化场景需求度最高）：基于已有 `scheduler.py` + APScheduler 增强 file-based spec + 运行记录
2. **8.6 OpenTelemetry OTLP**（P3，生产部署后）：实施 `OpenTelemetrySink`，接入可观测性平台
3. **8.5 tool presets 文档化**（P3，低成本）：在 `agent/tools/constants.py` 文档化各 mode 工具集预期
4. **8.1 Sub-agent**（P3，远期）：仅在并行分析需求超出 asyncio 能力时实施
5. **8.4 subprocess-sandbox**（P3，依赖 8.2）：仅在插件系统实施后考虑
6. **8.2 Plugin/Marketplace**（P3，远期）：仅在内部策略插件市场需求出现时实施
7. **8.3 Hub**（P3，远期）：仅在多客户端共享运行时需求出现时实施
8. **8.8 workflows/external-rules**（P3，远期）：仅在 IDE 迁移需求出现时实施

## 附录：阶段结论

Stage 8 的 8 个小阶段中：
- **不实施**：5 项（8.1 Sub-agent / 8.2 Plugin/Marketplace / 8.3 Hub / 8.4 subprocess-sandbox / 8.8 workflows/external-rules）
- **部分实施**：3 项（8.5 tool presets 文档化 / 8.6 OpenTelemetry 生产后 / 8.7 Cron 基于已有增强）
- **立即实施**：0 项（均为 P3，按需实施）

本阶段的核心价值在于明确每个 P3 项的决策与触发条件，避免未来需求变化时重复评估。已实施项（8.5 / 8.6 / 8.7）的工作量可控，且基于已有基础设施增强，不引入大规模重构。未实施项保留 `parent_agent_id` / `EventEmitter` / `max_iterations` / `TelemetrySink` 等底层字段为未来接入预留。
