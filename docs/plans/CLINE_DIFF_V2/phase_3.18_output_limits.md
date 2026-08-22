# Phase 3.18 输出截断常量对比（output-limits.ts vs constants.py）

> 对比范围：Cline `output-limits.ts` 集中式输出上限常量 + `truncateCommandOutput` 共享截断函数 + 各 executor 中的截断实现 与 Charles `agent/tools/constants.py` 集中常量 + 各工具文件中分散的截断实现 的差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/executors/output-limits.ts`（常量定义 + 共享截断函数）
> - `sdk/packages/core/src/extensions/tools/executors/bash.ts` L16-19 / L52-54 / L226-251 / L286-289（命令输出截断）
> - `sdk/packages/core/src/extensions/tools/executors/file-read.ts` L15-19 / L58-59 / L100-151（文件读取截断）
> - `sdk/packages/core/src/extensions/tools/executors/search.ts` L13 / L478-497（搜索输出截断）
> - `sdk/packages/core/src/extensions/tools/executors/web-fetch.ts` L230-238（网页抓取截断）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L21-25 / L255 / L353 / L417 / L434（工具描述中注入常量）
>
> Charles 源码：
> - `agent/tools/constants.py`（常量集中定义）
> - `agent/tools/run_commands.py` L40-46 / L57-63 / L282-288 / L364-388（命令输出截断）
> - `agent/tools/exec_tool.py` L31-35 / L51-55 / L181-188（命令输出截断，已废弃工具）
> - `agent/tools/file_tools.py` L22 / L35-38 / L137-147（单文件读取截断）
> - `agent/tools/read_files.py` L52-55 / L242-258（批量文件读取截断）
> - `agent/tools/search_codebase.py` L31-34 / L48-51 / L206-244（搜索匹配上限，无字符截断）
> - `agent/tools/list_files.py` L27 / L42-44 / L144-158（列表条目上限）
> - `agent/tools/fetch_web_content.py` L34 / L96-98 / L228-234（网页抓取截断）

---

## 一、执行摘要

Cline 与 Charles 都采用了"**集中定义常量、分散实现截断**"的模式，但在常量清单、常量值、截断策略一致性、共享截断函数、工具描述注入五个层面差异显著：

1. **常量清单差异**：Cline `output-limits.ts` 只定义 5 个**输出字符/行数上限**常量（`MAX_COMMAND_OUTPUT_CHARS` / `MAX_READ_LINES` / `MAX_LINE_CHARS` / `MAX_READ_OUTPUT_CHARS` / `MAX_SEARCH_OUTPUT_CHARS`），范围严格限定在"工具输出尺寸上限"；Charles `constants.py` 在同一文件中混入了 12 个常量，除输出字符上限外还包括超时秒数（`DEFAULT_COMMAND_TIMEOUT_SECONDS` / `MAX_COMMAND_TIMEOUT_SECONDS`）、命令数上限（`MAX_COMMANDS`）、列表条目上限（`MAX_LIST_ENTRIES`）、搜索匹配数上限（`MAX_SEARCH_MATCHES_PER_QUERY` / `MAX_SEARCH_MATCHES_PER_FILE`）、Web 内容上限（`MAX_WEB_CONTENT_CHARS`）以及工具预设字典（`TOOL_PRESETS`），**职责边界比 Cline 更宽**。

2. **常量值差异**：Cline 的字符上限统一为 `48_000`（命令/读取/搜索三者一致），Charles 的字符上限分别为 `8000`（单条命令 stdout）、`2000`（单条命令 stderr）、`16000`（exec_tool 合并输出 / 单文件读取）、`8000`（Web 内容），**Charles 整体更保守、且未对齐 Cline 的 48000**。Charles `constants.py` L19 docstring 明确说明"我的系统沿用各工具已验证的数值，未对齐 Cline 的 48000"，属于**有意为之的差异化**，非缺陷。

3. **截断策略差异（核心差距）**：Cline 对**长文本输出**统一采用"**head + tail 各一半，中间省略**"策略（`truncateCommandOutput` / `capSearchOutput`），并通过 `output-limits.ts` L10-14 注释强调"截断通知永远放在保留的 head/tail 中，不放在省略的中间，以便 message-builder 二次截断时通知仍能存活"；Charles 在 `run_commands.py` L364-388（`_truncate_output`）和 `exec_tool.py` L181-188 也采用了 head+tail 策略，但 `file_tools.py` L137-147（按行丢弃，无中间省略）、`read_files.py` L242-246（`content[:MAX]` 头部截断）、`fetch_web_content.py` L228-234（`content[:MAX]` 头部截断）均为**head-only 截断**，`search_codebase.py` **完全无字符截断**（仅限匹配数）。**Charles 的截断策略不统一**，与 Cline 的"输出类工具统一 head+tail"形成对比。

4. **共享截断函数缺失**：Cline 在 `output-limits.ts` 中导出 `truncateCommandOutput()` 共享函数，`bash.ts` 和 `search.ts` 各自调用（search.ts 另有本地 `capSearchOutput` 但策略一致）；Charles **无共享截断函数**，`run_commands.py` 的 `_truncate_output`、`exec_tool.py` 的内联截断、`file_tools.py` 的按行丢弃、`read_files.py` 的切片、`fetch_web_content.py` 的切片各自实现，**代码重复且策略分歧**。

5. **工具描述不注入常量**：Cline `definitions.ts` L255 / L353 / L417 / L434 在工具描述中显式拼接常量值（如 `Output beyond ~${Math.round(MAX_COMMAND_OUTPUT_CHARS / 1000)}k characters is middle-truncated (start and end preserved)...`），让 LLM 知道输出会被截断、主动收窄查询；Charles 所有工具的 `description` 属性**均未提及截断上限**，LLM 无法从工具描述中得知截断行为，**可能反复触发截断而不自知**。

6. **`MAX_LINE_CHARS` 缺失**：Cline `file-read.ts` L140-142 对单行超过 `MAX_LINE_CHARS=2000` 的行做头部截断并追加 ` [line truncated]` 标记（专门防御压缩/混淆文件）；Charles `file_tools.py` 和 `read_files.py` **均无单行字符截断**，遇到超长行（如压缩 JS）会原样返回，可能撑爆上下文。

7. **nanobot 残留**：P3.18 核心文件 `constants.py` **0 处残留**；P3.18 范围内的工具文件中 `exec_tool.py`（12 处）、`file_tools.py`（7 处）、`web_tool.py`（7 处）、`__init__.py`（1 处）有 nanobot 注释残留，**全部为 docstring / 行内注释**，无实现逻辑残留。`constants.py` 本身的 docstring 只引用 Cline，无 nanobot 引用。

8. **一致性总体评估**：**中**。常量集中化、命名风格（snake_case vs camelCase）已对齐；但常量值未对齐（有意为之）、截断策略不统一、缺少共享截断函数、缺少 `MAX_LINE_CHARS`、工具描述不注入常量五点构成实质性差距。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.18.1 | 常量集中化 | `output-limits.ts` 单文件 | `constants.py` 单文件 | 高 | 两者都集中定义，便于调整 |
| 3.18.2 | 常量文件职责边界 | 仅"输出字符/行数上限"5 个常量 | 混入超时/命令数/列表/搜索/Web/预设等 12+ 项 | 中 | Charles 职责更宽，非缺陷但耦合度高 |
| 3.18.3 | `MAX_COMMAND_OUTPUT_CHARS` 值 | `48_000` | `16_000`（exec_tool）；run_commands 用 `MAX_OUTPUT_PER_COMMAND=8_000` | 低 | **值不一致**，Charles 有意沿用已验证值 |
| 3.18.4 | `MAX_READ_LINES` 值 | `2_000` | `2_000` | 高 | 完全一致 |
| 3.18.5 | `MAX_LINE_CHARS`（单行截断） | `2_000`，超长行头部截断 + ` [line truncated]` 标记 | **无此常量，无单行截断** | 低 | **Charles 缺失**，遇压缩文件有撑爆上下文风险 |
| 3.18.6 | `MAX_READ_OUTPUT_CHARS` 值 | `48_000` | `16_000` | 低 | **值不一致**，Charles 有意沿用已验证值 |
| 3.18.7 | `MAX_SEARCH_OUTPUT_CHARS` 值 | `48_000`，对搜索结果文本做 head+tail 截断 | **无此常量**，search_codebase 仅限匹配数（50/20），无字符截断 | 低 | **Charles 缺失字符级截断**，长匹配行可能撑爆 |
| 3.18.8 | 命令输出截断策略 | head+tail 各半（`truncateCommandOutput`），通知在中间省略区**之外** | run_commands / exec_tool 均为 head+tail 各半，通知在中间 | 高 | 策略一致，但 Charles 通知位置未考虑 message-builder 二次截断 |
| 3.18.9 | 文件读取截断策略 | 三层：行数上限 + 单行截断 + 总字符上限（超出则停止捕获后续行） | 两层：行数上限 + 总字符上限（按行丢弃）；无单行截断 | 中 | Charles 缺单行截断层 |
| 3.18.10 | 搜索输出截断策略 | 对结果文本 head+tail 截断（`capSearchOutput`） | 仅限匹配数，**无文本截断** | 低 | **Charles 缺失**，长正则匹配可能产生超长输出 |
| 3.18.11 | 网页抓取截断策略 | head-only，硬编码 `50_000` 字符 + `[Content truncated...]` 标记 | head-only，`MAX_WEB_CONTENT_CHARS=8_000` + `note` 字段 | 中 | 策略一致（都 head-only），值不一致，Charles 更保守 |
| 3.18.12 | 共享截断函数 | `truncateCommandOutput()` 导出，bash.ts / search.ts 复用 | **无共享函数**，各工具内联实现 | 低 | **Charles 缺失**，代码重复且策略分歧 |
| 3.18.13 | 截断通知文案位置 | 强制放在保留的 head/tail，**不放在省略的中间**（output-limits.ts L10-14） | run_commands / exec_tool 通知在中间省略区；file_tools 通知在尾部；read_files 在 `note` 字段 | 中 | Charles 未考虑 provider 二次截断会丢失通知 |
| 3.18.14 | 截断通知文案内容 | `[... output truncated: ${totalChars} chars total. Refine the command (grep, head, tail) to view the elided middle ...]` | run_commands: `[... {omitted} characters omitted ...]`；exec_tool: `... ({N:,} 字符已截断) ...`；read_files: `内容已截断到 {N} 字符` | 中 | 文案不统一，Charles 部分工具未给出"如何收窄"的指引 |
| 3.18.15 | 工具描述注入常量 | `definitions.ts` L255/L353/L417/L434 在 description 中拼接 `MAX_*` 值 | **所有工具 description 均未提及截断上限** | 低 | **Charles 缺失**，LLM 无法预知截断 |
| 3.18.16 | message-builder 二次截断回退 | output-limits.ts L10-14 注释说明 provider 请求构建时会再次 middle-cut，故通知放边缘 | **无 message-builder 等价层**，无二次截断回退 | 中 | Charles 架构层级不同，非缺陷但少了安全网 |
| 3.18.17 | stderr 独立截断 | bash.ts 合并 stdout+stderr 后统一截断（`combineOutput=true` 默认） | run_commands 独立截断 stdout（8_000）和 stderr（2_000） | 中 | Charles 更细粒度，但与 Cline 模型不同 |
| 3.18.18 | 命令数上限 | 无（由工具调用层限制） | `MAX_COMMANDS=10` | — | Charles 额外限制，非 Cline 对标项 |
| 3.18.19 | 列表条目上限 | 不在 output-limits.ts（由 list_files 工具内部处理） | `MAX_LIST_ENTRIES=200` 在 constants.py | — | Charles 集中化，Cline 分散 |
| 3.18.20 | 单位说明 | output-limits.ts L5 明确"字符数（UTF-16 code units）" | constants.py 未说明单位 | 中 | Charles 隐含为字符数，Python `len()` 即码元数 |
| 3.18.21 | 常量命名风格 | camelCase：`MAX_COMMAND_OUTPUT_CHARS` | SNAKE_CASE：`MAX_COMMAND_OUTPUT_CHARS` | 高（语言习惯） | 命名一致（都全大写），仅大小写风格差异 |
| 3.18.22 | 数字分隔符 | `48_000` / `2_000` | `48000` / `2000`（无下划线分隔） | 低（风格） | Python 3.6+ 支持下划线，Charles 未用 |

**一致性总评**：22 项中，高一致性 4 项、中一致性 8 项、低一致性 10 项。低一致性主要集中在：常量值未对齐（有意）、`MAX_LINE_CHARS` 缺失、搜索字符截断缺失、共享截断函数缺失、工具描述不注入常量。

---

## 三、重点差距详细说明

### 差距 1：截断策略不统一（3.18.8 / 3.18.9 / 3.18.10 / 3.18.11）

**Cline 实现**：

Cline 对**所有可能产生超长文本的工具**统一采用 head+tail 中间省略策略，并由 `output-limits.ts` L10-14 注释明确设计意图："截断通知永远放在保留的 head/tail 中，不放在省略的中间，以便 provider 请求构建时的 middle-cut 回退仍能保留恢复指引"。

- `bash.ts` L226-251：调用 `truncateCommandOutput(failureOutput, { maxChars, totalChars })`，函数实现于 `output-limits.ts` L20-38，head 取 `ceil(max/2)`、tail 取 `max(1, max-head)`，中间插入 `[... output truncated: ${totalChars} chars total. Refine the command (grep, head, tail) to view the elided middle ...]`。
- `search.ts` L485-497：本地 `capSearchOutput(text)`，与 `truncateCommandOutput` 同策略，仅文案不同（`Narrow the pattern or scope to view the elided matches`）。
- `file-read.ts` L100-151：行数上限（`MAX_READ_LINES`）+ 单行截断（`MAX_LINE_CHARS`，头部截断 + ` [line truncated]`）+ 总字符上限（`MAX_READ_OUTPUT_CHARS`，超出则**停止捕获后续行**，不做中间省略）。文件读取是唯一不采用 head+tail 的工具，因为按行流式读取时无法预知尾部。
- `web-fetch.ts` L230-238：head-only（`content.slice(0, 50000)`）+ 尾部追加 `[Content truncated: showing first 50000 of ${N} characters]`，**这是 Cline 唯一的 head-only 例外**。

**Charles 实现**：

Charles 的截断策略**按工具分散、不统一**：

- `run_commands.py` L364-388（`_truncate_output`）：head+tail 各半，中间插入 `[... {omitted} characters omitted ...]`。**与 Cline 一致**。
- `exec_tool.py` L181-188：head+tail 各半，中间插入 `... ({N:,} 字符已截断) ...`。**与 Cline 一致**（但该工具已废弃）。
- `file_tools.py` L137-147：按行丢弃，`chars += len(line) + 1; if chars > self._MAX_CHARS: break`，**无中间省略、无单行截断**。尾部追加 `(显示第 X-Y 行，共 Z 行...)`。**与 Cline 策略不同**（Cline 有单行截断）。
- `read_files.py` L242-246：`content[:self._MAX_CHARS_PER_FILE]`，**纯头部切片**，无 tail 保留。`note` 字段提示"内容已截断到 N 字符"。**与 Cline 策略不同**。
- `search_codebase.py` L206-244：**完全无字符截断**，仅限 `MAX_SEARCH_MATCHES_PER_QUERY=50` 和 `MAX_SEARCH_MATCHES_PER_FILE=20`。若单条匹配行极长（如压缩文件中的一行），输出可能撑爆上下文。**与 Cline 策略不同**（Cline 有 `capSearchOutput`）。
- `fetch_web_content.py` L228-234：`text_content[:self._MAX_CONTENT_CHARS]`，**纯头部切片**，与 Cline web-fetch 策略一致但值更保守（8000 vs 50000）。

**影响**：
- Charles `read_files.py` 的 head-only 切片会**丢失文件末尾**（如函数 return 语句、异常处理），对 LLM 理解代码结构不利；Cline 的按行丢弃至少保留行完整性。
- Charles `search_codebase.py` 无字符截断，遇到压缩/混淆文件匹配会**直接撑爆上下文**，是**实际风险点**。
- Charles `file_tools.py` 无单行截断，遇到压缩 JS / minified 文件会原样返回超长行，**可能撑爆上下文**。

**建议**：
- **P1**：为 `search_codebase.py` 增加 `MAX_SEARCH_OUTPUT_CHARS` 字符级截断（建议 head+tail），对标 Cline `capSearchOutput`。
- **P2**：为 `file_tools.py` 和 `read_files.py` 增加 `MAX_LINE_CHARS` 单行截断，对标 Cline `file-read.ts` L140-142。
- **P2**：将 `read_files.py` 的 head-only 切片改为按行丢弃（与 `file_tools.py` 一致），保留行完整性。
- **P3**：考虑提取共享 `_truncate_middle(text, limit, notice)` 函数到 `constants.py` 或 `base.py`，统一 run_commands / exec_tool / search_codebase 的截断实现。

### 差距 2：`MAX_LINE_CHARS` 单行截断缺失（3.18.5）

**Cline 实现**（`file-read.ts` L139-142）：

```typescript
let line = rawLine;
if (line.length > MAX_LINE_CHARS) {
    line = `${line.slice(0, MAX_LINE_CHARS)} [line truncated]`;
}
```

`MAX_LINE_CHARS = 2_000`，专门防御 minified JS / 压缩 JSON / bundle 文件等单行超长场景。截断后追加 ` [line truncated]` 标记，让 LLM 知道该行被截断。

**Charles 实现**：

`file_tools.py` L130-135 和 `read_files.py` L231-240 均直接 `f"{行号} | {line}"` 拼接，**无任何单行长度检查**。`constants.py` 中**无 `MAX_LINE_CHARS` 常量定义**。

**影响**：
- 读取 `bundle.js` / `minified.css` / 压缩 JSON 等文件时，单行可能数万字符，Charles 会原样返回，**直接撑爆上下文**。
- Cline 的 `MAX_LINE_CHARS` 是对此类场景的硬防御，Charles 缺失该层防御。

**建议**：**P1** 在 `constants.py` 增加 `MAX_LINE_CHARS = 2000`，在 `file_tools.py` 和 `read_files.py` 的行拼接前增加单行截断逻辑。

### 差距 3：共享截断函数缺失（3.18.12）

**Cline 实现**（`output-limits.ts` L20-38）：

```typescript
export function truncateCommandOutput(
    text: string,
    options: { maxChars?: number; totalChars?: number } = {},
): string {
    const maxChars = options.maxChars ?? MAX_COMMAND_OUTPUT_CHARS;
    const totalChars = options.totalChars ?? text.length;
    if (text.length <= maxChars && totalChars <= maxChars) {
        return text;
    }
    const headLimit = Math.ceil(maxChars / 2);
    const tailLimit = Math.max(1, maxChars - headLimit);
    return (
        `${text.slice(0, headLimit)}\n` +
        `[... output truncated: ${totalChars} chars total. Refine the command (grep, head, tail) to view the elided middle ...]\n` +
        text.slice(-tailLimit)
    );
}
```

该函数被 `bash.ts` L227 / L246 和（以本地等价函数形式）`search.ts` L485 复用。`totalChars` 参数支持"实际文本已被 collector 部分丢弃，但需报告原始总字符数"的场景（bash.ts L223-225）。

**Charles 实现**：

Charles 无共享截断函数，各工具内联实现：

- `run_commands.py` L364-388 `_truncate_output`：独立方法，返回 `tuple[str, bool]`（截断文本 + 是否截断标志），与 Cline 签名不同（Cline 只返回字符串）。
- `exec_tool.py` L181-188：内联在 `_execute` 中，无函数封装。
- `search_codebase.py`：无截断。
- `file_tools.py` L137-147：按行丢弃，无函数封装。
- `read_files.py` L242-246：切片，无函数封装。
- `fetch_web_content.py` L228-234：切片，无函数封装。

**影响**：
- 截断策略分散，修改时需多处同步（如调整 head/tail 比例、修改通知文案）。
- `run_commands.py` 的 `_truncate_output` 与 `exec_tool.py` 的内联实现**逻辑几乎相同**（都 head+tail 各半），但代码重复，未提取公共函数。
- 若未来需要对标 Cline 的 `totalChars` 参数（报告原始总字符数而非截断后字符数），需多处修改。

**建议**：**P3** 在 `constants.py` 或 `base.py` 中提取 `_truncate_middle(text: str, limit: int, notice: str | None = None) -> tuple[str, bool]` 共享函数，统一 run_commands / exec_tool / search_codebase（若补齐字符截断）的截断实现。不强制补齐，但有助于一致性。

### 差距 4：工具描述不注入截断常量（3.18.15）

**Cline 实现**（`definitions.ts` L255 / L353 / L417 / L434）：

Cline 在工具描述中显式拼接常量值，让 LLM 知道输出会被截断、主动收窄查询：

- `read_files`：`Each read returns at most ${MAX_READ_LINES} lines / ~${Math.round(MAX_READ_OUTPUT_CHARS / 1024)}k characters; longer files report their total line count, page through them with start_line/end_line on that file's entry.`
- `search_codebase`：`Output beyond ~${Math.round(MAX_SEARCH_OUTPUT_CHARS / 1000)}k characters per query is middle-truncated; narrow patterns beat broad ones.`
- `run_commands`：`Output beyond ~${Math.round(MAX_COMMAND_OUTPUT_CHARS / 1000)}k characters is middle-truncated (start and end preserved); filter output when you need specific sections.`
- `bash`：`Output beyond ~${Math.round(MAX_COMMAND_OUTPUT_CHARS / 1000)}k characters is middle-truncated (start and end preserved); pipe through grep/head/tail when you need specific sections of large output.`

**Charles 实现**：

Charles 所有工具的 `description` 属性均**未提及截断上限**：

- `run_commands.py` L87-91：仅说明"最多 10 条"命令数上限，未提及输出字符上限。
- `file_tools.py` L46-51：仅说明"默认 2000"行数，未提及字符上限。
- `read_files.py` L70-75：仅说明"最多 10 个文件"，未提及单文件字符上限。
- `search_codebase.py` L90-93：仅说明"正则表达式数组"，未提及匹配数上限或字符上限。
- `fetch_web_content.py` L116-119：未提及内容字符上限。

**影响**：
- LLM 不知道输出会被截断，可能反复触发截断而不自知，浪费 token。
- LLM 不知道有分页机制（`offset` / `start_line`），不会主动分页读取大文件。
- Cline 的描述明确告诉 LLM "narrow patterns beat broad ones"、"pipe through grep/head/tail"，引导 LLM 主动收窄查询；Charles 缺少这种引导。

**建议**：**P2** 在 Charles 各工具 `description` 中补充截断上限说明，如：
- `run_commands`：`单条命令输出超过 8000 字符会被首尾各保留一半、中间省略；建议用 grep/head/tail 收窄输出。`
- `read_files`：`单文件输出超过 16000 字符会被截断；大文件请用 start_line/end_line 分页读取。`
- `search_codebase`：`单查询最多返回 50 个匹配、单文件最多 20 行；请用更精确的正则收窄结果。`

### 差距 5：常量值未对齐（3.18.3 / 3.18.6 / 3.18.11）

**Cline 实现**：

| 常量 | Cline 值 | 说明 |
|------|---------|------|
| `MAX_COMMAND_OUTPUT_CHARS` | `48_000` | 命令输出字符上限 |
| `MAX_READ_OUTPUT_CHARS` | `48_000` | 文件读取字符上限 |
| `MAX_SEARCH_OUTPUT_CHARS` | `48_000` | 搜索输出字符上限 |
| `MAX_READ_LINES` | `2_000` | 文件读取行数上限 |
| `MAX_LINE_CHARS` | `2_000` | 单行字符上限 |
| web-fetch 硬编码 | `50_000` | 网页抓取字符上限（非 output-limits.ts 常量） |

Cline 的字符上限**统一为 48000**（web-fetch 例外，硬编码 50000），设计意图是"在 200k token 上下文窗口下，单次工具输出约占 24% token，留出空间给其他工具和对话"。

**Charles 实现**：

| 常量 | Charles 值 | 对应工具 |
|------|-----------|---------|
| `MAX_OUTPUT_PER_COMMAND` | `8_000` | run_commands 单条 stdout |
| `MAX_STDERR_PER_COMMAND` | `2_000` | run_commands 单条 stderr |
| `MAX_COMMAND_OUTPUT_CHARS` | `16_000` | exec_tool 合并输出 |
| `MAX_READ_OUTPUT_CHARS` | `16_000` | file_tools 单次读取 |
| `MAX_READ_LINES` | `2_000` | file_tools 单次读取行数 |
| `MAX_WEB_CONTENT_CHARS` | `8_000` | fetch_web_content |
| `MAX_LIST_ENTRIES` | `200` | list_files |
| `MAX_SEARCH_MATCHES_PER_QUERY` | `50` | search_codebase |
| `MAX_SEARCH_MATCHES_PER_FILE` | `20` | search_codebase |
| `MAX_COMMANDS` | `10` | run_commands |

Charles `constants.py` L19 docstring 明确说明："我的系统沿用各工具已验证的数值，未对齐 Cline 的 48000。若后续需要调整，可统一修改本文件。"

**分析**：
- Charles 的值整体更保守（8000-16000 vs 48000），适合量化分析场景（输出多为 JSON 报告、CSV 数据，长度可控）。
- Charles 对 stdout / stderr / 合并输出分别设限（8000 / 2000 / 16000），比 Cline 的统一 48000 更细粒度。
- Charles 的 `MAX_READ_OUTPUT_CHARS=16000` 远小于 Cline 的 48000，读取大文件时需更多分页调用，但单次 token 成本更低。
- 这是**有意为之的差异化**，`constants.py` docstring 已明确说明，**非缺陷**。

**建议**：**不强制对齐**。Charles 的保守值符合量化场景特征。若后续发现 LLM 频繁触发截断导致信息丢失，可考虑将 `MAX_READ_OUTPUT_CHARS` 提升到 32000 或 48000。

---

## 四、nanobot 残留检查

针对 P3.18 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.18 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/constants.py` | **0** | 无 | docstring 仅引用 Cline output-limits.ts，无 nanobot 引用 |
| `agent/tools/run_commands.py` | **0** | 无 | 全文无 nanobot 引用（已对标 Cline bash.ts） |
| `agent/tools/exec_tool.py` | **12** | 注释残留 | docstring L2/L8/L9/L10/L18/L19 + 类 docstring L41 + 行内注释 L57/L123/L165/L181/L263 |
| `agent/tools/file_tools.py` | **7** | 注释残留 | docstring L2/L7/L12 + 类 docstring L27/L165 + 行内注释 L115/L130 |
| `agent/tools/read_files.py` | **0** | 无 | 全文无 nanobot 引用（对标 Cline ReadFilesInputSchema） |
| `agent/tools/search_codebase.py` | **0** | 无 | 全文无 nanobot 引用（对标 Cline createSearchTool） |
| `agent/tools/list_files.py` | **0** | 无 | 全文无 nanobot 引用 |
| `agent/tools/fetch_web_content.py` | **0** | 无 | 全文无 nanobot 引用（对标 Cline createWebFetchTool） |
| `agent/tools/web_tool.py` | **7** | 注释残留 | docstring L2/L9/L10/L13 + 类 docstring L28 + 行内注释 L111/L165 |
| `agent/tools/__init__.py` | **1** | 注释残留 | L2 docstring：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools` |

### 4.2 残留分类

#### 注释残留（27 处，分布在 4 个文件）

**性质**：全部为 docstring 或行内注释中的历史溯源说明，标注 Charles 工具同时对标了 Cline 和历史 nanobot。不影响运行时行为，不影响工具功能，不影响截断常量值。

**典型示例**：
- `exec_tool.py` L2：`"""命令执行工具 — 对标 Cline BashTool + nanobot ShellTool`
- `exec_tool.py` L181：`# 输出截断 — 对标 nanobot shell.py L171-178`
- `file_tools.py` L115：`# 分页读取 — 对标 nanobot filesystem.py L150-176`
- `file_tools.py` L130：`# 行号格式: "行号| 内容" — 对标 nanobot 格式`
- `web_tool.py` L111：`"""DuckDuckGo 搜索 — 对标 nanobot _search_duckduckgo`
- `__init__.py` L2：`"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools`

**处理建议**：属 P2 级别清理，不阻塞 P3.18 对比结论。建议在后续清理批次中统一移除 nanobot 引用，保留 Cline 对标引用。

#### 实现逻辑残留（0 处）

P3.18 核心文件中**未发现任何从 nanobot 直接移植的截断实现逻辑**：

- `constants.py` 的常量定义对标 Cline `output-limits.ts`（L7 docstring 明确标注"Cline 源码位置: sdk/packages/core/src/extensions/tools/executors/output-limits.ts"）。
- `run_commands.py` 的 `_truncate_output` 方法对标 Cline `truncateCommandOutput`（L365 docstring 标注"对标 Cline 首尾各一半截断"），Stage 12.1 G2.5 实现。
- `exec_tool.py` 的内联截断逻辑虽在注释中标注"对标 nanobot shell.py L171-178"，但**实际逻辑是 head+tail 各半**（L182-188），与 Cline `truncateCommandOutput` 策略一致，与 nanobot 的 head-only 截断不同（nanobot shell.py 实际为 head+tail，注释溯源准确但非逻辑移植）。
- `file_tools.py` 的按行丢弃策略对标 Cline `file-read.ts` 的 `captured.length >= MAX_READ_LINES` 逻辑（L134-136），与 nanobot 无关。
- `search_codebase.py` 的匹配数上限是 Charles 独有设计，无 nanobot 对应。
- `fetch_web_content.py` 的 head-only 切片对标 Cline `web-fetch.ts` L230-238，与 nanobot 无关。

### 4.3 P3.18 范围外但相关的 nanobot 残留

以下文件有 nanobot 残留，但属于 P3.x 其他小阶段的对比范围，不在 P3.18 处理：

| 文件 | nanobot 匹配数 | 对应小阶段 |
|------|---------------|-----------|
| `agent/tools/editor.py` | 待查 | P3.x（EditorTool 专项） |
| `agent/tools/apply_patch.py` | 待查 | P3.12（已完成） |
| `agent/skills/registry.py` | 待查 | P3.x（Skills 专项） |

---

## 五、修复建议

### 建议 1：为 search_codebase 增加字符级截断 [P1]

**文件**：`agent/tools/search_codebase.py` + `agent/tools/constants.py`
**问题**：当前 `search_codebase.py` 仅限匹配数（50/20），无字符级截断。遇到压缩/混淆文件匹配会撑爆上下文。
**修改**：
1. 在 `constants.py` 增加 `MAX_SEARCH_OUTPUT_CHARS = 16000`（沿用 Charles 保守值风格）。
2. 在 `search_codebase.py` 的 `_search_in_files` 返回后，对 `matches` 列表拼接的文本做 head+tail 截断（对标 Cline `capSearchOutput`）。
**理由**：对标 Cline `search.ts` L485-497 的 `capSearchOutput`，防御超长匹配行撑爆上下文。这是**实际风险点**。

### 建议 2：增加 MAX_LINE_CHARS 单行截断 [P1]

**文件**：`agent/tools/constants.py` + `agent/tools/file_tools.py` + `agent/tools/read_files.py`
**问题**：当前读取文件时无单行长度检查，遇到 minified JS / 压缩 JSON 会原样返回超长行。
**修改**：
1. 在 `constants.py` 增加 `MAX_LINE_CHARS = 2000`（对标 Cline）。
2. 在 `file_tools.py` L131-134 和 `read_files.py` L234-237 的行拼接前，增加 `if len(line) > MAX_LINE_CHARS: line = line[:MAX_LINE_CHARS] + " [line truncated]"`。
**理由**：对标 Cline `file-read.ts` L140-142，防御压缩文件撑爆上下文。

### 建议 3：工具描述补充截断上限说明 [P2]

**文件**：`agent/tools/run_commands.py` / `file_tools.py` / `read_files.py` / `search_codebase.py` / `fetch_web_content.py`
**问题**：当前工具 `description` 均未提及截断上限，LLM 无法预知截断行为。
**修改**：在各工具 `description` 属性中补充截断上限说明，引导 LLM 主动收窄查询/分页读取。
**理由**：对标 Cline `definitions.ts` L255/L353/L417/L434 的描述注入实践。

### 建议 4：将 read_files 的 head-only 切片改为按行丢弃 [P2]

**文件**：`agent/tools/read_files.py` L242-246
**问题**：当前 `content[:self._MAX_CHARS_PER_FILE]` 是纯头部切片，可能截断到行中间，丢失文件末尾。
**修改**：改为按行累积字符数、超出则停止捕获后续行（与 `file_tools.py` L137-147 一致）。
**理由**：保留行完整性，与 `file_tools.py` 策略统一，与 Cline `file-read.ts` L144-148 策略一致。

### 建议 5：清理 nanobot 注释残留 [P2]

**文件**：`agent/tools/exec_tool.py` / `file_tools.py` / `web_tool.py` / `__init__.py`
**问题**：27 处 nanobot 注释残留（详见第四节）。
**修改**：移除 docstring 和行内注释中的 `对标 nanobot ...` 段落，保留 `对标 Cline ...` 段落。
**理由**：统一为"对标 Cline"溯源风格，与 `constants.py` / `run_commands.py` / `read_files.py` / `search_codebase.py`（已无 nanobot 残留）保持一致。

### 建议 6：提取共享截断函数 [P3 不强制]

**文件**：`agent/tools/constants.py` 或 `agent/tools/base.py`
**问题**：`run_commands.py` 的 `_truncate_output` 和 `exec_tool.py` 的内联截断逻辑重复。
**修改**：提取 `_truncate_middle(text: str, limit: int, notice: str | None = None) -> tuple[str, bool]` 共享函数。
**理由**：减少代码重复，便于未来统一调整截断策略。不强制补齐，因为 `exec_tool.py` 已废弃，`run_commands.py` 的 `_truncate_output` 已稳定。

### 建议 7：不强制对齐常量值到 Cline 的 48000 [P3 不修复]

**理由**：
- Charles `constants.py` L19 docstring 已明确说明"沿用各工具已验证的数值，未对齐 Cline 的 48000"。
- Charles 的保守值（8000-16000）符合量化分析场景特征（输出多为 JSON/CSV，长度可控）。
- 强制对齐可能改变已验证的工具行为，引入风险。
- 若后续发现 LLM 频繁触发截断导致信息丢失，可单独调整某个常量值。

---

## 六、验证方法建议

### 验证方法 1：常量清单完整性检查

对比 Cline `output-limits.ts` 导出的常量与 Charles `constants.py` 定义的常量，确认缺失项：

```powershell
# Cline 侧（output-limits.ts）
# 常量：MAX_COMMAND_OUTPUT_CHARS / MAX_READ_LINES / MAX_LINE_CHARS / MAX_READ_OUTPUT_CHARS / MAX_SEARCH_OUTPUT_CHARS
# 函数：truncateCommandOutput

# Charles 侧（constants.py）
# 缺失：MAX_LINE_CHARS / MAX_SEARCH_OUTPUT_CHARS / truncateCommandOutput 等价函数
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern "MAX_LINE_CHARS|MAX_SEARCH_OUTPUT_CHARS|truncate"
```

**预期**：Charles 无 `MAX_LINE_CHARS` / `MAX_SEARCH_OUTPUT_CHARS` / 共享截断函数（已知差异，建议 1/2 决定补齐）。

### 验证方法 2：截断策略一致性检查

确认 Charles 各工具的截断策略（head-only vs head+tail vs 按行丢弃 vs 无截断）：

```powershell
# run_commands.py 应为 head+tail
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\run_commands.py" -Pattern "head|tail|half|slice\(-"
# read_files.py 应为 head-only（content[:MAX]）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\read_files.py" -Pattern "content\[:|slice"
# search_codebase.py 应无字符截断
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\search_codebase.py" -Pattern "truncat|slice|MAX.*CHARS"
```

### 验证方法 3：工具描述注入检查

确认 Charles 工具描述是否提及截断上限（应均未提及）：

```powershell
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\*.py" -Pattern "截断|truncat|字符上限|characters"
```

**预期**：仅在代码注释和 `note` 字段中出现，不在 `description` 属性中出现。

### 验证方法 4：nanobot 残留扫描

```powershell
# P3.18 核心文件扫描
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\constants.py" -Pattern "nanobot" -CaseSensitive:$false
# 应返回 0 行

Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\exec_tool.py" -Pattern "nanobot" -CaseSensitive:$false
# 应返回 12 行（全部为注释残留）
```

### 验证方法 5：单行截断缺失影响评估

构造一个包含超长行的文件（如 minified JS），用 `read_files` 读取，确认 Charles 不会截断单行：

```python
# 伪代码示意（不要求实际编写）
# 创建一个单行 50000 字符的文件
# 用 ReadFilesTool 读取
# 预期：Charles 原样返回 50000 字符行（不截断）
# 预期：Cline 会截断到 2000 字符 + " [line truncated]" 标记
```

**预期**：Charles 不截断（已知差异，建议 2 决定补齐）。

### 验证方法 6：搜索输出撑爆上下文评估

构造一个正则匹配压缩文件的超长行场景，用 `search_codebase` 搜索，确认 Charles 不会截断：

```python
# 伪代码示意（不要求实际编写）
# 创建一个包含 100000 字符单行的 minified.js
# 用 SearchCodebaseTool 搜索 queries=["function"]
# 预期：Charles 返回 50 个匹配，每个匹配行 100000 字符，总输出约 5,000,000 字符
# 预期：Cline 会对结果文本做 head+tail 截断到 48000 字符
```

**预期**：Charles 不截断（已知差异，建议 1 决定补齐）。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L1-15 | 文件头注释（设计说明：截断通知位置、message-builder 二次截断） |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L17-18 | `MAX_COMMAND_OUTPUT_CHARS = 48_000` |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L20-38 | `truncateCommandOutput()` 共享截断函数 |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L40-41 | `MAX_READ_LINES = 2_000` |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L43-44 | `MAX_LINE_CHARS = 2_000` |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L46-47 | `MAX_READ_OUTPUT_CHARS = 48_000` |
| `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` | L49-50 | `MAX_SEARCH_OUTPUT_CHARS = 48_000` |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L16-19 | 导入 `MAX_COMMAND_OUTPUT_CHARS` / `truncateCommandOutput` |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L52-54 | `maxOutputChars` 选项默认值说明 |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L86-100 | `createRollingCollector` head+tail 收集器 |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L226-251 | 失败/成功输出调用 `truncateCommandOutput` |
| `sdk/packages/core/src/extensions/tools/executors/bash.ts` | L286-289 | `maxOutputChars` 默认回退到 `MAX_COMMAND_OUTPUT_CHARS` |
| `sdk/packages/core/src/extensions/tools/executors/file-read.ts` | L15-19 | 导入 `MAX_LINE_CHARS` / `MAX_READ_LINES` / `MAX_READ_OUTPUT_CHARS` |
| `sdk/packages/core/src/extensions/tools/executors/file-read.ts` | L58-59 | `MAX_TEXT_STREAM_BYTES` / `MAX_UNRANGED_LINE_SCAN` 本地常量 |
| `sdk/packages/core/src/extensions/tools/executors/file-read.ts` | L100-105 | `maxCapturedLineNumber` 计算（行号前缀字符数） |
| `sdk/packages/core/src/extensions/tools/executors/file-read.ts` | L134-148 | 行数上限 + 单行截断 + 总字符上限 三层截断 |
| `sdk/packages/core/src/extensions/tools/executors/search.ts` | L13 | 导入 `MAX_SEARCH_OUTPUT_CHARS` |
| `sdk/packages/core/src/extensions/tools/executors/search.ts` | L478-497 | `capSearchOutput()` 本地截断函数（head+tail） |
| `sdk/packages/core/src/extensions/tools/executors/web-fetch.ts` | L230-238 | 硬编码 50000 字符 head-only 截断 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L21-25 | 导入 4 个 `MAX_*` 常量 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L255 | `read_files` 描述注入 `MAX_READ_LINES` / `MAX_READ_OUTPUT_CHARS` |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L353 | `search_codebase` 描述注入 `MAX_SEARCH_OUTPUT_CHARS` |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L417 / L434 | `run_commands` / `bash` 描述注入 `MAX_COMMAND_OUTPUT_CHARS` |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/constants.py` | L1-21 | 文件头 docstring（设计说明 + Cline 原始常量参考 + 未对齐说明） |
| `agent/tools/constants.py` | L27-33 | `MAX_OUTPUT_PER_COMMAND=8000` / `MAX_STDERR_PER_COMMAND=2000` |
| `agent/tools/constants.py` | L35-37 | `MAX_COMMAND_OUTPUT_CHARS=16000`（exec_tool） |
| `agent/tools/constants.py` | L39-47 | `MAX_COMMANDS=10` / `DEFAULT_COMMAND_TIMEOUT_SECONDS=60` / `MAX_COMMAND_TIMEOUT_SECONDS=600` |
| `agent/tools/constants.py` | L53-59 | `MAX_READ_LINES=2000` / `MAX_READ_OUTPUT_CHARS=16000` |
| `agent/tools/constants.py` | L65-67 | `MAX_LIST_ENTRIES=200` |
| `agent/tools/constants.py` | L73-79 | `MAX_SEARCH_MATCHES_PER_QUERY=50` / `MAX_SEARCH_MATCHES_PER_FILE=20` |
| `agent/tools/constants.py` | L85-87 | `MAX_WEB_CONTENT_CHARS=8000` |
| `agent/tools/constants.py` | L90-156 | `TOOL_PRESETS` 字典 + `resolve_tool_preset()` 函数（非截断相关） |
| `agent/tools/run_commands.py` | L40-46 | 导入 5 个命令常量 |
| `agent/tools/run_commands.py` | L57-63 | 类属性别名（`_MAX_OUTPUT_PER_COMMAND` 等） |
| `agent/tools/run_commands.py` | L282-288 | 调用 `_truncate_output` 截断 stdout / stderr |
| `agent/tools/run_commands.py` | L364-388 | `_truncate_output()` 方法（head+tail 各半） |
| `agent/tools/exec_tool.py` | L31-35 | 导入 `MAX_COMMAND_OUTPUT_CHARS` 等 |
| `agent/tools/exec_tool.py` | L51-55 | 类属性别名 |
| `agent/tools/exec_tool.py` | L181-188 | 内联 head+tail 截断（已废弃工具） |
| `agent/tools/file_tools.py` | L22 | 导入 `MAX_READ_LINES` / `MAX_READ_OUTPUT_CHARS` |
| `agent/tools/file_tools.py` | L35-38 | 类属性别名 |
| `agent/tools/file_tools.py` | L137-147 | 按行丢弃截断（无单行截断、无中间省略） |
| `agent/tools/read_files.py` | L52-55 | `_MAX_CHARS_PER_FILE=16000` 硬编码（未从 constants 导入） |
| `agent/tools/read_files.py` | L242-246 | `content[:MAX]` 头部切片截断 |
| `agent/tools/search_codebase.py` | L31-34 | 导入 `MAX_SEARCH_MATCHES_PER_QUERY` / `MAX_SEARCH_MATCHES_PER_FILE` |
| `agent/tools/search_codebase.py` | L48-51 | 类属性别名 |
| `agent/tools/search_codebase.py` | L206-244 | `_search_in_files` 仅限匹配数，**无字符截断** |
| `agent/tools/list_files.py` | L27 | 导入 `MAX_LIST_ENTRIES` |
| `agent/tools/list_files.py` | L42-44 | 类属性别名 |
| `agent/tools/list_files.py` | L144-158 | `entries[:MAX_ENTRIES]` 列表截断 |
| `agent/tools/fetch_web_content.py` | L34 | 导入 `MAX_WEB_CONTENT_CHARS` |
| `agent/tools/fetch_web_content.py` | L96-98 | 类属性别名 |
| `agent/tools/fetch_web_content.py` | L228-234 | `text_content[:MAX]` 头部切片截断 |

---

## 八、结论

P3.18 输出截断常量对比的核心结论：

1. **常量集中化已对齐**：两者都采用单文件集中定义（Cline `output-limits.ts` / Charles `constants.py`），便于调整。Charles 的 `constants.py` 职责边界更宽（混入超时/命令数/列表/搜索/Web/预设），但非缺陷。

2. **常量值有意不对齐**：Charles 的字符上限（8000-16000）整体比 Cline（48000）更保守，`constants.py` L19 docstring 已明确说明这是"沿用各工具已验证的数值"，**属于有意为之的差异化**，非缺陷。

3. **截断策略不统一是核心差距**：Cline 对长文本输出统一采用 head+tail 中间省略（`truncateCommandOutput` / `capSearchOutput`）；Charles 在 `run_commands` / `exec_tool` 中采用了 head+tail（与 Cline 一致），但在 `read_files` / `fetch_web_content` 中采用 head-only 切片，在 `search_codebase` 中**完全无字符截断**。这是**实际风险点**，建议 1（P1）和建议 2（P1）优先修复。

4. **`MAX_LINE_CHARS` 缺失是防御层漏洞**：Cline 对单行超过 2000 字符的行做头部截断（防御 minified 文件）；Charles 完全无此防御，遇到压缩文件可能撑爆上下文。建议 2（P1）补齐。

5. **共享截断函数缺失**：Cline 导出 `truncateCommandOutput` 供 bash.ts / search.ts 复用；Charles 各工具内联实现，代码重复且策略分歧。建议 6（P3）不强制补齐。

6. **工具描述不注入常量**：Cline 在工具描述中显式拼接 `MAX_*` 值引导 LLM 主动收窄查询；Charles 所有工具描述均未提及截断上限。建议 3（P2）补齐。

7. **nanobot 残留**：P3.18 核心文件 `constants.py` **0 处残留**；工具文件中 27 处注释残留（分布在 `exec_tool.py` / `file_tools.py` / `web_tool.py` / `__init__.py`），**全部为注释残留，无实现逻辑残留**。建议 5（P2）清理。

**整体一致性等级**：**中**。P3.18 范围内有 2 个 P1 级建议（search_codebase 字符截断缺失、MAX_LINE_CHARS 单行截断缺失）为**实际风险点**，建议优先修复；其余为 P2/P3 级别改进，不阻塞对比结论。
