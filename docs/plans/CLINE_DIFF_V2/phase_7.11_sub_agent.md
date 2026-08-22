# Phase 7.11 Sub-agent 对比

**对比主题**：Sub-agent 机制（子 agent 创建、工具集限制、上下文隔离、multi-agent 协作）
**验证方法**：Grep 搜索 `sub-agent` / `subagent` / `SubAgent` / `spawnAgent` / `spawn_agent` / `nanobot` 残留
**结论**：Charles 已在 Phase 27 移除 sub-agent 实现（源码删除），但仍存在大量注释残留、孤儿工具文件和 `__pycache__` 编译缓存。

---

## 一、Cline 实现概览

Cline 在 `extensions/tools/team/` 目录下提供完整的 sub-agent + multi-agent 协作框架，由 8 个核心源文件组成（不含测试）：

| 文件 | 行数 | 职责 |
|------|------|------|
| `spawn-agent-tool.ts` | 203 | `spawn_agent` 工具定义；主 agent 调用此工具委派任务给 sub-agent |
| `delegated-agent.ts` | 146 | `createDelegatedAgent()` 创建独立 `SessionRuntime`；区分 `subagent` / `teammate` 两种 kind |
| `configured-agent-config.ts` | 204 | AgentConfigLoader：从 YAML frontmatter 加载预配置 agent（name/description/tools/skills/providerId/modelId/maxIterations/systemPrompt） |
| `configured-agent-tool.ts` | — | 基于配置文件自动创建的 agent 工具 |
| `subagent-prompts.ts` | 41 | `buildSubAgentSystemPrompt()` / `buildTeammateSystemPrompt()` 构建隔离的系统提示词 |
| `multi-agent.ts` | — | `AgentTeamsRuntime` 多 agent 协调核心 |
| `team-tools.ts` | 916 | 17 个 team 工具（spawn_teammate / shutdown / status / task / run_task / cancel_run / list_runs / await_runs / send_message / broadcast / read_mailbox / mission_log / cleanup / create_outcome / attach_outcome_fragment / review_outcome_fragment / finalize_outcome / list_outcomes） |
| `runtime.ts` / `projections.ts` / `index.ts` | — | 运行时辅助、事件投影、 barrel 导出 |

### Cline sub-agent 三大机制

#### 1. 子 agent 创建（`spawn-agent-tool.ts` L117-202）

```typescript
export function createSpawnAgentTool(config: SpawnAgentToolConfig) {
  return createTool({
    name: "spawn_agent",
    execute: async (input, context) => {
      const subAgent = createDelegatedAgent({
        kind: "subagent",
        prompt: input.systemPrompt,
        configProvider: config.configProvider,
        tools,
        parentAgentId: context.agentId,
        abortSignal: context.signal,
        ...
      });
      const result = await subAgent.run(input.task);
      return { text: result.text, iterations, finishReason, usage };
    },
    timeoutMs: 300000,
  });
}
```

- 主 agent 通过 `spawn_agent` 工具委派任务
- 输入参数：`systemPrompt`（子 agent 行为定义）+ `task`（任务描述）
- 输出：`text` / `iterations` / `finishReason` / `usage`（token 消耗）

#### 2. 工具集限制（`SpawnAgentToolConfig`）

```typescript
export interface SpawnAgentToolConfig {
  subAgentTools?: AgentTool[];                    // 静态工具列表
  createSubAgentTools?: (input, context) => AgentTool[];  // 动态工具工厂
  toolPolicies?: Record<string, ToolPolicy>;     // 每个工具的策略
  requestToolApproval?: (request) => result;     // 工具调用审批回调
  ...
}
```

- 支持两种模式：静态 `subAgentTools` 列表 或 `createSubAgentTools()` 动态工厂
- `toolPolicies` 控制每个工具的执行策略
- `requestToolApproval` 允许对子 agent 工具调用做审批

#### 3. 上下文隔离（`delegated-agent.ts` L137-146）

```typescript
export function createDelegatedAgent(options): SessionRuntime {
  const config = buildDelegatedAgentConfig(options);
  const session = new SessionRuntime(config);  // 全新独立 SessionRuntime
  if (config.onEvent) session.subscribeEvents(config.onEvent);
  return session;
}
```

- 子 agent 拥有**独立的 `SessionRuntime` 实例**
- 独立的 `conversationId` / `agentId`
- 独立系统提示词（`buildSubAgentSystemPrompt` 调用 `buildClineSystemPrompt` 重新构建）
- 独立的事件流（`onEvent` 回调）
- 通过 `parentAgentId` 维持与主 agent 的父子关系

#### 4. Multi-agent 协作（`team-tools.ts`）

完整的 17 个 team 工具支持：
- **生命周期**：`team_spawn_teammate` / `team_shutdown_teammate` / `team_cleanup`
- **任务管理**：`team_task`（create/list/claim/complete/block）/ `team_run_task`（sync+async）/ `team_cancel_run` / `team_list_runs` / `team_await_runs`
- **通信**：`team_send_message` / `team_broadcast` / `team_read_mailbox` / `team_mission_log`
- **成果收敛**：`team_create_outcome` / `team_attach_outcome_fragment` / `team_review_outcome_fragment` / `team_finalize_outcome` / `team_list_outcomes`
- **状态查询**：`team_status`

---

## 二、Charles 实现概览

### 2.1 实际实现状态：**源码已删除**

| 项目 | 状态 |
|------|------|
| `agent/skills/sub_agent.py` | ❌ 源文件不存在（计划文件提到的"~1650 行待清理"已删除） |
| `agent/skills/sub_agent_worker.py` | ❌ 源文件不存在 |
| `agent/tools/attempt_completion.py` | ⚠️ 文件存在（96 行完整实现），但**未在任何位置注册** |
| `spawn_agent` 工具 | ❌ 无 |
| `subAgentTools` 配置 | ❌ 无 |
| `AgentConfigLoader` | ❌ 无 |
| multi-agent / team 工具 | ❌ 无 |

### 2.2 `__pycache__` 编译缓存残留

源码已删除但 Python 解释器缓存的 `.pyc` 文件仍残留在 `agent/skills/__pycache__/`：

| 文件 | 大小 |
|------|------|
| `sub_agent.cpython-310.pyc` | 已编译 |
| `sub_agent.cpython-311.pyc` | 已编译 |
| `sub_agent_worker.cpython-310.pyc` | 已编译 |

> 这些 `.pyc` 文件是历史构建产物，不影响运行（因 `.py` 源文件已删除，Python 不会加载它们），但属于文件系统残留。

### 2.3 孤儿工具：`attempt_completion.py`

`agent/tools/attempt_completion.py`（96 行）定义了 `AttemptCompletionTool` 类，实现完整的 `completes_run=True` 生命周期工具，但是：

- ❌ 未在 `agent/tools/__init__.py` 中导入
- ❌ 未在 `create_default_tools()` 中注册
- ❌ 未在 `agent/tools/routing.py` 中引用
- ❌ 没有任何 sub-agent runtime 会使用它（因 sub_agent.py 已删除）

该文件成为**孤儿工具**——代码完整但无任何调用路径。

---

## 三、对比矩阵

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 7.11.1 | `spawn_agent` 工具 | `team/spawn-agent-tool.ts` L117-202 | 无 | Charles 不实施；主 agent 无法委派 sub-agent |
| 7.11.2 | `subAgentTools` 配置 | `SpawnAgentToolConfig.subAgentTools` / `createSubAgentTools` | 仅注释残留（`skills/loader.py` L55） | Charles 仅有 `allowed_tools` frontmatter 字段（注释中提及"对标 Cline config.subAgentTools"），但无运行时机制使用它 |
| 7.11.3 | `AgentConfigLoader` | `team/configured-agent-config.ts` L151-204 `loadConfiguredAgentConfigs` | 无 | Charles 不实施；不支持从 YAML 文件加载预配置 agent |
| 7.11.4 | `createDelegatedAgent` | `team/delegated-agent.ts` L137-146 | 无 | Charles 不实施；无独立 `SessionRuntime` 创建逻辑 |
| 7.11.5 | 上下文隔离 | `SessionRuntime` 独立实例 + `buildSubAgentSystemPrompt` | 无 | Charles 不实施；skill 通过 `skill_tool.py` 在主上下文中注入指令（L7-8: "不创建子 agent，而是在主 agent 上下文中返回 skill 指令文本"） |
| 7.11.6 | Multi-agent 协作 | `team/multi-agent.ts` + `team-tools.ts`（17 个工具） | 无 | Charles 不实施；无 teammate / mailbox / outcome 机制 |
| 7.11.7 | `sub_agent.py` 源文件 | N/A | 已删除（仅 `.pyc` 残留） | Charles 已清理源码，但 `__pycache__` 中 3 个 `.pyc` 文件未清理 |
| 7.11.8 | `attempt_completion` 工具 | 通过 `spawn_agent` 返回 `result.text` | `agent/tools/attempt_completion.py` 孤儿文件（96 行） | Charles 工具文件存在但未注册；Cline 不需要此工具（直接通过 `spawn_agent` 返回结果） |

---

## 四、注释残留分类

### 4.1 注释残留（建议保留或修正——属文档性引用，非实现逻辑）

| 文件 | 行号 | 内容 | 性质 |
|------|------|------|------|
| `agent/skills/loader.py` | L15 | frontmatter 示例 `allowed_tools: # Phase 20: 子 agent 允许的工具列表` | 文档示例 |
| `agent/skills/loader.py` | L19 | frontmatter 示例 `- attempt_completion` | 文档示例 |
| `agent/skills/loader.py` | L53-55 | `allowed_tools: 技能允许子 agent 使用的工具名列表 / 对标 Cline config.subAgentTools` | 字段说明 |
| `agent/skills/loader.py` | L74 | `allowed_tools: list[str] \| None = None  # Phase 20: 子 agent 允许的工具列表` | 字段声明注释 |
| `agent/skills/registry.py` | L115 | "多 agent 场景下限制可用技能（如子 agent 只能用部分技能）" | 方法注释 |
| `agent/skills/skill_tool.py` | L7 | "执行: 不创建子 agent，而是在主 agent 上下文中返回 skill 指令文本" | 设计说明 |
| `agent/skills/skill_tool.py` | L18-22 | "这与 nanobot 的子 agent 隔离执行有本质区别" | 设计对比说明 |
| `agent/skills/skill_tool.py` | L123 | "不创建子 agent，直接返回 skill 指令字符串" | 方法注释 |
| `agent/tools/attempt_completion.py` | L2-22 | 模块 docstring 大量提及"子 agent" | 模块说明 |
| `agent/tools/attempt_completion.py` | L34-39 | 类 docstring 提及"子 agent 完成工具" | 类说明 |
| `agent/tools/attempt_completion.py` | L49 | 工具描述 "调用后子 agent 运行立即结束" | LLM 可见描述 |
| `agent/tools/attempt_completion.py` | L71 | "对标 Cline attempt_completion 工具的 lifecycle.completes_run" | 方法注释 |
| `agent/tools/todo_write.py` | L21-22 | "Cline .../spawn-agent-tool.ts 中子 agent 任务跟踪" | 对标说明 |
| `agent/runtime.py` | L2362 | 系统提示词 "你必须调用完成工具（如 attempt_completion 或 submit_and_exit）" | 系统提示词 |
| `agent/approval_policy.py` | L42 | `READ_ONLY_TOOLS` 集合包含 `"attempt_completion"` | 工具白名单 |
| `agent/types.py` | L160 | "用于 attempt_completion / submit_and_exit 等终止性工具" | 字段说明 |
| `agent/types.py` | L496 | "agent 必须调用 attempt_completion / submit_and_exit" | 字段说明 |
| `agent/tools/todo_write.py` | L189 | "所有任务已完成，可以调用 attempt_completion 或直接回复用户" | LLM 可见提示 |

### 4.2 实现逻辑残留（需评估是否清理）

| 文件 | 行号 | 内容 | 状态 |
|------|------|------|------|
| `agent/tools/attempt_completion.py` | 全文 96 行 | `AttemptCompletionTool` 完整类定义 | **孤儿工具**：未注册到任何 runtime；属于 sub-agent 机制的遗留实现 |
| `agent/skills/__pycache__/sub_agent.cpython-310.pyc` | — | 编译缓存 | **死文件**：源码已删，缓存无作用 |
| `agent/skills/__pycache__/sub_agent.cpython-311.pyc` | — | 编译缓存 | **死文件** |
| `agent/skills/__pycache__/sub_agent_worker.cpython-310.pyc` | — | 编译缓存 | **死文件** |
| `agent/skills/loader.py` | L74, L259-266 | `allowed_tools` 字段声明 + frontmatter 解析逻辑 | **死代码**：字段被解析但无运行时消费方（因 sub_agent.py 已删除） |
| `agent/approval_policy.py` | L42 | `READ_ONLY_TOOLS` 含 `"attempt_completion"` | **死配置**：工具未注册，白名单条目无意义 |

### 4.3 nanobot 残留（与 sub-agent 相关）

| 文件 | 行号 | 内容 | 性质 |
|------|------|------|------|
| `agent/skills/skill_tool.py` | L18 | "这与 nanobot 的子 agent 隔离执行有本质区别" | 设计对比注释 |

> 其他 nanobot 残留（`agent/skills/loader.py` L29-31、`agent/skills/registry.py` L20、`agent/tools/exec_tool.py` L8-19 等）属于工具/skills 体系的对标说明，与 sub-agent 无直接关系，归 P4.x skills 系列处理。

---

## 五、关键差异分析

### 5.1 架构路线差异

| 维度 | Cline | Charles |
|------|-------|---------|
| **skill 执行模式** | 双轨制：(a) `spawn_agent` 创建独立 sub-agent；(b) skills 工具在主上下文注入指令 | 单轨制：仅 skills 工具在主上下文注入指令（`skill_tool.py` L7: "不创建子 agent"） |
| **上下文隔离** | sub-agent 拥有独立 `SessionRuntime`、独立 conversationId、独立 system prompt | 无隔离——所有 skill 指令在主 agent 上下文执行 |
| **工具集限制** | `subAgentTools` / `createSubAgentTools` 可限制子 agent 工具集 | `allowed_tools` frontmatter 字段被解析但无运行时消费方 |
| **多 agent 协作** | 17 个 team 工具支持 teammate 生命周期、任务路由、mailbox 通信、outcome 收敛 | 无 |
| **结果回流** | `spawn_agent` 返回 `AgentResult`，主 agent 通过 `tool_result` 接收 | 不适用（无 sub-agent） |

### 5.2 Charles 的设计选择

Charles 在 `skill_tool.py` L18-22 明确记录了这一选择：

> 这与 nanobot 的"子 agent 隔离执行"有本质区别:
> - Cline skill 是"主上下文内的指令注入"
> - 不创建独立 runtime
> - 不限制工具集
> - 不用 attempt_completion 返回结果

即 Charles 主动放弃了 sub-agent 机制，统一采用"主上下文指令注入"模式。这是符合用户规则 1（之前完成正确的功能尽量不要修改）的设计决策——Phase 27 已移除技能子 agent。

### 5.3 残留清理建议（仅供后续参考，本阶段不执行）

| 残留类型 | 清理方式 | 优先级 |
|---------|---------|--------|
| `__pycache__/sub_agent*.pyc`（3 个） | 直接删除 | 低（无功能影响） |
| `agent/tools/attempt_completion.py`（96 行孤儿工具） | 删除文件 + 移除 `approval_policy.py` L42 引用 | 中（避免误导） |
| `agent/skills/loader.py` `allowed_tools` 字段 | 保留（属 frontmatter 规范，未来可能复用）或删除（无消费方） | 低 |
| 注释中的"子 agent"提及 | 保留（属设计对比文档）或修订为历史说明 | 低 |
| `agent/runtime.py` L2362 系统提示词 | 保留（attempt_completion 仍可能在用户自定义工具中出现）或改为仅 `submit_and_exit` | 低 |

---

## 六、验证方法与证据

### 6.1 Grep 搜索结果

```
# Charles agent 目录中 sub_agent / subagent / spawn_agent 的 .py 文件引用
agent/skills/loader.py:55:          对标 Cline config.subAgentTools — 每个技能可自定义工具集
agent/tools/attempt_completion.py:20:    - sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts
agent/tools/todo_write.py:21:    - Cline sdk-packages/core/src/extensions/tools/team/spawn-agent-tool.ts

# Glob 搜索 sub_agent*.py 源文件
No file found  (源码已删除)

# Glob 搜索 sub_agent* (含 .pyc)
agent/skills/__pycache__/sub_agent_worker.cpython-310.pyc
agent/skills/__pycache__/sub_agent.cpython-310.pyc
agent/skills/__pycache__/sub_agent.cpython-311.pyc
```

### 6.2 工具注册验证

`agent/tools/__init__.py` 的 `create_default_tools()` 函数（L48-112）注册了 16 个工具，**未包含** `AttemptCompletionTool`。`__all__` 导出列表（L115-136）也**未包含** `AttemptCompletionTool`。

### 6.3 Cline 文件存在性验证

`third_party/cline/sdk/packages/core/src/extensions/tools/team/` 目录下确认存在 14 个文件（含测试），核心源文件 8 个，sub-agent 机制完整。

---

## 七、结论

1. **Charles 已彻底移除 sub-agent 实现逻辑**——`sub_agent.py` / `sub_agent_worker.py` 源文件已删除，无运行时创建子 agent 的代码路径。
2. **Charles 不实施 Cline 的 sub-agent 机制**（7.11.1-7.11.4 全部为"Charles 不实施"），这是 Phase 27 的主动设计选择，采用"主上下文指令注入"替代"子 agent 隔离执行"。
3. **残留分两类**：
   - **注释残留**（约 18 处）：分散在 `skills/loader.py`、`skills/registry.py`、`skills/skill_tool.py`、`tools/attempt_completion.py`、`tools/todo_write.py`、`runtime.py`、`approval_policy.py`、`types.py`，多为设计对比说明或文档示例，不影响功能。
   - **实现逻辑残留**（3 类）：(a) `agent/tools/attempt_completion.py` 孤儿工具文件（96 行未注册）；(b) `agent/skills/__pycache__/` 下 3 个 `.pyc` 编译缓存；(c) `skills/loader.py` 中 `allowed_tools` 字段被解析但无运行时消费方。
4. **nanobot 残留**与 sub-agent 直接相关的仅 1 处（`skill_tool.py` L18），属设计对比注释。
5. **计划文件 L2789 "遗留 sub_agent.py ~1650 行待清理"已过时**——源码已删除，仅剩 `.pyc` 缓存和注释残留。
