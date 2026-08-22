# Phase 2.11 Turn Queue 用户输入排队对比报告

## 1. 执行摘要

Cline 与 Charles 在 Turn Queue（用户输入排队）机制上整体语义已对齐：两者均采用 `PendingPromptService`（纯逻辑层）+ `PendingPromptsController`（依赖注入 + 调度层）的双层架构，支持 `queue`（排队等当前 run 结束自动消费）和 `steer`（实时插入到当前 iteration 的 model request）两种 delivery 模式，且都通过 `consumePendingUserMessage` 回调让 runtime 在 `iteration > 1` 时取走 steer 消息追加到 model request。

主要差距集中在三点：

1. **drain 触发方式与 send_callback 角色**：Cline 的 `drain()` 协程通过 `send_callback` 真实启动新 run（`runTurn`），由 `queueMicrotask` 自动调度；Charles 的 `send_callback` 实现为**空操作**，真实消费由 `_sse_generator` 末尾的 `while` 循环在原 SSE 连接上完成。Charles 的设计将 drain 与 SSE 连接绑定，SSE 断开后队列无法自动消费；Cline 的 drain 独立于 SSE 连接。
2. **steer 消息文本是否包裹 mode 标签**：Cline 在 `consumePendingUserMessage` 回调内通过 `formatModePrompt` → `formatUserInputBlock` 把 steer prompt 包裹为 `<user_input mode="...">...</user_input>`；Charles 的回调直接返回 `entry.prompt` 原始文本，runtime 创建消息时不包裹 mode 标签。
3. **drain 重入保护数据结构**：Cline 用 `session.drainingPendingPrompts: boolean` 单标志；Charles 用 `_draining: set[str]` 集合 + `_drain_tasks: dict[str, asyncio.Task]` 双结构（额外的 task 引用防止 GC）。Charles 多一层任务管理。

其余项（PendingPromptEntry 字段、delivery 枚举、enqueue 合并/插队语义、shiftNext/consumeSteer 消费、requeueFront 失败回退、clearAborted 中止清理、SSE 事件类型、list/delete/update 端点、状态持久化）均已**强对齐**。

nanobot 残留检查结论：在 Turn Queue 直接相关代码（`turn_queue.py` + `runtime.py` 的 `consume_pending_user_message` 分支 + `server.py` 的 turn queue 端点）中**未发现 nanobot 残留**；间接相关的 `server.py` 文件头有 3 处 nanobot 注释残留（类型 A：实现来源标注），**全部为注释残留**，**未发现实现逻辑残留**。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.11 章节定义的 11 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.11.1 | PendingPromptEntry 字段 | pending-prompt-service.ts L16-23 | turn_queue.py L51-71 | 字段完整对齐：id/prompt/mode/delivery/userImages/user_files。Cline 用 interface + camelCase；Charles 用 dataclass + snake_case。Charles 字段默认值更明确（mode=None, delivery="queue", user_images/user_files=default_factory=list） | 强对齐 |
| 2.11.2 | delivery 枚举 | pending-prompt-service.ts L14（`type PendingPromptDelivery = "queue" \| "steer"`） | turn_queue.py L69（`delivery: str = "queue"`） | Cline 用字面量联合类型（编译期校验）；Charles 用 str 无枚举校验。Charles 在 enqueue 时通过 `if delivery == "steer"` 分支处理，运行时行为一致 | 强对齐 |
| 2.11.3 | enqueue 入队语义 | pending-prompt-service.ts L137-175 | turn_queue.py L122-195 | 完全对齐：① 同 prompt 已存在时合并更新（splice + unshift/push）② steer 放队首（unshift/insert(0)）③ queue 放队尾（push/append）④ steer + queue 合并时升级为 steer ⑤ ID 生成格式 `pending_<timestamp>_<rand>`（Cline 用 nanoid(5)，Charles 用 uuid4().hex[:5]） | 强对齐 |
| 2.11.4 | consume 消费时机（queue 类型） | pending-prompt-service.ts L295-335（drain 协程）+ local-runtime-host.ts L928-930（runTurn 完成后 queueMicrotask 调度 drain） | server.py L760-829（_sse_generator 末尾 while 循环消费，调用 _run_once 启动新 run） | drain 触发路径不同：Cline 在 runTurn 完成后 `queueMicrotask(() => drain())`，drain 内部 `await send_callback()` 真实启动新 run；Charles 的 `_schedule_drain` 在 run 运行中因 `can_start_run=False` 跳过，run 结束后由 `_sse_generator` 末尾循环接管消费，`send_callback` 空操作 | 弱对齐 |
| 2.11.5 | consume_for_steer 时机（steer 类型） | agent-runtime.ts L841-852（iteration > 1 时调 consumePendingUserMessage 回调）+ local-runtime-host.ts L640-648（回调内调 consumeSteer） | runtime.py L859-882（iteration > 1 且 config.consume_pending_user_message 存在时调用回调）+ server.py L308-339（回调内调 controller.consume_steer） | 已对齐：两者都在 `iteration > 1` 时调用回调，回调内调用 `consumeSteer` 取出队首 steer 条目。Charles 额外在 `except` 中捕获异常返回 None，Cline 无 try/catch | 强对齐 |
| 2.11.6 | steer 插入位置 | agent-runtime.ts L843-851（`request.messages = [...request.messages, ...cloneMessages([pendingUserMessage])]`）+ L1262（`this.state.messages.push(message)`） | runtime.py L875-876（`self._state.messages.append(pending_msg)` + `request.messages = list(request.messages) + [pending_msg]`） | 已对齐：两者都同时追加到 state.messages（持久化）和 request.messages（本轮请求）。Cline 用 cloneMessages 深拷贝；Charles 用 list()+append 浅拷贝。两者都 emit message_added 事件 | 强对齐 |
| 2.11.7 | queue 自动启动新 run | local-runtime-host.ts L928-930（`queueMicrotask(() => void this.pendingPromptsController.drain(input.sessionId))`）+ drain L311 `await this.deps.send(...)` 真实启动 run | server.py L760-829（_sse_generator 末尾 while 循环 + _run_once 启动新 run）+ send_callback 空操作（L125-146） | 关键差异：Cline 的 drain 独立于 SSE 连接，由 `send_callback` 启动新 run，事件通过 onEvent 回调独立推送；Charles 的 drain 与 SSE 连接绑定，run 事件通过原 SSE 连接 yield 推送。Charles SSE 断开后队列无法自动消费 | 弱对齐 |
| 2.11.8 | 状态持久化 | session.ts L35（`pendingPrompts: PendingPrompt[]` 存于 ActiveSession 内存）+ local-runtime-host.ts L753（创建 session 时 `pendingPrompts: []`） | turn_queue.py L370（`self._states: dict[str, PendingPromptQueueState]` 内存）+ L376-380（get_state 懒初始化） | 均为内存存储，未持久化到磁盘。Cline 与 ActiveSession 生命周期绑定；Charles 由 controller 单例持有，session 销毁时需显式 clear | 强对齐 |
| 2.11.9 | list_pending 查询 | pending-prompt-service.ts L212-214（`list(sessionId)` → service.list(session)）+ local-runtime-host.ts L282-283（暴露为 pendingPrompts.list API） | server.py L1145-1158（GET `/sessions/{session_id}/pending_prompts` → controller.list(session_id)） | 已对齐：两者均返回 snapshot 数组（id/prompt/delivery/mode/attachment_count/user_images/user_files）。Cline 通过 hub API；Charles 通过 REST 端点 | 强对齐 |
| 2.11.10 | delete / update | pending-prompt-service.ts L216-236（controller.update/delete）+ L59-135（service.update/delete） | server.py L1161-1202（DELETE/PUT 端点 → controller.delete/update）+ turn_queue.py L244-323（service.update/delete） | 已对齐：update 支持 prompt/mode/delivery 修改（None 表示保持原值）；delete 按 prompt_id 移除。Charles service.update 内重新插入逻辑（steer 升级到队首、queue 降级到队尾）与 Cline insertUpdatedPrompt 等价 | 强对齐 |
| 2.11.11 | SSE 事件通知 | pending-prompt-service.ts L271-279（emitPrompts 发 `pending_prompts`）+ L337-351（emitSubmitted 发 `pending_prompt_submitted`）+ session-event-projector.ts L67-90（投影到 hub） | server.py L781-790（_sse_generator 内直接 yield `pending_prompts` + `pending_prompt_submitted`）+ L1026（入队时返回 `pending_prompts_updated`） | 事件类型差异：Charles 入队时发 `pending_prompts_updated`（Cline 无此事件名，入队时 Cline 发 `pending_prompts`）；消费时两者均发 `pending_prompts` + `pending_prompt_submitted`。Charles 的 `pending_prompts_updated` 携带 queued_message + delivery 字段，Cline 无 | 弱对齐 |

## 3. 重点差距详细说明

### 差距 1：drain 触发方式与 send_callback 角色（对应对比项 2.11.4、2.11.7）

**Cline 设计**（pending-prompt-service.ts L281-335 + local-runtime-host.ts L928-930）：

```
runTurn 完成
  → queueMicrotask(() => void pendingPromptsController.drain(sessionId))
  → drain() 内：
      ① 检查 session.aborting / drainingPendingPrompts / canStartRun
      ② shiftNext 取出队首
      ③ emitPrompts + emitSubmitted
      ④ session.drainingPendingPrompts = true
      ⑤ await this.deps.send({sessionId, prompt, mode, ...})  ← 真实启动新 run
      ⑥ catch 时 requeueFront + emitPrompts
      ⑦ finally 重置 drainingPendingPrompts，队列非空时 queueMicrotask 继续 drain
```

`send` 回调由 `local-runtime-host.ts` L279 注入为 `this.runTurn(input)`，即 drain 内部启动新 run，run 的事件通过 `onEvent` 回调（L651-656）独立推送到 hub，与原请求的 SSE 连接解耦。

**Charles 设计**（server.py L94-161 + L760-829）：

```
run 结束（_sse_generator 内 _run_once 完成）
  → while True 循环：
      ① controller._states.get(session_id) 取队列状态
      ② 队列空 → break
      ③ shift_next 取出队首
      ④ 队首是 steer → requeue_front + break（防御性，steer 应已被 iteration 消费）
      ⑤ yield pending_prompts + pending_prompt_submitted SSE 事件
      ⑥ 若 entry.mode 变化 → set_mode + 重建系统提示
      ⑦ async for sse in _run_once(entry.prompt, queued_messages, run_system_prompt): yield sse  ← 启动新 run
      ⑧ except 时 requeue_front + break
```

`send_callback`（L125-146）实现为**空操作**，仅记录日志：

```python
async def send_callback(session_id, prompt, mode, user_images, user_files) -> None:
    logger.info("turn_queue: drain session=%s prompt=%d字符（由 _sse_generator 末尾循环消费）", ...)
    # 不抛异常，让 controller 认为发送成功，继续 drain 下一条
    # 真正的 run 由 _sse_generator 末尾循环启动
```

**差异分析**：

| 维度 | Cline | Charles |
|------|-------|---------|
| drain 调度 | `queueMicrotask` 异步微任务 | SSE 生成器内 while 循环（同步串行） |
| send_callback | 真实启动新 run（`runTurn`） | 空操作 |
| 事件推送通道 | 独立 onEvent 回调 → hub | 原 SSE 连接 yield |
| SSE 断开影响 | 不影响 drain，新 run 事件通过 hub 推送 | drain 中断，队列残留 |
| drain 重入保护 | `session.drainingPendingPrompts: boolean` | `_draining: set[str]` + `_drain_tasks: dict[str, asyncio.Task]` |

**影响**：Charles 的设计在 SSE 连接稳定时工作正常，但若客户端断开重连，原 SSE 生成器会被取消，未消费的 queue 条目会滞留在内存队列中，需用户重新发消息触发新的 `/stream` 请求才能消费（但 `/stream` 入口会先检查 `_active_runtimes`，若 runtime 已结束则直接启动新 run，不会消费残留队列）。Cline 的 drain 与 SSE 连接解耦，hub 持有 session 状态，新连接可继续接收事件。

**Charles 的优势**：在单一 SSE 连接内闭环消费，事件时序清晰（同一连接按顺序推送），无需 hub 中转。Cline 的 drain 启动的新 run 事件可能跨多个 SSE 连接推送，前端需按 sessionId 关联。

### 差距 2：steer 消息文本是否包裹 mode 标签（对应对比项 2.11.5、2.11.6）

**Cline 设计**（local-runtime-host.ts L640-648）：

```typescript
consumePendingUserMessage: () => {
    const entry = this.pendingPromptsController.consumeSteer(sessionId);
    return entry
        ? formatModePrompt(entry.prompt, entry.mode ?? configWithProvider.mode)
        : undefined;
},
```

`formatModePrompt`（team-session-coordinator.ts L232-238）内部调用 `formatUserInputBlock`，把 prompt 包裹为 `<user_input mode="act">...</user_input>` 格式。runtime 的 `consumePendingUserMessage`（agent-runtime.ts L1257）拿到的是已包裹的字符串，创建 message 后 push 到 state.messages。

**Charles 设计**（server.py L322-337 + runtime.py L871-873）：

```python
async def _consume(session_id_arg: str) -> str | None:
    controller = _get_turn_queue_controller()
    entry = controller.consume_steer(sid)
    if entry is None:
        return None
    return entry.prompt  # 原始文本，未包裹

# runtime.py L871-873
pending_msg = create_message(
    MessageRole.USER, [TextPart(text=pending_text)],
)
```

Charles 的回调直接返回 `entry.prompt` 原始文本，runtime 创建 message 时不包裹 mode 标签。

**影响**：steer 消息进入 model request 时，Cline 的消息含 `<user_input mode="act">` 包裹，LLM 能看到 mode 上下文；Charles 的消息是裸文本，LLM 不知道当前 mode。但实际上 Charles 的 steer 消息通常用于补充指令（如"再分析一下 X 股票"），mode 上下文已在 system prompt 中体现，影响较小。

**注**：Charles 的常规用户输入通过 `_apply_default_user_input_wrap`（runtime.py L2789-2848）包裹 `<user_input mode="...">`，但 steer 消息绕过了此包裹逻辑。

### 差距 3：drain 重入保护数据结构（对应对比项 2.11.4）

**Cline 设计**（pending-prompt-service.ts L285-286, L308, L323）：

```typescript
scheduleDrain(sessionId, session) {
    if (session.drainingPendingPrompts || ...) return;
    queueMicrotask(() => void this.drain(sessionId));
}

async drain(sessionId) {
    if (session.drainingPendingPrompts) return;
    session.drainingPendingPrompts = true;
    try { ... } finally { session.drainingPendingPrompts = false; }
}
```

单一布尔标志，存于 `ActiveSession.drainingPendingPrompts`（session.ts L36）。

**Charles 设计**（turn_queue.py L372-374, L519-611）：

```python
self._draining: set[str] = set()  # session_id 集合
self._drain_tasks: dict[str, asyncio.Task] = {}  # session_id -> Task 引用

def _schedule_drain(session_id) -> None:
    existing = self._drain_tasks.get(session_id)
    if existing and not existing.done():
        return  # 已有 drain 在排队
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._drain(session_id))
        self._drain_tasks[session_id] = task  # 防止 GC
    except RuntimeError:
        # 无运行中事件循环，跳过（由 server 层触发）
        ...

async def _drain(session_id) -> None:
    if session_id in self._draining: return
    self._draining.add(session_id)
    try { ... } finally:
        self._draining.discard(session_id)
        self._drain_tasks.pop(session_id, None)
```

双结构：`_draining` 集合防重入 + `_drain_tasks` 字典持有 Task 引用防 GC。

**差异分析**：

| 维度 | Cline | Charles |
|------|-------|---------|
| 防重入标志 | `session.drainingPendingPrompts: boolean` | `_draining: set[str]`（按 session_id 隔离） |
| Task 引用管理 | 无（queueMicrotask 不返回 Task） | `_drain_tasks` 字典持有 `asyncio.Task` |
| 无事件循环处理 | 不存在（JS 始终有事件循环） | `try/except RuntimeError` 跳过调度 |
| 清理时机 | drain finally 内重置布尔 | drain finally 内 discard + pop |

**影响**：Charles 的双结构更复杂，但解决了 Python `asyncio.create_task` 的 Task GC 问题（未持有引用的 Task 可能被回收）。Cline 的 `queueMicrotask` 不返回 Task，无需管理引用。两者功能等价。

**Charles 的额外保护**：`_schedule_drain` 在无运行中事件循环时（如同步上下文调用 enqueue）跳过调度，由 server 层在 async 上下文中触发。Cline 不存在此问题（JS 始终有事件循环）。

### 差距 4：入队时 SSE 事件命名差异（对应对比项 2.11.11）

**Cline 设计**：入队时 `enqueue`（L238-253）调用 `emitPrompts` 发射 `pending_prompts` 事件，与消费时事件类型相同。前端通过同一事件类型区分入队/消费状态。

**Charles 设计**：入队时（server.py L1026-1031）返回 `pending_prompts_updated` 事件，携带 `queued_message` + `delivery` 字段；消费时（L781-790）发 `pending_prompts` + `pending_prompt_submitted` 两个事件。

**差异**：

| 事件类型 | Cline | Charles |
|---------|-------|---------|
| 入队 | `pending_prompts` | `pending_prompts_updated`（含 queued_message + delivery） |
| 消费（queue） | `pending_prompts` + `pending_prompt_submitted` | `pending_prompts` + `pending_prompt_submitted` |
| 消费（steer） | `pending_prompts` + `pending_prompt_submitted`（在 consumeSteer 内 emit） | `pending_prompts` + `pending_prompt_submitted`（在 consume_steer 内 emit） |

**影响**：前端需监听两个不同事件类型（`pending_prompts` 和 `pending_prompts_updated`）。Charles 的 `pending_prompts_updated` 携带 `queued_message` 字段，前端可显示"已排队：xxx"提示。Cline 统一用 `pending_prompts` 事件，前端通过队列长度变化判断是否入队。

### 差距 5：drain 失败后的行为（对应对比项 2.11.4）

**Cline 设计**（pending-prompt-service.ts L318-334）：

```typescript
try {
    await this.deps.send({...});
} catch {
    continueDrain = false;
    this.service.requeueFront(session, next);
    this.emitPrompts(session);
} finally {
    session.drainingPendingPrompts = false;
    if (continueDrain && session.pendingPrompts.length > 0
        && session.status !== "failed" && session.status !== "cancelled") {
        queueMicrotask(() => void this.drain(sessionId));
    }
}
```

失败时 `requeueFront` 把 entry 放回队首，`continueDrain = false` 停止本次 drain；但 finally 内检查 `continueDrain` 为 false，不再调度新 drain。需外部触发（如用户再次发消息）才能重试。

**Charles 设计**（server.py L819-829）：

```python
except Exception as e:
    logger.warning("turn_queue: 自动消费 queue 失败 session=%s: %s", session_id, e)
    try:
        controller = _get_turn_queue_controller()
        q_state = controller._states.get(session_id)
        if q_state is not None and entry is not None:
            controller._service.requeue_front(q_state, entry)
    except Exception:
        pass
    break  # 退出 while 循环
```

失败时 `requeue_front` 把 entry 放回队首，`break` 退出 while 循环，SSE 生成器结束。客户端需重连才能继续消费。

**差异**：两者失败行为一致——requeue + 停止 drain。但 Charles 直接 break 退出 SSE 生成器，Cline 保留在 drain 协程内等待外部触发。

## 4. nanobot 残留检查

### 检查范围

在 `agent/` 目录下执行 `grep -ri "nanobot"` 搜索，共发现 55 行 nanobot 残留。与 P2.11（Turn Queue）**直接相关**的文件中：

| 文件 | 与 P2.11 关系 | nanobot 残留数 | 残留类型 |
|------|-------------|---------------|---------|
| `agent/turn_queue.py` | 直接相关（PendingPromptService + Controller 实现） | 0 | 无 |
| `agent/runtime.py` | 直接相关（consume_pending_user_message 回调集成） | 0 | 无 |
| `agent/server.py` | 直接相关（turn queue 端点 + drain 触发 + consume_steer 回调构造） | 3 | 类型 A（实现来源标注） |
| `agent/types.py` | 直接相关（AgentRuntimeConfig.consume_pending_user_message 字段） | 0 | 无 |

### 注释残留分类

#### 类型 A：实现来源标注（与 P2.11 间接相关）

形式：`对标 nanobot xxx` / `用 AgentRuntime 替换 nanobot`

出现在（server.py 文件头）：
- `agent/server.py` L2 — `"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`
- `agent/server.py` L4 — `提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`
- `agent/server.py` L28-29 — `对标 nanobot:\n    - routes/chat.py _sse_generator() + _StreamCollectorHook`

**性质**：纯文档注释，说明 SSE 服务端设计参考了 nanobot routes/chat.py 的 `_sse_generator` 结构，实际代码已用 Cline 对标设计重写（`_sse_generator` 内集成了 turn queue 消费循环，nanobot 无此机制）。不影响运行时行为。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。所有 Turn Queue 相关代码均基于 Cline 对标设计：

- `PendingPromptEntry` / `PendingPromptQueueState` dataclass 对标 Cline `PendingPromptEntry` interface（pending-prompt-service.ts L16-27）
- `PendingPromptService` 类对标 Cline `PendingPromptService` 类（L54-205），所有方法签名与逻辑均对标：`enqueue` / `consume_steer` / `shift_next` / `requeue_front` / `update` / `delete` / `clear` / `list`
- `PendingPromptsController` 类对标 Cline `PendingPromptsController` 类（L207-352），依赖注入结构一致：`session_status_query` ↔ `getSession`、`send_callback` ↔ `send`、`emit_callback` ↔ `emit`
- `consume_pending_user_message` 回调机制对标 Cline `agent-runtime.ts` L1252-1269 `consumePendingUserMessage` + `local-runtime-host.ts` L640-648 回调注入
- `_sse_generator` 末尾的 queue 消费循环对标 Cline `drain()` L295-335（虽然触发方式不同，但消费语义一致）
- 未发现任何从 nanobot 直接移植的 turn queue 代码逻辑（nanobot 无 turn queue 机制）

### 残留风险评估

| 残留类型 | 文件数（与 P2.11 相关） | 风险等级 | 处理建议 |
|---------|----------------------|---------|---------|
| 类型 A（实现来源标注） | 1（server.py 文件头） | 低 | 可保留作为历史来源参考，或统一清理为"对标 Cline" |

## 5. 修复建议

### P0（高优先级，影响功能正确性）

无。当前 Charles 的 Turn Queue 机制功能完整，queue 类型在 SSE 连接稳定时能自动消费，steer 类型能实时插入 model request，不影响运行时正确性。

### P1（中优先级，改善 SSE 断开后的鲁棒性）

**建议 1：解耦 drain 与 SSE 连接（对应差距 1）**

参考 Cline `drain()` 通过 `send_callback` 真实启动新 run 的设计，将 Charles 的 `send_callback` 改为真实启动新 run（而非空操作），让 drain 独立于 SSE 连接。

**收益**：SSE 断开后，drain 仍能通过 `send_callback` 启动新 run，事件通过 hub 或独立通道推送。避免 SSE 断开导致队列残留。

**改动范围**：
- `server.py` `send_callback` 改为真实调用 `_run_once` 并通过事件队列推送事件
- 需引入事件中转通道（如 `asyncio.Queue` + 独立任务），让 SSE 重连后能继续接收事件
- `_sse_generator` 末尾的 while 循环可移除（由 drain 接管）

**注意**：此改动涉及 SSE 架构调整，风险较高。当前 Charles 的 SSE 单连接闭环设计在稳定网络下工作正常，若用户网络稳定可暂不修改。

### P2（低优先级，改善 steer 消息一致性）

**建议 2：steer 消息包裹 mode 标签（对应差距 2）**

参考 Cline `formatModePrompt` 在 `consumePendingUserMessage` 回调内包裹 `<user_input mode="...">`，在 Charles 的 `_consume` 回调（server.py L322-337）内调用 `format_user_input_block` 或手动包裹：

```python
async def _consume(session_id_arg: str) -> str | None:
    entry = controller.consume_steer(sid)
    if entry is None:
        return None
    mode = entry.mode or _get_current_mode(sid)
    return f'<user_input mode="{mode}">\n{entry.prompt}\n</user_input>'
```

**收益**：steer 消息与常规用户输入格式一致，LLM 能看到 mode 上下文。

**改动范围**：server.py `_make_consume_pending_user_message_callback` 函数内新增 1-2 行包裹逻辑。

### P3（可选，事件命名对齐）

**建议 3：统一入队事件类型（对应差距 4）**

参考 Cline 入队时也发 `pending_prompts` 事件（而非 `pending_prompts_updated`），将 Charles 入队时的事件类型改为 `pending_prompts`，前端通过队列长度变化判断入队。

**收益**：前端只需监听一个事件类型，简化事件处理逻辑。

**注意**：Charles 的 `pending_prompts_updated` 携带 `queued_message` + `delivery` 字段，前端可能依赖此信息显示"已排队"提示。改动需评估前端兼容性。

## 6. 验证方法建议

### 验证方法 1：queue 类型排队顺序测试

1. 启动一个长 run（如让 agent 执行耗时工具调用）
2. 在 run 运行中连续发送 3 条消息：A（queue）、B（queue）、C（queue）
3. 等待当前 run 结束
4. 观察后续 run 的执行顺序

**预期**：
- Cline：drain 自动按 A → B → C 顺序启动 3 个新 run，每个 run 的事件通过 onEvent 推送
- Charles：_sse_generator 末尾 while 循环按 A → B → C 顺序启动 3 个新 run，事件通过原 SSE 连接 yield 推送

### 验证方法 2：steer 类型实时插入测试

1. 启动一个多 iteration 的 run（如 agent 需要多次工具调用）
2. 在 iteration 1 结束后、iteration 2 开始前，发送一条 steer 消息"再分析一下 X"
3. 观察 iteration 2 的 model request 是否包含该 steer 消息

**预期**：
- Cline：iteration 2 的 `request.messages` 末尾包含 steer 消息（含 `<user_input mode="act">` 包裹），`state.messages` 也持久化该消息，前端收到 `message-added` 事件
- Charles：iteration 2 的 `request.messages` 末尾包含 steer 消息（裸文本，无 mode 包裹），`state.messages` 也持久化该消息，前端收到 `message_added` 事件

### 验证方法 3：同 prompt 合并测试

1. 发送消息 A="分析茅台"（queue）
2. 立即发送消息 B="分析茅台"（queue，同 prompt）
3. 检查队列长度

**预期**：两者队列长度均为 1（同 prompt 合并更新，不重复入队）。

### 验证方法 4：steer + queue 合并升级测试

1. 发送消息 A="分析茅台"（queue）
2. 立即发送消息 B="分析茅台"（steer，同 prompt）
3. 检查队列中条目的 delivery

**预期**：两者队列中该条目的 delivery 均为 "steer"（queue + steer 合并升级为 steer），且位于队首。

### 验证方法 5：drain 失败 requeue 测试

1. 在 queue 消费过程中模拟 send_callback 抛异常（Cline）或 _run_once 抛异常（Charles）
2. 检查队列状态

**预期**：
- Cline：`requeueFront` 把 entry 放回队首，`continueDrain=false` 停止 drain，需外部触发重试
- Charles：`requeue_front` 把 entry 放回队首，`break` 退出 while 循环，SSE 生成器结束，客户端需重连

### 验证方法 6：abort 时清空队列测试

1. 发送 3 条 queue 消息
2. 调用 `/abort` 端点中止当前 run
3. 检查队列状态

**预期**：两者队列均为空（`clearAborted` / `clear_aborted` 清空队列）。

### 验证方法 7：SSE 断开后 queue 残留测试（差距 1 验证）

1. 启动一个长 run
2. 发送 2 条 queue 消息
3. 在当前 run 结束前断开 SSE 连接（如关闭浏览器）
4. 重新连接 SSE，检查队列中的 queue 消息是否被消费

**预期**：
- Cline：drain 独立于 SSE 连接，run 结束后 drain 仍启动新 run 消费 queue 消息（事件通过 hub 推送，新 SSE 连接可接收）
- Charles：SSE 断开后 _sse_generator 被取消，while 循环未执行，queue 消息残留 in memory；重新连接时 `/stream` 入口检查 `_active_runtimes`，若 runtime 已结束则直接启动新 run（不消费残留 queue）；需手动调用 `/pending_prompts` 端点查看残留并手动重新提交
