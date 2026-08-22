# Phase 4.1 技能工具（skills tool）实现对比

> 对比范围：Cline `createSkillsTool` 工厂 + `SkillsInputSchema` + `createUserInstructionSkillsExecutor` 与 Charles `SkillsTool` 类的实现差异；`runningSkills` 并发去重、`withTimeout` 超时、`allowedSkillNames` 白名单、`skillsTimeoutMs` 可配置性、动态 description 构建等核心机制逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L714-769（`createSkillsTool` 工厂，含 `Object.defineProperty` 动态 description + `withTimeout` 包裹）
> - `sdk/packages/core/src/extensions/tools/schemas.ts` L246-253（`SkillsInputSchema` Zod 定义）+ L338（`SkillsInput` 类型）
> - `sdk/packages/core/src/extensions/tools/types.ts` L135-139（`SkillsExecutor` 类型）+ L156-179（`SkillsExecutorSkillMetadata` + `SkillsExecutorWithMetadata`）+ L212（executors.skills 字段）
> - `sdk/packages/core/src/extensions/tools/helpers.ts` L48-59（`withTimeout` 实现：`Promise.race` + `setTimeout`）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L35-73（`normalizeSkillToken` + `toAllowedSkillSet` + `isSkillAllowed` 4 形式匹配）+ L75-172（`getConfiguredSkillsFromWatcher` + `resolveSkillRecord` 含 disabled/ambiguous 错误路径）+ L174-217（`createUserInstructionSkillsExecutor`：`runningSkills` Set + try/finally + XML 返回格式 + `configuredSkills` getter）
> - `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` 全文 89 行（`toggleSkillFrontmatter` 写入 SKILL.md 实现 enable/disable 切换）
>
> Charles 源码：
> - `agent/skills/skill_tool.py`（`SkillsTool` 类，全文 267 行）
> - `agent/skills/registry.py` L33-96（`_normalize_skill_token` + `_to_allowed_skill_set` + `_is_skill_allowed` 4 形式匹配）+ L99-292（`SkillRegistry` 类，含白名单/disabled 过滤）
> - `agent/skills/loader.py` L46-82（`SkillMetadata` 含 `disabled`/`allowed_tools` 字段）+ L237-241（disabled 解析）
> - `agent/server.py` L402-405（`skills_timeout_ms` 环境变量注入）
> - `agent/runtime.py` L1952-1970（`asyncio.wait_for` 超时包裹）

---

## 一、执行摘要

本阶段对比 Cline `skills` 工具与 Charles `SkillsTool` 类的核心实现。两者在**工具名、XML 返回格式、不创建子 agent、runningSkills 并发去重、try/finally 释放、15s 超时、白名单 4 形式匹配**等关键机制上**已对齐**（Stage 31.1-31.4 + Stage 37.2 已修复原 S1/S2 差距）。剩余差异主要集中在**实现语言范式**（TypeScript Zod vs Python JSON Schema、`Object.defineProperty` getter vs `@property` 装饰器）和**辅助功能缺失**（frontmatter toggle 写入功能、全局 skills 目录、文件监听热重载）。

### 核心结论

1. **工具名完全一致**：两者均为 `"skills"`。
2. **XML 返回格式完全一致**：两者均返回 `<command-name>{name}</command-name><command-args>{args}</command-args>\n<command-instructions>\n{description}{instructions}\n</command-instructions>` 格式。**注意**：AGENT_COMPARISON_PLAN_V2.md P4.1 计划表中将 XML 格式描述为 `<skill name="..."></skill>`，此描述与两方实际源码均不符，实际格式为 `<command-name>` 标签格式（Cline user-instruction-plugin.ts L202 + Charles skill_tool.py L201-207）。
3. **不创建子 agent**：两者均在主 agent 上下文中返回指令文本，不创建独立 runtime、不限制工具集、不用 attempt_completion 返回结果。Charles skill_tool.py L18-22 明确说明此设计差异。
4. **runningSkills 并发去重已对齐**（Stage 31.1）：Cline `Set<string>` vs Charles `set[str]`，均用 try/finally 释放。
5. **15s 超时已对齐**（Stage 31.2）：Cline `withTimeout(15000)` vs Charles `asyncio.wait_for(timeout=15.0)`，超时机制位置不同（Cline 在工具内部，Charles 在 runtime 层）。
6. **白名单 4 形式匹配已对齐**（Stage 31.3）：Charles registry.py L85-96 完整实现 4 形式检查（normalizedId + normalizedName + bareId + bareName）。**注意**：计划表 4.1.10 标注"S1 差距 4 形式 vs 2 形式"，但实际 Charles 已实现 4 形式，S1 差距已修复。
7. **skillsTimeoutMs 可配置已对齐**（Stage 37.2）：Charles 通过 `AGENT_SKILLS_TIMEOUT_MS` 环境变量注入，默认 15000。**注意**：计划表 4.1.9 标注"S2 差距 硬编码 15000"，但实际 Charles 已可配置，S2 差距已修复。
8. **nanobot 残留**：**15 处注释残留**（4 个文件），**0 处实现逻辑残留**。`allowed_tools` 字段（Phase 20）为未使用的 dead metadata，概念上源自 nanobot 子 agent 模型但从未被 SkillsTool 实际使用。

### 一致性总体评估

- **核心机制**：**高**。工具名、XML 格式、并发去重、超时、白名单均对齐。
- **实现范式**：**中**。TypeScript 与 Python 范式差异（Zod vs JSON Schema、Object.defineProperty vs @property）。
- **辅助功能**：**低**。Charles 缺失 frontmatter toggle 写入、全局 skills 目录、文件监听热重载。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.1.1 | 工具名 | `"skills"`（definitions.ts L734） | `"skills"`（skill_tool.py L77） | 高 | 完全一致 |
| 4.1.2 | XML 返回格式 | `<command-name>{name}</command-name><command-args>{args}</command-args>\n<command-instructions>\n{desc}{instr}\n</command-instructions>`（user-instruction-plugin.ts L195-202） | 完全相同格式（skill_tool.py L199-207） | 高 | 完全一致。计划表描述 `<skill name="...">` 有误 |
| 4.1.3 | 子 agent 创建 | 不创建，主上下文指令注入（user-instruction-plugin.ts L180-206） | 不创建，主上下文指令注入（skill_tool.py L123） | 高 | 完全一致 |
| 4.1.4 | description 动态生成 | `Object.defineProperty(tool, "description", { get() {...} })`（definitions.ts L754-766），getter 中过滤 disabled 并拼接 `Available skills: ...` | `@property description` 调用 `_build_description()`（skill_tool.py L80-81 + L225-253），通过 `list_skills()` 获取已过滤 disabled 的列表 | 高 | 实现范式不同但语义等价 |
| 4.1.5 | runningSkills 去重 | `const runningSkills = new Set<string>()`（user-instruction-plugin.ts L179），key 为 resolved skill `id` | `self._running_skills: set[str] = set()`（skill_tool.py L73），key 为 `_normalize_skill_token(skill_name)` | 高 | 已对齐（Stage 31.1）。key 选取略有差异：Cline 用 resolved id，Charles 用 normalized input name |
| 4.1.6 | finally 释放 | `try { ... } finally { runningSkills.delete(id); }`（user-instruction-plugin.ts L193-205） | `try: ... finally: self._running_skills.discard(skill_id)`（skill_tool.py L186-223） | 高 | 完全一致 |
| 4.1.7 | withTimeout 15s | `withTimeout(executor(...), timeoutMs, msg)`（definitions.ts L742-750），`withTimeout` = `Promise.race` + `setTimeout`（helpers.ts L48-59），`timeoutMs = config.skillsTimeoutMs ?? 15000` | `asyncio.wait_for(tool.execute(...), timeout=timeout_ms/1000.0)`（runtime.py L1965-1968），`timeout_ms = self._skills_timeout_ms`（默认 15000） | 高 | 已对齐（Stage 31.2）。位置不同：Cline 在工具内部，Charles 在 runtime 层 |
| 4.1.8 | allowedSkillNames 白名单 | `toAllowedSkillSet` + `isSkillAllowed` 4 形式（user-instruction-plugin.ts L39-73）：normalizedId / normalizedName / bareId / bareName | `_to_allowed_skill_set` + `_is_skill_allowed` 4 形式（registry.py L41-96），代码逐行对齐 | 高 | 已对齐（Stage 31.3）。计划表 4.1.10 标注"S1 差距"已失效 |
| 4.1.9 | skillsTimeoutMs 可配置 | `config.skillsTimeoutMs ?? 15000`（definitions.ts L723），通过 config 对象注入 | `skills_timeout_ms` 参数（skill_tool.py L55），通过 `AGENT_SKILLS_TIMEOUT_MS` 环境变量注入（server.py L404） | 高 | 已对齐（Stage 37.2）。计划表标注"S2 差距"已失效。注入方式不同：config 对象 vs 环境变量 |
| 4.1.10 | 白名单匹配形式 | 4 形式（user-instruction-plugin.ts L67-72） | 4 形式（registry.py L91-96） | 高 | 已对齐。计划表标注"4 形式 vs 2 形式 S1 差距"已失效 |
| 4.1.11 | InputSchema | Zod `SkillsInputSchema`：`skill: z.string().min(1)`，`args: z.string().nullable().optional()`（schemas.ts L246-253），通过 `zodToJsonSchema` 转 JSON Schema | JSON Schema dict（skill_tool.py L85-98）：`skill: {type: string}`，`args: {type: string}`，`required: ["skill"]` | 中 | 类型系统不同。Charles 缺 `minLength: 1` 和 `args` 的 nullable 标记，但运行时校验补全（L132 `if not skill_name`） |
| 4.1.12 | frontmatter toggle | `skill-frontmatter-toggle.ts` 全文 89 行：`toggleSkillFrontmatter` 读取 SKILL.md → 解析 frontmatter → 修改 `disabled` 字段 → 写回文件（L76-89） | `loader.py` L237-241 仅**读取** `disabled`/`enabled` 字段，**无写入/切换功能** | 低 | Charles 缺失 toggle 写入功能。读取已对齐（Stage 31.4），但无法通过 API 切换 enable/disable 状态 |
| 4.1.13 | args trim 处理 | `args?.trim()` 后再判断与插入（user-instruction-plugin.ts L194） | `input.get("args") or ""` 不 trim（skill_tool.py L130） | 中 | Charles 对纯空白 args 会生成 `<command-args>   </command-args>`，Cline 会视为无 args |
| 4.1.14 | disabled 错误提示 | `Skill "${name}" is configured but disabled.`（user-instruction-plugin.ts L125-127 / L154-157） | `Skill "{name}" is configured but disabled.`（skill_tool.py L168） | 高 | 完全一致（双引号 vs 单引号差异可忽略） |
| 4.1.15 | ambiguous 错误提示 | 有：`Skill "${requested}" is ambiguous. Use one of: ...`（L148-163） | 无：Charles 不支持 namespaced skill，无歧义场景 | 中 | Charles 当前无 namespace，可接受 |
| 4.1.16 | not found 错误提示 | `Skill "${requested}" not found. Available skills: ...`（L165-171） | `技能不存在: {name}` + `available_skills` 列表（skill_tool.py L155-161） | 中 | 信息等价但格式不同（英文 vs 中文，字符串 vs dict） |
| 4.1.17 | already running 错误提示 | `Skill "${name}" is already running.`（L189） | `Skill "{name}" is already running.`（skill_tool.py L179） | 高 | 完全一致。Charles 注释明确 `is_error=False` 对齐 Cline 返回提示文本而非 error |
| 4.1.18 | configuredSkills 元数据 | `Object.defineProperty(executor, "configuredSkills", { get })` 返回 `[{id, name, description, disabled}]`（user-instruction-plugin.ts L208-215），**包含 disabled 技能** | `configured_skills()` 方法返回 `[{name, description, disabled: False}]`（skill_tool.py L255-266），**仅含 enabled 技能**且 `disabled` 硬编码 False | 中 | Charles 方法似乎未被调用（_build_description 直接用 list_skills）。Cline configuredSkills 含 disabled 项供 description getter 过滤 |
| 4.1.19 | description 内容语言 | 英文，含 "blocking requirement"、"Never mention a skill without invoking"（definitions.ts L725-731） | 中文，含"必须先调用此工具"、"禁止只提及技能而不调用"（skill_tool.py L234-242） | 中 | 语义对齐，语言本地化。Charles 示例为金融领域（stock-price/read-pdf/write-report），Cline 为通用（pdf/commit/review-pr） |
| 4.1.20 | Plan 模式限制 | 无 | Phase 31.5：Plan 模式下禁止调用 `write-report`（skill_tool.py L138-150） | — | Charles 独有增强，非 nanobot 残留 |
| 4.1.21 | scripts 元数据 | 无 | Phase 33.4：若技能有自动发现的脚本，在 metadata 中返回 `{"scripts": [...]}`（skill_tool.py L209-213） | — | Charles 独有增强 |
| 4.1.22 | read_only | 无此概念 | `True`（skill_tool.py L101-102） | — | Charles 独有，Cline 由 toolPolicies 控制 |
| 4.1.23 | retryable / maxRetries | `retryable: false, maxRetries: 0`（definitions.ts L738-739） | 继承 BaseTool 默认值 | 高 | 语义一致 |

---

## 三、重点差距详细说明

### 3.1 计划表 S1/S2 差距已修复（4.1.9 + 4.1.10）

AGENT_COMPARISON_PLAN_V2.md 计划表标注两项差距：

- **4.1.9 skillsTimeoutMs 可配置 — S2 差距**：计划表称"Charles 硬编码 15000"。实际 Charles 在 Stage 37.2 已修复：`SkillsTool.__init__` 接受 `skills_timeout_ms: int = 15000` 参数（skill_tool.py L55），`server.py` L404 通过 `AGENT_SKILLS_TIMEOUT_MS` 环境变量注入可配置值。**S2 差距已失效**。

- **4.1.10 白名单匹配形式 — S1 差距**：计划表称"Charles 2 形式 vs Cline 4 形式"。实际 Charles `registry.py` L85-96 完整实现 4 形式检查：

```python
# registry.py L85-96
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

与 Cline user-instruction-plugin.ts L59-72 逐行对齐。**S1 差距已失效**。

### 3.2 超时机制位置差异（4.1.7）

- **Cline**：超时在**工具内部**实现。`createSkillsTool` 的 `execute` 函数用 `withTimeout(executor(...), timeoutMs, msg)` 包裹 executor 调用（definitions.ts L742-750）。`withTimeout` 使用 `Promise.race` + `setTimeout`（helpers.ts L48-59），超时后 reject 并抛出 `TimeoutError`。

- **Charles**：超时在 **runtime 层**实现。`SkillsTool.timeout_ms` 属性返回 `self._skills_timeout_ms`（skill_tool.py L104-114），runtime.py L1952-1968 读取该值并用 `asyncio.wait_for(tool.execute(...), timeout=timeout_ms/1000.0)` 包裹。超时后 runtime 捕获 `asyncio.TimeoutError` 并返回 is_error 结果。

两者语义等价（均超时 15s 后中断），但实现位置不同。Charles 的设计使超时逻辑对所有工具统一处理（runtime 层），Cline 的设计在工具内部按需包裹。Charles 方案更通用但耦合度略高。

### 3.3 frontmatter toggle 写入功能缺失（4.1.12）

Cline 提供完整的 `toggleSkillFrontmatter` 函数（skill-frontmatter-toggle.ts L76-89）：
1. 读取 SKILL.md 文件内容
2. 解析 YAML frontmatter
3. 根据 `enabled` 参数：enable 时删除 `disabled` 字段，disable 时设置 `disabled: true`
4. 序列化并写回文件

Charles `loader.py` L237-241 仅实现**读取** `disabled`/`enabled` 字段：

```python
disabled = bool(frontmatter.get("disabled", False))
if frontmatter.get("enabled", True) is False:
    disabled = True
```

**无任何写入/切换功能**。这意味着 Charles 无法通过 API 或工具调用动态启用/禁用技能，只能手动编辑 SKILL.md 文件。此功能缺失不影响 skills 工具的核心执行流程，但限制了运行时管理能力。

### 3.4 InputSchema 类型系统差异（4.1.11）

| 字段 | Cline Zod | Charles JSON Schema | 差异影响 |
|------|-----------|--------------------|---------|
| `skill` | `z.string().min(1)` | `{"type": "string"}`（无 `minLength`） | Charles 靠运行时 `if not skill_name` 补全校验（L132） |
| `args` | `z.string().nullable().optional()` | `{"type": "string"}`（无 nullable 标记，不在 required 中） | Charles 不显式支持 null 值，但 `input.get("args") or ""` 容错处理 |
| required | Zod 推断为 `["skill"]`（args optional） | `["skill"]`（L97） | 一致 |

Charles 的 JSON Schema 在声明层面不如 Cline Zod 严格，但运行时校验逻辑补全了关键约束。建议补充 `minLength: 1` 和 `args` 的 nullable 声明以提升 schema 自描述性。

### 3.5 runningSkills key 选取差异（4.1.5）

- **Cline**：key 为 `resolved skill id`。`resolveSkillRecord` 返回 `{ id, skill }`，其中 `id` 来自 watcher snapshot 的 entry key（通常为规范化名称），随后 `runningSkills.add(id)` 和 `runningSkills.has(id)` 均使用此 resolved id（user-instruction-plugin.ts L187-192）。

- **Charles**：key 为 `_normalize_skill_token(skill_name)`，即规范化后的**用户输入**名称（skill_tool.py L176-185）。

```python
skill_id = _normalize_skill_token(skill_name)
if skill_id in self._running_skills:
    ...
self._running_skills.add(skill_id)
```

差异影响：当前系统无 namespaced skill（如 `ms-office-suite:pdf`），`skill_name` 与 canonical id 相同，两者行为一致。但若未来引入 namespace，Charles 需确保 `_normalize_skill_token` 能正确映射 `ms-office-suite:pdf` 与 `pdf` 到同一 key（当前实现仅 `lstrip("/")` + `.lower()`，不处理 `:` 分隔符），否则可能出现同一技能以 `namespace:name` 和 `name` 两种形式同时运行。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（15 处，4 个文件）

| 文件 | 行号 | 残留内容 | 性质 |
|------|------|---------|------|
| `agent/skills/__init__.py` | L2 | `"""技能系统 — 对标 Cline skills + nanobot SkillsLoader` | docstring 标题 |
| `agent/skills/__init__.py` | L23-26 | `对标 nanobot:\n    - agent/skills.py: SkillsLoader 类\n    - frontmatter 解析: PyYAML + fallback\n    - build_skills_summary(): XML 格式技能列表` | docstring 对标说明 |
| `agent/skills/__init__.py` | L13 | `SkillTool: use_skill 工具，LLM 通过 tool_call 加载技能指令` | **工具名残留**：实际工具名为 `skills`，注释中为 `use_skill` |
| `agent/skills/__init__.py` | L15 | `关键设计: use_skill 工具解决"agent 不读 SKILL.md"问题` | **工具名残留** |
| `agent/skills/__init__.py` | L17 | `需要使用技能时通过 use_skill(name) 工具调用加载完整指令。` | **工具名残留** |
| `agent/skills/__init__.py` | L22 | `use_skill 工具: LLM 主动加载技能指令` | **工具名残留** |
| `agent/skills/skill_tool.py` | L18 | `这与 nanobot 的"子 agent 隔离执行"有本质区别:` | docstring 对比说明（强调 Charles 不采用 nanobot 模式） |
| `agent/skills/registry.py` | L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 标题 |
| `agent/skills/registry.py` | L20-22 | `对标 nanobot:\n    - build_skills_summary(): XML 格式技能列表\n    - get_always_skills(): always=True 的技能` | docstring 对标说明 |
| `agent/skills/registry.py` | L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | class docstring 标题 |
| `agent/skills/registry.py` | L184 | `"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()` | 方法 docstring |
| `agent/skills/loader.py` | L2 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | docstring 标题 |
| `agent/skills/loader.py` | L29-31 | `对标 nanobot:\n    - agent/skills.py SkillsLoader: list_skills / load_skill / _parse_frontmatter\n    - PyYAML 解析 + fallback 简单解析` | docstring 对标说明 |
| `agent/skills/loader.py` | L48 | `"""技能元数据 — 对标 Cline frontmatter + nanobot metadata` | dataclass docstring |
| `agent/skills/loader.py` | L96 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | class docstring 标题 |
| `agent/skills/loader.py` | L167 | `对标 nanobot: load_skill() + _strip_frontmatter()` | 方法 docstring |
| `agent/skills/loader.py` | L222 | `"""解析 SKILL.md 文件 — 对标 nanobot get_skill_metadata()` | 方法 docstring |
| `agent/skills/loader.py` | L392 | `# Fallback: 简单 YAML 解析 — 对标 nanobot fallback` | 行内注释 |
| `agent/skills/loader.py` | L423 | `"""去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()` | 方法 docstring |

**注释残留小结**：
- `nanobot` 关键词：15 处，全部为 docstring/注释中的"对标"说明，用于标注设计来源和历史参考。
- `use_skill` 关键词：4 处（均在 `__init__.py`），**工具名残留**——实际工具名为 `skills`（skill_tool.py L77 `return "skills"`），但 `__init__.py` 的模块 docstring 仍用旧名 `use_skill` 指代该工具。此为历史命名残留，不影响运行时行为。

### 4.2 实现逻辑残留（0 处）

**逐项核查结果**：

| 检查项 | Cline 实现 | Charles 实现 | 残留判定 |
|--------|-----------|-------------|---------|
| 子 agent 创建 | 不创建 | 不创建（skill_tool.py L123 明确声明） | **无残留** |
| 工具集限制 | 无 | 无（SkillsTool 不读取 `allowed_tools` 字段） | **无残留** |
| attempt_completion 返回 | 不使用 | 不使用（skill_tool.py L22 注释明确不用） | **无残留** |
| 独立 runtime | 无 | 无 | **无残留** |
| 隔离执行语义 | 无（主上下文注入） | 无（主上下文注入） | **无残留** |

**`allowed_tools` 字段说明**：

`SkillMetadata.allowed_tools` 字段（loader.py L74）在 frontmatter 中解析（L236-266），但其概念源自 nanobot 子 agent 模型（"技能允许子 agent 使用的工具名列表"）。经 Grep 全局搜索确认，该字段**仅在 loader.py 中解析和存储，从未被 SkillsTool、SkillRegistry 或任何其他模块读取使用**。

```python
# loader.py L74 — 字段定义
allowed_tools: list[str] | None = None  # Phase 20: 子 agent 允许的工具列表

# loader.py L236-266 — frontmatter 解析
allowed_tools_raw = frontmatter.get("allowed_tools", None)
# ... 解析逻辑 ...

# 全局搜索结果：无任何模块读取 skill_meta.allowed_tools
```

**判定**：`allowed_tools` 是**未使用的 dead metadata**，概念上源自 nanobot 子 agent 模型，但因 Charles skills 工具不创建子 agent（对齐 Cline），该字段从未被实际使用。这不是"实现逻辑残留"（不影响运行时行为），属于"设计概念遗留的 dead code"。建议在未来清理中移除该字段或明确标注其用途。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（nanobot 对标说明） | 15 处 | 低 | 可保留作为设计溯源参考，或统一清理 |
| 注释残留（use_skill 工具名） | 4 处 | 中 | **建议修正**为 `skills`，避免误导 |
| 实现逻辑残留 | 0 处 | — | 无需处理 |
| dead metadata（allowed_tools） | 1 字段 | 低 | 建议移除或重新标注用途 |

---

## 五、修复建议

### 5.1 高优先级（P1）

无。核心机制已对齐，无阻塞性问题。

### 5.2 中优先级（P2）

1. **修正 `use_skill` 工具名残留**（`__init__.py` L13/L15/L17/L22）：将 docstring 中的 `use_skill` 统一改为 `skills`，与实际工具名对齐。

2. **补充 InputSchema 约束**（skill_tool.py L85-98）：
   - `skill` 字段添加 `"minLength": 1`
   - `args` 字段考虑添加 `"nullable": true` 或在描述中注明可选

3. **args trim 对齐**（skill_tool.py L130）：将 `args = input.get("args") or ""` 改为 `args = (input.get("args") or "").strip()`，与 Cline user-instruction-plugin.ts L194 的 `args?.trim()` 对齐，避免纯空白 args 生成无意义的 `<command-args>` 标签。

### 5.3 低优先级（P3）

4. **frontmatter toggle 写入功能**（loader.py 或新文件）：若需要运行时动态启用/禁用技能，可参考 Cline `skill-frontmatter-toggle.ts` 实现 `toggle_skill_frontmatter(path, enabled)` 函数。当前无此需求可暂不实现。

5. **`allowed_tools` dead metadata 清理**（loader.py L74/L236-266）：若确认不使用子 agent 工具集限制，可移除该字段及其解析逻辑，减少代码噪音。

6. **`configured_skills()` 方法对齐**（skill_tool.py L255-266）：当前 `disabled` 硬编码 `False`，且方法未被调用。若保留则应反映实际 disabled 状态（但 `list_skills()` 已过滤 disabled，返回值恒为 False，可接受）；若不需要可移除。

7. **nanobot 注释统一**（15 处）：可选择保留作为设计溯源，或统一清理为仅引用 Cline 对标位置。

---

## 六、验证方法建议

### 6.1 核心机制验证

1. **工具名一致性**：
   ```python
   from agent.skills.skill_tool import SkillsTool
   tool = SkillsTool(registry)
   assert tool.name == "skills"
   ```

2. **XML 返回格式一致性**：
   - 构造 mock registry，调用 `SkillsTool._execute({"skill": "test", "args": "arg1"}, context)`
   - 验证返回的 `output` 字符串匹配 `<command-name>test</command-name>\n<command-args>arg1</command-args>\n<command-instructions>\n...` 格式
   - 对比 Cline user-instruction-plugin.ts L202 的输出格式

3. **runningSkills 并发去重**：
   - 同一技能两次并发调用，第二次应返回 `Skill "..." is already running.`
   - 技能执行完成后，再次调用应正常执行（try/finally 释放验证）

4. **15s 超时验证**：
   - 构造一个加载缓慢的 SKILL.md（如 mock `load_instructions` 延迟 16s）
   - 调用 SkillsTool，验证 runtime 在 15s 后返回 is_error 超时结果

5. **白名单 4 形式匹配**：
   - 构造 `allowed_skill_names=["ms-office-suite:pdf"]`
   - 测试 `pdf`（bareName）、`ms-office-suite:pdf`（normalizedId）均能通过
   - 测试 `excel` 不在白名单中被过滤

### 6.2 nanobot 残留验证

1. **use_skill 注释残留**：
   ```
   Grep "use_skill" agent/skills/__init__.py
   ```
   预期：4 处匹配，均为 docstring 注释

2. **实现逻辑残留验证**：
   ```python
   # 确认 SkillsTool 不引用 allowed_tools
   import inspect
   from agent.skills.skill_tool import SkillsTool
   source = inspect.getsource(SkillsTool)
   assert "allowed_tools" not in source
   assert "attempt_completion" not in source
   assert "sub_agent" not in source.lower()
   ```

3. **dead metadata 验证**：
   ```
   Grep "allowed_tools" agent/ --type py
   ```
   预期：仅 loader.py 中定义和解析，无其他模块读取

### 6.3 计划表差距修复验证

1. **S1 差距（白名单 4 形式）已修复**：
   ```python
   from agent.skills.registry import _is_skill_allowed
   allowed = {"ms-office-suite:pdf"}
   # 4 形式均应返回 True
   assert _is_skill_allowed("ms-office-suite:pdf", "pdf", allowed)  # normalizedId + bareName
   assert _is_skill_allowed("pdf", "pdf", allowed)  # bareId + normalizedName
   ```

2. **S2 差距（skillsTimeoutMs 可配置）已修复**：
   ```python
   import os
   os.environ["AGENT_SKILLS_TIMEOUT_MS"] = "30000"
   # 重新初始化 server，验证 SkillsTool.timeout_ms == 30000
   ```
