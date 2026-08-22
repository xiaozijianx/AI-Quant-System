# Phase 2.1 AgentRuntime 类结构对比报告

## 1. 执行摘要

Cline 在 SDK 层采用了清晰的"两层分离"架构：`@cline/agents` 包中的 `AgentRuntime` 类负责 stateless 的主循环执行（流式组装、工具执行、事件发射），而 `@cline/core` 包中的 `SessionRuntime` 类负责 stateful 的会话编排（消息持久化、扩展工具/hook 注入、会话级 mistake/loop 追踪）。两层通过 `createAgentRuntime` 工厂和 `RuntimeEventAdapter` 解耦，`SessionRuntime` 在每次 `run()` 时构建临时 `AgentRuntime` 实例并注入会话级配置。

Charles 的 `agent/runtime.py::AgentRuntime` 则是单一类混合实现，既承担主循环、流式组装、工具执行（对标 Cline `AgentRuntime`），又承担消息历史持有、工具/hook 注册、snapshot、会话级追踪（对标 Cline `SessionRuntime`）。这导致 Charles 的 `AgentRuntime` 类职责过重（2865 行，含 30+ 方法），缺乏会话编排层的独立抽象，扩展工具系统和持久化层时需要侵入修改主类。

nanobot 残留检查结论：在 12 个文件中发现 nanobot 残留，**全部为注释残留**（docstring 说明、行内来源标注、兼容性说明），**未发现实现逻辑残留**——所有实际代码均基于 Cline 对标设计实现，nanobot 仅作为历史来源参考被注释引用。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.1 章节定义的 6 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.1.1 | stateless loop 函数 | `agent-runtime.ts::AgentRuntime.execute()` (L595-794) — 主循环封装在类的私有 async 方法中，配合 `run_agent_loop` 风格的流式处理 | `runtime.py::AgentRuntime.run()` (L521-817) — 主循环直接在公开 `run()` 方法中，无独立 loop 函数 | Cline 把 loop 放在私有 `execute()`，公开 `run()`/`continue()` 只是 delegate；Charles 把 loop 直接写在公开 `run()` 中，无 delegate 层 | 弱对齐 |
| 2.1.2 | stateful 编排类 | `session-runtime-orchestrator.ts::SessionRuntime` (L279) — 独立的编排类，持有 ConversationStore / MistakeTracker / LoopDetectionTracker / MessageBuilder / ContributionRegistry | 无独立编排类，全部混合在 `AgentRuntime` 中 | Cline 有专门的 SessionRuntime 负责会话编排；Charles 把会话编排职责全部塞入 AgentRuntime，无 SessionRuntime 抽象 | 缺失 |
| 2.1.3 | 消息历史持有 | `SessionRuntime` 通过 `ConversationStore` (L289, L378) 间接持有；`AgentRuntime` 仅持有运行级 `state.messages` (L418) 副本 | `AgentRuntime._state.messages` (L221, L392) 直接持有，无 ConversationStore 抽象 | Cline 消息历史由 SessionRuntime 的 ConversationStore 持有，run 时复制到 AgentRuntime；Charles 直接由 AgentRuntime 持有，无分层 | 弱对齐 |
| 2.1.4 | 工具注册职责 | `SessionRuntime.addTools()` (L485-498) + `ContributionRegistry` (L308-312) 负责会话级工具注入；`AgentRuntime.initialize()` (L526-542) 从 config 读取工具到 `tools` Map | `AgentRuntime.register_tool()` (L364-366) 直接注册到 `self._tools` dict，无 ContributionRegistry 抽象 | Cline 工具注册分两层：SessionRuntime 的 addTools（会话级动态注入）+ AgentRuntime 的 initialize（运行级加载）；Charles 只有单层 register_tool | 弱对齐 |
| 2.1.5 | hook 注册职责 | `SessionRuntime.createRuntimeHooks()` (L853) 在每次 run 时动态构建 hooks；`AgentRuntime.registerHooks()` (L544-555) 从 config 静态注册 | `AgentRuntime.register_hooks()` (L368-369) 直接注册到 `self._hooks`，无动态构建层 | Cline hooks 在 SessionRuntime 层动态构建（支持扩展系统注入），AgentRuntime 只接收最终 hooks；Charles 单层静态注册，无扩展系统集成点 | 弱对齐 |
| 2.1.6 | snapshot 职责 | `AgentRuntime.snapshot()` (L505-519) 返回运行级快照（agentId/runId/status/iteration/messages/usage）；`SessionRuntime.getMessages()` (L458-460) + `getExtensionRegistry()` (L480-482) 返回会话级快照 | `AgentRuntime.snapshot()` (L425-443) 返回混合快照（含 agentId/runId/status/iteration/messages/pending_tool_calls/usage/last_error） | Cline 运行级与会话级快照分离；Charles 单一 snapshot 混合返回所有信息，无层级区分 | 弱对齐 |

## 3. 重点差距详细说明

### 差距 1：缺少 SessionRuntime 编排层抽象（对应对比项 2.1.2）

**Cline 设计**：`SessionRuntime`（session-runtime-orchestrator.ts L279）是独立的会话编排类，承担以下职责：
- 持有 `ConversationStore`（L289）——会话级消息持久化，与运行级 state 分离
- 持有 `MistakeTracker`（L290）和 `LoopDetectionTracker`（L291）——会话级追踪器，跨 run 复用
- 持有 `MessageBuilder`（L301）——provider 请求预处理
- 持有 `ContributionRegistry`（L308-312）——扩展系统注册表，支持 `api.registerTool` / `registerCommand` / `registerMessageBuilder` 等扩展点
- 持有 `RuntimeEventAdapter`（L332）——运行事件到会话事件的适配器
- 通过 `createAgentRuntimeImpl` 工厂（L315-317）在每次 run 时构建临时 `AgentRuntime` 实例

**Charles 设计**：`AgentRuntime`（runtime.py L231）单一类混合承担所有职责：
- `_state.messages`（L221）直接持有消息历史，无 ConversationStore 抽象
- `_mistake_tracker`（L270）和 `_loop_tracker`（L266）作为实例字段，但生命周期与 AgentRuntime 绑定，无法跨会话复用
- 无 MessageBuilder 抽象，provider 预处理逻辑分散在 `_generate_assistant_message` 内
- 无 ContributionRegistry，扩展工具系统（如 MCP、文件 hook）通过 `_load_file_hooks`（L315-358）和 `register_tool`（L364）零散接入
- 无 RuntimeEventAdapter，事件直接通过 `EventEmitter`（L252）发射

**影响**：扩展工具系统、持久化层、多 agent 编排时需要侵入修改 `AgentRuntime` 主类，违反开闭原则。会话级状态（如 mistake 累积、loop 历史）在 `restore()` 后丢失，无法跨会话复用。

### 差距 2：消息历史持有方式分层缺失（对应对比项 2.1.3）

**Cline 设计**：消息历史由 `ConversationStore`（session-runtime-orchestrator.ts L289）持有，`AgentRuntime` 在 run 时通过 `initialMessages`（L834-846）接收副本。run 结束后，`runResult.messages`（L905-907）回写到 `ConversationStore`。这实现了：
- 会话级消息持久化（SessionRuntime 层）
- 运行级消息操作（AgentRuntime 层）
- 两者通过 `messagesToAgentMessages` 转换器解耦

**Charles 设计**：`_state.messages`（runtime.py L221）直接由 `AgentRuntime` 持有，`restore()`（L376-403）只是替换 `self._state.messages`，无独立的 ConversationStore 层。`server.py` 等外部调用方需要手动管理会话持久化，并通过 `messages` 参数（L524）注入历史消息。

**影响**：会话持久化逻辑分散在 `server.py` 等调用方，无法集中管理；多 agent 场景下消息共享需要 hack（如直接操作 `_state.messages`）。

### 差距 3：工具注册与扩展系统集成点缺失（对应对比项 2.1.4）

**Cline 设计**：工具注册分三层：
1. `SessionRuntime.addTools()`（L485-498）——会话级动态注入（如扩展系统注册的工具）
2. `ContributionRegistry`（L308-312）——扩展贡献注册表，支持 `api.registerTool` 在扩展 `setup()` 时注册
3. `AgentRuntime.initialize()`（L526-542）——运行级加载，从 config.tools 和 plugin.setup() 读取

每次 run 时，`SessionRuntime` 在 L801-827 合并 config 声明的工具与扩展贡献的工具，去重后注入 `AgentRuntime`。

**Charles 设计**：只有单层 `register_tool()`（L364-366），直接注册到 `self._tools` dict。文件 hook 系统（L315-358）和 MCP 工具路由（L1596-1644）是硬编码集成点，无通用扩展系统抽象。

**影响**：新增扩展工具系统（如 VS Code 扩展、第三方插件）时需要修改 `AgentRuntime` 主类；无法在运行时动态禁用/启用工具集（除 `tool_routing_rules` 外）。

### 差距 4：hook 动态构建层缺失（对应对比项 2.1.5）

**Cline 设计**：`SessionRuntime.createRuntimeHooks()`（L853）在每次 run 时动态构建 hooks 对象，可合并：
- 扩展系统贡献的 hooks（通过 ContributionRegistry）
- 配置声明的 hooks
- 会话级 tracker hooks（MistakeTracker、LoopDetectionTracker）

`AgentRuntime.registerHooks()`（L544-555）只负责静态注册，不参与动态构建。

**Charles 设计**：`register_hooks()`（L368-369）直接添加到 `self._hooks`，无动态构建层。`_loop_detection_hook`（L268, L1277-1333）和 `_file_context_tracker_hook`（L289, L1117-1242）在 `__init__` 中硬编码注册，无法在运行时替换或扩展。

**影响**：无法在会话级别注入不同的 hook 集合（如不同用户角色的权限 hook）；扩展系统无法贡献 hooks。

## 4. nanobot 残留检查

### 检查范围

在 `agent/` 目录下共发现 12 个文件含 nanobot 残留，全部为**注释残留**（docstring 说明、行内来源标注、兼容性说明），**未发现实现逻辑残留**。

### 注释残留分类

#### 类型 A：实现来源标注（最多，约 80% 残留）

形式：`对标 nanobot xxx 方法` / `对标 nanobot xxx.py L123-185`

出现在：
- `agent/providers/qwen.py` L21, L49, L116, L214, L253, L385, L406
- `agent/tools/exec_tool.py` L2, L8, L9, L10, L18-19, L41, L57, L123, L165, L181, L263
- `agent/tools/file_tools.py` L2, L7
- `agent/tools/web_tool.py` L2, L9-10, L13, L28, L111, L165
- `agent/skills/registry.py` L2, L20, L100, L184
- `agent/skills/loader.py` L2, L29, L48, L96, L167, L222, L392, L423
- `agent/skills/__init__.py` L2, L23

**性质**：纯注释，说明当前代码实现参考了 nanobot 的某个方法/文件，实际代码已用 Cline 对标设计重写。不影响运行时行为。

#### 类型 B：兼容性说明（约 15% 残留）

形式：`兼容 nanobot 现有配置` / `与 nanobot 一致`

出现在：
- `agent/providers/qwen.py` L21（API key 环境变量 DASHSCOPE_API_KEY 兼容）
- `agent/providers/qwen.py` L49（默认流式空闲超时 90s 与 nanobot 一致）
- `agent/session.py` L2, L22-23（session_key 参数兼容 nanobot 内存存储）
- `agent/server.py` L2, L4, L28-29（SSE 事件流兼容 nanobot routes/chat.py）
- `agent/skills/skill_tool.py` L18（与 nanobot 子 agent 隔离执行的本质区别说明）

**性质**：说明配置参数或行为与 nanobot 保持兼容（如环境变量名、超时值、SSE 事件格式），属于**有意的兼容性设计**，不影响 Cline 对标。

#### 类型 C：废弃标注（约 5% 残留）

形式：`[已废弃] nanobot 风格`

出现在：
- `agent/context.py` L275（`extra_sections` 参数已废弃，保留签名仅为向后兼容）

**性质**：明确标注已废弃，无调用方传入，属于**有意的废弃保留**。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。所有实际代码（类定义、方法实现、数据结构、控制流）均基于 Cline 对标设计：
- `AgentRuntime` 类结构对标 Cline `agent-runtime.ts::AgentRuntime`
- `_PendingToolAssembly` / `_InvalidToolCall` / `_PreparedToolExecution` 数据结构对标 Cline 同名接口
- 主循环、流式组装、工具执行逻辑均对标 Cline agent-runtime.ts
- 未发现任何从 nanobot 直接移植的代码逻辑（如 nanobot 的 `Agent` 类、`SkillsLoader` 类等）

### 残留风险评估

| 残留类型 | 文件数 | 风险等级 | 处理建议 |
|---------|--------|---------|---------|
| 类型 A（实现来源标注） | 7 | 低 | 可保留作为历史来源参考，或统一清理为"对标 Cline" |
| 类型 B（兼容性说明） | 4 | 中 | 保留，但应在文档中明确说明"兼容性是临时措施，未来版本可能移除" |
| 类型 C（废弃标注） | 1 | 低 | 可在下个版本删除废弃参数 |

## 5. 修复建议

### P0（高优先级，影响架构正确性）

无。当前 Charles 的单一 `AgentRuntime` 类虽然职责混合，但功能完整，能正确执行 agent 主循环。架构差距是设计层面的，不影响运行时正确性。

### P1（中优先级，影响可扩展性）

**建议 1：引入 SessionRuntime 编排层抽象**

参考 Cline `SessionRuntime`（session-runtime-orchestrator.ts L279），在 `agent/` 目录下新增 `session_runtime.py`，承担：
- 持有 `ConversationStore`（消息历史持久化）
- 持有会话级 `MistakeTracker` / `LoopDetectionTracker`（跨 run 复用）
- 提供 `addTools()` / `addHooks()` 动态注入接口
- 在每次 `run()` 时构建临时 `AgentRuntime` 实例

**收益**：解耦会话编排与运行执行，支持扩展系统集成，为多 agent 编排铺路。

**改动范围**：新增 `session_runtime.py`，`AgentRuntime` 简化为运行级执行引擎，`server.py` 改为调用 `SessionRuntime`。

### P2（低优先级，改善代码组织）

**建议 2：抽取 ConversationStore 抽象**

参考 Cline `ConversationStore`（session-runtime-orchestrator.ts L289），新增 `agent/conversation_store.py`，承担消息历史持久化职责。`AgentRuntime._state.messages` 改为引用 ConversationStore，`restore()` 委托给 ConversationStore。

**收益**：消息持久化逻辑集中管理，支持多种后端（内存、文件、数据库）。

**建议 3：引入 ContributionRegistry 扩展点**

参考 Cline `ContributionRegistry`（session-runtime-orchestrator.ts L308-312），新增 `agent/contribution_registry.py`，提供 `register_tool` / `register_hook` / `register_message_builder` 等扩展点。现有的 `_load_file_hooks` 和 MCP 工具路由改为通过 ContributionRegistry 接入。

**收益**：扩展系统接入点统一，无需修改 `AgentRuntime` 主类。

### P3（可选，注释清理）

**建议 4：清理 nanobot 注释残留（类型 A）**

将 `agent/providers/qwen.py`、`agent/tools/`、`agent/skills/` 中的 `对标 nanobot xxx` 注释统一改为 `对标 Cline xxx` 或直接删除（若已有 Cline 对标注释）。

**收益**：减少历史包袱，代码溯源更清晰。

**注意**：类型 B（兼容性说明）和类型 C（废弃标注）应保留，因为它们记录了有意的兼容性设计。

## 6. 验证方法建议

### 验证方法 1：类结构图对比

绘制 Cline 与 Charles 的类结构图，对比以下维度：
- 类的数量与职责划分（Cline 应有 AgentRuntime + SessionRuntime 两个核心类；Charles 只有 AgentRuntime）
- 字段归属（消息历史、工具注册表、hook 列表、tracker 分别归属哪个类）
- 方法层级（公开 API / 私有执行 / 动态构建层的分层）

**预期**：Cline 类结构图显示清晰的两层分离；Charles 类结构图显示单一类承担所有职责。

### 验证方法 2：扩展系统集成测试

构造以下场景验证扩展性差距：
1. 动态注入新工具：Cline 通过 `SessionRuntime.addTools()` 在 run 之间注入；Charles 需要直接调用 `AgentRuntime.register_tool()`
2. 动态注入 hook：Cline 通过 `SessionRuntime.createRuntimeHooks()` 在 run 时构建；Charles 需要修改 `__init__` 或手动 `register_hooks()`
3. 会话级 tracker 复用：Cline 的 `MistakeTracker` 跨 run 累积；Charles 的 `MistakeTracker` 在 `restore()` 后重置

**预期**：Cline 能在不修改主类的前提下完成扩展注入；Charles 需要侵入修改或受限于实例生命周期。

### 验证方法 3：消息历史持久化测试

构造多 run 场景，验证消息历史的持有与恢复：
1. run 1 结束后，检查消息历史归属（Cline 应在 ConversationStore；Charles 应在 `_state.messages`）
2. 调用 `restore()` 后，检查 tracker 状态（Cline 的会话级 tracker 应保留；Charles 的 tracker 应重置）
3. 模拟 AgentRuntime 实例销毁重建，检查消息历史是否丢失（Cline 应通过 ConversationStore 保留；Charles 应丢失）

**预期**：Cline 消息历史与会话级 tracker 跨 AgentRuntime 实例保留；Charles 全部丢失。

### 验证方法 4：nanobot 残留扫描

执行 `grep -r "nanobot" agent/ --include="*.py"` 确认残留数量与类型，人工审查每个残留点确认：
1. 是否为注释（非代码逻辑）
2. 是否标注了正确的兼容性/废弃状态
3. 是否有遗漏的实现逻辑残留

**预期**：全部残留为注释，无实现逻辑残留，类型 B/C 应有明确的兼容性/废弃说明。
