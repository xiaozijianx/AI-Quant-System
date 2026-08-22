# Phase 6.4 AGENTS.md 与 rules 去重对比

> 对比范围：Cline `sdk/AGENTS.md` + `sdk/packages/llms/AGENTS.md`（SDK 开发参考文档）+ `.clinerules/` 目录（general.md / network.md / cline-overview.md 等 tribal knowledge 规则）与 Charles `agent_config/rules/AGENTS.md` + `agent_config/rules/{general,plan-mode-rules,research,trading}.md` 的内容去重情况；区分 AGENTS.md 与 rules 文件的内容重复、指针引用、量化特化段位置；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/AGENTS.md`（109 行，SDK 工作区开发参考：Repository Scope / Package Boundaries / Change Routing / Verifying Changes / Documentation Responsibilities）
> - `third_party/cline/sdk/packages/llms/AGENTS.md`（40 行，@cline/llms 包开发指引：Provider Option Routing）
> - `third_party/cline/.clinerules/general.md`（204 行，tribal knowledge：build output 规避 / gRPC Protobuf / StateManager / ChatRow 取消状态 / debug harness）
> - `third_party/cline/.clinerules/` 目录其他文件（network.md / storage.md / sdk-migration.md / protobuf-development.md / bun-and-node.md / debug-harness.md / cline-overview.md / hooks/README.md / workflows/*.md）
>
> Charles 源码：
> - `agent_config/rules/AGENTS.md`（56 行，Charles 主规则：身份声明 / 工作模式 / 工具 vs 技能 决策树 / 工具选择原则 / 硬约束 / 指针引用）
> - `agent_config/rules/general.md`（35 行，通用规则：输出格式 / 时间基准 / 工具调用规范 / 股票代码格式）
> - `agent_config/rules/plan-mode-rules.md`（46 行，Plan 模式专属规则）
> - `agent_config/rules/research.md`（34 行，研究模式规则）
> - `agent_config/rules/trading.md`（40 行，交易模式规则）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 在 AGENTS.md 与 rules 文件之间的内容去重情况。**核心结论：Charles AGENTS.md 去重彻底——AGENTS.md 不含 "时间基准"、"股票代码格式"、"输出规范" 任何段落，仅 L56 一行指针引用指向 general.md；Cline 侧 AGENTS.md（SDK 开发参考）与 .clinerules/（tribal knowledge）主题完全不同，亦无重复**。两边的去重策略已对齐。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.4 对比表（L2331-2336）存在**两处事实性错误**：

1. **6.4.3 股票代码格式段**：计划表标注"Charles | 在 AGENTS.md"。实际 Charles AGENTS.md **不含**该段，股票代码格式段位于 `agent_config/rules/general.md` L29-35。AGENTS.md 仅在 L56 用一行指针引用 "股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`"。
2. **6.4.4 输出规范段**：计划表标注"Charles | 在 AGENTS.md"。实际 Charles AGENTS.md **不含**该段，输出格式段位于 `agent_config/rules/general.md` L8-13。AGENTS.md 仅通过 L56 指针引用。

### 核心结论

1. **AGENTS.md 与 rules 内容去重已对齐**：Charles AGENTS.md 不重复 rules/general.md 的通用规则段（时间基准/股票代码格式/输出规范/工具调用规范），仅以指针引用；Cline sdk/AGENTS.md 不重复 .clinerules/ 的 tribal knowledge 段，两者主题完全分离（SDK 包边界 vs VS Code 扩展 tribal knowledge）。
2. **Charles 去重比计划描述更彻底**：计划 L2327-2328 仅提及"AGENTS.md 移除与 rules/general.md 重复的'时间基准'段"，实际 AGENTS.md 还移除了（或从未包含）"股票代码格式"段、"输出规范"段、"工具调用规范"段——共 4 个段全部下放到 general.md，AGENTS.md 仅保留身份声明 + 决策树 + 硬约束 + 指针引用。
3. **general.md 与 trading.md 存在部分重复**：股票代码格式段在两文件都有定义，基础格式（沪市/深市/北交所后缀）完全一致，附加内容不同（general.md 含 get_kline.py 后缀规则；trading.md 含自选监控池后缀规则）。这是 Charles 侧**唯一的内容重复点**，但属于"通用规则 + 模式特化规则"的合理重叠，非冗余。
4. **Cline 侧无量化场景概念**：Cline AGENTS.md 不处理投研/量化场景，无"时间基准"、"股票代码格式"、"输出规范"对应段。计划表标注"N/A"准确。
5. **nanobot 残留**：**0 处注释残留 + 0 处实现逻辑残留**。`agent_config/rules/` 全目录 grep "nanobot"（大小写不敏感）无匹配，`agent_config/` 全目录亦无匹配。rules 文件已彻底清除 nanobot 风格残留。

### 一致性总体评估

- **AGENTS.md 与 rules 去重**：**高**。Charles 已完成去重（AGENTS.md 仅指针引用 general.md），Cline 侧 AGENTS.md 与 .clinerules/ 主题分离。
- **重复内容检测**：**高**。Charles AGENTS.md 与 general.md 无重复段落，仅 general.md 与 trading.md 有"股票代码格式"段部分重叠（合理）。
- **量化特化段位置**：**高**。所有量化特化段（时间基准/股票代码格式/输出规范/工具调用规范）均集中在 general.md，AGENTS.md 不含。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.4.1 | AGENTS.md 与 rules 重复内容 | 无（AGENTS.md 是 SDK 开发参考；.clinerules/ 是 tribal knowledge，主题完全分离） | 无（AGENTS.md 是身份+决策树+硬约束；rules/general.md 是通用规则，主题分离） | 高 | 已对齐。两边均通过主题分离实现去重 |
| 6.4.2 | "时间基准"段位置 | N/A（Cline 不处理投研时间基准） | 在 `rules/general.md` L17-20（不在 AGENTS.md） | 高 | Charles AGENTS.md L56 仅指针引用。计划表 6.4.2 标注"在 rules"准确 |
| 6.4.3 | "股票代码格式"段位置 | N/A（Cline 不处理股票代码） | 在 `rules/general.md` L29-35（**不在 AGENTS.md**）+ `rules/trading.md` L29-34 部分重复 | 高 | **计划表 6.4.3 标注错误**：计划表称"在 AGENTS.md"，实际在 general.md。AGENTS.md L56 仅指针引用 |
| 6.4.4 | "输出规范"段位置 | N/A（Cline 不处理研报输出规范） | 在 `rules/general.md` L8-13（**不在 AGENTS.md**） | 高 | **计划表 6.4.4 标注错误**：计划表称"在 AGENTS.md"，实际在 general.md。AGENTS.md L56 仅指针引用 |
| 6.4.5 | AGENTS.md 指针引用 | 无（AGENTS.md 与 .clinerules/ 主题分离，无需指针） | 是（AGENTS.md L56：`注: 股票代码格式、时间基准、输出规范等通用规则见 rules/general.md（由 rules_loader 自动加载）`） | 中 | Charles 显式指针引用，Cline 无对应概念。Charles 通过指针避免重复并指引 rules_loader 加载链路 |
| 6.4.6 | rules 文件目录结构 | `.clinerules/`（扁平 + workflows/ 子目录 + hooks/ 子目录，共 16 个 .md 文件） | `agent_config/rules/`（扁平，共 5 个 .md 文件：AGENTS.md / general.md / plan-mode-rules.md / research.md / trading.md） | 中 | Charles 更精简（5 文件覆盖 Act/Plan/Research/Trade 模式），Cline 更细粒度（16 文件覆盖 workflows/hooks/debug/storage 等开发场景） |
| 6.4.7 | rules 文件 frontmatter | 是（`.clinerules/*.md` 用 `description` + `globs` + `alwaysApply`） | 是（`agent_config/rules/*.md` 用 `description` + `applyTo` + `enabled` + 部分 `mode`） | 高 | 字段命名不同但语义对齐。Charles 多 `applyTo`/`mode` 用于模式条件加载（详见 P6.6） |
| 6.4.8 | rules 间内容重复 | `.clinerules/` 内部无显著重复（每文件聚焦独立主题） | `general.md` L29-35 与 `trading.md` L29-34 股票代码格式段部分重复（基础格式一致，附加内容不同） | 中 | Charles 存在 1 处合理重复（通用规则 + 模式特化规则），非冗余。可考虑未来在 trading.md 用指针引用 general.md |

---

## 三、重点差距详细说明

### 3.1 计划表 6.4.3/6.4.4 标注错误（6.4.3 + 6.4.4）

AGENT_COMPARISON_PLAN_V2.md L2335-2336 标注：

```
| 6.4.3 | 股票代码格式段 | N/A | 在 AGENTS.md | Charles 量化特化 |
| 6.4.4 | 输出规范段 | N/A | 在 AGENTS.md | Charles 量化特化 |
```

**实际 Charles AGENTS.md 内容**（`agent_config/rules/AGENTS.md` 全文 56 行）：

| 行号 | 内容 | 段落 |
|------|------|------|
| L1-5 | frontmatter（description/applyTo/alwaysApply） | 元数据 |
| L7-10 | "你是 Charles，专业 AI 投研情报官..." | 身份声明 |
| L12-17 | "Act 模式/Plan 模式 + switch_to_act_mode" | 工作模式 |
| L19-38 | "工具 vs 技能 决策树" + 禁止行为 | 决策树（Stage P1.3 新增） |
| L40-47 | "工具选择原则（按数据类型）" 6 条 | 工具选择 |
| L49-54 | "硬约束（投研场景特有）" 4 条 | 硬约束 |
| L56 | "注: 股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`（由 rules_loader 自动加载）。" | 指针引用 |

**AGENTS.md 不含以下段落**（计划表误标"在 AGENTS.md"）：

- "股票代码格式"段：实际在 `rules/general.md` L29-35
- "输出规范"段（实际命名"输出格式"）：实际在 `rules/general.md` L8-13
- "时间基准"段：实际在 `rules/general.md` L17-20（计划表 6.4.2 标注正确）
- "工具调用规范"段：实际在 `rules/general.md` L23-27

**结论**：计划表 6.4.3/6.4.4 标注错误，需修正为"在 general.md（AGENTS.md L56 指针引用）"。Charles AGENTS.md 的去重比计划描述更彻底——共 4 个通用规则段全部下放到 general.md，AGENTS.md 仅保留身份声明 + 决策树 + 硬约束 + 指针引用。

### 3.2 Charles general.md 与 trading.md 股票代码格式段部分重复（6.4.8）

**general.md L29-35**：

```
## 股票代码格式

- 沪市: 600519.SH
- 深市: 000858.SZ
- 北交所: 代码.BJ
- get_kline.py 必须带后缀；其他脚本两种格式都支持
- read_files 读 CSV 文件名不带后缀：data/financial_data/600519_financial_abstract.csv
```

**trading.md L29-34**：

```
## 股票代码格式

- 沪市: 600519.SH
- 深市: 000858.SZ
- 北交所: 代码.BJ
- 自选监控池代码必须带交易所后缀
```

**重复内容**：基础格式 3 行（沪市/深市/北交所后缀）完全一致。

**差异内容**：
- general.md 附加：get_kline.py 后缀规则、read_files CSV 命名规则
- trading.md 附加：自选监控池后缀规则

**性质评估**：属"通用规则 + 模式特化规则"的合理重叠，非冗余。general.md 提供跨模式通用规则（所有模式都加载），trading.md 在交易模式下额外强化后缀要求。但基础格式 3 行重复可优化为 trading.md 用指针引用 general.md。

**Cline 侧对比**：Cline `.clinerules/` 内部无类似重复，每文件聚焦独立主题（network.md 专讲网络请求、storage.md 专讲存储、protobuf-development.md 专讲 protobuf）。Cline 主题分离更彻底。

### 3.3 Charles AGENTS.md 指针引用机制（6.4.5）

Charles AGENTS.md L56：

```
注: 股票代码格式、时间基准、输出规范等通用规则见 `rules/general.md`（由 rules_loader 自动加载）。
```

**机制**：
- AGENTS.md 作为主规则文件（`alwaysApply: true`），所有模式常驻加载
- general.md 作为通用规则文件（`enabled: true`），由 `agent/rules_loader.py` 的 `load_rules_directory()` 自动加载（context.py L499-528）
- AGENTS.md 通过指针引用告知 LLM 通用规则的存在和加载来源，避免重复内容
- rules_loader 加载链路：`SystemPromptBuilder._build_rules`（context.py L458-528）→ `_load_rules_directory`（L541-588）→ `load_rules_directory`（rules_loader.py L568-628）

**Cline 对比**：Cline sdk/AGENTS.md 无指针引用机制，因 AGENTS.md 与 .clinerules/ 主题完全分离（SDK 包边界 vs VS Code 扩展 tribal knowledge），无需互相引用。Cline 通过 `contributionRegistry.getRegisteredRules()` 在编排器层收集 rules（session-runtime-orchestrator.ts L682-687），不依赖指针引用。

**评估**：Charles 指针引用是合理设计——AGENTS.md 作为"主入口"告知 LLM 通用规则的存在，避免 LLM 在 AGENTS.md 中找不到通用规则时误以为不存在。Cline 无此需求因主题分离更彻底。两边均合理，非对齐缺口。

### 3.4 Cline AGENTS.md 与 .clinerules/ 主题分离（6.4.1）

**Cline sdk/AGENTS.md 主题**（109 行）：
- Repository Scope（SDK 工作区范围）
- Package Boundaries（@cline/shared / @cline/llms / @cline/agents / @cline/core 边界）
- Dependency Direction（依赖方向 mermaid 图）
- Change Routing（变更路由到对应包）
- Verifying Changes（验证变更命令）
- Practical Guidance（重构标准 / 边界保持）
- Documentation Responsibilities（README/CONTRIBUTING/AGENTS/ARCHITECTURE/DOC 更新责任）

**Cline .clinerules/general.md 主题**（204 行）：
- Miscellaneous（bun vs node、provider 字符串匹配、VS Code 扩展）
- Searching the Codebase — Avoiding Build Output（out/ dist/ src/generated/ 规避）
- gRPC/Protobuf Communication（proto 文件、enum、RPC 方法）
- Adding New Global State Keys（state-keys.ts / StateManager / settings plumbing）
- StateManager Cache vs Direct globalState Access
- ChatRow Cancelled/Interrupted States
- Debug Harness: clear inherited VSCode/Electron env vars

**主题分离验证**：两文件主题完全不重叠——AGENTS.md 讲"包边界与变更路由"（架构层），.clinerules/general.md 讲"VS Code 扩展开发 tribal knowledge"（实现层）。无任何段落重复。

**Charles 对比**：Charles AGENTS.md（身份+决策树+硬约束）与 general.md（输出格式+时间基准+工具调用规范+股票代码格式）也是主题分离——AGENTS.md 讲"Agent 身份与决策"（行为层），general.md 讲"投研通用规则"（业务层）。两边主题分离策略一致。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 AGENTS.md 与 rules 相关文件检查 nanobot 风格残留：

- `agent_config/rules/AGENTS.md`（56 行）
- `agent_config/rules/general.md`（35 行）
- `agent_config/rules/plan-mode-rules.md`（46 行）
- `agent_config/rules/research.md`（34 行）
- `agent_config/rules/trading.md`（40 行）

### 4.2 检查方法

```powershell
# 在 agent_config/rules/ 目录搜索 nanobot（大小写不敏感）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" -Pattern "nanobot" -CaseSensitive:$false

# 在 agent_config/ 全目录搜索 nanobot（大小写不敏感，覆盖更广范围）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\*.*" -Pattern "nanobot" -CaseSensitive:$false -Recurse
```

### 4.3 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent_config/rules/AGENTS.md` | 0 | 0 | 无残留 |
| `agent_config/rules/general.md` | 0 | 0 | 无残留 |
| `agent_config/rules/plan-mode-rules.md` | 0 | 0 | 无残留 |
| `agent_config/rules/research.md` | 0 | 0 | 无残留 |
| `agent_config/rules/trading.md` | 0 | 0 | 无残留 |

### 4.4 残留详情

**无残留**。`agent_config/rules/` 全目录及 `agent_config/` 全目录均无 "nanobot" 字符串匹配（大小写不敏感）。

### 4.5 与 Phase 4.20 / Phase 5.1 对比

- **Phase 4.20（技能系统 nanobot 残留审计）**：发现 17 处实现逻辑残留（`always` 预加载、`when_to_use` 字段、SKILL.md 三段式章节等）
- **Phase 5.1（SystemPromptBuilder 架构 nanobot 残留）**：发现 1 处注释残留（context.py L275 docstring `extra_sections` 参数）+ 1 个死参数
- **Phase 6.4（AGENTS.md 与 rules 去重）**：**0 处残留**

**结论**：rules 文件层面已彻底清除 nanobot 风格残留。Stage P3 重构（rules frontmatter 标准化 + AGENTS.md 去重）已将 rules 文件全部改为 Cline 风格的 frontmatter + Markdown 段落结构，无 nanobot 风格的"技能段落"、"扩展段落"等概念残留。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **6.4.1 重复内容**：Charles AGENTS.md 与 general.md 无重复段落，已对齐。
- **6.4.2 时间基准段位置**：在 general.md L17-20，AGENTS.md L56 指针引用，已对齐。
- **6.4.5 AGENTS.md 指针引用**：Charles 显式指针引用是合理设计，无需修改。
- **6.4.6 rules 文件目录结构**：Charles 5 文件 vs Cline 16 文件，文件数差异属合理偏离（Charles 聚焦投研场景，Cline 覆盖全开发流程）。
- **6.4.7 rules 文件 frontmatter**：已对齐（详见 P6.1）。

### 5.2 优先级 P1（建议处理）

- **6.4.8 general.md 与 trading.md 股票代码格式段部分重复**：建议在 trading.md L29-34 的"股票代码格式"段上方添加指针引用，如 `> 基础格式见 rules/general.md "股票代码格式"段；以下为交易模式特化规则：`，然后仅保留 trading.md 特化内容（自选监控池后缀规则），移除基础格式 3 行重复。当前重复不影响功能，但增加维护成本（修改基础格式需同步两文件）。

### 5.3 优先级 P2（可选优化）

- **6.4.3/6.4.4 计划表标注错误**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2335-2336：
  - 6.4.3 股票代码格式段：Charles 列从"在 AGENTS.md"改为"在 general.md（AGENTS.md L56 指针引用）"
  - 6.4.4 输出规范段：Charles 列从"在 AGENTS.md"改为"在 general.md（AGENTS.md L56 指针引用）"
  - 关键差异列保持"Charles 量化特化"不变（因 general.md 本身就是 Charles 量化特化规则文件，Cline 无对应概念）

### 5.4 优先级 P3（文档修正）

- **AGENTS.md L56 指针引用措辞优化**（可选）：当前 `注: 股票代码格式、时间基准、输出规范等通用规则见 rules/general.md（由 rules_loader 自动加载）。` 中的"输出规范"与 general.md 实际段名"输出格式"不一致。建议统一为"输出格式"以与 general.md L8 段名对齐，避免 LLM 查找时混淆。

---

## 六、验证方法

### 6.1 AGENTS.md 去重验证

```powershell
# 验证 Charles AGENTS.md 不含"时间基准"段（应仅 1 处指针引用）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "时间基准"
# 预期: L56 一行指针引用

# 验证 Charles AGENTS.md 不含"股票代码格式"段标题（应仅 L56 指针引用）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^## 股票代码格式"
# 预期: 无匹配（段标题在 general.md L29）

# 验证 Charles AGENTS.md 不含"输出格式"段标题（应仅 L56 指针引用"输出规范"）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\AGENTS.md" -Pattern "^## 输出格式"
# 预期: 无匹配（段标题在 general.md L8）
```

### 6.2 nanobot 残留验证

```powershell
# 在 agent_config/rules/ 目录搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无匹配

# 在 agent_config/ 全目录递归搜索 nanobot（应 0 处）
Get-ChildItem -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config" -Recurse -File | Select-String -Pattern "nanobot" -CaseSensitive:$false
# 预期: 无匹配
```

### 6.3 general.md 与 trading.md 重复段验证

```powershell
# 验证股票代码格式段在 general.md 和 trading.md 都存在（部分重复）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" -Pattern "^## 股票代码格式"
# 预期: 2 处匹配（general.md L29 + trading.md L29）

# 验证基础格式 3 行在两文件一致
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\*.md" -Pattern "^- 沪市: 600519\.SH$"
# 预期: 2 处匹配（general.md L31 + trading.md L31）
```

### 6.4 Cline 主题分离验证

```powershell
# 验证 Cline sdk/AGENTS.md 与 .clinerules/general.md 无段落标题重复
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\AGENTS.md" -Pattern "^## "
# 输出: Repository Scope / Package Boundaries / Change Routing / Verifying Changes / Practical Guidance / Documentation Responsibilities

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\.clinerules\general.md" -Pattern "^## "
# 输出: Miscellaneous / Searching the Codebase / gRPC/Protobuf Communication / Adding New Global State Keys / StateManager Cache vs Direct globalState Access / ChatRow Cancelled/Interrupted States / Debug Harness
# 预期: 两组标题无重叠
```

### 6.5 rules_loader 自动加载验证

```powershell
# 验证 general.md enabled: true（会被 rules_loader 自动加载）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent_config\rules\general.md" -Pattern "^enabled:"
# 预期: enabled: true

# 验证 rules_loader.py 的 load_rules_directory 函数存在
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "^def load_rules_directory"
# 预期: 匹配 rules_loader.py L568
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 6.4.1 重复内容 | Cline 无 / Charles 无 / 已对齐 | **确认已对齐** | 两边 AGENTS.md 与 rules 文件均无重复段落 |
| 6.4.2 时间基准段 | Cline 在 rules / Charles 在 rules / 已对齐 | **确认已对齐** | Charles 在 general.md L17-20，AGENTS.md L56 指针引用 |
| 6.4.3 股票代码格式段 | Cline N/A / Charles 在 AGENTS.md / Charles 量化特化 | **计划表标注错误** | 实际在 general.md L29-35（不在 AGENTS.md）+ trading.md L29-34 部分重复。AGENTS.md L56 仅指针引用 |
| 6.4.4 输出规范段 | Cline N/A / Charles 在 AGENTS.md / Charles 量化特化 | **计划表标注错误** | 实际在 general.md L8-13（段名"输出格式"，不在 AGENTS.md）。AGENTS.md L56 仅指针引用 |

**计划表标注总结**：4 项中 2 项（6.4.1/6.4.2）标注准确，2 项（6.4.3/6.4.4）标注错误。错误原因可能是计划编写时基于早期 AGENTS.md 版本（Stage P3 重构前 AGENTS.md 可能含股票代码格式段和输出规范段），Stage P3.2 重构将这些段全部下放到 general.md 后，计划表未同步更新。

**额外发现**（计划表未涵盖）：
- 6.4.5 AGENTS.md 指针引用机制（Charles 独有，Cline 无对应概念）
- 6.4.6 rules 文件目录结构差异（Charles 5 文件 vs Cline 16 文件）
- 6.4.7 rules 文件 frontmatter 字段对齐（详见 P6.1/P6.6）
- 6.4.8 general.md 与 trading.md 股票代码格式段部分重复（Charles 侧唯一内容重复点，属合理重叠）
- nanobot 残留：0 处（rules 文件已彻底清除）
