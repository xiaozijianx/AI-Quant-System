# Phase J: 上下文压缩 对比报告

> 对标源码：
> - `sdk/packages/core/src/extensions/context/compaction.ts`
> - `sdk/packages/core/src/extensions/context/agentic-compaction.ts`
> - `sdk/packages/core/src/extensions/context/basic-compaction.ts`
> - `sdk/packages/core/src/extensions/context/compaction-shared.ts`
>
> 当前实现：`agent/context.py::ContextCompactor` + `agent/budget_policy.py`
> 对比维度：J1-J20

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 6 项 |
| 弱对齐 | 12 项 |
| 缺失 | 1 项 |
| 额外增强 | 1 项 |
| **对齐度** | **约 60%** |

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| J1 | `maxInputTokens` 默认值 | compaction-shared.ts:13 `DEFAULT_MAX_INPUT_TOKENS = 128_000` | context.py:532 `_DEFAULT_MAX_INPUT_TOKENS = 128000` | 完全一致 |
| J2 | `triggerRatio` 默认值 | compaction-shared.ts:17 `COMPACTION_TRIGGER_RATIO = 0.9` | context.py:529 `_DEFAULT_COMPACTION_TRIGGER_RATIO = 0.9` | 完全一致 |
| J3 | `preserveRecentTokens` 默认值 | compaction-shared.ts:19 `DEFAULT_PRESERVE_RECENT_TOKENS = 20_000` | context.py:535 `_DEFAULT_PRESERVE_RECENT_TOKENS = 20000` | 完全一致 |
| J4 | `should_compact` 触发条件 | compaction.ts:312 `requestInputTokens >= requestTriggerTokens`（含 system+tools） | context.py:754 `total_tokens >= self._trigger_tokens`（仅 messages） | 弱对齐（语义不等价） |
| J5 | `_find_cut_index` 安全切割 | compaction-shared.ts:317-350 `findCutIndex` | context.py:1155-1205 `_find_cut_index` | 弱对齐 |
| J6 | `_is_safe_cut_boundary` 判定 | compaction-shared.ts:313-315 `isSafeCutBoundary`（含 isCompactionSummaryMessage 检查） | context.py:1119-1153（不检查 compaction_summary） | 弱对齐 |
| J7 | `_summarize_tool_activity` | compaction-shared.ts:535-609（含 diff 行号 + read_files start/end_line） | context.py:1265-1341（仅路径，无行号） | 弱对齐 |
| J8 | `_build_dropped_work_summary_block` | basic-compaction.ts:80-92（无 `-` 前缀） | context.py:1366-1438（带 `-` 前缀） | 弱对齐 |
| J9 | `_build_summary_request` | compaction-shared.ts:643-677 | context.py:1440-1515 | 完全一致 |
| J10 | `_ensure_files_section` | compaction-shared.ts:633-641 `/^## Files$/im`（含 `i` flag） | context.py:1517-1548 `re.MULTILINE`（无 IGNORECASE） | 弱对齐 |
| J11 | `PRESERVED_ASSISTANT_TEXT_COUNT` | basic-compaction.ts:60 `= 3` | context.py:556 `= 3` | 完全一致 |
| J12 | agentic 失败 fallback 到 basic | compaction.ts:419-438（区分 abort 错误） | context.py:955-978（不区分 abort） | 弱对齐 |
| J13 | `CompactionStateManager` 持久化 | compaction.ts:566-622 `createCompactionStateAwarePrepareTurn`（含 system_prompt 投影） | context.py:571-628（仅 summary_message + compacted_count） | 弱对齐 |
| J14 | `before_model` hook 集成 | compaction.ts:248-564 `createContextCompactionPrepareTurn`（prepareTurn 回调） | context.py:893-1007 `before_model`（hook 注册） | 弱对齐 |
| J15 | 压缩后消息结构 | agentic: compaction-shared.ts:720-740（带 metadata）；basic: basic-compaction.ts:649-663（dropped_work 嵌入 typed user） | context.py:1077-1085（混合 summary+dropped_work，无 metadata） | 弱对齐（语义不等价） |
| J16 | `summary_max_tokens` 限制 | compaction-shared.ts:20 `DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS = 1_024` | context.py:541 `_DEFAULT_SUMMARY_MAX_TOKENS = 1024` | 完全一致 |
| J17 | 压缩触发日志 | compaction.ts:313-332 + 458-475（10+ 字段） | context.py:948-953 + 1002-1005（3-2 字段） | 弱对齐 |
| J18 | 工具结果截断 `_truncate_tool_results` | compaction-shared.ts:100-124（处理 string/text/file/image block） | context.py:1089-1117（仅处理 string output） | 弱对齐 |
| J19 | `FileContextTracker` 集成 | Cline 核心 compaction 不集成（仅 vscode 应用层有 FileContextTracker） | context.py:1207-1263 `_summarize_tool_activity_v2` 优先从 tracker 取 | 额外增强 |
| J20 | 压缩事件 emit | compaction.ts:387-399 + 476-489 + 536-545 `emitStatusNotice` 多种事件 | 无 emit 机制，仅 logger.info | 缺失 |

---

## 3. 关键差距详细分析

### 差距 #J4：should_compact 触发条件语义不等价

**严重度**：P1（影响压缩时机精度）

**Cline 实现**（compaction.ts:284-312）：
```ts
const requestInputTokens = estimateRequestInputTokens({
    systemPrompt: context.systemPrompt,
    messages: context.apiMessages,
    tools: context.tools,
});
const requestTriggerTokens = maxInputTokens * COMPACTION_TRIGGER_RATIO;
const shouldCompact = requestInputTokens >= requestTriggerTokens;
```
- `requestInputTokens` 包含 system prompt + messages + tools 描述三部分
- 通过 `estimateRequestInputTokens` 统一估算

**我的实现**（context.py:751-756）：
```python
total_tokens = estimate_messages_tokens(messages)
if total_tokens >= self._trigger_tokens:
    self._last_compaction_reason = "threshold_exceeded"
    return True
```
- `total_tokens` 仅估算 messages，不含 system prompt 和 tools
- 通过 Phase 29.4 的 budget_projection 补偿（投影含 tools_tokens），但仍不含 system prompt

**影响**：
- 当 system prompt 较长（含 AGENTS.md / rules / skills 摘要，通常 2000-5000 tokens）时，我会延迟触发压缩
- 实际请求 token 数可能已超阈值，但 `should_compact` 返回 False，导致 LLM 请求被拒绝或截断
- budget_projection 部分弥补（投影含 tools_tokens），但仍遗漏 system prompt

**修复建议**：
1. 短期：在 `should_compact` 中传入 system_prompt，加入其 token 估算
2. 中期：实现 `estimate_request_input_tokens(system_prompt, messages, tools)` 统一估算函数，对标 Cline `estimateRequestInputTokens`

**优先级**：P1

---

### 差距 #J6：_is_safe_cut_boundary 不识别 compaction_summary 消息

**严重度**：P2（影响多次压缩后的切割精度）

**Cline 实现**（compaction-shared.ts:251-257 + 313-315）：
```ts
export function isTurnStartMessage(message) {
    return (
        message.role === "user" &&
        !isToolResultOnlyUserMessage(message) &&
        !isCompactionSummaryMessage(message)  // 关键：排除 compaction_summary
    );
}
function isSafeCutBoundary(message) {
    return message.role === "assistant" || isTurnStartMessage(message);
}
```

**我的实现**（context.py:1119-1153）：
```python
def _is_safe_cut_boundary(self, message):
    if message.role == MessageRole.ASSISTANT:
        return True
    if message.role == MessageRole.USER:
        if not message.content:
            return True
        all_tool_result = all(isinstance(p, ToolResultPart) for p in message.content)
        return not all_tool_result
    return False
```

**影响**：
- 我的实现没有 `isCompactionSummaryMessage` 检查，会把前次压缩留下的 summary message 当作 typed user message
- 这会导致 `_find_cut_index` 中 `last_turn_start` 错误地指向 summary message，cut_index 偏前
- 多次压缩后，summary message 会被反复重新纳入切割范围，可能导致摘要被覆盖

**修复建议**：
1. 实现 `is_compaction_summary_message(message)` 辅助函数（基于 metadata.kind == "compaction_summary"）
2. 在 `_is_safe_cut_boundary` 中排除 compaction_summary 消息
3. 注意：当前我的 summary message 不带 metadata（见 J15），需先补齐 metadata 才能识别

**优先级**：P2

---

### 差距 #J7：_summarize_tool_activity 缺少行号范围提取

**严重度**：P2（影响摘要信息密度）

**Cline 实现**（compaction-shared.ts:535-609）：
- `readFiles` 支持 `input.files[].start_line/end_line`，输出 `path:start-end` 格式
- `editedFiles` 通过 `extractDiffLineRange` 从 tool_result 内容中解析编号 diff（`-467:` / `+467:`），输出 `path:start-end`
- 通过 `editorPathsByToolUseId` Map 配对 tool_use 和 tool_result

**我的实现**（context.py:1265-1341）：
- `readFiles` 仅提取路径，不解析 start_line/end_line
- `editedFiles` 仅提取路径，不解析 diff 行号范围
- 不配对 tool_use 和 tool_result

**影响**：
- 摘要中文件操作信息密度低（只有路径，无行号范围）
- LLM 难以判断哪些行被读过/改过，可能重复读取或遗漏关键修改
- 长文件场景下（如 1000+ 行），路径级别摘要价值有限

**修复建议**：
1. 在 `_summarize_tool_activity` 中解析 `input.files[].start_line/end_line`
2. 通过 `tool_call_id` 配对 ToolCallPart 和 ToolResultPart
3. 实现 `extract_diff_line_range` 从 tool_result 文本中正则提取 `-N:` / `+N:` 行号

**优先级**：P2

---

### 差距 #J12：agentic 失败 fallback 不区分 abort 错误

**严重度**：P2（影响中断语义）

**Cline 实现**（compaction.ts:419-438）：
```ts
try {
    result = await runBuiltinStrategy(builtinOptions);
} catch (error) {
    if (strategy !== "agentic" || isCompactionCancellation(error, context.abortSignal)) {
        throw error;  // abort 错误直接 re-raise
    }
    // 非 abort 错误才 fallback 到 basic
    result = await BUILTIN_COMPACTION_STRATEGIES.basic(builtinOptions);
}
```
- `isCompactionCancellation` 检查 abortSignal.aborted 或 error.name 是 AbortError / AgentRuntimeAbortError

**我的实现**（context.py:955-978）：
```python
try:
    if self.model is not None:
        compacted = await self.compact(messages, summarize_func=..., session_id=session_id)
    else:
        compacted = await self.compact(messages, summarize_func=None, ...)
except Exception as e:
    logger.warning("ContextCompactor: LLM 摘要失败，回退到 basic 策略: %s", e)
    compacted = await self.compact(messages, summarize_func=None, session_id=session_id)
```

**影响**：
- 用户主动 abort（通过 abort signal）时，我会忽略 abort 错误并 fallback 到 basic 策略继续执行
- 这违背用户意图：用户希望立即停止，但我继续做 basic 压缩
- basic 压缩本身可能成功完成，导致用户难以中止长时间运行的压缩

**修复建议**：
1. 引入 abort signal 检查（或在 BeforeModelContext 中暴露 abort signal）
2. 在 except 中先判断是否是 abort 错误，是则 re-raise
3. 可参考 `agent/abort.py` 中的 abort 异常类型

**优先级**：P2

---

### 差距 #J13：CompactionStateManager 持久化字段不完整

**严重度**：P2（影响多次压缩状态恢复）

**Cline 实现**（compaction.ts:566-622 + session-compaction.ts）：
- 状态字段：`sourceMessages` / `compactedMessages` / `conversationId` / `systemPrompt`
- `projectSessionCompactionState(state, messages)` 投影函数：基于现有 state 和新 messages 重建完整消息列表
- re-compaction 从 `projectedMessages` 开始，避免重复处理

**我的实现**（context.py:562-628）：
- 状态字段：`summary_message` / `compacted_count` / `created_at`
- 应用方式：`messages = [state.summary_message] + messages[state.compacted_count:]`
- 不保存 system_prompt，不调用投影函数

**影响**：
- 我没有保存 system_prompt，跨轮次的 system prompt 变化无法追踪
- 应用状态时直接拼接，不调用 `projectSessionCompactionState`，无法处理消息已被部分修改的情况
- compacted_count 计算依赖 cut_index 推导（context.py:985-990），有累积误差风险

**修复建议**：
1. 在 `CompactionState` 中增加 `system_prompt` 字段
2. 实现 `project_session_compaction_state(state, messages)` 投影函数
3. 在 `before_model` 中先投影再压缩，对标 Cline `createCompactionStateAwarePrepareTurn`

**优先级**：P2

---

### 差距 #J14：before_model hook vs prepareTurn 回调

**严重度**：P3（接入方式不同，功能等价）

**Cline 实现**（compaction.ts:248-564）：
- 工厂函数 `createContextCompactionPrepareTurn(config)` 返回 `ContextPipelinePrepareTurn` 回调
- 回调签名：`(context: ContextPipelinePrepareTurnInput) => Promise<ContextPipelinePrepareTurnResult | undefined>`
- 输入字段：agentId / conversationId / parentAgentId / iteration / messages / apiMessages / abortSignal / systemPrompt / tools / model / emitStatusNotice

**我的实现**（context.py:893-1007）：
- 实例方法 `before_model(ctx: BeforeModelContext) -> BeforeModelResult | None`
- 通过 `runtime.register_hooks(AgentHooks(before_model=compactor.before_model))` 注册
- 输入字段：snapshot / request / session_id

**影响**：
- 功能等价（都是 LLM 调用前触发），但接入方式不同
- 我没有 `emitStatusNotice` 回调（关联 J20 缺失）
- 我没有 `abortSignal`（关联 J12 不能识别 abort 错误）
- 我没有 `iteration` 字段（日志中无法标记轮次）

**修复建议**：
1. 短期：保持 hook 接入方式（功能等价，无须改造）
2. 中期：在 `BeforeModelContext` 中增加 `iteration` / `abort_signal` 字段

**优先级**：P3

---

### 差距 #J15：压缩后消息结构语义不等价

**严重度**：P1（影响 LLM 对话理解和后续压缩识别）

**Cline 实现**：
- **agentic**（compaction-shared.ts:720-740）：
  ```ts
  {
    role: "user",
    content: [{type: "text", text: `Context summary:\n\n${summary}`}],
    metadata: {kind: "compaction_summary", summary, details, tokensBefore, generatedAt}
  }
  ```
  仅含 LLM 摘要，不含 dropped_work_block；带 `kind: "compaction_summary"` metadata

- **basic**（basic-compaction.ts:620-663）：
  - 通过 `mergeAdjacentUserTurns` 把 dropped_work_block 嵌入到 surviving typed user messages
  - 第一条 typed user 消息附加 metadata `{kind: "compaction", reason, displayRole, messagesRemoved, usageBefore}`
  - 非第一条消息附加 `{compaction: "preserved"}` 标记
  - 调用 `stripStaleMetrics` 移除 per-message metrics

**我的实现**（context.py:1077-1085）：
```python
summary_message = AgentMessage(
    role=MessageRole.USER,
    content=[TextPart(text=(
        "# 对话历史摘要\n\n"
        f"{summary_text}\n\n"
        f"{dropped_work_block}\n\n"
        "--- 以上为之前的对话摘要，以下是最近的对话 ---"
    ))],
)
return [summary_message] + recent_messages
```

**影响**：
1. **混合策略**：我把 LLM 摘要 + dropped_work_block 拼接成单一消息，Cline agentic 仅含 LLM 摘要，Cline basic 把 dropped_work_block 嵌入 surviving user 消息。我的混合方式既非 agentic 也非 basic
2. **无 metadata**：summary_message 不带 `kind: "compaction_summary"` 标记，下游无法识别这是压缩摘要消息
   - 直接影响 J6（无法识别 compaction_summary → 切割边界判定错误）
   - 直接影响 J13（state-aware 重新压缩时无法跳过已有 summary）
3. **无 stripStaleMetrics**：保留 per-message metrics，但压缩后这些 metrics 已不再准确
4. **无 displayRole**：前端无法区分显示角色（system vs user）

**修复建议**：
1. 在 `summary_message.metadata` 中添加 `{"kind": "compaction_summary", "summary": ..., "details": ..., "tokensBefore": ..., "generatedAt": ...}`
2. 区分 agentic / basic 策略：agentic 时 dropped_work_block 不放入 summary_message（仅 LLM 摘要）；basic 时按 Cline 方式嵌入 surviving user messages
3. 调用 `stripStaleMetrics` 移除压缩后消息的 metrics 字段
4. 添加 `displayRole: "system"` metadata

**优先级**：P1

---

### 差距 #J17：压缩触发日志字段远少于 Cline

**严重度**：P3（影响可观测性）

**Cline 实现**：
- 触发前 debug 日志（compaction.ts:313-332）：18 个字段（mode/strategy/iteration/providerId/modelId/requestInputTokens/apiMessageTokens/messageInputTokens/requestOverheadTokens/maxInputTokens/requestTriggerTokens/messageTriggerTokens/thresholdRatio/shouldCompact/messageCount/apiMessageCount/apiMessagesJsonChars/toolResultCount/toolResultSerializedChars/maxToolResultSerializedChars）
- 完成后 info 日志（compaction.ts:458-475）：14 个字段（strategy/maxInputTokens/messageInputTokens/apiInputTokens/requestInputTokens/requestOverheadTokens/afterMessageTokens/afterRequestTokens/tokensSaved/utilizationBefore/utilizationAfter/thresholdTrigger/messagesBefore/messagesAfter/messagesRemoved）
- skip 日志 + budget emergency 日志

**我的实现**：
- 触发日志（context.py:948-953）：3 字段（messages 数 / tokens 估算 / reason）
- 完成日志（context.py:1002-1005）：2 字段（messages 前后数）

**影响**：
- 难以诊断压缩触发时机异常（无法对比 requestInputTokens vs triggerTokens）
- 难以评估压缩效果（无 tokensSaved / utilizationBefore / utilizationAfter）
- 难以排查 tool_result 撑爆上下文问题（无 toolResultCount / maxToolResultSerializedChars）

**修复建议**：
1. 在 `before_model` 触发前补充 debug 日志：`maxInputTokens / triggerTokens / currentTokens / thresholdRatio / shouldCompact / messageCount / toolResultCount`
2. 在压缩完成后补充 info 日志：`tokensBefore / tokensAfter / tokensSaved / messagesBefore / messagesAfter / utilizationBefore / utilizationAfter`
3. 可观测性提升优先级，但非阻塞功能

**优先级**：P3

---

### 差距 #J18：_truncate_tool_results 不处理 file/image block

**严重度**：P2（影响长 tool_result 截断完整性）

**Cline 实现**（compaction-shared.ts:100-124）：
```ts
function truncateToolResultContentForCompaction(content) {
    if (typeof content === "string") {
        return truncateText(content, TOOL_RESULT_CHAR_LIMIT);
    }
    return content.map(block => {
        switch (block.type) {
            case "text": return {...block, text: truncateText(block.text, TOOL_RESULT_CHAR_LIMIT)};
            case "file": return {...block, content: truncateText(block.content, FILE_CONTENT_CHAR_LIMIT)};
            case "image": return block;  // image 不截断
            default: return block;
        }
    });
}
```

**我的实现**（context.py:1089-1117）：
```python
for i, part in enumerate(msg.content):
    if isinstance(part, ToolResultPart):
        output = part.output
        if isinstance(output, str) and len(output) > TOOL_RESULT_CHAR_LIMIT:
            msg.content[i] = ToolResultPart(...)
```
- 仅处理 `output` 是 string 的情况
- 不处理 output 是 dict / list / 含 file 内容的情况
- 不区分 text/file/image block

**影响**：
- 当 ToolResultPart.output 是 dict（如 `{type: "file", path: ..., content: ...}`）时，长内容不会被截断
- 实际工具返回的 file 内容（如 read_files 返回的大文件）不会被截断
- 可能导致压缩后消息仍包含超长 file 内容，撑爆上下文

**修复建议**：
1. 在 `_truncate_tool_results` 中处理 dict 类型 output
2. 递归扫描 output 字段，对 `content` 字段应用 FILE_CONTENT_CHAR_LIMIT 截断
3. 对 `text` 字段应用 TOOL_RESULT_CHAR_LIMIT 截断

**优先级**：P2

---

### 差距 #J20：压缩事件 emit 完全缺失

**严重度**：P2（影响前端可观测性和用户体验）

**Cline 实现**（compaction.ts:387-545）：
- 通过 `emitStatusNotice` 回调 emit 多种事件：
  - `compacting` / `auto-compacting`（phase: started）
  - `compacted` / `auto-compacted`（phase: completed，含 tokensBefore/tokensAfter/messagesBefore/messagesAfter）
  - `compaction-skipped` / `auto-compaction-skipped`（phase: skipped）
  - `compaction-budget-adjusted`（budget emergency）
- 含丰富 metadata：kind / reason / phase / iteration / triggerTokens / targetTokens / maxInputTokens / messageTargetTokens

**我的实现**：
- 完全没有 emit 机制
- 仅通过 `logger.info` 输出日志（context.py:948 / 1002）

**影响**：
- 前端无法实时显示"正在压缩..."状态提示
- 用户无法感知压缩发生（除非查看日志）
- 无法通过事件流追踪压缩历史
- budget emergency（budget 调整）事件无法通知前端

**修复建议**：
1. 在 `BeforeModelContext` 中增加 `emit_status_notice` 回调字段（或在 `AgentHooks` 中增加 `on_compaction` 钩子）
2. 在 `before_model` 中触发压缩时 emit `compacting` 事件
3. 压缩完成后 emit `compacted` 事件，含前后 token 数和消息数
4. 跳过压缩时 emit `compaction-skipped` 事件

**优先级**：P2

---

## 4. 一致性统计

### 按一致性等级

| 一致性 | 数量 | 子项 |
|--------|------|------|
| 完全一致 | 6 | J1, J2, J3, J9, J11, J16 |
| 弱对齐 | 12 | J4, J5, J6, J7, J8, J10, J12, J13, J14, J15, J17, J18 |
| 缺失 | 1 | J20 |
| 额外增强 | 1 | J19 |

### 按严重度分布

| 严重度 | 数量 | 子项 |
|--------|------|------|
| P1 | 2 | J4, J15 |
| P2 | 7 | J6, J7, J12, J13, J18, J20, (J8 视为低危) |
| P3 | 3 | J14, J17, (J5/J10 视为低危) |

### 核心配置完全对齐

J1/J2/J3/J11/J16 五项核心默认值（maxInputTokens / triggerRatio / preserveRecentTokens / PRESERVED_ASSISTANT_TEXT_COUNT / summary_max_tokens）完全一致，说明 Phase 16 对齐 Cline 配置的工作已落地。

---

## 5. 修复建议

### 短期（P1，影响压缩正确性）

1. **J15 消息结构对齐**：
   - 给 `summary_message` 添加 `metadata={"kind": "compaction_summary", "summary": ..., "details": ..., "tokensBefore": ..., "generatedAt": ...}`
   - 解除 J6 的依赖（识别 compaction_summary 后才能正确判定切割边界）

2. **J4 触发条件对齐**：
   - 在 `should_compact` 中增加 system_prompt token 估算
   - 短期方案：`request_tokens = total_tokens + estimate_tokens(system_prompt) + tools_tokens`
   - 阈值比较改为 `request_tokens >= self._trigger_tokens`

### 中期（P2，影响压缩质量和可观测性）

3. **J6 切割边界识别 compaction_summary**：
   - 实现 `is_compaction_summary_message(message)` 辅助函数
   - 在 `_is_safe_cut_boundary` 中排除 compaction_summary 消息

4. **J7 工具活动摘要补全行号**：
   - 解析 `input.files[].start_line/end_line`
   - 通过 `tool_call_id` 配对 tool_use 和 tool_result，提取 diff 行号范围

5. **J12 abort 错误识别**：
   - 在 `BeforeModelContext` 中暴露 abort signal
   - except 中先判断 abort，再 fallback

6. **J13 状态持久化补全**：
   - `CompactionState` 增加 `system_prompt` 字段
   - 实现 `project_session_compaction_state` 投影函数

7. **J18 file/image block 截断**：
   - 处理 ToolResultPart.output 是 dict 的情况
   - 递归扫描并截断 `content` / `text` 字段

8. **J20 压缩事件 emit**：
   - 在 `BeforeModelContext` 中增加 `emit_status_notice` 回调
   - emit `compacting` / `compacted` / `compaction-skipped` 事件

### 长期（P3，可观测性和接入方式优化）

9. **J14 prepareTurn 接入方式**：
   - 短期保持 hook 接入（功能等价）
   - 长期可考虑增加 `iteration` / `abort_signal` 字段

10. **J17 日志字段丰富化**：
    - 补全 debug / info 日志字段
    - 增加 tool_result 统计字段

11. **J10 IGNORECASE**：
    - 给 `_ensure_files_section` 的正则加 `re.IGNORECASE`

12. **J8 格式细节**：
    - 评估是否需要对齐 `- ` 前缀和空列表显示（影响小，可选）

---

## 6. 验证记录

### 验证范围
- 完整阅读 `compaction.ts`（564 行）
- 完整阅读 `compaction-shared.ts`（741 行）
- 完整阅读 `agentic-compaction.ts`（281 行）
- 完整阅读 `basic-compaction.ts`（695 行）
- 完整阅读 `agent/context.py`（1736 行）
- 完整阅读 `agent/budget_policy.py`（304 行）

### 关键验证点

1. **J1/J2/J3/J11/J16 默认值对比**：字节级核对，5 项默认值与 Cline 完全一致
2. **J4 触发公式对比**：Cline 用 `requestInputTokens`（含 system+tools），我用 `total_tokens`（仅 messages），确认语义不等价
3. **J5 切割算法对比**：从尾部累计 token → 找 last_turn_start → 取 min → 向前调整到安全边界，算法步骤一致；但 J6 的 boundary 判定差异会传导
4. **J9 摘要 prompt 对比**：5 段结构（Goal/State/Highlights/Next/Files）完全一致，Files 行格式一致
5. **J15 消息结构对比**：Cline agentic 单独 LLM 摘要 + metadata；Cline basic dropped_work 嵌入 surviving user + 多种 metadata；我混合拼接无 metadata，确认语义不等价
6. **J19 FileContextTracker**：核对 Cline 核心 compaction 模块（compaction.ts/compaction-shared.ts/agentic-compaction.ts/basic-compaction.ts）均无 FileContextTracker 引用，Cline 该模块仅用 `extractFileOps` 从消息扫描。我的 `_summarize_tool_activity_v2` 优先从 tracker 取，属于额外增强

### 未验证项

- 实际压缩效果对比（需构造 100+ 消息长对话，本对比为静态代码分析）
- abort signal 实际传递路径（需追踪 `BeforeModelContext` 的构造链路）
- CompactionStateManager 持久化文件的跨重启恢复（需端到端测试）

---

**Phase J 结论**：上下文压缩对齐度约 60%。核心默认值（maxInputTokens / triggerRatio / preserveRecentTokens / PRESERVED_ASSISTANT_TEXT_COUNT / summary_max_tokens）5 项完全一致，摘要 prompt 结构（J9）完全一致。主要差距集中在：(1) 触发条件不含 system_prompt（J4）；(2) 消息结构无 metadata 标记（J15），导致 J6 切割边界识别错误传导；(3) 工具活动摘要缺行号范围（J7）；(4) 压缩事件 emit 完全缺失（J20）。我额外增强 FileContextTracker 集成（J19），跨压缩周期保留文件状态，属于合理增强，建议保留。
