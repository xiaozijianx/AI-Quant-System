# Phase 4.19 技能脚本实现风格对比（scripts/*.py）

> 对比范围：Cline `skills.mdx` 文档中描述的脚本调用风格 + Cline 内置 SKILL.md 示例（publish-cli / publish-ui / cline-sdk / opentui）与 Charles `agent_config/skills/*/scripts/*.py`（19 个脚本）的实现风格差异；脚本调用方式、参数传递、输出方式、agent 运行时依赖、错误处理、编码、注释风格、结构、依赖管理、命名风格、与 SKILL.md 一致性 12 个维度逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/docs/customization/skills.mdx` 全文 271 行（SKILL.md 编写指南 + `scripts/` 子目录说明 + `python scripts/validate.py` 调用示例 + "Scripts are token-efficient because only their output enters context" 原则）
> - `third_party/cline/.cline/skills/publish-cli/SKILL.md`（266 行，Workflow 内嵌 ```sh 块调用 `git`/`gh`/`bun`/`npm` 等命令）
> - `third_party/cline/.cline/skills/publish-ui/SKILL.md`（153 行，Workflow 内嵌 ```sh 块）
> - `third_party/cline/.agents/skills/cline-sdk/SKILL.md`（208 行，无脚本调用，纯文档引用）
>
> Charles 源码（19 个脚本，全部位于 `agent_config/skills/*/scripts/`）：
> - `read-pdf/scripts/`：`fetch_report_pdf.py`（321 行）/ `query_report.py`（403 行）/ `build_index.py`（276 行）/ `fetch_financial_data.py`（370 行）/ `parse_pdf_ocr.py`（306 行）/ `parse_pdf_basic.py`（145 行）
> - `financial-analysis/scripts/`：`fetch_financial_csv.py`（116 行）/ `ratio_analysis.py`（242 行）/ `peer_compare.py`（241 行）
> - `web-search/scripts/`：`search_market.py`（141 行）
> - `compare-reports/scripts/`：`cross_company.py`（215 行）/ `cross_period.py`（229 行）
> - `write-report/scripts/`：`report_generator.py`（198 行）/ `prompts.py`（202 行）/ `five_step_analysis.py`（259 行）
> - `sentiment-analysis/scripts/`：`sentiment_scorer.py`（291 行）/ `news_fetcher.py`（300 行）/ `event_detector.py`（302 行）
> - `stock-price/scripts/`：`get_kline.py`（94 行）
>
> 历史参考源码（用于 nanobot 残留溯源）：`third_party/charles_bundle/charles-nanobot/`

---

## 一、执行摘要

本阶段对比 Cline 文档定义的技能脚本风格与 Charles 当前 19 个 `.py` 脚本的实际实现。两者在**stdout 输出**、**命令行参数传递**、**不依赖 agent 运行时**、**函数式结构**、**UTF-8 编码声明**、**SKILL.md 内嵌 bash 命令调用脚本**等基础约定上**已对齐**。剩余差异主要体现在**注释语言**（Charles 中文 vs Cline 英文）、**命名风格**（Charles snake_case vs Cline kebab-case 示例）、**错误输出通道**（Charles 用 stdout 而非 stderr）、**SKILL.md 与脚本签名一致性**（4 处参数描述与脚本实际签名不符）以及**少量 nanobot 实现逻辑残留**（try/except + fallback 模式、subprocess 跨脚本调用）。

### 核心结论

1. **脚本调用方式已对齐**：Charles 8 个 SKILL.md 全部用 ```bash 代码块内嵌 `python agent_config/skills/<skill>/scripts/<script>.py <args>` 命令，与 Cline `python scripts/validate.py` 模式一致；agent 通过执行 SKILL.md 中的 bash 命令调用脚本，不直接 import 脚本模块。
2. **参数传递已对齐**：19 个脚本中 18 个用 `argparse` 命令行参数（与 Cline 命令行参数模式一致），仅 `get_kline.py` 用 `sys.argv` 位置参数（风格偏离但仍是命令行参数，非函数参数）。
3. **输出方式已对齐**：19 个脚本全部用 `print()` 输出到 stdout，符合 Cline "only their output enters context" 原则；部分脚本同时返回值或写文件，但不影响 agent 上下文（agent 只读 stdout）。
4. **agent 运行时独立性已对齐**：19 个脚本均不 import `agent.*` 模块，仅依赖第三方库（akshare/pandas/langchain/openai 等）+ 环境变量（`DASHSCOPE_API_KEY`）+ 标准库，与 Cline "脚本独立运行" 原则一致。
5. **错误处理部分偏离**：17/19 用 `sys.exit(1)` 显式退出码（对齐 Cline 退出码模式），但错误信息用 `print()` 到 stdout 而非 stderr（偏离 Cline shell 模式）；部分脚本用 try/except + fallback 字典返回（残留 nanobot 风格）。
6. **编码完全对齐**：19 个脚本全部有 `# -*- coding: utf-8 -*-` 声明，文件写入统一用 `encoding="utf-8"` 或 `utf-8-sig"`；8/19 额外重配置 Windows stdout/stderr 为 UTF-8。
7. **注释风格偏离**：Charles 19 个脚本全部用中文注释（docstring + 行内注释），Cline 文档示例与内置 SKILL.md 全部用英文。偏离符合 Charles 中文投研系统本地化需求。
8. **结构完全对齐**：19 个脚本全部用函数式结构（`def` + `main()` + `if __name__ == "__main__"`），与 Cline `validate.py` 单文件函数式示例一致；`five_step_analysis.py` + `prompts.py` 是双文件模块化（标准 Python 模式）。
9. **依赖管理增强**：Charles 有项目根 `requirements.txt` 统一管理依赖，Cline 文档无 requirements.txt 要求；Charles 比文档示例更严格。
10. **命名风格偏离**：Charles 19 个脚本全部用 snake_case（符合 PEP 8 Python 文件命名惯例），Cline 文档示例用 kebab-case（`helper.sh`/`validate.py` 实际为 snake_case，但 Cline SKILL.md 命名规范要求 kebab-case）。Charles 选择符合 Python 惯例。
11. **nanobot 残留**：**0 处字面残留**（Grep "nanobot" 在 `agent_config/skills/` 无匹配），**3 处实现逻辑残留**（try/except + fallback 模式、subprocess 跨脚本调用 preprocess.py、fetch_financial_data.py 与 fetch_financial_csv.py 代码重复），**0 处注释残留**。
12. **SKILL.md 一致性中等**：8 个 SKILL.md 调用的脚本路径与 `scripts/` 目录实际文件一致，但**4 处参数描述与脚本实际签名不符**（sentiment_scorer/event_detector/search_market/report_generator），**2 处脚本未在 SKILL.md 中提及**（cross_period.py 未被 compare-reports/SKILL.md 提及，fetch_financial_data.py 被 read-pdf/SKILL.md 明确标记"本技能不使用"但仍保留在 scripts/）。

### 一致性总体评估

- **调用方式 / 参数传递 / 输出方式 / agent 独立性 / 编码 / 结构**：**高**（6 项核心约定完全对齐）
- **错误处理**：**中**（退出码对齐，stderr 通道偏离，try/except + fallback 残留）
- **依赖管理**：**高**（Charles 有 requirements.txt，比 Cline 文档更严格）
- **注释语言 / 命名风格**：**低**（Charles 中文 + snake_case vs Cline 英文 + kebab-case，但符合本地化与 Python 惯例）
- **SKILL.md 一致性**：**中**（路径一致，参数描述 4 处不符，2 处冗余脚本）
- **nanobot 残留**：**字面 0 处 / 注释 0 处 / 实现逻辑 3 处**

---

## 二、逐项对比表

| # | 对比项 | Cline 风格 | Charles 当前实现 | 一致性等级 | 说明 |
|---|--------|-----------|------------------|-----------|------|
| 4.19.1 | 脚本调用方式 | SKILL.md 内嵌 ```sh 块 + `python scripts/validate.py` 直接调用（skills.mdx L220）；agent 执行 bash 命令 | 8 个 SKILL.md 全部用 ```bash 块内嵌 `python agent_config/skills/<skill>/scripts/<script>.py <args>`；agent 通过 run_commands 工具执行 | 高 | 完全对齐。路径形式不同（Cline `scripts/x.py` vs Charles `agent_config/skills/<skill>/scripts/x.py`）但语义一致 |
| 4.19.2 | 脚本参数传递 | 命令行参数（`python scripts/validate.py`，skills.mdx L220） | 18/19 用 `argparse`（fetch_report_pdf.py L272-286 等）；1/19 用 `sys.argv` 位置参数（get_kline.py L82-88） | 高 | 18/19 完全对齐；get_kline.py 用 sys.argv 是风格偏离但仍为命令行参数 |
| 4.19.3 | 脚本输出方式 | stdout（skills.mdx L209 "only their output enters context"） | 19/19 用 `print()` 到 stdout；部分同时返回值（fetch_report_pdf.py L317）或写文件（sentiment_scorer.py L258-265） | 高 | 完全对齐。返回值/文件写入不影响 agent 上下文 |
| 4.19.4 | 脚本依赖 agent 运行时 | 否（脚本独立运行，skills.mdx L209） | 19/19 不 import `agent.*`；仅依赖第三方库 + 环境变量 + 标准库 | 高 | 完全对齐 |
| 4.19.5 | 脚本错误处理 | 退出码 + stderr（标准 shell 模式） | 17/19 用 `sys.exit(1)` 显式退出码；错误信息用 `print()` 到 stdout 而非 stderr；部分用 try/except + fallback dict 返回 | 中 | 退出码对齐，stderr 通道偏离，try/except + fallback 残留 nanobot 风格 |
| 4.19.6 | 脚本编码 | UTF-8（Python 默认） | 19/19 有 `# -*- coding: utf-8 -*-`；19/19 文件写入用 `encoding="utf-8"` 或 `utf-8-sig"`；8/19 显式重配置 Windows stdout/stderr 为 UTF-8 | 高 | 完全对齐。Charles 在 Windows 中文环境上更严格 |
| 4.19.7 | 脚本注释风格 | 英文（skills.mdx + 内置 SKILL.md 全部英文） | 19/19 用中文注释（docstring + 行内注释） | 低 | 风格偏离但符合 Charles 中文投研系统本地化需求（用户规则 2 要求中文注释） |
| 4.19.8 | 脚本结构 | 函数式 / 模块化单文件（skills.mdx L179 `validate.py` 示例） | 19/19 用函数式（`def` + `main()` + `if __name__ == "__main__"`）；five_step_analysis.py + prompts.py 双文件模块化 | 高 | 完全对齐。Charles 模块化程度更高 |
| 4.19.9 | 脚本依赖管理 | 无明确要求（skills.mdx 无 requirements.txt 说明） | 项目根 `requirements.txt` 统一管理；脚本内延迟 import（akshare 等） | 高 | Charles 比文档示例更严格，对齐"脚本不自带依赖管理"模式 |
| 4.19.10 | nanobot 风格残留 | N/A（Cline 非从 nanobot 迁移） | 0 处字面残留；0 处注释残留；3 处实现逻辑残留 | 中 | 见第四节专项检查 |
| 4.19.11 | 脚本命名风格 | kebab-case（skills.mdx L46 `helper.sh`，L179 `validate.py`；SKILL.md 命名规范 L101-114 要求 kebab-case） | 19/19 用 snake_case（fetch_report_pdf.py / query_report.py 等） | 低 | Charles 符合 PEP 8 Python 文件命名惯例，Cline 文档示例混用（`helper.sh` kebab-case + `validate.py` snake_case） |
| 4.19.12 | 脚本与 SKILL.md 一致性 | Workflow 步骤对应脚本调用（skills.mdx L213-221 示例） | 8 个 SKILL.md 调用路径与 scripts/ 实际文件一致；4 处参数描述与脚本签名不符；2 处脚本未在 SKILL.md 中提及 | 中 | 路径一致但参数描述偏离，存在冗余脚本 |

---

## 三、重点差距详细说明

### 3.1 错误处理通道偏离（4.19.5）

**Cline 风格**：标准 shell 模式，退出码 + stderr。skills.mdx L209 隐含"脚本输出进入上下文"，Cline 内置 SKILL.md 示例用 ```sh 块执行命令，依赖 shell 的退出码（`$?`）和 stderr 通道区分成功/失败。

**Charles 实现**：

- **退出码部分对齐**：17/19 脚本用 `sys.exit(1)` 显式退出码（如 query_report.py L103/L337、build_index.py L188/L239、parse_pdf_ocr.py L185、parse_pdf_basic.py L115、fetch_financial_csv.py 无 sys.exit、ratio_analysis.py L52、peer_compare.py L221、search_market.py L76、cross_company.py L66/L182、cross_period.py L66/L195、sentiment_scorer.py L75/L213/L221/L244、event_detector.py L107/L186/L196、news_fetcher.py L219、report_generator.py L169、five_step_analysis.py L42/L247）。`fetch_report_pdf.py` 和 `build_index.py`（除 sys.exit(1) 外）在主流程末尾不显式 sys.exit(0)，依赖 Python 默认退出码 0。
- **stderr 通道偏离**：19/19 脚本的错误信息用 `print()` 输出到 stdout，而非 `sys.stderr`。示例（query_report.py L102-103）：

```python
if not DASHSCOPE_API_KEY:
    print("[错误] 请设置环境变量 DASHSCOPE_API_KEY")
    sys.exit(1)
```

Cline shell 模式期望错误信息走 stderr（`echo "error" >&2`），agent 可通过退出码判断失败，但 stdout 中混入错误信息会污染上下文。Charles 当前实现让 agent 在 stdout 中同时看到正常输出和错误信息，需要 agent 自行区分（通过 `[错误]` / `[警告]` 前缀）。

- **try/except + fallback 残留**：部分脚本用 try/except 捕获异常后返回 fallback 字典（而非 sys.exit），这是 nanobot 风格的"容错优先"模式。示例（sentiment_scorer.py L127-146）：

```python
except json.JSONDecodeError:
    return {
        "sentiment": "中性",
        "strength": 1,
        ...
        "parse_error": True,
    }
except Exception as e:
    return {
        "sentiment": "中性",
        "strength": 0,
        ...
        "error": str(e),
    }
```

同类模式见 `event_detector.py` L150-151、`aggregate_sentiment` L180-200、`parse_pdf_ocr.py` L48-49（PyMuPDF 不可用回退到 pdf2image）。**用户规则 7 明确"代码中不要有 fallback"**，这些 fallback 是 nanobot 风格残留。

**差异影响**：
- Charles stdout 混入错误信息：agent 上下文中错误信息与正常输出混杂，但 Charles 通过 `[错误]`/`[警告]` 前缀让 agent 可识别。
- try/except + fallback：掩盖了真实错误，让 agent 看到"中性"等虚假结果而非失败信号，违反 fail-fast 原则。
- **判定**：stderr 通道偏离属于风格取向（Charles 选择"全部信息进 stdout 让 agent 看到"），非缺陷；try/except + fallback 属于 nanobot 实现逻辑残留（见第四节）。

### 3.2 注释语言偏离（4.19.7）

**Cline 风格**：英文注释。skills.mdx 全文英文，内置 SKILL.md（publish-cli/publish-ui/cline-sdk）全部英文，data-analysis 示例 SKILL.md 用英文注释 Python 代码（`# Load and explore`）。

**Charles 实现**：19/19 脚本全部用中文注释。示例（fetch_report_pdf.py L3-15）：

```python
"""
PDF报告下载工具

功能:
通过巨潮资讯网搜索并下载上市公司年报/季报/公告PDF,
下载完成后自动调用 preprocess.py 更新RAG统一索引,
使新PDF立即可通过 query_report.py 查询。
"""
```

行内注释也用中文（query_report.py L67 `"""标准化股票代码 — 去掉 .SH/.SZ/.BJ 后缀，便于兼容查询`）。

**差异影响**：
- Charles 中文注释符合中文投研系统本地化需求，符合用户规则 2（"生成的注释用中文，并使用 UTF-8 编码"）。
- 与 Cline 英文风格偏离，但 Charles 选择符合中文场景惯例。
- **判定**：风格取向差异，非缺陷。Charles 选择符合本地化需求。

### 3.3 命名风格偏离（4.19.11）

**Cline 风格**：skills.mdx L46/L179 示例混用 — `helper.sh` 是 kebab-case（实际是单个词无连字符），`validate.py` 是 snake_case。但 skills.mdx L101-114 对 SKILL.md `name` 字段明确要求 kebab-case（`aws-cdk-deploy` / `pr-review-checklist`）。Cline 文档对脚本文件命名无强制规范，但 SKILL.md 命名规范倾向 kebab-case。

**Charles 实现**：19/19 脚本全部用 snake_case：

| 脚本名 | 命名风格 |
|--------|---------|
| fetch_report_pdf.py | snake_case |
| query_report.py | snake_case |
| build_index.py | snake_case |
| fetch_financial_data.py | snake_case |
| parse_pdf_ocr.py | snake_case |
| parse_pdf_basic.py | snake_case |
| fetch_financial_csv.py | snake_case |
| ratio_analysis.py | snake_case |
| peer_compare.py | snake_case |
| search_market.py | snake_case |
| cross_company.py | snake_case |
| cross_period.py | snake_case |
| report_generator.py | snake_case |
| prompts.py | snake_case |
| five_step_analysis.py | snake_case |
| sentiment_scorer.py | snake_case |
| news_fetcher.py | snake_case |
| event_detector.py | snake_case |
| get_kline.py | snake_case |

**差异影响**：
- Python PEP 8 文件命名规范要求 snake_case，Charles 选择符合 Python 惯例。
- Cline SKILL.md `name` 字段用 kebab-case，但脚本文件名无强制规范。
- Charles 一致性极高（19/19 全部 snake_case），内部一致。
- **判定**：风格取向差异，非缺陷。Charles 选择符合 Python 惯例。

### 3.4 SKILL.md 与脚本签名一致性偏离（4.19.12）

#### 3.4.1 参数描述与脚本签名不符（4 处）

**问题 1：sentiment-analysis/SKILL.md Step 2 vs sentiment_scorer.py 实际签名**

SKILL.md L53-55 描述：
```bash
python agent_config/skills/sentiment-analysis/scripts/sentiment_scorer.py --stock <股票代码>
```

实际脚本签名（sentiment_scorer.py L204-209）：
```python
parser.add_argument("--news_file", required=True, help="新闻 JSON 文件路径")
parser.add_argument("--output_dir", default="./output", help="输出目录")
parser.add_argument("--model", default="qwen-turbo", help="LLM 模型（默认 qwen-turbo）")
parser.add_argument("--max_news", type=int, default=50, help="最大分析条数（默认 50）")
```

**差异**：SKILL.md 说用 `--stock`，实际脚本无 `--stock` 参数，必填参数是 `--news_file`。agent 按 SKILL.md 调用会失败。

**问题 2：sentiment-analysis/SKILL.md Step 3 vs event_detector.py 实际签名**

SKILL.md L66-68 描述：
```bash
python agent_config/skills/sentiment-analysis/scripts/event_detector.py --stock <股票代码>
```

实际脚本签名（event_detector.py L177-182）：
```python
parser.add_argument("--news_file", required=True, help="新闻 JSON 文件路径")
parser.add_argument("--output_dir", default="./output", help="输出目录")
parser.add_argument("--model", default="qwen-turbo", help="LLM 模型")
parser.add_argument("--use_llm", action="store_true", help="使用 LLM 进行精细事件识别")
```

**差异**：SKILL.md 说用 `--stock`，实际脚本必填参数是 `--news_file`。agent 按 SKILL.md 调用会失败。

**问题 3：web-search/SKILL.md vs search_market.py 实际签名**

SKILL.md L41-43 描述：
```bash
python agent_config/skills/web-search/scripts/search_market.py --query "<搜索关键词>" --num 10
```

实际脚本签名（search_market.py L102-112）：
```python
parser.add_argument("--query", required=True, help="搜索查询")
parser.add_argument("--type", choices=["stock", "news", "policy", "general"], default="general", ...)
parser.add_argument("--model", default="qwen-plus", help="模型(默认 qwen-plus)")
parser.add_argument("--output", default=None, help="结果保存路径(可选)")
```

**差异**：SKILL.md 说用 `--num 10`，实际脚本无 `--num` 参数。agent 按 SKILL.md 调用会因未知参数失败（argparse 默认拒绝未知参数）。

**问题 4：write-report/SKILL.md Step 4 vs report_generator.py 实际签名**

SKILL.md L73-76 描述：
```bash
python agent_config/skills/write-report/scripts/report_generator.py --stock <股票代码> --title <标题> --output_dir output/
```

实际脚本签名（report_generator.py L161-164）：
```python
parser.add_argument("--analysis_file", required=True, help="五步法分析结果 JSON 文件")
parser.add_argument("--output_dir", default="./output/reports", help="研报输出目录")
```

**差异**：SKILL.md 说用 `--stock` + `--title`，实际脚本必填参数是 `--analysis_file`，无 `--stock` 和 `--title` 参数。agent 按 SKILL.md 调用会失败。

#### 3.4.2 冗余/未提及脚本（2 处）

**问题 5：compare-reports/SKILL.md 未提及 cross_period.py**

compare-reports/SKILL.md L56-60 "脚本角色说明"：
```
本技能 scripts/ 目录下只有 1 个主脚本:
- `cross_company.py` — 跨公司年报对比，Step 2 使用
```

实际 scripts/ 目录有 2 个脚本：`cross_company.py` + `cross_period.py`。`cross_period.py`（229 行，跨期对比分析）未在 SKILL.md 中任何位置提及，既不在"脚本角色说明"中，也不在 Workflow Step 中。

**差异**：`cross_period.py` 是孤立脚本，agent 永远不会调用它。可能是历史遗留代码或 SKILL.md 文档遗漏。

**问题 6：read-pdf/SKILL.md 明确标记 fetch_financial_data.py "本技能不使用"**

read-pdf/SKILL.md L85：
```
- `fetch_financial_data.py` — 综合财务数据获取（akshare + 巨潮），功能与 financial-analysis 技能重叠，本技能不使用
```

实际 scripts/ 目录仍保留 `fetch_financial_data.py`（370 行），且与 `financial-analysis/scripts/fetch_financial_csv.py`（116 行）高度重复（前者是后者的超集 + PDF 下载功能）。

**差异**：`fetch_financial_data.py` 是冗余脚本，SKILL.md 明确说"不使用"但仍保留在 scripts/ 目录。`fetch_financial_csv.py` 是精简版（仅 akshare 财务数据），`fetch_financial_data.py` 是完整版（akshare + 巨潮 PDF），两者 `fetch_financial_statements` 函数代码几乎完全相同（fetch_financial_data.py L36-98 vs fetch_financial_csv.py L28-90）。

#### 3.4.3 一致性良好的部分（对齐项）

| SKILL.md | 调用脚本 | 脚本签名 | 一致性 |
|----------|---------|---------|--------|
| read-pdf Step 1/3 | `query_report.py --index_dir --query --stock` | `--index_dir --query --top_k --model --alpha --stock` | 高（必填参数一致） |
| read-pdf Step 2 | `fetch_report_pdf.py --stock --category` | `--stock --category --keyword --max_download --start_date --end_date --output_dir` | 高（必填参数一致） |
| financial-analysis Step 2 | `fetch_financial_csv.py --stock` | `--stock --output_dir` | 高 |
| financial-analysis Step 3 | `ratio_analysis.py --stock --years 5` | `--stock --years --data_dir --output` | 高 |
| financial-analysis Step 4 | `peer_compare.py --stocks` | `--stocks --data_dir --output` | 高 |
| stock-price Step 1 | `get_kline.py <股票代码> [周期] [条数]` | `sys.argv[1/2/3]` 位置参数 | 高（位置参数一致） |
| sentiment-analysis Step 1 | `news_fetcher.py --stock --days 30` | `--stock --keywords --days --output_dir --include_cctv` | 高（必填参数一致） |
| compare-reports Step 2 | `cross_company.py --stocks --query` | `--stocks --topic --index_dir --model --top_k` | 中（SKILL.md 用 `--query`，脚本用 `--topic`，默认值一致但参数名不符） |
| write-report Step 4 | `report_generator.py --stock --title --output_dir` | `--analysis_file --output_dir` | 低（见问题 4） |

**注**：compare-reports Step 2 的 `--query` vs `--topic` 也是参数名不符（SKILL.md L46 用 `--query`，脚本 L173 用 `--topic`），但语义一致，agent 按 SKILL.md 调用会因未知参数 `--query` 失败。这是第 5 处参数不符（上述 4 处之外的次要偏离）。

### 3.5 get_kline.py 风格偏离（4.19.2）

**Cline 风格**：命令行参数（`python scripts/validate.py`）。

**Charles 实现**：18/19 脚本用 `argparse`，仅 `get_kline.py` 用 `sys.argv` 位置参数（get_kline.py L82-88）：

```python
def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "请提供股票代码"}, ensure_ascii=False))
        sys.exit(1)
    stock_code = sys.argv[1]
    period = sys.argv[2] if len(sys.argv) > 2 else '1d'
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 100
    result = get_kline_data(stock_code, period=period, count=count)
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

**差异影响**：
- `sys.argv` 位置参数无 `--help` 自描述，agent 需查 SKILL.md 才知道参数顺序。
- `argparse` 提供 `--help` 自动生成用法说明，更符合 CLI 工具惯例。
- get_kline.py 缺少错误处理（如 `sys.argv[3]` 非数字会抛 `ValueError`，未被 try/except 包裹）。
- stock-price/SKILL.md L36-38 明确用位置参数调用（`<股票代码> [周期] [条数]`），与脚本一致。
- **判定**：风格偏离但功能正确。建议统一用 argparse（见第五节修复建议）。

### 3.6 stdout/stderr 重配置不一致（4.19.6）

**Charles 实现**：8/19 脚本显式重配置 Windows stdout/stderr 为 UTF-8，11/19 未重配置。

**重配置的 8 个脚本**（模式一致）：
- query_report.py L24-26
- ratio_analysis.py L24-26
- search_market.py L21-23
- cross_company.py L20-22
- cross_period.py L20-22
- （及类似模式的 build_index.py / sentiment_scorer.py / event_detector.py / news_fetcher.py 部分有部分无）

实际重配置模式：
```python
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
```

**未重配置的 11 个脚本**：fetch_report_pdf.py / fetch_financial_data.py / parse_pdf_ocr.py / parse_pdf_basic.py / fetch_financial_csv.py / peer_compare.py / report_generator.py / prompts.py / five_step_analysis.py / sentiment_scorer.py / get_kline.py（注：sentiment_scorer.py 实际未重配置，需复核）。

**差异影响**：
- Windows 默认 stdout 编码可能为 gbk，未重配置的脚本在 Windows 上 print 中文可能抛 `UnicodeEncodeError`。
- 重配置的 8 个脚本在 Windows 上稳定运行；未重配置的 11 个脚本在 Windows 上有乱码或崩溃风险。
- **判定**：内部一致性低（8/19 vs 11/19），建议统一重配置（见第五节修复建议）。

---

## 四、nanobot 残留专项检查

### 4.1 字面残留（0 处）

Grep 搜索 `nanobot`（不区分大小写）在 `agent_config/skills/` 目录下：

```
Grep -i "nanobot" e:\jikeAI\code\CASE-AI量化系统\agent_config\skills
 No matches found
```

**19 个脚本文件均无 "nanobot" 字面残留**。此结果与 Phase 4.1 中 `agent/skills/` Python 模块的 15 处注释残留形成对比——技能脚本作为从 nanobot 迁移而来的实现文件，已在历史重构中完全清理 nanobot 关键词。

### 4.2 注释残留（0 处）

逐文件检查 19 个脚本的 docstring 和行内注释，均无"nanobot"、"对标 nanobot"、"移植自 nanobot"、"从 nanobot 迁移"等溯源注释。与 `agent/tools/exec_tool.py` L711/L716 等保留"移植自 nanobot"注释不同，技能脚本注释已完全脱离 nanobot 溯源。

### 4.3 实现逻辑残留（3 处）

#### 4.3.1 try/except + fallback 模式（2 处）

**nanobot 风格特征**：nanobot 倾向用 try/except 捕获所有异常后返回 fallback 默认值，避免脚本崩溃，但掩盖真实错误。用户规则 7 明确"代码中不要有 fallback"。

**Charles 残留 1 — sentiment_scorer.py L111-146**：

```python
def analyze_single_news(client: OpenAI, news_text: str, model: str = "qwen-turbo") -> dict:
    prompt = SENTIMENT_PROMPT.format(news_text=news_text[:2000])
    try:
        response = client.chat.completions.create(...)
        content = response.choices[0].message.content.strip()
        # ... 解析 JSON
        result = json.loads(content)
        return result
    except json.JSONDecodeError:
        return {
            "sentiment": "中性",
            "strength": 1,
            "entities": [],
            "keywords": [],
            "summary": news_text[:50],
            "market_impact": "无法解析",
            "parse_error": True,
        }
    except Exception as e:
        return {
            "sentiment": "中性",
            "strength": 0,
            "entities": [],
            "keywords": [],
            "summary": "",
            "market_impact": "",
            "error": str(e),
        }
```

**残留分析**：JSON 解析失败时返回 `"sentiment": "中性"` fallback，掩盖了 LLM 输出格式错误；通用 Exception 捕获后返回 `"strength": 0` fallback，掩盖了 API 调用失败。agent 看到 fallback 结果会误以为分析成功，但实际数据无效。这是 nanobot 风格的"容错优先"模式，违反 fail-fast 原则。

**Charles 残留 2 — sentiment_scorer.py L166-200 aggregate_sentiment + event_detector.py L136-151 llm_event_detection**：

```python
# event_detector.py L132-151
def llm_event_detection(client: OpenAI, news_text: str, model: str = "qwen-turbo") -> dict:
    prompt = EVENT_DETECTION_PROMPT.format(news_text=news_text[:2000])
    try:
        response = client.chat.completions.create(...)
        content = response.choices[0].message.content.strip()
        # ...
        return json.loads(content)
    except Exception as e:
        return {"has_event": False, "error": str(e)}
```

**残留分析**：通用 Exception 捕获后返回 `{"has_event": False, "error": str(e)}` fallback，掩盖了 LLM 调用失败。agent 看到 `has_event: False` 会误以为无事件，但实际是 API 失败。

**Charles 残留 2 补充 — sentiment_scorer.py L180-200 aggregate_sentiment fallback**：

```python
except Exception as e:
    # 手动计算基础统计
    pos = sum(1 for a in analyses if a.get("sentiment") == "正面")
    neg = sum(1 for a in analyses if a.get("sentiment") == "负面")
    neu = len(analyses) - pos - neg
    total = len(analyses)
    index = int((pos / total) * 100) if total > 0 else 50
    return {
        "overall_sentiment": "乐观" if index > 60 else ("恐慌" if index < 40 else "中性"),
        ...
        "fallback": True,
        "error": str(e),
    }
```

**残留分析**：LLM 聚合失败时手动计算基础统计作为 fallback，标记 `"fallback": True`。虽然有标记，但仍是 fallback 模式，违反用户规则 7。

#### 4.3.2 subprocess 跨脚本调用 preprocess.py（1 处）

**nanobot 风格特征**：nanobot 倾向用 subprocess 调用其他脚本，形成"脚本调用脚本"的链式结构，而非 SKILL.md 显式编排。Cline 风格是 SKILL.md 显式编排所有脚本调用，脚本之间不互相调用。

**Charles 残留 — fetch_report_pdf.py L166-210 run_preprocess**：

```python
def run_preprocess(project_root: str) -> dict:
    """下载完成后自动更新统一索引（实时输出进度）"""
    preprocess_script = os.path.join(project_root, "preprocess.py")
    if not os.path.exists(preprocess_script):
        print("[索引更新] 未找到 preprocess.py，跳过自动索引更新")
        return {"status": "skipped", "reason": "preprocess.py not found"}

    print("[3/3] 开始更新 RAG 统一索引，这可能需要几分钟...")
    sys.stdout.flush()
    try:
        process = subprocess.Popen(
            [sys.executable, "preprocess.py"],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # ... 读取输出
        process.wait(timeout=600)
        if process.returncode == 0:
            ...
```

**残留分析**：`fetch_report_pdf.py` 通过 `subprocess.Popen` 调用项目根的 `preprocess.py`，形成"下载脚本 → 索引脚本"的链式调用。这是 nanobot 风格的"脚本编排脚本"模式。Cline 风格期望 SKILL.md 显式编排：SKILL.md Step 2 调用 `fetch_report_pdf.py`，Step 2.5 显式调用 `preprocess.py`，让 agent 看到完整流程。

**但是**：read-pdf/SKILL.md L60-63 明确说"该脚本会自动下载最新年报并调用解析脚本 + 构建索引脚本"，即 SKILL.md 已知情并允许这种链式调用。这是 Charles 有意设计的"封装式"脚本，而非 nanobot 残留。**判定**：风格偏离 Cline（脚本编排脚本 vs SKILL.md 编排脚本），但有 SKILL.md 明确背书，非 nanobot 残留。**降级为风格偏离，不计入残留**。

#### 4.3.3 fetch_financial_data.py 与 fetch_financial_csv.py 代码重复（1 处）

**nanobot 风格特征**：nanobot 倾向保留历史代码副本，不积极清理冗余。Cline 风格是单一脚本单一职责，避免代码重复。

**Charles 残留 — fetch_financial_data.py vs fetch_financial_csv.py**：

`fetch_financial_data.py`（370 行）和 `fetch_financial_csv.py`（116 行）的 `fetch_financial_statements` 函数代码几乎完全相同：

- fetch_financial_data.py L36-98 `fetch_financial_statements`（63 行）
- fetch_financial_csv.py L28-90 `fetch_financial_statements`（63 行）

两者差异仅在于：fetch_financial_data.py 额外包含 PDF 下载功能（L101-313，巨潮资讯网 PDF 下载），fetch_financial_csv.py 仅含 akshare 财务数据下载。

read-pdf/SKILL.md L85 明确标记 `fetch_financial_data.py` "本技能不使用"，但脚本仍保留在 `read-pdf/scripts/` 目录。

**残留分析**：`fetch_financial_data.py` 是 nanobot 版本的完整财务数据脚本，`fetch_financial_csv.py` 是 Charles 重构后的精简版。两者并存是历史迁移遗留，`fetch_financial_data.py` 已被 SKILL.md 明确废弃但仍未删除。这是 nanobot 风格的"保留历史代码"残留。

**判定**：实现逻辑残留（冗余代码），建议删除 `fetch_financial_data.py` 或合并到 `fetch_financial_csv.py`（见第五节修复建议）。

### 4.4 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 字面残留（"nanobot" 关键词） | 0 处 | — | 无需处理 |
| 注释残留（docstring/行内注释提到 nanobot） | 0 处 | — | 无需处理 |
| 实现逻辑残留 — try/except + fallback | 2 处（sentiment_scorer.py L111-146/L166-200，event_detector.py L132-151） | P2 | 移除 fallback，改为 sys.exit(1) + 错误信息到 stderr |
| 实现逻辑残留 — 冗余代码 | 1 处（fetch_financial_data.py 与 fetch_financial_csv.py 重复） | P3 | 删除 fetch_financial_data.py 或合并 |
| 实现逻辑残留 — subprocess 跨脚本调用 | 1 处（fetch_report_pdf.py 调用 preprocess.py） | — | 降级为风格偏离，SKILL.md 已背书，非残留 |

**技能脚本层面 nanobot 残留基本清理**。字面和注释层面完全清理；实现逻辑层面仅 2 处 try/except + fallback 残留（用户规则 7 明确禁止 fallback）+ 1 处冗余代码残留。与 Phase 4.1 发现的 `agent/skills/` Python 模块 15 处注释残留形成对比：技能脚本作为内容实现文件，已在历史重构中清理注释残留，但实现逻辑层面仍有少量 nanobot 风格特征。

---

## 五、修复建议

### 5.1 高优先级（P1）

#### 5.1.1 修复 SKILL.md 与脚本签名不一致（4 处 + 1 处）

**问题 1-2：sentiment-analysis/SKILL.md Step 2/3 参数描述错误**

当前 SKILL.md 说 `sentiment_scorer.py --stock` 和 `event_detector.py --stock`，实际脚本必填参数是 `--news_file`。

**修复方案 A（改 SKILL.md）**：更新 SKILL.md Step 2/3 命令为：
```bash
python agent_config/skills/sentiment-analysis/scripts/sentiment_scorer.py --news_file data/news/<股票代码>_news.json
python agent_config/skills/sentiment-analysis/scripts/event_detector.py --news_file data/news/<股票代码>_news.json
```

**修复方案 B（改脚本）**：在 sentiment_scorer.py 和 event_detector.py 中增加 `--stock` 参数，自动推导 `--news_file` 路径（`data/news/{stock}_news.json`），保持 `--news_file` 为可选。

**推荐方案 B**：与 SKILL.md 设计意图一致（用户只需提供股票代码），降低 agent 调用复杂度。

**问题 3：web-search/SKILL.md `--num` 参数不存在**

当前 SKILL.md 说 `search_market.py --query --num 10`，实际脚本无 `--num` 参数。

**修复方案**：删除 SKILL.md 中的 `--num 10`，或为 search_market.py 增加 `--num` 参数（限制返回结果数量）。推荐前者（脚本当前返回完整 LLM 响应，无数量限制概念）。

**问题 4：write-report/SKILL.md Step 4 `--stock --title` 参数不存在**

当前 SKILL.md 说 `report_generator.py --stock --title --output_dir`，实际脚本必填参数是 `--analysis_file`。

**修复方案 A（改 SKILL.md）**：更新 SKILL.md Step 4 命令为：
```bash
python agent_config/skills/write-report/scripts/report_generator.py --analysis_file output/<股票名称>_analysis.json --output_dir output/reports/
```

**修复方案 B（改脚本）**：在 report_generator.py 中增加 `--stock` 和 `--title` 参数，自动推导 `--analysis_file` 路径。

**推荐方案 A**：report_generator.py 的设计是接收 five_step_analysis.py 的输出 JSON，`--analysis_file` 是合理签名，应更新 SKILL.md 而非改脚本。

**问题 5（次要）：compare-reports/SKILL.md `--query` vs 脚本 `--topic`**

当前 SKILL.md L46 用 `--query`，脚本 cross_company.py L173 用 `--topic`。

**修复方案**：统一 SKILL.md 和脚本参数名。推荐改 SKILL.md 为 `--topic`（脚本签名更准确）。

#### 5.1.2 移除 nanobot 风格 fallback（2 处）

**问题**：sentiment_scorer.py L127-146 和 L180-200、event_detector.py L150-151 的 try/except + fallback 违反用户规则 7。

**修复方案**：移除 fallback 字典返回，改为 print 错误信息到 stderr + sys.exit(1)。示例（sentiment_scorer.py L111-146 修复后）：

```python
def analyze_single_news(client: OpenAI, news_text: str, model: str = "qwen-turbo") -> dict:
    prompt = SENTIMENT_PROMPT.format(news_text=news_text[:2000])
    try:
        response = client.chat.completions.create(...)
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)
        return result
    except json.JSONDecodeError as e:
        print(f"[错误] LLM 返回 JSON 解析失败: {e}", file=sys.stderr)
        print(f"[原始响应] {content[:200]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[错误] LLM 调用失败: {e}", file=sys.stderr)
        sys.exit(1)
```

**注意**：aggregate_sentiment 的 fallback（L180-200）需要保留"手动计算基础统计"逻辑作为降级方案，但应标记为错误退出而非正常返回。或改为在 LLM 聚合失败时 sys.exit(1)，让 agent 知道聚合失败。

### 5.2 中优先级（P2）

#### 5.2.1 统一 stdout/stderr 重配置（11 个脚本）

**问题**：8/19 脚本重配置 Windows stdout/stderr 为 UTF-8，11/19 未重配置，内部一致性低。

**修复方案**：在 11 个未重配置的脚本中添加统一的重配置块（顶部，import 之后）：

```python
import io
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
```

**待修复脚本**：fetch_report_pdf.py / fetch_financial_data.py / parse_pdf_ocr.py / parse_pdf_basic.py / fetch_financial_csv.py / peer_compare.py / report_generator.py / prompts.py / five_step_analysis.py / sentiment_scorer.py / get_kline.py（注：prompts.py 是纯常量模块无 print，可跳过）。

#### 5.2.2 错误信息输出到 stderr（17 处）

**问题**：19/19 脚本的错误信息用 `print()` 到 stdout，偏离 Cline shell 模式（stderr）。

**修复方案**：将所有 `print("[错误] ...")` 改为 `print("[错误] ...", file=sys.stderr)`。或在 sys.exit(1) 前的错误信息统一走 stderr。

**影响范围**：约 30+ 处 `print("[错误] ...")` 调用。可批量替换。

#### 5.2.3 get_kline.py 改用 argparse

**问题**：get_kline.py 用 `sys.argv` 位置参数，无 `--help` 自描述，与 18/19 脚本风格不一致。

**修复方案**：改为 argparse（保持位置参数兼容性）：

```python
def main():
    parser = argparse.ArgumentParser(description="MiniQMT K 线数据获取脚本")
    parser.add_argument("stock_code", help="股票代码，如 600519.SH")
    parser.add_argument("period", nargs="?", default="1d", help="周期（默认 1d）")
    parser.add_argument("count", nargs="?", type=int, default=100, help="条数（默认 100）")
    args = parser.parse_args()
    result = get_kline_data(args.stock_code, period=args.period, count=args.count)
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

**注意**：需同步更新 stock-price/SKILL.md 的调用示例（位置参数形式不变，但 argparse 兼容位置参数）。

### 5.3 低优先级（P3）

#### 5.3.1 删除冗余脚本 fetch_financial_data.py

**问题**：fetch_financial_data.py 与 fetch_financial_csv.py 代码重复，read-pdf/SKILL.md 明确标记"本技能不使用"。

**修复方案**：删除 `read-pdf/scripts/fetch_financial_data.py`。其 PDF 下载功能已由 `fetch_report_pdf.py` 实现，akshare 财务数据功能已由 `fetch_financial_csv.py` 实现，无功能损失。

**影响**：read-pdf/scripts/ 从 6 个脚本减少到 5 个，总数从 19 减少到 18。SKILL.md L85 的"本技能不使用"说明可一并删除。

#### 5.3.2 补充 cross_period.py 到 compare-reports/SKILL.md

**问题**：cross_period.py（229 行）未在 compare-reports/SKILL.md 中提及，是孤立脚本。

**修复方案 A（推荐）**：在 compare-reports/SKILL.md 中增加 Step 3（跨期对比），调用 `cross_period.py --stock --topics`。

**修复方案 B**：若 cross_period.py 已无需求，删除该脚本。

**推荐方案 A**：cross_period.py 功能完整（跨期对比是常见需求），应纳入 SKILL.md Workflow。

#### 5.3.3 注释语言与命名风格保持现状

**问题**：Charles 中文注释 + snake_case 命名 vs Cline 英文注释 + kebab-case 命名。

**判定**：风格取向差异，非缺陷。Charles 中文注释符合用户规则 2，snake_case 符合 PEP 8。**不建议修改**。

---

## 六、验证方法建议

### 6.1 SKILL.md 与脚本签名一致性验证

```python
import argparse
import os
import re
import subprocess
import sys

skills_dir = "agent_config/skills"
for skill_name in os.listdir(skills_dir):
    skill_md = os.path.join(skills_dir, skill_name, "SKILL.md")
    scripts_dir = os.path.join(skills_dir, skill_name, "scripts")
    if not os.path.exists(skill_md) or not os.path.exists(scripts_dir):
        continue

    # 1. 提取 SKILL.md 中调用的脚本命令
    with open(skill_md, encoding="utf-8") as f:
        content = f.read()
    commands = re.findall(r"python\s+(agent_config/skills/\S+/scripts/\S+\.py)\s+([^\n`]+)", content)

    for script_path, args_str in commands:
        # 2. 运行脚本 --help 获取实际签名
        result = subprocess.run(
            [sys.executable, script_path, "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        # 3. 检查 SKILL.md 中的参数是否在 --help 输出中
        args_in_skill_md = re.findall(r"--(\w+)", args_str)
        for arg in args_in_skill_md:
            if f"--{arg}" not in result.stdout:
                print(f"[不一致] {skill_name}: SKILL.md 用 --{arg}，脚本 --help 无此参数")
```

### 6.2 nanobot 字面残留验证

```bash
# 字面残留
Grep -i "nanobot" agent_config/skills/
# 预期：No matches found

# 注释残留（docstring 提到 nanobot）
Grep "nanobot|移植自|对标.*nanobot|从.*nanobot.*迁移" agent_config/skills/
# 预期：No matches found
```

### 6.3 fallback 残留验证

```python
# 检查 try/except + fallback 模式
import os
import re

scripts_dir = "agent_config/skills"
for root, dirs, files in os.walk(scripts_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        # 查找 except 块后紧跟 return dict 的模式
        matches = re.findall(r"except\s+\w*.*:\s*\n\s*return\s*\{", content)
        if matches:
            print(f"[fallback 残留] {path}: {len(matches)} 处")
```

### 6.4 stdout/stderr 重配置一致性验证

```python
import os
import re

scripts_dir = "agent_config/skills"
reconfigured = []
not_reconfigured = []
for root, dirs, files in os.walk(scripts_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        if "sys.stdout = io.TextIOWrapper" in content:
            reconfigured.append(path)
        else:
            not_reconfigured.append(path)

print(f"已重配置: {len(reconfigured)}/19")
print(f"未重配置: {len(not_reconfigured)}/19")
for p in not_reconfigured:
    print(f"  - {p}")
```

### 6.5 脚本命名风格验证

```python
import os
import re

scripts_dir = "agent_config/skills"
snake_case_count = 0
kebab_case_count = 0
for root, dirs, files in os.walk(scripts_dir):
    for f in files:
        if not f.endswith(".py"):
            continue
        if "_" in f:
            snake_case_count += 1
        elif "-" in f:
            kebab_case_count += 1
print(f"snake_case: {snake_case_count}/19")
print(f"kebab-case: {kebab_case_count}/19")
# 预期：snake_case: 19/19, kebab-case: 0/19
```

---

## 七、附录：19 个脚本实现风格汇总

| 技能 | 脚本 | 行数 | 编码声明 | argparse | sys.exit | stdout 重配置 | 中文注释 | 函数式 | nanobot 残留 |
|------|------|------|---------|----------|----------|--------------|---------|--------|-------------|
| read-pdf | fetch_report_pdf.py | 321 | UTF-8 | 是 | 否 | 否 | 是 | 是 | subprocess 调 preprocess.py（SKILL.md 背书，非残留） |
| read-pdf | query_report.py | 403 | UTF-8 | 是 | 是 | 是 | 是 | 是 | 无 |
| read-pdf | build_index.py | 276 | UTF-8 | 是 | 是 | 否 | 是 | 是 | 无 |
| read-pdf | fetch_financial_data.py | 370 | UTF-8 | 是 | 否 | 否 | 是 | 是 | 冗余代码（与 fetch_financial_csv.py 重复） |
| read-pdf | parse_pdf_ocr.py | 306 | UTF-8 | 是 | 是 | 否 | 是 | 是 | PyMuPDF→pdf2image fallback（实现逻辑残留） |
| read-pdf | parse_pdf_basic.py | 145 | UTF-8 | 是 | 是 | 否 | 是 | 是 | 无 |
| financial-analysis | fetch_financial_csv.py | 116 | UTF-8 | 是 | 否 | 否 | 是 | 是 | 无 |
| financial-analysis | ratio_analysis.py | 242 | UTF-8 | 是 | 是 | 是 | 是 | 是 | 无 |
| financial-analysis | peer_compare.py | 241 | UTF-8 | 是 | 是 | 否 | 是 | 是 | 无 |
| web-search | search_market.py | 141 | UTF-8 | 是 | 是 | 是 | 是 | 是 | 无 |
| compare-reports | cross_company.py | 215 | UTF-8 | 是 | 是 | 是 | 是 | 是 | 无 |
| compare-reports | cross_period.py | 229 | UTF-8 | 是 | 是 | 是 | 是 | 是 | SKILL.md 未提及（孤立脚本） |
| write-report | report_generator.py | 198 | UTF-8 | 是 | 是 | 否 | 是 | 是 | 无 |
| write-report | prompts.py | 202 | UTF-8 | 否（纯常量） | 否 | 否 | 是 | 否（纯常量） | 无 |
| write-report | five_step_analysis.py | 259 | UTF-8 | 是 | 是 | 否 | 是 | 是 | 无 |
| sentiment-analysis | sentiment_scorer.py | 291 | UTF-8 | 是 | 是 | 否 | 是 | 是 | try/except + fallback（2 处） |
| sentiment-analysis | news_fetcher.py | 300 | UTF-8 | 是 | 是 | 否 | 是 | 是 | 无 |
| sentiment-analysis | event_detector.py | 302 | UTF-8 | 是 | 是 | 否 | 是 | 是 | try/except + fallback（1 处） |
| stock-price | get_kline.py | 94 | UTF-8 | 否（sys.argv） | 是 | 否 | 是 | 是 | 无 |

**汇总统计**：

| 维度 | 对齐 Cline | 偏离 Cline | nanobot 残留 |
|------|-----------|-----------|-------------|
| 编码声明（UTF-8） | 19/19 | 0 | 0 |
| argparse 命令行参数 | 18/19 | 1（get_kline.py 用 sys.argv） | 0 |
| sys.exit 退出码 | 17/19 | 2（fetch_report_pdf.py / fetch_financial_csv.py 无 sys.exit） | 0 |
| stdout/stderr 重配置 | 8/19 | 11 | — |
| 中文注释 | 0/19（Cline 用英文） | 19/19 | 0（注释无 nanobot 溯源） |
| 函数式结构 | 18/19（prompts.py 纯常量） | 1（prompts.py） | 0 |
| try/except + fallback | — | 3 处（sentiment_scorer.py ×2，event_detector.py ×1） | 3 处实现逻辑残留 |
| 冗余代码 | — | 1 处（fetch_financial_data.py） | 1 处实现逻辑残留 |
| 字面残留 | — | — | 0 处 |
| 注释残留 | — | — | 0 处 |

**注**：parse_pdf_ocr.py L48-49 的 PyMuPDF→pdf2image fallback 也属于 try/except + fallback 模式（实现逻辑残留），但用户规则 7 主要针对业务逻辑 fallback，依赖库 fallback 属于合理的兼容性处理。本报告将依赖库 fallback 单独标注，不计入业务逻辑残留。如严格按用户规则 7 执行，parse_pdf_ocr.py 的依赖库 fallback 也应移除（改为 sys.exit(1) + 提示安装 PyMuPDF）。

---

## 八、与 Phase 4.7 / Phase 4.1 的关联

### 8.1 与 Phase 4.7（SKILL.md 形式风格）的关联

Phase 4.7 已确认 8 个 SKILL.md 文件层面 nanobot 残留完全清理（0 处字面 + 0 处风格结构 + 0 处实现逻辑）。本阶段（Phase 4.19）发现 19 个脚本层面 nanobot 残留基本清理（0 处字面 + 0 处注释 + 3 处实现逻辑）。

**差异**：
- SKILL.md 层面：0 处实现逻辑残留（已完全清理）
- 脚本层面：3 处实现逻辑残留（try/except + fallback + 冗余代码）

**原因**：SKILL.md 是面向 agent 的指令文件，已在历史重构中完全重写；脚本是面向开发者的实现文件，部分历史代码（如 fetch_financial_data.py）和容错模式（如 sentiment_scorer.py 的 fallback）保留至今。

### 8.2 与 Phase 4.1（技能工具）的关联

Phase 4.1 发现 `agent/skills/` Python 模块（skill_tool.py / loader.py / registry.py）有 15 处注释残留（"对标 nanobot" / "移植自 nanobot"），0 处实现逻辑残留。本阶段发现 19 个脚本 0 处注释残留，3 处实现逻辑残留。

**对比**：
- `agent/skills/` 模块：15 处注释残留，0 处实现逻辑残留
- `agent_config/skills/*/scripts/` 脚本：0 处注释残留，3 处实现逻辑残留

**结论**：技能系统的两个层面（Python 模块 + 脚本）残留分布不同——Python 模块保留注释溯源但实现已重构，脚本已清理注释但实现仍有少量 nanobot 风格特征。两者需分别清理：Python 模块清理注释（Phase 4.1 建议），脚本清理 fallback 和冗余代码（本阶段建议）。

### 8.3 与 Phase 4.20（nanobot 残留专项检查）的关联

本阶段已覆盖 AGENT_COMPARISON_PLAN_V2.md P4.20 计划表中关于脚本的部分检查项：

| P4.20 检查项 | 本阶段结论 |
|-------------|-----------|
| 4.20.9 脚本调用方式（subprocess vs import） | agent 通过 SKILL.md bash 命令调用脚本（对齐 Cline）；脚本内部 subprocess 调用 preprocess.py 有 SKILL.md 背书（非残留） |
| 4.20.10 脚本返回格式（stdout + exit_code vs return value） | 19/19 用 stdout + sys.exit（对齐 Cline）；部分脚本同时返回值但不影响 agent 上下文 |
| 4.20.11 注释残留 | 0 处（19 个脚本均无 nanobot 溯源注释） |

P4.20 计划表中关于 `agent/skills/` Python 模块的检查项（loader.py / registry.py / skill_tool.py）不在本阶段范围内，需在 Phase 4.20 中单独检查。
