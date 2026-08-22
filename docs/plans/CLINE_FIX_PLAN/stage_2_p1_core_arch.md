# Stage 2: P1 核心架构对齐方案

> 本阶段覆盖核心架构层的 8 个小阶段任务，基于 CLINE_DIFF 对比报告与实际源代码核对生成。
> 对标源码：Cline `sdk/packages/shared/src/agent.ts` 与 `sdk/packages/agents/src/agent-runtime.ts`
> 当前实现：`agent/types.py` / `agent/runtime.py` / `agent/events.py` / `agent/abort.py` / `agent/providers/*` / `agent/tools/run_commands.py`
>
> 关键说明：
> 1. 所有行号均基于实际 Read 后的当前代码状态，非 CLINE_DIFF 报告中的估算行号。
> 2. 已实现的差距（如 N12 子进程 kill）会如实说明，避免重复劳动。
> 3. 保留原函数逻辑，修改在原基础上增强，不重写。

---

## 2.1 LLM Provider abort 语义对齐（R14）

### 任务背景

来源 Phase R #R14。当前 provider 的 `stream()` 在检测到 abort 信号被触发时，发射的 `finish` 事件使用 `reason=AgentModelFinishReason.ERROR`，并把 `error` 字段设为 `"aborted by user"`。Cline 在 `apihandler-agent-model-adapter.ts` 中按 `request.signal?.aborted ? "aborted" : "error"` 分类：用户主动中止走 `aborted`，真实异常走 `error`。

`AgentModelFinishReason` 枚举（`agent/types.py` L209-215）已定义 `ABORTED = "aborted"`，但两个 provider 实现均未使用，统一走 `ERROR`，导致 runtime 难以区分"用户中止"与"真实错误"。

### 目标

将 `QwenModel.stream()` 与 `OpenAIModel.stream()` 中的 abort 分支改为发射 `reason=AgentModelFinishReason.ABORTED`，对齐 Cline 的语义分类，让 runtime 可通过 `finish_reason` 准确判断中止来源。

### 当前实现位置

- `agent/providers/qwen.py` L156-164：abort 检查分支
  ```python
  if abort_signal is not None and abort_signal.is_set():
      yield AgentModelEvent(
          type="finish",
          reason=AgentModelFinishReason.ERROR,
          error="aborted by user",
      )
      return
  ```
- `agent/providers/openai.py` L151-159：相同结构的 abort 检查分支
- `agent/types.py` L209-215：`AgentModelFinishReason` 枚举已含 `ABORTED`

### 目标源代码位置

- Cline `sdk/packages/core/src/services/llms/apihandler-agent-model-adapter.ts` L160-168
  ```typescript
  // try/catch 包裹流，捕获异常后发射 finish 事件
  // reason 为 signal.aborted ? "aborted" : "error"
  ```
- Cline `sdk/packages/shared/src/agent.ts` L225-230：`AgentModelFinishReason` 含 `"aborted"`

### 修复步骤建议

1. 修改 `agent/providers/qwen.py` L159-163 的 abort 分支：
   - 保留 `if abort_signal is not None and abort_signal.is_set():` 判断逻辑不变
   - 将 `reason=AgentModelFinishReason.ERROR` 改为 `reason=AgentModelFinishReason.ABORTED`
   - `error="aborted by user"` 保留（Cline 在 abort 时也会在 error 字段携带原因，便于调试）
2. 修改 `agent/providers/openai.py` L154-158 的 abort 分支，做相同改动
3. 保留两个 provider 中 `asyncio.TimeoutError` 和通用 `Exception` 分支的 `reason=ERROR` 不变（这些是真实错误，不是中止）

### 验证方法

1. 单元测试：构造一个已 set 的 `asyncio.Event` 作为 abort_signal，调用 `QwenModel.stream()` 与 `OpenAIModel.stream()`，断言收到的 `finish` 事件 `reason == AgentModelFinishReason.ABORTED.value`（即 `"aborted"`）
2. 集成测试：运行 agent 主循环，运行中调用 `runtime.abort()`，断言 runtime 能通过 `finish_reason == "aborted"` 识别中止来源（与 `runtime.py` L528-529 的 `if finish_reason == AgentModelFinishReason.ABORTED.value: raise RuntimeError(...)` 路径匹配）
3. 回归测试：触发真实超时（如 idle_timeout），断言 `reason == "error"` 不变

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：实际代码中 abort 检查在 chunk 间隙进行（qwen.py L158，openai.py L153），不是在 stream 入口，修改时保留这一时序
- 保留原函数逻辑，在其基础上修改：仅改 `reason` 枚举值，不调整 abort 检查的位置和条件
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：abort 信号未设置时走正常路径，无需额外兜底
- runtime.py L528-529 已有 `if finish_reason == AgentModelFinishReason.ABORTED.value: raise RuntimeError(self._abort_reason or "aborted")` 的处理路径，provider 改为 ABORTED 后该路径会被正确触发

---

## 2.2 类型系统消息片段补齐（A2）

### 任务背景

来源 Phase A #A2。Cline 的 `AgentMessagePart` 联合类型含 6 种片段：text / reasoning / image / file / tool-call / tool-result（`agent.ts` L65-71）。我的 `MessagePart` 联合类型仅含 4 种（`agent/types.py` L84）：TextPart / ReasoningPart / ToolCallPart / ToolResultPart，缺少 `ImagePart` 和 `FilePart`。

当前量化场景暂无图片输入需求，但若未来接入"K 线截图分析"或"PDF 文件附件"，需补齐这两种片段类型。FilePart 与现有 `read_files` 工具不同：FilePart 是用户上传的文件内容直接进 message，而非工具调用读取。

### 目标

在 `agent/types.py` 中新增 `ImagePart` 和 `FilePart` 数据结构，对齐 Cline `AgentImagePart`（`agent.ts` L37-41）和 `AgentFilePart`（`agent.ts` L43-47），并更新 `MessagePart` 联合类型。

### 当前实现位置

- `agent/types.py` L33-84：现有 4 种片段定义和 `MessagePart` 联合类型
  ```python
  # L83-84
  # 消息片段联合类型
  MessagePart = TextPart | ReasoningPart | ToolCallPart | ToolResultPart
  ```

### 目标源代码位置

- Cline `sdk/packages/shared/src/agent.ts` L37-47
  ```typescript
  export interface AgentImagePart {
      type: "image";
      image: string | Uint8Array | ArrayBuffer | URL;
      mediaType?: string;
  }
  export interface AgentFilePart {
      type: "file";
      path: string;
      content: string;
  }
  ```
- Cline `sdk/packages/shared/src/agent.ts` L65-71：`AgentMessagePart` 联合类型含 image 和 file

### 修复步骤建议

1. 在 `agent/types.py` L67（`ToolResultPart` 定义之后、`MessagePart` 联合类型之前）插入两个新 dataclass：
   ```python
   @dataclass
   class ImagePart:
       """图片消息片段 — 对标 Cline AgentImagePart

       用于承载用户上传的图片输入（如 K 线截图分析），
       image 字段支持 base64 字符串或原始字节。
       """
       type: str = field(default="image", init=False, repr=False)
       image: str | bytes = b""
       media_type: str | None = None  # image/png 等

   @dataclass
   class FilePart:
       """文件消息片段 — 对标 Cline AgentFilePart

       用于承载用户上传的文件附件内容，
       与 read_files 工具不同：FilePart 是直接进 message 的文件内容。
       """
       type: str = field(default="file", init=False, repr=False)
       path: str = ""
       content: str = ""
   ```
2. 修改 `agent/types.py` L84 的 `MessagePart` 联合类型：
   ```python
   MessagePart = TextPart | ReasoningPart | ImagePart | FilePart | ToolCallPart | ToolResultPart
   ```
3. 检查 `agent/types.py` L452-455 的 `text_from_message` 函数：该函数遍历 content 提取 TextPart/ReasoningPart 文本，新增 ImagePart/FilePart 不影响该逻辑（仅 TextPart/ReasoningPart 有 `.text` 属性），无需修改
4. 检查 provider 的 `agent_messages_to_openai`（`agent/providers/base.py`）：当前仅处理 TextPart/ReasoningPart/ToolCallPart/ToolResultPart，新增的 ImagePart/FilePart 在未被 provider 处理前应跳过（不写 fallback，provider 后续按需扩展）

### 验证方法

1. 静态检查：`python -c "from agent.types import ImagePart, FilePart, MessagePart; print('OK')"` 无报错
2. 构造测试：创建含 `ImagePart` 的消息，断言 `isinstance(msg.content[0], ImagePart)` 为 True，且 `msg.content[0].type == "image"`
3. 回归测试：运行现有 agent e2e 测试（`tests/test_agent_e2e.py`），断言无回归

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：实际代码中 `MessagePart` 是类型别名（L84），不是 dataclass 字段，修改时只需扩展 Union
- 保留原函数逻辑：`text_from_message` 等函数不修改，新增片段类型不在其处理范围内
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：provider 暂不处理 ImagePart/FilePart，后续接入多模态时再扩展
- `field(default="image", init=False, repr=False)` 模式与现有 TextPart/ReasoningPart 一致，保持风格统一

---

## 2.3 AgentTool/AgentModelEvent 类型安全增强（A8/A11/A20）

### 任务背景

来源 Phase A #A8 / #A11 / #A20。三项类型安全差距：

1. **A8 AgentTool 协议**：Cline 的 `AgentTool.execute` 返回 `Promise<TOutput>`（原始输出），由 Runtime 包装为 `AgentToolResult`；我的 `AgentTool.execute` 返回 `AgentToolResult`，工具自己包装。CLINE_DIFF 评估为 P2，已有 BaseTool 基类弥补。
2. **A11 AgentModelEvent**：Cline 用 discriminated union（5 个独立 interface），编译期类型安全；我用单一 dataclass 含所有字段（`agent/types.py` L218-248），多数字段为 None。CLINE_DIFF 评估为 P3，功能等价。
3. **A20 不可变性**：Cline 的 `AgentRuntimeStateSnapshot.messages` 是 `readonly AgentMessage[]`（`agent.ts` L136），编译期防修改；我用 `list[AgentMessage]`（`agent/types.py` L324），可变。CLINE_DIFF 评估为 P2。

### 目标

基于实际代码评估三项差距，对影响状态安全的 A20 进行对齐（snapshot.messages 改为 tuple），A8 和 A11 保留现有特化（已有 BaseTool 弥补，且改造代价大、收益小）。

### 当前实现位置

- `agent/types.py` L160-190：`AgentTool` Protocol，`execute` 返回 `AgentToolResult`
- `agent/types.py` L218-248：`AgentModelEvent` 单一 dataclass
- `agent/types.py` L311-327：`AgentRuntimeStateSnapshot`，`messages: list[AgentMessage]`（L324），`pending_tool_calls: list[str]`（L325）
- `agent/runtime.py` L354-368：`snapshot()` 方法，构造 snapshot 时用 `list(self._state.messages)`（L364）和 `list(self._state.pending_tool_calls)`（L365）

### 目标源代码位置

- Cline `sdk/packages/shared/src/agent.ts` L128-140：`AgentRuntimeStateSnapshot`，`messages: readonly AgentMessage[]`（L136），`pendingToolCalls: readonly string[]`（L137）
- Cline `sdk/packages/shared/src/agent.ts` L177-186：`AgentTool` 协议
- Cline `sdk/packages/shared/src/agent.ts` L232-257：`AgentModelEvent` discriminated union

### 修复步骤建议

**A8（AgentTool 协议）**：保留现状，不修改。理由：
- 已有 BaseTool 基类（`agent/tools/base.py`）提供统一包装层，实际行为接近 Cline
- 修改协议会破坏所有现有工具（run_commands / editor / read_files 等），代价过大
- 文档说明差异即可

**A11（AgentModelEvent discriminated union）**：保留现状，不修改。理由：
- Python 无原生 discriminated union，改造为 Union 类型需修改所有 provider 的 emit 逻辑
- 功能等价，仅类型安全弱
- 加强 provider 测试覆盖即可

**A20（不可变性）**：对齐 Cline，将 snapshot 的 messages 和 pending_tool_calls 改为 tuple：
1. 修改 `agent/types.py` L324-325：
   ```python
   messages: tuple[AgentMessage, ...] = field(default_factory=tuple)
   pending_tool_calls: tuple[str, ...] = field(default_factory=tuple)
   ```
2. 修改 `agent/runtime.py` L364-365 的 `snapshot()` 方法：
   ```python
   messages=tuple(self._state.messages),
   pending_tool_calls=tuple(self._state.pending_tool_calls),
   ```
3. 检查所有访问 `snapshot.messages` 的位置：grep `snapshot.messages` 和 `.messages` 访问点，确认无 `append` / `extend` / `__setitem__` 调用（snapshot 是只读视图，不应被修改）
4. 检查 `agent/events.py` 中事件携带 snapshot 的位置：事件传递 snapshot 引用，tuple 化后不会被 listener 误修改

### 验证方法

1. A20 单元测试：构造 snapshot，断言 `snapshot.messages` 是 tuple 类型，尝试 `snapshot.messages.append(...)` 应抛 `AttributeError`
2. A20 回归测试：运行 agent e2e 测试，确认无 listener 或 hook 依赖 list 方法（如 `len()` / 索引访问 / 迭代均兼容 tuple）
3. A8/A11：无需测试，保持现状

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：A8/A11 经评估后保留现状，仅 A20 做对齐
- 保留原函数逻辑：`snapshot()` 方法仅改 `list()` 为 `tuple()`，其余字段不变
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：tuple 化后若某处依赖 list 方法，应修复该处代码而非回退
- 检查 `agent/runtime.py` 中 `clone_messages(self._state.messages)` 等调用：`clone_messages` 接受 `list[AgentMessage]`（types.py L470），tuple 化后需确认其能接受 tuple 或调整签名
- 风险点：若 listener 中有 `snapshot.messages.append(...)`，tuple 化后会报错，需先 grep 确认

---

## 2.4 流式工具组装 nextToolIndex 时机修正（C3）

### 任务背景

来源 Phase C #C3。CLINE_DIFF 初步判断 `nextToolIndex` 自增时机偏离，但经实际代码分析后降级为"完全一致"。本任务基于实际代码核对，确认逻辑等价性，并对齐代码结构以提高可读性。

Cline 在 `agent-runtime.ts` L966-970 将 key 计算与 nextToolIndex 自增分离为两步：先用 `??` 计算 key，再用独立 `if` 判断是否自增。我的实现在 `runtime.py` L787-793 用 `if/elif/else` 三分支，自增在 else 分支内。

### 目标

确认逻辑等价性后，对齐 Cline 的代码结构：将 nextToolIndex 自增从 else 分支内移到独立的 `if` 判断，使"key 计算"与"自增决策"分离，提高可读性，并保留原逻辑。

### 当前实现位置

- `agent/runtime.py` L787-793：
  ```python
  if event.tool_call_id is not None:
      key = event.tool_call_id
  elif event.index is not None:
      key = f"tool_{event.index}"
  else:
      key = f"tool_{next_tool_index}"
      next_tool_index += 1
  ```

### 目标源代码位置

- Cline `sdk/packages/agents/src/agent-runtime.ts` L966-970：
  ```typescript
  const key = event.toolCallId ?? `tool_${event.index ?? nextToolIndex}`;
  if (event.index == null && event.toolCallId == null) {
      nextToolIndex += 1;
  }
  ```

### 修复步骤建议

1. 修改 `agent/runtime.py` L787-793，将 key 计算与自增分离：
   ```python
   # 对标 Cline agent-runtime.ts L966-970:
   # key = event.toolCallId ?? `tool_${event.index ?? nextToolIndex}`
   # 注意：Python 的 `or` 会把空字符串/0 当作 falsy，必须用 is None 判断，
   # 否则 index=0 的 tool call 会丢失参数。
   if event.tool_call_id is not None:
       key = event.tool_call_id
   elif event.index is not None:
       key = f"tool_{event.index}"
   else:
       key = f"tool_{next_tool_index}"

   # 自增决策独立判断 — 对标 Cline L968-970
   if event.index is None and event.tool_call_id is None:
       next_tool_index += 1
   ```
2. 保留原有的 `if event.tool_call_id is not None` 判断逻辑（Python 不能用 `??`，必须用 `is not None`）
3. 保留 L786 的注释说明（关于 Python `or` 与 `is None` 的差异）

### 验证方法

1. 边界测试：构造 `event.index = 0, tool_call_id = None` 的 delta，断言 `key = "tool_0"` 且 `next_tool_index` 不自增（与原逻辑一致）
2. 边界测试：构造 `event.index = None, tool_call_id = None` 的 delta，断言 `key = f"tool_{next_tool_index}"` 且 `next_tool_index` 自增 1
3. 边界测试：构造 `event.index = None, tool_call_id = "abc"` 的 delta，断言 `key = "abc"` 且 `next_tool_index` 不自增
4. 回归测试：运行流式工具调用 e2e 测试，断言无回归

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：经分析逻辑等价，本任务是对齐代码结构而非修正逻辑
- 保留原函数逻辑：key 计算的 `if/elif/else` 三分支保留，仅将自增从 else 分支移到独立 if
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：Python 不能用 `??`，必须用 `is not None` 判断，这是语言差异不是 fallback
- 关键边界：`index = 0` 时 `0 is not None` 为 True，走 elif 分支，不自增（与 Cline `0 ?? nextToolIndex` = 0 语义一致）

---

## 2.5 事件系统 assistant-message/tool-updated 补齐（D6/D8）

### 任务背景

来源 Phase D #D6 / #D8。Cline 的 `AgentRuntimeEvent` 含 14 种事件类型（`agent.ts` L466-550），其中 `assistant-message`（L497-503，携带 finishReason）和 `tool-updated`（L511-516，携带 toolCall 和 update）两种我的实现缺失。

当前我用 `message-added` 通用事件覆盖 assistant 消息，用 `status-notice` 复用覆盖工具进度更新（`runtime.py` L1686-1717 的 `_make_emit_update`）。功能等价，但前端无法单独监听 assistant 消息完成事件（携带 finishReason），也无法区分"工具进度更新"与"普通状态通知"。

### 目标

在 `agent/events.py` 新增 `ASSISTANT_MESSAGE` 和 `TOOL_UPDATED` 事件类型常量，添加对应的构造函数，并在 `runtime.py` 的 assistant 消息添加点和 `_make_emit_update` 添加 emit 点。保留原有 `message-added` 和 `status-notice` 事件不变（向后兼容）。

### 当前实现位置

- `agent/events.py` L33-54：事件类型常量定义，缺 `ASSISTANT_MESSAGE` 和 `TOOL_UPDATED`
- `agent/events.py` L61-105：`AgentEvent` dataclass，已有 `message` / `finish_reason` / `tool_call_id` / `tool_name` / `metadata` 等字段，无需新增字段
- `agent/events.py` L245-250：`make_message_added` 构造函数
- `agent/events.py` L331-345：`make_status_notice` 构造函数
- `agent/runtime.py` L549-550：assistant 消息添加后仅 emit `message-added`
- `agent/runtime.py` L1686-1717：`_make_emit_update` 用 `STATUS_NOTICE` 复用

### 目标源代码位置

- Cline `sdk/packages/shared/src/agent.ts` L497-503：`assistant-message` 事件定义
  ```typescript
  | {
      type: "assistant-message";
      snapshot: AgentRuntimeStateSnapshot;
      iteration: number;
      message: AgentMessage;
      finishReason: AgentModelFinishReason;
  }
  ```
- Cline `sdk/packages/shared/src/agent.ts` L511-516：`tool-updated` 事件定义
  ```typescript
  | {
      type: "tool-updated";
      snapshot: AgentRuntimeStateSnapshot;
      iteration: number;
      toolCall: AgentToolCallPart;
      update: unknown;
  }
  ```
- Cline `sdk/packages/agents/src/agent-runtime.ts` L665-671：emit `assistant-message`
- Cline `sdk/packages/agents/src/agent-runtime.ts` L1498-1506：`emitUpdate` 回调发射 `tool-updated`

### 修复步骤建议

1. 在 `agent/events.py` L46（`MESSAGE_ADDED` 常量之后）新增两个常量：
   ```python
   # assistant 消息完成事件 — 对标 Cline assistant-message
   ASSISTANT_MESSAGE = "assistant-message"
   # 工具进度更新事件 — 对标 Cline tool-updated
   TOOL_UPDATED = "tool-updated"
   ```
2. 在 `agent/events.py` 的辅助函数区（L250 `make_message_added` 之后）新增 `make_assistant_message`：
   ```python
   def make_assistant_message(
       snapshot: AgentRuntimeStateSnapshot,
       iteration: int,
       message: AgentMessage,
       finish_reason: str,
   ) -> AgentEvent:
       """构造 assistant-message 事件 — 对标 Cline agent-runtime.ts L665-671

       assistant 消息完成时发射，携带 finishReason，
       前端可据此区分 stop/tool-calls/max-tokens 等完成原因。
       """
       return AgentEvent(
           type=ASSISTANT_MESSAGE,
           snapshot=snapshot,
           iteration=iteration,
           message=message,
           finish_reason=finish_reason,
       )
   ```
3. 在 `agent/events.py` 新增 `make_tool_updated`：
   ```python
   def make_tool_updated(
       snapshot: AgentRuntimeStateSnapshot,
       iteration: int,
       tool_call_id: str,
       tool_name: str,
       update: Any,
   ) -> AgentEvent:
       """构造 tool-updated 事件 — 对标 Cline agent-runtime.ts L1498-1506

       工具执行过程中发射进度更新，携带 toolCall 标识和 update 数据。
       """
       return AgentEvent(
           type=TOOL_UPDATED,
           snapshot=snapshot,
           iteration=iteration,
           tool_call_id=tool_call_id,
           tool_name=tool_name,
           metadata=update if isinstance(update, dict) else {"value": update},
       )
   ```
4. 修改 `agent/runtime.py` 的 import（L66-94）添加新常量和构造函数：
   ```python
   from agent.events import (
       # ... 现有导入 ...
       ASSISTANT_MESSAGE,
       TOOL_UPDATED,
       make_assistant_message,
       make_tool_updated,
   )
   ```
5. 修改 `agent/runtime.py` L1700-1717 的 `_make_emit_update` 内部 `emit_update` 函数，将 `type=STATUS_NOTICE` 改为 `type=TOOL_UPDATED`，并补充 `tool_call_id` 和 `iteration` 字段：
   ```python
   def emit_update(update: Any) -> None:
       try:
           event = AgentEvent(
               type=TOOL_UPDATED,
               snapshot=self.snapshot(),
               iteration=self._state.iteration,
               tool_call_id=prepared_tool_call_id,  # 需在 _make_emit_update 签名中传入
               tool_name=tool_name,
               metadata=update if isinstance(update, dict) else {"value": update},
           )
           asyncio.create_task(self._emit(event))
       except Exception:
           pass
   ```
   注意：`_make_emit_update` 当前签名仅接收 `tool_name`（L1686），需扩展为接收 `tool_call_id`，调用方（`runtime.py` L1364）需传入 `prepared.tool_call.tool_call_id`。
6. 保留 `status-notice` 事件不变（用于 prepareTurn 等中间状态通知，不复用为工具更新）

### 验证方法

1. 静态检查：`python -c "from agent.events import ASSISTANT_MESSAGE, TOOL_UPDATED, make_assistant_message, make_tool_updated; print('OK')"` 无报错
2. assistant-message 测试：运行 agent 主循环，断言 assistant 消息添加后收到 `assistant-message` 事件，且 `finish_reason` 字段非 None
3. tool-updated 测试：运行 TodoWrite 工具，断言 update 触发 `tool-updated` 事件（而非 `status-notice`），且 `tool_call_id` 和 `tool_name` 字段正确
4. 兼容性测试：确认 `message-added` 和 `status-notice` 事件仍正常发射，前端监听不受影响

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`_make_emit_update` 签名需扩展以传入 `tool_call_id`，调用方 L1364 需同步修改
- 保留原函数逻辑：`_make_emit_update` 的 try/except 异常隔离保留，仅改事件类型和补充字段
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`update` 非 dict 时包装为 `{"value": update}`，这是与原逻辑一致的序列化方式，不是 fallback
- 前端 `static/js/ai-chat.js` 若监听 `status-notice` 处理工具更新，需同步增加 `tool-updated` 监听（本阶段不强制改前端，向后兼容）
- 任务 2.8 会在 runtime 主循环添加 `assistant-message` emit 点，与本任务的事件类型定义配套

---

## 2.6 AbortController 幂等检查（N2）

### 任务背景

来源 Phase N #N2。Cline 的 `abort()` 方法（`agent-runtime.ts` L454-460）在执行前检查 `this.abortController.signal.aborted`，若已 aborted 则直接 return，实现幂等。我的 `abort()` 方法（`runtime.py` L339-352）无幂等检查，重复调用会覆盖 `_abort_reason` 和 `_state.last_error`，可能丢失首次中止原因。

`agent/abort.py` 的 `AbortController.abort()` 方法（L72-79）也无幂等检查，重复调用会覆盖 `_reason`。

### 目标

在 `AgentRuntime.abort()` 和 `AbortController.abort()` 两层都添加幂等检查，对齐 Cline 的"已 aborted 则直接 return"语义，避免重复调用覆盖首次中止原因。

### 当前实现位置

- `agent/runtime.py` L339-352：`AgentRuntime.abort()` 方法
  ```python
  def abort(self, reason: str = "") -> None:
      self._aborted = True
      self._abort_reason = reason or "aborted by user"
      self._state.status = "aborted"
      self._state.last_error = self._abort_reason
      self._abort_controller.abort(self._abort_reason)
  ```
- `agent/abort.py` L72-79：`AbortController.abort()` 方法
  ```python
  def abort(self, reason: str = "") -> None:
      self._reason = reason
      self._signal.set()
  ```

### 目标源代码位置

- Cline `sdk/packages/agents/src/agent-runtime.ts` L454-460
  ```typescript
  abort(reason?: unknown): void {
      if (!this.abortController) {
          return;
      }
      if (this.abortController.signal.aborted) {
          return;  // 已 aborted，幂等返回
      }
      // ... 实际中止逻辑 ...
  }
  ```

### 修复步骤建议

1. 修改 `agent/abort.py` L72-79 的 `AbortController.abort()`，在方法开头添加幂等检查：
   ```python
   def abort(self, reason: str = "") -> None:
       """触发中止 — 对标 Cline AbortController.abort()

       Args:
           reason: 中止原因，记录到日志和异常消息
       """
       # 幂等检查 — 对标 Cline L458-460
       # 已 aborted 时直接返回，避免覆盖首次中止原因
       if self._signal.is_set():
           return
       self._reason = reason
       self._signal.set()
   ```
2. 修改 `agent/runtime.py` L339-352 的 `AgentRuntime.abort()`，在方法开头添加幂等检查：
   ```python
   def abort(self, reason: str = "") -> None:
       """中止运行 — 对标 Cline AgentRuntime.abort() L454-470

       设置中止标志，主循环在下一次检查点会抛出异常。
       Phase 30.2: 同步记录 last_error，对标 Cline L465。
       """
       # 幂等检查 — 对标 Cline L458-460
       # 已 aborted 时直接返回，避免覆盖首次中止原因
       if self._aborted:
           return
       self._aborted = True
       self._abort_reason = reason or "aborted by user"
       self._state.status = "aborted"
       self._state.last_error = self._abort_reason
       self._abort_controller.abort(self._abort_reason)
   ```
3. 保留 `restore()` 方法（L320-337）中 `self.abort("Agent state restored")` 的调用不变：restore 时若已 aborted，abort 幂等返回，然后 restore 继续重置状态（L336 `self._aborted = False` 复位）

### 验证方法

1. 单元测试：构造 `AgentRuntime`，调用 `abort("reason1")`，再调用 `abort("reason2")`，断言 `runtime._abort_reason == "reason1"`（首次原因保留）
2. 单元测试：构造 `AbortController`，调用 `abort("a")`，再调用 `abort("b")`，断言 `controller.reason == "a"`
3. 集成测试：运行 agent，运行中快速调用 `abort()` 两次（模拟用户快速双击停止按钮），断言 `state.last_error` 为首次原因
4. 回归测试：`restore()` 后能正常重新运行（`_aborted` 被 L336 复位为 False）

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`restore()` 方法 L323 调用 `self.abort("Agent state restored")`，幂等检查后若已 aborted 会直接返回，但 L336 `self._aborted = False` 仍会执行复位，不影响 restore 逻辑
- 保留原函数逻辑：仅添加幂等检查 if 分支，后续中止逻辑不变
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：幂等检查是前置守卫，不是 fallback
- 两层幂等检查冗余但安全：`AgentRuntime.abort()` 检查 `_aborted`，`AbortController.abort()` 检查 `_signal.is_set()`，任一层都能拦截重复调用

---

## 2.7 AbortController 子进程 kill on abort（N12）

### 任务背景

来源 Phase N #N12。CLINE_DIFF 报告"abort 时无子进程 kill"，但经实际代码核对，`agent/tools/run_commands.py` 已实现 abort 时 kill 子进程的机制（Phase 28.2）。本任务基于实际代码确认实现完整性，并评估是否有改进点。

Cline 在 AbortSignal 触发时，spawn 的子进程会被 kill。我的实现通过 `asyncio.wait` 将 `process.communicate()` 与 `signal.wait()` 组合等待，abort 触发时 `process.kill()` 并抛出 `AbortedError`。

### 目标

核对现有实现是否符合 Cline 的"abort 立即 kill 子进程"语义，补充缺失的边界处理（如 `exec_tool.py` 单命令工具是否也支持 abort kill）。

### 当前实现位置

- `agent/tools/run_commands.py` L171-249：`_execute_single` 方法，已处理 AbortedError 并清理子进程
- `agent/tools/run_commands.py` L251-305：`_wait_process_with_abort` 方法，通过 `asyncio.wait` 组合等待实现 abort 时 kill
  ```python
  # L288-295: abort 先触发时终止进程并抛出
  if abort_task in done:
      comm_task.cancel()
      try:
          process.kill()
          await asyncio.wait_for(process.wait(), timeout=2.0)
      except Exception:
          pass
      raise AbortedError("aborted by user")
  ```
- `agent/tools/run_commands.py` L233-242：`_execute_single` 的 AbortedError 处理，确保子进程被清理
- `agent/tools/base.py` L140-159：`_check_aborted` 方法，在批量执行的关键检查点调用

### 目标源代码位置

- Cline AbortSignal 触发时 kill 子进程的语义（`sdk/packages/agents/src/agent-runtime.ts` L633, L855, L862, L892, L914 的 `throwIfAborted` 调用点）

### 修复步骤建议

**核心结论**：`run_commands.py` 已实现 abort 时 kill 子进程，本任务无需重复实现，但需补充以下改进：

1. 核对 `agent/tools/exec_tool.py`（单命令执行工具）是否也支持 abort kill：
   - Grep `exec_tool.py` 中的 `abort_signal` / `_wait_process_with_abort` / `AbortedError` 使用情况
   - 若 `exec_tool.py` 未实现，参考 `run_commands.py` L251-305 的 `_wait_process_with_abort` 模式补齐
2. 核对 `agent/tools/web_tool.py` / `fetch_web_content.py` 等涉及网络 IO 的工具是否检查 abort_signal：
   - 这些工具的长 IO 操作应在关键检查点调用 `_check_aborted(context)`（base.py L140）
3. 在 `run_commands.py` L233-242 的 AbortedError 处理中，确认 `process.kill()` 后 `process.wait()` 的超时（当前 2.0 秒）是否合理：若子进程忽略 SIGKILL（罕见），2 秒后超时跳过，可能留下僵尸进程，但实际场景下 SIGKILL 无法被忽略，2 秒足够
4. 文档说明：在 `run_commands.py` 的模块文档字符串中补充"abort 时立即 kill 子进程"的行为说明

### 验证方法

1. 集成测试：运行 `run_commands(commands=["sleep 60"])`，运行中调用 `runtime.abort()`，断言：
   - 子进程在 2 秒内被 kill（`ps` 检查无残留 `sleep 60` 进程）
   - 工具抛出 `AbortedError`
   - runtime 状态变为 `aborted`
2. 边界测试：运行 `run_commands(commands=["sleep 60", "echo done"])`，运行中 abort，断言第二条命令不执行（L146 `_check_aborted` 在每条命令开始前检查）
3. 回归测试：正常执行 `run_commands(commands=["echo hello"])`，断言无 abort 干扰，输出正确

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：CLINE_DIFF 报告"无 kill"与实际代码不符，本任务实际是"核对 + 补齐 exec_tool 等其他工具"
- 保留原函数逻辑：`_wait_process_with_abort` 的 asyncio.wait 组合等待模式保留，不重写
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`process.kill()` 后的 `wait_for` 超时跳过是异常清理的合理做法，不是 fallback
- 关键检查点：`exec_tool.py` 是单命令工具，若未实现 abort kill，需优先补齐（与 run_commands 行为一致）

---

## 2.8 主循环 emit assistant-message 补齐（B20）

### 任务背景

来源 Phase B #B20。Cline 的主循环在 assistant 消息添加后 emit 两个事件：先 `message-added`（通用消息添加），再 `assistant-message`（专用 assistant 消息完成，携带 finishReason）（`agent-runtime.ts` L660-671）。我的实现仅 emit `message-added`（`runtime.py` L549-550），缺失 `assistant-message`，导致前端无法获取 finishReason，无法区分"正常结束"/"tool-calls"/"max-tokens"等完成原因。

本任务与 2.5 配套：2.5 定义事件类型和构造函数，2.8 在 runtime 主循环添加 emit 点。

### 目标

在 `agent/runtime.py` 主循环的 assistant 消息添加后（L550 之后），追加 emit `assistant-message` 事件，携带 `finish_reason`，对齐 Cline 的双事件发射模式。保留原有 `message-added` 事件不变（向后兼容）。

### 当前实现位置

- `agent/runtime.py` L547-550：assistant 消息保存和 emit message-added
  ```python
  # 保存 assistant 消息
  final_assistant_message = message
  self._state.messages.append(message)
  await self._emit(make_message_added(self.snapshot(), message))
  ```
- `agent/runtime.py` L526：`_generate_assistant_message` 返回 `message, finish_reason`
- `agent/runtime.py` L528-529：`finish_reason` 用于判断 aborted 分支

### 目标源代码位置

- Cline `sdk/packages/agents/src/agent-runtime.ts` L658-671
  ```typescript
  finalAssistantMessage = message;
  this.state.messages.push(message);
  await this.emit({
      type: "message-added",
      snapshot: this.snapshot(),
      message,
  });
  await this.emit({
      type: "assistant-message",
      snapshot: this.snapshot(),
      iteration: this.state.iteration,
      message,
      finishReason,
  });
  ```

### 修复步骤建议

1. 确认 2.5 已在 `agent/events.py` 添加 `ASSISTANT_MESSAGE` 常量和 `make_assistant_message` 构造函数
2. 确认 `agent/runtime.py` 的 import（L66-94）已引入 `make_assistant_message`（2.5 步骤 4）
3. 修改 `agent/runtime.py` L550 之后的位置，在 `await self._emit(make_message_added(...))` 之后追加 emit `assistant-message`：
   ```python
   # 保存 assistant 消息
   final_assistant_message = message
   self._state.messages.append(message)
   await self._emit(make_message_added(self.snapshot(), message))
   # 对标 Cline agent-runtime.ts L665-671: emit assistant-message 事件
   # 携带 finish_reason，前端可据此区分 stop/tool-calls/max-tokens 等完成原因
   await self._emit(make_assistant_message(
       self.snapshot(),
       self._state.iteration,
       message,
       finish_reason,
   ))
   ```
4. 保留 L549 的 `final_assistant_message = message` 赋值不变
5. 保留 L552-559 后续的 max_tokens / error 判断逻辑不变

### 验证方法

1. 集成测试：运行 agent 主循环一轮（无工具调用），断言事件流中先收到 `message-added`，紧接收到 `assistant-message`，且 `assistant-message` 的 `finish_reason` 字段非 None（如 `"stop"`）
2. 集成测试：运行 agent 一轮（含工具调用），断言 `assistant-message` 的 `finish_reason == "tool-calls"`
3. 集成测试：触发 max_tokens（设置很小的 max_tokens），断言 `assistant-message` 的 `finish_reason == "max-tokens"`
4. 兼容性测试：确认 `message-added` 事件仍正常发射，前端监听 `message-added` 的逻辑不受影响
5. 前端验证：`static/js/ai-chat.js` 若需展示完成原因，可新增 `assistant-message` 监听（本阶段不强制改前端）

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：`finish_reason` 在 L526 由 `_generate_assistant_message` 返回，是字符串类型（`AgentModelFinishReason.STOP.value`），与 `make_assistant_message` 的 `finish_reason: str` 参数类型匹配
- 保留原函数逻辑：`message-added` 事件保留，`assistant-message` 是追加发射，不替换
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`finish_reason` 始终有值（默认 `AgentModelFinishReason.STOP.value`），无需兜底
- 与 2.5 的依赖关系：本任务依赖 2.5 已定义 `ASSISTANT_MESSAGE` 常量和 `make_assistant_message` 构造函数，实施顺序为先 2.5 后 2.8
- emit 顺序：先 `message-added`（通用），后 `assistant-message`（专用），与 Cline L660-671 一致，前端可据需选择监听

---

## 附录：实施顺序建议

按依赖关系和影响范围排序：

1. **2.1 LLM Provider abort 语义对齐**：独立修改，无依赖，影响 provider 层
2. **2.6 AbortController 幂等检查**：独立修改，无依赖，影响 abort.py 和 runtime.py
3. **2.2 类型系统消息片段补齐**：独立修改，无依赖，影响 types.py
4. **2.3 AgentTool/AgentModelEvent 类型安全增强**：依赖 2.2（类型系统），影响 types.py 和 runtime.py
5. **2.4 流式工具组装 nextToolIndex 时机修正**：独立修改，影响 runtime.py
6. **2.5 事件系统 assistant-message/tool-updated 补齐**：独立修改，影响 events.py 和 runtime.py
7. **2.8 主循环 emit assistant-message 补齐**：依赖 2.5（事件类型定义），影响 runtime.py
8. **2.7 AbortController 子进程 kill on abort**：核对为主，可能涉及 exec_tool.py 补齐

## 附录：一致性风险点

1. **2.3 A20 tuple 化**：需先 grep 确认无 listener/hook 调用 `snapshot.messages.append/extend`，否则会运行时报错
2. **2.5 _make_emit_update 签名扩展**：需同步修改调用方 L1364 传入 `tool_call_id`
3. **2.7 exec_tool.py**：若未实现 abort kill，需优先补齐，否则单命令工具的 abort 行为与 run_commands 不一致
4. **前端兼容性**：2.5/2.8 新增事件类型，前端 `static/js/ai-chat.js` 若需消费需同步增加监听（本阶段不强制改前端，向后兼容）
