# Phase 3.20 模型工具路由对比（model-tool-routing 按模型路由工具集）

> 对比范围：Cline `model-tool-routing.ts` + `runtime.ts`（路由应用）+ `presets.ts`（plan/act 预设）+ `runtime-builder.ts`（应用时机） 与 Charles `agent/tools/routing.py`（路由规则与解析）+ `agent/runtime.py`（路由集成 `get_tools` / `_resolve_tool_routing_toggles`）+ `agent/server.py`（plan 模式 tool_policies）的实现差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/model-tool-routing.ts`（核心：规则定义 + 解析函数）
> - `sdk/packages/core/src/extensions/tools/model-tool-routing.test.ts`（行为用例）
> - `sdk/packages/core/src/extensions/tools/runtime.ts` L135-160（`resolvePresetFlags` 路由应用）
> - `sdk/packages/core/src/extensions/tools/presets.ts`（plan/act/yolo 预设工具集）
> - `sdk/packages/core/src/extensions/tools/types.ts` L226-280（`DefaultToolName` / `DefaultToolsConfig`）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L126-161（`createBuiltinToolsList` 路由应用时机）
> - `sdk/packages/core/src/types/config.ts` L278（`toolRoutingRules` 配置字段）
> - `sdk/packages/shared/src/session/runtime-config.ts` L3（`AgentMode` 类型）
>
> Charles 源码：
> - `agent/tools/routing.py`（核心：规则定义 + 解析函数 + 模型信息提取）
> - `agent/runtime.py` L445-515（`get_tools` / `_resolve_tool_routing_toggles` 路由集成）
> - `agent/types.py` L558-564（`AgentRuntimeConfig.provider_id` / `model_id` / `tool_routing_rules`）
> - `agent/server.py` L340-386（`_create_runtime` plan 模式 tool_policies + 路由配置注入）
> - `agent/state.py` L58 / L363-365（`AgentMode` 类型 + `get_mode`）
> - `agent/tools/__init__.py` L48-112（`create_default_tools` 全量装配）

---

## 一、执行摘要

Cline 与 Charles 在"按模型路由工具集"这一能力上**核心算法高度一致**，但在**应用范式**与**集成架构**上存在结构性差异：

1. **核心算法完全对齐**：两侧的规则数据结构（`ToolRoutingRule`）、默认规则（`DEFAULT_MODEL_TOOL_ROUTING_RULES`，2 条规则完全相同）、子串匹配逻辑（大小写不敏感）、规则顺序应用（后匹配覆盖先匹配）、mode 过滤（`"any"` 通配）等核心逻辑一一对应。Charles `routing.py` 的每个函数都明确标注了对标 Cline 的对应函数。

2. **关键架构差异**：
   - **Cline 路由输出是 `enable*` 开关标志**（`Partial<DefaultToolsConfig>`），在**runtime 构建期**一次性应用，与 `ToolPresets` 预设融合后传入 `createDefaultTools` 决定**是否实例化工具**。
   - **Charles 路由输出是工具名→布尔字典**（`dict[ToolName, bool]`），在**每次 `get_tools()` 调用时**动态应用，过滤**已实例化的工具定义列表**。
   - 两者应用层级不同：Cline 是"装配期过滤"（按标志决定是否创建工具实例），Charles 是"序列化期过滤"（工具已全部实例化，按字典过滤 definition）。

3. **plan/act 模式工具集差异**：
   - Cline 通过 `ToolPresets.plan`（`enableEditor: false` / `enableApplyPatch: false`）+ 路由规则 `mode: "act"` 限制，实现 plan 模式下编辑类工具关闭。
   - Charles **无 preset 系统**，plan 模式下编辑类工具的禁用由 `server.py` 的 `tool_policies`（`enabled: False`）实现，与路由系统**分离**。路由系统只负责模型维度（openai-native / codex / gpt）的过滤，不负责模式维度。

4. **Charles 多出的辅助函数**：
   - `extract_model_info(model)`：从模型对象推断 `provider_id` / `model_id`（Cline 无此逻辑，providerId/modelId 由 config 直接提供）。
   - `apply_tool_routing(tools, toggles)`：通用工具列表过滤函数（Cline 无等价物）。但经核查，**runtime.get_tools() 并未调用此函数**，而是内联了相同的过滤逻辑——`apply_tool_routing` 属于未使用的冗余函数（或预留给外部调用）。

5. **AgentMode 类型差异**：Cline `AgentMode = "act" | "plan" | "yolo" | "zen"`（4 种模式），Charles `AgentMode = Literal["act", "plan"]`（2 种模式）。Charles 不支持 yolo / zen 模式，路由规则中 `mode: "yolo"` 在 Charles 中无意义。

6. **nanobot 残留**：P3.20 核心文件（`routing.py` / `runtime.py` 路由段落 / `server.py` 路由配置 / `types.py` 路由字段）**0 处 nanobot 残留**，已完全清理。

7. **一致性总体评估**：**高**。核心路由算法（规则定义、匹配逻辑、顺序应用）完全对齐，差异集中在应用架构（构建期 vs 运行期、enable* 标志 vs 工具名字典）和 plan 模式的实现路径（preset vs tool_policies），这些差异属于设计选择，不影响路由功能正确性。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.20.1 | 规则数据结构 | `interface ToolRoutingRule`（TS 接口） | `@dataclass ToolRoutingRule`（Python 数据类） | 高 | 字段语义完全对应，仅命名风格差异（camelCase vs snake_case） |
| 3.20.2 | 规则字段：name | `name?: string`（可选） | `name: str = ""`（默认空串） | 高 | 语义等价，都用于调试标签 |
| 3.20.3 | 规则字段：mode | `mode?: CoreAgentMode \| "any"` | `mode: Mode \| Literal["any"] = "any"` | 中 | Cline CoreAgentMode 含 4 种模式，Charles Mode 仅 2 种 |
| 3.20.4 | 规则字段：modelIdIncludes | `modelIdIncludes?: string[]` | `model_id_includes: list[str]` | 高 | 语义一致 |
| 3.20.5 | 规则字段：providerIdIncludes | `providerIdIncludes?: string[]` | `provider_id_includes: list[str]` | 高 | 语义一致 |
| 3.20.6 | 规则字段：enableTools | `enableTools?: DefaultToolName[]` | `enable_tools: list[ToolName]` | 高 | Cline 限定枚举，Charles 用 str |
| 3.20.7 | 规则字段：disableTools | `disableTools?: DefaultToolName[]` | `disable_tools: list[ToolName]` | 高 | 同上 |
| 3.20.8 | DefaultToolName 类型 | 联合字面量类型（9 个枚举值） | `ToolName = str`（无类型约束） | 中 | Charles 无编译期校验，依赖运行时 |
| 3.20.9 | TOOL_NAME_TO_FLAG 映射 | 存在（9 个工具名 → enable* 标志） | **不存在**（注释说明"直接用工具名作为 key"） | 中 | 架构差异：Cline 路由输出是 enable* 标志，Charles 是工具名→布尔 |
| 3.20.10 | 默认路由规则 | 2 条规则（openai-native + codex/gpt） | 2 条规则（完全相同） | 高 | 名称、mode、includes、enable/disable 工具列表逐一对应 |
| 3.20.11 | 子串匹配逻辑 | `matchesModelId`：大小写不敏感子串匹配，空数组→true | `_matches_id`：大小写不敏感子串匹配，空/None→true | 高 | 算法完全一致 |
| 3.20.12 | 规则匹配逻辑 | `matchesRule`：mode 检查 + provider + model 双重匹配 | `_matches_rule`：mode 检查 + provider + model 双重匹配 | 高 | 逻辑完全一致 |
| 3.20.13 | 路由解析函数 | `resolveToolRoutingConfig` 返回 `Partial<DefaultToolsConfig>` | `resolve_tool_routing` 返回 `dict[ToolName, bool]` | 中 | 输出类型不同，但都用于过滤工具 |
| 3.20.14 | 规则应用顺序 | 按数组顺序，disable 先于 enable（同规则内） | 按列表顺序，disable 先于 enable（同规则内） | 高 | 完全一致 |
| 3.20.15 | 后匹配覆盖先匹配 | 同工具名以最后一次 toggle 为准（Map 覆盖） | 同工具名以最后一次 toggle 为准（dict 覆盖） | 高 | 完全一致 |
| 3.20.16 | 空规则返回值 | `rules` 为空/undefined → 返回 `{}` | `rules` 为空/None → 返回 `{}` | 高 | 完全一致 |
| 3.20.17 | 路由应用时机 | **runtime 构建期**（`createBuiltinToolsList` 一次性应用） | **每次 `get_tools()` 调用时**（每轮 LLM 请求都解析） | 中 | Charles 更动态（mode 变化即时生效），Cline 更高效（一次计算） |
| 3.20.18 | 路由应用方式 | 融合到 preset flags → `createDefaultTools` 按标志实例化 | `get_tools()` 内联过滤 definition 列表 | 中 | Cline 装配期过滤，Charles 序列化期过滤 |
| 3.20.19 | plan/act 预设系统 | `ToolPresets`（act/plan/search/minimal/yolo 5 套预设） | **无预设系统** | 低 | Charles 缺 preset 抽象层 |
| 3.20.20 | plan 模式编辑工具禁用 | preset `enableEditor: false` + 路由 `mode: "act"` 限制 | `server.py` `tool_policies: {enabled: False}` | 中 | 实现路径不同，效果一致 |
| 3.20.21 | mode 获取方式 | 从 `BuiltinToolAvailabilityContext.mode` 传入 | `agent.state.get_mode(session_id)` 运行时查询 | 高 | Charles 从会话状态读取，Cline 从上下文传入 |
| 3.20.22 | provider_id / model_id 来源 | config 上下文直接提供 | `extract_model_info(model)` 推断 + config 显式覆盖 | 中 | Charles 多了推断逻辑（兼容历史实现） |
| 3.20.23 | 模型信息提取函数 | 无（由调用方提供） | `extract_model_info`：显式属性优先 + 类名推断兜底 | 中 | Charles 独有，因 Charles model 对象无统一 provider_id 字段 |
| 3.20.24 | 工具列表过滤函数 | 无独立函数（`createDefaultTools` 内联按标志创建） | `apply_tool_routing(tools, toggles)` 独立函数 | 低 | Charles 有但**未被 runtime 调用**（冗余） |
| 3.20.25 | toolRoutingRules 配置字段 | `CoreSessionConfig.toolRoutingRules?: ToolRoutingRule[]` | `AgentRuntimeConfig.tool_routing_rules: list[Any] \| None` | 高 | 都支持外部自定义规则，None/undefined 时用默认规则 |
| 3.20.26 | AgentMode 类型 | `"act" \| "plan" \| "yolo" \| "zen"`（4 种） | `Literal["act", "plan"]`（2 种） | 中 | Charles 不支持 yolo / zen |
| 3.20.27 | 路由规则可自定义 | 支持（config.toolRoutingRules 覆盖默认） | 支持（config.tool_routing_rules 覆盖默认） | 高 | 完全一致 |
| 3.20.28 | editor 特殊处理 | `isEntryEnabledByDefault`：editor 在 apply_patch 开启时也算启用 | 无特殊处理（editor / apply_patch 独立过滤） | 中 | Cline 对 editor 有 catalog 级特殊逻辑 |

**一致性总评**：28 项中，高一致性 17 项、中一致性 9 项、低一致性 2 项（3.20.19 / 3.20.24）。低一致性项分别为 Charles 缺 preset 抽象层和存在未使用的 `apply_tool_routing` 冗余函数，不影响路由功能正确性。

---

## 三、重点差距详细说明

### 差距 1：路由输出类型与应用架构差异（3.20.9 / 3.20.13 / 3.20.17 / 3.20.18）

**Cline 实现**（`model-tool-routing.ts` L105-134 + `runtime-builder.ts` L126-161）：

`resolveToolRoutingConfig` 返回 `Partial<DefaultToolsConfig>`，即 `enable*` 标志对象。应用流程：

```
runtime-builder.createBuiltinToolsList:
  1. preset = ToolPresets[resolveToolPresetName({mode})]   // 取 preset 基础标志
  2. toolRoutingConfig = resolveToolRoutingConfig(...)     // 计算路由覆盖
  3. createBuiltinTools({ ...preset, ...toolRoutingConfig }) // 融合后传入工厂
     → enable* 标志决定是否调用对应工具工厂（如 enableEditor=false 则不创建 editor 工具实例）
```

关键点：Cline 通过 `TOOL_NAME_TO_FLAG` 映射表（L34-58）将工具名转为 `enable*` 标志，路由输出与 preset 融合后**在工具实例化阶段**决定哪些工具被创建。

**Charles 实现**（`routing.py` L108-139 + `runtime.py` L445-472）：

`resolve_tool_routing` 返回 `dict[ToolName, bool]`，即工具名→布尔字典。应用流程：

```
runtime.get_tools():
  1. defs = [tool.to_definition() for tool in self._tools.values()]  // 全量序列化
  2. toggles = self._resolve_tool_routing_toggles()                  // 计算路由开关
  3. if toggles: defs = [d for d in defs if toggles.get(d.name, True)] // 过滤
```

关键点：Charles **无 `TOOL_NAME_TO_FLAG` 映射**（`routing.py` L27-29 注释明确说明"直接用工具名作为 key，不需要再映射到字段名"），因为 Charles 没有 `DefaultToolsConfig` 的 `enable*` 标志系统。路由输出在**工具定义序列化阶段**过滤已实例化的工具。

**影响**：
- 功能等价：两者都能正确实现"按模型/模式启用或禁用工具"。
- 性能差异：Cline 在构建期一次计算，工具未实例化则无内存开销；Charles 每轮 LLM 请求都重新解析路由（`get_tools()` 在 `_generate_assistant_message` L851 每轮调用），但 16 个工具的过滤开销可忽略。
- 动态性差异：Charles 的方式让 mode 变化（如 plan → act 切换）**即时生效**（下一轮 `get_tools()` 即反映新 mode）；Cline 的方式在 runtime 构建期固定，mode 变化需要重建 runtime。

**建议**：不强制对齐。Charles 的运行期过滤方式更动态，符合 Charles 的会话级 mode 切换需求。

### 差距 2：plan/act 模式工具集实现路径分离（3.20.19 / 3.20.20）

**Cline 实现**（`presets.ts` + `runtime.ts` L135-160）：

Cline 有完整的 `ToolPresets` 预设系统，5 套预设（act / plan / search / minimal / yolo），每套预设定义所有 `enable*` 标志的默认值：

```typescript
plan: {
    enableReadFiles: true,  enableSearch: true,  enableBash: true,
    enableWebFetch: true,   enableApplyPatch: false,  enableEditor: false,
    enableSkills: true,     enableAskQuestion: true,  enableSubmitAndExit: false,
    enableSpawnAgent: true, enableAgentTeams: true,
}
```

`resolvePresetFlags`（runtime.ts L135-160）将 preset 与路由配置融合：`flags = { ...preset, ...routed }`。路由规则 `mode: "act"` 在 plan 模式下不匹配，因此 plan 模式保持 preset 默认值（editor=false, apply_patch=false）。

**Charles 实现**（`server.py` L358-377 + `routing.py`）：

Charles **无 preset 系统**，`create_default_tools` 全量实例化所有工具。plan 模式的工具禁用由 `server.py` 的 `tool_policies` 实现：

```python
if current_mode == "plan":
    tool_policies = {
        "editor": {"enabled": False, "reason": "Plan 模式下禁止编辑文件..."},
        "apply_patch": {"enabled": False, "reason": "Plan 模式下禁止打补丁..."},
        "file_write": {"enabled": False, "reason": "Plan 模式下禁止写文件..."},
    }
```

`tool_policies` 在 `_prepare_tool_execution`（runtime.py L1559-1564）中检查，`enabled: False` 的工具返回 `skip_reason`，不执行。

**关键差异**：
- Cline 的 plan 模式工具禁用是**装配级**（工具实例不存在，LLM 看不到工具定义）。
- Charles 的 plan 模式工具禁用是**执行级**（工具实例存在，LLM 看到工具定义，但调用时被 skip 并返回 reason）。
- Charles 的方式让 LLM 能看到工具存在但知道"被禁用"（skip_reason 会反馈给 LLM），Cline 的方式让 LLM 完全不知道有这些工具。
- 路由系统在 Charles 中**只负责模型维度**（openai-native / codex / gpt），**不负责模式维度**——模式维度由 tool_policies 承担。Cline 的路由系统也只负责模型维度（默认规则都是 `mode: "act"`），模式维度由 preset 承担。

**影响**：
- 功能效果接近：plan 模式下编辑类工具都不可用。
- LLM 体验差异：Charles 的 LLM 能看到工具但调用被拒（可能浪费一轮 token），Cline 的 LLM 看不到工具（更干净）。
- 架构清晰度：Cline 的 preset + routing 分工明确（模式维度 + 模型维度）；Charles 的 tool_policies + routing 也能分工，但 tool_policies 承担了本可由 preset 承担的职责。

**建议**：不强制补齐 preset 系统。Charles 的 tool_policies 方式已能满足 plan 模式需求，且提供了更细粒度的 reason 反馈。若未来支持 yolo / zen 等更多模式，可考虑引入 preset 层。

### 差距 3：`apply_tool_routing` 函数冗余（3.20.24）

**Charles 实现**（`routing.py` L142-167）：

```python
def apply_tool_routing(tools: list[Any], toggles: dict[ToolName, bool]) -> list[Any]:
    """根据路由开关过滤工具列表"""
    if not toggles:
        return list(tools)
    result: list[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
        if name is None:
            result.append(tool)
            continue
        enabled = toggles.get(name, True)
        if enabled:
            result.append(tool)
    return result
```

**问题**：此函数**未被 runtime 调用**。runtime.get_tools()（L466-472）内联了相同的过滤逻辑：

```python
toggles = self._resolve_tool_routing_toggles()
if toggles:
    defs = [d for d in defs if toggles.get(d.name, True)]
```

两者区别：`apply_tool_routing` 过滤的是工具对象列表（通过 `.name` 属性或 `["name"]` key），runtime 内联过滤的是 `AgentToolDefinition` 列表（通过 `.name` 属性）。runtime 选择内联是因为它已经持有 definition 列表，无需再调函数。

**影响**：
- 不影响功能：`apply_tool_routing` 是死代码，但不造成任何运行时问题。
- 维护风险：两处过滤逻辑若未来需要修改（如增加白名单逻辑），可能遗漏其中一处。
- 设计意图：可能是预留给外部调用方使用（如插件化工具过滤），但当前无调用方。

**建议**：可保留（预留给外部使用）或删除（减少冗余）。若保留，建议在 docstring 中标注"runtime 内联过滤未调用此函数，供外部工具列表过滤使用"。

### 差距 4：`extract_model_info` 推断逻辑 Charles 独有（3.20.22 / 3.20.23）

**Cline 实现**：

Cline 的 `providerId` / `modelId` 由调用方直接提供（`BuiltinToolAvailabilityContext.providerId` / `modelId`），`model-tool-routing.ts` 本身不涉及模型信息提取。`runtime-builder.ts` 从 session config 获取 providerId/modelId。

**Charles 实现**（`routing.py` L170-203）：

Charles 有 `extract_model_info(model)` 函数，三级推断：

1. **显式属性优先**：`model.provider_id` / `model.model`（若为非空字符串）
2. **类名推断兜底**：`type(model).__name__.lower()` 含 "qwen"/"dashscope" → "qwen"；含 "openai" → "openai"；含 "anthropic"/"claude" → "anthropic"
3. **返回空串**：未知时 provider_id 为空串

runtime 在 `_resolve_tool_routing_toggles`（L497-504）中调用：若 config 显式配置了 `provider_id` / `model_id` 则用配置值，否则调用 `extract_model_info` 推断。

**原因**：Charles 的 model 对象（如 `QwenModel`）没有统一的 `provider_id` 字段协议，需要从类名推断。Cline 的 model 配置在 session 层就明确了 providerId。

**影响**：
- Charles 的推断逻辑是兼容历史实现的兜底方案（注释说明"兼容 QwenModel 等历史实现"）。
- 若 model 类名不含已知关键字（如自定义 provider），provider_id 为空串，路由规则中 `providerIdIncludes` 匹配会失效（空串不匹配任何非空 includes）。
- 实际影响小：Charles 当前主要用 QwenModel，类名推断能正确返回 "qwen"。

**建议**：保留现状。推断逻辑是 Charles 的兼容层，删除会破坏历史 model 实现的路由功能。建议未来在 model 协议中统一要求 `provider_id` 属性，逐步淘汰类名推断。

### 差距 5：AgentMode 类型范围差异（3.20.3 / 3.20.26）

**Cline**：`AgentMode = "act" | "plan" | "yolo" | "zen"`（4 种模式）
- yolo 模式：自动化工具 + 无需审批（`ToolPresets.yolo` 定义）
- zen 模式：专注模式

**Charles**：`AgentMode = Literal["act", "plan"]`（2 种模式）
- 不支持 yolo / zen

**影响**：
- 路由规则中 `mode: "yolo"` 在 Charles 中永远不会匹配（Charles 的 Mode 类型不接受 "yolo"）。
- Charles 的 `resolveContextMode`（Cline runtime.ts L113-117）等价逻辑是 `get_mode` 直接返回 "act" 或 "plan"，无 yolo/zen 分支。
- 当前默认路由规则只用了 `mode: "act"`，不涉及 yolo/zen，因此无实际影响。

**建议**：不强制对齐。yolo/zen 是 Cline 的高级模式，Charles 当前场景不需要。若未来 Charles 引入 yolo 模式（如自动化流程），需同步扩展 AgentMode 类型和 preset。

---

## 四、nanobot 残留检查

针对 P3.20 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.20 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/routing.py` | **0** | 无 | 完全清理，docstring 仅引用 Cline 对标 |
| `agent/runtime.py`（`get_tools` / `_resolve_tool_routing_toggles` 段落 L445-515） | **0** | 无 | 路由集成段落无 nanobot 引用 |
| `agent/server.py`（`_create_runtime` 路由配置注入 L380-386） | **0** | 无 | provider_id / model_id 注入无 nanobot 引用 |
| `agent/types.py`（`tool_routing_rules` 字段 L558-564） | **0** | 无 | 配置字段定义无 nanobot 引用 |
| `agent/state.py`（`AgentMode` / `get_mode`） | **0** | 无 | 模式类型与查询无 nanobot 引用 |

### 4.2 残留分类

#### 注释残留（0 处）

P3.20 核心文件中**无任何 nanobot 注释残留**。`routing.py` 的 docstring 明确标注"对标 Cline model-tool-routing.ts"，`runtime.py` 的 `_resolve_tool_routing_toggles` 标注"对标 Cline resolveToolRoutingConfig"，全部为 Cline 对标，无 nanobot 引用。

#### 实现逻辑残留（0 处）

P3.20 核心文件中**未发现任何从 nanobot 直接移植的实现逻辑**：

- `ToolRoutingRule` 数据类对标 Cline `ToolRoutingRule` 接口（`routing.py` L36 注释"对标 Cline ToolRoutingRule"）。
- `DEFAULT_MODEL_TOOL_ROUTING_RULES` 对标 Cline 同名常量（`routing.py` L56 注释"对标 Cline DEFAULT_MODEL_TOOL_ROUTING_RULES"）。
- `_matches_id` 对标 Cline `matchesModelId`（`routing.py` L78 注释"对标 Cline matchesModelId"）。
- `_matches_rule` 对标 Cline `matchesRule`（`routing.py` L99 注释"对标 Cline matchesRule"）。
- `resolve_tool_routing` 对标 Cline `resolveToolRoutingConfig`（`routing.py` L114 注释"对标 Cline resolveToolRoutingConfig"）。
- `_resolve_tool_routing_toggles` 对标 Cline `resolveToolRoutingConfig` + `createBuiltinToolsList`（`runtime.py` L477 注释"对标 Cline resolveToolRoutingConfig"）。

### 4.3 P3.20 范围外但相关的 nanobot 残留

P3.20 核心文件无 nanobot 残留。`agent` 目录下其他文件的 nanobot 残留（如 `exec_tool.py` / `file_tools.py` / `web_tool.py` 等）不在 P3.20 范围内，已在前序 P3.x 报告中处理。

---

## 五、修复建议

### 建议 1：清理 `apply_tool_routing` 冗余函数 [P3 可选]

**文件**：`agent/tools/routing.py`
**位置**：L142-167
**问题**：`apply_tool_routing` 函数未被 runtime 调用，runtime.get_tools() 内联了相同的过滤逻辑。
**选项**：
- **选项 A（删除）**：移除 `apply_tool_routing` 函数，减少代码冗余。
- **选项 B（保留 + 标注）**：保留函数，在 docstring 中标注"runtime.get_tools() 内联过滤未调用此函数，供外部工具列表过滤使用"。

**理由**：当前两处过滤逻辑重复，若未来需要修改过滤规则（如增加白名单），可能遗漏其中一处。选项 B 成本更低且保留扩展性。

**优先级**：P3（不阻塞，可选清理）。

### 建议 2：不强制补齐 ToolPresets 预设系统 [P3 不修复]

**理由**：
- Charles 的 plan 模式工具禁用已由 `tool_policies` 承担，功能等价。
- Charles 当前只支持 act / plan 两种模式，preset 抽象层收益有限。
- 引入 preset 会增加配置层级（preset + routing + tool_policies 三层），与 Charles 简洁风格不符。

**保留条件**：若未来支持 yolo / zen 等更多模式，或需要按场景切换工具集（如 search-focused / minimal），可考虑引入 preset 层。

### 建议 3：不强制对齐路由输出类型 [P3 不修复]

**理由**：
- Cline 返回 `enable*` 标志、Charles 返回 `dict[ToolName, bool]`，是两种架构下的合理选择。
- Cline 需要 `enable*` 标志是因为 `createDefaultTools` 按标志决定是否实例化工具。
- Charles 不需要 `enable*` 标志是因为工具已全量实例化，直接按工具名过滤更直接。
- 强制对齐需要引入 `DefaultToolsConfig` 等价物，增加不必要的抽象层。

### 建议 4：不强制对齐路由应用时机 [P3 不修复]

**理由**：
- Cline 构建期应用路由更高效，但 mode 变化需要重建 runtime。
- Charles 运行期应用路由更动态，mode 变化即时生效，符合 Charles 的会话级 mode 切换需求。
- 16 个工具的过滤开销可忽略，性能不是问题。

### 建议 5：保留 `extract_model_info` 推断逻辑 [P0 不变]

**理由**：`extract_model_info` 的类名推断是 Charles 兼容历史 model 实现的必要兜底。删除会破坏 QwenModel 等无 `provider_id` 属性的 model 对象的路由功能。

**未来优化**：在 model 协议中统一要求 `provider_id` 属性，逐步淘汰类名推断分支。

---

## 六、验证方法建议

### 验证方法 1：默认路由规则等价性检查

对比 Cline `DEFAULT_MODEL_TOOL_ROUTING_RULES` 与 Charles `DEFAULT_MODEL_TOOL_ROUTING_RULES`，确认 2 条规则完全相同：

```powershell
# Cline 侧（model-tool-routing.ts L60-75）
# 规则 1: openai-native-use-apply-patch, mode=act, providerIdIncludes=["openai-native"], enable=[apply_patch], disable=[editor]
# 规则 2: codex-and-gpt-use-apply-patch, mode=act, modelIdIncludes=["codex","gpt"], enable=[apply_patch], disable=[editor]

# Charles 侧（routing.py L59-74）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\routing.py" -Pattern "openai-native-use-apply-patch|codex-and-gpt-use-apply-patch"
```

**预期**：两侧规则名称、mode、includes、enable/disable 工具列表完全一致。

### 验证方法 2：路由解析函数行为等价性

对比 Cline `resolveToolRoutingConfig` 与 Charles `resolve_tool_routing` 的行为，确认相同输入产出等价结果（参考 Cline 测试用例）：

```powershell
# Cline 测试用例（model-tool-routing.test.ts）
# 1. provider="openai", model="openai/gpt-5.4", mode="act" → enableApplyPatch=true, enableEditor=false
# 2. provider="openai", model="openai/gpt-5.4", mode="plan" → {} (空)
# 3. 自定义规则按顺序应用，后覆盖前
# 4. 无匹配规则 → {} (空)
# 5. provider-only 匹配

# Charles 侧验证（routing.py L108-139）
# resolve_tool_routing("openai", "openai/gpt-5.4", "act", DEFAULT_MODEL_TOOL_ROUTING_RULES)
# 应返回 {"apply_patch": True, "editor": False}
```

**预期**：Charles 返回 `{"apply_patch": True, "editor": False}`，与 Cline 的 `{enableApplyPatch: true, enableEditor: false}` 语义等价。

### 验证方法 3：路由集成点检查

确认 Charles runtime 在 `get_tools()` 中正确调用路由过滤：

```powershell
# 确认 get_tools 调用 _resolve_tool_routing_toggles
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "_resolve_tool_routing_toggles|resolve_tool_routing"
# 确认 _resolve_tool_routing_toggles 从 routing 模块导入
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "from agent.tools.routing import"
```

**预期**：`get_tools()` L466 调用 `_resolve_tool_routing_toggles()`，`_resolve_tool_routing_toggles` L484-488 从 `agent.tools.routing` 导入 `DEFAULT_MODEL_TOOL_ROUTING_RULES` / `extract_model_info` / `resolve_tool_routing`。

### 验证方法 4：mode 读取链路检查

确认 Charles 路由解析时正确读取当前 mode：

```powershell
# 确认 _resolve_tool_routing_toggles 从 session state 读取 mode
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "get_mode|session_id.*mode"
```

**预期**：`_resolve_tool_routing_toggles` L508-513 调用 `agent.state.get_mode(session_id)` 读取当前 mode，无 session_id 时默认 "act"。

### 验证方法 5：plan 模式工具禁用检查

确认 Charles plan 模式下 editor / apply_patch / file_write 被禁用：

```powershell
# 确认 server.py 在 plan 模式下设置 tool_policies
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern 'current_mode == "plan"|enabled.*False'
```

**预期**：`server.py` L363-369 在 `current_mode == "plan"` 时设置 editor / apply_patch / file_write 的 `enabled: False`。

### 验证方法 6：nanobot 残留扫描

```powershell
# P3.20 核心文件扫描（应全部为 0）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\routing.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\types.py" -Pattern "nanobot" -CaseSensitive:$false
```

**预期**：全部 0 匹配。

### 验证方法 7：`apply_tool_routing` 调用链检查

确认 `apply_tool_routing` 是否被 runtime 调用：

```powershell
# 搜索 apply_tool_routing 的所有引用
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent" -Pattern "apply_tool_routing" -Recurse
```

**预期**：仅在 `routing.py` L142 定义处出现，runtime.py 中无调用（证实为冗余函数）。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L4-32 | `ToolRoutingRule` 接口定义 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L34-58 | `TOOL_NAME_TO_FLAG` 映射表（9 个工具） |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L60-75 | `DEFAULT_MODEL_TOOL_ROUTING_RULES` 默认规则（2 条） |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L77-88 | `matchesModelId` 子串匹配函数 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L90-103 | `matchesRule` 规则匹配函数 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L105-134 | `resolveToolRoutingConfig` 路由解析函数 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.test.ts` | L1-86 | 5 个测试用例（act/plan/顺序/无匹配/provider-only） |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L29-84 | `BASE_TOOL_CATALOG` 静态目录 |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L135-160 | `resolvePresetFlags` preset + routing 融合 |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L162-183 | `isEntryEnabledByDefault` 可用性解析（含 editor 特殊处理） |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L20-109 | `ToolPresets` 5 套预设（act/plan/search/minimal/yolo） |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L116-126 | `resolveToolPresetName` 模式→预设名解析 |
| `sdk/packages/core/src/extensions/tools/types.ts` | L226-235 | `DefaultToolName` 联合类型（9 个工具名） |
| `sdk/packages/core/src/extensions/tools/types.ts` | L240-280 | `DefaultToolsConfig` enable* 标志接口 |
| `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` | L126-161 | `createBuiltinToolsList` 路由应用时机 |
| `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` | L131-141 | preset + toolRoutingConfig 融合 |
| `sdk/packages/core/src/types/config.ts` | L278 | `toolRoutingRules?: ToolRoutingRule[]` 配置字段 |
| `sdk/packages/shared/src/session/runtime-config.ts` | L3 | `AgentMode = "act" \| "plan" \| "yolo" \| "zen"` |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/routing.py` | L30-31 | `ToolName = str` / `Mode = Literal["act", "plan"]` 类型别名 |
| `agent/tools/routing.py` | L34-53 | `ToolRoutingRule` 数据类定义 |
| `agent/tools/routing.py` | L56-74 | `DEFAULT_MODEL_TOOL_ROUTING_RULES` 默认规则（2 条，与 Cline 一致） |
| `agent/tools/routing.py` | L77-90 | `_matches_id` 子串匹配函数 |
| `agent/tools/routing.py` | L93-105 | `_matches_rule` 规则匹配函数 |
| `agent/tools/routing.py` | L108-139 | `resolve_tool_routing` 路由解析函数 |
| `agent/tools/routing.py` | L142-167 | `apply_tool_routing` 工具列表过滤函数（**未被 runtime 调用**） |
| `agent/tools/routing.py` | L170-203 | `extract_model_info` 模型信息提取函数（Charles 独有） |
| `agent/runtime.py` | L445-472 | `get_tools()` 序列化 + 路由过滤 |
| `agent/runtime.py` | L474-515 | `_resolve_tool_routing_toggles` 路由开关解析 |
| `agent/runtime.py` | L484-488 | 从 `agent.tools.routing` 导入三个函数 |
| `agent/runtime.py` | L497-504 | provider_id / model_id 显式配置优先 + 推断兜底 |
| `agent/runtime.py` | L506-513 | 从 `agent.state.get_mode` 读取当前 mode |
| `agent/runtime.py` | L851 | `_generate_assistant_message` 中调用 `get_tools()`（每轮调用） |
| `agent/types.py` | L558-564 | `provider_id` / `model_id` / `tool_routing_rules` 配置字段 |
| `agent/server.py` | L358-377 | plan 模式 tool_policies 设置（editor/apply_patch/file_write 禁用） |
| `agent/server.py` | L381-386 | provider_id / model_id 环境变量注入 |
| `agent/state.py` | L58 | `AgentMode = Literal["act", "plan"]` 类型定义 |
| `agent/state.py` | L363-365 | `get_mode` 会话模式查询函数 |
| `agent/tools/__init__.py` | L48-112 | `create_default_tools` 全量装配（无 enable* 开关） |

---

## 八、结论

P3.20 模型工具路由对比的核心结论：

1. **核心算法完全对齐**：规则数据结构（`ToolRoutingRule`）、默认规则（2 条完全相同）、子串匹配逻辑、规则顺序应用、mode 过滤、空规则返回空字典等核心逻辑在两侧一一对应。Charles `routing.py` 的每个函数都明确标注了对标 Cline 的对应函数，实现逻辑无偏差。

2. **架构差异是设计选择，非缺陷**：
   - Cline 路由输出 `enable*` 标志 → 构建期融合 preset → 按标志实例化工具（装配期过滤）。
   - Charles 路由输出 `dict[ToolName, bool]` → 运行期过滤 definition 列表（序列化期过滤）。
   - 两种方式功能等价，Charles 的方式更动态（mode 变化即时生效），Cline 的方式更高效（一次计算）。

3. **plan/act 模式工具集实现路径分离**（已知差异，建议不修复）：
   - Cline 通过 `ToolPresets` 预设系统（5 套预设）+ 路由 `mode: "act"` 限制实现 plan 模式工具禁用。
   - Charles 无 preset 系统，plan 模式工具禁用由 `server.py` 的 `tool_policies`（`enabled: False`）实现，与路由系统分离。
   - 路由系统在两侧都只负责**模型维度**（openai-native / codex / gpt），**模式维度**由不同机制承担。

4. **Charles 的额外函数**：
   - `extract_model_info`：Charles 独有的模型信息推断逻辑，是兼容历史 model 实现的必要兜底（建议保留）。
   - `apply_tool_routing`：未被 runtime 调用的冗余函数（建议保留并标注，或删除）。

5. **AgentMode 类型范围差异**：Cline 支持 4 种模式（act/plan/yolo/zen），Charles 支持 2 种（act/plan）。当前默认路由规则只用 `mode: "act"`，无实际影响。

6. **nanobot 残留**：P3.20 核心文件（`routing.py` / `runtime.py` 路由段落 / `server.py` 路由配置 / `types.py` 路由字段 / `state.py` 模式定义）**0 处 nanobot 残留**，已完全清理。

7. **Cline 的 editor 特殊处理**：Cline 在 `isEntryEnabledByDefault` 中对 editor 有 catalog 级特殊逻辑（`enableEditor === true || enableApplyPatch === true` 都算 editor 启用），Charles 无此处理（editor / apply_patch 独立过滤）。这是因为 Cline 的 catalog 层将 editor / apply_patch 视为同一工具槽位的两种形态，Charles 无 catalog 层因此不需要。

**整体一致性等级**：**高**。P3.20 范围内无需阻塞性修复，核心路由算法完全对齐。建议 1（`apply_tool_routing` 冗余处理）为 P3 级别可选清理，其余建议均为"不修复"（设计差异保留现状）。
