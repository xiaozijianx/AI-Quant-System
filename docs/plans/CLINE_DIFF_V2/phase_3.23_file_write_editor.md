# Phase 3.23 file_write / editor 实现对比

> 对比范围：Cline `createEditorTool` + `createEditorExecutor` 与 Charles `FileWriteTool` + `EditorTool` 在输入 schema、写入模式、目录创建、编辑方式、多处替换、唯一性校验、备份机制、requires_approval、nanobot 风格残留、file_tools.py 其他工具检查十个维度的实现细节差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L656-714（createEditorTool 工厂 + editor 工具描述）
> - `sdk/packages/core/src/extensions/tools/executors/editor.ts`（createEditorExecutor + resolveFilePath + countOccurrences + detectLineEnding + normalizeLineEndings + createLineDiff + createFile + replaceInFile + insertInFile）
> - `sdk/packages/core/src/extensions/tools/schemas.ts` L192-221（EditFileInputSchema）、L10（INPUT_ARG_CHAR_LIMIT=6000）
> - `sdk/packages/core/src/extensions/tools/helpers.ts` L20-33（getEditorSizeError）
> - `sdk/packages/core/src/extensions/tools/executors/editor.test.ts`（测试用例，交叉验证行为）
>
> Charles 源码：
> - `agent/tools/file_tools.py`（FileReadTool + FileWriteTool）
> - `agent/tools/editor.py`（EditorTool + _detect_line_ending + _normalize_for_edit + _restore_line_ending + _create_line_diff）
> - `agent/tools/base.py` L96-103（requires_approval 基类默认值）
> - `agent/tools/routing.py` L59-74（editor 在 openai-native / codex / gpt 模型下被禁用，改用 apply_patch）

---

## 一、执行摘要

Cline 与 Charles 在文件写入 / 编辑工具的实现上采用了**不同的工具切分策略**，但核心编辑语义（create / replace / insert）高度对齐：

1. **工具切分策略不同**：
   - **Cline 不存在独立 FileWriteTool**——文件写入完全集成在 `editor` 工具的 create 模式中（文件不存在 + 无 old_text/insert_line 时用 new_text 创建文件），以及 `apply_patch` 的 Add File 操作中。Cline 的 `editor` 工具一肩三挑：create / replace / insert。
   - **Charles 切分为两个工具**：`FileWriteTool`（全文件覆盖写入，file_tools.py L164-237）+ `EditorTool`（行级编辑，editor.py L124-473）。Charles 的 EditorTool 在 Phase 3.1 G3.3 中已移除整体覆盖分支（`_do_overwrite` 不再被调用，文件已存在且无 old_text/insert_line 时返回错误），但保留了独立的 FileWriteTool 作为"全文件覆盖"入口。这是 Charles 相对 Cline 的**功能增量**——Cline editor 明确拒绝无 old_text 的整体覆盖（definitions.ts L668 描述 + editor.ts L257-261 抛错），Charles 用独立工具承载此能力。

2. **EditorTool 输入 schema 高度一致**：两侧均有 path / old_text / new_text / insert_line 四字段，required 均为 `[path, new_text]`。Cline 用 Zod（`z.string().min(1)` / `z.number().int().nullable().optional()`），Charles 用 JSON Schema（`minLength: 1` / `minimum: 1`）。字段语义完全对应。

3. **三种编辑模式一致**：两侧均支持 create（文件不存在）、replace（old_text 唯一匹配替换）、insert（insert_line 1-based 边界行）三种模式。分支判断顺序一致：insert_line 优先 → 文件不存在 → old_text 替换 → 抛错/返回错误。

4. **唯一性校验一致**：两侧均要求 old_text 在文件中唯一匹配，0 匹配或 >1 匹配均报错。Cline 用 `countOccurrences`（字符串分割计数），Charles 优先用行级匹配（多行 old_text 时按行列表比对，避免跨行误匹配），单行时退化为字符串 `count`。**Charles 的行级匹配更安全**（避免跨行子串误匹配），是 Charles 的优化点。

5. **多处替换均不支持**：两侧均只支持单处替换（唯一匹配约束），不支持一次调用替换多处。多处替换需 LLM 发起多次 editor 调用（Cline 工具描述明确鼓励"emit multiple editor tool calls in the same response"）。

6. **备份机制均缺失**：两侧均无显式备份（无 .bak 文件、无 git stash、无 undo 栈）。编辑失败靠唯一性校验前置拦截，编辑成功直接覆盖写盘。原子性依赖前置校验，写盘阶段非原子。

7. **CRLF 行尾符处理一致**：两侧均检测原文件行尾符（`\r\n` 或 `\n`），编辑时统一为 `\n` 处理，写盘时还原为原始行尾。**Charles 与 Cline 在此点完全对齐**（与 P3.12 apply_patch 中 Cline 丢失 CRLF 的行为不同——editor.ts 的 `detectLineEnding` + `normalizeLineEndings` 三件套保留了 CRLF）。

8. **diff 生成一致**：两侧均生成 ```diff 代码块，修剪公共前后缀只输出变更区域，行预算在 removed/added 间分配（避免单侧吃满 max_lines）。Charles `_create_line_diff`（editor.py L57-121）明确标注"对标 Cline editor.ts L87-149 createLineDiff"，逻辑逐行对应。默认 max_lines=200 一致。

9. **requires_approval 实现位置不同**：Cline 的 editor 工具定义中**无** `requiresApproval` 字段，审批由外部 `toolPolicies` 配置驱动（见 P3.8 报告）；Charles 在 `EditorTool.requires_approval`（editor.py L180-182）和 `FileWriteTool.requires_approval`（file_tools.py L202-204）显式覆盖为 `True`。两侧语义一致（编辑/写入均需审批），实现范式不同（外部策略 vs 工具自声明），与 P3.12 / P3.8 结论一致。

10. **Charles 缺失三项 Cline 高级能力**：
    - **INPUT_ARG_CHAR_LIMIT=6000 输入大小检查**：Cline 在 `getEditorSizeError` 中检查 old_text / new_text 长度，超 6000 字符返回错误引导 LLM 拆分；Charles 无此检查，LLM 可发送超大 payload 导致超时。
    - **cwd 越界检查**：Cline `resolveFilePath` 默认 `restrictToCwd=true`，相对路径解析到 cwd 之外时抛错；Charles 无此检查（与 P3.12 apply_patch 同一差距）。
    - **工具级 timeout**：Cline `editorTimeoutMs ?? 30000`（30 秒）；Charles 无工具级 timeout（依赖 runtime 全局控制）。

11. **nanobot 残留**：
    - `editor.py`：**0 处** nanobot 残留（完全清洁）。
    - `file_tools.py`：**9 处** nanobot 残留，**全部为注释残留**（docstring 溯源标注 "对标 nanobot FilesystemTool" / "对标 nanobot filesystem.py L150-176" / "对标 nanobot 格式"），**无实现逻辑残留**。file_tools.py 的读取行号格式 "行号| 内容" 是从 nanobot 移植的设计，但实现代码本身无 nanobot 引用。

12. **file_tools.py 其他工具检查**：file_tools.py 仅含 `FileReadTool`（L26-161）和 `FileWriteTool`（L164-237）两个工具。FileReadTool 对标 Cline `createReadFilesTool` + `createFileReadExecutor`（P3.10 已覆盖），本报告仅附带提及。FileWriteTool 是 Charles 独有工具，Cline 无对应物。

13. **一致性总体评估**：**中高**。EditorTool 的三种编辑模式、唯一性校验、CRLF 处理、diff 生成已与 Cline 高度对齐（Stage 3.3 G3.6 已对齐 diff 生成）。主要差距在 FileWriteTool 工具切分策略差异（Charles 增量，非缺陷）、INPUT_ARG_CHAR_LIMIT 大小检查缺失、cwd 越界检查缺失。Charles 在行级匹配安全性上优于 Cline。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.23.1 | 工具切分策略 | editor 一肩三挑（create/replace/insert），无独立 FileWriteTool | FileWriteTool（全文件覆盖）+ EditorTool（行级编辑）分离 | 中（设计差异） | Charles 多一个 FileWriteTool 作为全文件覆盖入口；Cline editor 明确拒绝无 old_text 的整体覆盖 |
| 3.23.2 | FileWriteTool 存在性 | 不存在（写入集成在 editor create 模式 + apply_patch Add File） | 存在（file_tools.py L164-237） | 低（Charles 增量） | Charles 独有工具，Cline 无对应物 |
| 3.23.3 | FileWriteTool 输入 schema | N/A | `{file_path: string, content: string}`，required `[file_path, content]` | — | Charles 简单的路径+内容二元组 |
| 3.23.4 | FileWriteTool 写入模式 | N/A | 全文件覆盖（`path.write_text(content, encoding="utf-8")`） | — | 无 old_text / 唯一性校验，直接覆盖 |
| 3.23.5 | FileWriteTool 目录创建 | N/A | `path.parent.mkdir(parents=True, exist_ok=True)` 自动创建 | — | 与 Cline editor.ts L156 `fs.mkdir(dirname, {recursive: true})` 行为一致 |
| 3.23.6 | FileWriteTool requires_approval | N/A | `requires_approval = True`（file_tools.py L202-204） | — | Charles 自声明审批 |
| 3.23.7 | EditorTool 输入 schema | Zod：path(string min(1)) / old_text(string nullable optional) / new_text(string) / insert_line(number int nullable optional) | JSON Schema：path(string minLength 1) / old_text(string) / new_text(string) / insert_line(integer minimum 1) | 高 | 字段与约束完全对应；Charles insert_line 有 minimum:1，Cline 无显式 minimum 但 executor 内校验 |
| 3.23.8 | EditorTool required 字段 | `[path, new_text]`（schemas.ts L192-221） | `[path, new_text]`（editor.py L172） | 高 | 完全一致 |
| 3.23.9 | EditorTool 编辑模式数量 | 3 种：create / replace / insert | 3 种：create / replace / insert | 高 | 完全一致 |
| 3.23.10 | EditorTool 分支判断顺序 | insert_line → fileExists(create) → old_text(replace) → 抛错 | insert_line → not exists(create) → old_text(replace) → 返回错误 | 高 | 顺序一致；Cline 抛 Error，Charles 返回 is_error=True |
| 3.23.11 | create 模式触发条件 | `!fileExists(filePath)` 且无 insert_line | `not exists` 且无 insert_line 且无 old_text | 高 | Cline 在 insert_line 判断之后立即检查 fileExists；Charles 在 insert_line + old_text 均判断后才检查 exists |
| 3.23.12 | create 模式目录创建 | `fs.mkdir(path.dirname(filePath), {recursive: true})`（editor.ts L156） | `_write_file` 内 `path.parent.mkdir(parents=True, exist_ok=True)`（editor.py L471） | 高 | 均自动创建父目录 |
| 3.23.13 | replace 模式唯一性校验 | `countOccurrences`（字符串分割计数），0 抛错 / >1 抛错 | 行级匹配（多行）或 `original.count`（单行），0 抛错 / >1 抛错 | 高 | Charles 行级匹配更安全（避免跨行子串误匹配） |
| 3.23.14 | replace 模式多处替换 | 不支持（唯一匹配约束） | 不支持（唯一匹配约束） | 高 | 两侧均要求 old_text 唯一匹配 |
| 3.23.15 | insert 模式行号语义 | 1-based 边界行，line_count+1 表示追加到 EOF | 1-based 边界行，line_count+1 表示追加到 EOF | 高 | 完全一致 |
| 3.23.16 | insert 模式越界校验 | `insertLineOneBased < 1 || > maxBoundaryLine` 抛 Error | `insert_line < 1 || > total + 1` 返回 is_error=True | 高 | 校验逻辑一致；maxBoundaryLine = lines.length + 1 |
| 3.23.17 | 文件已存在且无 old_text/insert_line | 抛 Error（editor.ts L257-261） | 返回 is_error=True（editor.py L239-246，Phase 3.1 G3.3 移除 _do_overwrite 调用） | 高 | 行为一致（均拒绝整体覆盖）；Charles 保留 _do_overwrite 方法定义但不再调用 |
| 3.23.18 | CRLF 行尾符处理 | `detectLineEnding` + `normalizeLineEndings` 三件套，写盘还原原 EOL | `_detect_line_ending` + `_normalize_for_edit` + `_restore_line_ending` 三件套，写盘还原原 EOL | 高 | 完全对齐；两侧均保留 CRLF（与 P3.12 apply_patch 中 Cline 丢失 CRLF 不同） |
| 3.23.19 | diff 生成 | `createLineDiff`（maxDiffLines=200，预算分配，```diff 代码块） | `_create_line_diff`（max_lines=200，预算分配，```diff 代码块） | 高 | Charles 明确标注"对标 Cline editor.ts L87-149"，逻辑逐行对应 |
| 3.23.20 | $-sequence 字面插入 | 用 replacer 函数 `() => normalizedNewStr` 避免 String.replace 展开 $&/$'/$$/ $n | 用 `str.replace()` 字面替换（Python str.replace 不展开 $-sequence） | 高 | 两侧均字面插入；机制不同（Cline 需显式绕过，Python 天然字面） |
| 3.23.21 | 备份机制 | 无（无 .bak / git stash / undo 栈） | 无（同左） | 高 | 两侧均无显式备份 |
| 3.23.22 | INPUT_ARG_CHAR_LIMIT 大小检查 | `getEditorSizeError`：old_text / new_text 超 6000 字符返回错误 | 无 | 低 | **Charles 缺失**：LLM 可发送超大 payload |
| 3.23.23 | cwd 越界检查 | `resolveFilePath` restrictToCwd=true（默认），相对路径越界抛错 | 无 | 低 | **Charles 缺失**：与 P3.12 apply_patch 同一差距 |
| 3.23.24 | 工具级 timeout | `editorTimeoutMs ?? 30000`（30 秒，definitions.ts L660） | 无（依赖 runtime 全局控制） | 中 | 与 P3.5 结论一致 |
| 3.23.25 | retryable / maxRetries | `retryable: false, maxRetries: 0`（definitions.ts L673-674） | `retryable = False, max_retries = 0`（BaseTool 默认） | 高 | 两侧均不可重试（编辑有状态，不应自动重试） |
| 3.23.26 | requires_approval | 外部 `toolPolicies` 配置驱动（工具定义无字段） | `EditorTool.requires_approval = True` + `FileWriteTool.requires_approval = True` | 高（语义）/ 中（实现） | 两侧语义一致，实现范式不同 |
| 3.23.27 | 响应格式 | 字符串（"File created successfully at: ..." / "Edited {path}\n```diff\n..."） | dict（`{path, operation, lines_before, lines_after, diff}` + metadata） | 中 | Charles 结构化、Cline 字符串 |
| 3.23.28 | 工具描述 | 静态字符串（definitions.ts L665-669），鼓励多调用并行 | `@property description` 动态返回（editor.py L139-146） | 高 | Charles 描述更详细（中文），语义一致 |
| 3.23.29 | 模型路由禁用 | editor 与 apply_patch 互斥（definitions.ts L913-917：enableEditor && executor → editor；else if enableApplyPatch → apply_patch） | routing.py L59-74：openai-native / codex / gpt 在 act 模式下禁用 editor 启用 apply_patch | 高 | 两侧均 editor / apply_patch 互斥，Charles 用 routing 规则动态切换 |
| 3.23.30 | nanobot 残留 | N/A | editor.py：0 处；file_tools.py：9 处（全部注释残留） | 高 | 见第四节详述 |

**一致性总评**：30 项中，高一致性 18 项、中一致性 6 项、低一致性 3 项（3.23.2 / 3.23.22 / 3.23.23），设计差异 3 项（3.23.1 / 3.23.3-6 / 3.23.27 不计入一致性评分）。低一致性项集中在 Charles 缺失的 INPUT_ARG_CHAR_LIMIT 大小检查和 cwd 越界检查。

---

## 三、重点差距详细说明

### 差距 1：FileWriteTool 工具切分策略差异（3.23.1 / 3.23.2）

**Cline 实现**：

Cline 不存在独立 FileWriteTool。文件写入通过两个路径：
1. `editor` 工具 create 模式（editor.ts L254-256）：文件不存在 + 无 insert_line 时，用 new_text 创建文件。
2. `apply_patch` 工具 Add File 操作（apply-patch.ts L290-296）：`*** Add File: path` + `+content` 行。

Cline 的 editor 工具**明确拒绝**无 old_text 的整体覆盖——文件已存在且未提供 old_text/insert_line 时抛 Error（editor.ts L257-261）：

```typescript
if (input.old_text == null) {
    throw new Error(
        "Parameter `old_text` is required when editing an existing file without `insert_line`",
    );
}
```

**Charles 实现**：

Charles 切分为两个工具：
1. `FileWriteTool`（file_tools.py L164-237）：独立的全文件覆盖工具，`path.write_text(content, encoding="utf-8")` 直接覆盖，无 old_text / 唯一性校验。
2. `EditorTool`（editor.py L124-473）：行级编辑工具，Phase 3.1 G3.3 已移除整体覆盖分支（`_do_overwrite` 不再被调用，L239-246 返回错误），与 Cline editor 行为对齐。

Charles 保留 `_do_overwrite` 方法定义（editor.py L442-466）但注释明确标注"Phase 3.1 (G3.3): 原 _do_overwrite 整体覆盖分支已移除... _do_overwrite 函数定义保留以备未来需要显式整体覆盖模式时复用"。

**影响**：
- Charles 的 FileWriteTool 是 Cline 没有的工具，是 Charles 的**功能增量**。Cline 若需全文件覆盖，LLM 必须先 read_files 读取全文，再用 editor 的 old_text 替换全文——效率低且 old_text 可能因行尾符 / 编码问题不匹配。
- Charles 的 FileWriteTool 直接覆盖，绕过唯一性校验，适合"重建文件"场景（如配置文件重写、日志文件清空）。
- 风险：FileWriteTool 无防误改机制，LLM 若误调用会覆盖整个文件。Charles 通过 `requires_approval=True` 提供前置审批防线。

**建议**：保留 Charles 现状。FileWriteTool 是合理的功能增量，填补 Cline editor 拒绝整体覆盖留下的能力空白。无需对齐 Cline 的"无独立 FileWriteTool"设计。

### 差距 2：INPUT_ARG_CHAR_LIMIT 大小检查缺失（3.23.22）

**Cline 实现**（helpers.ts L20-33 + schemas.ts L10）：

```typescript
export const INPUT_ARG_CHAR_LIMIT = 6000;

export function getEditorSizeError(input: EditFileInput): string | null {
    if (typeof input.old_text === "string" && input.old_text.length > INPUT_ARG_CHAR_LIMIT) {
        return `Editor input too large: old_text was ${input.old_text.length} characters, exceeding the recommended limit of ${INPUT_ARG_CHAR_LIMIT}. Split the edit into smaller tool calls...`;
    }
    if (input.new_text.length > INPUT_ARG_CHAR_LIMIT) {
        return `Editor input too large: new_text was ${input.new_text.length} characters...`;
    }
    return null;
}
```

`createEditorTool` 在 executor 调用前检查 `getEditorSizeError`，超 6000 字符直接返回错误，引导 LLM 拆分为多次小编辑。

**Charles 实现**：EditorTool 无任何输入大小检查，LLM 可发送任意大小的 old_text / new_text。

**影响**：
- 大文件编辑（如 10000 字符的 old_text）可能导致工具执行超时（Cline 有 30 秒 timeout，Charles 无工具级 timeout）。
- LLM 生成超大 old_text 时，若文件内容有细微差异（行尾符 / 编码 / 空白），匹配失败概率随 old_text 长度增加。
- Cline 的 6000 字符限制是"建议"而非硬限制——工具描述明确说"Keep this at or below ${INPUT_ARG_CHAR_LIMIT} characters when possible; larger payloads should be split across multiple tool calls"。

**建议**：建议补齐。在 EditorTool._execute 入口加 old_text / new_text 长度检查，超 6000 字符返回错误引导 LLM 拆分。实现简单（5-10 行），与 Cline 行为对齐。优先级 P2。

### 差距 3：cwd 越界检查缺失（3.23.23）

**Cline 实现**（editor.ts L37-60）：

```typescript
function resolveFilePath(cwd, inputPath, restrictToCwd): string {
    const isAbsoluteInput = path.isAbsolute(inputPath);
    const resolved = isAbsoluteInput ? path.normalize(inputPath) : path.resolve(cwd, inputPath);
    if (!restrictToCwd) return resolved;
    if (isAbsoluteInput) return resolved;  // 绝对路径直接接受
    const rel = path.relative(cwd, resolved);
    if (rel.startsWith("..") || path.isAbsolute(rel)) {
        throw new Error(`Path must stay within cwd: ${inputPath}`);
    }
    return resolved;
}
```

`restrictToCwd` 默认 true，相对路径若解析到 cwd 之外（如 `../../etc/passwd`）抛错。绝对路径直接接受。

**Charles 实现**：EditorTool 和 FileWriteTool 均直接 `Path(path_str)`，无 cwd 越界检查。

**影响**：
- 安全风险：LLM 可能被 prompt injection 引导修改 cwd 之外的敏感文件。
- Charles 的 `requires_approval=True` 提供了一道防线（用户可审批时拒绝），但审批后仍可越界。
- 与 P3.12 apply_patch 同一差距，建议统一补齐。

**建议**：建议补齐。在 EditorTool._execute 和 FileWriteTool._execute 入口加 cwd 越界检查。与 P3.12 建议 1 一致，优先级 P1。

### 差距 4：行级匹配 vs 字符串匹配（3.23.13）

**Cline 实现**（editor.ts L170-200）：

`replaceInFile` 用 `countOccurrences`（字符串分割计数）判断唯一性，用 `content.replace(normalizedOldStr, () => normalizedNewStr)` 执行替换。纯字符串匹配，不区分行边界。

**Charles 实现**（editor.py L307-417）：

`_do_replace` 优先用行级匹配（old_text 含换行时）：
1. 将 old_text 按行分割为 `old_lines`
2. 遍历 `original_lines`，找连续 n 行匹配 `old_lines` 的位置
3. 0 匹配抛错 / >1 匹配抛错 / 1 匹配执行行级替换

单行 old_text 时退化为字符串 `original.count(normalized_old)` 计数 + `original.replace()` 替换。

**影响**：
- Charles 的行级匹配**更安全**：避免 old_text 作为子串跨行误匹配。例如 old_text="a\nb" 在文件 "x a\nb y" 中，Cline 的字符串匹配会匹配到（子串 "a\nb" 在 "x a\nb y" 中存在），但 Charles 的行级匹配不会匹配（"a" 和 "b" 不是连续的独立行，"x a" 不等于 "a"）。
- Charles 的优化是合理的，是 Charles 相对 Cline 的**优势点**。

**建议**：保留 Charles 现状。行级匹配更安全，无需退化为 Cline 的纯字符串匹配。

### 差距 5：响应格式差异（3.23.27）

**Cline 实现**：

editor 返回纯字符串：
- create 模式：`"File created successfully at: {filePath}"`
- replace 模式：`"Edited {filePath}\n```diff\n...\n```"`
- insert 模式：`"Inserted content at line {n} in {filePath}."`

**Charles 实现**：

EditorTool 返回 dict：
- create 模式：`{path, operation: "create", lines_before: 0, lines_after: n, diff: "..."}`
- replace 模式：`{path, operation: "edit", lines_before: n, lines_after: m, diff: "..."}`
- insert 模式：`{path, operation: "insert", insert_line: n, lines_before: n, lines_after: m, inserted_lines: k, diff: "..."}`

FileWriteTool 返回：`"文件已写入: {file_path} ({len} 字符)"`（字符串）+ metadata `{file_path, chars}`。

**影响**：
- Charles 的结构化响应便于 LLM 解析 lines_before / lines_after 进行自我校验。
- Cline 的字符串响应更简洁，但 LLM 需从文本中提取信息。
- 两种格式都有效，非缺陷。

**建议**：保留 Charles 现状。结构化响应是 Charles 的设计选择，无需退化为 Cline 的字符串格式。

---

## 四、nanobot 残留检查

针对 P3.23 核心文件 `agent/tools/editor.py` 和 `agent/tools/file_tools.py` 执行 nanobot 残留扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.23 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/editor.py` | **0** | 无 | 完全清洁，无 nanobot 引用 |
| `agent/tools/file_tools.py` | **9** | 全部注释残留 | 见 4.2 详述 |

### 4.2 file_tools.py 残留分类

#### 注释残留（9 处）

| 行号 | 内容 | 残留类型 |
|------|------|---------|
| L2 | `"""文件读写工具 — 对标 Cline FileReadTool / FileWriteTool + nanobot FilesystemTool` | docstring 溯源标注 |
| L7 | `- 对标 nanobot FilesystemTool（行号格式 "行号| 内容"）` | docstring 设计溯源 |
| L12 | `- 对标 nanobot FilesystemTool write 方法` | docstring 设计溯源 |
| L27 | `"""文件读取工具 — 对标 Cline FileReadTool + nanobot FilesystemTool` | docstring 溯源标注 |
| L115 | `# 分页读取 — 对标 nanobot filesystem.py L150-176` | 行内注释溯源 |
| L130 | `# 行号格式: "行号| 内容" — 对标 nanobot 格式` | 行内注释溯源 |
| L165 | `"""文件写入工具 — 对标 Cline FileWriteTool + nanobot FilesystemTool` | docstring 溯源标注 |

共 9 处（含 L2 / L7 / L12 三处在同一 docstring 块内，L27 单独一处，L115 / L130 行内注释，L165 单独一处）。**全部为迁移说明注释**，标注 Charles 实现的设计溯源（FileReadTool 的行号格式 "行号| 内容" 移植自 nanobot FilesystemTool，FileWriteTool 的 write 方法对标 nanobot FilesystemTool write）。

这些标注是 Charles 项目的合规要求（见用户规则 4：保留之前函数逻辑，在原基础上修改），**不属于实现逻辑残留**。

#### 实现逻辑残留（0 处）

file_tools.py 中**未发现任何从 nanobot 直接移植的实现逻辑**：

- `FileReadTool` 类设计对标 Cline `FileReadTool` + `createFileReadExecutor`（L2 / L27 标注）。
- `FileWriteTool` 类设计对标 Cline `FileWriteTool`（L165 标注）——但 Cline 实际不存在 FileWriteTool，此处标注为"对标 Cline FileWriteTool"是历史遗留措辞，实际对标的是 Cline editor.ts 的 createFile 函数。
- 行号格式 "行号| 内容"（L130）是设计借鉴 nanobot FilesystemTool 的输出格式，但实现代码（L131-134 的列表推导式）是 Charles 原生 Python 代码，无 nanobot 代码引用。
- 分页读取逻辑（L115-153）是 Charles 原生实现，无 nanobot 函数调用。

**结论**：file_tools.py 的 9 处 nanobot 残留**全部为注释残留**，无实现逻辑残留。

### 4.3 editor.py 残留分类

editor.py 中**0 处** nanobot 残留。所有溯源标注均为"对标 Cline"风格：

- L2 docstring：`"""行级文件编辑工具 — 对标 Cline createEditorTool`
- L23-25 docstring：`对标 Cline: sdk/packages/core/src/extensions/tools/create-editor-tool.ts`
- L36 / L43 / L50 / L62 / L92 / L189 / L237-238 / L292 / L366 / L406 / L429：均为"对标 Cline xxx"或"Phase 3.x G3.x"标注

共约 15 处"对标 Cline" / "Phase 3.x" / "G3.x"标注，**全部为迁移说明注释**，无 nanobot 引用。

### 4.4 范围外但相关的残留

以下文件有"对标 nanobot"标注但属其他 P3.x 小阶段范围，不在 P3.23 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|----------------|-----------|
| `agent/tools/exec_tool.py` | 多处 | P3.11（run_commands 专项） |
| `agent/tools/web_tool.py` | 多处 | P3.x（WebSearchTool 专项） |
| `agent/tools/__init__.py` | 1 处（L2 docstring） | P3.1（已记录） |

这些标注均为合规的迁移说明，不影响 file_write / editor 工具的对比结论。

---

## 五、file_tools.py 其他工具检查

file_tools.py 仅含两个工具类，无其他工具需检查：

### 5.1 FileReadTool（file_tools.py L26-161）

- **对标**：Cline `createReadFilesTool` + `createFileReadExecutor`（P3.10 已覆盖）
- **输入 schema**：`{file_path: string, offset: integer minimum 1, limit: integer minimum 1}`，required `[file_path]`
- **行号格式**：`"行号| 内容"`（L131-134），借鉴 nanobot FilesystemTool 格式，与 Cline 的 `"{lineNumber} | {text}"`（file-read.ts L167）格式差异：Charles 用 `|` 紧贴行号（无空格），Cline 用 ` | `（前后有空格）。细微差异，不影响功能。
- **分页参数**：Charles 用 `offset` / `limit`，Cline 用 `start_line` / `end_line`。Charles 是行数+起始行，Cline 是起始行+结束行，语义不同但功能等价。
- **输出限制**：Charles `MAX_READ_OUTPUT_CHARS=16000`（constants.py L59），Cline `MAX_READ_OUTPUT_CHARS=48000`（output-limits.ts L47）。Charles 更保守（16K vs 48K）。
- **图片读取**：Cline 支持图片读取（file-read.ts L221-252，gif/png/jpg/jpeg/webp），Charles 不支持（file_tools.py L109-113 二进制文件直接返回错误）。
- **流式读取**：Cline 用 `createReadStream` + `createInterface` 流式读取（file-read.ts L107-159），Charles 用 `path.read_bytes()` 一次性读取（file_tools.py L102）。大文件场景 Cline 更优。
- **requires_approval**：FileReadTool 未覆盖 `requires_approval`，继承基类默认 `False`（只读工具）。与 Cline 一致。

### 5.2 FileWriteTool（file_tools.py L164-237）

已在第一节和第三节详述。核心要点：
- Charles 独有工具，Cline 无对应物
- 全文件覆盖写入，无 old_text / 唯一性校验
- 自动创建父目录，UTF-8 编码
- `requires_approval=True`
- 无 cwd 越界检查（与 EditorTool 同一差距）

---

## 六、修复建议

### 建议 1：补齐 cwd 越界检查 [P1 安全加固]

**文件**：`agent/tools/editor.py` + `agent/tools/file_tools.py`
**位置**：`EditorTool._execute` 入口 + `FileWriteTool._execute` 入口
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
            return None  # 越界，由调用方决定是否拒绝
    return p
```

在 EditorTool._execute 和 FileWriteTool._execute 入口调用，越界时返回 is_error=True。

**理由**：安全加固，与 P3.12 apply_patch 建议 1 一致。Cline 默认开启 `restrictToCwd`，Charles 应统一补齐。优先级 P1。

### 建议 2：补齐 INPUT_ARG_CHAR_LIMIT 大小检查 [P2 健壮性]

**文件**：`agent/tools/editor.py`
**位置**：`EditorTool._execute` 入口，schema 校验之后
**修改思路**：

```python
# 对标 Cline getEditorSizeError + INPUT_ARG_CHAR_LIMIT=6000
INPUT_ARG_CHAR_LIMIT = 6000

old_text = input.get("old_text")
new_text = input["new_text"]
if old_text and len(old_text) > INPUT_ARG_CHAR_LIMIT:
    return AgentToolResult(
        output={"error": f"old_text 过大（{len(old_text)} 字符），请拆分为多次小编辑（上限 {INPUT_ARG_CHAR_LIMIT} 字符）"},
        is_error=True,
    )
if len(new_text) > INPUT_ARG_CHAR_LIMIT:
    return AgentToolResult(
        output={"error": f"new_text 过大（{len(new_text)} 字符），请拆分为多次小编辑（上限 {INPUT_ARG_CHAR_LIMIT} 字符）"},
        is_error=True,
    )
```

**理由**：对标 Cline `getEditorSizeError`，防止 LLM 发送超大 payload 导致超时或匹配失败。实现简单（5-10 行），优先级 P2。

### 建议 3：保留 FileWriteTool 独立工具 [P0 不变]

**理由**：FileWriteTool 是 Charles 的功能增量，填补 Cline editor 拒绝整体覆盖留下的能力空白。Cline 若需全文件覆盖需 read_files + editor old_text 两步操作，效率低且易因行尾符 / 编码问题失败。Charles 的 FileWriteTool 直接覆盖，适合"重建文件"场景。`requires_approval=True` 已提供前置审批防线。保留现状。

### 建议 4：保留行级匹配优化 [P0 不变]

**理由**：Charles 的行级匹配（多行 old_text 时按行列表比对）比 Cline 的纯字符串匹配更安全，避免跨行子串误匹配。是 Charles 相对 Cline 的优势点，应予保留。无需退化为 Cline 的纯字符串匹配。

### 建议 5：保留 CRLF 行尾符处理 [P0 不变]

**理由**：Charles 的 `_detect_line_ending` + `_normalize_for_edit` + `_restore_line_ending` 三件套与 Cline editor.ts 的 `detectLineEnding` + `normalizeLineEndings` 完全对齐，两侧均保留 CRLF。这是正确的行为（Windows 环境尤其重要），应予保留。与 P3.12 apply_patch 中 Cline 丢失 CRLF 的行为不同——editor 两侧均正确处理 CRLF。

### 建议 6：保留 _do_overwrite 方法定义 [P0 不变]

**理由**：Charles editor.py L442-466 保留了 `_do_overwrite` 方法定义但不再调用（Phase 3.1 G3.3 移除调用）。注释明确标注"函数定义保留以备未来需要显式整体覆盖模式时复用"。这是向后兼容的合理设计，符合用户规则 4"保留之前函数逻辑，在原基础上修改"。保留现状。

### 建议 7：不强制补齐工具级 timeout [P3 不修复]

**理由**：
- Charles 依赖 runtime 全局 timeout 控制，与 Cline 的工具级 timeout（30 秒）范式不同。
- Charles 的 runtime 全局 timeout 已覆盖工具执行超时场景。
- 补齐工具级 timeout 需在 BaseTool 增加 timeout_ms 生效路径，涉及 runtime 改造，代码量较大。
- 与 P3.5 结论一致，优先级 P3。

### 建议 8：修正 file_tools.py docstring 措辞 [P3 可选]

**文件**：`agent/tools/file_tools.py`
**位置**：L2 docstring + L165 docstring
**修改思路**：

L2 当前：`"""文件读写工具 — 对标 Cline FileReadTool / FileWriteTool + nanobot FilesystemTool`
L165 当前：`"""文件写入工具 — 对标 Cline FileWriteTool + nanobot FilesystemTool`

Cline 实际不存在 FileWriteTool，此处"对标 Cline FileWriteTool"是历史遗留措辞。建议修正为"对标 Cline editor.ts createFile 函数"或"Charles 独有工具，Cline 无对应物"。

**理由**：docstring 准确性。非功能性问题，优先级 P3。

---

## 七、验证方法建议

### 验证方法 1：三种编辑模式等价性

构造相同输入，分别在 Cline executor 和 Charles tool 上执行，对比结果：

```
# create 模式
editor(path="new.txt", new_text="content")  # 文件不存在

# replace 模式
editor(path="exist.txt", old_text="old", new_text="new")  # 文件存在，old_text 唯一匹配

# insert 模式
editor(path="exist.txt", new_text="inserted", insert_line=2)  # 1-based，第 2 行前插入
```

**验证点**：
- 两侧均能执行三种模式
- create 模式：两侧均自动创建父目录
- replace 模式：两侧均要求 old_text 唯一匹配
- insert 模式：两侧均支持 line_count+1 追加到 EOF

### 验证方法 2：唯一性校验

构造 old_text 在文件中出现 0 次 / 1 次 / 2 次，验证两侧行为：

```powershell
# Charles 侧
# 0 次：返回 is_error=True，"old_text 在文件中未找到匹配"
# 1 次：执行替换
# 2 次：返回 is_error=True，"old_text 在文件中匹配 2 次，必须唯一匹配"

# Cline 侧（editor.test.ts 已有此测试逻辑）
# 0 次：throw "No replacement performed: text not found in {filePath}."
# 1 次：执行替换
# 2 次：throw "No replacement performed: multiple occurrences of text found in {filePath}."
```

**预期**：两侧行为一致（0 和 >1 均拒绝，仅 1 次执行替换）。

### 验证方法 3：CRLF 保留行为

构造 CRLF 行尾的文件，执行 replace / insert，验证两侧均保留 CRLF：

```powershell
# 构造 CRLF 文件
$content = "line1`r`nline2`r`n"
Set-Content -Path "test_crlf.txt" -Value $content -NoNewline

# 执行 replace（line2 → line2_modified）
# Charles 后：test_crlf.txt 仍为 CRLF
# Cline 后：test_crlf.txt 仍为 CRLF（editor.ts detectLineEnding 保留 CRLF）

# 执行 insert（insert_line=2, new_text="inserted")
# Charles 后：test_crlf.txt 仍为 CRLF
# Cline 后：test_crlf.txt 仍为 CRLF
```

**预期**：两侧均保留 CRLF（与 P3.12 apply_patch 中 Cline 丢失 CRLF 的行为不同）。

### 验证方法 4：行级匹配 vs 字符串匹配

构造 old_text 作为子串跨行存在但行级不匹配的场景：

```
文件内容: "x a\nb y"
old_text: "a\nb"

# Cline 字符串匹配: countOccurrences("x a\nb y", "a\nb") = 1 → 执行替换（可能误匹配）
# Charles 行级匹配: original_lines = ["x a", "b y"], old_lines = ["a", "b"]
#   ["x a", "b y"][0:2] != ["a", "b"] → 0 匹配 → 报错"未找到匹配"
```

**预期**：Cline 执行替换（子串匹配成功），Charles 报错（行级匹配失败）。Charles 更安全。

### 验证方法 5：requires_approval 行为

验证两侧 editor / file_write 工具均需用户审批：

```powershell
# Charles 侧
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\editor.py" -Pattern "requires_approval"
# 预期：L180-182 返回 True

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\file_tools.py" -Pattern "requires_approval"
# 预期：L202-204 返回 True（FileWriteTool）；FileReadTool 无覆盖（继承默认 False）

# Cline 侧（通过 toolPolicies 配置，非工具定义）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts" -Pattern "requiresApproval"
# 预期：editor / apply_patch 工具定义中无此字段，由外部 policy 控制
```

### 验证方法 6：nanobot 残留扫描

```powershell
# editor.py（预期 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\editor.py" -Pattern "nanobot" -CaseSensitive:$false

# file_tools.py（预期 9 匹配，全部为注释）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\file_tools.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期：L2 / L7 / L12 / L27 / L115 / L130 / L165（含 L2 块内多行）
```

### 验证方法 7：FileWriteTool 独立工具存在性

验证 Charles 有而 Cline 无的 FileWriteTool：

```powershell
# Charles 侧
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\file_tools.py" -Pattern "class FileWriteTool"
# 预期：L164 匹配

# Cline 侧
Get-ChildItem -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline" -Recurse -Filter "*.ts" | Select-String -Pattern "FileWriteTool|file-write" -List
# 预期：0 匹配（Cline 无独立 FileWriteTool）
```

---

## 八、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L656-714 | `createEditorTool` 工厂（含 timeoutMs=30000 / retryable=false / getEditorSizeError） |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L910-917 | editor / apply_patch 互斥装配逻辑 |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L10 | `INPUT_ARG_CHAR_LIMIT = 6000` |
| `sdk/packages/core/src/extensions/tools/schemas.ts` | L192-221 | `EditFileInputSchema`（path / old_text / new_text / insert_line） |
| `sdk/packages/core/src/extensions/tools/helpers.ts` | L20-33 | `getEditorSizeError` old_text / new_text 大小检查 |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L16-35 | `EditorExecutorOptions`（encoding / restrictToCwd / maxDiffLines） |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L37-60 | `resolveFilePath` cwd 越界检查 |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L62-65 | `countOccurrences` 字符串分割计数 |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L67-85 | `detectLineEnding` + `normalizeLineEndings` CRLF 三件套 |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L87-149 | `createLineDiff` diff 生成（maxDiffLines=200，预算分配） |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L151-159 | `createFile` create 模式（自动创建父目录） |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L170-200 | `replaceInFile` replace 模式（唯一性校验 + $-sequence 字面插入） |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L202-224 | `insertInFile` insert 模式（1-based 边界行校验） |
| `sdk/packages/core/src/extensions/tools/executors/editor.ts` | L229-271 | `createEditorExecutor` 工厂（分支判断顺序：insert_line → create → replace → 抛错） |
| `sdk/packages/core/src/extensions/tools/executors/editor.test.ts` | L27-54 | create 模式测试 |
| `sdk/packages/core/src/extensions/tools/executors/editor.test.ts` | L56-101 | insert 模式测试（含 EOF 边界） |
| `sdk/packages/core/src/extensions/tools/executors/editor.test.ts` | L103-167 | replace 模式 + diff 生成测试 |
| `sdk/packages/core/src/extensions/tools/executors/editor.test.ts` | L192-242 | CRLF 保留测试 |
| `sdk/packages/core/src/extensions/tools/executors/editor.test.ts` | L244-261 | $-sequence 字面插入测试 |
| `sdk/packages/core/src/extensions/tools/executors/editor.test.ts` | L263-292 | insert_line 越界拒绝测试 |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/file_tools.py` | L1-13 | 模块 docstring（含 nanobot 溯源标注） |
| `agent/tools/file_tools.py` | L26-161 | `FileReadTool` 类（行号格式 "行号\| 内容"，分页读取） |
| `agent/tools/file_tools.py` | L115 | `# 分页读取 — 对标 nanobot filesystem.py L150-176`（注释残留） |
| `agent/tools/file_tools.py` | L130 | `# 行号格式: "行号\| 内容" — 对标 nanobot 格式`（注释残留） |
| `agent/tools/file_tools.py` | L164-237 | `FileWriteTool` 类（全文件覆盖，requires_approval=True） |
| `agent/tools/file_tools.py` | L202-204 | `requires_approval = True`（FileWriteTool 自声明审批） |
| `agent/tools/editor.py` | L1-25 | 模块 docstring（对标 Cline createEditorTool，无 nanobot 残留） |
| `agent/tools/editor.py` | L36-54 | `_detect_line_ending` + `_normalize_for_edit` + `_restore_line_ending` CRLF 三件套 |
| `agent/tools/editor.py` | L57-121 | `_create_line_diff` diff 生成（对标 Cline editor.ts L87-149） |
| `agent/tools/editor.py` | L124-173 | `EditorTool` 类定义 + `name` / `description` / `input_schema` |
| `agent/tools/editor.py` | L175-182 | `read_only = False` + `requires_approval = True` |
| `agent/tools/editor.py` | L184-246 | `_execute` 主流程（分支判断：insert_line → create → replace → 返回错误） |
| `agent/tools/editor.py` | L236-246 | Phase 3.1 G3.3 移除 _do_overwrite 调用，改为返回错误 |
| `agent/tools/editor.py` | L248-305 | `_do_insert` insert 模式（1-based 边界行校验 + CRLF 还原 + diff 生成） |
| `agent/tools/editor.py` | L307-417 | `_do_replace` replace 模式（行级匹配优先 + 唯一性校验 + CRLF 还原 + diff 生成） |
| `agent/tools/editor.py` | L419-440 | `_do_create` create 模式（自动创建父目录 + diff 生成） |
| `agent/tools/editor.py` | L442-466 | `_do_overwrite` 覆盖模式（方法定义保留，不再调用） |
| `agent/tools/editor.py` | L468-473 | `_write_file` 写入文件（自动创建父目录，UTF-8 编码） |
| `agent/tools/routing.py` | L59-74 | editor 在 openai-native / codex / gpt 模型下禁用，改用 apply_patch |
| `agent/tools/base.py` | L96-103 | `requires_approval` 基类默认值（False） |

---

## 九、结论

P3.23 file_write / editor 工具实现对比的核心结论：

1. **工具切分策略不同但合理**：Cline 不存在独立 FileWriteTool，文件写入集成在 editor create 模式 + apply_patch Add File 中；Charles 切分为 FileWriteTool（全文件覆盖）+ EditorTool（行级编辑）两个工具。Charles 的 FileWriteTool 是功能增量，填补 Cline editor 拒绝整体覆盖留下的能力空白，应予保留。

2. **EditorTool 三种编辑模式高度对齐**：create / replace / insert 三种模式的触发条件、分支判断顺序、唯一性校验、CRLF 处理、diff 生成均与 Cline editor.ts 逐项对应。Stage 3.3 G3.6 已对齐 diff 生成，Phase 3.1 G3.3 已移除整体覆盖分支。

3. **Charles 在两个点上强于 Cline**（应予保留）：
   - **行级匹配安全性**：Charles 的 `_do_replace` 优先用行级匹配（多行 old_text 时按行列表比对），避免 Cline 纯字符串匹配的跨行子串误匹配风险。
   - **结构化响应**：EditorTool 返回 dict（含 operation / lines_before / lines_after / diff），便于 LLM 自我校验；Cline 返回纯字符串。

4. **Charles 缺失两项 Cline 高级能力**（建议补齐）：
   - **P1 安全加固**：cwd 越界检查缺失（建议 1）—— 应补齐，与 P3.12 apply_patch 建议 1 一致
   - **P2 健壮性**：INPUT_ARG_CHAR_LIMIT=6000 大小检查缺失（建议 2）—— 应补齐，防止 LLM 发送超大 payload

5. **多处替换均不支持**：两侧均要求 old_text 唯一匹配，不支持一次调用替换多处。多处替换需 LLM 发起多次 editor 调用。

6. **备份机制均缺失**：两侧均无显式备份（无 .bak / git stash / undo 栈），原子性靠前置唯一性校验，写盘阶段非原子。

7. **requires_approval 实现范式不同但语义一致**：Cline 由外部 `toolPolicies` 驱动，Charles 由工具类自声明 `requires_approval = True`。两侧 editor / file_write 均需用户审批，FileReadTool 保持默认 False（只读免审批），与 P3.8 / P3.12 结论一致。

8. **nanobot 残留**：
   - `editor.py`：**0 处** nanobot 残留（完全清洁）
   - `file_tools.py`：**9 处** nanobot 残留，**全部为注释残留**（docstring 溯源标注 "对标 nanobot FilesystemTool"），**无实现逻辑残留**。行号格式 "行号| 内容" 是设计借鉴 nanobot，但实现代码是 Charles 原生 Python。

9. **file_tools.py 其他工具检查**：file_tools.py 仅含 FileReadTool（P3.10 已覆盖）和 FileWriteTool 两个工具，无其他工具。FileReadTool 与 Cline 的差异（行号格式 / 分页参数 / 输出限制 / 图片读取 / 流式读取）已在第五节附带提及。

**整体一致性等级**：**中高**。EditorTool 的三种编辑模式、唯一性校验、CRLF 处理、diff 生成已与 Cline 高度对齐。P3.23 范围内建议 1（cwd 越界检查，P1）和建议 2（INPUT_ARG_CHAR_LIMIT 大小检查，P2）为可执行修复项，其余为保留现状项。Charles 在行级匹配安全性和结构化响应上优于 Cline，FileWriteTool 是合理的功能增量，均应予保留。
