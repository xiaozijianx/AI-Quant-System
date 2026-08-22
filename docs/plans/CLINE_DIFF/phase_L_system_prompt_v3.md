# Phase L v3: System Prompt 构造 — 逻辑级对比报告

> 生成时间：2026-07-28
> 对比基础：Cline 源码（third_party/cline/sdk/packages/shared/src/prompt/）+ Charles 当前实现
> 核心发现：上一轮重构完成了 base+rules 两层结构，但仍有 **7 处逻辑级偏差** 和 **3 处 nanobot 残留**

---

## 一、Cline 的真实构造链路（源码确认）

### 1.1 入口函数

**文件**: `sdk/packages/shared/src/prompt/cline.ts` L110-165

```typescript
export function buildClineSystemPrompt(options: ClineSystemPromptOptions): string {
    const basePrompt = mode === "yolo" ? YOLO_CLINE_SYSTEM_PROMPT : DEFAULT_CLINE_SYSTEM_PROMPT;

    // 关键：MODE_TAG 和 PLAN_MODE 作为 rule 注入，不在 base prompt 中
    const effectiveRules = [
        rules,
        MODE_TAG_INSTRUCTIONS,              // ← 作为 rule
        mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined,  // ← 作为 rule
    ].filter(Boolean).join("\n\n");

    return basePrompt
        .replace("{{PLATFORM_NAME}}", platform)
        .replace("{{CWD}}", workspaceRoot)
        .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
        .replace("{{IDE_NAME}}", ide)
        .replace("{{CLINE_METADATA}}", isCline ? buildWorkspaceMetadata(...) : "")
        .replace("{{CLINE_RULES}}", effectiveRules)  // ← rules 在最后
        .trim();
}
```

### 1.2 Base Prompt 模板

**文件**: `sdk/packages/shared/src/prompt/system.ts`

```text
身份定义（You are Cline...）
通用行为规则（gather context / use tools / parallelism / absolute paths）
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
行为约束（verify / complete / proactive）
{{CLINE_RULES}}        ← rules 在这里（含 MODE_TAG + PLAN_MODE）
{{CLINE_METADATA}}     ← metadata 在最后
```

**关键发现**：
- Base prompt 只有 **2 个占位符**：`{{CLINE_RULES}}` 和 `{{CLINE_METADATA}}`
- `MODE_TAG_INSTRUCTIONS` **不在** base prompt 中，而是作为 effectiveRules 的一部分
- `PLAN_MODE_INSTRUCTIONS` **不在** base prompt 中，也是作为 effectiveRules 的一部分
- `<env>` 段直接写在模板中，不是占位符

### 1.3 runtime-builder.ts 的真实职责

**文件**: `sdk/packages/core/src/runtime/orchestration/runtime-builder.ts`

**关键发现**：`runtime-builder.ts` **根本不构建 system prompt**！

它的 `DefaultRuntimeBuilder.build()` 方法只负责：
1. 构建 runtime environment（工具列表）
2. 加载 MCP 工具
3. 配置 team runtime
4. 设置 completionPolicy
5. 注册 userInstructionService（但 system prompt 的拼排在 cline.ts 中完成）

system prompt 的实际构建在 `cline.ts` 的 `buildClineSystemPrompt()` 中。

---

## 二、Charles 当前实现

### 2.1 入口函数

**文件**: `agent/context.py` L195-227

```python
def build(self, task_type: str = "general") -> str:
    base = DEFAULT_CHARLES_SYSTEM_PROMPT
    base = base.replace("{{PLATFORM_NAME}}", platform.platform(terse=True))
    base = base.replace("{{CURRENT_DATE}}", date.today().isoformat())
    base = base.replace("{{IDE_NAME}}", self.ide_name)
    base = base.replace("{{CWD}}", self.working_dir)
    plan_prompt = self._load_mode_prompt() or ""
    base = base.replace("{{PLAN_MODE_INSTRUCTIONS}}", plan_prompt)
    metadata = self._build_metadata()
    base = base.replace("{{CHARLES_METADATA}}", metadata)
    rules = self._build_rules(task_type)
    base = base.replace("{{CHARLES_RULES}}", rules)
    return base.strip()
```

### 2.2 Base Prompt 模板

**文件**: `agent/prompts/charles_system_prompt.py`

```text
身份定义（你是 Charles...）
通用行为规则（6 条）
工具调用规则
<env>
平台: {{PLATFORM_NAME}}
日期: {{CURRENT_DATE}}
IDE: {{IDE_NAME}}
工作目录: {{CWD}}
</env>
用户消息模式标签（mode tag 说明）        ← 硬编码在 base 中
{{PLAN_MODE_INSTRUCTIONS}}               ← 独立占位符
{{CHARLES_METADATA}}                     ← metadata 在 rules 之前
{{CHARLES_RULES}}                        ← rules 在最后
```

---

## 三、逻辑级差异矩阵（7 处偏差 + 3 处 nanobot 残留）

### A. 结构级偏差（影响 prompt 结构语义）

| # | 维度 | Cline 实现 | Charles 实现 | 差异类型 | 严重度 |
|---|------|-----------|-------------|---------|--------|
| **S1** | MODE_TAG 位置 | 作为 effectiveRules 注入到 `{{CLINE_RULES}}` | 硬编码在 base prompt 模板中 | **结构偏差** | P1 |
| **S2** | PLAN_MODE 位置 | 作为 effectiveRules 注入到 `{{CLINE_RULES}}` | 独立占位符 `{{PLAN_MODE_INSTRUCTIONS}}` | **结构偏差** | P1 |
| **S3** | Metadata vs Rules 顺序 | `{{CLINE_RULES}}` → `{{CLINE_METADATA}}`（rules 先，metadata 后） | `{{CHARLES_METADATA}}` → `{{CHARLES_RULES}}`（metadata 先，rules 后） | **顺序偏差** | P2 |
| **S4** | 占位符数量 | 2 个（`{{CLINE_RULES}}` + `{{CLINE_METADATA}}`） | 4 个（多了 `{{PLAN_MODE_INSTRUCTIONS}}` + mode tag 硬编码） | **结构偏差** | P2 |

### B. 逻辑级偏差（影响行为语义）

| # | 维度 | Cline 实现 | Charles 实现 | 差异类型 | 严重度 |
|---|------|-----------|-------------|---------|--------|
| **L1** | `<env>` 段字段格式 | `Platform: X / Date: X / IDE: X / Working Directory: X` | `平台: X / 日期: X / IDE: X / 工作目录: X` | **字段名语言** | P3 |
| **L2** | `<env>` 段字段顺序 | Platform → Date → IDE → Working Directory | 平台 → 日期 → IDE → 工作目录 | **顺序一致** | - |
| **L3** | metadata 内容 | workspace JSON（rootPath/hint/associatedRemoteUrls/gitCommit/gitBranch） | working_dir + ide_name + git_info | **内容差异** | P2 |
| **L4** | metadata 注入条件 | `isCline(providerId)` 时才注入，否则空字符串 | 始终注入 | **条件缺失** | P3 |

### C. Nanobot 残留（应清理但未清理）

| # | 维度 | 位置 | 问题 | 严重度 |
|---|------|------|------|--------|
| **N1** | docstring 描述 nanobot 架构 | `context.py` L1-33 | 文件头注释仍描述"identity → AGENTS.md → memory → skills → guidelines → rules"的 nanobot 11 层拼接，仍写"对标 nanobot" | **P1** |
| **N2** | `identity` 参数 | `context.py` L101, L134 + `server.py` L538 | Cline 用固定模板定义身份，不需要 identity 参数；server.py 仍传 `identity="你是 Charles，AI 投研情报官"` | **P2** |
| **N3** | `extra_sections` 参数 | `context.py` L106, L139, L302 | nanobot 风格的额外段落，Cline 无此概念；`_build_rules` 仍遍历 extra_sections 追加为 rule | **P3** |

### D. 职责分离差异（架构级）

| # | 维度 | Cline 实现 | Charles 实现 | 差异类型 | 严重度 |
|---|------|-----------|-------------|---------|--------|
| **A1** | runtime-builder 职责 | 只构建 runtime environment（工具/team/extensions） | SystemPromptBuilder 既构建 prompt 又加载 rules | **职责未分离** | P3 |
| **A2** | rules 注册机制 | ContributionRegistry + registerRule API | rules_loader 直接返回字符串 | **架构差异** | P3 |
| **A3** | rules 发现路径 | AGENTS.md / .clinerules / .cline/rules/*.md | agent_config/rules/*.md | **路径差异** | - |

---

## 四、关键差异详解

### 4.1 S1/S2: MODE_TAG 和 PLAN_MODE 的注入位置（最重要的逻辑偏差）

**Cline 的逻辑**：
```typescript
// cline.ts L145-151
const effectiveRules = [
    rules,                    // 用户规则
    MODE_TAG_INSTRUCTIONS,    // mode 标签说明
    mode === "plan" ? PLAN_MODE_INSTRUCTIONS : undefined,  // plan 契约
].filter(Boolean).join("\n\n");

// 注入到 {{CLINE_RULES}} 占位符
basePrompt.replace("{{CLINE_RULES}}", effectiveRules)
```

Cline 把 `MODE_TAG_INSTRUCTIONS` 和 `PLAN_MODE_INSTRUCTIONS` 都作为 **rule** 注入，它们和用户规则一起组成 `effectiveRules`，统一注入到 `{{CLINE_RULES}}` 占位符。

**Charles 的逻辑**：
```python
# context.py L195-227
base = base.replace("{{PLAN_MODE_INSTRUCTIONS}}", plan_prompt)  # 独立占位符
# ...
rules = self._build_rules(task_type)
base = base.replace("{{CHARLES_RULES}}", rules)  # rules 不含 MODE_TAG
```

Charles 把 mode tag 说明**硬编码**在 base prompt 模板中（`charles_system_prompt.py` L47-54），PLAN_MODE 用独立占位符 `{{PLAN_MODE_INSTRUCTIONS}}` 注入。这两者**不在** rules 中。

**影响**：
- 功能等价，但结构不对齐
- Cline 的方式更灵活（MODE_TAG 内容可动态调整），Charles 的方式更固定
- 如果未来需要根据 provider 动态调整 MODE_TAG 内容，Charles 的方式无法支持

### 4.2 S3: Metadata vs Rules 顺序

**Cline**: `{{CLINE_RULES}}` 在前，`{{CLINE_METADATA}}` 在后
```text
...
{{CLINE_RULES}}
{{CLINE_METADATA}}
```

**Charles**: `{{CHARLES_METADATA}}` 在前，`{{CHARLES_RULES}}` 在后
```text
...
{{PLAN_MODE_INSTRUCTIONS}}

{{CHARLES_METADATA}}

{{CHARLES_RULES}}
```

**影响**：顺序倒置。Cline 把 rules 放在 metadata 之前，意味着 rules 内容更靠近 base prompt 的行为规则部分，metadata 作为工作空间元数据放在最后。Charles 的顺序是 metadata 在 rules 之前。

### 4.3 N1: context.py docstring 仍描述 nanobot 架构

**当前**（`context.py` L1-33）：
```python
"""系统提示组装 + 上下文压缩 — 对标 Cline runtime-builder + compaction

SystemPromptBuilder:
    分层组装 system prompt（对标 Cline default → agent → custom → append）:
        1. identity（身份定义）
        2. AGENTS.md（引导文件）
        3. memory（记忆上下文，可选）
        4. always skills 指令（Level 2 自动加载）
        5. skills 摘要（Level 1，通过 use_skill 工具触发 Level 2）
        6. rules（任务规则文件）

    与 nanobot 的区别:
        ...

对标 nanobot:
    - agent/context.py build_system_prompt() L33-97
    - 组装顺序: identity → AGENTS.md → memory → skills → guidelines → rules
"""
```

**问题**：docstring 描述的是 nanobot 的 6 层拼接架构，但实际 `build()` 方法已经是 base+rules 两层结构。docstring 与代码逻辑不一致。

### 4.4 N2: identity 参数残留

**Cline**: 身份定义固定在 `DEFAULT_CLINE_SYSTEM_PROMPT` 模板第一行（"You are Cline..."），不接受外部传入。

**Charles**:
- `charles_system_prompt.py` 模板第一行已固定身份（"你是 Charles，专业的 AI 投研情报官"）
- 但 `SystemPromptBuilder.__init__` 仍接受 `identity` 参数
- `server.py` L538 仍传 `identity="你是 Charles，AI 投研情报官"`
- `build()` 方法中 `identity` 参数完全未使用（base prompt 模板已包含身份）

**影响**：`identity` 参数是死代码，传入但不使用，容易造成混淆。

### 4.5 N3: extra_sections 参数残留

**Cline**: 无 extra_sections 概念。所有内容要么在 base prompt 模板中，要么作为 rule 注入。

**Charles**:
- `SystemPromptBuilder.__init__` 接受 `extra_sections: dict[str, str]`
- `_build_rules()` L302 遍历 extra_sections，每个条目作为 rule 追加
- 当前无调用方传入 extra_sections（server.py 未传），但代码路径仍存在

**影响**：extra_sections 是 nanobot 风格的扩展机制，Cline 无此概念。保留它增加了复杂度但无实际使用。

### 4.6 L3: metadata 内容差异

**Cline** (`cline.ts` L47-86):
```typescript
function buildWorkspaceMetadata(rootPath, workspaceName, metadata) {
    // JSON 格式，包含 workspaces 对象
    {
        workspaces: {
            [rootPath]: {
                hint: workspaceName,
                associatedRemoteUrls: [...],
                latestGitCommitHash: "...",
                latestGitBranchName: "...",
            }
        }
    }
}
```

**Charles** (`context.py` L229-247):
```python
def _build_metadata(self) -> str:
    metadata = {
        "working_dir": self.working_dir,
        "ide_name": self.ide_name,
    }
    if git_info:
        metadata["git"] = git_info
    # 输出 <charles_metadata> JSON
```

**差异**：
- Cline 用 `workspaces` 嵌套结构，Charles 用扁平结构
- Cline 包含 `hint` / `associatedRemoteUrls` / `latestGitCommitHash` / `latestGitBranchName`
- Charles 包含 `working_dir` / `ide_name` / `git.branch` / `git.commit` / `git.remote`
- Cline 的 metadata 包裹在 `# Workspace Configuration` 标记下

### 4.7 L4: metadata 注入条件

**Cline**: `isCline(providerId)` 时才注入 metadata，否则 `{{CLINE_METADATA}}` 替换为空字符串。
**Charles**: 始终注入 metadata，无 provider 条件判断。

---

## 五、修复方案

### 5.1 P1 修复（必须）

#### 修复 S1/S2: MODE_TAG 和 PLAN_MODE 改为 rule 注入

**目标**：将 MODE_TAG_INSTRUCTIONS 和 PLAN_MODE_INSTRUCTIONS 从 base prompt 模板中移出，改为作为 effectiveRules 的一部分注入到 `{{CHARLES_RULES}}`。

**修改文件**：
1. `agent/prompts/charles_system_prompt.py`
   - 移除硬编码的"用户消息模式标签"段
   - 移除 `{{PLAN_MODE_INSTRUCTIONS}}` 占位符
   - 调整顺序：`{{CHARLES_RULES}}` → `{{CHARLES_METADATA}}`（对齐 Cline）

2. `agent/context.py`
   - `build()` 方法中不再替换 `{{PLAN_MODE_INSTRUCTIONS}}`
   - `_build_rules()` 中将 MODE_TAG 和 PLAN_MODE 作为 rule 追加到 rules 末尾

#### 修复 N1: 清理 context.py docstring

**修改文件**: `agent/context.py` L1-33
- 移除 nanobot 架构描述
- 移除"对标 nanobot"引用
- 改为描述 base+rules 两层结构

### 5.2 P2 修复（建议）

#### 修复 N2: 移除 identity 参数

**修改文件**：
1. `agent/context.py` — `__init__` 移除 `identity` 参数，移除 `self.identity`
2. `agent/server.py` L538 — 移除 `identity="你是 Charles，AI 投研情报官"`

#### 修复 S3: 调整 metadata/rules 顺序

**修改文件**: `agent/prompts/charles_system_prompt.py`
- 将 `{{CHARLES_RULES}}` 移到 `{{CHARLES_METADATA}}` 之前

#### 修复 L3: 对齐 metadata 内容

**修改文件**: `agent/context.py` `_build_metadata()`
- 改为 `workspaces` 嵌套结构
- 包含 `hint` 字段（用 ide_name 或目录名）

### 5.3 P3 修复（可选）

#### 修复 N3: 移除 extra_sections

**修改文件**: `agent/context.py`
- `__init__` 移除 `extra_sections` 参数
- `_build_rules()` 移除 extra_sections 遍历

#### 修复 L4: 添加 metadata 注入条件

**修改文件**: `agent/context.py`
- 添加 provider_id 参数
- 仅当 provider 为 Charles 原生时注入 metadata

---

## 六、修复后的目标结构

### 6.1 Base Prompt 模板（修复后）

```text
你是 Charles，专业的 AI 投研情报官...

## 通用行为规则
1. 上下文优先
2. 任务拆解
3. 技能触发
4. 工具选择
5. 绝对路径
6. 结果导向

## 工具调用规则
...

<env>
平台: {{PLATFORM_NAME}}
日期: {{CURRENT_DATE}}
IDE: {{IDE_NAME}}
工作目录: {{CWD}}
</env>

行为约束（verify / complete / proactive）

{{CHARLES_RULES}}
{{CHARLES_METADATA}}
```

### 6.2 Rules 内容（修复后）

```text
# Rules

## AGENTS
{AGENTS.md body}

## general
{general.md body}

## charles-mode-tag
{MODE_TAG_INSTRUCTIONS 内容}

## charles-plan-mode
{PLAN_MODE_INSTRUCTIONS 内容（仅 plan 模式）}
```

---

## 七、一致性统计

| 类别 | 数量 |
|------|------|
| 完全一致 | 5 项 |
| 结构偏差 | 4 项 (S1-S4) |
| 逻辑偏差 | 4 项 (L1-L4) |
| Nanobot 残留 | 3 项 (N1-N3) |
| 架构差异 | 3 项 (A1-A3) |
| **需修复** | **7 项 (P1: 2, P2: 3, P3: 2)** |

---

## 八、与之前对比方案的差异

### 8.1 之前方案的问题

之前的 `SYSTEM_PROMPT_REFACTOR_PLAN.md` 存在以下误判：

1. **误判 runtime-builder.ts 的职责**：之前认为 runtime-builder.ts 负责 system prompt 构建，但实际上它只构建 runtime environment
2. **误判 MODE_TAG 的位置**：之前认为 MODE_TAG 在 base prompt 中，但实际上 Cline 把它作为 rule 注入
3. **误判 PLAN_MODE 的位置**：同上
4. **未发现 metadata/rules 顺序差异**：之前未对比这个细节
5. **未发现 identity 参数是死代码**：之前保留了这个参数

### 8.2 本报告的修正

1. **准确识别了 Cline 的真实构造链路**：`buildClineSystemPrompt()` 在 `cline.ts` 中，不在 `runtime-builder.ts` 中
2. **准确识别了 effectiveRules 机制**：MODE_TAG 和 PLAN_MODE 作为 rule 注入
3. **发现了 metadata/rules 顺序倒置**
4. **发现了 identity 参数是 nanobot 残留死代码**
5. **发现了 docstring 与代码逻辑不一致**

---

**结论**：当前实现已完成 base+rules 两层结构的基本对齐，但在 MODE_TAG/PLAN_MODE 注入位置、metadata/rules 顺序、identity 参数残留、docstring 一致性等方面仍有逻辑级偏差。建议按 P1→P2→P3 顺序修复。
