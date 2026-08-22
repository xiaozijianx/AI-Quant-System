# Phase 4.20 技能系统 nanobot 残留专项检查报告

## 1. 执行摘要

本报告对 CASE-AI 量化系统技能系统进行 nanobot 风格残留专项检查，覆盖 4 个核心 Python 文件、8 个 SKILL.md 文件以及 19 个技能脚本（注：bond-credit-review/SKILL.md 引用了 `bond_credit_review.py`，但实际目录下并未存在该脚本，实际有效脚本为 18 个）。

检查发现：
- **注释残留**：共 18 处，主要分布在 4 个核心 Python 文件的 docstring 中，明确提到 "nanobot" 字样。这些是历史对标说明，不影响运行逻辑。
- **实现逻辑残留**：共 17 处，集中在三大机制：
  1. `always` 预加载机制（SkillMetadata 字段 + Registry 三个方法 + read-pdf/SKILL.md frontmatter）
  2. `when_to_use` 字段（SkillMetadata 字段 + 8 个 SKILL.md frontmatter + Registry 摘要构建）
  3. SKILL.md 中的"脚本角色说明 / 脚本调用规则 / 禁止行为"三段式章节（8 个 SKILL.md 全部命中）
  4. PyYAML fallback 简单解析（loader.py 中 try/except + fallback 解析逻辑）

整体结论：**技能系统的实现逻辑层面确实残留了 nanobot 风格，不仅仅是注释层面**。其中 always 预加载机制和 when_to_use 字段属于功能层面的残留（被代码消费），SKILL.md 三段式章节属于指令文档层面的残留（影响 LLM 行为）。这些残留与 Cline 原生 skills 实现存在设计差异。

## 2. 检查范围与方法

### 2.1 检查范围

**核心 Python 文件（4 个）**：
- `agent/skills/loader.py`（508 行）
- `agent/skills/registry.py`（292 行）
- `agent/skills/skill_tool.py`（267 行）
- `agent/skills/__init__.py`（38 行）

**SKILL.md 文件（8 个）**：
- `agent_config/skills/bond-credit-review/SKILL.md`
- `agent_config/skills/compare-reports/SKILL.md`
- `agent_config/skills/financial-analysis/SKILL.md`
- `agent_config/skills/read-pdf/SKILL.md`
- `agent_config/skills/sentiment-analysis/SKILL.md`
- `agent_config/skills/stock-price/SKILL.md`
- `agent_config/skills/web-search/SKILL.md`
- `agent_config/skills/write-report/SKILL.md`

**脚本文件（实际 18 个，文档声称 19 个）**：
- `compare-reports/scripts/cross_company.py`
- `compare-reports/scripts/cross_period.py`
- `financial-analysis/scripts/fetch_financial_csv.py`
- `financial-analysis/scripts/peer_compare.py`
- `financial-analysis/scripts/ratio_analysis.py`
- `read-pdf/scripts/build_index.py`
- `read-pdf/scripts/fetch_financial_data.py`
- `read-pdf/scripts/fetch_report_pdf.py`
- `read-pdf/scripts/parse_pdf_basic.py`
- `read-pdf/scripts/parse_pdf_ocr.py`
- `read-pdf/scripts/query_report.py`
- `sentiment-analysis/scripts/event_detector.py`
- `sentiment-analysis/scripts/news_fetcher.py`
- `sentiment-analysis/scripts/sentiment_scorer.py`
- `stock-price/scripts/get_kline.py`
- `web-search/scripts/search_market.py`
- `write-report/scripts/five_step_analysis.py`
- `write-report/scripts/prompts.py`
- `write-report/scripts/report_generator.py`

> 注：`bond-credit-review/SKILL.md` 中 Step 2 引用 `bond_credit_review.py`，但 `agent_config/skills/bond-credit-review/` 目录下仅有 SKILL.md，并无 scripts 子目录。这是文档与实现不一致问题，与本报告的 nanobot 残留主题相关度低，作为附带发现记录。

### 2.2 检查方法

1. **逐文件人工审阅**：完整读取 4 个核心 Python 文件、8 个 SKILL.md、18 个脚本文件，记录所有 nanobot 风格残留点。
2. **关键字检索**：使用 Grep 在 `agent/skills/` 与 `agent_config/skills/` 下检索 `nanobot`、`always`、`when_to_use`、`fallback`、`camelCase`、`subprocess`、`import` 等关键字，做交叉验证。
3. **10 项特征逐项核对**：按照任务定义的 10 项 nanobot 风格特征，逐项标注是否残留并评估严重程度。
4. **区分注释残留 vs 实现逻辑残留**：注释残留指 docstring/注释中提到 nanobot；实现逻辑残留指代码或 frontmatter 字段在功能层面消费 nanobot 风格机制。

## 3. 逐文件检查结果

### 3.1 `agent/skills/loader.py`

| 项目 | 数量 |
|---|---|
| 注释残留数 | 9 |
| 实现逻辑残留数 | 4 |

**注释残留详情**：
- L2: `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader`
- L29-31: `对标 nanobot: agent/skills.py SkillsLoader: list_skills / load_skill / _parse_frontmatter; PyYAML 解析 + fallback 简单解析`
- L48: `"""技能元数据 — 对标 Cline frontmatter + nanobot metadata`
- L96: `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader`
- L167: `对标 nanobot: load_skill() + _strip_frontmatter()`
- L222: `解析 SKILL.md 文件 — 对标 nanobot get_skill_metadata()`
- L393: `# Fallback: 简单 YAML 解析 — 对标 nanobot fallback`
- L423: `去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()`
- L70 注释: `always: bool = False  # 是否始终加载指令（Level 2）`

**实现逻辑残留详情**：
1. **L70 `always` 字段**（中）：`SkillMetadata.always: bool = False`，nanobot 独有的预加载机制，Cline 无此概念。
2. **L81 `when_to_use` 字段**（中）：`SkillMetadata.when_to_use: str = ""`，注释 L79-80 自己也承认"对标 Cline SKILL.md frontmatter 的 description 字段中隐含的'何时使用'语义"——也就是说 Cline 不需要此字段，应通过 description 内嵌 "Use when..." 句式表达。这是 nanobot 风格字段。
3. **L282 `when_to_use` 解析逻辑**（中）：`when_to_use = str(frontmatter.get("when_to_use", ""))`，从 frontmatter 读取该字段。
4. **L384-420 PyYAML fallback 简单解析**（中-高）：`try: import yaml; ... except Exception: pass`，随后是手写的"简单 YAML 解析"。注释 L393 明确说"对标 nanobot fallback"。这是 nanobot 风格的 try/except + fallback 错误处理，且违反用户规则"代码中不要有 fallback"。Cline 原生直接用 yaml 解析，没有自己写 fallback。

### 3.2 `agent/skills/registry.py`

| 项目 | 数量 |
|---|---|
| 注释残留数 | 4 |
| 实现逻辑残留数 | 4 |

**注释残留详情**：
- L2: `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader`
- L20-22: `对标 nanobot: build_skills_summary(): XML 格式技能列表; get_always_skills(): always=True 的技能`
- L100: `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader`
- L184: `获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()`

**实现逻辑残留详情**：
1. **L183-191 `get_always_skills()` 方法**（高）：完整实现 always=True 技能名称列表返回。这是 nanobot 独有机制，Cline 无此概念。
2. **L193-208 `load_always_instructions()` 方法**（高）：完整实现加载所有 always=True 技能的指令，注入 system prompt。
3. **L272-285 `load_always_instructions_as_rule()` 方法**（高）：将 always 技能指令包装为 rule 格式供 system prompt 增强层使用。这三个方法共同构成 always 预加载机制的实现。
4. **L245-250 `build_summary()` 中使用 `when_to_use`**（中）：在技能摘要中拼接 `when_to_use` 字段，使其成为 system prompt 的一部分。这使 nanobot 风格字段在生产环境中被消费。

### 3.3 `agent/skills/skill_tool.py`

| 项目 | 数量 |
|---|---|
| 注释残留数 | 1 |
| 实现逻辑残留数 | 2 |

**注释残留详情**：
- L18-22: `这与 nanobot 的"子 agent 隔离执行"有本质区别: Cline skill 是"主上下文内的指令注入"; 不创建独立 runtime; 不限制工具集; 不用 attempt_completion 返回结果`（此处 nanobot 是作为反面对照，但仍是注释残留）

**实现逻辑残留详情**：
1. **L245-253 `_build_description()` 中 `except Exception: pass`**（低）：捕获异常后静默忽略，属于轻微的 fallback 行为。Cline 风格应让异常抛出或返回明确错误。
2. **L255-267 `configured_skills()` 中 `except Exception: return []`**（低）：同上，捕获异常后返回空列表。

### 3.4 `agent/skills/__init__.py`

| 项目 | 数量 |
|---|---|
| 注释残留数 | 1 |
| 实现逻辑残留数 | 0 |

**注释残留详情**：
- L1: `"""技能系统 — 对标 Cline skills + nanobot SkillsLoader`
- L23-26: `对标 nanobot: agent/skills.py: SkillsLoader 类; frontmatter 解析: PyYAML + fallback; build_skills_summary(): XML 格式技能列表`

**实现逻辑残留详情**：无（仅导出类，无逻辑实现）。

### 3.5 SKILL.md 文件汇总

| SKILL.md | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| bond-credit-review/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L59）；"## 脚本调用规则"（L65）；"## 禁止行为"（L70） |
| compare-reports/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L56）；"## 脚本调用规则"（L62）；"## 禁止行为"（L74） |
| financial-analysis/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L85）；"## 脚本调用规则"（L93）；"## 禁止行为"（L107） |
| read-pdf/SKILL.md | 0 | 5 | frontmatter `when_to_use`（L4）+ `always: true`（L5）；正文"## 脚本角色说明"（L73）；"## 脚本调用规则"（L87）；"## 禁止行为"（L118） |
| sentiment-analysis/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L73）；"## 脚本调用规则"（L81）；"## 禁止行为"（L87） |
| stock-price/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L49）；"## 脚本调用规则"（L55）；"## 禁止行为"（L61） |
| web-search/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L58）；"## 脚本调用规则"（L64）；"## 禁止行为"（L70） |
| write-report/SKILL.md | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L81）；"## 脚本调用规则"（隐含在 Step 中）；"## 禁止行为"（L98） |
| **小计** | 0 | 33 | — |

**说明**：
- `when_to_use` 字段：8 个 SKILL.md 全部命中，是 nanobot 风格字段。Cline 用 description 内嵌 "Use when..." 句式。
- `always: true` 字段：仅 read-pdf/SKILL.md 命中，是 nanobot 独有预加载机制。Cline 无此概念。
- "脚本角色说明 / 脚本调用规则 / 禁止行为"三段式章节：8 个 SKILL.md 全部命中。这是 nanobot 风格的指令文档结构，Cline 用 Workflow 步骤内嵌说明。

### 3.6 脚本文件汇总

| 脚本文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| read-pdf/scripts/parse_pdf_ocr.py | 0 | 1 | `_pdf_page_to_base64_fallback` 函数（L48, L66）：PyMuPDF 不可用时回退到 pdf2image。属于依赖回退，工程上合理但属于 try/except + fallback 模式 |
| sentiment-analysis/scripts/sentiment_scorer.py | 0 | 1 | L198 `"fallback": True`：LLM 解析失败时手动计算基础统计作为 fallback。属于 nanobot 风格的 try/except + fallback |
| read-pdf/scripts/fetch_report_pdf.py | 0 | 0 | 用 `subprocess.Popen` 调用 preprocess.py（Cline 风格），无残留 |
| write-report/scripts/five_step_analysis.py | 0 | 0 | `from prompts import FIVE_STEP_CONFIG` 是同目录内部模块导入，不属于脚本间 import 残留 |
| 其他 14 个脚本 | 0 | 0 | 未发现 nanobot 风格残留 |
| **小计** | 0 | 2 | — |

**说明**：脚本层面的 nanobot 残留较少，主要因为脚本本身是命令行工具，通过 `argparse + main()` 模式组织，天然符合 Cline 的 subprocess 调用模型。脚本内部用 dict 作为返回值属于 Python 常见做法，不计入 nanobot 风格。

## 4. nanobot 风格特征逐项检查

### 4.1 函数命名：camelCase 或特定前缀
- **是否残留**：否
- **严重程度**：无
- **检查依据**：Grep `def [a-z]+[A-Z]\w*` 在所有脚本中无匹配。所有函数均使用 snake_case 命名，符合 Cline/Python 风格。

### 4.2 数据结构：dict 而非 dataclass
- **是否残留**：否
- **严重程度**：无
- **检查依据**：`SkillMetadata` 使用 `@dataclass`（loader.py L46-82），符合 Cline 风格。脚本中用 dict 作为返回值是 Python 函数返回多值的常见做法，不属于 nanobot 风格。

### 4.3 错误处理：try/except + fallback
- **是否残留**：是
- **严重程度**：中
- **检查依据**：
  - `loader.py` L384-420：PyYAML 失败时 fallback 到手写简单 YAML 解析，注释明确"对标 nanobot fallback"
  - `parse_pdf_ocr.py` L43-48, L66-86：PyMuPDF 不可用时 fallback 到 pdf2image
  - `sentiment_scorer.py` L127-146, L180-200：LLM 解析失败时 fallback 到手动统计
  - `skill_tool.py` L250, L267：`except Exception: pass/return []` 静默 fallback
- **备注**：其中 PyYAML fallback 违反用户规则"代码中不要有 fallback"，且与 Cline 原生实现不一致。其余 fallback 属于工程合理性回退，但风格上仍可识别为 nanobot 特征。

### 4.4 配置加载：JSON 而非 YAML
- **是否残留**：否
- **严重程度**：无
- **检查依据**：SKILL.md frontmatter 使用 YAML（符合 Cline）。脚本中用 `json.load/json.dump` 是作为输出结果存储格式，属于合理使用，不是配置加载。

### 4.5 脚本调用：直接 import 而非 subprocess
- **是否残留**：否
- **严重程度**：无
- **检查依据**：
  - `fetch_report_pdf.py` L176-184：用 `subprocess.Popen` 调用 `preprocess.py`，符合 Cline 风格
  - `five_step_analysis.py` L31-32：`from prompts import FIVE_STEP_CONFIG` 是同目录内部模块导入（prompts.py 是 five_step_analysis.py 的内部 Prompt 模板拆分），不属于跨脚本 import 调用
  - 其他脚本均独立通过命令行执行，无相互 import 调用

### 4.6 返回格式：字符串而非 AgentToolResult
- **是否残留**：否
- **严重程度**：无
- **检查依据**：`skill_tool.py` 中 `_execute()` 返回 `AgentToolResult`（L133, L144, L155, L167, L178, L190, L215），符合 Cline 风格。脚本本身是命令行工具，输出 stdout 字符串是合理设计（因为是 subprocess 调用目标）。

### 4.7 注释风格：docstring 提到 nanobot
- **是否残留**：是
- **严重程度**：高（数量多）
- **检查依据**：4 个核心 Python 文件共有 15+ 处 docstring/注释明确提到 "nanobot" 字样。详见第 3 节逐文件检查结果。

### 4.8 always 预加载机制（nanobot 独有，Cline 无）
- **是否残留**：是
- **严重程度**：高（实现层面有 always 机制）
- **检查依据**：
  - `loader.py` L70：`SkillMetadata.always: bool = False` 字段定义
  - `loader.py` L234：`always = bool(frontmatter.get("always", False))` 解析逻辑
  - `loader.py` L288：`always=always` 传入 SkillMetadata 构造
  - `registry.py` L183-191：`get_always_skills()` 方法实现
  - `registry.py` L193-208：`load_always_instructions()` 方法实现
  - `registry.py` L272-285：`load_always_instructions_as_rule()` 方法实现
  - `read-pdf/SKILL.md` L5：`always: true` frontmatter 字段
- **备注**：这是 nanobot 独有的预加载机制，Cline skills.mdx 中无此概念。Cline 的 Level 1/2/3 渐进式加载机制中，Level 2 加载由 LLM 通过 use_skill 工具主动触发，不存在"always 预加载"。

### 4.9 when_to_use 字段（nanobot 风格，Cline 用 description 内 "Use when ..." 句式）
- **是否残留**：是
- **严重程度**：高
- **检查依据**：
  - `loader.py` L81：`SkillMetadata.when_to_use: str = ""` 字段定义
  - `loader.py` L79-80 注释自己也承认："对标 Cline SKILL.md frontmatter 的 description 字段中隐含的'何时使用'语义"——即 Cline 不需要此字段
  - `loader.py` L282：`when_to_use = str(frontmatter.get("when_to_use", ""))` 解析逻辑
  - `loader.py` L297：`when_to_use=when_to_use` 传入 SkillMetadata 构造
  - `registry.py` L245-250：`build_summary()` 中拼接 `when_to_use` 到技能摘要
  - 8 个 SKILL.md frontmatter 全部有 `when_to_use` 字段
- **备注**：Cline 风格应将"何时使用"语义内嵌到 description 字段中（"Use when ..."句式），而非单独字段。

### 4.10 脚本角色说明 / 脚本调用规则 / 禁止行为 章节（nanobot 风格，Cline 用 Workflow 步骤内嵌）
- **是否残留**：是
- **严重程度**：高
- **检查依据**：8 个 SKILL.md 全部命中：
  - bond-credit-review/SKILL.md: L59, L65, L70
  - compare-reports/SKILL.md: L56, L62, L74
  - financial-analysis/SKILL.md: L85, L93, L107
  - read-pdf/SKILL.md: L73, L87, L118
  - sentiment-analysis/SKILL.md: L73, L81, L87
  - stock-price/SKILL.md: L49, L55, L61
  - web-search/SKILL.md: L58, L64, L70
  - write-report/SKILL.md: L81, L98
- **备注**：Cline 风格应将这些规则内嵌到 Workflow 步骤的描述中（如"Step 1: ...（注意：股票代码必须带交易所后缀）"），而非单独成章节。

## 5. 残留汇总表

### 5.1 注释残留 vs 实现逻辑残留

| 文件/类别 | 注释残留数 | 实现逻辑残留数 | 总计 |
|---|---|---|---|
| agent/skills/loader.py | 9 | 4 | 13 |
| agent/skills/registry.py | 4 | 4 | 8 |
| agent/skills/skill_tool.py | 1 | 2 | 3 |
| agent/skills/__init__.py | 1 | 0 | 1 |
| 8 个 SKILL.md | 0 | 33 | 33 |
| 18 个脚本 | 0 | 2 | 2 |
| **合计** | **15** | **45** | **60** |

### 5.2 按严重程度分类

| 严重程度 | 注释残留 | 实现逻辑残留 | 总计 | 典型项目 |
|---|---|---|---|---|
| 高 | 0 | 28 | 28 | always 机制（7 处）、when_to_use 字段（11 处）、三段式章节（24 处）|
| 中 | 0 | 8 | 8 | PyYAML fallback（1 处）、其他 when_to_use 消费（2 处）、脚本 fallback（2 处）等 |
| 低 | 15 | 9 | 24 | docstring 提到 nanobot（15 处）、except Exception 静默（2 处）等 |

### 5.3 按 nanobot 风格特征分类

| 特征编号 | 特征名称 | 是否残留 | 残留数 | 严重程度 |
|---|---|---|---|---|
| 1 | camelCase 命名 | 否 | 0 | 无 |
| 2 | dict 而非 dataclass | 否 | 0 | 无 |
| 3 | try/except + fallback | 是 | 5 | 中 |
| 4 | JSON 而非 YAML | 否 | 0 | 无 |
| 5 | import 而非 subprocess | 否 | 0 | 无 |
| 6 | 字符串而非 AgentToolResult | 否 | 0 | 无 |
| 7 | docstring 提到 nanobot | 是 | 15 | 高 |
| 8 | always 预加载机制 | 是 | 7 | 高 |
| 9 | when_to_use 字段 | 是 | 11 | 高 |
| 10 | 三段式章节 | 是 | 24 | 高 |

## 6. 修复建议

### 6.1 P0 优先级（高严重程度，影响功能行为）

#### P0-1: 移除 always 预加载机制
**影响范围**：
- `agent/skills/loader.py` L70（字段定义）、L234（解析）、L288（构造）、L70 注释
- `agent/skills/registry.py` L183-191（`get_always_skills`）、L193-208（`load_always_instructions`）、L272-285（`load_always_instructions_as_rule`）
- `agent_config/skills/read-pdf/SKILL.md` L5（`always: true`）

**修复方案**：
1. 从 `SkillMetadata` 移除 `always` 字段
2. 从 `_parse_skill_file` 移除 `always` 解析逻辑
3. 从 `SkillRegistry` 移除 `get_always_skills()`、`load_always_instructions()`、`load_always_instructions_as_rule()` 三个方法
4. 从 read-pdf/SKILL.md 移除 `always: true` frontmatter 字段
5. 全局搜索 `load_always_instructions`、`get_always_skills`、`load_always_instructions_as_rule` 的调用点，移除或改造为 Cline 风格的 use_skill 工具触发加载

**验证**：搜索 `always` 关键字应无残留；技能系统功能测试通过。

#### P0-2: 移除 when_to_use 字段
**影响范围**：
- `agent/skills/loader.py` L79-81（字段定义）、L282（解析）、L297（构造）
- `agent/skills/registry.py` L245-250（`build_summary` 中使用）
- 8 个 SKILL.md frontmatter 的 `when_to_use` 字段

**修复方案**：
1. 将 8 个 SKILL.md 中的 `when_to_use` 内容合并到 `description` 字段中，采用 Cline 风格的 "Use when ..." 句式
2. 从 `SkillMetadata` 移除 `when_to_use` 字段
3. 从 `_parse_skill_file` 移除 `when_to_use` 解析逻辑
4. 从 `build_summary()` 移除 `when_to_use` 拼接逻辑，仅展示 `description`

**示例**（read-pdf/SKILL.md frontmatter 修改前）：
```yaml
name: read-pdf
description: "查询上市公司年报/季报/公告等PDF叙述性内容，支持本地RAG查询；若本地无索引/PDF，自动下载并构建索引"
when_to_use: "用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"
```

**示例**（修改后，Cline 风格）：
```yaml
name: read-pdf
description: "查询上市公司年报/季报/公告等PDF叙述性内容，支持本地RAG查询；若本地无索引/PDF，自动下载并构建索引。Use when 用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"
```

#### P0-3: 重构 SKILL.md 三段式章节为 Workflow 内嵌
**影响范围**：8 个 SKILL.md 的"脚本角色说明 / 脚本调用规则 / 禁止行为"章节

**修复方案**：
1. 删除"## 脚本角色说明"章节，将脚本角色信息内嵌到对应 Step 的描述中（如"Step 2: 调用 XX 脚本（主脚本，agent 直接调用）"）
2. 删除"## 脚本调用规则"章节，将规则内嵌到对应 Step 的命令说明中（如在命令下方加 "> 注意：股票代码必须带交易所后缀"）
3. 删除"## 禁止行为"章节，将禁止事项分散到对应 Step 的"失败处理"或"跳过条件"中（Cline 风格用前置条件/失败处理表达约束）

**示例**（stock-price/SKILL.md 修改前）：
```markdown
## 脚本角色说明
本技能 scripts/ 目录下只有 1 个主脚本:
- `get_kline.py` — 获取 K 线行情数据，Step 1 使用

## 脚本调用规则
1. **股票代码必须带交易所后缀**: 如 `600519.SH`
2. **公司名称要转换**: 用户说"贵州茅台"时，先转换为 `600519.SH` 再调用
3. **不要用 web_search 查股价**: 本技能是查询股价的唯一正确途径

## 禁止行为
- 禁止用 `web_search` 查询股价/涨跌幅/K线数据（本技能是唯一途径）
```

**示例**（修改后，Cline 风格）：
```markdown
### Step 1: 获取 K 线数据
- **何时执行**: 用户询问股价/K线/走势/成交量时
- **前置条件**: MiniQMT 客户端已运行并登录
- **命令**:
  ```bash
  python agent_config/skills/stock-price/scripts/get_kline.py <股票代码> [周期] [条数]
  ```
- **参数约束**:
  - `<股票代码>` (必填): 带交易所后缀，如 `600519.SH`、`000858.SZ`、`688981.SH`。用户说公司名称时先转换为代码。
  - `[周期]` (可选): 默认 `1d`
  - `[条数]` (可选): 默认 `100`
- **预期输出**: K 线数据表格
- **失败处理**:
  - `xtquant not found` → 提示用户安装 xtquant 包
  - MiniQMT 连接失败 → 提示用户启动 MiniQMT 客户端
- **唯一性约束**: 本技能是查询股价的唯一正确途径，禁止用 `web_search` 查询股价/K线数据
```

### 6.2 P1 优先级（中严重程度，影响代码整洁度）

#### P1-1: 移除 PyYAML fallback 简单解析
**影响范围**：`agent/skills/loader.py` L384-420

**修复方案**：
1. 删除 L384-420 的 `try: import yaml; ... except Exception: pass` + 手写简单 YAML 解析
2. 直接使用 PyYAML，若 PyYAML 不可用则抛出明确异常（`ImportError: PyYAML is required to parse SKILL.md frontmatter`）
3. 同步更新 docstring，移除"对标 nanobot fallback"等注释

**理由**：用户规则明确"代码中不要有 fallback"。Cline 原生实现也直接用 yaml 解析。手写 fallback 维护成本高且易出 bug。

#### P1-2: 清理 docstring 中的 nanobot 对标说明
**影响范围**：4 个核心 Python 文件共 15 处

**修复方案**：
1. 移除所有"对标 nanobot"、"nanobot SkillsLoader"、"nanobot fallback"等注释
2. 保留"对标 Cline"部分（这是有价值的对照说明）
3. 对于必要的历史对比（如 skill_tool.py L18-22 关于"与 nanobot 子 agent 隔离执行的区别"），可改写为"Cline skill 是主上下文内的指令注入，不创建独立 runtime"——直接陈述 Cline 设计，不提 nanobot

### 6.3 P2 优先级（低严重程度，工程优化）

#### P2-1: 重构脚本 fallback 为明确错误
**影响范围**：
- `parse_pdf_ocr.py` L43-48, L66-86（PyMuPDF → pdf2image fallback）
- `sentiment_scorer.py` L127-146, L180-200（LLM 解析失败 → 手动统计 fallback）
- `skill_tool.py` L250, L267（`except Exception: pass/return []`）

**修复方案**：
- `parse_pdf_ocr.py`：保留依赖回退（工程合理），但改写为显式依赖检测（`try import fitz; except ImportError: raise RuntimeError("需要安装 PyMuPDF 或 pdf2image 之一")`）
- `sentiment_scorer.py`：保留 LLM 失败时的手动统计（业务合理），但移除 `"fallback": True` 标记，改为 `"aggregation_method": "manual_stat"` 等中性描述
- `skill_tool.py`：将 `except Exception: pass` 改为 `except Exception as e: logger.warning("...", e)`，记录日志而非静默忽略

### 6.4 P3 优先级（附带发现，非 nanobot 残留）

#### P3-1: bond-credit-review 脚本缺失
**影响范围**：`agent_config/skills/bond-credit-review/SKILL.md` L43-46 引用 `bond_credit_review.py`，但目录下无 scripts 子目录

**修复方案**：补建 `agent_config/skills/bond-credit-review/scripts/bond_credit_review.py` 脚本，或修改 SKILL.md 移除对该脚本的引用。

#### P3-2: write-report/SKILL.md 中 report_generator.py 参数描述与代码不一致
**影响范围**：`write-report/SKILL.md` L72-79 描述 `report_generator.py` 参数为 `--stock` 和 `--title`，但实际代码（`write-report/scripts/report_generator.py` L161-164）参数为 `--analysis_file` 和 `--output_dir`

**修复方案**：更新 SKILL.md 中的命令示例与参数说明，与代码保持一致。

## 7. 验证方法建议

### 7.1 自动化验证

1. **关键字检索验证**：
   ```powershell
   # 期望：无匹配
   Grep pattern="nanobot" path="agent/skills"
   Grep pattern="nanobot" path="agent_config/skills"
   Grep pattern="when_to_use" path="agent/skills"
   Grep pattern="when_to_use" path="agent_config/skills"
   Grep pattern="always" path="agent/skills"
   Grep pattern="always:\s*true" path="agent_config/skills"
   Grep pattern="脚本角色说明|脚本调用规则|禁止行为" path="agent_config/skills"
   ```

2. **导入与单元测试**：
   ```powershell
   python -c "from agent.skills import SkillLoader, SkillRegistry, SkillsTool, SkillMetadata; print('OK')"
   python -m pytest tests/skills/ -v
   ```

3. **SKILL.md frontmatter 校验**：
   ```powershell
   python -c "
   from agent.skills.loader import SkillLoader
   loader = SkillLoader('agent_config/skills')
   for s in loader.list_skills():
       assert not s.always, f'{s.name} still has always=True'
       assert not s.when_to_use, f'{s.name} still has when_to_use'
       print(f'{s.name}: OK')
   "
   ```

### 7.2 功能验证

1. **技能加载验证**：启动 agent，确认 8 个技能均能通过 `skills` 工具加载指令。
2. **read-pdf 技能验证**：确认移除 `always: true` 后，read-pdf 技能不再自动注入 system prompt，而是通过 `skills` 工具按需加载。
3. **技能摘要验证**：调用 `SkillRegistry.build_summary()`，确认输出中不再包含 `when_to_use` 列。
4. **LLM 行为验证**：让 LLM 执行 stock-price 技能任务，确认 LLM 能从 Workflow Step 1 中正确获取"股票代码必须带交易所后缀"的约束（验证三段式章节重构后规则仍可被 LLM 理解）。

### 7.3 回归验证

1. 运行现有技能系统测试套件（如存在）。
2. 执行一轮完整的研报生成任务（write-report 技能），确认研报正文输出正常。
3. 执行一轮财报查询任务（financial-analysis 技能），确认 CSV 下载与指标计算正常。

---

## 附录：检查覆盖声明

- 4 个核心 Python 文件：100% 完整审阅
- 8 个 SKILL.md 文件：100% 完整审阅
- 18 个脚本文件：100% 完整审阅（其中 `prompts.py` 为 Prompt 模板文件，无逻辑实现）
- 10 项 nanobot 风格特征：100% 逐项核对

本报告未修改任何源码，仅输出审计报告文件。
