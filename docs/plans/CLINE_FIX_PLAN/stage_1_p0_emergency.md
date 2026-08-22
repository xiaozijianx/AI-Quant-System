# Stage 1: P0 紧急修复方案 - 阻塞核心功能

> 优先级：P0（立即修复）
> 预估工作量：1-2 天
> 依赖：无
> 覆盖差距：2 项 P0
> 来源：CLINE_DIFF/SUMMARY.md 第三节 P0 级差距清单

---

## 1.1 apply_patch 原子性回滚

### 任务背景

来源：Phase G #G4.4（详见 CLINE_DIFF/SUMMARY.md P0-1）。

当前 `agent/tools/apply_patch.py` 的 `_execute` 方法在解析完所有补丁块后，**逐个 block 立即写盘**：

```python
# agent/tools/apply_patch.py L128-130
for block in blocks:
    result_item = self._apply_block(block)
    results.append(result_item)
```

每个 `_apply_block` 内部直接调用 `path.write_text` / `path.unlink` 立即落盘：
- `_apply_update` 在 L355 `path.write_text(content, encoding="utf-8")`
- `_apply_add` 在 L422 `path.write_text(content, encoding="utf-8")`
- `_apply_delete` 在 L441 `path.unlink()`

**问题**：若 patch 包含 5 个文件块，前 2 个成功写盘后第 3 个失败（如 `_replace_segment` 返回 None、文件不存在、二进制读取失败），前 2 个文件**已被修改**，仓库进入不一致状态。LLM 生成畸形 patch 时需手动恢复，存在数据安全风险。

Cline 对此采用**两阶段提交**：先解析全部 chunk 并计算每个文件的新内容（newContent），全部成功后才进入写盘阶段批量落盘。解析阶段任何 DiffError 都会抛出，此时零文件被修改。

### 目标

对齐 Cline 的两阶段提交模式：
1. **阶段一（compute）**：遍历所有补丁块，读取原文件、计算新内容，收集为 `changes` 列表。任何块解析失败立即抛出异常，此时不写盘。
2. **阶段二（apply）**：遍历 `changes` 列表，批量写盘（write/unlink）。

核心契约：**只要有一个 block 解析失败，整个 patch 不产生任何磁盘副作用**。

### 当前实现位置

- 文件：`e:\jikeAI\code\CASE-AI量化系统\agent\tools\apply_patch.py`
- 关键函数与行号：
  - `_execute` L111-142：主入口，循环调用 `_apply_block` 立即写盘
  - `_parse_patch` L144-218：解析补丁文本为 blocks 列表（无需改动，已正确分离）
  - `_apply_block` L220-253：分发到 `_apply_update` / `_apply_add` / `_apply_delete`
  - `_apply_update` L255-363：行级替换 + L355 立即写盘
  - `_replace_segment` L365-396：精确匹配 + fuzzy 匹配（纯计算，无 IO）
  - `_apply_add` L398-429：新建文件 + L422 立即写盘
  - `_apply_delete` L431-446：删除文件 + L441 立即 `unlink`

### 目标源代码位置

- 文件：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\apply-patch.ts`
- 关键函数与行号：
  - `computePatchChanges` L333-353：阶段一，解析 + 读取文件 + 计算变更，返回 `{changes, fuzz}`，不写盘
  - `patchToChanges` L215-254：遍历 patch.actions，对每个 action 计算 `newContent`（DELETE 不算 newContent）
  - `applyChanges` L275-325：阶段二，遍历 changes 批量写盘（rm / mkdir+writeFile / writeFile）
  - `createApplyPatchExecutor` L358-384：executor 入口，先 `computePatchChanges` 后 `applyChanges`
- 辅助文件：`apply-patch-parser.ts` L96-108 `PatchParser.parse()` 全量解析后返回 patch 对象，解析失败抛 DiffError

### 修复步骤建议

**原则**：保留 `_parse_patch` / `_replace_segment` / 行级替换逻辑不变，仅把"计算新内容"与"写盘"分离。

#### 步骤 1：新增 change 计算函数（不写盘）

在 `apply_patch.py` 中新增三个纯计算函数，对应原 `_apply_update` / `_apply_add` / `_apply_delete`，但**移除所有磁盘写操作**，仅返回 change 字典：

- `_compute_update_change(path, path_str, lines) -> dict`：复用 `_apply_update` 的 L260-354 逻辑（读取文件、检测换行符、行级替换、fuzzy 匹配），但把 L355 `path.write_text(...)` 替换为：在 change 字典中记录 `{"operation": "update", "path": path_str, "new_content": content, "old_content": raw_original, "lines_before": ..., "lines_after": ...}`。原 `_apply_update` 中"文件不存在""二进制读取失败""未找到要删除的行"等错误路径改为**抛出 ValueError**（而非返回 error 字典），让上层捕获后中止整个 patch。
- `_compute_add_change(path, path_str, lines) -> dict`：复用 `_apply_add` 的 L403-418 逻辑，但移除 L421-422 的 `mkdir` + `write_text`，仅返回 `{"operation": "add", "path": path_str, "new_content": content, "lines": len(content_lines)}`。文件已存在时抛 ValueError。
- `_compute_delete_change(path, path_str) -> dict`：复用 `_apply_delete` 的 L433-440 逻辑，移除 L441 `path.unlink()`，仅返回 `{"operation": "delete", "path": path_str, "old_content": raw_original}`。文件不存在时抛 ValueError。

#### 步骤 2：新增批量写盘函数

新增 `_apply_changes(changes: list[dict]) -> list[dict]` 函数：遍历 changes 列表，根据 `operation` 字段执行写盘：
- `update`：`path.write_text(change["new_content"], encoding="utf-8")`，返回结果字典（含 `success: True`、`lines_before`、`lines_after`）
- `add`：`path.parent.mkdir(parents=True, exist_ok=True)` + `path.write_text(change["new_content"], encoding="utf-8")`，返回结果字典
- `delete`：`path.unlink()`，返回结果字典

此阶段不再做任何校验（校验已在阶段一完成），仅机械写盘。

#### 步骤 3：重构 _apply_block 为分发器

保留 `_apply_block` 函数签名，但内部改为调用步骤 1 的 `_compute_*_change` 函数（而非原来的 `_apply_*`）。新增 `_apply_block_to_disk(change)` 调用步骤 2 的写盘逻辑。这样保留原函数的分发结构，便于回溯。

#### 步骤 4：重构 _execute 为两阶段提交

将 `_execute` L127-142 改为：

```python
# 阶段一：全量解析 + 计算 change，不写盘
changes: list[dict[str, Any]] = []
for block in blocks:
    try:
        change = self._apply_block(block)  # 现在返回 change 字典，不写盘
        changes.append(change)
    except ValueError as e:
        # 任一 block 解析失败，整体中止，零磁盘副作用
        return AgentToolResult(
            output={"error": f"补丁解析失败，已中止，未修改任何文件: {e}", "partial_path": block.get("path")},
            is_error=True,
        )

# 阶段二：全部解析成功，批量写盘
results = self._apply_changes(changes)
succeeded = sum(1 for r in results if r.get("success"))
failed = sum(1 for r in results if not r.get("success"))

return AgentToolResult(
    output={"results": results},
    metadata={"total_files": len(results), "succeeded": succeeded, "failed": failed},
)
```

#### 步骤 5：保留原 _apply_update / _apply_add / _apply_delete

按用户规则 4（保留之前函数逻辑），不删除原 `_apply_update` / `_apply_add` / `_apply_delete` 函数。它们可保留为"单块写盘"的辅助实现，供步骤 2 的 `_apply_changes` 内部调用其写盘片段，或保留作为历史实现参考。新增的 `_compute_*_change` 函数复用其计算逻辑。

### 验证方法

1. **构造畸形 patch**：编写一个 patch 包含 3 个 Update File 块，其中第 2 个块的 `-old line` 在目标文件中不存在（触发 `_replace_segment` 返回 None）。
2. **执行前快照**：记录 3 个目标文件的原始内容（如 `sha256` 或完整文本）。
3. **执行 apply_patch**：调用 `ApplyPatchTool._execute`，应返回 `is_error=True`，错误信息含"补丁解析失败，已中止，未修改任何文件"。
4. **执行后校验**：重新读取 3 个目标文件，验证内容与执行前**完全一致**（即第 1 个块也未写盘）。
5. **正常 patch 回归**：构造 3 个块的合法 patch，执行后 3 个文件均按预期修改，`metadata.succeeded == 3`。
6. **Add 已存在文件**：构造 Add File 块指向已存在文件，应整体失败，原文件未被覆盖。

### 注意事项

- 不能死板照搬 Cline 的 `PatchParser` 实现（Cline 用 `origIndex` 索引、canonicalize 标点归一化，我们的 `_replace_segment` 用精确+fuzzy 匹配，逻辑不同但目标一致）。保留我们的匹配逻辑，仅分离计算与写盘。
- 保留原函数逻辑，在其基础上修改：`_apply_update` / `_apply_add` / `_apply_delete` 的行级替换、换行符检测、fuzzy 匹配逻辑全部保留，只是把"写盘"动作抽离到阶段二。
- 中文注释 UTF-8 编码，无 emoji。
- 不写 fallback：解析失败直接抛 ValueError 中止，不尝试"部分应用"。
- 阶段二写盘若发生 IO 异常（如磁盘满、权限不足），属于不可恢复的运行时错误，仍按原逻辑用 try/except 包裹每个写盘操作，记录失败结果。但阶段一已确保逻辑一致性，阶段二的 IO 异常概率极低。

---

## 1.2 Turn Queue queue 路径修复

### 任务背景

来源：Phase O #O4/O7/O12/O13（详见 CLINE_DIFF/phase_O_turn_queue.md）。

Turn Queue 的 queue 类型消息消费链路存在**三重断裂**，导致用户在 agent 运行中发送的排队消息**永不被消费**：

1. **send_callback 空操作**（`agent/server.py` L123-143）：`_get_turn_queue_controller` 内部定义的 `send_callback` 仅 `logger.info`，不启动新 run。注释明确写道"不抛异常，让 controller 认为发送成功，继续 drain 下一条"——但实际什么都没发送。
2. **run 结束后无触发**（`agent/server.py` L630-631）：`run_agent()` 在 finally 中 `_active_runtimes.pop(session_id, None)`，此后 `can_start_run` 变为 True，但 `_sse_generator` 末尾仅 yield `pending_prompts_drained` 事件（L683-695），**无代码再次调用 `_schedule_drain()`**。
3. **前端不处理事件**（`static/js/ai-chat.js` L483-514）：`_handleSSEEvent` 的 switch 仅处理 `phase/token/plan/tool_call/tool_output/todos_updated/mode_changed/approval_request/done/error`，**不处理** `pending_prompts_drained` / `pending_prompts` / `pending_prompt_submitted` 任何事件，无排队 badge UI。

**影响**：用户在 agent 运行中发消息，agent 跑完后消息"消失"（实际堆积在队列里无人消费），用户输入丢失，核心交互语义破损。

Cline 的 `drain`（pending-prompt-service.ts L295-335）在 run 结束后通过 `await this.deps.send({...})` **直接启动新 run**，并通过原 SSE 连接推送事件，实现"运行中排队，结束后自动依次处理"。

### 目标

修复 queue 路径，确保排队消息能被消费：

1. **服务端自动消费**：在 `_sse_generator` 末尾，run 结束后若队列非空，循环取出队首并在服务端直接启动新 run（复用 `run_agent` 逻辑），通过原 SSE 连接推送事件。不依赖前端发起请求。
2. **前端补齐事件处理 + badge UI**：在 `_handleSSEEvent` 添加 `pending_prompts` / `pending_prompt_submitted` / `pending_prompts_drained` 三个 case；输入框附近添加排队 badge 显示排队数；提供排队列表查看/删除入口。

### 当前实现位置

- **send_callback 空操作**：`e:\jikeAI\code\CASE-AI量化系统\agent\server.py` L123-143
  - L138-143：`send_callback` 函数体仅 `logger.info`，无实际启动 run 逻辑
- **run 结束后无触发**：`e:\jikeAI\code\CASE-AI量化系统\agent\server.py`
  - L618：`_active_runtimes[session_id] = runtime` 注册活跃 runtime
  - L621-633：`run_agent()` async 函数 + `asyncio.create_task`
  - L630-631：finally 中 `_active_runtimes.pop(session_id, None)` + `event_queue.put_nowait(None)` 哨兵
  - L659-660：`while True` 收到 None 哨兵后 break
  - L683-695：yield `pending_prompts_drained` 事件（前端不处理）
  - L697：yield `done` 事件
- **前端不处理事件**：`e:\jikeAI\code\CASE-AI量化系统\static\js\ai-chat.js` L483-514
  - L483-514：`_handleSSEEvent` switch 无 turn_queue 相关 case
- **consume_pending_user_message 回调（steer 路径，无需改）**：`agent/server.py` L305-336 `_make_consume_pending_user_message_callback`，runtime 在 iteration > 1 时调用消费 steer 消息，已正常工作
- **turn_queue controller**：`e:\jikeAI\code\CASE-AI量化系统\agent\turn_queue.py`
  - L519-611：`_schedule_drain` / `_drain` 协程已实现完整 drain 逻辑，但因 `send_callback` 空操作而无效
  - L572-588：`_drain` 调用 `await self._send_callback(...)` 期望启动新 run

### 目标源代码位置

- 文件：`e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\turn-queue\pending-prompt-service.ts`
- 关键函数与行号：
  - `scheduleDrain` L281-293：检查条件后 `queueMicrotask(() => void this.drain(sessionId))`
  - `drain` L295-335：取出队首 → `emitPrompts` + `emitSubmitted` → `await this.deps.send({sessionId, prompt, mode, userImages, userFiles})` 真正启动新 run → 失败时 `requeueFront` → 成功且队列非空时递归 `queueMicrotask` 继续 drain
  - L310-317：`await this.deps.send()` 是 drain 的核心，真正启动新 run
  - L324-333：send 成功且 `pendingPrompts.length > 0` 时递归调度 drain

### 修复步骤建议

**原则**：保留原函数逻辑，在其基础上修改。不重写 `_sse_generator`，而是在其末尾增加循环消费段。

#### 步骤 1：抽取 run 单次运行为内部辅助函数

在 `_sse_generator`（L547-697）内部，把"创建 runtime + 启动 run_agent + 消费事件队列 + 清理"的逻辑（L579-673）抽取为嵌套 async generator 函数 `_run_once(user_message, messages)`，yield SSE 事件。保留原 L579-673 的所有逻辑（系统提示构建、runtime 创建、事件订阅、run_agent 后台任务、while 消费循环、finally 清理），仅改为可重复调用。

注意：系统提示构建（L572-577）和消息历史准备（L588-598）只需在首次 run 时执行；后续 queue 消费的 run 复用同一 session 的 messages（runtime 已持久化到 session_manager）。

#### 步骤 2：在 _sse_generator 末尾添加 queue 循环消费

在 L683-695（pending_prompts_drained 事件）位置改为循环消费逻辑：

```python
# Phase 30.1 修复 P0: run 结束后自动消费 queue 类型排队消息
# 对标 Cline drain() L295-335：await this.deps.send() 启动新 run
while True:
    try:
        controller = _get_turn_queue_controller()
        state = controller._states.get(session_id)
        if state is None or not state.pending_prompts:
            break
        # 取出队首 queue 类型条目（跳过 steer，steer 由 runtime iteration 消费）
        entry, prompts_snapshot = controller._service.shift_next(state)
        if entry is None:
            break
        # 发射 pending_prompts + pending_prompt_submitted 事件
        yield _sse_event("pending_prompts", {
            "session_id": session_id,
            "prompts": prompts_snapshot,
        })
        yield _sse_event("pending_prompt_submitted", {
            "session_id": session_id,
            "id": entry.id,
            "prompt": entry.prompt,
            "delivery": entry.delivery,
        })
        # 构造新 message（复用 user_input 标签包裹逻辑）
        from agent.state import get_mode
        current_mode = get_mode(session_id)
        wrapped = f'<user_input mode="{current_mode}">\n{entry.prompt}\n</user_input>'
        queued_message = create_text_message(MessageRole.USER, wrapped)
        # 复用 _run_once 启动新 run，消费事件
        async for sse in _run_once(entry.prompt, [queued_message]):
            yield sse
    except Exception as e:
        logger.warning("turn_queue: 自动消费 queue 失败 session=%s: %s", session_id, e)
        # 失败时把 entry 重新入队（对标 Cline requeueFront）
        try:
            controller = _get_turn_queue_controller()
            state = controller._states.get(session_id)
            if state is not None and entry is not None:
                controller._service.requeue_front(state, entry)
        except Exception:
            pass
        break
```

关键点：
- 循环消费直到队列空或失败
- 每次消费前发射 `pending_prompts` + `pending_prompt_submitted` 事件（对齐 Cline L306-307）
- 失败时 `requeue_front` 把 entry 放回队首（对齐 Cline L320）
- 复用 `_run_once` 启动新 run，事件通过原 SSE 连接推送

#### 步骤 3：send_callback 改为真实实现（可选，作为双保险）

将 `send_callback`（L123-143）改为真正能启动后台 run 的实现，作为 `_schedule_drain` 路径的双保险。但鉴于步骤 2 已在 `_sse_generator` 内闭环消费，`send_callback` 可保持空操作（仅日志），因为 `_schedule_drain` 在 run 运行中本就会被 `can_start_run=False` 跳过。保留空操作注释说明"实际消费由 _sse_generator 末尾循环完成"。

#### 步骤 4：前端补齐事件处理

在 `static/js/ai-chat.js` 的 `_handleSSEEvent`（L483-514）switch 中添加三个 case，**不修改现有 case**：

```javascript
case 'pending_prompts':
    this._onPendingPrompts(data);
    break;
case 'pending_prompt_submitted':
    this._onPendingPromptSubmitted(data);
    break;
case 'pending_prompts_drained':
    // 服务端已自动消费，前端仅用于 UI 反馈
    this._onPendingPromptsDrained(data);
    break;
case 'pending_prompts_updated':
    // 入队确认事件，更新 badge
    this._onPendingPromptsUpdated(data);
    break;
```

#### 步骤 5：前端添加 badge UI 与回调实现

在 `ai-chat.js` 中新增以下方法（保留现有方法不变）：

- `_onPendingPrompts(data)`：根据 `data.prompts` 更新排队 badge 数字与排队列表
- `_onPendingPromptSubmitted(data)`：从排队列表中移除已消费条目，更新 badge
- `_onPendingPromptsDrained(data)`：可选高亮提示"队列已消费"（服务端自动消费，前端无需主动发起请求）
- `_onPendingPromptsUpdated(data)`：入队后更新 badge

在 `templates/ai-chat.html` 的输入框附近添加 badge 元素（如 `<span id="queue-badge" class="queue-badge" style="display:none;">0</span>`），由上述回调控制显隐与数字。

#### 步骤 6：保留 emit_callback 空操作

`emit_callback`（L145-151）保持空操作。SSE 事件由 `_sse_generator` 内部直接 yield，不通过 controller 的 emit_callback。此设计已在注释中说明，无需改动。

### 验证方法

1. **排队消费端到端测试**：
   - 启动一个长耗时 agent 任务（如让 agent 执行多个工具调用）
   - 在 agent 运行中，通过前端发送 3 条 queue 类型消息（`delivery: "queue"`）
   - 观察：3 条消息入队后，前端 badge 显示"3"
   - 等待 agent 当前 run 结束
   - 验证：agent **自动**依次消费 3 条消息，每条消费时前端收到 `pending_prompt_submitted` 事件，badge 递减
   - 最终 badge 归零，3 条消息全部被 LLM 处理

2. **steer 路径回归**：
   - 在 agent 运行中发送 1 条 steer 消息（`delivery: "steer"`）
   - 验证：steer 消息在当前 run 的下一个 iteration 被追加到 model request（runtime.py L697-720），而非排队等待
   - steer 路径不受本次修复影响

3. **队列持久性测试**：
   - agent 运行中入队 2 条消息
   - 调用 `GET /sessions/{id}/pending_prompts` 验证队列包含 2 条
   - 让 agent run 结束，观察自动消费第 1 条
   - 在消费第 2 条前手动 `DELETE /sessions/{id}/pending_prompts/{第2条id}`
   - 验证：第 2 条不再被消费，badge 归零

4. **失败 requeue 测试**：
   - 构造让 run 启动失败的场景（如临时禁用 LLM provider）
   - 入队 1 条消息，run 结束后自动消费应失败
   - 验证：entry 被 `requeue_front` 放回队首，badge 仍显示"1"
   - 恢复 LLM provider，手动发新消息触发 run，验证队列中的消息最终被消费

5. **前端事件测试**：
   - 打开浏览器开发者工具 Network 面板，观察 SSE 事件流
   - 入队时应收到 `pending_prompts_updated` 事件
   - run 结束自动消费时应依次收到 `pending_prompts` → `pending_prompt_submitted` → 各类 run 事件 → `pending_prompts` → ... → `done`

### 注意事项

- 不能死板照搬 Cline 的 `queueMicrotask(() => void this.drain(sessionId))` 调度方式：Cline 有 SSE 连接复用，drain 启动的新 run 通过原连接推送事件；我们的 `_sse_generator` 是单次 generator，需在 generator 内部循环消费，不能脱离原 SSE 流。步骤 2 的循环消费是适配 Python asyncio 的等价实现。
- 保留原函数逻辑：`_sse_generator` 的 L547-697 原有逻辑全部保留，循环消费段添加在 L683 位置（替换原 pending_prompts_drained 单次 yield）。`_make_consume_pending_user_message_callback`（steer 路径）不改。`turn_queue.py` 的 controller / service / `_drain` / `_schedule_drain` 不改。
- send_callback 保持空操作：因步骤 2 已在 `_sse_generator` 内闭环，`_schedule_drain` 路径在 run 运行中本就因 `can_start_run=False` 跳过，run 结束后由步骤 2 接管。改 send_callback 反而会与步骤 2 重复启动 run。
- 中文 UTF-8 编码，无 emoji，不写 fallback。
- 前端修改遵循"只增不改"原则：新增 case、新增方法、新增 badge 元素，不修改现有 `_handleSSEEvent` 的现有 case 分支。
- 队列条目消费顺序：Cline `shiftNext` 取队首，steer 优先级高于 queue（enqueue 时 steer 放队首、queue 放队尾）。步骤 2 的 `shift_next` 会取到队首——若队首是 steer，应跳过（steer 由 runtime iteration 消费，不应在 run 间消费）。需在循环中判断 `if entry.delivery == "steer": requeue_front; break`，避免误消费 steer 条目。实际上 run 结束后 steer 应已被 runtime iteration 消费完毕，但防御性判断更安全。

---

## 修复顺序与依赖

1. **先修 1.1 apply_patch 原子性**（独立任务，无依赖，1 天）
2. **再修 1.2 Turn Queue queue 路径**（涉及服务端 + 前端，1 天）
   - 步骤 1-3 服务端循环消费（半天）
   - 步骤 4-5 前端事件处理 + badge（半天）

两项 P0 修复完成后，核心功能正确性恢复：
- apply_patch 不再因部分失败导致仓库不一致
- queue 类型排队消息能被自动消费，用户输入不再丢失

后续 P1/P2 修复（事件名统一、emit_callback 真实化、SSE 连接复用）见 Stage 2 方案。
