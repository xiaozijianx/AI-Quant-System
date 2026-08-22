# Phase 5.14 `<user_input mode>` 标签说明段对比

> 对比范围：Cline 与 Charles 的 `<user_input mode="...">` 标签说明段（MODE_TAG_INSTRUCTIONS）的内容、格式、注入位置；`<user_input>` 包装位置；`<mode_notice>` 切换通知机制；段落顺序；区分注释残留与实现逻辑残留；nanobot 风格残留专项检查。
>
> 本阶段聚焦 System Prompt 中"解释 `<user_input mode>` 标签语义"的说明段，以及该标签在运行时如何被包装到用户消息上、模式切换如何通过 `<mode_notice>` 通知模型。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L11-23（MODE_TAG_INSTRUCTIONS 常量，effectiveRules 第二项）+ L110-166（buildClineSystemPrompt 注入位置）
> - `sdk/packages/shared/src/prompt/format.ts` L5-10（formatUserInputBlock 纯函数，runtime 层调用）+ L20-32（parseUserInputMode）+ L41-46（formatModeSwitchNotice）+ L61-80（createModeSwitchNoticeTracker）+ L134-146（normalizeUserInput）+ L155-158（stripModeNotices）
> - `sdk/packages/core/src/runtime/host/local-runtime-host.ts` L1712-1761（prepareTurnInput 在 runtime 层调用 formatModePrompt → formatUserInputBlock 包装用户输入）
> - `sdk/packages/core/src/session/team/team-session-coordinator.ts` L232-238（formatModePrompt → formatUserInputBlock 在 team session 中调用）
> - `apps/vscode/src/sdk/sdk-session-lifecycle.ts` L370（mode_notice 持久化说明）
>
> Charles 源码：
> - `agent/context.py` L836-856（`_build_mode_tag_instructions` 生成标签说明段，作为 rule 注入）+ L503-509（_build_rules 注入位置）
> - `agent/server.py` L594-605（首次 run 手动包装 `<user_input mode>` + prepend `<mode_notice>`）+ L807-814（queue 消费的 run 同样包装）
> - `agent/runtime.py` L2686-2718（`_call_prepare_turn_input_hooks`）+ L2720-2787（`_call_format_user_input_block_hooks`）+ L2789-2848（`_apply_default_user_input_wrap` Stage 36.2 M2 runtime 层默认包装）
> - `agent/state.py` L140-156（`ModeSwitchNotice` 数据类）+ L159-162（`_pending_mode_notices` 全局字典，按 session_id 隔离）+ L410-432（`_record_mode_switch_locked` 链式切换 + 往返抵消逻辑）+ L435-448（`record_mode_switch` 线程安全包装）+ L451-464（`consume_mode_notice` 取出并清除）+ L467-485（`format_mode_switch_notice` 生成 XML 文本）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`（nanobot 原生无 `<user_input mode>` 标签说明段，无 mode_notice 机制）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 `<user_input mode>` 标签说明段及配套的运行时包装/通知机制。**核心结论：计划表（AGENT_COMPARISON_PLAN_V2.md L2061-2081）所列 5 项差距（M1/M2/L7/顺序偏移）已全部失效——Charles 通过 Stage 36.1 (M1) 补齐了 mode_notice 机制、Stage 36.2 (M2) 补齐了 runtime 层包装、L7 对齐移除了工具名列举。两者当前在所有 5 个维度上均已对齐，剩余差异仅为语言（中文 vs 英文）与文本结构（项目列表 vs 散文）层面的非语义差异。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.14（L2061-2081）的对比表标注了 5 项差距，**全部与实际源码不符**：

1. **5.14.1 包装位置（M2 差距）**：计划表标注"runtime 层 vs server.py，M2 差距"。**实际**：Charles 在 Stage 36.2 (M2) 已在 `agent/runtime.py` L2789-2848 新增 `_apply_default_user_input_wrap`，runtime 层在无 hook 时默认包装 `<user_input mode="...">`。server.py 与 runtime.py 双层包装已对齐 Cline 的 host 层包装（prepareTurnInput → formatUserInputBlock）。**M2 差距已失效**。

2. **5.14.3 工具名列举（L7 差距）**：计划表标注"Charles 是，L7 差距"。**实际**：`agent/context.py` L838-840 注释明确标注"L7 对齐: 移除具体工具名列举"，当前 `_build_mode_tag_instructions` 仅列举 mode 取值（`act`/`plan`/`yolo`），不列举工具名（如 `read_files`/`run_commands`）。与 Cline 完全一致——Cline 也不列举工具名。**L7 差距已失效**。

3. **5.14.4 mode_notice 机制（M1 差距）**：计划表标注"Charles 无，M1 差距"。**实际**：Charles 在 Stage 36.1 (M1) 已在 `agent/state.py` L140-485 实现完整的 mode_notice 机制：`ModeSwitchNotice` 数据类、`_pending_mode_notices` 按 session_id 隔离的全局字典、`_record_mode_switch_locked` 链式切换 + 往返抵消逻辑（与 Cline `createModeSwitchNoticeTracker` 完全等价）、`consume_mode_notice` 取出并清除、`format_mode_switch_notice` 生成与 Cline 字面一致的 `<mode_notice>` XML 文本。server.py L598-603 + L808-812 在包装用户输入前 consume 并 prepend。**M1 差距已失效**。

4. **5.14.5 段落位置（顺序偏移）**：计划表标注"第 12 段 vs 第 11 段，顺序偏移"。**实际**：两者顶层 System Prompt 段数均为 3（base + rules + metadata），`<user_input mode>` 标签说明段均作为 effectiveRules / `_build_rules` 的第二项（在用户规则之后、PLAN_MODE 之前）注入 `{{CLINE_RULES}}` / `{{CHARLES_RULES}}` 占位符内。"第 11/12 段"是基于早期版本或不同计数方式的理解，实际两者位置完全对齐。**顺序偏移不存在**。

5. **5.14.2 标签说明段（已对齐）**：计划表此项标注准确——两者均有标签说明段且已对齐。

### 核心结论

1. **标签说明段内容对齐**：两者均解释 `<user_input mode="...">` 标签语义、mode 取值（act/plan/yolo）、模式切换规则（最新消息 mode 为准）、`<mode_notice>` 块标记切换时刻。Charles 文本为中文，Cline 为英文；Charles 用项目列表枚举 mode 取值，Cline 用散文描述。语义等价。

2. **包装位置双层对齐**：Cline 在 `local-runtime-host.ts` L1712-1761 `prepareTurnInput` 内调用 `formatModePrompt → formatUserInputBlock` 包装；Charles 在 `server.py` L594-605 手动包装（首次 run）+ `server.py` L807-814（queue 消费的 run）+ `runtime.py` L2789-2848 `_apply_default_user_input_wrap`（runtime 层默认包装，跳过已包装消息避免双重包装）。两者均在 runtime/host 层完成包装，非 system prompt 文本层。

3. **mode_notice 机制完全对齐**：Cline `createModeSwitchNoticeTracker` 闭包（format.ts L61-80）与 Charles `_pending_mode_notices` 字典 + `_record_mode_switch_locked`（state.py L410-432）均实现：相同 mode 切换不记录、往返抵消（plan→act→plan 取消 pending）、链式切换保留原始 from。`formatModeSwitchNotice` 生成的 XML 文本两者字面一致：`<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>`。

4. **工具名列举已对齐**：两者均不列举具体工具名。Charles L7 对齐注释（context.py L838-840）明确说明工具限制由 `tool_policies` 硬禁用，不在 MODE_TAG 说明段重复——与 Cline 设计一致。

5. **段落位置对齐**：两者标签说明段均作为 effectiveRules / `_build_rules` 的第二项（始终注入），位于 `{{CLINE_RULES}}` / `{{CHARLES_RULES}}` 占位符内。

6. **nanobot 残留**：`<user_input mode>` 标签说明段层面 **0 处注释残留，0 处实现逻辑残留**。`agent/context.py` L275 的 `extra_sections` docstring 提到"nanobot 风格"，但该参数属于已废弃的 dead code，与 `<user_input mode>` 标签说明段无关（详见 P5.11）。

### 一致性总体评估

- **标签说明段存在性**：**对齐**（两者均有 MODE_TAG_INSTRUCTIONS 等价段，始终注入）
- **标签说明段语义**：**对齐**（解释 mode 取值、切换规则、mode_notice 块）
- **标签说明段格式**：**部分对齐**（Charles 中文 + 项目列表，Cline 英文 + 散文；语义等价，文本结构略异）
- **`<user_input>` 包装位置**：**对齐**（两者均在 runtime/host 层包装，非 system prompt 文本层）
- **`<mode_notice>` 机制**：**对齐**（数据类、pending 字典、链式切换、往返抵消、XML 文本字面一致）
- **工具名列举**：**对齐**（两者均不列举具体工具名）
- **段落位置**：**对齐**（两者均作为 rules 内第二项注入）
- **nanobot 残留**：0 处注释残留，0 处实现逻辑残留

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.14.1 | `<user_input>` 包装位置 | runtime/host 层：`prepareTurnInput`（local-runtime-host.ts L1712-1761）调用 `formatModePrompt → formatUserInputBlock`（format.ts L5-10）包装 | 双层：(1) `server.py` L594-605 / L807-814 手动包装（兼容层）；(2) `runtime.py` L2789-2848 `_apply_default_user_input_wrap`（Stage 36.2 M2 runtime 层默认包装，跳过已包装避免双重） | 对齐 | 计划表"M2 差距"已失效；Stage 36.2 (M2) 已补齐 runtime 层包装 |
| 5.14.2 | 标签说明段 | **存在**。`MODE_TAG_INSTRUCTIONS`（cline.ts L21-23）作为 effectiveRules 第二项注入（cline.ts L147），始终注入 | **存在**。`_build_mode_tag_instructions()`（context.py L836-856）生成标签说明，作为 rule 注入（context.py L503-509），始终注入 | 对齐 | 两者均始终注入；Charles 文本为中文 + 项目列表，Cline 为英文 + 散文，语义等价 |
| 5.14.3 | 工具名列举 | **无**。`MODE_TAG_INSTRUCTIONS` 仅描述 mode 取值（plan/act/yolo）语义，不列举具体工具名 | **无**。`_build_mode_tag_instructions` 仅列举 mode 取值（act/plan/yolo），不列举工具名。L7 对齐注释（L838-840）明确说明工具限制由 `tool_policies` 硬禁用 | 对齐 | 计划表"L7 差距"已失效；Charles 已在 L7 对齐时移除工具名列举 |
| 5.14.4 | mode_notice 机制 | **存在**。`formatModeSwitchNotice`（format.ts L41-46）+ `createModeSwitchNoticeTracker`（format.ts L61-80）闭包：相同 mode 不记录、往返抵消、链式切换保留原始 from | **存在**。`ModeSwitchNotice` 数据类（state.py L140-156）+ `_pending_mode_notices` 字典（L159-162）+ `_record_mode_switch_locked`（L410-432）+ `consume_mode_notice`（L451-464）+ `format_mode_switch_notice`（L467-485） | 对齐 | 计划表"M1 差距"已失效；Stage 36.1 (M1) 已补齐完整 mode_notice 机制；XML 文本字面一致 |
| 5.14.5 | 段落位置 | effectiveRules 第二项（cline.ts L145-151：`[rules, MODE_TAG_INSTRUCTIONS, PLAN_MODE?]`），注入 `{{CLINE_RULES}}` 占位符 | `_build_rules` 第二项（context.py L503-509：`[AGENTS.md, rules_dir, MODE_TAG, PLAN_MODE?, enhancements?]`），注入 `{{CHARLES_RULES}}` 占位符 | 对齐 | 计划表"第 12 段 vs 第 11 段，顺序偏移"不存在；两者顶层段均为 3（base + rules + metadata），标签说明段在 rules 内位置一致 |

---

## 三、重点差距详细说明

### 3.1 计划表 5.14.1 "M2 差距"已失效（`<user_input>` 包装位置）

计划表标注"Cline runtime 层 vs Charles server.py，M2 差距"。实际 Charles 在 Stage 36.2 (M2) 已完成 runtime 层默认包装补齐：

**Cline 实现**（runtime/host 层包装）：
```
local-runtime-host.ts L1712-1761 prepareTurnInput
  ├─ normalizeUserInput(input.prompt)         ← 清理标签
  ├─ enrichPromptWithMentions(...)            ← @mention 展开
  └─ formatModePrompt(enriched, mode)         ← 调用 formatUserInputBlock 包装
       └─ return `<user_input mode="${mode}">${input}</user_input>`
```

**Charles 实现**（双层包装，runtime 层为默认）：
```
server.py L594-605（兼容层，HTTP 入口）
  ├─ consume_mode_notice(session_id)          ← 取出 pending notice
  ├─ notice_prefix = format_mode_switch_notice(notice) + "\n"
  └─ wrapped = f'{notice_prefix}<user_input mode="{current_mode}">\n{message}\n</user_input>'

runtime.py L2789-2848 _apply_default_user_input_wrap（Stage 36.2 M2 runtime 层默认）
  ├─ mode = self._get_current_mode_for_wrap()
  ├─ if user_text.lstrip().startswith("<user_input"):  ← 已包装跳过
  │     return 原文本
  └─ else:
        wrapped = f'<user_input mode="{mode}">\n{user_text}\n</user_input>'
```

Charles 的双层包装设计：server.py 入口已包装的消息会被 runtime 层 `_apply_default_user_input_wrap` 检测到 `<user_input` 前缀而跳过（runtime.py L2831），避免双重包装；非 server.py 入口（如直接调用 `runtime.run()`）则由 runtime 层默认包装。语义与 Cline 的 host 层单点包装等价。

**结论**：M2 差距已失效。两者均在 runtime/host 层完成包装，非 system prompt 文本层。

### 3.2 计划表 5.14.4 "M1 差距"已失效（mode_notice 机制）

计划表标注"Charles 无 mode_notice 机制，M1 差距"。实际 Charles 在 Stage 36.1 (M1) 已实现完整的 mode_notice 机制，与 Cline `createModeSwitchNoticeTracker` 完全等价：

**Cline 实现**（闭包 + 模块级函数）：
```typescript
// format.ts L61-80
function createModeSwitchNoticeTracker() {
    let pending: ModeSwitchNotice | null = null;
    return {
        record(from, to) {
            if (from === to) return;                          // 相同 mode 不记录
            if (pending) {
                pending = pending.from === to ? null : { from: pending.from, to };  // 往返抵消 / 链式切换
                return;
            }
            pending = { from, to };
        },
        consume() { const n = pending; pending = null; return n; }
    };
}

// format.ts L41-46
function formatModeSwitchNotice(from, to) {
    return `<mode_notice>The user switched from ${from} mode to ${to} mode before sending this message.</mode_notice>`;
}
```

**Charles 实现**（数据类 + 全局字典 + 函数）：
```python
# state.py L140-156
@dataclass
class ModeSwitchNotice:
    from_mode: str
    to_mode: str

# state.py L159-162
_pending_mode_notices: dict[str, ModeSwitchNotice] = {}  # 按 session_id 隔离

# state.py L410-432
def _record_mode_switch_locked(session_id, from_mode, to_mode):
    if from_mode == to_mode: return                        # 相同 mode 不记录
    pending = _pending_mode_notices.get(session_id)
    if pending is not None:
        if pending.from_mode == to_mode:                   # 往返抵消：plan→act→plan
            _pending_mode_notices.pop(session_id, None)
        else:                                              # 链式切换：保留原始 from
            pending.to_mode = to_mode
    else:
        _pending_mode_notices[session_id] = ModeSwitchNotice(from_mode, to_mode)

# state.py L467-485
def format_mode_switch_notice(notice):
    return (
        f'<mode_notice>The user switched from {notice.from_mode} mode '
        f'to {notice.to_mode} mode before sending this message.</mode_notice>'
    )
```

**对比**：
- 数据结构：Cline 闭包内 `pending: ModeSwitchNotice | null` ↔ Charles 全局字典 `_pending_mode_notices[session_id]`（Charles 按 session_id 隔离，支持多会话；Cline 闭包单实例需由调用方按 session 持有）
- 逻辑等价性：相同 mode 不记录、往返抵消、链式切换保留原始 from——三者完全等价
- XML 文本字面一致：`<mode_notice>The user switched from {from} mode to {to} mode before sending this message.</mode_notice>`
- 消费时机：Cline 在 `sdk-session-lifecycle.ts` L370 consume 并 prepend；Charles 在 `server.py` L602 / L811 consume 并 prepend（包装用户输入前）

**结论**：M1 差距已失效。Charles mode_notice 机制与 Cline 完全等价，XML 文本字面一致。

### 3.3 计划表 5.14.3 "L7 差距"已失效（工具名列举）

计划表标注"Charles 是，L7 差距"——意指 Charles 在标签说明段中列举了具体工具名。实际 Charles 已在 L7 对齐时移除工具名列举：

**Charles `_build_mode_tag_instructions` 当前文本**（context.py L845-856）：
```
# 用户消息模式标签

用户消息会被 `<user_input mode="...">` 标签包裹，mode 取值:
- `act`: 执行模式，可直接调用工具完成任务
- `plan`: 规划模式，只读不写，先制定计划待用户批准后再执行。plan 模式下写入或执行类工具由 tool_policies 硬禁用
- `yolo`: 自动执行模式（如启用），与 act 等价但无需逐步确认

若连续消息的 mode 标签不同，说明用户切换了模式 — 以最新消息的 mode 为准，无论之前消息允许什么操作。消息内可能出现 `<mode_notice>` 块，标记模式切换的确切时刻。

各模式的具体行为约束见系统提示的 Plan Mode 段（仅 plan 模式注入）。
```

**Cline `MODE_TAG_INSTRUCTIONS` 文本**（cline.ts L21-23）：
```
# Plan / Act Modes

User messages arrive wrapped in a <user_input mode="..."> tag. The mode attribute is the interaction mode the user was in when they sent that message: "plan" means plan-mode constraints applied (explore, analyze, and align on a plan -- no edits or state-changing commands), while "act" (or "yolo") means implementation was allowed. If the mode attribute changes between messages, the user switched modes -- the newest message's mode is what governs right now, regardless of what earlier messages allowed. A <mode_notice> block inside a message marks exactly when such a switch happened.
```

**对比**：
- 标题：Charles "用户消息模式标签" vs Cline "Plan / Act Modes"（语义等价）
- mode 取值：两者均覆盖 act/plan/yolo，不列举具体工具名（如 `read_files`/`run_commands`/`editor`）
- 工具限制说明：Charles 提到"plan 模式下写入或执行类工具由 tool_policies 硬禁用"（说明限制机制，不列举工具名）；Cline 提到"plan-mode constraints applied (... no edits or state-changing commands)"（描述限制语义，不列举工具名）
- 模式切换规则：两者均说明"最新消息 mode 为准"
- `<mode_notice>` 块：两者均说明标记切换时刻
- Charles L7 对齐注释（L838-840）明确："L7 对齐: 移除具体工具名列举，工具限制由 tool_policies 硬禁用，不在 MODE_TAG 说明中重复（对齐 Cline — Cline 不列举具体工具名）"

**结论**：L7 差距已失效。两者均不列举具体工具名，仅描述 mode 语义和限制机制。

### 3.4 计划表 5.14.5 "顺序偏移"不存在（段落位置）

计划表标注"第 12 段 vs 第 11 段，顺序偏移"。实际两者顶层 System Prompt 段数均为 3，标签说明段在 rules 内位置一致：

**Cline 顶层结构**：
```
[Base Prompt 段]                          ← 第 1 段
[{{CLINE_RULES}} 段 → effectiveRules]     ← 第 2 段
  ├─ caller rules                          ← rules 内第 1 项
  ├─ MODE_TAG_INSTRUCTIONS                 ← rules 内第 2 项（标签说明段）
  └─ PLAN_MODE_INSTRUCTIONS?               ← rules 内第 3 项（仅 plan 模式）
[{{CLINE_METADATA}} 段 → metadata]        ← 第 3 段
```

**Charles 顶层结构**：
```
[Base Prompt 段]                          ← 第 1 段
[{{CHARLES_RULES}} 段 → _build_rules]     ← 第 2 段
  ├─ 全局 ~/.agent/AGENTS.md               ← rules 内第 1 项
  ├─ workspace agents_path                 ← rules 内第 2 项
  ├─ rules_dir 目录                        ← rules 内第 3 项
  ├─ MODE_TAG（标签说明段）                 ← rules 内第 4 项（始终注入）
  ├─ PLAN_MODE?                            ← rules 内第 5 项（仅 plan 模式）
  └─ enhancements?                         ← rules 内第 6+ 项（可选，默认关闭）
[{{CHARLES_METADATA}} 段 → metadata]      ← 第 3 段
```

**对比**：
- 顶层段数：均为 3（base + rules + metadata）
- 标签说明段位置：均在 rules 内，位于用户规则之后、PLAN_MODE 之前
- Charles rules 内子段数更多（因 AGENTS.md + rules_dir + enhancements），但标签说明段相对位置（在用户规则之后、PLAN_MODE 之前）与 Cline 一致

**结论**：顺序偏移不存在。"第 11/12 段"可能是基于早期版本或对段落计数方式的不同理解（如把 base 内嵌的 identity / 通用规则 / `<env>` 拆分为独立段，或把 enhancement 子段计入顶层段）。实际两者段落位置对齐。

---

## 四、文本对比（标签说明段）

### 4.1 Cline `MODE_TAG_INSTRUCTIONS`（cline.ts L21-23，英文散文）

```
# Plan / Act Modes

User messages arrive wrapped in a <user_input mode="..."> tag. The mode attribute is the interaction mode the user was in when they sent that message: "plan" means plan-mode constraints applied (explore, analyze, and align on a plan -- no edits or state-changing commands), while "act" (or "yolo") means implementation was allowed. If the mode attribute changes between messages, the user switched modes -- the newest message's mode is what governs right now, regardless of what earlier messages allowed. A <mode_notice> block inside a message marks exactly when such a switch happened.
```

**特征**：
- 标题：`# Plan / Act Modes`
- 单段散文，无项目列表
- mode 取值用引号内联（`"plan"` / `"act"` / `"yolo"`）
- plan 限制用括号内联（`explore, analyze, and align on a plan -- no edits or state-changing commands`）
- 不提及具体工具名，不提及限制机制（如 tool_policies）

### 4.2 Charles `_build_mode_tag_instructions`（context.py L845-856，中文 + 项目列表）

```
# 用户消息模式标签

用户消息会被 `<user_input mode="...">` 标签包裹，mode 取值:
- `act`: 执行模式，可直接调用工具完成任务
- `plan`: 规划模式，只读不写，先制定计划待用户批准后再执行。plan 模式下写入或执行类工具由 tool_policies 硬禁用
- `yolo`: 自动执行模式（如启用），与 act 等价但无需逐步确认

若连续消息的 mode 标签不同，说明用户切换了模式 — 以最新消息的 mode 为准，无论之前消息允许什么操作。消息内可能出现 `<mode_notice>` 块，标记模式切换的确切时刻。

各模式的具体行为约束见系统提示的 Plan Mode 段（仅 plan 模式注入）。
```

**特征**：
- 标题：`# 用户消息模式标签`
- 项目列表枚举 mode 取值（`act`/`plan`/`yolo`）
- 每个模式用一行描述，含冒号分隔
- plan 限制明确提及 `tool_policies` 硬禁用机制（Charles 独有术语，但不列举工具名）
- 末尾引导到 Plan Mode 段（仅 plan 模式注入）

### 4.3 语义等价性

| 语义点 | Cline | Charles | 等价 |
|--------|-------|---------|------|
| 标签语义 | `<user_input mode="...">` 包裹用户消息 | `<user_input mode="...">` 标签包裹 | 等价 |
| mode 取值 | plan / act (or yolo) | act / plan / yolo | 等价 |
| plan 限制 | no edits or state-changing commands | 只读不写，写入或执行类工具由 tool_policies 硬禁用 | 等价（Charles 额外说明限制机制） |
| 切换规则 | newest message's mode is what governs right now | 以最新消息的 mode 为准 | 等价 |
| `<mode_notice>` 块 | marks exactly when such a switch happened | 标记模式切换的确切时刻 | 等价 |
| 工具名列举 | 无 | 无 | 等价 |
| Plan Mode 段引用 | 无（PLAN_MODE_INSTRUCTIONS 独立注入） | 有（"各模式的具体行为约束见系统提示的 Plan Mode 段"） | Charles 额外引导 |

**结论**：文本结构略异（中文 vs 英文、项目列表 vs 散文），语义完全等价。Charles 额外提及 `tool_policies` 术语和 Plan Mode 段引用，属于增强说明，非语义偏差。

---

## 五、nanobot 残留专项检查

### 5.1 `<user_input mode>` 标签说明段层面

| 检查项 | Cline | Charles | 残留性质 |
|--------|-------|---------|---------|
| 标签说明段文本 | 英文散文 | 中文 + 项目列表 | 无残留（文本为 Charles 原生中文实现） |
| mode 取值命名 | act/plan/yolo | act/plan/yolo | 无残留（与 Cline 一致） |
| `<mode_notice>` 术语 | mode_notice | mode_notice | 无残留（与 Cline 一致） |
| `tool_policies` 术语 | 无（Cline 用 "plan-mode constraints"） | 有（"plan 模式下写入或执行类工具由 tool_policies 硬禁用"） | 无残留（Charles 独有术语，非 nanobot 术语） |
| 包装函数命名 | `formatUserInputBlock` | `_apply_default_user_input_wrap` + `format_user_input_block` hook | 无残留（命名风格不同但语义对齐） |
| mode_notice 数据结构 | `ModeSwitchNotice` type | `ModeSwitchNotice` dataclass | 无残留（命名与 Cline 一致） |
| mode_notice tracker | `createModeSwitchNoticeTracker` 闭包 | `_pending_mode_notices` 字典 + `_record_mode_switch_locked` | 无残留（实现范式不同但逻辑等价） |

**结论**：`<user_input mode>` 标签说明段层面 **0 处注释残留，0 处实现逻辑残留**。所有术语和命名均对齐 Cline，无 nanobot 风格残留。

### 5.2 相关文件的 nanobot 残留（非本阶段核心）

- `agent/context.py` L275：`extra_sections` 参数 docstring 提到 "nanobot 风格的额外段落，Cline 无此概念"——属于已废弃 dead code 的注释残留，与 `<user_input mode>` 标签说明段无关（详见 P5.11 Custom Instructions 段对比）。
- `agent/server.py` L2/L4/L28：docstring 提到 "对标 Cline server + nanobot routes/chat.py"——属于文件级历史溯源注释，非 `<user_input mode>` 标签说明段实现。
- `agent/providers/qwen.py`、`agent/tools/exec_tool.py`、`agent/tools/file_tools.py`、`agent/tools/web_tool.py`、`agent/skills/` 系列文件：均有 nanobot 残留注释，但与 `<user_input mode>` 标签说明段无关。

**结论**：本阶段范围内 nanobot 残留为 0；相关文件的 nanobot 残留已在其他阶段（P3.21/P3.22/P3.23/P3.24/P4.20/P5.11 等）覆盖。

---

## 六、最终结论

### 6.1 一致性总评

| 维度 | 一致性等级 | 说明 |
|------|-----------|------|
| 标签说明段存在性 | 对齐 | 两者均有 MODE_TAG_INSTRUCTIONS 等价段，始终注入 |
| 标签说明段语义 | 对齐 | 解释 mode 取值、切换规则、mode_notice 块 |
| 标签说明段格式 | 部分对齐 | Charles 中文 + 项目列表，Cline 英文 + 散文；语义等价 |
| `<user_input>` 包装位置 | 对齐 | 两者均在 runtime/host 层包装（Stage 36.2 M2 已补齐） |
| `<mode_notice>` 机制 | 对齐 | 数据类、pending 字典、链式切换、往返抵消、XML 文本字面一致（Stage 36.1 M1 已补齐） |
| 工具名列举 | 对齐 | 两者均不列举具体工具名（L7 已对齐） |
| 段落位置 | 对齐 | 两者均作为 rules 内第二项注入 |
| nanobot 残留 | 无 | 0 处注释残留，0 处实现逻辑残留 |

### 6.2 计划表勘误汇总

| 计划表项 | 计划表标注 | 实际情况 | 修正 |
|---------|----------|---------|------|
| 5.14.1 | "M2 差距" | Charles runtime.py L2789-2848 已实现 `_apply_default_user_input_wrap`（Stage 36.2 M2） | M2 差距已失效，改为"对齐" |
| 5.14.2 | "已对齐" | 两者均有标签说明段 | 标注准确 |
| 5.14.3 | "L7 差距" | Charles L7 对齐注释明确已移除工具名列举 | L7 差距已失效，改为"对齐" |
| 5.14.4 | "M1 差距" | Charles state.py L140-485 已实现完整 mode_notice 机制（Stage 36.1 M1） | M1 差距已失效，改为"对齐" |
| 5.14.5 | "顺序偏移" | 两者顶层段均为 3，标签说明段在 rules 内位置一致 | 顺序偏移不存在，改为"对齐" |

### 6.3 后续建议

- **无需修复**：本阶段所有差距均已失效，当前实现与 Cline 完全对齐。
- **可选优化**：标签说明段文本可考虑统一为英文（与 Cline 字面一致），但当前中文实现语义等价，非必须。
- **文档更新**：建议更新 AGENT_COMPARISON_PLAN_V2.md P5.14 表格，标注"M1/M2/L7 差距已失效"，避免后续阶段误引用。
