# Phase V: Sub-agent / 多 Agent 对比报告

> 对标源码：
> - `sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts`
> - `sdk/packages/core/src/extensions/tools/team/delegated-agent.ts`
> - `sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts`
> - `sdk/packages/core/src/extensions/tools/team/configured-agent-tool.ts`
> - `sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
> - `sdk/packages/core/src/extensions/tools/team/projections.ts`
> - `apps/vscode/src/core/task/tools/subagent/AgentConfigLoader.ts`
>
> 当前实现：无（Phase 27 移除了技能子 agent，无 `spawn_agent` 工具）
> 关联基础设施：`agent/runtime.py`（保留 `parent_agent_id` 字段）、`agent/skills/`（技能系统，非子 agent）
> 对比维度：V1-V10

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 0 项 |
| 弱对齐 | 3 项 |
| 缺失 | 7 项 |
| 额外增强 | 0 项 |
| **对齐度** | **约 10%** |

**核心结论**：当前实现整体缺失子 agent / 多 agent 协作机制。仅 `parent_agent_id` 字段、`EventEmitter.subscribe` 基础设施、`AgentRuntimeConfig.max_iterations` 三个底层字段为后续接入预留了弱对齐接口。Phase 27 主动移除技能子 agent 后，本系统不再有子 agent 路径。考虑到量化场景的特性（单 agent + 技能注入已能覆盖），此阶段属 P2 优先级，建议保留现状，详见第 7 节适用性评估。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| V1 | `spawn_agent` 工具 | spawn-agent-tool.ts L117-202 | 无 | 缺失 |
| V2 | `delegated-agent` 创建 | delegated-agent.ts L137-146 (`createDelegatedAgent`) | runtime.py L181/L223（仅 `parent_agent_id` 字段） | 弱对齐 |
| V3 | `subagent-prompts` 构造 | subagent-prompts.ts L23-41 (`buildSubAgentSystemPrompt`) | 无 | 缺失 |
| V4 | `configured-agent-tool` | configured-agent-tool.ts L152-253 (`createConfiguredAgentTools`) | 无（`SkillsTool` 是不同概念，见下方说明） | 缺失 |
| V5 | `multi-agent` 协作 | multi-agent.ts L176-466 (`AgentTeam` + `AgentTeamsRuntime`) | 无 | 缺失 |
| V6 | `projections` 事件投影 | projections.ts L45-283 (`buildTeamProgressSummary` + `toTeamProgressLifecycleEvent`) | 无 | 缺失 |
| V7 | `AgentConfigLoader` yaml | AgentConfigLoader.ts L157-354 | 无（`SkillLoader` 加载的是 SKILL.md，不是 agent 配置） | 缺失 |
| V8 | 子 agent 工具集限制 | spawn-agent-tool.ts L125-127 (`createSubAgentTools` 工厂，默认不传 spawn_agent) | 无 | 缺失 |
| V9 | 子 agent `max_iterations` | spawn-agent-tool.ts L134 (`defaultMaxIterations`) + configured-agent-tool.ts L148/L174 | runtime.py L203 (`AgentRuntimeConfig.max_iterations`) | 弱对齐 |
| V10 | 子 agent 事件冒泡 | spawn-agent-tool.ts L137 (`onSubAgentEvent`) + delegated-agent.ts L142-144 (`subscribeEvents`) | runtime.py L313-315 (`subscribe` + `EventEmitter`) | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #V1：`spawn_agent` 工具缺失

**严重度**：P2（量化场景非必需，详见第 7 节）

**Cline 实现**（spawn-agent-tool.ts L30-35, L117-202）：
- 输入 schema：`{ systemPrompt: string, task: string }`，仅 2 个字段，极简
- 工具名：`spawn_agent`
- 工具描述：`"Spawn a sub-agent with a custom system prompt for specialized tasks. Use when delegating work that benefits from focused expertise."`
- 执行流程：
  1. 调用 `createSubAgentTools(input, context)` 动态构造子 agent 工具集（防递归）
  2. `createDelegatedAgent({ kind: "subagent", prompt: input.systemPrompt, ... })` 创建独立 runtime
  3. 触发 `onSubAgentStart` 生命周期回调（best-effort，错误被吞掉）
  4. `subAgent.run(input.task)` 同步等待结果
  5. 触发 `onSubAgentEnd` 回调（成功/失败均触发）
  6. 返回 `SpawnAgentOutput { text, iterations, finishReason, usage: { inputTokens, outputTokens } }`
- 超时：`timeoutMs: 300000`（5 分钟）
- 不可重试：`retryable: false`

**我的实现**：无。Phase 27 已移除技能子 agent。

**影响**：
- 主 agent 无法将"专业化任务"委派给独立 runtime 执行
- 复杂任务无法通过分治降低单次 prompt 长度
- 无法实现"研究者 + 写作者"等多角色协作

**修复建议**：暂不实现。详见第 7 节量化场景适用性评估。如未来确需实现，建议参照 Cline schema 设计：
```python
class SpawnAgentInput(BaseModel):
    system_prompt: str
    task: str
```

**优先级**：P2

---

### 差距 #V2：`delegated-agent` 工厂缺失（基础设施弱对齐）

**严重度**：P2

**Cline 实现**（delegated-agent.ts L137-146）：
```typescript
export function createDelegatedAgent(options: BuildDelegatedAgentConfigOptions): SessionRuntime {
    const config = buildDelegatedAgentConfig(options);
    const session = new SessionRuntime(config);
    if (config.onEvent) {
        session.subscribeEvents(config.onEvent);
    }
    return session;
}
```
关键点：
- 工厂函数返回独立的 `SessionRuntime` 实例
- `buildDelegatedAgentConfig` 根据 `kind`（`"subagent"` / `"teammate"`）选择不同的 system prompt 构造器
- 子 agent 通过 `subscribeEvents(onEvent)` 自动把事件转发给父 agent 的 `onSubAgentEvent` 回调
- 配置通过 `DelegatedAgentConfigProvider` 注入，支持运行时更新连接配置（`updateConnectionDefaults`）

**我的实现**：`agent/runtime.py` L181/L223 保留了 `parent_agent_id` 字段，`AgentRuntime` 类已存在，但：
- 无 `create_delegated_agent` 工厂函数
- 无 `DelegatedAgentConfigProvider` 抽象
- 无 `subscribe_events` 方法（只有 `subscribe(listener)`，等价但不显式命名）
- 无 `kind` 区分（subagent vs teammate）

**影响**：基础设施层已预留 `parent_agent_id`，但缺少工厂层封装，需手动 `AgentRuntime(config)` 构造，无法统一处理事件转发、配置注入、kind 区分。

**修复建议**：如需实现，新增 `agent/delegated.py`：
```python
def create_delegated_agent(kind: str, prompt: str, tools: list[BaseTool],
                          parent_agent_id: str | None = None,
                          max_iterations: int | None = None,
                          on_event: EventListener | None = None) -> AgentRuntime:
    config = AgentRuntimeConfig(
        system_prompt=build_subagent_system_prompt(prompt, ...),
        tools=tools,
        max_iterations=max_iterations,
        parent_agent_id=parent_agent_id,
        ...
    )
    runtime = AgentRuntime(config)
    if on_event:
        runtime.subscribe(on_event)
    return runtime
```

**优先级**：P2

---

### 差距 #V3：`subagent-prompts` 构造缺失

**严重度**：P2

**Cline 实现**（subagent-prompts.ts L23-41）：
```typescript
export function buildSubAgentSystemPrompt(prompt: string, config: DelegatedAgentRuntimeConfig): string {
    const trimmedPrompt = prompt.trim();
    if (config.providerId.toLowerCase() !== "cline") {
        return trimmedPrompt;  // 非 cline provider 直接返回原 prompt
    }
    return buildClineSystemPrompt({
        ide: config.clineIdeName || "Terminal",
        workspaceRoot: config.cwd?.trim() || "/",
        providerId: config.providerId,
        overridePrompt: trimmedPrompt,  // 关键：用 overridePrompt 替换默认 cline prompt 主体
        metadata: config.workspaceMetadata,
        platform: config.clinePlatform,
    });
}
```
关键点：
- 区分 `subagent`（`overridePrompt` 完全替换主体）和 `teammate`（`rules` 拼接在 `# Team Teammate Role` 下）
- 仅 `cline` provider 才注入完整 Cline 系统 prompt（IDE、workspace、platform 等）
- 其他 provider 直接返回原始 prompt（极简）

**我的实现**：无。当前 `AgentRuntimeConfig.system_prompt` 由调用方直接传入，无构造器。

**影响**：子 agent 的 system prompt 无法包含 workspace 上下文（cwd、platform、IDE）。

**修复建议**：暂不实现。本系统无 IDE 集成需求，`overridePrompt` 等价于直接传入 prompt。

**优先级**：P2

---

### 差距 #V4：`configured-agent-tool`（预配置 agent）缺失

**严重度**：P2

**Cline 实现**（configured-agent-tool.ts L152-253）：
- 从 yaml 配置加载预定义 agent 列表（name、description、systemPrompt、tools、modelId、maxIterations）
- 为每个 agent 生成一个独立工具：`subagent_<sanitized_name>_<hash>`
- 工具 schema：`{ prompt: string }`（仅 1 个字段，比 spawn_agent 更简）
- 工具描述：`Use the "<name>" subagent: <description>`
- 调用时：用 agent 自身的 systemPrompt + 用户传入的 prompt 创建子 agent
- 工具名生成逻辑：`sanitizeAgentName` (a-z, 0-9, _) + `hashString` (FNV-1a 32 位 hash 取 6 位 base36)，最大 64 字符，去重

**与 SkillsTool 的区别**：
| 维度 | `configured-agent-tool` | 我的 `SkillsTool` |
|------|-------------------------|-------------------|
| 调用方式 | 创建独立 runtime 执行 | 主上下文注入指令 |
| 工具集 | 子 agent 独立工具集（受限） | 主 agent 完整工具集 |
| 隔离性 | 完全隔离（独立 messages、独立 max_iterations） | 无隔离（共享 messages） |
| 返回 | `SpawnAgentOutput { text, iterations, ... }` | XML 指令字符串 |
| 配置 | yaml 文件（`~/Documents/Cline/Agents/`） | SKILL.md frontmatter |

**我的实现**：无对应概念。`SkillsTool` 是"指令注入"而非"agent 委派"，本质不同。

**影响**：无法通过 yaml 配置快速注册"专家 agent"（如 `analyst_agent`、`writer_agent`）作为工具供主 agent 调用。

**修复建议**：暂不实现。`SkillsTool` 已覆盖"专业化指令注入"场景，对量化场景足够。

**优先级**：P2

---

### 差距 #V5：`multi-agent` 协作（AgentTeam）缺失

**严重度**：P2

**Cline 实现**（multi-agent.ts L176-466）：
- `AgentTeam` 类：基础多 agent 协作
  - `addAgent` / `removeAgent` / `getAgent`
  - `routeTo(agentId, message)`：路由消息到指定 agent
  - `continueTo(agentId, message)`：续聊
  - `runParallel(tasks)`：并行执行多 agent 任务
  - `runSequential(tasks)`：串行执行
  - `runPipeline(pipeline, initialMessage, transformer)`：流水线（前一个 agent 输出作为下一个输入）
  - `abortAll()` / `clear()`
  - 事件：`TaskStart` / `TaskEnd` / `AgentEvent` / `TeammateSpawned` / `TeammateShutdown`

- `AgentTeamsRuntime` 类（L522-1834）：高级 lead + teammate 协作
  - 任务管理：`createTask` / `claimTask` / `blockTask` / `completeTask`，支持 `dependsOn` 依赖
  - 邮箱：`sendMessage` / `broadcast` / `listMailbox`，支持 steer message 注入
  - 任务日志：`appendMissionLog`，按 step 数 + 时间间隔节流
  - 异步运行队列：`startTeammateRun` / `dispatchQueuedRuns` / `selectNextDispatchableQueuedRun`
  - 并发控制：`maxConcurrentRuns`（默认 2）
  - 重试：`maxRetries` + 指数退避（`2 ** retryCount` 秒，上限 30s）
  - 心跳：每 2s 更新 `heartbeatAt`
  - 故障恢复：`recoverActiveRuns` / `markStaleRunsInterrupted`
  - 状态导出：`exportState` / `hydrateState`
  - Outcome 协作产物：`createOutcome` / `attachOutcomeFragment` / `reviewOutcomeFragment` / `finalizeOutcome`

- 工厂：`createAgentTeam` / `createWorkerReviewerTeam`（doAndReview 模式）

**我的实现**：无。

**影响**：
- 无法实现"研究员 + 写作员 + 审核员"流水线
- 无法并行执行多个独立子任务
- 无任务依赖、邮箱、mission log 等协作原语

**修复建议**：暂不实现。详见第 7 节。

**优先级**：P2

---

### 差距 #V6：`projections` 事件投影缺失

**严重度**：P2

**Cline 实现**（projections.ts L45-283）：
- `buildTeamProgressSummary(teamName, state)`：从 `TeamRuntimeState` 构造进度摘要
  - 成员状态分布（idle/running/stopped）
  - 任务状态分布 + blockedTaskIds + readyTaskIds + completionPct
  - 运行状态分布 + activeRunIds + latestRunId
  - Outcome 状态分布 + missingRequiredSections
  - Fragment 状态分布
- `toTeamProgressLifecycleEvent({ teamName, sessionId, event })`：将内部 `TeamEvent` 投影为简化的 `TeamProgressLifecycleEvent`
  - 每种事件类型映射到统一的 `{ teamName, sessionId, eventType, ts, taskId?, agentId?, runId?, message? }` 结构
  - 用于 UI 展示与跨进程通信

**我的实现**：无。

**影响**：无统一的团队进度摘要 / 事件投影机制。

**修复建议**：暂不实现。本系统无团队协作场景。

**优先级**：P2

---

### 差距 #V7：`AgentConfigLoader` yaml 加载缺失

**严重度**：P2

**Cline 实现**（AgentConfigLoader.ts L157-354）：
- 单例模式：`AgentConfigLoader.getInstance(homeDir)`
- 配置目录：`~/Documents/Cline/Agents/`
- 文件格式：YAML frontmatter（`name`、`description`、`modelId?`、`tools?`、`skills?`） + body（systemPrompt）
- schema 校验：zod（`AgentBaseConfigSchema` + `AgentConfigFrontmatterSchema`）
- 工具名校验：`normalizeToolName` 必须是 `ClineDefaultTool` 枚举值
- 文件监听：`chokidar.watch`，add/change/unlink 触发 `reloadAndNotify`
- 工具名映射：`buildSubagentToolName` 生成 `subagent_<sanitized>`，去重
- 反向映射：`cachedToolNameToAgentName` 用于从工具名反查 agent 名
- 动态工具注册：`setDynamicToolUseNames("subagent", [...toolNames])` 注册到全局

**与 `SkillLoader` 的区别**：
| 维度 | `AgentConfigLoader` | 我的 `SkillLoader` |
|------|---------------------|-------------------|
| 加载对象 | agent 配置（含 systemPrompt + tools + modelId） | skill 配置（含 instructions + scripts） |
| 用途 | 注册为子 agent 工具 | 注入主 agent 上下文 |
| 工具名校验 | 必须是 `ClineDefaultTool` 枚举 | 无（skill 不是工具） |
| 热重载 | chokidar watch | 无（Phase I 已识别为差距 #I18） |
| 单例 | 是 | 否 |

**我的实现**：无 agent 配置加载器。`SkillLoader` 加载的是 SKILL.md，不是 agent 配置。

**影响**：无法通过 yaml 文件配置子 agent。

**修复建议**：暂不实现。

**优先级**：P2

---

### 差距 #V8：子 agent 工具集限制缺失

**严重度**：P2

**Cline 实现**（spawn-agent-tool.ts L125-127）：
```typescript
const tools = config.createSubAgentTools
    ? await config.createSubAgentTools(input, context)
    : (config.subAgentTools ?? []);
```
关键点：
- 子 agent 工具集由 `createSubAgentTools(input, context)` 工厂动态构造
- 调用方负责"过滤掉 spawn_agent 自身"以防止递归
- `configured-agent-tool.ts` 同样通过 `createSubAgentTools(config, input, context)` 工厂构造，并允许根据 agent 配置进一步限制工具集
- Cline 默认实现（在 vscode task 层）会从主 agent 工具集中移除 `spawn_agent` 和其他递归工具

**我的实现**：无。

**影响**：无防递归机制。但当前无 spawn_agent，本身不会递归。

**修复建议**：如未来实现 spawn_agent，必须在 `createSubAgentTools` 中显式过滤 `spawn_agent` 自身。

**优先级**：P2

---

### 差距 #V9：子 agent `max_iterations` 独立计数（弱对齐）

**严重度**：P2

**Cline 实现**：
- `spawn-agent-tool.ts` L134：`maxIterations: config.defaultMaxIterations`（可选，默认 undefined → 用 runtimeConfig.maxIterations）
- `configured-agent-tool.ts` L148：`maxIterations: agent.maxIterations ?? base.maxIterations`（agent 配置优先，回退到 base）
- `delegated-agent.ts` L123：`maxIterations: options.maxIterations ?? runtimeConfig.maxIterations`
- 子 agent 拥有独立的 `_RuntimeState.iteration` 计数器（由 `SessionRuntime` 实例化时初始化）
- 父 agent 的 iteration 不影响子 agent

**我的实现**：
- `agent/runtime.py` L203：`AgentRuntimeConfig.max_iterations=50`（默认 50）
- `agent/runtime.py` L185：`_RuntimeState.iteration: int = 0`（每个 AgentRuntime 实例独立）
- `agent/runtime.py` L517-518：`self.config.max_iterations is None or self._state.iteration < self.config.max_iterations`

**对齐点**：
- 每个 `AgentRuntime` 实例独立计数 → 子 agent 实例化后自然独立计数 ✓
- `max_iterations` 可配置 ✓

**未对齐点**：
- 无 `defaultMaxIterations` 配置项（无 SpawnAgentToolConfig）
- 无"agent 配置优先 + base 回退"的合并逻辑

**影响**：基础设施层支持独立计数，但缺少子 agent 上下文下的配置合并。

**修复建议**：如实现 spawn_agent，新增 `default_max_iterations` 参数即可。

**优先级**：P2

---

### 差距 #V10：子 agent 事件冒泡（弱对齐）

**严重度**：P2

**Cline 实现**：
- `spawn-agent-tool.ts` L137：`onEvent: config.onSubAgentEvent` 把父 agent 的回调传给子 agent
- `delegated-agent.ts` L142-144：`if (config.onEvent) { session.subscribeEvents(config.onEvent); }` 子 agent 订阅事件转发给父回调
- 事件流：子 agent emit → 父 agent 的 `onSubAgentEvent` → 父 agent 进一步投影/转发到 SSE
- 子 agent 事件包含完整的 `AgentEvent` 结构（iteration_start/content_start/content_end/iteration_end/done/error）

**我的实现**：
- `agent/runtime.py` L313-315：`subscribe(listener)` 方法存在
- `agent/runtime.py` L217：`self._emitter = EventEmitter()`，每个 AgentRuntime 独立
- 事件冒泡基础设施可用：父 agent 可调用 `child_runtime.subscribe(parent_listener)` 转发事件

**对齐点**：
- EventEmitter 模式与 Cline subscribeEvents 等价 ✓
- 每个 AgentRuntime 独立 emitter ✓

**未对齐点**：
- 无 `sub_agent_event` 事件类型（无 SSE 层标记）
- 无 `onSubAgentStart` / `onSubAgentEnd` 生命周期回调
- 无事件投影层（差距 #V6）

**影响**：事件冒泡基础设施可用，但无具体子 agent 事件协议。

**修复建议**：如实现 spawn_agent，需：
1. 定义 `sub_agent_event` SSE 事件类型
2. 在 `onSubAgentStart` / `onSubAgentEnd` 回调中包装子 agent 事件
3. 在 SSE 层增加 `parent_agent_id` 字段标识冒泡来源

**优先级**：P2

---

## 4. 一致性统计

### 按一致性等级

| 等级 | 项数 | 占比 | 项目 |
|------|------|------|------|
| 完全一致 | 0 | 0% | - |
| 弱对齐 | 3 | 30% | V2, V9, V10 |
| 缺失 | 7 | 70% | V1, V3, V4, V5, V6, V7, V8 |
| 额外增强 | 0 | 0% | - |

### 按优先级分布（仅差距项）

| 优先级 | 数量 | 项目 |
|--------|------|------|
| P0 | 0 | - |
| P1 | 0 | - |
| P2 | 10 | V1, V2, V3, V4, V5, V6, V7, V8, V9, V10 |
| P3 | 0 | - |

### 核心结论

- **无 P0/P1 差距**：子 agent / 多 agent 协作在量化场景非必需
- **全部为 P2**：本系统主动选择不实现子 agent（Phase 27 移除技能子 agent），保留 `parent_agent_id` 字段为未来接入预留
- **弱对齐集中在基础设施层**：V2（`parent_agent_id`）、V9（`max_iterations`）、V10（`EventEmitter`）三个底层字段/接口已存在，如未来实现 spawn_agent 可直接复用

---

## 5. 修复建议

### 短期（P2，建议本阶段完成）

**无**。本阶段为 P2 优先级，且量化场景不必需，短期无需修复。

### 中期（P2，按需实现）

仅在以下触发条件出现时再考虑实现：

1. **若需"分治复杂量化任务"**（如同时分析 10 只股票）：
   - 实现 V1 + V2 + V8 + V9 + V10（spawn_agent 工具链）
   - 跳过 V3（无 IDE 集成）、V4（SkillsTool 已覆盖部分场景）、V5/V6（多 agent 协作在量化场景过度设计）
   - 估计工作量：2-3 天
   - 实现优先级：V2 > V1 > V10 > V9 > V8

2. **若需"yaml 配置专家 agent"**：
   - 实现 V7 + V4（AgentConfigLoader + configured-agent-tool）
   - 与现有 SkillLoader 共享 frontmatter 解析逻辑
   - 估计工作量：1-2 天

### 长期（P3，暂不实现）

3. **V5 multi-agent 协作**：流水线 / 并行 / 邮箱 / mission log 等高级协作，量化场景暂无需求。
4. **V6 projections 事件投影**：依赖 V5，无独立价值。
5. **V3 subagent-prompts 完整构造**：无 IDE 集成，`overridePrompt` 等价于直接传 prompt。

---

## 6. 验证记录

### 6.1 已读取的对标文件

| 文件 | 行数 | 关键内容 |
|------|------|---------|
| `third_party/cline/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts` | 203 | SpawnAgentInputSchema、createSpawnAgentTool、onSubAgentStart/End 生命周期 |
| `third_party/cline/sdk/packages/core/src/extensions/tools/team/delegated-agent.ts` | 146 | createDelegatedAgentConfigProvider、buildDelegatedAgentConfig、createDelegatedAgent |
| `third_party/cline/sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts` | 41 | buildTeammateSystemPrompt、buildSubAgentSystemPrompt |
| `third_party/cline/sdk/packages/core/src/extensions/tools/team/configured-agent-tool.ts` | 253 | ConfiguredAgentInputSchema、sanitizeAgentName、hashString、buildConfiguredAgentToolName、createConfiguredAgentTools |
| `third_party/cline/sdk/packages/core/src/extensions/tools/team/multi-agent.ts` | 1852 | AgentTeam、AgentTeamsRuntime、createWorkerReviewerTeam、任务/邮箱/运行队列/Outcome 完整实现 |
| `third_party/cline/sdk/packages/core/src/extensions/tools/team/projections.ts` | 283 | buildTeamProgressSummary、toTeamProgressLifecycleEvent |
| `third_party/cline/apps/vscode/src/core/task/tools/subagent/AgentConfigLoader.ts` | 355 | AgentConfigLoader 单例、chokidar watch、YAML frontmatter 解析、buildSubagentToolName 映射 |

### 6.2 已读取的我的实现文件

| 文件 | 关键发现 |
|------|---------|
| `agent/skills/__init__.py` | 技能系统导出 SkillLoader / SkillRegistry / SkillsTool，非子 agent |
| `agent/skills/skill_tool.py` | SkillsTool 是"主上下文指令注入"，明确注释"不创建子 agent"（L8-L9） |
| `agent/runtime.py` | L181 `parent_agent_id` 字段保留；L203 `max_iterations=50`；L217 `EventEmitter`；L313 `subscribe()` |
| `agent/types.py` | L319 `parent_agent_id`；L390 `AgentToolContext.parent_agent_id` |
| `agent/telemetry.py` | L540 上报 `parent_agent_id` 字段 |

### 6.3 验证方法

1. **逐文件读取 Cline 源码**：7 个对标文件全部完整读取
2. **grep 搜索我的实现**：搜索 `sub_agent|subagent|spawn_agent|delegated|child_agent|parent_agent` 关键词，确认无子 agent 实现，仅保留 `parent_agent_id` 字段
3. **基础设施对齐验证**：`agent/runtime.py` 的 `EventEmitter`、`subscribe`、`max_iterations`、`parent_agent_id` 已确认存在
4. **与 phase_I 对比**：确认 SkillsTool 与 configured-agent-tool 是不同概念（指令注入 vs agent 委派）

### 6.4 关键发现

1. **Phase 27 主动移除技能子 agent**：`agent/skills/skill_tool.py` L8-L9 明确注释"不创建子 agent，而是在主 agent 上下文中返回 skill 指令文本"。这是设计选择，非实现遗漏。
2. **`parent_agent_id` 字段全链路保留**：runtime/types/telemetry 三处保留，说明早期可能有过子 agent 实现痕迹，字段为未来接入预留。
3. **Cline 子 agent 设计极简**：spawn_agent 输入仅 2 字段（systemPrompt + task），configured-agent 输入仅 1 字段（prompt），整体设计目标是为 LLM 提供"委派"原语，而非复杂协作。
4. **Cline multi-agent 极复杂**：`multi-agent.ts` 1852 行，含任务依赖、邮箱、运行队列、心跳、重试、故障恢复、Outcome 协作产物等，是面向"长时协作团队"的设计，量化场景过度设计。
5. **Cline AgentConfigLoader 与 SkillLoader 共享 frontmatter 解析**：两者都解析 YAML frontmatter，但 AgentConfigLoader 有 chokidar 热重载，SkillLoader 无（Phase I 差距 #I18 已记录）。
6. **Cline 工具名生成用 FNV-1a hash**：`hashString` 函数（configured-agent-tool.ts L83-90）用 FNV-1a 32 位 hash 取 6 位 base36 作为后缀，去重 + 长度控制。本系统 SkillLoader 无此需求（skill 名直接用作工具参数，不注册为独立工具）。
7. **Cline 区分 subagent 与 teammate**：`DelegatedAgentKind = "subagent" | "teammate"`，subagent 用 `overridePrompt` 完全替换，teammate 用 `rules` 拼接在 `# Team Teammate Role` 下。teammate 模式才参与 AgentTeamsRuntime 的 lead + teammate 协作。
8. **Cline 事件冒泡是订阅模式**：子 agent 通过 `session.subscribeEvents(config.onEvent)` 把事件转发给父 agent 提供的回调，父 agent 在回调中决定是否进一步投影/转发到 SSE。本系统的 `EventEmitter.subscribe(listener)` 模式与之等价。

---

## 7. 量化场景适用性评估

### 7.1 量化场景特性

| 特性 | 量化场景 | Cline 子 agent 设计目标 |
|------|---------|------------------------|
| 任务结构 | 单 agent + 多技能（数据获取 / 因子计算 / 回测 / 报告） | 多角色协作（lead + teammate） |
| 任务时长 | 单次 5-30 分钟 | 长时协作（含任务队列、心跳、重试） |
| 上下文共享 | 共享股票池 / 因子库 / 回测结果 | 通过邮箱 + mission log 共享 |
| 工具集 | read_file / execute_python / web_search 等通用工具 | 子 agent 可受限工具集 |
| 失败模式 | 单点失败，直接重试 | 任务依赖、邮箱、Outcome 等需复杂恢复 |
| 并发需求 | 偶尔（多股票并行分析） | 高（多 teammate 并行） |

### 7.2 子 agent 在量化场景的价值评估

| 子项 | 量化场景价值 | 建议 |
|------|-------------|------|
| V1 spawn_agent | **中**：可委派"批量分析 N 只股票"给子 agent，但 asyncio.gather 已能解决 | 暂不实现 |
| V2 delegated-agent 工厂 | **低**：基础设施已有，无具体应用 | 暂不实现 |
| V3 subagent-prompts | **低**：无 IDE 集成，等价于直接传 prompt | 暂不实现 |
| V4 configured-agent-tool | **中**：可配置"分析师 agent / 写作员 agent"，但 SkillsTool 已覆盖指令注入 | 暂不实现 |
| V5 multi-agent 协作 | **低**：量化任务无需 lead + teammate 协作 | 暂不实现 |
| V6 projections | **低**：依赖 V5 | 暂不实现 |
| V7 AgentConfigLoader | **低**：无多 agent 配置需求 | 暂不实现 |
| V8 工具集限制 | **低**：防递归，无 spawn_agent 即无递归风险 | 暂不实现 |
| V9 max_iterations 独立 | **低**：基础设施已支持 | 暂不实现 |
| V10 事件冒泡 | **低**：基础设施已支持 | 暂不实现 |

### 7.3 替代方案

量化场景下，以下替代方案已能覆盖子 agent 的核心价值：

1. **SkillsTool（已实现）**：专业化指令注入，覆盖 80% 的"专家 agent"需求
   - 例如：`use_skill("financial-analysis", args="分析600875.SH财务")`
   - 主 agent 收到 SKILL.md 指令后，用完整工具集执行
   - 优点：无子 agent 上下文切换开销、无 max_iterations 限制、工具集完整
   - 缺点：无隔离（共享 messages），但量化场景下隔离反而增加上下文同步成本

2. **asyncio.gather（语言原生）**：并行多任务
   - 例如：同时分析 10 只股票 → `await asyncio.gather(*[analyze(stock) for stock in stocks])`
   - 优点：无需多 agent 协作原语
   - 缺点：无任务依赖、无邮箱，但量化场景通常无此需求

3. **Plan Mode + 多轮对话（已实现）**：分治复杂任务
   - 主 agent 在 Plan Mode 下拆解任务，逐个执行
   - 优点：单 agent 上下文连续，无事件冒泡开销
   - 缺点：无并行，但量化场景多数任务串行更安全（避免数据竞争）

### 7.4 实现建议

**结论**：**不建议在量化场景实现子 agent / 多 agent 协作**。

**理由**：
1. 量化任务以"数据 → 因子 → 回测 → 报告"流水线为主，单 agent + SkillsTool 已能覆盖
2. 多 agent 协作的复杂度（任务依赖、邮箱、运行队列、故障恢复）与量化场景的简单流水线不匹配
3. 子 agent 上下文切换会增加 prompt 长度（每次 spawn 需传 systemPrompt + task），与 context compaction 目标冲突
4. 现有 `parent_agent_id` 字段为未来接入预留，如需求变化可低成本实现 V1+V2+V8+V9+V10 子集

**触发实现的条件**：
- 出现"需要并行分析 50+ 只股票"且 asyncio.gather 性能不足
- 出现"需要 lead agent 调度多个长时运行 teammate"的协作场景
- 出现"需要 yaml 配置专家 agent 工具"且 SkillsTool 无法满足

---

**阶段 V 结论**：本阶段对齐度约 10%，全部 10 个子项为 P2 级别缺失或弱对齐。Phase 27 主动移除技能子 agent 后，本系统不再有子 agent 路径，仅保留 `parent_agent_id` / `EventEmitter` / `max_iterations` 三个底层字段为未来接入预留。考虑到量化场景的特性（单 agent + SkillsTool 已覆盖核心需求，多 agent 协作为过度设计），建议保留现状，不实现 spawn_agent 工具链。如未来触发条件出现，优先实现 V2 + V1 + V10 + V9 + V8 子集即可覆盖单层 spawn 场景，跳过 V3/V4/V5/V6/V7 等多 agent 协作高级特性。
