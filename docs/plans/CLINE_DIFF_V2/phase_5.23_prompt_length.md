# Phase 5.23 System Prompt 长度对比

> 对比范围：Cline `DEFAULT_CLINE_SYSTEM_PROMPT` / `YOLO_CLINE_SYSTEM_PROMPT` / `MODE_TAG_INSTRUCTIONS` / `PLAN_MODE_INSTRUCTIONS` 与 Charles `DEFAULT_CHARLES_SYSTEM_PROMPT` / `YOLO_CHARLES_SYSTEM_PROMPT` / `_build_mode_tag_instructions()` / `PLAN_MODE_PROMPT` 的字符数、token 估算、各段长度占比；base prompt / rules / metadata 三大段长度逐项对标；token 估算方法差异分析；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/system.ts` L1-36（`DEFAULT_CLINE_SYSTEM_PROMPT`，3695 chars）+ L38-68（`YOLO_CLINE_SYSTEM_PROMPT`，2847 chars）
> - `sdk/packages/shared/src/prompt/cline.ts` L21-23（`MODE_TAG_INSTRUCTIONS`，606 chars）+ L32-45（`PLAN_MODE_INSTRUCTIONS`，1485 chars）+ L110-166（`buildClineSystemPrompt` 拼接逻辑）
>
> Charles 源码：
> - `agent/prompts/charles_system_prompt.py` L31-58（`DEFAULT_CHARLES_SYSTEM_PROMPT`，828 chars）+ L62-91（`YOLO_CHARLES_SYSTEM_PROMPT`，809 chars）
> - `agent/context.py` L836-856（`_build_mode_tag_instructions` 返回 334 chars）+ `agent/tools/plan_mode.py` L38-55（`PLAN_MODE_PROMPT`，745 chars）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 各段长度。**核心结论：两者在结构上对齐（base + rules + metadata 三段式），但因语言差异（Cline 英文 / Charles 中文）和 base prompt 内嵌规则详尽度差异，字符数差距显著，但 token 数（按各自语言混合估算）相对接近**。计划文件 P5.23 表格中的预估值与实测数据偏差较大，需全面修正。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.23（L2219-2228）预估值与实测数据存在系统性偏差：

| 计划项 | 计划估值 (Cline/Charles) | 实测数据 (Cline/Charles) | 偏差说明 |
|--------|------------------------|------------------------|---------|
| 5.23.1 总长度 | ~5000 / ~6459 chars | 4361 / 1226 chars（act, 空 rules） | **Charles 实测远低于估值**（1226 vs 6459）。计划估值可能含 enhancements 开启时的 tools/skills 概览段 |
| 5.23.2 Base prompt 长度 | ~2000 / ~2000 chars | 3695 / 828 chars | **Cline 实测高于估值**（3695 vs 2000），**Charles 实测远低于估值**（828 vs 2000）。Cline 在 base 中内嵌大量英文行为规则 |
| 5.23.3 工具说明长度 | ~1500 / ~1500 chars | Cline ~600 chars（base 内嵌）/ Charles ~200 chars（base 内嵌） | 工具说明在两者中均嵌入 base prompt，非独立段。Charles 另有 `_build_tools_section` 增强层（默认关闭） |
| 5.23.4 skills 长度 | ~500 / ~800 chars | 0 / 0 chars（默认关闭） | skills 段为 Charles 独有增强层，默认关闭，默认场景下长度为 0 |
| 5.23.5 rules 长度 | ~500 / ~500 chars | Cline 606 chars（MODE_TAG）/ Charles 334 chars（MODE_TAG） | rules 长度指内置 rules（MODE_TAG + PLAN_MODE）。空用户 rules 场景下，Cline MODE_TAG 606 / Charles MODE_TAG 334 |

**结论**：计划文件估值整体偏高，且未区分"默认关闭的增强层"与"默认开启的内置 rules"。本报告以实测数据为准。

### 核心结论

1. **总长度（DEFAULT, act, 空用户 rules）**：Cline 4361 chars / Charles 1226 chars。Cline 字符数是 Charles 的 3.6 倍，主要因 Cline base prompt 内嵌大量英文行为规则（3610 chars 硬编码 vs Charles 739 chars 硬编码）。
2. **总长度（DEFAULT, plan, 空用户 rules）**：Cline 5848 chars / Charles 1973 chars。plan 模式差距缩小（Cline 是 Charles 的 3.0 倍），因 Charles 的 `PLAN_MODE_PROMPT` 中文内容比 Cline `PLAN_MODE_INSTRUCTIONS` 更详尽。
3. **Base prompt 长度**：Cline DEFAULT 3695 chars / Charles DEFAULT 828 chars。Cline 是 Charles 的 4.5 倍。Cline base 包含 7 条 "Remember" 规则 + 4 条并行调用规则 + 完整流程指引，Charles base 仅含 6 条通用规则 + 4 条工具调用规则。
4. **<env> 段长度**：完全对齐，均为 120 chars（4 个字段 + XML 标签）。
5. **MODE_TAG_INSTRUCTIONS 长度**：Cline 606 chars / Charles 334 chars。Charles 简洁化（中文信息密度高），Cline 详尽解释 mode 属性语义和切换行为。
6. **PLAN_MODE_INSTRUCTIONS 长度**：Cline 1485 chars / Charles 745 chars。Cline 是 Charles 的 2.0 倍。Charles 的 PLAN_MODE_PROMPT 内容更聚焦（含工具限制说明、完成规划后行为）。
7. **Metadata 长度**：Cline 112 chars / Charles 113 chars。**几乎完全对齐**，因两者均采用 `# Workspace Configuration` + workspaces JSON 结构。
8. **Token 估算方法差异**：Cline 主要为英文，`chars/4` ≈ 实际 tokens（4361 chars ≈ 1090 tokens）；Charles 含大量中文，`chars/4` 严重低估（1226 chars/4 = 306 tokens，混合估算 1027 tokens）。**token 层面两者实际接近**（Cline 1090 / Charles 1027，act 模式）。
9. **各段占比**：Cline base 占比 82.8%（rules 13.9% + metadata 2.6%）；Charles base 占比 60.3%（rules 27.2% + metadata 9.2%）。Charles rules 占比相对更高，因 base 更短。
10. **nanobot 残留**：**1 处注释残留**（context.py L275 docstring），**0 处实现逻辑残留**。与 Phase 5.1 结论一致。

### 一致性总体评估

- **结构对齐**：**高**。两者均为 base + rules + metadata 三段式，占位符数量和语义对齐（6 个占位符）。
- **字符数对齐**：**低**。Cline 字符数显著多于 Charles（3.0~3.6 倍），主要因 base prompt 详尽度差异。
- **token 数对齐**：**中-高**。考虑语言差异后，实际 token 占用接近（Cline 1090 / Charles 1027，act 模式）。
- **各段比例对齐**：**中**。Cline base 占比过高（82.8%），Charles 更均衡（60.3% / 27.2% / 9.2%）。

---

## 二、逐项对比表

### 2.1 Base Prompt 模板长度

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.23.1 | DEFAULT 模板字符数 | 3695 chars（system.ts L1-36） | 828 chars（charles_system_prompt.py L31-58） | 低 | Cline 是 Charles 的 4.5 倍。Cline base 含 7 条 "Remember" + 4 条并行调用规则 + 完整流程指引；Charles base 仅含 6 条通用规则 + 4 条工具调用规则 |
| 5.23.2 | YOLO 模板字符数 | 2847 chars（system.ts L38-68） | 809 chars（charles_system_prompt.py L62-91） | 低 | Cline 是 Charles 的 3.5 倍。差距略小于 DEFAULT，因 YOLO 模板两者都更简洁 |
| 5.23.3 | DEFAULT base 硬编码部分（移除占位符） | 3610 chars | 739 chars | 低 | 占位符长度 Cline 85 chars / Charles 89 chars，几乎相同。硬编码部分差距为 4.9 倍 |
| 5.23.4 | YOLO base 硬编码部分 | 2762 chars | 720 chars | 低 | 差距 3.8 倍 |
| 5.23.5 | <env> 段字符数 | 120 chars | 120 chars | 完全对齐 | 4 字段（Platform/Date/IDE/Working Directory）+ XML 标签，结构完全一致 |
| 5.23.6 | 占位符数量 | 6 个 | 6 个 | 完全对齐 | `{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}` / `{{*_RULES}}` / `{{*_METADATA}}` |
| 5.23.7 | 占位符标记总长度 | 85 chars | 89 chars | 高 | Charles 占位符名略长（`CHARLES_RULES` 17 chars vs `CLINE_RULES` 15 chars） |

### 2.2 Rules 段长度（内置 rules，不含用户 rules）

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.23.8 | MODE_TAG_INSTRUCTIONS 字符数 | 606 chars（cline.ts L21-23） | 334 chars（context.py L836-856） | 中 | Cline 是 Charles 的 1.8 倍。Cline 详尽解释 mode 属性语义、mid-conversation switch、`<mode_notice>` 块；Charles 简洁列出三种 mode 取值和切换行为 |
| 5.23.9 | PLAN_MODE_INSTRUCTIONS 字符数 | 1485 chars（cline.ts L32-45） | 745 chars（plan_mode.py L38-55） | 中 | Cline 是 Charles 的 2.0 倍。Cline 详尽说明 plan-mode 行为契约 + run_commands 限制 + switch_to_act_mode 调用约束；Charles 包含工具限制说明（tool_policies 硬禁用）+ 完成规划后行为 |
| 5.23.10 | effectiveRules 总长度（act 模式，空用户 rules） | 606 chars（仅 MODE_TAG） | 334 chars（仅 MODE_TAG） | 中 | act 模式不注入 PLAN_MODE_INSTRUCTIONS |
| 5.23.11 | effectiveRules 总长度（plan 模式，空用户 rules） | 2091 chars（MODE_TAG + PLAN_MODE） | 1079 chars（MODE_TAG + PLAN_MODE） | 中 | plan 模式注入两者。Cline 2091 / Charles 1079，差距 1.9 倍 |

### 2.3 Metadata 段长度

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.23.12 | Metadata 字符数（空 workspaces，无 git） | 112 chars | 113 chars | 完全对齐 | 两者均采用 `# Workspace Configuration\n` + JSON 结构。1 char 差异来自 JSON 缩进细节 |
| 5.23.13 | Metadata 标记 | `# Workspace Configuration`（WORKSPACE_CONFIGURATION_MARKER） | `# Workspace Configuration` | 完全对齐 | Charles L448-452 明确对齐 Cline 标记 |
| 5.23.14 | Metadata JSON 结构 | `{workspaces: {rootPath: {hint, associatedRemoteUrls, latestGitCommitHash, latestGitBranchName}}}` | `{workspaces: {working_dir: {hint, latestGitCommitHash, latestGitBranchName, associatedRemoteUrls}}}` | 高 | 字段名和嵌套结构对齐。Charles 字段顺序略异（remoteUrls 在最后） |

### 2.4 完整 System Prompt 总长度（模拟渲染）

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.23.15 | DEFAULT act 模式总字符数 | 4361 chars | 1226 chars | 低 | Cline 是 Charles 的 3.6 倍。主要差距在 base prompt 硬编码部分（3610 vs 739） |
| 5.23.16 | DEFAULT plan 模式总字符数 | 5848 chars | 1973 chars | 低 | Cline 是 Charles 的 3.0 倍。plan 模式差距缩小，因 Charles PLAN_MODE_PROMPT 相对详尽 |
| 5.23.17 | YOLO 模式总字符数 | 3513 chars | 1207 chars | 低 | Cline 是 Charles 的 2.9 倍。YOLO 模式不注入 PLAN_MODE |
| 5.23.18 | DEFAULT act 模式 token 估算（Charles 混合算法） | 1090 tokens | 1027 tokens | 高 | **token 层面接近**。Cline 英文 chars/4 ≈ tokens；Charles 中文混合估算（中文字符 × 1.5 + 其他 / 4） |
| 5.23.19 | DEFAULT plan 模式 token 估算（Charles 混合算法） | 1462 tokens | 1620 tokens | 高 | plan 模式 Charles token 反而略多（1620 vs 1462），因 PLAN_MODE_PROMPT 中文内容信息密度高 |
| 5.23.20 | YOLO 模式 token 估算（Charles 混合算法） | 878 tokens | 1051 tokens | 中-高 | YOLO 模式 Charles token 略多（1051 vs 878） |

### 2.5 各段长度占比（DEFAULT act 模式，空用户 rules）

| # | 对比项 | Cline 占比 | Charles 占比 | 说明 |
|---|--------|-----------|-------------|------|
| 5.23.21 | Base prompt 硬编码部分占比 | 82.8%（3610/4361） | 60.3%（739/1226） | Cline base 占比过高，因内嵌大量英文规则 |
| 5.23.22 | Rules 部分（MODE_TAG）占比 | 13.9%（606/4361） | 27.2%（334/1226） | Charles rules 占比相对更高，因 base 更短 |
| 5.23.23 | Metadata 部分占比 | 2.6%（112/4361） | 9.2%（113/1226） | Charles metadata 占比相对更高，因总长度更短 |
| 5.23.24 | <env> 实际值占比 | 2.3%（101/4361） | 8.9%（109/1226） | Charles env 占比相对更高，因总长度更短 |

---

## 三、重点差距详细说明

### 3.1 Base Prompt 详尽度差异（5.23.1 / 5.23.2）

Cline 的 `DEFAULT_CLINE_SYSTEM_PROMPT`（3695 chars）远长于 Charles 的 `DEFAULT_CHARLES_SYSTEM_PROMPT`（828 chars），差距 4.5 倍。原因在于 Cline base prompt 内嵌了大量行为规则，而 Charles 将部分规则外移到 rules 段或增强层。

**Cline base prompt 包含的内容**：

```
1. 身份定义（"You are Cline, an AI coding agent..."）
2. 上下文收集要求（"Always gather all the necessary context..."）
3. 代码审查要求（"Review each question carefully..."）
4. 信息获取策略（"If you need more information, use one of the available tools..."）
5. <env> 段（4 字段）
6. 7 条 "Remember" 规则:
   - adhere to existing code conventions
   - use only confirmed libraries
   - provide complete code without omissions
   - be explicit about assumptions
   - show planning process before executing
   - use absolute paths
   - call multiple tools in single response
   - good parallelism examples
   - verify files after editing
7. 流程指引（"Begin by analyzing the user's input..."）
8. 行为约束（"REMEMBER, be helpful and proactive!..."）
9. 完成要求（"IMPORTANT: Always includes tool calls..."）
10. 总结要求（"When you have completed the task..."）
11. 简单问答规则（"If user asked a simple question..."）
```

**Charles base prompt 包含的内容**：

```
1. 身份定义（"你是 Charles，专业的 AI 投研情报官..."）
2. 通用行为规则（6 条: 上下文优先 / 任务拆解 / 技能触发 / 工具选择 / 绝对路径 / 结果导向）
3. 工具调用规则（4 条: 并行调用 / 依赖分轮 / 规划后调用 / 禁止直接 run_commands 技能脚本）
4. <env> 段（4 字段）
```

**差异分析**：
- Cline 在 base 中嵌入"流程指引"和"行为约束"等细节，Charles 将这些外移到 rules 或增强层
- Cline 的 "Remember" 规则更细粒度（9 条），Charles 的"通用行为规则"更宏观（6 条）
- Charles 额外包含"任务拆解"和"技能触发"规则（量化场景特有），Cline 无对应内容
- 两者均含"绝对路径"和"并行调用"规则，语义对齐

**评估**：这是设计差异非差距。Cline 的 base prompt 详尽化策略适合通用编码场景（无特定领域约束）；Charles 的 base prompt 精简策略适合量化投研场景（领域规则通过 rules/AGENTS.md 注入）。两者在"必备规则"上语义对齐（绝对路径、并行调用、验证文件）。

### 3.2 Token 估算方法差异（5.23.18 / 5.23.19）

Cline 主要为英文内容，`chars / 4` 是合理的 token 估算（英文平均 4 chars/token）。Charles 含大量中文内容，`chars / 4` 严重低估实际 token 数。

**Charles 的 token 估算算法**（context.py L897-910）：

```python
def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cn_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_chars = len(text) - cn_chars
    return max(1, int(cn_chars * 1.5 + other_chars / 4))
```

**估算对比**：

| 内容 | 字符数 | chars/4 估算 | Charles 混合估算 | 实际 token（参考 Qwen tokenizer） |
|------|--------|-------------|----------------|-------------------------------|
| Cline DEFAULT act 完整 | 4361 | 1090 | 1090 | ~1100（全英文） |
| Charles DEFAULT act 完整 | 1226 | 306 | 1027 | ~950（中文为主） |
| Charles PLAN_MODE_PROMPT | 745 | 186 | 592 | ~550 |

**结论**：Charles 的混合估算算法对中文内容更准确。token 层面两者实际接近（Cline 1090 / Charles 1027，act 模式），字符数差距（3.6 倍）不等于 token 差距（1.06 倍）。

**评估**：Charles 的 `estimate_tokens` 是合理增强（对标 Cline 的简单 chars/4，但对中文场景优化）。Cline 未提供专门的 token 估算函数，依赖底层 tokenizer 精确计算。

### 3.3 各段占比差异（5.23.21 - 5.23.24）

| 段 | Cline 占比 | Charles 占比 | 差异说明 |
|----|----------|-------------|---------|
| Base 硬编码 | 82.8% | 60.3% | Cline base 占比过高，因内嵌大量规则 |
| Rules (MODE_TAG) | 13.9% | 27.2% | Charles rules 占比更高，因 base 更短 |
| Metadata | 2.6% | 9.2% | Charles metadata 占比更高，因总长度更短 |
| <env> 实际值 | 2.3% | 8.9% | Charles env 占比更高，因总长度更短 |

**差异分析**：
- Cline 的 base prompt "臃肿"（82.8%），rules 和 metadata 占比被压缩
- Charles 的 base prompt "精简"（60.3%），rules 和 metadata 占比相对凸显
- 这种占比差异不影响功能，仅反映"规则放 base 还是放 rules"的设计取向

**评估**：非对齐缺口。两者的 rules 和 metadata 绝对长度接近（rules: Cline 606 / Charles 334；metadata: Cline 112 / Charles 113），占比差异来自 base 长度差异。

### 3.4 PLAN_MODE 内容详尽度差异（5.23.9）

Cline `PLAN_MODE_INSTRUCTIONS`（1485 chars）比 Charles `PLAN_MODE_PROMPT`（745 chars）长 2.0 倍。

**Cline PLAN_MODE_INSTRUCTIONS 包含**：
- Plan mode 角色定义（"explore, analyze, and plan -- not to execute"）
- 5 条行为约束（read files / ask questions / present plan / explain tradeoffs / do NOT edit）
- run_commands 工具的 plan-mode 行为契约（"inspection-only"）
- switch_to_act_mode 调用约束（"never call it in the same turn"）

**Charles PLAN_MODE_PROMPT 包含**：
- Plan mode 角色定义（"探索、分析并给出清晰的执行计划"）
- 5 条模式行为契约（探索 / run_commands 限制 / 规划 / 不执行 / 工具限制）
- 完成规划后行为（switch_to_act_mode 调用约束）

**差异分析**：
- Cline 强调"do NOT edit files, write code, run destructive commands"等具体禁止行为
- Charles 强调"editor / apply_patch / file_write / write-report 等写入/编辑类工具已由 tool_policies 硬禁用"
- Charles 的"工具限制"规则是对 Cline 的合理增强（量化场景需要明确工具策略）

**评估**：内容详尽度差异属合理设计取向。Cline 通过 prompt 约束 LLM 行为；Charles 通过 prompt + tool_policies 双重约束（prompt 说明 + 硬件禁用）。

### 3.5 计划文件 P5.23 估值偏差分析

计划文件 P5.23 的估值与实测数据存在系统性偏差，主要原因：

1. **未区分默认场景与增强场景**：Charles 的 skills/tools/mcp 段为增强层（默认关闭），计划估值可能基于 enhancements.enabled=true 场景，而本报告以默认场景（enhancements.enabled=false）为准。
2. **Base prompt 估值偏低**：计划估值 Cline base ~2000 chars，实测 3695 chars。计划可能未计入 Cline base 中的 "Remember" 规则和流程指引。
3. **Charles base 估值偏高**：计划估值 Charles base ~2000 chars，实测 828 chars。计划可能误将 rules/enhancements 内容计入 base。
4. **rules 估值偏低**：计划估值 ~500 chars，实测 Cline MODE_TAG 606 + PLAN_MODE 1485 = 2091 chars（plan 模式）。计划可能仅计入 MODE_TAG，未计 PLAN_MODE。

**修正建议**：计划文件 P5.23 表格应按本报告表 2.1-2.4 实测数据修正。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 System Prompt 长度相关文件检查 nanobot 风格残留：
- `agent/context.py`（含 `SystemPromptBuilder` + `_build_mode_tag_instructions` + `estimate_tokens`）
- `agent/prompts/charles_system_prompt.py`（base prompt 模板）
- `agent/tools/plan_mode.py`（`PLAN_MODE_PROMPT`）

### 4.2 检查结果

| 文件 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` | 1 | 0 | L275 docstring：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` |
| `agent/prompts/charles_system_prompt.py` | 0 | 0 | 无残留 |
| `agent/tools/plan_mode.py` | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（1 处）

**位置**：`agent/context.py` L275

```python
def __init__(
    self,
    identity: str = "",
    ...
    extra_sections: dict[str, str] | None = None,
    ...
) -> None:
    """初始化系统提示组装器

    Args:
        ...
        extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                        保留参数签名仅为向后兼容，当前无调用方传入。
        ...
    """
```

**性质**：纯注释残留，说明 `extra_sections` 参数的历史来源（nanobot 风格）和当前状态（已废弃、无调用方）。**不影响 System Prompt 长度**，因 `extra_sections` 默认为空 dict，`_build_rules` L530-537 的遍历逻辑为死代码（永不执行）。

#### 4.3.2 实现逻辑残留（0 处）

经核查 System Prompt 长度相关全部代码：

- `build_charles_system_prompt`（context.py L78-127）：**无 nanobot 风格实现逻辑**，仅做占位符替换
- `select_base_template`（context.py L185-205）：**无 nanobot 风格实现逻辑**，根据 mode 选择 DEFAULT / YOLO 模板
- `SystemPromptBuilder._build_rules`（context.py L454-539）：**无 nanobot 风格实现逻辑**，从磁盘加载 AGENTS.md + rules_dir + 注入 MODE_TAG/PLAN_MODE/enhancements
- `SystemPromptBuilder._build_metadata`（context.py L408-452）：**无 nanobot 风格实现逻辑**，查询 git 状态构建 workspaces JSON
- `_build_mode_tag_instructions`（context.py L836-856）：**无 nanobot 风格实现逻辑**，返回 mode 标签说明文本
- `PLAN_MODE_PROMPT`（plan_mode.py L38-55）：**无 nanobot 风格实现逻辑**，plan 模式行为契约文本
- `estimate_tokens`（context.py L897-910）：**无 nanobot 风格实现逻辑**，中英文混合 token 估算

**结论**：System Prompt 长度相关代码无 nanobot 风格实现逻辑残留。`extra_sections` 死参数不影响 System Prompt 实际长度（默认空 dict）。

### 4.4 与 Phase 5.1 对比

Phase 5.1（SystemPromptBuilder 架构对比）发现 1 处注释残留 + 0 处实现逻辑残留。**本阶段结论与 Phase 5.1 完全一致**，System Prompt 长度相关代码无新增 nanobot 残留。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.23.5 <env> 段长度**：完全对齐，无需修复。
- **5.23.6 占位符数量**：完全对齐，无需修复。
- **5.23.12 Metadata 字符数**：完全对齐（112 vs 113 chars，1 char 差异可忽略）。
- **5.23.13 Metadata 标记**：完全对齐，无需修复。
- **5.23.14 Metadata JSON 结构**：字段名和嵌套结构对齐，无需修复。

### 5.2 优先级 P1（建议处理）

- **5.23.18-5.23.20 Token 估算方法**：Charles 的 `estimate_tokens` 混合算法（中文字符 × 1.5 + 其他 / 4）是对 Cline 简单 chars/4 的合理增强。建议在 `estimate_tokens` docstring 中明确标注"Cline 采用 chars/4 简单估算，Charles 采用混合估算以适应中文内容"，避免后续对齐工作误判。当前 docstring（context.py L898-904）已说明"采用混合估算策略，对中文更友好"，但未明确与 Cline 的差异。

### 5.3 优先级 P2（可选优化）

- **5.23.1 / 5.23.2 Base prompt 详尽度差异**：Cline base 3695 chars / Charles base 828 chars。差异属设计取向（Cline 通用编码场景需详尽规则；Charles 量化场景通过 rules/AGENTS.md 注入领域规则）。无需强制对齐，但建议在 `charles_system_prompt.py` 模块 docstring 中说明"Charles base prompt 精简策略：领域规则通过 AGENTS.md + rules_dir 动态注入，不硬编码在 base 中"。

- **5.23.9 PLAN_MODE 内容详尽度差异**：Cline 1485 chars / Charles 745 chars。Charles 的 PLAN_MODE_PROMPT 已包含核心行为契约，且通过 tool_policies 硬禁用写入工具（双重保障）。无需扩展到 Cline 的 1485 chars。

- **nanobot 注释残留**（context.py L275）：建议保留，作为历史说明。与 Phase 5.1 结论一致。

### 5.4 优先级 P3（文档修正）

- **计划文件 P5.23 估值修正**：建议修正 AGENT_COMPARISON_PLAN_V2.md L2219-2228，按本报告表 2.1-2.4 实测数据更新。关键修正：
  - 5.23.1 总长度：`~5000 / ~6459` → `4361 / 1226`（DEFAULT act, 空 rules）
  - 5.23.2 Base prompt：`~2000 / ~2000` → `3695 / 828`
  - 5.23.3 工具说明：标注"嵌入 base prompt，非独立段"
  - 5.23.4 skills 长度：标注"默认关闭，长度 0"
  - 5.23.5 rules 长度：`~500 / ~500` → `606 / 334`（MODE_TAG only）

---

## 六、验证方法

### 6.1 字符数验证

```powershell
# Cline DEFAULT base prompt 字符数
$cline = Get-Content "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Raw
$match = [regex]::Match($cline, "export const DEFAULT_CLINE_SYSTEM_PROMPT = ``([^``]+)``", [System.Text.RegularExpressions.RegexOptions]::Singleline)
$match.Groups[1].Value.Length  # 预期: 3695

# Charles DEFAULT base prompt 字符数
$charles = Get-Content "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Raw
$match = [regex]::Match($charles, 'DEFAULT_CHARLES_SYSTEM_PROMPT = """([^"]+)"""', [System.Text.RegularExpressions.RegexOptions]::Singleline)
$match.Groups[1].Value.Length  # 预期: 828
```

### 6.2 Token 估算验证

```powershell
# Charles estimate_tokens 函数验证
python -c "from agent.context import estimate_tokens; print(estimate_tokens('你是 Charles'))"
# 预期: 7（4 中文字符 × 1.5 + 1 空格 / 4 = 6.25 → 7）
```

### 6.3 nanobot 残留验证

```powershell
# 在 System Prompt 相关文件中搜索 nanobot
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 1 处（L275 注释残留）

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\plan_mode.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处
```

### 6.4 完整 System Prompt 渲染验证

```powershell
# 渲染 Charles DEFAULT act 模式完整 system prompt
python -c "
import sys; sys.path.insert(0, r'e:\jikeAI\code\CASE-AI量化系统')
from agent.context import SystemPromptBuilder
b = SystemPromptBuilder(working_dir='.', ide_name='Charles Web')
prompt = b.build(task_type='general', provider_id='qwen')
print(f'总字符数: {len(prompt)}')
print(f'Token 估算: {len(prompt) // 4}')  # 简单估算
"
# 预期: 总字符数约 1200-1500（含实际 rules + metadata）
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表估值 | 实测数据 | 状态 | 说明 |
|--------|----------|---------|------|------|
| 5.23.1 总长度 | ~5000 / ~6459 chars | 4361 / 1226 chars（act, 空 rules） | **估值偏高** | Charles 实测远低于估值，计划可能含 enhancements 段 |
| 5.23.2 Base prompt 长度 | ~2000 / ~2000 chars | 3695 / 828 chars | **估值偏差大** | Cline 实测高于估值，Charles 实测远低于估值 |
| 5.23.3 工具说明长度 | ~1500 / ~1500 chars | 嵌入 base（Cline ~600 / Charles ~200） | **概念错误** | 工具说明非独立段，嵌入 base prompt |
| 5.23.4 skills 长度 | ~500 / ~800 chars | 0 / 0 chars（默认关闭） | **估值错误** | skills 段默认关闭，默认场景长度为 0 |
| 5.23.5 rules 长度 | ~500 / ~500 chars | 606 / 334 chars（MODE_TAG only） | **接近** | act 模式仅 MODE_TAG；plan 模式 Cline 2091 / Charles 1079 |

**计划表标注总结**：5 项中 4 项估值偏差较大，1 项接近实测。计划表 P5.23 整体偏保守，未区分默认场景与增强场景，未考虑语言差异对字符数的影响。建议按本报告实测数据修正。
