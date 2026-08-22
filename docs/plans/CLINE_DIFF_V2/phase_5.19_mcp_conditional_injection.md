# Phase 5.19 MCP 段条件注入对比

> 对比范围：Cline `runtime-builder.ts::loadConfiguredMcpTools` 的 MCP 工具加载条件门控（`disableMcpSettingsTools` + `hasMcpSettingsFile` + `registrations.disabled`）+ `cline.ts::buildClineSystemPrompt` 的 system prompt 模板渲染（无 MCP 占位符、无 MCP 段条件注入逻辑）与 Charles `SystemPromptBuilder._build_mcp_servers_section` + `_build_enhancement_rules` + `_load_enhancements` 三层条件门控（`enhancements.enabled` 总开关 + `enhancements.mcp_section` 子开关 + `registry.list_servers()` 非空）+ `MCPRegistry.list_servers` 的 enabled 过滤；区分注释残留与实现逻辑残留；nanobot 风格残留专项检查。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（DEFAULT + YOLO 双模板，仅 `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 两个占位符，**无 MCP 占位符**）
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 仅替换 PLATFORM/CWD/DATE/IDE/RULES/METADATA 6 个占位符，**无 MCP 段条件注入逻辑**）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L186-244（`loadConfiguredMcpTools` MCP 工具加载门控：`hasMcpSettingsFile` 检查配置文件存在性 + `registrations.filter((r) => r.disabled !== true)` 过滤 enabled 服务器 + `createMcpTools` 展开为 `AgentTool[]`）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L293 + L310 + L453-456（`disableMcpSettingsTools` 配置项控制是否调用 `loadConfiguredMcpTools`，默认 `false` 即默认加载）
>
> Charles 源码：
> - `agent/context.py` L788-834（`SystemPromptBuilder._build_mcp_servers_section` 方法，构建 `# MCP 服务器` 段文本；L802-803 `if not servers: return ""` 空服务器时返回空字符串）
> - `agent/context.py` L611-647（`_build_enhancement_rules` 方法，L627-630 按 `mcp_section` 开关 + body 非空双条件把段文本作为 rule 追加，标题 `charles-mcp-overview`）
> - `agent/context.py` L304-346（`_load_enhancements` 读取 `agent_config/system_prompt.yaml` 的 `enhancements.mcp_section` 开关，L342 `result[key] = enabled and bool(cfg.get(key, True))` 总开关关闭时强制 false）
> - `agent/context.py` L520-528（`_build_rules` 第 6 步调用 `_build_enhancement_rules`，把增强层 rule 追加到 `{{CHARLES_RULES}}`）
> - `agent/mcp/registry.py` L227-231（`MCPRegistry.list_servers` 返回 `enabled=True` 的服务器）
> - `agent/mcp/registry.py` L458-501（`MCPRegistry.build_servers_summary` 同步等价方法，L474-476 `if not servers: return ""`）
> - `agent_config/system_prompt.yaml` L4-10（`enhancements.enabled=false` 总开关默认关闭，`mcp_section: true` 子开关）
> - `agent_config/mcp_servers.yaml` L38（`servers: []` 默认空列表）
> - `agent/prompts/charles_system_prompt.py` L29-91（base prompt 模板，**无 `{{CHARLES_MCP}}` 占位符**，MCP 段通过 Rules 增强层注入）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 MCP 段条件注入逻辑（何时注入、MCP 服务器为空时行为）。**核心结论：Cline 完全不存在 MCP 段条件注入逻辑（system prompt 中无任何 MCP 占位符、无任何 MCP 段构建逻辑），Charles 通过增强层实现了 MCP 段条件注入（默认关闭，需显式开启且需有 enabled 服务器）**；计划文件 P5.19 描述与实际代码严重不符，所列 2 项"已对齐"均不成立——Cline 模式下 MCP 工具通过 `createMcpTools` 展开为独立 LLM function（在工具列表中暴露，门控条件为 `disableMcpSettingsTools=false` + 配置文件存在 + 服务器 enabled），Charles 模式下 MCP 段通过三层条件门控注入 system prompt（`enhancements.enabled` + `enhancements.mcp_section` + `list_servers()` 非空），两者是**架构路径不同**而非"条件注入对齐"。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.19（L2146-2160）将 Cline 实现描述为"有 MCP 服务器时注入"，将 Charles 实现描述为相同内容。**此描述存在严重事实错误**：

1. **Cline 不存在 MCP 段条件注入**：经核查 Cline `system.ts`（base prompt 模板）仅含 `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 两个占位符，**无 `{{CLINE_MCP}}` 或任何 MCP 相关占位符**；`cline.ts::buildClineSystemPrompt` 仅替换 PLATFORM/CWD/DATE/IDE/RULES/METADATA 6 个占位符，**无 MCP 段条件注入逻辑**。MCP 工具通过 `runtime-builder.ts::loadConfiguredMcpTools` 调用 `createMcpTools` 展开为 `AgentTool[]` 注入到 `tools` 列表（运行时工具清单），而非 system prompt 文本段。Cline 的"条件"门控的是**工具加载**，不是**system prompt 段注入**。

2. **Charles MCP 段条件注入属"增强层"非"基础段"**：Charles 通过 `_build_mcp_servers_section`（context.py L788-834）构建 MCP 段文本，但该方法**需满足三层条件**才注入：
   - **第一层**：`enhancements.enabled=true`（总开关，默认 `false`）
   - **第二层**：`enhancements.mcp_section=true`（子开关，总开关关闭时强制 `false`）
   - **第三层**：`registry.list_servers()` 返回非空（即 `mcp_servers.yaml` 配置了 `enabled=true` 的服务器）

   注入位置是 `{{CHARLES_RULES}}` 末尾作为增强层 rule，**不是** base prompt 的独立占位符段。

3. **计划表 5.19.1 + 5.19.2 全部失效**：2 项对比项均标注"已对齐"，但实际均为"表面行为对齐、底层机制不同"：
   - 5.19.1 MCP 注入条件：Cline 是"工具加载条件"（门控 tools 列表），Charles 是"system prompt 段注入条件"（门控 Rules 增强层），**条件对象不同**，不存在"对齐"概念。
   - 5.19.2 无 MCP 时行为：Cline 是"段不存在所以不注入 + tools 列表为空"，Charles 是"段存在但三层条件未满足所以不注入"，**不注入的根因不同**。

### 核心结论

1. **MCP 段条件注入存在性**（5.19.1）：**严重不对齐**。Cline 不存在 MCP 段条件注入逻辑（system prompt 无 MCP 占位符，无 MCP 段构建逻辑）；Charles 存在三层条件门控的 MCP 段注入逻辑（默认关闭）。计划表标注"已对齐"失效。
2. **无 MCP 时行为**（5.19.2）：**表面对齐**。两者在无 MCP 服务器时都不向 system prompt 注入 MCP 内容。但 Cline 是"段不存在所以不注入 + tools 列表为空"，Charles 是"段存在但三层条件未满足所以不注入"。
3. **条件门控对象差异**：Cline 门控的是**工具加载**（`disableMcpSettingsTools` 控制 `loadConfiguredMcpTools` 是否调用），Charles 门控的是**system prompt 段注入**（`enhancements.mcp_section` 控制 `_build_mcp_servers_section` 是否调用）。两者门控对象根本不同。
4. **条件门控粒度差异**：Cline 仅 1 层门控（`disableMcpSettingsTools` 总开关，无单服务器粒度）；Charles 有 3 层门控（总开关 + 子开关 + 服务器列表非空）+ 单服务器 `enabled` 字段粒度。
5. **注入时机差异**：Cline 在 session 启动时由 `loadConfiguredMcpTools` 一次性加载（eager，工具列表在 session 生命周期内不变）；Charles 在每次 `SystemPromptBuilder.build()` 调用时构建（per-turn，但受增强层开关控制，且 `_tools_cache` 懒加载影响内容完整性）。
6. **nanobot 残留**：MCP 段条件注入实现**无 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。`agent/context.py` L275 的 nanobot 注释属于 `extra_sections` 参数（与 MCP 段条件注入无关），`agent/mcp/` 目录、`agent/tools/mcp.py`、`agent_config/mcp_servers.yaml` 均无 nanobot 残留。

### 一致性总体评估

- **段条件注入存在性**：**不对齐**（Cline 无段条件注入，Charles 有三层条件门控的段注入作为增强层）。
- **架构路径**：**根本不同**（Cline 工具加载门控 vs Charles system prompt 段注入门控）。
- **无 MCP 时表面行为**：**对齐**（两者都不向 system prompt 注入 MCP 内容）。
- **条件门控粒度**：**Charles 更细**（Charles 3 层 + 单服务器 enabled 粒度；Cline 1 层总开关 + 单服务器 disabled 字段）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.19.1 | MCP 注入条件 | **不适用**（Cline 不存在 MCP 段注入；MCP 工具通过 `loadConfiguredMcpTools` 展开为 `AgentTool[]` 注入 `tools` 列表；门控条件：`disableMcpSettingsTools=false` + `hasMcpSettingsFile=true` + 服务器 `disabled !== true`） | **三层条件门控**：①`enhancements.enabled=true`（总开关）+ ②`enhancements.mcp_section=true`（子开关）+ ③`registry.list_servers()` 返回非空（即有 `enabled=true` 的服务器配置）。三层全满足时调用 `_build_mcp_servers_section` 构建 `# MCP 服务器` 段文本，作为 rule 追加到 `{{CHARLES_RULES}}` | 不对齐 | 计划表标注"已对齐"失效。Cline 门控的是**工具加载**（门控 tools 列表），Charles 门控的是**system prompt 段注入**（门控 Rules 增强层），**条件对象不同**，不存在"对齐"概念 |
| 5.19.2 | 无 MCP 时行为 | **不注入 + tools 列表为空**。`disableMcpSettingsTools=true` 时跳过 `loadConfiguredMcpTools` 调用（runtime-builder.ts L453-456）；`hasMcpSettingsFile=false` 时 `loadConfiguredMcpTools` 返回 `{tools: []}`（L191-193）；`registrations` 全部 `disabled=true` 时 `enabled` 数组为空，`results` 为空，`tools` 为空数组（L217-236）。system prompt 不含任何 MCP 内容（段不存在） | **不注入**（三层条件任一不满足即不注入）：①`enhancements.enabled=false`（默认）→ 跳过整个增强层；②`enhancements.mcp_section=false` → 跳过 MCP 段；③`registry.list_servers()` 返回空列表（`mcp_servers.yaml::servers: []` 默认）→ `_build_mcp_servers_section` 返回 `""`，`_build_enhancement_rules` 因 `if body:` 跳过追加 | 表面对齐 | 表面行为对齐：两者在无 MCP 服务器时都不向 system prompt 注入 MCP 内容。但 Cline 是"段不存在所以不注入 + tools 列表为空"，Charles 是"段存在但三层条件未满足所以不注入"。底层机制不同 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.19 描述与实际代码严重不符（5.19.1 + 5.19.2）

AGENT_COMPARISON_PLAN_V2.md L2148-2157 将 Cline 与 Charles 实现描述为：

```
**Cline 实现**：
- 有 MCP 服务器时注入

**Charles 实现**：
- 有 MCP 服务器时注入

| 5.19.1 | MCP 注入条件 | 有 MCP 时 | 有 MCP 时 | 已对齐 |
| 5.19.2 | 无 MCP 时行为 | 不注入 | 不注入 | 已对齐 |
```

经核查 Cline 实际代码：

**证据 1 — system.ts 模板无 MCP 占位符**（sdk/packages/shared/src/prompt/system.ts L1-68）：

DEFAULT_CLINE_SYSTEM_PROMPT 与 YOLO_CLINE_SYSTEM_PROMPT 模板仅含以下占位符：
- `{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}`（env 段）
- `{{CLINE_RULES}}`（rules 段）
- `{{CLINE_METADATA}}`（workspace metadata 段）

**无 `{{CLINE_MCP}}` 或任何 MCP 相关占位符**，因此 system prompt 中**不存在 MCP 段条件注入的位置**。

**证据 2 — cline.ts 无 MCP 段条件注入逻辑**（sdk/packages/shared/src/prompt/cline.ts L153-165）：

```typescript
return basePrompt
    .replace("{{PLATFORM_NAME}}", platform)
    .replace("{{CWD}}", workspaceRoot)
    .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
    .replace("{{IDE_NAME}}", ide)
    .replace(
        "{{CLINE_METADATA}}",
        isCline
            ? buildWorkspaceMetadata(workspaceRoot, workspaceName, metadata)
            : "",
    )
    .replace("{{CLINE_RULES}}", effectiveRules)
    .trim();
```

6 个 `replace` 调用，**无 MCP 段条件替换**。`isCline` 条件门控的是 `{{CLINE_METADATA}}`（workspace metadata），**不是 MCP 段**。

**证据 3 — runtime-builder.ts 走工具加载门控路径**（sdk/packages/core/src/runtime/orchestration/runtime-builder.ts L186-244 + L453-456）：

```typescript
async function loadConfiguredMcpTools(logger?: BasicLogger): Promise<{
    tools: AgentTool[];   // ← 工具列表，不是 system prompt 段
    shutdown?: () => Promise<void>;
}> {
    const settingsPath = resolveDefaultMcpSettingsPath();
    if (!hasMcpSettingsFile({ filePath: settingsPath })) {
        return { tools: [] };   // ← 无配置文件时返回空 tools 列表
    }
    // ...
    const enabled = registrations.filter((r) => r.disabled !== true);   // ← 过滤 enabled 服务器
    const results = await Promise.allSettled(
        enabled.map((r) =>
            createMcpTools({ serverName: r.name, provider: manager }),  // ← 展开为 AgentTool[]
        ),
    );
    // ...
}

// L453-456
if (!normalized.disableMcpSettingsTools) {
    const mcpRuntime = await loadConfiguredMcpTools(config.logger);
    tools.push(...mcpRuntime.tools);   // ← 注入到 tools 列表
    mcpShutdown = mcpRuntime.shutdown;
}
```

Cline 的"条件门控"门控的是**工具加载**（`disableMcpSettingsTools` 控制 `loadConfiguredMcpTools` 是否调用），MCP 工具通过 `createMcpTools` 展开为 `AgentTool[]`，注入到 runtime 的 `tools` 列表（即 LLM function 列表），**不注入 system prompt 文本**。

**结论**：计划表 5.19.1 标注的"已对齐"失效。Cline 走"工具加载门控"路径，Charles 走"system prompt 段条件注入"路径，两者是**架构路径根本不同**，不存在"条件注入对齐"概念。该差异已在 Phase 5.7 报告（CLINE_DIFF_V2/phase_5.7_mcp_overview_section.md）中详细记录，本阶段确认 P5.19 计划描述与 P5.7 结论不一致。

### 3.2 Charles MCP 段条件注入的三层门控链路（5.19.1）

Charles MCP 段条件注入的完整链路：

```
SystemPromptBuilder.build()
  → _build_rules(task_type)                         # context.py L454-539
      → step 6: if self._enhancements.get("enabled"):       # 第一层：总开关
            _build_enhancement_rules()              # context.py L611-647
              → if self._enhancements.get("mcp_section"):   # 第二层：子开关
                    body = self._build_mcp_servers_section()    # context.py L788-834
                    # 第三层：服务器列表非空
                    # ↓ _build_mcp_servers_section 内部：
                    #   registry = get_registry()
                    #   servers = registry.list_servers()       # 仅返回 enabled=True 的服务器
                    #   if not servers: return ""               # 空列表时返回空字符串
                    if body:                                  # body 非空才追加
                        rules.append(("charles-mcp-overview", body))
  → format_rules_content(results)                   # 把所有 rule 拼接，加 ## 标题
  → build_charles_system_prompt(rules_text=...)      # 替换 {{CHARLES_RULES}}
```

**三层条件门控详解**：

| 层级 | 条件 | 位置 | 默认值 | 失败行为 |
|------|------|------|--------|---------|
| 第一层 | `enhancements.enabled=true` | context.py L521 | `false`（system_prompt.yaml L5） | 跳过整个增强层（含 tools/mcp/skills/memory 所有子段） |
| 第二层 | `enhancements.mcp_section=true` | context.py L627 | `true`（system_prompt.yaml L9，但总开关 `false` 时强制 `false`，L342） | 跳过 MCP 段构建 |
| 第三层 | `registry.list_servers()` 返回非空 | context.py L801-803（`if not servers: return ""`） | 空列表（mcp_servers.yaml L38 `servers: []`） | `_build_mcp_servers_section` 返回 `""`，`_build_enhancement_rules` 因 `if body:` 跳过追加（L629） |

**关键事实**：

1. **默认场景下 Charles 也不注入 MCP 段**：`agent_config/system_prompt.yaml` L5 `enhancements.enabled: false`，总开关关闭时所有子开关（含 `mcp_section`）强制 `false`（context.py L342 `result[key] = enabled and bool(cfg.get(key, True))`）。即**默认场景下 Charles 也不注入 MCP 概览段**，与 Cline 默认行为表面一致。

2. **`list_servers()` 的 enabled 过滤**：`MCPRegistry.list_servers()`（registry.py L227-231）返回 `[c for c in self._configs.values() if c.enabled]`，即仅返回 `enabled=True` 的服务器。`mcp_servers.yaml` L38 默认 `servers: []`（空列表），`list_servers()` 返回空列表，触发第三层门控失败。

3. **不是 base prompt 独立段**：MCP 段不是 base prompt 模板的独立占位符段（如 `{{CHARLES_MCP}}`），而是作为增强层 rule 追加到 `{{CHARLES_RULES}}` 末尾。最终在 `format_rules_content` 中被 `##` 标题包裹，与用户规则、MODE_TAG、PLAN_MODE、tools-overview、always-skills、skills-summary、memory 等 rule 共同构成 Rules 段。

4. **三层门控的短路求值**：第一层 `enabled=false` 时直接跳过 `_build_enhancement_rules` 整个方法，不会调用 `_build_mcp_servers_section`；第二层 `mcp_section=false` 时跳过 MCP 段构建，不会调用 `get_registry()`；第三层 `list_servers()` 返回空时 `_build_mcp_servers_section` 立即返回 `""`，不会遍历服务器。三层门控按顺序短路求值，避免不必要的计算。

**评估**：Charles 的三层条件门控是**合理增强**（在 Q11 单一 use_mcp_tool 架构下，LLM 必须通过 system prompt 才能知道有哪些 server/tool 可用，否则无法调用；但默认关闭以与 Cline 默认行为对齐）。该增强已在 Phase 5.7 报告中标记为"额外增强（架构上必要）"，本阶段确认该结论。

### 3.3 Cline `disableMcpSettingsTools` vs Charles 三层门控的语义差异（5.19.1 + 5.19.2 补充）

| 维度 | Cline | Charles |
|------|-------|---------|
| 配置项 | `disableMcpSettingsTools`（runtime-builder.ts L293, L310） | `enhancements.enabled`（system_prompt.yaml L5）+ `enhancements.mcp_section`（L9）+ `mcp_servers.yaml::servers[].enabled` |
| 控制对象 | 控制**工具加载**（`loadConfiguredMcpTools` 是否调用） | 控制**system prompt 段注入**（`_build_mcp_servers_section` 是否调用） |
| 默认值 | `false`（即默认加载 MCP 工具） | `enhancements.enabled=false`（即默认不注入 MCP 段） |
| 影响范围 | 工具不加载 → LLM 看不到任何 MCP 工具 function | 段不注入 → LLM 看不到 MCP 服务器列表（但 `use_mcp_tool` 工具本身仍存在） |
| 单服务器粒度 | `registrations.filter((r) => r.disabled !== true)` 支持单服务器 disabled 过滤 | `mcp_servers.yaml::servers[].enabled` 支持单服务器 enabled 过滤 |
| 配置文件不存在时行为 | `hasMcpSettingsFile=false` → `loadConfiguredMcpTools` 返回 `{tools: []}` | `system_prompt.yaml` 不存在 → `_load_enhancements` 返回全部 `false` 默认值（context.py L327-328） |
| 门控层级数 | 1 层（`disableMcpSettingsTools` 总开关） | 3 层（总开关 + 子开关 + 服务器列表非空） |

**关键差异**：

- Cline 的 `disableMcpSettingsTools=true` 时，MCP 工具完全不加载，LLM 无法调用任何 MCP 工具。
- Charles 的 `enhancements.enabled=false` 时，整个增强层（含 MCP 段）都不注入，但 `use_mcp_tool` 工具本身仍注册（LLM 仍可调用，但因不知道 server_name/tool_name 而实际无法使用）。
- Charles 的 `mcp_servers.yaml::servers[].enabled=false` 时，该服务器不进入 `list_servers()`，`_build_mcp_servers_section` 不列该服务器，`call_tool` 也会因配置不存在而报错。
- Cline 的 `registrations.filter((r) => r.disabled !== true)` 与 Charles 的 `list_servers()` 在单服务器粒度过滤上语义对齐（Cline 用 `disabled !== true` 即默认启用，Charles 用 `c.enabled` 即默认禁用——但 `mcp_servers.yaml` 的 `enabled` 字段默认 `true`，registry.py L58 `enabled: bool = True`，语义等价）。

**评估**：门控对象不同（Cline 门控工具加载，Charles 门控 system prompt 段注入），但 net 效果在"无 MCP 时"对齐（两者都不向 LLM 暴露 MCP 信息）。非对齐缺口，属架构路径差异。

### 3.4 Cline `loadConfiguredMcpTools` 的三段式条件检查（5.19.1 + 5.19.2 补充）

Cline `loadConfiguredMcpTools`（runtime-builder.ts L186-244）的三段式条件检查：

| 段号 | 条件 | 位置 | 失败行为 |
|------|------|------|---------|
| 1 | `hasMcpSettingsFile({ filePath: settingsPath })` | L191-193 | 返回 `{ tools: [] }`（无配置文件时） |
| 2 | `registerMcpServersFromSettingsFile(manager, { filePath: settingsPath })` 成功 | L204-215 | 捕获异常，`manager.dispose()`，返回 `{ tools: [] }`（配置文件解析失败时） |
| 3 | `registrations.filter((r) => r.disabled !== true)` 非空 | L217-236 | `enabled` 数组为空时 `results` 为空，`tools` 为空数组（所有服务器 disabled 时） |

**与 Charles 三层门控的对比**：

| 层级 | Cline 条件 | Charles 条件 | 等价性 |
|------|-----------|-------------|--------|
| 1 | `disableMcpSettingsTools=false`（外部门控） | `enhancements.enabled=true`（第一层门控） | **不等价**：Cline 门控工具加载，Charles 门控 system prompt 段注入 |
| 2 | `hasMcpSettingsFile=true`（配置文件存在） | `enhancements.mcp_section=true`（第二层门控） | **不等价**：Cline 检查配置文件存在性，Charles 检查子开关 |
| 3 | `registrations` 含 `disabled !== true` 的服务器 | `list_servers()` 返回非空（`enabled=True` 的服务器） | **语义等价**：两者都过滤 enabled 服务器，Cline 用 `disabled !== true`（默认启用），Charles 用 `c.enabled`（默认 `True`） |

**评估**：第三层条件语义等价（enabled 服务器过滤），但第一层和第二层条件对象不同（Cline 门控工具加载，Charles 门控 system prompt 段注入）。计划表 5.19.1 标注"已对齐"仅在看第三层时成立，但整体条件门控对象不同，不应标注"已对齐"。

### 3.5 Charles 懒连接策略对 MCP 段条件注入的副作用（5.19.1 补充）

Charles `_build_mcp_servers_section`（context.py L820-829）从 `registry._tools_cache` 读取工具列表：

```python
cached_tools = registry._tools_cache.get(srv.name, [])
if cached_tools:
    lines.append("工具:")
    for tool in cached_tools:
        desc = (tool.description or "").split("\n")[0][:80]
        lines.append(f"- {tool.name}: {desc}")
else:
    lines.append(
        "(工具列表未加载，调用 use_mcp_tool 时会自动连接并加载)"
    )
```

由于 Charles 采用真懒连接（Q12 增强），`_tools_cache` 在首次 `list_tools()` 调用前为空。这意味着：

- **首次构建 system prompt 时**（即使三层门控全满足），MCP 段会输出"(工具列表未加载，调用 use_mcp_tool 时会自动连接并加载)"，LLM 只知道服务器名不知道具体工具。
- **后续构建**（若已有 MCP 工具调用过）才会列出工具名 + 描述首行 80 字符。

Cline 模式下（eager connect for tool discovery），session 启动时 `loadConfiguredMcpTools` 主动调用 `createMcpTools` → `provider.listTools(serverName)` → `manager.listTools` → `refreshTools` → `ensureConnectedClient`，即**启动时连接所有 enabled 服务器并枚举工具**，LLM 立即看到完整工具列表（作为独立 LLM function）。

**影响**：Charles 的懒连接策略导致 MCP 概览段在首次构建时信息不完整，LLM 可能因不知道具体工具名而无法调用。Phase Q 报告差距 #Q16 已记录此问题，建议"在 `GET /mcp/servers` 调用时主动预加载工具 cache"或"首次构建 system prompt 时触发 `list_all_tools()` 预加载"。

**评估**：非对齐缺口（Cline 无此问题因走工具展开路径），属 Charles 架构选择（懒连接）的副作用。已在 Phase Q 记录，本阶段不重复修复建议。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 MCP 段条件注入相关文件检查 nanobot 风格残留：
- `agent/context.py` L304-346（`_load_enhancements` 配置读取，门控第一层 + 第二层）
- `agent/context.py` L520-528（`_build_rules` 第 6 步调用增强层，门控第一层入口）
- `agent/context.py` L611-647（`_build_enhancement_rules` 增强层装配，门控第二层）
- `agent/context.py` L788-834（`_build_mcp_servers_section` 方法，门控第三层）
- `agent/mcp/registry.py` L227-231（`list_servers` enabled 过滤，门控第三层数据源）
- `agent/mcp/registry.py` L458-501（`build_servers_summary` 同步等价方法）
- `agent/mcp/client.py`（MCP 客户端实现）
- `agent/mcp/name_transform.py`（名称转换）
- `agent/mcp/__init__.py`（模块入口）
- `agent/tools/mcp.py`（use_mcp_tool 工具实现）
- `agent/prompts/charles_system_prompt.py`（base prompt 模板，确认无 `{{CHARLES_MCP}}` 占位符）
- `agent_config/system_prompt.yaml`（增强层配置，门控第一层 + 第二层配置源）
- `agent_config/mcp_servers.yaml`（MCP 服务器配置，门控第三层数据源）

### 4.2 检查结果

| 文件 / 范围 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` L304-346（`_load_enhancements`） | 0 | 0 | 无残留 |
| `agent/context.py` L520-528（`_build_rules` 第 6 步） | 0 | 0 | 无残留 |
| `agent/context.py` L611-647（`_build_enhancement_rules`） | 0 | 0 | 无残留 |
| `agent/context.py` L788-834（`_build_mcp_servers_section`） | 0 | 0 | 无残留 |
| `agent/mcp/registry.py` L227-231（`list_servers`） | 0 | 0 | 无残留 |
| `agent/mcp/registry.py` L458-501（`build_servers_summary`） | 0 | 0 | 无残留 |
| `agent/mcp/client.py`（全文） | 0 | 0 | 无残留 |
| `agent/mcp/name_transform.py`（全文） | 0 | 0 | 无残留 |
| `agent/mcp/__init__.py`（全文） | 0 | 0 | 无残留 |
| `agent/tools/mcp.py`（全文） | 0 | 0 | 无残留 |
| `agent/prompts/charles_system_prompt.py`（全文 94 行） | 0 | 0 | 无残留 |
| `agent_config/system_prompt.yaml`（全文 10 行） | 0 | 0 | 无残留 |
| `agent_config/mcp_servers.yaml`（全文 86 行） | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（0 处，MCP 段条件注入范围内）

经核查 MCP 段条件注入相关代码：

- **`agent/mcp/` 目录全文搜索 `nanobot`**（大小写不敏感）：**0 处匹配**。`agent/mcp/__init__.py`、`agent/mcp/client.py`、`agent/mcp/registry.py`、`agent/mcp/name_transform.py` 均无 nanobot 注释。
- **`agent/tools/mcp.py` 全文搜索 `nanobot`**：**0 处匹配**。
- **`agent/prompts/charles_system_prompt.py` 全文搜索 `nanobot`**：**0 处匹配**。
- **`agent/context.py` L304-346 + L520-528 + L611-647 + L788-834 范围内搜索 `nanobot`**：**0 处匹配**。
- **`agent_config/system_prompt.yaml` + `agent_config/mcp_servers.yaml` 搜索 `nanobot`**：**0 处匹配**。

**注**：`agent/context.py` L275 存在 1 处 nanobot 注释（`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`），但该注释属于 `extra_sections` 参数（与 Rules 段相关，用于解释为何保留该废弃参数），**不属于 MCP 段条件注入范围**。该项已在 P5.1 第四节、P5.7 第四节、P5.15 第四节记录，本阶段不重复计入。

#### 4.3.2 实现逻辑残留（0 处）

经核查 MCP 段条件注入全部实现逻辑：

- **条件门控逻辑**：`_load_enhancements` 使用 YAML 配置文件读取 `enhancements.enabled` + `enhancements.mcp_section` 开关（对齐 Cline `disableMcpSettingsTools` 配置项语义），**不**使用 nanobot 风格的硬编码启用或环境变量控制。
- **段构建逻辑**：`_build_mcp_servers_section` 使用 `# MCP 服务器` 文本标题 + `## {name}` 子标题 + 工具列表（对齐 Cline 工具描述格式），**不**使用 nanobot 风格的 XML 标签或自定义分隔符。
- **段注入逻辑**：通过 `_build_enhancement_rules` 作为增强层 rule 追加到 `{{CHARLES_RULES}}`（对齐 Cline effectiveRules 模式），**不**使用 nanobot 风格的"独立段硬编码"或"extra_sections 字典"注入。
- **服务器列表获取**：通过 `MCPRegistry.list_servers()` 获取 enabled 服务器（对齐 Cline `registrations.filter((r) => r.disabled !== true)`），**不**使用 nanobot 风格的全量遍历 + 内部过滤。
- **enabled 过滤逻辑**：`list_servers()` 返回 `[c for c in self._configs.values() if c.enabled]`（registry.py L231），`MCPServerConfig.enabled` 默认 `True`（registry.py L58），与 Cline `registrations.filter((r) => r.disabled !== true)`（默认启用）语义等价，**不**使用 nanobot 风格的默认禁用逻辑。
- **空列表处理逻辑**：`_build_mcp_servers_section` 在 `registry.list_servers()` 返回空列表时返回 `""`（context.py L802-803），`_build_enhancement_rules` 因 `if body:` 跳过追加（L629），避免空段污染（对齐 Cline `loadConfiguredMcpTools` 在无 enabled 服务器时返回 `{tools: []}` 的空列表处理），**不**使用 nanobot 风格的"空段占位"或"默认提示文本"。
- **客户端实现**：`agent/mcp/client.py` 实现 JSON-RPC 2.0 + stdio/http 传输（对齐 Cline `client.ts`），**不**使用 nanobot 风格的 HTTP REST 调用。
- **名称转换**：`agent/mcp/name_transform.py` 实现 SHA1 截断算法（对齐 Cline `name-transform.ts`，Phase Q 报告 #Q9 确认"完全一致"），**不**使用 nanobot 风格的命名约定。

**结论**：MCP 段条件注入实现**无任何 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。Charles MCP 子系统（agent/mcp/ + agent/tools/mcp.py + context.py 增强层）已完全对齐 Cline 架构，无 nanobot 风格实现逻辑。

### 4.4 与 Phase 5.7 / Phase 5.15 对比

Phase 5.7 报告（CLINE_DIFF_V2/phase_5.7_mcp_overview_section.md）已确认 MCP 概览段无 nanobot 残留（0 处注释残留、0 处实现逻辑残留）。Phase 5.15 报告（CLINE_DIFF_V2/phase_5.15_enhancement_section.md）确认 Enhancement 段机制本身无 nanobot 残留（仅 `extra_sections` docstring 1 处注释残留，与 MCP 段条件注入无关）。**本阶段确认 MCP 段条件注入逻辑与 P5.7 / P5.15 结论一致，无新增 nanobot 残留**。MCP 子系统的对齐质量高于技能系统（Phase 4.20 发现 17 处实现逻辑残留）。

### 4.5 历史标签残留检查

针对 nanobot 风格的 XML 标签（如 `<mcp_servers>` / `<mcp_overview>` / `<mcp_conditional>`）进行残留检查：

| 位置 | 类型 | 性质 |
|------|------|------|
| `agent/context.py` L806 | 代码 | `# MCP 服务器` 文本标题（对齐 Cline 工具描述格式），非 XML 标签 |
| `agent/mcp/registry.py` L478 | 代码 | `# 可用 MCP 服务器` 文本标题，非 XML 标签 |
| `agent_config/mcp_servers.yaml` L1-37 | 注释 | `# MCP 服务器配置 — 对标 Cline mcpSettings.json` 等 YAML 注释，非 XML 标签 |
| 其他位置 | — | 无残留 |

`<mcp_servers>` / `<mcp_overview>` / `<mcp_conditional>` 等 nanobot 风格 XML 标签**不出现在任何活跃代码或 base prompt 模板中**。**结论**：MCP 段条件注入从未使用 nanobot 风格 XML 标签，无历史标签残留需清理。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.19.2 无 MCP 时行为**：表面行为对齐，无需修复。两者在无 MCP 服务器时都不向 system prompt 注入 MCP 内容。
- **nanobot 残留**：MCP 段条件注入无 nanobot 残留（0 处注释残留、0 处实现逻辑残留），无需修复。

### 5.2 优先级 P1（建议处理）

- **5.19.1 MCP 段条件注入存在性**：Charles MCP 段条件注入属"架构上必要的增强"（在单一 use_mcp_tool 架构下，LLM 必须通过 system prompt 才能知道 server/tool 列表），**不建议移除**。但建议在文档中明确标注"Charles 增强项，Cline 无此段条件注入逻辑（Cline 走工具加载门控路径）"，避免与 Cline 对齐时产生混淆。
- **懒连接策略副作用**：建议在 `SystemPromptBuilder.build()` 首次调用时（或 session 启动时）触发 `registry.list_all_tools()` 预加载工具 cache，使 MCP 概览段在首次构建时即能列出完整工具列表。当前实现因懒连接（Q12 增强）导致首次段内容不完整，LLM 可能因不知道工具名而无法调用。该建议与 Phase Q 报告差距 #Q16 的"短期建议"一致。

### 5.3 优先级 P2（文档修正）

- **计划文件 P5.19 描述更新**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2146-2160，将 Cline 实现描述更新为：
  - **不存在 MCP 段条件注入**：Cline 通过 `createMcpTools` 把每个 MCP 工具展开为独立 LLM function（在 tools 列表中暴露），不在 system prompt 中构建 MCP 概览段，因此不存在 MCP 段条件注入逻辑。Cline 的"条件门控"门控的是**工具加载**（`disableMcpSettingsTools` 控制 `loadConfiguredMcpTools` 是否调用），不是 system prompt 段注入。
  - 无 MCP 时行为：`disableMcpSettingsTools=true` 或 `mcpSettings` 文件不存在时，`loadConfiguredMcpTools` 返回空 tools 列表，LLM 看不到任何 MCP 工具 function。

  并将 Charles 实现描述更新为：
  - **存在 MCP 段条件注入（增强层）**：通过 `_build_mcp_servers_section` 构建，作为增强层 rule 追加到 `{{CHARLES_RULES}}` 末尾，受三层条件门控：①`enhancements.enabled=true`（总开关）+ ②`enhancements.mcp_section=true`（子开关）+ ③`registry.list_servers()` 返回非空。三层全满足时才注入。默认 `enhancements.enabled=false`，即默认不注入。
  - 无 MCP 时行为：三层条件任一不满足即不注入。默认场景下（`enhancements.enabled=false`）直接跳过整个增强层。

  并将计划表 5.19.1 的"已对齐"标注更新为"不对齐（架构路径不同）"，5.19.2 维持"表面对齐"（表面行为对齐但底层机制不同）。

- **与 Phase 5.7 / Phase 5.15 交叉引用**：建议在 P5.19 计划表中添加交叉引用，注明 MCP 段条件注入的差异已在 Phase 5.7（MCP 概览段存在性）和 Phase 5.15（Enhancement 段机制）中详细记录，避免重复对比。

### 5.4 不建议修复

- **5.19.1 条件门控对象差异**：Cline 与 Charles 走不同架构路径（工具加载门控 vs system prompt 段注入门控），不存在"对齐"概念。强行对齐会破坏 Charles 的单一 use_mcp_tool 架构（该架构在量化场景下节省 token，是合理增强）。建议保留现状。
- **三层门控粒度**：Charles 三层条件门控（总开关 + 子开关 + 服务器列表非空）比 Cline 单层门控（`disableMcpSettingsTools`）更细，但这是 Charles 增强层架构的合理设计（允许用户按需开启子段），不建议简化为单层门控。

---

## 六、验证方法

### 6.1 Cline 不存在 MCP 段条件注入验证

```powershell
# 验证 Cline system.ts 模板无 MCP 占位符
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Pattern "MCP|mcp"
# 预期: 0 处匹配（模板仅含 {{CLINE_RULES}} + {{CLINE_METADATA}} 两个占位符）

# 验证 Cline cline.ts buildClineSystemPrompt 无 MCP 段条件注入
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "MCP|mcp"
# 预期: 0 处匹配（仅替换 PLATFORM/CWD/DATE/IDE/RULES/METADATA 6 个占位符，isCline 门控 METADATA 不是 MCP）

# 验证 Cline runtime-builder.ts 走工具加载门控路径
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\runtime-builder.ts" -Pattern "loadConfiguredMcpTools|createMcpTools|disableMcpSettingsTools|hasMcpSettingsFile"
# 预期: L11（import createMcpTools）+ L13（import hasMcpSettingsFile）+ L186（loadConfiguredMcpTools 定义）+ L191（hasMcpSettingsFile 检查）+ L220（createMcpTools 调用）+ L293（disableMcpSettingsTools 配置项）+ L310（默认值）+ L453-456（条件加载）
```

### 6.2 Charles MCP 段条件注入三层门控验证

```powershell
# 验证 Charles _build_mcp_servers_section 第三层门控（服务器列表非空）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "if not servers" -Context 0,2
# 预期: L802-803（if not servers: return ""）

# 验证 Charles _build_enhancement_rules 第二层门控（mcp_section 子开关）+ body 非空检查
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "mcp_section|if body:" -Context 0,3
# 预期: L313（配置注释）+ L324（默认配置）+ L340（配置键）+ L627（子开关判断）+ L628（方法调用）+ L629（body 非空判断）+ L630（rule 追加）

# 验证 Charles _build_rules 第一层门控（enhancements.enabled 总开关）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "_enhancements.get|_build_enhancement_rules" -Context 0,2
# 预期: L521（总开关判断）+ L522（调用增强层）+ L611（方法定义）

# 验证 Charles 增强层配置默认关闭
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\system_prompt.yaml" -Pattern "enabled|mcp_section"
# 预期: L5（enabled: false）+ L9（mcp_section: true，但总开关 false 时强制关闭）
```

### 6.3 Charles MCP 段条件注入路径验证

```powershell
# 验证 Charles MCP 段在 _build_enhancement_rules 中的位置（位于 tools_section 之后）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "tools_section|mcp_section|always_skills|skills_summary|memory" -Context 0,2
# 预期: L622（tools_section 判断）→ L627（mcp_section 判断）→ L632（always_skills 判断）→ L638（skills_summary 判断）→ L644（memory 判断）

# 验证 Charles _build_rules 第 6 步调用增强层
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "_build_enhancement_rules"
# 预期: L522（_build_rules 中调用）+ L611（方法定义）
```

### 6.4 nanobot 残留验证

```powershell
# 在 MCP 段条件注入相关代码范围内搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" | Where-Object { $_.LineNumber -ge 304 -and $_.LineNumber -le 346 -or $_.LineNumber -ge 520 -and $_.LineNumber -le 528 -or $_.LineNumber -ge 611 -and $_.LineNumber -le 647 -or $_.LineNumber -ge 788 -and $_.LineNumber -le 834 }
# 预期: 0 处（L275 的 extra_sections 注释不在 MCP 段条件注入范围内）

# 在 agent/mcp/ 目录搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\*.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处

# 在 agent/tools/mcp.py 搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\mcp.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处

# 在 base prompt 模板中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处

# 在 MCP 配置文件中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\system_prompt.yaml" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\mcp_servers.yaml" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处
```

### 6.5 无 MCP 时行为验证

```powershell
# 验证 Charles _build_mcp_servers_section 在无服务器时返回空字符串（第三层门控）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "if not servers" -Context 0,2
# 预期: L802-803（if not servers: return ""）

# 验证 Charles _build_enhancement_rules 跳过空 body
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "if body:" -Context 0,3
# 预期: L624（tools_section）+ L629（mcp_section）+ L635（always_skills）+ L641（skills_summary）

# 验证 Charles mcp_servers.yaml 默认 servers 为空
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\mcp_servers.yaml" -Pattern "^servers:"
# 预期: L38（servers: []）

# 验证 Cline loadConfiguredMcpTools 在无配置文件时返回空 tools 列表
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\runtime-builder.ts" -Pattern "hasMcpSettingsFile|return \{ tools: \[\] \}"
# 预期: L191（hasMcpSettingsFile 检查）+ L192（return { tools: [] }）
```

### 6.6 Cline enabled 过滤验证

```powershell
# 验证 Cline loadConfiguredMcpTools 的 enabled 过滤（disabled !== true）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\runtime-builder.ts" -Pattern "disabled"
# 预期: L217（registrations.filter((r) => r.disabled !== true)）

# 验证 Charles list_servers 的 enabled 过滤
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\registry.py" -Pattern "if c.enabled|enabled: bool"
# 预期: L58（enabled: bool = True 默认值）+ L231（return [c for c in self._configs.values() if c.enabled]）
```

### 6.7 Phase 5.7 / Phase 5.15 交叉验证

```powershell
# 验证 Phase 5.7 报告已记录 MCP 概览段为"额外增强"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_5.7_mcp_overview_section.md" -Pattern "5.7.1|5.7.5|不对齐|表面对齐"
# 预期: 5.7.1（不对齐）+ 5.7.5（表面对齐）

# 验证 Phase 5.15 报告已记录 Enhancement 段机制
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_5.15_enhancement_section.md" -Pattern "5.15.1|5.15.2|Charles 额外|对齐"
# 预期: 5.15.1（Charles 额外）+ 5.15.2（对齐，默认关闭）
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.19.1 MCP 注入条件 | 有 MCP 时 / 有 MCP 时 / 已对齐 | **不对齐** | Cline 不存在 MCP 段条件注入逻辑（system.ts 无 MCP 占位符，cline.ts 无 MCP 段替换，`isCline` 门控的是 METADATA 不是 MCP）。Cline 的"条件门控"门控的是**工具加载**（`disableMcpSettingsTools` 控制 `loadConfiguredMcpTools` 是否调用），MCP 工具通过 `createMcpTools` 展开为 `AgentTool[]` 注入 tools 列表。Charles 存在三层条件门控的 MCP 段注入逻辑（`enhancements.enabled` + `enhancements.mcp_section` + `list_servers()` 非空），作为增强层 rule 追加到 `{{CHARLES_RULES}}`，默认关闭。计划表标注基于错误描述（误以为 Cline 有 MCP 段条件注入），实际不对齐 |
| 5.19.2 无 MCP 时行为 | 不注入 / 不注入 / 已对齐 | **表面对齐** | 两者在无 MCP 服务器时都不向 system prompt 注入 MCP 内容。Cline 是"段不存在所以不注入 + tools 列表为空"（`disableMcpSettingsTools=true` 或 `hasMcpSettingsFile=false` 或 `registrations` 全 disabled → `loadConfiguredMcpTools` 返回 `{tools: []}`）；Charles 是"段存在但三层条件未满足所以不注入"（`enhancements.enabled=false` 默认关闭，或 `list_servers()` 返回空 → `_build_mcp_servers_section` 返回 `""`）。表面行为对齐，底层机制不同 |

**计划表标注总结**：2 项中 1 项标注"已对齐"的项（5.19.1）实际不对齐（Cline 不存在 MCP 段条件注入逻辑，无从对齐），1 项标注"已对齐"的项（5.19.2）表面行为对齐但底层机制不同。计划表 P5.19 整体基于错误描述（误以为 Cline 有 MCP 段条件注入逻辑），未反映 Cline 走"工具加载门控"路径、Charles 走"system prompt 段条件注入"路径的事实，需更新。该差异已在 Phase 5.7 报告（CLINE_DIFF_V2/phase_5.7_mcp_overview_section.md）和 Phase 5.15 报告（CLINE_DIFF_V2/phase_5.15_enhancement_section.md）中详细记录，本阶段确认 P5.19 计划描述与 P5.7 / P5.15 结论不一致。
