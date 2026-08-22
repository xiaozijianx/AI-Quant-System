# Phase 3.6 Schema 校验对比（zod vs jsonschema）

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在工具参数 schema 定义方式、schema 转 LLM 格式、运行时校验调用、校验失败错误格式、normalize_input 逻辑、schema 规范化六个维度，对应 AGENT_COMPARISON_PLAN_V2.md P3.6 章节定义的 9 个对比项。

总体结论：Charles 已将 Cline 的"schema 定义 + zodToJsonSchema 转换 + validateWithZod 校验 + normalizeJsonLikeStringsForSchema 规范化"核心机制对齐到功能等价，但实现路径存在三处分歧：

1. **schema 定义方式根本不同**：Cline 用 zod 库定义 schema（强类型 + coercion 能力），通过 `zodToJsonSchema()` 转为 JSON Schema 发给 LLM；Charles 直接手写 JSON Schema dict，无需转换。这是计划表 3.6.1 / 3.6.2 / 3.6.9 三项差异的根因。
2. **运行时校验调用位置不同**：Cline 的 `validateWithZod` 由**每个工具的 `execute()` 方法自行调用**（runtime 不统一校验），且各工具调用次数/位置不一致（如 `read_files` 在 L263、`search_codebase` 在 L360、`editor` 在 L676）；Charles 的 `_validate_input` 由 `BaseTool.execute()` 在调用 `_execute()` **之前统一调用**，所有工具一致。计划表 3.6.3 将 Charles 校验位置标注为 `_prepare_tool_execution` 不准确——实际位置是 `BaseTool.execute()` 入口（runtime 的 `_prepare_tool_execution` 只做 `_normalize_input_for_schema` 规范化，不做 schema 校验）。
3. **校验失败错误格式不同**：Cline 校验失败时 `validateWithZod` 抛 `Error(z.prettifyError(result.error))`，被 runtime 的 `executePreparedTool` 在 `try/catch` 中捕获后转为 `{ error: message, isError: true }` 扁平结构；Charles 不抛异常，直接返回结构化 `AgentToolResult`，含 `validation_errors` 数组，每项含 `field` / `message` / `validator` / `expected` / `got` 五字段。Charles 的错误信息更结构化、字段路径更精确。

`nanobot` 残留检查结论：在 P3.6 重点文件（`agent/tools/base.py`、`agent/runtime.py` 的 `_normalize_input_for_schema` / `_parse_json_string_for_schema` / `_schema_accepts_kind` 方法、各工具 `input_schema` 属性）**未发现** `nanobot` 字符串残留。`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标说明，与 P2.4 / P2.5 / P3.3 报告结论一致，不影响 schema 校验机制的实现逻辑。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P3.6 章节定义的 9 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 3.6.1 | schema 定义方式 | zod 库（`schemas.ts` 全文，如 `ReadFilesInputSchema = z.object({...})` L55-61） | 手写 JSON Schema dict（各工具 `input_schema` property，如 `read_files.py` L78-109） | 类型系统不同：Cline 用 zod DSL（强类型 + coercion + transform），Charles 直接写 JSON Schema 标准格式 | 已对齐（功能等价，实现形式不同） |
| 3.6.2 | schema 转 LLM 格式 | `zodToJsonSchema()`（`zod.ts` L21-23，调用 `z.toJSONSchema()`）+ `normalizeToolInputSchema()`（`create.ts` L5-79，剥 `$schema` + 强制 type:object） | 原生 JSON Schema（`to_definition()` 直接返回 `input_schema`，`base.py` L178-185） | Charles 无需转换；Cline 多一层 zod→JSON Schema 转换 + 一层规范化后处理 | 已对齐（Charles 更简洁） |
| 3.6.3 | 运行时校验调用 | `validateWithZod()` 由各工具 `execute()` 自行调用（`definitions.ts` L263 / L360 / L532 / L622 / L676 / L741，runtime 不统一校验） | `BaseTool._validate_input()` 由 `BaseTool.execute()` 入口统一调用（`base.py` L117，所有工具一致） | **调用位置不同**：Cline 分散在各工具 execute 内（每个工具自行决定校验时机和 schema），Charles 集中在基类入口（统一强制校验）。计划文档将 Charles 标注为 `_prepare_tool_execution` 不准确 | 已对齐（功能等价，架构不同） |
| 3.6.4 | 校验失败错误格式 | 抛 `Error(z.prettifyError(result.error))`（`zod.ts` L16）→ runtime `executePreparedTool` catch 后转为 `{ error: message, isError: true }`（`agent-runtime.ts` L1509-1515） | 返回结构化 `AgentToolResult`，含 `validation_errors: [{field, message, validator, expected, got}]`（`base.py` L119-127 + L260-273） | Charles 错误信息更结构化：含字段路径（如 `commands[0].path`）、校验器名（type/required/minItems）、期望值、实际值（截断 200 字符）；Cline 是 zod 格式化的扁平错误消息字符串 | Charles 更详细 |
| 3.6.5 | 校验失败反馈 LLM | 错误 result（`{ error: message, isError: true }` 作为 tool result 回传 LLM） | 错误 result（`AgentToolResult(output={error, tool, validation_errors, received_input}, is_error=True)` 作为 tool result 回传 LLM） | 已对齐：两者均通过 tool result 反馈错误让 LLM 自我纠正。Charles 多回传 `validation_errors` 数组和 `received_input`，更利于 LLM 定位字段 | 已对齐（Charles 增强） |
| 3.6.6 | 嵌套对象校验 | zod 递归（z.object 嵌套 z.object，`safeParse` 自动递归校验） | jsonschema 递归（`Draft7Validator.iter_errors` 自动递归 properties 嵌套） | 等价：均支持任意深度嵌套对象校验。Charles 通过 `error.absolute_path` 构建字段路径如 `commands[0].path` | 等价 |
| 3.6.7 | 枚举值校验 | zod enum（`z.enum(["a", "b"])`） | jsonschema enum（`{"enum": ["a", "b"]}`） | 等价：均支持枚举值校验。Cline 内置工具未使用 enum（schemas.ts grep `z.enum` / `z.coerce` 无匹配）；Charles 在 `todo_write.py` L82 使用了 `"enum": ["pending", "in_progress", "completed"]` 约束 todo 状态字段 | 等价（Charles 实际使用更多） |
| 3.6.8 | 必填字段校验 | zod required（`z.object({key: z.string()})` 默认必填，`.optional()` 标记可选） | jsonschema required（`"required": ["key"]` 显式列表） | 等价：均支持必填字段校验。Cline 默认必填（可选需 `.optional()`），Charles 显式列出 required 数组。Charles 还保留 `_validate_required()` 旧方法（`base.py` L187-210）供子类按需调用，附参数说明和默认值提示，但 `execute()` 已改用 `_validate_input()` | 等价 |
| 3.6.9 | 类型 coercion | zod 支持（`z.string().transform()` / `z.coerce.number()` 等，`RunCommandsInputUnionSchema` 用 `.transform()` 将 `file_path` 别名转为 `path` L77/L80） | jsonschema 不支持（`jsonschema.Draft7Validator` 仅校验不转换） | **Charles 弱**：Cline 的 zod schema 可在 `safeParse` 时执行 transform/coerce（如 `LooseReadFileRequestSchema` 将 `file_path` / `filePath` 别名自动转为 `path` L73-81），Charles 的 jsonschema 只校验不转换。Charles 通过 `_normalize_input_for_schema` 在校验前做 JSON 字符串解析规范化，但不支持字段别名转换 | Charles 弱（计划文档结论正确） |

## 3. schema 定义方式详细对比

### 3.1 Cline：zod DSL（schemas.ts）

Cline 在 `sdk/packages/core/src/extensions/tools/schemas.ts` 中用 zod 库定义所有工具的 input schema。zod schema 同时用于：
- 类型推导（`z.infer<typeof ReadFilesInputSchema>` 生成 TypeScript 类型）
- 运行时校验（`schema.safeParse(input)` 校验输入）
- JSON Schema 生成（`z.toJSONSchema(schema)` 转换后发给 LLM）

示例（`ReadFilesInputSchema` L55-61）：

```typescript
export const ReadFilesInputSchema = z.object({
    files: z
        .array(ReadFileRequestSchema)
        .describe(
            "Array of file read requests; each element is one file and must include path. ...",
        ),
});
```

zod 的优势：
- **强类型**：`z.infer` 自动生成 TypeScript 类型，避免手写 interface。
- **coercion/transform**：`LooseReadFileRequestSchema`（L73-81）用 `z.union` + `.transform()` 将 `file_path` / `filePath` 别名自动转为 `path`，让 LLM 用任何一种命名都能通过校验。
- **union 容错**：`ReadFilesInputUnionSchema`（L86-104）用 `z.union` 允许 9 种输入形态（单字符串 / 字符串数组 / 对象 / files 数组等），模型生成的不规范输入都能被规范化。
- **describe 链式**：`.describe()` 直接附加字段说明，zod 会自动转成 JSON Schema 的 `description` 字段。

### 3.2 Charles：手写 JSON Schema dict（各工具 input_schema property）

Charles 在每个工具类中用 `@property` 返回手写的 JSON Schema dict。schema 同时用于：
- LLM function calling（直接作为 `input_schema` 发给 provider）
- 运行时校验（`jsonschema.Draft7Validator(schema).iter_errors(input)`）

示例（`read_files.py` L78-109）：

```python
@property
def input_schema(self) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径..."},
                        "start_line": {"type": "integer", "minimum": 1, ...},
                        "end_line": {"type": "integer", "minimum": 1, ...},
                    },
                    "required": ["path"],
                },
                "description": "文件读取请求数组",
                "maxItems": 10,
            },
        },
        "required": ["files"],
    }
```

Charles 的特点：
- **直出 JSON Schema**：无需 zod→JSON Schema 转换，LLM 直接消费。
- **无 coercion**：jsonschema 标准不支持 transform，字段别名转换需手写代码。
- **maxItems 等约束**：直接写 `"maxItems": 10` / `"minimum": 1`，与 JSON Schema 标准一致。
- **中文 description**：所有字段说明用中文（如"文件路径"、"起始行"），与 Cline 英文 description 不同。

### 3.3 实现形式差异分析

| 维度 | Cline（zod） | Charles（手写 JSON Schema） | 评价 |
|------|-------------|---------------------------|------|
| 类型安全 | zod 编译期类型检查 | 无类型检查（dict 字符串 key 易拼错） | Cline 优 |
| schema 复用 | `ReadFileRequestSchema.shape.start_line` 跨 schema 复用字段定义 | 手写重复，无复用机制 | Cline 优 |
| LLM 可见性 | 需 `zodToJsonSchema()` 转换 | 原生 JSON Schema 直出 | Charles 简洁 |
| coercion 能力 | 支持 transform / coerce | 不支持 | Cline 优（见 3.6.9） |
| 错误信息 | zod 自带 prettifyError 格式化 | jsonschema 标准 error 对象 | Charles 字段路径更精确 |
| 学习成本 | 需学 zod DSL | JSON Schema 标准 | Charles 低 |
| 运行时依赖 | 依赖 zod 库 | 依赖 jsonschema 库 | 等价 |

## 4. schema 转 LLM 格式详细对比

### 4.1 Cline：zodToJsonSchema + normalizeToolInputSchema 两层处理

#### 4.1.1 zodToJsonSchema（zod.ts L21-23）

```typescript
export function zodToJsonSchema(schema: z.ZodTypeAny): Record<string, unknown> {
    return z.toJSONSchema(schema);
}
```

简单包装 `z.toJSONSchema()`（zod v4 内置方法），将 zod schema 转为 JSON Schema dict。

#### 4.1.2 normalizeToolInputSchema（create.ts L5-79）

`createTool` 工厂函数（L81-130）在注册工具时调用 `normalizeToolInputSchema` 对转换后的 schema 做后处理：

1. **剥除 `$schema` meta 字段**（L11）：zod v4 的 `z.toJSONSchema()` 会自动添加 `"$schema": "https://json-schema.org/draft-07/schema"` meta 字段，对 LLM 工具定义无用且可能让严格校验器困惑，故删除。
2. **补全顶层 `type: "object"`**（L13-25）：若 schema 缺 `type` 但有 `properties` / `required` / `additionalProperties`，自动补 `type: "object"`。
3. **处理 oneOf / anyOf**（L26-77）：若顶层是 `oneOf` / `anyOf`，要求所有分支都是 object 类型（否则抛错）；若顶层是 `allOf`，要求至少一个分支是 object 类型（否则抛错）。这是为了让 LLM provider 严格识别工具输入为 object。
4. **强制抛错**（L49-54 / L71-76）：若 schema 不符合 object 约束，**在工具注册时立即抛错**（fail loudly），让开发者在注册阶段发现错误而非推理时。

```typescript
const inputSchema = normalizeToolInputSchema(
    config.inputSchema instanceof z.ZodType
        ? zodToJsonSchema(config.inputSchema)
        : config.inputSchema,
);
```

#### 4.1.3 工具注册时调用

每个工具在 `createTool({...})` 时传入 zod schema（如 `definitions.ts` L258 `inputSchema: zodToJsonSchema(ReadFilesInputSchema)`），`createTool` 内部会再调 `normalizeToolInputSchema` 后处理。

### 4.2 Charles：原生 JSON Schema，无转换

Charles 的 `BaseTool.to_definition()`（`base.py` L178-185）直接返回 `AgentToolDefinition(input_schema=self.input_schema, ...)`，无任何转换：

```python
def to_definition(self) -> AgentToolDefinition:
    return AgentToolDefinition(
        name=self.name,
        description=self.description,
        input_schema=self.input_schema,
        lifecycle=self.lifecycle,
    )
```

各工具的 `input_schema` property 返回手写的 JSON Schema dict，直接作为 LLM function calling 的 `input_schema` 字段。

### 4.3 差异分析

| 步骤 | Cline | Charles | 等价性 |
|------|-------|---------|--------|
| 1. schema 定义 | zod DSL | JSON Schema dict | 形式不同 |
| 2. schema 转换 | `zodToJsonSchema()` → `z.toJSONSchema()` | 无转换 | Cline 多一步 |
| 3. schema 规范化 | `normalizeToolInputSchema()` 后处理（剥 `$schema`、补 `type:object`、校验 oneOf/anyOf/allOf） | 无规范化 | **Cline 多一层保护** |
| 4. 发给 LLM | 转换 + 规范化后的 JSON Schema | 原生 JSON Schema | 等价 |

Cline 的 `normalizeToolInputSchema` 是 Charles 缺失的一层保护：若开发者手写的 zod schema 顶层不是 object（如误用 `z.union` 不规范），Cline 会在工具注册时立即抛错；Charles 手写 JSON Schema 不会做这种校验，错误会延迟到运行时或被 LLM 误用。

## 5. 运行时校验调用详细对比

### 5.1 Cline：validateWithZod 由各工具自行调用

Cline 的 `validateWithZod`（`zod.ts` L13-19）是一个独立函数，由每个工具的 `execute()` 方法**自行决定**是否调用、调用几次、用哪个 schema：

```typescript
export function validateWithZod<T>(schema: z.ZodType<T>, input: unknown): T {
    const result = schema.safeParse(input);
    if (!result.success) {
        throw new Error(z.prettifyError(result.error));
    }
    return result.data;
}
```

调用位置统计（`definitions.ts`）：

| 工具 | 调用位置 | 调用的 schema | 备注 |
|------|---------|--------------|------|
| `read_files` | L263-266 | `ReadFilesInputUnionSchema`（union 容错 schema） | 先 `coalesceOrphanReadRanges(input)` 折叠孤儿行范围条目，再校验 |
| `search_codebase` | L360 | `SearchCodebaseUnionInputSchema`（union 容错 schema） | 直接校验 |
| `fetch_web_content` | L532 | `FetchWebContentInputSchema`（严格 schema） | 直接校验 |
| `run_commands` | （经 `normalizeRunCommandsInput` helpers.ts L137-165） | `RunCommandsInputUnionSchema` | 校验 + 规范化多种输入形态 |
| `apply_patch` | L622 | `ApplyPatchInputUnionSchema`（union schema，允许 string 或 object） | 直接校验 |
| `editor` | L676 | `EditFileInputSchema`（严格 schema） | 直接校验 |
| `skills` | L741 | `SkillsInputSchema`（严格 schema） | 直接校验 |

关键观察：
- **runtime 不统一校验**：`agent-runtime.ts` 的 `executePreparedTool`（L1464-1517）只调 `prepared.tool.execute(prepared.input, context)`，不做 schema 校验。
- **校验 schema 不一定是 inputSchema**：`read_files` 的 `inputSchema`（发给 LLM 的）是 `zodToJsonSchema(ReadFilesInputSchema)`（严格），但运行时校验用的是 `ReadFilesInputUnionSchema`（union 容错，允许 9 种输入形态）。
- **校验失败抛异常**：`validateWithZod` 失败时抛 `Error`，被 `executePreparedTool` 的 `try/catch`（L1509-1515）捕获后转为 `{ error: error.message, isError: true }`。
- **union schema + transform**：`LooseReadFileRequestSchema`（L73-81）用 `.transform()` 将 `file_path` / `filePath` 别名转为 `path`，校验后的数据是规范化后的形态。

### 5.2 Charles：_validate_input 由 BaseTool.execute 统一调用

Charles 的 `_validate_input`（`base.py` L212-275）由 `BaseTool.execute()` 在调用 `_execute()` **之前统一调用**：

```python
async def execute(
    self,
    input: dict[str, Any],
    context: AgentToolContext,
) -> AgentToolResult:
    # Phase 29.1: 运行时 schema 校验（含必填字段、类型、约束）
    errors = self._validate_input(input)
    if errors:
        return AgentToolResult(
            output={
                "error": "参数 schema 校验失败",
                "tool": self.name,
                "validation_errors": errors,
                "received_input": input,
            },
            is_error=True,
        )
    try:
        return await self._execute(input, context)
    except AbortedError:
        raise
    except Exception as e:
        return AgentToolResult(output={"error": str(e)}, is_error=True)
```

`_validate_input` 实现（`base.py` L212-275）：

```python
def _validate_input(self, input: dict[str, Any]) -> list[dict[str, Any]]:
    import jsonschema
    errors: list[dict[str, Any]] = []
    schema = self.input_schema
    # 空 schema 或无 type 的 schema 跳过校验
    if not schema or (not schema.get("type") and not schema.get("required")):
        return errors
    validator = jsonschema.Draft7Validator(schema)
    for error in validator.iter_errors(input):
        # 构建字段路径（如 "commands[0].path"）
        path_parts: list[str] = []
        for part in error.absolute_path:
            if isinstance(part, int):
                path_parts.append(f"[{part}]")
            else:
                if path_parts:
                    path_parts.append(f".{part}")
                else:
                    path_parts.append(str(part))
        field_path = "".join(path_parts) or "(root)"
        error_info: dict[str, Any] = {
            "field": field_path,
            "message": error.message,
            "validator": error.validator,
        }
        if error.validator_value is not None:
            error_info["expected"] = error.validator_value
        if error.instance is not None:
            instance_str = repr(error.instance)
            if len(instance_str) > 200:
                instance_str = instance_str[:200] + "..."
            error_info["got"] = instance_str
        errors.append(error_info)
    return errors
```

关键观察：
- **runtime 不参与校验**：`runtime.py` 的 `_prepare_tool_execution`（L1446-1535）只调 `_normalize_input_for_schema`（L1465）做 JSON 字符串解析，不做 schema 校验；`_execute_prepared_tool`（L1769+）调 `tool.execute(input, context)`（L1966/L1970），由 `BaseTool.execute` 入口统一校验。
- **校验 schema 与 LLM schema 一致**：`_validate_input` 用 `self.input_schema`（与发给 LLM 的 schema 完全相同），不存在 Cline 的"LLM schema vs 校验 schema 分离"。
- **校验失败不抛异常**：直接返回 `AgentToolResult(is_error=True)`，含结构化 `validation_errors` 数组。
- **跳过空 schema**：若 schema 无 `type` 且无 `required`，跳过校验（如 `switch_to_act_mode` 的 `{"properties": {}}`）。
- **字段路径构建**：通过 `error.absolute_path` 构建如 `commands[0].path` 的路径，便于 LLM 定位字段。

### 5.3 调用位置差异分析

| 维度 | Cline | Charles | 评价 |
|------|-------|---------|------|
| 校验入口 | 各工具 `execute()` 内自行调用 | `BaseTool.execute()` 统一调用 | Charles 集中、强制 |
| 校验强制度 | 工具可选择不校验或多次校验 | 所有工具必须校验（除非空 schema） | Charles 强制 |
| 校验 schema | 可与 LLM schema 不同（union schema 容错） | 与 LLM schema 完全相同 | Cline 更灵活 |
| 校验失败处理 | 抛异常被 runtime catch | 直接返回 error result | Charles 不需 try/catch |
| runtime 是否参与 | 不参与（runtime 只调 tool.execute） | 不参与（runtime 只调 tool.execute） | 等价 |
| 计划文档描述 | "execute 入口" ✓ | "_prepare_tool_execution" ✗ | **Charles 实际在 BaseTool.execute** |

> **注**：计划文档 P3.6 表格 3.6.3 将 Charles 校验位置标注为 `_prepare_tool_execution`，**与实际代码不符**。Charles 的 `_prepare_tool_execution`（`runtime.py` L1446）只做 `_normalize_input_for_schema`（L1465）规范化，不做 schema 校验；真正的 schema 校验在 `BaseTool.execute()`（`base.py` L117）入口，由 `_validate_input` 执行。本报告以实际源码为准。

## 6. 校验失败错误格式详细对比

### 6.1 Cline：抛 Error → runtime catch → 扁平 error 字符串

Cline 校验失败流程：

1. `validateWithZod` 调 `schema.safeParse(input)` 得到 `result`。
2. 若 `result.success === false`，抛 `new Error(z.prettifyError(result.error))`（`zod.ts` L16）。
3. 异常向上传播到 `executePreparedTool`（`agent-runtime.ts` L1488）的 `try/catch`（L1509-1515）：
   ```typescript
   } catch (error) {
       result = {
           output: {
               error: error instanceof Error ? error.message : String(error),
           },
           isError: true,
       };
   }
   ```
4. 最终 LLM 收到的 tool result 是 `{ error: "<zod prettified message>", isError: true }`，错误消息是 zod 格式化的多行字符串（含字段路径、期望类型、实际值），但是扁平字符串。

`z.prettifyError` 是 zod v4 内置方法，输出格式类似：

```
Validation failed:
  At path: files.0.path — Expected string, received null
```

### 6.2 Charles：返回结构化 validation_errors 数组

Charles 校验失败流程：

1. `_validate_input` 调 `jsonschema.Draft7Validator(schema).iter_errors(input)` 获取所有错误。
2. 对每个错误构建 `error_info` dict（`base.py` L260-273），含 5 个字段：
   - `field`：字段路径（如 `commands[0].path` 或 `(root)`）
   - `message`：jsonschema 错误消息（如 `"null is not of type 'string'"`）
   - `validator`：失败的校验器名（如 `type` / `required` / `minItems` / `minimum`）
   - `expected`：期望值（如 `"string"` 或 `["path"]`，来自 `error.validator_value`）
   - `got`：实际值（截断到 200 字符，来自 `error.instance`，用 `repr()` 包裹）
3. 返回 `AgentToolResult(output={error, tool, validation_errors, received_input}, is_error=True)`（`base.py` L119-127）。
4. LLM 收到的 tool result 是结构化 JSON，含完整错误列表和原始输入。

示例输出：

```json
{
    "error": "参数 schema 校验失败",
    "tool": "read_files",
    "validation_errors": [
        {
            "field": "files[0].path",
            "message": "null is not of type 'string'",
            "validator": "type",
            "expected": "string",
            "got": "None"
        },
        {
            "field": "files",
            "message": "[] is too short",
            "validator": "minItems",
            "expected": 1,
            "got": "[]"
        }
    ],
    "received_input": {"files": [{"path": null}]}
}
```

### 6.3 错误格式差异分析

| 维度 | Cline | Charles | 评价 |
|------|-------|---------|------|
| 错误形态 | 扁平字符串（zod prettifyError） | 结构化数组（jsonschema error 对象） | Charles 更结构化 |
| 字段路径 | zod 路径（`files.0.path`） | JSON Path 风格（`files[0].path`） | Charles 更符合 JSON Schema 标准 |
| 校验器名 | 不暴露（融合在消息中） | 显式 `validator` 字段（type/required/minItems） | Charles 更利于 LLM 程序化处理 |
| 期望值 | 融合在消息中 | 显式 `expected` 字段 | Charles 更精确 |
| 实际值 | 不暴露 | 显式 `got` 字段（截断 200 字符） | Charles 更利于调试 |
| 多错误 | zod 一次返回所有错误（prettifyError 多行） | jsonschema `iter_errors` 迭代所有错误 | 等价 |
| 原始输入 | 不回传 | 回传 `received_input` | Charles 更利于 LLM 自我纠正 |

## 7. normalize_input 逻辑详细对比

### 7.1 Cline：normalizeJsonLikeStringsForSchema（prepareToolExecution 调用）

Cline 在 `prepareToolExecution`（`agent-runtime.ts` L1334-1422）中，工具执行前调用 `normalizeJsonLikeStringsForSchema`（L1366）：

```typescript
if (tool && !skipReason) {
    input = normalizeJsonLikeStringsForSchema(input, tool.inputSchema);
}
```

`normalizeJsonLikeStringsForSchema`（`json.ts` L158-200）的作用：当 LLM 把 object/array 参数写成 JSON 字符串时（如 `commands: "[\"ls\", \"git status\"]"`），根据 schema 期望的类型尝试解析为真正的 object/array，并递归处理嵌套结构。

实现细节：

1. **`parseJsonStringForSchema`**（L126-156）：若 value 是字符串，且 schema 期望 array（`[` 开头）/object（`{` 开头），尝试 `JSON.parse(trimmed)`；解析失败返回原值。
2. **数组递归**（L164-176）：若 value 是数组，递归处理每个元素（用 `schema.items`）。
3. **对象递归**（L178-200）：若 value 是对象，递归处理每个属性（用 `schema.properties[key]`）。
4. **`schemaAcceptsKind`**（L102-124）：检查 schema 是否接受 array/object 类型，支持 `anyOf` / `oneOf` / `allOf` 分支递归检查。

### 7.2 Charles：_normalize_input_for_schema（_prepare_tool_execution 调用）

Charles 在 `_prepare_tool_execution`（`runtime.py` L1446-1535）中调用 `_normalize_input_for_schema`（L1465）：

```python
if tool is not None:
    input_value = self._normalize_input_for_schema(
        input_value, tool.input_schema
    )
```

`_normalize_input_for_schema`（`runtime.py` L2512-2553）实现与 Cline 几乎一致：

1. **`_parse_json_string_for_schema`**（L2555-2581）：若 value 是字符串，且 schema 期望 array/object，尝试 `json.loads(trimmed)`；解析失败返回原值。
2. **数组递归**（L2524-2534）：若 value 是 list，递归处理每个元素（用 `schema["items"]`）。
3. **对象递归**（L2536-2551）：若 value 是 dict，递归处理每个属性（用 `schema["properties"][key]`）。
4. **`_schema_accepts_kind`**（L2583-2605）：检查 schema 是否接受 array/object 类型，支持 `anyOf` / `oneOf` / `allOf` 分支递归检查。

### 7.3 等价性分析

| 步骤 | Cline | Charles | 等价性 |
|------|-------|---------|--------|
| 1. 调用位置 | `prepareToolExecution` L1366 | `_prepare_tool_execution` L1465 | 等价（均在 before_tool hooks 之前） |
| 2. JSON 字符串解析 | `JSON.parse` + `jsonrepair` fallback | `json.loads`（无 fallback） | **Cline 多 jsonrepair 容错** |
| 3. 数组递归 | `value.map(item => normalize(item, items))` | `for item in value: normalize(item, items)` | 等价 |
| 4. 对象递归 | `for ([key, propSchema] of Object.entries(properties))` | `for key, prop_schema in properties.items()` | 等价 |
| 5. schema 类型检查 | `schemaAcceptsKind` 支持 anyOf/oneOf/allOf | `_schema_accepts_kind` 支持 anyOf/oneOf/allOf | 等价 |
| 6. 返回值 | 规范化后的 value（原值未变则返回原引用） | 规范化后的 value（原值未变则返回原引用） | 等价 |

**差异**：Cline 的 `parseJsonStringForSchema` 在 `JSON.parse` 失败时还会尝试 `jsonrepair` 库（`json.ts` L36-40 的 strategies 数组），能修复部分损坏的 JSON（如未引号的对象值）；Charles 的 `_parse_json_string_for_schema` 只用 `json.loads`，无 fallback。但 `_normalize_input_for_schema` 的核心逻辑（递归规范化）两边等价。

## 8. schema 规范化详细对比

### 8.1 Cline：normalizeToolInputSchema（createTool 注册时）

Cline 在 `createTool`（`create.ts` L81-130）注册工具时调用 `normalizeToolInputSchema`（L5-79）对 zod 转换后的 JSON Schema 做后处理：

1. **剥除 `$schema` meta 字段**（L11）：`const { $schema: _ignored, ...schema } = inputSchema;`
2. **补全顶层 `type: "object"`**（L13-25）：若 schema 缺 `type` 但有 `properties` / `required` / `additionalProperties`，自动补 `type: "object"`。
3. **校验 oneOf / anyOf / allOf**（L26-77）：
   - `oneOf` / `anyOf`：所有分支必须 `type: "object"`，否则抛错。
   - `allOf`：至少一个分支 `type: "object"`，否则抛错。
4. **fail loudly**（L49-54 / L71-76）：不符合 object 约束时在注册时立即抛错。

### 8.2 Charles：无 schema 规范化

Charles 的 `BaseTool.to_definition()`（`base.py` L178-185）直接返回 `input_schema`，无任何后处理：

```python
def to_definition(self) -> AgentToolDefinition:
    return AgentToolDefinition(
        name=self.name,
        description=self.description,
        input_schema=self.input_schema,
        lifecycle=self.lifecycle,
    )
```

各工具的 `input_schema` property 返回手写的 JSON Schema dict，原样发给 LLM。

### 8.3 差异分析

| 维度 | Cline | Charles | 评价 |
|------|-------|---------|------|
| 剥 `$schema` | 是（L11） | 不适用（手写无此字段） | 等价 |
| 补 `type: object` | 是（L13-25） | 无（手写时直接写 `type: object`） | 等价 |
| oneOf/anyOf/allOf 校验 | 是（L26-77，注册时抛错） | 无 | **Cline 多一层保护** |
| fail loudly | 是（注册时抛错） | 无（错误延迟到运行时） | **Cline 更早发现错误** |

Charles 缺失 `normalizeToolInputSchema` 等价物的影响：
- Charles 手写 JSON Schema 时若误用 `oneOf` / `anyOf` 顶层非 object 分支，不会在注册时抛错，错误会延迟到 LLM 调用时或运行时校验时才暴露。
- 但 Charles 实际代码中未使用 `oneOf` / `anyOf` / `allOf`（grep `agent/tools/*.py` 无匹配），手写 schema 都是简单的 `type: object` + `properties`，故此差异实际无影响。

## 9. nanobot 残留检查

### 检查范围

P3.6 重点文件为：
- `agent/tools/base.py`（`_validate_input` / `_validate_required` / `execute` / `to_definition`）
- `agent/runtime.py`（`_normalize_input_for_schema` / `_parse_json_string_for_schema` / `_schema_accepts_kind` / `_prepare_tool_execution`）
- 各工具文件（`read_files.py` / `run_commands.py` / `ask_question.py` / `submit_and_exit.py` / `plan_mode.py` / `apply_patch.py` / `editor.py` / `search_codebase.py` / `fetch_web_content.py` / `todo_write.py` / `mcp.py` / `exec_tool.py` / `file_tools.py` / `web_tool.py` / `list_files.py` / `attempt_completion.py` / `routing.py`）的 `input_schema` 属性

### 重点文件检查结论

| 文件 | 残留性质 | 是否影响 schema 校验实现 |
|------|---------|------------------------|
| `agent/tools/base.py` | **无残留** | 不适用 |
| `agent/runtime.py`（schema 校验相关方法） | **无残留** | 不适用 |
| `agent/tools/read_files.py` | **无残留** | 不适用 |
| `agent/tools/run_commands.py` | **无残留** | 不适用 |
| `agent/tools/ask_question.py` | **无残留** | 不适用 |
| `agent/tools/submit_and_exit.py` | **无残留** | 不适用 |
| `agent/tools/plan_mode.py` | **无残留** | 不适用 |
| `agent/tools/apply_patch.py` | **无残留** | 不适用 |
| `agent/tools/editor.py` | **无残留** | 不适用 |
| `agent/tools/search_codebase.py` | **无残留** | 不适用 |
| `agent/tools/fetch_web_content.py` | **无残留** | 不适用 |
| `agent/tools/todo_write.py` | **无残留** | 不适用 |
| `agent/tools/mcp.py` | **无残留** | 不适用 |
| `agent/tools/exec_tool.py` L2-263 | 多处 docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | 多处 docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | 多处 docstring 对标 nanobot WebSearchTool | 否（注释） |

P3.6 重点文件中，`_validate_input` / `_validate_required` / `execute` / `to_definition` / `_normalize_input_for_schema` / `_parse_json_string_for_schema` / `_schema_accepts_kind` / `_prepare_tool_execution` 等核心方法均无 nanobot 命名或 nanobot 风格逻辑。各工具的 `input_schema` 属性也无 nanobot 残留。

`agent/tools/exec_tool.py` / `file_tools.py` / `web_tool.py` 的 nanobot 残留全部为 docstring 层面的历史对标说明，与 P2.4 / P2.5 / P3.3 报告结论一致，不影响 schema 校验机制的实现逻辑。

### 注释残留 vs 实现逻辑残留区分

- **注释残留**：docstring 中引用 `nanobot xxx` 作为历史来源标注（如"对标 nanobot ShellTool"），不影响代码运行时行为。P3.6 重点文件中 `exec_tool.py` / `file_tools.py` / `web_tool.py` 的 docstring 有此类残留，但 `input_schema` 属性本身无残留。
- **实现逻辑残留**：代码中直接移植 nanobot 的类名、方法名、数据结构或控制流。P3.6 重点文件 **未发现** 任何实现逻辑残留，所有 schema 校验相关实现均基于 Cline 对标设计（`_validate_input` 对标 `validateWithZod`，`_normalize_input_for_schema` 对标 `normalizeJsonLikeStringsForSchema`，`_schema_accepts_kind` 对标 `schemaAcceptsKind`）。

## 10. 修复建议

### P0（计划文档修正）

1. **修正 AGENT_COMPARISON_PLAN_V2.md P3.6 章节 3.6.3 项的 Charles 校验位置描述**：计划文档 L793 称 Charles 的运行时校验调用位置为 `_prepare_tool_execution`，**与实际源码不符**。Charles 的 schema 校验实际在 `BaseTool.execute()` 入口（`base.py` L117 调 `_validate_input`），`_prepare_tool_execution`（`runtime.py` L1446）只做 `_normalize_input_for_schema` 规范化，不做 schema 校验。建议修正为"Charles: `BaseTool.execute()` 入口（统一调用 `_validate_input`）"。
   - **影响**：消除计划文档与实际源码的分歧，避免后续工作基于错误信息。
   - **风险**：无，仅文档修正。

### P1（功能增强，可选）

2. **评估是否引入 schema 规范化层（对标 Cline `normalizeToolInputSchema`）**：Cline 在工具注册时调用 `normalizeToolInputSchema` 校验顶层 schema 必须是 object 类型（oneOf/anyOf/allOf 分支校验），不符合则注册时立即抛错。Charles 缺失此层保护。建议：
   - 方案 A（对齐 Cline）：在 `BaseTool.__init_subclass__` 或 `to_definition()` 中加一层 schema 规范化校验，若 `input_schema` 顶层非 object 且无 `type: object`，抛 `ValueError`。
   - 方案 B（保持现状）：Charles 手写 schema 都很简单（`type: object` + `properties`），未使用 oneOf/anyOf/allOf，此差异实际无影响。
   - **推荐**：方案 B，除非未来 Charles 工具引入复杂 schema。
   - **影响**：无（保持现状）。
   - **风险**：无。

3. **评估是否增强 `_normalize_input_for_schema` 的 JSON 解析容错**：Cline 的 `parseJsonStringForSchema` 在 `JSON.parse` 失败时还会尝试 `jsonrepair` 库修复损坏的 JSON（如未引号的对象值 `{"key": some unquoted value}`）。Charles 的 `_parse_json_string_for_schema` 只用 `json.loads`，无 fallback。建议：
   - 方案 A（对齐 Cline）：引入 `jsonrepair` Python 等价库（如 `json-repair`）作为 fallback。
   - 方案 B（保持现状）：Charles 已通过 `_validate_input` 在校验失败时返回结构化错误让 LLM 重试，无需更激进的 JSON 修复。
   - **推荐**：方案 B，因为 Charles 的错误反馈机制已足够让 LLM 自我纠正。
   - **影响**：无（保持现状）。
   - **风险**：无。

### P2（可选，注释清理）

4. **清理 `agent/tools/exec_tool.py` / `file_tools.py` / `web_tool.py` 的 nanobot 注释残留**：这些文件的 docstring 中有多处"对标 nanobot xxx"的历史对标说明。建议改为"对标 Cline xxx"或直接删除 nanobot 引用。此项与 P2.4 / P2.5 / P3.3 报告建议一致，非 P3.6 新增问题。

## 11. 验证方法建议

1. **schema 定义方式验证**：
   - Cline：在 `sdk/packages/core/src/extensions/tools/schemas.ts` 中 grep `z.object` / `z.array` / `z.string` / `z.union`，预期大量匹配（zod DSL）。
   - Charles：在 `agent/tools/*.py` 中 grep `"type": "object"` / `"properties"` / `"required"`，预期大量匹配（手写 JSON Schema）。

2. **schema 转换验证**：
   - Cline：在 `sdk/packages/shared/src/parse/zod.ts` 中确认 `zodToJsonSchema` 调用 `z.toJSONSchema`；在 `sdk/packages/shared/src/tools/create.ts` 中确认 `normalizeToolInputSchema` 在 `createTool` 中被调用。
   - Charles：在 `agent/tools/base.py` 中确认 `to_definition()` 直接返回 `input_schema`，无转换函数。

3. **运行时校验调用位置验证**：
   - Cline：在 `sdk/packages/core/src/extensions/tools/definitions.ts` 中 grep `validateWithZod`，预期 6+ 处匹配（各工具 execute 内自行调用）；在 `sdk/packages/agents/src/agent-runtime.ts` 的 `executePreparedTool` 中确认无 schema 校验调用。
   - Charles：在 `agent/tools/base.py` L117 确认 `_validate_input` 由 `execute()` 统一调用；在 `agent/runtime.py` 的 `_prepare_tool_execution` 中确认无 schema 校验调用（只有 `_normalize_input_for_schema`）。

4. **校验失败错误格式验证**：构造非法参数（如 `read_files(files=[{"path": null}])`）调用工具：
   - Cline：预期返回 `{ error: "<zod prettified message>", isError: true }`（扁平字符串）。
   - Charles：预期返回 `{ error: "参数 schema 校验失败", tool: "read_files", validation_errors: [{field, message, validator, expected, got}], received_input: {...}, is_error: True }`（结构化数组）。

5. **normalize_input 逻辑验证**：构造 LLM 把 array 参数写成 JSON 字符串的场景（如 `run_commands(commands="[\"ls\", \"git status\"]")`）：
   - 两边预期：`commands` 字段被解析为真正的 list `["ls", "git status"]`，校验通过。
   - 验证点：对比 normalize 前后的 input 结构。

6. **类型 coercion 验证（3.6.9）**：构造 LLM 用 `file_path` 别名代替 `path` 调用 `read_files`：
   - Cline：`LooseReadFileRequestSchema`（L73-81）用 `.transform()` 将 `file_path` 转为 `path`，校验通过并规范化。
   - Charles：jsonschema 不支持 transform，`file_path` 不在 `properties` 中会被忽略（`additionalProperties` 默认允许），但 `path` 必填字段会缺失导致校验失败。
   - 验证点：对比两边对字段别名的容错能力。

7. **nanobot 残留回归**：运行 `grep -r "nanobot" agent/tools/base.py agent/runtime.py` 确认重点文件无残留；运行 `grep -r "nanobot" agent/tools/read_files.py agent/tools/run_commands.py agent/tools/ask_question.py agent/tools/submit_and_exit.py agent/tools/plan_mode.py agent/tools/apply_patch.py agent/tools/editor.py agent/tools/search_codebase.py agent/tools/fetch_web_content.py agent/tools/todo_write.py agent/tools/mcp.py agent/tools/list_files.py agent/tools/attempt_completion.py agent/tools/routing.py` 确认各工具 input_schema 文件无残留。
