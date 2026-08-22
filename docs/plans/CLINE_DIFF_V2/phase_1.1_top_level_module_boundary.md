# Phase 1.1 顶层模块边界对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在 Agent 引擎顶层模块边界上的差异。Charles 已将 Cline 的核心语义（消息片段、工具协议、运行时快照、Hook 回调、事件类型）在 `agent/types.py` / `agent/runtime.py` / `agent/hooks.py` / `agent/events.py` 中对齐到函数级，但采用了单层扁平包结构，未按 Cline 的 `shared/agents/core/apps` 四层严格分层。工具注册、技能发现、模型提供方转换分别集中在 `agent/tools/__init__.py`、`agent/skills/`、`agent/providers/base.py`，与 Cline 的 `core/extensions/tools` / `core/extensions/config/user-instruction-plugin.ts` 在职责上近似，但缺少 Marketplace/Plugin 沙箱等扩展机制。代码中仍存在多处 `nanobot` 命名残留，主要出现在注释与对标说明中，未在 `agent/runtime.py`、`agent/types.py`、`agent/tools/base.py` 三个重点文件中发现残留。

## 2. 逐项对比表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 1.1.1 | shared 层（类型+协议） | `sdk/packages/shared/src/agent.ts` 等 | `agent/types.py` | Cline 为独立 npm 包；Charles 为单文件，无包边界隔离 | 弱对齐 |
| 1.1.2 | agents 层（stateless loop） | `sdk/packages/agents/src/agent-runtime.ts` | `agent/runtime.py::AgentRuntime` | Cline 将 stateless loop 独立为 `@cline/agents`；Charles 未拆分，stateful/stateless 混合在同一类 | 弱对齐 |
| 1.1.3 | core 层（stateful 编排） | `sdk/packages/core/src/runtime/`、`extensions/`、`services/`、`hooks/` | `agent/runtime.py` + `agent/server.py` | Cline core 独立成包；Charles 用 `server.py` 承载 HTTP 宿主与部分编排职责 | 弱对齐 |
| 1.1.4 | apps 层（宿主） | `apps/vscode/`、`apps/cli/`、`apps/cline-hub/` | `agent/server.py`（FastAPI/SSE） | Cline 多宿主；Charles 单一 FastAPI 宿主 | 缺失 |
| 1.1.5 | extensions 目录 | `sdk/packages/core/src/extensions/tools/`、`extensions/config/` | `agent/tools/`、`agent/skills/`、`agent/providers/` | Charles 无统一 `extensions` 命名空间，但职责分散对应 | 弱对齐 |
| 1.1.6 | 消息片段类型 | `sdk/packages/shared/src/agent.ts` L25-71 | `agent/types.py` L33-129 | 六种片段类型（text/reasoning/image/file/tool-call/tool-result）字段基本对齐；Charles 额外有 `truncated`/`truncate_reason`/`alt_text` 等截断标记 | 弱对齐 |
| 1.1.7 | 工具协议（AgentTool） | `sdk/packages/shared/src/agent.ts` L177-186 | `agent/types.py` L215-245 / `agent/tools/base.py` | `execute`/`to_definition`/`timeout_ms`/`retryable`/`max_retries` 对齐；Charles `BaseTool` 额外引入 `read_only`/`requires_approval` | 弱对齐 |
| 1.1.8 | 工具定义入口 | `sdk/packages/core/src/extensions/tools/definitions.ts` | `agent/tools/__init__.py::create_default_tools` | Cline 工具工厂分散在 `definitions.ts`；Charles 集中注册，功能集合相近 | 弱对齐 |
| 1.1.9 | 技能入口 | `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | `agent/skills/loader.py` + `agent/skills/registry.py` | 都支持 SKILL.md frontmatter、白名单、disabled 过滤、always skills；Charles 的 `SkillRegistry`/`SkillLoader` 与 Cline `UserInstructionConfigWatcher`/`createUserInstructionSkillsExecutor` 职责等价 | 弱对齐 |
| 1.1.10 | 运行时状态快照 | `sdk/packages/shared/src/agent.ts` L128-140 | `agent/types.py`（AgentRuntimeStateSnapshot）+ `agent/runtime.py::_RuntimeState` | 字段基本对齐（agent_id/status/iteration/messages/pending_tool_calls/usage/last_error 等） | 弱对齐 |
| 1.1.11 | 事件系统 | `sdk/packages/shared/src/agent.ts` L466-550 | `agent/events.py` | Cline 为 13 种事件类型的 discriminated union；Charles 为单一 `AgentEvent` 数据类，额外补充了压缩相关事件（compaction-*） | 弱对齐 |
| 1.1.12 | Hook 系统 | `sdk/packages/shared/src/agent.ts` L336-364 | `agent/hooks.py` | 9 个核心钩子点对齐；Charles 额外扩展了 `prepare_turn_input` / `format_user_input_block` / `before_approval` 三个钩子 | 弱对齐 |
| 1.1.13 | 模型适配器 | `sdk/packages/llms/`、`sdk/packages/shared/src/agent.ts` L259-263 | `agent/providers/base.py`、`agent/providers/qwen.py` | Cline 通过 `@cline/llms` gateway 统一多 provider；Charles 以 Qwen 为主、OpenAI 兼容为辅，能力降级逻辑已对齐 | 弱对齐 |
| 1.1.14 | 顶层运行时类 | `sdk/packages/agents/src/agent-runtime.ts::AgentRuntime` | `agent/runtime.py::AgentRuntime` | 类名相同，主循环结构近似；但 Cline 拆分为 stateless loop + `SessionRuntime`，Charles 为单一混合类 | 语义不等价 |
| 1.1.15 | 装配点 | `apps/cli/src/main.ts`、`apps/vscode/src/extension.ts`、`sdk/packages/core/src/ClineCore.ts` | `agent/server.py::_create_runtime()` | Cline 多宿主、多装配点；Charles 单一函数装配 | 缺失 |
| 1.1.16 | Plugin 系统 | `sdk/packages/core/src/plugin-loader.ts`、`plugin-sandbox.ts` | 无对应实现 | Charles 配置中保留 `plugins` 字段但不加载 | 缺失 |
| 1.1.17 | Marketplace | `sdk/packages/core/src/marketplace/` | 无对应实现 | Charles 完全缺失 | 缺失 |

## 3. 重点差距详细说明

### 3.1 包分层未拆分：stateless loop 与 stateful 编排混合
- **Cline**：`@cline/shared`（类型）→ `@cline/agents`（stateless loop）→ `@cline/core`（stateful 编排）→ `apps/*`（宿主），依赖方向严格向下。
- **Charles**：所有逻辑集中在 `agent/` 单层，`agent/runtime.py::AgentRuntime` 同时持有 `_state.messages`、工具注册、Hook 注册、文件 Hook 加载、文件上下文追踪、SSE 回调等 stateful 职责，又直接实现 `run()` 主循环。
- **影响**：未来若要支持多宿主（CLI、桌面端、测试夹具）或 hub 模式时，需要像 Cline 那样将 session/storage/配置 watch 等状态职责下沉到独立层，否则宿主代码会与运行时紧耦合。

### 3.2 工具系统缺少统一 extensions 命名空间与 parallel 执行
- **Cline**：工具定义位于 `core/extensions/tools/definitions.ts`，并通过 `createDefaultTools` 工厂装配；`agent-runtime.ts` 支持 `toolExecution: "sequential" | "parallel"`。
- **Charles**：`agent/tools/__init__.py::create_default_tools` 集中注册所有工具，`agent/runtime.py` 当前只实现了 sequential 执行（对比表 P2.4.1 已标记为缺失）。`BaseTool` 还引入了 `read_only` 属性作为并发安全提示，但 runtime 未使用它实现并行调度。
- **影响**：当 LLM 一次返回多个只读工具调用（如同时读多个文件）时，sequential 执行会增加延迟；parallel 执行缺失属于功能差距。

### 3.3 多宿主与装配点单一
- **Cline**：拥有 `apps/cli`、`apps/vscode`、`apps/cline-hub` 三个宿主入口，核心装配在 `ClineCore.ts` 完成。
- **Charles**：唯一装配点在 `agent/server.py::_create_runtime()`，宿主为 FastAPI/SSE。
- **影响**：Charles 当前只能作为 Web 服务运行，无法直接以 CLI 或 VS Code 插件形式嵌入；`ClineCore.ts` 中的配置监听、会话持久化、hub 发现等职责也未在 Charles 中形成独立装配层。

### 3.4 扩展机制缺失 Plugin 与 Marketplace
- **Cline**：具备 `plugin-loader`、`plugin-sandbox` 以及 Marketplace 远程安装能力。
- **Charles**：仅有 Python Hooks（9 点）与文件 Hooks（7 种），`AgentRuntimeConfig.plugins` 字段被保留但注释明确说明“当前不实现加载逻辑”。
- **影响**：Charles 无法动态加载第三方扩展或从市场安装技能/规则，扩展性受限。

## 4. nanobot 残留检查

在 `agent/tools/base.py`、`agent/runtime.py`、`agent/types.py` 三个重点文件中 **未发现** `nanobot` 字符串残留。

在其他源码中仍存在以下 `nanobot` 风格残留（注释/对标说明）：

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/tools/__init__.py` | 2 | 模块 docstring 标题包含“对标 Cline extensions/tools 和 nanobot agent/tools” | nanobot 残留 |
| `agent/skills/loader.py` | 2、29、96、167、222、392、423 | 多处 docstring/注释提到“对标 nanobot SkillsLoader / get_skill_metadata / fallback / _strip_frontmatter” | nanobot 残留 |
| `agent/skills/registry.py` | 2、20、100、184 | docstring/注释提到“对标 Cline skills registry + nanobot SkillsLoader / build_skills_summary / get_always_skills” | nanobot 残留 |
| `agent/skills/__init__.py` | 2、23 | 类似 nanobot 对标说明 | nanobot 残留 |
| `agent/skills/skill_tool.py` | 18 | 提到“这与 nanobot 的‘子 agent 隔离执行’有本质区别” | nanobot 残留 |
| `agent/tools/web_tool.py` | 2、9、10、13、28、111、165 | 多处提到 nanobot WebSearchTool 实现 | nanobot 残留 |
| `agent/tools/file_tools.py` | 2、7、12、27、115、130、165 | 多处提到 nanobot FilesystemTool | nanobot 残留 |
| `agent/tools/exec_tool.py` | 2、8、9、10、18、19、41、57、123、165、181、263 | 大量 nanobot ShellTool 对标说明 | nanobot 残留 |
| `agent/server.py` | 2、4、28 | SSE 服务端 docstring 提到 nanobot routes/chat.py | nanobot 残留 |
| `agent/session.py` | 2、22 | 会话管理提到 nanobot session_key | nanobot 残留 |
| `agent/context.py` | 275 | 注释提到“[已废弃] nanobot 风格的额外段落” | nanobot 残留 |
| `agent/providers/qwen.py` | 21、49、116、214、253、385、406 | 多处兼容/对标 nanobot openai_compat_provider | nanobot 残留 |

> 注：上述残留目前均为注释/docstring 层面的历史对标说明，未影响运行时行为；但按 Charles 统一命名规范，应逐步替换为“Charles 历史实现”或删除。

## 5. 修复建议

### P0（阻碍后续对比/集成）
1. **明确 runtime 拆分方向**：将 `AgentRuntime` 中的 stateful 职责（状态持有、Hook/工具注册、文件 Hook 加载、文件上下文追踪）与 stateless loop 职责分离，至少先通过内部模块拆分（如 `agent/runtime_core.py` / `agent/runtime_loop.py`）为后续对齐 Cline 的 `SessionRuntime` 做准备。
2. **补齐 parallel 工具执行**：在 `agent/runtime.py::_execute_tool_calls` 中基于 `BaseTool.read_only` 与 `toolExecution="parallel"` 配置实现并行执行，避免只读工具顺序阻塞。
3. **清理重点文件的 nanobot 残留**：优先清理 `agent/tools/base.py`、`agent/runtime.py`、`agent/types.py` 已确认无残留，下一步清理 `agent/tools/__init__.py`、`agent/skills/loader.py`、`agent/skills/registry.py` 的 docstring 历史对标说明。

### P1（架构债务）
4. **建立 core 层边界**：将 `agent/server.py` 中的运行时装配、配置读取、会话持久化逻辑抽取到独立的 `agent/core/` 或 `agent/runtime/` 子包，与 HTTP 路由解耦。
5. **统一 extensions 命名空间**：将 `agent/tools/`、`agent/skills/`、`agent/providers/` 的入口逻辑按 Cline `extensions/tools`、`extensions/config`、`extensions/providers` 的语义重新组织目录或至少统一接口契约。
6. **补齐 Plugin 加载占位**：若短期内不实现，应在 `AgentRuntime.__init__` 中对非空 `plugins` 列表抛出 `NotImplementedError` 或记录警告，避免用户误以为已生效。

### P2（功能增强）
7. **多宿主抽象**：参考 Cline `ClineCore.ts` 抽象出与传输无关的 `AgentRuntime` 装配函数，使 CLI/测试/桌面端可以复用同一装配逻辑，而非仅依赖 `server.py`。
8. **事件类型补全**：将 Cline 的 `assistant-message`、`tool-updated`、`tool-finished` 等事件在 `agent/events.py` 中补充完整（当前 Charles 已有 `ASSISTANT_MESSAGE`、`TOOL_UPDATED`、`TOOL_EXECUTION_FINISHED`，但字段结构需逐字段核对）。

### P3（文档/规范）
9. **批量替换 nanobot 注释**：对剩余 40+ 处 nanobot 历史对标注释，统一改为“Charles 历史实现”或直接删除，避免新成员对系统血统产生困惑。
10. **补充 ARCHITECTURE.md**：在 `agent/` 下补充顶层模块边界说明，明确 `types.py` / `runtime.py` / `server.py` / `tools/` / `skills/` / `providers/` 的职责与依赖方向。

## 6. 验证方法建议

1. **目录结构对比**：使用 `tree` 或 `ls` 输出 Cline `sdk/packages/` 与 Charles `agent/` 的目录树，确认 Charles 是否形成 `shared/agents/core/apps` 四层边界。
2. **依赖方向检查**：运行 `pydeps agent/`（或人工绘制 import 图），验证 `agent/types.py` 是否被各模块依赖、而 `agent/runtime.py` 不反向被底层模块依赖。
3. **parallel 执行验证**：构造一次 assistant 消息包含两个 `read_files` tool_call 的输入，在 Charles 中运行并记录耗时；与 Cline 的 parallel 模式对比，确认 Charles 是否顺序执行。
4. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/` 并统计行数，建立基线；后续修复后确认重点文件无残留。
5. **Hook 点数检查**：在 `agent/hooks.py` 与 Cline `agent.ts` 中列出 hook 名称，确认 9 个核心钩子点完整且新增的 3 个扩展钩子不影响兼容性。
6. **事件类型检查**：启动一次运行，打印 `agent/events.py` 发射的所有事件类型，与 Cline `AgentRuntimeEvent` union 对比，确认缺失项。

---

*报告生成时间：2026-07-28*  
*覆盖文件：AGENT_COMPARISON_PLAN_V2.md §P1.1、cline sdk packages shared/agents/core、Charles agent/{runtime,types,tools,skills,providers,events,hooks}*
