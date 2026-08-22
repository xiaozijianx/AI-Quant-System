# Phase 5.1 SystemPromptBuilder 架构对比

> 对比范围：Cline `buildClineSystemPrompt` 纯组装函数 + `composeSystemPrompt` 编排器方法 + CLI `resolveSystemPrompt` 主机包装层 与 Charles `build_charles_system_prompt` 纯组装函数 + `SystemPromptBuilder` 编排器类的架构职责分层差异；函数 vs 类范式、rules/metadata/skills 注入位置、模板渲染、占位符替换、条件注入等 8 项逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 纯组装函数，含模板选择 + effectiveRules 拼接 + 占位符替换 + isCline provider 条件门控）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L680-689（`composeSystemPrompt` 编排器方法，从 contributionRegistry 收集 rules）+ L103-116（`mergeSystemPromptRules` 合并函数）+ L795（调用点）
> - `apps/cli/src/runtime/prompt.ts` L12-36（`resolveSystemPrompt` 主机包装层，加载 metadata + 合并 rules + 调用 buildClineSystemPrompt）
> - `sdk/packages/shared/src/extensions/context.ts` L55-76（`WorkspaceContext` 接口，定义 rules/metadata/mode/ide 字段）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` 全文 740 行（**注**：计划文件 P5.1 将此文件标注为 SystemPromptBuilder 实现位置，实际此文件是 `DefaultRuntimeBuilder`，负责 tools/MCP/team 构建，**不**负责 system prompt 构建，计划文件描述有误）
>
> Charles 源码：
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装函数）+ L130-205（`should_inject_metadata` / `is_charles_provider` / `select_base_template` 辅助函数）+ L214-889（`SystemPromptBuilder` 编排器类，含 `build` / `_build_rules` / `_build_metadata` / `_build_enhancement_rules` 等方法）
> - `agent/prompts/charles_system_prompt.py`（`DEFAULT_CHARLES_SYSTEM_PROMPT` / `YOLO_CHARLES_SYSTEM_PROMPT` 模板，含 `{{CHARLES_RULES}}` / `{{CHARLES_METADATA}}` / `{{PLATFORM_NAME}}` 等占位符）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 SystemPromptBuilder 架构职责分层。**核心结论：Charles 已通过 A1 重构完成职责分层，与 Cline 的两层架构（纯组装函数 + 编排器）在概念上对齐**；剩余差异主要在于实现范式（Python 类 vs TypeScript 方法）、纯组装函数的职责边界（Charles 比 Cline 更"纯"）、skills 注入机制（Charles 作为 rules 注入 vs Cline 通过 extension/plugin 系统注册为工具）。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.1（L1737-1741）将 Cline 实现位置标注为 `runtime-builder.ts`，并称"`buildClineSystemPrompt()` 是纯组装函数"。**此描述存在两处事实错误**：

1. **文件位置错误**：`runtime-builder.ts` 是 `DefaultRuntimeBuilder` 类，负责 tools/MCP/team runtime 构建（L325-739），**不**包含 `buildClineSystemPrompt`，也**不**参与 system prompt 构建。实际的 `buildClineSystemPrompt` 位于 `sdk/packages/shared/src/prompt/cline.ts` L110-166。
2. **职责描述过简**：Cline 的 `buildClineSystemPrompt` 并非"纯组装函数"——它除了占位符替换，还**内部完成**模板选择（`mode === "yolo" ? YOLO : DEFAULT`）和 effectiveRules 拼接（`[rules, MODE_TAG_INSTRUCTIONS, PLAN_MODE_INSTRUCTIONS].filter(Boolean).join("\n\n")`）。相比之下，Charles 的 `build_charles_system_prompt` 将模板选择和 rules 拼接放在编排器层，纯组装函数**只做**占位符替换，职责更"纯"。

### 核心结论

1. **架构职责分层已对齐**（A1 重构）：Charles 已拆分为 `build_charles_system_prompt`（纯组装函数）+ `SystemPromptBuilder`（编排器类），对应 Cline 的 `buildClineSystemPrompt`（纯组装函数）+ `composeSystemPrompt`（编排器方法）+ CLI `resolveSystemPrompt`（主机包装层）。
2. **函数 vs 类范式差异**：Cline 纯组装器是 `function`、编排器是 class 的 `method`；Charles 纯组装器是 module-level `function`、编排器是独立 `class`。语义等价，范式略异。
3. **rules 加载位置已对齐**：两者均在编排器层加载 rules（Cline `composeSystemPrompt` 从 contributionRegistry 收集；Charles `SystemPromptBuilder._build_rules` 从磁盘 AGENTS.md + rules_dir 加载）。
4. **metadata 注入位置已对齐**：两者均在编排器层构建 metadata（Cline 在 CLI `resolveSystemPrompt` 调用 `buildWorkspaceMetadata`；Charles 在 `SystemPromptBuilder._build_metadata` 查询 git 状态）。
5. **skills 注入机制差异**：Cline skills 通过 `userInstructionPlugin` extension 注册为 `skills` 工具，**不**直接写入 system prompt；Charles skills 通过 `_build_enhancement_rules` 作为 rules 追加到 system prompt（受 `agent_config/system_prompt.yaml` 配置开关控制，默认关闭）。
6. **模板渲染 + 占位符替换已对齐**：两者均通过字符串 replace 完成占位符替换。
7. **条件注入已对齐**：Cline 用 `isClineProvider(providerId)` 门控 metadata 注入；Charles 用 `is_charles_provider(provider_id)` 门控（白名单语义不同但模式对齐）。
8. **nanobot 残留**：**1 处注释残留**（context.py L275 docstring），**0 处实现逻辑残留**。`extra_sections` 参数仅为向后兼容保留，无调用方传入。

### 一致性总体评估

- **架构分层**：**高**。A1 重构后 Charles 已完成纯组装器 + 编排器两层拆分。
- **职责边界**：**中-高**。Charles 纯组装器比 Cline 更"纯"（模板选择和 rules 拼接放在编排器），属设计差异非差距。
- **skills 注入**：**中**。机制不同（rules 注入 vs extension 工具注册），但 Charles 受配置开关控制默认关闭，与 Cline 默认行为接近。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.1.1 | 架构职责 | 两层：`buildClineSystemPrompt`（纯组装，cline.ts L110）+ `composeSystemPrompt`（编排器，session-runtime-orchestrator.ts L680）+ CLI `resolveSystemPrompt`（主机包装，prompt.ts L12） | 两层：`build_charles_system_prompt`（纯组装，context.py L78）+ `SystemPromptBuilder`（编排器类，context.py L214） | 高 | A1 重构后已对齐。计划表标注"A1 差距"已失效 |
| 5.1.2 | 函数 vs 类 | 纯组装器 = `export function`；编排器 = class 的 `private async method` | 纯组装器 = module-level `def`；编排器 = 独立 `class` | 高 | 范式略异但语义等价。Charles 编排器为独立类（含 `__init__` 状态），Cline 编排器为 orchestrator class 的方法 |
| 5.1.3 | rules 加载 | 编排器 `composeSystemPrompt` 从 `contributionRegistry.getRegisteredRules()` 收集（session-runtime-orchestrator.ts L682-687），CLI 层 `mergeRulesForSystemPrompt` 合并（prompt.ts L23） | 编排器 `SystemPromptBuilder._build_rules` 从磁盘加载 AGENTS.md + rules_dir + 注入 MODE_TAG/PLAN_MODE/enhancements（context.py L454-539） | 高 | 位置已对齐（均在编排器层）。数据源不同：Cline 从 contributionRegistry（extension 注册），Charles 从磁盘文件 |
| 5.1.4 | metadata 注入 | 主机包装层 `resolveSystemPrompt` 调用 `buildWorkspaceMetadata(input.cwd)` 加载 git 状态（prompt.ts L19），作为 `metadata` 参数传入 `buildClineSystemPrompt` | 编排器 `SystemPromptBuilder._build_metadata` 调用 `_read_git_state` 查询 git 状态（context.py L408-452），作为 `metadata_text` 传入 `build_charles_system_prompt` | 高 | 位置已对齐（均在编排器/主机层）。Cline 在 CLI 主机层，Charles 在 SystemPromptBuilder 类内 |
| 5.1.5 | skills 注入 | 通过 `userInstructionPlugin` extension 注册 `skills` 工具（runtime-builder.ts L411-435），**不**写入 system prompt；skills 元数据通过 `createExtension` 注入为 runtime extension | 通过 `_build_enhancement_rules` 将 always-skills 指令 + skills-summary 作为 rules 追加到 system prompt（context.py L611-647），受 `agent_config/system_prompt.yaml` 配置开关控制（默认关闭） | 中 | 机制不同。Cline skills 走 extension/tool 通道；Charles skills 走 rules 通道。Charles 默认关闭，开启时与 Cline 行为差异较大 |
| 5.1.6 | 模板渲染 | `buildClineSystemPrompt` 内部根据 `mode === "yolo"` 选择 `YOLO_CLINE_SYSTEM_PROMPT` 或 `DEFAULT_CLINE_SYSTEM_PROMPT`（cline.ts L138-139） | 编排器 `SystemPromptBuilder.build` 调用 `select_base_template(mode)`（context.py L185-205 + L378-379），再传入纯组装器 | 高 | 已对齐。Charles 模板选择在编排器层，Cline 在纯组装器内——Charles 更"纯" |
| 5.1.7 | 占位符替换 | `buildClineSystemPrompt` 内部 `basePrompt.replace("{{PLATFORM_NAME}}", ...)` 等 6 个占位符（cline.ts L153-165） | `build_charles_system_prompt` 内部 `prompt.replace("{{PLATFORM_NAME}}", ...)` 等 6 个占位符（context.py L108-127） | 高 | 完全一致。占位符命名不同（`{{CLINE_*}}` vs `{{CHARLES_*}}`），语义对齐 |
| 5.1.8 | 条件注入 | `isClineProvider(providerId || "")` 门控 `{{CLINE_METADATA}}` 注入（cline.ts L124 + L158-163），仅 `cline`/`cline-pass` 注入 | `should_inject_metadata(provider_id)` → `is_charles_provider(provider_id)` 门控 `{{CHARLES_METADATA}}` 注入（context.py L122-146），白名单含 `qwen`/`deepseek`/`openai`/`anthropic`/`charles` | 高 | 模式对齐。白名单成员不同（Cline 仅官方 cline/cline-pass；Charles 所有支持的 provider）。None/空字符串 Charles 视为默认 provider 注入，Cline 视为非 cline 不注入 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.1 文件位置标注错误（5.1.1）

AGENT_COMPARISON_PLAN_V2.md L1737 标注"Cline 实现（runtime-builder.ts）：`buildClineSystemPrompt()`"，经核查 `runtime-builder.ts`（全文 740 行）实际是 `DefaultRuntimeBuilder` 类，负责：

- 工具列表构建（`createBuiltinToolsList`，L126-161）
- MCP 工具加载（`loadConfiguredMcpTools`，L186-244）
- Agent Teams runtime 构建（`ensureTeamRuntime`，L545-643）
- 工具策略过滤（`filterAvailableTools`，L79-84）

该文件**完全不涉及 system prompt 构建**。实际的 Cline system prompt 构建链路为：

```
CLI resolveSystemPrompt (apps/cli/src/runtime/prompt.ts L12-36)
  ├─ buildWorkspaceMetadata(cwd)         ← 加载 git metadata
  ├─ mergeRulesForSystemPrompt(rules)    ← 合并 rules
  └─ buildClineSystemPrompt(options)     ← 纯组装（shared/prompt/cline.ts L110-166）
       ├─ 选择 base 模板（DEFAULT / YOLO）
       ├─ 拼接 effectiveRules（rules + MODE_TAG + PLAN_MODE）
       └─ 占位符替换（{{PLATFORM_NAME}} 等 6 个）

SessionRuntimeOrchestrator.composeSystemPrompt (session-runtime-orchestrator.ts L680-689)
  ├─ contributionRegistry.getRegisteredRules()  ← 收集 extension 注册的 rules
  └─ mergeSystemPromptRules(config.systemPrompt, rules)  ← 合并到既有 system prompt
```

Charles 对应链路为：

```
SystemPromptBuilder.build (agent/context.py L348-391)
  ├─ _build_rules(task_type)             ← 加载 AGENTS.md + rules_dir + MODE_TAG + PLAN_MODE + enhancements
  ├─ _build_metadata()                   ← 查询 git 状态构建 workspaces JSON
  ├─ _get_current_mode() → select_base_template(mode)  ← 选择 DEFAULT / YOLO
  └─ build_charles_system_prompt(...)    ← 纯组装（context.py L78-127）
       └─ 占位符替换（{{PLATFORM_NAME}} 等 6 个）
```

**结论**：Charles 已完成 A1 重构，架构分层与 Cline 对齐；计划文件 P5.1 的文件位置和"纯组装函数"描述需修正。

### 3.2 纯组装器职责边界差异（5.1.6 + 5.1.7）

Cline `buildClineSystemPrompt` 的职责边界**较宽**，包含三件事：

```typescript
// cline.ts L138-151
const basePrompt = mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT;
const effectiveRules = [rules, MODE_TAG_INSTRUCTIONS, mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined]
    .filter(Boolean).join("\n\n");
return basePrompt.replace(...).replace("{{CLINE_RULES}}", effectiveRules).trim();
```

1. 模板选择（`mode` → `DEFAULT` / `YOLO`）
2. effectiveRules 拼接（`rules` + `MODE_TAG_INSTRUCTIONS` + `PLAN_MODE_INSTRUCTIONS`）
3. 占位符替换

Charles `build_charles_system_prompt` 的职责边界**较窄**，只做一件事：

```python
# context.py L78-127
def build_charles_system_prompt(base_template, platform_name, current_date, ide_name,
                                working_dir, rules_text, metadata_text, provider_id=None):
    prompt = base_template
    prompt = prompt.replace("{{PLATFORM_NAME}}", platform_name)
    # ... 6 个占位符替换
    return prompt.strip()
```

模板选择（`select_base_template`）和 rules 拼接（`_build_rules` 含 MODE_TAG/PLAN_MODE 注入）均在编排器 `SystemPromptBuilder.build` 中完成。

**评估**：这是设计差异非差距。Charles 的纯组装器更"纯"（单一职责），Cline 的纯组装器内聚了模板选择和 rules 拼接。两者在职责分层上均合理，Charles 的拆分更彻底，不构成对齐缺口。

### 3.3 skills 注入机制差异（5.1.5）

这是本阶段**最主要的实质性差异**：

**Cline 方案**：skills 通过 extension 系统注册为 `skills` 工具，**不**写入 system prompt。
- `runtime-builder.ts` L411-435：`userInstructionService.createExtension` 创建 extension，注册 `skills` 工具 executor
- `runtime-builder.ts` L436-438：extension 加入 `runtimeExtensions`，由 AgentRuntime 加载
- skills 的 `description` 动态生成（`Object.defineProperty` getter），列出可用技能
- skills 指令在工具调用时按需注入（`skills` tool execute 返回 SKILL.md 内容）

**Charles 方案**：skills 通过 `_build_enhancement_rules` 作为 rules 追加到 system prompt。
- `context.py` L611-647：`_build_enhancement_rules` 生成 `charles-tools-overview` / `charles-always-skills` / `charles-skills-summary` 等 rule 段
- `context.py` L520-528：当 `enhancements.enabled=true` 时，这些段作为 rule 追加到 `Rules` 末尾
- `agent_config/system_prompt.yaml` 默认 `enabled: false`，与 Cline 默认行为接近

**差异影响**：
- Cline：skills 信息按需提供（LLM 调用 `skills` 工具时才看到指令），system prompt 更短
- Charles（开启 enhancements 时）：skills 概览始终在 system prompt 中，LLM 可直接看到技能目录和 always 指令，system prompt 更长

**评估**：Charles 默认关闭 enhancements 时与 Cline 行为接近；开启时为业务增强（量化场景需要 LLM 始终感知技能目录），属合理偏离，非 nanobot 残留。但 `charles-tools-overview` / `charles-mcp-overview` 段在 Cline 中无对应概念（Cline 工具列表由 tool definitions 动态提供，不写入 system prompt），建议在文档中明确标注此为 Charles 独有增强。

### 3.4 编排器调用频次差异

**Cline**：`composeSystemPrompt` 每轮调用，但仅做 rules 合并（`mergeSystemPromptRules`），base system prompt 在会话工厂（`cline-session-factory.ts`）一次性构建并缓存于 `config.systemPrompt`，每轮只追加 contributionRegistry 动态注册的 rules。

**Charles**：`SystemPromptBuilder.build` 每轮调用时**完整重建** system prompt（重新加载磁盘 rules、重新查询 git、重新选择模板、重新替换占位符）。

**影响**：Charles 每轮重复磁盘 I/O（读 AGENTS.md、扫 rules_dir、git 命令），Cline 仅首轮做完整构建。在 rules 目录文件较多或 git 仓库较大时，Charles 可能有性能开销。但 Charles 通过 `_build_rules` 内部的 `synchronize_rule_toggles` 缓存了部分状态，实际开销可控。

**评估**：非对齐缺口，属实现策略差异。Charles 的完整重建策略支持 rules 热更新（运行中修改 rules 文件即时生效），Cline 的缓存策略性能更优但不支持 rules 热更新。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 SystemPromptBuilder 架构相关文件检查 nanobot 风格残留：
- `agent/context.py`（全文 2666 行，含 `build_charles_system_prompt` + `SystemPromptBuilder` + `ContextCompactor`）
- `agent/prompts/charles_system_prompt.py`（base prompt 模板）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` |
| `agent/prompts/charles_system_prompt.py` | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（1 处）

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

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。不影响运行逻辑。

#### 4.3.2 实现逻辑残留（0 处）

经核查 `SystemPromptBuilder` 全部方法：

- `__init__`：`self.extra_sections = extra_sections or {}`（L292）—— 仅为兼容保留，无调用方传入
- `_build_rules` L530-537：遍历 `self.extra_sections.items()` 生成 `__extra__/{title}.md` rule —— **由于 `extra_sections` 默认为空 dict，此循环实际不执行**
- `build` / `_build_metadata` / `_build_enhancement_rules` / `_build_tools_section` / `_build_mcp_servers_section` / `_build_mode_tag_instructions` 等方法：**无 nanobot 风格实现逻辑**

**结论**：`extra_sections` 参数虽保留，但因默认为空 dict 且无调用方传入，**不产生任何实际效果**，属"死参数"，非实现逻辑残留。`_build_rules` L530-537 的遍历逻辑为死代码（永不执行），但语法上保留 nanobot 风格的"额外段落"概念。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留（`always` 预加载、`when_to_use` 字段、SKILL.md 三段式章节等）。**SystemPromptBuilder 架构层面无类似的实现逻辑残留**，仅 1 处注释残留 + 1 个死参数。这说明 A1 重构已彻底清除 SystemPromptBuilder 的 nanobot 风格实现逻辑。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.1.1 架构职责分层**：已对齐，无需修复。
- **5.1.3 rules 加载位置**：已对齐。
- **5.1.4 metadata 注入位置**：已对齐。
- **5.1.6 模板渲染**：已对齐。
- **5.1.7 占位符替换**：已对齐。
- **5.1.8 条件注入**：已对齐。

### 5.2 优先级 P1（建议处理）

- **5.1.2 函数 vs 类范式**：无需修复，范式差异属合理偏离。Charles 独立 `SystemPromptBuilder` 类便于状态管理（缓存 `_enhancements` 配置、`rules_dir`、`skills_registry` 等），Cline 编排器为 orchestrator class 方法依赖实例状态。

### 5.3 优先级 P2（可选优化）

- **5.1.5 skills 注入机制**：建议在 `_build_enhancement_rules` docstring 中明确标注"Charles 独有增强，Cline 通过 extension/tool 系统注册 skills 工具，不写入 system prompt"，避免后续对齐工作误判。当前 docstring（context.py L232-238）已说明"可选增强层"，但未明确与 Cline 的机制差异。

- **nanobot 注释残留**（context.py L275）：建议保留，作为历史说明。`extra_sections` 参数和 `_build_rules` L530-537 死代码可在未来 major 版本移除，当前保留不影响功能。

### 5.4 优先级 P3（文档修正）

- **计划文件 P5.1 文件位置标注错误**：建议修正 AGENT_COMPARISON_PLAN_V2.md L1737-1741，将 Cline 实现位置从 `runtime-builder.ts` 改为 `sdk/packages/shared/src/prompt/cline.ts` + `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`，并补充 CLI `resolveSystemPrompt` 主机包装层。

---

## 六、验证方法

### 6.1 架构分层验证

1. **纯组装器职责验证**：
   - Cline `buildClineSystemPrompt`（cline.ts L110-166）：检查函数签名 `ClineSystemPromptOptions` 入参含 `rules` / `metadata` / `mode` 等预加载数据，函数体内**不**读取磁盘、**不**查询 git、**不**加载 rules 目录。
   - Charles `build_charles_system_prompt`（context.py L78-127）：检查函数签名入参含 `rules_text` / `metadata_text` / `base_template` 等预加载数据，函数体内**仅**做 `prompt.replace` 占位符替换。

2. **编排器职责验证**：
   - Cline `composeSystemPrompt`（session-runtime-orchestrator.ts L680-689）：检查方法体内调用 `contributionRegistry.getRegisteredRules()` 收集 rules，调用 `mergeSystemPromptRules` 合并。
   - Charles `SystemPromptBuilder.build`（context.py L348-391）：检查方法体内调用 `_build_rules`（磁盘加载）、`_build_metadata`（git 查询）、`select_base_template`（模板选择），最后调用 `build_charles_system_prompt` 纯组装器。

### 6.2 nanobot 残留验证

```powershell
# 在 agent/context.py 中搜索 nanobot（应仅 1 处注释残留）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false

# 在 agent/prompts/charles_system_prompt.py 中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
```

### 6.3 占位符替换验证

```powershell
# 验证 Charles 占位符与 Cline 对齐（名称不同但数量和语义一致）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "\{\{[A-Z_]+\}\}"
# 应输出 6 个占位符: {{PLATFORM_NAME}} {{CURRENT_DATE}} {{IDE_NAME}} {{CWD}} {{CHARLES_RULES}} {{CHARLES_METADATA}}
```

### 6.4 死参数验证

```powershell
# 验证 extra_sections 无调用方传入（应仅在 __init__ 和 _build_rules 内部引用）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\*.py" -Pattern "extra_sections"
# 预期: context.py 内 3 处（__init__ 签名、docstring、_build_rules 遍历），其他文件 0 处
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.1.1 架构职责 | A1 差距（纯组装函数 vs 组装+加载 rules） | **已对齐** | A1 重构已完成，Charles 拆分为纯组装器 + 编排器 |
| 5.1.2 函数 vs 类 | 实现范式不同 | **范式差异**（非差距） | Charles 用独立 class，Cline 用 orchestrator method |
| 5.1.3 rules 加载 | 位置不同 | **已对齐** | 两者均在编排器层加载 |
| 5.1.4 metadata 注入 | 位置不同 | **已对齐** | 两者均在编排器/主机层构建 |
| 5.1.5 skills 注入 | 位置不同 | **机制差异** | Cline 走 extension/tool，Charles 走 rules（默认关闭） |
| 5.1.6 模板渲染 | 已对齐 | **已对齐** | — |
| 5.1.7 占位符替换 | 已对齐 | **已对齐** | — |
| 5.1.8 条件注入 | 位置不同 | **已对齐** | isClineProvider vs is_charles_provider 模式对齐 |

**计划表标注总结**：8 项中 5 项标注"差距/位置不同"的项实际已对齐或为合理差异，3 项标注"已对齐"的项确认对齐。计划表 P5.1 整体偏保守，未反映 A1 重构成果。
