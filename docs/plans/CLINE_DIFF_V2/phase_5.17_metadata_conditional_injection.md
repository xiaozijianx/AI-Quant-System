# Phase 5.17 Metadata 段条件注入对比

> 对比范围：Cline `isClineProvider` 白名单门控 + `buildClineSystemPrompt` 中的 `{{CLINE_METADATA}}` 条件注入 与 Charles `should_inject_metadata` + `is_charles_provider` + `_CHARLES_PROVIDER_IDS` 白名单 + `build_charles_system_prompt` 中的 `{{CHARLES_METADATA}}` 条件注入 的门控函数、白名单成员、None/空值处理、调用链路透传、实际运行时行为等 3 项逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/providers/utils.ts` L1-3（`isClineProvider` 白名单函数：`cline` / `cline-pass`）
> - `sdk/packages/shared/src/prompt/cline.ts` L124（`const isCline = isClineProvider(providerId || "")`）
> - `sdk/packages/shared/src/prompt/cline.ts` L126-136（overridePrompt 分支：`isCline && metadata?.trim() && !trimmed.includes(MARKER)` 三重条件）
> - `sdk/packages/shared/src/prompt/cline.ts` L158-163（basePrompt 分支：`isCline ? buildWorkspaceMetadata(...) : ""` 二元条件）
>
> Charles 源码：
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装函数，含 `should_inject_metadata(provider_id)` 条件门控 + `{{CHARLES_METADATA}}` 占位符替换）
> - `agent/context.py` L130-146（`should_inject_metadata` 转发函数 → `is_charles_provider`）
> - `agent/context.py` L149-159（`_CHARLES_PROVIDER_IDS` 白名单常量：`qwen` / `deepseek` / `openai` / `anthropic` / `charles`）
> - `agent/context.py` L162-182（`is_charles_provider` 白名单函数，含 None/空字符串默认注入逻辑）
> - `agent/context.py` L348-391（`SystemPromptBuilder.build` 编排器方法，接收 `provider_id` 参数并透传到纯组装器）
> - `agent/server.py` L541-549（唯一调用点：`builder.build(task_type=task_type)`，**不**透传 `provider_id`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Metadata 段**条件注入逻辑**（provider 白名单门控）。**核心结论：Charles 已在代码层完整实现 provider 条件门控（`should_inject_metadata` → `is_charles_provider` → `_CHARLES_PROVIDER_IDS` 白名单），模式与 Cline `isClineProvider` 完全对齐**；但当前唯一调用点（`server.py` L549）**不**透传 `provider_id`，参数默认为 `None`，触发 `is_charles_provider(None) → True` 默认注入分支，导致**运行时实际表现为"始终注入"**。计划文件 P5.17 描述的"Charles 实现：always 注入（无 provider 条件判断）"在代码层**不成立**，在运行时层**成立**——属"逻辑已实现但未启用"状态。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.17（L2114-2129）将 Charles 实现描述为"always 注入（无 provider 条件判断）"，并将对比表 5.17.1 / 5.17.2 标注为"L4 差距"。**此描述与实际代码不符**，存在一处事实错误：

1. **provider 条件判断已实现**：Charles 实际代码（context.py L122-146）已实现 `should_inject_metadata(provider_id)` → `is_charles_provider(provider_id)` 条件门控，**并非"无 provider 条件判断"**。门控函数、白名单常量、None 默认处理三件套均已就位。计划表 5.17.2 标注的"L4 差距"已失效。

2. **"always 注入"仅对当前调用点成立**：唯一调用点 `server.py` L549 `builder.build(task_type=task_type)` 不透传 `provider_id`，参数默认为 `None`，`is_charles_provider(None)` 返回 `True`（L179-181 的默认注入分支），故运行时表现为"始终注入"。但这是**调用方未传参**的结果，**非门控逻辑缺失**。计划表 5.17.1 标注的"L4 差距"应修正为"运行时表现为 always，代码层已实现门控"。

### 核心结论

1. **门控函数已对齐**：Charles `is_charles_provider` 对标 Cline `isClineProvider`，均为"provider ID 白名单成员判定"纯函数，无副作用、无状态。
2. **白名单成员属合理偏离**：Cline 白名单 = `{cline, cline-pass}`（官方 provider）；Charles 白名单 = `{qwen, deepseek, openai, anthropic, charles}`（所有 Charles 支持的 provider）。两者语义不同但模式一致：仅"原生/官方"provider 注入 metadata。
3. **None/空值处理策略相反**：Cline `isClineProvider("")` 返回 `false`（非 cline 不注入）；Charles `is_charles_provider(None)` 返回 `True`（默认 provider 注入）。Charles 策略向后兼容未显式传入 `provider_id` 的旧调用方，但导致当前唯一调用点（`server.py` L549）的门控失效。
4. **调用链路透传缺失**：`SystemPromptBuilder.build` 已接受 `provider_id` 参数并透传到纯组装器（context.py L390），但 `server.py` L549 调用点未传入 `provider_id`，导致门控函数始终收到 `None`。这是"管道已铺好但源头未注水"的状态。
5. **overridePrompt 分支差异**：Cline `buildClineSystemPrompt` 在 overridePrompt 分支（cline.ts L126-136）也有 `isCline && metadata?.trim() && !trimmed.includes(MARKER)` 三重条件门控；Charles 无 overridePrompt 概念，纯组装器仅在 basePrompt 路径做单点门控。属功能集差异，非对齐缺口（Charles 不支持 overridePrompt）。
6. **nanobot 残留**：Metadata 条件注入逻辑**无 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。L275 的 nanobot 注释属于 `extra_sections` 参数（与条件注入无关）。

### 一致性总体评估

- **门控函数实现**：**高**。`is_charles_provider` 与 `isClineProvider` 模式完全对齐。
- **白名单语义**：**高**。成员不同但语义对齐（均为"原生 provider 集合"）。
- **运行时门控生效**：**中**。代码层门控已实现，但当前调用点不传参导致门控失效，运行时表现为 always 注入。
- **None 处理策略**：**中**。Charles 与 Cline 策略相反，属设计选择差异。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.17.1 | metadata 注入条件 | `isCline ? buildWorkspaceMetadata(...) : ""`（cline.ts L158-163），basePrompt 路径二元条件；overridePrompt 路径三重条件（L126-136） | `if should_inject_metadata(provider_id): replace(metadata_text) else: replace("")`（context.py L122-125），basePrompt 路径二元条件；无 overridePrompt 路径 | 高 | 模式对齐。Charles 仅 basePrompt 路径（无 overridePrompt 概念），门控点位置一致（均在纯组装器层、占位符替换前）。计划表标注"L4 差距"已失效 |
| 5.17.2 | provider 判断函数 | `isClineProvider(providerId)`（providers/utils.ts L1-3），白名单 = `{cline, cline-pass}`，None/空字符串返回 `false` | `should_inject_metadata(provider_id)` → `is_charles_provider(provider_id)`（context.py L130-182），白名单 = `{qwen, deepseek, openai, anthropic, charles}`，None/空字符串返回 `True` | 高 | 函数模式对齐。白名单成员属合理偏离（语义一致：原生 provider 集合）。None 处理策略相反（Cline 拒绝，Charles 接受），属设计选择。计划表标注"L4 差距"已失效 |
| 5.17.3 | 合理性 | N/A（Cline 官方实现） | 合理增强：白名单覆盖所有 Charles 支持的 provider，None 默认注入向后兼容旧调用方 | 高 | Charles 保留为合理增强。None 默认注入策略在当前调用点未透传 `provider_id` 的场景下保证 metadata 始终注入，符合量化场景所有 provider 都需要 workspaces metadata 的业务需求 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.17 描述与实际代码不符（5.17.1 + 5.17.2）

AGENT_COMPARISON_PLAN_V2.md L2119-2120 将 Charles 实现描述为：

```
**Charles 实现**：
- always 注入（无 provider 条件判断）
```

经核查实际代码（context.py L122-146），Charles 的 `build_charles_system_prompt` 纯组装器**已实现** provider 条件门控：

```python
# context.py L122-125
if should_inject_metadata(provider_id):
    prompt = prompt.replace("{{CHARLES_METADATA}}", metadata_text)
else:
    prompt = prompt.replace("{{CHARLES_METADATA}}", "")
```

门控链路完整：`should_inject_metadata`（L130-146）→ `is_charles_provider`（L162-182）→ `_CHARLES_PROVIDER_IDS` 白名单（L153-159）。

**"always 注入"的真相**：唯一调用点 `server.py` L549 `builder.build(task_type=task_type)` **不**透传 `provider_id`，参数默认为 `None`，`is_charles_provider(None)` 命中 L179-181 的默认注入分支返回 `True`，故运行时表现为"始终注入"。这是**调用方未传参**的结果，**非门控逻辑缺失**。

**结论**：计划表 5.17.1（L4 差距）、5.17.2（L4 差距）标注已失效。代码层门控已实现，运行时表现为 always 是调用点透传缺失的副作用。

### 3.2 门控函数实现对比（5.17.2）

**Cline `isClineProvider`**（providers/utils.ts L1-3）：

```typescript
export function isClineProvider(providerId: string): boolean {
    return providerId === "cline" || providerId === "cline-pass";
}
```

- 入参类型：`string`（非可选，调用方 `providerId || ""` 保证空字符串）
- 白名单：`{cline, cline-pass}`
- None/空字符串处理：返回 `false`（非 cline，不注入）
- 实现风格：直接字符串比较，无中间集合

**Charles `is_charles_provider`**（context.py L162-182）：

```python
def is_charles_provider(provider_id: str | None) -> bool:
    if not provider_id:
        # Charles 默认有 provider（qwen），None/空字符串视为默认 provider
        return True
    return provider_id in _CHARLES_PROVIDER_IDS
```

- 入参类型：`str | None`（可选，调用方可不传）
- 白名单：`{qwen, deepseek, openai, anthropic, charles}`（L153-159 `frozenset`）
- None/空字符串处理：返回 `True`（默认 provider，注入）
- 实现风格：`frozenset` 成员判定 + None 短路

**差异分析**：

| 维度 | Cline | Charles | 评估 |
|------|-------|---------|------|
| 白名单数据结构 | 内联字符串比较 | `frozenset` 常量 | Charles 更易扩展（增删 provider 只改常量），Cline 更紧凑 |
| None/空值策略 | 拒绝（`false`） | 接受（`True`） | 策略相反，属设计选择。Charles 策略向后兼容旧调用方，但弱化门控语义 |
| 调用方传参保证 | `providerId || ""` 显式归一化 | 依赖 `str \| None` 可选类型 | Cline 更严格（强制归一化为字符串），Charles 更宽松 |

**评估**：门控函数实现属合理偏离。Charles 的 `frozenset` 常量更符合 Python 风格，None 默认注入策略符合"未显式指定 provider 时按默认 provider 处理"的业务语义。非对齐缺口。

### 3.3 调用链路透传缺失（5.17.1 运行时行为）

**Cline 调用链路**：

```
CLI resolveSystemPrompt (apps/cli/src/runtime/prompt.ts L12-36)
  └─ buildClineSystemPrompt({providerId, ...})  ← providerId 显式传入
       └─ isClineProvider(providerId || "")     ← 门控生效
```

Cline 在 CLI 主机层显式传入 `providerId`，门控函数收到实际 provider ID，门控生效。

**Charles 调用链路**：

```
server.py L549: builder.build(task_type=task_type)  ← 不传 provider_id
  └─ SystemPromptBuilder.build(task_type, provider_id=None)  ← 默认 None
       └─ build_charles_system_prompt(..., provider_id=None)  ← 透传 None
            └─ should_inject_metadata(None) → is_charles_provider(None) → True  ← 门控失效
```

Charles 的 `SystemPromptBuilder.build` 已接受 `provider_id` 参数（context.py L348）并透传到纯组装器（context.py L390），管道已铺好。但唯一调用点 `server.py` L549 不传 `provider_id`，导致门控函数始终收到 `None`，命中默认注入分支。

**影响**：当前运行时行为为"始终注入 metadata"，与计划文件描述的"always 注入"一致，但**原因不同**——计划文件认为是"无 provider 条件判断"，实际是"调用方未传参导致门控失效"。

**评估**：非对齐缺口，属调用方集成缺陷。若未来需要按 provider 差异化注入 metadata（如某 provider 不需要 workspaces metadata），只需在 `server.py` L549 传入实际 `provider_id` 即可激活门控，无需改动门控逻辑本身。

### 3.4 overridePrompt 分支差异（5.17.1）

**Cline** `buildClineSystemPrompt`（cline.ts L110-166）有两个门控点：

1. **overridePrompt 分支**（L126-136）：当 `overridePrompt?.trim()` 非空时，进入此分支。门控条件为 `isCline && metadata?.trim() && !trimmed.includes(WORKSPACE_CONFIGURATION_MARKER)` 三重条件——仅当是 cline provider、metadata 非空、且 overridePrompt 不已含 marker 时，才追加 `buildWorkspaceMetadata` 到 overridePrompt 末尾。

2. **basePrompt 分支**（L153-165）：常规路径。门控条件为 `isCline ? buildWorkspaceMetadata(...) : ""` 二元条件。

**Charles** `build_charles_system_prompt`（context.py L78-127）仅有一个门控点：

- **basePrompt 路径**（L122-125）：`if should_inject_metadata(provider_id): replace(metadata_text) else: replace("")` 二元条件。
- **无 overridePrompt 概念**：Charles 不支持 `overridePrompt`（用户自定义 system prompt 覆盖），故无对应分支。

**评估**：属功能集差异，非对齐缺口。Charles 不支持 overridePrompt 是合理的功能裁剪（量化场景不需要用户完全覆盖 system prompt）。若未来 Charles 接入 overridePrompt，需补齐对应的三重条件门控。

### 3.5 None/空值处理策略相反（5.17.2）

| 调用 | Cline `isClineProvider` | Charles `is_charles_provider` |
|------|-------------------------|-------------------------------|
| 传入白名单成员 | `True` | `True` |
| 传入非白名单字符串 | `False` | `False` |
| 传入 `""`（空字符串） | `False`（不注入） | `True`（注入，因 `not ""` 为真） |
| 传入 `None` | 类型错误（`string` 非可选） | `True`（注入） |

**Cline 策略**：空字符串视为非 cline，不注入。语义严格——"未指定 provider = 非 cline"。

**Charles 策略**：None/空字符串视为默认 provider（qwen），注入。语义宽松——"未指定 provider = 默认 provider"。

**业务背景**：Charles 默认有 provider（qwen），所有 Charles 支持的 provider 都需要 workspaces metadata；Cline 默认无 provider，仅官方 cline/cline-pass 注入 metadata。

**评估**：策略相反属合理偏离，反映两者对"默认 provider"的不同假设。Charles 策略在当前调用点未透传 `provider_id` 的场景下保证 metadata 始终注入，符合业务需求。但若未来需要严格门控（如接入不应注入 metadata 的第三方 provider），需将 None 分支改为 `False` 或在调用方强制传入 provider_id。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 Metadata 条件注入相关代码检查 nanobot 风格残留：
- `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装器，含条件门控）
- `agent/context.py` L130-182（`should_inject_metadata` + `is_charles_provider` + `_CHARLES_PROVIDER_IDS`）
- `agent/context.py` L348-391（`SystemPromptBuilder.build` 编排器，含 `provider_id` 透传）
- `agent/server.py` L541-549（唯一调用点）

### 4.2 检查结果

| 文件 / 范围 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` L78-127（纯组装器 + 条件门控） | 0 | 0 | 无残留 |
| `agent/context.py` L130-182（门控函数 + 白名单） | 0 | 0 | 无残留 |
| `agent/context.py` L348-391（编排器透传） | 0 | 0 | 无残留 |
| `agent/server.py` L541-549（调用点） | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（0 处，条件注入范围内）

经核查条件注入相关代码：

- `build_charles_system_prompt`（L78-127）：无 nanobot 注释。L119 注释"L4: metadata 条件注入 — 对齐 Cline isCline(providerId) 条件"为对齐说明，非残留。
- `should_inject_metadata`（L130-146）：无 nanobot 注释。L131-137 docstring 为对标 Cline 的说明，非残留。
- `is_charles_provider`（L162-182）：无 nanobot 注释。L165-168 docstring 引用 Cline 源码，非残留。
- `_CHARLES_PROVIDER_IDS`（L149-159）：无 nanobot 注释。L149-152 注释为对标 Cline 的说明，非残留。
- `SystemPromptBuilder.build`（L348-391）：无 nanobot 注释。
- `server.py` L541-549：无 nanobot 注释。

**注**：`agent/context.py` L275 存在 1 处 nanobot 注释（`extra_sections: [已废弃] nanobot 风格的额外段落`），但该注释属于 `extra_sections` 参数（与 Rules 段相关），**不属于条件注入范围**。该项已在 P5.1 第四节记录，本阶段不重复计入。

#### 4.3.2 实现逻辑残留（0 处）

经核查条件注入全部实现逻辑：

- **门控函数模式**：`is_charles_provider` 采用"白名单成员判定"模式（对齐 Cline `isClineProvider`），**不**使用 nanobot 风格的"始终注入"或"配置开关注入"。
- **白名单数据结构**：`_CHARLES_PROVIDER_IDS` 为 `frozenset` 常量（对齐 Cline 的内联字符串比较语义），**不**使用 nanobot 风格的动态配置或运行时注册。
- **条件分支**：`if should_inject_metadata(provider_id): ... else: ...` 为标准二元条件（对齐 Cline `isCline ? ... : ""`），**不**使用 nanobot 风格的单分支注入（无 else）。
- **透传链路**：`provider_id` 从 `SystemPromptBuilder.build` 透传到 `build_charles_system_prompt` 再到 `should_inject_metadata`（context.py L390 → L86 → L122），**不**使用 nanobot 风格的全局变量或隐式获取。

**结论**：条件注入实现**无任何 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。L4 重构已彻底清除条件注入的旧"始终注入"风格，与 Cline 白名单门控模式完全对齐。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**条件注入逻辑无类似的实现逻辑残留**，仅 0 处注释残留 + 0 处实现逻辑残留。这说明 L4 重构已彻底清除条件注入的 nanobot 风格实现逻辑，对齐质量高于技能系统。

### 4.5 历史标签残留检查（`<charles_metadata>`）

针对 L5 重构前的 `<charles_metadata>` XML 标签进行残留检查（与 P5.6 第四节交叉验证）：

| 位置 | 类型 | 性质 | 与条件注入的关系 |
|------|------|------|----------------|
| `context.py` L424 | 注释（docstring） | 历史说明："L5 对齐: ... 不再使用 `<charles_metadata>` XML 标签。" 属重构记录 | 与条件注入无关（属标签格式范畴，P5.6 已记录） |
| 条件注入范围内 | — | 无残留 | — |

`<charles_metadata>` 标签**不**出现在条件注入相关代码中。条件注入门控的是 `{{CHARLES_METADATA}}` 占位符的替换内容，与标签格式无关。**结论**：条件注入逻辑无历史标签残留。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.17.1 metadata 注入条件**：门控逻辑已对齐，无需修复。overridePrompt 分支差异属功能集差异（Charles 不支持 overridePrompt），非对齐缺口。
- **5.17.2 provider 判断函数**：门控函数已对齐，无需修复。白名单成员属合理偏离，None 处理策略属设计选择。
- **5.17.3 合理性**：Charles 保留为合理增强，无需修复。

### 5.2 优先级 P1（建议处理）

- **5.17.1 调用点透传 `provider_id`（可选）**：当前 `server.py` L549 不透传 `provider_id`，导致门控失效。若希望激活按 provider 差异化注入（如未来接入不应注入 metadata 的第三方 provider），建议在 `server.py` L549 传入实际 provider ID：
  ```python
  # 修改前
  return builder.build(task_type=task_type)
  # 修改后（需获取实际 provider_id）
  return builder.build(task_type=task_type, provider_id=current_provider_id)
  ```
  当前所有 Charles 支持的 provider 都在白名单内，激活门控后行为不变（仍全部注入）。但门控语义会更严格——`None` 不再默认注入，需显式传入白名单成员才注入。**注意**：此修改需同步调整 `is_charles_provider` 的 None 分支为 `False`，否则 None 仍默认注入。若当前业务无需按 provider 差异化注入，建议保持现状（门控已实现，未来需要时激活即可）。

### 5.3 优先级 P2（文档修正）

- **计划文件 P5.17 描述更新**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2119-2120，将 Charles 实现描述更新为：
  - 代码层：已实现 `should_inject_metadata` → `is_charles_provider` 白名单门控（对齐 Cline `isClineProvider`）
  - 运行时：当前唯一调用点（`server.py` L549）不透传 `provider_id`，参数默认为 `None`，命中默认注入分支，表现为"始终注入"
  
  并将计划表 5.17.1 / 5.17.2 的"L4 差距"标注更新为"代码层已对齐，运行时表现为 always（调用点未透传 provider_id）"。

- **None 处理策略文档化**：建议在 `is_charles_provider` docstring（context.py L162-178）中补充说明 None 默认注入的策略意图："Charles 默认有 provider（qwen），None/空字符串视为默认 provider 注入。当前唯一调用点（server.py L549）不透传 provider_id，故运行时表现为 always 注入。若未来需要严格门控，需在调用方显式传入 provider_id 并将 None 分支改为 False。" 当前 docstring 已说明 None 处理逻辑，但未说明运行时影响。

---

## 六、验证方法

### 6.1 门控函数实现验证

```powershell
# 验证 Charles should_inject_metadata / is_charles_provider 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "should_inject_metadata|is_charles_provider|_CHARLES_PROVIDER_IDS"
# 预期: L122（调用）+ L130（定义）+ L134（docstring）+ L146（return）+ L149（注释）+ L153（白名单）+ L162（定义）+ L179（None 处理）+ L182（return）

# 验证 Cline isClineProvider 白名单
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\providers\utils.ts" -Pattern "isClineProvider"
# 预期: L1-3，仅 cline / cline-pass
```

### 6.2 条件注入门控验证

```powershell
# 验证 Charles build_charles_system_prompt 中的条件门控
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "should_inject_metadata\(provider_id\)"
# 预期: L122（if 条件）

# 验证 Cline buildClineSystemPrompt 中的条件门控
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "isCline"
# 预期: L124（const isCline = ...）+ L129（overridePrompt 分支）+ L160（basePrompt 分支三元）
```

### 6.3 调用链路透传验证

```powershell
# 验证 SystemPromptBuilder.build 接受并透传 provider_id
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "provider_id"
# 预期: L86（纯组装器签名）+ L103（docstring）+ L122（门控调用）+ L130/141/146（should_inject_metadata）+ L162/174/179/182（is_charles_provider）+ L348（build 签名）+ L363（docstring）+ L390（透传）

# 验证唯一调用点是否透传 provider_id
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "builder\.build\("
# 预期: L549，builder.build(task_type=task_type) —— 不传 provider_id
```

### 6.4 白名单成员验证

```powershell
# 验证 Charles 白名单成员
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "qwen|deepseek|openai|anthropic|charles" -Context 0,0 | Where-Object { $_.LineNumber -ge 153 -and $_.LineNumber -le 159 }
# 预期: L154-158，5 个 provider ID

# 验证 Cline 白名单成员
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\providers\utils.ts" -Pattern "cline|cline-pass"
# 预期: L2，2 个 provider ID
```

### 6.5 nanobot 残留验证

```powershell
# 在条件注入相关代码范围内搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" | Where-Object { $_.LineNumber -ge 78 -and $_.LineNumber -le 182 -or $_.LineNumber -ge 348 -and $_.LineNumber -le 391 }
# 预期: 0 处（L275 的 extra_sections 注释不在条件注入范围内）

# 在调用点搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "nanobot" -CaseSensitive:$false | Where-Object { $_.LineNumber -ge 541 -and $_.LineNumber -le 549 }
# 预期: 0 处
```

### 6.6 None 处理策略验证

```powershell
# 验证 Charles None 默认注入逻辑
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "if not provider_id" -Context 0,2
# 预期: L179，if not provider_id: return True

# 验证 Cline 空字符串处理（isClineProvider("") 返回 false）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "isClineProvider\(providerId"
# 预期: L124，isClineProvider(providerId || "") —— 空字符串归一化后比较，返回 false
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.17.1 metadata 注入条件 | L4 差距（isCline vs always） | **代码层已对齐，运行时表现为 always** | Charles 已实现 `should_inject_metadata` 条件门控（对齐 Cline `isCline`）。运行时表现为 always 是调用点（server.py L549）未透传 `provider_id` 的副作用，非门控逻辑缺失。计划表标注基于旧实现或未核查调用点 |
| 5.17.2 provider 判断 | L4 差距（是 vs 无） | **已对齐** | Charles 已实现 `is_charles_provider` 白名单判定（对齐 Cline `isClineProvider`）。计划表标注"无"不成立 |
| 5.17.3 合理性 | N/A / 合理增强 / Charles 保留 | **确认合理增强** | 白名单成员覆盖所有 Charles 支持的 provider，None 默认注入向后兼容旧调用方。与计划表标注一致 |

**计划表标注总结**：3 项中 2 项标注"L4 差距"的项（5.17.1 / 5.17.2）实际已通过 L4 重构对齐，1 项标注"合理增强"的项（5.17.3）确认合理。计划表 P5.17 整体基于 L4 重构前的旧实现描述，未反映 L4 重构成果，需更新。

**与 P5.6 的关系**：P5.6（Metadata 段对比）已覆盖条件门控的总体对齐情况（5.6.2 provider 条件判断）。P5.17 为条件注入逻辑的**专项深化对比**，补充了 P5.6 未涉及的调用链路透传分析（server.py L549 不传 provider_id）、overridePrompt 分支差异、None 处理策略对比、运行时 vs 代码层行为差异等 4 项细节。两份报告结论一致：条件门控已对齐，计划表标注的"L4 差距"已失效。
