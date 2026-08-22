# Phase 3.16 Plan Mode 实现细节对比（plan/act 模式切换、工具集、限制、系统提示、completes_run）

> 对比范围：Cline plan mode 工作流（mode 枚举、tool preset、PLAN_MODE_INSTRUCTIONS、switch_to_act_mode 工具、mode switch notice tracker、auto-continuation、completesRun 生命周期）与 Charles `agent/tools/plan_mode.py` + `agent/state.py` ModeSwitchNotice + `agent/server.py` mode 切换 API 的实现差异。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L21-45（MODE_TAG_INSTRUCTIONS / PLAN_MODE_INSTRUCTIONS）
> - `sdk/packages/shared/src/prompt/format.ts` L5-80（formatUserInputBlock / formatModeSwitchNotice / createModeSwitchNoticeTracker）
> - `sdk/packages/core/src/extensions/tools/presets.ts` L20-126（ToolPresets.act / plan / resolveToolPresetName）
> - `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` L1-140（ToolRoutingRule + DEFAULT_MODEL_TOOL_ROUTING_RULES）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L796-826（createSubmitAndExitTool 的 completesRun）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L79-84, 126-161, 660-665（filterAvailableTools + createBuiltinToolsList）
> - `sdk/packages/agents/src/agent-runtime.ts` L557-595, 722-739, 1312-1332（getRequiredCompletionToolNames / findCompletingToolMessage）
> - `sdk/packages/shared/src/agent.ts` L146-156（AgentToolDefinition.lifecycle.completesRun）
> - `apps/cli/src/runtime/interactive/mode.ts`（createInteractiveModeSwitchTool + sendTurnWithActModeContinuation）
> - `apps/vscode/src/sdk/sdk-session-config-builder.ts` L38-80（plan 模式额外注册 switch_to_act_mode）
> - `apps/vscode/src/sdk/sdk-mode-coordinator.ts`（SdkModeCoordinator + rebuildSessionForMode + ACT_MODE_CONTINUATION_PROMPT）
>
> Charles 源码：
> - `agent/tools/plan_mode.py`（PLAN_MODE_PROMPT + SwitchToActModeTool + SwitchToPlanModeTool + 辅助函数）
> - `agent/state.py` L58, 101, 140-162, 363-485（AgentMode / SessionState.mode / ModeSwitchNotice / set_mode / get_mode / consume_mode_notice / format_mode_switch_notice）
> - `agent/tools/__init__.py` L48-112（create_default_tools 注册两个切换工具）
> - `agent/tools/constants.py` L90-156（TOOL_PRESETS 文档化预设）
> - `agent/tools/routing.py`（ToolRoutingRule + resolve_tool_routing）
> - `agent/runtime.py` L506-515, 740-747, 2045-2074, 2308-2321, 2850-2865（mode 读取 / _find_completing_tool / _get_current_mode_for_wrap）
> - `agent/server.py` L340-386, 505-549, 575-606, 880-906, 936-977, 1336-1380（_create_runtime tool_policies / SystemPromptBuilder / _sse_generator / STATUS_NOTICE / mode 切换 API）
> - `agent/context.py` L275, 454-518, 836-872（_build_rules / _build_mode_tag_instructions / _load_mode_prompt）
> - `agent/prompts/charles_system_prompt.py`（DEFAULT / YOLO 模板，{{CHARLES_RULES}} 占位符）
> - `agent/approval_policy.py` L34-47（READ_ONLY_TOOLS 含 switch_to_*）

---

## 一、执行摘要

Cline 与 Charles 在 Plan Mode 工作流上整体架构对齐（mode 枚举、plan 提示、切换工具、`completes_run`、mode_notice 机制都有对应实现），但在**5 个关键行为**上存在差异：

1. **switch_to_plan_mode 工具存在性**：Charles 额外实现了 `SwitchToPlanModeTool`（允许 LLM 主动从 act 切回 plan），Cline 无此工具（plan 模式切换只能由 UI 触发）。**Charles 是 Cline 的超集**。

2. **switch_to_act_mode 自动续跑（auto-continue）**：Cline 在 LLM 调用 `switch_to_act_mode` 且 `finishReason === "completed"` 后，会自动注入 `ACT_MODE_CONTINUATION_PROMPT = "The user approved switching to act mode. Continue with the approved plan now."` 作为合成用户消息**立即继续下一轮**；Charles 仅靠 `completes_run=True` 结束当前 run，**无自动续跑**，需用户手动发下一条消息。**Charles 缺失此特性**。

3. **Mode switch notice 记录路径**：Cline 严格区分 UI 触发（`recordModeSwitchNotice`）与工具触发（不记录 notice，靠 continuation prompt 自带 announce）；Charles 的 `set_mode` 函数对**所有路径**（包括 SwitchToActModeTool 调用）都记录 pending notice，与 docstring 声称的"仅 UI 切换应记录"**不一致**。但因 Charles 缺失 continuation prompt，此"不一致"反而是**功能上必要的补偿**——否则模型无法感知工具发起的切换。

4. **Plan 模式工具集差异**：Cline 仅禁用 `editor` + `apply_patch`（`enableSubmitAndExit: false` 是 preset 配置但 submit_and_exit 不在 plan preset 中实际创建）；Charles 禁用 `editor` + `apply_patch` + `file_write`，但**保留 submit_and_exit 可用**。两侧都保留 `run_commands` 可用（仅靠提示词约束为只读检查）。

5. **Mode 切换后会话重建**：Cline `SdkModeCoordinator.rebuildSessionForMode` 完全销毁旧 session、重建 runtime 与工具集（保证 act 模式工具只在重建后出现）；Charles 仅更新 `SessionState.mode`，runtime 与工具集**不会重建**，下次 `_create_runtime` 调用（即下次 `/stream` 请求）时才反映新 mode 的 `tool_policies`。

6. **nanobot 残留**：Plan Mode 核心文件 `plan_mode.py` / `state.py`（mode 段落）/ `runtime.py`（completes_run 段落）/ `tools/routing.py` / `tools/constants.py` 均 0 残留。残留集中在 `tools/__init__.py` L2（docstring）、`server.py` L2/L4/L28（docstring）、`context.py` L275（参数注释），全部为注释残留，无实现逻辑残留。

7. **一致性总体评估**：**中**。核心机制对齐，但 `auto-continue` 缺失导致 plan→act 切换后用户体验割裂（用户必须手动续跑），是 P1 级别功能差距。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.16.1 | Mode 枚举类型 | `act \| plan \| yolo`（CoreAgentMode / Mode） | `Literal["act", "plan"]`（AgentMode） | 中 | Charles 不支持 yolo 模式（量化场景不启用实盘自动执行） |
| 3.16.2 | Mode 状态存储位置 | `stateManager.getGlobalSettingsKey("mode")` 全局设置 | `SessionState.mode` per-session 内存 + 持久化磁盘 | 中（设计差异） | Cline 是 host 级全局；Charles 是 session 级隔离 |
| 3.16.3 | Plan 模式工具预设 | `ToolPresets.plan`（presets.ts L43-55） | `TOOL_PRESETS["plan"]`（constants.py L128-139）+ `server.py` L362-369 tool_policies | 中 | Charles 预设仅文档化，实际过滤靠 tool_policies |
| 3.16.4 | Plan 模式禁用的工具 | `editor: false`, `apply_patch: false`, `enableSubmitAndExit: false` | `editor`, `apply_patch`, `file_write` 禁用 | 中 | Charles 多禁用 file_write；submit_and_exit 在 Charles 仍可用 |
| 3.16.5 | Plan 模式保留 run_commands | 是（preset `enableBash: true`） | 是（不在禁用列表） | 高 | 两侧一致：仅靠提示词约束为只读 |
| 3.16.6 | Plan 模式系统提示 | `PLAN_MODE_INSTRUCTIONS`（cline.ts L32-45，英文） | `PLAN_MODE_PROMPT`（plan_mode.py L38-55，中文） | 高 | 内容对齐，措辞本地化 |
| 3.16.7 | Mode 标签说明 | `MODE_TAG_INSTRUCTIONS`（cline.ts L21-23） | `_build_mode_tag_instructions`（context.py L836-856） | 高 | Charles 用 Python 字符串生成，语义一致 |
| 3.16.8 | Mode 标签注入位置 | `effectiveRules` 数组（cline.ts L145-151） | `_build_rules` 中作为 rule 项注入（context.py L502-518） | 高 | 都作为 rules 段拼接，对齐 Cline effectiveRules 顺序 |
| 3.16.9 | switch_to_act_mode 工具 | 仅 plan 模式注册（sdk-session-config-builder.ts L38-46） | 始终注册（tools/__init__.py L109） | 中 | Charles 不区分 mode 注册；Cline act 模式过滤掉此工具 |
| 3.16.10 | switch_to_plan_mode 工具 | **不存在**（Cline 仅有 switch_to_act_mode） | 存在（plan_mode.py L167-266） | 低（Charles 超集） | **Charles 扩展**：允许 LLM 主动切回 plan |
| 3.16.11 | 切换工具 lifecycle | `completesRun: true`（mode.ts L53-55） | `ToolLifecycle(completes_run=True)`（plan_mode.py L110, L213） | 高 | 完全对齐 |
| 3.16.12 | 切换工具 read_only | 无显式标记 | `read_only = True`（plan_mode.py L113-115, L216） | 中 | Charles 显式声明只读；Cline 由 toolPolicies 控制 |
| 3.16.13 | 切换工具参数 schema | `{type:"object", properties:{}}` | `{type:"object", properties:{}, description:"..."}` | 高 | Charles 多了顶层 description 字段（无害） |
| 3.16.14 | 工具触发后行为 | `completesRun` 结束 run + 注入 ACT_MODE_CONTINUATION_PROMPT 自动续跑 | 仅 `completes_run=True` 结束 run | 低 | **Charles 缺失 auto-continue** |
| 3.16.15 | Auto-continue 触发条件 | `switched.source === "tool"` AND `result.finishReason === "completed"` | 无此机制 | 低 | Charles 无 source 区分（无 auto-continue） |
| 3.16.16 | UI 切换 vs 工具切换区分 | `PendingModeChange.source: "tool" \| "ui"` | 无 source 字段 | 低 | Charles 不区分（无 auto-continue 需求） |
| 3.16.17 | Mode 切换 notice tracker | `createModeSwitchNoticeTracker`（format.ts L61-80） | `_pending_mode_notices: dict` + `_record_mode_switch_locked`（state.py L162, L398-432） | 高 | 两侧语义完全一致：往返抵消 + 链式保留 from |
| 3.16.18 | Notice 格式 | `<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>` | 完全相同（state.py L482-485） | 高 | 字节级一致 |
| 3.16.19 | Notice 记录路径 | 仅 `source === "ui"` 记录（sdk-mode-coordinator.ts L305-307） | 所有 set_mode 调用都记录（state.py L387-388） | 低 | **Charles 不区分**：工具切换也会记录 notice |
| 3.16.20 | Notice 消费时机 | `fireAndForgetSend` 包装用户消息前 consume | `_sse_generator` 包装用户消息前 consume（server.py L603-604） | 高 | 都在下一条用户消息前 prepend |
| 3.16.21 | Mode 切换后会话重建 | `rebuildSessionForMode`：销毁旧 session + 创建新 runtime + 新工具集 | 仅更新 SessionState.mode，runtime 不重建 | 低 | **Charles 不重建**：下次 /stream 才生效 |
| 3.16.22 | Mode 切换 API | UI 触发（togglePlanActMode）+ 工具触发（switch_to_act_mode） | UI 触发（POST /api/chat/mode）+ 工具触发（switch_to_*） | 高 | 两侧都支持两种路径 |
| 3.16.23 | Plan→Act 重建后状态 | `mode` 设置为新值 + 新工具集立即生效 + 自动续跑（若 source=tool） | `mode` 设置为新值 + 工具集下次 run 才生效 + 无续跑 | 低 | **Charles 三个差距叠加** |
| 3.16.24 | completes_run 检测算法 | `findCompletingToolMessage`（agent-runtime.ts L1312-1332） | `_find_completing_tool`（runtime.py L2048-2074） | 高 | 算法逐行对齐：遍历 tool_calls → 检查 lifecycle.completesRun → 检查 is_error |
| 3.16.25 | Multiple completing tools | 取第一个匹配且非 error 的（agent-runtime.ts L1316-1330） | 取第一个匹配且非 error 的（runtime.py L2059-2073） | 高 | 行为一致 |
| 3.16.26 | Completion policy | `completionPolicy.requireCompletionTool` + `completionGuard` | `_find_completing_tool_name` + `_inject_completion_reminder` | 中 | Charles 用 reminder 注入提示，Cline 用 policy 配置 |
| 3.16.27 | 用户消息 mode 包装 | `formatUserInputBlock(input, mode)` → `<user_input mode="...">` | `f'<user_input mode="{current_mode}">...</user_input>'`（server.py L605） | 高 | 字面格式一致 |
| 3.16.28 | Mode 标签解析 | `parseUserInputMode`（format.ts L27-32） | 无独立解析函数 | 中 | Charles 不需要回溯解析历史消息的 mode |
| 3.16.29 | Tool routing 与 mode 联动 | `resolveToolRoutingConfig(providerId, modelId, mode, rules)` | `resolve_tool_routing(provider_id, model_id, mode, rules)` | 高 | 函数签名与逻辑完全对齐 |
| 3.16.30 | Plan 模式 tool routing 规则 | `DEFAULT_MODEL_TOOL_ROUTING_RULES` 仅 act 模式规则（model-tool-routing.ts L60-75） | `DEFAULT_MODEL_TOOL_ROUTING_RULES` 仅 act 模式规则（routing.py L59-74） | 高 | 两侧 plan 模式都无 routing 规则（plan 由 preset/policies 控制） |
| 3.16.31 | Plan 模式 approval_policy | 无 mode 相关 approval 规则（全局 toolPolicies） | `switch_to_*` 在 READ_ONLY_TOOLS（approval_policy.py L44-45）自动批准 | 中 | Charles 显式声明切换工具为只读自动批准 |
| 3.16.32 | YOLO 模式支持 | `mode === "yolo"` 触发 YOLO_CLINE_SYSTEM_PROMPT + 自动批准 | 不支持 yolo（charles_system_prompt.py 有 YOLO 模板但无 yolo mode 触发） | 低 | Charles 模板存在但 mode 枚举不含 yolo |

**一致性总评**：32 项中，高一致性 16 项、中一致性 10 项、低一致性 6 项（3.16.10 / 3.16.14 / 3.16.19 / 3.16.21 / 3.16.23 / 3.16.32）。低一致性中 3.16.10 是 Charles 超集（增强），3.16.14/3.16.21/3.16.23 是 Charles 缺失特性，3.16.19 是 Charles 适应性偏离，3.16.32 是设计选择（量化场景不启用 yolo）。

---

## 三、重点差距详细说明

### 差距 1：switch_to_plan_mode 工具存在性（3.16.10）

**Cline 实现**：

Cline 仅提供 `switch_to_act_mode` 工具，**不存在 `switch_to_plan_mode`**。Plan 模式的进入只能由用户通过 UI 触发（`SdkModeCoordinator.togglePlanActMode("plan")` 或 CLI 的 TUI 模式切换）。设计哲学是：

- Plan 模式是用户主动选择的"规划阶段"，LLM 不应自主决定进入规划
- 一旦在 act 模式，LLM 应继续执行直到完成或用户中断
- 避免循环切换（plan→act→plan→act...）导致任务无法收敛

**Charles 实现**（`plan_mode.py` L167-266）：

Charles 额外实现了 `SwitchToPlanModeTool`：

```python
class SwitchToPlanModeTool(BaseTool):
    """切换到 Plan 模式 — 对标 Cline switch_to_plan_mode

    从 Act 模式切换到 Plan 模式，切换后进入只读规划状态。
    lifecycle.completes_run = True: 切换后结束本轮，等待用户下次输入。

    使用场景:
        - 用户希望重新规划任务
        - 任务方向偏离，需要重新对齐
        - 复杂任务开始前的规划阶段
    """
```

工具描述明确标注"对标 Cline switch_to_plan_mode"，但 **Cline 中并不存在此工具**——这是 Charles 的注释溯源错误（标注了不存在的对标对象）。

工具行为：
- 校验当前模式必须为 `act`，否则返回 `is_error=True`
- 调用 `set_mode(session_id, "plan")` 切换模式
- 通过 `context.emit_update` 通知前端 `mode_changed` 事件
- `lifecycle.completes_run=True` 结束当前 run

**影响**：
- Charles 的 LLM 可自主切回 plan 模式，可能导致任务执行中途进入规划状态，打断执行流。
- 与 Cline 的"plan 是用户决定"哲学冲突。
- 但在量化场景下，LLM 遇到不确定时主动切回 plan 重新对齐，是合理的策略性退避。

**建议**：保留 Charles 现状。`SwitchToPlanModeTool` 是场景化扩展，标注错误（注释对标不存在的 Cline 工具）应修正为"Charles 扩展：Cline 仅有 switch_to_act_mode，本工具为 Charles 增补"。

### 差距 2：switch_to_act_mode 自动续跑缺失（3.16.14 / 3.16.15 / 3.16.23）

**Cline 实现**（`apps/cli/src/runtime/interactive/mode.ts` L80-108 + `apps/vscode/src/sdk/sdk-mode-coordinator.ts` L25, L131-141, L194-382）：

Cline 的 plan→act 切换完整流程：

1. LLM 在 plan 模式调用 `switch_to_act_mode` 工具
2. 工具 `execute` 调用 `onSwitchToActMode()` 回调（仅设置 `pendingModeChange = { mode: "act", source: "tool" }`）
3. 工具返回成功消息，因 `completesRun: true`，runtime 调用 `finishRun("completed", ...)`
4. CLI/VSCode 的 `applyPendingModeChange` 检测到 `pendingModeChange.source === "tool"`
5. **销毁旧 session，重建 runtime**（`rebuildSessionForMode("act", { autoContinue: true, source: "tool" })`）
6. 重建完成后，**自动发送 `ACT_MODE_CONTINUATION_PROMPT = "The user approved switching to act mode. Continue with the approved plan now."`** 作为合成用户消息
7. runtime 用新 act 模式工具集 + 此 prompt 启动新 run

关键代码（`mode.ts` L80-108 `sendTurnWithActModeContinuation`）：

```typescript
const result = await input.sendInitialTurn();
const switched = await input.applyPendingModeChange();
if (
    switched?.mode !== "act" ||
    switched.source !== "tool" ||
    result?.finishReason !== "completed"
) {
    return result;
}
const continuation = await input.sendContinuationTurn(
    ACT_MODE_CONTINUATION_PROMPT,
);
```

**严格条件**：仅当 `switched.source === "tool"` 且 `result.finishReason === "completed"` 时才续跑。UI 触发的切换（`source === "ui"`）不会自动续跑，必须用户手动发消息。

**Charles 实现**（`agent/tools/plan_mode.py` L117-164 + `agent/runtime.py` L740-747）：

Charles 的 plan→act 切换流程：

1. LLM 在 plan 模式调用 `switch_to_act_mode` 工具
2. 工具 `_execute` 直接调用 `set_mode(self._session_id, "act")`（注意：这是工具直接修改状态，非设置 pending）
3. 工具通过 `context.emit_update` 通知前端 `mode_changed` 事件
4. 工具返回成功消息
5. 因 `lifecycle.completes_run=True`，runtime 的 `_find_completing_tool` 检测到并调用 `_finish_run("completed", ...)`
6. **run 结束，等待用户手动发下一条消息**

Charles 完全缺失：
- `ACT_MODE_CONTINUATION_PROMPT` 常量（grep 全局 0 匹配）
- `sendTurnWithActModeContinuation` 等价函数
- `PendingModeChange.source` 字段（无 source 区分）
- `rebuildSessionForMode` 等价逻辑（runtime 不重建）

**影响**：
- **用户体验割裂**：LLM 在 plan 模式呈现计划后调用 `switch_to_act_mode`，run 结束，用户必须手动输入"开始执行"或类似消息才能继续。Cline 用户则体验为"LLM 自动开始执行计划"。
- **mode 切换的工具集未立即生效**：Charles 不重建 runtime，所以即便 mode 已切换为 act，当前 runtime 实例的工具集仍可能是 plan 模式的（editor/apply_patch 仍被 tool_policies 禁用）。下次 `/stream` 请求创建新 runtime 时才生效。
- **量化场景实际影响**：用户通过前端"切换到 Act"按钮触发时，Charles 行为是"切换并等待下一条消息"，符合用户预期；但 LLM 主动调用 `switch_to_act_mode` 时，用户可能误以为 agent 卡住。

**建议**：[P1] 在 `agent/server.py` 的 `_sse_generator` 中，检测到 `switch_to_act_mode` 工具调用导致的 run 完成后，自动注入中文版"用户已批准切换到 Act 模式，请立即继续执行已批准的计划。"作为合成用户消息，并启动新 run。需配合 `runtime.py` 添加 `last_completing_tool_name` 字段，让 server 层能判断 run 是否由 `switch_to_act_mode` 结束。

### 差距 3：Mode switch notice 记录路径偏离（3.16.19）

**Cline 实现**（`apps/vscode/src/sdk/sdk-mode-coordinator.ts` L93-104, L305-307）：

Cline 严格区分两种切换路径：

```typescript
private async performRebuildSessionForMode(newMode, options) {
    // ...
    if (options.source === "ui") {
        this.recordModeSwitchNotice(startResult.sessionId, previousMode, newMode);
    }
    // 工具触发的 switch_to_act_mode 不记录 notice
    // 因为 ACT_MODE_CONTINUATION_PROMPT 已在续跑时自带 announce
}
```

设计依据（`format.ts` L53-60 注释）：

> Tracks a user-initiated mode switch so the next user message can carry a `<mode_notice>` marking it. Only UI toggles should be recorded: the model-initiated switch_to_act_mode path already announces itself via the continuation prompt.

**Charles 实现**（`agent/state.py` L368-389）：

Charles 的 `set_mode` 函数**不区分 source**，对所有调用统一记录 notice：

```python
def set_mode(session_id: str, mode: AgentMode) -> AgentMode:
    """设置会话当前模式，返回旧模式

    Stage 36.1 (M1): 若 mode 实际切换，记录 pending notice（对标 Cline tracker.record）。
                     仅 UI 切换应调用本函数记录 notice；模型发起的 switch_to_act_mode
                     不通过本函数记录（其切换通过 continuation prompt 自带 announce）。
    """
    with _lock:
        # ...
        if old_mode != mode:
            _record_mode_switch_locked(session_id, old_mode, mode)  # 所有路径都记录！
        return old_mode
```

**docstring 与实现矛盾**：注释声称"仅 UI 切换应调用本函数记录 notice；模型发起的 switch_to_act_mode 不通过本函数记录"，但实际 `_record_mode_switch_locked` 在所有 `set_mode` 调用中都被触发，包括 `SwitchToActModeTool._execute` 的调用。

**影响评估**：
- 因 Charles 缺失 `ACT_MODE_CONTINUATION_PROMPT`，工具发起的切换**没有其他 announce 机制**——record notice 是 Charles 唯一的"让模型感知切换发生"的方式。
- 所以此"偏离"实际上是**功能补偿**：在缺 auto-continue 的前提下，record notice 是必要的。
- 但 docstring 误导性大：声称对标 Cline 但实际偏离，应修正注释或补齐 auto-continue 后修正实现。

**建议**：[P2] 二选一：
- 方案 A：补齐 auto-continue 后，将 `_record_mode_switch_locked` 调用从 `set_mode` 中移出，仅 UI 路径调用 `record_mode_switch`（对齐 Cline）
- 方案 B：保留现状，修正 docstring 为"Charles 扩展：因缺失 auto-continue，所有切换路径都记录 notice 作为唯一 announce 机制"

### 差距 4：Mode 切换后会话重建缺失（3.16.21 / 3.16.23）

**Cline 实现**（`apps/vscode/src/sdk/sdk-mode-coordinator.ts` L194-382）：

`rebuildSessionForMode` 完整流程：

1. 设置 `stateManager.setGlobalState("mode", newMode)` （更新全局设置）
2. 获取 active session，若正在运行则 `cancelRunningTurnForModeChange`（中止当前 run）
3. 加载 initial messages
4. 调用 `sessionConfigBuilder.build({ cwd, mode: newMode })` 重建 config（含新工具集）
5. `sessions.replaceActiveSession({ expectedSession, startInput, initialMessages, disposeReason: "modeChange" })` 销毁旧 session + 创建新 session
6. 若 `autoContinue`，注入 `ACT_MODE_CONTINUATION_PROMPT` 并 `fireAndForgetSend` 启动新 run
7. `postStateToWebview` 更新前端状态

**Charles 实现**：

Charles 的 mode 切换 API（`server.py` L1353-1380）：

```python
@router.post("/mode")
async def set_session_mode(request: Request):
    # ...
    set_mode(session_id, mode)  # 仅更新 SessionState.mode
    return {"status": "ok", "mode": mode}
```

仅更新 `SessionState.mode`，**不重建 runtime**。下次 `/stream` 请求时 `_create_runtime` 才会根据新 mode 构建 `tool_policies` 与工具集。

工具触发的切换（`SwitchToActModeTool._execute`）：直接 `set_mode` + `emit_update`，runtime 实例**继续以旧工具集运行**直到 run 结束。

**影响**：
- **plan→act 切换后立即续跑会失败**：若在 Charles 实现 auto-continue（差距 2），续跑的 run 仍使用 plan 模式的 runtime（editor/apply_patch 被 tool_policies 禁用），无法执行计划中的写操作。
- **当前影响有限**：因 Charles 不续跑，用户下次发消息时新 runtime 已创建，工具集正确。
- **未来修复差距 2 时必须同时修复此差距**。

**建议**：[P1] 修复差距 2 时同步引入会话重建逻辑——在 `_sse_generator` 中检测到 `switch_to_act_mode` 完成后，重新调用 `_create_runtime` 替换当前 runtime 实例，再启动续跑 run。

### 差距 5：Plan 模式工具集细节差异（3.16.4）

**Cline Plan 模式工具集**（`presets.ts` L43-55）：

```typescript
plan: {
    enableReadFiles: true,
    enableSearch: true,
    enableBash: true,            // run_commands 保留
    enableWebFetch: true,
    enableApplyPatch: false,    // 禁用
    enableEditor: false,        // 禁用
    enableSkills: true,
    enableAskQuestion: true,
    enableSubmitAndExit: false, // 禁用（preset 配置）
    enableSpawnAgent: true,
    enableAgentTeams: true,
}
```

**Charles Plan 模式工具集**（`server.py` L362-369 tool_policies）：

```python
tool_policies = {
    "editor": {"enabled": False, "reason": "Plan 模式下禁止编辑文件..."},
    "apply_patch": {"enabled": False, "reason": "Plan 模式下禁止打补丁..."},
    "file_write": {"enabled": False, "reason": "Plan 模式下禁止写文件..."},
}
```

**差异**：

| 工具 | Cline Plan | Charles Plan | 说明 |
|------|-----------|-------------|------|
| editor | ❌ 禁用 | ❌ 禁用 | 一致 |
| apply_patch | ❌ 禁用 | ❌ 禁用 | 一致 |
| file_write | (无此工具) | ❌ 禁用 | Charles 多出的 FileWriteTool 工具，在 plan 模式下也禁用 |
| submit_and_exit | ❌ 禁用（preset） | ✅ 可用 | **Charles 不禁用** |
| run_commands | ✅ 可用 | ✅ 可用 | 一致 |
| ask_question | ✅ 可用 | ✅ 可用 | 一致 |
| skills | ✅ 可用 | ✅ 可用 | 一致 |

**影响**：
- Charles 的 `submit_and_exit` 在 plan 模式可用：LLM 可在 plan 模式直接调用 submit_and_exit 结束 run（但因 `completes_run=True` 会立即结束）。这是合理的——LLM 在 plan 模式若认为无需执行（如纯分析任务），可直接提交分析结果。
- Cline 在 plan preset 中禁用 submit_and_exit，意味着 LLM 必须先切换到 act 模式才能提交。这与 Cline 的"plan 是规划，不提交最终结果"哲学一致。
- Charles 的选择更适合量化场景（plan 模式提交分析报告是常见需求）。

**建议**：保留 Charles 现状。这是场景化适配，非缺陷。

### 差距 6：Mode 状态作用域差异（3.16.2）

**Cline**：mode 是 host 级全局设置（`stateManager.getGlobalSettingsKey("mode")`），所有 task 共享同一 mode。但 `<mode_notice>` 是 session-scoped（`modeSwitchNoticeSessionId` 字段保证 notice 不跨 session 泄露）。

**Charles**：mode 是 session-scoped（`SessionState.mode` per session），不同会话可有不同 mode。

**影响**：
- Cline 的设计假设单 host 单 mode（用户在一个 IDE 实例中只会处于一种工作模式）。
- Charles 的设计假设多会话多 mode（不同会话可能处于不同模式，如一个会话在 plan，另一个在 act）。
- Charles 的设计在多会话场景下更灵活。

**建议**：保留 Charles 现状。Charles 的 session-scoped mode 是功能增强。

---

## 四、nanobot 残留检查

针对 P3.16 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.16 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/plan_mode.py` | **0** | 无 | PLAN_MODE_PROMPT + SwitchToActModeTool + SwitchToPlanModeTool 全无 nanobot 引用 |
| `agent/state.py`（mode/notice 段落） | **0** | 无 | AgentMode / SessionState.mode / ModeSwitchNotice / set_mode / consume_mode_notice / format_mode_switch_notice 全无 nanobot 引用 |
| `agent/tools/constants.py` | **0** | 无 | TOOL_PRESETS + resolve_tool_preset 全无 nanobot 引用 |
| `agent/tools/routing.py` | **0** | 无 | ToolRoutingRule + resolve_tool_routing 全无 nanobot 引用 |
| `agent/runtime.py` | **0** | 无 | _find_completing_tool + _get_current_mode_for_wrap 全无 nanobot 引用 |
| `agent/approval_policy.py` | **0** | 无 | READ_ONLY_TOOLS 含 switch_to_* 无 nanobot 引用 |
| `agent/tools/__init__.py` | **1** | 注释残留 | L2 docstring：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools`（与 P3.1 同一残留） |
| `agent/server.py` | **3** | 注释残留 | L2 docstring：`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`<br>L4：`提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`<br>L28：`对标 nanobot:` |
| `agent/context.py` | **1** | 注释残留 | L275：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` |
| `agent/prompts/charles_system_prompt.py` | **0** | 无 | DEFAULT/YOLO 模板无 nanobot 引用 |

### 4.2 残留分类

#### 注释残留（5 处）

**位置 1**：`agent/tools/__init__.py` L2
```python
"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools
```
**性质**：docstring 历史溯源说明。与 P3.1 同一残留，不在 P3.16 修复范围。

**位置 2-4**：`agent/server.py` L2 / L4 / L28
```python
"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py
...
提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。
...
对标 nanobot:
    - routes/chat.py _sse_generator() + _StreamCollectorHook
```
**性质**：docstring 中的历史溯源说明，标注 SSE 服务端设计同时参考了 Cline server 和历史 nanobot routes/chat.py。不影响 mode 切换、tool_policies、PLAN_MODE_PROMPT 注入等 plan mode 实现逻辑。

**位置 5**：`agent/context.py` L275
```python
extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
```
**性质**：参数 docstring 中的废弃说明，标注 `extra_sections` 参数源自 nanobot 风格，已被 Cline 风格的 `_build_rules` 取代。不影响 `_build_rules` / `_load_mode_prompt` 等 plan mode 提示注入逻辑。

#### 实现逻辑残留（0 处）

P3.16 核心文件中**未发现任何从 nanobot 直接移植的 plan mode 实现逻辑**：

- `PLAN_MODE_PROMPT` 对标 Cline `PLAN_MODE_INSTRUCTIONS`（plan_mode.py L20-22 明确标注）
- `SwitchToActModeTool` 对标 Cline `switch_to_act_mode`（plan_mode.py L21 标注 sdk-session-config-builder.ts L51-80）
- `SwitchToPlanModeTool` 标注"对标 Cline switch_to_plan_mode"但 Cline 无此工具——属注释溯源错误，非 nanobot 残留
- `ModeSwitchNotice` 对标 Cline `createModeSwitchNoticeTracker`（state.py L147-149 标注）
- `_find_completing_tool` 对标 Cline `findCompletingToolMessage`（runtime.py L2045 标注）
- `TOOL_PRESETS` 对标 Cline `ToolPresets`（constants.py L93 标注）
- `ToolRoutingRule` 对标 Cline `model-tool-routing.ts`（routing.py L18-19 标注）

### 4.3 P3.16 范围外但相关的 nanobot 残留

以下文件有 nanobot 残留，但属于其他 P3.x 小阶段的对比范围，不在 P3.16 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|---------------|-----------|
| `agent/tools/exec_tool.py` | 12 | P3.x（exec_tool 专项，已废弃工具） |
| `agent/tools/file_tools.py` | 7 | P3.x（FileWriteTool 专项） |
| `agent/tools/web_tool.py` | 7 | P3.x（WebSearchTool 专项） |
| `agent/session.py` | 2 | P3.x（会话持久化专项） |

这些残留全部为 docstring / 行内注释（如"对标 nanobot ShellTool"、"对标 nanobot filesystem.py L150-176"），属历史溯源标注，不影响 plan mode 实现对比结论。

---

## 五、修复建议

### 建议 1：补齐 switch_to_act_mode 自动续跑 [P1]

**文件**：`agent/server.py`（`_sse_generator` 函数内）
**位置**：`run-finished` 事件处理后
**修改思路**：

1. 在 `agent/runtime.py` 的 `AgentRunResult` 增加 `completing_tool_name: str | None` 字段，记录结束 run 的工具名（若有）
2. `_find_completing_tool` 返回 tool_message 时同时返回 tool_call 的 tool_name
3. `_sse_generator` 检测 `result.completing_tool_name == "switch_to_act_mode"` 且 `result.finish_reason == "completed"` 时：
   - 销毁当前 runtime（旧 mode 工具集）
   - 调用 `_create_runtime` 创建新 runtime（新 mode 工具集）
   - 注入合成用户消息："用户已批准切换到 Act 模式，请立即继续执行已批准的计划。"
   - 调用 `_run_once` 启动续跑 run

**理由**：Cline 的 plan→act 切换是无缝的——LLM 呈现计划后调用 `switch_to_act_mode`，自动续跑执行。Charles 当前需用户手动续跑，体验割裂。

**复杂度**：中。需要修改 `AgentRunResult` 数据结构 + `_sse_generator` 流程 + 增加 `completing_tool_name` 字段。需注意 SSE 事件流不能中断（前端需感知到续跑）。

### 建议 2：补齐会话重建 [P1，与建议 1 同步]

**文件**：`agent/server.py`
**位置**：`_sse_generator` 在切换 mode 后
**修改思路**：

切换 mode 后立即调用 `_create_runtime(session_id=session_id)` 重建 runtime，确保续跑 run 使用新 mode 的 tool_policies 与工具集。

**理由**：当前 Charles 不重建 runtime，若实现建议 1 的 auto-continue，续跑 run 仍用旧 mode 的 tool_policies（editor/apply_patch 被禁用），无法执行计划中的写操作。

### 建议 3：修正 SwitchToPlanModeTool 的对标注释 [P2]

**文件**：`agent/tools/plan_mode.py`
**位置**：L20-22（docstring）+ L167-170（SwitchToPlanModeTool docstring）
**修改**：

当前（L167-170）：
```python
class SwitchToPlanModeTool(BaseTool):
    """切换到 Plan 模式 — 对标 Cline switch_to_plan_mode

    从 Act 模式切换到 Plan 模式，切换后进入只读规划状态。
```

建议：
```python
class SwitchToPlanModeTool(BaseTool):
    """切换到 Plan 模式 — Charles 扩展（Cline 仅有 switch_to_act_mode）

    Cline 不提供 switch_to_plan_mode 工具，plan 模式切换只能由 UI 触发。
    Charles 在量化场景下允许 LLM 主动切回 plan 重新对齐。
```

**理由**：避免误导后续维护者认为 Cline 有此工具。Cline 全局 `grep switch_to_plan_mode` 0 匹配。

### 建议 4：修正 set_mode docstring 与实现的矛盾 [P2]

**文件**：`agent/state.py`
**位置**：L368-375（set_mode docstring）
**修改**：

当前 docstring：
```python
def set_mode(session_id: str, mode: AgentMode) -> AgentMode:
    """设置会话当前模式，返回旧模式

    Stage 36.1 (M1): 若 mode 实际切换，记录 pending notice（对标 Cline tracker.record）。
                     仅 UI 切换应调用本函数记录 notice；模型发起的 switch_to_act_mode
                     不通过本函数记录（其切换通过 continuation prompt 自带 announce）。
    """
```

建议改为：
```python
def set_mode(session_id: str, mode: AgentMode) -> AgentMode:
    """设置会话当前模式，返回旧模式

    Stage 36.1 (M1): 若 mode 实际切换，记录 pending notice（对标 Cline tracker.record）。

    Charles 偏离 Cline：Cline 仅 UI 切换记录 notice，工具切换通过 continuation prompt
    自带 announce；Charles 缺失 auto-continue 机制，所有切换路径都需记录 notice 作为
    唯一 announce 方式。若未来补齐 auto-continue，应将 notice 记录移出本函数，
    仅 UI 路径调用 record_mode_switch。
    """
```

**理由**：消除 docstring 与实现的矛盾，明确标注偏离原因与未来修复方向。

### 建议 5：保留 SwitchToPlanModeTool 工具 [P0 不变]

**理由**：Charles 的 `SwitchToPlanModeTool` 是量化场景下的策略性扩展——LLM 在 act 模式遇到不确定时主动切回 plan 重新对齐。这是 Charles 相对 Cline 的功能增强，不应移除。仅需修正对标注释（建议 3）。

### 建议 6：不强制补齐 yolo 模式 [P3 不修复]

**理由**：
- yolo 模式涉及实盘交易安全，量化场景不默认启用。
- Charles 的 `YOLO_CHARLES_SYSTEM_PROMPT` 模板已存在，若未来需要可通过 `mode === "yolo"` 触发。
- 当前 `AgentMode = Literal["act", "plan"]` 不含 yolo，是设计选择非缺陷。

### 建议 7：清理 server.py 与 context.py 的 nanobot 注释残留 [P2]

**文件**：`agent/server.py` L2/L4/L28 + `agent/context.py` L275
**修改**：将 docstring 中的"对标 nanobot ..."段落移除或改为"对标 Cline ..."。

**理由**：统一为"对标 Cline"溯源风格。不影响功能。

---

## 六、验证方法建议

### 验证方法 1：Plan 模式工具集等价性

确认 Charles plan 模式实际禁用的工具与 Cline preset 一致（除 file_write / submit_and_exit 差异外）：

```powershell
# 确认 server.py 在 plan 模式禁用 editor/apply_patch/file_write
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern 'tool_policies\s*=\s*\{'
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern '"enabled":\s*False'

# 确认 Cline plan preset 禁用 editor/apply_patch
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\presets.ts" -Pattern "enable\w+:\s*false"
```

### 验证方法 2：completes_run 检测算法对齐

确认 Charles `_find_completing_tool` 与 Cline `findCompletingToolMessage` 算法一致：

```powershell
# Charles 算法
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "_find_completing_tool|completes_run"

# Cline 算法
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\agents\src\agent-runtime.ts" -Pattern "findCompletingToolMessage|completesRun"
```

**预期**：两侧都遍历 tool_calls → 检查 lifecycle.completesRun/completes_run → 检查 is_error/isError → 返回 tool_message。

### 验证方法 3：Mode switch notice 语义对齐

确认 Charles `format_mode_switch_notice` 输出与 Cline `formatModeSwitchNotice` 字节级一致：

```powershell
# Charles 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "format_mode_switch_notice|mode_notice"

# Cline 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\format.ts" -Pattern "formatModeSwitchNotice|mode_notice"
```

**预期**：两侧输出格式均为 `<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>`。

### 验证方法 4：Auto-continue 缺失验证

确认 Charles 全局无 `ACT_MODE_CONTINUATION_PROMPT` / `sendTurnWithActModeContinuation` 等价物：

```powershell
# 应全部 0 匹配（验证缺失）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent" -Pattern "ACT_MODE_CONTINUATION|sendTurnWithActModeContinuation|auto_continue|continuation_prompt" -Recurse
```

**预期**：0 匹配，确认 Charles 缺失 auto-continue 机制。

### 验证方法 5：SwitchToPlanModeTool 在 Cline 不存在

确认 Cline 全局无 `switch_to_plan_mode`：

```powershell
# 应 0 匹配
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline" -Pattern "switch_to_plan_mode" -Recurse
```

**预期**：0 匹配，确认 `SwitchToPlanModeTool` 是 Charles 独有扩展。

### 验证方法 6：Mode 切换 API 路径检查

确认 Charles 提供 mode 切换 API（对应 Cline 的 UI toggle）：

```powershell
# 确认 /mode GET/POST 端点存在
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern '@router\.(get|post)\("/mode"\)'
```

### 验证方法 7：nanobot 残留扫描

```powershell
# P3.16 核心文件扫描（应 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\plan_mode.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\routing.py" -Pattern "nanobot" -CaseSensitive:$false

# 相关文件（应有少量注释残留）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
```

### 验证方法 8：Plan 模式提示注入流程

确认 Charles plan 模式提示通过 SystemPromptBuilder 注入：

```powershell
# 确认 _build_rules 注入 MODE_TAG + PLAN_MODE
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "_build_mode_tag_instructions|_load_mode_prompt|PLAN_MODE"
```

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/shared/src/prompt/cline.ts` | L21-23 | `MODE_TAG_INSTRUCTIONS` 常量 |
| `sdk/packages/shared/src/prompt/cline.ts` | L25-45 | `PLAN_MODE_INSTRUCTIONS` 常量（含 run_commands 保留说明） |
| `sdk/packages/shared/src/prompt/cline.ts` | L138-165 | `buildClineSystemPrompt` 注入 effectiveRules |
| `sdk/packages/shared/src/prompt/format.ts` | L5-10 | `formatUserInputBlock` 包装 `<user_input mode="...">` |
| `sdk/packages/shared/src/prompt/format.ts` | L20-32 | `USER_INPUT_MODE_RE` + `parseUserInputMode` |
| `sdk/packages/shared/src/prompt/format.ts` | L41-46 | `formatModeSwitchNotice` 生成 `<mode_notice>` |
| `sdk/packages/shared/src/prompt/format.ts` | L48-51 | `ModeSwitchNotice` 类型 |
| `sdk/packages/shared/src/prompt/format.ts` | L53-80 | `createModeSwitchNoticeTracker` 往返抵消 + 链式保留 from |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L20-109 | `ToolPresets` 5 种预设（act/plan/search/minimal/yolo） |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L116-126 | `resolveToolPresetName` 按 mode 解析预设名 |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L137-158 | `createToolPoliciesWithPreset` yolo 策略构建 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L4-32 | `ToolRoutingRule` 接口（mode 字段） |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L60-75 | `DEFAULT_MODEL_TOOL_ROUTING_RULES` 仅 act 模式规则 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L90-140 | `matchesRule` + `resolveToolRoutingConfig` |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L796-826 | `createSubmitAndExitTool` 含 `completesRun: true` |
| `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` | L79-84 | `filterAvailableTools` 按 toolPolicies 过滤 |
| `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` | L126-161 | `createBuiltinToolsList` 按 mode + preset + routing 装配 |
| `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` | L660-665 | `requiresCompletionTool` 检测 completesRun |
| `sdk/packages/agents/src/agent-runtime.ts` | L557-575 | `getRequiredCompletionToolNames` 收集 completing tools |
| `sdk/packages/agents/src/agent-runtime.ts` | L722-739 | 主循环调用 `findCompletingToolMessage` 检测 run 完成 |
| `sdk/packages/agents/src/agent-runtime.ts` | L1312-1332 | `findCompletingToolMessage` 算法实现 |
| `sdk/packages/shared/src/agent.ts` | L146-156 | `AgentToolDefinition.lifecycle.completesRun` 接口 |
| `apps/cli/src/runtime/interactive/mode.ts` | L5-16 | `InteractiveUiMode` + `PendingModeChange` 类型 |
| `apps/cli/src/runtime/interactive/mode.ts` | L28-29 | `ACT_MODE_CONTINUATION_PROMPT` 常量 |
| `apps/cli/src/runtime/interactive/mode.ts` | L31-68 | `createInteractiveModeSwitchTool` 工厂 |
| `apps/cli/src/runtime/interactive/mode.ts` | L80-108 | `sendTurnWithActModeContinuation` 续跑逻辑 |
| `apps/cli/src/runtime/interactive/mode.ts` | L118-130 | `applyInteractiveModeConfig` 切换 mode + extraTools |
| `apps/vscode/src/sdk/sdk-session-config-builder.ts` | L38-46 | plan 模式额外注册 switch_to_act_mode；act 模式过滤掉 |
| `apps/vscode/src/sdk/sdk-session-config-builder.ts` | L51-80 | `createSwitchToActModeTool` VSCode 版本 |
| `apps/vscode/src/sdk/sdk-mode-coordinator.ts` | L25 | `ACT_MODE_CONTINUATION_PROMPT` 常量 |
| `apps/vscode/src/sdk/sdk-mode-coordinator.ts` | L60-104 | `SdkModeCoordinator` 类 + notice tracker + session scope |
| `apps/vscode/src/sdk/sdk-mode-coordinator.ts` | L131-141 | `applyPendingModeChange` 工具触发时 autoContinue |
| `apps/vscode/src/sdk/sdk-mode-coordinator.ts` | L194-382 | `rebuildSessionForMode` 完整重建流程 |
| `apps/vscode/src/sdk/sdk-mode-coordinator.ts` | L305-307 | 仅 `source === "ui"` 记录 notice |
| `apps/vscode/src/sdk/sdk-mode-coordinator.ts` | L384-404 | `cancelRunningTurnForModeChange` 中止当前 run |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/plan_mode.py` | L1-23 | 模块 docstring（对标说明） |
| `agent/tools/plan_mode.py` | L38-55 | `PLAN_MODE_PROMPT` 中文版 plan 模式契约 |
| `agent/tools/plan_mode.py` | L63-164 | `SwitchToActModeTool` 工具类 |
| `agent/tools/plan_mode.py` | L104-110 | `lifecycle` 属性返回 `ToolLifecycle(completes_run=True)` |
| `agent/tools/plan_mode.py` | L117-164 | `_execute` 直接调用 `set_mode` + `emit_update` |
| `agent/tools/plan_mode.py` | L167-266 | `SwitchToPlanModeTool` 工具类（Charles 扩展） |
| `agent/tools/plan_mode.py` | L274-298 | `get_mode_prompt` / `is_plan_mode` / `is_act_mode` 辅助函数 |
| `agent/state.py` | L58 | `AgentMode = Literal["act", "plan"]` 类型 |
| `agent/state.py` | L98-101 | `SessionState.mode` 字段 |
| `agent/state.py` | L140-162 | `ModeSwitchNotice` dataclass + `_pending_mode_notices` 全局字典 |
| `agent/state.py` | L363-389 | `get_mode` / `set_mode`（含 notice 记录） |
| `agent/state.py` | L398-432 | `_record_mode_switch_locked` 往返抵消 + 链式保留 from |
| `agent/state.py` | L451-464 | `consume_mode_notice` 消费 pending notice |
| `agent/state.py` | L467-485 | `format_mode_switch_notice` 生成 `<mode_notice>` |
| `agent/tools/__init__.py` | L48-112 | `create_default_tools` 注册两个切换工具 |
| `agent/tools/__init__.py` | L109-110 | `SwitchToActModeTool` + `SwitchToPlanModeTool` 始终注册 |
| `agent/tools/constants.py` | L90-140 | `TOOL_PRESETS` 文档化预设（act/plan） |
| `agent/tools/constants.py` | L143-156 | `resolve_tool_preset` 返回预设副本 |
| `agent/tools/routing.py` | L34-53 | `ToolRoutingRule` dataclass |
| `agent/tools/routing.py` | L59-74 | `DEFAULT_MODEL_TOOL_ROUTING_RULES` 仅 act 模式规则 |
| `agent/tools/routing.py` | L108-139 | `resolve_tool_routing` 解析开关字典 |
| `agent/runtime.py` | L506-515 | `_resolve_tool_routing_toggles` 读取 mode |
| `agent/runtime.py` | L740-747 | 主循环检测 `_find_completing_tool` 后结束 run |
| `agent/runtime.py` | L2045-2074 | `_find_completing_tool` 算法实现 |
| `agent/runtime.py` | L2308-2321 | `_find_completing_tool_name` 查找 completing 工具 |
| `agent/runtime.py` | L2850-2865 | `_get_current_mode_for_wrap` 读取当前 mode |
| `agent/server.py` | L340-386 | `_create_runtime` 含 plan 模式 tool_policies |
| `agent/server.py` | L362-369 | Plan 模式禁用 editor/apply_patch/file_write |
| `agent/server.py` | L505-549 | `_build_system_prompt` 调用 SystemPromptBuilder |
| `agent/server.py` | L575-606 | `_sse_generator` 设置 mode + 包装 `<user_input>` |
| `agent/server.py` | L880-906 | `STATUS_NOTICE` / `TOOL_UPDATED` 事件处理 |
| `agent/server.py` | L936-977 | `_handle_status_notice` 处理 `mode_changed` 事件 |
| `agent/server.py` | L1336-1350 | GET `/mode` API |
| `agent/server.py` | L1353-1380 | POST `/mode` API（UI 触发切换） |
| `agent/context.py` | L275 | `extra_sections` 参数废弃注释（nanobot 残留） |
| `agent/context.py` | L454-518 | `_build_rules` 注入 MODE_TAG + PLAN_MODE |
| `agent/context.py` | L836-856 | `_build_mode_tag_instructions` 中文版 MODE_TAG |
| `agent/context.py` | L858-872 | `_load_mode_prompt` 调用 `get_mode_prompt` |
| `agent/prompts/charles_system_prompt.py` | L29-58 | `DEFAULT_CHARLES_SYSTEM_PROMPT` 模板 |
| `agent/prompts/charles_system_prompt.py` | L60-91 | `YOLO_CHARLES_SYSTEM_PROMPT` 模板 |
| `agent/approval_policy.py` | L34-47 | `READ_ONLY_TOOLS` 含 `switch_to_*` |

---

## 八、结论

P3.16 Plan Mode 实现细节对比的核心结论：

1. **核心机制对齐**：mode 枚举、PLAN_MODE 提示、MODE_TAG 说明、mode_notice tracker、`completes_run` 生命周期、`_find_completing_tool` 算法、tool routing 与 mode 联动——这些核心机制在两侧都有对应实现，且 Charles 明确标注了对标 Cline 的具体位置。

2. **5 个关键行为差异**：

   - **Charles 超集**（1 项）：`SwitchToPlanModeTool` 是 Charles 独有扩展，Cline 无此工具。允许 LLM 主动切回 plan 模式，适合量化场景的策略性退避。仅需修正对标注释错误。

   - **Charles 缺失**（3 项）：
     - `switch_to_act_mode` 自动续跑（`ACT_MODE_CONTINUATION_PROMPT`）—— [P1] 用户必须手动续跑，体验割裂
     - Mode 切换后会话重建（`rebuildSessionForMode`）—— [P1] 与 auto-continue 缺失共同修复
     - `PendingModeChange.source` 区分（tool vs ui）—— [P2] 因无 auto-continue 暂不需要

   - **Charles 偏离**（1 项）：`set_mode` 对所有路径记录 notice（包括工具触发），与 Cline "仅 UI 记录" 设计偏离——但因缺失 auto-continue，此偏离是必要的功能补偿。[P2] 修正 docstring 或补齐 auto-continue 后修正实现。

3. **Plan 模式工具集细节差异**：Charles 多禁用 `file_write`（因 Charles 有 FileWriteTool 工具），不禁用 `submit_and_exit`（量化场景需在 plan 模式提交分析报告）。两侧都保留 `run_commands` 仅靠提示词约束为只读。属场景化适配，非缺陷。

4. **Mode 状态作用域**：Cline 是 host 级全局，Charles 是 session 级隔离。Charles 的设计在多会话场景下更灵活，是功能增强。

5. **nanobot 残留**：P3.16 核心文件（`plan_mode.py` / `state.py` mode 段落 / `runtime.py` completes_run 段落 / `tools/routing.py` / `tools/constants.py` / `approval_policy.py`）**全部 0 残留**。残留集中在 `tools/__init__.py` L2 / `server.py` L2/L4/L28 / `context.py` L275，全部为注释残留（docstring 历史溯源），无实现逻辑残留。

6. **`completes_run` 行为对齐度高**：`_find_completing_tool` 算法与 Cline `findCompletingToolMessage` 逐行对齐（遍历 tool_calls → 检查 lifecycle.completes_run → 检查 is_error → 返回 tool_message）。`SwitchToActModeTool` / `SwitchToPlanModeTool` 的 `lifecycle.completes_run=True` 与 Cline `switch_to_act_mode` 的 `completesRun: true` 完全一致。

**整体一致性等级**：**中**。P3.16 范围内有 1 个 P1 级别功能差距（auto-continue 缺失，建议 1+2 同步修复），2 个 P2 级别注释修正（建议 3+4），其余差异为场景化适配或设计选择，无需修复。

**修复优先级**：
- P1（建议 1 + 建议 2）：补齐 auto-continue + 会话重建——是 Charles plan mode 工作流的关键体验差距
- P2（建议 3 + 建议 4 + 建议 7）：修正对标注释 + 修正 docstring 矛盾 + 清理 nanobot 注释
- P3（建议 6）：不强制补齐 yolo 模式
- P0（建议 5）：保留 SwitchToPlanModeTool 不变
