# Phase U: 审批机制 + ToolPolicies 对比报告

> 对标源码：
> - `sdk/packages/core/src/runtime/tools/tool-approval.ts`（桌面端文件 IPC 审批）
> - `sdk/packages/core/src/extensions/tools/presets.ts`（工具预设 + yolo 策略）
> - `sdk/packages/core/src/extensions/tools/definitions.ts`（lifecycle.blocking 相关）
> - `sdk/packages/shared/src/llms/tools.ts`（ToolPolicy / ToolApprovalRequest / ToolApprovalResult 类型）
> - `sdk/packages/shared/src/agent.ts`（AgentRuntimeConfig.toolPolicies / requestToolApproval）
> - `sdk/packages/agents/src/agent-runtime.ts`（审批检查 + requestToolApproval 调用）
> - `apps/cli/src/runtime/tool-policies.ts`（交互式 auto-approve 覆盖逻辑）
> - `apps/cli/src/runtime/interactive/approvals.ts`（TUI 审批控制器 + autoApproveAllRef）
> - `apps/vscode/src/sdk/sdk-tool-policies.ts`（VSCode AutoApprovalSettings → toolPolicies 映射）
> - `apps/vscode/src/services/mcp/McpHub.ts`（toggleToolAutoApprove：MCP 工具审批记忆）
> - `docs/features/auto-approve.mdx`（auto-approve 行为说明）
>
> 当前实现：
> - `agent/approval.py`（审批请求生命周期 + asyncio.Event 等待）
> - `agent/approval_policy.py`（AutoApprovalPolicy：off/readonly/all 三档策略）
> - `agent/hooks.py`（before_approval 钩子点 + BeforeApprovalContext/Result）
> - `agent/tools/base.py`（requires_approval 属性）
> - `agent/runtime.py`（_prepare_tool_execution + _request_tool_approval 流程）
> - `agent/server.py`（/api/chat/approve 端点 + Plan Mode 工具策略 + 中止取消审批）
> - `agent/types.py`（AgentRuntimeConfig.auto_approve / tool_policies）
> - `static/js/ai-chat.js`（前端审批卡片 UI + SSE 接收 + POST 决策）
>
> 对比维度：U1-U10

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 3 项 |
| 弱对齐 | 5 项 |
| 缺失 | 1 项 |
| 额外增强 | 1 项 |
| **对齐度** | **约 65%** |

> 评分口径：完全一致 = 1.0，弱对齐 = 0.5，额外增强 = 1.0，缺失 = 0。计算：(3 + 5×0.5 + 1×1) / 10 = 65%。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| U1 | `autoApprove` 全局开关 | shared/llms/tools.ts L17（默认 true）；approvals.ts L21-23 `autoApproveAllRef` | types.py L397 `auto_approve: bool = False` | 弱对齐 |
| U2 | `toolPolicies` per-tool 配置（allow/deny/ask） | shared/llms/tools.ts L7-18 `{enabled, autoApprove}`；agent-runtime.ts L1396-1413 | types.py L392 `tool_policies: dict`；runtime.py L1182-1187；base.py L96 `requires_approval` | 弱对齐 |
| U3 | `requestToolApproval` 回调 | shared/agent.ts L437-439 config 回调；agent-runtime.ts L1424-1462 | hooks.py L224-251 `before_approval` hook；runtime.py L1209-1317 | 弱对齐 |
| U4 | Plan Mode 工具策略 | presets.ts L43-55 `ToolPresets.plan`（enableEditor/enableApplyPatch: false） | server.py L363-372（editor/apply_patch/file_write 全部 enabled: False） | 弱对齐 |
| U5 | 审批 UI 流程（弹窗 + approve/deny） | approvals.ts L9-18 `tuiToolApprover`；VSCode webview AutoApproveBar | ai-chat.js L225-275 `renderApprovalBlock` + L709-762 `_onApprovalRequest`/`_sendApproval` | 完全一致 |
| U6 | 审批超时 | tool-approval.ts L74 `5 * 60_000`ms 默认；L101 返回 `{approved: false}` | approval.py L42 `APPROVAL_TIMEOUT_SECONDS = 300.0`；runtime.py L1303-1305 超时拒绝 | 完全一致 |
| U7 | `before_approval` hook（hook 形式 vs config 形式） | 无（Cline 仅有 config 回调 `requestToolApproval`，无前置 hook） | hooks.py L224-251 `BeforeApprovalHook` + approval_policy.py `AutoApprovalPolicy` | 额外增强 |
| U8 | 审批结果传播（approve → 执行，deny → 跳过） | agent-runtime.ts L1409-1412 `!approval.approved` → skipReason | runtime.py L1311-1317 result == "approved" → None；否则返回 reason | 完全一致 |
| U9 | 工具分组审批（同组工具一次审批） | sdk-tool-policies.ts L48-73 `isToolAutoApproved` 按类别（read/edit/command/browser/mcp）分组；AutoApprovalSettings 5 类开关 | approval_policy.py L34-54 `READ_ONLY_TOOLS` / `WRITE_TOOLS` 分类（仅用于自动决策，非分组审批） | 弱对齐 |
| U10 | 审批记忆（"始终允许" 选项） | sdk-tool-policies.ts `AutoApprovalSettings` 持久化；McpHub.ts L1534 `toggleToolAutoApprove` 按 MCP 工具记忆；approvals.ts L30-37 `setInteractiveAutoApprove` 热切换 | 无持久化审批记忆；AGENT_AUTO_APPROVAL 环境变量仅全局三档 | 缺失 |

---

## 3. 关键差距详细分析

### 差距 #U1：autoApprove 全局开关默认值与作用域不同

**严重度**：P3（语义差异，但我的实现更安全）

**Cline 实现**：
- `ToolPolicy.autoApprove` 默认 `true`（shared/llms/tools.ts L17 注释 `@default true`）
- 全局开关通过 `toolPolicies["*"].autoApprove` 控制
- 交互式运行时维护 `autoApproveAllRef.current`（approvals.ts L21-23），初始值取自 `config.toolPolicies["*"]?.autoApprove !== false`
- VSCode 通过 `sdk-tool-policies.ts` 把所有受 AutoApproveBar 控制的工具显式设为 `{autoApprove: false}`，再由 `requestToolApproval` 回调内根据最新 UI 设置决定是否静默通过

**我的实现**：
- `AgentRuntimeConfig.auto_approve: bool = False`（types.py L397）单一全局开关
- 默认 `False`：所有 `requires_approval=True` 的工具都会挂起等待用户审批
- 无 per-tool `autoApprove` 覆盖能力，只能通过 `before_approval` 钩子（`AutoApprovalPolicy`）做模式化决策

**逻辑差异**：
- D1 默认值：Cline 默认 `true`（信任工具），VSCode 显式翻转；我默认 `False`（保守，必须显式开启）
- D2 作用域：Cline 是 per-tool 字段（`toolPolicies[name].autoApprove`），可精细到每个工具；我是全局 bool，全或无
- D3 热切换：Cline 的 `setInteractiveAutoApprove` 可在任务运行中切换；我只能通过环境变量在启动时设定

**影响**：
- 默认值差异不构成安全问题（我的更保守），但与 Cline SDK 直连场景行为不同
- 缺少 per-tool `autoApprove` 覆盖，无法表达"只读工具自动批准、写工具需审批"这类策略（部分由 `AutoApprovalPolicy` 弥补）

**修复建议**：
- 短期：保持 `auto_approve: bool = False` 默认值（更安全）
- 中期：在 `tool_policies` 字典中支持 `autoApprove` 字段，与 Cline ToolPolicy 对齐：
  ```python
  tool_policies = {
      "*": {"autoApprove": False},
      "read_files": {"autoApprove": True},
      "search_codebase": {"autoApprove": True},
  }
  ```
- runtime 中改为读取 `policy.autoApprove` 而非全局 `config.auto_approve`

**优先级**：P3

---

### 差距 #U2：toolPolicies 三态语义不完整

**严重度**：P2（缺少 per-tool autoApprove 覆盖能力）

**Cline 实现**（shared/llms/tools.ts L7-18 + agent-runtime.ts L1396-1413）：
ToolPolicy 三态语义：
- `enabled: false` → **deny**（工具被禁用，直接 skip）
- `autoApprove: false` → **ask**（需用户审批）
- 默认（`enabled` 未设/true 且 `autoApprove` 未设/true）→ **allow**（直接执行）

策略合并：`resolveToolPolicy` 先取 `toolPolicies["*"]`，再覆盖 `toolPolicies[name]`，最后再被 `beforeTool` hook 返回的 `policy` 覆盖（agent-runtime.ts L1397-1400）。

**我的实现**（runtime.py L1182-1187 + base.py L96-103）：
- `tool_policies` 字典仅支持 `{"enabled": False, "reason": ...}` 一种语义（deny）
- "ask" 状态由 `BaseTool.requires_approval` 属性硬编码在每个工具类上，而非策略配置
- 没有 per-tool `autoApprove` 字段
- 策略合并逻辑：`merged = {**global_policy, **policy}`，仅判断 `enabled is False`

**逻辑差异**：
- D1 配置来源：Cline 完全外部配置（`toolPolicies`）；我把"是否需要审批"硬编码在工具类上，策略层只能禁用
- D2 状态数：Cline 三态（allow/ask/deny）；我两态（allow/deny），ask 由工具自描述
- D3 运行时覆盖：Cline 的 `beforeTool` hook 可返回 `policy` 字段覆盖策略；我的 `BeforeToolResult` 无 `policy` 字段

**影响**：
- 无法通过配置运行时切换某工具的审批需求（必须改代码覆盖 `requires_approval`）
- 无法表达"同一工具在不同会话模式下审批策略不同"（Plan Mode 当前用 `enabled: False` 直接禁用，而非 `autoApprove: False` 走审批）

**修复建议**：
- 中期：扩展 `tool_policies` 字典值类型，支持 `{enabled, autoApprove, reason}`：
  ```python
  # Plan 模式下：editor 不走审批直接禁用，run_commands 走审批
  tool_policies = {
      "editor": {"enabled": False, "reason": "Plan 模式禁止编辑"},
      "run_commands": {"autoApprove": False},
  }
  ```
- runtime 中：先判 `enabled is False` → skip；再判 `autoApprove is False` 或 `tool.requires_approval` → 走审批
- 在 `BeforeToolResult` 增加 `policy` 字段，允许 hook 运行时覆盖策略

**优先级**：P2

---

### 差距 #U3：requestToolApproval 回调 vs before_approval hook 架构差异

**严重度**：P3（架构差异，默认流程功能等价）

**Cline 实现**（shared/agent.ts L437-439 + agent-runtime.ts L1424-1462）：
- `requestToolApproval` 是 **config 级回调**，签名 `(request: ToolApprovalRequest) => Promise<ToolApprovalResult>`
- runtime 完全把审批决策委托给该回调：回调返回 `{approved: true}` → 执行；`{approved: false}` → 跳过
- 若未配置回调，runtime 直接返回 `{approved: false, reason: "...no approval callback is configured"}`
- Host（VSCode/CLI）在回调内部实现 UI 弹窗、AutoApproveBar 检查、MCP 工具记忆查询等所有逻辑

**我的实现**（hooks.py L224-251 + runtime.py L1209-1317）：
- `before_approval` 是 **hook**，签名 `(ctx: BeforeApprovalContext) -> BeforeApprovalResult | None`
- hook 仅做**前置自动决策**：返回 `decision="approved"` → 跳过审批直接执行；`decision="denied"` → 跳过；`decision=None` → 继续走默认流程
- 默认流程固化在 runtime 中：`request_approval` → emit `approval_request` 事件 → `await entry.event.wait()` → 读取结果
- 没有把整个审批流程委托给外部回调的能力

**逻辑差异**：
- D1 控制权：Cline 完全委托回调（host 自定义 UI/逻辑）；我把默认流程固化在 runtime，hook 仅前置拦截
- D2 灵活性：Cline 的回调可实现任意 UI（TUI/Web/无 UI）；我的默认流程绑定 SSE + HTTP 端点
- D3 默认行为：Cline 无回调时拒绝；我无 hook 时走用户审批流程

**影响**：
- 功能上等价：默认场景（web UI + 用户点击）两边都能跑通
- Cline 方式更适合多 host（VSCode/CLI/Hub）共用 SDK；我更适合单一 web host
- 我的 hook 机制使自动审批策略（`AutoApprovalPolicy`）与默认用户审批流程解耦，更清晰

**修复建议**：保持现状。如需支持多 host，可考虑增加 `config.request_tool_approval` 回调作为高级覆盖点，但当前 web 场景不需要。

**优先级**：P3

---

### 差距 #U4：Plan Mode 工具策略范围不同

**严重度**：P3（我的实现更严格，非缺陷）

**Cline 实现**（presets.ts L43-55）：
```typescript
plan: {
    enableReadFiles: true,
    enableSearch: true,
    enableBash: true,           // 仍然启用 run_commands
    enableWebFetch: true,
    enableApplyPatch: false,    // 禁用 apply_patch
    enableEditor: false,        // 禁用 editor
    enableSkills: true,
    enableAskQuestion: true,
    enableSubmitAndExit: false,
    enableSpawnAgent: true,
    enableAgentTeams: true,
}
```
- Plan 模式仅禁用 `editor` 和 `apply_patch`（写文件类工具）
- `run_commands` 仍启用，靠模型自律 + auto-approve 策略约束只读命令
- 无独立 `file_write` 工具（写文件统一走 `editor` create 模式）

**我的实现**（server.py L363-372）：
```python
tool_policies = {
    "editor": {"enabled": False, "reason": "Plan 模式下禁止编辑文件"},
    "apply_patch": {"enabled": False, "reason": "Plan 模式下禁止打补丁"},
    "file_write": {"enabled": False, "reason": "Plan 模式下禁止写文件"},
}
```
- 禁用 `editor` / `apply_patch` / `file_write` 三种写工具（我有独立 `file_write` 工具）
- `run_commands` 仍启用，靠 `requires_approval=True` + `AutoApprovalPolicy` 约束只读命令

**逻辑差异**：
- D1 工具集：Cline 无独立 `file_write`；我有，额外禁用
- D2 约束方式：Cline 用 preset 在工具创建阶段过滤；我用 `tool_policies` 在运行时跳过
- D3 一致性：两边都禁用 `editor` + `apply_patch`；我额外禁用 `file_write`（合理增强）

**影响**：
- 我的实现更严格（多禁用 `file_write`），无安全风险
- 实现方式不同：Cline 在工厂阶段过滤（工具不存在）；我在运行时跳过（工具存在但被策略禁用，返回 skip_reason）

**修复建议**：保持现状。我的实现是合理增强。

**优先级**：P3

---

### 差距 #U9：工具分组审批能力薄弱

**严重度**：P2（影响 UX：用户需逐个审批同类工具）

**Cline 实现**（sdk-tool-policies.ts L48-73 + auto-approve.mdx L31-47）：
- `AutoApprovalSettings.actions` 5 个类别开关：
  - `readFiles`：覆盖 read_files / list_files / search_codebase 等
  - `editFiles`：覆盖 editor / replace_in_file / write_to_file / apply_patch / delete_file
  - `executeSafeCommands`：覆盖 run_commands
  - `useBrowser`：覆盖 fetch_web_content / web_fetch / web_search
  - `useMcp`：覆盖所有 MCP 工具
- `isToolAutoApproved` 按类别判断工具是否自动批准
- 用户在 AutoApproveBar 勾选一个类别 → 该类别所有工具共享自动批准状态
- MCP 工具粒度更细：`McpHub.toggleToolAutoApprove(serverName, toolNames, shouldAllow)` 按单个 MCP 工具记忆

**我的实现**（approval_policy.py L34-54）：
- `READ_ONLY_TOOLS` 集合（12 个工具名）：仅用于 `AutoApprovalPolicy` 自动决策
- `WRITE_TOOLS` 集合（3 个工具名）：仅用于"不自动批准，走用户审批"
- 这两个集合是**分类**，不是**分组审批**：用户审批一个写工具后，下一个写工具仍需重新审批
- 无类别级开关，无"勾选一次覆盖一组"能力

**逻辑差异**：
- D1 类别粒度：Cline 5 类 + MCP 细粒度；我 3 类（read/write/run_commands）
- D2 共享状态：Cline 类别开关被同组工具共享；我的分类仅用于自动决策，不共享审批状态
- D3 用户控制：Cline 用户可前端勾选类别；我完全由 `AutoApprovalPolicy` 内部规则决定

**影响**：
- UX 差：用户审批 5 个连续的写操作需点击 5 次（我）；Cline 勾选"Edit project files"一次即可
- 但 Cline 的"始终允许"也是类别级，不能 mid-task 临时批准单个工具

**修复建议**：
- 中期：在审批 UI 增加"始终允许此类工具"复选框，勾选后写入会话级 `auto_approve_groups` 集合
- runtime 在 `_request_tool_approval` 前检查 `tool_name` 是否在 `auto_approve_groups` 中
- 长期：持久化到 `agent_data/state/` 类似 Cline 的 AutoApprovalSettings

**优先级**：P2

---

### 差距 #U10：审批记忆完全缺失

**严重度**：P1（重要 UX 功能，影响生产可用性）

**Cline 实现**：
- VSCode `AutoApprovalSettings` 持久化到工作区状态（`state-keys.ts`），跨会话保留
- `McpHub.toggleToolAutoApprove`（McpHub.ts L1534）按单个 MCP 工具记忆，写入 `mcp_settings.json`
- `applyInteractiveAutoApproveOverride`（tool-policies.ts L50-95）支持任务运行中热切换：调用 `setInteractiveAutoApprove(true)` 后所有工具立即自动批准
- 三层粒度：全局 `autoApproveAllRef` / 类别 `AutoApprovalSettings.actions` / 单工具 `McpHub`
- 详见 `docs/features/auto-approve.mdx`

**我的实现**：
- 完全无持久化审批记忆
- `AGENT_AUTO_APPROVAL` 环境变量三档（off/readonly/all）仅启动时读取，不可运行时切换
- `AutoApprovalPolicy` 的决策基于工具名 + 命令模式匹配，不记忆用户决策
- 每次审批都是一次性的：用户批准 `editor` 后，下次 `editor` 调用仍需重新审批

**逻辑差异**：
- D1 持久化：Cline 跨会话持久；我无持久化
- D2 粒度：Cline 三层（全局/类别/单工具）；我一层（全局环境变量）
- D3 热切换：Cline 支持 mid-task 切换；我不支持
- D4 用户驱动：Cline 用户可前端勾选"始终允许"；我完全由代码规则决定

**影响**：
- 生产 UX 差：每次写文件都需手动批准，长时间任务体验恶劣
- 无法满足"信任此 MCP 工具"这类常见需求
- 与 Cline 的核心卖点（auto-approve）差距最大

**修复建议**：
- 短期：在审批 UI 卡片增加"始终允许此工具"复选框，勾选后写入会话级 set，runtime 检查 set 跳过审批
  ```python
  # approval.py 新增
  _session_auto_approved: dict[str, set[str]] = {}  # session_id → {tool_name}
  def mark_auto_approved(session_id: str, tool_name: str) -> None:
      _session_auto_approved.setdefault(session_id, set()).add(tool_name)
  def is_auto_approved(session_id: str, tool_name: str) -> bool:
      return tool_name in _session_auto_approved.get(session_id, set())
  ```
- 中期：持久化到 `agent_data/state/approval_settings.json`，跨会话保留
- 长期：实现类别级开关 + 前端 AutoApproveBar UI

**优先级**：P1

---

## 4. 一致性统计

| 等级 | 数量 | 占比 | 子项 |
|------|------|------|------|
| 完全一致 | 3 | 30% | U5, U6, U8 |
| 弱对齐 | 5 | 50% | U1, U2, U3, U4, U9 |
| 缺失 | 1 | 10% | U10 |
| 额外增强 | 1 | 10% | U7 |
| **合计** | **10** | **100%** | — |

### 一致性等级判定依据

- **完全一致**：逻辑等价，行为可替换。U5（审批 UI 弹窗 + approve/deny）、U6（5 分钟超时 + 自动拒绝）、U8（approve → 执行，deny → 跳过）三项核心流程行为一致。
- **弱对齐**：同名但行为不同，或部分等价。U1（默认值不同）、U2（三态 vs 两态）、U3（config 回调 vs hook）、U4（禁用工具范围不同）、U9（类别分组能力不同）。
- **缺失**：Cline 有而我没有的功能。U10（持久化审批记忆）。
- **额外增强**：我有而 Cline 没有的合理增强。U7（`before_approval` 独立 hook 点，Cline 仅有 config 回调）。

### 关键差距优先级分布

| 优先级 | 数量 | 子项 |
|--------|------|------|
| P0 | 0 | — |
| P1 | 1 | U10 |
| P2 | 2 | U2, U9 |
| P3 | 3 | U1, U3, U4 |

---

## 5. 修复建议

### 短期（1-2 周内可完成）

1. **U10 审批记忆（会话级）**：在审批 UI 卡片增加"始终允许此工具"复选框，勾选后写入会话级 set。runtime 在 `_request_tool_approval` 入口检查 set 跳过审批。这是 P1 级差距，影响生产 UX，应优先解决。
2. **U6 验证**：确认 300 秒超时在长任务场景下足够（Cline 同 5 分钟），并验证 SSE 断连时前端 `ai-chat.js` L842-845 把 pending 审批标记为 denied 的逻辑稳健。

### 中期（1-2 月）

1. **U2 toolPolicies 三态语义**：扩展 `tool_policies` 字典值支持 `{enabled, autoApprove, reason}` 三字段。runtime 改为：先判 `enabled is False` → skip；再判 `autoApprove is False` 或 `tool.requires_approval` → 走审批。在 `BeforeToolResult` 增加 `policy` 字段，允许 hook 运行时覆盖策略。
2. **U9 类别级分组审批**：定义 5 类工具分组（read/edit/command/browser/mcp），审批 UI 增加"始终允许此类工具"复选框，勾选后整组工具共享自动批准状态。
3. **U1 per-tool autoApprove 覆盖**：配合 U2 改造，支持 `tool_policies["run_commands"] = {"autoApprove": False}` 这类精细配置。

### 长期（3+ 月）

1. **U10 持久化审批记忆**：把会话级 `auto_approve_groups` 持久化到 `agent_data/state/approval_settings.json`，跨会话保留。前端增加 AutoApproveBar 风格的设置面板。
2. **U3 多 host 支持**：如需支持 CLI/TUI 等多 host，可增加 `config.request_tool_approval` 回调作为高级覆盖点，把默认 web 流程作为内置实现。
3. **U10 MCP 工具粒度记忆**：参考 Cline `McpHub.toggleToolAutoApprove`，在 MCP 工具注册时记录 auto-approve 状态，支持按单个 MCP 工具记忆。

---

## 6. 验证记录

### 已验证文件路径

**Cline 源码（参考标准）**：
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\tools\tool-approval.ts`（102 行，桌面 IPC 审批）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\presets.ts`（190 行，5 个预设 + yolo 策略）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts`（937 行，工具工厂）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\llms\tools.ts`（96 行，ToolPolicy/ToolApprovalRequest/ToolApprovalResult 类型定义）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\agent.ts`（L295-439，AgentRuntimeConfig + hooks 接口）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\agents\src\agent-runtime.ts`（L1380-1462，审批检查 + requestToolApproval 调用）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\cli\src\runtime\tool-policies.ts`（95 行，交互式 auto-approve 覆盖）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\cli\src\runtime\interactive\approvals.ts`（66 行，TUI 审批控制器）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\sdk\sdk-tool-policies.ts`（100 行，AutoApprovalSettings → toolPolicies 映射）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\apps\vscode\src\services\mcp\McpHub.ts`（L1534 toggleToolAutoApprove）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\docs\features\auto-approve.mdx`（auto-approve 行为说明）

**我的实现**：
- `e:\jikeAI\code\CASE-AI量化系统\agent\approval.py`（195 行，审批请求生命周期）
- `e:\jikeAI\code\CASE-AI量化系统\agent\approval_policy.py`（224 行，AutoApprovalPolicy 三档策略）
- `e:\jikeAI\code\CASE-AI量化系统\agent\hooks.py`（374 行，BeforeApprovalContext/Result + HookBag）
- `e:\jikeAI\code\CASE-AI量化系统\agent\tools\base.py`（L96-103 requires_approval 属性）
- `e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py`（L1140-1317 审批流程；L1180-1196 策略 + 审批检查）
- `e:\jikeAI\code\CASE-AI量化系统\agent\server.py`（L355-372 Plan Mode 策略；L1095-1102 中止取消审批；L1115-1151 /approve 端点）
- `e:\jikeAI\code\CASE-AI量化系统\agent\types.py`（L370-402 AgentRuntimeConfig）
- `e:\jikeAI\code\CASE-AI量化系统\static\js\ai-chat.js`（L161-275 审批卡片渲染；L690-762 SSE + POST 决策）

### 验证方法

- 静态对比：逐行读取两边源码，标注关键行号
- 逻辑等价性：对每个子项验证"输入相同 → 输出相同"
- 行号引用：所有对比表行号均来自实际读取的源码

### 关键逻辑点验证

| 验证点 | Cline 行号 | 我的位置 | 结论 |
|--------|-----------|---------|------|
| autoApprove 默认值 | shared/llms/tools.ts L17 `@default true` | types.py L397 `False` | 默认值不同（我更保守） |
| 审批触发条件 | agent-runtime.ts L1403 `policy.autoApprove === false` | runtime.py L1192-1193 `requires_approval and not auto_approve` | 触发条件不同（Cline 看策略，我看工具属性） |
| 超时秒数 | tool-approval.ts L74 `5 * 60_000` | approval.py L42 `300.0` | 完全一致（300 秒） |
| 超时行为 | tool-approval.ts L101 `{approved: false, reason: "timed out"}` | runtime.py L1303-1305 返回 skip_reason | 完全一致（自动拒绝） |
| 审批结果传播 | agent-runtime.ts L1409-1412 `!approved` → skipReason | runtime.py L1311-1317 `result == "approved"` → None | 完全一致 |
| Plan Mode 禁用工具 | presets.ts L49-50 `enableEditor: false, enableApplyPatch: false` | server.py L367-371 editor/apply_patch/file_write 全禁用 | 我更严格（多禁 file_write） |
| 全局 auto-approve 切换 | approvals.ts L30-37 `setInteractiveAutoApprove` | 无（仅环境变量启动时设定） | 缺失热切换 |
| per-tool autoApprove | sdk-tool-policies.ts L19-37 `policies[tool] = {autoApprove: false}` | 无（仅全局 auto_approve bool） | 缺失 per-tool 覆盖 |
| 持久化审批记忆 | McpHub.ts L1534 `toggleToolAutoApprove` 写 mcp_settings.json | 无 | 完全缺失 |
| before_approval hook | 无（Cline 仅有 config.requestToolApproval 回调） | hooks.py L224-251 + approval_policy.py | 额外增强 |
| 审批 UI 弹窗 | approvals.ts L9-18 tuiToolApprover；VSCode webview | ai-chat.js L225-275 renderApprovalBlock | 功能等价 |
| 中止取消审批 | 无显式取消（依赖超时） | server.py L1095-1102 cancel_pending_approvals_for_session | 额外增强 |

### 与既有阶段报告的交叉引用

- **Phase E（hooks）#E10**：已详述 `requestToolApproval` 回调 vs `before_approval` hook 的架构差异。本阶段 U3 与 #E10 结论一致：功能等价，架构不同，保持现状。
- **Phase F（tools infra）#F16**：`requires_approval` 属性被标注为"额外增强"。本阶段 U2 进一步分析该属性与 Cline `toolPolicies.autoApprove` 的语义差异。
- **Phase G（builtin tools）#G2.10**：危险命令拦截被标注为"额外增强"。本阶段确认 `AutoApprovalPolicy._DENY_COMMAND_PATTERNS` 与 Cline 无内置黑名单（依赖外部 tool-approval）的差异一致。

---

**阶段 U 结论**：审批机制对齐度约 65%。核心审批流程（U5 UI / U6 超时 / U8 结果传播）完全一致，且我有 `before_approval` 独立 hook 点（U7 额外增强）。主要差距集中在 U10（持久化审批记忆完全缺失，P1）和 U2/U9（toolPolicies 三态语义 + 类别分组能力，P2）。建议短期补齐会话级审批记忆，中期对齐 ToolPolicy 三态语义，长期实现持久化 + 类别级开关。
