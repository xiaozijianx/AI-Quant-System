# Phase 6.10 AGENTS.md 与 SKILL.md 去重对比

> 对比范围：Cline `sdk/AGENTS.md` + `.cline/skills/*/SKILL.md` + `.agents/skills/*/SKILL.md` 的内容去重情况，与 Charles `agent_config/rules/AGENTS.md` + `agent_config/skills/*/SKILL.md`（8 个技能）的内容去重情况逐项对标；并对比 Charles AGENTS.md 与 `rules/general.md` 的职责分离；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md`（109 行，SDK 开发参考文档）
> - `third_party/cline/.cline/skills/publish-ui/SKILL.md`（158 行，UI 发布技能）
> - `third_party/cline/.cline/skills/publish-cli/SKILL.md`（266 行，CLI 发布技能）
> - `third_party/cline/.cline/skills/publish-desktop/SKILL.md`（127 行，桌面应用发布技能）
> - `third_party/cline/.agents/skills/cline-sdk/SKILL.md`（208 行，SDK 技能指南）
> - `third_party/cline/.agents/skills/create-pull-request/SKILL.md`（211 行，PR 创建技能）
> - `third_party/cline/.agents/skills/opentui/SKILL.md`（200 行，OpenTUI 技能）
> - `third_party/cline/sdk/.cline/skills/plugin.md`（892 行，插件开发技能）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md`（56 行，Agent 主规则）
> - `agent_config/rules/general.md`（35 行，通用规则）
> - `agent_config/skills/bond-credit-review/SKILL.md`（74 行）
> - `agent_config/skills/compare-reports/SKILL.md`（78 行）
> - `agent_config/skills/financial-analysis/SKILL.md`（112 行）
> - `agent_config/skills/read-pdf/SKILL.md`（125 行）
> - `agent_config/skills/sentiment-analysis/SKILL.md`（92 行）
> - `agent_config/skills/stock-price/SKILL.md`（66 行）
> - `agent_config/skills/web-search/SKILL.md`（76 行）
> - `agent_config/skills/write-report/SKILL.md`（105 行）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 与 SKILL.md 内容去重情况。**核心结论：Cline 通过"职责分离"实现天然去重（AGENTS.md 是仓库开发规范，SKILL.md 是任务执行指南，关注点完全不重叠）；Charles 的 AGENTS.md 与 SKILL.md 存在 4 处可识别的禁止行为重复，但属于"全局硬约束 + 技能上下文强化"的有意重复模式，非冗余残留。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.10（L2436-2452）标注"Charles 已对齐（Stage P5.3）：SKILL.md 移除与 AGENTS.md 重复的注意事项"。

**此标注与实际源码不符**：Charles 的 8 个 SKILL.md 中仍存在 4 处与 AGENTS.md 硬约束语义重复的禁止行为（详见三、3.2 节）。具体为：
- `financial-analysis/SKILL.md` L111 与 AGENTS.md L53 **完全字面重复**
- `stock-price/SKILL.md` L63 与 AGENTS.md L51 **语义重复**
- `web-search/SKILL.md` L72-74 与 AGENTS.md L51 **语义重复**（3 条）

### 核心结论

1. **Cline AGENTS.md 与 SKILL.md 职责完全分离**：Cline `sdk/AGENTS.md` 是"SDK 仓库开发规范"（包边界、依赖方向、变更路由、验证规则、文档责任），SKILL.md 是"特定任务执行指南"（发布流程、PR 创建、SDK 使用、TUI 开发）。**两者关注点零重叠，天然无重复**。
2. **Charles AGENTS.md 与 SKILL.md 职责有重叠**：Charles AGENTS.md 是"Agent 主规则"，包含跨技能的全局硬约束（如"禁止用 web_search 查股价"）；SKILL.md 是"技能指南"，在技能特定上下文中再次强调部分全局约束。**存在 4 处可识别的重复**。
3. **Charles AGENTS.md 与 general.md 已去重**：Charles AGENTS.md L56 明确"股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`"，把通用规则从 AGENTS.md 移到 general.md，**这部分去重已完成**。
4. **重复性质判断**：Charles 的 4 处重复属于 prompt 工程中常见的"重要事项多次强化"模式——AGENTS.md 全局强调，SKILL.md 技能上下文再次强调。**非 nanobot 残留，非冗余 bug，是有意设计**。
5. **nanobot 残留**：P6.10 范围内（AGENTS.md + 8 个 SKILL.md + general.md）**0 处残留**（注释残留 0、实现逻辑残留 0）。Charles AGENTS.md 已从 nanobot 工具名（exec/read_file）迁移到 Cline 工具名（run_commands/read_files）。

### 一致性总体评估

- **AGENTS.md 与 SKILL.md 去重**：**中**。Cline 天然零重复（职责分离），Charles 有 4 处有意强化重复。
- **AGENTS.md 与 general.md 去重**：**高**。Charles 已通过"注: ... 见 general.md"实现职责分离。
- **nanobot 残留清理**：**高**。AGENTS.md 和所有 SKILL.md 均无 nanobot 字样，工具名已迁移。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.10.1 | AGENTS.md 不含 SKILL.md 重复内容 | 是（sdk/AGENTS.md 是仓库开发规范，与 SKILL.md 任务指南零重叠） | 部分（AGENTS.md L40-47"工具选择原则"与各 SKILL.md"本技能核心能力"有路由信息重叠，但属必要路由非冗余） | 中 | Charles AGENTS.md 的"工具选择原则"是技能路由表，与 SKILL.md 的"核心能力"描述存在必要重叠（用于决策树路由），非冗余残留 |
| 6.10.2 | SKILL.md 不与 AGENTS.md 重复注意事项 | 是（Cline SKILL.md 的"Critical Rules"/"Release contract"等段落均为技能特定，不与 AGENTS.md 重复） | 部分（4 处重复：financial-analysis L111 完全重复，stock-price L63 / web-search L72-74 语义重复） | 中 | Charles 4 处重复属"全局约束 + 技能上下文强化"模式，非 nanobot 残留，但计划表标注"已对齐"与实际不符 |
| 6.10.3 | AGENTS.md 与 general.md 职责分离 | N/A（Cline sdk/AGENTS.md 无对应 general.md 概念） | 是（AGENTS.md L56 注释指向 general.md，通用规则已移出） | 高 | Charles 在 AGENTS.md/general.md 分离上做得清晰，AGENTS.md 只保留 Agent 主规则 |
| 6.10.4 | SKILL.md 注意事项技能特定性 | 是（每个 SKILL.md 的注意事项均针对该技能的脚本/参数/流程） | 是（8 个 SKILL.md 的注意事项多数为技能特定，仅 4 处与 AGENTS.md 全局约束重复） | 中-高 | Charles 多数注意事项已技能特定化，4 处重复是"全局约束在技能上下文强化"的合理设计 |
| 6.10.5 | 工具名风格（nanobot vs Cline） | Cline 原生（run_commands/read_files/search_codebase/editor） | Cline 风格（run_commands/read_files/search_codebase/editor/web_search） | 高 | Charles AGENTS.md 和所有 SKILL.md 均使用 Cline 风格工具名，无 nanobot 残留（exec/read_file 已清理） |
| 6.10.6 | nanobot 残留（注释 + 实现逻辑） | N/A | 0 处（AGENTS.md + 8 SKILL.md + general.md 全文无 nanobot 字样） | 高 | 完全清理 |

---

## 三、重点差距详解

### 3.1 Cline 的"职责分离"去重模式

Cline 的 AGENTS.md 与 SKILL.md 之间**天然零重复**，因为两者的关注点完全不同：

**Cline `sdk/AGENTS.md` 的内容结构**：
1. Repository Scope（仓库范围）
2. Package Boundaries（包边界：@cline/shared / @cline/llms / @cline/agents / @cline/core）
3. Dependency Direction（依赖方向）
4. Change Routing（变更路由：哪个包 owns 哪个 concern）
5. Verifying Changes（验证变更：bun install / build / test / types / check）
6. Practical Guidance（实践指导：保持边界清晰、重构标准）
7. Documentation Responsibilities（文档责任：README/CONTRIBUTING/AGENTS/ARCHITECTURE/DOC 各自职责）

**Cline SKILL.md 的内容结构**（以 publish-cli 为例）：
1. Release contract（发布契约：版本源、tag 命名、发布路径）
2. Step 0: Release the SDK first if changed（SDK 先于 CLI 发布）
3. Workflow（9 步发布流程：gather context → collect commits → draft notes → decide version → update files → verify → commit → publish → final report）
4. Error Handling（错误处理）
5. Summary Checklist（检查清单）

**对比**：Cline AGENTS.md 回答"在这个仓库中如何开发"，SKILL.md 回答"如何执行特定任务"。**两者职责正交，无任何内容重叠**。这是 Cline 通过"职责分离"实现的天然去重，无需显式去重操作。

### 3.2 Charles 的 4 处重复详解

Charles AGENTS.md L49-54 的"硬约束"段落：

```
## 硬约束（投研场景特有）

- 禁止用 web_search 查本地已有数据的股价、财报
- 禁止用 RAG 查结构化数字（存货金额、营收等）— 用 financial-analysis CSV
- 禁止用 read_files 读 data/parsed/ 下的切分文件（那是给 RAG 用的）
- 禁止用 run_commands 执行不存在的脚本
```

以下 4 处 SKILL.md 禁止行为与上述硬约束重复：

| # | SKILL.md 位置 | SKILL.md 内容 | 重复的 AGENTS.md 硬约束 | 重复类型 |
|---|--------------|--------------|------------------------|---------|
| 1 | `financial-analysis/SKILL.md` L111 | `禁止用 read_files 读 data/parsed/ 下的切分文件（那是给 RAG 用的）` | L53: `禁止用 read_files 读 data/parsed/ 下的切分文件（那是给 RAG 用的）` | **完全字面重复** |
| 2 | `stock-price/SKILL.md` L63 | `禁止用 web_search 查询股价/涨跌幅/K线数据（本技能是唯一途径）` | L51: `禁止用 web_search 查本地已有数据的股价、财报` | **语义重复**（股价/K线 ⊂ 股价、财报） |
| 3 | `web-search/SKILL.md` L72 | `禁止用 web_search 查询股价/K线数据（用 stock-price 技能）` | L51: `禁止用 web_search 查本地已有数据的股价、财报` | **语义重复**（股价/K线 ⊂ 股价、财报） |
| 4 | `web-search/SKILL.md` L73-74 | `禁止用 web_search 查询财务指标（用 financial-analysis 技能）` + `禁止用 web_search 查询年报内容（用 read-pdf 技能）` | L51: `禁止用 web_search 查本地已有数据的股价、财报` | **语义重复**（财务指标/年报 ⊂ 财报） |

**重复性质判断**：

这 4 处重复**不是 nanobot 残留**（无 nanobot 字样），**不是未清理的 bug**（内容正确），而是 prompt 工程中常见的"重要事项多次强化"模式：
- AGENTS.md 全局硬约束：作为 Agent 主规则，在所有场景下常驻生效
- SKILL.md 技能上下文强化：在技能特定上下文中再次强调，确保模型在加载技能后不会"忘记"全局约束

**设计合理性**：
- 在 RAG/prompt 工程中，重要约束在 system prompt（AGENTS.md）和 skill prompt（SKILL.md）中重复强调是**常见且推荐的实践**，因为模型的注意力机制对"当前上下文"更敏感，技能加载后全局约束可能被稀释
- 但过度重复会导致 prompt 冗长，影响 token 效率

**与 Cline 对比**：
- Cline 的 AGENTS.md 是"仓库开发规范"，不包含"禁止用某工具查某数据"这类业务约束
- Cline 的 SKILL.md 各自独立，不依赖全局约束强化
- Cline 的模式更"干净"，但 Charles 的模式更适合"投研场景特有"的业务约束强化

### 3.3 Charles AGENTS.md 与 general.md 的去重（已完成）

Charles AGENTS.md L56：
```
注: 股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`（由 rules_loader 自动加载）。
```

Charles `general.md` 内容：
- 输出格式（Markdown / 风险提示 / 来源标注 / 五步法）
- 时间基准（当前日期 / 年报披露规则 / 默认报告期）
- 工具调用规范（并行/串行 / 规划/调整 / schema 检查）
- 股票代码格式（沪/深/北交所 / get_kline.py 后缀规则 / CSV 文件名）

**对比 charles-nanobot 旧版 AGENTS.md**：
- 旧版 `third_party/charles_bundle/charles-nanobot/AGENTS.md` 包含"股票代码"段落（L23-27）和"输出"段落（L29-33）
- 新版 `agent_config/rules/AGENTS.md` **已移除**这两个段落，改为引用 `general.md`

**结论**：Charles 在 AGENTS.md 与 general.md 的去重上**已完成**，符合"AGENTS.md 只保留 Agent 主规则，通用规则移到 general.md"的职责分离原则。

### 3.4 Charles AGENTS.md 的"工具选择原则"与 SKILL.md 的"核心能力"重叠

Charles AGENTS.md L40-47 的"工具选择原则（按数据类型）"段落：
```
1. 结构化财务数字 → financial-analysis 技能（CSV 数据）
2. 年报叙述性内容 → read-pdf 技能（RAG 检索，可下载 PDF，无需用户提前准备文件）
3. 时效性信息（新闻、公告） → web_search 工具
4. 股价/K线数据 → stock-price 技能（MiniQMT 实时行情）
5. 撰写深度研报 → write-report 技能（五步法）
6. 通用文件/代码操作 → read_files / search_codebase / editor 工具
```

各 SKILL.md 的"本技能核心能力"段落：
- financial-analysis/SKILL.md L9-17: "本技能可自动下载上市公司结构化财务 CSV 数据..."
- read-pdf/SKILL.md L9-18: "本技能可自动下载上市公司年报 PDF 并解析为可检索文本..."
- stock-price/SKILL.md L9-12: "通过 MiniQMT 实时获取 A 股行情数据..."
- write-report/SKILL.md L9-14: "本技能直接在对话中输出 Markdown 格式研报..."

**重叠性质**：这是**必要的路由信息重叠**，非冗余：
- AGENTS.md 的"工具选择原则"是**决策树入口**（用户任务 → 选择哪个技能）
- SKILL.md 的"核心能力"是**技能说明**（这个技能做什么）

两者描述同一事物但从不同角度，AGENTS.md 是"路由表"，SKILL.md 是"技能说明书"。这种重叠是必要的，不应去重。

### 3.5 Charles AGENTS.md 工具名已从 nanobot 迁移到 Cline

**对比 charles-nanobot 旧版 AGENTS.md**：
- 旧版 L7: `必须先 read_file 对应的 skills/<技能名>/SKILL.md`（nanobot 工具名 `read_file`）
- 旧版 L17: `禁止用 exec 跑不存在的脚本`（nanobot 工具名 `exec`）
- 旧版 L19: `禁止用 read_file 读 data/parsed/`（nanobot 工具名 `read_file`）

**新版 Charles AGENTS.md**：
- L9-10: `使用 read_files/run_commands/web_search 等结构化工具`（Cline 工具名 `read_files`/`run_commands`/`web_search`）
- L27: `直接调用 read_files / search_codebase / editor 等工具`（Cline 工具名）
- L29: `直接调用 run_commands 工具`（Cline 工具名）
- L31: `直接调用 web_search 工具`（Cline 工具名）
- L53: `禁止用 read_files 读 data/parsed/`（Cline 工具名）
- L54: `禁止用 run_commands 执行不存在的脚本`（Cline 工具名）

**结论**：Charles AGENTS.md 的工具名**已完全从 nanobot 风格（exec/read_file）迁移到 Cline 风格（run_commands/read_files/search_codebase/editor/web_search）**，0 处工具名残留。这是"实现逻辑残留"层面的完全清理。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.10 范围内涉及以下 10 个文件：
- `agent_config/rules/AGENTS.md`（56 行）
- `agent_config/rules/general.md`（35 行）
- `agent_config/skills/bond-credit-review/SKILL.md`（74 行）
- `agent_config/skills/compare-reports/SKILL.md`（78 行）
- `agent_config/skills/financial-analysis/SKILL.md`（112 行）
- `agent_config/skills/read-pdf/SKILL.md`（125 行）
- `agent_config/skills/sentiment-analysis/SKILL.md`（92 行）
- `agent_config/skills/stock-price/SKILL.md`（66 行）
- `agent_config/skills/web-search/SKILL.md`（76 行）
- `agent_config/skills/write-report/SKILL.md`（105 行）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent_config/rules/AGENTS.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。工具名已从 nanobot 风格（exec/read_file）迁移到 Cline 风格（run_commands/read_files/search_codebase/editor/web_search） |
| `agent_config/rules/general.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。内容为通用规则（输出格式/时间基准/工具调用规范/股票代码格式），无 nanobot 工具名引用 |
| `bond-credit-review/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`（Cline 风格），无 nanobot 路径 |
| `compare-reports/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，无 nanobot 路径 |
| `financial-analysis/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，工具名用 `read_files`（Cline 风格） |
| `read-pdf/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，工具名用 `read_files`（Cline 风格） |
| `sentiment-analysis/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，无 nanobot 路径 |
| `stock-price/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，工具名用 `web_search`（Cline 风格） |
| `web-search/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，工具名用 `web_search`（Cline 风格） |
| `write-report/SKILL.md` | 0 处 | 0 处 | 全文无 "nanobot" 字样。脚本路径用 `agent_config/skills/...`，工具名用 `todo_write`（Cline 风格） |

**P6.10 范围内 nanobot 残留总计：0 处（注释 0 + 实现逻辑 0）。**

### 4.3 工具名迁移验证

对比旧版 `third_party/charles_bundle/charles-nanobot/AGENTS.md` 与新版 `agent_config/rules/AGENTS.md`：

| 工具用途 | 旧版 nanobot 工具名 | 新版 Cline 工具名 | 迁移状态 |
|---------|--------------------|------------------|---------|
| 读文件 | `read_file` | `read_files` | 已迁移 |
| 执行命令 | `exec` | `run_commands` | 已迁移 |
| 联网搜索 | `web_search` | `web_search` | 一致（无变化） |
| 搜索代码 | N/A | `search_codebase` | 新增（Cline 风格） |
| 编辑文件 | N/A | `editor` | 新增（Cline 风格） |

**结论**：Charles AGENTS.md 和所有 SKILL.md 的工具名**已完全迁移到 Cline 风格**，0 处 nanobot 工具名残留。

### 4.4 范围外残留说明

以下文件的 nanobot 残留**超出 P6.10 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/context.py` L275 | 注释残留 | docstring "nanobot 风格的额外段落" | P5.1（已记录） |
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/tools/base.py` L2/L11/L37/L188 | 注释残留 | docstring 提到 nanobot Tool 基类 | F-base（P7.19） |
| `agent/skills/loader.py` 多处 | 注释 + 实现残留 | docstring + fallback 解析逻辑 | P4.20（已审计） |

---

## 五、修复建议

### 5.1 高优先级：修正计划文件事实错误

**问题**：AGENT_COMPARISON_PLAN_V2.md L2444 标注"Charles 实现：SKILL.md 移除与 AGENTS.md 重复的注意事项"，L2448 对比表 6.10.1 标注"已对齐（Stage P5.3）"。

**实际源码核实结果**：Charles 8 个 SKILL.md 中仍有 4 处与 AGENTS.md 硬约束重复（详见三、3.2 节）：
- `financial-analysis/SKILL.md` L111（完全字面重复）
- `stock-price/SKILL.md` L63（语义重复）
- `web-search/SKILL.md` L72-74（3 条语义重复）

**修复**：将 L2444 改为：
```
- SKILL.md 保留与 AGENTS.md 重复的注意事项作为"全局约束 + 技能上下文强化"（4 处重复，属有意设计）
```

将 L2448 对比表改为：

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 6.10.1 | AGENTS.md 与 SKILL.md 去重 | 是（职责分离天然零重复） | 部分（4 处有意强化重复） | Charles 保留全局约束在技能上下文的强化重复 |

### 5.2 中优先级：评估 4 处重复是否需要清理（可选，非必须）

**问题**：Charles 4 处 SKILL.md 与 AGENTS.md 重复的禁止行为，是"全局约束 + 技能上下文强化"模式，但也增加 prompt token 消耗。

**修复建议（可选）**：根据以下原则评估是否清理：

1. **完全字面重复（1 处）建议保留**：`financial-analysis/SKILL.md` L111 与 AGENTS.md L53 完全相同。这条约束在 financial-analysis 技能上下文中强化"不要读 data/parsed/ 切分文件"是必要的，因为 financial-analysis 技能可能涉及读 CSV 文件，模型可能误读切分文件。保留作为强化。
2. **语义重复（3 处）建议保留**：`stock-price/SKILL.md` L63 和 `web-search/SKILL.md` L72-74 在技能上下文中强化"不要用 web_search 查股价/财报"是必要的，因为：
   - stock-price 技能加载后，模型需要明确"本技能是唯一途径"
   - web-search 技能加载后，模型需要明确"不要用本技能查股价/财报/年报"
   - 这些强化在技能上下文中比 AGENTS.md 全局约束更直接有效

**权衡**：
- **保留（推荐）**：4 处重复增加约 100 token，但显著提升技能上下文下的约束强度，符合 prompt 工程最佳实践
- **移除**：节省约 100 token，但可能降低技能上下文下的约束强度，模型在加载技能后可能"忘记"全局约束

**建议**：**保留 4 处重复**，但修正计划文件标注（5.1 节），明确这是有意设计而非"已对齐"。

### 5.3 低优先级：AGENTS.md "工具选择原则"与 SKILL.md "核心能力"重叠（无需修改）

**问题**：Charles AGENTS.md L40-47"工具选择原则"与各 SKILL.md"本技能核心能力"存在必要路由信息重叠。

**修复建议**：**无需修改**。这是必要的路由信息重叠：
- AGENTS.md 的"工具选择原则"是决策树入口（用户任务 → 选择技能）
- SKILL.md 的"核心能力"是技能说明（这个技能做什么）

两者从不同角度描述同一事物，去重会破坏决策树或技能说明的完整性。

### 5.4 低优先级：AGENTS.md 与 general.md 职责分离（已完成，无需修改）

**问题**：Charles AGENTS.md 与 general.md 的职责分离是否彻底。

**核实结果**：AGENTS.md L56 明确"股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`"，AGENTS.md 只保留 Agent 主规则（工作模式/工具 vs 技能决策树/工具选择原则/硬约束）。**职责分离已完成**，无需修改。

---

## 六、验证方法

### 6.1 AGENTS.md 与 SKILL.md 去重验证

1. 读取 Cline `sdk/AGENTS.md`，确认内容为"仓库开发规范"（包边界/变更路由/验证规则），不包含任何 SKILL.md 中的任务执行指南
2. 读取 Cline 任意 SKILL.md（如 `.cline/skills/publish-cli/SKILL.md`），确认内容为"特定任务执行指南"，不包含 AGENTS.md 中的仓库开发规范
3. 读取 Charles `agent_config/rules/AGENTS.md` L49-54"硬约束"段落，记录 4 条禁止行为
4. Grep Charles `agent_config/skills/` 搜索"禁止用 web_search 查.*股价"、"禁止用 read_files 读 data/parsed/"，确认 4 处重复
5. 对比重复内容，区分为"完全字面重复"（1 处）和"语义重复"（3 处）

### 6.2 AGENTS.md 与 general.md 职责分离验证

1. 读取 Charles `agent_config/rules/AGENTS.md` L56，确认指向 `rules/general.md` 的注释存在
2. 读取 Charles `agent_config/rules/general.md`，确认包含"输出格式/时间基准/工具调用规范/股票代码格式"4 个段落
3. 对比 charles-nanobot 旧版 `third_party/charles_bundle/charles-nanobot/AGENTS.md`，确认旧版有"股票代码"和"输出"段落，新版已移除

### 6.3 nanobot 残留验证

1. Grep `agent_config/rules/AGENTS.md` 搜索 `nanobot`（case-insensitive），确认 0 匹配
2. Grep `agent_config/rules/general.md` 搜索 `nanobot`（case-insensitive），确认 0 匹配
3. Grep `agent_config/skills/` 目录搜索 `nanobot`（case-insensitive），确认 0 匹配
4. 对比旧版 `charles-nanobot/AGENTS.md` 的工具名（exec/read_file）与新版 `agent_config/rules/AGENTS.md` 的工具名（run_commands/read_files），确认工具名已迁移

### 6.4 重复性质判断验证

1. 确认 4 处重复内容均无 "nanobot" 字样（属非 nanobot 残留）
2. 确认 4 处重复内容在技能上下文中具有强化作用（如 stock-price 技能加载后，L63"本技能是唯一途径"比 AGENTS.md 全局约束更直接）
3. 评估 4 处重复的 token 成本（约 100 token）vs 约束强化收益，确认保留合理

### 6.5 计划文件错误验证

1. 读取 `AGENT_COMPARISON_PLAN_V2.md` L2442-2452，确认 P6.10 标注"Charles 已对齐（Stage P5.3）：SKILL.md 移除与 AGENTS.md 重复的注意事项"
2. 对比 Charles 实际 SKILL.md（4 处重复），确认计划表标注与实际不符
3. 确认 L2448 对比表 6.10.1 标注"已对齐（Stage P5.3）"需修正

---

## 七、附录

### 7.1 Cline AGENTS.md 与 SKILL.md 职责分离示意

```
Cline sdk/AGENTS.md                      Cline .cline/skills/*/SKILL.md
┌─────────────────────────┐              ┌─────────────────────────┐
│ Repository Scope        │              │ Release contract        │
│ Package Boundaries      │              │ Workflow (Step 1-N)     │
│ Dependency Direction    │              │ Error Handling          │
│ Change Routing          │              │ Summary Checklist       │
│ Verifying Changes       │              │                         │
│ Practical Guidance      │              │ （任务执行指南）         │
│ Documentation Resp.     │              │                         │
│ （仓库开发规范）         │              │                         │
└─────────────────────────┘              └─────────────────────────┘
        │                                          │
        └────────────关注点零重叠──────────────────┘
                  天然无重复
```

### 7.2 Charles AGENTS.md 与 SKILL.md 职责重叠示意

```
Charles agent_config/rules/AGENTS.md     Charles agent_config/skills/*/SKILL.md
┌─────────────────────────┐              ┌─────────────────────────┐
│ 工作模式                │              │ 本技能核心能力          │
│ 工具 vs 技能 决策树     │              │ 场景路由                │
│ 工具选择原则            │←──路由重叠──→│ Workflow (Step 1-N)     │
│ 硬约束（4 条）          │←──强化重叠──→│ 禁止行为（含 4 处重复） │
│ 注: general.md 引用     │              │ 脚本调用规则            │
│ （Agent 主规则）         │              │ （技能指南）             │
└─────────────────────────┘              └─────────────────────────┘
        │                                          │
        └────────关注点部分重叠────────────────────┘
              4 处有意强化重复
```

### 7.3 Charles 4 处重复详情

| # | SKILL.md 位置 | SKILL.md 内容（摘录） | AGENTS.md 对应硬约束 | 重复类型 |
|---|--------------|----------------------|---------------------|---------|
| 1 | `financial-analysis/SKILL.md` L111 | 禁止用 `read_files` 读 `data/parsed/` 下的切分文件（那是给 RAG 用的） | L53: 禁止用 read_files 读 data/parsed/ 下的切分文件（那是给 RAG 用的） | 完全字面重复 |
| 2 | `stock-price/SKILL.md` L63 | 禁止用 `web_search` 查询股价/涨跌幅/K线数据（本技能是唯一途径） | L51: 禁止用 web_search 查本地已有数据的股价、财报 | 语义重复 |
| 3 | `web-search/SKILL.md` L72 | 禁止用 `web_search` 查询股价/K线数据（用 `stock-price` 技能） | L51: 禁止用 web_search 查本地已有数据的股价、财报 | 语义重复 |
| 4 | `web-search/SKILL.md` L73-74 | 禁止用 `web_search` 查询财务指标/年报内容（用 financial-analysis / read-pdf 技能） | L51: 禁止用 web_search 查本地已有数据的股价、财报 | 语义重复 |

### 7.4 Charles AGENTS.md 与 general.md 职责分离

```
Charles agent_config/rules/AGENTS.md     Charles agent_config/rules/general.md
┌─────────────────────────┐              ┌─────────────────────────┐
│ 工作模式                │              │ 输出格式                │
│ 工具 vs 技能 决策树     │              │ 时间基准                │
│ 工具选择原则            │   L56 注释   │ 工具调用规范            │
│ 硬约束                  │────指向────→│ 股票代码格式            │
│ （Agent 主规则）         │              │ （通用规则）             │
└─────────────────────────┘              └─────────────────────────┘
        职责分离已完成（AGENTS.md 不含通用规则，general.md 不含 Agent 主规则）
```

### 7.5 nanobot 工具名迁移对比

| 工具用途 | 旧版 nanobot 工具名 | 新版 Cline 工具名 | 迁移状态 |
|---------|--------------------|------------------|---------|
| 读文件 | `read_file` | `read_files` | 已迁移 |
| 执行命令 | `exec` | `run_commands` | 已迁移 |
| 联网搜索 | `web_search` | `web_search` | 一致 |
| 搜索代码 | N/A | `search_codebase` | 新增 |
| 编辑文件 | N/A | `editor` | 新增 |

### 7.6 各 SKILL.md 禁止行为段落统计

| SKILL.md | 禁止行为条数 | 与 AGENTS.md 重复条数 | 技能特定条数 |
|---------|------------|---------------------|------------|
| bond-credit-review | 3 | 0 | 3 |
| compare-reports | 3 | 0 | 3 |
| financial-analysis | 3 | 1（L111） | 2 |
| read-pdf | 5 | 0 | 5 |
| sentiment-analysis | 3 | 0 | 3 |
| stock-price | 3 | 1（L63） | 2 |
| web-search | 4 | 3（L72-74） | 1 |
| write-report | 5 | 0 | 5 |
| **合计** | **29** | **5**（分布在 3 个文件） | **24** |

注：web-search/SKILL.md L72-74 为 3 条，但统计为 1 处"重复位置"（同一段落内 3 条语义重复）。实际重复条数为 5 条（financial-analysis 1 + stock-price 1 + web-search 3），分布在 3 个 SKILL.md 文件中。
