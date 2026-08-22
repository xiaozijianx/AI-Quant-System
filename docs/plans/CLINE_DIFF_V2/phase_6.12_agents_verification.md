# Phase 6.12 AGENTS.md 验证方法对比

> 对比范围：Cline `sdk/AGENTS.md` 的 `## Verifying Changes` 段（L51-86，含安装/构建/测试/lint/typecheck 命令）+ `sdk/packages/llms/AGENTS.md`（子包级，无验证段），与 Charles `agent_config/rules/AGENTS.md`（无验证方法段）+ `agent_config/rules/` 其他规则文件的验证相关内容逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md` L51-86（`## Verifying Changes` 段，6 条 shell 命令示例）
> - `third_party/cline/sdk/AGENTS.md` L88-108（`## Practical Guidance` + `## Documentation Responsibilities`，间接与验证相关）
> - `third_party/cline/sdk/packages/llms/AGENTS.md` L1-39（子包级，无验证段，仅 provider routing 指导）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md` L1-56（全文，无验证方法段）
> - `agent_config/rules/general.md`（通用规则，无验证段）
> - `agent_config/rules/plan-mode-rules.md` L34（仅出现"可验证的成功标准"字样，非命令）
> - `agent_config/rules/research.md` / `trading.md`（业务规则，无验证段）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 中的验证方法（构建命令、测试命令、lint 命令、typecheck 命令等）。**核心结论：Cline AGENTS.md 含完整的 `## Verifying Changes` 段（6 条 shell 命令，覆盖安装/构建/typecheck/test/lint/聚焦测试），Charles AGENTS.md 完全无验证方法段。这是两者 AGENTS.md 定位差异的直接体现——Cline 是 SDK 开发参考文档（面向人类开发者，必须含验证命令），Charles 是 LLM 业务规则文档（面向 LLM，无开发验证概念）。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.12（L2476-2487）列出的 4 个验证项（6.12.1-6.12.4）均**与 AGENTS.md 验证方法无关**：

| 计划项 | 计划描述 | 实测情况 | 偏差说明 |
|--------|---------|---------|---------|
| 6.12.1 | frontmatter 生效：检查 rules_loader 日志，AGENTS.md 按 alwaysApply 加载 | 与 P6.1 重复（frontmatter 字段评估） | **计划项错位**：此属 P6.1 frontmatter 范畴，非"验证方法" |
| 6.12.2 | 主体结构：打印 AGENTS.md 内容，含决策树段 | 与 P6.2 重复（主体结构） | **计划项错位**：此属 P6.2 主体结构范畴 |
| 6.12.3 | 去重：对比 AGENTS.md 与 rules，无重复 | 与 P6.4 重复（rules 去重） | **计划项错位**：此属 P6.4 去重范畴 |
| 6.12.4 | 条件注入：切换 mode，按 applyTo 注入 | 与 P6.6 重复（条件注入） | **计划项错位**：此属 P6.6 条件注入范畴 |

**计划文件 P6.12 的标题"AGENTS.md 验证方法"与实际列出的 4 个验证项不匹配**。标题指向"AGENTS.md 中描述的验证方法（构建/测试/lint 命令）"，但 4 个验证项实际是"AGENTS.md 加载机制的功能验证"（属 P6.1/P6.2/P6.4/P6.6 的运行时验证，而非 AGENTS.md 文档内容的对比）。

本报告按标题"AGENTS.md 验证方法"的字面含义执行——对比 AGENTS.md 文档中描述的验证方法（构建/测试/lint 命令），这是 P6.2 主体结构对比中 6.2.4 项的深化展开。

### 核心结论

1. **Cline 有完整验证段**：`sdk/AGENTS.md` L51-86 的 `## Verifying Changes` 段含 6 条 shell 命令，覆盖依赖安装（`bun install --frozen-lockfile`）、构建（`bun run build:sdk`）、typecheck（`bun run types`）、全量测试（`bun run test`）、综合检查（`bun run check` = lint + build + typecheck + check-publish）、聚焦测试（`bun -F @cline/<pkg> test`）。
2. **Charles 无验证段**：`agent_config/rules/AGENTS.md` 全文 56 行无任何构建/测试/lint 命令。Charles 的 AGENTS.md 定位是 LLM 行为规则，非开发者参考文档。
3. **Charles rules 目录其他文件也无验证段**：`general.md` / `plan-mode-rules.md` / `research.md` / `trading.md` 均无开发验证命令。`plan-mode-rules.md` L34 出现"可验证的成功标准"字样，但是 plan 内容要求（plan 须含成功标准），非开发验证命令。
4. **Cline 子包 AGENTS.md 也无验证段**：`sdk/packages/llms/AGENTS.md`（39 行）无 `## Verifying Changes` 段，仅有 provider routing 指导。验证命令集中在 workspace 根 AGENTS.md，子包级 AGENTS.md 只关注包内开发约定。
5. **Cline 验证段的上下文说明完整**：除命令本身外，L60-62 解释了为何需要 `build:sdk`（dist 缺失时 sibling 包解析失败），L84 解释了聚焦测试失败的处置流程（先 build 依赖包，再重跑，属 workspace 设置问题非源码 bug）。Charles 无等价说明。
6. **Cline 验证段含文档维护约束**：L86 "If you touch hub/bootstrap/session flows, please update ARCHITECTURE.md"——将代码变更与文档更新绑定。Charles 无此约束（Charles 无 ARCHITECTURE.md 等开发者文档）。
7. **Cline 验证段与 Documentation Responsibilities 段联动**：L103-108 的 `## Documentation Responsibilities` 段定义了 5 个文档（README/CONTRIBUTING/AGENTS/ARCHITECTURE/DOC）的更新触发条件，与验证段的"update ARCHITECTURE.md"形成闭环。Charles 无文档维护约束。
8. **Charles 的"验证"语义在 SKILL.md 而非 AGENTS.md**：Charles 的验证逻辑分散在各 skill 的 SKILL.md "失败处理"段（如 financial-analysis 技能的 CSV 校验、stock-price 技能的行情返回校验），不在 AGENTS.md。这是 Charles 架构选择——验证逻辑下沉到技能层。
9. **nanobot 残留**：P6.12 范围内（`agent_config/rules/` 全目录）**0 处残留**（注释残留 0、实现逻辑残留 0）。

### 一致性总体评估

- **验证方法段存在性**：**低**。Cline 有完整验证段，Charles 完全无。
- **验证命令完备性**：**低**。Cline 6 条命令覆盖完整开发链路，Charles 0 条。
- **验证上下文说明**：**低**。Cline 有失败处置流程说明，Charles 无。
- **文档维护约束**：**低**。Cline 有文档更新触发条件，Charles 无。
- **定位合理性**：**高**。两者各自在其架构中都是合理的——Cline 作为 SDK 必须有开发验证命令，Charles 作为单 agent 应用无需开发验证命令。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.12.1 | 验证段存在性 | 有（`## Verifying Changes`，L51-86，36 行） | 无（AGENTS.md 全文 56 行无验证段） | 低 | Cline 有独立验证段，Charles 无。定位差异：Cline 面向开发者，Charles 面向 LLM |
| 6.12.2 | 依赖安装命令 | 有（`bun install --frozen-lockfile`，L57） | 无 | 低 | Cline 用 bun 锁定依赖版本，Charles 是 Python 单 agent 应用，依赖安装不在 AGENTS.md |
| 6.12.3 | 构建命令 | 有（`bun run build:sdk`，L63） | 无 | 低 | Cline 需构建 dist/ 供 sibling 包解析，Charles 无构建步骤（Python 解释执行） |
| 6.12.4 | typecheck 命令 | 有（`bun run types`，L69，注释"typecheck all packages"） | 无 | 低 | Cline 用 TypeScript 需类型检查，Charles 用 Python（类型检查由 mypy/IDE 处理，不在 AGENTS.md） |
| 6.12.5 | 测试命令 | 有（`bun run test`，L70，注释"run all tests"） | 无 | 低 | Cline 有全量测试命令，Charles 无测试命令在 AGENTS.md |
| 6.12.6 | lint 命令 | 有（`bun run check`，L71，注释"lint + build + typecheck + check-publish"） | 无 | 低 | Cline 的 `check` 是综合命令含 lint，Charles 无 lint 命令在 AGENTS.md |
| 6.12.7 | 聚焦测试命令 | 有（`bun -F @cline/<pkg> test`，L77-82，5 个包各一条） | 无 | 低 | Cline 支持按包聚焦测试，Charles 无等价概念 |
| 6.12.8 | 失败处置说明 | 有（L84，聚焦测试失败时先 build 依赖包再重跑，视为 workspace 设置问题非源码 bug） | 无 | 低 | Cline 有详细的失败处置流程，Charles 无 |
| 6.12.9 | 文档维护约束 | 有（L86，touch hub/bootstrap/session flows 须更新 ARCHITECTURE.md） | 无 | 低 | Cline 将代码变更与文档更新绑定，Charles 无文档维护约束 |
| 6.12.10 | 工作区根命令约束 | 有（L13-15，禁止从 legacy repo root 跑 `bun test sdk/...`，须从 `sdk/` 跑） | 无 | 低 | Cline 有工作区根路径约束，Charles 无（单 agent 应用无工作区概念） |
| 6.12.11 | dist 缺失处置 | 有（L60-62，dist 缺失时先 `build:sdk`） | 无 | 低 | Cline 的 sibling 包解析依赖 dist/，Charles 无此问题 |
| 6.12.12 | 子包级验证段 | 无（`sdk/packages/llms/AGENTS.md` 无验证段，仅 provider routing 指导） | 不适用（Charles 无子包概念） | 中 | Cline 验证命令集中在 workspace 根 AGENTS.md，子包级 AGENTS.md 只关注包内约定。Charles 无子包，不适用 |

---

## 三、重点差距详解

### 3.1 Cline 验证段的完整命令清单

Cline `sdk/AGENTS.md` L51-86 的 `## Verifying Changes` 段包含以下命令：

```sh
# 1. 依赖安装（L53-58）
cd sdk
bun install --frozen-lockfile

# 2. 构建（L60-64，dist 缺失时）
bun run build:sdk

# 3. 跨包综合命令（L66-72，SDK 根执行）
bun run types       # typecheck all packages
bun run test        # run all tests
bun run check       # lint + build + typecheck + check-publish

# 4. 聚焦测试（L74-82，按包执行）
bun -F @cline/shared test
bun -F @cline/llms test
bun -F @cline/agents test
bun -F @cline/core test:unit
bun -F @cline/cli test:unit
```

**命令分层设计**：
- **第 1 层（环境准备）**：`bun install --frozen-lockfile` + `bun run build:sdk`
- **第 2 层（全量验证）**：`bun run types` + `bun run test` + `bun run check`
- **第 3 层（聚焦验证）**：`bun -F @cline/<pkg> test`（5 个包各一条）

**第 2 层的 `bun run check` 是聚合命令**，等价于 `lint + build + typecheck + check-publish`，是 CI/发布前的综合检查。第 3 层用于开发过程中的快速反馈，避免每次跑全量。

### 3.2 Charles AGENTS.md 为何无验证段

Charles AGENTS.md 的段落构成（P6.2 已实测）：
1. 身份声明（L7-10）
2. 工作模式（L12-17）
3. 工具 vs 技能 决策树（L19-38）
4. 工具选择原则（L40-47）
5. 硬约束（L49-55）
6. 注脚引用（L56）

**无验证段的原因**：
- **定位差异**：Charles AGENTS.md 是 LLM 行为规则文档，受众是 LLM 而非人类开发者。LLM 不需要知道如何构建/测试代码，只需知道如何选择工具和执行任务。
- **架构差异**：Charles 是单 agent Python 应用，无 SDK 工作区、无多包构建、无 sibling 包 dist 依赖。开发验证由开发者自行用 pytest/mypy 处理，不在 AGENTS.md。
- **验证下沉**：Charles 的运行时验证逻辑分散在各 skill 的 SKILL.md "失败处理"段（如 financial-analysis 技能校验 CSV 列、stock-price 技能校验行情返回），不集中在 AGENTS.md。

### 3.3 Charles 的"验证"语义在 SKILL.md 而非 AGENTS.md

Charles 的验证逻辑分布：

| 验证类型 | Cline 位置 | Charles 位置 | 说明 |
|---------|-----------|-------------|------|
| 开发验证（构建/测试/lint） | AGENTS.md `## Verifying Changes` | 无（开发者自行处理） | Charles 无开发验证命令文档 |
| 运行时输入验证 | 不在 AGENTS.md（在工具实现中） | 各 skill 的 SKILL.md "失败处理"段 | Charles 下沉到技能层 |
| 文档维护验证 | AGENTS.md L86 + `## Documentation Responsibilities` | 无 | Charles 无文档维护约束 |

**Charles 的设计选择**：将验证逻辑放在最需要的地方——技能层。例如 financial-analysis 技能的 SKILL.md 会说明"CSV 缺列时如何报错"，stock-price 技能的 SKILL.md 会说明"行情返回空时如何重试"。这是技能级的运行时验证，非开发验证。

### 3.4 Cline 验证段的上下文说明质量

Cline 的验证段不仅列命令，还提供上下文说明：

1. **为何需要 `build:sdk`**（L60-62）：
   > SDK package exports resolve sibling packages through compiled `dist/` files. If `dist/` is missing, build the SDK packages before running package tests.

2. **工作区根约束**（L13-15）：
   > Run SDK commands from `sdk/`, not from the legacy repository root. Do not run direct root-level commands such as `bun test sdk/...`; they bypass the SDK workspace setup and can fail to resolve `workspace:*` packages correctly.

3. **聚焦测试失败处置**（L84）：
   > If a focused test command fails with a missing `@cline/*` export or missing `dist/` file, build the relevant dependency package or run `bun run build:sdk`, then rerun the same test command. Treat that as a workspace setup issue, not as evidence of a source-code bug.

4. **文档联动约束**（L86）：
   > If you touch hub/bootstrap/session flows, please update `ARCHITECTURE.md`.

这些说明将"做什么命令"提升为"为何做、何时做、失败后如何处置、做完后还要更新什么文档"的完整闭环。Charles AGENTS.md 无此层次的说明。

### 3.5 Cline Documentation Responsibilities 段与验证段的联动

Cline `sdk/AGENTS.md` L103-108 的 `## Documentation Responsibilities` 段定义了 5 个文档的更新触发条件：

| 文档 | 更新触发条件 |
|------|-------------|
| README.md | repo story 或 package inventory 变化 |
| CONTRIBUTING.md | contributor setup 或 release process 变化 |
| AGENTS.md | package boundaries / dependency rules / change routing 变化 |
| ARCHITECTURE.md | system design 或 architectural constraints 变化 |
| DOC.md | exported surfaces / lifecycle semantics / runtime behavior 变化 |

验证段 L86 的"touch hub/bootstrap/session flows → update ARCHITECTURE.md"是此段的实例化。Charles 无此文档维护约束——Charles 的文档主要是 AGENTS.md + general.md + 各 SKILL.md，无 README/CONTRIBUTING/ARCHITECTURE/DOC 的分层。

### 3.6 子包级 AGENTS.md 的验证段缺失分析

Cline `sdk/packages/llms/AGENTS.md`（39 行）无 `## Verifying Changes` 段，仅有 `## Provider Option Routing` 段。

**原因**：验证命令集中在 workspace 根 AGENTS.md（`sdk/AGENTS.md`），子包级 AGENTS.md 只关注包内开发约定（如 provider routing 规则）。开发者验证时从 workspace 根跑 `bun run test` 或 `bun -F @cline/llms test`，无需在子包 AGENTS.md 重复命令清单。

**Charles 不适用**：Charles 是单 agent 应用，无子包概念，AGENTS.md 只有一个（`agent_config/rules/AGENTS.md`），不存在"子包级 AGENTS.md 验证段缺失"问题。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.12 范围内涉及以下文件：
- `agent_config/rules/AGENTS.md`（56 行）
- `agent_config/rules/general.md`
- `agent_config/rules/plan-mode-rules.md`
- `agent_config/rules/research.md`
- `agent_config/rules/trading.md`
- `third_party/cline/sdk/AGENTS.md`（109 行，Cline 源码，非 Charles 代码，不检查 nanobot）
- `third_party/cline/sdk/packages/llms/AGENTS.md`（39 行，Cline 源码，不检查）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent_config/rules/AGENTS.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样（case-insensitive 搜索）。验证方法相关内容为 0（本就无验证段） |
| `agent_config/rules/general.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样 |
| `agent_config/rules/plan-mode-rules.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。L34"可验证的成功标准"是 plan 内容要求，非 nanobot 残留 |
| `agent_config/rules/research.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样 |
| `agent_config/rules/trading.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样 |

**P6.12 范围内 nanobot 残留总计：0 处（注释 0 + 实现逻辑 0）。**

### 4.3 范围外残留说明

以下文件的 nanobot 残留**超出 P6.12 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1（已记录） |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20（已审计） |
| `agent/skills/registry.py` 多处 | 注释 + 实现残留 | docstring + always/when_to_use 字段 | P4.20（已审计） |
| `agent/skills/skill_tool.py` L18 | 注释残留 | "nanobot 子 agent 隔离执行"对比说明 | P4.x |
| `agent/providers/qwen.py` 多处 | 注释残留 | 对标 nanobot openai_compat_provider | P1.x |
| `agent/tools/exec_tool.py` 多处 | 注释残留 | 对标 nanobot ShellTool / shell.py | P3.x |
| `agent/tools/web_tool.py` 多处 | 注释残留 | 对标 nanobot WebSearchTool | P3.x |
| `agent/tools/file_tools.py` 多处 | 注释残留 | 对标 nanobot FilesystemTool | P3.x |
| `agent/skills/__init__.py` | 注释残留 | 待确认 | P4.x |
| `agent/tools/__init__.py` | 注释残留 | 待确认 | P3.x |

**注**：以上范围外残留与 P6.1 报告第四节 4.3 节一致，P6.12 范围（`agent_config/rules/` 目录）无新增残留。

---

## 五、修复建议

### 5.1 高优先级：修正计划文件 P6.12 验证项错位

**问题**：AGENT_COMPARISON_PLAN_V2.md P6.12（L2476-2487）的标题为"AGENTS.md 验证方法"，但列出的 4 个验证项（6.12.1-6.12.4）实际是 AGENTS.md 加载机制的功能验证（frontmatter 生效/主体结构/去重/条件注入），与"AGENTS.md 文档中的验证方法（构建/测试/lint 命令）"无关。这 4 项分别与 P6.1/P6.2/P6.4/P6.6 重复。

**修复建议**：

方案 A（推荐）：将 P6.12 的 4 个验证项重新定义为"AGENTS.md 验证方法对比"，对标 Cline `## Verifying Changes` 段：

| # | 验证项 | 方法 | 预期结果 |
|---|--------|------|---------|
| 6.12.1 | 验证段存在性 | 检查 AGENTS.md 是否含 `## Verifying Changes` 段 | Cline 有，Charles 无 |
| 6.12.2 | 构建命令 | 检查 AGENTS.md 是否含 build 命令 | Cline 有 `bun run build:sdk`，Charles 无 |
| 6.12.3 | 测试命令 | 检查 AGENTS.md 是否含 test 命令 | Cline 有 `bun run test` + 聚焦测试，Charles 无 |
| 6.12.4 | lint/typecheck 命令 | 检查 AGENTS.md 是否含 lint/typecheck 命令 | Cline 有 `bun run check`/`bun run types`，Charles 无 |

方案 B：将 P6.12 的 4 个验证项归入 P6.1/P6.2/P6.4/P6.6 的"验证方法"小节（这些阶段已有验证方法段），删除 P6.12 节。

### 5.2 中优先级：Charles AGENTS.md 是否需要补验证段

**问题**：Charles AGENTS.md 无验证方法段，开发者无统一的构建/测试/lint 命令参考。

**修复建议**：**不建议补**。理由：
1. Charles 是 Python 单 agent 应用，无 SDK 工作区的多包构建复杂性，验证命令简单（`pytest`/`mypy`），无需在 AGENTS.md 集中说明。
2. Charles AGENTS.md 的定位是 LLM 行为规则，加入开发验证命令会混淆受众（LLM vs 开发者）。
3. 若需开发验证命令参考，建议放在独立的 `CONTRIBUTING.md` 或 `DEVELOPMENT.md` 中（Cline 的做法是 AGENTS.md + CONTRIBUTING.md 分工，AGENTS.md 含验证命令是因为 SDK 复杂度高）。

**权衡**：若 Charles 未来演化为多包 Python 项目（如拆分 agent / skills / providers 为独立包），则可考虑在 AGENTS.md 或 CONTRIBUTING.md 中补验证段。当前单 agent 架构下无需补。

### 5.3 低优先级：Charles 文档维护约束缺失

**问题**：Cline AGENTS.md L86 + L103-108 将代码变更与文档更新绑定（touch hub/bootstrap/session → update ARCHITECTURE.md），Charles 无此约束。

**修复建议**：**不建议补**。理由：
1. Charles 的文档主要是 AGENTS.md + general.md + 各 SKILL.md，无 README/CONTRIBUTING/ARCHITECTURE/DOC 的分层，无需文档联动约束。
2. Charles 的 AGENTS.md 由 rules_loader 自动加载，文档维护频率低。
3. 若 Charles 未来引入架构文档（如 ARCHITECTURE.md），可考虑补文档维护约束。当前无需。

### 5.4 低优先级：plan-mode-rules.md 的"可验证的成功标准"

**问题**：`agent_config/rules/plan-mode-rules.md` L34 出现"<可验证的成功标准>"，是 plan 内容要求（plan 须含成功标准），非开发验证命令。与 Cline AGENTS.md 的验证方法无对应关系。

**修复建议**：**无需修改**。这是 Charles plan 模式的业务规则，非开发验证。与本阶段对比无关。

---

## 六、验证方法

### 6.1 Cline 验证段存在性验证

1. 读取 Cline `sdk/AGENTS.md` L51-86，确认含 `## Verifying Changes` 段
2. 确认段内含 6 条 shell 命令：`bun install --frozen-lockfile` / `bun run build:sdk` / `bun run types` / `bun run test` / `bun run check` / `bun -F @cline/<pkg> test`
3. 确认 L84 含失败处置说明，L86 含文档维护约束

### 6.2 Charles 验证段缺失验证

1. 读取 Charles `agent_config/rules/AGENTS.md` 全文 56 行，确认无 `## Verifying Changes` 段
2. Grep `agent_config/rules/AGENTS.md` 搜索 `verify|test|build|lint|check|命令|command`（case-insensitive），确认仅命中 `run_commands` 工具名（非开发验证命令）
3. 读取 `agent_config/rules/` 目录其他文件（general.md / plan-mode-rules.md / research.md / trading.md），确认均无开发验证命令段

### 6.3 Cline 子包 AGENTS.md 验证段缺失验证

1. 读取 Cline `sdk/packages/llms/AGENTS.md` 全文 39 行，确认无 `## Verifying Changes` 段
2. 确认子包级 AGENTS.md 仅含包内开发约定（provider routing），验证命令集中在 workspace 根 AGENTS.md

### 6.4 nanobot 残留验证

1. Grep `agent_config/rules/` 目录搜索 `nanobot`（case-insensitive），确认 0 匹配
2. Grep `agent_config/rules/AGENTS.md` 全文搜索 `nanobot`（case-insensitive），确认 0 匹配

### 6.5 计划文件错位验证

1. 读取 `AGENT_COMPARISON_PLAN_V2.md` L2476-2487，确认 P6.12 标题为"AGENTS.md 验证方法"
2. 确认 6.12.1-6.12.4 的验证项（frontmatter 生效/主体结构/去重/条件注入）与"验证方法（构建/测试/lint 命令）"无关
3. 确认这 4 项分别与 P6.1/P6.2/P6.4/P6.6 重复

---

## 七、附录

### 7.1 Cline sdk/AGENTS.md 验证段全文（L51-86）

```markdown
## Verifying Changes

Before testing in a fresh worktree, install SDK dependencies from the SDK workspace root:

```sh
cd sdk
bun install --frozen-lockfile
```

SDK package exports resolve sibling packages through compiled `dist/` files. If `dist/` is missing, build the SDK packages before running package tests:

```sh
bun run build:sdk
```

SDK-root commands for cross-package confidence:

```sh
bun run types       # typecheck all packages
bun run test        # run all tests
bun run check       # lint + build + typecheck + check-publish
```

For focused verification, prefer workspace package scripts from the SDK root:

```sh
bun -F @cline/shared test
bun -F @cline/llms test
bun -F @cline/agents test
bun -F @cline/core test:unit
bun -F @cline/cli test:unit
```

If a focused test command fails with a missing `@cline/*` export or missing `dist/` file, build the relevant dependency package or run `bun run build:sdk`, then rerun the same test command. Treat that as a workspace setup issue, not as evidence of a source-code bug.

If you touch hub/bootstrap/session flows, please update `ARCHITECTURE.md`.
```

### 7.2 Charles agent_config/rules/AGENTS.md 验证段实际内容

```
（无验证段）
```

Charles AGENTS.md 全文 56 行无任何 `## Verifying Changes` 或等价段落。Grep `verify|test|build|lint|check` 仅命中 `run_commands` 工具名（L10/L25/L28/L29/L35/L54），均为 LLM 工具调用说明，非开发验证命令。

### 7.3 Cline 验证命令分层架构图

```
Cline sdk/AGENTS.md 验证命令分层
┌─────────────────────────────────────────────────┐
│ 第 1 层：环境准备                                │
│  - bun install --frozen-lockfile  (依赖安装)    │
│  - bun run build:sdk              (dist 构建)   │
├─────────────────────────────────────────────────┤
│ 第 2 层：全量验证（SDK 根执行）                  │
│  - bun run types    (typecheck)                 │
│  - bun run test     (全量测试)                  │
│  - bun run check    (lint+build+typecheck+publish) │
├─────────────────────────────────────────────────┤
│ 第 3 层：聚焦验证（按包执行）                    │
│  - bun -F @cline/shared test                    │
│  - bun -F @cline/llms test                      │
│  - bun -F @cline/agents test                    │
│  - bun -F @cline/core test:unit                 │
│  - bun -F @cline/cli test:unit                  │
└─────────────────────────────────────────────────┘
        │
        ↓ 失败处置
┌─────────────────────────────────────────────────┐
│ 聚焦测试失败 → build 依赖包 → 重跑              │
│ (视为 workspace 设置问题，非源码 bug)           │
└─────────────────────────────────────────────────┘
        │
        ↓ 文档联动
┌─────────────────────────────────────────────────┐
│ touch hub/bootstrap/session → update ARCHITECTURE.md │
└─────────────────────────────────────────────────┘


Charles agent_config/rules/AGENTS.md 验证命令分层
┌─────────────────────────────────────────────────┐
│ （无验证段）                                    │
└─────────────────────────────────────────────────┘
```

### 7.4 双方验证方法定位对比

```
Cline 验证方法定位:
  AGENTS.md (开发者参考)
    └── ## Verifying Changes (L51-86, 6 条命令)
    └── ## Documentation Responsibilities (L103-108, 文档联动)
  子包 AGENTS.md (包内约定)
    └── 无验证段 (验证命令集中在 workspace 根)

Charles 验证方法定位:
  AGENTS.md (LLM 行为规则)
    └── 无验证段
  general.md (通用规则)
    └── 无验证段
  SKILL.md (技能级运行时验证)
    └── 各技能的"失败处理"段 (运行时输入校验，非开发验证)

Cline: 开发验证集中化 (AGENTS.md)
Charles: 运行时验证下沉化 (SKILL.md)
```
