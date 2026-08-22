# Phase 5.3 Base Prompt 对比报告（DEFAULT_CLINE_SYSTEM_PROMPT）

## 1. 执行摘要

本报告对 CASE-AI 量化系统（Charles）与 Cline 的 base prompt（系统提示模板字符串常量）进行逐项对比，覆盖模板文件结构、DEFAULT/YOLO 双模板设计、身份声明、角色定义、行为约束、`submit_and_exit` 约束、语言、内容长度与措辞，并对 base prompt 相关代码做 nanobot 风格残留专项检查。

**核心发现**：

1. **双模板设计已对齐**：Charles 已实现 `DEFAULT_CHARLES_SYSTEM_PROMPT` 与 `YOLO_CHARLES_SYSTEM_PROMPT` 双模板，并通过 `select_base_template(mode)` 在 `agent/context.py` L185-205 按 mode 路由，结构与 Cline `cline.ts` 完全对齐。**计划文件 P5.3 中标记的 5.3.2 / 5.3.6 / 5.3.7 三项 L8 差距已修复**（Charles YOLO 模板已存在，身份为"后台自主运行"，`submit_and_exit` 描述为"必须"而非"可选"）。

2. **内容长度差距显著（L2 差距）**：Cline DEFAULT 模板 3695 字符 / 36 行，Charles DEFAULT 模板仅 828 字符 / 27 行（约为 Cline 的 22%）。Cline YOLO 模板 2847 字符 / 31 行，Charles YOLO 模板 809 字符 / 29 行（约为 Cline 的 28%）。Charles 模板整体远比 Cline 精简，缺失大量"Remember"清单、"REMEMBER/IMPORTANT"强调段、并行调用示例、规划过程展示要求、完成总结要求等行为约束。

3. **语言差距（L1 差距）**：Cline 模板为英文，Charles 模板为中文。这是设计层面的本地化决策，不影响功能对齐，但会让 LLM 在 system prompt 层面接收到的指令语言不同。

4. **身份/角色定义差距（L2 差距）**：
   - Cline 身份："You are Cline, an AI coding agent"（通用编码 agent）
   - Charles 身份："你是 Charles，专业的 AI 投研情报官"（领域特化投研 agent）
   Charles 的身份绑定了"Python 核心 / 中文量化投研工作流 / 数据分析 / 研报撰写 / 金融数据查询"等领域语义，Cline 为通用编码 agent。这是产品定位差异，非缺陷。

5. **nanobot 残留**：base prompt 模板文件 `agent/prompts/charles_system_prompt.py` **无任何 nanobot 残留**（注释和实现均干净）。但在 base prompt 的**消费方** `agent/context.py` 中存在 1 处注释残留 + 1 处实现逻辑残留（`extra_sections` 参数，标记为"已废弃的 nanobot 风格段落"，但代码仍消费）。

6. **占位符对齐**：两方均采用 `{{PLATFORM_NAME}} / {{CURRENT_DATE}} / {{IDE_NAME}} / {{CWD}} / {{*_RULES}} / {{*_METADATA}}` 六个占位符，命名与位置对齐。

**整体结论**：base prompt 的**架构层面**（双模板 + 占位符 + 路由）已对齐 Cline；但**内容层面**存在显著差距（L2），Charles 模板过于精简，缺失 Cline 中大量行为约束与并行调用指导，可能影响 LLM 的实际行为质量。nanobot 残留集中在 context.py 的 `extra_sections` 兼容层，属低风险历史残留。

---

## 2. 检查范围与方法

### 2.1 检查范围

**Cline 源文件**：
- `third_party/cline/sdk/packages/shared/src/prompt/system.ts`（68 行）— `DEFAULT_CLINE_SYSTEM_PROMPT` 与 `YOLO_CLINE_SYSTEM_PROMPT` 模板定义
- `third_party/cline/sdk/packages/shared/src/prompt/cline.ts`（部分）— `MODE_TAG_INSTRUCTIONS` / `PLAN_MODE_INSTRUCTIONS` 等 rule 注入说明（用于理解 base prompt 与 rules 的边界）

**Charles 源文件**：
- `agent/prompts/charles_system_prompt.py`（94 行）— `DEFAULT_CHARLES_SYSTEM_PROMPT` 与 `YOLO_CHARLES_SYSTEM_PROMPT` 模板定义
- `agent/context.py`（base prompt 消费方）— `select_base_template()` L185-205、`SystemPromptBuilder` 类 L214+、`extra_sections` 兼容层 L255 / L275 / L292 / L530-537

**计划文件**：
- `AGENT_COMPARISON_PLAN_V2.md` L1810-1833（P5.3 章节）

### 2.2 检查方法

1. **逐行人工审阅**：完整读取 Cline `system.ts` 与 Charles `charles_system_prompt.py`，逐段比对身份声明、行为规则、`<env>` 段、占位符位置、YOLO 模板的 `submit_and_exit` 约束。
2. **精确长度计量**：用 Python 脚本（UTF-8 解码 + 正则提取模板字面量）统计两方四个模板的行数、字符数、去空白字符数。
3. **消费方追踪**：Grep `DEFAULT_CHARLES_SYSTEM_PROMPT` / `YOLO_CHARLES_SYSTEM_PROMPT` / `select_base_template` 在 `agent/context.py` 中的调用点，验证模板实际被消费。
4. **nanobot 残留检索**：Grep `nanobot`（不区分大小写）在 `charles_system_prompt.py` 与 `context.py` 中的命中，并区分注释残留 vs 实现逻辑残留。
5. **计划差距项复核**：对计划 P5.3 表格的 8 项（5.3.1-5.3.8）逐项验证当前代码状态，标注计划中已过时的差距项。

---

## 3. 计划差距项逐项复核

计划文件 L1821-1830 给出的 8 项对比表，基于历史代码状态。本次复核发现其中 3 项已修复，下表给出**当前代码状态**：

| # | 对比项 | Cline 位置 | Charles 位置 | 计划原判定 | 当前状态 | 复核结论 |
|---|--------|-----------|-------------|-----------|---------|---------|
| 5.3.1 | Base prompt 模板 | system.ts L1-36 | charles_system_prompt.py L31-58 | 已对齐 | 已对齐 | **确认**。两方均为单一模板字符串常量，结构一致。 |
| 5.3.2 | yolo 独立模板 | system.ts L38-68 | 无 | L8 差距 | **已修复** | Charles 已新增 `YOLO_CHARLES_SYSTEM_PROMPT`（L62-91），并通过 `select_base_template()` 路由。计划原判定**已过时**。 |
| 5.3.3 | 身份声明 | system.ts L1 | charles_system_prompt.py L31 | 已对齐 | L2 差距 | **修正为 L2**。两方均有身份声明，但内容差距显著：Cline 为"AI coding agent"（通用），Charles 为"AI 投研情报官"（领域特化）。详见 §4.1。 |
| 5.3.4 | 角色定义 | system.ts L1 | charles_system_prompt.py L31 | 已对齐 | L2 差距 | **修正为 L2**。角色定义均存在，但 Charles 绑定"Python 核心 / 中文量化投研工作流"领域语义。 |
| 5.3.5 | 行为约束 | system.ts L3-34 | charles_system_prompt.py L33-47 | 已对齐 | L2 差距 | **修正为 L2**。两方均有行为约束，但 Charles 缺失 Cline 中的"Remember"8 项清单、"REMEMBER/IMPORTANT"强调段、并行调用示例、规划展示、完成总结等大量约束。详见 §5。 |
| 5.3.6 | yolo 身份差异 | 后台自动化 | 描述为"与 act 等价" | L8 差距 | **已修复** | Charles YOLO 模板 L62 已明确"在后台自主运行 / 无法与用户直接沟通"，与 Cline 对齐。计划原判定**已过时**。 |
| 5.3.7 | yolo submit_and_exit | 必须 | 描述为"可选" | L8 差距 | **已修复** | Charles YOLO 模板 L86-87 已明确"只有通过调用 submit_and_exit 工具才能结束任务 / 不调用将被视为未完成"，为"必须"语义。计划原判定**已过时**。 |
| 5.3.8 | 语言 | 英文 | 中文 | 语言不同 | L1 差距 | **确认 L1**。设计层面的本地化决策。 |

**复核结论**：计划中的 3 项 L8 差距（5.3.2 / 5.3.6 / 5.3.7）已在历史迭代中修复，当前代码状态优于计划记录。但 5.3.3 / 5.3.4 / 5.3.5 三项原判定"已对齐"应修正为"L2 差距"——虽然字段存在，但内容丰富度与约束粒度差距显著。

---

## 4. 身份声明与角色定义对比

### 4.1 DEFAULT 模板身份声明

**Cline**（system.ts L1）：
```
You are Cline, an AI coding agent. Your primary goal is to assist users with various coding tasks by leveraging your knowledge and the tools at your disposal. Given the user's prompt, you should use the tools available to you to answer user's question.
```

**Charles**（charles_system_prompt.py L31）：
```
你是 Charles，专业的 AI 投研情报官。你运行在以 Python 为核心的中文量化投研工作流中，擅长通过结构化工具调用完成数据分析、研报撰写、代码开发、金融数据查询等任务。
```

| 维度 | Cline | Charles | 差距 |
|------|-------|---------|------|
| 角色名 | Cline | Charles | 品牌差异 |
| 角色定位 | AI coding agent（通用编码 agent） | AI 投研情报官（领域特化） | L2 — 产品定位差异 |
| 工作领域 | 通用 coding tasks | 数据分析 / 研报撰写 / 代码开发 / 金融数据查询 | L2 — 领域绑定 |
| 技术栈 | 不限定 | Python 核心 + 中文量化投研工作流 | L2 — 技术栈绑定 |
| 行动指引 | use the tools available to answer | 通过结构化工具调用完成 | 已对齐（语义等价） |

### 4.2 YOLO 模板身份声明

**Cline**（system.ts L38-40）：
```
You are Cline, a careful and helpful coding agent that works in the background.
You are tasked to solve an issue reported by the user who you cannot communicate with directly.
Your goal is to utilize the tools at your disposal to investigate and answer the question according to user's instructions with the aim to verify that the issue is resolved.
```

**Charles**（charles_system_prompt.py L62）：
```
你是 Charles，在后台自主运行的 AI 投研助手。你无法与用户直接沟通，你的任务是利用可用工具调查并解决用户报告的问题，验证问题已解决。
```

| 维度 | Cline | Charles | 差距 |
|------|-------|---------|------|
| 后台运行 | works in the background | 在后台自主运行 | 已对齐 |
| 无法沟通 | cannot communicate with directly | 无法与用户直接沟通 | 已对齐 |
| 目标 | investigate and answer / verify resolved | 调查并解决 / 验证已解决 | 已对齐 |
| 角色修饰 | careful and helpful coding agent | AI 投研助手 | L1 — 措辞差异（领域特化） |

**YOLO 身份声明已对齐**，仅角色修饰词因产品定位不同（coding agent vs 投研助手），属可接受的本地化差异。

### 4.3 YOLO submit_and_exit 约束对比

**Cline**（system.ts L65-66）：
```
- You should only end the task when all of the requirements are met by calling the 'submit_and_exit' tool.
- Response without the submit_and_exit tool call will considered not completed and the task will continue.
```

**Charles**（charles_system_prompt.py L86-87）：
```
- 回复中必须始终包含工具调用，直到任务完成。只有通过调用 submit_and_exit 工具才能结束任务。
- 不调用 submit_and_exit 的回复将被视为未完成，任务将继续。
```

| 维度 | Cline | Charles | 差距 |
|------|-------|---------|------|
| 结束条件 | only end when all requirements met by submit_and_exit | 只有通过调用 submit_and_exit 才能结束 | 已对齐 |
| 未调用后果 | considered not completed, task continue | 视为未完成，任务继续 | 已对齐 |
| 强制性 | should only（语义为必须） | 必须 | 已对齐 |

**submit_and_exit 约束已对齐**。计划 5.3.7 原判定"Charles 描述为可选"已过时，当前为"必须"语义，与 Cline 一致。

---

## 5. 行为约束内容对比

### 5.1 DEFAULT 模板行为约束结构

**Cline DEFAULT 模板行为约束构成**（system.ts L3-34）：
1. 上下文收集段（L3）：gather necessary context / understand requirement / naming conventions / frameworks / validate unit test
2. 审问段（L4）：Review each question carefully / detailed accurate information
3. 澄清段（L5）：ask for clarification instead of making assumptions or lies
4. `<env>` 段（L7-13）
5. "Remember:" 8 项清单（L15-24）：代码约定 / 库限制 / 完整代码 / 假设显式化 / 规划展示 / 绝对路径 / 多工具并行 + 两次"do not"强约束 / 并行示例 / 文件验证
6. 规划展示段（L26）：present your plan at the start
7. "REMEMBER" 段（L28）：be helpful and proactive / don't ask for permission
8. "IMPORTANT" 段（L30）：Always includes tool calls / Response without tool calls considered completed
9. 完成总结段（L32）：provide a summary / don't indicate action without doing / validate answer
10. 简单问题段（L34）：simple question without coding context → answer directly without tools
11. `{{CLINE_RULES}}` + `{{CLINE_METADATA}}`（L35-36）

**Charles DEFAULT 模板行为约束构成**（charles_system_prompt.py L33-57）：
1. 身份声明（L31）
2. `## 通用行为规则` 6 项编号清单（L35-40）：上下文优先 / 任务拆解（todo_write）/ 技能触发 / 工具选择 / 绝对路径 / 结果导向
3. `## 工具调用规则` 4 项 bullet（L44-47）：并行调用 / 依赖分轮 / 先规划后调整 / 禁止绕过 skills 直接 run_commands
4. `<env>` 段（L49-54）
5. `{{CHARLES_RULES}}` + `{{CHARLES_METADATA}}`（L56-57）

### 5.2 行为约束差距清单

| # | Cline 约束项 | Charles 是否存在 | 差距等级 | 说明 |
|---|-------------|----------------|---------|------|
| 5.2.1 | 上下文收集（gather context / naming conventions / validate unit test） | 部分（L35"上下文优先"仅泛述） | L2 | Charles 缺失"naming conventions / frameworks / validate unit test"具体指引 |
| 5.2.2 | 审问与详细回答（Review carefully / detailed accurate） | 否 | L2 | Charles 无此约束 |
| 5.2.3 | 澄清优于假设（ask instead of assumptions or lies） | 否 | L2 | Charles 无此约束 |
| 5.2.4 | 代码约定遵循（adhere to existing conventions） | 否 | L2 | Charles 无此约束 |
| 5.2.5 | 库限制（only confirmed libraries） | 否 | L2 | Charles 无此约束 |
| 5.2.6 | 完整代码（no omissions or placeholders） | 否 | L2 | Charles 无此约束 |
| 5.2.7 | 假设显式化（explicit about assumptions） | 否 | L2 | Charles 无此约束 |
| 5.2.8 | 规划展示（show planning process） | 部分（L46"工具调用前先规划"） | L2 | Charles 仅在工具调用层提及规划，缺失"present your plan at the start of response"层面的约束 |
| 5.2.9 | 绝对路径（absolute paths） | 是（L39 第 5 项） | 已对齐 | |
| 5.2.10 | 多工具并行 + do not wait 强约束 | 是（L44 + L38 第 4 项） | 已对齐 | Charles 表述为"独立工具可一次回复中并行调用" |
| 5.2.11 | 并行调用示例（read_files / run_commands / editor 联合） | 否 | L2 | Charles 无具体示例，仅泛述 |
| 5.2.12 | 文件验证（verify edited files） | 否 | L2 | Charles 无此约束 |
| 5.2.13 | 主动帮助（be helpful and proactive / don't ask permission） | 否 | L2 | Charles 无此约束 |
| 5.2.14 | 工具调用强制性（Always includes tool calls / no-tool = completed） | 部分（L40"结果导向"） | L2 | Charles 表述为"文本输出不代表任务完成"，语义近似但弱于 Cline 的"no-tool response considered completed" |
| 5.2.15 | 完成总结（provide summary） | 否 | L2 | Charles 无此约束 |
| 5.2.16 | 简单问题直答（simple question without coding context → direct answer） | 否 | L2 | Charles 无此约束 |
| 5.2.17 | todo_write 任务拆解（Charles 独有） | — | Charles 独有 | Charles L36 强制 todo_write，Cline 无此约束（Cline 通过 todo_write 工具描述说明） |
| 5.2.18 | 技能触发规则（Charles 独有） | — | Charles 独有 | Charles L37-38 强制 skills 工具加载，Cline 无此约束 |
| 5.2.19 | 禁止绕过 skills 直接 run_commands（Charles 独有） | — | Charles 独有 | Charles L47，Cline 无此约束 |

**行为约束差距结论**：
- Cline DEFAULT 有 16 项行为约束，Charles 仅对齐其中 3 项（绝对路径 / 多工具并行 / 工具调用强制性-部分），缺失 13 项。
- Charles 有 3 项独有约束（todo_write 强制 / skills 触发 / 禁止绕过 skills），这些是 Charles 业务特化，非 Cline 风格。
- **整体行为约束丰富度差距为 L2**：Charles 模板过于精简，缺失 Cline 中大量"软约束"（如详细回答、澄清优于假设、代码约定、完整代码、假设显式化、文件验证、完成总结等），这些约束虽不阻塞功能但会影响 LLM 输出质量。

### 5.3 YOLO 模板行为约束对比

**Cline YOLO 模板约束**（system.ts L42-50）：8 项 RULES（输出格式 / 库兼容 / 完整代码 / 规划展示不重复 / 绝对路径 / 多工具并行 / 并行示例 / 文件验证）+ `<env>` + 6 项 IMPORTANT（bug 修复目标 / 正确修复定义 / 测试套件 / 测试通过前不完成 / submit_and_exit 必须 / 不调用继续）。

**Charles YOLO 模板约束**（charles_system_prompt.py L64-87）：8 项规则（输出格式 / 库兼容 / 完整代码 / 规划不重复 / 绝对路径 / 多工具并行 / 并行示例 / 文件验证）+ `<env>` + 6 项重要（bug 修复 / 正确修复 / 测试套件 / 测试通过前不完成 / submit_and_exit 必须 / 不调用继续）。

| # | Cline YOLO 约束 | Charles YOLO 约束 | 差距 |
|---|----------------|------------------|------|
| 5.3.Y.1 | RULES 8 项 | 规则 8 项 | **已对齐**（逐项语义等价） |
| 5.3.Y.2 | IMPORTANT 6 项 | 重要 6 项 | **已对齐**（逐项语义等价） |
| 5.3.Y.3 | submit_and_exit 必须 | submit_and_exit 必须 | 已对齐 |
| 5.3.Y.4 | 测试套件验证 | 测试套件验证 | 已对齐 |

**YOLO 模板行为约束已完全对齐**，两方的 RULES 8 项与 IMPORTANT 6 项逐项语义等价，仅语言不同。这是 P5.3 中对齐度最高的部分。

---

## 6. 内容长度与措辞对比

### 6.1 精确长度计量

用 Python 脚本（UTF-8 解码 + 正则提取模板字面量）统计：

| 模板 | 行数 | 字符数 | 去空白字符数 |
|------|------|--------|-------------|
| Cline DEFAULT | 36 | 3695 | 3088 |
| Cline YOLO | 31 | 2847 | 2383 |
| Charles DEFAULT | 27 | 828 | 756 |
| Charles YOLO | 29 | 809 | 735 |

### 6.2 长度差距分析

| 对比 | Cline | Charles | Charles/Cline 比例 | 差距等级 |
|------|-------|---------|-------------------|---------|
| DEFAULT 字符数 | 3695 | 828 | 22.4% | L2 |
| DEFAULT 去空白 | 3088 | 756 | 24.5% | L2 |
| YOLO 字符数 | 2847 | 809 | 28.4% | L1 |
| YOLO 去空白 | 2383 | 735 | 30.8% | L1 |

**关键观察**：
- **DEFAULT 模板长度差距为 L2**：Charles 仅为 Cline 的 ~22%，缺失大量行为约束（详见 §5.2）。
- **YOLO 模板长度差距为 L1**：Charles 为 Cline 的 ~28%，但因 YOLO 的 8+6 项约束已逐项对齐（§5.3），长度差距主要来自中英文编码密度差异（中文每字符信息量高于英文），实际约束覆盖度已对齐。
- **DEFAULT 与 YOLO 的对齐度倒挂**：Charles 的 YOLO 模板对齐度高于 DEFAULT 模板。这是因为 YOLO 模板的约束项更结构化（清单式），Charles 在迁移时逐项翻译；而 DEFAULT 模板的约束更散文化（Remember / REMEMBER / IMPORTANT 多段），Charles 在迁移时做了大幅精简。

### 6.3 措辞风格对比

| 维度 | Cline | Charles |
|------|-------|---------|
| 段落组织 | 散文式 + "Remember:" / "REMEMBER" / "IMPORTANT" 多段强调 | Markdown 结构化（## 通用行为规则 / ## 工具调用规则） |
| 强调词 | REMEMBER / IMPORTANT / Always 大写强调 | "必须" / "禁止" 中文强调 |
| 编号风格 | bullet（-）为主 | 编号（1. 2. 3.）+ bullet（-）混合 |
| 示例丰富度 | 高（并行调用具体示例） | 低（仅泛述） |
| 语气 | 命令式 + 鼓励式混合（be helpful and proactive） | 纯命令式（必须 / 禁止） |

**措辞风格差距**：Charles 采用更结构化的 Markdown 组织（## 二级标题），可读性优于 Cline 的散文式；但 Cline 的多段强调（REMEMBER / IMPORTANT）对 LLM 的注意力引导更强。这是风格差异，非缺陷。

---

## 7. nanobot 残留专项检查

### 7.1 模板文件残留检查

**检查文件**：`agent/prompts/charles_system_prompt.py`

**检查方法**：Grep `nanobot`（不区分大小写）+ Grep `always` / `when_to_use` / `fallback`（nanobot 风格特征词）

**检查结果**：
- `nanobot`：0 处命中
- `always`：0 处命中
- `when_to_use`：0 处命中
- `fallback`：0 处命中

**结论**：`charles_system_prompt.py` **无任何 nanobot 风格残留**，模板文件完全干净。文件头 docstring（L1-25）明确说明"对标 Cline system.ts"，未提及 nanobot。

### 7.2 消费方残留检查

**检查文件**：`agent/context.py`（base prompt 的消费方）

**检查方法**：Grep `nanobot`（不区分大小写）+ 追踪 `extra_sections` 参数生命周期

**检查结果**：

#### 7.2.1 注释残留（1 处）

| 位置 | 内容 | 类型 |
|------|------|------|
| context.py L275-276 | `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` | 注释残留（docstring） |

该注释明确标注 `extra_sections` 为 nanobot 风格的废弃参数，Cline 无此概念。属历史对标说明，不影响运行逻辑。

#### 7.2.2 实现逻辑残留（1 处，分 3 个代码点）

虽然 `extra_sections` 在 docstring 中标记为"已废弃 / 当前无调用方传入"，但**代码仍在消费该参数**：

| 位置 | 代码 | 残留类型 |
|------|------|---------|
| context.py L255 | `extra_sections: dict[str, str] \| None = None,`（`SystemPromptBuilder.__init__` 参数签名） | 实现逻辑残留（参数签名） |
| context.py L292 | `self.extra_sections = extra_sections or {}`（实例化保存） | 实现逻辑残留（状态保存） |
| context.py L530-537 | `# 7. 额外段落（已废弃，保留兼容）` + `for title, content in self.extra_sections.items():` + 包装为 `RuleLoadResult` 注入 rules | 实现逻辑残留（**实际消费**） |

**L530-537 完整代码**：
```python
# 7. 额外段落（已废弃，保留兼容）
for title, content in self.extra_sections.items():
    if content:
        results.append(RuleLoadResult(
            path=Path(f"__extra__/{title}.md"),
            body=f"# {title}\n\n{content}",
            activated=True,
        ))
```

**残留评估**：
- **严重程度**：低。虽然代码仍消费 `extra_sections`，但 docstring 明确"当前无调用方传入"，即运行时 `self.extra_sections` 恒为 `{}`，for 循环体不会执行。
- **风险**：若未来有调用方误传 `extra_sections`，会以 nanobot 风格的"额外段落"形式注入 rules，破坏 base prompt + rules 的两层结构对齐。
- **与 Cline 的差异**：Cline `cline.ts` 的 `buildClineSystemPrompt()` 无 `extra_sections` 概念，base prompt 模板 + rules 两层即完整结构。Charles 保留此参数是 nanobot 风格的历史兼容层。

### 7.3 nanobot 残留结论

| 文件 | 注释残留 | 实现逻辑残留 | 整体评估 |
|------|---------|-------------|---------|
| `agent/prompts/charles_system_prompt.py` | 0 | 0 | 干净 |
| `agent/context.py`（base prompt 消费方） | 1 | 1（3 个代码点，运行时恒为空） | 低风险历史残留 |

**整体结论**：base prompt **模板本身无 nanobot 残留**；nanobot 残留集中在消费方 `context.py` 的 `extra_sections` 兼容层，属低风险历史残留（运行时不触发，但代码仍存在）。

---

## 8. 占位符与模板结构对比

### 8.1 占位符对比

| 占位符 | Cline | Charles | 差距 |
|--------|-------|---------|------|
| 平台 | `{{PLATFORM_NAME}}` | `{{PLATFORM_NAME}}` | 已对齐 |
| 日期 | `{{CURRENT_DATE}}` | `{{CURRENT_DATE}}` | 已对齐 |
| IDE | `{{IDE_NAME}}` | `{{IDE_NAME}}` | 已对齐 |
| 工作目录 | `{{CWD}}` | `{{CWD}}` | 已对齐 |
| Rules | `{{CLINE_RULES}}` | `{{CHARLES_RULES}}` | 已对齐（命名前缀不同，语义等价） |
| Metadata | `{{CLINE_METADATA}}` | `{{CHARLES_METADATA}}` | 已对齐（命名前缀不同，语义等价） |

### 8.2 模板结构对比

**DEFAULT 模板结构**：

| 段落顺序 | Cline | Charles |
|---------|-------|---------|
| 1 | 身份声明 | 身份声明 |
| 2 | 上下文收集 / 审问 / 澄清（3 段散文） | `## 通用行为规则`（6 项编号） |
| 3 | `<env>` 段 | `## 工具调用规则`（4 项 bullet） |
| 4 | "Remember:" 8 项清单 | `<env>` 段 |
| 5 | 规划展示段 | `{{CHARLES_RULES}}` |
| 6 | "REMEMBER" 段 | `{{CHARLES_METADATA}}` |
| 7 | "IMPORTANT" 段 | — |
| 8 | 完成总结段 | — |
| 9 | 简单问题段 | — |
| 10 | `{{CLINE_RULES}}` | — |
| 11 | `{{CLINE_METADATA}}` | — |

**结构差距**：Charles 将行为约束合并为两个 `##` 二级标题段（通用行为规则 + 工具调用规则），Cline 分散为 5-6 个散文段。Charles 缺失 Cline 的"Remember / REMEMBER / IMPORTANT / 完成总结 / 简单问题"5 个段落。`<env>` 段与 `{{*_RULES}}` / `{{*_METADATA}}` 的相对顺序已对齐。

**YOLO 模板结构**：

| 段落顺序 | Cline | Charles | 差距 |
|---------|-------|---------|------|
| 1 | 身份声明（后台运行） | 身份声明（后台运行） | 已对齐 |
| 2 | RULES 8 项 | 规则 8 项 | 已对齐 |
| 3 | `<env>` 段 | `<env>` 段 | 已对齐 |
| 4 | IMPORTANT 6 项 | 重要 6 项 | 已对齐 |
| 5 | `{{CLINE_RULES}}` | `{{CHARLES_RULES}}` | 已对齐 |
| 6 | `{{CLINE_METADATA}}` | `{{CHARLES_METADATA}}` | 已对齐 |

**YOLO 模板结构完全对齐**。

### 8.3 模板路由对比

**Cline**（cline.ts，通过 `buildClineSystemPrompt` 调用）：
- `mode === "yolo"` → `YOLO_CLINE_SYSTEM_PROMPT`
- 其他（act / plan）→ `DEFAULT_CLINE_SYSTEM_PROMPT`

**Charles**（context.py L185-205 `select_base_template`）：
```python
def select_base_template(mode: str | None = None) -> str:
    if mode == "yolo":
        return YOLO_CHARLES_SYSTEM_PROMPT
    return DEFAULT_CHARLES_SYSTEM_PROMPT
```

**路由逻辑完全对齐**：两方均按 `mode == "yolo"` 二选一路由，act / plan 共用 DEFAULT 模板。

---

## 9. 结论与差距评级

### 9.1 差距评级汇总

| 差距项 | 等级 | 说明 |
|--------|------|------|
| 5.3.1 Base prompt 模板存在性 | 已对齐 | 两方均有模板字符串常量 |
| 5.3.2 YOLO 独立模板 | **已修复**（计划原 L8 已过时） | Charles 已新增 YOLO 模板 |
| 5.3.3 身份声明 | L2 | 字段存在，内容差距显著（通用 vs 领域特化） |
| 5.3.4 角色定义 | L2 | 字段存在，领域绑定不同 |
| 5.3.5 行为约束 | L2 | Charles DEFAULT 缺失 13/16 项 Cline 约束 |
| 5.3.6 YOLO 身份差异 | **已修复**（计划原 L8 已过时） | Charles YOLO 已明确后台运行 |
| 5.3.7 YOLO submit_and_exit | **已修复**（计划原 L8 已过时） | Charles 已为"必须"语义 |
| 5.3.8 语言 | L1 | 英文 vs 中文（本地化决策） |
| 5.3.9 DEFAULT 模板长度 | L2 | Charles 828 字符 vs Cline 3695 字符（22%） |
| 5.3.10 YOLO 模板长度 | L1 | Charles 809 字符 vs Cline 2847 字符（28%），但约束项已对齐 |
| 5.3.11 YOLO 行为约束覆盖度 | 已对齐 | 8+6 项逐项语义等价 |
| 5.3.12 占位符 | 已对齐 | 6 个占位符命名与位置对齐 |
| 5.3.13 模板路由 | 已对齐 | `select_base_template` 与 Cline 二选一逻辑一致 |
| 5.3.14 nanobot 残留（模板文件） | 已对齐 | `charles_system_prompt.py` 干净 |
| 5.3.15 nanobot 残留（消费方） | L1（低风险） | `context.py` `extra_sections` 兼容层仍存在，运行时不触发 |

### 9.2 整体结论

**架构层面**（双模板设计 + 占位符 + 路由 + YOLO 约束覆盖度）：**已对齐 Cline**。计划 P5.3 中标记的 3 项 L8 差距（5.3.2 / 5.3.6 / 5.3.7）已在历史迭代中修复，当前代码状态优于计划记录。

**内容层面**（DEFAULT 模板行为约束丰富度）：**L2 差距**。Charles DEFAULT 模板过于精简（828 字符 vs Cline 3695 字符），缺失 Cline 中 13 项行为约束（上下文收集具体指引、审问详细回答、澄清优于假设、代码约定、库限制、完整代码、假设显式化、规划展示、并行示例、文件验证、主动帮助、完成总结、简单问题直答）。这些约束虽不阻塞功能，但会影响 LLM 输出质量。

**残留层面**：base prompt 模板文件无 nanobot 残留；消费方 `context.py` 的 `extra_sections` 兼容层为低风险历史残留（运行时不触发，但代码仍存在）。

**建议**（仅供参考，不在本报告任务范围内）：
- 若需进一步对齐 DEFAULT 模板内容，可参考 Cline 的"Remember 8 项清单"补充"代码约定遵循 / 库限制 / 完整代码 / 文件验证 / 完成总结"等约束到 Charles DEFAULT 模板。
- 若需清理 nanobot 残留，可移除 `context.py` 中 `extra_sections` 参数及 L530-537 的消费逻辑（需先确认无调用方依赖）。

---

## 10. 文件清单

### 10.1 Cline 源文件
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts`（DEFAULT + YOLO 模板定义）
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts`（模板消费方 / rule 注入说明）

### 10.2 Charles 源文件
- `e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py`（DEFAULT + YOLO 模板定义，无 nanobot 残留）
- `e:\jikeAI\code\CASE-AI量化系统\agent\context.py`（模板消费方，L185-205 路由 + L255/L275/L292/L530-537 `extra_sections` 兼容层）

### 10.3 计划文件
- `e:\jikeAI\code\CASE-AI量化系统\AGENT_COMPARISON_PLAN_V2.md` L1810-1833（P5.3 章节，部分判定已过时）
