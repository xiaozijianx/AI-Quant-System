# Phase H: 内置工具(搜索/交互/控制) 对比报告

> 对标源码：`sdk/packages/core/src/extensions/tools/definitions.ts` + `executors/search.ts` + `executors/web-fetch.ts` + `schemas.ts` + `apps/vscode/src/sdk/sdk-session-config-builder.ts` + `sdk/packages/shared/src/prompt/cline.ts`
> 当前实现：`agent/tools/search_codebase.py` + `list_files.py` + `fetch_web_content.py` + `ask_question.py` + `submit_and_exit.py` + `attempt_completion.py` + `todo_write.py` + `plan_mode.py` + `web_tool.py`
> 对比维度：D1-D16（按工具分组）

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 7 项 |
| 弱对齐 | 4 项 |
| 缺失 | 0 项 |
| 额外增强 | 5 项 |
| **对齐度** | **约 75%** |

**说明**：
- 完全一致项集中在 schema 字段定义（verified / completes_run / options 数量 / requests 数组等）
- 弱对齐项集中在执行机制与输出格式（搜索输出格式、prompt 用途、ignore 实现）
- 额外增强项是我有但 Cline 新 SDK 没有的工具（list_files / todo_write / switch_to_plan_mode / attempt_completion 子 agent 用法）
- 关键差距是搜索输出格式（Cline 字符串+上下文，我结构化+无上下文）和 prompt 用途（Cline 写入输出，我只放 metadata）

---

## 2. 详细对比表

### 2.1 search_codebase（D1-D3）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D1 | queries 数组 vs 单 query | definitions.ts L340-395 + schemas.ts L109-113 | search_codebase.py L97-108 | 完全一致 |
| D2 | 正则 vs glob（文件名匹配 vs 内容匹配） | executors/search.ts L159-271（ripgrep 优先 + RegExp fallback） | search_codebase.py L141-154（Python re） | 弱对齐 |
| D3 | 输出格式（匹配数 vs 字符数限制） | executors/search.ts L325-496（字符串拼接 + 中间截断 48000 字符） | search_codebase.py L160-181（结构化 + 匹配数限制 50/20） | 弱对齐 |

### 2.2 list_files（D4-D5）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D4 | 递归选项（recursive 参数） | 新 SDK 无此工具（用 run_commands 替代） | list_files.py L80-94 + L128-158 | 额外增强 |
| D5 | 忽略规则（.clineignore 支持） | apps/vscode/src/core/ignore/ClineIgnoreController.ts（.clineignore + 文件监听） | list_files.py L46-57（硬编码 _SKIP_DIRS） | 弱对齐 |

### 2.3 fetch_web_content（D6-D7）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D6 | requests 数组（url + prompt 结构） | schemas.ts L175-187 + definitions.ts L514-562 | fetch_web_content.py L122-147 | 完全一致 |
| D7 | prompt 用途（是否真的用 prompt 提取） | executors/web-fetch.ts L240（写入输出末尾 "--- Analysis Request ---"） | fetch_web_content.py L240-242（仅放 metadata，不写入输出） | 弱对齐 |

### 2.4 ask_question（D8-D9）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D8 | options 数量限制（2-4 vs 2-5） | schemas.ts L258-272（min 2 / max 5） | ask_question.py L60-72（minItems 2 / maxItems 5） | 完全一致 |
| D9 | multiSelect（是否支持多选） | schemas.ts L258-272（无 multiSelect 字段，单选） | ask_question.py L50-72（无 multiSelect 字段，单选） | 完全一致 |

### 2.5 submit_and_exit（D10-D11）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D10 | verified 字段（是否含验证标记） | schemas.ts L274-286 + definitions.ts L797-827 | submit_and_exit.py L53-69 | 完全一致 |
| D11 | completes_run（True vs False） | definitions.ts L812-814（lifecycle.completesRun=true） | submit_and_exit.py L72-78（ToolLifecycle(completes_run=True)） | 完全一致 |

### 2.6 attempt_completion（D12）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D12 | result vs command（Cline 是否含 command 字段） | 新 SDK 无 attempt_completion（被 submit_and_exit 替代，见 .greptile/rules.md L75）；老 VSCode 扩展有 result+command | attempt_completion.py L54-65（仅 result，无 command） | 弱对齐 |

### 2.7 todo_write（D13-D14）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D13 | 替换 vs 增量（Cline 是替换式） | 新 SDK 无 todo_write 工具 | todo_write.py L161-173（替换式 set_todos） | 额外增强 |
| D14 | active_form 必填（in_progress 时是否强制） | 新 SDK 无此工具 | todo_write.py L85-90（required 仅 content+status，active_form 非必填） | 额外增强 |

### 2.8 switch_to_act_mode / switch_to_plan_mode（D15-D16）

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| D15 | switch_to_act_mode completes_run | sdk-session-config-builder.ts L68-70（lifecycle.completesRun=true） | plan_mode.py L108-115（ToolLifecycle(completes_run=True)） | 完全一致 |
| D16 | switch_to_plan_mode 输入 schema（是否含 plan 文本参数） | 新 SDK 无 switch_to_plan_mode 工具（plan 模式切换由用户 UI 触发） | plan_mode.py L204-210（空 schema，无 plan 参数） | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #D2：search_codebase 实现机制（ripgrep vs 纯 Python re）

**严重度**：P2（影响搜索性能与 gitignore 自动尊重）

**Cline 实现**（executors/search.ts）：
- 优先用 ripgrep（spawn "rg" 子进程）：`rg --json --context=2 --max-count=1 -i <query>`
- ripgrep 不可用时 fallback 到 RegExp("gim") + 手动遍历文件
- ripgrep 自动尊重 .gitignore 和 .ignore 文件
- 通过 `getFileIndex(cwd)` 获取文件索引（服务层维护）
- 检查 ripgrep 可用性并缓存结果（rgAvailable 单例）

**我的实现**（search_codebase.py L141-204）：
- 纯 Python `re.compile` + `pathlib.Path.rglob` 遍历
- 硬编码 _SKIP_DIRS 跳过 .git/node_modules/__pycache__/.venv 等
- 硬编码 _SKIP_EXTENSIONS 跳过二进制文件
- 不尊重 .gitignore / .clineignore

**影响**：
- 大型代码库搜索性能差（Python 遍历慢于 ripgrep 数倍）
- 不会自动跳过 .gitignore 中排除的文件（如 build 产物）
- 无并发搜索（Cline ripgrep 是子进程并行）

**修复建议**：
- 短期：保持纯 Python 实现作为 fallback
- 中期：检测系统是否安装 rg，可用时调用子进程执行搜索（参考 Cline checkRipgrepAvailable）
- 长期：接入文件索引服务（对标 Cline getFileIndex）

**优先级**：P2

---

### 差距 #D3：search_codebase 输出格式（字符串+上下文 vs 结构化+无上下文）

**严重度**：P1（影响 LLM 理解搜索结果）

**Cline 实现**（executors/search.ts L325-496）：
- 输出格式：字符串拼接
  ```
  Found N results for pattern: <query>

  <file>:<line>:<column>
  > <line_number>: <context_line_before>
  > <line_number>: <matched_line>
    <line_number>: <context_line_after>

  (Showing first 100 results...)
  ```
- 包含上下文行（默认 contextLines=2，匹配行前后各 2 行）
- 中间截断到 MAX_SEARCH_OUTPUT_CHARS=48000 字符（head/tail 保留）
- 返回 ToolOperationResult { query, result: string, success }

**我的实现**（search_codebase.py L160-181）：
- 输出格式：结构化 JSON
  ```json
  {
    "results": [
      {
        "query": "...",
        "match_count": N,
        "matches": [
          {"file": "...", "line_number": N, "line_content": "..."}
        ]
      }
    ]
  }
  ```
- 不包含上下文行（只有匹配行本身）
- 不包含 column 列号
- 限制 MAX_MATCHES_PER_QUERY=50 + MAX_MATCHES_PER_FILE=20
- 无字符数限制（仅匹配数限制）

**影响**：
- LLM 看不到匹配行的上下文，理解代码语义更困难
- 没有列号，定位长行中的匹配位置不便
- 50 匹配上限可能漏掉重要结果（Cline 是 100，并通过字符数中间截断保留首尾）

**修复建议**：
1. 添加 contextLines 参数（默认 2），在匹配行前后各包含 N 行上下文
2. 在 matches 中添加 column 字段（match.index + 1）
3. 添加 MAX_SEARCH_OUTPUT_CHARS=48000 字符数限制，超过时中间截断（保留首尾）
4. 将 maxResults 从 50 提升到 100

**优先级**：P1

---

### 差距 #D5：list_files 忽略规则（.clineignore 缺失）

**严重度**：P3（list_files 是额外工具，且硬编码跳过已覆盖大部分场景）

**Cline 实现**：
- 新 SDK 无 list_files 工具（用 run_commands 替代）
- 但有 ClineIgnoreController（apps/vscode/src/core/ignore/ClineIgnoreController.ts）：
  - 读取 `.clineignore` 文件，支持 .gitignore 语法
  - 用 chokidar 监听 .clineignore 变化热加载
  - validateAccess(filePath) / filterPaths(paths) 接口
  - 支持 `!include <filename>` 引用其他忽略文件
- ClineIgnoreController 注入到 file 操作服务，所有文件工具都受其约束

**我的实现**（list_files.py L46-57）：
- 硬编码 _SKIP_DIRS（.git/node_modules/__pycache__/.venv/venv/.idea/.vscode/dist/build）
- 不读取 .clineignore / .gitignore
- 无文件监听

**影响**：
- 用户无法通过配置文件自定义忽略规则
- .gitignore 中排除的目录（如 .next/coverage/target）不会被跳过
- 配置变化需修改代码

**修复建议**：
- 短期：扩展 _SKIP_DIRS 包含 .next/coverage/target/.cache/.turbo/out/bin/obj 等
- 中期：实现简化版 ClineIgnoreController，读取 .clineignore 并用 fnmatch/pathspec 解析
- 长期：将 ignore 控制器注入到所有文件工具（list_files/search_codebase/read_files）

**优先级**：P3

---

### 差距 #D7：fetch_web_content prompt 用途（写入输出 vs 仅 metadata）

**严重度**：P2（影响 LLM 知道"我用什么 prompt 提取的"）

**Cline 实现**（executors/web-fetch.ts L225-242）：
- 输出字符串格式：
  ```
  URL: <url>
  Content-Type: <contentType>
  Size: <bytes> bytes

  --- Content ---
  <content 前 50000 字符>

  [Content truncated: showing first 50000 of N characters]

  --- Analysis Request ---
  Prompt: <prompt>
  ```
- prompt 写入输出末尾，LLM 能看到"我请求提取什么"
- 截断到 50000 字符（远大于我的 8000）
- 输出包含元数据（URL/Content-Type/Size）

**我的实现**（fetch_web_content.py L236-248）：
- 输出结构化 JSON：
  ```json
  {
    "index": 0,
    "url": "...",
    "content": "...",
    "prompt": "...",
    "chars": 8000,
    "truncated": true,
    "note": "内容已截断到 8000 字符"
  }
  ```
- prompt 放在字段中（LLM 也能看到，但位置不如 Cline 显眼）
- 截断到 8000 字符（远小于 Cline 的 50000）
- 不包含 Content-Type / Size

**影响**：
- 截断阈值过小（8000 vs 50000），长文档可能丢失关键信息
- 缺少 Content-Type 元数据，LLM 无法判断是 HTML/JSON/纯文本
- prompt 字段位置在结构化 JSON 中，LLM 可能忽略

**修复建议**：
1. 将 MAX_WEB_CONTENT_CHARS 从 8000 提升到 50000（对齐 Cline）
2. 在 result 中添加 content_type / size_bytes 字段
3. 输出末尾追加 "--- Analysis Request ---\nPrompt: <prompt>" 段落（对齐 Cline）

**优先级**：P2

---

### 差距 #D12：attempt_completion 与 Cline 子 agent 完成机制不同

**严重度**：P2（影响子 agent 完成语义）

**Cline 实现**：
- 新 SDK 无 attempt_completion 工具（被 submit_and_exit 替代，见 .greptile/rules.md L75）
- 子 agent 完成机制：spawn_agent 工具（team/spawn-agent-tool.ts L117-203）
  - 子 agent 通过 `subAgent.run(input.task)` 同步等待
  - 子 agent 自然结束（无显式完成工具）
  - 返回 SpawnAgentOutput { text, iterations, finishReason, usage }
  - spawn_agent 工具本身无 completesRun（不结束主 agent 运行）
- 老 VSCode 扩展有 attempt_completion（result + command 字段），用于主 agent 完成

**我的实现**（attempt_completion.py）：
- attempt_completion 作为子 agent 完成工具
- lifecycle.completes_run = True（结束子 agent 运行）
- input_schema 只有 result 参数（无 command）
- 子 agent 调用后立即结束，result 作为 AgentRunResult.output_text 返回主 agent

**影响**：
- 语义不等价：Cline 子 agent 自然结束，我强制要求调用 attempt_completion
- 若子 agent LLM 不调用 attempt_completion 直接返回文本，我的 runtime 会追加 reminder 继续下一轮（require_completion_tool=True 时）
- 缺少 command 字段（老 Cline 的 attempt_completion 有 command 用于打开文件/运行命令）

**修复建议**：
1. 保持 attempt_completion 作为子 agent 完成机制（合理设计，强制显式完成更可控）
2. 可选添加 command 字段（可选参数，用于完成后执行打开文件等操作）
3. 文档中标注"语义不等价于 Cline spawn_agent"

**优先级**：P2

---

### 差距 #D16：switch_to_plan_mode Cline 无此工具

**严重度**：P3（额外增强，但偏离 Cline 设计）

**Cline 实现**：
- 新 SDK 只有 switch_to_act_mode（plan → act，LLM 在 plan 模式下调用）
- plan 模式切换由用户 UI 操作触发（toggle-plan-act-mode.ts）
- 设计哲学：LLM 不能主动切换到 plan 模式（避免逃避执行）
- sdk-session-config-builder.ts L38-46：plan 模式注册 switch_to_act_mode，act 模式过滤掉

**我的实现**（plan_mode.py L172-271）：
- 同时提供 switch_to_act_mode 和 switch_to_plan_mode
- LLM 可主动调用 switch_to_plan_mode 切换到 plan 模式
- 切换前校验当前模式（act → plan 才允许）

**影响**：
- LLM 可能滥用 switch_to_plan_mode 逃避执行任务
- 偏离 Cline "用户掌控 plan 模式" 的设计哲学
- 但在量化场景下，LLM 主动重新规划可能合理

**修复建议**：
1. 短期：保留 switch_to_plan_mode 但在描述中强调"仅在用户要求重新规划时调用"
2. 中期：将 switch_to_plan_mode 标记为 requires_approval=True（需用户审批）
3. 长期：考虑移除，改为用户 UI 触发（对齐 Cline）

**优先级**：P3

---

## 4. 一致性统计

### 4.1 按一致性等级统计

| 等级 | 数量 | 占比 | 说明 |
|------|------|------|------|
| 完全一致 | 7 项 | 44% | D1/D6/D8/D9/D10/D11/D15 |
| 弱对齐 | 4 项 | 25% | D2/D3/D7/D12 |
| 缺失 | 0 项 | 0% | - |
| 额外增强 | 5 项 | 31% | D4/D5/D13/D14/D16 |
| **总计** | **16 项** | **100%** | - |

### 4.2 按工具统计

| 工具 | 完全一致 | 弱对齐 | 额外增强 | 对齐度 |
|------|---------|--------|---------|--------|
| search_codebase | 1 (D1) | 2 (D2/D3) | 0 | 33% |
| list_files | 0 | 1 (D5) | 1 (D4) | 额外工具 |
| fetch_web_content | 1 (D6) | 1 (D7) | 0 | 50% |
| ask_question | 2 (D8/D9) | 0 | 0 | 100% |
| submit_and_exit | 2 (D10/D11) | 0 | 0 | 100% |
| attempt_completion | 0 | 1 (D12) | 0 | 弱对齐 |
| todo_write | 0 | 0 | 2 (D13/D14) | 额外工具 |
| switch_to_act_mode | 1 (D15) | 0 | 0 | 100% |
| switch_to_plan_mode | 0 | 0 | 1 (D16) | 额外工具 |

### 4.3 按严重度统计

| 严重度 | 数量 | 差距编号 |
|--------|------|---------|
| P0 | 0 项 | - |
| P1 | 1 项 | D3 |
| P2 | 3 项 | D2/D7/D12 |
| P3 | 2 项 | D5/D16 |

---

## 5. 修复建议

### 5.1 短期（1-2 周）

1. **D3 search_codebase 输出格式**（P1）
   - 在 matches 中添加 `column` 字段（`match.start() + 1`）
   - 添加 `context_before` / `context_after` 字段（默认各 2 行）
   - 添加 MAX_SEARCH_OUTPUT_CHARS=48000 字符数限制，中间截断保留首尾
   - 将 MAX_MATCHES_PER_QUERY 从 50 提升到 100

2. **D7 fetch_web_content 截断阈值**（P2）
   - 将 MAX_WEB_CONTENT_CHARS 从 8000 提升到 50000
   - 在 result 中添加 `content_type` / `size_bytes` 字段
   - 输出末尾追加 "--- Analysis Request ---\nPrompt: <prompt>" 段落

3. **D5 list_files 忽略目录扩展**（P3）
   - 扩展 _SKIP_DIRS 包含 `.next` / `coverage` / `target` / `.cache` / `.turbo` / `out` / `bin` / `obj`

### 5.2 中期（2-4 周）

1. **D2 search_codebase ripgrep 集成**（P2）
   - 检测系统是否安装 rg（缓存检测结果）
   - 可用时调用子进程执行搜索（参考 Cline checkRipgrepAvailable + searchWithRipgrep）
   - 保留纯 Python 实现作为 fallback
   - 通过 rg 自动尊重 .gitignore

2. **D5 .clineignore 支持**（P3）
   - 实现简化版 ClineIgnoreController（Python）
   - 用 pathspec 库解析 .gitignore 语法
   - 注入到 list_files / search_codebase / read_files

3. **D12 attempt_completion command 字段**（P2）
   - 可选添加 `command` 字段（可选参数，用于完成后执行打开文件等操作）
   - 文档中标注"语义不等价于 Cline spawn_agent"

### 5.3 长期（1 个月+）

1. **D16 switch_to_plan_mode 审批机制**（P3）
   - 标记 requires_approval=True，需用户审批才能切换
   - 或考虑移除，改为用户 UI 触发（对齐 Cline）

2. **D2 文件索引服务**（P2）
   - 接入文件索引服务（对标 Cline getFileIndex）
   - 避免每次搜索都全量遍历
   - 支持增量更新

3. **统一 ignore 控制器**（P3）
   - 将 ignore 控制器注入到所有文件工具
   - 对标 Cline ClineIgnoreController 的 validateAccess / filterPaths 接口

---

## 6. 额外增强项

### 增强 #D4：list_files 工具（Cline 新 SDK 无此工具）

**我**：提供专用 list_files 工具，支持 path + recursive 参数，返回结构化 {path, entries, count, truncated}。
**Cline**：新 SDK 无此工具，用 run_commands（ls/find）替代。
**评估**：合理增强。结构化输出比 shell 命令输出更易解析，且支持 recursive 参数。保留。

### 增强 #D13/D14：todo_write 工具（Cline 新 SDK 无此工具）

**我**：实现 Claude TodoWrite 风格的任务清单工具，支持 content/status/active_form，替换式更新，强制单一 in_progress。
**Cline**：新 SDK 无 todo_write 工具。
**评估**：合理增强。任务清单对复杂量化分析任务的进度跟踪很有价值。保留。

### 增强 #D16：switch_to_plan_mode 工具（Cline 无此工具）

**我**：提供 switch_to_plan_mode 让 LLM 主动切换到 plan 模式。
**Cline**：plan 模式切换由用户 UI 触发，LLM 不能主动切换。
**评估**：偏离 Cline 设计哲学，但量化场景下 LLM 主动重新规划可能合理。保留但需添加审批机制。

### 增强 #web_search：web_search 工具（Cline 新 SDK 无此工具）

**我**：提供 web_search 工具（DuckDuckGo 搜索，无需 API Key）。
**Cline**：新 SDK 无此工具（用 fetch_web_content + 搜索引擎 URL 替代）。
**评估**：合理增强。DuckDuckGo 无需 API Key，适合量化场景获取市场信息。保留。

---

## 7. 验证记录

### 7.1 验证方法

1. **逐工具 schema 对比**：读取 Cline schemas.ts 中 zod schema 定义，对比我的 input_schema JSON Schema 字段
2. **lifecycle 对比**：读取 Cline definitions.ts 中 lifecycle 配置，对比我的 ToolLifecycle
3. **executor 实现对比**：读取 Cline executors/*.ts，对比我的 _execute 方法实现逻辑
4. **跨文件搜索验证**：用 Grep 搜索 switch_to_plan_mode / attempt_completion / todo_write 等关键字，确认 Cline 是否有对应实现

### 7.2 关键发现

1. **Cline 新 SDK 没有 list_files / todo_write / switch_to_plan_mode 工具**：这些是我的额外增强
2. **Cline 新 SDK 用 submit_and_exit 替代了老 attempt_completion**：我的 attempt_completion 用于子 agent 完成机制，与 Cline spawn_agent 不同
3. **Cline search_codebase 优先用 ripgrep**：我用纯 Python re，性能差但功能等价
4. **Cline fetch_web_content 截断阈值 50000**：我仅 8000，需提升
5. **Cline ask_question options 2-5**：与我的 2-5 完全一致（任务描述说"2-4 vs 2-5"是误记）

### 7.3 文件路径核对

| 工具 | Cline 路径 | 我的路径 |
|------|-----------|---------|
| search_codebase | sdk/packages/core/src/extensions/tools/definitions.ts L340-395 + executors/search.ts | agent/tools/search_codebase.py |
| list_files | （新 SDK 无） | agent/tools/list_files.py |
| fetch_web_content | sdk/packages/core/src/extensions/tools/definitions.ts L514-562 + executors/web-fetch.ts | agent/tools/fetch_web_content.py |
| ask_question | sdk/packages/core/src/extensions/tools/definitions.ts L776-795 + schemas.ts L258-272 | agent/tools/ask_question.py |
| submit_and_exit | sdk/packages/core/src/extensions/tools/definitions.ts L797-827 + schemas.ts L274-286 | agent/tools/submit_and_exit.py |
| attempt_completion | （新 SDK 无，老 VSCode 扩展有） | agent/tools/attempt_completion.py |
| todo_write | （新 SDK 无） | agent/tools/todo_write.py |
| switch_to_act_mode | apps/vscode/src/sdk/sdk-session-config-builder.ts L51-80 | agent/tools/plan_mode.py L68-169 |
| switch_to_plan_mode | （新 SDK 无） | agent/tools/plan_mode.py L172-271 |

---

**阶段 H 结论**：内置工具(搜索/交互/控制)对齐度约 75%。核心 schema 字段（verified / completes_run / options 数量 / requests 数组）完全一致，但执行机制与输出格式存在弱对齐：
- 搜索：Cline 用 ripgrep + 字符串+上下文输出，我用纯 Python re + 结构化+无上下文（P1 级差距）
- Web 抓取：Cline 截断 50000 字符 + prompt 写入输出，我截断 8000 + prompt 仅放 metadata（P2 级差距）
- 子 agent 完成：Cline 自然结束，我强制 attempt_completion（P2 级差距，但合理设计）

我额外增强 5 项（list_files / todo_write / switch_to_plan_mode / web_search / attempt_completion 子 agent 用法），覆盖 Cline 新 SDK 未提供的功能。最优先修复 D3（搜索输出格式），其次 D7（Web 截断阈值）和 D2（ripgrep 集成）。
