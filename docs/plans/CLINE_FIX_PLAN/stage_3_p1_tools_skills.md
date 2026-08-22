# Stage 3: P1 工具与技能修复方案

> 生成时间：2026-07-26
> 覆盖范围：CLINE_DIFF/phase_G_builtin_tools_file_cmd_edit.md（G1.6/G3.3/G3.6/G4.4）
>           CLINE_DIFF/phase_I_skills.md（I6/I8/I12）
>           CLINE_DIFF/phase_Q_mcp.md（Q8 per-tool policies）
> 依赖：stage_1（apply_patch 原子性基础已建立）、stage_2（核心架构对齐）
> 原则：基于差距分析但需 Read 实际代码后判断，保留原函数逻辑在其基础上修改

---

## 总览

| 小阶段 | 任务 | 来源 | 优先级 | 修改文件 |
|--------|------|------|--------|----------|
| 3.1 | editor 文件已存在覆盖行为对齐 | G3.3 | P1 | agent/tools/editor.py |
| 3.2 | read_files 行号输出 | G1.6 | P1 | agent/tools/read_files.py |
| 3.3 | editor diff 生成 | G3.6 | P1 | agent/tools/editor.py |
| 3.4 | apply_patch 部分成功回滚完善 | G4.4 后续 | P1 | agent/tools/apply_patch.py |
| 3.5 | 技能 frontmatter BOM/CRLF 兼容 | I12 | P2 | agent/skills/loader.py |
| 3.6 | 技能 runningSkills key 规范化 | I6 | P2 | agent/skills/skill_tool.py |
| 3.7 | 技能 allowedSkillNames 多形式匹配 | I8 | P2 | agent/skills/registry.py |
| 3.8 | MCP per-tool policies | Q8 | P1 | agent_config/mcp_servers.yaml + agent/mcp/registry.py |

---

## 3.1 editor 文件已存在覆盖行为对齐（G3.3）

### 任务背景

来源 Phase G #G3.3，**语义不等价差距**。

- **Cline 行为**（`editor.ts` L254-261）：文件已存在且未提供 `old_text` 或 `insert_line` 时，**抛错拒绝执行**。这是安全护栏，防止 LLM 漏传 `old_text` 导致整个文件被覆盖。
- **我的行为**（`editor.py` L163-169 + L353-377 `_do_overwrite`）：文件已存在且未提供 `old_text`/`insert_line` 时，**直接用 `new_text` 覆盖整个文件**，仅在返回结果的 `note` 字段标注。

风险：LLM 若误调用 `editor(path="existing.py", new_text="new content")`（漏传 `old_text`），我会直接覆盖整个文件，量化策略文件、配置文件被误覆盖会造成实际损失。

### 目标

对齐 Cline 的严格行为：文件已存在且未提供 `old_text`/`insert_line` 时，返回错误结果（`is_error=True`），不再执行整体覆盖。

### 当前实现位置

- `agent/tools/editor.py` L163-169：`_execute` 末尾的覆盖分支
  ```python
  # 分支: 创建模式（文件不存在且无 old_text）
  if not exists:
      return self._do_create(path, path_str, new_text)

  # 文件已存在但没有提供 old_text 或 insert_line — 视为整体覆盖
  # 保留原有逻辑：用 new_text 覆盖文件
  return self._do_overwrite(path, path_str, original, new_text, lines_before, line_ending)
  ```
- `agent/tools/editor.py` L353-377：`_do_overwrite` 方法实现整体覆盖逻辑

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/tools/executors/editor.ts` L254-261：
  ```typescript
  if (!(await fileExists(filePath))) {
      return createFile(filePath, input.new_text, encoding);  // 文件不存在则创建
  }
  if (input.old_text == null) {
      throw new Error(
          "Parameter `old_text` is required when editing an existing file without `insert_line`",
      );  // 文件存在且无 old_text/insert_line → 抛错
  }
  ```

### 修复步骤建议

**步骤 1**：修改 `agent/tools/editor.py` 的 `_execute` 方法，将末尾的"覆盖分支"改为"错误返回分支"。

保留 `_do_overwrite` 方法本身不删除（保留原函数逻辑），但 `_execute` 不再调用它。在原调用点改为返回错误：

```python
# 分支: 创建模式（文件不存在且无 old_text）
if not exists:
    return self._do_create(path, path_str, new_text)

# 文件已存在但没有提供 old_text 或 insert_line — 对齐 Cline 抛错行为
# 原整体覆盖分支（_do_overwrite）已移除，改为返回错误
# 保留 _do_overwrite 函数定义以便未来需要时复用
return AgentToolResult(
    output={
        "error": "文件已存在，必须提供 old_text（替换模式）或 insert_line（插入模式）",
        "path": path_str,
        "lines_before": lines_before,
    },
    is_error=True,
)
```

**步骤 2**：更新 `description` 属性，去掉"文件不存在且无 old_text 时用 new_text 创建文件"中暗示可整体覆盖的表述，明确文件已存在时必须提供 `old_text` 或 `insert_line`：

```python
@property
def description(self) -> str:
    return (
        "行级文件编辑工具。提供 path(必填)/old_text(可选)/new_text(必填)/insert_line(可选)。"
        "有 insert_line 时在指定行号前插入 new_text（1-based，line_count+1 表示追加到末尾）；"
        "有 old_text 时用 new_text 替换 old_text（old_text 必须唯一匹配）；"
        "文件不存在且无 old_text 时用 new_text 创建文件；"
        "文件已存在且未提供 old_text/insert_line 时返回错误（不对齐 Cline 抛错行为）。"
    )
```

**步骤 3**：保留 `_do_overwrite` 函数定义（不删除），但在函数 docstring 中标注"已废弃，保留以备未来需要显式整体覆盖模式时复用"。

### 验证方法

1. **单元验证**：构造一个已存在的文件 `test.txt`，调用 `editor(path="test.txt", new_text="new content")`（无 `old_text`/`insert_line`），验证：
   - 返回 `is_error=True`
   - 返回 `error` 字段含"文件已存在，必须提供 old_text 或 insert_line"
   - 文件内容**未被修改**（仍为原始内容）
2. **回归验证**：
   - 文件不存在 + 无 `old_text` → 仍走 `_do_create` 创建文件（保持原行为）
   - 文件存在 + 有 `old_text` → 仍走 `_do_replace`（保持原行为）
   - 文件存在 + 有 `insert_line` → 仍走 `_do_insert`（保持原行为）
3. **集成验证**：在 agent e2e 测试中验证 LLM 漏传 `old_text` 时不会误覆盖文件。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — 已 Read `editor.py` L116-169 确认 `_execute` 分支顺序
- 保留原函数逻辑，在其基础上修改 — `_do_overwrite` 函数定义保留，仅 `_execute` 不再调用
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — 错误直接返回，不尝试其他模式
- 此修改是**语义对齐**，会改变现有行为：依赖"漏传 old_text 时整体覆盖"特性的 LLM prompt 需同步更新

---

## 3.2 read_files 行号输出（G1.6）

### 任务背景

来源 Phase G #G1.6，**缺失差距**。

- **Cline 行为**（`file-read.ts` L52-56 默认 `includeLineNumbers: true`，L103-105 计算行号前缀宽度，L161-170 输出格式 `${lineNumber.padStart(maxLineNumWidth)} | ${text}`）：输出 `cat -n` 风格的行号，行号右对齐。
- **我的行为**（`read_files.py` L227-243）：只返回 `content` 纯文本，不含行号。仅返回 `start_line`/`end_line` 元数据。

影响：LLM 读取文件后无法直接看到行号，后续 `insert_line`/`start_line` 调用需自行数行，易出错；与 `editor` 的 `old_text` 定位、`apply_patch` 的 `@@` 上下文匹配形成连锁影响。

### 目标

在 `read_files` 输出 `content` 时按 Cline 格式注入行号前缀：`{行号右对齐} | {行内容}`，行号宽度按最大行号位数计算。保留 `start_line`/`end_line`/`has_more`/`next_start_line` 元数据字段。

### 当前实现位置

- `agent/tools/read_files.py` L210-252：`_read_single_file` 中行范围读取与 content 拼接逻辑
  ```python
  # 行范围读取
  all_lines = text.splitlines()
  total = len(all_lines)
  ...
  start_idx = start_line - 1
  end_idx = end_line if end_line else total
  end_idx = min(end_idx, total)

  selected_lines = all_lines[start_idx:end_idx]
  content = "\n".join(selected_lines)
  ...
  result: dict[str, Any] = {
      "index": index,
      "path": path_str,
      "content": content,
      "lines": total,
      "start_line": start_line,
      "end_line": end_idx,
  }
  ```

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/tools/executors/file-read.ts` L103-105（行号前缀宽度计算）：
  ```typescript
  const lineNumberPrefixChars = includeLineNumbers
      ? String(maxCapturedLineNumber).length + 3
      : 0;
  ```
- `file-read.ts` L161-170（行号格式化输出）：
  ```typescript
  const maxLineNumWidth = String(
      captured[captured.length - 1]?.lineNumber ?? totalLines,
  ).length;
  const body = captured
      .map(({ lineNumber, text }) =>
          includeLineNumbers
              ? `${String(lineNumber).padStart(maxLineNumWidth, " ")} | ${text}`
              : text,
      )
      .join("\n");
  ```

### 修复步骤建议

**步骤 1**：在 `agent/tools/read_files.py` 的 `_read_single_file` 方法中，修改 `content` 拼接逻辑，注入行号前缀。

定位到 L227-228：
```python
selected_lines = all_lines[start_idx:end_idx]
content = "\n".join(selected_lines)
```

改为：
```python
selected_lines = all_lines[start_idx:end_idx]
# 对齐 Cline file-read.ts L161-170：输出 cat -n 风格行号
# 行号右对齐，宽度按最大行号位数计算，格式 "{行号} | {行内容}"
max_line_num = start_line + len(selected_lines) - 1
max_width = len(str(max_line_num)) if selected_lines else 1
lines_with_num = [
    f"{str(start_line + i).rjust(max_width)} | {line}"
    for i, line in enumerate(selected_lines)
]
content = "\n".join(lines_with_num)
```

**步骤 2**：注意字符数截断逻辑（L231-234）的执行顺序 — 行号前缀已计入 `content`，截断时按完整 content 长度计算。保留原截断逻辑不变：
```python
# 字符数截断
truncated = False
if len(content) > self._MAX_CHARS_PER_FILE:
    content = content[:self._MAX_CHARS_PER_FILE]
    truncated = True
```

**步骤 3**：空文件分支（L189-198）保持不变 — 空文件返回 `content: ""`，不注入行号。

**步骤 4**：保留 `start_line`/`end_line`/`lines`/`has_more`/`next_start_line` 元数据字段不变（Cline 也保留这些字段，便于分页）。

### 验证方法

1. **格式验证**：读取一个 10 行文件，验证 content 输出格式：
   ```
     1 | first line
     2 | second line
   ...
   10 | tenth line
   ```
   行号右对齐到 2 位宽度（最大行号 10 的位数）。
2. **行范围验证**：读取 `start_line=5, end_line=8` 的 4 行内容，验证行号显示为 `5`/`6`/`7`/`8`（不是 `1`/`2`/`3`/`4`）。
3. **空文件验证**：读取空文件，验证 `content: ""`，无行号注入。
4. **截断验证**：读取大文件触发截断，验证 `note` 字段提示仍正确。
5. **回归验证**：现有调用 `read_files` 的代码（如 system prompt 构建）不受影响 — content 字段仍是字符串。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — 已 Read `read_files.py` L155-265 确认 `_read_single_file` 完整逻辑
- 保留原函数逻辑，在其基础上修改 — 仅修改 `content` 拼接，其他字段不变
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — 行号注入失败不应降级为无行号输出
- 行号宽度按**实际最大行号**计算（不是文件总行数），避免前导空格过多
- 此修改会改变 content 字段的实际值，依赖纯文本 content 的下游代码需检查（如 RAG 切片）

---

## 3.3 editor diff 生成（G3.6）

### 任务背景

来源 Phase G #G3.6，**缺失差距**。

- **Cline 行为**（`editor.ts` L87-149 `createLineDiff` + L198 `replaceInFile` 返回 `Edited ${filePath}\n${diff}`）：
  - 修剪公共前缀/后缀，只输出变更区域
  - 行预算在 removed/added 间分配（L122-129），避免单侧吃满
  - 输出 ` ```diff ` 代码块格式：`-{lineNum}: {oldLine}` / `+{lineNum}: {newLine}`
- **我的行为**（`editor.py` 各分支）：只返回 `{path, operation, lines_before, lines_after}`，无 diff 内容。

影响：LLM 执行编辑后无法直观看到实际变更，难以自我校验；后续 turn 中 LLM 可能重复编辑或误判编辑结果。

### 目标

在 `editor.py` 实现 `_create_line_diff` 函数（对标 Cline `createLineDiff`），在 `_do_replace`/`_do_insert`/`_do_create` 返回结果中加入 `diff` 字段，让 LLM 能自我校验。

### 当前实现位置

- `agent/tools/editor.py` L227-331：`_do_replace` 方法，返回结果无 diff 字段
- `agent/tools/editor.py` L171-225：`_do_insert` 方法，返回结果无 diff 字段
- `agent/tools/editor.py` L333-351：`_do_create` 方法，返回结果无 diff 字段
- `agent/tools/editor.py` L353-377：`_do_overwrite` 方法（3.1 后已不调用，但仍保留）

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/tools/executors/editor.ts` L87-149 `createLineDiff`：
  ```typescript
  function createLineDiff(oldContent, newContent, maxLines): string {
      const oldLines = oldContent.split(/\r\n|\n/);
      const newLines = newContent.split(/\r\n|\n/);
      // 修剪公共前缀
      let start = 0;
      while (start < oldLines.length && start < newLines.length
             && oldLines[start] === newLines[start]) { start++; }
      // 修剪公共后缀
      let oldEnd = oldLines.length, newEnd = newLines.length;
      while (oldEnd > start && newEnd > start
             && oldLines[oldEnd-1] === newLines[newEnd-1]) { oldEnd--; newEnd--; }
      // 行预算分配
      const removedCount = oldEnd - start, addedCount = newEnd - start;
      let removedBudget = removedCount, addedBudget = addedCount;
      if (removedCount + addedCount > maxLines) {
          removedBudget = Math.min(removedCount,
              Math.max(Math.ceil(maxLines/2), maxLines - addedCount));
          addedBudget = Math.min(addedCount, maxLines - removedBudget);
      }
      // 输出 ```diff 代码块
      const out: string[] = ["```diff"];
      for (let i = start; i < start + removedBudget; i++)
          out.push(`-${i+1}: ${oldLines[i]}`);
      for (let i = start; i < start + addedBudget; i++)
          out.push(`+${i+1}: ${newLines[i]}`);
      if (omittedRemoved > 0 || omittedAdded > 0)
          out.push(`... diff truncated (...) ...`);
      out.push("```");
      return out.join("\n");
  }
  ```
- `editor.ts` L198：`replaceInFile` 返回 `` `Edited ${filePath}\n${diff}` ``

### 修复步骤建议

**步骤 1**：在 `agent/tools/editor.py` 顶部（`_restore_line_ending` 函数之后，`EditorTool` 类之前）新增 `_create_line_diff` 函数：

```python
def _create_line_diff(
    old_content: str,
    new_content: str,
    max_lines: int = 200,
) -> str:
    """生成行级 diff — 对标 Cline editor.ts L87-149 createLineDiff

    修剪公共前后缀，只输出变更区域。行预算在 removed/added 间分配，
    避免单侧吃满 max_lines。输出 ```diff 代码块格式。

    Args:
        old_content: 编辑前的内容
        new_content: 编辑后的内容
        max_lines: diff 最大行数（含 removed + added）

    Returns:
        ```diff 代码块字符串
    """
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    # 修剪公共前缀
    start = 0
    while (start < len(old_lines) and start < len(new_lines)
           and old_lines[start] == new_lines[start]):
        start += 1

    # 修剪公共后缀
    old_end = len(old_lines)
    new_end = len(new_lines)
    while (old_end > start and new_end > start
           and old_lines[old_end - 1] == new_lines[new_end - 1]):
        old_end -= 1
        new_end -= 1

    # 行预算分配 — 对齐 Cline L122-129
    removed_count = old_end - start
    added_count = new_end - start
    removed_budget = removed_count
    added_budget = added_count
    if removed_count + added_count > max_lines:
        removed_budget = min(
            removed_count,
            max(-(-max_lines // 2), max_lines - added_count),  # ceil(max_lines/2)
        )
        added_budget = min(added_count, max_lines - removed_budget)

    # 输出 ```diff 代码块
    out: list[str] = ["```diff"]
    for i in range(start, start + removed_budget):
        out.append(f"-{i + 1}: {old_lines[i]}")
    for i in range(start, start + added_budget):
        out.append(f"+{i + 1}: {new_lines[i]}")

    omitted_removed = removed_count - removed_budget
    omitted_added = added_count - added_budget
    if omitted_removed > 0 or omitted_added > 0:
        out.append(
            f"... diff truncated ({omitted_removed} more removed, "
            f"{omitted_added} more added lines) ..."
        )

    out.append("```")
    return "\n".join(out)
```

**步骤 2**：修改 `_do_replace` 方法（L227-331），在两个返回点（行级匹配成功 L286-294、字符串替换成功 L323-330）的 `output` 字典中加入 `diff` 字段。

行级匹配成功分支（L286-294）：
```python
# 计算变更区域 diff — 对标 Cline editor.ts L198
diff = _create_line_diff(original, content)
return AgentToolResult(
    output={
        "path": path_str,
        "operation": "edit",
        "lines_before": lines_before,
        "lines_after": lines_after,
        "diff": diff,
    },
    metadata={"operation": "edit", "path": path_str},
)
```

字符串替换成功分支（L323-330）类似处理，计算 `diff = _create_line_diff(original, new_content)`。

**步骤 3**：修改 `_do_insert` 方法（L171-225），在返回点（L215-225）加入 `diff` 字段。insert 模式的 diff 是新增行：

```python
# 计算插入后的 diff（对比 original 与插入后的 content）
diff = _create_line_diff(original, content)
return AgentToolResult(
    output={
        "path": path_str,
        "operation": "insert",
        "insert_line": insert_line,
        "lines_before": lines_before,
        "lines_after": lines_after,
        "inserted_lines": len(insert_lines),
        "diff": diff,
    },
    metadata={"operation": "insert", "path": path_str},
)
```

**步骤 4**：修改 `_do_create` 方法（L333-351），加入 `diff` 字段。create 模式 diff 是新增全部内容：

```python
# create 模式：全部为新增行
diff = _create_line_diff("", new_text)
return AgentToolResult(
    output={
        "path": path_str,
        "operation": "create",
        "lines_before": 0,
        "lines_after": lines_after,
        "diff": diff,
    },
    metadata={"operation": "create", "path": path_str},
)
```

**步骤 5**：`_do_overwrite` 方法（L353-377）也加入 `diff` 字段，保持函数完整性（虽已不调用，但保留以备未来复用）。

### 验证方法

1. **diff 格式验证**：对文件做替换编辑，验证返回的 `diff` 字段格式：
   `` ```
   diff
   -3: old line content
   +3: new line content
   ``` ``
2. **公共前后缀修剪验证**：文件 100 行，仅第 50 行变更，验证 diff 只输出第 50 行的 `-`/`+`，不含 1-49 和 51-100 的公共行。
3. **行预算验证**：构造一个替换 300 行的场景，验证 diff 输出不超过 `max_lines=200`，且 removed/added 各占约 100 行，末尾有 `... diff truncated ...` 提示。
4. **回归验证**：`is_error=True` 的错误返回路径（old_text 未找到/多次匹配）不加 diff 字段，保持原错误信息。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — 已 Read `editor.py` 完整文件确认各返回点位置
- 保留原函数逻辑，在其基础上修改 — `_do_replace`/`_do_insert`/`_do_create` 原返回字段全部保留，仅新增 `diff` 字段
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — diff 生成失败不应影响编辑操作本身（编辑已写盘成功）
- `max_lines=200` 与 Cline 默认值对齐（`editor.ts` L34 `maxDiffLines?: number @default 200`）
- diff 中行号是 1-based（Cline L133/L136 `i+1`），与 `insert_line` 一致

---

## 3.4 apply_patch 部分成功回滚完善（G4.4 后续）

### 任务背景

来源 Phase G #G4.4 后续，**P0 级差距的后续完善**。

- **Cline 行为**（`apply-patch.ts` L333-353 `computePatchChanges` + L275-325 `applyChanges`）：
  - **两阶段提交**：先 `computePatchChanges` 解析所有 chunk 并计算变更（不写盘），若 `patch.warnings.length > 0` 抛 `DiffError` 不写任何文件；再 `applyChanges` 实际写盘。
  - **all-or-nothing**：任一 chunk 上下文匹配失败，整个 patch 拒绝应用，文件保持原状。
- **我的行为**（`apply_patch.py` L111-142 `_execute` + L220-253 `_apply_block`）：
  - 每个 block 立即应用并写盘（`_apply_block` → `_apply_update`/`_apply_add`/`_apply_delete`）。
  - `_apply_update` 在某段 `-` 行找不到时返回 `{success: False, error: ...}`，但**已应用的前续块不会回滚**。

stage_1 已建立 apply_patch 原子性基础（两阶段提交骨架），本阶段是**后续完善**：补齐失败时的回滚逻辑、warning 收集、错误信息格式化。

### 目标

在 stage_1 两阶段提交骨架基础上：
1. 失败时收集所有 warning（不止首个失败），返回完整错误信息
2. 错误信息格式对标 Cline `formatSkippedHunkFailure`（含 hunk 编号、path、message、context）
3. 确保阶段 1（计算变更）完全不写盘，阶段 2（写盘）全部成功后才提交

### 当前实现位置

- `agent/tools/apply_patch.py` L111-142 `_execute`：循环 `_apply_block` 立即写盘
- `agent/tools/apply_patch.py` L220-253 `_apply_block`：分发到 `_apply_update`/`_apply_add`/`_apply_delete`
- `agent/tools/apply_patch.py` L255-363 `_apply_update`：行级替换，立即 `path.write_text`
- `agent/tools/apply_patch.py` L365-396 `_replace_segment`：精确 + fuzzy 匹配
- `agent/tools/apply_patch.py` L398-429 `_apply_add`：新建文件，立即 `path.write_text`
- `agent/tools/apply_patch.py` L431-446 `_apply_delete`：删除文件，立即 `path.unlink`

注：若 stage_1 已改造为两阶段提交，本阶段在 stage_1 基础上完善。若 stage_1 未完成，本阶段需先实现两阶段提交骨架。

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/tools/executors/apply-patch.ts` L333-353 `computePatchChanges`：
  ```typescript
  export async function computePatchChanges(patchText, cwd, options) {
      const normalizedInput = normalizePatchInput(patchText);
      const currentFiles = await loadFiles(normalizedInput.lines, cwd, ...);
      const parser = new PatchParser(normalizedInput.lines, currentFiles);
      const { patch, fuzz } = parser.parse();
      if (patch.warnings && patch.warnings.length > 0) {
          throw new DiffError(formatSkippedHunkFailure(patch.warnings));
      }
      return { changes: patchToChanges(patch, currentFiles), fuzz };
  }
  ```
- `apply-patch.ts` L256-273 `formatSkippedHunkFailure`：
  ```typescript
  function formatSkippedHunkFailure(warnings: PatchWarning[]): string {
      const lines = [`Patch could not be applied because ${warnings.length} hunk(s) did not match...`];
      for (const warning of warnings) {
          const hunkNumber = warning.chunkIndex === undefined
              ? "unknown" : String(warning.chunkIndex + 1);
          lines.push(`${warning.path}: hunk ${hunkNumber}: ${warning.message}`);
          if (warning.context) { lines.push(`Context:\n${warning.context}`); }
      }
      return lines.join("\n");
  }
  ```
- `apply-patch.ts` L275-325 `applyChanges`：实际写盘（DELETE/ADD/UPDATE 含 move 语义）

### 修复步骤建议

**步骤 1**：先 Read `agent/tools/apply_patch.py` 当前实现，确认 stage_1 是否已完成两阶段提交改造。

若 stage_1 已完成：跳到步骤 3。若未完成：执行步骤 2。

**步骤 2**：将 `_execute` 改造为两阶段提交骨架（若 stage_1 未做）：

```python
async def _execute(self, input, context):
    patch_text = input["input"]
    blocks = self._parse_patch(patch_text)
    if not blocks:
        return AgentToolResult(
            output={"error": "未解析到有效的补丁块"},
            is_error=True,
        )

    # 阶段 1: 计算所有变更（不写盘）— 对标 Cline computePatchChanges
    warnings: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for block_idx, block in enumerate(blocks):
        change = self._compute_change(block, block_idx, warnings)
        if change is not None:
            changes.append(change)

    # 阶段 1 失败：有 warning 则拒绝应用 — 对标 Cline L348-350
    if warnings:
        error_msg = self._format_skipped_hunk_failure(warnings)
        return AgentToolResult(
            output={"error": error_msg, "warnings": warnings},
            is_error=True,
        )

    # 阶段 2: 全部成功后写盘 — 对标 Cline applyChanges
    results = []
    for change in changes:
        result_item = self._apply_change(change)
        results.append(result_item)

    succeeded = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success"))
    return AgentToolResult(
        output={"results": results},
        metadata={"total_files": len(results), "succeeded": succeeded, "failed": failed},
    )
```

**步骤 3**：新增 `_compute_change` 方法，对标 Cline `patchToChanges` + `applyChunks` 中的"计算变更但不写盘"逻辑：

```python
def _compute_change(
    self,
    block: dict[str, Any],
    block_idx: int,
    warnings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """计算单个 block 的变更（不写盘）— 对标 Cline patchToChanges

    Args:
        block: {operation, path, lines}
        block_idx: block 索引（用于 warning 报告）
        warnings: 收集所有 warning（不止首个失败）

    Returns:
        变更描述 dict，含 operation/path/old_content/new_content；
        若 block 解析失败但仍需记录 warning，返回 None
    """
    operation = block["operation"]
    path_str = block["path"]
    path = Path(path_str)

    if operation == "update":
        return self._compute_update_change(path, path_str, block["lines"], block_idx, warnings)
    elif operation == "add":
        return self._compute_add_change(path, path_str, block["lines"])
    elif operation == "delete":
        return self._compute_delete_change(path, path_str)
    return None
```

**步骤 4**：新增 `_compute_update_change` 方法，对标 Cline `applyChunks`（计算 newContent 但不写盘）。从现有 `_apply_update` 提取计算逻辑，移除 `path.write_text` 调用。匹配失败时收集 warning（不立即返回错误）：

```python
def _compute_update_change(
    self, path, path_str, lines, block_idx, warnings
) -> dict[str, Any] | None:
    """计算 update 变更（不写盘）— 对标 Cline applyChunks"""
    if not path.exists():
        warnings.append({
            "path": path_str,
            "chunk_index": block_idx,
            "message": f"文件不存在: {path_str}",
            "context": "",
        })
        return None

    try:
        raw_original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        warnings.append({
            "path": path_str,
            "chunk_index": block_idx,
            "message": f"无法读取二进制文件: {path_str}",
            "context": "",
        })
        return None

    # 复用 _apply_update 的匹配与替换逻辑，但不写盘
    # ... 提取 result_lines 计算逻辑 ...
    # 若 _replace_segment 返回 None，收集 warning 而非立即返回错误
    # ... 计算最终 content ...

    return {
        "operation": "update",
        "path": path_str,
        "old_content": raw_original,
        "new_content": content,
        "lines_before": len(original_lines),
        "lines_after": len(result_lines),
    }
```

**步骤 5**：新增 `_format_skipped_hunk_failure` 方法，对标 Cline `formatSkippedHunkFailure`：

```python
def _format_skipped_hunk_failure(
    self, warnings: list[dict[str, Any]]
) -> str:
    """格式化 warning 列表为错误信息 — 对标 Cline formatSkippedHunkFailure

    输出格式:
        Patch could not be applied because N hunk(s) did not match...
        path1: hunk 1: message1
        Context:
        ...
        path2: hunk 2: message2
    """
    count = len(warnings)
    hunk_text = "hunk" if count == 1 else "hunks"
    lines = [
        f"Patch could not be applied because {count} {hunk_text} "
        f"did not match the current file content."
    ]
    for warning in warnings:
        chunk_idx = warning.get("chunk_index")
        hunk_number = "unknown" if chunk_idx is None else str(chunk_idx + 1)
        lines.append(
            f"{warning['path']}: hunk {hunk_number}: {warning['message']}"
        )
        context = warning.get("context", "")
        if context:
            lines.append(f"Context:\n{context}")
    return "\n".join(lines)
```

**步骤 6**：新增 `_apply_change` 方法，对标 Cline `applyChanges`（实际写盘）：

```python
def _apply_change(self, change: dict[str, Any]) -> dict[str, Any]:
    """应用变更到磁盘 — 对标 Cline applyChanges

    Args:
        change: {operation, path, old_content/new_content, ...}
    """
    operation = change["operation"]
    path_str = change["path"]
    path = Path(path_str)

    try:
        if operation == "update":
            new_content = change["new_content"]
            path.write_text(new_content, encoding="utf-8")
            return {
                "path": path_str,
                "operation": "update",
                "success": True,
                "lines_before": change.get("lines_before", 0),
                "lines_after": change.get("lines_after", 0),
            }
        elif operation == "add":
            new_content = change["new_content"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_content, encoding="utf-8")
            return {"path": path_str, "operation": "add", "success": True}
        elif operation == "delete":
            path.unlink()
            return {"path": path_str, "operation": "delete", "success": True}
        return {"path": path_str, "operation": operation, "success": False,
                "error": f"未知操作: {operation}"}
    except Exception as e:
        return {"path": path_str, "operation": operation, "success": False,
                "error": str(e)}
```

**步骤 7**：保留 `_apply_block`/`_apply_update`/`_apply_add`/`_apply_delete` 原函数定义（不删除），在 docstring 标注"已废弃，保留以备单 block 直接应用场景复用"。

### 验证方法

1. **原子性验证**：构造 3 文件 patch，第 2 个文件匹配失败，验证：
   - 文件 1 **未被修改**（保持原状）
   - 文件 3 **未被修改**（保持原状）
   - 返回 `is_error=True`，错误信息含"hunk ... did not match"
2. **warning 收集验证**：构造 3 文件 patch，第 1 和第 3 个文件都匹配失败，验证错误信息含 2 条 hunk warning（不止首个）。
3. **错误信息格式验证**：验证错误信息含 `path: hunk N: message` 格式，对标 Cline `formatSkippedHunkFailure`。
4. **成功路径验证**：3 文件 patch 全部匹配成功，验证 3 文件全部写盘，返回 `succeeded=3, failed=0`。
5. **回归验证**：`_apply_update` 的 fuzzy 匹配逻辑（`_replace_segment`）保持不变，仅调用时机从"立即写盘"改为"计算变更"。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — **必须先 Read `apply_patch.py` 确认 stage_1 是否已完成两阶段提交改造**
- 保留原函数逻辑，在其基础上修改 — `_apply_update`/`_apply_add`/`_apply_delete` 的匹配/计算逻辑保留，仅剥离写盘调用
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — 阶段 1 失败直接返回错误，不尝试部分应用
- 注意：阶段 1 中已读取的文件内容在阶段 2 写盘前可能被外部修改，可通过文件锁或 mtime 校验缓解（本阶段不强制实现）
- `warning.chunkIndex` 是 0-based，输出时 +1 转 1-based（对标 Cline L263 `chunkIndex + 1`）

---

## 3.5 技能系统 frontmatter BOM/CRLF 兼容（I12）

### 任务背景

来源 Phase I #I12，**Windows 环境必须修复的差距**。

- **Cline 行为**（`user-instruction-config-loader.ts` L194-225 `parseMarkdownFrontmatter`）：
  - `stripUtf8Bom(content)` 剥离 UTF-8 BOM（修复 cline/cline#12151）
  - 正则 `/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/` 支持 CRLF
  - 严格 YAML 解析，类型检查（`parseStringField`/`parseBooleanField`）
  - 解析失败抛错（含 `parseError`）
- **我的行为**（`loader.py` L334-384 `_parse_frontmatter`）：
  - 不处理 BOM（`content.startswith("---")` 对 `\uFEFF---` 开头返回 False）
  - 正则 `r"^---\n(.*?)\n---"` 仅支持 LF，不支持 CRLF
  - PyYAML 失败时静默 fallback 到简单解析
  - 无类型检查

影响：Windows Notepad 保存的 "UTF-8 with BOM" 文件，我的 `content.startswith("---")` 会失败（实际开头是 `\uFEFF---`），整个技能被静默跳过；CRLF 行尾的 SKILL.md 也会因正则不匹配被跳过。

### 目标

在 `_parse_frontmatter` 中：
1. 剥离 UTF-8 BOM
2. 正则支持 CRLF（`\r?\n`）
3. `_strip_frontmatter` 同步支持 BOM/CRLF

### 当前实现位置

- `agent/skills/loader.py` L334-384 `_parse_frontmatter`：
  ```python
  def _parse_frontmatter(self, content: str) -> dict[str, Any] | None:
      if not content.startswith("---"):
          return None
      match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
      if not match:
          return None
      raw = match.group(1)
      # PyYAML + fallback 简单解析
      ...
  ```
- `agent/skills/loader.py` L386-392 `_strip_frontmatter`：
  ```python
  def _strip_frontmatter(self, content: str) -> str:
      if content.startswith("---"):
          match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
          if match:
              return content[match.end():].strip()
      return content
  ```

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L194-225 `parseMarkdownFrontmatter`：
  ```typescript
  // Strip a leading UTF-8 BOM (e.g. added by Windows Notepad's "UTF-8 with BOM" encoding)
  const normalizedContent = stripUtf8Bom(content);
  const frontmatterRegex = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;
  const match = normalizedContent.match(frontmatterRegex);
  if (!match) {
      return { data: {}, body: normalizedContent, hadFrontmatter: false };
  }
  const [, yamlContent, body] = match;
  try {
      const parsed = YAML.parse(yamlContent);
      ...
  } catch (error) {
      return { data: {}, body: normalizedContent, hadFrontmatter: true, parseError: message };
  }
  ```

### 修复步骤建议

**步骤 1**：在 `agent/skills/loader.py` 顶部（`import re` 之后）新增 BOM 剥离辅助函数：

```python
def _strip_utf8_bom(content: str) -> str:
    """剥离 UTF-8 BOM — 对标 Cline stripUtf8Bom

    Windows Notepad 保存的 "UTF-8 with BOM" 文件开头是 \\uFEFF，
    会导致 frontmatter 正则不匹配（见 cline/cline#12151）。
    """
    if content.startswith("\ufeff"):
        return content[1:]
    return content
```

**步骤 2**：修改 `_parse_frontmatter` 方法（L334-384），在开头剥离 BOM 并修正正则支持 CRLF：

```python
def _parse_frontmatter(self, content: str) -> dict[str, Any] | None:
    """解析 YAML frontmatter — 对标 Cline parseMarkdownFrontmatter

    优先使用 PyYAML，失败时用简单解析。
    对齐 Cline: BOM 剥离 + \\r?\\n 支持 CRLF。
    """
    # 对齐 Cline L200: 剥离 UTF-8 BOM
    content = _strip_utf8_bom(content)

    if not content.startswith("---"):
        return None

    # 对齐 Cline L202: 正则支持 \r\n (CRLF) 和 \n (LF)
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", content, re.DOTALL)
    if not match:
        return None

    raw = match.group(1)

    # 优先使用 PyYAML
    try:
        import yaml
        result = yaml.safe_load(raw)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Fallback: 简单 YAML 解析 — 保留原有逻辑
    metadata: dict[str, Any] = {}
    current_key: str | None = None

    # 对齐 CRLF: split 时同时处理 \r\n 和 \n
    for line in raw.split("\n"):
        stripped = line.rstrip("\r").strip()
        # 列表项
        if stripped.startswith("- ") and current_key:
            item = stripped[2:].strip()
            if isinstance(metadata.get(current_key), list):
                metadata[current_key].append(item)
            else:
                metadata[current_key] = [item]
            continue

        # 键值对
        if ":" in line and not stripped.startswith("-"):
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if value:
                metadata[key] = value
            else:
                metadata[key] = []
                current_key = key

    return metadata
```

**步骤 3**：同步修改 `_strip_frontmatter` 方法（L386-392），支持 BOM + CRLF：

```python
def _strip_frontmatter(self, content: str) -> str:
    """去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()

    对齐 Cline: BOM 剥离 + \\r?\\n 支持 CRLF。
    """
    # 对齐 Cline: 剥离 BOM
    content = _strip_utf8_bom(content)
    if content.startswith("---"):
        # 对齐 CRLF: 正则支持 \r\n
        match = re.match(r"^---\r?\n.*?\r?\n---\r?\n?", content, re.DOTALL)
        if match:
            return content[match.end():].strip()
    return content
```

**步骤 4**：`_parse_skill_file` 方法（L197-268）调用 `_parse_frontmatter` 时无需修改 — BOM 剥离已在 `_parse_frontmatter` 内部完成。但需确认 `load_instructions` 调用 `_strip_frontmatter` 的路径也正确处理 BOM。

### 验证方法

1. **BOM 验证**：构造一个 UTF-8 with BOM 的 SKILL.md 文件（开头 `\uFEFF---`），验证：
   - `_parse_frontmatter` 能正确解析 frontmatter（不再返回 None）
   - `_strip_frontmatter` 能正确剥离 frontmatter 返回正文
   - `list_skills()` 能发现该技能（不再静默跳过）
2. **CRLF 验证**：构造一个 CRLF 行尾的 SKILL.md 文件（`\r\n`），验证：
   - `_parse_frontmatter` 正则匹配成功
   - `_strip_frontmatter` 正则匹配成功
3. **LF 回归验证**：构造一个 LF 行尾的 SKILL.md 文件（原格式），验证行为不变。
4. **Fallback 解析验证**：构造一个 PyYAML 解析失败但简单解析可处理的 frontmatter，验证 fallback 路径在 BOM/CRLF 下也工作。
5. **实际技能验证**：在 `agent_config/skills/` 下用一个 BOM + CRLF 的 SKILL.md 替换现有技能，验证 agent 能正确加载。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — 已 Read `loader.py` L334-392 确认 `_parse_frontmatter`/`_strip_frontmatter` 完整逻辑
- 保留原函数逻辑，在其基础上修改 — PyYAML + fallback 简单解析逻辑全部保留，仅增加 BOM 剥离和 `\r?\n` 支持
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — BOM 剥离和 CRLF 支持是必要兼容，不是降级
- 注意：`_strip_utf8_bom` 只剥离**开头**的 BOM，不处理文件中间的 BOM（Cline 行为一致）
- 此修改不影响 `disabled`/`always`/`keywords` 等字段的解析逻辑（这些在 `_parse_skill_file` 中处理，调用 `_parse_frontmatter` 后获取 dict）

---

## 3.6 技能系统 runningSkills key 规范化（I6）

### 任务背景

来源 Phase I #I6，**并发去重失效差距**。

- **Cline 行为**（`user-instruction-plugin.ts` L179/L188-205）：`runningSkills` Set 用 `id`（`normalizeSkillToken(name)` 后的值）作 key。`normalizeSkillToken` = `trim().replace(/^\/+/, "").toLowerCase()`，因此 `"PDF"`、`"pdf"`、`"/pdf"` 都映射到同一个 key `"pdf"`。
- **我的行为**（`skill_tool.py` L62/L147-191）：`_running_skills` Set 用原始 `skill_name`（仅 `.strip()`，未小写化、未去前导斜杠）作 key。

影响：同一技能以不同大小写/前导斜杠形式并发调用时，去重失效，会重复注入指令。实际场景影响概率低，但与 Cline 行为不等价。

### 目标

将 `_running_skills` 的去重 key 改为规范化形式：复用 `agent.skills.registry._normalize_skill_token`（已存在，L33-38），与 Cline `normalizeSkillToken` 行为一致。

### 当前实现位置

- `agent/skills/skill_tool.py` L62：`self._running_skills: set[str] = set()` 初始化
- `agent/skills/skill_tool.py` L147-151：去重检查
  ```python
  if skill_name in self._running_skills:
      return AgentToolResult(
          output=f'Skill "{skill_name}" is already running.',
          is_error=False,
      )
  ```
- `agent/skills/skill_tool.py` L154：标记运行中 `self._running_skills.add(skill_name)`
- `agent/skills/skill_tool.py` L191：释放 `self._running_skills.discard(skill_name)`
- `agent/skills/registry.py` L33-38：`_normalize_skill_token` 函数（已存在，可复用）

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L35-37 `normalizeSkillToken`：
  ```typescript
  function normalizeSkillToken(token: string): string {
      return token.trim().replace(/^\/+/, "").toLowerCase();
  }
  ```
- `user-instruction-plugin.ts` L179/L188-205 `runningSkills` 用 `id`（normalized）作 key：
  ```typescript
  const runningSkills = new Set<string>();
  // ...
  const { id, skill } = resolved;  // id 来自 resolveSkillRecord，是 normalizeSkillToken(name)
  if (runningSkills.has(id)) { return `Skill "${skill.name}" is already running.`; }
  runningSkills.add(id);
  try { ... } finally { runningSkills.delete(id); }
  ```

### 修复步骤建议

**步骤 1**：在 `agent/skills/skill_tool.py` 顶部导入 `_normalize_skill_token`：

```python
from agent.skills.registry import SkillRegistry, _normalize_skill_token
```

**步骤 2**：修改 `_execute` 方法中的去重逻辑（L147-151），将 key 改为规范化形式：

```python
# Phase 31.1: 检查技能是否正在运行 — 对标 Cline L188-190
# `if (runningSkills.has(id)) return 'Skill "${name}" is already running.'`
# 对齐 Cline I6: 去重 key 改用 _normalize_skill_token(skill_name)
# 确保 "PDF"/"pdf"/"/pdf" 映射到同一 key "pdf"
skill_id = _normalize_skill_token(skill_name)
if skill_id in self._running_skills:
    return AgentToolResult(
        output=f'Skill "{skill_name}" is already running.',
        is_error=False,  # Cline 返回的是提示文本，不是 error
    )
```

**步骤 3**：修改标记运行中逻辑（L154），用 `skill_id` 替代 `skill_name`：

```python
# Phase 31.1: 标记技能为运行中 — 对标 Cline L192 `runningSkills.add(id)`
# 对齐 Cline I6: 用规范化 id 作 key
self._running_skills.add(skill_id)
```

**步骤 4**：修改 finally 释放逻辑（L191），用 `skill_id` 替代 `skill_name`：

```python
finally:
    # Phase 31.1: 完成后释放（含异常路径）— 对标 Cline L203-205
    # `finally { runningSkills.delete(id); }`
    # 对齐 Cline I6: 释放规范化 id
    self._running_skills.discard(skill_id)
```

**步骤 5**：保留 `skill_name` 用于错误提示和 XML 返回（`<command-name>{skill_name}</command-name>`），仅去重 key 改用 `skill_id`。

### 验证方法

1. **大小写去重验证**：构造同一技能 `"pdf"`，连续调用 `skills(skill="PDF")` 和 `skills(skill="pdf")`，验证第二次返回 `"Skill \"PDF\" is already running."`（去重生效）。
2. **前导斜杠去重验证**：连续调用 `skills(skill="/pdf")` 和 `skills(skill="pdf")`，验证第二次返回 already running。
3. **释放后可重入验证**：第一次调用完成（finally 释放）后，第二次调用应正常加载指令，不报 already running。
4. **异常路径释放验证**：构造一个技能加载失败的场景（如 SKILL.md 损坏），验证 finally 仍释放 `_running_skills`，后续可重入。
5. **回归验证**：现有技能调用流程不变，`<command-name>` 仍使用原始 `skill_name`（不是 `skill_id`）。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — 已 Read `skill_tool.py` L52-191 确认 `_running_skills` 使用位置
- 保留原函数逻辑，在其基础上修改 — 仅改 key 计算，其他流程不变
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — 规范化失败（如 `skill_name` 为空）已在前面 `if not skill_name` 检查拦截
- 注意：`_normalize_skill_token` 是 `registry.py` 的模块级函数（非 SkillRegistry 方法），导入时用 `from agent.skills.registry import _normalize_skill_token`
- 此修改不影响 `has_skill`/`get_skill` 的查询逻辑（这些走 `SkillRegistry`，已用原始 name 查询）

---

## 3.7 技能系统 allowedSkillNames 多形式匹配（I8）

### 任务背景

来源 Phase I #I8，**白名单匹配形式单一差距**。

- **Cline 行为**（`user-instruction-plugin.ts` L51-73 `isSkillAllowed`）：检查 4 种形式 — 完整 id、完整 name、去 namespace 的 bare id、去 namespace 的 bare name。支持 `ms-office-suite:pdf` 这类 namespaced skill，白名单写 `pdf` 即可匹配。
- **我的行为**（`registry.py` L57-68 `_is_skill_allowed`）：仅检查 1 种形式 — 规范化后的 name。不支持 namespace 前缀，无 bare name 提取。

影响：若未来引入 namespaced skill（如 `plugin-a:pdf`），白名单写 `pdf` 无法匹配；多 agent 场景下白名单粒度不如 Cline 灵活。

### 目标

扩展 `_is_skill_allowed` 检查 4 种形式（对标 Cline `isSkillAllowed`）：
1. 完整 normalized name
2. bare name（去 `:` namespace 前缀）

注：当前系统无 namespaced skill，`id` 与 `name` 相同，因此 4 形式简化为 2 形式（normalized + bare）。但为未来 namespace 扩展预留完整 4 形式检查。

### 当前实现位置

- `agent/skills/registry.py` L33-38 `_normalize_skill_token`：
  ```python
  def _normalize_skill_token(token: str) -> str:
      return (token or "").strip().lstrip("/").lower()
  ```
- `agent/skills/registry.py` L57-68 `_is_skill_allowed`：
  ```python
  def _is_skill_allowed(skill_name: str, allowed_skills: set[str] | None) -> bool:
      if allowed_skills is None:
          return True
      return _normalize_skill_token(skill_name) in allowed_skills
  ```
- `agent/skills/registry.py` L90-100 `SkillRegistry.__init__`：白名单初始化
- `agent/skills/registry.py` L112-130 `list_skills`：调用 `_is_skill_allowed`
- `agent/skills/registry.py` L132-146 `get_skill`：调用 `_is_skill_allowed`

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L51-73 `isSkillAllowed`：
  ```typescript
  function isSkillAllowed(skillId, skillName, allowedSkills): boolean {
      if (!allowedSkills) return true;
      const normalizedId = normalizeSkillToken(skillId);
      const normalizedName = normalizeSkillToken(skillName);
      const bareId = normalizedId.includes(":")
          ? (normalizedId.split(":").at(-1) ?? normalizedId)
          : normalizedId;
      const bareName = normalizedName.includes(":")
          ? (normalizedName.split(":").at(-1) ?? normalizedName)
          : normalizedName;
      return (
          allowedSkills.has(normalizedId) ||
          allowedSkills.has(normalizedName) ||
          allowedSkills.has(bareId) ||
          allowedSkills.has(bareName)
      );
  }
  ```

### 修复步骤建议

**步骤 1**：修改 `agent/skills/registry.py` 的 `_is_skill_allowed` 函数（L57-68），扩展为 4 形式检查：

```python
def _is_skill_allowed(
    skill_name: str,
    allowed_skills: set[str] | None,
) -> bool:
    """检查技能是否在白名单中 — 对标 Cline isSkillAllowed

    allowed_skills 为 None 时全部允许。
    否则检查 4 种形式（对齐 Cline L51-73）:
        1. 完整 normalized name
        2. bare name（去 ":" namespace 前缀）

    注: 当前系统无 namespaced skill，skill_id 与 skill_name 相同，
        4 形式简化为 2 形式（normalized + bare）。
        为未来 namespace 扩展预留完整 4 形式检查。
    """
    if allowed_skills is None:
        return True

    normalized = _normalize_skill_token(skill_name)
    # bare name: 去 ":" namespace 前缀 — 对齐 Cline L61-66
    bare = normalized.split(":")[-1] if ":" in normalized else normalized

    return normalized in allowed_skills or bare in allowed_skills
```

**步骤 2**：可选增强 — 新增 `_is_skill_allowed_full` 函数，接受 `skill_id` 和 `skill_name` 两个参数，完整对标 Cline 4 形式检查。当前系统 `skill_id == skill_name`，调用方无需修改：

```python
def _is_skill_allowed_full(
    skill_id: str,
    skill_name: str,
    allowed_skills: set[str] | None,
) -> bool:
    """完整 4 形式白名单检查 — 对标 Cline isSkillAllowed(skillId, skillName, ...)

    当前系统 skill_id 与 skill_name 相同，等价于 _is_skill_allowed。
    未来引入 namespaced skill 后，skill_id 可能含 ":" 前缀（如 "plugin-a:pdf"），
    此时需用本函数检查 4 形式。
    """
    if allowed_skills is None:
        return True

    normalized_id = _normalize_skill_token(skill_id)
    normalized_name = _normalize_skill_token(skill_name)
    bare_id = normalized_id.split(":")[-1] if ":" in normalized_id else normalized_id
    bare_name = normalized_name.split(":")[-1] if ":" in normalized_name else normalized_name

    return (
        normalized_id in allowed_skills
        or normalized_name in allowed_skills
        or bare_id in allowed_skills
        or bare_name in allowed_skills
    )
```

**步骤 3**：`list_skills`（L112-130）和 `get_skill`（L132-146）的调用无需修改 — 仍调用 `_is_skill_allowed(skill.name, ...)`，但内部行为已扩展为 4 形式（实际 2 形式，因 `skill.name` 不含 `:`）。

**步骤 4**：`_to_allowed_skill_set`（L41-54）无需修改 — 白名单集合元素已在初始化时 `_normalize_skill_token` 规范化。

### 验证方法

1. **基本白名单验证**：`allowed_skill_names=["pdf", "write-report"]`，验证 `pdf` 和 `write-report` 技能可访问，其他技能被过滤。
2. **bare name 匹配验证**（未来场景模拟）：构造一个 `skill_name="plugin-a:pdf"` 的技能，`allowed_skill_names=["pdf"]`，验证：
   - `_is_skill_allowed("plugin-a:pdf", {"pdf"})` 返回 `True`（bare name 匹配）
   - `_is_skill_allowed("plugin-a:other", {"pdf"})` 返回 `False`
3. **大小写规范化验证**：`allowed_skill_names=["PDF"]`，验证 `_is_skill_allowed("pdf", ...)` 返回 `True`（白名单初始化时已 lowercase）。
4. **前导斜杠验证**：`_is_skill_allowed("/pdf", {"pdf"})` 返回 `True`（`_normalize_skill_token` 已 lstrip `/`）。
5. **None 白名单验证**：`allowed_skill_names=None` 或 `[]`，验证全部技能允许（`_to_allowed_skill_set` 返回 None）。
6. **回归验证**：现有 `agent_config/skills/` 下技能名均不含 `:`，行为应与修改前一致。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — 已 Read `registry.py` L33-68 确认 `_normalize_skill_token`/`_is_skill_allowed` 完整逻辑
- 保留原函数逻辑，在其基础上修改 — `_is_skill_allowed` 原签名保留，仅扩展内部检查逻辑
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — 4 形式检查任一命中即返回 True，不是降级
- 注意：`_normalize_skill_token` 当前是 `lstrip("/")` 去前导斜杠，Cline 是 `replace(/^\/+/, "")` 去多个前导斜杠 — Python `lstrip("/")` 也会去多个，行为一致
- 此修改为未来 namespace skill 预留，当前系统无 namespaced skill，不会改变现有行为

---

## 3.8 MCP per-tool policies（Q8）

### 任务背景

来源 Phase Q #Q8，**P1 级真缺口（唯一）**。

- **Cline 行为**（`policies.ts` + `shared/llms/tools.ts`）：
  - `ToolPolicy` 类型：`{enabled?: boolean (default true), autoApprove?: boolean (default true)}`
  - `createDisabledMcpToolPolicy(serverName, toolName)`：用 `nameTransform` 计算展开后的工具名，返回 `{[name]: {enabled: false}}`
  - runtime 在工具执行前查询策略：`enabled: false` 跳过执行，`autoApprove: false` 触发 `requestToolApproval` 回调
- **我的行为**：
  - 无 per-tool policy 概念
  - 所有 MCP 工具通过单一 `use_mcp_tool` 调用，`read_only=True`，runtime 自动批准
  - 无机制禁用某个具体 MCP 工具（server_name + tool_name 组合）
  - 无机制要求用户批准某个 MCP 工具调用

影响：无法对敏感 MCP 工具（如执行交易的 MCP 工具）强制人工审批，存在安全风险；量化场景下若 MCP 工具涉及下单/资金操作，缺少 `auto_approve=false` 机制是真实安全缺口。

### 目标

1. 在 `agent_config/mcp_servers.yaml` 增加 `tool_policies` 段，支持 per-tool `enabled`/`auto_approve` 配置
2. 在 `agent/mcp/registry.py` 加载 `tool_policies` 配置，提供 `get_tool_policy(server_name, tool_name)` 查询接口
3. 在 `agent/tools/mcp.py` 的 `UseMcpToolTool._execute` 调用 `registry.call_tool` 前查询策略：
   - `enabled: false` 返回错误
   - `auto_approve: false` 设置 `requires_approval=True`（对接现有 approval 机制）

注：本阶段先实现 `enabled: false` 禁用机制（短期目标），`auto_approve: false` 审批机制对接留待中期。

### 当前实现位置

- `agent_config/mcp_servers.yaml` L38：`servers: []`（空列表，仅示例注释）
- `agent/mcp/registry.py` L41-65 `MCPServerConfig` dataclass：无 tool_policies 字段
- `agent/mcp/registry.py` L116-180 `load_config`：仅加载 servers，无 tool_policies 加载
- `agent/mcp/registry.py` L272-310 `call_tool`：无策略查询
- `agent/tools/mcp.py`：`UseMcpToolTool` 调用 `registry.call_tool`（需 Read 确认具体行号）

### 目标源代码位置

- `third_party/cline/sdk/packages/core/src/extensions/mcp/policies.ts` L17-30 `createDisabledMcpToolPolicy`：
  ```typescript
  export function createDisabledMcpToolPolicy(options): Record<string, ToolPolicy> {
      const nameTransform = options.nameTransform ?? defaultMcpToolNameTransform;
      const name = nameTransform({ serverName: options.serverName, toolName: options.toolName });
      return { [name]: { enabled: false } };
  }
  ```
- `shared/llms/tools.ts` L7-18 `ToolPolicy` 类型：
  ```typescript
  export interface ToolPolicy {
      enabled?: boolean;       // default true
      autoApprove?: boolean;   // default true
  }
  ```

### 修复步骤建议

**步骤 1**：在 `agent_config/mcp_servers.yaml` 顶部注释中补充 `tool_policies` 段说明，并在 `servers: []` 之后增加 `tool_policies: []` 段（空列表）：

```yaml
# tool_policies: MCP 工具粒度策略 — 对标 Cline policies.ts ToolPolicy
#   - server: 服务器名（必填）
#     tool: 工具名（必填）
#     enabled: true | false  （可选，默认 true；false 表示完全禁用该工具）
#     auto_approve: true | false  （可选，默认 true；false 表示调用前需用户批准）
#
# 示例:
#   tool_policies:
#     - server: trading
#       tool: place_order
#       auto_approve: false  # 调用前需用户确认
#     - server: filesystem
#       tool: delete_file
#       enabled: false        # 完全禁用

servers: []
tool_policies: []
```

**步骤 2**：在 `agent/mcp/registry.py` 顶部新增 `MCPToolPolicy` dataclass：

```python
@dataclass
class MCPToolPolicy:
    """MCP 工具策略 — 对标 Cline shared/llms/tools.ts ToolPolicy

    Attributes:
        server_name: 服务器名
        tool_name: 工具名
        enabled: 是否启用（默认 True；False 表示完全禁用）
        auto_approve: 是否自动批准（默认 True；False 表示需用户批准）
    """
    server_name: str
    tool_name: str
    enabled: bool = True
    auto_approve: bool = True
```

**步骤 3**：在 `MCPRegistry.__init__` 中新增 `_tool_policies` 字段：

```python
def __init__(self, config_path: str | Path | None = None) -> None:
    ...
    # Phase Q8: per-tool 策略缓存 — 对标 Cline policies.ts
    # key: (server_name, tool_name) → MCPToolPolicy
    self._tool_policies: dict[tuple[str, str], MCPToolPolicy] = {}
    self._loaded = False
```

**步骤 4**：在 `load_config` 方法中（L116-180），加载 `tool_policies` 段：

```python
def load_config(self) -> int:
    self._configs.clear()
    self._tool_policies.clear()  # 对齐 Q8: 清空策略缓存
    self._loaded = True

    if not self._config_path.exists():
        logger.info(f"MCP 配置文件不存在: {self._config_path}，跳过加载")
        return 0

    try:
        import yaml
    except ImportError:
        logger.warning("未安装 PyYAML，无法加载 MCP 配置文件")
        return 0

    try:
        with open(self._config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"加载 MCP 配置失败: {e}", exc_info=True)
        return 0

    # 加载 servers 段（原有逻辑保留）
    servers_raw = data.get("servers", []) or []
    enabled_count = 0
    for srv in servers_raw:
        ...  # 原有 server 加载逻辑不变

    # Phase Q8: 加载 tool_policies 段 — 对标 Cline policies.ts
    policies_raw = data.get("tool_policies", []) or []
    for policy in policies_raw:
        if not isinstance(policy, dict):
            continue
        server = policy.get("server", "").strip()
        tool = policy.get("tool", "").strip()
        if not server or not tool:
            logger.warning(f"MCP tool_policy 缺少 server/tool 字段，跳过: {policy}")
            continue
        self._tool_policies[(server, tool)] = MCPToolPolicy(
            server_name=server,
            tool_name=tool,
            enabled=policy.get("enabled", True),
            auto_approve=policy.get("auto_approve", True),
        )
        logger.info(f"MCP tool_policy 已加载: {server}/{tool} "
                    f"(enabled={policy.get('enabled', True)}, "
                    f"auto_approve={policy.get('auto_approve', True)})")

    if enabled_count > 0:
        logger.info(f"MCP 配置加载完成: {enabled_count} 个服务器已启用")
    return enabled_count
```

**步骤 5**：新增 `get_tool_policy` 方法，查询 per-tool 策略：

```python
def get_tool_policy(
    self, server_name: str, tool_name: str
) -> MCPToolPolicy | None:
    """查询 per-tool 策略 — 对标 Cline runtime 查询 toolPolicies

    Args:
        server_name: 服务器名
        tool_name: 工具名

    Returns:
        MCPToolPolicy 实例（若配置存在），None 表示无策略（默认全部允许）
    """
    if not self._loaded:
        self.load_config()
    return self._tool_policies.get((server_name, tool_name))
```

**步骤 6**：在 `call_tool` 方法中（L272-310），调用前查询策略，`enabled: false` 拒绝执行：

```python
async def call_tool(
    self,
    server_name: str,
    tool_name: str,
    args: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """调用 MCP 工具

    Phase Q8: 调用前查询 per-tool 策略，enabled=False 拒绝执行。
    auto_approve=False 由调用方（UseMcpToolTool）处理。
    """
    # Phase Q8: 策略查询 — 对标 Cline runtime enabled: false 跳过执行
    policy = self.get_tool_policy(server_name, tool_name)
    if policy is not None and not policy.enabled:
        logger.warning(f"MCP 工具 {server_name}/{tool_name} 已被策略禁用")
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": f"MCP 工具 {server_name}/{tool_name} 已被策略禁用（enabled=false）",
            }],
        }

    lock = self._client_locks.get(server_name)
    if lock is None:
        raise KeyError(f"MCP 服务器未配置: {server_name}")

    async with lock:
        client = self.get_client(server_name)
        try:
            return await client.call_tool(tool_name, args, timeout=timeout)
        except Exception as e:
            ...  # 原有错误处理逻辑保留
```

**步骤 7**：修改 `agent/tools/mcp.py` 的 `UseMcpToolTool`，在调用 `registry.call_tool` 前查询 `auto_approve` 策略。需先 Read `mcp.py` 确认 `_execute` 与 `requires_approval` 的具体实现。

预期修改方向（实际需 Read 后确认）：
- `requires_approval` 属性改为动态查询：若 `registry.get_tool_policy(server_name, tool_name).auto_approve == False`，返回 `True`
- 或在 `_execute` 中查询策略，`auto_approve: false` 时返回需审批提示

注：`requires_approval` 是属性（property），运行时动态查询需改为方法或在使用处查询。具体实现需 Read `mcp.py` 后确定。

### 验证方法

1. **enabled=false 禁用验证**：在 `mcp_servers.yaml` 配置 `tool_policies: [{server: filesystem, tool: delete_file, enabled: false}]`，调用 `use_mcp_tool(server_name="filesystem", tool_name="delete_file")`，验证：
   - 返回 `isError: True`
   - 错误信息含"已被策略禁用"
   - 实际 MCP 工具未被调用（无 client.call_tool 日志）
2. **enabled=true 允许验证**：配置 `enabled: true`，验证工具正常调用。
3. **无策略默认允许验证**：未配置策略的工具，验证正常调用（`get_tool_policy` 返回 None）。
4. **auto_approve=false 审批验证**（若步骤 7 已实现）：配置 `auto_approve: false`，验证 `UseMcpToolTool.requires_approval` 返回 True，runtime 触发审批流程。
5. **配置热加载验证**：修改 `mcp_servers.yaml` 后 `POST /mcp/reload`，验证新策略生效。
6. **回归验证**：现有 `servers: []` + `tool_policies: []` 空配置，验证行为不变。

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断 — **必须先 Read `agent/tools/mcp.py` 确认 `UseMcpToolTool` 的 `_execute` 与 `requires_approval` 实现**
- 保留原函数逻辑，在其基础上修改 — `call_tool` 原有错误处理保留，仅在前置查询策略
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback — 策略查询返回 None 时默认允许（Cline 行为一致），不降级
- 注意：`tool_policies` 段与 `servers` 段并列（同级别），不是 server 内嵌字段 — 对标 Cline 独立的 `toolPolicies` map
- `auto_approve` 机制对接现有 `agent/approval.py`，本阶段优先实现 `enabled` 机制，`auto_approve` 可分阶段完成
- 此修改不影响现有 `mcp_servers.yaml` 的 `servers` 段格式，仅新增 `tool_policies` 段

---

## 阶段总结

### 修复优先级

| 小阶段 | 优先级 | 影响 | 建议顺序 |
|--------|--------|------|----------|
| 3.1 editor 覆盖对齐 | P1 | 数据安全 | 1（最简单，立即可做） |
| 3.2 read_files 行号 | P1 | LLM 定位能力 | 2（独立修改） |
| 3.3 editor diff | P1 | LLM 自我校验 | 3（依赖 3.1 完成） |
| 3.4 apply_patch 回滚 | P1 | 数据完整性 | 4（依赖 stage_1） |
| 3.5 BOM/CRLF | P2 | Windows 兼容 | 5（独立修改） |
| 3.6 runningSkills key | P2 | 并发去重 | 6（依赖 3.7 的 `_normalize_skill_token`） |
| 3.7 allowedSkillNames | P2 | 白名单完整性 | 7（独立修改） |
| 3.8 MCP policies | P1 | 安全审批 | 8（最复杂，需 Read mcp.py） |

### 依赖关系

- 3.1 → 3.3：3.3 在 3.1 后做，避免 `_do_overwrite` 改动冲突
- 3.4 依赖 stage_1：apply_patch 两阶段提交骨架由 stage_1 建立
- 3.6 依赖 3.7：`_normalize_skill_token` 已存在于 `registry.py`，3.6 导入复用
- 3.8 需先 Read `agent/tools/mcp.py` 确认 `requires_approval` 实现

### 验证策略

每个小阶段完成后：
1. 单元验证：按"验证方法"章节逐项验证
2. 集成验证：运行 `python tests/test_agent_e2e.py` 确保不破坏现有功能
3. 回归验证：对比修改前后的工具返回格式，确保仅新增字段/行为，不删除原有字段

### 对齐度提升预期

完成 stage_3 后，工具与技能层对齐度预期提升：
- Phase G（内置工具）：60% → 约 75%（G3.3/G3.6/G1.6 修复，G4.4 完善）
- Phase I（技能系统）：60% → 约 75%（I6/I8/I12 修复）
- Phase Q（MCP）：65% → 约 75%（Q8 修复，唯一 P1 真缺口）

---

**stage_3 方案结束。按 3.1 → 3.8 顺序执行，每阶段独立可验证。**
