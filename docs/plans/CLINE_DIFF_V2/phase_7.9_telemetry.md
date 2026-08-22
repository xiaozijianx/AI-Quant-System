# Phase 7.9 Telemetry 对比

> 对比范围：Cline `sdk/packages/core/src/services/telemetry/` + `sdk/packages/shared/src/services/telemetry*.ts` + `apps/cli/src/utils/telemetry.ts` + `sdk/packages/core/src/services/global-settings.ts` + `sdk/packages/shared/src/cron/` 的遥测/Cron 体系，与 Charles `agent/telemetry.py` + `agent/types.py`（TelemetryEventType）+ `agent/server.py`（telemetry REST API + Hooks 注册）+ `agent/runtime.py`（telemetry 字段）+ `app.py`（capture_service_activated）+ `agent/cron_*.py`（Cron 完整架构）逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段聚焦"遥测系统 + Cron 架构"维度，覆盖事件追踪 / 数据收集 / 隐私保护 / 开关 / OTLP 上报 / Cron 完整链路六个核心环节。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/services/telemetry/ITelemetryAdapter.ts`（L1-94，适配器接口：emit/emitRequired/recordCounter/recordHistogram/recordGauge/isEnabled/flush/dispose）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryAdapter.ts`（L1-348，基于 @opentelemetry/api 的实现：Meter.createCounter/Histogram/ObservableGauge + counters/histograms/gauges Map 缓存 + flattenProperties 递归展平 + 循环引用检测 + maxDepth=10 + maxArraySize=100 + 原型污染防护 + Date/Error 特殊处理）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/TelemetryLoggerSink.ts`（L1-121，转发到 BasicLogger 的 sink：emit/emitRequired/recordCounter/recordHistogram/recordGauge 全部 forward 到 logger.log/debug）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/TelemetryService.ts`（L1-139，服务层：多 adapter 派发 + capture/captureRequired/recordCounter/recordHistogram/recordGauge + buildAttributes 合并 commonProperties + metadata + distinctId + 构造器自动 push TelemetryLoggerSink）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryProvider.ts`（L1-579，Provider 工厂：MeterProvider/LoggerProvider/TracerProvider + OTLP HTTP exporters for metrics/logs/traces + console+otlp 双 exporter + PeriodicExportingMetricReader + BatchLogRecordProcessor + BatchSpanProcessor + OptedOutTelemetryService 空实现 + createConfiguredTelemetryHandle 生命周期句柄 + createConfiguredTelemetryService 工厂 + isTelemetryOptedOutGlobally 检查 + emitProviderCreated 事件）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/core-events.ts`（L1-825，CORE_TELEMETRY_EVENTS 9 分组事件枚举常量 + 30+ capture* 辅助函数 + identifyAccount + captureTelemetryOptOut + MAX_ERROR_MESSAGE_LENGTH=500 + truncateErrorMessage + normalizeErrorType/normalizeErrorMessage）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/distinct-id.ts`（L1-69，resolveCoreDistinctId：explicitDistinctId → machineIdSync（node-machine-id）→ 持久化 fallback `cl-${nanoid()}` 到 sessionDataDir/machine-id 文件）
> - `third_party/cline/sdk/packages/core/src/services/telemetry/tool-context.ts`（L1-15，getToolContextTelemetry 从 metadata 拿 ITelemetryService）
> - `third_party/cline/sdk/packages/shared/src/services/telemetry.ts`（L1-401，ITelemetryService 接口 + TelemetryMetadata + OpenTelemetryClientConfig + captureSdkError/captureTaskLifecycleEvent/captureAgentUnexpectedReasoningTokens + sanitizeTelemetryErrorMessage（Bearer/api_key/password 脱敏 + Linux/Windows 用户路径脱敏）+ truncateTelemetryString + DEFAULT_ERROR_MESSAGE_LIMIT=500 + TASK_PROVIDER_REQUEST_STARTED_EVENT 等事件常量）
> - `third_party/cline/sdk/packages/shared/src/services/telemetry-config.ts`（L1-58，createClineTelemetryServiceConfig/createClineTelemetryServiceMetadata：环境变量 OTEL_TELEMETRY_ENABLED/OTEL_METRICS_EXPORTER/OTEL_LOGS_EXPORTER/OTEL_TRACES_EXPORTER/OTEL_EXPORTER_OTLP_ENDPOINT 等 + metadata 默认值）
> - `third_party/cline/apps/cli/src/utils/telemetry.ts`（L1-142，CLI 单例：getCliTelemetryService/disposeCliTelemetryService/identifyTelemetryAccount/captureCliExtensionActivated + wasActivationCaptured 防重复 + registerDisposable）
> - `third_party/cline/sdk/packages/core/src/services/global-settings.ts`（L1-180，GlobalSettingsSchema（Zod 校验 telemetryOptOut）+ readGlobalSettings/writeGlobalSettings（持久化到 global-settings.json + mtime+size 缓存）+ isTelemetryOptedOutGlobally/setTelemetryOptOutGlobally + writeGlobalSettings 时检测 opt-out 转换调用 captureTelemetryOptOut）
> - `third_party/cline/sdk/packages/shared/src/cron/`（cron-spec-types.ts + index.ts，仅 CronSpec 类型定义：CronOneOffSpec/CronScheduleSpec/CronEventSpec + CronSpecCommonFields/CronSpecMode/CronSpecExtensionKind）
>
> Charles 源码：
> - `agent/telemetry.py`（L1-1393，单文件遥测系统：TelemetryEvent dataclass + TelemetrySink 基类 + LoggerSink/FileSink/MemorySink/OtlpHttpExporter + TelemetryService 单例 + TelemetryHooks + _redact_pii + _read_telemetry_opt_out + _sanitize_value + _truncate_preview + capture_service_activated + load_telemetry_from_yaml + get_telemetry_service/dispose_telemetry_service/set_telemetry_dir）
> - `agent/types.py` L680-767（TelemetryEventType 枚举：12 分组 24 个常量）
> - `agent/server.py` L460-475（TelemetryHooks 注册到 runtime）+ L2226-2290（三个 telemetry REST API：/telemetry/events、/telemetry/sinks、/telemetry/flush）
> - `agent/runtime.py` L295-302（`self._telemetry = config.telemetry`，仅存储未主动 capture）
> - `app.py` L281-286（启动时调用 capture_service_activated）
> - `agent/cron_materializer.py`（L1-40+，spec/job 状态持久化到 agent_config/cron_store.json，tmp.replace 原子写）
> - `agent/cron_reconciler.py`（L1-40+，定期扫描 spec 目录 + diff 已注册 job + APScheduler BlockingScheduler）
> - `agent/cron_runner.py`（L1-80+，job 执行抽象：asyncio.create_subprocess_shell + 超时控制 + stdout/stderr 截断到 10000 字符）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的遥测系统 + Cron 架构。**核心结论：Charles 的遥测系统在"事件追踪基础架构 + OTLP HTTP exporter + opt-out 开关 + PII 脱敏 + Cron 完整链路"五个维度与 Cline 高度对齐，但在"OTel SDK 集成深度 / distinctId 持久化 / 事件枚举业务覆盖 / 属性展平 / TelemetryLoggerSink metric 转发 / 配置持久化"六个维度存在显著简化。Charles 的简化是"零外部依赖 + 单进程 + 中国本地化"架构下的有意设计，并非缺陷。**

### 核心结论

1. **OpenTelemetryAdapter 实现策略根本不同**：Cline `OpenTelemetryAdapter.ts` 基于 `@opentelemetry/api` 的 Meter/Logger（L51-52 getMeter/getLogger），通过 `counters/histograms/gauges` 三个 Map 缓存 instrument 实例（L33-42），`flattenProperties` 递归展平嵌套对象为 `Record<string, primitive>`（L252-337，带 maxArraySize=100 + maxDepth=10 + 循环引用检测 + __proto__/constructor/prototype 原型污染防护 + Date/Error 特殊处理）；Charles 把 `record_counter/record_histogram/record_gauge` 直接放到 `TelemetrySink` 基类作为 no-op（L245-297），由 `OtlpHttpExporter` 子类重写为手写 OTLP JSON + aiohttp POST（L1208-1248）。**Charles 零外部 OTel 依赖，代价是缺失 OTel SDK 的 instrument 复用、属性展平、原型污染防护。**

2. **TelemetryLoggerSink metric 转发缺失**：Cline `TelemetryLoggerSink.ts` 实现完整 ITelemetryAdapter 接口，`recordCounter/recordHistogram/recordGauge` 全部 forward 到 `logger.debug("telemetry.metric", {...})`（L51-112）；Charles `LoggerSink` 仅实现 `write(event)` 写日志（L319-327），未重写 metric 方法，继承基类 no-op。**Charles 的 LoggerSink 不转发 metric 到日志，metric 仅由 OtlpHttpExporter 消费。**

3. **distinctId 持久化机制缺失**：Cline `distinct-id.ts` `resolveCoreDistinctId`（L9-21）三级回退：explicitDistinctId → `node-machine-id` 的 `machineIdSync()` → 持久化 fallback `cl-${nanoid()}` 写入 `sessionDataDir/machine-id` 文件（L43-68），保证跨会话稳定；Charles `TelemetryEvent.distinct_id` 默认 `str(uuid.uuid4())`（L198），由 `TelemetryHooks.before_run` 生成并缓存到 `_run_distinct_ids[run_id]`（L896-898），`after_run` 复用（L923），`before_tool/after_tool` 用 `tool_call_id` 作为 distinct_id（L985/L1020）。**Charles 缺失机器级 distinctId 持久化——每次进程重启都生成新 UUID，跨会话无法关联同一用户/机器。**

4. **事件枚举覆盖范围不同**：Cline `core-events.ts` `CORE_TELEMETRY_EVENTS` 9 分组（CLIENT/SESSION/AGENT/USER/TASK/HOOKS/WORKSPACE/SDK/FEATURE_FLAGS）约 40+ 事件常量（L42-106），配套 30+ capture* 辅助函数（captureExtensionActivated/captureTaskCreated/captureToolUsage/captureTokenUsage/captureCompactionExecuted/captureSubagentExecution 等）；Charles `TelemetryEventType` 12 分组 24 个枚举常量（Run/Tool/Compaction/Budget/Hook/Approval/Checkpoint/Session/Provider/MistakeTracker/LoopDetection/服务事件），仅在 `TelemetryHooks` 内触发 6 个事件（run.started/finished/failed + tool.started/finished + service.activated/opt_out）。**Cline 侧重 task/user/workspace 业务事件 + 丰富 capture* 工具函数，Charles 侧重 run/tool/compaction 系统事件 + 枚举常量化。命名风格均用点号分隔，但 namespace 不同（Cline: task/user/session；Charles: run/tool/compaction）。**

5. **OTLP exporter 覆盖差距大**：Cline `OpenTelemetryProvider.ts` 三种 exporter（metrics/logs/traces）每种支持 console+otlp 双模式（L233-336），metrics 走 `PeriodicExportingMetricReader` + `OTLPMetricExporterHttp`（L537-568），logs 走 `BatchLogRecordProcessor` + `OTLPLogExporterHttp`（L489-510），traces 走 `BatchSpanProcessor` + `OTLPTraceExporter`（L512-535），可配置 interval/timeout/batchSize/queueSize；Charles `OtlpHttpExporter` 仅 metrics（无 logs/traces），单一 otlp 模式（无 console），手写 OTLP JSON `resourceMetrics.scopeMetrics.metrics`（L1306-1321），aiohttp POST + 定期 flush loop（默认 10 秒，L1323-1328）。**Charles 缺失 logs/traces exporter + console exporter + PeriodicExportingMetricReader 自动批量上报机制。**

6. **Cron 架构 Charles 完整度高于 Cline SDK**：Cline `shared/src/cron/` 仅 `cron-spec-types.ts` 类型定义（CronSpec = CronOneOffSpec | CronScheduleSpec | CronEventSpec）+ `index.ts` 导出，无 runner/reconciler/materializer 实现（在 Cline apps 层）；Charles `agent/cron_*.py` 4 个文件完整实现：`cron_materializer.py`（状态持久化到 `agent_config/cron_store.json`，tmp.replace 原子写）+ `cron_reconciler.py`（定期扫描 spec 目录 + diff 已注册 job + APScheduler BlockingScheduler）+ `cron_runner.py`（job 执行抽象：asyncio.create_subprocess_shell + 超时控制 + stdout/stderr 截断到 10000 字符）+ cron_spec 类型。**Charles 把 Cron 三组件放在 agent 核心层，Cline SDK 仅提供 spec 类型。**

7. **隐私保护（opt-out + PII 脱敏）部分对齐**：Cline `global-settings.ts` 用 Zod schema 校验 `telemetryOptOut` 字段（L42）+ 持久化到 `global-settings.json`（L147-159）+ mtime+size 缓存（L120-141）+ `OptedOutTelemetryService` 空实现类（OpenTelemetryProvider.ts L48-111，所有方法 no-op）；Charles `_read_telemetry_opt_out` 环境变量 `AGENT_TELEMETRY_OPT_OUT` > `agent_config/telemetry.yaml` opt_out 字段（简单行解析，无 PyYAML 依赖）> 默认 False（L104-136），`TelemetryService._opted_out` 字段 + `set_opt_out` 运行时切换 + `capture` early return + `capture_required` 绕过 opt-out + `set_opt_out(True)` 时调用 `capture_required(TELEMETRY_OPT_OUT)`（L746-766）。**Charles 缺失持久化到 global-settings 文件 + OptedOutTelemetryService 空实现类（用 `_opted_out` 标志替代）。**

8. **PII 脱敏策略本地化差异**：Cline `sanitizeTelemetryErrorMessage`（shared/telemetry.ts L254-265）脱敏 Bearer token / api_key / access_token / refresh_token / authorization / password / secret + Linux `/Users/` + `/home/` + Windows `C:\Users\` 用户路径；Charles `_redact_pii`（telemetry.py L84-101）脱敏身份证（18 位）/ 手机号（1[3-9]+9 位）/ 邮箱，注释明确说明"银行卡号正则需结合字段名判断，避免误伤时间戳毫秒数等长数字"（L70-73），顺序"长模式先于短模式"避免身份证被手机号正则误吃（L75-78）。**两者覆盖的 PII 类型完全不同——Cline 侧重 API 凭证和文件路径（西方场景），Charles 侧重中国居民个人信息（身份证/手机号/邮箱）。**

9. **属性展平与原型污染防护缺失**：Cline `OpenTelemetryAdapter.flattenProperties`（L252-337）递归展平嵌套对象为 `Record<string, primitive>`，带 maxArraySize=100（数组超限截断+`_truncated`/`_original_length` 标记）+ maxDepth=10（超限返回 `[MaxDepthExceeded]`）+ WeakSet 循环引用检测（返回 `[Circular]`）+ `__proto__/constructor/prototype` 原型污染防护（L267-269 跳过）+ Date/Error 特殊处理；Charles `_sanitize_value`（L1040-1091）递归处理 dict/list，带 `id(obj)` set 循环引用检测（返回 `[Circular]`）+ 字符串 PII 脱敏 + 截断，**无展平逻辑（保持嵌套结构）、无原型污染防护、无 maxDepth/maxArraySize 限制**。

10. **nanobot 残留**：P7.9 范围内（`agent/telemetry.py` + `agent/types.py` TelemetryEventType + `agent/server.py` L460-475/L2226-2290 + `agent/runtime.py` L295-302 + `app.py` L281-286 + `agent/cron_*.py`）共 **0 处注释残留 + 0 处实现逻辑残留**。telemetry 与 cron 模块是 Charles 已完全清理的模块。PostHog 残留检查：agent 目录 0 处（Cline core-events.ts L753 注释提及 PostHog 是 downstream join 目标，Charles 未引用）。

11. **配置文件缺失**：Charles 代码引用 `agent_config/telemetry.yaml`（`_read_telemetry_opt_out` L122 + `load_telemetry_from_yaml` L1340），但 `agent_config/` 目录下无此文件。用户需手动创建才能启用 OTLP 或 opt-out。Cline 的配置走环境变量（`OTEL_TELEMETRY_ENABLED`/`OTEL_METRICS_EXPORTER` 等）+ `global-settings.json`（telemetryOptOut 字段），有完整 Zod schema 校验和跨进程 mtime 缓存。

### 一致性总体评估

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| OpenTelemetryAdapter | 中 | 语义对齐（counter/histogram/gauge 三种 instrument），实现路径不同（Cline 走 OTel SDK，Charles 走手写 OTLP JSON） |
| TelemetryLoggerSink | 低 | Cline 完整实现 ITelemetryAdapter 接口（含 metric forward），Charles LoggerSink 仅 write(event)，metric 继承 no-op |
| distinctId | 中 | 事件级 distinct_id 已对齐（before_run/after_run/before_tool/after_tool 共享），但缺失机器级持久化（跨会话稳定） |
| 事件枚举 | 中 | 命名风格对齐（点号分隔），覆盖范围不同（Cline 侧重业务事件+30+ capture* 函数，Charles 侧重系统事件+6 个触发点） |
| OTLP exporter | 低 | Cline 三种 exporter（metrics/logs/traces）+ console+otlp 双模式 + PeriodicExportingMetricReader，Charles 仅 metrics + 单 otlp + 手写 JSON |
| Cron 架构 | 高 | Charles 完整度高于 Cline SDK（Cline SDK 仅 spec 类型，Charles 含 runner/reconciler/materializer 三组件） |
| opt-out 开关 | 中 | 均支持环境变量 + 配置文件 + 运行时切换 + capture_required 绕过，Charles 缺失持久化到 global-settings + OptedOutTelemetryService 空实现类 |
| PII 脱敏 | 中 | 均有 PII 脱敏，覆盖类型不同（Cline: API 凭证+文件路径；Charles: 身份证+手机号+邮箱） |
| 属性展平 | 低 | Cline 有完整 flattenProperties（展平+maxDepth+maxArraySize+原型污染防护），Charles 保持嵌套结构，仅 PII 脱敏+截断+循环引用检测 |
| 配置可靠性 | 低 | Cline Zod 校验 + global-settings.json 持久化 + mtime 缓存，Charles 简单行解析 + 无配置文件存在 |
| REST API | 额外增强 | Charles 提供 3 个 REST API（/telemetry/events、/telemetry/sinks、/telemetry/flush），Cline SDK 未提供 |
| nanobot 残留 | 干净 | 0 处注释残留 + 0 处实现逻辑残留 |

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.9.1 | OpenTelemetryAdapter | `OpenTelemetryAdapter.ts` L24-338，基于 `@opentelemetry/api` Meter/Logger，counters/histograms/gauges Map 缓存 instrument，flattenProperties 递归展平+maxDepth=10+maxArraySize=100+原型污染防护 | `TelemetrySink` 基类 L225-305 把 metric 方法作为 no-op，`OtlpHttpExporter` L1135-1332 子类重写为手写 OTLP JSON + aiohttp POST | 中 | 语义对齐（counter/histogram/gauge），Cline 走 OTel SDK instrument 复用，Charles 走手写 OTLP JSON datapoint。Charles 缺失 instrument 缓存、属性展平、原型污染防护 |
| 7.9.2 | TelemetryLoggerSink | `TelemetryLoggerSink.ts` L19-121 完整实现 ITelemetryAdapter，emit/emitRequired forward 到 logger.log，recordCounter/recordHistogram/recordGauge forward 到 logger.debug | `LoggerSink` L308-327 仅实现 write(event) 写日志，未重写 metric 方法，继承基类 no-op | 低 | Charles 缺失 metric 到 logger 的转发。Cline 的 LoggerSink 是完整 ITelemetryAdapter，Charles 的 LoggerSink 仅事件 sink |
| 7.9.3 | distinctId | `distinct-id.ts` L9-21 `resolveCoreDistinctId`：explicitDistinctId → `node-machine-id` machineIdSync → 持久化 fallback `cl-${nanoid()}` 到 sessionDataDir/machine-id 文件 | `TelemetryEvent.distinct_id` L198 默认 `str(uuid.uuid4())`，TelemetryHooks L896-898 before_run 生成并缓存 `_run_distinct_ids[run_id]`，L923 after_run 复用，L985/L1020 before_tool/after_tool 用 tool_call_id | 中 | 事件级 distinct_id 已对齐（run/tool 前后共享），但 Charles 缺失机器级持久化——每次进程重启都生成新 UUID，跨会话无法关联同一用户/机器 |
| 7.9.4 | 事件枚举 | `core-events.ts` L42-106 `CORE_TELEMETRY_EVENTS` 9 分组（CLIENT/SESSION/AGENT/USER/TASK/HOOKS/WORKSPACE/SDK/FEATURE_FLAGS）约 40+ 事件常量 + 30+ capture* 辅助函数（captureExtensionActivated/captureTaskCreated/captureToolUsage/captureTokenUsage/captureCompactionExecuted/captureSubagentExecution/captureMistakeLimitReached 等） | `types.py` L685-767 `TelemetryEventType` 12 分组 24 个枚举常量（Run/Tool/Compaction/Budget/Hook/Approval/Checkpoint/Session/Provider/MistakeTracker/LoopDetection/服务事件），仅在 TelemetryHooks 内触发 6 个事件 | 中 | 命名风格均点号分隔，namespace 不同（Cline: task/user/session；Charles: run/tool/compaction）。Cline 侧重业务事件+丰富 capture* 函数，Charles 侧重系统事件+枚举常量化+`str, Enum` 向后兼容 |
| 7.9.5 | OTLP exporter | `OpenTelemetryProvider.ts` L233-336 三种 exporter（metrics/logs/traces）每种 console+otlp 双模式，metrics 走 PeriodicExportingMetricReader + OTLPMetricExporterHttp，logs 走 BatchLogRecordProcessor + OTLPLogExporterHttp，traces 走 BatchSpanProcessor + OTLPTraceExporter，可配置 interval/timeout/batchSize/queueSize | `OtlpHttpExporter` L1135-1332 仅 metrics（无 logs/traces），单一 otlp 模式（无 console），手写 OTLP JSON `resourceMetrics.scopeMetrics.metrics` L1306-1321，aiohttp POST + 定期 flush loop 默认 10 秒 L1323-1328 | 低 | Charles 缺失 logs/traces exporter + console exporter + PeriodicExportingMetricReader 自动批量上报。Charles 的 flush 需手动触发或依赖 start_flush_loop |
| 7.9.6 | Cron 架构 | `shared/src/cron/` 仅 `cron-spec-types.ts` 类型定义（CronSpec = CronOneOffSpec/CronScheduleSpec/CronEventSpec）+ `index.ts` 导出，无 runner/reconciler/materializer 实现 | `agent/cron_materializer.py` + `cron_reconciler.py` + `cron_runner.py` 三组件完整实现：状态持久化（tmp.replace 原子写）+ 定期扫描 spec 目录 diff（APScheduler BlockingScheduler）+ job 执行（asyncio.create_subprocess_shell + 超时控制 + stdout/stderr 截断 10000 字符） | 高 | Charles Cron 完整度高于 Cline SDK。Cline SDK 仅提供 spec 类型，具体实现在 apps 层；Charles 把三组件放在 agent 核心层 |
| 7.9.7 | opt-out 开关 | `global-settings.ts` L42 Zod 校验 telemetryOptOut + L147-159 持久化到 global-settings.json + L120-141 mtime+size 缓存 + `OpenTelemetryProvider.ts` L48-111 OptedOutTelemetryService 空实现类 + L384 `isTelemetryOptedOutGlobally` 检查 + L155-157 opt-out 转换时调用 captureTelemetryOptOut | `telemetry.py` L104-136 `_read_telemetry_opt_out`（环境变量 > yaml > 默认 False）+ L493 `_opted_out` 字段 + L558 capture early return + L564 capture_required 绕过 + L746-766 set_opt_out 运行时切换 + L760 调用 capture_required(TELEMETRY_OPT_OUT) | 中 | 均支持环境变量+配置文件+运行时切换+capture_required 绕过。Charles 缺失持久化到 global-settings 文件 + OptedOutTelemetryService 空实现类（用 _opted_out 标志替代） |
| 7.9.8 | PII 脱敏 | `shared/telemetry.ts` L254-265 `sanitizeTelemetryErrorMessage` 脱敏 Bearer token / api_key / access_token / refresh_token / authorization / password / secret + Linux /Users/ + /home/ + Windows C:\Users\ 用户路径 | `telemetry.py` L74-101 `_redact_pii` 脱敏身份证（18 位+X/x）+ 手机号（1[3-9]+9 位）+ 邮箱，L70-73 注释说明银行卡号需结合字段名判断避免误伤时间戳，L75-78 顺序"长模式先于短模式"避免身份证被手机号误吃 | 中 | 覆盖类型完全不同：Cline 侧重 API 凭证+文件路径（西方场景），Charles 侧重中国居民个人信息（身份证/手机号/邮箱）。两者互补，不冲突 |
| 7.9.9 | 属性展平 | `OpenTelemetryAdapter.ts` L252-337 `flattenProperties` 递归展平嵌套对象为 `Record<string, primitive>`，带 maxArraySize=100（截断+_truncated/_original_length 标记）+ maxDepth=10（[MaxDepthExceeded]）+ WeakSet 循环引用检测（[Circular]）+ __proto__/constructor/prototype 原型污染防护 + Date/Error 特殊处理 | `telemetry.py` L1040-1091 `_sanitize_value` 递归处理 dict/list，带 id(obj) set 循环引用检测（[Circular]）+ 字符串 PII 脱敏 + 截断，无展平逻辑、无原型污染防护、无 maxDepth/maxArraySize | 低 | Charles 保持嵌套结构（不展平），仅做 PII 脱敏+截断+循环引用检测。Cline 的展平逻辑适配 OTel attribute 必须 primitive 的约束 |
| 7.9.10 | 配置可靠性 | `global-settings.ts` Zod schema 校验 + 持久化到 global-settings.json + mtime+size 缓存 + `telemetry-config.ts` 环境变量 OTEL_TELEMETRY_ENABLED/OTEL_METRICS_EXPORTER 等完整 schema | `telemetry.py` L122-132 简单行解析（`opt_out: true` 行匹配，无 PyYAML 依赖）+ `agent_config/telemetry.yaml` 文件实际不存在 | 低 | Charles 配置文件缺失，用户需手动创建。Cline 有完整 Zod 校验 + 跨进程 mtime 缓存 + 环境变量 schema |
| 7.9.11 | 单例管理 | `apps/cli/src/utils/telemetry.ts` L22-68 `telemetrySingleton` + `getCliTelemetryService`（带 logger 延迟 attach）+ `disposeCliTelemetryService` + `registerDisposable` 自动注册 | `telemetry.py` L809-852 `_telemetry_service` + `get_telemetry_service`（默认添加 LoggerSink + FileSink）+ `dispose_telemetry_service` + `set_telemetry_dir` | 高 | 均单例 + 双重检查锁 + dispose 释放资源。Charles 额外提供 set_telemetry_dir 自定义持久化目录 |
| 7.9.12 | 服务激活事件 | `core-events.ts` L191-195 `captureExtensionActivated`（emit `user.extension_activated`）+ `apps/cli/telemetry.ts` L128-142 `captureCliExtensionActivated`（wasActivationCaptured 防重复 + identifyAccount + captureExtensionActivated） | `telemetry.py` L1099-1126 `capture_service_activated`（_activated 标志 + _activation_lock 防重复 + identify + capture_required(SERVICE_ACTIVATED)） + `app.py` L281-286 启动时调用 | 高 | 均防重复 + identify + capture_required 绕过 opt-out。Charles 用 capture_required 确保激活事件不被 opt-out 吞掉 |
| 7.9.13 | 事件捕获接口 | `TelemetryService.ts` L68-80 `capture({event, properties})` + `captureRequired(event, properties)` + `ITelemetryAdapter.emit/emitRequired` | `telemetry.py` L526-562 `capture(event, session_id, run_id, iteration, properties, distinct_id)` + L564-593 `capture_required` + L595-651 `_dispatch_event` 内部派发 | 高 | 语义等价。Charles 的 capture 签名更扁平（session_id/run_id/iteration 作为位置参数），Cline 用 properties dict 封装 |
| 7.9.14 | REST API | 无（CLI/VSCode 通过 ITelemetryService 接口直接调用） | `server.py` L2230-2290 三个 API：GET /telemetry/events（按 session_id/event_type/limit 过滤）+ GET /telemetry/sinks（列出 sink）+ POST /telemetry/flush（手动 flush） | 额外增强 | Charles 提供 REST API 供前端/运维查询事件和 sink 状态，Cline SDK 未提供 |
| 7.9.15 | Hooks 集成 | 通过 ITelemetryService 接口在 runtime 各处显式调用 capture*（core-events.ts 30+ capture* 函数） | `telemetry.py` L859-1021 `TelemetryHooks` 类（before_run/after_run/before_tool/after_tool）+ `server.py` L460-475 通过 `runtime.register_hooks` 集成 | 中 | 范式不同：Cline 在 runtime 显式调用 capture*（侵入式但精细），Charles 通过 hooks 系统路由（非侵入但事件类型有限） |
| 7.9.16 | 错误信息处理 | `shared/telemetry.ts` L223-252 `normalizeSdkError`（error_type/error_message/error_code/error_status 四字段）+ `truncateTelemetryString`（DEFAULT_ERROR_MESSAGE_LIMIT=500）+ `sanitizeTelemetryErrorMessage` | `telemetry.py` L1024-1037 `_truncate_preview`（max_chars=500 默认）+ `_sanitize_value` PII 脱敏 | 中 | 均截断到 500 字符。Cline 有结构化 error_type/code/status 四字段，Charles 仅截断+PII 脱敏 |
| 7.9.17 | identify 账户上下文 | `core-events.ts` L367-391 `identifyAccount`（setDistinctId + updateCommonProperties user_id/account_id/account_email/provider/organization_id/organization_name/member_id） | `telemetry.py` L518-524 `identify(account)`（_account dict update）+ L612-614 _dispatch_event 合并 account 到 properties | 中 | 均支持账户上下文富化。Cline 拆分 setDistinctId + updateCommonProperties，Charles 用 _account dict 统一存储 |
| 7.9.18 | metric instrument 派发 | `TelemetryService.ts` L82-119 recordCounter/recordHistogram/recordGauge 遍历 adapters 调用对应方法 + buildAttributes 合并 commonProperties+metadata+distinctId | `telemetry.py` L671-744 record_counter/record_histogram/record_gauge 遍历 sinks 调用对应方法 + opt_out 检查 | 高 | 语义等价。Charles 额外做 opt_out 检查，Cline 由 adapter 内部 enabled 标志控制 |
| 7.9.19 | tool-context 集成 | `tool-context.ts` L1-15 `getToolContextTelemetry` 从 metadata 拿 ITelemetryService（CLINE_INTERNAL_TELEMETRY_METADATA_KEY） | 无（Charles 通过 TelemetryHooks 在 runtime 层集成，不从 tool context 拿） | 缺失 | Charles 不实施 tool-context 集成。Cline 让 tool 执行时能从 context 拿 telemetry 实例自主上报 |
| 7.9.20 | 环境变量配置 | `telemetry-config.ts` L8-31 `getTelemetryBuildTimeConfig`（OTEL_TELEMETRY_ENABLED/OTEL_METRICS_EXPORTER/OTEL_LOGS_EXPORTER/OTEL_TRACES_EXPORTER/OTEL_EXPORTER_OTLP_PROTOCOL/OTEL_EXPORTER_OTLP_ENDPOINT/OTEL_METRIC_EXPORT_INTERVAL/OTEL_EXPORTER_OTLP_HEADERS） | `telemetry.py` L115-119 仅 `AGENT_TELEMETRY_OPT_OUT`（1/true/yes/on） | 低 | Charles 仅一个环境变量，Cline 完整 OTEL_* 环境变量集合 |

---

## 三、重点差距详解

### 3.1 OpenTelemetryAdapter 实现策略差距

**严重度**：P3（Charles 量化场景下不影响功能，但限制 OTel 生态集成深度）

**Cline 实现**（`OpenTelemetryAdapter.ts` L24-338）：

Cline 基于 `@opentelemetry/api` 的 Meter/Logger，通过三个 Map 缓存 instrument 实例：

```typescript
// OpenTelemetryAdapter.ts L33-42 — instrument 缓存
private counters = new Map<string, ReturnType<Meter["createCounter"]>>();
private histograms = new Map<string, ReturnType<Meter["createHistogram"]>>();
private gauges = new Map<string, ReturnType<Meter["createObservableGauge"]>>();
private gaugeValues = new Map<string, Map<string, { value: number; attributes?: TelemetryProperties }>>();

// L71-95 recordCounter — 复用 counter 实例
recordCounter(name, value, attributes, description, required = false): void {
    if (!this.meter || (!required && !this.isEnabled())) return;
    let counter = this.counters.get(name);
    if (!counter) {
        counter = this.meter.createCounter(name, description ? { description } : undefined);
        this.counters.set(name, counter);
    }
    counter.add(value, this.flattenProperties(this.buildAttributes(attributes)));
}
```

`flattenProperties`（L252-337）递归展平嵌套对象为 `Record<string, primitive>`，带 maxArraySize=100 + maxDepth=10 + WeakSet 循环引用检测 + 原型污染防护：

```typescript
// L266-269 — 原型污染防护
if (key === "__proto__" || key === "constructor" || key === "prototype") {
    continue;
}
// L278-291 — 数组截断 + _truncated 标记
if (Array.isArray(value)) {
    const limited = value.length > maxArraySize ? value.slice(0, maxArraySize) : value;
    flattened[fullKey] = JSON.stringify(limited);
    if (value.length > maxArraySize) {
        flattened[`${fullKey}_truncated`] = true;
        flattened[`${fullKey}_original_length`] = value.length;
    }
}
// L302-305 — 循环引用检测
if (seen.has(value)) {
    flattened[fullKey] = "[Circular]";
    continue;
}
// L306-308 — 最大深度检测
if (depth >= maxDepth) {
    flattened[fullKey] = "[MaxDepthExceeded]";
    continue;
}
```

**Charles 实现**（`telemetry.py` L225-305 + L1135-1332）：

Charles 把 metric 方法放到 `TelemetrySink` 基类作为 no-op，由 `OtlpHttpExporter` 子类重写：

```python
# telemetry.py L225-305 — TelemetrySink 基类 no-op metric
class TelemetrySink:
    def record_counter(self, name, value, attributes=None):
        """计数器 metric — Stage 8.6 新增，默认 no-op"""
        pass
    def record_histogram(self, name, value, attributes=None):
        pass
    def record_gauge(self, name, value, attributes=None):
        pass

# L1208-1248 — OtlpHttpExporter 重写 metric 方法
def record_counter(self, name, value, attributes=None):
    datapoint = self._build_metric_datapoint(name, value, attributes)
    with self._lock:
        self._buffer.append({
            "name": name,
            "sum": {"dataPoints": [datapoint], "aggregationTemporality": 2},
        })
```

**对比**：
- Cline 走 OTel SDK instrument 复用（counter/histogram/gauge 实例缓存，避免重复创建）
- Charles 走手写 OTLP JSON datapoint（每次调用都构造新 datapoint 写入 buffer）
- Cline 的 `flattenProperties` 适配 OTel attribute 必须 primitive 的约束
- Charles 保持嵌套结构（_sanitize_value 不展平），依赖 OTLP JSON 的嵌套对象支持
- Charles 缺失原型污染防护（`__proto__/constructor/prototype` 不跳过）和 maxDepth/maxArraySize 限制

### 3.2 distinctId 持久化机制差距

**严重度**：P2（影响跨会话用户行为分析，Charles 量化场景下可接受）

**Cline 实现**（`distinct-id.ts` L9-69）：

三级回退保证 distinctId 跨会话稳定：

```typescript
// L9-21 — 三级回退
export function resolveCoreDistinctId(explicitDistinctId?: string): string {
    const normalizedDistinctId = explicitDistinctId?.trim();
    if (normalizedDistinctId) return normalizedDistinctId;  // 1. 显式传入
    const machineDistinctId = getMachineDistinctId();
    if (machineDistinctId) return machineDistinctId;  // 2. node-machine-id
    return resolveGeneratedFallbackDistinctId();  // 3. 持久化 fallback
}

// L43-68 — 持久化 fallback 到 sessionDataDir/machine-id 文件
function resolveGeneratedFallbackDistinctId(): string {
    const distinctIdPath = resolve(sessionDataDir, "machine-id");
    if (existsSync(distinctIdPath)) {
        const saved = readFileSync(distinctIdPath, "utf8").trim();
        if (saved.length > 0) return saved;  // 读已有
    }
    const generated = `cl-${nanoid()}`;  // 生成新 ID
    mkdirSync(sessionDataDir, { recursive: true });
    writeFileSync(distinctIdPath, generated, "utf8");  // 持久化
    return generated;
}
```

**Charles 实现**（`telemetry.py` L195-198 + L884-886）：

Charles 的 distinct_id 默认 UUID v4，无持久化：

```python
# L195-198 — TelemetryEvent.distinct_id 默认 UUID
distinct_id: str = field(default_factory=lambda: str(uuid.uuid4()))

# L884-886 — TelemetryHooks 缓存 run 级 distinct_id
self._run_distinct_ids: dict[str, str] = {}

# L896-898 — before_run 生成并缓存
distinct_id = str(uuid.uuid4())
if run_id:
    self._run_distinct_ids[run_id] = distinct_id

# L923 — after_run 复用
distinct_id = self._run_distinct_ids.pop(run_id, None) or str(uuid.uuid4())
```

**对比**：
- Cline 三级回退：显式 → 机器 ID（node-machine-id） → 持久化文件（`cl-${nanoid()}` 写入 sessionDataDir/machine-id）
- Charles 单级：默认 `str(uuid.uuid4())`，无机器 ID，无持久化
- Cline 保证跨会话/跨进程 distinctId 稳定（同一机器始终相同 ID）
- Charles 每次进程重启都生成新 UUID，跨会话无法关联同一用户/机器
- Charles 的 run 级 distinct_id（before_run/after_run 共享）和 tool 级 distinct_id（tool_call_id）已对齐 Cline 的事件关联语义

### 3.3 OTLP exporter 覆盖差距

**严重度**：P2（Charles 量化场景下仅需 metrics，logs/traces 可选）

**Cline 实现**（`OpenTelemetryProvider.ts` L233-568）：

Cline 支持三种 exporter × 两种模式（console + otlp）= 6 种组合：

```typescript
// L233-269 — MeterProvider（metrics）
private createMeterProvider(resource): MeterProvider | null {
    const exporters = normalizeExporters(this.options.metricsExporter);  // ["console", "otlp"]
    const readers = exporters.map((exporter) =>
        createMetricReader(exporter, {
            endpoint: this.options.otlpEndpoint,
            headers: this.options.otlpHeaders,
            protocol: "http/json",
            interval,  // 默认 60000ms
            timeout,
        }),
    ).filter(...);
    return new MeterProvider({ resource, readers });
}

// L537-568 — OTLP metric reader
function createMetricReader(exporter, options): MetricReader | null {
    if (exporter === "console") return new PeriodicExportingMetricReader({...});
    const endpoint = ensurePathSuffix(options.endpoint, "/v1/metrics");
    return new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporterHttp({ url: endpoint, headers: options.headers }),
        exportIntervalMillis: options.interval,
        exportTimeoutMillis: options.timeout,
    });
}
```

**Charles 实现**（`telemetry.py` L1135-1332）：

Charles 仅 metrics + 单 otlp 模式：

```python
# L1135-1156 — OtlpHttpExporter 仅 metrics
class OtlpHttpExporter(TelemetrySink):
    """上报 metric 到 OTLP 兼容后端（如 OpenTelemetry Collector）"""

# L1306-1321 — 手写 OTLP JSON
def _to_otlp_json(self, batch):
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [...]
            },
            "scopeMetrics": [{
                "scope": {"name": "agent", "version": "1.0.0"},
                "metrics": batch,
            }],
        }],
    }

# L1323-1328 — 定期 flush loop
async def start_flush_loop(self):
    self._loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(self._batch_interval)  # 默认 10 秒
        await self._async_flush()
```

**对比**：
- Cline 三种 exporter（metrics/logs/traces），Charles 仅 metrics
- Cline console + otlp 双模式，Charles 单 otlp 模式
- Cline 走 OTel SDK 的 PeriodicExportingMetricReader（自动批量上报 + interval/timeout 配置），Charles 手写 flush loop
- Cline 的 BatchLogRecordProcessor + BatchSpanProcessor 支持批量+队列大小配置，Charles 无 logs/traces
- Charles 的 `load_telemetry_from_yaml`（L1340-1393）从 yaml 加载 endpoint/headers/resource_attrs/batch_interval_seconds，Cline 走环境变量 + OpenTelemetryClientConfig

### 3.4 PII 脱敏策略本地化差异

**严重度**：P3（两者互补，不冲突；Charles 中国本地化场景必需）

**Cline 实现**（`shared/telemetry.ts` L254-265）：

Cline 脱敏 API 凭证 + 文件路径（西方场景）：

```typescript
function sanitizeTelemetryErrorMessage(message: string): string {
    return message
        .replace(/(authorization=Bearer\s+)[^&\s]+/gi, "$1[redacted]")
        .replace(/(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)=([^&\s]+)/gi, "$1=[redacted]")
        .replace(/(Bearer\s+)[A-Za-z0-9._~+/-]+=*/gi, "$1[redacted]")
        .replace(/\/Users\/[^/\s]+/g, "/Users/[redacted]")
        .replace(/\/home\/[^/\s]+/g, "/home/[redacted]")
        .replace(/([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\s]+/g, "$1[redacted]");
}
```

**Charles 实现**（`telemetry.py` L74-101）：

Charles 脱敏中国居民个人信息（身份证/手机号/邮箱）：

```python
# L74-81 — PII 正则模式
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 身份证：18 位数字 + 末位 X/x（先匹配，避免被手机号正则误吃）
    (re.compile(r"\d{17}[\dXx]"), "[ID_CARD]"),
    # 手机号：1[3-9] + 9 位数字（中国大陆手机号）
    (re.compile(r"1[3-9]\d{9}"), "[PHONE]"),
    # 邮箱
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
]

# L84-101 — _redact_pii 函数
def _redact_pii(text: str) -> str:
    if not text:
        return text
    result = text
    for pattern, placeholder in _PII_PATTERNS:
        result = pattern.sub(placeholder, result)
    return result
```

**对比**：
- Cline 脱敏：API 凭证（Bearer/api_key/access_token/refresh_token/authorization/password/secret）+ Linux/Windows 用户路径
- Charles 脱敏：身份证（18 位+X/x）+ 手机号（1[3-9]+9 位）+ 邮箱
- 两者覆盖的 PII 类型完全不同，互补不冲突
- Charles 注释（L70-73）明确说明顺序敏感性：长模式（身份证 18 位）必须先于短模式（手机号 11 位），否则手机号正则会先吃掉身份证号中的 11 位连续数字子串
- Charles 的 PII 脱敏在 `_sanitize_value` 中对所有字符串值应用（L1064-1068），Cline 的 `sanitizeTelemetryErrorMessage` 仅在 `normalizeSdkError` 中对 error message 应用

### 3.5 配置文件缺失与可靠性差距

**严重度**：P2（Charles 用户需手动创建 telemetry.yaml 才能启用 OTLP/opt-out）

**Cline 实现**（`global-settings.ts` + `telemetry-config.ts`）：

Cline 有完整 Zod schema 校验 + 持久化 + 缓存：

```typescript
// global-settings.ts L40-48 — Zod schema
export const GlobalSettingsSchema = z.object({
    telemetryOptOut: z.boolean().default(false).catch(false),
    autoUpdateEnabled: z.boolean().default(true).catch(true),
    // ...
}).strip().transform(...);

// L120-141 — mtime+size 缓存
function getCachedSettings(): CachedSettings {
    const filePath = resolveGlobalSettingsPath();
    const stats = statSync(filePath, { throwIfNoEntry: false });
    const cached = settingsCache;
    if (cached && cached.path === filePath && cached.mtimeMs === mtimeMs && cached.size === size) {
        return cached;
    }
    // ...
}

// L147-159 — 持久化 + opt-out 转换检测
export function writeGlobalSettings(settings, options = {}): void {
    const previous = readGlobalSettings();
    mkdirSync(dirname(filePath), { recursive: true });
    const normalized = GlobalSettingsSchema.parse(settings);
    if (!previous.telemetryOptOut && normalized.telemetryOptOut) {
        captureTelemetryOptOut(options.telemetry);  // opt-out 转换时上报
    }
    writeFileSync(filePath, `${JSON.stringify(normalized, null, 2)}\n`, "utf8");
    invalidateSettingsCache();
}
```

**Charles 实现**（`telemetry.py` L104-136）：

Charles 简单行解析，无 PyYAML 依赖，配置文件实际不存在：

```python
# L104-136 — _read_telemetry_opt_out
def _read_telemetry_opt_out() -> bool:
    # 1. 环境变量优先
    env_val = os.environ.get("AGENT_TELEMETRY_OPT_OUT", "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        return True
    # 2. 配置文件 agent_config/telemetry.yaml
    try:
        config_path = Path("agent_config/telemetry.yaml")
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8")
            # 简单解析 opt_out: true/false 行（避免引入 PyYAML 依赖）
            for line in content.splitlines():
                if line.startswith("opt_out:"):
                    val = line.split(":", 1)[1].strip().lower()
                    return val in ("true", "yes", "1", "on")
    except Exception:
        pass
    # 3. 默认 False
    return False
```

**对比**：
- Cline：Zod schema 校验 + 持久化到 global-settings.json + mtime+size 跨进程缓存 + writeGlobalSettings 自动检测 opt-out 转换并上报
- Charles：简单行解析（`opt_out: true` 行匹配）+ 无 PyYAML 依赖 + 配置文件实际不存在
- Charles 的 `set_opt_out(value)` 方法（L746-766）支持运行时切换，但不持久化到文件（重启后从配置文件/环境变量重新读取）
- Charles 的 `load_telemetry_from_yaml`（L1340-1393）用 `yaml.safe_load` 加载 OTLP 配置，但同样依赖用户手动创建 yaml 文件

---

## 四、nanobot 残留专项检查

### 4.1 注释残留

P7.9 范围内（`agent/telemetry.py` + `agent/types.py` TelemetryEventType + `agent/server.py` L460-475/L2226-2290 + `agent/runtime.py` L295-302 + `app.py` L281-286 + `agent/cron_*.py`）grep "nanobot" 关键词：**0 处**。

telemetry 模块和 cron 模块的所有文档字符串均对标 Cline（如 telemetry.py L2 "事件追踪系统 — 对标 Cline telemetry"、L35 "apps/cli/src/utils/telemetry.ts: getCliTelemetryService"、cron_runner.py L2 "对标 Cline cron/runner.ts"），无 nanobot 注释残留。

### 4.2 实现逻辑残留

P7.9 范围内检查 nanobot 实现逻辑残留：**0 处**。

- `agent/telemetry.py`：完全基于 Cline ITelemetryService 接口设计，单例/多 sink/capture/capture_required/identify/record_counter 等均对标 Cline
- `agent/types.py` TelemetryEventType：枚举值对标 Cline CORE_TELEMETRY_EVENTS（点号分隔命名风格）
- `agent/server.py` TelemetryHooks 注册：通过 `runtime.register_hooks(AgentHooks(...))` 集成，无 nanobot 风格的 hook 机制
- `agent/cron_*.py`：对标 Cline cron/runner.ts + reconciler.ts + materializer.ts，无 nanobot 残留

### 4.3 PostHog 残留检查

agent 目录 grep "posthog/PostHog"：**0 处**。Cline core-events.ts L753 注释提及 PostHog（"downstream PostHog joins consistent"），Charles 未引用 PostHog。

---

## 五、一致性总体评估

### 5.1 已对齐项（6 项）

| # | 对比项 | 对齐程度 | 说明 |
|---|--------|---------|------|
| 7.9.1 | OpenTelemetryAdapter | 中 | counter/histogram/gauge 三种 instrument 语义对齐，Charles 用 OtlpHttpExporter 子类重写实现 |
| 7.9.3 | distinctId | 中 | 事件级 distinct_id 已对齐（run/tool 前后共享），缺失机器级持久化 |
| 7.9.6 | Cron 架构 | 高 | Charles 三组件完整实现（materializer/reconciler/runner），完整度高于 Cline SDK |
| 7.9.11 | 单例管理 | 高 | 均单例 + 双重检查锁 + dispose 释放资源 |
| 7.9.12 | 服务激活事件 | 高 | 均防重复 + identify + capture_required 绕过 opt-out |
| 7.9.13 | 事件捕获接口 | 高 | capture/capture_required 语义等价，Charles 签名更扁平 |

### 5.2 部分对齐项（5 项）

| # | 对比项 | 差距 | 影响 |
|---|--------|------|------|
| 7.9.4 | 事件枚举 | Cline 40+ 事件 + 30+ capture* 函数，Charles 24 枚举常量 + 6 触发点 | Charles 业务事件覆盖不足，但系统事件已覆盖 |
| 7.9.7 | opt-out 开关 | Charles 缺失持久化到 global-settings + OptedOutTelemetryService 空实现类 | 运行时切换不持久化，重启后从配置/环境变量重新读取 |
| 7.9.8 | PII 脱敏 | 覆盖类型不同（Cline: API 凭证+文件路径；Charles: 身份证+手机号+邮箱） | 互补不冲突，Charles 中国本地化场景必需 |
| 7.9.15 | Hooks 集成 | Cline 显式调用 capture*（侵入式但精细），Charles 通过 hooks 路由（非侵入但事件类型有限） | Charles 仅 6 个事件类型，Cline 40+ |
| 7.9.17 | identify 账户上下文 | Cline 拆分 setDistinctId + updateCommonProperties，Charles 用 _account dict 统一存储 | 语义等价，实现风格不同 |

### 5.3 缺失/简化项（6 项）

| # | 对比项 | 缺失内容 | 严重度 |
|---|--------|---------|--------|
| 7.9.2 | TelemetryLoggerSink | Charles LoggerSink 仅 write(event)，不转发 metric 到 logger | P3 |
| 7.9.5 | OTLP exporter | Charles 缺失 logs/traces exporter + console exporter + PeriodicExportingMetricReader | P2 |
| 7.9.9 | 属性展平 | Charles 无 flattenProperties，保持嵌套结构，无原型污染防护/maxDepth/maxArraySize | P3 |
| 7.9.10 | 配置可靠性 | Charles 配置文件实际不存在，简单行解析，无 Zod 校验/持久化/mtime 缓存 | P2 |
| 7.9.19 | tool-context 集成 | Charles 不实施 tool-context 集成，tool 无法从 context 拿 telemetry 自主上报 | P3 |
| 7.9.20 | 环境变量配置 | Charles 仅 AGENT_TELEMETRY_OPT_OUT，Cline 完整 OTEL_* 环境变量集合 | P3 |

### 5.4 额外增强项（2 项）

| # | 对比项 | Charles 增强 |
|---|--------|-------------|
| 7.9.14 | REST API | Charles 提供 3 个 REST API（/telemetry/events、/telemetry/sinks、/telemetry/flush）供前端/运维查询 |
| 7.9.6 | Cron 架构 | Charles 把 runner/reconciler/materializer 三组件放在 agent 核心层，Cline SDK 仅提供 spec 类型 |

---

## 六、验证方法

1. **OpenTelemetryAdapter 对齐验证**：
   - Cline: `grep -n "recordCounter\|recordHistogram\|recordGauge" third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryAdapter.ts`
   - Charles: `grep -n "record_counter\|record_histogram\|record_gauge" agent/telemetry.py`
   - 验证三种 instrument 方法签名和语义等价

2. **distinctId 持久化验证**：
   - Cline: `cat third_party/cline/sdk/packages/core/src/services/telemetry/distinct-id.ts` 检查 resolveCoreDistinctId 三级回退
   - Charles: `grep -n "distinct_id\|_run_distinct_ids" agent/telemetry.py` 检查默认 UUID + run 级缓存
   - 验证 Charles 缺失机器级持久化

3. **OTLP exporter 覆盖验证**：
   - Cline: `grep -n "OTLPMetricExporter\|OTLPLogExporter\|OTLPTraceExporter" third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryProvider.ts`
   - Charles: `grep -n "class OtlpHttpExporter\|_to_otlp_json" agent/telemetry.py`
   - 验证 Charles 仅 metrics，无 logs/traces

4. **opt-out 开关验证**：
   - Cline: `grep -n "telemetryOptOut\|isTelemetryOptedOutGlobally\|OptedOutTelemetryService" third_party/cline/sdk/packages/core/src/services/`
   - Charles: `grep -n "_opted_out\|set_opt_out\|_read_telemetry_opt_out" agent/telemetry.py`
   - 验证 Charles 缺失持久化到 global-settings

5. **PII 脱敏验证**：
   - Cline: `grep -n "sanitizeTelemetryErrorMessage" third_party/cline/sdk/packages/shared/src/services/telemetry.ts`
   - Charles: `grep -n "_redact_pii\|_PII_PATTERNS" agent/telemetry.py`
   - 验证覆盖类型不同（API 凭证 vs 身份证/手机号/邮箱）

6. **Cron 架构验证**：
   - Cline: `ls third_party/cline/sdk/packages/shared/src/cron/` 仅 spec 类型
   - Charles: `ls agent/cron_*.py` 三组件完整实现
   - 验证 Charles Cron 完整度高于 Cline SDK

7. **nanobot 残留验证**：
   - `grep -ri "nanobot" agent/telemetry.py agent/types.py agent/cron_*.py` → 0 处
   - `grep -ri "posthog" agent/` → 0 处

8. **配置文件存在性验证**：
   - `ls agent_config/telemetry.yaml` → 文件不存在
   - Charles 代码引用但实际未提供默认配置文件

---

## 七、结论

P7.9 Telemetry 对比覆盖 20 个对比项，已对齐 6 项（含 1 项高对齐），部分对齐 5 项，缺失/简化 6 项，额外增强 2 项。

**Charles 遥测系统的核心价值**：
- 单文件完整实现（TelemetryEvent + TelemetrySink 基类 + 4 个 sink 子类 + TelemetryService 单例 + TelemetryHooks + OTLP exporter + PII 脱敏 + opt-out）
- 零外部 OTel SDK 依赖，手写 OTLP JSON + aiohttp POST
- 中国本地化 PII 脱敏（身份证/手机号/邮箱）
- 通过 hooks 系统非侵入式集成到 runtime
- 提供 REST API 供前端/运维查询

**主要差距**：
- distinctId 缺失机器级持久化（跨会话无法关联同一用户/机器）
- OTLP exporter 仅 metrics（无 logs/traces）
- 事件枚举业务覆盖不足（24 枚举常量 + 6 触发点 vs Cline 40+ 事件 + 30+ capture* 函数）
- 配置文件实际不存在，用户需手动创建
- 属性展平缺失（无原型污染防护/maxDepth/maxArraySize）

**Cron 架构**：Charles 完整度高于 Cline SDK（Cline SDK 仅 spec 类型，Charles 含 runner/reconciler/materializer 三组件），是 Charles 的增强项。

**nanobot 残留**：P7.9 范围内 0 处注释残留 + 0 处实现逻辑残留，telemetry 和 cron 模块已完全清理。

**建议优先级**：
- P2: distinctId 持久化（跨会话用户关联）、OTLP logs/traces exporter（完整可观测性）、配置文件可靠性（Zod 校验 + 默认配置文件）
- P3: TelemetryLoggerSink metric 转发、属性展平 + 原型污染防护、tool-context 集成、环境变量配置扩展
