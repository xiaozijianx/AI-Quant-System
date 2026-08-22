# Phase 7.15 循环检测对比

> 子代理：Agent 与 Cline 对比执行
> 阶段：P7.15 循环检测对比
> 计划依据：`AGENT_COMPARISON_PLAN_V2.md` L2867-2891
> 生成时间：2026-07-29 (Asia/Shanghai)

---

## 1. 范围与方法

本报告对比 Cline SDK 与 Charles（`CASE-AI量化系统/agent`）在"循环检测 / 错误追踪 / 中止策略"三个层面的实现差异，覆盖以下源文件：

**Cline 实现**
- `third_party/cline/sdk/packages/core/src/runtime/safety/loop-detection.ts`（LoopDetectionTracker + 纯函数）
- `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts`（MistakeTracker + 停止消息构造）
- `third_party/cline/sdk/packages/core/src/runtime/safety/rules.ts`（规则格式化辅助函数 — 仅为 system-prompt 渲染辅助，并非运行时安全规则引擎）
- `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L1070-1310（hook 接线、abort 路径、telemetry）

**Charles 实现**
- `agent/loop_detection.py`（LoopDetectionTracker + 纯函数）
- `agent/mistake_tracker.py`（MistakeTracker + classify_mistake + 恢复提示）
- `agent/rules_loader.py`（规则加载器 — frontmatter 解析、条件评估、toggle 持久化）
- `agent/runtime.py` L265-270、L394-395、L547-548、L1277-1423（hook 接线、reset 路径、abort 路径、Phase 26 重复失败检测）

**nanobot 残留核查**
- 全局 `Grep "nanobot"`（不区分大小写）在 `agent/` 目录共命中 12 个 `.py` 文件、55 行；逐行核查后全部为 docstring/注释中的历史对标说明（如"对标 nanobot SkillsLoader"、"兼容 nanobot 现有配置"），未发现任何 `import nanobot` / `from nanobot` 形式的实际代码依赖。
- 结论：**仅注释残留**，无实现逻辑残留。详见第 6 节。

---

## 2. 总览对照表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 计划原结论 | 实际结论 |
|---|--------|-----------|-------------|---------|-----------|---------|
| 7.15.1 | LoopDetectionTracker 类 | `loop-detection.ts` L125-161 | `loop_detection.py` L99-124 | 类签名不同（Cline 接收 `{name, input}` 对象；Charles 拆为 `tool_name, input_value` 两参），内部状态/逻辑等价 | 已对齐 | **对齐** |
| 7.15.2 | 软/硬阈值默认值 | soft=3 / hard=5（L113-116） | soft=3 / hard=5（`MistakeTrackerConfig` L57-58；`LoopDetectionConfig` 默认值见 `types.py`） | 默认值一致 | 已对齐 | **对齐** |
| 7.15.3 | 循环判定 key | `tool_name + toolCallSignature(input)`（L50-59，递归排序 key 后 JSON.stringify） | `tool_name + tool_call_signature(input_value)`（L51-62，递归排序 key 后 json.dumps，`ensure_ascii=False, separators=(",", ":")`） | 序列化参数略有差异（Charles 显式禁用 ASCII 转义、紧凑分隔符），功能等价；中文字符在 Charles 端不会被转义为 `\uXXXX` | 已对齐 | **对齐**（序列化参数微差） |
| 7.15.4 | MistakeTracker 类 | `mistake-tracker.ts` L80-159 | `mistake_tracker.py` L123-257 | Cline 单阈值 `maxConsecutiveMistakes` + 异步 `record()` + onLimitReached 回调；Charles 双阈值（`max_per_type=3` / `max_total=5`）+ 同步 `record()` + 内置分类器 | 已对齐 | **Charles 增强**（见 7.15.5/7.15.6） |
| 7.15.5 | mistake_type 枚举 | 3 类：`api_error` / `invalid_tool_call` / `tool_execution_failed`（`MistakeReason` L39-42）；`buildMistakeLimitStopMessage` 另接受第 4 类 `completion_without_submit`（L170-173）但未纳入 `MistakeReason` 联合 | 5 类：`PARAM_ERROR` / `TOOL_NOT_FOUND` / `PERMISSION_DENIED` / `EXEC_ERROR` / `TIMEOUT`（L21-28） | Charles 多 2 类（permission_denied / timeout 拆分），且命名风格不同（snake_case 业务语义 vs Cline 通用错误源） | 已对齐 | **不一致** — Charles 分类更细 |
| 7.15.6 | 每类独立阈值 | **无** — 仅一个全局 `maxConsecutiveMistakes`（L57），不区分 mistake_type 计数 | **有** — `max_per_type=3`（单类型软阈值）+ `max_total=5`（总硬阈值），按 `_counts: dict[str, int]` 分类型计数（L149、L188-189） | Charles 引入 per-type 维度，Cline 无此概念 | 已对齐 | **不一致** — Charles 多一层 per-type 维度 |
| 7.15.7 | safety rules 引擎 | `safety/rules.ts`（L1-49）—— 但实际只是"规则文档→system prompt"的格式化辅助（`formatRulesForSystemPrompt` / `isRuleEnabled` / `mergeRulesForSystemPrompt` / `listEnabledRulesFromWatcher` / `loadRulesForSystemPromptFromWatcher`），**不是运行时安全规则引擎** | `agent/rules_loader.py`（1053 行）—— frontmatter 解析 + 条件评估（applyTo / mode / paths）+ toggle 持久化（global+local）+ mtime 缓存；功能显著多于 Cline `rules.ts` | Charles 有等价（且更丰富）的规则加载能力，但位于 `rules_loader.py` 而非 `safety/rules.py`；命名/位置不对应 | Charles 缺失 | **计划误判** — Charles 实际未缺失，只是文件名/位置不同 |
| 7.15.8 | MistakeLimitExceeded 概念 | 无 `MistakeLimitExceeded` 异常类；通过 `MistakeOutcome.action="stop"` + `task.mistake_limit_reached` telemetry 事件 + `onConsecutiveMistakeLimitReached` 回调表达（`config.ts` L273、`core-events.ts` L74、`session-runtime-orchestrator.ts` L406-414） | 无 `MistakeLimitExceeded` 异常类；通过 `MistakeOutcome.action="stop"` + `MISTAKE_LIMIT_REACHED="mistake.limit_reached"` 事件（`types.py` L756）+ `_build_stop_message()` 表达 | 两侧均无显式异常类，均通过 outcome+事件表达；Charles 缺 `onLimitReached` 回调 hook（无外部决策注入点） | 已对齐 | **基本对齐**（Charles 缺外部决策回调） |

---

## 3. LoopDetectionTracker 细节对比

### 3.1 状态结构

| 字段 | Cline (`LoopDetectionState`) | Charles (`LoopDetectionState`) | 一致性 |
|------|------------------------------|--------------------------------|--------|
| lastToolName | `string` | `str` | 一致 |
| lastToolSignature | `string` | `str` | 一致 |
| consecutiveIdenticalCount | `number` | `int` | 一致 |

### 3.2 签名生成函数

Cline `toolCallSignature`（loop-detection.ts L50-59）：
```ts
return JSON.stringify(sortKeys(input));
```

Charles `tool_call_signature`（loop_detection.py L51-62）：
```python
return json.dumps(_sort_keys(input_value), ensure_ascii=False, separators=(",", ":"))
```

**差异**：Charles 显式禁用 ASCII 转义 + 紧凑分隔符。对纯 ASCII 输入两者输出完全相同；对包含中文/Unicode 的输入，Cline 会输出 `\uXXXX`，Charles 输出原文。功能等价，比较时基于自身输出一致性，不影响循环检测语义。

### 3.3 检测逻辑

两侧 `checkRepeatedToolCall` / `check_repeated_tool_call` 逻辑完全等价：
- `tool_name == last_tool_name && signature == last_tool_signature` → `count += 1`
- 否则 `count = 1`
- 更新 `last_tool_name` / `last_tool_signature`
- `count >= hardThreshold` → `kind="hard"`
- `count == softThreshold` → `kind="soft"`
- 否则 `kind="ok"`

**注意**：Cline 用 `===` 严格相等判定 soft（L84），Charles 用 `==` 相等判定 soft（L88），都是 `==` 语义；Charles hard 用 `>=`（L80），Cline hard 用 `>=`（L85），一致。

### 3.4 verdict 消息文案

两侧 soft / hard 消息文案完全一致（仅大小写/标点差异）：
- Cline hard: `` `Detected ${n} consecutive identical calls to \`${name}\`; stopping to avoid a loop.` ``
- Charles hard: `` f"Detected {n} consecutive identical calls to `{tool_name}`; stopping to avoid a loop." ``

### 3.5 配置注入

| 维度 | Cline | Charles |
|------|-------|---------|
| 配置类型 | `LoopDetectionConfig { softThreshold, hardThreshold }`（@cline/shared） | `LoopDetectionConfig`（agent/types.py） |
| 默认值 | soft=3 / hard=5（L113-116） | soft=3 / hard=5（LoopDetectionConfig 默认） |
| 关闭开关 | `execution.loopDetection === false` 时 `loopDetectionDisabled=true`（session-runtime-orchestrator.ts L439-441） | **未实现关闭开关** — `LoopDetectionTracker` 始终启用，通过 `before_tool` hook 始终接入 |

**差异点**：Cline 支持通过 `execution.loopDetection=false` 完全禁用循环检测；Charles 无此开关。属于次要缺失，不影响默认行为。

---

## 4. MistakeTracker 细节对比

### 4.1 错误分类

| Cline `MistakeReason` | Charles `MistakeType` | 映射关系 |
|----------------------|----------------------|---------|
| `api_error` | — | Charles 无对应分类（API 错误由 provider 层处理） |
| `invalid_tool_call` | `PARAM_ERROR` | 语义近似（schema 校验失败 / 字段缺失） |
| — | `TOOL_NOT_FOUND` | Charles 拆出"工具不存在"独立分类 |
| — | `PERMISSION_DENIED` | Charles 拆出"权限拒绝"独立分类 |
| `tool_execution_failed` | `EXEC_ERROR` | 语义等价 |
| — | `TIMEOUT` | Charles 拆出"超时"独立分类 |
| (`completion_without_submit`，仅在 `buildMistakeLimitStopMessage` 签名中出现，`MistakeReason` 联合未包含) | — | Cline 类型定义不一致 |

**Charles 额外能力**：`classify_mistake(error_text)`（L81-94）通过关键词模式从错误文本反推 mistake_type，Cline 无此能力（调用方需显式传入 reason）。

### 4.2 阈值结构

| 维度 | Cline | Charles |
|------|-------|---------|
| 单一阈值 | `maxConsecutiveMistakes`（L57） | — |
| 单类型软阈值 | 无 | `max_per_type=3`（L57） |
| 总硬阈值 | （即 `maxConsecutiveMistakes`） | `max_total=5`（L58） |
| 计数维度 | 单一标量 `consecutiveMistakes` | 双层：`_counts: dict[str, int]`（按类型）+ `_total: int`（总计） |
| 软阈值触发后行为 | 调用 `onLimitReached` 回调；若返回 `continue` 则 `consecutiveMistakes=0` 重置（L134） | 返回 `action="continue_with_guidance"` + guidance 文本；通过 `_soft_triggered` set 保证同类型只触发一次（L203-209） |
| 硬阈值触发后行为 | 返回 `action="stop"` + stop message（L138-149） | 返回 `action="stop"` + `_build_stop_message()`（L195-199） |

**关键差异**：
1. Charles 的 per-type 独立阈值是其原创设计，Cline 无对应概念。这意味着 Charles 中"3 次参数错误 + 2 次权限错误"不会触发硬停止（per-type 都未达 max_per_type，但 _total 已达 max_total=5 时仍会硬停止）；Cline 中任意 5 次 mistake（不分类）即触发硬停止。
2. Cline 通过 `onLimitReached` 回调让宿主（如 Hub）参与决策，可"继续运行"；Charles 无外部决策注入点，硬阈值触发后只能 stop。
3. Charles `_soft_triggered` 集合避免同一类型反复注入 guidance；Cline 通过 `consecutiveMistakes=0` 重置后才能再次触发软阈值。

### 4.3 record() 接口

| 字段 | Cline `RecordMistakeInput` | Charles `record()` 参数 |
|------|---------------------------|--------------------------|
| iteration | `number` | `int` |
| reason | `MistakeReason`（3 类枚举） | `str`（5 类常量） |
| details | `string?` | `str` |
| forceAtLimit | `boolean?` | `bool=False` |
| tool_name | **无** | `str`（必填） |

**差异**：Charles 额外要求 `tool_name`，用于在 stop message 和 guidance 中标识工具；Cline 不需要（调用方已知上下文）。

### 4.4 中止路径

**Cline**（session-runtime-orchestrator.ts L1287-1310）：
```
enqueueMistakeRecord → mistakeTracker.record(input) → outcome.action==="stop"
  → trackerAbortInFlight = true
  → conversation.appendMessage({role:"user", text: outcome.message})
  → activeRuntime.abort(outcome.reason ?? outcome.message)
```
通过 `activeTrackerWork = activeTrackerWork.then(...)` 串行队列保证 record 顺序。

**Charles**（runtime.py L1305-1316、L1388-1399）：
```
mistake_tracker.record(...) → outcome.action==="stop"
  → self.abort(stop_reason)        # 统一 abort 路径，status="aborted"
  → return BeforeToolResult(stop=True, reason=stop_reason)   # 在 hook 路径
  或 raise RuntimeError(self._abort_reason)                  # 在 _check_repeated_tool_failures 路径
```
Charles 无串行队列（同步 `record()`），但 hook 路径与 `_check_repeated_tool_failures` 路径可能产生重复 abort 调用（`abort` 内部应幂等，未在本次核查中验证）。

### 4.5 telemetry / 事件

| 维度 | Cline | Charles |
|------|-------|---------|
| 限制触发事件 | `task.mistake_limit_reached`（core-events.ts L74）通过 `onLimitTelemetry` 钩子发射一次 | `MISTAKE_LIMIT_REACHED = "mistake.limit_reached"`（types.py L756） |
| 事件命名风格 | `task.mistake_limit_reached`（点号分隔 + task 前缀） | `mistake.limit_reached`（点号分隔，无 task 前缀） |
| 触发次数保证 | `onLimitTelemetry` 在 `record()` 内"exactly once"（L123 注释） | 由调用方控制；hook 路径 + `_check_repeated_tool_failures` 路径都可能触发，未做去重 |

### 4.6 重置时机

| 时机 | Cline | Charles |
|------|-------|---------|
| `run()` 开始 | `mistakeTracker.reset()` + `loopTracker.reset()`（L540-541） | `_loop_tracker.reset()` + `_mistake_tracker.reset()`（L547-548） |
| 成功调用 | `mistakeTracker.reset()`（turn-finished 中 succeeded>0 时，L1165） | `_mistake_tracker.reset()`（`_check_repeated_tool_failures` 中成功时，L1381） |
| abort | — | `_loop_tracker.reset()` + `_mistake_tracker.reset()`（L394-395） |

**差异**：Charles 在 abort 路径额外重置；Cline 未在 abort 路径重置（依赖下次 `run()` 重置）。

---

## 5. before_tool Hook 接线对比

### 5.1 Cline 接线方式

Cline **不使用 before_tool hook** 接入循环检测。改为在 `session-runtime-orchestrator.ts` L1084-1098 的 `tool-started` 事件分支中调用 `inspectLoopForToolCall(toolName, input, iteration)`：

```ts
case "tool-started": {
    this.inspectLoopForToolCall(
        event.toolCall.toolName,
        event.toolCall.input,
        event.iteration,
    );
    break;
}
```

`inspectLoopForToolCall`（L1244-1274）：
- `verdict.kind === "ok"` → 直接返回
- `verdict.kind === "soft"` → `conversation.appendMessage({role:"user", text: verdict.message})`
- `verdict.kind === "hard"` → `enqueueMistakeRecord({iteration, reason:"tool_execution_failed", forceAtLimit:true, details: verdict.message})`

### 5.2 Charles 接线方式

Charles 通过 `_hooks.before_tool.append(self._loop_detection_hook)`（runtime.py L268）接入：

`_loop_detection_hook`（L1277-1333）：
- `verdict.kind === "hard"` → `_mistake_tracker.record(force_at_limit=True)`
  - `outcome.action === "stop"` → `self.abort(stop_reason)` + `return BeforeToolResult(stop=True, reason=stop_reason)`
  - `outcome.action === "continue_with_guidance"` → `_inject_user_notice(outcome.guidance)`
- `verdict.kind === "soft"` → `logger.warning(...)` + `_inject_user_notice(verdict.message)`

`_inject_user_notice`（L1335-1348）：追加 user 消息 + emit `message_added` 事件。

### 5.3 接线差异

| 维度 | Cline | Charles |
|------|-------|---------|
| 接入点 | `tool-started` 事件回调 | `before_tool` hook |
| 是否可阻止调用 | 否（事件回调在调用开始后才触发） | 是（hook 返回 `stop=True` 可阻止） |
| soft 分支日志 | 无独立日志，仅追加消息 | `logger.warning` + 追加消息 |
| hard 分支 abort | 通过 `enqueueMistakeRecord` 异步链 + `activeRuntime.abort` | 同步 `self.abort` + `BeforeToolResult(stop=True)` |
| 消息注入方式 | `conversation.appendMessage` 直接修改 conversation | `_inject_user_notice` 修改 `_state.messages` + emit `message_added` |
| 串行化保证 | `activeTrackerWork` Promise 链 | 无（同步调用） |

**关键差异**：Charles 在 `before_tool` hook 中拦截，可在调用前阻止；Cline 在 `tool-started` 事件中观察，调用已开始。这意味着 Charles 硬阈值触发时可阻止本次工具执行，Cline 不能（只能 abort 整个 run）。

---

## 6. nanobot 残留核查

全局 `Grep -i "nanobot"` 在 `agent/` 目录命中 12 个 Python 文件、55 行。逐文件分类：

| 文件 | 命中行数 | 残留类型 | 说明 |
|------|---------|---------|------|
| `agent/context.py` | 1 | 注释残留 | L275 docstring 标注"已废弃 nanobot 风格的额外段落" |
| `agent/session.py` | 2 | 注释残留 | L2/L22 docstring "对标 Cline session persistence + nanobot session_key" |
| `agent/server.py` | 3 | 注释残留 | L2/L4/L28 docstring "对标 Cline server + nanobot routes/chat.py" |
| `agent/skills/loader.py` | 7 | 注释残留 | 多处 docstring "对标 Cline skills discovery + nanobot SkillsLoader" |
| `agent/skills/registry.py` | 4 | 注释残留 | docstring 历史对标说明 |
| `agent/skills/__init__.py` | 2 | 注释残留 | 模块 docstring |
| `agent/skills/skill_tool.py` | 1 | 注释残留 | L18 docstring "与 nanobot 的子 agent 隔离执行有本质区别" |
| `agent/providers/qwen.py` | 7 | 注释残留 | docstring "兼容 nanobot 现有配置" / "对标 nanobot openai_compat_provider.py" |
| `agent/tools/exec_tool.py` | 8 | 注释残留 | docstring "对标 Cline BashTool + nanobot ShellTool" |
| `agent/tools/file_tools.py` | 4 | 注释残留 | docstring "对标 Cline FileReadTool + nanobot FilesystemTool" |
| `agent/tools/__init__.py` | 1 | 注释残留 | 模块 docstring |
| `agent/tools/web_tool.py` | 5 | 注释残留 | docstring "对标 Cline WebSearchTool + nanobot WebSearchTool" |

**核查结论**：
- 全部 55 行命中均为 docstring/注释中的历史对标说明
- **未发现任何 `import nanobot` 或 `from nanobot` 形式的实际代码依赖**
- **未发现任何以 nanobot 命名的类、函数、变量、配置项**
- 无 `nanobot/` 目录或 Python 模块存在于代码库中
- 因此判定为**仅注释残留**，无实现逻辑残留

按用户规则 1（"之前完成正确的功能尽量不要修改"）+ 规则 4（"保留之前的函数逻辑"），这些注释属于历史对标说明，不构成功能差异，本报告不要求清理。

---

## 7. 结论与建议

### 7.1 与计划原结论的偏差

计划（AGENT_COMPARISON_PLAN_V2.md L2879-2888）的 8 项对比中，有 3 项与实际代码状态不符：

| # | 计划原结论 | 实际结论 | 证据 |
|---|-----------|---------|------|
| 7.15.5 | mistake_type 枚举 5 类 — 已对齐 | **不一致** — Cline 仅 3 类（+1 未纳入 MistakeReason 联合），Charles 5 类 | Cline `mistake-tracker.ts` L39-42 |
| 7.15.6 | 每类独立阈值 — 已对齐 | **不一致** — Cline 无 per-type 阈值，仅单一 `maxConsecutiveMistakes` | Cline `mistake-tracker.ts` L57、L81、L90 |
| 7.15.7 | safety rules 引擎 — Charles 缺失 | **计划误判** — Charles 有 `rules_loader.py`（1053 行），功能比 Cline `rules.ts`（49 行）更丰富 | Charles `agent/rules_loader.py`；Cline `safety/rules.ts` |

其余 5 项（7.15.1/7.15.2/7.15.3/7.15.4/7.15.8）基本对齐，仅有微差（序列化参数、配置关闭开关、外部决策回调等）。

### 7.2 Charles 相对 Cline 的增强点

1. **MistakeTracker 分类更细**：5 类 vs Cline 3 类，多出 `permission_denied` / `timeout` 两个独立分类
2. **per-type 独立阈值**：Charles 引入 `max_per_type=3` 单类型软阈值 + `max_total=5` 总硬阈值双层结构；Cline 仅有单一 `maxConsecutiveMistakes`
3. **错误文本分类器**：`classify_mistake(error_text)` 通过关键词模式从错误文本反推 mistake_type；Cline 要求调用方显式传入
4. **rules_loader 能力**：Charles `rules_loader.py` 支持 frontmatter 解析、applyTo/mode/paths 三维条件评估、global+local toggle 持久化、mtime 缓存；Cline `rules.ts` 仅是规则格式化辅助
5. **before_tool hook 接入**：Charles 在工具调用前可阻止；Cline 在 `tool-started` 事件中只能观察

### 7.3 Charles 相对 Cline 的缺失点

1. **无 `execution.loopDetection=false` 关闭开关**：Cline 支持配置禁用循环检测；Charles 始终启用
2. **无 `onLimitReached` 外部决策回调**：Cline 允许宿主（如 Hub）注入"继续/停止"决策；Charles 硬阈值触发后只能 stop
3. **无串行队列保证**：Cline 通过 `activeTrackerWork` Promise 链串行化 record 调用；Charles 同步调用，无显式串行化（Python 单线程 GIL 下通常无问题，但 hook 路径 + `_check_repeated_tool_failures` 路径可能重复触发 abort）
4. **telemetry 事件命名不统一**：Cline `task.mistake_limit_reached` vs Charles `mistake.limit_reached`（缺 `task.` 前缀）
5. **telemetry 去重未保证**：Cline `onLimitTelemetry` 显式声明"exactly once"；Charles 两条路径都可能触发，未做去重

### 7.4 是否需要对齐的建议

按用户规则 1（"之前完成正确的功能尽量不要修改"），上述差异多为 Charles 的增强设计，不建议回退到 Cline 的简化模型。仅以下两点建议考虑补齐：

- **telemetry 事件命名统一**：将 `mistake.limit_reached` 改为 `task.mistake_limit_reached`，与 Cline 对齐（影响 `types.py` L756 与所有 emit 点）
- **重复 abort 去重**：在 `_loop_detection_hook` 和 `_check_repeated_tool_failures` 共用的 abort 入口处加幂等检查（如 `if self._aborted: return`），避免双重 abort 导致状态不一致

其余差异（分类粒度、per-type 阈值、classify_mistake、rules_loader、before_tool hook 接入）属于 Charles 的设计选择，不构成对齐缺口。

---

## 8. 文件清单

**Cline 源文件（已读）**
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\safety\loop-detection.ts`
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\safety\mistake-tracker.ts`
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\safety\rules.ts`
- `e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\runtime\orchestration\session-runtime-orchestrator.ts`（L1070-1310）

**Charles 源文件（已读）**
- `e:\jikeAI\code\CASE-AI量化系统\agent\loop_detection.py`
- `e:\jikeAI\code\CASE-AI量化系统\agent\mistake_tracker.py`
- `e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py`
- `e:\jikeAI\code\CASE-AI量化系统\agent\runtime.py`（L265-270、L394-395、L547-548、L1277-1423）

**报告输出**
- `e:\jikeAI\code\CASE-AI量化系统\CLINE_DIFF_V2\phase_7.15_loop_detection.md`（本文件）
