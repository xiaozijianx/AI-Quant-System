# Agent 与 Cline 全面对比计划 V2（逻辑级 + Prompt 级）

> 生成时间：2026-07-28
> 目标：在已有 6 份对比/修改计划（AGENT_CLINE_COMPARISON_PLAN / AGENT_FINAL_ALIGNMENT_PLAN / AGENT_MIGRATION_PLAN / AGENT_PHASE28_PLAN / AGENT_PHASE30_PLAN / AGENT_PROMPT_FIX_PLAN）基础上，进行**更细化、更全面**的对比，覆盖功能结构、实现结构、Prompt 组件结构、Prompt 形式风格四个维度
> 原则：
> - 不停留在"模块有无"层面，深入到每个函数的逻辑分支、数据流、状态变迁、错误处理
> - 不仅对比 system prompt，还要对比 agent prompt（AGENTS.md）和 skill prompt（SKILL.md）
> - 不仅对比功能实现，还要对比 Prompt 的组件结构、措辞风格、标签格式
> - 每次新视角的对比都会发现上一视角看不到的细节差距，本计划纳入 7 个视角
> - 以 Cline 源码为参考标准，保留 Charles 合理的量化场景特化

---

## 一、对比方法论

### 1.1 七维对比视角

本计划相比历史计划，新增了"Prompt 形式风格"视角，并将对比维度扩展为 7 个：

| 视角 | 含义 | 历史计划覆盖情况 |
|------|------|-----------------|
| **V1 功能结构** | 模块/包划分、分层架构、入口装配 | AGENT_CLINE_COMPARISON_PLAN 部分覆盖 |
| **V2 实现结构** | 每个功能的函数逻辑、控制流、数据流 | AGENT_CLINE_COMPARISON_PLAN 部分覆盖 |
| **V3 Prompt 组件结构** | system prompt 分层、段落数量、段落顺序 | AGENT_PROMPT_FIX_PLAN 部分覆盖 |
| **V4 Prompt 形式风格** | 标签格式、措辞风格、字段名语言、表格 vs 列表 | LOGICAL_DIFF_V1 部分覆盖 |
| **V5 Agent Prompt** | AGENTS.md frontmatter、主体结构、决策树 | AGENT_PROMPT_FIX_PLAN 部分覆盖 |
| **V6 Skill Prompt** | SKILL.md frontmatter、Workflow、脚本规则 | AGENT_PROMPT_FIX_PLAN 部分覆盖 |
| **V7 上下文与辅助系统** | 压缩、MCP、Provider、持久化、Hooks | AGENT_CLINE_COMPARISON_PLAN 部分覆盖 |

### 1.2 逻辑级对比维度（每个对比项都需覆盖 D1-D7）

| 维度 | 含义 |
|------|------|
| **D1 数据结构** | 字段是否齐全、类型是否等价、可选性是否一致 |
| **D2 控制流** | 分支条件、循环边界、提前返回、异常路径 |
| **D3 状态变迁** | 状态字段何时变更、变更顺序、并发安全 |
| **D4 错误处理** | 异常捕获范围、错误传播、降级策略 |
| **D5 副作用** | 事件发射、持久化、日志、外部调用时机 |
| **D6 边界条件** | 空值、超长、越界、并发、超时 |
| **D7 语义等价** | 同名方法/字段的行为是否真正等价 |

### 1.3 Prompt 级对比维度（每个 prompt 段都需覆盖 P1-P6）

| 维度 | 含义 |
|------|------|
| **P1 段落存在性** | Cline 有此段，Charles 是否有 |
| **P2 段落顺序** | 在 system prompt 中的位置是否一致 |
| **P3 段落内容** | 字段、措辞、示例是否一致 |
| **P4 标签格式** | XML 标签 vs Markdown 标题 vs 纯文本 |
| **P5 字段名语言** | 中文 vs 英文 |
| **P6 条件注入** | 何时注入此段（always / mode / provider / path） |

### 1.4 验证手段

- **静态对比**：源码逐行 diff（Grep + Read）
- **动态验证**：构造相同输入，对比两边输出/事件流
- **Prompt 抓取**：启动 agent，打印完整 system prompt，逐段对比
- **边界测试**：构造极端场景（空消息、超长、并发 abort）
- **回归测试**：`python tests/test_agent_e2e.py` + 新增针对性测试

### 1.5 对比记录格式

每个小阶段输出一份 `CLINE_DIFF_V2/phase_<X>.<Y>_<name>.md`，含：

```markdown
| 对比项 | Cline 实现 | Charles 实现 | 一致性 | 差距描述 | 修复建议 |
|--------|-----------|-------------|--------|---------|---------|
| ...    | 文件:行号  | 文件:行号    | 一致/弱/缺失/语义不等价 | ... | ... |
```

### 1.6 一致性等级定义

| 等级 | 含义 |
|------|------|
| **完全一致** | 逻辑、字段、语义、Prompt 风格全部等价 |
| **弱对齐** | 有类似实现，但字段缺失或语义不等价 |
| **缺失** | Cline 有，Charles 没有 |
| **额外** | Charles 有，Cline 没有（合理增强或待清理） |
| **语义不等价** | 同名但行为不同 |
| **风格差异** | 功能等价但 Prompt 措辞/标签/格式不同 |

---

## 二、阶段总览（7 大阶段，130+ 小阶段）

| 阶段 | 主题 | 对比视角 | 小阶段数 | 优先级 | 依赖 |
|------|------|---------|---------|--------|------|
| **Phase 1** | 顶层架构与功能模块对比 | V1 功能结构 | 7 | P0 | 无 |
| **Phase 2** | 核心引擎（AgentRuntime）实现对比 | V2 实现结构 | 12 | P0 | P1 |
| **Phase 3** | 工具系统实现对比 | V2 实现结构 | 20 | P0 | P1 |
| **Phase 4** | 技能系统与 Skill Prompt 对比 | V2+V6 Skill Prompt | 18 | P0 | P1, P3 |
| **Phase 5** | System Prompt 组件结构与形式风格对比 | V3+V4 Prompt | 23 | P0 | P4 |
| **Phase 6** | Agent Prompt（AGENTS.md）组件结构与形式风格对比 | V5 Agent Prompt | 12 | P0 | P5 |
| **Phase 7** | 上下文管理与辅助系统对比 | V7 辅助系统 | 23 | P1 | P2 |

---

## 三、Phase 1：顶层架构与功能模块对比

**对标视角**：V1 功能结构
**目标**：对比 Charles 与 Cline 在顶层模块划分、分层架构、入口装配上的差异
**Cline 源码根目录**：`third_party/cline/`
**Charles 源码根目录**：`agent/`

### P1.1 包/模块划分对比

**Cline 包结构**（4 层）：
- `sdk/packages/shared/` — 类型 + 协议（agent.ts, llms/, tools/, prompt/）
- `sdk/packages/agents/` — stateless 主循环（agent-runtime.ts）
- `sdk/packages/core/` — stateful 编排（runtime/, extensions/, services/, hooks/）
- `apps/` — 宿主层（vscode/, cli/, cline-hub/）

**Charles 包结构**（单层）：
- `agent/` — 全部逻辑（types.py, runtime.py, context.py, tools/, skills/, providers/, ...）

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.1.1 | shared 层（类型+协议） | 独立包 | agent/types.py 单文件 | Charles 未分层 |
| 1.1.2 | agents 层（stateless loop） | 独立包 | agent/runtime.py 混合 | Charles 未拆分 stateless/stateful |
| 1.1.3 | core 层（stateful 编排） | 独立包 | agent/runtime.py + server.py | Charles 用 server.py 替代 |
| 1.1.4 | apps 层（宿主） | vscode/cli/hub | server.py（FastAPI） | Charles 单一宿主 |
| 1.1.5 | extensions 目录 | core/extensions/ | agent/ 各子目录 | Charles 无统一 extensions 概念 |

**验证方法**：对比两边目录树，绘制分层架构图

### P1.2 分层架构对比（shared/agents/core/apps 四层）

**Cline 分层依赖关系**：
```
shared（类型） ← agents（loop） ← core（编排） ← apps（宿主）
```

**Charles 实际依赖关系**：
```
types.py ← runtime.py ← server.py
        ← context.py
        ← tools/
        ← skills/
        ← providers/
```

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.2.1 | shared 层独立性 | 独立包，无依赖 | types.py，被各模块依赖 | Charles 共享层不独立 |
| 1.2.2 | agents 层独立性 | 独立包，仅依赖 shared | runtime.py 依赖 types/context/tools | Charles loop 层不独立 |
| 1.2.3 | core 层编排职责 | runtime/orchestration/ | server.py | Charles 编排与 HTTP 路由混合 |
| 1.2.4 | apps 层宿主隔离 | apps/vscode + apps/cli | server.py 单一宿主 | Charles 无多宿主能力 |

**验证方法**：用 `pydeps` 或人工绘制 Charles 依赖图，对比 Cline 分层

### P1.3 入口与装配点对比

**Cline 装配点**：
- `apps/cli/src/main.ts` — CLI 入口
- `apps/vscode/src/extension.ts` — VSCode 入口
- `sdk/packages/core/src/ClineCore.ts` — 核心装配

**Charles 装配点**：
- `agent/server.py::_create_runtime()` — 唯一装配点

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.3.1 | 装配函数 | ClineCore.ts | _create_runtime() | Charles 单一函数 |
| 1.3.2 | 多宿主支持 | vscode/cli/hub | 仅 server.py | Charles 无多宿主 |
| 1.3.3 | 装配配置来源 | config 文件 + 环境变量 | 环境变量 + agent_config/ | Charles 用 YAML |
| 1.3.4 | 装配时工具注册 | core/extensions/tools/ | agent/tools/__init__.py | Charles 集中注册 |
| 1.3.5 | 装配时 hook 注册 | core/hooks/ | agent/hooks.py + file_hooks/ | Charles 双重 hook |

**验证方法**：对比两边装配函数的初始化顺序

### P1.4 配置文件组织对比

**Cline 配置组织**：
- `.cline/` — 工作区配置（mcp_settings.json, skills/）
- `.clinerules/` — 规则文件（按主题分文件）
- `~/.cline/` — 全局配置
- `apps/vscode/package.json` — VSCode 配置

**Charles 配置组织**：
- `agent_config/` — 工作区配置（skills/, rules/, hooks/, mcp_servers.yaml, system_prompt.yaml）
- 无全局配置概念

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.4.1 | 工作区配置目录 | .cline/ | agent_config/ | 路径不同 |
| 1.4.2 | 全局配置 | ~/.cline/ | 无 | Charles 缺失 |
| 1.4.3 | 规则文件组织 | .clinerules/ 按主题 | agent_config/rules/ 按业务模式 | 组织维度不同 |
| 1.4.4 | MCP 配置格式 | mcp_settings.json | mcp_servers.yaml | JSON vs YAML |
| 1.4.5 | 系统提示配置 | 内嵌代码 | agent_config/system_prompt.yaml | Charles 可配置 |
| 1.4.6 | 审批记忆 | 无持久化 | approval_memory.json | Charles 额外增强 |
| 1.4.7 | 规则开关 | toggles 机制 | rule_toggles.json | 形式不同 |

**验证方法**：对比两边配置文件树，检查加载逻辑

### P1.5 数据目录组织对比

**Cline 数据组织**：
- SQLite 数据库（sessions.db）
- shadow-git 仓库（checkpoints）
- 全局 storage 目录

**Charles 数据组织**：
- `agent_data/sessions/` — JSON 会话文件
- `agent_data/state/` — 会话状态
- `agent_data/file_context/` — 文件追踪
- `agent_data/checkpoints/` — 检查点
- `data/` — 业务数据（financial_data, vector_store, parsed）

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.5.1 | 会话存储 | SQLite | JSON 文件 | 格式不同 |
| 1.5.2 | 检查点存储 | shadow-git | file_checkpoint.py | 实现不同 |
| 1.5.3 | 业务数据 | 无 | data/ | Charles 量化场景特化 |
| 1.5.4 | 数据目录层级 | 扁平 | 分层（agent_data + data） | Charles 双数据目录 |

**验证方法**：对比两边数据目录结构

### P1.6 扩展机制对比（hook/plugin/marketplace）

**Cline 扩展机制**：
- Python Hooks（9 钩子点）
- 文件 Hooks（7 种类型，HookProcess 跑外部脚本）
- Plugin 系统（plugin-loader, plugin-sandbox）
- Marketplace（远程插件安装）

**Charles 扩展机制**：
- Python Hooks（9 钩子点）
- 文件 Hooks（7 种类型，file_hooks/）
- 无 Plugin 系统
- 无 Marketplace

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.6.1 | Python Hooks | 9 钩子点 | 9 钩子点 | 已对齐 |
| 1.6.2 | 文件 Hooks 类型 | 7 种 | 7 种 | 已对齐 |
| 1.6.3 | Plugin 系统 | 完整 | 无 | Charles 缺失 |
| 1.6.4 | Marketplace | 完整 | 无 | Charles 缺失 |
| 1.6.5 | hook 模板 | templates.ts | agent_config/hooks/templates/ | 已对齐 |
| 1.6.6 | hook 沙箱 | plugin-sandbox | 无 | Charles 缺失 |

**验证方法**：对比两边扩展机制清单

### P1.7 测试组织对比

**Cline 测试组织**：
- `sdk/packages/*/src/**/*.test.ts` — 单元测试
- `apps/vscode/src/test/e2e/` — E2E 测试
- `evals/` — 评估测试

**Charles 测试组织**：
- `tests/test_agent_e2e.py` — E2E 测试
- `tests/test_phase*.py` — 阶段性单元测试
- 无评估测试

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 1.7.1 | 单元测试覆盖 | 全面 | 阶段性 | Charles 不全 |
| 1.7.2 | E2E 测试 | 有 | 有 | 已对齐 |
| 1.7.3 | 评估测试 | evals/ | 无 | Charles 缺失 |
| 1.7.4 | 测试夹具 | fixtures/ | 无 | Charles 缺失 |

**验证方法**：对比两边测试文件清单

---

## 四、Phase 2：核心引擎（AgentRuntime）实现对比

**对标视角**：V2 实现结构
**目标**：对比 Charles `agent/runtime.py` 与 Cline `sdk/packages/agents/src/agent-runtime.ts` 的实现细节
**Cline 源码**：`sdk/packages/agents/src/agent-runtime.ts`（L595-794 主循环 + L965-1058 流式组装 + L424-470 abort）
**Charles 源码**：`agent/runtime.py`

### P2.1 AgentRuntime 类结构对比（stateless vs stateful 拆分）

**Cline 架构**：
- `@cline/agents` 包 — stateless loop（`run_agent_loop` 函数）
- `@cline/core` 包 — stateful 编排（`SessionRuntime` 类）

**Charles 架构**：
- `agent/runtime.py::AgentRuntime` — 单一类，混合 stateless + stateful

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.1.1 | stateless loop 函数 | run_agent_loop() | 无独立函数 | Charles 未拆分 |
| 2.1.2 | stateful 编排类 | SessionRuntime | AgentRuntime | Charles 混合 |
| 2.1.3 | 消息历史持有 | SessionRuntime.messages | AgentRuntime._messages | 位置不同 |
| 2.1.4 | 工具注册职责 | SessionRuntime | AgentRuntime | 位置不同 |
| 2.1.5 | hook 注册职责 | SessionRuntime | AgentRuntime | 位置不同 |
| 2.1.6 | snapshot 职责 | SessionRuntime | AgentRuntime | 位置不同 |

**验证方法**：对比两边类结构图，检查 stateless/stateful 是否分离

### P2.2 主循环 run() 控制流对比

**Cline 主循环**（agent-runtime.ts L595-794）：
```
execute(input) → while iteration < maxIterations && !aborted && !stopped:
  throwIfAborted()
  callBeforeRunHooks()
  emit run_started
  addUserMessage()
  generateAssistantMessage()
  emit message_added
  if no tool_calls: completion_policy 判断
  executeToolCalls()
  findCompletingToolMessage()
  emit turn_finished
```

**Charles 主循环**（runtime.py::run()）：
```
run(input) → while iteration < max_iterations and not _aborted:
  _throw_if_aborted()
  _call_before_run_hooks()
  emit run_started
  _add_user_message()
  _generate_assistant_message()
  emit message_added
  if no tool_calls: completion_policy 判断
  _execute_tool_calls()
  _find_completing_tool()
  emit turn_finished
```

| # | 对比项 | Cline 行号 | Charles 行号 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.2.1 | while 条件顺序 | L600-610 | runtime.py | 三个条件顺序 |
| 2.2.2 | throwIfAborted 调用点 | L588, L610, L796 | runtime.py | 调用点数量 |
| 2.2.3 | emit run_started 时机 | L611 | runtime.py | hooks 前后 |
| 2.2.4 | beforeRunHooks stop 处理 | L612-620 | runtime.py | stop 后状态 |
| 2.2.5 | addUserMessage 位置 | L625-640 | runtime.py | 是否经 formatUserInputBlock |
| 2.2.6 | generateAssistantMessage 返回 | L645-660 | runtime.py | 元组结构 |
| 2.2.7 | emit message_added 时机 | L660 | runtime.py | 立即 vs batch |
| 2.2.8 | 无 tool_calls 分支 | L665-680 | runtime.py | completion_policy 逻辑 |
| 2.2.9 | executeToolCalls 调用 | L685-700 | runtime.py | parallel vs sequential |
| 2.2.10 | findCompletingToolMessage | L1312-1332 | runtime.py | 检查条件 |
| 2.2.11 | completes_run 后 finish | L700-710 | runtime.py | status 值 |
| 2.2.12 | emit turn_finished 时机 | L730 | runtime.py | 每轮 vs finish |
| 2.2.13 | max_iterations 超限 | L790-794 | runtime.py | status + emit |
| 2.2.14 | 异常捕获范围 | L796-809 | runtime.py | 吞掉哪些异常 |
| 2.2.15 | finally 清理 | L805-809 | runtime.py | 清理内容 |
| 2.2.16 | consumePendingUserMessage | L841-852 | runtime.py | iteration > 1 检查 |
| 2.2.17 | iteration 自增时机 | L605 | runtime.py | hooks 前后 |

**验证方法**：画两边的控制流图，逐节点对比；构造 max_iterations 边界测试

### P2.3 _generate_assistant_message 流式组装对比

**Cline 流式组装**（agent-runtime.ts L965-1058）：
- `PendingToolAssembly` 数据结构（tool_call_id / tool_name / input_text / input_value / index）
- 组装 key = `toolCallId ?? tool_${index}`
- 流式过程中尝试 parse 部分 JSON
- `invalidToolCalls` 检测与反馈

**Charles 流式组装**（runtime.py::_generate_assistant_message）：
- `_PendingToolAssembly` 数据结构
- 组装 key = `event.index`（无 index 时 fallback）
- Qwen 特殊处理：按 index 维护 tool_call_ids map

| # | 对比项 | Cline 行号 | Charles 行号 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.3.1 | PendingToolAssembly 字段 | L965-980 | runtime.py | 字段完整性 |
| 2.3.2 | 组装 key 策略 | L985-1000 | runtime.py | index 优先级 |
| 2.3.3 | tool_call_id 不稳定处理 | N/A | qwen.py | Charles Qwen 特化 |
| 2.3.4 | input_text 增量累积 | L1000-1020 | runtime.py | 拼接方式 |
| 2.3.5 | 增量 JSON parse 尝试 | L1020-1030 | runtime.py | 是否流式 parse |
| 2.3.6 | invalidToolCalls 检测 | L1031-1058 | runtime.py | 检测条件 |
| 2.3.7 | invalidToolCalls 反馈 | L1040-1050 | runtime.py | metadata 写入 |
| 2.3.8 | tool_call 完成判定 | L1050-1058 | runtime.py | finish vs parse |
| 2.3.9 | tool_name 为空行为 | L1035 | runtime.py | 跳过/报错/invalid |
| 2.3.10 | 多 tool_call 并发组装 | L965-1000 | runtime.py | 按 index 区分 |
| 2.3.11 | usage event 处理 | L302-347 | runtime.py | 累积 vs 替换 |
| 2.3.12 | reasoning_delta 累积 | L1015-1020 | runtime.py | ReasoningPart |
| 2.3.13 | finish event 处理 | L1080-1090 | runtime.py | finish_reason 提取 |
| 2.3.14 | 流式 metadata 合并 | L965-1058 | runtime.py | _deep_merge_metadata |
| 2.3.15 | reasoning token 检测 | L302-347 | runtime.py | captureUnexpectedReasoningTokens |

**验证方法**：用 dummy model 构造流式分片，对比两边组装结果

### P2.4 _execute_tool_calls 工具执行对比

**Cline 工具执行**（agent-runtime.ts L685-700, L1291-1310）：
- 支持 parallel / sequential 两种模式
- beforeTool hooks（可 skip/modify input/stop）
- tool.execute(input, context)
- afterTool hooks（可修改 result/stop）
- 构建 tool result message

**Charles 工具执行**（runtime.py::_execute_tool_calls）：
- sequential 模式
- before_tool hooks
- tool.execute(input, context)
- after_tool hooks

| # | 对比项 | Cline 行号 | Charles 行号 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.4.1 | parallel 模式支持 | L685-700 | runtime.py | Charles 仅 sequential |
| 2.4.2 | beforeTool 调用 | L1291-1310 | runtime.py | 调用顺序 |
| 2.4.3 | tool.execute 传参 | L1295 | runtime.py | context 字段 |
| 2.4.4 | afterTool 调用 | L1300 | runtime.py | 调用顺序 |
| 2.4.5 | tool result message 构建 | L1305 | runtime.py | 字段结构 |
| 2.4.6 | tool 执行超时 | withTimeout | asyncio.wait_for | 实现方式 |
| 2.4.7 | tool 重试 | retryable + maxRetries | 无 | Charles 缺失（待确认） |
| 2.4.8 | abort_signal 透传 | AgentToolContext.signal | AgentToolContext.signal | 已对齐 |
| 2.4.9 | 工具结果截断 | output-limits.ts | constants.py | 阈值不同 |
| 2.4.10 | 工具结果序列化 | 原样 | 原样 | 已对齐 |

**验证方法**：对比两边工具执行流程图

### P2.5 completion_policy + completes_run 对比

**Cline 实现**（agent.ts L430-433 + agent-runtime.ts L670-710）：
- `CompletionPolicy` dataclass（require_completion_tool + completion_guard）
- 无 tool_calls 时：若 require_completion_tool=True，追加 reminder 消息继续
- completes_run 工具成功后 finish_run

**Charles 实现**（types.py + runtime.py）：
- `CompletionPolicy` dataclass
- 同样逻辑

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.5.1 | CompletionPolicy 字段 | agent.ts L430-433 | types.py | 字段完整性 |
| 2.5.2 | require_completion_tool 逻辑 | L670-678 | runtime.py | reminder 构建 |
| 2.5.3 | completion_guard 回调 | L675 | runtime.py | 是否调用 |
| 2.5.4 | completes_run 检查 | L1312-1332 | runtime.py | 检查条件 |
| 2.5.5 | completes_run 后 status | L700-710 | runtime.py | status 值 |
| 2.5.6 | reminder 循环前预注入 | L670-678 | runtime.py | Stage 10.3 已实现 |

**验证方法**：构造无 tool_calls 场景，对比两边行为

### P2.6 restore() + abort() 对比

**Cline 实现**（agent-runtime.ts L454-470, L487-503, L588-593）：
- `AbortController` 类（signal + abort() + reason）
- `throwIfAborted()` 调用点（循环顶、stream 中、tool 前）
- `restore(messages)` — abort 当前运行 + 重置状态 + 替换消息

**Charles 实现**（abort.py + runtime.py）：
- `AbortController` 类（signal: asyncio.Event + abort() + reason）
- `_throw_if_aborted()` 调用点
- `restore(messages)`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.6.1 | AbortController 类结构 | L424 | abort.py | 字段完整性 |
| 2.6.2 | signal 类型 | AbortSignal | asyncio.Event | 类型不同 |
| 2.6.3 | abort() 副作用 | L455-465 | runtime.py | status + last_error + emit |
| 2.6.4 | throwIfAborted 调用点 | L588, L610, L796 | runtime.py | 调用点数量 |
| 2.6.5 | signal 透传到 model.stream | L645 | qwen.py | 是否检查 signal |
| 2.6.6 | signal 透传到 tool.execute | L685 | tools/ | AgentToolContext.signal |
| 2.6.7 | stream 中途 abort 行为 | L796 | qwen.py | raise AbortedError |
| 2.6.8 | tool 中途 abort 行为 | L700 | run_commands.py | 子进程 kill |
| 2.6.9 | abort 后状态清理 | L805-809 | runtime.py | unsubscribe |
| 2.6.10 | abort 事件 emit | L465 | events.py | run_failed vs run_finished |
| 2.6.11 | reason 字段传播 | L465 | runtime.py | snapshot.last_error |
| 2.6.12 | 多次 abort 幂等 | L455 | runtime.py | 重复调用行为 |
| 2.6.13 | restore() 实现 | L487-503 | runtime.py | 重置内容 |
| 2.6.14 | restore 与 abort 关系 | L487 | runtime.py | 是否先 abort |
| 2.6.15 | abort 时记录 lastError | L465 | runtime.py L350 | 已对齐（Stage 30.2） |
| 2.6.16 | abort 时 kill 子进程 | 自动 | _wait_process_with_abort | 已对齐（Stage 30.3） |

**验证方法**：stream 中途调用 abort，测响应时间；tool 执行中 abort，测子进程 kill

### P2.7 invalidToolCalls + normalize_input_for_schema 对比

**Cline 实现**（agent-runtime.ts L1031-1058, L1365-1367）：
- `_InvalidToolCall` 数据结构
- 组装阶段写入 `message.metadata["invalid_tool_calls"]`
- 下一轮生成错误 result message
- `normalizeJsonLikeStringsForSchema` — 递归反序列化字符串化的 JSON

**Charles 实现**（runtime.py）：
- `_InvalidToolCall` 数据结构
- `_extract_invalid_tool_calls`
- `_normalize_input_for_schema`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.7.1 | invalidToolCalls 检测条件 | L1031-1058 | runtime.py | 空 name / parse 失败 |
| 2.7.2 | invalidToolCalls 写入位置 | L1040-1050 | runtime.py | message.metadata |
| 2.7.3 | 下一轮错误 result 生成 | L1050-1058 | runtime.py | 时机 |
| 2.7.4 | normalizeJsonLikeStringsForSchema | L1365-1367 | runtime.py | 递归深度 |
| 2.7.5 | schema 校验调用时机 | execute 入口 | _prepare_tool_execution | 位置 |
| 2.7.6 | schema 校验失败错误格式 | validateWithZod | jsonschema | 错误信息结构 |

**验证方法**：构造空 name / 畸形 JSON 的 tool_call，对比两边处理

### P2.8 LoopDetection + MistakeTracker 对比

**Cline 实现**（core/runtime/safety/）：
- `LoopDetectionTracker`（软阈值 3 / 硬阈值 5）
- 循环判定 key = tool_name + input hash
- `MistakeTracker`（mistake_type 枚举：param_error/tool_not_found/permission_denied/exec_error/timeout）
- 每类独立阈值
- safety rules 引擎

**Charles 实现**（loop_detection.py + mistake_tracker.py）：
- `LoopDetectionTracker`
- `MistakeTracker`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.8.1 | LoopDetectionTracker 数据结构 | loop-detection.ts | loop_detection.py | 字段完整性 |
| 2.8.2 | 循环判定 key | loop-detection.ts | loop_detection.py | tool_name + input hash |
| 2.8.3 | 软阈值触发行为 | loop-detection.ts | loop_detection.py | 注入提示 vs 警告 |
| 2.8.4 | 硬阈值触发行为 | loop-detection.ts | loop_detection.py | abort + status |
| 2.8.5 | key 老化机制 | loop-detection.ts | loop_detection.py | LRU / 时间窗口 |
| 2.8.6 | MistakeTracker mistake_type 枚举 | mistake-tracker.ts | mistake_tracker.py | 5 类完整性 |
| 2.8.7 | 每类独立阈值 | mistake-tracker.ts | mistake_tracker.py | 软/硬阈值 |
| 2.8.8 | 错误分类逻辑 | mistake-tracker.ts | mistake_tracker.py | Exception → type |
| 2.8.9 | 软阈值提示格式 | mistake-tracker.ts | mistake_tracker.py | 注入结构 |
| 2.8.10 | 硬阈值 abort 标记 | mistake-tracker.ts | mistake_tracker.py | MistakeLimitExceeded |
| 2.8.11 | 集成方式 | rules.ts | runtime.py | hook vs inline |
| 2.8.12 | safety rules 引擎 | rules.ts | 无 | Charles 缺失 |
| 2.8.13 | 跨轮次状态保持 | mistake-tracker.ts | mistake_tracker.py | session vs runtime |

**验证方法**：构造连续相同参数工具调用，对比两边处理

### P2.9 事件系统 EventEmitter 对比

**Cline 实现**（agent-runtime.ts emit 调用点 + shared/agent.ts 事件类型）：
- 事件类型枚举：run_started/turn_started/assistant_text_delta/assistant_reasoning_delta/message_added/turn_finished/run_finished/run_failed/tool_execution_started/tool_execution_finished/usage_updated/status_notice
- `EventEmitter.subscribe` 返回 unsubscribe 函数
- emit 同步 vs 异步

**Charles 实现**（events.py）：
- 事件类型常量
- `EventEmitter` 类

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.9.1 | 事件类型枚举完整性 | agent.ts | events.py | 12 类完整性 |
| 2.9.2 | AgentEvent 字段 | agent.ts | events.py | 字段完整性 |
| 2.9.3 | subscribe 返回值 | agent-runtime.ts L399 | events.py | unsubscribe 函数 |
| 2.9.4 | emit 同步 vs 异步 | L611 etc. | events.py | await vs fire-and-forget |
| 2.9.5 | listener 异常处理 | L611-620 | events.py | 是否影响其他 listener |
| 2.9.6 | 事件顺序保证 | 全文 | events.py | 同步 vs 异步顺序 |
| 2.9.7 | snapshot 在事件中的角色 | agent.ts | events.py | 引用 vs 深拷贝 |
| 2.9.8 | accumulated_text 语义 | agent.ts | events.py | delta vs 累积 |
| 2.9.9 | message_added 触发时机 | L660, L720 | events.py | assistant + tool 都 emit? |
| 2.9.10 | status_notice 用途 | agent.ts | events.py | 用途一致性 |
| 2.9.11 | tool_execution_started 字段 | agent.ts | events.py | metadata 字段 |
| 2.9.12 | run_failed vs run_finished 互斥 | L796-809 | events.py | 失败时只 emit 一个 |

**验证方法**：订阅所有事件，记录 type 序列，对比两边

### P2.10 Hooks 生命周期对比（9 钩子点）

**Cline 实现**（shared/agent.ts L265-364 + agent-runtime.ts L229-237, L544-554, L796-809）：
- 9 个钩子点：before_run/after_run/before_model/after_model/before_tool/after_tool/prepare_turn_input/format_user_input_block/before_approval
- HookBag + 注册/调用
- 钩子返回 None 语义

**Charles 实现**（hooks.py）：
- 9 个钩子点
- HookBag

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.10.1 | 9 钩子点枚举 | agent.ts L265-364 | hooks.py | 完整性 |
| 2.10.2 | BeforeRunContext 字段 | agent.ts | hooks.py | snapshot |
| 2.10.3 | BeforeModelContext 字段 | agent.ts | hooks.py | snapshot/request/session_id |
| 2.10.4 | BeforeModelResult 字段 | agent.ts | hooks.py | stop/reason/messages/tools/options |
| 2.10.5 | BeforeToolContext 字段 | agent.ts | hooks.py | snapshot/tool/tool_call/input |
| 2.10.6 | BeforeToolResult 字段 | agent.ts | hooks.py | skip/stop/reason/input |
| 2.10.7 | AfterToolResult 字段 | agent.ts | hooks.py | stop/reason/result |
| 2.10.8 | 钩子执行顺序 | L544-554 | hooks.py | 注册序 vs 优先级 |
| 2.10.9 | 钩子失败处理 | L544-554 | hooks.py | 是否中断后续 |
| 2.10.10 | prepare_turn_input 调用时机 | L841-852 | runtime.py | model.stream 前 |
| 2.10.11 | format_user_input_block 作用 | L625-640 | runtime.py | 包装 user input |
| 2.10.12 | before_approval 与 toolPolicies 关系 | agent.ts | hooks.py + approval.py | hook vs config |
| 2.10.13 | 钩子返回 None 语义 | L544-554 | hooks.py | 继续不修改 vs 显式返回 |
| 2.10.14 | 异步钩子 vs 同步钩子 | agent.ts | hooks.py | 是否区分 async |
| 2.10.15 | on_task_resume / on_task_cancel | apps/vscode hooks | hooks.py | 触发时机 |
| 2.10.16 | additional_context 字段 | N/A | hooks.py | Charles 额外增强（context-injection） |

**验证方法**：注册多个同类型 hook，看执行顺序；构造 hook 抛错

### P2.11 Turn Queue 用户输入排队对比

**Cline 实现**（core/runtime/turn-queue/pending-prompt-service.ts）：
- `PendingPromptEntry`（id/prompt/mode/delivery/user_images/user_files）
- delivery 枚举：queue vs steer
- enqueue / consume / consume_for_steer
- 状态持久化

**Charles 实现**（turn_queue.py）：
- `PendingPromptEntry`
- `PendingPromptService`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.11.1 | PendingPromptEntry 字段 | L54 | turn_queue.py | 字段完整性 |
| 2.11.2 | delivery 枚举 | L60 | turn_queue.py | queue vs steer |
| 2.11.3 | enqueue 入队语义 | L100 | turn_queue.py | steer 是否插队首 |
| 2.11.4 | consume 消费时机 | L150 | runtime.py | run 结束后自动 |
| 2.11.5 | consume_for_steer 时机 | L200 | runtime.py | iteration > 1 检查 |
| 2.11.6 | steer 插入位置 | L841 | runtime.py | model request messages |
| 2.11.7 | queue 自动启动新 run | pending-prompt-service.ts | server.py | Cline 自动 vs Charles 前端触发 |
| 2.11.8 | 状态持久化 | L300 | turn_queue.py | 内存 vs 磁盘 |
| 2.11.9 | list_pending 查询 | L250 | server.py | 返回排队列表 |
| 2.11.10 | delete / update | L280, L290 | server.py | 删除/更新 |
| 2.11.11 | SSE 事件通知 | session-event-projector | server.py | pending_prompts_updated |

**验证方法**：运行中发送多条消息，测试排队顺序；测试 steer delivery

### P2.12 Budget Projection 对比

**Cline 实现**（core/extensions/context/budget-projection/）：
- `BudgetPolicyIntent` 枚举
- `ProjectionPolicy` 字段
- `resolve_projection_policy`
- `find_latest_typed_user_message_index`
- `find_protected_tail_start_index`
- `drop_thinking_blocks`
- `apply_budget_policy`
- `estimate_protected_token_budget`

**Charles 实现**（budget_policy.py + context.py::_project_future_usage）：
- `BudgetPolicyIntent` 枚举
- `ProjectionPolicy` 数据类

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 2.12.1 | BudgetPolicyIntent 枚举 | types.ts | budget_policy.py | 3 值完整性 |
| 2.12.2 | ProjectionPolicy 字段 | types.ts | budget_policy.py | 4 字段完整性 |
| 2.12.3 | resolve_projection_policy 逻辑 | project.ts | budget_policy.py | 按 intent 解析 |
| 2.12.4 | find_latest_typed_user_message_index | project.ts | budget_policy.py | 找最后一条用户输入 |
| 2.12.5 | find_protected_tail_start_index | project.ts | budget_policy.py | live tail 起始 |
| 2.12.6 | drop_thinking_blocks | project.ts | budget_policy.py | 移除 ReasoningPart |
| 2.12.7 | apply_budget_policy | project.ts | budget_policy.py | 块级策略应用 |
| 2.12.8 | estimate_protected_token_budget | project.ts | budget_policy.py | token 估算 |
| 2.12.9 | _project_future_usage 公式 | project.ts | context.py | current + tools + avg_tool_result |
| 2.12.10 | projection_ratio 默认值 | index.ts | context.py | 0.8 |
| 2.12.11 | tool_result_history_max | index.ts | context.py | 历史样本数 |
| 2.12.12 | 提前压缩触发条件 | index.ts | context.py | projected >= trigger |
| 2.12.13 | compaction_reason 标记 | index.ts | context.py | budget_projection vs threshold |
| 2.12.14 | 无历史样本时行为 | project.ts | context.py | avg=0 保守 |

**验证方法**：构造不同 intent 场景，对比策略应用

---

## 五、Phase 3：工具系统实现对比

**对标视角**：V2 实现结构
**目标**：对比 Charles `agent/tools/` 与 Cline `sdk/packages/core/src/extensions/tools/` 的实现细节
**Cline 源码**：`sdk/packages/shared/src/tools/create.ts` + `sdk/packages/core/src/extensions/tools/{runtime,definitions,schemas,presets}.ts` + `sdk/packages/core/src/extensions/tools/executors/`
**Charles 源码**：`agent/tools/base.py` + `agent/tools/__init__.py` + `agent/tools/*.py`（20 个工具文件）+ `agent/approval.py`
**小阶段数**：24 个（P3.1-P3.24），覆盖全部 20 个工具文件

### P3.1 工具基础设施对比（createTool 工厂 vs BaseTool 类）

**Cline 实现**：
- `createTool()` 工厂函数（create.ts），返回 `AgentTool` 对象
- 工具实现是函数式 + 闭包，非 OOP
- 工具字段：`name`/`description`/`inputSchema`/`execute`/`lifecycle`/`timeoutMs`/`retryable`/`maxRetries`

**Charles 实现**：
- `BaseTool` 抽象基类（base.py），子类继承实现
- 工具实现是 OOP 风格
- 工具字段：`name`/`description`/`input_schema`/`timeout_ms`/`retryable`/`max_retries`/`completes_run`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.1.1 | 工具实现范式 | create.ts 工厂 | base.py 类继承 | 函数式 vs OOP |
| 3.1.2 | 工具字段命名 | camelCase | snake_case | 命名风格 |
| 3.1.3 | inputSchema 类型 | zod schema | JSON Schema dict | 类型系统不同 |
| 3.1.4 | inputSchema 运行时校验 | zod 转换 + validateWithZod | jsonschema.validate | 校验库不同 |
| 3.1.5 | 工具描述动态生成 | Object.defineProperty getter | _build_description() 方法 | 实现方式 |
| 3.1.6 | 工具实例化时机 | 工厂调用时 | 装配时 new | 实例化点 |
| 3.1.7 | 工具状态隔离 | 闭包隔离 | 实例字段隔离 | 隔离机制 |
| 3.1.8 | 工具复用 | 每次调用工厂 | 单例复用 | 实例复用策略 |

**验证方法**：对比两边工具定义代码风格，检查字段映射

### P3.2 工具执行接口对比（execute 方法签名）

**Cline 实现**：
- `execute(input, context): AsyncIterator<AgentToolResult>` — 异步迭代器
- 支持 yield 多个 result（进度更新）
- `AgentToolResult`: `{ output: string \| object, is_error: boolean, metadata?: object }`

**Charles 实现**：
- `execute(input, context) -> AgentToolResult` — 协程返回单值
- 不支持进度更新
- `AgentToolResult`: dataclass `{ output, is_error, metadata }`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.2.1 | execute 返回类型 | AsyncIterator | coroutine | **Charles 不支持流式工具** |
| 3.2.2 | 进度更新支持 | yield 中间 result | 无 | Charles 缺失 |
| 3.2.3 | 长任务进度反馈 | yield 进度 | 仅最终结果 | UX 差异 |
| 3.2.4 | AgentToolResult.output 类型 | string \| object | Any | 类型约束 |
| 3.2.5 | AgentToolResult.is_error | boolean | bool | 等价 |
| 3.2.6 | AgentToolResult.metadata | optional | optional | 等价 |
| 3.2.7 | 工具取消支持 | AbortSignal | abort_signal | 已对齐 |
| 3.2.8 | context 字段完整性 | AgentToolContext | AgentToolContext | 见 P3.4 |

**验证方法**：对比 execute 方法签名，检查是否支持 yield 中间结果

### P3.3 ToolLifecycle 与 completes_run 对比

**Cline 实现**：
- `ToolLifecycle`: `{ completesRun: boolean, blocking?: boolean }`
- `completesRun` = true 时，工具成功执行后结束 run
- `blocking` = true 时，UI 显示阻塞

**Charles 实现**：
- `ToolLifecycle`: dataclass `{ completes_run: bool }`
- 无 `blocking` 字段

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.3.1 | completes_run 字段 | 是 | 是 | 已对齐 |
| 3.3.2 | completes_run 触发条件 | !is_error | !is_error | 已对齐 |
| 3.3.3 | completes_run 后 status | completed | completed | 已对齐 |
| 3.3.4 | blocking 字段 | 是 | 无 | Charles 缺失 |
| 3.3.5 | blocking 用途 | UI 阻塞提示 | N/A | Charles 单机无需 |
| 3.3.6 | lifecycle 默认值 | completesRun=false | completes_run=False | 等价 |

**验证方法**：对比 ToolLifecycle 字段，评估 blocking 是否必要

### P3.4 AgentToolContext 字段对比

**Cline 实现**（agent.ts L170-186）：
- `session_id` / `agent_id` / `run_id` / `iteration` / `signal` / `snapshot` / `emit_update` / `metadata`

**Charles 实现**（types.py）：
- `session_id` / `agent_id` / `run_id` / `iteration` / `signal` / `snapshot` / `metadata`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.4.1 | session_id | 是 | 是 | 已对齐 |
| 3.4.2 | agent_id | 是 | 是 | 已对齐 |
| 3.4.3 | run_id | 是 | 是 | 已对齐 |
| 3.4.4 | iteration | 是 | 是 | 已对齐 |
| 3.4.5 | signal | AbortSignal | asyncio.Event | 类型不同但语义等价 |
| 3.4.6 | snapshot | AgentRuntimeStateSnapshot | AgentRuntimeStateSnapshot | 已对齐 |
| 3.4.7 | emit_update | 是 | 无 | Charles 缺失（用 emit 事件替代） |
| 3.4.8 | metadata | 是 | 是 | 已对齐（Stage 10.5） |
| 3.4.9 | abort_signal 透传 | context.signal | context.signal | 已对齐 |

**验证方法**：对比 AgentToolContext 字段，检查 emit_update 用途

### P3.5 工具超时与重试对比（timeoutMs/retryable/maxRetries）

**Cline 实现**：
- per-tool `timeoutMs`（默认 60000）
- per-tool `retryable`（默认 false）
- per-tool `maxRetries`（默认 3）
- `withTimeout` 包裹 execute

**Charles 实现**：
- per-tool `timeout_ms`（部分工具硬编码）
- per-tool `retryable`（部分工具 False）
- 无 `max_retries` 字段
- 仅 `run_commands` 有超时

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.5.1 | timeout_ms 默认值 | 60000 | 工具特定 | 默认值不同 |
| 3.5.2 | timeout_ms 可配置 | per-tool | per-tool | 已对齐 |
| 3.5.3 | withTimeout 包裹 | 全工具 | 仅 run_commands | Charles 不全 |
| 3.5.4 | retryable 字段 | 全工具 | 部分工具 | Charles 不全 |
| 3.5.5 | max_retries 字段 | 是 | 无 | Charles 缺失 |
| 3.5.6 | 重试错误判定 | 可重试错误类型 | 无 | Charles 缺失 |
| 3.5.7 | 重试间隔 | 指数退避 | 无 | Charles 缺失 |
| 3.5.8 | skills 工具超时 | skillsTimeoutMs=15000 | timeout_ms=15000 | 已对齐 |

**验证方法**：对比每个工具的 timeout_ms/retryable 字段

### P3.6 Schema 校验对比（zod vs jsonschema）

**Cline 实现**：
- 工具 inputSchema 用 zod 定义
- `zodToJsonSchema()` 转换为 JSON Schema 发给 LLM
- `validateWithZod()` 在 execute 入口校验
- 校验失败返回结构化错误

**Charles 实现**：
- 工具 input_schema 用 JSON Schema dict 定义
- `jsonschema.validate()` 在 `_prepare_tool_execution` 校验
- 校验失败返回错误 result

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.6.1 | schema 定义方式 | zod | JSON Schema dict | 类型系统不同 |
| 3.6.2 | schema 转 LLM 格式 | zodToJsonSchema | 原生 JSON Schema | Charles 无需转换 |
| 3.6.3 | 运行时校验调用 | execute 入口 | _prepare_tool_execution | 调用位置不同 |
| 3.6.4 | 校验失败错误格式 | zod 错误对象 | jsonschema 错误对象 | 错误信息结构 |
| 3.6.5 | 校验失败反馈 LLM | 错误 result | 错误 result | 已对齐 |
| 3.6.6 | 嵌套对象校验 | zod 递归 | jsonschema 递归 | 等价 |
| 3.6.7 | 枚举值校验 | zod enum | jsonschema enum | 等价 |
| 3.6.8 | 必填字段校验 | zod required | jsonschema required | 等价 |
| 3.6.9 | 类型 coercion | zod 支持 | jsonschema 不支持 | Charles 弱 |

**验证方法**：构造非法参数，对比两边错误反馈

### P3.7 ToolRegistry 对比

**Cline 实现**：
- `ToolRuntime` 类管理工具注册
- 工具按 name 注册，支持别名
- `get_definitions()` 返回所有工具的 LLM schema

**Charles 实现**：
- `ToolRegistry` 类管理工具注册
- 工具按 name 注册，无别名
- `get_definitions()` 返回所有工具 schema

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.7.1 | Registry 数据结构 | Map | dict | 等价 |
| 3.7.2 | 工具注册时机 | 装配时 | 装配时 | 已对齐 |
| 3.7.3 | 别名支持 | 是 | 否 | Charles 缺失 |
| 3.7.4 | 动态注册 | 支持 | 支持 | 已对齐 |
| 3.7.5 | 工具启用/禁用 | enabled 字段 | enabled 字段 | 已对齐 |
| 3.7.6 | get_definitions 过滤 | 按 enabled | 按 enabled | 已对齐 |
| 3.7.7 | 工具覆盖 | 后注册覆盖 | 后注册覆盖 | 已对齐 |
| 3.7.8 | MCP 工具注入 | 动态注册 | 动态注册 | 已对齐 |

**验证方法**：对比 ToolRegistry 接口

### P3.8 工具审批机制对比（toolPolicies + before_approval）

**Cline 实现**：
- `toolPolicies` config（per-tool enabled/autoApprove）
- `requestToolApproval` config 回调
- `tool-approval.ts` 审批流程
- 审批结果持久化

**Charles 实现**：
- `tool_policies` dict（per-tool enabled/auto_approve）
- `before_approval` hook
- `approval.py` 审批流程
- `approval_memory.json` 持久化

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.8.1 | policies 配置格式 | config 文件 | tool_policies dict | 格式不同 |
| 3.8.2 | enabled 字段 | 是 | 是 | 已对齐 |
| 3.8.3 | autoApprove 字段 | 是 | auto_approve | 已对齐 |
| 3.8.4 | 审批触发机制 | requestToolApproval 回调 | before_approval hook | 形式不同但等价 |
| 3.8.5 | 审批结果持久化 | 是 | approval_memory.json | Charles 额外增强 |
| 3.8.6 | 跨会话审批记忆 | 是 | 是 | 已对齐（Stage 9.6） |
| 3.8.7 | 审批 UI | VSCode 原生 | SSE + 前端弹窗 | 形式不同但等价 |
| 3.8.8 | 审批超时 | 是 | 是 | 已对齐 |
| 3.8.9 | 审批 deny 后行为 | skip 工具 | skip 工具 | 已对齐 |
| 3.8.10 | MCP 工具审批 | policies.ts | registry.py + mcp.py | Q8 部分实现 |

**验证方法**：配置 tool_policies，测试审批流程

### P3.9 内置工具清单对比

**Cline 内置工具**（definitions.ts）：
- `read_files` / `run_commands` / `editor` / `apply_patch` / `list_files` / `search_codebase` / `fetch_web_content` / `ask_followup_question` / `submit_and_exit` / `attempt_completion` / `todo_write` / `plan_mode` / `skills` / `use_mcp_tool` / `access_mcp_resource` / `spawn_agent`

**Charles 内置工具**：
- `read_files` / `run_commands` / `apply_patch` / `file_write` / `list_files` / `search_codebase` / `fetch_web_content` / `ask_followup_question` / `submit_and_exit` / `attempt_completion` / `todo_write` / `plan_mode` / `skills` / `use_mcp_tool`

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 3.9.1 | read_files | 有 | 有 | 已对齐 |
| 3.9.2 | run_commands | 有 | 有 | 已对齐 |
| 3.9.3 | editor（行级编辑） | 有 | 无 | Charles 用 apply_patch 替代 |
| 3.9.4 | apply_patch | 有 | 有 | 已对齐 |
| 3.9.5 | file_write | 无 | 有 | Charles 额外 |
| 3.9.6 | list_files | 有 | 有 | 已对齐 |
| 3.9.7 | search_codebase | 有 | 有 | 已对齐 |
| 3.9.8 | fetch_web_content | 有 | 有 | 已对齐 |
| 3.9.9 | ask_followup_question | 有 | 有 | 已对齐 |
| 3.9.10 | submit_and_exit | 有 | 有 | 已对齐 |
| 3.9.11 | attempt_completion | 有 | 有 | 已对齐 |
| 3.9.12 | todo_write | 有 | 有 | 已对齐 |
| 3.9.13 | plan_mode | 有 | 有 | 已对齐 |
| 3.9.14 | skills | 有 | 有 | 已对齐 |
| 3.9.15 | use_mcp_tool | 有 | 有 | 已对齐 |
| 3.9.16 | access_mcp_resource | 有 | 无 | Charles 缺失 |
| 3.9.17 | spawn_agent | 有 | 无 | Charles 不实施（Phase 27 移除） |

**验证方法**：对比两边工具清单

### P3.10 read_files 工具实现对比

**Cline 实现**（executors/read-files.ts）：
- 支持 line range
- 支持 maxLines 截断
- 返回行号格式 `cat -n`
- cat -n 格式输出

**Charles 实现**（read_files.py）：
- 支持 line range
- 支持 max_lines 截断
- 返回行号格式
- 输出格式 `LINE_NUMBER→LINE_CONTENT`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.10.1 | 行号格式 | `  123→content` | `123→content` | 对齐方式不同 |
| 3.10.2 | line range 参数 | start_line/end_line | offset/limit | 参数名不同 |
| 3.10.3 | maxLines 截断 | MAX_READ_LINES=2000 | MAX_READ_LINES=2000 | 已对齐 |
| 3.10.4 | maxOutputChars | MAX_READ_OUTPUT_CHARS=48000 | 30000 | 阈值不同 |
| 3.10.5 | 二进制文件检测 | 是 | 是 | 已对齐 |
| 3.10.6 | 大文件提示 | 是 | 是 | 已对齐 |
| 3.10.7 | 多文件读取 | 支持 | 支持 | 已对齐 |
| 3.10.8 | 相对路径解析 | cwd | cwd | 已对齐 |
| 3.10.9 | 文件不存在错误 | 错误 result | 错误 result | 已对齐 |
| 3.10.10 | 截断提示文本 | "... truncated ..." | "... 已截断 ..." | 文案不同 |

**验证方法**：读取相同文件，对比输出格式

### P3.11 run_commands 工具实现对比

**Cline 实现**（executors/run-commands.ts）：
- 支持 cwd / env / timeout
- 子进程 spawn
- AbortSignal 触发 kill
- 输出截断 MAX_COMMAND_OUTPUT_CHARS=48000
- stdout/stderr 分离

**Charles 实现**（run_commands.py）：
- 支持 cwd / env / timeout
- asyncio.create_subprocess_exec
- abort_signal 触发 kill（_wait_process_with_abort）
- 输出截断 MAX_COMMAND_OUTPUT_CHARS=30000
- stdout/stderr 合并

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.11.1 | 子进程创建 | child_process.spawn | asyncio.create_subprocess_exec | 实现等价 |
| 3.11.2 | cwd 参数 | 是 | 是 | 已对齐 |
| 3.11.3 | env 参数 | 是 | 是 | 已对齐 |
| 3.11.4 | timeout 参数 | 是 | 是 | 已对齐 |
| 3.11.5 | abort kill 子进程 | AbortSignal | _wait_process_with_abort | 已对齐（Stage 30.3） |
| 3.11.6 | 输出截断阈值 | 48000 | 30000 | 阈值不同 |
| 3.11.7 | stdout/stderr 分离 | 是 | 合并 | Charles 简化 |
| 3.11.8 | 退出码 | 是 | 是 | 已对齐 |
| 3.11.9 | 超时行为 | kill + 错误 | kill + 错误 | 已对齐 |
| 3.11.10 | 命令注入防护 | shell-escape | shlex.quote | 实现不同但等价 |
| 3.11.11 | 优雅 kill | SIGTERM → SIGKILL | terminate → kill | 已对齐（Stage 12.1） |
| 3.11.12 | Windows 兼容 | 是 | 是 | 已对齐 |

**验证方法**：运行相同命令，对比输出格式和行为

### P3.12 apply_patch 工具实现对比

**Cline 实现**（executors/apply-patch.ts）：
- 标准 unified diff 格式
- 模糊匹配
- Unicode 支持
- PatchApplyError

**Charles 实现**（apply_patch.py）：
- 标准 unified diff 格式
- 模糊匹配（Stage 12.2）
- Unicode 支持（Stage 12.2）
- PatchApplyError（Stage 12.2）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.12.1 | diff 格式 | unified diff | unified diff | 已对齐 |
| 3.12.2 | 模糊匹配 | 是 | 是 | 已对齐（Stage 12.2） |
| 3.12.3 | Unicode 支持 | 是 | 是 | 已对齐（Stage 12.2） |
| 3.12.4 | PatchApplyError | 是 | 是 | 已对齐（Stage 12.2） |
| 3.12.5 | 备份机制 | 是 | 是 | 已对齐 |
| 3.12.6 | 多 hunk 支持 | 是 | 是 | 已对齐 |
| 3.12.7 | 空文件创建 | 是 | 是 | 已对齐 |
| 3.12.8 | 文件删除 | 是 | 是 | 已对齐 |
| 3.12.9 | 行尾符处理 | 是 | 是 | 已对齐 |

**验证方法**：应用相同 patch，对比结果

### P3.13 search_codebase 工具实现对比

**Cline 实现**（executors/search-codebase.ts）：
- ripgrep 后端
- 支持 regex / glob / type 过滤
- 输出截断 MAX_SEARCH_OUTPUT_CHARS=48000

**Charles 实现**（search_codebase.py）：
- ripgrep 后端（Grep 工具）
- 支持 regex / glob / type 过滤
- 输出截断 MAX_SEARCH_MATCHES_PER_QUERY=50

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.13.1 | 搜索后端 | ripgrep | ripgrep | 已对齐 |
| 3.13.2 | regex 支持 | 是 | 是 | 已对齐 |
| 3.13.3 | glob 过滤 | 是 | 是 | 已对齐 |
| 3.13.4 | type 过滤 | 是 | 是 | 已对齐 |
| 3.13.5 | 输出截断单位 | 字符数 | 匹配数 | 单位不同 |
| 3.13.6 | 输出截断阈值 | 48000 chars | 50 matches | 阈值不同 |
| 3.13.7 | 上下文行 | -A/-B/-C | -A/-B/-C | 已对齐 |
| 3.13.8 | 多文件输出 | 是 | 是 | 已对齐 |
| 3.13.9 | 行号显示 | 是 | 是 | 已对齐 |
| 3.13.10 | 大仓库优化 | 是 | 是 | 已对齐 |

**验证方法**：搜索相同 pattern，对比输出

### P3.14 list_files 工具实现对比

**Cline 实现**（executors/list-files.ts）：
- 递归/非递归
- 忽略 .gitignore
- 输出截断

**Charles 实现**（list_files.py）：
- 递归/非递归
- 忽略 .gitignore
- 输出截断

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.14.1 | 递归参数 | recursive | recursive | 已对齐 |
| 3.14.2 | .gitignore 忽略 | 是 | 是 | 已对齐 |
| 3.14.3 | 输出格式 | 树形 | 列表 | 格式不同 |
| 3.14.4 | 截断阈值 | 是 | 是 | 已对齐 |
| 3.14.5 | 隐藏文件 | 是 | 是 | 已对齐 |
| 3.14.6 | 排序 | 字母序 | 修改时间 | 排序不同 |

**验证方法**：列出相同目录，对比输出

### P3.15 todo_write 工具实现对比

**Cline 实现**（definitions.ts + executors/）：
- TodoWrite 工具
- 支持 pending/in_progress/completed 状态
- 优先级 high/medium/low

**Charles 实现**（todo.py / TodoWrite 工具）：
- 同样设计

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.15.1 | 状态枚举 | pending/in_progress/completed | pending/in_progress/completed | 已对齐 |
| 3.15.2 | 优先级 | high/medium/low | high/medium/low | 已对齐 |
| 3.15.3 | 单 in_progress 约束 | 是 | 是 | 已对齐 |
| 3.15.4 | merge 参数 | 是 | 是 | 已对齐 |
| 3.15.5 | summary 字段 | 是 | 是 | 已对齐 |
| 3.15.6 | 持久化 | 是 | 是 | 已对齐 |

**验证方法**：对比 todo_write 接口

### P3.16 plan_mode 工具实现对比

**Cline 实现**（definitions.ts）：
- plan_mode 工具切换 plan/act 模式
- 切换后重新构建 system prompt

**Charles 实现**（plan_mode.py）：
- plan_mode 工具
- 切换后重新构建 system prompt

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.16.1 | 模式枚举 | plan/act | plan/act | 已对齐 |
| 3.16.2 | yolo 模式 | 是 | 描述为"与 act 等价" | L8 差距 |
| 3.16.3 | 切换后 prompt 重建 | 是 | 是 | 已对齐 |
| 3.16.4 | PLAN_MODE_PROMPT 内容 | 模式行为契约 | 模式行为契约 | 已对齐（Stage P4） |
| 3.16.5 | run_commands 只读范围 | 列举具体命令 | 宽泛描述 | L6 差距 |
| 3.16.6 | tool_policies 硬禁用 | 是 | 是 | 已对齐 |
| 3.16.7 | mode_notice 机制 | 是 | 无 | M1 差距 |
| 3.16.8 | MODE_TAG_INSTRUCTIONS | 不列举工具名 | 列举工具名 | L7 差距 |

**验证方法**：切换 plan/act 模式，对比 system prompt 变化

### P3.17 attempt_completion / submit_and_exit 对比

**Cline 实现**：
- `attempt_completion` — 完成任务，返回最终结果，completes_run
- `submit_and_exit` — yolo 模式专用，提交并退出

**Charles 实现**：
- `attempt_completion` — 完成任务
- `submit_and_exit` — 同样存在

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.17.1 | attempt_completion 字段 | result + image | result + image | 已对齐 |
| 3.17.2 | attempt_completion completes_run | 是 | 是 | 已对齐 |
| 3.17.3 | submit_and_exit 字段 | result | result | 已对齐 |
| 3.17.4 | submit_and_exit completes_run | 是 | 是 | 已对齐 |
| 3.17.5 | yolo 模式专用 | 是 | 描述为"与 act 等价" | L8 差距 |

**验证方法**：对比两个工具的 schema

### P3.18 工具输出截断常量对比

**Cline 实现**（output-limits.ts）：
- `MAX_COMMAND_OUTPUT_CHARS = 48000`
- `MAX_READ_LINES = 2000`
- `MAX_READ_OUTPUT_CHARS = 48000`
- `MAX_SEARCH_OUTPUT_CHARS = 48000`
- `MAX_TOOL_RESULT_CHARS = 48000`

**Charles 实现**（constants.py）：
- `MAX_COMMAND_OUTPUT_CHARS = 30000`
- `MAX_READ_LINES = 2000`
- `MAX_READ_OUTPUT_CHARS = 30000`
- `MAX_SEARCH_OUTPUT_CHARS = 30000`（实际用 50 matches）
- `MAX_TOOL_RESULT_CHARS = 16000`

| # | 对比项 | Cline 值 | Charles 值 | 关键差异 |
|---|--------|---------|-----------|---------|
| 3.18.1 | MAX_COMMAND_OUTPUT_CHARS | 48000 | 30000 | 阈值不同 |
| 3.18.2 | MAX_READ_LINES | 2000 | 2000 | 已对齐 |
| 3.18.3 | MAX_READ_OUTPUT_CHARS | 48000 | 30000 | 阈值不同 |
| 3.18.4 | MAX_SEARCH_OUTPUT_CHARS | 48000 chars | 50 matches | 单位+阈值不同 |
| 3.18.5 | MAX_TOOL_RESULT_CHARS | 48000 | 16000 | 阈值不同 |
| 3.18.6 | 统一管理 | output-limits.ts | constants.py | 已对齐（Stage 31.5） |

**验证方法**：对比常量值，评估是否需要对齐

### P3.19 MCP 工具对比（use_mcp_tool / access_mcp_resource）

**Cline 实现**：
- `use_mcp_tool` — 调用 MCP 服务器工具
- `access_mcp_resource` — 访问 MCP 资源
- per-tool policies（policies.ts）
- OAuth 认证
- name-transform 命名空间

**Charles 实现**：
- `use_mcp_tool` — 调用 MCP 服务器工具
- 无 `access_mcp_resource`
- per-tool policies（registry.py）
- 无 OAuth
- name-transform hash 截断（Stage 32.3）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.19.1 | use_mcp_tool 工具 | 是 | 是 | 已对齐 |
| 3.19.2 | access_mcp_resource 工具 | 是 | 无 | Charles 缺失 |
| 3.19.3 | per-tool policies | policies.ts | registry.py | 已对齐 |
| 3.19.4 | auto_approve 消费 | tool-approval.ts | mcp.py（Q8 部分实现） | 部分对齐 |
| 3.19.5 | OAuth 认证 | oauth.ts | 无 | Charles 不实施 |
| 3.19.6 | name-transform | 是 | hash 截断（Stage 32.3） | 已对齐 |
| 3.19.7 | plugin-server-registration | 是 | 无 | Charles 不实施 |
| 3.19.8 | config-loader | .cline/mcp_settings.json | mcp_servers.yaml | 格式不同 |
| 3.19.9 | MCP 工具动态注册 | 是 | 是 | 已对齐 |
| 3.19.10 | MCP 服务器启动 | 是 | 是 | 已对齐 |

**验证方法**：配置 MCP 服务器，测试工具调用

### P3.20 model-tool-routing 工具路由对比

**Cline 实现**（model-tool-routing.ts）：
- 按模型路由工具集
- 不同模型看到不同工具列表

**Charles 实现**（Stage 32.1）：
- 按模型路由工具集
- 13 个单元测试 + e2e

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.20.1 | 路由配置 | config | config | 已对齐 |
| 3.20.2 | 按模型过滤工具 | 是 | 是 | 已对齐（Stage 32.1） |
| 3.20.3 | 默认工具集 | 是 | 是 | 已对齐 |
| 3.20.4 | 云厂商 provider | Bedrock/Vertex | 无 | Charles 不实施 |

**验证方法**：配置不同模型，对比工具列表

### P3.21 web_tool（WebSearchTool）实现对比

**Cline 实现**（无独立 WebSearchTool，由 fetch_web_content + 模型自主搜索组成）：
- Cline 没有独立的"网络搜索"工具
- 网络信息获取通过 `fetch_web_content` 抓取 URL
- 或通过 MCP 服务器接入搜索能力

**Charles 实现**（web_tool.py）：
- `WebSearchTool` — 独立的网络搜索工具
- 输入 schema：query / num_results / source
- 搜索后端：AkShare / 其他
- 结果格式与截断
- 可能从 nanobot 迁移而来

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.21.1 | 工具存在性 | 无独立搜索工具 | 有 WebSearchTool | Charles 额外 |
| 3.21.2 | 输入 schema | N/A | query/num_results/source | Charles 量化特化 |
| 3.21.3 | 搜索后端 | N/A | AkShare 等 | Charles 量化特化 |
| 3.21.4 | 结果格式 | N/A | 结构化结果 | Charles 量化特化 |
| 3.21.5 | 结果截断 | N/A | 是 | Charles 量化特化 |
| 3.21.6 | 错误处理 | N/A | 是 | Charles 量化特化 |
| 3.21.7 | nanobot 风格残留 | N/A | 需检查 | 重点对比 |
| 3.21.8 | read_only 属性 | N/A | True | Charles 设置 |
| 3.21.9 | requires_approval | N/A | False | Charles 设置 |
| 3.21.10 | timeout_ms | N/A | 需检查 | Charles 设置 |

**验证方法**：对比 web_tool.py 实现风格是否残留 nanobot，评估是否应改为 fetch_web_content + MCP 搜索

### P3.22 fetch_web_content 实现对比

**Cline 实现**（executors/web-fetch.ts）：
- 抓取 URL 内容
- HTML 转 Markdown
- 输出截断
- 超时控制

**Charles 实现**（fetch_web_content.py）：
- 抓取 URL 内容
- HTML 转 Markdown
- 输出截断
- 超时控制

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.22.1 | URL 抓取 | web-fetch.ts | fetch_web_content.py | 已对齐 |
| 3.22.2 | HTML 转 Markdown | 是 | 是 | 已对齐 |
| 3.22.3 | 输出截断 | 是 | 是 | 已对齐 |
| 3.22.4 | 超时控制 | 是 | 是 | 已对齐 |
| 3.22.5 | 重定向跟随 | 是 | 需检查 | 待验证 |
| 3.22.6 | 认证 URL 检测 | 是 | 需检查 | 待验证 |
| 3.22.7 | prompt 提取 | 是 | 需检查 | 待验证 |
| 3.22.8 | nanobot 风格残留 | N/A | 需检查 | 重点对比 |
| 3.22.9 | read_only 属性 | 是 | True | 已对齐 |
| 3.22.10 | requires_approval | 否 | False | 已对齐 |

**验证方法**：抓取相同 URL，对比输出格式和行为

### P3.23 file_write / editor 实现对比

**Cline 实现**：
- `FileWriteTool`（executors/file-write.ts）— 全文件写入
- `EditorTool`（executors/editor.ts）— 行级编辑（old_string/new_string 替换）

**Charles 实现**：
- `FileWriteTool`（file_tools.py）— 全文件写入
- `EditorTool`（editor.py）— 行级编辑

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.23.1 | FileWriteTool 输入 schema | path + content | path + content | 已对齐 |
| 3.23.2 | FileWriteTool 写入模式 | overwrite | overwrite | 已对齐 |
| 3.23.3 | FileWriteTool 目录创建 | 是 | 需检查 | 待验证 |
| 3.23.4 | EditorTool 编辑方式 | old_string/new_string | old_string/new_string | 已对齐 |
| 3.23.5 | EditorTool 多处替换 | replace_all | replace_all | 已对齐 |
| 3.23.6 | EditorTool 唯一性校验 | 是 | 需检查 | 待验证 |
| 3.23.7 | EditorTool 备份机制 | 是 | 需检查 | 待验证 |
| 3.23.8 | requires_approval | True | True | 已对齐 |
| 3.23.9 | nanobot 风格残留 | N/A | 需检查 | 重点对比 |
| 3.23.10 | file_tools.py 其他工具 | N/A | 需检查是否有 nanobot 残留 | 重点对比 |

**验证方法**：写入/编辑相同文件，对比行为

### P3.24 ask_question / exec_tool 实现对比

**Cline 实现**：
- `ask_followup_question` — 向用户提问，completes_run
- 无 ExecTool 等价物（run_commands 替代）

**Charles 实现**：
- `AskQuestionTool`（ask_question.py）— 向用户提问
- `ExecTool`（exec_tool.py）— 已废弃，保留导入兼容

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 3.24.1 | ask_question 输入 schema | question | question | 已对齐 |
| 3.24.2 | ask_question completes_run | 是 | 需检查 | 待验证 |
| 3.24.3 | ask_question UI 交互 | VSCode 弹窗 | SSE + 前端 | 形式不同但等价 |
| 3.24.4 | ExecTool 状态 | N/A | 已废弃 | Charles 遗留 |
| 3.24.5 | ExecTool 是否注册 | N/A | 不注册（保留导入） | 已对齐 |
| 3.24.6 | ExecTool 代码清理 | N/A | 需检查是否应删除 | 待评估 |
| 3.24.7 | nanobot 风格残留 | N/A | 需检查 | 重点对比 |

**验证方法**：对比 ask_question 行为，评估 ExecTool 清理必要性

---

## 六、Phase 4：技能系统与 Skill Prompt 对比

**对标视角**：V2 实现结构 + V6 Skill Prompt
**目标**：对比 Charles `agent/skills/` 与 Cline `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` + `sdk/packages/core/src/extensions/tools/executors/skills.ts` 的实现细节，同时对比 SKILL.md 的 Prompt 组件结构与形式风格
**Cline 源码**：`user-instruction-plugin.ts` + `skill-frontmatter-toggle.ts` + `user-instruction-config-loader.ts` + `skills.ts`
**Charles 源码**：`agent/skills/loader.py` + `agent/skills/registry.py` + `agent/skills/skill_tool.py` + `agent_config/skills/*/SKILL.md`（8 个）+ `agent_config/skills/*/scripts/*.py`（19 个脚本）
**小阶段数**：20 个（P4.1-P4.20），覆盖技能系统实现 + SKILL.md Prompt + 脚本实现风格 + nanobot 残留专项检查

### P4.1 技能工具（skills tool）实现对比

**Cline 实现**（user-instruction-plugin.ts + skills.ts）：
- 工具名 `skills`
- XML 返回格式 `<skill name="..."></skill>`
- 不创建子 agent，主上下文指令注入
- description 动态含技能列表（Object.defineProperty getter）
- `runningSkills: Set<string>` 并发去重
- `withTimeout(15000)` 超时
- `allowedSkillNames` 白名单
- zod `SkillsInputSchema`

**Charles 实现**（skill_tool.py）：
- 工具名 `skills`
- XML 返回格式 `<skill name="..."></skill>`
- 不创建子 agent，主上下文指令注入
- description 动态含技能列表（_build_description()）
- `_running_skills: set[str]` 并发去重（Stage 31.1）
- `asyncio.wait_for(timeout=15.0)` 超时（Stage 31.2）
- `allowed_skill_names` 白名单（Stage 31.3）
- JSON Schema dict

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.1.1 | 工具名 | skills | skills | 已对齐 |
| 4.1.2 | XML 返回格式 | `<skill name="...">` | `<skill name="...">` | 已对齐 |
| 4.1.3 | 子 agent 创建 | 不创建 | 不创建 | 已对齐 |
| 4.1.4 | description 动态生成 | Object.defineProperty | _build_description() | 实现不同但等价 |
| 4.1.5 | runningSkills 去重 | Set<string> | set[str] | 已对齐（Stage 31.1） |
| 4.1.6 | finally 释放 | try/finally discard | try/finally discard | 已对齐 |
| 4.1.7 | withTimeout 15s | withTimeout(15000) | asyncio.wait_for(15.0) | 已对齐（Stage 31.2） |
| 4.1.8 | allowedSkillNames 白名单 | toAllowedSkillSet | allowed_skill_names | 已对齐（Stage 31.3） |
| 4.1.9 | skillsTimeoutMs 可配置 | config.skillsTimeoutMs ?? 15000 | 硬编码 15000 | S2 差距 |
| 4.1.10 | 白名单匹配形式 | 4 形式 | 2 形式 | S1 差距 |
| 4.1.11 | InputSchema | zod | JSON Schema dict | 类型系统不同 |
| 4.1.12 | frontmatter toggle | skill-frontmatter-toggle.ts | loader.py（Stage 31.4） | 已对齐 |

**验证方法**：对比 skills 工具实现

### P4.2 技能加载器对比（SkillLoader）

**Cline 实现**（user-instruction-config-loader.ts）：
- 扫描 `.cline/skills/` 目录
- 解析 SKILL.md frontmatter
- 多源加载（.cline/skills + 全局 skills）
- SkillMetadata 数据结构

**Charles 实现**（loader.py）：
- 扫描 `agent_config/skills/` 目录
- 解析 SKILL.md frontmatter（Stage 31.4）
- 多源加载 load_skills_multi_source（Stage 13.4）
- SkillMetadata 数据结构

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.2.1 | 扫描目录 | .cline/skills/ | agent_config/skills/ | 路径不同 |
| 4.2.2 | frontmatter 解析 | YAML frontmatter | parse_yaml_frontmatter | 已对齐（Stage 31.4） |
| 4.2.3 | 多源加载 | 是 | 是 | 已对齐（Stage 13.4） |
| 4.2.4 | 全局 skills 目录 | ~/.cline/skills/ | 无 | Charles 缺失 |
| 4.2.5 | SkillMetadata 字段 | name/description/disabled/always | name/description/disabled/always/when_to_use | Charles 额外（when_to_use） |
| 4.2.6 | disabled 字段 | 是 | 是 | 已对齐（Stage 31.4） |
| 4.2.7 | always 字段 | 是 | 是 | 已对齐 |
| 4.2.8 | 文件监听 | watcher | 无 | Charles 缺失 |
| 4.2.9 | 热重载 | 是 | 无 | Charles 缺失 |
| 4.2.10 | SKILL.md 路径 | {skill_name}/SKILL.md | {skill_name}/SKILL.md | 已对齐 |

**验证方法**：对比加载器实现，检查热重载

### P4.3 技能注册表对比（SkillRegistry）

**Cline 实现**：
- `SkillRegistry` 管理 SkillMetadata
- `build_summary()` 生成技能概览
- `isSkillAllowed()` 白名单检查（4 形式）

**Charles 实现**（registry.py）：
- `SkillRegistry` 管理 SkillMetadata
- `build_summary()` 生成技能概览（3 列表格）
- `is_skill_allowed()` 白名单检查（2 形式）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.3.1 | Registry 数据结构 | Map | dict | 等价 |
| 4.3.2 | build_summary 输出 | 表格 | 3 列表格 | Charles 额外 when_to_use |
| 4.3.3 | 白名单检查形式 | 4 形式 | 2 形式 | S1 差距 |
| 4.3.4 | 禁用技能过滤 | 是 | 是 | 已对齐（Stage 31.4） |
| 4.3.5 | always 技能标记 | 是 | 是 | 已对齐 |
| 4.3.6 | get_skill_metadata | 是 | 是 | 已对齐 |
| 4.3.7 | 技能覆盖 | 后注册覆盖 | 后注册覆盖 | 已对齐 |

**验证方法**：对比 registry 实现

### P4.4 渐进式技能加载对比（3 级）

**Cline 实现**（docs/customization/skills.mdx）：
- Level 1 - Metadata（启动时）：name + description，~100 tokens/技能
- Level 2 - Instructions（触发时）：SKILL.md 正文，<5k tokens
- Level 3 - Resources（按需）：scripts / docs / templates

**Charles 实现**：
- Level 1 - Metadata（启动时）：name + description + when_to_use，~100 tokens/技能
- Level 2 - Instructions（触发时）：SKILL.md 正文
- Level 3 - Resources（按需）：scripts / docs / templates

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.4.1 | Level 1 Metadata | name + description | name + description + when_to_use | Charles 额外 |
| 4.4.2 | Level 1 token 预算 | ~100 tokens | ~100 tokens | 已对齐 |
| 4.4.3 | Level 2 Instructions | SKILL.md 正文 | SKILL.md 正文 | 已对齐 |
| 4.4.4 | Level 2 token 预算 | <5k tokens | <5k tokens | 已对齐 |
| 4.4.5 | Level 3 Resources | scripts/docs/templates | scripts/docs/templates | 已对齐 |
| 4.4.6 | Level 3 加载方式 | read_files / run_commands | read_files / run_commands | 已对齐 |
| 4.4.7 | always 技能 Level 2 预加载 | 是 | 是 | 已对齐 |

**验证方法**：对比 3 级加载机制

### P4.5 SKILL.md frontmatter 对比

**Cline frontmatter 字段**：
- `name` / `description` / `disabled` / `always` / `globs` / `applyTo`

**Charles frontmatter 字段**：
- `name` / `description` / `disabled` / `always` / `when_to_use`

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 4.5.1 | name 字段 | 是 | 是 | 已对齐 |
| 4.5.2 | description 字段 | 是 | 是 | 已对齐 |
| 4.5.3 | disabled 字段 | 是 | 是 | 已对齐（Stage 31.4） |
| 4.5.4 | always 字段 | 是 | 是 | 已对齐 |
| 4.5.5 | globs 字段 | 是 | 无 | Charles 缺失 |
| 4.5.6 | applyTo 字段 | 是（plan/act） | 无 | Charles 缺失 |
| 4.5.7 | when_to_use 字段 | 无 | 是 | Charles 额外（Stage P5.2） |
| 4.5.8 | frontmatter 格式 | YAML | YAML | 已对齐 |
| 4.5.9 | frontmatter 分隔符 | `---` | `---` | 已对齐 |

**验证方法**：对比 frontmatter 字段

### P4.6 SKILL.md 主体结构对比

**Cline SKILL.md 结构**（参考 publish-cli/SKILL.md）：
- `## Workflow` + 编号步骤
- 内嵌 shell 命令块
- 脚本调用规则段
- 禁止行为段

**Charles SKILL.md 结构**（Stage P2 重构后）：
- `## 本技能核心能力` 段
- `## Workflow（必须按顺序执行）` 段
- `### Step N: <步骤名>` 子段
- `## 脚本调用规则` 段
- `## 禁止行为` 段

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 4.6.1 | Workflow 段 | 是 | 是 | 已对齐（Stage P2） |
| 4.6.2 | 编号步骤 | 是 | 是 | 已对齐 |
| 4.6.3 | 内嵌 shell 命令块 | 是 | 是 | 已对齐 |
| 4.6.4 | 脚本调用规则段 | 是 | 是 | 已对齐 |
| 4.6.5 | 禁止行为段 | 是 | 是 | 已对齐 |
| 4.6.6 | 核心能力段 | 无 | 是 | Charles 额外 |
| 4.6.7 | 何时执行字段 | 无 | 是 | Charles 额外 |
| 4.6.8 | 预期输出字段 | 无 | 是 | Charles 额外 |
| 4.6.9 | 失败处理字段 | 无 | 是 | Charles 额外 |
| 4.6.10 | 标题层级 | ## / ### | ## / ### | 已对齐 |

**验证方法**：对比 SKILL.md 模板

### P4.7 SKILL.md 形式风格对比（标签/措辞/语言）

**Cline 风格**：
- 英文为主
- 命令块用 ```bash
- 字段名英文

**Charles 风格**：
- 中文为主
- 命令块用 ```bash
- 字段名中文

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 4.7.1 | SKILL.md 语言 | 英文 | 中文 | 语言不同 |
| 4.7.2 | 命令块语言 | bash | bash | 已对齐 |
| 4.7.3 | 字段名语言 | 英文 | 中文 | 语言不同 |
| 4.7.4 | 标签格式 | Markdown | Markdown | 已对齐 |
| 4.7.5 | 示例命令 | 英文注释 | 中文注释 | 语言不同 |
| 4.7.6 | 错误提示语言 | 英文 | 中文 | 语言不同 |
| 4.7.7 | 步骤命名 | Step 1 / Step 2 | Step 1 / Step 2 | 已对齐 |
| 4.7.8 | Workflow 关键字 | Workflow | Workflow | 已对齐 |

**验证方法**：对比 SKILL.md 措辞风格

### P4.8 stock-price SKILL.md 对比

**Charles 现状**（Stage P2 重构）：
- frontmatter: name/description/when_to_use
- 核心能力段
- Workflow Step 1-N
- 脚本调用规则
- 禁止行为

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.8.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.8.2 | Workflow 步骤数 | N/A | N 步 | Charles 量化特化 |
| 4.8.3 | 脚本调用规则 | 是 | 是 | 已对齐 |
| 4.8.4 | 禁止行为 | 是 | 是 | 已对齐 |
| 4.8.5 | 与 AGENTS.md 重复内容 | 无 | 无 | 已对齐（Stage P5.3） |

**验证方法**：检查 stock-price SKILL.md

### P4.9 read-pdf SKILL.md 对比

**Charles 现状**（Stage P2 重构）：
- 顶部强调"可下载年报 PDF"
- Workflow Step 1-4

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.9.1 | 顶部能力强调 | 是 | 是 | 已对齐（Stage P2） |
| 4.9.2 | 下载能力说明 | 是 | 是 | 已对齐 |
| 4.9.3 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.9.4 | fetch_report_pdf.py 调用 | N/A | 是 | Charles 量化特化 |
| 4.9.5 | query_report.py 调用 | N/A | 是 | Charles 量化特化 |

**验证方法**：检查 read-pdf SKILL.md

### P4.10 financial-analysis SKILL.md 对比

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.10.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.10.2 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.10.3 | 脚本调用规则 | 是 | 是 | 已对齐 |
| 4.10.4 | 财务指标说明 | N/A | 是 | Charles 量化特化 |

**验证方法**：检查 financial-analysis SKILL.md

### P4.11 write-report SKILL.md 对比

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.11.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.11.2 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.11.3 | 报告模板说明 | N/A | 是 | Charles 量化特化 |
| 4.11.4 | 输出位置规则 | 是 | 是 | 已对齐 |

**验证方法**：检查 write-report SKILL.md

### P4.12 compare-reports SKILL.md 对比

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.12.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.12.2 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.12.3 | 对比维度说明 | N/A | 是 | Charles 量化特化 |

**验证方法**：检查 compare-reports SKILL.md

### P4.13 sentiment-analysis SKILL.md 对比

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.13.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.13.2 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.13.3 | 情感分析模型说明 | N/A | 是 | Charles 量化特化 |

**验证方法**：检查 sentiment-analysis SKILL.md

### P4.14 bond-credit-review SKILL.md 对比

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.14.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.14.2 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.14.3 | 信用评级说明 | N/A | 是 | Charles 量化特化 |

**验证方法**：检查 bond-credit-review SKILL.md

### P4.15 web-search SKILL.md 对比

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.15.1 | frontmatter 完整性 | name/description | name/description/when_to_use | Charles 额外 |
| 4.15.2 | Workflow 步骤 | 是 | 是 | 已对齐 |
| 4.15.3 | 搜索引擎说明 | N/A | 是 | Charles 量化特化 |

**验证方法**：检查 web-search SKILL.md

### P4.16 always_skills 段对比

**Cline 实现**：
- always=True 的技能在 system prompt 中预加载 Level 2 Instructions
- skills_summary 段不含 always 技能的 Level 2

**Charles 实现**：
- always=True 的技能在 system prompt 中预加载
- always_skills 段开头标注"已自动加载"（Stage P5.4）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.16.1 | always 预加载 Level 2 | 是 | 是 | 已对齐 |
| 4.16.2 | always_skills 段标注 | 无 | "已自动加载" | Charles 额外（Stage P5.4） |
| 4.16.3 | always 技能在 summary 中 | 是 | 是 | 已对齐 |
| 4.16.4 | always 技能调用 skills 工具 | 不需要 | 不需要 | 已对齐 |

**验证方法**：检查 always_skills 段

### P4.17 skills_summary 段对比

**Cline 实现**：
- 表格列示技能名 + description
- 不含 when_to_use

**Charles 实现**：
- 3 列表格：技能名 / 何时使用 / 用途（Stage P5.1）
- 含 when_to_use

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.17.1 | summary 列数 | 2 列 | 3 列 | Charles 额外 when_to_use |
| 4.17.2 | summary 内容 | name + description | name + when_to_use + description | Charles 增强 |
| 4.17.3 | 与 skills 工具 description 去重 | 是 | 是 | 已对齐（Stage P5.1） |
| 4.17.4 | 禁用技能过滤 | 是 | 是 | 已对齐 |
| 4.17.5 | always 技能标记 | 是 | 是 | 已对齐 |

**验证方法**：检查 skills_summary 段

### P4.18 技能脚本调用规则对比

**Cline 风格**：
- SKILL.md 内嵌 shell 命令块
- Workflow 步骤化
- 失败处理说明

**Charles 风格**（Stage P2 重构）：
- SKILL.md 内嵌 shell 命令块
- Workflow 步骤化
- 失败处理说明
- 何时执行字段
- 预期输出字段

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 4.18.1 | 命令块格式 | ```bash | ```bash | 已对齐 |
| 4.18.2 | 参数说明 | 是 | 是 | 已对齐 |
| 4.18.3 | 失败处理 | 是 | 是 | 已对齐 |
| 4.18.4 | 何时执行 | 无 | 是 | Charles 额外 |
| 4.18.5 | 预期输出 | 无 | 是 | Charles 额外 |
| 4.18.6 | 输出位置 | 是 | 是 | 已对齐 |
| 4.18.7 | 错误码处理 | 是 | 是 | 已对齐 |
| 4.18.8 | 脚本路径 | 相对 SKILL.md | 相对 SKILL.md | 已对齐 |

**验证方法**：对比技能脚本调用规则

### P4.19 技能脚本实现风格对比（scripts/*.py）

**背景**：Charles 的技能目录下有 19 个 .py 脚本，这些脚本从 nanobot 迁移而来，需要对比其实现风格是否已对齐 Cline 的技能脚本风格，或仍保留 nanobot 风格。

**Cline 技能脚本风格**：
- Cline 的技能脚本通常是 SKILL.md 内嵌的 shell 命令
- 或为独立脚本，但通过 SKILL.md 的 Workflow 步骤调用
- 脚本接收命令行参数，输出到 stdout
- 脚本不直接依赖 agent 运行时

**Charles 技能脚本清单**（19 个）：

| 技能 | 脚本 | 路径 |
|------|------|------|
| read-pdf | fetch_report_pdf.py | agent_config/skills/read-pdf/scripts/ |
| read-pdf | query_report.py | agent_config/skills/read-pdf/scripts/ |
| read-pdf | build_index.py | agent_config/skills/read-pdf/scripts/ |
| read-pdf | fetch_financial_data.py | agent_config/skills/read-pdf/scripts/ |
| read-pdf | parse_pdf_ocr.py | agent_config/skills/read-pdf/scripts/ |
| read-pdf | parse_pdf_basic.py | agent_config/skills/read-pdf/scripts/ |
| financial-analysis | fetch_financial_csv.py | agent_config/skills/financial-analysis/scripts/ |
| financial-analysis | ratio_analysis.py | agent_config/skills/financial-analysis/scripts/ |
| financial-analysis | peer_compare.py | agent_config/skills/financial-analysis/scripts/ |
| web-search | search_market.py | agent_config/skills/web-search/scripts/ |
| compare-reports | cross_company.py | agent_config/skills/compare-reports/scripts/ |
| compare-reports | cross_period.py | agent_config/skills/compare-reports/scripts/ |
| write-report | report_generator.py | agent_config/skills/write-report/scripts/ |
| write-report | prompts.py | agent_config/skills/write-report/scripts/ |
| write-report | five_step_analysis.py | agent_config/skills/write-report/scripts/ |
| sentiment-analysis | sentiment_scorer.py | agent_config/skills/sentiment-analysis/scripts/ |
| sentiment-analysis | news_fetcher.py | agent_config/skills/sentiment-analysis/scripts/ |
| sentiment-analysis | event_detector.py | agent_config/skills/sentiment-analysis/scripts/ |
| stock-price | get_kline.py | agent_config/skills/stock-price/scripts/ |

| # | 对比项 | Cline 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 4.19.1 | 脚本调用方式 | SKILL.md 内嵌命令 / 独立脚本 | 独立脚本 | 需检查 |
| 4.19.2 | 脚本参数传递 | 命令行参数 | 需检查 | 待验证 |
| 4.19.3 | 脚本输出方式 | stdout | 需检查 | 待验证 |
| 4.19.4 | 脚本依赖 agent 运行时 | 否 | 需检查 | 待验证 |
| 4.19.5 | 脚本错误处理 | 退出码 + stderr | 需检查 | 待验证 |
| 4.19.6 | 脚本编码 | UTF-8 | 需检查 | 待验证 |
| 4.19.7 | 脚本注释风格 | 英文 | 需检查（是否中文） | 待验证 |
| 4.19.8 | 脚本结构 | 函数式 / 模块化 | 需检查 | 待验证 |
| 4.19.9 | 脚本依赖管理 | requirements.txt | 需检查 | 待验证 |
| 4.19.10 | nanobot 风格残留 | N/A | 需检查 | 重点对比 |
| 4.19.11 | 脚本命名风格 | kebab-case / snake_case | 需检查 | 待验证 |
| 4.19.12 | 脚本与 SKILL.md 一致性 | Workflow 步骤对应 | 需检查 | 待验证 |

**验证方法**：逐个检查 19 个脚本的实现风格，对比 Cline 技能脚本风格，标注 nanobot 残留

### P4.20 技能系统 nanobot 残留专项检查

**背景**：技能系统是从 nanobot 迁移而来，需要专项检查实现逻辑层面是否残留 nanobot 风格，而不仅仅是注释层面。

**检查范围**：
- `agent/skills/loader.py` — 技能加载器
- `agent/skills/registry.py` — 技能注册表
- `agent/skills/skill_tool.py` — 技能工具
- `agent/skills/__init__.py` — 包入口
- `agent_config/skills/*/SKILL.md` — 8 个 SKILL.md
- `agent_config/skills/*/scripts/*.py` — 19 个脚本

**nanobot 风格特征**（需检查是否残留）：
1. 函数命名：nanobot 用 camelCase 或特定前缀（如 `get_skill_metadata`）
2. 数据结构：nanobot 用 dict 而非 dataclass
3. 错误处理：nanobot 用 try/except + fallback
4. 配置加载：nanobot 用 JSON 而非 YAML
5. 脚本调用：nanobot 直接 import 而非 subprocess
6. 返回格式：nanobot 用字符串而非 AgentToolResult
7. 注释风格：docstring 提到 nanobot

| # | 检查项 | Cline 风格 | nanobot 风格 | Charles 现状 | 关键差异 |
|---|--------|-----------|-------------|-------------|---------|
| 4.20.1 | loader.py 函数命名 | snake_case | camelCase | 需检查 | 待验证 |
| 4.20.2 | loader.py 数据结构 | dataclass | dict | 需检查 | 待验证 |
| 4.20.3 | loader.py 错误处理 | raise | try/except + fallback | 需检查 | 待验证 |
| 4.20.4 | registry.py 数据结构 | dataclass | dict | 需检查 | 待验证 |
| 4.20.5 | registry.py 返回格式 | SkillMetadata | dict | 需检查 | 待验证 |
| 4.20.6 | skill_tool.py 返回格式 | AgentToolResult | string | 需检查 | 待验证 |
| 4.20.7 | skill_tool.py XML 格式 | `<skill name="...">` | 其他 | 需检查 | 待验证 |
| 4.20.8 | SKILL.md frontmatter | YAML | JSON | 需检查 | 待验证 |
| 4.20.9 | 脚本调用方式 | subprocess | import | 需检查 | 待验证 |
| 4.20.10 | 脚本返回格式 | stdout + exit_code | return value | 需检查 | 待验证 |
| 4.20.11 | 注释残留 | 无 | 提到 nanobot | 需检查 | 待验证 |
| 4.20.12 | 配置文件格式 | YAML | JSON | 需检查 | 待验证 |

**验证方法**：逐文件检查 nanobot 风格特征，区分"注释残留"和"实现逻辑残留"

---

## 七、Phase 5：System Prompt 组件结构与形式风格对比

**对标视角**：V3 Prompt 组件结构 + V4 Prompt 形式风格
**目标**：对比 Charles `agent/context.py::SystemPromptBuilder` + `agent/prompts/charles_system_prompt.py` 与 Cline `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` + `sdk/packages/shared/src/prompt/system.ts` 的实现细节，覆盖段落存在性、段落顺序、段落内容、标签格式、字段名语言、条件注入
**Cline 源码**：`runtime-builder.ts` + `system.ts` + `format.ts` + `cline-rules.ts` + `frontmatter.ts` + `rule-conditionals.ts`
**Charles 源码**：`agent/context.py` + `agent/prompts/charles_system_prompt.py` + `agent/rules_loader.py`

### P5.1 SystemPromptBuilder 架构对比

**Cline 实现**（runtime-builder.ts）：
- `buildClineSystemPrompt()` 是纯组装函数
- rules / metadata / skills 由编排器传入
- 不负责加载 rules
- 职责单一：模板渲染 + 占位符替换

**Charles 实现**（context.py::SystemPromptBuilder）：
- `SystemPromptBuilder` 类
- 既构建 prompt 又加载 rules
- 职责混合

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.1.1 | 架构职责 | 纯组装函数 | 组装 + 加载 rules | A1 差距 |
| 5.1.2 | 函数 vs 类 | 函数 | 类 | 实现范式不同 |
| 5.1.3 | rules 加载 | 编排器 | SystemPromptBuilder | 位置不同 |
| 5.1.4 | metadata 注入 | 编排器 | SystemPromptBuilder | 位置不同 |
| 5.1.5 | skills 注入 | 编排器 | SystemPromptBuilder | 位置不同 |
| 5.1.6 | 模板渲染 | 是 | 是 | 已对齐 |
| 5.1.7 | 占位符替换 | 是 | 是 | 已对齐 |
| 5.1.8 | 条件注入 | 编排器 | SystemPromptBuilder | 位置不同 |

**验证方法**：对比 SystemPromptBuilder 架构

### P5.2 System Prompt 段落清单对比

**Cline system prompt 段落顺序**（runtime-builder.ts）：
1. Base prompt（DEFAULT_CLINE_SYSTEM_PROMPT / YOLO_CLINE_SYSTEM_PROMPT）
2. `<env>` 段（环境信息）
3. 工具说明段（自动生成）
4. Workspace Configuration 段（metadata）
5. MCP 服务器概览段
6. Cline Rules 段（.clinerules/ + frontmatter + conditionals）
7. Skills 概览段（name + description）
8. Always Skills 指令段（Level 2）
9. Custom Instructions 段
10. Memory 段
11. Mode 段（plan/act/yolo）
12. `<user_input mode>` 标签说明段

**Charles system prompt 段落顺序**（context.py）：
1. Base prompt（DEFAULT_CHARLES_SYSTEM_PROMPT）
2. `<env>` 段
3. 工具说明段
4. `<charles_metadata>` 段
5. MCP 服务器概览段
6. Cline Rules 段（agent_config/rules/）
7. Skills 概览段（3 列表格）
8. Always Skills 指令段
9. Memory 段
10. Mode 段
11. `<user_input mode>` 标签说明段
12. Enhancement 段（可选）

| # | 对比项 | Cline 顺序 | Charles 顺序 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.2.1 | Base prompt 段 | 1 | 1 | 已对齐 |
| 5.2.2 | `<env>` 段 | 2 | 2 | 已对齐 |
| 5.2.3 | 工具说明段 | 3 | 3 | 已对齐 |
| 5.2.4 | metadata 段 | 4 | 4 | 已对齐 |
| 5.2.5 | MCP 概览段 | 5 | 5 | 已对齐 |
| 5.2.6 | Cline Rules 段 | 6 | 6 | 已对齐 |
| 5.2.7 | Skills 概览段 | 7 | 7 | 已对齐 |
| 5.2.8 | Always Skills 段 | 8 | 8 | 已对齐 |
| 5.2.9 | Custom Instructions 段 | 9 | 无 | Charles 缺失 |
| 5.2.10 | Memory 段 | 10 | 9 | 顺序偏移 |
| 5.2.11 | Mode 段 | 11 | 10 | 顺序偏移 |
| 5.2.12 | `<user_input mode>` 段 | 12 | 11 | 顺序偏移 |
| 5.2.13 | Enhancement 段 | 无 | 12（可选） | Charles 额外 |
| 5.2.14 | 段落总数 | 12 | 11-12 | 数量不同 |

**验证方法**：打印完整 system prompt，逐段对比

### P5.3 Base Prompt 对比（DEFAULT_CLINE_SYSTEM_PROMPT）

**Cline 实现**（system.ts）：
- `DEFAULT_CLINE_SYSTEM_PROMPT` — 标准 act 模式
- `YOLO_CLINE_SYSTEM_PROMPT` — yolo 后台自动化模式
- 身份声明 + 角色定义 + 行为约束

**Charles 实现**（charles_system_prompt.py）：
- `DEFAULT_CHARLES_SYSTEM_PROMPT` — 标准 act 模式
- 无独立 yolo 模板（L8 差距）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.3.1 | Base prompt 模板 | system.ts | charles_system_prompt.py | 已对齐 |
| 5.3.2 | yolo 独立模板 | YOLO_CLINE_SYSTEM_PROMPT | 无 | L8 差距 |
| 5.3.3 | 身份声明 | 是 | 是 | 已对齐 |
| 5.3.4 | 角色定义 | 是 | 是 | 已对齐 |
| 5.3.5 | 行为约束 | 是 | 是 | 已对齐 |
| 5.3.6 | yolo 身份差异 | 后台自动化 | 描述为"与 act 等价" | L8 差距 |
| 5.3.7 | yolo submit_and_exit | 必须 | 描述为"可选" | L8 差距 |
| 5.3.8 | 语言 | 英文 | 中文 | 语言不同 |

**验证方法**：对比 base prompt 内容

### P5.4 `<env>` 段对比

**Cline 实现**（system.ts）：
```
<env>
Platform: {platform}
Date: {date}
IDE: {ide}
Working Directory: {cwd}
</env>
```

**Charles 实现**（charles_system_prompt.py）：
```
<env>
平台: {platform}
日期: {date}
IDE: {ide}
工作目录: {cwd}
</env>
```

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.4.1 | `<env>` 标签 | 是 | 是 | 已对齐 |
| 5.4.2 | Platform 字段 | Platform | 平台 | L1 差距（中文） |
| 5.4.3 | Date 字段 | Date | 日期 | L1 差距（中文） |
| 5.4.4 | IDE 字段 | IDE | IDE | 已对齐 |
| 5.4.5 | Working Directory 字段 | Working Directory | 工作目录 | L1 差距（中文） |
| 5.4.6 | 字段值语言 | 英文 | 中文 | L1 差距 |
| 5.4.7 | 段落位置 | 第 2 段 | 第 2 段 | 已对齐 |

**验证方法**：打印 `<env>` 段，对比字段名

### P5.5 工具说明段对比

**Cline 实现**（runtime-builder.ts）：
- 自动从 tool definition 生成
- 每个工具：name + description + input_schema
- XML 格式

**Charles 实现**（context.py::_build_tools_section）：
- 自动从 tool definition 生成
- skills 工具特殊处理（不重复列技能名）（Stage P1.1）
- 增加"工具 vs 技能 决策树"段（Stage P1.2）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.5.1 | 工具说明生成 | 自动 | 自动 | 已对齐 |
| 5.5.2 | 工具字段 | name + description + input_schema | name + description + input_schema | 已对齐 |
| 5.5.3 | skills 工具展示 | 含技能名列表 | 不含技能名列表（Stage P1.1） | Charles 去重 |
| 5.5.4 | 工具 vs 技能 决策树 | 无 | 是 | Charles 额外（Stage P1.2） |
| 5.5.5 | 工具使用指引 | 是 | 是 | 已对齐 |
| 5.5.6 | XML 格式 | 是 | 是 | 已对齐 |
| 5.5.7 | 段落位置 | 第 3 段 | 第 3 段 | 已对齐 |

**验证方法**：打印工具说明段，对比内容

### P5.6 Metadata 段对比

**Cline 实现**（runtime-builder.ts）：
- `# Workspace Configuration\n{...}` 文本块
- WORKSPACE_CONFIGURATION_MARKER
- 仅 `isCline(providerId)` 时注入

**Charles 实现**（context.py::_build_metadata）：
- `<charles_metadata>\n{...}\n</charles_metadata>` XML 标签
- 始终注入（无 provider 条件判断）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.6.1 | 标签格式 | `# Workspace Configuration` | `<charles_metadata>` | L5 差距 |
| 5.6.2 | provider 条件判断 | isCline | 无 | L4 差距 |
| 5.6.3 | 注入内容 | workspaces | workspaces | 已对齐 |
| 5.6.4 | 注入时机 | always | always | 已对齐 |
| 5.6.5 | 段落位置 | 第 4 段 | 第 4 段 | 已对齐 |
| 5.6.6 | 标签闭合 | 无 | `</charles_metadata>` | L5 差距 |

**验证方法**：打印 metadata 段，对比标签格式

### P5.7 MCP 服务器概览段对比

**Cline 实现**：
- 列出已连接的 MCP 服务器
- 服务器名 + 工具数

**Charles 实现**：
- 列出已连接的 MCP 服务器
- 服务器名 + 工具数

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.7.1 | MCP 概览段 | 是 | 是 | 已对齐 |
| 5.7.2 | 服务器名 | 是 | 是 | 已对齐 |
| 5.7.3 | 工具数 | 是 | 是 | 已对齐 |
| 5.7.4 | 段落位置 | 第 5 段 | 第 5 段 | 已对齐 |
| 5.7.5 | 无 MCP 时行为 | 不注入 | 不注入 | 已对齐 |

**验证方法**：配置 MCP 服务器，打印概览段

### P5.8 Cline Rules 段对比

**Cline 实现**（cline-rules.ts + frontmatter.ts + rule-conditionals.ts）：
- `.clinerules/` 目录扫描
- frontmatter 解析（description/globs/alwaysApply/applyTo）
- rule-conditionals 按 mode 加载
- external-rules（.cursorrules 等）

**Charles 实现**（rules_loader.py）：
- `agent_config/rules/` 目录扫描
- frontmatter 解析
- rule_toggles 开关
- 无 external-rules

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.8.1 | rules 目录 | .clinerules/ | agent_config/rules/ | 路径不同 |
| 5.8.2 | frontmatter 解析 | 是 | 是 | 已对齐 |
| 5.8.3 | rule-conditionals | 按 mode 加载 | 无 | Charles 缺失 |
| 5.8.4 | external-rules | .cursorrules 等 | 无 | Charles 不实施 |
| 5.8.5 | globs 匹配 | 是 | 无 | Charles 缺失 |
| 5.8.6 | applyTo 字段 | plan/act | 无 | Charles 缺失 |
| 5.8.7 | alwaysApply 字段 | 是 | 是 | 已对齐 |
| 5.8.8 | rule_toggles | 是 | 是 | 已对齐（Stage 13.3） |
| 5.8.9 | rule name | watcher.name | 文件 stem | L3-new 差距 |
| 5.8.10 | 段落位置 | 第 6 段 | 第 6 段 | 已对齐 |

**验证方法**：配置 rules，打印 rules 段

### P5.9 Skills 概览段对比

**Cline 实现**：
- 2 列表格：技能名 + description
- 不含 when_to_use

**Charles 实现**：
- 3 列表格：技能名 / 何时使用 / 用途（Stage P5.1）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.9.1 | 表格列数 | 2 列 | 3 列 | Charles 额外 when_to_use |
| 5.9.2 | 技能名 | 是 | 是 | 已对齐 |
| 5.9.3 | description | 是 | 是 | 已对齐 |
| 5.9.4 | when_to_use | 无 | 是 | Charles 额外 |
| 5.9.5 | 禁用技能过滤 | 是 | 是 | 已对齐 |
| 5.9.6 | 段落位置 | 第 7 段 | 第 7 段 | 已对齐 |

**验证方法**：打印 skills 概览段

### P5.10 Always Skills 指令段对比

**Cline 实现**：
- always=True 的技能 Level 2 Instructions 预加载
- 无特殊标注

**Charles 实现**：
- always=True 的技能 Level 2 预加载
- 段开头标注"已自动加载"（Stage P5.4）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.10.1 | always 预加载 | 是 | 是 | 已对齐 |
| 5.10.2 | "已自动加载"标注 | 无 | 是 | Charles 额外 |
| 5.10.3 | Level 2 内容 | SKILL.md 正文 | SKILL.md 正文 | 已对齐 |
| 5.10.4 | 段落位置 | 第 8 段 | 第 8 段 | 已对齐 |

**验证方法**：打印 always skills 段

### P5.11 Custom Instructions 段对比

**Cline 实现**：
- 用户自定义指令段
- 从 config 加载

**Charles 实现**：
- 无独立 Custom Instructions 段

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.11.1 | Custom Instructions 段 | 是 | 无 | Charles 缺失 |
| 5.11.2 | 用户自定义指令 | 是 | 无 | Charles 缺失 |
| 5.11.3 | 段落位置 | 第 9 段 | 无 | Charles 缺失 |

**验证方法**：检查是否有 Custom Instructions 段

### P5.12 Memory 段对比

**Cline 实现**：
- `memory/MEMORY.md` 内容
- 持久化记忆

**Charles 实现**：
- `agent_config/memory/MEMORY.md` 内容
- 持久化记忆

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.12.1 | Memory 段 | 是 | 是 | 已对齐 |
| 5.12.2 | Memory 文件 | memory/MEMORY.md | agent_config/memory/MEMORY.md | 路径不同 |
| 5.12.3 | 加载时机 | 启动时 | 启动时 | 已对齐 |
| 5.12.4 | 段落位置 | 第 10 段 | 第 9 段 | 顺序偏移 |
| 5.12.5 | 无 Memory 时行为 | 不注入 | 不注入 | 已对齐 |

**验证方法**：配置 MEMORY.md，打印 memory 段

### P5.13 Mode 段对比（plan/act/yolo）

**Cline 实现**：
- 切换 mode 时重新构建 system prompt
- PLAN_MODE_PROMPT 注入
- yolo 独立 base prompt

**Charles 实现**：
- 切换 mode 时重新构建 system prompt
- PLAN_MODE_PROMPT 注入
- yolo 描述为"与 act 等价"

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.13.1 | mode 切换 prompt 重建 | 是 | 是 | 已对齐 |
| 5.13.2 | PLAN_MODE_PROMPT | 是 | 是 | 已对齐（Stage P4） |
| 5.13.3 | yolo 独立模板 | 是 | 无 | L8 差距 |
| 5.13.4 | mode_notice 机制 | 是 | 无 | M1 差距 |
| 5.13.5 | 段落位置 | 第 11 段 | 第 10 段 | 顺序偏移 |

**验证方法**：切换 mode，打印 mode 段

### P5.14 `<user_input mode>` 标签说明段对比

**Cline 实现**（format.ts）：
- `formatUserInputBlock(input, mode)` 在 runtime 层调用
- 标签说明段解释 `<user_input mode="...">` 语义
- 不列举具体工具名

**Charles 实现**（context.py::MODE_TAG_INSTRUCTIONS）：
- server.py 手动包装（M2 差距）
- 标签说明段列举具体工具名（L7 差距）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.14.1 | `<user_input>` 包装位置 | runtime 层 | server.py | M2 差距 |
| 5.14.2 | 标签说明段 | 是 | 是 | 已对齐 |
| 5.14.3 | 工具名列举 | 无 | 是 | L7 差距 |
| 5.14.4 | mode_notice 机制 | 是 | 无 | M1 差距 |
| 5.14.5 | 段落位置 | 第 12 段 | 第 11 段 | 顺序偏移 |

**验证方法**：打印标签说明段

### P5.15 Enhancement 段对比

**Cline 实现**：
- 无 Enhancement 段

**Charles 实现**：
- tools_section / skills_summary / always_skills / mcp_section / memory 增强
- 默认 `enabled: false`

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.15.1 | Enhancement 段 | 无 | 是（可选） | Charles 额外 |
| 5.15.2 | 默认启用 | N/A | false | 合理增强 |
| 5.15.3 | 段落位置 | N/A | 第 12 段 | Charles 额外 |

**验证方法**：启用 Enhancement，打印段

### P5.16 `<env>` 段条件注入对比

**Cline 实现**：
- always 注入

**Charles 实现**：
- always 注入

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.16.1 | `<env>` 注入条件 | always | always | 已对齐 |
| 5.16.2 | `<env>` 内容来源 | system.ts | charles_system_prompt.py | 已对齐 |

**验证方法**：检查 `<env>` 段注入条件

### P5.17 Metadata 段条件注入对比

**Cline 实现**：
- 仅 `isCline(providerId)` 时注入

**Charles 实现**：
- always 注入（无 provider 条件判断）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.17.1 | metadata 注入条件 | isCline | always | L4 差距 |
| 5.17.2 | provider 判断 | 是 | 无 | L4 差距 |
| 5.17.3 | 合理性 | N/A | 合理增强 | Charles 保留 |

**验证方法**：检查 metadata 段注入条件

### P5.18 Skills 段条件注入对比

**Cline 实现**：
- 有技能时注入

**Charles 实现**：
- 有技能时注入

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.18.1 | skills 注入条件 | 有技能时 | 有技能时 | 已对齐 |
| 5.18.2 | always skills 注入 | always=True | always=True | 已对齐 |
| 5.18.3 | 无技能时行为 | 不注入 | 不注入 | 已对齐 |

**验证方法**：检查 skills 段注入条件

### P5.19 MCP 段条件注入对比

**Cline 实现**：
- 有 MCP 服务器时注入

**Charles 实现**：
- 有 MCP 服务器时注入

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.19.1 | MCP 注入条件 | 有 MCP 时 | 有 MCP 时 | 已对齐 |
| 5.19.2 | 无 MCP 时行为 | 不注入 | 不注入 | 已对齐 |

**验证方法**：检查 MCP 段注入条件

### P5.20 Mode 段条件注入对比

**Cline 实现**：
- plan 模式注入 PLAN_MODE_PROMPT
- act 模式不注入
- yolo 模式注入 YOLO base prompt

**Charles 实现**：
- plan 模式注入 PLAN_MODE_PROMPT
- act 模式不注入
- yolo 模式描述为"与 act 等价"

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 5.20.1 | plan 模式注入 | 是 | 是 | 已对齐 |
| 5.20.2 | act 模式注入 | 否 | 否 | 已对齐 |
| 5.20.3 | yolo 模式注入 | YOLO base | 无 | L8 差距 |
| 5.20.4 | mode_notice | 是 | 无 | M1 差距 |

**验证方法**：切换 mode，检查注入条件

### P5.21 System Prompt 形式风格对比（标签/措辞）

**Cline 风格**：
- XML 标签：`<env>` / `<user_input>` / `<mode_notice>`
- 文本块：`# Workspace Configuration`
- 字段名：英文
- 措辞：英文

**Charles 风格**：
- XML 标签：`<env>` / `<user_input>` / `<charles_metadata>`
- 文本块：无
- 字段名：中文（部分）
- 措辞：中文

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 5.21.1 | XML 标签风格 | `<env>` | `<env>` | 已对齐 |
| 5.21.2 | metadata 标签 | `# Workspace Configuration` | `<charles_metadata>` | L5 差距 |
| 5.21.3 | 字段名语言 | 英文 | 中文（部分） | L1 差距 |
| 5.21.4 | 措辞语言 | 英文 | 中文 | 语言不同 |
| 5.21.5 | 标签闭合 | 是 | 是 | 已对齐 |
| 5.21.6 | 标签嵌套 | 是 | 是 | 已对齐 |

**验证方法**：对比 system prompt 标签风格

### P5.22 System Prompt 字段名语言对比

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 5.22.1 | env 字段名 | 英文 | 中文 | L1 差距 |
| 5.22.2 | metadata 字段名 | 英文 | 英文 | 已对齐 |
| 5.22.3 | tools 字段名 | 英文 | 英文 | 已对齐 |
| 5.22.4 | skills 字段名 | 英文 | 中文（部分） | 语言不同 |
| 5.22.5 | rules 字段名 | 英文 | 中文 | 语言不同 |

**验证方法**：对比字段名语言

### P5.23 System Prompt 长度对比

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 5.23.1 | 总长度 | ~5000 chars | ~6459 chars | Charles 略长 |
| 5.23.2 | Base prompt 长度 | ~2000 chars | ~2000 chars | 已对齐 |
| 5.23.3 | 工具说明长度 | ~1500 chars | ~1500 chars | 已对齐 |
| 5.23.4 | skills 长度 | ~500 chars | ~800 chars | Charles 略长（when_to_use） |
| 5.23.5 | rules 长度 | ~500 chars | ~500 chars | 已对齐 |

**验证方法**：打印 system prompt 长度

---

## 八、Phase 6：Agent Prompt（AGENTS.md）组件结构与形式风格对比

**对标视角**：V5 Agent Prompt
**目标**：对比 Charles `agent_config/AGENTS.md` 与 Cline `sdk/AGENTS.md` 的组件结构、frontmatter、主体结构、决策树、措辞风格
**Cline 源码**：`sdk/AGENTS.md` + `sdk/packages/core/src/extensions/config/cline-rules.ts` + `frontmatter.ts`
**Charles 源码**：`agent_config/AGENTS.md` + `agent/rules_loader.py`

### P6.1 AGENTS.md frontmatter 对比

**Cline frontmatter**（参考 sdk/AGENTS.md）：
```yaml
---
description: <规则描述>
globs: ["**/*.ts"]
applyTo: [act, plan]
alwaysApply: true
---
```

**Charles frontmatter**（Stage P3 已加）：
```yaml
---
description: Charles 投研情报官主规则 — 所有模式和业务场景下常驻应用
applyTo: [act, plan]
alwaysApply: true
---
```

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.1.1 | frontmatter 存在 | 是 | 是 | 已对齐（Stage P3.1） |
| 6.1.2 | description 字段 | 是 | 是 | 已对齐 |
| 6.1.3 | globs 字段 | 是 | 无 | Charles 缺失 |
| 6.1.4 | applyTo 字段 | 是 | 是 | 已对齐 |
| 6.1.5 | alwaysApply 字段 | 是 | 是 | 已对齐 |
| 6.1.6 | frontmatter 分隔符 | `---` | `---` | 已对齐 |
| 6.1.7 | frontmatter 解析 | frontmatter.ts | parse_yaml_frontmatter | 已对齐 |
| 6.1.8 | frontmatter 移除 | _strip_frontmatter | _strip_frontmatter | 已对齐（Stage P3） |

**验证方法**：对比 frontmatter 字段

### P6.2 AGENTS.md 主体结构对比

**Cline AGENTS.md 结构**（开发参考文档风格）：
- 项目边界（做什么、不做什么）
- 路由规则（何时用 tools、何时用 skills）
- 验证规则（如何验证结果）
- 开发约束（命名、错误处理）

**Charles AGENTS.md 结构**（Stage P3 重构后）：
- 身份声明
- 硬约束
- 工具 vs 技能 决策树（Stage P1.3）
- 股票代码格式
- 输出规范

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.2.1 | 主体风格 | 开发参考文档 | 业务规则堆叠 | 风格不同 |
| 6.2.2 | 项目边界段 | 是 | 无 | Charles 缺失 |
| 6.2.3 | 路由规则段 | 是 | 工具 vs 技能 决策树 | 形式不同但等价 |
| 6.2.4 | 验证规则段 | 是 | 无 | Charles 缺失 |
| 6.2.5 | 开发约束段 | 是 | 硬约束段 | 形式不同但等价 |
| 6.2.6 | 身份声明段 | 无 | 是 | Charles 额外 |
| 6.2.7 | 股票代码格式段 | 无 | 是 | Charles 量化特化 |
| 6.2.8 | 输出规范段 | 无 | 是 | Charles 量化特化 |

**验证方法**：对比 AGENTS.md 主体结构

### P6.3 AGENTS.md 决策树对比

**Cline 决策树**：
- 无显式决策树（默认 prompt 已含并行调用指引）
- 工具选择靠 tool description

**Charles 决策树**（Stage P1.3 新增）：
- 显式"工具 vs 技能 决策树"段
- 明确何时用 tools、何时用 skills

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.3.1 | 决策树存在 | 无 | 是 | Charles 额外（Stage P1.3） |
| 6.3.2 | 工具选择指引 | 默认 prompt | 决策树段 | 形式不同 |
| 6.3.3 | tools vs skills 优先级 | 默认 prompt | 决策树段 | Charles 显式 |
| 6.3.4 | 股票代码路由 | 无 | 是 | Charles 量化特化 |

**验证方法**：对比决策树段

### P6.4 AGENTS.md 与 rules 去重对比

**Cline 去重**：
- AGENTS.md 不含 rules 重复内容
- rules 在 .clinerules/ 中

**Charles 去重**（Stage P3.2）：
- AGENTS.md 移除与 rules/general.md 重复的"时间基准"段
- rules 在 agent_config/rules/

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.4.1 | 重复内容 | 无 | 无 | 已对齐（Stage P3.2） |
| 6.4.2 | 时间基准段 | 在 rules | 在 rules | 已对齐 |
| 6.4.3 | 股票代码格式段 | N/A | 在 AGENTS.md | Charles 量化特化 |
| 6.4.4 | 输出规范段 | N/A | 在 AGENTS.md | Charles 量化特化 |

**验证方法**：检查 AGENTS.md 与 rules 去重

### P6.5 AGENTS.md 措辞风格对比

**Cline 风格**：
- 英文
- 简洁陈述句
- 无表格

**Charles 风格**：
- 中文
- 业务规则堆叠
- 含表格

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.5.1 | 语言 | 英文 | 中文 | 语言不同 |
| 6.5.2 | 句式 | 简洁陈述 | 业务规则 | 风格不同 |
| 6.5.3 | 表格使用 | 无 | 是 | 形式不同 |
| 6.5.4 | 标题层级 | ## / ### | ## / ### | 已对齐 |
| 6.5.5 | 代码块 | ```bash | ```bash | 已对齐 |

**验证方法**：对比 AGENTS.md 措辞

### P6.6 AGENTS.md 条件注入对比

**Cline 实现**：
- `alwaysApply: true` 时 always 注入
- `applyTo` 字段控制按 mode 注入

**Charles 实现**：
- `alwaysApply: true` 时 always 注入
- `applyTo` 字段（Stage P3 已加）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 6.6.1 | alwaysApply 注入 | always | always | 已对齐 |
| 6.6.2 | applyTo 字段 | 是 | 是 | 已对齐（Stage P3） |
| 6.6.3 | 按 mode 注入 | 是 | 是 | 已对齐 |
| 6.6.4 | globs 匹配 | 是 | 无 | Charles 缺失 |

**验证方法**：检查 AGENTS.md 注入条件

### P6.7 AGENTS.md 加载机制对比

**Cline 实现**（cline-rules.ts）：
- watcher 监听文件变化
- frontmatter 解析
- 热重载

**Charles 实现**（rules_loader.py）：
- 启动时扫描
- frontmatter 解析
- 无热重载

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 6.7.1 | 加载时机 | 启动 + 热重载 | 启动 | Charles 无热重载 |
| 6.7.2 | 文件监听 | watcher | 无 | Charles 缺失 |
| 6.7.3 | frontmatter 解析 | 是 | 是 | 已对齐 |
| 6.7.4 | _strip_frontmatter | 是 | 是 | 已对齐（Stage P3） |
| 6.7.5 | 多文件加载 | 是 | 是 | 已对齐 |

**验证方法**：对比加载机制

### P6.8 AGENTS.md rule name 对比

**Cline 实现**：
- rule name = watcher 提供的 `rule.name`

**Charles 实现**：
- rule name = 文件 stem（L3-new 差距）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 6.8.1 | rule name 来源 | watcher.name | 文件 stem | L3-new 差距 |
| 6.8.2 | 功能等价性 | 是 | 是 | 合理差异 |

**验证方法**：对比 rule name 来源

### P6.9 AGENTS.md rule_toggles 对比

**Cline 实现**：
- toggles 机制
- 全局/本地 toggle 分离

**Charles 实现**（Stage 13.3）：
- rule_toggles.json
- load_merged_toggles

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 6.9.1 | toggles 机制 | 是 | 是 | 已对齐 |
| 6.9.2 | 全局/本地分离 | 是 | 是 | 已对齐（Stage 13.3） |
| 6.9.3 | toggle 持久化 | 是 | rule_toggles.json | 已对齐 |

**验证方法**：对比 toggles 机制

### P6.10 AGENTS.md 与 SKILL.md 去重对比

**Cline 实现**：
- AGENTS.md 不含 SKILL.md 重复内容
- SKILL.md 注意事项不与 AGENTS.md 重复

**Charles 实现**（Stage P5.3）：
- AGENTS.md 不含 SKILL.md 重复内容
- SKILL.md 移除与 AGENTS.md 重复的注意事项

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.10.1 | AGENTS.md 与 SKILL.md 去重 | 是 | 是 | 已对齐（Stage P5.3） |
| 6.10.2 | SKILL.md 注意事项 | 技能特定 | 技能特定 | 已对齐 |

**验证方法**：检查去重

### P6.11 AGENTS.md 段落顺序对比

**Cline AGENTS.md 段落顺序**：
1. 项目边界
2. 路由规则
3. 验证规则
4. 开发约束

**Charles AGENTS.md 段落顺序**：
1. 身份声明
2. 硬约束
3. 工具 vs 技能 决策树
4. 股票代码格式
5. 输出规范

| # | 对比项 | Cline 顺序 | Charles 顺序 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 6.11.1 | 段落顺序 | 边界→路由→验证→约束 | 身份→约束→决策树→格式→输出 | 顺序不同 |
| 6.11.2 | 段落数 | 4 | 5 | 数量不同 |
| 6.11.3 | 风格 | 开发参考 | 业务规则 | 风格不同 |

**验证方法**：对比段落顺序

### P6.12 AGENTS.md 验证方法

| # | 验证项 | 方法 | 预期结果 |
|---|--------|------|---------|
| 6.12.1 | frontmatter 生效 | 检查 rules_loader 日志 | AGENTS.md 按 alwaysApply 加载 |
| 6.12.2 | 主体结构 | 打印 AGENTS.md 内容 | 含决策树段 |
| 6.12.3 | 去重 | 对比 AGENTS.md 与 rules | 无重复 |
| 6.12.4 | 条件注入 | 切换 mode | 按 applyTo 注入 |

**验证方法**：综合验证 AGENTS.md

---

## 九、Phase 7：上下文管理与辅助系统对比

**对标视角**：V7 上下文与辅助系统
**目标**：对比 Charles 与 Cline 在上下文压缩、Provider 适配、会话持久化、Checkpoint、Hooks、MCP、Telemetry 等辅助系统的实现
**Cline 源码**：`sdk/packages/core/src/extensions/context/` + `sdk/packages/core/src/services/` + `apps/vscode/src/core/`
**Charles 源码**：`agent/context.py` + `agent/providers/` + `agent/session.py` + `agent/file_checkpoint.py` + `agent/file_hooks/` + `agent/mcp/` + `agent/telemetry.py`

### P7.1 上下文压缩架构对比

**Cline 实现**（compaction.ts + compaction-shared.ts）：
- 触发比例 0.9
- maxInput 128000
- preserve_recent_tokens 20000
- _find_cut_index 安全切割
- _summarize_tool_activity
- PRESERVED_ASSISTANT_TEXT_COUNT
- agentic + basic fallback
- state-aware 持久化（CompactionStateManager）

**Charles 实现**（context.py）：
- 同上全部对齐

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.1.1 | 触发比例 | 0.9 | 0.9 | 已对齐 |
| 7.1.2 | maxInput | 128000 | 128000 | 已对齐 |
| 7.1.3 | preserve_recent_tokens | 20000 | 20000 | 已对齐 |
| 7.1.4 | _find_cut_index | 是 | 是 | 已对齐 |
| 7.1.5 | _summarize_tool_activity | 是 | 是 | 已对齐 |
| 7.1.6 | PRESERVED_ASSISTANT_TEXT_COUNT | 是 | 是 | 已对齐 |
| 7.1.7 | agentic + basic fallback | 是 | 是 | 已对齐 |
| 7.1.8 | CompactionStateManager | 是 | 是 | 已对齐（Stage 11.3） |
| 7.1.9 | abort_signal 透传 | 是 | 是 | 已对齐（Stage 11.2） |
| 7.1.10 | file/image 截断 | 是 | 是 | 已对齐（Stage 11.4） |

**验证方法**：构造超长对话，对比压缩行为

### P7.2 Budget Projection 对比

**Cline 实现**（budget-projection/）：
- BudgetPolicyIntent 枚举
- ProjectionPolicy 字段
- resolve_projection_policy
- find_latest_typed_user_message_index
- find_protected_tail_start_index
- drop_thinking_blocks
- apply_budget_policy
- estimate_protected_token_budget

**Charles 实现**（budget_policy.py + context.py::_project_future_usage）：
- BudgetPolicyIntent 枚举
- ProjectionPolicy 数据类

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.2.1 | BudgetPolicyIntent 枚举 | 是 | 是 | 已对齐 |
| 7.2.2 | ProjectionPolicy 字段 | 是 | 是 | 已对齐 |
| 7.2.3 | resolve_projection_policy | 是 | 是 | 已对齐 |
| 7.2.4 | find_latest_typed_user_message_index | 是 | 是 | 已对齐 |
| 7.2.5 | find_protected_tail_start_index | 是 | 是 | 已对齐 |
| 7.2.6 | drop_thinking_blocks | 是 | 是 | 已对齐 |
| 7.2.7 | apply_budget_policy | 是 | 是 | 已对齐 |
| 7.2.8 | estimate_protected_token_budget | 是 | 是 | 已对齐 |
| 7.2.9 | _project_future_usage | 是 | 是 | 已对齐 |
| 7.2.10 | projection_ratio 默认值 | 0.8 | 0.8 | 已对齐 |
| 7.2.11 | 提前压缩触发 | 是 | 是 | 已对齐 |
| 7.2.12 | compaction_reason 标记 | 是 | 是 | 已对齐 |

**验证方法**：构造不同 intent 场景，对比策略应用

### P7.3 FileContextTracker 对比

**Cline 实现**（context-tracking/）：
- 持久化文件状态
- 压缩摘要质量
- UI 文件状态

**Charles 实现**：
- 仅压缩时临时扫描
- 无持久化文件状态

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.3.1 | FileContextTracker | 是 | 无 | Charles 缺失 |
| 7.3.2 | 持久化文件状态 | 是 | 无 | Charles 缺失 |
| 7.3.3 | 压缩摘要质量 | 高 | 中 | Charles 弱 |
| 7.3.4 | UI 文件状态 | 是 | 无 | Charles 缺失 |

**验证方法**：对比文件追踪机制

### P7.4 LLM Provider 适配对比

**Cline 实现**（services/llms/）：
- Anthropic / OpenAI / Bedrock / Vertex AI
- apply_capability_downgrade
- provider-settings 持久化

**Charles 实现**（providers/）：
- Qwen / OpenAI 兼容
- apply_capability_downgrade（Stage 13.1）
- provider_settings.py（Stage 13.2）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.4.1 | Qwen 适配 | N/A | qwen.py | Charles 量化特化 |
| 7.4.2 | OpenAI 适配 | 是 | 是 | 已对齐（Stage 32.2） |
| 7.4.3 | Anthropic 适配 | 是 | 无 | Charles 缺失 |
| 7.4.4 | Bedrock 适配 | 是 | 无 | Charles 不实施 |
| 7.4.5 | Vertex AI 适配 | 是 | 无 | Charles 不实施 |
| 7.4.6 | apply_capability_downgrade | 是 | 是 | 已对齐（Stage 13.1） |
| 7.4.7 | provider-settings 持久化 | 是 | 是 | 已对齐（Stage 13.2） |
| 7.4.8 | tool_call_id 不稳定处理 | N/A | qwen.py | Charles Qwen 特化 |

**验证方法**：对比 Provider 适配

### P7.5 会话持久化对比

**Cline 实现**（sqlite-session-store.ts）：
- SQLite 数据库
- state-migrations 版本迁移
- SqliteLockManager 跨进程锁

**Charles 实现**（session.py）：
- JSON 文件存储
- _SESSION_FILE_VERSION + _migrate_session_data
- 跨进程文件锁（Stage 31.7）
- session 列表内存索引（Stage 31.8）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.5.1 | 存储格式 | SQLite | JSON 文件 | 格式不同 |
| 7.5.2 | 版本迁移 | state-migrations | _migrate_session_data | 已对齐 |
| 7.5.3 | 跨进程锁 | SqliteLockManager | msvcrt.locking | 已对齐（Stage 31.7） |
| 7.5.4 | session 列表查询 | SQLite 查询 | 内存索引 | 已对齐（Stage 31.8） |
| 7.5.5 | 可读性 | 低 | 高 | Charles 增强 |
| 7.5.6 | 性能 | 高 | 中 | Charles 弱（量化场景可接受） |
| 7.5.7 | session-export | 是 | 无 | Charles 缺失 |

**验证方法**：对比会话持久化

### P7.6 Checkpoint 机制对比

**Cline 实现**（checkpoints/ + shadow-git）：
- shadow-git 仓库
- git ref 持久化
- 回滚联动

**Charles 实现**（file_checkpoint.py）：
- 简化版（消息快照）
- git update-ref（Stage 6.4）
- /rollback + /rollback_file（Stage T5）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.6.1 | Checkpoint 存储 | shadow-git | file_checkpoint.py | 实现不同 |
| 7.6.2 | git ref 持久化 | 是 | 是 | 已对齐（Stage 6.4） |
| 7.6.3 | 回滚联动 | 是 | 是 | 已对齐（Stage T5） |
| 7.6.4 | /rollback 端点 | 是 | 是 | 已对齐 |
| 7.6.5 | /rollback_file 端点 | 是 | 是 | 已对齐 |
| 7.6.6 | 消息快照 | 是 | 是 | 已对齐 |

**验证方法**：对比 Checkpoint 机制

### P7.7 文件 Hooks 系统对比

**Cline 实现**（apps/vscode/src/core/hooks/）：
- 7 种 hook 类型（PreToolUse/PostToolUse/UserPromptSubmit/TaskStart/TaskComplete/TaskResume/TaskCancel）
- HookProcess 跑外部脚本
- hook-factory + templates
- HookError / HookProcessRegistry
- shell-escape
- context-injection

**Charles 实现**（file_hooks/）：
- 7 种 hook 类型
- subprocess 执行脚本
- build_file_hooks_agent_hooks
- HookError（Stage 12.4）
- HookProcessRegistry（Stage 12.4）
- context-injection（Stage 12.3）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.7.1 | hook 类型数 | 7 | 7 | 已对齐 |
| 7.7.2 | PreToolUse | 是 | 是 | 已对齐 |
| 7.7.3 | PostToolUse | 是 | 是 | 已对齐 |
| 7.7.4 | UserPromptSubmit | 是 | 是 | 已对齐 |
| 7.7.5 | TaskStart | 是 | 是 | 已对齐 |
| 7.7.6 | TaskComplete | 是 | 是 | 已对齐 |
| 7.7.7 | TaskResume | 是 | 是 | 已对齐（Stage 31.6） |
| 7.7.8 | TaskCancel | 是 | 是 | 已对齐（Stage 31.6） |
| 7.7.9 | HookProcess | 是 | subprocess | 实现不同但等价 |
| 7.7.10 | hook-factory | 是 | build_file_hooks_agent_hooks | 已对齐 |
| 7.7.11 | templates | 是 | agent_config/hooks/templates/ | 已对齐 |
| 7.7.12 | HookError | 是 | 是 | 已对齐（Stage 12.4） |
| 7.7.13 | HookProcessRegistry | 是 | 是 | 已对齐（Stage 12.4） |
| 7.7.14 | shell-escape | 是 | shlex.quote | 实现不同但等价 |
| 7.7.15 | context-injection | 是 | 是 | 已对齐（Stage 12.3） |
| 7.7.16 | hook 并发执行 | 是 | asyncio.gather | 已对齐（Stage 12.5） |
| 7.7.17 | hook 超时 | 是 | 是 | 已对齐 |
| 7.7.18 | Windows 编码 | N/A | PYTHONIOENCODING=utf-8 | Charles 特化 |

**验证方法**：对比文件 Hooks 系统

### P7.8 MCP 集成对比

**Cline 实现**（extensions/mcp/）：
- MCP 客户端 + 工具注册
- OAuth 认证
- policies.ts 工具策略
- plugin-server-registration
- name-transform 命名空间
- config-loader（.cline/mcp_settings.json）

**Charles 实现**（agent/mcp/）：
- MCP 客户端 + 工具注册
- 无 OAuth
- registry.py per-tool policies
- name-transform hash 截断（Stage 32.3）
- mcp_servers.yaml

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.8.1 | MCP 客户端 | 是 | 是 | 已对齐 |
| 7.8.2 | 工具动态注册 | 是 | 是 | 已对齐 |
| 7.8.3 | OAuth 认证 | 是 | 无 | Charles 不实施 |
| 7.8.4 | per-tool policies | policies.ts | registry.py | 已对齐 |
| 7.8.5 | auto_approve 消费 | tool-approval.ts | mcp.py（Q8 部分实现） | 部分对齐 |
| 7.8.6 | plugin-server-registration | 是 | 无 | Charles 不实施 |
| 7.8.7 | name-transform | 是 | hash 截断 | 已对齐（Stage 32.3） |
| 7.8.8 | config-loader | .cline/mcp_settings.json | mcp_servers.yaml | 格式不同 |
| 7.8.9 | OpenAI 兼容 provider | N/A | 是 | Charles 额外（Stage 32.2） |

**验证方法**：对比 MCP 集成

### P7.9 Telemetry 对比

**Cline 实现**（services/telemetry/）：
- OpenTelemetryAdapter
- TelemetryLoggerSink
- distinctId
- 事件枚举
- OTLP exporter

**Charles 实现**（telemetry.py）：
- OtlpHttpExporter（Stage 14.1）
- distinct_id（Stage 14.3）
- 事件枚举常量（Stage 14.3）
- Cron 完整架构（Stage 14.2）

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.9.1 | OpenTelemetryAdapter | 是 | 是 | 已对齐（Stage 14.1） |
| 7.9.2 | TelemetryLoggerSink | 是 | 无 | Charles 缺失 |
| 7.9.3 | distinctId | 是 | 是 | 已对齐（Stage 14.3） |
| 7.9.4 | 事件枚举 | 是 | 是 | 已对齐（Stage 14.3） |
| 7.9.5 | OTLP exporter | 是 | 是 | 已对齐（Stage 14.1） |
| 7.9.6 | Cron 架构 | 是 | 是 | 已对齐（Stage 14.2） |

**验证方法**：对比 Telemetry

### P7.10 Connectors / Kanban 对比

**Cline 实现**：
- Slack / Telegram / Discord / Linear / GChat / WhatsApp 连接器
- Kanban 看板
- FeatureFlagsService

**Charles 实现**（connectors.py + kanban.py）：
- 骨架
- 未落地

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.10.1 | Slack 连接器 | 是 | 骨架 | Charles 未落地 |
| 7.10.2 | Telegram 连接器 | 是 | 骨架 | Charles 未落地 |
| 7.10.3 | Discord 连接器 | 是 | 骨架 | Charles 未落地 |
| 7.10.4 | Kanban 看板 | 是 | 骨架 | Charles 未落地 |
| 7.10.5 | FeatureFlagsService | 是 | 无 | Charles 缺失 |

**验证方法**：对比 Connectors / Kanban

### P7.11 Sub-agent 对比

**Cline 实现**（extensions/tools/team/）：
- spawn_agent 工具
- subAgentTools 配置
- AgentConfigLoader
- multi-agent 协作

**Charles 实现**：
- Phase 27 已移除技能子 agent
- 遗留 sub_agent.py ~1650 行待清理

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.11.1 | spawn_agent 工具 | 是 | 无 | Charles 不实施 |
| 7.11.2 | subAgentTools 配置 | 是 | 无 | Charles 不实施 |
| 7.11.3 | AgentConfigLoader | 是 | 无 | Charles 不实施 |
| 7.11.4 | multi-agent 协作 | 是 | 无 | Charles 不实施 |
| 7.11.5 | 遗留 sub_agent.py | N/A | ~1650 行 | Charles 待清理 |

**验证方法**：对比 Sub-agent

### P7.12 Plugin / Marketplace 对比

**Cline 实现**（extensions/plugin/ + marketplace/）：
- plugin-loader
- plugin-sandbox
- Marketplace 远程插件安装

**Charles 实现**：
- 无 Plugin 系统
- 无 Marketplace

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.12.1 | Plugin 系统 | 是 | 无 | Charles 不实施 |
| 7.12.2 | plugin-loader | 是 | 无 | Charles 不实施 |
| 7.12.3 | plugin-sandbox | 是 | 无 | Charles 不实施 |
| 7.12.4 | Marketplace | 是 | 无 | Charles 不实施 |

**验证方法**：对比 Plugin / Marketplace

### P7.13 Cline Rules / Frontmatter / Workflows 对比

**Cline 实现**（user-instructions/）：
- cline-rules.ts
- frontmatter.ts
- rule-conditionals.ts
- external-rules.ts
- workflows.ts

**Charles 实现**（rules_loader.py）：
- rules 加载
- frontmatter 解析
- 无 rule-conditionals
- 无 external-rules
- 无 workflows

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.13.1 | cline-rules 加载 | 是 | 是 | 已对齐 |
| 7.13.2 | frontmatter 解析 | 是 | 是 | 已对齐 |
| 7.13.3 | rule-conditionals | 是 | 无 | Charles 缺失 |
| 7.13.4 | external-rules | 是 | 无 | Charles 不实施 |
| 7.13.5 | workflows | 是 | 无 | Charles 不实施 |
| 7.13.6 | globs 匹配 | 是 | 无 | Charles 缺失 |
| 7.13.7 | applyTo 字段 | 是 | 无 | Charles 缺失 |

**验证方法**：对比 Cline Rules

### P7.14 审批机制对比

**Cline 实现**（tool-approval.ts + presets.ts）：
- autoApprove 全局开关
- toolPolicies per-tool 配置
- requestToolApproval config 回调
- VSCode 原生审批 UI

**Charles 实现**（approval.py + hooks.py）：
- auto_approve 全局开关
- tool_policies per-tool 配置
- before_approval hook
- SSE + 前端弹窗
- approval_memory.json 持久化

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.14.1 | autoApprove 全局开关 | 是 | 是 | 已对齐 |
| 7.14.2 | toolPolicies per-tool | 是 | 是 | 已对齐 |
| 7.14.3 | 审批触发 | requestToolApproval 回调 | before_approval hook | 形式不同但等价 |
| 7.14.4 | 审批 UI | VSCode 原生 | SSE + 前端弹窗 | 形式不同但等价 |
| 7.14.5 | 审批记忆持久化 | 是 | approval_memory.json | 已对齐（Stage 9.6） |
| 7.14.6 | 跨会话审批记忆 | 是 | 是 | 已对齐 |

**验证方法**：对比审批机制

### P7.15 循环检测对比

**Cline 实现**（loop-detection.ts + mistake-tracker.ts + rules.ts）：
- LoopDetectionTracker（软阈值 3 / 硬阈值 5）
- 循环判定 key = tool_name + input hash
- MistakeTracker（5 类 mistake_type）
- safety rules 引擎

**Charles 实现**（loop_detection.py + mistake_tracker.py）：
- LoopDetectionTracker
- MistakeTracker

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.15.1 | LoopDetectionTracker | 是 | 是 | 已对齐 |
| 7.15.2 | 软/硬阈值 | 3/5 | 3/5 | 已对齐 |
| 7.15.3 | 循环判定 key | tool_name + input hash | tool_name + input hash | 已对齐 |
| 7.15.4 | MistakeTracker | 是 | 是 | 已对齐 |
| 7.15.5 | mistake_type 枚举 | 5 类 | 5 类 | 已对齐 |
| 7.15.6 | 每类独立阈值 | 是 | 是 | 已对齐 |
| 7.15.7 | safety rules 引擎 | 是 | 无 | Charles 缺失 |
| 7.15.8 | MistakeLimitExceeded | 是 | 是 | 已对齐 |

**验证方法**：对比循环检测

### P7.16 AbortController 对比

**Cline 实现**（agent-runtime.ts L424-470）：
- AbortController 类（signal + abort() + reason）
- throwIfAborted 调用点
- signal 透传到 model.stream + tool.execute

**Charles 实现**（abort.py + runtime.py）：
- AbortController 类（signal: asyncio.Event + abort() + reason）
- _throw_if_aborted 调用点
- signal 透传

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.16.1 | AbortController 类 | 是 | 是 | 已对齐 |
| 7.16.2 | signal 类型 | AbortSignal | asyncio.Event | 类型不同但语义等价 |
| 7.16.3 | abort() 副作用 | status + last_error + emit | status + last_error + emit | 已对齐（Stage 30.2） |
| 7.16.4 | throwIfAborted 调用点 | 多处 | 多处 | 已对齐 |
| 7.16.5 | signal 透传到 model.stream | 是 | 是 | 已对齐 |
| 7.16.6 | signal 透传到 tool.execute | 是 | 是 | 已对齐 |
| 7.16.7 | abort 时 kill 子进程 | 是 | 是 | 已对齐（Stage 30.3） |
| 7.16.8 | abort 时记录 lastError | 是 | 是 | 已对齐（Stage 30.2） |

**验证方法**：对比 AbortController

### P7.17 Turn Queue 对比

**Cline 实现**（pending-prompt-service.ts）：
- PendingPromptEntry
- delivery 枚举（queue / steer）
- enqueue / consume / consume_for_steer
- 状态持久化

**Charles 实现**（turn_queue.py）：
- PendingPromptEntry
- PendingPromptService

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.17.1 | PendingPromptEntry 字段 | 是 | 是 | 已对齐 |
| 7.17.2 | delivery 枚举 | queue / steer | queue / steer | 已对齐（Stage 30.1） |
| 7.17.3 | enqueue 入队 | 是 | 是 | 已对齐 |
| 7.17.4 | consume 消费 | 是 | 是 | 已对齐 |
| 7.17.5 | consume_for_steer | 是 | 是 | 已对齐 |
| 7.17.6 | queue 自动启动新 run | 是 | 前端触发 | Charles 简化 |
| 7.17.7 | 状态持久化 | 是 | 内存 | Charles 简化 |
| 7.17.8 | SSE 事件通知 | 是 | pending_prompts_updated | 已对齐 |

**验证方法**：对比 Turn Queue

### P7.18 事件系统对比

**Cline 实现**（agent-runtime.ts emit + agent.ts 事件类型）：
- 12 种事件类型
- EventEmitter.subscribe 返回 unsubscribe
- emit 同步 vs 异步

**Charles 实现**（events.py）：
- 事件类型常量
- EventEmitter 类

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.18.1 | 事件类型枚举 | 12 种 | 12 种 | 已对齐 |
| 7.18.2 | AgentEvent 字段 | 是 | 是 | 已对齐 |
| 7.18.3 | subscribe 返回 unsubscribe | 是 | 是 | 已对齐 |
| 7.18.4 | emit 同步 vs 异步 | 同步 | 同步 | 已对齐 |
| 7.18.5 | listener 异常处理 | 不影响其他 | 不影响其他 | 已对齐 |
| 7.18.6 | 事件顺序保证 | 是 | 是 | 已对齐 |
| 7.18.7 | snapshot 引用语义 | 引用 | 引用 | 已对齐 |
| 7.18.8 | run_failed vs run_finished 互斥 | 是 | 是 | 已对齐 |

**验证方法**：对比事件系统

### P7.19 nanobot 残留清理对比

**Cline 实现**：
- 无 nanobot 引用

**Charles 实现**：
- `agent/tools/base.py` L2/L11/L37/L188 仍有 nanobot 引用（F-base 差距）

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 7.19.1 | nanobot 引用清理 | 无 | 有（base.py） | F-base 差距 |
| 7.19.2 | 遗留 sub_agent.py | 无 | ~1650 行 | Charles 待清理 |
| 7.19.3 | 遗留 sub_agent_worker.py | 无 | 是 | Charles 待清理 |
| 7.19.4 | 遗留 server.py::_handle_sub_agent_event | 无 | 是 | Charles 待清理 |

**验证方法**：Grep nanobot 引用

### P7.20 整体对齐度评估

| 模块 | 对齐度 | 关键差距 |
|------|--------|---------|
| 顶层架构 | 95% | 单层 vs 四层（合理简化） |
| 核心引擎 | 95% | MistakeTracker safety rules 缺失 |
| 工具系统 | 90% | zod vs jsonschema / max_retries 缺失 |
| 技能系统 | 95% | skillsTimeoutMs 不可配置 / 白名单 2 形式 |
| System Prompt | 85% | A1 职责未分离 / L1 中文字段名 / L4 metadata 条件 / L5 标签格式 / M1 mode_notice / M2 user_input 包装 |
| Agent Prompt | 90% | 风格不同 / globs 缺失 |
| 上下文管理 | 95% | FileContextTracker 缺失 |
| 辅助系统 | 90% | Telemetry LoggerSink 缺失 / Connectors 未落地 |

**整体对齐度**：约 93%（含 prompt 构建层细节差距）

### P7.21 优先级矩阵

| 差距 ID | 模块 | 优先级 | 工作量 | 影响范围 |
|---------|------|--------|--------|---------|
| Q8 | MCP auto_approve | P1 | 30 行 | mcp.py |
| F-base | nanobot 清理 | P2 | 4 行 | base.py |
| M1 | mode_notice 机制 | P2 | 20 行 | state.py + server.py |
| M2 | user_input 包装下沉 | P2 | 15 行 | runtime.py |
| A1 | SystemPromptBuilder 职责分离 | P3 | 100 行 | context.py + charles_system_prompt.py |
| L1 | env 字段名英文 | P3 | 4 行 | charles_system_prompt.py |
| L4 | metadata provider 条件 | P3 | 10 行 | context.py |
| L5 | metadata 标签格式 | P3 | 4 行 | context.py |
| L6 | PLAN_MODE run_commands 描述 | P3 | 2 行 | plan_mode.py |
| L7 | MODE_TAG 移除工具名 | P3 | 2 行 | context.py |
| L8 | yolo base prompt | P3 | 50 行 | charles_system_prompt.py |
| S1 | skill 白名单 4 形式 | P3 | 20 行 | registry.py |
| S2 | skillsTimeoutMs 可配置 | P3 | 5 行 | skill_tool.py |
| L3-new | rule name 文件 stem | P3 | 0 | 合理差异 |

### P7.22 推荐执行顺序

```
Stage 1: A1 架构重构（最先执行，架构基础）
  └─ SystemPromptBuilder 职责分离为纯组装器 + 编排器

Stage 2: P1 + P2 补全（立即执行）
  ├─ Q8 MCP approval 对接（30 行）
  ├─ F-base nanobot 清理（4 行）
  ├─ M1 mode_notice 机制（20 行）
  └─ M2 user_input 包装下沉（15 行）

Stage 3: P3 语义优化（按需执行）
  ├─ L1 env 字段名英文
  ├─ L4 metadata provider 条件
  ├─ L5 metadata 标签格式
  ├─ L6 PLAN_MODE run_commands 描述
  ├─ L7 MODE_TAG 移除工具名
  ├─ L8 yolo base prompt
  ├─ S1 skill 白名单 4 形式
  └─ S2 skillsTimeoutMs 可配置
```

**预期结果**：
- Stage 1 完成后：架构分层对齐 Cline
- Stage 2 完成后：整体对齐度 93% → 96%
- Stage 3 完成后：整体对齐度 96% → 99%

### P7.23 对比计划执行建议

**执行方式**：
- 每个大阶段（Phase 1-7）独立可执行
- 每个小阶段（P1.1 / P2.1 ...）可独立对比
- 对比结果输出到 `CLINE_DIFF_V2/phase_<X>.<Y>_<name>.md`

**对比流程**：
1. 读取 Cline 源码对应位置
2. 读取 Charles 源码对应位置
3. 逐项填写对比表
4. 标注一致性等级
5. 给出修复建议
6. 评估优先级

**对比工具**：
- Grep + Read 静态对比
- 构造测试用例动态验证
- 打印 system prompt 抓取
- 边界测试

---

## 十、附录

### 附录 A：Cline 源码位置索引

| 模块 | Cline 源码位置 |
|------|---------------|
| 类型系统 | `sdk/packages/shared/src/agent.ts` |
| 主循环 | `sdk/packages/agents/src/agent-runtime.ts` L595-794 |
| 流式组装 | `sdk/packages/agents/src/agent-runtime.ts` L965-1058 |
| AbortController | `sdk/packages/agents/src/agent-runtime.ts` L424-470 |
| 工具系统 | `sdk/packages/core/src/extensions/tools/` |
| 工具执行器 | `sdk/packages/core/src/extensions/tools/executors/` |
| 技能系统 | `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` |
| 上下文压缩 | `sdk/packages/core/src/extensions/context/compaction*.ts` |
| Budget Projection | `sdk/packages/core/src/extensions/context/budget-projection/` |
| System Prompt | `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` |
| Base Prompt | `sdk/packages/shared/src/prompt/system.ts` |
| Format | `sdk/packages/shared/src/prompt/format.ts` |
| Cline Rules | `sdk/packages/core/src/extensions/config/cline-rules.ts` |
| Frontmatter | `sdk/packages/core/src/extensions/config/frontmatter.ts` |
| Rule Conditionals | `sdk/packages/core/src/extensions/config/rule-conditionals.ts` |
| 文件 Hooks | `apps/vscode/src/core/hooks/` |
| MCP | `sdk/packages/core/src/extensions/mcp/` |
| Provider | `sdk/packages/core/src/services/llms/` |
| 会话存储 | `sdk/packages/core/src/services/storage/sqlite-session-store.ts` |
| Checkpoint | `apps/vscode/src/core/controller/checkpoints/` |
| Telemetry | `sdk/packages/core/src/services/telemetry/` |
| 循环检测 | `sdk/packages/core/src/runtime/safety/loop-detection.ts` |
| MistakeTracker | `sdk/packages/core/src/runtime/safety/mistake-tracker.ts` |
| Turn Queue | `sdk/packages/core/src/runtime/turn-queue/pending-prompt-service.ts` |

### 附录 B：Charles 源码位置索引

| 模块 | Charles 源码位置 |
|------|-----------------|
| 类型系统 | `agent/types.py` |
| 主循环 | `agent/runtime.py` |
| 流式组装 | `agent/runtime.py::_generate_assistant_message` |
| AbortController | `agent/abort.py` |
| 工具系统 | `agent/tools/base.py` + `agent/tools/__init__.py` |
| 工具执行器 | `agent/tools/*.py` |
| 技能系统 | `agent/skills/loader.py` + `agent/skills/registry.py` + `agent/skills/skill_tool.py` |
| 上下文压缩 | `agent/context.py` |
| Budget Projection | `agent/budget_policy.py` + `agent/context.py::_project_future_usage` |
| System Prompt | `agent/context.py::SystemPromptBuilder` |
| Base Prompt | `agent/prompts/charles_system_prompt.py` |
| Cline Rules | `agent/rules_loader.py` |
| 文件 Hooks | `agent/file_hooks/` |
| MCP | `agent/mcp/` |
| Provider | `agent/providers/` |
| 会话存储 | `agent/session.py` |
| Checkpoint | `agent/file_checkpoint.py` |
| Telemetry | `agent/telemetry.py` |
| 循环检测 | `agent/loop_detection.py` |
| MistakeTracker | `agent/mistake_tracker.py` |
| Turn Queue | `agent/turn_queue.py` |

### 附录 C：历史计划关系

| 历史计划 | 状态 | 本计划关系 |
|---------|------|-----------|
| AGENT_MIGRATION_PLAN（Phase 1-27） | 已完成 | 历史归档 |
| AGENT_PHASE28_PLAN（Phase 28+） | 已完成 | 历史归档 |
| AGENT_PHASE30_PLAN（Phase 30-33） | 已完成 | 历史归档 |
| AGENT_PROMPT_FIX_PLAN（P1-P5） | 已完成 | 历史归档 |
| AGENT_CLINE_COMPARISON_PLAN（A-Z 26 阶段） | 已完成 | 历史归档，本计划扩展 |
| AGENT_FINAL_ALIGNMENT_PLAN（Stage 34+） | 进行中 | 本计划为其提供对比基础 |
| **AGENT_COMPARISON_PLAN_V2（本计划）** | **进行中** | **最新对比计划，7 大阶段 130+ 小阶段** |

### 附录 D：与历史计划的差异

| 维度 | 历史计划 | 本计划 V2 |
|------|---------|----------|
| 对比视角 | 1-2 个（功能 + 实现） | 7 个（功能 + 实现 + Prompt 组件 + Prompt 风格 + Agent Prompt + Skill Prompt + 辅助系统） |
| 阶段数 | 26 个 | 7 大阶段，130+ 小阶段 |
| 对比深度 | 模块级 | 函数级 + 字段级 + Prompt 段落级 |
| Prompt 对比 | 部分覆盖 | 完整覆盖（system + agent + skill） |
| 形式风格对比 | 弱 | 强（标签格式 + 字段名语言 + 条件注入） |
| 一致性等级 | 简单 | 6 级（完全一致 / 弱对齐 / 缺失 / 额外 / 语义不等价 / 风格差异） |
| 优先级矩阵 | 无 | 有（P1/P2/P3 + 工作量 + 影响范围） |

### 附录 E：为什么每次对比结果不同

用户反馈"每次对比都有不一样的发现"，原因如下：

1. **对比视角不同**：
   - 功能层看"有没有功能 X"
   - 实现层看"函数逻辑是否一致"
   - Prompt 组件层看"段落是否存在、顺序是否一致"
   - Prompt 风格层看"标签格式、字段名语言、措辞风格"
   - 一个功能可能"已实现"（功能层）但"Prompt 风格不同"（风格层）

2. **粒度不同**：
   - 功能层看"有没有 metadata 注入" → 有 → 通过
   - 组件层看"metadata 段在 system prompt 第几位" → 顺序偏移 → 差距
   - 风格层看"metadata 用什么标签" → `<charles_metadata>` vs `# Workspace Configuration` → 差距

3. **因此每次新视角的对比都会发现上一视角看不到的细节差距**：
   - v1（功能层）：整体对齐度 95%
   - v2（+实现层）：整体对齐度 93%
   - v3（+Prompt 组件层）：整体对齐度 90%
   - v4（+Prompt 风格层）：整体对齐度 88%
   - 本计划 V2 纳入全部 7 个视角，给出最全面的对比

---

**计划结束。按 Phase 1 → 2 → 3 → 4 → 5 → 6 → 7 顺序逐步执行对比，每个小阶段独立可执行。**
