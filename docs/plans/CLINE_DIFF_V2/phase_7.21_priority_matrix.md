# Phase 7.21 优先级矩阵

> 本报告汇总 Phase 3-7 全部对比阶段（P3.1-P3.24 / P4.1-P4.20 / P5.1-P5.23 / P6.1-P6.12 / P7.1-P7.20）发现的差距，按修复优先级（P0/P1/P2/P3）分级整理，生成修复优先级矩阵。
>
> 数据来源：各阶段对比报告的"修复建议"与"严重度"标注，经交叉核对后去重合并。
>
> 计划文件基线：AGENT_COMPARISON_PLAN_V2.md P7.21（L2998-3016）的优先级矩阵标注了 13 项差距（Q8/F-base/M1/M2/A1/L1/L4/L5/L6/L7/L8/S1/S2/L3-new），其中 M1/M2/L7/A1/L5 等多项已在 Stage 36.1/36.2/A1 等阶段修复，本报告以实际代码对比结论为准。

---

## 一、执行摘要

Phase 3-7 共计 81 个对比阶段，累计发现需修复差距 62 项（去重后），按优先级分布如下：

| 优先级 | 数量 | 性质 | 修复建议 |
|--------|------|------|---------|
| **P0** | 7 项 | 阻塞性问题，影响功能正确性或使技能无法执行 | 立即修复 |
| **P1** | 19 项 | 重要功能缺失或安全加固，影响一致性/安全性 | 短期修复 |
| **P2** | 36 项 | 改进建议，改善健壮性/可观测性/可维护性 | 中期按需修复 |
| **P3** | 若干 | 可选优化/文档修正/合理偏离 | 长期或不修复 |

**关键发现**：

1. **P0 阻塞性问题集中在技能系统**：3 项 SKILL.md 脚本调用缺陷（write-report/sentiment-analysis/bond-credit-review）导致技能无法实际执行，是最高优先级修复项。
2. **P0 还包括路径拼写错误与 nanobot 残留**：P6.7 全局 AGENTS.md 路径 `.agent` 应为 `.agents`；P7.19 的 always 预加载/when_to_use/三段式章节共 42 处 nanobot 风格残留影响 LLM 行为。
3. **P1 安全加固集中在文件工具**：apply_patch/editor/list_files 的 cwd 越界检查缺失（3 项），是安全护栏缺口。
4. **P1 功能缺失集中在 plan_mode 与 hooks**：switch_to_act_mode 自动续跑缺失导致体验割裂；HookProcessRegistry 未接入 runtime abort 导致资源泄漏。
5. **多数 P2 项为已知差异且影响有限**：Charles 量化场景下可接受，按需修复即可。
6. **计划文件原矩阵中 M1/M2/L7/A1/L5 已失效**：这些差距在 Stage 36.1/36.2/A1 等阶段已修复，本报告不再列为待修复项。

---

## 二、优先级定义

| 优先级 | 定义 | 修复时机 | 影响描述 |
|--------|------|---------|---------|
| **P0** | 阻塞性问题 | 立即修复 | 影响功能正确性、使技能无法执行、或存在路径错误导致功能失效 |
| **P1** | 重要功能缺失 | 短期修复（1-2 个迭代） | 影响一致性/安全性/用户体验，缺失安全护栏或核心功能不完整 |
| **P2** | 改进建议 | 中期按需修复 | 改善健壮性/可观测性/可维护性，当前不影响核心功能但有优化空间 |
| **P3** | 可选优化 | 长期或不修复 | 文档修正/合理偏离/生态扩展层主动不实施，Charles 量化场景下无需对齐 |

---

## 三、P0 级差距清单（阻塞性问题）

共 7 项，需立即修复。

### P0-1: write-report SKILL.md 命令参数与脚本不一致

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-1 |
| 来源阶段 | P4.11 |
| 模块 | 技能系统 / write-report |
| 文件 | `agent_config/skills/write-report/SKILL.md` |
| 描述 | SKILL.md Step 4 描述命令参数 `--stock` / `--title`，但脚本 `report_generator.py` 实际接受 `--analysis_file` / `--output_dir`，参数完全不匹配 |
| 影响 | agent 按 SKILL.md 调用脚本会直接报错，技能无法实际执行 |
| 修复难度 | 低（改 SKILL.md 参数描述，约 5 行） |
| 建议方案 | 方案 A（改 SKILL.md）：将 Step 4 命令改为 `python agent_config/skills/write-report/scripts/report_generator.py --analysis_file <分析结果JSON> --output_dir output/` |

### P0-2: sentiment-analysis SKILL.md 命令参数与脚本不一致

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-2 |
| 来源阶段 | P4.13 |
| 模块 | 技能系统 / sentiment-analysis |
| 文件 | `agent_config/skills/sentiment-analysis/SKILL.md` |
| 描述 | SKILL.md Step 2/3 描述命令参数 `--stock`，但脚本 `sentiment_scorer.py` / `event_detector.py` 实际接受 `--news_file`，参数不匹配 |
| 影响 | agent 按 SKILL.md 调用脚本会报错，技能无法实际执行 |
| 修复难度 | 低（改 SKILL.md 参数描述，约 5 行） |
| 建议方案 | 方案 A（改 SKILL.md）：将 Step 2/3 命令改为 `--news_file data/<股票代码>_news.json`，并在 Step 1 明确输出文件路径 |

### P0-3: bond-credit-review 脚本不存在

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-3 |
| 来源阶段 | P4.14 |
| 模块 | 技能系统 / bond-credit-review |
| 文件 | `agent_config/skills/bond-credit-review/SKILL.md` |
| 描述 | SKILL.md Step 2 描述调用 `bond_credit_review.py`，但 `scripts/` 目录不存在，脚本未实现 |
| 影响 | agent 按 SKILL.md 调用会因 FileNotFoundError 报错，技能无法执行；原版 charles-nanobot 为纯 LLM 流程，agent_config 版主动引入脚本调用属于过度设计 |
| 修复难度 | 中（需实现脚本或移除脚本调用） |
| 建议方案 | 方案 A：实现 `bond_credit_review.py` 脚本；方案 B：移除脚本调用，回退为纯 LLM 描述性流程（与原版一致） |

### P0-4: 全局 AGENTS.md 路径拼写错误

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-4 |
| 来源阶段 | P6.7 |
| 模块 | AGENTS.md 加载机制 |
| 文件 | `agent/context.py` L472 |
| 描述 | Charles 全局 AGENTS.md 路径用 `.agent`，Cline 用 `.agents`（复数），拼写不一致导致无法读取 Cline 生态全局规则 |
| 影响 | 全局规则文件无法被正确发现和加载 |
| 修复难度 | 极低（一行修改） |
| 建议方案 | 将 `.agent` 改为 `.agents` |

### P0-5: always 预加载机制 nanobot 残留

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-5 |
| 来源阶段 | P7.19 |
| 模块 | 技能系统 / nanobot 残留 |
| 文件 | `skills/loader.py` + `registry.py` + `context.py` + `read-pdf/SKILL.md` |
| 描述 | always 预加载机制（7 处残留）源自 nanobot 设计模式，Cline 无等价物，与 Cline on-demand 设计哲学冲突，影响 LLM 行为 |
| 影响 | 默认关闭（`enhancements.enabled=false`）不影响运行时，但 docstring 误导性标注"对标 Cline" |
| 修复难度 | 中 |
| 建议方案 | 方案 A（推荐）：保留但修正 docstring 为"Charles 独有增强"；方案 B：严格对齐 Cline 移除 always 机制 |

### P0-6: when_to_use 字段 nanobot 残留

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-6 |
| 来源阶段 | P7.19 |
| 模块 | 技能系统 / nanobot 残留 |
| 文件 | `skills/loader.py` + `registry.py` + 8 个 SKILL.md |
| 描述 | when_to_use 字段（11 处残留）是 nanobot frontmatter 规范字段，Cline 用 description 内 "Use when ..." 句式代替，Charles agent_config 版主动引入 |
| 影响 | frontmatter 字段集与 Cline 不一致，影响 LLM 对技能触发时机的理解 |
| 修复难度 | 中 |
| 建议方案 | 将 8 个 SKILL.md 的 when_to_use 内容合并到 description 字段，采用 "Use when ..." 句式，移除 when_to_use 字段 |

### P0-7: SKILL.md 三段式章节 nanobot 残留

| 属性 | 值 |
|------|-----|
| 差距 ID | P0-7 |
| 来源阶段 | P7.19 |
| 模块 | 技能系统 / nanobot 残留 |
| 文件 | 8 个 SKILL.md |
| 描述 | 24 处三段式章节（脚本角色说明 / 脚本调用规则 / 禁止行为）是 nanobot 习惯，Cline 把这些信息嵌入 Workflow Step（用 "Always ..." / "Do not ..." 句式） |
| 影响 | SKILL.md 主体结构与 Cline 风格不一致，影响 LLM 对工作流的理解 |
| 修复难度 | 高（需重构 8 个 SKILL.md） |
| 建议方案 | 重构为 Workflow Step 内嵌说明，用 "Always ..." / "Do not ..." 句式替代独立章节 |

---

## 四、P1 级差距清单（重要功能缺失）

共 19 项，建议短期修复。

### P1-1: apply_patch cwd 越界检查缺失

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-1 |
| 来源阶段 | P3.12 |
| 模块 | 工具系统 / apply_patch |
| 文件 | `agent/tools/apply_patch.py` |
| 描述 | `_compute_*_change` 入口无 cwd 越界检查，Cline 默认开启 `restrictToCwd` |
| 影响 | 安全加固缺口，patch 可写入 cwd 外文件 |
| 修复难度 | 低（5-10 行） |
| 建议方案 | 在入口加 cwd 越界检查（若 `Path(path_str).resolve().relative_to(cwd)` 抛 ValueError 则拒绝） |

### P1-2: editor/file_write cwd 越界检查缺失

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-2 |
| 来源阶段 | P3.23 |
| 模块 | 工具系统 / editor + file_write |
| 文件 | `agent/tools/file_tools.py`（EditorTool / FileWriteTool） |
| 描述 | EditorTool._execute 和 FileWriteTool._execute 入口无 cwd 越界检查，与 P1-1 同源 |
| 影响 | 安全加固缺口，编辑/写入可操作 cwd 外文件 |
| 修复难度 | 低（5-10 行） |
| 建议方案 | 与 P1-1 一致，统一补齐 cwd 越界检查 |

### P1-3: list_files 受限路径保护缺失

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-3 |
| 来源阶段 | P3.14 |
| 模块 | 工具系统 / list_files |
| 文件 | `agent/tools/list_files.py` |
| 描述 | `_execute` 入口无受限路径检查，Cline 有 `deniedDirectories` / `allowedDirectories` 机制 |
| 影响 | 安全护栏缺口，可列出敏感目录 |
| 修复难度 | 低（10-15 行） |
| 建议方案 | 在 `_execute` 入口增加受限路径检查 |

### P1-4: read_files 常量未统一管理

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-4 |
| 来源阶段 | P3.10 |
| 模块 | 工具系统 / read_files |
| 文件 | `agent/tools/read_files.py` |
| 描述 | `read_files.py` 使用本地 `_MAX_CHARS_PER_FILE` 常量，未引用 `constants.py` 的 `MAX_READ_OUTPUT_CHARS` |
| 影响 | 常量分散管理，维护成本高 |
| 修复难度 | 极低（2-3 行） |
| 建议方案 | 引入 `from agent.tools.constants import MAX_READ_LINES, MAX_READ_OUTPUT_CHARS`，统一常量引用 |

### P1-5: search_codebase 单查询容错缺失

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-5 |
| 来源阶段 | P3.13 |
| 模块 | 工具系统 / search_codebase |
| 文件 | `agent/tools/search_codebase.py` |
| 描述 | 一个错误的正则 pattern 会导致全部查询失败，Cline 为 best-effort（跳过失败 query） |
| 影响 | 单个错误 pattern 中断整个搜索，LLM 体验差 |
| 修复难度 | 低（10-15 行） |
| 建议方案 | 在预编译阶段收集编译失败的 query，搜索阶段跳过，结果中为失败 query 返回 error 信息 |

### P1-6: switch_to_act_mode 自动续跑缺失

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-6 |
| 来源阶段 | P3.16 |
| 模块 | 工具系统 / plan_mode |
| 文件 | `agent/server.py`（`_sse_generator`） |
| 描述 | plan→act 切换后用户必须手动续跑，Cline 的 switch_to_act_mode 会自动注入合成用户消息并启动新 run |
| 影响 | 用户体验割裂，plan 模式切换后需手动触发执行 |
| 修复难度 | 中（需修改 AgentRunResult + _sse_generator 流程） |
| 建议方案 | 检测 `switch_to_act_mode` 完成后，注入合成用户消息并启动续跑 run |

### P1-7: plan_mode 会话重建缺失

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-7 |
| 来源阶段 | P3.16 |
| 模块 | 工具系统 / plan_mode |
| 文件 | `agent/server.py` |
| 描述 | 切换 mode 后不重建 runtime，续跑 run 仍用旧 mode 的 tool_policies（editor/apply_patch 被禁用） |
| 影响 | 与 P1-6 同步修复，否则续跑 run 无法执行计划中的写操作 |
| 修复难度 | 中（与 P1-6 同步） |
| 建议方案 | 切换 mode 后立即调用 `_create_runtime` 重建 runtime |

### P1-8: AGENTS.md 加载顺序相反

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-8 |
| 来源阶段 | P6.7 |
| 模块 | AGENTS.md 加载机制 |
| 文件 | `agent/context.py` L471-500 |
| 描述 | Charles 加载顺序为 global → workspace，Cline 为 workspace → global，顺序相反影响优先级覆盖语义 |
| 影响 | workspace 规则可能被 global 规则错误覆盖 |
| 修复难度 | 低（调换步骤 1 与步骤 2 顺序） |
| 建议方案 | 调换加载顺序为 workspace → global |

### P1-9: HookProcessRegistry 未接入 runtime abort

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-9 |
| 来源阶段 | P7.7 |
| 模块 | Hooks |
| 文件 | `agent/hooks/integration.py` L166/L210 + `agent/runtime.py` L405-423 |
| 描述 | `run_hook` 调用时未传 `registry` 参数；`runtime.abort()` 不调用 `get_global_registry().kill_all()`，abort 后 hook 子进程可能继续运行 |
| 影响 | 资源泄漏 + 潜在副作用（abort 后 hook 仍执行） |
| 修复难度 | 低（5-10 行） |
| 建议方案 | integration.py 传入 registry 参数；runtime.abort() 内调用 `get_global_registry().kill_all()` |

### P1-10: compact() 未调用 build_budget_projection 安全阀

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-10 |
| 来源阶段 | P7.2 |
| 模块 | 上下文压缩 |
| 文件 | `agent/context.py`（`compact()` 方法） |
| 描述 | `compact()` 的 `_simple_summary` 路径后未调用 `build_budget_projection` 作为安全阀，可能导致压缩后仍超限 |
| 影响 | 边缘情况下压缩后消息仍超过 trigger_tokens |
| 修复难度 | 低（10 行） |
| 建议方案 | 在 `compact()` 末尾增加 `build_budget_projection` 调用作为安全阀 |

### P1-11: rule 输出格式 docstring 修正

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-11 |
| 来源阶段 | P7.13 |
| 模块 | Rules / frontmatter |
| 文件 | `agent/rules_loader.py` L700 |
| 描述 | 注释"对齐 Cline ## name 格式"不准确，Cline 实际用相对文件路径作为 label，无 `##` 标题 |
| 影响 | docstring 误导后续对齐工作 |
| 修复难度 | 极低（1 行注释） |
| 建议方案 | 修正为"Charles 优化的输出格式：使用文件 stem 作为 markdown ## 标题" |

### P1-12: alwaysApply 死字段

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-12 |
| 来源阶段 | P7.13 / P6.1 / P6.6 |
| 模块 | Rules / frontmatter |
| 文件 | `agent_config/rules/AGENTS.md` frontmatter |
| 描述 | `alwaysApply: true` 字段被解析但无任何效果，从 Cursor Rules 模板复制而来，可能误导用户 |
| 影响 | 误导用户认为有"始终应用"语义 |
| 修复难度 | 极低（删除 1 行） |
| 建议方案 | 移除 `alwaysApply: true` 字段 |

### P1-13: PyYAML fallback 简单解析残留

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-13 |
| 来源阶段 | P7.19 / P4.2 |
| 模块 | 技能系统 / loader |
| 文件 | `agent/skills/loader.py` L384-420 |
| 描述 | frontmatter 解析有双路径（PyYAML + fallback 简单解析），fallback 是 nanobot 实现逻辑残留 |
| 影响 | 实现逻辑残留，与 Cline 单路径不一致 |
| 修复难度 | 低（删除 fallback 代码） |
| 建议方案 | 统一为 PyYAML 的 `parse_yaml_frontmatter`，移除 fallback 简单解析 |

### P1-14: 孤儿工具 attempt_completion.py

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-14 |
| 来源阶段 | P7.19 |
| 模块 | 工具系统 / nanobot 残留 |
| 文件 | `agent/tools/attempt_completion.py` + `approval_policy.py` L42 |
| 描述 | attempt_completion.py 是孤儿工具文件，不在 create_default_tools 中注册，但 approval_policy.py 仍引用 |
| 影响 | 死代码，增加维护噪音 |
| 修复难度 | 低（删除文件 + 移除引用） |
| 建议方案 | 删除 `attempt_completion.py`，移除 `approval_policy.py` L42 的引用 |

### P1-15: allowed_tools 死代码字段

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-15 |
| 来源阶段 | P7.19 |
| 模块 | 技能系统 / loader |
| 文件 | `agent/skills/loader.py` L74/L259-266 |
| 描述 | `allowed_tools` 字段被解析但无消费方，属死代码 |
| 影响 | 死代码，增加维护噪音 |
| 修复难度 | 低（删除字段 + 解析逻辑） |
| 建议方案 | 删除 `allowed_tools` 字段及其解析逻辑 |

### P1-16: Custom Instructions 扩展 rule 机制评估

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-16 |
| 来源阶段 | P5.11 |
| 模块 | System Prompt / custom_instructions |
| 文件 | `agent/context.py`（SystemPromptBuilder） |
| 描述 | Charles 缺失 Cline 的 `composeSystemPrompt()` 扩展 rule 合并机制，无法运行时动态注册 rule |
| 影响 | 不支持运行时扩展 system prompt（Charles 当前无插件系统，影响有限） |
| 修复难度 | 中（需新增 register_rule 接口） |
| 建议方案 | 保留方案（推荐）：在 docstring 标注架构差异；或补建 register_rule 接口 |

### P1-17: 计划表 Memory 段标注勘误

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-17 |
| 来源阶段 | P5.12 |
| 模块 | System Prompt / memory |
| 文件 | `AGENT_COMPARISON_PLAN_V2.md` L2022-2035 |
| 描述 | 计划表将 nanobot 的 MemoryStore 机制误标为 Cline 实现，导致对比基准错误 |
| 影响 | 后续修复方向偏差 |
| 修复难度 | 极低（文档修正） |
| 建议方案 | 修正计划表标注，明确 Cline 无 MEMORY.md 加载机制 |

### P1-18: general.md 与 trading.md 股票代码格式段重复

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-18 |
| 来源阶段 | P6.4 |
| 模块 | AGENTS.md / rules 去重 |
| 文件 | `agent_config/rules/trading.md` L29-34 |
| 描述 | general.md 与 trading.md 的"股票代码格式"段部分重复，修改基础格式需同步两文件 |
| 影响 | 增加维护成本 |
| 修复难度 | 低（5 行） |
| 建议方案 | 在 trading.md 上方添加指针引用，仅保留特化内容 |

### P1-19: AGENTS.md 命名对齐

| 属性 | 值 |
|------|-----|
| 差距 ID | P1-19 |
| 来源阶段 | P6.8 |
| 模块 | AGENTS.md / rule name |
| 文件 | `agent/rules_loader.py`（`format_rules_content`） |
| 描述 | Cline 的 rule name 三级优先级（frontmatter name → AGENTS.md 特殊名 → 文件 stem），Charles 仅用文件 stem 一级 |
| 影响 | Charles 缺失 frontmatter name 覆盖能力 |
| 修复难度 | 中 |
| 建议方案 | 中优先级：AGENTS.md 命名对齐；低优先级：frontmatter name 字段支持 |

---

## 五、P2 级差距清单（改进建议）

共 36 项，按模块分组，中期按需修复。

### 5.1 工具系统（P3.x）

| 差距 ID | 来源 | 描述 | 文件 | 修复难度 |
|---------|------|------|------|---------|
| P2-1 | P3.1 | 清理 `__init__.py` L2 nanobot 注释残留 | `agent/tools/__init__.py` L2 | 极低 |
| P2-2 | P3.10 | 补齐 `start_line <= end_line` 校验 | `agent/tools/read_files.py` | 极低 |
| P2-3 | P3.10 | 增加 `MAX_LINE_CHARS` 单行字符截断 | `agent/tools/read_files.py` | 低 |
| P2-4 | P3.10 | 清理 `file_tools.py` nanobot 注释残留 | `agent/tools/file_tools.py` | 极低 |
| P2-5 | P3.11 | 考虑补进程树 kill | `agent/tools/exec_tool.py` | 中 |
| P2-6 | P3.12 | 补齐重复操作检查 | `agent/tools/apply_patch.py` | 低 |
| P2-7 | P3.13 | 上下文行缺失（匹配行前后 context_lines） | `agent/tools/search_codebase.py` | 低 |
| P2-8 | P3.13 | 截断策略（字符级截断 + truncated 标记） | `agent/tools/search_codebase.py` | 低 |
| P2-9 | P3.14 | 补齐超时保护 | `agent/tools/list_files.py` | 低 |
| P2-10 | P3.14 | 补齐 `.gitignore` 支持 | `agent/tools/list_files.py` | 中 |
| P2-11 | P3.16 | 修正 SwitchToPlanModeTool 对标注释 | `agent/tools/plan_mode.py` | 极低 |
| P2-12 | P3.16 | 修正 set_mode docstring 与实现矛盾 | `agent/state.py` | 极低 |
| P2-13 | P3.16 | 清理 server.py 与 context.py nanobot 注释残留 | `agent/server.py` + `agent/context.py` | 极低 |
| P2-14 | P3.22 | 响应大小检查 | `agent/tools/web_tool.py` | 低 |
| P2-15 | P3.22 | JSON 响应 Content-Type 分支处理 | `agent/tools/web_tool.py` | 低 |
| P2-16 | P3.22 | URL 协议校验 | `agent/tools/web_tool.py` | 极低 |
| P2-17 | P3.23 | 补齐 INPUT_ARG_CHAR_LIMIT 大小检查 | `agent/tools/file_tools.py` | 低 |
| P2-18 | P3.24 | 补充 ask_question 描述关键约束 | `agent/tools/ask_question.py` | 极低 |
| P2-19 | P3.24 | 清理 ExecTool 废弃残留 | `agent/tools/exec_tool.py` | 低 |
| P2-20 | P3.8 | 清理 server.py 文件头 nanobot 注释 | `agent/server.py` L2/L4/L28-29 | 极低 |

### 5.2 技能系统（P4.x）

| 差距 ID | 来源 | 描述 | 文件 | 修复难度 |
|---------|------|------|------|---------|
| P2-21 | P4.2 | frontmatter 解析双路径分裂（与 P1-13 同源） | `agent/skills/loader.py` | 低 |
| P2-22 | P4.13 | 补充 `--keywords` 参数文档 | `agent_config/skills/sentiment-analysis/SKILL.md` | 极低 |
| P2-23 | P4.13 | 修正 `--days` 默认值与输出路径描述 | `agent_config/skills/sentiment-analysis/SKILL.md` | 极低 |

### 5.3 System Prompt（P5.x）

| 差距 ID | 来源 | 描述 | 文件 | 修复难度 |
|---------|------|------|------|---------|
| P2-24 | P5.10 | 修正计划文件 P5.10 错误标注 | `AGENT_COMPARISON_PLAN_V2.md` | 极低 |
| P2-25 | P5.10 | 评估 always_skills 段保留必要性（与 P0-5 关联） | `agent/context.py` | 中 |
| P2-26 | P5.11 | 清理 extra_sections 已废弃参数 nanobot 注释 | `agent/context.py` L275/L255/L292/L530-537 | 低 |
| P2-27 | P5.12 | 评估 memory 参数和 charles-memory 段保留必要性 | `agent/context.py` L252/L289/L644-645 | 中 |

### 5.4 AGENTS.md（P6.x）

| 差距 ID | 来源 | 描述 | 文件 | 修复难度 |
|---------|------|------|------|---------|
| P2-28 | P6.4 | 计划表标注错误修正（6.4.3/6.4.4） | `AGENT_COMPARISON_PLAN_V2.md` | 极低 |

### 5.5 核心引擎与辅助系统（P7.x）

| 差距 ID | 来源 | 描述 | 文件 | 修复难度 |
|---------|------|------|------|---------|
| P2-29 | P7.4 | Provider 覆盖广度差距（7 vs 40+） | `agent/providers/factory.py` | 高 |
| P2-30 | P7.7 | 用户中止后 hook 仍执行到超时 | `agent/hooks/runner.py` | 中 |
| P2-31 | P7.7 | 长时 hook 无进度反馈 | `agent/hooks/runner.py` | 中 |
| P2-32 | P7.7 | JSON 提取鲁棒性（两阶段提取） | `agent/hooks/runner.py` L269-289 | 低 |
| P2-33 | P7.8 | MCP 客户端传输协议覆盖（缺 sse/streamableHttp） | `agent/mcp/client.py` | 高 |
| P2-34 | P7.8 | MCP 配置可靠性（无锁/无原子写） | `agent/mcp/config.py` | 中 |
| P2-35 | P7.9 | OTLP exporter 缺失（logs/traces） | `agent/telemetry.py` | 中 |
| P2-36 | P7.9 | 配置文件缺失（telemetry.yaml 不存在） | `agent_config/telemetry.yaml` | 低 |
| P2-37 | P7.9 | distinctId 不持久化（跨会话不稳定） | `agent/telemetry.py` | 中 |
| P2-38 | P7.14 | 清理 server.py nanobot 注释残留（与 P2-20 同源） | `agent/server.py` | 极低 |
| P2-39 | P7.16 | throwIfAborted 调用点数量差异（2 处 vs 7 处） | `agent/runtime.py` | 中 |
| P2-40 | P7.17 | drain 触发方式差异（SSE 绑定 vs 独立调度） | `agent/server.py` + `agent/turn_queue.py` | 高 |
| P2-41 | P7.18 | 事件名串不一致（tool-started vs tool-execution-started） | `agent/events.py` | 低 |
| P2-42 | P7.19 | `__pycache__/*.pyc` 死文件清理 | `agent/skills/__pycache__/` | 极低 |
| P2-43 | P7.19 | skill_tool.py 静默异常改日志 | `agent/skills/skill_tool.py` L245-267 | 极低 |
| P2-44 | P7.19 | 脚本 fallback 标记清理 | `parse_pdf_ocr.py` + `sentiment_scorer.py` | 极低 |

---

## 六、P3 级差距清单（可选优化）

P3 级差距为可选优化、文档修正或合理偏离，Charles 量化场景下无需对齐，共涵盖以下类别：

1. **架构差异保留现状**：inputSchema 规范化层缺失、ToolCatalog 抽象层缺失、executor 依赖注入缺失（P3.1）
2. **生态扩展层主动不实施**：Connectors（P7.10，对齐度 20%）、Sub-agent（P7.11，对齐度 10%）、Plugin（P7.12，对齐度 5%）
3. **语言生态差异**：YAML schema（safe_load vs JSON_SCHEMA）、字段命名（snake_case vs camelCase）
4. **文档修正**：计划表多处标注已失效（M1/M2/L7/A1/L5 等差距已在早期 Stage 修复）
5. **nanobot 注释溯源**：55 处 docstring nanobot 对标说明（P7.19），可选择保留作为设计溯源或统一清理
6. **合理偏离项**：Charles 独有增强（mode_notice 机制、user_input 包装、动态工具注册、emit_sync 同步通道等）应予保留

---

## 七、优先级矩阵汇总表

| 差距 ID | 模块 | 描述 | 严重度 | 修复难度 | 建议优先级 |
|---------|------|------|--------|---------|-----------|
| P0-1 | 技能系统/write-report | SKILL.md 命令参数与脚本不一致 | P0 阻塞 | 低 | 立即 |
| P0-2 | 技能系统/sentiment-analysis | SKILL.md 命令参数与脚本不一致 | P0 阻塞 | 低 | 立即 |
| P0-3 | 技能系统/bond-credit-review | 脚本不存在，技能无法执行 | P0 阻塞 | 中 | 立即 |
| P0-4 | AGENTS.md 加载 | 全局路径拼写错误 `.agent` vs `.agents` | P0 阻塞 | 极低 | 立即 |
| P0-5 | 技能系统/nanobot 残留 | always 预加载机制（7 处） | P0 高 | 中 | 立即 |
| P0-6 | 技能系统/nanobot 残留 | when_to_use 字段（11 处） | P0 高 | 中 | 立即 |
| P0-7 | 技能系统/nanobot 残留 | SKILL.md 三段式章节（24 处） | P0 高 | 高 | 立即 |
| P1-1 | 工具系统/apply_patch | cwd 越界检查缺失 | P1 安全 | 低 | 短期 |
| P1-2 | 工具系统/editor | cwd 越界检查缺失 | P1 安全 | 低 | 短期 |
| P1-3 | 工具系统/list_files | 受限路径保护缺失 | P1 安全 | 低 | 短期 |
| P1-4 | 工具系统/read_files | 常量未统一管理 | P1 一致性 | 极低 | 短期 |
| P1-5 | 工具系统/search_codebase | 单查询容错缺失 | P1 功能 | 低 | 短期 |
| P1-6 | 工具系统/plan_mode | switch_to_act_mode 自动续跑缺失 | P1 功能 | 中 | 短期 |
| P1-7 | 工具系统/plan_mode | 会话重建缺失 | P1 功能 | 中 | 短期 |
| P1-8 | AGENTS.md 加载 | 加载顺序相反 | P1 一致性 | 低 | 短期 |
| P1-9 | Hooks | HookProcessRegistry 未接入 abort | P1 资源泄漏 | 低 | 短期 |
| P1-10 | 上下文压缩 | compact() 未调用 budget_projection 安全阀 | P1 正确性 | 低 | 短期 |
| P1-11 | Rules/frontmatter | rule 输出格式 docstring 修正 | P1 文档 | 极低 | 短期 |
| P1-12 | Rules/frontmatter | alwaysApply 死字段 | P1 清理 | 极低 | 短期 |
| P1-13 | 技能系统/loader | PyYAML fallback 简单解析残留 | P1 残留 | 低 | 短期 |
| P1-14 | 工具系统/nanobot 残留 | 孤儿工具 attempt_completion.py | P1 残留 | 低 | 短期 |
| P1-15 | 技能系统/loader | allowed_tools 死代码字段 | P1 残留 | 低 | 短期 |
| P1-16 | System Prompt | Custom Instructions 扩展 rule 机制 | P1 功能 | 中 | 短期 |
| P1-17 | System Prompt/memory | 计划表 Memory 段标注勘误 | P1 文档 | 极低 | 短期 |
| P1-18 | AGENTS.md/rules | 股票代码格式段重复 | P1 维护 | 低 | 短期 |
| P1-19 | AGENTS.md/rule name | AGENTS.md 命名对齐 | P1 一致性 | 中 | 短期 |
| P2-1~P2-20 | 工具系统（P3.x） | 注释清理/校验补齐/截断策略等 20 项 | P2 改进 | 极低~中 | 中期 |
| P2-21~P2-23 | 技能系统（P4.x） | 参数文档/路径修正等 3 项 | P2 改进 | 极低~低 | 中期 |
| P2-24~P2-27 | System Prompt（P5.x） | 计划表勘误/参数清理等 4 项 | P2 改进 | 极低~中 | 中期 |
| P2-28 | AGENTS.md（P6.x） | 计划表标注修正 | P2 改进 | 极低 | 中期 |
| P2-29~P2-44 | 核心引擎/辅助系统（P7.x） | Provider/Hooks/MCP/Telemetry 等改进 16 项 | P2 改进 | 极低~高 | 中期 |

---

## 八、修复建议总结

### 8.1 推荐执行顺序

```
Stage 1: P0 阻塞性修复（立即执行）
  ├─ P0-4 全局路径拼写修正（1 行，最先执行）
  ├─ P0-1 write-report SKILL.md 参数修正（5 行）
  ├─ P0-2 sentiment-analysis SKILL.md 参数修正（5 行）
  ├─ P0-3 bond-credit-review 脚本实现或移除脚本调用
  ├─ P0-5 always 预加载机制 docstring 修正（推荐方案 A）
  ├─ P0-6 when_to_use 字段合并到 description（8 个 SKILL.md）
  └─ P0-7 SKILL.md 三段式章节重构（8 个 SKILL.md，工作量最大）

Stage 2: P1 安全加固（短期执行，1-2 个迭代）
  ├─ P1-1 + P1-2 + P1-3 cwd 越界/受限路径检查（apply_patch + editor + list_files 统一补齐）
  ├─ P1-4 read_files 常量统一管理（2-3 行）
  ├─ P1-5 search_codebase 单查询容错（10-15 行）
  ├─ P1-9 HookProcessRegistry 接入 runtime abort（5-10 行）
  └─ P1-10 compact() budget_projection 安全阀（10 行）

Stage 3: P1 功能补齐（短期执行，与 Stage 2 并行）
  ├─ P1-6 + P1-7 plan_mode 自动续跑 + 会话重建（同步修复）
  ├─ P1-8 AGENTS.md 加载顺序对齐
  ├─ P1-13 PyYAML fallback 清理
  ├─ P1-14 孤儿工具 attempt_completion.py 删除
  └─ P1-15 allowed_tools 死代码字段删除

Stage 4: P1 文档/清理（短期执行）
  ├─ P1-11 rule 输出格式 docstring 修正
  ├─ P1-12 alwaysApply 死字段移除
  ├─ P1-17 计划表 Memory 段勘误
  └─ P1-18 股票代码格式段去重

Stage 5: P2 改进建议（中期按需执行）
  ├─ 优先：P2-32 JSON 提取鲁棒性 + P2-41 事件名串统一
  ├─ 优先：P2-42~P2-44 nanobot 残留清理（极低难度）
  ├─ 按需：P2-29~P2-37 Provider/Hooks/MCP/Telemetry 改进
  └─ 按需：P2-1~P2-28 工具系统/技能/System Prompt 改进
```

### 8.2 修复策略建议

1. **P0 优先级最高**：7 项阻塞性问题中，P0-4（路径拼写）只需 1 行修改应最先执行；P0-1/P0-2（SKILL.md 参数）只需 5 行修改；P0-3（脚本不存在）需决策实现还是移除；P0-5/P0-6/P0-7（nanobot 残留）工作量最大但影响 LLM 行为，建议统一在技能系统重构批次中处理。

2. **P1 安全加固批量处理**：P1-1/P1-2/P1-3（cwd 越界检查）建议统一补齐，可抽取公共的 `_check_path_in_cwd(path, cwd)` 辅助函数复用。

3. **P1 功能补齐成对修复**：P1-6/P1-7（plan_mode 自动续跑 + 会话重建）必须同步修复，单独修复任一项都无法正常工作。

4. **P2 按模块分批**：P2 项较多但多数修复难度极低（注释清理/文档修正），建议按模块分批在常规维护中处理，无需专门排期。

5. **P3 不主动修复**：生态扩展层（Connectors/Sub-agent/Plugin）的主动不实施属合理偏离，Charles 量化场景下无需对齐；架构差异保留现状即可。

### 8.3 与计划文件原矩阵的差异说明

计划文件 P7.21（L2998-3016）的原矩阵标注了 13 项差距，经 Phase 3-7 实际对比后，状态变化如下：

| 原差距 ID | 原优先级 | 实际状态 | 说明 |
|-----------|---------|---------|------|
| Q8 MCP auto_approve | P1 | 未在本报告列为 P1 | P3.19 确认 Charles 调度器模式功能等价，非阻塞性 |
| F-base nanobot 清理 | P2 | 已完成 | P3.1 确认 base.py 已清理完毕 |
| M1 mode_notice 机制 | P2 | 已失效 | P5.13/P5.14 确认 Stage 36.1 (M1) 已完整实现 |
| M2 user_input 包装下沉 | P2 | 已失效 | P5.14 确认 Stage 36.2 (M2) 已实现 runtime 层包装 |
| A1 SystemPromptBuilder 职责分离 | P3 | 已失效 | P5.1 确认 A1 重构已完成 |
| L1 env 字段名英文 | P3 | 已失效 | P5.21 确认 base prompt 字段名全英文 |
| L4 metadata provider 条件 | P3 | 待评估 | 未在 Phase 5 报告中明确关闭 |
| L5 metadata 标签格式 | P3 | 已失效 | P5.21 确认 L5 阶段已完成对齐 |
| L6 PLAN_MODE run_commands 描述 | P3 | 待评估 | 未在 Phase 5 报告中明确关闭 |
| L7 MODE_TAG 移除工具名 | P3 | 已失效 | P5.14 确认 L7 对齐时已移除工具名列举 |
| L8 yolo base prompt | P3 | 部分残留 | P5.13 确认模板已存在但 AgentMode 类型未启用 yolo |
| S1 skill 白名单 4 形式 | P3 | 已对齐 | P4.1 确认已对齐 |
| S2 skillsTimeoutMs 可配置 | P3 | 已对齐 | P4.1 确认已对齐 |
| L3-new rule name 文件 stem | P3 | 合理差异 | P6.8 确认 Charles 仅用文件 stem，Cline 三级优先级 |

**结论**：原矩阵 13 项中 9 项已失效/已对齐，4 项为合理差异或待评估。本报告基于实际代码对比重新生成优先级矩阵，P0/P1 项均为新发现的实际差距。

---

## 九、附录：各阶段差距数量统计

| Phase | 对比阶段数 | P0 | P1 | P2 | P3 | 备注 |
|-------|-----------|----|----|----|----|------|
| Phase 3 | 24 | 0 | 7 | 20 | 若干 | 安全加固 + 功能补齐 |
| Phase 4 | 20 | 3 | 0 | 3 | 若干 | SKILL.md 脚本调用缺陷 |
| Phase 5 | 23 | 0 | 2 | 4 | 若干 | 计划表勘误 + 参数清理 |
| Phase 6 | 12 | 1 | 3 | 1 | 若干 | 路径拼写 + 加载顺序 |
| Phase 7 | 20 | 3 | 7 | 16 | 若干 | nanobot 残留 + 辅助系统改进 |
| **合计** | **99** | **7** | **19** | **44** | **若干** | 去重后 P2 为 36 项 |

> 注：P2 原始统计 44 项含跨阶段重复项（如 server.py nanobot 注释清理在 P3.8/P3.16/P7.14 重复出现），去重后为 36 项。P0/P1 无跨阶段重复。
