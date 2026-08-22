# Pro Agent (Charles) vs Cline — Prompt 构建逻辑差异分析 V1

> 生成时间：2026-07-28
> 核对方式：直接读取双方当前源码实现，不依赖任何 plan/Stage 完成标记
> 核心关注点：system prompt / agent prompt / skill prompt / rules / metadata 的构建逻辑与风格结构差异

---

## 一、总体结论

| 维度 | Cline | Charles (Pro Agent) | 差异评级 |
|------|-------|---------------------|----------|
| 基础模板结构 | 单一字符串模板 + 6 占位符 | 单一字符串模板 + 6 占位符 | 高度相似 |
| 构建职责划分 | 分层：shared/cline.ts 构建 base → orchestrator 合并 extension rules | 集中：SystemPromptBuilder 一手包办 base + rules + metadata + enhancements | **显著差异** |
| Rules 机制 | 简单 rule 列表，extension 注册 | 复杂 frontmatter + 条件过滤 + toggle + cache | **显著差异** |
| 模式契约 | MODE_TAG + PLAN_MODE 作为 effectiveRules | MODE_TAG + PLAN_MODE 作为 effectiveRules | 高度相似 |
| Metadata 注入 | 仅 isCline provider 注入 | 无条件注入 | **差异** |
| 增强层 | 无 | tools_section / skills_summary / always_skills / mcp_section / memory | **差异** |
| 用户输入包装 | runtime 层 formatUserInputBlock | server.py 手动包装 + runtime 钩子可选增强 | **差异** |
| Skill 提示格式 | XML `<command-name>/<command-args>/<command-instructions>` | 同左 | 一致 |

**一句话总结**：双方在"base prompt + effectiveRules + metadata"的大框架上已对齐，但 Charles 在 Rules 层做了大量超出 Cline 的增强（frontmatter 条件、toggle、业务模式过滤），同时保留了 Cline 没有的 enhancement 层；Cline 更依赖 extension registry 和 provider 条件注入，结构更紧凑。

---

## 二、System Prompt 构建链路对比

### 2.1 Base Prompt 模板

#### Cline
- 文件：`sdk/packages/shared/src/prompt/system.ts`
- 结构：
  ```
  You are Cline, an AI coding agent. ...
  Remember:
  - ...
  <env>
  1. Platform: {{PLATFORM_NAME}}
  2. Date: {{CURRENT_DATE}}
  3. IDE: {{IDE_NAME}}
  4. Working Directory: {{CWD}}
  </env>
  {{CLINE_RULES}}
  {{CLINE_METADATA}}
  ```
- 身份：固定在模板首行
- 环境字段：英文，带序号

#### Charles
- 文件：`agent/prompts/charles_system_prompt.py`
- 结构：
  ```
  你是 Charles，专业的 AI 投研情报官。...
  ## 通用行为规则
  ...
  <env>
  平台: {{PLATFORM_NAME}}
  日期: {{CURRENT_DATE}}
  IDE: {{IDE_NAME}}
  工作目录: {{CWD}}
  </env>
  {{CHARLES_RULES}}
  {{CHARLES_METADATA}}
  ```
- 身份：固定在模板首行
- 环境字段：中文，无序号

**真实差异点 #L1**：
- 字段语言不同（Cline 英文 vs Charles 中文）
- 字段顺序不同（Cline Platform→Date→IDE→CWD vs Charles 平台→日期→IDE→工作目录）
- 有无序号：Cline 有 `1. 2. 3. 4.`，Charles 无
- 日期格式：Cline 用 `new Date().toLocaleDateString()`（区域相关），Charles 用 `date.today().isoformat()`（ISO 8601）

**影响**：功能等价，但模型对中英文字段名的解析习惯可能略有不同；ISO 日期更稳定。

---

### 2.2 Prompt 构建主入口

#### Cline
- 文件：`sdk/packages/shared/src/prompt/cline.ts`
- 函数：`buildClineSystemPrompt(options)`
- 职责：
  1. 选择 base prompt（DEFAULT / YOLO）
  2. 替换 4 个 `<env>` 占位符
  3. 组装 `effectiveRules = [rules, MODE_TAG_INSTRUCTIONS, plan_mode_if_needed]`
  4. 替换 `{{CLINE_RULES}}`
  5. 仅在 `isClineProvider(providerId)` 时注入 metadata
- 特点：
  - 不加载 rules，rules 由调用方传入
  - 不加载 skills，skills 通过 tools 字段暴露
  - 不认识 AGENTS.md

#### Charles
- 文件：`agent/context.py`
- 类：`SystemPromptBuilder`
- 方法：`build(task_type)`
- 职责：
  1. 读取 `DEFAULT_CHARLES_SYSTEM_PROMPT`
  2. 替换 4 个 `<env>` 占位符
  3. 调用 `_build_rules(task_type)`：
     - 加载全局 `~/.agent/AGENTS.md`
     - 加载 workspace `AGENTS.md`
     - 扫描 `rules_dir` 下所有 .md 文件
     - 注入 MODE_TAG_INSTRUCTIONS
     - 注入 PLAN_MODE_PROMPT（仅 plan 模式）
     - 注入 enhancements（若开启）
     - 注入 extra_sections
  4. 替换 `{{CHARLES_RULES}}`
  5. 调用 `_build_metadata()` 并替换 `{{CHARLES_METADATA}}`
- 特点：
  - 一手包办所有规则加载
  - 支持 AGENTS.md 作为 rule
  - 支持可开关的 enhancement 层

**真实差异点 #L2（架构差异）**：
- Cline 的 prompt 构建是"函数式 + 外部输入"：buildClineSystemPrompt 只负责组装，rules/metadata 由 orchestrator 提供
- Charles 的 prompt 构建是"面向对象 + 自给自足"：SystemPromptBuilder 内部读取文件、加载 rules、查询 mode、构建 metadata
- 这与 SUMMARY_v4 中 P3 差距 A1 描述一致："SystemPromptBuilder 职责未分离"

---

### 2.3 Rules 层

#### Cline
- 文件：
  - `sdk/packages/core/src/runtime/safety/rules.ts`（格式化）
  - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`（注册）
- 加载流程：
  1. `user-instruction-plugin.ts` 注册 rule：`api.registerRule({ id: "cline-user-instructions:rules", content: () => loadRulesForSystemPromptFromWatcher(options.watcher) })`
  2. `session-runtime-orchestrator.ts::composeSystemPrompt()` 调用 `resolveRuleContent(rule)` 收集所有 registered rules
  3. `mergeSystemPromptRules(systemPrompt, rules)` 将 rules 拼接到 system prompt 末尾
- 格式：
  ```
  # Rules
  ## rule_name
  rule_instructions
  ```
- 条件过滤：在 `user-instruction-config-loader.ts` 中按 frontmatter 的 `applyTo` / `paths` / `disabled` 过滤（本次未深入读取，但 `rules.ts` 本身只做格式化）

#### Charles
- 文件：`agent/rules_loader.py`
- 加载流程：
  1. `SystemPromptBuilder._build_rules()` 直接调用 `load_rules_directory()`
  2. `load_rules_directory()` 递归扫描 `rules_dir/*.md`
  3. `_read_with_mtime_cache()` 读取并缓存 frontmatter 解析结果
  4. `evaluate_rule_conditionals()` 按 `applyTo` / `mode` / `paths` / `enabled` / `toggles` 过滤
  5. `format_rules_content()` 输出 `# Rules` + `## name` + body
- 格式：与 Cline 相同 `# Rules` + `## name` + body
- 额外能力：
  - `mode` 字段：支持业务 modes（如 research/trade）
  - `toggles`：文件级开关，支持 global/local 持久化
  - `mtime cache`：减少重复 I/O

**真实差异点 #L3**：
- Cline 的 rule 过滤逻辑在 config loader/watcher 层，rules.ts 只做字符串拼接
- Charles 的 rule 过滤、toggle、cache 全部集中在 `rules_loader.py`
- Charles 支持 `mode` 业务过滤，Cline 没有对应概念
- Charles 的 rule name 用文件 stem，Cline 用 `rule.name`（来自 watcher）

**真实差异点 #L4**：
- Charles 有 `synchronize_rule_toggles` / `load_merged_toggles` / `load_local_toggles` 完整 toggle 持久化机制
- Cline 的 toggle 状态由 watcher/VSCode state 管理，rules.ts 不处理

---

### 2.4 MODE_TAG_INSTRUCTIONS（模式标签说明）

#### Cline
- 文件：`sdk/packages/shared/src/prompt/cline.ts` L21-23
- 内容要点：
  - `plan` = explore/analyze/align，no edits / state-changing commands
  - `act` or `yolo` = implementation allowed
  - newest message's mode governs right now
  - `<mode_notice>` marks mode switch

#### Charles
- 文件：`agent/context.py` L661-678 `_build_mode_tag_instructions()`
- 内容要点：
  - 解释 act / plan / yolo 三种模式
  - plan 模式下不得调用 editor/apply_patch/file_write/write-report
  - 以最新消息 mode 为准
  - 提到 `<mode_notice>`

**真实差异点 #L5**：
- Cline 的说明更精确："plan-mode constraints applied (explore, analyze, and align on a plan -- no edits or state-changing commands)"
- Charles 的说明额外限制了具体工具名，但限制工具主要靠 `tool_policies`，这里存在语义重复
- Cline 明确区分 `act` 和 `yolo`，Charles 将 yolo 描述为"与 act 等价但无需逐步确认"，与 Cline 一致

---

### 2.5 PLAN_MODE_PROMPT（Plan 模式契约）

#### Cline
- 文件：`sdk/packages/shared/src/prompt/cline.ts` L32-45
- 核心约束：
  - read files / search / gather context
  - ask clarifying questions
  - present structured outline
  - explain tradeoffs
  - **Do NOT edit files, write code, run destructive commands, or make any changes**
  - run_commands 仅用于 read-only inspection
  - 切换用 `switch_to_act_mode` tool

#### Charles
- 文件：`agent/tools/plan_mode.py` L38-54
- 核心约束：
  - 探索、分析、给出计划
  - 使用 todo_write 拆解
  - 不直接实现或输出最终产物
  - editor/apply_patch/file_write/write-report 由 tool_policies 硬禁用
  - 切换用 `switch_to_act_mode` tool

**真实差异点 #L6**：
- Cline 明确允许 run_commands 用于只读检查（listing files, grep, git history, tool versions）
- Charles 直接说"run_commands（只读命令）"，范围描述较宽泛
- Cline 强调"Do NOT implement anything"，Charles 强调"不直接实现或输出最终产物"，语义一致
- Charles 额外要求 todo_write 拆解任务，这是量化场景的合理增强

---

### 2.6 Metadata 层

#### Cline
- 文件：`sdk/packages/shared/src/prompt/cline.ts` L64-86
- 函数：`buildWorkspaceMetadata(rootPath, workspaceName, metadata)`
- 关键逻辑：
  - 使用 `WORKSPACE_CONFIGURATION_MARKER = "# Workspace Configuration"`
  - 仅在 `isClineProvider(providerId)` 时注入
  - 若传入 `metadata` 且包含 marker，则直接使用
  - 否则生成 `{"workspaces": {rootPath: {hint: ...}}}` JSON

#### Charles
- 文件：`agent/context.py` L237-277 `_build_metadata()`
- 关键逻辑：
  - 使用 `<charles_metadata>` XML 标签包裹
  - **无条件注入**（无 provider 判断）
  - 生成 `{"workspaces": {working_dir: {hint, latestGitCommitHash, latestGitBranchName, associatedRemoteUrls}}}` JSON

**真实差异点 #L7**：
- Cline metadata 是 provider 条件注入，非 Cline provider 不注入
- Charles 始终注入 metadata
- Cline 使用 `# Workspace Configuration\n{...}` 文本块
- Charles 使用 `<charles_metadata>\n{...}\n</charles_metadata>` 标签
- Charles 主动查询 git branch/commit/remote，Cline 的 `buildWorkspaceMetadata` 仅使用传入的 `metadata` 参数

---

## 三、Agent Prompt / 用户输入层对比

### 3.1 用户输入包装

#### Cline
- 文件：`sdk/packages/shared/src/prompt/format.ts`
- 函数：`formatUserInputBlock(input, mode)`
- 行为：`return '<user_input mode="${mode}">${input}</user_input>'`
- 调用位置：runtime 层 `prepareTurnInput`

#### Charles
- 文件：`agent/server.py` L592-596
- 行为：`wrapped_message = f'<user_input mode="{current_mode}">\n{message}\n</user_input>'`
- 调用位置：**server.py 在调用 runtime 之前**手动包装
- runtime 层（`agent/runtime.py` L614-617）有 `format_user_input_block` 钩子，但默认无实现，不主动包装

**真实差异点 #A1**：
- Cline 的用户输入包装在 runtime 内部完成，是标准行为
- Charles 的用户输入包装在 server.py 完成，runtime 本身不保证包装
- 如果未来有其他入口调用 runtime.run() 而不经过 server.py，用户输入可能不会被 `<user_input>` 包裹

---

### 3.2 Mode Switch Notice

#### Cline
- 文件：`sdk/packages/shared/src/prompt/format.ts`
- 函数：`formatModeSwitchNotice(from, to)` 返回 `<mode_notice>The user switched from ${from} mode to ${to} mode before sending this message.</mode_notice>`
- 状态：`createModeSwitchNoticeTracker()` 追踪待生效的 mode switch

#### Charles
- 文件：未在读取范围内找到 `formatModeSwitchNotice` 等价实现
- `agent/state.py` 有 `set_mode` 变更状态，但未见在 user message 前 prepend `<mode_notice>` 的逻辑

**真实差异点 #A2**：
- Charles 缺少 Cline 的 `<mode_notice>` 机制
- 这会导致 mode 切换时刻在对话中没有被明确标记，模型可能无法感知切换发生的精确位置

---

## 四、Skill Prompt 层对比

### 4.1 Skill 工具 XML 格式

#### Cline
- 文件：`sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L174-217
- 返回格式：
  ```xml
  <command-name>{skill.name}</command-name>
  <command-args>{args}</command-args>
  <command-instructions>
  Description: {description}
  {skill.instructions}
  </command-instructions>
  ```

#### Charles
- 文件：`agent/skills/skill_tool.py` L182-194
- 返回格式：
  ```xml
  <command-name>{skill_name}</command-name>
  <command-args>{args}</command-args>
  <command-instructions>
  Description: {description}
  {instructions}
  </command-instructions>
  ```

**结论**：XML 结构基本一致。

---

### 4.2 Skill 去重 key

#### Cline
- 使用 `normalizeSkillToken(name)` = `trim().replace(/^\/+/, "").toLowerCase()`
- `runningSkills` key 是规范化后的 id

#### Charles
- 文件：`agent/skills/skill_tool.py` L163
- 使用 `_normalize_skill_token(skill_name)`，与 Cline 等价

**结论**：已对齐（Stage 3.6 修复后）。

---

### 4.3 Skill 白名单匹配

#### Cline
- 文件：`sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L51-73
- 检查 4 种形式：normalizedId / normalizedName / bareId / bareName

#### Charles
- 文件：`agent/skills/registry.py` L57-79
- 检查 2 种形式：normalized / bare（去 `:` namespace 前缀）
- 注释说明：当前无 namespaced skill，故简化为 2 形式

**真实差异点 #S1**：
- Cline 同时检查 id 和 name 的 4 种形式
- Charles 只检查 name 的 2 种形式
- 当前系统无 namespaced skill，差异未暴露，但未来引入 plugin skill 时可能不匹配

---

### 4.4 Skill 超时配置

#### Cline
- 文件：`sdk/packages/core/src/extensions/tools/definitions.ts` L719-723
- `const timeoutMs = config.skillsTimeoutMs ?? 15000`（可配置）

#### Charles
- 文件：`agent/skills/skill_tool.py` L94-101
- 硬编码 `return 15000`

**真实差异点 #S2**：
- Cline 支持通过 `config.skillsTimeoutMs` 覆盖默认值
- Charles 不可配置

---

### 4.5 Skill 在 System Prompt 中的呈现

#### Cline
- 不在 system prompt 中列出技能
- 技能列表通过 `skills` 工具的 `description` 动态 getter 暴露：
  ```
  baseDescription + " Available skills: " + names.join(", ") + "."
  ```

#### Charles
- 默认也不注入 system prompt
- 但开启 `enhancements.skills_summary` 后，会注入 `## charles-skills-summary` rule，含完整 markdown 表格
- 同时支持 `enhancements.always_skills` 自动注入 always=True 技能指令

**真实差异点 #S3**：
- Cline 没有 "always skills" 概念，也没有 "skills summary" rule
- Charles 的 enhancement 层是额外能力，非 Cline 等价物

---

## 五、Enhancement 层对比

### 5.1 Cline
- 无 enhancement 配置概念
- 工具描述通过 model API tools 字段完整传递
- MCP 工具作为普通 AgentTool 注册，不注入 system prompt 概览

### 5.2 Charles
- 文件：`agent_config/system_prompt.yaml`
- 开关：
  - `enabled: false`（总开关，默认关闭）
  - `tools_section: true`
  - `skills_summary: true`
  - `always_skills: true`
  - `mcp_section: true`
  - `memory: true`
- 实现：`agent/context.py` L436-472 `_build_enhancement_rules()`

**真实差异点 #E1**：
- 这是 Charles 独有的增强层，Cline 没有对应物
- 关闭 enhancements 时与 Cline 完全对齐
- 开启时 system prompt 会显著变长，可能影响模型上下文

---

## 六、风格与结构差异

### 6.1 语言与文化差异

| 项目 | Cline | Charles |
|------|-------|---------|
| 身份 | "You are Cline, an AI coding agent" | "你是 Charles，专业的 AI 投研情报官" |
| 场景 | 通用编码 | 中文量化投研 |
| 环境字段 | Platform/Date/IDE/Working Directory | 平台/日期/IDE/工作目录 |
| 规则语言 | 英文 | 中文（因为用户 rules 也是中文） |
| 工具名 | read_files / editor / run_commands | 相同 |

### 6.2 紧凑度差异

- Cline base prompt：约 30 行，高度紧凑
- Charles base prompt：约 50 行，更详细的通用行为规则
- Charles enhancements 开启后可能再增加数百行

### 6.3 扩展性差异

- Cline：新增 rule 通过 extension registry 注册，host 侧无感知
- Charles：新增 rule 直接放 `agent_config/rules/*.md`，由 SystemPromptBuilder 自动扫描
- Cline 的扩展机制更插件化；Charles 的文件驱动方式更适合当前量化场景

---

## 七、真实缺陷 / 不同点清单（按优先级）

| # | 差异点 | 严重度 | 说明 | 位置 |
|---|--------|--------|------|------|
| 1 | `<mode_notice>` 机制缺失 | P2 | mode 切换时没有显式标记，模型可能感知不到切换时刻 | Charles 未实现 |
| 2 | 用户输入包装在 server.py 而非 runtime | P2 | 非 server 入口调用 runtime 时可能缺失 `<user_input>` 标签 | `agent/server.py` L592-596 |
| 3 | Metadata 无条件注入 | P3 | Cline 仅 isCline provider 注入；Charles 始终注入 | `agent/context.py` L232 |
| 4 | Metadata 标签格式不同 | P3 | Cline 用 `# Workspace Configuration`，Charles 用 `<charles_metadata>` | `agent/context.py` L273-276 |
| 5 | SystemPromptBuilder 职责未分离 | P3 | 一手包办所有规则/技能/metadata 加载 | `agent/context.py` L200-235 |
| 6 | skillsTimeoutMs 不可配置 | P3 | 硬编码 15000ms | `agent/skills/skill_tool.py` L94-101 |
| 7 | Skill 白名单只检查 name 2 形式 | P3 | 未覆盖 id vs name 4 形式匹配 | `agent/skills/registry.py` L57-79 |
| 8 | `<env>` 字段中文+无序号 | P3 | 与 Cline 英文有序号不同 | `agent/prompts/charles_system_prompt.py` L44-49 |
| 9 | Enhancement 层为 Charles 独有 | P3 | Cline 无对应概念，开启后不对齐 | `agent_config/system_prompt.yaml` |
| 10 | PLAN_MODE_PROMPT 对 run_commands 只读范围描述较宽泛 | P3 | Cline 明确列举允许的只读命令 | `agent/tools/plan_mode.py` L44 |
| 11 | Rule name 使用文件 stem | P3 | Cline 使用 watcher 提供的 rule.name | `agent/rules_loader.py` L716 |
| 12 | Charles 无 `yolo` base prompt 变体 | P3 | Cline 有 `YOLO_CLINE_SYSTEM_PROMPT` | `third_party/cline/sdk/packages/shared/src/prompt/system.ts` L38-68 |
| 13 | Charles 的 MODE_TAG 说明额外限制具体工具名 | P3 | 与 tool_policies 语义重复 | `agent/context.py` L670-672 |

---

## 八、已对齐的关键点

1. **Base prompt + Rules 两层结构**：双方都是 base template + `{{RULES}}` + `{{METADATA}}`
2. **effectiveRules 顺序**：都是 `[rules, MODE_TAG, PLAN_MODE_if_plan]`
3. **`<user_input mode="...">` 包装**：双方都包装用户输入
4. **Skill XML 返回格式**：`<command-name>/<command-args>/<command-instructions>` 一致
5. **Skill runningSkills 去重**：双方都使用规范化 id 作为 key
6. **Plan 模式切换工具**：双方都提供 `switch_to_act_mode` 概念
7. **Rules 格式化输出**：双方都使用 `# Rules` + `## name` + body
8. **Metadata workspaces 嵌套结构**：双方都使用 `{"workspaces": {path: {hint, ...}}}`

---

## 九、建议下一步

1. **P2 必做**：
   - 在 runtime 层补充默认的 `<user_input>` 包装，避免 server.py 成为唯一入口
   - 实现 `<mode_notice>` 机制，标记 mode 切换时刻
2. **P3 可选**：
   - 将 `SystemPromptBuilder` 的职责拆分，rules 加载由 `rules_loader` 独立完成，builder 只负责组装
   - 支持 `skillsTimeoutMs` 配置注入
   - 完善 skill 白名单 4 形式匹配
   - 评估是否需要 `yolo` 专用 base prompt

---

*本文件基于 2026-07-28 的代码状态生成，不依赖任何 plan/Stage 标记，所有差异点均来自源码实际逻辑对比。*
