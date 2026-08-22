# Phase 3.8 工具审批机制对比（toolPolicies + before_approval）

> 对比范围：Cline `ToolPolicy` + `toolPolicies` + `requestToolApproval` 回调 + hub 审批流程 与 Charles `tool_policies` dict + `before_approval` hook + `approval.py` 审批流程 + `approval_memory.json` 持久化的实现差异。
>
> Cline 源码：
> - `sdk/packages/shared/src/llms/tools.ts` L7-85（`ToolPolicy` / `ToolApprovalRequest` / `ToolApprovalResult` 接口）
> - `sdk/packages/shared/src/agent.ts` L435-439（`AgentRuntimeConfig.toolPolicies` / `requestToolApproval` 字段）
> - `sdk/packages/shared/src/session/runtime-config.ts` L66-68（`SessionExecutionConfig.toolPolicies`）
> - `sdk/packages/core/src/extensions/tools/presets.ts` L137-158（`createToolPoliciesWithPreset` yolo 预设）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L118-146（`isToolEnabledByPolicies` / `filterToolsByPolicies`）
> - `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` L57-76（同上的 builder 副本）
> - `sdk/packages/core/src/runtime/host/local-runtime-host.ts` L613-635（`requestToolApproval` 回调包装）
> - `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts`（hub 端审批流程：`requestToolApproval` / `resolvePendingApproval` / `cancelPendingApprovals` / `handleApprovalRespond`）
> - `sdk/packages/core/src/hub/server/hub-server-transport.ts` L351（路由 `approval.requested` 事件）
> - `sdk/packages/core/src/hub/runtime-host/hub-runtime-host.ts` L2081-2083（hub 客户端处理 `approval.requested` 事件）
> - `sdk/packages/core/src/cron/runner/cron-runner.ts` L62-81（`buildToolPolicies` 构建 cron 策略）
> - `sdk/packages/core/src/cline-core/automation.ts` L123-127（`autoApproveTools` 布尔值转 `*: { autoApprove }`）
> - `sdk/packages/core/src/hub/server/handlers/session-handlers.ts` L359-365 / L619-627（`autoApproveTools` → `toolPolicies` 转换）
> - `sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts` L100-141（子代理继承 `toolPolicies` / `requestToolApproval`）
>
> Charles 源码：
> - `agent/approval.py`（审批管理：`ApprovalEntry` + `_pending_approvals` + `_session_auto_approved` + `_persistent_auto_approved` + 持久化文件 `agent_config/approval_memory.json`）
> - `agent/approval_policy.py`（`AutoApprovalPolicy` 默认 `before_approval` 钩子实现，含只读/写/危险命令分类）
> - `agent/hooks.py` L239-266（`BeforeApprovalContext` / `BeforeApprovalResult`）L313（`AgentHooks.before_approval` 字段）
> - `agent/runtime.py` L1446-1594（`_prepare_tool_execution` 策略检查 + 审批触发）L1646-1765（`_request_tool_approval` 审批流程）
> - `agent/runtime.py` L1596-1644（`_get_mcp_tool_policy_override` MCP per-tool 策略注入）
> - `agent/types.py` L536（`AgentRuntimeConfig.tool_policies`）L541（`AgentRuntimeConfig.auto_approve`）
> - `agent/tools/base.py` L96-103（`BaseTool.requires_approval` 属性）
> - `agent/tools/apply_patch.py` L201-203 / `file_tools.py` L202-204 / `editor.py` L180-182 / `run_commands.py` L113-115（覆盖 `requires_approval=True`）
> - `agent/server.py` L1261-1328（`POST /api/chat/approve`）L1386-1450（`GET/DELETE /api/chat/approval_memory` 持久化记忆管理）
> - `agent/server.py` L481-484（注册 `AutoApprovalPolicy` 作为 `before_approval` 钩子）
> - `agent/mcp/registry.py` L68-78（`MCPToolPolicy`）L126-128（`_tool_policies` 缓存）L201-220（加载 `tool_policies` 段）L317-340（`get_tool_policy` 查询）

---

## 一、执行摘要

Cline 与 Charles 在工具审批机制上采用了**两种等价但形态不同的方案**：

1. **Cline 采用回调驱动 + hub 事件流模式**：`AgentRuntimeConfig.requestToolApproval` 是 host 注入的回调函数；runtime 在工具执行前调用此回调，回调内部由 host（如 VS Code 扩展或 hub server）展示审批 UI 并返回 `ToolApprovalResult`。Hub server 通过 `approval.requested` / `approval.resolved` 事件 + `approval.respond` 命令实现客户端↔服务端双向通信。策略层仅依赖 `toolPolicies: Record<string, ToolPolicy>` 字典（含 `enabled` / `autoApprove` 两个字段），无独立的审批前钩子。

2. **Charles 采用 asyncio.Event + SSE 推送 + hook 拦截模式**：`agent/approval.py` 维护全局 `_pending_approvals` 字典，每个审批请求创建 `ApprovalEntry` 含 `asyncio.Event`；runtime 通过 `_request_tool_approval` 创建 entry、emit `approval_request` SSE 事件、`await entry.event.wait()` 挂起；前端 `POST /api/chat/approve` 设置结果并 `event.set()` 唤醒。策略层在 `tool_policies` 字典之外，额外提供 `before_approval` 钩子（`AutoApprovalPolicy` 默认实现）和 `BaseTool.requires_approval` 工具自声明属性。

3. **关键差异点**：
   - **审批触发机制**：Cline 是 `requestToolApproval` 回调（host 负责展示 UI）；Charles 是 `before_approval` hook + SSE 事件 + `/api/chat/approve` 端点（server 负责展示 UI）。形式不同但等价。
   - **审批结果持久化**：Cline 跨会话记忆依赖 host 的 `globalState`（VS Code 扩展 API），无服务端持久化文件；Charles 实现了独立的 `agent_config/approval_memory.json` 持久化文件 + 三级查询优先级（会话级内存 > 全局持久化 > 默认逻辑），**Charles 在持久化上更强**。
   - **审批前自动决策**：Cline 无独立的 `before_approval` 钩子，自动决策通过 `beforeTool` hook 返回 `policy` 覆盖实现；Charles 有独立的 `before_approval` 钩子点 + `AutoApprovalPolicy` 内置实现（含只读/写/危险命令分类），**Charles 在自动决策上更精细**。
   - **MCP 工具审批**：Cline 通过统一的 `toolPolicies` 配置（`use_mcp_tool` 作为普通工具名）；Charles 在 `mcp/registry.py` 实现 `MCPToolPolicy` per-tool 粒度策略（server_name + tool_name 二维 key），并在 `_get_mcp_tool_policy_override` 中转换为 runtime 策略，**Charles 的 MCP 策略粒度更细**。
   - **审批超时**：Cline 无硬编码超时（依赖 `cancelPendingApprovals` 在会话结束时取消）；Charles 硬编码 `APPROVAL_TIMEOUT_SECONDS = 300.0` 秒超时自动拒绝，**Charles 的超时机制更明确**。
   - **工具自声明审批需求**：Cline 无 `requires_approval` 概念，完全由 `toolPolicies.autoApprove` 控制；Charles 有 `BaseTool.requires_approval` 属性，工具自声明是否需要审批，再由策略层覆盖，**Charles 多一层工具自声明**。

4. **nanobot 残留**：P3.8 核心文件中 `approval.py` / `approval_policy.py` / `hooks.py` / `runtime.py`（审批相关段落）/ `mcp/registry.py` 均无 nanobot 残留；`server.py` L2 / L4 / L28-29 有 4 处 docstring 残留（"对标 Cline server + nanobot routes/chat.py" / "用 AgentRuntime 替换 nanobot" / "对标 nanobot: routes/chat.py _sse_generator()"），属注释残留，不在 P3.8 审批逻辑范围内但位于审批端点所在文件。

5. **一致性总体评估**：**高**。两种方案在功能上完全等价（都能实现 per-tool 策略、自动批准、用户审批、拒绝跳过、超时取消），核心差距在于 Charles 额外增强了持久化记忆、自动决策钩子、MCP per-tool 策略三个维度，这些是 Charles 的功能增强而非缺陷。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.8.1 | policies 配置格式 | `toolPolicies: Record<string, ToolPolicy>`（TS 接口，强类型） | `tool_policies: dict[str, dict[str, Any]]`（Python dict，弱类型） | 中（语言习惯） | Cline 强类型更安全，Charles 灵活但需运行时校验 |
| 3.8.2 | enabled 字段 | `ToolPolicy.enabled?: boolean`（@default true） | `dict["enabled"]: bool`（合并逻辑同 Cline） | 高 | 已对齐，`enabled is False` → skip 工具 |
| 3.8.3 | autoApprove 字段 | `ToolPolicy.autoApprove?: boolean`（@default true） | `dict["autoApprove"]: bool`（合并逻辑同 Cline） | 高 | 已对齐，`autoApprove is False` → 走审批 |
| 3.8.4 | 全局通配符 `*` | `toolPolicies["*"]` 作为 global policy，与 per-tool 合并 | `tool_policies.get("*", {})` 同语义合并 | 高 | 已对齐，合并顺序 global → per-tool 一致 |
| 3.8.5 | 审批触发机制 | `requestToolApproval` 回调（host 注入） | `before_approval` hook + `approval.py` 流程 | 中（形式不同） | Cline 由 host 负责 UI；Charles 由 server 负责 UI |
| 3.8.6 | 审批请求结构 | `ToolApprovalRequest`（含 sessionId/agentId/conversationId/iteration/toolCallId/toolName/input/policy） | `ApprovalEntry`（含 tool_call_id/tool_name/input/session_id/event/result/created_at） | 中 | Charles 缺 agentId/conversationId/iteration/policy 字段，但功能等价 |
| 3.8.7 | 审批结果结构 | `ToolApprovalResult { approved: boolean, reason?: string }` | `entry.result: "approved" / "denied"` + reason 字符串 | 高 | 语义等价 |
| 3.8.8 | 审批结果持久化 | host `globalState`（VS Code 扩展 API，无服务端文件） | `agent_config/approval_memory.json`（服务端原子写入） | 低（Charles 增强） | **Charles 额外增强**：服务端持久化 + 原子写入 |
| 3.8.9 | 跨会话审批记忆 | host globalState（依赖 host 实现） | `_persistent_auto_approved` set + 持久化文件 | 高 | 已对齐（Stage 9.6 完成） |
| 3.8.10 | 会话级审批记忆 | host autoApprovalSettings.actions（VS Code 端） | `_session_auto_approved` dict[session_id → set[tool_name]] | 高 | 已对齐（Stage 5.6 完成） |
| 3.8.11 | 审批 UI 形式 | VS Code 原生对话框（host 实现） | SSE `approval_request` 事件 + 前端弹窗 + `/api/chat/approve` 端点 | 中（形式不同） | 形式不同但等价 |
| 3.8.12 | 审批超时 | 无硬编码超时（依赖 `cancelPendingApprovals` 会话结束取消） | `APPROVAL_TIMEOUT_SECONDS = 300.0` 秒，`asyncio.wait_for` 自动拒绝 | 低（Charles 增强） | **Charles 额外增强**：硬编码 5 分钟超时 |
| 3.8.13 | 审批 deny 后行为 | 返回 `{ approved: false }`，runtime 将工具结果标记为 denied | 返回拒绝原因字符串作为 `skip_reason`，工具结果含 error | 高 | 已对齐，工具被 skip 不执行 |
| 3.8.14 | 审批 cancel 处理 | `cancelPendingApprovals(filter, reason)` 批量取消 + emit `approval.resolved` 事件 | `cancel_pending_approvals_for_session(session_id)` 批量设置 denied | 高 | 已对齐，会话结束时清理 |
| 3.8.15 | MCP 工具审批 | `toolPolicies["use_mcp_tool"]` 统一配置 | `MCPRegistry._tool_policies[(server, tool)]` per-tool 粒度 + `_get_mcp_tool_policy_override` 转换 | 低（Charles 增强） | **Charles 额外增强**：MCP per-tool 粒度策略 |
| 3.8.16 | 审批前自动决策钩子 | 无独立钩子，通过 `beforeTool` hook 返回 `policy` 覆盖实现 | 独立 `before_approval` 钩子点 + `AutoApprovalPolicy` 内置实现 | 低（Charles 增强） | **Charles 额外增强**：独立审批前钩子 |
| 3.8.17 | 自动决策规则 | 无内置规则（host 自行实现） | `AutoApprovalPolicy`：READ_ONLY_TOOLS 自动批准 / WRITE_TOOLS 走审批 / run_commands 按命令分类（readonly/deny/write） | 低（Charles 增强） | **Charles 额外增强**：内置命令分类规则 |
| 3.8.18 | 工具自声明审批需求 | 无（完全由 `toolPolicies.autoApprove` 控制） | `BaseTool.requires_approval` 属性（默认 False，写工具覆盖为 True） | 中（Charles 多一层） | Charles 工具自声明 + 策略覆盖双层 |
| 3.8.19 | 策略合并顺序 | global `*` → per-tool（`session-runtime-orchestrator.ts` L122-128） | global `*` → per-tool → MCP per-tool → hook policy_override（`runtime.py` L1562） | 高（Charles 多 MCP 层） | Charles 多 MCP per-tool 层，符合 Q8 设计 |
| 3.8.20 | Yolo 预设 | `createToolPoliciesWithPreset("yolo")` 预填充 `*: { enabled, autoApprove }` | 无 yolo 预设（依赖 `auto_approve: bool` 全局开关） | 中 | Charles 用 `auto_approve=True` 全局开关等价 |
| 3.8.21 | autoApproveTools 布尔开关 | `ChatStartSessionRequest.autoApproveTools: boolean`（转 `*: { autoApprove: true }`） | `AgentRuntimeConfig.auto_approve: bool = False`（全局开关） | 高 | 已对齐，布尔开关 → 策略字典 |
| 3.8.22 | 子代理审批继承 | `spawn-agent-tool.ts` 显式传 `toolPolicies` + `requestToolApproval` 给子代理 | 无 spawn_agent 工具（Phase 27 移除） | — | Charles 不实施子代理，N/A |
| 3.8.23 | 审批记忆管理 API | host UI 自行管理（无服务端 API） | `GET /api/chat/approval_memory` + `DELETE /api/chat/approval_memory[/{tool_name}]` | 低（Charles 增强） | **Charles 额外增强**：服务端管理 API |
| 3.8.24 | 非交互会话审批 | `state.interactive === false` → 自动拒绝 + 原因 | 无显式非交互会话检查（所有会话都走相同流程） | 低 | **Charles 缺失**，但实际场景无非交互模式 |

**一致性总评**：24 项中，高一致性 11 项、中一致性 6 项、低一致性 7 项（其中 6 项为 Charles 增强、1 项为 Charles 缺失）。低一致性项中 6 项是 Charles 相对 Cline 的功能增强（持久化、超时、MCP per-tool、before_approval 钩子、自动决策规则、管理 API），1 项是 Charles 缺失（非交互会话审批拒绝），不影响核心功能。

---

## 三、重点差距详细说明

### 差距 1：审批触发机制 — 回调 vs SSE+Event（3.8.5 / 3.8.11）

**Cline 实现**（`shared/src/agent.ts` L437-439 + `local-runtime-host.ts` L613-635 + `approval-handlers.ts`）：

Cline 的审批流程是**回调驱动**的：

1. `AgentRuntimeConfig.requestToolApproval?: (request: ToolApprovalRequest) => Promise<ToolApprovalResult>` 是一个可选回调函数，由 host（VS Code 扩展 / hub client）在创建 runtime 时注入。
2. Runtime 在工具执行前调用此回调，回调内部由 host 负责：
   - VS Code 扩展：弹出原生对话框，用户点击批准/拒绝
   - Hub 模式：`approval-handlers.ts` 的 `requestToolApproval(ctx, request)` 创建 `approvalId`，emit `approval.requested` 事件，返回 `Promise` 等待客户端 `approval.respond` 命令
3. 回调返回 `ToolApprovalResult { approved, reason }`，runtime 据此决定是否执行工具。

关键代码（`local-runtime-host.ts` L613-635）：
```typescript
requestToolApproval: bootstrap.requestToolApproval
    ? async (request) => {
            const requestToolApproval = bootstrap.requestToolApproval;
            const liveSession = this.sessions.get(sessionId);
            if (liveSession) {
                await this.markTurnPending(liveSession);
            }
            try {
                if (!requestToolApproval) {
                    return { approved: false, reason: "Tool approval callback is not configured." };
                }
                return await requestToolApproval(request);
            } finally {
                const currentSession = this.sessions.get(sessionId);
                if (currentSession?.status === "pending") {
                    await this.markTurnRunning(currentSession);
                }
            }
        }
    : undefined,
```

**Charles 实现**（`approval.py` + `runtime.py` L1646-1765 + `server.py` L1261-1328）：

Charles 的审批流程是**事件驱动 + 协程挂起**的：

1. `runtime._request_tool_approval` 调用 `request_approval()` 在全局 `_pending_approvals` 字典中创建 `ApprovalEntry`（含 `asyncio.Event`）
2. Runtime emit `approval_request` SSE 事件（通过 `STATUS_NOTICE` 转发）到前端
3. Runtime `await asyncio.wait_for(entry.event.wait(), timeout=300)` 挂起协程
4. 前端显示审批弹窗，用户点击后 `POST /api/chat/approve`
5. Server 端 `set_approval_result(tool_call_id, result)` 设置 `entry.result` 并 `entry.event.set()`
6. Runtime 被唤醒，读取结果决定是否执行工具

关键代码（`runtime.py` L1717-1765）：
```python
entry = request_approval(
    tool_call_id=tool_call.tool_call_id,
    tool_name=tool_call.tool_name,
    input=input_value if isinstance(input_value, dict) else {},
    session_id=self.config.session_id or "",
)
approval_event = AgentEvent(
    type=STATUS_NOTICE,
    snapshot=self.snapshot(),
    notice=f"approval_request from {tool_call.tool_name}",
    metadata={
        "type": "approval_request",
        "tool_call_id": tool_call.tool_call_id,
        "tool_name": tool_call.tool_name,
        "input": input_value if isinstance(input_value, dict) else {},
    },
)
await self._emit(approval_event)
try:
    await asyncio.wait_for(entry.event.wait(), timeout=APPROVAL_TIMEOUT_SECONDS)
except asyncio.TimeoutError:
    clear_approval(tool_call.tool_call_id)
    return f"工具 {tool_call.tool_name} 审批超时（{int(APPROVAL_TIMEOUT_SECONDS)} 秒）"
```

**影响**：
- 两种方案功能等价，都能实现"runtime 挂起 → 用户决策 → 唤醒 runtime"。
- Cline 的回调模式更灵活（host 可以自由决定 UI 形式），但要求 host 主动注入回调。
- Charles 的 SSE+Event 模式更自包含（server 自带 UI 推送和接收端点），无需 host 注入。
- Charles 的方案额外硬编码了 300 秒超时，避免永久挂起；Cline 依赖 host 超时或会话取消。

**建议**：保留 Charles 现状。SSE+Event 方案是 Web 服务端场景的最佳实践，无需退化为回调模式。

### 差距 2：审批结果持久化 — host globalState vs 服务端文件（3.8.8 / 3.8.9 / 3.8.10 / 3.8.23）

**Cline 实现**：

Cline 的跨会话审批记忆依赖 host 实现：
- VS Code 扩展使用 `context.globalState` API 持久化"始终允许此工具"的工具列表
- Hub 模式下，记忆存储在 hub 客户端（如 CLI / Web UI）的本地状态中
- 服务端（hub server）**不持久化**审批记忆，每次会话开始时由 host 注入

Cline 无服务端审批记忆管理 API，记忆的查看/删除由 host UI 自行实现。

**Charles 实现**（`approval.py` L75-315 + `server.py` L1386-1450）：

Charles 实现了**三级查询优先级 + 服务端持久化文件**：

1. **会话级内存**：`_session_auto_approved: dict[str, set[str]]`，会话结束后清理
2. **全局持久化**：`_persistent_auto_approved: set[str]`，懒加载自 `agent_config/approval_memory.json`
3. **默认逻辑**：走 `tool_policies` + `requires_approval` + `auto_approve` 决策

持久化文件格式（`approval.py` L82-89 注释）：
```json
{
  "version": 1,
  "tools": ["read_files", "search_codebase"],
  "updated_at": "2026-07-26T10:00:00Z"
}
```

写入采用 **tmpfile + os.replace 原子写入**（`approval.py` L140-174），避免崩溃导致数据损坏。

管理 API（`server.py`）：
- `GET /api/chat/approval_memory` — 列出所有持久化工具
- `DELETE /api/chat/approval_memory` — 清空所有持久化记忆
- `DELETE /api/chat/approval_memory/{tool_name}` — 删除单个工具

**影响**：
- Charles 的持久化方案**强于 Cline**：服务端原子写入、三级查询、独立管理 API。
- Cline 依赖 host 持久化，hub 模式下若客户端不持久化，记忆会丢失。
- Charles 的方案适合无状态客户端（如纯 Web UI），所有状态集中在服务端。

**建议**：保留 Charles 现状。这是 Charles 相对 Cline 的功能增强。

### 差距 3：审批前自动决策 — beforeTool policy 覆盖 vs 独立 before_approval 钩子（3.8.16 / 3.8.17）

**Cline 实现**：

Cline 无独立的 `before_approval` 钩子点。自动决策通过 `beforeTool` hook 返回 `policy` 覆盖实现（`shared/src/agent.ts` L300-306 的 `AgentBeforeToolResult.policy` 字段）：

```typescript
export interface AgentBeforeToolResult {
    skip?: boolean;
    stop?: boolean;
    reason?: string;
    policy?: ToolPolicy;  // 覆盖 toolPolicies 决策
}
```

Host 可注册 `beforeTool` hook，在工具执行前根据工具名/输入返回 `policy: { autoApprove: true }` 跳过审批，或 `policy: { enabled: false }` 禁用工具。Cline **不内置任何自动决策规则**，完全由 host 自行实现。

**Charles 实现**（`hooks.py` L239-266 + `approval_policy.py` + `runtime.py` L1688-1715 + `server.py` L481-484）：

Charles 有独立的 `before_approval` 钩子点，在 `_request_tool_approval` 入口调用（在创建审批请求之前）：

```python
@dataclass
class BeforeApprovalResult:
    decision: str | None = None  # None / "approved" / "denied"
    reason: str | None = None
```

`AutoApprovalPolicy` 是默认实现（`approval_policy.py`），通过 `AGENT_AUTO_APPROVAL` 环境变量控制模式：

- `off` / `0` / `false`：关闭自动审批，全部走用户审批
- `readonly`（默认）：只读工具自动批准，写工具走审批，危险命令自动拒绝
- `all`：自动批准所有工具

工具级别规则（`approval_policy.py` L33-54）：
- `READ_ONLY_TOOLS`：`file_read / read_files / list_files / search_codebase / web_search / fetch_web_content / ask_question / attempt_completion / todo_write / switch_to_plan_mode / switch_to_act_mode / submit_and_exit` → 自动批准
- `WRITE_TOOLS`：`file_write / editor / apply_patch` → 走用户审批

命令级别规则（`approval_policy.py` L61-101）：
- `_READ_ONLY_COMMAND_PATTERNS`：`cat / ls / git status / pip list` 等 → 自动批准
- `_DENY_COMMAND_PATTERNS`：`rm -rf / mkfs / dd if=/dev/ / format C:` 等 → 自动拒绝
- `_WRITE_COMMAND_PATTERNS`：`mv / rm / git push / pip install / python *.py` 等 → 走用户审批

**影响**：
- Charles 的 `before_approval` 钩子**职责更单一**（只做审批决策，不修改工具输入/不跳过工具），与 `before_tool` 钩子分离。
- Cline 的 `beforeTool` 钩子承担多重职责（跳过工具 / 修改输入 / 覆盖策略 / 中止运行），自动审批只是其中一种用法。
- Charles 内置 `AutoApprovalPolicy`，开箱即用；Cline 需 host 自行实现自动决策规则。

**建议**：保留 Charles 现状。独立 `before_approval` 钩子 + 内置 `AutoApprovalPolicy` 是 Charles 的功能增强，符合"开箱即用"设计目标。

### 差距 4：MCP 工具审批粒度 — 统一配置 vs per-tool 二维 key（3.8.15 / 3.8.19）

**Cline 实现**：

Cline 对 MCP 工具的审批通过统一的 `toolPolicies` 配置：
- `toolPolicies["use_mcp_tool"]` 配置整个 `use_mcp_tool` 工具的策略
- 无法区分"server A 的 tool X 自动批准，server B 的 tool Y 需审批"这类 per-MCP-tool 粒度
- 若需要 per-MCP-tool 策略，需 host 在 `requestToolApproval` 回调中根据 `request.input` 解析 server_name/tool_name 自行决策

**Charles 实现**（`mcp/registry.py` L68-78 + L126-128 + L201-220 + L317-340 + `runtime.py` L1596-1644）：

Charles 在 `mcp_servers.yaml` 中支持 `tool_policies` 段，per-MCP-tool 粒度配置：

```yaml
tool_policies:
  - server: filesystem
    tool: read_file
    enabled: true
    auto_approve: true
  - server: filesystem
    tool: write_file
    enabled: true
    auto_approve: false
```

`MCPRegistry` 加载时缓存为 `_tool_policies: dict[tuple[str, str], MCPToolPolicy]`（key 是 `(server_name, tool_name)` 二元组）。

Runtime 在 `_prepare_tool_execution` 中检测到 `use_mcp_tool` 调用时，调用 `_get_mcp_tool_policy_override(tool_call)`：
1. 从 `tool_call.input` 解析 `server_name` / `tool_name`
2. 调用 `MCPRegistry.get_tool_policy(server, tool)` 查询 MCP 策略
3. 转换为 runtime 的 `autoApprove` / `enabled` 字段
4. 合并到 `policy_override`（优先级：global → per-tool → MCP per-tool → hook override）

**影响**：
- Charles 的 MCP per-tool 策略**粒度更细**：可以精确控制"filesystem server 的 read_file 自动批准，write_file 需审批"。
- Cline 的统一配置只能控制 `use_mcp_tool` 整体，无法区分具体 MCP 工具。
- Charles 的方案更适合多 MCP server 场景（不同 server 的工具风险等级不同）。

**建议**：保留 Charles 现状。MCP per-tool 策略是 Charles 的功能增强，符合 Q8 设计目标。

### 差距 5：工具自声明审批需求 — 无 vs requires_approval 属性（3.8.18）

**Cline 实现**：

Cline 的 `AgentTool` 接口**无 `requiresApproval` 字段**。工具是否需要审批完全由外部 `toolPolicies.autoApprove` 控制：
- `toolPolicies["run_commands"].autoApprove === false` → 需审批
- `toolPolicies["run_commands"].autoApprove === true`（或未设）→ 不审批
- 工具自身不声明审批需求

**Charles 实现**（`base.py` L96-103 + `apply_patch.py` L201-203 / `file_tools.py` L202-204 / `editor.py` L180-182 / `run_commands.py` L113-115）：

Charles 的 `BaseTool` 有 `requires_approval` 属性，默认 `False`，写工具覆盖为 `True`：

```python
@property
def requires_approval(self) -> bool:
    """是否需要用户审批 — Phase 19 新增，对标 Cline tool-approval

    True 时工具执行前会挂起等待用户批准（除非 auto_approve=True）。
    危险工具（file_write / run_commands / editor / apply_patch）应覆盖为 True。
    只读工具（read_files / search_codebase / list_files）保持默认 False。
    """
    return False
```

审批决策逻辑（`runtime.py` L1559-1583）：
1. 若 `tool_policies` 显式设 `autoApprove`（True 或 False）→ 按策略决策
2. 若策略未显式设 `autoApprove` → 回退到 `tool.requires_approval and not config.auto_approve`
3. 即：工具自声明 + 全局开关 + 策略覆盖三层合并

**影响**：
- Charles 的 `requires_approval` 提供了**工具自声明**能力，工具开发者可以在工具类内部标注风险等级。
- Cline 完全依赖外部配置，工具开发者无法在工具定义中表达审批需求。
- Charles 的方案更适合工具由开发者维护、策略由用户配置的场景（职责分离）。
- Cline 的方案更适合工具集动态加载、策略统一管理的场景（集中配置）。

**建议**：保留 Charles 现状。`requires_approval` 是工具自声明 + 策略覆盖的双层设计，符合 Charles 的 OOP 风格。

### 差距 6：审批超时 — 无硬编码 vs 300 秒（3.8.12）

**Cline 实现**：

Cline 的 `approval-handlers.ts` 中 `requestToolApproval` 函数返回 `new Promise(resolve => ...)`，**无超时机制**。Promise 一直挂起，直到：
- 客户端发送 `approval.respond` 命令（`handleApprovalRespond` 处理）
- 会话结束时 `cancelPendingApprovals` 批量取消（返回 `{ approved: false, cancelled: true, reason }`）

若客户端不响应且会话不结束，审批请求会永久挂起（占用内存）。

**Charles 实现**（`approval.py` L47 + `runtime.py` L1745-1753）：

Charles 硬编码 `APPROVAL_TIMEOUT_SECONDS = 300.0`（5 分钟），使用 `asyncio.wait_for` 自动超时：

```python
try:
    await asyncio.wait_for(
        entry.event.wait(),
        timeout=APPROVAL_TIMEOUT_SECONDS,
    )
except asyncio.TimeoutError:
    clear_approval(tool_call.tool_call_id)
    return f"工具 {tool_call.tool_name} 审批超时（{int(APPROVAL_TIMEOUT_SECONDS)} 秒）"
```

超时后自动清理 entry 并返回拒绝原因（作为 `skip_reason`），工具不执行。

**影响**：
- Charles 的超时机制**更健壮**：避免用户离开后审批请求永久挂起。
- Cline 依赖会话取消清理，若会话长时间不结束，挂起的审批请求会累积。
- 5 分钟超时是合理的用户体验阈值（既给用户足够思考时间，又避免无限等待）。

**建议**：保留 Charles 现状。硬编码超时是防御性设计，符合 Charles 的"避免永久挂起"原则。

### 差距 7：非交互会话审批拒绝 — 有 vs 无（3.8.24）

**Cline 实现**（`approval-handlers.ts` L13-22）：

Cline 在 `requestToolApproval` 入口检查 `state.interactive === false`，非交互会话直接返回拒绝：

```typescript
const state = ctx.sessionState.get(sessionId);
if (state?.interactive === false) {
    return {
        approved: false,
        reason: "Tool approval requires an interactive session, but this session is non-interactive.",
    };
}
```

这避免了 cron job / 自动化场景下因等待用户审批而挂起。

**Charles 实现**：

Charles 无显式的非交互会话检查。所有会话都走相同的审批流程。Charles 的 cron 场景（`cron_runner.py`）通过 `auto_approve=True` 全局开关跳过审批，而非会话级 interactive 标记。

**影响**：
- Charles 缺失非交互会话检查，理论上若 cron job 未设 `auto_approve=True`，会触发审批请求并挂起 300 秒超时。
- 实际影响小：Charles 的 cron runner 默认设 `auto_approve=True`（`buildToolPolicies` 等价逻辑），不会触发审批。
- 但缺少防御层：若配置错误（cron job 忘记设 auto_approve），会浪费 5 分钟超时。

**建议**：不强制补齐。Charles 的 cron 场景通过配置层（`auto_approve=True`）规避了此问题，引入 interactive 标记会增加状态管理复杂度。若未来支持非交互会话（如 headless 模式），可考虑增加此检查。

---

## 四、nanobot 残留检查

针对 P3.8 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.8 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/approval.py` | **0** | 无 | 审批管理无 nanobot 引用 |
| `agent/approval_policy.py` | **0** | 无 | 自动审批策略无 nanobot 引用 |
| `agent/hooks.py`（审批钩子段落） | **0** | 无 | `BeforeApprovalContext` / `BeforeApprovalResult` / `before_approval` 字段无 nanobot 引用 |
| `agent/runtime.py`（审批段落 L1446-1765） | **0** | 无 | `_prepare_tool_execution` / `_request_tool_approval` / `_get_mcp_tool_policy_override` 无 nanobot 引用 |
| `agent/types.py`（`tool_policies` / `auto_approve` 字段） | **0** | 无 | 配置字段无 nanobot 引用 |
| `agent/tools/base.py`（`requires_approval` 属性） | **0** | 无 | 已在 P3.1 清理完毕 |
| `agent/mcp/registry.py`（`MCPToolPolicy` / `get_tool_policy`） | **0** | 无 | MCP 策略无 nanobot 引用 |
| `agent/server.py`（审批端点 + 审批钩子注册） | **4** | 注释残留 | 见 4.2 详述 |

### 4.2 残留分类

#### 注释残留（4 处，均在 `agent/server.py`）

**位置 1**：`agent/server.py` L2
```python
"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py
```

**位置 2**：`agent/server.py` L4
```python
提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。
```

**位置 3**：`agent/server.py` L28-29
```python
对标 nanobot:
    - routes/chat.py _sse_generator() + _StreamCollectorHook
```

**性质**：全部为 docstring 中的历史溯源说明，标注 Charles SSE 服务端同时对标了 Cline server 和历史 nanobot routes/chat.py。这些注释位于 `server.py` 的文件级 docstring，**不在审批端点（`/api/chat/approve` / `/api/chat/approval_memory`）的实现段落内**，但 `server.py` 是审批端点所在文件。

**处理建议**：将 L2 改为 `"""SSE 服务端 — 对标 Cline server`，L4 删除 `用 AgentRuntime 替换 nanobot` 段落，L28-29 删除 `对标 nanobot:` 段落。属于 P2 级别清理，不阻塞 P3.8 对比结论。注意：这些残留属于 P1.7（前端后端交互）或 P2.x（事件系统）范围的清理任务，P3.8 仅负责审批机制对比。

#### 实现逻辑残留（0 处）

P3.8 核心文件中**未发现任何从 nanobot 直接移植的审批实现逻辑**：

- `approval.py` 的 `ApprovalEntry` + `_pending_approvals` + `asyncio.Event` 机制是 Charles 原创设计，对标 Cline `tool-approval.ts`（文件头明确标注"对标 Cline tool-approval.ts + auto-approve 机制"）。
- `approval_policy.py` 的 `AutoApprovalPolicy` + 命令分类正则是 Charles 原创设计，无 nanobot 对应物。
- `hooks.py` 的 `BeforeApprovalContext` / `BeforeApprovalResult` 对标 Cline `AgentBeforeToolResult.policy`（注释标注"对标 Cline 审批钩子"），但独立为 `before_approval` 钩子点是 Charles 的设计增强。
- `runtime.py` 的 `_request_tool_approval` 对标 Cline `requestDesktopToolApproval`（注释标注"对标 Cline requestDesktopToolApproval"），实现逻辑是 Charles 原创的 asyncio.Event 方案。
- `mcp/registry.py` 的 `MCPToolPolicy` 对标 Cline `shared/llms/tools.ts ToolPolicy`（L69 注释标注），per-tool 二维 key 是 Charles 的 Q8 设计增强。

### 4.3 P3.8 范围外但相关的残留

以下文件有 nanobot 残留，但属于其他 P 阶段的对比范围，不在 P3.8 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|---------------|-----------|
| `agent/session.py` | 2 | P1.x（会话管理） |
| `agent/context.py` | 1 | P1.x（上下文管理） |
| `agent/tools/file_tools.py` | 7 | P3.x（FileWriteTool 专项） |
| `agent/tools/exec_tool.py` | 12 | P3.x（exec_tool 专项，已废弃） |
| `agent/tools/web_tool.py` | 7 | P3.x（WebSearchTool 专项） |
| `agent/providers/qwen.py` | 3 | P4.x（Qwen provider 专项） |

这些残留全部为 docstring / 行内注释，属历史溯源标注，不影响审批机制层的对比结论。

---

## 五、修复建议

### 建议 1：清理 `server.py` 文件头 nanobot 注释残留 [P2]

**文件**：`agent/server.py`
**位置**：L2 / L4 / L28-29
**修改**：
- L2：`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py` → `"""SSE 服务端 — 对标 Cline server`
- L4：删除 `提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。` 中的 `用 AgentRuntime 替换 nanobot` 段落
- L28-29：删除 `对标 nanobot:` 及其子项

**理由**：统一为"对标 Cline"溯源风格，与 `approval.py` / `approval_policy.py` / `hooks.py`（均无 nanobot 残留）保持一致。不影响功能。注意此清理属于文件级 docstring 维护，不仅涉及审批端点，应在 P1.7 或专门清理批次中统一处理。

### 建议 2：不强制补齐非交互会话审批拒绝 [P3 不修复]

**理由**：
- Charles 的 cron 场景通过 `auto_approve=True` 全局开关规避了审批挂起。
- Charles 无显式的 interactive session 标记，引入会增加状态管理复杂度。
- 实际影响小：配置正确的 cron job 不会触发审批。

**保留条件**：若未来支持 headless 模式（如 CI/CD 集成），应在 `AgentRuntimeConfig` 增加 `interactive: bool` 字段，并在 `_request_tool_approval` 入口检查。

### 建议 3：保留持久化审批记忆方案 [P0 不变]

**理由**：Charles 的 `approval_memory.json` + 三级查询优先级 + 原子写入 + 管理 API 是相对 Cline 的功能增强，应予保留。

### 建议 4：保留 `before_approval` 独立钩子 [P0 不变]

**理由**：独立 `before_approval` 钩子职责单一（只做审批决策），与 `before_tool` 钩子（跳过工具 / 修改输入 / 覆盖策略）分离，符合关注点分离原则。`AutoApprovalPolicy` 内置实现提供了开箱即用的命令分类规则。

### 建议 5：保留 MCP per-tool 策略粒度 [P0 不变]

**理由**：`MCPToolPolicy` 的 `(server_name, tool_name)` 二维 key 粒度比 Cline 的统一 `toolPolicies["use_mcp_tool"]` 更精细，适合多 MCP server 场景。这是 Charles Q8 设计的核心增强。

### 建议 6：保留 `requires_approval` 工具自声明属性 [P0 不变]

**理由**：`BaseTool.requires_approval` 提供工具自声明 + 策略覆盖的双层设计，工具开发者可在工具类内部标注风险等级，用户通过 `tool_policies` 覆盖。符合 Charles 的 OOP 风格。

### 建议 7：保留 300 秒审批超时 [P0 不变]

**理由**：硬编码超时是防御性设计，避免用户离开后审批请求永久挂起。5 分钟阈值合理（既给用户思考时间，又避免无限等待）。

---

## 六、验证方法建议

### 验证方法 1：策略字段映射检查

对比 Cline `ToolPolicy` 与 Charles `tool_policies` dict 的字段对应：

```powershell
# Cline 侧（shared/src/llms/tools.ts L7-18）
# 字段：enabled / autoApprove

# Charles 侧（types.py L536 + runtime.py L1560-1565）
# 字段：enabled / autoApprove（dict key）
```

**验证命令**：
```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern 'merged\.get\("enabled"\)|merged\.get\("autoApprove"\)'
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\types.py" -Pattern "tool_policies|auto_approve"
```

### 验证方法 2：审批流程端到端检查

确认 Charles 审批流程完整（创建 → emit → 等待 → 设置结果 → 唤醒 → 清理）：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "request_approval|set_approval_result|get_approval_result|clear_approval|asyncio\.wait_for"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "def request_approval|def set_approval_result|def get_approval_result|def clear_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern 'approve_tool|/approve'
```

### 验证方法 3：持久化记忆文件操作检查

确认 Charles 持久化记忆的加载/保存/管理 API 完整：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "_load_persistent_memory|_save_persistent_memory|mark_auto_approved|is_auto_approved|list_persistent_auto_approved|remove_persistent_auto_approved|clear_persistent_auto_approved"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "approval_memory"
```

### 验证方法 4：before_approval 钩子注册检查

确认 `AutoApprovalPolicy` 已注册为 `before_approval` 钩子：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "AutoApprovalPolicy|before_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\hooks.py" -Pattern "BeforeApprovalContext|BeforeApprovalResult|before_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "before_approval|_request_tool_approval"
```

### 验证方法 5：MCP per-tool 策略检查

确认 MCP 工具策略的加载、查询、注入流程：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\registry.py" -Pattern "MCPToolPolicy|_tool_policies|get_tool_policy|tool_policies"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "_get_mcp_tool_policy_override|mcp_policy_override"
```

### 验证方法 6：requires_approval 工具自声明检查

确认写工具覆盖了 `requires_approval=True`：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\apply_patch.py" -Pattern "requires_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\file_tools.py" -Pattern "requires_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\editor.py" -Pattern "requires_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "requires_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\base.py" -Pattern "requires_approval"
```

### 验证方法 7：审批超时验证

确认 Charles 硬编码 300 秒超时：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "APPROVAL_TIMEOUT_SECONDS"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "APPROVAL_TIMEOUT_SECONDS|asyncio\.wait_for"
```

### 验证方法 8：nanobot 残留扫描

```powershell
# P3.8 核心文件扫描（应仅 server.py 有 4 处文件级 docstring 残留）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval_policy.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\hooks.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\registry.py" -Pattern "nanobot" -CaseSensitive:$false
```

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/shared/src/llms/tools.ts` | L7-18 | `ToolPolicy` 接口（`enabled` / `autoApprove`） |
| `sdk/packages/shared/src/llms/tools.ts` | L46-85 | `ToolApprovalRequest` / `ToolApprovalResult` 接口 |
| `sdk/packages/shared/src/agent.ts` | L435-439 | `AgentRuntimeConfig.toolPolicies` / `requestToolApproval` 字段 |
| `sdk/packages/shared/src/session/runtime-config.ts` | L66-68 | `SessionExecutionConfig.toolPolicies` |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L137-158 | `createToolPoliciesWithPreset` yolo 预设生成 |
| `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` | L118-146 | `isToolEnabledByPolicies` / `filterToolsByPolicies` / `filterAvailableExtensionTools` |
| `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts` | L57-76 | `isToolEnabledByPolicies` / `filterToolsByPolicies`（builder 副本） |
| `sdk/packages/core/src/runtime/host/local-runtime-host.ts` | L613-635 | `requestToolApproval` 回调包装（markTurnPending / markTurnRunning） |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L9-46 | `requestToolApproval`：创建 approvalId + emit `approval.requested` + 等待 |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L48-60 | `resolvePendingApproval`：resolve promise |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L62-84 | `cancelPendingApprovals`：批量取消 + emit `approval.resolved` |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L86-133 | `handleApprovalRespond`：处理客户端 `approval.respond` 命令 |
| `sdk/packages/core/src/hub/server/hub-server-transport.ts` | L351 | 路由 `approval.requested` 事件到 handler |
| `sdk/packages/core/src/hub/runtime-host/hub-runtime-host.ts` | L2081-2083 | hub 客户端解析 `approval.requested` 事件的 policy 字段 |
| `sdk/packages/core/src/cron/runner/cron-runner.ts` | L62-81 | `buildToolPolicies`：cron 场景策略构建（默认 `*: { autoApprove: true }`） |
| `sdk/packages/core/src/cline-core/automation.ts` | L123-127 | `autoApproveTools` 布尔值转 `*: { autoApprove }` 策略 |
| `sdk/packages/core/src/hub/server/handlers/session-handlers.ts` | L359-365 / L619-627 | `autoApproveTools` → `toolPolicies` 转换逻辑 |
| `sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts` | L100-141 | 子代理继承 `toolPolicies` / `requestToolApproval` |
| `sdk/packages/core/src/extensions/tools/team/delegated-agent.ts` | L71-131 | 委托代理继承 `toolPolicies` / `requestToolApproval` |
| `sdk/packages/core/src/extensions/tools/team/configured-agent-tool.ts` | L51-180 | 配置化子代理继承 `toolPolicies` / `requestToolApproval` |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/approval.py` | L47 | `APPROVAL_TIMEOUT_SECONDS = 300.0`（5 分钟超时） |
| `agent/approval.py` | L50-69 | `ApprovalEntry` dataclass（含 `asyncio.Event`） |
| `agent/approval.py` | L73-92 | `_pending_approvals` / `_session_auto_approved` / `_persistent_auto_approved` 全局状态 |
| `agent/approval.py` | L95-174 | `_get_persist_file_path` / `_load_persistent_memory` / `_save_persistent_memory`（原子写入） |
| `agent/approval.py` | L177-227 | `mark_auto_approved` / `is_auto_approved`（三级查询优先级） |
| `agent/approval.py` | L230-315 | `list_auto_approved` / `clear_session_auto_approved` / `list_persistent_auto_approved` / `remove_persistent_auto_approved` / `clear_persistent_auto_approved` |
| `agent/approval.py` | L318-346 | `request_approval`：创建 entry 到 `_pending_approvals` |
| `agent/approval.py` | L349-373 | `set_approval_result`：设置 result + `event.set()` 唤醒 |
| `agent/approval.py` | L376-417 | `get_approval_result` / `clear_approval` / `get_pending_approval_meta` |
| `agent/approval.py` | L419-463 | `list_pending_approvals` / `cancel_pending_approvals_for_session` |
| `agent/approval_policy.py` | L33-54 | `READ_ONLY_TOOLS` / `WRITE_TOOLS` 工具分类集合 |
| `agent/approval_policy.py` | L61-101 | `_READ_ONLY_COMMAND_PATTERNS` / `_DENY_COMMAND_PATTERNS` / `_WRITE_COMMAND_PATTERNS` 命令分类正则 |
| `agent/approval_policy.py` | L108-136 | `_classify_command`：单条命令分类（readonly/deny/write） |
| `agent/approval_policy.py` | L139-224 | `AutoApprovalPolicy`：默认 `before_approval` 钩子实现 |
| `agent/hooks.py` | L239-266 | `BeforeApprovalContext` / `BeforeApprovalResult`（decision: None/"approved"/"denied"） |
| `agent/hooks.py` | L283 | `BeforeApprovalHook` 类型定义 |
| `agent/hooks.py` | L313 | `AgentHooks.before_approval` 字段 |
| `agent/hooks.py` | L339 / L360-361 / L374 / L388 | `HookBag.before_approval` 列表 + add/clear/is_empty |
| `agent/runtime.py` | L1446-1594 | `_prepare_tool_execution`：4 步流程（normalize → before_tool → policy check → approval check） |
| `agent/runtime.py` | L1543-1551 | MCP per-tool 策略注入（Stage 9.1 Q8） |
| `agent/runtime.py` | L1553-1567 | 策略三态语义检查（enabled=False → skip / autoApprove=False → ask） |
| `agent/runtime.py` | L1569-1583 | `requires_approval` + `auto_approve` 兜底逻辑 |
| `agent/runtime.py` | L1596-1644 | `_get_mcp_tool_policy_override`：MCP 策略转换 |
| `agent/runtime.py` | L1646-1765 | `_request_tool_approval`：5 步审批流程（auto_approved 检查 → before_approval hook → 创建 entry → emit → 等待） |
| `agent/types.py` | L536 | `AgentRuntimeConfig.tool_policies: dict[str, dict[str, Any]]` |
| `agent/types.py` | L541 | `AgentRuntimeConfig.auto_approve: bool = False` |
| `agent/tools/base.py` | L96-103 | `BaseTool.requires_approval` 属性（默认 False） |
| `agent/tools/apply_patch.py` | L201-203 | `requires_approval = True` |
| `agent/tools/file_tools.py` | L202-204 | `requires_approval = True`（FileWriteTool） |
| `agent/tools/editor.py` | L180-182 | `requires_approval = True` |
| `agent/tools/run_commands.py` | L113-115 | `requires_approval = True` |
| `agent/mcp/registry.py` | L68-78 | `MCPToolPolicy` dataclass（server_name/tool_name/enabled/auto_approve） |
| `agent/mcp/registry.py` | L126-128 | `_tool_policies: dict[tuple[str, str], MCPToolPolicy]` 缓存 |
| `agent/mcp/registry.py` | L201-220 | 加载 `tool_policies` 段（YAML 配置） |
| `agent/mcp/registry.py` | L317-340 | `get_tool_policy(server_name, tool_name)` 查询 |
| `agent/server.py` | L481-484 | 注册 `AutoApprovalPolicy` 作为 `before_approval` 钩子 |
| `agent/server.py` | L1261-1328 | `POST /api/chat/approve` 端点 |
| `agent/server.py` | L1386-1402 | `GET /api/chat/approval_memory` 列出持久化记忆 |
| `agent/server.py` | L1405-1422 | `DELETE /api/chat/approval_memory` 清空所有持久化记忆 |
| `agent/server.py` | L1425-1450 | `DELETE /api/chat/approval_memory/{tool_name}` 删除单个工具记忆 |

---

## 八、结论

P3.8 工具审批机制对比的核心结论：

1. **两种等价但形态不同的方案**：Cline 采用回调驱动（`requestToolApproval` 回调 + hub 事件流），Charles 采用事件驱动（`asyncio.Event` + SSE + `/api/chat/approve` 端点）。两种方案都能实现"runtime 挂起 → 用户决策 → 唤醒 runtime"的完整流程。

2. **核心功能已对齐**：`toolPolicies` per-tool 配置、`enabled` / `autoApprove` 字段、全局通配符 `*`、策略合并顺序（global → per-tool）、审批 deny 后 skip 工具、会话级审批记忆、跨会话审批记忆等核心功能在两侧都有对应实现。

3. **Charles 在 6 个维度上强于 Cline**（应予保留）：
   - **审批结果持久化**：服务端 `approval_memory.json` 原子写入 + 管理 API（Cline 依赖 host globalState）
   - **审批超时**：硬编码 300 秒超时自动拒绝（Cline 无硬编码超时）
   - **MCP per-tool 策略**：`(server_name, tool_name)` 二维 key 粒度（Cline 统一 `use_mcp_tool` 配置）
   - **审批前自动决策钩子**：独立 `before_approval` 钩子点 + `AutoApprovalPolicy` 内置实现（Cline 无独立钩子）
   - **自动决策规则**：内置 READ_ONLY_TOOLS / WRITE_TOOLS / 命令分类正则（Cline 无内置规则）
   - **审批记忆管理 API**：`GET/DELETE /api/chat/approval_memory`（Cline 无服务端 API）

4. **Charles 在 1 个维度上缺失**（建议不修复）：
   - **非交互会话审批拒绝**：Cline 检查 `state.interactive === false` 自动拒绝；Charles 无此检查，但 cron 场景通过 `auto_approve=True` 规避。

5. **Charles 多一层工具自声明**：`BaseTool.requires_approval` 属性提供工具自声明审批需求，与 `tool_policies` 策略层形成双层设计（Cline 完全由外部策略控制）。

6. **nanobot 残留**：P3.8 核心审批文件（`approval.py` / `approval_policy.py` / `hooks.py` / `runtime.py` 审批段落 / `mcp/registry.py`）均无 nanobot 残留；`server.py` 文件头有 4 处 docstring 残留（L2 / L4 / L28-29），属文件级历史溯源标注，不在审批逻辑段落内，应在文件级清理批次中统一处理。

**整体一致性等级**：**高**。P3.8 范围内无需阻塞性修复，建议 1（清理 `server.py` 文件头 nanobot 注释）为 P2 级别清理任务，应在 P1.7 或专门清理批次中处理。Charles 在审批机制上的 6 项功能增强应予保留，1 项缺失（非交互会话检查）建议不修复。
