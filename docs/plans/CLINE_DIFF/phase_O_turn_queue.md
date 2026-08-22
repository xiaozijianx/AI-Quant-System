# Phase O: Turn Queue 用户输入排队 对比报告

> 对标源码：`sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` + `sdk/packages/agents/src/agent-runtime.ts` L841-852 / L1252-1269
> 当前实现：`agent/turn_queue.py` + `agent/runtime.py` L694-720 + `agent/server.py` L88-158 / L683-695 / L838-905 / L995-1067
> 对比维度：O1-O13

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 4 项 |
| 弱对齐 | 4 项 |
| 缺失 | 3 项 |
| 额外增强 | 2 项 |
| **对齐度** | **约 50%** |

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| O1 | `PendingPromptEntry` 字段 | pending-prompt-service.ts L16-23 | turn_queue.py L51-71 | 弱对齐（快照多 `mode` 字段） |
| O2 | `delivery` 枚举 | pending-prompt-service.ts L14 | turn_queue.py L69 | 弱对齐（str 而非字面量类型） |
| O3 | `enqueue()` 入队语义 | pending-prompt-service.ts L137-175 | turn_queue.py L122-195 | 完全一致 |
| O4 | `consume()` 消费时机（queue drain） | pending-prompt-service.ts L295-335 + controller L281-335 | server.py L683-695 + turn_queue.py L519-611 | 缺失（drain 不启动新 run） |
| O5 | `consume_for_steer()` 消费时机 | agent-runtime.ts L841-852 | runtime.py L694-720 | 完全一致 |
| O6 | steer 插入位置 | agent-runtime.ts L844-850 + L1261-1262 | runtime.py L709-716 | 完全一致 |
| O7 | queue 自动启动新 run | controller.drain L310-317 `await this.deps.send()` | server.py L123-143 send_callback 为空操作 | 缺失（P0） |
| O8 | 状态持久化 | 内存（ActiveSession.pendingPrompts） | 内存（controller._states dict） | 完全一致（均内存） |
| O9 | `list_pending()` 查询 | controller.list L212-214 | server.py L999-1012 GET 端点 | 完全一致 |
| O10 | `delete()` 删除 | controller.delete L227-236 + emit + scheduleDrain | server.py L1015-1027 DELETE 端点 | 弱对齐（emit/drain 为空操作） |
| O11 | `update()` 更新 | controller.update L216-225 + service.update L59-108 | server.py L1030-1056 PUT 端点 + turn_queue.py L244-300 | 弱对齐（emit/drain 为空操作） |
| O12 | SSE 事件通知 | controller.emitPrompts L271-279 + emitSubmitted L337-351（`pending_prompts` / `pending_prompt_submitted`） | server.py L880 `pending_prompts_updated` + L689 `pending_prompts_drained`（事件名不同且 submitted 事件未发射） | 缺失（事件名不一致 + submitted 未透传） |
| O13 | 前端排队 badge | webview-ui（pending prompts 面板） | static/js/ai-chat.js（无任何处理） | 缺失（P0） |
| 额外1 | `clear()` 显式清空 | 无（仅有 `clearAborted`） | turn_queue.py L479-487 + server.py L1059-1067 | 额外增强 |
| 额外2 | `pending_prompts_drained` 事件 | 无 | server.py L683-695 | 额外增强（但前端未消费） |

---

## 3. 关键差距详细分析

### 差距 #O1：PendingPromptEntry 快照多 `mode` 字段

**严重度**：P3（信息泄漏级别低）

**Cline 实现**：
- `PendingPromptEntry` 内部结构包含 `mode`（pending-prompt-service.ts L19）
- `snapshotPrompt()` 返回的 `SessionPendingPrompt` 不含 `mode`（events.ts L41-48），仅含 `id/prompt/delivery/attachmentCount/userImages/userFiles`

**我的实现**：
- `PendingPromptEntry` dataclass 含 `mode`（turn_queue.py L68）
- `snapshot_prompt()` 返回的字典**额外包含** `mode` 字段（turn_queue.py L93）

**影响**：
- 前端能拿到 `mode` 字段，比 Cline 多了一个信息维度
- 不影响功能，但与 Cline 的快照契约不一致

**修复建议**：从 `snapshot_prompt()` 移除 `mode` 字段，保持与 Cline `SessionPendingPrompt` 一致；`mode` 仅在内部 entry 中保留。

**优先级**：P3

---

### 差距 #O2：delivery 枚举类型约束

**严重度**：P3（运行时无防护）

**Cline 实现**：
- `PendingPromptDelivery = "queue" | "steer"` 字面量联合类型（L14）
- TypeScript 编译期阻止其他值

**我的实现**：
- `delivery: str = "queue"`（turn_queue.py L69）
- 仅在 server.py L862-863 做运行时校验（`if delivery not in ("queue", "steer")`）
- service 层无校验，可直接传入任意字符串

**影响**：
- 内部调用 `service.enqueue()` 不经过 server.py 校验时，可传入非法 delivery 值
- 不会导致崩溃，但行为未定义（既不是 steer 也不是 queue 时按 queue 处理）

**修复建议**：使用 `Literal["queue", "steer"]` 或定义常量 Enum，在 service 层也加校验。

**优先级**：P3

---

### 差距 #O4 + #O7：queue 类型消息消费链路断裂（P0 核心）

**严重度**：P0（核心功能不可用）

**Cline 实现**：
1. `enqueue()` 后调用 `scheduleDrain()`（controller L281-293）
2. `scheduleDrain()` 检查 `canStartRun()` 后用 `queueMicrotask(() => this.drain())` 调度
3. `drain()` 调用 `shiftNext()` 取出队首，然后 `await this.deps.send({...})` **直接启动新 run**（controller L310-317）
4. send 成功后若队列还有，递归 `queueMicrotask(() => this.drain())` 继续
5. send 失败时 `requeueFront()` 把 entry 放回队首

关键点：Cline 的 `drain` 在 run 结束后**自动**启动下一个 run 消费队列，无需前端介入。

**我的实现**：
1. `enqueue()` 后调用 `_schedule_drain()`（turn_queue.py L519-551）
2. `_schedule_drain()` 检查 `can_start_run`：runtime 运行中时返回 `(is_aborting, False, False)`，跳过调度（正确）
3. run 结束后 runtime 从 `_active_runtimes` 弹出（server.py L630），此时 `can_start_run=True`，但**没有任何代码再次调用 `_schedule_drain()`**
4. `_sse_generator` 末尾 yield `pending_prompts_drained` 事件（server.py L683-695）告知前端
5. `send_callback` 是**空操作**（server.py L123-143），仅记录日志，不启动新 run
6. 前端 `ai-chat.js` **不处理** `pending_prompts_drained` 事件（L483-514 的 switch 无此 case）

**影响**：
- queue 类型消息入队后**永远不会被消费**（除非用户手动发新消息，但新消息会启动新 run 而非消费队列）
- 队列条目会一直堆积，直到 session 清理或 abort
- Cline 的"运行中排队，结束后自动依次处理"核心语义**完全丢失**
- 用户感知：发了一条消息在 agent 运行中，agent 跑完后这条消息消失（实际在队列里但无人消费）

**修复建议**：
- **短期**：在 `_sse_generator` 末尾（run 结束后）若队列非空，直接在服务端启动新 run 消费下一条（复用 `run_agent()` 逻辑），而非依赖前端
- **中期**：实现 SSE 连接复用，让 `drain()` 能通过原 SSE 连接推送事件
- **长期**：`send_callback` 改为真正启动后台 run 任务，对齐 Cline `await this.deps.send()`

**优先级**：P0

---

### 差距 #O10 + #O11：delete/update 后 emit 与 drain 为空操作

**严重度**：P2（功能可用但无事件通知 + 无自动消费）

**Cline 实现**：
- `controller.delete()` → `service.delete()` → `emitPrompts()` 发射 `pending_prompts` 事件 → `scheduleDrain()` 检查并自动消费
- `controller.update()` → `service.update()` → `emitPrompts()` → `scheduleDrain()`

**我的实现**：
- `controller.delete()` 调用 `_emit_prompts()`，但 `_emit_callback` 是**空操作**（server.py L145-151，仅 `logger.debug`）
- `controller.update()` 同理
- `_schedule_drain()` 即使被调用，因 `send_callback` 为空操作，drain 不启动新 run
- 真正的 SSE 事件由 server.py 端点直接返回 `{"removed": ..., "prompts": ...}` HTTP 响应，不通过 SSE 推送

**影响**：
- 前端通过 HTTP 响应能拿到删除/更新结果，但**无法实时感知**其他客户端的删除/更新操作
- 删除 queue 类型条目后，不会触发 drain（但因 O4 已断，此处影响可忽略）

**修复建议**：让 `emit_callback` 真正向 SSE 队列推送事件，而非空操作。需要重构 controller 与 server 的 SSE 通道连接。

**优先级**：P2

---

### 差距 #O12：SSE 事件名不一致 + submitted 事件未透传

**严重度**：P1（事件契约不对齐）

**Cline 实现**：
- 事件类型：`pending_prompts`（队列状态变化）+ `pending_prompt_submitted`（条目被消费/提交时）
- `pending_prompts` 在 enqueue/update/delete/consumeSteer/drain 时发射
- `pending_prompt_submitted` 在 consumeSteer 和 drain 取出条目时发射
- 定义见 events.ts L84-88

**我的实现**：
- `turn_queue.py` controller 内部发射 `pending_prompts` 和 `pending_prompt_submitted`（L494, L507），但 `emit_callback` 为空操作，**事件不到达前端**
- `server.py` 实际发射的事件名是 `pending_prompts_updated`（L880，enqueue 时）和 `pending_prompts_drained`（L689，run 结束时）
- `pending_prompt_submitted` **从未发射到 SSE**
- 事件名与 Cline 不一致：`pending_prompts_updated` vs `pending_prompts`，`pending_prompts_drained` 是额外事件

**影响**：
- 前端无法通过标准事件名感知队列状态变化
- `pending_prompt_submitted` 缺失：前端无法知道哪条条目被消费了（steer 或 queue）
- 事件契约与 Cline 不对齐，跨端兼容性差

**修复建议**：
1. 统一事件名为 `pending_prompts` 和 `pending_prompt_submitted`，移除 `pending_prompts_updated` 命名
2. 让 `emit_callback` 真正向 SSE 通道推送事件（需解决 controller 与 SSE generator 的通道连接）
3. 保留 `pending_prompts_drained` 作为额外增强事件（用于通知前端"run 结束，可消费 queue"）

**优先级**：P1

---

### 差距 #O13：前端排队 badge 完全缺失

**严重度**：P0（用户体验不可用）

**Cline 实现**：
- webview-ui 提供 pending prompts 面板/badge，实时显示排队数量
- 用户可查看/编辑/删除排队条目
- 通过 `pending_prompts` 事件实时更新

**我的实现**：
- `static/js/ai-chat.js` 的 `_handleSSEEvent`（L483-514）仅处理：`phase/token/plan/tool_call/tool_output/todos_updated/mode_changed/approval_request/done/error`
- **不处理** `pending_prompts_updated` / `pending_prompts_drained` / `pending_prompt_submitted` 任何事件
- 无排队 badge UI、无排队列表展示、无编辑/删除入口
- 前端虽然后端提供了 `GET/DELETE/PUT /pending_prompts` 端点，但前端从不调用

**影响**：
- 用户在 agent 运行中发送的消息**无任何视觉反馈**（不知道已排队）
- 用户无法查看/管理排队消息
- 配合 O4 的 drain 断裂，用户体验为"消息消失"——发了消息没反应，也不知道在队列里

**修复建议**：
1. 在输入框附近添加排队 badge（显示数字）
2. 添加排队列表下拉/面板，支持编辑/删除
3. 监听 `pending_prompts` / `pending_prompt_submitted` 事件更新 UI
4. 监听 `pending_prompts_drained` 事件主动发起新 /stream 请求消费下一条（作为 O4 短期方案的补充）

**优先级**：P0

---

## 4. 一致性统计

| 一致性等级 | 数量 | 子项 |
|-----------|------|------|
| 完全一致 | 4 项 | O3, O5, O6, O8, O9（含 O9 共 5 项，扣除外加增强） |
| 弱对齐 | 4 项 | O1, O2, O10, O11 |
| 缺失 | 3 项 | O4, O7, O12, O13（共 4 项） |
| 额外增强 | 2 项 | `clear()` 显式清空、`pending_prompts_drained` 事件 |

> 注：O9 同时算完全一致，统计已合并。实际对齐度约 50%（核心 queue 消费链路断裂导致 O4/O7/O13 三项 P0 缺失）。

---

## 5. 修复建议

### 短期（P0 修复，恢复 queue 消费链路）

1. **服务端自动消费 queue**：在 `_sse_generator` 末尾（run 结束后）若 `controller.list(session_id)` 非空，循环取出队首并在服务端直接启动新 run（复用 `run_agent()` 逻辑），直到队列空或失败。这样不依赖前端，对齐 Cline `drain` 语义。

2. **前端添加排队 badge**：
   - 在 `ai-chat.js` 的 `_handleSSEEvent` 添加 `pending_prompts` / `pending_prompt_submitted` / `pending_prompts_drained` 三个 case
   - 输入框旁添加 badge 显示排队数
   - 收到 `pending_prompts_drained` 时主动发起新 /stream 请求（作为短期方案，与服务端自动消费二选一）

### 中期（P1/P2 修复，对齐事件契约）

3. **统一事件名**：将 `pending_prompts_updated` 改为 `pending_prompts`，保留 `pending_prompts_drained` 作为额外增强。补齐 `pending_prompt_submitted` 事件透传。

4. **emit_callback 真实化**：让 controller 的 `emit_callback` 真正向 SSE 通道推送事件，而非空操作。需重构 controller 与 server 的通道连接（可用 asyncio.Queue 桥接）。

5. **send_callback 真实化**：让 `send_callback` 真正启动后台 run 任务，对齐 Cline `await this.deps.send()`，使 drain 能自动连续消费。

### 长期（P3 修复，契约对齐）

6. **delivery 枚举约束**：用 `Literal["queue", "steer"]` 替换 `str`，service 层加校验。

7. **snapshot 移除 mode**：从 `snapshot_prompt()` 移除 `mode` 字段，与 Cline `SessionPendingPrompt` 契约一致。

8. **SSE 连接复用**：实现长连接 SSE，让 drain 启动的新 run 能通过原连接推送事件，彻底对齐 Cline 的单连接自动消费模型。

---

## 6. 验证记录

### 6.1 文件读取验证

| 文件 | 路径 | 行数 | 状态 |
|------|------|------|------|
| Cline 源码 | `third_party/cline/sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` | 1-385 | 已读 |
| Cline 事件类型 | `third_party/cline/sdk/packages/core/src/types/events.ts` L41-88 | - | 已读 |
| Cline consume 调用点 | `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L841-852 | - | 已读 |
| Cline consume 实现 | `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L1252-1269 | - | 已读 |
| 我的 turn_queue | `agent/turn_queue.py` | 1-639 | 已读 |
| 我的 runtime | `agent/runtime.py` L680-720 | - | 已读 |
| 我的 server | `agent/server.py` L88-158 / L300-336 / L615-695 / L838-1067 | - | 已读 |
| 我的前端 | `static/js/ai-chat.js` L480-540 | - | 已读 |

### 6.2 关键代码片段验证

**Cline drain 自动启动新 run**（pending-prompt-service.ts L310-317）：
```typescript
await this.deps.send({
    sessionId,
    prompt: next.prompt,
    ...(next.mode ? { mode: next.mode } : {}),
    userImages: next.userImages,
    userFiles: next.userFiles,
});
```

**我的 send_callback 空操作**（server.py L123-143）：
```python
async def send_callback(session_id, prompt, mode, user_images, user_files):
    logger.info("turn_queue: drain session=%s prompt=%d字符（前端将主动消费）", ...)
    # 不抛异常，让 controller 认为发送成功，继续 drain 下一条
    # 真正的 run 由前端发起新 /stream 请求触发
```

**前端不处理 turn_queue 事件**（ai-chat.js L483-514）：
```javascript
switch (data.type) {
    case 'phase': ... break;
    case 'token': ... break;
    case 'plan': ... break;
    case 'tool_call': ... break;
    case 'tool_output': ... break;
    case 'todos_updated': ... break;
    case 'mode_changed': ... break;
    case 'approval_request': ... break;
    case 'done': break;
    case 'error': ... break;
    // 无 pending_prompts / pending_prompts_drained / pending_prompt_submitted
}
```

### 6.3 核心结论

- **steer 路径（O5/O6）完全可用**：runtime.py L694-720 在 iteration > 1 时通过 `consume_pending_user_message` 回调从 turn_queue 取 steer 消息，追加到 model request，并发射 message_added 事件。逻辑与 Cline agent-runtime.ts L841-852 / L1252-1269 等价。
- **queue 路径（O4/O7）完全断裂**：`send_callback` 为空操作 + 前端不处理 `pending_prompts_drained` 事件 + run 结束后无代码触发 drain，导致 queue 类型消息入队后永不消费。
- **前端（O13）完全缺失**：无 badge、无排队列表、无事件监听。
- **事件契约（O12）不一致**：事件名不同 + `pending_prompt_submitted` 未透传。
- **纯逻辑层（O3/O8/O9）对齐良好**：enqueue 语义、内存持久化、list 查询均与 Cline 一致。
