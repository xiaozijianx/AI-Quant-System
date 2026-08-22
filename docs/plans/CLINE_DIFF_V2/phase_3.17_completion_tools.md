# Phase 3.17 attempt_completion / submit_and_exit 实现对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在 `submit_and_exit` 与 `attempt_completion` 两个"任务完成类工具"上的输入 schema、`completes_run` 行为、结果格式、用户交互、注册策略与工具间关系六个维度，对应 AGENT_COMPARISON_PLAN_V2.md P3.17 章节定义的对比项。

总体结论：Charles 的 `submit_and_exit` 与 Cline 在 schema 字段层基本对齐（`summary` + `verified`），但 `attempt_completion` 在两侧**语义完全不同**，且 Charles 的 `attempt_completion` 实际是**未注册的死代码**，存在三处需要关注的分歧：

1. **`attempt_completion` 语义分歧（关键）**：
   - **Cline** 中 `attempt_completion` 不是独立工具，而是 `submit_and_exit` 的**历史别名**（`runtime-builder.ts` L88 别名映射表 `attempt_completion: "submit_and_exit"`）。Cline 另在 VSCode host 中保留了一个**非 completesRun** 的 `attempt_completion` 工具（`vscode-runtime-builder.ts` L65-116），用于"向用户展示结果 + 可选执行 showcase 命令（如开 dev server）+ 接收用户反馈"，**与 Charles 的 completesRun=True 子 agent 终止工具毫无关系**。
   - **Charles** 中 `attempt_completion` 是独立工具类（`attempt_completion.py`），`completes_run=True`，docstring 声称"仅注册到子 agent，主 agent 不注册"。但 Charles **没有任何子 agent 生成机制**（无 `spawn_agent` 工具、无 `use_skill` 创建子 runtime 的逻辑），且 `create_default_tools`（`tools/__init__.py` L48-112）**未导入也未注册** `AttemptCompletionTool`。该类是**死代码**。

2. **结果格式分歧**：Charles `submit_and_exit` 返回结构化 dict（`{summary, verified, status}` + `metadata`）；Cline `submit_and_exit` 通过 `VerifySubmitExecutor` 返回**纯字符串**（CLI 实现为 `"Submission recorded (verified/unverified): {summary}"`）。Charles `attempt_completion` 返回**纯字符串**（`output=result_text`）。两侧 `output` 类型不统一。

3. **超时与重试配置分歧**：Cline `submit_and_exit` 显式配置 `timeoutMs`（默认 15000ms，可用 `submitTimeoutMs` 覆盖）+ `retryable: false` + `maxRetries: 0` + `withTimeout` 包装；Charles 两个工具均**未覆盖** `timeout_ms` / `retryable` / `max_retries`（继承 `BaseTool` 默认值 None / False / 0），无超时包装。

4. **`ask_question` 互斥策略分歧**：Cline 在 `createDefaultTools`（definitions.ts L927-933）规定 **`submit_and_exit` 与 `ask_question` 互斥**——当 `submitExecutor` 存在时，`ask_question` 不注册；Charles 同时注册 `AskQuestionTool` 与 `SubmitAndExitTool`（`tools/__init__.py` L99-101），**无互斥逻辑**。

5. **`read_only` 标记分歧**：Charles `submit_and_exit` 显式 `read_only = False`（注释自称"终止性工具，不修改文件，标记为 False 以符合规范"，自相矛盾）；Charles `attempt_completion` `read_only = True`。Cline 两侧均无 `read_only` 字段（Cline 用 `toolPolicies` 控制）。Charles `submit_and_exit` 的 `read_only=False` 注释逻辑不能成立——它不修改任何文件，应当为 `True`。

`nanobot` 残留检查结论：P3.17 两个重点文件（`agent/tools/submit_and_exit.py`、`agent/tools/attempt_completion.py`）**未发现** 任何 `nanobot` 字符串（注释与实现均无）。`agent/` 其他文件的 nanobot 残留均为注释/docstring 层面的历史对标说明，与 P2.4 / P2.5 / P3.3 报告结论一致，不影响完成类工具的实现逻辑。

---

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P3.17 章节定义的对比项列出：

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.17.1 | `submit_and_exit` 输入字段 | `summary: string (min 10)` + `verified: boolean`（schemas.ts L274-286 `SubmitInputSchema`） | `summary: string (minLength 10)` + `verified: boolean`（submit_and_exit.py L54-69） | 高 | 字段名、类型、长度约束完全对齐；Charles 用 JSON Schema `minLength`，Cline 用 Zod `.min(10)` |
| 3.17.2 | `submit_and_exit` completes_run | `lifecycle: { completesRun: true }`（definitions.ts L812-814） | `ToolLifecycle(completes_run=True)`（submit_and_exit.py L72-78） | 高 | 完全对齐 |
| 3.17.3 | `submit_and_exit` 结果格式 | executor 返回**纯字符串**（`VerifySubmitExecutor: (summary, verified, context) => Promise<string>`，CLI 实现 `"Submission recorded (verified/unverified): {summary}"`） | 返回**结构化 dict** `AgentToolResult(output={summary, verified, status:"任务完成"}, metadata={tool, completed, verified})` | 低 | 类型与字段完全不同；Charles 多了 `status` / `metadata`，Cline 仅返回字符串 |
| 3.17.4 | `submit_and_exit` 超时配置 | `timeoutMs: 15000`（默认，可由 `submitTimeoutMs` 覆盖）+ `withTimeout` 包装（definitions.ts L801, L815-825） | 未覆盖 `timeout_ms`（继承 BaseTool 默认 None） | 低 | Charles 无超时控制 |
| 3.17.5 | `submit_and_exit` 重试配置 | `retryable: false` + `maxRetries: 0`（definitions.ts L816-817） | 继承 BaseTool 默认 `retryable=False` + `max_retries=0` | 高 | 行为等价（Charles 是继承默认值，Cline 是显式声明） |
| 3.17.6 | `submit_and_exit` 与 `ask_question` 互斥 | 是（definitions.ts L927: `if (enableAskQuestion && executors.askQuestion && !submitExecutor)`，submit 存在时 ask 不注册） | 否（tools/__init__.py L99-101 同时注册 AskQuestionTool + SubmitAndExitTool） | 低 | Charles 无互斥逻辑，两个工具可同时被 LLM 调用 |
| 3.17.7 | `submit_and_exit` 注册条件 | `enableSubmitAndExit: false`（默认不启用，types.ts L289-293），需显式开启 + 提供 `submit` executor | 默认注册（tools/__init__.py L101 无条件 `SubmitAndExitTool()`） | 中 | Cline 默认关闭，Charles 默认开启 |
| 3.17.8 | `submit_and_exit` read_only | 无此字段（Cline 用 `toolPolicies.enabled` / `autoApprove` 控制） | `read_only = False`（submit_and_exit.py L80-83，注释自相矛盾） | 低 | Charles 标记为可写但实际不写文件，注释逻辑不能成立 |
| 3.17.9 | `attempt_completion` 是否独立工具 | **否**——是 `submit_and_exit` 的别名（runtime-builder.ts L88 `attempt_completion: "submit_and_exit"`）；VSCode host 另有独立的非 completesRun 工具（vscode-runtime-builder.ts L65-116） | **是**（attempt_completion.py 独立类，completes_run=True） | 低 | 两侧语义完全不同：Cline 是别名/展示工具，Charles 是子 agent 终止工具 |
| 3.17.10 | `attempt_completion` 输入字段 | VSCode 版：`result: string (required)` + `command: string (optional)`（vscode-runtime-builder.ts L71-86） | `result: string (required)`（attempt_completion.py L54-65） | 中 | Charles 缺少 `command` 参数（showcase 命令） |
| 3.17.11 | `attempt_completion` completes_run | **否**（VSCode 版无 `lifecycle` 字段；别名版继承 `submit_and_exit` 的 completesRun） | **是**（attempt_completion.py L67-74 `ToolLifecycle(completes_run=True)`） | 低 | Charles 显式标记 completesRun，Cline VSCode 版未标记 |
| 3.17.12 | `attempt_completion` 注册状态 | VSCode host 注册（vscode-runtime-builder.ts L152 `createAttemptCompletionTool`）；CLI 不注册；别名版由 `submit_and_exit` 间接覆盖 | **死代码**——`AttemptCompletionTool` 类未被 `tools/__init__.py` 导入，未被 `create_default_tools` 注册，无任何子 agent 机制调用 | 低 | Charles 类存在但完全未使用 |
| 3.17.13 | `attempt_completion` 结果格式 | VSCode 版返回**字符串**（`resultText` 或 `resultText + "\n\n[Command: ...]\n" + output`） | 返回**字符串** `AgentToolResult(output=result_text, metadata={tool, completed})` | 中 | output 类型一致（字符串），Charles 多 metadata |
| 3.17.14 | `attempt_completion` 用户交互 | "用户可提供反馈，agent 据此改进重试"（vscode-runtime-builder.ts L69-70 description） | 无用户交互（一次性 completesRun 终止） | 低 | Cline 支持反馈循环，Charles 是单向终止 |
| 3.17.15 | 子 agent 完成机制 | `spawn_agent` 工具（spawn-agent-tool.ts L117-202）：子 agent `subAgent.run(task)` 自然结束，父 agent 通过 `result.text` 拿到结果，**子 agent 无需调用任何 completesRun 工具** | **无子 agent 机制**——`spawn_agent` 工具不存在（Phase 27 移除），`use_skill` 工具不创建子 runtime（skill_tool.py L18-22 明确"不创建子 agent"） | 低 | Charles 无对应场景；`attempt_completion` 的"子 agent 终止"设计无落地对象 |
| 3.17.16 | `completes_run` 检测算法 | `findCompletingToolMessage`（agent-runtime.ts L1312-1332）：遍历 tool_calls → 检查 `lifecycle?.completesRun === true` → 找匹配 `toolCallId` 且 `!isError` 的 tool-result | `_find_completing_tool`（runtime.py L2048-2074）：遍历 tool_calls → 检查 `lifecycle.completes_run` → 找匹配 `tool_call_id` 且 `not is_error` 的 ToolResultPart | 高 | 算法完全对齐（详见 P3.3 报告第 5 节） |
| 3.17.17 | `completes_run` 命中后 status | `"completed"` + `callAfterRunHooks` + emit `run-finished` + return result（agent-runtime.ts L722-738） | `"completed"` + `_call_after_run_hooks` + emit `make_run_finished` + return result（runtime.py L740-747） | 高 | 完全对齐（详见 P3.3 报告第 6 节） |
| 3.17.18 | 完成工具数量（主 agent） | 1 个（`submit_and_exit`，条件注册）+ 别名 `attempt_completion` 映射 | 1 个（`submit_and_exit`，无条件注册）+ 0 个（`attempt_completion` 未注册） | 中 | Charles 主 agent 实际可用完成工具数与 Cline 等价（1 个） |
| 3.17.19 | 是否需要两个类似工具 | **否**——Cline 已将 `attempt_completion` 合并为 `submit_and_exit` 别名 | **声称是**（attempt_completion.py docstring "仅子 agent"）但**实际无子 agent 机制**，两个工具未并存使用 | 低 | Charles 的"两个工具"设计在当前架构下无意义 |

**一致性总评**：19 项中，高一致性 6 项（3.17.1 / 3.17.2 / 3.17.5 / 3.17.16 / 3.17.17 / 3.17.18）、中一致性 4 项、低一致性 9 项。低一致性集中在 `attempt_completion` 语义、结果格式、超时配置、互斥策略、子 agent 机制五个方面。

---

## 3. 重点差距详细说明

### 3.1 差距 1：`attempt_completion` 语义分歧（对应 3.17.9 / 3.17.11 / 3.17.12 / 3.17.15）

这是本次对比最关键的分歧，需要逐层拆解 Cline 中 `attempt_completion` 的三重身份：

#### 3.1.1 Cline 的 `attempt_completion` 三重身份

**身份 A：历史别名（sdk 层）**

`sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L86-93 定义了工具名别名映射表：

```typescript
const CONFIGURED_AGENT_TOOL_NAME_ALIASES: Record<string, string> = {
    apply_diff: "editor",
    attempt_completion: "submit_and_exit",
    bash: "run_commands",
    execute_command: "run_commands",
    list_code_definition_names: "search_codebase",
    list_files: "run_commands",
    read_file: "read_files",
    // ...
};
```

当 LLM 调用 `attempt_completion` 时，Cline runtime 会将其**透明重映射**为 `submit_and_exit`，复用同一工具定义与 executor。这是 Cline 为兼容旧版 prompt / 旧版 agent 配置而保留的兼容层。**此身份下 `attempt_completion` 不是独立工具**。

**身份 B：VSCode host 的展示工具（apps 层）**

`apps/vscode/src/sdk/vscode-runtime-builder.ts` L65-116 定义了一个**独立的** `attempt_completion` 工具：

```typescript
function createAttemptCompletionTool(options: { cwd?: string } = {}): AgentTool {
    return createTool({
        name: "attempt_completion",
        description:
            "Once you've completed the user's task, use this tool to present the result to the user. " +
            "The user may provide feedback if they are not satisfied, which you can use to make improvements and try again.",
        inputSchema: {
            type: "object",
            properties: {
                result: { type: "string", description: "A clear, brief summary of the final result of the task." },
                command: { type: "string", description: "An optional terminal command to showcase the result (e.g. open a dev server)." },
            },
            required: ["result"],
        },
        execute: async (input, context) => {
            // ... 可选执行 command，返回 resultText + command output
        },
    });
}
```

关键特征：
- **无 `lifecycle` 字段**（即 `completesRun` 为 `undefined`，**不结束运行**）
- 输入含 `command` 可选参数（用于执行 showcase 命令，如 `open a dev server`）
- description 明确"用户可提供反馈，agent 据此改进重试"——是**反馈循环**工具，不是终止工具
- 在 `createVscodeExtraTools`（L152）中与 MCP 工具一同注册

**身份 C：CLI 不注册**

`apps/cli/src/runtime/run-agent.ts` L164-167 的 `toolExecutors` 只提供 `askQuestion` 和 `submit`，**不注册** `attempt_completion`。CLI 模式下 `attempt_completion` 仅作为别名映射到 `submit_and_exit`（身份 A）。

#### 3.1.2 Charles 的 `attempt_completion` 单一身份

`agent/tools/attempt_completion.py` L33-95 定义了 `AttemptCompletionTool`：

```python
class AttemptCompletionTool(BaseTool):
    """子 agent 完成工具 — 对标 Cline attempt_completion

    lifecycle.completes_run = True
    子 agent 调用此工具返回最终结果，runtime 检测到 completes_run 后结束运行。

    仅注册到子 agent，主 agent 不注册。
    """
```

关键特征：
- `completes_run=True`（终止性工具）
- 输入仅 `result`（无 `command` 参数）
- docstring 声称"仅注册到子 agent"，但 Charles **无子 agent 机制**：
  - `agent/tools/__init__.py` 的 `create_default_tools` **未导入** `AttemptCompletionTool`
  - `agent/runtime.py` grep `sub_agent|subagent|spawn|use_skill|delegat` **无任何匹配**
  - `agent/skills/skill_tool.py` L18-22 明确"不创建子 agent"、"不用 attempt_completion 返回结果"
  - 全 `agent/` 目录 grep `AttemptCompletionTool` 仅在 `attempt_completion.py` 自身、`todo_write.py`（提示文本）、`runtime.py`（reminder 文本）、`types.py`（docstring）、`approval_policy.py`（工具名集合）、`skills/loader.py`（frontmatter 示例）、`skills/skill_tool.py`（注释）中出现，**无任何 `import` 或实例化语句**

结论：Charles 的 `AttemptCompletionTool` 是**完全未注册、未实例化、未调用的死代码**。其 docstring 描述的"子 agent 终止"场景在当前架构下不存在。

#### 3.1.3 分歧性质

| 维度 | Cline | Charles | 分歧性质 |
|------|-------|---------|---------|
| 是否独立工具 | 否（别名）+ 是（VSCode 展示工具） | 是（独立类） | 设计分歧 |
| completesRun | 别名版继承 true / VSCode 版 false | true | 语义分歧 |
| 用途 | 别名版=submit_and_exit / VSCode 版=展示+反馈 | 子 agent 终止（无落地） | 用途分歧 |
| 输入字段 | VSCode 版有 command 参数 | 无 command 参数 | schema 分歧 |
| 注册状态 | VSCode 注册 / CLI 别名映射 | **未注册** | 实现差距 |

**残留性质**：Charles 的 `attempt_completion` 不是 nanobot 残留，而是基于"Cline 有 attempt_completion 工具"的**误读**设计的死代码。Cline 的 `attempt_completion` 在 sdk 层只是别名，在 VSCode 层是展示工具，均非 Charles 所设想的"子 agent 终止工具"。

### 3.2 差距 2：`submit_and_exit` 结果格式分歧（对应 3.17.3）

#### 3.2.1 Cline 结果格式

Cline `submit_and_exit` 的结果由 `VerifySubmitExecutor` 决定（types.ts L189-193）：

```typescript
export type VerifySubmitExecutor = (
    summary: string,
    verified: boolean,
    context: AgentToolContext,
) => Promise<string>;
```

返回**纯字符串**。CLI 实现（`apps/cli/src/utils/approval.ts` L162-167）：

```typescript
export async function submitAndExitInTerminal(
    summary: string,
    verified: boolean,
): Promise<string> {
    const status = verified ? "verified" : "unverified";
    return `Submission recorded (${status}): ${summary}`;
}
```

工具的 `output` 字段就是该字符串，runtime 通过 `textFromToolMessage` 提取后作为 `AgentRunResult.outputText` 返回。

#### 3.2.2 Charles 结果格式

Charles `submit_and_exit`（submit_and_exit.py L85-105）：

```python
async def _execute(self, input, context) -> AgentToolResult:
    summary = input["summary"]
    verified = input["verified"]
    return AgentToolResult(
        output={
            "summary": summary,
            "verified": verified,
            "status": "任务完成",
        },
        metadata={
            "tool": "submit_and_exit",
            "completed": True,
            "verified": verified,
        },
    )
```

返回**结构化 dict**，含 `summary` / `verified` / `status` 三个键 + `metadata` 四个键。

#### 3.2.3 分歧影响

- **runtime 提取 output_text 的行为差异**：Charles runtime 通过 `text_from_tool_message(completing_message)` 提取 output_text。若 `AgentToolResult.output` 是 dict，`text_from_tool_message` 的提取行为决定 `AgentRunResult.output_text` 的最终值（可能是 `str(dict)` 或空字符串，取决于 `text_from_tool_message` 实现）。Cline 直接是字符串，提取无歧义。
- **LLM 可见性差异**：Cline 的 tool-result 内容是 `"Submission recorded (verified): ..."` 自然语言，LLM 在下一轮（若有）能直接读懂；Charles 的 tool-result 内容是 JSON dict，LLM 需解析。
- **一致性等级**：低。

### 3.3 差距 3：超时与重试配置分歧（对应 3.17.4 / 3.17.5）

#### 3.3.1 Cline 配置

`submit_and_exit`（definitions.ts L797-826）显式配置：

```typescript
const timeoutMs = config.submitTimeoutMs ?? 15000;
return createTool<SubmitInput, string>({
    // ...
    lifecycle: { completesRun: true },
    timeoutMs,
    retryable: false,
    maxRetries: 0,
    execute: async (input, context) => {
        const validatedInput = validateWithZod(SubmitInputSchema, input);
        return withTimeout(
            executor(validatedInput.summary, validatedInput.verified, context),
            timeoutMs,
            `submit_and_exit timed out after ${timeoutMs}ms`,
        );
    },
});
```

- `timeoutMs` 默认 15000ms，可通过 `config.submitTimeoutMs` 覆盖
- 用 `withTimeout` 包装 executor 调用，超时抛错
- `retryable: false` + `maxRetries: 0` 显式声明不重试

#### 3.3.2 Charles 配置

Charles `SubmitAndExitTool`（submit_and_exit.py）**未覆盖** `timeout_ms` / `retryable` / `max_retries`，继承 `BaseTool` 默认值（base.py L75-88）：

```python
@property
def timeout_ms(self) -> int | None:
    """超时毫秒数 — None 表示由 AgentRuntime 控制"""
    return None

@property
def retryable(self) -> bool:
    return False

@property
def max_retries(self) -> int:
    return 0
```

- `timeout_ms = None`：无工具级超时，由 AgentRuntime 全局控制
- 无 `withTimeout` 等价包装
- `retryable = False` + `max_retries = 0`：行为等价（继承默认值）

#### 3.3.3 分歧影响

- Cline 有工具级 15s 超时保护，Charles 依赖 runtime 全局超时（若存在）。若 executor 挂起（如 CLI 的 `submitAndExitInTerminal` 等待用户输入），Cline 会在 15s 后超时，Charles 可能永久挂起。
- 一致性等级：低（超时）/ 高（重试）。

### 3.4 差距 4：`ask_question` 互斥策略分歧（对应 3.17.6）

#### 3.4.1 Cline 互斥逻辑

`createDefaultTools`（definitions.ts L924-934）：

```typescript
const submitExecutor = enableSubmitAndExit ? executors.submit : undefined;

// Add ask_question tool if enabled and executor provided
if (enableAskQuestion && executors.askQuestion && !submitExecutor) {
    tools.push(createAskQuestionTool(executors.askQuestion));
}

// Add submit_and_exit tool if enabled and executor provided
if (submitExecutor) {
    tools.push(createSubmitAndExitTool(submitExecutor, config));
}
```

关键条件：`!submitExecutor`——当 `submit` executor 存在时，`ask_question` **不注册**。设计意图：`submit_and_exit` 本身就是"提交并退出"的终态工具，无需再问用户问题；反之 `ask_question` 模式下用户可连续提问，不希望 LLM 提前 submit。

#### 3.4.2 Charles 无互斥逻辑

`create_default_tools`（tools/__init__.py L86-106）：

```python
tools: list[BaseTool] = [
    # ...
    AskQuestionTool(),
    ListFilesTool(working_dir=working_dir),
    SubmitAndExitTool(),
    # ...
]
```

两个工具**同时无条件注册**，LLM 可在同一轮中先调用 `ask_question` 再调用 `submit_and_exit`，或在 `submit_and_exit` 后（若 runtime 未结束）继续 `ask_question`。

#### 3.4.3 分歧影响

- LLM 工具列表不同：Cline 在 submit 模式下 LLM 看不到 `ask_question`，Charles 总能看到两个。
- 行为差异：Cline 强制"要么问要么提交"，Charles 允许"先问后提交"。
- 一致性等级：低。

### 3.5 差距 5：`read_only` 标记分歧（对应 3.17.8）

#### 3.5.1 Charles 的 `read_only` 标记

`submit_and_exit.py` L80-83：

```python
@property
def read_only(self) -> bool:
    # 终止性工具，不修改文件，标记为 False 以符合规范
    return False
```

注释自称"不修改文件"却返回 `False`，逻辑自相矛盾。`attempt_completion.py` L76-78 则返回 `True`：

```python
@property
def read_only(self) -> bool:
    return True
```

两个完成类工具的 `read_only` 标记不一致。

#### 3.5.2 Cline 的处理

Cline 无 `read_only` 字段，工具的可用性与审批性由 `toolPolicies`（per-tool `enabled` / `autoApprove`）控制，`submit_and_exit` 在 `approval_policy.ts` 中默认行为由 host 决定。

#### 3.5.3 分歧影响

- Charles `submit_and_exit` 的 `read_only=False` 会导致该工具在 approval_policy 中被归入"写入类工具"（如 `WRITE_TOOLS` 集合），可能触发不必要的用户审批。但实际查看 `approval_policy.py` L37-47，`submit_and_exit` 在 `READ_ONLY_TOOLS` 集合中（自动批准），未受 `read_only` 属性影响。
- 一致性等级：低（属性标记与实际行为不符）。

---

## 4. 是否需要两个类似工具的评估

### 4.1 Cline 的答案：否

Cline 通过三种方式处理"任务完成"场景，**不存在两个功能重叠的 completesRun 工具**：

| 场景 | Cline 工具 | completesRun | 说明 |
|------|-----------|--------------|------|
| 主 agent 提交最终答案并退出 | `submit_and_exit` | true | 唯一的终止性提交工具 |
| 主 agent 向用户展示结果 + 接收反馈 | `attempt_completion`（VSCode） | false | 非终止，支持反馈循环 |
| 旧版配置兼容 | `attempt_completion`（别名） | 继承 submit_and_exit | 透明映射，非独立工具 |
| 子 agent 完成任务 | `spawn_agent` 自然结束 | N/A | 子 agent run 结束即返回，无需调用完成工具 |

Cline 的设计哲学：**终止性工具只有一个**（`submit_and_exit`），其他"完成类"工具要么是别名要么是非终止的展示工具。

### 4.2 Charles 的答案：声称是，实际否

Charles docstring 声称需要两个工具：

| 场景 | Charles 工具 | completesRun | 实际状态 |
|------|-----------|--------------|---------|
| 主 agent 提交最终答案并退出 | `submit_and_exit` | true | 已注册，可用 |
| 子 agent 完成任务返回结果给主 agent | `attempt_completion` | true | **未注册，死代码** |

Charles 的设计意图：主 agent 用 `submit_and_exit`，子 agent 用 `attempt_completion`，语义区分"提交并退出"vs"尝试完成"。

但 Charles **无子 agent 机制**（无 `spawn_agent`，`use_skill` 不创建子 runtime），`attempt_completion` 的设计场景不存在。两个工具未并存使用，实际可用完成工具只有 `submit_and_exit` 一个。

### 4.3 评估结论

| 评估维度 | 结论 |
|---------|------|
| 功能重叠度 | 高（两个工具都是 completesRun=True 的终止性工具） |
| 输入字段差异度 | 中（submit: summary+verified / attempt: result） |
| 结果格式差异度 | 高（submit: dict / attempt: string） |
| 实际并存使用 | 否（attempt_completion 未注册） |
| 是否需要两个 | **当前架构下不需要**——Charles 无子 agent 机制，attempt_completion 是死代码 |
| 未来若引入子 agent | 可考虑保留 attempt_completion 作为子 agent 专用，但需对齐 Cline 的 `spawn_agent` 自然结束模式（子 agent 无需 completesRun 工具，run 结束即返回） |

**推荐方案**（详见第 6 节修复建议）：
- 方案 A（对齐 Cline）：移除 `attempt_completion.py`，主 agent 唯一完成工具为 `submit_and_exit`。
- 方案 B（保留设计）：在 `attempt_completion.py` docstring 顶部明确标注"当前为预留死代码，待子 agent 机制引入后激活"，并从 `approval_policy.READ_ONLY_TOOLS` / `todo_write.py` 提示文本 / `runtime.py` reminder 文本中移除对 `attempt_completion` 的引用，避免误导。

---

## 5. nanobot 残留检查

### 5.1 检查范围

P3.17 重点文件：
- `agent/tools/submit_and_exit.py`
- `agent/tools/attempt_completion.py`
- `agent/runtime.py`（`_find_completing_tool` / `_find_completing_tool_name` / `_inject_completion_reminder` 方法，completes_run 检测段）
- `agent/types.py`（`ToolLifecycle` dataclass，含 attempt_completion / submit_and_exit 引用的 docstring）
- `agent/tools/__init__.py`（工具注册工厂）
- `agent/approval_policy.py`（READ_ONLY_TOOLS 含两个工具名）
- `agent/tools/todo_write.py`（提示文本引用 attempt_completion）

### 5.2 重点文件检查结论

| 文件 | 残留性质 | 是否影响完成类工具实现 |
|------|---------|----------------------|
| `agent/tools/submit_and_exit.py` | **无残留** | 不适用 |
| `agent/tools/attempt_completion.py` | **无残留** | 不适用 |
| `agent/runtime.py`（completes_run 段） | **无残留** | 不适用 |
| `agent/types.py`（ToolLifecycle 段） | **无残留** | 不适用 |
| `agent/tools/__init__.py` L2 | docstring 标题"对标 Cline extensions/tools 和 nanobot agent/tools" | 否（注释） |
| `agent/approval_policy.py` | **无残留** | 不适用 |
| `agent/tools/todo_write.py` | **无残留** | 不适用 |

### 5.3 其他文件残留（与 P2.4 / P2.5 / P3.3 报告一致，仅供完整性参考）

`agent/` 其他文件的 nanobot 残留全部为注释/docstring 层面的历史对标说明，不影响 P3.17 对比项的实现逻辑：

| 文件 | 残留性质 | 是否影响完成类工具 |
|------|---------|------------------|
| `agent/tools/exec_tool.py` L2-263 | docstring 对标 nanobot ShellTool | 否（注释） |
| `agent/tools/file_tools.py` L2-165 | docstring 对标 nanobot FilesystemTool | 否（注释） |
| `agent/tools/web_tool.py` L2-165 | docstring 对标 nanobot WebSearchTool | 否（注释） |
| `agent/skills/loader.py` / `registry.py` / `__init__.py` / `skill_tool.py` | docstring 对标 nanobot SkillsLoader | 否（注释） |
| `agent/providers/qwen.py` L21-406 | docstring 对标 nanobot openai_compat_provider | 否（注释） |
| `agent/server.py` L2-28 | docstring 对标 nanobot routes/chat.py | 否（注释） |
| `agent/session.py` L2-22 | docstring 对标 nanobot session_key | 否（注释） |
| `agent/context.py` L275 | 注释"[已废弃] nanobot 风格的额外段落" | 否（注释） |

### 5.4 注释残留 vs 实现逻辑残留区分

- **注释残留**：docstring 中引用 `nanobot xxx` 作为历史来源标注（如"对标 nanobot SkillsLoader"），不影响代码运行时行为。P3.17 重点文件中仅 `agent/tools/__init__.py` L2 有 1 处此类残留（docstring 标题），其余重点文件无残留。
- **实现逻辑残留**：代码中直接移植 nanobot 的类名、方法名、数据结构或控制流。P3.17 重点文件 **未发现** 任何实现逻辑残留，所有实现均基于 Cline 对标设计（尽管 `attempt_completion` 的对标存在误读，但属于设计分歧而非 nanobot 逻辑残留）。

---

## 6. 修复建议

### P0（关键，死代码清理）

1. **处理 `attempt_completion` 死代码**：`agent/tools/attempt_completion.py` 的 `AttemptCompletionTool` 类未被任何模块导入或注册，是死代码。建议二选一：
   - **方案 A（对齐 Cline，推荐）**：删除 `agent/tools/attempt_completion.py` 文件，同时清理以下引用：
     - `agent/approval_policy.py` L42 `"attempt_completion"` 从 `READ_ONLY_TOOLS` 集合移除
     - `agent/tools/todo_write.py` L189 提示文本"可以调用 attempt_completion 或直接回复用户"改为"可以调用 submit_and_exit 或直接回复用户"
     - `agent/runtime.py` L2362 reminder 文本"你必须调用完成工具（如 attempt_completion 或 submit_and_exit）"改为"你必须调用完成工具（submit_and_exit）"
     - `agent/types.py` L160 / L496-497 docstring 中"attempt_completion / submit_and_exit"改为"submit_and_exit"
     - `agent/skills/loader.py` L19 frontmatter 示例 `allowed_tools` 列表中移除 `attempt_completion`
     - `agent/skills/skill_tool.py` L22 注释"不用 attempt_completion 返回结果"可保留作为历史说明，或改为"不创建子 agent，不调用终止性工具"
   - **方案 B（保留设计）**：保留文件，但在 docstring 顶部添加显著标注"当前为预留死代码，待子 agent 机制引入后激活"，并从 `approval_policy.READ_ONLY_TOOLS` 移除该工具名（避免未注册工具出现在策略集合中造成误导）。
   - **推荐方案 A**：Charles 当前无子 agent 机制（Phase 27 已移除 `spawn_agent`），保留 `attempt_completion` 无实际价值，反而造成"两个完成工具"的认知混淆。
   - **影响**：清理死代码，消除认知混淆。
   - **风险**：无（类未被任何代码引用）。

### P1（功能对齐）

2. **统一 `submit_and_exit` 结果格式**：Charles 返回结构化 dict，Cline 返回纯字符串。建议对齐 Cline，将 `submit_and_exit.py` L94-105 的 `_execute` 返回值改为纯字符串：
   ```python
   return AgentToolResult(
       output=f"任务完成（verified={verified}）: {summary}",
       metadata={...},
   )
   ```
   - **影响**：与 Cline 行为一致，runtime 提取 `output_text` 无歧义。
   - **风险**：低（需确认前端 / 日志层是否依赖原 dict 结构）。

3. **补充 `submit_and_exit` 超时配置**：Charles `SubmitAndExitTool` 未覆盖 `timeout_ms`，建议对齐 Cline 添加 15000ms 超时：
   ```python
   @property
   def timeout_ms(self) -> int | None:
       return 15000
   ```
   - **影响**：防止 executor 挂起导致 runtime 永久阻塞。
   - **风险**：低（runtime 已有超时处理逻辑）。

4. **实现 `ask_question` 互斥策略**：Charles 同时注册 `ask_question` 与 `submit_and_exit`，建议对齐 Cline 在 `create_default_tools` 中实现互斥（通过参数控制）：
   ```python
   def create_default_tools(working_dir=None, session_id=None, enable_submit=True):
       tools = [...]
       if not enable_submit:
           tools.append(AskQuestionTool())
       else:
           tools.append(SubmitAndExitTool())
       return tools
   ```
   - **影响**：与 Cline 行为一致，避免 LLM 在 submit 模式下误调用 ask_question。
   - **风险**：中（需评估现有调用方是否依赖两个工具并存）。

### P2（注释清理）

5. **修正 `submit_and_exit.py` 的 `read_only` 注释**：L80-83 的注释"终止性工具，不修改文件，标记为 False 以符合规范"自相矛盾。建议二选一：
   - 方案 A（推荐）：将 `read_only` 改为 `True`（与 `attempt_completion` 一致，与实际行为一致——不修改文件）。
   - 方案 B：保留 `read_only=False`，但修正注释说明"标记为 False 以确保审批流程不跳过"（若这是有意为之）。
   - **影响**：消除属性标记与实际行为的矛盾。
   - **风险**：低（需确认 `approval_policy` 是否依赖 `read_only` 属性——实际查看 `approval_policy.py` L37-47，`submit_and_exit` 在 `READ_ONLY_TOOLS` 集合中，与属性无关）。

6. **清理 `agent/tools/__init__.py` 的 nanobot 注释残留**：L2 的 docstring 标题"对标 Cline extensions/tools 和 nanobot agent/tools"是历史对标说明，建议改为"对标 Cline extensions/tools"。此项与 P2.4 / P2.5 / P3.3 报告建议一致，非 P3.17 新增问题。

---

## 7. 验证方法建议

1. **`attempt_completion` 死代码验证**：在 `agent/` 目录执行 `grep -rn "from agent.tools.attempt_completion import\|from agent.tools import.*AttemptCompletionTool\|AttemptCompletionTool(" agent/`，预期无任何匹配（确认类未被导入或实例化）。

2. **`submit_and_exit` completesRun 验证**：构造 LLM 调用 `submit_and_exit(summary="...", verified=true)` 的场景，运行 agent：
   - 预期：`_find_completing_tool` 返回非 None，`_finish_run("completed", ...)` 被调用，`AgentRunResult.status == "completed"`，`run-finished` 事件发射。
   - 验证点：对比 Charles 与 Cline 的 `AgentRunResult.status` / `output_text` / `iterations` 字段值。

3. **`submit_and_exit` 失败不结束验证**：构造 LLM 调用 `submit_and_exit` 但 `verified=false` 或 summary 不满足 minLength=10 的场景：
   - 预期（schema 校验失败）：BaseTool `_validate_input` 返回错误，`is_error=True`，`_find_completing_tool` 跳过（因 `not part.is_error` 条件不满足），运行继续下一轮。
   - 验证点：确认 schema 校验失败时不会误触发 finishRun。

4. **`ask_question` 互斥验证**：在 Charles 当前实现下，确认 `create_default_tools()` 返回的工具列表同时含 `AskQuestionTool` 与 `SubmitAndExitTool`；对比 Cline 在 `enableSubmitAndExit=true` 时工具列表只含 `submit_and_exit` 不含 `ask_question`。

5. **超时配置验证**：在 Charles `submit_and_exit.py` 中确认 `timeout_ms` 属性返回 None（当前实现）；对比 Cline `submit_and_exit` 的 `timeoutMs` 返回 15000。

6. **结果格式验证**：在 Charles 中调用 `submit_and_exit`，检查 `AgentToolResult.output` 类型为 dict；对比 Cline 调用结果类型为 string。

7. **nanobot 残留回归**：运行 `grep -r "nanobot" agent/tools/submit_and_exit.py agent/tools/attempt_completion.py agent/runtime.py agent/types.py agent/approval_policy.py agent/tools/todo_write.py` 确认重点文件无残留（`tools/__init__.py` L2 的 1 处注释除外）。

8. **Cline 别名映射验证**：在 Cline sdk 包内执行 `grep -rn "attempt_completion" sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`，预期 L88 出现 `attempt_completion: "submit_and_exit"` 别名映射。

9. **Cline VSCode attempt_completion 非 completesRun 验证**：在 `apps/vscode/src/sdk/vscode-runtime-builder.ts` L65-116 确认 `createAttemptCompletionTool` 返回的工具对象**无 `lifecycle` 字段**（即 completesRun 为 undefined）。
