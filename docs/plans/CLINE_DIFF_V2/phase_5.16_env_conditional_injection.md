# Phase 5.16 `<env>` 段条件注入对比

> 对比范围：Cline `buildClineSystemPrompt` 中 `<env>` 段的注入条件（何时注入 / 何时不注入）与 Charles `build_charles_system_prompt` 中 `<env>` 段的注入条件差异；`<env>` 段内容来源（base prompt 模板硬编码 vs 动态构建）、占位符替换是否受 provider/mode 条件门控、与 metadata 段条件注入的边界区分；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-36（`DEFAULT_CLINE_SYSTEM_PROMPT`，`<env>` 段硬编码在 base prompt 模板 L7-13）+ L38-68（`YOLO_CLINE_SYSTEM_PROMPT`，`<env>` 段硬编码 L52-58）
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt`，占位符替换 L153-165；env 占位符替换 L154-157 无条件执行，metadata 占位符替换 L158-163 有 `isCline` 条件门控）
>
> Charles 源码：
> - `agent/prompts/charles_system_prompt.py` L29-58（`DEFAULT_CHARLES_SYSTEM_PROMPT`，`<env>` 段硬编码在 base prompt 模板 L49-54）+ L60-91（`YOLO_CHARLES_SYSTEM_PROMPT`，`<env>` 段硬编码 L74-79）
> - `agent/context.py` L78-127（`build_charles_system_prompt`，占位符替换 L108-127；env 占位符替换 L111-114 无条件执行，metadata 占位符替换 L122-125 有 `should_inject_metadata` 条件门控）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 `<env>` 段**条件注入逻辑**（非 env 段内容本身，内容对比见 P5.4）。**核心结论：Charles 已与 Cline 完全对齐 —— 两者的 `<env>` 段均为 always 注入，无任何条件门控**。

### 核心结论

1. **注入条件完全对齐**：Cline 与 Charles 的 `<env>` 段均硬编码在 base prompt 模板中（`DEFAULT` / `YOLO` 双模板均含 `<env>` 段），模板选择仅区分 `mode`（act/plan → DEFAULT，yolo → YOLO），两个模板均含 `<env>` 段，因此 `<env>` 段**始终注入**，无 provider/mode/task_type 条件门控。
2. **占位符替换无条件执行**：Cline `buildClineSystemPrompt` L154-157 对 `{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` 的替换为**无条件链式 replace**；Charles `build_charles_system_prompt` L111-114 同样为**无条件链式 replace**。两者均不做 provider 判断、mode 判断或任何 if 分支。
3. **与 metadata 条件注入的边界清晰**：Cline 仅对 `{{CLINE_METADATA}}` 施加 `isClineProvider(providerId)` 条件门控（cline.ts L124 + L158-163）；Charles 仅对 `{{CHARLES_METADATA}}` 施加 `should_inject_metadata(provider_id)` 条件门控（context.py L122-125）。**`<env>` 段不涉及任何 provider 条件判断** —— 这是 P5.17（metadata 段条件注入）的范畴，与 P5.16 无关。
4. **内容来源对齐**：Cline `<env>` 段来自 `system.ts` 的 base prompt 模板；Charles `<env>` 段来自 `charles_system_prompt.py` 的 base prompt 模板。两者均为**模板硬编码**，非运行时动态构建。
5. **nanobot 残留**：**0 处实现逻辑残留**（env 段条件注入逻辑无 nanobot 风格）；**1 处注释残留**（context.py L275 `extra_sections` 参数 docstring，与 env 段条件注入无直接关系）。

### 计划文件一致性

`AGENT_COMPARISON_PLAN_V2.md` L2099-2113 的 P5.16 计划描述准确：
- "Cline 实现：always 注入" —— 与实际代码一致
- "Charles 实现：always 注入" —— 与实际代码一致
- 对比表 5.16.1（注入条件 always vs always，已对齐）—— 与实际代码一致
- 对比表 5.16.2（内容来源 system.ts vs charles_system_prompt.py，已对齐）—— 与实际代码一致

**计划文件无修正项**。

### 一致性总体评估

- **注入条件**：**完全对齐**。两者均为 always 注入，无任何条件门控。
- **占位符替换**：**完全对齐**。两者均为无条件链式 replace。
- **内容来源**：**完全对齐**。两者均来自 base prompt 模板硬编码。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.16.1 | `<env>` 注入条件 | always（模板硬编码，无 if 分支） | always（模板硬编码，无 if 分支） | 完全对齐 | 两者 `<env>` 段均嵌入 base prompt 模板，模板始终被选中（DEFAULT 或 YOLO 均含 env），无 provider/mode/task_type 条件门控 |
| 5.16.2 | `<env>` 内容来源 | `system.ts` 的 `DEFAULT_CLINE_SYSTEM_PROMPT` L7-13 / `YOLO_CLINE_SYSTEM_PROMPT` L52-58（模板硬编码） | `charles_system_prompt.py` 的 `DEFAULT_CHARLES_SYSTEM_PROMPT` L49-54 / `YOLO_CHARLES_SYSTEM_PROMPT` L74-79（模板硬编码） | 完全对齐 | 两者均为 base prompt 模板硬编码，非运行时动态构建 |
| 5.16.3 | env 占位符替换条件 | 无条件（cline.ts L154-157 链式 replace） | 无条件（context.py L111-114 链式 replace） | 完全对齐 | `{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` 均为无条件替换 |
| 5.16.4 | provider 条件门控 | 无（env 段不检查 `isClineProvider`） | 无（env 段不检查 `is_charles_provider`） | 完全对齐 | provider 条件门控仅作用于 metadata 段（P5.17 范畴），不作用于 env 段 |
| 5.16.5 | mode 条件门控 | 无（DEFAULT 与 YOLO 模板均含 env 段） | 无（DEFAULT 与 YOLO 模板均含 env 段） | 完全对齐 | mode 仅决定选择哪个 base 模板，两个模板均含 env 段，因此 env 始终注入 |
| 5.16.6 | overridePrompt 场景 | overridePrompt 非空时跳过 base 模板（cline.ts L126-136），env 段不注入 | 无 overridePrompt 机制 | 设计差异（合理） | Cline 的 overridePrompt 是 per-request 覆盖整个 system prompt 的逃生通道，覆盖时 env 段自然不注入；Charles 无此机制。此差异属于主机层能力差异，非 env 条件注入逻辑差异 |
| 5.16.7 | 模板缺失场景 | base 模板必选（DEFAULT 或 YOLO），无空模板路径 | base 模板必选（DEFAULT 或 YOLO），无空模板路径 | 完全对齐 | 两者均保证 base 模板非空，env 段必然存在 |

---

## 三、重点差距详细说明

### 3.1 注入条件对比（5.16.1）

**Cline `<env>` 注入条件分析**：

Cline 的 `<env>` 段硬编码在 `system.ts` 的两个 base prompt 模板中：
- `DEFAULT_CLINE_SYSTEM_PROMPT`（L7-13）含 `<env>` 段
- `YOLO_CLINE_SYSTEM_PROMPT`（L52-58）含 `<env>` 段

`buildClineSystemPrompt`（cline.ts L110-166）的模板选择逻辑（L138-139）：
```typescript
const basePrompt =
    mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT;
```

- `mode === "yolo"` → YOLO 模板（含 env）
- `mode === "act"` / `"plan"` / `undefined` → DEFAULT 模板（含 env）

**结论**：无论 mode 取何值，选中的 base 模板均含 `<env>` 段，env 段**始终注入**。

唯一的例外是 `overridePrompt` 场景（cline.ts L126-136）：当 `overridePrompt` 非空时，直接返回 overridePrompt（可能拼接 metadata），跳过整个 base 模板，此时 env 段不注入。但这是 per-request 全量覆盖机制，不属于 env 段的条件注入逻辑。

**Charles `<env>` 注入条件分析**：

Charles 的 `<env>` 段硬编码在 `charles_system_prompt.py` 的两个 base prompt 模板中：
- `DEFAULT_CHARLES_SYSTEM_PROMPT`（L49-54）含 `<env>` 段
- `YOLO_CHARLES_SYSTEM_PROMPT`（L74-79）含 `<env>` 段

`select_base_template`（context.py L185-205）的模板选择逻辑：
```python
if mode == "yolo":
    return YOLO_CHARLES_SYSTEM_PROMPT
return DEFAULT_CHARLES_SYSTEM_PROMPT
```

- `mode == "yolo"` → YOLO 模板（含 env）
- `mode == "act"` / `"plan"` / `None` → DEFAULT 模板（含 env）

**结论**：无论 mode 取何值，选中的 base 模板均含 `<env>` 段，env 段**始终注入**。Charles 无 overridePrompt 机制，不存在跳过 base 模板的路径。

**对比结论**：两者注入条件**完全对齐** —— 均为 always 注入。

### 3.2 占位符替换条件对比（5.16.3）

**Cline 占位符替换**（cline.ts L153-157）：
```typescript
return basePrompt
    .replace("{{PLATFORM_NAME}}", platform)
    .replace("{{CWD}}", workspaceRoot)
    .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
    .replace("{{IDE_NAME}}", ide)
    .replace("{{CLINE_METADATA}}", isCline ? ... : "")
    .replace("{{CLINE_RULES}}", effectiveRules)
    .trim();
```

- env 相关的 4 个占位符（`{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}`）为**无条件 replace**
- metadata 占位符（`{{CLINE_METADATA}}`）有 `isCline ? ... : ""` 条件
- rules 占位符（`{{CLINE_RULES}}`）为无条件 replace

**Charles 占位符替换**（context.py L108-127）：
```python
prompt = prompt.replace("{{PLATFORM_NAME}}", platform_name)
prompt = prompt.replace("{{CURRENT_DATE}}", current_date)
prompt = prompt.replace("{{IDE_NAME}}", ide_name)
prompt = prompt.replace("{{CWD}}", working_dir)
prompt = prompt.replace("{{CHARLES_RULES}}", rules_text)
if should_inject_metadata(provider_id):
    prompt = prompt.replace("{{CHARLES_METADATA}}", metadata_text)
else:
    prompt = prompt.replace("{{CHARLES_METADATA}}", "")
```

- env 相关的 4 个占位符为**无条件 replace**
- rules 占位符为无条件 replace
- metadata 占位符有 `should_inject_metadata(provider_id)` 条件

**对比结论**：两者 env 占位符替换**完全对齐** —— 均为无条件 replace。条件门控仅作用于 metadata 段，不作用于 env 段。

### 3.3 与 metadata 条件注入的边界区分（5.16.4）

**关键澄清**：P5.16 的 env 段条件注入与 P5.17 的 metadata 段条件注入是两个独立维度，不应混淆。

| 维度 | env 段（P5.16） | metadata 段（P5.17） |
|------|----------------|---------------------|
| Cline 注入条件 | always（无条件） | `isClineProvider(providerId)`（仅 cline/cline-pass） |
| Charles 注入条件 | always（无条件） | `should_inject_metadata(provider_id)` → `is_charles_provider`（白名单） |
| 条件门控位置 | 无 | cline.ts L124 / context.py L122-125 |
| 一致性 | 完全对齐 | L4 差距（P5.17 详查） |

**结论**：env 段的条件注入逻辑（无门控）与 metadata 段的条件注入逻辑（有 provider 门控）是分离的。env 段不继承、不依赖 metadata 段的 provider 判断 —— 即使 provider 不在白名单（metadata 不注入），env 段仍正常注入。

### 3.4 overridePrompt 场景差异（5.16.6）

**Cline overridePrompt 机制**（cline.ts L126-136）：
```typescript
if (overridePrompt?.trim()) {
    const trimmed = overridePrompt.trim();
    if (isCline && metadata?.trim() && !trimmed.includes(WORKSPACE_CONFIGURATION_MARKER)) {
        return `${trimmed}\n\n${buildWorkspaceMetadata(...)}`.trim();
    }
    return trimmed;
}
```

当 `overridePrompt` 非空时：
- 跳过 base 模板选择（L138-139 不执行）
- 跳过 env 占位符替换（L154-157 不执行）
- 直接返回 overridePrompt（可能拼接 metadata）
- **env 段不注入**（除非 overridePrompt 自身含 env 文本）

**Charles overridePrompt 机制**：无。`build_charles_system_prompt` 无 overridePrompt 参数，`SystemPromptBuilder.build` 无 override 逻辑。

**差异性质**：这是主机层 per-request 覆盖能力的差异，**非 env 段条件注入逻辑差异**。overridePrompt 是 Cline 提供的"用自定义 prompt 替换整个 system prompt"的逃生通道，属于高级覆盖机制；Charles 未实现此机制，env 段在任何请求中均通过 base 模板注入。

**严重程度**：低。Charles 不需要 overridePrompt 机制 —— 其 system prompt 组装完全由 `SystemPromptBuilder.build` 控制，无 per-request 覆盖需求。

---

## 四、nanobot 残留分析

### 4.1 env 段条件注入逻辑的 nanobot 残留

**结论**：**0 处实现逻辑残留**，**0 处注释残留**。

**检查依据**：
- `charles_system_prompt.py`（base 模板）：env 段模板与 Cline 一致，无条件注入逻辑，无 nanobot 风格。Grep 检索 `nanobot` 关键字：无匹配。
- `context.py::build_charles_system_prompt`（占位符替换）：env 占位符替换为无条件链式 replace，与 Cline 一致，无 nanobot 风格的条件分支。
- `context.py::select_base_template`（模板选择）：仅区分 yolo/非 yolo，与 Cline 一致，无 nanobot 风格的动态模板构建。

### 4.2 env 段周边代码的 nanobot 注释残留

**结论**：**1 处注释残留**，与 env 段条件注入无直接关系。

**残留详情**：
- `context.py` L275：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`
  - 位置：`SystemPromptBuilder.__init__` 的 `extra_sections` 参数 docstring
  - 性质：注释残留（非实现逻辑残留）
  - 与 env 段条件注入关系：**无**。`extra_sections` 是已废弃的参数，用于向 rules 段追加额外段落（L530-537），与 env 段的注入条件无关。
  - 严重程度：低
  - 此残留已在 P5.4 报告中记录，本报告仅做交叉验证确认。

### 4.3 注释残留 vs 实现逻辑残留汇总

| 类别 | 数量 | 位置 | 与 env 条件注入关系 | 严重程度 |
|---|---|---|---|---|
| 注释残留（env 条件注入相关） | 0 | — | — | 无 |
| 实现逻辑残留（env 条件注入相关） | 0 | — | — | 无 |
| 注释残留（env 段周边，extra_sections） | 1 | context.py L275 | 无（extra_sections 与 env 注入条件无关） | 低 |

---

## 五、与计划文件的差异说明

### 5.1 计划文件描述准确性

`AGENT_COMPARISON_PLAN_V2.md` L2099-2113 的 P5.16 段描述**与实际代码完全一致**，无需修正：

| 计划描述 | 实际代码验证 | 一致性 |
|---------|-------------|--------|
| Cline 实现：always 注入 | cline.ts L138-139 模板选择 + L154-157 无条件 replace | 一致 |
| Charles 实现：always 注入 | context.py L185-205 模板选择 + L111-114 无条件 replace | 一致 |
| 5.16.1 注入条件：always vs always，已对齐 | 两者均无 if 分支门控 env 段 | 一致 |
| 5.16.2 内容来源：system.ts vs charles_system_prompt.py，已对齐 | env 段均硬编码在对应 base 模板文件中 | 一致 |

### 5.2 计划文件未覆盖的维度

计划文件 P5.16 仅列 2 项对比（注入条件 + 内容来源），本报告补充以下维度：
- 5.16.3：env 占位符替换条件（两者均为无条件 replace）
- 5.16.4：provider 条件门控（两者均无，门控仅作用于 metadata）
- 5.16.5：mode 条件门控（两者均无，DEFAULT/YOLO 均含 env）
- 5.16.6：overridePrompt 场景（Cline 有，Charles 无；属主机层能力差异，非 env 条件注入差异）
- 5.16.7：模板缺失场景（两者均无空模板路径）

---

## 六、修复建议

### 6.1 P0 优先级（高严重程度）

无。env 段条件注入逻辑已完全对齐。

### 6.2 P1 优先级（中严重程度，影响一致性）

无。两者均为 always 注入，无差异需修复。

### 6.3 P2 优先级（低严重程度，工程优化）

#### P2-1: 清理 `extra_sections` 参数的 nanobot 注释（与 P5.4 P2-1 重复）

**影响范围**：`agent/context.py` L275、L292、L530-537

**问题**：`extra_sections` 参数已废弃（docstring 明确说"当前无调用方传入"），但保留参数签名和 `_build_rules` 中的处理逻辑（L530-537），且 docstring 提到 nanobot。此残留与 env 段条件注入无直接关系，但位于 env 段构建的同文件内。

**修复方案**：
1. 移除 `__init__` 的 `extra_sections` 参数（需确认无外部调用方）
2. 移除 `_build_rules` 中 L530-537 的 `extra_sections` 处理逻辑
3. 移除 L275 docstring 中的 nanobot 注释

**理由**：此建议与 P5.4 报告 P2-1 完全一致，本报告仅做交叉确认。是否清理由整体重构计划决定。

#### P2-2: 补充 overridePrompt 机制（可选，非必需）

**影响范围**：`agent/context.py` `build_charles_system_prompt` + `SystemPromptBuilder.build`

**问题**：Cline 提供 `overridePrompt` per-request 覆盖机制（cline.ts L126-136），Charles 无此机制。若未来需要 per-request 自定义 system prompt（如插件系统、测试场景），需补充。

**修复方案**：保持现状。Charles 当前无 per-request 覆盖需求，且补充此机制需改动 build 签名，与"不要 gold-plate"原则冲突。

**理由**：overridePrompt 是 Cline 的高级能力，非 env 段条件注入的核心逻辑。Charles 不需要此机制即可正常工作。

---

## 七、验证方法建议

### 7.1 自动化验证

1. **env 段始终注入验证（DEFAULT 模板）**：
   ```powershell
   python -c "
   from agent.context import SystemPromptBuilder
   builder = SystemPromptBuilder(working_dir='e:/jikeAI/code', ide_name='Charles Web')
   prompt = builder.build()
   assert '<env>' in prompt
   assert '</env>' in prompt
   assert 'Platform:' in prompt
   assert 'Date:' in prompt
   assert 'IDE:' in prompt
   assert 'Working Directory:' in prompt
   print('OK: DEFAULT 模板 env 段已注入')
   "
   ```

2. **env 段始终注入验证（YOLO 模板）**：
   ```powershell
   python -c "
   from agent.context import SystemPromptBuilder, select_base_template
   from agent.prompts.charles_system_prompt import YOLO_CHARLES_SYSTEM_PROMPT
   template = select_base_template('yolo')
   assert template == YOLO_CHARLES_SYSTEM_PROMPT
   assert '<env>' in template
   assert '</env>' in template
   print('OK: YOLO 模板 env 段已注入')
   "
   ```

3. **env 段不受 provider 条件门控验证**：
   ```powershell
   python -c "
   from agent.context import build_charles_system_prompt, select_base_template
   from agent.prompts.charles_system_prompt import DEFAULT_CHARLES_SYSTEM_PROMPT
   # 即使 provider 不在白名单（metadata 不注入），env 段仍应注入
   prompt = build_charles_system_prompt(
       base_template=DEFAULT_CHARLES_SYSTEM_PROMPT,
       platform_name='Windows', current_date='2026-07-29',
       ide_name='Charles Web', working_dir='e:/jikeAI/code',
       rules_text='', metadata_text='',
       provider_id='unknown_provider',
   )
   assert '<env>' in prompt
   assert 'Platform: Windows' in prompt
   assert '{{CHARLES_METADATA}}' not in prompt  # metadata 占位符被清空
   print('OK: env 段不受 provider 条件门控')
   "
   ```

4. **nanobot 残留检索**：
   ```powershell
   # 期望：env 段条件注入相关代码无 nanobot 残留
   # Grep pattern="nanobot" path="agent/prompts/charles_system_prompt.py"  # 期望无匹配
   # Grep pattern="nanobot" path="agent/context.py"                        # 期望仅 L275 一处（extra_sections 注释）
   ```

### 7.2 功能验证

1. **DEFAULT 模式验证**：启动 agent，打印 system prompt，确认 env 段始终存在（无论 provider 是 qwen/deepseek/openai/anthropic/charles 还是未知 provider）。
2. **YOLO 模式验证**：切换到 yolo 模式，打印 system prompt，确认 YOLO 模板 env 段与 DEFAULT 一致注入。
3. **provider 条件隔离验证**：传入不在白名单的 provider_id（如 `"unknown"`），确认 metadata 段不注入但 env 段仍正常注入。

### 7.3 回归验证

1. 运行 `tests/test_stage4_context_prompt.py`，确认现有测试通过。
2. 执行一轮对话，确认 LLM 能从 env 段正确读取平台/日期/IDE/工作目录信息，且 metadata 段的 provider 门控不影响 env 段。

---

## 八、附录：检查覆盖声明

- Cline `system.ts`：100% 完整审阅（68 行，重点 L7-13 / L52-58 env 段硬编码位置）
- Cline `cline.ts`：100% 完整审阅（166 行，重点 L110-166 buildClineSystemPrompt，区分 env 占位符替换 L154-157 无条件 vs metadata 占位符替换 L158-163 有 isCline 条件）
- Charles `charles_system_prompt.py`：100% 完整审阅（94 行，重点 L49-54 / L74-79 env 段硬编码位置）
- Charles `context.py` env 段条件注入相关代码：100% 审阅（L78-127 build_charles_system_prompt 占位符替换 + L185-205 select_base_template 模板选择 + L130-146 should_inject_metadata/is_charles_provider 边界确认）
- nanobot 残留检索：`agent/context.py` + `agent/prompts/charles_system_prompt.py` 全量 Grep，确认 env 段条件注入逻辑无 nanobot 残留，仅 L275 一处 extra_sections 注释残留（与 env 注入无关）
- 计划文件 P5.16 段：L2099-2113 完整审阅，与实际代码交叉验证，描述准确无需修正

本报告未修改任何源码，仅输出审计报告文件。
