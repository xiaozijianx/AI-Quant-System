# Phase 6.11 AGENTS.md 段落顺序对比

> 对比范围：Cline `third_party/cline/sdk/AGENTS.md` 的段落（section）顺序与 Charles `agent_config/rules/AGENTS.md` 的段落顺序逐项对标；重点对比"身份声明 / 工作模式 / 决策树 / 工具选择 / 硬约束"等业务段落的出现位置与排列次序；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md` L1-109（全文，6 个二级段落）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md` L1-56（全文，5 个二级段落 + 1 个尾注）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 段落顺序与段落集合。**核心结论：双方段落顺序完全不同、段落数量不同、风格定位不同，这是合理的"开发参考 vs 业务规则"定位差异，非缺陷。**计划文件 P6.11 的描述与双方实际源码基本吻合，但段落数与细节描述存在小幅偏差（详见 3.1）。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.11（L2453-2475）给出的段落顺序概要：

| 项目 | 计划描述 | 实际源码核实 |
|------|---------|-------------|
| Cline 段落顺序 | 边界→路由→验证→约束 | **范围→边界→路由→验证→实践指导→文档职责**（计划漏列"范围/Scope"和"文档职责"，且把"实践指导"简化为"约束"） |
| Cline 段落数 | 4 | **6**（实际为 6 个二级段落） |
| Charles 段落顺序 | 身份→约束→决策树→格式→输出 | **身份声明→工作模式→决策树→工具选择原则→硬约束**（计划漏列"工作模式"，"格式/输出"在主 AGENTS.md 中未单独成段，仅以尾注引用 general.md） |
| Charles 段落数 | 5 | **5**（与计划一致，但其中"格式/输出"实际为尾注引用而非独立段落） |
| 风格 | 开发参考 vs 业务规则 | ✓ 一致 |

**修正要点**：
1. Cline 段落数应为 **6**（非 4）：计划漏列 `## Repository Scope`（L11-15）和 `## Documentation Responsibilities`（L103-109）。
2. Cline "约束"段落实为 `## Practical Guidance`（L88-101，含 `### Keep Boundaries Clean` 和 `### Refactor Standard`），更准确的描述是"实践指导/重构准则"而非"约束"。
3. Charles "格式/输出"在主 AGENTS.md 中**未独立成段**，仅 L56 尾注引用 `rules/general.md`（"股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`"）。实际格式/输出规范托管在 `general.md`，不在 AGENTS.md 本体。

### 核心结论

1. **段落顺序完全不同**：Cline 以"工程架构"为主线（范围→边界→路由→验证→实践→文档），Charles 以"业务行为"为主线（身份→工作模式→决策树→工具选择→硬约束）。双方无任何段落顺序重合点。
2. **段落数量不同**：Cline 6 个二级段落，Charles 5 个二级段落（+1 尾注）。Cline 段落更细分（有子标题 `###`），Charles 段落更扁平（无 `###` 子标题）。
3. **风格定位根本性差异**：Cline AGENTS.md 是"SDK 开发参考"（写给 SDK 贡献者看，描述包边界/依赖方向/变更路由/验证命令/重构准则/文档职责），Charles AGENTS.md 是"投研业务规则"（写给 Agent 自身看，描述身份/工作模式/工具决策树/工具选择原则/硬约束）。这是合理的产品定位差异，非对齐缺口。
4. **Charles 无 Cline 对应段落的缺失**：Charles AGENTS.md 不需要 `Repository Scope` / `Package Boundaries` / `Change Routing` / `Verifying Changes` / `Practical Guidance` / `Documentation Responsibilities` —— 这些是 SDK 工程化概念，对单 Agent 投研助手无意义。
5. **Cline 无 Charles 对应段落的缺失**：Cline AGENTS.md 不需要"身份声明/工作模式/工具决策树/硬约束"—— Cline 的身份声明、工作模式、决策树逻辑分散在 `cline.ts` 的 `buildClineSystemPrompt` 等系统提示构造代码中，而非 AGENTS.md。
6. **nanobot 残留**：P6.11 范围内（仅 2 个 AGENTS.md 文件）**0 处残留**（注释残留 0、实现逻辑残留 0）。

### 一致性总体评估

- **段落顺序一致性**：**低**（双方顺序完全不同，但属合理差异）
- **段落数量一致性**：**低**（Cline 6 / Charles 5，但属合理差异）
- **风格定位一致性**：**低**（开发参考 vs 业务规则，但属合理差异）
- **段落顺序"是否应对齐"评估**：**不应强行对齐**。Cline 与 Charles 的 AGENTS.md 服务于不同对象（SDK 贡献者 vs Agent 自身），段落顺序差异是产品定位差异的合理体现。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.11.1 | 段落顺序 | 范围→边界→路由→验证→实践指导→文档职责 | 身份声明→工作模式→决策树→工具选择原则→硬约束 | 低 | 双方顺序完全不同，属合理差异（开发参考 vs 业务规则） |
| 6.11.2 | 段落数 | 6（二级段落 `##`） | 5（二级段落 `##`）+1 尾注 | 低 | Cline 段落更细分（含 `###` 子标题），Charles 更扁平 |
| 6.11.3 | 风格 | 开发参考（SDK 贡献者视角） | 业务规则（Agent 自身视角） | 低 | 风格定位根本性不同，非对齐缺口 |
| 6.11.4 | 身份声明段落 | 无（身份声明在 `cline.ts` 系统提示构造中，非 AGENTS.md） | 有（L7-10 `# Charles - AI 投研情报官`，含身份+工作流概述） | 低 | Charles 把身份声明作为首段，Cline AGENTS.md 无身份声明（Cline 身份由 `buildClineSystemPrompt` 注入） |
| 6.11.5 | 工作模式段落 | 无（无 act/plan 模式概念） | 有（L12-17 `## 工作模式`，Act/Plan 双模式 + 切换工具） | 低 | Charles 扩展。Cline 无模式切换概念，故 AGENTS.md 无此段 |
| 6.11.6 | 决策树段落 | 无（决策逻辑在 `cline.ts` 工具注册/系统提示中） | 有（L19-38 `## 工具 vs 技能 决策树（最重要）`，4 步决策 + 禁止行为） | 低 | Charles 扩展。Cline 的工具选择逻辑由系统提示注入，非 AGENTS.md 段落 |
| 6.11.7 | 工具选择段落 | 无（工具说明在系统提示 `tools` 段，非 AGENTS.md） | 有（L40-47 `## 工具选择原则（按数据类型）`，6 类数据→技能/工具映射） | 低 | Charles 扩展。Cline 的工具选择由 `tools` 系统提示段处理，AGENTS.md 不涉及 |
| 6.11.8 | 硬约束段落 | 部分对应（L88-101 `## Practical Guidance` 含边界约束，但语义不同） | 有（L49-55 `## 硬约束（投研场景特有）`，4 条投研禁止项） | 低 | 语义不同。Cline 的"实践指导"是工程边界（不要把状态逻辑下沉到 agents），Charles 的"硬约束"是业务禁止（禁止用 web_search 查本地股价） |
| 6.11.9 | 仓库范围段落 | 有（L11-15 `## Repository Scope`） | 无 | 低 | Charles 无 SDK 工程概念，无需此段 |
| 6.11.10 | 包边界段落 | 有（L17-39 `## Package Boundaries`，含 Published Packages + Dependency Direction） | 无 | 低 | Charles 无 monorepo 多包结构，无需此段 |
| 6.11.11 | 变更路由段落 | 有（L41-50 `## Change Routing`） | 无 | 低 | Charles 无多包变更路由概念，无需此段 |
| 6.11.12 | 验证命令段落 | 有（L52-86 `## Verifying Changes`，含 bun install/build/test 命令） | 无 | 低 | Charles 的验证由测试脚本/集成测试处理，非 AGENTS.md 范围 |
| 6.11.13 | 文档职责段落 | 有（L103-109 `## Documentation Responsibilities`，列出 README/CONTRIBUTING/AGENTS/ARCHITECTURE/DOC 更新时机） | 无 | 低 | Charles 无多文档协作维护场景，无需此段 |
| 6.11.14 | 格式/输出规范段落 | 无 | 无独立段落（L56 尾注引用 `rules/general.md`） | 中 | 双方 AGENTS.md 本体均无格式/输出规范段落。Charles 托管在 general.md，Cline 托管在系统提示 |
| 6.11.15 | 子标题层级 | 有 `###` 三级标题（L19/26/90/97） | 无 `###` 三级标题 | 低 | Cline 段落更细分，Charles 段落更扁平 |

---

## 三、重点差距详解

### 3.1 计划文件 P6.11 的描述偏差

AGENT_COMPARISON_PLAN_V2.md L2455-2467 给出的段落顺序概要与实际源码存在偏差：

**Cline 段落顺序**：
- 计划描述：边界→路由→验证→约束（4 段）
- 实际源码：范围→边界→路由→验证→实践指导→文档职责（6 段）

实际 Cline `sdk/AGENTS.md` 的 6 个二级段落（按出现顺序）：
1. `## Repository Scope`（L11-15）— 仓库范围
2. `## Package Boundaries`（L17-39）— 包边界
3. `## Change Routing`（L41-50）— 变更路由
4. `## Verifying Changes`（L52-86）— 验证变更
5. `## Practical Guidance`（L88-101）— 实践指导（计划误标为"约束"）
6. `## Documentation Responsibilities`（L103-109）— 文档职责

计划漏列了首段（Repository Scope）和末段（Documentation Responsibilities），并将 Practical Guidance 误标为"约束"。计划描述的"边界→路由→验证→约束"实际对应 Cline 的 L17-101 段落（漏了首尾两段）。

**Charles 段落顺序**：
- 计划描述：身份→约束→决策树→格式→输出（5 段）
- 实际源码：身份声明→工作模式→决策树→工具选择原则→硬约束（5 段 + 1 尾注）

实际 Charles `agent_config/rules/AGENTS.md` 的 5 个二级段落（按出现顺序）：
1. `# Charles - AI 投研情报官`（L7-10）— 身份声明 + 工作流概述（一级标题段落）
2. `## 工作模式`（L12-17）— Act/Plan 双模式
3. `## 工具 vs 技能 决策树（最重要）`（L19-38）— 决策树
4. `## 工具选择原则（按数据类型）`（L40-47）— 工具选择原则
5. `## 硬约束（投研场景特有）`（L49-55）— 硬约束
6. L56 尾注：股票代码格式/时间基准/输出规范引用 `rules/general.md`

计划描述的"身份→约束→决策树→格式→输出"与实际顺序不符：
- 实际顺序是"身份→工作模式→决策树→工具选择→硬约束"，约束在最后（非第二位）
- 计划漏列"工作模式"段落
- "格式/输出"在主 AGENTS.md 中无独立段落，仅为 L56 尾注引用

**修正建议**：计划表 6.11.1 应改为"Cline 顺序：范围→边界→路由→验证→实践指导→文档职责 / Charles 顺序：身份→工作模式→决策树→工具选择→硬约束"。计划表 6.11.2 的 Cline 段落数应改为 6（非 4）。

### 3.2 段落顺序差异的本质：开发参考 vs 业务规则

双方 AGENTS.md 的段落顺序差异源于**服务对象不同**：

| 维度 | Cline AGENTS.md | Charles AGENTS.md |
|------|----------------|------------------|
| 服务对象 | SDK 贡献者（人类开发者） | Agent 自身（LLM 运行时） |
| 文档定位 | 开发参考（onboarding + 边界约束） | 业务规则（身份 + 行为约束） |
| 主线 | 工程架构（包边界 + 变更路由 + 验证） | 业务行为（身份 + 决策树 + 硬约束） |
| 段落顺序逻辑 | 从"在哪开发"到"如何验证"到"如何维护文档" | 从"我是谁"到"如何决策"到"什么不能做" |

Cline 的段落顺序是典型的 SDK 工程文档结构：
1. `Repository Scope` — 先界定工作范围
2. `Package Boundaries` — 再讲包边界
3. `Change Routing` — 再讲变更路由
4. `Verifying Changes` — 再讲验证方法
5. `Practical Guidance` — 最后讲实践指导
6. `Documentation Responsibilities` — 末尾讲文档维护职责

Charles 的段落顺序是典型的 Agent 系统提示结构：
1. 身份声明 — 先告诉 LLM"你是谁"
2. 工作模式 — 再讲 Act/Plan 模式切换
3. 决策树 — 再讲工具 vs 技能决策（核心）
4. 工具选择原则 — 再讲按数据类型选工具
5. 硬约束 — 最后讲投研场景禁止项

**结论**：双方段落顺序差异是产品定位差异的合理体现，**不应强行对齐**。若 Charles 照搬 Cline 的"范围→边界→路由"顺序，会把无关的 SDK 工程概念塞进投研 Agent 的系统提示，反而稀释业务规则的优先级。

### 3.3 Charles 段落顺序的内部逻辑评估

Charles AGENTS.md 的段落顺序遵循"身份→能力→约束"的递进逻辑：

1. **身份声明（L7-10）**：先确立"Charles，专业 AI 投研情报官"身份 + 工作流概述（skills 工具 → 结构化工具）
2. **工作模式（L12-17）**：再讲 Act/Plan 双模式（直接执行 vs 先规划后执行）+ 切换工具
3. **决策树（L19-38，标注"最重要"）**：再讲工具 vs 技能的 4 步决策（核心规则）
4. **工具选择原则（L40-47）**：再讲按数据类型选工具（6 类数据→技能/工具映射）
5. **硬约束（L49-55）**：最后讲投研场景禁止项（4 条禁止）

这个顺序的逻辑链：
- 身份 → 告诉 LLM 角色
- 工作模式 → 告诉 LLM 执行方式
- 决策树 → 告诉 LLM 如何选择工具（核心）
- 工具选择原则 → 决策树的补充（按数据类型细化）
- 硬约束 → 底线禁止项

**评估**：Charles 的段落顺序内部逻辑自洽，符合 Agent 系统提示的"先身份后行为后约束"惯例。决策树段标注"（最重要）"明确优先级，硬约束放最后作为底线提醒。

### 3.4 Cline 段落顺序的内部逻辑评估

Cline AGENTS.md 的段落顺序遵循"范围→边界→路由→验证→实践→文档"的工程文档结构：

1. **Repository Scope（L11-15）**：界定 SDK 工作区范围（sdk/ 而非 legacy repo root）
2. **Package Boundaries（L17-39）**：列出 4 个发布包 + 依赖方向（mermaid 图）
3. **Change Routing（L41-50）**：按 concern 路由变更到对应包
4. **Verifying Changes（L52-86）**：验证命令（bun install/build/test/check）
5. **Practical Guidance（L88-101）**：实践指导（边界清洁 + 重构准则）
6. **Documentation Responsibilities（L103-109）**：文档维护职责（README/CONTRIBUTING/AGENTS/ARCHITECTURE/DOC）

**评估**：Cline 的段落顺序是典型的 SDK 工程文档结构，从"在哪开发"到"如何开发"到"如何验证"到"如何维护文档"，逻辑递进清晰。这种结构对 SDK 贡献者友好，但对投研 Agent 的 LLM 运行时无意义。

### 3.5 Charles "格式/输出规范"段落缺失分析

计划描述 Charles 段落顺序包含"格式/输出"，但实际 `agent_config/rules/AGENTS.md` **无独立的"格式/输出"段落**，仅在 L56 以尾注形式引用：

```
注: 股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`（由 rules_loader 自动加载）。
```

这表明 Charles 的格式/输出规范**托管在 `rules/general.md`**，由 `rules_loader.py` 自动加载，而非内联在 AGENTS.md 本体。这是合理的规则去重设计（P6.4 已审计）：

- AGENTS.md 聚焦"身份 + 决策 + 约束"（投研特有）
- general.md 聚焦"格式 + 时间 + 输出"（通用规则）

**对比 Cline**：Cline AGENTS.md 同样不包含格式/输出规范（Cline 的格式/输出由系统提示 `mode`/`user_input` 段处理，非 AGENTS.md 范围）。双方在"格式/输出规范不放在 AGENTS.md 本体"这一点上**行为一致**。

### 3.6 段落顺序对 LLM 行为的影响

Charles AGENTS.md 作为 Agent 系统提示的一部分（`alwaysApply: true` + `applyTo: [act, plan]`），段落顺序直接影响 LLM 的注意力分配：

- **身份声明在前**：LLM 首先建立"投研情报官"角色认知，后续决策基于此身份
- **决策树标注"最重要"**：明确告诉 LLM 工具选择是核心规则
- **硬约束在最后**：作为底线提醒，符合"先讲该做什么，再讲不该做什么"的提示工程惯例

若按 Cline 顺序（范围→边界→路由）排列，LLM 会先看到无关的 SDK 工程概念，导致身份认知延迟、决策树优先级降低。**Charles 当前的段落顺序对投研 Agent 的 LLM 行为更友好**。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.11 范围内仅涉及以下 2 个文件：
- `third_party/cline/sdk/AGENTS.md`（109 行）
- `agent_config/rules/AGENTS.md`（56 行）

### 4.2 检查方法

1. Grep `agent_config/rules/AGENTS.md` 搜索 `nanobot`（case-insensitive）
2. Grep `third_party/cline/sdk/AGENTS.md` 搜索 `nanobot`（case-insensitive）
3. 逐行人工审阅双方 AGENTS.md 全文，确认无 nanobot 风格特征

### 4.3 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `third_party/cline/sdk/AGENTS.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样（case-insensitive 搜索 0 匹配）。段落均为 Cline SDK 原生工程文档，无 nanobot 风格 |
| `agent_config/rules/AGENTS.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样（case-insensitive 搜索 0 匹配）。段落均为 Charles 投研业务规则，无 nanobot 风格（无 camelCase 函数名、无 dict 数据结构、无 try/except fallback、无 JSON 配置、无脚本直接 import） |

**P6.11 范围内 nanobot 残留总计：0 处（注释 0 + 实现逻辑 0）。**

### 4.4 段落风格 nanobot 特征排查

针对 AGENTS.md 这种 Markdown 规则文件，nanobot 风格特征主要表现为：
- 段落标题使用英文 camelCase（如 `## getSkillMetadata`）
- 引用 nanobot 内部函数/类名（如 `SkillsLoader`、`build_skills_summary`）
- 引用 nanobot 文件路径（如 `nanobot/skills/`）
- 注释中提到"对标 nanobot"

**Charles AGENTS.md 排查结果**：
- 段落标题均为中文业务术语（`## 工作模式` / `## 工具 vs 技能 决策树` / `## 工具选择原则` / `## 硬约束`），无 camelCase
- 无 nanobot 内部函数/类名引用
- 引用的路径为 `agent_config/skills/stock-price/scripts/get_kline.py`（Charles 自有路径），非 nanobot 路径
- 无"对标 nanobot"注释

**Cline AGENTS.md 排查结果**：
- 段落标题均为英文工程术语（`## Repository Scope` / `## Package Boundaries` / `## Change Routing`），无 camelCase
- 引用的路径为 `sdk/packages/llms/AGENTS.md`（Cline 自有路径），非 nanobot 路径
- 无 nanobot 引用

**结论**：双方 AGENTS.md 均无 nanobot 残留，段落风格均为各自原生设计。

### 4.5 范围外残留说明

以下文件的 nanobot 残留**超出 P6.11 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1（已记录） |
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/tools/base.py` L2/L11/L37/L188 | 注释残留 | docstring 对标 nanobot Tool 基类 | F-base（P7.19） |
| `pages/tab1_chat.py` 多处 | 注释残留 | nanobot 版 Charles 加载逻辑注释 | 范围外（前端页面） |

---

## 五、修复建议

### 5.1 高优先级：修正计划文件 P6.11 的描述偏差

**问题**：AGENT_COMPARISON_PLAN_V2.md L2455-2467 的段落顺序描述与实际源码不符：
- Cline 段落顺序漏列 `Repository Scope` 和 `Documentation Responsibilities`
- Cline 段落数标注 4，实际为 6
- Charles 段落顺序漏列 `工作模式`，且"格式/输出"在主 AGENTS.md 中无独立段落
- Charles "约束"实际在第 5 位（非第 2 位）

**修复**：将 L2455-2467 改为：

```
**Cline AGENTS.md 段落顺序**：
1. Repository Scope（仓库范围）
2. Package Boundaries（包边界）
3. Change Routing（变更路由）
4. Verifying Changes（验证变更）
5. Practical Guidance（实践指导）
6. Documentation Responsibilities（文档职责）

**Charles AGENTS.md 段落顺序**：
1. 身份声明（# Charles - AI 投研情报官）
2. 工作模式（Act/Plan 双模式）
3. 工具 vs 技能 决策树（最重要）
4. 工具选择原则（按数据类型）
5. 硬约束（投研场景特有）
+ 尾注：格式/输出规范引用 rules/general.md
```

将 L2468-2472 对比表改为：

| # | 对比项 | Cline 顺序 | Charles 顺序 | 关键差异 |
|---|--------|-----------|-------------|---------|
| 6.11.1 | 段落顺序 | 范围→边界→路由→验证→实践→文档 | 身份→工作模式→决策树→工具选择→硬约束 | 顺序完全不同（开发参考 vs 业务规则） |
| 6.11.2 | 段落数 | 6 | 5（+1 尾注） | 数量不同 |
| 6.11.3 | 风格 | 开发参考 | 业务规则 | 风格不同 |

### 5.2 低优先级：Charles 段落顺序是否调整（不建议修改）

**问题**：Charles AGENTS.md 的"硬约束"段落放在最后（第 5 位），有人可能认为应前置以提高禁止项的注意力。

**修复建议**：**不建议修改**。当前顺序符合 Agent 系统提示的"先身份后行为后约束"惯例：
- 身份声明在前 → 建立 LLM 角色认知
- 决策树在中（标注"最重要"）→ 明确核心规则
- 硬约束在后 → 作为底线提醒

若将硬约束前置，会打断"身份→能力→约束"的递进逻辑。当前顺序对 LLM 行为更友好。

### 5.3 低优先级：Cline 段落顺序是否参考（不建议修改）

**问题**：Cline AGENTS.md 的"范围→边界→路由"段落顺序是否应引入 Charles。

**修复建议**：**不建议修改**。Cline 的段落顺序服务于 SDK 工程文档，对投研 Agent 的 LLM 运行时无意义。Charles 当前的"身份→工作模式→决策树→工具选择→硬约束"顺序对投研 Agent 更友好。

### 5.4 低优先级：Charles 尾注是否升级为独立段落（不建议修改）

**问题**：Charles L56 尾注"股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`"是否应升级为独立的"## 格式/输出规范"段落。

**修复建议**：**不建议修改**。当前尾注设计是合理的规则去重：
- AGENTS.md 聚焦投研特有规则（身份 + 决策 + 约束）
- general.md 聚焦通用规则（格式 + 时间 + 输出）

若将尾注升级为独立段落并在 AGENTS.md 内联格式/输出规范，会与 general.md 重复（P6.4 已审计的去重设计）。保留尾注引用即可。

---

## 六、验证方法

### 6.1 段落顺序对比验证

1. 读取 Cline `sdk/AGENTS.md` 全文（109 行），按 `^## ` 正则提取所有二级段落标题，确认顺序为：
   - `## Repository Scope`（L11）
   - `## Package Boundaries`（L17）
   - `## Change Routing`（L41）
   - `## Verifying Changes`（L52）
   - `## Practical Guidance`（L88）
   - `## Documentation Responsibilities`（L103）
2. 读取 Charles `agent_config/rules/AGENTS.md` 全文（56 行），按 `^## ` 正则提取所有二级段落标题，确认顺序为：
   - `## 工作模式`（L12）
   - `## 工具 vs 技能 决策树（最重要）`（L19）
   - `## 工具选择原则（按数据类型）`（L40）
   - `## 硬约束（投研场景特有）`（L49）
3. 确认 Charles L7-10 的一级标题 `# Charles - AI 投研情报官` 作为身份声明段落（非 `##` 二级标题）
4. 确认 Charles L56 尾注为格式/输出规范引用（非独立段落）

### 6.2 段落数量对比验证

1. 统计 Cline AGENTS.md 的 `## ` 二级标题数量 = 6
2. 统计 Charles AGENTS.md 的 `## ` 二级标题数量 = 4（工作模式/决策树/工具选择原则/硬约束）+ 1 个一级标题段落（身份声明）= 5 个段落 + 1 尾注
3. 确认 Cline 含 `### ` 三级标题（4 个：Published SDK Packages / Dependency Direction / Keep Boundaries Clean / Refactor Standard），Charles 无 `### ` 三级标题

### 6.3 nanobot 残留验证

1. Grep `agent_config/rules/AGENTS.md` 搜索 `nanobot`（case-insensitive），确认 0 匹配
2. Grep `third_party/cline/sdk/AGENTS.md` 搜索 `nanobot`（case-insensitive），确认 0 匹配
3. 逐行审阅双方 AGENTS.md，确认无 nanobot 风格特征（camelCase 标题 / nanobot 函数名 / nanobot 路径 / 对标 nanobot 注释）

### 6.4 计划文件偏差验证

1. 读取 `AGENT_COMPARISON_PLAN_V2.md` L2455-2467，确认 Cline 段落顺序描述为"边界→路由→验证→约束"（4 段）
2. 对比 Cline `sdk/AGENTS.md` 实际段落（6 段），确认计划漏列 Repository Scope 和 Documentation Responsibilities
3. 确认计划 Charles 段落顺序描述为"身份→约束→决策树→格式→输出"，与实际"身份→工作模式→决策树→工具选择→硬约束"不符
4. 确认计划 Cline 段落数标注 4，实际为 6

---

## 七、附录

### 7.1 Cline sdk/AGENTS.md 段落顺序实际内容

```
L1-5    frontmatter（description / globs / alwaysApply）
L7-9    # Cline SDK — Development Reference（标题 + 简介）
L11-15  ## Repository Scope（仓库范围）
L17-39  ## Package Boundaries（包边界）
          L19-24  ### Published SDK Packages
          L26-34  ### Dependency Direction（mermaid 图）
L41-50  ## Change Routing（变更路由）
L52-86  ## Verifying Changes（验证变更）
L88-101 ## Practical Guidance（实践指导）
          L90-95  ### Keep Boundaries Clean
          L97-101 ### Refactor Standard
L103-109 ## Documentation Responsibilities（文档职责）
```

### 7.2 Charles agent_config/rules/AGENTS.md 段落顺序实际内容

```
L1-5    frontmatter（description / applyTo / alwaysApply）
L7-10   # Charles - AI 投研情报官（身份声明 + 工作流概述）
L12-17  ## 工作模式（Act/Plan 双模式 + 切换工具）
L19-38  ## 工具 vs 技能 决策树（最重要）（4 步决策 + 禁止行为）
L40-47  ## 工具选择原则（按数据类型）（6 类数据→技能/工具映射）
L49-55  ## 硬约束（投研场景特有）（4 条禁止项）
L56     尾注：股票代码格式/时间基准/输出规范引用 rules/general.md
```

### 7.3 双方段落顺序对比图

```
Cline sdk/AGENTS.md（开发参考，6 段）        Charles agent_config/rules/AGENTS.md（业务规则，5 段 + 尾注）
┌─────────────────────────────────┐        ┌─────────────────────────────────┐
│ ## Repository Scope             │        │ # Charles - AI 投研情报官       │ ← 身份声明
│ ## Package Boundaries           │        │ ## 工作模式                     │ ← 工作模式
│ ## Change Routing               │        │ ## 工具 vs 技能 决策树（最重要）│ ← 决策树
│ ## Verifying Changes            │        │ ## 工具选择原则（按数据类型）   │ ← 工具选择
│ ## Practical Guidance           │        │ ## 硬约束（投研场景特有）       │ ← 硬约束
│ ## Documentation Responsibilities│        │ 尾注：引用 rules/general.md     │ ← 格式/输出（引用）
└─────────────────────────────────┘        └─────────────────────────────────┘

双方段落顺序无任何重合点：
- Cline 主线：工程架构（范围→边界→路由→验证→实践→文档）
- Charles 主线：业务行为（身份→工作模式→决策树→工具选择→硬约束）
```

### 7.4 双方段落风格特征对比

| 维度 | Cline AGENTS.md | Charles AGENTS.md |
|------|----------------|------------------|
| 标题语言 | 英文（`## Repository Scope`） | 中文（`## 工作模式`） |
| 标题层级 | `##` + `###`（两级） | 仅 `##`（一级，扁平） |
| 段落数 | 6（二级）+ 4（三级） | 5（二级/一级）+ 1（尾注） |
| 含 mermaid 图 | 是（L28-34 依赖方向图） | 否 |
| 含代码块 | 是（L55-82 sh 命令块） | 否 |
| 含禁止项 | 部分（L92-95 "Don't move..."） | 是（L33-38 / L51-54 多条"禁止"） |
| 引用其他规则文件 | 是（L9/93/105-108 引用 CONTRIBUTING/ARCHITECTURE/DOC） | 是（L56 引用 rules/general.md） |
| 服务对象 | SDK 贡献者（人类） | Agent 自身（LLM） |
| 文档定位 | 开发参考 | 业务规则 |
