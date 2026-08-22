# Phase 4.18 技能脚本调用规则对比

> 对比范围：Cline SKILL.md 文档中指导 agent 调用脚本的规范（脚本调用方式、参数传递、输出格式、错误处理、路径约定、脚本角色说明、脚本调用规则段）与 Charles 8 个技能 SKILL.md 中"脚本调用规则"段的实现差异；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> 本阶段聚焦 SKILL.md 文本层面"如何指导 agent 调用脚本"的规则约定，不涉及脚本自身 .py 实现风格（P4.19 专项）。
>
> Cline 源码：
> - `third_party/cline/docs/customization/skills.mdx` 全文 269 行（脚本调用规范、scripts/ 目录用途、referencing bundled files 示例）
> - `third_party/cline/docs/customization/skills.mdx` L201-223（scripts/ 用途说明 + 引用示例 + token 效率说明）
> - `third_party/cline/docs/customization/skills.mdx` L225-230（Use Scripts For vs Use Instructions For 对照表）
> - `third_party/cline/docs/customization/skills.mdx` L52-66（SKILL.md 模板：`## Steps` + `python scripts/validate.py`）
> - `third_party/cline/docs/customization/skills.mdx` L236-269（data-analysis 示例：内嵌代码块 + 步骤化）
>
> Charles 源码（8 个技能 SKILL.md 的"脚本角色说明"+"脚本调用规则"段）：
> - `agent_config/skills/bond-credit-review/SKILL.md` L59-68（脚本角色说明 + 脚本调用规则 2 条）
> - `agent_config/skills/compare-reports/SKILL.md` L56-67（脚本角色说明 + 脚本调用规则 3 条）
> - `agent_config/skills/financial-analysis/SKILL.md` L85-99（脚本角色说明 + 脚本调用规则 4 条）
> - `agent_config/skills/read-pdf/SKILL.md` L73-94（脚本角色说明 主脚本/内部脚本 + 脚本调用规则 5 条）
> - `agent_config/skills/sentiment-analysis/SKILL.md` L73-86（脚本角色说明 + 脚本调用规则 3 条）
> - `agent_config/skills/stock-price/SKILL.md` L49-60（脚本角色说明 + 脚本调用规则 3 条）
> - `agent_config/skills/web-search/SKILL.md` L58-69（脚本角色说明 + 脚本调用规则 3 条）
> - `agent_config/skills/write-report/SKILL.md` L81-104（脚本角色说明 主脚本/内部脚本 + 脚本调用规则段省略，以禁止行为替代）
>
> nanobot 溯源（原 SKILL.md 脚本调用规范，用于区分残留）：
> - `third_party/charles_bundle/charles-nanobot/skills/compare-reports/SKILL.md` L21-27（可用脚本表格）
> - `third_party/charles_bundle/charles-nanobot/skills/financial-analysis/SKILL.md` L24-31（可用脚本表格）
> - `third_party/charles_bundle/charles-nanobot/skills/read-pdf/SKILL.md` L71-80（可用脚本表格 + 执行流程）
> - `third_party/charles_bundle/charles-nanobot/skills/stock-price/SKILL.md` L22-26（可用脚本表格）
> - `third_party/charles_bundle/charles-nanobot/skills/web-search/SKILL.md` L20-24（可用脚本表格）
> - `third_party/charles_bundle/charles-nanobot/skills/sentiment-analysis/SKILL.md` L28-34（可用脚本表格）
> - `third_party/charles_bundle/charles-nanobot/skills/write-report/SKILL.md` L32-38（可用脚本表格）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 SKILL.md 中"指导 agent 如何调用脚本"的规则约定。**核心结论：两者在脚本调用方式（subprocess `python script.py`）和路径相对性上已对齐；Charles 在 Cline 极简规范基础上做了大量结构化增强（脚本角色说明、脚本调用规则段、Workflow 结构化字段、禁止行为段），这些增强是 Charles 独有设计而非 nanobot 残留——Charles 完全重构了 nanobot 的"可用脚本表格 + 示例对话"模式，替换为"脚本角色说明（主脚本/内部脚本）+ 脚本调用规则 + 结构化 Workflow"模式。**

### 核心结论

1. **脚本调用方式完全一致**：Cline 与 Charles 均采用 subprocess 风格（`python {path}/script.py --args`），脚本输出进入上下文、脚本代码不进入上下文。Cline skills.mdx L223 明确"Scripts can be executed directly, and only the script's output enters the context window"，Charles 8 个 SKILL.md 均用 ` ```bash ` 命令块包裹 `python agent_config/skills/.../script.py` 命令。

2. **路径约定已对齐但有差异**：Cline 用相对 SKILL.md 的路径（`python scripts/validate.py`，skills.mdx L220），Charles 用相对项目根目录的路径（`python agent_config/skills/{name}/scripts/{script}.py`）。两者均为相对路径（无前导 `/`），但基准点不同：Cline 以 SKILL.md 所在目录为基准，Charles 以项目根目录为基准。

3. **参数传递方式一致**：两者均用命令行参数（`--stock`、`--query` 等 argparse 风格），无 JSON/stdin 传参。Charles 在 Workflow Step 中用结构化"参数"子段列出每个参数的必填/可选、默认值、格式约束。

4. **输出格式约定差异**：Cline 不在 SKILL.md 中描述脚本输出格式（仅说明"output enters context"），Charles 用"预期输出"子段明确描述每个 Step 的输出形态（如"K 线数据表格"、"信用评分 + 风险点清单"）。

5. **错误处理差异**：Cline 不在 SKILL.md 模板中要求错误处理说明，Charles 用"失败处理"子段明确列出每种错误场景的应对（如"网络错误 → 提示用户检查网络后重试"）。

6. **脚本角色说明（Charles 独有）**：Cline 不区分脚本角色，所有 scripts/ 下文件等价；Charles 用"脚本角色说明"段将脚本分为"主脚本（agent 直接调用）"和"内部脚本（agent 不要直接调用，由主脚本内部调度）"两类。read-pdf 和 write-report 两个技能有内部脚本分类。

7. **脚本调用规则段（Charles 独有）**：Cline 无独立"脚本调用规则"段；Charles 7/8 个技能有独立的"## 脚本调用规则"段（write-report 以"禁止行为"段替代），用编号列表约定参数格式、路径约定、调用顺序等。

8. **nanobot 残留**：**0 处注释残留**（Charles 8 个 SKILL.md 中无任何 "nanobot" 字样），**0 处实现逻辑残留**（Charles 完全重构了 nanobot 的脚本调用文档模式，nanobot 的"可用脚本表格 + 示例对话 + keywords/capabilities frontmatter"在 Charles 中均不存在）。

### 一致性总体评估

- **脚本调用方式（subprocess）**：**高**。两者均用 `python script.py --args`，输出入上下文。
- **路径约定**：**中**。均为相对路径，但基准点不同（SKILL.md 目录 vs 项目根目录）。
- **参数传递**：**高**。均用命令行 argparse 风格。
- **输出/错误处理结构化**：**低**。Charles 有结构化"预期输出"/"失败处理"子段，Cline 无。
- **脚本角色说明**：**低**。Charles 独有主脚本/内部脚本区分，Cline 无。
- **脚本调用规则段**：**低**。Charles 独有独立规则段，Cline 无。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.18.1 | 命令块格式 | ` ```bash ` 内嵌 shell 命令（skills.mdx L220 `python scripts/validate.py`） | ` ```bash ` 内嵌 shell 命令（8 个 SKILL.md 的 Workflow Step "命令"子段） | 高 | 已对齐 |
| 4.18.2 | 脚本调用方式 | subprocess：`python scripts/validate.py`（skills.mdx L220），脚本输出进入上下文（L223） | subprocess：`python agent_config/skills/{name}/scripts/{script}.py --args`（8 个 SKILL.md） | 高 | 完全一致。nanobot 也用 subprocess，非残留 |
| 4.18.3 | 参数说明 | 无结构化参数说明，示例中直接写 `python scripts/validate.py`（skills.mdx L220） | 每个 Workflow Step 有"参数"子段，列出 `--参数 (必填/可选): 说明 + 默认值 + 格式约束` | 中 | Charles 额外增强（结构化参数说明） |
| 4.18.4 | 失败处理 | 无要求。skills.mdx 模板无失败处理段 | 每个 Workflow Step 有"失败处理"子段，列出错误场景 → 应对动作（如"网络错误 → 提示用户检查网络后重试"） | 低 | Charles 额外增强（结构化失败处理） |
| 4.18.5 | 何时执行 | 无要求。skills.mdx 模板仅 `## Steps` 编号列表 | 每个 Workflow Step 有"何时执行"子段，明确触发时机 | 低 | Charles 额外增强 |
| 4.18.6 | 预期输出 | 无要求。skills.mdx L223 仅说明"output enters context"，不描述输出形态 | 每个 Workflow Step 有"预期输出"子段，描述输出形态（如"K 线数据表格"、"信用评分 + 风险点清单"） | 低 | Charles 额外增强 |
| 4.18.7 | 前置条件 | 无要求 | 每个 Workflow Step 有"前置条件"子段（如"Step 1 已收集到足够数据"） | 低 | Charles 额外增强 |
| 4.18.8 | 跳过条件 | 无要求 | 部分 Step 有"跳过条件"子段（如"用户只需要信用评分时，可跳过 Step 3"） | 低 | Charles 额外增强 |
| 4.18.9 | 成功处理 | 无要求 | 部分 Step 有"成功处理"子段（如 read-pdf Step 1"若返回有效结果，直接引用文档名和页码回答用户，到此结束"） | 低 | Charles 额外增强 |
| 4.18.10 | 脚本路径基准 | 相对 SKILL.md 所在目录：`python scripts/validate.py`（skills.mdx L220，scripts/ 是 SKILL.md 同级子目录） | 相对项目根目录：`python agent_config/skills/{name}/scripts/{script}.py` | 中 | 基准点不同。Charles 路径更长但更明确，避免 cwd 依赖 |
| 4.18.11 | 路径相对性 | 相对路径（无前导 `/`），skills.mdx L220 示例 `scripts/validate.py` | 相对路径（无前导 `/`），如 `agent_config/skills/stock-price/scripts/get_kline.py` | 高 | 均为相对路径，已对齐 |
| 4.18.12 | 脚本角色说明 | 无。scripts/ 下所有文件等价，skills.mdx L201-208 仅按用途分类（validation/data processing/calculations/API） | 有独立"## 脚本角色说明"段，分"主脚本（agent 直接调用）"和"内部脚本（agent 不要直接调用）"两类。read-pdf 有 4 个内部脚本，write-report 有 2 个内部脚本 | 低 | Charles 独有增强，非 nanobot 残留（nanobot 无此区分） |
| 4.18.13 | 脚本调用规则段 | 无独立规则段。skills.mdx 仅在"Keeping Skills Focused"段给写作建议 | 有独立"## 脚本调用规则"段（7/8 技能有），编号列表约定参数格式/路径约定/调用顺序。write-report 以"禁止行为"段替代 | 低 | Charles 独有增强 |
| 4.18.14 | 禁止行为段 | 无。skills.mdx 无"禁止行为"段 | 8/8 技能均有"## 禁止行为"段，编号列表约定不可执行的动作 | 低 | Charles 独有增强 |
| 4.18.15 | 场景路由段 | 无。skills.mdx 模板无场景路由 | 8/8 技能均有"## 场景路由"段，根据用户意图选择执行路径 | 低 | Charles 独有增强 |
| 4.18.16 | 执行说明子段 | 无 | 部分 Step 有"执行说明"子段（如 read-pdf Step 2"该脚本会自动下载最新年报并调用解析脚本 + 构建索引"） | 低 | Charles 额外增强 |
| 4.18.17 | 终端监控说明 | 无 | read-pdf 有"## 终端监控说明"段（L112-116），描述脚本进度输出格式 | 低 | Charles 独有增强 |
| 4.18.18 | 错误码处理 | 无 | Charles 不显式处理退出码，靠"失败处理"子段描述错误场景文案（如"xtquant not found"、"MiniQMT not running"） | 中 | Charles 按错误消息文案匹配，非退出码 |
| 4.18.19 | 脚本输出位置 | 输出到 stdout，进入 agent 上下文（skills.mdx L223） | 输出到 stdout，进入 agent 上下文（8 个 SKILL.md 隐含约定） | 高 | 已对齐 |
| 4.18.20 | token 效率说明 | 明确："Scripts are token-efficient because only their output enters context, not the code itself"（skills.mdx L209） | 无显式说明，但设计隐含遵循（脚本代码不入上下文） | 中 | Cline 显式说明，Charles 隐含遵循 |
| 4.18.21 | scripts/ 用途分类 | 有"Use Scripts For vs Use Instructions For"对照表（skills.mdx L225-230）：脚本用于确定性操作/复杂计算/可靠性需求 | 无显式分类，但脚本用途符合 Cline 分类（validation/data processing/calculations/API） | 中 | Charles 隐含遵循，无显式文档 |
| 4.18.22 | 引用 bundled 文件方式 | `[advanced.md](docs/advanced.md)` markdown 链接 + `python scripts/validate.py` 命令（skills.mdx L216-220） | 无 docs/ 引用（Charles 技能无 docs/ 子目录），仅 scripts/ 命令引用 | 中 | Charles 无 docs/ 引用场景 |
| 4.18.23 | 步骤化组织 | `## Steps` + 编号列表（skills.mdx L62-65） | `## Workflow` + `### Step N: 标题` + 结构化子段（8 个 SKILL.md） | 中 | 均步骤化，Charles 更结构化 |
| 4.18.24 | 内部脚本禁调规则 | 无此概念 | read-pdf L93"不要直接调用内部脚本：parse_pdf_basic.py、parse_pdf_ocr.py、build_index.py 是底层工具，由 fetch_report_pdf.py 内部调度"；write-report L89/L104 禁止调用 five_step_analysis.py / prompts.py | 低 | Charles 独有增强 |
| 4.18.25 | 股票代码格式约定 | 无 | Charles 多技能统一约定"不带交易所后缀"（financial-analysis/read-pdf/sentiment-analysis/compare-reports）vs stock-price"必须带后缀"（`.SH`/`.SZ`） | — | Charles 独有领域约定，跨技能一致性需注意 |

---

## 三、重点差距详细说明

### 3.1 脚本调用方式：subprocess 已对齐（4.18.2）

Cline 与 Charles 在脚本调用方式上**完全一致**，均采用 subprocess 风格：

- **Cline**：skills.mdx L220 示例 `python scripts/validate.py`，L223 明确"Scripts can be executed directly, and only the script's output enters the context window"。Cline 的设计是 agent 通过执行命令（execute_command 工具）运行脚本，脚本 stdout 进入上下文，脚本代码本身不进入上下文（token 效率）。

- **Charles**：8 个 SKILL.md 的 Workflow Step "命令"子段均用 ` ```bash ` 块包裹 `python agent_config/skills/{name}/scripts/{script}.py --args` 命令。例如 stock-price SKILL.md L36：
  ```
  python agent_config/skills/stock-price/scripts/get_kline.py <股票代码> [周期] [条数]
  ```

**nanobot 对比**：nanobot SKILL.md 也用 subprocess 风格（`python skills/{name}/scripts/{script}.py`），如 nanobot compare-reports SKILL.md L38 `python skills/compare-reports/scripts/cross_period.py --stock 688981`。三者（Cline/Charles/nanobot）在脚本调用方式上一致，**subprocess 风格非 nanobot 残留**。

**关于 AGENT_COMPARISON_PLAN_V2.md L1705 的说明**：计划表 P4.20 列出"脚本调用：nanobot 直接 import 而非 subprocess"作为 nanobot 风格特征。此描述指 nanobot **agent 运行时**内部调用脚本的方式（直接 import 模块），而非 SKILL.md 文档中的调用规范。SKILL.md 文档层面 nanobot 同样用 subprocess 命令风格。本阶段聚焦 SKILL.md 文本规范，subprocess 风格在三者中一致，无残留。

### 3.2 路径约定：基准点差异（4.18.10 / 4.18.11）

- **Cline**：脚本路径相对 SKILL.md 所在目录。skills.mdx L41-48 目录结构示例 `my-skill/scripts/helper.sh`，L220 引用示例 `python scripts/validate.py`（scripts/ 是 SKILL.md 同级子目录）。Cline 的 `use_skill` 工具加载 SKILL.md 后，agent 在 SKILL.md 所在目录上下文中执行命令。

- **Charles**：脚本路径相对项目根目录。所有 8 个 SKILL.md 的命令均用 `python agent_config/skills/{name}/scripts/{script}.py` 完整路径，如 financial-analysis SKILL.md L50 `python agent_config/skills/financial-analysis/scripts/fetch_financial_csv.py --stock <股票代码>`。

- **nanobot**：脚本路径相对项目根目录，但前缀为 `skills/`（无 `agent_config/`）。如 nanobot financial-analysis SKILL.md L35 `python skills/financial-analysis/scripts/fetch_financial_csv.py --stock <代码>`。

**差异影响**：
1. Cline 的相对 SKILL.md 路径更短（`scripts/validate.py`），但依赖 agent 的 cwd 为 SKILL.md 目录。
2. Charles 的相对项目根路径更长（`agent_config/skills/.../script.py`），但 cwd 无关（项目根目录是 agent 的默认 cwd），更健壮。
3. Charles 从 nanobot 迁移时仅将路径前缀从 `skills/` 改为 `agent_config/skills/`，路径结构一致，非残留。

### 3.3 脚本角色说明：Charles 独有的主脚本/内部脚本区分（4.18.12 / 4.18.24）

这是 Charles 相对 Cline 和 nanobot 最显著的增强。

**Cline**：不区分脚本角色。skills.mdx L201-208 将 scripts/ 下文件按用途分类（validation/data processing/calculations/API），但所有脚本对 agent 等价可用，无"内部脚本"概念。

**nanobot**：不区分脚本角色。nanobot SKILL.md 用"可用脚本"表格列出所有脚本（如 read-pdf L72-80 列出 6 个脚本），agent 可调用任意脚本。

**Charles**：用"## 脚本角色说明"段将脚本分两类：

| 技能 | 主脚本（agent 直接调用） | 内部脚本（agent 不要直接调用） |
|------|------------------------|------------------------------|
| read-pdf | query_report.py、fetch_report_pdf.py | build_index.py、parse_pdf_basic.py、parse_pdf_ocr.py、fetch_financial_data.py |
| write-report | report_generator.py | five_step_analysis.py、prompts.py |
| 其他 6 个 | 全部为主脚本 | 无内部脚本 |

Charles 的内部脚本禁调规则在"脚本调用规则"段和"禁止行为"段双重约束：
- read-pdf L93："不要直接调用内部脚本：parse_pdf_basic.py、parse_pdf_ocr.py、build_index.py 是底层工具，由 fetch_report_pdf.py 内部调度"
- read-pdf L124："禁止直接调用 parse_pdf_basic.py、parse_pdf_ocr.py、build_index.py 等内部脚本"
- write-report L104："禁止直接调用 five_step_analysis.py 或 prompts.py 等内部脚本"

**残留判定**：**非 nanobot 残留**。nanobot 无主脚本/内部脚本区分，Charles 的此设计是独有增强，用于约束 agent 不绕过主脚本的编排逻辑（如 fetch_report_pdf.py 内部自动调用 parse + build_index）。

### 3.4 脚本调用规则段：Charles 独有独立段（4.18.13）

**Cline**：无独立"脚本调用规则"段。skills.mdx 仅在"Keeping Skills Focused"（L143-147）和"Writing Effective Descriptions"（L117-141）段给 SKILL.md 写作建议，不涉及脚本调用规则。

**Charles**：7/8 个技能有独立"## 脚本调用规则"段（write-report 例外，以"禁止行为"段替代）。规则段用编号列表约定：

| 技能 | 规则数 | 典型规则内容 |
|------|--------|-------------|
| bond-credit-review | 2 | `--type` 必须为 `城投`/`产业`；Step 2 依赖 Step 1 数据收集 |
| compare-reports | 3 | 股票代码不带后缀；对比维度要简洁；至少两家公司 |
| financial-analysis | 4 | 股票代码不带后缀；不要指定 `--output_dir`；CSV 文件名格式；read_files 读 CSV 不带后缀 |
| read-pdf | 5 | 股票代码不带后缀；查询关键词要简洁；索引目录固定；下载脚本自动构建索引；不要直接调用内部脚本 |
| sentiment-analysis | 3 | 股票代码不带后缀；Step 1 必需；Step 2 和 Step 3 独立 |
| stock-price | 3 | 股票代码必须带后缀；公司名称要转换；不要用 web_search 查股价 |
| web-search | 3 | 关键词要简洁；多关键词用空格分隔；不要用 web_search 查股价/财报 |
| write-report | 0（以禁止行为替代） | — |

**残留判定**：**非 nanobot 残留**。nanobot SKILL.md 无"脚本调用规则"段，仅有"可用脚本"表格和"示例对话"。Charles 的规则段是独有增强。

### 3.5 Workflow 结构化字段：Charles 独有的 9 类子段（4.18.3-4.18.9 / 4.18.16）

**Cline**：skills.mdx L52-66 SKILL.md 模板仅用 `## Steps` + 编号列表，每步一句话描述。L236-269 data-analysis 示例用 `## 1. Understand the Data` 标题 + 无序列表，无结构化子段。

**Charles**：8 个 SKILL.md 的 `## Workflow` 段下每个 `### Step N: 标题` 含最多 9 类结构化子段：

| 子段 | 用途 | 示例（stock-price Step 1） |
|------|------|---------------------------|
| 何时执行 | 触发时机 | "用户询问股价/K线/走势/成交量时" |
| 前置条件 | 执行前提 | "MiniQMT 客户端已运行并登录" |
| 命令 | bash 命令块 | `python agent_config/skills/stock-price/scripts/get_kline.py <股票代码> [周期] [条数]` |
| 参数 | 参数说明 | `--stock (必填): 股票代码带交易所后缀` |
| 参数选择 | 参数选择策略 | "根据场景路由表选择合适的周期和条数" |
| 预期输出 | 输出形态 | "K 线数据表格（日期/开盘/收盘/最高/最低/成交量）" |
| 成功处理 | 成功后的动作 | read-pdf Step 1："若返回有效结果，直接引用文档名和页码回答用户，到此结束" |
| 失败处理 | 错误场景应对 | "xtquant not found → 提示用户安装 xtquant 包" |
| 跳过条件 | 可跳过的场景 | bond-credit-review Step 3："用户只需要信用评分或风险点时，可跳过此步" |
| 执行方式 | 非命令执行说明 | write-report Step 2："直接在对话中输出 Markdown 格式研报正文" |
| 执行说明 | 命令执行补充说明 | read-pdf Step 2："该脚本会自动下载最新年报并调用解析脚本 + 构建索引" |

**残留判定**：**非 nanobot 残留**。nanobot SKILL.md 的"工作流程"/"执行流程"段仅用编号列表 + 内嵌命令，无结构化子段。Charles 的 9 类子段是独有增强。

### 3.6 禁止行为段：Charles 独有（4.18.14）

**Cline**：skills.mdx 无"禁止行为"段。

**nanobot**：部分技能有零散的"禁止"行（如 read-pdf L101"禁止: 安装依赖、检查环境、验证包版本。"、stock-price L42"禁止：安装依赖、检查环境、验证包版本。"），但无独立"禁止行为"段。

**Charles**：8/8 技能均有独立"## 禁止行为"段，编号列表约定不可执行的动作。典型禁止项：
- 数据假设类："禁止假设本地一定有 CSV 数据"（financial-analysis L109）
- 跳步类："禁止跳过 Step 1 直接执行 Step 2"（bond-credit-review L72）
- 内部脚本类："禁止直接调用 parse_pdf_basic.py 等内部脚本"（read-pdf L124）
- 工具替代类："禁止用 web_search 查询股价/K线数据"（stock-price L63）

**残留判定**：**非 nanobot 残留**。Charles 的"禁止行为"段是独立结构化段，nanobot 仅有零散"禁止"行。Charles 的禁止项内容也更丰富（数据假设/跳步/内部脚本/工具替代），非 nanobot 残留。

### 3.7 场景路由段：Charles 独有（4.18.15）

**Cline**：skills.mdx 无"场景路由"段。

**nanobot**：nanobot SKILL.md 无"场景路由"段，仅有"示例对话"段展示典型用户查询。

**Charles**：8/8 技能均有"## 场景路由"段，根据用户意图选择执行路径。例如 bond-credit-review L22-26：
- 完整信用审查 → Step 1 → Step 2 → Step 3
- 只需要信用评分 → Step 1 → Step 2，跳过 Step 3
- 只需要风险点识别 → Step 1 → Step 2，提取风险点

**残留判定**：**非 nanobot 残留**。Charles 的场景路由是独有增强，替代了 nanobot 的"示例对话"段。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（0 处）

对 Charles 8 个 SKILL.md 文件执行 Grep `nanobot`（忽略大小写）搜索：

```
Grep -i "nanobot" agent_config/skills/
```

**结果**：0 命中。Charles 8 个 SKILL.md 中无任何 "nanobot" 字样，无注释残留。

### 4.2 实现逻辑残留（0 处）

逐项核查 nanobot SKILL.md 脚本调用文档模式是否在 Charles 中残留：

| 检查项 | nanobot 模式 | Charles 模式 | 残留判定 |
|--------|-------------|-------------|---------|
| 可用脚本表格 | ` \| 脚本 \| 功能 \| 参数 \| ` markdown 表格（7/8 技能有） | 无表格，改用"## 脚本角色说明"段 bullet list + 主脚本/内部脚本分类 | **无残留**（完全重构） |
| 示例对话段 | "## 示例对话"段，含"用户: ..." + "步骤: ..." | 无"示例对话"段，改用"## 场景路由"段 | **无残留**（完全替换） |
| keywords frontmatter | `keywords: 财务分析, 指标, ...`（nanobot 6/8 技能有） | 无 `keywords` 字段，改用 `when_to_use` 字段 | **无残留**（字段替换） |
| capabilities frontmatter | `capabilities: [- xxx, - yyy]`（nanobot 6/8 技能有） | 无 `capabilities` 字段 | **无残留**（字段移除） |
| 执行流程段标题 | "## 执行流程（必须遵守）" / "## 工作流程" | "## Workflow" + "### Step N" | **无残留**（标题英文化 + 结构化） |
| 路径前缀 | `python skills/{name}/scripts/...` | `python agent_config/skills/{name}/scripts/...` | **无残留**（路径前缀更新） |
| 零散禁止行 | "禁止: 安装依赖、检查环境、验证包版本。" | "## 禁止行为"独立段，禁止项更丰富 | **无残留**（结构化为独立段） |
| 相对路径注释 | "注意：所有路径参数使用相对路径（不带前导 /）。" | 无此注释（路径约定在"脚本调用规则"段统一约定） | **无残留**（注释移除，约定保留） |
| subprocess 调用风格 | `python skills/{name}/scripts/{script}.py --args` | `python agent_config/skills/{name}/scripts/{script}.py --args` | **非残留**（subprocess 风格三者一致，Cline 也用） |
| 依赖技能段 | "## 依赖技能"（sentiment-analysis nanobot 有） | 无"依赖技能"段 | **无残留**（段移除） |
| 关键词过滤体系 | "## 关键词过滤体系" + 利好/利空/政策类（sentiment-analysis nanobot 有） | 无此段 | **无残留**（段移除） |

**关键说明**：

1. **subprocess 风格非 nanobot 残留**：nanobot、Charles、Cline 三者在 SKILL.md 文档层面均用 subprocess 命令风格（`python script.py --args`）。AGENT_COMPARISON_PLAN_V2.md P4.20 提及的"nanobot 直接 import 而非 subprocess"指 nanobot agent 运行时内部调用方式，非 SKILL.md 文档规范。本阶段聚焦 SKILL.md 文本，subprocess 风格无残留。

2. **Charles 完全重构了 nanobot 脚本调用文档模式**：nanobot 的核心文档模式（可用脚本表格 + 示例对话 + keywords/capabilities frontmatter）在 Charles 中**全部不存在**。Charles 用全新的"脚本角色说明 + 脚本调用规则 + 结构化 Workflow + 场景路由 + 禁止行为"五段式替代，这是 Charles 的独有设计，非 nanobot 残留。

3. **路径前缀更新非残留**：Charles 将 nanobot 的 `skills/` 前缀更新为 `agent_config/skills/`，这是路径迁移（P2 重构），非逻辑残留。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（nanobot 字样） | 0 处 | — | 无需处理 |
| 实现逻辑残留（nanobot 文档模式） | 0 处 | — | 无需处理 |
| Charles 独有增强（非残留） | 5 段式文档结构（脚本角色说明 + 脚本调用规则 + 结构化 Workflow + 场景路由 + 禁止行为） | — | 保留，属合理增强 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**：在 SKILL.md 文本中引用 "nanobot" 字样。Charles 8 个 SKILL.md 经 Grep 搜索确认 0 命中，无注释残留。

**实现逻辑残留**：nanobot 的脚本调用文档模式（结构、段落、字段约定）在 Charles 中持续存在并影响 agent 行为。经逐项核查（§4.2），nanobot 的 10 类文档模式在 Charles 中**全部不存在或已被重构**：
- 可用脚本表格 → 替换为脚本角色说明段
- 示例对话段 → 替换为场景路由段
- keywords/capabilities frontmatter → 替换为 when_to_use 字段
- 执行流程段 → 替换为结构化 Workflow 段
- 零散禁止行 → 替换为独立禁止行为段

**关键区别**：若删除 Charles 的"脚本角色说明"段，agent 将失去主脚本/内部脚本的区分约束，可能直接调用 parse_pdf_basic.py 等底层脚本——但这不会恢复 nanobot 行为（nanobot 无此区分），而是丢失 Charles 独有增强。因此"脚本角色说明"段是 Charles 增强而非 nanobot 残留。

---

## 五、修复建议

### 5.1 高优先级（P1）

无。脚本调用方式已对齐，无阻塞性问题。

### 5.2 中优先级（P2）

1. **路径约定基准点对齐**（4.18.10）：Charles 用相对项目根目录的完整路径（`agent_config/skills/.../script.py`），Cline 用相对 SKILL.md 目录的短路径（`scripts/validate.py`）。Charles 方案更健壮（cwd 无关），但路径较长。建议保留 Charles 方案，但在"脚本调用规则"段统一说明"所有命令路径相对项目根目录"，避免 agent 误用 SKILL.md 目录为 cwd。

2. **write-report 脚本调用规则段补全**（4.18.13）：write-report 是 8 个技能中唯一无"## 脚本调用规则"段的技能（以"禁止行为"段替代）。建议补全独立规则段，与其他 7 个技能格式一致，约定 `--stock`/`--title`/`--output_dir` 参数格式。

3. **股票代码格式跨技能一致性**（4.18.25）：Charles 7 个技能约定"不带交易所后缀"（如 `600519`），但 stock-price 约定"必须带后缀"（如 `600519.SH`）。这是业务合理性差异（MiniQMT 要带后缀，东方财富/巨潮不带），但应在 AGENTS.md 或通用规则中统一说明此差异，避免 agent 跨技能调用时混淆。

### 5.3 低优先级（P3）

4. **token 效率说明补全**（4.18.20）：Cline skills.mdx L209 显式说明"Scripts are token-efficient because only their output enters context, not the code itself"。Charles 无此显式说明。可在 AGENTS.md 或通用技能规则中补充此原则，帮助 agent 理解为何优先用脚本而非内嵌代码。

5. **错误码处理规范化**（4.18.18）：Charles 当前靠"失败处理"子段描述错误消息文案匹配（如"xtquant not found"），不显式处理退出码。可考虑在"脚本调用规则"段统一约定"脚本失败时返回非零退出码 + stderr 错误消息，agent 按 stderr 内容匹配失败处理规则"。

6. **场景路由段格式统一**（4.18.15）：8 个技能的"场景路由"段格式略有差异（有的用 bullet list，有的用表格）。可统一为 bullet list 格式，提升可读性。

---

## 六、验证方法建议

### 6.1 脚本调用方式验证

1. **subprocess 风格一致性**：
   ```
   Grep "```bash" agent_config/skills/*/SKILL.md
   ```
   预期：8 个 SKILL.md 均有 ` ```bash ` 命令块，命令均以 `python agent_config/skills/...` 开头

2. **Cline subprocess 风格**：
   ```
   Grep "python scripts/" third_party/cline/docs/customization/skills.mdx
   ```
   预期：命中 L220 `python scripts/validate.py`

### 6.2 路径约定验证

1. **Charles 路径基准**：
   ```
   Grep "python agent_config/skills/" agent_config/skills/*/SKILL.md
   ```
   预期：8 个 SKILL.md 均用 `python agent_config/skills/{name}/scripts/...` 路径

2. **无前导 `/` 验证**：
   ```
   Grep "python /agent_config" agent_config/skills/
   ```
   预期：0 命中（均为相对路径）

### 6.3 脚本角色说明验证

1. **主脚本/内部脚本区分**：
   ```
   Grep "内部脚本" agent_config/skills/*/SKILL.md
   ```
   预期：命中 read-pdf + write-report 两个 SKILL.md

2. **内部脚本禁调规则**：
   ```
   Grep "不要直接调用" agent_config/skills/*/SKILL.md
   ```
   预期：命中 read-pdf L93 + L124，write-report L89 + L104

### 6.4 脚本调用规则段验证

1. **独立规则段存在性**：
   ```
   Grep "## 脚本调用规则" agent_config/skills/*/SKILL.md
   ```
   预期：7 个命中（write-report 无此段）

2. **禁止行为段存在性**：
   ```
   Grep "## 禁止行为" agent_config/skills/*/SKILL.md
   ```
   预期：8 个命中（全部技能）

### 6.5 nanobot 残留验证

1. **注释残留验证**：
   ```
   Grep -i "nanobot" agent_config/skills/
   ```
   预期：0 命中

2. **nanobot 文档模式残留验证**：
   ```
   Grep "可用脚本" agent_config/skills/*/SKILL.md
   Grep "示例对话" agent_config/skills/*/SKILL.md
   Grep "^keywords:" agent_config/skills/*/SKILL.md
   Grep "^capabilities:" agent_config/skills/*/SKILL.md
   ```
   预期：均 0 命中（Charles 已完全重构 nanobot 文档模式）

3. **nanobot 溯源对比验证**：
   ```
   Grep "可用脚本" third_party/charles_bundle/charles-nanobot/skills/*/SKILL.md
   ```
   预期：命中 nanobot 7/8 技能（bond-credit-review 除外，nanobot 该技能无脚本）

### 6.6 Workflow 结构化字段验证

1. **结构化子段存在性**：
   ```
   Grep "何时执行" agent_config/skills/*/SKILL.md
   Grep "前置条件" agent_config/skills/*/SKILL.md
   Grep "预期输出" agent_config/skills/*/SKILL.md
   Grep "失败处理" agent_config/skills/*/SKILL.md
   ```
   预期：8 个 SKILL.md 均命中上述子段

2. **Cline 无结构化子段**：
   ```
   Grep "何时执行\|前置条件\|预期输出\|失败处理" third_party/cline/docs/customization/skills.mdx
   ```
   预期：0 命中（Cline 模板无结构化子段）

---

## 七、与 P4.6/P4.7 发现的衔接

P4.6（SKILL.md body 结构）和 P4.7（SKILL.md 风格）已发现 Charles SKILL.md body 比 Cline 更结构化，本阶段（P4.18）在**脚本调用规则层面**深入对比，**确认并细化了以下发现**：

| P4.6/P4.7 发现 | P4.18 深化 |
|---------------|-----------|
| Charles SKILL.md body 含 Workflow + 禁止行为段，Cline 仅 `## Steps`（P4.6） | 确认 Workflow 段含 9 类结构化子段（何时执行/前置条件/命令/参数/预期输出/成功处理/失败处理/跳过条件/执行说明），Cline 无任何子段 |
| Charles 独有"脚本角色说明"段（P4.6） | 确认脚本角色说明分主脚本/内部脚本两类，read-pdf + write-report 有内部脚本禁调规则，Cline + nanobot 均无此区分 |
| Charles SKILL.md 风格更结构化（P4.7） | 确认结构化体现在脚本调用规则段（7/8 技能有独立段）、场景路由段（8/8）、禁止行为段（8/8），Cline 均无 |

**本阶段新增发现**（P4.6/P4.7 未覆盖）：
1. 脚本调用方式（subprocess）三者一致，非 nanobot 残留（§3.1）
2. 路径约定基准点差异：Cline 相对 SKILL.md 目录，Charles 相对项目根目录（§3.2）
3. Charles 完全重构 nanobot 文档模式：可用脚本表格 → 脚本角色说明、示例对话 → 场景路由、keywords/capabilities → when_to_use（§4.2）
4. 脚本调用规则段的跨技能一致性：7/8 技能有独立段，write-report 例外（§3.4）
5. 股票代码格式跨技能不一致：7 技能不带后缀 vs stock-price 带后缀（§4.18.25）
6. token 效率说明：Cline 显式说明，Charles 隐含遵循（§4.18.20）
