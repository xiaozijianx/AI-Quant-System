# Stage 14: P2 遥测与调度补全方案

> 生成时间：2026-07-26
> 优先级：P2
> 预估工作量：1 周
> 依赖：无（基于 Stage 8 已完成的 TelemetrySink 接口和 Cron spec 加载）
>
> 来源：
> - `CLINE_DIFF/SUMMARY_v2.md` §3.2 P2 级剩余差距 #14-#16
> - `CLINE_DIFF/phase_Z_telemetry_hub.md`（Z2 / Z3 / Z4 / Z11）
>
> 涉及源文件：
> - 我的：`agent/telemetry.py`、`scheduler.py`、`agent/types.py`、`agent/server.py`
> - Cline：`third_party/cline/sdk/packages/core/src/services/telemetry/`、`third_party/cline/sdk/packages/core/src/services/scheduler/`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 14.1 | OTLP exporter 完整实现 | Z2 | P2 | agent/telemetry.py、agent_config/telemetry.yaml |
| 14.2 | Cron 完整架构（reconcile/materializer/runner） | Z11 | P2 | scheduler.py、agent/persistence/cron_store.py |
| 14.3 | distinctId + 事件枚举覆盖率 | Z3 / Z4 | P2 | agent/telemetry.py、agent/types.py |

依赖关系：
- 14.1 / 14.2 / 14.3 互相独立，可并行
- 建议执行顺序：14.3 → 14.1 → 14.2

---

## 14.1 OTLP exporter 完整实现（Z2）

### 任务背景

来源 Phase Z #Z2。Stage 8.6 已为 `TelemetrySink` 增加 `record_counter` / `record_histogram` / `record_gauge` 接口（no-op 默认实现），但**未实现 OTLP exporter**：
- 当前所有 metric 调用都是 no-op，数据丢弃
- 用户无法将遥测数据上报到 Prometheus / Jaeger / Grafana 等后端
- 量化场景下，用户希望监控 agent 的 token 消耗、工具调用频率、压缩触发次数等

Cline 的 `telemetry-exporters.ts` 中实现了 `OtlpHttpExporter`，通过 HTTP POST 上报到 OTLP 兼容后端。

### 目标

实现 OTLP HTTP exporter：
1. 新增 `OtlpHttpExporter` 类，实现 `TelemetrySink` 接口
2. 通过 `agent_config/telemetry.yaml` 配置 endpoint / headers / 资源属性
3. metric 数据按 OTLP/Protobuf 格式序列化
4. 定期批量上报（默认 10 秒一次）

### 当前实现位置

- `agent/telemetry.py`（`TelemetrySink` 抽象类、`TelemetryService`）
- `agent_config/`（无 telemetry 配置文件，需新增）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/exporters/otlp-http-exporter.ts`
- Cline `telemetry-exporters.ts`（`OtlpHttpExporter` 类）

### 修复步骤建议

1. **新增 `OtlpHttpExporter` 类**
   - 在 `agent/telemetry.py` 中新增：
     ```python
     class OtlpHttpExporter(TelemetrySink):
         """OTLP HTTP exporter，上报 metric 到 OTLP 兼容后端"""

         def __init__(self, endpoint: str, headers: dict[str, str] | None = None,
                      resource_attrs: dict[str, str] | None = None,
                      batch_interval_seconds: float = 10.0):
             self.name = "otlp_http"
             self._endpoint = endpoint
             self._headers = headers or {}
             self._resource_attrs = resource_attrs or {}
             self._batch_interval = batch_interval_seconds
             self._buffer: list[dict] = []
             self._lock = asyncio.Lock()
             self._flush_task: asyncio.Task | None = None

         async def _start(self) -> None:
             """启动定期 flush 任务"""
             self._flush_task = asyncio.create_task(self._flush_loop())

         async def _flush_loop(self) -> None:
             while True:
                 await asyncio.sleep(self._batch_interval)
                 await self._flush()

         async def _flush(self) -> None:
             """批量上报缓冲区数据"""
             async with self._lock:
                 if not self._buffer:
                     return
                 batch = self._buffer[:]
                 self._buffer.clear()
             # 转换为 OTLP JSON 格式
             payload = self._to_otlp_json(batch)
             try:
                 async with aiohttp.ClientSession() as session:
                     async with session.post(
                         self._endpoint,
                         json=payload,
                         headers=self._headers,
                         timeout=aiohttp.ClientTimeout(total=30),
                     ) as resp:
                         if resp.status != 200:
                             logger.warning(f"OTLP export failed: {resp.status}")
             except Exception as e:
                 logger.warning(f"OTLP export error: {e}")

         def _to_otlp_json(self, batch: list[dict]) -> dict:
             """转换为 OTLP JSON 格式"""
             return {
                 "resourceMetrics": [{
                     "resource": {"attributes": [
                         {"key": k, "value": {"stringValue": v}}
                         for k, v in self._resource_attrs.items()
                     ]},
                     "scopeMetrics": [{
                         "metrics": batch,
                     }],
                 }],
             }

         def record_counter(self, name: str, value: int | float,
                            attributes: dict | None = None) -> None:
             self._buffer.append({
                 "name": name,
                 "gauge": {"dataPoints": [{
                     "attributes": [{"key": k, "value": {"stringValue": str(v)}}
                                    for k, v in (attributes or {}).items()],
                     "value": {"doubleValue": float(value)},
                 }]},
             })

         # record_histogram / record_gauge 类似
     ```
   - 用 `aiohttp` 异步上报，避免阻塞主循环
   - 缓冲区用 `asyncio.Lock` 保护

2. **配置文件 `agent_config/telemetry.yaml`**
   - 新建配置文件：
     ```yaml
     otlp:
       enabled: false  # 默认关闭，用户显式启用
       endpoint: "http://localhost:4318/v1/metrics"
       headers:
         Content-Type: "application/json"
       resource_attrs:
         service.name: "agent"
         service.version: "1.0.0"
         deployment.environment: "production"
       batch_interval_seconds: 10.0
     ```
   - `enabled: false` 默认关闭，符合用户规则"不写 fallback"

3. **`TelemetryService` 加载 exporter**
   - 在 `agent/telemetry.py` 的 `TelemetryService` 中新增 `load_from_yaml`：
     ```python
     @classmethod
     def load_from_yaml(cls, config_path: Path) -> "TelemetryService":
         """从 yaml 加载配置，构造 TelemetryService"""
         service = cls()
         if not config_path.exists():
             return service
         config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
         otlp_config = config.get("otlp", {})
         if otlp_config.get("enabled"):
             exporter = OtlpHttpExporter(
                 endpoint=otlp_config["endpoint"],
                 headers=otlp_config.get("headers", {}),
                 resource_attrs=otlp_config.get("resource_attrs", {}),
                 batch_interval_seconds=otlp_config.get("batch_interval_seconds", 10.0),
             )
             service.add_sink(exporter)
         return service
     ```
   - 在 `agent/runtime.py` 启动时调用 `TelemetryService.load_from_yaml`

4. **metric 命名规范**
   - 统一 metric 命名：`agent.<module>.<action>`，如 `agent.runtime.iterations`、`agent.compaction.triggered`、`agent.tool.calls`
   - 在 `agent/types.py` 中定义 `METRIC_NAMES` 常量字典，避免拼写不一致
   - 现有 metric 调用点统一使用常量

5. **错误隔离**
   - exporter 抛错不影响主流程（仅 logger.warning）
   - 网络不可达时退化为 no-op（缓冲区满后丢弃旧数据）
   - 不写 fallback：exporter 失败时数据丢失（用户需自行监控 exporter 健康）

### 验证方法

1. 启动本地 OTLP 接收器（如 `otelcol --config otel-collector.yaml`）
2. 配置 `telemetry.yaml` 的 `enabled: true` 和 endpoint
3. 启动 agent，触发几次工具调用
4. 等待 10 秒（batch_interval），确认 OTLP 接收器收到 metric
5. 关闭接收器，确认 agent 不报错（仅 warning 日志）

### 注意事项

- `aiohttp` 需加入依赖（`requirements.txt`）
- 上报异步进行，不阻塞主循环
- 缓冲区无上限（生产环境建议加上限，当前简化实现）

---

## 14.2 Cron 完整架构（Z11）

### 任务背景

来源 Phase Z #Z11。Stage 8.7 已实现 Cron file-based spec 加载（从 `agent_config/cron/*.yaml` 读取）和 APScheduler 集成，但**缺完整架构**：
- 无 reconcile 机制（spec 文件变更后不自动重载）
- 无 materializer（spec 与已注册 job 状态无持久化）
- 无 runner 抽象（job 执行与 scheduler 强耦合）

Cline 的 `cron/` 目录包含 `reconciler.ts` / `materializer.ts` / `runner.ts` 三个独立模块。

### 目标

补齐 Cron 完整架构：
1. `CronReconciler`：定期扫描 spec 目录，diff 已注册 job，增删改
2. `CronMaterializer`：将 spec 和 job 状态持久化到 `cron_store.json`
3. `CronRunner`：job 执行抽象，支持同步/异步、超时、错误处理

### 当前实现位置

- `scheduler.py`（`load_cron_specs` / `register_cron_specs` / `_make_spec_job_executor`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/scheduler/cron/reconciler.ts`
- Cline `cron/materializer.ts`、`cron/runner.ts`

### 修复步骤建议

1. **`CronReconciler` 类**
   - 新建 `agent/cron_reconciler.py`：
     ```python
     class CronReconciler:
         """定期扫描 spec 目录，diff 已注册 job，增删改"""

         def __init__(self, sched: BlockingScheduler, specs_dir: Path,
                      check_interval_seconds: float = 60.0):
             self._sched = sched
             self._specs_dir = specs_dir
             self._check_interval = check_interval_seconds
             self._known_specs: dict[str, dict] = {}  # name -> spec

         async def start(self) -> None:
             """启动定期 reconcile"""
             while True:
                 self.reconcile()
                 await asyncio.sleep(self._check_interval)

         def reconcile(self) -> dict:
             """执行一次 reconcile，返回 {added, removed, updated}"""
             current_specs = {s["name"]: s for s in load_cron_specs(self._specs_dir)}
             added = set(current_specs) - set(self._known_specs)
             removed = set(self._known_specs) - set(current_specs)
             updated = {
                 name for name in (set(current_specs) & set(self._known_specs))
                 if current_specs[name] != self._known_specs[name]
             }
             # 处理新增
             for name in added:
                 self._register_job(current_specs[name])
             # 处理删除
             for name in removed:
                 self._sched.remove_job(name)
             # 处理更新（先删后加）
             for name in updated:
                 self._sched.remove_job(name)
                 self._register_job(current_specs[name])
             self._known_specs = current_specs
             return {"added": list(added), "removed": list(removed),
                     "updated": list(updated)}

         def _register_job(self, spec: dict) -> None:
             trigger = _parse_cron_schedule(spec["schedule"])
             if not trigger:
                 return
             executor = _make_spec_job_executor(spec["command"], spec["name"])
             self._sched.add_job(
                 executor, id=spec["name"], name=spec["description"],
                 trigger=trigger, timezone=spec["timezone"],
                 replace_existing=True,
             )
     ```
   - 用 mtime 检测文件变更（避免每次都全量解析）
   - reconcile 结果记录日志（INFO 级别）

2. **`CronMaterializer` 类**
   - 新建 `agent/cron_materializer.py`：
     ```python
     class CronMaterializer:
         """将 spec 和 job 状态持久化"""

         def __init__(self, store_path: Path):
             self._store_path = store_path
             self._state: dict = self._load()

         def _load(self) -> dict:
             if not self._store_path.exists():
                 return {"version": 1, "specs": {}, "last_run": {}}
             return json.loads(self._store_path.read_text(encoding="utf-8"))

         def save(self) -> None:
             tmp = self._store_path.with_suffix(".tmp")
             tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2),
                            encoding="utf-8")
             tmp.replace(self._store_path)

         def record_spec(self, name: str, spec: dict) -> None:
             self._state["specs"][name] = spec
             self.save()

         def record_run(self, name: str, run_info: dict) -> None:
             self._state["last_run"][name] = run_info
             self.save()

         def get_last_run(self, name: str) -> dict | None:
             return self._state["last_run"].get(name)
     ```
   - 持久化路径：`agent_config/cron_store.json`
   - 每次 spec 变更或 job 执行后调用 `save()`

3. **`CronRunner` 类**
   - 新建 `agent/cron_runner.py`：
     ```python
     class CronRunner:
         """job 执行抽象，支持同步/异步、超时、错误处理"""

         def __init__(self, materializer: CronMaterializer, default_timeout: float = 600.0):
             self._materializer = materializer
             self._default_timeout = default_timeout

         async def run(self, spec: dict) -> None:
             """执行 spec.command"""
             start_time = datetime.utcnow()
             run_info = {
                 "started_at": start_time.isoformat(),
                 "status": "running",
             }
             self._materializer.record_run(spec["name"], run_info)
             try:
                 # 执行 command（subprocess）
                 proc = await asyncio.create_subprocess_shell(
                     spec["command"],
                     stdout=asyncio.subprocess.PIPE,
                     stderr=asyncio.subprocess.PIPE,
                 )
                 stdout, stderr = await asyncio.wait_for(
                     proc.communicate(),
                     timeout=spec.get("timeout", self._default_timeout),
                 )
                 run_info.update({
                     "status": "completed" if proc.returncode == 0 else "failed",
                     "exit_code": proc.returncode,
                     "stdout": stdout.decode("utf-8", errors="replace")[:10000],
                     "stderr": stderr.decode("utf-8", errors="replace")[:10000],
                     "completed_at": datetime.utcnow().isoformat(),
                 })
             except asyncio.TimeoutError:
                 proc.kill()
                 run_info.update({
                     "status": "timeout",
                     "completed_at": datetime.utcnow().isoformat(),
                 })
             except Exception as e:
                 run_info.update({
                     "status": "error",
                     "error": str(e),
                     "completed_at": datetime.utcnow().isoformat(),
                 })
             self._materializer.record_run(spec["name"], run_info)
     ```
   - 执行结果记录到 materializer
   - 超时/错误不抛出（仅记录，避免阻塞 scheduler）

4. **`scheduler.py` 集成三个模块**
   - 在 `scheduler.py` 中：
     ```python
     def start_scheduler_with_cron(specs_dir: Path, store_path: Path) -> None:
         sched = BlockingScheduler()
         materializer = CronMaterializer(store_path)
         runner = CronRunner(materializer)
         reconciler = CronReconciler(sched, specs_dir)
         # 初始 reconcile
         reconciler.reconcile()
         # 启动定期 reconcile（在独立线程）
         threading.Thread(
             target=lambda: asyncio.run(reconciler.start()),
             daemon=True,
         ).start()
         sched.start()
     ```
   - 保留原有 `load_cron_specs` / `register_cron_specs` 函数（向后兼容）
   - 新增 `start_scheduler_with_cron` 作为推荐入口

5. **API 端点**
   - `GET /api/agent/cron/specs`：返回当前 spec 列表
   - `GET /api/agent/cron/jobs`：返回已注册 job 列表
   - `GET /api/agent/cron/last_run/<name>`：返回上次执行结果
   - `POST /api/agent/cron/reconcile`：手动触发 reconcile

### 验证方法

1. 在 `agent_config/cron/` 创建 `test.yaml`，确认 reconcile 后 job 已注册
2. 修改 `test.yaml` 的 schedule，确认 60 秒内自动更新
3. 删除 `test.yaml`，确认 job 自动移除
4. 触发 job 执行，确认 `cron_store.json` 记录了 `last_run`
5. 超时 job（timeout=1s，命令 sleep 5），确认状态为 `timeout`

### 注意事项

- reconcile 线程是 daemon，主进程退出时自动结束
- materializer 文件写入用 `tmp.replace` 保证原子性
- runner 的 stdout/stderr 截断到 10000 字符（避免文件膨胀）

---

## 14.3 distinctId + 事件枚举覆盖率（Z3 / Z4）

### 任务背景

来源 Phase Z #Z3 / Z4。当前遥测系统两个差距：

1. **Z3 distinctId 缺失**：每个事件无唯一标识，无法去重和追踪。Cline 的事件含 `distinctId` 字段（UUID），便于在 OTLP 后端做去重和关联。
2. **Z4 事件枚举覆盖率低**：当前遥测事件用字符串硬编码（如 `"run_started"`），无统一枚举，易拼写错误。Cline 有 `TelemetryEvent` 枚举类，覆盖 30+ 事件。

### 目标

补齐 distinctId 和事件枚举：
1. 每个遥测事件携带 `distinct_id`（UUID v4）
2. 定义 `TelemetryEvent` 枚举类，覆盖所有事件
3. 现有事件调用点改用枚举常量

### 当前实现位置

- `agent/telemetry.py`（`TelemetryService.record_event` 方法）
- `agent/runtime.py` / `agent/compaction.py` / `agent/tools/*.py`（事件调用点）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/events.ts`（`TelemetryEvent` 枚举）
- Cline `telemetry-types.ts`（`distinctId` 字段）

### 修复步骤建议

1. **`TelemetryEvent` 枚举类**
   - 在 `agent/types.py` 中新增：
     ```python
     from enum import Enum

     class TelemetryEvent(str, Enum):
         """遥测事件枚举"""
         # Runtime 事件
         RUN_STARTED = "run_started"
         RUN_FINISHED = "run_finished"
         RUN_FAILED = "run_failed"
         RUN_ABORTED = "run_aborted"
         # 工具事件
         TOOL_CALLED = "tool_called"
         TOOL_SUCCEEDED = "tool_succeeded"
         TOOL_FAILED = "tool_failed"
         # 压缩事件
         COMPACTION_STARTED = "compaction_started"
         COMPACTION_COMPLETED = "compaction_completed"
         COMPACTION_FAILED = "compaction_failed"
         COMPACTION_SKIPPED = "compaction_skipped"
         # 预算事件
         BUDGET_PROJECTION = "budget_projection"
         # Hook 事件
         HOOK_EXECUTED = "hook_executed"
         HOOK_FAILED = "hook_failed"
         # 审批事件
         APPROVAL_REQUESTED = "approval_requested"
         APPROVAL_DECIDED = "approval_decided"
         # Checkpoint 事件
         CHECKPOINT_CREATED = "checkpoint_created"
         CHECKPOINT_RESTORED = "checkpoint_restored"
         # 会话事件
         SESSION_CREATED = "session_created"
         SESSION_RESTORED = "session_restored"
         SESSION_CLOSED = "session_closed"
         # Provider 事件
         PROVIDER_CALLED = "provider_called"
         PROVIDER_ERROR = "provider_error"
         # MistakeTracker 事件
         MISTAKE_RECORDED = "mistake_recorded"
         MISTAKE_LIMIT_REACHED = "mistake_limit_reached"
         # 循环检测事件
         LOOP_DETECTED_SOFT = "loop_detected_soft"
         LOOP_DETECTED_HARD = "loop_detected_hard"
     ```
   - 继承 `str, Enum` 让枚举值可直接作为字符串使用
   - 覆盖 28 个核心事件

2. **事件结构增加 `distinct_id` 字段**
   - 在 `agent/telemetry.py` 中的 `record_event` 方法签名：
     ```python
     def record_event(
         self,
         event: TelemetryEvent | str,  # 接受枚举或字符串（向后兼容）
         attributes: dict | None = None,
         distinct_id: str | None = None,  # 新增
     ) -> None:
         if distinct_id is None:
             distinct_id = str(uuid.uuid4())
         # ... 上报逻辑
     ```
   - 默认生成 UUID v4，调用方也可传入（便于关联多个事件）

3. **现有事件调用点改用枚举**
   - 全局替换字符串字面量为枚举常量：
     ```python
     # 原有
     telemetry.record_event("run_started", {...})
     # 改为
     telemetry.record_event(TelemetryEvent.RUN_STARTED, {...})
     ```
   - 用 Grep 找出所有 `record_event("` 调用点，逐个替换
   - 保留字符串传入的兼容性（运行时若是字符串，自动尝试转枚举）

4. **`distinct_id` 关联示例**
   - run_started 和 run_finished 用同一个 distinct_id：
     ```python
     run_id = str(uuid.uuid4())
     telemetry.record_event(TelemetryEvent.RUN_STARTED, {...}, distinct_id=run_id)
     # ... run 主循环 ...
     telemetry.record_event(TelemetryEvent.RUN_FINISHED, {...}, distinct_id=run_id)
     ```
   - tool_called 和 tool_succeeded/failed 用同一个 tool_call_id
   - compaction_started 和 compaction_completed/failed 用同一个 compaction_id

5. **OTLP 上报携带 distinct_id**
   - 在 `OtlpHttpExporter._to_otlp_json` 中：
     ```python
     def _to_otlp_json(self, batch: list[dict]) -> dict:
         return {
             "resourceMetrics": [{
                 # ...
                 "scopeMetrics": [{
                     "metrics": batch,
                 }],
             }],
             # OTLP spans 用 distinct_id 作为 trace_id 关联
         }
     ```
   - distinct_id 作为 attribute 写入 metric datapoint
   - 便于在 Grafana 中按 distinct_id 过滤关联事件

6. **事件覆盖率检查**
   - 新增 `tests/test_telemetry_coverage.py`（仅文档说明，不强制写测试）：
     - 列出所有 TelemetryEvent 枚举值
     - Grep 源码确认每个枚举至少有 1 个调用点
     - 未覆盖的枚举 logger.warning（不报错）
   - 该检查作为开发辅助，不强制 CI

### 验证方法

1. 触发一次 run，确认 run_started 和 run_finished 的 distinct_id 相同
2. 检查 OTLP 上报数据，确认每个 datapoint 含 `distinct_id` attribute
3. Grep 源码，确认所有 `record_event` 调用使用枚举（无字符串字面量）
4. 现有字符串调用（如第三方库）仍能工作（向后兼容）

### 注意事项

- `distinct_id` 用 UUID v4（碰撞概率极低）
- 枚举值与现有字符串一致（向后兼容）
- 事件覆盖率检查不强制（开发辅助）

---

## 15. 阶段汇总

### 15.1 完成判据

- 14.1：`OtlpHttpExporter` 上报 metric 到 OTLP 后端，配置文件可控制启用
- 14.2：`CronReconciler` 自动检测 spec 变更，`CronMaterializer` 持久化状态，`CronRunner` 执行 job
- 14.3：所有事件携带 `distinct_id`，`TelemetryEvent` 枚举覆盖 28 个事件

### 15.2 风险与回滚

- 14.1 网络上报可能失败，需错误隔离（仅 warning，不阻塞主流程）
- 14.2 reconcile 线程需正确处理异常（避免线程退出导致 spec 不更新）
- 14.3 枚举替换需全局回归测试，避免遗漏

### 15.3 后续衔接

- 14.1 完成后，未来可扩展 OTLP gRPC exporter（性能更好）
- 14.2 完成后，未来可支持 cron job 依赖关系（如 A 完成后触发 B）
- 14.3 完成后，未来可扩展事件采样（高频事件按比例上报）

---

**Stage 14 结束。建议按 14.3 → 14.1 → 14.2 顺序执行。**

---

## 16. 全轮修复总结

### 16.1 整体进度

| Stage | 优先级 | 任务数 | 预估工作量 |
|-------|--------|--------|-----------|
| Stage 9 | P1 | 6 | 1 周 |
| Stage 10 | P2 | 6 | 1.5 周 |
| Stage 11 | P2 | 4 | 1 周 |
| Stage 12 | P2 | 5 | 1.5 周 |
| Stage 13 | P2 | 4 | 1 周 |
| Stage 14 | P2 | 3 | 1 周 |
| **合计** | - | **28** | **6 周** |

### 16.2 完成后预期对齐度

基于 v2 评估 69% 对齐度，完成 Stage 9-14 后预计：
- P1 剩余 6 项全部修复：+5% 对齐度
- P2 剩余 22 项全部修复：+10% 对齐度
- **预期 v3 对齐度：约 84%**
- **去除有意不实施项后对齐度：约 90%**

### 16.3 执行原则重申

1. 每个 stage 可独立执行，不依赖其他 stage（除明确标注的依赖）
2. 保留原有功能，不移除已有逻辑
3. 中文注释 UTF-8 编码
4. 不写 fallback，不写测试脚本（除非用户要求）
5. plan 是指引，执行时根据实际结果调整

---

**第二轮修复计划结束。建议按 Stage 9 → 10 → 11 → 12 → 13 → 14 顺序推进。**
