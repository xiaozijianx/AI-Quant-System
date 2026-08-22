# Phase 5.7 MCP 服务器概览段对比

> 对比范围：Cline `runtime-builder.ts::loadConfiguredMcpTools` + `createMcpTools`（MCP 工具展开为独立 LLM function）+ `disableMcpSettingsTools` 配置开关 + `system.ts` / `cline.ts` base prompt 模板（无 MCP 占位符）与 Charles `SystemPromptBuilder._build_mcp_servers_section` + `_build_enhancement_rules` 增强层装配 + `mcp_section` 开关 + `MCPRegistry.build_servers_summary` 同步等价方法 + `mcp_servers.yaml` 配置的 MCP 概览段存在性、内容、格式、注入时机、无 MCP 时行为等 5 项逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（DEFAULT + YOLO 双模板，仅 `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 两个占位符，**无 MCP 占位符**）
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 仅替换 PLATFORM/CWD/DATE/IDE/RULES/METADATA，**无 MCP 段替换**）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L186-244（`loadConfiguredMcpTools` 调用 `createMcpTools` 展开为 `AgentTool[]`，注入到 `tools` 列表而非 system prompt）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L293 + L310 + L453-456（`disableMcpSettingsTools` 配置项控制是否加载 MCP 工具，**不**控制系统提示段）
> - `sdk/packages/core/src/extensions/mcp/tools.ts`（`createMcpTools` 把每个 MCP 工具描述符展开为独立 LLM function，description 由 `defaultMcpDescription(serverName, descriptor)` 生成）
>
> Charles 源码：
> - `agent/context.py` L788-834（`SystemPromptBuilder._build_mcp_servers_section` 方法，构建 `# MCP 服务器` 段文本）
> - `agent/context.py` L611-647（`_build_enhancement_rules` 方法，按 `mcp_section` 开关把段文本作为 rule 追加，标题 `charles-mcp-overview`）
> - `agent/context.py` L304-346（`_load_enhancements` 读取 `agent_config/system_prompt.yaml` 的 `enhancements.mcp_section` 开关，默认 false）
> - `agent/context.py` L454-539（`_build_rules` 在第 6 步调用 `_build_enhancement_rules`，把增强层 rule 追加到 `{{CHARLES_RULES}}`）
> - `agent/mcp/registry.py` L458-501（`MCPRegistry.build_servers_summary` 同步等价方法，输出 `# 可用 MCP 服务器`）
> - `agent/mcp/registry.py` L227-231（`list_servers` 仅返回 enabled 的服务器）
> - `agent_config/system_prompt.yaml` L4-10（`enhancements.enabled=false` 总开关默认关闭，`mcp_section: true` 子开关）
> - `agent_config/mcp_servers.yaml` L38（`servers: []` 默认空列表）
> - `agent/prompts/charles_system_prompt.py` L1-94（base prompt 模板，**无 `{{CHARLES_MCP}}` 占位符**，MCP 段通过 Rules 增强层注入）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 MCP 服务器概览段实现。**核心结论：Cline 完全不存在 MCP 服务器概览段（system prompt 中无任何 MCP 占位符、无任何 MCP 段构建逻辑），Charles 通过增强层实现了 MCP 概览段（默认关闭，需显式开启）**；计划文件 P5.7 描述与实际代码严重不符，所列 5 项"已对齐"均不成立——Cline 模式下 MCP 工具通过 `createMcpTools` 展开为独立 LLM function（在工具列表中暴露），Charles 模式下 MCP 工具通过单一 `use_mcp_tool` 调用（在 Rules 增强层中暴露服务器列表），两者是**架构路径不同**而非"段对齐"。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.7（L1914-1933）将 Cline 实现描述为"列出已连接的 MCP 服务器，服务器名 + 工具数"，将 Charles 实现描述为相同内容。**此描述存在严重事实错误**：

1. **Cline 不存在 MCP 概览段**：经核查 Cline `system.ts`（base prompt 模板）仅含 `{{CLINE_RULES}}` + `{{CLINE_METADATA}}` 两个占位符，**无 `{{CLINE_MCP}}` 或任何 MCP 相关占位符**；`cline.ts::buildClineSystemPrompt` 仅替换 PLATFORM/CWD/DATE/IDE/RULES/METADATA 6 个占位符，**无 MCP 段替换逻辑**。MCP 工具通过 `runtime-builder.ts::loadConfiguredMcpTools` 调用 `createMcpTools` 展开为 `AgentTool[]` 注入到 `tools` 列表（运行时工具清单），而非 system prompt 文本段。

2. **Charles MCP 概览段属"增强层"非"基础段"**：Charles 通过 `_build_mcp_servers_section`（context.py L788-834）构建 MCP 概览文本，但该方法**仅当 `enhancements.enabled=true` 且 `enhancements.mcp_section=true` 时才注入**（默认全部关闭，参见 `system_prompt.yaml` L5）。注入位置是 `{{CHARLES_RULES}}` 末尾作为增强层 rule，**不是** base prompt 的独立占位符段。

3. **计划表 5.7.1-5.7.5 全部失效**：5 项对比项均标注"已对齐"，但实际只有 5.7.5（无 MCP 时不注入）的表面行为对齐，其余 4 项均不成立（Cline 不存在该段，无从对齐）。

### 核心结论

1. **MCP 概览段存在性**（5.7.1）：**严重不对齐**。Cline 不存在 MCP 概览段；Charles 存在但默认关闭。计划表标注"已对齐"失效。
2. **服务器名 / 工具数**（5.7.2 / 5.7.3）：**架构路径不同**。Cline 通过 LLM function 列表暴露每个 MCP 工具的 name + description + inputSchema；Charles 通过 system prompt 文本段列出 server_name + 工具列表（含工具描述首行 80 字符）。两者信息密度不同，不存在"对齐"概念。
3. **段落位置**（5.7.4）：**不对齐**。Cline 无段；Charles 位于 `{{CHARLES_RULES}}` 末尾（增强层 rule）。
4. **无 MCP 时行为**（5.7.5）：**表面对齐**。Cline 不注入（段不存在）；Charles 不注入（`list_servers()` 返回空时 `_build_mcp_servers_section` 返回空字符串，`_build_enhancement_rules` 跳过追加）。
5. **注入时机**：**架构路径不同**。Cline 在 session 启动时由 `loadConfiguredMcpTools` 一次性加载（eager）；Charles 在每次 `SystemPromptBuilder.build()` 调用时构建（per-turn，但受增强层开关控制）。
6. **nanobot 残留**：MCP 概览段实现**无 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。`agent/context.py` L275 的 nanobot 注释属于 `extra_sections` 参数（与 MCP 段无关），`agent/mcp/` 目录与 `agent/tools/mcp.py` 均无 nanobot 残留。

### 一致性总体评估

- **段存在性**：**不对齐**（Cline 无段，Charles 有段作为增强层）。
- **架构路径**：**根本不同**（Cline 工具展开 vs Charles 单一 use_mcp_tool + system prompt 概览）。
- **信息暴露**：**等价目标不同路径**（Cline 通过 function schema 暴露；Charles通过文本段暴露）。
- **配置开关**：**等价**（Cline `disableMcpSettingsTools` 控制工具加载；Charles `mcp_section` 控制段注入 + `mcp_servers.yaml::enabled` 控制工具加载）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.7.1 | MCP 概览段存在性 | **不存在**（system.ts 模板无 MCP 占位符；cline.ts 无 MCP 段替换；MCP 工具通过 `createMcpTools` 展开为 AgentTool 注入 tools 列表） | **存在**（context.py L788-834 `_build_mcp_servers_section` 构建文本段；通过 `_build_enhancement_rules` 作为增强层 rule 追加到 `{{CHARLES_RULES}}`） | 不对齐 | 计划表标注"已对齐"失效。Cline 走"工具列表"路径，Charles 走"system prompt 段"路径，架构根本不同。Charles 段默认关闭（`enhancements.enabled=false`） |
| 5.7.2 | 服务器名 | **不适用**（Cline 不在 system prompt 中列服务器名；每个 MCP 工具的 description 由 `defaultMcpDescription(serverName, descriptor)` 生成，serverName 嵌入工具描述） | **存在**（context.py L816 `## {srv.name}{(transport)}`，每个服务器一个 `##` 子段） | 不对齐 | 计划表标注"已对齐"失效。Cline 把服务器名编码进每个工具的 description；Charles 用 `##` 标题显式列出 |
| 5.7.3 | 工具数 / 工具列表 | **不适用**（Cline 不在 system prompt 中列工具；工具数等于 `tools.length`，每个工具作为独立 function 暴露 name + description + inputSchema） | **存在**（context.py L820-829 从 `registry._tools_cache` 读取工具列表，列出 `tool.name: description首行80字符`；cache 未命中时输出"(工具列表未加载，调用 use_mcp_tool 时会自动连接并加载)"） | 不对齐 | 计划表标注"已对齐"失效。Cline 通过 function schema 暴露精确工具签名；Charles 通过文本概览暴露工具名+简短描述（首行 80 字符），不暴露完整 schema |
| 5.7.4 | 段落位置 | **不适用**（Cline 无段） | **位于 `{{CHARLES_RULES}}` 末尾**（context.py L627-630 通过 `_build_enhancement_rules` 把 `charles-mcp-overview` 作为 rule 追加；最终由 `format_rules_content` 添加 `##` 标题） | 不对齐 | 计划表标注"第 5 段 vs 第 5 段 已对齐"失效。Charles 的 MCP 段不是 base prompt 的独立段，而是 Rules 增强层的最后一个 rule（在 tools-overview / always-skills / skills-summary 之后） |
| 5.7.5 | 无 MCP 时行为 | **不注入**（段不存在；`disableMcpSettingsTools=true` 时也不加载工具；`mcpSettings` 文件不存在时 `loadConfiguredMcpTools` 返回 `{tools: []}`） | **不注入**（context.py L802-803 `if not servers: return ""`；`_build_enhancement_rules` 跳过空 body 的 rule） | 表面对齐 | 表面行为对齐：两者在无 MCP 服务器时都不向 system prompt 注入 MCP 相关内容。但 Cline 是"段不存在所以不注入"，Charles 是"段存在但内容为空所以不注入" |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.7 描述与实际代码严重不符（5.7.1 + 5.7.2 + 5.7.3 + 5.7.4）

AGENT_COMPARISON_PLAN_V2.md L1916-1930 将 Cline 与 Charles 实现描述为：

```
**Cline 实现**：
- 列出已连接的 MCP 服务器
- 服务器名 + 工具数

**Charles 实现**：
- 列出已连接的 MCP 服务器
- 服务器名 + 工具数

| 5.7.1 | MCP 概览段 | 是 | 是 | 已对齐 |
| 5.7.2 | 服务器名 | 是 | 是 | 已对齐 |
| 5.7.3 | 工具数 | 是 | 是 | 已对齐 |
| 5.7.4 | 段落位置 | 第 5 段 | 第 5 段 | 已对齐 |
| 5.7.5 | 无 MCP 时行为 | 不注入 | 不注入 | 已对齐 |
```

经核查 Cline 实际代码：

**证据 1 — system.ts 模板无 MCP 占位符**（sdk/packages/shared/src/prompt/system.ts L1-68）：

DEFAULT_CLINE_SYSTEM_PROMPT 与 YOLO_CLINE_SYSTEM_PROMPT 模板仅含以下占位符：
- `{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}`（env 段）
- `{{CLINE_RULES}}`（rules 段）
- `{{CLINE_METADATA}}`（workspace metadata 段）

**无 `{{CLINE_MCP}}` 或任何 MCP 相关占位符**。

**证据 2 — cline.ts 无 MCP 段替换**（sdk/packages/shared/src/prompt/cline.ts L153-165）：

```typescript
return basePrompt
    .replace("{{PLATFORM_NAME}}", platform)
    .replace("{{CWD}}", workspaceRoot)
    .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
    .replace("{{IDE_NAME}}", ide)
    .replace(
        "{{CLINE_METADATA}}",
        isCline ? buildWorkspaceMetadata(...) : "",
    )
    .replace("{{CLINE_RULES}}", effectiveRules)
    .trim();
```

6 个 `replace` 调用，**无 MCP 段替换**。

**证据 3 — runtime-builder.ts 走工具展开路径**（sdk/packages/core/src/runtime/orchestration/runtime-builder.ts L186-244 + L453-456）：

```typescript
async function loadConfiguredMcpTools(logger?: BasicLogger): Promise<{
    tools: AgentTool[];   // ← 工具列表，不是 system prompt 段
    shutdown?: () => Promise<void>;
}> {
    // ...
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

MCP 工具通过 `createMcpTools` 展开为 `AgentTool[]`，注入到 runtime 的 `tools` 列表（即 LLM function 列表），**不注入 system prompt 文本**。

**结论**：计划表 5.7.1 / 5.7.2 / 5.7.3 / 5.7.4 标注的"已对齐"全部失效。Cline 走"工具展开为独立 LLM function"路径，Charles 走"单一 use_mcp_tool + system prompt 概览段"路径，两者是**架构路径根本不同**，不存在"段对齐"概念。该差异已在 Phase Q 报告（CLINE_DIFF/phase_Q_mcp.md）差距 #Q11（工具注册架构）与 #Q16（MCP 概览注入）中详细记录，本阶段确认 P5.7 计划描述与 Q11/Q16 结论不一致。

### 3.2 Charles MCP 概览段的注入路径与默认行为（5.7.1 + 5.7.4）

Charles MCP 概览段的注入链路：

```
SystemPromptBuilder.build()
  → _build_rules(task_type)                         # context.py L454-539
      → step 6: if self._enhancements.get("enabled"):
            _build_enhancement_rules()              # context.py L611-647
              → if self._enhancements.get("mcp_section"):
                    body = self._build_mcp_servers_section()    # context.py L788-834
                    if body:
                        rules.append(("charles-mcp-overview", body))
  → format_rules_content(results)                   # 把所有 rule 拼接，加 ## 标题
  → build_charles_system_prompt(rules_text=...)      # 替换 {{CHARLES_RULES}}
```

**关键事实**：

1. **默认关闭**：`agent_config/system_prompt.yaml` L5 `enhancements.enabled: false`，总开关关闭时所有子开关（含 `mcp_section`）强制 false（context.py L342 `result[key] = enabled and bool(cfg.get(key, True))`）。即**默认场景下 Charles 也不注入 MCP 概览段**。

2. **不是 base prompt 独立段**：MCP 概览段不是 base prompt 模板的独立占位符段（如 `{{CHARLES_MCP}}`），而是作为增强层 rule 追加到 `{{CHARLES_RULES}}` 末尾。最终在 `format_rules_content` 中被 `##` 标题包裹，与用户规则、MODE_TAG、PLAN_MODE、tools-overview、always-skills、skills-summary、memory 等 rule 共同构成 Rules 段。

3. **段落顺序**：在 `_build_enhancement_rules` 中（context.py L620-647），MCP 段位于第 2 位（tools_section → mcp_section → always_skills → skills_summary → memory），即 Rules 末尾的"工具概览"之后、"技能"之前。

4. **无 MCP 时返回空字符串**：`_build_mcp_servers_section` 在 `registry.list_servers()` 返回空列表时（context.py L802-803）返回 `""`，`_build_enhancement_rules` 因 `if body:` 跳过追加（L629）。最终 Rules 段不含 MCP 标题，避免空段污染。

**评估**：Charles 的 MCP 概览段实现是**合理增强**（在 Q11 单一 use_mcp_tool 架构下，LLM 必须通过 system prompt 才能知道有哪些 server/tool 可用，否则无法调用）。该增强已在 Phase Q 报告差距 #Q16 中标记为"额外增强（架构上必要）"，本阶段确认该结论。

### 3.3 Charles `_build_mcp_servers_section` 与 `MCPRegistry.build_servers_summary` 的重复（架构观察）

Charles 存在两个等价的 MCP 概览构建方法：

| 方法 | 位置 | 输出格式 | 调用方 |
|------|------|---------|--------|
| `SystemPromptBuilder._build_mcp_servers_section` | context.py L788-834 | `# MCP 服务器` + `## {name}` + 工具列表 | `SystemPromptBuilder._build_enhancement_rules`（system prompt 注入） |
| `MCPRegistry.build_servers_summary` | registry.py L458-501 | `# 可用 MCP 服务器` + `## {name}` + 工具列表 | 外部调用（如 API 端点 `GET /mcp/servers`） |

两者逻辑几乎相同（遍历 `list_servers()` + 读 `_tools_cache` + 拼接文本），但标题不同（`# MCP 服务器` vs `# 可用 MCP 服务器`），引导语略有差异。`_build_mcp_servers_section` 直接访问 `registry._tools_cache`（私有属性），`build_servers_summary` 通过 `self._tools_cache` 访问（同类内访问）。

**评估**：非对齐缺口，属代码重复（DRY 违规）。建议 `_build_mcp_servers_section` 委托 `registry.build_servers_summary()` 实现以避免重复，但不在本阶段修复范围内（本阶段仅对比，不修改源码）。

### 3.4 Cline `disableMcpSettingsTools` vs Charles `mcp_section` 开关语义差异（5.7.5 补充）

| 维度 | Cline | Charles |
|------|-------|---------|
| 配置项 | `disableMcpSettingsTools`（runtime-builder.ts L293, L310） | `enhancements.mcp_section`（system_prompt.yaml L9）+ `mcp_servers.yaml::servers[].enabled` |
| 控制对象 | 控制**工具加载**（`loadConfiguredMcpTools` 是否调用） | 控制**system prompt 段注入**（`_build_mcp_servers_section` 是否调用） |
| 默认值 | `false`（即默认加载 MCP 工具） | `enhancements.enabled=false`（即默认不注入 MCP 段） |
| 影响范围 | 工具不加载 → LLM 看不到任何 MCP 工具 function | 段不注入 → LLM 看不到 MCP 服务器列表（但 `use_mcp_tool` 工具本身仍存在） |
| 单服务器粒度 | 无（只能全开/全关） | `mcp_servers.yaml::servers[].enabled` 支持单服务器启停 |

**关键差异**：

- Cline 的 `disableMcpSettingsTools=true` 时，MCP 工具完全不加载，LLM 无法调用任何 MCP 工具。
- Charles 的 `mcp_section=false` 时，仅 system prompt 不列服务器概览，但 `use_mcp_tool` 工具本身仍注册（LLM 仍可调用，但因不知道 server_name/tool_name 而实际无法使用）。
- Charles 的 `mcp_servers.yaml::servers[].enabled=false` 时，该服务器不进入 `list_servers()`，`_build_mcp_servers_section` 不列该服务器，`call_tool` 也会因配置不存在而报错。

**评估**：开关语义不同，但 net 效果在"无 MCP 时"对齐（两者都不向 LLM 暴露 MCP 信息）。非对齐缺口，属架构路径差异。

### 3.5 Charles 工具列表 cache 命中率影响 MCP 段质量（5.7.3 补充）

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

- **首次构建 system prompt 时**，MCP 段会输出"(工具列表未加载，调用 use_mcp_tool 时会自动连接并加载)"，LLM 只知道服务器名不知道具体工具。
- **后续构建**（若已有 MCP 工具调用过）才会列出工具名 + 描述首行 80 字符。

Cline 模式下（eager connect for tool discovery），session 启动时 `loadConfiguredMcpTools` 主动调用 `createMcpTools` → `provider.listTools(serverName)` → `manager.listTools` → `refreshTools` → `ensureConnectedClient`，即**启动时连接所有 enabled 服务器并枚举工具**，LLM 立即看到完整工具列表。

**影响**：Charles 的懒连接策略导致 MCP 概览段在首次构建时信息不完整，LLM 可能因不知道具体工具名而无法调用。Phase Q 报告差距 #Q16 已记录此问题，建议"在 `GET /mcp/servers` 调用时主动预加载工具 cache"或"首次构建 system prompt 时触发 `list_all_tools()` 预加载"。

**评估**：非对齐缺口（Cline 无此问题因走工具展开路径），属 Charles 架构选择（懒连接）的副作用。已在 Phase Q 记录，本阶段不重复修复建议。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 MCP 概览段相关文件检查 nanobot 风格残留：
- `agent/context.py` L611-647（`_build_enhancement_rules` 增强层装配）
- `agent/context.py` L788-834（`_build_mcp_servers_section` 方法）
- `agent/context.py` L304-346（`_load_enhancements` 配置读取）
- `agent/mcp/registry.py` L458-501（`build_servers_summary` 同步等价方法）
- `agent/mcp/registry.py` L227-231（`list_servers` 方法）
- `agent/mcp/client.py`（MCP 客户端实现）
- `agent/mcp/name_transform.py`（名称转换）
- `agent/tools/mcp.py`（use_mcp_tool 工具实现）
- `agent/prompts/charles_system_prompt.py`（base prompt 模板）
- `agent_config/system_prompt.yaml`（增强层配置）
- `agent_config/mcp_servers.yaml`（MCP 服务器配置）

### 4.2 检查结果

| 文件 / 范围 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` L611-647（`_build_enhancement_rules`） | 0 | 0 | 无残留 |
| `agent/context.py` L788-834（`_build_mcp_servers_section`） | 0 | 0 | 无残留 |
| `agent/context.py` L304-346（`_load_enhancements`） | 0 | 0 | 无残留 |
| `agent/mcp/registry.py` L458-501（`build_servers_summary`） | 0 | 0 | 无残留 |
| `agent/mcp/registry.py` L227-231（`list_servers`） | 0 | 0 | 无残留 |
| `agent/mcp/client.py`（全文） | 0 | 0 | 无残留 |
| `agent/mcp/name_transform.py`（全文） | 0 | 0 | 无残留 |
| `agent/tools/mcp.py`（全文） | 0 | 0 | 无残留 |
| `agent/prompts/charles_system_prompt.py`（全文 94 行） | 0 | 0 | 无残留 |
| `agent_config/system_prompt.yaml`（全文 10 行） | 0 | 0 | 无残留 |
| `agent_config/mcp_servers.yaml`（全文 86 行） | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（0 处，MCP 概览段范围内）

经核查 MCP 概览段相关代码：

- **`agent/mcp/` 目录全文搜索 `nanobot`**（大小写不敏感）：**0 处匹配**。`agent/mcp/__init__.py`、`agent/mcp/client.py`、`agent/mcp/registry.py`、`agent/mcp/name_transform.py` 均无 nanobot 注释。
- **`agent/tools/mcp.py` 全文搜索 `nanobot`**：**0 处匹配**。
- **`agent/prompts/charles_system_prompt.py` 全文搜索 `nanobot`**：**0 处匹配**。
- **`agent/context.py` L611-647 + L788-834 + L304-346 范围内搜索 `nanobot`**：**0 处匹配**。
- **`agent_config/system_prompt.yaml` + `agent_config/mcp_servers.yaml` 搜索 `nanobot`**：**0 处匹配**。

**注**：`agent/context.py` L275 存在 1 处 nanobot 注释（`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`），但该注释属于 `extra_sections` 参数（与 Rules 段相关，用于解释为何保留该废弃参数），**不属于 MCP 概览段范围**。该项已在 P5.1 第四节记录，本阶段不重复计入。

#### 4.3.2 实现逻辑残留（0 处）

经核查 MCP 概览段全部实现逻辑：

- **段构建逻辑**：`_build_mcp_servers_section` 使用 `# MCP 服务器` 文本标题 + `## {name}` 子标题 + 工具列表（对齐 Cline 工具描述格式），**不**使用 nanobot 风格的 XML 标签或自定义分隔符。
- **段注入逻辑**：通过 `_build_enhancement_rules` 作为增强层 rule 追加到 `{{CHARLES_RULES}}`（对齐 Cline effectiveRules 模式），**不**使用 nanobot 风格的"独立段硬编码"或"extra_sections 字典"注入。
- **配置开关逻辑**：通过 `agent_config/system_prompt.yaml` 的 `enhancements.mcp_section` 开关控制（对齐 Cline `disableMcpSettingsTools` 配置项语义），**不**使用 nanobot 风格的硬编码启用。
- **服务器列表获取**：通过 `MCPRegistry.list_servers()` 获取 enabled 服务器（对齐 Cline `registrations.filter((r) => r.disabled !== true)`），**不**使用 nanobot 风格的全量遍历 + 内部过滤。
- **工具列表获取**：从 `registry._tools_cache` 读取缓存（对齐 Cline `toolCache` + `toolCacheUpdatedAt` 模式，但无 TTL），**不**使用 nanobot 风格的同步阻塞查询。
- **客户端实现**：`agent/mcp/client.py` 实现 JSON-RPC 2.0 + stdio/http 传输（对齐 Cline `client.ts`），**不**使用 nanobot 风格的 HTTP REST 调用。
- **名称转换**：`agent/mcp/name_transform.py` 实现 SHA1 截断算法（对齐 Cline `name-transform.ts`，Phase Q 报告 #Q9 确认"完全一致"），**不**使用 nanobot 风格的命名约定。

**结论**：MCP 概览段实现**无任何 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。Charles MCP 子系统（agent/mcp/ + agent/tools/mcp.py + context.py 增强层）已完全对齐 Cline 架构，无 nanobot 风格实现逻辑。

### 4.4 与 Phase Q 对比

Phase Q 报告（CLINE_DIFF/phase_Q_mcp.md）已确认 MCP 子系统对齐度约 65%（16 项中 1 项完全一致 + 4 项额外增强 + 2 项合理特化缺失 + 8 项弱对齐 + 1 项真缺口）。**MCP 概览段（Q16）作为"额外增强"已记录**，本阶段确认 Q16 结论与 P5.7 计划描述不符。MCP 概览段本身无 nanobot 残留，与 Phase 4.20（技能系统 nanobot 残留审计发现 17 处实现逻辑残留）形成对比，说明 MCP 子系统的对齐质量高于技能系统。

### 4.5 历史标签残留检查

针对 nanobot 风格的 XML 标签（如 `<mcp_servers>` / `<mcp_overview>`）进行残留检查：

| 位置 | 类型 | 性质 |
|------|------|------|
| `agent/context.py` L806 | 代码 | `# MCP 服务器` 文本标题（对齐 Cline 工具描述格式），非 XML 标签 |
| `agent/mcp/registry.py` L478 | 代码 | `# 可用 MCP 服务器` 文本标题，非 XML 标签 |
| 其他位置 | — | 无残留 |

`<mcp_servers>` / `<mcp_overview>` 等 nanobot 风格 XML 标签**不出现在任何活跃代码或 base prompt 模板中**。**结论**：MCP 概览段从未使用 nanobot 风格 XML 标签，无历史标签残留需清理。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.7.5 无 MCP 时行为**：表面行为对齐，无需修复。两者在无 MCP 服务器时都不向 system prompt 注入 MCP 内容。
- **nanobot 残留**：MCP 概览段无 nanobot 残留（0 处注释残留、0 处实现逻辑残留），无需修复。

### 5.2 优先级 P1（建议处理）

- **5.7.1 MCP 概览段存在性**：Charles MCP 概览段属"架构上必要的增强"（在单一 use_mcp_tool 架构下，LLM 必须通过 system prompt 才能知道 server/tool 列表），**不建议移除**。但建议在文档中明确标注"Charles 增强项，Cline 无此段"，避免与 Cline 对齐时产生混淆。
- **5.7.3 工具列表 cache 命中率**：建议在 `SystemPromptBuilder.build()` 首次调用时（或 session 启动时）触发 `registry.list_all_tools()` 预加载工具 cache，使 MCP 概览段在首次构建时即能列出完整工具列表。当前实现因懒连接（Q12 增强）导致首次段内容不完整，LLM 可能因不知道工具名而无法调用。该建议与 Phase Q 报告差距 #Q16 的"短期建议"一致。

### 5.3 优先级 P2（文档修正）

- **计划文件 P5.7 描述更新**：建议修正 AGENT_COMPARISON_PLAN_V2.md L1914-1933，将 Cline 实现描述更新为：
  - **不存在 MCP 概览段**：Cline 通过 `createMcpTools` 把每个 MCP 工具展开为独立 LLM function（在 tools 列表中暴露），不在 system prompt 中构建 MCP 概览段。
  - 段落位置：不适用（Cline 无段）。
  - 无 MCP 时行为：`disableMcpSettingsTools=true` 或 `mcpSettings` 文件不存在时，`loadConfiguredMcpTools` 返回空 tools 列表，LLM 看不到任何 MCP 工具。

  并将 Charles 实现描述更新为：
  - **存在 MCP 概览段（增强层）**：通过 `_build_mcp_servers_section` 构建，作为增强层 rule 追加到 `{{CHARLES_RULES}}` 末尾，受 `enhancements.mcp_section` 开关控制（默认关闭）。
  - 段落位置：Rules 末尾（增强层 rule，非 base prompt 独立段）。
  - 无 MCP 时行为：`list_servers()` 返回空时返回空字符串，`_build_enhancement_rules` 跳过追加。

  并将计划表 5.7.1 / 5.7.2 / 5.7.3 / 5.7.4 的"已对齐"标注更新为"不对齐（架构路径不同）"，5.7.5 维持"表面对齐"。

- **代码重复修正（可选）**：建议 `_build_mcp_servers_section` 委托 `registry.build_servers_summary()` 实现以避免重复，但需统一两者输出格式（`# MCP 服务器` vs `# 可用 MCP 服务器`）。非对齐缺口，属代码质量改进。

### 5.4 不建议修复

- **5.7.2 服务器名 / 5.7.3 工具数**：Cline 与 Charles 走不同架构路径（工具展开 vs 单一 use_mcp_tool），不存在"对齐"概念。强行对齐会破坏 Charles 的单一 use_mcp_tool 架构（该架构在量化场景下节省 token，是合理增强）。建议保留现状。
- **5.7.4 段落位置**：Charles MCP 段位于 Rules 增强层末尾是合理的（与 tools-overview / skills-summary 等增强层 rule 同级），不建议改为 base prompt 独立段（会破坏 base prompt 模板简洁性）。

---

## 六、验证方法

### 6.1 Cline 不存在 MCP 概览段验证

```powershell
# 验证 Cline system.ts 模板无 MCP 占位符
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Pattern "MCP|mcp"
# 预期: 0 处匹配（模板仅含 {{CLINE_RULES}} + {{CLINE_METADATA}} 两个占位符）

# 验证 Cline cline.ts buildClineSystemPrompt 无 MCP 段替换
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "MCP|mcp"
# 预期: 0 处匹配（仅替换 PLATFORM/CWD/DATE/IDE/RULES/METADATA 6 个占位符）

# 验证 Cline runtime-builder.ts 走工具展开路径
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\runtime-builder.ts" -Pattern "loadConfiguredMcpTools|createMcpTools|disableMcpSettingsTools"
# 预期: L11（import createMcpTools）+ L186（loadConfiguredMcpTools 定义）+ L220（createMcpTools 调用）+ L293（disableMcpSettingsTools 配置项）+ L310（默认值）+ L453-456（条件加载）
```

### 6.2 Charles MCP 概览段实现验证

```powershell
# 验证 Charles _build_mcp_servers_section 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "_build_mcp_servers_section|mcp_section|charles-mcp-overview"
# 预期: L17/L235（docstring 提及）+ L245（docstring 提及）+ L313（配置注释）+ L324（默认配置）+ L340（配置键）+ L627（开关判断）+ L628（方法调用）+ L630（rule 追加）+ L788（方法定义）+ L789（docstring）+ L792（返回值注释）

# 验证 Charles MCP 段作为增强层 rule 注入
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "charles-mcp-overview"
# 预期: L17/L235（docstring 提及）+ L630（rule 标题）

# 验证 Charles 增强层配置默认关闭
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\system_prompt.yaml" -Pattern "enabled|mcp_section"
# 预期: L5（enabled: false）+ L9（mcp_section: true，但总开关 false 时强制关闭）

# 验证 Charles MCP 段输出格式
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "# MCP 服务器|use_mcp_tool|access_mcp_resource"
# 预期: L806（# MCP 服务器 标题）+ L809（use_mcp_tool 引导）+ L810（access_mcp_resource 引导）
```

### 6.3 Charles MCP 段注入路径验证

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
# 在 MCP 概览段相关代码范围内搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" | Where-Object { $_.LineNumber -ge 304 -and $_.LineNumber -le 346 -or $_.LineNumber -ge 611 -and $_.LineNumber -le 647 -or $_.LineNumber -ge 788 -and $_.LineNumber -le 834 }
# 预期: 0 处（L275 的 extra_sections 注释不在 MCP 段范围内）

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
# 验证 Charles _build_mcp_servers_section 在无服务器时返回空字符串
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "if not servers" -Context 0,2
# 预期: L802-803（if not servers: return ""）

# 验证 Charles _build_enhancement_rules 跳过空 body
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "if body:" -Context 0,3
# 预期: L624（tools_section）+ L629（mcp_section）+ L635（always_skills）+ L641（skills_summary）

# 验证 Cline loadConfiguredMcpTools 在无配置文件时返回空 tools 列表
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\runtime-builder.ts" -Pattern "hasMcpSettingsFile|return \{ tools: \[\] \}"
# 预期: L191（hasMcpSettingsFile 检查）+ L192（return { tools: [] }）
```

### 6.6 Phase Q 报告交叉验证

```powershell
# 验证 Phase Q 报告已记录 MCP 概览段为"额外增强"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF\phase_Q_mcp.md" -Pattern "Q16|MCP 服务器概览|_build_mcp_servers_section"
# 预期: L46（Q16 表项）+ L527（差距 #Q16 标题）+ L538（context.py L207-211 引用）+ L539（_build_mcp_servers_section 引用）
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.7.1 MCP 概览段 | 是 / 是 / 已对齐 | **不对齐** | Cline 不存在 MCP 概览段（system.ts 无 MCP 占位符，cline.ts 无 MCP 段替换，MCP 工具通过 createMcpTools 展开为 AgentTool 注入 tools 列表）。Charles 存在但作为增强层 rule 默认关闭。计划表标注基于错误描述，实际不对齐 |
| 5.7.2 服务器名 | 是 / 是 / 已对齐 | **不对齐** | Cline 不在 system prompt 中列服务器名（服务器名嵌入每个工具的 description）。Charles 通过 `## {name}` 标题显式列出。计划表标注失效 |
| 5.7.3 工具数 | 是 / 是 / 已对齐 | **不对齐** | Cline 不在 system prompt 中列工具数（工具作为独立 LLM function 暴露，工具数等于 tools.length）。Charles 通过文本段列出工具名 + 描述首行 80 字符。计划表标注失效 |
| 5.7.4 段落位置 | 第 5 段 / 第 5 段 / 已对齐 | **不对齐** | Cline 无段（不适用）。Charles 位于 Rules 末尾（增强层 rule，非 base prompt 独立段）。计划表标注"第 5 段"对 Cline 不成立 |
| 5.7.5 无 MCP 时行为 | 不注入 / 不注入 / 已对齐 | **表面对齐** | 两者在无 MCP 服务器时都不向 system prompt 注入 MCP 内容。Cline 是"段不存在所以不注入"，Charles 是"段存在但内容为空所以不注入"。表面行为对齐，底层机制不同 |

**计划表标注总结**：5 项中 4 项标注"已对齐"的项（5.7.1 / 5.7.2 / 5.7.3 / 5.7.4）实际不对齐（Cline 不存在该段，无从对齐），1 项标注"已对齐"的项（5.7.5）表面行为对齐但底层机制不同。计划表 P5.7 整体基于错误描述（误以为 Cline 有 MCP 概览段），未反映 Cline 走"工具展开为独立 LLM function"路径的事实，需更新。该差异已在 Phase Q 报告（CLINE_DIFF/phase_Q_mcp.md）差距 #Q11 + #Q16 中详细记录，本阶段确认 P5.7 计划描述与 Q11/Q16 结论不一致。
