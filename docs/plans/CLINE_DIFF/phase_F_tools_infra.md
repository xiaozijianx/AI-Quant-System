# Phase F: 工具系统基础设施 对比报告

> 对标源码：`sdk/packages/shared/src/tools/create.ts` + `core/extensions/tools/runtime.ts` + `definitions.ts` + `schemas.ts`
> 当前实现：`agent/tools/base.py` + `agent/tools/routing.py` + `agent/tools/constants.py`
> 对比维度：D1-D7

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 5 项 |
| 弱对齐 | 4 项 |
| 缺失 | 3 项 |
| 额外增强 | 2 项 |
| **对齐度** | **约 65%** |

---

## 2. 详细对比表

| # | 对比项 | Cline | 我的位置 | 一致性 |
|---|--------|-------|---------|--------|
| F1 | 工具工厂模式 | `createTool()` 工厂 + zod | `BaseTool` ABC + jsonschema | 弱对齐 |
| F2 | execute 返回类型 | `Promise<TOutput>` (raw) | `AgentToolResult` (wrapped) | 弱对齐 |
| F3 | lifecycle.completesRun | definitions.ts | base.py L71 | 完全一致 |
| F4 | **lifecycle.blocking** | definitions.ts | 无 | 缺失 |
| F5 | timeoutMs per-tool | definitions.ts | base.py L76 | 完全一致 |
| F6 | retryable + maxRetries | definitions.ts | base.py L81-88 | 完全一致 |
| F7 | withTimeout 包裹 | `Promise.race` | `asyncio.wait_for` (runtime.py L1505) | 完全一致 |
| F8 | Schema 校验 | zod + `validateWithZod` | jsonschema Draft7 (base.py L212) | 完全一致 |
| F9 | ToolRegistry | `Map<string, AgentTool>` | `dict[str, AgentTool]` (runtime.py L218) | 完全一致 |
| F10 | get_definitions() | runtime.ts | runtime.py L370 | 完全一致 |
| F11 | **subprocess-sandbox** | `subprocess-sandbox.ts` | 无 | 缺失 |
| F12 | **tool presets** | `presets.ts` (read-only/full) | 无 | 缺失 |
| F13 | model-tool-routing | `model-tool-routing.ts` | routing.py (Phase 32.1) | 完全一致 |
| F14 | **output-limits 统一常量** | `output-limits.ts` | constants.py (部分) | 弱对齐 |
| F15 | read_only/concurrencySafe | Cline 无此字段 | base.py L91 `read_only` | 额外增强 |
| F16 | requires_approval | `tool-approval.ts` 外部 | base.py L96 `requires_approval` | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #F2：execute 返回类型不同

**严重度**：P2（已在 Phase A #A8 详述）

Cline `execute` 返回原始 `TOutput`，Runtime 包装为 `AgentToolResult`。
我 `execute` 返回 `AgentToolResult`，工具自己包装。

**影响**：BaseTool 基类已统一异常→is_error 转换（base.py L129-138），实际行为接近 Cline。

**修复建议**：保持现状，BaseTool 已弥补。

**优先级**：P2

---

### 差距 #F4：lifecycle.blocking 缺失

**严重度**：P3（影响 UI 阻塞标记）

**Cline**：`lifecycle.blocking` 标记工具是否阻塞 UI（如 ask_question 阻塞等待用户输入）。

**我**：无此字段。

**影响**：
- 前端无法从工具定义判断是否应阻塞 UI
- 实际通过 `requires_approval` 和工具类型隐式判断

**修复建议**：可选添加 `blocking` 字段。当前影响小。

**优先级**：P3

---

### 差距 #F11：subprocess-sandbox 缺失

**严重度**：P3（量化场景无插件需求）

**Cline**：`subprocess-sandbox.ts` 用 Node.js 子进程隔离执行工具，用于插件安全隔离。

**我**：工具直接在主进程执行。

**影响**：
- 无插件场景下无安全风险
- 量化场景暂无插件需求

**修复建议**：暂不实现。

**优先级**：P3

---

### 差距 #F12：tool presets 缺失

**严重度**：P2（影响工具集预设）

**Cline**：`presets.ts` 定义工具集预设（如 read-only / full / plan-mode），可快速切换工具集。

**我**：通过 `model-tool-routing` + `SessionState.mode` 动态过滤工具，无预设概念。

**影响**：
- 无法一键切换"只读模式"/"完整模式"
- 但 mode-based 路由已覆盖 Plan Mode 工具过滤

**修复建议**：可选实现 presets。当前 mode-based 路由够用。

**优先级**：P2

---

### 差距 #F14：output-limits 未完全统一

**严重度**：P2（影响配置一致性）

**Cline**：`output-limits.ts` 统一管理 `MAX_COMMAND_OUTPUT_CHARS` / `MAX_READ_LINES` / `MAX_SEARCH_OUTPUT_CHARS` 等常量。

**我**：`constants.py` 部分统一，部分仍散落各工具。

**修复建议**：提取所有输出限制到 `constants.py`：
```python
MAX_COMMAND_OUTPUT_CHARS = 30000
MAX_READ_LINES = 500
MAX_READ_OUTPUT_CHARS = 30000
MAX_SEARCH_OUTPUT_CHARS = 30000
MAX_TOOL_RESULT_CHARS = 16000
```

**优先级**：P2

---

## 4. 额外增强项

### 增强 #F15：read_only 属性

**我**：`base.py L91 read_only` 标记工具是否无副作用（可并行执行）。
**Cline**：无此字段，通过 `toolExecution` config 全局控制。

**评估**：合理增强，支持 per-tool 并发控制。保留。

### 增强 #F16：requires_approval 属性

**我**：`base.py L96 requires_approval` 标记工具是否需审批。
**Cline**：通过 `tool-approval.ts` + `toolPolicies` 外部配置。

**评估**：合理增强，工具自描述审批需求。保留。

---

## 5. 修复优先级清单

### P2
1. **F14 output-limits 统一**：提取所有输出限制到 constants.py
2. **F12 tool presets**：可选，mode-based 路由已覆盖
3. **F2 execute 返回类型**：保持现状，BaseTool 已弥补

### P3
1. **F4 lifecycle.blocking**：可选
2. **F11 subprocess-sandbox**：暂不实现

---

**阶段 F 结论**：工具系统对齐度约 65%，核心 timeout/retry/schema 校验完全一致。主要差距是 subprocess-sandbox（无插件需求）和 tool presets（mode 路由覆盖）。我额外增强 read_only 和 requires_approval 属性，工具自描述能力更强。
