# Stage 4: P1 上下文与提示对齐方案

> 生成时间：2026-07-26
> 优先级：P1
> 预估工作量：1 周
> 依赖：stage_2（核心架构对齐，BeforeModelContext / AgentMessage metadata 等基础设施）
>
> 来源：
> - `CLINE_DIFF/phase_J_context_compaction.md`（J4 / J6 / J15 / J20）
> - `CLINE_DIFF/phase_K_budget_projection.md`（K6 / K7）
> - `CLINE_DIFF/phase_L_system_prompt.md`（L2 / L4 / L6 / L14 / L18）
>
> 涉及源文件：
> - 我的：`agent/context.py`、`agent/budget_policy.py`、`agent/events.py`、`agent/hooks.py`、`agent/types.py`
> - Cline：`sdk/packages/core/src/extensions/context/`、`sdk/packages/shared/src/prompt/`、`sdk/packages/core/src/services/workspace/`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 4.1 | 上下文压缩触发条件对齐 | J4 | P1 | agent/context.py |
| 4.2 | 压缩后消息结构对齐 | J15 | P1 | agent/context.py |
| 4.3 | apply_budget_policy 补齐 4 步流水线 | K7 | P1 | agent/budget_policy.py |
| 4.4 | env 段补齐 IDE 字段 | L2 | P2 | agent/context.py |
| 4.5 | user_input mode 标签补齐 | L4 | P2 | agent/context.py |
| 4.6 | git 状态注入 | L18 | P2 | agent/context.py |
| 4.7 | _is_safe_cut_boundary 修复 | J6 | P2 | agent/context.py |
| 4.8 | 压缩事件 emit 补齐 | J20 | P2 | agent/context.py、agent/events.py |

依赖关系：
- 4.2（summary metadata）是 4.7（识别 compaction_summary）的前置条件
- 4.3（4 步流水线）独立可执行，但建议在 4.1 后做（便于 build_budget_projection 复用 token 估算）
- 4.4 / 4.5 / 4.6 互相独立，可并行
- 4.8 独立可执行，但需先确认 4.2 的 metadata 结构以便事件 payload 复用

---

## 4.1 上下文压缩触发条件对齐（J4）

### 任务背景

来源 Phase J #J4。Cline 的 `shouldCompact` 触发条件使用 `requestInputTokens`，该值通过 `estimateRequestInputTokens({systemPrompt, messages, tools})` 统一估算，包含 system prompt + messages + tools 描述三部分（`compaction.ts:289-312`）。

我的实现 `agent/context.py:751-756` 中 `should_compact` 仅用 `estimate_messages_tokens(messages)` 估算消息 token 数，不含 system prompt 和 tools。虽然 Phase 29.4 的 budget_projection 在投影路径中部分弥补（投影含 tools_tokens，见 `context.py:843-854`），但常规阈值触发路径仍遗漏 system prompt。

影响：当 system prompt 较长（含 AGENTS.md / rules / skills 摘要，通常 2000-5000 tokens）时，我会延迟触发压缩。实际请求 token 数可能已超阈值，但 `should_compact` 返回 False，导致 LLM 请求被拒绝或截断。

### 目标

对齐 Cline `requestInputTokens` 语义：在 `should_compact` 的常规阈值触发路径中，把 system prompt 的 token 估算纳入比较，使触发时机与 Cline 一致。

### 当前实现位置

- `agent/context.py:716-756`（`should_compact` 方法）
- `agent/context.py:751-756`（常规触发：`total_tokens = estimate_messages_tokens(messages)`）
- `agent/context.py:893-943`（`before_model` 调用 `should_compact`，未传 system_prompt）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction.ts:289-312`
  - L289-293：`estimateRequestInputTokens({systemPrompt, messages, tools})` 统一估算
  - L307：`requestTriggerTokens = maxInputTokens * COMPACTION_TRIGGER_RATIO`
  - L312：`shouldCompact = requestInputTokens >= requestTriggerTokens`

### 修复步骤建议

1. **在 `ContextCompactor` 中新增 system prompt token 估算能力**
   - 在 `should_compact` 方法签名增加可选参数 `system_prompt: str | None = None`
   - 保留原 `total_tokens = estimate_messages_tokens(messages)` 逻辑不动
   - 在常规触发比较前，计算 `request_tokens = total_tokens + estimate_tokens(system_prompt or "")`
   - 将 `if total_tokens >= self._trigger_tokens` 改为 `if request_tokens >= self._trigger_tokens`
   - budget_projection 分支保持不变（投影路径已含 tools_tokens，但仍可补 system_prompt 估算以统一口径）

2. **在 `before_model` 中传入 system_prompt**
   - `ctx.request.system_prompt` 已存在于 `AgentModelRequest`（见 `agent/types.py`）
   - 修改 `before_model` L943 调用：`self.should_compact(messages, tools=tools, system_prompt=ctx.request.system_prompt)`

3. **同步更新 `get_stats` 调用**（`context.py:1693`）
   - `get_stats` 内部调用 `should_compact`，需传入 system_prompt 参数；若 `get_stats` 调用方未提供，传 None 保持向后兼容

4. **补充日志字段**（可选，对齐 J17 可观测性，本任务不强制）
   - 在 `before_model` 触发日志中增加 `system_prompt_tokens` / `request_tokens` 字段

### 验证方法

1. 构造一个长 system prompt（约 5000 tokens）+ 短消息列表（约 10000 tokens）的场景
2. 设置 `max_input_tokens=128000, trigger_ratio=0.9`，则 `_trigger_tokens=115200`
3. 旧逻辑：`total_tokens=10000 < 115200` 不触发；新逻辑：`request_tokens=15000 < 115200` 也不触发（符合预期，因为确实未超阈值）
4. 构造超阈值场景：消息 110000 tokens + system_prompt 8000 tokens = 118000 > 115200，新逻辑应触发，旧逻辑（110000 < 115200）不触发
5. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`should_compact` 当前已有 `tools` 参数和 budget_projection 分支，修改时不能破坏这两条路径
- 保留原函数逻辑：`total_tokens = estimate_messages_tokens(messages)` 仍需保留（用于日志和 budget_projection 的 current_tokens 传入），只是阈值比较改用 `request_tokens`
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：system_prompt 为 None 时 `estimate_tokens("")` 返回 0，自然退化为原行为
- budget_projection 分支的 `current_tokens` 参数（L769）仍传 `total_tokens`（仅 messages），因为投影公式 `projected = current + tools + avg_tool_result` 已单独处理 tools，避免重复计入

---

## 4.2 压缩后消息结构对齐（J15）

### 任务背景

来源 Phase J #J15。Cline 的压缩后 summary message 带 `metadata.kind = "compaction_summary"` 标记，下游通过 `isCompactionSummaryMessage` 识别（关联 J6 切割边界、J13 状态投影）。

- Cline agentic 策略（`compaction-shared.ts:720-740` `buildSummaryMessage`）：summary message 仅含 LLM 摘要文本，metadata 为 `{kind: "compaction_summary", summary, details: fileOps, tokensBefore, generatedAt: Date.now()}`
- Cline basic 策略（`basic-compaction.ts:638-663`）：把 dropped_work 嵌入 surviving typed user messages，第一条 typed user 附加 `{kind: "compaction", reason, displayRole: "system", messagesRemoved, usageBefore}`

我的实现 `agent/context.py:1077-1085` 把 LLM 摘要 + dropped_work_block 拼接成单一消息，且不带任何 metadata。直接影响：
1. J6 无法识别 compaction_summary 消息（切割边界判定错误）
2. J13 state-aware 重新压缩时无法跳过已有 summary
3. 前端无法区分显示角色

### 目标

给 `summary_message` 添加 `metadata.kind = "compaction_summary"` 标记及关联字段，使下游能识别这是压缩摘要消息。`AgentMessage` 已有 `metadata` 字段（`agent/types.py:99`），无需扩展数据结构。

### 当前实现位置

- `agent/context.py:1077-1085`（`compact` 方法中创建 summary_message）
- `agent/context.py:1009-1087`（`compact` 方法整体，summary_message 在末尾返回）

### 目标源代码位置

- Cline agentic：`third_party/cline/sdk/packages/core/src/extensions/context/compaction-shared.ts:720-740`
  ```ts
  metadata: {
      kind: "compaction_summary",
      summary: options.summary,
      details: options.fileOps,
      tokensBefore: options.tokensBefore,
      generatedAt: Date.now(),
  }
  ```
- Cline basic：`third_party/cline/sdk/packages/core/src/extensions/context/basic-compaction.ts:638-663`
  - `compactionMetadata = {kind: "compaction", reason, displayRole: "system", messagesRemoved, usageBefore}`

### 修复步骤建议

1. **在 `compact` 方法中收集 tokensBefore**
   - 在 `context.py:1049`（`old_messages = messages[:cut_index]`）后计算 `tokens_before = estimate_messages_tokens(old_messages)`
   - 该值用于 metadata.tokensBefore 字段

2. **给 summary_message 添加 metadata**
   - 修改 `context.py:1077-1085` 的 `AgentMessage(...)` 构造，增加 `metadata` 参数：
     ```python
     import time
     summary_message = AgentMessage(
         role=MessageRole.USER,
         content=[TextPart(text=(
             "# 对话历史摘要\n\n"
             f"{summary_text}\n\n"
             f"{dropped_work_block}\n\n"
             "--- 以上为之前的对话摘要，以下是最近的对话 ---"
         ))],
         metadata={
             "kind": "compaction_summary",
             "summary": summary_text,
             "details": {
                 "readFiles": tool_activity.get("readFiles", []),
                 "editedFiles": tool_activity.get("editedFiles", []),
                 "commands": tool_activity.get("commands", []),
             },
             "tokensBefore": tokens_before,
             "generatedAt": int(time.time() * 1000),  # 毫秒时间戳，对齐 Cline Date.now()
         },
     )
     ```
   - 保留原 content 文本结构不动（含 dropped_work_block 拼接），本阶段只补 metadata
   - 后续可考虑对齐 Cline agentic 策略把 dropped_work_block 移出 summary_message，但本阶段先做 metadata 对齐以解除 J6/J13 依赖阻塞

3. **同步更新 CompactionStateManager 持久化**（`context.py:603-619`）
   - `_message_to_dict` / `_dict_to_message` 需确认能正确序列化/反序列化 metadata 字段
   - 若 `agent/session.py` 的 `_message_to_dict` 已处理 metadata，则无需改动；否则需补 metadata 序列化

### 验证方法

1. 触发一次压缩，检查 `summary_message.metadata["kind"] == "compaction_summary"`
2. 检查 metadata 含 `summary` / `details` / `tokensBefore` / `generatedAt` 四个字段
3. 检查 `CompactionStateManager.save` / `load` 能正确往返 metadata
4. 运行 `python tests/test_agent_e2e.py` 验证压缩流程不破坏

### 注意事项

- 不能死板照搬计划：Cline agentic 把 dropped_work_block 移出 summary_message，但我当前 content 文本结构已上线且 LLM 已适应，本阶段不强制对齐 agentic 的 content 结构，仅补 metadata
- 保留原函数逻辑：`compact` 方法的 cut_index / tool_activity / preserved_responses / summary_text / dropped_work_block 计算逻辑全部保留，只在最后构造 AgentMessage 时增加 metadata 参数
- `details` 字段格式参考 Cline `FileOperationSummary`（readFiles/editedFiles/commands），我的 `tool_activity` 字典已含这三个键（`context.py:1337-1341`）
- `generatedAt` 用毫秒时间戳对齐 Cline `Date.now()`，便于后续 telemetry 对齐
- 不写 fallback：metadata 直接构造，不处理序列化失败

---

## 4.3 apply_budget_policy 补齐 4 步流水线（K7）

### 任务背景

来源 Phase K #K7。Cline 的 `buildBudgetProjection`（`project.ts:483-672`）实现 4 步流水线，输出一个能塞进 `targetTokens` 的消息列表：
1. `dropThinkingBlocks` + `pruneEmptyMessages`（L510-519）— 丢弃 thinking 块
2. `dropUnsafeBlocks` + `pruneEmptyMessages`（L526-541）— 丢弃 image/redacted_thinking 块（非 live tail）
3. `truncateMessageText`（L555-594）— 从尾到头按 targetChars 截断文本
4. `collectMessageClosure` + `removeMessagesAt`（L596-645）— 丢整条消息闭包（tool_use/tool_result 配对，从头开始丢）

我的实现 `agent/budget_policy.py:214-240` 的 `apply_budget_policy` 仅实现第 1 步（drop_thinking_blocks），未实现第 2/3/4 步。当真实超预算时，我的 `apply_budget_policy` 无法把消息裁剪到 target 内，只能依赖 `ContextCompactor._simple_summary` / agentic 摘要路径兜底。

### 目标

在 `agent/budget_policy.py` 中补齐 Cline 4 步流水线的剩余 3 步，并新增 `build_budget_projection` 函数对标 Cline `buildBudgetProjection`。保留原 `apply_budget_policy`（仅 step 1）作为 `build_budget_projection` 的子步骤调用。

### 当前实现位置

- `agent/budget_policy.py:214-240`（`apply_budget_policy`，仅 step 1）
- `agent/budget_policy.py:185-211`（`drop_thinking_blocks`，step 1 已实现）
- `agent/budget_policy.py:102-112`（`is_tool_result_only_user_message`）
- `agent/budget_policy.py:115-130`（`find_latest_typed_user_message_index`）
- `agent/budget_policy.py:133-139`（`find_first_typed_user_message_index`）
- `agent/budget_policy.py:153-182`（`find_protected_tail_start_index`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/project.ts:483-672`
  - L510-519：step 1 `dropThinkingBlocks` + `pruneEmptyMessages`
  - L526-541：step 2 `dropUnsafeBlocks` + `pruneEmptyMessages`
  - L555-594：step 3 `truncateMessageText` 循环
  - L596-645：step 4 `collectMessageClosure` + `removeMessagesAt`
- Cline `project.ts:217-241`（`pruneEmptyMessages`）
- Cline `project.ts:301-327`（`dropThinkingBlocks` 含 action 跟踪）
- Cline `project.ts:329-399`（`dropUnsafeBlocks`）
- Cline `project.ts:401-431`（`truncateMessageText`）
- Cline `project.ts:433-481`（`collectMessageClosure` / `removeMessagesAt` / `closureTouchesPinnedMessage`）

### 修复步骤建议

1. **新增数据类**（在 `budget_policy.py` 顶部）
   - `BudgetAction`：`kind: str` / `path: dict` / `reason: str` / `original_size: int` / `final_size: int`
   - `BudgetProjectionWarning`：`code: str` / `message: str`
   - `BudgetProjectionResult`：`status: str` / `messages: list[AgentMessage]` / `actions: list[BudgetAction]` / `live_tail_handling: str` / `estimated_tokens: int` / `warnings: list[BudgetProjectionWarning]`

2. **补齐 step 2：`drop_unsafe_blocks`**
   - 签名：`drop_unsafe_blocks(messages, original_indexes, actions, latest_typed_user_idx, protected_tail_start_idx, policy) -> list[AgentMessage]`
   - 遍历消息，对非 live tail（index < protected_tail_start_idx）且非 latest_typed_user 的消息，丢弃 `ReasoningPart(redacted=True)` 等不安全块
   - 我的 `agent/types.py:50-53` 已有 `ReasoningPart` 含 `redacted` 字段，对齐 Cline `redacted_thinking`
   - 每删一块 push 一条 `BudgetAction(kind="dropped_block", reason="unsafe_to_truncate", ...)`

3. **新增 `prune_empty_messages`**
   - 签名：`prune_empty_messages(messages, original_indexes, actions, reason="empty_after_drop") -> tuple[list[AgentMessage], list[int]]`
   - 移除 `content.length == 0` 的消息，同步更新 original_indexes 映射
   - 对标 Cline `project.ts:217-241`

4. **补齐 step 3：`truncate_message_text`**
   - 签名：`truncate_message_text(message, target_chars) -> AgentMessage`
   - 对 message.content 中的 `TextPart` 截断到 target_chars 字符
   - 跳过 `ToolCallPart` / `ToolResultPart`（不截断工具部分）
   - 对标 Cline `project.ts:401-431`
   - 在 `build_budget_projection` 中循环调用：从尾到头，跳过 latest_typed_user / live tail，按 `targetChars = max(16, target_tokens * chars_per_token / message_count)` 截断

5. **补齐 step 4：`collect_message_closure` + `remove_messages_at`**
   - `collect_message_closure(messages, start_index) -> set[int]`：从 start_index 开始收集 tool_use/tool_result 配对闭包（含关联的 assistant 消息和 tool_result user 消息）
   - `remove_messages_at(messages, original_indexes, closure) -> tuple[list[AgentMessage], list[int]]`：移除闭包内所有消息
   - 对标 Cline `project.ts:433-481`
   - 在 `build_budget_projection` 中循环调用：从头开始，跳过 first/last typed user 和 protected tail，丢整条闭包

6. **新增 `build_budget_projection` 主函数**
   - 签名：`build_budget_projection(messages, target_tokens, intent, estimate_tokens_fn=None) -> BudgetProjectionResult`
   - 按 Cline 4 步流水线实现：
     - target_tokens <= 0 时返回 `status="failed"` + `warnings=[budget_impossible]`
     - step 1：`drop_thinking_blocks` + `prune_empty_messages`（当 policy.drop_thinking_blocks）
     - step 2：`drop_unsafe_blocks` + `prune_empty_messages`（当 policy.drop_unsafe_outside_live_tail）
     - 估算 tokens，若 <= target_tokens 直接返回 `status="ok"`
     - step 3：从尾到头 `truncate_message_text` 循环
     - step 4：从头 `collect_message_closure` + `remove_messages_at` 循环
     - 仍超预算返回 `status="failed"` + `warnings=[budget_unachievable_with_protections]`

7. **保留原 `apply_budget_policy` 不动**
   - 该函数已被 `_project_future_usage`（`context.py:832`）调用，保持原签名和行为
   - 新增 `build_budget_projection` 作为完整 4 步流水线入口，供后续 `ContextCompactor.basic` 路径调用

### 验证方法

1. 单元测试：构造 100 条消息（含 thinking / redacted / tool_use / tool_result），target_tokens 设为 50% 当前 tokens
2. 调用 `build_budget_projection(messages, target_tokens, BudgetPolicyIntent.BASIC_COMPACTION_PROJECTION)`
3. 验证 `result.estimated_tokens <= target_tokens`（或 `result.status == "failed"` 时 warnings 含 `budget_unachievable_with_protections`）
4. 验证 `result.actions` 含 `dropped_block` / `truncated_text` / `dropped_message` 记录
5. 验证 latest_typed_user 和 live tail 未被丢弃
6. 运行 `python tests/test_agent_e2e.py` 验证 `apply_budget_policy` 仍正常工作（未破坏原路径）

### 注意事项

- 不能死板照搬计划：Cline 用 `originalIndexes` 数组维持审计索引，我需根据 Python 列表特性选择合适方式（如保留 `list[int]` 映射或用 `id(message)` 跟踪）
- 保留原函数逻辑：`drop_thinking_blocks`（L185-211）保留原实现，仅在 `build_budget_projection` 中调用；`apply_budget_policy`（L214-240）保留原签名和行为
- `ReasoningPart` 的 `redacted=True` 对应 Cline `redacted_thinking`，需在 `drop_unsafe_blocks` 中识别
- `ToolResultPart` 的 image 内容对应 Cline `image` block，但我的 `ToolResultPart.output` 是 `Any`，需检查是否含 image 数据；本阶段可先处理 `ReasoningPart(redacted=True)`，image 块识别留作后续增强
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`build_budget_projection` 在 target_tokens <= 0 时返回 failed 状态，不做降级处理

---

## 4.4 env 段补齐 IDE 字段（L2）

### 任务背景

来源 Phase L #L2。Cline 的 `<env>` 段含 4 个字段（Platform / Date / IDE / Working Directory），其中 `{{IDE_NAME}}` 在不同 host 传入不同值（VS Code / Cline Cron / Terminal）。

我的实现 `agent/context.py:234-260` 的 `_build_environment` 仅含 3 个字段（工作目录 / 平台 / 日期），缺 IDE 字段。影响：LLM 无法感知当前运行环境（Web / CLI / IDE），影响 IDE 相关建议。

### 目标

在 `_build_environment` 中补齐 IDE 字段，对齐 Cline `<env>` 段结构。IDE 字段通过 `SystemPromptBuilder.__init__` 的 `ide_name` 参数传入，默认值 `"Charles Web"`。

### 当前实现位置

- `agent/context.py:234-260`（`_build_environment` 方法）
- `agent/context.py:105-119`（`SystemPromptBuilder.__init__` 签名）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/prompt/system.ts:7-13`
  ```
  <env>
  1. Platform: {{PLATFORM_NAME}}
  2. Date: {{CURRENT_DATE}}
  3. IDE: {{IDE_NAME}}
  4. Working Directory: {{CWD}}
  </env>
  ```

### 修复步骤建议

1. **`SystemPromptBuilder.__init__` 增加 `ide_name` 参数**
   - 在 `context.py:105-119` 的 `__init__` 签名中增加 `ide_name: str = "Charles Web"`
   - 在 `__init__` body 中赋值 `self.ide_name = ide_name`（紧邻 `self.working_dir` 赋值后）

2. **`_build_environment` 补齐 IDE 字段**
   - 修改 `context.py:253-259` 的 `lines` 列表，在 `f"日期: {today}"` 后插入 `f"IDE: {self.ide_name}"`
   - 保留原字段顺序：工作目录 / 平台 / 日期 / IDE（与 Cline Platform / Date / IDE / CWD 顺序略有不同，但保持中文风格一致性）
   - 保留中文字段名（与 AGENTS.md 风格一致，Cline 用英文字段名是因为其 base prompt 全英文）

3. **调用方传入 ide_name**（可选，本阶段不强制）
   - `agent/runtime.py` 或 `agent/server.py` 中构造 `SystemPromptBuilder` 时可传入 `ide_name="Charles Web"` / `ide_name="Charles CLI"` 等
   - 默认值 `"Charles Web"` 已能覆盖大部分场景

### 验证方法

1. 构造 `SystemPromptBuilder(ide_name="Test IDE")`，调用 `build()`
2. 检查 system prompt 含 `"<env>"` 段且包含 `"IDE: Test IDE"` 行
3. 检查 env 段含 4 个字段（工作目录 / 平台 / 日期 / IDE）
4. 不传 `ide_name` 时默认为 `"Charles Web"`
5. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划：Cline 用英文字段名 + 序号，我用中文字段名无序号，本阶段保持中文风格（与 AGENTS.md 一致），仅补 IDE 字段
- 保留原函数逻辑：`_build_environment` 的 `today` / `plat` 计算逻辑保留，仅在 `lines` 列表中增加一行
- 日期格式保持 `date.today().isoformat()`（ISO 8601，比 Cline `toLocaleDateString` 更稳定），不对齐 Cline 日期格式
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`ide_name` 有默认值，无需处理 None

---

## 4.5 user_input mode 标签补齐（L4）

### 任务背景

来源 Phase L #L4。Cline 的 `MODE_TAG_INSTRUCTIONS`（`cline.ts:21-23`）说明：
1. mode 取值 `plan` / `act` / `yolo`（yolo 与 act 等价但无需逐步确认）
2. "the newest message's mode is what governs right now"（最新 mode 优先）
3. `<mode_notice>` 块标记 mode 切换时刻
4. 同时适用于 plan 和 act 模式

我的实现 `agent/context.py:370-386` 的 `_build_mode_tag_instructions` 仅说明 act / plan 两种 mode，缺 yolo / mode_notice / 最新优先语义。

### 目标

补齐 mode 标签说明，对齐 Cline `MODE_TAG_INSTRUCTIONS` 语义：增加 yolo mode、`<mode_notice>` 块说明、"最新 mode 优先"语义。

### 当前实现位置

- `agent/context.py:370-386`（`_build_mode_tag_instructions` 方法）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/prompt/cline.ts:21-23`
  ```
  # Plan / Act Modes

  User messages arrive wrapped in a <user_input mode="..."> tag. The mode attribute is the interaction mode the user was in when they sent that message: "plan" means plan-mode constraints applied (explore, analyze, and align on a plan -- no edits or state-changing commands), while "act" (or "yolo") means implementation was allowed. If the mode attribute changes between messages, the user switched modes -- the newest message's mode is what governs right now, regardless of what earlier messages allowed. A <mode_notice> block inside a message marks exactly when such a switch happened.
  ```

### 修复步骤建议

1. **修改 `_build_mode_tag_instructions` 返回文本**
   - 在 `context.py:379-386` 的返回字符串中：
     - mode 取值列表增加 `- \`yolo\`: 自动执行模式（如启用），与 act 等价但无需逐步确认`
     - 在 mode 取值列表后增加"最新 mode 优先"语义段落：
       ```
       若连续消息的 mode 标签不同，说明用户切换了模式 —
       以最新消息的 mode 为准，无论之前消息允许什么操作。
       消息内可能出现 `<mode_notice>` 块，标记模式切换的确切时刻。
       ```
     - 保留原"请根据 mode 标签调整行为：plan 模式下不得调用任何写入/编辑类工具..."段落

2. **保留原 plan/act 说明**
   - 不移除原 act / plan 说明文本，仅在其后追加 yolo / mode_notice / 最新优先

### 验证方法

1. 构造 `SystemPromptBuilder()`，调用 `build()`
2. 检查 system prompt 含 `"# 用户消息模式标签"` 段
3. 检查该段含 `yolo` / `mode_notice` / "以最新消息的 mode 为准" 关键字
4. 检查原 act / plan 说明保留
5. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划：Cline 用英文整段描述，我用中文分点 + 段落描述，保持中文风格
- 保留原函数逻辑：原 act / plan 说明保留，仅追加内容
- yolo mode 当前可能未在 runtime 实现（需确认 `agent/tools/plan_mode.py` 是否支持），但标签说明先对齐，便于未来支持
- `mode_notice` 块的注入逻辑不在本阶段范围（需在 `agent/runtime.py` 或 `agent/session.py` 中实现 mode 切换时注入），本阶段仅补 system prompt 说明
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback

---

## 4.6 git 状态注入（L18）

### 任务背景

来源 Phase L #L18。Cline 通过 `processWorkspaceInfo`（`cline.ts:47-62`）序列化 workspace + git 元数据，注入到 `{{CLINE_METADATA}}` slot，含 5 个字段（rootPath / hint / associatedRemoteUrls / latestGitCommitHash / latestGitBranchName）。git 状态通过 `workspace-manifest.ts:133-176` 用 simpleGit 读取。

我的实现 `agent/context.py:234-260` 的 `_build_environment` 仅注入 3 个字段（工作目录 / 平台 / 日期），无 git 状态。影响：LLM 无法感知当前 git 分支与提交，影响代码相关建议（如"在 main 分支上需谨慎修改"）。

### 目标

在 `_build_environment` 中增加 git 状态字段（分支 / 提交 / 远端 URL），对齐 Cline workspace metadata 语义。git 状态通过 `subprocess` 调用 `git` 命令读取（不引入 simpleGit 依赖）。

### 当前实现位置

- `agent/context.py:234-260`（`_build_environment` 方法）
- `agent/context.py:105-119`（`SystemPromptBuilder.__init__` 签名）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/prompt/cline.ts:47-62`（`processWorkspaceInfo` 序列化为 JSON）
- Cline `third_party/cline/sdk/packages/core/src/services/workspace/workspace-manifest.ts:133-176`（git 读取逻辑）
  - L141-150：`getRemotes(true)` 读远端 URL
  - L156-159：`revparse(["HEAD"])` 读 commit hash
  - L167-171：`branch().current` 读分支名

### 修复步骤建议

1. **新增 `_read_git_state` 辅助方法**
   - 在 `SystemPromptBuilder` 类中新增方法：
     ```python
     def _read_git_state(self) -> dict[str, Any]:
         """读取当前工作目录的 git 状态 — 对标 Cline workspace-manifest.ts git 读取"""
         import subprocess
         try:
             branch = subprocess.check_output(
                 ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                 cwd=self.working_dir, stderr=subprocess.DEVNULL,
                 timeout=2,
             ).decode().strip()
             commit = subprocess.check_output(
                 ["git", "rev-parse", "--short", "HEAD"],
                 cwd=self.working_dir, stderr=subprocess.DEVNULL,
                 timeout=2,
             ).decode().strip()
             remote = subprocess.check_output(
                 ["git", "remote", "get-url", "origin"],
                 cwd=self.working_dir, stderr=subprocess.DEVNULL,
                 timeout=2,
             ).decode().strip()
             return {"branch": branch, "commit": commit, "remote": remote}
         except Exception:
             return {}
     ```
   - 对标 Cline `workspace-manifest.ts:156-171`（branch / commit）和 `L141-150`（remote）
   - timeout=2 秒，避免非 git 仓库或网络问题阻塞

2. **`_build_environment` 增加 git 字段**
   - 修改 `context.py:253-259` 的 `lines` 列表构造：
     - 在 `f"日期: {today}"` 后（IDE 字段后，若 4.4 已实施）调用 `git_info = self._read_git_state()`
     - 若 `git_info.get("branch")` 非空，追加 `f"Git 分支: {git_info['branch']}"`
     - 若 `git_info.get("commit")` 非空，追加 `f"Git 提交: {git_info['commit']}"`
     - 若 `git_info.get("remote")` 非空，追加 `f"Git 远端: {git_info['remote']}"`
   - 非 git 仓库时 `git_info` 为空字典，不追加任何 git 字段（自然降级，不报错）

3. **保留原字段顺序**
   - 工作目录 / 平台 / 日期 / IDE（4.4）/ Git 分支 / Git 提交 / Git 远端
   - git 字段放在末尾，便于非 git 仓库时直接省略

### 验证方法

1. 在 git 仓库中构造 `SystemPromptBuilder(working_dir=<git repo>)`，调用 `build()`
2. 检查 env 段含 `Git 分支` / `Git 提交` / `Git 远端` 字段
3. 在非 git 仓库中（如临时目录）构造 `SystemPromptBuilder(working_dir=<non-git>)`，调用 `build()`
4. 检查 env 段不含任何 git 字段，且不抛异常
5. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划：Cline 用 simpleGit 库读取 git 状态，我用 subprocess 调用 git 命令（不引入新依赖）
- 保留原函数逻辑：`_build_environment` 的 `today` / `plat` 计算逻辑保留，仅在 `lines` 列表中条件追加 git 字段
- Cline 把 git 状态序列化为 JSON 注入 `{{CLINE_METADATA}}` slot，我把 git 状态作为 env 段的额外字段（与 4.4 IDE 字段同段），保持 env 段统一性
- `subprocess.check_output` 的 `stderr=subprocess.DEVNULL` 避免 git 命令报错时输出到 stderr
- `timeout=2` 秒，避免网络问题或大仓库阻塞 system prompt 构造
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：非 git 仓库时 `git_info` 为空字典，自然不追加 git 字段（这不是 fallback，是条件追加）

---

## 4.7 压缩 _is_safe_cut_boundary 修复（J6）

### 任务背景

来源 Phase J #J6。Cline 的 `isTurnStartMessage`（`compaction-shared.ts:251-257`）排除 compaction_summary 消息：
```ts
return message.role === "user" && !isToolResultOnlyUserMessage(message) && !isCompactionSummaryMessage(message);
```
`isCompactionSummaryMessage`（`compaction-shared.ts:197-203`）检查 `message.metadata?.kind === "compaction_summary"`。`isSafeCutBoundary`（`compaction-shared.ts:313-315`）调用 `isTurnStartMessage`。

我的实现 `agent/context.py:1119-1153` 的 `_is_safe_cut_boundary` 没有 compaction_summary 检查，会把前次压缩留下的 summary message 当作 typed user message。这导致 `_find_cut_index` 中 `last_turn_start` 错误地指向 summary message，cut_index 偏前，多次压缩后 summary message 会被反复重新纳入切割范围，可能导致摘要被覆盖。

**依赖**：本任务依赖 4.2（summary_message 需带 `metadata.kind = "compaction_summary"`）先完成。

### 目标

在 `_is_safe_cut_boundary` 中排除 compaction_summary 消息，对齐 Cline `isSafeCutBoundary` 语义。新增 `is_compaction_summary_message` 辅助函数识别 summary message。

### 当前实现位置

- `agent/context.py:1119-1153`（`_is_safe_cut_boundary` 方法）
- `agent/context.py:1155-1205`（`_find_cut_index` 方法，调用 `_is_safe_cut_boundary`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction-shared.ts:197-203`
  ```ts
  export function isCompactionSummaryMessage(message): boolean {
      return (message.metadata as { kind?: string } | undefined)?.kind === "compaction_summary";
  }
  ```
- Cline `compaction-shared.ts:251-257`（`isTurnStartMessage` 含 `!isCompactionSummaryMessage`）
- Cline `compaction-shared.ts:313-315`（`isSafeCutBoundary` 调用 `isTurnStartMessage`）

### 修复步骤建议

1. **新增 `is_compaction_summary_message` 辅助函数**
   - 在 `agent/context.py` 的 `_is_safe_cut_boundary` 方法前新增模块级函数：
     ```python
     def is_compaction_summary_message(message: AgentMessage) -> bool:
         """判断消息是否是压缩摘要消息 — 对标 Cline isCompactionSummaryMessage

         基于 message.metadata.kind == "compaction_summary" 识别。
         """
         return message.metadata.get("kind") == "compaction_summary"
     ```
   - 对标 Cline `compaction-shared.ts:197-203`

2. **修改 `_is_safe_cut_boundary` 排除 compaction_summary**
   - 在 `context.py:1143`（`if message.role == MessageRole.USER:` 分支）内，先检查 compaction_summary：
     ```python
     if message.role == MessageRole.USER:
         # 空内容视为安全
         if not message.content:
             return True
         # 压缩摘要消息不是 turn_start，不应作为安全切割边界
         # 对标 Cline isTurnStartMessage 中的 !isCompactionSummaryMessage
         if is_compaction_summary_message(message):
             return False
         # 如果所有 part 都是 ToolResultPart，则不安全
         all_tool_result = all(
             isinstance(part, ToolResultPart) for part in message.content
         )
         return not all_tool_result
     ```
   - 保留原 assistant 分支（L1139-1140）和 user 分支的空内容 / tool_result 检查逻辑

3. **验证 `_find_cut_index` 行为**
   - `_find_cut_index`（L1188-1193）从尾部找 `last_turn_start`，调用 `_is_safe_cut_boundary`
   - 修复后，compaction_summary 消息不再被视为 `last_turn_start`，cut_index 不会错误地指向 summary message
   - 保留 `_find_cut_index` 的其他逻辑不动

### 验证方法

1. 构造消息列表：`[summary_message_with_metadata, user_msg, assistant_msg, user_msg2]`
   - `summary_message_with_metadata` 的 `metadata.kind = "compaction_summary"`
2. 调用 `_is_safe_cut_boundary(summary_message_with_metadata)`，应返回 `False`
3. 调用 `_find_cut_index(messages)`，验证 `last_turn_start` 不指向 index 0（summary_message）
4. 对比无 metadata 的普通 user 消息：`_is_safe_cut_boundary(plain_user_msg)` 仍返回 `True`
5. 运行 `python tests/test_agent_e2e.py` 验证多次压缩场景不破坏

### 注意事项

- 不能死板照搬计划：Cline 的 `isTurnStartMessage` 同时排除 tool_result-only 和 compaction_summary，我的 `_is_safe_cut_boundary` 在 user 分支内顺序检查空内容 / compaction_summary / tool_result-only，逻辑等价
- 保留原函数逻辑：`_is_safe_cut_boundary` 的 assistant 分支和 user 分支的空内容 / tool_result 检查保留，仅插入 compaction_summary 检查
- **依赖 4.2**：若 summary_message 未带 `metadata.kind`，`is_compaction_summary_message` 永远返回 False，本任务修复无效。必须先完成 4.2
- `AgentMessage.metadata` 是 `dict[str, Any]`（`agent/types.py:99`），`.get("kind")` 安全，无需处理 None
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback

---

## 4.8 压缩事件 emit 补齐（J20）

### 任务背景

来源 Phase J #J20。Cline 通过 `emitStatusNotice` 回调 emit 多种压缩事件（`compaction.ts:387-545`）：
- `compacting` / `auto-compacting`（phase: started，含 triggerTokens / targetTokens / maxInputTokens）
- `compacted` / `auto-compacted`（phase: completed，含 tokensBefore / tokensAfter / messagesBefore / messagesAfter）
- `compaction-skipped` / `auto-compaction-skipped`（phase: skipped）
- `compaction-budget-adjusted`（budget emergency，含 policyIntent / actionCount / warningCount）

我的实现完全无 emit 机制，仅通过 `logger.info` 输出日志（`context.py:948` / `1002`）。影响：前端无法实时显示"正在压缩..."状态提示，用户无法感知压缩发生，无法通过事件流追踪压缩历史。

### 目标

在 `agent/events.py` 中新增压缩事件类型，在 `ContextCompactor.before_model` 中触发压缩时 emit 对应事件。事件通过 `BeforeModelContext` 暴露的 emit 回调或 `EventEmitter` 引用发射。

### 当前实现位置

- `agent/context.py:893-1007`（`before_model` 方法，仅 `logger.info`）
- `agent/context.py:948-953`（触发日志，对应 Cline started 事件位置）
- `agent/context.py:1002-1005`（完成日志，对应 Cline completed 事件位置）
- `agent/events.py:32-54`（事件类型常量，无压缩事件）
- `agent/events.py:331-345`（`make_status_notice` 辅助函数）
- `agent/hooks.py:85-93`（`BeforeModelContext` 类，无 emit 回调字段）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/compaction.ts:387-399`（started 事件）
  ```ts
  context.emitStatusNotice?.(mode === "manual" ? "compacting" : "auto-compacting", {
      kind: statusReason, reason: statusReason, phase: "started",
      iteration: context.iteration, triggerTokens, targetTokens, maxInputTokens, messageTargetTokens,
  });
  ```
- Cline `compaction.ts:476-489`（completed 事件，含 tokensBefore/tokensAfter/messagesBefore/messagesAfter）
- Cline `compaction.ts:526-533`（budget-adjusted 事件）
- Cline `compaction.ts:536-545`（skipped 事件）

### 修复步骤建议

1. **`agent/events.py` 新增压缩事件类型常量**
   - 在 `events.py:32-54` 的事件类型常量区追加：
     ```python
     # 压缩生命周期 — 对标 Cline emitStatusNotice 的 compaction 事件
     COMPACTION_STARTED = "compaction-started"
     COMPACTION_COMPLETED = "compaction-completed"
     COMPACTION_SKIPPED = "compaction-skipped"
     COMPACTION_BUDGET_ADJUSTED = "compaction-budget-adjusted"
     ```
   - 保留原 `STATUS_NOTICE` 常量不动

2. **`agent/events.py` 新增压缩事件辅助函数**
   - 在 `events.py:331-345`（`make_status_notice`）后追加：
     ```python
     def make_compaction_started(
         snapshot: AgentRuntimeStateSnapshot,
         reason: str,
         trigger_tokens: int,
         target_tokens: int,
         max_input_tokens: int,
         iteration: int | None = None,
     ) -> AgentEvent:
         """构造 compaction-started 事件 — 对标 Cline compacting/auto-compacting"""
         return AgentEvent(
             type=COMPACTION_STARTED,
             snapshot=snapshot,
             iteration=iteration,
             metadata={
                 "kind": reason,
                 "reason": reason,
                 "phase": "started",
                 "trigger_tokens": trigger_tokens,
                 "target_tokens": target_tokens,
                 "max_input_tokens": max_input_tokens,
             },
         )

     def make_compaction_completed(
         snapshot: AgentRuntimeStateSnapshot,
         reason: str,
         tokens_before: int,
         tokens_after: int,
         messages_before: int,
         messages_after: int,
         max_input_tokens: int,
         iteration: int | None = None,
     ) -> AgentEvent:
         """构造 compaction-completed 事件 — 对标 Cline compacted/auto-compacted"""
         return AgentEvent(
             type=COMPACTION_COMPLETED,
             snapshot=snapshot,
             iteration=iteration,
             metadata={
                 "kind": reason,
                 "reason": reason,
                 "phase": "completed",
                 "tokens_before": tokens_before,
                 "tokens_after": tokens_after,
                 "messages_before": messages_before,
                 "messages_after": messages_after,
                 "max_input_tokens": max_input_tokens,
             },
         )

     def make_compaction_skipped(
         snapshot: AgentRuntimeStateSnapshot,
         reason: str,
         max_input_tokens: int,
         iteration: int | None = None,
     ) -> AgentEvent:
         """构造 compaction-skipped 事件 — 对标 Cline compaction-skipped"""
         return AgentEvent(
             type=COMPACTION_SKIPPED,
             snapshot=snapshot,
             iteration=iteration,
             metadata={
                 "kind": reason,
                 "reason": reason,
                 "phase": "skipped",
                 "max_input_tokens": max_input_tokens,
             },
         )
     ```

3. **`ContextCompactor` 增加 emit 回调字段**
   - 在 `ContextCompactor.__init__`（`context.py:672-714`）增加可选参数 `emit_event: Callable[[AgentEvent], Awaitable[None]] | None = None`
   - 赋值 `self.emit_event = emit_event`
   - 保留原 `model` / `state_manager` 等参数不动

4. **`before_model` 中 emit 压缩事件**
   - 在 `context.py:943`（`if not self.should_compact(...)`）的 `return None` 前 emit skipped 事件：
     ```python
     if not self.should_compact(messages, tools=tools, system_prompt=ctx.request.system_prompt):
         if self.emit_event is not None:
             from agent.events import make_compaction_skipped
             await self.emit_event(make_compaction_skipped(
                 snapshot=ctx.snapshot,
                 reason="auto_compaction",
                 max_input_tokens=self.max_input_tokens,
             ))
         return None
     ```
   - 在 `context.py:948`（触发日志后）emit started 事件：
     ```python
     if self.emit_event is not None:
         from agent.events import make_compaction_started
         await self.emit_event(make_compaction_started(
             snapshot=ctx.snapshot,
             reason="auto_compaction",
             trigger_tokens=self._trigger_tokens,
             target_tokens=int(self.max_input_tokens * self.trigger_ratio * 0.7),  # 压缩后目标约 70%
             max_input_tokens=self.max_input_tokens,
         ))
     ```
   - 在 `context.py:1002`（完成日志后）emit completed 事件：
     ```python
     if self.emit_event is not None:
         from agent.events import make_compaction_completed
         tokens_before = estimate_messages_tokens(messages)
         tokens_after = estimate_messages_tokens(compacted)
         await self.emit_event(make_compaction_completed(
             snapshot=ctx.snapshot,
             reason="auto_compaction",
             tokens_before=tokens_before,
             tokens_after=tokens_after,
             messages_before=len(messages),
             messages_after=len(compacted),
             max_input_tokens=self.max_input_tokens,
         ))
     ```
   - 保留原 `logger.info` 日志不动，事件 emit 是额外增加

5. **调用方注入 emit 回调**
   - `agent/runtime.py` 或 `agent/server.py` 构造 `ContextCompactor` 时传入 `emit_event=runtime.emit`（runtime 的 EventEmitter.emit 方法）
   - 本阶段不强制修改调用方，`emit_event` 默认 None 时退化为原行为（仅日志）

### 验证方法

1. 构造 `EventEmitter`，订阅事件：`emitter.subscribe(lambda e: print(e.type, e.metadata))`
2. 构造 `ContextCompactor(emit_event=emitter.emit)`，触发压缩
3. 验证订阅器依次收到 `compaction-started` → `compaction-completed` 事件
4. 验证 `compaction-completed` 事件 metadata 含 `tokens_before` / `tokens_after` / `messages_before` / `messages_after`
5. 不触发压缩时（消息数不足），验证收到 `compaction-skipped` 事件
6. `emit_event=None` 时验证退化为原行为（仅日志，不抛异常）
7. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划：Cline 用 `context.emitStatusNotice?.(...)` 可选链调用，我用 `if self.emit_event is not None` 显式判断，语义等价
- 保留原函数逻辑：`before_model` 的 state-aware 加载 / should_compact / compact / state 保存逻辑全部保留，事件 emit 是在原日志位置额外增加
- `AgentEvent.metadata` 是 `Any`（`agent/types.py` / `agent/events.py:80`），可传 dict，无需扩展数据结构
- `ctx.snapshot` 已存在于 `BeforeModelContext`（`agent/hooks.py:91`），可直接用于事件构造
- `emit_event` 是 async 回调（`Callable[[AgentEvent], Awaitable[None]]`），与 `EventEmitter.emit` 签名一致
- budget-adjusted 事件（Cline `compaction.ts:526-533`）依赖 `build_budget_projection` 的 `actions` / `warnings`（关联 4.3），本阶段可先不实现，待 4.3 完成后补
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`emit_event=None` 时跳过 emit，这不是 fallback，是可选回调

---

## 附录：执行顺序建议

按依赖关系推荐执行顺序：

1. **第一批（独立可并行）**：4.4（env IDE）、4.5（mode 标签）、4.6（git 状态）
   - 这三个任务互相独立，仅改 `agent/context.py` 的 `SystemPromptBuilder`，无跨文件依赖
2. **第二批（独立可并行）**：4.3（4 步流水线）、4.8（事件 emit）
   - 4.3 改 `agent/budget_policy.py`，4.8 改 `agent/events.py` + `agent/context.py`，无冲突
3. **第三批（有依赖）**：4.1（触发条件）、4.2（消息结构）
   - 4.1 改 `should_compact` 签名，4.2 改 `compact` 输出，建议先 4.2 后 4.1（4.1 的日志可复用 4.2 的 tokensBefore）
4. **第四批（依赖 4.2）**：4.7（_is_safe_cut_boundary）
   - 必须在 4.2 完成后执行，否则 `is_compaction_summary_message` 永远返回 False

每批完成后运行 `python tests/test_agent_e2e.py` 验证不破坏现有功能。

---

## 附录：一致性预期

完成本阶段后，Phase J / K / L 对齐度提升预期：

| Phase | 当前对齐度 | 完成后预期 | 关键提升项 |
|-------|-----------|-----------|-----------|
| Phase J（上下文压缩） | 60% | 80% | J4 触发条件 + J15 metadata + J6 切割边界 + J20 事件 |
| Phase K（budget projection） | 71% | 85% | K7 4 步流水线补齐 |
| Phase L（系统提示） | 50% | 70% | L2 IDE + L4 mode + L18 git |

未覆盖项（留待后续阶段）：
- J7（工具活动摘要行号范围）— P2，影响摘要信息密度
- J12（abort 错误识别）— P2，依赖 abort signal 传递链路
- J13（CompactionStateManager 持久化字段）— P2，需补 system_prompt 字段和投影函数
- J17（日志字段丰富化）— P3，可观测性提升
- J18（file/image block 截断）— P2，依赖 4.3 的 truncate_message_text
- K6（drop_thinking_blocks action 跟踪）— P2，依赖 4.3 的 BudgetAction 数据类
- L6（cline-rules 加载顺序）— P2，保持现状
- L14（AGENTS.md 多位置搜索）— P2，保持现状
