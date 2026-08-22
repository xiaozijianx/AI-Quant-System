# Phase 7.10 Connectors / Kanban 对比

> 对比范围：Cline `apps/cli/src/connectors/`（聊天平台连接器 + 事件派发 + 线程绑定）+ `apps/cli/src/commands/kanban.ts`（外部 kanban npm 工具启动器）+ `sdk/packages/core/src/services/feature-flags/`（远程功能开关服务）与 Charles `agent/connectors.py`（外部命令派发器）+ `agent/kanban.py`（内嵌看板视图）逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段聚焦"外部集成 / 可视化层 / 远程开关"维度。Cline 的 Connectors 是聊天平台适配器（Slack/Telegram/Discord/GChat/WhatsApp/Linear），Kanban 是外部 npm 工具启动器，FeatureFlagsService 是远程功能开关服务；Charles 是 AI 量化系统 Web 应用，无聊天平台集成需求，将 Connectors 简化为"外部命令派发器"，Kanban 改为内嵌看板视图，FeatureFlags 完全缺失。
>
> Cline 源码：
> - `third_party/cline/apps/cli/src/connectors/base.ts`（L1-235，ConnectorBase 抽象类 — commander 命令解析 + 后台进程管理 + 状态文件读写 + stopAllFromStatePaths）
> - `third_party/cline/apps/cli/src/connectors/hooks.ts`（L1-143，dispatchConnectorHook + authorizeConnectorEvent — shell 命令派发 + zod schema 决策解析）
> - `third_party/cline/apps/cli/src/connectors/registry.ts`（L1-77，6 个连接器注册表 — discord/gchat/linear/slack/telegram/whatsapp 懒加载）
> - `third_party/cline/apps/cli/src/connectors/types.ts`（L1-17，ConnectCommandDefinition / ConnectIo / ConnectStopResult 接口）
> - `third_party/cline/apps/cli/src/connectors/catalog.ts`（L1-2，CONNECTOR_CATALOG 重新导出）
> - `third_party/cline/apps/cli/src/connectors/connector-host.ts`（L1-80+，handleConnectorUserTurn + maybeHandleConnectorApprovalReply — 连接器用户回合处理）
> - `third_party/cline/apps/cli/src/connectors/adapters/slack.ts`（L1-1200，SlackConnector — socket/webhook 双模式 + 团队隔离）
> - `third_party/cline/apps/cli/src/connectors/adapters/telegram.ts`（L1-1121，TelegramConnector — polling 长轮询 + Markdown 格式化）
> - `third_party/cline/apps/cli/src/connectors/adapters/discord.ts`（L1-1548，DiscordConnector — gateway + 线程频道 + /mute /unmute 命令）
> - `third_party/cline/apps/cli/src/connectors/adapters/gchat.ts`（L1-831，GChatConnector — Google Chat webhook）
> - `third_party/cline/apps/cli/src/connectors/adapters/linear.ts`（L1-869，LinearConnector — Linear webhook）
> - `third_party/cline/apps/cli/src/connectors/adapters/whatsapp.ts`（L1-857，WhatsAppConnector — WhatsApp webhook）
> - `third_party/cline/sdk/packages/shared/src/connectors/events.ts`（L1-73，ConnectorHookEventName 枚举 + ConnectorAuthorizationRequestSchema + ConnectorAuthorizationDecisionSchema + ConnectorHookEventSchema）
> - `third_party/cline/sdk/packages/shared/src/connectors/platforms.ts`（L193-442，CONNECTOR_PLATFORMS — 6 个平台字段定义 + 安全配置 + buildArgs）
> - `third_party/cline/sdk/packages/core/src/hooks/subprocess-runner.ts`（L110-200，runSubprocessEvent — spawn + stdin JSON + stdout/stderr 收集 + timeout）
> - `third_party/cline/apps/cli/src/commands/kanban.ts`（L1-405，launchKanban — npm/pnpm/bun 安装器 + spawn + 信号转发 + 平台差异）
> - `third_party/cline/sdk/packages/core/src/services/feature-flags/FeatureFlagsService.ts`（L1-332，FeatureFlagsService — provider 模式 + 持久化缓存 + 1h TTL + 7d persistent cache）
> - `third_party/cline/sdk/packages/shared/src/feature-flags.ts`（L1-67，FeatureFlag 枚举 + IFeatureFlagsProvider 接口 + FeatureFlagsContext）
> - `third_party/cline/docs/usage/kanban.mdx`（L1-50，kanban 文档 — 隔离 worktree + 任务依赖 + inline review）
>
> Charles 源码：
> - `agent/connectors.py`（L1-608，ConnectorConfig + ConnectorEvent + ConnectorManager + ConnectorHooks + get_connector_manager — YAML 配置驱动的外部命令派发器）
> - `agent/kanban.py`（L1-291，KanbanCard + KanbanColumn + KanbanBoard + KanbanManager + get_kanban_manager — 基于 SessionState.todos 的内嵌看板视图）
> - `agent/server.py` L489-502（ConnectorHooks 注册到 AgentRuntime）+ L2293-2367（/connectors + /connectors/reload + /kanban + /kanban/overview HTTP 端点）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Connectors / Kanban / FeatureFlagsService 三大子系统。**核心结论：Charles 在 Connectors 维度采用了"概念映射 + 实现简化"策略（对标 Cline `hooks.ts` 而非完整 connectors 系统），在 Kanban 维度采用了"内嵌视图替代外部应用"策略，在 FeatureFlagsService 维度完全缺失。三处差异均源于 Charles 是 Web 应用而非 CLI 工具集，且为单进程本地架构。**

### 核心结论

1. **Connectors 概念完全不同**：Cline 的 connectors 是 **6 个聊天平台适配器**（Slack/Telegram/Discord/GChat/WhatsApp/Linear），每个适配器 800-1500 行，实现完整的 bot 接入 + 线程绑定 + 会话生命周期 + 任务更新 + 用户审批流程；Charles 的 `connectors.py`（L1-608）是 **外部命令派发器**，通过 YAML 配置 shell 命令，将 AgentRuntime 事件路由到外部脚本。Charles 的注释（L15-22）明确说明"Cline 的 connectors 是 Slack/Discord/Telegram 等聊天平台适配器，本系统是 AI 量化系统智能助手，无需集成聊天平台，因此将 connectors 简化为外部命令派发器"。

2. **Charles Connectors 实际对标的是 Cline hooks.ts**：Cline `connectors/hooks.ts`（L1-143）实现 `dispatchConnectorHook` + `authorizeConnectorEvent` 两个函数，是连接器内部的事件派发机制；Charles `ConnectorManager.dispatch_event`（L248-291）+ `ConnectorManager.authorize`（L293-342）的语义与 Cline `hooks.ts` 高度对齐——都通过 shell 命令派发事件，都通过 stdin 传递 JSON payload，都解析 stdout 作为决策结果。Charles 是"将 hooks.ts 提取为独立子系统"的设计。

3. **6 个聊天平台适配器全部缺失**：Cline 的 SlackConnector（L437-1200）、TelegramConnector、DiscordConnector、GChatConnector、LinearConnector、WhatsAppConnector 共约 6000+ 行代码，Charles **0 行实现**。这与 Charles 是 Web 应用一致——Web 应用通过 HTTP API 接收用户输入，不需要聊天平台桥接。

4. **Kanban 实现方向相反**：Cline `commands/kanban.ts`（L1-405）是**外部 npm 工具启动器**——通过 `spawn` 启动独立 `kanban` 进程，自动检测/安装 npm 包（npm/pnpm/bun），处理 SIGINT/SIGTERM 信号转发，平台差异（Windows shell:true / Unix detached）。kanban 本身是完整应用（git worktree + 任务依赖 + inline review + auto-commit/PR）。Charles `kanban.py`（L1-291）是**内嵌看板视图**——基于 `SessionState.todos` 实时构建 3 列看板（待办/进行中/已完成），无独立进程，无 git worktree，无任务依赖，是 TodoWrite 工具的可视化层。

5. **Kanban 数据来源不同**：Cline kanban 的任务卡片来自外部 kanban 应用的内部状态（用户手动创建或 sidebar chat 生成），每个卡片有独立 git worktree；Charles kanban 的卡片直接来自 `SessionState.todos`（L216 `todos = state.todos`），是 TodoWrite 工具的状态映射，单一数据源，无独立任务存储。

6. **FeatureFlagsService 完全缺失**：Cline `FeatureFlagsService.ts`（L1-332）实现完整的远程功能开关服务——PostHog provider + 1 小时内存 TTL 缓存 + 7 天持久化缓存 + context 上下文（distinctId/userId/clientName）+ hydrateCache 快照恢复。Charles **无 `feature_flags.py` 文件，无配置文件，无任何实现**。这与 Charles 单进程本地架构一致——本地应用无需远程功能开关。

7. **subprocess-runner 实现策略对齐**：Cline `subprocess-runner.ts` L110-200 `runSubprocessEvent` 使用 Node.js `spawn` + stdin JSON + stdout/stderr 监听 + timeout；Charles `connectors.py` L344-425 `_run_command` 使用 `asyncio.create_subprocess_shell` + stdin JSON + stdout/stderr 收集 + `asyncio.wait_for` timeout。两者语义等价，实现细节因语言而异。

8. **事件类型枚举差距大**：Cline `events.ts` L3-17 定义 13 种连接器事件类型（connector.started/stopping + session.authorize/started/reused/reset + message.received/denied/completed/failed + schedule.delivery.started/sent/failed）；Charles `connectors.py` 通过 YAML 配置任意事件字符串（L94 `events: list[str]`），实际使用的 5 种事件（run.started/finished + tool.started/finished + session.authorize）由 `ConnectorHooks`（L497-589）硬编码。Charles 的事件命名空间与 Cline 不重叠。

9. **授权决策 schema 对齐**：Cline `events.ts` L50-55 `ConnectorAuthorizationDecisionSchema` 定义 `{action: "allow"|"deny", message?, reason?, metadata?}`；Charles `connectors.py` L427-449 `_parse_approval_decision` 解析 `{action, reason, message, connector}`，语义等价（action + reason + message），Charles 多了 `connector` 字段用于追溯决策来源。

10. **nanobot 残留**：P7.10 范围内（`agent/connectors.py` + `agent/kanban.py`）共 **0 处注释残留 + 0 处实现逻辑残留**。两个文件均以 Cline 为对标对象，未引用 nanobot。但 agent 目录其他文件（session.py / server.py / context.py / providers/qwen.py / tools/file_tools.py / tools/exec_tool.py / skills/* 等 12 个文件）仍有 nanobot 注释残留，属于 P7.10 范围外。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| Connectors 概念 | 低 | Cline 是聊天平台适配器，Charles 是外部命令派发器，概念完全不同 |
| Connectors 事件派发 | 高 | Charles `dispatch_event` 与 Cline `dispatchConnectorHook` 语义等价 |
| Connectors 授权决策 | 高 | Charles `authorize` 与 Cline `authorizeConnectorEvent` 语义等价 |
| Connectors subprocess 执行 | 高 | 两者均 spawn + stdin JSON + stdout 解析 + timeout |
| 6 个聊天平台适配器 | 缺失 | Charles 0 行实现，Web 应用无需聊天平台 |
| Kanban 实现方向 | 低 | Cline 是外部 npm 工具启动器，Charles 是内嵌视图 |
| Kanban 数据来源 | 低 | Cline 来自 kanban 应用内部状态，Charles 来自 SessionState.todos |
| Kanban 看板列数 | 高 | 两者均 3 列（待办/进行中/已完成） |
| Kanban 多项目视图 | 中 | Cline 通过外部应用支持多仓库，Charles `get_overview` 聚合所有会话 |
| FeatureFlagsService | 缺失 | Charles 完全未实现 |
| 事件类型枚举 | 低 | Cline 13 种固定枚举，Charles 任意字符串 + 5 种硬编码 |
| 授权决策 schema | 高 | 语义等价（action + reason + message） |
| 配置文件 | 不同 | Cline 无独立配置（命令行参数），Charles 用 YAML |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.10.1 | Slack 连接器 | `adapters/slack.ts` L437-1200 SlackConnector — socket/webhook 双模式 + 团队隔离 + HubSessionClient + thread-bindings + task-updates | 无 | 缺失 | Charles 是 Web 应用，无 Slack 集成需求。Cline 1200 行实现完整 Slack bot |
| 7.10.2 | Telegram 连接器 | `adapters/telegram.ts` L1-1121 TelegramConnector — polling 长轮询 + Markdown 格式化 + getMe API + allowed-user-id 安全限制 | 无 | 缺失 | Charles 是 Web 应用，无 Telegram 集成需求。Cline 1121 行实现完整 Telegram bot |
| 7.10.3 | Discord 连接器 | `adapters/discord.ts` L1-1548 DiscordConnector — gateway + 线程频道 + /mute /unmute 命令 + subscribed thread 处理 + /idle no-op | 无 | 缺失 | Charles 是 Web 应用，无 Discord 集成需求。Cline 1548 行实现完整 Discord bot |
| 7.10.4 | Kanban 看板 | `commands/kanban.ts` L1-405 launchKanban — npm/pnpm/bun 安装器 + spawn + 信号转发 + 平台差异 + KANBAN_SHUTDOWN_TIMEOUT_MS 10s | `agent/kanban.py` L1-291 KanbanManager — 基于 SessionState.todos 实时构建 3 列看板 + get_board + get_progress + get_overview | 低 | 实现方向完全不同。Cline 是外部 npm 工具启动器（kanban 是独立应用，含 git worktree + 任务依赖 + inline review）；Charles 是内嵌视图（TodoWrite 工具的可视化层）。两者仅在"3 列看板"概念上对齐 |
| 7.10.5 | FeatureFlagsService | `FeatureFlagsService.ts` L1-332 + `shared/feature-flags.ts` L1-67 + PostHog provider — 1h 内存 TTL + 7d 持久化缓存 + context + hydrateCache + 1 个 flag (CLINE_PASS) | 无 | 缺失 | Charles 完全未实现。无 `feature_flags.py` 文件，无配置文件，无任何代码引用。Charles 单进程本地架构无需远程功能开关 |
| 7.10.6 | GChat 连接器 | `adapters/gchat.ts` L1-831 GChatConnector — Google Chat webhook | 无 | 缺失 | Charles 是 Web 应用，无 GChat 集成需求 |
| 7.10.7 | Linear 连接器 | `adapters/linear.ts` L1-869 LinearConnector — Linear webhook | 无 | 缺失 | Charles 是 Web 应用，无 Linear 集成需求 |
| 7.10.8 | WhatsApp 连接器 | `adapters/whatsapp.ts` L1-857 WhatsAppConnector — WhatsApp webhook | 无 | 缺失 | Charles 是 Web 应用，无 WhatsApp 集成需求 |
| 7.10.9 | ConnectorBase 抽象类 | `base.ts` L21-235 ConnectorBase — commander 命令解析 + maybeRunInBackground + stopManagedProcess + parseMode + readStateFile/writeStateFile + removeStaleState | 无 | 缺失 | Charles 不需要 ConnectorBase——它的 connectors 是 YAML 配置的 shell 命令，不是 commander 子命令 |
| 7.10.10 | 连接器注册表 | `registry.ts` L1-77 — 6 个连接器懒加载 Map + listConnectors + getConnector | `connectors.py` L236-246 list_connectors + get_connector（dict 查询） | 中 | 两者均提供 list/get 接口。Cline 是懒加载（dynamic import），Charles 是启动时全量加载 |
| 7.10.11 | 事件派发函数 | `hooks.ts` L17-64 dispatchConnectorHook — shell 命令派发 + runSubprocessEvent + 非零退出码警告 | `connectors.py` L248-291 dispatch_event — asyncio.gather 并发派发 + 非零退出码警告 | 高 | 语义等价。Cline 单命令派发，Charles 多连接器并发派发 |
| 7.10.12 | 授权决策函数 | `hooks.ts` L66-143 authorizeConnectorEvent — runSubprocessEvent + ConnectorAuthorizationDecisionSchema zod 解析 + 失败默认 allow | `connectors.py` L293-342 authorize — 遍历授权连接器 + _parse_approval_decision + 失败默认 allow | 高 | 语义等价。Cline 单授权命令，Charles 多授权连接器串行（任一 deny 即拒绝） |
| 7.10.13 | subprocess 执行 | `subprocess-runner.ts` L110-200 runSubprocessEvent — spawn + stdin JSON + stdout/stderr 监听 + timeout + detached 选项 | `connectors.py` L344-425 _run_command — asyncio.create_subprocess_shell + stdin JSON + stdout/stderr 收集 + asyncio.wait_for timeout | 高 | 语义等价。Cline 支持 detached 模式（fire-and-forget），Charles 不支持 |
| 7.10.14 | 事件类型枚举 | `events.ts` L3-17 ConnectorHookEventNameSchema — 13 种固定枚举（connector.started/stopping + session.* + message.* + schedule.delivery.*） | `connectors.py` L94 events: list[str]（YAML 任意字符串）+ L497-589 ConnectorHooks 硬编码 5 种（run.started/finished + tool.started/finished + session.authorize） | 低 | Cline 事件命名空间面向聊天平台，Charles 面向 agent 运行时。命名不重叠 |
| 7.10.15 | 授权决策 schema | `events.ts` L50-55 ConnectorAuthorizationDecisionSchema — {action: "allow"\|"deny", message?, reason?, metadata?} + zod 校验 | `connectors.py` L427-449 _parse_approval_decision — {action, reason, message, connector} + 非 JSON 默认 allow | 高 | 语义等价。Charles 多了 `connector` 字段用于追溯决策来源，缺少 `metadata` 字段 |
| 7.10.16 | ConnectorHookEvent 结构 | `events.ts` L57-63 ConnectorHookEventSchema — {adapter, botUserName?, event, payload, ts} | `connectors.py` L117-138 ConnectorEvent — {connector, event, payload, ts} | 中 | 字段结构相似。Cline 有 adapter/botUserName（聊天平台概念），Charles 用 connector 替代 adapter |
| 7.10.17 | ConnectorConfig | `types.ts` ConnectCommandDefinition 接口 + `base.ts` ConnectorBase 实现（name + description + run + showHelp + stopAll） | `connectors.py` L79-109 ConnectorConfig dataclass — {name, command, events, enabled, description, timeout, is_approval} | 低 | 概念不同。Cline ConnectorConfig 是 commander 子命令定义，Charles 是 shell 命令 + 事件订阅配置 |
| 7.10.18 | 配置驱动方式 | 命令行参数（commander）+ `connect <platform> --bot-token xxx` | `connectors.py` L65 _DEFAULT_CONNECTORS_CONFIG = "agent_config/connectors.yaml" + YAML 加载 | 不同 | Cline 通过命令行参数配置，Charles 通过 YAML 文件配置。Charles 更适合 Web 应用的运维模式 |
| 7.10.19 | Kanban 多项目视图 | kanban 应用本身支持多仓库多项目（独立 git worktree） | `kanban.py` L166-212 get_overview — 扫描 _sessions 字典 + 每个会话构建摘要 + total_sessions + total_tasks | 中 | 两者均支持多项目视图。Cline 通过外部应用支持多仓库，Charles 通过内存 _sessions 聚合（重启后丢失，除非持久化） |
| 7.10.20 | Kanban 看板列 | kanban 应用自定义列（默认 3 列：todo/doing/done） | `kanban.py` L238-254 硬编码 3 列（pending/in_progress/completed）+ 中文标题（待办/进行中/已完成） | 高 | 两者均 3 列。Cline 列可自定义，Charles 列固定 |
| 7.10.21 | Kanban 卡片字段 | kanban 应用卡片字段（任务描述 + 状态 + worktree 路径 + 最新 agent 输出 + 依赖链 + 评论） | `kanban.py` L55-76 KanbanCard — {content, status, active_form, session_id} | 低 | Charles 卡片字段远少于 Cline。Charles 无 worktree、无依赖链、无评论 |
| 7.10.22 | Kanban 启动方式 | `main.ts` L687-691 + L744-745 launchKanban — `--kanban` 命令行选项 + 自动安装 kanban npm 包 | `server.py` L2330-2350 /kanban HTTP 端点 + `server.py` L2353-2367 /kanban/overview HTTP 端点 | 不同 | Cline 通过 CLI 启动外部进程，Charles 通过 HTTP API 返回 JSON 数据 |
| 7.10.23 | ConnectorHooks 集成 | `connector-host.ts` L20-27 导入 dispatchConnectorHook + authorizeConnectorEvent + 在 handleConnectorUserTurn 中调用 | `server.py` L489-502 ConnectorHooks 注册到 AgentRuntime + before_run/after_run/before_tool/after_tool/before_approval 5 个钩子 | 中 | Cline 在连接器回合处理中调用，Charles 在 AgentRuntime 钩子系统中注册。Charles 的集成更通用 |
| 7.10.24 | 授权决策消费 | `connector-host.ts` maybeHandleConnectorApprovalReply — 解析用户回复作为审批决策 | `connectors.py` L564-589 ConnectorHooks.before_approval — 调用 authorize + 返回 BeforeApprovalResult | 中 | Cline 通过聊天回复决策，Charles 通过外部命令决策。Charles 的决策更自动化 |
| 7.10.25 | 信号转发 | `kanban.ts` L225-252 forwardSignalToKanbanProcess — SIGINT/SIGTERM + KANBAN_SHUTDOWN_TIMEOUT_MS 10s 后 SIGKILL + Unix 进程组 -pid | 无 | 缺失 | Charles 无外部进程，无需信号转发 |
| 7.10.26 | 平台差异处理 | `kanban.ts` L51-66 getKanbanCommand/getPackageManagerCommand — Windows kanban.cmd + Unix kanban + L156-174 buildKanbanSpawnOptions — Windows shell:true + Unix detached | `connectors.py` L368 asyncio.create_subprocess_shell（跨平台统一） | 中 | Charles 通过 shell=True 跨平台统一，Cline 显式处理 Windows/Unix 差异 |
| 7.10.27 | 连接器状态持久化 | `base.ts` L107-121 readStateFile/writeStateFile/removeStateFile + L123-134 removeStaleState — JSON 文件 + PID 检测 + stale 清理 | 无 | 缺失 | Charles 的连接器无状态（每次派发即启即停），无需持久化 |
| 7.10.28 | 后台进程管理 | `base.ts` L136-169 maybeRunInBackground — spawnDetachedConnector + childEnvVar 环境变量标识 + isRunning 检测 + 已运行提示 | 无 | 缺失 | Charles 的连接器是短命令（30s 超时），无后台进程 |
| 7.10.29 | 线程绑定 | `thread-bindings.ts`（未展开）— ConnectorBindingStore + ConnectorThreadState + findBindingForDeliveryTarget + persistMergedThreadState | 无 | 缺失 | Charles 无聊天线程概念，无需线程绑定 |
| 7.10.30 | 任务更新中继 | `task-updates.ts`（未展开）— startConnectorTaskUpdateRelay — 将 agent 任务进度推送到聊天平台 | 无 | 缺失 | Charles 无聊天平台，无需任务更新中继 |
| 7.10.31 | FeatureFlagsProvider 接口 | `shared/feature-flags.ts` L51-59 IFeatureFlagsProvider — getAllFlagsAndPayloads + enabled + getSettings + dispose | 无 | 缺失 | Charles 完全未实现 |
| 7.10.32 | FeatureFlagsContext | `shared/feature-flags.ts` L24-31 FeatureFlagsContext — {distinctId?, userId?, clientName?} | 无 | 缺失 | Charles 完全未实现 |
| 7.10.33 | FeatureFlag 枚举 | `shared/feature-flags.ts` L1-4 FeatureFlag — 仅 CLINE_PASS: "ext-cline-pass" | 无 | 缺失 | Charles 完全未实现 |

---

## 三、重点差距详解

### 3.1 Connectors 概念差异：聊天平台适配器 vs 外部命令派发器

**Cline 的 connectors 是完整的聊天平台集成系统**：

- `apps/cli/src/connectors/` 目录共约 7000+ 行代码
- 6 个聊天平台适配器（Slack/Telegram/Discord/GChat/WhatsApp/Linear），每个 800-1500 行
- 每个 adapter 实现：bot 接入 + 线程绑定 + 会话生命周期 + 任务更新 + 用户审批 + 命令处理（/mute /unmute /idle）
- 通过 `ConnectorBase` 抽象类（L21-235）提供 commander 命令解析 + 后台进程管理 + 状态文件读写
- 通过 `registry.ts`（L1-77）懒加载注册表
- 通过 `connector-host.ts` 处理用户回合 + 审批回复
- 通过 `thread-bindings.ts` 维护线程 ↔ 会话绑定
- 通过 `task-updates.ts` 将 agent 进度推送到聊天平台

**Charles 的 connectors.py 是简化版外部命令派发器**（L1-608）：

- 仅 608 行代码
- 不集成任何聊天平台
- 通过 YAML 配置外部 shell 命令（L65 `_DEFAULT_CONNECTORS_CONFIG = "agent_config/connectors.yaml"`）
- `ConnectorManager.dispatch_event`（L248-291）将事件派发到匹配的连接器
- `ConnectorManager.authorize`（L293-342）调用授权连接器做决策
- `ConnectorHooks`（L473-589）适配到 AgentRuntime 的钩子系统
- 通过 `server.py` L2293-2367 提供 HTTP 端点管理

**关键差距**：

1. **集成对象不同**：Cline 集成聊天平台（用户通过 Slack/Telegram 等与 agent 交互），Charles 集成外部 shell 命令（agent 事件触发外部脚本）
2. **数据流向不同**：Cline 是双向（用户消息 → agent → 回复 → 用户），Charles 是单向（agent 事件 → 外部命令）
3. **状态管理不同**：Cline 维护线程绑定 + 会话生命周期 + 任务更新，Charles 无状态（每次派发即启即停）
4. **进程模型不同**：Cline 的连接器是长期运行的后台进程（`maybeRunInBackground` L136-169），Charles 的连接器是短命令（30s 超时）

**Charles 的设计合理性**：Charles 是 AI 量化系统 Web 应用，用户通过 Web UI 与 agent 交互，无需聊天平台桥接。Charles 的 connectors.py 实际对标的是 Cline `hooks.ts`（仅 143 行），将其提取为独立子系统并扩展为 YAML 配置驱动。这是合理的架构简化。

### 3.2 Kanban 实现方向差异：外部 npm 工具 vs 内嵌视图

**Cline 的 kanban 是外部 npm 工具启动器**（`commands/kanban.ts` L1-405）：

- `launchKanban` 函数（L335-405）启动独立 `kanban` npm 进程
- `ensureKanbanInstalled`（L281-326）自动检测/安装 npm 包（npm/pnpm/bun 三种包管理器）
- `spawnKanbanProcess`（L190-192）通过 `spawn` 启动子进程
- `forwardSignalToKanbanProcess`（L225-252）转发 SIGINT/SIGTERM 信号 + 10s 后 SIGKILL
- `buildKanbanSpawnOptions`（L162-174）处理平台差异（Windows shell:true / Unix detached）
- kanban 应用本身是完整工具：git worktree 隔离 + 任务依赖链 + inline review + auto-commit/PR

**Charles 的 kanban.py 是内嵌看板视图**（L1-291）：

- `KanbanManager.get_board`（L144-154）基于 `SessionState.todos` 实时构建 3 列看板
- `KanbanManager.get_progress`（L156-164）返回进度统计
- `KanbanManager.get_overview`（L166-212）扫描所有会话构建多项目概览
- `_build_board`（L214-261）按 status 分组为 pending/in_progress/completed 三列
- `_calc_stats`（L263-276）计算 total/pending/in_progress/completed/completion_rate
- 通过 `server.py` L2330-2367 提供 HTTP 端点返回 JSON 数据

**关键差距**：

1. **实现层级不同**：Cline 是进程启动器（启动外部应用），Charles 是数据视图（基于 SessionState.todos 构建）
2. **任务来源不同**：Cline 的任务卡片来自 kanban 应用内部状态（用户手动创建或 sidebar chat 生成），Charles 的卡片来自 TodoWrite 工具
3. **隔离机制不同**：Cline 每个任务有独立 git worktree（agent 在隔离环境工作），Charles 无隔离（所有任务在同一 agent 会话中）
4. **功能范围不同**：Cline 支持任务依赖链 + inline review + auto-commit/PR + resume ID，Charles 仅支持看板视图 + 进度统计
5. **生命周期不同**：Cline 的 kanban 进程独立于 agent 运行，Charles 的 kanban 视图随 agent 会话生命周期

**Charles 的设计合理性**：Charles 是 Web 应用，看板应内嵌于 Web UI 而非启动外部进程。Charles 的 kanban 是 TodoWrite 工具的可视化层，单一数据源（SessionState.todos），避免数据冗余。这与 Cline 的独立 kanban 应用设计哲学完全不同，但符合 Web 应用的架构模式。

### 3.3 FeatureFlagsService 完全缺失

**Cline 的 FeatureFlagsService 是完整的远程功能开关服务**（`FeatureFlagsService.ts` L1-332）：

- `FeatureFlagsService` 类（L47-332）：
  - `provider: IFeatureFlagsProvider`（L48）—— PostHog provider 实现
  - `cacheTtlMs`（L52）—— 1 小时内存 TTL 缓存（L18 `DEFAULT_CACHE_TTL_MS = 60 * 60 * 1000`）
  - `persistentCacheMaxAgeMs`（L53）—— 7 天持久化缓存（L19 `DEFAULT_PERSISTENT_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000`）
  - `cacheFilePath`（L52）—— 持久化缓存文件路径
  - `context: FeatureFlagsContext`（L54）—— {distinctId, userId, clientName}
  - `poll(userId?)`（L91）—— 拉取远程 flags + 更新缓存 + 持久化
  - `getBooleanFlagEnabled(flagName)`（L303）—— 读取布尔 flag
  - `getFlagPayload(flagName)`（L307）—— 读取任意类型 flag
  - `hydrateCache(snapshot)`（L74）—— 从快照恢复缓存
  - `getCacheSnapshot()`（L83）—— 获取缓存快照
  - `dispose()`（L329）—— 释放资源

- `FeatureFlag` 枚举（`shared/feature-flags.ts` L1-4）：
  - 仅 1 个 flag：`CLINE_PASS: "ext-cline-pass"`（启用 ClinePass provider/model list）
  - 默认值：`false`（L64 `FeatureFlagDefaultValue`）

- `IFeatureFlagsProvider` 接口（L51-59）：
  - `getAllFlagsAndPayloads(options)` —— 拉取所有 flags
  - `enabled` —— provider 是否启用
  - `getSettings()` —— 获取设置
  - `dispose()` —— 释放资源

**Charles 完全未实现**：

- 无 `agent/feature_flags.py` 文件
- 无 `agent_config/feature_flags.yaml` 配置文件
- 无任何代码引用 `FeatureFlag` / `feature_flag` / `featureFlag`
- `AGENT_PHASE28_PLAN.md` L615-618 曾规划"新增 `agent/feature_flags.py`；从 `agent_config/feature_flags.yaml` 加载；支持运行时热更新"，但未实施

**Charles 缺失的合理性**：Charles 是单进程本地 Web 应用，无远程功能开关需求。功能开关用于灰度发布、A/B 测试、按用户群体启用功能等场景，这些场景在本地单进程应用中不存在。Charles 的功能启用/禁用通过 `agent_config/rule_toggles.json` 等本地配置文件管理，无需远程服务。

### 3.4 授权决策 schema 对齐分析

**Cline `events.ts` L50-55**：
```typescript
export const ConnectorAuthorizationDecisionSchema = z.object({
    action: z.enum(["allow", "deny"]).default("allow"),
    message: z.string().optional(),
    reason: z.string().optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
});
```

**Charles `connectors.py` L427-449**：
```python
def _parse_approval_decision(
    self,
    result: dict[str, Any],
    connector_name: str,
) -> dict[str, Any]:
    parsed = result.get("parsed_json")
    if not isinstance(parsed, dict):
        return {"action": "allow", "connector": connector_name}
    action = parsed.get("action", "allow")
    if action not in ("allow", "deny"):
        action = "allow"
    return {
        "action": action,
        "reason": parsed.get("reason", ""),
        "message": parsed.get("message", ""),
        "connector": connector_name,
    }
```

**对比分析**：

| 字段 | Cline | Charles | 说明 |
|------|-------|---------|------|
| action | `z.enum(["allow", "deny"]).default("allow")` | `parsed.get("action", "allow")` + 校验 | 语义等价，均默认 allow |
| message | `z.string().optional()` | `parsed.get("message", "")` | Charles 默认空字符串，Cline 默认 undefined |
| reason | `z.string().optional()` | `parsed.get("reason", "")` | Charles 默认空字符串，Cline 默认 undefined |
| metadata | `z.record(z.string(), z.unknown()).optional()` | 无 | Charles 缺失 metadata 字段 |
| connector | 无 | `connector_name`（参数注入） | Charles 多了 connector 字段用于追溯决策来源 |

两者在核心语义上对齐（action + reason + message），Charles 缺少 `metadata` 字段但增加了 `connector` 追溯字段。Charles 的 `_parse_approval_decision` 在非 JSON 或解析失败时默认 allow（L438-439），与 Cline 的 zod `default("allow")` 语义一致。

---

## 四、nanobot 残留专项检查

### 4.1 P7.10 范围内检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 说明 |
|------|---------|-------------|------|
| `agent/connectors.py` | 0 处 | 0 处 | 文件头注释（L2）对标 Cline connectors + dispatchConnectorHook，L15-22 明确说明与 Cline 的差异，未引用 nanobot |
| `agent/kanban.py` | 0 处 | 0 处 | 文件头注释（L2）对标 Cline kanban，L14-19 明确说明与 Cline 的差异，未引用 nanobot |

### 4.2 P7.10 范围外发现（仅供参考，不在本阶段处理范围）

在 agent 目录其他文件中发现 12 个文件有 nanobot 注释残留（均为注释，非实现逻辑）：

- `agent/session.py` L2/L22 — "对标 Cline session persistence + nanobot session_key" / "对标 nanobot"
- `agent/server.py` L2/L4/L28 — "对标 Cline server + nanobot routes/chat.py" / "用 AgentRuntime 替换 nanobot" / "对标 nanobot"
- `agent/context.py` L275 — "[已废弃] nanobot 风格的额外段落"
- `agent/providers/qwen.py` L21/L49/L116/L214/L253/L385/L406 — 多处 "对标 nanobot openai_compat_provider.py"
- `agent/tools/file_tools.py` L2/L7/L12/L27/L115/L130/L165 — "对标 Cline FileReadTool + nanobot FilesystemTool"
- `agent/tools/exec_tool.py` L2/L8/L9/L10/L18/L19/L41/L57/L123/L165/L181/L263 — "对标 Cline BashTool + nanobot ShellTool"
- `agent/tools/web_tool.py` L2/L9/L10/L13/L28/L111/L165 — "对标 Cline WebSearchTool + nanobot WebSearchTool"
- `agent/tools/__init__.py` L2 — "对标 Cline extensions/tools 和 nanobot agent/tools"
- `agent/skills/registry.py` L2/L20/L100/L184 — "对标 Cline skills registry + nanobot SkillsLoader"
- `agent/skills/loader.py` L2/L29/L48/L96/L167/L222/L392/L423 — "对标 Cline skills discovery + nanobot SkillsLoader"
- `agent/skills/skill_tool.py` L18 — "这与 nanobot 的子 agent 隔离执行有本质区别"
- `agent/skills/__init__.py` L2/L23 — "对标 Cline skills + nanobot SkillsLoader"

这些残留属于其他 Phase 的处理范围（P3.x 工具对比、P4.x 技能对比、P5.x 提示词对比、P7.4 LLM provider 对比等），P7.10 不处理。

---

## 五、结论

### 5.1 一致性总评

| 子系统 | 一致性等级 | 说明 |
|--------|-----------|------|
| Connectors（聊天平台适配器） | 缺失 | Charles 不实施聊天平台集成，0 行实现 vs Cline 7000+ 行 |
| Connectors（事件派发） | 高 | Charles `dispatch_event` + `authorize` 与 Cline `dispatchConnectorHook` + `authorizeConnectorEvent` 语义等价 |
| Kanban（外部应用启动） | 缺失 | Charles 不实施外部应用启动，0 行实现 vs Cline 405 行 |
| Kanban（内嵌视图） | 额外增强 | Charles 实现了 Cline 没有的内嵌看板视图（291 行），基于 SessionState.todos |
| FeatureFlagsService | 缺失 | Charles 完全未实现，0 行实现 vs Cline 332+67 行 |

### 5.2 差距根源

1. **应用形态不同**：Cline 是 CLI 工具集（支持聊天平台集成 + 外部 kanban 应用），Charles 是 Web 应用（通过 HTTP API 接收输入 + 内嵌视图渲染）
2. **进程模型不同**：Cline 支持多进程（外部 kanban 进程 + 后台连接器进程），Charles 是单进程（所有功能内嵌）
3. **用户交互模式不同**：Cline 支持聊天平台异步交互（用户通过 Slack 等发送消息），Charles 是同步 Web 交互（用户通过 Web UI 实时交互）
4. **部署环境不同**：Cline 面向开发者本地使用（需要 git worktree 隔离 + npm 工具链），Charles 面向量化系统服务器部署（无需 git worktree + 无需 npm 工具链）
5. **功能开关需求不同**：Cline 是 SaaS 产品需要灰度发布（FeatureFlagsService + PostHog），Charles 是本地应用无需远程开关

### 5.3 Charles 设计合理性评估

Charles 的三处差异（Connectors 简化 + Kanban 内嵌 + FeatureFlags 缺失）均是 Web 应用架构下的合理设计：

- **Connectors 简化合理**：Charles 将 Cline 的 `hooks.ts`（143 行）提取为独立子系统（608 行），扩展为 YAML 配置驱动，保留了事件派发 + 授权决策的核心语义，去除了聊天平台适配器的复杂度
- **Kanban 内嵌合理**：Charles 基于 SessionState.todos 构建看板视图，单一数据源避免数据冗余，符合 Web 应用的视图层设计模式
- **FeatureFlags 缺失合理**：Charles 单进程本地应用无需远程功能开关，功能启用/禁用通过本地配置文件管理

### 5.4 改进建议（可选，非必需）

1. **Connectors 事件类型对齐**：Charles 的 5 种事件（run.started/finished + tool.started/finished + session.authorize）与 Cline 的 13 种事件类型不重叠。若未来需要与 Cline 生态兼容，可考虑对齐事件命名空间
2. **授权决策 schema 补全**：Charles 的 `_parse_approval_decision` 缺少 `metadata` 字段，可补充以支持更丰富的决策元数据
3. **Kanban 持久化**：Charles 的 `get_overview` 依赖内存 `_sessions` 字典，重启后丢失。可考虑持久化会话状态以支持跨重启的多项目概览
4. **FeatureFlags 本地化实现**：若未来需要功能开关（如灰度启用新工具），可实现本地化版本（从 `agent_config/feature_flags.yaml` 加载），无需远程服务

---

## 六、附录：源码文件清单

### 6.1 Cline 源码文件

| 文件路径 | 行数 | 说明 |
|---------|------|------|
| `third_party/cline/apps/cli/src/connectors/base.ts` | 235 | ConnectorBase 抽象类 |
| `third_party/cline/apps/cli/src/connectors/hooks.ts` | 143 | dispatchConnectorHook + authorizeConnectorEvent |
| `third_party/cline/apps/cli/src/connectors/registry.ts` | 77 | 6 个连接器注册表 |
| `third_party/cline/apps/cli/src/connectors/types.ts` | 17 | ConnectCommandDefinition 接口 |
| `third_party/cline/apps/cli/src/connectors/catalog.ts` | 2 | CONNECTOR_CATALOG 重新导出 |
| `third_party/cline/apps/cli/src/connectors/connector-host.ts` | 80+ | 连接器用户回合处理 |
| `third_party/cline/apps/cli/src/connectors/adapters/slack.ts` | 1200 | SlackConnector |
| `third_party/cline/apps/cli/src/connectors/adapters/telegram.ts` | 1121 | TelegramConnector |
| `third_party/cline/apps/cli/src/connectors/adapters/discord.ts` | 1548 | DiscordConnector |
| `third_party/cline/apps/cli/src/connectors/adapters/gchat.ts` | 831 | GChatConnector |
| `third_party/cline/apps/cli/src/connectors/adapters/linear.ts` | 869 | LinearConnector |
| `third_party/cline/apps/cli/src/connectors/adapters/whatsapp.ts` | 857 | WhatsAppConnector |
| `third_party/cline/sdk/packages/shared/src/connectors/events.ts` | 73 | 事件类型 + 授权决策 schema |
| `third_party/cline/sdk/packages/shared/src/connectors/platforms.ts` | 442 | 6 个平台字段定义 |
| `third_party/cline/sdk/packages/core/src/hooks/subprocess-runner.ts` | 200+ | runSubprocessEvent |
| `third_party/cline/apps/cli/src/commands/kanban.ts` | 405 | launchKanban |
| `third_party/cline/sdk/packages/core/src/services/feature-flags/FeatureFlagsService.ts` | 332 | FeatureFlagsService |
| `third_party/cline/sdk/packages/shared/src/feature-flags.ts` | 67 | FeatureFlag 枚举 + 接口 |

### 6.2 Charles 源码文件

| 文件路径 | 行数 | 说明 |
|---------|------|------|
| `agent/connectors.py` | 608 | ConnectorConfig + ConnectorEvent + ConnectorManager + ConnectorHooks |
| `agent/kanban.py` | 291 | KanbanCard + KanbanColumn + KanbanBoard + KanbanManager |
| `agent/server.py` L489-502 | 14 | ConnectorHooks 注册到 AgentRuntime |
| `agent/server.py` L2293-2367 | 75 | /connectors + /connectors/reload + /kanban + /kanban/overview HTTP 端点 |
| `agent/feature_flags.py` | 不存在 | FeatureFlagsService 完全缺失 |
| `agent_config/connectors.yaml` | 不存在 | 配置文件未创建（代码支持加载，文件可选） |
| `agent_config/feature_flags.yaml` | 不存在 | 配置文件未创建 |
