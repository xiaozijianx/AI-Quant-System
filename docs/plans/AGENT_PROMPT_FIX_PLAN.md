# Charles Agent Prompt 系统修改计划

> 生成时间：2026-07-27
> 目标：解决 agent 在 tools/skills 调用、SKILL.md 脚本规则、AGENTS.md 风格、Plan/Act 模式、Skill 组织方式上与 Cline 的偏离
> 原则：保留现有已对齐部分，按优先级渐进式改进，避免大爆炸式重构
> 用户特别指示：**Phase P1 谨慎修改**，其他按规划推进

---

## 一、问题根因分析

### 1.1 Tools vs Skills 调用混乱根因

| 根因 | 位置 | 表现 |
|------|------|------|
| 重复列示技能名 | `agent/context.py:_build_tools_section` 把 `skills` 工具的 description（含"可用技能: ..."）列入工具列表；`agent/skills/registry.py:build_summary` 又在 Layer 6 用表格列了一遍 | LLM 在两个段落都看到技能名，混淆"技能是工具还是技能" |
| run_commands 误导 | 工具列表列出 `run_commands`，未声明"跑技能脚本前必须先 skills 加载指令" | LLM 直接 `run_commands("python get_kline.py ...")` 而不先 `skills(skill="stock-price")` |
| 缺决策树 | `AGENTS.md` "工具选择原则"只列了 4 条匹配规则，没说"工具 vs 技能"的优先级 | LLM 不清楚遇到股票代码时该先 read_files 还是先 skills(stock-price) |

### 1.2 Skills 脚本规则不清楚根因

| 根因 | 位置 | 表现 |
|------|------|------|
| 表格化易跳过 | SKILL.md 用 Markdown 表格列脚本 | LLM 跳读表格，没看到完整命令格式 |
| 缺 Workflow 步骤化 | 对比 Cline `publish-cli/SKILL.md` 用 `## Workflow` + 编号步骤 + 内嵌 shell 命令块 | LLM 不知道脚本调用的先后顺序和触发条件 |
| 缺脚本调用规则段 | 所有 SKILL.md 都没有"何时调用 / 参数如何传 / 失败如何处理"独立段 | LLM 知道有脚本但不知道何时该用 |
| read-pdf 下载能力未强调 | `read-pdf/SKILL.md` 未在顶部显式说明"本技能可下载年报 PDF" | LLM 不知道 read-pdf 能下载，等到搜索失败才试探性调用 |

### 1.3 AGENTS.md 与 Cline 风格偏离

| 偏离点 | Cline 风格 | Charles 现状 |
|--------|-----------|--------------|
| frontmatter | `description / globs / alwaysApply: true` | 无 frontmatter |
| 主体结构 | 开发参考文档（边界/路由/验证） | 业务规则堆叠（模式/工具/约束/代码/时间/输出） |
| 重复内容 | 无（rules 在 .clinerules 中） | "时间基准""股票代码格式""输出规范"与 `rules/general.md` 重复 |
| 工具选择决策 | 无（Cline 默认 prompt 已含并行调用指引） | 仅 4 条匹配规则，无"tools vs skills"决策树 |

### 1.4 Plan/Act 模式 prompt 重叠

| 重叠点 | 位置 | 重叠内容 |
|--------|------|---------|
| "禁止编辑"三处重复 | `plan_mode.py:PLAN_MODE_PROMPT` + `rules/plan-mode-rules.md` + `context.py:MODE_TAG_INSTRUCTIONS` | 三处都说"plan 模式不得编辑文件" |
| "任务拆解"两处重复 | `context.py:_build_tools_section` 的"任务拆解（强制）" + `rules/plan-mode-rules.md` "探索阶段要求" | 都说"必须先 todo_write 拆解" |
| tool_policies 硬禁用 + prompt 软约束 | `server.py` 已硬禁用 editor/apply_patch/file_write + PLAN_MODE_PROMPT 又说一遍 | 双重约束冗余 |

### 1.5 Skill 组织方式与 Cline 重叠

| 重叠点 | 位置 | 重叠内容 |
|--------|------|---------|
| skills_summary vs skills 工具 description | `registry.py:build_summary` 表格 + `skill_tool.py:_build_description` 末尾"可用技能: ..." | 技能名列表出现两次 |
| SKILL.md 注意事项 vs AGENTS.md 硬约束 | `stock-price/SKILL.md` "不要用 web_search 查实时股价" + `AGENTS.md` 同条规则 | 同一约束在两处声明 |
| always_skills vs skills_summary | `context.py` always_skills 段 + skills_summary 段 | 若技能标 always=True，则在两段都出现 |

---

## 二、修改计划（5 个阶段）

### Phase P1: tools vs skills 调用链路去重 [P0] [谨慎修改]

**目标**：让 LLM 清楚"何时用 tools、何时用 skills、何时按 skills 返回的指令调脚本"。

**谨慎原则**：
- 保留 `SkillTool._build_description` 的现有动态拼接逻辑（Cline 风格，通过 tools API 暴露给 LLM）
- 只在 `SystemPromptBuilder._build_tools_section` 显示时做特殊处理（避免 system prompt 文本重复）
- 决策树是新增内容，不影响现有逻辑
- AGENTS.md 修改保留所有现有约束，只增加决策树段

#### P1.1 修改 `_build_tools_section()` 对 skills 工具的展示

**文件**：`agent/context.py`

**修改方案**：在 `_build_tools_section` 中对 skills 工具做特殊处理，工具列表中只显示一句话描述，不重复列技能名（技能名已在 Layer 6 skills_summary 段展示）。

#### P1.2 在 `_build_tools_section` 增加"工具 vs 技能 决策树"

**文件**：`agent/context.py`

**修改方案**：在"工具使用指引"段后插入"工具 vs 技能 决策树"段，明确何时用 tools、何时用 skills。

#### P1.3 在 AGENTS.md 强化"工具选择原则"

**文件**：`agent_config/AGENTS.md`

**修改方案**：把"工具选择原则"段重组为"工具 vs 技能 决策树"，与 P1.2 呼应（AGENTS.md 是常驻规则，context.py 是动态拼接，两处都改确保 LLM 一定看到）。保留所有现有约束。

#### P1.4 验证方法

- 启动 agent，输入"获取600875.SH的K线"，确认 LLM 第一轮调用 `skills(skill="stock-price")` 而非直接 `run_commands`
- 输入"读取 README.md"，确认 LLM 直接 `read_files(...)` 而非先 `skills`
- 确认 `SkillTool._build_description` 逻辑未被破坏（通过 tools API 仍能看到完整技能列表）

---

### Phase P2: SKILL.md 重构为 Workflow 步骤化 [P0]

**目标**：让 LLM 加载 SKILL.md 后能立即知道"何时调脚本、命令格式、参数、失败处理"，对齐 Cline publish-cli 风格。

#### P2.1 制定 SKILL.md 模板规范

**新模板结构**（所有 SKILL.md 统一此结构）：

```
---
name: <技能名>
description: "<一句话用途说明，含核心能力>"
when_to_use: "<何时使用此技能>"
---

# <技能名> 技能指南

## 本技能核心能力
<2-3 句话说明本技能能做什么、何时该用、能解决什么问题。
特别强调 LLM 容易误解的点，如 "本技能可下载年报 PDF，不需要用户提前准备文件"。>

## Workflow（必须按顺序执行）
### Step 1: <步骤名>
- **何时执行**: <触发条件>
- **命令**: <shell 命令块>
- **参数**: <参数说明>
- **预期输出**: <输出格式与位置>
- **失败处理**: <出错时怎么办>

### Step 2: <步骤名>
...

## 脚本调用规则
1. 必须按 Workflow 顺序
2. 参数格式
3. 输出位置
4. 错误码处理

## 禁止行为
<仅技能特定的禁止行为，不与 AGENTS.md 重复>
```

#### P2.2-P2.5 重构 8 个 SKILL.md

按 P2.1 模板重构：
- `stock-price/SKILL.md`
- `read-pdf/SKILL.md`（重点：顶部强调"可下载年报 PDF"）
- `financial-analysis/SKILL.md`
- `write-report/SKILL.md`
- `compare-reports/SKILL.md`
- `sentiment-analysis/SKILL.md`
- `bond-credit-review/SKILL.md`
- `web-search/SKILL.md`

#### P2.6 验证方法

- 输入"分析东方电气 2025 年年报氢能业务"，确认 LLM 调用 `skills(skill="read-pdf")` 后能按 Workflow Step 1→2→3→4 顺序执行
- 确认 LLM 不会跳过 `fetch_report_pdf.py` 直接调用 `query_report.py`

---

### Phase P3: AGENTS.md 对齐 Cline 风格 [P1]

**目标**：加 frontmatter、去重、增加决策树，对齐 Cline sdk/AGENTS.md 风格。

#### P3.1 加 frontmatter

```markdown
---
description: Charles 投研情报官主规则 — 所有模式和业务场景下常驻应用
applyTo: [act, plan]
alwaysApply: true
---
```

#### P3.2 重组主体结构

- 增加"工具 vs 技能 决策树"段（与 P1.3 协同）
- 保留"硬约束""股票代码格式""输出规范"
- 移除与 `rules/general.md` 重复的"时间基准"段

#### P3.3 验证方法

- 启动后检查 system prompt 输出，确认 AGENTS.md 段无重复内容
- 确认 rules/general.md 仍被 rules_loader 加载

---

### Phase P4: Plan/Act 模式 prompt 去重 [P1]

**目标**：消除"禁止编辑"三处重复、"任务拆解"两处重复，明确各段职责。

#### P4.1 精简 PLAN_MODE_PROMPT

**职责重新定义**：PLAN_MODE_PROMPT 只负责"模式行为契约"（探索/分析/规划，不执行），不重复 tool_policies 已禁用的工具列表。

#### P4.2 精简 plan-mode-rules.md

**职责重新定义**：plan-mode-rules.md 只负责"计划呈现格式"和"探索深度要求"，不重复 PLAN_MODE_PROMPT 已说的"禁止编辑"。

#### P4.3 精简 MODE_TAG_INSTRUCTIONS

**职责重新定义**：MODE_TAG_INSTRUCTIONS 只解释 `<user_input mode>` 标签语义，不重复"禁止编辑"。

#### P4.4 验证方法

- 切换到 Plan 模式，检查 system prompt 中"禁止编辑"只出现 1 次（在 PLAN_MODE_PROMPT 中）
- 确认 plan-mode-rules.md 仍被 rules_loader 按 `applyTo: [plan]` 加载

---

### Phase P5: skills_summary 与 skills 工具去重 [P1]

**目标**：消除 skills_summary 段与 skills 工具 description 的内容重叠，明确各段职责。

#### P5.1 精简 skills_summary 段职责

**职责重新定义**：skills_summary 段是 LLM 选择技能的"目录索引"，只列技能名 + 一句话用途 + 何时该用，不重复 skills 工具 description 的调用示例。

#### P5.2 SKILL.md frontmatter 增加 `when_to_use` 字段

供 skills_summary 表格的"何时使用"列填充。

#### P5.3 移除 SKILL.md 中与 AGENTS.md 重复的"注意事项"

- 与 AGENTS.md "硬约束"重复的条目移除
- 保留技能特定的注意事项
- 保留脚本调用规则

#### P5.4 always_skills 段与 skills_summary 段区分

在 always_skills 段开头明确标注"以下技能指令已自动加载，无需调用 skills 工具"。

#### P5.5 验证方法

- 启动后检查 system prompt，确认技能名只出现在"技能目录"表格中一次
- 确认 always_skills 段有"已自动加载"标注

---

## 三、执行顺序与依赖

```
Phase P1 (tools vs skills 去重) [谨慎] ──┐
                                         ├──> Phase P3 (AGENTS.md 对齐)
                                         │
Phase P2 (SKILL.md 重构) ────────────────┤
                                         ├──> Phase P5 (skills_summary 去重)
Phase P4 (Plan/Act 去重) ────────────────┘
```

**推荐执行顺序**：

1. **第一周（P0 必做）**：
   - Phase P1（tools vs skills 决策树）— 谨慎修改，保留现有逻辑
   - Phase P2（SKILL.md 重构） — 解决"不知道技能脚本规则"问题

2. **第二周（P1 建议做）**：
   - Phase P3（AGENTS.md 对齐） — 依赖 P1 的决策树内容
   - Phase P4（Plan/Act 去重） — 独立可做
   - Phase P5（skills_summary 去重） — 依赖 P2 的 when_to_use 字段

---

## 四、验证清单

| 验证项 | 方法 | 预期结果 |
|--------|------|---------|
| Tools vs Skills 决策正确 | 输入"获取600875.SH的K线" | LLM 第一轮调用 `skills(skill="stock-price")` |
| 脚本调用顺序正确 | 输入"分析东方电气氢能业务" | LLM 按 read-pdf SKILL.md Workflow Step 1→2→3→4 顺序执行 |
| Plan 模式无重复约束 | 切换到 Plan 模式，打印 system prompt | "禁止编辑"只出现 1 次 |
| 技能名无重复列示 | 打印 system prompt | 技能名只在"技能目录"表格中出现一次 |
| AGENTS.md frontmatter 生效 | 检查 rules_loader 日志 | AGENTS.md 按 `alwaysApply: true` 加载 |
| always_skills 标注清晰 | 打印 system prompt | always_skills 段开头有"已自动加载"标注 |

---

## 五、进度追踪

| Phase | 状态 | 完成时间 | 验证结果 |
|-------|------|----------|---------|
| P1 tools vs skills 去重 | 已完成 | 2026-07-27 | context.py + AGENTS.md 增加决策树，skills 工具展示去重 |
| P2 SKILL.md 重构 | 已完成 | 2026-07-27 | 8 个 SKILL.md 重构为 Workflow 步骤化，增加 when_to_use frontmatter |
| P3 AGENTS.md 对齐 | 已完成 | 2026-07-27 | 加 frontmatter，移除与 general.md 重复的三段，_strip_frontmatter 方法 |
| P4 Plan/Act 去重 | 已完成 | 2026-07-27 | PLAN_MODE_PROMPT 精简，plan-mode-rules.md 精简，MODE_TAG_INSTRUCTIONS 精简 |
| P5 skills_summary 去重 | 已完成 | 2026-07-27 | build_summary 3 列表格，when_to_use 字段，always_skills 标注 |

### 验证记录（2026-07-27）

1. **导入测试**: context.py / plan_mode.py / loader.py / registry.py 全部导入成功
2. **System prompt 构造测试**:
   - System prompt 长度: 6459 字符
   - 包含"工具 vs 技能 决策树"段: True
   - 包含"常驻技能指令（已自动加载）"标注: True
   - 包含"何时使用"列: True
   - AGENTS.md frontmatter 已移除: True（"alwaysApply" 不在 system prompt 中）

### 修改文件清单

| 文件 | Phase | 修改内容 |
|------|-------|---------|
| agent/context.py | P1 | _build_tools_section skills 工具展示去重 + 增加决策树段 |
| agent_config/AGENTS.md | P1/P3 | 增加决策树段 + 加 frontmatter + 移除与 general.md 重复段 |
| agent_config/skills/stock-price/SKILL.md | P2 | Workflow 步骤化 + when_to_use + 核心能力段 |
| agent_config/skills/read-pdf/SKILL.md | P2 | Workflow 步骤化 + 强调可下载 + when_to_use |
| agent_config/skills/financial-analysis/SKILL.md | P2 | Workflow 步骤化 + when_to_use + 核心能力段 |
| agent_config/skills/write-report/SKILL.md | P2 | Workflow 步骤化 + when_to_use + 核心能力段 |
| agent_config/skills/compare-reports/SKILL.md | P2 | Workflow 步骤化 + when_to_use |
| agent_config/skills/sentiment-analysis/SKILL.md | P2 | Workflow 步骤化 + when_to_use |
| agent_config/skills/bond-credit-review/SKILL.md | P2 | Workflow 步骤化 + when_to_use |
| agent_config/skills/web-search/SKILL.md | P2 | Workflow 步骤化 + when_to_use |
| agent/context.py | P3 | _strip_frontmatter 方法 + _load_agents_file 调用 |
| agent/tools/plan_mode.py | P4 | PLAN_MODE_PROMPT 精简为模式行为契约 |
| agent_config/rules/plan-mode-rules.md | P4 | 移除与 PLAN_MODE_PROMPT 重复内容 |
| agent/context.py | P4 | MODE_TAG_INSTRUCTIONS 移除重复工具约束 |
| agent/skills/loader.py | P5 | SkillMetadata 增加 when_to_use 字段 + _parse_skill_file 解析 |
| agent/skills/registry.py | P5 | build_summary 输出 3 列表格（技能名/何时使用/用途） |
| agent/context.py | P5 | always_skills 段增加"已自动加载"标注 |

---

**计划结束。按 P1 [谨慎] → P2 → P3 → P4 → P5 顺序推进。**
