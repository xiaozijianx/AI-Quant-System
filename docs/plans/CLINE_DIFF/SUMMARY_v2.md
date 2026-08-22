# Cline 对齐差距总览 v2（Stage 1-8 修复后重新评估）

> 生成时间：2026-07-26
> 评估方法：基于 v1 CLINE_DIFF 26 个 phase 报告，逐项核对当前 agent/ 源码状态
> 评估维度：D1 数据结构 / D2 控制流 / D3 状态变迁 / D4 错误处理 / D5 副作用 / D6 边界条件 / D7 语义等价
> 已完成修复：Stage 1 (P0) + Stage 2-8 (P1/P2/P3)

---

## 一、整体对齐度

**整体对齐度：约 69%**（v1 为 58%，提升 +11%）
**去除有意不实施项后对齐度：约 74%**（排除 Phase V Sub-agent + Phase Y Plugin/Marketplace）

### 1.1 对齐度变化分布

| 对齐度区间 | v1 阶段数 | v2 阶段数 | 变化 |
|-----------|----------|----------|------|
| 90%+ | 0 | 1 | +1（K 100%） |
| 75-89% | 5 | 10 | +5（A/C/D/E/W/O 升入） |
| 60-74% | 9 | 11 | +2 |
| 40-59% | 7 | 2 | -5 |
| <40% | 3 | 2 | -1（Z 升出 40% 以下） |
| 有意不实施 | 2 | 2 | 0（V/Y 保持） |

### 1.2 按 Phase 汇总

| Phase | 主题 | v1 对齐度 | v2 对齐度 | 提升 | 主要修复来源 |
|-------|------|----------|----------|------|-------------|
| A | 类型系统与消息契约 | 50% | 75% | +25% | Stage 2（ImagePart/FilePart + tuple 不可变性） |
| B | AgentRuntime 主循环 | 70% | 80% | +10% | Stage 2.8（assistant-message 事件 + finally 清理） |
| C | 流式工具调用组装 | 75% | 80% | +5% | Stage 2（C3 降级 + C9 确认等价） |
| D | 事件系统 | 65% | 85% | +20% | Stage 2.5/2.8（tool-updated + assistant-message + 4 compaction 事件） |
| E | Hooks 生命周期 | 75% | 85% | +10% | Stage 5.7（BeforeToolResult.policy + 9 hook 字段完整） |
| F | 工具系统基础设施 | 65% | 65% | 0% | 未在 Stage 1-8 范围 |
| G | 内置工具(文件/命令/编辑) | 60% | 78% | +18% | Stage 1 P0 + Stage 3（G1.6 行号 + G3.3 覆盖报错 + G3.6 diff + G4.4 原子回滚） |
| H | 内置工具(搜索/交互/控制) | 75% | 75% | 0% | 未在 Stage 1-8 范围 |
| I | 技能系统 | 60% | 60% | 0% | Stage 3 修复项已实施但报告未覆盖 |
| J | 上下文压缩 | 60% | 75% | +15% | Stage 4.1/4.2/4.7/4.8（should_compact + compaction_summary + 切割边界 + 4 事件） |
| K | Budget Projection | 71% | 100% | +29% | Stage 4.3 + Stage 7.7（完整 4 步流水线 + BudgetAction 跟踪） |
| L | 系统提示构造 | 50% | 65% | +15% | Stage 4.4/4.5/4.6 + Stage 7.3（env IDE + mode tag + git 状态 + AGENTS.md 多位置） |
| M | 循环检测+MistakeTracker | 51% | 70% | +19% | Stage 5.1/5.2（软阈值注入 + force_at_limit + abort 标记） |
| N | AbortController | 60% | 70% | +10% | Stage 7（abort 幂等检查） |
| O | Turn Queue | 50% | 85% | +35% | Stage 1 P0（三重断裂修复：queue 消费闭环 + SSE 事件 + badge UI） |
| P | 文件 Hooks | 50% | 70% | +20% | Stage 5.3/5.4/5.6（fail-open + JSON cancel + 审批记忆） |
| Q | MCP 集成 | 65% | 70% | +5% | Stage 3（per-tool policies enabled=False） |
| R | LLM Provider | 57% | 75% | +18% | Stage 7.8（capabilities + usage 6 字段 + ABORTED 语义） |
| S | 会话持久化 | 64% | 64% | 0% | 未在 Stage 1-8 范围 |
| T | Checkpoint | 60% | 60% | 0% | 未在 Stage 1-8 范围 |
| U | 审批机制 | 65% | 75% | +10% | Stage 5.6/5.7（会话级记忆 + toolPolicies 三态） |
| V | Sub-agent | 10% | 10% | 0% | 有意不实施（P3 决策） |
| W | FileContextTracker | 35% | 85% | +50% | Stage 6（SSE 事件 + 操作类型语义 + source 字段） |
| X | Cline Rules/Frontmatter | 40% | 61% | +21% | Stage 7.1/7.2/7.3/7.4（wcmatch + toggles 持久化 + AGENTS.md 多位置 + excluded_subdirs + mtime 缓存） |
| Y | Plugin/Marketplace | 0% | 0% | 0% | 有意不实施（P3 决策） |
| Z | Telemetry/Hub | 27% | 42% | +15% | Stage 5.8 + Stage 8.6/8.7（PII 脱敏 + metric 接口 + Cron spec） |

---

## 二、Stage 1-8 修复成果验证

### 2.1 P0 紧急修复（Stage 1）— 全部完成

| 修复项 | Phase | 验证结果 |
|--------|-------|---------|
| apply_patch 原子性回滚（两阶段提交） | G4.4 | 已对齐 |
| Turn Queue queue 路径三重断裂 | O4/O7/O12/O13 | 已对齐（queue 消费闭环 + SSE 事件 + badge UI） |

### 2.2 P1 核心架构与稳定性（Stage 2-5）— 全部完成

| Stage | 修复项 | Phase | 验证结果 |
|-------|--------|-------|---------|
| 2.2 | ImagePart/FilePart 数据结构 | A2 | 已对齐 |
| 2.3 | tuple 不可变性（messages/pending_tool_calls） | A20 | 已对齐 |
| 2.5 | tool-updated 事件 | D8 | 已对齐 |
| 2.8 | assistant-message 事件 | B20/D6 | 已对齐 |
| 3.1 | editor 覆盖行为对齐（拒绝覆盖） | G3.3 | 已对齐 |
| 3.2 | read_files 行号输出（cat -n 风格） | G1.6 | 已对齐 |
| 3.3 | editor diff 生成 | G3.6 | 已对齐 |
| 3.4 | apply_patch 原子回滚（多 block 失败零写盘） | G4.4 | 已对齐 |
| 3.5 | 技能 BOM/CRLF 兼容性 | I12 | 已对齐 |
| 3.6 | runningSkills key 规范化 | I6 | 已对齐 |
| 3.7 | allowedSkillNames 多形式匹配 | I8 | 已对齐 |
| 3.8 | MCP per-tool policies enabled=False | Q8 | 部分对齐（auto_approve 未对接 approval 流程） |
| 4.1 | should_compact 纳入 system_prompt | J4 | 已对齐 |
| 4.2 | compaction_summary metadata.kind | J15 | 已对齐 |
| 4.3 | build_budget_projection 4 步流水线 | K7 | 已对齐 |
| 4.4 | env IDE 字段 | L2 | 已对齐 |
| 4.5 | mode tag yolo/mode_notice/最新优先 | L4 | 已对齐 |
| 4.6 | git 状态注入 | L18 | 已对齐 |
| 4.7 | _is_safe_cut_boundary 排除 compaction_summary | J6 | 已对齐 |
| 4.8 | compaction 4 事件 | J20 | 已对齐 |
| 5.1 | 循环检测软阈值注入 LLM 上下文 | M3 | 已对齐 |
| 5.2 | 硬阈值联动 MistakeTracker（force_at_limit） | M4/M10 | 已对齐 |
| 5.3 | 文件 Hooks blocking 默认值 fail-open | P4/P18 | 已对齐 |
| 5.4 | 退出码 JSON cancel 语义 | P8 | 已对齐 |
| 5.6 | 审批记忆会话级持久化 | U10 | 部分对齐（仅会话级，无跨会话持久化） |
| 5.7 | toolPolicies 三态语义 | U2 | 已对齐 |
| 5.8 | telemetry opt-out + PII 脱敏 | Z13 | 已对齐 |

### 2.3 P2 持久化与扩展（Stage 6-7）— 全部完成

| Stage | 修复项 | Phase | 验证结果 |
|-------|--------|-------|---------|
| 6.7 | FileContextTracker SSE 事件 | W11 | 已对齐 |
| 6.8 | 操作类型语义对齐 + source 字段 | W3/W9 | 已对齐 |
| 7.1 | paths glob wcmatch 升级 | X4 | 已对齐 |
| 7.2 | toggles 持久化到 rule_toggles.json | X6 | 已对齐 |
| 7.3 | AGENTS.md 多位置搜索与全局合并 | L14 | 已对齐 |
| 7.4 | cline-rules excluded_subdirs + mtime 缓存 | X11/X12 | 已对齐 |
| 7.5 | 硬阈值 MistakeTracker abort 标记对齐 | M10 | 已对齐 |
| 7.6 | MistakeTracker force_at_limit 参数 | M4 | 已对齐 |
| 7.7 | Budget Projection drop_thinking_blocks action 跟踪 | K6 | 已对齐 |
| 7.8 | LLM Provider capabilities + usage 补全 | R5/R14/R15 | 已对齐 |

### 2.4 P3 长期评估（Stage 8）— 3 项部分实施 + 5 项不实施验证

| Stage | 修复项 | Phase | 验证结果 |
|-------|--------|-------|---------|
| 8.5 | tool presets 文档化 | F12 | 部分对齐（仅文档，不参与运行时过滤） |
| 8.6 | TelemetrySink metric 接口预留 | Z1/Z2 | 部分对齐（接口预留，OTLP 未实现） |
| 8.7 | Cron file-based spec 加载 | Z11 | 部分对齐（file spec + APScheduler，无完整架构） |
| 8.1 | Sub-agent 不实施验证 | V1-V10 | 有意不实施（量化场景不需要） |
| 8.2 | Plugin/Marketplace 不实施验证 | Y1-Y7 | 有意不实施（量化场景不需要） |
| 8.3 | Hub 不实施验证 | Z9/Z10 | 有意不实施（单机场景） |
| 8.4 | subprocess-sandbox 不实施验证 | F11 | 有意不实施（无插件场景） |
| 8.8 | workflows/external-rules 不实施验证 | L9/L10 | 有意不实施（量化场景不需要） |

---

## 三、剩余差距清单（按优先级）

### 3.1 P1 级剩余差距（建议下一轮修复）

| # | Phase | 差距 | 风险 | 工作量 |
|---|-------|------|------|--------|
| 1 | Q8 | MCP per-tool policies `auto_approve=False` 未对接 approval 流程 | 半成品，per-tool 审批未生效 | S |
| 2 | N12 | 子进程 kill on abort 缺失（run_commands 未订阅 abort_signal） | 用户中止后子进程继续运行 | M |
| 3 | S6/S12 | 会话版本迁移机制缺失 | 升级版本号导致历史会话丢失 | M |
| 4 | T3/T6 | Checkpoint git ref 持久化缺失（用悬空 commit） | 长期运行 checkpoint 被 GC 回收 | S |
| 5 | T5 | Checkpoint 回滚联动缺失（消息+文件分离式） | 回滚操作不完整 | M |
| 6 | U10 | 审批记忆仅会话级，无跨会话持久化 | 重启后审批记忆丢失 | S |

### 3.2 P2 级剩余差距（中期修复）

| # | Phase | 差距 | 影响 |
|---|-------|------|------|
| 1 | C8/C18 | 流式 metadata 合并链路未实现（assembly.metadata 字段存在但不填充） | ToolCallPart.metadata 不完整 |
| 2 | C19 | captureUnexpectedReasoningTokens 未实现 | reasoning token 异常未检测 |
| 3 | B9 | reminder 循环前预注入未实现 | 首轮 token 效率问题 |
| 4 | B33 | hook stop 仍分类为 "failed"（未引入 ControlledStopError） | 状态判断偏差 |
| 5 | A7 | AgentToolContext.metadata 字段未补 | 工具上下文元数据缺失 |
| 6 | A16 | AgentRuntimeConfig 缺 initial_messages/plugins/logger/telemetry | 配置字段不全 |
| 7 | J7 | _summarize_tool_activity 行号范围未修复 | 工具活动摘要缺行号 |
| 8 | J12 | agentic 失败 fallback 未透传 abort signal | 压缩中止语义不完整 |
| 9 | J13 | CompactionStateManager 缺 system_prompt 字段 + 投影函数 | 压缩状态不完整 |
| 10 | J18 | _truncate_tool_results 仅处理 string，未处理 file/image | 截断不完整 |
| 11 | P9 | context-injection 在 before_tool 未实际注入 | 上下文注入不完整 |
| 12 | P11/P12/P14 | HookError/HookProcessRegistry/hook 模板缺失 | Hook 基础设施不全 |
| 13 | P16 | hook 并发执行未实施（仍串行） | 性能差异 |
| 14 | Z2 | OTLP exporter 未实现（仅接口预留） | 无法上报 OTLP |
| 15 | Z11 | Cron 完整架构未实现（无 reconcile/materializer/runner） | 仅 file spec + APScheduler |
| 16 | Z3/Z4 | distinctId 未添加 + 事件枚举覆盖率低 | 遥测数据不完整 |
| 17 | X7 | global/local toggle 分离未实现 | toggle 粒度不足 |
| 18 | X10 | skills multi-source + override resolution 未实现 | 技能多目录不支持 |
| 19 | R5 | capabilities 未透传到 AgentModelRequest 供 runtime 路由决策 | 模型能力路由未生效 |
| 20 | R10 | provider-settings 持久化缺失 | 配置不持久化 |
| 21 | G2.3/G2.4/G2.5 | run_commands 运行时行为差距（超时/kill/截断） | 命令执行细节 |
| 22 | G4.1/G4.2/G4.5 | apply_patch 鲁棒性差距（Unicode/上下文匹配） | patch 解析容错 |

### 3.3 有意不实施项（P3 决策，保留未来接入预留）

| Phase | 项目 | 决策理由 |
|-------|------|---------|
| V1-V10 | Sub-agent | 量化任务流水线式，单 agent + SkillsTool 已覆盖 |
| Y1-Y7 | Plugin/Marketplace | 量化扩展以策略代码 + CI 回测为主 |
| Z9/Z10 | Hub 远程运行时 | 单机场景 |
| Z12 | FeatureFlagsService | 无 feature flag 需求 |
| F11 | subprocess-sandbox | 无插件生态 |
| L9/L10 | external-rules/workflows | 量化场景不需要 |
| I17/I18 | 多技能目录/热重载 | 当前单目录够用 |

---

## 四、语义不等价项专项清单（v2）

> 同名但行为不同，需特别关注

| # | Phase | 项目 | v1 状态 | v2 状态 | 风险 |
|---|-------|------|---------|---------|------|
| 1 | A8 | AgentTool.execute 返回类型 | 语义不等价 | 有意不实施（BaseTool 弥补） | 低 |
| 2 | A11 | AgentModelEvent 类型 | 语义不等价 | 有意不实施（功能等价） | 低 |
| 3 | A20 | 消息不可变性 | 语义不等价 | 已对齐（tuple 化） | 已修复 |
| 4 | G2.2 | run_commands 执行模式 | 语义不等价 | 有意不实施（量化场景需命令依赖） | 低 |
| 5 | G3.3 | editor 文件已存在覆盖 | 语义不等价 | 已对齐（改为抛错拒绝） | 已修复 |
| 6 | J4 | 压缩触发条件 | 语义不等价 | 已对齐（含 system_prompt） | 已修复 |
| 7 | J15 | 压缩后消息结构 | 语义不等价 | 已对齐（metadata.kind=compaction_summary） | 已修复 |
| 8 | M3 | 循环检测软阈值 | 语义不等价 | 已对齐（注入 user 消息） | 已修复 |
| 9 | P8 | 文件 Hooks 退出码 | 语义不等价 | 已对齐（JSON cancel 优先） | 已修复 |
| 10 | R14 | LLM abort finish_reason | 语义不等价 | 已对齐（ABORTED） | 已修复 |
| 11 | W3 | FileContextTracker 操作类型 | 语义不等价 | 已对齐（语义文档化 + source 预留） | 已修复 |
| 12 | W9 | FileContextTracker 去重 | 语义不等价 | 已对齐（语义文档化） | 已修复 |
| 13 | X4 | paths glob 匹配 | 语义不等价 | 已对齐（wcmatch 引入） | 已修复 |

**v1 有 13 项语义不等价，v2 修复 10 项，保留 3 项有意不实施。**

---

## 五、合理特化清单（非缺失，量化场景不需要）

| # | Phase | 项目 | 理由 |
|---|-------|------|------|
| 1 | S1/S3 | JSON 文件 + 文件锁替代 SQLite | 量化单机场景，消息量可控 |
| 2 | Q5 | 无 OAuth 支持 | 量化场景以本地 stdio MCP 为主 |
| 3 | Q10 | 无 plugin-server-registration | 无插件生态需求 |
| 4 | V1-V10 | 无 Sub-agent | 量化任务流水线式，单 agent + SkillsTool 已覆盖 |
| 5 | Y1-Y7 | 无 Plugin/Marketplace | 量化扩展以策略代码 + CI 回测为主 |
| 6 | Z9/Z10 | 无 Hub 远程运行时 | 单机场景 |
| 7 | R11 | 无 agent-model-adapter | 无 legacy ApiHandler 适配需求 |

---

## 六、额外增强清单（建议保留）

| # | Phase | 增强项 | 价值 |
|---|-------|--------|------|
| 1 | B18/B24/B27 | invalid_tool_calls 检测、_check_repeated_tool_failures | 稳定性增强 |
| 2 | E8/E9/E10 | prepare_turn_input/format_user_input_block/before_approval hooks | 扩展性增强 |
| 3 | F15/F16 | read_only/requires_approval 属性 | 安全性增强 |
| 4 | G2.10 | 危险命令黑名单（9 个模式） | 安全性增强 |
| 5 | H/D4/D13/D14/D16 | list_files/todo_write/switch_to_plan_mode/web_search 工具 | 功能增强 |
| 6 | I10/I14/I15/I16/I20 | always/scripts 自动发现/keywords/source/build_summary 表格 | 技能系统增强 |
| 7 | K8-K14 | 未来用量投影 + 提前压缩机制 | 上下文管理增强 |
| 8 | L3/L5/L8/L11/L12/L15/L16 | tools_section/MCP 概览/applyTo+mode/always skills/技能目录表格/memory 段/工具描述截断 | 系统提示增强 |
| 9 | Q7/Q12/Q15/Q16 | ${VAR} 解析/真懒连接//mcp/reload/system prompt 概览段 | MCP 增强 |
| 10 | R13 | create_model_from_env | headless 部署友好 |
| 11 | S11/S14 | FileLock 保护/索引内存缓存 | 并发安全 + 性能 |
| 12 | T2/T10 | 消息快照/未跟踪文件处理 | Checkpoint 增强 |
| 13 | W6/W7/W8/W10/W12/W13 | get_state/get_entries/路径规范化/压缩集成/API 端点/原子写入 | FileContextTracker 增强 |
| 14 | Z3 | query_events API | 遥测查询增强 |

---

## 七、关键发现与建议

### 7.1 整体评价

1. **核心架构对齐度优秀**（A-E 平均 81%，v1 为 67%）：类型系统、主循环、流式工具组装、事件系统、Hooks 生命周期与 Cline 逻辑等价度高
2. **工具系统对齐度良好**（F-I 平均 70%，v1 为 65%）：Stage 3 修复了 editor 覆盖、read_files 行号、apply_patch 原子回滚等关键差距
3. **上下文管理对齐度优秀**（J-K 平均 88%，v1 为 66%）：Stage 4+7 全面落地，Budget Projection 达到 100% 对齐
4. **安全机制对齐度良好**（M-P 平均 71%，v1 为 51%）：Stage 5 修复了软阈值注入、硬阈值联动、文件 Hooks fail-open、审批记忆
5. **辅助系统对齐度良好**（O-T 平均 70%，v1 为 58%）：Turn Queue P0 修复使 O 从 50% 跃升至 85%
6. **扩展系统对齐度中等**（U-Z 平均 46%，v1 为 27%）：FileContextTracker 和 Rules 显著提升，Sub-agent/Plugin 保持有意不实施

### 7.2 优势领域

1. **Budget Projection**（K 100%）：完整 4 步流水线 + BudgetAction 跟踪 + 自研未来用量投影增强
2. **Turn Queue**（O 85%）：Stage 1 P0 修复使 queue 消费链路完整闭环
3. **FileContextTracker**（W 85%）：Stage 6 SSE 事件 + 操作类型语义对齐 + source 字段预留
4. **事件系统**（D 85%）：assistant-message + tool-updated + 4 compaction 事件全部补齐
5. **Hooks 生命周期**（E 85%）：9 个 hook 字段完整 + BeforeToolResult.policy + 3 个增强 hook

### 7.3 弱势领域

1. **Sub-agent**（V 10%）：完全缺失（量化场景不需要，合理特化）
2. **Plugin/Marketplace**（Y 0%）：完全缺失（量化场景不需要，合理特化）
3. **Telemetry/Hub**（Z 42%）：OTLP/Cron 完整架构/Hub 仍缺失（部分有意不实施）
4. **技能系统**（I 60%）：Stage 3 修复项已实施但多项 P2 差距未修复
5. **会话持久化**（S 64%）：版本迁移机制缺失（P1 风险）
6. **Checkpoint**（T 60%）：git ref 持久化缺失（P1 风险）

### 7.4 下一步修复策略建议

#### 立即修复（P1，下一轮）
1. **Q8 auto_approve 对接 approval 流程**（半成品补全）
2. **N12 子进程 kill on abort**（用户中止后子进程继续运行）
3. **S6/S12 会话版本迁移机制**（升级会丢数据）
4. **T3/T6 Checkpoint git ref 持久化**（长期运行 checkpoint 失效）
5. **U10 审批记忆跨会话持久化**

#### 短期修复（P2，1-2 周内）
1. **C8/C18 流式 metadata 合并链路**
2. **B33 hook stop 分类为 "completed" 而非 "failed"**
3. **J7 工具活动摘要行号范围**
4. **P9 context-injection 在 before_tool 实际注入**
5. **R5 capabilities 透传到 AgentModelRequest**

#### 中期修复（P2，1 个月内）
1. **Z2 OTLP exporter 完整实现**
2. **Z11 Cron 完整架构（reconcile/materializer/runner）**
3. **X7 global/local toggle 分离**
4. **G2.3/G2.4/G2.5 run_commands 运行时行为**
5. **G4.1/G4.2/G4.5 apply_patch 鲁棒性**

#### 长期评估（P3，按需）
1. **Sub-agent 实现**（量化场景评估后决定）
2. **Plugin/Marketplace**（不建议实现）
3. **Hub 远程运行时**（不建议实现）
4. **技能热重载 + 多技能目录**

---

## 八、对比 v1 → v2 关键指标

| 指标 | v1 | v2 | 变化 |
|------|-----|-----|------|
| 整体对齐度 | 58% | 69% | +11% |
| 去除有意不实施项后对齐度 | 62% | 74% | +12% |
| 90%+ 对齐 Phase 数 | 0 | 1 | +1 |
| 75%+ 对齐 Phase 数 | 5 | 11 | +6 |
| <40% 对齐 Phase 数 | 3 | 2 | -1 |
| P0 差距 | 2 项 | 0 项 | -2（全部修复） |
| 语义不等价项 | 13 项 | 3 项 | -10（10 项已修复） |
| 有意不实施项 | 18 项 | 18 项 | 0（保持决策） |

---

**汇总结束。Stage 1-8 修复后，除有意不实施的 18 项外，核心架构与功能已基本完成逻辑层面的一致性对齐。剩余 P1 差距 6 项 + P2 差距 22 项，建议按优先级逐步推进。**
