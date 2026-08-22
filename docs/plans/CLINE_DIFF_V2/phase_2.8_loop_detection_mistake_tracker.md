# Phase 2.8 LoopDetection + MistakeTracker 对比报告

## 1. 执行摘要

Cline 在 SDK 层将"运行时安全"拆为三个独立职责：`LoopDetectionTracker`（连续相同工具调用检测，软阈值 3 / 硬阈值 5）、`MistakeTracker`（连续错误计数，单一 `maxConsecutiveMistakes` 阈值，3 类 mistake reason）、以及 `rules.ts`（仅做 `RuleConfig` → system prompt 的纯文本格式化，无运行时拦截能力）。三者通过 `SessionRuntime.handleRuntimeEvent`（session-runtime-orchestrator.ts L1062-1167）在事件流上集中接线：`tool-started` 触发 `inspectLoopForToolCall`，`turn-finished` 触发 `enqueueMistakeRecord`，由 `activeTrackerWork` 串行队列保证 MistakeTracker.record 的顺序与时机。

Charles 在 `agent/loop_detection.py` + `agent/mistake_tracker.py` + `agent/rules_loader.py` 实现了对标逻辑，且在两个维度上**显著超出 Cline 的能力边界**：
1. **MistakeTracker 错误分类更细**：Cline 仅 3 类（`api_error` / `invalid_tool_call` / `tool_execution_failed`）且不自动推断；Charles 提供 5 类（`param_error` / `tool_not_found` / `permission_denied` / `exec_error` / `timeout`）+ `classify_mistake(error_text)` 关键词推断函数。
2. **MistakeTracker 双层阈值**：Cline 只有单一 `maxConsecutiveMistakes`（默认 6）；Charles 拆为 `max_per_type=3`（单类型软阈值，触发 guidance 注入）+ `max_total=5`（总错误硬阈值，触发 abort），分类计数更精细。
3. **Rules 引擎更完整**：Cline `rules.ts` 仅 49 行，是 `formatRulesForSystemPrompt` + `mergeRulesForSystemPrompt` 的纯函数库；Charles `rules_loader.py`（1053 行）实现了 frontmatter 解析、`applyTo`/`mode`/`paths` 三类条件评估、wcmatch/picomatch glob 匹配、global+local 双层 toggle 持久化、mtime 缓存。PLAN 表中"2.8.12 safety rules 引擎 — Charles 缺失"的判断与实际不符，应改为"Charles 反而更完整"。

集成方式上，Cline 在 `SessionRuntime` 的事件处理器中集中接线（`tool-started` / `turn-finished` 事件驱动），Charles 在 `AgentRuntime` 内联接线（`_loop_detection_hook` 作为 before_tool hook + `_check_repeated_tool_failures` 在工具执行后直接调用）。Charles 的 `_check_repeated_tool_failures` 还**保留了 Phase 26 的"同一工具同一错误连续 N 次"独立硬阈值**（threshold=3），与 MistakeTracker 的总错误硬阈值并存，是 Cline 没有的额外保护层。

nanobot 残留检查结论：在 P2.8 涉及的 4 个核心文件（`loop_detection.py` / `mistake_tracker.py` / `rules_loader.py` / `runtime.py` 中的循环/错误追踪段落）中**未发现任何 nanobot 残留**（既无注释残留也无实现逻辑残留）。所有实现均基于 Cline 对标设计。P2.1 报告中提到的 12 个 nanobot 残留文件均位于 `providers/` / `tools/` / `skills/` / `session.py` / `server.py` 等其他模块，与本阶段无关。

## 2. 逐项对比表

按 AGENT_COMPARISON_PLAN_V2.md P2.8 章节定义的 13 个对比项列出：

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 2.8.1 | LoopDetectionTracker 数据结构 | `loop-detection.ts` L20-32 `LoopDetectionState`（lastToolName / lastToolSignature / consecutiveIdenticalCount） | `loop_detection.py` L22-27 `LoopDetectionState`（last_tool_name / last_signature / consecutive_identical_count） | 字段一一对应，仅命名风格差异（camelCase vs snake_case） | 完全对齐 |
| 2.8.2 | 循环判定 key | `loop-detection.ts` L50-59 `toolCallSignature`（JSON.stringify(sortKeys(input))） + L72-79 比较 `toolName === lastToolName && signature === lastToolSignature` | `loop_detection.py` L51-62 `tool_call_signature`（json.dumps(_sort_keys(input), ensure_ascii=False, separators=(",",":"))） + L72 比较 `tool_name == last_tool_name and signature == last_tool_signature` | 算法等价：递归排序键 + JSON 序列化；Charles 多了 `ensure_ascii=False` 和紧凑分隔符，对含中文输入更稳定 | 完全对齐 |
| 2.8.3 | 软阈值触发行为 | `loop-detection.ts` L84 `consecutiveIdenticalCount === softThreshold`；`session-runtime-orchestrator.ts` L1256-1263 `verdict.kind === "soft"` 分支调用 `conversation.appendMessage({role:"user", content:[{type:"text", text:verdict.message}]})` 注入提示，**不阻止**工具调用 | `loop_detection.py` L88 `consecutive_identical_count == soft_threshold`；`runtime.py` L1323-1332 `_loop_detection_hook` soft 分支：先 `logger.warning` 记录日志，再调用 `_inject_user_notice(verdict.message)` 追加 user 消息 + emit message_added 事件，**不阻止**工具调用 | 行为等价：两者都"注入 user 消息 + 不阻止"；Charles 多了 logger.warning 日志（保留原逻辑） | 完全对齐 |
| 2.8.4 | 硬阈值触发行为 | `loop-detection.ts` L85 `consecutiveIdenticalCount >= hardThreshold`；`session-runtime-orchestrator.ts` L1265-1273 hard 分支调用 `enqueueMistakeRecord({forceAtLimit:true})`；L1300-1308 MistakeTracker 返回 `action:"stop"` 时调用 `activeRuntime.abort(outcome.reason)`，`finishReason:"aborted"` | `loop_detection.py` L80 `consecutive_identical_count >= hard_threshold`；`runtime.py` L1301-1316 hard 分支调用 `self._mistake_tracker.record(force_at_limit=True)`，`outcome.action=="stop"` 时调用 `self.abort(stop_reason)` + 返回 `BeforeToolResult(stop=True, reason=stop_reason)` | 行为等价：两者都"联动 MistakeTracker + abort"；Charles 额外返回 `BeforeToolResult(stop=True)` 让 hook 链感知停止 | 完全对齐 |
| 2.8.5 | key 老化机制 | `loop-detection.ts` L72-79：仅记录"上一次"调用的 toolName+signature，**无 LRU / 时间窗口**；不同调用立即重置 `consecutiveIdenticalCount=1` | `loop_detection.py` L72-75：与 Cline 完全一致，**无 LRU / 时间窗口** | 两者都缺老化机制，仅在"连续相同"时计数；任何中间不同调用都会重置计数 | 完全对齐（均缺失） |
| 2.8.6 | MistakeTracker mistake_type 枚举 | `mistake-tracker.ts` L39-42 `MistakeReason = "api_error" \| "invalid_tool_call" \| "tool_execution_failed"`，仅 3 类 | `mistake_tracker.py` L21-28 `MistakeType` 常量类 5 类：`PARAM_ERROR` / `TOOL_NOT_FOUND` / `PERMISSION_DENIED` / `EXEC_ERROR` / `TIMEOUT` | Charles 多 2 类（`param_error` / `tool_not_found` / `permission_denied` / `timeout` 是 Cline 没有的细分）；Charles 少 1 类（`api_error` / `invalid_tool_call` 是 Charles 没有的）；分类粒度不同，Charles 偏向"工具执行错误细分"，Cline 偏向"错误来源层级" | 弱对齐（粒度不同） |
| 2.8.7 | 每类独立阈值 | `mistake-tracker.ts` L89 `max = options.maxConsecutiveMistakes`（单一阈值，默认 6）；L112 `if (!max \|\| next < max) return {action:"continue"}` — **不分类型，单一总计数** | `mistake_tracker.py` L57-58 `max_per_type=3`（单类型软阈值）+ `max_total=5`（总硬阈值）；L195-209 按类型计数 `_counts[mistake_type]`，单类型达 `max_per_type` 触发 `continue_with_guidance`，总数达 `max_total` 触发 `stop` | Charles 双层阈值 + 按类型独立计数，比 Cline 的"单一总计数"更精细；Charles 软阈值触发 guidance，Cline 软阈值（即 `< max`）静默 continue | Charles 超出 Cline |
| 2.8.8 | 错误分类逻辑 | `mistake-tracker.ts` L88 `record(input)` 由**调用方**直接传入 `input.reason`（MistakeReason 枚举），**MistakeTracker 本身不做文本分类**；`session-runtime-orchestrator.ts` L1156-1161 在 `turn-finished` 事件中硬编码 `reason:"tool_execution_failed"` | `mistake_tracker.py` L81-94 `classify_mistake(error_text)` 函数，按 `_ERROR_PATTERNS` 关键词列表（L62-78）匹配推断 mistake_type；`runtime.py` L1387-1388 在 `_check_repeated_tool_failures` 中调用 `classify_mistake(error_text)` 自动分类 | Charles 提供自动分类函数，Cline 需调用方显式指定；Charles 的关键词匹配可能误判（如错误文本含 "timeout" 但实际是 permission 问题） | Charles 超出 Cline（自动分类） |
| 2.8.9 | 软阈值提示格式 | `mistake-tracker.ts` L129-135 `decision.action === "continue"` 分支：若 `decision.guidance` 非空，调用 `options.appendRecoveryNotice(guidance, input.reason)`（L431-436 实现为 `conversation.appendMessage({role:"user", content:[{type:"text", text:message}]})`）；guidance 内容由 `onLimitReached` 回调返回，**格式由调用方决定** | `mistake_tracker.py` L230-236 `_build_guidance`：固定格式 `[MistakeTracker 恢复提示] 检测到工具 \`{tool_name}\` 连续 {count} 次犯 \`{mistake_type}\` 类型错误。{hint}`，hint 来自 `_RECOVERY_HINTS` 字典（L98-120，每个 mistake_type 一段固定恢复建议） | Charles 格式固定且内置分类专属 hint；Cline 格式由调用方自定义（更灵活但默认无内容）；Charles 的 hint 更具体（如 PARAM_ERROR 提示"检查工具 schema"） | 弱对齐（格式不同） |
| 2.8.10 | 硬阈值 abort 标记 | `mistake-tracker.ts` L138-149 返回 `{action:"stop", message: buildMistakeLimitStopMessage(...)}`；`session-runtime-orchestrator.ts` L1307 `this.activeRuntime.abort(outcome.reason ?? outcome.message)` → `finishReason:"aborted"` | `mistake_tracker.py` L195-199 返回 `MistakeOutcome(action="stop", message=self._build_stop_message())`；`runtime.py` L1313-1316 / L1397-1399 调用 `self.abort(stop_reason)` + `raise RuntimeError(self._abort_reason)` → `status:"aborted"`，`finish_reason:"aborted"` | 行为等价：两者都通过 abort 路径终止；Charles 额外 `raise RuntimeError` 让主循环 catch 块感知；Cline 通过 `activeRuntime.abort` 让 stream 自然终止 | 完全对齐 |
| 2.8.11 | 集成方式 | `session-runtime-orchestrator.ts` L1062 `handleRuntimeEvent` 在事件流上集中接线：L1084-1098 `tool-started` → `inspectLoopForToolCall`；L1146-1167 `turn-finished` → `enqueueMistakeRecord`；L1287-1310 `activeTrackerWork` 串行 promise 队列保证顺序 | `runtime.py` L268 `self._hooks.before_tool.append(self._loop_detection_hook)` 注册为 before_tool hook；L728 主循环内 `self._check_repeated_tool_failures(tool_calls, tool_messages)` 直接内联调用；无串行队列，主循环天然顺序执行 | Cline 事件驱动 + 串行队列（保证 async record 顺序）；Charles hook + 内联调用（同步顺序）；Charles 更直接，Cline 更解耦 | 弱对齐（架构不同） |
| 2.8.12 | safety rules 引擎 | `rules.ts` L1-49：仅 4 个纯函数 `isRuleEnabled` / `formatRulesForSystemPrompt` / `mergeRulesForSystemPrompt` / `listEnabledRulesFromWatcher` / `loadRulesForSystemPromptFromWatcher`；**无 frontmatter 解析、无条件评估、无 toggle 持久化、无运行时拦截** | `rules_loader.py` L1-1053：完整实现 `parse_yaml_frontmatter` + `evaluate_rule_conditionals`（applyTo/mode/paths 三条件）+ `_match_glob`（wcmatch/picomatch 对标）+ `load_rules_directory` + `format_rules_content` + `load_for_session` + `synchronize_rule_toggles` + `load_local_toggles` / `save_local_toggles` / `load_merged_toggles`（global+local 双层 toggle）+ mtime 缓存 | **PLAN 表"Charles 缺失"判断错误**：Charles 的 rules_loader 比 Cline rules.ts 完整得多；Cline rules.ts 仅是格式化工具，实际 frontmatter 解析在 `apps/vscode/src/core/context/instructions/user-instructions/` 下（Charles 已对标） | Charles 超出 Cline |
| 2.8.13 | 跨轮次状态保持 | `session-runtime-orchestrator.ts` L290-291 `mistakeTracker` / `loopTracker` 为 SessionRuntime 实例字段，**跨 run 复用**；L1165 `mistakeTracker.reset()` 仅在"productive turn"（有成功工具）时重置，**非每 run 重置**；`restore()` 不重置 tracker（因 tracker 属于 SessionRuntime 而非 AgentRuntime） | `runtime.py` L270 `self._mistake_tracker` / L266 `self._loop_tracker` 为 AgentRuntime 实例字段；L394-395 `restore()` 重置两个 tracker；L547-548 `run()` 开始时也重置两个 tracker；**每 run 重置，不跨 run 累积** | Cline tracker 跨 run 累积（直到 productive turn 或 session 结束）；Charles 每 run 重置（即使同一会话内多轮 run 也独立计数） | 弱对齐（生命周期不同） |

## 3. 重点差距详细说明

### 差距 1：MistakeTracker 错误分类粒度与阈值模型不同（对应对比项 2.8.6 / 2.8.7 / 2.8.8）

**Cline 设计**（`mistake-tracker.ts` L39-42, L89, L112）：
- `MistakeReason` 仅 3 类：`api_error` / `invalid_tool_call` / `tool_execution_failed`
- 单一阈值 `maxConsecutiveMistakes`（默认 6，由 `config.execution?.maxConsecutiveMistakes` 配置）
- 不做自动分类：调用方在 `enqueueMistakeRecord` 时显式传入 `reason`（`session-runtime-orchestrator.ts` L1156-1161 硬编码 `reason:"tool_execution_failed"`）
- 软阈值（`next < max`）静默 `continue`，硬阈值（`next >= max`）触发 `onLimitReached` 回调决定 continue/stop
- 跨轮次累积，仅在"productive turn"（`succeeded > 0`）时 `reset()`（L1162-1166）

**Charles 设计**（`mistake_tracker.py` L21-28, L57-58, L81-94, L195-211）：
- `MistakeType` 5 类：`PARAM_ERROR` / `TOOL_NOT_FOUND` / `PERMISSION_DENIED` / `EXEC_ERROR` / `TIMEOUT`
- 双层阈值：`max_per_type=3`（单类型软阈值）+ `max_total=5`（总硬阈值）
- 自动分类：`classify_mistake(error_text)` 按 `_ERROR_PATTERNS` 关键词列表匹配（L62-78），未匹配默认 `EXEC_ERROR`
- 软阈值（`per_type_count >= max_per_type`）触发 `continue_with_guidance`，注入固定格式 hint
- 硬阈值（`_total >= max_total`）触发 `stop`
- 每 run 重置（`runtime.py` L548）

**影响**：
- Charles 的 5 类分类更贴近工具错误实际形态（参数错误、权限拒绝、超时是常见独立类别），但少了 `api_error`（LLM API 层错误）和 `invalid_tool_call`（工具调用格式错误）两类——这两类在 Charles 中由 `runtime.py` 的 `_extract_invalid_tool_calls` / `_build_invalid_tool_result_message`（L2373-2420）独立处理，不进入 MistakeTracker。
- Charles 的双层阈值更精细：单类型连续 3 次就注入 guidance（早干预），总 5 次才 abort（晚停止）；Cline 是单一阈值 6 次，无早干预机制。
- Charles 的自动分类可能误判：如错误文本同时含 "permission" 和 "timeout"，按 `_ERROR_PATTERNS` 顺序优先匹配 `permission`（L66-68 在 L70-71 之前）。
- Charles 缺少 `onLimitReached` 回调机制：Cline 允许调用方自定义 limit 决策（如询问用户是否继续），Charles 是硬编码 stop。

### 差距 2：集成方式 — 事件驱动 vs hook + 内联（对应对比项 2.8.11）

**Cline 设计**（`session-runtime-orchestrator.ts` L1062-1310）：
- `handleRuntimeEvent(event)` 集中处理所有 `AgentRuntimeEvent`
- `tool-started` 事件（L1084-1098）→ `inspectLoopForToolCall(toolName, input, iteration)` → 调用 `loopTracker.inspect` + 软阈值注入 / 硬阈值联动 MistakeTracker
- `turn-finished` 事件（L1146-1167）→ 评估本轮 success/fail 计数，失败时 `enqueueMistakeRecord`，成功时 `mistakeTracker.reset()`
- `enqueueMistakeRecord`（L1287-1310）通过 `activeTrackerWork` 串行 promise 队列链式调用 `mistakeTracker.record`，保证 async record 的顺序与时机
- `trackerAbortInFlight` 标志防止 abort 后继续 record

**Charles 设计**（`runtime.py` L268, L728, L1277-1333, L1350-1423）：
- `_loop_detection_hook`（L1277-1333）注册为 before_tool hook（L268 `self._hooks.before_tool.append`），在工具执行**前**触发
- `_check_repeated_tool_failures`（L1350-1423）在主循环 L728 工具执行**后**直接内联调用
- 同步执行，无串行队列（Python 主循环天然顺序，无 async record 排序问题）
- `_check_repeated_tool_failures` 同时维护 `self._recent_tool_errors` 列表（L264）做"同一工具同一错误连续 N 次"独立检测（L1405-1423），与 MistakeTracker 并存

**影响**：
- Cline 的 loop detection 在 `tool-started` 触发，即工具**开始执行前**就能 abort（避免执行无意义的重复调用）；Charles 的 `_loop_detection_hook` 是 before_tool hook，同样在工具执行前触发，行为等价。
- Cline 的 mistake tracking 在 `turn-finished` 触发，按"整轮 success/fail 计数"评估；Charles 的 `_check_repeated_tool_failures` 在工具执行后立即逐个评估，粒度更细（每个工具独立 record）。
- Charles 多了一层 `_recent_tool_errors` 硬阈值（threshold=3，L1419-1423），是 Phase 26 的遗留逻辑，与 MistakeTracker 的 `max_total=5` 并存——同一错误连续 3 次会先触发 `_recent_tool_errors` 的 RuntimeError，可能提前于 MistakeTracker 的硬阈值。

### 差距 3：rules 引擎能力对比（对应对比项 2.8.12）

**Cline 设计**（`rules.ts` L1-49）：
- 仅 4 个纯函数，核心是 `formatRulesForSystemPrompt`（L10-21）：把 `RuleConfig[]` 拼接为 `\n\n# Rules\n## {name}\n{instructions}` 格式的 system prompt 文本
- `listEnabledRulesFromWatcher`（L35-43）从 `UserInstructionConfigWatcher` 读取已启用的 RuleConfig
- **无 frontmatter 解析**（frontmatter 解析在 `apps/vscode/src/core/context/instructions/user-instructions/frontmatter.ts`，不在 sdk/core 层）
- **无条件评估**（applyTo / paths 条件评估在 `rule-conditionals.ts`，不在 sdk/core 层）
- **无 toggle 持久化**（toggle 在 `rule-helpers.ts` + `stateManager`，不在 sdk/core 层）
- **无运行时拦截**（rules 仅注入 system prompt，由 LLM 自行遵守，无强制约束）

**Charles 设计**（`rules_loader.py` L1-1053）：
- 完整对标 Cline `apps/vscode/src/core/context/instructions/user-instructions/` 下的全部能力
- `parse_yaml_frontmatter`（L131-181）：YAML frontmatter 解析，fail-open 策略
- `evaluate_rule_conditionals`（L433-481）：三类条件评估
  - `applyTo`：agent 模式过滤（act / plan）
  - `mode`：业务模式过滤（自定义字符串列表，如 research / trade）
  - `paths`：工作空间路径 glob 匹配
- `_match_glob`（L279-333）：wcmatch/picomatch 对标，支持 brace expansion / negation / extglob / DOTGLOB；wcmatch 不可用时回退到简化正则
- `load_rules_directory`（L568-683）：递归扫描 .md 文件，支持 `excluded_subdirs`（对标 Cline 排除 workflows/hooks/skills 子目录）
- `synchronize_rule_toggles`（L889-957）：toggle 列表与磁盘文件同步，新增文件默认 True，已删除文件清理
- `load_local_toggles` / `save_local_toggles` / `load_merged_toggles`（L965-1053）：global + local 双层 toggle（local 覆盖 global），对标 Cline globalState + workspaceState
- `_read_with_mtime_cache`（L524-556）：mtime 缓存，避免无变更文件的重复 I/O
- 通过 `agent/context.py` L49 导入并在 system prompt 构建时调用，`agent/server.py` L2055+ 提供 toggle 管理 API

**影响**：
- PLAN 表 2.8.12 标注"Charles 缺失"safety rules 引擎，**与实际不符**：Charles 的 `rules_loader.py` 不仅存在，且功能比 Cline sdk/core 层的 `rules.ts` 完整得多。
- 真正的"Charles 缺失"应是：Cline 在 `apps/vscode/src/core/context/instructions/` 下的完整能力，Charles 已通过 `rules_loader.py` 对标实现，**无缺失**。
- 两者都**不是运行时安全引擎**：rules 仅注入 system prompt，由 LLM 自行遵守；真正的运行时安全由 LoopDetectionTracker + MistakeTracker 承担。

### 差距 4：跨轮次状态保持生命周期不同（对应对比项 2.8.13）

**Cline 设计**：
- `mistakeTracker` / `loopTracker` 是 `SessionRuntime` 实例字段（L290-291），**不属于 AgentRuntime**
- 每次 `run()` 时 `SessionRuntime` 创建临时 `AgentRuntime`（L315-317 工厂），tracker 留在 SessionRuntime 层
- `restore()` 不重置 tracker（tracker 在 SessionRuntime 层，restore 只影响 AgentRuntime 层的 state）
- tracker 跨 run 累积，仅在"productive turn"（L1162-1166 `succeeded > 0`）时 `mistakeTracker.reset()`

**Charles 设计**：
- `_mistake_tracker` / `_loop_tracker` 是 `AgentRuntime` 实例字段（L266, L270）
- `run()` 开始时（L547-548）重置两个 tracker
- `restore()` 时（L394-395）也重置两个 tracker
- tracker 不跨 run 累积，每次 run 独立计数

**影响**：
- Cline 的 tracker 能跨 run 累积错误：如 run 1 失败 3 次、run 2 失败 3 次，Cline 会累积到 6 次触发 abort；Charles 每 run 重置，run 2 重新从 0 计数。
- Charles 的设计更"宽容"：每次 run 独立评估，不因历史失败累积而提前 abort；但也可能导致同一会话内反复犯同类错误而不触发硬停止。
- Cline 的 `productive turn reset` 逻辑（L1162-1166）保证"成功一轮后清零"，避免跨任务累积误报；Charles 的 `_check_repeated_tool_failures` L1380-1382 也有类似逻辑（成功调用 `self._mistake_tracker.reset()`），但因每 run 重置而弱化。

## 4. nanobot 残留检查

### 检查范围

针对 P2.8 涉及的 4 个核心文件执行 `grep -n nanobot`：

| 文件 | nanobot 匹配数 | 残留类型 |
|------|---------------|---------|
| `agent/loop_detection.py` | 0 | 无 |
| `agent/mistake_tracker.py` | 0 | 无 |
| `agent/rules_loader.py` | 0 | 无 |
| `agent/runtime.py`（循环检测 + 错误追踪相关段落） | 0 | 无 |

### 注释残留分类

**无注释残留**。P2.8 涉及的 4 个文件均未引用 nanobot。所有 docstring 和行内注释均以"对标 Cline xxx"形式标注来源。

### 实现逻辑残留检查结论

**未发现实现逻辑残留**。所有实现均基于 Cline 对标设计：
- `LoopDetectionTracker` 对标 Cline `loop-detection.ts::LoopDetectionTracker`
- `MistakeTracker` 对标 Cline `mistake-tracker.ts::MistakeTracker`（且在 mistake_type 枚举和双层阈值上做了增强）
- `rules_loader.py` 对标 Cline `apps/vscode/src/core/context/instructions/user-instructions/` 下的 frontmatter.ts / rule-conditionals.ts / rule-helpers.ts
- `_loop_detection_hook` / `_check_repeated_tool_failures` 对标 Cline `session-runtime-orchestrator.ts` 的 `inspectLoopForToolCall` / `enqueueMistakeRecord`

### 与 P2.1 报告的关联

P2.1 报告中提到的 12 个 nanobot 残留文件（`providers/qwen.py` / `tools/exec_tool.py` / `tools/file_tools.py` / `tools/web_tool.py` / `skills/registry.py` / `skills/loader.py` / `skills/__init__.py` / `session.py` / `server.py` / `context.py` / `skills/skill_tool.py`）**均不属于 P2.8 的循环检测 / 错误追踪 / rules 引擎职责范围**。其中 `context.py` L275 的 `[已废弃] nanobot 风格` 标注是 `extra_sections` 参数的废弃说明，与 rules_loader 的实现无关（rules_loader 由 `context.py` L49 导入调用，但 rules_loader 本身无 nanobot 残留）。

### 残留风险评估

| 残留类型 | 文件数 | 风险等级 | 处理建议 |
|---------|--------|---------|---------|
| 注释残留 | 0 | 无 | 无需处理 |
| 实现逻辑残留 | 0 | 无 | 无需处理 |

## 5. 修复建议

### P0（高优先级，影响架构正确性）

无。Charles 的 LoopDetectionTracker + MistakeTracker + rules_loader 功能完整，且在多个维度超出 Cline 能力，运行时安全机制正确。

### P1（中优先级，影响行为一致性）

**建议 1：MistakeTracker 跨 run 状态保持**

参考 Cline `session-runtime-orchestrator.ts` L290-291，将 `MistakeTracker` / `LoopDetectionTracker` 的生命周期从 `AgentRuntime` 实例级改为会话级：
- 当前 `runtime.py` L547-548 在 `run()` 开始时重置两个 tracker，导致跨 run 累积失效
- 建议移除 `run()` 中的 `reset()` 调用，仅在 `restore()` 时重置（L394-395 保留）
- 或引入 `SessionRuntime` 编排层（见 P2.1 建议 1），将 tracker 上移到会话层

**收益**：跨 run 累积错误能触发会话级硬停止，避免同一会话内反复犯同类错误。

**改动范围**：`runtime.py` L547-548 删除两行 `reset()` 调用；测试跨 run 错误累积场景。

**注意**：此改动会改变现有行为，需评估是否与 Charles 的"每 run 独立"设计意图冲突。若 Charles 有意每 run 重置，则保留现状。

### P2（低优先级，改善分类精度）

**建议 2：MistakeTracker 补充 api_error / invalid_tool_call 分类**

参考 Cline `mistake-tracker.ts` L39-42 的 3 类 `MistakeReason`，Charles 的 `MistakeType`（L21-28）可补充：
- `API_ERROR`：LLM API 层错误（如 rate_limit / network_error）
- `INVALID_TOOL_CALL`：工具调用格式错误（missing_name / missing_arguments / invalid_arguments）

当前 Charles 的 `invalid_tool_call` 由 `runtime.py` L2373-2420 的 `_extract_invalid_tool_calls` / `_build_invalid_tool_result_message` 独立处理，不进入 MistakeTracker。可考虑在 `_check_repeated_tool_failures` 中识别 invalid_tool_call 模式并记录到 MistakeTracker，让连续格式错误也能触发软/硬阈值。

**收益**：错误分类更完整，连续格式错误能被 MistakeTracker 拦截。

**改动范围**：`mistake_tracker.py` 新增 2 个常量 + `_ERROR_PATTERNS` 新增关键词；`runtime.py` `_check_repeated_tool_failures` 增加 invalid_tool_call 识别。

**建议 3：`classify_mistake` 支持优先级配置或正则匹配**

当前 `classify_mistake`（`mistake_tracker.py` L81-94）按 `_ERROR_PATTERNS` 列表顺序匹配，先匹配先返回。如错误文本同时含 "permission" 和 "timeout"，会优先归类为 `PERMISSION_DENIED`（L66-68 在 L70-71 之前）。

可考虑：
- 支持正则匹配（如 `r"permission.*denied"` 提高精度）
- 支持调用方传入优先级覆盖（如 `classify_mistake(text, preferred_types=["timeout"])`）

**收益**：减少误判，分类更准确。

### P3（可选，文档修正）

**建议 4：修正 PLAN 表 2.8.12 的"Charles 缺失"判断**

`AGENT_COMPARISON_PLAN_V2.md` L515 表 2.8.12 标注"safety rules 引擎 — Charles 缺失"，与实际不符。Charles 的 `rules_loader.py`（1053 行）完整实现了 frontmatter 解析、条件评估、glob 匹配、toggle 持久化、mtime 缓存，能力远超 Cline sdk/core 层的 `rules.ts`（49 行纯函数）。

建议修正为："safety rules 引擎 — Charles 反而更完整（rules_loader.py 1053 行 vs rules.ts 49 行）"。

## 6. 验证方法建议

### 验证方法 1：构造连续相同参数工具调用，对比两边处理

按 PLAN 章节末尾的验证方法建议：

1. **软阈值触发**（连续 3 次相同调用）：
   - Cline：`tool-started` 事件触发 `inspectLoopForToolCall` → `verdict.kind === "soft"` → `conversation.appendMessage` 注入 user 消息 → 工具继续执行
   - Charles：`_loop_detection_hook` 触发 → `verdict.kind == "soft"` → `logger.warning` + `_inject_user_notice` 注入 user 消息 + emit message_added → 返回 None（不阻止）→ 工具继续执行
   - **预期**：两者行为等价，第 3 次调用时均注入"建议换思路"提示，第 4 次调用无提示（因 `consecutive_identical_count` 已超过 soft_threshold）

2. **硬阈值触发**（连续 5 次相同调用）：
   - Cline：`inspectLoopForToolCall` → `verdict.kind === "hard"` → `enqueueMistakeRecord({forceAtLimit:true})` → `mistakeTracker.record` 返回 `action:"stop"` → `activeRuntime.abort(outcome.message)` → `finishReason:"aborted"`
   - Charles：`_loop_detection_hook` → `verdict.kind == "hard"` → `self._mistake_tracker.record(force_at_limit=True)` → `outcome.action == "stop"` → `self.abort(stop_reason)` + 返回 `BeforeToolResult(stop=True, reason=stop_reason)` → 主循环 catch 块 `status:"aborted"`
   - **预期**：两者均 abort，status/finishReason 一致

3. **跨轮次重置**（第 3 次后插入一次不同调用，再连续 3 次相同）：
   - 两者均应在第 4 次不同调用时 `consecutive_identical_count` 重置为 1，第 7 次相同调用重新触发软阈值
   - **预期**：行为一致（key 老化机制相同，均无 LRU/时间窗口）

### 验证方法 2：MistakeTracker 错误分类与阈值触发

1. **单类型软阈值**（连续 3 次 `param_error`）：
   - Cline：无单类型阈值，仅总计数 `next < max(6)` 静默 continue
   - Charles：第 3 次 `param_error` 时 `per_type_count >= max_per_type(3)` → 返回 `continue_with_guidance` + guidance 注入
   - **预期**：Charles 提前注入 guidance，Cline 静默

2. **总硬阈值**（连续 5 次混合错误）：
   - Cline：第 6 次时 `next >= max(6)` → 触发 `onLimitReached` → 默认 stop
   - Charles：第 5 次时 `_total >= max_total(5)` → 返回 `stop` + `_build_stop_message`
   - **预期**：Charles 提前 1 次 abort（5 vs 6）

3. **成功调用重置**：
   - Cline：`turn-finished` 事件中 `succeeded > 0` → `mistakeTracker.reset()`
   - Charles：`_check_repeated_tool_failures` 中成功调用 → `self._mistake_tracker.reset()`（L1380-1382）
   - **预期**：行为一致

### 验证方法 3：rules 引擎条件过滤

1. **applyTo 条件**：构造 frontmatter `applyTo: [plan]` 的规则文件，分别在 act / plan 模式下加载
   - Cline：`rule-conditionals.ts` 评估 applyTo
   - Charles：`rules_loader.py::_evaluate_apply_to_conditional`（L369-400）评估 applyTo
   - **预期**：仅 plan 模式下激活

2. **paths 条件**：构造 frontmatter `paths: [src/**/*.py]` 的规则文件，候选路径含/不含 `src/foo.py`
   - Cline：`picomatch(pattern, { dot: true })`
   - Charles：`_match_glob`（L279-333）wcmatch 优先，回退正则
   - **预期**：含 `src/foo.py` 时激活，不含时不激活

3. **toggle 持久化**：禁用某规则文件，重启会话后检查 toggle 是否保留
   - Cline：`stateManager.update('localClineRulesToggles', toggles)`
   - Charles：`save_toggles` / `load_toggles`（L836-887）+ global/local 双层
   - **预期**：toggle 跨会话保留，local 覆盖 global

### 验证方法 4：nanobot 残留扫描

执行 `grep -rn "nanobot" agent/loop_detection.py agent/mistake_tracker.py agent/rules_loader.py agent/runtime.py` 确认无残留。

**预期**：无任何匹配（已验证，见第 4 节）。
