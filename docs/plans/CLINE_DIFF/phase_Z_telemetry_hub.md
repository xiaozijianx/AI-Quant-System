# Phase Z: Telemetry / Connectors / Kanban / Hub 对比报告

> 对标源码：
> - `sdk/packages/core/src/services/telemetry/`（整个目录，含 TelemetryLoggerSink / OpenTelemetryAdapter / TelemetryService / core-events / tool-context / distinct-id / OpenTelemetryProvider）
> - `apps/cli/src/connectors/`（连接器适配器：base / registry / hooks / types / adapters/{slack,discord,telegram,whatsapp,gchat,linear} / connector-host / chat-runtime / session-runtime / runtime-turn / thread-bindings / task-updates / stores）
> - `apps/cli/src/commands/kanban.ts`（外部 kanban 应用启动器）
> - `sdk/packages/core/src/hub/`（Hub 远程运行时：client / daemon / discovery / server / runtime-host）
> - `sdk/packages/core/src/cron/`（定时调度：service / runner / schedule / specs / store / events / reports）
> - `sdk/packages/core/src/services/feature-flags/FeatureFlagsService.ts`（功能开关）
> - `sdk/packages/core/src/services/global-settings.ts`（telemetry opt-out 全局开关）
> - `apps/cli/src/utils/telemetry.ts`（CLI 单例 + 激活事件）
>
> 当前实现：
> - `agent/telemetry.py`（TelemetryService + LoggerSink + FileSink + MemorySink + TelemetryHooks）
> - `agent/connectors.py`（ConnectorManager + ConnectorConfig + ConnectorHooks，shell 命令派发器）
> - `agent/kanban.py`（KanbanManager，基于 SessionState.todos 的看板视图）
> - `agent_data/telemetry/`（JSONL 持久化目录）
> - 无 Hub、无 Cron、无 FeatureFlags、无 OpenTelemetryAdapter
>
> 对比维度：Z1-Z13（共 13 个子项）

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 0 项 |
| 弱对齐 | 6 项 |
| 缺失 | 7 项 |
| 额外增强 | 1 项（Z3 内嵌的 MemorySink 查询 API） |
| **对齐度** | **约 23%** |

**核心结论**：

- 本阶段是对齐度最低的阶段之一，主要原因是 Hub / Cron / FeatureFlags 三大子系统完全缺失，且这些子系统属于"生态层"而非"核心运行时层"。
- Telemetry 核心抽象（多 sink 派发 + 全局单例 + hooks 集成）与 Cline 逻辑等价，但缺少 OpenTelemetry/OTLP 上报、metric instrument（counter/histogram/gauge）、distinctId、opt-out 隐私机制。
- Connectors 走了完全不同的设计路线：Cline 是聊天平台适配器（Slack/Discord/Telegram 等），我的实现是 shell 命令派发器。这是有意的场景适配（量化系统无需聊天平台桥接），属于"语义不等价但合理"的偏离。
- Kanban 同样走了不同路线：Cline 启动外部 npm 工具，我提供内嵌数据 API。对于 Web 应用形态的量化系统，内嵌 API 更合适。
- 量化场景真正需要的子项是 Z11（Cron 定时调度，用于定时报告/再平衡/盘后清算）和 Z13（PII 脱敏，用于合规），其余缺失项（Hub/FeatureFlags/聊天 connectors）量化场景不需要。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| Z1 | `TelemetryLoggerSink` | `TelemetryLoggerSink.ts` L19-121 | `telemetry.py` L132-173（`TelemetrySink` 基类 + `LoggerSink`） | 弱对齐 |
| Z2 | `OpenTelemetryAdapter` | `OpenTelemetryAdapter.ts` L24-338 | 无 | 缺失 |
| Z3 | `TelemetryService` | `TelemetryService.ts` L18-138 | `telemetry.py` L302-447 | 弱对齐 |
| Z4 | core-events 事件枚举 | `core-events.ts` L42-106（`CORE_TELEMETRY_EVENTS`） | `telemetry.py` L21-32（docstring 字符串列表） | 弱对齐 |
| Z5 | tool-context | `tool-context.ts` L1-15（`getToolContextTelemetry`） | 无 | 缺失 |
| Z6 | connectors 适配器 | `apps/cli/src/connectors/adapters/`（slack/discord/telegram/whatsapp/gchat/linear） | `connectors.py`（shell 命令派发器，**语义不等价**） | 弱对齐 |
| Z7 | connector 注册 | `registry.ts` L14-77（Map + lazy load） | `connectors.py` L146-247（dict + YAML 配置） | 弱对齐 |
| Z8 | Kanban 看板 | `commands/kanban.ts` L335-405（`launchKanban` 外部进程） | `kanban.py` L130-276（`KanbanManager` 内嵌数据 API，**语义不等价**） | 弱对齐 |
| Z9 | Hub client/server | `hub/client/index.ts` L292-794（`NodeHubClient` WebSocket） | 无 | 缺失 |
| Z10 | Hub daemon | `hub/daemon/index.ts` L217-489（`spawnDetachedHubServer` + `ensureDetachedHubServer`） | 无 | 缺失 |
| Z11 | Cron 调度 | `cron/service/cron-service.ts` L50-163（`CronService` + SqliteCronStore + Reconciler + Watcher + Materializer + Runner） | 无 | 缺失 |
| Z12 | `FeatureFlagsService` | `FeatureFlagsService.ts` L47-332 | 无 | 缺失 |
| Z13 | telemetry 隐私 | `global-settings.ts` L42/155-177 + `OpenTelemetryProvider.ts` L48-111（`OptedOutTelemetryService`） + `core-events.ts` L21/357-365（`captureRequired` + `captureTelemetryOptOut`） | `telemetry.py` L633-646（`_truncate_preview` 仅截断） | 缺失 |

---

## 3. 关键差距详细分析

### 差距 #Z1：TelemetryLoggerSink 缺少 metric instrument

**严重度**：P3（影响 metric 上报，量化场景暂无需求）

**Cline 实现**（`TelemetryLoggerSink.ts` L19-121）：
- 实现 `ITelemetryAdapter` 接口（`ITelemetryAdapter.ts` L32-94）
- 提供 5 类方法：`emit` / `emitRequired`（事件）、`recordCounter` / `recordHistogram` / `recordGauge`（metric instrument）
- 构造参数：`logger`、`name`、`enabled`（支持 boolean 或 `() => boolean` 函数）
- `emit` 将事件转发到 `logger.log("telemetry.event", {...})`
- `recordCounter/Histogram/Gauge` 将 metric 转发到 `logger.debug("telemetry.metric", { instrument, name, value, ... })`
- `isEnabled()` 支持运行时动态开关
- `flush()` / `dispose()` 为 async 空实现

**我的实现**（`telemetry.py` L132-173）：
- `TelemetrySink` 基类（L132-151）：仅定义 `write(event)` / `flush()` / `close()` 三个方法
- `LoggerSink`（L154-173）：仅实现 `write(event)`，将事件 `logger.log` 输出
- 无 `emitRequired`、无 `recordCounter/Histogram/Gauge`、无 `isEnabled` 动态开关
- 事件结构 `TelemetryEvent`（L88-124）与 Cline 的 `TelemetryProperties` 不同：我是强类型 dataclass，Cline 是 `Record<string, TelemetryValue>` 松散 dict

**影响**：
- 无法上报 metric（如 token 用量统计、工具耗时分布、缓存命中率等）
- 无法区分 `emit` vs `emitRequired`（影响 opt-out 语义，见 Z13）
- 量化场景当前未使用 metric instrument，实际影响有限

**修复建议**：
- 短期：在 `TelemetrySink` 基类添加 `record_counter` / `record_histogram` / `record_gauge` 空方法（默认 no-op）
- 中期：为 `LoggerSink` 实现这些方法，输出到 logger
- 长期：对齐 `ITelemetryAdapter` 接口语义

**优先级**：P3

---

### 差距 #Z2：OpenTelemetryAdapter 完全缺失

**严重度**：P2（影响 OTLP 远程上报，量化场景可选）

**Cline 实现**（`OpenTelemetryAdapter.ts` L24-338）：
- 完整的 OpenTelemetry SDK 适配器，实现 `ITelemetryAdapter` 接口
- 通过 `MeterProvider` 创建 `Meter`，支持 `createCounter` / `createHistogram` / `createObservableGauge`
- 通过 `LoggerProvider` 创建 `Logger`，`emitLog` 发送 log record
- `flattenProperties`（L252-337）：递归展平嵌套属性为 `Record<string, string|number|boolean>`
  - 处理 `null`/`undefined` → `String(value)`
  - 处理数组：超过 `maxArraySize=100` 截断并标记 `_truncated` / `_original_length`
  - 处理 `Date` → `toISOString()`
  - 处理 `Error` → `message`
  - 循环引用检测：`WeakSet` + `[Circular]` 标记
  - 最大深度 `maxDepth=10` → `[MaxDepthExceeded]`
- `buildAttributes`（L226-237）：合并 `commonProperties` + `metadata` + `properties` + `distinctId` + `_required` 标记
- `setDistinctId` / `setCommonProperties` / `updateCommonProperties` 运行时更新
- `flush` / `dispose` 调用 `meterProvider.forceFlush/shutdown` + `loggerProvider.forceFlush/shutdown`

配套的 `OpenTelemetryProvider.ts`（L148-337）：
- 创建 `MeterProvider` / `LoggerProvider` / `TracerProvider`
- 支持 `console` 和 `otlp` 两种 exporter
- OTLP HTTP exporter 配置：`endpoint` / `headers` / `insecure`
- `PeriodicExportingMetricReader` 配置 `exportIntervalMillis` / `exportTimeoutMillis`
- `BatchLogRecordProcessor` 配置 `maxQueueSize` / `maxExportBatchSize` / `scheduledDelayMillis`
- `BatchSpanProcessor` for traces
- `createConfiguredTelemetryService`（L377-400）：根据 `enabled` 和 `isTelemetryOptedOutGlobally()` 选择不同实现
- `OptedOutTelemetryService`（L48-111）：opt-out 时的 no-op 服务
- `createConfiguredTelemetryHandle`（L440-472）：统一 `flush` / `dispose` 生命周期闭包

**我的实现**：无。仅有 `LoggerSink` / `FileSink` / `MemorySink` 三个本地 sink。

**影响**：
- 无法将遥测数据上报到 OTLP 兼容后端（Jaeger / Tempo / Loki / Grafana / Datadog / Honeycomb 等）
- 无法接入企业可观测性平台
- 量化场景当前仅本地日志 + JSONL 文件，满足开发调试但不满足生产可观测性

**修复建议**：
- 短期：暂不实现，本地 sink 够用
- 中期：引入 `opentelemetry-api` + `opentelemetry-sdk` Python 包，实现 `OpenTelemetrySink`（对标 `OpenTelemetryAdapter`）
- 长期：实现 `OpenTelemetryProvider` 等价物，支持 OTLP HTTP exporter

**优先级**：P2

---

### 差距 #Z3：TelemetryService 缺少 metric 和 distinctId

**严重度**：P2（核心服务已对齐，但 metric 维度缺失）

**Cline 实现**（`TelemetryService.ts` L18-138）：
- 实现 `ITelemetryService` 接口
- `adapters: ITelemetryAdapter[]` 适配器列表
- `addAdapter(adapter)` 添加适配器
- `setDistinctId(distinctId)` / `setMetadata` / `updateMetadata` / `setCommonProperties` / `updateCommonProperties`
- `isEnabled()`：任一 adapter 启用即为启用
- `capture({ event, properties })`：构建属性后遍历 adapters 调用 `emit`
- `captureRequired(event, properties)`：调用 `emitRequired`（绕过 opt-out）
- `recordCounter` / `recordHistogram` / `recordGauge`：遍历 adapters 调用对应方法
- `buildAttributes`（L129-138）：合并 `commonProperties` + `properties` + `metadata` + `distinctId`
- `flush` / `dispose`：并发调用所有 adapter

**我的实现**（`telemetry.py` L302-447）：
- `_sinks: list[TelemetrySink]` sink 列表（内置 `MemorySink`）
- `add_sink` / `remove_sink` / `list_sinks`
- `identify(account)`：设置账户上下文（L361-368），对标 Cline `identifyAccount`
- `capture(event, session_id, run_id, iteration, properties)`：构建 `TelemetryEvent` 后遍历 sinks 调用 `write`
- `query_events(session_id, event_type, limit)`：通过 `MemorySink` 查询最近事件（**额外增强**，Cline 无此 API）
- `flush` / `close`
- `_global_metadata`（L326-330）：`cline_type` / `python_version` / `platform`，对标 Cline `metadata`
- 无 `distinctId`、无 `captureRequired`、无 `recordCounter/Histogram/Gauge`、无 `setMetadata`/`updateMetadata` 分离

**语义差异**：
| 维度 | Cline | 我 |
|------|-------|-----|
| 适配器接口 | `ITelemetryAdapter`（emit + metric） | `TelemetrySink`（仅 write） |
| 属性合并 | commonProperties + properties + metadata + distinctId | global_metadata + account + properties |
| 事件结构 | 松散 `TelemetryProperties` dict | 强类型 `TelemetryEvent` dataclass |
| 查询 API | 无 | `query_events`（通过 MemorySink） |
| metric | 支持 | 不支持 |
| opt-out | `captureRequired` 绕过 | 无 |

**影响**：
- 无法上报 metric（同 Z1）
- 无 distinctId，无法按用户/机器聚合事件
- 但 `query_events` 额外增强支持前端实时查询最近事件，Cline 无此能力

**修复建议**：
- 短期：添加 `distinct_id` 字段到 `TelemetryEvent`，`capture` 时合并
- 中期：添加 `capture_required` 方法（标记绕过 opt-out）
- 长期：扩展 `TelemetrySink` 接口支持 metric instrument

**优先级**：P2

---

### 差距 #Z4：core-events 事件枚举覆盖严重不足

**严重度**：P2（影响事件覆盖率）

**Cline 实现**（`core-events.ts` L42-106）：
`CORE_TELEMETRY_EVENTS` 常量定义 9 个命名空间、40+ 事件：
- `CLIENT.EXTENSION_ACTIVATED` = `"user.extension_activated"`
- `SESSION.STARTED` / `SESSION.ENDED`
- `AGENT.UNEXPECTED_REASONING_TOKENS`
- `USER.AUTH_STARTED/SUCCEEDED/FAILED/LOGGED_OUT/AUTH_REFRESH_SOFT_FAILURE/AUTH_RUN_RETRY/PROVIDER_CONFIGURED/TELEMETRY_OPT_OUT`
- `TASK.CREATED/RESTARTED/COMPLETED/CONVERSATION_TURN/TOKEN_USAGE/MODE_SWITCH/TOOL_USED/SKILL_USED/DIFF_EDIT_FAILED/PROVIDER_API_ERROR/MISTAKE_LIMIT_REACHED/PROVIDER_REQUEST_STARTED/PROVIDER_STREAM_STARTED/FIRST_CHUNK_RECEIVED/PROVIDER_STREAM_FAILED/CANCELLED/MENTION_USED/MENTION_FAILED/MENTION_SEARCH_RESULTS/AGENT_CREATED/AGENT_TEAM_CREATED/SUBAGENT_STARTED/SUBAGENT_COMPLETED/COMPACTION_EXECUTED/COMPACTION_SKIPPED/COMPACTION_BUDGET_EMERGENCY`
- `HOOKS.DISCOVERY_COMPLETED`
- `WORKSPACE.INITIALIZED/INIT_ERROR/PATH_RESOLVED`
- `SDK.ERROR/TOOL_TIMEOUT`
- `FEATURE_FLAGS.FLAG_CALLED`

配套 30+ capture 辅助函数：`captureExtensionActivated` / `captureTaskCreated` / `captureTokenUsage` / `captureToolUsage` / `captureCompactionExecuted` 等。

**我的实现**（`telemetry.py` L21-32 docstring）：
仅 11 个事件字符串（无枚举常量）：
- `run.started` / `run.finished` / `run.failed`
- `turn.started` / `turn.finished`
- `tool.started` / `tool.finished`
- `model.requested` / `model.responded`
- `approval.requested` / `approval.resolved`
- `service.activated`（L672）

实际在 `TelemetryHooks` 中实现的只有 5 个：`run.started` / `run.finished` / `run.failed` / `tool.started` / `tool.finished`。

**覆盖差距**：
| Cline 事件类别 | 我是否覆盖 |
|---------------|-----------|
| CLIENT/SESSION | 部分（`service.activated` ≈ `EXTENSION_ACTIVATED`） |
| USER.AUTH | 缺失（无 auth 流程） |
| TASK.* | 部分（`run.*` ≈ `TASK.CREATED/COMPLETED`） |
| TASK.TOOL_USED | 覆盖（`tool.started/finished`） |
| TASK.TOKEN_USAGE | 缺失 |
| TASK.MODE_SWITCH | 缺失 |
| TASK.SKILL_USED | 缺失 |
| TASK.COMPACTION_* | 缺失 |
| TASK.MISTAKE_LIMIT_REACHED | 缺失 |
| TASK.SUBAGENT_* | 缺失 |
| HOOKS/WORKSPACE/SDK/FEATURE_FLAGS | 缺失 |

**影响**：
- 事件覆盖率约 12%（5/40+），无法支撑完整的运行时可观测性
- 缺少 token 用量事件，无法做成本分析
- 缺少 compaction/mistake 事件，无法做稳定性分析

**修复建议**：
- 短期：在 `TelemetryHooks` 补充 `model.requested/responded`（已在 docstring 但未实现）
- 中期：添加 `TASK.TOKEN_USAGE` / `TASK.MODE_SWITCH` / `TASK.MISTAKE_LIMIT_REACHED` 事件
- 长期：定义 `CORE_TELEMETRY_EVENTS` 常量枚举，对齐 Cline 命名空间

**优先级**：P2

---

### 差距 #Z5：tool-context 缺失

**严重度**：P3（工具可通过全局单例访问 telemetry）

**Cline 实现**（`tool-context.ts` L1-15）：
- `CLINE_INTERNAL_TELEMETRY_METADATA_KEY = "__clineInternalTelemetry"`
- `getToolContextTelemetry(metadata)`：从工具执行上下文的 `metadata` 字典中提取 `ITelemetryService` 实例
- 工具执行时可通过 `ctx.metadata` 访问 telemetry 服务，无需全局单例

**我的实现**：无。工具只能通过 `from agent.telemetry import get_telemetry_service` 全局单例访问。

**影响**：
- 工具无法获取会话级 telemetry 上下文（如 session_id 绑定的 telemetry 实例）
- 全局单例模式无法支持多租户/多实例隔离
- 量化场景工具不需要直接上报 telemetry（hooks 系统已覆盖），实际影响小

**修复建议**：
- 短期：暂不实现，hooks 系统已覆盖工具事件
- 中期：在工具执行上下文添加 `telemetry` 字段，传递 `TelemetryService` 引用

**优先级**：P3

---

### 差距 #Z6：connectors 适配器语义不等价

**严重度**：P3（有意的场景适配，量化系统无需聊天平台）

**Cline 实现**（`apps/cli/src/connectors/adapters/`）：
- 6 个完整聊天平台适配器：`slack.ts` / `discord.ts` / `telegram.ts` / `whatsapp.ts` / `gchat.ts` / `linear.ts`
- 每个适配器是完整的聊天桥接器：
  - 创建 chat adapter（如 `createSlackAdapter`）
  - 启动 webhook/socket 服务器接收消息
  - 将用户消息路由到 `HubSessionClient`（通过 Hub 远程会话）
  - 流式回复到聊天线程
  - 工具审批通过聊天交互（`PendingConnectorApproval`）
  - 线程绑定（`thread-bindings.ts`）：将聊天线程绑定到 agent session
  - 任务更新中继（`task-updates.ts`）：将 agent 进度推送到聊天
  - 后台进程管理（`maybeRunInBackground`）
  - 多会话状态管理（`stores/file-state.ts` / `memory-state.ts`）

**我的实现**（`connectors.py`）：
- 完全不同的设计：**shell 命令派发器**
- `ConnectorConfig`（L79-109）：`name` / `command` / `events` / `enabled` / `is_approval`
- `ConnectorManager`（L146-247）：
  - 从 `agent_config/connectors.yaml` 加载配置
  - `dispatch_event(event, payload)`：异步并发派发事件到匹配的连接器命令
  - `authorize(payload)`：调用授权连接器做决策（allow/deny）
  - `_run_command`（L344-425）：通过 `asyncio.create_subprocess_shell` 执行命令，stdin 传 JSON payload，收集 stdout/stderr
- `ConnectorHooks`（L473-589）：将 AgentRuntime 事件路由到外部命令

**语义对比**：
| 维度 | Cline | 我 |
|------|-------|-----|
| 设计目标 | 聊天平台桥接 | 外部命令派发 |
| 适配器形式 | 代码实现（TypeScript class） | 配置驱动（YAML + shell 命令） |
| 消息流向 | 双向（接收消息 + 推送回复） | 单向（事件 → 命令） |
| 授权机制 | 聊天交互审批 | shell 命令返回 JSON 决策 |
| 会话管理 | 多会话 + 线程绑定 | 无（仅事件派发） |
| 典型用途 | Slack 机器人对话 | 工具执行前调用安全审计脚本 |

**影响**：
- 无法接入 Slack/Discord/Telegram 等聊天平台
- 但量化场景不需要聊天平台桥接（用户通过 Web UI 交互）
- shell 命令派发器更适合量化场景（如调用风控脚本、推送通知到企业微信）
- 属于"语义不等价但合理"的偏离

**修复建议**：
- 短期：保持现状，shell 命令派发器满足量化场景需求
- 中期：如需聊天平台集成，可参考 Cline 设计实现飞书/钉钉适配器
- 长期：抽象 `ConnectorBase` 接口，支持多种连接器类型（shell + chat）

**优先级**：P3

---

### 差距 #Z7：connector 注册机制不同

**严重度**：P3（注册模式已对齐，加载方式不同）

**Cline 实现**（`registry.ts` L14-77）：
- `registry: Map<string, ConnectorRegistryEntry>` 静态注册表
- 每个条目：`{ name, description, load: () => Promise<ConnectCommandDefinition> }`
- `load()` 使用动态 `import()` 懒加载适配器模块
- `listConnectors()` 返回 catalog（`catalog.ts`）
- `getConnector(name)` 按名称查找并异步加载

**我的实现**（`connectors.py` L146-247）：
- `_connectors: dict[str, ConnectorConfig]` 配置驱动注册表
- `load_config()` 从 `agent_config/connectors.yaml` 加载
- `list_connectors()` / `get_connector(name)` 同步查询
- 无懒加载（配置即数据，无需加载代码）

**语义差异**：
| 维度 | Cline | 我 |
|------|-------|-----|
| 注册来源 | 代码静态注册 | YAML 配置文件 |
| 加载方式 | 异步动态 import | 同步字典查找 |
| 适配器形式 | `ConnectCommandDefinition`（run/showHelp/stopAll） | `ConnectorConfig`（command + events） |
| catalog | 独立 catalog.ts | 无 |

**影响**：
- 无法支持复杂的适配器生命周期（如 `stopAll` 停止所有会话）
- 但配置驱动更灵活（用户无需写代码即可添加连接器）
- 量化场景连接器简单（shell 命令），配置驱动足够

**修复建议**：
- 短期：保持现状
- 中期：添加 `catalog` 等价物，内置常用连接器模板

**优先级**：P3

---

### 差距 #Z8：Kanban 看板实现方式不同

**严重度**：P3（语义不等价但合理，Web 应用形态更适合内嵌 API）

**Cline 实现**（`commands/kanban.ts` L335-405）：
- `launchKanban(options)`：启动外部 `kanban` npm 工具作为前台子进程
- `ensureKanbanInstalled(command)`：检测 `kanban` 命令是否存在，不存在则自动安装
  - 支持 `npm` / `pnpm` / `bun` 三种包管理器
  - `resolveKanbanInstallCommand` 按优先级选择可用的包管理器
- `spawnKanbanProcess`：`spawn(getKanbanCommand(), [], buildKanbanSpawnOptions())`
  - Windows: `kanban.cmd` + `shell: true`
  - Unix: `kanban` + `detached: true`
  - `windowsHide: true` 防止 Windows 控制台窗口闪烁
- 信号转发：`forwardSignalToKanbanProcess` 将 SIGINT/SIGTERM 转发到子进程
- 关闭超时：`KANBAN_SHUTDOWN_TIMEOUT_MS = 10_000`，超时后 SIGKILL
- `.kanban/config.json`：快捷方式配置（如 "Build & Link CLI"）

**我的实现**（`kanban.py` L130-276）：
- `KanbanManager`：基于 `SessionState.todos` 构建看板视图的内存数据 API
- `get_board(session_id)`：实时构建 `KanbanBoard`（3 列：待办/进行中/已完成）
- `get_progress(session_id)`：进度统计（total/pending/in_progress/completed/completion_rate）
- `get_overview()`：跨会话聚合看板摘要
- 不启动外部进程，不维护独立任务状态（单一数据源 `SessionState.todos`）
- 通过 `/api/chat/kanban` 端点暴露给前端

**语义对比**：
| 维度 | Cline | 我 |
|------|-------|-----|
| 形态 | 外部 CLI 工具 | 内嵌数据 API |
| 数据源 | kanban 工具自管理 | `SessionState.todos`（单一数据源） |
| 进程模型 | 前台子进程 | 无（同进程） |
| 安装 | 自动安装 npm 包 | 无需安装 |
| 信号处理 | SIGINT/SIGTERM 转发 | 无 |
| 跨会话 | 不支持 | `get_overview` 聚合所有会话 |

**影响**：
- 无外部 kanban 工具的完整功能（如拖拽排序、多看板）
- 但内嵌 API 更适合 Web 应用形态，前端可自定义渲染
- 单一数据源（`SessionState.todos`）避免数据冗余，与 TodoWrite 工具自动联动
- `get_overview` 是**额外增强**，Cline 外部工具无法聚合多会话

**修复建议**：
- 短期：保持现状，内嵌 API 更适合量化 Web 应用
- 中期：添加任务排序、优先级字段
- 长期：考虑 WebSocket 实时推送看板变更

**优先级**：P3

---

### 差距 #Z9：Hub client/server 完全缺失

**严重度**：P3（量化场景不需要远程会话）

**Cline 实现**（`hub/client/index.ts` L292-794 + `hub/server/`）：
- `NodeHubClient`：WebSocket 客户端
  - `connect()`：建立 WebSocket 连接，超时 8s，支持 auth token（子协议头）
  - `command(command, payload, sessionId, options)`：发送命令，等待 reply，支持超时
  - `subscribe(listener, { sessionId })`：订阅事件流，支持按 session 过滤
  - 自动重连：指数退避（250ms ~ 5000ms）+ 50% 抖动
  - 本地 Hub 故障恢复：`recoverLocalHubTransport` 检测并重启 Hub
  - `client.register` / `client.unregister` 注册/注销
  - `stream.subscribe` / `stream.unsubscribe` 订阅管理
- Hub Server（`hub/server/`）：
  - WebSocket 服务器（`hub-websocket-server.ts`）
  - 多种传输：`native-transport` / `browser-websocket` / `command-transport`
  - Handler 分发：`session-handlers` / `approval-handlers` / `run-handlers` / `capability-handlers` / `client-handlers` / `connector-handlers`
  - 会话事件投影（`session-event-projector.ts`）
  - Hub 通知（`hub-notifications.ts`）+ 调度事件（`hub-schedule-events.ts`）
- 用途：多客户端共享一个 agent 运行时（如 VS Code + CLI + 移动端同时连接）

**我的实现**：无。

**影响**：
- 无法支持多客户端远程连接
- 无法支持 detached 后台运行时
- 量化场景为单用户 Web 应用，不需要多客户端共享运行时

**修复建议**：
- 短期：暂不实现
- 中期：如需远程访问，可基于 FastAPI WebSocket 实现简化版 Hub
- 长期：暂无需求

**优先级**：P3

---

### 差距 #Z10：Hub daemon 完全缺失

**严重度**：P3（依赖 Z9，量化场景不需要）

**Cline 实现**（`hub/daemon/index.ts` L217-489）：
- `spawnDetachedHubServer(workspaceRoot, endpoint)`：spawn detached 子进程运行 Hub daemon
  - `detached: true` + `child.unref()` 使 daemon 独立于父进程
  - `windowsHide: true` 防止 Windows 控制台窗口
  - 日志重定向到 `~/.cline/logs/hub-daemon.log`
  - 环境变量 `CLINE_RUN_AS_HUB_DAEMON=1` 标记 daemon 进程
- `spawnDetachedHubServerWithRetry`：ETXTBSY 错误重试（100/250/500/1000/2000ms）
- `ensureDetachedHubServer`：完整的 daemon 启动流程
  - 检查 discovery 记录
  - 探测已运行 Hub 是否兼容（`isHubProtocolCompatible`）
  - 退休不兼容的 Hub（`retireIncompatibleHub`）
  - 启动新 daemon 并等待 discovery 记录出现（8s 超时）
- `prewarmDetachedHubServer`：预热 daemon
- `retireLegacySharedHub`：清理旧版本遗留 daemon

**我的实现**：无。

**影响**：
- 无后台 daemon 进程，agent 运行时仅在 Web 服务器进程内
- 量化场景不需要 detached daemon

**修复建议**：
- 短期：暂不实现
- 中期：依赖 Z9，如需 Hub 再考虑 daemon

**优先级**：P3

---

### 差距 #Z11：Cron 调度完全缺失

**严重度**：P2（量化场景可能需要定时任务）

**Cline 实现**（`cron/service/cron-service.ts` L50-163 + 整个 `cron/` 目录）：
- `CronService`：顶层调度器，组装 5 个组件：
  1. `SqliteCronStore`（`store/sqlite-cron-store.ts`）：SQLite 持久化（cron.db），存储 spec / run / event log
  2. `CronReconciler`（`specs/cron-reconciler.ts`）：磁盘 → DB 同步（cron spec 文件 → DB 记录）
  3. `CronWatcher`（`specs/cron-watcher.ts`）：文件系统监听（debounce），spec 变更自动 reconcile
  4. `CronMaterializer`（`runner/cron-materializer.ts`）：队列物化（将 spec 按时间表生成 run 记录）
  5. `CronRunner`（`runner/cron-runner.ts`）：claim + execute + report（租约 + 并发控制）
- API：
  - `start()` / `stop()` / `dispose()`：生命周期
  - `listSpecs` / `getSpec`：查询调度规格
  - `listRuns` / `getRun` / `listActiveRuns` / `listUpcomingRuns`：查询运行记录
  - `reconcileNow()`：手动触发同步
  - `ingestEvent(event)`：事件驱动触发（`CronEventIngress`）
  - `listEventLogs` / `getEventLog`：事件日志
- 子模块：
  - `schedule/scheduler.ts`：调度算法
  - `schedule/schedule-service.ts`：编程式调度 API（`HubScheduleService`）
  - `runner/resource-limiter.ts`：资源限流（`globalMaxConcurrency`）
  - `reports/cron-report-writer.ts`：运行报告
  - `events/cron-event-ingress.ts`：事件入口（外部事件触发 cron）
- 配置：`workspaceRoot` / `specs`（cron spec 目录）/ `dbPath` / `pollIntervalMs` / `claimLeaseSeconds` / `globalMaxConcurrency` / `watcherDebounceMs`

**我的实现**：无。

**影响**：
- 无法定时执行任务（如每日盘前数据预加载、定时生成研究报告、周期性再平衡）
- 无法基于事件触发任务（如市场异动触发风控检查）
- 量化场景**可能需要** Cron（见第 7 节评估）

**修复建议**：
- 短期：使用外部调度器（如 cron / Windows Task Scheduler / APScheduler）调用 agent API
- 中期：实现简化版 `CronService`，基于 `APScheduler` 库，支持 file-based spec + SQLite 持久化
- 长期：对齐 Cline 的 reconcile + watch + materialize + run 架构

**优先级**：P2

---

### 差距 #Z12：FeatureFlagsService 完全缺失

**严重度**：P3（量化场景不需要远程功能开关）

**Cline 实现**（`FeatureFlagsService.ts` L47-332）：
- `FeatureFlagsService`：功能开关服务
  - `provider: IFeatureFlagsProvider`：开关数据源抽象（PostHog 实现 in `posthog.ts`）
  - `poll(userId)`：TTL 轮询（默认 1 小时），从 provider 拉取所有 flag
  - `getBooleanFlagEnabled(flagName)`：查询布尔开关
  - `getFlagPayload(flagName)`：查询开关 payload
  - 持久化缓存：`cacheFilePath` 文件缓存（7 天最大年龄）
  - `hydrateFromPersistentCache()`：启动时从磁盘恢复
  - `writePersistentCache()`：轮询后写入磁盘
  - 上下文：`setContext({ userId, ... })`
  - 遥测集成：flag 变更时触发 `$feature_flag_called` 事件
  - `test(flagName, value)`：测试模式覆盖
- 配套：`FEATURE_FLAGS` 常量列表 + `FeatureFlagDefaultValue` 默认值表

**我的实现**：无。

**影响**：
- 无法远程控制功能开关（如灰度发布、A/B 测试）
- 量化场景为单租户系统，功能开关通过配置文件管理即可

**修复建议**：
- 短期：暂不实现
- 中期：如需灰度发布，可基于 `agent_config/feature_flags.yaml` 实现简化版
- 长期：暂无需求

**优先级**：P3

---

### 差距 #Z13：telemetry 隐私机制缺失

**严重度**：P2（影响合规，量化场景处理金融数据需重视隐私）

**Cline 实现**：
1. **全局 opt-out 开关**（`global-settings.ts` L42/155-177）：
   - `telemetryOptOut: boolean` 持久化到 `~/.cline/settings.json`
   - `isTelemetryOptedOutGlobally()` 查询
   - `setTelemetryOptOutGlobally(value)` 设置（false→true 时自动触发 `captureTelemetryOptOut`）
   - `writeGlobalSettings` 检测 `!previous.telemetryOptOut && normalized.telemetryOptOut` 发送 opt-out 事件

2. **OptedOutTelemetryService**（`OpenTelemetryProvider.ts` L48-111）：
   - opt-out 时返回的 no-op 服务
   - `isEnabled()` 返回 `false`
   - `capture` / `captureRequired` 仅构建属性但不发送
   - `recordCounter` / `recordHistogram` / `recordGauge` 完全 no-op
   - `flush` / `dispose` no-op
   - 但仍保留 `setDistinctId` / `setMetadata` / `setCommonProperties`（为恢复 opt-in 准备）

3. **captureRequired 语义**（`TelemetryService.ts` L75-80 + `core-events.ts` L357-365）：
   - `capture(event, properties)`：普通事件，opt-out 时被 `OptedOutTelemetryService` 吞掉
   - `captureRequired(event, properties)`：必需事件，绕过 opt-out（如 `user.opt_out` 确认事件本身）
   - `TelemetryLoggerSink.emitRequired`（L42-49）：使用 `severity: "warn"` 标记

4. **错误消息截断**（`core-events.ts` L21/166-171）：
   - `MAX_ERROR_MESSAGE_LENGTH = 500`
   - `truncateErrorMessage(errorMessage)` 截断到 500 字符

5. **属性展平安全**（`OpenTelemetryAdapter.ts` L252-337）：
   - 循环引用检测：`WeakSet` + `[Circular]` 标记
   - 最大深度 `maxDepth=10` → `[MaxDepthExceeded]`
   - 数组截断：`maxArraySize=100` + `_truncated` / `_original_length` 标记
   - `__proto__` / `constructor` / `prototype` 键过滤（防原型污染）

6. **undefined 属性清理**（`core-events.ts` L573-581）：
   - `stripUndefinedProperties` 移除值为 `undefined` 的属性

**我的实现**（`telemetry.py`）：
1. **无 opt-out 机制**：无全局开关，无 `isTelemetryOptedOutGlobally`，无 `OptedOutTelemetryService`
2. **无 captureRequired**：所有事件走同一个 `capture`，无绕过机制
3. **截断**（L633-646）：`_truncate_preview(value, max_chars=500)` 仅截断工具输入/输出预览，不截断错误消息
4. **无循环引用检测**：`json.dumps` 默认会抛 `ValueError` on circular reference
5. **无原型污染防护**：Python 不存在此问题（无原型链）
6. **无 undefined 清理**：Python 用 `None`，`json.dumps` 会输出 `null`（非严格等价但可接受）

**影响**：
- 用户无法 opt-out 遥测（合规风险，GDPR/CCPA 要求）
- 错误消息可能包含敏感信息（如 API key、用户数据）且无长度限制
- 循环引用会导致 `json.dumps` 抛异常（虽然 `TelemetryService.capture` 的 try/except 会吞掉，但事件丢失）
- 量化场景处理金融数据，PII 脱敏尤为重要

**修复建议**：
- 短期（P1）：
  1. 在 `agent_config/` 添加 `telemetry_opt_out` 配置项
  2. `TelemetryService.capture` 检查 opt-out 标志，opt-out 时直接返回
  3. 添加 `capture_required` 方法（绕过 opt-out）
  4. `_truncate_preview` 扩展为通用 `_sanitize_value`，对所有字符串属性截断到 500 字符
- 中期：
  5. 添加 PII 脱敏正则（手机号、邮箱、身份证、银行卡号）
  6. `json.dumps` 添加 `default=str` 防止序列化异常
- 长期：
  7. 实现循环引用检测（基于 `seen` set）

**优先级**：P2（短期修复项为 P1）

---

## 4. 一致性统计

### 按一致性等级分布

| 等级 | 数量 | 子项 |
|------|------|------|
| 完全一致 | 0 | — |
| 弱对齐 | 6 | Z1, Z3, Z4, Z6, Z7, Z8 |
| 缺失 | 7 | Z2, Z5, Z9, Z10, Z11, Z12, Z13 |
| 额外增强 | 1 | Z3 内嵌 `query_events` API（MemorySink） |

### 按严重度分布

| 严重度 | 数量 | 子项 |
|--------|------|------|
| P1 | 0（Z13 短期修复项为 P1，整体为 P2） | — |
| P2 | 4 | Z2, Z3, Z4, Z11, Z13 |
| P3 | 8 | Z1, Z5, Z6, Z7, Z8, Z9, Z10, Z12 |

### 对齐度计算

- 完全一致：0 × 1.0 = 0.0
- 弱对齐：6 × 0.5 = 3.0
- 缺失：7 × 0.0 = 0.0
- 额外增强：1 × 0.5 = 0.5（合理增强，不扣分但也不计为一致）
- **对齐度 = (0.0 + 3.0 + 0.5) / 13 ≈ 27%**

---

## 5. 修复建议

### 短期（P1/P2，影响合规与核心可观测性）

1. **Z13 telemetry opt-out**（P1 短期项）：
   - 在 `agent_config/` 添加 `telemetry_opt_out` 配置
   - `TelemetryService.capture` 检查 opt-out 标志
   - 添加 `capture_required` 方法
   - 扩展 `_truncate_preview` 为通用属性截断

2. **Z4 事件枚举补充**：
   - 在 `TelemetryHooks` 实现 `model.requested/responded`（已在 docstring）
   - 添加 `task.token_usage` 事件（对标 `captureTokenUsage`）
   - 定义 `CORE_TELEMETRY_EVENTS` 常量枚举

3. **Z3 distinctId 支持**：
   - `TelemetryEvent` 添加 `distinct_id` 字段
   - `capture` 时从 `_account` 提取 distinct_id

### 中期（P2，提升可观测性与调度能力）

1. **Z2 OpenTelemetryAdapter**：
   - 引入 `opentelemetry-api` + `opentelemetry-sdk`
   - 实现 `OpenTelemetrySink`，支持 OTLP HTTP exporter
   - 实现 `flattenProperties` 等价物（循环引用 + 深度限制）

2. **Z11 Cron 调度**：
   - 引入 `APScheduler` 库
   - 实现简化版 `CronService`，支持 file-based spec + SQLite 持久化
   - 量化场景典型用途：每日盘前数据预加载、定时研究报告、周期性再平衡

3. **Z13 PII 脱敏**：
   - 添加 PII 正则脱敏（手机号、邮箱、身份证、银行卡号）
   - `json.dumps` 添加 `default=str` 防止序列化异常

### 长期（P3，生态扩展）

1. **Z1 metric instrument**：扩展 `TelemetrySink` 接口支持 counter/histogram/gauge
2. **Z5 tool-context**：工具执行上下文添加 `telemetry` 字段
3. **Z6/Z7 聊天平台适配器**：如需聊天平台集成，参考 Cline 设计实现飞书/钉钉适配器
4. **Z8 Kanban 增强**：任务排序、优先级、WebSocket 实时推送
5. **Z9/Z10 Hub**：如需远程访问，基于 FastAPI WebSocket 实现简化版
6. **Z12 FeatureFlags**：如需灰度发布，基于 YAML 配置实现简化版

---

## 6. 验证记录

### 已读取的对标文件

**我的实现**：
- `e:\jikeAI\code\CASE-AI量化系统\agent\telemetry.py`（678 行，完整读取）
- `e:\jikeAI\code\CASE-AI量化系统\agent\connectors.py`（608 行，完整读取）
- `e:\jikeAI\code\CASE-AI量化系统\agent\kanban.py`（291 行，完整读取）
- `e:\jikeAI\code\CASE-AI量化系统\agent_data\telemetry\telemetry_20260724.jsonl`（存在，验证 FileSink 工作）

**Cline 源码**：
- `sdk/packages/core/src/services/telemetry/TelemetryLoggerSink.ts`（121 行，完整读取）
- `sdk/packages/core/src/services/telemetry/OpenTelemetryAdapter.ts`（338 行，完整读取）
- `sdk/packages/core/src/services/telemetry/TelemetryService.ts`（138 行，完整读取）
- `sdk/packages/core/src/services/telemetry/core-events.ts`（825 行，完整读取）
- `sdk/packages/core/src/services/telemetry/tool-context.ts`（15 行，完整读取）
- `sdk/packages/core/src/services/telemetry/ITelemetryAdapter.ts`（94 行，完整读取）
- `sdk/packages/core/src/services/telemetry/OpenTelemetryProvider.ts`（579 行，完整读取）
- `sdk/packages/core/src/services/telemetry/distinct-id.ts`（69 行，完整读取）
- `sdk/packages/core/src/services/telemetry/index.ts`（22 行，完整读取）
- `sdk/packages/core/src/services/feature-flags/FeatureFlagsService.ts`（332 行，完整读取）
- `sdk/packages/core/src/services/global-settings.ts`（347 行，完整读取）
- `apps/cli/src/connectors/base.ts`（235 行，完整读取）
- `apps/cli/src/connectors/registry.ts`（77 行，完整读取）
- `apps/cli/src/connectors/hooks.ts`（143 行，完整读取）
- `apps/cli/src/connectors/types.ts`（17 行，完整读取）
- `apps/cli/src/connectors/connector-host.ts`（120 行，部分读取）
- `apps/cli/src/connectors/adapters/slack.ts`（100 行，部分读取）
- `apps/cli/src/commands/kanban.ts`（405 行，完整读取）
- `apps/cli/src/utils/telemetry.ts`（142 行，完整读取）
- `sdk/packages/core/src/hub/client/index.ts`（1100 行，完整读取）
- `sdk/packages/core/src/hub/daemon/index.ts`（489 行，完整读取）
- `sdk/packages/core/src/hub/server/index.ts`（5 行，完整读取）
- `sdk/packages/core/src/hub/index.ts`（37 行，完整读取）
- `sdk/packages/core/src/cron/service/cron-service.ts`（163 行，完整读取）
- `sdk/packages/core/src/cron/index.ts`（7 行，完整读取）
- `.kanban/config.json`（9 行，完整读取）

### 集成验证

- `agent/server.py` L449-464：确认 `TelemetryHooks` 已注册到 AgentRuntime（before_run/after_run/before_tool/after_tool）
- `agent/server.py` L478-487：确认 `ConnectorHooks` 已注册（含 before_approval）
- `agent/server.py` L1534/1556/1570：确认 telemetry 查询 API 已暴露
- `agent/server.py` L1627/1647/1667：确认 kanban API 已暴露

---

## 7. 量化场景适用性评估

### 量化场景需要的功能

| 子项 | 是否需要 | 理由 | 优先级 |
|------|---------|------|--------|
| Z1 LoggerSink metric | 不需要 | 量化场景暂无 metric 上报需求，日志 + 事件够用 | P3 |
| Z2 OpenTelemetryAdapter | 可选 | 生产部署时接入可观测性平台有价值，但当前本地 sink 够用 | P2 |
| Z3 TelemetryService | 需要（已实现核心） | 核心服务已对齐，distinctId/metric 可后续补充 | P2 |
| Z4 core-events 事件 | 部分需要 | run/tool 事件已覆盖核心，token_usage/mistake_limit 有价值 | P2 |
| Z5 tool-context | 不需要 | hooks 系统已覆盖工具事件，工具无需直接上报 | P3 |
| Z6 聊天平台 connectors | 不需要 | 量化系统通过 Web UI 交互，无需 Slack/Discord 桥接 | P3 |
| Z7 connector 注册 | 不需要（已实现） | 配置驱动的 shell 命令派发器满足量化场景 | P3 |
| Z8 Kanban | 需要（已实现） | 任务进度可视化对量化研究/交易流程有价值，内嵌 API 更适合 Web 应用 | P3 |
| Z9 Hub client/server | 不需要 | 单用户 Web 应用，不需要多客户端共享运行时 | P3 |
| Z10 Hub daemon | 不需要 | 依赖 Z9，无需 detached daemon | P3 |
| **Z11 Cron 调度** | **需要** | **量化场景典型用途**：每日盘前数据预加载、定时生成研究报告、周期性投资组合再平衡、盘后 P&L 汇总、定时风控检查 | **P2** |
| Z12 FeatureFlags | 不需要 | 单租户系统，配置文件管理功能开关即可 | P3 |
| **Z13 telemetry 隐私** | **需要** | **量化场景处理金融数据**，PII 脱敏与 opt-out 是合规要求（GDPR/CCPA/个人信息保护法） | **P2（短期 P1）** |

### 量化场景典型 Cron 用例

1. **每日盘前数据预加载**（08:30）：定时拉取行情数据、新闻、公告，预处理后存入向量库
2. **定时研究报告生成**（盘后 16:00）：调用 agent 生成每日市场分析报告
3. **周期性投资组合再平衡**（每周一 09:00）：根据策略信号调整持仓
4. **盘后 P&L 汇总**（每日 16:30）：计算当日盈亏、风险指标，推送通知
5. **定时风控检查**（盘中每小时）：检查持仓集中度、回撤、波动率，触发预警

### 结论

Phase Z 的 13 个子项中，量化场景**真正需要**的只有 3 项：
- Z3 TelemetryService（已实现核心，需补充 distinctId）
- Z11 Cron 调度（完全缺失，需实现）
- Z13 telemetry 隐私（完全缺失，需实现 opt-out + PII 脱敏）

其余 10 项要么已实现核心（Z1/Z4/Z7/Z8），要么量化场景不需要（Z2/Z5/Z6/Z9/Z10/Z12）。

**建议优先级**：
1. **立即修复**：Z13 隐私机制（合规风险）
2. **近期实现**：Z11 Cron 调度（量化场景核心需求）
3. **中期补充**：Z4 事件枚举 + Z3 distinctId（提升可观测性）
4. **暂缓实现**：Z2/Z5/Z6/Z9/Z10/Z12（量化场景不需要或已有替代方案）

---

**阶段 Z 结论**：对齐度约 27%，是所有阶段中最低的之一。主要原因是大面积的"生态层"子系统缺失（Hub/Cron/FeatureFlags/聊天 connectors）。但这些缺失项中绝大多数（10/13）量化场景不需要或已有合理替代方案。真正需要补齐的是 Z13（隐私合规）和 Z11（定时调度），以及 Z3/Z4 的部分增强（distinctId + 事件覆盖）。Telemetry 核心抽象（多 sink 派发 + hooks 集成 + JSONL 持久化）与 Cline 逻辑等价，Connectors 和 Kanban 走了不同的设计路线但适合 Web 应用形态的量化系统。
