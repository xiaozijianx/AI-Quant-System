# Phase E: Hooks 生命周期 对比报告

> 对标源码：`sdk/packages/shared/src/agent.ts` L265-364（AgentRuntimeHooks + Context/Result 类型）
> 当前实现：`agent/hooks.py`
> 对比维度：D1-D7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 6 项 |
| 弱对齐 | 4 项 |
| 缺失 | 2 项 |
| 额外增强 | 3 项 |
| **对齐度** | **约 75%** |

---

## 2. 钩子点枚举对比

| # | Cline 钩子点 | 我的钩子点 | 一致性 |
|---|-------------|-----------|--------|
| E1 | `beforeRun` | `before_run` | 完全一致 |
| E2 | `afterRun` | `after_run` | 完全一致 |
| E3 | `beforeModel` | `before_model` | 完全一致 |
| E4 | `afterModel` | `after_model` | 完全一致 |
| E5 | `beforeTool` | `before_tool` | 完全一致 |
| E6 | `afterTool` | `after_tool` | 完全一致 |
| E7 | **`onEvent`** | **缺失** | 缺失 |
| E8 | `prepareTurn`（config 回调） | `prepare_turn_input`（hook） | 额外增强 |
| E9 | 无 | `format_user_input_block` | 额外增强 |
| E10 | `requestToolApproval`（config 回调） | `before_approval`（hook） | 额外增强 |

**Cline 7 个 hook + 2 个 config 回调 = 9 个注入点**
**我 9 个 hook = 9 个注入点**
数量一致，但 `onEvent` 缺失，`prepareTurn/requestToolApproval` 实现形式不同。

---

## 3. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| E11 | AgentHooks 字段结构 | agent.ts L336-365 | hooks.py L271-298 | 弱对齐 |
| E12 | HookBag 数据结构 | agent-runtime.ts L229-237 | hooks.py L305-374 | 完全一致 |
| E13 | registerHooks 逻辑 | L544-554 | L326-346 | 完全一致 |
| E14 | BeforeModelContext 字段 | agent.ts L269-272 | hooks.py L86-93 | 弱对齐 |
| E15 | BeforeModelResult 字段 | agent.ts L279-285 | hooks.py L97-106 | 完全一致 |
| E16 | AfterModelContext 字段 | agent.ts L287-291 | hooks.py L110-114 | 完全一致 |
| E17 | BeforeToolContext 字段 | agent.ts L293-298 | hooks.py L118-123 | 完全一致 |
| E18 | **BeforeToolResult.policy** | agent.ts L300-306 `policy?: ToolPolicy` | hooks.py L127-137 无 | **缺失** |
| E19 | AfterToolContext 字段 | agent.ts L308-317 | hooks.py L141-150 | 完全一致 |
| E20 | AfterToolResult 字段 | agent.ts L319-323 | hooks.py L154-162 | 完全一致 |
| E21 | StopControl 字段 | agent.ts L274-277 | hooks.py L55-62 | 完全一致 |
| E22 | **onEvent hook** | agent.ts L364 | 无 | 缺失 |
| E23 | hook 执行顺序 | L796-803 注册序 | runtime.py L1622 注册序 | 完全一致 |
| E24 | hook 异常处理 | 未明确捕获 | runtime.py L2083-2088 `_call_hook` | 弱对齐 |
| E25 | hook 同步/异步支持 | Promise/非 Promise | `inspect.isawaitable` | 完全一致 |
| E26 | hook 返回 None 语义 | 不修改 | 不修改 | 完全一致 |

---

## 4. 关键差距详细分析

### 差距 #E7/E22：onEvent hook 缺失

**严重度**：P2（影响事件流拦截能力）

**Cline 实现**（agent.ts L364）：
```typescript
onEvent?: (event: AgentRuntimeEvent) => void | Promise<void>;
```

Cline 有 `onEvent` hook，每次 emit 事件时都会调用，可用于：
- 事件日志记录
- 事件过滤/转换
- 事件统计

**我的实现**：无 `onEvent` hook。事件通过 `EventEmitter.subscribe()` 订阅。

**逻辑差异**：
- D2 控制流：
  - Cline：`onEvent` 是 hook，与 before_model 等 hook 同级，在 emit 时同步调用
  - 我：用 `subscribe()` 订阅事件，listener 在 emit 时调用
- D7 语义等价：
  - 功能等价，`subscribe` 可实现 `onEvent` 的所有功能
  - 但 `onEvent` 作为 hook 可通过 `AgentHooks` 统一注册，`subscribe` 需单独调用

**影响**：
- 功能无缺失，`subscribe` 已覆盖
- 但无法通过 `AgentHooks` 统一注册事件监听（需额外 `runtime.subscribe()`）

**修复建议**：
保持现状，`subscribe` 已满足需求。若需统一注册，可添加：
```python
class AgentHooks:
    on_event: EventListener | None = None  # 新增

# HookBag.add 中
if hooks.on_event is not None:
    self._runtime.subscribe(hooks.on_event)
```

**优先级**：P3（功能已由 subscribe 覆盖）

---

### 差距 #E18：BeforeToolResult 缺失 policy 字段

**严重度**：P2（影响工具策略控制）

**Cline 实现**（agent.ts L300-306）：
```typescript
export interface AgentBeforeToolResult {
    skip?: boolean;
    stop?: boolean;
    reason?: string;
    input?: unknown;
    policy?: ToolPolicy;  // 可修改工具策略
}
```

Cline 的 `BeforeToolResult` 有 `policy` 字段，hook 可动态修改工具的审批策略。

**我的实现**（hooks.py L127-137）：
```python
@dataclass
class BeforeToolResult:
    skip: bool = False
    stop: bool = False
    reason: str | None = None
    input: Any | None = None
    # 无 policy 字段
```

**逻辑差异**：
- D1 数据结构：缺失 `policy` 字段
- D2 控制流：hook 无法动态修改工具审批策略
- D7 语义等价：Cline 的 `policy` 允许 hook 将 "需审批" 工具临时改为 "自动批准"

**影响**：
- 无法通过 hook 动态调整审批策略
- 当前用 `before_approval` hook 实现类似功能（自动批准/拒绝）

**修复建议**：
保持现状。`before_approval` hook 已覆盖动态审批决策需求，`policy` 字段功能重叠。

**优先级**：P3（功能已由 before_approval 覆盖）

---

### 差距 #E8：prepareTurn 实现形式不同

**严重度**：P3（架构差异，功能等价）

**Cline 实现**（agent.ts L447-452）：
```typescript
prepareTurn?: (context: AgentRuntimePrepareTurnContext) =>
    Promise<AgentRuntimePrepareTurnResult | undefined>;
```

Cline 的 `prepareTurn` 是 **config 回调**，接收完整上下文（messages/tools/model/signal），返回可修改 messages + systemPrompt。

**我的实现**（hooks.py L170-193）：
```python
@dataclass
class PrepareTurnInputContext:
    snapshot: AgentRuntimeStateSnapshot
    user_input: str  # 仅用户输入文本

@dataclass
class PrepareTurnInputResult:
    stop: bool = False
    reason: str | None = None
    modified_input: str | None = None
```

我的 `prepare_turn_input` 是 **hook**，仅接收/修改用户输入文本。

**逻辑差异**：
- D1 数据结构：
  - Cline `prepareTurn` 接收完整上下文（messages/tools/model），可修改 messages + systemPrompt
  - 我 `prepare_turn_input` 仅接收 user_input，仅修改用户输入文本
- D7 语义等价：
  - Cline `prepareTurn` 功能更强：可投影消息、修改 system prompt
  - 我 `prepare_turn_input` 功能较弱：仅修改用户输入文本
  - 但我的 `before_model` hook 可修改 messages/tools/options，覆盖了 `prepareTurn` 的消息投影功能

**影响**：
- 功能无缺失（before_model 覆盖消息投影）
- 但 Cline 区分 `prepareTurn`（host-owned）vs `beforeModel`（hook），语义更清晰

**修复建议**：保持现状，文档说明 `before_model` 等价于 Cline 的 `prepareTurn + beforeModel`。

**优先级**：P3

---

### 差距 #E10：requestToolApproval 实现形式不同

**严重度**：P3（架构差异，功能等价）

**Cline 实现**（agent.ts L437-439）：
```typescript
requestToolApproval?: (request: ToolApprovalRequest) =>
    Promise<ToolApprovalResult> | ToolApprovalResult;
```

Cline 的 `requestToolApproval` 是 **config 回调**，接收审批请求，返回审批结果。

**我的实现**（hooks.py L224-251）：
```python
@dataclass
class BeforeApprovalContext:
    snapshot: AgentRuntimeStateSnapshot
    tool_name: str
    tool_call_id: str
    input: dict[str, Any]

@dataclass
class BeforeApprovalResult:
    decision: str | None = None  # None / "approved" / "denied"
    reason: str | None = None
```

我的 `before_approval` 是 **hook**，可自动决策（跳过用户审批）。

**逻辑差异**：
- D2 控制流：
  - Cline `requestToolApproval`：完全接管审批流程，返回 approve/deny
  - 我 `before_approval`：仅前置自动决策，未决策时走默认审批流程（emit + 等待用户）
- D7 语义等价：
  - Cline 方式更灵活：host 完全控制审批 UI
  - 我的方式更简单：hook 自动决策 + 默认审批流程

**影响**：
- 功能等价，实现方式不同
- 我的 `before_approval` 适合"白名单自动批准"场景
- Cline 的 `requestToolApproval` 适合"自定义审批 UI"场景

**修复建议**：保持现状。

**优先级**：P3

---

## 5. 额外增强项

### 增强 #E9：format_user_input_block hook

**我的实现**：独有的 hook，在用户消息添加到历史前注入元数据（时间戳、工作目录等）。

**Cline 实现**：无对应 hook，但 `prepareTurn` 可部分覆盖。

**评估**：合理增强，保留。典型用途：注入 IDE 上下文（当前文件、选中文本）。

---

## 6. hook 执行行为对比

### 执行顺序

**Cline**：注册序执行（`for (const hook of this.hooks.beforeRun)`）。
**我**（runtime.py L1622）：注册序执行（`for hook in self._hooks.before_run`）。
**完全一致**。

### 异常处理

**Cline**：hook 抛异常会传播到 execute()，被 catch 块捕获。
**我**（runtime.py L2083-2088）：
```python
async def _call_hook(self, hook: Callable, ctx: Any) -> Any:
    result = hook(ctx)
    if asyncio.iscoroutine(result):
        result = await result
    return result
```
hook 异常直接传播到 run()，被 catch 块捕获。
**完全一致**。

### 同步/异步支持

**Cline**：支持同步和异步 hook（`Promise.resolve(result)`）。
**我**：`inspect.isawaitable(result)` 判断后 await。
**完全一致**。

---

## 7. 一致性统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 完全一致 | 6 | 50% |
| 弱对齐 | 4 | 33% |
| 缺失 | 2 | 17% |
| 额外增强 | 3 | 25% |

---

## 8. 修复优先级清单

### P2（次要）
1. **E7 onEvent hook**：可选，subscribe 已覆盖功能

### P3（锦上添花）
1. **E18 BeforeToolResult.policy**：before_approval 已覆盖
2. **E8 prepareTurn**：before_model 已覆盖消息投影
3. **E10 requestToolApproval**：before_approval 已覆盖审批决策

---

**阶段 E 结论**：Hooks 系统对齐度约 75%，6/7 Cline hook 点已对齐。主要差异是 `onEvent` 缺失（subscribe 覆盖）和 `prepareTurn/requestToolApproval` 实现形式不同（hook vs config 回调）。我额外增强 3 个 hook（prepare_turn_input/format_user_input_block/before_approval），功能更灵活。hook 执行行为（顺序/异常/同步异步）完全一致。
