# Phase N: AbortController 与中止语义 对比报告

> 对标源码：`sdk/packages/agents/src/agent-runtime.ts` L424-470, L588-593, L791-793
> 当前实现：`agent/abort.py` + `agent/runtime.py` L339-352, L469-474, L664-666
> 对比维度：D1-D7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 4 项 |
| 弱对齐 | 3 项 |
| 缺失 | 3 项 |
| 偏离 | 2 项 |
| **对齐度** | **约 60%** |

---

## 2. 详细对比表

| # | 对比项 | Cline 行号 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| N1 | signal 类型 | L424 `AbortController` | abort.py L59 `asyncio.Event` | 弱对齐 |
| N2 | abort() 幂等检查 | L458-460 已 aborted 则 return | 无 | 缺失 |
| N3 | abort() reason 处理 | L461-464 `AgentRuntimeAbortError` | abort.py L72-79 str reason | 弱对齐 |
| N4 | abort() 设置 lastError | L465 `state.lastError = abortError.message` | runtime.py L350 `state.last_error = reason` | 完全一致 |
| N5 | abort() telemetry 事件 | L466-468 `captureTaskLifecycle` | 无 | 缺失 |
| N6 | abort() 触发 signal | L469 `abortController.abort(abortError)` | abort.py L79 `_signal.set()` | 完全一致 |
| N7 | throwIfAborted 调用点 | L633, L796, stream 内 | runtime.py L520, L748, L1719 | 完全一致 |
| N8 | signal 透传到 model.stream | L831 `request.signal = abortController.signal` | runtime.py L738 `abort_signal=self._abort_controller.signal` | 完全一致 |
| N9 | signal 透传到 tool.execute | `AgentToolContext.signal` | runtime.py L1365 `abort_signal=self._abort_controller.signal` | 完全一致 |
| N10 | 每轮创建新 AbortController | L601 `new AbortController()` | runtime.py L474 `_abort_controller.reset()` | 偏离 |
| N11 | finally 清理 | L792 `abortController = undefined` | runtime.py L665 `_aborted = False` | 弱对齐 |
| N12 | **子进程 kill on abort** | AbortSignal 触发时 kill | 无 kill | 缺失 |
| N13 | restore() 中 abort 调用 | L488 `this.abort("Agent state restored")` | runtime.py L323 `self.abort("Agent state restored")` | 完全一致 |

---

## 3. 关键差距详细分析

### 差距 #N2：abort() 幂等检查缺失

**严重度**：P2（影响重复 abort 行为）

**Cline 实现**（L454-460）：
```typescript
abort(reason?: unknown): void {
    if (!this.abortController) {
        return;
    }
    if (this.abortController.signal.aborted) {
        return;  // 已 aborted，幂等返回
    }
    // ...
}
```

Cline 在 abort 时先检查是否已 aborted，避免重复触发。

**我的实现**（runtime.py L339-352）：
```python
def abort(self, reason: str = "") -> None:
    self._aborted = True
    self._abort_reason = reason or "aborted by user"
    self._state.status = "aborted"
    self._state.last_error = self._abort_reason
    self._abort_controller.abort(self._abort_reason)
```

无幂等检查，重复调用 abort 会覆盖 reason 和 status。

**逻辑差异**：
- D2 控制流：Cline 幂等，我不幂等
- D6 边界条件：多次 abort 时，我的 reason 会被覆盖（可能丢失首次原因）

**影响**：
- 用户快速点两次"停止"按钮时，第二次 abort 覆盖首次 reason
- 实际影响小（reason 通常相同）

**修复建议**：
```python
def abort(self, reason: str = "") -> None:
    if self._aborted:
        return  # 幂等返回
    self._aborted = True
    # ...
```

**优先级**：P2

---

### 差距 #N5：abort() telemetry 事件缺失

**严重度**：P3（影响监控）

**Cline 实现**（L466-468）：
```typescript
this.captureTaskLifecycle(TASK_CANCELLED_EVENT, {
    error: abortError,
});
```

Cline 在 abort 时触发 `TASK_CANCELLED_EVENT` telemetry 事件。

**我的实现**：无 telemetry 上报。

**影响**：
- 无法监控 abort 事件
- 当前无 telemetry 系统（Phase Z）

**修复建议**：接入 telemetry 后补齐。

**优先级**：P3

---

### 差距 #N10：每轮创建新 AbortController vs reset

**严重度**：P3（实现差异，功能等价）

**Cline 实现**（L601）：
```typescript
this.abortController = new AbortController();  // 每轮新建
```

Cline 在每次 execute() 开头创建新的 AbortController。

**我的实现**（runtime.py L474）：
```python
self._abort_controller.reset()  # 重置现有
```

我重置现有的 AbortController（`_signal.clear()` + `_reason = ""`）。

**逻辑差异**：
- D3 状态变迁：
  - Cline：新对象，旧 signal 引用失效
  - 我：同一对象，clear 后可复用
- D7 语义等价：功能等价，reset 与 new 效果相同

**影响**：
- 若有外部持有旧 signal 引用，Cline 方式旧引用失效，我方式旧引用仍有效（但已 clear）
- 实际无影响（signal 仅在 run 期间使用）

**修复建议**：保持现状，功能等价。

**优先级**：P3

---

### 差距 #N12：子进程 kill on abort 缺失

**严重度**：P1（影响用户体验）

**Cline 实现**：AbortSignal 触发时，spawn 的子进程会被 kill。

**我的实现**：`run_commands` 工具用 `asyncio.create_subprocess_exec`，abort 时不 kill 子进程。

**逻辑差异**：
- D2 控制流：
  - Cline：abort → signal → 子进程 kill → 立即结束
  - 我：abort → signal → 工具检查点抛异常 → 但子进程仍在运行
- D6 边界条件：长命令（如 `npm install`）abort 后仍继续运行

**影响**：
- 用户点"停止"后，子进程仍在后台运行（消耗资源）
- 直到子进程自然结束或手动 kill

**修复建议**：
在 `run_commands.py` 中订阅 abort_signal，触发时 kill 子进程：
```python
async def execute(self, input, context):
    proc = await asyncio.create_subprocess_exec(...)
    
    # 监听 abort signal
    if context.abort_signal:
        async def _on_abort():
            await context.abort_signal.wait()
            proc.kill()
        asyncio.create_task(_on_abort())
    
    # 等待子进程或 abort
    await asyncio.wait(
        [proc.wait(), context.abort_signal.wait()],
        return_when=asyncio.FIRST_COMPLETED
    )
    if context.abort_signal.is_set():
        proc.kill()
        raise AbortedError("命令执行被中止")
```

**优先级**：P1（影响"停止"按钮的响应性）

---

## 4. 一致性统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 完全一致 | 4 | 31% |
| 弱对齐 | 3 | 23% |
| 缺失 | 3 | 23% |
| 偏离 | 2 | 15% |

---

## 5. 修复优先级清单

### P1（重要）
1. **N12 子进程 kill on abort**：run_commands 订阅 abort_signal，触发时 kill 子进程

### P2（次要）
1. **N2 abort 幂等检查**：重复 abort 时直接返回

### P3（锦上添花）
1. **N5 telemetry 事件**：接入 telemetry 后补齐
2. **N10 new vs reset**：保持现状，功能等价

---

**阶段 N 结论**：AbortController 对齐度约 60%，核心 signal 透传和 throw_if_aborted 检查点一致。主要差距是子进程 kill（用户停止后子进程仍运行）和幂等检查。建议优先修复子进程 kill。
