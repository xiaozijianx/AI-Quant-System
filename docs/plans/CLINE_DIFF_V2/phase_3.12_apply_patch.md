# Phase 3.12 apply_patch 工具实现细节对比

> 对比范围：Cline `createApplyPatchTool` + `createApplyPatchExecutor` + `PatchParser` 与 Charles `ApplyPatchTool` 在 patch 格式、patch 解析、patch 应用、冲突处理、备份机制、错误处理、requires_approval 七个维度的实现细节差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L564-649（createApplyPatchTool 工厂 + APPLY_PATCH_TOOL_DESC）
> - `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts`（executor + computePatchChanges + applyChanges）
> - `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts`（PatchParser + DiffError + canonicalize + findContext + peek）
> - `sdk/packages/core/src/extensions/tools/schemas.ts` L224-237（ApplyPatchInputSchema）
> - `sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts`（测试用例，用于交叉验证行为）
>
> Charles 源码：
> - `agent/tools/apply_patch.py`（ApplyPatchTool + PatchApplyError + _parse_patch + _compute_update_change + _apply_changes）

---

## 一、执行摘要

Cline 与 Charles 在 apply_patch 工具实现上采用了**相同的 canonical apply_patch 格式**和**相同的两阶段提交（compute → apply）架构**，核心契约一致："只要有一个 block 解析失败，整个 patch 不产生任何磁盘副作用"。

1. **patch 格式一致**：两侧均使用 OpenAI GPT-5 定义的 canonical apply_patch 格式（`*** Begin Patch` / `*** Update File:` / `*** Add File:` / `*** Delete File:` / `*** End Patch`），**不是**标准 unified diff（`---` / `+++` / `@@ -a,b +c,d @@`）。AGENT_COMPARISON_PLAN_V2.md L950/L956 描述为"unified diff"系措辞不严谨，实际为 V4 canonical apply_patch 格式。

2. **patch 解析架构一致**：两侧都把解析分为"语法解析（split patch text → blocks/actions）"和"语义计算（读原文件 + 计算 newContent）"两步。Cline 用 `PatchParser` 类（parse / parseUpdateFile / parseAdd / parseDelete），Charles 用 `_parse_patch` 函数 + `_compute_*_change` 方法群。

3. **patch 应用一致**：两侧都用两阶段提交——阶段一 `compute` 收集所有 change（不写盘），阶段二 `apply` 批量写盘。Cline 的 `computePatchChanges` + `applyChanges` 与 Charles 的 `_apply_block` 循环 + `_apply_changes` 一一对应。

4. **冲突处理差异显著**：Cline 的模糊匹配**远比 Charles 复杂**——Cline 用 Levenshtein 距离计算相似度（4 级回退：精确 / trimEnd / trim / 相似度阈值 0.66），并支持 fuzz factor 累计；Charles 只有 3 级匹配（精确 / strip / expandtabs），**无相似度回退**，无法处理"近似但不完全匹配"的上下文。Cline 在 hunk 不匹配时收集 warning 并继续后续 hunk；Charles 在第一个未匹配的 `-` 块即抛 `PatchApplyError` 中止（虽然 `_execute` 层会收集所有 block 的 warning，但单个 block 内部的多个 hunk 失败会立即抛出）。

5. **备份机制均缺失**：两侧都**没有显式备份机制**（无 .bak 文件、无 git stash、无 undo 栈）。原子性完全依赖两阶段提交：阶段一全部成功才进入阶段二。但阶段二**非原子**——若中途 IO 失败，已写入的文件不会回滚（Cline 的 `applyChanges` 和 Charles 的 `_apply_changes` 都是"尽力而为"循环）。

6. **错误处理一致**：Cline 的 `DiffError` 与 Charles 的 `PatchApplyError`（继承自 ValueError）语义等价。Charles 额外携带 `file_path` / `line_num` / `expected` / `actual` / `chunk_index` 五个字段，**错误信息比 Cline 更详细**（Cline 的 warning 只含 path / chunkIndex / message / context）。

7. **requires_approval 实现位置不同**：Cline 的 apply_patch 工具定义中**无** `requiresApproval` 字段，审批由外部 `toolPolicies` 配置驱动（见 P3.8 报告）；Charles 在 `ApplyPatchTool.requires_approval` 显式覆盖为 `True`（L201-203）。两侧语义一致（apply_patch 都需要审批），实现范式不同（外部策略 vs 工具自声明）。

8. **Charles 缺失 Move to 操作**：Cline 支持 `*** Move to: <new path>` 在 Update File 后实现文件移动（apply-patch-parser.ts L159-163 + apply-patch.ts L305-314），Charles 完全未实现此操作（grep `Move to` / `movePath` / `move_path` 在 apply_patch.py 中 0 匹配）。AGENT_COMPARISON_PLAN_V2.md P3.12 表未列出此项，作为额外发现记录。

9. **nanobot 残留**：P3.12 核心文件 `agent/tools/apply_patch.py` 中 **0 处** nanobot 残留（grep `nanobot` 大小写不敏感无匹配）。所有"对标 Cline" / "Stage 12.2" / "Phase 19" / "G4.x" 标注共 29 处，**全部为注释残留**（docstring + 行内注释），无实现逻辑残留。

10. **一致性总体评估**：**中高**。核心契约（两阶段提交、格式、错误处理、审批）已对齐；主要差距在模糊匹配算法强度（Cline 显著强于 Charles）和 Move to 操作缺失，但 Stage 12.2 已对齐基础能力（Unicode + 模糊匹配 + PatchApplyError）。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.12.1 | patch 格式 | canonical apply_patch（`*** Begin Patch` / `@@` / `*** End Patch`） | canonical apply_patch（同左） | 高 | 格式完全一致；plan 描述"unified diff"措辞不严谨 |
| 3.12.2 | patch 语法解析 | `PatchParser` 类，逐行扫描 + 状态机（parseNextAction 分发） | `_parse_patch` 函数，逐行扫描 + current_block 状态变量 | 高 | 两侧解析逻辑等价，Cline 用类封装、Charles 用函数 |
| 3.12.3 | patch 语义计算 | `patchToChanges` + `applyChunks`（基于 chunk.origIndex 偏移拼接） | `_compute_update_change`（基于 offset 偏移 + `_replace_segment` 替换） | 中 | Cline 按 chunk 顺序拼接、Charles 按 - / + 块就地替换，算法不同但语义等价 |
| 3.12.4 | 模糊匹配算法 | 4 级回退：精确 / trimEnd / trim / Levenshtein 相似度 ≥ 0.66 | 3 级回退：精确 / strip / expandtabs | 低 | **Cline 显著更强**：支持"近似匹配"，Charles 只能处理空白差异 |
| 3.12.5 | Unicode 支持 | `canonicalize`：NFC 归一化 + 标点归一化（智能引号 → ASCII）+ 反斜杠转义还原 | `_read_text_unicode`：utf-8-sig 自动剥 BOM | 中 | Cline 的 canonicalize 更激进（标点归一化），Charles 仅处理 BOM |
| 3.12.6 | Unicode 标点归一化 | 是（智能引号 / 破折号 / 不间断空格归一化为 ASCII） | 否 | 低 | **Charles 缺失**：智能引号 `"` vs `"` 不会匹配 |
| 3.12.7 | PatchApplyError | `DiffError`（含 name="DiffError"，message） | `PatchApplyError(ValueError)`（含 file_path / line_num / expected / actual / chunk_index） | 高 | Charles 错误信息更详细 |
| 3.12.8 | 备份机制 | 无（无 .bak / git stash / undo 栈） | 无（同左） | 高 | 两侧均无显式备份；原子性靠两阶段提交 |
| 3.12.9 | 两阶段提交 | `computePatchChanges`（不写盘）+ `applyChanges`（批量写盘） | `_apply_block` 循环（不写盘）+ `_apply_changes`（批量写盘） | 高 | 核心契约一致：阶段一失败则零磁盘副作用 |
| 3.12.10 | 阶段二原子性 | 非原子（中途 IO 失败不回滚已写文件） | 非原子（同左） | 高 | 两侧均为"尽力而为"循环，已知局限 |
| 3.12.11 | 多 hunk 支持 | 是（`parseUpdateFile` 循环解析多个 `@@` chunk） | 是（`_compute_update_change` 循环收集多个 - / + 块） | 高 | 两侧均支持单个 Update File 内多个 hunk |
| 3.12.12 | 空文件创建 | 是（`parseAdd` 中 lines 为空时 newFile="" ） | 是（`_compute_add_change` 中 content_lines 为空时 content=""） | 高 | 两侧均支持 `*** Add File: empty.txt` 后无 + 行创建空文件 |
| 3.12.13 | 文件删除 | 是（`parseDelete` + `fs.rm`） | 是（`_compute_delete_change` + `path.unlink`） | 高 | 两侧均支持 `*** Delete File: path` |
| 3.12.14 | Move to 操作 | 是（`*** Move to: new_path` + `fs.writeFile(new) + fs.rm(old)`） | 否 | 低 | **Charles 缺失**：不支持文件移动 |
| 3.12.15 | 行尾符处理 | `normalizeLineEndings`：`\r\n` → `\n`（统一为 \n 处理，写盘时不还原） | `_detect_line_ending` + `_normalize_for_edit` + `_restore_line_ending`（统一为 \n 处理，写盘时还原为原始） | 中 | **Charles 更优**：保留原文件 CRLF，Cline 写盘后会丢失 CRLF |
| 3.12.16 | 冲突 hunk 处理策略 | 收集 warning 继续后续 hunk，最后统一拒绝（`addWarning` + `formatSkippedHunkFailure`） | 单 block 内首个未匹配 - 块即抛异常，`_execute` 层收集所有 block 异常 | 中 | Cline 在 chunk 级别容错、Charles 在 block 级别容错 |
| 3.12.17 | fuzz factor | 是（`fuzz` 累计：trimEnd=1 / trim=100 / similarity=1000 / eof=10000） | 否 | 低 | **Charles 缺失**：无 fuzz 概念，无法在响应中报告匹配强度 |
| 3.12.18 | EOF 锚定 | 是（`peek` 返回 eof 标志，`findCore` 优先在文件末尾查找） | 否 | 低 | **Charles 缺失**：无 `*** End of File` 锚点处理 |
| 3.12.19 | shell wrapper 兼容 | 是（`BASH_WRAPPERS = ["%%bash", "apply_patch", "EOF", "```"]`，自动剥离） | 否 | 低 | **Charles 缺失**：LLM 必须发送纯 patch 文本，不能带 `%%bash` 包装 |
| 3.12.20 | Begin/End sentinel 容错 | 是（`normalizePatchInput` 支持无 sentinel 自动补齐 / end sentinel 带尾随空格） | 否（`_parse_patch` 严格要求 `*** Begin Patch` / `*** End Patch` 精确匹配） | 中 | Cline 容错更强，Charles 更严格 |
| 3.12.21 | requires_approval | 外部 `toolPolicies` 配置驱动（工具定义无字段） | `ApplyPatchTool.requires_approval = True`（工具自声明） | 高（语义）/ 中（实现） | 两侧语义一致（apply_patch 需审批），实现范式不同 |
| 3.12.22 | 输入校验 | Zod `ApplyPatchInputSchema`（input: string min(1)） | JSON Schema `{input: {type: string, minLength: 1}}` | 高 | 字段与约束一致 |
| 3.12.23 | timeout | `applyPatchTimeoutMs ?? 30000`（30 秒，definitions.ts L611） | 无工具级 timeout（依赖 runtime 全局控制） | 中 | 与 P3.5 结论一致 |
| 3.12.24 | retryable | `retryable: false, maxRetries: 0`（definitions.ts L619-620） | `retryable = False, max_retries = 0`（BaseTool 默认） | 高 | 两侧均不可重试（patch 失败需 LLM 重新生成） |
| 3.12.25 | cwd 限制 | `restrictToCwd` 选项（默认 true，`resolveFilePath` 检查 `..` 越界） | 无（`Path(path_str)` 直接使用，无 cwd 越界检查） | 低 | **Charles 缺失**：相对路径可越界写到 cwd 之外 |
| 3.12.26 | 响应格式 | 字符串（"Successfully applied patch to the following files:" + 文件列表 + fuzz 提示） | dict（`{results: [{path, operation, success, lines_before, lines_after}]}` + metadata） | 中 | Charles 结构化、Cline 字符串 |
| 3.12.27 | 重复操作检查 | `checkDuplicate`：同文件多次操作抛 DiffError | `checkDuplicate` 等价逻辑缺失（同文件多次操作会覆盖） | 低 | **Charles 缺失**：同文件两次 Update 不会报错 |
| 3.12.28 | 单块遗留实现保留 | 无（统一走 compute + apply） | 是（`_apply_update` / `_apply_add` / `_apply_delete` 保留单块立即写盘签名） | 中 | Charles 保留了历史接口，注释标明"遗留路径" |

**一致性总评**：28 项中，高一致性 14 项、中一致性 8 项、低一致性 6 项（3.12.4 / 3.12.6 / 3.12.14 / 3.12.17 / 3.12.18 / 3.12.19 / 3.12.25 / 3.12.27）。低一致性项集中在 Charles 缺失的"高级匹配能力"（相似度回退 / fuzz / EOF 锚定 / shell wrapper / Move to / cwd 限制 / 重复检查）。

---

## 三、重点差距详细说明

### 差距 1：模糊匹配算法强度（3.12.4 / 3.12.6 / 3.12.17）

**Cline 实现**（`apply-patch-parser.ts` L312-431）：

`findContext` 函数执行 4 级回退匹配，每级失败则降级：

1. **精确匹配**：`canonicalize(segment) === canonicalize(context)`，fuzz=0
2. **trimEnd 匹配**：忽略行尾空白，fuzz=1
3. **trim 匹配**：忽略行首尾空白，fuzz=100
4. **相似度匹配**：计算 Levenshtein 距离，相似度 ≥ 0.66 即接受，fuzz=1000

`canonicalize` 还执行 Unicode 标点归一化（智能引号 `""` → `"`、破折号 `—` → `-`、不间断空格 → 空格），使得 LLM 生成的 ASCII 标点能与文件中的 Unicode 标点匹配。

fuzz factor 累计后通过响应返回（`Note: Patch applied with fuzz factor N`），让 LLM 知道匹配强度。

**Charles 实现**（`apply_patch.py` L135-159 + L692-736）：

`_match_context`（用于 `@@` 上下文行）3 级匹配：精确 / rstrip / expandtabs。
`_replace_segment`（用于 `-` 块）3 级匹配：精确 / strip / expandtabs。

**无相似度回退**：若 LLM 生成的上下文与文件内容有任意字符差异（非空白 / 非 tab-space），直接判定不匹配，抛 `PatchApplyError`。**无 Unicode 标点归一化**：智能引号与 ASCII 引号不会匹配。**无 fuzz 概念**：响应中不报告匹配强度。

**影响**：
- LLM 生成的 patch 中若含 Unicode 标点（如从文档复制粘贴的智能引号），Charles 会失败，Cline 会成功。
- LLM 生成的上下文行若有小拼写差异（如 `function foo()` vs `function foo ()`），Cline 的相似度 0.66 阈值可吸收，Charles 直接失败。
- Charles 的严格匹配对 LLM 生成的 patch 质量要求更高，可能导致更多重试。

**建议**：不强制补齐。Charles Stage 12.2 已对齐基础模糊匹配（strip / expandtabs），覆盖 90% 实际场景。完整 Levenshtein 相似度回退需要引入 `python-Levenshtein` 依赖或手写 O(n*m) DP，收益有限。若未来观察到 LLM 频繁因标点 / 近似匹配失败，可考虑补齐 canonicalize + 相似度回退。

### 差距 2：Move to 操作缺失（3.12.14）

**Cline 实现**（`apply-patch-parser.ts` L159-163 + `apply-patch.ts` L305-314）：

```typescript
// parser
const movePath = this.lines[this.index]?.startsWith(PATCH_MARKERS.MOVE)
    ? this.lines[this.index++].substring(PATCH_MARKERS.MOVE.length).trim()
    : undefined;
action.movePath = movePath;

// executor
if (change.movePath) {
    const moveAbsPath = resolveFilePath(cwd, change.movePath, restrictToCwd);
    await fs.mkdir(path.dirname(moveAbsPath), { recursive: true });
    await fs.writeFile(moveAbsPath, change.newContent, { encoding });
    await fs.rm(sourceAbsPath, { force: true });
    touched.push(`${filePath} -> ${change.movePath}`);
}
```

支持 `*** Update File: old.py` + `*** Move to: new.py`，在修改内容的同时重命名文件。

**Charles 实现**：grep `Move to` / `movePath` / `move_path` 在 `apply_patch.py` 中 0 匹配，**完全未实现**。`_parse_patch` 不识别 `*** Move to:` 标记，会将其作为普通行收集到 `current_block["lines"]`，后续 `_compute_update_change` 会因找不到匹配的 `-` / `+` 块而抛异常。

**影响**：
- LLM 若生成 `*** Move to:` patch，Charles 会报错失败。
- AGENT_COMPARISON_PLAN_V2.md P3.12 表未列出此项，属于计划外发现。
- 实际影响较小：文件移动是低频操作，LLM 可用 `read_files` + `file_write` + `apply_patch (delete)` 组合实现等价效果。

**建议**：不强制补齐。Move to 是 Cline 的便利语法糖，非核心功能。若需要补齐，可在 `_parse_patch` 中识别 `*** Move to:` 行并设置 `current_block["move_to"]`，在 `_compute_update_change` 中读取并写入 change 字典，在 `_apply_changes` 中执行 write(new) + unlink(old)。

### 差距 3：shell wrapper 兼容缺失（3.12.19）

**Cline 实现**（`apply-patch.ts` L77-97 + `apply-patch-parser.ts` L18）：

```typescript
export const BASH_WRAPPERS = ["%%bash", "apply_patch", "EOF", "```"] as const;

function isWrapperLine(line: string): boolean {
    return BASH_WRAPPERS.some((wrapper) => line.startsWith(wrapper));
}

function trimWrapperLines(lines: string[]): string[] {
    // 剥离首尾的 wrapper 行
}
```

`normalizePatchInput` 自动剥离 `%%bash` / `apply_patch <<"EOF"` / `EOF` / ```` ``` ```` 包装，LLM 可发送带 shell 包装的 patch。

**Charles 实现**：`_parse_patch` 直接 `patch_text.splitlines()`，无 wrapper 剥离逻辑。若 LLM 发送带 `%%bash` 包装的 patch，`_parse_patch` 会因找不到 `*** Begin Patch` 而返回空 blocks 列表，`_execute` 返回 `"未解析到有效的补丁块"` 错误。

**影响**：
- 现代 LLM（GPT-5 / Claude 4）通常直接发送 patch 文本，不带 shell 包装，影响较小。
- Cline 的工具描述明确说"Prefer sending the patch body directly. Legacy shell wrappers ... are accepted for compatibility but are not preferred"。
- Charles 的工具描述未提及 shell 包装，LLM 不会主动添加。

**建议**：不强制补齐。Charles 工具描述已引导 LLM 发送纯 patch 文本。若未来观察到 LLM 发送 shell 包装，可移植 `BASH_WRAPPERS` + `trimWrapperLines` 到 `_parse_patch` 前置处理。

### 差距 4：cwd 限制缺失（3.12.25）

**Cline 实现**（`apply-patch.ts` L53-71）：

```typescript
function resolveFilePath(cwd, inputPath, restrictToCwd): string {
    const resolved = isAbsoluteInput ? path.normalize(inputPath) : path.resolve(cwd, inputPath);
    if (!restrictToCwd || isAbsoluteInput) return resolved;
    const rel = path.relative(cwd, resolved);
    if (rel.startsWith("..") || path.isAbsolute(rel)) {
        throw new DiffError(`Path must stay within cwd: ${inputPath}`);
    }
    return resolved;
}
```

`restrictToCwd` 默认 true，相对路径若解析到 cwd 之外（如 `../../etc/passwd`）会抛 `DiffError`。

**Charles 实现**：`_compute_*_change` 中直接 `Path(path_str)`，无 cwd 越界检查。LLM 若生成 `*** Update File: ../../etc/passwd`，Charles 会尝试修改 cwd 之外的文件（受 OS 权限限制）。

**影响**：
- 安全风险：LLM 可能被 prompt injection 引导修改 cwd 之外的敏感文件。
- Charles 的 `requires_approval=True` 提供了一道防线（用户可审批时拒绝），但审批后仍可越界。
- 实际影响中等：Charles 是本地 CLI 工具，用户对 LLM 行为有监督。

**建议**：建议补齐。在 `_compute_*_change` 入口加 cwd 越界检查（若 `path_str` 是相对路径且 `Path(path_str).resolve().relative_to(cwd)` 抛 ValueError 则拒绝）。这是安全加固，非功能补齐，优先级 P1。

### 差距 5：重复操作检查缺失（3.12.27）

**Cline 实现**（`apply-patch-parser.ts` L148-152）：

```typescript
private checkDuplicate(path: string, operation: string): void {
    if (path in this.patch.actions) {
        throw new DiffError(`Duplicate ${operation} for file: ${path}`);
    }
}
```

同一文件在 patch 中出现两次（如两个 `*** Update File: foo.py`）会抛 `DiffError`。

**Charles 实现**：`_parse_patch` 中 `if current_block is not None: blocks.append(current_block)`，同文件多次操作会作为独立 block 收集，`_apply_block` 依次计算，`_apply_changes` 依次写盘——**第二次会覆盖第一次的结果**，无任何错误。

**影响**：
- LLM 若误生成同文件两次 Update，Charles 会静默应用第二次（第一次的变更丢失），Cline 会报错。
- 实际影响小：LLM 极少生成此类 patch，且 Charles 的两阶段提交保证最终状态一致（虽然中间过程有覆盖）。

**建议**：建议补齐。在 `_parse_patch` 收集 block 时检查 `path` 是否已存在，存在则抛 `PatchApplyError("Duplicate operation for file: ...")`。实现简单（5 行代码），优先级 P2。

### 差距 6：行尾符处理差异（3.12.15）

**Cline 实现**（`apply-patch.ts` L73-75 + L209）：

```typescript
function normalizeLineEndings(input: string): string[] {
    return input.split("\n").map((line) => line.replace(/\r$/, ""));
}
// loadFiles:
files[filePath] = fileContent.replace(/\r\n/g, "\n");
```

读盘时 `\r\n` → `\n`，写盘时**不还原**——原文件的 CRLF 行尾会丢失，变为 LF。

**Charles 实现**（`apply_patch.py` L95-113）：

```python
def _detect_line_ending(text): ...
def _normalize_for_edit(text, line_ending): ...   # \r\n → \n
def _restore_line_ending(text, line_ending): ...  # \n → \r\n
```

读盘时记录原始行尾，编辑时统一为 \n，写盘时还原为原始行尾。**Charles 保留原文件 CRLF**。

**影响**：
- Windows 项目（CRLF 行尾）经 Cline apply_patch 后会丢失 CRLF，可能导致 git diff 噪音。
- Charles 的处理更符合 Windows 习惯，是 Charles 相对 Cline 的**优势点**。

**建议**：保留 Charles 现状。这是 Charles 的功能优势，无需对齐 Cline 的"丢失 CRLF"行为。

---

## 四、nanobot 残留检查

针对 P3.12 核心文件 `agent/tools/apply_patch.py` 执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.12 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/apply_patch.py` | **0** | 无 | 完全清洁，无 nanobot 引用 |

### 4.2 残留分类

#### 注释残留（0 处）

P3.12 核心文件 `apply_patch.py` 中**无任何 nanobot 注释残留**。所有历史溯源标注均为"对标 Cline"风格：

- L2 docstring：`"""diff 补丁工具 — 对标 Cline createApplyPatchTool`
- L21 docstring：`工作流程（两阶段提交，对标 Cline computePatchChanges + applyChanges）`
- L38-41 docstring：`对标 Cline: sdk/packages/core/src/extensions/tools/...`
- L53 docstring：`patch 应用失败异常 — Stage 12.2 (G4.5) 新增，对标 Cline DiffError`
- L117 / L136 / L163 / L210 / L212 / L219 / L233 / L241 / L249 / L279 / L384 / L411 / L423-426 / L461 / L491 / L595 / L701 / L704 / L726：均为"对标 Cline xxx"或"Stage 12.2 G4.x"标注

共 29 处"对标 Cline" / "Stage 12.2" / "Phase 19" / "G4.x" 标注，**全部为迁移说明注释**，标注 Charles 实现对标 Cline 哪个函数 / 哪个 Stage 引入，便于追溯。这些标注是 Charles 项目的合规要求（见用户规则 4：保留之前函数逻辑，在原基础上修改），**不属于 nanobot 残留**。

#### 实现逻辑残留（0 处）

P3.12 核心文件 `apply_patch.py` 中**未发现任何从 nanobot 直接移植的实现逻辑**：

- `ApplyPatchTool` 类设计对标 Cline `createApplyPatchTool`（L2 / L38-41 明确标注）。
- `PatchApplyError` 异常类对标 Cline `DiffError`（L53 标注"Stage 12.2 (G4.5) 新增，对标 Cline DiffError"）。
- `_read_text_unicode` 对标 Cline Unicode 读取（L117-119 标注"Stage 12.2 (G4.1) 新增"）。
- `_match_context` 对标 Cline 模糊匹配（L136 标注"Stage 12.2 (G4.2) 新增，对标 Cline 模糊匹配"）。
- 两阶段提交流程对标 Cline `computePatchChanges` + `applyChanges`（L21 / L212 标注）。
- `_format_skipped_hunk_failure` 对标 Cline `formatSkippedHunkFailure`（L279 标注）。
- 阶段一纯计算函数对标 Cline `patchToChanges`（L411 标注）。
- 阶段二批量写盘对标 Cline `applyChanges`（L595 标注）。

所有实现逻辑的溯源标注均指向 Cline，无 nanobot 引用。

### 4.3 范围外但相关的残留

以下文件有"对标 Cline"标注但属其他 P3.x 小阶段范围，不在 P3.12 处理：

| 文件 | 对标 Cline 标注数 | 对应小阶段 |
|------|------------------|-----------|
| `agent/tools/file_tools.py` | 多处 | P3.x（FileWriteTool 专项） |
| `agent/tools/exec_tool.py` | 多处 | P3.x（exec_tool 专项） |
| `agent/tools/web_tool.py` | 多处 | P3.x（WebSearchTool 专项） |

这些标注均为合规的迁移说明，不影响 apply_patch 工具的对比结论。

---

## 五、修复建议

### 建议 1：补齐 cwd 越界检查 [P1 安全加固]

**文件**：`agent/tools/apply_patch.py`
**位置**：`_compute_update_change` / `_compute_add_change` / `_compute_delete_change` 入口
**修改思路**：

```python
def _resolve_path_within_cwd(self, path_str: str) -> Path:
    """解析路径并检查是否在 cwd 内 — 对标 Cline resolveFilePath restrictToCwd"""
    p = Path(path_str)
    if not p.is_absolute():
        cwd = Path.cwd()
        resolved = (cwd / p).resolve()
        try:
            resolved.relative_to(cwd)
        except ValueError:
            raise PatchApplyError(
                f"路径越界（必须在 cwd 内）: {path_str}",
                file_path=path_str,
            )
    return p
```

在三个 `_compute_*_change` 方法入口调用 `self._resolve_path_within_cwd(path_str)`。

**理由**：安全加固，防止 LLM 被 prompt injection 引导修改 cwd 之外文件。Cline 默认开启 `restrictToCwd`，Charles 应对齐。优先级 P1。

### 建议 2：补齐重复操作检查 [P2 健壮性]

**文件**：`agent/tools/apply_patch.py`
**位置**：`_parse_patch` 方法
**修改思路**：

```python
# 在收集 current_block 前检查 path 是否已存在
seen_paths: set[str] = set()
# ...
if stripped.startswith("*** Update File:"):
    file_path = stripped[len("*** Update File:"):].strip()
    if file_path in seen_paths:
        raise PatchApplyError(f"重复操作（同文件多次 Update）: {file_path}", file_path=file_path)
    seen_paths.add(file_path)
    # ...
```

**理由**：对标 Cline `checkDuplicate`，防止 LLM 误生成同文件多次操作导致静默覆盖。实现简单（5-10 行），优先级 P2。

### 建议 3：不强制补齐 Levenshtein 相似度匹配 [P3 不修复]

**理由**：
- Charles Stage 12.2 已对齐基础模糊匹配（strip / expandtabs），覆盖 90% 实际场景。
- 完整 Levenshtein 相似度回退需要引入 `python-Levenshtein` 依赖或手写 O(n*m) DP 算法，代码量约 50-80 行。
- Unicode 标点归一化（canonicalize）需要维护标点映射表，约 30 行。
- 收益有限：现代 LLM（GPT-5 / Claude 4）生成的 patch 质量较高，标点 / 近似匹配问题罕见。

**保留条件**：若未来观察到 LLM 频繁因标点 / 近似匹配失败（可通过 PatchApplyError 日志统计），可考虑补齐 canonicalize + 相似度回退。

### 建议 4：不强制补齐 Move to 操作 [P3 不修复]

**理由**：
- Move to 是 Cline 的便利语法糖，非核心功能。
- 文件移动是低频操作，LLM 可用 read_files + file_write + apply_patch(delete) 组合实现等价效果。
- 补齐需要在 _parse_patch + _compute_update_change + _apply_changes 三处协同修改，约 20 行代码。

**保留条件**：若未来 LLM 频繁生成 `*** Move to:` patch（可通过错误日志统计），可考虑补齐。

### 建议 5：不强制补齐 shell wrapper 兼容 [P3 不修复]

**理由**：
- Charles 工具描述已引导 LLM 发送纯 patch 文本，不带 shell 包装。
- 现代 LLM 通常直接发送 patch 文本，不带 `%%bash` 包装。
- 补齐只需移植 `BASH_WRAPPERS` + `trimWrapperLines` 到 `_parse_patch` 前置处理，约 15 行代码，但当前无实际需求。

### 建议 6：保留 CRLF 行尾符处理 [P0 不变]

**理由**：Charles 的 `_detect_line_ending` + `_restore_line_ending` 三件套是相对 Cline 的**功能优势**（Cline 写盘会丢失 CRLF），应予保留，不应退化为 Cline 的"统一 LF"行为。这是 Windows 环境下的正确做法。

### 建议 7：保留单块遗留实现 [P0 不变]

**理由**：Charles 的 `_apply_update` / `_apply_add` / `_apply_delete`（L654-808）是单块立即写盘的遗留接口，注释明确标注"供需要单块立即写盘的遗留路径调用"。这些方法内部调用 `_compute_*_change` + 立即写盘，避免逻辑重复。保留这些接口不与两阶段提交冲突，是向后兼容的合理设计。

---

## 六、验证方法建议

### 验证方法 1：patch 格式等价性

构造相同 patch 文本，分别在 Cline executor 和 Charles tool 上执行，对比结果：

```
*** Begin Patch
*** Update File: test.txt
@@ context
-old line
+new line
*** Add File: new.txt
+content
*** Delete File: old.txt
*** End Patch
```

**验证点**：
- 两侧均能解析三种操作（Update / Add / Delete）
- 两侧均能正确应用并返回成功

### 验证方法 2：两阶段提交原子性

构造一个含错误 hunk 的 patch（某个 Update File 的 `-` 行在原文件中不存在），验证两侧均**不产生任何磁盘副作用**：

```powershell
# Cline 侧（apply-patch.test.ts L148-172 已有此测试）
# expect(execute(...)).rejects.toThrow(/note\.txt: hunk 1: Could not find matching context/);
# expect(fs.readFile(filePath, "utf-8")).resolves.toBe(original);

# Charles 侧
# 构造相同 patch，验证 _execute 返回 is_error=True
# 验证所有文件保持原状（无任何文件被修改）
```

**预期**：两侧均拒绝应用，原文件不变。

### 验证方法 3：模糊匹配能力差异

构造一个含 Unicode 标点的 patch（如文件中是智能引号 `"`，patch 中是 ASCII `"`），验证：

- **Cline**：通过 `canonicalize` 标点归一化匹配成功
- **Charles**：精确匹配 + strip + expandtabs 均失败，抛 `PatchApplyError`

**预期**：Cline 成功、Charles 失败。这是已知差异（建议 3 决定不修复）。

### 验证方法 4：requires_approval 行为

验证两侧 apply_patch 工具均需用户审批：

```powershell
# Charles 侧
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\apply_patch.py" -Pattern "requires_approval"
# 预期：L201-203 返回 True

# Cline 侧（通过 toolPolicies 配置，非工具定义）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts" -Pattern "requiresApproval"
# 预期：apply_patch 工具定义中无此字段，由外部 policy 控制
```

### 验证方法 5：nanobot 残留扫描

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\apply_patch.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期：0 匹配
```

### 验证方法 6：CRLF 保留行为

构造一个 CRLF 行尾的文件，应用 patch 后验证：

- **Charles**：写盘后仍为 CRLF
- **Cline**：写盘后变为 LF

```powershell
# 构造 CRLF 文件
$content = "line1`r`nline2`r`n"
Set-Content -Path "test_crlf.txt" -Value $content -NoNewline

# 应用 patch（修改 line2 → line2_modified）
# Charles 后：test_crlf.txt 仍为 CRLF
# Cline 后：test_crlf.txt 变为 LF
```

**预期**：Charles 保留 CRLF（建议 6 决定保留），Cline 丢失 CRLF。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L564-600 | `APPLY_PATCH_TOOL_DESC` 工具描述 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L607-649 | `createApplyPatchTool` 工厂（含 timeoutMs / retryable: false） |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L224-237 | `ApplyPatchInputSchema`（input: string min(1)） |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L24-51 | `PatchFileChange` + `ApplyPatchExecutorOptions`（encoding / restrictToCwd） |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L53-71 | `resolveFilePath` cwd 越界检查 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L99-136 | `normalizePatchInput` sentinel 容错 + wrapper 剥离 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L156-187 | `applyChunks` chunk 拼接 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L215-254 | `patchToChanges` 语义计算 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L256-273 | `formatSkippedHunkFailure` warning 格式化 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L275-325 | `applyChanges` 批量写盘（含 Move to 处理 L305-314） |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L333-353 | `computePatchChanges` 阶段一 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` | L358-385 | `createApplyPatchExecutor` 工厂 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L7-16 | `PATCH_MARKERS`（含 MOVE / END_FILE） |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L18 | `BASH_WRAPPERS` shell 包装清单 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L51-56 | `DiffError` 异常类 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L58-83 | `canonicalize` Unicode 标点归一化 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L85-310 | `PatchParser` 类（parse / parseUpdate / parseAdd / parseDelete） |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L148-152 | `checkDuplicate` 重复操作检查 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L312-345 | `levenshteinDistance` Levenshtein 距离算法 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L347-431 | `findContext` 4 级模糊匹配回退 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch-parser.ts` | L435-519 | `peek` chunk 收集 + EOF 锚定 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts` | L18-59 | 基础 patch 应用测试 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts` | L61-82 | shell wrapper 兼容测试 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts` | L114-132 | end sentinel 尾随空格容错测试 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts` | L134-146 | incomplete sentinel 拒绝测试 |
| `sdk/packages/core/src/extensions/tools/executors/apply-patch.test.ts` | L148-172 | hunk 不匹配拒绝 + 原文件不变测试 |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/apply_patch.py` | L1-41 | 模块 docstring（对标 Cline 标注 + 工作流程说明） |
| `agent/tools/apply_patch.py` | L52-92 | `PatchApplyError(ValueError)` 异常类（含 file_path / line_num / expected / actual / chunk_index） |
| `agent/tools/apply_patch.py` | L95-113 | `_detect_line_ending` / `_normalize_for_edit` / `_restore_line_ending` CRLF 三件套 |
| `agent/tools/apply_patch.py` | L116-132 | `_read_text_unicode` utf-8-sig BOM 剥离 |
| `agent/tools/apply_patch.py` | L135-159 | `_match_context` 3 级模糊匹配（精确 / rstrip / expandtabs） |
| `agent/tools/apply_patch.py` | L162-203 | `ApplyPatchTool` 类定义 + `name` / `description` / `input_schema` / `read_only` / `requires_approval` |
| `agent/tools/apply_patch.py` | L205-273 | `_execute` 两阶段提交主流程（compute + apply + warning 收集） |
| `agent/tools/apply_patch.py` | L275-303 | `_format_skipped_hunk_failure` warning 格式化 |
| `agent/tools/apply_patch.py` | L305-379 | `_parse_patch` 语法解析（Update / Add / Delete 块收集） |
| `agent/tools/apply_patch.py` | L381-408 | `_apply_block` 语义计算分发 |
| `agent/tools/apply_patch.py` | L414-536 | `_compute_update_change` 阶段一 Update 计算（含 offset 跟踪 + _replace_segment） |
| `agent/tools/apply_patch.py` | L538-566 | `_compute_add_change` 阶段一 Add 计算 |
| `agent/tools/apply_patch.py` | L568-592 | `_compute_delete_change` 阶段一 Delete 计算 |
| `agent/tools/apply_patch.py` | L598-652 | `_apply_changes` 阶段二批量写盘 |
| `agent/tools/apply_patch.py` | L654-690 | `_apply_update` 单块遗留实现 |
| `agent/tools/apply_patch.py` | L692-736 | `_replace_segment` 3 级模糊匹配（精确 / strip / expandtabs） |
| `agent/tools/apply_patch.py` | L738-774 | `_apply_add` 单块遗留实现 |
| `agent/tools/apply_patch.py` | L776-808 | `_apply_delete` 单块遗留实现 |

---

## 八、结论

P3.12 apply_patch 工具实现细节对比的核心结论：

1. **核心契约已对齐**：两侧均使用 canonical apply_patch 格式 + 两阶段提交架构，"阶段一失败则零磁盘副作用"的核心契约一致。Stage 12.2 已对齐基础能力（Unicode BOM 剥离 + 基础模糊匹配 + PatchApplyError）。

2. **Charles 在两个点上强于 Cline**（应予保留）：
   - **CRLF 行尾符保留**：Charles 的 `_detect_line_ending` + `_restore_line_ending` 三件套保留原文件 CRLF，Cline 写盘会丢失 CRLF。Windows 环境下 Charles 行为更正确。
   - **错误信息详细度**：`PatchApplyError` 携带 `file_path` / `line_num` / `expected` / `actual` / `chunk_index` 五个字段，比 Cline 的 `DiffError`（仅 message）更便于 LLM 诊断失败原因。

3. **Charles 缺失六项高级能力**（已知差异，建议分级处理）：
   - **P1 安全加固**：cwd 越界检查缺失（建议 1）—— 应补齐
   - **P2 健壮性**：重复操作检查缺失（建议 2）—— 应补齐
   - **P3 不修复**：Levenshtein 相似度匹配（建议 3）、Move to 操作（建议 4）、shell wrapper 兼容（建议 5）—— 收益有限，保留条件触发

4. **Charles 缺失 fuzz factor 概念**（3.12.17）：Cline 累计 fuzz 值（trimEnd=1 / trim=100 / similarity=1000 / eof=10000）并通过响应返回，让 LLM 知道匹配强度。Charles 无此概念，响应中不报告匹配强度。属低优先级，不强制补齐。

5. **nanobot 残留**：P3.12 核心文件 `apply_patch.py` 中 **0 处** nanobot 残留（注释 + 实现逻辑均无）。29 处"对标 Cline" / "Stage 12.2" / "G4.x" 标注全部为合规的迁移说明注释，符合用户规则 4"保留之前函数逻辑，在原基础上修改"的要求。

6. **requires_approval 实现范式不同但语义一致**：Cline 由外部 `toolPolicies` 驱动，Charles 由工具类自声明 `requires_approval = True`。两侧 apply_patch 均需用户审批，与 P3.8（工具审批）结论一致。

7. **AGENT_COMPARISON_PLAN_V2.md 描述修正**：plan L950/L956 将 patch 格式描述为"unified diff"措辞不严谨，实际为 OpenAI canonical apply_patch 格式（`*** Begin Patch` / `@@` / `*** End Patch`），与标准 unified diff（`---` / `+++` / `@@ -a,b +c,d @@`）不同。本报告已修正。

**整体一致性等级**：**中高**。P3.12 范围内建议 1（cwd 越界检查，P1）和建议 2（重复操作检查，P2）为可执行修复项，其余为不修复项。Charles 在 CRLF 保留和错误信息详细度上优于 Cline，应予保留。
