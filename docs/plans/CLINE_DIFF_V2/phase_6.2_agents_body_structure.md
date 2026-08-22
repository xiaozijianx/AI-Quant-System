# Phase 6.2 AGENTS.md 主体结构对比

> 对比范围：Cline `sdk/AGENTS.md`（开发参考文档风格，109 行）+ `sdk/packages/llms/AGENTS.md`（子包级，39 行）与 Charles `agent_config/rules/AGENTS.md`（业务规则堆叠风格，56 行）的 AGENTS.md 主体段落结构、段落顺序、段落内容；区分注释残留与实现逻辑残留；nanobot 残留专项检查。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md` L1-109（主 workspace 级，frontmatter + 6 个 ## 段落）
> - `third_party/cline/sdk/packages/llms/AGENTS.md` L1-39（子包级，frontmatter + 1 个 ## 段落）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md` L1-56（frontmatter + 开头自然段 + 4 个 ## 段落 + 1 个注脚引用）
> - `agent_config/rules/general.md` L1-35（被 AGENTS.md 注脚引用，含股票代码格式/输出规范/时间基准）
> - `agent/context.py` L454-539（`_build_rules`：AGENTS.md 加载与 rules 拼接逻辑）
> - `agent/rules_loader.py`（rules_dir 目录加载器，无 nanobot 残留）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 主体段落结构与段落内容。**核心结论：两者在 AGENTS.md 的设计取向存在根本性差异——Cline 的 AGENTS.md 是"开发者参考文档"风格（面向人类开发者，描述代码库边界与变更路由），Charles 的 AGENTS.md 是"LLM 业务规则"风格（面向 LLM，描述工具选择与硬约束）。两者段落结构不重合，但各自在其架构中都是合理的**。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.2（L2274-2301）的预判与实测存在以下偏差：

| 计划项 | 计划预判 | 实测情况 | 偏差说明 |
|--------|---------|---------|---------|
| 6.2.7 股票代码格式段 | Charles AGENTS.md 内有此段 | 实际在 `general.md` L29-35，AGENTS.md L56 仅以注脚引用 | **计划描述需修正**：股票代码格式不在 AGENTS.md 主体段落，而是通过 rules_loader 自动加载的 general.md 提供 |
| 6.2.8 输出规范段 | Charles AGENTS.md 内有此段 | 实际在 `general.md` L8-14，AGENTS.md L56 仅以注脚引用 | **计划描述需修正**：同上，输出规范在 general.md |
| Charles 段落清单 | 身份声明/硬约束/决策树/股票代码/输出规范 | 实际为：身份声明/工作模式/决策树/工具选择原则/硬约束/注脚引用 | **计划遗漏 2 段**：未列出"工作模式"和"工具选择原则"两段；多列 2 段（股票代码/输出规范实际在 general.md） |
| Cline 段落清单 | 项目边界/路由规则/验证规则/开发约束 | 实际为 6 段：Repository Scope/Package Boundaries/Change Routing/Verifying Changes/Practical Guidance/Documentation Responsibilities | **计划遗漏 2 段**：未列出"Package Boundaries"和"Documentation Responsibilities" |

**结论**：计划文件 P6.2 表格的对比项框架（6.2.1-6.2.8）基本正确，但对 Charles 段落构成的描述与实测有偏差（混淆了 AGENTS.md 主体与 general.md 内容）。本报告以实测段落为准。

### 核心结论

1. **主体风格差异（6.2.1）**：Cline AGENTS.md 是开发参考文档（描述代码库如何开发），Charles AGENTS.md 是业务规则文档（描述 LLM 如何执行投研任务）。这是面向受众的根本差异，非对齐缺口。
2. **项目边界段（6.2.2）**：Cline 有（`## Repository Scope` + `## Package Boundaries`，共 24 行），Charles 无。Charles 是单 agent 应用，无包/模块边界概念。
3. **路由规则段（6.2.3）**：Cline 有（`## Change Routing`，按 package 路由变更），Charles 有等价段（`## 工具 vs 技能 决策树` + `## 工具选择原则`，按数据类型路由工具）。形式不同但语义等价（都是"路由决策"）。
4. **验证规则段（6.2.4）**：Cline 有（`## Verifying Changes`，含 6 条 shell 命令示例），Charles 无。Charles 的验证逻辑分散在 skills 的 SKILL.md "失败处理"中，不在 AGENTS.md。
5. **开发约束段（6.2.5）**：Cline 有（`## Practical Guidance` 含 Keep Boundaries Clean + Refactor Standard），Charles 有等价段（`## 硬约束（投研场景特有）`）。形式不同但语义等价（都是"约束规则"）。
6. **身份声明段（6.2.6）**：Cline 无（身份定义在 system prompt base 模板中），Charles 有（AGENTS.md 开头自然段 L9-10）。Charles 额外。
7. **股票代码格式段（6.2.7）**：Cline 无，Charles 通过 `general.md` L29-35 提供（AGENTS.md L56 注脚引用）。Charles 量化特化。**修正计划描述：此段不在 AGENTS.md 主体**。
8. **输出规范段（6.2.8）**：Cline 无，Charles 通过 `general.md` L8-14 提供（AGENTS.md L56 注脚引用）。Charles 量化特化。**修正计划描述：此段不在 AGENTS.md 主体**。
9. **段落顺序差异**：Cline 顺序为 Scope → Boundaries → Routing → Verifying → Guidance → Docs（从"范围"到"细节"递进）；Charles 顺序为 身份 → 模式 → 决策树 → 工具选择 → 硬约束 → 引用（从"我是谁"到"怎么做"递进）。
10. **nanobot 残留**：AGENTS.md 主体结构相关文件**0 处注释残留，0 处实现逻辑残留**。Charles AGENTS.md 的段落结构（决策树/硬约束/身份声明）是通用 agent 规则模式，非 nanobot 风格残留。

### 一致性总体评估

- **段落存在性对齐**：**低**。8 项对比中仅 2 项完全对齐（路由规则段、开发约束段，且均为"形式不同但等价"），4 项一方有一方无，2 项计划误判（实际在 general.md）。
- **段落顺序对齐**：**低**。两者段落顺序无对应关系，因段落构成本身不重合。
- **段落内容对齐**：**中**。在"路由决策"和"约束规则"两个语义维度上，两者有等价段落，内容虽形式不同但功能对齐。
- **设计取向合理性**：**高**。两者各自在其架构中都是合理的设计——Cline 作为 SDK 工作区，AGENTS.md 服务于多包代码库的开发治理；Charles 作为单 agent 应用，AGENTS.md 服务于 LLM 行为治理。

---

## 二、逐项对比表

### 2.1 AGENTS.md 主体段落清单

| # | Cline 段落（sdk/AGENTS.md） | 行号 | Charles 段落（agent_config/rules/AGENTS.md） | 行号 | 一致性等级 |
|---|---------------------------|------|---------------------------------------------|------|-----------|
| 6.2.1 | 标题：`# Cline SDK — Development Reference` + quick-reference 指针 | L7-9 | 标题：`# Charles - AI 投研情报官` + 开头自然段（身份声明） | L7-10 | 低（风格不同） |
| 6.2.2 | `## Repository Scope`（项目边界：sdk/ 工作区范围） | L11-15 | 无 | — | Charles 缺失 |
| 6.2.3 | `## Package Boundaries`（含 ### Published SDK Packages + ### Dependency Direction） | L17-39 | 无 | — | Charles 缺失 |
| 6.2.4 | `## Change Routing`（路由规则：按 package 路由变更） | L41-49 | `## 工具 vs 技能 决策树（最重要）` + `## 工具选择原则（按数据类型）` | L19-47 | 形式不同但等价 |
| 6.2.5 | `## Verifying Changes`（验证规则：6 条 shell 命令） | L51-86 | 无 | — | Charles 缺失 |
| 6.2.6 | `## Practical Guidance`（含 ### Keep Boundaries Clean + ### Refactor Standard） | L88-101 | `## 硬约束（投研场景特有）` | L49-54 | 形式不同但等价 |
| 6.2.7 | `## Documentation Responsibilities`（文档责任：5 个 md 文件维护规则） | L103-108 | 无 | — | Charles 缺失 |
| 6.2.8 | 无 | — | `## 工作模式`（act/plan 模式切换） | L12-17 | Cline 缺失 |
| 6.2.9 | 无 | — | `注:`（general.md 引用脚注） | L56 | Cline 缺失 |

### 2.2 计划表逐项核对

| 计划项 | 计划预判（Cline / Charles） | 实测结论 | 状态 |
|--------|---------------------------|---------|------|
| 6.2.1 主体风格 | 开发参考文档 / 业务规则堆叠 | ✓ 完全符合预判。Cline 面向开发者，Charles 面向 LLM | **符合** |
| 6.2.2 项目边界段 | 是 / 无 | ✓ 符合。Cline 有 Repository Scope + Package Boundaries 两段；Charles 无 | **符合** |
| 6.2.3 路由规则段 | 是 / 工具 vs 技能 决策树 | ✓ 符合。Cline Change Routing 按 package 路由；Charles 决策树按任务类型路由。形式不同但等价 | **符合** |
| 6.2.4 验证规则段 | 是 / 无 | ✓ 符合。Cline Verifying Changes 含 shell 命令；Charles 无独立验证段 | **符合** |
| 6.2.5 开发约束段 | 是 / 硬约束段 | ✓ 符合。Cline Practical Guidance 含 Refactor Standard；Charles 硬约束段。形式不同但等价 | **符合** |
| 6.2.6 身份声明段 | 无 / 是 | ✓ 符合。Cline 身份在 system prompt base；Charles AGENTS.md 开头自然段含身份声明 | **符合** |
| 6.2.7 股票代码格式段 | 无 / 是 | ⚠ **部分修正**。Charles 有此内容，但位于 `general.md` L29-35，非 AGENTS.md 主体段落。AGENTS.md L56 仅以注脚引用 | **需修正定位** |
| 6.2.8 输出规范段 | 无 / 是 | ⚠ **部分修正**。Charles 有此内容，但位于 `general.md` L8-14，非 AGENTS.md 主体段落。AGENTS.md L56 仅以注脚引用 | **需修正定位** |

---

## 三、重点差距详细说明

### 3.1 主体风格差异（6.2.1）—— 设计取向非对齐缺口

Cline `sdk/AGENTS.md` 是**开发参考文档**（Development Reference），第一行即声明"Quick-reference for active development"，并在 L9 指向 CONTRIBUTING.md / ARCHITECTURE.md / DOC.md 三个文档。其内容面向**人类开发者**，描述"如何在这个代码库工作"——包边界、依赖方向、变更路由、验证命令、重构标准、文档维护责任。

Charles `agent_config/rules/AGENTS.md` 是**业务规则文档**，第一行是身份声明"你是 Charles，专业 AI 投研情报官"。其内容面向**LLM**，描述"如何执行投研任务"——工作模式、工具 vs 技能决策树、工具选择原则、硬约束。

**差异分析**：
- 两者都是作为 `effectiveRules` 注入 system prompt 的（Cline 通过 `.clinerules`/AGENTS.md 加载，Charles 通过 `_build_rules` 加载 AGENTS.md + rules_dir）
- 但 Cline 选择把"开发者参考"作为规则注入（因 Cline 是 SDK，LLM 主要做编码任务，开发者参考即 LLM 行为指导）
- Charles 选择把"LLM 业务规则"作为规则注入（因 Charles 是垂直 agent，LLM 需要领域行为约束）

**评估**：这是设计取向差异，非对齐缺口。两者各自在其架构中都是合理的。Charles 不应强行添加"项目边界/包边界"段落（单 agent 无包概念），Cline 也不应强行添加"工作模式/工具决策树"段落（通用编码 agent 无垂直领域工具）。

### 3.2 项目边界段差异（6.2.2 / 6.2.3）—— Charles 合理缺失

Cline 有两段描述项目边界：
- `## Repository Scope`（L11-15）：声明 AGENTS.md 作用于 `sdk/` 工作区，区分 SDK root 与 legacy repo root
- `## Package Boundaries`（L17-39）：列出 4 个发布包（@cline/shared / llms / agents / core）的职责，并用 mermaid 图描述依赖方向

Charles **无此两段**，因 Charles 是单 agent 应用，无包/模块边界概念。Charles 的"边界"通过 skills 目录划分（每个 skill 一个目录），而非 AGENTS.md 段落。

**评估**：Charles 合理缺失。强行添加"包边界"段落会对单 agent 架构造成误导。

### 3.3 路由规则段等价性（6.2.4）—— 形式不同但语义对齐

Cline `## Change Routing`（L41-49）按 **package** 路由变更：
```
- model/provider schemas → @cline/llms
- stateless loop → @cline/agents
- session lifecycle → @cline/core
- remote-config schemas → @cline/shared
- host-specific UX → app package
```

Charles `## 工具 vs 技能 决策树`（L19-39）+ `## 工具选择原则（按数据类型）`（L40-47）按 **任务/数据类型** 路由工具：
```
1. 任务匹配技能 → skills(skill="...")
2. 通用文件操作 → read_files / search_codebase / editor
3. 临时命令执行 → run_commands
4. 联网搜索 → web_search

1. 结构化财务数字 → financial-analysis 技能
2. 年报叙述性内容 → read-pdf 技能
3. 时效性信息 → web_search
4. 股价/K线数据 → stock-price 技能
5. 撰写深度研报 → write-report 技能
6. 通用文件/代码操作 → read_files 等
```

**差异分析**：
- Cline 路由目标是"代码包"（开发者把变更提交到哪个 package）
- Charles 路由目标是"工具/技能"（LLM 把任务分派给哪个工具）
- 两者都是"路由决策"语义，但路由目标不同

**评估**：形式不同但语义对齐。两者都解决了"X 应该放到哪里"的路由问题。Charles 的决策树更详细（含 4 条禁止行为），因 LLM 需要更明确的行为约束。

### 3.4 验证规则段差异（6.2.5）—— Charles 分散到 SKILL.md

Cline `## Verifying Changes`（L51-86）提供 6 条 shell 命令用于验证变更：
```sh
bun install --frozen-lockfile
bun run build:sdk
bun run types
bun run test
bun run check
bun -F @cline/shared test
```

Charles **无独立验证段**。Charles 的验证逻辑分散在 8 个 SKILL.md 的"失败处理"段落中（如 stock-price/SKILL.md 的"xtquant not found → 提示用户安装"）。

**差异分析**：
- Cline 的验证是"代码层面验证"（typecheck / test / lint），面向开发者
- Charles 的验证是"运行时验证"（脚本执行失败如何处理），面向 LLM
- 两者验证对象不同，不构成对齐缺口

**评估**：Charles 合理缺失独立验证段。Charles 的验证逻辑放在 SKILL.md 中更合适（与具体技能绑定），而非放在 AGENTS.md 全局规则中。

### 3.5 开发约束段等价性（6.2.6）—— 形式不同但语义对齐

Cline `## Practical Guidance`（L88-101）含两个子段：
- `### Keep Boundaries Clean`：不要把 stateful logic 下沉到 agents、不要把 app 行为放进 core
- `### Refactor Standard`：优先直接架构清理而非兼容 shim、把代码移到拥有该 concern 的层

Charles `## 硬约束（投研场景特有）`（L49-54）含 4 条约束：
- 禁止用 web_search 查本地已有数据的股价、财报
- 禁止用 RAG 查结构化数字
- 禁止用 read_files 读 data/parsed/ 下的切分文件
- 禁止用 run_commands 执行不存在的脚本

**差异分析**：
- Cline 约束是"架构约束"（包边界、重构标准），面向开发者
- Charles 约束是"业务约束"（工具使用禁忌），面向 LLM
- 两者都是"什么不能做"的约束语义，但约束对象不同

**评估**：形式不同但语义对齐。Charles 的硬约束是量化场景特有，Cline 的 Practical Guidance 是 SDK 开发特有。

### 3.6 身份声明段差异（6.2.7）—— Charles 额外但合理

Cline AGENTS.md **无身份声明段**（Cline 身份定义在 `system.ts` 的 `DEFAULT_CLINE_SYSTEM_PROMPT` 第一行"You are Cline, an AI coding agent..."）。

Charles AGENTS.md **开头自然段（L9-10）含身份声明**：
```
你是 Charles，专业 AI 投研情报官。当任务匹配某个技能时，先通过 skills 工具加载该技能的详细指令，
然后在当前主上下文中使用 read_files/run_commands/web_search 等结构化工具执行具体操作。
```

**差异分析**：
- Cline 把身份定义放在 system prompt base 模板（硬编码），AGENTS.md 不重复
- Charles 把身份定义放在 AGENTS.md 开头（用户可编辑），system prompt base 模板仅含通用规则
- 这是 P5.x 阶段已确认的设计差异：Charles base prompt 精简（828 chars），领域规则通过 AGENTS.md 注入；Cline base prompt 详尽（3695 chars），身份硬编码在 base

**评估**：Charles 额外但合理。Charles 的 AGENTS.md 身份声明是对 base prompt 精简策略的补偿——身份和领域规则统一放在可编辑的 AGENTS.md 中，便于用户调整。

### 3.7 股票代码格式/输出规范段定位修正（6.2.7 / 6.2.8）

计划文件 P6.2 表格 L2297-2298 将"股票代码格式段"和"输出规范段"列为 Charles AGENTS.md 的段落。**实测发现这两段不在 AGENTS.md 主体，而在 `general.md`**：

- `agent_config/rules/general.md` L8-14：`## 输出格式`（Markdown 格式、投资建议附带风险提示、研报五步法）
- `agent_config/rules/general.md` L29-35：`## 股票代码格式`（沪市/深市/北交所格式、get_kline.py 必须带后缀）
- `agent_config/rules/AGENTS.md` L56：`注: 股票代码格式、时间基准、输出规范等通用规则见 rules/general.md（由 rules_loader 自动加载）。`

**加载机制**：Charles 的 `rules_loader.py` 会自动扫描 `agent_config/rules/` 目录下所有 `.md` 文件（含 general.md / plan-mode-rules.md / research.md / trading.md），按 frontmatter 的 `enabled` 字段过滤后加载。因此 general.md 的内容会被自动注入 system prompt 的 rules 段，与 AGENTS.md 一起生效。

**评估**：计划描述需修正。股票代码格式段和输出规范段**功能上属于 Charles rules 体系**，但**结构上不在 AGENTS.md 主体段落**。Charles 通过"AGENTS.md 主规则 + general.md 通用规则 + 场景规则"的多文件拆分组织规则，而 Cline 通过单文件 AGENTS.md 组织规则。这是组织方式差异，非对齐缺口。

### 3.8 段落顺序差异

**Cline 段落顺序**（sdk/AGENTS.md，从"范围"到"细节"递进）：
1. Repository Scope（项目范围）
2. Package Boundaries（包边界）
3. Change Routing（变更路由）
4. Verifying Changes（验证变更）
5. Practical Guidance（实践指导）
6. Documentation Responsibilities（文档责任）

**Charles 段落顺序**（agent_config/rules/AGENTS.md，从"我是谁"到"怎么做"递进）：
1. 开头自然段（身份声明 + 工作流概述）
2. 工作模式（act/plan 切换）
3. 工具 vs 技能 决策树（最重要）
4. 工具选择原则（按数据类型）
5. 硬约束（投研场景特有）
6. 注脚引用（general.md）

**差异分析**：
- Cline 顺序遵循"先定义边界，再定义流程，最后定义责任"的开发文档逻辑
- Charles 顺序遵循"先声明身份，再定义模式，然后定义决策，最后定义约束"的 agent 规则逻辑
- 两者段落构成不重合，顺序无对应关系

**评估**：段落顺序差异源于段落构成差异，非独立对齐缺口。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 AGENTS.md 主体结构相关文件检查 nanobot 风格残留：
- `agent_config/rules/AGENTS.md`（Charles AGENTS.md 主体）
- `agent_config/rules/general.md`（被 AGENTS.md 引用的通用规则）
- `agent_config/rules/plan-mode-rules.md`、`research.md`、`trading.md`（同目录其他规则文件）
- `agent/rules_loader.py`（rules 目录加载器）
- `agent/context.py` L454-539（`_build_rules` AGENTS.md 加载逻辑）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent_config/rules/AGENTS.md` | 0 | 0 | Grep `nanobot` 无匹配 |
| `agent_config/rules/general.md` | 0 | 0 | Grep `nanobot` 无匹配 |
| `agent_config/rules/` 全目录 | 0 | 0 | Grep `nanobot` 全目录无匹配 |
| `agent/rules_loader.py` | 0 | 0 | Grep `nanobot` 无匹配 |
| `agent/context.py` `_build_rules` | 0 | 0 | L454-539 无 nanobot 字样（L275 的 extra_sections 注释残留属于 Phase 5.1/5.23 范畴，与本阶段 AGENTS.md 主体结构无关） |

### 4.3 残留详情

#### 4.3.1 注释残留（0 处）

经 Grep 检索 `agent_config/rules/` 全目录及 `agent/rules_loader.py`，**未发现任何 nanobot 字样的注释残留**。Charles AGENTS.md 的段落结构（身份声明 / 工作模式 / 决策树 / 工具选择 / 硬约束）是通用 agent 规则模式，非 nanobot 风格。

#### 4.3.2 实现逻辑残留（0 处）

经核查 AGENTS.md 主体结构相关全部代码：

- `agent_config/rules/AGENTS.md`：**纯 Markdown 规则文档**，无代码逻辑，无 nanobot 风格实现
- `agent/rules_loader.py`：**rules 目录加载器**，按 frontmatter `enabled` 字段过滤加载，无 nanobot 风格机制（无 `always` 预加载、无 `when_to_use` 字段、无 fallback 解析）
- `agent/context.py` `_build_rules`（L454-539）：**AGENTS.md + rules_dir + MODE_TAG/PLAN_MODE 拼接逻辑**，对齐 Cline effectiveRules 组装顺序，无 nanobot 风格实现逻辑

**关于 AGENTS.md 段落结构是否属于 nanobot 风格的判断**：

Charles AGENTS.md 的段落结构（身份声明 / 工作模式 / 决策树 / 工具选择 / 硬约束）属于通用 agent 规则文档模式，**非 nanobot 独有风格**：
- "身份声明"：所有 agent 规则文档通用（如 Anthropic Claude 的 system prompt 开头）
- "工作模式"：act/plan 模式切换是 Cline 也有的概念（Cline 的 MODE_TAG_INSTRUCTIONS）
- "决策树"：工具路由决策是通用 agent 模式
- "硬约束"：业务约束是垂直 agent 通用模式

与 Phase 4.20 发现的 nanobot 风格特征（`always` 预加载、`when_to_use` 字段、三段式章节、PyYAML fallback）不同，AGENTS.md 的段落结构不属于 nanobot 风格特征。

**结论**：AGENTS.md 主体结构相关文件无 nanobot 风格残留（0 注释 + 0 实现逻辑）。

### 4.4 与历史阶段对比

| 阶段 | 检查范围 | 注释残留 | 实现逻辑残留 |
|------|---------|---------|-------------|
| Phase 4.20 | 技能系统（skills/ + SKILL.md + 脚本） | 15 | 45 |
| Phase 5.1 | SystemPromptBuilder 架构（context.py） | 1 | 0 |
| Phase 5.23 | System Prompt 长度（context.py + charles_system_prompt.py + plan_mode.py） | 1 | 0 |
| **Phase 6.2** | **AGENTS.md 主体结构（rules/ + rules_loader.py + context.py `_build_rules`）** | **0** | **0** |

**本阶段是迄今首次实现 nanobot 残留为 0 的阶段**。AGENTS.md 主体结构与 rules 加载机制完全对齐 Cline effectiveRules 模式，无 nanobot 风格残留。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **6.2.1 主体风格差异**：Cline 开发参考文档 vs Charles 业务规则文档。设计取向差异，无需对齐。
- **6.2.2 项目边界段**：Charles 无此段。单 agent 架构无包边界概念，合理缺失。
- **6.2.3 路由规则段**：Cline Change Routing vs Charles 决策树。形式不同但语义对齐，无需对齐。
- **6.2.4 验证规则段**：Charles 无独立验证段。验证逻辑分散在 SKILL.md 失败处理中，合理。
- **6.2.5 开发约束段**：Cline Practical Guidance vs Charles 硬约束。形式不同但语义对齐，无需对齐。
- **6.2.6 身份声明段**：Charles 额外但合理，补偿 base prompt 精简策略。
- **nanobot 残留**：0 处，无需修复。

### 5.2 优先级 P1（建议处理）

- **6.2.7 / 6.2.8 计划文件描述修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2297-2298，将"股票代码格式段"和"输出规范段"的定位从"Charles AGENTS.md 主体段落"修正为"Charles general.md 段落（通过 rules_loader 自动加载，AGENTS.md L56 注脚引用）"。这避免后续对齐工作误判 AGENTS.md 主体段落构成。

### 5.3 优先级 P2（可选优化）

- **Charles AGENTS.md 段落顺序优化**：当前顺序为"身份 → 模式 → 决策树 → 工具选择 → 硬约束 → 引用"。建议考虑将"硬约束"段落前移到"工作模式"之后（即身份 → 模式 → 硬约束 → 决策树 → 工具选择 → 引用），使 LLM 先感知业务约束再学习工具选择。这是可选优化，非对齐缺口。

- **Charles AGENTS.md 补充验证规则段（可选）**：可考虑在 AGENTS.md 末尾添加"## 验证规则"段落，集中说明"工具执行后如何验证结果"（如 read_files 后检查文件存在、run_commands 后检查退出码）。当前验证逻辑分散在 SKILL.md 中，集中一段可提高 LLM 验证意识。但此为可选增强，非对齐缺口。

### 5.4 优先级 P3（文档修正）

- **计划文件 P6.2 段落清单修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2282-2288 的 Charles 段落清单：
  - 修正前：身份声明 / 硬约束 / 工具 vs 技能 决策树 / 股票代码格式 / 输出规范
  - 修正后：身份声明 / 工作模式 / 工具 vs 技能 决策树 / 工具选择原则 / 硬约束 / general.md 引用
  - 新增"工作模式"段（L12-17）和"工具选择原则"段（L40-47）
  - 移除"股票代码格式"和"输出规范"段（实际在 general.md）

- **计划文件 P6.2 Cline 段落清单修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2276-2280 的 Cline 段落清单：
  - 修正前：项目边界 / 路由规则 / 验证规则 / 开发约束
  - 修正后：Repository Scope / Package Boundaries / Change Routing / Verifying Changes / Practical Guidance / Documentation Responsibilities
  - 新增"Package Boundaries"段和"Documentation Responsibilities"段

---

## 六、验证方法

### 6.1 AGENTS.md 段落结构验证

```powershell
# Cline sdk/AGENTS.md 段落清单
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^## "
# 预期: 6 个匹配（Repository Scope / Package Boundaries / Change Routing / Verifying Changes / Practical Guidance / Documentation Responsibilities）

# Charles AGENTS.md 段落清单
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^## "
# 预期: 4 个匹配（工作模式 / 工具 vs 技能 决策树 / 工具选择原则 / 硬约束）

# Charles general.md 段落清单（验证股票代码格式/输出规范在此文件）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\general.md" -Pattern "^## "
# 预期: 包含"输出格式"和"股票代码格式"段落
```

### 6.2 nanobot 残留验证

```powershell
# AGENTS.md 主体结构相关文件 nanobot 检索（预期全部无匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\general.md" -Pattern "nanobot" -CaseSensitive:$false
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "nanobot" -CaseSensitive:$false

# rules 目录全目录检索（预期无匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" -Pattern "nanobot" -CaseSensitive:$false
```

### 6.3 段落内容等价性验证

```powershell
# Cline Change Routing 段（路由规则）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "Route changes to the package"
# 预期: L43 匹配

# Charles 决策树段（路由规则等价）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "决策树"
# 预期: L19 匹配

# Cline Practical Guidance 段（开发约束）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "Practical Guidance"
# 预期: L88 匹配

# Charles 硬约束段（开发约束等价）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "硬约束"
# 预期: L49 匹配
```

### 6.4 general.md 引用验证

```powershell
# Charles AGENTS.md L56 注脚引用 general.md
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "general\.md"
# 预期: L56 匹配，内容为"注: 股票代码格式、时间基准、输出规范等通用规则见 rules/general.md"
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划预判 | 实测结论 | 状态 | 说明 |
|--------|---------|---------|------|------|
| 6.2.1 主体风格 | 开发参考文档 / 业务规则堆叠 | ✓ 完全符合 | **符合** | Cline 面向开发者，Charles 面向 LLM |
| 6.2.2 项目边界段 | 是 / 无 | ✓ 符合 | **符合** | Cline 有 Repository Scope + Package Boundaries；Charles 无 |
| 6.2.3 路由规则段 | 是 / 决策树 | ✓ 符合 | **符合** | Cline Change Routing vs Charles 决策树，形式不同但等价 |
| 6.2.4 验证规则段 | 是 / 无 | ✓ 符合 | **符合** | Cline Verifying Changes；Charles 验证分散在 SKILL.md |
| 6.2.5 开发约束段 | 是 / 硬约束段 | ✓ 符合 | **符合** | Cline Practical Guidance vs Charles 硬约束，形式不同但等价 |
| 6.2.6 身份声明段 | 无 / 是 | ✓ 符合 | **符合** | Cline 身份在 base prompt；Charles 在 AGENTS.md 开头 |
| 6.2.7 股票代码格式段 | 无 / 是（AGENTS.md） | ⚠ 定位偏差 | **需修正** | Charles 有此内容，但在 general.md，非 AGENTS.md 主体 |
| 6.2.8 输出规范段 | 无 / 是（AGENTS.md） | ⚠ 定位偏差 | **需修正** | Charles 有此内容，但在 general.md，非 AGENTS.md 主体 |

**计划表标注总结**：8 项中 6 项完全符合预判，2 项存在定位偏差（6.2.7 / 6.2.8 的段落定位在 general.md 而非 AGENTS.md 主体）。计划表对 Cline 和 Charles 的段落清单描述均有遗漏（Cline 遗漏 Package Boundaries 和 Documentation Responsibilities 两段；Charles 遗漏工作模式和工具选择原则两段，多列股票代码格式和输出规范两段）。建议按本报告实测数据修正。

**nanobot 残留总结**：AGENTS.md 主体结构相关文件 0 处注释残留 + 0 处实现逻辑残留。本阶段是迄今首次实现 nanobot 残留为 0 的阶段，AGENTS.md 主体结构与 rules 加载机制完全对齐 Cline effectiveRules 模式。
