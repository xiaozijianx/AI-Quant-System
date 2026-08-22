# Phase 3.24 ask_question / exec_tool 实现对比

> 对比范围：Cline `createAskQuestionTool` 工厂 + `AskQuestionInputSchema` + `AskQuestionExecutor` 与 Charles `AskQuestionTool` 类的实现差异；Charles `ExecTool` 类的废弃状态、注册情况、代码清理必要性评估；nanobot 风格残留扫描。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L770-794（`createAskQuestionTool` 工厂）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L871-933（`createDefaultTools` 中 ask_question 装配与互斥逻辑）
> - `sdk/packages/core/src/extensions/tools/schemas.ts` L255-272（`AskQuestionInputSchema` Zod 定义）
> - `sdk/packages/core/src/extensions/tools/types.ts` L144-153（`AskQuestionExecutor` 类型）+ L209-217（executors 字段）+ L279-287（`enableAskQuestion` 开关）
> - `sdk/packages/core/src/extensions/tools/runtime.ts` L66-71（`ask_question` catalog 条目）+ L110（`TOOL_NAME_TO_FLAG` 映射）
> - `sdk/packages/core/src/extensions/tools/constants.ts` L20（`ASK: "ask_question"` 常量）
> - `sdk/packages/core/src/extensions/tools/definitions.test.ts` L127-271（ask_question 测试用例，含阻塞等待验证）
> - `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` L45 / L56（routing 映射）
>
> Charles 源码：
> - `agent/tools/ask_question.py`（`AskQuestionTool` 类，全文 114 行）
> - `agent/tools/exec_tool.py`（`ExecTool` 类，全文 271 行，已废弃）
> - `agent/tools/__init__.py` L12 / L30 / L55 / L99 / L125（ExecTool 废弃标注与 AskQuestionTool 注册）
> - `agent/tools/constants.py` L24-47 / L112-140（exec_tool 常量与 TOOL_PRESETS 字典）

---

## 一、执行摘要

本阶段对比两个工具：`ask_question`（活跃工具，Cline 与 Charles 都有对应实现）和 `exec_tool`（Charles 独有的废弃工具，Cline 无对应物）。

### 1. ask_question 对比

Cline 与 Charles 在 `ask_question` 工具的**输入 schema 完全一致**（question: string min 1 + options: array min 2 max 5）、**lifecycle 一致**（都不 `completesRun`）、**retryable/maxRetries 一致**（false / 0）。但在**执行语义**上存在根本差异：

- **Cline 是"阻塞等待"语义**：`execute` 调用 `executor(question, options, context)` 并返回其结果；`AskQuestionExecutor` 返回 `Promise<string>`，由 host（如 VS Code 扩展）实现 UI 交互并阻塞等待用户选择，executor resolve 后**返回值即用户答案**，LLM 收到的 tool result 是用户选择的选项字符串。测试用例 `waits for ask_question answers without timing out`（definitions.test.ts L211-271）明确验证了这一行为：executor 返回一个未解决的 Promise，60 秒后仍未 settle，直到 `resolveAnswer("Option 2")` 被调用后才 resolve 为 `"Option 2"`。
- **Charles 是"发送即返回"语义**：工具通过 `context.emit_update` 将问题发送到前端，立即返回 `AgentToolResult(output={question, options, status: "已发送问题到前端，等待用户回答"})`；LLM 收到的 tool result 是"已发送"确认字符串，**不是用户答案**。docstring L14-16 明确承认："此工具不真正等待用户回答（那需要挂起机制）"。

这是**实现逻辑层面的语义差异**，不是注释残留。Charles 缺少挂起机制，无法将用户回答回传给 LLM 作为 tool result。

### 2. ExecTool 对比

`ExecTool` 是 Charles 独有的废弃工具，Cline 无对应物（Cline 的命令执行工具是 `run_commands` + `executors/bash.ts`，Charles 的 `RunCommandsTool` 已对标实现）。

- **废弃状态**：`__init__.py` L12 / L30 / L55 / L125 四处标注"已废弃，主 agent 不再注册（保留导入以兼容历史代码）"；`create_default_tools` L86-106 的工具列表中**未实例化** ExecTool，只实例化 `RunCommandsTool`。
- **但仍有残留**：`__init__.py` L30 仍 `from agent.tools.exec_tool import ExecTool`、L125 仍在 `__all__` 中导出、`constants.py` L35-37 仍有 `MAX_COMMAND_OUTPUT_CHARS = 16000` 专用常量、`constants.py` L118 / L132 的 `TOOL_PRESETS` 字典仍引用 `"exec_tool"` key（但 `ExecTool.name = "exec"`，key 与工具名不匹配，该条目实际无效）。
- **对标位置错误**：exec_tool.py L17 标注"对标 Cline sdk/packages/core/src/extensions/tools/executors/bash.ts L291-307"，但 `bash.ts` 是 `RunCommandsTool` 的对标位置，ExecTool 作为单命令工具在 Cline 中无对应物。

### 3. nanobot 残留

- **ask_question.py**：**0 处**残留（无 nanobot 引用）。
- **exec_tool.py**：**12 处**残留，**全部为注释残留**（docstring + 行内注释），**0 处实现逻辑残留**。实现逻辑是标准 Python asyncio（`create_subprocess_shell` + `communicate` + `abort_signal.wait`）+ 通用 regex deny_patterns，非 nanobot 移植。
- **__init__.py**：**1 处**注释残留（L2 docstring "对标 Cline extensions/tools 和 nanobot agent/tools"）。

### 4. 一致性总体评估

- **ask_question**：**中低**。schema 与 lifecycle 对齐，但执行语义根本不同（阻塞等待 vs 发送即返回），导致 LLM 收到的 tool result 性质完全不同。
- **ExecTool**：**不适用**（Cline 无对应物，且工具已废弃）。清理必要性为 P2 级别。

---

## 二、逐项对比表

### 2.1 ask_question 对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.24.1 | 工具名 | `ask_question`（definitions.ts L779） | `ask_question`（ask_question.py L40） | 高 | 完全一致 |
| 3.24.2 | 工具描述 | 英文，含 "Never include an option to toggle to Act mode." 警告（L781-786） | 中文简化版，**缺失 Act mode 警告**（L44-48） | 中 | Charles 缺少关键使用约束提示 |
| 3.24.3 | question 字段 schema | `z.string().min(1)`（schemas.ts L259-264） | `{"type": "string", "minLength": 1}`（L55-59） | 高 | 语义等价 |
| 3.24.4 | options 字段 schema | `z.array(z.string().min(1)).min(2).max(5)`（L265-271） | `{"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 2, "maxItems": 5}`（L60-69） | 高 | 完全一致 |
| 3.24.5 | required 字段 | Zod 推断为 `["question", "options"]` | `["question", "options"]`（L71） | 高 | 完全一致 |
| 3.24.6 | lifecycle / completesRun | **未设置**（createAskQuestionTool 返回对象无 lifecycle 字段，默认不 completesRun） | 返回 `None`（L75-77），注释明确"不是 completes_run" | 高 | 语义一致，提问后不结束运行 |
| 3.24.7 | retryable | `false`（L788） | `False`（继承 BaseTool L82） | 高 | 完全一致 |
| 3.24.8 | maxRetries | `0`（L788） | `0`（继承 BaseTool L87） | 高 | 完全一致 |
| 3.24.9 | timeoutMs | 未设置（默认 30000，由 createTool 工厂注入） | `None`（继承 BaseTool L77） | 中 | Charles 默认无超时 |
| 3.24.10 | 执行语义 | **阻塞等待**：execute 调用 executor 并返回其结果（L791-792） | **发送即返回**：emit_update 后立即返回"已发送"确认（L93-109） | **低** | **根本差异**：Cline 返回用户答案，Charles 返回"已发送" |
| 3.24.11 | executor 抽象 | `AskQuestionExecutor` 由 host 注入（types.ts L149-153），返回 `Promise<string>` | 无 executor，直接用 `context.emit_update` | 低 | Charles 无 DI，UI 交互硬编码 |
| 3.24.12 | UI 交互实现 | 由 host（VS Code 扩展）实现 executor，弹出选项卡片等待用户选择 | 通过 `context.emit_update` 发送 `{type: "ask_question", question, options}` 到前端，不等待 | 低 | Charles 无挂起机制 |
| 3.24.13 | tool result 性质 | 用户选择的选项字符串（如 "Option 2"） | `{question, options, status: "已发送问题到前端，等待用户回答"}` | 低 | LLM 收到的信息完全不同 |
| 3.24.14 | 与 submit_and_exit 互斥 | 是：`if (enableAskQuestion && executors.askQuestion && !submitExecutor)`（L927） | 否：create_default_tools 同时注册两者（L99 / L101） | 中 | Charles 无互斥逻辑 |
| 3.24.15 | enableAskQuestion 开关 | 有（types.ts L287，默认 true） | 无（create_default_tools 无开关，全部注册） | 中 | Charles 无按需装配 |
| 3.24.16 | catalog 条目 | 有（runtime.ts L66-71，headlessToolNames: ["ask_question"]） | 无独立 catalog | 中 | Charles 缺 catalog 层（与 P3.1 结论一致） |
| 3.24.17 | routing 映射 | `ask_question: "enableAskQuestion"`（runtime.ts L110） | `ask_question: True`（constants.py L123 / L137，TOOL_PRESETS 字典） | 中 | 两者都支持 routing 过滤，但机制不同 |
| 3.24.18 | read_only 字段 | 无此字段（Cline 无 read_only 概念） | `True`（L80-81） | — | Charles 独有，Cline 由 toolPolicies 控制 |
| 3.24.19 | 参数校验 | `validateWithZod(AskQuestionInputSchema, input)`（L791） | `jsonschema.Draft7Validator`（继承 BaseTool._validate_input） | 高 | 校验库不同但语义等价 |
| 3.24.20 | metadata | 无（executor 返回纯字符串） | `{"tool": "ask_question", "options_count": len(options)}`（L110-113） | — | Charles 额外附加 metadata |

**ask_question 一致性总评**：20 项中，高一致性 8 项、中一致性 6 项、低一致性 5 项（3.24.10 / 3.24.11 / 3.24.12 / 3.24.13 / 3.24.14 中部分）。**核心差距是执行语义（3.24.10）**：Cline 阻塞等待返回用户答案，Charles 发送即返回"已发送"确认。

### 2.2 ExecTool 状态评估表

| # | 评估项 | 现状 | 清理必要性 |
|---|--------|------|-----------|
| 3.24.21 | 工具是否实例化 | 否（create_default_tools L86-106 未实例化） | — |
| 3.24.22 | 工具是否导入 | 是（__init__.py L30 `from agent.tools.exec_tool import ExecTool`） | P2：可移除导入 |
| 3.24.23 | 工具是否导出 | 是（__init__.py L125 `"ExecTool"` in __all__，标注"已废弃"） | P2：可从 __all__ 移除 |
| 3.24.24 | 是否有专用常量 | 是（constants.py L35-37 `MAX_COMMAND_OUTPUT_CHARS = 16000`） | P2：可移除常量（仅 ExecTool 使用） |
| 3.24.25 | TOOL_PRESETS 引用 | 是（constants.py L118 / L132 `"exec_tool": True`） | P2：可移除条目（key 与工具名 "exec" 不匹配，无效） |
| 3.24.26 | Cline 对标物 | 无（Cline 命令执行工具是 `run_commands`，Charles 已有 `RunCommandsTool` 对标） | — |
| 3.24.27 | docstring 对标位置 | L17 标注"对标 bash.ts L291-307"，实际是 RunCommandsTool 的对标位置 | P2：对标位置错误 |
| 3.24.28 | 文件是否可删除 | 是（271 行，无活跃引用） | P2：可整体删除文件 |

---

## 三、重点差距详细说明

### 差距 1：ask_question 执行语义根本差异（3.24.10 / 3.24.11 / 3.24.12 / 3.24.13）

**这是本阶段最核心的差距，属于实现逻辑层面，非注释残留。**

**Cline 实现**（definitions.ts L789-792 + types.ts L149-153）：

```typescript
// AskQuestionExecutor 类型签名
export type AskQuestionExecutor = (
    question: string,
    options: string[],
    context: AgentToolContext,
) => Promise<string>;

// createAskQuestionTool 的 execute
execute: async (input, context) => {
    const validatedInput = validateWithZod(AskQuestionInputSchema, input);
    return executor(validatedInput.question, validatedInput.options, context);
},
```

`execute` 直接 `return executor(...)`，executor 返回的 `Promise<string>` resolve 后的字符串就是 tool result。executor 由 host 实现（如 VS Code 扩展弹出选项卡片），**阻塞等待用户选择**后才 resolve。测试用例（definitions.test.ts L211-271）明确验证：

```typescript
it("waits for ask_question answers without timing out", async () => {
    let resolveAnswer: (answer: string) => void = () => {};
    const execute = vi.fn(
        () => new Promise<string>((resolve) => { resolveAnswer = resolve; }),
    );
    // ... 创建工具并调用 execute ...
    await vi.advanceTimersByTimeAsync(60_000);  // 推进 60 秒
    expect(settled).toBeUndefined();             // 仍未 settle
    resolveAnswer("Option 2");                   // 模拟用户回答
    await expect(pending).resolves.toBe("Option 2");  // tool result 是用户答案
});
```

**Charles 实现**（ask_question.py L83-114）：

```python
async def _execute(self, input, context):
    question = input["question"]
    options = input["options"]
    if context.emit_update is not None:
        try:
            context.emit_update({
                "type": "ask_question",
                "question": question,
                "options": options,
            })
        except Exception:
            pass
    return AgentToolResult(
        output={
            "question": question,
            "options": options,
            "status": "已发送问题到前端，等待用户回答",
        },
        metadata={"tool": "ask_question", "options_count": len(options)},
    )
```

Charles 的 `_execute` 在 `emit_update` 后立即返回，**不等待用户回答**。LLM 收到的 tool result 是 `{question, options, status: "已发送问题到前端，等待用户回答"}`，而非用户选择的选项。

**影响**：
- Cline 中 LLM 可以基于用户答案继续推理（如用户选 "Option 2"，LLM 知道用户偏好，据此决策）。
- Charles 中 LLM 只知道"问题已发送"，不知道用户选了什么，无法基于用户答案决策。用户回答需要作为新的 user message 进入下一轮对话。
- 两种模式适用于不同场景：Cline 模式适合"工具内挂起"，Charles 模式适合"工具外异步"。

**建议**：不强制对齐。Charles 缺少挂起机制（tool execution suspension），改为阻塞等待需要引入 runtime 层的挂起/恢复机制，改动较大。当前"发送即返回 + 用户回答作为新消息"的模式在量化场景下可工作。若未来需要 LLM 直接获取用户答案，可考虑引入 tool execution suspension 机制。

### 差距 2：ask_question 描述缺失 Act mode 警告（3.24.2）

**Cline 实现**（definitions.ts L780-786）：

```typescript
description:
    "Ask user a question for clarifying or gathering information needed to complete the task. " +
    "For example, ask the user clarifying questions about a key implementation decision. " +
    "You should only ask one question. " +
    "Provide an array of 2-5 options for the user to choose from. " +
    "Never include an option to toggle to Act mode.",
```

最后一句 "Never include an option to toggle to Act mode." 是关键约束，防止 LLM 在选项中混入"切换到 Act 模式"的选项（这会绕过 Plan Mode 的只读约束）。

**Charles 实现**（ask_question.py L44-48）：

```python
return (
    "向用户提问以澄清信息。"
    "参数: question(必填): 问题文本; "
    "options(必填): 2-5 个选项数组"
)
```

Charles 的描述是参数说明式，**缺失三项关键约束**：
1. "You should only ask one question."（每次只问一个问题）
2. "Provide an array of 2-5 options"（虽然 schema 已约束，但描述中未提及）
3. "Never include an option to toggle to Act mode."（防止绕过 Plan Mode）

**影响**：
- Charles 的 Plan Mode（SwitchToActModeTool）有独立切换工具，LLM 不需要通过 ask_question 的选项切换模式，但缺少此约束可能导致 LLM 在选项中混入模式切换内容，造成用户困惑。
- 描述风格差异：Cline 是行为指导式（告诉 LLM 怎么用），Charles 是参数说明式（告诉 LLM 参数格式）。

**建议**：P2 级别。可在描述中补充关键约束，尤其是"每次只问一个问题"和"不要在选项中混入模式切换内容"。

### 差距 3：ask_question 与 submit_and_exit 互斥逻辑缺失（3.24.14）

**Cline 实现**（definitions.ts L927）：

```typescript
// Add ask_question tool if enabled and executor provided
if (enableAskQuestion && executors.askQuestion && !submitExecutor) {
    tools.push(createAskQuestionTool(executors.askQuestion));
}
```

Cline 中 `ask_question` 与 `submit_and_exit` **互斥**：如果 `submit` executor 存在（即启用 submit_and_exit），则不注册 ask_question。测试用例（definitions.test.ts L304-317）明确验证：

```typescript
it("excludes ask_question when submit_and_exit is included", () => {
    const tools = createDefaultTools({
        executors: { askQuestion: async () => "answer", submit: async () => "submitted" },
        enableAskQuestion: true,
        enableSubmitAndExit: true,
    });
    const toolNames = tools.map((tool) => tool.name);
    expect(toolNames).toContain("submit_and_exit");
    expect(toolNames).not.toContain("ask_question");
});
```

**Charles 实现**（__init__.py L99 / L101）：

```python
tools: list[BaseTool] = [
    ...
    AskQuestionTool(),
    ListFilesTool(working_dir=working_dir),
    SubmitAndExitTool(),
    ...
]
```

Charles 同时注册 `AskQuestionTool` 和 `SubmitAndExitTool`，无互斥逻辑。

**影响**：
- Cline 的互斥逻辑源于 `submit_and_exit` 是 `ask_question` 的"最终化"变体（submit 后运行结束，无需再问）。Charles 两者功能不冲突（ask_question 发送即返回，submit_and_exit 是完成任务），同时注册不会产生问题。
- 这是设计选择差异，非缺陷。

**建议**：不强制对齐。Charles 的两个工具语义不冲突，无需互斥。

### 差距 4：ExecTool 废弃但未完全清理（3.24.21 - 3.24.28）

**现状**：ExecTool 已从 `create_default_tools` 中移除（不再实例化），但仍有以下残留：

1. **`__init__.py` L30**：`from agent.tools.exec_tool import ExecTool  # 保留导入以兼容历史代码`
2. **`__init__.py` L125**：`"ExecTool",  # 已废弃，保留导入以兼容历史代码`（__all__ 导出）
3. **`__init__.py` L12 / L55**：docstring 中仍提及 ExecTool
4. **`constants.py` L35-37**：`MAX_COMMAND_OUTPUT_CHARS = 16000`（仅 ExecTool 使用的专用常量）
5. **`constants.py` L118 / L132**：`TOOL_PRESETS` 字典中 `"exec_tool": True`（act / plan 模式）
6. **`exec_tool.py` 文件本身**：271 行代码，已无活跃引用

**TOOL_PRESETS 无效条目**：`ExecTool.name = "exec"`（exec_tool.py L75），但 `TOOL_PRESETS` 的 key 是 `"exec_tool"`（文件名而非工具名），两者不匹配。即便 ExecTool 被注册，routing 层按工具名 `"exec"` 过滤时也查不到 `"exec_tool"` 条目。该条目是历史残留，无效。

**对标位置错误**：exec_tool.py L17 标注"对标 Cline sdk/packages/core/src/extensions/tools/executors/bash.ts L291-307"，但 `bash.ts` 是 Cline `run_commands` 工具的 executor，Charles 的 `RunCommandsTool` 已对标。ExecTool 作为单命令工具在 Cline 中无对应物。

**清理必要性评估**：
- **导入残留**（__init__.py L30 / L125）：保留导入会让人误以为 ExecTool 仍可用，建议移除。但需确认无外部代码 `from agent.tools import ExecTool`。
- **常量残留**（constants.py L35-37）：`MAX_COMMAND_OUTPUT_CHARS` 仅被 exec_tool.py L53 引用，若删除 exec_tool.py 则该常量无引用，可一并删除。
- **TOOL_PRESETS 残留**（constants.py L118 / L132）：`"exec_tool"` key 无效，可移除。
- **文件本身**：271 行废弃代码，无活跃引用，可整体删除。但若担心外部依赖，可保留文件仅移除导入。

**建议**：P2 级别清理。分两步：
1. 移除 `__init__.py` 的导入与 __all__ 导出（L30 / L125），更新 docstring（L12 / L55）。
2. 移除 `constants.py` 的专用常量（L35-37）与 TOOL_PRESETS 无效条目（L118 / L132）。
3. 可选：整体删除 `exec_tool.py` 文件（需确认无外部引用）。

---

## 四、nanobot 残留检查

针对 P3.24 核心文件执行 nanobot 残留扫描，严格区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.24 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/ask_question.py` | **0** | 无 | 无任何 nanobot 引用，对标位置指向 Cline `ask-question-tool.ts`（实际为 definitions.ts） |
| `agent/tools/exec_tool.py` | **12** | 全部注释残留 | docstring + 行内注释，详见 4.2 |
| `agent/tools/__init__.py` | **1** | 注释残留 | L2 docstring：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools` |
| `agent/tools/constants.py` | **0** | 无 | 无 nanobot 引用 |

### 4.2 exec_tool.py nanobot 残留分类

#### 注释残留（12 处，全部为注释）

| 行号 | 内容 | 类型 |
|------|------|------|
| L2 | `"""命令执行工具 — 对标 Cline BashTool + nanobot ShellTool` | docstring |
| L8 | `1. asyncio.create_subprocess_shell 异步执行（对标 nanobot shell.py）` | docstring |
| L9 | `2. deny_patterns 阻止危险命令（对标 nanobot _guard_command）` | docstring |
| L10 | `3. 输出截断防止撑爆上下文（对标 nanobot _MAX_OUTPUT）` | docstring |
| L18 | `对标 nanobot:` | docstring |
| L19 | `- nanobot/agent/tools/shell.py L113-183` | docstring |
| L41 | `"""命令执行工具 — 对标 Cline BashTool + nanobot ShellTool` | 类 docstring |
| L57 | `# 危险命令模式 — 对标 nanobot deny_patterns` | 行内注释 |
| L123 | `# 安全检查 — 对标 nanobot _guard_command` | 行内注释 |
| L165 | `# 组装输出 — 对标 nanobot shell.py L156-168` | 行内注释 |
| L181 | `# 输出截断 — 对标 nanobot shell.py L171-178` | 行内注释 |
| L263 | `"""安全检查 — 对标 nanobot _guard_command` | 方法 docstring |

#### 实现逻辑残留（0 处）

ExecTool 的实现逻辑**无任何从 nanobot 直接移植的代码**：

1. **异步执行**：`asyncio.create_subprocess_shell`（L133-139）是 Python 标准库 API，非 nanobot 特有。
2. **危险命令检查**：`_guard_command`（L262-271）使用 `re.search` 遍历 `_DENY_PATTERNS`（L58-68），是通用的 regex deny-list 模式。nanobot 的 `_guard_command` 也是类似实现，但这是安全工具的通用模式，非 nanobot 独创。
3. **输出截断**：L182-188 的 half+half 截断逻辑是通用截断模式，nanobot 的 `_MAX_OUTPUT` 也是类似实现，但非 nanobot 独创。
4. **abort-aware wait**：`_wait_process_with_abort`（L205-260）是 Phase 2.7 新增，对标 `run_commands._wait_process_with_abort`，使用 `asyncio.wait` + `FIRST_COMPLETED`，是标准 asyncio 模式。
5. **环境变量**：`PYTHONUNBUFFERED=1`（L130）是项目约束，非 nanobot 特有。

### 4.3 残留处理建议

| 文件 | 处理建议 | 优先级 |
|------|---------|--------|
| `ask_question.py` | 无需处理（0 残留） | — |
| `exec_tool.py` | 整体删除文件（已废弃，12 处注释残留随文件删除而消失） | P2 |
| `__init__.py` L2 | 移除 `和 nanobot agent/tools` 段落 | P2（与 P3.1 建议 1 一致） |

**注**：exec_tool.py 的 12 处 nanobot 注释残留无需逐条清理，因为整个文件已废弃，建议整体删除。若暂不删除文件，可保留注释作为历史溯源（不影响运行时行为）。

---

## 五、修复建议

### 建议 1：不强制对齐 ask_question 执行语义 [P3 不修复]

**理由**：
- Cline 的"阻塞等待"语义依赖 host 实现 executor（如 VS Code 扩展 UI），Charles 无 host 层，只有 SSE 前端。
- 改为阻塞等待需要引入 tool execution suspension 机制（runtime 层挂起工具执行、等待前端回传答案、恢复执行），改动涉及 runtime / server / 前端三层，成本较高。
- Charles 当前的"发送即返回 + 用户回答作为新消息"模式在量化场景下可工作（用户回答后作为新的 user message 触发下一轮 LLM 推理）。
- docstring L14-16 已明确说明此设计选择，非疏漏。

**保留条件**：若未来需要 LLM 在工具调用内直接获取用户答案（如多轮澄清对话场景），可考虑引入 suspension 机制。

### 建议 2：补充 ask_question 描述的关键约束 [P2]

**文件**：`agent/tools/ask_question.py`
**位置**：L44-48（description 属性）
**修改方向**：
- 当前：`"向用户提问以澄清信息。参数: question(必填): 问题文本; options(必填): 2-5 个选项数组"`
- 建议补充：
  - "每次只问一个问题"（对标 Cline "You should only ask one question."）
  - "不要在选项中混入模式切换内容"（对标 Cline "Never include an option to toggle to Act mode."）

**理由**：Cline 的描述包含关键使用约束，防止 LLM 滥用工具。Charles 的描述是纯参数说明，缺少行为指导。

### 建议 3：清理 ExecTool 废弃残留 [P2]

**分两步清理**：

**步骤 1：移除 __init__.py 的 ExecTool 导入与导出**
- 文件：`agent/tools/__init__.py`
- 移除 L30：`from agent.tools.exec_tool import ExecTool`
- 移除 L125：`"ExecTool",`（从 __all__ 移除）
- 更新 L12 docstring：移除 `ExecTool: 已废弃...` 行
- 更新 L55 docstring：移除 `（替代 ExecTool）` 段落中的 ExecTool 引用（保留 RunCommandsTool 说明）

**步骤 2：移除 constants.py 的 ExecTool 专用常量与 TOOL_PRESETS 条目**
- 文件：`agent/tools/constants.py`
- 移除 L35-37：`MAX_COMMAND_OUTPUT_CHARS = 16000` 及其注释（仅 ExecTool 使用）
- 移除 L118：`"exec_tool": True,`（TOOL_PRESETS act 模式，key 与工具名 "exec" 不匹配，无效）
- 移除 L132：`"exec_tool": True,`（TOOL_PRESETS plan 模式，同上）

**步骤 3（可选）：整体删除 exec_tool.py 文件**
- 文件：`agent/tools/exec_tool.py`
- 前提：确认无外部代码 `from agent.tools.exec_tool import ExecTool` 或 `from agent.tools import ExecTool`
- 删除后 12 处 nanobot 注释残留随之消失

**理由**：ExecTool 已废弃，RunCommandsTool 已完全替代。保留废弃代码会增加维护负担、混淆新开发者、影响 nanobot 残留统计的清洁度。

### 建议 4：不强制对齐 ask_question 与 submit_and_exit 互斥 [P3 不修复]

**理由**：
- Cline 的互斥逻辑源于 submit_and_exit 是 ask_question 的"最终化"变体。
- Charles 的两个工具语义不冲突（ask_question 发送即返回，submit_and_exit 完成任务），同时注册不会产生问题。
- 强制互斥会限制 Charles 的灵活性。

### 建议 5：保留 ask_question 的 read_only=True 标记 [P0 不变]

**理由**：ask_question 是无副作用工具（仅发送前端通知），`read_only=True` 正确。Cline 无此字段（由 toolPolicies 控制），但 Charles 的显式声明更清晰，应予保留。

---

## 六、验证方法建议

### 验证方法 1：ask_question schema 等价性检查

对比 Cline `AskQuestionInputSchema` 与 Charles `AskQuestionTool.input_schema`，确认字段约束一一对应：

```powershell
# Cline 侧（schemas.ts L258-272）
# question: z.string().min(1)
# options: z.array(z.string().min(1)).min(2).max(5)

# Charles 侧（ask_question.py L52-72）
# question: {type: string, minLength: 1}
# options: {type: array, items: {type: string, minLength: 1}, minItems: 2, maxItems: 5}

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\ask_question.py" -Pattern "minLength|minItems|maxItems|required"
```

**预期**：4 项约束全部存在，与 Cline Zod schema 等价。

### 验证方法 2：ask_question lifecycle 检查

确认 Charles ask_question 的 lifecycle 返回 None（不 completesRun），与 Cline 一致：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\ask_question.py" -Pattern "lifecycle|completes_run"
```

**预期**：L75-77 返回 None，注释标注"不是 completes_run"。

### 验证方法 3：ExecTool 注册状态验证

确认 ExecTool 未在 create_default_tools 中实例化：

```powershell
# 检查 create_default_tools 函数体是否包含 ExecTool 实例化
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\__init__.py" -Pattern "ExecTool\("
```

**预期**：无匹配（ExecTool 未实例化，只有 RunCommandsTool 实例化）。

### 验证方法 4：ExecTool 导入残留检查

确认 __init__.py 仍导入 ExecTool（清理前）或已移除（清理后）：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\__init__.py" -Pattern "ExecTool"
```

**预期（清理前）**：4 处匹配（L12 docstring / L30 import / L55 docstring / L125 __all__）。
**预期（清理后）**：0 处匹配。

### 验证方法 5：TOOL_PRESETS 无效条目验证

确认 TOOL_PRESETS 中 "exec_tool" key 与 ExecTool.name "exec" 不匹配：

```powershell
# 检查 ExecTool 的工具名
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\exec_tool.py" -Pattern 'return "exec"'
# 检查 TOOL_PRESETS 的 key
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern '"exec_tool"'
```

**预期**：ExecTool.name = "exec"，TOOL_PRESETS key = "exec_tool"，两者不匹配，TOOL_PRESETS 条目无效。

### 验证方法 6：nanobot 残留扫描

```powershell
# ask_question.py 应为 0 处
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\ask_question.py" -Pattern "nanobot" -CaseSensitive:$false
# exec_tool.py 应为 12 处（全部注释）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\exec_tool.py" -Pattern "nanobot" -CaseSensitive:$false
# __init__.py 应为 1 处（L2 docstring）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\__init__.py" -Pattern "nanobot" -CaseSensitive:$false
```

### 验证方法 7：Cline ask_question 阻塞等待语义验证

确认 Cline 测试用例验证了 executor 阻塞等待行为：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.test.ts" -Pattern "waits for ask_question answers without timing out"
```

**预期**：L211 匹配，测试用例验证 executor 返回未解决 Promise，60 秒后仍未 settle，直到 resolveAnswer 被调用。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L770-794 | `createAskQuestionTool` 工厂（name / description / inputSchema / retryable / maxRetries / execute） |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L871-933 | `createDefaultTools` 中 ask_question 装配与 submit_and_exit 互斥逻辑 |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L255-272 | `AskQuestionInputSchema` Zod 定义（question + options） |
| `sdk/packages/core/src/extensions/tools/types.ts` | L144-153 | `AskQuestionExecutor` 类型（返回 `Promise<string>`） |
| `sdk/packages/core/src/extensions/tools/types.ts` | L209-217 | `DefaultExecutors` 中 `askQuestion?` 字段 |
| `sdk/packages/core/src/extensions/tools/types.ts` | L279-287 | `enableAskQuestion` 开关（默认 true） |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L66-71 | `ask_question` catalog 条目（headlessToolNames） |
| `sdk/packages/core/src/extensions/tools/runtime.ts` | L110 | `TOOL_NAME_TO_FLAG` 映射 `ask_question: "enableAskQuestion"` |
| `sdk/packages/core/src/extensions/tools/constants.ts` | L20 | `ASK: "ask_question"` 常量 |
| `sdk/packages/core/src/extensions/tools/definitions.test.ts` | L127-145 | ask_question 默认启用 / 禁用测试 |
| `sdk/packages/core/src/extensions/tools/definitions.test.ts` | L147-165 | ask_question 需要 executor 才注册测试 |
| `sdk/packages/core/src/extensions/tools/definitions.test.ts` | L167-209 | ask_question 输入校验与执行测试 |
| `sdk/packages/core/src/extensions/tools/definitions.test.ts` | L211-271 | ask_question 阻塞等待用户回答测试（关键语义验证） |
| `sdk/packages/core/src/extensions/tools/definitions.test.ts` | L304-317 | ask_question 与 submit_and_exit 互斥测试 |
| `sdk/packages/core/src/extensions/tools/model-tool-routing.ts` | L45 / L56 | routing 映射 `enableAskQuestion` / `ask_question` |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/ask_question.py` | L1-20 | 模块 docstring（对标 Cline createAskQuestionTool，说明"不真正等待用户回答"） |
| `agent/tools/ask_question.py` | L30-36 | `AskQuestionTool` 类 docstring |
| `agent/tools/ask_question.py` | L38-48 | `name` / `description` 属性 |
| `agent/tools/ask_question.py` | L50-72 | `input_schema` 属性（question + options） |
| `agent/tools/ask_question.py` | L74-81 | `lifecycle`（返回 None）/ `read_only`（返回 True）属性 |
| `agent/tools/ask_question.py` | L83-114 | `_execute` 方法（emit_update + 立即返回"已发送"确认） |
| `agent/tools/exec_tool.py` | L1-20 | 模块 docstring（标注对标 Cline BashTool + nanobot ShellTool） |
| `agent/tools/exec_tool.py` | L40-68 | `ExecTool` 类定义 + `_DENY_PATTERNS` 危险命令模式 |
| `agent/tools/exec_tool.py` | L70-108 | `__init__` / `name` / `description` / `input_schema` |
| `agent/tools/exec_tool.py` | L114-203 | `_execute` 方法（asyncio + abort + 截断） |
| `agent/tools/exec_tool.py` | L205-260 | `_wait_process_with_abort` 方法（Phase 2.7 新增） |
| `agent/tools/exec_tool.py` | L262-271 | `_guard_command` 方法（regex deny-list） |
| `agent/tools/__init__.py` | L12 / L30 / L55 / L125 | ExecTool 废弃标注与导入/导出残留 |
| `agent/tools/__init__.py` | L99 | `AskQuestionTool()` 实例化 |
| `agent/tools/constants.py` | L35-37 | `MAX_COMMAND_OUTPUT_CHARS = 16000`（ExecTool 专用常量） |
| `agent/tools/constants.py` | L112-140 | `TOOL_PRESETS` 字典（含无效 `"exec_tool"` 条目） |

---

## 八、结论

P3.24 ask_question / exec_tool 对比的核心结论：

### 8.1 ask_question 结论

1. **schema 完全对齐**：question / options 的类型、约束（minLength / minItems / maxItems）、required 字段在两侧完全一致。
2. **lifecycle 对齐**：两侧都不 `completesRun`，ask_question 后不结束运行。
3. **retryable / maxRetries 对齐**：两侧都是 false / 0，不重试。
4. **执行语义根本差异**（核心差距）：Cline 阻塞等待用户回答，tool result 是用户答案；Charles 发送即返回，tool result 是"已发送"确认。这是实现逻辑层面差异，非注释残留。Charles 缺少挂起机制，改为阻塞等待成本较高，建议不强制对齐。
5. **描述缺失关键约束**：Charles 缺少 "Never include an option to toggle to Act mode." 等行为指导，建议 P2 级别补充。
6. **无 nanobot 残留**：ask_question.py 是清洁文件，0 处残留。

### 8.2 ExecTool 结论

1. **已废弃，Cline 无对应物**：Cline 的命令执行工具是 `run_commands`，Charles 的 `RunCommandsTool` 已对标实现。ExecTool 是单命令工具，已废弃。
2. **未完全清理**：虽未在 `create_default_tools` 中实例化，但 `__init__.py` 仍导入/导出、`constants.py` 仍有专用常量与无效 TOOL_PRESETS 条目、文件本身 271 行废弃代码仍存在。
3. **12 处 nanobot 注释残留**：全部为注释（docstring + 行内注释），0 处实现逻辑残留。实现逻辑是标准 Python asyncio + 通用安全模式，非 nanobot 移植。
4. **对标位置错误**：docstring 标注"对标 bash.ts"，实际是 RunCommandsTool 的对标位置。
5. **清理必要性 P2**：建议分步清理（移除导入/导出 → 移除常量/TOOL_PRESETS → 可选删除文件）。

### 8.3 整体一致性等级

- **ask_question**：**中低**。schema / lifecycle / retry 对齐，但执行语义根本不同。
- **ExecTool**：**不适用**（Cline 无对应物，工具已废弃）。
- **nanobot 残留**：ask_question.py 清洁（0 处）；exec_tool.py 12 处注释残留（随文件删除可消除）；__init__.py 1 处注释残留（与 P3.1 结论一致）。

### 8.4 阻塞性问题

**无阻塞性问题**。ask_question 的语义差异是已知设计选择（docstring 已说明），不影响现有功能；ExecTool 已废弃不参与运行。所有修复建议均为 P2 级别，可在后续清理批次中统一处理。
