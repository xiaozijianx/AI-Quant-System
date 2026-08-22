# Phase 5.5 工具说明段对比

> 对比范围：Cline 工具定义序列化机制（`AgentTool` 接口 + `createTool` 工厂 + `zodToJsonSchema` 转换 + `runtime-builder.ts` 工具列表构建）与 Charles 工具说明段构建机制（`SystemPromptBuilder._build_tools_section` + `BaseTool.to_definition` + 增强层 rules 注入）的位置差异、格式差异、skills 工具特殊处理、工具描述生成机制；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（`buildClineSystemPrompt` 纯组装函数，**无** tools 占位符，工具说明不进入 system prompt）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L126-161（`createBuiltinToolsList` 构建工具列表）+ L440-458（runtime 构建 tools 数组传给 runtime）+ L710（`tools: finalTools` 作为 runtime 字段）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L244-319（`createReadFilesTool` 工厂示例，name + description + inputSchema 三字段）+ L720-769（`createSkillsTool` 含动态 description getter，**追加** "Available skills: ..." 列表）
> - `sdk/packages/core/src/extensions/tools/base.ts`（`AgentTool` 接口与 `createTool` 工厂，工具定义序列化为 LLM API 调用参数）
>
> Charles 源码：
> - `agent/context.py` L723-786（`SystemPromptBuilder._build_tools_section` 构建工具说明段，作为增强层 rules 注入 system prompt）
> - `agent/context.py` L611-647（`_build_enhancement_rules` 增强层 rule 列表生成，受 `agent_config/system_prompt.yaml` 配置开关控制）
> - `agent/context.py` L304-346（`_load_enhancements` 读取增强层配置，默认关闭）
> - `agent/tools/base.py` L54-66 + L178-183（`BaseTool` 抽象基类：`name` / `description` / `input_schema` 三属性 + `to_definition()` 转 `AgentToolDefinition`）
> - `agent/tools/__init__.py` L48-112（`create_default_tools` 默认工具集注册）
> - `agent/skills/skill_tool.py` L38-267（`SkillsTool` 类：`_build_description` 动态生成 description，**追加** "可用技能: ..." 列表）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的工具说明段构建机制。**核心结论：Cline 与 Charles 在工具说明段的"位置"上存在根本性架构差异**——Cline 工具说明仅作为 LLM API 调用时的 `tools` 参数（含 name + description + inputSchema 的 JSON Schema 结构）传递，**不**注入 system prompt；Charles 除同样作为 `tools` 参数传递外，**还**通过 `_build_tools_section()` 将工具说明作为增强层 rules 注入 system prompt（受配置开关控制，默认关闭）。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.5（L1870-1873）对 Cline 实现的描述存在以下问题：

1. **"XML 格式"描述错误**：Cline 工具说明使用 JSON Schema 格式（`inputSchema: zodToJsonSchema(...)`，见 definitions.ts L258/354/478 等），**不是** XML 格式。Charles 的 `_build_tools_section()` 输出虽是 Markdown 列表（`- {name}: {desc}`），但也**不是** XML。计划表 5.5.6 "XML 格式：是/是 → 已对齐"的判定基于错误前提。
2. **位置描述模糊**：计划称"Cline 实现（runtime-builder.ts）：自动从 tool definition 生成"。`runtime-builder.ts` 实际只构建 `tools: AgentTool[]` 列表传给 runtime（L440-458 + L710），**不**构建"工具说明段"注入 system prompt。Cline 的 `buildClineSystemPrompt`（cline.ts L110-166）只有 6 个占位符（`{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CLINE_METADATA}}` / `{{CLINE_RULES}}`），**无** tools 占位符。
3. **遗漏关键事实**：Cline **没有**将工具说明作为独立段落注入 system prompt 的设计。Charles 的 `_build_tools_section()` 是 Charles 独有增强（对标 Cline 不存在此机制）。

### 核心结论

1. **工具说明位置差异（根本性）**：Cline 工具说明仅在 LLM API 调用的 `tools` 参数中；Charles 工具说明同时在 `tools` 参数 + system prompt 增强层 rules 中。Charles 的增强层受 `agent_config/system_prompt.yaml` 的 `enhancements.enabled` 控制，**默认关闭**，关闭时行为与 Cline 完全一致。
2. **工具字段格式已对齐**：两者工具定义均含 `name + description + input_schema`（Cline 为 `inputSchema`）三字段。Charles `BaseTool.to_definition()` 序列化为 `AgentToolDefinition`，Cline `createTool` 工厂直接产出 `AgentTool` 对象。
3. **skills 工具展示差异**：Cline `createSkillsTool`（definitions.ts L754-766）通过 `Object.defineProperty` 动态 getter，在 description 末尾**追加** "Available skills: {names}" 列表；Charles `SkillsTool._build_description`（skill_tool.py L225-253）**同样追加** "可用技能: {names}" 列表——两者机制对齐。但 Charles 在 `_build_tools_section()` 中**额外**对 skills 工具做特殊处理（context.py L736-742），用固定文本替换 description，避免与 SkillsSummary 段重复列技能名（Stage P1.1）。
4. **工具 vs 技能 决策树差异**：Cline **无**此段；Charles `_build_tools_section()` 含"工具 vs 技能 决策树"段（context.py L756-773），引导 LLM 在 skills 工具与其他工具间正确决策（Stage P1.2）。属 Charles 独有增强。
5. **工具使用指引差异**：Cline **无**专门的"工具使用指引"段（工具使用规范散布在 base prompt 中）；Charles `_build_tools_section()` 含"工具使用指引"段（context.py L748-754），含并行/串行调用、规划调整等指引。
6. **段落位置差异**：Cline system prompt **无**工具说明段（占位符中无 tools）；Charles 工具说明段作为增强层 rules 注入，位于 Rules 段末尾（在 MODE_TAG/PLAN_MODE 之后、`__extra__` 之前），与计划表 5.5.7 "段落位置：第 3 段/第 3 段 → 已对齐"的判定不符。
7. **nanobot 残留**：**注释残留**：`agent/context.py` 1 处（L275 docstring），`agent/tools/__init__.py` 1 处（L2 docstring），`agent/tools/web_tool.py` / `file_tools.py` / `exec_tool.py` 共 27 处行内注释。**实现逻辑残留**：0 处。所有实际代码均基于 Cline 对标设计实现，nanobot 仅作为历史来源参考被注释引用。

### 一致性总体评估

- **工具字段格式**：**高**。两者均含 name + description + input_schema 三字段，序列化机制对齐。
- **skills 工具 description 动态生成**：**高**。两者均在 description 末尾追加技能名列表，机制对齐。
- **工具说明段位置**：**低**。Cline 不注入 system prompt，Charles 注入（默认关闭）。开启时与 Cline 行为差异显著。
- **工具 vs 技能 决策树**：**低**。Charles 独有，Cline 无。
- **工具使用指引**：**中**。Charles 独有专门段落，Cline 散布在 base prompt。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.5.1 | 工具说明生成 | 自动（`createTool` 工厂 + `zodToJsonSchema` 从 Zod schema 生成 inputSchema，definitions.ts L258 等） | 自动（`BaseTool` 子类实现 `name` / `description` / `input_schema` 属性，`to_definition()` 转 `AgentToolDefinition`，base.py L178-183） | 高 | 两者均自动从工具定义生成。Cline 用 Zod schema → JSON Schema；Charles 直接实现 dict 属性 |
| 5.5.2 | 工具字段 | `name + description + inputSchema`（AgentTool 接口，base.ts） | `name + description + input_schema`（AgentToolDefinition，base.py L180-183） | 高 | 字段名 camelCase vs snake_case 差异，语义完全对齐 |
| 5.5.3 | skills 工具展示 | description 末尾**追加** "Available skills: {names}"（definitions.ts L754-766，通过 `Object.defineProperty` 动态 getter） | description 末尾**追加** "可用技能: {names}"（skill_tool.py L225-253，`_build_description` 方法）+ `_build_tools_section` 中**特殊处理**用固定文本替换 description（context.py L736-742） | 中 | 两者 description 动态生成机制对齐。Charles 额外在 system prompt 工具说明段去重（避免与 SkillsSummary 重复），Cline 无此去重逻辑（因 Cline 不注入 system prompt） |
| 5.5.4 | 工具 vs 技能 决策树 | **无** | **有**（context.py L756-773，"工具 vs 技能 决策树（重要）"段，含 4 步决策流程 + 禁止行为清单） | 低 | Charles 独有增强（Stage P1.2）。Cline 工具使用规范散布在 base prompt 中，无专门决策树 |
| 5.5.5 | 工具使用指引 | 散布在 base prompt（system.ts）中，无专门段落 | **有**（context.py L748-754，"工具使用指引"段，含并行/串行调用、规划调整、skills 前置调用等指引） | 中 | Charles 独有专门段落。Cline 的工具使用规范分散在 base prompt 多处 |
| 5.5.6 | 工具说明格式 | JSON Schema（`inputSchema: zodToJsonSchema(...)`，definitions.ts L258/354/478 等） | 双重：(a) LLM API 调用用 JSON Schema（`input_schema` dict）；(b) system prompt 增强层用 Markdown 列表（`- {name}: {desc}`，context.py L746） | 中 | 计划表称"XML 格式：是/是"有误。Cline 用 JSON Schema；Charles LLM API 调用用 JSON Schema（对齐），system prompt 增强层用 Markdown（Charles 独有） |
| 5.5.7 | 段落位置 | **不注入 system prompt**（cline.ts L110-166 无 tools 占位符，工具说明仅作为 LLM API `tools` 参数） | 作为增强层 rules 注入 system prompt Rules 段末尾（context.py L622-625，在 MODE_TAG/PLAN_MODE 之后） | 低 | 计划表称"第 3 段/第 3 段 → 已对齐"有误。Cline system prompt 无工具说明段；Charles 作为增强层 rules 注入（默认关闭） |
| 5.5.8 | 配置开关 | 无（工具说明始终作为 LLM API `tools` 参数传递，无 system prompt 注入开关） | `agent_config/system_prompt.yaml` 的 `enhancements.enabled` + `enhancements.tools_section`（context.py L304-346），**默认关闭** | 中 | Charles 默认关闭时行为与 Cline 一致（工具说明仅在 LLM API `tools` 参数中）。开启时注入 system prompt |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.5 "XML 格式"描述错误（5.5.6）

AGENT_COMPARISON_PLAN_V2.md L1873 称"Cline 实现（runtime-builder.ts）：... XML 格式"，L1887 计划表 5.5.6 称"XML 格式：是/是 → 已对齐"。经核查：

**Cline 工具说明格式**（definitions.ts L250-258）：

```typescript
return createTool<ReadFilesInput, ToolOperationResult[]>({
    name: "read_files",
    description: "Read the content of text or image files at the provided absolute paths...",
    inputSchema: zodToJsonSchema(ReadFilesInputSchema),  // JSON Schema 格式
    ...
});
```

`zodToJsonSchema` 将 Zod schema 转为 JSON Schema 对象（含 `type` / `properties` / `required` 字段），**不是** XML 格式。

**Charles 工具说明格式**（双重）：

(a) LLM API 调用用 JSON Schema（base.py L66 + L180-183）：

```python
@property
def input_schema(self) -> dict[str, Any]:
    ...  # 返回 JSON Schema dict

def to_definition(self) -> AgentToolDefinition:
    return AgentToolDefinition(
        name=self.name,
        description=self.description,
        input_schema=self.input_schema,  # JSON Schema 格式
    )
```

(b) system prompt 增强层用 Markdown 列表（context.py L732-746）：

```python
lines = ["# 工具", "", "可用工具:"]
for tool in self.tools:
    name = getattr(tool, "name", "")
    desc = getattr(tool, "description", "")
    ...
    if name:
        lines.append(f"- {name}: {desc}")  # Markdown 列表格式
```

**结论**：两者工具说明格式均**不是** XML。Cline 用 JSON Schema；Charles LLM API 调用用 JSON Schema（对齐），system prompt 增强层用 Markdown 列表（Charles 独有）。计划表 5.5.6 判定基于错误前提，需修正。

### 3.2 工具说明段位置差异（5.5.7，根本性架构差异）

**Cline 实现**：

Cline 的 `buildClineSystemPrompt`（cline.ts L110-166）只处理 6 个占位符：

```typescript
return basePrompt
    .replace("{{PLATFORM_NAME}}", platform)
    .replace("{{CWD}}", workspaceRoot)
    .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
    .replace("{{IDE_NAME}}", ide)
    .replace("{{CLINE_METADATA}}", isCline ? buildWorkspaceMetadata(...) : "")
    .replace("{{CLINE_RULES}}", effectiveRules)
    .trim();
```

**无** `{{CLINE_TOOLS}}` 或类似占位符。工具说明仅作为 LLM API 调用的 `tools` 参数传递（runtime-builder.ts L710 `tools: finalTools`），**不**注入 system prompt。

**Charles 实现**：

Charles 的 `build_charles_system_prompt`（context.py L78-127）同样只处理 6 个占位符（`{{PLATFORM_NAME}}` / `{{CWD}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CHARLES_RULES}}` / `{{CHARLES_METADATA}}`），工具说明通过 `{{CHARLES_RULES}}` 作为增强层 rules 注入（context.py L622-625 + L521-528）：

```python
# _build_enhancement_rules (context.py L622-625)
if self._enhancements.get("tools_section"):
    body = self._build_tools_section()
    if body:
        rules.append(("charles-tools-overview", body))

# _build_rules (context.py L521-528)
if self._enhancements.get("enabled"):
    for title, body in self._build_enhancement_rules():
        if body:
            results.append(RuleLoadResult(
                path=Path(f"__enhancements__/{title}.md"),
                body=body,
                activated=True,
            ))
```

**影响**：

- Charles 默认关闭（`enhancements.enabled: false`，context.py L320）时，行为与 Cline 一致（工具说明仅在 LLM API `tools` 参数中）。
- Charles 开启时，工具说明作为 rules 注入 system prompt，会增加 system prompt token 占用，但提供更明确的工具使用指引（含决策树、并行/串行调用规范等）。

**评估**：Charles 独有增强，非对齐缺口。开启时属合理偏离（量化场景需要更明确的工具 vs 技能决策引导）。

### 3.3 skills 工具 description 生成机制对齐（5.5.3）

**Cline 实现**（definitions.ts L754-766）：

```typescript
Object.defineProperty(tool, "description", {
    get() {
        const skills = executor.configuredSkills
            ?.filter((s) => !s.disabled)
            .map((s) => s.name);
        if (skills && skills.length > 0) {
            return `${baseDescription} Available skills: ${skills.join(", ")}.`;
        }
        return baseDescription;
    },
    enumerable: true,
    configurable: true,
});
```

通过 `Object.defineProperty` 动态 getter，每次访问 `tool.description` 时实时读取 `executor.configuredSkills`，过滤禁用技能，拼接 "Available skills: {names}." 后缀。

**Charles 实现**（skill_tool.py L225-253）：

```python
def _build_description(self) -> str:
    """构建动态 description，包含可用技能列表

    严格对标 Cline createSkillsTool 中 baseDescription（definitions.ts L725-731）：
    - 给出具体调用示例
    - 强调 skill 匹配时调用此工具是阻断性前置要求
    - 禁止空谈 skill 而不调用
    - description 末尾追加 Available skills 列表
    """
    base = (
        "执行一个已配置的技能。当用户的任务与某个可用技能匹配时，..."
    )
    try:
        skills = self._registry.list_skills()
        if skills:
            names = ", ".join(s.name for s in skills)
            return f"{base} 可用技能: {names}。"
    except Exception:
        pass
    return base

@property
def description(self) -> str:
    return self._build_description()
```

通过 `@property` 动态属性，每次访问 `tool.description` 时调用 `_build_description()`，从 `self._registry.list_skills()` 读取技能列表，拼接 "可用技能: {names}." 后缀。

**差异**：

1. **机制对齐**：两者均用动态属性（Cline getter / Charles `@property`）实时生成 description。
2. **过滤逻辑**：Cline 过滤 `!s.disabled`；Charles `list_skills()` 默认返回所有技能（需检查 `SkillRegistry.list_skills` 是否过滤 disabled）。
3. **后缀文本**：Cline "Available skills: {names}."；Charles "可用技能: {names}。"（中英文差异）。
4. **Charles 额外去重**：`_build_tools_section()`（context.py L736-742）对 skills 工具特殊处理，用固定文本替换 description，避免在 system prompt 工具说明段中重复列技能名（因 SkillsSummary 段已列）。Cline 无此去重逻辑（因 Cline 不注入 system prompt）。

### 3.4 工具 vs 技能 决策树为 Charles 独有增强（5.5.4）

Charles `_build_tools_section()` 含"工具 vs 技能 决策树（重要）"段（context.py L756-773），引导 LLM 在 skills 工具与其他工具间正确决策：

```
## 工具 vs 技能 决策树（重要）
遇到用户任务时，按以下顺序决策:
1. 任务匹配某个技能（财务分析/RAG读年报/K线行情/写研报/...）?
    → 是: 先调用 skills(skill="...") 加载该技能 SKILL.md 指令，...
2. 任务是通用文件操作（读代码/搜索/编辑）?
    → 是: 直接调用 read_files / search_codebase / editor 等工具，无需 skills
3. 任务是临时命令执行（git status / ls / 跑独立脚本）?
    → 是: 直接调用 run_commands 工具
4. 任务需要联网搜索新闻/公告?
    → 是: 直接调用 web_search 工具（但股价/财报等本地已有数据禁止 web_search）

**禁止行为**:
- 禁止不调用 skills 工具而直接 run_commands 调用技能目录下的脚本
- 禁止把技能名当作工具名直接调用（如 stock-price(...) 是错误的，应 skills(skill="stock-price")）
- 禁止在 skills 工具返回指令前就假定知道脚本参数格式
```

**Cline 对比**：Cline **无**此段。Cline 的工具使用规范散布在 base prompt（`DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT`）中，无专门的工具 vs 技能决策引导。

**评估**：Charles 独有增强（Stage P1.2），属合理偏离。量化场景技能较多（财务分析/RAG/K线/研报等），需要更明确的决策引导避免 LLM 误调用。

### 3.5 工具使用指引段差异（5.5.5）

Charles `_build_tools_section()` 含"工具使用指引"段（context.py L748-754）：

```
## 工具使用指引
- 一次回复中可调用多个独立工具（并行），如多个 read_files / search_codebase
- 依赖的工具调用需分多轮（如先 read_files 再 editor）
- 当任务与某个专业技能（如 stock-price、read-pdf、write-report）匹配时，必须先调用 skills 工具加载该技能指令，再按返回的指令执行
- 工具调用前先规划，调用后根据结果调整下一步
```

**Cline 对比**：Cline **无**专门的"工具使用指引"段。Cline 的工具使用规范散布在 base prompt 中（如 "When you already know multiple files you need, read them together in one call" 见 definitions.ts L254），无集中段落。

**评估**：Charles 独有专门段落，属合理偏离。集中的工具使用指引便于 LLM 在工具调用前快速参考规范。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对工具说明段构建相关文件检查 nanobot 风格残留：
- `agent/context.py`（`_build_tools_section` + `_build_enhancement_rules` + `_load_enhancements`）
- `agent/tools/__init__.py`（`create_default_tools` 工具注册）
- `agent/tools/base.py`（`BaseTool` 抽象基类）
- `agent/tools/web_tool.py` / `file_tools.py` / `exec_tool.py`（具体工具实现）
- `agent/skills/skill_tool.py`（`SkillsTool` 类）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` |
| `agent/tools/__init__.py` | 1 | 0 | L2 docstring：`工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools` |
| `agent/tools/base.py` | 0 | 0 | 无残留 |
| `agent/tools/web_tool.py` | 5 | 0 | L2/L9-10/L13/L28/L111/L165 行内注释："对标 nanobot WebSearchTool" / "nanobot/agent/tools/web.py L124-140" 等 |
| `agent/tools/file_tools.py` | 5 | 0 | L2/L7/L12/L27/L115/L130/L165 行内注释："对标 nanobot FilesystemTool" / "nanobot filesystem.py L150-176" 等 |
| `agent/tools/exec_tool.py` | 7 | 0 | L2/L8-10/L18-19/L41/L57/L123/L165/L181/L263 行内注释："对标 nanobot ShellTool" / "nanobot shell.py L113-183" 等 |
| `agent/skills/skill_tool.py` | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（共 19 处）

**类型 A：实现来源标注**（`agent/tools/` 下 17 处）

形式：`对标 nanobot xxx 方法` / `对标 nanobot xxx.py L123-185`

示例（`agent/tools/exec_tool.py` L18-19）：

```python
"""
对标 nanobot:
    - nanobot/agent/tools/shell.py L113-183
"""
```

**性质**：纯注释，说明当前代码实现参考了 nanobot 的某个方法/文件，实际代码已用 Cline 对标设计重写。不影响运行时行为。

**类型 B：兼容性说明**（`agent/context.py` L275，1 处）

```python
def __init__(
    self,
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

**性质**：说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。不影响运行逻辑。

**类型 C：文件级 docstring 来源标注**（`agent/tools/__init__.py` L2，1 处）

```python
"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools
"""
```

**性质**：文件级 docstring 说明工具系统同时参考了 Cline 和 nanobot。不影响运行逻辑。

#### 4.3.2 实现逻辑残留（0 处）

经核查工具说明段构建链路全部相关方法：

- `SystemPromptBuilder._build_tools_section`（context.py L723-786）：**无 nanobot 风格实现逻辑**。工具列表遍历用 `getattr(tool, "name", "")` / `getattr(tool, "description", "")`，skills 工具特殊处理用固定文本替换 description，工具使用指引和决策树均为 Charles 独有增强。
- `SystemPromptBuilder._build_enhancement_rules`（context.py L611-647）：**无 nanobot 风格实现逻辑**。增强层 rule 列表按配置开关生成，与 Cline extension 注册机制不同但非 nanobot 风格。
- `SystemPromptBuilder._load_enhancements`（context.py L304-346）：**无 nanobot 风格实现逻辑**。读取 YAML 配置，默认全部 false。
- `BaseTool.to_definition`（base.py L178-183）：**无 nanobot 风格实现逻辑**。转为 `AgentToolDefinition` 对标 Cline 工具定义序列化。
- `SkillsTool._build_description`（skill_tool.py L225-253）：**无 nanobot 风格实现逻辑**。严格对标 Cline `createSkillsTool` 中 `baseDescription`（definitions.ts L725-731）。
- `create_default_tools`（tools/__init__.py L48-112）：**无 nanobot 风格实现逻辑**。工具注册顺序和工具类均为 Cline 对标设计。

**结论**：工具说明段构建链路中**无任何 nanobot 实现逻辑残留**。所有实际代码均基于 Cline 对标设计实现，nanobot 仅作为历史来源参考被注释引用。

### 4.4 与 Phase 2.1 / 2.2 对比

Phase 2.1（agent runtime 类结构）发现 12 个文件含 nanobot 注释残留，全部为注释残留。Phase 2.2（主循环控制流）确认 `agent/runtime.py` 无 nanobot 残留。**工具说明段构建链路的 nanobot 残留分布与 Phase 2.1 一致**——`agent/tools/` 目录下的具体工具实现文件（`web_tool.py` / `file_tools.py` / `exec_tool.py`）保留较多 nanobot 注释残留（17 处），但 `_build_tools_section` 本身无残留。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.5.1 工具说明生成**：已对齐，无需修复。
- **5.5.2 工具字段**：已对齐，无需修复。
- **5.5.3 skills 工具展示**：description 动态生成机制已对齐。Charles 额外去重逻辑属合理增强（避免 system prompt 中技能名重复），无需修复。

### 5.2 优先级 P1（建议处理）

- **5.5.7 段落位置**：Charles 工具说明段作为增强层 rules 注入 system prompt，默认关闭时与 Cline 行为一致。建议在 `_build_tools_section` docstring 中明确标注"Charles 独有增强，Cline 通过 LLM API `tools` 参数传递工具说明，不注入 system prompt"，避免后续对齐工作误判。当前 docstring（context.py L723-728）仅说明"作为可选增强层保留"，未明确与 Cline 的机制差异。

### 5.3 优先级 P2（可选优化）

- **5.5.4 工具 vs 技能 决策树**：Charles 独有增强，量化场景需要更明确的决策引导。建议保留，但可在 docstring 中标注"Charles 独有，Cline 无此段"。
- **5.5.5 工具使用指引**：同上，建议保留并标注"Charles 独有"。

- **nanobot 注释残留**（`agent/tools/` 下 17 处 + `agent/context.py` 1 处 + `agent/tools/__init__.py` 1 处）：建议保留，作为历史说明。`agent/tools/` 下的注释残留可在未来 major 版本统一清理（替换为"对标 Cline xxx"或删除），当前保留不影响功能。

### 5.4 优先级 P3（文档修正）

- **计划文件 P5.5 "XML 格式"描述错误**：建议修正 AGENT_COMPARISON_PLAN_V2.md L1873，将"XML 格式"改为"JSON Schema 格式"，并补充说明 Charles system prompt 增强层用 Markdown 列表。
- **计划文件 P5.5 段落位置判定错误**：建议修正 L1888 计划表 5.5.7，将"段落位置：第 3 段/第 3 段 → 已对齐"改为"Cline 不注入 system prompt / Charles 作为增强层 rules 注入（默认关闭） → 低一致性"。
- **计划文件 P5.5 Cline 位置描述模糊**：建议修正 L1870，明确 Cline 工具说明仅作为 LLM API `tools` 参数传递（runtime-builder.ts L710），不注入 system prompt。

---

## 六、验证方法

### 6.1 工具说明段位置验证

```powershell
# 验证 Cline system prompt 无 tools 占位符
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "tool|Tool"
# 应仅匹配 MODE_TAG_INSTRUCTIONS 中的 "switch_to_act_mode tool" 等，无 {{CLINE_TOOLS}} 占位符

# 验证 Cline 工具定义作为 tools 参数传递
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\runtime-builder.ts" -Pattern "tools: finalTools|tools: AgentTool"
# 应输出 L710 tools: finalTools

# 验证 Charles 工具说明段作为增强层 rules 注入
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "_build_tools_section|tools_section"
# 应输出 L244/L278/L310/L321/L340/L622/L623/L723 等行
```

### 6.2 工具字段格式验证

```powershell
# 验证 Cline 工具定义含 name + description + inputSchema 三字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts" -Pattern "name:|description:|inputSchema:"
# 应输出多处匹配，每个工具工厂含三字段

# 验证 Charles 工具定义含 name + description + input_schema 三字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\base.py" -Pattern "def name|def description|def input_schema|to_definition"
# 应输出 L54/L60/L66/L178 等行
```

### 6.3 skills 工具 description 动态生成验证

```powershell
# 验证 Cline skills 工具动态 description getter
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts" -Pattern "defineProperty|Available skills"
# 应输出 L754 defineProperty 和 L760 Available skills

# 验证 Charles skills 工具动态 description
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\skill_tool.py" -Pattern "_build_description|可用技能"
# 应输出 L81/L225/L249 等行
```

### 6.4 nanobot 残留验证

```powershell
# 在 agent/context.py 中搜索 nanobot（应仅 1 处注释残留）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 应输出 L275: extra_sections: [已废弃] nanobot 风格的额外段落

# 在 agent/tools/ 目录中搜索 nanobot（应 17 处注释残留）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\*.py" -Pattern "nanobot" -CaseSensitive:$false
# 应输出 web_tool.py 5 处 + file_tools.py 5 处 + exec_tool.py 7 处

# 在 agent/skills/skill_tool.py 中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\skill_tool.py" -Pattern "nanobot" -CaseSensitive:$false
# 应无输出
```

### 6.5 增强层配置开关验证

```powershell
# 验证 Charles 增强层默认关闭
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "enabled.*False|default.*enabled"
# 应输出 L320: "enabled": False

# 验证增强层配置文件
Test-Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\system_prompt.yaml"
# 应输出 True，文件含 enhancements.enabled 配置项
```

---

## 七、附录

### 7.1 Cline 工具说明构建链路

```
runtime-builder.ts L126-161 createBuiltinToolsList
  ├─ ToolPresets[resolveToolPresetName({mode})]  ← 按模式选择工具预设
  ├─ createReadFilesTool(...)                    ← definitions.ts L244，含 name+description+inputSchema
  ├─ createSearchCodebaseTool(...)               ← definitions.ts L336
  ├─ createRunCommandsTool(...)                  ← definitions.ts L464
  ├─ createSkillsTool(...)                       ← definitions.ts L720，动态 description getter
  └─ ... 其他工具工厂

runtime-builder.ts L440-458 runtime 构建
  └─ tools.push(...createBuiltinToolsList(...))  ← 工具列表加入 runtime

runtime-builder.ts L710 runtime 返回值
  └─ tools: finalTools                           ← 作为 runtime 字段传递给 LLM API 调用

cline.ts L110-166 buildClineSystemPrompt
  └─ 6 个占位符替换（无 tools 占位符）           ← 工具说明不进入 system prompt
```

### 7.2 Charles 工具说明构建链路

```
tools/__init__.py L48-112 create_default_tools
  └─ 返回 list[BaseTool]                          ← 工具实例列表

context.py L248-302 SystemPromptBuilder.__init__
  └─ self.tools = tools or []                     ← 接收工具列表
  └─ self._enhancements = self._load_enhancements()  ← 读取增强层配置

context.py L348-391 SystemPromptBuilder.build
  └─ rules_text = self._build_rules(task_type)    ← 构建规则文本
       └─ _build_enhancement_rules (L611-647)     ← 增强层 rule 列表
            └─ _build_tools_section (L723-786)    ← 工具说明段（受 enhancements.tools_section 控制）
                 ├─ 遍历 self.tools 输出 Markdown 列表
                 ├─ skills 工具特殊处理（固定文本替换 description，L736-742）
                 ├─ 工具使用指引段（L748-754）
                 ├─ 工具 vs 技能 决策树段（L756-773）
                 └─ 任务拆解段 + 输出≠完成段（L774-785）
  └─ build_charles_system_prompt(...)             ← 纯组装，占位符替换

base.py L178-183 BaseTool.to_definition
  └─ AgentToolDefinition(name, description, input_schema)  ← LLM API 调用用工具定义
```

### 7.3 计划文件 P5.5 修正建议汇总

| 计划表行号 | 原描述 | 修正建议 |
|-----------|--------|---------|
| L1870 | "Cline 实现（runtime-builder.ts）：自动从 tool definition 生成" | "Cline 实现：工具定义作为 LLM API `tools` 参数传递（runtime-builder.ts L710），不注入 system prompt" |
| L1873 | "XML 格式" | "JSON Schema 格式（inputSchema: zodToJsonSchema(...)）" |
| L1882 | "工具说明生成：自动/自动 → 已对齐" | 保持"已对齐"（两者均自动生成） |
| L1883 | "工具字段：name + description + input_schema → 已对齐" | 保持"已对齐" |
| L1884 | "skills 工具展示：含技能名列表/不含技能名列表（Stage P1.1）→ Charles 去重" | 修正为："skills description 动态生成：均含技能名列表（机制对齐）；Charles 在 system prompt 工具说明段额外去重（避免与 SkillsSummary 重复）" |
| L1885 | "工具 vs 技能 决策树：无/是 → Charles 额外（Stage P1.2）" | 保持（描述准确） |
| L1886 | "工具使用指引：是/是 → 已对齐" | 修正为："工具使用指引：散布在 base prompt/集中段落 → Charles 独有专门段落" |
| L1887 | "XML 格式：是/是 → 已对齐" | 修正为："工具说明格式：JSON Schema / JSON Schema + Markdown → 中一致性" |
| L1888 | "段落位置：第 3 段/第 3 段 → 已对齐" | 修正为："段落位置：不注入 system prompt / 作为增强层 rules 注入（默认关闭） → 低一致性" |
