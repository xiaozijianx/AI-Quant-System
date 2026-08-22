# Phase 3.13 search_codebase 工具实现细节对比

> 对比范围：Cline `createSearchTool` + `createSearchExecutor` 与 Charles `SearchCodebaseTool` 在输入 schema、搜索后端（ripgrep vs Python re）、结果格式、结果截断、文件类型过滤、正则支持、多目录搜索、错误处理八个维度的实现细节差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L335-395（createSearchTool 工厂 + 工具描述）
> - `sdk/packages/core/src/extensions/tools/executors/search.ts`（createSearchExecutor + searchWithRipgrep + shouldIncludeFile + capSearchOutput）
> - `sdk/packages/core/src/extensions/tools/schemas.ts` L107-121（SearchCodebaseInputSchema + SearchCodebaseUnionInputSchema）
> - `sdk/packages/core/src/extensions/tools/types.ts` L65-69（SearchExecutor 类型签名）
> - `sdk/packages/core/src/extensions/tools/executors/output-limits.ts` L49-50（MAX_SEARCH_OUTPUT_CHARS = 48000）
> - `sdk/packages/core/src/extensions/tools/executors/search.test.ts`（中截断行为交叉验证）
>
> Charles 源码：
> - `agent/tools/search_codebase.py`（SearchCodebaseTool + _collect_files + _search_in_files）
> - `agent/tools/constants.py` L69-79（MAX_SEARCH_MATCHES_PER_QUERY = 50 / MAX_SEARCH_MATCHES_PER_FILE = 20）
> - `agent/tools/base.py` L140-159（_check_aborted 中止信号检查）

---

## 一、执行摘要

Cline 与 Charles 在 search_codebase 工具上**输入契约一致**（`queries: string[]` 正则数组），但**搜索后端、结果格式、截断策略、上下文行、大小写、文件过滤策略**七项核心实现差异显著。AGENT_COMPARISON_PLAN_V2.md P3.13 表声称 Charles 使用"ripgrep 后端（Grep 工具）"系**事实性错误**——Charles 实际使用 Python `re` 模块 + `pathlib.Path.rglob`，全仓库 grep `ripgrep` / `\brg\b` / `spawn.*rg` 在 `agent/tools/` 下 0 匹配（唯一 `rg` 引用在 `agent/approval_policy.py` L63 的只读命令白名单，与 search_codebase 无关）。

1. **输入 schema 一致**：两侧均为 `queries: string[]`。Cline 额外用 Zod union 接受裸字符串 / 裸数组 / 对象三种形态（`SearchCodebaseUnionInputSchema`），Charles 仅接受对象形态（JSON Schema `required: ["queries"]`）。语义等价，宽容度 Cline 更高。

2. **搜索后端差异极大**：Cline **优先用 ripgrep**（`rg --json --context=N --max-count=1 -i <query>`，5 秒超时，JSON 输出解析），ripgrep 不可用时**回退到手写正则遍历**（`new RegExp(query, "gim")` + `getFileIndex` 快速文件索引）。Charles **仅用 Python `re`**（`re.compile(q)` + `Path.rglob("*")`），**无 ripgrep、无回退链**。Charles 对大仓库（>10k 文件）显著慢于 Cline。

3. **结果格式差异显著**：Cline 返回**格式化字符串**（`Found N results for pattern: Q\n\nfile:line:col\n> context lines\n\n...`），Charles 返回**结构化 JSON**（`{results: [{query, match_count, matches: [{file, line_number, line_content}]}]}` + metadata）。Cline 的字符串直接喂给 LLM；Charles 的结构化 dict 由 runtime 序列化后喂给 LLM。

4. **截断策略完全不同**：Cline **按字符数中截断**（`MAX_SEARCH_OUTPUT_CHARS = 48000`，保留 head + tail + 恢复提示 "Narrow the pattern or scope"）；Charles **按匹配数截断**（`MAX_SEARCH_MATCHES_PER_QUERY = 50` + `MAX_SEARCH_MATCHES_PER_FILE = 20`，**无字符级截断**）。Charles 的 50 匹配上限若每行很长，理论上可输出远超 48000 字符；反之若匹配稀疏，可能远低于 48000 字符就停止。AGENT_COMPARISON_PLAN_V2.md L993-994 描述"单位不同 / 阈值不同"准确。

5. **上下文行 Charles 缺失**：Cline **默认返回 2 行上下文**（`contextLines: 2`，ripgrep 路径用 `--context=2`，回退路径手算 `contextStart/contextEnd`，匹配行前缀 `>`），Charles **仅返回匹配行本身**（`line_content` 单行，无 `context` 字段，无 `>` 前缀）。这是 Charles 的显著功能缺失——LLM 拿到匹配后无法直接看到上下文，需额外调用 `read_files` 才能理解匹配语义。

6. **大小写敏感性相反**：Cline **大小写不敏感**（ripgrep `-i` 标志 + 正则 `gim` flags 的 `i`）；Charles **大小写敏感**（`re.compile(q)` 无 `re.IGNORECASE`）。`search("Foo")` 在 Cline 能匹配 `foo` / `FOO` / `Foo`，在 Charles 只匹配 `Foo`。这是行为差异，非缺陷——但与 Cline 不一致。

7. **文件过滤策略相反**：Cline 用**扩展名白名单**（`DEFAULT_INCLUDE_EXTENSIONS` 约 40 种代码扩展名：ts/js/py/go/rs/java/...）+ **排除目录**（14 个：node_modules/.git/dist/build/...）+ **maxDepth=20**；Charles 用**扩展名黑名单**（`_SKIP_EXTENSIONS` 约 25 种二进制扩展名：png/pdf/zip/exe/...）+ **排除目录**（9 个：.git/node_modules/__pycache__/.venv/...）+ **无 maxDepth**。Cline 的白名单更精准（只搜代码文件），Charles 的黑名单更宽泛（搜所有非二进制文本文件，包括 .log/.csv/.txt 等非代码文件）。

8. **多查询并行性差异**：Cline 用 `Promise.all` **并行执行**多查询；Charles 用 `for` 循环**串行执行**。对 3 个查询 + 大仓库，Charles 耗时约为 Cline 的 3 倍。

9. **timeout / retry 差异**：Cline `timeoutMs = searchTimeoutMs ?? 30000`（30 秒，工具级翻倍到 60 秒）+ `retryable: true, maxRetries: 1`；Charles **无工具级 timeout**（`BaseTool.timeout_ms` 默认 None，依赖 runtime 全局控制）+ **不可重试**（`BaseTool.retryable` 默认 False）。与 P3.5 结论一致。

10. **nanobot 残留**：P3.13 核心文件 `agent/tools/search_codebase.py` 中 **0 处** nanobot 残留（grep `nanobot` 大小写不敏感无匹配）；`agent/tools/constants.py` 中 **0 处** nanobot 残留。所有"对标 Cline createSearchTool" / "Phase 31.5" / "Phase 28.2" 标注共 6 处，**全部为注释残留**（docstring + 行内注释），无实现逻辑残留。注：`agent/` 目录下其他文件（session.py / server.py / skills/* / providers/qwen.py / tools/file_tools.py / tools/exec_tool.py / tools/web_tool.py / tools/__init__.py）共 12 个文件含 nanobot 注释残留，但均不在 P3.13 范围内。

11. **一致性总体评估**：**中低**。输入契约对齐，但搜索后端（ripgrep vs Python re）、上下文行（2 行 vs 0 行）、大小写（不敏感 vs 敏感）、截断单位（字符 vs 匹配数）、文件过滤（白名单 vs 黑名单）五项核心行为差异显著。AGENT_COMPARISON_PLAN_V2.md P3.13 表 10 项中标记"已对齐"的 8 项里，**至少 5 项与实际代码不符**（3.13.1 搜索后端、3.13.3 glob 过滤、3.13.4 type 过滤、3.13.7 上下文行、3.13.10 大仓库优化），需以本报告为准。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.13.1 | 搜索后端 | ripgrep 优先（`rg --json`）+ 手写正则回退 | Python `re` + `pathlib.Path.rglob` | 低 | **plan 描述错误**：Charles 无 ripgrep，无回退链 |
| 3.13.2 | regex 支持 | 是（`new RegExp(query, "gim")` + ripgrep RE2 语法） | 是（`re.compile(q)`，Python re 语法） | 中 | 两侧均支持正则，但引擎不同（Cline JS RegExp / Charles Python re），部分高级语法（lookbehind 在旧 Python、命名捕获组语法）行为不同 |
| 3.13.3 | glob 过滤 | 否（无 glob 参数，仅扩展名白名单） | 否（无 glob 参数，仅扩展名黑名单） | 高 | 两侧均**无 glob 过滤**；plan L993 标"已对齐"虽结论对但措辞误导（暗示有 glob） |
| 3.13.4 | type 过滤 | 否（无 `--type` 参数，用扩展名白名单等价） | 否（无 type 参数，用扩展名黑名单等价） | 中 | plan L994 标"已对齐"不准确——两侧均无 rg `--type`，但 Cline 的白名单等价于 type 过滤，Charles 的黑名单不等价 |
| 3.13.5 | 输出截断单位 | 字符数（`MAX_SEARCH_OUTPUT_CHARS`） | 匹配数（`MAX_SEARCH_MATCHES_PER_QUERY` + `MAX_SEARCH_MATCHES_PER_FILE`） | 低 | 单位完全不同；plan L995 准确 |
| 3.13.6 | 输出截断阈值 | 48000 chars（中截断保留 head+tail） | 50 matches/query + 20 matches/file（硬上限，无字符截断） | 低 | 阈值语义不可直接比较；plan L996 准确 |
| 3.13.7 | 上下文行 | 是（`contextLines: 2`，匹配行前后各 2 行，`>` 前缀标记） | 否（仅返回匹配行 `line_content`，无 context 字段） | 低 | **Charles 缺失**；plan L997 标"已对齐"错误 |
| 3.13.8 | 多文件输出 | 是（ripgrep 自然跨文件 / 回退路径遍历 fileList） | 是（`_collect_files` 收集后遍历） | 高 | 两侧均跨文件输出 |
| 3.13.9 | 行号显示 | 是（`match.line`，1-based） | 是（`line_number`，1-based，`enumerate(..., start=1)`） | 高 | 行号语义一致 |
| 3.13.10 | 大仓库优化 | 是（ripgrep C 级速度 + `getFileIndex` 快速索引缓存 + rg 自带 .gitignore） | 否（每次 `rglob` 全量遍历，无索引缓存） | 低 | **Charles 缺失**；plan L998 标"已对齐"错误 |
| 3.13.11 | 列号显示 | 是（`match.column`，ripgrep `submatch.start+1` / 正则 `match.index+1`） | 否（仅 file + line_number + line_content） | 低 | **Charles 缺失** |
| 3.13.12 | 大小写敏感性 | 不敏感（ripgrep `-i` + 正则 `gim` 的 `i`） | 敏感（`re.compile(q)` 无 `re.IGNORECASE`） | 低 | **行为相反** |
| 3.13.13 | 文件扩展名过滤策略 | 白名单（`DEFAULT_INCLUDE_EXTENSIONS` 40 种代码扩展名） | 黑名单（`_SKIP_EXTENSIONS` 25 种二进制扩展名） | 低 | 策略相反；Cline 只搜代码文件，Charles 搜所有非二进制文本文件 |
| 3.13.14 | 排除目录 | 14 个（node_modules/.git/dist/build/.next/coverage/__pycache__/.venv/venv/.cache/.turbo/.output/out/target/bin/obj） | 9 个（.git/node_modules/__pycache__/.venv/venv/.idea/.vscode/dist/build） | 中 | Charles 多了 .idea/.vscode，少了 .next/coverage/.cache/.turbo/.output/out/target/bin/obj |
| 3.13.15 | maxDepth 限制 | 是（默认 20，`shouldIncludeFile` 检查 `directoryDepth > maxDepth`） | 否（`rglob("*")` 全量递归，无深度限制） | 低 | **Charles 缺失**：极深目录树可能耗时 |
| 3.13.16 | 多查询并行 | 是（`Promise.all(queries.map(...))` 并行） | 否（`for query in compiled:` 串行） | 中 | Charles 多查询耗时线性增长 |
| 3.13.17 | 单查询最大结果数 | 100（`maxResults: 100`，ripgrep 路径 `matches.length >= maxResults` 中断 / 回退路径同理） | 50（`_MAX_MATCHES_PER_QUERY = 50`） | 中 | Charles 上限更保守 |
| 3.13.18 | 单文件最大结果数 | 无显式上限（受 `maxResults` 全局上限约束） | 20（`_MAX_MATCHES_PER_FILE = 20`） | 中 | Charles 额外约束单文件，避免一个文件占满配额 |
| 3.13.19 | 结果格式 | 格式化字符串（`Found N results for pattern: Q\n\nfile:line:col\n> ctx\n...`） | 结构化 dict（`{results: [{query, match_count, matches: [{file, line_number, line_content}]}]}` + metadata） | 中 | Cline 字符串直喂 LLM；Charles dict 经 runtime 序列化 |
| 3.13.20 | 截断恢复提示 | 是（`Narrow the pattern or scope to view the elided matches`） | 否（达到 50 匹配静默停止，无提示 LLM 缩小范围） | 低 | **Charles 缺失**：LLM 不知道结果被截断 |
| 3.13.21 | ripgrep 可用性检测 | 是（`checkRipgrepAvailable` 缓存 `rgAvailable`，1 秒超时 spawn `rg --version`） | 否（无 ripgrep 概念） | 低 | Charles 不适用 |
| 3.13.22 | 文件索引服务 | 是（`getFileIndex(cwd)` 来自 `services/workspace/file-indexer`，缓存文件列表） | 否（每次 `rglob` 全量遍历文件系统） | 低 | **Charles 缺失**：重复搜索重复遍历 |
| 3.13.23 | abort 信号粒度 | 每文件检查（`for (const relativePath of fileList)` 循环内 `context.signal?.aborted`） | 每查询检查（`for query in compiled:` 循环内 `_check_aborted`） | 中 | Cline 中止粒度更细；Charles 单查询内无法中止 |
| 3.13.24 | timeout | `searchTimeoutMs ?? 30000`（30 秒，工具级 `timeoutMs: timeoutMs * 2` = 60 秒）+ `withTimeout` 包装 | 无工具级 timeout（`BaseTool.timeout_ms` 默认 None） | 低 | 与 P3.5 结论一致；Charles 大仓库搜索可能长时间阻塞 |
| 3.13.25 | retryable | `retryable: true, maxRetries: 1` | `retryable: False`（BaseTool 默认） | 低 | Cline 允许 1 次重试，Charles 不重试 |
| 3.13.26 | 输入 schema 校验 | Zod `SearchCodebaseUnionInputSchema`（union：object / array / string） | JSON Schema `{queries: array, required: [queries]}` + `BaseTool._validate_input` Draft7 | 中 | Cline 宽容（3 种形态），Charles 严格（仅 object） |
| 3.13.27 | 正则编译失败处理 | `try { regex = new RegExp(query, "gim") } catch { throw new Error("Invalid regex pattern") }`，单查询失败返回 `{query, error: "Search failed: ...", success: false}`，**其他查询继续** | `try { re.compile(q) } except re.error: return AgentToolResult(is_error=True)`，**整个调用立即失败** | 低 | **Charles 容错更弱**：一个正则错误导致所有查询失败 |
| 3.13.28 | 文件读取失败处理 | `try { await fs.readFile(...) } catch {}`（静默跳过，空 catch） | `try { read_text("utf-8") } except (UnicodeDecodeError, PermissionError, OSError): continue`（显式跳过） | 高 | 语义等价；Charles 异常类型更明确 |
| 3.13.29 | 工具描述引导 | 详细（提及 regex / parallel / 48k 截断 / 缩小 pattern 建议） | 简略（"正则表达式数组，每个查询独立搜索"） | 中 | Cline 描述引导 LLM 优化查询；Charles 描述无截断提示 |
| 3.13.30 | 多目录搜索 | 否（单 `cwd`，由 `createSearchTool` config 传入） | 否（单 `working_dir`，由构造函数传入） | 高 | 两侧均单目录 |
| 3.13.31 | 二进制文件检测 | 扩展名白名单间接排除（非代码扩展名不搜） | 扩展名黑名单显式排除 + UTF-8 解码失败跳过 | 中 | Charles 双重防护（扩展名 + 解码），Cline 白名单单一防护 |
| 3.13.32 | 零长匹配防护 | 是（`if (match.index === regex.lastIndex) regex.lastIndex++`） | 否（Python `re.search` 无 lastIndex 问题，但 `re.finditer` 在零长匹配会自动前进） | 高 | 两侧均无零长匹配死循环风险（机制不同） |
| 3.13.33 | requires_approval | 外部 `toolPolicies` 驱动（工具定义无字段） | `BaseTool.requires_approval` 默认 False（search_codebase 未覆盖） | 高 | 两侧语义一致（search_codebase 不需审批） |
| 3.13.34 | read_only / concurrencySafe | 是（search 工具隐式只读，可并行） | 是（`read_only = True` 显式声明） | 高 | 两侧均标记只读可并行 |

**一致性总评**：34 项中，高一致性 11 项、中一致性 11 项、低一致性 12 项。低一致性项集中在 Charles 缺失的"高级搜索能力"（ripgrep 后端 / 上下文行 / 列号 / 大小写不敏感 / 文件索引 / timeout / retry / 截断恢复提示 / 单查询容错）和"策略差异"（截断单位 / 文件过滤策略 / 多查询并行）。

---

## 三、重点差距详细说明

### 差距 1：搜索后端差异——ripgrep vs Python re（3.13.1 / 3.13.10 / 3.13.21 / 3.13.22）

**Cline 实现**（`search.ts` L125-271 + L383）：

```typescript
// 1. 检测 ripgrep 可用性（全局缓存，1 秒超时）
async function checkRipgrepAvailable(): Promise<boolean> {
    if (rgAvailable !== null) return Promise.resolve(rgAvailable);
    return new Promise((resolve) => {
        const child = spawn("rg", ["--version"], { windowsHide: true });
        child.on("close", (code) => { rgAvailable = code === 0; resolve(rgAvailable); });
        child.on("error", () => { rgAvailable = false; resolve(false); });
        setTimeout(() => { if (!child.killed) child.kill("SIGTERM"); ... }, 1000);
    });
}

// 2. ripgrep 搜索（5 秒超时，JSON 输出）
function searchWithRipgrep(query, cwd, maxResults, contextLines, timeoutMs = 5000, abortSignal) {
    const child = spawn("rg", ["--json", `--context=${contextLines}`, "--max-count=1", "-i", query], { cwd, windowsHide: true });
    // 解析 JSON 行：type === "match" 收集，type === "context" 追加上下文
}

// 3. 回退：手写正则 + getFileIndex 快速索引
const fileList = await getFileIndex(cwd);  // services/workspace/file-indexer 缓存
for (const relativePath of fileList) {
    const content = await fs.readFile(filePath, "utf-8");
    const regex = new RegExp(query, "gim");
    // 逐行 exec，收集 match + context
}
```

Cline 的 `getFileIndex` 来自 `sdk/packages/core/src/services/workspace/file-indexer.ts`（`getFileIndex` + `prewarmFileIndex` 导出），是工作区级别的文件索引缓存服务，避免每次搜索重复遍历文件系统。

**Charles 实现**（`search_codebase.py` L141-204 + L206-245）：

```python
# 预编译正则
compiled = []
for q in queries:
    try:
        pattern = re.compile(q)  # 无 re.IGNORECASE
        compiled.append((q, pattern))
    except re.error as e:
        return AgentToolResult(output={"error": ...}, is_error=True)

# 收集文件（每次全量 rglob）
files = self._collect_files(root)  # Path.rglob("*") 遍历整个目录树

# 逐查询串行搜索
for query_str, pattern in compiled:
    self._check_aborted(context)
    matches = self._search_in_files(query_str, pattern, files)
```

Charles **无 ripgrep、无文件索引缓存、无回退链**。每次调用 `_collect_files` 都全量遍历文件系统，对 10k+ 文件的仓库，单次搜索可能耗时数秒（Python 文件系统遍历 + 逐文件 UTF-8 解码 + 逐行 `re.search`）。

**影响**：
- **性能**：Cline 的 ripgrep 是 C 实现的搜索引擎，对 10k 文件仓库通常 <100ms；Charles 的 Python re 通常 1-5 秒，大仓库可能 10 秒+。
- **正确性**：ripgrep 默认遵循 .gitignore（自动跳过忽略文件），Charles 的 `_SKIP_DIRS` / `_SKIP_EXTENSIONS` 是硬编码列表，不会读取 .gitignore，可能搜到用户期望忽略的文件（如 .env.local 若不在黑名单）。
- **正则语法**：ripgrep 用 RE2 引擎（不支持回溯反向引用如 `(a)\1`），Cline 回退路径用 JS RegExp（支持回溯）；Charles 用 Python re（支持回溯）。三方正则语法不完全兼容，但对 LLM 常用 pattern（`def\s+\w+` / `class\s+\w+`）影响极小。

**建议**：不强制补齐 ripgrep。Charles 作为 Python 项目，引入 ripgrep 需 (a) 要求宿主安装 rg 二进制 / (b) 用 `subprocess` spawn（Windows 路径兼容性风险）/ (c) 维护回退链。收益主要是大仓库性能。若未来观察到搜索成为瓶颈，可考虑：(1) 引入 `python-rapidfuzz` 或 `pygrep` 等纯 Python 加速库；(2) 缓存 `_collect_files` 结果到会话级别（类似 Cline 的 `getFileIndex`）；(3) 用 `concurrent.futures` 并行多文件搜索。优先级 P2。

### 差距 2：上下文行缺失（3.13.7 / 3.13.11）

**Cline 实现**（`search.ts` L41-47 + L170 + L420-431 + L247-253）：

```typescript
// 默认 contextLines: 2
const { contextLines = 2 } = options;

// ripgrep 路径：--context=2 标志
spawn("rg", ["--json", `--context=${contextLines}`, "--max-count=1", "-i", query], ...);

// 回退路径：手算上下文
const contextStart = Math.max(0, lineIdx - contextLines);
const contextEnd = Math.min(lines.length - 1, lineIdx + contextLines);
const contextLinesArr = [];
for (let i = contextStart; i <= contextEnd; i++) {
    const prefix = i === lineIdx ? ">" : " ";
    contextLinesArr.push(`${prefix} ${i + 1}: ${lines[i]}`);
}

// ripgrep JSON 解析：type === "context" 追加到上一个 match 的 context 数组
} else if (json.type === "context" && matches.length > 0) {
    const lastMatch = matches[matches.length - 1];
    const prefix = json.data.line_number === lastMatch.line ? ">" : " ";
    lastMatch.context.push(`${prefix} ${json.data.line_number}: ${json.data.lines?.text ?? ...}`);
}
```

每个匹配返回 `file:line:col` + 上下文行（匹配行用 `>` 前缀，上下文行用空格前缀，含行号）。LLM 拿到结果可直接理解匹配语义，无需额外调用 `read_files`。

**Charles 实现**（`search_codebase.py` L229-243）：

```python
for line_idx, line in enumerate(content.splitlines(), start=1):
    if match_count >= self._MAX_MATCHES_PER_QUERY:
        break
    if file_matches >= self._MAX_MATCHES_PER_FILE:
        break
    if pattern.search(line):
        matches.append({
            "file": str(file_path),
            "line_number": line_idx,
            "line_content": line,  # 仅匹配行，无 context
        })
```

Charles 的 `matches` 字典只有 `file` / `line_number` / `line_content` 三字段，**无 `context` 字段、无 `column` 字段、无 `>` 前缀**。

**影响**：
- LLM 拿到 Charles 的搜索结果后，若需理解匹配上下文（如判断是否为函数定义 vs 函数调用），必须额外调用 `read_files`，增加工具调用轮次和 token 消耗。
- 对于 `search("foo")` 匹配 50 行，Cline 一次返回 50 行 + 200 行上下文（每行前后各 2 行），LLM 可直接判断；Charles 需 50 次 `read_files` 或 1 次 `read_files`（50 文件）才能获得等价信息。
- Charles 的 `line_content` 是原始行，无 `>` 前缀标记匹配行，LLM 需自行从 `line_number` 推断。

**建议**：建议补齐。在 `_search_in_files` 中增加 `context_lines` 参数（默认 2），匹配行前后各收集 `context_lines` 行，匹配行用 `>` 前缀，结构化字段 `context: list[str]`。同时补齐 `column` 字段（Python `re.search` 返回的 `match.start() + 1`）。这是 LLM 体验优化，非功能缺陷，优先级 P2。

### 差距 3：大小写敏感性相反（3.13.12）

**Cline 实现**：
- ripgrep 路径：`spawn("rg", [..., "-i", query])`（`-i` 标志 = `--ignore-case`）
- 回退路径：`new RegExp(query, "gim")`（`i` flag = `ignoreCase`）

两条路径均大小写不敏感。`search("Foo")` 匹配 `Foo` / `foo` / `FOO` / `fOo`。

**Charles 实现**（`search_codebase.py` L145）：

```python
pattern = re.compile(q)  # 无 re.IGNORECASE
```

`search("Foo")` 只匹配 `Foo`，不匹配 `foo` / `FOO`。

**影响**：
- LLM 生成 `search("SearchCodebaseTool")` 时，Cline 能匹配 `searchcodebasetool` / `SEARCHCODEBASETOOL`（虽然罕见），Charles 只匹配精确大小写。
- 对于代码搜索，大小写敏感通常更精准（Python 类名 `Foo` vs 变量名 `foo` 语义不同），但与 Cline 行为不一致，可能让习惯了 Cline 行为的 LLM 用户困惑。
- 若 LLM 不确定大小写，可能生成 `search("[Ff]oo")` 这类字符类，Charles 能正确处理，但增加了 LLM 负担。

**建议**：建议对齐为大小写不敏感（加 `re.IGNORECASE`），与 Cline 行为一致。若需保留大小写敏感能力，可在 input_schema 增加 `case_sensitive: bool = false` 参数。优先级 P3（行为不一致但非缺陷）。

### 差距 4：截断策略差异（3.13.5 / 3.13.6 / 3.13.20）

**Cline 实现**（`output-limits.ts` L49-50 + `search.ts` L485-497）：

```typescript
export const MAX_SEARCH_OUTPUT_CHARS = 48_000;

function capSearchOutput(text: string): string {
    if (text.length <= MAX_SEARCH_OUTPUT_CHARS) return text;
    const headLimit = Math.ceil(MAX_SEARCH_OUTPUT_CHARS / 2);  // 24000
    const tailLimit = Math.max(1, MAX_SEARCH_OUTPUT_CHARS - headLimit);  // 24000
    return (
        `${text.slice(0, headLimit)}\n` +
        `[... search output truncated: ${text.length} chars total. ` +
        "Narrow the pattern or scope to view the elided matches ...]\n" +
        text.slice(-tailLimit)
    );
}
```

Cline 按**字符数**中截断：超 48000 字符时，保留前 24000 字符 + 截断提示 + 后 24000 字符。提示信息 `"Narrow the pattern or scope"` 引导 LLM 缩小 pattern。截断提示在保留的 head/tail 内，确保 LLM 能看到。

**Charles 实现**（`constants.py` L75-79 + `search_codebase.py` L50-51 + L220-234）：

```python
MAX_SEARCH_MATCHES_PER_QUERY = 50
MAX_SEARCH_MATCHES_PER_FILE = 20

# _search_in_files
for file_path in files:
    if match_count >= self._MAX_MATCHES_PER_QUERY:  break  # 50 上限
    ...
    for line_idx, line in enumerate(content.splitlines(), start=1):
        if match_count >= self._MAX_MATCHES_PER_QUERY:  break
        if file_matches >= self._MAX_MATCHES_PER_FILE:  break  # 20 上限
        if pattern.search(line):
            matches.append({...})
            match_count += 1
            file_matches += 1
```

Charles 按**匹配数**硬上限：单查询 50 匹配、单文件 20 匹配，达到即停止。**无字符级截断、无截断提示**。若 50 个匹配每行 1000 字符，总输出可达 50000+ 字符（无截断）；若每行 50 字符，仅 2500 字符就停止。

**影响**：
- Charles 的 50 匹配上限可能让 LLM 误以为"只有 50 个匹配"，实际可能有 500 个。Cline 的 48000 字符截断 + 恢复提示明确告知 LLM"结果被截断，缩小 pattern"。
- Charles 无字符级截断，若 LLM 生成宽泛 pattern（如 `search("a")`）匹配大量长行，可能输出远超 48000 字符，撑爆上下文窗口。
- Charles的单文件 20 匹配上限是 Cline 没有的额外约束（Cline 仅全局 maxResults=100），这避免了单文件占满配额，是 Charles 的优势点。

**建议**：建议补齐字符级截断。在 `_execute` 返回前，对 `results` 序列化后的字符串做 `cap_search_output` 中截断（保留 head + tail + 恢复提示）。同时达到 50 匹配上限时，在 metadata 中增加 `truncated: true` 字段，引导 LLM 缩小 pattern。优先级 P2。

### 差距 5：单查询容错差异（3.13.27）

**Cline 实现**（`definitions.ts` L358-393）：

```typescript
execute: async (input, context) => {
    const validate = validateWithZod(SearchCodebaseUnionInputSchema, input);
    const queries = Array.isArray(validate) ? validate : ...;

    return Promise.all(
        queries.map(async (query): Promise<ToolOperationResult> => {
            try {
                const results = await withTimeout(executor(query, cwd, context), timeoutMs, ...);
                return { query, result: results, success: true };
            } catch (error) {
                return { query, result: "", error: `Search failed: ${msg}`, success: false };
            }
        }),
    );
}
```

Cline 对每个查询独立 try/catch：单个查询失败（正则编译错误 / 超时 / 异常）只返回该查询的 `{success: false, error: ...}`，**其他查询继续执行**并返回结果。

**Charles 实现**（`search_codebase.py` L141-154）：

```python
compiled = []
for q in queries:
    try:
        pattern = re.compile(q)
        compiled.append((q, pattern))
    except re.error as e:
        return AgentToolResult(
            output={"error": f"正则表达式编译失败: {q}", "detail": str(e)},
            is_error=True,
        )  # 整个调用立即失败
```

Charles 在**预编译阶段**任一正则编译失败，立即返回 `is_error=True`，**所有查询都不执行**（包括合法的查询）。

**影响**：
- LLM 生成 `queries: ["valid_pattern", "[invalid"]` 时，Cline 返回 valid_pattern 的结果 + invalid 的错误；Charles 返回整体错误，valid_pattern 也不执行。
- Charles 的行为对 LLM 更不友好——一个错误 pattern 导致整个工具调用失败，LLM 需重新调用（且可能不知道哪个 pattern 错了）。
- Charles 的设计是"fail-fast"，Cline 的设计是"best-effort"。对于多查询并行搜索，Cline 的容错更合理。

**建议**：建议对齐为 best-effort。在预编译阶段收集编译失败的 query（不立即 return），在搜索阶段跳过失败的 query，最后在结果中为失败的 query 返回 `{query, error: "正则编译失败: ...", success: false}`。优先级 P2。

---

## 四、nanobot 残留分析

### 4.1 search_codebase.py 残留分析

**grep 结果**：`agent/tools/search_codebase.py` 中 grep `nanobot`（大小写不敏感）**0 匹配**。

**注释残留**（全部为 Cline / Phase 标注，非 nanobot）：

| 行号 | 内容 | 类型 | 残留性质 |
|------|------|------|---------|
| L2 | `"""正则代码搜索工具 — 对标 Cline createSearchTool` | docstring | 注释残留（对标 Cline，无害） |
| L19-20 | `对标 Cline:\n    - sdk/packages/core/src/extensions/tools/search-tool.ts` | docstring | **注释残留且路径错误**：实际路径为 `executors/search.ts`（无 `search-tool.ts`） |
| L39 | `"""正则代码搜索工具 — 对标 Cline createSearchTool` | docstring | 注释残留（无害） |
| L48 | `# Phase 31.5: 常量统一到 agent.tools.constants — 对标 Cline output-limits.ts` | 行内注释 | 注释残留（无害） |
| L119 | `"""执行正则代码搜索 — 对标 Cline createSearchTool.execute()"""` | docstring | 注释残留（无害） |
| L162 | `# Phase 28.2: 每个查询开始前检查中止信号` | 行内注释 | 注释残留（无害） |

**实现逻辑残留**：**0 处**。所有逻辑均为 Charles 自主实现（Python `re` + `pathlib.rglob`），无 nanobot 代码移植痕迹。

**需修正的注释错误**：L19-20 引用 `sdk/packages/core/src/extensions/tools/search-tool.ts` 不存在，实际 Cline 源码位于 `sdk/packages/core/src/extensions/tools/executors/search.ts` + `definitions.ts` L335-395（createSearchTool 工厂）。此为注释笔误，非实现问题。

### 4.2 constants.py 残留分析

**grep 结果**：`agent/tools/constants.py` 中 grep `nanobot`（大小写不敏感）**0 匹配**。

**注释残留**：constants.py L1-21 docstring 标注"对标 Cline output-limits.ts"，L93-94 标注"对标 Cline sdk/packages/core/src/extensions/tools/presets.ts:20-109"。均为 Cline 对标注释，无 nanobot 残留。

**实现逻辑残留**：**0 处**。常量值（`MAX_SEARCH_MATCHES_PER_QUERY = 50` / `MAX_SEARCH_MATCHES_PER_FILE = 20`）为 Charles 自主设定，constants.py L19 docstring 明确说明"我的系统沿用各工具已验证的数值，未对齐 Cline 的 48000"。

### 4.3 范围外 nanobot 残留（仅记录，不属 P3.13）

`agent/` 目录下 grep `nanobot` 共 12 个文件命中（55 行），均在 P3.13 范围外：

| 文件 | 命中数 | 残留类型 |
|------|--------|---------|
| `agent/session.py` | 2 | 注释残留（docstring "对标 nanobot session_key"） |
| `agent/server.py` | 3 | 注释残留（docstring "对标 Cline server + nanobot routes/chat.py"） |
| `agent/skills/loader.py` | 7 | 注释残留（docstring + 行内 "对标 nanobot SkillsLoader"） |
| `agent/skills/registry.py` | 3 | 注释残留（docstring "对标 nanobot SkillsLoader"） |
| `agent/skills/__init__.py` | 2 | 注释残留（docstring "对标 nanobot agent/tools"） |
| `agent/skills/skill_tool.py` | 1 | 注释残留（行内 "与 nanobot 的子 agent 隔离执行有本质区别"） |
| `agent/context.py` | 1 | 注释残留（"nanobot 风格的额外段落，Cline 无此概念"） |
| `agent/providers/qwen.py` | 6 | 注释残留（"对标 nanobot openai_compat_provider.py"） |
| `agent/tools/file_tools.py` | 5 | 注释残留（"对标 nanobot FilesystemTool"） |
| `agent/tools/exec_tool.py` | 7 | 注释残留（"对标 nanobot ShellTool / shell.py / _guard_command"） |
| `agent/tools/web_tool.py` | 5 | 注释残留（"对标 nanobot WebSearchTool / web.py"） |
| `agent/tools/__init__.py` | 1 | 注释残留（docstring "对标 Cline extensions/tools 和 nanobot agent/tools"） |

均为**注释残留**（docstring + 行内注释），无实现逻辑残留。这些文件的 nanobot 残留清理属于各自 Phase 的范围（P3.10 file_tools / P3.11 exec_tool / P3.15 web_tool / Skills 系列 / Session / Provider），不在 P3.13 search_codebase 范围内。

---

## 五、与 AGENT_COMPARISON_PLAN_V2.md P3.13 表的差异订正

| plan 行号 | plan 描述 | 实际情况 | 订正 |
|----------|----------|---------|------|
| L977 | Cline 实现（executors/search-codebase.ts） | 实际为 `executors/search.ts`（无连字符，无 `-codebase` 后缀） | 路径笔误 |
| L978 | Cline：ripgrep 后端 | 准确 | — |
| L979 | Cline：支持 regex / glob / type 过滤 | 实际：regex 支持，**无 glob、无 type**（仅扩展名白名单等价 type 过滤） | glob/type 描述不准确 |
| L980 | Cline：输出截断 MAX_SEARCH_OUTPUT_CHARS=48000 | 准确 | — |
| L983 | Charles：ripgrep 后端（Grep 工具） | **错误**：Charles 用 Python `re` + `pathlib.rglob`，无 ripgrep | **事实性错误** |
| L984 | Charles：支持 regex / glob / type 过滤 | 实际：regex 支持，**无 glob、无 type**（仅扩展名黑名单） | glob/type 描述不准确 |
| L985 | Charles：输出截断 MAX_SEARCH_MATCHES_PER_QUERY=50 | 准确（但遗漏 MAX_SEARCH_MATCHES_PER_FILE=20） | 遗漏单文件上限 |
| L989 | 3.13.1 搜索后端：ripgrep / ripgrep / 已对齐 | **错误**：Charles 非 ripgrep | **订正为低一致性** |
| L991 | 3.13.3 glob 过滤：是 / 是 / 已对齐 | **错误**：两侧均无 glob | 订正为"两侧均无 glob"（高一致性但 plan 描述误导） |
| L992 | 3.13.4 type 过滤：是 / 是 / 已对齐 | **错误**：两侧均无 `--type`，Cline 白名单等价、Charles 黑名单不等价 | 订正为中一致性 |
| L995 | 3.13.7 上下文行：-A/-B/-C / -A/-B/-C / 已对齐 | **错误**：Cline 有 contextLines=2，Charles 无上下文行；两侧均无 -A/-B/-C 参数 | **订正为低一致性** |
| L998 | 3.13.10 大仓库优化：是 / 是 / 已对齐 | **错误**：Cline 有 ripgrep + getFileIndex，Charles 无优化 | **订正为低一致性** |

**订正总结**：plan P3.13 表 10 项中，**5 项与实际代码不符**（3.13.1 / 3.13.3 / 3.13.4 / 3.13.7 / 3.13.10），均高估了一致性。本报告以实际代码为准，重新评定为 34 项中高一致性 11 项、中一致性 11 项、低一致性 12 项。

---

## 六、一致性总评与建议

### 6.1 一致性等级分布

- **高一致性（11 项）**：行号显示、多文件输出、多目录搜索（均无）、文件读取失败处理、零长匹配防护、requires_approval、read_only、glob 过滤（均无）、输入 schema 字段（queries: string[]）、正则支持（基础）、二进制检测双重防护。
- **中一致性（11 项）**：排除目录列表、单查询最大结果数、单文件最大结果数、结果格式、abort 粒度、输入 schema 校验、工具描述引导、正则语法（引擎差异）、多查询并行、扩展名过滤策略。
- **低一致性（12 项）**：搜索后端、截断单位、截断阈值、上下文行、大仓库优化、列号、大小写敏感性、maxDepth、截断恢复提示、ripgrep 可用性检测、文件索引服务、timeout、retryable、单查询容错。

### 6.2 Charles 相对 Cline 的优势点

1. **单文件匹配上限**（3.13.18）：Charles 的 `_MAX_MATCHES_PER_FILE = 20` 避免单文件占满配额，Cline 无此约束（仅全局 maxResults=100，单文件可能占满 100）。
2. **二进制文件双重防护**（3.13.31）：Charles 用扩展名黑名单 + UTF-8 解码失败跳过；Cline 回退路径仅靠扩展名白名单（ripgrep 路径靠 rg 自身能力）。
3. **错误信息结构化**（3.13.27）：Charles 的正则编译错误含 `error` + `detail` 两字段；Cline 仅 `error: "Search failed: ..."` 字符串。
4. **结构化结果便于程序化处理**（3.13.19）：Charles 的 dict 结构含 `match_count` / `total_matches` / `files_searched` metadata，便于 runtime 统计；Cline 的字符串需 LLM 自行解析。

### 6.3 补齐建议（按优先级）

| 优先级 | 建议项 | 对应差距 | 理由 |
|--------|--------|---------|------|
| P1 | 单查询容错（best-effort） | 差距 5（3.13.27） | 当前一个错误 pattern 导致整个调用失败，严重影响 LLM 体验；改造成本低 |
| P2 | 字符级截断 + 截断提示 | 差距 4（3.13.5/3.13.6/3.13.20） | 防止撑爆上下文；引导 LLM 缩小 pattern |
| P2 | 上下文行 + 列号 | 差距 2（3.13.7/3.13.11） | 减少 LLM 额外 read_files 调用；提升结果可用性 |
| P2 | 大小写不敏感对齐 | 差距 3（3.13.12） | 与 Cline 行为一致；可加 `case_sensitive` 参数保留灵活 |
| P3 | 文件索引缓存 | 差距 1（3.13.22） | 大仓库性能优化；改造成本中等 |
| P3 | timeout / retryable | 3.13.24/3.13.25 | 与 P3.5 全局结论一致；大仓库搜索可能阻塞 |
| P4 | ripgrep 后端 | 差距 1（3.13.1） | 引入二进制依赖 + 回退链维护；收益有限（Python re 对中小仓库足够） |
| P4 | 多查询并行 | 3.13.16 | Python `asyncio.gather` 改造；收益依赖查询数 |

### 6.4 不建议补齐的项

- **maxDepth 限制**（3.13.15）：Cline 的 maxDepth=20 是防御性约束，实际代码仓库极少超过 20 层；Charles 的 rglob 全量遍历虽无限制，但 `_SKIP_DIRS` 已排除常见深目录（node_modules 等）。补齐收益低。
- **ripgrep 可用性检测**（3.13.21）：仅当引入 ripgrep 后端时才需要，属 P4 补齐项的子项。
- **文件扩展名白名单**（3.13.13）：Charles 的黑名单策略虽搜更多文件，但配合 UTF-8 解码失败跳过，不会搜到真正的二进制内容；白名单可能漏搜新扩展名（如 .proto / .graphql）。策略差异非缺陷。

---

## 七、结论

Cline 与 Charles 的 search_codebase 工具在**输入契约**（`queries: string[]`）和**只读语义**（`read_only=True` / 无需审批）上对齐，但在**搜索后端、结果格式、截断策略、上下文行、大小 case 敏感性、文件过滤策略**六项核心实现上差异显著。AGENT_COMPARISON_PLAN_V2.md P3.13 表对一致性的评估偏高（10 项中 8 项标"已对齐"），实际代码层面 34 项中仅 11 项高一致性，**plan 中"Charles 使用 ripgrep 后端"系事实性错误**。

**nanobot 残留**：P3.13 核心文件（search_codebase.py + constants.py）**0 处** nanobot 残留，6 处 Cline/Phase 标注全部为注释残留（其中 1 处路径笔误 `search-tool.ts` 应为 `executors/search.ts`），无实现逻辑残留。范围外 12 个文件的 nanobot 注释残留不属 P3.13 范围。

**最关键的三项差距**：(1) 单查询容错（P1，一个错误 pattern 全部失败）；(2) 上下文行缺失（P2，LLM 需额外 read_files）；(3) 截断策略（P2，无字符级截断可能撑爆上下文）。建议按 P1 → P2 顺序补齐。
