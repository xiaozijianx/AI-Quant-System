# Phase M: 循环检测 + MistakeTracker 对比报告

> 对标源码：
> - `sdk/packages/core/src/runtime/safety/loop-detection.ts`
> - `sdk/packages/core/src/runtime/safety/mistake-tracker.ts`
> - `sdk/packages/core/src/runtime/safety/rules.ts`
> - 集成位置：`sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`
>
> 当前实现：
> - `agent/loop_detection.py`
> - `agent/mistake_tracker.py`
> - 集成位置：`agent/runtime.py`
>
> 对比维度：M1-M13

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 3 项 |
| 弱对齐 | 5 项 |
| 缺失 | 1 项 |
| 额外增强（含语义不等价增强） | 4 项 |
| **对齐度** | **约 45%** |

说明：本阶段的"额外增强"多为语义不等价的增强——我的 MistakeTracker 引入了 Cline 不存在的"按类型独立计数 + 软阈值 + 关键词分类"机制，设计哲学与 Cline 不同。这些增强在功能上更细致，但与 Cline 的逻辑不等价，因此不能视为"对齐"。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| M1 | LoopDetectionTracker 数据结构（软3/硬5） | loop-detection.ts L20-24, L113-116 | loop_detection.py L22-27, types.py L300-308 | 完全一致 |
| M2 | 循环判定 key（tool_name + input hash） | loop-detection.ts L40-59, L136-143 | loop_detection.py L37-62, L115-120 | 完全一致 |
| M3 | 软阈值触发行为（注入提示 vs 警告） | orchestrator.ts L1256-1263（注入 user message） | runtime.py L1038-1043（仅 logger.warning） | 弱对齐（语义不等价） |
| M4 | 硬阈值触发行为（abort + status） | orchestrator.ts L1265-1273 + L1300-1308（经 MistakeTracker 间接 abort） | runtime.py L1033-1037（直接 BeforeToolResult stop） | 弱对齐（路径不同） |
| M5 | key 老化机制（LRU/时间窗口） | loop-detection.ts L72-79（仅连续相同判断，无 LRU） | loop_detection.py L72-78（同上） | 完全一致 |
| M6 | MistakeTracker mistake_type 枚举 | mistake-tracker.ts L39-42（3 类：api_error/invalid_tool_call/tool_execution_failed） | mistake_tracker.py L21-28（5 类：param_error/tool_not_found/permission_denied/exec_error/timeout） | 额外增强（语义不等价） |
| M7 | 每类独立阈值 | mistake-tracker.ts L81（单一 consecutiveMistakes 计数，不分类型） | mistake_tracker.py L149-153, L173-194（按类型独立计数 + 总计数） | 额外增强（语义不等价） |
| M8 | 错误分类逻辑 | mistake-tracker.ts L88-150（reason 由调用方显式传入，不分类） | mistake_tracker.py L62-94（classify_mistake 关键词匹配） | 额外增强（语义不等价） |
| M9 | 软阈值提示格式 | mistake-tracker.ts L116-135（无软阈值，仅硬阈值 + onLimitReached 回调返回 guidance） | mistake_tracker.py L186-194 + L215-221（单类型软阈值触发 continue_with_guidance） | 额外增强（语义不等价） |
| M10 | 硬阈值 abort 标记 | orchestrator.ts L1301-1308（outcome.action="stop" → activeRuntime.abort，finishReason="aborted"） | runtime.py L1090-1091（抛 RuntimeError） | 弱对齐（语义不等价） |
| M11 | 集成方式（hook vs inline） | orchestrator.ts L1084-1098（tool-started 事件驱动 + beforeTool hook 链） | runtime.py L233, L1019-1044（before_tool hook 内联） | 弱对齐 |
| M12 | safety rules 引擎（规则注册/优先级/执行） | rules.ts L1-49（**非安全引擎**，是用户指令注入 system prompt 的工具） | 无对应物 | 弱对齐（语义不等价） |
| M13 | 跨轮次状态保持 | orchestrator.ts L281-291, L538-542（SessionOrchestrator 持有，per-session，restore 时 reset） | runtime.py L230-235, L332-333, L472-473（AgentRuntime 持有，per-run，run 入口 reset） | 弱对齐 |

---

## 3. 关键差距详细分析

### 差距 #M3：软阈值触发行为不同（P1）

**严重度**：P1（影响 LLM 自纠错能力）

**Cline 实现**（orchestrator.ts L1256-1263）：
```typescript
if (verdict.kind === "soft") {
    if (verdict.message) {
        this.conversation.appendMessage({
            role: "user",
            content: [{ type: "text", text: verdict.message }],
        });
    }
    return;
}
```
软阈值触发时，将 `verdict.message`（形如 `"Detected N consecutive identical calls to \`tool_name\`; consider trying a different approach."`）作为 user 消息追加到 conversation，**让 LLM 在下一轮看到该提示并自纠错**。工具调用本身不阻止。

**我的实现**（runtime.py L1038-1043）：
```python
if verdict.kind == "soft":
    # 软警告仅记录日志，不阻止工具执行，给 LLM 留出自纠错空间
    logger.warning(
        "Loop detection soft warning: %s",
        verdict.message,
    )
return None
```
软阈值仅写日志，**不注入 LLM 上下文**。LLM 看不到该提示，无法据此自纠错。

**影响**：
- Cline 设计意图：让 LLM 在 3 次相同调用后看到"建议换思路"的提示，主动改变策略，避免滑向硬阈值
- 我的实现：LLM 对软阈值无感知，必须达到硬阈值（5 次）才会被强行中止，浪费 2 次迭代 + token
- 在量化场景下，若 LLM 卡在某个数据查询循环，会多消耗 2 轮 API 调用

**修复建议**：
在 `_loop_detection_hook` 的 soft 分支中，将 `verdict.message` 作为 user 消息追加到 `self._state.messages`：
```python
if verdict.kind == "soft":
    if verdict.message:
        notice_msg = create_text_message(MessageRole.USER, verdict.message)
        self._state.messages.append(notice_msg)
        await self._emit(make_message_added(self.snapshot(), notice_msg))
    return None
```

**优先级**：P1

---

### 差距 #M4：硬阈值触发路径不同（P1）

**严重度**：P1（影响 abort 语义与 finishReason）

**Cline 实现**（orchestrator.ts L1265-1308）：
```typescript
// Hard escalation → 不直接 abort，而是经 MistakeTracker 间接 abort
this.enqueueMistakeRecord({
    iteration,
    reason: "tool_execution_failed",
    forceAtLimit: true,  // 跳过递增，直接到 maxConsecutiveMistakes
    details: verdict.message ?? ...,
});
// enqueueMistakeRecord 内部:
const outcome = await this.mistakeTracker.record(input);
if (outcome.action === "stop") {
    this.trackerAbortInFlight = true;
    this.conversation.appendMessage({ role: "user", content: [...] });
    this.activeRuntime?.abort(outcome.reason ?? outcome.message);
}
```
Cline 的硬阈值**不直接 abort**，而是用 `forceAtLimit:true` 触发 MistakeTracker 立即达到 maxConsecutiveMistakes，再由 MistakeTracker 的 `outcome.action="stop"` 触发 `activeRuntime.abort()`。这一路径会让 finishReason 变为 `"aborted"`，并走 MistakeTracker 的 `onLimitReached` 回调（用户可决策 "Try a different approach" 还是 "Stop"）。

**我的实现**（runtime.py L1033-1037）：
```python
if verdict.kind == "hard":
    return BeforeToolResult(
        stop=True,
        reason=verdict.message,
    )
```
硬阈值直接返回 `BeforeToolResult(stop=True)`，由 `_prepare_tool_execution` 抛 `RuntimeError`，主循环 catch 后 status 设为 `"failed"` 或 `"aborted"`（取决于 _aborted 标志，此处未设 _aborted 故为 `"failed"`）。

**影响**：
- Cline：硬阈值→MistakeTracker→abort，finishReason="aborted"，用户可经 `onLimitReached` 回调决策是否继续
- 我：硬阈值→直接 RuntimeError，status="failed"，无用户决策环节
- 语义不等价：Cline 视循环硬阈值为"可恢复的 abort"，我视为"硬失败"
- 我未联动 MistakeTracker：硬阈值未触发 MistakeTracker 的 `forceAtLimit` 路径，导致两个 tracker 各自为政

**修复建议**：
1. 短期：在 `_loop_detection_hook` 的 hard 分支中，先调用 `self._mistake_tracker.record(..., force_at_limit=True)`（需扩展 record 支持 force_at_limit 参数），再根据 outcome 决定 abort 还是 continue_with_guidance
2. 长期：考虑将循环检测硬阈值的 abort 路径与 MistakeTracker 的 abort 路径统一，让 finishReason 一致为 "aborted"

**优先级**：P1

---

### 差距 #M6/M7/M8/M9：MistakeTracker 设计哲学不同（P2，语义不等价）

**严重度**：P2（功能更强但与 Cline 不等价）

**Cline 实现**（mistake-tracker.ts L39-150）：
- **M6 mistake_type 枚举**：仅 3 类（`api_error` / `invalid_tool_call` / `tool_execution_failed`），由调用方在 `enqueueMistakeRecord` 时显式传入
- **M7 每类独立阈值**：无。单一 `consecutiveMistakes` 全局计数，不区分类型
- **M8 错误分类逻辑**：无分类。reason 由调用方根据触发场景显式传入：
  - tool-started 事件触发循环硬阈值 → `reason: "tool_execution_failed"` + `forceAtLimit: true`
  - turn-finished 事件且全失败 → `reason: "tool_execution_failed"`
  - API 错误 → `reason: "api_error"`
- **M9 软阈值**：MistakeTracker **无软阈值概念**。达到 `maxConsecutiveMistakes`（默认 6）时触发 `onLimitReached` 回调，回调可返回 `{action: "continue", guidance}` 让 LLM 继续并注入 guidance，或 `{action: "stop"}` 中止

**我的实现**（mistake_tracker.py L21-194）：
- **M6 mistake_type 枚举**：5 类（`param_error` / `tool_not_found` / `permission_denied` / `exec_error` / `timeout`）
- **M7 每类独立阈值**：`_counts: dict[str, int]` 按类型独立计数，`_total` 总计数。`max_per_type=3` 单类型软阈值，`max_total=5` 总错误硬阈值
- **M8 错误分类逻辑**：`classify_mistake(error_text)` 用关键词匹配（"not found"→tool_not_found, "permission"→permission_denied, "timeout"→timeout, "schema"/"validation"→param_error, 其他→exec_error）
- **M9 软阈值**：单类型达到 `max_per_type=3` 时返回 `continue_with_guidance`，把恢复提示注入 LLM 上下文

**影响**：
- 我的实现更精细：按类型分类计数，避免一种类型的错误把另一种类型的"配额"用完
- 但语义与 Cline 不等价：
  - Cline 的 maxConsecutiveMistakes=6 是"连续错误总数"，我的 max_total=5 是"错误总数"
  - Cline 的 onLimitReached 回调允许用户交互决策，我的实现无用户决策环节
  - Cline 的 reason 是调用方语义化传入，我的 classify_mistake 是字符串匹配（可能误判，如错误文本含 "permission" 但实际是 exec_error）
- Cline 的"连续"概念：成功调用会 reset（orchestrator.ts L1162-1166），我的实现也 reset（runtime.py L1077），这点一致
- 关键差异：Cline 没有"单类型软阈值"概念，我的 `max_per_type` 是额外引入的层次

**修复建议**：
1. 保留按类型分类计数（合理增强），但增加 `force_at_limit` 参数以支持 Cline 的硬阈值联动路径
2. `classify_mistake` 的关键词匹配可作为合理增强保留，但应在调用方明确知道 mistake_type 时优先使用调用方传入值（与 Cline 对齐）
3. 考虑增加 `on_limit_reached` 回调机制，让上层（如 CLI 交互模式）可决策 continue/stop
4. 默认 `max_total` 改为 6 与 Cline 对齐（当前为 5）

**优先级**：P2

---

### 差距 #M10：硬阈值 abort 标记不同（P2）

**严重度**：P2（影响 status 语义）

**Cline 实现**：
- MistakeTracker 返回 `{action: "stop", message, reason}`，无 `MistakeLimitExceeded` 异常类型
- orchestrator.ts L1307：`this.activeRuntime?.abort(outcome.reason ?? outcome.message)` 调用 AgentRuntime.abort()
- AgentRuntime.abort() 设置 status="aborted"，finishReason="aborted"
- 任务计划文档中提到的 `MistakeLimitExceeded` 在 Cline 源码中**实际不存在**，是文档误称

**我的实现**（runtime.py L1090-1091）：
```python
if outcome.action == "stop":
    raise RuntimeError(outcome.message or "MistakeTracker 达到硬阈值上限")
```
抛 RuntimeError，主循环 catch 后：
- `is_aborted = self._aborted` → False（未调用 abort()）
- `status = "failed"`（而非 "aborted"）
- 发射 `run_failed` 事件（而非 `run_finished`）

**影响**：
- Cline：mistake limit → status="aborted"，前端可显示"用户中止"语义
- 我：mistake limit → status="failed"，前端显示"运行失败"
- 用户从状态无法区分"是 LLM 犯错太多被中止"还是"系统异常失败"

**修复建议**：
在 `_check_repeated_tool_failures` 中，当 `outcome.action == "stop"` 时，调用 `self.abort(outcome.message)` 而非抛 RuntimeError，使 status 一致为 "aborted"：
```python
if outcome.action == "stop":
    self.abort(outcome.message or "MistakeTracker 达到硬阈值上限")
    raise RuntimeError(self._abort_reason)
```

**优先级**：P2

---

### 差距 #M11：集成方式不同（P2）

**严重度**：P2（影响 hook 触发时序）

**Cline 实现**（orchestrator.ts L1084-1098）：
- 循环检测在 `tool-started` 事件处理器中触发（`inspectLoopForToolCall`）
- `tool-started` 事件在工具实际执行**之前**发射，因此效果等同于 beforeTool
- 但 Cline 的 `SessionRuntime` 同时有 `beforeTool` hook 链（orchestrator.ts L203-213），循环检测**不在** beforeTool 链中，而是独立的事件处理器
- 设计意图：让循环检测与 tool execution 解耦，可被 `loopDetectionDisabled` 配置关闭

**我的实现**（runtime.py L233, L1019-1044）：
- 循环检测注册为 `before_tool` hook（`self._hooks.before_tool.append(self._loop_detection_hook)`）
- 在 `_prepare_tool_execution` 中按 hook 链顺序执行
- 优点：与 tool 集成紧密，可在工具执行前直接 skip/stop
- 缺点：与 Cline 的"事件驱动"架构不同，无法被事件层独立关闭

**影响**：
- 功能等价：都在工具执行前触发
- 架构不等价：Cline 的事件驱动方式支持更松耦合的扩展（如可在 orchestrator 层加开关），我的 hook 方式更紧密
- 我的实现无 `loopDetectionDisabled` 开关（但有 `LoopDetectionConfig` 可调整阈值）

**修复建议**：
1. 短期：保持 hook 方式（功能等价，重构成本高）
2. 长期：可选在 `AgentRuntimeConfig` 增加 `loop_detection_enabled: bool = True` 开关，对齐 Cline 的 `loopDetectionDisabled`

**优先级**：P2

---

### 差距 #M12：safety rules 引擎语义不符（P3）

**严重度**：P3（对比维度本身有歧义）

**Cline 实现**（rules.ts L1-49）：
```typescript
export function formatRulesForSystemPrompt(rules: ReadonlyArray<RuleConfig>): string {
    // 将用户自定义规则渲染为 "# Rules\n## rule_name\nrule_instructions" 注入 system prompt
}
export function listEnabledRulesFromWatcher(watcher: UserInstructionConfigWatcher): RuleConfig[] {
    // 从配置 watcher 加载启用规则，按名称排序
}
```
Cline 的 `rules.ts` **不是 safety rules 引擎**，而是**用户自定义指令注入工具**：
- `RuleConfig` 是用户在配置文件中定义的"规则"（如"代码风格用 black"）
- 启用后格式化注入 system prompt
- 与"安全规则引擎"（规则注册、优先级、执行）完全无关

任务计划文档（AGENT_CLINE_COMPARISON_PLAN.md L577）将 M12 描述为"safety rules 引擎（规则注册、优先级、执行）"，但 Cline 的 `rules.ts` 实际不是这个语义。

**我的实现**：无对应物（也不需要，因为 Cline 的 rules.ts 是用户指令注入，我的实现有其他途径处理 system prompt）。

**影响**：
- 若按字面对比维度 M12（"safety rules 引擎"）：Cline 也没有，双方都缺失
- 若按 Cline rules.ts 实际功能（用户指令注入）：我的实现通过 `agent_config/system_prompt` 等其他方式处理，无 1:1 对应
- 不影响功能

**修复建议**：
1. 文档修正：将 M12 对比维度描述改为"用户指令规则注入"，避免误解为 safety 引擎
2. 若需要用户自定义规则注入 system prompt，可在 `context.py` 中实现类似 `formatRulesForSystemPrompt` 的逻辑（可选）

**优先级**：P3

---

### 差距 #M13：跨轮次状态保持粒度不同（P2）

**严重度**：P2（影响 session 级状态语义）

**Cline 实现**（orchestrator.ts L281-291, L538-542）：
- `MistakeTracker` 和 `LoopDetectionTracker` 由 `SessionRuntimeOrchestrator` 持有
- 生命周期：**per-session**（跨多次 run 保持）
- 仅在 `restore(messages)` 时 reset（即用户显式恢复会话或开始新会话）
- 多次 run 之间状态保持，连续犯错的记忆跨 run 累积

**我的实现**（runtime.py L230-235, L332-333, L472-473）：
- `MistakeTracker` 和 `LoopDetectionTracker` 由 `AgentRuntime` 持有
- 生命周期：**per-run**（每次 run() 入口 reset）
- `run()` L472-473：`self._loop_tracker.reset(); self._mistake_tracker.reset()`
- `restore()` L332-333：同样 reset
- 多次 run 之间状态不保持，每次 run 都从 0 开始

**影响**：
- Cline：用户在同一 session 内多次发消息时，mistake 计数跨 run 累积，第 N 次运行会继承 N-1 次的 mistake 历史
- 我：每次 run 都重置，用户在 session 内多次发消息时，mistake 计数从 0 开始
- Cline 的设计：让长期"卡循环"的 session 最终被强制中止（即使每次 run 都没触发硬阈值）
- 我的设计：每次 run 独立计算，更适合"每次任务是独立的"量化场景
- 语义不等价，但我的实现可能更适合量化场景（每次研报生成是独立任务）

**修复建议**：
1. 短期：保持 per-run reset（量化场景下合理）
2. 长期：可选在 `SessionState` 层增加 per-session mistake 累积，用于检测"长期低效"session，但需评估是否真的需要

**优先级**：P2

---

## 4. 一致性统计

| 一致性等级 | 数量 | 子项 |
|-----------|------|------|
| 完全一致 | 3 项 | M1, M2, M5 |
| 弱对齐 | 5 项 | M3, M4, M10, M11, M13 |
| 缺失 | 1 项 | M12（Cline rules.ts 非安全引擎，语义不符） |
| 额外增强（语义不等价） | 4 项 | M6, M7, M8, M9 |

**对齐度计算**：
- 完全一致：3 × 1.0 = 3.0
- 弱对齐：5 × 0.5 = 2.5
- 缺失：1 × 0 = 0
- 额外增强（语义不等价）：4 × 0.3 = 1.2（增强但不构成对齐）
- 总计：(3.0 + 2.5 + 0 + 1.2) / 13 ≈ **51%**

**核心结论**：
- LoopDetectionTracker 部分（M1-M5）对齐度高（3/5 完全一致）
- MistakeTracker 部分（M6-M10）设计哲学不同，我的实现更精细但与 Cline 不等价
- 集成层（M11-M13）架构差异显著

---

## 5. 修复建议

### 短期（P1）

1. **M3 软阈值注入 LLM 上下文**（`agent/runtime.py` `_loop_detection_hook`）
   - 将 `verdict.message` 作为 user 消息追加到 `self._state.messages`
   - 发射 `message_added` 事件让前端可见
   - 让 LLM 在下一轮看到"建议换思路"提示

2. **M4 硬阈值联动 MistakeTracker**（`agent/runtime.py` `_loop_detection_hook` + `agent/mistake_tracker.py` `record`）
   - 给 `MistakeTracker.record` 增加 `force_at_limit: bool = False` 参数，对标 Cline
   - 硬阈值时调用 `self._mistake_tracker.record(..., force_at_limit=True)`，由 MistakeTracker 决定 abort
   - 统一 abort 路径，避免两个 tracker 各自为政

### 中期（P2）

3. **M10 abort 标记对齐**（`agent/runtime.py` `_check_repeated_tool_failures`）
   - `outcome.action == "stop"` 时调用 `self.abort(outcome.message)` 而非抛 RuntimeError
   - 使 status 一致为 "aborted"，前端可区分"mistake limit 中止"vs"系统失败"

4. **M6/M7 默认阈值对齐**（`agent/mistake_tracker.py` `MistakeTrackerConfig`）
   - `max_total` 默认值改为 6（对标 Cline `maxConsecutiveMistakes ?? 6`）
   - 保留 `max_per_type` 作为合理增强

5. **M8 增加 reason 显式传入支持**（`agent/mistake_tracker.py` `record`）
   - 增加可选 `reason` 参数，调用方明确知道类型时优先用传入值
   - `classify_mistake` 仅在 reason 缺失时作为兜底

6. **M11 增加 loop_detection_enabled 开关**（`agent/types.py` `AgentRuntimeConfig`）
   - 增加 `loop_detection_enabled: bool = True`，对标 Cline `loopDetectionDisabled`

### 长期（P3）

7. **M9 考虑 on_limit_reached 回调机制**
   - 让上层（CLI 交互模式）可注册回调，在硬阈值触发时决策 continue/stop
   - 对标 Cline `onConsecutiveMistakeLimitReached` 回调 + CLI 的 `createMistakeLimitDecisionResolver`（询问用户）

8. **M12 文档修正**
   - 将对比维度 M12 描述改为"用户指令规则注入"，避免误解为 safety 引擎
   - 若需要用户自定义规则注入 system prompt，可在 `context.py` 实现

9. **M13 评估 per-session mistake 累积需求**
   - 量化场景下每次 run 独立，per-run reset 可能合理
   - 若需检测"长期低效 session"，可在 `SessionState` 层增加 per-session 累积

---

## 6. 验证记录

### 6.1 已读取的源文件

**Cline 源码**：
- `third_party/cline/sdk/packages/core/src/runtime/safety/loop-detection.ts`（162 行）
- `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts`（230 行）
- `third_party/cline/sdk/packages/core/src/runtime/safety/rules.ts`（49 行）
- `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`（关键片段 L281-291, L400-444, L538-542, L1084-1098, L1244-1310）
- `third_party/cline/apps/cli/src/runtime/interactive/mistakes.ts`（60 行，CLI 的 onLimitReached 决策器）
- `third_party/cline/sdk/packages/shared/src/agents/types.ts`（ConsecutiveMistakeLimitContext/Decision 定义）

**我的实现**：
- `agent/loop_detection.py`（123 行）
- `agent/mistake_tracker.py`（242 行）
- `agent/runtime.py`（关键片段 L215-254, L317-338, L446-480, L1019-1116）
- `agent/types.py` L300-308（LoopDetectionConfig 定义）

### 6.2 关键验证点

| 验证点 | Cline | 我 | 结论 |
|--------|-------|------|------|
| LoopDetectionConfig 默认值 | soft=3, hard=5（L113-116） | soft=3, hard=5（types.py L307-308） | 一致 |
| toolCallSignature 实现 | sortKeys + JSON.stringify（L40-59） | _sort_keys + json.dumps（L37-62） | 一致 |
| 软阈值消息注入 | appendMessage user（L1258-1261） | logger.warning（L1040-1043） | 不等价 |
| 硬阈值 abort 路径 | 经 MistakeTracker forceAtLimit（L1265-1273） | 直接 BeforeToolResult stop（L1033-1037） | 不等价 |
| MistakeReason 枚举 | 3 类（L39-42） | 5 类（L21-28） | 不等价（我增强） |
| maxConsecutiveMistakes 默认 | 6（orchestrator.ts L405） | max_total=5（L58） | 不一致 |
| mistake 分类 | 调用方传入（L88-150） | classify_mistake 关键词匹配（L81-94） | 不等价（我增强） |
| mistake 软阈值 | 无（仅硬阈值 + onLimitReached 回调） | max_per_type=3 触发 guidance（L188-194） | 不等价（我增强） |
| mistake limit abort | activeRuntime.abort（L1307） | raise RuntimeError（L1091） | 不等价 |
| 集成点 | tool-started 事件（L1093） | before_tool hook（L233） | 路径不同 |
| rules.ts 实际功能 | 用户指令注入 system prompt | 无对应 | 语义不符 |
| 状态生命周期 | per-session（orchestrator 持有） | per-run（runtime 持有，run 入口 reset） | 不等价 |

### 6.3 Cline MistakeLimitExceeded 文档勘误

任务计划文档（AGENT_CLINE_COMPARISON_PLAN.md L575）提到 M10 对比项为"硬阈值 abort 标记（MistakeLimitExceeded）"，但**Cline 源码中不存在 `MistakeLimitExceeded` 异常类型**：
- 在 `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts` 中无此类型
- 在 `third_party/cline/sdk/packages/shared/src/agents/types.ts` 中无此类型
- 全局 grep "MistakeLimitExceeded" 在 Cline 源码中无匹配
- Cline 实际通过 `outcome.action === "stop"` + `activeRuntime.abort()` 实现 abort，无专门异常类型

建议文档修正此描述。

---

**阶段 M 结论**：
- LoopDetectionTracker 部分（M1-M5）对齐度良好，3/5 完全一致，核心数据结构与签名算法与 Cline 1:1 对齐
- 主要 P1 差距：M3 软阈值未注入 LLM 上下文、M4 硬阈值未联动 MistakeTracker
- MistakeTracker 部分（M6-M10）我的实现更精细（按类型分类 + 软阈值 + 关键词分类），但与 Cline 设计哲学不等价，应保留为合理增强并补充 force_at_limit 联动路径
- rules.ts（M12）对比维度本身有歧义，Cline 的 rules.ts 非安全引擎
- 整体对齐度约 51%，修复 P1 差距后可达约 65%
