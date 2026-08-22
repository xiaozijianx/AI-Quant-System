# Phase 3.1 工具基础设施对比（createTool 工厂 vs BaseTool 类）

> 对比范围：Cline `createTool` 工厂 + `ToolRuntime`（实为 ToolCatalog）+ `AgentTool` 接口 与 Charles `BaseTool` 抽象类 + `create_default_tools` + `AgentRuntime.register_tool` 的实现范式差异。
>
> Cline 源码：
> - `sdk/packages/shared/src/tools/create.ts`（createTool 工厂）
> - `sdk/packages/shared/src/agent.ts` L146-186（AgentToolDefinition / AgentToolContext / AgentTool 接口）
> - `sdk/packages/shared/src/parse/zod.ts`（validateWithZod / zodToJsonSchema）
> - `sdk/packages/core/src/extensions/tools/runtime.ts`（ToolCatalog，工具目录与可用性解析）
> - `sdk/packages/core/src/extensions/tools/definitions.ts`（createDefaultTools + createReadFilesTool 等工厂）
> - `sdk/packages/core/src/extensions/tools/index.ts`（createBuiltinTools 入口）
>
> Charles 源码：
> - `agent/tools/base.py`（BaseTool 抽象类）
> - `agent/tools/__init__.py`（create_default_tools）
> - `agent/types.py` L150-245（ToolLifecycle / AgentToolDefinition / AgentToolResult / AgentToolContext / AgentTool Protocol）
> - `agent/runtime.py` L364-472（register_tool / get_tools / _resolve_tool_routing_toggles）
> - `agent/server.py` L393-405（工具注册调用点）

---

## 一、执行摘要

Cline 与 Charles 在工具基础设施层面采用了**两种不同的设计范式**，但最终对 LLM 暴露的 `AgentToolDefinition` 形态基本一致：

1. **Cline 采用函数式工厂模式**：`createTool(config)` 返回一个普通对象字面量（`AgentTool<TInput, TOutput>`），每个具体工具是一个 `createXxxTool(executor, config)` 工厂函数，内部调用 `createTool(...)` 组装对象。工具无类、无 `this`，状态通过闭包隔离，executor 通过工厂参数依赖注入。

2. **Charles 采用 OOP 继承模式**：`BaseTool` 是抽象基类，子类必须实现 `name` / `description` / `input_schema` 抽象属性和 `_execute()` 抽象方法；`execute()` 是模板方法，固定流程为"参数校验 → 调用 `_execute()` → 异常捕获"。工具状态通过实例字段隔离，executor 直接嵌入工具类内部（无依赖注入）。

3. **关键差异点**：
   - Cline 的 `createTool` 内置 `normalizeToolInputSchema` 强制 `type: "object"` 并校验 `oneOf/anyOf/allOf` 分支，Charles 无此规范化层。
   - Cline 默认 `timeoutMs=30000 / retryable=true / maxRetries=3`，Charles 默认 `timeout_ms=None / retryable=False / max_retries=0`，**Charles 默认更保守**。
   - Cline 的 `runtime.ts` 实际是**工具目录（ToolCatalog）+ 可用性解析层**，并非工具运行时；Charles 的等价职能分散在 `runtime.py` 的 `register_tool/get_tools`（注册与序列化）和 `tools/__init__.py` 的 `create_default_tools`（装配）中，**Charles 缺少独立的 ToolCatalog 层**。
   - Cline 通过 `enable*` 开关在 `createDefaultTools` 内部按需装配；Charles 的 `create_default_tools` 无开关、全部实例化，过滤逻辑延迟到 `get_tools()` 的 routing 层。

4. **nanobot 残留**：P3.1 核心文件 `base.py` 已清理完毕（0 处残留）；`__init__.py` L2 仍有 1 处 docstring 残留（"对标 Cline extensions/tools 和 nanobot agent/tools"），属注释残留，不影响实现逻辑。其他工具文件（`exec_tool.py` / `file_tools.py` / `web_tool.py`）的 nanobot 残留不在 P3.1 范围内，留待 P3.x 对应小阶段处理。

5. **一致性总体评估**：**中高**。两种范式在功能上等价（都能产出 `AgentToolDefinition` 供 LLM 调用、都能执行工具并返回 `AgentToolResult`），字段命名差异源于语言习惯（camelCase vs snake_case），核心差距在于 Charles 缺少 schema 规范化层和独立的 ToolCatalog 抽象。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.1.1 | 工具实现范式 | `createTool()` 工厂返回对象字面量，函数式闭包 | `BaseTool` 抽象类，子类继承实现 `_execute()` | 中（设计差异） | 两种范式都有效，非缺陷 |
| 3.1.2 | 工具字段命名 | camelCase：`inputSchema` / `timeoutMs` / `maxRetries` | snake_case：`input_schema` / `timeout_ms` / `max_retries` | 高（语言习惯） | Python PEP 8 与 TS 规范各自正确 |
| 3.1.3 | inputSchema 类型系统 | Zod schema（`z.ZodTypeAny`），经 `zodToJsonSchema` 转为 JSON Schema | 直接定义 JSON Schema dict | 中 | Charles 跳过 Zod 中间层，直接产出 JSON Schema |
| 3.1.4 | inputSchema 运行时校验 | `validateWithZod(schema, input)`（Zod `safeParse`，execute 内调用） | `jsonschema.Draft7Validator`（`_validate_input`，execute 模板方法调用） | 高 | 校验库不同但语义等价；Charles 错误信息含字段路径 |
| 3.1.5 | inputSchema 规范化 | `normalizeToolInputSchema`：剥离 `$schema`、强制 `type:"object"`、校验 `oneOf/anyOf/allOf` 分支 | 无规范化层，直接使用 dict | 低 | **Charles 缺失**，非 object 顶层 schema 不会被拦截 |
| 3.1.6 | 工具描述动态生成 | `createTool` 接收静态 `description` 字符串 | `@property description` 可动态返回（SkillTool 用 `_build_description()`） | 高（Charles 更灵活） | Charles 的 property 机制天然支持动态 |
| 3.1.7 | 工具实例化时机 | 工厂调用时（`createReadFilesTool(executor, config)`） | 装配时 `new`（`RunCommandsTool(working_dir=...)`） | 高 | 两者都在装配阶段创建工具对象 |
| 3.1.8 | 工具状态隔离 | 闭包隔离（每次工厂调用产生新闭包） | 实例字段隔离（每个 BaseTool 实例独立 `self._xxx`） | 高 | 语义等价 |
| 3.1.9 | 工具复用策略 | 工厂每次调用创建新对象；`createDefaultTools` 一次性产出数组 | `create_default_tools` 一次性实例化，单例注册到 runtime | 高 | 实际都是"装配一次、运行期复用" |
| 3.1.10 | 默认 timeout | `timeoutMs ?? 30_000`（30 秒） | `timeout_ms = None`（由 AgentRuntime 控制） | 中 | Charles 默认不设超时，依赖 runtime 全局控制 |
| 3.1.11 | 默认 retryable | `retryable ?? true` | `retryable = False` | 低 | **Charles 默认不重试**，更保守 |
| 3.1.12 | 默认 maxRetries | `maxRetries ?? 3` | `max_retries = 0` | 低 | **Charles 默认 0 次**，与 retryable=False 一致 |
| 3.1.13 | 工具注册方式 | `AgentRuntimeConfig.tools` 数组传入构造函数 | `runtime.register_tool(tool)` 逐个调用 | 中（接口差异） | Charles 支持运行期动态注册（如 SkillsTool 后注册） |
| 3.1.14 | 工具定义序列化 | 工厂返回的 `AgentTool` 对象**本身**即定义 + 执行体 | `to_definition()` 方法将 BaseTool 转为 `AgentToolDefinition` | 高 | Charles 多一步转换，但 `get_tools()` 已封装 |
| 3.1.15 | 依赖注入 | executor 作为工厂参数注入（`ShellExecutor` / `FileReadExecutor` 等） | 工具类内部直接实现执行逻辑，无注入 | 低 | **Charles 无 DI**，工具与执行器耦合 |
| 3.1.16 | 工具目录（ToolCatalog） | `runtime.ts` 的 `BASE_TOOL_CATALOG` + `getCoreBuiltinToolCatalog(context)` | 无独立 catalog，`create_default_tools` 硬编码列表 | 低 | **Charles 缺 catalog 抽象层** |
| 3.1.17 | 工具可用性解析 | `resolveCoreSelectedToolIds` + `getCoreHeadlessToolNames` + presets + routing | `get_tools()` 内联 `_resolve_tool_routing_toggles()` 过滤 | 中 | Charles 有 routing 但缺 preset/catalog 层 |
| 3.1.18 | 工具启用开关 | `createDefaultTools` 的 `enableReadFiles` / `enableBash` 等参数 | `create_default_tools` 无开关，全部实例化 | 低 | **Charles 无按需装配**，全量注册后靠 routing 过滤 |
| 3.1.19 | abort 信号检查 | `context.signal`（AbortSignal），runtime 在 execute 外包裹 | `context.abort_signal`（asyncio.Event）+ `_check_aborted()` 辅助方法 | 高 | 已对齐（P2.6 验证） |
| 3.1.20 | 异常处理位置 | execute 内部抛出，由 runtime 的 `executePreparedTool` 捕获 | `execute()` 模板方法内 `try/except` 捕获并返回 `is_error=True` | 中（范式差异） | Charles 集中在基类处理，Cline 分散在 runtime |
| 3.1.21 | requires_approval | `toolPolicies` 配置（外部策略驱动） | `BaseTool.requires_approval` 属性（工具自声明） | 中 | Charles 工具自带审批标记，Cline 由外部 policy 决定 |
| 3.1.22 | read_only / concurrencySafe | 无显式字段（由 toolPolicies 控制） | `BaseTool.read_only` 属性 | 中 | Charles 显式声明只读性 |
| 3.1.23 | ToolRuntime 等价物 | `runtime.ts`（实为 ToolCatalog，非运行时） | `runtime.py` 的 `register_tool/get_tools` + `tools/__init__.py` | 中 | 职责拆分不同，功能可对应 |
| 3.1.24 | 工厂 vs 类的代码量 | 每个工具约 30-80 行工厂函数 | 每个工具约 80-200 行类定义 | — | Charles 类风格代码量略多但可读性好 |

**一致性总评**：24 项中，高一致性 11 项、中一致性 9 项、低一致性 4 项（3.1.5 / 3.1.15 / 3.1.16 / 3.1.18）。低一致性项均为 Charles 缺失的抽象层，不影响现有功能但影响可扩展性。

---

## 三、重点差距详细说明

### 差距 1：inputSchema 规范化层缺失（3.1.5）

**Cline 实现**（`create.ts` L5-79）：

`createTool` 工厂在返回对象前，强制调用 `normalizeToolInputSchema(inputSchema)`，执行三项规范化：

1. **剥离 `$schema` 元键**：Zod v4 的 `z.toJSONSchema()` 会输出 `$schema` 字段，可能干扰严格校验器，工厂自动剥离。
2. **强制 `type: "object"`**：若 schema 有 `properties` / `required` / `additionalProperties` 但缺少 `type`，自动补 `type: "object"`。
3. **校验 `oneOf/anyOf/allOf` 分支**：遍历联合分支，确保每个分支都声明 `type: "object"`；`allOf` 要求至少一个分支声明 `type: "object"`，否则**抛出注册时错误**（fail loudly），让开发者在工具定义阶段就发现问题，而非等到 LLM 推理时才报错。

**Charles 实现**（`base.py`）：

`BaseTool` 直接使用子类返回的 `input_schema` dict，无任何规范化。`_validate_input()` 使用 `jsonschema.Draft7Validator` 按 schema 校验输入，但**不校验 schema 本身的合法性**。

**影响**：
- 若 Charles 工具子类返回了一个顶层 `type` 不是 `object` 的 schema（如 `type: "string"`），LLM provider 会拒绝该工具定义，但 Charles 不会在注册时提前发现。
- 实际影响较小：现有 20 个工具的 `input_schema` 都是规范的 object schema，但缺少防御层。

**建议**：不强制补齐。Charles 工具数量固定、由开发者人工保证 schema 规范，且 Python 无 Zod 等价物，引入规范化层收益有限。若未来开放第三方工具注册，可考虑在 `register_tool` 中加 schema 合法性检查。

### 差距 2：依赖注入缺失（3.1.15）

**Cline 实现**（`definitions.ts` L244-280）：

每个工具工厂接收 executor 作为参数：
```typescript
export function createReadFilesTool(
    executor: FileReadExecutor,
    config: Pick<DefaultToolsConfig, "fileReadTimeoutMs"> = {},
): AgentTool<ReadFilesInput, ToolOperationResult[]> {
    // ...
    return createTool({
        execute: async (input, context) => {
            const output = await executor(...);
            // ...
        }
    });
}
```

`createDefaultExecutors(options)` 集中创建所有 executor（`createDefaultShellExecutor` / `createFileReadExecutor` 等），`createBuiltinTools`（index.ts L180-213）负责把 executor 注入到各工具工厂。executor 与工具定义解耦，同一工具可配不同 executor（如测试用 mock executor）。

**Charles 实现**（`base.py` + 各工具文件）：

`BaseTool` 子类在 `_execute()` 内部直接调用具体实现，无 executor 抽象。例如 `RunCommandsTool` 内部直接调用 `asyncio.create_subprocess_shell`，`ReadFilesTool` 内部直接调用 `open()` / `pathlib.Path.read_text()`。

**影响**：
- Charles 工具**无法在不修改工具类的情况下替换执行后端**。例如要让 `RunCommandsTool` 在沙箱中执行命令，必须修改工具类本身。
- Cline 的 executor 模式允许 host（如 VS Code 扩展）注入自定义 executor 复用工具定义。
- Charles 当前是单机 CLI 场景，执行后端固定，DI 缺失影响不大。

**建议**：不强制补齐。Charles 的工具执行逻辑与具体场景强绑定，引入 DI 会增加复杂度且无实际收益。若未来支持多 host（如 Web 端），可考虑引入 executor 抽象。

### 差距 3：工具目录（ToolCatalog）抽象层缺失（3.1.16 / 3.1.17 / 3.1.18）

**Cline 实现**（`runtime.ts`）：

`runtime.ts` 虽然名为 "runtime"，实则是**工具目录与可用性解析层**，不持有工具实例、不执行工具。核心 API：

- `BASE_TOOL_CATALOG`：静态数组，每项含 `id` / `description` / `headlessToolNames`，是工具的元数据登记表。
- `getCoreBuiltinToolCatalog(context)`：根据 `mode` / `providerId` / `modelId` / `disabledToolIds` 计算每个工具的 `defaultEnabled`，融合 preset + routing 规则。
- `resolveCoreSelectedToolIds({ enabled, allowlist, availabilityContext })`：根据 allowlist 解析最终选中的工具 ID 集合，对未知 ID **抛错**。
- `getCoreHeadlessToolNames(selectedToolIds, context)`：将工具 ID 映射为 headless 工具名（用于 ACP / 无头模式）。

`definitions.ts` 的 `createDefaultTools(options)` 根据 `enableReadFiles` / `enableBash` 等开关**按需调用工厂**创建工具实例。

**Charles 实现**：

- `tools/__init__.py` 的 `create_default_tools(working_dir, session_id)` **无开关**，一次性实例化全部 16 个工具（RunCommandsTool / ReadFilesTool / FileWriteTool / WebSearchTool / TodoWriteTool / EditorTool / ApplyPatchTool / SearchCodebaseTool / FetchWebContentTool / AskQuestionTool / ListFilesTool / SubmitAndExitTool / UseMcpToolTool / AccessMcpResourceTool / SwitchToActModeTool / SwitchToPlanModeTool）。
- `runtime.py` 的 `get_tools()` 在返回定义前调用 `_resolve_tool_routing_toggles()` 按 provider/model/mode 过滤，等价于 Cline 的 `resolveToolRoutingConfig`。
- 缺少独立的 catalog 层：工具 ID 登记表、preset 预设、`defaultEnabled` 计算等概念在 Charles 中不存在。

**影响**：
- Charles 无法表达"某工具在 plan 模式下默认禁用"这类 preset 规则（只能靠 routing 过滤）。
- Charles 无法在装配阶段跳过不需要的工具（全部实例化后再过滤，轻微浪费内存，但 16 个工具开销可忽略）。
- Charles 的 `SwitchToActModeTool` / `SwitchToPlanModeTool` 通过 `get_mode(sid)` 在装配时决定是否注册，是 preset 的简化等价物，但逻辑硬编码在 `create_default_tools` 内。

**建议**：不强制补齐。Charles 的工具集固定、场景单一，catalog 抽象层收益有限。当前 routing 过滤 + 装配时 mode 判断已能满足需求。若未来支持插件化工具或多种 agent 模式（plan/act/yolo），可考虑引入 catalog 层。

### 差距 4：默认 timeout / retry 策略差异（3.1.10 / 3.1.11 / 3.1.12）

| 字段 | Cline 默认 | Charles 默认 | 影响 |
|------|-----------|-------------|------|
| timeout | 30000ms | None（runtime 控制） | Charles 工具默认无超时，长任务可能阻塞 |
| retryable | true | False | Charles 工具默认不重试，失败即返回 |
| maxRetries | 3 | 0 | 与 retryable=False 一致 |

**分析**：
- Cline 的默认值偏"乐观"（重试 3 次、30 秒超时），适合网络型工具（如 `fetch_web_content`）。
- Charles 的默认值偏"悲观"（不重试、无超时），适合本地 IO 型工具（如 `read_files` / `editor`）。
- Charles 的 `run_commands` 工具单独硬编码了超时（命令级超时），其他工具确实不需要重试。
- 两种默认值策略都合理，无需强制对齐。

**建议**：不强制补齐。Charles 的保守默认值符合本地 CLI 场景。若未来引入网络型工具（如远程 API 调用），可在该工具子类覆盖 `retryable=True` / `max_retries=3`。

### 差距 5：工具注册接口差异（3.1.13）

**Cline**：`AgentRuntimeConfig.tools` 是构造参数，runtime 在初始化时一次性接收工具数组（`readonly AgentTool<any, any>[]`）。运行期不提供 `registerTool` 方法，工具集在 runtime 创建时固定。

**Charles**：`AgentRuntime.register_tool(tool)` 是公开方法，支持运行期动态注册。`server.py` L393-405 在 runtime 创建后逐个调用 `register_tool` 注册默认工具，L405 额外注册 `SkillsTool`，`skills/registry.py` L111 在技能加载后动态注册 `skill_tool`，`tools/todo_write.py` L42 也支持动态注册。

**分析**：
- Charles 的动态注册能力**强于 Cline**，支持技能工具的延迟注册（技能配置加载完成后才注册 SkillsTool）。
- Cline 的静态数组模式更函数式、更易推理，但需要提前组装好完整工具集。

**建议**：保留 Charles 现状。动态注册是 Charles 技能系统的实际需求，无需退化为静态数组。

---

## 四、nanobot 残留检查

针对 P3.1 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.1 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/base.py` | **0** | 无 | 已清理完毕（`AGENT_FINAL_ALIGNMENT_PLAN.md` F-base 任务已完成） |
| `agent/tools/__init__.py` | **1** | 注释残留 | L2 docstring：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools` |
| `agent/types.py` | **0** | 无 | 工具类型定义无 nanobot 引用 |
| `agent/runtime.py`（register_tool / get_tools 段落） | **0** | 无 | 工具注册与序列化逻辑无 nanobot 引用 |

### 4.2 残留分类

#### 注释残留（1 处）

**位置**：`agent/tools/__init__.py` L2
```python
"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools
```

**性质**：docstring 中的历史溯源说明，标注 Charles 工具系统同时对标了 Cline extensions/tools 和历史 nanobot agent/tools。不影响运行时行为，不影响工具功能。

**处理建议**：将 L2 改为 `"""工具系统 — 对标 Cline extensions/tools`，移除 `和 nanobot agent/tools` 段落。属于 P2 级别清理，不阻塞 P3.1 对比结论。

#### 实现逻辑残留（0 处）

P3.1 核心文件（`base.py` / `__init__.py` 的 `create_default_tools` / `types.py` 的工具类型 / `runtime.py` 的工具注册）中**未发现任何从 nanobot 直接移植的实现逻辑**：

- `BaseTool` 类设计对标 Cline `AgentTool` 接口（`base.py` L17-20 明确标注"对标 Cline: 接口定义: sdk/packages/shared/src/agent.ts L177-186"）。
- `_validate_input()` 对标 Cline `validateWithZod`（`base.py` L213 标注"对标 Cline validateWithZod"）。
- `_check_aborted()` 对标 Cline `throwIfAborted`（`base.py` L141 标注）。
- `create_default_tools` 对标 Cline `initialize()` 中的工具注册（`__init__.py` L52 标注）。
- `register_tool` 对标 Cline `AgentRuntime tools Map.set`（`runtime.py` L365 标注）。

### 4.3 P3.1 范围外但相关的 nanobot 残留

以下文件有 nanobot 残留，但属于 P3.x 后续小阶段的对比范围，不在 P3.1 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|---------------|-----------|
| `agent/tools/exec_tool.py` | 12 | P3.x（exec_tool 专项，注意该工具已废弃） |
| `agent/tools/file_tools.py` | 7 | P3.x（FileWriteTool 专项） |
| `agent/tools/web_tool.py` | 7 | P3.x（WebSearchTool 专项） |

这些残留全部为 docstring / 行内注释（如"对标 nanobot ShellTool"、"对标 nanobot filesystem.py L150-176"），属历史溯源标注，不影响工具基础设施层的对比结论。

---

## 五、修复建议

### 建议 1：清理 `__init__.py` L2 的 nanobot 注释残留 [P2]

**文件**：`agent/tools/__init__.py`
**位置**：L2
**修改**：
- 当前：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools`
- 建议：`"""工具系统 — 对标 Cline extensions/tools`

**理由**：统一为"对标 Cline"溯源风格，与 `base.py`（已清理）保持一致。不影响功能。

### 建议 2：不强制补齐 inputSchema 规范化层 [P3 不修复]

**理由**：
- Charles 工具数量固定（16 个），由开发者人工保证 schema 规范。
- Python 无 Zod 等价物，引入规范化层需手写 JSON Schema 合法性检查，收益有限。
- 现有工具的 `input_schema` 均为规范的 object schema，未触发过相关问题。

**保留条件**：若未来开放第三方工具插件注册，应在 `register_tool` 中加 schema 合法性校验（顶层 `type` 必须为 `object` 或含 `properties`）。

### 建议 3：不强制补齐 ToolCatalog 抽象层 [P3 不修复]

**理由**：
- Charles 当前场景（单机 CLI、固定工具集）不需要 catalog 层。
- `create_default_tools` 的硬编码列表 + `get_tools()` 的 routing 过滤已能满足需求。
- 引入 catalog 层会增加抽象层级，与 Charles 简洁风格不符。

**保留条件**：若未来支持多 agent 模式（plan/act/yolo 各自有不同工具集）或插件化工具，可考虑引入 catalog 层。

### 建议 4：不强制补齐 executor 依赖注入 [P3 不修复]

**理由**：
- Charles 工具与执行逻辑耦合在单文件内，代码直观、易调试。
- 单机 CLI 场景执行后端固定，无多 host 复用需求。
- 引入 DI 会增加工厂函数层级，与 Charles OOP 风格不符。

### 建议 5：保留动态注册能力 [P0 不变]

**理由**：Charles 的 `register_tool` 动态注册是技能系统（SkillsTool 延迟注册）的实际需求，**不应退化为 Cline 的静态数组模式**。这是 Charles 相对 Cline 的功能增强，应予保留。

---

## 六、验证方法建议

### 验证方法 1：工具字段映射检查

对比 Cline `createTool` 返回对象的字段与 Charles `BaseTool` 属性，确认字段一一对应：

```powershell
# Cline 侧（create.ts L120-129）
# 字段：name / description / inputSchema / lifecycle / timeoutMs / retryable / maxRetries / execute

# Charles 侧（base.py L52-103）
# 属性：name / description / input_schema / lifecycle / timeout_ms / retryable / max_retries / execute / read_only / requires_approval
```

**验证命令**：
```powershell
# 确认 Cline createTool 输出的 8 个字段在 Charles BaseTool 中都有对应
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\base.py" -Pattern "def (name|description|input_schema|lifecycle|timeout_ms|retryable|max_retries|execute)"
```

### 验证方法 2：工具定义序列化等价性

确认 Charles `BaseTool.to_definition()` 产出的 `AgentToolDefinition` 与 Cline `createTool` 返回对象经 `toJSONSchema` 后的形态一致：

```powershell
# 检查 AgentToolDefinition 的 4 个字段（name / description / input_schema / lifecycle）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\base.py" -Pattern "to_definition|AgentToolDefinition"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\types.py" -Pattern "class AgentToolDefinition"
```

### 验证方法 3：工具注册流程检查

确认 Charles 工具注册流程与 Cline 等价（装配 → 注册 → 序列化 → LLM 请求）：

```powershell
# 确认 server.py 调用 create_default_tools + register_tool
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "create_default_tools|register_tool"
# 确认 runtime.py 的 get_tools 调用 to_definition
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "to_definition|get_tools"
```

### 验证方法 4：nanobot 残留扫描

```powershell
# P3.1 核心文件扫描（应仅 __init__.py L2 有 1 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\base.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\__init__.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\types.py" -Pattern "nanobot" -CaseSensitive:$false
```

### 验证方法 5：默认值差异回归测试

构造一个不覆盖 `timeout_ms` / `retryable` / `max_retries` 的测试工具子类，验证 Charles 默认值与 Cline 默认值的差异不会导致 runtime 行为异常：

```python
# 伪代码示意（不要求实际编写）
class DummyTool(BaseTool):
    @property
    def name(self): return "dummy"
    @property
    def description(self): return "test"
    @property
    def input_schema(self): return {"type": "object", "properties": {}}
    async def _execute(self, input, context):
        return AgentToolResult(output="ok")

t = DummyTool()
assert t.timeout_ms is None      # vs Cline 30000
assert t.retryable is False      # vs Cline true
assert t.max_retries == 0        # vs Cline 3
```

### 验证方法 6：schema 规范化层缺失影响评估

构造一个顶层 `type` 非 `object` 的 schema，确认 Charles 不会在注册时拦截（与 Cline 行为不同）：

```python
# 伪代码示意（不要求实际编写）
class BadSchemaTool(BaseTool):
    @property
    def input_schema(self):
        return {"type": "string"}  # 顶层非 object
    # ...

# Charles: register_tool 不会报错，但 LLM provider 会拒绝该工具定义
# Cline: createTool 在 normalizeToolInputSchema 阶段就会抛错
```

**预期**：Charles 不拦截（已知差异，建议 2 决定不修复）。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/shared/src/tools/create.ts` | L5-79 | `normalizeToolInputSchema` 规范化函数 |
| `sdk/packages/shared/src/tools/create.ts` | L81-129 | `createTool` 工厂实现（两个重载 + 实现） |
| `sdk/packages/shared/src/agent.ts` | L146-156 | `AgentToolDefinition` 接口 |
| `sdk/packages/shared/src/agent.ts` | L158-162 | `AgentToolResult` 接口 |
| `sdk/packages/shared/src/agent.ts` | L164-175 | `AgentToolContext` 接口 |
| `sdk/packages/shared/src/agent.ts` | L177-186 | `AgentTool` 接口（含 timeoutMs / retryable / maxRetries） |
| `sdk/packages/shared/src/parse/zod.ts` | L13-19 | `validateWithZod` 实现 |
| `sdk/packages/shared/src/parse/zod.ts` | L21-23 | `zodToJsonSchema` 实现 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L244-280 | `createReadFilesTool` 工厂示例 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L871-910 | `createDefaultTools` 聚合工厂 |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L29-84 | `BASE_TOOL_CATALOG` 静态目录 |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L206-218 | `getCoreBuiltinToolCatalog` API |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L220-245 | `resolveCoreSelectedToolIds` API |
| `sdk/packages/core/src/extensions/tools/index.ts` | L180-213 | `createBuiltinTools` 便捷入口（executor 注入） |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/base.py` | L36-103 | `BaseTool` 抽象基类定义 + 抽象属性 + 默认值 |
| `agent/tools/base.py` | L105-138 | `execute()` 模板方法（校验 + 异常捕获） |
| `agent/tools/base.py` | L161-176 | `_execute()` 抽象方法 |
| `agent/tools/base.py` | L178-185 | `to_definition()` 序列化方法 |
| `agent/tools/base.py` | L212-275 | `_validate_input()` jsonschema 校验 |
| `agent/tools/base.py` | L140-159 | `_check_aborted()` 中止检查辅助 |
| `agent/tools/__init__.py` | L48-112 | `create_default_tools` 装配函数 |
| `agent/types.py` | L154-161 | `ToolLifecycle` dataclass |
| `agent/types.py` | L164-173 | `AgentToolDefinition` dataclass |
| `agent/types.py` | L176-184 | `AgentToolResult` dataclass |
| `agent/types.py` | L187-211 | `AgentToolContext` dataclass |
| `agent/types.py` | L214-245 | `AgentTool` Protocol |
| `agent/runtime.py` | L364-366 | `register_tool(tool)` 注册方法 |
| `agent/runtime.py` | L445-472 | `get_tools()` 序列化 + routing 过滤 |
| `agent/runtime.py` | L474-515 | `_resolve_tool_routing_toggles()` routing 解析 |
| `agent/server.py` | L393-405 | 工具注册调用点 |

---

## 八、结论

P3.1 工具基础设施对比的核心结论：

1. **范式差异是设计选择，非缺陷**：Cline 的函数式工厂 vs Charles 的 OOP 继承，两种范式都能正确产出 `AgentToolDefinition` 并执行工具，选择哪种取决于语言习惯（TS 偏函数式、Python 偏 OOP）和团队偏好。

2. **核心功能已对齐**：工具定义、工具注册、工具序列化、参数校验、中止检查、异常处理等核心功能在两侧都有对应实现，且 Charles 的 `BaseTool` 明确标注了对标 Cline `AgentTool` 接口。

3. **Charles 缺少三个抽象层**（已知差异，建议不修复）：
   - inputSchema 规范化层（`normalizeToolInputSchema`）
   - ToolCatalog 工具目录层（`BASE_TOOL_CATALOG`）
   - executor 依赖注入层（`ShellExecutor` / `FileReadExecutor` 等）

4. **Charles 在两个点上强于 Cline**（应予保留）：
   - 动态注册能力（`register_tool` 支持 runtime 期注册，Cline 仅支持构造期数组传入）
   - 工具描述动态生成（`@property description` 天然支持，SkillTool 已利用此特性）

5. **nanobot 残留**：P3.1 核心文件中仅 `__init__.py` L2 有 1 处注释残留，`base.py` 已清理完毕，无实现逻辑残留。

6. **默认值策略差异**（已知差异，建议不修复）：Charles 的保守默认值（不重试、无超时）符合本地 CLI 场景，Cline 的乐观默认值（重试 3 次、30 秒超时）适合网络型工具。

**整体一致性等级**：**中高**。P3.1 范围内无需阻塞性修复，建议 1（清理 `__init__.py` L2 nanobot 注释）为 P2 级别清理任务，可在后续清理批次中统一处理。
