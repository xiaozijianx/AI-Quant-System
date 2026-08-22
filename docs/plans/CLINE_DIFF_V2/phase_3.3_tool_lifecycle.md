# Phase 3.3 ToolLifecycle 与 completes_run 对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在 `ToolLifecycle` 字段定义、`completes_run` 标注工具清单、`completes_run` 检查算法、命中后行为、默认值处理六个维度，对应 AGENT_COMPARISON_PLAN_V2.md P3.3 章节定义的 6 个对比项。

总体结论：Charles 已将 Cline 的"ToolLifecycle + completes_run"核心语义对齐到字段级与方法级，`ToolLifecycle` 字段结构、`completes_run` 检测算法、命中后 `finish_run("completed")` 行为均与 Cline 等价。但存在三处需要关注的分歧：

1. **计划文档与实际代码不符（blocking 字段）**：AGENT_COMPARISON_PLAN_V2.md P3.3 表格列出 `blocking` 字段对比项（3.3.4 / 3.3.5），称 Cline 有 `blocking` 字段、Charles 缺失。**经核对 Cline 实际源码（agent.ts L150-156），ToolLifecycle 接口只有 `completesRun?: boolean` 一个字段，没有 `blocking` 字段**。Cline 全 sdk 包内搜索 `blocking?:` / `ToolLifecycle` 均无匹配，仅在文档/注释中有 `blocking` 一词的非字段用法（如 skills 工具描述"blocking requirement"、telemetry 注释"blocking deactivation"）。计划文档关于 blocking 字段的描述与 Cline 实际代码不符，本报告以实际源码为准。
2. **completes_run 工具清单差异**：Charles 标记 4 个工具为 `completes_run=True`（`submit_and_exit` / `attempt_completion` / `switch_to_act_mode` / `switch_to_plan_mode`），Cline 仅标记 2 个（`submit_and_exit` / `switch_to_act_mode`）。Charles 多出 `attempt_completion`（Cline 中是历史遗留工具名，被映射到 `submit_and_exit`）和 `switch_to_plan_mode`（Cline 中不存在此工具）。
3. **lifecycle 字段位置差异**：Cline 将 `lifecycle` 内联定义在 `AgentToolDefinition` 接口中（agent.ts L150-156），是 `AgentToolDefinition` 的可选字段；Charles 将 `ToolLifecycle` 作为独立 dataclass（types.py L155-162），同时被 `AgentToolDefinition`（L174）和 `AgentTool` Protocol（L233）持有。两者语义等价，但 Charles 的独立 dataclass 更利于复用与测试。

`nanobot` 残留检查结论：在 P3.3 重点文件（`agent/types.py`、`agent/tools/base.py`、`agent/tools/__init__.py`、`agent/tools/submit_and_exit.py`、`agent/tools/attempt_completion.py`、`agent/tools/plan_mode.py`、`agent/tools/ask_question.py`、`agent/runtime.py` 中 lifecycle 相关方法）**未发现** `nanobot` 字符串残留（注释与实现均无）。`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标说明，与 P2.4 / P2.5 报告结论一致，不影响 ToolLifecycle 与 completes_run 的实现逻辑。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P3.3 章节定义的 6 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 3.3.1 | completes_run 字段 | `agent.ts` L150-156（`AgentToolDefinition.lifecycle?: { completesRun?: boolean }`，内联匿名对象，单字段） | `types.py` L155-162（`@dataclass class ToolLifecycle { completes_run: bool = False }`，独立 dataclass，单字段） | 字段语义一致；实现形式不同（Cline 内联匿名类型 vs Charles 独立 dataclass）；命名风格不同（camelCase vs snake_case）；Charles 独立 dataclass 更利于复用与类型推导 | 已对齐 |
| 3.3.2 | completes_run 触发条件 | `agent-runtime.ts` L1316-1330（`findCompletingToolMessage`：遍历 toolCalls，`this.tools.get(toolName)?.lifecycle?.completesRun !== true` 跳过，找 `part.type === "tool-result" && part.toolCallId === toolCall.toolCallId && !result.isError` 返回） | `runtime.py` L2048-2074（`_find_completing_tool`：遍历 tool_calls，`tool is None` 跳过，`lifecycle is None or not lifecycle.completes_run` 跳过，`i >= len(tool_messages)` 跳过，找 `isinstance(part, ToolResultPart) && part.tool_call_id == tool_call.tool_call_id && not part.is_error` 返回） | 算法等价：均按 tool_calls 顺序遍历，跳过非 completesRun 工具，找匹配 tool_call_id 且非 error 的 tool_result 返回对应 tool_message。Charles 多 2 处显式边界检查（`tool is None` / `i >= len(tool_messages)`），Cline 用 `?.` 链式安全访问隐式处理；Cline 用 `Array.find` 查找 part，Charles 用 for 循环 | 已对齐 |
| 3.3.3 | completes_run 后 status | `agent-runtime.ts` L722-738（`findCompletingToolMessage` 返回非空 → `finishRun("completed", finalAssistantMessage, textFromToolMessage(terminalToolMessage) \|\| undefined)` → `callAfterRunHooks(result)` → emit `run-finished` → return result） | `runtime.py` L740-747（`_find_completing_tool` 返回非空 → `_finish_run("completed", final_assistant_message, output_text)` → `_call_after_run_hooks(result)` → emit `make_run_finished` → return result） | 完全对齐：status 同为 `"completed"`，均调用 after_run hooks，均 emit run-finished，均 return result；output_text 提取方式等价（`textFromToolMessage` vs `text_from_tool_message`） | 已对齐 |
| 3.3.4 | blocking 字段 | **Cline 实际源码无此字段**（`agent.ts` L150-156 的 lifecycle 接口仅含 `completesRun?: boolean`；全 sdk 包 grep `blocking\??:` / `ToolLifecycle` 均无匹配） | 无 | 计划文档 P3.3 表格称"Cline 有 blocking 字段、Charles 缺失"，**与 Cline 实际源码不符**。Cline 的 ToolLifecycle 只有 `completesRun` 一个字段。本项无对比对象 | 计划文档错误 |
| 3.3.5 | blocking 用途 | N/A（Cline 实际无 blocking 字段） | N/A | 计划文档称"UI 阻塞提示"，实际 Cline 源码中 `blocking` 一词仅出现在 skills 工具描述（"blocking requirement"，非字段）和 telemetry 注释（"blocking deactivation"，非字段）。本项无对比对象 | 计划文档错误 |
| 3.3.6 | lifecycle 默认值 | `agent.ts` L150（`lifecycle?: {...}` 整个 lifecycle 字段可选，未声明时为 `undefined`）；`agent-runtime.ts` L1318 用 `?.lifecycle?.completesRun !== true` 隐式处理 undefined（undefined !== true → 跳过，等价于默认不完成） | `types.py` L162（`completes_run: bool = False`）；`base.py` L71-73（`lifecycle` 属性默认返回 `None`）；`runtime.py` L2063-2064（`lifecycle is None or not lifecycle.completes_run` 显式处理 None） | 语义等价：未声明 lifecycle 时均视为"不完成运行"。实现形式不同：Cline 用可选字段 + `?.` 链式访问；Charles 用 `None` 默认值 + 显式 `is None` 检查 | 已对齐 |

## 3. completes_run 标注工具清单对比

### 3.1 Cline 标注清单（共 2 个工具）

| 工具名 | 位置 | lifecycle 配置 | 注册条件 |
|--------|------|---------------|---------|
| `submit_and_exit` | `sdk/packages/core/src/extensions/tools/definitions.ts` L812-814 | `lifecycle: { completesRun: true }` | 默认注册（`createDefaultTools` 工厂，需传 `submitExecutor`） |
| `switch_to_act_mode` | `apps/vscode/src/sdk/sdk-session-config-builder.ts` L68-70 | `lifecycle: { completesRun: true }` | 仅 plan 模式注册（L38-41：`input.mode === "plan"` 时 `extraTools` 追加此工具；act 模式时 filter 移除） |

补充说明：
- Cline 中 `attempt_completion` 不是独立工具，而是历史遗留工具名，在 `runtime-builder.ts` L88 被映射到 `submit_and_exit`：`attempt_completion: "submit_and_exit"`（别名映射表）。
- Cline 中**不存在** `switch_to_plan_mode` 工具。`apps/cli` 和 `apps/vscode` 中 grep `switch_to_plan_mode` 均无匹配。
- Cline 中 `ask_question`（definitions.ts L776-795）**未**标注 `lifecycle.completesRun`，即 `completesRun` 为 `undefined`，不结束运行。Charles 的 `ask_question.py` L74-77 显式返回 `None`，行为等价。

### 3.2 Charles 标注清单（共 4 个工具）

| 工具名 | 位置 | lifecycle 配置 | 注册条件 |
|--------|------|---------------|---------|
| `submit_and_exit` | `agent/tools/submit_and_exit.py` L72-78 | `ToolLifecycle(completes_run=True)` | 默认注册（`create_default_tools` L101） |
| `attempt_completion` | `agent/tools/attempt_completion.py` L67-74 | `ToolLifecycle(completes_run=True)` | **主 agent 不注册**，仅子 agent 注册（docstring L39 明确"仅注册到子 agent"） |
| `switch_to_act_mode` | `agent/tools/plan_mode.py` L103-110 | `ToolLifecycle(completes_run=True)` | 始终注册（`create_default_tools` L109），运行时由 `tool_policies` 按模式控制可用性 |
| `switch_to_plan_mode` | `agent/tools/plan_mode.py` L207-213 | `ToolLifecycle(completes_run=True)` | 始终注册（`create_default_tools` L110），运行时由 `tool_policies` 按模式控制可用性 |

### 3.3 工具清单差异分析

| 工具名 | Cline | Charles | 差异性质 |
|--------|-------|---------|---------|
| `submit_and_exit` | 是（completesRun=true） | 是（completes_run=True） | 已对齐 |
| `switch_to_act_mode` | 是（completesRun=true，仅 plan 模式注册） | 是（completes_run=True，始终注册 + tool_policies 控制） | 注册策略不同但语义等价：Cline 用"plan 模式追加、act 模式 filter 移除"，Charles 用"始终注册 + tool_policies 按模式禁用" |
| `attempt_completion` | **否**（历史别名，映射到 `submit_and_exit`） | **是**（completes_run=True，仅子 agent 注册） | Charles 多出：Charles 保留了 `attempt_completion` 作为独立工具用于子 agent 场景；Cline 已将其合并到 `submit_and_exit` |
| `switch_to_plan_mode` | **否**（Cline 中不存在此工具） | **是**（completes_run=True） | Charles 多出：Charles 支持从 Act 模式切换回 Plan 模式；Cline 仅支持 plan → act 单向切换（`switch_to_act_mode`） |
| `ask_question` | 否（无 lifecycle） | 否（显式返回 None） | 已对齐 |

## 4. 重点差距详细说明

### 4.1 计划文档与实际代码不符：blocking 字段（对应对比项 3.3.4 / 3.3.5）

- **计划文档描述**：AGENT_COMPARISON_PLAN_V2.md P3.3 章节（L706-720）称 Cline 的 ToolLifecycle 为 `{ completesRun: boolean, blocking?: boolean }`，包含 `blocking` 字段，并列举对比项 3.3.4（blocking 字段：Cline 有 / Charles 无）和 3.3.5（blocking 用途：UI 阻塞提示 / N/A）。
- **Cline 实际源码**：
  - `sdk/packages/shared/src/agent.ts` L150-156：
    ```typescript
    export interface AgentToolDefinition {
        name: string;
        description: string;
        inputSchema: Record<string, unknown>;
        lifecycle?: {
            /** Whether a successful call to this tool completes the current run. */
            completesRun?: boolean;
        };
    }
    ```
    仅含 `completesRun?: boolean` 一个字段，**无 `blocking` 字段**。
  - 全 sdk 包 grep `blocking\??:`（字段定义语法）无任何匹配。
  - 全 sdk 包 grep `ToolLifecycle`（类型名）无任何匹配（Cline 未定义名为 `ToolLifecycle` 的独立类型，lifecycle 是内联匿名对象）。
  - sdk 包内 `blocking` 一词仅出现在非字段上下文：
    - `definitions.ts` L730：skills 工具描述文本"blocking requirement"（语义为"必须先调用"，非字段）。
    - `OpenTelemetryProvider.ts` L421/L454：telemetry 注释"blocking deactivation"（语义为"阻塞停用"，非字段）。
    - 多处 README/文档中的通用英语单词"blocking"。
- **结论**：计划文档关于 `blocking` 字段的描述与 Cline 实际源码不符。Cline 的 ToolLifecycle 实际只有 `completesRun` 一个字段。本报告以实际源码为准，对比项 3.3.4 / 3.3.5 标注为"计划文档错误"。
- **残留性质**：非残留，属于计划文档编写时的信息错误（可能基于早期 Cline 版本或假设）。

### 4.2 completes_run 工具清单差异：Charles 多出 attempt_completion 和 switch_to_plan_mode（对应第 3 节）

- **Cline 设计**：
  - `submit_and_exit`：唯一的主 agent 完成工具，对标 Cline 历史的 `attempt_completion`（`runtime-builder.ts` L88 别名映射）。
  - `switch_to_act_mode`：唯一的模式切换完成工具，仅 plan 模式注册（`sdk-session-config-builder.ts` L38-45）。
  - Cline 不支持 act → plan 反向切换（无 `switch_to_plan_mode` 工具）。
- **Charles 设计**：
  - `submit_and_exit`：主 agent 完成工具（对标 Cline）。
  - `attempt_completion`：**独立工具**，仅子 agent 注册（`attempt_completion.py` L39 docstring 明确"仅注册到子 agent，主 agent 不注册"）。Charles 保留了 Cline 已合并的历史工具名作为子 agent 专用。
  - `switch_to_act_mode` + `switch_to_plan_mode`：**双向切换**，均始终注册，由 `tool_policies` 按当前模式控制可用性（plan 模式下 `switch_to_act_mode` 可用，act 模式下 `switch_to_plan_mode` 可用）。
- **影响**：
  1. 工具数量：Charles 主 agent 注册 3 个 completesRun 工具（`submit_and_exit` + `switch_to_act_mode` + `switch_to_plan_mode`），Cline 主 agent 注册 1-2 个（`submit_and_exit` 总是注册 + `switch_to_act_mode` 仅 plan 模式注册）。
  2. 子 agent 工具：Charles 子 agent 注册 `attempt_completion`（1 个 completesRun 工具），Cline 子 agent 用 `submit_and_exit`（与主 agent 共用）。
  3. 多工具场景：Charles 的 `_find_completing_tool_name`（runtime.py L2308-2321）多个时取第一个，与 Cline `getRequiredCompletionToolNames`（agent-runtime.ts L557-565）sort 后列全部不同（详见 P2.5 报告 3.2 节）。
- **残留性质**：`attempt_completion` 是 Charles 主动保留的历史工具名（Cline 已合并但 Charles 选择保留作为子 agent 专用），属于设计决策而非残留。`switch_to_plan_mode` 是 Charles 主动扩展的双向切换能力，Cline 不支持。

### 4.3 lifecycle 字段位置差异：内联 vs 独立 dataclass（对应对比项 3.3.1）

- **Cline 设计**：`lifecycle` 内联定义在 `AgentToolDefinition` 接口中（agent.ts L150-156），是 `AgentToolDefinition` 的可选字段。`AgentTool` 接口（L177-186）`extends AgentToolDefinition`，继承 `lifecycle` 字段。无独立 `ToolLifecycle` 类型。
  - 优点：类型定义集中，减少类型数量。
  - 缺点：lifecycle 结构无法独立复用（如作为函数参数、变量类型时需重复内联匿名结构）。
- **Charles 设计**：`ToolLifecycle` 作为独立 `@dataclass`（types.py L155-162），被 `AgentToolDefinition`（L174）和 `AgentTool` Protocol（L233）引用。`BaseTool` 基类（base.py L70-73）提供 `lifecycle` 属性默认返回 `None`。
  - 优点：独立 dataclass 利于复用、测试、类型推导；`BaseTool` 子类只需覆盖 `lifecycle` 属性返回 `ToolLifecycle(completes_run=True)` 即可，无需重写 `to_definition()`。
  - 缺点：多一层类型嵌套（`tool.lifecycle.completes_run` vs Cline 的 `tool.lifecycle?.completesRun`）。
- **影响**：语义等价，仅实现形式不同。Charles 的独立 dataclass 更符合 Python OOP 风格，Cline 的内联定义更符合 TypeScript 函数式风格。
- **残留性质**：非残留，属于语言风格差异。

## 5. completes_run 检查逻辑详细对比

### 5.1 Cline `findCompletingToolMessage`（agent-runtime.ts L1312-1332）

```typescript
private findCompletingToolMessage(
    toolCalls: AgentToolCallPart[],
    toolMessages: AgentMessage[],
): AgentMessage | undefined {
    for (let index = 0; index < toolCalls.length; index += 1) {
        const toolCall = toolCalls[index];
        if (this.tools.get(toolCall.toolName)?.lifecycle?.completesRun !== true) {
            continue;
        }
        const toolMessage = toolMessages[index];
        const result = toolMessage?.content.find(
            (part): part is Extract<AgentMessagePart, { type: "tool-result" }> =>
                part.type === "tool-result" &&
                part.toolCallId === toolCall.toolCallId,
        );
        if (result && !result.isError) {
            return toolMessage;
        }
    }
    return undefined;
}
```

### 5.2 Charles `_find_completing_tool`（runtime.py L2048-2074）

```python
def _find_completing_tool(
    self,
    tool_calls: list[ToolCallPart],
    tool_messages: list[AgentMessage],
) -> AgentMessage | None:
    """检查是否有 completes_run 工具成功执行

    对标 Cline findCompletingToolMessage()。
    如果工具的 lifecycle.completes_run=True 且执行成功（非 error），
    则返回对应的 tool message，AgentRuntime 据此结束运行。
    """
    for i, tool_call in enumerate(tool_calls):
        tool = self._tools.get(tool_call.tool_name)
        if tool is None:
            continue
        lifecycle = getattr(tool, "lifecycle", None)
        if lifecycle is None or not lifecycle.completes_run:
            continue

        if i >= len(tool_messages):
            continue
        tool_message = tool_messages[i]
        for part in tool_message.content:
            if isinstance(part, ToolResultPart):
                if part.tool_call_id == tool_call.tool_call_id and not part.is_error:
                    return tool_message
    return None
```

### 5.3 算法等价性分析

| 步骤 | Cline | Charles | 等价性 |
|------|-------|---------|--------|
| 1. 遍历 tool_calls | `for (let index = 0; ...)` | `for i, tool_call in enumerate(tool_calls)` | 等价 |
| 2. 取工具定义 | `this.tools.get(toolCall.toolName)` | `self._tools.get(tool_call.tool_name)` | 等价（Map vs dict） |
| 3. 工具不存在处理 | `?.lifecycle?.completesRun !== true` 隐式跳过（undefined !== true → continue） | `if tool is None: continue` 显式跳过 + `getattr(tool, "lifecycle", None)` 防御 | Charles 多一层显式检查，语义等价 |
| 4. lifecycle 不存在处理 | `?.lifecycle?.completesRun !== true` 隐式跳过 | `if lifecycle is None or not lifecycle.completes_run: continue` 显式跳过 | 等价 |
| 5. completesRun 为 false 处理 | `!== true` 跳过 | `not lifecycle.completes_run` 跳过 | 等价 |
| 6. tool_messages 越界处理 | `toolMessages[index]` 返回 `undefined`，后续 `?.content.find` 安全跳过 | `if i >= len(tool_messages): continue` 显式跳过 | 等价（Cline 隐式 / Charles 显式） |
| 7. 查找 tool_result part | `toolMessage?.content.find(part => part.type === "tool-result" && part.toolCallId === toolCall.toolCallId)` | `for part in tool_message.content: if isinstance(part, ToolResultPart) and part.tool_call_id == tool_call.tool_call_id` | 等价（Array.find vs for 循环） |
| 8. is_error 检查 | `if (result && !result.isError)` | `if part.tool_call_id == ... and not part.is_error` | 等价 |
| 9. 返回值 | `return toolMessage`（返回整个 tool message） | `return tool_message`（返回整个 tool message） | 等价 |
| 10. 未找到返回 | `return undefined` | `return None` | 等价 |

**结论**：算法完全等价，仅边界检查风格不同（Cline 隐式 `?.` 链式 vs Charles 显式 `is None` / `i >= len` 检查）。

## 6. completes_run 命中后行为详细对比

### 6.1 Cline 命中后行为（agent-runtime.ts L722-738）

```typescript
const terminalToolMessage = this.findCompletingToolMessage(
    toolCalls,
    toolMessages,
);
if (terminalToolMessage) {
    const result = this.finishRun(
        "completed",
        finalAssistantMessage,
        textFromToolMessage(terminalToolMessage) || undefined,
    );
    await this.callAfterRunHooks(result);
    await this.emit({
        type: "run-finished",
        snapshot: this.snapshot(),
        result,
    });
    return result;
}
```

### 6.2 Charles 命中后行为（runtime.py L740-747）

```python
# 检查 completes_run 工具
completing_message = self._find_completing_tool(tool_calls, tool_messages)
if completing_message is not None:
    output_text = text_from_tool_message(completing_message) or None
    result = self._finish_run("completed", final_assistant_message, output_text)
    await self._call_after_run_hooks(result)
    await self._emit(make_run_finished(self.snapshot(), result))
    return result
```

### 6.3 行为等价性分析

| 步骤 | Cline | Charles | 等价性 |
|------|-------|---------|--------|
| 1. 检测完成工具 | `findCompletingToolMessage(toolCalls, toolMessages)` | `_find_completing_tool(tool_calls, tool_messages)` | 等价（见第 5 节） |
| 2. 提取 output_text | `textFromToolMessage(terminalToolMessage) \|\| undefined` | `text_from_tool_message(completing_message) or None` | 等价（`\|\|` vs `or`，空字符串转 undefined/None） |
| 3. finishRun 状态 | `"completed"` | `"completed"` | 等价 |
| 4. finishRun 参数 | `(status, finalAssistantMessage, outputText)` | `(status, final_assistant_message, output_text)` | 等价 |
| 5. 调用 after_run hooks | `await this.callAfterRunHooks(result)` | `await self._call_after_run_hooks(result)` | 等价 |
| 6. emit run-finished | `await this.emit({ type: "run-finished", snapshot, result })` | `await self._emit(make_run_finished(self.snapshot(), result))` | 等价（直接对象 vs 工厂函数） |
| 7. return result | `return result` | `return result` | 等价 |

**结论**：命中后行为完全对齐，status 同为 `"completed"`，均调用 after_run hooks，均 emit run-finished，均 return result。

## 7. nanobot 残留检查

### 检查范围

P3.3 重点文件为：
- `agent/types.py`（ToolLifecycle dataclass 定义）
- `agent/tools/base.py`（BaseTool.lifecycle 属性）
- `agent/tools/__init__.py`（工具注册工厂）
- `agent/tools/submit_and_exit.py` / `attempt_completion.py` / `plan_mode.py` / `ask_question.py`（lifecycle 配置）
- `agent/runtime.py`（`_find_completing_tool` / `_find_completing_tool_name` / `_inject_completion_reminder` / `_build_completion_reminder` 方法）

### 重点文件检查结论

| 文件 | 残留性质 | 是否影响 ToolLifecycle / completes_run 实现 |
|------|---------|-------------------------------------------|
| `agent/types.py` | **无残留** | 不适用 |
| `agent/tools/base.py` | **无残留** | 不适用 |
| `agent/tools/__init__.py` L2 | docstring 标题对标说明（"对标 Cline extensions/tools 和 nanobot agent/tools"） | 否（注释） |
| `agent/tools/submit_and_exit.py` | **无残留** | 不适用 |
| `agent/tools/attempt_completion.py` | **无残留** | 不适用 |
| `agent/tools/plan_mode.py` | **无残留** | 不适用 |
| `agent/tools/ask_question.py` | **无残留** | 不适用 |
| `agent/runtime.py`（lifecycle 相关方法） | **无残留** | 不适用 |

`agent/tools/__init__.py` L2 的 docstring 标题"对标 Cline extensions/tools 和 nanobot agent/tools"是历史对标说明（注释），不影响 ToolLifecycle 与 completes_run 的实现逻辑。其余 P3.3 重点文件 grep `nanobot` 均无任何匹配，`ToolLifecycle` dataclass、`BaseTool.lifecycle` 属性、各工具的 `lifecycle` 属性实现、`_find_completing_tool` / `_find_completing_tool_name` / `_inject_completion_reminder` / `_build_completion_reminder` 等核心方法均无 nanobot 命名或 nanobot 风格逻辑。

### 其他文件残留（与 P2.4 / P2.5 报告一致，仅供完整性参考）

`agent/` 其他文件的 nanobot 残留全部为注释/docstring 层面的历史对标说明，不影响 P3.3 对比项的实现逻辑：

| 文件 | 残留性质 | 是否影响 ToolLifecycle / completes_run |
|------|---------|---------------------------------------|
| `agent/tools/exec_tool.py` L2-263 | 多处 docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | 多处 docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | 多处 docstring 对标 nanobot WebSearchTool | 否（注释） |
| `agent/skills/loader.py` / `registry.py` | 多处 docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/providers/qwen.py` L21-406 | 多处 docstring 对标 nanobot openai_compat_provider | 否（注释） |
| `agent/server.py` L2-28 | docstring 对标 nanobot routes/chat.py | 否（注释） |
| `agent/session.py` L2-22 | docstring 对标 nanobot session_key | 否（注释） |
| `agent/context.py` L275 | 注释标注"[已废弃] nanobot 风格的额外段落" | 否（注释） |

> 注：上述残留全部为注释/docstring 性质，**无实现逻辑残留**。ToolLifecycle 与 completes_run 的核心方法（`ToolLifecycle` / `BaseTool.lifecycle` / 各工具 `lifecycle` 属性 / `_find_completing_tool` / `_find_completing_tool_name` / `_inject_completion_reminder` / `_build_completion_reminder` / `_finish_run`）均无 nanobot 命名或 nanobot 风格逻辑。

### 注释残留 vs 实现逻辑残留区分

- **注释残留**：docstring 中引用 `nanobot xxx` 作为历史来源标注（如"对标 nanobot SkillsLoader"），不影响代码运行时行为。P3.3 重点文件中仅 `agent/tools/__init__.py` L2 有 1 处此类残留（docstring 标题），其余重点文件无残留。
- **实现逻辑残留**：代码中直接移植 nanobot 的类名、方法名、数据结构或控制流。P3.3 重点文件 **未发现** 任何实现逻辑残留，所有实现均基于 Cline 对标设计。

## 8. 修复建议

### P0（计划文档修正）

1. **修正 AGENT_COMPARISON_PLAN_V2.md P3.3 章节的 blocking 字段描述**：计划文档 L706 称 Cline ToolLifecycle 为 `{ completesRun: boolean, blocking?: boolean }`，L719-720 列出对比项 3.3.4（blocking 字段）和 3.3.5（blocking 用途）。**实际 Cline 源码（agent.ts L150-156）只有 `completesRun?: boolean` 一个字段，无 `blocking` 字段**。建议修正计划文档：
   - 删除对比项 3.3.4 和 3.3.5，或标注为"计划文档错误，Cline 实际无此字段"。
   - 修正 L706 的 Cline ToolLifecycle 描述为 `{ completesRun?: boolean }`。
   - **影响**：消除计划文档与实际源码的分歧，避免后续工作基于错误信息。
   - **风险**：无，仅文档修正。

### P1（功能对齐）

2. **评估 attempt_completion 工具的必要性**：Charles 保留了 `attempt_completion` 作为子 agent 专用工具（`attempt_completion.py`），Cline 已将其合并到 `submit_and_exit`（runtime-builder.ts L88 别名映射）。建议二选一：
   - 方案 A（对齐 Cline）：移除 `attempt_completion` 工具，子 agent 也用 `submit_and_exit`。
   - 方案 B（保留 Charles 设计）：在 `attempt_completion.py` docstring 中明确标注"Charles 主动保留：子 agent 专用，Cline 已合并到 submit_and_exit"，避免未来对齐时误删。
   - **推荐**：方案 B，因为 Charles 的子 agent 设计与 Cline 的 spawn_agent 模式不同，保留 `attempt_completion` 有语义价值（"尝试完成"vs"提交并退出"）。
   - **影响**：仅文档澄清，无代码变更。
   - **风险**：无。

3. **评估 switch_to_plan_mode 工具的必要性**：Charles 支持 act → plan 反向切换（`switch_to_plan_mode`），Cline 不支持。建议在 `plan_mode.py` docstring 中明确标注"Charles 主动扩展：Cline 仅支持 plan → act 单向切换，Charles 扩展为双向切换"，避免未来对齐时误删。
   - **影响**：仅文档澄清，无代码变更。
   - **风险**：无。

### P2（可选，注释清理）

4. **清理 agent/tools/__init__.py 的 nanobot 注释残留**：`__init__.py` L2 的 docstring 标题"对标 Cline extensions/tools 和 nanobot agent/tools"是历史对标说明，建议改为"对标 Cline extensions/tools"或直接删除"和 nanobot agent/tools"部分。此项与 P2.4 / P2.5 报告建议一致，非 P3.3 新增问题。

## 9. 验证方法建议

1. **blocking 字段不存在验证**：在 Cline sdk 包内执行 `grep -r "blocking\?\:" sdk/packages/`，预期无任何字段定义匹配；执行 `grep -r "ToolLifecycle" sdk/packages/`，预期无任何类型名匹配（Cline 用内联匿名对象，无独立 ToolLifecycle 类型）。

2. **completes_run 工具清单验证**：在 Cline sdk 包内执行 `grep -rn "completesRun: true" sdk/ apps/`，预期仅 2 处匹配：
   - `sdk/packages/core/src/extensions/tools/definitions.ts` L813（`submit_and_exit`）
   - `apps/vscode/src/sdk/sdk-session-config-builder.ts` L69（`switch_to_act_mode`）
   在 Charles `agent/` 内执行 `grep -rn "completes_run=True" agent/tools/`，预期 4 处匹配：
   - `submit_and_exit.py` L78
   - `attempt_completion.py` L74
   - `plan_mode.py` L110 / L213

3. **completes_run 命中后 status 验证**：构造 LLM 第一轮调用 `submit_and_exit`（`completes_run=True`）工具且执行成功的场景，运行 agent：
   - 两边预期：`status="completed"`，`run-finished` 事件发射，`output_text` 为 tool result 文本，`after_run` hooks 调用。
   - 验证点：对比 `AgentRunResult.status` / `output_text` / `iterations` 字段值。

4. **completes_run 失败不结束验证**：构造 LLM 调用 `submit_and_exit` 但工具执行返回 `is_error=True` 的场景：
   - 两边预期：`findCompletingToolMessage` / `_find_completing_tool` 返回 None/undefined，运行继续下一轮。
   - 验证点：确认 `is_error=True` 时不会误触发 finishRun。

5. **lifecycle 默认值验证**：构造一个未声明 `lifecycle` 的工具（如 `ask_question`），运行 agent 调用该工具：
   - 两边预期：工具执行成功后运行不结束，继续下一轮。
   - 验证点：确认 `lifecycle` 为 undefined/None 时 `completesRun` / `completes_run` 视为 false。

6. **switch_to_act_mode 注册策略验证**：
   - Cline：plan 模式启动时 `extraTools` 含 `switch_to_act_mode`，act 模式启动时 `extraTools` 不含（filter 移除）。
   - Charles：两种模式启动时 `tools` 列表都含 `switch_to_act_mode` 和 `switch_to_plan_mode`，由 `tool_policies` 按当前模式控制可用性（plan 模式下 `switch_to_plan_mode` 被禁用，act 模式下 `switch_to_act_mode` 被禁用）。
   - 验证点：对比两种注册策略下 LLM 可见的工具列表是否等价。

7. **nanobot 残留回归**：运行 `grep -r "nanobot" agent/types.py agent/tools/base.py agent/tools/submit_and_exit.py agent/tools/attempt_completion.py agent/tools/plan_mode.py agent/tools/ask_question.py agent/runtime.py` 确认重点文件无残留（`__init__.py` L2 的 1 处注释除外）。
