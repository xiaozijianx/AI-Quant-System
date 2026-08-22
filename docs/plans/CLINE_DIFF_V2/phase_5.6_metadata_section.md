# Phase 5.6 Metadata 段对比

> 对比范围：Cline `buildWorkspaceMetadata` + `processWorkspaceInfo` + `WORKSPACE_CONFIGURATION_MARKER` 文本标记 + `isClineProvider` 条件门控 与 Charles `SystemPromptBuilder._build_metadata` + `should_inject_metadata` + `is_charles_provider` 的标签格式、provider 条件判断、注入内容、字段结构、段落位置、标签闭合等 6 项逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L9（`WORKSPACE_CONFIGURATION_MARKER = "# Workspace Configuration"` 常量）
> - `sdk/packages/shared/src/prompt/cline.ts` L47-62（`processWorkspaceInfo` 函数，将 `WorkspaceInfo` 序列化为 workspaces JSON）
> - `sdk/packages/shared/src/prompt/cline.ts` L64-86（`buildWorkspaceMetadata` 函数，拼接 marker + body）
> - `sdk/packages/shared/src/prompt/cline.ts` L124 + L158-163（`isClineProvider(providerId)` 门控 `{{CLINE_METADATA}}` 注入）
> - `sdk/packages/shared/src/prompt/system.ts` L35-36 + L67-68（`{{CLINE_METADATA}}` 占位符位置，紧随 `{{CLINE_RULES}}`）
> - `sdk/packages/shared/src/providers/utils.ts` L1-3（`isClineProvider` 白名单：`cline` / `cline-pass`）
>
> Charles 源码：
> - `agent/context.py` L78-127（`build_charles_system_prompt` 纯组装函数，含 `{{CHARLES_METADATA}}` 占位符替换 + `should_inject_metadata` 条件门控）
> - `agent/context.py` L130-182（`should_inject_metadata` + `is_charles_provider` + `_CHARLES_PROVIDER_IDS` 白名单）
> - `agent/context.py` L408-452（`SystemPromptBuilder._build_metadata` 方法，查询 git 状态 + 拼接 marker + JSON 序列化）
> - `agent/prompts/charles_system_prompt.py` L57 + L90（`{{CHARLES_METADATA}}` 占位符位置，紧随 `{{CHARLES_RULES}}`）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 Metadata 段（工作空间元数据）实现。**核心结论：Charles 已通过 L5 重构完成对齐，与 Cline 在标签格式、provider 条件判断、注入内容、段落位置、标签闭合 5 个维度均达到高一致性**；剩余差异主要在于 provider 白名单成员、JSON body 前导换行、字段可选性实现方式等细节，均属合理偏离而非对齐缺口。

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P5.6（L1899-1910）将 Charles 实现描述为"`<charles_metadata>\n{...}\n</charles_metadata>` XML 标签"且"始终注入（无 provider 条件判断）"。**此描述与实际代码严重不符，存在两处事实错误**：

1. **标签格式已对齐**：Charles 实际代码（context.py L448-452）已使用 `# Workspace Configuration\n` 文本标记，**不再**使用 `<charles_metadata>` XML 标签。L424 注释明确说明"L5 对齐: 使用 Cline 的 `# Workspace Configuration` 文本标记，不再使用 `<charles_metadata>` XML 标签"。计划表 5.6.1 / 5.6.6 标注的"L5 差距"已失效。

2. **provider 条件判断已对齐**：Charles 实际代码（context.py L122-146）已实现 `should_inject_metadata(provider_id)` → `is_charles_provider(provider_id)` 条件门控，**不再**是"始终注入"。计划表 5.6.2 标注的"L4 差距"已失效。

### 核心结论

1. **标签格式已对齐**（L5 重构）：Charles 使用 `# Workspace Configuration` 文本标记，与 Cline 的 `WORKSPACE_CONFIGURATION_MARKER` 常量一致。计划表 5.6.1 标注的"L5 差距"已失效。
2. **provider 条件判断已对齐**：Charles 通过 `should_inject_metadata` + `is_charles_provider` 实现 provider 白名单门控，模式与 Cline 的 `isClineProvider` 完全一致。计划表 5.6.2 标注的"L4 差距"已失效。
3. **注入内容已对齐**：两者均注入 `workspaces` 嵌套 JSON，含 `hint` / `latestGitCommitHash` / `latestGitBranchName` / `associatedRemoteUrls` 字段。
4. **注入时机已对齐**：两者均在 system prompt 组装时注入（每轮 system prompt 重建时重新构建）。
5. **段落位置已对齐**：两者均位于 `{{*_RULES}}` 之后，作为 base prompt 模板的最后一个段落。
6. **标签闭合已对齐**：两者均无独立闭合标签，仅用 `# Workspace Configuration` 文本标记 + JSON body 表示，JSON body 自然结束即为段落结束。
7. **nanobot 残留**：Metadata 段实现**无 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。L275 的 nanobot 注释属于 `extra_sections` 参数（与 metadata 无关）。

### 一致性总体评估

- **标签格式**：**高**。L5 重构后已完全对齐（均使用 `# Workspace Configuration` 文本标记）。
- **provider 门控**：**高**。条件判断模式完全对齐，仅白名单成员不同（合理偏离）。
- **JSON 结构**：**高**。两者均为 `workspaces → rootPath → {hint, git fields}` 嵌套结构。
- **段落位置**：**高**。两者均位于 rules 之后、模板末尾。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.6.1 | 标签格式 | `# Workspace Configuration`（cline.ts L9 + L85，`\n${MARKER}\n${body}`） | `# Workspace Configuration`（context.py L450，`"# Workspace Configuration\n" + json.dumps(...)`） | 高 | L5 重构后已对齐。计划表标注"L5 差距"已失效。唯一差异：Cline 在 marker 前加 `\n` 前导换行，Charles 无前导换行 |
| 5.6.2 | provider 条件判断 | `isClineProvider(providerId \|\| "")`（cline.ts L124），仅 `cline` / `cline-pass` 注入（providers/utils.ts L1-3） | `should_inject_metadata(provider_id)` → `is_charles_provider(provider_id)`（context.py L122-146），白名单含 `qwen` / `deepseek` / `openai` / `anthropic` / `charles` | 高 | 模式完全对齐。白名单成员不同（Cline 仅官方 cline/cline-pass；Charles 所有支持的 provider）。None/空字符串 Charles 视为默认 provider 注入，Cline 视为非 cline 不注入。计划表标注"L4 差距"已失效 |
| 5.6.3 | 注入内容 | `workspaces` 嵌套 JSON：`{workspaces: {rootPath: {hint, associatedRemoteUrls, latestGitCommitHash, latestGitBranchName}}}`（cline.ts L47-62 `processWorkspaceInfo`） | `workspaces` 嵌套 JSON：`{workspaces: {working_dir: {hint, [latestGitCommitHash], [latestGitBranchName], [associatedRemoteUrls as [remote]]}}}`（context.py L429-452） | 高 | 结构对齐。字段可选性实现方式略异：Cline `processWorkspaceInfo` 始终序列化全部 4 字段（`undefined` 由 `JSON.stringify` 自动省略）；Charles 显式条件追加（`if git_info.get(...)`）。Net 效果一致 |
| 5.6.4 | 注入时机 | `buildClineSystemPrompt` 每次调用时注入（cline.ts L158-163），base prompt 模板替换 | `build_charles_system_prompt` 每次调用时注入（context.py L122-125），base prompt 模板替换 | 高 | 完全一致。两者均在纯组装器层做占位符替换，metadata 文本由编排器/主机层预构建 |
| 5.6.5 | 段落位置 | base prompt 模板第 4 段（system.ts L35-36）：`{{CLINE_RULES}}\n{{CLINE_METADATA}}`，位于 `<env>` 段之后、模板末尾 | base prompt 模板第 4 段（charles_system_prompt.py L56-57 + L89-90）：`{{CHARLES_RULES}}\n{{CHARLES_METADATA}}`，位于 `<env>` 段之后、模板末尾 | 高 | 完全一致。两者均位于 rules 之后、模板末尾，DEFAULT / YOLO 双模板均遵循此顺序 |
| 5.6.6 | 标签闭合 | 无闭合标签，JSON body 自然结束即为段落结束 | 无闭合标签，JSON body 自然结束即为段落结束 | 高 | L5 重构后已对齐。计划表标注"L5 差距"（`</charles_metadata>`）已失效，Charles 不再使用 XML 标签 |

---

## 三、重点差距详细说明

### 3.1 计划文件 P5.6 描述与实际代码严重不符（5.6.1 + 5.6.2 + 5.6.6）

AGENT_COMPARISON_PLAN_V2.md L1899-1910 将 Charles 实现描述为：

```
**Charles 实现**（context.py::_build_metadata）：
- `<charles_metadata>\n{...}\n</charles_metadata>` XML 标签
- 始终注入（无 provider 条件判断）
```

经核查实际代码（context.py L408-452），Charles 的 `_build_metadata` 方法实际返回：

```python
# L448-452
return (
    "# Workspace Configuration\n"
    f"{json.dumps(metadata, ensure_ascii=False, indent=2)}"
)
```

且 `build_charles_system_prompt`（context.py L122-125）实际有 provider 条件门控：

```python
if should_inject_metadata(provider_id):
    prompt = prompt.replace("{{CHARLES_METADATA}}", metadata_text)
else:
    prompt = prompt.replace("{{CHARLES_METADATA}}", "")
```

L424 的注释明确记录了 L5 重构的历史："L5 对齐: 使用 Cline 的 `# Workspace Configuration` 文本标记，不再使用 `<charles_metadata>` XML 标签。"

**结论**：计划表 5.6.1（L5 差距）、5.6.2（L4 差距）、5.6.6（L5 差距）三项标注均已失效，实际代码已完成 L5 对齐。计划文件 P5.6 描述基于 L5 重构前的旧实现，需更新。

### 3.2 marker 前导换行差异（5.6.1）

Cline `buildWorkspaceMetadata`（cline.ts L85）返回 `\n${WORKSPACE_CONFIGURATION_MARKER}\n${body}`，marker 前有 `\n` 前导换行。Charles `_build_metadata`（context.py L449-451）返回 `"# Workspace Configuration\n" + json.dumps(...)`，marker 前无前导换行。

由于 base prompt 模板中 `{{*_RULES}}` 与 `{{*_METADATA}}` 之间已有换行（Cline system.ts L35-36、Charles charles_system_prompt.py L56-57）：

```
{{CLINE_RULES}}
{{CLINE_METADATA}}
```

替换后的实际效果：

- **Cline**：`{rules}\n\n# Workspace Configuration\n{body}`（marker 前出现空行，因 `\n` 前导 + 模板换行）
- **Charles**：`{rules}\n# Workspace Configuration\n{body}`（marker 前无空行，仅模板换行）

**影响**：纯格式差异，不影响 LLM 解析。Cline 的空行更易区分 rules 与 metadata 段落边界，Charles 的紧凑格式更节省 token。两者均可被 LLM 正确识别。

**评估**：非对齐缺口，属格式偏好差异。若追求字节级对齐，建议 Charles 在 `_build_metadata` 返回值前加 `\n`。

### 3.3 provider 白名单成员差异（5.6.2）

| 维度 | Cline | Charles |
|------|-------|---------|
| 白名单函数 | `isClineProvider(providerId)` | `is_charles_provider(provider_id)` |
| 白名单成员 | `cline` / `cline-pass` | `qwen` / `deepseek` / `openai` / `anthropic` / `charles` |
| None/空字符串处理 | 视为非 cline，**不**注入 | 视为默认 provider（qwen），**注入** |
| 语义 | 仅 Cline 官方 provider 注入 | 所有 Charles 支持的 provider 注入 |

Charles context.py L179-182 对 None/空字符串的处理：

```python
if not provider_id:
    # Charles 默认有 provider（qwen），None/空字符串视为默认 provider
    return True
return provider_id in _CHARLES_PROVIDER_IDS
```

**评估**：白名单成员差异属合理偏离——Charles 不存在"第三方非原生 provider"概念，所有接入的 provider 都需要 workspaces metadata（量化场景统一需求）。None 默认注入策略向后兼容未显式传入 `provider_id` 的旧调用方。非对齐缺口。

### 3.4 字段可选性实现方式差异（5.6.3）

**Cline** 通过 `processWorkspaceInfo`（cline.ts L47-62）始终序列化全部 4 字段：

```typescript
return JSON.stringify({
    workspaces: {
        [info.rootPath]: {
            hint: info.hint,
            associatedRemoteUrls: info.associatedRemoteUrls,    // 可能 undefined
            latestGitCommitHash: info.latestGitCommitHash,      // 可能 undefined
            latestGitBranchName: info.latestGitBranchName,      // 可能 undefined
        },
    },
}, null, 2);
```

JavaScript `JSON.stringify` 自动省略值为 `undefined` 的键，因此 net 效果是缺值的字段不出现在 JSON 中。

**Charles** 通过显式条件追加（context.py L432-446）：

```python
workspace_entry: dict[str, Any] = {"hint": workspace_name}
if git_info.get("commit"):
    workspace_entry["latestGitCommitHash"] = git_info["commit"]
if git_info.get("branch"):
    workspace_entry["latestGitBranchName"] = git_info["branch"]
if git_info.get("remote"):
    workspace_entry["associatedRemoteUrls"] = [git_info["remote"]]
```

Python `json.dumps` 不会自动省略 `None` 值（会序列化为 `null`），因此 Charles 必须显式条件追加才能达到与 Cline 相同的 net 效果。

**Net 效果对比**：
- 两者在 git 信息完整时输出相同的 4 字段 JSON
- 两者在 git 信息缺失时均省略对应字段
- Charles 将 `remote` 包装为单元素列表 `[remote]`（对齐 Cline 的 `associatedRemoteUrls: string[]` 类型）

**评估**：实现方式不同但 net 效果一致。非对齐缺口。

### 3.5 metadata 来源与构建位置差异（5.6.4）

**Cline**：metadata 文本由主机包装层（CLI `resolveSystemPrompt`）预构建，作为 `metadata` 参数传入 `buildClineSystemPrompt`。`buildClineSystemPrompt` 内部调用 `buildWorkspaceMetadata(workspaceRoot, workspaceName, metadata)`，若 metadata 已含 marker 则原样返回，否则补 marker。

**Charles**：metadata 文本由编排器 `SystemPromptBuilder._build_metadata`（context.py L408-452）构建，直接调用 `_read_git_state` 查询 git 状态。`build_charles_system_prompt` 纯组装器仅做占位符替换，不参与 metadata 构建。

**差异**：Cline 的 metadata 可由调用方预先构建（含 marker）或由 `buildWorkspaceMetadata` 补 marker；Charles 的 metadata 始终由 `_build_metadata` 完整构建（含 marker）。Charles 的纯组装器更"纯"（不内嵌 metadata 补 marker 逻辑），与 P5.1 的"Charles 纯组装器职责更窄"结论一致。

**评估**：非对齐缺口，属架构职责分层差异（已在 P5.1 详述）。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

针对 Metadata 段相关文件检查 nanobot 风格残留：
- `agent/context.py` L78-182（`build_charles_system_prompt` + `should_inject_metadata` + `is_charles_provider`）
- `agent/context.py` L408-452（`_build_metadata` 方法）
- `agent/prompts/charles_system_prompt.py`（base prompt 模板，含 `{{CHARLES_METADATA}}` 占位符）

### 4.2 检查结果

| 文件 / 范围 | 注释残留数 | 实现逻辑残留数 | 残留详情 |
|------|-----------|---------------|---------|
| `agent/context.py` L78-182（纯组装器 + provider 门控） | 0 | 0 | 无残留 |
| `agent/context.py` L408-452（`_build_metadata` 方法） | 0 | 0 | 无残留 |
| `agent/prompts/charles_system_prompt.py`（base prompt 模板） | 0 | 0 | 无残留 |

### 4.3 残留详情

#### 4.3.1 注释残留（0 处，Metadata 段范围内）

经核查 Metadata 段相关代码：
- `build_charles_system_prompt`（L78-127）：无 nanobot 注释
- `should_inject_metadata` / `is_charles_provider` / `_CHARLES_PROVIDER_IDS`（L130-182）：无 nanobot 注释
- `_build_metadata`（L408-452）：无 nanobot 注释
- `charles_system_prompt.py`（全文 94 行）：无 nanobot 注释

**注**：`agent/context.py` L275 存在 1 处 nanobot 注释（`extra_sections: [已废弃] nanobot 风格的额外段落`），但该注释属于 `extra_sections` 参数（与 Rules 段相关），**不属于 Metadata 段范围**。该项已在 P5.1 第四节记录，本阶段不重复计入。

#### 4.3.2 实现逻辑残留（0 处）

经核查 Metadata 段全部实现逻辑：

- **标签格式**：使用 `# Workspace Configuration` 文本标记（对齐 Cline），**不**使用 nanobot 风格的 XML 标签或自定义分隔符
- **JSON 结构**：使用 `workspaces` 嵌套结构（对齐 Cline `processWorkspaceInfo`），**不**使用 nanobot 风格的扁平 metadata 字典
- **字段命名**：`hint` / `latestGitCommitHash` / `latestGitBranchName` / `associatedRemoteUrls` 完全对齐 Cline，**不**使用 nanobot 风格的 `workspace_name` / `git_commit` / `git_branch` 命名
- **provider 门控**：使用 `is_charles_provider` 白名单（对齐 Cline `isClineProvider`），**不**使用 nanobot 风格的"始终注入"或"配置开关注入"
- **构建位置**：在编排器 `_build_metadata` 中构建（对齐 Cline 主机包装层），**不**在纯组装器中构建

**结论**：Metadata 段实现**无任何 nanobot 残留**（0 处注释残留、0 处实现逻辑残留）。L5 重构已彻底清除 Metadata 段的旧 XML 标签风格，与 Cline 文本标记 + JSON body 风格完全对齐。

### 4.4 与 Phase 4.20 对比

Phase 4.20（技能系统 nanobot 残留审计）发现技能系统存在 17 处实现逻辑残留。**Metadata 段无类似的实现逻辑残留**，仅 0 处注释残留 + 0 处实现逻辑残留。这说明 L5 重构已彻底清除 Metadata 段的 nanobot 风格实现逻辑，对齐质量高于技能系统。

### 4.5 历史标签残留检查（`<charles_metadata>`）

针对 L5 重构前的 `<charles_metadata>` XML 标签进行残留检查：

| 位置 | 类型 | 性质 |
|------|------|------|
| `context.py` L424 | 注释（docstring） | 历史说明："L5 对齐: ... 不再使用 `<charles_metadata>` XML 标签。" 属重构记录，非残留 |
| 其他位置 | — | 无残留 |

`<charles_metadata>` 与 `</charles_metadata>` 标签**仅**出现在 L424 的历史说明注释中，**不**出现在任何活跃代码或 base prompt 模板中。charles_system_prompt.py 全文搜索 `charles_metadata`（不带 `{{}}`）匹配数为 0。**结论**：L5 重构已彻底移除 `<charles_metadata>` XML 标签的活跃使用，仅保留注释作为历史记录。

---

## 五、修复建议

### 5.1 优先级 P0（无需修复）

- **5.6.1 标签格式**：已对齐，无需修复。marker 前导换行差异属格式偏好，不影响 LLM 解析。
- **5.6.2 provider 条件判断**：已对齐，无需修复。白名单成员差异属合理偏离。
- **5.6.3 注入内容**：已对齐，无需修复。字段可选性实现方式不同但 net 效果一致。
- **5.6.4 注入时机**：已对齐，无需修复。
- **5.6.5 段落位置**：已对齐，无需修复。
- **5.6.6 标签闭合**：已对齐，无需修复。

### 5.2 优先级 P1（建议处理）

- **5.6.1 marker 前导换行（可选）**：若追求字节级对齐，建议在 `_build_metadata` 返回值前加 `\n`，使输出为 `\n# Workspace Configuration\n{body}`，与 Cline `buildWorkspaceMetadata` 输出格式完全一致。当前差异不影响功能，但若后续做 prompt diff 自动化比对，可能导致 spurious diff。

### 5.3 优先级 P2（文档修正）

- **计划文件 P5.6 描述更新**：建议修正 AGENT_COMPARISON_PLAN_V2.md L1899-1910，将 Charles 实现描述更新为：
  - 标签格式：`# Workspace Configuration\n{...}` 文本标记（对齐 Cline）
  - provider 条件判断：`should_inject_metadata` → `is_charles_provider` 白名单门控（对齐 Cline `isClineProvider`）
  - 标签闭合：无闭合标签（对齐 Cline）
  
  并将计划表 5.6.1 / 5.6.2 / 5.6.6 的"差距"标注更新为"已对齐"。

- **历史标签注释保留**（context.py L424）：建议保留"`<charles_metadata>` XML 标签"的历史说明注释，作为 L5 重构记录。该注释对理解代码演进有价值，非残留。

---

## 六、验证方法

### 6.1 标签格式验证

```powershell
# 验证 Charles _build_metadata 输出格式（应输出 "# Workspace Configuration\n{...}"）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "# Workspace Configuration"
# 预期: L412（docstring 示例）+ L423（docstring 说明）+ L427（docstring 返回值）+ L448（注释）+ L450（代码）

# 验证 Charles 不再使用 <charles_metadata> XML 标签（应仅在 L424 历史注释中出现）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "charles_metadata"
# 预期: L11（{{CHARLES_METADATA}} 占位符说明）+ L123/L125（占位符替换）+ L424（历史注释）

# 验证 base prompt 模板不含 <charles_metadata> 标签
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "charles_metadata"
# 预期: 仅 {{CHARLES_METADATA}} 占位符（L18/L23/L30/L57/L90），无 <charles_metadata> XML 标签
```

### 6.2 provider 条件门控验证

```powershell
# 验证 Charles should_inject_metadata 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "should_inject_metadata|is_charles_provider|_CHARLES_PROVIDER_IDS"
# 预期: L122（调用）+ L130（定义）+ L146（return）+ L149（注释）+ L153（白名单）+ L162（定义）+ L179（None 处理）

# 验证 Cline isClineProvider 白名单
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\providers\utils.ts" -Pattern "isClineProvider"
# 预期: L1-3，仅 cline / cline-pass
```

### 6.3 JSON 结构验证

```powershell
# 验证 Charles _build_metadata 输出字段（hint / latestGitCommitHash / latestGitBranchName / associatedRemoteUrls）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "latestGitCommitHash|latestGitBranchName|associatedRemoteUrls"
# 预期: L417/L418（docstring 示例）+ L436/L438/L440（代码追加字段）

# 验证 Cline processWorkspaceInfo 输出字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\cline.ts" -Pattern "latestGitCommitHash|latestGitBranchName|associatedRemoteUrls"
# 预期: L53/L54/L55（processWorkspaceInfo 序列化字段）
```

### 6.4 nanobot 残留验证

```powershell
# 在 Metadata 段相关代码范围内搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "nanobot" | Where-Object { $_.LineNumber -ge 78 -and $_.LineNumber -le 182 -or $_.LineNumber -ge 408 -and $_.LineNumber -le 452 }
# 预期: 0 处（L275 的 extra_sections 注释不在 Metadata 段范围内）

# 在 base prompt 模板中搜索 nanobot（应 0 处）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期: 0 处
```

### 6.5 段落位置验证

```powershell
# 验证 Charles base prompt 模板中 {{CHARLES_METADATA}} 位于 {{CHARLES_RULES}} 之后
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\prompts\charles_system_prompt.py" -Pattern "\{\{CHARLES_(RULES|METADATA)\}\}"
# 预期: L56 {{CHARLES_RULES}} → L57 {{CHARLES_METADATA}}（DEFAULT 模板）；L89 → L90（YOLO 模板）

# 验证 Cline base prompt 模板中 {{CLINE_METADATA}} 位于 {{CLINE_RULES}} 之后
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\prompt\system.ts" -Pattern "\{\{CLINE_(RULES|METADATA)\}\}"
# 预期: L35 {{CLINE_RULES}} → L36 {{CLINE_METADATA}}（DEFAULT 模板）；L67 → L68（YOLO 模板）
```

---

## 七、附录：计划表项状态汇总

| 计划项 | 计划表标注 | 实际状态 | 说明 |
|--------|----------|---------|------|
| 5.6.1 标签格式 | L5 差距（`# Workspace Configuration` vs `<charles_metadata>`） | **已对齐** | L5 重构后 Charles 使用 `# Workspace Configuration` 文本标记，与 Cline 完全一致。计划表标注基于旧实现 |
| 5.6.2 provider 条件判断 | L4 差距（isCline vs 无） | **已对齐** | Charles 已实现 `should_inject_metadata` → `is_charles_provider` 白名单门控，模式与 Cline 完全一致。计划表标注基于旧实现 |
| 5.6.3 注入内容 | 已对齐（workspaces vs workspaces） | **已对齐** | 确认对齐。两者均注入 `workspaces` 嵌套 JSON，字段命名与结构一致 |
| 5.6.4 注入时机 | 已对齐（always vs always） | **已对齐** | 确认对齐。两者均在 system prompt 组装时注入 |
| 5.6.5 段落位置 | 已对齐（第 4 段 vs 第 4 段） | **已对齐** | 确认对齐。两者均位于 rules 之后、模板末尾 |
| 5.6.6 标签闭合 | L5 差距（无 vs `</charles_metadata>`） | **已对齐** | L5 重构后 Charles 不再使用 XML 标签，无闭合标签需求。计划表标注基于旧实现 |

**计划表标注总结**：6 项中 3 项标注"差距"的项（5.6.1 / 5.6.2 / 5.6.6）实际已通过 L5 重构对齐，3 项标注"已对齐"的项（5.6.3 / 5.6.4 / 5.6.5）确认对齐。计划表 P5.6 整体基于 L5 重构前的旧实现描述，未反映 L5 重构成果，需更新。
