# Stage 7: P2 扩展机制完善方案

> 生成时间：2026-07-26
> 优先级：P2
> 预估工作量：1.5 周
> 依赖：stage_2（核心架构）、stage_4（budget_policy 基础设施）、stage_6（MistakeTracker 软阈值注入路径）
>
> 来源：
> - `CLINE_DIFF/phase_X_rules_frontmatter.md`（X4 / X6 / X7 / X11 / X12）
> - `CLINE_DIFF/phase_L_system_prompt.md`（L6 / L14）
> - `CLINE_DIFF/phase_M_loop_mistake.md`（M4 / M10）
> - `CLINE_DIFF/phase_K_budget_projection.md`（K6）
> - `CLINE_DIFF/phase_R_llm_provider.md`（R5 / R15）
>
> 涉及源文件：
> - 我的：`agent/rules_loader.py`、`agent/context.py`、`agent/mistake_tracker.py`、`agent/runtime.py`、`agent/budget_policy.py`、`agent/providers/base.py`、`agent/providers/factory.py`、`agent/providers/qwen.py`、`agent/providers/openai.py`、`agent/types.py`
> - Cline：`third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts`、`cline-rules.ts`、`rule-helpers.ts`、`third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts`、`third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/project.ts`、`third_party/cline/sdk/packages/core/src/services/llms/provider-defaults.ts`、`provider-settings.ts`

---

## 0. 阶段总览

| 小阶段 | 任务 | 来源 | 严重度 | 涉及文件 |
|--------|------|------|--------|----------|
| 7.1 | paths glob 引擎升级（picomatch 等价） | X4 | P1 | agent/rules_loader.py |
| 7.2 | toggles 持久化到 stateManager | X6 | P1 | agent/rules_loader.py |
| 7.3 | AGENTS.md 多位置搜索与全局合并 | L14 | P2 | agent/context.py |
| 7.4 | cline-rules 加载机制优化（热重载评估） | L6 / X12 | P2 | agent/rules_loader.py |
| 7.5 | 硬阈值 MistakeTracker abort 标记对齐 | M10 | P2 | agent/runtime.py、agent/mistake_tracker.py |
| 7.6 | MistakeTracker force_at_limit 参数 | M4 | P1 | agent/mistake_tracker.py、agent/runtime.py |
| 7.7 | Budget Projection drop_thinking_blocks action 跟踪 | K6 | P2 | agent/budget_policy.py |
| 7.8 | LLM Provider capabilities 字段 + usage 补全 | R5 / R15 | P1 | agent/providers/base.py、factory.py、qwen.py、openai.py、types.py |

依赖关系：
- 7.6 是 7.5 的前置条件（abort 标记改造依赖 `force_at_limit` 参数先到位）
- 7.7 独立可执行
- 7.8 与 7.1-7.7 解耦，可并行
- 7.1 / 7.2 / 7.3 / 7.4 互相独立，可并行

---

## 7.1 paths glob 引擎升级（X4）

### 任务背景

来源 Phase X #X4。Cline 的 `rule-conditionals.ts` 使用 `picomatch` 库（L65: `picomatch(pattern, { dot: true })`）做 glob 匹配，支持完整 glob 语义：brace expansion（`{a,b}`）、negation（`!pattern`）、extglob（`+(a)`）、`**` 跨目录、`dot: true` 显式匹配以 `.` 开头的文件/目录。

我的实现 `agent/rules_loader.py:191-231` 中 `_match_glob` 是自实现的简化正则版本，仅支持 `*`（单层）、`**`（多层）、`?`（单字符），不支持 brace expansion / negation / extglob，也不显式处理 dot 文件。当前量化场景的规则文件均未使用 `paths` 字段（见 `agent_config/rules/*.md`），实际影响有限，但若未来需要按路径过滤规则（如仅对 `live_trading/` 目录启用交易规则），复杂 glob 模式（如 `src/{lib,bin}/**/*.py` 或 `!**/*.test.ts`）将无法正确匹配。

### 目标

对齐 Cline `picomatch(pattern, { dot: true })` 的 glob 语义，引入成熟的 glob 匹配库替换自实现正则，支持 brace expansion / negation / extglob / dot 文件，保证未来复杂路径过滤的语义与 Cline 等价。

### 当前实现位置

- `agent/rules_loader.py:191-231`（`_match_glob` 函数，自实现正则转换）
- `agent/rules_loader.py:234-264`（`_evaluate_paths_conditional`，调用 `_match_glob`）
- `agent/rules_loader.py:186-188`（`_to_posix` 辅助函数）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-conditionals.ts:12`（`import picomatch from "picomatch"`）
- Cline `rule-conditionals.ts:39-72`（`evaluatePathsConditional`，调用 `picomatch(pattern, { dot: true })`）
- Cline `rule-conditionals.ts:31-33`（`toPosix`）
- Cline `rule-conditionals.ts:35-37`（`isNonEmptyStringArray`）

### 修复步骤建议

1. **引入 `wcmatch` 库作为 picomatch 的 Python 等价物**
   - 在 `agent/rules_loader.py` 顶部增加 `from wcmatch import glob as wcglob`（延迟导入更佳，放在 `_match_glob` 函数体内）
   - `wcmatch.glob` 支持 brace expansion / negation / extglob / dot 文件，与 picomatch 语义对齐
   - 在 `requirements.txt` / `pyproject.toml` 添加 `wcmatch>=8.5` 依赖
   - 若 `wcmatch` 不可用，可降级使用 `pathspec`（仅支持 gitignore 风格 glob），但 brace/expansion 能力较弱

2. **重写 `_match_glob` 函数（保留原函数签名与逻辑骨架）**
   - 在原函数顶部增加延迟导入：`from wcmatch import glob as wcglob`
   - 保留 `if not pattern: return False` 的空模式短路逻辑
   - 用 `wcglob.globmatch(candidate, pattern, flags=wcglob.GLOBSTAR | wcglob.DOTGLOB | wcglob.BRACE | wcglob.EXTGLOB | wcglob.NEGATE)` 替换原正则匹配
   - `DOTGLOB` 等价 Cline `dot: true`，让 `*` 显式匹配 `.` 开头文件
   - 失败时（如库未安装）保留原简化正则作为兜底，记一条 warning 日志后走原逻辑（不写 fallback，但保留旧路径用于过渡期，待 wcmatch 稳定后移除）

3. **更新 `_evaluate_paths_conditional` 的 candidate 路径处理**
   - 当前 `candidate_paths = [_to_posix(p) for p in context.paths if p]` 已与 Cline 一致，无需修改
   - 但需要在 `wcglob.globmatch` 中传入 `flags` 而非依赖默认行为，确保跨平台路径分隔符处理一致

4. **保留 `_to_posix` 与 `_is_non_empty_string_array` 辅助函数不变**
   - 这两个函数语义已与 Cline `toPosix` / `isNonEmptyStringArray` 完全对齐

### 验证方法

1. 单元验证：构造以下测试模式，确认匹配结果与 Cline picomatch 一致：
   - brace: `src/{lib,bin}/**/*.py` 匹配 `src/lib/a.py` / `src/bin/b/c.py`
   - negation: `!**/*.test.ts` 不匹配 `src/a.test.ts`，匹配 `src/a.ts`
   - extglob: `+(a).py` 匹配 `a.py` / `aa.py`，不匹配 `b.py`
   - dot: `*.md` 匹配 `.hidden.md`（DOTGLOB 启用）
   - `**` 跨目录：`**/*.py` 匹配 `a/b/c/d.py`
2. 集成验证：在 `agent_config/rules/test_paths.md` 写入 frontmatter `paths: ["agent_config/**"]`，调用 `load_for_session(rules_dir, paths=["agent_config/rules/a.md"])`，确认规则被激活
3. 回归验证：现有 4 个规则文件（general / plan-mode-rules / research / trading）均无 `paths` 字段，确认加载行为不变

### 注意事项

- 不能死板照搬计划，需 Read 实际代码后判断：当前 `_match_glob` 实现虽简化但量化场景未实际触发差距，引入 wcmatch 是为未来扩展做准备，不应过度改造其他逻辑
- 保留原 `_match_glob` 函数的逻辑骨架（空模式短路、pattern→regex 转换思路），在其基础上替换底层匹配引擎，不重写整个函数
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：若 wcmatch 安装失败应直接报错让用户安装，不在生产代码中做静默兜底（但保留原正则路径作为"等价语义的另一实现"是允许的，区别于"失败时降级"）
- `wcmatch` 是纯 Python 库，无 C 扩展依赖，跨平台兼容 Windows

---

## 7.2 toggles 持久化（X6）

### 任务背景

来源 Phase X #X6。Cline 的 `cline-rules.ts:7-33` 中 `refreshClineRulesToggles` 实现 global + local 两层 toggle 持久化：
- Global toggles 存于 `stateManager` 的 global settings（`globalClineRulesToggles`）
- Local toggles 存于 `stateManager` 的 workspace state（`localClineRulesToggles`）
- `rule-helpers.ts:40-104` `synchronizeRuleToggles` 扫描目录，为新文件添加默认 `toggle=true`，删除不存在文件的 toggle
- toggle key 为**绝对路径**

我的实现 `agent/rules_loader.py:420-432` 中 `toggles: dict[str, bool]` 由调用方传入（`context.py:458-468` 临时构造），无持久化、无磁盘同步，重启后丢失。`context.py:458-461` 还会用 toggle 跳过兼容层已加载的 `task_type.md`，避免重复，属于运行时临时合并。

影响：用户无法持久化禁用某个规则文件（重启后丢失），新增规则文件不会自动出现在 toggle 列表中（但默认 True 仍激活，影响可控），删除规则文件后 toggle 残留（无清理逻辑，无副作用）。

### 目标

对齐 Cline `synchronizeRuleToggles` 与 `refreshClineRulesToggles` 的持久化语义：
1. 引入 toggle 持久化存储（JSON 文件，对标 Cline stateManager 的 workspace state）
2. 实现 `synchronize_rule_toggles` 等价函数，扫描目录同步 toggle 列表（新增文件默认 True、删除文件清理 toggle）
3. toggle key 统一用相对路径（与 Cline 绝对路径不同，因量化场景无 workspace 切换需求，相对路径更便携）

### 当前实现位置

- `agent/rules_loader.py:392-432`（`load_rules_directory` 函数中 toggles 处理逻辑，L420-432）
- `agent/rules_loader.py:552-601`（`load_for_session` 入口，toggles 参数透传）
- `agent/context.py:455-469`（`SystemPromptBuilder._load_rules` 临时构造 `merged_toggles`）

### 目标源代码位置

- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts:7-33`（`refreshClineRulesToggles`，两层持久化）
- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts:40-104`（`synchronizeRuleToggles`，扫描目录同步）
- Cline `rule-helpers.ts:220`（`getRuleFilesTotalContentWithMetadata`，`if (ruleFilePath in toggles && toggles[ruleFilePath] === false)` 跳过禁用规则）

### 修复步骤建议

1. **新增 toggle 持久化模块（在 `agent/rules_loader.py` 末尾追加）**
   - 新增 `load_toggles(store_path: Path | str) -> dict[str, bool]`：从 JSON 文件读取 toggles，文件不存在时返回空 dict
   - 新增 `save_toggles(toggles: dict[str, bool], store_path: Path | str) -> None`：写入 JSON 文件（UTF-8 编码、`ensure_ascii=False`、`indent=2`）
   - 默认存储路径：`agent_config/rule_toggles.json`（与 rules/ 同级，便于用户查看与版本控制）

2. **实现 `synchronize_rule_toggles` 函数（对标 Cline `synchronizeRuleToggles`）**
   - 函数签名：`synchronize_rule_toggles(rules_dir: Path | str, store_path: Path | str | None = None) -> dict[str, bool]`
   - 逻辑：
     a. 读取现有 toggles（`load_toggles`）
     b. 扫描 `rules_dir` 下所有 `.md` 文件（`rglob("*.md")` + `_is_rule_file` 过滤），计算相对路径作为 key
     c. 为新文件（key 不在 toggles 中）添加默认 `True`
     d. 为已删除文件（key 在 toggles 中但磁盘不存在）清理 toggle
     e. 写回存储（`save_toggles`）
     f. 返回同步后的 toggles

3. **在 `load_rules_directory` 中保留原 toggle 过滤逻辑（L420-432）**
   - 不修改函数签名与现有过滤行为
   - 调用方（`load_for_session` / `SystemPromptBuilder._load_rules`）负责先调 `synchronize_rule_toggles` 同步磁盘，再把结果作为 `toggles` 参数传入

4. **在 `load_for_session` 入口增加可选 `persist_toggles` 参数**
   - 新增参数 `persist_toggles: bool = False`，默认 False 保持向后兼容
   - 当 `persist_toggles=True` 且 `toggles is None` 时，自动调用 `synchronize_rule_toggles(rules_dir)` 加载持久化 toggle
   - 当调用方显式传入 `toggles` 时，跳过自动加载（用户显式优先）

5. **在 `SystemPromptBuilder._load_rules` 中启用持久化（`agent/context.py:455-469`）**
   - 保留原 `merged_toggles = dict(self.rule_toggles or {})` 逻辑
   - 在合并前先调用 `synchronize_rule_toggles` 拿到磁盘 toggles，再用 `self.rule_toggles` 覆盖（运行时覆盖磁盘）
   - 保留 `compat_loaded` 跳过 `task_type.md` 的逻辑（L459-461）

### 验证方法

1. 持久化验证：
   - 调用 `synchronize_rule_toggles("agent_config/rules")`，确认 `agent_config/rule_toggles.json` 生成且包含全部 .md 文件
   - 修改 JSON 把某规则设为 `false`，重启 `SystemPromptBuilder.build()`，确认该规则未激活
2. 同步验证：
   - 新增 `agent_config/rules/test.md`，再调 `synchronize_rule_toggles`，确认 JSON 中出现 `test.md: true`
   - 删除 `test.md`，再调 `synchronize_rule_toggles`，确认 JSON 中 `test.md` 条目被清理
3. 兼容验证：调用 `load_for_session(persist_toggles=False)`（默认），确认行为与改造前一致（toggles=None 时全部激活）
4. 集成验证：`context.py._load_rules` 调用后，`get_activated_rules_summary` 输出的激活列表与 JSON 状态一致

### 注意事项

- 不能死板照搬计划：Cline 用绝对路径作为 key，但量化场景 `agent_config/rules/` 是固定的，相对路径更便携（项目迁移不会失效），这是合理偏离
- 保留原 `load_rules_directory` 中 L420-432 的 toggle 过滤逻辑不动，仅在调用链上游增加持久化层
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：JSON 解析失败应直接抛异常让用户感知，不静默返回空 dict
- 并发写入保护：若多线程同时调用 `save_toggles`，可考虑加文件锁（参考 `agent/file_lock.py`），但量化场景单进程为主，初期可不加

---

## 7.3 AGENTS.md 多位置搜索（L14）

### 任务背景

来源 Phase L #L14。Cline 的 `paths.ts:372-394` 中 `resolveRulesConfigSearchPaths` 返回多个搜索路径，AGENTS.md 作为 external rule 的一种走多位置扫描：
1. `{workspacePath}/AGENTS.md`（workspace 级）
2. `{HOME_DIR}/.cline/AGENTS.md`（全局级，`resolveGlobalAgentsRulesPath()`）
3. `{clineDir}/rules/`、`Documents/Rules/` 等

多文件合并：所有发现的 AGENTS.md + 其他 .md 文件都作为独立 RuleConfig 注册（`user-instruction-config-loader.ts:479-498`），`resolveRuleFallbackName` 为 AGENTS.md 生成友好名称（"Workspace AGENTS.md" / "Global AGENTS.md"）。

我的实现 `agent/context.py:409-421` 中 `_load_agents_file` 仅加载 `agents_path` 参数指定的**单个文件**，无多位置搜索、无全局 AGENTS.md、无多文件合并。AGENTS.md 与 rules 分两段注入（AGENTS.md 在第 3 段，rules 在第 8 段）。

### 目标

对齐 Cline 多位置搜索与全局 AGENTS.md 合并语义：
1. 在 `_load_agents_file` 中增加全局 AGENTS.md 路径（`~/.agent/AGENTS.md`，对标 Cline `~/.cline/AGENTS.md`）
2. 合并 workspace + global 两层 AGENTS.md 内容（global 在前，workspace 在后，对标 Cline 拼接顺序）
3. 保留当前 AGENTS.md 作为顶层指令单独加载的语义（不走 rules_loader 流程），避免破坏现有 system prompt 段落结构

### 当前实现位置

- `agent/context.py:409-421`（`SystemPromptBuilder._load_agents_file`，单文件加载）
- `agent/context.py:176-179`（`build` 方法中调用 `_load_agents_file`，注入到第 3 段）
- `agent/context.py:124`（`__init__` 中 `agents_path` 参数定义）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/shared/src/storage/paths.ts:372-394`（`resolveRulesConfigSearchPaths`，多位置搜索）
- Cline `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts:479-498`（AGENTS.md 多文件发现与合并）
- Cline `paths.ts:24`（`AGENTS_RULES_FILE_NAME = "AGENTS.md"` 常量）

### 修复步骤建议

1. **在 `_load_agents_file` 中增加全局 AGENTS.md 路径**
   - 保留原 `if not self.agents_path or not self.agents_path.exists(): return None` 的 workspace 单文件逻辑作为主路径
   - 在函数开头先检查全局路径 `~/.agent/AGENTS.md`（用 `Path.home() / ".agent" / "AGENTS.md"`）
   - 全局路径存在时读取内容并加入 `parts: list[str]`
   - workspace 路径存在时读取内容并追加到 `parts`
   - 两层都不存在时返回 None（保留原行为）

2. **合并格式：用 `\n\n` 拼接（对标 Cline 多文件合并）**
   - global 内容在前，workspace 内容在后
   - 拼接分隔符 `"\n\n"` 与 Cline `mergeSystemPromptRules` 一致
   - 不添加额外标题（如 `# Global AGENTS.md`），保持原文注入，避免破坏 AGENTS.md 内部 markdown 结构

3. **保留原 workspace AGENTS.md 加载逻辑**
   - 不修改 `__init__` 中 `agents_path` 参数语义
   - 不修改 `build` 方法中第 3 段注入位置
   - 仅在 `_load_agents_file` 函数体内扩展全局路径合并

4. **可选：增加日志记录合并来源**
   - 在合并后 `logger.debug` 记录加载了哪些 AGENTS.md 文件（global / workspace），便于调试
   - 不影响功能，仅观测用

### 验证方法

1. 全局 AGENTS.md 验证：
   - 创建 `~/.agent/AGENTS.md`，写入 `# Global Agent Rules`
   - 调用 `SystemPromptBuilder.build()`，确认 system prompt 第 3 段含 `# Global Agent Rules`
2. 双层合并验证：
   - 同时存在 `~/.agent/AGENTS.md`（Global）和 `agent_config/AGENTS.md`（workspace）
   - 调用 `build()`，确认第 3 段先含 Global 内容后含 workspace 内容，且以 `\n\n` 分隔
3. 单层回退验证：
   - 删除 `~/.agent/AGENTS.md`，仅保留 workspace，确认行为与改造前一致
   - 删除 workspace AGENTS.md，仅保留全局，确认仍能加载全局内容
4. 双层都不存在验证：删除两个文件，确认 `_load_agents_file` 返回 None，第 3 段不注入

### 注意事项

- 不能死板照搬：Cline 把 AGENTS.md 作为 external-rules 走 rules_loader 流程，我把 AGENTS.md 作为顶层指令单独加载，两种定位都合理，应保留我的"顶层指令"语义
- 保留原 `_load_agents_file` 函数签名与返回类型（`str | None`），仅在函数体内扩展
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：全局 AGENTS.md 不存在时不报错，跳过即可
- 路径选择 `~/.agent/AGENTS.md`（而非 Cline 的 `~/.cline/AGENTS.md`），与本项目命名空间对齐

---

## 7.4 cline-rules 加载机制优化（L6）

### 任务背景

来源 Phase L #L6 与 Phase X #X12。Cline 的 rules 加载通过 extension 机制注册（`user-instruction-plugin.ts:237-243` 调用 `api.registerRule(...)`），`session-runtime-orchestrator.ts:680-688` `composeSystemPrompt` 遍历 `getRegisteredRules()` 拼接内容。数据源是 `UserInstructionConfigWatcher`（基于 `UnifiedConfigFileWatcher`，`unified-config-file-watcher.ts:94-189`），支持 fs.watch + 75ms debounce 热重载，事件驱动增量更新。

我的实现 `agent/rules_loader.py:392-416` 中 `load_rules_directory` 每次 build 时同步扫描 `rules_path.rglob("*.md")`，按文件名字典序排序加载，无 watcher、无缓存、无增量更新。`SystemPromptBuilder.build()` 每次调用都全量重读所有规则文件。

**语义不等价标注**：
- Cline: 事件驱动 + 增量更新（仅变更文件重新解析），适合长驻进程（VS Code 扩展）
- 我: 每次 build 全量重读（无缓存），适合短请求周期（Web 服务每次请求重建 system prompt）
- 两种模式都能保证"最新数据"，但性能特征不同

### 目标

评估并适度对齐 Cline 加载机制，但**不引入 watcher**（Web 服务场景不必要）：
1. 引入 mtime 缓存，避免无变更文件的重复 I/O 与解析（对标 Cline 增量更新的性能特征）
2. 保留同步扫描模式，不引入 fs.watch（量化场景规则文件不频繁变更，每次 build 重读语义已等价热重载）
3. 在加载入口增加 `excluded_subdirs` 参数，对标 Cline `cline-rules.ts:22-27` 排除 `workflows/`、`hooks/`、`skills/` 子目录

### 当前实现位置

- `agent/rules_loader.py:392-416`（`load_rules_directory` 函数，递归扫描 + 文件名排序）
- `agent/rules_loader.py:387-389`（`_is_rule_file` 辅助函数，仅判断 .md 后缀）
- `agent/rules_loader.py:499-527`（`format_rules_content` 格式化函数）
- `agent/context.py:423-477`（`SystemPromptBuilder._load_rules` 调用 `load_for_session`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts:94-189`（`UnifiedConfigFileWatcher`，fs.watch + 75ms debounce）
- Cline `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts:22-27`（排除 `workflows/` / `hooks/` / `skills/` 子目录）
- Cline `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts:680-688`（`composeSystemPrompt` 遍历 registered rules）

### 修复步骤建议

1. **在 `load_rules_directory` 增加 `excluded_subdirs` 参数**
   - 函数签名扩展：`def load_rules_directory(rules_dir, context=None, toggles=None, excluded_subdirs: list[str] | None = None)`
   - 默认值 `None` 保持向后兼容
   - 在 L416 的 `rglob("*.md")` 后增加过滤：跳过任何 `part` 在 `excluded_subdirs` 中的路径（用 `Path.relative_to(rules_dir).parts` 判断）
   - 推荐默认排除列表：`["workflows", "hooks", "skills"]`（对标 Cline L24-27），由调用方传入

2. **引入 mtime 缓存（模块级单例）**
   - 在 `agent/rules_loader.py` 顶部新增模块级缓存变量：`_RULES_MTIME_CACHE: dict[str, tuple[float, RuleLoadResult]] = {}`（key 为文件绝对路径，value 为 `(mtime, RuleLoadResult)` 元组）
   - 在 `load_rules_directory` 的文件读取循环中（L419 附近），先检查 `file_path.stat().st_mtime` 与缓存中的 mtime 是否一致
   - 一致则复用缓存的 `RuleLoadResult`（但需重新评估 `context` 与 `toggles`，因为这两项可能跨调用变化）
   - 不一致则重新读取并解析，更新缓存
   - 缓存仅缓存"文件内容 + frontmatter 解析结果"，不缓存"条件评估结果"（条件评估每次都需基于当前 context 重算）

3. **保留原文件名排序逻辑（L416）**
   - `sorted([p for p in rules_path.rglob("*.md") if _is_rule_file(p)])` 不变
   - 排序后应用 `excluded_subdirs` 过滤

4. **在 `load_for_session` 中透传 `excluded_subdirs` 参数**
   - 函数签名增加 `excluded_subdirs: list[str] | None = None`
   - 透传给 `load_rules_directory`
   - 默认值 `["workflows", "hooks", "skills"]`（若调用方未指定则用此默认，对标 Cline）

5. **在 `SystemPromptBuilder._load_rules` 中传入 `excluded_subdirs`**
   - 调用 `load_for_session(..., excluded_subdirs=["workflows", "hooks", "skills"])`
   - 保留其他参数透传逻辑不变

6. **不引入 fs.watch watcher**
   - Web 服务场景每次请求重建 system prompt，"每次 build 重读"已等价"热重载"
   - 引入 watcher 会增加进程开销与复杂度，收益有限
   - 在 docstring 中明确说明此设计选择，对标 Cline `UnifiedConfigFileWatcher` 的差异

### 验证方法

1. 排除子目录验证：
   - 在 `agent_config/rules/` 下创建 `skills/dummy.md` 与 `workflows/dummy.md`
   - 调用 `load_for_session(excluded_subdirs=["workflows", "hooks", "skills"])`，确认 `dummy.md` 未被加载
   - 调用 `load_for_session(excluded_subdirs=None)`，确认 `dummy.md` 被加载（向后兼容）
2. mtime 缓存验证：
   - 第一次调用 `load_rules_directory`，记录耗时
   - 第二次调用（文件未变更），确认耗时显著降低（缓存命中）
   - 修改某规则文件后再次调用，确认该文件被重新解析（缓存失效）
3. 语义等价验证：改造前后对同一 `rules_dir` 调用 `load_for_session`，确认 `format_rules_content` 输出一致
4. 集成验证：`SystemPromptBuilder.build()` 多次调用，确认 system prompt 中规则段内容稳定（无变更时）

### 注意事项

- 不能死板照搬 Cline watcher 架构：Cline 是长驻 VS Code 扩展进程，watcher 必要；本项目是 Web 服务请求-响应模型，每次 build 重读已满足热重载语义
- 保留原 `load_rules_directory` 函数签名向后兼容（新增参数均有默认值）
- mtime 缓存需注意跨进程失效问题：若多进程部署，每个进程独立缓存，但量化场景单进程为主，可接受
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：mtime 读取失败应抛异常，不静默跳过缓存

---

## 7.5 硬阈值 MistakeTracker abort 标记对齐（M10）

### 任务背景

来源 Phase M #M10。Cline 的 `mistake-tracker.ts:138-150` 中 MistakeTracker 返回 `{action: "stop", message, reason}` 后，由 `orchestrator.ts:1307` 调用 `this.activeRuntime?.abort(outcome.reason ?? outcome.message)`，设置 `status="aborted"`、`finishReason="aborted"`。任务计划文档提到的 `MistakeLimitExceeded` 异常类型在 Cline 源码中实际不存在，是文档误称。

我的实现 `agent/runtime.py:1090-1091`（`_check_repeated_tool_failures` 方法内）中，当 `outcome.action == "stop"` 时直接 `raise RuntimeError(outcome.message or "MistakeTracker 达到硬阈值上限")`，主循环 catch 后：
- `is_aborted = self._aborted` → False（未调用 `self.abort()`）
- `status = "failed"`（而非 `"aborted"`）
- 发射 `run_failed` 事件（而非 `run_finished`）

**任务描述勘误**：原任务清单写"修改 `agent/mistake_tracker.py` 改为调用 self.abort()"，但 `MistakeTracker` 类（`agent/mistake_tracker.py`）无 `abort()` 方法，`abort()` 是 `AgentRuntime` 的方法。实际改造点在 `agent/runtime.py:1090-1091`。

影响：mistake limit → `status="failed"`，前端显示"运行失败"而非"用户中止"，用户从状态无法区分"是 LLM 犯错太多被中止"还是"系统异常失败"。

### 目标

对齐 Cline abort 语义：当 MistakeTracker 返回 `action="stop"` 时，调用 `self.abort(outcome.message)` 而非抛 RuntimeError，使 `status="aborted"`、`finishReason="aborted"`，前端可区分"mistake limit 中止"与"系统失败"。

### 当前实现位置

- `agent/runtime.py:1046-1115`（`_check_repeated_tool_failures` 方法）
- `agent/runtime.py:1090-1091`（关键改造点：`raise RuntimeError(outcome.message or "MistakeTracker 达到硬阈值上限")`）
- `agent/runtime.py:1111-1115`（保留原有 Phase 26 同一工具连续失败硬阈值逻辑，本任务不修改）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts:138-150`（`record` 返回 `{action: "stop", message, reason}`）
- Cline `third_party/cline/sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts:1301-1308`（`outcome.action === "stop"` 时调用 `this.activeRuntime?.abort(outcome.reason ?? outcome.message)`）

### 修复步骤建议

1. **在 `agent/runtime.py:1090-1091` 改造 abort 路径**
   - 保留原 `if outcome.action == "stop":` 分支判断
   - 将 `raise RuntimeError(outcome.message or "MistakeTracker 达到硬阈值上限")` 改为：
     ```python
     if outcome.action == "stop":
         # 对齐 Cline orchestrator.ts:1307：调用 abort() 而非抛 RuntimeError
         # 使 status="aborted"、finishReason="aborted"
         self.abort(outcome.message or "MistakeTracker 达到硬阈值上限")
         # abort() 设置 _aborted=True 后仍需抛异常跳出当前执行路径
         raise RuntimeError(self._abort_reason)
     ```
   - `self.abort()` 方法已存在于 `AgentRuntime`（参考 `runtime.py:529` 中 `self._abort_reason` 的使用模式），负责设置 `_aborted=True` 与 `_abort_reason`

2. **保留 Phase 26 原有连续失败硬阈值逻辑（L1097-1115）**
   - 不修改 `entry = (tc.tool_name, error_text)` 与后续 `consecutive >= threshold` 判断
   - 该路径仍走 `raise RuntimeError(...)`（L1112），这是 Phase 26 设计的"同一工具同一错误连续 N 次"快速失败，与 MistakeTracker 总错误硬阈值是不同维度
   - 如需统一为 abort 路径，可在后续小阶段单独评估，本任务不动

3. **保留软阈值 guidance 注入路径（L1092-1095）**
   - `outcome.action == "continue_with_guidance"` 分支不动，仍把 `guidance` 作为 user message 注入下一轮 LLM 上下文
   - 这部分已由 Stage 6（M3 软阈值注入）对齐，本任务不重复改造

4. **在 `MistakeTracker` 类中不增加 `abort()` 方法**
   - MistakeTracker 是纯逻辑组件（无 runtime 引用），不应承担 abort 职责
   - abort 调用应在 `AgentRuntime` 层（即 `_check_repeated_tool_failures` 内），符合 Cline `orchestrator.ts` 调用 `activeRuntime.abort()` 的分层

### 验证方法

1. abort 标记验证：
   - 触发 MistakeTracker 硬阈值（连续 5 次工具失败，`max_total=5`）
   - 确认 `AgentRuntime` 的 `status` 为 `"aborted"`（而非 `"failed"`）
   - 确认 `finishReason` 为 `"aborted"`
   - 确认 `run_finished` 事件被发射（而非 `run_failed`）
2. 事件区分验证：
   - 触发 MistakeTracker 硬阈值 → 发射 `run_finished` 事件，payload 含 `reason="aborted"`
   - 触发真实异常（如 API Key 错误）→ 发射 `run_failed` 事件，payload 含 error 信息
   - 前端可基于事件类型区分两种场景
3. 软阈值路径回归验证：连续 3 次同类型错误（`max_per_type=3`），确认 `continue_with_guidance` 分支仍注入 guidance，不触发 abort
4. Phase 26 路径回归验证：同一工具同一错误连续 3 次（`threshold=3`），确认仍走 `raise RuntimeError(...)` 路径（L1112），未被本改造影响

### 注意事项

- 不能死板照搬任务描述：原描述说"修改 `agent/mistake_tracker.py`"，但 `MistakeTracker` 无 `abort()` 方法，实际改造点在 `agent/runtime.py:1090-1091`
- 保留原 `_check_repeated_tool_failures` 函数签名与 Phase 26 连续失败逻辑不动，仅改造 MistakeTracker 硬阈值分支
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`self.abort()` 调用后必须 `raise RuntimeError` 跳出执行路径，不能继续往下执行（否则会造成"abort 已触发但循环未终止"的不一致状态）
- 注意与 7.6（force_at_limit 参数）的协同：7.6 完成后，`_check_repeated_tool_failures` 中调用 `record` 时可传 `force_at_limit=True`，与本任务的 abort 路径共同形成 Cline 风格的"硬阈值 → MistakeTracker → abort"链路

---

## 7.6 MistakeTracker force_at_limit 参数（M4 后续）

### 任务背景

来源 Phase M #M4 后续。Cline 的 `mistake-tracker.ts:44-50` 中 `RecordMistakeInput` 接口含 `forceAtLimit?: boolean` 字段，L90 `const next = input.forceAtLimit && max ? max : this.consecutiveMistakes + 1` 实现：当 `forceAtLimit=true` 时跳过递增，直接把 `consecutiveMistakes` 设为 `max`，立即触发 `onLimitReached` 回调与 `action="stop"`。

Cline 的循环检测硬阈值（`orchestrator.ts:1265-1273`）**不直接 abort**，而是用 `forceAtLimit:true` 触发 MistakeTracker 立即达到 `maxConsecutiveMistakes`，再由 MistakeTracker 的 `outcome.action="stop"` 触发 `activeRuntime.abort()`。这一路径让 finishReason 一致为 `"aborted"`，并走 MistakeTracker 的 `onLimitReached` 回调。

我的实现 `agent/mistake_tracker.py:155-197` 中 `record` 方法签名仅含 `iteration / mistake_type / tool_name / details` 四个参数，无 `force_at_limit` 参数。`runtime.py:1033-1037` 中循环检测硬阈值直接返回 `BeforeToolResult(stop=True)`，由 `_prepare_tool_execution` 抛 RuntimeError，未联动 MistakeTracker。

### 目标

对齐 Cline `forceAtLimit` 语义：
1. 在 `MistakeTracker.record` 增加 `force_at_limit: bool = False` 参数
2. 当 `force_at_limit=True` 时，跳过 `_counts[mistake_type]` 递增与 `_total` 递增，直接把 `_total` 设为 `max_total`，立即触发 `action="stop"`
3. 在 `AgentRuntime._loop_detection_hook` 硬阈值分支中调用 `record(..., force_at_limit=True)`，由 MistakeTracker 决定 abort 路径（与 7.5 协同）

### 当前实现位置

- `agent/mistake_tracker.py:155-197`（`MistakeTracker.record` 方法，无 `force_at_limit` 参数）
- `agent/mistake_tracker.py:179-184`（硬阈值判断：`if self._total >= self.config.max_total`）
- `agent/runtime.py:1019-1044`（`_loop_detection_hook` 方法，硬阈值分支在 L1033-1037）
- `agent/runtime.py:1090-1091`（MistakeTracker 硬阈值 abort 路径，由 7.5 改造为 `self.abort()`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/runtime/safety/mistake-tracker.ts:44-50`（`RecordMistakeInput.forceAtLimit` 字段定义）
- Cline `mistake-tracker.ts:88-91`（`record` 方法中 `const next = input.forceAtLimit && max ? max : this.consecutiveMistakes + 1`）
- Cline `mistake-tracker.ts:112-114`（`if (!max || next < max) return { action: "continue" }`，force_at_limit 时 next=max，不进入此分支）
- Cline `orchestrator.ts:1265-1273`（循环检测硬阈值调用 `enqueueMistakeRecord({forceAtLimit: true, reason: "tool_execution_failed"})`）

### 修复步骤建议

1. **在 `MistakeTracker.record` 增加 `force_at_limit` 参数**
   - 函数签名扩展：`def record(self, iteration: int, mistake_type: str, tool_name: str, details: str, force_at_limit: bool = False) -> MistakeOutcome:`
   - 默认值 `False` 保持向后兼容
   - 在函数体开头（L173 之前）增加 force_at_limit 处理：
     ```python
     if force_at_limit:
         # 对标 Cline mistake-tracker.ts:90：
         # forceAtLimit=true 时跳过递增，直接把 _total 设为 max_total，立即触发硬阈值
         self._total = self.config.max_total
         self._counts[mistake_type] = max(
             self._counts.get(mistake_type, 0),
             self.config.max_per_type,
         )
         self._history.append(
             MistakeRecord(iteration, mistake_type, tool_name, details[:200])
         )
         return MistakeOutcome(
             action="stop",
             message=self._build_stop_message(),
         )
     ```
   - 保留原递增逻辑（L173-177）作为非 force_at_limit 路径

2. **保留原硬阈值与软阈值判断逻辑（L179-196）**
   - `if self._total >= self.config.max_total: return MistakeOutcome(action="stop", ...)` 不变
   - 软阈值 `continue_with_guidance` 分支不变
   - 仅在函数开头增加 force_at_limit 短路分支

3. **在 `runtime.py:1033-1037` 循环检测硬阈值分支联动 MistakeTracker**
   - 保留原 `if verdict.kind == "hard":` 分支判断
   - 在 `return BeforeToolResult(stop=True, reason=verdict.message)` 之前，先调用 MistakeTracker：
     ```python
     if verdict.kind == "hard":
         # 对标 Cline orchestrator.ts:1265-1273：硬阈值经 MistakeTracker force_at_limit 间接 abort
         mistake_outcome = self._mistake_tracker.record(
             iteration=self._state.iteration,
             mistake_type="exec_error",  # 循环硬阈值统一归类为执行错误
             tool_name=verdict.tool_name or "unknown",
             details=verdict.message or "loop detected",
             force_at_limit=True,
         )
         if mistake_outcome.action == "stop":
             # 由 7.5 改造后的 abort 路径处理
             self.abort(mistake_outcome.message or "Loop hard limit reached")
             raise RuntimeError(self._abort_reason)
         # 若 MistakeTracker 未返回 stop（理论上 force_at_limit 必返回 stop），回退到原逻辑
         return BeforeToolResult(stop=True, reason=verdict.message)
     ```
   - 注意：需先完成 7.5 改造（abort 路径对齐），否则此处的 `self.abort()` 调用会与 7.5 之前的 RuntimeError 路径冲突

4. **更新 `MistakeTracker.record` docstring**
   - 在 docstring 中增加 `force_at_limit` 参数说明
   - 说明语义：对标 Cline `forceAtLimit`，跳过递增直接触发硬阈值

### 验证方法

1. force_at_limit 单元验证：
   - 构造 `MistakeTracker(config=MistakeTrackerConfig(max_total=5))`
   - 调用 `record(iteration=1, mistake_type="exec_error", tool_name="t", details="d", force_at_limit=True)`
   - 确认返回 `action="stop"`，且 `_total == 5`、`_counts["exec_error"] >= 3`
   - 确认 `_history` 含 1 条记录
2. 非 force_at_limit 回归验证：
   - 调用 `record(iteration=1, mistake_type="exec_error", tool_name="t", details="d")`（默认 force_at_limit=False）
   - 确认返回 `action="continue"`，`_total == 1`，行为与改造前一致
3. 集成验证（循环硬阈值联动）：
   - 触发循环检测硬阈值（同一工具同一参数连续 5 次调用，`hard=5`）
   - 确认 `MistakeTracker.record` 被调用且 `force_at_limit=True`
   - 确认 `self.abort()` 被调用，`status="aborted"`
   - 确认 `finishReason="aborted"`（而非 `"failed"`）
4. 软阈值路径回归验证：触发循环检测软阈值（连续 3 次相同调用，`soft=3`），确认行为与改造前一致（不调 MistakeTracker，仅注入 user message）

### 注意事项

- 依赖关系：本任务依赖 7.5（abort 路径对齐）已完成，否则 `self.abort()` 调用与 RuntimeError 路径冲突
- 保留原 `record` 函数的递增与软阈值逻辑不动，仅在函数开头增加 force_at_limit 短路分支
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`force_at_limit=True` 必返回 `action="stop"`，不进入 continue 分支
- `mistake_type` 选择 `"exec_error"`：循环硬阈值本质是工具执行卡循环，归类为执行错误最贴近（Cline 用 `tool_execution_failed`，等价于我的 `exec_error`）

---

## 7.7 Budget Projection drop_thinking_blocks action 跟踪（K6）

### 任务背景

来源 Phase K #K6。Cline 的 `project.ts:301-327` 中 `dropThinkingBlocks` 函数：
- 过滤 `block.type === "thinking"` 的块
- 每删一块都向 `actions` 数组 push 一条审计记录：`{kind: "dropped_block", path: {messageIndex, blockIndex}, reason: "unsafe_to_truncate", originalSize: safeJsonSize(block), finalSize: 0}`
- 调用方在 `buildBudgetProjection` 内紧接着 `pruneEmptyMessages`（`project.ts:217-241`），移除因 thinking 全删而变成空 content 的消息

我的实现 `agent/budget_policy.py:185-211` 中 `drop_thinking_blocks`：
- 过滤 `isinstance(part, ReasoningPart)` 的块（语义等价于 Cline 的 `thinking`）
- **不记录 action**，无审计轨迹
- **不裁剪空消息**：若一条 assistant 消息只有 ReasoningPart，过滤后 content 为空但消息仍保留（注释说明"保留空内容消息以维持索引对齐"）

影响：审计缺失（无法回放"哪些块被丢弃、节省了多少 token"），空消息残留（轻微高估 token）。

### 目标

对齐 Cline `dropThinkingBlocks` + `pruneEmptyMessages` 行为：
1. 为 `drop_thinking_blocks` 增加可选 `actions` 参数，记录丢弃块的审计信息（对标 Cline `BudgetAction`）
2. 新增 `prune_empty_messages` 辅助函数（对标 Cline `pruneEmptyMessages`），在 `apply_budget_policy` 末尾按需调用
3. 保留原"保留空消息以维持索引对齐"逻辑作为可选行为（通过参数控制），默认行为对齐 Cline（裁剪空消息）

### 当前实现位置

- `agent/budget_policy.py:185-211`（`drop_thinking_blocks` 函数，无 action 跟踪、无空消息裁剪）
- `agent/budget_policy.py:214-240`（`apply_budget_policy` 函数，调用 `drop_thinking_blocks`）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/extensions/context/budget-projection/project.ts:301-327`（`dropThinkingBlocks` 含 action 记录）
- Cline `project.ts:217-241`（`pruneEmptyMessages` 移除空 content 消息）
- Cline `project.ts:483-672`（`buildBudgetProjection` 调用链：dropThinking → dropUnsafe → pruneEmpty → truncateText → dropClosure）

### 修复步骤建议

1. **定义 `BudgetAction` 数据类（在 `agent/budget_policy.py` 顶部增加）**
   - 新增 dataclass：`BudgetAction`，字段对标 Cline `BudgetAction`：
     ```python
     @dataclass
     class BudgetAction:
         """预算裁剪动作审计记录 — 对标 Cline BudgetAction"""
         kind: str  # "dropped_block" / "dropped_message"
         message_index: int  # 原始消息索引
         block_index: int | None = None  # 块索引（dropped_block 时有效）
         reason: str = ""  # "unsafe_to_truncate" / "over_budget" 等
         original_size: int = 0  # 原始字节大小
         final_size: int = 0  # 最终大小（dropped 时为 0）
     ```
   - 不破坏现有 import 链，仅增加新 dataclass

2. **为 `drop_thinking_blocks` 增加 `actions` 参数**
   - 函数签名扩展：`def drop_thinking_blocks(messages: list[AgentMessage], actions: list[BudgetAction] | None = None, original_indexes: list[int] | None = None) -> list[AgentMessage]:`
   - 默认值 `None` 保持向后兼容
   - 在过滤循环中，每删一个 ReasoningPart 时，若 `actions is not None`，构造 `BudgetAction` 并 append：
     ```python
     if actions is not None and original_indexes is not None:
         actions.append(BudgetAction(
             kind="dropped_block",
             message_index=original_indexes[msg_idx],
             block_index=block_idx,
             reason="unsafe_to_truncate",
             original_size=len(repr(part)),  # 近似 safeJsonSize
             final_size=0,
         ))
     ```
   - 保留原 `new_content = [p for p in message.content if not isinstance(p, ReasoningPart)]` 过滤逻辑，改为 enumerate 以获取 block_index

3. **新增 `prune_empty_messages` 函数（对标 Cline `pruneEmptyMessages`）**
   - 函数签名：`def prune_empty_messages(messages: list[AgentMessage], actions: list[BudgetAction] | None = None, original_indexes: list[int] | None = None, reason: str = "over_budget") -> tuple[list[AgentMessage], list[int]]:`
   - 逻辑：遍历 messages，跳过 `content.length == 0` 的消息，记录 `dropped_message` action
   - 返回 `(new_messages, new_original_indexes)`，保持索引映射一致性
   - 在函数 docstring 中说明：对标 Cline `pruneEmptyMessages`，移除空 content 消息

4. **在 `apply_budget_policy` 末尾调用 `prune_empty_messages`**
   - 保留原 `policy = resolve_projection_policy(intent)` 与 `drop_thinking_blocks` 调用
   - 在 `drop_thinking_blocks` 后增加 `prune_empty_messages` 调用：
     ```python
     if policy.drop_thinking_blocks:
         result = drop_thinking_blocks(result, actions=actions, original_indexes=list(range(len(result))))
         result, _ = prune_empty_messages(result, actions=actions, original_indexes=list(range(len(result))))
     ```
   - `apply_budget_policy` 函数签名增加可选 `actions: list[BudgetAction] | None = None` 参数，透传给 `drop_thinking_blocks` 与 `prune_empty_messages`

5. **保留原"保留空消息以维持索引对齐"逻辑作为可选行为**
   - 不删除原注释"保留空内容消息以维持索引对齐"
   - 通过 `prune_empty_messages` 的调用与否控制：默认调用（对齐 Cline），调用方可通过不传 `actions` 参数跳过裁剪（但 `apply_budget_policy` 默认会裁剪）
   - 在 docstring 中说明此行为变化

### 验证方法

1. action 跟踪验证：
   - 构造含 3 条 ReasoningPart 的消息列表
   - 调用 `drop_thinking_blocks(messages, actions=[])`，确认 `actions` 列表含 3 条 `dropped_block` 记录
   - 确认每条 action 的 `original_size > 0`、`final_size == 0`、`reason == "unsafe_to_truncate"`
2. 空消息裁剪验证：
   - 构造 1 条仅含 ReasoningPart 的 assistant 消息（过滤后 content 为空）
   - 调用 `apply_budget_policy(messages, intent=BudgetPolicyIntent.AGENTIC_SUMMARY)`
   - 确认返回列表中无空消息（被 `prune_empty_messages` 裁剪）
3. 索引映射验证：
   - 构造 5 条消息，索引 2 仅含 ReasoningPart
   - 调用 `apply_budget_policy`，确认返回列表长度为 4（索引 2 被裁剪）
   - 确认其他消息内容不变
4. 回归验证：现有 `ContextCompactor` 调用 `apply_budget_policy` 的路径不传 `actions` 参数，确认行为兼容（仅多了空消息裁剪，不影响功能）
5. 审计回放验证：在 `ContextCompactor` 中记录 `actions` 列表到日志，便于回放"哪些块被丢弃、节省了多少 token"

### 注意事项

- 不能死板照搬：Cline 用 `safeJsonSize(block)` 计算 original_size，我用 `len(repr(part))` 近似（Python 对象的 repr 长度），数值不精确但相对大小可用
- 保留原 `drop_thinking_blocks` 函数签名向后兼容（`actions` 与 `original_indexes` 均有默认值 None）
- `apply_budget_policy` 默认调用 `prune_empty_messages` 是行为变化，需在 docstring 中明确说明，并在 CHANGELOG 中记录
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：`actions` 为 None 时不记录审计，但裁剪行为仍执行（不因 actions 缺失而跳过裁剪）

---

## 7.8 LLM Provider capabilities 字段 + usage 补全（R5/R15）

### 任务背景

来源 Phase R #R5 与 #R15。

**R5 差距**：Cline 有三层 capabilities 体系：
1. `ProviderCapability`（`provider-settings.ts:163-176`）：`reasoning / prompt-cache / streaming / tools / vision / computer-use / oauth / popular`
2. `GatewayModelCapability`（`gateway.ts:26-33`）：`text / tools / reasoning / prompt-cache / images / audio / structured-output`
3. `toGatewayCapabilities`（`handler-factory.ts:131-159`）：将 `ModelInfo.capabilities` 映射为 `GatewayModelDefinition.capabilities`

capabilities 被用于 `GatewayStreamRequest` 路由匹配、模型清单 UI 展示、prompt-cache / reasoning 路由决策。

我的实现 `agent/providers/factory.py:38-53` 中 `ProviderDefaults` 仅有 `supports_reasoning: bool` 单字段，无 capabilities 列表，无法表达 prompt-cache / tools / vision 等能力。

**R15 差距**：Cline 的 `ApiStreamUsageChunk`（`stream.ts:56-72`）字段含 `inputTokens / outputTokens / cacheWriteTokens / cacheReadTokens / thoughtsTokenCount / totalCost / id`。`AgentTokenUsage`（`agent.ts:79-86`）含 `reasoningTokenCount?: number`。

我的实现 `agent/providers/qwen.py:258-270` 与 `openai.py:230-242` 中 `_parse_chunk` 仅解析 `input_tokens / output_tokens / cache_read_tokens` 三个字段。`AgentUsage`（`agent/types.py:271-278`）定义了 `cache_write_tokens / reasoning_token_count / total_cost` 字段，但 provider 从未填充。

### 目标

对齐 Cline capabilities 与 usage 字段：
1. 在 `ProviderDefaults` 增加 `capabilities: list[str]` 字段，将 `supports_reasoning` 改为 `capabilities` 的派生属性（保持向后兼容）
2. 定义 `ProviderCapability` 枚举常量，对齐 Cline 最小能力集：`reasoning / prompt-cache / tools / images`
3. 在 `qwen.py` / `openai.py` 的 `_parse_chunk` usage 分支中补全 `cache_write_tokens` 与 `reasoning_token_count` 字段解析
4. 在 `AgentUsage` 类型上确认字段定义完整（已定义但未填充 → 改为已填充）

### 当前实现位置

- `agent/providers/factory.py:38-53`（`ProviderDefaults` dataclass，仅 `supports_reasoning: bool`）
- `agent/providers/factory.py:57-107`（`BUILTIN_PROVIDER_DEFAULTS` 字典，7 个 provider 配置）
- `agent/providers/factory.py:165-168`（`create_model` 中 `supports_reasoning` 选项处理）
- `agent/providers/qwen.py:258-270`（`_parse_chunk` usage 分支，仅 3 字段）
- `agent/providers/openai.py:230-242`（`_parse_chunk` usage 分支，仅 3 字段）
- `agent/providers/base.py:142-148`（`_FINISH_REASON_MAP`，不修改）
- `agent/types.py:271-278`（`AgentUsage` 类型定义，已含完整字段）

### 目标源代码位置

- Cline `third_party/cline/sdk/packages/core/src/services/llms/provider-settings.ts:163-176`（`ProviderCapability` 枚举：reasoning / prompt-cache / streaming / tools / vision / computer-use / oauth / popular）
- Cline `third_party/cline/sdk/packages/core/src/services/llms/provider-defaults.ts:15-25`（`BuiltInProviderManifest` 含 `capabilities` 字段）
- Cline `third_party/cline/sdk/packages/core/src/services/llms/provider-defaults.ts:99-114`（`toRuntimeCapabilities` 收敛 catalog capability 到运行时）
- Cline `third_party/cline/sdk/packages/llms/src/providers/stream.ts:56-72`（`ApiStreamUsageChunk` 含 cacheWriteTokens / thoughtsTokenCount / totalCost）
- Cline `third_party/cline/sdk/packages/core/src/services/llms/apihandler-agent-model-adapter.ts:60-73`（适配为 `AgentModelEvent.usage: Partial<AgentUsage>`，含 `reasoningTokenCount` 来自 `thoughtsTokenCount`）

### 修复步骤建议

1. **在 `agent/providers/factory.py` 定义 `ProviderCapability` 常量类**
   - 在文件顶部增加：
     ```python
     class ProviderCapability:
         """Provider 能力常量 — 对标 Cline ProviderCapability"""
         REASONING = "reasoning"          # 支持推理（reasoning_content 字段）
         PROMPT_CACHE = "prompt-cache"    # 支持 prompt cache
         STREAMING = "streaming"          # 支持流式输出
         TOOLS = "tools"                  # 支持工具调用
         IMAGES = "images"                # 支持图片输入
         VISION = "vision"                # 支持视觉理解
         STRUCTURED_OUTPUT = "structured-output"  # 支持结构化输出
     ```

2. **在 `ProviderDefaults` dataclass 增加 `capabilities` 字段**
   - 字段定义：`capabilities: list[str] = field(default_factory=list)`
   - 保留 `supports_reasoning: bool = True` 字段不动（向后兼容）
   - 在 `__post_init__` 中同步：若 `supports_reasoning=True` 且 `ProviderCapability.REASONING not in capabilities`，自动追加 `"reasoning"` 到 capabilities
   - 这样旧调用方传 `supports_reasoning=True` 仍能自动获得 `capabilities=["reasoning"]`

3. **更新 `BUILTIN_PROVIDER_DEFAULTS` 7 个 provider 的 capabilities 字段**
   - `qwen`：`["reasoning", "tools", "streaming"]`（DashScope 支持 reasoning_content 与工具调用）
   - `openai` / `openai-native`：`["reasoning", "tools", "streaming", "vision", "structured-output", "prompt-cache"]`（GPT-4o 完整能力）
   - `deepseek`：`["reasoning", "tools", "streaming"]`（DeepSeek-R1 支持 reasoning）
   - `moonshot`：`["tools", "streaming"]`（Kimi 不支持 reasoning_content）
   - `zhipu`：`["tools", "streaming"]`（GLM-4 不支持 reasoning_content）
   - `openai-compatible`：`["reasoning", "tools", "streaming"]`（保守默认，调用方可覆盖）
   - 保留各 provider 的 `supports_reasoning` 字段值不变（向后兼容）

4. **在 `create_model` 中透传 capabilities**
   - 保留 `supports_reasoning = options.pop("supports_reasoning", defaults.supports_reasoning)` 逻辑
   - 新增 `capabilities = options.pop("capabilities", list(defaults.capabilities))`
   - 透传给 `QwenModel` / `OpenAIModel`（这两个类需在 `__init__` 增加 `capabilities` 参数，存为实例属性）
   - 暴露 `self.capabilities` 供 model-tool-routing 与 runtime 决策使用

5. **在 `qwen.py` / `openai.py` 的 `_parse_chunk` usage 分支补全字段**
   - 保留原 `input_tokens / output_tokens / cache_read_tokens` 解析逻辑
   - 新增 `cache_write_tokens` 解析：
     ```python
     cache_write_tokens = _get_nested_int(
         usage_dict, ("prompt_tokens_details", "write_tokens")
     ) or _get_nested_int(
         usage_dict, ("cache_creation_input_tokens",)  # Anthropic 风格字段
     )
     ```
   - 新增 `reasoning_token_count` 解析：
     ```python
     reasoning_token_count = _get_nested_int(
         usage_dict, ("completion_tokens_details", "reasoning_tokens")
     )
     ```
   - 新增 `total_cost = 0.0` 占位（无定价表，暂不计算）
   - 更新 `yield AgentModelEvent(type="usage", usage={...})` 包含全部 6 字段

6. **在 `QwenModel` / `OpenAIModel` 的 `__init__` 增加 `capabilities` 参数**
   - 函数签名扩展：`def __init__(self, ..., capabilities: list[str] | None = None):`
   - 默认值 `None` 保持向后兼容，None 时用 `["reasoning"] if supports_reasoning else []`
   - 存为 `self.capabilities = capabilities or [...]`
   - 保留原 `supports_reasoning` 参数与 `self.supports_reasoning` 实例属性不动

7. **不在 `AgentUsage` 类型上做修改（`agent/types.py:271-278`）**
   - 该类型已定义 `cache_write_tokens / reasoning_token_count / total_cost` 字段
   - 本任务仅需在 provider 中填充，类型定义无需改动

### 验证方法

1. capabilities 字段验证：
   - 调用 `get_provider_defaults("qwen")`，确认 `capabilities` 含 `["reasoning", "tools", "streaming"]`
   - 调用 `get_provider_defaults("openai")`，确认 `capabilities` 含 `["reasoning", "tools", "streaming", "vision", "structured-output", "prompt-cache"]`
   - 调用 `create_model("qwen", "qwen-plus", "sk-...")`，确认返回的 `QwenModel` 实例 `self.capabilities` 含上述列表
2. 向后兼容验证：
   - 调用 `create_model("moonshot", "moonshot-v1-8k", "sk-...", supports_reasoning=False)`，确认 `capabilities` 不含 `"reasoning"`
   - 调用 `create_model("openai-compatible", "model", "sk-...", capabilities=["tools"])`，确认显式传入覆盖默认值
3. usage 字段补全验证：
   - 调用 Qwen API（或 mock chunk），确认 `usage` 事件含 6 字段
   - `cache_write_tokens` 与 `reasoning_token_count` 在 API 不返回时为 0（不抛异常）
   - `total_cost` 暂为 0.0（无定价表）
4. 集成验证：触发一次完整 LLM 调用，确认 `AgentUsage` 在 `AgentRuntime` 中被正确累积与统计（参考 `runtime.py` 中 usage 处理逻辑）
5. 路由决策验证（若有 model-tool-routing 集成）：确认 `capabilities` 字段可被 `agent/tools/routing.py` 读取并用于路由决策

### 注意事项

- 不能死板照搬：Cline 有三层 capabilities 体系（ProviderCapability / GatewayModelCapability / catalog capability），我只引入一层 `ProviderCapability` 常量类即可，避免过度设计
- 保留 `supports_reasoning` 字段不动，通过 `__post_init__` 同步到 `capabilities`，确保旧调用方向后兼容
- `cache_write_tokens` 与 `reasoning_token_count` 在 OpenAI 兼容 API 中字段名不统一，需尝试多种字段名（`prompt_tokens_details.write_tokens` / `cache_creation_input_tokens` / `completion_tokens_details.reasoning_tokens`）
- `total_cost` 暂填 0.0，不引入定价表（长期可参考 Cline `billing.ts` 引入模型定价）
- 中文注释 UTF-8 编码，无 emoji
- 不写 fallback：字段解析失败时填 0（这是字段缺失的正常情况，不是异常），不抛错

---

## 阶段验收清单

完成本阶段后，需逐项确认：

- [ ] 7.1 paths glob 引擎升级：`_match_glob` 用 wcmatch 替换简化正则，支持 brace / negation / extglob / dot
- [ ] 7.2 toggles 持久化：`agent_config/rule_toggles.json` 持久化存储，`synchronize_rule_toggles` 同步磁盘
- [ ] 7.3 AGENTS.md 多位置搜索：`~/.agent/AGENTS.md` 与 workspace AGENTS.md 合并加载
- [ ] 7.4 cline-rules 加载机制优化：`excluded_subdirs` 参数排除 workflows/hooks/skills，mtime 缓存避免重复 I/O
- [ ] 7.5 硬阈值 MistakeTracker abort 标记：`runtime.py:1090-1091` 改为 `self.abort()` + `raise RuntimeError(self._abort_reason)`
- [ ] 7.6 MistakeTracker force_at_limit 参数：`record` 增加 `force_at_limit` 参数，循环硬阈值联动 MistakeTracker
- [ ] 7.7 Budget Projection action 跟踪：`drop_thinking_blocks` 记录 `BudgetAction`，新增 `prune_empty_messages`
- [ ] 7.8 Provider capabilities + usage 补全：`ProviderDefaults.capabilities` 字段，`_parse_chunk` usage 补全 6 字段

## 风险与回滚

- **7.1 风险**：wcmatch 库依赖引入，若环境无法安装需回退到原简化正则。回滚方式：保留原 `_match_glob` 函数体（注释掉 wcmatch 调用），恢复正则匹配
- **7.2 风险**：JSON 文件并发写入可能损坏。回滚方式：删除 `rule_toggles.json`，行为回退到内存 toggles
- **7.5 / 7.6 风险**：abort 路径与 RuntimeError 路径协同复杂，可能引入状态不一致。回滚方式：恢复 `raise RuntimeError(outcome.message)` 单一路径
- **7.7 风险**：`prune_empty_messages` 默认调用可能破坏下游消费者（依赖固定索引）。回滚方式：在 `apply_budget_policy` 增加 `prune_empty: bool = False` 参数，默认不裁剪
- **7.8 风险**：`supports_reasoning` 与 `capabilities` 双字段可能造成状态不一致。回滚方式：`__post_init__` 中强制同步，确保 `supports_reasoning == ("reasoning" in capabilities)`

---

**Stage 7 总结**：本阶段聚焦 P2 扩展机制完善，覆盖规则加载（7.1/7.2/7.3/7.4）、错误追踪（7.5/7.6）、预算裁剪（7.7）、Provider 元数据（7.8）四大模块。核心原则：
1. 基于 CLINE_DIFF 差距报告但不死板照搬，Read 实际代码后判断改造点
2. 保留原函数逻辑，在其基础上增加新参数与新分支
3. 中文 UTF-8 编码，无 emoji，不写 fallback
4. 每个小阶段独立可验证，可并行执行（除 7.6 依赖 7.5）
