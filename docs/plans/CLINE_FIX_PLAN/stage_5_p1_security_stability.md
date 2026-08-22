# Stage 5: P1 安全与稳定性方案

> 生成时间：2026-07-26
> 优先级：P1
> 预估工作量：1.5 周
> 依赖：stage_2（核心架构对齐，BeforeToolResult / AgentMessage / hooks 基础设施）
>
> 来源：
> - `CLINE_DIFF/phase_M_loop_mistake.md`（M3 / M4 / M10）
> - `CLINE_DIFF/phase_P_file_hooks.md`（P4 / P8 / P16 / P18）
> - `CLINE_DIFF/phase_U_approval.md`（U2 / U10）
> - `CLINE_DIFF/phase_Z_telemetry_hub.md`（Z13）
>
> 涉及源文件：
> - 我的：`agent/loop_detection.py`、`agent/mistake_tracker.py`、`agent/file_hooks/runner.py`、`agent/file_hooks/integration.py`、`agent/file_hooks/types.py`、`agent/approval.py`、`agent/approval_policy.py`、`agent/telemetry.py`、`agent/runtime.py`、`agent/hooks.py`
> - Cline：`sdk/packages/core/src/runtime/safety/loop-detection.ts`、`sdk/packages/core/src/runtime/safety/mistake-tracker.ts`、`sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`、`apps/vscode/src/core/hooks/hook-factory.ts`、`sdk/packages/core/src/runtime/tools/tool-approval.ts`、`sdk/packages/shared/src/llms/tools.ts`、`sdk/packages/agents/src/agent-runtime.ts`、`sdk/packages/core/src/services/telemetry/OpenTelemetryProvider.ts`、`sdk/packages/core/src/services/global-settings.ts`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 5.1 | 循环检测软阈值注入 LLM 上下文 | M3 | P1 | agent/runtime.py |
| 5.2 | 循环检测硬阈值联动 MistakeTracker | M4 | P1 | agent/runtime.py、agent/mistake_tracker.py |
| 5.3 | 文件 Hooks blocking 默认值对齐 fail-open | P4 / P18 | P1 | agent/file_hooks/types.py、agent/file_hooks/runner.py、agent/file_hooks/integration.py |
| 5.4 | 文件 Hooks 退出码语义对齐 JSON cancel | P8 | P1 | agent/file_hooks/runner.py |
| 5.5 | 文件 Hooks 并发模型评估并行化 | P16 | P2 | agent/file_hooks/integration.py |
| 5.6 | 审批记忆会话级持久化 | U10 | P1 | agent/approval.py、agent/runtime.py |
| 5.7 | 审批 toolPolicies 三态语义 | U2 | P2 | agent/approval_policy.py、agent/runtime.py、agent/types.py |
| 5.8 | telemetry 隐私合规 opt-out + PII 脱敏 | Z13 | P1 | agent/telemetry.py |

依赖关系：
- 5.1 与 5.2 同处 `_loop_detection_hook`，建议一并实施，避免对同一函数反复修改
- 5.3 / 5.4 / 5.5 同处文件 hooks 子系统，可并行评估，但 5.3 改默认值后需复测 5.4 的 error 分支
- 5.6 与 5.7 同处审批流程，5.7 实现 `autoApprove` 字段后，5.6 的"始终允许"可复用该字段写入会话级策略
- 5.8 完全独立，可并行

---

## 5.1 循环检测软阈值注入 LLM 上下文（M3）

### 任务背景

来源 Phase M #M3。Cline 的循环检测软阈值触发时，将 `verdict.message`（形如 `"Detected N consecutive identical calls to \`tool_name\`; consider trying a different approach."`）作为 user 消息追加到 conversation，让 LLM 在下一轮看到该提示并自纠错，工具调用本身不阻止。

我的实现 `agent/runtime.py:1038-1043` 中软阈值仅写 `logger.warning`，不注入 LLM 上下文。LLM 看不到该提示，无法据此自纠错，必须达到硬阈值（5 次）才会被强行中止，浪费 2 轮 API 调用与 token。在量化场景下，若 LLM 卡在某个数据查询循环，会多消耗 2 轮 LLM 请求。

### 目标

对齐 Cline `inspectLoopForToolCall` 的 soft 分支语义：将 `verdict.message` 作为 user 消息追加到 `self._state.messages`，并发射 `message_added` 事件让前端可见，使 LLM 在下一轮看到"建议换思路"提示后主动改变策略。

### 当前实现位置

- `agent/runtime.py:1019-1044`（`_loop_detection_hook` 方法）
- `agent/runtime.py:1038-1043`（soft 分支：仅 `logger.warning`）
- `agent/loop_detection.py:88-95`（`LoopDetectionVerdict` soft 消息生成）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts:1256-1263`
  - L1256-1258：`if (verdict.kind === "soft") { if (verdict.message) {`
  - L1258-1261：`this.conversation.appendMessage({ role: "user", content: [{ type: "text", text: verdict.message }] })`
  - L1263：`return`（不阻止工具执行）

### 修复步骤建议

1. **在 `_loop_detection_hook` 的 soft 分支追加 user 消息**
   - 保留原 `logger.warning` 日志（不删除原逻辑）
   - 在日志之后增加：若 `verdict.message` 非空，调用 `create_text_message(MessageRole.USER, verdict.message)` 构造 user 消息
   - 追加到 `self._state.messages`
   - 通过 `await self._emit(make_message_added(self.snapshot(), notice_msg))` 发射事件让前端可见
   - 最后 `return None`（不阻止工具执行，与原行为一致）

2. **复用已有的 `create_text_message` / `make_message_added` 符号**
   - `agent/runtime.py:70` 已 import `make_message_added`
   - `agent/types.py:442` 提供 `create_text_message(role, text)`
   - `agent/types.py:26-30` 定义 `MessageRole.USER = "user"`
   - 无需新增 import（`create_text_message` 在 `runtime.py` 内已使用，见 `_check_repeated_tool_failures` L1094）

3. **参考 MistakeTracker 的 guidance 注入逻辑**
   - `agent/runtime.py:1092-1095` 中 `continue_with_guidance` 分支已实现"把 guidance 作为 user message 注入"的等价逻辑，可作为同文件内参考
   - 注意：MistakeTracker 的 guidance 注入不 emit 事件，本任务需 emit `message_added` 让前端可见，因为软阈值提示用户也应看到

### 验证方法

1. 单元测试：构造一个连续 3 次以相同参数调用同一工具的场景
2. 检查第 3 次调用后 `self._state.messages` 末尾应新增一条 `role="user"` 的文本消息，内容包含 `"Detected 3 consecutive identical calls"`
3. 检查 `_emit` 被调用一次，事件类型为 `message_added`
4. 检查工具调用本身未被阻止（`_loop_detection_hook` 返回 `None`，工具正常执行）
5. 第 4、5 次相同调用应继续累积计数，第 5 次触发硬阈值
6. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`_loop_detection_hook` 当前是同步函数（返回 `BeforeToolResult | None`，非 async），若要 `await self._emit(...)` 需确认 hook 调用机制。实际上 `agent/runtime.py:1163-1170` 中 `before_tool` hooks 通过 `self._call_hook(hook, ctx)` 调用，`_call_hook` 支持同步和异步 hook（见 hooks.py L259-268 的 `Union[..., Awaitable[...]]` 类型签名）。因此需将 `_loop_detection_hook` 改为 `async def`，与 `_request_tool_approval` 等已有 async hook 一致
- 保留原 `logger.warning` 逻辑（不删除），在其基础上追加注入逻辑
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`verdict.message` 为 None 时跳过注入（与 Cline `if (verdict.message)` 一致）
- 软阈值不阻止工具执行（`return None`），与原行为一致；仅追加提示消息

---

## 5.2 循环检测硬阈值联动 MistakeTracker（M4）

### 任务背景

来源 Phase M #M4。Cline 的循环检测硬阈值不直接 abort，而是用 `forceAtLimit: true` 触发 MistakeTracker 立即达到 `maxConsecutiveMistakes`，再由 MistakeTracker 的 `outcome.action === "stop"` 触发 `activeRuntime.abort()`。这一路径会让 `finishReason` 变为 `"aborted"`，并走 MistakeTracker 的 `onLimitReached` 回调（用户可决策 "Try a different approach" 还是 "Stop"）。

我的实现 `agent/runtime.py:1033-1037` 中硬阈值直接返回 `BeforeToolResult(stop=True)`，由 `_prepare_tool_execution` 抛 `RuntimeError`（`runtime.py:1178-1179`），主循环 catch 后 status 设为 `"failed"`（因 `_aborted` 未设为 True）。语义不等价：Cline 视循环硬阈值为"可恢复的 abort"，我视为"硬失败"。且我未联动 MistakeTracker：硬阈值未触发 MistakeTracker 的 `forceAt_limit` 路径，两个 tracker 各自为政。

### 目标

对齐 Cline 的硬阈值联动路径：给 `MistakeTracker.record` 增加 `force_at_limit: bool = False` 参数（对标 Cline `RecordMistakeInput.forceAtLimit`），硬阈值时调用 `self._mistake_tracker.record(..., force_at_limit=True)`，由 MistakeTracker 的 `outcome.action == "stop"` 决定是否 abort。统一 abort 路径，避免两个 tracker 各自为政，同时让 status 一致为 `"aborted"`（关联 M10 修复）。

### 当前实现位置

- `agent/runtime.py:1019-1044`（`_loop_detection_hook` 方法）
- `agent/runtime.py:1033-1037`（hard 分支：直接 `BeforeToolResult(stop=True)`）
- `agent/mistake_tracker.py:155-196`（`record` 方法，无 `force_at_limit` 参数）
- `agent/mistake_tracker.py:180-184`（硬阈值判断：`self._total >= self.config.max_total`）
- `agent/runtime.py:1084-1091`（`_check_repeated_tool_failures` 中 MistakeTracker 调用与 abort 分支）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts:1265-1308`
  - L1265-1273：hard 分支调用 `this.enqueueMistakeRecord({ iteration, reason: "tool_execution_failed", forceAtLimit: true, details: verdict.message })`
  - L1287-1310：`enqueueMistakeRecord` 内部 `await this.mistakeTracker.record(input)`，若 `outcome.action === "stop"` 则 `this.activeRuntime?.abort(outcome.reason ?? outcome.message)`
- Cline `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts:88-150`
  - L49：`forceAtLimit?: boolean` 字段定义
  - L90：`const next = input.forceAtLimit && max ? max : this.consecutiveMistakes + 1`
  - L138-149：`outcome.action === "stop"` 时返回 `{ action: "stop", reason, message: buildMistakeLimitStopMessage(...) }`

### 修复步骤建议

1. **扩展 `MistakeTracker.record` 方法签名**
   - 在 `agent/mistake_tracker.py:155-161` 的 `record` 方法参数列表末尾增加 `force_at_limit: bool = False`
   - 保留原 `iteration / mistake_type / tool_name / details` 参数不变
   - 在 `agent/mistake_tracker.py:173-174` 的计数逻辑前增加：若 `force_at_limit` 为 True，直接将 `self._total` 设为 `self.config.max_total`（对标 Cline L90 `next = input.forceAtLimit && max ? max : ...`），并仍记录到 `_history`；否则保持原 `self._counts[mistake_type] += 1` 与 `self._total += 1` 逻辑
   - 后续硬阈值判断 `self._total >= self.config.max_total` 不变（force_at_limit 后必然满足）

2. **修改 `_loop_detection_hook` 的 hard 分支**
   - 在 `agent/runtime.py:1033-1037` 的 hard 分支中，不再直接返回 `BeforeToolResult(stop=True)`
   - 改为：调用 `self._mistake_tracker.record(iteration=self._state.iteration, mistake_type=MistakeType.EXEC_ERROR, tool_name=ctx.tool_call.tool_name, details=verdict.message or "", force_at_limit=True)`
   - 检查 `outcome.action`：
     - 若为 `"stop"`：调用 `self.abort(outcome.message or "Loop detection hard limit reached")`（对标 Cline L1307 `activeRuntime.abort`），然后返回 `BeforeToolResult(stop=True, reason=outcome.message)` —— 这样主循环 catch RuntimeError 后因 `_aborted=True` 会设 status="aborted"（关联 M10）
     - 若为 `"continue_with_guidance"`：把 `outcome.guidance` 作为 user 消息注入（复用 5.1 的注入逻辑），返回 `None`（不阻止工具执行，让 LLM 看到提示自纠错）
     - 若为 `"continue"`：返回 `None`（理论上 force_at_limit 后不会走到此分支，但保留兜底）

3. **保留原 `_check_repeated_tool_failures` 中的 MistakeTracker 调用**
   - `agent/runtime.py:1084-1091` 的逻辑不动（错误失败场景的 MistakeTracker 调用，不传 `force_at_limit`）
   - 仅修改 `outcome.action == "stop"` 分支：将 `raise RuntimeError(outcome.message)` 改为先 `self.abort(outcome.message)` 再 `raise RuntimeError(self._abort_reason)`，使 status 一致为 `"aborted"`（对标 M10 修复建议）

4. **import `MistakeType`**
   - `agent/runtime.py` 顶部确认 import `from agent.mistake_tracker import MistakeTracker, MistakeType, classify_mistake`（已有 `classify_mistake` 和 `MistakeTracker` 的 import，需补 `MistakeType`）

### 验证方法

1. 单元测试：构造连续 5 次以相同参数调用同一工具的场景
2. 第 5 次调用时检查：
   - `MistakeTracker.record` 被调用，参数含 `force_at_limit=True`
   - `MistakeTracker._total` 立即等于 `max_total`（而非 +1 递增）
   - `self.abort()` 被调用，`self._aborted` 为 True
   - 最终 `AgentRunResult.status == "aborted"`（而非 `"failed"`）
3. 构造 `max_total` 配置为 10 的场景，验证硬阈值触发后 MistakeTracker 的 stop 消息含 `consecutive=10/max=10` 字样
4. 验证 `_check_repeated_tool_failures` 的 RuntimeError 分支也走 `self.abort()`，status 为 `"aborted"`
5. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`_loop_detection_hook` 当前是同步函数，改为 async 后需确认 `_call_hook` 支持（支持，见 hooks.py L259-268）。同时 5.1 也需改为 async，建议合并实施
- 保留原函数逻辑：`_loop_detection_hook` 的 ok 分支 `return None` 不变；hard 分支原 `BeforeToolResult(stop=True)` 逻辑保留但作为 `outcome.action == "stop"` 的子分支
- `MistakeTracker.record` 的原计数逻辑（`self._counts[mistake_type] += 1` / `self._total += 1`）保留，仅在 `force_at_limit=True` 时跳过递增直接设为 max
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`outcome.action` 为 `"continue"` 时返回 `None` 是合理兜底，不算 fallback
- 关联 M10：本任务将 mistake limit 的 status 从 `"failed"` 改为 `"aborted"`，是对 M10 的同步修复

---

## 5.3 文件 Hooks blocking 默认值对齐 fail-open（P4 / P18）

### 任务背景

来源 Phase P #P4 与 #P18。Cline 的文件 hooks 采用 fail-open 语义（`hook-factory.ts:268-272` 注释明确："Treats hooks as 'fail-open': only shouldContinue:false blocks tool execution"），脚本执行错误（非零退出）不阻止工具执行，只有 hook 显式返回 JSON `{cancel: true}` 才阻止主流程。

我的实现 `agent/file_hooks/types.py:99` 中 `blocking: bool = True`（默认阻塞），`agent/file_hooks/runner.py:120,164` 中 `action = "block" if config.blocking else "error"`，`agent/file_hooks/integration.py:153-161` 中 `if config.blocking: return "block", result.reason`。默认行为与 Cline 相反：脚本崩溃时工具被阻止。

影响：量化场景下脚本崩溃可能掩盖真实问题，fail-closed 表面更安全，但与 Cline 行为不一致；用户若同时使用 Cline 和本系统，行为预期会不一致；且 fail-closed 会导致 hook 脚本自身的 bug（如语法错误）阻断主流程，影响可用性。

### 目标

对齐 Cline fail-open 语义：将 `FileHookConfig.blocking` 默认值从 `True` 改为 `False`。保留 `blocking` 字段作为额外增强，允许用户在 frontmatter 显式开启 fail-closed（如对安全审计脚本设 `blocking: true`）。

### 当前实现位置

- `agent/file_hooks/types.py:99`（`blocking: bool = True`）
- `agent/file_hooks/runner.py:120`（超时分支：`action = "error" if not config.blocking else "block"`）
- `agent/file_hooks/runner.py:164`（其他错误码分支：`action = "block" if config.blocking else "error"`）
- `agent/file_hooks/runner.py:182`（异常分支：`action = "error" if not config.blocking else "block"`）
- `agent/file_hooks/integration.py:153-161`（`if config.blocking: return "block", result.reason`）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts:268-272`
  - L268-270：注释 "Error handling: Treats hooks as 'fail-open': only shouldContinue:false blocks tool execution"
  - L270：注释 "Hook script errors (non-zero exit) don't block tools, only explicit JSON response does"
- Cline `third_party/cline/sdk/packages/core/src/hooks/subprocess.ts:425-428`（SDK 端 `beforeTool` 失败时返回 undefined，继续执行工具）

### 修复步骤建议

1. **修改 `FileHookConfig.blocking` 默认值**
   - `agent/file_hooks/types.py:99` 将 `blocking: bool = True` 改为 `blocking: bool = False`
   - 同步修改 `agent/file_hooks/types.py:25-27` 的 frontmatter 文档注释（将"是否阻塞主流程（true 时 block 会中止工具执行）"改为"是否阻塞主流程（默认 False 与 Cline fail-open 对齐；true 时脚本错误也会中止工具执行）"）
   - 同步修改 `agent/file_hooks/types.py:93` 的 `Attributes` 文档

2. **保留 `runner.py` 与 `integration.py` 的 blocking 判断逻辑**
   - `agent/file_hooks/runner.py:120,164,182` 的 `action = "block" if config.blocking else "error"` 不变（逻辑正确，只是默认值翻转后多数场景走 error 分支）
   - `agent/file_hooks/integration.py:153-161` 的 `if config.blocking: return "block", result.reason` 不变
   - 这两处读取的是 `config.blocking` 字段值，默认值改了它们自动跟随

3. **更新 frontmatter 解析的默认值**
   - `agent/file_hooks/loader.py` 中解析 frontmatter 的 `blocking` 字段时，若用户未显式指定，使用 `FileHookConfig` 的默认值 `False`（dataclass 默认值机制自动处理，无需改 loader 代码，但需确认 loader 未硬编码 `True`）

4. **更新文档与注释**
   - `agent/file_hooks/types.py:9-22` 的模块 docstring 中"退出码协议"部分，补充说明"blocking=False 时脚本错误不阻止主流程（fail-open，与 Cline 对齐）"
   - `agent/file_hooks/runner.py:9-12` 的模块 docstring 同步更新

### 验证方法

1. 单元测试：构造一个退出码为 2 的 hook 脚本，不显式设置 `blocking`
2. 检查 `FileHookConfig.blocking` 默认为 `False`
3. 检查 `run_hook` 返回 `action="error"`（而非 `"block"`）
4. 检查 `_run_hooks_of_type` 走 `logger.warning` 分支，不返回 `"block"`，主流程继续
5. 构造 frontmatter 显式 `blocking: true` 的脚本，退出码 2，检查 `action="block"`（显式开启 fail-closed 仍生效）
6. 运行 `python tests/test_agent_e2e.py` 与 `python test_phase23_hooks.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`loader.py` 中 frontmatter 解析是否硬编码 `blocking` 默认值，需先 Read 确认
- 保留原函数逻辑：`runner.py` 与 `integration.py` 的 blocking 判断分支不动，仅默认值翻转
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback
- 量化场景评估：若用户依赖 fail-closed 行为（如安全审计脚本），需在 frontmatter 显式 `blocking: true`，文档应明确提示此变更
- 与 5.4（退出码语义）有交互：5.4 实施 block 仅由 JSON cancel 决定后，exit code 2 不再走 block 分支，blocking 字段仅影响 exit code 非 0 且无 JSON 时的行为

---

## 5.4 文件 Hooks 退出码语义对齐 JSON cancel（P8）

### 任务背景

来源 Phase P #P8。Cline 的 hook 协议中退出码不决定 continue/block，只有 stdout JSON 的 `cancel: true` 字段才决定 block（`hook-factory.ts:452-529`）。具体语义：
- exit code 0 + 有效 JSON → 按 JSON 的 `cancel` 字段决定
- exit code 0 + 无 JSON → continue
- exit code 非 0 + 有效 JSON → 仍按 JSON 决定（L454-499 注释 "If we have valid JSON, honor it regardless of exit code"）
- exit code 非 0 + 无 JSON → throw HookExecutionError（caller 决定是否阻止，结合 5.3 fail-open 默认不阻止）

我的实现 `agent/file_hooks/runner.py:130-169` 中退出码直接决定 action：exit code 0 → continue；exit code 1 → block（stderr 作为 reason）；其他 → error（若 blocking=true 则 block）。跨系统迁移 hook 脚本时行为不一致：Cline hook 脚本（用 `exit 1` 表示阻止）在本系统会 block，但 Cline 自身 `exit 1` 不阻止；反之亦然。

### 目标

对齐 Cline 的退出码语义：block 仅由 stdout JSON 的 `cancel: true` 字段决定，退出码仅表示执行成功/失败。具体规则：
- 任何退出码 + 有效 JSON 含 `cancel: true` → block
- 任何退出码 + 有效 JSON 不含 `cancel: true` → continue（解析 context_injection）
- exit code 0 + 无 JSON → continue
- exit code 非 0 + 无 JSON → error（结合 5.3 fail-open 默认不阻止）

保留对原 `exit code 1 = block` 协议的兼容性，作为本系统的额外增强（非 Cline 协议），但需在文档中标注差异。

### 当前实现位置

- `agent/file_hooks/runner.py:130-169`（退出码分支解析）
- `agent/file_hooks/runner.py:130-146`（exit code 0 分支：仅解析 context_injection，不检查 cancel）
- `agent/file_hooks/runner.py:147-155`（exit code 1 分支：直接 block）
- `agent/file_hooks/runner.py:156-169`（其他退出码分支：error 或 block）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts:452-529`
  - L454-499：`if (parsedOutput) { ... return parsedOutput }`（有有效 JSON 时按 JSON 决定，无视退出码）
  - L503-527：`if (exitCode === 0) { return HookOutput.create({ cancel: false }) }`（exit 0 无 JSON → continue）
  - L529：`throw HookExecutionError.execution(...)`（exit 非 0 无 JSON → 抛错）
- Cline `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts:668`（`cancel = results.some(result => result.cancel === true)`）

### 修复步骤建议

1. **重构 `run_hook` 的结果解析逻辑**
   - 在 `agent/file_hooks/runner.py:125-128` 获取 `exit_code / stdout_text / stderr_text` 后，先尝试解析 stdout JSON
   - 抽取一个 `_parse_stdout_json(stdout_text) -> dict | None` 辅助函数（尝试 `json.loads`，失败返回 None）
   - 将原 L130-169 的三分支重构为：
     - 若 stdout_json 非 None 且为 dict：
       - 检查 `stdout_json.get("cancel") is True` 或 `stdout_json.get("cancel") is True` 或兼容字段 `stdout_json.get("block") is True` → 返回 `action="block"`，reason 取 `stdout_json.get("reason")` 或 stderr_text
       - 否则 → 返回 `action="continue"`，context_injection 取 `stdout_json.get("context_injection")` 或 `stdout_json.get("contextModification")`（兼容 Cline 字段名）
     - 若 stdout_json 为 None：
       - exit code 0 → `action="continue"`（无 context_injection）
       - exit code 1 → 保留原兼容逻辑 `action="block"`（本系统额外增强，reason 取 stderr_text），但日志标注"非 Cline 协议，建议改用 JSON cancel:true"
       - 其他 exit code → `action = "block" if config.blocking else "error"`（保留原逻辑）

2. **支持 Cline 字段名 `contextModification`**
   - 在解析 stdout JSON 时，除 `context_injection` 外，也检查 `contextModification` 字段（Cline 字段名），取非空值作为 context_injection
   - 这是向 Cline 协议对齐的关键步骤，使本系统可运行 Cline 格式的 hook 脚本

3. **更新 stdout JSON 输出协议文档**
   - `agent/file_hooks/types.py:34-35` 的 docstring 中 stdout JSON 格式说明，补充 `cancel` 与 `contextModification` 字段
   - `agent/file_hooks/runner.py:9-22` 的模块 docstring 同步更新

4. **保留原 exit code 1 = block 兼容**
   - 不删除原 exit code 1 分支，作为本系统额外增强（已有用户可能依赖此协议）
   - 但优先级低于 JSON cancel：若 stdout 同时有 JSON `cancel: false`，则以 JSON 为准（continue）
   - 即：exit code 1 + 无 JSON → block（兼容）；exit code 1 + JSON cancel:false → continue（Cline 语义）

### 验证方法

1. 单元测试：构造 4 类脚本：
   - 脚本 A：exit 0 + stdout `{"cancel": true}` → 期望 `action="block"`
   - 脚本 B：exit 1 + stdout `{"cancel": false}` → 期望 `action="continue"`（JSON 优先于退出码）
   - 脚本 C：exit 0 + stdout `{"contextModification": "提示文本"}` → 期望 `action="continue"`，context_injection="提示文本"
   - 脚本 D：exit 1 + 无 JSON → 期望 `action="block"`（兼容本系统原协议）
2. 检查脚本 B 验证 JSON 优先于退出码
3. 检查脚本 C 验证 Cline 字段名 `contextModification` 被正确解析
4. 运行 `python test_phase23_hooks.py` 验证不破坏现有 hook 脚本

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：原 exit code 1 分支是否有用户依赖，需评估兼容性风险
- 保留原函数逻辑：原 exit code 0 分支的 `context_injection` 解析逻辑保留，仅扩展为同时检查 `cancel` 与 `contextModification` 字段
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：stdout JSON 解析失败时按无 JSON 处理（exit 0 → continue，exit 非 0 → error/block），符合 Cline 语义
- 与 5.3（blocking 默认值）有交互：5.3 改为 fail-open 后，exit 非 0 + 无 JSON 走 error 分支不阻止主流程
- 字段名兼容：`context_injection`（本系统原字段）与 `contextModification`（Cline 字段）并存，取值优先级建议 `contextModification` > `context_injection`（向 Cline 对齐）

---

## 5.5 文件 Hooks 并发模型评估并行化（P16）

### 任务背景

来源 Phase P #P16。Cline 的 `CombinedHookRunner`（`hook-factory.ts:651-684`）使用 `Promise.all` 并行执行所有同类型 hook，结果合并规则：任一 `cancel=true` 则最终 `cancel=true`，`contextModification` 用 `\n\n` 连接，`errorMessage` 用 `\n` 连接，所有 hook 都会执行完（即使某个 cancel）。

我的实现 `agent/file_hooks/integration.py:111-165` 中 `_run_hooks_of_type` 用 `for` 循环 `await` 串行执行，遇到 `block` 立即返回，后续 hook 不执行。多 hook 场景下延迟叠加，且遇 block 短路语义不同：我的 block 后续 hook 不执行，可能遗漏日志/审计。

### 目标

评估将 `_run_hooks_of_type` 改为 `asyncio.gather` 并行执行，统一合并语义：任一 block 则最终 block，但所有 hook 都执行完（不短路）。若评估后发现量化场景 hook 数量少（通常 1-2 个）且串行已够用，可记录评估结论暂不实施。

### 当前实现位置

- `agent/file_hooks/integration.py:111-165`（`_run_hooks_of_type` 函数）
- `agent/file_hooks/integration.py:132`（`for config in configs:` 串行循环）
- `agent/file_hooks/integration.py:144-151`（`if result.action == "block": return "block", result.reason` 短路返回）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/hooks/hook-factory.ts:651-684`（`CombinedHookRunner`）
  - L661：`const results = await Promise.all(this.runners.map((runner) => runner[exec](input)))`
  - L668：`const cancel = results.some((result) => result.cancel === true)`
  - L669-672：`contextModification` 用 `\n\n` 连接
  - L673-676：`errorMessage` 用 `\n` 连接

### 修复步骤建议

1. **评估量化场景 hook 数量**
   - Read `agent_config/hooks/` 目录（若存在）统计当前 hook 脚本数量
   - 若每个类型通常仅 1 个 hook，并行化无性能收益，可暂不实施
   - 若存在多 hook 场景（如 PreToolUse 有 2+ 脚本），则实施并行化

2. **若实施并行化，重构 `_run_hooks_of_type`**
   - 保留原函数签名与返回值结构（`tuple[str, str]`）
   - 将 `for config in configs` 改为 `asyncio.gather(*[run_hook(cfg, context) for cfg in configs], return_exceptions=True)`
   - 注意 `apply_to` 过滤需在 gather 前完成：先 `filtered_configs = [c for c in configs if tool_name is None or c.applies_to_tool(tool_name)]`
   - 收集所有结果后合并：
     - 若任一 `result.action == "block"` → 最终 action="block"，reason 取第一个 block 的 reason（或合并所有 block reason）
     - 若任一 `result.action == "error"` 且 `config.blocking` → 最终 action="block"
     - 否则 → action="continue"，injections 用 `\n\n` 连接
   - 异常处理：`return_exceptions=True` 后逐个检查，`Exception` 实例按 error 处理

3. **保留原串行逻辑作为兼容选项（可选）**
   - 增加 `_run_hooks_of_type_parallel` 与 `_run_hooks_of_type_serial` 两个实现
   - 通过环境变量 `AGENT_HOOK_PARALLEL` 控制（默认并行，对标 Cline）

4. **更新日志**
   - 并行执行后，日志需包含所有 hook 的执行结果（而非仅第一个 block 的）
   - 每个 hook 的执行时间分别记录

### 验证方法

1. 单元测试：构造 3 个 PreToolUse hook 脚本（A continue + B block + C continue）
2. 串行模式（旧）：仅 A 执行后 B block 立即返回，C 不执行
3. 并行模式（新）：A/B/C 都执行，最终 action="block"，日志含 A/B/C 三条记录
4. 检查 `context_injection` 合并：A 和 C 的 injection 用 `\n\n` 连接（B 的 block 不含 injection）
5. 性能测试：3 个各 sleep 1 秒的 hook，串行需 3 秒，并行应约 1 秒
6. 运行 `python test_phase23_hooks.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：先评估 `agent_config/hooks/` 实际 hook 数量，若仅 1 个则暂不实施
- 保留原函数逻辑：串行实现保留作为兼容，并行实现新增
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback
- 并行化后 hook 执行顺序不确定，若用户 hook 有顺序依赖（如 A 必须先于 B），需文档提示
- 量化场景评估：量化系统的 hook 多为安全审计类，通常无顺序依赖，并行化安全
- 优先级 P2：若评估后决定暂不实施，需在本任务结论中记录"评估完成，量化场景 hook 数量少，暂不并行化"

---

## 5.6 审批记忆会话级持久化（U10）

### 任务背景

来源 Phase U #U10。Cline 的审批记忆支持三层粒度：
- 全局 `autoApproveAllRef`（`approvals.ts:21-23`）任务运行中可热切换
- 类别级 `AutoApprovalSettings.actions`（5 类：readFiles/editFiles/executeSafeCommands/useBrowser/useMcp）持久化到工作区状态
- 单工具级 `McpHub.toggleToolAutoApprove`（`McpHub.ts:1534`）按 MCP 工具记忆，写入 `mcp_settings.json`

我的实现 `agent/approval.py` 完全无持久化审批记忆，`AGENT_AUTO_APPROVAL` 环境变量三档（off/readonly/all）仅启动时读取，不可运行时切换。`AutoApprovalPolicy` 的决策基于工具名 + 命令模式匹配，不记忆用户决策。每次审批都是一次性的：用户批准 `editor` 后，下次 `editor` 调用仍需重新审批。

生产 UX 差：每次写文件都需手动批准，长时间任务体验恶劣；无法满足"信任此 MCP 工具"这类常见需求。

### 目标

实现会话级"始终允许此工具"持久化：在 `agent/approval.py` 维护会话级 `_session_auto_approved: dict[str, set[str]]`（session_id → 工具名集合），runtime 在 `_request_tool_approval` 入口检查集合跳过审批。前端审批 UI 卡片增加"始终允许此工具"复选框，勾选后写入集合。

### 当前实现位置

- `agent/approval.py:67-68`（`_pending_approvals` 全局字典，无持久化记忆）
- `agent/approval.py:71-99`（`request_approval` 函数）
- `agent/runtime.py:1209-1317`（`_request_tool_approval` 方法，无记忆检查）
- `agent/runtime.py:1243-1268`（before_approval 钩子调用，无记忆检查）
- `agent/server.py`（`/api/chat/approve` 端点，需 Read 确认行号）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/sdk/sdk-tool-policies.ts:48-73`（`isToolAutoApproved` 按类别判断）
- Cline `third_party/cline/apps/vscode/src/services/mcp/McpHub.ts:1534`（`toggleToolAutoApprove` 持久化到 mcp_settings.json）
- Cline `third_party/cline/apps/cli/src/runtime/interactive/approvals.ts:21-37`（`autoApproveAllRef` 与 `setInteractiveAutoApprove` 热切换）

### 修复步骤建议

1. **在 `agent/approval.py` 新增会话级记忆数据结构**
   - 在 `_pending_approvals` 字典下方新增 `_session_auto_approved: dict[str, set[str]] = {}`（session_id → 工具名集合）
   - 新增 `mark_auto_approved(session_id: str, tool_name: str) -> None`：将工具名加入对应 session 的集合
   - 新增 `is_auto_approved(session_id: str, tool_name: str) -> bool`：检查工具名是否在集合中
   - 新增 `clear_session_auto_approved(session_id: str) -> None`：会话结束时清空（可选，避免内存泄漏）
   - 新增 `list_auto_approved(session_id: str) -> list[str]`：查询当前会话已自动批准的工具列表（供前端展示）

2. **在 `_request_tool_approval` 入口检查记忆**
   - 在 `agent/runtime.py:1243`（before_approval 钩子调用）之前增加记忆检查：
     ```python
     if is_auto_approved(self.config.session_id or "", tool_call.tool_name):
         logger.info(f"工具 {tool_call.tool_name} 已被会话级记忆自动批准")
         return None
     ```
   - 此检查在 before_approval 钩子之前，因为记忆是用户显式决策的结果，优先级最高

3. **扩展 `/api/chat/approve` 端点支持"始终允许"标志**
   - Read `agent/server.py` 确认 `/api/chat/approve` 端点行号与请求体格式
   - 请求体增加 `auto_approve: bool` 字段（前端复选框值）
   - 端点处理：若 `auto_approve=True` 且 `result="approved"`，调用 `mark_auto_approved(session_id, tool_name)`
   - 端点返回值增加 `auto_approved_tools: list[str]`（供前端展示当前已自动批准的工具列表）

4. **前端审批 UI 增加复选框**
   - Read `static/js/ai-chat.js` 确认 `renderApprovalBlock` 与 `_sendApproval` 行号
   - 在审批卡片中增加 `<label><input type="checkbox" id="auto-approve-checkbox"> 始终允许此工具</label>`
   - `_sendApproval` 提交时附带 `auto_approve: checkbox.checked`

5. **会话结束时清理记忆（可选）**
   - 在 `agent/server.py` 的会话清理逻辑中调用 `clear_session_auto_approved(session_id)`
   - 避免长期运行的服务内存累积

### 验证方法

1. 单元测试：构造会话级记忆场景
   - 调用 `mark_auto_approved("session-1", "editor")`
   - 检查 `is_auto_approved("session-1", "editor")` 返回 True
   - 检查 `is_auto_approved("session-1", "run_commands")` 返回 False
   - 检查 `is_auto_approved("session-2", "editor")` 返回 False（会话隔离）
2. 集成测试：模拟用户审批 `editor` 工具并勾选"始终允许"
   - 第一次调用 `editor` → 走完整审批流程，用户批准并勾选
   - 第二次调用 `editor` → 直接通过（不挂起等待）
   - 调用 `run_commands` → 仍走审批流程（未被记忆）
3. 前端测试：检查审批卡片含复选框，勾选后 POST 请求体含 `auto_approve: true`
4. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`agent/server.py` 的 `/api/chat/approve` 端点与 `static/js/ai-chat.js` 的审批 UI 需先 Read 确认行号与请求体格式
- 保留原函数逻辑：`request_approval` / `set_approval_result` / `get_approval_result` 等函数不动，仅新增记忆相关函数
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback
- 安全性：会话级记忆仅在当前会话有效，不跨会话持久化（跨会话持久化是中长期任务，见 phase U 修复建议第 1 条长期项）
- 与 5.7（三态语义）有交互：5.7 实现 `autoApprove` 字段后，本任务的"始终允许"可视为运行时动态写入 `tool_policies[tool_name].autoApprove = True` 的等价行为，建议两者协同设计
- 量化场景评估：量化系统用户常需连续写多个文件（如生成研报、调整策略代码），会话级记忆显著提升 UX

---

## 5.7 审批 toolPolicies 三态语义（U2）

### 任务背景

来源 Phase U #U2。Cline 的 `ToolPolicy` 三态语义（`shared/llms/tools.ts:7-18`）：
- `enabled: false` → deny（工具被禁用，直接 skip）
- `autoApprove: false` → ask（需用户审批）
- 默认（`enabled` 未设/true 且 `autoApprove` 未设/true）→ allow（直接执行）

策略合并（`agent-runtime.ts:129-137` `resolveToolPolicy`）：先取 `toolPolicies["*"]`，再覆盖 `toolPolicies[name]`，最后被 `beforeTool` hook 返回的 `policy` 字段覆盖（`agent-runtime.ts:1397-1400`）。

我的实现 `agent/runtime.py:1182-1187` 中 `tool_policies` 字典仅支持 `{"enabled": False, "reason": ...}` 一种语义（deny），"ask" 状态由 `BaseTool.requires_approval` 属性硬编码在每个工具类上（`agent/tools/base.py:96`），策略层只能禁用。没有 per-tool `autoApprove` 字段，无法通过配置运行时切换某工具的审批需求。

### 目标

扩展 `tool_policies` 字典值类型支持 `{enabled, autoApprove, reason}` 三字段，实现三态语义。runtime 改为：先判 `enabled is False` → skip；再判 `autoApprove is False` 或 `tool.requires_approval` → 走审批。在 `BeforeToolResult` 增加 `policy` 字段，允许 hook 运行时覆盖策略。

### 当前实现位置

- `agent/runtime.py:1182-1187`（工具策略检查，仅判 `enabled is False`）
- `agent/runtime.py:1189-1196`（审批检查，基于 `requires_approval` 与 `auto_approve`）
- `agent/approval_policy.py:139-191`（`AutoApprovalPolicy` 类，作为 before_approval 钩子）
- `agent/tools/base.py:95-103`（`requires_approval` 属性，硬编码）
- `agent/hooks.py:126-138`（`BeforeToolResult` dataclass，无 `policy` 字段）
- `agent/types.py`（`AgentRuntimeConfig.tool_policies`，需 Read 确认行号）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/llms/tools.ts:7-18`（`ToolPolicy` 接口：`enabled?` + `autoApprove?`）
- Cline `third_party/cline/sdk/packages/agents/src/agent-runtime.ts:129-137`（`resolveToolPolicy` 合并函数）
- Cline `third_party/cline/sdk/packages/agents/src/agent-runtime.ts:1396-1413`（三态判断：`enabled === false` → skip；`autoApprove === false` → requestToolApproval）

### 修复步骤建议

1. **扩展 `tool_policies` 字典值类型**
   - `agent/types.py` 中 `AgentRuntimeConfig.tool_policies` 类型保持 `dict[str, dict[str, Any]]`（已是 dict，无需改类型）
   - 文档注释更新：字典值支持 `{"enabled": bool, "autoApprove": bool, "reason": str}` 三字段，均为可选
   - 默认语义：`enabled` 未设 = True（允许）；`autoApprove` 未设 = True（自动批准）

2. **修改 `_prepare_tool_execution` 的策略检查**
   - `agent/runtime.py:1182-1187` 的策略合并逻辑保留：`merged = {**global_policy, **policy}`
   - 在 `merged.get("enabled") is False` 判断后增加 `autoApprove` 判断：
     ```python
     if merged.get("enabled") is False:
         skip_reason = merged.get("reason") or f'Tool "{tool_call.tool_name}" is disabled by policy'
     elif merged.get("autoApprove") is False:
         # 显式配置需审批，无论 tool.requires_approval 如何
         skip_reason = await self._request_tool_approval(tool_call, input_value)
     ```
   - 原 `agent/runtime.py:1191-1196` 的 `requires_approval and not auto_approve` 逻辑保留作为兜底：若策略未显式设 `autoApprove`，则按工具属性 + 全局 `auto_approve` 决定

3. **在 `BeforeToolResult` 增加 `policy` 字段**
   - `agent/hooks.py:126-138` 的 `BeforeToolResult` dataclass 增加 `policy: dict[str, Any] | None = None`
   - 在 `agent/runtime.py:1163-1179` 的 before_tool hooks 调用中，检查 `result.policy` 并合并到 `policyOverride`
   - 合并逻辑对标 Cline `agent-runtime.ts:1381-1386`：`policyOverride = {...policyOverride, ...result.policy}`
   - 合并后传入后续的策略检查（`merged = {**global_policy, **policy, **policyOverride}`）

4. **更新 `AutoApprovalPolicy` 与 `before_approval` 钩子**
   - `agent/approval_policy.py` 的 `AutoApprovalPolicy` 不变（它作为 before_approval 钩子，与 tool_policies 是互补关系）
   - 但需确认：若 `tool_policies` 显式设 `autoApprove: False`，`AutoApprovalPolicy` 仍可决策 approved/denied（钩子优先级高于策略）
   - 即：tool_policies 决定"是否需要审批"，`AutoApprovalPolicy` 决定"审批是否自动通过"

5. **更新 Plan Mode 工具策略**
   - `agent/server.py` 中 Plan Mode 的 `tool_policies`（Read 确认行号，约 L363-372）可改为：
     ```python
     tool_policies = {
         "editor": {"enabled": False, "reason": "Plan 模式下禁止编辑文件"},
         "apply_patch": {"enabled": False, "reason": "Plan 模式下禁止打补丁"},
         "file_write": {"enabled": False, "reason": "Plan 模式下禁止写文件"},
         "run_commands": {"autoApprove": False},  # Plan 模式下 run_commands 走审批
     }
     ```
   - 原 `enabled: False` 禁用逻辑不变，新增 `autoApprove: False` 走审批的能力

### 验证方法

1. 单元测试：构造 4 类策略场景
   - `tool_policies = {"editor": {"enabled": False}}` → editor 被禁用，skip_reason 含 "disabled by policy"
   - `tool_policies = {"run_commands": {"autoApprove": False}}` → run_commands 走审批流程
   - `tool_policies = {"read_files": {"autoApprove": True}}` → read_files 直接执行（即使 `requires_approval=True`）
   - `tool_policies = {}` → 按原逻辑（`requires_approval` + `auto_approve`）决定
2. 验证 `BeforeToolResult.policy` 字段：before_tool 钩子返回 `policy={"autoApprove": False}`，runtime 应走审批流程
3. 验证策略合并：`tool_policies = {"*": {"autoApprove": True}, "editor": {"autoApprove": False}}` → editor 走审批，其他工具自动批准
4. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`agent/types.py` 的 `AgentRuntimeConfig.tool_policies` 字段类型与默认值需先 Read 确认
- 保留原函数逻辑：`requires_approval` 属性保留（作为工具的默认审批需求），`auto_approve` 全局开关保留（作为兜底），新增 `tool_policies[name].autoApprove` 作为更细粒度的覆盖
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback
- 与 5.6（会话级记忆）协同：5.6 的"始终允许"可视为运行时动态写入 `tool_policies[name].autoApprove = True`，建议两者协同设计
- 与 Plan Mode（`agent/server.py` L363-372）有交互：Plan Mode 可用 `autoApprove: False` 替代部分 `enabled: False`，提供更细粒度的控制
- 优先级 P2：本任务为中期改造，不影响 P1 主流程

---

## 5.8 telemetry 隐私合规 opt-out + PII 脱敏（Z13）

### 任务背景

来源 Phase Z #Z13。Cline 的 telemetry 隐私机制包含：
- 全局 opt-out 开关（`global-settings.ts:42,155-177`）：`telemetryOptOut: boolean` 持久化到 `~/.cline/settings.json`，`isTelemetryOptedOutGlobally()` 查询，opt-out 时返回 `OptedOutTelemetryService`（no-op）
- `captureRequired` 语义（`TelemetryService.ts:75-80` + `core-events.ts:357-365`）：必需事件绕过 opt-out（如 `user.opt_out` 确认事件本身）
- 错误消息截断（`core-events.ts:21,166-171`）：`MAX_ERROR_MESSAGE_LENGTH = 500`，`truncateErrorMessage` 截断
- 属性展平安全（`OpenTelemetryAdapter.ts:252-337`）：循环引用检测、最大深度限制、数组截断、`__proto__` 键过滤

我的实现 `agent/telemetry.py` 完全无 opt-out 机制、无 `captureRequired`、无 PII 脱敏。`_truncate_preview`（`telemetry.py:633-646`）仅截断工具输入/输出预览，不截断错误消息，不脱敏 PII。`json.dumps` 默认会抛 `ValueError` on circular reference。

量化场景处理金融数据，PII 脱敏与 opt-out 是合规要求（GDPR/CCPA/个人信息保护法）。

### 目标

实现 telemetry 隐私合规机制：
1. 全局 opt-out 开关：通过环境变量 `AGENT_TELEMETRY_OPT_OUT` 与配置文件控制，opt-out 时 `capture` 直接返回
2. `capture_required` 方法：绕过 opt-out（用于 opt-out 事件本身等必需事件）
3. PII 脱敏：对手机号、邮箱、身份证、银行卡号等敏感字段正则脱敏
4. 通用属性截断：所有字符串属性截断到 500 字符（扩展 `_truncate_preview` 为 `_sanitize_value`）
5. `json.dumps` 防 circular reference：添加 `default=str` 与循环引用检测

### 当前实现位置

- `agent/telemetry.py:369-411`（`capture` 方法，无 opt-out 检查）
- `agent/telemetry.py:386-402`（属性合并逻辑，无 PII 脱敏）
- `agent/telemetry.py:633-646`（`_truncate_preview` 函数，仅截断预览）
- `agent/telemetry.py:322-336`（`TelemetryService.__init__`，无 opt-out 标志）
- `agent/telemetry.py:470-487`（`get_telemetry_service` 单例，无 opt-out 检查）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/global-settings.ts:42,155-177`
  - L42：`telemetryOptOut: z.boolean().default(false).catch(false)`
  - L155-157：`if (!previous.telemetryOptOut && normalized.telemetryOptOut) { captureTelemetryOptOut(...) }`
  - L162-164：`isTelemetryOptedOutGlobally()` 查询
- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/OpenTelemetryProvider.ts:48-111`（`OptedOutTelemetryService` no-op 实现）
- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/TelemetryService.ts:75-80`（`captureRequired` 方法）
- Cline `third_party/cline/sdk/packages/core/src/services/telemetry/core-events.ts:21,166-171`（`MAX_ERROR_MESSAGE_LENGTH = 500` + `truncateErrorMessage`）

### 修复步骤建议

1. **新增 opt-out 配置读取**
   - 在 `agent/telemetry.py` 顶部新增 `_read_telemetry_opt_out() -> bool` 函数
   - 优先级：环境变量 `AGENT_TELEMETRY_OPT_OUT`（值为 "1"/"true"/"yes" 时为 True）> 配置文件 `agent_config/telemetry.yaml` 的 `opt_out` 字段 > 默认 False
   - 在 `TelemetryService.__init__` 中读取并存储 `self._opted_out: bool = _read_telemetry_opt_out()`

2. **在 `capture` 方法入口检查 opt-out**
   - `agent/telemetry.py:386-388` 的 `if self._closed: return` 之后增加 `if self._opted_out: return`
   - 保留原 `_closed` 检查与后续逻辑

3. **新增 `capture_required` 方法**
   - 在 `capture` 方法之后新增 `capture_required(self, event, session_id="", run_id="", iteration=None, properties=None) -> None`
   - 该方法不检查 `self._opted_out`（绕过 opt-out），其余逻辑与 `capture` 相同
   - 用途：opt-out 事件本身、必需的错误事件等
   - 在方法内复用 `capture` 的属性合并与 sink 派发逻辑（可抽取一个 `_dispatch_event` 内部方法供两者调用）

4. **扩展 `_truncate_preview` 为通用 `_sanitize_value`**
   - 保留原 `_truncate_preview` 函数（不删除，向后兼容）
   - 新增 `_sanitize_value(value: Any, max_chars: int = 500) -> Any` 函数：
     - 字符串：先 PII 脱敏（步骤 5），再截断到 max_chars
     - dict：递归 sanitize 每个值
     - list：递归 sanitize 每个元素
     - 其他：原值返回
   - 在 `capture` 的属性合并后，遍历 `merged_props` 调用 `_sanitize_value`

5. **新增 PII 脱敏正则**
   - 在 `agent/telemetry.py` 顶部新增 `_PII_PATTERNS: list[tuple[re.Pattern, str]]` 列表：
     - 手机号：`r"1[3-9]\d{9}"` → `"[PHONE]"`
     - 邮箱：`r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"` → `"[EMAIL]"`
     - 身份证：`r"\d{17}[\dXx]"` → `"[ID_CARD]"`
     - 银行卡号：`r"\d{16,19}"` → `"[BANK_CARD]"`（需注意不误伤短数字）
   - 新增 `_redact_pii(text: str) -> str` 函数：遍历 `_PII_PATTERNS` 做 `re.sub`
   - 在 `_sanitize_value` 的字符串分支中调用 `_redact_pii`

6. **`json.dumps` 防 circular reference**
   - `agent/telemetry.py:244` 的 `json.dumps(ev.to_dict(), ensure_ascii=False)` 增加 `default=str` 参数
   - 在 `TelemetryEvent.to_dict` 或 `capture` 中增加循环引用检测：维护一个 `seen: set[int]` set，递归时检查 `id(obj) in seen`，是则返回 `"[Circular]"`

7. **新增 opt-out 状态查询与切换 API**
   - `is_opted_out() -> bool`：查询当前 opt-out 状态
   - `set_opt_out(value: bool) -> None`：运行时切换 opt-out（对标 Cline `setTelemetryOptOutGlobally`）
   - 切换为 True 时，调用 `capture_required("telemetry.opt_out", properties={"reason": "user_request"})` 记录 opt-out 事件本身

8. **在 `capture_service_activated` 中使用 `capture_required`**
   - `agent/telemetry.py:672` 的 `service.capture(event="service.activated", ...)` 改为 `service.capture_required(event="service.activated", ...)`
   - 服务激活事件是必需事件（用于统计活跃安装），不应被 opt-out 吞掉

### 验证方法

1. 单元测试：构造 opt-out 场景
   - 设置 `AGENT_TELEMETRY_OPT_OUT=1`
   - 调用 `service.capture("run.started", ...)`，检查 MemorySink 中无该事件
   - 调用 `service.capture_required("telemetry.opt_out", ...)`，检查 MemorySink 中有该事件
2. PII 脱敏测试：
   - 构造 properties 含 `{"error": "用户手机号 13800138000 已注册，邮箱 user@example.com"}`
   - 调用 `capture`，检查 MemorySink 中事件 properties.error 为 `"...[PHONE]...已注册，邮箱 [EMAIL]"`
3. 截断测试：
   - 构造 properties 含超长字符串（1000 字符）
   - 检查 MemorySink 中该字段被截断到 500 字符 + `"...(截断)"`
4. 循环引用测试：
   - 构造 properties 含自引用 dict（`d = {}; d["self"] = d`）
   - 调用 `capture`，检查不抛异常，properties 中自引用字段为 `"[Circular]"`
5. opt-out 切换测试：
   - 调用 `set_opt_out(True)`
   - 检查 `is_opted_out()` 返回 True
   - 检查 MemorySink 中有 `telemetry.opt_out` 事件（通过 `capture_required` 记录）
6. 运行 `python tests/test_agent_e2e.py` 验证不破坏现有流程

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`agent_config/` 目录是否已有 `telemetry.yaml` 配置文件，若无则需新建或仅用环境变量
- 保留原函数逻辑：`_truncate_preview` 保留（向后兼容），`capture` 方法的原属性合并逻辑保留，仅在入口增加 opt-out 检查与出口增加 sanitize
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback
- PII 脱敏正则需谨慎：银行卡号 `\d{16,19}` 可能误伤非敏感长数字（如时间戳毫秒数），建议仅对明确标识为"银行卡号"的字段名（如 `bank_card` / `card_number`）脱敏，或结合字段名与正则双重判断
- 量化场景评估：金融数据可能含股票代码（6 位数字）、订单号等，PII 正则不应误伤这些字段
- 优先级 P1：合规风险，应优先实施 opt-out 与 PII 脱敏；循环引用检测为 P2（实际场景中少见）
- 与 5.1-5.7 独立，可并行实施

---

## 附录：实施顺序建议

1. **第一周（P1 主流程）**：
   - 5.1 + 5.2（合并实施，同改 `_loop_detection_hook`）
   - 5.3（blocking 默认值，单点改动）
   - 5.8（telemetry 隐私，独立可并行）

2. **第二周（P1 收尾 + P2）**：
   - 5.4（退出码语义，依赖 5.3 的 fail-open 默认值）
   - 5.6（审批记忆，前端 + 后端协同）
   - 5.5（并发评估，可能仅评估不实施）
   - 5.7（三态语义，中期改造）

3. **验证**：
   - 每个小阶段完成后运行 `python tests/test_agent_e2e.py` 与对应单元测试
   - 全部完成后运行 `python test_phase23_hooks.py` 验证 hooks 系统不破坏
   - 量化场景端到端测试：生成一份研报，观察循环检测、hook、审批、telemetry 行为
