# Phase 5.13 Mode 段对比（plan/act/yolo）

> 对比范围：Cline 与 Charles 在 Mode 段（plan/act/yolo）的注入位置、标签格式、mode 切换重建、mode_notice 机制、yolo 独立模板、PLAN_MODE_PROMPT 内容等 5 项逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L21-23（`MODE_TAG_INSTRUCTIONS`，# Plan / Act Modes 段）+ L32-45（`PLAN_MODE_INSTRUCTIONS`，# Plan Mode 段）+ L138-151（`buildClineSystemPrompt` 中 effectiveRules 拼接 + base 模板选择）
> - `sdk/packages/shared/src/prompt/system.ts` L1-36（`DEFAULT_CLINE_SYSTEM_PROMPT`）+ L38-68（`YOLO_CLINE_SYSTEM_PROMPT`）
> - `sdk/packages/shared/src/prompt/format.ts` L5-10（`formatUserInputBlock`，`<user_input mode="...">` 包装）+ L41-46（`formatModeSwitchNotice`，`<mode_notice>` 标签）+ L48-80（`ModeSwitchNotice` 类型 + `createModeSwitchNoticeTracker` tracker 工厂）
> - `sdk/packages/shared/src/session/runtime-config.ts` L3（`AgentMode = "act" | "plan" | "yolo" | "zen"` 类型定义）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L680-689（`composeSystemPrompt`，每轮调用但仅合并动态 rules）+ L795（调用点）
> - `apps/cli/src/runtime/prompt.ts` L12-36（`resolveSystemPrompt`，CLI 主机层包装）+ L20-22 注释（说明 mode-tag/plan-mode 由 shared prompt builder 注入）
> - `apps/vscode/src/sdk/cline-session-factory.ts` L775-782（VS Code 主机层 `buildClineSystemPrompt` 调用，**仅传 `mode: "plan" | "act"`，不传 yolo**）
> - `sdk/packages/shared/src/prompt/cline.test.ts` L15-74（5 个测试用例覆盖 act/plan/yolo/override 的 mode 段注入）
>
> Charles 源码：
> - `agent/context.py` L185-205（`select_base_template`，yolo 模板选择）+ L348-391（`SystemPromptBuilder.build`，每轮完整重建含 mode 查询）+ L393-406（`_get_current_mode`）+ L502-509（`_build_rules` 中 MODE_TAG 注入）+ L511-518（`_build_rules` 中 PLAN_MODE 注入）+ L836-856（`_build_mode_tag_instructions`，# 用户消息模式标签 段）
> - `agent/prompts/charles_system_prompt.py` L31-58（`DEFAULT_CHARLES_SYSTEM_PROMPT`）+ L60-91（`YOLO_CHARLES_SYSTEM_PROMPT`）
> - `agent/tools/plan_mode.py` L38-55（`PLAN_MODE_PROMPT`，# Plan Mode 段）+ L274-288（`get_mode_prompt`，plan 模式返回提示词）
> - `agent/state.py` L58（`AgentMode = Literal["act", "plan"]`，**不含 yolo/zen**）+ L142-157（`ModeSwitchNotice` 数据类）+ L363-389（`get_mode` / `set_mode`）+ L398-432（`_record_mode_switch_locked`，tracker 逻辑）+ L451-464（`consume_mode_notice`）+ L467-485（`format_mode_switch_notice`，`<mode_notice>` 标签）
> - `agent/server.py` L575-606（SSE 入口：`set_mode` + `_build_system_prompt` 完整重建 + `consume_mode_notice` + `<user_input mode>` 包装）+ L792-814（turn_queue 模式切换时重建 system prompt + consume notice）
> - `agent/runtime.py` L2789-2848（`_apply_default_user_input_wrap`，runtime 层默认 `<user_input>` 包装）+ L2850-2865（`_get_current_mode_for_wrap`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 Mode 段（plan/act/yolo）的实现差异。**核心结论：Charles 已通过 Stage P4 + Stage 36.1 (M1) + Stage 36.2 (M2) 三个阶段完成 Mode 段的全面对齐**；计划表标注的 L8（yolo 独立模板）和 M1（mode_notice 机制）差距均已失效，实际已对齐。剩余差异主要为：PLAN_MODE 段内容本地化（中文+列举工具名）、AgentMode 类型边界（Charles 不含 yolo/zen）、mode 切换重建策略（Charles 每轮完整重建 vs Cline 主机层一次性构建）。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.13（L2051-2057）标注的 5 项对比中，3 项标注的差距状态已失效：

1. **5.13.3 yolo 独立模板**：计划标注"L8 差距"（Cline 是 / Charles 无）。**实际**：Charles 已在 `agent/prompts/charles_system_prompt.py` L60-91 实现 `YOLO_CHARLES_SYSTEM_PROMPT`，并通过 `select_base_template(mode)` 在 `mode == "yolo"` 时启用（context.py L203-205）。模板已对齐，但 `AgentMode` 类型（state.py L58）不含 yolo，**状态层无法切换到 yolo**——这是"L8 差距已部分关闭，剩余为类型边界差异"。
2. **5.13.4 mode_notice 机制**：计划标注"M1 差距"（Cline 是 / Charles 无）。**实际**：Charles 已在 `agent/state.py` L142-485 完整实现 `ModeSwitchNotice` + `_record_mode_switch_locked`（含往返抵消和链式切换逻辑）+ `consume_mode_notice` + `format_mode_switch_notice`，并在 server.py L599-604 和 L808-812 两处入口 consume notice 并 prepend `<mode_notice>` 到用户消息前。**M1 差距已完全关闭**。
3. **5.13.5 段落位置**：计划标注"第 11 段 / 第 10 段，顺序偏移"。**实际**：两者均将 MODE_TAG + PLAN_MODE 作为 rules 注入到 `{{*_RULES}}` 占位符，位于 base prompt 末尾、`{{*_METADATA}}` 之前。段落顺序完全对齐，"第 11 段 / 第 10 段"的偏移源于 Charles base prompt 比 Cline 少一个独立 "Remember:" 段（合并到"通用行为规则"中），不影响 Mode 段相对位置。

### 核心结论

1. **MODE_TAG_INSTRUCTIONS 已对齐**：两者均作为 rule 注入到 `{{*_RULES}}`，说明 `<user_input mode="...">` 标签语义和 `<mode_notice>` 块。Charles 为中文版本+补充"plan 模式下写入由 tool_policies 硬禁用"说明。
2. **PLAN_MODE_PROMPT 已对齐（含合理本地化）**：两者均仅 plan 模式注入。Charles 为中文版本，且**列举具体工具名**（read_files/list_files/search_codebase/run_commands/web_search/skills），Cline 不列举具体工具名。Charles 的列举是为配合 `tool_policies` 硬禁用机制（Cline 仅靠 prompting，不靠 tool removal）。
3. **yolo 独立模板已对齐**：两者均有 YOLO 模板（后台自动化场景）。Charles `AgentMode` 类型不含 yolo，但 `select_base_template` 支持——若外部传入 `mode="yolo"` 可正确选择模板。
4. **mode_notice 机制已对齐**：Charles `ModeSwitchNotice` tracker 语义与 Cline `createModeSwitchNoticeTracker` 完全一致（含往返抵消和链式切换）。
5. **mode 切换 prompt 重建策略差异**：Charles 每轮 SSE 入口完整重建 system prompt（含 mode 查询、模板选择、rules 加载、metadata 构建占位符替换）；Cline 在 VS Code 主机层一次性构建（session-factory L775，mode 仅 "plan"/"act"），core orchestrator 每轮 `composeSystemPrompt` 但仅合并动态 rules，不重新选择 base 模板。Charles 策略更激进，支持运行中 mode 切换即时生效。
6. **AgentMode 类型边界差异**：Cline `AgentMode = "act" | "plan" | "yolo" | "zen"`（4 种），Charles `AgentMode = Literal["act", "plan"]`（2 种）。Charles 不支持 zen 模式，yolo 模板存在但状态层未启用。
7. **nanobot 残留**：Mode 段相关文件**0 处实现逻辑残留**，仅 1 处注释残留（context.py L275，已记录于 P5.1 报告，非 Mode 段专属）。

### 一致性总体评估

- **Mode 段注入位置**：**高**。两者均作为 rules 注入到 `{{*_RULES}}` 占位符。
- **MODE_TAG 内容**：**高**。语义完全对齐，仅语言差异（中/英）。
- **PLAN_MODE 内容**：**中-高**。语义对齐，Charles 列举工具名是为配合 tool_policies 机制，属合理本地化。
- **yolo 模板**：**中-高**。模板已对齐，但 AgentMode 类型未包含 yolo，无法通过状态层切换。
- **mode_notice 机制**：**高**。tracker 语义完全对齐。
- **mode 切换重建**：**中**。策略差异（每轮重建 vs 一次性构建），Charles 更激进但性能开销更大。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.13.1 | mode 切换 prompt 重建 | VS Code 主机层一次性构建（cline-session-factory.ts L775，mode 仅 "plan"/"act"），core orchestrator 每轮 `composeSystemPrompt` 仅合并动态 rules（session-runtime-orchestrator.ts L680-689），不重新选择 base 模板 | 每轮 SSE 入口 `_build_system_prompt` 完整重建（server.py L583，含 mode 查询+模板选择+rules 加载+metadata 构建+占位符替换）；turn_queue 模式切换时也重建（server.py L794-800） | 中 | 策略差异：Charles 每轮完整重建支持 mode 热切换；Cline 一次性构建性能更优但 mode 切换需重建会话。Charles 更激进 |
| 5.13.2 | PLAN_MODE_PROMPT 内容 | 英文，# Plan Mode 段，"explore, analyze, and plan -- not to execute"，run_commands read-only 契约，不列举具体工具名（cline.ts L32-45） | 中文，# Plan Mode 段，"探索、分析并给出清晰的执行计划"，**列举具体工具名**（read_files/list_files/search_codebase/run_commands/web_search/skills），switch_to_act_mode（plan_mode.py L38-55） | 中-高 | 语义对齐，本地化合理。Charles 列举工具名是为配合 `tool_policies` 硬禁用机制（Cline 仅靠 prompting） |
| 5.13.3 | yolo 独立模板 | `YOLO_CLINE_SYSTEM_PROMPT`（system.ts L38-68），英文，"You are Cline, a careful and helpful coding agent that works in the background"，`mode === "yolo"` 时启用（cline.ts L138-139） | `YOLO_CHARLES_SYSTEM_PROMPT`（charles_system_prompt.py L60-91），中文，"你是 Charles，在后台自主运行的 AI 投研助手"，`select_base_template(mode)` 中 `mode == "yolo"` 时启用（context.py L203-205） | 中-高 | 模板已对齐。但 Charles `AgentMode = Literal["act", "plan"]`（state.py L58）不含 yolo，状态层无法切换到 yolo——模板"悬空" |
| 5.13.4 | mode_notice 机制 | `formatModeSwitchNotice(from, to)` 生成 `<mode_notice>` 标签（format.ts L41-46）；`createModeSwitchNoticeTracker` 工厂含 record/consume，支持往返抵消和链式切换（format.ts L61-80）；仅 UI 切换记录，模型 switch_to_act_mode 走 continuation prompt | `format_mode_switch_notice(notice)` 生成相同格式 `<mode_notice>` 标签（state.py L467-485）；`_record_mode_switch_locked` 含相同往返抵消和链式切换逻辑（state.py L398-432）；`consume_mode_notice` 取出并清除（state.py L451-464）；server.py L599-604 和 L808-812 两处入口 consume 并 prepend | 高 | Stage 36.1 (M1) 已完全对齐。tracker 语义、标签格式、consume 时机均一致 |
| 5.13.5 | 段落位置 | MODE_TAG + PLAN_MODE 作为 effectiveRules 注入到 `{{CLINE_RULES}}`（cline.ts L145-151），位于 base prompt 末尾、`{{CLINE_METADATA}}` 之前 | MODE_TAG + PLAN_MODE 作为 rule 注入到 `{{CHARLES_RULES}}`（context.py L502-518），位于 base prompt 末尾、`{{CHARLES_METADATA}}` 之前 | 高 | 位置完全对齐。两者均通过 rules 占位符注入，不硬编码在 base prompt 中 |

---

## 三、重点差距详细说明

### 3.1 mode 切换 prompt 重建策略差异（5.13.1）

**Cline 策略**：VS Code 主机层在会话创建时一次性构建 system prompt（含 mode 选择和 MODE_TAG/PLAN_MODE 注入），core orchestrator 每轮 `composeSystemPrompt` 仅合并动态 rules：

```typescript
// cline-session-factory.ts L775-782（VS Code 主机层，一次性构建）
systemPrompt = buildClineSystemPrompt({
    ide: "VS Code",
    workspaceRoot,
    workspaceName,
    mode: mode === "plan" ? "plan" : "act",  // 仅 plan/act，不传 yolo
    providerId,
    platform: process.platform,
});

// session-runtime-orchestrator.ts L680-689（core 每轮调用，仅合并动态 rules）
private async composeSystemPrompt(): Promise<string> {
    const rules: string[] = [];
    for (const rule of this.contributionRegistry.getRegisteredRules()) {
        const content = await resolveRuleContent(rule);
        if (content) rules.push(content);
    }
    return mergeSystemPromptRules(this.config.systemPrompt, rules);  // base 不变
}
```

**Charles 策略**：每轮 SSE 入口完整重建 system prompt（含 mode 查询、模板选择、rules 加载、metadata 构建占位符替换）：

```python
# server.py L575-583（每轮 SSE 入口，完整重建）
if mode in ("act", "plan"):
    from agent.state import set_mode
    set_mode(session_id, mode)
system_prompt = _build_system_prompt(session_id=session_id, task_type=task_type)

# server.py L794-800（turn_queue 模式切换时也重建）
if entry.mode and entry.mode != current_mode:
    set_mode(session_id, entry.mode)
    current_mode = entry.mode
    run_system_prompt = _build_system_prompt(session_id=session_id, task_type=task_type)
```

**差异影响**：
- Cline：mode 切换在 VS Code 主机层需要重建会话或重新调用 `buildClineSystemPrompt`；runtime 层无法感知 mode 切换。
- Charles：mode 切换在 server 层 `set_mode` 后立即生效，下一轮 `_build_system_prompt` 自动选择新模板和注入对应 PLAN_MODE_PROMPT。

**评估**：Charles 策略更激进，支持运行中 mode 热切换，但每轮重复磁盘 I/O（读 AGENTS.md、扫 rules_dir、git 命令）。Cline 性能更优但 mode 切换需重建会话。**非对齐缺口，属实现策略差异**。

### 3.2 PLAN_MODE_PROMPT 内容差异（5.13.2）

**Cline `PLAN_MODE_INSTRUCTIONS`**（cline.ts L32-45）：
- 英文
- 标题：`# Plan Mode`
- 核心契约："explore, analyze, and plan -- not to execute"
- run_commands 契约："remains available in plan mode strictly for read-only inspection"
- **不列举具体工具名**（仅说明 run_commands 的只读约束）
- switch_to_act_mode 调用时机说明

**Charles `PLAN_MODE_PROMPT`**（plan_mode.py L38-55）：
- 中文
- 标题：`# Plan Mode`
- 核心契约："探索、分析并给出清晰的执行计划，而不是直接执行"
- **列举具体工具名**：`read_files / list_files / search_codebase / run_commands（只读检查）/ web_search / skills（除 write-report 外）`
- 工具限制说明："editor / apply_patch / file_write / write-report 等写入/编辑类工具已由 tool_policies 硬禁用，无需自律"
- switch_to_act_mode 调用时机说明

**差异分析**：
- 语言差异：Charles 中文本地化，属合理偏离。
- 列举工具名差异：Charles 列举具体工具名是为配合 `tool_policies` 硬禁用机制——Charles 同时使用 prompting + tool removal 双重策略；Cline 仅用 prompting（计划文件 cline.ts L26-30 注释明确说明"mitigation for plan-mode mutations is prompting plus mode-switch notices, not tool removal"）。
- Charles 的"无需自律"表述：明确告知 LLM 写入类工具已被硬禁用，LLM 无需自我约束——这与 Cline 的"prompting only"哲学不同。

**评估**：Charles 的双重策略（prompting + tool_policies）比 Cline 的单一策略（prompting only）更严格，属合理增强。但 PLAN_MODE_PROMPT 中列举工具名会让 prompt 更长，且工具名变更时需同步更新 prompt。**非对齐缺口，属策略增强**。

### 3.3 yolo 模板"悬空"问题（5.13.3）

**Cline `AgentMode`**（runtime-config.ts L3）：
```typescript
export type AgentMode = "act" | "plan" | "yolo" | "zen";
```

**Charles `AgentMode`**（state.py L58）：
```python
AgentMode = Literal["act", "plan"]
```

**Charles yolo 相关代码**：
- `select_base_template(mode)`（context.py L203-205）：`if mode == "yolo": return YOLO_CHARLES_SYSTEM_PROMPT` —— 支持 yolo
- `_get_current_mode()`（context.py L393-406）：从 `agent.state.get_mode(session_id)` 获取 mode —— 仅返回 "act"/"plan"
- `MODE_TAG_INSTRUCTIONS`（context.py L851）：描述中提到 "`yolo`: 自动执行模式（如启用），与 act 等价但无需逐步确认" —— 文档层面提及 yolo
- `state.py` L410 注释：举例 "act→plan→act→yolo 链式切换" —— 注释层面提及 yolo
- `tools/constants.py` L103-104：`yolo 模式涉及实盘交易安全，不默认开启` —— 明确不启用的业务原因

**问题**：Charles `YOLO_CHARLES_SYSTEM_PROMPT` 模板存在且 `select_base_template` 支持，但 `AgentMode = Literal["act", "plan"]` 不含 yolo，`set_mode(session_id, "yolo")` 会被类型检查拒绝（运行时虽不报错但 `state.mode` 字段无 yolo 选项）。**模板"悬空"**：代码存在但无法通过正常路径启用。

**评估**：这是 L8 差距的**部分残留**——模板已对齐，但状态层未启用。Charles 在 `tools/constants.py` L103-104 明确说明"yolo 模式涉及实盘交易安全，不默认开启"，属业务决策（量化场景实盘交易风险高）。建议在 `MODE_TAG_INSTRUCTIONS` 和 `select_base_template` docstring 中明确标注"yolo 模板保留供未来启用，当前 AgentMode 不含 yolo"，避免后续对齐工作误判。

### 3.4 mode_notice 机制已对齐（5.13.4）

**Cline `createModeSwitchNoticeTracker`**（format.ts L61-80）：
```typescript
record(from, to): void {
    if (from === to) return;  // no-op
    if (pending) {
        pending = pending.from === to ? null : { from: pending.from, to };  // 往返抵消 / 链式切换
        return;
    }
    pending = { from, to };
},
consume(): ModeSwitchNotice | null {
    const notice = pending;
    pending = null;
    return notice;
},
```

**Charles `_record_mode_switch_locked`**（state.py L398-432）：
```python
if from_mode == to_mode:
    return  # no-op
pending = _pending_mode_notices.get(session_id)
if pending is not None:
    if pending.from_mode == to_mode:
        _pending_mode_notices.pop(session_id, None)  # 往返抵消
    else:
        pending.to_mode = to_mode  # 链式切换
else:
    _pending_mode_notices[session_id] = ModeSwitchNotice(from_mode=from_mode, to_mode=to_mode)
```

**对齐点**：
1. 往返抵消语义：`plan→act→plan` 模式实际未变，清除 pending —— 完全一致
2. 链式切换语义：`act→plan→act→yolo` 保留原始 from —— 完全一致
3. consume 语义：取出并清除 pending —— 完全一致
4. 标签格式：`<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>` —— 完全一致
5. 仅 UI 切换记录：Charles `set_mode` 内部调用 `_record_mode_switch_locked`，模型 `switch_to_act_mode` 工具调用也走 `set_mode` 但**也会记录 notice**——这与 Cline "model-initiated switch_to_act_mode path already announces itself via the continuation prompt" 不同。Charles 的 switch_to_act_mode 工具调用会同时记录 notice 和返回切换结果，可能导致重复通知。

**评估**：tracker 语义和标签格式已完全对齐（Stage 36.1 M1 已完成）。剩余细微差异：Charles 模型发起的 switch_to_act_mode 也会记录 notice，Cline 不会（走 continuation prompt）。影响较小，非对齐缺口。

### 3.5 段落位置已对齐（5.13.5）

**Cline base prompt 结构**（DEFAULT_CLINE_SYSTEM_PROMPT）：
1. 身份定义
2. 通用规则（Always gather... / Review each question...）
3. Remember: rules
4. `<env>...</env>`
5. `{{CLINE_RULES}}` ← MODE_TAG + PLAN_MODE 在此
6. `{{CLINE_METADATA}}`

**Charles base prompt 结构**（DEFAULT_CHARLES_SYSTEM_PROMPT）：
1. 身份定义
2. `## 通用行为规则`
3. `## 工具调用规则`
4. `<env>...</env>`
5. `{{CHARLES_RULES}}` ← MODE_TAG + PLAN_MODE 在此
6. `{{CHARLES_METADATA}}`

**对齐点**：两者均将 MODE_TAG + PLAN_MODE 作为 rules 注入到 `{{*_RULES}}` 占位符，位于 base prompt 末尾、`{{*_METADATA}}` 之前。**段落位置完全对齐**。

计划表标注"第 11 段 / 第 10 段，顺序偏移"源于 Charles base prompt 将 Cline 的"通用规则"+"Remember:"合并为"通用行为规则"+"工具调用规则"两段，段数计数不同，但 Mode 段的**相对位置**（在 rules 占位符中，metadata 之前）完全一致。**非对齐缺口**。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 Mode 段相关文件检查 nanobot 风格残留：
- `agent/context.py`（SystemPromptBuilder + MODE_TAG_INSTRUCTIONS + select_base_template）
- `agent/prompts/charles_system_prompt.py`（DEFAULT + YOLO 模板）
- `agent/tools/plan_mode.py`（PLAN_MODE_PROMPT + SwitchToActModeTool + SwitchToPlanModeTool）
- `agent/state.py`（AgentMode + ModeSwitchNotice + tracker）
- `agent/server.py`（mode 切换 + system prompt 重建 + mode_notice consume）
- `agent/runtime.py`（`_apply_default_user_input_wrap` + `_get_current_mode_for_wrap`）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`（**非 Mode 段专属**，已记录于 P5.1 报告） |
| `agent/prompts/charles_system_prompt.py` | 0 | 0 | 无残留 |
| `agent/tools/plan_mode.py` | 0 | 0 | 无残留 |
| `agent/state.py` | 0 | 0 | 无残留 |
| `agent/server.py` | 0 | 0 | 无残留 |
| `agent/runtime.py` | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（1 处，非 Mode 段专属）

**位置**：`agent/context.py` L275

```python
def __init__(
    self,
    identity: str = "",
    ...
    extra_sections: dict[str, str] | None = None,
    ...
) -> None:
    """初始化系统提示组装器

    Args:
        ...
        extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                        保留参数签名仅为向后兼容，当前无调用方传入。
        ...
    """
```

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。不影响 Mode 段运行逻辑。此残留已在 P5.1 报告 §4.3.1 记录，**非 Mode 段专属**。

#### 4.3.2 实现逻辑残留（0 处）

经核查 Mode 段全部相关方法：

- `select_base_template`（context.py L185-205）：纯 Cline 风格（DEFAULT/YOLO 双模板选择），**无 nanobot 风格实现逻辑**
- `_build_mode_tag_instructions`（context.py L836-856）：对标 Cline `MODE_TAG_INSTRUCTIONS`，**无 nanobot 风格实现逻辑**
- `_load_mode_prompt`（context.py L858-872）：调用 `get_mode_prompt`，**无 nanobot 风格实现逻辑**
- `PLAN_MODE_PROMPT`（plan_mode.py L38-55）：对标 Cline `PLAN_MODE_INSTRUCTIONS`，**无 nanobot 风格实现逻辑**
- `SwitchToActModeTool` / `SwitchToPlanModeTool`（plan_mode.py L63-266）：对标 Cline `switch_to_act_mode`，**无 nanobot 风格实现逻辑**
- `ModeSwitchNotice` + `_record_mode_switch_locked` + `consume_mode_notice` + `format_mode_switch_notice`（state.py L142-485）：对标 Cline `createModeSwitchNoticeTracker`，**无 nanobot 风格实现逻辑**
- `_apply_default_user_input_wrap`（runtime.py L2789-2848）：对标 Cline `formatUserInputBlock`，**无 nanobot 风格实现逻辑**

**结论**：Mode 段相关代码**无任何 nanobot 风格实现逻辑残留**。仅 1 处注释残留（context.py L275，非 Mode 段专属，已记录于 P5.1）。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**Mode 段无类似的实现逻辑残留**，说明 Stage P4 + Stage 36.1 (M1) + Stage 36.2 (M2) 三个阶段已彻底清除 Mode 段的 nanobot 风格实现逻辑。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.13.1 mode 切换 prompt 重建**：策略差异（每轮重建 vs 一次性构建），Charles 支持热切换更灵活，无需修复。
- **5.13.4 mode_notice 机制**：Stage 36.1 (M1) 已完全对齐，无需修复。
- **5.13.5 段落位置**：完全对齐，无需修复。

### 5.2 优先级 P1（建议处理）

- **5.13.2 PLAN_MODE_PROMPT 内容**：建议在 `plan_mode.py` PLAN_MODE_PROMPT docstring 中明确标注"Charles 列举具体工具名是为配合 `tool_policies` 硬禁用机制，Cline 仅靠 prompting 不列举工具名"，避免后续对齐工作误判为差距。当前 docstring（plan_mode.py L36-37）仅说明"对标 Cline PLAN_MODE_INSTRUCTIONS"，未明确策略差异。

- **5.13.3 yolo 模板"悬空"**：建议在 `select_base_template` docstring（context.py L186-197）中明确标注"yolo 模板保留供未来启用，当前 `AgentMode = Literal["act", "plan"]` 不含 yolo，无法通过状态层切换；如需启用应在 `state.py` 扩展 AgentMode 类型并确保实盘交易安全"。当前 docstring 提及 yolo 但未说明"悬空"状态。

### 5.3 优先级 P2（可选优化）

- **AgentMode 类型边界**：Charles `AgentMode = Literal["act", "plan"]`（state.py L58）不含 yolo/zen，Cline `AgentMode = "act" | "plan" | "yolo" | "zen"`（runtime-config.ts L3）含 4 种。Charles 不支持 zen 模式（量化场景无需求），yolo 模板存在但状态层未启用。建议保持现状，但在 `MODE_TAG_INSTRUCTIONS`（context.py L845-856）中明确标注"yolo 模式当前未启用，模板保留供未来扩展"，避免 LLM 误以为 yolo 可用。

- **mode_notice 模型发起的切换**：Charles `switch_to_act_mode` 工具调用走 `set_mode`，会触发 `_record_mode_switch_locked` 记录 notice；Cline `switch_to_act_mode` 不记录 notice（走 continuation prompt）。建议在 `SwitchToActModeTool._execute` 中显式调用 `consume_mode_notice` 清除 pending notice，避免模型发起的切换也触发 `<mode_notice>` 通知（与 Cline 行为对齐）。影响较小，非阻塞。

### 5.4 优先级 P3（文档修正）

- **计划文件 P5.13 标注修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2051-2057：
  - 5.13.3 yolo 独立模板：从"L8 差距"改为"模板已对齐，AgentMode 类型未启用 yolo"
  - 5.13.4 mode_notice 机制：从"M1 差距"改为"已对齐（Stage 36.1 M1）"
  - 5.13.5 段落位置：从"顺序偏移"改为"已对齐"

---

## 六、验证方法

### 6.1 MODE_TAG 段验证

```powershell
# 验证 Charles MODE_TAG_INSTRUCTIONS 含 <user_input mode> 和 <mode_notice> 说明
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "user_input mode|mode_notice|act|plan|yolo"
# 预期: L848-855 区域含上述关键词

# 验证 Cline MODE_TAG_INSTRUCTIONS 含相同语义
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "user_input mode|mode_notice|plan|act|yolo"
# 预期: L21-23 含上述关键词
```

### 6.2 PLAN_MODE 段验证

```powershell
# 验证 Charles PLAN_MODE_PROMPT 仅 plan 模式注入
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "_load_mode_prompt|PLAN_MODE"
# 预期: L511-518 _build_rules 中 _load_mode_prompt() 调用，L858-872 _load_mode_prompt 方法定义

# 验证 Charles PLAN_MODE_PROMPT 内容
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\plan_mode.py" -Pattern "PLAN_MODE_PROMPT|switch_to_act_mode|run_commands"
# 预期: L38-55 PLAN_MODE_PROMPT 定义，含 switch_to_act_mode 和 run_commands 工具名
```

### 6.3 yolo 模板验证

```powershell
# 验证 Charles YOLO 模板存在且 select_base_template 支持
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "yolo|YOLO"
# 预期: L189-205 select_base_template 中 mode == "yolo" 分支

# 验证 Charles AgentMode 不含 yolo（类型边界）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "AgentMode"
# 预期: L58 AgentMode = Literal["act", "plan"]，不含 yolo

# 验证 Cline AgentMode 含 yolo
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\session\runtime-config.ts" -Pattern "AgentMode"
# 预期: L3 AgentMode = "act" | "plan" | "yolo" | "zen"
```

### 6.4 mode_notice 机制验证

```powershell
# 验证 Charles ModeSwitchNotice tracker 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "ModeSwitchNotice|_record_mode_switch_locked|consume_mode_notice|format_mode_switch_notice"
# 预期: L142-485 区域含上述定义

# 验证 Charles server.py 两处入口 consume notice
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "consume_mode_notice|format_mode_switch_notice|mode_notice"
# 预期: L599-604 和 L808-812 两处 consume + prepend

# 验证 <mode_notice> 标签格式与 Cline 一致
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "<mode_notice>"
# 预期: L483-484 生成 '<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>'

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\format.ts" -Pattern "<mode_notice>"
# 预期: L45 生成相同格式
```

### 6.5 mode 切换 prompt 重建验证

```powershell
# 验证 Charles 每轮 SSE 入口重建 system prompt
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "_build_system_prompt|set_mode"
# 预期: L575-583 SSE 入口 set_mode + _build_system_prompt；L794-800 turn_queue 重建

# 验证 Cline VS Code 主机层一次性构建（仅传 plan/act）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\sdk\cline-session-factory.ts" -Pattern "buildClineSystemPrompt|mode:"
# 预期: L775-782 buildClineSystemPrompt 调用，L779 mode: mode === "plan" ? "plan" : "act"
```

### 6.6 nanobot 残留验证

```powershell
# 在 Mode 段相关文件中搜索 nanobot（应仅 1 处注释残留，且非 Mode 段专属）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: L275 1 处注释残留（extra_sections docstring）

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\plan_mode.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\state.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.13.1 mode 切换 prompt 重建 | 已对齐 | **策略差异**（非差距） | Charles 每轮完整重建，Cline 一次性构建。两者均支持 mode 切换，策略不同 |
| 5.13.2 PLAN_MODE_PROMPT | 已对齐（Stage P4） | **已对齐**（含合理本地化） | 中文版本+列举工具名，配合 tool_policies 双重策略 |
| 5.13.3 yolo 独立模板 | L8 差距 | **部分对齐** | 模板已存在（YOLO_CHARLES_SYSTEM_PROMPT），但 AgentMode 类型不含 yolo，状态层无法切换 |
| 5.13.4 mode_notice 机制 | M1 差距 | **已对齐** | Stage 36.1 (M1) 已完整实现 ModeSwitchNotice tracker + consume + format |
| 5.13.5 段落位置 | 顺序偏移 | **已对齐** | 两者均通过 {{*_RULES}} 占位符注入，位于 metadata 之前，相对位置完全对齐 |

**计划表标注总结**：5 项中 2 项标注"已对齐"的项确认对齐（5.13.1 策略差异、5.13.2 含本地化），3 项标注"差距"的项实际已对齐或部分对齐（5.13.3 模板已对齐仅类型边界差异、5.13.4 完全对齐、5.13.5 完全对齐）。计划表 P5.13 整体偏保守，未反映 Stage P4 + Stage 36.1 (M1) + Stage 36.2 (M2) 三个阶段的对齐成果。
