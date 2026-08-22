# Phase 3.9 内置工具清单与类似工具重复度评估报告

> 对比范围：Cline `sdk/packages/core/src/extensions/tools/definitions.ts` 与 Charles `agent/tools/*.py`
> 重点评估：5 组类似工具的逻辑重复度、合并/删除建议
> 输出文件：`CLINE_DIFF_V2/phase_3.9_builtin_tools_overview.md`

---

## 一、执行摘要

1. **工具清单总体对齐**：Charles 的 `create_default_tools` 注册了 15 个工具，覆盖 Cline 主要工具，但在与计划表 P3.9 的对照中存在 **3 处偏差**：
   - 计划表 3.9.3 标注 Charles `editor` "无" — 实际 Charles **已注册** `EditorTool`（`__init__.py:95`）。
   - 计划表 3.9.11 标注 `attempt_completion` "已对齐" — 实际 `AttemptCompletionTool` **从未被实例化/注册**（仅在 `attempt_completion.py` 中定义，全文无 `AttemptCompletionTool(` 调用），属于孤儿工具。
   - 计划表未列 `file_read`（`FileReadTool`）状态 — 实际 `FileReadTool` 在 `file_tools.py` 中定义，但 **未在 `__init__.py` 导出**、**未注册**，同样属于孤儿工具。

2. **5 组类似工具评估结论**：
   | 组别 | 工具 | 逻辑重复度 | 建议 |
   |------|------|----------|------|
   | 1 命令执行 | `exec_tool` vs `run_commands` | **高** | **删除 `exec_tool.py`** |
   | 2 网络 | `web_tool` vs `fetch_web_content` | **低** | 保留两者 |
   | 3 文件写入 | `file_write` / `editor` / `apply_patch` | **中** | 保留三者，依赖 routing 规则互斥 |
   | 4 交互/完成 | `ask_question` / `attempt_completion` / `submit_and_exit` | **低** | 删除 `attempt_completion`（孤儿） |
   | 5 文件读取 | `read_files` vs `list_files` | **低** | 保留两者 |

3. **孤儿工具汇总**（定义存在但未注册）：
   - `ExecTool`（`exec_tool.py`）— 显式标注 "已废弃"
   - `FileReadTool`（`file_tools.py`）— 未导出、未注册
   - `AttemptCompletionTool`（`attempt_completion.py`）— 未注册

4. **nanobot 残留**：`agent/tools/` 目录共 27 处 nanobot 字样，集中在 `exec_tool.py`（12 处）、`file_tools.py`（8 处）、`web_tool.py`（6 处）、`__init__.py`（1 处），全部为文档注释中的"对标 nanobot"溯源说明，**无实际代码依赖**。

---

## 二、内置工具清单对比表（Cline vs Charles）

### 2.1 Cline `createDefaultTools` 工具清单

来源：`definitions.ts` L871-936，按 `enable*` 开关动态启用。

| # | 工具名 | 工厂函数 | 启用默认 | 说明 |
|---|--------|---------|---------|------|
| C1 | `read_files` | `createReadFilesTool` | enableReadFiles=true | 批量读文件，支持 start_line/end_line |
| C2 | `search_codebase` | `createSearchTool` | enableSearch=true | 正则代码搜索 |
| C3 | `run_commands` | `createShellTool` | enableBash=true | 命令执行（PowerShell/bash 自适应） |
| C4 | `fetch_web_content` | `createWebFetchTool` | enableWebFetch=true | URL 抓取 + prompt 分析 |
| C5 | `editor` | `createEditorTool` | enableEditor=true | 行级编辑（old_text/new_text, insert_line, create） |
| C5' | `apply_patch` | `createApplyPatchTool` | enableApplyPatch=false（与 editor 互斥） | canonical patch 格式 |
| C6 | `skills` | `createSkillsTool` | enableSkills=true | 技能调用 |
| C7 | `ask_question` | `createAskQuestionTool` | enableAskQuestion=true（无 submit 时） | 向用户提问 |
| C8 | `submit_and_exit` | `createSubmitAndExitTool` | enableSubmitAndExit=false | 提交并退出（与 ask_question 互斥） |

**Cline 互斥规则**（`definitions.ts` L912-917）：
- `editor` 与 `apply_patch` 二选一，不同时启用
- `ask_question` 与 `submit_and_exit` 二选一（有 submit 时不注册 ask_question）

**Cline SDK core 未直接包含但文档列出的工具**（来自 VSCode 集成层 / spawn-agent）：
`list_files` / `todo_write` / `plan_mode`（switch_to_act_mode / switch_to_plan_mode）/ `use_mcp_tool` / `access_mcp_resource` / `spawn_agent`

### 2.2 Charles `create_default_tools` 工具清单

来源：`agent/tools/__init__.py` L86-110。

| # | 工具名 | 类 | 来源 | 说明 |
|---|--------|-----|------|------|
| S1 | `run_commands` | `RunCommandsTool` | Cline 原生 | 批量命令执行（替代 ExecTool） |
| S2 | `read_files` | `ReadFilesTool` | Cline 原生 | 批量文件读取（多文件+行范围） |
| S3 | `file_write` | `FileWriteTool` | Charles 新增 | 全文件写入（Cline 无独立工具） |
| S4 | `web_search` | `WebSearchTool` | nanobot 迁移 | DuckDuckGo 搜索 |
| S5 | `todo_write` | `TodoWriteTool` | Cline 原生 | 任务清单 |
| S6 | `editor` | `EditorTool` | Cline 原生 | 行级编辑 |
| S7 | `apply_patch` | `ApplyPatchTool` | Cline 原生 | patch 格式应用 |
| S8 | `search_codebase` | `SearchCodebaseTool` | Cline 原生 | 正则代码搜索 |
| S9 | `fetch_web_content` | `FetchWebContentTool` | Cline 原生 | URL 抓取 |
| S10 | `ask_question` | `AskQuestionTool` | Cline 原生 | 向用户提问 |
| S11 | `list_files` | `ListFilesTool` | Charles 新增 | 目录列表 |
| S12 | `submit_and_exit` | `SubmitAndExitTool` | Cline 原生 | 提交并退出 |
| S13 | `use_mcp_tool` | `UseMcpToolTool` | Cline 原生 | MCP 工具调用 |
| S14 | `access_mcp_resource` | `AccessMcpResourceTool` | Cline 原生 | MCP 资源读取 |
| S15 | `switch_to_act_mode` | `SwitchToActModeTool` | Cline 原生 | 模式切换 |
| S16 | `switch_to_plan_mode` | `SwitchToPlanModeTool` | Cline 原生 | 模式切换 |

**额外通过 `server.py` 单独注册的工具**（不在 `create_default_tools` 中）：
- `skills`（`SkillsTool`）— `server.py:405` 单独注册，需要 SkillRegistry 依赖

**Charles 已定义但未注册的孤儿工具**：
- `ExecTool`（`exec_tool.py`）— `__init__.py:30` 显式导入并导出，但 `create_default_tools` 不实例化
- `FileReadTool`（`file_tools.py:26`）— 类定义存在，但 `__init__.py:32` 只导入 `FileWriteTool`，`FileReadTool` 既不导入也不注册
- `AttemptCompletionTool`（`attempt_completion.py`）— 类定义存在，但全文无实例化调用，`__init__.py` 不导入

### 2.3 工具清单差异对比表（修正版）

| # | 工具名 | Cline | Charles | 来源 | 状态差异（vs 计划表 P3.9） |
|---|--------|-------|---------|------|------------------------|
| 3.9.1 | `read_files` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.2 | `run_commands` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.3 | `editor` | 有 | **有** | Cline 原生 | **计划表标注错误**：计划称"无"，实际已注册 |
| 3.9.4 | `apply_patch` | 有 | 有 | Cline 原生 | 已对齐 ✓（与 editor 同时注册，靠 routing 互斥） |
| 3.9.5 | `file_write` | 无 | 有 | Charles 新增 | Charles 额外 ✓ |
| 3.9.6 | `list_files` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.7 | `search_codebase` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.8 | `fetch_web_content` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.9 | `ask_question` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.10 | `submit_and_exit` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.11 | `attempt_completion` | 有 | **定义存在但未注册** | Cline 原生 | **计划表标注错误**：计划称"已对齐"，实际从未注册 |
| 3.9.12 | `todo_write` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.13 | `plan_mode` | 有 | 有 | Cline 原生 | 已对齐 ✓（split 为 switch_to_act/switch_to_plan） |
| 3.9.14 | `skills` | 有 | 有 | Cline 原生 | 已对齐 ✓（在 server.py 单独注册） |
| 3.9.15 | `use_mcp_tool` | 有 | 有 | Cline 原生 | 已对齐 ✓ |
| 3.9.16 | `access_mcp_resource` | 有 | 有 | Cline 原生 | **计划表标注错误**：计划称"无"，实际已注册 |
| 3.9.17 | `spawn_agent` | 有 | 无 | — | Charles 不实施（Phase 27 移除）✓ |
| 新增 | `web_search` | 无 | 有 | nanobot 迁移 | Charles 额外（Cline 无独立搜索工具） |
| 新增 | `file_read`（FileReadTool） | 无 | **定义存在但未注册** | nanobot 迁移 | 孤儿工具，应清理 |

### 2.4 关键差异说明

1. **Cline `editor` 与 `apply_patch` 互斥**（`definitions.ts` L912-917 注释："Do not enable two similar tools at the same time"），Charles **两者都注册**，通过 `routing.py` 的 `DEFAULT_MODEL_TOOL_ROUTING_RULES` 按模型动态切换（openai-native / codex / gpt 系列用 apply_patch，其他用 editor）。
2. **Cline `ask_question` 与 `submit_and_exit` 互斥**，Charles **两者都注册**（不同时使用，但运行时都暴露给 LLM）。
3. **Charles 缺失 `spawn_agent`**（计划 Phase 27 明确移除），因此 `attempt_completion`（依赖子 agent 上下文）失去使用场景，成为孤儿工具。

---

## 三、类似工具逻辑重复度评估（重点章节）

### 3.1 第 1 组：命令执行类 — `exec_tool.py` vs `run_commands.py`

#### 3.1.1 工具对比表

| 对比项 | `ExecTool`（exec_tool.py） | `RunCommandsTool`（run_commands.py） |
|--------|---------------------------|-------------------------------------|
| 工具名 | `exec` | `run_commands` |
| 输入 | 单 command 字符串 | commands 数组（最多 10 条） |
| 是否注册 | **否**（已废弃，`__init__.py:12` 注释） | 是（默认工具集） |
| 异步执行 | `asyncio.create_subprocess_shell` | `asyncio.create_subprocess_shell` |
| 危险命令拦截 | `_DENY_PATTERNS`（9 条） | `_DENY_PATTERNS`（9 条，**完全复制**自 ExecTool） |
| 中止处理 | `_wait_process_with_abort` | `_wait_process_with_abort` + `_wait_process_with_abort_stream`（流式版本） |
| 超时处理 | 超时抛 `TimeoutError` 后 kill | 超时优雅 kill（`_graceful_kill`：SIGTERM → SIGKILL） |
| 输出截断 | 整体上限 `MAX_COMMAND_OUTPUT_CHARS=16000`，中段截断 | 单命令 stdout 8000 + stderr 2000，首尾各一半 |
| 实时输出 | 无 | 有（`emit_update` 推送 terminal_output） |
| 审批要求 | 无 `requires_approval` | `requires_approval=True` |
| 行数 | 271 行 | 530 行 |

#### 3.1.2 逻辑重复度：**高**

- **核心逻辑完全重复**：两者都实现 `asyncio.create_subprocess_shell` + `_guard_command` + `_wait_process_with_abort` + 输出截断。
- `run_commands.py:65-66` 注释明示"复用自 ExecTool._DENY_PATTERNS"，`run_commands.py:522` 注释"复用自 ExecTool._guard_command"。
- `ExecTool._wait_process_with_abort` 与 `RunCommandsTool._wait_process_with_abort` 实现几乎一致（仅返回值多一个 `timed_out` 字段）。
- `RunCommandsTool` 在功能上是 `ExecTool` 的超集：支持批量、流式输出、优雅 kill、审批控制。

#### 3.1.3 功能差异

- `ExecTool` 是 nanobot 时代的单命令实现，已被 `RunCommandsTool` 完全替代。
- `RunCommandsTool` 增加了：批量执行、实时终端输出、超时不抛错而是返回部分输出 + timed_out 标记、SIGTERM 优雅 kill。

#### 3.1.4 合并建议：**删除 `exec_tool.py`**

**理由**：
1. `ExecTool` 已被显式标注废弃（`__init__.py:12` "已废弃，主 agent 不再注册"），`create_default_tools` 不实例化。
2. 全文搜索 `ExecTool(` 调用：仅在 `__init__.py:30` 的导入语句和 `__all__` 导出中存在，**无任何业务代码实例化**。
3. `run_commands.py` 内部注释引用"复用自 ExecTool"，删除 `exec_tool.py` 后这些注释应改为独立说明（如"危险命令模式，对标 Cline deny_patterns"）。
4. `constants.py:36-37` 中 `MAX_COMMAND_OUTPUT_CHARS` 仅用于 `exec_tool.py`，删除后该常量也应一并清理。
5. `constants.py:113-139` 的 `TOOL_PRESETS` 字典中包含 `"exec_tool": True`，删除后应改为 `"run_commands": True`。

**清理清单**：
- 删除 `agent/tools/exec_tool.py`
- `__init__.py:30` 移除 `from agent.tools.exec_tool import ExecTool`
- `__init__.py:125` 移除 `"ExecTool"` from `__all__`
- `__init__.py:12` 移除文档字符串中 ExecTool 行
- `__init__.py:55` 移除"替代 ExecTool"注释
- `constants.py:36-37` 删除 `MAX_COMMAND_OUTPUT_CHARS` 常量
- `constants.py:113-139` `TOOL_PRESETS` 中 `"exec_tool"` 改为 `"run_commands"`
- `run_commands.py:5,65,150,522` 修改注释，去掉对 ExecTool 的引用

---

### 3.2 第 2 组：网络工具类 — `web_tool.py` vs `fetch_web_content.py`

#### 3.2.1 工具对比表

| 对比项 | `WebSearchTool`（web_tool.py） | `FetchWebContentTool`（fetch_web_content.py） |
|--------|------------------------------|---------------------------------------------|
| 工具名 | `web_search` | `fetch_web_content` |
| 用途 | 搜索引擎查询 | 抓取指定 URL 内容 |
| 输入 | `query` + `num_results` | `requests: [{url, prompt}]` |
| 数据来源 | DuckDuckGo（ddgs 库） | 直接 HTTP GET（urllib） |
| 输出格式 | 标题/URL/摘要 列表 | URL 内容纯文本 |
| 是否注册 | 是 | 是 |
| 是否只读 | `read_only=True` | `read_only=True` |
| 超时 | 30 秒 | 60 秒（批量） |
| 重试 | retryable=True, max_retries=2 | retryable=True, max_retries=2 |
| 审批 | 否（自动批准） | 否（自动批准） |
| 中止处理 | `to_thread` + `abort_signal.wait` 组合 | 无（`asyncio.to_thread` 但未与 abort 组合） |

#### 3.2.2 逻辑重复度：**低**

- 两者用途完全不同：一个是搜索（输入关键词，输出候选 URL 列表），一个是抓取（输入 URL，输出页面内容）。
- 实现路径不同：`WebSearchTool` 用第三方 `ddgs` 库，`FetchWebContentTool` 用标准库 `urllib.request` + 自实现 HTML 解析器。
- 无共享代码、无重复模式。

#### 3.2.3 功能差异

- `WebSearchTool` 不抓取页面内容，仅返回搜索结果摘要（典型用法：先 `web_search` 找链接，再 `fetch_web_content` 抓详情）。
- `FetchWebContentTool` 必须已知 URL，且要求 prompt 字段（≥2 字符），用于"告诉工具如何处理抓取的内容"（虽然实现上 prompt 仅作为透传字段，未真正用于分析）。

#### 3.2.4 合并建议：**保留两者**

**理由**：
1. 功能互补，符合 Cline 的工具粒度划分（Cline 也有独立的 `fetch_web_content` 工具；Cline 无独立 `web_search`，但 Charles 量化场景需要搜索财经新闻）。
2. 删除任一都会丢失能力：删除 `web_search` 失去搜索能力，删除 `fetch_web_content` 失去 URL 内容获取能力。

**小问题**（不强制修改）：
- `FetchWebContentTool` 的 `prompt` 字段在实现中仅作为返回结果的透传字段，未真正用于"分析"内容。描述中称"用 prompt 分析"但实际只是抓取后截断。建议修改描述，去掉"分析"误导，或后续真正实现基于 prompt 的内容提取。
- `FetchWebContentTool` 未与 `abort_signal` 组合等待，长抓取无法即时中止（与 `WebSearchTool` 行为不一致）。

---

### 3.3 第 3 组：文件写入类 — `file_tools.py` / `editor.py` / `apply_patch.py`

#### 3.3.1 工具对比表

| 对比项 | `FileWriteTool`（file_tools.py） | `EditorTool`（editor.py） | `ApplyPatchTool`（apply_patch.py） |
|--------|-------------------------------|-------------------------|---------------------------------|
| 工具名 | `file_write` | `editor` | `apply_patch` |
| 输入 | `file_path` + `content` | `path` + `new_text` + (`old_text` \| `insert_line`) | `input`（patch 文本） |
| 写入模式 | 全文件覆盖 | 创建/插入/替换（三种） | Update/Add/Delete（多文件原子） |
| 多文件 | 否 | 否 | 是（一个 patch 含多个 block） |
| 原子性 | 单文件写入 | 单文件写入 | 两阶段提交（compute → apply） |
| 唯一匹配校验 | 无 | old_text 必须唯一匹配 | fuzzy 匹配（精确 + rstrip + expandtabs） |
| 行号 diff | 无 | 有（`_create_line_diff`） | 无 |
| 换行符处理 | 无 | 有（`_detect_line_ending` 等） | 有（同 EditorTool 的三函数） |
| 是否注册 | 是 | 是 | 是 |
| 审批要求 | `requires_approval=True` | `requires_approval=True` | `requires_approval=True` |
| routing 互斥 | 否（始终启用） | 与 apply_patch 互斥（routing 规则控制） | 与 editor 互斥（routing 规则控制） |

#### 3.3.2 逻辑重复度：**中**

重复点：
1. **换行符处理三函数完全重复**：
   - `editor.py:36-54` 定义 `_detect_line_ending` / `_normalize_for_edit` / `_restore_line_ending`
   - `apply_patch.py:95-113` **完全相同**地定义了同名三函数（实现一字不差）
   - `file_tools.py` 的 `FileWriteTool` 未做换行符处理（直接 `write_text`）
2. **写入逻辑重复**：
   - `EditorTool._do_create`（创建模式）≈ `FileWriteTool._execute`（全文件写入）≈ `ApplyPatchTool._compute_add_change`（Add File）
   - 三者都做 `path.parent.mkdir(parents=True, exist_ok=True)` + `path.write_text(content, encoding="utf-8")`
3. **`FileWriteTool` 与 `EditorTool._do_create` 功能重叠**：两者都是"文件不存在则创建，存在则覆盖"，仅参数名不同（`file_path`/`content` vs `path`/`new_text`）。

不重复点：
- `ApplyPatchTool` 的两阶段提交（compute → apply）、fuzzy 匹配、多文件原子性是其他两者不具备的。
- `EditorTool` 的 `old_text` 唯一匹配 + 行级 diff 是 `FileWriteTool` 不具备的。

#### 3.3.3 功能差异

- `FileWriteTool`：最简单的"全文件覆盖写入"，适合创建新文件或完全重写。
- `EditorTool`：Cline 风格的精确编辑，适合小修改（old_text/new_string 替换、insert_line 插入、create 创建）。
- `ApplyPatchTool`：Cline 风格的批量 patch，适合一次修改多个文件、多个位置（OpenAI 模型优化路径）。

#### 3.3.4 合并建议：**保留三者，但建议抽取公共换行符工具**

**理由**：
1. Cline 原生设计就是 `editor` + `apply_patch` 二选一（`definitions.ts:912-917`），两者各自有适用场景，靠 routing 互斥即可。
2. Charles 已通过 `routing.py:59-74` 的 `DEFAULT_MODEL_TOOL_ROUTING_RULES` 实现 openai-native / codex / gpt 系列用 apply_patch、其他用 editor，符合 Cline 设计意图。
3. `FileWriteTool` 虽然功能上被 `EditorTool._do_create` 覆盖，但保留独立工具的优势：
   - LLM 生成 `file_write` 调用比 `editor` 调用更直观（"我要写一个新文件"→ `file_write`，而非"我要编辑一个不存在的文件"→ `editor` create 模式）
   - `FileWriteTool` 不需要读取原文件，性能略好（对大文件覆盖场景）
   - `FileWriteTool` 不需要 LLM 理解 editor 的三种模式分支
4. **不建议强制合并**，但建议以下优化（可选）：
   - 抽取 `editor.py` 和 `apply_patch.py` 中的换行符三函数到 `agent/tools/_text_utils.py`（或类似公共模块），两者共同导入，消除重复。
   - 在 `file_tools.py` 的 `FileWriteTool` 中也使用同样的换行符处理，保证三个工具写入行为一致。

**清理清单**（可选优化，不强制）：
- 新建 `agent/tools/_text_utils.py`，迁移 `_detect_line_ending` / `_normalize_for_edit` / `_restore_line_ending`
- `editor.py:36-54`、`apply_patch.py:95-113` 改为 `from agent.tools._text_utils import ...`
- 不修改 `FileWriteTool` 的写入逻辑（避免破坏已验证行为）

---

### 3.4 第 4 组：交互/完成类 — `ask_question.py` / `attempt_completion.py` / `submit_and_exit.py`

#### 3.4.1 工具对比表

| 对比项 | `AskQuestionTool` | `AttemptCompletionTool` | `SubmitAndExitTool` |
|--------|------------------|------------------------|--------------------|
| 工具名 | `ask_question` | `attempt_completion` | `submit_and_exit` |
| 用途 | 向用户提问 | 子 agent 返回结果 | 主 agent 提交并退出 |
| 输入 | `question` + `options`(2-5) | `result` | `summary`(≥10 字符) + `verified` |
| `completes_run` | 否 | 是 | 是 |
| `read_only` | True | True | False |
| 是否注册 | 是 | **否**（孤儿） | 是 |
| 使用场景 | 主 agent 澄清信息 | 子 agent 完成技能 | 主 agent 完成任务 |
| 依赖 | 无 | 依赖 `spawn_agent` 子 agent 机制 | 无 |

#### 3.4.2 逻辑重复度：**低**

- 三者用途完全不同：`ask_question` 是交互（不结束运行），`attempt_completion` 和 `submit_and_exit` 都是结束运行但服务对象不同（子 agent vs 主 agent）。
- `attempt_completion` 与 `submit_and_exit` 的 `lifecycle.completes_run=True` 标记相同，但这是生命周期标记的复用，不算逻辑重复。
- 三者无共享代码、无重复实现。

#### 3.4.3 功能差异

- `ask_question`：通过 `context.emit_update` 推送问题到前端，不等待回答，LLM 收到"已发送"结果。
- `attempt_completion`：设计用于子 agent（spawn_agent 机制），子 agent 调用后 runtime 结束子 agent 运行，结果回流给主 agent。
- `submit_and_exit`：主 agent 调用后 runtime 结束整个运行，summary 作为最终结果返回。

#### 3.4.4 合并建议：**删除 `attempt_completion.py`**

**理由**：
1. `AttemptCompletionTool` **从未被实例化**：全文搜索 `AttemptCompletionTool(` 仅匹配类定义（`attempt_completion.py:33`），无任何调用。
2. `__init__.py` **未导入** `AttemptCompletionTool`，`create_default_tools` 不注册，`server.py` 也不注册。
3. Charles 在 Phase 27 已明确移除 `spawn_agent` 工具（计划表 3.9.17），`attempt_completion` 失去使用场景（它依赖子 agent 机制）。
4. 计划表 3.9.11 标注"已对齐"是错误的——Cline 的 `attempt_completion` 在 spawn-agent 上下文中使用，Charles 既无 spawn_agent 也未注册 attempt_completion，实际未对齐。
5. `submit_and_exit` 已覆盖"主 agent 完成任务"场景，无需保留 `attempt_completion`。

**清理清单**：
- 删除 `agent/tools/attempt_completion.py`
- `agent/skills/loader.py:19` 中 `attempt_completion` 提及的是文档示例（技能可用工具列表），需同步更新文档
- `agent/skills/skill_tool.py:22` 注释"不用 attempt_completion 返回结果"可保留（说明 Charles 的设计选择），或一并清理
- `agent/runtime.py:2362` 注释"你必须调用完成工具（如 attempt_completion 或 submit_and_exit）"应改为仅提 `submit_and_exit`
- `agent/types.py:160,496` 注释中 `attempt_completion` 提及应改为 `submit_and_exit`
- `agent/approval_policy.py:42` 只读工具白名单中 `attempt_completion` 应移除
- `agent/tools/todo_write.py:189` hint 文案"可以调用 attempt_completion 或直接回复用户"应改为 `submit_and_exit`

---

### 3.5 第 5 组：文件读取类 — `read_files.py` vs `list_files.py`

#### 3.5.1 工具对比表

| 对比项 | `ReadFilesTool`（read_files.py） | `ListFilesTool`（list_files.py） |
|--------|-------------------------------|-------------------------------|
| 工具名 | `read_files` | `list_files` |
| 用途 | 读取文件内容 | 列出目录条目 |
| 输入 | `files: [{path, start_line, end_line}]` | `path` + `recursive` |
| 输出 | 文件内容 + 行号 | 条目列表（name/type/size） |
| 多文件 | 是（最多 10 个） | 否（单目录） |
| 行范围 | 是（start_line/end_line） | 否 |
| 是否注册 | 是 | 是 |
| 是否只读 | `read_only=True` | `read_only=True` |
| 跳过目录 | 无（不遍历目录） | `.git/node_modules/__pycache__/.venv` 等 |
| 截断 | 单文件 16000 字符 | 最多 200 条目 |

#### 3.5.2 逻辑重复度：**低**

- 两者用途完全不同：一个是读文件内容，一个是列目录结构。
- 无共享代码、无重复模式。

#### 3.5.3 功能差异

- `ReadFilesTool` 不遍历目录，只读取指定文件路径。
- `ListFilesTool` 不读取文件内容，只返回目录下的文件/子目录列表。
- 两者是互补关系（典型用法：先 `list_files` 找文件，再 `read_files` 读内容）。

#### 3.5.4 合并建议：**保留两者**

**理由**：
1. 功能互补，符合 Cline 的工具粒度划分。
2. 合并会导致工具职责模糊（一个工具既读内容又列目录），不利于 LLM 选择。

**附带清理建议**：
- `file_tools.py` 中的 `FileReadTool`（孤儿工具）应一并清理：
  - 全文搜索 `from agent.tools.file_tools import.*FileReadTool` 无匹配（`__init__.py:32` 仅导入 `FileWriteTool`）
  - 但 `agent/context.py:2238` 和 `agent/runtime.py:1154` 中存在 `tool_name == "read_files" or tool_name == "file_read"` 的兼容判断——这是为兼容历史命名（FileReadTool 曾用名 `file_read`）保留的，删除 FileReadTool 后这些兼容判断应保留（防止旧会话回放失败），或一并清理。
  - `agent/approval_policy.py:35` 只读白名单中 `"file_read"` 应改为 `"read_files"`（或两者都保留，因为 `"file_read"` 已无对应工具）。
  - `agent/tools/file_tools.py:1-13` 模块文档字符串提及 FileReadTool 应同步更新或拆分文件。
  - **建议**：将 `file_tools.py` 重命名为 `file_write.py`（仅保留 FileWriteTool），或保留文件名但删除 FileReadTool 类。`constants.py:24` 注释"用于 file_tools.py"也应更新。

---

## 四、nanobot 残留检查

### 4.1 残留统计

对 `agent/tools/` 目录执行 `grep -i nanobot`，共 **27 处**匹配，分布如下：

| 文件 | 匹配数 | 残留类型 |
|------|--------|---------|
| `exec_tool.py` | 12 | 模块文档 + 类文档 + 行内注释（"对标 nanobot shell.py" 等） |
| `file_tools.py` | 8 | 模块文档 + 类文档 + 行内注释（"对标 nanobot FilesystemTool" 等） |
| `web_tool.py` | 6 | 模块文档 + 方法注释（"对标 nanobot _search_duckduckgo" 等） |
| `__init__.py` | 1 | 模块文档字符串（"对标 Cline extensions/tools 和 nanobot agent/tools"） |

### 4.2 残留性质分析

**全部为文档注释，无实际代码依赖**：
- 所有 27 处均为 `"""..."""` 文档字符串或 `# 对标 nanobot ...` 行内注释。
- 无 `from nanobot...` 或 `import nanobot...` 语句。
- 无 nanobot 类/函数的引用。
- 残留的目的是"溯源说明"——标注 Charles 工具参考了 nanobot 的哪些实现。

### 4.3 残留清理建议

| 优先级 | 文件 | 建议 |
|--------|------|------|
| 高 | `exec_tool.py` | 整个文件删除（见 3.1.4） |
| 中 | `file_tools.py` | 删除 FileReadTool（见 3.5.4），保留 FileWriteTool 的 nanobot 注释可改为"对标 Cline FileWriteTool" |
| 中 | `web_tool.py` | 保留（web_search 是 nanobot 迁移工具，溯源注释有保留价值），或改为"参考 nanobot 实现" |
| 低 | `__init__.py` | 模块文档中"和 nanobot agent/tools"可删除（Charles 已是对标 Cline 的独立实现） |

---

## 五、工具清理建议汇总（按优先级）

### 5.1 高优先级（明确废弃，无业务依赖）

| # | 操作 | 文件 | 理由 |
|---|------|------|------|
| 1 | **删除文件** | `agent/tools/exec_tool.py` | 已废弃，无实例化，逻辑被 `run_commands.py` 完全覆盖 |
| 2 | **删除文件** | `agent/tools/attempt_completion.py` | 孤儿工具，从未注册，依赖的 spawn_agent 已移除 |
| 3 | **修改 `__init__.py`** | 移除 `ExecTool` 导入与 `__all__` 导出 | 配合 #1 |
| 4 | **修改 `__init__.py`** | 移除文档字符串中 ExecTool / attempt_completion 相关行 | 配合 #1 #2 |
| 5 | **修改 `constants.py`** | 删除 `MAX_COMMAND_OUTPUT_CHARS`（仅 exec_tool 使用） | 配合 #1 |
| 6 | **修改 `constants.py`** | `TOOL_PRESETS` 中 `"exec_tool"` 改为 `"run_commands"` | 配合 #1 |
| 7 | **修改 `approval_policy.py`** | 只读白名单移除 `attempt_completion` | 配合 #2 |
| 8 | **修改 `runtime.py` / `todo_write.py` / `types.py`** | 注释中 `attempt_completion` 改为 `submit_and_exit` | 配合 #2 |

### 5.2 中优先级（孤儿工具，但有历史命名兼容）

| # | 操作 | 文件 | 理由 |
|---|------|------|------|
| 9 | **删除 `FileReadTool` 类** | `agent/tools/file_tools.py` | 未导出、未注册，被 `ReadFilesTool` 完全替代 |
| 10 | **修改 `file_tools.py`** | 模块文档字符串更新（仅保留 FileWriteTool 说明） | 配合 #9 |
| 11 | **评估兼容判断** | `agent/context.py:2238` / `agent/runtime.py:1154` | `tool_name == "file_read"` 兼容判断是否保留（建议保留，防止旧会话回放失败） |
| 12 | **修改 `approval_policy.py`** | `"file_read"` 改为 `"read_files"`（或保留两者） | 配合 #9 |

### 5.3 低优先级（代码重复消除，可选优化）

| # | 操作 | 文件 | 理由 |
|---|------|------|------|
| 13 | **抽取公共模块** | 新建 `agent/tools/_text_utils.py` | 消除 `editor.py` 与 `apply_patch.py` 中换行符三函数的重复（共 ~20 行） |
| 14 | **修改 `editor.py` / `apply_patch.py`** | 从 `_text_utils` 导入换行符函数 | 配合 #13 |
| 15 | **清理 nanobot 注释** | `__init__.py` / `file_tools.py` / `web_tool.py` | 将"对标 nanobot"改为"对标 Cline"或保留为"参考 nanobot 实现" |
| 16 | **修复描述误导** | `fetch_web_content.py` | 描述中"用 prompt 分析"实际未实现分析，建议改为"用 prompt 标注抓取意图"或后续实现 |
| 17 | **补齐中止处理** | `fetch_web_content.py` | 当前 `to_thread` 未与 `abort_signal` 组合，长抓取无法即时中止（与 `web_tool.py` 行为不一致） |

### 5.4 不建议改动项

| # | 项目 | 理由 |
|---|------|------|
| - | `editor` + `apply_patch` 同时注册 | 已通过 `routing.py` 实现按模型互斥，符合 Cline 设计意图 |
| - | `file_write` + `editor` 同时注册 | 两者各有适用场景，LLM 生成 `file_write` 比 `editor` create 更直观 |
| - | `ask_question` + `submit_and_exit` 同时注册 | Cline 是互斥，Charles 是共存，实际不冲突（LLM 不会在需要提问时调用 submit） |
| - | `web_search` + `fetch_web_content` 同时注册 | 功能互补，无重复 |

---

## 六、验证方法建议

### 6.1 工具清单验证

```python
# 验证 create_default_tools 返回的工具名清单
from agent.tools import create_default_tools
tools = create_default_tools(working_dir=".", session_id="test")
tool_names = sorted(t.name for t in tools)
print(tool_names)
# 期望输出（清理后）:
# ['access_mcp_resource', 'apply_patch', 'ask_question', 'editor',
#  'fetch_web_content', 'file_write', 'list_files', 'read_files',
#  'run_commands', 'search_codebase', 'submit_and_exit',
#  'switch_to_act_mode', 'switch_to_plan_mode', 'todo_write',
#  'use_mcp_tool', 'web_search']
```

### 6.2 孤儿工具验证

```python
# 验证 ExecTool / AttemptCompletionTool / FileReadTool 不再可导入
# 清理后应抛 ImportError
try:
    from agent.tools.exec_tool import ExecTool
    print("FAIL: ExecTool 仍可导入")
except ImportError:
    print("OK: ExecTool 已删除")

try:
    from agent.tools.attempt_completion import AttemptCompletionTool
    print("FAIL: AttemptCompletionTool 仍可导入")
except ImportError:
    print("OK: AttemptCompletionTool 已删除")
```

### 6.3 nanobot 残留验证

```powershell
# Windows PowerShell 验证残留
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\tools\*.py" -Pattern "nanobot" -CaseSensitive:$false
# 期望: 仅 web_tool.py 中保留"参考 nanobot 实现"类溯源注释
```

### 6.4 routing 互斥验证

```python
# 验证 editor / apply_patch 在 openai-native 模型下互斥
from agent.tools.routing import resolve_tool_routing, DEFAULT_MODEL_TOOL_ROUTING_RULES

# openai-native provider 应启用 apply_patch、禁用 editor
toggles = resolve_tool_routing("openai-native", "gpt-4o", "act", DEFAULT_MODEL_TOOL_ROUTING_RULES)
assert toggles.get("apply_patch") is True
assert toggles.get("editor") is False

# qwen provider 不命中规则，两者都保持默认启用
toggles = resolve_tool_routing("qwen", "qwen-plus", "act", DEFAULT_MODEL_TOOL_ROUTING_RULES)
assert "apply_patch" not in toggles
assert "editor" not in toggles
```

### 6.5 计划表修正建议

本报告发现计划表 `AGENT_COMPARISON_PLAN_V2.md` P3.9 中以下条目需修正：

| 计划表条目 | 原标注 | 实际情况 | 建议修正 |
|-----------|--------|---------|---------|
| 3.9.3 editor | Charles 无 | Charles 有（已注册 EditorTool） | 改为"有，已对齐" |
| 3.9.11 attempt_completion | 已对齐 | Charles 定义但从未注册 | 改为"Charles 未注册（孤儿工具），建议删除" |
| 3.9.16 access_mcp_resource | Charles 无 | Charles 有（已注册 AccessMcpResourceTool） | 改为"有，已对齐" |

---

## 七、附录：Charles 工具文件清单

| 文件 | 行数 | 主要类 | 状态 |
|------|------|-------|------|
| `__init__.py` | 136 | - | 工具集工厂 `create_default_tools` |
| `base.py` | 284 | `BaseTool` | 工具基类 |
| `constants.py` | 156 | - | 输出限制常量 + TOOL_PRESETS |
| `routing.py` | 203 | `ToolRoutingRule` | 模型工具路由 |
| `run_commands.py` | 530 | `RunCommandsTool` | 活跃 |
| `exec_tool.py` | 271 | `ExecTool` | **废弃，建议删除** |
| `read_files.py` | 277 | `ReadFilesTool` | 活跃 |
| `file_tools.py` | 237 | `FileReadTool` + `FileWriteTool` | FileReadTool 孤儿，建议删除 |
| `list_files.py` | 231 | `ListFilesTool` | 活跃 |
| `search_codebase.py` | 245 | `SearchCodebaseTool` | 活跃 |
| `editor.py` | 473 | `EditorTool` | 活跃 |
| `apply_patch.py` | 808 | `ApplyPatchTool` | 活跃 |
| `web_tool.py` | 174 | `WebSearchTool` | 活跃 |
| `fetch_web_content.py` | 311 | `FetchWebContentTool` | 活跃 |
| `ask_question.py` | 114 | `AskQuestionTool` | 活跃 |
| `attempt_completion.py` | 95 | `AttemptCompletionTool` | **孤儿，建议删除** |
| `submit_and_exit.py` | 105 | `SubmitAndExitTool` | 活跃 |
| `todo_write.py` | 207 | `TodoWriteTool` | 活跃 |
| `plan_mode.py` | 297 | `SwitchToActModeTool` + `SwitchToPlanModeTool` | 活跃 |
| `mcp.py` | 352 | `UseMcpToolTool` + `AccessMcpResourceTool` | 活跃 |

**总计**：20 个 .py 文件，~5670 行；活跃工具 17 个，孤儿工具 3 个（ExecTool / FileReadTool / AttemptCompletionTool）。
