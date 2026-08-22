# Agent 引擎迁移计划：从 nanobot 到 Cline 架构

> 历史归档：本文件记录 Phase 1-27 的完整迁移历程（已完成），保留作为"为什么这么改"的回溯依据。
> **后续新计划（Phase 28+）请见 [AGENT_PHASE28_PLAN.md](./AGENT_PHASE28_PLAN.md)**，本文件不再追加新章节。

> 目标：用 Python 重写 Cline 的核心 Agent 架构，替代现有 nanobot，实现类似 Trae/Cursor 的 AI 助手体验。
> 测试用例：东方电气(600875.SH)深度研报生成，使用 write-report / financial-analysis / read-pdf 三个技能。

---

## 一、架构总览

### 1.1 现有系统痛点

| 问题 | 根因 | Cline 的解法 |
|------|------|-------------|
| agent 不读 SKILL.md | 靠 prompt 祈求 agent read_file，不可靠 | use_skill 是正式工具，调用时强制加载 SKILL.md 全文 |
| 执行流程死板 | `<plan>` 硬编码，agent 机械执行 | 工具驱动，模型自主决定下一步；completes_run 工具结束运行 |
| prompt 架构重复 | AGENTS.md / SKILL.md / rules 三层重复 | 分层 prompt + 渐进式技能加载（metadata~100t → instructions<5k → resources） |
| 研报截断 | 上下文压缩后 agent 误以为搜索总结是最终答案 | 流式事件系统，text_delta / reasoning_delta / tool_call_delta 分离 |
| 工具选择随机 | 全量工具 schema 塞入 prompt | 工具注册表 + 按需加载 + tool policy 控制 |
| 中间思考混入正文 | 后端只发 phase:thinking，最终答案也进 thinking block | 事件类型明确区分 assistant_text_delta vs assistant_reasoning_delta |

### 1.2 新架构目录结构

```
CASE-AI量化系统/
├── agent/                              # 新 Agent 引擎（替代 nanobot）
│   ├── __init__.py                     # 包入口，导出主要类
│   ├── types.py                        # 核心类型定义（对标 @cline/shared/agent.ts）
│   ├── runtime.py                      # AgentRuntime 主循环（对标 agent-runtime.ts）
│   ├── events.py                       # 事件系统 + EventEmitter
│   ├── hooks.py                        # 生命周期钩子（对标 AgentRuntimeHooks）
│   ├── prompt.py                       # 系统提示分层构造器
│   ├── context.py                      # 上下文管理（compaction / token 预算）
│   ├── providers/                      # LLM 适配层（对标 @cline/llms gateway）
│   │   ├── __init__.py
│   │   ├── base.py                     # AgentModel 协议（对标 AgentModel 接口）
│   │   └── qwen.py                     # 通义千问适配器（stream + tool_calls）
│   ├── tools/                          # 工具系统（对标 @cline/core/extensions/tools）
│   │   ├── __init__.py
│   │   ├── base.py                     # AgentTool 基类 + ToolRegistry
│   │   ├── exec_tool.py                # 脚本执行工具
│   │   ├── file_tools.py              # 文件读写工具
│   │   ├── web_tools.py               # 网络搜索工具
│   │   └── skill_tool.py              # use_skill 工具（核心！）
│   └── skills/                         # 技能系统（对标 Cline skills）
│       ├── __init__.py
│       ├── loader.py                   # 渐进式技能加载器
│       └── registry.py                 # 技能注册表 + 元数据缓存
├── routes/
│   └── chat.py                         # SSE 路由（更新事件映射）
├── static/
│   ├── js/ai-chat.js                   # 前端逻辑（更新事件消费）
│   └── css/ai-chat.css                 # 样式（Trae 风格）
├── skills_config/                      # 技能 + 规则配置（从 charles-nanobot 迁移）
│   ├── skills/                         # SKILL.md 目录
│   │   ├── write-report/
│   │   ├── financial-analysis/
│   │   ├── read-pdf/
│   │   └── ...
│   ├── rules/                          # 任务规则
│   │   ├── report.md
│   │   ├── financial.md
│   │   └── ...
│   └── AGENTS.md                       # Agent 身份定义
└── third_party/charles_bundle/         # 旧系统保留（不删除，作为参考）
```

### 1.3 核心数据流

```
用户消息
  ↓
AgentRuntime.execute()
  ↓
┌─────────────────────────────────────────────────┐
│  主循环 (while iteration < max_iterations)      │
│                                                   │
│  1. beforeModel hooks                            │
│  2. model.stream(request) → 流式事件             │
│     ├─ text_delta → emit(assistant_text_delta)   │
│     ├─ reasoning_delta → emit(reasoning_delta)   │
│     ├─ tool_call_delta → 组装工具调用            │
│     └─ finish → 结束本轮                         │
│  3. afterModel hooks                             │
│  4. 如果有 tool_calls:                           │
│     ├─ beforeTool hooks（可 skip/modify input）  │
│     ├─ tool.execute(input, context)              │
│     ├─ afterTool hooks                           │
│     └─ emit(tool_result)                         │
│  5. 如果 tool.completes_run → 结束运行           │
│  6. 如果无 tool_calls → 结束运行                 │
└─────────────────────────────────────────────────┘
  ↓
事件流 → SSE → 前端渲染
```

---

## 二、Cline 核心模式移植清单

以下是从 Cline 移植的关键设计模式，每个都标注了 Cline 源码位置和移植目标：

### 2.1 AgentRuntime 主循环
- **Cline 源码**: `sdk/packages/agents/src/agent-runtime.ts` L595-794
- **移植到**: `agent/runtime.py`
- **关键模式**:
  - `execute()` 方法：while 循环 + iteration 计数 + abort 检查
  - `generate_assistant_message()`：流式消费 model.stream() 事件
  - `execute_tool_calls()`：支持 parallel / sequential 两种模式
  - `finish_run()`：正常完成 vs max_iterations 超限
  - `find_completing_tool()`：检查 tool.lifecycle.completes_run
  - `throw_if_aborted()`：每轮检查 abort 状态
  - **complete_run 机制**：工具可以标记 `completes_run=True`，执行成功后直接结束运行，防止 agent 空转

### 2.2 流式事件系统
- **Cline 源码**: `sdk/packages/agents/src/agent-runtime.ts` L913-1015 (stream消费) + `sdk/packages/shared/src/agent.ts` L232-257 (AgentModelEvent)
- **移植到**: `agent/events.py` + `agent/types.py`
- **关键模式**:
  - `AgentModelEvent` 类型：text_delta / reasoning_delta / tool_call_delta / usage / finish
  - 事件组装：text_delta 累积成 text part，tool_call_delta 累积成 tool_call part
  - `emit()` 方法：每个状态变更都发事件，listener 可订阅
  - 事件类型：run_started / turn_started / assistant_text_delta / assistant_reasoning_delta / message_added / turn_finished / run_finished / run_failed
  - **关键优势**：text_delta 和 reasoning_delta 分离，前端能区分"思考过程"和"最终回答"

### 2.3 AgentTool 接口
- **Cline 源码**: `sdk/packages/shared/src/agent.ts` L146-186
- **移植到**: `agent/types.py` + `agent/tools/base.py`
- **关键模式**:
  - `AgentToolDefinition`: name + description + input_schema + lifecycle
  - `AgentTool`: 继承 Definition + execute 方法 + timeout_ms + retryable
  - `AgentToolResult`: output + is_error + metadata
  - `AgentToolContext`: session_id / agent_id / run_id / iteration / signal / snapshot
  - **lifecycle.completes_run**: 工具执行成功后直接结束运行（如 attempt_completion）

### 2.4 AgentModel 协议
- **Cline 源码**: `sdk/packages/shared/src/agent.ts` L192-263
- **移植到**: `agent/providers/base.py`
- **关键模式**:
  - `AgentModelRequest`: system_prompt + messages + tools + signal + options
  - `AgentModel.stream(request) -> AsyncIterator[AgentModelEvent]`
  - 流式返回 text_delta / reasoning_delta / tool_call_delta / usage / finish
  - **关键优势**：统一接口，Qwen / OpenAI / Anthropic 都可实现此协议

### 2.5 Hooks 生命周期
- **Cline 源码**: `sdk/packages/agents/src/agent-runtime.ts` L229-237 (HookBag) + L544-554 (registerHooks) + L796-809 (callBeforeRunHooks/callAfterRunHooks)
- **移植到**: `agent/hooks.py`
- **6 个钩子点**:
  - `before_run(snapshot)`: 运行开始前，可 stop
  - `after_run(snapshot, result)`: 运行结束后
  - `before_model(snapshot, request)`: 每次调 LLM 前，可修改 messages/tools/options，可 stop
  - `after_model(snapshot, message, finish_reason)`: LLM 返回后，可 stop
  - `before_tool(snapshot, tool, tool_call, input)`: 工具执行前，可 skip/modify input/stop
  - `after_tool(snapshot, tool, tool_call, result, duration_ms)`: 工具执行后，可修改 result/stop
- **关键用途**:
  - `before_model`: 注入技能上下文、上下文压缩
  - `before_tool`: 权限控制、参数校验、日志记录
  - `after_tool`: 结果后处理、敏感信息过滤

### 2.6 prepareTurn 上下文压缩
- **Cline 源码**: `sdk/packages/agents/src/agent-runtime.ts` L1208-1250
- **移植到**: `agent/context.py`
- **关键模式**:
  - `prepare_turn()` 钩子：每轮调用 LLM 前执行
  - 可修改 messages（压缩旧消息）和 system_prompt
  - 返回修改后的 request
  - **关键优势**：不靠硬编码的 _snip_history，而是可配置的压缩策略

### 2.7 渐进式技能加载
- **Cline 源码**: `docs/customization/skills.mdx` + `sdk/packages/core/src/extensions/tools/`
- **移植到**: `agent/skills/loader.py` + `agent/tools/skill_tool.py`
- **三级加载**:
  - Level 1 - Metadata（启动时）：name + description，~100 tokens/技能
  - Level 2 - Instructions（触发时）：SKILL.md 正文，<5k tokens
  - Level 3 - Resources（按需）：scripts / docs / templates，仅输出进入上下文
- **use_skill 工具**: agent 调用 `use_skill(skill_name)` → 加载 SKILL.md 全文 → 返回给 agent
- **关键优势**：不靠 LLM 判断该用什么技能，而是让 agent 自己通过 tool_call 决定

### 2.8 系统提示分层构造
- **Cline 源码**: `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`
- **移植到**: `agent/prompt.py`
- **分层结构**:
  - Layer 1: 环境信息（时间、平台、工作目录）
  - Layer 2: Agent 身份（AGENTS.md）
  - Layer 3: 工具说明（自动从 tool definition 生成）
  - Layer 4: 技能概览（name + description，~100 tokens/技能）
  - Layer 5: 任务规则（rules/*.md）
  - Layer 6: 记忆（memory/MEMORY.md）
- **关键优势**：不把 SKILL.md 全文塞入 system prompt，只放概览；agent 需要时通过 use_skill 加载

---

## 三、分阶段实施计划

### Phase 1: 类型定义 + 事件系统（基础层）

**目标**: 建立所有核心类型契约，后续模块都依赖这些类型

**创建文件**:
1. `agent/__init__.py` — 包入口
2. `agent/types.py` — 核心类型定义
3. `agent/events.py` — 事件系统

**`agent/types.py` 内容**:
```python
# 对标 @cline/shared/agent.ts 的全部接口定义

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable, Protocol, runtime_checkable

# --- 消息类型 ---
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass
class TextPart:
    """文本消息片段"""
    type: str = "text"
    text: str = ""

@dataclass
class ReasoningPart:
    """推理/思考过程片段（对标 Cline reasoning-delta）"""
    type: str = "reasoning"
    text: str = ""
    redacted: bool = False

@dataclass
class ToolCallPart:
    """工具调用片段"""
    type: str = "tool-call"
    tool_call_id: str = ""
    tool_name: str = ""
    input: dict[str, Any] = field(default_factory=dict)

@dataclass
class ToolResultPart:
    """工具结果片段"""
    type: str = "tool-result"
    tool_call_id: str = ""
    tool_name: str = ""
    output: Any = None
    is_error: bool = False

MessagePart = TextPart | ReasoningPart | ToolCallPart | ToolResultPart

@dataclass
class AgentMessage:
    """对标 AgentMessage"""
    id: str
    role: MessageRole
    content: list[MessagePart] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

# --- 工具类型 ---
@dataclass
class ToolLifecycle:
    """工具生命周期标记"""
    completes_run: bool = False  # 执行成功后结束运行

@dataclass
class AgentToolDefinition:
    """对标 AgentToolDefinition — 工具的静态定义"""
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema
    lifecycle: ToolLifecycle | None = None

@dataclass
class AgentToolResult:
    """对标 AgentToolResult"""
    output: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentToolContext:
    """对标 AgentToolContext — 工具执行上下文"""
    session_id: str | None = None
    agent_id: str = ""
    conversation_id: str | None = None
    run_id: str | None = None
    iteration: int = 0
    tool_call_id: str | None = None
    snapshot: Any | None = None  # AgentRuntimeStateSnapshot
    emit_update: Callable[[Any], None] | None = None

@runtime_checkable
class AgentTool(AgentToolDefinition, Protocol):
    """对标 AgentTool — 可执行的工具"""
    timeout_ms: int | None
    retryable: bool
    max_retries: int
    def execute(self, input: Any, context: AgentToolContext) -> AsyncIterator[AgentToolResult] | AgentToolResult: ...

# --- 模型类型 ---
@dataclass
class AgentModelRequest:
    """对标 AgentModelRequest"""
    system_prompt: str | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    tools: list[AgentToolDefinition] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

class AgentModelFinishReason(str, Enum):
    STOP = "stop"
    TOOL_CALLS = "tool-calls"
    MAX_TOKENS = "max-tokens"
    ABORTED = "aborted"
    ERROR = "error"

@dataclass
class AgentModelEvent:
    """对标 AgentModelEvent — 模型流式事件"""
    type: str  # text-delta / reasoning-delta / tool-call-delta / usage / finish
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    input_text: str | None = None
    input_value: Any = None
    usage: dict[str, int] | None = None
    reason: AgentModelFinishReason | None = None
    error: str | None = None

@runtime_checkable
class AgentModel(Protocol):
    """对标 AgentModel — LLM 适配器协议"""
    async def stream(self, request: AgentModelRequest) -> AsyncIterator[AgentModelEvent]: ...

# --- 运行时状态 ---
@dataclass
class AgentUsage:
    """对标 AgentUsage"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_token_count: int = 0
    total_cost: float = 0.0

@dataclass
class AgentRuntimeStateSnapshot:
    """对标 AgentRuntimeStateSnapshot"""
    agent_id: str = ""
    agent_role: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    status: str = "idle"  # idle / running / completed / aborted / failed
    iteration: int = 0
    messages: list[AgentMessage] = field(default_factory=list)
    pending_tool_calls: list[str] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)
    last_error: str | None = None

@dataclass
class AgentRunResult:
    """对标 AgentRunResult"""
    agent_id: str = ""
    run_id: str = ""
    status: str = "completed"
    iterations: int = 0
    output_text: str | None = None
    messages: list[AgentMessage] = field(default_factory=list)
    usage: AgentUsage = field(default_factory=AgentUsage)
    error: Exception | None = None
```

**`agent/events.py` 内容**:
```python
# 事件发射器 + 事件类型定义

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

# 事件类型常量
RUN_STARTED = "run-started"
TURN_STARTED = "turn-started"
ASSISTANT_TEXT_DELTA = "assistant-text-delta"
ASSISTANT_REASONING_DELTA = "assistant-reasoning-delta"
MESSAGE_ADDED = "message-added"
TURN_FINISHED = "turn-finished"
RUN_FINISHED = "run-finished"
RUN_FAILED = "run-failed"
TOOL_EXECUTION_STARTED = "tool-execution-started"
TOOL_EXECUTION_FINISHED = "tool-execution-finished"
USAGE_UPDATED = "usage-updated"
STATUS_NOTICE = "status-notice"

@dataclass
class AgentEvent:
    """对标 AgentRuntimeEvent"""
    type: str
    snapshot: Any = None  # AgentRuntimeStateSnapshot
    iteration: int | None = None
    text: str | None = None
    accumulated_text: str | None = None
    message: Any = None  # AgentMessage
    finish_reason: str | None = None
    tool_call_count: int | None = None
    result: Any = None  # AgentRunResult
    error: Exception | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

class EventEmitter:
    """事件发射器 — 对标 AgentRuntime 的 emit() + listeners"""

    def __init__(self):
        self._listeners: list[Callable[[AgentEvent], Any]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, listener: Callable[[AgentEvent], Any]) -> Callable[[], None]:
        """订阅事件，返回取消订阅函数"""
        self._listeners.append(listener)
        def unsubscribe():
            if listener in self._listeners:
                self._listeners.remove(listener)
        return unsubscribe

    async def emit(self, event: AgentEvent) -> None:
        """发射事件给所有监听器"""
        for listener in self._listeners:
            result = listener(event)
            if asyncio.iscoroutine(result):
                await result
```

**验证方式**: `python -c "from agent.types import *; from agent.events import *; print('OK')"`

**Cline 对标**: `sdk/packages/shared/src/agent.ts` (全部接口) + `agent-runtime.ts` L399 (listeners) + L611/636/660/682/698/710/716/733 (emit 调用点)

---

### Phase 2: AgentRuntime 主循环 + Hooks

**目标**: 实现核心 Agent 循环，不依赖具体 LLM 和工具

**创建文件**:
1. `agent/hooks.py` — 钩子系统
2. `agent/runtime.py` — AgentRuntime 类

**`agent/hooks.py` 内容**:
```python
# 对标 AgentRuntimeHooks + HookBag
# 6 个钩子点: before_run / after_run / before_model / after_model / before_tool / after_tool

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

# --- 钩子上下文 ---
@dataclass
class BeforeRunContext:
    snapshot: Any

@dataclass
class AfterRunContext:
    snapshot: Any
    result: Any

@dataclass
class BeforeModelContext:
    snapshot: Any
    request: Any  # AgentModelRequest

@dataclass
class BeforeModelResult:
    stop: bool = False
    reason: str | None = None
    messages: list | None = None
    tools: list | None = None
    options: dict | None = None

@dataclass
class AfterModelContext:
    snapshot: Any
    assistant_message: Any  # AgentMessage
    finish_reason: str

@dataclass
class BeforeToolContext:
    snapshot: Any
    tool: Any  # AgentTool
    tool_call: Any  # ToolCallPart
    input: Any

@dataclass
class BeforeToolResult:
    skip: bool = False
    stop: bool = False
    reason: str | None = None
    input: Any | None = None

@dataclass
class AfterToolContext:
    snapshot: Any
    tool: Any
    tool_call: Any
    input: Any
    result: Any  # AgentToolResult
    started_at: Any  # datetime
    ended_at: Any
    duration_ms: int

@dataclass
class AfterToolResult:
    stop: bool = False
    reason: str | None = None
    result: Any | None = None

# --- 钩子函数类型 ---
HookCallable = Callable[[Any], Awaitable[Any | None]]

@dataclass
class AgentHooks:
    """对标 AgentRuntimeHooks — 可选实现任意子集"""
    before_run: HookCallable | None = None
    after_run: HookCallable | None = None
    before_model: HookCallable | None = None
    after_model: HookCallable | None = None
    before_tool: HookCallable | None = None
    after_tool: HookCallable | None = None
```

**`agent/runtime.py` 内容**（核心，对标 agent-runtime.ts L595-794）:
```python
# 对标 AgentRuntime 类

class AgentRuntime:
    """Agent 运行时 — 对标 Cline AgentRuntime"""

    def __init__(self, config: AgentRuntimeConfig):
        self.config = config
        self._emitter = EventEmitter()
        self._tools: dict[str, AgentTool] = {}
        self._hooks = HookBag()
        self._abort_flag = False
        self._state = RuntimeState()

    # --- 公开接口 ---
    def register_tool(self, tool: AgentTool) -> None: ...
    def register_hooks(self, hooks: AgentHooks) -> None: ...
    def subscribe(self, listener) -> Callable[[], None]: ...
    def abort(self, reason: str = "") -> None: ...
    def snapshot(self) -> AgentRuntimeStateSnapshot: ...

    async def run(self, input: str | AgentMessage | list[AgentMessage]) -> AgentRunResult:
        """主入口 — 对标 execute()"""
        # 1. 初始化状态
        # 2. call_before_run_hooks()
        # 3. emit(run_started)
        # 4. 添加输入消息
        # 5. while iteration < max_iterations:
        #      a. throw_if_aborted()
        #      b. emit(turn_started)
        #      c. message, finish_reason = await generate_assistant_message()
        #      d. emit(message_added, assistant_message)
        #      e. tool_calls = extract_tool_calls(message)
        #      f. if no tool_calls: finish_run("completed")
        #      g. tool_messages = await execute_tool_calls(tool_calls)
        #      h. emit(message_added for each tool_message)
        #      i. if completes_run tool succeeded: finish_run("completed")
        #      j. emit(turn_finished)
        # 6. catch: emit(run_failed) or emit(run_finished)
        # 7. finally: cleanup

    async def _generate_assistant_message(self) -> tuple[AgentMessage, str]:
        """对标 generateAssistantMessage() L811-1077"""
        # 1. 构建 AgentModelRequest (system_prompt + messages + tools)
        # 2. call_before_model_hooks()
        # 3. stream = await model.stream(request)
        # 4. for event in stream:
        #      - text_delta → 累积文本, emit(assistant_text_delta)
        #      - reasoning_delta → 累积推理, emit(assistant_reasoning_delta)
        #      - tool_call_delta → 组装工具调用
        #      - usage → 更新 usage
        #      - finish → 记录 finish_reason
        # 5. 组装 AgentMessage (text parts + reasoning parts + tool_call parts)
        # 6. call_after_model_hooks()
        # 7. return message, finish_reason

    async def _execute_tool_calls(self, tool_calls: list[ToolCallPart]) -> list[AgentMessage]:
        """对标 executeToolCalls() L1291-1310"""
        # 支持 parallel / sequential 两种模式
        # 每个 tool_call:
        #   1. resolve tool from registry
        #   2. call_before_tool_hooks() — 可 skip/modify
        #   3. tool.execute(input, context)
        #   4. call_after_tool_hooks()
        #   5. 构建 tool result message

    def _find_completing_tool(self, tool_calls, tool_messages) -> AgentMessage | None:
        """对标 findCompletingToolMessage() L1312-1332"""
        # 检查 tool.lifecycle.completes_run == True 且执行成功
```

**验证方式**: 用 Mock AgentModel（返回固定文本）测试主循环，验证事件流

**Cline 对标**: `agent-runtime.ts` 全文

---

### Phase 3: Qwen Provider 适配器

**目标**: 连接通义千问 API，实现 AgentModel 协议

**创建文件**:
1. `agent/providers/__init__.py`
2. `agent/providers/base.py` — AgentModel 协议（从 types.py 导入）
3. `agent/providers/qwen.py` — Qwen 适配器

**`agent/providers/qwen.py` 核心逻辑**:
```python
# 对标 Cline gateway provider，适配 DashScope API

class QwenModel:
    """通义千问 AgentModel 实现"""

    def __init__(self, model: str = "qwen-plus", api_key: str | None = None,
                 max_tokens: int = 8192, temperature: float = 0.1):
        self.model = model
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def stream(self, request: AgentModelRequest) -> AsyncIterator[AgentModelEvent]:
        """调用 DashScope 兼容模式 API，流式返回事件

        对标 Cline AgentModel.stream()

        关键逻辑:
        1. 将 AgentModelRequest 转为 OpenAI 兼容格式
           - system_prompt → messages[0] = {"role": "system", "content": ...}
           - messages → 转换 AgentMessage 为 OpenAI message 格式
           - tools → 转为 OpenAI function calling 格式
        2. 调用 dashscope SSE 接口
        3. 解析 SSE chunk，转为 AgentModelEvent:
           - delta.content → text_delta
           - delta.reasoning_content → reasoning_delta (qwen-plus 支持)
           - delta.tool_calls → tool_call_delta
           - usage → usage event
           - finish_reason → finish event
        4. yield 每个事件
        """
```

**关键实现细节**:
- 使用 `dashscope` SDK 或直接 HTTP SSE 调用兼容模式
- `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- 流式解析 `stream=true` 的 SSE 响应
- 工具调用格式：OpenAI function calling 兼容
- reasoning_content：qwen-plus 思考模式返回的字段

**验证方式**: 单独测试 `QwenModel.stream()`，打印事件流

**依赖**: Phase 1 (types.py)

---

### Phase 4: 工具系统

**目标**: 实现工具注册表 + 移植现有工具

**创建文件**:
1. `agent/tools/__init__.py`
2. `agent/tools/base.py` — AgentTool 基类 + ToolRegistry
3. `agent/tools/exec_tool.py` — 脚本执行
4. `agent/tools/file_tools.py` — 文件读写
5. `agent/tools/web_tools.py` — 网络搜索

**`agent/tools/base.py` 核心逻辑**:
```python
# 对标 Cline createBuiltinTools + ToolRegistry

class BaseTool(AgentToolDefinition):
    """工具基类 — 子类实现 execute()"""
    timeout_ms: int | None = None
    retryable: bool = False
    max_retries: int = 0

    async def execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        raise NotImplementedError

    def to_definition(self) -> AgentToolDefinition:
        """转换为 LLM 可见的工具定义"""
        return AgentToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            lifecycle=self.lifecycle,
        )

class ToolRegistry:
    """对标 Cline tools Map — 工具注册表"""
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None: ...
    def get(self, name: str) -> BaseTool | None: ...
    def get_definitions(self) -> list[AgentToolDefinition]: ...
    def __iter__(self): ...
```

**`agent/tools/exec_tool.py`** — 移植自 nanobot `tools/shell.py`:
```python
class ExecTool(BaseTool):
    """执行 Python 脚本 — 对标 Cline run_commands / BashTool

    移植自 nanobot agent/tools/shell.py，保留原有逻辑:
    - subprocess 异步执行
    - 超时控制 (默认 600s)
    - PYTHONUNBUFFERED=1 实时输出
    - 工作目录设为项目根目录
    """
    name = "exec"
    description = "执行 Python 脚本或命令..."
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"}
        },
        "required": ["command"]
    }
    timeout_ms = 600_000
```

**`agent/tools/file_tools.py`** — 移植自 nanobot `tools/filesystem.py`:
```python
class ReadFileTool(BaseTool):
    name = "read_file"
    # 移植自 nanobot filesystem.py 的 read 逻辑

class WriteFileTool(BaseTool):
    name = "write_file"
    # 移植自 nanobot filesystem.py 的 write 逻辑

class ListDirTool(BaseTool):
    name = "list_dir"
    # 移植自 nanobot filesystem.py 的 list 逻辑
```

**`agent/tools/web_tools.py`** — 移植自 nanobot `tools/web.py`:
```python
class WebSearchTool(BaseTool):
    name = "web_search"
    # 移植自 nanobot web.py 的 Tavily 搜索逻辑

class WebFetchTool(BaseTool):
    name = "web_fetch"
    # 移植自 nanobot web.py 的 URL 抓取逻辑
```

**验证方式**: 注册工具到 ToolRegistry，手动调用 execute() 测试

**依赖**: Phase 1 (types.py)
**Cline 对标**: `sdk/packages/core/src/extensions/tools/definitions.ts` + `sdk/packages/core/src/extensions/tools/runtime.ts`

---

### Phase 5: 技能系统（核心！）

**目标**: 实现渐进式技能加载 + use_skill 工具

**创建文件**:
1. `agent/skills/__init__.py`
2. `agent/skills/loader.py` — 技能加载器
3. `agent/skills/registry.py` — 技能注册表
4. `agent/tools/skill_tool.py` — use_skill 工具

**`agent/skills/loader.py` 核心逻辑**:
```python
# 对标 Cline skills 渐进式加载 + nanobot SkillsLoader

class SkillLoader:
    """技能加载器 — 三级渐进式加载

    Level 1 - Metadata（启动时）: name + description + keywords
    Level 2 - Instructions（触发时）: SKILL.md 正文
    Level 3 - Resources（按需）: scripts / docs / references
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._metadata_cache: dict[str, SkillMetadata] = {}

    def load_all_metadata(self) -> list[SkillMetadata]:
        """Level 1: 扫描所有 SKILL.md，提取 frontmatter

        对标 Cline: 启动时加载所有技能的 name + description
        对标 nanobot: SkillsLoader.list_skills() + build_skills_summary()
        """
        # 遍历 skills_dir/*/SKILL.md
        # 解析 YAML frontmatter
        # 缓存 SkillMetadata(name, description, keywords, source_path)

    def load_instructions(self, skill_name: str) -> str | None:
        """Level 2: 加载 SKILL.md 正文（去掉 frontmatter）

        对标 Cline: use_skill 触发时加载 instructions
        对标 nanobot: SkillsLoader.load_skill() + _strip_frontmatter()
        """
        # 读取 SKILL.md，去掉 frontmatter，返回正文

    def get_skill_path(self, skill_name: str) -> Path | None:
        """获取技能目录路径（用于执行脚本）"""
```

**`agent/skills/registry.py` 核心逻辑**:
```python
@dataclass
class SkillMetadata:
    """技能元数据 — Level 1 加载内容"""
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    source_path: str = ""

class SkillRegistry:
    """技能注册表 — 管理技能发现和加载"""

    def __init__(self, loader: SkillLoader):
        self.loader = loader
        self._all_skills: list[SkillMetadata] = []

    def initialize(self):
        """启动时加载所有技能元数据"""
        self._all_skills = self.loader.load_all_metadata()

    def get_all_metadata(self) -> list[SkillMetadata]:
        """返回所有技能元数据（Level 1）"""
        return self._all_skills

    def get_skill(self, name: str) -> SkillMetadata | None: ...

    def load_instructions(self, name: str) -> str | None:
        """加载技能指令（Level 2）"""
        return self.loader.load_instructions(name)

    def build_skills_summary(self) -> str:
        """构建技能概览文本（放入 system prompt）

        对标 nanobot build_skills_summary()，但更简洁:
        每个技能一行: name: description
        """
```

**`agent/tools/skill_tool.py` 核心逻辑**:
```python
# 对标 Cline use_skill 工具 — 这是解决"agent 不读 SKILL.md"的关键

class UseSkillTool(BaseTool):
    """use_skill 工具 — 加载技能指令

    agent 通过 tool_call 调用此工具，工具返回 SKILL.md 全文。
    这比"在 prompt 里要求 agent read_file"可靠得多。

    lifecycle.completes_run = False（加载技能后继续运行）
    """

    name = "use_skill"
    description = "加载指定技能的详细指令。当任务需要特定技能时调用此工具。"
    input_schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "要加载的技能名称"
            }
        },
        "required": ["skill_name"]
    }

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    async def execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        skill_name = input.get("skill_name", "")
        instructions = self.registry.load_instructions(skill_name)
        if instructions is None:
            return AgentToolResult(
                output=f"Error: 技能 '{skill_name}' 不存在。可用技能: {[s.name for s in self.registry.get_all_metadata()]}",
                is_error=True
            )
        # 返回 SKILL.md 全文给 agent
        return AgentToolResult(output=instructions)
```

**验证方式**: 加载所有技能元数据，调用 use_skill 获取 write-report 指令

**依赖**: Phase 1 (types.py), Phase 4 (base.py)
**Cline 对标**: `docs/customization/skills.mdx` + `sdk/packages/core/src/extensions/tools/`
**nanobot 对标**: `agent/skills.py` (SkillsLoader)

---

### Phase 6: 系统提示构造 + 上下文管理

**目标**: 分层构造 system prompt + 上下文压缩

**创建文件**:
1. `agent/prompt.py` — 系统提示构造器
2. `agent/context.py` — 上下文管理

**`agent/prompt.py` 核心逻辑**:
```python
# 对标 Cline runtime-builder.ts 的 systemPrompt 构造

class SystemPromptBuilder:
    """分层构造系统提示

    Layer 1: 环境信息（时间、平台、工作目录）
    Layer 2: Agent 身份（AGENTS.md）
    Layer 3: 工具说明（自动生成）
    Layer 4: 技能概览（name + description，~100 tokens/技能）
    Layer 5: 任务规则（rules/*.md）
    Layer 6: 记忆（memory/MEMORY.md）
    """

    def __init__(self, workspace: Path, skills_registry: SkillRegistry,
                 tools_registry: ToolRegistry):
        self.workspace = workspace
        self.skills = skills_registry
        self.tools = tools_registry

    def build(self, task_type: str = "general") -> str:
        """构造完整 system prompt"""
        parts = []
        parts.append(self._build_environment())    # Layer 1
        parts.append(self._build_identity())       # Layer 2: AGENTS.md
        parts.append(self._build_tools_section())  # Layer 3: 自动生成
        parts.append(self._build_skills_summary()) # Layer 4: 技能概览
        parts.append(self._build_rules(task_type)) # Layer 5: rules
        parts.append(self._build_memory())         # Layer 6: memory
        return "\n\n---\n\n".join(p for p in parts if p)

    def _build_environment(self) -> str:
        """环境信息: 时间、平台、时区"""

    def _build_identity(self) -> str:
        """读取 AGENTS.md"""

    def _build_tools_section(self) -> str:
        """从 ToolRegistry 自动生成工具说明"""

    def _build_skills_summary(self) -> str:
        """技能概览: 每个技能一行 name: description
        指示 agent: 需要使用技能时调用 use_skill 工具加载详细指令
        """

    def _build_rules(self, task_type: str) -> str:
        """读取 rules/{task_type}.md"""

    def _build_memory(self) -> str:
        """读取 memory/MEMORY.md"""
```

**`agent/context.py` 核心逻辑**:
```python
# 对标 Cline prepareTurn + nanobot _snip_history

class ContextManager:
    """上下文管理 — token 预算 + 消息压缩

    实现 before_model hook，每轮调用 LLM 前检查 token 数，
    超过阈值时压缩旧消息。
    """

    def __init__(self, context_window_tokens: int = 65536,
                 max_tool_result_chars: int = 16000):
        self.context_window = context_window_tokens
        self.max_tool_result_chars = max_tool_result_chars

    async def before_model(self, ctx: BeforeModelContext) -> BeforeModelResult | None:
        """before_model hook — 压缩上下文

        1. 估算当前 messages 的 token 数
        2. 如果超过 context_window * 0.8:
           a. 保留最近 N 轮消息
           b. 旧消息压缩为摘要
           c. 工具结果截断到 max_tool_result_chars
        3. 返回修改后的 messages
        """

    def _estimate_tokens(self, messages: list[AgentMessage]) -> int:
        """估算消息 token 数"""

    def _compact_messages(self, messages: list[AgentMessage],
                          keep_recent: int = 10) -> list[AgentMessage]:
        """压缩旧消息: 保留最近 N 轮，旧消息合并为摘要"""

    def _truncate_tool_results(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        """截断过长的工具结果"""
```

**验证方式**: 构造 system prompt，检查分层内容正确

**依赖**: Phase 1, Phase 4, Phase 5
**Cline 对标**: `runtime-builder.ts` (systemPrompt) + `agent-runtime.ts` L1208-1250 (prepareTurn)
**nanobot 对标**: `context.py` (ContextBuilder) + `runner.py` (_snip_history)

---

### Phase 7: 集成 — 替换 chat.py 后端

**目标**: 用新 AgentRuntime 替换 nanobot，保持 SSE 接口

**修改文件**:
1. `routes/chat.py` — 替换 nanobot 加载逻辑

**核心改动**:
```python
# routes/chat.py 更新

# 旧: 从 charles-nanobot 加载 build_bot()
# 新: 构建新 AgentRuntime

from agent.runtime import AgentRuntime
from agent.providers.qwen import QwenModel
from agent.tools.exec_tool import ExecTool
from agent.tools.file_tools import ReadFileTool, WriteFileTool, ListDirTool
from agent.tools.web_tools import WebSearchTool, WebFetchTool
from agent.tools.skill_tool import UseSkillTool
from agent.skills.registry import SkillRegistry, SkillLoader
from agent.prompt import SystemPromptBuilder
from agent.context import ContextManager
from agent.hooks import AgentHooks

def _build_agent_runtime() -> AgentRuntime:
    """构建 AgentRuntime 实例"""
    workspace = Path(__file__).resolve().parent.parent
    skills_dir = workspace / "skills_config" / "skills"

    # 1. 技能系统
    loader = SkillLoader(skills_dir)
    registry = SkillRegistry(loader)
    registry.initialize()

    # 2. 工具系统
    tools = ToolRegistry()
    tools.register(ExecTool(workspace=workspace))
    tools.register(ReadFileTool(workspace=workspace))
    tools.register(WriteFileTool(workspace=workspace))
    tools.register(ListDirTool(workspace=workspace))
    tools.register(WebSearchTool())
    tools.register(WebFetchTool())
    tools.register(UseSkillTool(registry))  # 关键！

    # 3. 系统提示
    prompt_builder = SystemPromptBuilder(workspace, registry, tools)

    # 4. 模型
    model = QwenModel(model="qwen-plus")

    # 5. 上下文管理
    context_mgr = ContextManager(context_window_tokens=65536)

    # 6. AgentRuntime
    runtime = AgentRuntime(config=AgentRuntimeConfig(
        model=model,
        system_prompt=prompt_builder.build(),
        tools=tools,
        max_iterations=50,
        tool_execution="sequential",
    ))
    runtime.register_hooks(AgentHooks(
        before_model=context_mgr.before_model,
    ))

    return runtime

# SSE 生成器更新:
# 旧: _StreamCollectorHook + nanobot AgentLoop
# 新: AgentRuntime.subscribe() → SSE 事件映射

async def _sse_generator(message: str, session_id: str, history: list):
    runtime = _build_agent_runtime()

    # 事件映射: AgentRuntime 事件 → SSE 事件
    event_queue: asyncio.Queue = asyncio.Queue()

    async def on_event(event: AgentEvent):
        if event.type == ASSISTANT_TEXT_DELTA:
            await event_queue.put(("token", {"text": event.text}))
        elif event.type == ASSISTANT_REASONING_DELTA:
            await event_queue.put(("thinking", {"text": event.text}))
        elif event.type == TOOL_EXECUTION_STARTED:
            await event_queue.put(("tool_call", {
                "name": event.metadata.get("tool_name", ""),
                "args": event.metadata.get("args", ""),
                "idx": event.metadata.get("idx", 0),
            }))
        elif event.type == TOOL_EXECUTION_FINISHED:
            await event_queue.put(("tool_output", {
                "output": event.metadata.get("output", ""),
                "error": event.metadata.get("is_error", False),
                "idx": event.metadata.get("idx", ""),
            }))
        elif event.type == RUN_STARTED:
            await event_queue.put(("phase", {"phase": "thinking"}))
        elif event.type == RUN_FINISHED:
            await event_queue.put(("phase", {"phase": "answering"}))
            await event_queue.put(("done", {}))

    runtime.subscribe(on_event)

    # 启动运行
    task = asyncio.create_task(runtime.run(message))

    # 流式输出事件
    while True:
        try:
            kind, payload = await asyncio.wait_for(event_queue.get(), timeout=600)
        except asyncio.TimeoutError:
            yield _sse_event("error", {"text": "超时"})
            break

        if kind == "done":
            break
        yield _sse_event(kind, payload)

    await task  # 等待完成
    yield _sse_event("done", {})
```

**验证方式**: 用 curl 或前端测试 `/api/chat/stream`，验证 SSE 事件流

**依赖**: Phase 1-6 全部完成

---

### Phase 8: 前端更新

**目标**: 更新前端消费新事件格式，实现 Trae 风格 UI

**修改文件**:
1. `static/js/ai-chat.js` — 事件消费逻辑
2. `static/css/ai-chat.css` — 样式调整

**核心改动**:

1. **新增事件类型处理**:
```javascript
// 新增 thinking 事件（推理过程，与 token 区分）
case 'thinking':
    this.appendThinking(data.text);
    break;

// tool_call 事件增加 status 跟踪
case 'tool_call':
    this.startToolBlock(data);
    break;

// tool_output 事件标记完成
case 'tool_output':
    this.finishToolBlock(data);
    break;
```

2. **UI 分区明确**:
   - 推理过程（thinking）: 灰色折叠区域，小字体
   - 工具调用（tool_call/tool_output）: 卡片式，可展开
   - 最终回答（token + phase:answering）: 正文区域，markdown 渲染
   - 计划（plan）: 独立卡片，步骤式

3. **Trae 风格布局**:
   - 左侧对话列表保持
   - 右侧对话区: 消息气泡 + 工具卡片 + 推理折叠
   - 底部输入框: 固定位置
   - 新增停止按钮（abort）

4. **对话持久化**: 保持 localStorage 存储对话历史

**验证方式**: 在浏览器中测试东方电气研报生成，验证 UI 展示

**依赖**: Phase 7

---

### Phase 9: 技能迁移 + 测试

**目标**: 迁移所有技能和规则到新位置，端到端测试

**操作**:
1. 复制 `charles-nanobot/skills/` → `skills_config/skills/`
2. 复制 `charles-nanobot/rules/` → `skills_config/rules/`
3. 复制 `charles-nanobot/AGENTS.md` → `skills_config/AGENTS.md`
4. 更新 SKILL.md frontmatter 格式（统一为 name + description）
5. 端到端测试: "帮我写一份东方电气(600875.SH)的深度研报"

**测试检查点**:
- [ ] agent 自主调用 use_skill 加载 write-report 技能
- [ ] agent 按五步法格式输出研报
- [ ] agent 调用 financial-analysis 获取财务数据
- [ ] agent 调用 read-pdf 查询年报 RAG
- [ ] agent 调用 web_search 获取最新信息
- [ ] 推理过程和最终研报在前端正确分区显示
- [ ] 工具调用过程可折叠查看
- [ ] 研报完整输出不被截断
- [ ] 对话可中止（abort 按钮）

**依赖**: Phase 1-8 全部完成

---

## 四、阶段依赖关系

```
Phase 1 (类型+事件)
  ├── Phase 2 (Runtime+Hooks)    ← 依赖 Phase 1
  ├── Phase 4 (工具系统)          ← 依赖 Phase 1
  └── Phase 5 (技能系统)          ← 依赖 Phase 1, 4
       │
Phase 3 (Qwen Provider)           ← 依赖 Phase 1
       │
Phase 6 (Prompt+Context)          ← 依赖 Phase 1, 4, 5
       │
Phase 7 (后端集成)                ← 依赖 Phase 1-6
       │
Phase 8 (前端更新)                ← 依赖 Phase 7
       │
Phase 9 (技能迁移+测试)           ← 依赖 Phase 1-8
```

**可并行的阶段**:
- Phase 2 和 Phase 3 可并行（都只依赖 Phase 1）
- Phase 4 可与 Phase 2/3 并行（只依赖 Phase 1）
- Phase 5 依赖 Phase 4，但可先写 loader 再写 skill_tool

---

## 五、Cline 关键优化清单（必须移植）

以下是从 Cline 中识别的关键优化，不能遗漏：

| # | 优化项 | Cline 位置 | 移植到 | 为什么重要 |
|---|--------|-----------|--------|-----------|
| 1 | completes_run 工具生命周期 | agent.ts L150-155 | types.py ToolLifecycle | 防止 agent 任务完成后空转 |
| 2 | text_delta / reasoning_delta 分离 | agent.ts L233-237 | events.py | 前端区分思考 vs 回答 |
| 3 | before_tool hook 可 skip | agent.ts L300-306 | hooks.py | 权限控制、参数修改 |
| 4 | prepareTurn 上下文压缩 | agent-runtime.ts L1208 | context.py | 防止上下文溢出 |
| 5 | use_skill 渐进式加载 | skills.mdx | skill_tool.py | 解决"不读 SKILL.md" |
| 6 | 事件驱动（非回调） | agent-runtime.ts L399 | events.py | 解耦 runtime 和传输层 |
| 7 | abort 机制 | agent-runtime.ts L454 | runtime.py | 用户可中止运行 |
| 8 | usage 追踪 | agent-runtime.ts L1271 | runtime.py | token 成本监控 |
| 9 | 工具输入 JSON 修复 | agent-runtime.ts L1366 | runtime.py | LLM 返回的 JSON 格式不规范时自动修复 |
| 10 | max_tokens 检测 | agent-runtime.ts L673 | runtime.py | 检测截断并报错 |
| 11 | 工具结果截断 | context.py | context.py | 防止单个工具结果撑爆上下文 |
| 12 | empty response 检测 | agent-runtime.ts L646 | runtime.py | LLM 返回空时的错误处理 |

---

## 六、风险与对策

| 风险 | 对策 |
|------|------|
| Qwen API 的 tool_call 格式与 OpenAI 不完全一致 | Phase 3 中充分测试 tool_call_delta 解析 |
| 前端改动影响现有对话历史 | Phase 8 保持 localStorage 格式兼容 |
| 技能脚本路径变化 | Phase 9 中统一路径为 skills_config/skills/ |
| 上下文压缩策略不当导致信息丢失 | Phase 6 中保留最近 10 轮 + 旧消息摘要 |
| agent 仍不调用 use_skill | system prompt 中明确指示 + 技能 description 写清楚触发条件 |

---

## 七、实施节奏建议

每个 Phase 完成后验证再进入下一个，避免积累问题。Phase 1-3 完成后可做第一次端到端测试（Mock 工具 + Qwen 对话），Phase 4-6 完成后做第二次测试（真实工具 + 技能），Phase 7-9 完成后做最终测试。

每个 Phase 的上下文需求约 1-2 万 token（读 Cline 源码 + 写 Python 代码），可以在单个对话中完成。

---

## 八、彻底重构计划（Phase 10-15）

> 背景：Phase 1-9 完成了 Cline 架构的"壳"，但 `use_skill` 仅返回 SKILL.md 文本（无 sub-agent 隔离）、`exec` 是通用 BashTool、ContextCompactor 未接入 LLM 也未挂到 runtime、缺 TodoWrite/Plan Mode。这些是"用 Cline 的壳装 nanobot 的魂"，必须彻底重构。

### 8.1 重构范围与对标

| Phase | 重构项 | 当前问题 | Cline 对标源码 |
|-------|--------|---------|---------------|
| 10 | Sub-agent 化 | `SkillTool` 仅返回文本 | `spawn-agent-tool.ts` + `delegated-agent.ts` |
| 11 | 结构化工具系统 | `exec` 单命令字符串 | `schemas.ts` RunCommandsInputSchema + ReadFilesInputSchema |
| 12 | TodoWrite + Plan Mode | 完全缺失 | `cline.ts` PLAN_MODE_INSTRUCTIONS + `sdk-session-config-builder.ts` switch_to_act_mode |
| 13 | LLM 上下文压缩接入 | 简单截断、未挂 runtime | `compaction.ts` runAgenticCompaction + createContextCompactionPrepareTurn |
| 14 | AGENTS.md + SKILL.md Cline 化 | 残留 nanobot 风格 | `cline.ts` buildClineSystemPrompt |
| 15 | 前端 Cursor/Trae/Cline 风格 | 现有 UI 朴素 | Trae/Cursor sub-agent 嵌套、TodoList 卡片 |

---

### Phase 10: Sub-agent 化（核心！）

**目标**: `use_skill` 真正创建独立子 runtime 执行技能，隔离上下文

**为什么关键**: 这是 Cline 与 nanobot 的本质区别。当前 `SkillTool` 把 SKILL.md 文本塞回主对话，导致技能指令被主上下文稀释，长 SKILL.md（如 write-report 含五步法）会污染主对话，研报易截断。Cline 的 `spawn_agent` 创建独立 `SessionRuntime`，注入专用 system prompt + 受限工具集，技能在隔离环境执行，结果以文本形式回流主 agent。

**Cline 对标**:
- `third_party/cline/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts` — SpawnAgentInputSchema + createSpawnAgentTool
- `third_party/cline/sdk/packages/core/src/extensions/tools/team/delegated-agent.ts` — createDelegatedAgent + buildDelegatedAgentConfig
- `third_party/cline/sdk/packages/core/src/extensions/tools/team/subagent-prompts.ts` — buildSubAgentSystemPrompt

**创建文件**:
1. `agent/skills/sub_agent.py` — SubAgentRuntime 工厂
2. 修改 `agent/skills/skill_tool.py` — 重写为 spawn_agent 语义

**`agent/skills/sub_agent.py` 核心逻辑**:
```python
# 对标 Cline createDelegatedAgent + buildSubAgentSystemPrompt

class SubAgentFactory:
    """子 Agent 工厂 — 对标 Cline createDelegatedAgent

    为技能执行创建独立的 AgentRuntime，注入:
        1. 技能 SKILL.md 作为 override system prompt
        2. 受限工具集（仅 file_read + run_commands + web_search + 技能自有工具）
        3. 独立的消息历史（不共享主 agent 上下文）
        4. 独立的 iteration 计数（防止子 agent 死循环）
    """

    def __init__(
        self,
        model: AgentModel,  # 复用主 agent 的 LLM
        workspace_root: str,
        max_iterations: int = 20,  # 子 agent 迭代上限
    ):
        self.model = model
        self.workspace_root = workspace_root
        self.max_iterations = max_iterations

    def create_for_skill(
        self,
        skill_name: str,
        instructions: str,
        task: str,
        parent_agent_id: str,
        allowed_tools: list[str] | None = None,  # None = 默认受限工具集
    ) -> AgentRuntime:
        """为技能执行创建子 agent — 对标 buildDelegatedAgentConfig

        Args:
            skill_name: 技能名称
            instructions: SKILL.md 正文（作为 override system prompt）
            task: 子 agent 要执行的任务
            parent_agent_id: 父 agent ID（用于事件追溯）
            allowed_tools: 允许子 agent 使用的工具名列表

        Returns:
            配置好的 AgentRuntime，调用 .run(task) 执行
        """
        # 构造子 agent system prompt — 对标 buildSubAgentSystemPrompt
        system_prompt = self._build_sub_agent_prompt(skill_name, instructions)

        # 创建子 runtime — 对标 createDelegatedAgent
        sub_runtime = AgentRuntime(config=AgentRuntimeConfig(
            model=self.model,
            system_prompt=system_prompt,
            max_iterations=self.max_iterations,
            parent_agent_id=parent_agent_id,
            agent_role=f"subagent:{skill_name}",
            tool_execution="sequential",  # 子 agent 用串行更稳
        ))

        # 注册受限工具集 — 对标 config.subAgentTools
        for tool in self._get_restricted_tools(allowed_tools):
            sub_runtime.register_tool(tool)

        return sub_runtime

    def _build_sub_agent_prompt(self, skill_name: str, instructions: str) -> str:
        """构造子 agent system prompt — 对标 buildSubAgentSystemPrompt

        结构:
            1. 工作环境（cwd、platform）
            2. 技能角色（"你是 {skill_name} 技能执行器"）
            3. SKILL.md 正文（override prompt）
            4. 输出要求（"完成后用 attempt_completion 工具返回结果"）
        """
        return (
            f"# 工作环境\n"
            f"- 工作目录: {self.workspace_root}\n"
            f"- 平台: windows\n\n"
            f"# 技能角色\n"
            f"你是 {skill_name} 技能执行器，按照以下指令执行任务：\n\n"
            f"# 技能指令\n{instructions}\n\n"
            f"# 输出要求\n"
            f"任务完成后调用 attempt_completion 工具返回最终结果文本。"
        )

    def _get_restricted_tools(self, allowed: list[str] | None) -> list[AgentTool]:
        """获取子 agent 受限工具集 — 对标 config.subAgentTools

        默认工具集（无 spawn_agent / 无 use_skill，防止嵌套递归）:
            - read_files
            - run_commands
            - web_search
            - attempt_completion（completes_run=True）
        """
        if allowed is None:
            allowed = ["read_files", "run_commands", "web_search", "attempt_completion"]
        # 从主 tool registry 解析并实例化
        ...
```

**修改 `agent/skills/skill_tool.py`** — 重写为 spawn_agent 语义:
```python
class SkillTool(BaseTool):
    """use_skill 工具 — 对标 Cline spawn_agent tool

    调用此工具时:
        1. 加载技能 SKILL.md 指令
        2. 通过 SubAgentFactory 创建独立子 runtime
        3. 子 agent 在隔离上下文执行技能
        4. 子 agent 通过 attempt_completion 返回结果
        5. 结果作为 use_skill 的 tool_result 回流主 agent

    生命周期: completes_run=False（主 agent 收到结果后继续决策）
    """

    def __init__(
        self,
        registry: SkillRegistry,
        sub_agent_factory: SubAgentFactory,
    ):
        self._registry = registry
        self._factory = sub_agent_factory

    @property
    def name(self) -> str:
        return "use_skill"

    @property
    def description(self) -> str:
        return (
            "加载并执行指定技能。技能会在独立的子 agent 上下文中执行，"
            "执行完毕后返回结果。"
            "参数: skill_name(必填): 技能名称; "
            "task(可选): 技能要执行的具体任务描述，默认为'按 SKILL.md 指令执行'"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "技能名称（如 write-report, financial-analysis, read-pdf）",
                },
                "task": {
                    "type": "string",
                    "description": "技能要执行的具体任务（默认'按 SKILL.md 指令执行'）",
                },
            },
            "required": ["skill_name"],
        }

    async def _execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        skill_name = input["skill_name"]
        task = input.get("task") or "按 SKILL.md 指令执行"

        # 检查技能是否存在
        if not self._registry.has_skill(skill_name):
            available = [s.name for s in self._registry.list_skills()]
            return AgentToolResult(
                output={"error": f"技能不存在: {skill_name}", "available_skills": available},
                is_error=True,
            )

        # 加载技能指令 — Level 2
        instructions = self._registry.load_instructions(skill_name)
        if instructions is None:
            return AgentToolResult(
                output={"error": f"无法加载技能指令: {skill_name}"},
                is_error=True,
            )

        # 创建子 agent — 对标 createDelegatedAgent
        sub_runtime = self._factory.create_for_skill(
            skill_name=skill_name,
            instructions=instructions,
            task=task,
            parent_agent_id=context.agent_id,
        )

        # 执行子 agent — 对标 subAgent.run(task)
        try:
            result = await sub_runtime.run(task)
            output_text = result.output_text or "(技能执行无输出)"
            return AgentToolResult(
                output=output_text,
                metadata={
                    "skill_name": skill_name,
                    "sub_agent_id": result.agent_id,
                    "sub_iterations": result.iterations,
                    "sub_status": result.status,
                },
            )
        except Exception as e:
            return AgentToolResult(
                output={"error": f"技能执行失败: {e}"},
                is_error=True,
            )
```

**新增 `attempt_completion` 工具**（子 agent 专用，`completes_run=True`）:
```python
# agent/tools/attempt_completion.py

class AttemptCompletionTool(BaseTool):
    """子 agent 完成工具 — 对标 Cline attempt_completion

    lifecycle.completes_run = True
    子 agent 调用此工具返回最终结果，runtime 检测到 completes_run 后结束运行。
    """

    @property
    def name(self) -> str:
        return "attempt_completion"

    @property
    def description(self) -> str:
        return "任务完成后调用此工具返回最终结果。调用后子 agent 运行结束。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "result": {
                    "type": "string",
                    "description": "最终结果文本",
                },
            },
            "required": ["result"],
        }

    @property
    def lifecycle(self) -> ToolLifecycle:
        return ToolLifecycle(completes_run=True)

    async def _execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        return AgentToolResult(output=input["result"])
```

**事件流增强**: 子 agent 的事件需要冒泡到主 agent 的事件流，前端以"嵌套卡片"展示:
```python
# 主 agent 收到子 agent 事件时，包装为 sub_agent_event 类型
# 前端 ai-chat.js 收到 sub_agent_event 时，渲染为嵌套折叠卡片
{
    "type": "sub_agent_event",
    "skill_name": "write-report",
    "sub_agent_id": "abc123",
    "event": { /* 原始子 agent 事件 */ }
}
```

**验证方式**:
1. 调用 `use_skill(skill_name="write-report", task="写东方电气研报")`
2. 检查子 agent 是否独立执行（事件流中出现 sub_agent_event）
3. 检查子 agent 工具集是否受限（无 use_skill、无 spawn_agent）
4. 检查主 agent 上下文是否只收到最终研报文本（不含子 agent 中间步骤）

**依赖**: Phase 1-2 (Runtime), Phase 5 (skills)
**Cline 对标**: `spawn-agent-tool.ts` + `delegated-agent.ts` + `subagent-prompts.ts`

---

### Phase 11: 结构化工具系统（替换 exec）

**目标**: 用 Cline 结构化工具替代通用 exec，提升 token 效率和安全性

**为什么关键**: 当前 `ExecTool` 接收单个 `command` 字符串，LLM 容易拼错路径、漏空格、误用 shell 元字符。Cline 的 `run_commands` 接收 `commands: string[]` 数组（批量执行+原子返回），`read_files` 接收 `files: [{path, start_line, end_line}]` 结构化数组，token 效率高、LLM 易生成、安全可控。

**Cline 对标**:
- `third_party/cline/sdk/packages/core/src/extensions/tools/schemas.ts` L42-92 — ReadFilesInputSchema + RunCommandsInputSchema
- `third_party/cline/sdk/packages/core/src/extensions/tools/executors/bash.ts` — 命令执行器

**删除文件**:
- `agent/tools/exec_tool.py` — 删除（被 run_commands 替代）

**新建文件**:
1. `agent/tools/run_commands.py` — 批量命令执行
2. `agent/tools/read_files.py` — 批量文件读取（支持行范围）
3. `agent/tools/write_file.py` — 单文件写入
4. `agent/tools/list_dir.py` — 目录列表

**`agent/tools/run_commands.py` 核心逻辑**:
```python
# 对标 Cline RunCommandsInputSchema + bash.ts

class RunCommandsTool(BaseTool):
    """批量命令执行 — 对标 Cline run_commands tool

    接收命令数组，按顺序执行，每条命令独立返回结果。
    相比单 command 字符串:
        - LLM 更易生成（结构化数组）
        - 单条失败不影响其他命令
        - 每条命令独立 timeout 和 exit_code
    """

    _MAX_COMMANDS = 10  # 单次最多 10 条命令
    _MAX_OUTPUT_PER_COMMAND = 8000  # 单条命令输出上限

    @property
    def name(self) -> str:
        return "run_commands"

    @property
    def description(self) -> str:
        return (
            "批量执行命令行命令。每条命令独立执行并返回 stdout/stderr/exit_code。"
            "适合运行 Python 脚本、系统命令等。"
            "参数: commands(必填): 命令字符串数组，最多 10 条"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要执行的命令数组，按顺序执行",
                    "maxItems": 10,
                },
            },
            "required": ["commands"],
        }

    async def _execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        commands = input["commands"]
        if len(commands) > self._MAX_COMMANDS:
            return AgentToolResult(
                output={"error": f"命令数超过上限 {self._MAX_COMMANDS}"},
                is_error=True,
            )

        results = []
        for i, cmd in enumerate(commands):
            # 安全检查（复用原 ExecTool 的 _DENY_PATTERNS）
            guard_error = self._guard_command(cmd)
            if guard_error:
                results.append({"command": cmd, "error": guard_error, "exit_code": -1})
                continue

            # 异步执行 — PYTHONUNBUFFERED=1
            try:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=600
                )
                results.append({
                    "command": cmd,
                    "stdout": stdout.decode("utf-8", errors="replace")[:self._MAX_OUTPUT_PER_COMMAND],
                    "stderr": stderr.decode("utf-8", errors="replace")[:2000],
                    "exit_code": process.returncode,
                })
            except asyncio.TimeoutError:
                process.kill()
                results.append({"command": cmd, "error": "timeout 600s", "exit_code": -1})

        return AgentToolResult(output={"results": results})
```

**`agent/tools/read_files.py` 核心逻辑**:
```python
# 对标 Cline ReadFilesInputSchema

class ReadFilesTool(BaseTool):
    """批量文件读取 — 对标 Cline read_files tool

    支持行范围读取，避免读取大文件撑爆上下文。
    相比 read_file 单文件:
        - 一次可读多个文件（减少 tool_call 次数）
        - 支持 start_line/end_line 行范围
        - 自动检测 UTF-8 编码
    """

    @property
    def name(self) -> str:
        return "read_files"

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
                            "path": {"type": "string", "description": "文件绝对路径"},
                            "start_line": {"type": "integer", "minimum": 1, "description": "起始行（1-based，可选）"},
                            "end_line": {"type": "integer", "minimum": 1, "description": "结束行（1-based，可选）"},
                        },
                        "required": ["path"],
                    },
                    "description": "文件读取请求数组",
                    "maxItems": 10,
                },
            },
            "required": ["files"],
        }

    async def _execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        results = []
        for req in input["files"]:
            path = req["path"]
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                start = (req.get("start_line") or 1) - 1
                end = req.get("end_line") or len(lines)
                content = "".join(lines[start:end])
                results.append({"path": path, "content": content, "lines": len(lines)})
            except Exception as e:
                results.append({"path": path, "error": str(e)})
        return AgentToolResult(output={"results": results})
```

**SKILL.md 脚本调用示例更新**:
所有技能 SKILL.md 中的 `exec` 调用示例改为 `run_commands`:
```markdown
# 旧（exec 单命令）
使用 exec 工具执行: python skills/financial-analysis/scripts/ratio_analysis.py --stock 600875.SH

# 新（run_commands 数组）
使用 run_commands 工具执行:
commands: ["python skills/financial-analysis/scripts/ratio_analysis.py --stock 600875.SH"]
```

**验证方式**:
1. 调用 `run_commands(commands=["dir", "python --version"])` 验证批量执行
2. 调用 `read_files(files=[{path: "test.txt", start_line: 1, end_line: 10}])` 验证行范围
3. 确认所有 SKILL.md 中无 `exec` 字样

**依赖**: Phase 4 (base.py)
**Cline 对标**: `schemas.ts` + `bash.ts`

---

### Phase 12: TodoWrite + Plan Mode 工具

**目标**: 引入 Cline 的任务规划和模式切换工具，解决"执行流程死板"

**为什么关键**: 用户多次反馈"agent 执行流程死板"，根源是缺乏显式任务规划工具。Cline 的 TodoWrite 让 LLM 显式维护任务清单（pending/in_progress/completed），runtime 每轮提示更新；Plan Mode 让 LLM 先规划再执行，研报等复杂任务可分阶段对齐用户预期。

**Cline 对标**:
- `third_party/cline/sdk/packages/shared/src/prompt/cline.ts` L32-45 — PLAN_MODE_INSTRUCTIONS
- `third_party/cline/apps/vscode/src/sdk/sdk-session-config-builder.ts` L51-80 — createSwitchToActModeTool
- `third_party/cline/sdk/packages/core/src/extensions/tools/schemas.ts` — 工具 schema 风格

**新建文件**:
1. `agent/tools/todo_write.py` — TodoWrite 工具
2. `agent/tools/plan_mode.py` — switch_to_act_mode + switch_to_plan_mode 工具
3. `agent/state.py` — 全局会话状态（todos 列表、当前 mode）

**`agent/state.py` 核心逻辑**:
```python
# 对标 Cline 会话状态管理
import threading
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class TodoItem:
    content: str
    status: Literal["pending", "in_progress", "completed"] = "pending"
    active_form: str = ""  # 当前正在执行的动作描述

@dataclass
class SessionState:
    """会话全局状态 — 跨工具共享"""
    todos: list[TodoItem] = field(default_factory=list)
    mode: Literal["act", "plan"] = "act"

# 全局会话状态注册表（按 session_id 隔离）
_sessions: dict[str, SessionState] = {}
_lock = threading.Lock()

def get_session_state(session_id: str) -> SessionState:
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = SessionState()
        return _sessions[session_id]
```

**`agent/tools/todo_write.py` 核心逻辑**:
```python
# 对标 Claude/Cline TodoWrite 工具

class TodoWriteTool(BaseTool):
    """任务清单工具 — 对标 Claude TodoWrite

    LLM 显式维护任务清单，每轮工具返回后更新进度。
    前端以可折叠卡片展示 todos。
    """

    def __init__(self, session_id: str):
        self._session_id = session_id

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "更新任务清单。用于复杂任务的规划和进度跟踪。"
            "参数: todos(必填): 任务清单数组，每项含 content/status/active_form"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "任务描述"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "任务状态",
                            },
                            "active_form": {
                                "type": "string",
                                "description": "当前动作描述（status=in_progress 时必填）",
                            },
                        },
                        "required": ["content", "status"],
                    },
                    "description": "完整的任务清单（替换式更新，非增量）",
                },
            },
            "required": ["todos"],
        }

    async def _execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        state = get_session_state(self._session_id)
        new_todos = [
            TodoItem(
                content=t["content"],
                status=t["status"],
                active_form=t.get("active_form", ""),
            )
            for t in input["todos"]
        ]
        old_todos = state.todos
        state.todos = new_todos

        # 事件通知前端更新
        if context.emit_update:
            context.emit_update({"todos_updated": [t.__dict__ for t in new_todos]})

        return AgentToolResult(
            output={
                "old_todos": [t.__dict__ for t in old_todos],
                "new_todos": [t.__dict__ for t in new_todos],
                "hint": "清单已更新，继续执行 in_progress 任务",
            },
            metadata={"todos_count": len(new_todos)},
        )
```

**`agent/tools/plan_mode.py` 核心逻辑**:
```python
# 对标 Cline switch_to_act_mode + PLAN_MODE_INSTRUCTIONS

PLAN_MODE_PROMPT = """# Plan Mode

你当前处于 Plan 模式。你的职责是探索、分析、规划——而非执行。

- 读取文件、搜索代码库、收集上下文以理解问题
- 需求不明确时主动提问
- 以结构化大纲呈现你的计划，列出清晰步骤
- 阐述不同方案的权衡
- 不要编辑文件、写代码、运行破坏性命令
- 不要实现任何东西——先聚焦理解和对齐

run_commands 工具在 Plan 模式下仅用于只读检查（ls/grep/cat/git log 等），
绝不可用于变更状态。

当用户审核并明确批准你的计划后，调用 switch_to_act_mode 工具切换到 Act 模式开始执行。
切换到 Act 模式会立即开始执行，所以:
    - 不要在你呈现计划的同一轮调用 switch_to_act_mode
    - 不要把原始任务请求当作批准
    - 呈现计划后结束本轮，等待用户响应"""

class SwitchToActModeTool(BaseTool):
    """切换到 Act 模式 — 对标 Cline switch_to_act_mode"""

    def __init__(self, session_id: str):
        self._session_id = session_id

    @property
    def name(self) -> str:
        return "switch_to_act_mode"

    @property
    def description(self) -> str:
        return (
            "从 Plan 模式切换到 Act 模式。切换后立即开始执行计划。"
            "仅在用户明确批准计划后调用（如'可以'、'开始执行'、'切换到 Act 模式'）。"
            "不要在呈现计划的同一轮调用，不要把原始任务请求当作批准。"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def lifecycle(self) -> ToolLifecycle:
        return ToolLifecycle(completes_run=True)  # 切换后结束本轮，等用户下次输入

    async def _execute(self, input: dict, context: AgentToolContext) -> AgentToolResult:
        state = get_session_state(self._session_id)
        old_mode = state.mode
        state.mode = "act"
        return AgentToolResult(
            output=(
                f"已从 {old_mode} 模式切换到 act 模式。"
                "你现在可以编辑文件、运行命令、执行计划。"
                "(switch_to_act_mode 工具仅在 plan 模式可用)"
            ),
            metadata={"old_mode": old_mode, "new_mode": "act"},
        )


class SwitchToPlanModeTool(BaseTool):
    """切换到 Plan 模式"""

    # 同上，state.mode = "plan"，lifecycle.completes_run=True
    ...
```

**SystemPromptBuilder 增强**: 根据当前 mode 注入 PLAN_MODE_PROMPT:
```python
# 在 SystemPromptBuilder.build() 中
if state.mode == "plan":
    parts.append(PLAN_MODE_PROMPT)
```

**前端事件**: todos_updated 事件触发前端 TodoList 卡片渲染:
```javascript
// ai-chat.js
eventSource.addEventListener("todos_updated", (e) => {
    const todos = JSON.parse(e.data);
    renderTodoListCard(todos);  // 渲染为可折叠卡片
});
```

**验证方式**:
1. 复杂任务（写研报）时 LLM 是否主动调用 todo_write 规划步骤
2. Plan 模式下 LLM 是否只读不写
3. switch_to_act_mode 后是否解除写入限制
4. 前端是否显示 TodoList 卡片

**依赖**: Phase 1-2 (Runtime), Phase 6 (Prompt)
**Cline 对标**: `cline.ts` + `sdk-session-config-builder.ts`

**完成状态**: 已完成（后端部分）
- [x] 新建 `agent/state.py` — SessionState 管理 todos + mode，按 session_id 隔离
- [x] 新建 `agent/tools/todo_write.py` — TodoWriteTool，替换式更新，强制单一 in_progress
- [x] 新建 `agent/tools/plan_mode.py` — SwitchToActModeTool + SwitchToPlanModeTool，completes_run=True
- [x] `agent/tools/__init__.py` — create_default_tools 接受 session_id，注册 3 个新工具
- [x] `agent/context.py` — SystemPromptBuilder 支持 session_id，plan 模式注入 PLAN_MODE_PROMPT
- [x] `agent/runtime.py` — 新增 _make_emit_update，通过 STATUS_NOTICE 事件转发工具 update
- [x] `agent/server.py` — _create_runtime / _build_system_prompt 传入 session_id；_handle_status_notice 转发 todos_updated / mode_changed SSE 事件
- [ ] 前端 TodoList 卡片渲染 + Plan Mode 切换按钮（Phase 15 实施）

**测试结果**: 8 项单元测试 + 4 项集成测试全部通过
- TodoWrite 创建清单、多 in_progress 拦截、active_form 持久化
- Plan Mode 切换、重复切换拦截、completes_run 标记
- SystemPromptBuilder plan 模式注入 PLAN_MODE_PROMPT、act 模式不注入
- 不同 session_id 状态隔离

---

### Phase 13: LLM 上下文压缩 + 接入 runtime

**目标**: ContextCompactor 用 Qwen 生成摘要，作为 before_model hook 自动触发

**为什么关键**: 当前 `_simple_summary` 仅截断每条消息到 200 字符拼接，长对话（如研报生成含多次工具调用）会丢失关键财务数据。Cline 的 `runAgenticCompaction` 用 LLM 生成摘要，保留关键事实。同时 ContextCompactor 当前是独立类，未接入 runtime，根本没生效。

**Cline 对标**:
- `third_party/cline/sdk/packages/core/src/extensions/context/compaction.ts` — createContextCompactionPrepareTurn
- `third_party/cline/sdk/packages/core/src/extensions/context/agentic-compaction.ts` — runAgenticCompaction

**修改文件**:
1. `agent/context.py` — ContextCompactor 接入 Qwen + 改造为 before_model hook

**`agent/context.py` 核心改造**:
```python
class ContextCompactor:
    """上下文压缩器 — 对标 Cline compaction.ts

    改造点:
        1. 接入 Qwen 实现 LLM 摘要（替代 _simple_summary）
        2. 实现 before_model hook，自动接入 runtime
        3. 保留 basic 策略作为 fallback（agentic 失败时）
    """

    def __init__(
        self,
        model: AgentModel,  # 新增：用于生成摘要
        max_input_tokens: int = 65536,
        trigger_ratio: float = 0.8,
        keep_recent: int = 6,
        summary_max_tokens: int = 2000,
    ):
        self.model = model
        # ... 其他参数同前

    async def before_model(self, ctx: BeforeModelContext) -> BeforeModelResult | None:
        """before_model hook — 对标 Cline createContextCompactionPrepareTurn

        每轮调 LLM 前自动检查:
            1. 估算 messages token 数
            2. 超过阈值则压缩
            3. 返回修改后的 messages
        """
        messages = ctx.request.messages
        if not self.should_compact(messages):
            return None

        try:
            # 优先用 LLM 生成摘要 — 对标 runAgenticCompaction
            compacted = await self.compact(messages, summarize_func=self._llm_summarize)
        except Exception as e:
            logger.warning(f"LLM 摘要失败，回退到 basic 策略: {e}")
            # 对标 Cline: agentic 失败时 fallback 到 basic
            compacted = await self.compact(messages, summarize_func=None)

        return BeforeModelResult(messages=compacted)

    async def _llm_summarize(self, old_messages: list[AgentMessage]) -> str:
        """用 Qwen 生成摘要 — 对标 Cline runAgenticCompaction

        构造摘要 prompt:
            1. 提取每条消息的角色和关键内容
            2. 让 Qwen 生成结构化摘要（保留数字、结论、决策）
            3. 限制摘要长度
        """
        # 构造对话历史文本
        history_text = self._format_messages_for_summary(old_messages)

        summary_prompt = (
            "# 对话历史摘要任务\n\n"
            "请将以下对话历史压缩为简洁摘要，必须保留:\n"
            "- 所有具体数字（股价、财务指标、日期）\n"
            "- 关键结论和决策\n"
            "- 工具调用的重要返回结果\n"
            "- 用户的明确要求\n\n"
            "可省略:\n"
            "- 工具调用的中间步骤\n"
            "- 重复的上下文\n"
            "- 冗长的引用文本\n\n"
            f"# 对话历史\n{history_text}\n\n"
            f"# 摘要（不超过 {self.summary_max_tokens} tokens）"
        )

        # 调用 Qwen
        request = AgentModelRequest(
            system_prompt="你是对话摘要助手，生成保留关键信息的简洁摘要。",
            messages=[create_message(MessageRole.USER, [TextPart(text=summary_prompt)])],
            options={"max_tokens": self.summary_max_tokens},
        )

        summary_text = ""
        async for event in self.model.stream(request):
            if event.type == "text-delta":
                summary_text += event.text or ""

        return summary_text.strip() or self._simple_summary(old_messages)

    def _format_messages_for_summary(self, messages: list[AgentMessage]) -> str:
        """格式化消息列表为摘要 prompt 文本"""
        parts = []
        for msg in messages:
            role = msg.role.value
            text = _extract_message_text(msg)
            if text:
                # 每条消息保留前 500 字符（避免 prompt 过长）
                if len(text) > 500:
                    text = text[:500] + "..."
                parts.append(f"[{role}] {text}")
        return "\n".join(parts)
```

**接入 runtime** — 在 AgentRuntime 初始化时注册 hook:
```python
# agent/server.py 或主 runtime 装配处
runtime = AgentRuntime(config=...)
compactor = ContextCompactor(model=qwen_model)
runtime.register_hooks(AgentHooks(before_model=compactor.before_model))
```

**验证方式**:
1. 构造 100+ 条消息的长对话，触发压缩
2. 检查压缩后是否保留关键数字（如股价、财报日期）
3. 检查 LLM 摘要失败时是否回退到 basic 策略
4. 检查 before_model hook 是否每轮自动触发

**依赖**: Phase 1-2 (Runtime + Hooks), Phase 3 (Qwen Provider)
**Cline 对标**: `compaction.ts` + `agentic-compaction.ts`

**完成状态**: 已完成
- [x] `agent/context.py` — ContextCompactor 接入 AgentModel，实现 before_model hook，新增 _llm_summarize 和 _format_messages_for_summary，保留 _simple_summary 作为 fallback
- [x] `agent/server.py` — 移除全局 _compactor，在 _create_runtime 中创建 ContextCompactor(model=qwen_model) 并注册为 before_model hook
- [x] `agent/server.py` — 移除 _sse_generator 中的手动压缩代码（已由 before_model hook 自动处理）
- [x] `agent/runtime.py` — 修复 run() 方法支持 messages 参数（修复已存在的 TypeError bug）

**测试结果**: 6 项单元测试 + 集成验证全部通过
- should_compact 触发判断
- basic 策略压缩（无 model 时）
- before_model hook 自动触发
- 短消息不触发压缩
- LLM 失败时 fallback 到 basic 策略
- _format_messages_for_summary 格式化
- runtime.run 支持 messages 参数
- ContextCompactor 可作为 before_model hook 注册

---

### Phase 14: AGENTS.md + SKILL.md Cline 化

**目标**: 移除 nanobot 残留风格，统一为 Cline 简洁格式

**Cline 对标**:
- `third_party/cline/sdk/packages/shared/src/prompt/cline.ts` — DEFAULT_CLINE_SYSTEM_PROMPT 风格
- `third_party/cline/sdk/AGENTS.md` — Cline 自身 AGENTS.md 简洁风格

**重写 `agent_config/AGENTS.md`**:
```markdown
# Charles - AI 投研情报官

你是 Charles，专业 AI 投研情报官。通过 use_skill 工具加载技能（技能在独立子 agent 中执行），
通过 read_files/run_commands/web_search 等结构化工具执行具体操作。

## 工作模式

- Act 模式: 直接执行任务
- Plan 模式: 先规划后执行（复杂研报任务建议先用 Plan 模式对齐）

切换模式通过 switch_to_act_mode / switch_to_plan_mode 工具。

## 工具选择原则

1. 结构化财务数字 → financial-analysis 技能（CSV 数据）
2. 年报叙述性内容 → read-pdf 技能（RAG 检索）
3. 时效性信息（新闻、公告） → web_search 工具
4. 股价/K线数据 → stock-price 技能

## 硬约束

- 禁止用 web_search 查本地已有数据的股价、财报
- 禁止用 RAG 查结构化数字（存货金额、营收等）— 用 financial-analysis CSV
- 禁止用 read_files 读 data/parsed/ 下的切分文件（那是给 RAG 用的）
- 禁止用 run_commands 执行不存在的脚本

## 股票代码格式

- 沪市: 600519.SH
- 深市: 000858.SZ
- 北交所: 代码.BJ
- get_kline.py 必须带后缀；其他脚本两种格式都支持
- read_files 读 CSV 文件名不带后缀：data/financial_data/600519_financial_abstract.csv

## 输出规范

- Markdown 格式
- 投资建议附带风险提示
- 数据引用标注来源
- 研报遵循五步法: 信息差 → 逻辑差 → 预期差 → 催化剂 → 结论+风险闭环
```

**清理所有 SKILL.md frontmatter**:
```yaml
# 旧（含 nanobot 残留字段）
---
name: write-report
description: 写深度研报
keywords: [研报, 报告, 分析]
capabilities: [财务分析, 年报解读]
always: false
---

# 新（Cline 风格，仅 name + description）
---
name: write-report
description: 生成个股深度研报，遵循五步法框架（信息差→逻辑差→预期差→催化剂→结论+风险闭环）。使用前必须 use_skill 加载详细指令。
---
```

**更新所有 SKILL.md 中的工具调用示例**:
- `exec` → `run_commands`
- `read_file` → `read_files`
- 路径示例更新为结构化数组格式

**验证方式**:
1. 检查所有 SKILL.md frontmatter 仅含 name + description
2. 检查所有 SKILL.md 正文中无 `exec`、`read_file`（单数）字样
3. 检查 AGENTS.md 符合 Cline 简洁风格

**依赖**: Phase 11 (结构化工具)
**Cline 对标**: `cline.ts` DEFAULT_CLINE_SYSTEM_PROMPT

**完成状态**: 已完成
- [x] `agent_config/AGENTS.md` — 重写为 Cline 简洁风格，移除 nanobot 残留（exec/file_read → run_commands/read_files），新增工作模式/工具选择原则/五步法输出规范
- [x] 8 个 SKILL.md frontmatter 检查 — 全部已是 Cline 风格（仅 name + description），无需修改
- [x] 8 个 SKILL.md 正文检查 — 全部无旧工具名（exec/read_file 单数）残留

**测试结果**: 3 项验证全部通过
- AGENTS.md 包含 run_commands/read_files/switch_to_act_mode/switch_to_plan_mode/五步法
- 8 个 SKILL.md frontmatter 仅含 name + description
- 8 个 SKILL.md 正文无旧工具名

---

### Phase 15: 前端 Cursor/Trae/Cline 风格改造

**目标**: 前端支持 Sub-agent 嵌套展示、TodoList 卡片、Plan Mode 切换按钮、结构化工具调用展示

**为什么关键**: 用户明确要求前端学习 Cursor/Trae/Cline 风格。Sub-agent 化后，技能执行的中间步骤需要嵌套展示，否则用户看不到子 agent 在做什么。TodoWrite 需要可视化卡片。Plan Mode 需要模式切换按钮。

**UI 改造点**:

1. **Sub-agent 嵌套卡片** — 主消息流中插入可折叠的子 agent 执行区:
   ```
   [主 agent] 我来调用 write-report 技能
   ┌─ [子 agent: write-report] ──────────────┐
   │ [thinking] 需要先获取财务数据              │
   │ [tool] run_commands: ratio_analysis.py   │
   │ [tool] read_files: 600875_financial.csv  │
   │ [tool] web_search: 东方电气 最新公告       │
   │ [completion] 研报全文...                  │
   └────────────────────────────────────────┘
   [主 agent] 研报已生成（结果如上）
   ```

2. **TodoList 卡片** — 显示任务清单和进度:
   ```
   ┌─ 任务清单 ─────────────────────┐
   │ ✓ 获取财务数据                  │
   │ → 查询年报叙述   [执行中]       │
   │ ○ 搜索最新公告                  │
   │ ○ 生成研报                      │
   └────────────────────────────────┘
   ```

3. **Plan Mode 切换按钮** — 输入框旁的模式切换:
   - Act 模式（默认）：直接执行
   - Plan 模式：先规划，用户批准后再执行
   - 按钮显示当前模式，点击切换

4. **结构化工具调用展示** — run_commands 显示为命令列表:
   ```
   [tool] run_commands
   - $ python ratio_analysis.py --stock 600875.SH
   - $ dir data\financial_data\
   ```

**修改文件**:
1. `static/js/ai-chat.js` — 新增 Sub-agent 嵌套渲染、TodoList 卡片、模式切换
2. `static/css/ai-chat.css` — 嵌套卡片样式、TodoList 样式
3. `templates/ai-chat.html` — 模式切换按钮
4. `agent/server.py` — SSE 新增 `sub_agent_event` / `todos_updated` / `mode_switched` 事件类型

**验证方式**:
1. 调用 use_skill 时前端显示嵌套子 agent 卡片
2. 调用 todo_write 时前端显示 TodoList 卡片
3. 切换 Plan/Act 模式时按钮状态正确
4. run_commands 调用以命令列表形式展示

**依赖**: Phase 10-12 全部完成
**参考**: Cursor 的 sub-agent 嵌套展示、Trae 的 plan mode、Cline 的 tool call 卡片

**完成状态**: 已完成
- [x] `agent/skills/skill_tool.py` — 修复事件转发器，完整捕获 tool_name/tool_input/tool_output/tool_is_error 字段（之前仅捕获 type/iteration/text/metadata）
- [x] `agent/server.py` — `_handle_status_notice` 新增 sub_agent_event 处理；新增 `_handle_sub_agent_event` 将子 agent 事件映射为 SSE（sub_type=token/tool_call/tool_output/done/error）；`_sse_generator` 接收 mode 参数，调用 set_mode 设置会话模式；`chat_stream` 路由提取 mode 字段
- [x] `templates/ai-chat.html` — 新增 Plan Mode 切换按钮（#mode-toggle-btn），刷新版本号到 v20260725a
- [x] `static/js/ai-chat.js` — 新增 sub_agent_event/todos_updated/mode_changed 事件处理；新增 renderSubAgentBlock/renderTodoListBlock 渲染方法；新增 _renderSubToolCard 紧凑工具卡片；增强 renderToolCard 支持 run_commands/read_files 结构化展示；新增 _renderRunCommandsParams 命令列表渲染；新增 Plan Mode 切换（toggleMode/loadMode/_updateModeUI）；_finishStream 处理 sub_agent 状态收尾
- [x] `static/css/ai-chat.css` — 新增 Plan Mode 按钮、子 agent 嵌套卡片（含状态色 sub-running/sub-done/sub-error）、子 agent 内部工具卡片（紧凑版 .sub-tool）、TodoList 卡片（含进度显示）、run_commands 命令列表（终端风格深色背景）样式

**测试结果**: 语法验证全部通过
- skill_tool.py / server.py Python 语法正确
- agent.server.router / agent.skills.skill_tool.SkillTool 导入正常
- ai-chat.js Node.js 语法检查通过

---

### 8.2 重构阶段依赖关系

```
Phase 10 (Sub-agent)              ← 依赖 Phase 1-2, 5
Phase 11 (结构化工具)              ← 依赖 Phase 4
Phase 12 (TodoWrite+PlanMode)     ← 依赖 Phase 1-2, 6
Phase 13 (LLM压缩接入)            ← 依赖 Phase 1-3
Phase 14 (AGENTS.md重写)          ← 依赖 Phase 11
Phase 15 (前端改造)               ← 依赖 Phase 10-12
```

**可并行**: Phase 10/11/12/13 之间无依赖，可并行开发
**串行**: Phase 14 必须在 Phase 11 后（工具名变更后再改 SKILL.md）
**串行**: Phase 15 必须在 Phase 10-12 后（事件类型稳定后再改前端）

### 8.3 重构优先级

| 优先级 | Phase | 理由 |
|--------|-------|------|
| P0（必做）| 10, 11, 13 | Sub-agent + 结构化工具 + 压缩接入，这三项是 Cline 核心，不做等于没重构 |
| P1（重要）| 12, 14 | TodoWrite/PlanMode + AGENTS.md 重写，提升体验和规范性 |
| P2（增强）| 15 | 前端改造，可视化提升但不影响功能 |

### 8.4 重构风险

| 风险 | 对策 |
|------|------|
| Sub-agent 嵌套过深导致死循环 | 子 agent 工具集不含 use_skill/spawn_agent，max_iterations=20 |
| Qwen API 限流影响 LLM 摘要 | 摘要请求加 sleep(0.7)，失败时回退 basic 策略 |
| 工具名变更导致旧 SKILL.md 失效 | Phase 14 同步更新所有 SKILL.md，新增工具名兼容性检查 |
| Plan Mode 误切换导致 LLM 困惑 | switch_to_act_mode 标记 completes_run=True，切换后结束本轮 |
| 前端事件类型新增导致旧对话丢失 | ai-chat.js 对未知事件类型静默忽略，保证向后兼容 |

---

## 9. 第三轮重构：Cline 完整对齐（Phase 16-25）

### 9.0 重构背景

用户审计 Phase 1-15 后发现多处"计划写了但实现简化/省略"的 bug，且与 Cline 原本逻辑仍有显著差距。用户明确要求：
- 完全按 Cline 方式实现，不再简化任何计划承诺
- 保留 Cline 已有的全部机制（工具/hooks/checkpoint/MCP/telemetry/connectors/kanban）
- 实现会话本地持久化（与其他页面一致，重启可恢复）
- 工具审批 + auto-approve
- Sub-agent 工具集可配置
- 最后整体 bug 检查

### 9.1 已发现的"计划简化/省略"Bug 清单（P0 必修）

| 编号 | 文件 | 计划承诺 | 实际实现 | 严重度 |
|------|------|---------|---------|--------|
| B1 | `agent/context.py` SystemPromptBuilder | Phase 6 承诺分层 environment/tools_section/mode_tag | 只有 identity/agents/memory/skills/rules/mode 6 段，缺 environment/tools/mode_tag | P0 |
| B2 | `agent/context.py` ContextCompactor 参数 | 对标 Cline 128000/0.9/20000 tokens | 硬编码 65536/0.8/6 条消息 | P0 |
| B3 | `agent/context.py` ContextCompactor 实现 | Phase 6 承诺 _truncate_tool_results + findCutIndex + summarizeToolActivity + buildDroppedWorkSummaryBlock + buildSummaryRequest + ensureFilesSection + isSafeCutBoundary + PRESERVED_ASSISTANT_TEXT_COUNT | 仅简单 split_point 分割，无安全切割/工具活动摘要/结构化 LLM 摘要 | P0 |
| B4 | `agent/server.py` tool_policies | Phase 12 承诺根据 mode 应用 tool_policies | _create_runtime 未设置 tool_policies，runtime 检查逻辑永远走不到 | P0 |
| B5 | `agent/server.py` 用户消息包裹 | Phase 12 承诺 `<user_input mode="...">` 标签 | 直接 create_text_message 无包裹 | P0 |
| B6 | `agent/tools/__init__.py` 工具集 | Phase 4 承诺 write_file/list_dir/web_fetch | 只有 8 个工具，缺 6 个 Cline 核心工具 | P0 |
| B7 | `agent/tools/attempt_completion.py` | Phase 10 承诺注册到主 agent | 文件存在但未在 create_default_tools 注册 | P1 |
| B8 | `agent/session.py` 持久化 | 用户要求本地+内存 | 仅内存 dict | P0 |
| B9 | `agent/skills/sub_agent.py` 工具集 | 应可配置 | `_DEFAULT_SUB_AGENT_TOOLS` 硬编码 | P1 |
| B10 | `agent/hooks.py` 钩子点 | Cline 有 prepareTurnInput/formatUserInputBlock/审批钩子 | 仅 6 个基础钩子 | P2 |

### Phase 16: 修复计划简化 P0 Bug（SystemPromptBuilder + ContextCompactor + tool_policies + mode 标签）

**目标**: 修复 B1-B5 五个 P0 级"计划简化"Bug，让系统提示和上下文压缩完全对齐 Cline。

**修改文件**:
1. `agent/context.py` — SystemPromptBuilder 补齐 `_build_environment()` / `_build_tools_section()` / `_build_mode_tag_instructions()` 方法；ContextCompactor 参数对齐 Cline（128000/0.9/20000 tokens）；补齐 `_truncate_tool_results` / `_find_cut_index` / `_summarize_tool_activity` / `_build_dropped_work_summary_block` / `_build_summary_request` / `_ensure_files_section` / `_is_safe_cut_boundary`，保留最近 3 条 assistant 文本（PRESERVED_ASSISTANT_TEXT_COUNT）
2. `agent/server.py` — `_create_runtime` 根据 session mode 设置 `tool_policies`（plan 模式禁用 editor/apply_patch/file_write）；`_sse_generator` 用户消息包裹 `<user_input mode="...">` 标签

**验证方式**:
1. SystemPromptBuilder.build() 输出含 `<env>` 段、工具列表段、`<user_input mode>` 说明段
2. ContextCompactor 参数为 128000/0.9/20000，触发压缩时输出含 `<SYSTEM_NOTICE>` 摘要块
3. Plan 模式下 editor/file_write 工具被 tool_policies 禁用
4. LLM 收到的用户消息含 `<user_input mode="plan">` 包裹

**依赖**: Phase 1-15 全部完成
**Cline 对标**: `system.ts` DEFAULT_CLINE_SYSTEM_PROMPT + `compaction.ts` + `presets.ts` plan preset

**完成状态**: 进行中

---

### Phase 17: 迁移 Cline 核心工具（editor/apply_patch/search_codebase/fetch_web_content/ask_question/submit_and_exit/list_files）

**目标**: 修复 B6/B7，让 agent 具备 Cursor/Trae 级代码编辑和搜索能力。

**新建文件**:
1. `agent/tools/editor.py` — 行级编辑工具（path/old_text/new_text/insert_line），对标 Cline createEditorTool
2. `agent/tools/apply_patch.py` — diff 补丁工具（input），对标 Cline createApplyPatchTool
3. `agent/tools/search_codebase.py` — 正则代码搜索（queries 数组），对标 Cline createSearchTool
4. `agent/tools/fetch_web_content.py` — URL 抓取（requests 数组，url+prompt），对标 Cline createWebFetchTool
5. `agent/tools/ask_question.py` — 向用户提问（question+options 2-5），对标 Cline createAskQuestionTool
6. `agent/tools/list_files.py` — 目录列表（path），对标 Cline list_files
7. `agent/tools/submit_and_exit.py` — 任务完成（summary+verified，completes_run=True），对标 Cline createSubmitAndExitTool

**修改文件**:
1. `agent/tools/__init__.py` — `create_default_tools` 注册上述新工具
2. `agent/tools/attempt_completion.py` — 确认注册到主 agent
3. `agent/server.py` — Plan 模式 tool_policies 禁用 editor/apply_patch/file_write
4. `static/js/ai-chat.js` — ask_question 事件渲染为选项卡片，submit_and_exit 事件结束对话

**验证方式**:
1. LLM 可调用 editor 精准替换文件内容
2. LLM 可调用 search_codebase 并行正则搜索
3. LLM 可调用 fetch_web_content 抓取 URL
4. LLM 可调用 ask_question 向用户提问，前端显示选项
5. LLM 可调用 submit_and_exit 结束对话

**依赖**: Phase 16（tool_policies 必须先就位）
**Cline 对标**: `definitions.ts` createEditorTool/createApplyPatchTool/createSearchTool/createWebFetchTool/createAskQuestionTool/createSubmitAndExitTool

---

### Phase 18: 会话持久化（本地 JSON + 内存）

**目标**: 修复 B8，让会话重启后可恢复。

**修改文件**:
1. `agent/session.py` — SessionManager 增加 JSON 文件持久化，每条消息落盘到 `agent_data/sessions/<session_id>.json`；启动时自动加载
2. `agent/state.py` — SessionState（todos/mode）持久化到 `agent_data/state/<session_id>.json`
3. `agent/server.py` — 启动时调用 SessionManager.load_all() 恢复会话

**验证方式**:
1. 对话后重启服务，会话历史完整恢复
2. TodoList 和 mode 状态重启后保持

**依赖**: 无
**Cline 对标**: Cline 会话持久化机制

---

### Phase 19: 工具审批 + auto-approve

**目标**: 危险操作需用户确认，支持 auto-approve toggle。

**修改文件**:
1. `agent/types.py` — AgentToolDefinition 增加 `requires_approval` 字段
2. `agent/runtime.py` — before_tool 钩子检查 requires_approval，挂起等待用户批准
3. `agent/server.py` — 新增 `/api/chat/approve` 端点接收批准/拒绝
4. `static/js/ai-chat.js` — 工具调用前显示 approve/deny 按钮
5. `static/css/ai-chat.css` — 审批 UI 样式

**验证方式**:
1. 调用 file_write/run_commands 时前端弹出审批按钮
2. 用户拒绝后工具不执行
3. auto-approve 开启后跳过审批

**依赖**: Phase 17（工具集完整）
**Cline 对标**: `presets.ts` createToolPoliciesWithPreset + autoApprove

---

### Phase 20: Sub-agent 工具集可配置

**目标**: 修复 B9，技能 SKILL.md frontmatter 可声明 allowed_tools。

**修改文件**:
1. `agent/skills/loader.py` — SkillMetadata 增加 `allowed_tools: list[str]` 字段
2. `agent/skills/sub_agent.py` — SubAgentFactory 读取 allowed_tools，未声明时用默认工具集
3. `agent_config/skills/*/SKILL.md` — 关键技能 frontmatter 声明 allowed_tools

**验证方式**:
1. SKILL.md 声明 allowed_tools: [read_files, run_commands] 后子 agent 只能用这两个工具

**依赖**: Phase 17（工具集完整）
**Cline 对标**: `spawn-agent-tool.ts` 子 agent 工具配置

---

### Phase 21: Checkpoint 机制

**目标**: 用户可回滚到之前的消息状态。

**新建文件**:
1. `agent/checkpoint.py` — CheckpointManager，每次工具执行前保存快照到 `agent_data/checkpoints/<session_id>/`

**修改文件**:
1. `agent/runtime.py` — before_tool 钩子保存 checkpoint
2. `agent/server.py` — 新增 `/api/chat/rollback` 端点
3. `static/js/ai-chat.js` — 每条消息显示回滚按钮

**验证方式**:
1. 工具执行后可回滚到执行前状态

**依赖**: Phase 18（持久化）
**Cline 对标**: Cline checkpoint 机制

---

### Phase 22: MCP 支持

**目标**: 接入 MCP 服务器生态。

**新建文件**:
1. `agent/tools/mcp.py` — use_mcp_tool / access_mcp_resource 工具
2. `agent/mcp/registry.py` — MCP 服务器注册表
3. `agent_config/mcp_servers.yaml` — MCP 服务器配置

**验证方式**:
1. 配置 MCP 服务器后 agent 可调用其工具

**依赖**: 无
**Cline 对标**: `use_mcp_tool` / `access_mcp_resource`

**完成状态**: 已完成
- [x] `agent_config/mcp_servers.yaml` — 服务器配置文件，支持 stdio/http 两种传输方式，含 ${ENV_VAR} 环境变量引用语法
- [x] `agent/mcp/__init__.py` — MCP 模块入口
- [x] `agent/mcp/client.py` — MCPClient，JSON-RPC 2.0 over stdio/http，实现 initialize/tools/list/tools/call/resources/list/resources/read/ping/shutdown
- [x] `agent/mcp/registry.py` — MCPRegistry 全局单例，配置加载、懒连接、工具/资源缓存、${VAR} 环境变量解析
- [x] `agent/tools/mcp.py` — UseMcpToolTool + AccessMcpResourceTool 两个工具，含错误处理和 MCP 结果格式解析
- [x] `agent/tools/__init__.py` — create_default_tools 注册 MCP 工具
- [x] `agent/server.py` — 新增 3 个路由: GET /mcp/servers（列出服务器+工具）、GET /mcp/resources（列出资源）、POST /mcp/reload（热加载配置）
- [x] `agent/context.py` — SystemPromptBuilder 新增 _build_mcp_servers_section() 方法，注入 MCP 服务器概览到 system prompt

**测试结果**: 全部验证通过
- 7 个文件语法检查通过
- 导入测试通过（MCPClient/MCPRegistry/UseMcpToolTool/AccessMcpResourceTool）
- 配置加载测试通过（0 个服务器，符合预期）
- 17 个工具创建成功（含 use_mcp_tool + access_mcp_resource）
- ${ENV_VAR} 环境变量解析测试通过
- SystemPromptBuilder 在无 MCP 服务器时不注入 MCP 段

---

### Phase 23: Hooks 系统补齐

**目标**: 修复 B10，补齐 Cline 全部钩子点。

**修改文件**:
1. `agent/hooks.py` — 新增 `prepare_turn_input` / `format_user_input_block` / `before_approval` 钩子点和上下文/结果类
2. `agent/runtime.py` — 在用户输入预处理和工具审批节点调用新钩子

**验证方式**:
1. prepare_turn_input 钩子可修改用户输入
2. before_approval 钩子可拦截工具审批

**依赖**: Phase 19（审批机制）
**Cline 对标**: `agent-runtime.ts` prepareTurnInput / formatUserInputBlock

---

### Phase 24: Telemetry / Connectors / Kanban

**目标**: 迁移 Cline 特色系统。

**新建文件**:
1. `agent/telemetry.py` — 事件追踪系统
2. `agent/connectors.py` — 外部连接器（数据库/API）
3. `agent/kanban.py` — 任务看板

**修改文件**:
1. `static/js/ai-chat.js` — Kanban 看板 UI
2. `templates/ai-chat.html` — 看板入口

**验证方式**:
1. 关键操作有 telemetry 记录
2. Kanban 看板可视化任务进度

**依赖**: Phase 18-23
**Cline 对标**: Cline telemetry/connectors/kanban

---

### Phase 25: 整体 Bug 检查与修复

**目标**: 全系统审计，修复所有已知/未知 bug。

**检查项**:
1. 所有 Phase 16-24 实现是否完整（无简化）
2. 工具调用链路端到端测试
3. Plan Mode 硬约束验证
4. 上下文压缩边界条件测试
5. 会话持久化并发安全
6. 中文乱码检查
7. 前端事件类型向后兼容

**依赖**: Phase 16-24 全部完成

---

### 9.2 第三轮重构依赖关系

```
Phase 16 (P0 Bug 修复)          ← 独立，先做
Phase 17 (核心工具迁移)          ← 依赖 Phase 16
Phase 18 (会话持久化)            ← 独立，可与 17 并行
Phase 19 (工具审批)              ← 依赖 Phase 17
Phase 20 (Sub-agent 工具集)     ← 依赖 Phase 17
Phase 21 (Checkpoint)            ← 依赖 Phase 18
Phase 22 (MCP)                   ← 独立
Phase 23 (Hooks 补齐)            ← 依赖 Phase 19
Phase 24 (Telemetry/Connectors/Kanban) ← 依赖 Phase 18-23
Phase 25 (整体 Bug 检查)         ← 依赖 Phase 16-24
```

### 9.3 第三轮重构优先级

| 优先级 | Phase | 理由 |
|--------|-------|------|
| P0（必做）| 16, 17, 18 | 修复简化 Bug + 核心工具 + 持久化，这是"像 Cursor"的根基 |
| P1（重要）| 19, 20, 21 | 审批 + Sub-agent 配置 + Checkpoint，提升安全和体验 |
| P2（增强）| 22, 23, 24 | MCP + Hooks 补齐 + Telemetry，Cline 特色 |
| P0（收尾）| 25 | 整体 bug 检查，保证交付质量 |

---

## 十、Cline 真实逻辑对齐修复（Phase 26）

> 背景：前序 Phase 虽已按迁移计划实现功能，但局部补丁式修复导致实现细节与 Cline 真实逻辑产生偏离。本阶段基于 `sdk/packages/agents/src/agent-runtime.ts`、`sdk/packages/shared/src/agent.ts` 等源码逐项对齐，优先恢复 Cline 核心语义，避免"为修 bug 调偏方向"。

### 10.1 修复原则

1. **对齐 Cline 真实实现**，不凭臆测改动。
2. **移除掩盖问题的补丁**（如 `list_files` 默认值），让参数错误暴露。
3. **保留合理增强**（如工具执行超时、错误循环检测），但不让增强替代 Cline 核心机制。
4. **每步修复后运行 `tests/test_agent_e2e.py` 验证**。

### 10.2 已识别偏离点与修复方案

#### P0-1: 工具调用参数丢失（`list_files` 默认值 + tool-call-delta 组装 key 不稳定）

- **现象**: 用户任务中 `list_files` 反复列出当前目录，始终无法进入 `data/`；根本原因是流式 `tool-call-delta` 的参数分片在组装时因 key 不稳定而丢失/错位，`list_files` 的 `path` 默认值又掩盖了这一问题。
- **Cline 源码位置**:
  - `third_party/cline/apps/cli/src/runtime/tools.ts`（`listFiles` schema，无默认值）
  - `sdk/packages/agents/src/agent-runtime.ts` L965-1000（`PendingToolAssembly` 以 `index` 为 key）
- **当前偏离与已落地方案**:
  1. **QwenModel `tool_call_id` 不稳定**: Qwen 流式响应中 `tool_call_id` 通常只在首个 delta 出现，后续为空字符串。已在 `agent/providers/qwen.py` 中按 `index` 维护 `tool_call_ids` map，确保同一工具调用的所有 delta 使用相同的 `tool_call_id`。
  2. **Runtime 组装 key 错误**: 原实现以 `tool_call_id` 或 `len(tool_assemblies)` 为 key，导致分片错位/参数丢失。已在 `agent/runtime.py` 中改为以 `event.index` 为 primary key（无 index 时用 `next_tool_index` fallback），对齐 Cline `PendingToolAssembly`。
  3. **`list_files` 默认值**: 已移除 `input_schema` 中的 `default`，`path` 加入 `required`，description 明确必填；`_execute` 中防御式 `input.get("path", ".")` 仍保留作为 schema 校验之外的兜底，但 e2e 验证以 schema 必填为准。
- **验证**:
  - dummy model / 真实 LLM 调用 `list_files(path="data")` 时，参数完整接收并返回 `data/` 内容。
  - e2e 测试中若 LLM 未传 `path`，工具返回参数错误而非列出根目录。

#### P0-2: 工具调用参数解析缺少 `invalidToolCalls` 机制 `[已完成]`

- **Cline 源码位置**: `sdk/packages/agents/src/agent-runtime.ts` L1031-1058
- **已修复**: `_generate_assistant_message()` 已新增 `_InvalidToolCall` 数据结构，组装阶段将无效调用写入 `message.metadata["invalid_tool_calls"]`，并在下一轮为这些无效调用生成错误结果消息，让 LLM 看到反馈。
- **实现位置**: `agent/runtime.py`
- **验证**: 构造一个 LLM 返回空 `tool_name` 的 dummy model，检查 metadata 中是否含 `invalid_tool_calls`。

#### P0-3: 工具输入未按 Schema 规范化 `[已完成]`

- **Cline 源码位置**: `sdk/packages/agents/src/agent-runtime.ts` L1365-1367（`normalizeJsonLikeStringsForSchema`）
- **已修复**: 在 `_prepare_tool_execution()` 中加入 `_normalize_input_for_schema(input, tool.input_schema)`，递归地将字符串化的 object/array 反序列化为 schema 期望的类型。
- **实现位置**: `agent/runtime.py`
- **验证**: 单元测试中传入字符串形式的 JSON object，验证执行前被解析为 dict。

#### P0-4: 循环检测语义与 Cline 不一致 `[已完成]`

- **Cline 源码位置**: `sdk/packages/core/src/runtime/safety/loop-detection.ts`
- **已修复**:
  - 新增 `agent/loop_detection.py`，实现 `LoopDetectionTracker`（软阈值 3，硬阈值 5）。
  - 作为 `before_tool` hook 注册到 runtime。
  - 保留现有 `_check_repeated_tool_failures` 作为补充。
- **实现位置**: `agent/loop_detection.py`、`agent/runtime.py`
- **验证**: dummy model 连续 5 次调用相同参数的 `list_files`，runtime 应主动停止。

#### P0-5: `usage` delta 记录零值 `[已完成]`

- **Cline 源码位置**: `sdk/packages/agents/src/agent-runtime.ts` L302-347
- **已修复**: `_compute_usage_delta()` 改为只返回非零字段，与 Cline `usageDelta` 一致。
- **实现位置**: `agent/runtime.py`

#### P0-6: 工具结果强制序列化为字符串 `[已完成]`

- **Cline 源码位置**: `sdk/packages/agents/src/agent-runtime.ts` L1541-1549（`output` 原样放入 `tool-result`）
- **已修复**:
  - `ToolResultPart.output` 保持原始类型，不再由 runtime 强制 JSON/字符串化。
  - 截断逻辑仅在事件展示路径调用 `_serialize_tool_output()`，不影响 `ToolResultPart`。
  - 向 LLM 发送 tool result 消息时，对象由 provider 层统一序列化。
- **实现位置**: `agent/runtime.py`
- **验证**: 工具返回 dict 时，`message.content` 中 `ToolResultPart.output` 仍为 dict。

#### P1-1: 缺少 `completion_policy` `[已完成]`

- **Cline 源码位置**: `sdk/packages/shared/src/agent.ts` L430-433
- **已修复**:
  - `agent/types.py` 新增 `CompletionPolicy` dataclass，含 `require_completion_tool` 与 `completion_guard`。
  - `AgentRuntimeConfig` 增加 `completion_policy: CompletionPolicy` 字段。
  - `agent/runtime.py` 主循环无 tool_calls 时，若 `require_completion_tool=True`，调用 `_build_completion_reminder()` 追加用户提醒并继续下一轮；否则正常结束运行。
- **实现位置**: `agent/types.py`、`agent/runtime.py`
- **验证**: dummy model 测试确认 `require_completion_tool=True` 时运行持续到达 max_iterations；默认策略下单轮结束。

#### P1-2: 缺少 `restore()` 方法 `[已完成]`

- **Cline 源码位置**: `sdk/packages/agents/src/agent-runtime.ts` L487-503
- **已修复**: 在 `AgentRuntime` 中添加 `restore(messages)`：调用 `abort()` 中止当前运行，保留订阅者/工具/钩子/模型，重置 `run_id`/`status`/`iteration`/`pending_tool_calls`/`usage`/`last_error`，并用传入消息替换历史。
- **实现位置**: `agent/runtime.py`
- **验证**: dummy model 测试确认 `restore()` 后 `iteration==0`、`status==idle`、messages 被替换。

#### P0-4: `restore()` / `abort()` 未严格对齐 Cline `[待评估]`

- **Cline 源码位置**: `sdk/packages/agents/src/agent-runtime.ts` L454-470 / L588-593
- **当前偏离**: 当前用 `_aborted` 布尔标志，Cline 用 `AbortController.signal`。
- **处理**: 本 Phase 暂不全面替换为 `AbortController`（改动面大），但评估在 `model.stream()` 和工具 context 中透传 `signal` 的必要性，作为 Phase 27 候选。

#### P0-7: 子 agent IPC 返回结果时 `error` 字段未序列化 `[已完成]`

- **现象**: `use_skill` 调用 `financial-analysis` 等技能时返回 `AgentToolResult(output={'error': '技能执行失败: Object of type AgentToolResult is not JSON serializable'}, ...)`。
- **根因**: `agent/skills/sub_agent_worker.py` 的 `_write_response()` 把 `AgentRunResult.error` 原样放入 JSON payload；`error` 可能是 Exception/AgentToolResult 等不可序列化对象，导致 `json.dumps()` 失败，子进程返回的 error message 被进一步包装。
- **已修复**: 在 `_write_response()` 中把 `error` 统一 `str()` 后再序列化。
- **实现位置**: `agent/skills/sub_agent_worker.py`
- **验证**: dummy model 构造含 Exception 的 `AgentRunResult`，确认 `_write_response()` 输出合法 JSON。

#### P0-8: 子 agent system prompt 缺少全局规则导致路径后缀误用 `[已完成]`

- **现象**: `financial-analysis` 子 agent 用 `data/financial_data/600519.SH_financial_abstract.csv`（带后缀）查找 CSV，实际文件名为 `600519_financial_abstract.csv`（无后缀）。
- **根因**: 子 agent 的 system prompt 只包含 SKILL.md，未包含 `agent_config/AGENTS.md` 中的硬约束和股票代码格式规则。
- **已修复**: 在 `SubAgentFactory._build_sub_agent_prompt()` 中读取并追加 `AGENTS.md` 的"## 硬约束"和"## 股票代码格式"两段，使子 agent 与主 agent 共享关键规则。
- **实现位置**: `agent/skills/sub_agent.py`
- **验证**: 单元测试确认 `_load_global_rules()` 正确提取两段规则。

### 10.3 当前合理增强（保留）

| 增强项 | 位置 | 保留理由 |
|--------|------|----------|
| 工具执行超时 | `AgentRuntimeConfig.default_tool_timeout_ms` | Cline 工具层无统一超时，当前实现防止工具挂死。 |
| 错误循环检测 | `runtime.py::_check_repeated_tool_failures()` | Cline 没有，作为额外保护避免 LLM 在同一错误上重试。 |
| `before_approval` hook | `agent/hooks.py` | Cline 用 `toolPolicies` + `requestToolApproval` config，当前 hook 形式语义等价且更灵活。 |
| `prepare_turn_input` / `format_user_input_block` hooks | `agent/hooks.py` | Cline 中为 config 回调，当前 hook 形式可工作，但后续如严格对齐可迁回 config。 |

### 10.4 实施顺序与当前状态

- [x] P0-1 工具调用参数丢失修复（QwenModel 稳定 tool_call_id + Runtime 按 index 组装 + list_files 默认值回退）
- [x] P0-2 `invalidToolCalls` 机制
- [x] P0-3 工具输入 schema 规范化
- [x] P0-4 `LoopDetectionTracker`
- [x] P0-5 / P0-6 usage delta 零值过滤 + tool result 不强制序列化
- [x] P0-7 子 agent IPC error 字段序列化
- [x] P0-8 子 agent prompt 注入 AGENTS.md 全局规则
- [x] P1-1 `completion_policy`
- [x] P1-2 `restore()`
- [x] e2e 全链路验证（真实 LLM + dummy model 覆盖 completion_policy / restore / sub-agent IPC）

### 10.5 验证方式

1. `python "CASE-AI量化系统\tests\test_agent_e2e.py"` 通过真实 LLM 验证基础对话与工具调用。
2. 新增/补充单元测试覆盖 `invalidToolCalls`、schema 规范化、循环检测。
3. 用 dummy model 构造边界场景（参数丢失、无效工具名、循环调用）。
4. 检查中文注释无乱码、UTF-8 编码正确。

### 10.6 依赖

- `agent/types.py`
- `agent/runtime.py`
- `agent/hooks.py`
- `agent/tools/list_files.py`
- `agent/tools/base.py`（用于 `lifecycle.completes_run`）
- `tests/test_agent_e2e.py`

---

## 十一、技能系统目录与执行架构重构（Phase 27）

> 背景：前序 Phase 中技能脚本和数据仍分散在 `third_party/charles_bundle/charles-nanobot/` 下，
> 且技能执行采用了 nanobot 风格的"子 agent 隔离执行"，与 Cline 原生的 `skills` 工具（主上下文指令注入）不一致。
> 本阶段按用户确认的"选项 a"进行重构：复制（非移动）数据与脚本到项目根目录，保留原 nanobot 不动，
> 并将技能执行架构改为严格复刻 Cline 原生实现。

### 11.1 重构原则

1. **复制而非移动**：`data/` 和技能脚本复制到根目录，`third_party/charles_bundle/charles-nanobot/` 保留作为历史参考。
2. **脚本路径固定写死**：脚本内部使用相对根目录的固定路径（如 `data/financial_data`、`data/vector_store`），不通过环境变量传入。
3. **复刻 Cline 原生实现**：技能工具从"子 agent 隔离执行"改为"主上下文指令注入"，不创建独立 runtime。
4. **不打补丁**：路径计算、数据依赖等问题通过目录重构一次性解决，而非在脚本里加兼容逻辑。

### 11.2 目录重构

#### 11.2.1 数据目录

- **来源**：`third_party/charles_bundle/charles-nanobot/data/`
- **目标**：`CASE-AI量化系统/data/`
- **复制内容**：
  - `data/financial_data/` —— 财务摘要 CSV（如 `600519_financial_abstract.csv`）
  - `data/vector_store/` —— FAISS 统一索引（`preprocess.py` 构建）
  - `data/parsed/` / `data/reports/` / `data/financial_reports/` —— PDF 年报及解析结果
  - `data/news/` / `data/sentiment/` 等 —— 新闻情绪数据
- **保留来源**：`third_party/charles_bundle/charles-nanobot/data/` 不删除、不清理，仅不再被新 agent 使用。

#### 11.2.2 技能脚本目录

- **来源**：原 nanobot 中的技能脚本（散落各处，部分通过 SKILL.md 引用）
- **目标**：`CASE-AI量化系统/agent_config/skills/{name}/scripts/`
- **已迁移技能**：
  - `financial-analysis/scripts/`: `fetch_financial_csv.py`, `ratio_analysis.py`, `peer_compare.py`
  - `read-pdf/scripts/`: `query_report.py`, `fetch_report_pdf.py`, `parse_pdf_basic.py`, `parse_pdf_ocr.py`, `build_index.py`, `fetch_financial_data.py`
  - `stock-price/scripts/`: `get_kline.py`
  - `write-report/scripts/`: `report_generator.py`, `five_step_analysis.py`, `prompts.py`
  - `sentiment-analysis/scripts/`: `sentiment_scorer.py`, `news_fetcher.py`, `event_detector.py`
  - `web-search/scripts/`: `search_market.py`
  - `compare-reports/scripts/`: `cross_company.py`, `cross_period.py`
- **SKILL.md 同步更新**：所有 SKILL.md 中的"脚本目录"和示例命令已改为 `agent_config/skills/{name}/scripts/`。

### 11.3 执行架构重构：子 agent 隔离 → Cline 原生 skills 指令注入

#### 11.3.1 Cline 原生实现

Cline 的 `skills` 工具（`sdk/packages/core/src/extensions/tools/definitions.ts` 中的 `createSkillsTool`）本质是：

- 工具名：`skills`
- 输入：`skill`（必填）, `args`（可选）
- 执行：不创建子 agent，直接返回 XML 格式的技能指令文本
- 返回格式：
  ```xml
  <command-name>{skill_name}</command-name>
  <command-args>{args}</command-args>
  <command-instructions>
  {skill_description}\n{skill_instructions}
  </command-instructions>
  ```
- 主 agent 收到该 tool_result 后，在后续轮次中将技能指令纳入上下文，继续使用主 agent 的完整工具集执行。

#### 11.3.2 当前实现修改

| 文件 | 修改内容 |
|------|---------|
| `agent/skills/skill_tool.py` | 工具名从 `use_skill` 改为 `skills`；移除子 agent 创建逻辑；直接返回 XML 技能指令文本。 |
| `agent/skills/registry.py` | `build_summary()` / `build_tool_hint()` 改为引导 LLM 使用 `skills` 工具加载指令。 |
| `agent/server.py` | 注册 `SkillsTool`，移除 `SubAgentFactory` 和旧的 `SkillTool` 注册。 |
| `agent_config/AGENTS.md` | 技能调用描述改为"通过 `skills` 工具加载该技能的详细指令，然后在当前主上下文中使用工具"。 |

### 11.4 脚本路径修正

重构后，脚本内部所有路径引用统一改为以项目根目录为基准的相对路径：

- `data/financial_data`（替代 `third_party/charles_bundle/charles-nanobot/data/financial_data`）
- `data/vector_store`（替代旧版单文档索引路径）
- `agent_config/skills/{name}/scripts/`（替代 nanobot 内部脚本路径）

具体修复示例：

- `agent_config/skills/read-pdf/scripts/query_report.py` 中 `_project_root()` 从 `Path(__file__).resolve().parents[3]` 修正为 `parents[4]`，确保正确指向 `CASE-AI量化系统/` 根目录。

### 11.5 验证结果

#### 11.5.1 端到端技能验证

| 技能 | 验证命令/脚本 | 结果 |
|------|--------------|------|
| financial-analysis | `python tests/test_skill_e2e.py` | 通过，成功分析贵州茅台(600519.SH)近三年毛利率趋势。 |
| read-pdf | `python agent_config/skills/read-pdf/scripts/query_report.py --index_dir data/vector_store --query "贵州茅台2025年营收和净利润" --top_k 3 --stock 600519` | 通过，RAG 成功召回并回答 2025 年三季报营收/净利润。 |
| stock-price | `python agent_config/skills/stock-price/scripts/get_kline.py 600519.SH 1d 30` | 通过，MiniQMT 连接成功并返回 30 日 K 线数据。 |

#### 11.5.2 架构验证

- `skills` 工具调用后，LLM 未创建子 agent，而是继续使用主工具集（`list_files` / `read_files` / `run_commands`）执行。
- `runtime.py` 中 `AgentToolResult` 的异常处理已确保 `output` 不含 Exception 对象；事件展示路径通过 `_serialize_tool_output()` 兜底序列化。
- `AgentToolResult` 的 `output` 保持原始类型（字符串/dict）对齐 Cline 语义，不在 runtime 层强制 JSON 化。

### 11.6 本次附带修改

- `agent_config/skills/financial-analysis/scripts/ratio_analysis.py`：修复 Windows 终端中文乱码，参考 `query_report.py` 增加 `sys.stdout = io.TextIOWrapper(...)` 和 `sys.stderr = io.TextIOWrapper(...)`。

### 11.7 数据目录重复问题修复

- **现象**：发现 `data/financial_data/financial_data/` 嵌套目录，含 600519 的重复 CSV。
- **根因**：`fetch_financial_csv.py` 的 `--output_dir` 表示"输出根目录"，脚本会再在其下创建 `financial_data/` 子目录。LLM 从 SKILL.md 中误解了参数含义，执行时传了 `--output_dir data/financial_data/`，导致生成 `data/financial_data/financial_data/`。
- **处理**：
  1. 已删除嵌套目录 `data/financial_data/financial_data/`。
  2. 更新 `fetch_financial_csv.py` 的模块 docstring 和 `--output_dir` help，明确"输出根目录"语义和默认行为。
  3. 更新 `agent_config/skills/financial-analysis/SKILL.md` 的参数说明和执行流程，提示"不要指定 `--output_dir`，默认输出到 `data/financial_data/`"。

### 11.8 相对路径解析修复（read_files）

- **现象**：agent 调用 `read_files` 传相对路径 `data/financial_data/600519_financial_abstract.csv` 时报"文件不存在"，传绝对路径则成功。
- **根因**：`ReadFilesTool` 直接用 `Path(path_str)` 解析路径，依赖运行时的当前工作目录。当 agent 入口的 cwd 不是项目根目录时，相对路径无法定位到正确文件。
- **修复**：
  1. `agent/tools/read_files.py`：增加 `__init__(working_dir)`，在 `_read_single_file` 中对非绝对路径基于 `working_dir` 解析。
  2. `agent/tools/__init__.py`：注册 `ReadFilesTool(working_dir=working_dir)`，与 `list_files` / `run_commands` 保持一致。
- **验证**：已用 `ReadFilesTool(working_dir='.')` 测试相对路径 `data/financial_data/600519_financial_abstract.csv`，成功读取。

### 11.9 报告期选择歧义修复

- **现象**：用户要求"用五步法分析贵州茅台"，agent 却自行构造 `<command-args>贵州茅台(600519.SH) 2024年中报深度分析</command-args>`，并围绕 2024 年中报展开下载和查询。
- **根因**：系统提示和技能文档未明确当前日期及"默认分析最新可得财报"的规则，LLM 因训练数据截止时间产生 2024 年中报为"最新"的幻觉。
- **修复**：
  1. `agent_config/AGENTS.md`：新增"时间基准"章节，明确当前日期 2026-07-25、A股年报披露规则、最新完整年报为 2025 年年报。
  2. `agent_config/skills/write-report/SKILL.md`：在"关键要求"中增加报告期选择规则，禁止默认使用 2024 年中报等历史报告期。
  3. `agent_config/skills/read-pdf/SKILL.md`：更新数据源选择规则中的年份范围（2025 年及以前用 RAG/CSV，2026 年季度用 CSV）。

### 11.10 web_search 依赖修复

- **现象**：agent 调用 `web_search` 时报错 `duckduckgo-search 库未安装`。
- **根因**：
  - 后端实际运行在 `Agu-2` 虚拟环境（路径 `E:\anaconda\envs\Agu-2`）。
  - `Agu-2` 环境已安装新包 `ddgs`（`duckduckgo-search` 已重命名为 `ddgs`），但 `agent/tools/web_tool.py` 仍使用旧导入 `from duckduckgo_search import DDGS`，导致找不到模块。
- **处理**：
  1. 更新 `agent/tools/web_tool.py`：导入从 `duckduckgo_search` 改为 `ddgs`，错误提示和注释同步更新。
  2. 在 `requirements.txt` 中增加 `ddgs>=9.0`，确保新环境部署时不会遗漏。
- **验证**：已使用 `E:\anaconda\envs\Agu-2\python.exe` 直接测试 `web_search` 查询"贵州茅台 2025年年报"，成功返回 5 条搜索结果。

### 11.11 遗留代码说明（暂不删除）

以下文件/代码属于旧"子 agent 隔离"架构残留，当前已不会被 `skills` 指令注入模式触发，功能无影响，但和 Cline 原生实现对齐后属于死代码：

- `agent/skills/sub_agent.py`
- `agent/skills/sub_agent_worker.py`
- `agent/server.py` 中的 `_handle_sub_agent_event()` 及 `sub_agent_event` 事件分支

按用户当前要求，**暂时保留不删除**，后续如确认不再需要可集中清理。

---

## 十二、后续方向（Phase 28+）

- 评估是否将 `prepare_turn_input` / `format_user_input_block` 从 hooks 迁回 `AgentRuntimeConfig` 回调，严格对齐 Cline。
- 评估 `AbortController.signal` 替换当前 `_aborted` 标志，向下传递到 model stream 和工具执行。
- 完成 telemetry / connectors / kanban 的落地集成。
