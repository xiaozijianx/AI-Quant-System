# Phase 7.14 审批机制对比

**对比主题**：审批机制全链路（审批策略、审批触发、审批持久化、审批超时、MCP per-tool 策略、审批 UI、审批记忆管理）
**对比范围**：Cline 多端审批路径（SDK Core / Hub Server / Cline Hub Webview / CLI / VS Code 扩展）与 Charles 单端审批路径（SSE + asyncio.Event + 持久化文件）的实现差异。
**与 P3.8 的关联**：P3.8 聚焦"工具审批机制"作为工具执行链路的一个切片（24 项 per-tool 字段级对比）；P7.14 在系统架构层重新审视审批机制，**重点补充 P3.8 未深入的多端审批路径差异、Cline AutoApprovalSettings 持久化模型、Charles 三级查询优先级、Cline CLI 交互模式 `SAFE_AUTO_APPROVE_TOOL_NAMES` 白名单、Cline `tool-approval-denial.ts` 拒绝原因语义化等维度**。P7.14 在 P3.8 已确认的 6 项 Charles 增强基础上，进一步对照 Cline 多端实现，验证 Charles 单端方案的完整性。
**验证方法**：Grep 搜索 `approval` / `approve` / `autoApprove` / `auto_approve` / `alwaysAsk` / `requestToolApproval` / `nanobot` 残留；Read Cline 多端审批源码；对照 Charles `approval.py` / `approval_policy.py` / `hooks.py` / `runtime.py` / `server.py` / `mcp/registry.py`。
**结论**：Charles 在审批机制上的单端方案在功能上覆盖了 Cline 多端方案的核心能力（per-tool 策略、自动批准、用户审批、拒绝跳过、超时取消、持久化记忆、MCP per-tool），并在持久化、超时、自动决策、MCP 粒度 4 个维度上**强于** Cline。Cline 在多端协同（hub ↔ client 事件流、CLI TUI、Desktop IPC、VS Code globalState）和拒绝原因语义化（编辑工具特殊提示）2 个维度上**更精细**。Charles 单端方案适合 Web 服务端场景，Cline 多端方案适合跨平台 IDE/CLI/Hub 场景。

---

## 一、Cline 实现概览

Cline 的审批机制是**多端协同**的：SDK Core 定义接口与默认实现，各 host（VS Code 扩展 / Hub Server / Cline Hub Webview / CLI）注入自己的 `requestToolApproval` 回调或事件流，记忆持久化由 host 各自实现。

### 1.1 SDK Core 接口与默认实现

| 文件 | 行数 | 职责 |
|------|------|------|
| `sdk/packages/shared/src/llms/tools.ts` | L7-18 / L46-85 | `ToolPolicy` / `ToolApprovalRequest` / `ToolApprovalResult` 接口定义 |
| `sdk/packages/core/src/runtime/tools/tool-approval.ts` | 102 行 | `requestDesktopToolApproval` — 文件 IPC 默认实现（5 分钟超时 + 轮询 decision 文件） |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L137-158 | `createToolPoliciesWithPreset("yolo")` — yolo 预设填充 `*: { enabled, autoApprove }` |
| `sdk/packages/core/src/runtime/host/local-runtime-host.ts` | L613-635 | `requestToolApproval` 回调包装（前后 markTurnPending / markTurnRunning） |
| `sdk/packages/core/src/cron/runner/cron-runner.ts` | L61-81 | `buildToolPolicies` — cron 场景默认 `*: { autoApprove: true }` |

`ToolPolicy` 接口（`shared/src/llms/tools.ts` L7-18）：
```typescript
export interface ToolPolicy {
    enabled?: boolean;     // @default true
    autoApprove?: boolean; // @default true
}
```

`ToolApprovalRequest` 接口（`shared/src/llms/tools.ts` L46-80）：
```typescript
export interface ToolApprovalRequest {
    sessionId: string;
    agentId: string;
    conversationId: string;
    iteration: number;
    toolCallId: string;
    toolName: string;
    input: unknown;
    policy: ToolPolicy;
}
```

### 1.2 Hub Server 审批流（`approval-handlers.ts`）

| 函数 | 行 | 行为 |
|------|---|------|
| `requestToolApproval` | L9-46 | 创建 `approvalId` → emit `approval.requested` 事件 → 返回 Promise 等待客户端 `approval.respond` 命令 |
| `resolvePendingApproval` | L48-60 | 客户端响应后 resolve Promise |
| `cancelPendingApprovals` | L62-84 | 会话结束/中止时批量 cancel + emit `approval.resolved { cancelled: true }` |
| `handleApprovalRespond` | L86-133 | 处理客户端 `approval.respond` 命令，提取 approved/reason |

**关键设计**：
- L16-22：入口检查 `state.interactive === false` → 直接返回拒绝（非交互会话不挂起）
- **无硬编码超时**，依赖 `cancelPendingApprovals` 在会话结束时清理
- 通过 hub 事件流双向通信：server emit `approval.requested` → client 发 `approval.respond` 命令 → server emit `approval.resolved`

### 1.3 Cline Hub Webview 审批流（`cline-hub/src/server/approvals.ts`）

| 函数 | 行 | 行为 |
|------|---|------|
| `requestToolApprovalFromWebview` | L61-105 | 创建 `approvalId` → `setTimeout(10 * 60_000)` 超时 → emit `approval_request` 到 webview |
| `resolveToolApproval` | L10-27 | webview 响应后 resolve Promise + emit `approval_resolved` |
| `rejectPendingApprovalsForSession` | L29-39 | 按会话批量拒绝 |
| `rejectAllPendingApprovals` | L41-48 | 全局批量拒绝（如服务关闭） |
| `rejectOrphanedApprovals` | L50-59 | webview 断连时拒绝孤儿审批 |

**关键差异**：Cline Hub Webview 有 **10 分钟硬编码超时**（L86），不同于 Hub Server 的无超时设计。

### 1.4 CLI 交互审批流（`cli/src/runtime/interactive/approvals.ts` + `tool-policies.ts`）

```typescript
export function createInteractiveApprovalController(config: Config) {
    const autoApproveAllRef = {
        current: config.toolPolicies["*"]?.autoApprove !== false,
    };
    const baselineToolPolicies = cloneToolPolicies(config.toolPolicies);
    // ...
    const requestToolApproval = async (request) => {
        if (autoApproveAllRef.current) return { approved: true };
        if (request.policy?.autoApprove === true) return { approved: true };
        if (refs.tuiToolApprover.current) return refs.tuiToolApprover.current(request);
        return { approved: false };
    };
    // ...
}
```

`SAFE_AUTO_APPROVE_TOOL_NAMES` 白名单（`tool-policies.ts` L3-11）：
```typescript
const SAFE_AUTO_APPROVE_TOOL_NAMES = [
    "ask_followup_question",
    "ask_question",
    "fetch_web_content",
    "read_files",
    "search_codebase",
    "skills",
    "submit_and_exit",
];
```

CLI 模式下 `applyInteractiveAutoApproveOverride`：
- `enabled=true`：所有工具 `autoApprove=true`
- `enabled=false`：仅 `SAFE_AUTO_APPROVE_TOOL_NAMES` 中的工具保持 `autoApprove=true`，其余强制 `autoApprove=false`

CLI 还支持两种 UI（`cli/src/utils/approval.ts`）：
- `requestTerminalToolApproval`：TTY 交互式 `[y/N]` 提示
- `requestDesktopToolApprovalFromCore`：调用 SDK Core 文件 IPC（5 分钟超时）

### 1.5 VS Code 扩展持久化（`AutoApprovalSettings`）

`apps/vscode/src/shared/AutoApprovalSettings.ts`：
```typescript
export interface AutoApprovalSettings {
    version: number;            // 防竞态版本号
    enabled: boolean;           // Legacy，恒为 true
    favorites: string[];        // Legacy
    maxRequests: number;        // Legacy
    actions: {
        readFiles: boolean;
        editFiles: boolean;
        executeSafeCommands?: boolean;
        executeAllCommands?: boolean;
        useBrowser: boolean;
        useMcp: boolean;
    };
    enableNotifications: boolean;
}
```

`updateAutoApprovalSettings.ts` L11-37：通过 `controller.stateManager.setGlobalState("autoApprovalSettings", settings)` 持久化到 VS Code `globalState`，并按 `version` 字段防止并发覆盖。

### 1.6 拒绝原因语义化（`tool-approval-denial.ts`）

VS Code 扩展对编辑工具的拒绝原因特殊处理：
```typescript
export const EDIT_TOOL_APPROVAL_DENIAL_REASON =
    "The user denied this edit. The file was NOT modified and still contains its original content.";

export function buildToolApprovalDenialReason(toolName, feedback) {
    const denial = toolName && isEditTool(toolName)
        ? EDIT_TOOL_APPROVAL_DENIAL_REASON
        : DEFAULT_TOOL_APPROVAL_DENIAL_REASON;
    // ...
}
```

**设计动机**（注释 L12-16）：编辑工具拒绝后，模型若只看到用户反馈（如"改大一点"），会误以为编辑已应用，下次重试用错误的 `old_text` 匹配文件实际内容，导致状态漂移。明确告知"文件未被修改"可避免此问题。

---

## 二、Charles 实现概览

Charles 的审批机制是**单端自包含**的：server 端通过 `asyncio.Event` 挂起 runtime 协程，前端通过 SSE 接收审批请求并通过 `POST /api/chat/approve` 响应。所有状态集中在服务端。

### 2.1 核心文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `agent/approval.py` | 464 行 | 审批管理：`ApprovalEntry` + 全局字典 + 三级查询 + 持久化 + 管理 API |
| `agent/approval_policy.py` | 224 行 | `AutoApprovalPolicy` — 默认 `before_approval` 钩子（工具级 + 命令级分类） |
| `agent/hooks.py` | L239-266 / L313 | `BeforeApprovalContext` / `BeforeApprovalResult` / `AgentHooks.before_approval` |
| `agent/runtime.py` | L1446-1765 | `_prepare_tool_execution`（策略检查）+ `_request_tool_approval`（5 步审批流程）+ `_get_mcp_tool_policy_override`（MCP 策略转换） |
| `agent/server.py` | L481-484（注册钩子）/ L1261-1328（`POST /api/chat/approve`）/ L1386-1450（`GET/DELETE /api/chat/approval_memory`） |
| `agent/mcp/registry.py` | L67-82 / L126-128 / L201-220 / L317-340 | `MCPToolPolicy` + `_tool_policies` 缓存 + YAML 加载 + `get_tool_policy` 查询 |
| `agent/types.py` | L536 / L541 | `AgentRuntimeConfig.tool_policies` + `auto_approve` |
| `agent/tools/base.py` | L96-103 | `BaseTool.requires_approval` 属性（默认 False） |
| `agent/tools/apply_patch.py` / `file_tools.py` / `editor.py` / `run_commands.py` | — | 覆盖 `requires_approval=True` |

### 2.2 审批流程（`runtime.py` L1645-1765）

5 步流程：
1. **会话级记忆检查**（L1680-1685）：`is_auto_approved(session_id, tool_name)` 命中则直接返回 None（跳过审批）
2. **before_approval 钩子**（L1687-1714）：调用 `AutoApprovalPolicy.before_approval`，可返回 approved/denied/None
3. **创建审批请求**（L1716-1722）：`request_approval()` 在 `_pending_approvals` 字典中注册 `ApprovalEntry`
4. **emit 事件**（L1724-1736）：emit `STATUS_NOTICE` 事件，metadata 含 `approval_request` 类型 + tool_call_id + tool_name + input
5. **等待结果**（L1744-1764）：`await asyncio.wait_for(entry.event.wait(), timeout=300)` — 300 秒超时自动拒绝

### 2.3 三级查询优先级（`approval.py` L205-227）

```python
def is_auto_approved(session_id, tool_name) -> bool:
    # 1. 会话级内存优先
    tools = _session_auto_approved.get(session_id)
    if tools and tool_name in tools:
        return True
    # 2. 持久化记忆兜底
    return tool_name in _load_persistent_memory()
```

### 2.4 持久化方案（`approval.py` L75-315）

- **存储格式**：`agent_config/approval_memory.json`，含 `version` / `tools` / `updated_at`
- **原子写入**：tmpfile + `os.replace`（L140-174）
- **懒加载**：首次访问时读取，缓存到 `_persistent_auto_approved: set[str]`
- **管理 API**：`list_persistent_auto_approved` / `remove_persistent_auto_approved` / `clear_persistent_auto_approved`

### 2.5 MCP per-tool 策略（`mcp/registry.py` + `runtime.py` L1595-1643）

```python
@dataclass
class MCPToolPolicy:
    server_name: str
    tool_name: str
    enabled: bool = True
    auto_approve: bool = True
```

YAML 配置（`mcp_servers.yaml`）：
```yaml
tool_policies:
  - server: filesystem
    tool: read_file
    enabled: true
    auto_approve: true
```

`_get_mcp_tool_policy_override` 从 `tool_call.input` 解析 `server_name` / `tool_name`，调用 `MCPRegistry.get_tool_policy` 查询，转换为 runtime 的 `autoApprove` / `enabled` 字段。

### 2.6 自动审批策略（`approval_policy.py`）

`AutoApprovalPolicy` 通过 `AGENT_AUTO_APPROVAL` 环境变量控制模式：
- `off` / `0` / `false`：关闭自动审批
- `readonly`（默认）：只读工具/命令自动批准，写操作走审批，危险命令自动拒绝
- `all`：自动批准所有工具

工具级规则（L33-54）：
- `READ_ONLY_TOOLS`（12 个）：`file_read` / `read_files` / `list_files` / `search_codebase` / `web_search` / `fetch_web_content` / `ask_question` / `attempt_completion` / `todo_write` / `switch_to_plan_mode` / `switch_to_act_mode` / `submit_and_exit`
- `WRITE_TOOLS`（3 个）：`file_write` / `editor` / `apply_patch`

命令级规则（L61-101）：
- `_READ_ONLY_COMMAND_PATTERNS`：`cat` / `ls` / `git status` / `pip list` 等 → 自动批准
- `_DENY_COMMAND_PATTERNS`：`rm -rf` / `mkfs` / `dd if=/dev/` / `format C:` 等 → 自动拒绝
- `_WRITE_COMMAND_PATTERNS`：`mv` / `rm` / `git push` / `pip install` / `python *.py` 等 → 走用户审批

---

## 三、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 7.14.1 | autoApprove 全局开关 | `toolPolicies["*"].autoApprove` + CLI `autoApproveAllRef` + VS Code `AutoApprovalSettings.enabled` | `AgentRuntimeConfig.auto_approve: bool` + `AGENT_AUTO_APPROVAL=off/all/readonly` | 高 | 两侧均有全局开关，Charles 额外支持三态模式 |
| 7.14.2 | toolPolicies per-tool 配置 | `toolPolicies: Record<string, ToolPolicy>`（TS 强类型） | `tool_policies: dict[str, dict[str, Any]]`（Python dict） | 高 | 已对齐（P3.8 已确认） |
| 7.14.3 | 审批触发机制 | `requestToolApproval` 回调（host 注入） | `before_approval` hook + `approval.py` 流程 | 中（形式不同） | Cline 多端回调；Charles 单端 hook |
| 7.14.4 | 审批 UI 形式 | 4 端各自实现：VS Code 原生对话框 / Hub webview / CLI TUI `[y/N]` / Desktop 文件 IPC | SSE `approval_request` 事件 + 前端弹窗 + `POST /api/chat/approve` | 中（形式不同） | Cline 多端 UI；Charles 单端 Web UI |
| 7.14.5 | 审批记忆持久化 | VS Code `globalState`（`AutoApprovalSettings`，per-action 粒度） | `agent_config/approval_memory.json`（per-tool 粒度，原子写入） | 低（Charles 增强） | **Charles 增强**：服务端文件 + 原子写入 + 独立 API |
| 7.14.6 | 跨会话审批记忆 | VS Code globalState 跨会话保留；CLI/Hub 模式依赖 host | `_persistent_auto_approved` set + 持久化文件 | 高 | 已对齐（Stage 9.6 完成） |
| 7.14.7 | 会话级审批记忆 | VS Code `autoApprovalSettings.actions`（per-action） | `_session_auto_approved: dict[session_id → set[tool_name]]` | 高 | 已对齐（Stage 5.6 完成） |
| 7.14.8 | 审批超时 | Hub Server 无超时；Cline Hub Webview 10 分钟；Desktop IPC 5 分钟；CLI 无超时 | `APPROVAL_TIMEOUT_SECONDS = 300.0`（5 分钟）硬编码 | 高 | Charles 选择与 Desktop IPC 一致的 5 分钟 |
| 7.14.9 | 审批超时配置化 | 各端硬编码（5/10 分钟）或无超时 | 硬编码 300 秒（常量，需改源码调整） | 高 | 两侧均硬编码，配置化程度相当 |
| 7.14.10 | 非交互会话审批拒绝 | Hub Server `state.interactive === false` → 自动拒绝（`approval-handlers.ts` L16-22） | 无显式检查（cron 场景通过 `auto_approve=True` 规避） | 低 | **Charles 缺失**，但实际场景无影响（P3.8 已确认） |
| 7.14.11 | MCP 工具审批 | 统一 `toolPolicies["use_mcp_tool"]`（无 per-MCP-tool 粒度） | `MCPToolPolicy`（`(server_name, tool_name)` 二维 key） | 低（Charles 增强） | **Charles 增强**：MCP per-tool 粒度策略 |
| 7.14.12 | 审批前自动决策钩子 | 无独立钩子，通过 `beforeTool` hook 返回 `policy` 覆盖 | 独立 `before_approval` 钩子点 + `AutoApprovalPolicy` 内置实现 | 低（Charles 增强） | **Charles 增强**：独立钩子 + 内置规则 |
| 7.14.13 | 自动决策白名单 | CLI `SAFE_AUTO_APPROVE_TOOL_NAMES`（7 个：ask_followup_question / ask_question / fetch_web_content / read_files / search_codebase / skills / submit_and_exit） | `READ_ONLY_TOOLS`（12 个，含 switch_to_plan_mode / switch_to_act_mode / list_files / web_search / todo_write / attempt_completion） | 中 | Charles 白名单更宽，覆盖更多只读工具 |
| 7.14.14 | 自动决策黑名单 | 无内置黑名单（host 自行实现） | `_DENY_COMMAND_PATTERNS`（rm -rf / mkfs / dd / format / shutdown 等） | 低（Charles 增强） | **Charles 增强**：内置危险命令黑名单 |
| 7.14.15 | 命令分类自动决策 | 无内置命令分类 | `_classify_command` 三态分类（readonly / deny / write） | 低（Charles 增强） | **Charles 增强**：命令级三态分类 |
| 7.14.16 | 工具自声明审批需求 | 无（完全由 `toolPolicies.autoApprove` 控制） | `BaseTool.requires_approval` 属性（默认 False，写工具覆盖为 True） | 中（Charles 多一层） | Charles 工具自声明 + 策略覆盖双层 |
| 7.14.17 | 审批请求结构字段 | `ToolApprovalRequest`（含 sessionId/agentId/conversationId/iteration/toolCallId/toolName/input/policy） | `ApprovalEntry`（含 tool_call_id/tool_name/input/session_id/event/result/created_at） | 中 | Charles 缺 agentId/conversationId/iteration/policy 字段，但功能等价 |
| 7.14.18 | 审批结果结构 | `ToolApprovalResult { approved: boolean, reason?: string }` | `entry.result: "approved" / "denied"` + reason 字符串 | 高 | 语义等价 |
| 7.14.19 | 审批 deny 后行为 | 返回 `{ approved: false }`，runtime 标记工具结果为 denied | 返回拒绝原因字符串作为 `skip_reason`，工具结果含 error | 高 | 已对齐 |
| 7.14.20 | 审批 cancel 处理 | `cancelPendingApprovals` 批量 cancel + emit `approval.resolved { cancelled: true }` | `cancel_pending_approvals_for_session` 批量设置 denied + `event.set()` 唤醒 | 高 | 已对齐 |
| 7.14.21 | 拒绝原因语义化 | VS Code 扩展 `buildToolApprovalDenialReason` 对编辑工具特殊提示"文件未被修改" | 统一返回"工具 X 被用户拒绝"，无工具类型区分 | 低 | **Charles 缺失**：拒绝原因未区分工具类型 |
| 7.14.22 | Yolo 预设 | `createToolPoliciesWithPreset("yolo")` 返回 `*: { enabled, autoApprove }` + 所有默认工具 | 无 yolo 预设（依赖 `auto_approve=True` 全局开关） | 中 | Charles 用全局开关等价 |
| 7.14.23 | cron 场景默认策略 | `buildToolPolicies` 默认 `*: { autoApprove: true }`，list 模式 `*: { enabled: false, autoApprove: true }` + per-tool enabled | cron runner 默认 `auto_approve=True`（全局开关） | 高 | 已对齐 |
| 7.14.24 | autoApproveTools 布尔开关 | `ChatStartSessionRequest.autoApproveTools: boolean` → `*: { autoApprove: true }` | `AgentRuntimeConfig.auto_approve: bool` | 高 | 已对齐 |
| 7.14.25 | 审批记忆管理 API | 无服务端 API（host UI 自行管理 globalState） | `GET /api/chat/approval_memory` + `DELETE /api/chat/approval_memory[/{tool_name}]` | 低（Charles 增强） | **Charles 增强**：服务端管理 API |
| 7.14.26 | 审批事件流 | Hub 模式 emit `approval.requested` / `approval.resolved` 双向事件 | emit `STATUS_NOTICE` 单向事件（metadata 含 approval_request 类型） | 中 | Charles 单向 SSE 推送 + HTTP 端点响应；Cline 双向事件流 |
| 7.14.27 | 审批状态 markTurnPending | `local-runtime-host.ts` L613-635：审批前 `markTurnPending`，审批后 `markTurnRunning` | 无显式 turn 状态切换（runtime 协程挂起即隐含 pending） | 中 | Charles 通过协程挂起隐含表达，Cline 显式标记会话状态 |
| 7.14.28 | 版本号防竞态 | `AutoApprovalSettings.version` 字段 + `updateAutoApprovalSettings.ts` L17 比较 version 才更新 | 无版本号字段（`_persist_lock` 互斥锁保护并发写入） | 高 | 两侧均防竞态，机制不同（版本号 vs 互斥锁） |
| 7.14.29 | 多端审批一致性 | 4 端实现各不相同（Hub Server / Webview / CLI / VS Code），需各自维护 | 单端实现，天然一致 | — | Charles 单端无需考虑多端一致性 |

**一致性总评**：29 项中，高一致性 12 项、中一致性 9 项、低一致性 8 项（其中 6 项为 Charles 增强、2 项为 Charles 缺失/弱化）。Charles 在持久化、超时、MCP per-tool、before_approval 钩子、自动决策规则、管理 API 共 6 个维度**强于** Cline；Cline 在拒绝原因语义化、非交互会话拒绝 2 个维度**更精细**。

---

## 四、重点差距详细说明

### 差距 1：审批触发机制 — 多端回调 vs 单端 hook + SSE（7.14.3 / 7.14.4 / 7.14.26 / 7.14.27）

**Cline 实现**（4 端各自实现）：

Cline 通过 `AgentRuntimeConfig.requestToolApproval?: (request: ToolApprovalRequest) => Promise<ToolApprovalResult>` 回调函数注入审批逻辑。各 host 自行实现回调：

1. **VS Code 扩展**：弹出原生对话框，用户点击批准/拒绝；持久化通过 `globalState`
2. **Hub Server**（`approval-handlers.ts`）：创建 `approvalId` → emit `approval.requested` 事件 → 返回 Promise 等待客户端 `approval.respond` 命令；客户端响应后 `resolvePendingApproval` resolve Promise
3. **Cline Hub Webview**（`approvals.ts`）：emit `approval_request` 到 webview → webview 发 `approval_response` → `resolveToolApproval` resolve Promise；10 分钟超时
4. **CLI**（`approvals.ts`）：TTY 模式 `[y/N]` 提示 / Desktop 文件 IPC 模式调用 SDK Core

`local-runtime-host.ts` L613-635 在回调外层包装 `markTurnPending` / `markTurnRunning`，将会话状态从 running 切换到 pending，审批完成后再切回 running。

**Charles 实现**（`approval.py` + `runtime.py` L1645-1765 + `server.py` L1261-1328）：

Charles 通过 `before_approval` 钩子 + `asyncio.Event` + SSE 事件 + HTTP 端点实现单端审批：

1. `runtime._request_tool_approval` 调用 `request_approval()` 创建 `ApprovalEntry`
2. Runtime emit `STATUS_NOTICE` 事件（metadata.type = "approval_request"）通过 SSE 推送到前端
3. Runtime `await asyncio.wait_for(entry.event.wait(), timeout=300)` 挂起协程
4. 前端显示审批弹窗，用户点击后 `POST /api/chat/approve`
5. Server 端 `set_approval_result(tool_call_id, result)` 设置 `entry.result` 并 `entry.event.set()` 唤醒
6. Runtime 读取结果决定是否执行工具

**影响**：
- Cline 的多端回调模式**更灵活**：各 host 可自由选择 UI 形式（原生对话框 / webview / TUI / 文件 IPC）
- Charles 的单端 SSE+Event 模式**更自包含**：server 自带 UI 推送和接收端点，无需 host 注入回调
- Cline 的 `markTurnPending` 显式标记会话状态便于多端协同（如 Hub 模式下其他客户端能看到会话处于审批中）；Charles 通过协程挂起隐含表达，单端场景足够
- Charles 的 SSE 是单向推送，前端响应通过 HTTP 端点；Cline Hub 模式是双向事件流（`approval.requested` / `approval.respond` / `approval.resolved`）

**建议**：保留 Charles 现状。SSE+Event 方案是 Web 服务端场景的最佳实践，无需退化为多端回调模式。

### 差距 2：审批记忆持久化 — host globalState vs 服务端文件（7.14.5 / 7.14.6 / 7.14.7 / 7.14.25 / 7.14.28）

**Cline 实现**：

Cline 的跨会话审批记忆**完全依赖 host 实现**：
- VS Code 扩展使用 `context.globalState` API 持久化 `AutoApprovalSettings` 对象（含 `version` 防竞态字段 + `actions` per-action 粒度）
- Hub 模式下，记忆存储在 hub 客户端（CLI / Web UI）的本地状态
- 服务端（hub server）**不持久化**审批记忆

`AutoApprovalSettings` 持久化结构：
```typescript
{
    version: 1,                  // 防竞态版本号，每次更新递增
    enabled: true,               // Legacy，恒为 true
    actions: {
        readFiles: true,         // 读文件
        editFiles: true,         // 编辑文件
        executeSafeCommands: false,  // 执行安全命令
        executeAllCommands: true,    // 执行所有命令
        useBrowser: true,        // 浏览器
        useMcp: true,            // MCP 工具
    },
    enableNotifications: false,
}
```

`updateAutoApprovalSettings.ts` L13-17 通过比较 `version` 字段防止并发覆盖：
```typescript
if (incomingVersion > currentVersion) {
    // 合并 settings 并持久化
}
```

**Charles 实现**（`approval.py` L75-315 + `server.py` L1386-1450）：

Charles 实现**三级查询优先级 + 服务端持久化文件**：

1. **会话级内存**：`_session_auto_approved: dict[str, set[str]]`，会话结束后清理
2. **全局持久化**：`_persistent_auto_approved: set[str]`，懒加载自 `agent_config/approval_memory.json`
3. **默认逻辑**：走 `tool_policies` + `requires_approval` + `auto_approve` 决策

持久化文件格式：
```json
{
  "version": 1,
  "tools": ["read_files", "search_codebase"],
  "updated_at": "2026-07-26T10:00:00Z"
}
```

写入采用 **tmpfile + os.replace 原子写入**（`approval.py` L140-174），并用 `_persist_lock` 互斥锁保护并发写入。

管理 API（`server.py` L1386-1450）：
- `GET /api/chat/approval_memory` — 列出所有持久化工具
- `DELETE /api/chat/approval_memory` — 清空所有持久化记忆
- `DELETE /api/chat/approval_memory/{tool_name}` — 删除单个工具

**影响**：
- Charles 的持久化方案**强于 Cline**：服务端原子写入、独立管理 API、三级查询
- Cline 依赖 host 持久化，hub 模式下若客户端不持久化，记忆会丢失
- Cline 的 `AutoApprovalSettings` 是 **per-action 粒度**（readFiles/editFiles/executeSafeCommands/useBrowser/useMcp），Charles 是 **per-tool 粒度**（tool_name 列表）
  - Cline 的 per-action 粒度更粗（按工具类别），Charles 的 per-tool 粒度更细（按具体工具名）
  - Charles 的粒度适合工具集动态变化的场景（如 MCP 工具动态加载）
- Cline 用 `version` 字段防竞态；Charles 用 `_persist_lock` 互斥锁防竞态 — 两种方案均有效

**建议**：保留 Charles 现状。Charles 的服务端持久化方案是相对 Cline 的功能增强，适合无状态客户端场景。

### 差距 3：审批超时 — 多端不同 vs 单端 5 分钟（7.14.8 / 7.14.9）

**Cline 实现**（各端超时不一致）：

| 端 | 超时 | 位置 |
|---|------|------|
| Hub Server | **无超时** | `approval-handlers.ts` L23-45（Promise 永久挂起，依赖 `cancelPendingApprovals` 清理） |
| Cline Hub Webview | **10 分钟** | `approvals.ts` L86 `setTimeout(10 * 60_000)` |
| Desktop IPC | **5 分钟** | `tool-approval.ts` L74 `timeoutMs ?? 5 * 60_000` |
| CLI TUI | **无超时** | `approval.ts` L75-87（readline 等待用户输入，无超时） |
| CLI Desktop | **5 分钟** | 复用 SDK Core `requestDesktopToolApproval` |

**Charles 实现**（`approval.py` L47 + `runtime.py` L1744-1752）：

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

**影响**：
- Charles 选择与 Cline Desktop IPC 一致的 5 分钟超时，是合理的中间值（既给用户思考时间，又避免无限等待）
- Cline Hub Server 无超时是潜在风险：若客户端不响应且会话不结束，审批请求会永久挂起占用内存
- Cline 各端超时不一致可能导致行为差异（如同一会话从 webview 切到 CLI，超时行为变化）

**建议**：保留 Charles 现状。5 分钟硬编码超时是防御性设计，避免永久挂起。若未来需配置化，可将 `APPROVAL_TIMEOUT_SECONDS` 改为从环境变量读取。

### 差距 4：MCP 工具审批粒度 — 统一配置 vs per-tool 二维 key（7.14.11）

**Cline 实现**：

Cline 对 MCP 工具的审批通过统一的 `toolPolicies` 配置：
- `toolPolicies["use_mcp_tool"]` 配置整个 `use_mcp_tool` 工具的策略
- 无法区分"server A 的 tool X 自动批准，server B 的 tool Y 需审批"这类 per-MCP-tool 粒度
- 若需要 per-MCP-tool 策略，需 host 在 `requestToolApproval` 回调中根据 `request.input` 解析 server_name/tool_name 自行决策

**Charles 实现**（`mcp/registry.py` L67-82 + L126-128 + L201-220 + L317-340 + `runtime.py` L1595-1643）：

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
- Charles 的 MCP per-tool 策略**粒度更细**：可以精确控制"filesystem server 的 read_file 自动批准，write_file 需审批"
- Cline 的统一配置只能控制 `use_mcp_tool` 整体，无法区分具体 MCP 工具
- Charles 的方案更适合多 MCP server 场景（不同 server 的工具风险等级不同）

**建议**：保留 Charles 现状。MCP per-tool 策略是 Charles Q8 设计的核心增强。

### 差距 5：审批前自动决策 — 多端分散 vs 独立钩子 + 内置规则（7.14.12 / 7.14.13 / 7.14.14 / 7.14.15）

**Cline 实现**（各端分散实现）：

Cline 无独立的 `before_approval` 钩子点，自动决策分散在各 host：

1. **VS Code 扩展**：通过 `AutoApprovalSettings.actions` 控制（readFiles/editFiles/executeSafeCommands/useBrowser/useMcp），在 `requestToolApproval` 回调中检查
2. **CLI 交互模式**（`tool-policies.ts` + `approvals.ts`）：
   - `autoApproveAllRef.current` 全局开关
   - `SAFE_AUTO_APPROVE_TOOL_NAMES` 白名单（7 个工具）：`ask_followup_question` / `ask_question` / `fetch_web_content` / `read_files` / `search_codebase` / `skills` / `submit_and_exit`
   - `applyInteractiveAutoApproveOverride` 根据 `enabled` 切换所有工具的 `autoApprove` 字段
3. **Hub Server / Webview**：无内置自动决策规则，完全依赖客户端响应

Cline **不内置命令分类规则**（如 `rm -rf` 自动拒绝），完全由 host 或用户配置控制。

**Charles 实现**（`hooks.py` L239-266 + `approval_policy.py` + `runtime.py` L1687-1714 + `server.py` L481-484）：

Charles 有独立的 `before_approval` 钩子点，在 `_request_tool_approval` 入口调用（在创建审批请求之前）：

```python
@dataclass
class BeforeApprovalResult:
    decision: str | None = None  # None / "approved" / "denied"
    reason: str | None = None
```

`AutoApprovalPolicy` 是默认实现（`approval_policy.py`），通过 `AGENT_AUTO_APPROVAL` 环境变量控制模式：
- `off` / `0` / `false`：关闭自动审批
- `readonly`（默认）：只读工具/命令自动批准，写工具走审批，危险命令自动拒绝
- `all`：自动批准所有工具

工具级白名单（`READ_ONLY_TOOLS`，12 个）：`file_read` / `read_files` / `list_files` / `search_codebase` / `web_search` / `fetch_web_content` / `ask_question` / `attempt_completion` / `todo_write` / `switch_to_plan_mode` / `switch_to_act_mode` / `submit_and_exit`

命令级规则（`_classify_command` 三态分类）：
- `_READ_ONLY_COMMAND_PATTERNS`：`cat` / `ls` / `git status` / `pip list` 等 → 自动批准
- `_DENY_COMMAND_PATTERNS`：`rm -rf` / `mkfs` / `dd if=/dev/` / `format C:` / `shutdown` 等 → 自动拒绝
- `_WRITE_COMMAND_PATTERNS`：`mv` / `rm` / `git push` / `pip install` / `python *.py` 等 → 走用户审批

**影响**：
- Charles 的 `before_approval` 钩子**职责更单一**（只做审批决策，不修改工具输入/不跳过工具）
- Charles 内置 `AutoApprovalPolicy`，开箱即用；Cline 各 host 需自行实现自动决策规则
- Charles 的命令级三态分类（readonly/deny/write）是 Cline 完全没有的能力
- Charles 的工具白名单（12 个）比 Cline CLI 白名单（7 个）更宽，覆盖 `list_files` / `web_search` / `todo_write` / `attempt_completion` / `switch_to_plan_mode` / `switch_to_act_mode`

**建议**：保留 Charles 现状。独立 `before_approval` 钩子 + 内置 `AutoApprovalPolicy` 是 Charles 的功能增强。

### 差距 6：拒绝原因语义化 — VS Code 特殊处理 vs Charles 统一字符串（7.14.21）

**Cline 实现**（`apps/vscode/src/sdk/tool-approval-denial.ts`）：

VS Code 扩展对编辑工具的拒绝原因特殊处理：

```typescript
export const DEFAULT_TOOL_APPROVAL_DENIAL_REASON = "User denied the tool execution";
export const EDIT_TOOL_APPROVAL_DENIAL_REASON =
    "The user denied this edit. The file was NOT modified and still contains its original content.";
export const USER_MESSAGE_TOOL_APPROVAL_DENIAL_REASON =
    "Tool execution was cancelled because the user sent a follow-up message.";

export function buildToolApprovalDenialReason(toolName, feedback) {
    const denial = toolName && isEditTool(toolName)
        ? EDIT_TOOL_APPROVAL_DENIAL_REASON
        : DEFAULT_TOOL_APPROVAL_DENIAL_REASON;
    const trimmedFeedback = feedback?.trim();
    if (!trimmedFeedback) return denial;
    return `${denial} The user provided the following feedback:\n<feedback>\n${trimmedFeedback}\n</feedback>`;
}
```

**设计动机**（注释 L12-16）：编辑工具拒绝后，模型若只看到用户反馈（如"改大一点"），会误以为编辑已应用，下次重试用错误的 `old_text` 匹配文件实际内容，导致状态漂移。明确告知"文件未被修改"可避免此问题。

另外 `USER_MESSAGE_TOOL_APPROVAL_DENIAL_REASON` 用于用户在审批期间发送新消息时取消当前审批。

`isKnownToolApprovalDenial` / `isDeniedToolApprovalMistake` 用于 mistake tracker 识别审批拒绝导致的"错误"，避免误判为模型失误。

**Charles 实现**（`runtime.py` L1758-1764）：

Charles 统一返回拒绝原因字符串，无工具类型区分：

```python
if result == "approved":
    logger.info(f"工具审批通过: {tool_call.tool_name}")
    return None
else:
    reason = f"工具 {tool_call.tool_name} 被用户拒绝"
    logger.info(f"工具审批拒绝: {tool_call.tool_name}")
    return reason
```

**影响**：
- Charles 缺失拒绝原因语义化，编辑工具（`file_write` / `editor` / `apply_patch`）拒绝后，模型可能误以为编辑已应用，下次重试时 `old_text` / 文件内容不匹配
- Charles 缺失 `USER_MESSAGE_TOOL_APPROVAL_DENIAL_REASON` 语义（用户在审批期间发送新消息时取消审批的场景）
- Charles 的 mistake tracker（`agent/mistake_tracker.py`）未识别审批拒绝导致的"错误"，可能误判为模型失误

**建议**：**[P2 修复]** 在 `runtime.py` L1758-1764 增加编辑工具拒绝原因特殊处理：
```python
EDIT_TOOL_APPROVAL_DENIAL_REASON = (
    "用户拒绝了此编辑。文件未被修改，仍保持原始内容。"
)

if result == "approved":
    return None
else:
    edit_tools = {"file_write", "editor", "apply_patch"}
    if tool_call.tool_name in edit_tools:
        return EDIT_TOOL_APPROVAL_DENIAL_REASON
    return f"工具 {tool_call.tool_name} 被用户拒绝"
```

此修复符合 Charles 的"避免模型状态漂移"原则，与 P2.8（loop detection / mistake tracker）协同。注意：此为 P2 级别优化，不阻塞 P7.14 对比结论。

### 差距 7：非交互会话审批拒绝 — Cline 有 vs Charles 无（7.14.10）

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
- Charles 缺失非交互会话检查，理论上若 cron job 未设 `auto_approve=True`，会触发审批请求并挂起 300 秒超时
- 实际影响小：Charles 的 cron runner 默认设 `auto_approve=True`（对标 Cline `buildToolPolicies` 的 `*: { autoApprove: true }`），不会触发审批
- 但缺少防御层：若配置错误（cron job 忘记设 auto_approve），会浪费 5 分钟超时

**建议**：不强制补齐（与 P3.8 结论一致）。Charles 的 cron 场景通过配置层（`auto_approve=True`）规避了此问题，引入 interactive 标记会增加状态管理复杂度。若未来支持非交互会话（如 headless 模式 / CI/CD 集成），应在 `AgentRuntimeConfig` 增加 `interactive: bool` 字段，并在 `_request_tool_approval` 入口检查。

---

## 五、nanobot 残留检查

针对 P7.14 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 5.1 P7.14 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/approval.py` | **0** | 无 | 审批管理无 nanobot 引用 |
| `agent/approval_policy.py` | **0** | 无 | 自动审批策略无 nanobot 引用 |
| `agent/hooks.py`（审批钩子段落 L239-266 / L313） | **0** | 无 | `BeforeApprovalContext` / `BeforeApprovalResult` / `before_approval` 字段无 nanobot 引用 |
| `agent/runtime.py`（审批段落 L1446-1765） | **0** | 无 | `_prepare_tool_execution` / `_request_tool_approval` / `_get_mcp_tool_policy_override` 无 nanobot 引用 |
| `agent/types.py`（`tool_policies` / `auto_approve` 字段） | **0** | 无 | 配置字段无 nanobot 引用 |
| `agent/tools/base.py`（`requires_approval` 属性） | **0** | 无 | 已在 P3.1 清理完毕 |
| `agent/mcp/registry.py`（`MCPToolPolicy` / `get_tool_policy`） | **0** | 无 | MCP 策略无 nanobot 引用 |
| `agent/server.py`（审批端点 + 审批钩子注册段落） | **0**（段落内） | 无 | `/api/chat/approve` 端点（L1261-1328）+ 审批钩子注册（L481-484）+ 持久化记忆 API（L1386-1450）段落内均无 nanobot 引用 |

### 5.2 残留分类

#### 注释残留（0 处，P7.14 范围内）

P7.14 核心审批文件中**无 nanobot 注释残留**。

但需注意：`agent/server.py` 文件级 docstring（L2 / L4 / L28-29）有 4 处 nanobot 注释残留，属于 P1.7（前端后端交互）或 P2.x（事件系统）范围的清理任务。这些残留位于 `server.py` 文件头，**不在审批端点（`/api/chat/approve` / `/api/chat/approval_memory`）或审批钩子注册段落的实现代码内**，但 `server.py` 是审批端点所在文件。

**位置**（与 P3.8 一致，未变化）：
- L2：`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`
- L4：`提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`
- L28-29：`对标 nanobot:` + 子项 `routes/chat.py _sse_generator() + _StreamCollectorHook`

**性质**：全部为 docstring 中的历史溯源说明，标注 Charles SSE 服务端同时对标了 Cline server 和历史 nanobot routes/chat.py。

**处理建议**：将 L2 改为 `"""SSE 服务端 — 对标 Cline server`，L4 删除 `用 AgentRuntime 替换 nanobot` 段落，L28-29 删除 `对标 nanobot:` 段落。属于 P2 级别清理，不阻塞 P7.14 对比结论。注意：这些残留属于文件级 docstring 维护，不仅涉及审批端点，应在 P1.7 或专门清理批次中统一处理。

#### 实现逻辑残留（0 处）

P7.14 核心文件中**未发现任何从 nanobot 直接移植的审批实现逻辑**：

- `approval.py` 的 `ApprovalEntry` + `_pending_approvals` + `asyncio.Event` 机制是 Charles 原创设计，对标 Cline `tool-approval.ts`（文件头明确标注"对标 Cline tool-approval.ts + auto-approve 机制"）。
- `approval_policy.py` 的 `AutoApprovalPolicy` + 命令分类正则是 Charles 原创设计，无 nanobot 对应物。
- `hooks.py` 的 `BeforeApprovalContext` / `BeforeApprovalResult` 对标 Cline `AgentBeforeToolResult.policy`（注释标注"对标 Cline 审批钩子"），但独立为 `before_approval` 钩子点是 Charles 的设计增强。
- `runtime.py` 的 `_request_tool_approval` 对标 Cline `requestDesktopToolApproval`（注释标注"对标 Cline requestDesktopToolApproval"），实现逻辑是 Charles 原创的 asyncio.Event 方案。
- `mcp/registry.py` 的 `MCPToolPolicy` 对标 Cline `shared/llms/tools.ts ToolPolicy`（L69 注释标注），per-tool 二维 key 是 Charles 的 Q8 设计增强。

### 5.3 P7.14 范围外但相关的残留

以下文件有 nanobot 残留，但属于其他 P 阶段的对比范围，不在 P7.14 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|---------------|-----------|
| `agent/session.py` | 2 | P1.x（会话管理） |
| `agent/context.py` | 1 | P1.x（上下文管理） |
| `agent/tools/file_tools.py` | 7 | P3.x（FileWriteTool 专项） |
| `agent/tools/exec_tool.py` | 12 | P3.x（exec_tool 专项，已废弃） |
| `agent/tools/web_tool.py` | 7 | P3.x（WebSearchTool 专项） |
| `agent/providers/qwen.py` | 3 | P4.x（Qwen provider 专项） |
| `agent/skills/registry.py` | 4 | P4.x（skills registry） |
| `agent/skills/loader.py` | 6 | P4.x（skills loader） |
| `agent/skills/__init__.py` | 2 | P4.x（skills 模块） |
| `agent/skills/skill_tool.py` | 1 | P4.x（skill tool） |
| `agent/tools/__init__.py` | 1 | P3.x（tools 模块） |

这些残留全部为 docstring / 行内注释，属历史溯源标注，不影响审批机制层的对比结论。

---

## 六、修复建议

### 建议 1：保留持久化审批记忆方案 [P0 不变]

**理由**：Charles 的 `approval_memory.json` + 三级查询优先级 + 原子写入 + 管理 API 是相对 Cline 的功能增强，应予保留。

### 建议 2：保留 `before_approval` 独立钩子 [P0 不变]

**理由**：独立 `before_approval` 钩子职责单一（只做审批决策），与 `before_tool` 钩子（跳过工具 / 修改输入 / 覆盖策略）分离，符合关注点分离原则。`AutoApprovalPolicy` 内置实现提供了开箱即用的命令分类规则。

### 建议 3：保留 MCP per-tool 策略粒度 [P0 不变]

**理由**：`MCPToolPolicy` 的 `(server_name, tool_name)` 二维 key 粒度比 Cline 的统一 `toolPolicies["use_mcp_tool"]` 更精细，适合多 MCP server 场景。这是 Charles Q8 设计的核心增强。

### 建议 4：保留 `requires_approval` 工具自声明属性 [P0 不变]

**理由**：`BaseTool.requires_approval` 提供工具自声明 + 策略覆盖的双层设计，工具开发者可在工具类内部标注风险等级，用户通过 `tool_policies` 覆盖。符合 Charles 的 OOP 风格。

### 建议 5：保留 300 秒审批超时 [P0 不变]

**理由**：硬编码超时是防御性设计，避免用户离开后审批请求永久挂起。5 分钟阈值合理（既给用户思考时间，又避免无限等待），与 Cline Desktop IPC 的 5 分钟超时一致。

### 建议 6：增加编辑工具拒绝原因语义化 [P2 修复]

**文件**：`agent/runtime.py`
**位置**：L1758-1764（`_request_tool_approval` 返回拒绝原因处）
**修改**：

```python
# 当前代码（L1758-1764）：
if result == "approved":
    logger.info(f"工具审批通过: {tool_call.tool_name}")
    return None
else:
    reason = f"工具 {tool_call.tool_name} 被用户拒绝"
    logger.info(f"工具审批拒绝: {tool_call.tool_name}")
    return reason

# 建议修改为：
# 编辑工具拒绝原因特殊处理 — 对标 Cline tool-approval-denial.ts
# 避免模型误以为编辑已应用，下次重试时 old_text / 文件内容不匹配
EDIT_TOOL_APPROVAL_DENIAL_REASON = (
    "用户拒绝了此编辑。文件未被修改，仍保持原始内容。"
)
EDIT_TOOLS = {"file_write", "editor", "apply_patch"}

if result == "approved":
    logger.info(f"工具审批通过: {tool_call.tool_name}")
    return None
else:
    if tool_call.tool_name in EDIT_TOOLS:
        reason = EDIT_TOOL_APPROVAL_DENIAL_REASON
    else:
        reason = f"工具 {tool_call.tool_name} 被用户拒绝"
    logger.info(f"工具审批拒绝: {tool_call.tool_name}, reason={reason}")
    return reason
```

**理由**：对标 Cline `tool-approval-denial.ts` 的 `EDIT_TOOL_APPROVAL_DENIAL_REASON` 设计，避免编辑工具拒绝后模型状态漂移。与 P2.8（loop detection / mistake tracker）协同。注意：此为 P2 级别优化，不阻塞 P7.14 对比结论。

### 建议 7：不强制补齐非交互会话审批拒绝 [P3 不修复]

**理由**（与 P3.8 结论一致）：
- Charles 的 cron 场景通过 `auto_approve=True` 全局开关规避了审批挂起
- Charles 无显式的 interactive session 标记，引入会增加状态管理复杂度
- 实际影响小：配置正确的 cron job 不会触发审批

**保留条件**：若未来支持 headless 模式（如 CI/CD 集成），应在 `AgentRuntimeConfig` 增加 `interactive: bool` 字段，并在 `_request_tool_approval` 入口检查。

### 建议 8：清理 `server.py` 文件头 nanobot 注释残留 [P2]

**文件**：`agent/server.py`
**位置**：L2 / L4 / L28-29
**修改**：
- L2：`"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py` → `"""SSE 服务端 — 对标 Cline server`
- L4：删除 `提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。` 中的 `用 AgentRuntime 替换 nanobot` 段落
- L28-29：删除 `对标 nanobot:` 及其子项

**理由**：统一为"对标 Cline"溯源风格，与 `approval.py` / `approval_policy.py` / `hooks.py`（均无 nanobot 残留）保持一致。不影响功能。注意此清理属于文件级 docstring 维护，不仅涉及审批端点，应在 P1.7 或专门清理批次中统一处理。此建议与 P3.8 建议 1 完全一致，未重复执行以避免冲突。

---

## 七、验证方法建议

### 验证方法 1：审批流程端到端检查

确认 Charles 审批流程完整（创建 → emit → 等待 → 设置结果 → 唤醒 → 清理）：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "request_approval|set_approval_result|get_approval_result|clear_approval|asyncio\.wait_for"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "def request_approval|def set_approval_result|def get_approval_result|def clear_approval"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern 'approve_tool|/approve'
```

### 验证方法 2：三级查询优先级检查

确认 Charles 三级查询优先级（会话级内存 > 全局持久化 > 默认逻辑）：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "_load_persistent_memory|_save_persistent_memory|mark_auto_approved|is_auto_approved|_session_auto_approved|_persistent_auto_approved"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "is_auto_approved|before_approval"
```

### 验证方法 3：持久化记忆管理 API 检查

确认 Charles 持久化记忆的加载/保存/管理 API 完整：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "list_persistent_auto_approved|remove_persistent_auto_approved|clear_persistent_auto_approved"
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

### 验证方法 6：审批超时验证

确认 Charles 硬编码 300 秒超时：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "APPROVAL_TIMEOUT_SECONDS"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "APPROVAL_TIMEOUT_SECONDS|asyncio\.wait_for"
```

### 验证方法 7：Cline 多端审批路径对比

确认 Cline 4 端审批路径的超时差异：

```powershell
# Hub Server（无超时）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\hub\server\handlers\approval-handlers.ts" -Pattern "setTimeout|timeout"

# Cline Hub Webview（10 分钟）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\cline-hub\src\server\approvals.ts" -Pattern "setTimeout|10 \* 60"

# Desktop IPC（5 分钟）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\tools\tool-approval.ts" -Pattern "timeoutMs|5 \* 60"

# CLI（无超时，TTY 等待）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\cli\src\utils\approval.ts" -Pattern "setTimeout|timeout"
```

### 验证方法 8：Cline 拒绝原因语义化检查

确认 Cline VS Code 扩展对编辑工具的拒绝原因特殊处理：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\sdk\tool-approval-denial.ts" -Pattern "EDIT_TOOL_APPROVAL_DENIAL_REASON|buildToolApprovalDenialReason|isEditTool"
```

### 验证方法 9：Cline AutoApprovalSettings 持久化检查

确认 Cline VS Code 扩展通过 globalState 持久化 + version 防竞态：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\core\controller\state\updateAutoApprovalSettings.ts" -Pattern "setGlobalState|version|autoApprovalSettings"
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\shared\AutoApprovalSettings.ts" -Pattern "version|actions|enabled"
```

### 验证方法 10：nanobot 残留扫描

```powershell
# P7.14 核心文件扫描（应全部为 0）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval_policy.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\hooks.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\mcp\registry.py" -Pattern "nanobot" -CaseSensitive:$false

# server.py 文件头残留（仅文件级 docstring，不在审批段落内）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\server.py" -Pattern "nanobot" -CaseSensitive:$false
```

---

## 八、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/shared/src/llms/tools.ts` | L7-18 | `ToolPolicy` 接口（`enabled` / `autoApprove`，默认均 true） |
| `sdk/packages/shared/src/llms/tools.ts` | L46-80 | `ToolApprovalRequest` 接口（sessionId/agentId/conversationId/iteration/toolCallId/toolName/input/policy） |
| `sdk/packages/shared/src/llms/tools.ts` | L82-85 | `ToolApprovalResult { approved: boolean, reason?: string }` |
| `sdk/packages/core/src/runtime/tools/tool-approval.ts` | L29-101 | `requestDesktopToolApproval` — 文件 IPC 默认实现（5 分钟超时 + 轮询 decision 文件） |
| `sdk/packages/core/src/extensions/tools/presets.ts` | L137-158 | `createToolPoliciesWithPreset("yolo")` — yolo 预设填充 `*: { enabled, autoApprove }` |
| `sdk/packages/core/src/runtime/host/local-runtime-host.ts` | L613-635 | `requestToolApproval` 回调包装（markTurnPending / markTurnRunning） |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L9-46 | `requestToolApproval`：创建 approvalId + emit `approval.requested` + 等待（无超时） |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L13-22 | 非交互会话检查 `state.interactive === false` → 自动拒绝 |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L48-60 | `resolvePendingApproval`：resolve promise |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L62-84 | `cancelPendingApprovals`：批量取消 + emit `approval.resolved { cancelled: true }` |
| `sdk/packages/core/src/hub/server/handlers/approval-handlers.ts` | L86-133 | `handleApprovalRespond`：处理客户端 `approval.respond` 命令 |
| `apps/cline-hub/src/server/approvals.ts` | L10-27 | `resolveToolApproval`：webview 响应后 resolve + emit `approval_resolved` |
| `apps/cline-hub/src/server/approvals.ts` | L29-59 | `rejectPendingApprovalsForSession` / `rejectAllPendingApprovals` / `rejectOrphanedApprovals` |
| `apps/cline-hub/src/server/approvals.ts` | L61-105 | `requestToolApprovalFromWebview`：emit `approval_request` + 10 分钟超时 |
| `apps/cli/src/runtime/interactive/approvals.ts` | L20-66 | `createInteractiveApprovalController`：`autoApproveAllRef` 全局开关 + `requestToolApproval` 回调 |
| `apps/cli/src/runtime/tool-policies.ts` | L3-11 | `SAFE_AUTO_APPROVE_TOOL_NAMES` 白名单（7 个工具） |
| `apps/cli/src/runtime/tool-policies.ts` | L30-48 | `resolveInteractiveAutoApprovePolicy`：根据 enabled 切换 autoApprove |
| `apps/cli/src/runtime/tool-policies.ts` | L50-95 | `applyInteractiveAutoApproveOverride`：批量覆盖 targetPolicies |
| `apps/cli/src/utils/approval.ts` | L24-59 | `requestDesktopToolApprovalFromCore`：调用 SDK Core 文件 IPC |
| `apps/cli/src/utils/approval.ts` | L65-96 | `requestTerminalToolApproval`：TTY `[y/N]` 提示（无超时） |
| `apps/cli/src/utils/approval.ts` | L102-110 | `requestToolApproval`：根据 `CLINE_TOOL_APPROVAL_MODE` 选择 desktop/terminal |
| `apps/vscode/src/shared/AutoApprovalSettings.ts` | L1-44 | `AutoApprovalSettings` 接口 + `DEFAULT_AUTO_APPROVAL_SETTINGS`（per-action 粒度） |
| `apps/vscode/src/core/controller/state/updateAutoApprovalSettings.ts` | L11-37 | `updateAutoApprovalSettings`：version 防竞态 + `setGlobalState` 持久化 |
| `apps/vscode/src/sdk/tool-approval-denial.ts` | L3-6 | `DEFAULT_TOOL_APPROVAL_DENIAL_REASON` / `EDIT_TOOL_APPROVAL_DENIAL_REASON` / `USER_MESSAGE_TOOL_APPROVAL_DENIAL_REASON` |
| `apps/vscode/src/sdk/tool-approval-denial.ts` | L17-24 | `buildToolApprovalDenialReason`：编辑工具特殊提示"文件未被修改" |
| `apps/vscode/src/sdk/tool-approval-denial.ts` | L43-76 | `isKnownToolApprovalDenial` / `isDeniedToolApprovalMistake`：mistake tracker 识别 |
| `sdk/packages/core/src/cron/runner/cron-runner.ts` | L61-81 | `buildToolPolicies`：cron 默认 `*: { autoApprove: true }`，list 模式 per-tool enabled |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/approval.py` | L47 | `APPROVAL_TIMEOUT_SECONDS = 300.0`（5 分钟超时） |
| `agent/approval.py` | L50-69 | `ApprovalEntry` dataclass（含 `asyncio.Event`） |
| `agent/approval.py` | L73-92 | `_pending_approvals` / `_session_auto_approved` / `_persistent_auto_approved` 全局状态 |
| `agent/approval.py` | L95-174 | `_get_persist_file_path` / `_load_persistent_memory` / `_save_persistent_memory`（原子写入 + `_persist_lock` 互斥锁） |
| `agent/approval.py` | L177-227 | `mark_auto_approved` / `is_auto_approved`（三级查询优先级） |
| `agent/approval.py` | L230-315 | `list_auto_approved` / `clear_session_auto_approved` / `list_persistent_auto_approved` / `remove_persistent_auto_approved` / `clear_persistent_auto_approved` |
| `agent/approval.py` | L318-346 | `request_approval`：创建 entry 到 `_pending_approvals` |
| `agent/approval.py` | L349-373 | `set_approval_result`：设置 result + `event.set()` 唤醒 |
| `agent/approval.py` | L376-417 | `get_approval_result` / `clear_approval` / `get_pending_approval_meta` |
| `agent/approval.py` | L419-464 | `list_pending_approvals` / `cancel_pending_approvals_for_session` |
| `agent/approval_policy.py` | L33-54 | `READ_ONLY_TOOLS`（12 个）/ `WRITE_TOOLS`（3 个）工具分类集合 |
| `agent/approval_policy.py` | L61-101 | `_READ_ONLY_COMMAND_PATTERNS` / `_DENY_COMMAND_PATTERNS` / `_WRITE_COMMAND_PATTERNS` 命令分类正则 |
| `agent/approval_policy.py` | L108-136 | `_classify_command`：单条命令分类（readonly/deny/write） |
| `agent/approval_policy.py` | L139-224 | `AutoApprovalPolicy`：默认 `before_approval` 钩子实现（off/readonly/all 三态） |
| `agent/hooks.py` | L239-266 | `BeforeApprovalContext` / `BeforeApprovalResult`（decision: None/"approved"/"denied"） |
| `agent/hooks.py` | L283 | `BeforeApprovalHook` 类型定义 |
| `agent/hooks.py` | L313 | `AgentHooks.before_approval` 字段 |
| `agent/hooks.py` | L339 / L360-361 / L374 / L388 | `HookBag.before_approval` 列表 + add/clear/is_empty |
| `agent/runtime.py` | L1446-1594 | `_prepare_tool_execution`：5 步流程（normalize → before_tool → MCP policy → policy check → approval check） |
| `agent/runtime.py` | L1542-1551 | MCP per-tool 策略注入（Stage 9.1 Q8） |
| `agent/runtime.py` | L1553-1567 | 策略三态语义检查（enabled=False → skip / autoApprove=False → ask） |
| `agent/runtime.py` | L1569-1583 | `requires_approval` + `auto_approve` 兜底逻辑 |
| `agent/runtime.py` | L1595-1643 | `_get_mcp_tool_policy_override`：MCP 策略转换 |
| `agent/runtime.py` | L1645-1764 | `_request_tool_approval`：5 步审批流程（auto_approved 检查 → before_approval hook → 创建 entry → emit → 等待） |
| `agent/runtime.py` | L1744-1752 | `asyncio.wait_for` 超时处理 |
| `agent/runtime.py` | L1758-1764 | 拒绝原因返回（**当前未区分工具类型，建议 6 修复点**） |
| `agent/types.py` | L536 | `AgentRuntimeConfig.tool_policies: dict[str, dict[str, Any]]` |
| `agent/types.py` | L541 | `AgentRuntimeConfig.auto_approve: bool = False` |
| `agent/tools/base.py` | L96-103 | `BaseTool.requires_approval` 属性（默认 False） |
| `agent/tools/apply_patch.py` | L201-203 | `requires_approval = True` |
| `agent/tools/file_tools.py` | L202-204 | `requires_approval = True`（FileWriteTool） |
| `agent/tools/editor.py` | L180-182 | `requires_approval = True` |
| `agent/tools/run_commands.py` | L113-115 | `requires_approval = True` |
| `agent/mcp/registry.py` | L67-82 | `MCPToolPolicy` dataclass（server_name/tool_name/enabled/auto_approve） |
| `agent/mcp/registry.py` | L126-128 | `_tool_policies: dict[tuple[str, str], MCPToolPolicy]` 缓存 |
| `agent/mcp/registry.py` | L201-220 | 加载 `tool_policies` 段（YAML 配置） |
| `agent/mcp/registry.py` | L317-340 | `get_tool_policy(server_name, tool_name)` 查询 |
| `agent/server.py` | L481-484 | 注册 `AutoApprovalPolicy` 作为 `before_approval` 钩子 |
| `agent/server.py` | L1261-1328 | `POST /api/chat/approve` 端点（接收 approved/auto_approve，调用 mark_auto_approved） |
| `agent/server.py` | L1386-1402 | `GET /api/chat/approval_memory` 列出持久化记忆 |
| `agent/server.py` | L1405-1422 | `DELETE /api/chat/approval_memory` 清空所有持久化记忆 |
| `agent/server.py` | L1425-1450 | `DELETE /api/chat/approval_memory/{tool_name}` 删除单个工具记忆 |

---

## 九、与 P3.8 的关联与差异

P7.14 在 P3.8 已确认的结论基础上，**新增以下维度**：

| 维度 | P3.8 覆盖 | P7.14 新增 |
|------|----------|-----------|
| 审批策略字段（enabled/autoApprove/通配符 `*`） | 24 项 per-tool 字段级对比 | — |
| Cline 多端审批路径（Hub Server / Webview / CLI / VS Code） | 仅提及 Hub Server | **4 端详细对比 + 超时差异表** |
| Cline `AutoApprovalSettings` 持久化模型 | 仅提及 host globalState | **per-action 粒度 + version 防竞态字段** |
| Cline CLI `SAFE_AUTO_APPROVE_TOOL_NAMES` 白名单 | 未覆盖 | **7 个工具白名单 + `applyInteractiveAutoApproveOverride` 逻辑** |
| Cline `tool-approval-denial.ts` 拒绝原因语义化 | 未覆盖 | **编辑工具特殊提示 + mistake tracker 识别** |
| Charles 三级查询优先级 | 已覆盖 | **补充与 Cline per-action 粒度对比** |
| Charles `_persist_lock` 互斥锁 | 未覆盖 | **补充与 Cline version 字段防竞态对比** |
| Cline `markTurnPending` / `markTurnRunning` 会话状态切换 | 未覆盖 | **补充 Charles 协程挂起隐含表达对比** |
| Cline cron `buildToolPolicies` 默认策略 | 已覆盖 | **补充 list 模式 per-tool enabled 逻辑** |
| nanobot 残留 | server.py 4 处 | **P7.14 范围内 0 处（确认审批段落无残留）** |

**P3.8 与 P7.14 结论一致性**：
- 6 项 Charles 增强（持久化 / 超时 / MCP per-tool / before_approval 钩子 / 自动决策规则 / 管理 API）— **两侧结论一致**
- 1 项 Charles 缺失（非交互会话审批拒绝）— **两侧结论一致，建议不修复**
- 1 项 Charles 多一层（`requires_approval` 工具自声明）— **两侧结论一致**

**P7.14 新增发现**：
- Cline 拒绝原因语义化（`EDIT_TOOL_APPROVAL_DENIAL_REASON`）是 P3.8 未覆盖的 Charles 缺失项，建议 P2 级修复（建议 6）
- Cline 多端超时不一致（Hub Server 无超时 / Webview 10 分钟 / Desktop 5 分钟 / CLI 无超时）是 P3.8 未覆盖的 Cline 实现细节，Charles 选择 5 分钟是合理中间值
- Cline `AutoApprovalSettings` 的 per-action 粒度（readFiles/editFiles/executeSafeCommands/useBrowser/useMcp）与 Charles per-tool 粒度的差异是 P3.8 未覆盖的维度

---

## 十、结论

P7.14 审批机制对比的核心结论：

1. **两种等价但形态不同的方案**：Cline 采用多端回调驱动（4 端各自实现 `requestToolApproval` 回调 + hub 事件流双向通信），Charles 采用单端事件驱动（`asyncio.Event` + SSE 单向推送 + HTTP 端点响应）。两种方案都能实现"runtime 挂起 → 用户决策 → 唤醒 runtime"的完整流程。

2. **核心功能已对齐**：`toolPolicies` per-tool 配置、`enabled` / `autoApprove` 字段、全局通配符 `*`、策略合并顺序（global → per-tool）、审批 deny 后 skip 工具、会话级审批记忆、跨会话审批记忆、cron 场景默认 `auto_approve=true`、`autoApproveTools` 布尔开关等核心功能在两侧都有对应实现。

3. **Charles 在 6 个维度上强于 Cline**（应予保留）：
   - **审批结果持久化**：服务端 `approval_memory.json` 原子写入 + 管理 API + 三级查询优先级（Cline 依赖 host globalState，无服务端 API）
   - **审批超时**：硬编码 300 秒超时自动拒绝（Cline 各端不一致，Hub Server 无超时）
   - **MCP per-tool 策略**：`(server_name, tool_name)` 二维 key 粒度（Cline 统一 `use_mcp_tool` 配置）
   - **审批前自动决策钩子**：独立 `before_approval` 钩子点 + `AutoApprovalPolicy` 内置实现（Cline 无独立钩子，分散在各 host）
   - **自动决策规则**：内置 `READ_ONLY_TOOLS` / `WRITE_TOOLS` / 命令三态分类正则（Cline 仅 CLI 有 `SAFE_AUTO_APPROVE_TOOL_NAMES` 白名单，无命令分类）
   - **审批记忆管理 API**：`GET/DELETE /api/chat/approval_memory`（Cline 无服务端 API）

4. **Charles 在 2 个维度上缺失或弱于 Cline**：
   - **拒绝原因语义化**（建议 P2 修复）：Cline VS Code 扩展对编辑工具特殊提示"文件未被修改"，避免模型状态漂移；Charles 统一返回"工具 X 被用户拒绝"
   - **非交互会话审批拒绝**（建议不修复）：Cline 检查 `state.interactive === false` 自动拒绝；Charles 无此检查，但 cron 场景通过 `auto_approve=True` 规避

5. **Charles 多一层工具自声明**：`BaseTool.requires_approval` 属性提供工具自声明审批需求，与 `tool_policies` 策略层形成双层设计（Cline 完全由外部策略控制）。

6. **多端 vs 单端的架构权衡**：
   - Cline 多端方案适合跨平台 IDE/CLI/Hub 场景（各 host 自由选择 UI 形式），但需各自维护一致性
   - Charles 单端方案适合 Web 服务端场景（所有状态集中在服务端，无状态客户端），天然一致但灵活性较低

7. **nanobot 残留**：P7.14 核心审批文件（`approval.py` / `approval_policy.py` / `hooks.py` / `runtime.py` 审批段落 / `mcp/registry.py` / `types.py` / `tools/base.py`）均无 nanobot 残留；`server.py` 文件头有 4 处 docstring 残留（L2 / L4 / L28-29），属文件级历史溯源标注，不在审批端点段落内，应在 P1.7 或专门清理批次中统一处理（与 P3.8 结论一致，未重复执行）。

**整体一致性等级**：**高**。P7.14 范围内无需阻塞性修复。建议 6（编辑工具拒绝原因语义化）为 P2 级别优化，对标 Cline `tool-approval-denial.ts` 设计，与 P2.8（loop detection / mistake tracker）协同。建议 8（清理 `server.py` 文件头 nanobot 注释）为 P2 级别清理任务，与 P3.8 建议 1 完全一致，应在 P1.7 或专门清理批次中处理。Charles 在审批机制上的 6 项功能增强应予保留，2 项缺失中 1 项建议 P2 修复（拒绝原因语义化）、1 项建议不修复（非交互会话检查）。
