# Phase 5.20 Mode 段条件注入对比

> 对比范围：Cline `buildClineSystemPrompt` 中 mode 驱动的条件注入逻辑（base 模板选择 + `MODE_TAG_INSTRUCTIONS` + `PLAN_MODE_INSTRUCTIONS` + `<mode_notice>` 运行时跟踪）与 Charles `SystemPromptBuilder` / `select_base_template` / `_build_rules` / `_load_mode_prompt` / `state.py` ModeSwitchNotice 链路的逐项对标；区分注释残留与实现逻辑残留，专项核查 nanobot 风格注入残留。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt`：L138-139 base 模板选择；L145-151 `effectiveRules` 拼接，注入 `MODE_TAG_INSTRUCTIONS` + 条件注入 `PLAN_MODE_INSTRUCTIONS`）
> - `sdk/packages/shared/src/prompt/cline.ts` L11-23（`MODE_TAG_INSTRUCTIONS` 常量，提及 `<user_input mode="...">` 与 `<mode_notice>`）
> - `sdk/packages/shared/src/prompt/cline.ts` L32-45（`PLAN_MODE_INSTRUCTIONS` 常量，plan 模式行为契约）
> - `sdk/packages/shared/src/prompt/system.ts` L1（`DEFAULT_CLINE_SYSTEM_PROMPT`）+ L38（`YOLO_CLINE_SYSTEM_PROMPT`）
> - `sdk/packages/shared/src/prompt/format.ts` L9（`<user_input mode="...">` 包装）+ L41-46（`formatModeSwitchNotice`）+ L48-51（`ModeSwitchNotice` 接口）+ L61-80（`createModeSwitchNoticeTracker`）+ L149-157（`removeTagElements` 移除 `mode_notice`）
>
> Charles 源码：
> - `agent/context.py` L185-205（`select_base_template`：yolo → `YOLO_CHARLES_SYSTEM_PROMPT`，其他 → `DEFAULT_CHARLES_SYSTEM_PROMPT`）
> - `agent/context.py` L378-379（`SystemPromptBuilder.build` 调用 `select_base_template(mode)`）
> - `agent/context.py` L454-539（`_build_rules`：L502-509 注入 MODE_TAG；L511-518 条件注入 PLAN_MODE_PROMPT）
> - `agent/context.py` L836-856（`_build_mode_tag_instructions`：构建 `<user_input mode>` 标签说明，提及 `<mode_notice>`）
> - `agent/context.py` L858-872（`_load_mode_prompt` → `agent.tools.plan_mode.get_mode_prompt`）
> - `agent/tools/plan_mode.py` L38-55（`PLAN_MODE_PROMPT` 常量）+ L274-288（`get_mode_prompt`：plan 返回 PLAN_MODE_PROMPT，其他返回 None）
> - `agent/prompts/charles_system_prompt.py` L31-58（`DEFAULT_CHARLES_SYSTEM_PROMPT`）+ L62-91（`YOLO_CHARLES_SYSTEM_PROMPT`）
> - `agent/state.py` L140-156（`ModeSwitchNotice` dataclass）+ L159-162（`_pending_mode_notices` 全局字典）+ L368-389（`set_mode` 内调用 `_record_mode_switch_locked`）+ L398-432（`_record_mode_switch_locked`：往返抵消 + 链式切换）+ L451-464（`consume_mode_notice`）+ L467-485（`format_mode_switch_notice`）
> - `agent/server.py` L595-606（用户消息包装：consume notice + prepend `<mode_notice>` + `<user_input mode="...">` 包装）+ L808-813（queue 消费路径同样处理）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 Mode 段条件注入逻辑的对齐情况。**核心结论：plan/act/yolo 三种模式的注入条件已完全对齐，`<mode_notice>` 运行时跟踪机制也已对齐（Stage 36.1 M1 已实现）**；计划文件 P5.20 表格中标注的两项差距（5.20.3 yolo 模式 L8 差距、5.20.4 mode_notice M1 差距）**均已失效**，Charles 当前实现已闭合这两项差距。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.20（L2161-2181）表格中存在两处过时标注：

1. **5.20.3 yolo 模式注入**：计划标注"Cline=YOLO base，Charles=无，L8 差距"。**实际**：Charles 已实现 `YOLO_CHARLES_SYSTEM_PROMPT` 模板（`agent/prompts/charles_system_prompt.py` L62-91），并通过 `select_base_template(mode)` 在 yolo 模式时选用（`agent/context.py` L185-205 + L378-379）。与 Cline `cline.ts` L138-139 `mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT` 完全对齐。**L8 差距已失效**。

2. **5.20.4 mode_notice**：计划标注"Cline=是，Charles=无，M1 差距"。**实际**：Charles 已实现完整的 `<mode_notice>` 机制（Stage 36.1 M1）：
   - `state.py` L140-485 实现 `ModeSwitchNotice` dataclass + `_pending_mode_notices` 全局字典 + `_record_mode_switch_locked`（含往返抵消与链式切换）+ `consume_mode_notice` + `format_mode_switch_notice`
   - `set_mode`（L388）在锁内调用 `_record_mode_switch_locked` 记录 pending notice
   - `server.py` L599-606 在包装用户消息时 consume notice 并 prepend `<mode_notice>` 到 `<user_input mode="...">` 前

   与 Cline `format.ts` L41-80 `formatModeSwitchNotice` + `createModeSwitchNoticeTracker` 完全对齐。**M1 差距已失效**。

### 核心结论

1. **plan 模式注入**：完全对齐。Cline 在 `effectiveRules` 数组中通过 `mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined` 条件注入；Charles 在 `_build_rules` 中通过 `_load_mode_prompt() → get_mode_prompt(session_id)` 返回 `PLAN_MODE_PROMPT` 或 None 条件注入。
2. **act 模式不注入**：完全对齐。两者在 act 模式下均不注入 plan 模式契约。
3. **yolo 模式注入 YOLO base**：完全对齐。两者在 yolo 模式下均切换到 YOLO base prompt，且不注入 plan 模式契约。
4. **MODE_TAG 始终注入**：完全对齐。两者无论何种模式都注入 MODE_TAG 说明（Cline `effectiveRules` 数组无条件包含；Charles `_build_rules` L502-509 无条件追加）。
5. **mode_notice 运行时跟踪**：完全对齐。两者均通过"切换时记录 pending notice → 下一条用户消息前 consume 并 prepend"的模式实现。
6. **nanobot 残留**：与 Mode 段条件注入直接相关的代码文件中 **0 处实现逻辑残留，0 处注释残留**。`context.py` L275 的 1 处 nanobot 注释残留属于 `extra_sections` 废弃参数，与 mode 注入无关。

### 一致性总体评估

- **plan/act/yolo 注入条件**：**高**。三种模式的 base 模板选择与 PLAN_MODE 注入逻辑完全对齐。
- **MODE_TAG 始终注入**：**高**。无条件注入，语义与位置对齐。
- **mode_notice 运行时跟踪**：**高**。记录、抵消、链式、消费、格式化、prepend 全链路对齐。
- **nanobot 残留**：**无**。Mode 段条件注入逻辑无 nanobot 风格残留。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.20.1 | plan 模式注入 PLAN_MODE | `effectiveRules` 数组条件包含 `PLAN_MODE_INSTRUCTIONS`（cline.ts L148 `mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined`） | `_build_rules` 调用 `_load_mode_prompt() → get_mode_prompt(session_id)`，plan 返回 `PLAN_MODE_PROMPT`，其他返回 None（context.py L511-518 + plan_mode.py L274-288） | 高 | 已对齐。注入位置（rules 槽位）与条件（`mode === "plan"`）一致；Charles 通过 `get_mode_prompt` 间接判断，语义等价 |
| 5.20.2 | act 模式不注入 | `effectiveRules` 中 `mode === "plan"` 为 false，`PLAN_MODE_INSTRUCTIONS` 项为 `undefined`，被 `.filter(Boolean)` 过滤掉（cline.ts L148-150） | `get_mode_prompt` 在非 plan 模式返回 None，`_load_mode_prompt` 返回 None 时不追加到 `results`（context.py L512-518 + plan_mode.py L285-288） | 高 | 已对齐。act 模式下 PLAN_MODE 均不注入 |
| 5.20.3 | yolo 模式注入 YOLO base | `mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT`（cline.ts L138-139）；PLAN_MODE 不注入（yolo ≠ plan） | `select_base_template(mode)`：`mode == "yolo"` 返回 `YOLO_CHARLES_SYSTEM_PROMPT`，否则 `DEFAULT_CHARLES_SYSTEM_PROMPT`（context.py L203-205）；PLAN_MODE 不注入（yolo ≠ plan） | 高 | 已对齐。**计划标注的 L8 差距已失效**。Charles 已实现 YOLO 模板（charles_system_prompt.py L62-91）+ 模板选择函数（context.py L185-205） |
| 5.20.4 | mode_notice 运行时跟踪 | `format.ts` L41-46 `formatModeSwitchNotice` + L48-51 `ModeSwitchNotice` + L61-80 `createModeSwitchNoticeTracker`（record/consume）；runtime 在 `setMode` 时 record，在 `prepareTurnInput` 时 consume 并 prepend | `state.py` L140-156 `ModeSwitchNotice` + L159-162 `_pending_mode_notices` + L398-432 `_record_mode_switch_locked`（含往返抵消/链式）+ L451-464 `consume_mode_notice` + L467-485 `format_mode_switch_notice`；`set_mode` L388 record，`server.py` L599-606 consume 并 prepend | 高 | 已对齐。**计划标注的 M1 差距已失效**。Charles Stage 36.1 M1 已实现完整链路，含 Cline 的往返抵消与链式切换语义 |
| 5.20.5 | MODE_TAG 始终注入 | `effectiveRules` 数组无条件包含 `MODE_TAG_INSTRUCTIONS`（cline.ts L147） | `_build_rules` L502-509 无条件追加 `_build_mode_tag_instructions()` 结果到 `results` | 高 | 已对齐。MODE_TAG 在所有模式下均注入，因为切换 mode 后历史消息仍含旧 mode 标签，模型需能识别 |
| 5.20.6 | MODE_TAG 内容提及 mode_notice | `MODE_TAG_INSTRUCTIONS` 文本中含 "A `<mode_notice>` block inside a message marks exactly when such a switch happened."（cline.ts L23） | `_build_mode_tag_instructions` 文本中含 "消息内可能出现 `<mode_notice>` 块，标记模式切换的确切时刻。"（context.py L854） | 高 | 已对齐。语义一致，措辞本地化为中文 |
| 5.20.7 | mode 取值枚举 | `MODE_TAG_INSTRUCTIONS` 提及 `"plan"` / `"act"` / `"yolo"`（cline.ts L23）；`format.ts` L20 `USER_INPUT_MODE_RE = /<user_input\b[^>]*\bmode="(act|plan|yolo)"/` | `_build_mode_tag_instructions` 提及 `act` / `plan` / `yolo`（context.py L849-851）；`server.py` L605/L813 包装时直接用 `current_mode` 值 | 高 | 已对齐。三值枚举一致 |
| 5.20.8 | yolo 模式描述 | Cline `MODE_TAG_INSTRUCTIONS`："act" (or "yolo") means implementation was allowed"——yolo 与 act 行为等价，仅标签不同 | Charles `_build_mode_tag_instructions`："`yolo`: 自动执行模式（如启用），与 act 等价但无需逐步确认"（context.py L851） | 高 | 已对齐。两者均描述 yolo 与 act 行为等价 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.20 表格两项差距标注已失效（5.20.3 / 5.20.4）

AGENT_COMPARISON_PLAN_V2.md L2177-2178 标注：

```
| 5.20.3 | yolo 模式注入 | YOLO base | 无 | L8 差距 |
| 5.20.4 | mode_notice | 是 | 无 | M1 差距 |
```

经核查源码，两项差距均已闭合：

#### 5.20.3 yolo 模式注入（L8 差距已失效）

Charles 已实现 YOLO base prompt 注入，链路完整：

```
SystemPromptBuilder.build (context.py L378-379)
  └─ mode = self._get_current_mode()          ← 查询当前 mode
  └─ base_template = select_base_template(mode)  ← 选择模板
       └─ mode == "yolo" → YOLO_CHARLES_SYSTEM_PROMPT
       └─ 其他          → DEFAULT_CHARLES_SYSTEM_PROMPT
  └─ build_charles_system_prompt(base_template=base_template, ...)
```

`YOLO_CHARLES_SYSTEM_PROMPT`（charles_system_prompt.py L62-91）内容对标 Cline `YOLO_CLINE_SYSTEM_PROMPT`（system.ts L38+），描述"后台自主运行、无法与用户直接沟通、自主调查并解决问题"的场景，并含 `submit_and_exit` 强制结束语义。

Cline 对应链路：

```
buildClineSystemPrompt (cline.ts L138-139)
  └─ basePrompt = mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT
  └─ basePrompt.replace("{{CLINE_RULES}}", effectiveRules).replace(...)
```

两者语义完全一致：yolo 模式切换 base 模板，但 effectiveRules 注入逻辑不变（MODE_TAG 始终注入，PLAN_MODE 不注入）。

#### 5.20.4 mode_notice（M1 差距已失效）

Charles Stage 36.1 (M1) 已实现完整 `<mode_notice>` 机制，全链路对标 Cline：

| 环节 | Cline 位置 | Charles 位置 | 对齐情况 |
|------|-----------|-------------|---------|
| 数据结构 | `format.ts` L48-51 `ModeSwitchNotice` 接口（`from`/`to`） | `state.py` L140-156 `ModeSwitchNotice` dataclass（`from_mode`/`to_mode`） | 高（字段名略异，语义一致） |
| 全局存储 | `format.ts` L61-80 `createModeSwitchNoticeTracker` 返回闭包 | `state.py` L159-162 `_pending_mode_notices: dict[str, ModeSwitchNotice]` 按 session_id 隔离 | 高（Charles 用全局字典 + 锁，Cline 用闭包） |
| 记录（record） | tracker.record（`format.ts` L70-75） | `_record_mode_switch_locked`（`state.py` L398-432） | 高（含往返抵消 + 链式切换） |
| 触发点 | runtime `setMode` 调用 tracker.record | `set_mode` L388 在锁内调用 `_record_mode_switch_locked` | 高 |
| 消费（consume） | tracker.consume（`format.ts` L77-79） | `consume_mode_notice`（`state.py` L451-464） | 高（pop 语义） |
| 格式化 | `formatModeSwitchNotice`（`format.ts` L41-46） | `format_mode_switch_notice`（`state.py` L467-485） | 高（文本完全一致） |
| prepend 位置 | `prepareTurnInput` / `formatUserInputBlock` 在 `<user_input mode>` 前 prepend | `server.py` L599-606 在 `<user_input mode>` 前 prepend | 高 |

Charles `format_mode_switch_notice` 输出文本：

```
<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>
```

与 Cline `formatModeSwitchNotice` 输出**完全一致**（含标点与措辞）。

Charles 还实现了 Cline 的"往返抵消"与"链式切换"语义（`state.py` L420-432）：
- 往返抵消：`plan→act→plan`，pending 抵消为 None
- 链式切换：`act→plan→act→yolo`，保留原始 from（act），更新 to（yolo）

### 3.2 注入条件逻辑对比（5.20.1 / 5.20.2 / 5.20.5）

**Cline 注入逻辑**（cline.ts L145-151）：

```typescript
const effectiveRules = [
    rules,
    MODE_TAG_INSTRUCTIONS,                       // 无条件注入
    mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined,  // 条件注入
]
    .filter(Boolean)
    .join("\n\n");
```

**Charles 注入逻辑**（context.py L502-518）：

```python
# 4. MODE_TAG_INSTRUCTIONS — 作为 rule 注入（对齐 Cline effectiveRules）
mode_tag = self._build_mode_tag_instructions()
if mode_tag:
    results.append(RuleLoadResult(
        path=Path("__mode__/mode_tag_instructions.md"),
        body=mode_tag,
        activated=True,
    ))

# 5. PLAN_MODE_INSTRUCTIONS — 作为 rule 注入（仅 plan 模式，对齐 Cline effectiveRules）
plan_prompt = self._load_mode_prompt()
if plan_prompt:
    results.append(RuleLoadResult(
        path=Path("__mode__/plan_mode_instructions.md"),
        body=plan_prompt,
        activated=True,
    ))
```

两者对齐点：
- **MODE_TAG 无条件注入**：Cline 数组无条件包含；Charles `if mode_tag` 总为真（`_build_mode_tag_instructions` 始终返回非空文本），等价于无条件注入。
- **PLAN_MODE 条件注入**：Cline 用三元运算符 `mode === "plan" ? ... : undefined`；Charles 用 `if plan_prompt`，`plan_prompt` 由 `get_mode_prompt(session_id)` 返回——plan 模式返回 `PLAN_MODE_PROMPT`，其他返回 None。语义等价。
- **注入位置**：两者均注入到 rules 槽位（Cline `effectiveRules` → `{{CLINE_RULES}}`；Charles `results` → `format_rules_content` → `{{CHARLES_RULES}}`）。

### 3.3 nanobot 残留专项检查

针对 Mode 段条件注入相关代码文件的 nanobot 残留检查结果：

| 文件 | 注释残留 | 实现逻辑残留 | 说明 |
|------|---------|-------------|------|
| `agent/context.py` | 1 处（L275 `extra_sections` docstring 提及 "nanobot 风格的额外段落"） | 0 处 | `extra_sections` 参数已废弃，无调用方传入，与 mode 注入无关 |
| `agent/prompts/charles_system_prompt.py` | 0 处 | 0 处 | 模板纯对标 Cline system.ts |
| `agent/tools/plan_mode.py` | 0 处 | 0 处 | PLAN_MODE_PROMPT 纯对标 Cline PLAN_MODE_INSTRUCTIONS |
| `agent/state.py` | 0 处 | 0 处 | ModeSwitchNotice 纯对标 Cline format.ts |
| `agent/server.py` | 1 处（L2/L4 docstring 提及 "对标 Cline server + nanobot routes/chat.py"） | 0 处 | 文件级 docstring 历史溯源，与 mode 注入逻辑无关 |

**结论**：Mode 段条件注入逻辑**无 nanobot 实现逻辑残留**。`context.py` L275 的 nanobot 注释残留属于 `extra_sections` 废弃参数的 docstring，不影响 mode 注入逻辑；`server.py` 文件级 docstring 的 nanobot 提及是历史溯源说明，与 mode_notice 包装逻辑无关。

---

## 四、注入逻辑流程图对比

### 4.1 Cline Mode 段条件注入流程

```
buildClineSystemPrompt(options)  ← cline.ts L110-166
  │
  ├─ mode 参数从 options.mode 传入（act / plan / yolo）
  │
  ├─ 选择 base 模板（L138-139）
  │    ├─ mode === "yolo" → YOLO_CLINE_SYSTEM_PROMPT
  │    └─ 其他           → DEFAULT_CLINE_SYSTEM_PROMPT
  │
  ├─ 拼接 effectiveRules（L145-151）
  │    ├─ rules                              ← 用户规则（始终）
  │    ├─ MODE_TAG_INSTRUCTIONS              ← mode 标签说明（始终）
  │    └─ mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined  ← 条件
  │
  └─ 占位符替换（L153-165）
       ├─ {{PLATFORM_NAME}} / {{CWD}} / {{CURRENT_DATE}} / {{IDE_NAME}}
       ├─ {{CLINE_METADATA}} ← isCline 条件
       └─ {{CLINE_RULES}}    ← effectiveRules
```

### 4.2 Charles Mode 段条件注入流程

```
SystemPromptBuilder.build(task_type, provider_id)  ← context.py L348-391
  │
  ├─ rules_text = _build_rules(task_type)  ← context.py L454-539
  │    ├─ AGENTS.md + rules_dir            ← 用户规则（始终）
  │    ├─ _build_mode_tag_instructions()   ← mode 标签说明（始终，L502-509）
  │    ├─ _load_mode_prompt()              ← 条件（L511-518）
  │    │    └─ get_mode_prompt(session_id) ← plan_mode.py L274-288
  │    │         ├─ mode == "plan" → PLAN_MODE_PROMPT
  │    │         └─ 其他          → None
  │    └─ enhancements（可选，默认关闭）
  │
  ├─ mode = _get_current_mode()  ← 查询 SessionState.mode
  ├─ base_template = select_base_template(mode)  ← context.py L185-205
  │    ├─ mode == "yolo" → YOLO_CHARLES_SYSTEM_PROMPT
  │    └─ 其他           → DEFAULT_CHARLES_SYSTEM_PROMPT
  │
  └─ build_charles_system_prompt(...)  ← context.py L78-127
       ├─ 占位符替换
       │    ├─ {{PLATFORM_NAME}} / {{CWD}} / {{CURRENT_DATE}} / {{IDE_NAME}}
       │    ├─ {{CHARLES_METADATA}} ← should_inject_metadata 条件
       │    └─ {{CHARLES_RULES}}    ← rules_text
       └─ return prompt.strip()
```

### 4.3 mode_notice 运行时跟踪流程对比

**Cline**：

```
runtime.setMode(newMode)  ← 用户/UI 切换 mode
  └─ tracker.record(from, to)  ← format.ts L70-75
       ├─ 往返抵消：plan→act→plan → pending = null
       └─ 链式切换：保留 from，更新 to

runtime.prepareTurnInput(userMessage)  ← 下一轮用户消息
  ├─ notice = tracker.consume()  ← format.ts L77-79
  ├─ if notice: prefix = formatModeSwitchNotice(notice)  ← L41-46
  └─ return `${prefix}<user_input mode="${mode}">${input}</user_input>`
```

**Charles**：

```
set_mode(session_id, newMode)  ← state.py L368-389
  └─ _record_mode_switch_locked(session_id, from, to)  ← L398-432
       ├─ 往返抵消：pending.from == to → pop
       └─ 链式切换：pending.to = to

server.py 用户消息接收（L599-606）
  ├─ notice = consume_mode_notice(session_id)  ← state.py L451-464
  ├─ notice_prefix = format_mode_switch_notice(notice) + "\n" if notice else ""  ← L467-485
  └─ wrapped_message = f'{notice_prefix}<user_input mode="{current_mode}">\n{message}\n</user_input>'
```

两者流程完全对齐，包括往返抵消与链式切换语义。

---

## 五、结论

### 5.1 对齐状态总结

| 对比项 | 计划文件标注 | 实际状态 | 结论 |
|--------|------------|---------|------|
| 5.20.1 plan 模式注入 | 已对齐 | 已对齐 | 计划标注正确 |
| 5.20.2 act 模式注入 | 已对齐 | 已对齐 | 计划标注正确 |
| 5.20.3 yolo 模式注入 | L8 差距 | 已对齐 | **计划标注过时，L8 差距已闭合** |
| 5.20.4 mode_notice | M1 差距 | 已对齐 | **计划标注过时，M1 差距已闭合** |

### 5.2 nanobot 残留结论

- **Mode 段条件注入逻辑**：0 处实现逻辑残留，0 处注释残留（与 mode 注入直接相关代码）。
- **周边代码**：`context.py` L275（`extra_sections` docstring）+ `server.py` L2/L4（文件级 docstring）共 2 处注释残留，均与 mode 注入逻辑无关，属于历史溯源说明。
- **区分注释残留 vs 实现逻辑残留**：所有 nanobot 提及均为注释/docstring，无任何 nanobot 风格的条件注入实现逻辑残留。Mode 段条件注入完全基于 Cline 模式实现。

### 5.3 一致性最终评估

Mode 段条件注入逻辑（plan/act/yolo 何时注入）**完全对齐**：
- plan 模式：注入 PLAN_MODE_PROMPT，使用 DEFAULT base
- act 模式：不注入 PLAN_MODE，使用 DEFAULT base
- yolo 模式：不注入 PLAN_MODE，使用 YOLO base
- MODE_TAG：所有模式始终注入
- mode_notice：运行时跟踪机制完整对齐（含往返抵消与链式切换）
