# Phase 3.2 工具执行接口对比（execute 方法签名）

> 对比范围：Cline `AgentTool.execute` 方法签名、`AgentToolResult` 类型定义、runtime 对 execute 返回值的处理路径，与 Charles `BaseTool.execute` / `AgentTool.execute` Protocol、`AgentToolResult` dataclass、`AgentToolContext` 字段的差异。
>
> Cline 源码：
> - `sdk/packages/shared/src/agent.ts` L146-186（AgentToolDefinition / AgentToolResult / AgentToolContext / AgentTool 接口）
> - `sdk/packages/shared/src/agent.ts` L57-63（AgentToolResultPart）
> - `sdk/packages/shared/src/tools/create.ts` L81-130（createTool 工厂的 execute 签名）
> - `sdk/packages/core/src/extensions/tools/types.ts` L26-37（ToolOperationResult）+ L51-216（各 Executor 类型）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L262 / L358 / L482 / L530 / L621 / L675 / L740 / L790 / L818（各工具 execute 实现）
> - `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` L358-384（createApplyPatchExecutor 返回 `Promise<string>`）
> - `sdk/packages/agents/src/agent-runtime.ts` L1475-1517（executePreparedTool 调用 execute 并包装为 AgentToolResult）
>
> Charles 源码：
> - `agent/types.py` L70-80（ToolResultPart）+ L150-211（ToolLifecycle / AgentToolDefinition / AgentToolResult / AgentToolContext）+ L214-244（AgentTool Protocol）
> - `agent/tools/base.py` L105-138（BaseTool.execute 模板方法）+ L162-176（_execute 抽象方法）
> - `agent/runtime.py` L1767-1912（_execute_prepared_tool 调用 execute 并构建 ToolResultPart）

---

## 一、执行摘要

Cline 与 Charles 在工具执行接口层面**核心语义等价**，但**计划文档 P3.2 对 Cline 的描述与最新源码存在偏差**，需要先纠正认知再讨论差异：

1. **计划文档与源码的偏差**：AGENT_COMPARISON_PLAN_V2.md L681 描述 Cline `execute(input, context): AsyncIterator<AgentToolResult>`，但**最新 Cline SDK 源码已改为 `execute(input, context): Promise<TOutput> | TOutput`**（agent.ts L182-185 / create.ts L85 / L98 / L108）。即 Cline execute **不再是异步迭代器**，不通过 yield 产出多个 AgentToolResult，而是返回单个 `TOutput`，由 runtime 包装为 `AgentToolResult`。

2. **进度更新机制的实际差异**：两侧 execute 均不 yield 中间结果，**进度更新通过 `context.emitUpdate` / `context.emit_update` 回调推送**（Cline agent.ts L174 + agent-runtime.ts L1498-1506；Charles types.py L206 + runtime.py L1820-1823）。Charles 的 `emit_update` 已对齐 Cline，被 `run_commands` / `todo_write` / `plan_mode` / `ask_question` 等工具用于实时推送 stdout / todos / 模式切换 / 问题展示。计划文档 3.2.2 / 3.2.3 标注的"Charles 缺失"实际**不成立**。

3. **AgentToolResult 字段对比**：
   - 字段名差异：Cline `isError` vs Charles `is_error`（camelCase vs snake_case，语言习惯）。
   - 可选性差异：Cline `isError?` / `metadata?` 均为 optional；Charles `is_error: bool = False` / `metadata: dict = field(default_factory=dict)` 均有默认值，dataclass 实例化时字段始终存在。
   - 类型差异：Cline `output: TOutput`（泛型，由工具声明具体类型，如 `ToolOperationResult[]` / `string`）；Charles `output: Any`（无类型约束）。
   - metadata 填充差异：**Cline runtime 主执行路径不填充 metadata**（agent-runtime.ts L1508 `result = { output }`）；**Charles 工具广泛填充 metadata**（FileWriteTool 写 `{"file_path", "chars"}`、EditorTool 写 `{"operation", "path"}` 等共 14 处）。

4. **ToolResultPart 的 metadata 字段差异**：Cline `AgentToolResultPart` **无 metadata 字段**（agent.ts L57-63）；Charles `ToolResultPart` **有 metadata 字段**（types.py L80），但 runtime.py L1890-1896 构建消息时**未把 result.metadata 写入 ToolResultPart**，实际丢弃。两侧最终落地的 tool-result 消息都只有 `output` + `is_error`。

5. **abort_signal 已对齐**：Cline `context.signal: AbortSignal` 与 Charles `context.abort_signal: asyncio.Event` 类型不同但语义等价（详见 P3.4 / P2.6）。

6. **异常处理位置差异**：Cline execute 内部抛异常，由 runtime 的 `executePreparedTool` 用 try/catch 捕获并包装为 `{ output: {error}, isError: true }`（agent-runtime.ts L1509-1516）；Charles `BaseTool.execute` 模板方法在基类内 try/except 捕获并返回 `AgentToolResult(is_error=True)`（base.py L129-138），runtime 再补一层 try/except 处理超时/重试耗尽（runtime.py L1828-1861）。**Charles 多一层防御**。

7. **nanobot 残留**：P3.2 核心文件 `agent/types.py` 与 `agent/tools/base.py` **0 处 nanobot 残留**，已完全清理。其他工具文件（`exec_tool.py` / `file_tools.py` / `web_tool.py` / `skills/*`）的 nanobot 注释残留不在 P3.2 范围内，留待 P3.21 / P3.22 / P3.23 / P3.24 等对应小阶段处理。

8. **一致性总体评估**：**高**。两侧 execute 接口语义等价，进度更新机制等价，AgentToolResult 三字段（output / is_error / metadata）一一对应。计划文档因基于旧版 Cline SDK 描述，误判 Charles 缺失流式与进度更新，本报告予以修正。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.2.1 | execute 返回类型 | `Promise<TOutput> \| TOutput`（agent.ts L185） | `Coroutine[AgentToolResult]`（base.py L109 / types.py L243） | 高 | 计划文档说的 AsyncIterator 已过时；实际两侧均为单值返回 |
| 3.2.2 | 进度更新支持 | `context.emitUpdate(update)` 回调（agent-runtime.ts L1498-1506） | `context.emit_update(update)` 回调（runtime.py L1820-1823） | 高 | **计划文档误判 Charles 缺失**，实际已对齐 |
| 3.2.3 | 长任务进度反馈 | emitUpdate 推 tool-updated 事件 | emit_update 推 STATUS_NOTICE 事件 | 高 | 事件名不同但机制等价（run_commands 实时推 stdout） |
| 3.2.4 | AgentToolResult.output 类型 | `TOutput`（泛型，工具声明，如 `ToolOperationResult[]` / `string`） | `Any`（types.py L182） | 中 | Charles 无类型约束，运行时灵活但无静态检查 |
| 3.2.5 | AgentToolResult.is_error | `isError?: boolean`（optional，agent.ts L160） | `is_error: bool = False`（types.py L183） | 高 | 字段名 camelCase vs snake_case；语义等价 |
| 3.2.6 | AgentToolResult.metadata | `metadata?: Record<string, unknown>`（optional，agent.ts L161） | `metadata: dict[str, Any] = field(default_factory=dict)`（types.py L184） | 高 | Charles 字段始终存在（默认空 dict），Cline 可省略 |
| 3.2.7 | 工具取消支持 | `context.signal: AbortSignal`（agent.ts L171） | `context.abort_signal: asyncio.Event`（types.py L207） | 高 | 类型不同但语义等价，P2.6 已验证 |
| 3.2.8 | context 字段完整性 | 9 字段（agent.ts L164-175） | 9 字段（types.py L188-211） | 高 | 详见 P3.4 |
| 3.2.9 | execute 是否 yield 中间结果 | 否（Promise 单值返回） | 否（coroutine 单值返回） | 高 | 两侧均不通过 yield 产出中间 result |
| 3.2.10 | execute 入参类型 | `input: TInput`（泛型，由工具 schema 推断） | `input: dict[str, Any]`（固定 dict） | 中 | Charles 无 schema 到类型的映射，input 永远是 dict |
| 3.2.11 | runtime 对 execute 返回值的处理 | 包装为 `AgentToolResult { output, isError? }`（agent-runtime.ts L1508 / L1510-1515） | 直接使用 `AgentToolResult`（runtime.py L1829） | 高 | Charles execute 已返回 AgentToolResult，Cline 需 runtime 包装 |
| 3.2.12 | 异常捕获位置 | runtime 的 `executePreparedTool` 捕获（agent-runtime.ts L1487-1516） | `BaseTool.execute` 模板方法 + runtime 双层捕获（base.py L129-138 + runtime.py L1828-1861） | 中 | Charles 多一层防御（基类已捕获，runtime 仍兜底） |
| 3.2.13 | 错误 result 的 output 形态 | `{ error: string }` 对象（agent-runtime.ts L1478 / L1483 / L1512） | `{"error": str}` 对象（base.py L136 / runtime.py L1845-1848 / L1857-1859） | 高 | 结构一致，均将错误信息包在 `error` 键下 |
| 3.2.14 | schema 校验失败 result 形态 | zod 错误对象（工具内 validateWithZod 返回） | `{"error", "tool", "validation_errors", "received_input"}` 结构化（base.py L119-127） | 中 | Charles 错误信息更详细（含字段路径、tool 名、原始 input） |
| 3.2.15 | metadata 实际填充情况 | runtime 主路径不填充（agent-runtime.ts L1508 仅 `{ output }`） | 工具广泛填充（14 处：file_write / editor / run_commands 等） | 低 | **Cline 工具不主动填 metadata，Charles 工具主动填** |
| 3.2.16 | ToolResultPart 是否含 metadata | 不含（agent.ts L57-63 仅 4 字段） | 含字段但 runtime 未写入（types.py L80 + runtime.py L1890-1896） | 低 | Charles dataclass 多 1 字段但实际未落地，两侧等价 |
| 3.2.17 | skip_reason 错误 result | `{ output: { error: skipReason }, isError: true }`（agent-runtime.ts L1476-1480） | `AgentToolResult(output={"error": skip_reason}, is_error=True)`（runtime.py L1790-1794） | 高 | 完全等价 |
| 3.2.18 | unknown tool 错误 result | `{ output: { error: "Unknown tool: X" }, isError: true }`（agent-runtime.ts L1481-1485） | `AgentToolResult(output={"error": f"Unknown tool: {name}"}, is_error=True)`（runtime.py L1795-1799） | 高 | 完全等价 |
| 3.2.19 | execute 超时处理 | `withTimeout(executor(...), timeoutMs)`（definitions.ts L310 / L538） | `_execute_with_timeout_and_retry` + `asyncio.wait_for`（runtime.py L1918+） | 高 | 两侧都在 execute 外包裹超时，P3.5 详述 |
| 3.2.20 | execute 重试处理 | runtime 层未自动重试（retryable/maxRetries 字段保留但 agent-runtime.ts 未实现） | `_execute_with_timeout_and_retry` 实现指数退避重试（runtime.py L1918+） | 中 | **Charles 实际实现了重试，Cline SDK 仅声明字段未实现** |
| 3.2.21 | after_tool hooks 修改 result | 支持（agent-runtime.ts L1522-1538，`after.result` 替换） | 支持（runtime.py L1866-1884，`after_result.result` 替换） | 高 | 机制等价，详见 P2.x hooks 系列 |
| 3.2.22 | abort 异常传播 | signal.aborted 时 execute 内抛 DOMException，runtime 捕获 | `AbortedError` 抛出后不捕获，直接向上传播（base.py L131-133） | 中 | Charles 让 abort 穿透 execute，Cline 由 runtime 统一处理 |
| 3.2.23 | executor 与 execute 的关系 | executor 是底层执行器（返回 `Promise<string>`），execute 是工具层包装（返回 `Promise<ToolOperationResult[]>`） | 无 executor 概念，`_execute` 直接返回 `AgentToolResult` | 中 | Cline 两层拆分（executor + tool），Charles 单层 |
| 3.2.24 | nanobot 残留（P3.2 范围） | N/A | `types.py` / `base.py` 均无残留 | 高 | 已清理完毕 |

**一致性总评**：24 项中，高一致性 16 项、中一致性 7 项、低一致性 1 项（3.2.15）。低一致性项不影响功能正确性，仅反映两侧工具对 metadata 字段的使用习惯不同。

---

## 三、重点差距详细说明

### 差距 1：计划文档对 Cline execute 签名的描述已过时（3.2.1 / 3.2.2 / 3.2.3）

**计划文档描述**（AGENT_COMPARISON_PLAN_V2.md L681-694）：

```
Cline 实现：
- execute(input, context): AsyncIterator<AgentToolResult> — 异步迭代器
- 支持 yield 多个 result（进度更新）
- AgentToolResult: { output: string | object, is_error: boolean, metadata?: object }
```

**实际 Cline 源码**：

`agent.ts` L177-186：
```typescript
export interface AgentTool<TInput = unknown, TOutput = unknown>
    extends AgentToolDefinition {
    timeoutMs?: number;
    retryable?: boolean;
    maxRetries?: number;
    execute: (
        input: TInput,
        context: AgentToolContext,
    ) => Promise<TOutput> | TOutput;
}
```

`create.ts` L85 / L98 / L108（createTool 工厂的三次重载）：
```typescript
execute: (input: TInput, context: AgentToolContext) => Promise<TOutput>;
```

`definitions.ts` L262（read_files 工具的 execute 实现）：
```typescript
execute: async (input, context) => {
    // ... validate + 调用 executor ...
    return Promise.all(requests.map(async (request) => { ... }));
},  // 返回 Promise<ToolOperationResult[]>，非 AsyncIterator
```

`agent-runtime.ts` L1488-1508（runtime 调用 execute）：
```typescript
const output = await prepared.tool.execute(prepared.input, { ... });
result = { output };  // 包装为 AgentToolResult，无 yield
```

**结论**：Cline SDK 已从 AsyncIterator 演进为 Promise 单值返回。AGENT_COMPARISON_PLAN_V2.md 的 P3.2 章节基于旧版 SDK，需以本报告为准。Charles 的 `execute -> AgentToolResult` 与最新 Cline 语义一致。

**影响**：无功能影响。计划文档 3.2.1 标注的"Charles 不支持流式工具"和 3.2.2 / 3.2.3 标注的"Charles 缺失"均不成立——**两侧 execute 均不通过 yield 产出中间 result**，进度更新通过 `emit_update` 回调独立通道推送。

### 差距 2：AgentToolResult.output 类型约束（3.2.4 / 3.2.10）

**Cline 实现**：

`AgentTool<TInput, TOutput>` 是泛型接口，`TOutput` 由工具工厂声明：

- `createReadFilesTool` 声明 `AgentTool<ReadFilesInput, ToolOperationResult[]>`（definitions.ts L247）
- `createApplyPatchTool` 声明 `AgentTool<ApplyPatchInput, ToolOperationResult>`（definitions.ts L610）
- `createSkillsTool` 声明 `AgentTool<SkillsInput, string>`（definitions.ts L733）

execute 返回 `Promise<TOutput>`，TypeScript 编译器在工具实现处强制类型检查，例如 `read_files` 的 execute 必须返回 `Promise<ToolOperationResult[]>`，否则编译失败。

**Charles 实现**：

`AgentToolResult.output: Any`（types.py L182），无类型约束。所有工具的 `_execute` 返回 `AgentToolResult(output=...)`，`output` 可以是 `str` / `dict` / `list` 等任意类型，Python 运行时不检查。

**影响**：

- Cline 的泛型约束让 IDE 能在工具实现处提示 `TOutput` 的具体形态，减少类型错误。
- Charles 的 `Any` 牺牲了静态检查，但 Python 生态本就弱类型，工具数量固定（20 个），影响有限。
- 实际运行时行为一致：`output` 都会被序列化为 tool-result 消息的 `output` 字段，最终发给 LLM。

**建议**：不强制补齐。Python 缺少 Zod 等运行时类型系统，强行用 `typing.Generic` 增加复杂度收益不大。若未来引入 `pydantic` 可考虑给 `AgentToolResult` 加泛型。

### 差距 3：metadata 字段的实际使用差异（3.2.15 / 3.2.16）

**Cline 实现**：

`AgentToolResult.metadata?: Record<string, unknown>`（agent.ts L161）字段在接口中存在，但 runtime 主执行路径**不填充**：

`agent-runtime.ts` L1508：
```typescript
result = { output };  // 仅 output，无 metadata
```

L1510-1515（异常分支）：
```typescript
result = {
    output: { error: error instanceof Error ? error.message : String(error) },
    isError: true,
};  // 仅 output + isError，无 metadata
```

只有 after_tool hooks 替换 `result` 时可能写入 metadata（agent-runtime.ts L1536 `result = after.result`），但默认 hooks 不写。

`AgentToolResultPart`（agent.ts L57-63）也**无 metadata 字段**：
```typescript
export interface AgentToolResultPart {
    type: "tool-result";
    toolCallId: string;
    toolName: string;
    output: unknown;
    isError?: boolean;
}
```

即 Cline 工具执行结果最终落地到消息时，**只有 output + isError 两字段**。

**Charles 实现**：

`AgentToolResult.metadata: dict[str, Any] = field(default_factory=dict)`（types.py L184）字段在 dataclass 中始终存在，工具广泛填充：

- `FileWriteTool`：`metadata={"file_path": str(path), "chars": len(content)}`（file_tools.py L225）
- `EditorTool`：`metadata={"operation": "edit", "path": path_str}`（editor.py L376 / L416 / L439 / L465）
- `RunCommandsTool`：`metadata={"exit_code": exit_code, "command_id": ..., ...}`（run_commands.py L166）
- `ApplyPatchTool` / `ReadFilesTool` / `SearchCodebaseTool` / `FetchWebContentTool` / `ListFilesTool` / `TodoWriteTool` / `AttemptCompletionTool` / `AskQuestionTool` / `PlanModeTool` / `SubmitAndExitTool` / `MCPTool` 均填充
- 共 14 处工具主动写入 metadata

但 `ToolResultPart` 虽有 metadata 字段（types.py L80），runtime 构建消息时**未写入**：

`runtime.py` L1890-1896：
```python
message = create_message(MessageRole.TOOL, [
    ToolResultPart(
        tool_call_id=prepared.tool_call.tool_call_id,
        tool_name=prepared.tool_call.tool_name,
        output=result.output,
        is_error=result.is_error,
    )  # 未传 metadata
])
```

即 Charles 工具设置的 `result.metadata` 在 runtime 构建消息时**被丢弃**，最终落地到 `ToolResultPart` 的 metadata 是默认空 dict。

**影响**：

- 两侧最终落地到 tool-result 消息的字段一致：`output` + `is_error`（Cline）/ `is_error`（Charles）。
- Charles 工具主动填的 metadata 实际不进入消息流，**仅存在于 runtime 内部的 `result` 对象生命周期内**，可被 after_tool hooks 读取（`AfterToolContext.result.metadata`）。
- 这是一个**潜在 bug**：Charles 工具开发者可能误以为 metadata 会被前端或 LLM 看到，实际不会。

**建议**：不强制修改。当前 after_tool hooks 可读取 metadata 用于审计 / 日志，已满足现有需求。若未来需要把 metadata 传给前端，可在 `runtime.py` L1890-1896 的 `ToolResultPart(...)` 构造时补 `metadata=result.metadata`，但需同步检查 SSE 序列化层是否兼容。

### 差距 4：异常处理的双层防御（3.2.12 / 3.2.22）

**Cline 实现**：

execute 内部抛异常，由 runtime 的 `executePreparedTool` 统一捕获（agent-runtime.ts L1487-1516）：

```typescript
try {
    const output = await prepared.tool.execute(prepared.input, { ... });
    result = { output };
} catch (error) {
    result = {
        output: { error: error instanceof Error ? error.message : String(error) },
        isError: true,
    };
}
```

工具内部不做 try/catch（除少数工具如 `read_files` 在 execute 内捕获单个文件的错误以继续处理其他文件，如 definitions.ts L320-328）。

`AbortedError` 等价物（AbortSignal 触发）会抛 DOMException，runtime 的 catch 会捕获并包装为 `isError: true`，**不区分 abort 与普通错误**。

**Charles 实现**：

`BaseTool.execute` 模板方法在基类内 try/except 捕获（base.py L129-138）：

```python
try:
    return await self._execute(input, context)
except AbortedError:
    # 中止异常向上传播，由 runtime 统一处理状态
    raise
except Exception as e:
    return AgentToolResult(
        output={"error": str(e)},
        is_error=True,
    )
```

runtime 再补一层 try/except 处理超时 / 重试耗尽 / 其他异常（runtime.py L1828-1861）：

```python
try:
    result = await self._execute_with_timeout_and_retry(
        prepared.tool, prepared.input, context
    )
except asyncio.TimeoutError:
    result = AgentToolResult(output={"error": "..."}, is_error=True)
except AbortedError:
    raise  # 中止异常向上传播
except Exception as e:
    result = AgentToolResult(output={"error": "..."}, is_error=True)
```

**差异**：

- Charles `AbortedError` **穿透 execute 不捕获**，由 runtime 主循环处理状态（runtime.py L1851-1853），语义清晰。
- Cline 的 abort 被通用 catch 吞掉，包装为 `isError: true` 的普通错误 result，**前端无法区分"用户中止"与"工具报错"**。
- Charles 多一层防御：基类捕获后 runtime 仍兜底，确保任何遗漏异常都不会穿透到主循环导致整个 run 崩溃。

**影响**：Charles 的 abort 处理更清晰，但需注意 `BaseTool.execute` 的 `except Exception` 已捕获所有非 abort 异常，runtime 的 `except Exception` 实际只在超时 / 重试耗尽路径触发，正常路径不会到达。

**建议**：不修改。Charles 当前设计合理，双层防御在工具数量多、子类实现质量参差时更稳健。

### 差距 5：executor 与 execute 的两层拆分（3.2.23）

**Cline 实现**：

Cline 把"底层执行器"与"工具层"拆为两层：

- **executor 层**（executors/*.ts）：返回 `Promise<string>`，纯 I/O 操作。例如 `ShellExecutor` 执行命令返回 stdout，`FileReadExecutor` 读文件返回内容字符串，`ApplyPatchExecutor` 应用 patch 返回受影响文件列表。
- **tool 层**（definitions.ts）：返回 `Promise<ToolOperationResult[]>` 或 `Promise<ToolOperationResult>`，负责 schema 校验、超时包裹、错误格式化、多请求并发等。例如 `createReadFilesTool` 内部 `Promise.all(requests.map(...))` 并发调用 executor，每个 request 独立 try/catch。

`createDefaultExecutors(options)`（executors/index.ts L91-102）集中创建所有 executor，`createBuiltinTools`（index.ts L180-213）把 executor 注入到各工具工厂。同一工具可配不同 executor（如测试用 mock executor）。

**Charles 实现**：

无 executor 概念，`_execute` 直接返回 `AgentToolResult`。工具类内部直接调用 `Path.read_text()` / `subprocess.run()` / `httpx.get()` 等 I/O API，schema 校验由 `BaseTool.execute` 模板方法前置完成，超时由 runtime 的 `_execute_with_timeout_and_retry` 外部包裹。

**差异**：

- Cline 的两层拆分让 executor 可独立测试（executors 目录下有 `.test.ts`），工具层只负责组装。
- Charles 单层设计代码量更少，但工具与 I/O 耦合，测试时需 mock 文件系统 / 子进程。
- 语义上等价：两侧最终都产出 `AgentToolResult` 给 runtime。

**影响**：不影响功能。Charles 单层设计在工具数量固定时更简洁，但可测试性弱于 Cline。

**建议**：不修改。Charles 已有 `BaseTool._execute` 抽象层，若未来需要可测试性，可在子类内进一步抽取 I/O 方法为可注入依赖，但当前无此需求。

---

## 四、AgentToolResult 字段映射对照表

| 字段 | Cline（agent.ts L158-162） | Charles（types.py L177-184） | 差异 |
|------|--------------------------|----------------------------|------|
| output | `output: TOutput`（泛型，必填） | `output: Any`（必填） | Cline 有类型约束，Charles 无 |
| is_error | `isError?: boolean`（optional） | `is_error: bool = False`（有默认值） | 字段名 camelCase vs snake_case；Charles 字段始终存在 |
| metadata | `metadata?: Record<string, unknown>`（optional） | `metadata: dict[str, Any] = field(default_factory=dict)`（有默认值） | Charles 字段始终存在（默认空 dict） |
| 类型定义方式 | TypeScript interface | Python @dataclass | 语言差异 |
| 实例化语法 | 对象字面量 `{ output, isError: true }` | `AgentToolResult(output=..., is_error=True)` | 语言差异 |
| 序列化 | runtime 包装为 `AgentToolResultPart`（无 metadata 字段） | runtime 构建为 `ToolResultPart`（有 metadata 字段但未写入） | 两侧最终消息均只有 output + is_error |

---

## 五、execute 方法签名对照表

| 维度 | Cline（agent.ts L182-185 + create.ts L85） | Charles（base.py L105-109 + types.py L238-242） | 差异 |
|------|------------------------------------------|------------------------------------------------|------|
| 方法签名 | `execute: (input: TInput, context: AgentToolContext) => Promise<TOutput> \| TOutput` | `async def execute(self, input: dict[str, Any], context: AgentToolContext) -> AgentToolResult` | Cline 泛型 TInput/TOutput，Charles 固定 dict/AgentToolResult |
| 调用方式 | `await tool.execute(input, context)` | `await tool.execute(input, context)` | 一致 |
| 返回值 | `TOutput`（由 runtime 包装为 AgentToolResult） | `AgentToolResult`（直接返回） | Cline 多一步 runtime 包装 |
| input 类型 | `TInput`（由 schema 推断，如 `ReadFilesInput`） | `dict[str, Any]`（固定 dict） | Cline 有静态类型，Charles 无 |
| context 类型 | `AgentToolContext`（interface） | `AgentToolContext`（dataclass） | 一致（字段对比见 P3.4） |
| 上下文 emit_update | `context.emitUpdate?: (update: unknown) => void` | `context.emit_update: Callable[[Any], None] \| None = None` | 字段名差异，语义等价 |
| 上下文 signal | `context.signal?: AbortSignal` | `context.abort_signal: Any = None`（实际 asyncio.Event） | 类型不同，语义等价 |
| 是否抽象 | 否（createTool 接收 execute 函数） | 是（BaseTool.execute 是模板方法，_execute 是 abstractmethod） | Charles 用模板方法模式 |
| 子类覆盖点 | 工厂函数传入 execute 实现 | 子类覆盖 `_execute()` | Cline 函数式，Charles OOP |

---

## 六、AgentToolContext 字段对照（与 P3.4 互补，仅列 execute 相关）

| 字段 | Cline（agent.ts L164-175） | Charles（types.py L188-211） | execute 中的用途 |
|------|--------------------------|----------------------------|-----------------|
| session_id | `sessionId?: string` | `session_id: str \| None = None` | 工具可读取用于审计日志 |
| agent_id | `agentId: string` | `agent_id: str = ""` | 工具可读取用于多 agent 路由 |
| conversation_id | `conversationId?: string` | `conversation_id: str \| None = None` | 工具可读取用于会话隔离 |
| run_id | `runId?: string` | `run_id: str \| None = None` | 工具可读取用于追踪当前 run |
| iteration | `iteration: number` | `iteration: int = 0` | 工具可读取用于循环检测 |
| tool_call_id | `toolCallId?: string` | `tool_call_id: str \| None = None` | 工具可读取用于结果关联 |
| signal / abort_signal | `signal?: AbortSignal` | `abort_signal: Any = None` | execute 内检查中止（Cline 由 runtime 包裹，Charles 由 `_check_aborted` 辅助） |
| snapshot | `snapshot?: AgentRuntimeStateSnapshot` | `snapshot: AgentRuntimeStateSnapshot \| None = None` | 工具可读取运行时状态（消息历史等） |
| emit_update | `emitUpdate?: (update: unknown) => void` | `emit_update: Callable[[Any], None] \| None = None` | 工具推送进度更新（todos / stdout / mode 切换） |
| metadata | `metadata?: Record<string, unknown>` | `metadata: dict[str, Any] = field(default_factory=dict)` | 工具读取运行时元数据（run_id / iteration / trigger_source / verbose） |

字段完全一一对应，命名差异为 camelCase vs snake_case。详见 P3.4。

---

## 七、nanobot 残留检查（P3.2 范围）

### 检查范围

P3.2 涉及的核心文件：
- `agent/types.py`（AgentToolResult / AgentToolContext / AgentTool Protocol 定义）
- `agent/tools/base.py`（BaseTool.execute 模板方法）

### 检查结果

| 文件 | nanobot 出现次数 | 残留类型 | 说明 |
|------|----------------|---------|------|
| `agent/types.py` | 0 | — | 已完全清理 |
| `agent/tools/base.py` | 0 | — | 已完全清理 |

### 范围外残留（不在 P3.2 处理范围）

以下文件的 nanobot 残留属**注释残留**（docstring / 行内注释中"对标 nanobot xxx"的描述性文本），不影响实现逻辑，留待对应小阶段处理：

| 文件 | nanobot 出现次数 | 残留类型 | 对应小阶段 |
|------|----------------|---------|-----------|
| `agent/tools/exec_tool.py` | 7 | 注释残留（"对标 nanobot ShellTool" / "对标 nanobot _guard_command" 等） | P3.24 |
| `agent/tools/file_tools.py` | 4 | 注释残留（"对标 nanobot FilesystemTool" / "对标 nanobot filesystem.py L150-176" 等） | P3.23 |
| `agent/tools/web_tool.py` | 4 | 注释残留（"对标 nanobot WebSearchTool" / "对标 nanobot _search_duckduckgo" 等） | P3.21 |
| `agent/skills/loader.py` | 6 | 注释残留 | P3.x skills |
| `agent/skills/registry.py` | 3 | 注释残留 | P3.x skills |
| `agent/skills/__init__.py` | 1 | 注释残留 | P3.x skills |
| `agent/skills/skill_tool.py` | 1 | 注释残留 | P3.x skills |
| `agent/server.py` | 3 | 注释残留 | P1.x |
| `agent/session.py` | 1 | 注释残留 | P1.x |
| `agent/context.py` | 1 | 注释残留 | P1.x |
| `agent/providers/qwen.py` | 6 | 注释残留 | P2.x providers |

**注释残留 vs 实现逻辑残留的判定标准**：

- **注释残留**：仅在 docstring 或 `#` 行内注释中出现 "nanobot" 字样，描述"对标 nanobot xxx"或"与 nanobot 一致"，**不影响代码行为**。这些残留是历史演化痕迹，表明该模块从 nanobot 演化而来但已重新基于 Cline 接口实现。
- **实现逻辑残留**：代码逻辑中仍保留 nanobot 特有的行为模式（如特定的输出格式、错误处理风格、API 调用方式），与 Cline 接口不一致。**P3.2 范围内的 `types.py` 和 `base.py` 不存在此类残留**。

---

## 八、与计划文档的差异修正

| 计划文档条目 | 计划描述 | 实际情况 | 修正 |
|-------------|---------|---------|------|
| 3.2.1 | execute 返回类型：Cline AsyncIterator / Charles coroutine | Cline `Promise<TOutput>` / Charles `Coroutine[AgentToolResult]` | 计划文档基于旧版 Cline SDK，已过时 |
| 3.2.2 | 进度更新支持：Cline yield 中间 result / Charles 无 | 两侧均不 yield，均通过 emit_update 回调 | 计划文档误判 Charles 缺失 |
| 3.2.3 | 长任务进度反馈：Cline yield 进度 / Charles 仅最终结果 | 两侧均通过 emit_update 推进度（Charles run_commands 实时推 stdout） | 计划文档误判 |
| 3.2.4 | AgentToolResult.output 类型：Cline `string \| object` / Charles Any | Cline `TOutput`（泛型）/ Charles `Any` | Cline 实际是泛型，不是简单的 `string \| object` |
| 3.2.5 | AgentToolResult.is_error：Cline boolean / Charles bool | Cline `isError?: boolean`（optional）/ Charles `is_error: bool = False` | 一致，仅字段名差异 |
| 3.2.6 | AgentToolResult.metadata：Cline optional / Charles optional | Cline `metadata?: Record` / Charles `metadata: dict = field(default_factory=dict)` | 一致，Charles 字段始终存在但语义等价 optional |
| 3.2.7 | 工具取消支持：Cline AbortSignal / Charles abort_signal | 一致 | 无修正 |
| 3.2.8 | context 字段完整性：见 P3.4 | 一致 | 无修正 |

---

## 九、结论与建议

### 结论

1. **execute 方法签名核心语义等价**：Cline 与 Charles 的 execute 均为单值返回（Promise / coroutine），均不通过 yield 产出中间 result。计划文档描述的 AsyncIterator 模式已过时。

2. **进度更新机制等价**：两侧均通过 `context.emit_update` 回调独立通道推送进度，与 execute 返回值解耦。Charles 已对齐 Cline。

3. **AgentToolResult 三字段一一对应**：`output` / `is_error` / `metadata` 在两侧均存在，命名差异源于语言习惯（camelCase vs snake_case）。

4. **metadata 落地不一致**：Cline runtime 不填充 metadata，Charles 工具广泛填充但 runtime 构建消息时丢弃。两侧最终 tool-result 消息均只有 output + is_error。

5. **异常处理 Charles 更稳健**：Charles 双层防御（BaseTool + runtime），且 `AbortedError` 穿透 execute 由主循环处理，语义比 Cline 更清晰。

6. **P3.2 核心文件无 nanobot 残留**：`types.py` 和 `base.py` 已完全清理。

### 建议

1. **不修改源码**：P3.2 范围内的实现已与最新 Cline SDK 对齐，无需调整。

2. **修正计划文档**：建议在 AGENT_COMPARISON_PLAN_V2.md 的 P3.2 章节标注"基于旧版 SDK 描述，最新 Cline 已改为 Promise<TOutput>，详见 phase_3.2 报告"。

3. **后续关注 metadata 落地**：若未来需要把工具 metadata 传给前端或 LLM，需在 `runtime.py` L1890-1896 的 `ToolResultPart(...)` 构造时补 `metadata=result.metadata`，并同步检查 SSE 序列化层。当前不修改。

4. **后续小阶段关注 executor 拆分**：Charles 的单层 `_execute` 设计在 P3.22 / P3.23 / P3.24 等具体工具对比中可能暴露可测试性差距，届时再评估是否引入 executor 层。
