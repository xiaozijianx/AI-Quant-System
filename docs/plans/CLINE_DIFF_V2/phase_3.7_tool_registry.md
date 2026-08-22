# Phase 3.7 ToolRegistry 对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在工具注册表机制上的差异，覆盖 Registry 数据结构、工具注册时机、别名支持、动态注册、工具启用/禁用、`get_definitions` 过滤、工具覆盖、MCP 工具注入、工具预设（presets）、模型工具路由（model-tool-routing）、工具排序十一个维度。

总体结论：Charles 在工具注册表核心机制上已与 Cline **基本对齐**，但存在四处需要澄清的差异：

1. **计划 P3.7 描述与实际代码不符**：计划声称"Charles 有 `ToolRegistry` 类管理工具注册"，实际 Charles **没有独立的 `ToolRegistry` 类**。Charles `AgentRuntime._tools: dict[str, AgentTool]`（`runtime.py` L253）直接承担注册表角色，工具注册通过 `runtime.register_tool(tool)`（`runtime.py` L364-366）方法完成。Cline 同样没有独立的 `ToolRegistry` 类，工具注册表是 `AgentRuntime.tools: Map<string, AgentTool>`（`agent-runtime.ts` L401）。nanobot 原始代码中的 `ToolRegistry` 类（`nanobot/agent/tools/registry.py` L8）**未被 Charles 沿用**，这是 Charles 主动重构为 Cline 风格的结果。
2. **别名支持位置不同**：Cline 的 `CONFIGURED_AGENT_TOOL_NAME_ALIASES`（`runtime-builder.ts` L86-98）是配置化子 agent（configured-agent）层面的工具名别名映射（如 `bash → run_commands`、`write_to_file → editor`），**不是** Registry 层的别名。Registry 层两者都按 `tool.name` 单一注册，无别名。计划 P3.7.3 描述"Charles 缺失别名"是不准确的：Cline Registry 本身也无别名，别名只在 configured-agent 子模块中存在。
3. **MCP 工具注入方式本质不同**：Cline 将每个 MCP 工具作为独立的 first-class `AgentTool` 注入注册表（`runtime-builder.ts` L454-456 `tools.push(...mcpRuntime.tools)`）；Charles 注册一个统一的 `UseMcpToolTool` 调度器工具（`mcp.py` L46），运行时通过 `MCPRegistry` 路由到具体 MCP 服务器工具。两者在 LLM 看到的工具列表形态不同：Cline 暴露每个 MCP 工具为独立 function，Charles 暴露一个 `use_mcp_tool` function 让 LLM 传 `server_name + tool_name + args`。
4. **工具预设（presets）实现层级不同**：Cline 的 `ToolPresets`（`presets.ts` L20-109）是 5 种预设（act/plan/search/minimal/yolo）的静态 enableXxx 开关，参与运行时工具创建；Charles 的 `TOOL_PRESETS`（`constants.py` L112-140）是 2 种预设（act/plan）的 **文档化字典**，明确注释"本字典仅作文档参考，不参与运行时过滤"（L106）。Charles 的实际过滤由 `agent/tools/routing.py` 的 `ToolRoutingRule` 动态规则实现。

`nanobot` 残留检查：在 `agent/runtime.py`、`agent/tools/base.py`、`agent/tools/routing.py`、`agent/tools/constants.py` 四个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）；`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标注说明，详见第 4 节。

## 2. 逐项对比表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 3.7.1 | Registry 数据结构 | `agent-runtime.ts` L401（`tools = new Map<string, AgentTool>`） | `runtime.py` L253（`_tools: dict[str, AgentTool]`） | Map vs dict，均按 tool.name 键存储，语义等价 | 已对齐 |
| 3.7.2 | Registry 是否独立类 | 无独立类，AgentRuntime 内联管理 | 无独立类，AgentRuntime 内联管理 | 两者均无独立 ToolRegistry 类；计划描述"Charles 有 ToolRegistry 类"不准确 | 已对齐 |
| 3.7.3 | 工具注册时机 | `agent-runtime.ts` L525-541（`initialize()` 首次 run 时遍历 config.tools 调 `this.tools.set`） | `runtime.py` L364-366（`register_tool` 方法，由 server.py L393-405 装配时显式调用） | Cline 在首次 run 时懒加载初始化；Charles 在装配阶段显式注册（run 前） | 已对齐 |
| 3.7.4 | 别名支持（Registry 层） | 无（Map 按 tool.name 单一注册） | 无（dict 按 tool.name 单一注册） | 两者 Registry 层均无别名；计划 P3.7.3 描述"Charles 缺失"不准确 | 已对齐 |
| 3.7.5 | 别名支持（configured-agent 层） | `runtime-builder.ts` L86-98（`CONFIGURED_AGENT_TOOL_NAME_ALIASES` 映射 bash/write_to_file 等旧名到新名） | 无对应实现 | Charles 无 configured-agent 子模块，故无别名映射需求；属于子模块差异而非 Registry 差异 | 弱对齐（场景差异） |
| 3.7.6 | 动态注册 API | `agent-runtime.ts` L529（`this.tools.set(tool.name, tool)`，初始化时遍历 config.tools） + `session-runtime-orchestrator.ts` L486（`addTools` 追加） + plugin-sandbox `api.registerTool` | `runtime.py` L364-366（`register_tool(tool)`，server.py / skills/registry.py 调用） | 两者均支持动态注册；Cline 有 plugin/extension 多入口，Charles 仅 runtime.register_tool 单入口 | 已对齐 |
| 3.7.7 | 工具启用/禁用字段 | `toolPolicies[toolName].enabled`（`session-runtime-orchestrator.ts` L118-130 `isToolEnabledByPolicies`） | `tool_policies[tool_name]["enabled"]`（`runtime.py` L1559-1564，server.py L370） | 字段名差异（toolPolicies vs tool_policies），语义等价；Cline 在 tools 列表构建时过滤，Charles 在 _prepare_tool_execution 时 skip | 已对齐 |
| 3.7.8 | get_definitions 过滤 | `agent-runtime.ts` L826-830（内联构建 AgentToolDefinition，无过滤） | `runtime.py` L445-472（`get_tools` 内联构建 + `_resolve_tool_routing_toggles` 过滤） | Cline runtime 层不过滤，过滤在 session-runtime-orchestrator 上游完成；Charles runtime 层应用 routing 过滤 | 弱对齐（过滤位置不同） |
| 3.7.9 | 工具覆盖（同名注册） | `Map.set` 语义：后注册覆盖（`agent-runtime.ts` L528-529） | `dict[key] = value` 语义：后注册覆盖（`runtime.py` L366） | 两者均后注册覆盖，语义等价 | 已对齐 |
| 3.7.10 | 工具覆盖（config vs extension） | `session-runtime-orchestrator.ts` L818-824（`mergedToolsByName` 先放 extensionTools，再用 config.tools 覆盖，config 胜） | 无对应分层机制（server.py 单一注册源） | Cline config 工具优先于 extension 工具；Charles 无 extension 层，无需覆盖 | 弱对齐（场景差异） |
| 3.7.11 | MCP 工具注入方式 | `runtime-builder.ts` L454-456（`loadConfiguredMcpTools` 加载每个 MCP 工具为独立 AgentTool，`tools.push(...mcpRuntime.tools)`） | `mcp.py` L46（`UseMcpToolTool` 单一调度器工具）+ `mcp.py` L131（`AccessMcpResourceTool`） | Cline 每个 MCP 工具是 first-class AgentTool；Charles 用统一调度器工具路由 | 弱对齐（架构差异） |
| 3.7.12 | MCP 工具数量暴露 | 每个 MCP 工具独立暴露给 LLM | 仅暴露 `use_mcp_tool` + `access_mcp_resource` 两个 function | LLM 看到的 function 数量不同；Cline 直观但数量多，Charles 紧凑但需 LLM 知道 server_name/tool_name | 弱对齐（架构差异） |
| 3.7.13 | 工具预设（presets）数量 | `presets.ts` L20-109（5 种：act/plan/search/minimal/yolo） | `constants.py` L112-140（2 种：act/plan） | Charles 缺 search/minimal/yolo 预设；量化场景无需求 | 已对齐（场景裁剪） |
| 3.7.14 | 工具预设运行时参与 | `presets.ts` L175-190（`createDefaultToolsWithPreset` 按 preset 创建工具集） | `constants.py` L106 注释明确"本字典仅作文档参考，不参与运行时过滤" | Cline 预设是工具创建的依据；Charles 预设是文档，实际过滤由 routing.py 实现 | 弱对齐（实现层级不同） |
| 3.7.15 | 模型工具路由规则 | `model-tool-routing.ts` L60-75（`DEFAULT_MODEL_TOOL_ROUTING_RULES` 2 条规则） | `routing.py` L59-74（`DEFAULT_MODEL_TOOL_ROUTING_RULES` 2 条规则） | 规则数量、内容、匹配逻辑完全一致 | 已对齐 |
| 3.7.16 | 路由规则应用时机 | `runtime-builder.ts` L137-142（`createBuiltinToolsList` 创建工具时合并 preset + routing config，决定是否创建工具） | `runtime.py` L466-471（`get_tools` 列出工具时按 toggles 过滤） | Cline 在工具**创建**时应用路由（不创建的工具不存在）；Charles 在工具**列出**时应用路由（工具存在但被过滤） | 弱对齐（时机不同） |
| 3.7.17 | 路由规则匹配逻辑 | `model-tool-routing.ts` L77-103（`matchesModelId` 子串匹配 + `matchesRule` mode/provider/model 三条件） | `routing.py` L77-105（`_matches_id` 子串匹配 + `_matches_rule` mode/provider/model 三条件） | 逻辑完全一致，大小写不敏感、子串匹配、空列表不限制 | 已对齐 |
| 3.7.18 | 路由规则覆盖语义 | `model-tool-routing.ts` L117-127（后匹配规则覆盖先匹配，同工具名以最后一次为准） | `routing.py` L132-138（后命中规则覆盖先命中，同工具名以最后一次为准） | 覆盖语义完全一致 | 已对齐 |
| 3.7.19 | 工具排序（插入顺序） | `agent-runtime.ts` L826（`[...this.tools.values()]`，JS Map 保留插入顺序） | `runtime.py` L454（`for tool in self._tools.values()`，Python 3.7+ dict 保留插入顺序） | 两者均保留插入顺序，语义等价 | 已对齐 |
| 3.7.20 | 工具列表构建位置 | `agent-runtime.ts` L823-835（`generateAssistantMessage` 内联构建 request.tools） | `runtime.py` L848-854（`_generate_assistant_message` 调 `self.get_tools()` 填充 request.tools） | Cline 内联构建；Charles 抽取为 `get_tools()` 方法（含 routing 过滤） | 已对齐 |
| 3.7.21 | 工具列表 before_model 修改 | `agent-runtime.ts` L867-869（before_model hook 可替换 `result.tools`） | `runtime.py` L2118-2119（before_model hook 可替换 `result.tools`） | 两者均允许 before_model hook 修改工具列表，语义等价 | 已对齐 |
| 3.7.22 | 插件工具注册 | `agent-runtime.ts` L530-538（`plugin.setup()` 返回 tools，逐个 `this.tools.set`） + `plugin-sandbox-bootstrap.ts` L455（`api.registerTool`） | 无插件系统（Charles 无 plugin 概念） | Cline 有插件工具注册路径；Charles 无插件系统 | 弱对齐（场景差异） |
| 3.7.23 | skills 工具注册 | `definitions.ts` L719-769（`createSkillsTool` 工厂，由 `createDefaultTools` 按需创建） | `server.py` L405（`runtime.register_tool(SkillsTool(registry, ...))` 显式注册） | Cline 在 createDefaultTools 中按 enableSkills 标志创建；Charles 在 server.py 装配时显式注册 | 已对齐 |
| 3.7.24 | 工具总数（默认） | 9 个内置 + spawn_agent + teams + MCP 工具 + 插件工具 | 17 个内置（含 SwitchToAct/Plan/TodoWrite/UseMcpTool/AccessMcpResource） | 工具集差异详见 P3.9 内置工具清单对比 | 已对齐（清单差异见 P3.9） |

## 3. 重点差距详细说明

### 3.1 Charles 无独立 ToolRegistry 类：计划描述与实际代码不符

- **计划描述**：P3.7 表格声称"Charles `ToolRegistry` 类管理工具注册"。
- **实际代码**：Charles **没有** `ToolRegistry` 类。全局搜索 `class ToolRegistry` 仅在两个位置命中：
  1. `AGENT_MIGRATION_PLAN.md` L700（历史迁移计划文档，非源码）
  2. `third_party/charles_bundle/nanobot-main/nanobot/agent/tools/registry.py` L8（nanobot 原始代码，未引入 Charles）
- **Charles 实际实现**：`AgentRuntime._tools: dict[str, AgentTool]`（`runtime.py` L253）直接承担注册表角色，通过 `register_tool(tool)` 方法（L364-366）注册：
  ```python
  def register_tool(self, tool: AgentTool) -> None:
      """注册工具 — 对标 Cline AgentRuntime tools Map.set"""
      self._tools[tool.name] = tool
  ```
- **Cline 实际实现**：`AgentRuntime.tools: Map<string, AgentTool>`（`agent-runtime.ts` L401）同样内联在 AgentRuntime 中，无独立 Registry 类。工具注册在 `initialize()` 方法（L525-541）中遍历 `config.tools` 调用 `this.tools.set(tool.name, tool)`。
- **影响**：计划描述会误导后续修复决策，让人以为 Charles 有独立的 Registry 类需要对标。实际上两者均采用"runtime 内联管理"模式，结构已对齐。
- **残留性质**：非残留，属于计划描述错误。nanobot 的 `ToolRegistry` 类被 Charles 主动重构为 Cline 风格，是正确的架构演进。

### 3.2 别名支持位置不同：Registry 层两者均无别名

- **计划描述**：P3.7.3 表格声称"Cline 支持别名，Charles 缺失"。
- **Cline Registry 层**：`AgentRuntime.tools` 是 `Map<string, AgentTool>`，按 `tool.name` 单一注册，无别名机制。`this.tools.set(tool.name, tool)` 和 `this.tools.get(toolCall.toolName)`（`agent-runtime.ts` L1337）均使用原始 tool.name。
- **Cline configured-agent 层**：`CONFIGURED_AGENT_TOOL_NAME_ALIASES`（`runtime-builder.ts` L86-98）定义了 11 个别名映射（如 `bash → run_commands`、`write_to_file → editor`、`apply_diff → editor`），但这是为配置化子 agent（configured-agent）解析用户配置的工具名时使用，**不是** Registry 层的别名。`resolveConfiguredAgentToolName`（L100-103）在解析配置时将旧名映射到新名，映射后仍按新名注册到 Registry。
- **Charles**：无 configured-agent 子模块，故无别名映射需求。Registry 层同样按 `tool.name` 单一注册。
- **影响**：计划描述混淆了"Registry 层别名"和"configured-agent 层别名"。两者 Registry 层均无别名，Cline 的别名是 configured-agent 子模块的功能，与 Registry 机制无关。
- **残留性质**：非残留，属于计划描述不准确。

### 3.3 MCP 工具注入方式本质不同：first-class 工具 vs 统一调度器

- **Cline**：`loadConfiguredMcpTools`（`runtime-builder.ts` L454）加载所有配置的 MCP 服务器工具，每个 MCP 工具成为一个独立的 `AgentTool`，通过 `tools.push(...mcpRuntime.tools)` 注入到工具列表。LLM 看到每个 MCP 工具作为独立的 function，可直接调用。
- **Charles**：`UseMcpToolTool`（`mcp.py` L46）是一个统一的调度器工具，注册到 runtime 后 LLM 通过 `use_mcp_tool(server_name="xxx", tool_name="yyy", args={...})` 调用。`AccessMcpResourceTool`（`mcp.py` L131）类似。LLM 看到的是 2 个 function（`use_mcp_tool` + `access_mcp_resource`），具体 MCP 工具在运行时通过 `MCPRegistry` 路由。
- **影响**：
  1. LLM 看到的工具列表形态不同：Cline 暴露每个 MCP 工具为独立 function（直观但数量多），Charles 暴露统一调度器（紧凑但需 LLM 知道 server_name/tool_name）。
  2. 工具审批策略粒度不同：Cline 可对每个 MCP 工具单独配置 `toolPolicies`；Charles 通过 `_get_mcp_tool_policy_override`（`runtime.py` L1596-1644）在 `use_mcp_tool` 调用时动态查询 MCP 工具策略，实现等价粒度。
  3. 工具描述丰富度不同：Cline 的 MCP 工具描述由 MCP 服务器提供（含完整 inputSchema）；Charles 的 `use_mcp_tool` 描述是固定的（不含具体 MCP 工具的 inputSchema），LLM 需通过其他方式获知可用 MCP 工具。
- **残留性质**：非残留，属于架构设计差异。Charles 的统一调度器模式更紧凑，适合 MCP 工具数量多的场景；Cline 的 first-class 模式更直观，适合 MCP 工具数量少的场景。

### 3.4 工具预设（presets）实现层级不同：静态预设 vs 动态路由

- **Cline**：`ToolPresets`（`presets.ts` L20-109）定义 5 种预设（act/plan/search/minimal/yolo），每种预设是一组 enableXxx 布尔开关。`createDefaultToolsWithPreset`（L175-190）按预设创建工具集，`createBuiltinToolsList`（`runtime-builder.ts` L126-160）合并预设 + 路由配置后调 `createDefaultTools` 创建工具。预设是工具**创建**的依据：未启用的工具根本不会被创建。
- **Charles**：`TOOL_PRESETS`（`constants.py` L112-140）定义 2 种预设（act/plan），但注释明确说明：
  ```
  本系统不引入预设机制，实际工具过滤由 agent/tools/routing.py 的 mode-based 路由实现
  （动态规则比静态预设更灵活）。此处仅文档化各 mode 的工具集预期，
  便于排查 routing 规则与实际行为的差异。
  ```
  `resolve_tool_preset`（L143-156）函数也注释"仅文档化用途...本函数不参与运行时过滤"。实际过滤由 `routing.py` 的 `ToolRoutingRule` 动态规则实现。
- **影响**：
  1. Cline 预设决定工具**是否存在**（创建时过滤）；Charles 预设仅文档化，工具**存在但被 routing 过滤**（列出时过滤）。
  2. Cline 的 `search/minimal/yolo` 预设在 Charles 中无对应；Charles 注释称"量化场景无需求"和"yolo 模式涉及实盘交易安全，不默认开启"。
  3. Charles 的动态路由更灵活（可按 provider/model/mode 组合规则），但牺牲了预设的简洁性。
- **残留性质**：非残留，属于设计选择差异。Charles 主动选择动态路由替代静态预设，并在 `constants.py` 文档化了这一决策。

### 3.5 路由规则应用时机不同：创建时过滤 vs 列出时过滤

- **Cline**：`createBuiltinToolsList`（`runtime-builder.ts` L136-142）在工具创建时合并 `preset` + `toolRoutingConfig`，调 `createBuiltinTools` 时传入合并后的 enableXxx 标志。未启用的工具**不会被创建**，因此不会出现在 `AgentRuntime.tools` Map 中。
- **Charles**：`get_tools`（`runtime.py` L445-472）在列出工具时调 `_resolve_tool_routing_toggles()`（L474-515）获取开关字典，然后 `defs = [d for d in defs if toggles.get(d.name, True)]` 过滤。工具**始终被注册**到 `_tools` dict 中，仅在 `get_tools` 返回时被过滤掉。
- **影响**：
  1. 工具执行可达性不同：Cline 未创建的工具无法被 `_tools.get(toolCall.toolName)` 找到（`agent-runtime.ts` L1337），返回 "Unknown tool"；Charles 被路由过滤的工具仍存在于 `_tools` dict 中，`_prepare_tool_execution`（`runtime.py` L1458）能找到工具，但 `get_tools` 不暴露给 LLM，LLM 理论上不会调用到。
  2. 内存占用：Charles 注册所有工具但部分被过滤；Cline 仅注册启用的工具。差异可忽略。
  3. 动态切换：Charles 的 routing 规则可在运行时通过修改 `config.tool_routing_rules` 改变过滤结果（下次 `get_tools` 生效）；Cline 的工具集在 `createBuiltinToolsList` 创建后固定，需重新构建 runtime 才能改变。
- **残留性质**：非残留，属于实现策略差异。Charles 的列出时过滤更灵活，支持运行时动态切换；Cline 的创建时过滤更彻底，工具集更稳定。

## 4. nanobot 残留检查

在 `agent/runtime.py`、`agent/tools/base.py`、`agent/tools/routing.py`、`agent/tools/constants.py` 四个重点文件中 **未发现** `nanobot` 字符串残留（注释与实现均无）。

`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标说明，未影响工具注册表机制。重点文件清单：

| 文件 | 残留性质 | 是否影响 ToolRegistry |
|------|---------|----------------------|
| `agent/runtime.py` | 无残留 | 不适用 |
| `agent/tools/base.py` | 无残留 | 不适用 |
| `agent/tools/routing.py` | 无残留 | 不适用 |
| `agent/tools/constants.py` | 无残留 | 不适用 |
| `agent/tools/__init__.py` L2 | docstring 标题对标说明 | 否（注释） |
| `agent/tools/exec_tool.py` L2-263 | 多处 docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | 多处 docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | 多处 docstring 对标 nanobot WebSearchTool | 否（注释） |
| `agent/server.py` L2-28 | docstring 对标 nanobot routes/chat.py | 否（注释） |
| `agent/skills/loader.py` L2-423 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/skills/registry.py` L2-184 | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/skills/__init__.py` L2-23 | docstring 对标说明 | 否（注释） |
| `agent/providers/qwen.py` L21-406 | 多处 docstring 对标 nanobot openai_compat_provider | 否（注释） |
| `agent/session.py` L2-22 | docstring 对标 nanobot session_key | 否（注释） |
| `agent/context.py` L275 | 注释标注"[已废弃] nanobot 风格的额外段落" | 否（注释） |

> 注：上述残留全部为注释/docstring 性质，**无实现逻辑残留**。关键证据：nanobot 原始代码中的 `ToolRegistry` 类（`nanobot/agent/tools/registry.py` L8-87，含 `register`/`unregister`/`get`/`has`/`get_definitions`/`prepare_call`/`execute` 方法）**未被 Charles 沿用**。Charles 主动重构为 Cline 风格的 `AgentRuntime._tools` dict + `register_tool` 方法，方法签名与 Cline `AgentRuntime.tools.set` 对齐。Charles 的 `get_tools`（L445-472）返回 `list[AgentToolDefinition]`，与 Cline `agent-runtime.ts` L826-830 内联构建 `AgentToolDefinition[]` 语义一致，而 nanobot 的 `get_definitions` 返回 `list[dict[str, Any]]`（OpenAI 格式 schema）已被弃用。

## 5. 修复建议

### P0（阻碍后续对比/集成）
1. **修正计划 P3.7 描述**：计划表格声称"Charles 有 `ToolRegistry` 类管理工具注册"，实际 Charles 无独立 ToolRegistry 类，工具注册表内联在 `AgentRuntime._tools` dict 中。建议将计划描述改为"Charles `AgentRuntime._tools` dict 管理工具注册，无独立 Registry 类，与 Cline `AgentRuntime.tools` Map 结构对齐"，避免误导后续修复决策。
2. **修正计划 P3.7.3 别名描述**：计划声称"Cline 支持别名，Charles 缺失"。实际 Cline Registry 层也无别名，别名仅在 configured-agent 子模块存在。建议将描述改为"Cline configured-agent 层有别名映射（`CONFIGURED_AGENT_TOOL_NAME_ALIASES`），Charles 无 configured-agent 子模块故无别名；Registry 层两者均无别名"。

### P1（架构债务）
3. **评估 MCP 工具注入方式是否需对齐**：Cline 将每个 MCP 工具作为 first-class AgentTool 注入，Charles 用统一调度器工具。两者各有优劣：
   - Cline 方式：LLM 直观调用，但 MCP 工具数量多时 function 列表膨胀；工具描述由 MCP 服务器提供，含完整 inputSchema。
   - Charles 方式：LLM 需知道 server_name/tool_name，但 function 列表紧凑；工具描述固定，不含具体 MCP 工具 inputSchema。
   建议保留 Charles 现有方式（统一调度器），但在 `use_mcp_tool` 的 description 中动态注入可用 MCP 工具列表（类似 Cline `createSkillsTool` 在 description 中列出可用 skills 的做法，`definitions.ts` L754-766），提升 LLM 调用准确率。
4. **评估工具预设是否需参与运行时**：Charles `TOOL_PRESETS` 当前仅作文档参考。若未来需要支持 `search/minimal/yolo` 等预设场景，建议将 `resolve_tool_preset` 改为返回 routing 规则（而非文档字典），让预设通过 routing 机制生效，避免引入两套过滤机制。

### P2（功能增强）
5. **统一 routing 应用时机**：Charles 在 `get_tools` 列出时过滤，Cline 在工具创建时过滤。两者行为等价（LLM 看到的工具列表一致），但 Charles 的列出时过滤更灵活（支持运行时动态切换 routing 规则）。建议保留 Charles 现有方式，但在文档中明确标注"Charles routing 在 get_tools 时应用，Cline routing 在 createBuiltinToolsList 时应用"。
6. **补齐 configured-agent 别名映射（如引入 configured-agent 子模块）**：若 Charles 未来引入 configured-agent 子模块（对标 Cline `createConfiguredAgentTools`），需同步实现 `CONFIGURED_AGENT_TOOL_NAME_ALIASES` 别名映射，让用户配置中使用旧名（如 `bash`/`write_to_file`）时能正确映射到新名。当前 Charles 无此子模块，属于预留建议。

### P3（文档/规范）
7. **清理 nanobot 残留**：`agent/tools/__init__.py` L2、`agent/tools/exec_tool.py`/`file_tools.py`/`web_tool.py` 的多处 docstring、`agent/server.py` L2-28、`agent/skills/` 系列文件、`agent/providers/qwen.py`、`agent/session.py`、`agent/context.py` 的 40+ 处 nanobot 历史对标注释，统一改为"Charles 历史实现"或直接删除。
8. **补齐计划 P3.7 字段清单**：计划 P3.7 表格未列出工具预设（presets）、模型工具路由（model-tool-routing）、工具排序、MCP 工具注入方式等对比项，建议补齐（已在本文档第 2 节补充 3.7.11-3.7.24）。

## 6. 验证方法建议

1. **Registry 数据结构验证**：在 Charles 中创建 `AgentRuntime(config)` 实例，注册一个工具后检查 `runtime._tools` 是 dict 类型且按 `tool.name` 键存储；与 Cline `runtime.tools` 是 Map 类型且按 `tool.name` 键存储对比，确认结构等价。
2. **工具注册时机验证**：在 Charles `register_tool` 方法加断点，确认 server.py L393-405 装配阶段调用；在 Cline `initialize` 方法加断点，确认首次 run 时调用。两者均在 run 开始前完成注册。
3. **别名缺失验证**：在 Charles 注册一个工具 `tool.name = "foo"`，尝试 `runtime._tools.get("bar")` 应返回 None；在 Cline 同样验证 `runtime.tools.get("bar")` 返回 undefined。确认两者 Registry 层均无别名。
4. **MCP 工具注入方式验证**：在 Charles 配置一个 MCP 服务器，启动后检查 `runtime._tools` 中只有 `use_mcp_tool` 和 `access_mcp_resource` 两个 MCP 相关工具；在 Cline 同样配置后检查 `runtime.tools` 中应包含每个 MCP 工具作为独立 AgentTool。
5. **routing 应用时机验证**：在 Charles 修改 `config.tool_routing_rules` 后，下次 `get_tools()` 调用应返回新过滤结果（无需重建 runtime）；在 Cline 修改 `toolRoutingRules` 后需重建 runtime 才能生效。验证 Charles 的列出时过滤更灵活。
6. **工具覆盖语义验证**：在 Charles 连续注册两个同名工具 `runtime.register_tool(tool_a)` 和 `runtime.register_tool(tool_b)`，`runtime._tools["foo"]` 应为 `tool_b`；在 Cline 同样验证 `runtime.tools.get("foo")` 应为后注册的工具。
7. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/` 并统计行数，建立基线（当前约 55 行）；后续修复后确认重点文件（runtime.py / tools/base.py / tools/routing.py / tools/constants.py）无残留。
8. **预设文档化性质验证**：在 Charles 修改 `TOOL_PRESETS` 字典内容，运行 agent 后确认工具列表无变化（因预设不参与运行时过滤）；修改 `DEFAULT_MODEL_TOOL_ROUTING_RULES` 后运行 agent，确认工具列表按新规则过滤。
