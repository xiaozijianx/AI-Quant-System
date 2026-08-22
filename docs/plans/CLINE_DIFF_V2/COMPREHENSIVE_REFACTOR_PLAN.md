# Charles 全面对齐 Cline 综合修改计划

> 基于 Phase 1-7 共 121 份对比报告的综合分析
> 生成时间：2026-07-29
> 核心原则：完整复现 Cline 实现，量化场景有所取舍，消除打乱 Cline 设计的"伪增强"

---

## 目录

1. [修改优先级总览](#1-修改优先级总览)
2. [P0 阻塞性修复（立即执行）](#2-p0-阻塞性修复立即执行)
3. [P1 重要功能修复（短期执行）](#3-p1-重要功能修复短期执行)
4. [P2 对齐改进（中期执行）](#4-p2-对齐改进中期执行)
5. [P3 可选优化（长期执行）](#5-p3-可选优化长期执行)
6. [Charles 增强项评估](#6-charles-增强项评估)
7. [nanobot 残留清理](#7-nanobot-残留清理)
8. [执行顺序与依赖关系](#8-执行顺序与依赖关系)

---

## 1. 修改优先级总览

### 1.1 统计总览

| 优先级 | 数量 | 说明 |
|--------|------|------|
| P0 | 14 项 | 阻塞性问题：工具无法执行 / 安全风险 / 功能 bug / nanobot 工具残留 |
| P1 | 20 项 | 重要功能缺失：影响 LLM 输出质量和用户体验 / Prompt 文件清理 |
| P2 | 28 项 | 对齐改进：缩小与 Cline 的实现差距 |
| P3 | 15 项 | 可选优化：合理偏离或低影响差异 |
| **合计** | **77 项** | |

### 1.2 按模块分布

| 模块 | P0 | P1 | P2 | P3 | 小计 |
|------|----|----|----|----|------|
| 工具系统 | 5 | 6 | 8 | 3 | 22 |
| 技能系统 | 5 | 3 | 4 | 2 | 14 |
| System Prompt | 0 | 2 | 5 | 2 | 9 |
| AGENTS.md | 1 | 2 | 2 | 1 | 6 |
| 核心引擎 | 1 | 4 | 5 | 4 | 14 |
| nanobot 清理 | 2 | 0 | 2 | 1 | 5 |
| 前端/架构 | 0 | 3 | 2 | 2 | 7 |

---

## 2. P0 阻塞性修复（立即执行）

### P0-1: SKILL.md write-report 命令参数与脚本不匹配

- **来源**：P4.11
- **问题**：SKILL.md 写 `--stock`/`--title`，脚本 `report_generator.py` 实际要 `--analysis_file`（必填）
- **影响**：agent 调用 write-report 技能必失败
- **修改文件**：`agent_config/skills/write-report/SKILL.md`
- **修改方案**：将 Step 4 的命令参数改为 `--analysis_file <分析结果文件路径>`，并更新参数说明

### P0-2: SKILL.md sentiment-analysis 命令参数与脚本不匹配

- **来源**：P4.13
- **问题**：SKILL.md 写 `--stock`，脚本 `sentiment_scorer.py` 和 `event_detector.py` 实际要 `--news_file`（必填）
- **影响**：agent 调用 sentiment-analysis 技能必失败
- **修改文件**：`agent_config/skills/sentiment-analysis/SKILL.md`
- **修改方案**：将 Step 2/Step 3 的命令参数改为 `--news_file <新闻数据文件路径>`

### P0-3: SKILL.md bond-credit-review 脚本文件不存在

- **来源**：P4.14
- **问题**：SKILL.md 引用 `bond_credit_review.py`，但该脚本文件不存在
- **影响**：技能完全无法执行
- **修改文件**：`agent_config/skills/bond-credit-review/SKILL.md` + 新建脚本或移除技能
- **修改方案**：创建 `bond_credit_review.py` 脚本，或移除 bond-credit-review 技能目录

### P0-4: web_tool / fetch_web_content 截断阈值过激进

- **来源**：P3.21, P3.22
- **问题**：web_tool 和 fetch_web_content 均使用 8000 字符截断，Cline 为 50000 字符（1/6.25）
- **影响**：用户明确反馈"网络搜索工具很不好用"，搜索结果和网页内容严重不完整
- **修改文件**：`agent/tools/web_tool.py`, `agent/tools/fetch_web_content.py`（或对应工具文件）
- **修改方案**：
  - web_tool：8000 → 50000 字符
  - fetch_web_content：8000 → 50000 字符
  - fetch_web_content：增加响应大小保护（5MB 流式检查）
  - fetch_web_content：区分 Content-Type（HTML/JSON/其他）

### P0-5: 全局 AGENTS.md 路径拼写错误

- **来源**：P6.7
- **问题**：Charles 用 `.agent`（单数），Cline 用 `.agents`（复数），位于 `agent/context.py` L472
- **影响**：无法读取 Cline 生态全局规则
- **修改文件**：`agent/context.py` L472
- **修改方案**：`.agent` → `.agents`（一行修改）

### P0-6: invalid_tool_messages 双重追加 bug

- **来源**：P2.7
- **问题**：L687-689 立即追加+emit，L722-724 再次追加到 tool_messages，L731-733 再次追加+emit
- **影响**：消息历史中出现重复的 invalid_tool_messages，可能导致 LLM 混乱
- **修改文件**：`agent/runtime.py`
- **修改方案**：移除重复的追加逻辑，保留第一次追加+emit 即可

### P0-7: 工具结果存入 message 未截断

- **来源**：P2.4
- **问题**：工具 output 在 emit 时截断为 8000 字符，但存入 message history 的 output 未截断
- **影响**：大输出工具（如 run_commands / search_codebase）的结果可能撑爆上下文
- **修改文件**：`agent/runtime.py`
- **修改方案**：在存入 message 前应用 head+tail 截断（参考 Cline 的 48000 字符 head+tail 策略）

### P0-8: ControlledStopError status 映射不一致

- **来源**：P1.6, P2.2
- **问题**：Cline 的 `ControlledStopError` → `status="aborted"`，Charles → `status="completed"`
- **影响**：前端状态展示错误，controlled_stop 被误认为正常完成
- **修改文件**：`agent/runtime.py`
- **修改方案**：`ControlledStopError` → `status="aborted"`（对齐 Cline）

### P0-9: before_run hook stop 路径不一致

- **来源**：P2.2
- **问题**：before_tool 路径抛 `ControlledStopError`，before_run 路径抛 `RuntimeError` → failed
- **影响**：before_run hook 中止时状态不正确
- **修改文件**：`agent/runtime.py`
- **修改方案**：before_run 路径也抛 `ControlledStopError`

### P0-10: 预注入 reminder 不 emit message-added 事件

- **来源**：P2.5
- **问题**：`_inject_completion_reminder` 只 push 不 emit，前端无法感知
- **影响**：前端看不到预注入的 reminder 消息
- **修改文件**：`agent/runtime.py`
- **修改方案**：在 push 后 emit `message-added` 事件

### P0-11: routes/chat.py 旧 nanobot 路由残留

- **来源**：P1.2
- **问题**：`routes/chat.py` 仍引用 `third_party/charles_bundle/charles-nanobot/agent.py`
- **影响**：未挂载但代码存在，维护困惑
- **修改文件**：`routes/chat.py`
- **修改方案**：删除文件或移至 `legacy/` 目录

### P0-12: always 预加载机制（nanobot 残留）

- **来源**：P4.16, P4.20, P5.10
- **问题**：`always: true` 字段源自 nanobot，Cline 无此机制，打破 on-demand 设计哲学
- **影响**：部分技能绕过 on-demand 加载直接注入 System Prompt
- **修改文件**：
  - `agent/skills/loader.py`（移除 `always` 字段解析）
  - `agent/skills/registry.py`（移除 `get_always_skills()` / `load_always_instructions()` / `load_always_instructions_as_rule()`）
  - `agent/context.py`（移除 always_skills 注入链路）
  - `agent_config/skills/read-pdf/SKILL.md`（移除 `always: true`）
  - `agent_config/system_prompt.yaml`（移除 `always_skills` 开关）
- **修改方案**：完整移除 always 预加载机制，所有技能走 on-demand 加载

### P0-13: when_to_use 字段（nanobot 残留）

- **来源**：P4.5, P4.20, P5.9
- **问题**：`when_to_use` 字段 Cline 不支持，应内嵌到 `description` 的 "Use when ..." 句式
- **影响**：服务于 nanobot 风格的 skills_summary 段（本身也应移除）
- **修改文件**：
  - `agent/skills/loader.py`（移除 `when_to_use` 字段解析）
  - `agent/skills/registry.py`（移除 `build_summary()` 中的 when_to_use 使用）
  - 8 个 `agent_config/skills/*/SKILL.md`（将 `when_to_use` 内容合并到 `description`）
- **修改方案**：将 `when_to_use: <内容>` 合并到 `description` 末尾，改为 "Use when <内容>" 句式

### P0-14: 工具实现逻辑全面 Cline 化（删除孤儿 + 替换 nanobot 实现）

- **来源**：P3.1-P3.24 全阶段
- **问题**：Charles 的工具存在两类问题：
  1. **孤儿工具**：Cline 无此工具，功能与 Cline 工具完全重合 → 删除
  2. **nanobot 实现残留**：Cline 和 Charles 都有此工具，但 Charles 的实现逻辑从 nanobot 迁移而来，与 Cline 实现不同 → **替换为 Cline 实现逻辑**
- **用户策略**："即使双方都有同一功能工具，如果 Charles 的实现是从 nanobot 迁移的，就需要替换为 Cline 的实现逻辑"

#### 第一部分：删除孤儿工具

| 文件 | 工具 | Cline 对标 | 删除理由 |
|------|------|-----------|---------|
| `agent/tools/exec_tool.py` | ExecTool | execute_command | 孤儿工具，功能与 run_commands 完全重合 |
| `agent/tools/file_tools.py` | FileReadTool | read_file | 孤儿工具，功能与 read_files 完全重合 |
| `agent/tools/attempt_completion.py` | AttemptCompletionTool | attempt_completion | 死代码，从未注册，依赖的 spawn_agent 已移除 |

FileWriteTool（file_tools.py）：检查 `__init__.py` 注册状态，已注册 → 保留并对齐 Cline `write_to_file`；未注册 → 删除。

#### 第二部分：替换 nanobot 实现逻辑为 Cline 实现逻辑

以下工具双方都有，但 Charles 的实现逻辑源自 nanobot，需要替换为 Cline 的实现方式：

| 工具 | nanobot 实现逻辑（当前） | Cline 实现逻辑（目标） | 对应修改项 |
|------|------------------------|----------------------|-----------|
| **web_tool.py** (WebSearchTool) | DuckDuckGo HTML 抓取 + 8000 字符截断 | Cline 的 web_search 实现（更大截断 + 结构化结果） | P0-4 |
| **fetch_web_content.py** (FetchWebContentTool) | 8000 字符截断 + 无响应大小保护 | Cline 的 web_fetch：50000 字符截断 + 5MB 流式检查 + Content-Type 区分 | P0-4 |
| **run_commands.py** (RunCommandsTool) | 串行 `for` 循环执行 + 600s 超时 + 8000 字符截断 + `_guard_command` 复用自 ExecTool(nanobot shell.py) | Cline 的 execute_command：`Promise.all` 并行 + 30s 超时 + 48000 字符 head+tail 截断 | P1-11 |
| **search_codebase.py** (SearchCodebaseTool) | Python `re` 模块 + 大小写敏感 + 无上下文行 + 无字符截断 | Cline 的 search_files：ripgrep + 大小写不敏感 + 2 行上下文 + 48000 字符 head+tail 截断 | P1-1 |
| **read_files.py** (ReadFilesTool) | 串行读取 + 一次性 `read_bytes()` + 1 层截断(16000 字符) | Cline 的 read_file：`Promise.all` 并行 + 流式 `createReadStream` + 3 层截断(行数 2000 + 单行 2000 字符 + 总字符 48000) | P1-2 |
| **ask_question.py** (AskQuestionTool) | "发送即返回"（nanobot 非阻塞模式） | Cline 的 ask_followup_question：`asyncio.Event` 阻塞等待用户答案 | P1-10 |
| **apply_patch.py** (ApplyPatchTool) | 缺 cwd 越界检查 + 缺 Levenshtein 模糊匹配 | Cline 的 apply_patch：`restrictToCwd` 检查 + Levenshtein≥0.66 回退 | P1-5, P2-4 |
| **editor.py** (EditorTool) | 缺 cwd 越界检查 | Cline 的 replace_in_file：`restrictToCwd` 检查 | P1-5 |
| **list_files.py** (ListFilesTool) | 无 `.gitignore` 支持 + 无受限路径保护 | Cline 的 list_files：`.gitignore` 增量解析 + 受限路径保护 + 10s 超时 | P1-6 |
| **plan_mode.py** (SwitchToPlanModeTool) | 缺 auto-continue + 缺会话重建 | Cline 的 switch_mode：`ACT_MODE_CONTINUATION_PROMPT` 自动续跑 + `rebuildSessionForMode` | P1-3 |

#### 第三部分：保留的工具（实现已对齐 Cline 或合理增强）

| 工具 | 状态 | 说明 |
|------|------|------|
| mcp.py (UseMcpToolTool) | **已对齐** + 合理增强 | per-tool 策略 + name-transform 对齐；Charles 增强属合理偏离（P1-19 补 auto_approve） |
| todo_write.py (TodoWriteTool) | **合理偏离** | Cline 有 focus_chain 但实现差异大；Charles 对标 Claude 的 todo_write 是合理设计选择 |
| submit_and_exit.py (SubmitAndExitTool) | **合理偏离** | 功能对标 Cline 的 summarize_task，实现方式适配量化场景 |

#### 执行顺序

1. **先删除孤儿工具**（P0-14 第一部分）→ 清理 `__init__.py` 注册表
2. **再逐个替换 nanobot 实现逻辑**（P0-14 第二部分）→ 按 P0-4 → P1-1 → P1-2 → P1-10 → P1-11 顺序执行
3. **每替换一个工具后运行测试**确认功能正常

---

## 3. P1 重要功能修复（短期执行）

### P1-1: search_codebase 补齐上下文行 + 字符截断 + 大小写不敏感

- **来源**：P3.13
- **问题**：
  - 无上下文行（Cline 默认 2 行 `>` 前缀标记）
  - 无字符级截断（Cline 48000 字符 head+tail，宽泛 pattern 撑爆上下文）
  - 大小写敏感（Cline 不敏感，行为相反，漏匹配）
  - 无列号显示
  - 无截断恢复提示
- **修改文件**：`agent/tools/search_codebase.py`
- **修改方案**：
  1. 增加上下文行：匹配行前后各 2 行，`>` 前缀标记
  2. 增加字符截断：48000 字符 head+tail 截断
  3. 改为大小写不敏感（`re.IGNORECASE`）
  4. 增加列号显示
  5. 增加截断恢复提示 "Narrow the pattern or scope"

### P1-2: read_files 补齐 3 层截断 + 流式读取

- **来源**：P3.10
- **问题**：
  - Charles 1 层截断（16000 字符），Cline 3 层（行数 2000 + 单行 2000 字符 + 总字符 48000）
  - Charles 一次性 `read_bytes()`，Cline 流式 `createReadStream`
  - Charles 串行读取，Cline 并行
- **修改文件**：`agent/tools/read_files.py`
- **修改方案**：
  1. 增加 3 层截断：MAX_LINES=2000, MAX_LINE_CHARS=2000, MAX_CHARS=48000
  2. 改为流式读取（`open(path, 'rb')` 逐行读取）
  3. 改为并行读取（`asyncio.gather`）

### P1-3: plan_mode 补齐 auto-continue + 会话重建

- **来源**：P3.16
- **问题**：
  - plan→act 切换后无 auto-continue（Cline 有 `ACT_MODE_CONTINUATION_PROMPT`）
  - 无会话重建（Cline 有 `rebuildSessionForMode`）
- **修改文件**：`agent/runtime.py`, `agent/server.py`
- **修改方案**：
  1. plan→act 切换后注入 `ACT_MODE_CONTINUATION_PROMPT` 自动续跑
  2. 实现 `rebuild_session_for_mode()` 方法（可选，量化场景 session 级隔离已部分覆盖）

### P1-4: Base Prompt 补齐 13 项行为约束

- **来源**：P5.3
- **问题**：Charles DEFAULT 828 chars vs Cline 3695 chars，缺失 13 项行为约束
- **修改文件**：`agent/context.py`（`DEFAULT_CHARLES_SYSTEM_PROMPT`）+ `agent_config/prompts/charles_base.txt`（如存在）
- **修改方案**：补齐以下 13 项（中文翻译适配量化场景）：
  1. 上下文收集具体指引
  2. 审问与详细回答
  3. 澄清优于假设
  4. 代码约定遵循
  5. 库限制
  6. 完整代码（无省略）
  7. 假设显式化
  8. 规划展示
  9. 并行调用示例
  10. 文件验证
  11. 主动帮助
  12. 完成总结
  13. 简单问题直答

### P1-5: apply_patch / editor / file_write 补齐 cwd 越界检查

- **来源**：P3.12, P3.23
- **问题**：三个文件写入工具均无 `restrictToCwd` 检查，可越界写到 cwd 外
- **修改文件**：`agent/tools/apply_patch.py`, `agent/tools/editor.py`, `agent/tools/file_write.py`
- **修改方案**：增加 `restrict_to_cwd(path)` 检查函数，在 execute 入口校验

### P1-6: list_files 补齐 .gitignore 支持 + 受限路径保护

- **来源**：P3.14
- **问题**：
  - 无 `.gitignore` 支持（gitignored 文件如 `.env` 会泄露到 LLM 上下文）
  - 无受限路径保护（可列出 `/` 或 `~`）
- **修改文件**：`agent/tools/list_files.py`
- **修改方案**：
  1. 增加 `.gitignore` 增量解析（BFS 中读取）
  2. 增加受限路径保护（阻止根目录/主目录）
  3. 增加超时保护（10s）

### P1-7: HookProcessRegistry 接入 runtime abort

- **来源**：P7.7
- **问题**：`integration.py` 调用 `run_hook` 不传 `registry` 参数，`runtime.py` `abort()` 不调用 `kill_all()`
- **影响**：abort 后 hook 子进程仍可能在后台运行，资源泄漏
- **修改文件**：`agent/file_hooks/integration.py`, `agent/runtime.py`
- **修改方案**：
  1. `integration.py` 传入 `registry` 参数
  2. `runtime.py` `abort()` 调用 `registry.kill_all()`
  3. `run_hook` 增加 `abort_signal` 参数

### P1-8: compact() 调用 build_budget_projection 作为安全阀

- **来源**：P7.2, P2.12
- **问题**：Charles `build_budget_projection` 已实现但 `compact()` 未调用
- **影响**：已移植的 4 步流水线未实际生效
- **修改文件**：`agent/context.py`（`compact()` 方法）
- **修改方案**：在 `compact()` 末尾调用 `build_budget_projection()` 作为安全阀

### P1-9: throwIfAborted 检查点补齐

- **来源**：P2.2, P2.6, P7.16
- **问题**：Charles 仅 2 处检查（循环顶 + stream 内），Cline 7 处
- **影响**：hook 执行中 abort 响应延迟
- **修改文件**：`agent/runtime.py`
- **修改方案**：在以下位置增加 `self._throw_if_aborted()`：
  1. before_model hook 后
  2. prepareTurn 后
  3. before_tool hook 后
  4. after_tool hook 后
  5. before_stream 后

### P1-10: ask_question 改为阻塞等待用户答案

- **来源**：P3.24
- **问题**：Charles "发送即返回"，Cline "阻塞等待答案"
- **影响**：LLM 拿不到用户反馈，破坏交互闭环
- **修改文件**：`agent/tools/ask_question.py`, `agent/server.py`
- **修改方案**：改为 `asyncio.Event` 阻塞等待，参考审批机制的实现模式

### P1-11: run_commands 改为并行执行 + 降低超时

- **来源**：P3.11
- **问题**：串行执行（`for` 循环），超时 600s（Cline 30s，20 倍）
- **修改文件**：`agent/tools/run_commands.py`
- **修改方案**：
  1. 改为 `asyncio.gather` 并行执行
  2. 默认超时 600s → 30s（或 60s 量化场景折中）
  3. 输出截断 8000 → 48000 字符

### P1-12: MistakeTracker 跨轮次状态

- **来源**：P2.8
- **问题**：Charles tracker 每 run 重置，Cline 跨 run 累积
- **影响**：跨轮次的连续错误无法检测
- **修改文件**：`agent/mistake_tracker.py`, `agent/runtime.py`
- **修改方案**：将 tracker 从 AgentRuntime 级移到 Session 级

### P1-13: SSE 事件映射补齐丢失事件

- **来源**：P1.2
- **问题**：丢失 `run-started`/`turn-started`/`turn-finished`/`usage-updated`/`assistant-message` 事件
- **修改文件**：`agent/server.py`
- **修改方案**：在 `_handle_event()` 中补齐事件映射

### P1-14: snapshot 深拷贝

- **来源**：P1.3, P2.9
- **问题**：`tuple(self._state.messages)` 浅包装，内部 AgentMessage 共享引用
- **修改文件**：`agent/events.py`
- **修改方案**：改为 `copy.deepcopy` 或 `clone_messages()`

### P1-15: skills_summary System Prompt 段移除

- **来源**：P4.17, P5.9
- **问题**：Cline 仅通过工具 description 暴露技能列表，Charles 额外在 System Prompt 注入
- **修改文件**：`agent/context.py`, `agent/skills/registry.py`, `agent_config/system_prompt.yaml`
- **修改方案**：移除 `skills_summary` 增强段，仅保留工具 description 暴露

### P1-16: SKILL.md 全面 Cline 化改写（结构 + 内容风格）

- **来源**：P4.6, P4.7, P4.20
- **问题**：8/8 技能的 SKILL.md 从 nanobot 迁移而来，不仅结构（三段式章节）非 Cline 风格，**内容本身的语气、句式、表达方式**也是 nanobot 风格。仅删除结构不够，需要全面改写为 Cline 范式。
- **修改文件**：8 个 `agent_config/skills/*/SKILL.md`
- **Cline 风格参考**：`third_party/cline/.agents/skills/create-pull-request/SKILL.md`、`cline-sdk/SKILL.md`

#### 改写维度 1：frontmatter 改写

```yaml
# 修改前（nanobot 风格）
name: stock-price
description: 获取A股/港股/美股实时行情数据
when_to_use: 需要查询股票价格、涨跌幅、成交量等实时市场数据时

# 修改后（Cline 风格）
name: stock-price
description: Fetch real-time stock market data for A-shares, HK stocks, and US stocks. Use when querying stock prices, price changes, trading volume, or other real-time market data.
```

- `when_to_use` 内容合并到 `description` 末尾，用 "Use when ..." 句式
- description 改为英文（对齐 Cline 惯例，LLM 理解英文 description 更准确）
- 移除 `always` 字段（P0-12）

#### 改写维度 2：结构改写（删除三段式，改为 Cline Workflow 范式）

```
# 修改前（nanobot 6 段式）
## 核心能力
## 场景路由
## Workflow
### Step 1: ...
## 脚本角色说明
## 脚本调用规则
## 禁止行为

# 修改后（Cline Workflow 范式）
# <技能标题>

<一句引导语描述技能整体目标>

## Prerequisites Check
### 1. Check <前置条件>
（命令直接嵌入）
### 2. Verify <验证步骤>

## Workflow
### Step 1: <步骤描述>
（命令 + 参数说明 + 行为约束 全部内嵌）

### Step 2: <步骤描述>
...

## Error Handling
### Common Issues
1. <常见问题 1>
2. <常见问题 2>
```

- 删除"## 脚本角色说明"：脚本信息内嵌到对应 Step
- 删除"## 脚本调用规则"：规则用 `**IMPORTANT**:` / `Note:` 内嵌到对应 Step
- 删除"## 禁止行为"：禁止事项转化为 Step 内的 `Do not...` / `**IMPORTANT**: Do not...` 句式
- 删除"## 核心能力"和"## 场景路由"：能力描述融入引导语，路由用 ASCII 决策树（如需要）

#### 改写维度 3：内容风格改写（nanobot 指令式 → Cline 协作式）

| 维度 | nanobot 风格（修改前） | Cline 风格（修改后） |
|------|----------------------|---------------------|
| 语气 | 指令式："禁止..."、"必须..." | 协作式："Ensure..."、"Before proceeding, verify..." |
| 禁止表达 | 独立章节"## 禁止行为"列表 | 嵌入 Step："**IMPORTANT**: Do not..." |
| 规则表达 | 独立章节"## 脚本调用规则" | 嵌入 Step："**Note**: <规则说明>" |
| 错误处理 | 独立"失败处理"子段 | `## Error Handling` 章节列常见问题 |
| 前置检查 | 无独立段 | `## Prerequisites Check` 章节 |
| 命令展示 | 独立"命令"子段 + 独立"脚本角色说明" | 直接嵌入 Step：```` ```bash ```` 代码块 + 参数说明 |
| 引导语 | 无 | 开头一句："This skill guides you through..." |
| 检查清单 | 无 | 末尾 `## Summary Checklist`（可选） |

#### 改写维度 4：命令参数修正（与 P0-1/2/3 联动）

在改写过程中同步修复脚本参数不匹配问题：
- write-report: `--stock`/`--title` → `--analysis_file`
- sentiment-analysis: `--stock` → `--news_file`
- bond-credit-review: 创建缺失脚本或移除技能

#### 改写示例（以 stock-price 为例）

```markdown
---
name: stock-price
description: Fetch real-time stock market data for A-shares, HK stocks, and US stocks. Use when querying stock prices, price changes, trading volume, or other real-time market data.
---

# Stock Price Query

This skill guides you through fetching real-time stock market data using the get_kline.py script.

## Prerequisites Check

### 1. Verify stock code format

**IMPORTANT**: Stock codes must include exchange suffix:
- A-shares: `.SH` (Shanghai) or `.SZ` (Shenzhen)
- HK stocks: `.HK`
- US stocks: `.US`

If the user provides a code without suffix, ask them to clarify the exchange.

## Workflow

### Step 1: Fetch K-line data

```bash
python agent_config/skills/stock-price/scripts/get_kline.py --stock <STOCK_CODE> --period <PERIOD> --count <COUNT>
```

**Parameters**:
- `--stock`: Stock code with exchange suffix (e.g., `000001.SZ`)
- `--period`: K-line period (`daily` / `weekly` / `monthly`)
- `--count`: Number of records (default: 100)

**Note**: If the script returns empty data, verify the stock code and try again. Do not fabricate data.

### Step 2: Return results to user

Present the fetched data in a clear format (table or summary).

## Error Handling

### Common Issues

1. **Invalid stock code**: Stock code without exchange suffix
   - Ask user to provide the correct format (e.g., `000001.SZ` not `000001`)

2. **Network timeout**: Data source unavailable
   - Retry once, then inform the user that the data source may be temporarily unavailable

3. **Empty results**: No data returned for valid code
   - Verify the stock code is correct and the stock is actively traded
```

#### 8 个技能逐个改写清单

| 技能 | 主要改写点 | 联动修复 |
|------|-----------|---------|
| stock-price | 删除三段式 + description 英文化 + 协作式语气 | — |
| read-pdf | 删除三段式 + 移除 `always: true` + description 英文化 | P0-12 |
| financial-analysis | 删除三段式 + 6 处实现逻辑残留改写 | — |
| write-report | 删除三段式 + 参数修正 + description 英文化 | P0-1 |
| compare-reports | 删除三段式 + cross_period.py 文档化 | — |
| sentiment-analysis | 删除三段式 + 参数修正 + description 英文化 | P0-2 |
| bond-credit-review | 删除三段式 + 脚本创建/移除 | P0-3 |
| web-search | 删除三段式 + description 英文化 + 命名去混淆 | — |

### P1-17: 排水（drain）触发方式对齐

- **来源**：P2.11, P7.17
- **问题**：Charles `send_callback` 空操作，由 SSE 末尾 while 循环消费；Cline `send_callback` 真实启动新 run
- **影响**：SSE 断开后队列残留
- **修改文件**：`agent/runtime.py`, `agent/server.py`
- **修改方案**：`send_callback` 改为真实启动新 run

### P1-18: completion reminder 工具名列举对齐

- **来源**：P2.5
- **问题**：Charles 预注入只取第一个工具名；Cline 列出所有 `completesRun=true` 工具名
- **修改文件**：`agent/runtime.py`
- **修改方案**：列出所有 `completes_run=True` 的工具名（sort 逗号分隔）

### P1-19: MCP auto_approve 对接

- **来源**：P7.8
- **问题**：Charles `use_mcp_tool` 不消费 auto_approve 配置
- **修改文件**：`agent/tools/mcp.py`
- **修改方案**：`use_mcp_tool` 调用前检查 `auto_approve` 列表

### P1-20: Prompt/规则文件清理（对齐 Cline 组织方式）

- **来源**：P5.2, P5.11, P6.2, P6.4
- **问题**：Charles 的 prompt/规则文件组织方式源自 nanobot，与 Cline 不同。根据用户策略："如果 Cline 有 → 对齐 Cline 风格；如果 Cline 没有 → 删除"
- **清理原则**：
  - Cline 有对应文件 → 对齐 Cline 的组织方式和内容风格
  - Cline 无对应文件 → 评估内容是否可整合到 Cline 对标文件中，无法整合则删除

#### Charles 当前文件清单

| 文件 | Cline 对标 | 处理方式 | 理由 |
|------|-----------|---------|------|
| `agent_config/rules/AGENTS.md` | `.agents/rules/AGENTS.md` | **保留**，对齐 Cline 风格（P6.2/P6.5） | Cline 有 AGENTS.md |
| 8 个 `agent_config/skills/*/SKILL.md` | `.agents/skills/*/SKILL.md` | **保留**，全面 Cline 化改写（P1-16） | Cline 有 SKILL.md |
| `agent_config/rules/plan-mode-rules.md` | 无独立文件 | **删除**，内容整合到 System Prompt mode 段 | Cline 的 plan 模式规则在 System Prompt 的 mode 段中，无独立文件 |
| `agent_config/rules/general.md` | 无独立文件 | **删除**，内容整合到 AGENTS.md | Cline 的通用规则在 base prompt + AGENTS.md 中，无独立 general.md |
| `agent_config/rules/trading.md` | 无独立文件 | **删除**，内容整合到 AGENTS.md | Cline 无独立业务规则文件；业务规则应在 AGENTS.md 中 |
| `agent_config/rules/research.md` | 无独立文件 | **删除**，内容整合到 AGENTS.md | 同上 |
| `agent_config/system_prompt.yaml` | 无对应文件 | **评估** | Cline 的 prompt 组装在代码中（builder），Charles 用 YAML 配置。保留配置化方式但需对齐内容 |

#### 整合方案

**Step 1: general.md → AGENTS.md**

将 general.md 中的通用行为规则合并到 AGENTS.md 中。AGENTS.md 已有类似内容（根据 P6.4 分析有部分重复），合并时去重。

**Step 2: trading.md → AGENTS.md**

将 trading.md 中的交易规则（股票代码格式、数据源限制等）作为 AGENTS.md 的一个章节。Cline 的 AGENTS.md 也是把所有项目规则放一个文件。

**Step 3: research.md → AGENTS.md**

将 research.md 中的研究规则合并到 AGENTS.md。

**Step 4: plan-mode-rules.md → System Prompt mode 段**

将 plan-mode-rules.md 中的 Plan 模式规则迁移到 `agent/context.py` 的 mode section 生成逻辑中（对齐 Cline 的 `MODE_SECTION` 实现）。

**Step 5: 删除 4 个独立规则文件**

```bash
# 整合完成后删除
agent_config/rules/plan-mode-rules.md  # 删除
agent_config/rules/general.md          # 删除
agent_config/rules/trading.md          # 删除
agent_config/rules/research.md         # 删除
```

**Step 6: AGENTS.md 对齐 Cline 风格改写**

整合后的 AGENTS.md 按 Cline 风格组织（参考 P6.2/P6.5 的改写要求）：
- 使用英文（对齐 Cline 惯例）
- 协作式语气而非指令式
- frontmatter 评估器对齐 Cline（移除 dead 字段 alwaysApply / globs）

#### system_prompt.yaml 评估

Charles 用 `system_prompt.yaml` 控制 System Prompt 段落组装（enhancement 开关等），Cline 在代码中硬编码。

- **保留 YAML 配置化方式**（合理偏离，便于调试）
- **但对齐内容**：移除 `always_skills` 开关（P0-12）、移除 `skills_summary` 开关（P1-15）、移除 `memory` 段开关（dead code）
- 保留的开关：`tools`、`mcp`、`enhancement`（默认关闭）

---

## 4. P2 对齐改进（中期执行）

### 工具系统

| ID | 差距 | 修改方案 |
|----|------|---------|
| P2-1 | web_tool 搜索后端单一（DuckDuckGo） | 评估接入 MCP 搜索服务或 Google Search API |
| P2-2 | fetch_web_content 不区分 Content-Type | 增加 HTML/JSON/其他分支处理 |
| P2-3 | fetch_web_content 无重定向/编码检测完善 | 补齐重定向链 + 编码检测 |
| P2-4 | apply_patch 模糊匹配强度不足 | 增加 Levenshtein≥0.66 回退 + Unicode 标点归一化 |
| P2-5 | apply_patch 缺 Move to 操作 | 增加 move 操作支持 |
| P2-6 | run_commands 进程树 kill 不完整 | 增加 `taskkill /T /F`（Windows）/ `os.killpg`（Linux） |
| P2-7 | MAX_LINE_CHARS 全局缺失 | 在 types.py 定义 `MAX_LINE_CHARS = 2000`，各工具引用 |
| P2-8 | 截断策略不统一 | 抽取公共 `truncate_output(text, max_chars)` head+tail 函数 |

### 技能系统

| ID | 差距 | 修改方案 |
|----|------|---------|
| P2-9 | PyYAML fallback 手写解析 | 移除 fallback，强制 PyYAML（违反"不要 fallback"规则） |
| P2-10 | 脚本 try/except + fallback | 移除 3 处 fallback（sentiment_scorer.py / event_detector.py） |
| P2-11 | fetch_financial_data.py 冗余脚本 | 删除（与 fetch_financial_csv.py 重复） |
| P2-12 | SKILL.md 硬编码日期 | read-pdf L101 / write-report L94 移除或改为动态 |
| P2-13 | SkillsTool 无超时 | 增加 `asyncio.wait_for` 超时（对齐 Cline `withTimeout`） |

### System Prompt

| ID | 差距 | 修改方案 |
|----|------|---------|
| P2-14 | composeSystemPrompt 动态规则合并缺失 | 实现 `compose_system_prompt()` 扩展点 |
| P2-15 | metadata provider_id 未透传 | `server.py` L549 透传 `provider_id` |
| P2-16 | extra_sections 死参数 | 删除 `extra_sections` 参数 + 消费逻辑 |
| P2-17 | 废弃 `_build_environment()` 中文字段名 | 删除废弃方法 |
| P2-18 | AgentMode 类型缺 yolo/zen | 增加 `Literal["act", "plan", "yolo"]` |

### 核心引擎

| ID | 差距 | 修改方案 |
|----|------|---------|
| P2-19 | Provider 缺 Anthropic 原生适配 | 实现 `AnthropicModel`（thinking + prompt cache） |
| P2-20 | Provider 缺专用错误类型 | 实现 `ProviderError` 层级 |
| P2-21 | Hooks 缺 Notification + PreCompact 类型 | 增加 2 个 hook 类型 |
| P2-22 | Hooks 缺流式 stdout/stderr | 改为 `asyncio.create_subprocess_exec` + 逐行读取 |
| P2-23 | Checkpoint 缺 diff 对比视图 | 增加 `checkpoint-diff` API |
| P2-24 | 事件名串不一致 | `tool-execution-started` → `tool-started`（对齐 Cline） |
| P2-25 | snapshot 引用语义 | tuple → deepcopy（同 P1-14） |
| P2-26 | listener 容器 list → Set | 改为 `set` 去重 |
| P2-27 | Telemetry distinctId 持久化 | 增加机器 ID 持久化文件 |
| P2-28 | AGENTS.md 加载顺序相反 | global→workspace 改为 workspace→global |

---

## 5. P3 可选优化（长期执行）

| ID | 差距 | 评估 |
|----|------|------|
| P3-1 | Connectors/Kanban | 主动不实施（Web 应用架构合理偏离） |
| P3-2 | Sub-agent | 主动不实施（主上下文指令注入替代） |
| P3-3 | Plugin/Marketplace | 主动不实施（Stage 8 决策） |
| P3-4 | Provider Bedrock/Vertex | 按需评估（量化场景可能不需要） |
| P3-5 | Provider Gateway 动态注册 | 按需评估 |
| P3-6 | MCP OAuth | 按需评估（如需连接公开 MCP 服务） |
| P3-7 | MCP streamableHttp 传输 | 按需评估 |
| P3-8 | Session OCC 乐观锁 | 按需评估（单进程场景可能不需要） |
| P3-9 | Session stale 回收 | 按需评估 |
| P3-10 | Telemetry logs/traces exporter | 按需评估 |
| P3-11 | Checkpoint "仅消息回滚"模式 | 按需评估 |
| P3-12 | nanobot 注释残留（55 处） | 统一改为"对标 Cline"或删除 |
| P3-13 | AGENTS.md 标题层级 2→3 | 按需评估 |
| P3-14 | list_files DFS→BFS | 按需评估 |
| P3-15 | todo_write 替换式→增量式 | 按需评估 |

---

## 6. Charles 增强项评估

### 6.1 真增强（保留，不对齐回退）

| # | 增强项 | 理由 |
|---|--------|------|
| 1 | run_commands 危险命令拦截 | 量化场景安全需要 |
| 2 | run_commands 实时终端输出推送 | Web 场景长命令监控需要 |
| 3 | run_commands 优雅 kill（SIGTERM→SIGKILL） | 比 Cline SIGKILL 更优雅 |
| 4 | apply_patch 保留 CRLF 行尾 | Windows 场景正确处理 |
| 5 | apply_patch 结构化错误信息 | LLM 自我纠正更友好 |
| 6 | todo_write 状态持久化 + Kanban | Web 场景可视化需要 |
| 7 | 审批持久化 + 超时 + MCP per-tool 策略 | Web 场景精细控制需要 |
| 8 | 重试机制（指数退避） | Cline 声明字段未实现，Charles 真实现 |
| 9 | Provider Qwen tool_call_id 稳定化 | Python 端必要适配 |
| 10 | Checkpoint 原子性联动回滚 | 比 Cline 单消息回滚更完整 |
| 11 | 循环检测 per-type 阈值 | 比 Cline 单一阈值更精细 |
| 12 | Abort 优雅 kill | 比 Cline SIGKILL 更优雅 |
| 13 | emit_sync 同步推送 | Python asyncio 调度延迟补偿 |
| 14 | 中国本地化 PII 脱敏 | 合规需要 |
| 15 | budget-projection 提前压缩 | 避免下一轮超限 |
| 16 | System Prompt tools_section 段 | 量化场景工具使用指引长文本 |
| 17 | System Prompt mcp_section 段 | 量化场景 MCP 服务器概览 |
| 18 | System Prompt memory 段 | 量化场景记忆持久化 |
| 19 | AGENTS.md 三类条件评估器（applyTo/mode/enabled） | Cline 严格超集 |
| 20 | invalidToolCalls 主动生成错误 result | LLM 自我纠正（修复 bug 后） |
| 21 | schema 结构化错误列表 | LLM 自我纠正更友好 |
| 22 | 9 hook 点多订阅者链 | 多插件协同 |
| 23 | rules_loader 完整实现 | Cline SDK 端弱化版的功能补齐 |
| 24 | COMPACTION 事件常量 | 前端无需解析 metadata.reason |
| 25 | Turn Queue drain 重入保护 | 并发安全 |
| 26 | `register_sse_event_callback` 旁路通道 | **需重新评估**（见 6.2） |

### 6.2 打乱 Cline 设计（需修正）

| # | 增强项 | 问题 | 修改方案 |
|---|--------|------|---------|
| 1 | **always 预加载机制** | 打破 Cline on-demand 设计哲学，skills 和 rules 边界模糊 | **移除**（P0-12） |
| 2 | **when_to_use 字段** | Cline 无此字段，应内嵌到 description | **移除**（P0-13） |
| 3 | **skills_summary System Prompt 段** | Cline 仅工具 description 暴露，冗余 | **移除**（P1-15） |
| 4 | **SKILL.md 三段式章节** | Cline 无此结构，nanobot 风格 | **重构**（P1-16） |
| 5 | **ask_question 发送即返回** | 破坏交互闭环，LLM 拿不到反馈 | **改为阻塞等待**（P1-10） |
| 6 | **completion_guard 捕获降级** | 与"guard 是纯函数"语义分歧 | 移除 try/except，让异常传播 |
| 7 | **runtime 层统一超时/重试** | 与"工具自治"语义分歧 | 评估：保留（Charles 真实现 vs Cline 死字段，属合理增强） |
| 8 | **`register_sse_event_callback` 旁路通道** | 破坏事件单一出口原则 | 评估：保留（Web 场景 hook 需要直接推 SSE，但需文档化） |

### 6.3 设计选择（不对齐，合理偏离）

| # | 差异 | 理由 |
|---|------|------|
| 1 | MCP 调度器模式 vs first-class | token 受限场景适用 |
| 2 | AGENTS.md 业务规则 vs 开发文档 | 面向 LLM vs 面向人类 |
| 3 | 前端 SSE vs VSCode Webview | Web 应用架构 |
| 4 | 单进程 vs 多宿主 | Web 服务端架构 |
| 5 | JSON 会话存储 vs SQLite | Python 生态简化 |

---

## 7. nanobot 残留清理

### 7.1 实现逻辑残留（高优先级）

| 残留项 | 数量 | 清理方案 | 优先级 |
|--------|------|---------|--------|
| always 预加载机制 | 7 处 | 完整移除（P0-12） | P0 |
| when_to_use 字段 | 11 处 | 合并到 description（P0-13） | P0 |
| 三段式章节 | 24 处 | 重构为 Workflow 内嵌（P1-16） | P1 |
| PyYAML fallback | 1 处 | 移除 fallback（P2-9） | P2 |
| 脚本 try/except+fallback | 3 处 | 移除 fallback（P2-10） | P2 |
| routes/chat.py 旧路由 | 1 处 | 删除文件（P0-11） | P0 |
| attempt_completion.py 孤儿 | 1 处 | 删除文件 | P2 |
| exec_tool.py 孤儿 | 1 处 | 删除文件 | P2 |
| FileReadTool 旧版 | 1 处 | 删除（被 read_files 取代） | P2 |
| .pyc 死文件 | 3 处 | 删除 | P2 |
| extra_sections 死参数 | 1 处 | 删除（P2-16） | P2 |

### 7.2 注释残留（低优先级）

| 文件 | 残留数 | 清理方案 |
|------|--------|---------|
| `agent/tools/exec_tool.py` | 12 | 删除文件后自动清除 |
| `agent/tools/file_tools.py` | 7 | 删除文件后自动清除 |
| `agent/tools/web_tool.py` | 7 | 改为"对标 Cline"或删除 |
| `agent/skills/loader.py` | 9 | 改为"对标 Cline"或删除 |
| `agent/skills/registry.py` | 4 | 改为"对标 Cline"或删除 |
| `agent/providers/qwen.py` | 7 | 改为"对标 Cline"或删除 |
| `agent/server.py` | 3 | 改为"对标 Cline"或删除 |
| `agent/session.py` | 2 | 改为"对标 Cline"或删除 |
| `agent/context.py` | 1 | 删除（P2-16） |
| 其他 | 3 | 改为"对标 Cline"或删除 |
| **合计** | **55** | |

---

## 8. 执行顺序与依赖关系

### Stage 1: 紧急修复（P0，无依赖）

```
P0-5  路径拼写错误（1 行）
P0-6  invalid_tool_messages 双重追加 bug
P0-7  工具结果未截断
P0-8  ControlledStopError status 映射
P0-9  before_run hook stop 路径
P0-10 预注入 reminder 不 emit
P0-11 routes/chat.py 删除
P0-1  write-report SKILL.md 参数修复
P0-2  sentiment-analysis SKILL.md 参数修复
P0-3  bond-credit-review 脚本创建/移除
P0-4  web_tool/fetch_web_content 截断阈值
```

### Stage 2: nanobot 清理 + 工具改进（P0-12/13 + P1）

```
P0-12 always 预加载移除 ──┐
P0-13 when_to_use 移除 ──┤
P1-15 skills_summary 段移除 ─┤── 依赖：先移除 always/when_to_use
P1-16 三段式章节重构 ─────┘
P1-1  search_codebase 补齐
P1-2  read_files 补齐
P1-4  Base Prompt 补齐
P1-5  cwd 越界检查
P1-6  list_files 补齐
P1-10 ask_question 阻塞等待
P1-11 run_commands 并行+超时
```

### Stage 3: 核心引擎修复（P1）

```
P1-7  HookProcessRegistry 接入 abort
P1-8  compact() 调用 budget_projection
P1-9  throwIfAborted 检查点
P1-12 MistakeTracker 跨轮次
P1-13 SSE 事件映射补齐
P1-14 snapshot 深拷贝
P1-17 drain 触发方式
P1-18 completion reminder 工具名
P1-19 MCP auto_approve 对接
```

### Stage 4: 对齐改进（P2）

```
P2-1 ~ P2-28 按模块分组执行
```

### Stage 5: 可选优化（P3）

```
P3-1 ~ P3-15 按需评估
```

### 依赖关系图

```
P0-12 (always 移除) ─┬─→ P1-15 (skills_summary 移除)
P0-13 (when_to_use) ─┘
                     └─→ P1-16 (三段式重构)

P1-10 (ask_question) ←─ 独立

P0-4 (截断阈值) ─┬─→ P2-1 (web_tool 后端)
                 └─→ P2-2 (fetch Content-Type)

P1-7 (Hooks abort) ─→ P2-21 (Hooks 类型)
                  ─→ P2-22 (Hooks 流式)

P0-12/P0-13/P1-15/P1-16 ─→ P3-12 (注释清理)
```

---

## 附录：报告索引

| Phase | 报告数 | 主题 |
|-------|--------|------|
| Phase 1 | 7 | 架构边界 |
| Phase 2 | 12 | 运行时核心 |
| Phase 3 | 24 | 工具系统 |
| Phase 4 | 20 | 技能系统 |
| Phase 5 | 23 | System Prompt |
| Phase 6 | 12 | AGENTS.md |
| Phase 7 | 23 | 核心引擎与评估 |
| **合计** | **121** | |

---

## 附录 B：遗漏项补充（对照 P7.21 优先级矩阵）

> P7.21 优先级矩阵（62 项去重差距）是最权威的差距汇总。对照后发现以下差距项在修改计划正文中遗漏，现补充。

### B.1 遗漏的 P1 项（5 项）

| 新编号 | P7.21 编号 | 来源 | 差距描述 | 修改文件 | 修改方案 |
|--------|-----------|------|---------|---------|---------|
| P1-21 | P1-8 | P6.7 | AGENTS.md 加载顺序相反（global→workspace，应为 workspace→global） | `agent/context.py` L471-500 | 调换加载顺序 |
| P1-22 | P1-12 | P7.13/P6.1/P6.6 | `alwaysApply: true` 死字段（从 Cursor Rules 复制，无评估器消费） | `agent_config/rules/AGENTS.md` frontmatter | 移除字段 |
| P1-23 | P1-15 | P7.19 | `allowed_tools` 死代码字段（被解析但无消费方） | `agent/skills/loader.py` L74/L259-266 | 删除字段及解析逻辑 |
| P1-24 | P1-19 | P6.8 | AGENTS.md 命名仅用文件 stem，Cline 三级优先级（frontmatter name → AGENTS.md 特殊名 → 文件 stem） | `agent/rules_loader.py` | 增加 frontmatter name 覆盖 |
| P1-25 | P1-18 | P6.4 | general.md 与 trading.md 股票代码格式段重复 | `agent_config/rules/trading.md` L29-34 | 合并到 AGENTS.md 后删除（与 P1-20 联动） |

### B.2 遗漏的 P2 项（18 项）

| 新编号 | P7.21 编号 | 来源 | 差距描述 | 修改文件 |
|--------|-----------|------|---------|---------|
| P2-29 | P2-1 | P3.1 | `__init__.py` L2 nanobot 注释清理 | `agent/tools/__init__.py` |
| P2-30 | P2-2 | P3.10 | read_files `start_line <= end_line` 校验缺失 | `agent/tools/read_files.py` |
| P2-31 | P2-4 | P3.10 | `file_tools.py` nanobot 注释清理 | `agent/tools/file_tools.py` |
| P2-32 | P2-6 | P3.12 | apply_patch 重复操作检查缺失 | `agent/tools/apply_patch.py` |
| P2-33 | P2-11 | P3.16 | SwitchToPlanModeTool 对标注释修正 | `agent/tools/plan_mode.py` |
| P2-34 | P2-12 | P3.16 | `set_mode` docstring 与实现矛盾 | `agent/state.py` |
| P2-35 | P2-13 | P3.16 | server.py + context.py nanobot 注释清理 | `agent/server.py` + `agent/context.py` |
| P2-36 | P2-16 | P3.22 | web_tool URL 协议校验缺失 | `agent/tools/web_tool.py` |
| P2-37 | P2-17 | P3.23 | INPUT_ARG_CHAR_LIMIT 大小检查缺失 | `agent/tools/file_tools.py` |
| P2-38 | P2-18 | P3.24 | ask_question 描述关键约束补充 | `agent/tools/ask_question.py` |
| P2-39 | P2-22 | P4.13 | sentiment-analysis `--keywords` 参数文档缺失 | `agent_config/skills/sentiment-analysis/SKILL.md` |
| P2-40 | P2-23 | P4.13 | sentiment-analysis `--days` 默认值与输出路径描述修正 | `agent_config/skills/sentiment-analysis/SKILL.md` |
| P2-41 | P2-30 | P7.7 | 用户中止后 hook 仍执行到超时 | `agent/hooks/runner.py` |
| P2-42 | P2-31 | P7.7 | 长时 hook 无进度反馈 | `agent/hooks/runner.py` |
| P2-43 | P2-32 | P7.7 | JSON 提取鲁棒性（两阶段提取） | `agent/hooks/runner.py` L269-289 |
| P2-44 | P2-41 | P7.18 | 事件名串不一致（tool-started vs tool-execution-started） | `agent/events.py` |
| P2-45 | P2-42 | P7.19 | `__pycache__/*.pyc` 死文件清理 | `agent/skills/__pycache__/` |
| P2-46 | P2-43 | P7.19 | skill_tool.py 静默异常改日志 | `agent/skills/skill_tool.py` L245-267 |

### B.3 更新后统计

| 优先级 | 原数量 | 遗漏补充 | 更新后数量 |
|--------|--------|---------|-----------|
| P0 | 14 | 0 | 14 |
| P1 | 20 | 5 | 25 |
| P2 | 28 | 18 | 46 |
| P3 | 15 | 0 | 15 |
| **合计** | **77** | **23** | **100** |

---

## 附录 C：追溯映射表（修改计划项 → P7.21 矩阵 → 对比报告）

> 本表建立修改计划中每个修改项到对比报告中具体不同点的追溯关系，便于修改时定位和修改后验证。

### C.1 P0 级追溯

| 修改计划项 | P7.21 矩阵 | 来源报告 | 具体不同点 |
|-----------|-----------|---------|-----------|
| P0-1 write-report 参数 | P0-1 | P4.11 | SKILL.md `--stock`/`--title` vs 脚本 `--analysis_file` |
| P0-2 sentiment-analysis 参数 | P0-2 | P4.13 | SKILL.md `--stock` vs 脚本 `--news_file` |
| P0-3 bond-credit-review 脚本不存在 | P0-3 | P4.14 | `bond_credit_review.py` 文件不存在 |
| P0-4 web_tool/fetch 截断 | — | P3.21, P3.22 | 8000 字符 vs Cline 50000 字符 |
| P0-5 路径拼写错误 | P0-4 | P6.7 | `.agent` vs `.agents` |
| P0-6 invalid_tool_messages 双重追加 | — | P2.7 | L687-689 + L722-724 重复追加 |
| P0-7 工具结果未截断 | — | P2.4 | emit 截断但 message 未截断 |
| P0-8 ControlledStopError status | — | P1.6, P2.2 | `status="completed"` vs 应为 `"aborted"` |
| P0-9 before_run hook stop | — | P2.2 | before_run 抛 RuntimeError vs 应抛 ControlledStopError |
| P0-10 预注入 reminder 不 emit | — | P2.5 | push 后未 emit message-added |
| P0-11 routes/chat.py 残留 | — | P1.2 | 引用已废弃 charles-nanobot |
| P0-12 always 预加载 | P0-5 | P4.16, P4.20, P5.10, P7.19 | 7 处 always 机制 nanobot 残留 |
| P0-13 when_to_use | P0-6 | P4.5, P4.20, P5.9, P7.19 | 11 处 when_to_use 字段 nanobot 残留 |
| P0-14 工具实现逻辑 Cline 化 | P0-7 + P1-14 | P3.1-P3.24 全阶段 | 3 个孤儿工具删除 + 10 个工具 nanobot 实现替换 |

### C.2 P1 级追溯

| 修改计划项 | P7.21 矩阵 | 来源报告 | 具体不同点 |
|-----------|-----------|---------|-----------|
| P1-1 search_codebase | P1-5 + P2-7/8 | P3.13 | Python re vs ripgrep；无上下文行；无截断；大小写敏感 |
| P1-2 read_files | P2-3 | P3.10 | 串行 vs 并行；1 层截断 vs 3 层；一次性 vs 流式 |
| P1-3 plan_mode | P1-6 + P1-7 | P3.16 | 缺 auto-continue；缺会话重建 |
| P1-4 Base Prompt | — | P5.3 | 828 chars vs 3695 chars；缺 13 项行为约束 |
| P1-5 cwd 越界检查 | P1-1 + P1-2 | P3.12, P3.23 | apply_patch/editor/file_write 无 restrictToCwd |
| P1-6 list_files | P1-3 + P2-9/10 | P3.14 | 无 .gitignore；无受限路径；无超时 |
| P1-7 Hooks abort | P1-9 | P7.7 | registry 未传入；abort 不 kill_all |
| P1-8 compact() 安全阀 | P1-10 | P7.2 | build_budget_projection 已实现但未调用 |
| P1-9 throwIfAborted | P2-39 | P2.2, P2.6, P7.16 | 2 处 vs 7 处检查点 |
| P1-10 ask_question 阻塞 | — | P3.24 | 发送即返回 vs 阻塞等待 |
| P1-11 run_commands | — | P3.11 | 串行 vs 并行；600s vs 30s；8000 vs 48000 |
| P1-12 MistakeTracker | — | P2.8 | 每 run 重置 vs 跨 run 累积 |
| P1-13 SSE 事件映射 | — | P1.2 | 丢失 5 个事件类型 |
| P1-14 snapshot 深拷贝 | — | P1.3, P2.9 | 浅包装 vs deepcopy |
| P1-15 skills_summary 段 | — | P4.17, P5.9 | Cline 仅工具 description，Charles 额外注入 |
| P1-16 SKILL.md Cline 化 | P0-7 | P4.6, P4.7, P4.20 | 24 处三段式章节 + 内容风格 |
| P1-17 drain 触发 | P2-40 | P2.11, P7.17 | SSE 末尾循环 vs send_callback 启动 |
| P1-18 completion reminder | — | P2.5 | 仅第一个工具名 vs 所有 completesRun 工具名 |
| P1-19 MCP auto_approve | — | P7.8 | 不消费 auto_approve 配置 |
| P1-20 Prompt 文件清理 | P1-18 | P5.2, P5.11, P6.2, P6.4 | 4 个独立规则文件 → 整合到 AGENTS.md |
| P1-21 AGENTS.md 加载顺序 | P1-8 | P6.7 | global→workspace vs workspace→global |
| P1-22 alwaysApply 死字段 | P1-12 | P7.13, P6.1, P6.6 | 从 Cursor Rules 复制，无评估器消费 |
| P1-23 allowed_tools 死代码 | P1-15 | P7.19 | 被解析但无消费方 |
| P1-24 AGENTS.md 命名 | P1-19 | P6.8 | 一级 vs 三级优先级 |
| P1-25 股票代码段重复 | P1-18 | P6.4 | general.md 与 trading.md 重复 |

### C.3 P2 级追溯（关键项）

| 修改计划项 | P7.21 矩阵 | 来源报告 | 具体不同点 |
|-----------|-----------|---------|-----------|
| P2-1 web_tool 后端 | P2-14/15 | P3.21 | DuckDuckGo 单一后端 |
| P2-4 apply_patch 模糊匹配 | — | P3.12 | 缺 Levenshtein≥0.66 回退 |
| P2-7 MAX_LINE_CHARS | P2-3 | P3.10 | 全局缺失单行字符截断 |
| P2-8 截断策略统一 | — | P3.18 | 各工具截断策略不一致 |
| P2-9 PyYAML fallback | P1-13/P2-21 | P4.2, P7.19 | 双路径解析，fallback 是 nanobot 残留 |
| P2-13 SkillsTool 超时 | — | P4.1 | 无 asyncio.wait_for |
| P2-14 composeSystemPrompt | P1-16 | P5.11 | 缺动态规则合并层 |
| P2-15 metadata provider_id | — | P5.17 | server.py 未透传 |
| P2-29 __init__.py 注释 | P2-1 | P3.1 | L2 nanobot 注释 |
| P2-41 hook 中止后仍执行 | P2-30 | P7.7 | 用户中止后 hook 仍到超时 |
| P2-44 事件名串 | P2-41 | P7.18 | tool-started vs tool-execution-started |
| P2-45 .pyc 死文件 | P2-42 | P7.19 | __pycache__ 下 3 个 .pyc |

### C.4 未列入修改计划的项（合理排除）

| P7.21 编号 | 差距 | 排除理由 |
|-----------|------|---------|
| P1-11 | rule docstring 修正 | 极低优先级注释修正，不影响功能 |
| P1-17 | Memory 段标注勘误 | 计划文件勘误，非代码修改 |
| P2-5 | 进程树 kill | 已在 P2-6 中覆盖 |
| P2-20/P2-38 | server.py nanobot 注释 | 已在 P2-35 中合并 |
| P2-24/P2-28 | 计划表标注修正 | 计划文件勘误，非代码修改 |
| P2-25 | always_skills 段评估 | 已在 P0-12 中处理 |
| P2-27 | memory 段评估 | 已在 P1-20 中处理 |
| P2-29 | Provider 覆盖广度 | Charles 量化场景只需 7 个 provider，合理偏离 |
| P2-33 | MCP 传输协议 | sse/streamableHttp 缺失，量化场景暂不需要 |
| P2-34 | MCP 配置无锁 | 低影响，中期按需 |
| P2-35~P2-37 | Telemetry 改进 | 中国本地化场景，合理偏离 |
