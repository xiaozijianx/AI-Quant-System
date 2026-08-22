# Phase 6.3 AGENTS.md 决策树对比

> 对比范围：Cline 默认 system prompt（`DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT`）+ Cline 各 `AGENTS.md`（`sdk/AGENTS.md`、`sdk/packages/llms/AGENTS.md`）+ Cline 技能内嵌决策树（`.agents/skills/cline-sdk/SKILL.md`、`.agents/skills/opentui/SKILL.md`）与 Charles `agent_config/rules/AGENTS.md`（L19-55 决策树 + 工具选择原则 + 硬约束）+ `agent/context.py::_build_tools_section`（L748-785 动态注入决策树段）逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-36（`DEFAULT_CLINE_SYSTEM_PROMPT`：含并行调用指引 L22-23，**无工具 vs 技能决策树**，无 skills 工具优先级说明）
> - `sdk/packages/shared/src/prompt/system.ts` L38-67（`YOLO_CLINE_SYSTEM_PROMPT`：同样含并行调用指引 L48-49，**无决策树**）
> - `sdk/packages/shared/src/prompt/cline.ts` L145-151（`effectiveRules = [rules, MODE_TAG, PLAN_MODE].filter(Boolean).join("\n\n")`：rules 槽注入用户规则，但默认 prompt 本身不含决策树）
> - `sdk/AGENTS.md` L1-109（SDK 工作区开发参考：包边界 / 依赖方向 / 变更路由 / 验证命令，**无工具选择决策树**）
> - `sdk/packages/llms/AGENTS.md` L1-39（`@cline/llms` 包开发指引：Provider Option Routing，**无工具选择决策树**）
> - `.agents/skills/cline-sdk/SKILL.md` L67-120（技能内嵌 "Quick Decision Trees"：仅用于"选哪个 API 表面 / 创建工具 / 处理事件 / 配置 provider"，**非工具 vs 技能决策**）
> - `.agents/skills/opentui/SKILL.md` L64-100（技能内嵌 "Quick Decision Trees"：仅用于"选哪个 framework / 显示内容 / 用户输入"，**非工具 vs 技能决策**）
> - `third_party/charles_bundle/nanobot-main/nanobot/templates/AGENTS.md` L1-21（nanobot 模板：含 `cron` / `HEARTBEAT.md` 调度任务说明，**与 Charles 当前 AGENTS.md 无任何文本继承关系**）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md` L19-39（**"工具 vs 技能 决策树（最重要）" 段**：4 分支决策 + 3 条禁止行为，Stage P1.3 新增）
> - `agent_config/rules/AGENTS.md` L40-48（**"工具选择原则（按数据类型）" 段**：6 条数据类型 → 技能/工具映射）
> - `agent_config/rules/AGENTS.md` L49-55（**"硬约束（投研场景特有）" 段**：4 条投研场景禁止行为）
> - `agent/context.py` L748-785（`_build_tools_section` 动态注入"工具 vs 技能 决策树（重要）"段，Stage P1.2 新增，与 AGENTS.md 决策树内容等价）
> - `AGENT_PROMPT_FIX_PLAN.md` L74-90（P1.2 + P1.3 计划：AGENTS.md 与 context.py 双处放置决策树以确保 LLM 一定看到）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 AGENTS.md / 默认 prompt 中的"决策树"实现。**核心结论：Charles 在 Stage P1.3 在 AGENTS.md 中显式新增"工具 vs 技能 决策树"段，并在 Stage P1.2 在 context.py 动态拼接层注入等价决策树，两处内容对齐以确保 LLM 在常驻规则与动态 tools 段任一处都能看到；Cline 默认 prompt 仅有并行调用指引（system.ts L22-23 / L48-49），不提供"工具 vs 技能"选择决策树，工具选择完全依赖 tool description 与用户提供的 rules**；剩余差异主要是 Charles 决策树量化特化（股票代码路由、本地数据 vs web_search 优先级）。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.3（L2302-2319）的对比表存在 **1 处事实不准 + 1 处描述不完整**，需逐项修正：

1. **6.3.3 标注"tools vs skills 优先级 — Cline: 默认 prompt / Charles: 决策树段 / Charles 显式"** — **描述不准**：Cline 默认 prompt（system.ts L1-36）**完全不提及 `skills` 工具**，更无 tools vs skills 优先级指引。默认 prompt 仅含"call multiple tools in a single response"的并行调用指引（L22-23），针对的是 `read_files` / `run_commands` / `search_codebase` / `editor` 等内置工具的并行调度，**与 skills 工具选择无关**。Cline 的 skills 工具仅作为普通工具注册，LLM 是否调用完全依赖 tool description。计划表"Cline: 默认 prompt"容易误读为"默认 prompt 含 skills 优先级指引"，应修正为"Cline: 无（依赖 tool description）"。

2. **6.3.2 标注"工具选择指引 — Cline: 默认 prompt / Charles: 决策树段 / 形式不同"** — **描述不完整**：Cline 默认 prompt 的"工具选择指引"仅是**并行调度策略**（"identify every independent read, search, command, or edit ... emit all of those tool calls now"），**不涉及选哪个工具**。Charles 决策树是**工具路由决策**（任务匹配技能 → skills 工具；通用文件操作 → read_files；命令执行 → run_commands；联网搜索 → web_search）。两者解决的是不同维度的问题：Cline 解决"何时并行"，Charles 解决"选哪个工具"。计划表"形式不同"掩盖了这一本质差异。

3. **6.3.1 标注"决策树存在 — Cline: 无 / Charles: 是 / Charles 额外（Stage P1.3）"** — **正确**：Cline 各 AGENTS.md 文件（`sdk/AGENTS.md`、`sdk/packages/llms/AGENTS.md`）均无工具选择决策树；Cline 技能内嵌的 "Quick Decision Trees"（`.agents/skills/cline-sdk/SKILL.md` L67-120、`.agents/skills/opentui/SKILL.md` L64-100）是**技能内部路由决策**（选哪个 API 表面 / 选哪个 framework），**非 AGENTS.md 决策树**，与 Charles AGENTS.md 决策树无可比性。

4. **6.3.4 标注"股票代码路由 — Cline: 无 / Charles: 是 / Charles 量化特化"** — **正确**：Charles 决策树第 1 分支（任务匹配技能 → skills）+ 第 4 分支（web_search 禁止查本地已有股价/财报）+ "工具选择原则"第 1/4 条（结构化财务数字 → financial-analysis；股价/K线 → stock-price）共同构成股票代码路由。Cline 无任何量化场景路由。

### 核心结论

1. **Cline 默认 prompt 无决策树**（事实）：`DEFAULT_CLINE_SYSTEM_PROMPT`（system.ts L1-36）与 `YOLO_CLINE_SYSTEM_PROMPT`（L38-67）均不含"工具 vs 技能"决策树，仅含并行调用指引（L22-23 / L48-49）。skills 工具的选择完全依赖 tool description。

2. **Cline AGENTS.md 无决策树**（事实）：`sdk/AGENTS.md`（L1-109）是 SDK 工作区开发参考（包边界 / 依赖方向 / 变更路由 / 验证命令）；`sdk/packages/llms/AGENTS.md`（L1-39）是 `@cline/llms` 包开发指引（Provider Option Routing）。两者均无工具选择决策树。

3. **Cline 技能内嵌决策树不可比**（澄清）：`.agents/skills/cline-sdk/SKILL.md` L67-120 与 `.agents/skills/opentui/SKILL.md` L64-100 含 "Quick Decision Trees"，但是**技能内部路由**（选哪个 API 表面 / 选哪个 framework），出现在 SKILL.md 而非 AGENTS.md，且在 LLM 调用 skills 工具加载该技能后才可见，**不用于工具 vs 技能的初始选择**。

4. **Charles AGENTS.md 决策树是 P1.3 新增**（事实）：`agent_config/rules/AGENTS.md` L19-39 "工具 vs 技能 决策树（最重要）" 段含 4 分支决策（技能匹配 / 通用文件操作 / 临时命令 / 联网搜索）+ 3 条禁止行为（禁止绕过 skills 调脚本 / 禁止技能名当工具名 / 禁止假定脚本参数格式）。

5. **Charles 决策树双处放置是故意设计**（事实）：AGENTS.md（L19-39，常驻规则）+ context.py（L756-772，动态注入 tools 段）两处决策树内容等价，按 `AGENT_PROMPT_FIX_PLAN.md` L80-84 说明："AGENTS.md 是常驻规则，context.py 是动态拼接，两处都改确保 LLM 一定看到"。两处文本几乎逐字一致，差异仅为标题后缀（"（最重要）" vs "（重要）"）与少量措辞。

6. **Charles 决策树含量化特化路由**（事实）：决策树第 4 分支明确"股价/财报等本地已有数据禁止 web_search"；"工具选择原则"段（L40-48）按数据类型路由（结构化财务数字 → financial-analysis；年报叙述 → read-pdf；股价/K线 → stock-price），属投研场景特化。

7. **nanobot 残留**：`agent_config/rules/AGENTS.md` **0 处残留**（全文 55 行无 nanobot 字样）；`agent/context.py` 决策树段（L748-785）**0 处残留**。Charles 项目内 nanobot 字样仅出现在 `AGENT_MIGRATION_PLAN.md`（历史迁移计划文档，非 AGENTS.md 残留）。`third_party/charles_bundle/nanobot-main/nanobot/templates/AGENTS.md` 是 nanobot 原始模板（含 `cron` / `HEARTBEAT.md` 调度任务说明），与 Charles 当前 `agent_config/rules/AGENTS.md` **无任何文本继承关系**——Charles AGENTS.md 全文重写为投研情报官规则，未保留 nanobot 模板的任何段落。

### 一致性总体评估

- **决策树存在性**：**Charles 独有**。Cline 默认 prompt 与各 AGENTS.md 均无工具选择决策树；Charles 在 AGENTS.md + context.py 双处显式放置。
- **工具选择指引**：**形式不同（不可直接对标）**。Cline 默认 prompt 提供并行调度指引（何时并行）；Charles 决策树提供工具路由决策（选哪个工具）。两者解决不同维度问题。
- **tools vs skills 优先级**：**Charles 独有**。Cline 默认 prompt 不提及 skills 工具；Charles 决策树第 1 分支明确"任务匹配技能 → 先调 skills 工具"。
- **量化场景路由**：**Charles 独有**。Cline 无任何量化场景路由；Charles 决策树 + 工具选择原则 + 硬约束三层共同构成股票代码/财报/年报路由。
- **nanobot 残留**：**0 处**。AGENTS.md 与 context.py 决策树段均无 nanobot 注释残留、无 nanobot 实现逻辑残留。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.3.1 | 决策树存在 | **无**：默认 prompt（system.ts L1-36）无决策树；`sdk/AGENTS.md`（L1-109）是包边界/路由指引；`sdk/packages/llms/AGENTS.md`（L1-39）是 Provider Routing 指引；均无工具选择决策树 | **是**：`agent_config/rules/AGENTS.md` L19-39 "工具 vs 技能 决策树（最重要）" 段（Stage P1.3 新增） | Charles 独有 | 计划表标注"Charles 额外（Stage P1.3）"**正确**。Cline 技能内嵌 "Quick Decision Trees"（cline-sdk/SKILL.md L67-120、opentui/SKILL.md L64-100）是技能内部路由，非 AGENTS.md 决策树，不可比 |
| 6.3.2 | 工具选择指引 | 默认 prompt（system.ts L22-23）：`"You can call multiple tools in a single response. Before using tools, identify every independent read, search, command, or edit needed for the next step and emit all of those tool calls now"` + "Good parallelism examples"（read_files / run_commands / search_codebase / editor 并行示例）。**仅并行调度策略，不涉及选哪个工具** | 决策树段（AGENTS.md L19-39）：4 分支决策（技能匹配 → skills；通用文件 → read_files；命令 → run_commands；联网 → web_search）+ "工具选择原则（按数据类型）"段（L40-48）：6 条数据类型 → 工具映射 | 形式不同（不可直接对标） | 计划表标注"形式不同"**不完整**。两者解决不同维度问题：Cline 解决"何时并行"，Charles 解决"选哪个工具"。Cline 默认 prompt 不含工具路由决策 |
| 6.3.3 | tools vs skills 优先级 | **无**：默认 prompt（system.ts L1-36）**完全不提及 `skills` 工具**，更无 tools vs skills 优先级指引。skills 工具仅作为普通工具注册，LLM 是否调用完全依赖 tool description | 决策树段第 1 分支（AGENTS.md L23-25）：`"任务匹配某个技能（财务分析/RAG读年报/K线行情/写研报/...）? → 是: 先调用 skills(skill=\"...\") 加载该技能 SKILL.md 指令"` + 3 条禁止行为（L34-38）：禁止绕过 skills 调脚本 / 禁止技能名当工具名 / 禁止假定脚本参数格式 | Charles 独有 | 计划表标注"Cline: 默认 prompt"**描述不准**。Cline 默认 prompt 不提及 skills 工具，应修正为"Cline: 无（依赖 tool description）"。Charles 决策树显式声明 skills 优先级 + 禁止绕过 skills 的 3 类反模式 |
| 6.3.4 | 股票代码路由 | **无**：Cline 无任何量化场景路由 | 决策树第 4 分支（AGENTS.md L30-31）：`"任务需要联网搜索新闻/公告? → 是: 直接调用 web_search 工具（但股价/财报等本地已有数据禁止 web_search）"` + "工具选择原则"第 1 条（L42）：`"结构化财务数字 → financial-analysis 技能（CSV 数据）"` + 第 4 条（L45）：`"股价/K线数据 → stock-price 技能（MiniQMT 实时行情）"` + "硬约束"第 1 条（L51）：`"禁止用 web_search 查本地已有数据的股价、财报"` | Charles 独有（量化特化） | 计划表标注"Charles 量化特化"**正确**。Charles 决策树 + 工具选择原则 + 硬约束三层共同构成股票代码/财报/年报路由 |
| 6.3.5 | 决策树放置位置 | N/A（无决策树） | **双处放置**：(1) `agent_config/rules/AGENTS.md` L19-39（常驻规则，Stage P1.3）(2) `agent/context.py` L756-772（动态注入 tools 段，Stage P1.2）。两处内容等价，差异仅为标题后缀（"（最重要）" vs "（重要）"）与少量措辞 | Charles 独有 | 按 `AGENT_PROMPT_FIX_PLAN.md` L80-84：双处放置是故意设计，"AGENTS.md 是常驻规则，context.py 是动态拼接，两处都改确保 LLM 一定看到" |
| 6.3.6 | 决策树分支数 | N/A | **4 分支**：(1) 技能匹配 → skills (2) 通用文件操作 → read_files/search_codebase/editor (3) 临时命令 → run_commands (4) 联网搜索 → web_search | Charles 独有 | 4 分支覆盖 Charles 全部工具类别。AGENTS.md 版（L23-31）与 context.py 版（L758-766）分支数一致 |
| 6.3.7 | 禁止行为条数 | N/A | **3 条**：(1) 禁止绕过 skills 直接 run_commands 调技能脚本 (2) 禁止技能名当工具名调用 (3) 禁止在 skills 返回指令前假定脚本参数格式 | Charles 独有 | AGENTS.md 版（L34-38）与 context.py 版（L768-772）禁止行为一致。3 条均针对 skills 工具的反模式 |
| 6.3.8 | 并行调用指引 | 默认 prompt（system.ts L22-23 + L48-49）：`"call multiple tools in a single response"` + "Good parallelism examples"（read_files / run_commands / search_codebase / editor 并行） | context.py L751-752（动态注入 tools 段）：`"一次回复中可调用多个独立工具（并行），如多个 read_files / search_codebase"` + `"依赖的工具调用需分多轮（如先 read_files 再 editor）"` | 高 | 两者均提供并行调用指引。Cline 在默认 prompt；Charles 在动态 tools 段。语义对齐：均强调"独立调用并行，依赖调用分轮" |
| 6.3.9 | nanobot 残留（AGENTS.md） | N/A | `agent_config/rules/AGENTS.md` 全文 55 行：**0 处 nanobot 字样**（注释残留 0 + 实现逻辑残留 0） | 高（无残留） | Charles AGENTS.md 全文重写为投研情报官规则，未保留 nanobot 模板（`third_party/charles_bundle/nanobot-main/nanobot/templates/AGENTS.md`）的任何段落 |
| 6.3.10 | nanobot 残留（context.py 决策树段） | N/A | `agent/context.py` L748-785（决策树段）：**0 处 nanobot 字样**（注释残留 0 + 实现逻辑残留 0） | 高（无残留） | context.py 动态注入的决策树段为 Charles 原创实现（Stage P1.2），无 nanobot 残留 |

---

## 三、重点差距详细说明

### 3.1 Cline 默认 prompt 仅含并行调度，不含工具路由

Cline `DEFAULT_CLINE_SYSTEM_PROMPT`（system.ts L1-36）中与"工具选择"相关的仅有 L22-23：

```
- You can call multiple tools in a single response. Before using tools, identify every independent read, search, command, or edit needed for the next step and emit all of those tool calls now, either as multiple tool calls or as one batched input for tools that accept arrays. Do not wait for one independent result before requesting another. Do not split independent reads, searches, checks, or edits across separate turns.
- Good parallelism examples: read all known relevant files in one read_files call; run independent inspection commands in one run_commands call; emit independent read_files, search_codebase, and run_commands calls together in one response; emit multiple editor calls together when editing different files or non-overlapping regions.
```

该指引解决的是"**已知要用哪些工具后，何时并行发射**"，**不解决"该用哪个工具"**。Cline 的工具选择完全依赖：

1. **tool description**：每个工具注册时提供的 `description` 字段（LLM 基于 description 自行判断）
2. **用户提供的 rules**：用户在 `.clinerules/` 或 `AGENTS.md` 中自行编写决策树（Cline 不强制提供模板）
3. **技能内嵌决策树**：技能加载后，SKILL.md 内的 "Quick Decision Trees" 指导技能内部路由（如选哪个 API 表面）

Cline 本身在默认 prompt 与各 AGENTS.md 中**均不提供"工具 vs 技能"决策树**。这是 Cline 的设计哲学：保持核心 prompt 通用，把场景特化决策交给用户/技能。

### 3.2 Charles 决策树是投研场景特化的显式约束

Charles `agent_config/rules/AGENTS.md` L19-39 的"工具 vs 技能 决策树（最重要）"段是 Stage P1.3 新增（见 `AGENT_PROMPT_FIX_PLAN.md` L80-84），目的是解决 LLM 在投研场景下的工具误用问题：

- **问题 1**：LLM 直接 `run_commands` 调用 `agent_config/skills/stock-price/scripts/get_kline.py`，绕过 skills 工具加载流程 → 决策树第 1 分支 + 禁止行为第 1 条
- **问题 2**：LLM 把技能名当工具名调用（如 `stock_price(...)`）→ 禁止行为第 2 条
- **问题 3**：LLM 在 skills 工具返回 SKILL.md 指令前就假定知道脚本参数格式 → 禁止行为第 3 条
- **问题 4**：LLM 用 web_search 查本地已有的股价/财报数据 → 决策树第 4 分支 + 硬约束第 1 条

这些问题是投研场景特化的，Cline 通用 prompt 不可能覆盖。Charles 的决策树是对 Cline 默认 prompt 的**场景特化补充**，而非"对齐 Cline"。

### 3.3 Charles 决策树双处放置的故意性

Charles 在两处放置等价决策树：

| 位置 | 文件 | 行号 | Stage | 角色 |
|------|------|------|-------|------|
| 常驻规则 | `agent_config/rules/AGENTS.md` | L19-39 | P1.3 | 作为 rules 文件加载，注入 `{{CHARLES_RULES}}` 槽 |
| 动态 tools 段 | `agent/context.py::_build_tools_section` | L756-772 | P1.2 | 动态拼接到 tools 段，紧随工具列表之后 |

按 `AGENT_PROMPT_FIX_PLAN.md` L80-84 的设计说明：

> P1.3 在 AGENTS.md 强化"工具选择原则"
> 修改方案：把"工具选择原则"段重组为"工具 vs 技能 决策树"，与 P1.2 呼应（AGENTS.md 是常驻规则，context.py 是动态拼接，两处都改确保 LLM 一定看到）。保留所有现有约束。

两处决策树内容几乎逐字一致，差异仅为：

- 标题后缀：AGENTS.md 用"（最重要）"，context.py 用"（重要）"
- context.py 版本在决策树后还有"任务拆解（强制）"段（L774-778）和"输出内容 ≠ 完成任务"段（L780-785），这些是动态 tools 段的额外内容，不在 AGENTS.md 中

双处放置的目的：AGENTS.md 作为 rules 加载时位于 `{{CHARLES_RULES}}` 槽（prompt 末尾），context.py 动态注入时位于 tools 段（prompt 中部），两处位置不同，确保 LLM 无论注意力分布在哪一段都能看到决策树。

### 3.4 Cline 技能内嵌决策树不可与 AGENTS.md 决策树对标

Cline 在 `.agents/skills/cline-sdk/SKILL.md` L67-120 与 `.agents/skills/opentui/SKILL.md` L64-100 含 "Quick Decision Trees" 段，但与 Charles AGENTS.md 决策树**无可比性**：

| 维度 | Cline 技能内嵌决策树 | Charles AGENTS.md 决策树 |
|------|---------------------|-------------------------|
| 出现位置 | SKILL.md（技能文件） | AGENTS.md（常驻规则） |
| 可见时机 | LLM 调用 skills 工具加载该技能后 | LLM 接收到 system prompt 即可见 |
| 决策对象 | 技能内部路由（选哪个 API 表面 / 选哪个 framework） | 工具 vs 技能的初始选择 |
| 决策树示例 | "Which API surface should I use?" → agent/ vs clinecore/ | "任务匹配某个技能?" → skills 工具 vs 直接 read_files |
| 通用性 | 技能特化（每个技能自定义） | 跨技能通用（适用于所有技能） |

Cline 技能内嵌决策树是"技能加载后的二级路由"，Charles AGENTS.md 决策树是"技能加载前的一级路由"。两者层级不同，不构成对标关系。

---

## 四、nanobot 残留专项检查

### 4.1 AGENTS.md 残留检查

**检查文件**：`agent_config/rules/AGENTS.md`（全文 55 行）

**检查方法**：`grep -i "nanobot" agent_config/rules/AGENTS.md`

**检查结果**：**0 处残留**（注释残留 0 + 实现逻辑残留 0）。

**残留分析**：Charles AGENTS.md 全文为投研情报官规则（"你是 Charles，专业 AI 投研情报官"），未保留 nanobot 模板（`third_party/charles_bundle/nanobot-main/nanobot/templates/AGENTS.md`）的任何段落。nanobot 模板含 `cron` 工具调度、`HEARTBEAT.md` 心跳任务等说明，Charles AGENTS.md 完全无这些内容，属全文重写。

### 4.2 context.py 决策树段残留检查

**检查文件**：`agent/context.py` L748-785（`_build_tools_section` 动态注入决策树段）

**检查方法**：`grep -i "nanobot" agent/context.py`（在决策树段范围内）

**检查结果**：**0 处残留**（注释残留 0 + 实现逻辑残留 0）。

**残留分析**：context.py 决策树段为 Charles 原创实现（Stage P1.2），4 分支决策 + 3 条禁止行为均针对 Charles 自有的 skills / read_files / run_commands / web_search 工具，无 nanobot 工具引用（nanobot 的 `exec` / `edit_file` / `write_file` 等工具名均未出现）。

### 4.3 Charles 项目内 nanobot 字样分布

**检查方法**：`grep -ri "nanobot" --include="!third_party/**" CASE-AI量化系统/`

**检查结果**：Charles 项目内（排除 `third_party/`）nanobot 字样仅出现在 `AGENT_MIGRATION_PLAN.md`（历史迁移计划文档），属正常的历史文档引用，非 AGENTS.md 或 context.py 残留。

**结论**：AGENTS.md 决策树对比范围内 **nanobot 残留 = 0**（注释残留 0 + 实现逻辑残留 0）。

---

## 五、与计划表的对齐情况

| 计划表条目 | 计划表描述 | 实际验证结果 | 对齐状态 |
|-----------|-----------|-------------|---------|
| 6.3.1 | 决策树存在：Cline 无 / Charles 是 / Charles 额外（Stage P1.3） | Cline 默认 prompt + 各 AGENTS.md 均无决策树；Charles AGENTS.md L19-39 有决策树（Stage P1.3 新增） | **对齐** |
| 6.3.2 | 工具选择指引：Cline 默认 prompt / Charles 决策树段 / 形式不同 | Cline 默认 prompt 仅含并行调度指引（system.ts L22-23），不含工具路由；Charles 决策树段含 4 分支工具路由 | **部分对齐**（"形式不同"掩盖了本质差异：Cline 解决并行，Charles 解决路由） |
| 6.3.3 | tools vs skills 优先级：Cline 默认 prompt / Charles 决策树段 / Charles 显式 | Cline 默认 prompt **完全不提及 skills 工具**；Charles 决策树第 1 分支 + 3 条禁止行为显式声明 skills 优先级 | **描述不准**（Cline 应为"无"，非"默认 prompt"） |
| 6.3.4 | 股票代码路由：Cline 无 / Charles 是 / Charles 量化特化 | Cline 无量化路由；Charles 决策树 + 工具选择原则 + 硬约束三层共同构成股票代码路由 | **对齐** |

---

## 六、结论

1. **Charles AGENTS.md 决策树是 Stage P1.3 新增的投研场景特化补充**，与 Cline 无对标关系（Cline 默认 prompt 与各 AGENTS.md 均无工具选择决策树）。
2. **Charles 决策树双处放置（AGENTS.md + context.py）是故意设计**，确保 LLM 在 prompt 不同位置都能看到决策树。
3. **Cline 默认 prompt 的"工具选择指引"仅是并行调度策略**（何时并行），**不涉及选哪个工具**；Charles 决策树是工具路由决策（选哪个工具）。两者解决不同维度问题，计划表"形式不同"的描述掩盖了这一本质差异。
4. **计划表 6.3.3 描述不准**：Cline 默认 prompt 完全不提及 skills 工具，应修正为"Cline: 无（依赖 tool description）"，而非"Cline: 默认 prompt"。
5. **nanobot 残留 = 0**：AGENTS.md 与 context.py 决策树段均无 nanobot 注释残留、无 nanobot 实现逻辑残留。Charles AGENTS.md 全文重写，未保留 nanobot 模板的任何段落。
6. **Cline 技能内嵌 "Quick Decision Trees"**（cline-sdk/SKILL.md、opentui/SKILL.md）是技能内部路由，出现在 SKILL.md 而非 AGENTS.md，且在技能加载后才可见，与 Charles AGENTS.md 决策树层级不同，不构成对标关系。
