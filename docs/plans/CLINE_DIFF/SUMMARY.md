# Cline 对齐差距总览

> 生成时间：2026-07-26
> 对比范围：26 个阶段（A-Z），覆盖 Agent Runtime 全栈
> 对比方法：逻辑级而非功能级，以 Cline 为参考标准，保留合理增强
> 详细报告：见同目录 `phase_*.md`

---

## 一、整体对齐度

**整体对齐度：约 58%**（按 26 个阶段加权平均，去除合理特化与额外增强后的真实差距）

### 1.1 按对齐度分布

| 对齐度区间 | 阶段数 | 阶段 |
|-----------|--------|------|
| 70%+ | 5 | C(75%)、E(75%)、H(75%)、K(71%)、B(70%) |
| 55-69% | 9 | F(65%)、D(65%)、Q(65%)、U(65%)、S(64%)、R(57%)、J(60%)、G(60%)、N(60%)、T(60%)、I(60%) |
| 40-54% | 7 | M(51%)、O(50%)、L(50%)、P(50%)、A(50%)、X(40%)、W(35%) |
| <40% | 3 | Z(27%)、V(10%)、Y(0%) |

### 1.2 按统计项汇总

| 等级 | 总数 | 占比 |
|------|------|------|
| 完全一致 | 约 105 项 | 23% |
| 弱对齐 | 约 168 项 | 37% |
| 缺失 | 约 95 项 | 21% |
| 语义不等价 | 约 10 项 | 2% |
| 额外增强 | 约 78 项 | 17% |

---

## 二、按模块统计

| 模块 | 阶段 | 完全一致 | 弱对齐 | 缺失 | 额外增强 | 对齐度 |
|------|------|---------|--------|------|---------|--------|
| 类型系统 | A | 6 | 8 | 5 | 2 | 50% |
| 主循环 | B | 9 | 5 | 3 | 4 | 70% |
| 流式工具组装 | C | 8 | 3 | 2 | 1 | 75% |
| 事件系统 | D | 8 | 3 | 3 | 0 | 65% |
| Hooks 生命周期 | E | 6 | 4 | 2 | 3 | 75% |
| 工具基础设施 | F | 5 | 4 | 3 | 2 | 65% |
| 内置工具(文件/命令/编辑) | G | 10 | 15 | 5 | 1 | 60% |
| 内置工具(搜索/交互/控制) | H | 7 | 4 | 0 | 5 | 75% |
| 技能系统 | I | 5 | 7 | 3 | 5 | 60% |
| 上下文压缩 | J | 6 | 12 | 1 | 1 | 60% |
| Budget Projection | K | 5 | 2 | 0 | 7 | 71% |
| 系统提示构造 | L | 2 | 7 | 2 | 7 | 50% |
| 循环检测+MistakeTracker | M | 3 | 5 | 1 | 4 | 51% |
| AbortController | N | 4 | 3 | 3 | 0 | 60% |
| Turn Queue | O | 4 | 4 | 4 | 2 | 50% |
| 文件 Hooks | P | 2 | 9 | 3 | 3 | 50% |
| MCP 集成 | Q | 1 | 8 | 3 | 4 | 65% |
| LLM Provider | R | 4 | 7 | 3 | 1 | 57% |
| 会话持久化 | S | 3 | 6 | 3 | 2 | 64% |
| Checkpoint | T | 2 | 6 | 0 | 2 | 60% |
| 审批机制 | U | 3 | 5 | 1 | 1 | 65% |
| Sub-agent | V | 0 | 3 | 7 | 0 | 10% |
| FileContextTracker | W | 0 | 4 | 1 | 6 | 35% |
| Cline Rules/Frontmatter | X | 1 | 6 | 4 | 3 | 40% |
| Plugin/Marketplace | Y | 0 | 0 | 7 | 0 | 0% |
| Telemetry/Hub | Z | 0 | 6 | 7 | 1 | 27% |

---

## 三、P0 级差距清单（阻塞核心功能正确性）

> **必须立即修复，影响核心功能正确性或生产可用性**

### P0-1：apply_patch 缺少原子性回滚（Phase G #G4.4）

- **位置**：`agent/tools/apply_patch.py`
- **问题**：每个 block 立即写盘，部分失败会导致仓库不一致
- **Cline 实现**：两阶段提交（先解析全部 chunk，全部成功后才写盘）
- **影响**：LLM 生成畸形 patch 时部分文件被修改，需手动恢复
- **修复建议**：实现"先全量解析 + 验证，后批量写盘"模式

### P0-2：Turn Queue queue 路径三重断裂（Phase O #O4/O7/O12/O13）

- **位置**：`agent/server.py` L123-143、`agent/runtime.py`、`static/js/ai-chat.js` L483-514
- **问题**：
  1. `send_callback` 是空操作（仅日志）
  2. run 结束后无代码再次触发 `_schedule_drain()`
  3. 前端不处理 `pending_prompts_drained` 事件，无 badge UI
- **影响**：queue 类型排队消息永不消费，用户输入丢失
- **修复建议**：在 `_sse_generator` 末尾若队列非空，服务端直接循环启动新 run 消费；前端补齐 turn_queue 事件 case + badge UI

---

## 四、P1 级差距清单（影响体验和稳定性）

> **建议短期修复（1-2 周内）**

### 4.1 核心架构层

| # | 阶段 | 差距 | 修复建议 | 工作量 |
|---|------|------|---------|--------|
| 1 | A #A2 | 消息片段类型缺失（Image/File） | 添加 ImagePart/FilePart 数据结构 | S |
| 2 | A #A8/A11/A20 | AgentTool/AgentModelEvent/不可变性语义不等价 | 评估是否对齐，保留合理特化 | M |
| 3 | R #R14 | LLM Provider abort 语义不等价（我用 ERROR，Cline 用 ABORTED） | 修改 `qwen.py`/`openai.py` abort 分支为 `reason=AgentModelFinishReason.ABORTED` | S |
| 4 | R #R5 | capabilities 字段完全缺失 | 在 `ProviderDefaults` 增加 `capabilities: list[str]` | M |
| 5 | R #R15 | usage 字段缺失 cache_write_tokens/reasoning_token_count/total_cost | 补全 OpenAI/Qwen 响应解析 | M |

### 4.2 工具与技能层

| # | 阶段 | 差距 | 修复建议 | 工作量 |
|---|------|------|---------|--------|
| 6 | G #G3.3 | editor 文件已存在且无 old_text 时直接覆盖 | 改为抛错拒绝（安全护栏） | S |
| 7 | G #G2.2 | run_commands 串行执行 vs Cline 并行 | 评估是否改为 `asyncio.gather` 并行 | M |
| 8 | G #G1.6/G3.6 | read_files/editor 不输出行号和 diff | 添加 `cat -n` 风格行号、diff 生成 | M |
| 9 | I #I12 | frontmatter 解析缺 BOM 剥离和 CRLF 支持 | 在 `loader.py` 添加 BOM 剥离 + `\r?\n` 支持 | S |
| 10 | I #I6 | runningSkills 去重 key 未规范化 | 改用 normalized id（小写+去前导斜杠） | S |
| 11 | I #I8 | allowedSkillNames 仅检查 1 种 name 形式 | 补齐 4 种 name 形式检查（含 namespace bare name） | S |
| 12 | Q #Q8 | MCP per-tool policies 完全缺失 | 在 `mcp_servers.yaml` 增加 `tool_policies` 段 | M |

### 4.3 上下文与提示层

| # | 阶段 | 差距 | 修复建议 | 工作量 |
|---|------|------|---------|--------|
| 13 | J #J4 | 压缩触发条件语义不等价（用 total_tokens 而非 requestInputTokens） | 改用含 system prompt + tools 描述的 token 数 | S |
| 14 | J #J15 | 压缩后消息结构不等价（不带 kind metadata） | 添加 `kind: "compaction_summary"` metadata | S |
| 15 | K #K7 | apply_budget_policy 仅实现 4 步流水线的第 1 步 | 补齐 drop_unsafe_blocks/truncate_message_text/drop_message_closure 三步 | M |
| 16 | L #L2 | `<env>` 段缺 IDE 字段 | 补齐 IDE 字段 | S |
| 17 | L #L4 | `<user_input mode>` 标签说明缺 yolo mode/mode_notice 块 | 补齐 mode 标签语义 | S |
| 18 | L #L18 | 缺 git 状态注入 | 补齐 branch/commit/remoteUrls | S |

### 4.4 安全与稳定性层

| # | 阶段 | 差距 | 修复建议 | 工作量 |
|---|------|------|---------|--------|
| 19 | M #M3 | 循环检测软阈值未注入 LLM 上下文 | 将 `verdict.message` 作为 user 消息注入 conversation | S |
| 20 | M #M4 | 硬阈值未联动 MistakeTracker | 增加 `force_at_limit` 参数，经 MistakeTracker 间接 abort | M |
| 21 | P #P4/P18 | 文件 Hooks blocking 默认值不等价（我 fail-closed，Cline fail-open） | 评估是否改为 fail-open | S |
| 22 | P #P8 | 退出码语义不等价（我用 exit 1 表示 block） | 改为仅靠 JSON `cancel: true` 字段决定 block | S |
| 23 | P #P16 | 文件 Hooks 并发模型不等价（我串行，Cline 并行） | 评估是否改为 `asyncio.gather` 并行 | M |
| 24 | U #U10 | 审批记忆完全缺失 | 补齐会话级"始终允许此工具"复选框 | M |
| 25 | Z #Z13 | telemetry 隐私合规风险（无 opt-out、无 PII 脱敏） | 添加 opt-out 开关 + PII 脱敏 | M |

### 4.5 持久化与扩展层

| # | 阶段 | 差距 | 修复建议 | 工作量 |
|---|------|------|---------|--------|
| 26 | S #S6/S12 | 版本迁移完全缺失 | 实现版本迁移注册表 | M |
| 27 | T #T3/T6 | Checkpoint git ref 持久化缺失（用悬空 commit） | 用 `git update-ref refs/cline/checkpoints/{sessionId}/{runCount}` | S |
| 28 | T #T5 | Checkpoint 回滚语义不等价（部分恢复 vs 全工作区恢复） | 实现 `/rollback` 端点联动文件回滚 | M |
| 29 | X #X4 | paths glob 引擎不等价（简化正则 vs picomatch） | 引入 `wcmatch` 或 `pathspec` 库 | S |
| 30 | X #X6 | toggles 仅内存传入，无持久化 | 持久化到 stateManager | M |
| 31 | Z #Z11 | Cron 调度完全缺失（量化场景需要） | 实现定时任务调度 | M |

---

## 五、语义不等价项专项清单

> **同名但行为不同，需特别关注，避免误判为"已实现"**

| # | 阶段 | 项目 | Cline 行为 | 我的行为 | 风险 |
|---|------|------|-----------|---------|------|
| 1 | A #A8 | AgentTool.execute 返回类型 | `Promise<TOutput>` (raw) | `AgentToolResult` (wrapped) | BaseTool 已弥补 |
| 2 | A #A11 | AgentModelEvent 类型 | discriminated union（14 变体） | 单一 dataclass | 类型安全弱 |
| 3 | A #A20 | 消息不可变性 | readonly/freeze | 无保护 | 数据可能被误改 |
| 4 | G #G2.2 | run_commands 执行模式 | `Promise.all` 并行 | `for` 循环串行 | 性能差异 |
| 5 | G #G3.3 | editor 文件已存在覆盖 | 抛错拒绝 | 直接覆盖 | 数据丢失风险 |
| 6 | J #J4 | 压缩触发条件 | `requestInputTokens`（含 system+tools） | `total_tokens`（仅 messages） | 延迟触发 |
| 7 | J #J15 | 压缩后消息结构 | 带 `kind: "compaction_summary"` metadata | 不带 metadata | 切割边界识别错误传导 |
| 8 | M #M3 | 循环检测软阈值 | 注入 user 消息让 LLM 自纠错 | 仅 `logger.warning` | LLM 无感知 |
| 9 | P #P8 | 文件 Hooks 退出码 | 仅靠 JSON `cancel: true` 决定 block | 用 exit code 1 表示 block | 行为不一致 |
| 10 | R #R14 | LLM abort finish_reason | `ABORTED` | `ERROR` | 状态判断错误 |
| 11 | W #W3 | FileContextTracker 操作类型 | 按"谁触发编辑"分类（user_edited/cline_edited） | 按"什么操作"分类（read/edited） | 设计目标不同 |
| 12 | W #W9 | FileContextTracker 去重 | 不去重，标记 stale | 同 path+operation 去重 | 策略相反 |
| 13 | X #X4 | paths glob 匹配 | picomatch（brace/negation/extglob） | 简化正则（仅 `*`/`**`/`?`） | 匹配能力弱 |

---

## 六、合理特化清单（非缺失，量化场景不需要）

> **以下差异标注为"合理特化"，不建议盲目对齐 Cline**

| # | 阶段 | 项目 | 理由 |
|---|------|------|------|
| 1 | S #S1 | JSON 文件替代 SQLite | 量化单机场景，消息量可控 |
| 2 | S #S3 | 文件锁替代 SQLite 锁 | 单机场景够用 |
| 3 | Q #Q5 | 无 OAuth 支持 | 量化场景以本地 stdio MCP 为主 |
| 4 | Q #Q10 | 无 plugin-server-registration | 无插件生态需求 |
| 5 | V #V1-V10 | 无 Sub-agent | 量化任务流水线式，单 agent + SkillsTool 已覆盖 |
| 6 | Y #Y1-Y7 | 无 Plugin/Marketplace | 量化扩展以策略代码 + CI 回测为主 |
| 7 | Z #Z9/Z10 | 无 Hub 远程运行时 | 单机场景 |
| 8 | R #R11 | 无 agent-model-adapter | 无 legacy ApiHandler 适配需求 |

---

## 七、额外增强清单（建议保留）

> **我的实现中有但 Cline 没有的合理增强，建议保留**

| # | 阶段 | 增强项 | 价值 |
|---|------|--------|------|
| 1 | B #B18/B24/B27 | invalid_tool_calls 检测、_check_repeated_tool_failures | 稳定性增强 |
| 2 | E #E8/E9/E10 | prepare_turn_input/format_user_input_block/before_approval hooks | 扩展性增强 |
| 3 | F #F15/F16 | read_only/requires_approval 属性 | 安全性增强 |
| 4 | G #G2.10 | 危险命令黑名单（9 个模式） | 安全性增强 |
| 5 | H #D4/D13/D14/D16 | list_files/todo_write/switch_to_plan_mode/web_search 工具 | 功能增强 |
| 6 | I #I10/I14/I15/I16/I20 | always/scripts 自动发现/keywords/source/build_summary 表格 | 技能系统增强 |
| 7 | K #K8-K14 | 未来用量投影 + 提前压缩机制 | 上下文管理增强 |
| 8 | L #L3/L5/L8/L11/L12/L15/L16 | tools_section/MCP 概览/applyTo+mode/always skills/技能目录表格/memory 段/工具描述截断 | 系统提示增强 |
| 9 | Q #Q7/Q12/Q15/Q16 | ${VAR} 解析/真懒连接//mcp/reload/system prompt 概览段 | MCP 增强 |
| 10 | R #R13 | create_model_from_env | headless 部署友好 |
| 11 | S #S11/S14 | FileLock 保护/索引内存缓存 | 并发安全 + 性能 |
| 12 | T #T2/T10 | 消息快照/未跟踪文件处理 | Checkpoint 增强 |
| 13 | W #W6/W7/W8/W10/W12/W13 | get_state/get_entries/路径规范化/压缩集成/API 端点/原子写入 | FileContextTracker 增强 |
| 14 | Z #Z3 | query_events API | 遥测查询增强 |

---

## 八、修复优先级建议

### 8.1 立即修复（P0，1-2 天）

1. **apply_patch 原子性回滚**（Phase G #G4.4）— 数据安全风险
2. **Turn Queue queue 路径三重断裂**（Phase O #O4/O7/O12/O13）— 用户输入丢失

### 8.2 短期修复（P1，1-2 周）

#### 第 1 周：核心架构与稳定性
1. **LLM Provider abort 语义对齐**（Phase R #R14）— 影响状态判断
2. **循环检测软阈值注入 LLM**（Phase M #M3）— 影响 LLM 自纠错
3. **压缩触发条件对齐**（Phase J #J4）— 影响压缩时机
4. **压缩后消息结构对齐**（Phase J #J15）— 影响切割边界识别
5. **apply_budget_policy 补齐 4 步流水线**（Phase K #K7）— 影响预算裁剪

#### 第 2 周：工具与安全
6. **editor 覆盖行为对齐**（Phase G #G3.3）— 数据丢失风险
7. **read_files/editor 行号和 diff 输出**（Phase G #G1.6/G3.6）— LLM 定位能力
8. **技能系统 BOM/CRLF 兼容性**（Phase I #I12）— Windows 必修
9. **MCP per-tool policies**（Phase Q #Q8）— 安全缺口
10. **审批记忆持久化**（Phase U #U10）— 生产 UX
11. **telemetry 隐私合规**（Phase Z #Z13）— 合规风险

### 8.3 中期修复（P2，1-2 月）

1. **会话版本迁移机制**（Phase S #S6/S12）
2. **Checkpoint git ref 持久化**（Phase T #T3/T6）
3. **Checkpoint 回滚语义对齐**（Phase T #T5）
4. **paths glob 引擎升级**（Phase X #X4）
5. **toggles 持久化**（Phase X #X6）
6. **Cron 调度实现**（Phase Z #Z11）
7. **文件 Hooks 并发模型评估**（Phase P #P16）
8. **run_commands 并行执行评估**（Phase G #G2.2）
9. **capabilities 字段引入**（Phase R #R5）
10. **usage 字段补全**（Phase R #R15）
11. **硬阈值联动 MistakeTracker**（Phase M #M4）
12. **FileContextTracker SSE 事件**（Phase W #W11）

### 8.4 长期评估（P3，按需）

1. **Sub-agent 实现**（Phase V）— 量化场景评估后决定
2. **Plugin/Marketplace**（Phase Y）— 不建议实现
3. **Hub 远程运行时**（Phase Z #Z9/Z10）— 不建议实现
4. **workflows 文件加载**（Phase L #L10）
5. **external-rules 支持**（Phase L #L9）
6. **技能热重载**（Phase I #I18）
7. **多技能目录**（Phase I #I17）
8. **subprocess-sandbox**（Phase F #F11）
9. **tool presets**（Phase F #F12）
10. **OpenTelemetry OTLP 上报**（Phase Z #Z2）

---

## 九、按修复工作量估算

| 工作量 | 数量 | 说明 |
|--------|------|------|
| S（小，<4 小时） | 约 15 项 | 单文件修改，逻辑简单 |
| M（中，1-2 天） | 约 12 项 | 多文件修改，需测试 |
| L（大，1 周以上） | 约 4 项 | 架构性改动 |

**短期修复（P0+P1）总工作量估算**：约 2-3 周（单人）

---

## 十、关键发现与建议

### 10.1 整体评价

1. **核心架构对齐度良好**（B/C/D/E 平均 71%）：主循环、流式工具组装、事件系统、Hooks 生命周期与 Cline 逻辑等价度高
2. **工具系统对齐度中等**（F/G/H/I 平均 65%）：基础设施完善，但内置工具细节（editor 覆盖、apply_patch 原子性）有差距
3. **上下文管理对齐度中等**（J/K/L 平均 60%）：核心机制对齐，但触发条件和消息结构有语义不等价
4. **安全机制对齐度偏低**（M/P/U 平均 55%）：循环检测、文件 Hooks、审批机制有语义不等价
5. **辅助系统对齐度低**（O/Q/S/T/W/X 平均 52%）：Turn Queue 断裂、持久化缺迁移、Rules 引擎弱
6. **可选系统完全缺失**（V/Y/Z 平均 12%）：Sub-agent/Plugin/Hub 量化场景不需要

### 10.2 优势领域

1. **AbortController 机制**（N 60%）：abort 信号透传、throwIfAborted 调用点与 Cline 完全一致
2. **流式工具组装**（C 75%）：PendingToolAssembly 结构、key 选择策略、invalid_tool_calls 检测与 Cline 完全一致
3. **内置工具搜索/交互**（H 75%）：search_codebase、ask_question、submit_and_exit 与 Cline 完全一致，额外增强 list_files/todo_write/switch_to_plan_mode
4. **Budget Projection**（K 71%）：K1-K5 完全一致，K8-K14 是额外增强（Cline 无对应实现）

### 10.3 弱势领域

1. **Turn Queue**（O 50%）：queue 路径三重断裂，用户输入丢失（P0）
2. **FileContextTracker**（W 35%）：设计目标不同（活动日志 vs 过期检测），语义不等价
3. **Cline Rules/Frontmatter**（X 40%）：paths glob 引擎弱、toggles 无持久化、workflows/external-rules 缺失
4. **Sub-agent**（V 10%）：完全缺失（量化场景不需要，合理特化）
5. **Plugin/Marketplace**（Y 0%）：完全缺失（量化场景不需要，合理特化）
6. **Telemetry/Hub**（Z 27%）：核心抽象对齐，但 OTLP/Cron/Hub/FeatureFlags 完全缺失

### 10.4 修复策略建议

1. **优先修复 P0**：apply_patch 原子性、Turn Queue queue 路径
2. **短期集中修复语义不等价项**：LLM abort、循环检测软阈值、压缩触发条件、editor 覆盖行为
3. **中期补齐安全机制**：MCP per-tool policies、审批记忆、telemetry 隐私
4. **长期评估可选系统**：Sub-agent、Plugin、Hub 量化场景不需要，不建议实现
5. **保留合理增强**：read_only/requires_approval、危险命令黑名单、always 技能、Budget Projection、FileLock 等增强应保留

---

## 十一、报告索引

| 阶段 | 报告文件 | 对齐度 |
|------|---------|--------|
| A | [phase_A_types.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_A_types.md) | 50% |
| B | [phase_B_runtime_loop.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_B_runtime_loop.md) | 70% |
| C | [phase_C_streaming_tool.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_C_streaming_tool.md) | 75% |
| D | [phase_D_events.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_D_events.md) | 65% |
| E | [phase_E_hooks.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_E_hooks.md) | 75% |
| F | [phase_F_tools_infra.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_F_tools_infra.md) | 65% |
| G | [phase_G_builtin_tools_file_cmd_edit.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_G_builtin_tools_file_cmd_edit.md) | 60% |
| H | [phase_H_builtin_tools_search_interact.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_H_builtin_tools_search_interact.md) | 75% |
| I | [phase_I_skills.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_I_skills.md) | 60% |
| J | [phase_J_context_compaction.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_J_context_compaction.md) | 60% |
| K | [phase_K_budget_projection.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_K_budget_projection.md) | 71% |
| L | [phase_L_system_prompt.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_L_system_prompt.md) | 50% |
| M | [phase_M_loop_mistake.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_M_loop_mistake.md) | 51% |
| N | [phase_N_abort.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_N_abort.md) | 60% |
| O | [phase_O_turn_queue.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_O_turn_queue.md) | 50% |
| P | [phase_P_file_hooks.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_P_file_hooks.md) | 50% |
| Q | [phase_Q_mcp.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_Q_mcp.md) | 65% |
| R | [phase_R_llm_provider.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_R_llm_provider.md) | 57% |
| S | [phase_S_session_persistence.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_S_session_persistence.md) | 64% |
| T | [phase_T_checkpoint.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_T_checkpoint.md) | 60% |
| U | [phase_U_approval.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_U_approval.md) | 65% |
| V | [phase_V_subagent.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_V_subagent.md) | 10% |
| W | [phase_W_file_context_tracker.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_W_file_context_tracker.md) | 35% |
| X | [phase_X_rules_frontmatter.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_X_rules_frontmatter.md) | 40% |
| Y | [phase_Y_plugin_marketplace.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_Y_plugin_marketplace.md) | 0% |
| Z | [phase_Z_telemetry_hub.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_Z_telemetry_hub.md) | 27% |

---

**汇总结束。建议按"立即修复 P0 → 短期修复 P1 → 中期修复 P2 → 长期评估 P3"的顺序推进改进计划。**
