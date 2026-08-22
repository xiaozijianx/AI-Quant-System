# Phase 4.3 SkillRegistry 对比报告

## 1. 执行摘要

本次对比聚焦 Cline（TypeScript）与 Charles（Python）在技能注册表（SkillRegistry）机制上的差异，覆盖 Registry 数据结构、`build_summary`、`_build_description`、`allowed_skill_names` 白名单过滤、`load_all`/discover、技能排序、禁用技能跳过、always 技能标记、`get_skill_metadata`、技能覆盖十个维度。

总体结论：Charles 在 SkillRegistry 核心机制上与 Cline **部分对齐**，但存在五处需要澄清的差异：

1. **计划 P4.3 描述与实际代码不符（Cline 侧）**：计划声称"Cline 有 `SkillRegistry` 类管理 SkillMetadata"和"`build_summary()` 生成技能概览"。实际 Cline **没有** `SkillRegistry` 类，也**没有** `build_summary` 方法。Cline 的"注册表"是 `UserInstructionConfigWatcher.getSnapshot("skill")` 返回的 `Map<string, UnifiedConfigRecord>`（`unified-config-file-watcher.ts` L210-218），技能概览通过 `skills` 工具的动态 `description` 暴露（`definitions.ts` L754-766 追加 "Available skills: a, b, c."）。Charles 的 `SkillRegistry` 类（`registry.py` L99-292）和 `build_summary()` 方法（L210-252）是 **Charles 额外实现**，对标的是 nanobot `SkillsLoader`，不是 Cline。
2. **`build_summary` 输出格式差异是 Charles 额外功能**：Cline 无 `build_summary`，仅在 `skills` 工具 description 末尾追加逗号分隔的技能名列表（disabled 过滤后）。Charles `build_summary()`（`registry.py` L210-252）生成完整的"技能目录"段落，每行 `- {name} ({when_to_use}): {description}`（3 列：名称/何时使用/描述），并通过 `build_summary_as_rule()`（L254-263）包装为 `## charles-skills-summary` rule 注入 system prompt（`context.py` L638-642，受 `enhancements.skills_summary` 开关控制）。这是 Charles 额外的 prompt 增强层，Cline 不存在等价物。
3. **`allowed_skill_names` 白名单检查形式差异（S1 差距）**：Cline `isSkillAllowed`（`user-instruction-plugin.ts` L51-73）是真正的 4 形式检查（`normalizedId`/`normalizedName`/`bareId`/`bareName`），因为 watcher 的 `skill.id`（基于路径，可能含 namespace 前缀如 `ms-office-suite:pdf`）与 `skill.name`（frontmatter `name`）可以不同。Charles `_is_skill_allowed`（`registry.py` L57-96）**代码结构上是 4 形式**（L86-95 四个 `in` 检查），但调用处（L154 `list_skills`、L170 `get_skill`）传入 `(s.name, s.name, ...)` ——`skill_id` 与 `skill_name` 相同，4 形式退化为 2 形式（`normalized_id == normalized_name`、`bare_id == bare_name`）。Charles 的 `_skills` dict 按 `name` 键存储（L137），无独立 `id` 概念。
4. **always 技能标记语义不同（实现逻辑残留）**：计划 P4.3.5 声称"always 技能标记 | 是 | 是 | 已对齐"，实际**语义完全不同**。Cline 的 `alwaysEnabled`（`file.proto` L310、`skills.ts` L92 `alwaysEnabled: entry.alwaysEnabled`）仅用于 **remote skill**（企业策略：用户无法在 UI 关闭），语义是"始终启用、不可 toggled off"。Charles 的 `always` 字段（`loader.py` L70 `always: bool = False`、L234 `bool(frontmatter.get("always", False))`）语义是"**始终预加载指令到 system prompt**"（Level 2 预加载，`registry.py` L183-208 `get_always_skills` + `load_always_instructions` + `load_always_instructions_as_rule`）。Charles 的 always 预加载功能是 **nanobot 实现逻辑残留**（docstring 多处标注"对标 nanobot get_always_skills()"），Cline 明确声明 skills 是 on-demand 加载（`skills.mdx` L9 "Unlike rules which are always active, skills load on-demand"），无"预加载指令"概念。
5. **技能覆盖（多源 override）Charles 未集成到 Registry**：计划 P4.3.7 声称"技能覆盖 | 后注册覆盖 | 后注册覆盖 | 已对齐"。Cline `getAvailableSkills`（`skills.ts` L256-270）反向迭代实现多源 override（project → disk-global → remote，last wins）。Charles `SkillRegistry.discover()`（`registry.py` L130-138）仅调用单个 `SkillLoader(skills_dir).list_skills()`，**只支持单目录加载，无 override 机制**。Charles 虽有 `load_skills_multi_dir`/`load_skills_with_dirs`（`loader.py` L443-508）实现多目录 override，但这两个函数**未被 `SkillRegistry` 调用**（`server.py` L200-204 仅实例化单目录 `SkillRegistry`），属于"已实现但未集成"的孤立代码。

`nanobot` 残留检查：在 `agent/skills/registry.py`、`agent/skills/loader.py`、`agent/skills/__init__.py` 三个文件中发现 **15 处** `nanobot` 字符串残留，全部为 docstring/注释层面的历史对标注说明（详见第 4 节）。**实现逻辑残留**仅 1 处：`always` 字段及其预加载机制（`get_always_skills` / `load_always_instructions` / `load_always_instructions_as_rule`），源自 nanobot `get_always_skills()`，Cline 无等价物。

## 2. 逐项对比表

| # | 对比项 | Cline 位置 | Charles 位置 | 关键差异 | 一致性等级 |
|---|--------|-----------|-------------|---------|-----------|
| 4.3.1 | Registry 数据结构 | `unified-config-file-watcher.ts` L210（`getSnapshot("skill")` 返回 `Map<string, UnifiedConfigRecord<"skill", SkillConfig>>`） | `registry.py` L124（`_skills: dict[str, SkillMetadata]`） | Map vs dict，均按键存储；Cline 键为 watcher id（路径派生），Charles 键为 frontmatter name | 已对齐 |
| 4.3.2 | Registry 是否独立类 | 无独立类，watcher 内联管理 | `registry.py` L99 独立 `SkillRegistry` 类 | Charles 有独立类（nanobot 风格），Cline 无；计划描述"Cline 有 SkillRegistry 类"不准确 | 弱对齐（架构差异） |
| 4.3.3 | build_summary 输出 | 无 `build_summary` 方法；`definitions.ts` L754-766 在 `skills` 工具 description 末尾追加 `Available skills: ${names.join(", ")}.`（仅名称列表，disabled 过滤） | `registry.py` L210-252 `build_summary()` 生成 3 列段落（name + when_to_use + description），通过 `build_summary_as_rule()` 注入 system prompt | Charles 额外的 prompt 增强层；Cline 仅在工具 description 暴露名称 | 弱对齐（Charles 额外） |
| 4.3.4 | _build_description | `definitions.ts` L719-769 `createSkillsTool`，L754-766 动态 description getter 追加 `Available skills: ...` | `skill_tool.py` L225-253 `_build_description()` 追加 `可用技能: {names}。` | 逻辑等价（base + 可用技能列表）；Charles 在 SkillsTool 类中，Cline 在 createSkillsTool 工厂中 | 已对齐 |
| 4.3.5 | 白名单检查形式 | `user-instruction-plugin.ts` L51-73 `isSkillAllowed` 4 形式（id 与 name 可不同，namespace 前缀场景） | `registry.py` L57-96 `_is_skill_allowed` 代码 4 形式，调用处 `(s.name, s.name)` 退化为 2 形式 | Charles 结构 4 形式但有效 2 形式（无独立 id）；S1 差距 | 弱对齐（形式差距） |
| 4.3.6 | allowed_skill_names 来源 | `CreateUserInstructionPluginOptions.allowedSkillNames`（`user-instruction-plugin.ts` L32）由 plugin 调用方传入 | `SkillRegistry.__init__` 参数（`registry.py` L121），`server.py` L194-199 从 `AGENT_ALLOWED_SKILLS` 环境变量读取 | 来源不同（plugin 参数 vs 环境变量），语义等价 | 已对齐 |
| 4.3.7 | 禁用技能过滤（list） | `user-instruction-plugin.ts` L100 `listAvailableSkillNames` 中 `.filter((skill) => !skill.disabled)`；`definitions.ts` L757 description getter 中 `.filter((s) => !s.disabled)` | `registry.py` L157 `list_skills` 中 `[s for s in all_skills if not s.disabled]` | 两者均在 list 阶段过滤 disabled；语义等价 | 已对齐 |
| 4.3.8 | 禁用技能查询（get） | `user-instruction-plugin.ts` L120-128 `resolveSkillRecord` 中 exact 匹配后检查 `skill.disabled === true` 返回 `"configured but disabled"` 错误 | `skill_tool.py` L165-170 `SkillsTool._execute` 中 `skill_meta.disabled` 返回 `is_error=True` 错误；`registry.py` L160-174 `get_skill` 不过滤 disabled（保留供错误提示） | 两者均保留 disabled 技能元数据供错误提示；语义等价 | 已对齐 |
| 4.3.9 | always 技能标记 | `file.proto` L310 `always_enabled`（remote-only，用户不可 toggle off）；`skills.ts` L92 `alwaysEnabled: entry.alwaysEnabled`；frontmatter 无 `always` 字段 | `loader.py` L70 `always: bool`；L234 解析 frontmatter `always`；`registry.py` L183-208 `get_always_skills` + `load_always_instructions` 预加载指令到 system prompt | 语义完全不同：Cline = 不可禁用策略；Charles = 预加载指令；Charles 功能源自 nanobot | 未对齐（语义差异） |
| 4.3.10 | get_skill_metadata | `skills.ts` L171-209 `loadSkillMetadata` 解析 frontmatter 构建 `SkillMetadata`；L276-313 `getSkillContent` 返回 metadata + instructions | `loader.py` L221-298 `_parse_skill_file` 解析 frontmatter；`registry.py` L160-174 `get_skill` + L176-181 `load_instructions` 分两步 | 两者均支持按名获取元数据；Charles 拆分为 get_skill + load_instructions 两方法 | 已对齐 |
| 4.3.11 | 技能覆盖（单源） | `Map.set` 后注册覆盖（watcher 内部刷新时） | `dict[name] = meta` 后注册覆盖（`registry.py` L137 `{s.name: s for s in skills}`） | 单源场景语义等价 | 已对齐 |
| 4.3.12 | 技能覆盖（多源 override） | `skills.ts` L256-270 `getAvailableSkills` 反向迭代，last wins（project → disk-global → remote） | `registry.py` L130-138 `discover()` 仅单目录；`loader.py` L443-508 `load_skills_multi_dir` 已实现但未集成到 SkillRegistry | Charles Registry 不支持多源 override；孤立函数未接线 | 未对齐（功能缺失） |
| 4.3.13 | 技能排序 | `user-instruction-plugin.ts` L103 `listAvailableSkillNames` 中 `.sort((a, b) => a.localeCompare(b))`（仅错误提示中的可用列表排序）；`getConfiguredSkillsFromWatcher` 不排序（按 watcher 插入顺序） | `loader.py` L132 `sorted(self.skills_dir.iterdir())` 按目录名排序；`registry.py` L137 dict 保留插入顺序 | Cline 仅在错误提示列表排序；Charles 在加载阶段排序；list_skills 输出顺序不同 | 弱对齐（时机不同） |
| 4.3.14 | load_all / discover | `skills.ts` L220-251 `discoverSkills` 扫描 project + disk-global + remote 三源 | `registry.py` L130-138 `discover()` 调 `loader.list_skills()` 扫描单目录 | Cline 三源发现；Charles 单源发现 | 弱对齐（场景差异） |
| 4.3.15 | SkillMetadata 字段数量 | `skills.ts` L5-10 `SkillMetadata` 4 字段（name/description/path/source） | `loader.py` L46-81 `SkillMetadata` 12 字段（name/description/keywords/always/capabilities/file_path/source/allowed_tools/disabled/scripts/source_dir/when_to_use） | Charles 多出 8 个字段（keywords/capabilities/allowed_tools/scripts/source_dir/when_to_use 源自 nanobot，always 源自 nanobot，disabled 对标 Cline） | 弱对齐（Charles 扩展） |
| 4.3.16 | frontmatter 字段 | `user-instruction-config-loader.ts` L42-48 `SkillConfig` 4 字段（name/description/disabled/instructions）+ frontmatter 透传 | `loader.py` L221-298 解析 name/description/disabled/enabled/always/keywords/capabilities/allowed_tools/scripts/when_to_use | Charles 多出 6 个 frontmatter 字段；详见 P4.5 frontmatter 对比 | 弱对齐（Charles 扩展） |
| 4.3.17 | name 与目录名一致性校验 | `skills.ts` L194-197 `if (frontmatter.name !== skillName) return null` 严格校验 | `loader.py` L231 `name = frontmatter.get("name", skill_file.parent.name)` fallback 到目录名，不强制校验 | Cline 严格拒绝不一致；Charles fallback 容错 | 弱对齐（容错差异） |

## 3. 重点差距详细说明

### 3.1 Cline 无 SkillRegistry 类、无 build_summary 方法：计划描述与实际代码不符

- **计划描述**：P4.3 表格声称"Cline `SkillRegistry` 管理 SkillMetadata"、"Cline `build_summary()` 生成技能概览"。
- **Cline 实际实现**：
  - 全局搜索 `SkillRegistry|skillRegistry|class SkillRegistry` 在 `third_party/cline` 下 **0 命中**。
  - Cline 的"注册表"是 `UserInstructionConfigWatcher.getSnapshot("skill")` 返回的 `Map<string, UnifiedConfigRecord<"skill", SkillConfig>>`（`unified-config-file-watcher.ts` L210-218），由 `createUserInstructionConfigWatcher`（`user-instruction-config-loader.ts` L608-610）创建。
  - 全局搜索 `buildSummary|build_summary|skillSummary|skill_summary|skills-summary|skillsSummary` 在 `third_party/cline` 下 **0 命中**（命中的 `buildSummaryRequest`/`buildSummaryMessage` 是上下文压缩相关，与技能无关）。
  - Cline 的"技能概览"是 `createSkillsTool` 中 `Object.defineProperty(tool, "description", { get() { ... return \`${baseDescription} Available skills: ${skills.join(", ")}.\`; } })`（`definitions.ts` L754-766），仅在工具 description 末尾追加逗号分隔的技能名列表（disabled 过滤后）。
- **Charles 实际实现**：`SkillRegistry` 类（`registry.py` L99-292）是独立类，`build_summary()` 方法（L210-252）生成完整段落（标题 + 说明 + 每技能一行 3 列：name + when_to_use + description），并通过 `build_summary_as_rule()`（L254-263）包装为 `## charles-skills-summary` rule，由 `context.py` L638-642 在 `enhancements.skills_summary` 开启时注入 system prompt。
- **影响**：计划描述会让人以为 Charles 的 `SkillRegistry` 类和 `build_summary` 方法是对标 Cline 的，实际是 Charles 额外实现的 prompt 增强层（对标 nanobot `build_skills_summary()`），Cline 不存在等价物。
- **残留性质**：Charles 的 `SkillRegistry` 类结构源自 nanobot `SkillsLoader`（docstring L2/L20/L100/L184 多处标注"对标 nanobot"），属于 nanobot 实现逻辑的保留与扩展。Cline 的 watcher-based 设计未在 Charles 中复刻。

### 3.2 白名单检查形式：Charles 结构 4 形式但有效 2 形式（S1 差距）

- **Cline `isSkillAllowed`**（`user-instruction-plugin.ts` L51-73）：
  ```typescript
  const normalizedId = normalizeSkillToken(skillId);
  const normalizedName = normalizeSkillToken(skillName);
  const bareId = normalizedId.includes(":") ? normalizedId.split(":").at(-1) ?? normalizedId : normalizedId;
  const bareName = normalizedName.includes(":") ? normalizedName.split(":").at(-1) ?? normalizedName : normalizedName;
  return allowedSkills.has(normalizedId) || allowedSkills.has(normalizedName)
      || allowedSkills.has(bareId) || allowedSkills.has(bareName);
  ```
  调用处 `getConfiguredSkillsFromWatcher`（L92）传入 `isSkillAllowed(skill.id, skill.name, allowedSkills)`，其中 `skill.id` 来自 watcher snapshot 的 key（基于路径派生，可能含 namespace 前缀如 `ms-office-suite:pdf`），`skill.name` 来自 frontmatter `name`（如 `pdf`）。两者可不同，4 形式检查有实际意义。
- **Charles `_is_skill_allowed`**（`registry.py` L57-96）：
  ```python
  normalized_id = _normalize_skill_token(skill_id)
  normalized_name = _normalize_skill_token(skill_name)
  bare_id = normalized_id.split(":")[-1] if ":" in normalized_id else normalized_id
  bare_name = normalized_name.split(":")[-1] if ":" in normalized_name else normalized_name
  return (
      normalized_id in allowed_skills
      or normalized_name in allowed_skills
      or bare_id in allowed_skills
      or bare_name in allowed_skills
  )
  ```
  代码结构是 4 形式（L91-95 四个 `in` 检查），与 Cline 对齐。但调用处 `list_skills`（L154）和 `get_skill`（L170-172）传入 `_is_skill_allowed(s.name, s.name, self._allowed_skills)` —— **`skill_id` 与 `skill_name` 相同**，因为 Charles 的 `_skills` dict 按 `name` 键存储（L137 `{s.name: s for s in skills}`），无独立 `id` 概念。
- **退化结果**：`normalized_id == normalized_name`、`bare_id == bare_name`，4 形式退化为 2 形式（`normalized in set` 或 `bare in set`）。
- **影响**：Charles 当前系统无 namespaced skill（如 `ms-office-suite:pdf`），2 形式与 4 形式行为等价。但若未来引入 namespace，Charles 的调用处需同步传入独立 `id`，否则 4 形式检查形同虚设。docstring L65-72 已明确说明这一退化："当前系统无 namespaced skill，skill_id 与 skill_name 相同，4 形式退化为 2 形式...但为未来 namespace 扩展预留完整检查。"
- **残留性质**：非残留，属于 Charles 主动对齐 Cline 代码结构但受限于自身数据模型（无独立 id）的退化。S1 差距是计划标注的已知项。

### 3.3 always 技能标记语义不同：Charles 实现逻辑残留自 nanobot

- **Cline `alwaysEnabled`**：
  - 仅用于 remote skill（企业配置下发），`file.proto` L310 注释 "Whether the skill is always enabled (remote only, user cannot toggle off)"。
  - `parseRemoteSkillEntries`（`skills.ts` L105-125）将 `entry.alwaysEnabled` 映射到 `ValidatedRemoteSkill.alwaysEnabled`（L92），再写入 `SkillMetadata` 时仅作为 source 标记（L239-244 未将 `alwaysEnabled` 写入 `SkillMetadata`，因 `SkillMetadata` 接口无此字段）。
  - `skills.mdx` L9 明确："Unlike rules (which are always active), skills load on-demand" —— Cline skills **永远是 on-demand**，无"预加载指令到 system prompt"机制。
- **Charles `always`**：
  - `loader.py` L70 `always: bool = False`，L234 `always = bool(frontmatter.get("always", False))` 从 frontmatter 解析。
  - `registry.py` L183-191 `get_always_skills()` 返回 `always=True` 的技能名列表。
  - `registry.py` L193-208 `load_always_instructions()` 加载这些技能的完整指令文本并拼接。
  - `registry.py` L272-285 `load_always_instructions_as_rule()` 包装为 `## charles-always-skills` rule。
  - `context.py` L632-636 在 `enhancements.always_skills` 开启时注入 system prompt。
  - docstring L184 明确标注："对标 nanobot get_always_skills()"。
- **语义对比**：
  | 维度 | Cline `alwaysEnabled` | Charles `always` |
  |------|----------------------|-----------------|
  | 适用范围 | remote skill 专属 | 所有 skill 均可配置 |
  | 语义 | 用户不可在 UI toggle off | 启动时预加载指令到 system prompt |
  | 影响 | toggle 状态锁定 | Level 2 指令预注入（绕过 use_skill 工具） |
  | frontmatter 字段 | 无（来自 remote entry 元数据） | `always: true` |
- **影响**：Charles 的 `always` 预加载功能是 **nanobot 实现逻辑残留**，与 Cline 的 on-demand 设计哲学冲突。Charles 主动保留此功能用于"常驻技能"场景（如 write-report 研报技能需常驻指令），属于场景驱动的扩展，但 docstring 标注"对标 Cline"是不准确的。
- **残留性质**：**实现逻辑残留**。Charles 的 `get_always_skills` / `load_always_instructions` / `load_always_instructions_as_rule` 三个方法（`registry.py` L183-285）是 nanobot `get_always_skills()` 的扩展实现，Cline 无等价物。

### 3.4 技能覆盖（多源 override）：Charles 已实现但未集成到 Registry

- **Cline 多源 override**：
  - `discoverSkills`（`skills.ts` L220-251）按 `project → disk-global → remote` 顺序收集 skills 到数组。
  - `getAvailableSkills`（L256-270）反向迭代数组，`seen` Set 去重，`result.unshift(skill)` —— 后插入的（高优先级）先被 seen，覆盖先插入的（低优先级），实现 last-wins 语义。
  - `skills.mdx` L162 明确："When a global skill and project skill have the same name, the global skill takes precedence."
- **Charles 多源 override**：
  - `load_skills_multi_dir`（`loader.py` L443-485）遍历 `dirs` 列表，`skills_by_name[skill.name] = skill` 后加载的覆盖先加载的，last-wins 语义。
  - `load_skills_with_dirs`（L488-508）封装版本，`primary_dir` 优先级最高。
  - **但**：`SkillRegistry.discover()`（`registry.py` L130-138）仅调用 `self.loader.list_skills()`（单目录），**未调用** `load_skills_multi_dir`。`server.py` L200-204 实例化 `SkillRegistry(skills_dir=skills_path)` 也仅传入单个 `agent_config/skills` 目录。
- **影响**：Charles 的多源 override 功能已实现但**孤立存在**，SkillRegistry 实际运行时只支持单目录加载，无法实现"用户级 + 项目级"override。若用户在 `~/.cline/skills/` 和 `agent_config/skills/` 都放了同名 skill，Charles 不会触发 override（仅加载 `agent_config/skills` 中的版本）。
- **残留性质**：非残留，属于"已实现未集成"的功能缺口。`load_skills_multi_dir` 函数对标 Cline 多源加载，但未接入 `SkillRegistry` 主路径。

### 3.5 技能排序时机不同：Cline 错误提示排序，Charles 加载阶段排序

- **Cline**：
  - `getConfiguredSkillsFromWatcher`（`user-instruction-plugin.ts` L75-93）返回 skills 列表时**不排序**，按 watcher snapshot Map 的插入顺序（即目录扫描顺序）。
  - `listAvailableSkillNames`（L95-104）仅在生成"可用技能"错误提示时调用 `.sort((a, b) => a.localeCompare(b))`（L103）排序。
  - `createSkillsTool` 的 description getter（`definitions.ts` L756-758）`executor.configuredSkills?.filter((s) => !s.disabled).map((s) => s.name)` —— **不排序**，按 configuredSkills 顺序。
- **Charles**：
  - `SkillLoader.list_skills`（`loader.py` L132）`for skill_dir in sorted(self.skills_dir.iterdir())` —— **加载阶段即按目录名排序**。
  - `SkillRegistry.discover`（`registry.py` L137）`{s.name: s for s in skills}` 保留 loader 的排序顺序。
  - `list_skills`（L149）`list(self._skills.values())` 返回排序后的列表。
- **影响**：两者最终暴露给 LLM 的技能顺序可能不同。Cline 按 watcher 扫描顺序（通常也是字母序，但不保证）；Charles 强制字母序（sorted）。对 LLM 而言差异可忽略，但在 description 中的"可用技能"列表顺序可能不同。
- **残留性质**：非残留，属于实现细节差异。

## 4. nanobot 残留检查

在 `agent/skills/registry.py`、`agent/skills/loader.py`、`agent/skills/__init__.py` 三个重点文件中发现 **15 处** `nanobot` 字符串残留，**全部为 docstring/注释**层面，不影响 SkillRegistry 核心机制。**实现逻辑残留**仅 1 处（always 预加载机制）。

### 4.1 注释残留（14 处，不影响功能）

| 文件 | 行号 | 残留内容 | 残留性质 | 是否影响 SkillRegistry |
|------|------|---------|---------|----------------------|
| `agent/skills/registry.py` | L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 标题 | 否（注释） |
| `agent/skills/registry.py` | L20 | `对标 nanobot:` 段落 | docstring 对标说明 | 否（注释） |
| `agent/skills/registry.py` | L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | 类 docstring 标题 | 否（注释） |
| `agent/skills/registry.py` | L184 | `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()` | 方法 docstring | 否（注释，但方法本身是实现残留，见 4.2） |
| `agent/skills/loader.py` | L2 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | docstring 标题 | 否（注释） |
| `agent/skills/loader.py` | L29 | `对标 nanobot:` 段落 | docstring 对标说明 | 否（注释） |
| `agent/skills/loader.py` | L48 | `"""技能元数据 — 对标 Cline frontmatter + nanobot metadata` | dataclass docstring | 否（注释） |
| `agent/skills/loader.py` | L96 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | 类 docstring 标题 | 否（注释） |
| `agent/skills/loader.py` | L167 | `对标 nanobot: load_skill() + _strip_frontmatter()` | 方法 docstring | 否（注释） |
| `agent/skills/loader.py` | L222 | `"""解析 SKILL.md 文件 — 对标 nanobot get_skill_metadata()` | 方法 docstring | 否（注释） |
| `agent/skills/loader.py` | L392 | `# Fallback: 简单 YAML 解析 — 对标 nanobot fallback` | 行内注释 | 否（注释） |
| `agent/skills/loader.py` | L423 | `"""去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()` | 方法 docstring | 否（注释） |
| `agent/skills/__init__.py` | L2 | `"""技能系统 — 对标 Cline skills + nanobot SkillsLoader` | 模块 docstring 标题 | 否（注释） |
| `agent/skills/__init__.py` | L23 | `对标 nanobot:` 段落 | docstring 对标说明 | 否（注释） |

### 4.2 实现逻辑残留（1 处，影响功能）

| 文件 | 行号 | 残留内容 | 残留性质 | 是否影响 SkillRegistry |
|------|------|---------|---------|----------------------|
| `agent/skills/registry.py` | L183-285 | `get_always_skills()` / `load_always_instructions()` / `load_always_instructions_as_rule()` 三个方法实现 always 技能指令预加载到 system prompt | **实现逻辑残留**（源自 nanobot `get_always_skills()`） | 是（Charles 额外功能，Cline 无等价物） |

> **关键证据**：
> 1. `registry.py` L184 docstring 明确标注"对标 nanobot get_always_skills()"，未标注"对标 Cline"。
> 2. Cline `skills.mdx` L9 明确声明 "skills load on-demand"，无"预加载指令"概念。
> 3. Cline `alwaysEnabled`（`file.proto` L310）仅用于 remote skill 的 toggle 锁定，语义是"用户不可禁用"，与 Charles "预加载指令到 system prompt"完全不同。
> 4. Charles 的 `always` 预加载通过 `context.py` L632-636 注入 system prompt，是 Charles/nanobot 风格的 prompt 增强，Cline 不存在等价物。
>
> **残留判定**：此为 nanobot 实现逻辑的保留与扩展，属于"Charles 主动保留的 nanobot 功能"。由于 Charles 量化场景需要"常驻技能"（如 write-report 研报技能需常驻指令），此功能有实际用途，**不建议移除**，但应在 docstring 中明确标注"Charles 额外功能，源自 nanobot，Cline 无等价物"，避免误导后续对标。

### 4.3 非残留的 Charles 主动扩展

以下 Charles 功能虽未严格对标 Cline，但属于 Charles 主动扩展，非 nanobot 残留：
- `build_summary()` 3 列输出（name + when_to_use + description）：Charles 额外的 prompt 增强层
- `build_summary_as_rule()` / `load_always_instructions_as_rule()`：rule 包装方法
- `build_tool_hint()`：返回 None 的占位方法
- `SkillMetadata` 的 `keywords`/`capabilities`/`allowed_tools`/`scripts`/`source_dir`/`when_to_use` 字段：Charles 场景扩展
- `load_skills_multi_dir` / `load_skills_with_dirs`：多目录加载（已实现未集成）

## 5. 修复建议

### P0（阻碍后续对比/集成）
1. **修正计划 P4.3 描述**：计划表格声称"Cline 有 `SkillRegistry` 类"和"Cline 有 `build_summary()` 方法"，实际 Cline 两者均无。建议将描述改为"Cline 通过 `UserInstructionConfigWatcher.getSnapshot("skill")` 返回的 Map 管理技能，无独立 Registry 类；通过 `skills` 工具动态 description 暴露可用技能列表，无 `build_summary` 方法。Charles 的 `SkillRegistry` 类和 `build_summary` 方法是额外实现（对标 nanobot）"，避免误导后续修复决策。
2. **修正计划 P4.3.5 always 描述**：计划声称"always 技能标记 | 是 | 是 | 已对齐"。实际 Cline `alwaysEnabled` 与 Charles `always` 语义完全不同（toggle 锁定 vs 指令预加载）。建议将描述改为"Cline `alwaysEnabled` 仅用于 remote skill toggle 锁定；Charles `always` 用于指令预加载到 system prompt，源自 nanobot，Cline 无等价物"。

### P1（架构债务）
3. **评估 always 预加载机制是否需保留**：Charles 的 `always` 预加载功能（`registry.py` L183-285）源自 nanobot，与 Cline on-demand 设计哲学冲突。建议：
   - 若保留：在 docstring 中明确标注"Charles 额外功能，源自 nanobot `get_always_skills()`，Cline 无等价物"，移除"对标 Cline"的误导性标注。
   - 若移除：需评估 `context.py` L632-636 `enhancements.always_skills` 路径的依赖，确认无生产场景依赖此功能后方可移除。
4. **集成多源 override 到 SkillRegistry**：Charles 的 `load_skills_multi_dir`（`loader.py` L443-485）已实现多目录 override 但未接入 `SkillRegistry`。建议在 `SkillRegistry.__init__` 增加 `skills_dirs: list[Path] | None` 参数，当传入多目录时调用 `load_skills_multi_dir` 而非 `loader.list_skills`，对标 Cline `discoverSkills` 的多源加载。

### P2（功能增强）
5. **白名单检查传独立 id（消除 S1 差距）**：Charles `_is_skill_allowed` 代码结构已是 4 形式，但调用处传入 `(s.name, s.name)` 退化为 2 形式。建议：
   - 在 `SkillMetadata` 增加 `id` 字段（默认等于 `name`），或在 `_skills` dict 的 key 中保留独立 id。
   - `list_skills` / `get_skill` 调用处改为 `_is_skill_allowed(s.id, s.name, self._allowed_skills)`。
   - 这样未来引入 namespace（如 `ms-office-suite:pdf`）时 4 形式检查自动生效。
6. **name 与目录名一致性校验对齐**：Cline `loadSkillMetadata`（`skills.ts` L194-197）严格校验 `frontmatter.name !== skillName` 时返回 null；Charles `_parse_skill_file`（`loader.py` L231）fallback 到目录名。建议增加可选严格模式：当 `frontmatter.name` 与目录名不一致时记录 warning（对标 Cline `Logger.warn`），但保留 fallback 容错。

### P3（文档/规范）
7. **清理 nanobot 注释残留**：`agent/skills/registry.py` L2/L20/L100/L184、`agent/skills/loader.py` L2/L29/L48/L96/L167/L222/L392/L423、`agent/skills/__init__.py` L2/L23 共 14 处 nanobot 历史对标注释，建议统一改为"Charles 历史实现"或保留"对标 nanobot"但补充说明"nanobot 功能在 Cline 中无等价物"。
8. **补齐计划 P4.3 字段清单**：计划 P4.3 表格未列出 `_build_description`、`load_all/discover`、`SkillMetadata` 字段数量、`name` 与目录名一致性校验等对比项，建议补齐（已在本文档第 2 节补充 4.3.4/4.3.14/4.3.15/4.3.16/4.3.17）。

## 6. 验证方法建议

1. **Cline 无 SkillRegistry 验证**：在 `third_party/cline` 目录运行 `grep -R "class SkillRegistry" .`，应返回 0 命中；运行 `grep -R "build_summary\|buildSummary" . | grep -i skill`，应返回 0 命中（命中的 `buildSummaryRequest`/`buildSummaryMessage` 是上下文压缩相关）。
2. **Registry 数据结构验证**：在 Charles 中创建 `SkillRegistry(skills_dir=Path("agent_config/skills"))` 实例，调用 `discover()` 后检查 `registry._skills` 是 dict 类型且按 `name` 键存储；在 Cline 中调用 `watcher.getSnapshot("skill")` 应返回 Map 类型且按 watcher id 键存储。两者结构等价但键来源不同（name vs path-derived id）。
3. **白名单退化验证**：在 Charles `SkillRegistry` 中配置 `allowed_skill_names=["pdf"]`，注册一个 `name="pdf"` 的技能，调用 `list_skills()` 应返回该技能；检查 `_is_skill_allowed("pdf", "pdf", {"pdf"})` 返回 True，但 `_is_skill_allowed("ms-office-suite:pdf", "pdf", {"pdf"})` 也应返回 True（bare_name 匹配），验证 4 形式代码结构正确（虽然当前调用处不传 namespace id）。
4. **always 预加载验证**：在 Charles 中创建一个 `always: true` 的技能，调用 `registry.get_always_skills()` 应返回该技能名，`registry.load_always_instructions()` 应返回非空指令文本；在 Cline 中搜索 `alwaysEnabled` 仅在 remote skill 解析路径命中，无"预加载指令"逻辑。
5. **多源 override 未集成验证**：在 Charles 中创建两个目录 `skills_a/` 和 `skills_b/`，各放一个同名技能（内容不同），实例化 `SkillRegistry(skills_dir="skills_a")` 后 `list_skills()` 仅返回 `skills_a` 版本；调用 `load_skills_multi_dir(["skills_a", "skills_b"])` 应返回 `skills_b` 版本（覆盖 `skills_a`），验证多源 override 函数本身正确但未集成到 SkillRegistry。
6. **禁用技能跳过验证**：在 Charles 中创建 `disabled: true` 的技能，调用 `registry.list_skills()` 不应返回该技能；调用 `registry.get_skill(name)` 应返回元数据（含 `disabled=True`）；调用 `SkillsTool._execute({skill: name})` 应返回 `is_error=True` 的 "configured but disabled" 错误。与 Cline `resolveSkillRecord` L123-127 行为一致。
7. **build_summary 输出验证**：在 Charles 中调用 `registry.build_summary()` 应返回多行文本，首行 `# 技能目录...`，每技能一行 `- {name} ({when_to_use}): {description}`；在 Cline 中调用 `createSkillsTool(executor).description` 应返回 `... Available skills: a, b, c.`（仅名称列表）。两者输出形态完全不同，Charles 是段落注入 system prompt，Cline 是工具描述。
8. **nanobot 残留回归**：运行 `grep -R "nanobot" agent/skills/` 并统计行数，建立基线（当前 15 行：14 注释 + 1 实现逻辑）；后续修复后确认注释残留可清理至 0（实现逻辑残留 `always` 预加载按 P1.3 决策保留或移除）。
