# Phase 3.21 web_tool（WebSearchTool）实现对比

> 对比范围：Cline `sdk/packages/core/src/extensions/tools/`（确认无独立 WebSearchTool，仅有 `web-fetch.ts` URL 抓取 + `search.ts` 代码库搜索 + MCP 服务器接入搜索能力） 与 Charles `agent/tools/web_tool.py`（`WebSearchTool` 独立网络搜索工具，基于 DuckDuckGo）的实现差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/executors/web-fetch.ts`（URL 抓取，非搜索）
> - `sdk/packages/core/src/extensions/tools/executors/search.ts`（代码库 ripgrep/regex 搜索，非网络搜索）
> - `sdk/packages/core/src/extensions/tools/executors/index.ts` L91-101（`createDefaultExecutors` 装配清单，无 web-search executor）
> - `sdk/packages/core/src/extensions/tools/types.ts` L201-263（`DefaultToolName` 枚举仅含 `search_codebase` / `fetch_web_content`，无 `web_search`）
>
> Charles 源码：
> - `agent/tools/web_tool.py` L1-174（`WebSearchTool` 完整实现，DuckDuckGo 后端）
> - `agent/tools/base.py` L36-103（`BaseTool` 基类：`read_only` / `requires_approval` / `timeout_ms` / `retryable` / `max_retries` 默认值）
> - `agent/tools/__init__.py` L45 / L91（`WebSearchTool` 导入与默认装配）
> - `agent/approval_policy.py` L36-43（`web_search` 在只读自动批准白名单中）
> - `agent/tools/fetch_web_content.py`（Charles 另有 `FetchWebContentTool`，对标 Cline `web-fetch.ts`，不属于本对比范围）

---

## 一、执行摘要

Cline 与 Charles 在"网络搜索"这一能力上**存在结构性差异**：Cline **不提供独立的网络搜索工具**，网络信息获取通过 `fetch_web_content`（URL 抓取）+ MCP 服务器接入搜索能力组成；Charles **提供了独立的 `WebSearchTool`**，内置 DuckDuckGo 搜索后端，无需 API Key 即可直接使用。

1. **工具存在性差异**：Cline 的 `DefaultToolName` 枚举（`types.ts` L228-230）仅含 `search_codebase` / `fetch_web_content` / `read_files` / `run_commands` / `list_files` / `apply_patch` / `editor` / `ask_question` / `submit_and_exit` 等 9 个工具，**无 `web_search`**。Cline 的 `createDefaultExecutors`（`executors/index.ts` L91-101）也只装配 `readFile` / `search` / `bash` / `webFetch` / `applyPatch` / `editor` 六个 executor，**无 web-search executor**。Charles 的 `create_default_tools`（`__init__.py` L91）默认装配 `WebSearchTool()`，并暴露给 LLM 调用。

2. **搜索后端差异**：Charles `WebSearchTool` 使用 **DuckDuckGo**（通过 `ddgs` 库的 `DDGS.text()` 接口），在线程池中执行同步搜索；Cline 无内置搜索后端，需用户自行接入 MCP 搜索服务器（如 Brave Search MCP / Tavily MCP 等）。
   - **注意**：AGENT_COMPARISON_PLAN_V2.md 中提到"搜索后端：AkShare / 其他"以及"输入 schema：query / num_results / source"，经核查 **Charles 实际实现并无 `source` 字段、也非 AkShare 后端**，仅为 DuckDuckGo 单一后端，计划描述与实际实现不符，本报告以实际实现为准。

3. **结果格式差异**：Charles 返回纯文本格式化结果（标题 + URL + 摘要，逐条编号）；Cline 无原生搜索结果格式（取决于 MCP 服务器返回）。

4. **结果截断差异**：Charles **无显式字符数截断**（仅通过 `num_results` 限制条数，最大 10 条），单条摘要长度依赖 DuckDuckGo 返回；Cline `web-fetch.ts` 有 50000 字符截断（`content.slice(0, 50000)`），`search.ts` 有 `MAX_SEARCH_OUTPUT_CHARS` 中间截断。Charles `WebSearchTool` 的截断策略**与 Cline 两个工具都不对齐**。

5. **错误处理差异**：Charles `WebSearchTool` 用 try/except 捕获异常，返回 `AgentToolResult(output={"error": ...}, is_error=True)`；Cline `web-fetch.ts` 直接 throw 错误（由 runtime 统一捕获）。Charles 还特判 `ImportError`（ddgs 库未安装时返回安装提示），Cline 无等价机制（Cline 不依赖外部搜索库）。

6. **nanobot 残留**：`web_tool.py` 共 **7 处 nanobot 注释残留**（docstring 与行内注释中"对标 nanobot"的引用），**0 处实现逻辑残留**（无 nanobot 模块导入、无 nanobot 类继承、无 nanobot 函数调用）。残留均为文档性引用，不影响运行时行为。

7. **read_only / requires_approval / timeout_ms**：Charles `WebSearchTool` 设置 `read_only = True`（L67-68）、未覆盖 `requires_approval`（继承 `BaseTool` 默认 `False`）、`timeout_ms = 30_000`（L71-73）；此外 `retryable = True` / `max_retries = 2`（L76-83）。Cline 无对应工具，无对比项。

8. **一致性总体评估**：**低**（工具存在性层面 Charles 额外）。Charles 多出 `WebSearchTool` 是量化场景的特化需求（市场信息、新闻、公司公告搜索），与 Cline "搜索能力由 MCP 承担"的设计哲学不同。是否应改为 `fetch_web_content + MCP 搜索` 架构需结合 Charles 实际使用场景评估。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 3.21.1 | 工具存在性 | 无独立 WebSearchTool（`DefaultToolName` 枚举无 `web_search`） | 有 `WebSearchTool`（`web_tool.py` L27） | 低 | Charles 额外提供 |
| 3.21.2 | 工具名称 | N/A | `"web_search"`（L37） | N/A | Charles 独有 |
| 3.21.3 | 工具描述 | N/A | "网络搜索。获取最新市场信息、新闻、公司公告等..."（L41-45） | N/A | Charles 量化场景特化描述 |
| 3.21.4 | 输入 schema：query | N/A | `{"type": "string", "description": "搜索关键词"}`，`required: ["query"]`（L52-55 / L63） | N/A | Charles 必填 |
| 3.21.5 | 输入 schema：num_results | N/A | `{"type": "integer", "minimum": 1, "maximum": 10}`，可选默认 5（L56-61） | N/A | Charles 独有 |
| 3.21.6 | 输入 schema：source | N/A | **不存在**（计划描述与实际不符） | N/A | Charles 实际无 source 字段 |
| 3.21.7 | 搜索后端 | N/A（依赖 MCP 服务器） | DuckDuckGo（`ddgs.DDGS.text()`，L130-137） | N/A | Charles 实际为 DuckDuckGo，非 AkShare |
| 3.21.8 | API Key 需求 | N/A（取决于 MCP 服务器） | 无需 API Key（L13 注释"对标 nanobot fallback 方案"） | N/A | Charles 选择 DuckDuckGo 即为免 Key |
| 3.21.9 | 搜索执行方式 | N/A | 同步接口在线程池执行（`asyncio.to_thread`，L142 / L145） | N/A | Charles 将同步 DDGS 包装为异步 |
| 3.21.10 | 结果字段 | N/A | `title` / `url` / `content`（L132-136） | N/A | Charles 从 DDGS 返回提取 |
| 3.21.11 | URL 字段提取逻辑 | N/A | `r.get("href", r.get("link", ""))` 双键兜底（L134） | N/A | Charles 兼容 DDGS 不同版本返回字段 |
| 3.21.12 | 摘要字段提取逻辑 | N/A | `r.get("body", r.get("snippet", ""))` 双键兜底（L135） | N/A | Charles 兼容 DDGS 不同版本返回字段 |
| 3.21.13 | 结果格式 | N/A | 纯文本：标题行 + URL 行 + 摘要行，逐条编号（L166-172） | N/A | Charles 文本格式化 |
| 3.21.14 | 结果截断 | N/A | **无显式字符截断**，仅靠 `num_results` 限制条数（最大 10） | N/A | Charles 截断策略与 Cline 其他工具不一致 |
| 3.21.15 | 空结果处理 | N/A | 返回 `"未找到搜索结果: {query}"`（L163） | N/A | Charles 友好提示 |
| 3.21.16 | 错误处理 | N/A | try/except 捕获，返回 `AgentToolResult(output={"error": ...}, is_error=True)`（L102-106） | N/A | Charles 不抛异常，返回错误结果 |
| 3.21.17 | ImportError 特判 | N/A | ddgs 未安装时返回安装提示（L118-122） | N/A | Charles 库缺失友好提示 |
| 3.21.18 | AbortedError 传播 | N/A | 中止异常向上传播，由 runtime 处理（L99-101 / L152-154） | N/A | Charles 支持用户中止 |
| 3.21.19 | 中止信号检查 | N/A | 搜索开始前 `_check_aborted`（L94）+ to_thread 与 abort_signal.wait 竞速（L145-160） | N/A | Charles 即时中止 |
| 3.21.20 | nanobot 注释残留 | N/A | 7 处（L2 / L9 / L10 / L13 / L28 / L111 / L165） | 低 | 均为 docstring / 行内注释引用 |
| 3.21.21 | nanobot 实现逻辑残留 | N/A | 0 处（无 nanobot 导入 / 继承 / 调用） | 高 | 已完全清理实现层 |
| 3.21.22 | read_only 属性 | N/A | `True`（L67-68） | N/A | Charles 标记为只读 |
| 3.21.23 | requires_approval | N/A | `False`（继承 `BaseTool` 默认，未覆盖） | N/A | Charles 网络搜索无需审批 |
| 3.21.24 | timeout_ms | N/A | `30_000`（30 秒，L71-73） | N/A | Charles 显式设置 |
| 3.21.25 | retryable | N/A | `True`（L76-78） | N/A | Charles 网络瞬时故障可重试 |
| 3.21.26 | max_retries | N/A | `2`（L80-83） | N/A | Charles 最多重试 2 次 |
| 3.21.27 | 自动审批白名单 | N/A（无对应工具） | `web_search` 在 `APPROVE_FREE` 白名单中（`approval_policy.py` L39） | N/A | Charles 自动批准只读搜索 |
| 3.21.28 | 上下文 prompt 引用 | N/A | `context.py` L760 / L766 引导 LLM 调用 `web_search` | N/A | Charles 在系统 prompt 中主动引导使用 |
| 3.21.29 | plan 模式可用性 | N/A（无对应工具） | plan 模式下可用（不在 `tool_policies` 禁用列表） | N/A | Charles plan 模式允许探索性搜索 |

**一致性总评**：29 项中，因 Cline 无对应工具，**所有项均为 N/A 或 Charles 独有**。核心结论是 Charles 额外提供了独立的网络搜索能力，Cline 需通过 MCP 服务器接入等价能力。

---

## 三、重点差距详细说明

### 差距 1：工具存在性差异（3.21.1）

**Cline 实现**：

Cline 的工具注册体系（`types.ts` L228-230 的 `DefaultToolName` 联合类型）枚举如下 9 个内置工具：

```typescript
| "read_files" | "run_commands" | "list_files" | "apply_patch"
| "editor" | "search_codebase" | "fetch_web_content"
| "ask_question" | "submit_and_exit"
```

其中 `search_codebase` 是**代码库搜索**（`search.ts` 使用 ripgrep / regex），`fetch_web_content` 是 **URL 抓取**（`web-fetch.ts` 使用 native fetch），**均非网络搜索**。`createDefaultExecutors`（`executors/index.ts` L91-101）装配清单也无 web-search executor。

Cline 的网络搜索能力需通过 MCP 服务器接入（用户配置 Brave Search MCP / Tavily MCP / SerpAPI MCP 等），由 `use_mcp_tool` 工具调用，搜索结果格式由 MCP 服务器决定。

**Charles 实现**：

Charles 在 `create_default_tools`（`__init__.py` L91）默认装配 `WebSearchTool()`，所有场景下 LLM 都能直接调用 `web_search` 工具，无需额外配置 MCP 服务器。搜索后端为 DuckDuckGo（`web_tool.py` L130），无需 API Key。

**影响**：
- Charles 的方式开箱即用，适合量化场景下频繁的市场信息 / 新闻 / 公司公告搜索。
- Cline 的方式更灵活（可选不同搜索后端），但需要用户自行配置 MCP 服务器。
- 两者设计哲学不同：Cline "能力由 MCP 承担"，Charles "核心场景能力内置"。

**建议**：不强制改为 `fetch_web_content + MCP 搜索`。Charles 的 `WebSearchTool` 满足量化场景的即时搜索需求，且 DuckDuckGo 免 API Key 降低部署门槛。若未来需要支持更多搜索后端（如 AkShare 财经搜索、Tavily AI 搜索），可考虑在 `WebSearchTool` 中引入 `source` 字段或通过 MCP 接入。

### 差距 2：搜索后端单一性（3.21.7 / 3.21.8）

**Charles 实现**（`web_tool.py` L116-137）：

```python
from ddgs import DDGS

def _sync_search() -> list[dict[str, str]]:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=n):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", r.get("link", "")),
                "content": r.get("body", r.get("snippet", "")),
            })
    return results
```

Charles 仅支持 DuckDuckGo 单一后端，无 `source` 字段切换后端。**计划描述的"AkShare / 其他"后端、`source` 字段在实际实现中不存在**。

**影响**：
- DuckDuckGo 对中文搜索支持较好，但财经数据 / 上市公司公告等垂直领域覆盖可能不如 AkShare / Tavily 等专业后端。
- 单一后端无冗余，DuckDuckGo 服务不可用时搜索能力完全丧失（虽有 `retryable=True` / `max_retries=2` 缓解瞬时故障）。

**建议**：保留 DuckDuckGo 作为默认后端。若量化场景需要财经数据搜索，可考虑未来扩展 `source` 字段（如 `"duckduckgo" | "akshare" | "tavily"`），但当前不阻塞。

### 差距 3：结果截断策略缺失（3.21.14）

**Charles 实现**（`web_tool.py` L162-174）：

```python
if not items:
    return f"未找到搜索结果: {query}"

lines = [f"搜索结果: {query}", f"共 {len(items)} 条结果", ""]
for i, item in enumerate(items, 1):
    lines.append(f"[{i}] {item['title']}")
    lines.append(f"    URL: {item['url']}")
    if item["content"]:
        lines.append(f"    摘要: {item['content']}")
    lines.append("")

return "\n".join(lines)
```

Charles **无显式字符数截断**，仅通过 `num_results`（最大 10）限制条数。若 DuckDuckGo 返回的摘要过长（如长篇新闻摘要），单条摘要可能数百字符，10 条结果累计可能超过 5000 字符，存在撑爆 LLM 上下文的风险。

**Cline 对比**：
- Cline `web-fetch.ts` L231：`content.slice(0, 50000)` 显式截断到 50000 字符，超出时追加 `[Content truncated: showing first 50000 of ${content.length} characters]` 提示。
- Cline `search.ts` L485-497：`capSearchOutput` 中间截断到 `MAX_SEARCH_OUTPUT_CHARS`，保留头尾，中间用 `[... search output truncated ...]` 替代。

**影响**：
- Charles `WebSearchTool` 是唯一一个无字符截断的工具，与 Charles 其他工具（如 `fetch_web_content.py` 的 8000 字符截断、`exec_tool.py` 的输出截断）风格不一致。
- 实际风险较低：DuckDuckGo 摘要通常较短（几十到几百字符），10 条结果一般不超过 5000 字符。

**建议**：P3 级别可选修复。在 `_search_duckduckgo` 返回前增加字符截断（如 8000 字符，与 `fetch_web_content.py` 对齐），超出时追加截断提示。

### 差距 4：错误处理风格差异（3.21.16 / 3.21.17）

**Charles 实现**（`web_tool.py` L96-106）：

```python
try:
    results = await self._search_duckduckgo(query, num_results, context)
    return AgentToolResult(output=results)
except AbortedError:
    raise  # 中止异常向上传播
except Exception as e:
    return AgentToolResult(
        output={"error": f"搜索失败: {e}"},
        is_error=True,
    )
```

Charles 在 `_execute` 层捕获所有异常，返回 `is_error=True` 的结构化错误结果。此外 `_search_duckduckgo` 内部特判 `ImportError`（L118-122），ddgs 库未安装时返回安装提示字符串（**注意：此处返回的是字符串而非 AgentToolResult，会作为 `output` 传给 LLM**）。

**Cline 对比**：
- Cline `web-fetch.ts` L243-257：`catch` 块中 `throw new Error(...)`，错误向上抛出，由 runtime 统一捕获。
- Cline `search.ts`：错误同样 throw，不返回结构化错误。
- Cline 无 ImportError 特判（不依赖外部搜索库，无需考虑库缺失场景）。

**影响**：
- Charles 的方式让 LLM 能看到错误信息（作为 `output`），便于 LLM 自我纠正（如换关键词重试）。
- Cline 的方式让 runtime 统一处理错误格式，风格更一致。
- Charles 的 `ImportError` 特判返回字符串而非 `AgentToolResult`，与其他错误的 `is_error=True` 风格不一致，但功能上 LLM 仍能收到提示。

**建议**：保留现状。Charles 的错误处理风格与 `BaseTool.execute`（L129-138）的统一异常捕获一致，`ImportError` 特判是用户体验优化（引导用户安装库）。

### 差距 5：中止信号处理（3.21.18 / 3.21.19）

**Charles 实现**（`web_tool.py` L93-160）：

Charles `WebSearchTool` 有两层中止检查：
1. **搜索开始前**（L94）：`self._check_aborted(context)` 检查 abort_signal 是否已触发。
2. **搜索执行中**（L145-160）：将 `asyncio.to_thread(_sync_search)` 与 `abort_signal.wait()` 组合，用 `asyncio.wait(..., FIRST_COMPLETED)` 竞速，先完成者胜：
   - 若 abort 先触发：取消搜索任务，抛 `AbortedError`。
   - 若搜索先完成：取消 abort 等待任务，返回结果。

```python
search_task = asyncio.ensure_future(asyncio.to_thread(_sync_search))
abort_task = asyncio.ensure_future(signal.wait())
try:
    done, _ = await asyncio.wait(
        {search_task, abort_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if abort_task in done:
        search_task.cancel()
        raise AbortedError("aborted by user")
    abort_task.cancel()
    items = search_task.result()
except asyncio.CancelledError:
    search_task.cancel()
    abort_task.cancel()
    raise
```

**Cline 对比**：
- Cline `web-fetch.ts` L131-139：用 `AbortController` + `setTimeout` 组合，`context.signal` 的 abort 事件触发 `controller.abort()`，由 native fetch 的 `signal` 参数响应。
- Cline `search.ts` L205-213 / L388-390：检查 `abortSignal?.aborted` 或 `context.signal?.aborted`，但 ripgrep 子进程中止依赖 `child.kill("SIGTERM")`。

**影响**：
- Charles 的竞速方式能即时中止 DuckDuckGo 同步搜索（在线程池中运行的 `_sync_search` 通过 `cancel` 取消 future，但底层同步调用可能继续运行直到自然结束）。
- Cline 的方式更依赖底层（native fetch / ripgrep 子进程）对 abort 信号的响应能力。
- 两者都能在用户中止时让 LLM 尽快收到反馈，但 Charles 的 `to_thread` 任务取消可能不立即停止底层 HTTP 请求。

**建议**：保留现状。Charles 的中止处理已满足用户交互需求。

### 差距 6：Cline 搜索能力架构差异（架构层）

**Cline 架构**：

Cline 的网络信息获取分为两条路径：
1. **已知 URL**：`fetch_web_content` 工具（`web-fetch.ts`）抓取 URL 内容，HTML 转 Markdown，50000 字符截断。
2. **未知 URL / 需搜索**：通过 MCP 服务器接入搜索能力（用户配置 Brave Search MCP / Tavily MCP 等），由 `use_mcp_tool` 工具调用 MCP 服务器提供的搜索工具。

这种架构让 Cline 的搜索能力**可插拔**，用户按需选择搜索后端，但需要额外配置。

**Charles 架构**：

Charles 同时提供两个工具：
1. `WebSearchTool`（`web_tool.py`）：内置 DuckDuckGo 搜索，开箱即用。
2. `FetchWebContentTool`（`fetch_web_content.py`）：URL 抓取，对标 Cline `web-fetch.ts`。

Charles 也有 MCP 工具（`UseMcpToolTool` / `AccessMcpResourceTool`），但 `WebSearchTool` 是内置的，不依赖 MCP。

**影响**：
- Charles 的架构在量化场景下更高效（LLM 一次调用 `web_search` 即可获得搜索结果，无需先调 MCP 搜索再调 `fetch_web_content` 抓取）。
- Cline 的架构更通用（支持任意搜索后端），但 LLM 需要两步操作（MCP 搜索 + URL 抓取）才能获取网页内容。
- Charles 的 `context.py` L760 / L766 在系统 prompt 中主动引导 LLM 调用 `web_search`，强化了量化场景下的搜索能力。

**建议**：不强制改为 Cline 架构。Charles 的内置 `WebSearchTool` 是量化场景的合理特化。

---

## 四、nanobot 残留检查

针对 P3.21 核心文件 `agent/tools/web_tool.py` 执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块）。

### 4.1 P3.21 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/tools/web_tool.py` | **7** | 注释残留 | 见 4.2 详表 |

### 4.2 残留分类

#### 注释残留（7 处）

| 行号 | 内容 | 残留类型 |
|------|------|---------|
| L2 | `"""网络搜索工具 — 对标 Cline WebSearchTool + nanobot WebSearchTool` | docstring |
| L9 | `对标 nanobot:` | docstring |
| L10 | `    - nanobot/agent/tools/web.py L124-140` | docstring（文件路径引用） |
| L13 | `    - 无需 API Key（对标 nanobot fallback 方案）` | docstring（设计理由引用） |
| L28 | `"""网络搜索工具 — 对标 Cline WebSearchTool + nanobot WebSearchTool` | 类 docstring |
| L111 | `"""DuckDuckGo 搜索 — 对标 nanobot _search_duckduckgo` | 方法 docstring |
| L165 | `# 格式化结果 — 对标 nanobot _format_results` | 行内注释 |

**特点**：
- 7 处残留**全部为注释 / docstring**，引用 nanobot 作为设计来源标注（"对标 nanobot XXX"）。
- 无任何运行时行为受 nanobot 影响：无 `import nanobot`、无 `from nanobot import`、无 `nanobot.XXX` 调用、无继承 nanobot 类。
- 注释中提到的 `nanobot/agent/tools/web.py L124-140` 是 nanobot 项目的 `_search_duckduckgo` 函数，Charles 的 `_search_duckduckgo` 在逻辑上参考了 nanobot 的实现（使用 ddgs 库 + 在线程池中执行同步搜索），但代码是重写而非复制粘贴（变量名 / 错误处理 / 中止信号处理均为 Charles 特有）。

#### 实现逻辑残留（0 处）

P3.21 核心文件中**未发现任何从 nanobot 直接移植的实现逻辑**：

- 无 `import nanobot` 或 `from nanobot import` 语句。
- 无 `nanobot.XXX` 调用。
- 无继承 nanobot 类的代码。
- `_search_duckduckgo` 方法（L108-160）是 Charles 重写实现，包含 Charles 特有的中止信号竞速逻辑（L145-160），nanobot 原版无此逻辑。
- `_format_results` 逻辑（L166-172）是 Charles 重写实现，格式与 nanobot 原版可能类似（标题 + URL + 摘要的通用格式），但这是搜索工具的通用格式，非 nanobot 独有。

### 4.3 残留处理建议

7 处注释残留均为设计来源标注，**不影响运行时行为**，但有以下考虑：
- **优点**：保留 nanobot 标注可追溯设计来源，便于未来对照参考。
- **缺点**：nanobot 是历史项目，长期保留引用可能造成混淆（如新开发者误以为 nanobot 是当前依赖）。
- **建议**：P3 级别可选清理。若要清理，将"对标 Cline WebSearchTool + nanobot WebSearchTool"改为"对标 Cline WebSearchTool（Charles 独有，Cline 无对应工具）"，移除 L9-10 / L13 / L111 / L165 的 nanobot 引用。

---

## 五、修复建议

### 建议 1：不强制改为 fetch_web_content + MCP 搜索架构 [P3 不修复]

**理由**：
- Charles `WebSearchTool` 满足量化场景的即时搜索需求（市场信息 / 新闻 / 公司公告）。
- DuckDuckGo 免 API Key，降低部署门槛。
- `context.py` 系统 prompt 已主动引导 LLM 使用 `web_search`，改为 MCP 架构需要同步修改 prompt。
- Cline 的 MCP 搜索架构更通用，但 Charles 量化场景下内置工具更高效。

**保留条件**：若未来需要支持多搜索后端（AkShare / Tavily / Brave 等），可考虑引入 `source` 字段或通过 MCP 接入。

### 建议 2：增加结果字符截断 [P3 可选]

**文件**：`agent/tools/web_tool.py`
**位置**：L162-174（`_search_duckduckgo` 返回前）
**问题**：无显式字符截断，若 DuckDuckGo 返回长摘要可能撑爆 LLM 上下文。
**修复方式**：在 `return "\n".join(lines)` 前增加截断逻辑（如 8000 字符，与 `fetch_web_content.py` 对齐），超出时追加截断提示。

**理由**：与 Charles 其他工具（`fetch_web_content.py` 8000 字符截断、`exec_tool.py` 输出截断、`search_codebase.py` 截断）风格一致。

**优先级**：P3（不阻塞，实际风险低，DuckDuckGo 摘要通常较短）。

### 建议 3：清理 nanobot 注释残留 [P3 可选]

**文件**：`agent/tools/web_tool.py`
**位置**：L2 / L9-10 / L13 / L28 / L111 / L165
**问题**：7 处 nanobot 注释残留，均为设计来源标注，不影响运行时。
**修复方式**：
- L2 / L28：将"对标 Cline WebSearchTool + nanobot WebSearchTool"改为"网络搜索工具（Charles 独有，Cline 无对应工具）"。
- L9-10 / L13：移除 nanobot 段落，保留 DuckDuckGo 选择理由（无需 API Key / 支持中文搜索 / 使用 ddgs 库）。
- L111：将"对标 nanobot _search_duckduckgo"改为"DuckDuckGo 搜索实现"。
- L165：将"对标 nanobot _format_results"改为"格式化结果"。

**理由**：nanobot 是历史项目，长期保留引用可能造成混淆。

**优先级**：P3（不阻塞，可选清理）。

### 建议 4：保留 requires_approval = False [P0 不变]

**理由**：`web_search` 是只读工具，不产生副作用（不写文件 / 不执行命令 / 不修改状态），无需用户审批。`approval_policy.py` L39 已将 `web_search` 加入 `APPROVE_FREE` 白名单，自动批准。

### 建议 5：保留 timeout_ms = 30_000 [P0 不变]

**理由**：30 秒超时合理。DuckDuckGo 搜索通常 2-5 秒完成，30 秒超时能容纳网络波动。Cline `web-fetch.ts` 默认也是 30000ms（L18 注释 `@default 30000 (30 seconds)`），两侧超时一致。

### 建议 6：保留 retryable = True / max_retries = 2 [P0 不变]

**理由**：网络请求可能因瞬时故障失败，重试 2 次能提高成功率。Cline `web-fetch.ts` 无内置重试（依赖 runtime 层），Charles 的重试是增强。

---

## 六、验证方法建议

### 验证方法 1：Cline 无 WebSearchTool 确认

```powershell
# 确认 Cline DefaultToolName 枚举无 web_search
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\types.ts" -Pattern "web_search|WebSearch"
# 确认 Cline executors 目录无 web-search.ts
Get-ChildItem "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors" -Filter "web-search*"
# 确认 createDefaultExecutors 装配清单无 webSearch
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\executors\index.ts" -Pattern "webSearch|web.?search"
```

**预期**：
- `types.ts` 无 `web_search` 匹配（仅有 `fetch_web_content` / `search_codebase`）。
- `executors` 目录无 `web-search.ts` 文件。
- `index.ts` 无 `webSearch` 匹配。

### 验证方法 2：Charles WebSearchTool 属性检查

```powershell
# 确认 read_only / timeout_ms / retryable / max_retries
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\web_tool.py" -Pattern "read_only|timeout_ms|retryable|max_retries|requires_approval"
```

**预期**：
- `read_only` 返回 `True`（L67-68）。
- `timeout_ms` 返回 `30_000`（L71-73）。
- `retryable` 返回 `True`（L76-78）。
- `max_retries` 返回 `2`（L80-83）。
- `requires_approval` **未定义**（继承 `BaseTool` 默认 `False`）。

### 验证方法 3：输入 schema 检查

```powershell
# 确认 input_schema 字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\web_tool.py" -Pattern "query|num_results|source"
```

**预期**：
- `query` 字段存在（L52-55），`required: ["query"]`（L63）。
- `num_results` 字段存在（L56-61），`minimum: 1` / `maximum: 10`。
- **`source` 字段不存在**（计划描述与实际不符）。

### 验证方法 4：搜索后端确认

```powershell
# 确认 DuckDuckGo 后端
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\web_tool.py" -Pattern "ddgs|DDGS|duckduckgo|akshare|AkShare"
```

**预期**：
- 匹配 `ddgs` / `DDGS`（L117 / L130）。
- **无 `akshare` / `AkShare` 匹配**（计划描述与实际不符）。

### 验证方法 5：nanobot 残留扫描

```powershell
# P3.21 核心文件扫描
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\web_tool.py" -Pattern "nanobot" -CaseSensitive:$false
```

**预期**：7 处匹配（L2 / L9 / L10 / L13 / L28 / L111 / L165），全部为注释 / docstring。

### 验证方法 6：自动审批白名单检查

```powershell
# 确认 web_search 在 APPROVE_FREE 白名单中
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\approval_policy.py" -Pattern "web_search"
```

**预期**：`approval_policy.py` L39 `"web_search"` 在白名单中。

### 验证方法 7：系统 prompt 引用检查

```powershell
# 确认 context.py 在系统 prompt 中引导使用 web_search
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\context.py" -Pattern "web_search"
```

**预期**：`context.py` L760 / L766 引用 `web_search` 工具。

### 验证方法 8：截断策略缺失确认

```powershell
# 确认 web_tool.py 无显式字符截断
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\web_tool.py" -Pattern "truncat|slice|MAX_.*CHARS|8000|50000"
```

**预期**：无匹配（Charles `WebSearchTool` 无字符截断逻辑）。

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/tools/types.ts` | L228-230 | `DefaultToolName` 联合类型（9 个工具名，无 `web_search`） |
| `sdk/packages/core/src/extensions/tools/types.ts` | L201-206 | `SearchExecutor` / `WebFetchExecutor` 类型定义（代码搜索 / URL 抓取，非网络搜索） |
| `sdk/packages/core/src/extensions/tools/types.ts` | L248-263 | `enableSearch` / `enableWebFetch` 标志（无 `enableWebSearch`） |
| `sdk/packages/core/src/extensions/tools/executors/index.ts` | L91-101 | `createDefaultExecutors` 装配清单（无 webSearch executor） |
| `sdk/packages/core/src/extensions/tools/executors/web-fetch.ts` | L1-259 | `createWebFetchExecutor` URL 抓取实现（非搜索） |
| `sdk/packages/core/src/extensions/tools/executors/web-fetch.ts` | L18 | `timeoutMs` 默认 30000（30 秒） |
| `sdk/packages/core/src/extensions/tools/executors/web-fetch.ts` | L231 | `content.slice(0, 50000)` 50000 字符截断 |
| `sdk/packages/core/src/extensions/tools/executors/search.ts` | L1-497 | `createSearchExecutor` 代码库搜索（ripgrep / regex，非网络搜索） |
| `sdk/packages/core/src/extensions/tools/executors/search.ts` | L485-497 | `capSearchOutput` 中间截断到 `MAX_SEARCH_OUTPUT_CHARS` |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/tools/web_tool.py` | L1-16 | 模块 docstring（含 nanobot 注释残留） |
| `agent/tools/web_tool.py` | L27-33 | `WebSearchTool` 类定义与 docstring |
| `agent/tools/web_tool.py` | L35-37 | `name` 属性返回 `"web_search"` |
| `agent/tools/web_tool.py` | L39-45 | `description` 属性（量化场景描述） |
| `agent/tools/web_tool.py` | L47-64 | `input_schema`：query（必填）+ num_results（可选，1-10） |
| `agent/tools/web_tool.py` | L66-68 | `read_only` 返回 `True` |
| `agent/tools/web_tool.py` | L70-73 | `timeout_ms` 返回 `30_000` |
| `agent/tools/web_tool.py` | L75-78 | `retryable` 返回 `True` |
| `agent/tools/web_tool.py` | L80-83 | `max_retries` 返回 `2` |
| `agent/tools/web_tool.py` | L85-106 | `_execute` 方法：try/except 错误处理 |
| `agent/tools/web_tool.py` | L93-94 | 搜索开始前 `_check_aborted` 中止检查 |
| `agent/tools/web_tool.py` | L108-160 | `_search_duckduckgo` 方法：DuckDuckGo 搜索 + 中止竞速 |
| `agent/tools/web_tool.py` | L116-122 | ddgs 库 ImportError 特判 |
| `agent/tools/web_tool.py` | L128-137 | `_sync_search` 同步搜索函数（DDGS.text） |
| `agent/tools/web_tool.py` | L140-160 | to_thread + abort_signal.wait 竞速中止逻辑 |
| `agent/tools/web_tool.py` | L162-174 | 结果格式化（无字符截断） |
| `agent/tools/base.py` | L75-88 | `timeout_ms` / `retryable` / `max_retries` 默认值 |
| `agent/tools/base.py` | L90-93 | `read_only` 默认 `False` |
| `agent/tools/base.py` | L95-103 | `requires_approval` 默认 `False`（WebSearchTool 未覆盖） |
| `agent/tools/__init__.py` | L45 | `WebSearchTool` 导入 |
| `agent/tools/__init__.py` | L91 | `create_default_tools` 装配 `WebSearchTool()` |
| `agent/tools/__init__.py` | L120 | `__all__` 包含 `"WebSearchTool"` |
| `agent/approval_policy.py` | L36-43 | `APPROVE_FREE` 白名单含 `web_search` |
| `agent/context.py` | L760 / L766 | 系统 prompt 引导 LLM 使用 `web_search` |
| `agent/tools/plan_mode.py` | L44 | plan 模式下 `web_search` 可用（探索工具） |

---

## 八、结论

P3.21 web_tool（WebSearchTool）对比的核心结论：

1. **工具存在性差异是核心结论**：Cline **无独立的 WebSearchTool**（`DefaultToolName` 枚举无 `web_search`，`createDefaultExecutors` 无 webSearch executor），网络搜索能力通过 `fetch_web_content`（URL 抓取）+ MCP 服务器接入搜索能力组成。Charles **有独立的 `WebSearchTool`**（`web_tool.py`），内置 DuckDuckGo 搜索后端，开箱即用无需 API Key。这是 Charles 在量化场景下的特化设计。

2. **计划描述与实际实现不符的修正**：
   - 计划描述"输入 schema：query / num_results / source"——**实际无 `source` 字段**，仅有 `query` 和 `num_results`。
   - 计划描述"搜索后端：AkShare / 其他"——**实际为 DuckDuckGo 单一后端**（通过 `ddgs` 库），无 AkShare。
   - 本报告以实际实现为准。

3. **属性配置合理**：
   - `read_only = True`：网络搜索无副作用，标记为只读合理。
   - `requires_approval = False`：继承 `BaseTool` 默认值，且在 `approval_policy.py` 的 `APPROVE_FREE` 白名单中，自动批准。
   - `timeout_ms = 30_000`：30 秒超时，与 Cline `web-fetch.ts` 默认值一致。
   - `retryable = True` / `max_retries = 2`：网络瞬时故障可重试，Charles 增强。

4. **结果截断策略缺失**：Charles `WebSearchTool` **无显式字符截断**，仅靠 `num_results`（最大 10）限制条数。与 Cline `web-fetch.ts`（50000 字符截断）、`search.ts`（`MAX_SEARCH_OUTPUT_CHARS` 中间截断）以及 Charles 其他工具（`fetch_web_content.py` 8000 字符截断）风格不一致。实际风险低（DuckDuckGo 摘要通常较短），但建议 P3 级别可选修复以保持风格一致。

5. **错误处理风格差异**：Charles 在 `_execute` 层捕获所有异常返回 `is_error=True` 的结构化错误（便于 LLM 自我纠正），特判 `ImportError` 引导用户安装 ddgs 库；Cline `web-fetch.ts` 直接 throw 错误由 runtime 统一捕获。两者风格不同但功能等价。

6. **中止信号处理完善**：Charles 有两层中止检查（搜索开始前 + 搜索执行中竞速），通过 `asyncio.wait(..., FIRST_COMPLETED)` 实现 DuckDuckGo 同步搜索的即时中止。这是 Charles 特有的实现（nanobot 原版无此逻辑），对标 Cline 的 abort signal 响应机制。

7. **nanobot 残留**：`web_tool.py` 共 **7 处 nanobot 注释残留**（全部为 docstring / 行内注释中的"对标 nanobot"引用），**0 处实现逻辑残留**（无 nanobot 导入 / 继承 / 调用）。残留均为文档性标注，不影响运行时行为。建议 P3 级别可选清理。

8. **架构差异是设计选择**：Charles 内置 `WebSearchTool` 是量化场景的合理特化（市场信息 / 新闻 / 公司公告搜索），与 Cline "搜索能力由 MCP 承担"的通用架构不同。不建议强制改为 `fetch_web_content + MCP 搜索`架构。

**整体一致性等级**：**低**（因 Cline 无对应工具，所有对比项均为 N/A 或 Charles 独有）。但 Charles `WebSearchTool` 的实现质量良好：属性配置合理（`read_only` / `timeout_ms` / `retryable` / `max_retries`）、错误处理完善、中止信号处理健全、DuckDuckGo 后端免 API Key。主要改进点为结果截断策略缺失（P3 可选）和 nanobot 注释残留（P3 可选），均不阻塞。
