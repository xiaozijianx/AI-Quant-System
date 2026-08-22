# Stage 10: P2 核心架构补全方案

> 生成时间：2026-07-26
> 优先级：P2
> 预估工作量：1.5 周
> 依赖：Stage 9 完成（推荐，非强制）
>
> 来源：
> - `CLINE_DIFF/SUMMARY_v2.md` §3.2 P2 级剩余差距 #1-#6
> - `CLINE_DIFF/phase_C_streaming_tool.md`（C8 / C18 / C19）
> - `CLINE_DIFF/phase_B_runtime_loop.md`（B9 / B33）
> - `CLINE_DIFF/phase_A_types.md`（A7 / A16）
>
> 涉及源文件：
> - 我的：`agent/runtime.py`、`agent/types.py`、`agent/providers/qwen.py`、`agent/providers/openai.py`、`agent/providers/base.py`
> - Cline：`third_party/cline/sdk/packages/agents/src/agent-runtime.ts`、`third_party/cline/sdk/packages/shared/src/agent.ts`、`third_party/cline/sdk/packages/core/src/services/llms/`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 10.1 | 流式 metadata 合并链路 | C8 / C18 | P2 | agent/runtime.py、agent/types.py |
| 10.2 | captureUnexpectedReasoningTokens | C19 | P2 | agent/runtime.py、agent/providers/qwen.py |
| 10.3 | reminder 循环前预注入 | B9 | P2 | agent/runtime.py |
| 10.4 | hook stop 状态分类（ControlledStopError） | B33 | P2 | agent/runtime.py、agent/types.py |
| 10.5 | AgentToolContext.metadata 字段 | A7 | P2 | agent/types.py、agent/tools/*.py |
| 10.6 | AgentRuntimeConfig 缺失字段补全 | A16 | P2 | agent/types.py、agent/runtime.py |

依赖关系：
- 10.1 / 10.2 互相独立，可并行（都涉及流式处理但路径不同）
- 10.3 / 10.4 独立
- 10.5 / 10.6 独立
- 建议执行顺序：10.6 → 10.5 → 10.4 → 10.3 → 10.1 → 10.2

---

## 10.1 流式 metadata 合并链路（C8 / C18）

### 任务背景

来源 Phase C #C8 / C18。当前 `PendingToolAssembly` 数据结构中 `metadata` 字段已存在（Stage 2 已补），但**流式累积过程中不填充**：
- LLM Provider（qwen.py / openai.py）解析流式 chunk 时，`tool-call-delta` 事件中 `metadata` 字段始终为 `None`
- `runtime.py::_generate_assistant_message` 中累积 `assembly.metadata` 时，无数据可合并
- 最终 `ToolCallPart.metadata` 字段为空 dict，下游（如 Hooks）无法读取 provider 元数据

Cline 的 `agent-runtime.ts` 中 `PendingToolAssembly.metadata` 在每个 chunk 到达时合并：
- `chunk.metadata` 中的 `provider_metadata` 字段被深度合并到 `assembly.metadata.provider_metadata`
- 用于记录工具调用的 provider 上下文（如 model_version、request_id、finish_reason 等）

### 目标

让流式 metadata 真正流转到 `ToolCallPart.metadata`：
1. LLM Provider 在 `tool-call-delta` 事件中填充 `metadata` 字段
2. `PendingToolAssembly.metadata` 在每个 chunk 到达时深度合并
3. 工具调用组装完成后，`metadata` 写入 `ToolCallPart.metadata`

### 当前实现位置

- `agent/runtime.py`（`PendingToolAssembly` 类、`_generate_assistant_message` 流式累积逻辑）
- `agent/providers/qwen.py`（`stream_chat` 中 `tool-call-delta` 事件构造）
- `agent/providers/openai.py`（同上）
- `agent/types.py`（`ToolCallPart.metadata` 字段，已有）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/agents/src/agent-runtime.ts` L965-1058（PendingToolAssembly 累积逻辑）
- Cline `agent-runtime.ts` L1020-1030（metadata 深度合并）
- Cline `third_party/cline/sdk/packages/core/src/services/llms/llm-gateway.ts`（chunk.metadata 填充）

### 修复步骤建议

1. **LLM Provider 填充 chunk.metadata**
   - 在 `agent/providers/qwen.py` 和 `agent/providers/openai.py` 的 `stream_chat` 方法中：
     - 解析每个流式 chunk 时，提取 `request_id` / `model_version` / `finish_reason` 等字段
     - 构造 `metadata = {"provider_metadata": {...}, "request_id": "...", "model_version": "..."}`
     - 在 `tool-call-delta` 事件中传入 `metadata=metadata`
   - 保留原有 chunk 解析逻辑，仅增加 metadata 字段
   - 不可获取的字段（如 finish_reason 在中间 chunk 中）用 `None`，最终 chunk 才有值

2. **`PendingToolAssembly.metadata` 深度合并**
   - 在 `agent/runtime.py::_generate_assistant_message` 中处理 `tool-call-delta` 事件时：
     - 若 `event.metadata` 非空，深度合并到 `assembly.metadata`
     - 深度合并：`assembly.metadata["provider_metadata"].update(event.metadata.get("provider_metadata", {}))`
     - 顶层字段（如 `request_id`）用覆盖语义（后到为准）
   - 新建 `_deep_merge_metadata(assembly_meta: dict, chunk_meta: dict) -> None` 辅助函数
   - 函数语义：原地修改 `assembly_meta`，无返回值

3. **`ToolCallPart.metadata` 写入**
   - 工具调用组装完成（`_finalize_tool_call`）时，将 `assembly.metadata` 写入 `ToolCallPart.metadata`
   - 保留 `ToolCallPart.metadata` 的默认值 `{}`，仅在有数据时覆盖
   - 不修改 `ToolCallPart` 的其他字段赋值逻辑

4. **metadata 字段标准化**
   - 在 `agent/types.py` 中定义 `PROVIDER_METADATA_FIELDS = ["request_id", "model_version", "finish_reason", "prompt_tokens", "completion_tokens"]`
   - Provider 填充时按此列表标准化字段名，避免拼写不一致
   - 不强制要求所有字段都填充，缺失字段不写入

### 验证方法

1. 调用 agent 触发工具调用，确认 `ToolCallPart.metadata` 包含 `provider_metadata`、`request_id` 等字段
2. 在 `before_tool` hook 中读取 `tool_call.metadata`，确认非空
3. 流式中途网络中断，确认已累积的 metadata 不丢失
4. 不同 Provider（qwen/openai）切换，确认 metadata 字段一致（标准化生效）

### 注意事项

- 深度合并仅对 `provider_metadata` 子字段，其他字段用覆盖语义
- metadata 不可序列化的字段（如 datetime）需转换为字符串
- 不修改 `text-delta` / `reasoning-delta` 事件（仅 tool-call-delta 需要 metadata）

---

## 10.2 captureUnexpectedReasoningTokens（C19）

### 任务背景

来源 Phase C #C19。部分 LLM Provider（如 DeepSeek R1、Claude 3.7 Sonnet）在 `finish_reason="tool_calls"` 时仍可能输出 reasoning content（思考链），但流式响应中未明确以 `reasoning-delta` 事件标识，而是混入 `text-delta`。

当前实现未检测这种情况：
- reasoning content 被误认为普通 text，写入 `TextPart`
- LLM 上下文中出现"思考内容被当成回答"的污染
- 量化场景下，研报生成时 LLM 的推理过程可能泄露到最终输出

Cline 的 `agent-runtime.ts` 中 `captureUnexpectedReasoningTokens` 函数检测 finish 后的 text-delta，若发现则转换为 `ReasoningPart`。

### 目标

实现 `captureUnexpectedReasoningTokens` 机制：
1. 当 `finish_reason="tool_calls"` 或 `"stop"` 后仍收到 text-delta 时
2. 检测 text 内容是否符合 reasoning 模式（如 `<think>...</think>` 标签或纯思考内容）
3. 符合则转换为 `ReasoningPart`，不符合则保留为 `TextPart`

### 当前实现位置

- `agent/runtime.py::_generate_assistant_message`（流式累积循环）
- `agent/providers/qwen.py`（流式 chunk 解析）
- `agent/types.py`（`ReasoningPart` 类型，已有）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/agents/src/agent-runtime.ts`（`captureUnexpectedReasoningTokens` 函数）
- Cline `agent-runtime.ts`（finish 事件后的 text-delta 处理）

### 修复步骤建议

1. **新增 `_capture_unexpected_reasoning_tokens` 方法**
   - 在 `agent/runtime.py` 的 `AgentRuntime` 类中新增方法：
     ```python
     def _capture_unexpected_reasoning_tokens(
         self,
         text_buffer: str,
         finish_reason: str | None,
     ) -> tuple[list[ReasoningPart], str]:
         """检测 finish 后的意外 reasoning tokens，返回 (reasoning_parts, remaining_text)"""
     ```
   - 输入：累积的 text 内容 + finish_reason
   - 输出：识别为 reasoning 的部分 + 剩余的真实 text

2. **reasoning 模式识别**
   - 检测 `<think>...</think>` 标签：用正则 `<think>(.*?)</think>` 提取
   - 检测纯思考内容（无标签但 finish_reason 已为 tool_calls）：启发式判断
     - 内容以"让我" / "我需要" / "首先" / "Let me" / "I need to" 开头
     - 内容长度 > 50 字符且不含句号（思考碎片特征）
   - 不识别则原样返回 text（保守策略，避免误判）

3. **流式累积循环集成**
   - 在 `_generate_assistant_message` 的流式循环中：
     - 收到 `finish` 事件后，若 `text_buffer` 非空，调用 `_capture_unexpected_reasoning_tokens`
     - 转换的 reasoning parts 追加到 `message.content`
     - 剩余 text 作为 `TextPart` 追加（若有）
   - 保留原有 text-delta 累积逻辑，仅在 finish 后增加检测步骤

4. **Provider 兼容性**
   - Qwen / OpenAI Provider 在 `stream_chat` 中正常输出 `reasoning-delta` 事件的不受影响
   - 仅 Provider 未输出 `reasoning-delta` 但 finish 后有 text 时触发检测
   - DeepSeek R1 等模型若已正确输出 `reasoning-delta`，跳过检测

### 验证方法

1. 模拟 DeepSeek R1 响应：finish_reason="tool_calls" 后跟 `<think>xxx</think>` 文本
2. 确认该文本被识别为 `ReasoningPart`，不污染 `TextPart`
3. 正常 finish 后跟普通回答文本（如 "好的，我来执行"），确认不被误判为 reasoning
4. Qwen Plus 正常响应（已有 reasoning-delta 事件），确认检测不触发（回归测试）

### 注意事项

- 启发式判断可能误判，保守策略优先（不确定时保留为 text）
- 不修改 Provider 层的 reasoning-delta 输出逻辑
- 性能考虑：仅在 finish 后触发一次，不在每个 chunk 触发

---

## 10.3 reminder 循环前预注入（B9）

### 任务背景

来源 Phase B #B9。当前 `require_completion_tool=True` 时，若 LLM 第一轮未调用 completing tool，会追加 reminder 消息"请使用 submit_and_exit 工具完成"。但 reminder 在**第一轮失败后**才注入，导致：
- 第一轮 LLM 可能基于不完整上下文生成回答，浪费 token
- 量化场景下，LLM 可能直接生成研报文本而不调用 submit_and_exit，第一轮回答被丢弃

Cline 的 `agent-runtime.ts` 在循环开始前预注入 reminder，提示 LLM "本任务必须以 submit_and_exit 结束"，让 LLM 从第一轮就规划工具调用。

### 目标

实现 reminder 循环前预注入：
1. `require_completion_tool=True` 时，run 开始时注入 system reminder
2. reminder 内容："本任务必须以 <completing_tool> 工具完成，请在适当时候调用"
3. reminder 作为 system message 注入（不污染 user/assistant 历史）

### 当前实现位置

- `agent/runtime.py`（`run()` 方法主循环、`completion_policy` 处理）
- `agent/types.py`（`CompletionPolicy` 类型，已有）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/agents/src/agent-runtime.ts`（`callBeforeRunHooks` 中预注入 reminder）

### 修复步骤建议

1. **新增 `_inject_completion_reminder` 方法**
   - 在 `AgentRuntime` 类中新增：
     ```python
     def _inject_completion_reminder(self, completing_tool: str) -> None:
         """在循环开始前注入 completion reminder"""
         reminder_text = (
             f"[System Reminder] 本任务必须以 `{completing_tool}` 工具结束。"
             f"请在完成所有准备工作后调用该工具提交结果。"
         )
         reminder_msg = create_text_message(MessageRole.SYSTEM, reminder_text)
         self._state.messages.append(reminder_msg)
         # 发射 message_added 事件让前端可见
     ```
   - 保留原有 reminder 逻辑（第一轮失败后仍会再次注入）

2. **`run()` 入口调用**
   - 在 `run()` 方法的 `callBeforeRunHooks` 之后、主循环之前：
     - 检查 `self._config.completion_policy.require_completion_tool`
     - 若为 True，查询 completing tool 名称（从 `self._tools` 中找 `lifecycle.completes_run=True` 的工具）
     - 调用 `_inject_completion_reminder(tool_name)`
   - 多个 completing tool 时取第一个（与 Cline 行为一致）

3. **reminder 不重复注入**
   - 用 `self._state.completion_reminder_injected: bool` 标记
   - 首次注入后置 True，后续 run 不再注入（除非 restore 重置）
   - `restore()` 方法中重置该标记为 False

4. **与现有 reminder 的协调**
   - 现有"第一轮失败后 reminder"逻辑保留（作为兜底）
   - 预注入是优化，失败后 reminder 是补救，两者不冲突
   - 失败后 reminder 文本改为："提醒：仍需调用 `<tool>` 完成（之前预注入已说明）"

### 验证方法

1. 配置 `require_completion_tool=True`，启动 run
2. 确认首轮消息列表中包含 system reminder
3. LLM 第一轮直接调用 completing tool，确认不再追加失败 reminder
4. LLM 第一轮未调用 completing tool，确认追加失败 reminder（兜底）
5. 同一会话第二次 run，确认预注入不再触发（标记生效）

### 注意事项

- reminder 是 system message，不参与 LLM 的 user/assistant 对话流
- 多轮 run 中只注入一次（避免消息堆积）
- 不修改 `completion_policy.require_completion_tool` 的语义

---

## 10.4 hook stop 状态分类（B33）

### 任务背景

来源 Phase B #B33。当前 `before_run` / `before_tool` hook 返回 `stop=True` 时，`AgentRuntime` 将 status 设为 `"failed"`，发射 `run_failed` 事件。问题：
- hook 主动 stop 是**受控停止**（如用户配置的拦截规则），不是失败
- 前端看到 "failed" 状态会显示错误，用户体验差
- 量化场景下，用户可能配置"实盘交易前必须人工确认" hook，触发 stop 是预期行为

Cline 的 `agent-runtime.ts` 中引入 `ControlledStopError`，hook stop 时抛该异常，主循环 catch 后 status 设为 `"completed"`（而非 `"failed"`），finish_reason 为 `"controlled_stop"`。

### 目标

区分 hook stop 与真实失败：
1. 新增 `ControlledStopError` 异常类
2. hook stop 时抛 `ControlledStopError`，主循环 catch 后 status="completed"
3. `finish_reason="controlled_stop"`，发射 `run_finished` 事件（非 `run_failed`）
4. 前端可区分显示"用户中止" / "hook 拦截" / "系统失败"

### 当前实现位置

- `agent/runtime.py`（`_prepare_tool_execution` 中 hook stop 处理、主循环异常捕获）
- `agent/types.py`（`AgentRunResult.status` 枚举）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/agents/src/agent-runtime.ts`（`ControlledStopError` 类、catch 分支）

### 修复步骤建议

1. **新增 `ControlledStopError` 异常**
   - 在 `agent/types.py` 中新增：
     ```python
     class ControlledStopError(Exception):
         """hook 主动 stop，非失败"""
         def __init__(self, reason: str, source: str = "hook"):
             self.reason = reason
             self.source = source  # "hook" / "policy" / "user"
             super().__init__(reason)
     ```
   - `source` 字段记录触发来源，便于前端展示

2. **hook stop 抛出 `ControlledStopError`**
   - 在 `agent/runtime.py::_prepare_tool_execution` 中：
     - 当 `BeforeToolResult.stop=True` 时，抛 `ControlledStopError(reason=before_result.reason, source="hook")`
     - 替代原有的 `RuntimeError` 抛出
   - 保留 `BeforeToolResult.policy` 字段语义不变

3. **主循环异常捕获区分**
   - 在 `run()` 方法的 try/except 中：
     ```python
     try:
         # 主循环
     except ControlledStopError as e:
         status = "completed"
         finish_reason = "controlled_stop"
         # 发射 run_finished 事件
     except RuntimeError as e:
         status = "failed"
         finish_reason = "error"
         # 发射 run_failed 事件
     ```
   - `ControlledStopError` 是 `RuntimeError` 的子类时需注意捕获顺序（先子类后父类）
   - 推荐 `ControlledStopError` 不继承 `RuntimeError`，避免捕获歧义

4. **`AgentRunResult` 扩展**
   - 增加 `finish_reason: str` 字段（已有则复用）
   - 取值：`"stop"` / `"tool_calls"` / `"max_iterations"` / `"aborted"` / `"error"` / `"controlled_stop"`
   - 前端根据 finish_reason 显示不同图标和文案

5. **前端事件处理**
   - `run_finished` 事件中携带 `finish_reason`，前端根据值显示：
     - `controlled_stop`：黄色图标 + "被规则拦截"
     - `stop`：绿色图标 + "正常完成"
     - `aborted`：灰色图标 + "用户中止"
     - `error`：红色图标 + "运行失败"
   - 保留现有事件处理逻辑，仅增加 case 分支

### 验证方法

1. 配置 `before_tool` hook 返回 `stop=True`
2. 触发工具调用，确认：
   - status="completed"（非 "failed"）
   - finish_reason="controlled_stop"
   - 发射 `run_finished` 事件（非 `run_failed`）
3. 前端确认显示"被规则拦截"图标
4. 真实异常（如 LLM API 错误），确认仍走 "failed" 路径（回归测试）

### 注意事项

- `ControlledStopError` 不继承 `RuntimeError`，避免与现有 `except RuntimeError` 冲突
- 不修改 `aborted` 路径（用户主动中止仍走 `aborted`，非 `controlled_stop`）
- 前端需同步更新事件处理逻辑（增加 `controlled_stop` case）

---

## 10.5 AgentToolContext.metadata 字段（A7）

### 任务背景

来源 Phase A #A7。当前 `AgentToolContext` 字段包括 `session_id` / `agent_id` / `run_id` / `iteration` / `signal` / `snapshot` / `emit_update` 等，但**无 `metadata` 字段**。

Cline 的 `AgentToolContext.metadata` 是一个 `Record<string, unknown>`，用于存储工具运行时的元数据（如触发来源、关联 checkpoint、用户偏好等），工具可读取该字段做行为决策。

量化场景下需求：
- 工具需要知道"本次调用是否由 checkpoint 触发"（决定是否记录到 checkpoint）
- 工具需要知道"用户是否启用了详细日志"（决定输出详尽程度）
- 工具需要知道"当前 run 的优先级"（决定是否走快速路径）

### 目标

为 `AgentToolContext` 增加 `metadata` 字段：
1. 字段类型 `dict[str, Any]`，默认空 dict
2. `AgentRuntime` 构造 context 时填充关键字段
3. 工具可通过 `context.metadata.get(key)` 读取

### 当前实现位置

- `agent/types.py`（`AgentToolContext` dataclass）
- `agent/runtime.py`（`_prepare_tool_execution` 中构造 context）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/agent.ts` L170-186（`AgentToolContext.metadata`）

### 修复步骤建议

1. **`AgentToolContext` 增加 `metadata` 字段**
   - 在 `agent/types.py` 的 `AgentToolContext` dataclass 中：
     ```python
     @dataclass
     class AgentToolContext:
         # 原有字段...
         session_id: str
         agent_id: str
         # ...
         metadata: dict[str, Any] = field(default_factory=dict)
     ```
   - 默认值用 `field(default_factory=dict)` 避免可变默认值陷阱
   - 保留原有字段顺序，新增字段在最后

2. **`AgentRuntime` 填充 metadata**
   - 在 `_prepare_tool_execution` 中构造 `AgentToolContext` 时：
     ```python
     metadata = {
         "run_id": self._current_run_id,
         "iteration": iteration,
         "trigger_source": "user",  # 或 "checkpoint" / "scheduler"
         "checkpoint_id": self._state.last_checkpoint_id,
         "verbose": self._config.verbose,
     }
     ctx = AgentToolContext(..., metadata=metadata)
     ```
   - 字段含义文档化在 `AgentToolContext.metadata` 的注释中

3. **metadata 字段标准化**
   - 在 `agent/types.py` 中定义常量：
     ```python
     AGENT_TOOL_METADATA_KEYS = {
         "run_id": "当前 run 的唯一 ID",
         "iteration": "当前迭代轮次",
         "trigger_source": "调用来源（user/checkpoint/scheduler）",
         "checkpoint_id": "关联的 checkpoint ID（若有）",
         "verbose": "是否启用详细日志",
     }
     ```
   - 工具按 key 读取，避免拼写错误

4. **工具读取示例**
   - 不修改现有工具，仅在需要时由工具开发者主动读取
   - 例如 `run_commands` 可读 `context.metadata.get("verbose")` 决定日志详细度
   - 例如 `editor` 可读 `context.metadata.get("checkpoint_id")` 决定是否记录修改

### 验证方法

1. 调用任意工具，在工具实现中打印 `context.metadata`
2. 确认包含 `run_id` / `iteration` / `trigger_source` 等字段
3. 字段值与当前 run 上下文一致
4. 现有工具不受影响（默认 metadata 不被读取）

### 注意事项

- metadata 是只读上下文，工具不应修改（仅 runtime 填充）
- 不强制工具读取 metadata，保持现有工具兼容
- metadata 不参与序列化（不写入会话 JSON）

---

## 10.6 AgentRuntimeConfig 缺失字段补全（A16）

### 任务背景

来源 Phase A #A16。当前 `AgentRuntimeConfig` 字段包括 `model` / `max_iterations` / `completion_policy` / `tools` / `hooks` / `signal` 等核心字段，但**缺失**：
- `initial_messages: list[AgentMessage]`（初始化消息，如系统预设上下文）
- `plugins: list[Any]`（插件列表，预留）
- `logger: Logger`（自定义 logger）
- `telemetry: TelemetryService`（遥测服务注入）

Cline 的 `AgentRuntimeConfig` 含上述字段，便于上层灵活配置。当前我的实现中这些字段散落在 `AgentRuntime.__init__` 参数或全局变量中，未统一管理。

### 目标

为 `AgentRuntimeConfig` 补齐缺失字段：
1. 增加 `initial_messages` / `plugins` / `logger` / `telemetry` 字段
2. 所有字段有合理默认值（向后兼容）
3. `AgentRuntime.__init__` 优先使用 config 中的字段

### 当前实现位置

- `agent/types.py`（`AgentRuntimeConfig` dataclass）
- `agent/runtime.py`（`AgentRuntime.__init__`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/agent.ts`（`AgentRuntimeConfig` 接口）

### 修复步骤建议

1. **`AgentRuntimeConfig` 增加字段**
   - 在 `agent/types.py` 的 `AgentRuntimeConfig` 中：
     ```python
     @dataclass
     class AgentRuntimeConfig:
         # 原有字段...
         model: str
         max_iterations: int = 50
         # ...
         initial_messages: list[AgentMessage] = field(default_factory=list)
         plugins: list[Any] = field(default_factory=list)
         logger: Logger | None = None  # None 时用模块级 logger
         telemetry: TelemetryService | None = None  # None 时不收集遥测
     ```
   - 默认值用 `field(default_factory=list)` 避免可变默认值
   - `logger` / `telemetry` 用 `Optional`，None 时走原逻辑

2. **`AgentRuntime.__init__` 接入新字段**
   - 优先从 `config` 读取：
     ```python
     self._logger = config.logger or logger
     self._telemetry = config.telemetry  # None 时跳过遥测调用
     self._initial_messages = list(config.initial_messages)  # 复制避免外部修改
     ```
   - 保留原有 `logger` 模块级引用作为兜底
   - `initial_messages` 在 `run()` 入口追加到 `self._state.messages`

3. **`initial_messages` 处理**
   - 在 `run()` 方法的 `callBeforeRunHooks` 之前：
     - 若 `self._state.messages` 为空且 `self._initial_messages` 非空，追加到 messages
     - 仅首次 run 注入（后续 run 不重复）
   - 用 `self._initial_messages_injected: bool` 标记
   - `restore()` 时重置该标记为 False（允许新会话重新注入）

4. **`telemetry` 字段使用**
   - 在 `agent/runtime.py` 中所有遥测调用前判断：
     ```python
     if self._telemetry:
         self._telemetry.record_event(...)
     ```
   - 保留原有 `agent.telemetry` 模块级引用作为兜底（若 config.telemetry 为 None）
   - 不修改现有遥测调用点，仅增加 `if self._telemetry` 守卫

5. **`plugins` 字段预留**
   - 当前不实现 plugin 加载逻辑（Stage 8 已确认 Y 阶段不实施）
   - 仅在 config 中保留字段，未来扩展时使用
   - `AgentRuntime.__init__` 中存储但不处理：`self._plugins = list(config.plugins)`

6. **`logger` 字段使用**
   - `AgentRuntime` 内所有 `logger.info(...)` 改为 `self._logger.info(...)`
   - 默认值 `self._logger = config.logger or logger`（模块级 logger）
   - 上层可注入自定义 logger 实现日志聚合

### 验证方法

1. 不传新字段，确认现有行为不变（向后兼容）
2. 传入 `initial_messages=[...]`，确认首次 run 时消息被注入
3. 第二次 run，确认 initial_messages 不重复注入
4. 注入自定义 `logger`，确认日志走自定义 logger
5. 注入 `telemetry=None`，确认遥测调用被跳过

### 注意事项

- `initial_messages` 仅在 messages 为空时注入，避免污染已有会话
- `telemetry` 字段为 None 时跳过遥测，不等价于 `opt_out`（opt_out 是用户选择，None 是未配置）
- `plugins` 字段预留但不处理，避免引入未实现逻辑

---

## 11. 阶段汇总

### 11.1 完成判据

- 10.1：`ToolCallPart.metadata` 包含 provider 元数据
- 10.2：finish 后的 reasoning content 被正确识别
- 10.3：首轮 LLM 即看到 completion reminder
- 10.4：hook stop 状态为 "completed"（非 "failed"）
- 10.5：工具可读取 `context.metadata` 上下文
- 10.6：`AgentRuntimeConfig` 字段完整，向后兼容

### 11.2 风险与回滚

- 10.1 / 10.2 涉及流式处理，需充分回归测试
- 10.4 异常类型变更需同步前端，否则状态显示错乱
- 10.6 字段补全向后兼容，风险低

### 11.3 后续衔接

- 10.1 完成后，Stage 11 的 J13（CompactionStateManager）可基于 metadata 扩展
- 10.4 完成后，Stage 12 的 P11（HookError）可基于 ControlledStopError 扩展
- 10.6 完成后，Stage 13 的 R5（capabilities 透传）可基于 config 字段扩展

---

**Stage 10 结束。建议按 10.6 → 10.5 → 10.4 → 10.3 → 10.1 → 10.2 顺序执行，完成后进入 Stage 11。**
