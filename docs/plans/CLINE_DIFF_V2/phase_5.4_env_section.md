# Phase 5.4 `<env>` 段对比报告

## 1. 执行摘要

本报告对 CASE-AI 量化系统（Charles）与 Cline 的 `<env>` 段进行逐项对比，覆盖 env 段内容（时间、平台、工作目录、shell/IDE 等）、标签格式、字段名、占位符替换机制、段落位置等维度，并区分注释残留与实现逻辑残留。

核心发现：

- **生产路径已对齐**：Charles 生产使用的 `charles_system_prompt.py` 模板中 `<env>` 段与 Cline `system.ts` 高度对齐 —— 字段名（英文）、字段顺序、占位符（`{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}`）、编号格式（`1. 2. 3. 4.`）均一致。
- **两处差异**：(a) Charles 缺少 Cline 的 `Environment you are running in:` 引导句；(b) Charles 在 `context.py` 中保留了一个废弃的 `_build_environment()` 方法，使用中文字段名 + git 字段，与生产路径不一致，属于历史遗留。
- **计划文件描述过时**：`AGENT_COMPARISON_PLAN_V2.md` L1846-1854 描述 Charles env 段使用中文字段名（平台/日期/工作目录），这是基于废弃方法 `_build_environment()` 的旧实现，与实际生产路径（英文字段名）不符。
- **nanobot 残留**：env 段构建逻辑本身无 nanobot 残留；仅 `context.py` L275 `extra_sections` 参数的 docstring 中有 1 处 nanobot 注释残留，与 env 段无直接关系。
- **git 字段处理对齐**：Charles 与 Cline 均将 git 状态放在 metadata 段（`# Workspace Configuration` JSON），不放在 `<env>` 段中；仅废弃的 `_build_environment()` 方法把 git 字段塞进 env 段，与 Cline 设计不一致。

整体结论：**Charles env 段生产路径已与 Cline 对齐**，差异主要在引导句缺失和废弃方法残留两点，严重程度低。

## 2. 检查范围与方法

### 2.1 检查范围

**Cline 源码**：
- `third_party/cline/sdk/packages/shared/src/prompt/system.ts`（base prompt 模板，env 段硬编码）
- `third_party/cline/sdk/packages/shared/src/prompt/cline.ts`（buildClineSystemPrompt 占位符替换）

**Charles 源码**：
- `agent/prompts/charles_system_prompt.py`（base prompt 模板，env 段硬编码 — **生产路径**）
- `agent/context.py`（`build_charles_system_prompt` 占位符替换 + `_build_environment` 废弃方法）

**计划文件**：
- `AGENT_COMPARISON_PLAN_V2.md` L1834-1866（P5.4 段对比计划）

**nanobot 残留检索**：
- 在 `agent/` 目录下检索 `nanobot` 关键字，重点筛查与 env 段构建相关的残留。

### 2.2 检查方法

1. **逐文件人工审阅**：完整读取 Cline `system.ts` / `cline.ts` 与 Charles `charles_system_prompt.py` / `context.py` 中 env 段相关代码。
2. **关键字检索**：使用 Grep 检索 `<env>`、`Environment you are running in`、`_build_environment`、`nanobot` 等关键字做交叉验证。
3. **区分注释残留 vs 实现逻辑残留**：注释残留指 docstring/注释中提到 nanobot；实现逻辑残留指代码或模板在功能层面消费 nanobot 风格机制。
4. **生产路径 vs 废弃方法**：明确区分 Charles 当前生产路径（`charles_system_prompt.py` 模板）与废弃方法（`context.py::_build_environment`）的差异，避免误判。

## 3. 逐文件检查结果

### 3.1 Cline `system.ts`（base prompt 模板）

**文件路径**：`third_party/cline/sdk/packages/shared/src/prompt/system.ts`

**DEFAULT 模板 env 段**（L7-13）：
```
Environment you are running in:
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

**YOLO 模板 env 段**（L52-58）：与 DEFAULT 完全一致。

**特征**：
- 字段名：英文（Platform / Date / IDE / Working Directory）
- 字段顺序：Platform → Date → IDE → Working Directory
- 编号格式：`1. 2. 3. 4.`（带点号）
- 占位符：`{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}`
- 引导句：`Environment you are running in:`（在 `<env>` 标签上方）
- git 字段：不在 env 段（git 状态在 metadata 段 `# Workspace Configuration` JSON 中）
- Shell 字段：无（IDE 字段已涵盖运行环境）

### 3.2 Cline `cline.ts`（占位符替换）

**文件路径**：`third_party/cline/sdk/packages/shared/src/prompt/cline.ts`

**替换逻辑**（L153-165）：
```typescript
return basePrompt
    .replace("{{PLATFORM_NAME}}", platform)
    .replace("{{CWD}}", workspaceRoot)
    .replace("{{CURRENT_DATE}}", new Date().toLocaleDateString())
    .replace("{{IDE_NAME}}", ide)
    .replace("{{CLINE_METADATA}}", ...)
    .replace("{{CLINE_RULES}}", effectiveRules)
    .trim();
```

**特征**：
- `platform` 默认 `"unknown"`（L116）
- `ide` 默认 `"Terminal Shell"`（L114）
- `{{CURRENT_DATE}}` 用 `new Date().toLocaleDateString()` 生成（本地化日期格式）
- `{{CWD}}` 用 `workspaceRoot` 替换（L123）

### 3.3 Charles `charles_system_prompt.py`（生产路径 — base prompt 模板）

**文件路径**：`agent/prompts/charles_system_prompt.py`

**DEFAULT 模板 env 段**（L49-54）：
```
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

**YOLO 模板 env 段**（L74-79）：与 DEFAULT 完全一致。

**特征**：
- 字段名：英文（Platform / Date / IDE / Working Directory）— **与 Cline 一致**
- 字段顺序：Platform → Date → IDE → Working Directory — **与 Cline 一致**
- 编号格式：`1. 2. 3. 4.`（带点号）— **与 Cline 一致**
- 占位符：`{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}` — **与 Cline 一致**
- 引导句：**无**（缺少 `Environment you are running in:` 引导句）
- git 字段：不在 env 段（在 metadata 段 `# Workspace Configuration` JSON 中）— **与 Cline 一致**
- Shell 字段：无 — **与 Cline 一致**

### 3.4 Charles `context.py`（占位符替换 + 废弃方法）

**文件路径**：`agent/context.py`

#### 3.4.1 生产路径：`build_charles_system_prompt` 函数（L78-127）

```python
prompt = prompt.replace("{{PLATFORM_NAME}}", platform_name)
prompt = prompt.replace("{{CURRENT_DATE}}", current_date)
prompt = prompt.replace("{{IDE_NAME}}", ide_name)
prompt = prompt.replace("{{CWD}}", working_dir)
```

**调用方传入值**（`SystemPromptBuilder.build` L382-391）：
- `platform_name=platform.platform(terse=True)`（L384）
- `current_date=date.today().isoformat()`（L385）— **ISO 8601 格式，与 Cline 的 `toLocaleDateString()` 不同**
- `ide_name=self.ide_name`（默认 `"Charles Web"`，L262）
- `working_dir=self.working_dir`（默认 `os.getcwd()`，L295）

**特征**：
- 占位符替换顺序与 Cline 一致
- 日期格式差异：Charles 用 ISO 8601（`2026-07-29`），Cline 用 `toLocaleDateString()`（本地化格式，如 `7/29/2026`）
- IDE 默认值差异：Charles 默认 `"Charles Web"`，Cline 默认 `"Terminal Shell"`

#### 3.4.2 废弃方法：`_build_environment`（L649-681）

```python
def _build_environment(self) -> str:
    """构建运行环境信息段 — 保留方法供测试/外部调用

    注意：新 build() 中 <env> 段由 base prompt 模板直接构造，
    但本方法保留原输出格式（含 git 字段）以维持向后兼容。
    """
    ...
    lines = [
        "<env>",
        f"工作目录: {self.working_dir}",
        f"平台: {plat}",
        f"日期: {today}",
        f"IDE: {self.ide_name}",
    ]
    git_info = self._read_git_state()
    if git_info.get("branch"):
        lines.append(f"Git 分支: {git_info['branch']}")
    if git_info.get("commit"):
        lines.append(f"Git 提交: {git_info['commit']}")
    if git_info.get("remote"):
        lines.append(f"Git 远端: {git_info['remote']}")
    lines.append("</env>")
    return "\n".join(lines)
```

**调用情况**（Grep 检索结果）：
- 生产代码：无调用（`build()` 方法 L348-391 不调用此方法）
- 测试代码：`tests/test_stage4_context_prompt.py` L133, L143, L304, L322 调用
- 注释明确说"新 build() 中 `<env>` 段由 base prompt 模板直接构造"

**特征**：
- 字段名：**中文**（工作目录 / 平台 / 日期 / IDE / Git 分支 / Git 提交 / Git 远端）
- 字段顺序：工作目录 → 平台 → 日期 → IDE → Git 字段（与 Cline 顺序不同）
- 编号格式：**无编号**（与 Cline 的 `1. 2. 3. 4.` 不同）
- git 字段：**塞进 env 段**（与 Cline 设计不一致，Cline 把 git 放在 metadata 段）
- **这是计划文件 P5.4 描述的来源**，但实际生产路径不使用此方法

### 3.5 nanobot 残留检索

**检索范围**：`agent/` 目录全量检索 `nanobot` 关键字。

**与 env 段构建相关的残留**：无。`context.py` 中与 env 段相关的代码（L78-127、L649-681）均未提到 nanobot。

**`context.py` 中的 nanobot 残留**（共 1 处，与 env 段无关）：
- L275：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。` — 这是 `__init__` 参数 `extra_sections` 的 docstring，与 env 段构建无关。

**其他文件中的 nanobot 残留**（共 50+ 处，均与 env 段无关）：
- `agent/providers/qwen.py`：7 处（对标 nanobot openai_compat_provider.py）
- `agent/server.py`：3 处（对标 nanobot routes/chat.py）
- `agent/session.py`：2 处（对标 nanobot session_key）
- `agent/skills/`：10+ 处（对标 nanobot SkillsLoader，已在 Phase 4.20 详查）
- `agent/tools/`：20+ 处（对标 nanobot ShellTool/FilesystemTool/WebSearchTool）

这些残留属于其他模块的对标说明，不在本报告范围内。

## 4. 对比表

### 4.1 生产路径对比（Charles `charles_system_prompt.py` vs Cline `system.ts`）

| # | 对比项 | Cline（system.ts） | Charles（charles_system_prompt.py） | 关键差异 |
|---|--------|-------------------|-------------------------------------|---------|
| 5.4.1 | `<env>` 标签 | 是 | 是 | 已对齐 |
| 5.4.2 | Platform 字段名 | `Platform` | `Platform` | 已对齐 |
| 5.4.3 | Date 字段名 | `Date` | `Date` | 已对齐 |
| 5.4.4 | IDE 字段名 | `IDE` | `IDE` | 已对齐 |
| 5.4.5 | Working Directory 字段名 | `Working Directory` | `Working Directory` | 已对齐 |
| 5.4.6 | 字段顺序 | Platform → Date → IDE → Working Directory | Platform → Date → IDE → Working Directory | 已对齐 |
| 5.4.7 | 编号格式 | `1. 2. 3. 4.` | `1. 2. 3. 4.` | 已对齐 |
| 5.4.8 | 占位符 | `{{PLATFORM_NAME}}` 等 4 个 | `{{PLATFORM_NAME}}` 等 4 个 | 已对齐 |
| 5.4.9 | 引导句 | `Environment you are running in:` | 无 | **Charles 缺失**（L1 差距） |
| 5.4.10 | 日期格式 | `toLocaleDateString()`（本地化） | `date.today().isoformat()`（ISO 8601） | **L1 差距**（格式不同） |
| 5.4.11 | IDE 默认值 | `Terminal Shell` | `Charles Web` | **L1 差距**（场景差异，合理） |
| 5.4.12 | git 字段 | 不在 env 段（在 metadata 段） | 不在 env 段（在 metadata 段） | 已对齐 |
| 5.4.13 | Shell 字段 | 无（IDE 涵盖） | 无（IDE 涵盖） | 已对齐 |
| 5.4.14 | DEFAULT 与 YOLO 一致 | 是 | 是 | 已对齐 |
| 5.4.15 | 段落位置 | 第 2 段（身份/规则后，rules/metadata 前） | 第 2 段（身份/规则后，rules/metadata 前） | 已对齐 |

### 4.2 废弃方法对比（Charles `context.py::_build_environment` vs Cline `system.ts`）

| # | 对比项 | Cline（system.ts） | Charles（context.py::_build_environment） | 关键差异 |
|---|--------|-------------------|------------------------------------------|---------|
| 5.4.16 | 字段名语言 | 英文 | **中文**（工作目录/平台/日期/IDE） | L1 差距（中文） |
| 5.4.17 | 字段顺序 | Platform → Date → IDE → Working Directory | **工作目录 → 平台 → 日期 → IDE** | L1 差距（顺序不同） |
| 5.4.18 | 编号格式 | `1. 2. 3. 4.` | **无编号** | L1 差距 |
| 5.4.19 | git 字段 | 不在 env 段 | **塞进 env 段**（Git 分支/提交/远端） | **L2 差距**（设计不一致） |
| 5.4.20 | 是否在生产路径 | 是 | **否**（仅测试调用） | — |
| 5.4.21 | 占位符机制 | 模板占位符替换 | **直接 f-string 拼接** | L2 差距（机制不同） |

## 5. nanobot 残留分析

### 5.1 env 段构建逻辑的 nanobot 残留

**结论**：无。

**检查依据**：
- `charles_system_prompt.py`（生产路径）：env 段模板与 Cline 一致，无 nanobot 风格。
- `context.py::build_charles_system_prompt`（生产路径）：占位符替换逻辑与 Cline 一致，无 nanobot 风格。
- `context.py::_build_environment`（废弃方法）：虽然使用中文字段名 + git 字段塞进 env 段，但这是早期 Cline 对标残留（Stage 4 P1 阶段实现），并非 nanobot 风格 —— nanobot 的 env 段也是英文且不含 git 字段。

### 5.2 env 段周边代码的 nanobot 注释残留

**结论**：1 处，与 env 段无直接关系。

**残留详情**：
- `context.py` L275：`extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。`
  - 位置：`SystemPromptBuilder.__init__` 的 `extra_sections` 参数 docstring
  - 性质：注释残留（非实现逻辑残留）
  - 与 env 段关系：无（`extra_sections` 是已废弃的参数，当前无调用方传入）
  - 严重程度：低

### 5.3 注释残留 vs 实现逻辑残留

| 类别 | 数量 | 位置 | 严重程度 |
|---|---|---|---|
| 注释残留（env 段相关） | 0 | — | 无 |
| 实现逻辑残留（env 段相关） | 0 | — | 无 |
| 注释残留（env 段周边，extra_sections） | 1 | context.py L275 | 低 |
| 实现逻辑残留（extra_sections） | 0 | — | 无（参数已废弃，无调用） |

## 6. 与计划文件的差异说明

### 6.1 计划文件描述过时

`AGENT_COMPARISON_PLAN_V2.md` L1846-1854 描述 Charles env 段如下：
```
**Charles 实现**（charles_system_prompt.py）：
<env>
平台: {platform}
日期: {date}
IDE: {ide}
工作目录: {cwd}
</env>
```

**实际 `charles_system_prompt.py` 中的 env 段**（L49-54）：
```
<env>
1. Platform: {{PLATFORM_NAME}}
2. Date: {{CURRENT_DATE}}
3. IDE: {{IDE_NAME}}
4. Working Directory: {{CWD}}
</env>
```

**差异分析**：
- 计划文件描述的是**中文字段名 + 无编号**格式，与实际生产模板（英文字段名 + 编号）不符。
- 计划文件的描述来源应是 `context.py::_build_environment()` 废弃方法的输出格式（中文 + 无编号 + git 字段），而非生产模板。
- 计划文件 L1846 标注的源文件是 `charles_system_prompt.py`，但描述的内容却来自 `context.py::_build_environment()`，属于标注与内容不匹配。

### 6.2 计划文件对比表过时

计划文件 L1856-1866 的对比表声称 Charles 使用中文字段名（平台/日期/工作目录），标注为"L1 差距（中文）"。实际上生产路径已改为英文字段名，L1 差距不存在。

**实际差异仅剩**：
- 5.4.9：引导句缺失（Charles 无 `Environment you are running in:`）
- 5.4.10：日期格式不同（ISO 8601 vs 本地化）
- 5.4.11：IDE 默认值不同（`Charles Web` vs `Terminal Shell`，场景差异合理）

## 7. 修复建议

### 7.1 P0 优先级（高严重程度）

无。生产路径已与 Cline 对齐，无高严重程度差异。

### 7.2 P1 优先级（中严重程度，影响一致性）

#### P1-1: 删除或改造废弃的 `_build_environment()` 方法

**影响范围**：`agent/context.py` L649-681

**问题**：该方法使用中文字段名 + 无编号 + git 字段塞进 env 段，与生产路径（`charles_system_prompt.py` 英文模板）不一致，且被 `tests/test_stage4_context_prompt.py` L133/L143/L304/L322 调用。该方法的存在导致：
- 计划文件描述过时（误以为生产路径使用中文）
- 测试验证的是废弃方法而非生产路径
- 维护成本高（两套 env 段实现）

**修复方案**：
1. **方案 A（推荐）**：删除 `_build_environment()` 方法，同步修改 `tests/test_stage4_context_prompt.py` 中 4 处调用，改为验证 `build_charles_system_prompt()` 替换后的 env 段输出。
2. **方案 B**：保留方法但改写为调用生产路径（`build_charles_system_prompt` 替换 base 模板中的 env 占位符），输出与生产路径一致的英文格式。

**理由**：用户规则"之前完成正确的功能，尽量不要修改"——生产路径已正确，废弃方法属于历史遗留，删除或改造不影响生产功能。

#### P1-2: 补齐引导句 `Environment you are running in:`

**影响范围**：`agent/prompts/charles_system_prompt.py` L49-54、L74-79

**问题**：Cline 在 `<env>` 标签上方有引导句 `Environment you are running in:`，Charles 缺失。这是 L1 差距。

**修复方案**：在 DEFAULT 和 YOLO 两个模板的 `<env>` 标签上方各加一行 `Environment you are running in:`。

**示例**（DEFAULT 模板修改前）：
```
<env>
1. Platform: {{PLATFORM_NAME}}
...
</env>
```

**示例**（修改后，Cline 风格）：
```
Environment you are running in:
<env>
1. Platform: {{PLATFORM_NAME}}
...
</env>
```

**理由**：对齐 Cline，引导句帮助 LLM 理解 env 段的语义上下文。

### 7.3 P2 优先级（低严重程度，工程优化）

#### P2-1: 清理 `extra_sections` 参数的 nanobot 注释

**影响范围**：`agent/context.py` L275、L292、L530-537

**问题**：`extra_sections` 参数已废弃（docstring 明确说"当前无调用方传入"），但保留参数签名和 `_build_rules` 中的处理逻辑（L530-537），且 docstring 提到 nanobot。

**修复方案**：
1. 移除 `__init__` 的 `extra_sections` 参数（需确认无外部调用方）
2. 移除 `_build_rules` 中 L530-537 的 `extra_sections` 处理逻辑
3. 移除 L275 docstring 中的 nanobot 注释

**理由**：用户规则"代码中不要有 fallback"+"不要 gold-plate"，废弃参数应及时清理。但需先确认无外部调用方（如测试代码或其他模块）。

#### P2-2: 更新计划文件 P5.4 段

**影响范围**：`AGENT_COMPARISON_PLAN_V2.md` L1846-1866

**问题**：计划文件描述 Charles env 段使用中文字段名，与实际生产路径（英文）不符。

**修复方案**：更新计划文件 P5.4 段的 Charles 实现描述，改为反映 `charles_system_prompt.py` 的实际英文模板；同步更新对比表，移除"L1 差距（中文）"标注，改为标注实际差异（引导句缺失、日期格式）。

#### P2-3: 日期格式对齐（可选）

**影响范围**：`agent/context.py` L385

**问题**：Charles 用 `date.today().isoformat()`（`2026-07-29`），Cline 用 `new Date().toLocaleDateString()`（本地化格式，如 `7/29/2026`）。

**修复方案**：保持现状。ISO 8601 格式更清晰、无歧义，且跨locale 稳定，是合理增强。Cline 的 `toLocaleDateString()` 受运行环境 locale 影响，反而不如 ISO 8601 可靠。

**理由**：这是 Charles 合理增强，不需要对齐。

## 8. 验证方法建议

### 8.1 自动化验证

1. **生产路径 env 段输出验证**：
   ```powershell
   python -c "
   from agent.context import SystemPromptBuilder
   builder = SystemPromptBuilder(working_dir='e:/jikeAI/code', ide_name='Charles Web')
   prompt = builder.build()
   env_start = prompt.find('<env>')
   env_end = prompt.find('</env>') + len('</env>')
   print(prompt[env_start:env_end])
   "
   ```
   预期输出：
   ```
   <env>
   1. Platform: Windows-...
   2. Date: 2026-07-29
   3. IDE: Charles Web
   4. Working Directory: e:/jikeAI/code
   </env>
   ```

2. **字段名英文化验证**：
   ```powershell
   python -c "
   from agent.prompts.charles_system_prompt import DEFAULT_CHARLES_SYSTEM_PROMPT, YOLO_CHARLES_SYSTEM_PROMPT
   assert 'Platform:' in DEFAULT_CHARLES_SYSTEM_PROMPT
   assert 'Date:' in DEFAULT_CHARLES_SYSTEM_PROMPT
   assert 'IDE:' in DEFAULT_CHARLES_SYSTEM_PROMPT
   assert 'Working Directory:' in DEFAULT_CHARLES_SYSTEM_PROMPT
   assert '平台' not in DEFAULT_CHARLES_SYSTEM_PROMPT
   assert '工作目录' not in DEFAULT_CHARLES_SYSTEM_PROMPT
   assert 'Platform:' in YOLO_CHARLES_SYSTEM_PROMPT
   print('OK: env 段字段名为英文')
   "
   ```

3. **nanobot 残留检索**：
   ```powershell
   # 期望：env 段相关代码无 nanobot 残留
   Grep pattern="nanobot" path="agent/prompts/charles_system_prompt.py"   # 期望无匹配
   Grep pattern="nanobot" path="agent/context.py"                         # 期望仅 L275 一处（extra_sections 注释）
   ```

### 8.2 功能验证

1. **DEFAULT 模板验证**：启动 agent，打印 system prompt，确认 env 段含 4 个英文字段 + 编号。
2. **YOLO 模式验证**：切换到 yolo 模式，打印 system prompt，确认 YOLO 模板 env 段与 DEFAULT 一致。
3. **metadata 段分离验证**：确认 git 状态（branch/commit/remote）在 `# Workspace Configuration` JSON 段，不在 `<env>` 段。

### 8.3 回归验证

1. 运行 `tests/test_stage4_context_prompt.py`，确认现有测试通过（若采用 P1-1 方案 A 删除 `_build_environment`，需同步更新测试）。
2. 执行一轮对话，确认 LLM 能从 env 段正确读取平台/日期/IDE/工作目录信息。

---

## 附录：检查覆盖声明

- Cline `system.ts`：100% 完整审阅（68 行）
- Cline `cline.ts`：100% 完整审阅（166 行，重点 L110-166 buildClineSystemPrompt）
- Charles `charles_system_prompt.py`：100% 完整审阅（94 行）
- Charles `context.py` env 段相关代码：100% 审阅（L78-127 build_charles_system_prompt + L649-681 _build_environment）
- nanobot 残留检索：`agent/` 目录全量 Grep，共 55 处命中，逐项筛查与 env 段的关联性
- 计划文件 P5.4 段：L1834-1866 完整审阅，与实际代码交叉验证

本报告未修改任何源码，仅输出审计报告文件。
