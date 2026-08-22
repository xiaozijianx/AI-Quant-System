# Phase 5.11 Custom Instructions 段对比

> 对比范围：Cline 与 Charles 的 System Prompt 中 "Custom Instructions 段" 是否存在、内容来源、注入方式；区分注释残留与实现逻辑残留；nanobot 风格残留专项检查。
>
> 本阶段聚焦 Cline 的 "Custom Instructions" 段（即 `composeSystemPrompt()` 扩展 rule 合并机制）在 Charles 中的对应实现，深入到注册接口、加载链路、合并函数级别，区分"用户自定义指令字段"与"扩展 rule 合并机制"两个层次。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（buildClineSystemPrompt 纯组装器，本身不处理 Custom Instructions）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L103-116（mergeSystemPromptRules 合并扩展 rule）+ L680-689（composeSystemPrompt 编排器，遍历 contributionRegistry.getRegisteredRules()）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L220-277（createUserInstructionPlugin 扩展工厂）+ L238-242（registerRule 注册 `cline-user-instructions:rules`）
> - `sdk/packages/core/src/runtime/safety/rules.ts` L10-49（formatRulesForSystemPrompt + listEnabledRulesFromWatcher + loadRulesForSystemPromptFromWatcher）
> - `apps/vscode/src/core/storage/state-migrations.ts` L73-116（migrateCustomInstructionsToGlobalRules：历史 customInstructions 字段迁移到 `.clinerules/custom_instructions.md`）
> - `apps/vscode/src/extension.ts` L34 / L731-732（启动时调用迁移）
>
> Charles 源码：
> - `agent/context.py` L78-127（build_charles_system_prompt 纯组装器，无扩展合并层）+ L214-391（SystemPromptBuilder 编排器，无 register_rule 接口）+ L454-539（_build_rules 静态加载所有 rules）+ L530-537（extra_sections 已废弃消费逻辑，nanobot 风格残留）
> - `agent/rules_loader.py` L686-700（format_rules_content 统一 ## 标题格式）
> - `agent/prompts/charles_system_prompt.py` L29-91（base prompt 模板，无 Custom Instructions 占位符）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`（nanobot 原生无独立 Custom Instructions 段）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 中 "Custom Instructions 段" 的存在性、内容来源、注入方式。**核心结论：Charles 缺失 Cline 的 `composeSystemPrompt()` 扩展 rule 合并机制，无法在运行时通过插件 API 动态注册 rule 注入 system prompt 末尾；同时 Charles 也缺失 Cline 历史上的 `customInstructions` 用户配置字段（该字段在 Cline 中已被迁移到 `.clinerules/custom_instructions.md`）。Charles 的 `extra_sections` 参数虽在形态上类似，但属于 nanobot 风格的已废弃残留，不是 Cline 扩展 rule 机制的等价实现。**

### 核心结论

1. **存在性差异**：
   - **Cline**：**存在两层 Custom Instructions 机制**。(1) 扩展 rule 合并机制：`composeSystemPrompt()` 遍历 `contributionRegistry.getRegisteredRules()`，将扩展注册的 rule 内容用 `\n\n` 追加到 base system prompt 末尾；(2) 用户配置字段：历史 `globalState.customInstructions` 字段（VSCode 存储键），现已通过 `migrateCustomInstructionsToGlobalRules()` 一次性迁移到 `.clinerules/custom_instructions.md` 文件，由 user-instruction-watcher 加载并经 `cline-user-instructions:rules` 注册到扩展 rule 系统。
   - **Charles**：**两层均缺失**。无 `composeSystemPrompt()` 等价的扩展 rule 合并层；无 `customInstructions` 等价的用户配置字段；无 `registerRule()` 等价的动态注册接口。所有 rules 在 `SystemPromptBuilder._build_rules()` 中静态加载。

2. **内容来源差异**：
   - **Cline**：扩展 rule 内容由 `loadRulesForSystemPromptFromWatcher(watcher)` 动态加载，watcher 监听 `~/.clinerules/` 目录与 workspace `.clinerules/` 目录下的 rule 文件（含已迁移的 `custom_instructions.md`），通过 `listEnabledRulesFromWatcher` 过滤 `enabled=true` 的 rule，经 `formatRulesForSystemPrompt` 拼接为 `# Rules\n## rule_name\ninstructions` 格式。
   - **Charles**：rules 内容由 `_build_rules()` 静态加载：全局 `~/.agent/AGENTS.md` + workspace `agents_path` + `rules_dir` 目录 + MODE_TAG + PLAN_MODE + enhancements。无 watcher 监听机制，无运行时动态加载。

3. **注入方式差异**：
   - **Cline**：扩展 rule 通过 `mergeSystemPromptRules(basePrompt, additionalRules)` 在 base prompt 末尾追加（`${base}\n\n${additional}`），位于 `{{CLINE_METADATA}}` 之后。注入时机为 `composeSystemPrompt()` 在每次 run 开始时调用。
   - **Charles**：所有 rules 通过 `{{CHARLES_RULES}}` 占位符替换注入到 base prompt 内部（位于 `<env>` 段之后、`{{CHARLES_METADATA}}` 之前）。无运行时追加机制。

4. **段落位置勘误**：计划表 L2015 标注"段落位置 第 9 段"，但实际 Cline system prompt 顶层段仅 3 段（base + rules + metadata），扩展 rule 通过 `composeSystemPrompt()` 追加在末尾，是第 4 段（非第 9 段）。"第 9 段"可能是基于更早期 Cline 版本或对段落计数方式的不同理解。

5. **nanobot 残留**：Custom Instructions 段对比层面仅 **1 处注释残留**（`agent/context.py` L275 `extra_sections` 参数 docstring 提到 "nanobot 风格"），**0 处实现逻辑残留**。`extra_sections` 参数虽在形态上类似 Custom Instructions（接受调用方传入额外段落），但 docstring 明确标注"已废弃，当前无调用方传入"，属于 dead code 性质的 nanobot 注释残留，不是 Cline 扩展 rule 机制的等价实现。

### 一致性总体评估

- **Custom Instructions 段存在性**：**未对齐**（Cline 有两层机制，Charles 两层均缺失）
- **扩展 rule 注册接口**：**未对齐**（Cline 有 `api.registerRule()`，Charles 无）
- **扩展 rule 合并函数**：**未对齐**（Cline 有 `mergeSystemPromptRules()`，Charles 无）
- **用户配置字段**：**未对齐**（Cline 历史有 `customInstructions` 字段并已迁移，Charles 无）
- **注入位置**：**未对齐**（Cline 追加在 base 末尾，Charles 通过 `{{CHARLES_RULES}}` 占位符注入 base 内部）
- **加载机制**：**未对齐**（Cline watcher 动态加载，Charles 静态加载）
- **nanobot 残留**：1 处注释残留，0 处实现逻辑残留

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.11.1 | Custom Instructions 段存在性 | **存在**。两层机制：(1) `composeSystemPrompt()` 扩展 rule 合并（orchestrator.ts L680-689）；(2) 历史 `customInstructions` 用户配置字段（已迁移到 `.clinerules/custom_instructions.md`，state-migrations.ts L73-116） | **缺失**。无 `composeSystemPrompt()` 等价机制，无 `customInstructions` 等价字段，所有 rules 静态加载 | 未对齐 | Charles 两层均缺失；计划表 L2013 标注"是"准确 |
| 5.11.2 | 用户自定义指令内容来源 | `cline-user-instructions:rules` 扩展 rule，内容由 `loadRulesForSystemPromptFromWatcher(watcher)` 动态加载（rules.ts L45-49），watcher 监听 `~/.clinerules/` + workspace `.clinerules/` 目录 | 无等价机制。Charles rules 来源为 `~/.agent/AGENTS.md` + `agents_path` + `rules_dir` 静态加载（context.py L471-500） | 未对齐 | 计划表 L2014 标注"Charles 缺失"准确；Cline 的 watcher 机制是 Charles 没有的动态加载能力 |
| 5.11.3 | 段落位置 | 扩展 rule 通过 `mergeSystemPromptRules()` 追加在 base prompt 末尾（`${base}\n\n${additional}`，orchestrator.ts L113），位于 `{{CLINE_METADATA}}` 之后 | 无扩展 rule 段，无追加位置 | 未对齐 | 计划表 L2015 标注"第 9 段"与实际不符；实际是第 4 段（base + rules + metadata + 扩展 rule） |
| 5.11.4 | 扩展 rule 注册接口 | `api.registerRule({id, source, content})`（user-instruction-plugin.ts L238-242），由 `AgentExtension.setup(api)` 调用 | 无 `register_rule()` 接口。`SystemPromptBuilder` 无动态注册入口 | 未对齐 | Charles 无法在不修改代码的前提下通过插件动态注入 rule |
| 5.11.5 | 扩展 rule 合并函数 | `mergeSystemPromptRules(systemPrompt, rules)`（orchestrator.ts L103-116），用 `\n\n` 拼接 base 与 additional rules | 无等价合并函数。`build_charles_system_prompt()` 仅做占位符替换，不追加扩展 rules | 未对齐 | Charles 缺失合并层，所有 rules 在 `_build_rules()` 内部静态拼接 |
| 5.11.6 | rule 格式化函数 | `formatRulesForSystemPrompt(rules)`（rules.ts L10-21），输出 `# Rules\n## rule_name\ninstructions` 格式 | `format_rules_content(results)`（rules_loader.py L686-700），输出 `# Rules\n## rule_name\nbody` 格式 | 对齐 | 两者格式化函数输出结构一致（`# Rules` 标题 + `## rule_name` 子标题 + body） |
| 5.11.7 | rule 启用过滤 | `listEnabledRulesFromWatcher(watcher)` 通过 `isRuleEnabled(rule)` 过滤（rules.ts L35-43），按 `rule.name` 字典序排序 | `load_rules_directory()` 通过 `toggles` 字典 + frontmatter `mode/paths` 过滤（rules_loader.py），无字典序排序 | 部分对齐 | 两者均有启用/禁用过滤，但 Charles 额外支持 frontmatter 条件过滤（mode/paths），Cline 仅支持 enabled 字段 |
| 5.11.8 | 历史 customInstructions 字段迁移 | `migrateCustomInstructionsToGlobalRules(context)`（state-migrations.ts L73-116）：从 `globalState.customInstructions` 读取，写入 `~/.clinerules/custom_instructions.md`，然后清除 globalState 字段。启动时调用（extension.ts L731-732） | 无等价历史字段，无迁移逻辑 | 未对齐 | Cline 已废弃独立 customInstructions 字段，统一收敛到 Cline Rules 文件机制 |
| 5.11.9 | extra_sections 参数（Charles 独有） | 无等价参数 | `SystemPromptBuilder.__init__(extra_sections=None)`（context.py L255 / L292），消费逻辑在 `_build_rules()` L530-537 将 extra_sections 包装为 `__extra__/{title}.md` rule 注入。docstring 标注"已废弃，当前无调用方传入" | 未对齐 | Charles 的 `extra_sections` 形态上类似 Custom Instructions（接受调用方传入额外段落），但属于 nanobot 风格已废弃残留，非 Cline 扩展 rule 机制的等价实现 |

---

## 三、重点差距详细说明

### 3.1 Cline 的 Custom Instructions 两层机制（5.11.1 / 5.11.2 / 5.11.3 / 5.11.8）

Cline 的 Custom Instructions 实现包含两层，需要分别理解：

#### 第一层：扩展 rule 合并机制（架构层）

**注册入口**：`user-instruction-plugin.ts` L234-243
```typescript
async setup(api) {
    await watcherReady;
    if (options.includeRules) {
        api.registerRule({
            id: "cline-user-instructions:rules",
            source: "user-instruction-watcher",
            content: () => loadRulesForSystemPromptFromWatcher(options.watcher),
        });
    }
    // ...
}
```

**合并入口**：`session-runtime-orchestrator.ts` L680-689
```typescript
private async composeSystemPrompt(): Promise<string> {
    const rules: string[] = [];
    for (const rule of this.contributionRegistry.getRegisteredRules()) {
        const content = await resolveRuleContent(rule);
        if (content) {
            rules.push(content);
        }
    }
    return mergeSystemPromptRules(this.config.systemPrompt, rules);
}
```

**合并函数**：`session-runtime-orchestrator.ts` L103-116
```typescript
function mergeSystemPromptRules(
    systemPrompt: string,
    rules: ReadonlyArray<string>,
): string {
    const base = systemPrompt.trim();
    const additional = rules
        .map((rule) => rule.trim())
        .filter(Boolean)
        .join("\n\n");
    if (base && additional) {
        return `${base}\n\n${additional}`;
    }
    return base || additional;
}
```

**关键点**：
- `composeSystemPrompt()` 在每次 run 开始时调用（L795 `const systemPrompt = await this.composeSystemPrompt()`）。
- `contributionRegistry.getRegisteredRules()` 返回所有通过 `api.registerRule()` 注册的 rule，包括 `cline-user-instructions:rules`、`cline-hub-user-instructions:rules`（hub-client-contributions.ts L403-404）、plugin-sandbox 注册的 plugin rules（plugin-sandbox.ts L470-478）等。
- 合并位置在 base system prompt **末尾**，位于 `{{CLINE_METADATA}}` 之后。
- 这是 Cline 的**扩展点机制**：第三方扩展可在运行时动态注册 rule，无需修改 system prompt 组装代码。

#### 第二层：用户配置字段（数据层）

**历史字段**：VSCode `globalState.customInstructions` 字段，用户在 Cline 设置界面输入的自定义指令文本。

**迁移逻辑**：`state-migrations.ts` L73-116
```typescript
export async function migrateCustomInstructionsToGlobalRules(context: vscode.ExtensionContext) {
    const customInstructions = (await context.globalState.get("customInstructions")) as string | undefined
    if (customInstructions?.trim()) {
        const globalRulesDir = await ensureRulesDirectoryExists()
        const migrationFileName = "custom_instructions.md"
        const migrationFilePath = path.join(globalRulesDir, migrationFileName)
        // 写入或追加到 ~/.clinerules/custom_instructions.md
        await fs.writeFile(migrationFilePath, contentToWrite)
        // 清除 globalState.customInstructions 字段
        await context.globalState.update("customInstructions", undefined)
    }
}
```

**迁移触发**：`extension.ts` L731-732，VSCode 扩展启动时一次性调用。

**迁移后的加载链路**：
1. `~/.clinerules/custom_instructions.md` 文件被 user-instruction-watcher 监听
2. watcher 通过 `getSnapshot("rule")` 提供 RuleConfig 列表
3. `listEnabledRulesFromWatcher(watcher)` 过滤 `enabled=true` 的 rule（rules.ts L35-43）
4. `formatRulesForSystemPrompt(rules)` 格式化为 `# Rules\n## rule_name\ninstructions`（rules.ts L10-21）
5. `loadRulesForSystemPromptFromWatcher(watcher)` 组合上述两步（rules.ts L45-49）
6. `cline-user-instructions:rules` 扩展 rule 的 `content` 函数返回上述格式化文本
7. `composeSystemPrompt()` 通过 `mergeSystemPromptRules()` 追加到 system prompt 末尾

**关键澄清**：
- Cline 的 `customInstructions` 字段**已被废弃**，统一收敛到 Cline Rules 文件机制（`.clinerules/` 目录）。
- 迁移是**一次性**的：扩展启动时检测 `globalState.customInstructions` 是否非空，非空则写入文件并清除字段。
- 迁移后，用户自定义指令与普通 Cline Rules 文件无区别，统一通过 watcher 加载。

### 3.2 Charles 的缺失（5.11.1 / 5.11.4 / 5.11.5）

Charles 在 Custom Instructions 段对比中存在两层缺失：

#### 缺失一：扩展 rule 合并机制

**Charles 的 `build_charles_system_prompt()`**（context.py L78-127）仅做占位符替换：
```python
def build_charles_system_prompt(
    base_template, platform_name, current_date, ide_name,
    working_dir, rules_text, metadata_text, provider_id=None,
) -> str:
    prompt = base_template
    prompt = prompt.replace("{{PLATFORM_NAME}}", platform_name)
    # ... 其他占位符替换 ...
    prompt = prompt.replace("{{CHARLES_RULES}}", rules_text)
    if should_inject_metadata(provider_id):
        prompt = prompt.replace("{{CHARLES_METADATA}}", metadata_text)
    else:
        prompt = prompt.replace("{{CHARLES_METADATA}}", "")
    return prompt.strip()
```

**对比 Cline 的 `composeSystemPrompt()`**：
- Cline 在 `buildClineSystemPrompt()`（纯组装器）之后，额外调用 `mergeSystemPromptRules()` 追加扩展 rules。
- Charles 的 `build_charles_system_prompt()`（纯组装器）之后，**无任何追加逻辑**，直接返回 `prompt.strip()`。
- Charles 的 `SystemPromptBuilder.build()`（编排器，context.py L348-391）调用 `build_charles_system_prompt()` 后直接返回，无 `compose_system_prompt()` 等价的扩展合并步骤。

#### 缺失二：扩展 rule 注册接口

**Charles 的 `SystemPromptBuilder`**（context.py L214-300）无 `register_rule()` 方法：
```python
class SystemPromptBuilder:
    def __init__(
        self, identity="", agents_path=None, memory="", skills_registry=None,
        rules_dir=None, extra_sections=None, session_id=None, tools=None,
        working_dir=None, business_modes=None, rule_paths=None,
        rule_toggles=None, ide_name="Charles Web", config_path=None,
    ) -> None:
        # ... 静态参数初始化，无动态注册入口 ...
```

**对比 Cline 的 `AgentExtension.setup(api)`**：
- Cline 扩展通过 `api.registerRule({id, source, content})` 动态注册 rule。
- 注册的 rule 由 `contributionRegistry` 统一管理，`composeSystemPrompt()` 遍历合并。
- Charles 的 `SystemPromptBuilder` 无 `api` 对象，无 `contributionRegistry`，无动态注册入口。

#### Charles 的 `extra_sections` 参数不是等价实现

`SystemPromptBuilder.__init__(extra_sections=None)`（context.py L255）虽然接受调用方传入额外段落，但：
1. **调用时机不同**：`extra_sections` 在 `__init__()` 时静态传入，非运行时动态注册。
2. **来源不同**：`extra_sections` 由调用方在编译时确定，非 watcher 动态加载。
3. **使用状态**：docstring 明确标注"已废弃，当前无调用方传入"（context.py L275-276），属于 dead code。
4. **设计来源**：docstring 标注"nanobot 风格的额外段落"（context.py L275），溯源到 nanobot 设计模式，非 Cline 扩展 rule 机制。

因此 `extra_sections` 不是 Cline 扩展 rule 机制的等价实现，仅是形态上类似的已废弃残留。

### 3.3 段落位置勘误（5.11.3）

计划表 L2015 标注 Cline 的 Custom Instructions 段位置为"第 9 段"，但实际 Cline system prompt 顶层段仅 3-4 段：

```
[C-1] Base Prompt（identity + 通用规则 + <env>）
[C-2] {{CLINE_RULES}} → effectiveRules（caller rules + MODE_TAG + PLAN_MODE?）
[C-3] {{CLINE_METADATA}} → workspace metadata
[C-4] 扩展 rule（composeSystemPrompt 追加，含 cline-user-instructions:rules）
```

扩展 rule（即 Custom Instructions 段）实际是第 4 段，非第 9 段。"第 9 段"可能是基于以下误解：
- 将 effectiveRules 内部的子段（caller rules / MODE_TAG / PLAN_MODE）拆分计数
- 将 base prompt 内部的子段（identity / 通用规则 / <env>）拆分计数
- 基于更早期 Cline 版本的不同段落结构

实际源码中，扩展 rule 始终追加在 base prompt 末尾（`{{CLINE_METADATA}}` 之后），是最后一个顶层段。

### 3.4 Charles 的 rules 加载机制与 Cline 的对比（5.11.2 / 5.11.7）

虽然 Charles 缺失 Custom Instructions 段，但其 rules 加载机制与 Cline 的 user-instructions 加载机制存在部分对齐：

| 维度 | Cline | Charles |
|------|-------|---------|
| 全局 rules 文件 | `~/.clinerules/` 目录（含 `custom_instructions.md`） | `~/.agent/AGENTS.md` 单文件 |
| workspace rules | workspace `.clinerules/` 目录 | workspace `agents_path` + `rules_dir` 目录 |
| 加载方式 | watcher 动态监听 + `getSnapshot("rule")` | `_build_rules()` 静态读取 |
| 启用过滤 | `isRuleEnabled(rule)` 按 `enabled` 字段过滤 | `toggles` 字典 + frontmatter `mode/paths` 过滤 |
| 格式化 | `formatRulesForSystemPrompt()` 输出 `# Rules\n## name\ninstructions` | `format_rules_content()` 输出 `# Rules\n## name\nbody` |
| 排序 | 按 `rule.name` 字典序排序 | 无排序（按目录扫描顺序） |
| 注入位置 | 通过 `mergeSystemPromptRules()` 追加 base 末尾 | 通过 `{{CHARLES_RULES}}` 占位符注入 base 内部 |

**关键差异**：
- Cline 的 rules 加载是**动态**的（watcher 监听文件变化，运行时重新加载）；Charles 是**静态**的（每次 `build()` 时从磁盘读取，无 watcher）。
- Cline 的 rules 注入位置在 base **末尾**（`{{CLINE_METADATA}}` 之后）；Charles 注入位置在 base **内部**（`{{CHARLES_METADATA}}` 之前）。
- Cline 的全局 rules 是**目录**（`~/.clinerules/`）；Charles 的全局 rules 是**单文件**（`~/.agent/AGENTS.md`）。
- Charles 额外支持 frontmatter 条件过滤（`mode`/`paths`），Cline 仅支持 `enabled` 字段。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（1 处，1 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/context.py` | L275 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` | docstring 参数说明 |

**注释残留说明**：
- `extra_sections` 参数是 `SystemPromptBuilder.__init__()` 的一个已废弃参数（context.py L255 / L292）。
- docstring 明确标注"nanobot 风格的额外段落"，说明该参数源自 nanobot 设计模式。
- 参数保留仅为向后兼容，`_build_rules()` 中 L530-537 仍有消费逻辑（将 `extra_sections` 包装为 `__extra__/{title}.md` rule），但"当前无调用方传入"。
- 这是纯注释残留，删除 docstring 中的"nanobot 风格"描述不影响功能。

### 4.2 实现逻辑残留（0 处）

**Custom Instructions 段对比层面的实现逻辑残留：无**。

逐项验证：
- **Cline 扩展 rule 合并机制**（`composeSystemPrompt()` / `mergeSystemPromptRules()`）：Charles 无等价实现，无 nanobot 残留。
- **Cline 扩展 rule 注册接口**（`api.registerRule()`）：Charles 无等价接口，无 nanobot 残留。
- **Cline 用户配置字段迁移**（`migrateCustomInstructionsToGlobalRules()`）：Charles 无等价字段，无迁移逻辑，无 nanobot 残留。
- **Charles `extra_sections` 参数消费**（context.py L530-537）：虽然 docstring 标注"nanobot 风格"，但实现逻辑是将 extra_sections 包装为 rule 注入，这与 enhancement 机制设计一致，且"当前无调用方传入"，属于 dead code 性质，非活跃的 nanobot 实现残留。
- **Charles base prompt 模板**（charles_system_prompt.py L29-91）：无 Custom Instructions 占位符，无 nanobot 残留。
- **Charles `build_charles_system_prompt()` 纯组装器**（context.py L78-127）：无扩展合并层，无 nanobot 残留。
- **Charles `SystemPromptBuilder` 编排器**（context.py L214-391）：无 `register_rule()` 接口，无 nanobot 残留。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（docstring 提到 nanobot） | 1 处（context.py L275） | 低 | 可保留作为设计溯源参考，或统一清理 |
| 实现逻辑残留（Custom Instructions 段层面） | 0 处 | 无 | 无需处理 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（1 处）：context.py L275 docstring 中提到"nanobot 风格的额外段落"，这是设计溯源说明，删除后功能不变。

**实现逻辑残留**（0 处）：Custom Instructions 段对比层面无 nanobot 实现逻辑残留。具体来说：
- Cline 扩展 rule 机制：Charles 无等价实现，无 nanobot 复刻
- Cline 用户配置字段迁移：Charles 无等价字段，无 nanobot 复刻
- Charles `extra_sections` 参数：虽溯源 nanobot，但属于 dead code（无调用方传入），非活跃实现残留

**关联说明**：`extra_sections` 参数的 nanobot 注释残留与 P5.2 阶段 4.1 节发现的残留是同一处（context.py L275），本阶段不重复修复建议，统一在 P5.2 的 P2-1 修复建议中处理。

---

## 五、Custom Instructions 机制完整性矩阵

### 5.1 Cline Custom Instructions 机制清单

| 机制编号 | 机制名称 | 存在性 | 位置 | 注入条件 |
|---------|---------|--------|------|---------|
| CI-C-1 | 扩展 rule 合并函数 `mergeSystemPromptRules()` | 存在 | orchestrator.ts L103-116 | 始终存在（composeSystemPrompt 调用） |
| CI-C-2 | 扩展 rule 编排器 `composeSystemPrompt()` | 存在 | orchestrator.ts L680-689 | 每次 run 开始时调用 |
| CI-C-3 | 扩展 rule 注册接口 `api.registerRule()` | 存在 | plugin-sandbox-bootstrap.ts L85 / L478 | 扩展 setup 时调用 |
| CI-C-4 | user-instructions 扩展工厂 `createUserInstructionPlugin()` | 存在 | user-instruction-plugin.ts L220-277 | runtime-builder.ts L427-428 创建 |
| CI-C-5 | user-instructions rule 注册 `cline-user-instructions:rules` | 存在 | user-instruction-plugin.ts L238-242 | `includeRules=true` 时注册 |
| CI-C-6 | rule 加载函数 `loadRulesForSystemPromptFromWatcher()` | 存在 | rules.ts L45-49 | 注册的 content 函数调用 |
| CI-C-7 | rule 格式化函数 `formatRulesForSystemPrompt()` | 存在 | rules.ts L10-21 | loadRulesForSystemPromptFromWatcher 调用 |
| CI-C-8 | rule 启用过滤 `listEnabledRulesFromWatcher()` | 存在 | rules.ts L35-43 | loadRulesForSystemPromptFromWatcher 调用 |
| CI-C-9 | 历史 customInstructions 字段迁移 | 存在 | state-migrations.ts L73-116 | 扩展启动时一次性调用 |
| CI-C-10 | hub-client 扩展 rule 注册 `cline-hub-user-instructions:rules` | 存在 | hub-client-contributions.ts L403-404 | hub 连接时注册 |
| CI-C-11 | plugin-sandbox 扩展 rule 注册 | 存在 | plugin-sandbox.ts L470-478 | 插件 setup 时注册 |

### 5.2 Charles Custom Instructions 机制清单

| 机制编号 | 机制名称 | 存在性 | 位置 | 说明 |
|---------|---------|--------|------|------|
| CI-S-1 | 扩展 rule 合并函数 | **缺失** | — | 无 `merge_system_prompt_rules()` 等价函数 |
| CI-S-2 | 扩展 rule 编排器 | **缺失** | — | 无 `compose_system_prompt()` 等价方法 |
| CI-S-3 | 扩展 rule 注册接口 | **缺失** | — | 无 `register_rule()` 等价方法 |
| CI-S-4 | user-instructions 扩展工厂 | **缺失** | — | 无扩展工厂机制 |
| CI-S-5 | user-instructions rule 注册 | **缺失** | — | 无动态 rule 注册 |
| CI-S-6 | rule 动态加载函数 | **缺失** | — | 无 watcher，无动态加载 |
| CI-S-7 | rule 格式化函数 `format_rules_content()` | 存在 | rules_loader.py L686-700 | 静态加载时格式化，与 Cline CI-C-7 对齐 |
| CI-S-8 | rule 启用过滤 `load_rules_directory()` | 存在 | rules_loader.py | 通过 toggles + frontmatter 过滤，与 Cline CI-C-8 部分对齐 |
| CI-S-9 | 历史 customInstructions 字段迁移 | **缺失** | — | 无历史字段，无迁移逻辑 |
| CI-S-10 | hub-client 扩展 rule 注册 | **缺失** | — | 无 hub 机制 |
| CI-S-11 | plugin-sandbox 扩展 rule 注册 | **缺失** | — | 无插件沙箱机制 |
| CI-S-12 | `extra_sections` 参数（已废弃） | 存在（dead code） | context.py L255 / L292 / L530-537 | nanobot 风格残留，当前无调用方传入，非 Cline 扩展 rule 等价实现 |

### 5.3 机制存在性对比矩阵

| 机制类型 | Cline | Charles | 差异 |
|---------|-------|---------|------|
| 扩展 rule 合并函数 | 有（mergeSystemPromptRules） | **无** | Charles 缺失合并层 |
| 扩展 rule 编排器 | 有（composeSystemPrompt） | **无** | Charles 缺失编排层 |
| 扩展 rule 注册接口 | 有（api.registerRule） | **无** | Charles 缺失注册接口 |
| user-instructions 扩展 | 有（createUserInstructionPlugin） | **无** | Charles 缺失扩展工厂 |
| rule 动态加载 | 有（watcher + getSnapshot） | **无** | Charles 仅静态加载 |
| rule 格式化函数 | 有（formatRulesForSystemPrompt） | 有（format_rules_content） | 对齐 |
| rule 启用过滤 | 有（isRuleEnabled） | 有（toggles + frontmatter） | 部分对齐（Charles 额外支持 frontmatter） |
| 历史 customInstructions 迁移 | 有（migrateCustomInstructionsToGlobalRules） | **无** | Charles 无历史字段 |
| hub-client 扩展 rule | 有（cline-hub-user-instructions:rules） | **无** | Charles 无 hub 机制 |
| plugin-sandbox 扩展 rule | 有（plugin-sandbox registerRule） | **无** | Charles 无插件沙箱 |
| extra_sections 参数 | 无 | 有（已废弃，dead code） | Charles 独有，nanobot 风格残留 |

---

## 六、修复建议

### 6.1 高优先级（P1）

#### P1-1: 评估 Custom Instructions 扩展 rule 机制的补建必要性（5.11.1 / 5.11.4 / 5.11.5）

**问题**：Charles 缺失 Cline 的 `composeSystemPrompt()` 扩展 rule 合并机制，无法在运行时动态注册 rule。

**影响范围**：
- `agent/context.py` L78-127（`build_charles_system_prompt()` 纯组装器，无扩展合并层）
- `agent/context.py` L214-391（`SystemPromptBuilder` 编排器，无 `register_rule()` 接口）
- `agent/context.py` L348-391（`build()` 方法，无 `compose_system_prompt()` 步骤）

**修复方案**：
- **保留方案**（推荐）：Charles 当前所有 rules 静态加载，满足现有业务需求。若未来无插件化扩展 system prompt 的场景，可不补建。在 docstring 中明确标注"Charles 不支持运行时动态注册 rule，与 Cline composeSystemPrompt 机制不一致"。
- **补建方案**：若需对齐 Cline 的扩展能力，可在 `SystemPromptBuilder` 中新增：
  1. `register_rule(rule_id, content_provider)` 方法，将注册的 rules 存入 `self._registered_rules`
  2. `_compose_system_prompt(base_prompt)` 方法，将 `self._registered_rules` 追加到 base_prompt 末尾
  3. 在 `build()` 方法中调用 `_compose_system_prompt()` 完成扩展合并

**建议**：保留方案更务实（Charles 当前无扩展插件系统，无 hub 机制，无插件沙箱），但应在 `SystemPromptBuilder` 类 docstring 中明确标注架构差异。

### 6.2 中优先级（P2）

#### P2-1: 清理 extra_sections 已废弃参数的 nanobot 注释（4.1）

**影响范围**：`agent/context.py` L275（docstring）+ L255（参数签名）+ L292（初始化）+ L530-537（消费逻辑）

**修复方案**：
1. 若确认无调用方传入 `extra_sections`（docstring 已声明"当前无调用方传入"），可移除该参数及其消费逻辑（L530-537）。
2. 若保留参数以向后兼容，修正 docstring 移除"nanobot 风格"描述，改为"已废弃，保留参数签名仅为向后兼容"。

**理由**：用户规则"代码中不要有 fallback"和"生成的注释用中文"，docstring 中"nanobot 风格"是历史溯源，可统一清理。本项与 P5.2 阶段 P2-1 修复建议一致，统一处理。

#### P2-2: 勘误计划表的"第 9 段"标注（3.3）

**影响范围**：`AGENT_COMPARISON_PLAN_V2.md` L2015（5.11.3 项"段落位置"列）

**修复方案**：将"第 9 段"改为"第 4 段（base + rules + metadata + 扩展 rule）"或"末尾追加"。

**理由**：实际 Cline system prompt 顶层段仅 3-4 段，扩展 rule 通过 `mergeSystemPromptRules()` 追加在 base 末尾，是第 4 段而非第 9 段。

### 6.3 低优先级（P3）

#### P3-1: 补充 Custom Instructions 机制的架构文档（5.11.1 / 5.11.2）

**问题**：Charles 与 Cline 在 Custom Instructions 机制上的架构差异未在代码文档中明确说明。

**修复方案**：在 `SystemPromptBuilder` 类 docstring 中补充：
- "Charles 不支持运行时动态注册 rule（无 `register_rule()` 接口）"
- "Charles 不支持扩展 rule 合并（无 `compose_system_prompt()` 步骤）"
- "Charles 所有 rules 在 `_build_rules()` 中静态加载，与 Cline `composeSystemPrompt()` 动态合并机制不一致"

**理由**：明确架构差异有助于后续开发者理解 Charles 与 Cline 的设计取舍。

---

## 七、验证方法建议

### 7.1 Cline Custom Instructions 机制存在性验证

1. **扩展 rule 合并函数验证**：
   ```
   Grep "mergeSystemPromptRules" third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts
   # 预期：命中 L103（定义）+ L688（调用）
   ```

2. **扩展 rule 编排器验证**：
   ```
   Grep "composeSystemPrompt" third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts
   # 预期：命中 L680（定义）+ L795（调用）
   ```

3. **扩展 rule 注册接口验证**：
   ```
   Grep "registerRule" third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-plugin.ts
   # 预期：命中 L238（cline-user-instructions:rules 注册）
   ```

4. **历史 customInstructions 迁移验证**：
   ```
   Grep "migrateCustomInstructionsToGlobalRules" third_party/cline/apps/vscode/src/
   # 预期：命中 extension.ts L34（import）+ L732（调用）；state-migrations.ts L73（定义）
   ```

### 7.2 Charles Custom Instructions 机制缺失验证

1. **Charles 无扩展 rule 合并函数**：
   ```
   Grep "merge_system_prompt_rules|mergeSystemPromptRules" agent/context.py
   # 预期：0 命中
   ```

2. **Charles 无扩展 rule 编排器**：
   ```
   Grep "compose_system_prompt|composeSystemPrompt" agent/context.py
   # 预期：0 命中
   ```

3. **Charles 无扩展 rule 注册接口**：
   ```
   Grep "register_rule|registerRule" agent/context.py
   # 预期：0 命中
   ```

4. **Charles 无 customInstructions 字段**：
   ```
   Grep "customInstructions|custom_instructions" agent/
   # 预期：0 命中（Charles 无此字段）
   ```

### 7.3 nanobot 残留验证

1. **Custom Instructions 段层面 nanobot 残留**：
   ```
   Grep "nanobot" agent/context.py
   # 预期：命中 1 处（L275 extra_sections docstring）
   ```

2. **charles_system_prompt.py 无 nanobot 残留**：
   ```
   Grep "nanobot" agent/prompts/charles_system_prompt.py
   # 预期：0 命中
   ```

### 7.4 extra_sections dead code 验证

```python
# 验证 extra_sections 无调用方传入
Grep "extra_sections" agent/
# 预期：仅命中 context.py 内部（参数定义 + 初始化 + 消费逻辑），无外部调用
```

---

## 八、与 P5.2 及其他阶段的衔接

### 8.1 与 P5.2 的衔接

P5.2（System Prompt 段落清单对比）在 5.2.9 项已发现 Custom Instructions 段缺失，本阶段（P5.11）在段落清单基础上深入到机制级别，**确认并细化了以下发现**：

| P5.2 发现 | P5.11 深化 |
|----------|----------|
| Charles 缺失 `composeSystemPrompt()` 扩展 rule 合并机制 | 确认缺失两层机制：(1) 扩展 rule 合并机制（`mergeSystemPromptRules` + `composeSystemPrompt`）；(2) 历史 `customInstructions` 用户配置字段（已迁移到 `.clinerules/custom_instructions.md`） |
| Charles 无 `registerRule()` 等价的动态注册接口 | 确认 Charles 的 `extra_sections` 参数不是等价实现（dead code，nanobot 风格残留） |
| Charles 所有 rules 在 `_build_rules()` 中静态加载 | 确认 Charles 缺失 watcher 动态加载机制，rules 来源为 `~/.agent/AGENTS.md` 单文件（vs Cline `~/.clinerules/` 目录） |

### 8.2 与 P5.1 的衔接

| P5.1 发现 | P5.11 衔接 |
|----------|----------|
| 两者均采用 base + rules + metadata 三层骨架 | 确认 Cline 在三层骨架之外有第 4 层"扩展 rule"（通过 `composeSystemPrompt()` 追加），Charles 无第 4 层 |
| Charles 的 `build_charles_system_prompt()` 是纯组装器 | 确认纯组装器无扩展合并层，与 Cline `buildClineSystemPrompt()` 一致；差异在编排器层（Cline `composeSystemPrompt()` 有扩展合并，Charles `SystemPromptBuilder.build()` 无） |

### 8.3 本阶段新增发现（P5.1 / P5.2 未覆盖）

1. **Cline 历史 customInstructions 字段迁移机制**（5.11.8）：`migrateCustomInstructionsToGlobalRules()` 将 VSCode `globalState.customInstructions` 一次性迁移到 `~/.clinerules/custom_instructions.md`，这是 P5.2 未覆盖的发现。
2. **Cline 扩展 rule 注册的多个来源**（5.11.4）：除 `cline-user-instructions:rules` 外，还有 `cline-hub-user-instructions:rules`（hub-client）和 plugin-sandbox 注册的 plugin rules，这是 P5.2 未细化的发现。
3. **Charles `extra_sections` 参数的 dead code 性质确认**（4.2）：虽溯源 nanobot，但"当前无调用方传入"，属于 dead code 而非活跃实现残留，这是 P5.2 未明确的发现。
4. **段落位置"第 9 段"勘误**（3.3）：计划表 L2015 标注与实际源码不符，实际是第 4 段（末尾追加）。
5. **rules 加载机制对比**（3.4）：Cline watcher 动态加载 vs Charles 静态加载，Cline 全局目录 vs Charles 全局单文件，这是 P5.2 未细化的发现。

---

## 附录：检查覆盖声明

- **Cline 源码**：
  - `sdk/packages/shared/src/prompt/cline.ts`（L1-166）：100% 完整审阅（buildClineSystemPrompt 纯组装器，不处理 Custom Instructions）
  - `sdk/packages/shared/src/prompt/system.ts`（L1-68）：100% 完整审阅（base prompt 模板，无 Custom Instructions 占位符）
  - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`（L95-116 / L680-689 / L795）：100% 完整审阅（mergeSystemPromptRules + composeSystemPrompt + 调用点）
  - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`（L220-277）：100% 完整审阅（createUserInstructionPlugin 扩展工厂 + registerRule 调用）
  - `sdk/packages/core/src/runtime/safety/rules.ts`（L1-49）：100% 完整审阅（formatRulesForSystemPrompt + listEnabledRulesFromWatcher + loadRulesForSystemPromptFromWatcher）
  - `apps/vscode/src/core/storage/state-migrations.ts`（L73-116）：100% 完整审阅（migrateCustomInstructionsToGlobalRules 迁移逻辑）
  - `apps/vscode/src/extension.ts`（L34 / L731-732）：关键段落审阅（迁移调用点）

- **Charles 源码**：
  - `agent/prompts/charles_system_prompt.py`（L1-94）：100% 完整审阅（base prompt 模板，无 Custom Instructions 占位符）
  - `agent/context.py`（L1-2666）：100% 完整审阅（含 SystemPromptBuilder + ContextCompactor，确认无扩展 rule 机制）
  - `agent/rules_loader.py`（L686-700 关键方法）：关键段落审阅（format_rules_content 格式化函数）

- **nanobot 溯源**：
  - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`：通过 P5.2 已审阅，本阶段引用结论

- **11 项对比项**（5.11.1 - 5.11.9）：100% 逐项核对

本报告未修改任何源码，仅输出审计报告文件。
