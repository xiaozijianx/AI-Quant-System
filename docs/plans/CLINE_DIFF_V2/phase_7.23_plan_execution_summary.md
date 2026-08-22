# Phase 7.23 对比计划执行建议汇总

> 本报告对 Phase 3-7 全部对比计划（P3.1-P3.24 / P4.1-P4.20 / P5.1-P5.23 / P6.1-P6.12 / P7.1-P7.20）的执行情况进行系统总结，并给出后续修复建议、后续对比建议与文档更新建议。
>
> 评估依据：`CLINE_DIFF_V2/` 目录下 99 份阶段对比报告 + Phase 7.20 整体对齐度评估结论 + 各阶段"计划文件关键修正"章节。
>
> 计划文件基线：`AGENT_COMPARISON_PLAN_V2.md` P7.23（L3045-3060）。

---

## 一、执行摘要

Phase 3-7 对比计划已**全部执行完毕**，共生成 99 份阶段对比报告（Phase 3: 24 份 / Phase 4: 20 份 / Phase 5: 23 份 / Phase 6: 12 份 / Phase 7: 20 份），覆盖工具系统、技能系统、System Prompt、AGENTS.md、上下文压缩、Provider、会话持久化、Checkpoint、Hooks、MCP、Telemetry、Connectors、Sub-agent、Plugin、审批、循环检测、Abort、Turn Queue、事件系统共 19 个核心模块。

执行过程中发现计划文件 `AGENT_COMPARISON_PLAN_V2.md` 存在系统性勘误：**25 个阶段的对比表与实际源码不符**，累计约 **60+ 项**错误标注，主要集中在 Phase 5（System Prompt，10 个阶段有勘误）和 Phase 6（AGENTS.md，4 个阶段有勘误）。勘误性质可分为三类：(1) 将 Charles 实际已实现/超越 Cline 的功能误标为"Charles 缺失"（最严重，占 40%）；(2) 将 Cline 未实现/未评估的字段误标为"Cline 支持"（占 30%）；(3) 将 nanobot 的实现误标为 Cline 实现（占 15%）。

整体对齐度结论（来自 P7.20）：**核心 + 辅助模块约 82%**，核心引擎层约 90%，辅助系统层约 66%，生态扩展层约 12%（主动不实施）。Charles 在 14 个维度有独有增强（应予保留，不应对齐回退），2 个 P1 关键缺口需优先修复（Hooks 模块的 abort 接入）。

---

## 二、对比计划执行统计

### 2.1 阶段执行统计

| Phase | 计划阶段数 | 已完成报告数 | 完成率 | 报告目录 |
|-------|-----------|-------------|--------|---------|
| Phase 3（工具系统） | 24 | 24 | 100% | `phase_3.1_*.md` ~ `phase_3.24_*.md` |
| Phase 4（技能系统） | 20 | 20 | 100% | `phase_4.1_*.md` ~ `phase_4.20_*.md` |
| Phase 5（System Prompt） | 23 | 23 | 100% | `phase_5.1_*.md` ~ `phase_5.23_*.md` |
| Phase 6（AGENTS.md） | 12 | 12 | 100% | `phase_6.1_*.md` ~ `phase_6.12_*.md` |
| Phase 7（核心机制） | 20 | 20 | 100% | `phase_7.1_*.md` ~ `phase_7.20_*.md` |
| **合计** | **99** | **99** | **100%** | — |

**关联阶段**（Phase 2 中被 P7.20 引用的 4 个阶段，已在此前完成）：P2.6 / P2.8 / P2.9 / P2.11。

### 2.2 发现差距统计

| 差距类别 | 数量 | 来源 |
|---------|------|------|
| Charles 缺失功能（含主动不实施） | 30 项 | P7.20 §七 |
| Charles 独有增强（应保留） | 14 项 | P7.20 §六 |
| 主动不实施模块 | 3 个（Connectors/Sub-agent/Plugin） | P7.20 §五 |
| P1 关键缺口（需优先修复） | 3 项（Hooks abort × 2 + Provider Anthropic） | P7.20 §七 |
| P2 中等缺口 | 11 项 | P7.20 §七 |
| P3 长尾优化 | 14 项 | P7.20 §七 |
| 计划文件勘误 | 25 个阶段 / 60+ 项 | 本报告 §四 |

### 2.3 模块对齐度分布

| 对齐度区间 | 模块数 | 模块清单 | 占比 |
|-----------|--------|---------|------|
| 高（≥ 85%） | 11 | 工具系统/技能系统/System Prompt/AGENTS.md/上下文压缩/Checkpoint/审批/循环检测/Abort/Turn Queue/事件系统 | 58% |
| 中（60%-85%） | 5 | Provider/会话持久化/Hooks/MCP/Telemetry | 26% |
| 低（< 60%） | 3 | Connectors/Sub-agent/Plugin（主动不实施） | 16% |

---

## 三、计划文件勘误汇总

Phase 3-7 执行过程中发现 `AGENT_COMPARISON_PLAN_V2.md` 共 **25 个阶段**的对比表与实际源码不符，累计约 **60+ 项**错误标注。按严重程度排序如下：

| # | 阶段 | 计划行号 | 勘误数量 | 勘误摘要 | 严重程度 |
|---|------|---------|---------|---------|---------|
| 1 | P3.5 | L747-772 | 8 项 | timeoutMs 默认值错误（60000→实际 30000）；retryable 默认值相反（false→实际 true）；Charles "无 max_retries 字段"（实际有）；Charles "仅 run_commands 有超时"（实际 5 个工具有）；Charles "缺失重试错误判定"（实际 Charles 是唯一有判定的一方）；Charles "缺失重试间隔"（实际 Charles 是唯一有退避的一方）；Cline "withTimeout 包裹全工具"（实际 ask_question 未调用）；Cline "有运行时重试"（实际 Cline 无重试） | **极高**（描述与实际截然相反） |
| 2 | P5.14 | L2061-2081 | 5 项（全部失效） | 5 项差距标注（M1/M2/L7/顺序偏移）全部与实际源码不符：Stage 36.1 (M1) 已补齐 mode_notice；Stage 36.2 (M2) 已补齐 runtime 层包装；L7 已移除工具名列举；段落顺序已对齐 | **高**（差距已全部修复但计划未更新） |
| 3 | P5.12 | L2022-2035 | 7 项 | 将 nanobot 的 MemoryStore 机制误标为 Cline 实现：Memory 段存在性、文件加载、加载时机、段落位置等 7 处标注错误 | **高**（对比基准错误） |
| 4 | P5.8 | L1952-1955 | 3 项 | 5.8.3 rule-conditionals 标注"Charles 缺失"严重错误（实际 Charles 是 Cline 严格超集）；5.8.5 globs 标注"Charles 缺失"事实错误（两者均不评估）；5.8.6 applyTo 标注"Charles 缺失"严重错误（Charles 实现，Cline 未实现） | **高**（系统性误判） |
| 5 | P6.6 | L2362-2379 | 4 项 | 6.6.1 alwaysApply 误导性描述（"已对齐"实为"都不评估"）；6.6.2 applyTo 严重错误（Cline 未实现）；6.6.3 mode 严重错误（Cline 未实现）；6.6.4 globs 事实错误（两者均不评估） | **高**（与 P5.8 同源） |
| 6 | P7.13 | L2829-2837 | 3 项 | 7.13.3 rule-conditionals 严重错误；7.13.6 globs 事实错误；7.13.7 applyTo 严重错误（与 P5.8/P6.1/P6.6 同源，复用了错误前提） | **高**（与 P5.8 同源） |
| 7 | P6.1 | L2243-2250 | 2 项 | `applyTo` 字段虚构（Cline 实际不含此字段）；`globs` 字段未被评估（Cline 解析但不评估，是死字段） | **高**（Cline 字段集合虚构） |
| 8 | P5.10 | — | 4 项（全部错误） | 4 项"已对齐"标注全部错误，应为"未对齐"：always_skills 段 Cline 无此段、Charles 有此段；段落位置错误；Level 2 内容错误 | **高**（与 P4.16 结论自相矛盾） |
| 9 | P5.18 | — | 3 项（全部不准确） | 5.18.1/5.18.2/5.18.3 标注"已对齐"全部不准确：未区分"工具维度"和"System Prompt 段维度"；误将 Charles `always` 等同于 Cline `alwaysEnabled`（语义正交） | **高**（与 P5.10 同源） |
| 10 | P5.22 | L2207-2217 | 3 项 | 5.22.1 env 字段名"Charles 中文"事实错误（生产路径英文）；5.22.5 rules 字段名"Charles 中文"事实错误（占位符+标题英文）；5.22.3 tools 字段名误导（Charles 独有增强层） | 中 |
| 11 | P5.21 | L2182-2206 | 3 项 | 5.21.5"文本块: 无"错误（Charles 有 `##` 标题）；5.21.11"字段名: 中文（部分）"错误（生产路径英文）；5.21.14 描述错误 | 中 |
| 12 | P5.13 | L2051-2057 | 3 项 | 5.13.3 yolo 独立模板"L8 差距"已失效（模板已对齐）；5.13.4 mode_notice"M1 差距"已失效（Stage 36.1 已补齐）；5.13.5 段落位置"顺序偏移"不存在 | 中（差距已修复但计划未更新） |
| 13 | P6.5 | L2352-2358 | 3 项 | 6.5.3 表格使用"Charles 是"错误（双方均无表格）；6.5.4 标题层级"已对齐"错误（Cline 3 级 / Charles 2 级）；6.5.5 代码块双重错误（Cline 用 ```sh 非 ```bash；Charles 无代码块） | 中 |
| 14 | P3.9 | — | 3 项 | 3.9.3 `editor` 工具计划称"无"实际已注册；3.9.11 `attempt_completion` 计划称"已对齐"实际从未注册；3.9.16 `access_mcp_resource` 计划称"无"实际已注册 | 中 |
| 15 | P3.2 | L706-720 | 4 项 | 3.2.1 execute 返回类型描述过时（基于旧版 SDK）；3.2.2 进度更新误判 Charles 缺失；3.2.3 长任务进度误判；3.2.4 AgentToolResult.output 类型描述错误 | 中（基于旧版 SDK） |
| 16 | P3.4 | — | 1 项 | 3.4.7 emit_update 字段标注"Charles 缺失"错误，实际 Charles 已定义且被工具实际使用 | 中 |
| 17 | P3.7 | — | 2 项 | "Charles 有 ToolRegistry 类"不准确（实际无独立类）；P3.7.3 别名描述"Charles 缺失"不准确（Cline Registry 层也无别名） | 中 |
| 18 | P3.11 | — | 2 项 | "asyncio.create_subprocess_exec"与实际不符（实际是 `_shell` 变体）；"Cline SIGTERM → SIGKILL"与实际不符（Cline 只 SIGKILL，Charles 才是两阶段） | 中 |
| 19 | P3.21 | — | 2 项 | "source 字段"不存在（实际无此字段）；"AkShare 后端"不存在（实际是 DuckDuckGo） | 中 |
| 20 | P4.2 | — | 1 项 | 4.2.7 always 字段标注"已对齐"与实际源码不符（实际 Charles 独有，Cline 缺失） | 中 |
| 21 | P4.3 | — | 2 项 | "Cline 有 SkillRegistry 类"不准确（实际无）；"Cline 有 build_summary 方法"不准确（实际无）；4.3.5 always 描述错误 | 中 |
| 22 | P5.1 | L1737-1741 | 1 项 | Cline 实现位置标注错误（应为 `cline.ts` + `session-runtime-orchestrator.ts`，非 `runtime-builder.ts`） | 低 |
| 23 | P5.11 | L2015 | 1 项 | "段落位置 第 9 段"标注错误（Cline 顶层段仅 3 段，扩展 rule 是第 4 段） | 低 |
| 24 | P5.19 | — | 2 项 | 5.19.1 实际不对齐（Cline 不存在 MCP 段条件注入逻辑）；5.19.2 表面对齐但底层机制不同 | 低 |
| 25 | P6.10 | L2436-2452 | 1 项 | "Charles 已对齐（Stage P5.3）：SKILL.md 移除与 AGENTS.md 重复"与实际源码不符（仍有 4 处重复） | 低 |

### 3.1 勘误性质分类

| 勘误性质 | 数量 | 典型案例 |
|---------|------|---------|
| 将 Charles 实际已实现/超越 Cline 的功能误标为"Charles 缺失" | ~24 项 | P5.8.3/5.8.6/6.6.2/6.6.3/7.13.3/7.13.7（applyTo/mode/enabled 评估器 Charles 独有却标注缺失） |
| 将 Cline 未实现/未评估的字段误标为"Cline 支持" | ~18 项 | P3.5（Cline retryable/maxRetries 实际是死字段）；P6.1（Cline applyTo/globs 实际不评估） |
| 将 nanobot 的实现误标为 Cline 实现 | ~9 项 | P5.12（MemoryStore 是 nanobot 机制）；P5.10（always skills 是 nanobot 设计） |
| 差距已修复但计划未更新 | ~7 项 | P5.13/P5.14（M1/M2/L7 已在 Stage 36.x 补齐） |
| 基于旧版 SDK 描述 | ~5 项 | P3.2（execute 返回类型基于旧版 AsyncIterator 描述） |

### 3.2 勘误分布

| Phase | 有勘误的阶段数 | 勘误项总数 |
|-------|--------------|-----------|
| Phase 3 | 7（P3.2/P3.3/P3.4/P3.5/P3.7/P3.9/P3.11/P3.21） | ~22 |
| Phase 4 | 2（P4.2/P4.3） | ~3 |
| Phase 5 | 10（P5.1/P5.8/P5.10/P5.11/P5.12/P5.13/P5.14/P5.18/P5.19/P5.21/P5.22） | ~32 |
| Phase 6 | 4（P6.1/P6.5/P6.6/P6.10） | ~11 |
| Phase 7 | 1（P7.13） | ~3 |
| **合计** | **25** | **~71** |

**Phase 5 勘误最集中**：System Prompt 模块的对比表错误率最高，主要源于：(1) 计划编写时误将 Charles 的增强层（enhancements）当作 Cline 等价物；(2) 误将 nanobot 的 MemoryStore / always_skills 机制当作 Cline 实现；(3) 差距修复后未同步更新计划表。

---

## 四、关键发现总结（Top 10）

### 发现 1：整体对齐度呈"三段式"分布

Charles 与 Cline 的整体对齐度约 **82%**（排除主动不实施的 3 个生态扩展模块）：核心引擎层（11 模块）约 90%，辅助系统层（5 模块）约 66%，生态扩展层（3 模块）约 12%（主动不实施）。这反映了 Charles "Web 应用 + 单进程 + OpenAI 兼容协议 + 量化场景"的架构定位。

### 发现 2：Charles 在 14 个维度有独有增强（应予保留）

Charles 在动态工具注册、工具描述动态生成、AGENTS.md 三类条件评估器（applyTo/mode/enabled）、上下文压缩 5 项扩展、Provider Qwen 稳定性处理、Checkpoint 原子性联动回滚、Hooks 4 项扩展、Telemetry 中国本地化 PII 脱敏、循环检测 per-type 阈值、Abort 优雅 kill、事件系统 emit_sync、Turn Queue drain 重入保护、System Prompt skills 注入（默认关闭）共 14 个维度做了合理增强，**不应对齐回退**至 Cline 行为。

### 发现 3：Hooks 模块有 2 个 P1 关键缺口

Hooks 模块的 `HookProcessRegistry` 未接入 runtime abort 流程（abort 后 hook 子进程仍可能在后台运行）+ `run_hook` 不接受 `abort_signal`（单 hook 无法被中止，仅靠超时 kill）。这两项是影响资源清理与中止语义的关键缺口，建议优先修复。

### 发现 4：Provider 模块覆盖广度差距最大

Charles Provider 仅覆盖 7 个 Provider，Cline 覆盖 40+。Anthropic/Bedrock/Vertex 原生适配完全缺失，导致 Claude 模型丢失 thinking/prompt cache 原生能力。若业务需要 Claude 原生能力，需补齐（P1）。

### 发现 5：3 个生态扩展模块主动不实施（合理偏离）

Connectors（对齐度 20%）、Sub-agent（10%）、Plugin（5%）3 个模块的低对齐度是架构原则驱动的主动选择，非缺陷。Charles 在 Phase 27 主动移除 sub-agent 实现，在 Stage 8 决策"Y 阶段不实施"Plugin。这些差异源于 Charles 是 Web 应用 + 单进程 + 量化场景内部迭代的架构原则。

### 发现 6：计划文件存在系统性勘误（25 个阶段 / 60+ 项）

计划文件 `AGENT_COMPARISON_PLAN_V2.md` 的对比表存在系统性误判，最严重的模式是**将 Charles 实际已实现/超越 Cline 的功能误标为"Charles 缺失"**（占 40%），典型案例如 P5.8/P6.6/P7.13 中 Charles 的 applyTo/mode/enabled 三类条件评估器被反复标注为"Charles 缺失"，实际 Charles 是 Cline 的严格超集。

### 发现 7：P3.5 计划描述与实际代码"截然相反"是最严重勘误

P3.5（超时与重试）章节是所有勘误中最严重的：计划将 Cline 描述为"有重试、Charles 缺失"，实际恰好相反——Cline 的 retryable/maxRetries 是死字段（runtime 从不读取），Charles 才是唯一实现运行时重试（指数退避 0.2×2^n）的一方。这种"截然相反"的勘误会严重误导修复决策。

### 发现 8：nanobot 残留以注释为主，实现逻辑已基本清理

Phase 3-7 各阶段的 nanobot 残留检查显示：实现逻辑残留已基本清理完毕（Sub-agent 主动移除、Plugin 不实施、Rules 段重构完成），剩余残留 95% 以上为 docstring/注释中的"对标 nanobot"历史溯源说明，不影响运行时行为。仅 `agent/skills/registry.py` 等少数文件保留完整的 nanobot 风格实现逻辑（如 always_skills 预加载链路），属 Charles 主动保留的增强功能。

### 发现 9：Phase 5（System Prompt）是勘误重灾区

Phase 5 的 23 个阶段中有 10 个阶段存在勘误（勘误率 43%），累计 32 项错误。根本原因是计划编写时：(1) 误将 Charles 的增强层（enhancements）当作 Cline 等价物；(2) 误将 nanobot 的 MemoryStore/always_skills 机制当作 Cline 实现；(3) Stage 36.x 修复 M1/M2/L7 差距后未同步更新计划表。

### 发现 10：核心引擎层对齐度高（90%），稳定性有保障

工具系统、技能系统、System Prompt、AGENTS.md、上下文压缩、Checkpoint、审批、循环检测、Abort、Turn Queue、事件系统 11 个核心引擎模块的对齐度集中在 85%-96% 区间，且 Charles 在多个维度做了合理增强。这是 Charles 能够稳定运行量化投研场景的基础，核心引擎层无需大规模修复。

---

## 五、后续建议

### 5.1 修复建议（按优先级排序）

#### P1（关键缺口，建议立即修复）

| # | 模块 | 缺口 | 修复方案 | 工作量 | 来源 |
|---|------|------|---------|--------|------|
| 1 | Hooks | HookProcessRegistry 未接入 runtime abort | 在 `agent/runtime.py` 的 abort 流程中调用 `hook_registry.abort_all()`，确保 abort 后清理 hook 子进程 | ~30 行 | P7.7 |
| 2 | Hooks | run_hook 不接受 abort_signal | 修改 `run_hook` 签名增加 `abort_signal: asyncio.Event` 参数，在 hook 执行循环中检查信号 | ~20 行 | P7.7 |
| 3 | Provider | Anthropic 原生适配（若需 Claude 原生能力） | 新增 `AnthropicProvider` 实现 thinking + prompt cache 原生能力 | ~200 行 | P7.4 |

#### P2（中等缺口，建议近期修复）

| # | 模块 | 缺口 | 修复方案 | 工作量 | 来源 |
|---|------|------|---------|--------|------|
| 4 | Provider | 专用错误类型 + onResponseError 钩子 | 定义 `ProviderError` 基类 + 4 个子类（Auth/RateLimit/Network/InvalidRequest） | ~80 行 | P7.4 |
| 5 | 会话持久化 | OCC 乐观锁 + stale 会话回收 | 在 `session.py` 增加 `version` 字段 + UPDATE WHERE version=? 乐观锁；增加 stale 会话定时清理 | ~100 行 | P7.5 |
| 6 | Hooks | Notification + PreCompact 2 类 hook | 新增 `NotificationHook` + `PreCompactHook` 类 | ~60 行 | P7.7 |
| 7 | Hooks | 流式 stdout/stderr 输出 | 修改 `run_hook` 使用 `asyncio.create_subprocess_exec` + 流式读取 | ~50 行 | P7.7 |
| 8 | MCP | 配置可靠性（跨进程锁 + 原子写 + 纯度校验） | `mcp_config.json` 写入用 `tempfile + os.replace` 原子写；增加 `fcntl`/`msvcrt` 文件锁 | ~40 行 | P7.8 |
| 9 | Telemetry | distinctId 持久化（跨会话稳定） | 将 distinctId 持久化到 `global-settings.json` | ~15 行 | P7.9 |
| 10 | 工具系统 | F-base nanobot 清理（base.py 4 处引用） | 清理 `agent/tools/base.py` L2/L11/L37/L188 的 nanobot 注释 | 4 行 | P7.19 |

#### P3（长尾优化，按需执行）

| # | 模块 | 缺口 | 修复方案 | 来源 |
|---|------|------|---------|------|
| 11 | 会话持久化 | session-export + SessionManifest zod 校验 | 新增 `/sessions/<id>/export` 端点 + manifest schema 校验 | P7.5 |
| 12 | Checkpoint | diff 对比视图 + "仅消息回滚"独立模式 | 前端增加 Compare 按钮 + 后端增加 task 模式端点 | P7.6 |
| 13 | Telemetry | OTel SDK 集成深度 + logs/traces exporter | 替换手写 OTLP JSON 为 OTel SDK instrument | P7.9 |
| 14 | 事件系统 | onEvent hook + AgentEvent discriminated union | 新增 onEvent 钩子点 + AgentEvent 改为 Literal 联合类型 | P2.9 |
| 15 | 技能系统 | frontmatter toggle 写入功能 | 新增 `/skills/<name>/toggle` 端点写入 frontmatter | P4.1 |

#### 不修复（合理偏离 / 主动不实施）

- 工具系统的 inputSchema 规范化层、ToolCatalog 抽象层、executor 依赖注入：场景单一，无需补齐。
- 技能系统的全局 skills 目录 + 文件监听热重载：量化场景无需求。
- Provider 的 Gateway 注册机制 + ApiHandler 接口：架构简单无需。
- MCP 的 OAuth 认证 + 插件服务器注册 + first-class 工具暴露：量化场景无需求。
- Connectors/Sub-agent/Plugin 3 个生态扩展模块：架构原则驱动的主动选择。

### 5.2 后续对比建议

#### 建议 1：补充 Phase 1-2 的勘误回扫

本报告仅汇总 Phase 3-7 的勘误。建议后续对 Phase 1（顶层架构）和 Phase 2（核心引擎）的 19 份报告进行同样的勘误回扫，确认是否存在将 Charles 增强误标为缺失、将 nanobot 机制误标为 Cline 实现的系统性问题。

#### 建议 2：建立"计划文件 vs 实际代码"交叉校验机制

勘误的根本原因是计划编写时部分基于推测而非源码核查。建议后续对比计划在编写时即采用"Grep + Read 源码验证 → 标注源码行号 → 填写对比表"的三步流程，避免基于推测或旧版 SDK 描述。

#### 建议 3：对修复后的模块进行回归对比

P1/P2 修复完成后，建议对涉及模块（Hooks/Provider/会话持久化/MCP/Telemetry）进行回归对比，更新对应阶段报告的"一致性总体评估"结论，并同步更新 P7.20 整体对齐度评分。

#### 建议 4：补充 Charles 独有增强的独立报告

Charles 的 14 项独有增强散落在各阶段报告中，建议汇总为独立的 `phase_8_charles_enhancements.md` 报告，明确每项增强的设计动机、实现位置、与 Cline 的差异、保留理由，避免后续对齐工作时误将这些增强"回退"。

#### 建议 5：补充 nanobot 残留清理专项报告

各阶段的 nanobot 残留检查结果分散，建议汇总为独立的 `phase_8_nanobot_residue_audit.md` 报告，按"注释残留 / 实现逻辑残留 / dead code"三类整理，给出统一清理方案。

### 5.3 文档更新建议

#### 建议 1：批量修正计划文件勘误（25 个阶段）

建议在 `AGENT_COMPARISON_PLAN_V2.md` 中新增"勘误汇总"章节，逐项修正本报告 §三列出的 25 个阶段 / 60+ 项勘误。优先修正严重程度"极高/高"的 9 个阶段：P3.5 / P5.8 / P5.10 / P5.12 / P5.14 / P6.1 / P6.6 / P7.13 / P3.2。

#### 建议 2：更新 P7.20 整体对齐度基线

P7.20（L2983-2997）标注的"约 93%（含 prompt 构建层细节差距）"对应核心引擎层维度，但未纳入辅助系统层和生态扩展层的拉低效应。建议更新为分层数据：核心引擎层 90% / 辅助系统层 66% / 生态扩展层 12% / 整体（含主动不实施）72% / 核心+辅助 82%。

#### 建议 3：更新 P7.21 优先级矩阵

P7.21（L2998-3015）的优先级矩阵基于计划表的错误标注，多项差距（M1/M2/L7/L1/L5 等）已在 Stage 36.x 修复或经核查不存在。建议更新优先级矩阵：
- 移除已修复项：M1（mode_notice 已补齐）/ M2（user_input 包装已下沉）/ L7（工具名列举已移除）/ L1（env 字段名已对齐）/ L5（metadata 标签已对齐）/ F-base（可保留，4 行清理）。
- 新增 P1 项：Hooks abort 接入 × 2 / Provider Anthropic 适配。
- 新增 P2 项：Provider 专用错误类型 / 会话持久化 OCC / Hooks Notification+PreCompact / MCP 配置可靠性 / Telemetry distinctId 持久化。

#### 建议 4：更新 P7.22 推荐执行顺序

P7.22（L3017-3038）的 Stage 1（A1 架构重构）已完成（P5.1 确认 SystemPromptBuilder 职责已分离），Stage 2 的 M1/M2/F-base 中 M1/M2 已完成。建议更新执行顺序：
- Stage 1（已完成）：A1 架构重构 + M1 + M2 + L7 + L1 + L5。
- Stage 2（立即执行）：Hooks abort 接入 × 2（P1）+ F-base nanobot 清理（4 行）。
- Stage 3（近期执行）：Provider 错误类型 + 会话持久化 OCC + Hooks 流式输出 + MCP 配置可靠性 + Telemetry distinctId。
- Stage 4（按需执行）：P3 长尾优化项。

#### 建议 5：补充"Charles 独有增强"标注

建议在计划文件中为 Charles 的 14 项独有增强增加"Charles 增强（不应对齐回退）"标注，避免后续对齐工作时误将这些增强"修复"回 Cline 行为。

---

## 六、附录：Phase 3-7 报告索引

### 6.1 Phase 3（工具系统，24 份）

| 阶段 | 报告文件 | 模块归属 |
|------|---------|---------|
| P3.1 | phase_3.1_tool_infrastructure.md | 工具系统 |
| P3.2 | phase_3.2_tool_execute_interface.md | 工具系统 |
| P3.3 | phase_3.3_tool_lifecycle.md | 工具系统 |
| P3.4 | phase_3.4_agent_tool_context.md | 工具系统 |
| P3.5 | phase_3.5_timeout_retry.md | 工具系统 |
| P3.6 | phase_3.6_schema_validation.md | 工具系统 |
| P3.7 | phase_3.7_tool_registry.md | 工具系统 |
| P3.8 | phase_3.8_tool_approval.md | 审批 |
| P3.9 | phase_3.9_builtin_tools_overview.md | 工具系统 |
| P3.10 | phase_3.10_read_files.md | 工具系统 |
| P3.11 | phase_3.11_run_commands.md | 工具系统 |
| P3.12 | phase_3.12_apply_patch.md | 工具系统 |
| P3.13 | phase_3.13_search_codebase.md | 工具系统 |
| P3.14 | phase_3.14_list_files.md | 工具系统 |
| P3.15 | phase_3.15_todo_write.md | 工具系统 |
| P3.16 | phase_3.16_plan_mode.md | 工具系统 |
| P3.17 | phase_3.17_completion_tools.md | 工具系统 |
| P3.18 | phase_3.18_output_limits.md | 工具系统 |
| P3.19 | phase_3.19_mcp_tools.md | MCP |
| P3.20 | phase_3.20_model_tool_routing.md | 工具系统 |
| P3.21 | phase_3.21_web_tool.md | 工具系统 |
| P3.22 | phase_3.22_fetch_web_content.md | 工具系统 |
| P3.23 | phase_3.23_file_write_editor.md | 工具系统 |
| P3.24 | phase_3.24_ask_question_exec_tool.md | 工具系统 |

### 6.2 Phase 4（技能系统，20 份）

| 阶段 | 报告文件 | 模块归属 |
|------|---------|---------|
| P4.1 | phase_4.1_skills_tool.md | 技能系统 |
| P4.2 | phase_4.2_skill_loader.md | 技能系统 |
| P4.3 | phase_4.3_skill_registry.md | 技能系统 |
| P4.4 | phase_4.4_progressive_skill_loading.md | 技能系统 |
| P4.5 | phase_4.5_skill_frontmatter.md | 技能系统 |
| P4.6 | phase_4.6_skill_body_structure.md | 技能系统 |
| P4.7 | phase_4.7_skill_style.md | 技能系统 |
| P4.8 | phase_4.8_stock_price_skill.md | 技能系统 |
| P4.9 | phase_4.9_read_pdf_skill.md | 技能系统 |
| P4.10 | phase_4.10_financial_analysis_skill.md | 技能系统 |
| P4.11 | phase_4.11_write_report_skill.md | 技能系统 |
| P4.12 | phase_4.12_compare_reports_skill.md | 技能系统 |
| P4.13 | phase_4.13_sentiment_analysis_skill.md | 技能系统 |
| P4.14 | phase_4.14_bond_credit_review_skill.md | 技能系统 |
| P4.15 | phase_4.15_web_search_skill.md | 技能系统 |
| P4.16 | phase_4.16_always_skills_section.md | 技能系统 |
| P4.17 | phase_4.17_skills_summary_section.md | 技能系统 |
| P4.18 | phase_4.18_script_invocation_rules.md | 技能系统 |
| P4.19 | phase_4.19_script_implementation_style.md | 技能系统 |
| P4.20 | phase_4.20_nanobot_residue_audit.md | 技能系统 |

### 6.3 Phase 5（System Prompt，23 份）

| 阶段 | 报告文件 | 模块归属 |
|------|---------|---------|
| P5.1 | phase_5.1_system_prompt_builder_architecture.md | System Prompt |
| P5.2 | phase_5.2_prompt_sections_list.md | System Prompt |
| P5.3 | phase_5.3_base_prompt.md | System Prompt |
| P5.4 | phase_5.4_env_section.md | System Prompt |
| P5.5 | phase_5.5_tools_section.md | System Prompt |
| P5.6 | phase_5.6_metadata_section.md | System Prompt |
| P5.7 | phase_5.7_mcp_overview_section.md | System Prompt |
| P5.8 | phase_5.8_cline_rules_section.md | System Prompt |
| P5.9 | phase_5.9_skills_overview_section.md | System Prompt |
| P5.10 | phase_5.10_always_skills_section.md | System Prompt |
| P5.11 | phase_5.11_custom_instructions_section.md | System Prompt |
| P5.12 | phase_5.12_memory_section.md | System Prompt |
| P5.13 | phase_5.13_mode_section.md | System Prompt |
| P5.14 | phase_5.14_user_input_mode_section.md | System Prompt |
| P5.15 | phase_5.15_enhancement_section.md | System Prompt |
| P5.16 | phase_5.16_env_conditional_injection.md | System Prompt |
| P5.17 | phase_5.17_metadata_conditional_injection.md | System Prompt |
| P5.18 | phase_5.18_skills_conditional_injection.md | System Prompt |
| P5.19 | phase_5.19_mcp_conditional_injection.md | System Prompt |
| P5.20 | phase_5.20_mode_conditional_injection.md | System Prompt |
| P5.21 | phase_5.21_prompt_style.md | System Prompt |
| P5.22 | phase_5.22_field_name_language.md | System Prompt |
| P5.23 | phase_5.23_prompt_length.md | System Prompt |

### 6.4 Phase 6（AGENTS.md，12 份）

| 阶段 | 报告文件 | 模块归属 |
|------|---------|---------|
| P6.1 | phase_6.1_agents_frontmatter.md | AGENTS.md |
| P6.2 | phase_6.2_agents_body_structure.md | AGENTS.md |
| P6.3 | phase_6.3_agents_decision_tree.md | AGENTS.md |
| P6.4 | phase_6.4_agents_rules_dedup.md | AGENTS.md |
| P6.5 | phase_6.5_agents_writing_style.md | AGENTS.md |
| P6.6 | phase_6.6_agents_conditional_injection.md | AGENTS.md |
| P6.7 | phase_6.7_agents_loading_mechanism.md | AGENTS.md |
| P6.8 | phase_6.8_agents_rule_name.md | AGENTS.md |
| P6.9 | phase_6.9_agents_rule_toggles.md | AGENTS.md |
| P6.10 | phase_6.10_agents_skill_dedup.md | AGENTS.md |
| P6.11 | phase_6.11_agents_section_order.md | AGENTS.md |
| P6.12 | phase_6.12_agents_verification.md | AGENTS.md |

### 6.5 Phase 7（核心机制，20 份）

| 阶段 | 报告文件 | 模块归属 |
|------|---------|---------|
| P7.1 | phase_7.1_context_compression.md | 上下文压缩 |
| P7.2 | phase_7.2_budget_projection.md | 上下文压缩 |
| P7.3 | phase_7.3_file_context_tracker.md | 上下文压缩 |
| P7.4 | phase_7.4_llm_provider.md | Provider |
| P7.5 | phase_7.5_session_persistence.md | 会话持久化 |
| P7.6 | phase_7.6_checkpoint.md | Checkpoint |
| P7.7 | phase_7.7_file_hooks.md | Hooks |
| P7.8 | phase_7.8_mcp_integration.md | MCP |
| P7.9 | phase_7.9_telemetry.md | Telemetry |
| P7.10 | phase_7.10_connectors_kanban.md | Connectors |
| P7.11 | phase_7.11_sub_agent.md | Sub-agent |
| P7.12 | phase_7.12_plugin_marketplace.md | Plugin |
| P7.13 | phase_7.13_rules_frontmatter_workflows.md | AGENTS.md |
| P7.14 | phase_7.14_approval_mechanism.md | 审批 |
| P7.15 | phase_7.15_loop_detection.md | 循环检测 |
| P7.16 | phase_7.16_abort_controller.md | Abort |
| P7.17 | phase_7.17_turn_queue.md | Turn Queue |
| P7.18 | phase_7.18_event_system.md | 事件系统 |
| P7.19 | phase_7.19_nanobot_residue_cleanup.md | nanobot 残留 |
| P7.20 | phase_7.20_alignment_assessment.md | 整体对齐度 |

### 6.6 关联阶段（Phase 2，被 P7.20 引用）

| 阶段 | 报告文件 | 模块归属 |
|------|---------|---------|
| P2.6 | phase_2.6_restore_abort.md | Abort |
| P2.8 | phase_2.8_loop_detection_mistake_tracker.md | 循环检测 |
| P2.9 | phase_2.9_event_system_emit.md | 事件系统 |
| P2.11 | phase_2.11_turn_queue.md | Turn Queue |

---

## 七、总结

Phase 3-7 对比计划已**100% 执行完毕**，99 份报告覆盖 19 个核心模块，整体对齐度约 82%（核心+辅助模块），核心引擎层达 90%，Charles 在 14 个维度有独有增强。

执行过程中发现计划文件存在 **25 个阶段 / 60+ 项**系统性勘误，主要集中在 Phase 5（System Prompt）和 Phase 6（AGENTS.md），最严重的勘误模式是"将 Charles 实际已实现/超越 Cline 的功能误标为 Charles 缺失"。建议后续优先修复 3 个 P1 关键缺口（Hooks abort 接入 × 2 + Provider Anthropic 适配），并批量修正计划文件勘误以避免误导后续对齐工作。

Charles 的架构定位（Web 应用 + 单进程 + OpenAI 兼容协议 + 量化场景）决定了 3 个生态扩展模块（Connectors/Sub-agent/Plugin）的低对齐度是合理偏离，不应视为缺陷。Charles 的 14 项独有增强是量化场景的合理扩展，应予保留，不应对齐回退至 Cline 行为。
