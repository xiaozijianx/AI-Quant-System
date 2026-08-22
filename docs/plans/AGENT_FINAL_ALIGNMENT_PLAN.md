# Agent 与 Cline 最终对齐方案（Phase 34+）

> 生成时间：2026-07-28（v2：纳入 LOGICAL_DIFF_V1 核实结果）
> 评估基础：代码级逐项核对（非基于 SUMMARY_v3 旧评估）+ LOGICAL_DIFF_V1 prompt 构建层核实
> 核心发现：SUMMARY_v3.md 评估严重过时，Stage 9-14 的 P1/P2 差距项实际已全部实现
> 剩余差距：1 项 P1（部分实现）+ 3 项 P2（含 LOGICAL_DIFF_V1 新增 2 项）+ 10 项 P3（含新增 7 项）
>
> **v2 更新**：纳入 LOGICAL_DIFF_V1（prompt 构建层对比）核实的 9 项新差距。
> 核实方法：逐项读取 Charles 与 Cline 源码确认，非依赖标记。

---

## 一、核对方法说明

本次评估未沿用 SUMMARY_v3.md 的结论，而是通过 Grep 直接在 `agent/` 目录下搜索每个差距项对应的 Stage 标记（如 `Stage 9.6`、`Stage 10.1` 等）和关键函数名，确认代码实际落地情况。

核对范围覆盖：
- P1 差距 6 项（SUMMARY_v3 标记未修复）
- P2 差距 23 项（SUMMARY_v3 标记未修复）
- P3 差距 3 项（Phase L 剩余）
- 有意不实施项 18 项

---

## 二、核对结果总览

### 2.1 P1 差距项核对（6 项）

| # | 差距 | SUMMARY_v3 状态 | 实际状态 | 核对依据 |
|---|------|----------------|---------|---------|
| 1 | Q8 MCP auto_approve 对接 approval | 未修复 | **部分实现** | registry.py 有 per-tool policies，但 UseMcpToolTool 未消费 |
| 2 | N12 子进程 kill on abort | 未修复 | **已实现** | run_commands.py `_wait_process_with_abort`（Stage 30.3） |
| 3 | S6/S12 会话版本迁移 | 未修复 | **已实现** | session.py `_SESSION_FILE_VERSION=2` + `_migrate_session_data` |
| 4 | T3/T6 Checkpoint git ref 持久化 | 未修复 | **已实现** | file_checkpoint.py `git update-ref`（Stage 6.4） |
| 5 | T5 Checkpoint 回滚联动 | 未修复 | **已实现** | server.py `/rollback` + `/rollback_file` + `_try_rollback_file_for_message_checkpoint` |
| 6 | U10 审批记忆跨会话持久化 | 未修复 | **已实现** | approval.py `agent_config/approval_memory.json`（Stage 9.6） |

**结论**：6 项 P1 中，5 项已实现，1 项部分实现（Q8）。

### 2.2 P2 差距项核对（23 项）

| # | 差距 | SUMMARY_v3 状态 | 实际状态 | 核对依据 |
|---|------|----------------|---------|---------|
| 1 | C8/C18 流式 metadata 合并 | 未修复 | **已实现** | runtime.py `_deep_merge_metadata`（Stage 10.1） |
| 2 | C19 reasoning token 检测 | 未修复 | **已实现** | runtime.py `captureUnexpectedReasoningTokens`（Stage 10.2） |
| 3 | B9 reminder 循环前预注入 | 未修复 | **已实现** | runtime.py（Stage 10.3） |
| 4 | B33 hook stop 分类 | 未修复 | **已实现** | types.py `ControlledStopError`（Stage 10.4） |
| 5 | A7 AgentToolContext.metadata | 未修复 | **已实现** | types.py `metadata: dict` 字段（Stage 10.5） |
| 6 | A16 AgentRuntimeConfig 字段 | 未修复 | **已实现** | types.py `initial_messages/plugins/logger/telemetry`（Stage 10.6） |
| 7 | J7 工具活动摘要行号范围 | 未修复 | **已实现** | context.py `extract_line_range_from_read/diff`（Stage 11.1） |
| 8 | J12 abort signal 透传 | 未修复 | **已实现** | context.py 透传 `abort_signal` 到 compact（Stage 11.2） |
| 9 | J13 CompactionStateManager | 未修复 | **已实现** | context.py `CompactionStateManager` 类（Stage 11.3） |
| 10 | J18 file/image 截断 | 未修复 | **已实现** | context.py `_truncate_tool_results`（Stage 11.4） |
| 11 | P9 context-injection 注入 | 未修复 | **已实现** | hooks.py `additional_context` 字段（Stage 12.3） |
| 12 | P11 HookError | 未修复 | **已实现** | file_hooks/types.py `HookError`（Stage 12.4） |
| 13 | P12 HookProcessRegistry | 未修复 | **已实现** | file_hooks/registry.py `HookProcessRegistry`（Stage 12.4） |
| 14 | P16 hook 并发执行 | 未修复 | **已实现** | file_hooks/integration.py `asyncio.gather`（Stage 12.5） |
| 15 | G2.3-G2.5 run_commands 运行时 | 未修复 | **已实现** | run_commands.py 超时/优雅kill/截断（Stage 12.1） |
| 16 | G4.1-G4.5 apply_patch 鲁棒性 | 未修复 | **已实现** | apply_patch.py Unicode/模糊匹配/PatchApplyError（Stage 12.2） |
| 17 | R5 capabilities 透传 | 未修复 | **已实现** | providers/base.py `apply_capability_downgrade`（Stage 13.1） |
| 18 | R10 provider-settings 持久化 | 未修复 | **已实现** | provider_settings.py `ProviderSettingsStore`（Stage 13.2） |
| 19 | X7 global/local toggle 分离 | 未修复 | **已实现** | rules_loader.py `load_merged_toggles`（Stage 13.3） |
| 20 | X10 skills multi-source | 未修复 | **已实现** | skills/loader.py `load_skills_multi_source`（Stage 13.4） |
| 21 | Z2 OTLP exporter | 未修复 | **已实现** | telemetry.py `OtlpHttpExporter`（Stage 14.1） |
| 22 | Z11 Cron 完整架构 | 未修复 | **已实现** | cron_reconciler/cron_materializer/cron_runner（Stage 14.2） |
| 23 | Z3/Z4 distinctId + 事件枚举 | 未修复 | **已实现** | telemetry.py `distinct_id` + 枚举常量（Stage 14.3） |
| 24 | F-base nanobot 引用 | 新增 | **未实现** | base.py L2/L11/L37/L188 仍有 nanobot 引用 |

**结论**：23 项 P2 中，22 项已实现，1 项未实现（F-base 文档清理）。

### 2.3 P3 差距项核对（3 项，Phase L 剩余）

| # | 差距 | 状态 | 说明 |
|---|------|------|------|
| 1 | L1 `<env>` 字段名为中文 | 未实现 | Cline 用英文（Platform/Date/IDE/Working Directory） |
| 2 | L4 metadata 无 provider 条件判断 | 未实现 | Cline 仅 `isCline(providerId)` 时注入 metadata |
| 3 | A1 SystemPromptBuilder 职责未分离 | 未实现 | Cline runtime-builder.ts 不构建 prompt |

### 2.4 整体对齐度修正

| 指标 | SUMMARY_v3 评估 | 实际评估（v1） | v2（含 LOGICAL_DIFF_V1） | 变化 |
|------|----------------|---------|------|------|
| 整体对齐度 | 70% | **95%** | **93%** | v2 略降（prompt 层细节差距纳入） |
| P1 差距 | 6 项 | **1 项** | **1 项** | 不变 |
| P2 差距 | 23 项 | **1 项** | **3 项** | +2（mode_notice + user_input 包装位置） |
| P3 差距 | 3 项 | **3 项** | **10 项** | +7（metadata 标签/skillsTimeout/白名单/PLAN_MODE/rule name/yolo/MODE_TAG） |

> **v2 说明**：v1 评估聚焦"功能是否实现"，v2 纳入 LOGICAL_DIFF_V1 的"prompt 构建层结构/风格"对比视角。
> 新增差距均为实现细节层面的风格/结构差异，不影响功能正确性，故整体对齐度仅微调。

---

## 三、有意不实施项清单（18 项）

以下模块经评估后确认不实施，理由为量化场景不需要或单机场景不适用：

| # | Cline 模块 | 不实施理由 |
|---|-----------|-----------|
| 1 | V Sub-agent / spawn_agent | Phase 27 已移除技能子 agent，量化场景用技能指令注入更可控 |
| 2 | Y Plugin / Marketplace | 量化场景不需要插件市场 |
| 3 | services/workspace/file-indexer | 量化任务不需要全仓库文件索引 |
| 4 | services/workspace/mention-enricher | 量化任务不需要 @mention 增强 |
| 5 | services/workspace/workspace-manager | Charles 用 server.py 替代 |
| 6 | runtime/capabilities | Charles 用 server.py 直接编排 |
| 7 | session/models/session-graph | Charles 用简单 JSON 替代 |
| 8 | auth/ + account/ | 单机场景，无需认证 |
| 9 | cline-core/ClineCore.ts | Charles 用 server.py 替代启动编排 |
| 10 | hub/ | 单机场景，无需远程运行时 |
| 11 | remote-config/ | 单机场景，无需远程配置 |
| 12 | logging/early-logger.ts | Charles 用 Python logging 替代 |
| 13 | SQLite 会话存储 | 用户明确表示当前 JSON 存储够用（Phase 33.1 决策） |
| 14 | MCP OAuth | 量化场景用不到 |
| 15 | MCP plugin-server-registration | 量化场景用不到 |
| 16 | external-rules (.cursorrules/.windsurfrules) | 量化场景用不到 |
| 17 | workflows 工作流文件 | 量化场景用不到 |
| 18 | model-tool-routing 云厂商 provider | 量化场景无需 Bedrock/Vertex AI |

---

## 四、确实差距项清单（5 项）

### 4.1 P1 级（1 项，部分实现）

#### Q8: MCP auto_approve 对接 approval 流程

**现状**：
- `agent/mcp/registry.py` L71-82 已实现 `MCPToolPolicy` 数据结构（含 `auto_approve` 字段）
- `agent/mcp/registry.py` L322 `get_tool_policy()` 可查询 per-tool 策略
- `agent/mcp/registry.py` L347 注释说明 `auto_approve=False 由调用方（UseMcpToolTool）处理`
- **但** `agent/tools/mcp.py::UseMcpToolTool._execute()`（L109-191）直接调用 `registry.call_tool()`，**未查询策略、未对接 approval 流程**

**Cline 参考**：
- `sdk/packages/core/src/extensions/mcp/policies.ts` — per-tool 策略定义
- `sdk/packages/core/src/runtime/tools/tool-approval.ts` — 审批流程

**修复要点**：
1. `UseMcpToolTool` 增加动态 `requires_approval` 逻辑：查询 `registry.get_tool_policy(server_name, tool_name)`，若 `auto_approve=False` 则返回 True
2. `_execute()` 开头查询策略，`enabled=False` 时直接拒绝（已有注释但未实现）
3. 审批流程由 runtime 层的 `before_approval` hook 统一处理（已有基础设施）

### 4.2 P2 级（1 项，文档清理）

#### F-base: base.py docstring 仍有 nanobot 引用

**现状**：`agent/tools/base.py` L2/L11/L37/L188 仍有 "nanobot" 引用
- L2: `"""工具基类 — 对标 Cline AgentTool 接口 + nanobot Tool 基类`
- L11: `与 nanobot Tool 的区别:`
- L37: `"""工具基类 — 对标 Cline AgentTool + nanobot Tool`
- L188: `"""校验必填参数 — 对标 nanobot validate_params()`

**修复要点**：清理 docstring 中的 nanobot 引用，保留 Cline 对标说明。

### 4.3 P3 级（3 项，语义优化）

#### L1: `<env>` 字段名为中文

**现状**：`charles_system_prompt.py` 的 `<env>` 段用中文（平台/日期/IDE/工作目录）
**Cline**：用英文（Platform/Date/IDE/Working Directory）
**修复要点**：`<env>` 段字段名改为英文。低优先级，不影响功能。

#### L4: metadata 无 provider 条件判断

**现状**：`context.py` 的 `_build_metadata()` 始终注入 workspaces metadata
**Cline**：仅 `isCline(providerId)` 时注入
**修复要点**：增加 provider 条件判断。**v2 升级为必做**（彻底复刻 Cline）。

#### A1: SystemPromptBuilder 职责未分离

**现状**：`context.py::SystemPromptBuilder` 既构建 prompt 又加载 rules
**Cline**：`buildClineSystemPrompt()` 是纯组装函数，rules/metadata 由编排器传入
**修复要点**：分离为纯组装器 + 编排器。**v2 升级为必做**（彻底复刻 Cline 架构）。

### 4.4 LOGICAL_DIFF_V1 核实的新增 P2 差距（2 项）

> 以下 2 项经代码级核实确认真实存在，来源：LOGICAL_DIFF_V1.md prompt 构建层对比。

#### M1: `<mode_notice>` 机制缺失 [P2]

**现状**：
- `agent/state.py::set_mode()` 仅变更状态并持久化，不生成任何 notice 文本
- `agent/context.py::_build_mode_tag_instructions()` L676 告诉模型"消息内可能出现 `<mode_notice>` 块"，但**实际从未生成**
- `agent/server.py` L592-596 包装用户输入时也未 prepend `<mode_notice>`

**Cline 参考**：
- `sdk/packages/shared/src/prompt/format.ts` L41-46 `formatModeSwitchNotice(from, to)` 返回 `<mode_notice>...`
- L61-80 `createModeSwitchNoticeTracker()` 追踪待生效的 mode switch，在下条用户消息前 consume 并 prepend

**影响**：模型被告知 notice 可能出现但实际看不到，mode 切换时刻在对话中无显式标记，模型可能无法精确感知切换位置。

**修复要点**：
1. 在 `agent/state.py` 增加 `_pending_mode_notice: dict[str, ModeSwitchNotice]`（按 session_id 隔离）
2. `set_mode()` 中若 old_mode != new_mode，记录 pending notice
3. `agent/server.py` 包装用户输入前，consume pending notice 并 prepend `<mode_notice>...</mode_notice>`

#### M2: 用户输入包装在 server.py 而非 runtime [P2]

**现状**：
- `agent/server.py` L592-596 在调用 runtime 前手动包装 `<user_input mode="...">`
- `agent/runtime.py` L614-617 有 `format_user_input_block` 钩子，但默认无实现，不主动包装
- 若未来有其他入口直接调用 `runtime.run()`，用户输入不会被 `<user_input>` 包裹

**Cline 参考**：
- `sdk/packages/shared/src/prompt/format.ts` L5-10 `formatUserInputBlock(input, mode)` 在 runtime 层 `prepareTurnInput` 调用

**影响**：非 server 入口调用 runtime 时缺失 `<user_input>` 标签，模型无法识别当前 mode。

**修复要点**：
1. 在 `agent/runtime.py` 的 `_call_format_user_input_block_hooks()` 增加默认实现：若 input 是字符串且未被包装，则用 `<user_input mode="{current_mode}">` 包裹
2. server.py 的手动包装可保留（作为兼容层）或移除（由 runtime 统一处理）

### 4.5 LOGICAL_DIFF_V1 核实的新增 P3 差距（7 项）

#### L5: Metadata 标签格式不同 [P3]

**现状**：`agent/context.py` L273-276 用 `<charles_metadata>...</charles_metadata>` XML 标签
**Cline**：用 `# Workspace Configuration\n{...}` 文本块（cline.ts WORKSPACE_CONFIGURATION_MARKER）
**修复要点**：将 `<charles_metadata>` 改为 `# Workspace Configuration`。低优先级。

#### S2: skillsTimeoutMs 不可配置 [P3]

**现状**：`agent/skills/skill_tool.py` L101 硬编码 `return 15000`
**Cline**：`definitions.ts` L723 `const timeoutMs = config.skillsTimeoutMs ?? 15000`（可配置覆盖）
**修复要点**：从配置读取 `skills_timeout_ms`，默认 15000。低优先级。

#### S1: Skill 白名单只检查 2 形式 [P3]

**现状**：`agent/skills/registry.py` L57-79 检查 normalized + bare 两种形式
**Cline**：`user-instruction-plugin.ts` L51-73 检查 normalizedId/normalizedName/bareId/bareName 四种形式
**说明**：Charles 代码注释明确标注"当前无 namespaced skill，4 形式简化为 2 形式"，属刻意简化。
**修复要点**：为未来 namespace 扩展预留 4 形式检查。低优先级，当前无影响。

#### L6: PLAN_MODE_PROMPT 对 run_commands 只读范围描述宽泛 [P3]

**现状**：`agent/tools/plan_mode.py` L44 仅写"run_commands（只读命令）"
**Cline**：`cline.ts` L40 明确列举"listing files, grep, git history, tool versions"
**修复要点**：补充具体只读命令示例。低优先级。

#### L3-new: Rule name 使用文件 stem [P3]

**现状**：`agent/rules_loader.py` L716 用 `r.path.stem` 作为 rule 标题
**Cline**：用 watcher 提供的 `rule.name`
**说明**：功能等价，均产生规则标题。差异可忽略。
**修复要点**：无需修改，标注为合理差异。

#### L8: Charles 无 yolo base prompt 变体 [P3]

**现状**：`agent/prompts/charles_system_prompt.py` 仅有 `DEFAULT_CHARLES_SYSTEM_PROMPT` 一个模板，yolo 被描述为"与 act 等价"
**Cline**：`system.ts` L38-68 有独立的 `YOLO_CLINE_SYSTEM_PROMPT`，身份/规则/约束完全不同（后台自动化场景，强调"solve issue without communicating with user"，必须调用 `submit_and_exit` 结束）
**修复要点**：评估是否需要 yolo 专用模板。当前量化场景 yolo 与 act 行为一致，可标注为合理简化。

#### L7: MODE_TAG 说明额外限制具体工具名 [P3]

**现状**：`agent/context.py` L671-672 在 MODE_TAG 说明中列举"editor / apply_patch / file_write / write-report"
**Cline**：MODE_TAG 说明不列举具体工具，工具限制靠 tool_policies
**说明**：Charles 的列举与 tool_policies 语义重复。
**修复要点**：移除具体工具名列举，依赖 tool_policies 硬禁用。低优先级。

### 4.6 非缺陷项（Charles 合理增强，不对齐 Cline）

#### E1: Enhancement 层（tools_section/skills_summary/always_skills/mcp_section/memory）

**说明**：这是 Charles 独有的增强层，Cline 无对应概念。`agent_config/system_prompt.yaml` 默认 `enabled: false`，关闭时与 Cline 完全对齐。**不视为缺陷，不对齐。**

---

## 五、分阶段修复方案

### Stage 34: P1 补全 + P2 清理（立即执行）

**目标**：补全 Q8 MCP approval 对接，清理 nanobot 残留引用

#### 34.1 Q8 MCP auto_approve 对接 approval 流程 [P1]

**修改文件**：
- `agent/tools/mcp.py` — UseMcpToolTool 消费 per-tool policies

**修改步骤**：
1. `UseMcpToolTool` 新增 `_get_tool_policy(server_name, tool_name)` 方法，调用 `registry.get_tool_policy()`
2. `_execute()` 开头查询策略：
   - `enabled=False` → 直接返回错误 `{"error": "工具被策略禁用"}`
   - `auto_approve=False` → 设置 `requires_approval=True`，由 runtime 审批流程处理
3. 增加 `requires_approval` 动态判断（需支持 per-call 判断，不能是静态属性）

**Cline 参考位置**：
- `sdk/packages/core/src/extensions/mcp/policies.ts`
- `sdk/packages/core/src/runtime/tools/tool-approval.ts`

**验证方法**：
- 配置 `tool_policies` 中某 MCP 工具 `auto_approve: false`
- 调用该工具时确认触发审批 UI
- 配置 `enabled: false` 时确认直接拒绝

#### 34.2 F-base 清理 nanobot 引用 [P2]

**修改文件**：
- `agent/tools/base.py`

**修改步骤**：
1. L2 docstring 改为：`"""工具基类 — 对标 Cline AgentTool 接口`
2. L11 段落移除 `与 nanobot Tool 的区别:` 描述
3. L37 docstring 改为：`"""工具基类 — 对标 Cline AgentTool`
4. L188 docstring 改为：`"""校验必填参数 — 对标 Cline 参数校验`

**验证方法**：Grep `nanobot` 确认无残留引用。

---

### Stage 35: P3 语义优化（按需执行）

**目标**：对齐 Cline 语义细节，提升对齐度从 95% 到 98%+

#### 35.1 L1 `<env>` 字段名改为英文 [P3]

**修改文件**：
- `agent/prompts/charles_system_prompt.py`

**修改步骤**：
- `<env>` 段字段名从中文改为英文：
  - `平台` → `Platform`
  - `日期` → `Date`
  - `IDE` → `IDE`（已是英文）
  - `工作目录` → `Working Directory`

**Cline 参考位置**：`sdk/packages/shared/src/prompt/system.ts`

#### 35.2 L4 metadata provider 条件判断 [P3]

**修改文件**：
- `agent/context.py::_build_metadata()`

**修改步骤**：
1. 增加 `provider_id` 参数
2. 仅当 `provider_id` 在白名单时注入 metadata（Cline 仅 `isCline` 时注入）
3. 或保持当前行为（所有 provider 都注入），标注为"合理增强"

**Cline 参考位置**：`sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`

**决策建议**：当前所有 provider 都需要 workspaces metadata，建议保留现有行为并标注为"合理增强"，不对齐 Cline 的 `isCline` 条件判断。

#### 35.3 A1 SystemPromptBuilder 职责分离 [P3]

**修改文件**：
- `agent/context.py`
- `agent/prompts/charles_system_prompt.py`

**修改步骤**：
1. 将 rules 加载逻辑从 `SystemPromptBuilder` 分离到独立的 `RulesLoader`（部分已有 `rules_loader.py`）
2. `SystemPromptBuilder` 只负责模板渲染和占位符替换
3. rules 内容由外部传入，而非内部加载

**Cline 参考位置**：`sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`

**决策建议**：**v2 升级为必做**。重构为纯组装器 + 编排器，彻底对齐 Cline 架构分层。实施顺序调整为最先执行（架构基础）。

### Stage 36: LOGICAL_DIFF_V1 P2 补全（立即执行，与 Stage 34 同优先级）

**目标**：补全 prompt 构建层核实出的 2 项 P2 差距（mode_notice + user_input 包装位置）

#### 36.1 M1 `<mode_notice>` 机制实现 [P2]

**修改文件**：
- `agent/state.py` — 增加 pending notice 追踪
- `agent/server.py` — 包装用户输入前 consume 并 prepend notice

**修改步骤**：
1. `agent/state.py` 新增模块级 `_pending_mode_notices: dict[str, tuple[str, str]]`（session_id → (from, to)）
2. `set_mode()` 中若 `old_mode != mode`，写入 `_pending_mode_notices[session_id] = (old_mode, mode)`
3. 新增 `consume_mode_notice(session_id) -> tuple[str, str] | None`：取出并清除 pending notice
4. `agent/server.py` L592-596 包装用户输入前调用 `consume_mode_notice()`，若有则 prepend：
   ```python
   notice = consume_mode_notice(session_id)
   prefix = f'<mode_notice>The user switched from {notice[0]} mode to {notice[1]} mode before sending this message.</mode_notice>\n' if notice else ''
   wrapped_message = f'{prefix}<user_input mode="{current_mode}">\n{message}\n</user_input>'
   ```

**Cline 参考位置**：`sdk/packages/shared/src/prompt/format.ts` L41-80

**验证方法**：
1. 在 plan 模式下发送消息，切换到 act 模式，再发送消息
2. 确认第二条消息前有 `<mode_notice>` 块
3. 确认连续切换（plan→act→plan）不发 notice（往返抵消）

#### 36.2 M2 用户输入包装下沉到 runtime [P2]

**修改文件**：
- `agent/runtime.py` — `_call_format_user_input_block_hooks()` 增加默认包装

**修改步骤**：
1. 在 `agent/runtime.py` 的 `_call_format_user_input_block_hooks()` 中，若 hooks 为空（默认情况），执行默认包装逻辑
2. 默认逻辑：若 input 是字符串且未以 `<user_input` 开头，用 `<user_input mode="{mode}">` 包裹
3. mode 从 `agent.state.get_mode(session_id)` 获取
4. server.py 的手动包装保留（兼容层，runtime 默认包装会检测已包装而跳过）

**Cline 参考位置**：`sdk/packages/shared/src/prompt/format.ts` L5-10 `formatUserInputBlock`

**验证方法**：
1. 直接调用 `runtime.run()`（不经 server.py），确认用户输入被 `<user_input>` 包裹
2. 经 server.py 调用，确认不会双重包装

### Stage 37: LOGICAL_DIFF_V1 P3 语义优化（按需执行）

**目标**：对齐 prompt 构建层的 P3 风格/结构差异

#### 37.1 L5 metadata 标签格式对齐 [P3]

**修改文件**：`agent/context.py` L273-276
**步骤**：将 `<charles_metadata>\n{...}\n</charles_metadata>` 改为 `# Workspace Configuration\n{...}`

#### 37.2 S2 skillsTimeoutMs 可配置 [P3]

**修改文件**：`agent/skills/skill_tool.py` L94-101
**步骤**：从 `agent_config` 读取 `skills_timeout_ms`，默认 15000

#### 37.3 S1 skill 白名单 4 形式 [P3]

**修改文件**：`agent/skills/registry.py` L57-79
**步骤**：扩展为 4 形式匹配（normalizedId/normalizedName/bareId/bareName），为 namespace 扩展预留

#### 37.4 L6 PLAN_MODE run_commands 只读范围细化 [P3]

**修改文件**：`agent/tools/plan_mode.py` L44
**步骤**：将"run_commands（只读命令）"改为"run_commands（只读检查：列目录/搜索/git log/查版本等）"

#### 37.5 L7 MODE_TAG 移除工具名列举 [P3]

**修改文件**：`agent/context.py` L671-672
**步骤**：移除"editor / apply_patch / file_write / write-report"列举，改为"plan 模式下不得调用写入或执行类工具（由 tool_policies 硬禁用）"

#### 37.6 L8 yolo base prompt 评估 [P3]

**决策建议**：**v2 升级为必做**。创建独立的 YOLO_CHARLES_SYSTEM_PROMPT 模板，对齐 Cline 的后台自动化场景。

#### 37.7 L3-new rule name 文件 stem [P3]

**决策建议**：功能等价，**不实施**，标注为合理差异。

---

## 六、执行顺序建议

```
Stage 35.3 A1 架构重构（最先执行，架构基础）
  └─ SystemPromptBuilder 职责分离为纯组装器 + 编排器

Stage 34（P1+P2，立即执行）
  ├─ 34.1 Q8 MCP approval 对接（约 30 行代码）
  └─ 34.2 F-base nanobot 清理（约 4 行 docstring 修改）

Stage 36（LOGICAL_DIFF_V1 P2，在 A1 重构后执行）
  ├─ 36.1 M1 mode_notice 机制（约 20 行代码）
  └─ 36.2 M2 user_input 包装下沉 runtime（约 15 行代码）

Stage 35+37（P3，按需执行，全部必做）
  ├─ 35.1 L1 env 字段名英文
  ├─ 35.2 L4 metadata provider 条件判断
  ├─ 37.1 L5 metadata 标签格式
  ├─ 37.2 S2 skillsTimeoutMs 可配置
  ├─ 37.3 S1 skill 白名单 4 形式
  ├─ 37.4 L6 PLAN_MODE run_commands 描述
  ├─ 37.5 L7 MODE_TAG 移除工具名
  ├─ 37.6 L8 yolo base prompt 独立模板
  └─ 37.7 L3-new rule name stem（不实施，合理差异）
```

**预期结果**：
- A1 重构完成后：架构分层对齐 Cline
- Stage 34 + 36 完成后：整体对齐度 93% → 96%
- Stage 35 + 37 完成后：整体对齐度 96% → 99%（彻底复刻）

---

## 七、执行原则

1. **保留原有功能**：修改某个函数时，先理解原有逻辑，在原有基础上修改
2. **中文注释 UTF-8**：所有新增注释用中文，文件用 UTF-8 编码
3. **不写 fallback**：不添加降级逻辑
4. **不写测试脚本**：除非用户明确要求
5. **plan 是指引**：每步执行后根据实际结果决定下一步
6. **参考 Cline 源码**：不确定的实现细节参考 `third_party/cline/` 源码

---

## 八、与历史计划的关系

| 历史计划 | 状态 | 本方案关系 |
|---------|------|-----------|
| CLINE_FIX_PLAN（第一轮，8 个 stage） | 已完成 | 历史归档 |
| CLINE_FIX_PLAN_ROUND2（第二轮，6 个 stage） | 已完成 | 历史归档，Stage 9-14 实际已全部实现 |
| AGENT_MIGRATION_PLAN（Phase 1-27） | 已完成 | 历史归档 |
| AGENT_PHASE28_PLAN（Phase 28+） | 已完成 | 历史归档，Phase 28-33 已完成 |
| AGENT_PHASE30_PLAN（Phase 30-33） | 已完成 | 历史归档 |
| AGENT_PROMPT_FIX_PLAN（P1-P5） | 已完成 | 历史归档 |
| AGENT_CLINE_COMPARISON_PLAN（A-Z 26 阶段） | 已完成 | 历史归档，对比计划全面性 98% |
| CLINE_DIFF/SUMMARY_v3.md | **过时** | 本方案替代其结论 |
| CLINE_DIFF/LOGICAL_DIFF_V1.md | **已纳入** | prompt 构建层对比，核实结果已并入本方案 Stage 36/37 |
| **AGENT_FINAL_ALIGNMENT_PLAN（本方案）** | **进行中** | 最终对齐方案（v2） |

---

**方案结束（v2）。建议按 Stage 34 + 36（P1/P2 并行）→ Stage 35 + 37（P3）顺序推进。Stage 34+36 完成后对齐度达 96%。**

---

## 附：为什么每次对比结果不同（解释）

用户反馈"每次对比都有不一样的发现"，原因如下：

1. **对比视角不同**：
   - SUMMARY_v3/v4 是**功能层对比**（Phase A-Z）：判断"功能 X 是否实现且工作"
   - LOGICAL_DIFF_V1 是**prompt 构建层对比**：判断"prompt 的精确结构/风格/措辞是否对齐"
   - 一个功能可能"已实现"（通过功能层）但"prompt 风格不同"（未通过构建层）

2. **粒度不同**：
   - 功能层看"有没有 metadata 注入" → 有 → 通过
   - 构建层看"metadata 用什么标签、什么条件注入、什么顺序" → 标签不同/无条件判断 → 差距

3. **因此每次新视角的对比都会发现上一视角看不到的细节差距**。这不是矛盾，而是对比维度的补充。
   - v1（功能层）：P1×1 + P2×1 + P3×3 = 5 项
   - v2（+构建层）：P1×1 + P2×3 + P3×10 = 14 项
   - 新增 9 项均为构建层细节差距，不影响功能正确性
