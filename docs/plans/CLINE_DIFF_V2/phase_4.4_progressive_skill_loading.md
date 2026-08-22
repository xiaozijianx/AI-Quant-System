# Phase 4.4 渐进式技能加载对比（三级加载机制）

> 对比范围：Cline `extensions/config/user-instruction-plugin.ts` + `extensions/config/user-instruction-config-loader.ts` + `extensions/tools/definitions.ts` + `docs/customization/skills.mdx` 的渐进式三级加载（Metadata / Instructions / Resources）与 Charles `agent/skills/` 模块（`loader.py` + `registry.py` + `skill_tool.py`）+ `agent/context.py` 增强层的渐进式三级加载的实现差异。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`（SkillsExecutorWithMetadata — Level 2 指令注入 + runningSkills 去重 + disabled 拦截）
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L42-48（SkillConfig 接口 — Level 1 metadata 字段）+ L283-310（parseSkillConfigFromMarkdown — frontmatter 解析）
> - `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts`（toggleSkillFrontmatter — disabled 字段运行时写入）
> - `sdk/packages/core/src/extensions/tools/definitions.ts` L719-769（createSkillsTool — skills 工具工厂 + 15s 超时 + 动态 description）
> - `sdk/packages/core/src/extensions/tools/types.ts` L135-179（SkillsExecutor / SkillsExecutorWithMetadata / SkillsExecutorSkillMetadata 接口）
> - `docs/customization/skills.mdx` L17-23（三级加载机制说明表）
>
> Charles 源码：
> - `agent/skills/__init__.py`（模块导出 + 三级加载说明）
> - `agent/skills/loader.py`（SkillLoader + SkillMetadata — Level 1 + Level 2 + 脚本自动发现）
> - `agent/skills/registry.py`（SkillRegistry — list_skills / build_summary / load_instructions / get_always_skills / load_always_instructions）
> - `agent/skills/skill_tool.py`（SkillsTool — skills 工具实现 + 15s 超时 + runningSkills 去重 + Plan 模式拦截）
> - `agent/context.py` L304-343（_load_enhancements — 增强层开关）+ L611-647（_build_enhancement_rules — skills_summary / always_skills 段注入）

---

## 一、执行摘要

Cline 与 Charles 在渐进式技能加载机制上**整体对齐度高**，三级加载（Metadata / Instructions / Resources）的范式与 token 预算完全一致，但在 always 技能预加载、Level 3 资源自动发现、Skills 工具 description 暴露方式上存在差异：

1. **三级加载范式完全对齐**：
   - **Level 1 - Metadata**（启动时）：Cline 与 Charles 都仅加载 `name` + `description`（Charles 额外加载 `when_to_use` 用于摘要表格），~100 tokens/技能。
   - **Level 2 - Instructions**（触发时）：Cline 与 Charles 都通过 `skills` 工具触发，加载 SKILL.md 正文（去除 frontmatter），<5k tokens。
   - **Level 3 - Resources**（按需）：Cline 与 Charles 都通过 `read_file` / `run_commands` 工具加载 docs/templates/scripts，脚本只输出结果入上下文。

2. **关键架构差异**：

   | 维度 | Cline | Charles |
   |------|-------|---------|
   | Level 1 metadata 字段 | name + description（+ disabled） | name + description + when_to_use（+ disabled + always + keywords + capabilities + allowed_tools + scripts） |
   | Level 1 暴露方式 | 通过 `skills` 工具 description 的 `Available skills: ...` 后缀动态暴露 | 通过 `skills` 工具 description 后缀 + 可选增强层 `charles-skills-summary` rule 双通道暴露 |
   | Level 2 触发工具 | `skills` 工具（definitions.ts L734） | `skills` 工具（skill_tool.py L77） |
   | Level 2 超时 | 15000ms（definitions.ts L723） | 15000ms（skill_tool.py L56） |
   | Level 2 返回格式 | XML 包裹（`<command-name>` + `<command-args>` + `<command-instructions>`） | 完全对齐（skill_tool.py L201-207） |
   | Level 2 runningSkills 去重 | per-executor Set（user-instruction-plugin.ts L179） | per-tool Set（skill_tool.py L73） |
   | Level 3 脚本发现 | LLM 按 SKILL.md 引用自行 read_file/run_commands | **Charles 自动扫描** skill 目录下 .py 文件，路径列表注入 Level 2 指令末尾（loader.py L300-342 `_discover_scripts`） |
   | always 技能预加载 | **无此概念**（skills.mdx L9 明确："skills load on-demand"） | **Charles 独有**：`always: true` 的技能在启动时通过 `load_always_instructions` 预加载到 system prompt |
   | always 概念来源 | 无（Cline `alwaysEnabled` 是远程企业配置的"管理员锁定"标志，非 frontmatter 字段） | nanobot `get_always_skills()`（registry.py L184 docstring 明确标注） |
   | disabled 字段写入 | `toggleSkillFrontmatter` 支持运行时改写 SKILL.md frontmatter | 仅运行时读取，不支持运行时写入 |
   | 工具白名单 | `allowedSkillNames` 参数 + 4 形式匹配（normalizedId/normalizedName/bareId/bareName） | 完全对齐（registry.py L57-96 `_is_skill_allowed` 4 形式检查） |
   | Plan 模式拦截 | 无 | **Charles 独有**：Plan 模式下禁止调用 `write-report` 技能（skill_tool.py L138-150） |

3. **nanobot 残留**：P4.4 核心文件共 **15 处 nanobot 注释残留**（全部为 docstring/行内注释溯源引用），**1 处实现逻辑残留**（`always=True` 预加载机制源自 nanobot `get_always_skills()`，Cline 无对应实现）。另有 1 处 stale docstring（`__init__.py` L13 提及 `use_skill` 工具名，实际工具名为 `skills`）。

4. **一致性总体评估**：**中高**。三级加载核心机制（Level 1/2/3 + token 预算 + skills 工具 + XML 返回格式 + runningSkills 去重 + disabled 拦截 + 白名单 4 形式匹配）完全对齐；Charles 在 always 预加载（源自 nanobot）、Level 3 脚本自动发现、Plan 模式拦截三点上为独有扩展；Cline 在 disabled 字段运行时写入上独有。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.4.1 | Level 1 Metadata 字段 | name + description + disabled（SkillConfig L42-48） | name + description + when_to_use + disabled + always + keywords + capabilities + allowed_tools + scripts（SkillMetadata L46-81） | 中 | Charles 字段更丰富，when_to_use 为 Charles 额外（P5.2） |
| 4.4.2 | Level 1 token 预算 | ~100 tokens/技能（skills.mdx L21） | ~100 tokens/技能（__init__.py L5） | 高 | 已对齐 |
| 4.4.3 | Level 1 加载时机 | 启动时（watcher.getSnapshot，user-instruction-plugin.ts L80） | 启动时（SkillLoader.list_skills，loader.py L119） | 高 | 已对齐 |
| 4.4.4 | Level 1 暴露方式 | `skills` 工具 description 后缀 `Available skills: name1, name2`（definitions.ts L754-766） | `skills` 工具 description 后缀（skill_tool.py L245-249） + 可选增强层 `charles-skills-summary` rule（context.py L638-642） | 中 | Charles 双通道，Cline 单通道 |
| 4.4.5 | Level 1 frontmatter 解析 | YAML.parse + BOM 剥离 + CRLF 兼容（user-instruction-config-loader.ts L198-209） | PyYAML safe_load + BOM 剥离 + CRLF 兼容 + fallback 简单解析（loader.py L364-420） | 高 | Charles 多一层 fallback（源自 nanobot） |
| 4.4.6 | Level 2 Instructions 加载 | skills 工具触发，返回 SKILL.md body（user-instruction-plugin.ts L202） | skills 工具触发，返回 SKILL.md body 去除 frontmatter（skill_tool.py L188 + loader.py L159-184） | 高 | 已对齐 |
| 4.4.7 | Level 2 token 预算 | <5k tokens（skills.mdx L22） | <5k tokens（__init__.py L6） | 高 | 已对齐 |
| 4.4.8 | Level 2 触发工具名 | `skills`（definitions.ts L734） | `skills`（skill_tool.py L77） | 高 | 完全一致 |
| 4.4.9 | Level 2 输入 schema | `{skill: string, args?: string}`（SkillsInputSchema） | `{skill: string, args?: string}`（skill_tool.py L85-98） | 高 | 完全一致 |
| 4.4.10 | Level 2 返回格式 | `<command-name>{name}</command-name>\n<command-args>{args}</command-args>\n<command-instructions>\n{description}{instructions}\n</command-instructions>`（user-instruction-plugin.ts L202） | 完全一致（skill_tool.py L201-207） | 高 | 字节级对齐 |
| 4.4.11 | Level 2 超时 | 15000ms（definitions.ts L723 `skillsTimeoutMs ?? 15000`） | 15000ms（skill_tool.py L56 `skills_timeout_ms: int = 15000`） | 高 | 完全一致 |
| 4.4.12 | Level 2 runningSkills 去重 | per-executor `Set<string>`（user-instruction-plugin.ts L179） | per-tool `set[str]`（skill_tool.py L73） | 高 | 语义等价 |
| 4.4.13 | runningSkills key | skill id（user-instruction-plugin.ts L188 `runningSkills.has(id)`） | `_normalize_skill_token(skill_name)`（skill_tool.py L176） | 高 | Charles 用规范化名作 key |
| 4.4.14 | runningSkills 重复时返回 | `Skill "${name}" is already running.`（user-instruction-plugin.ts L189） | `Skill "{skill_name}" is already running.`（skill_tool.py L179） | 高 | 字面量对齐（仅引号差异） |
| 4.4.15 | runningSkills 释放 | `finally { runningSkills.delete(id); }`（user-instruction-plugin.ts L203-205） | `finally: self._running_skills.discard(skill_id)`（skill_tool.py L219-223） | 高 | 完全对齐 |
| 4.4.16 | Level 3 Resources 加载方式 | read_file（docs/templates）+ run_commands（scripts），仅输出入上下文（skills.mdx L23, L223） | 完全一致：read_files + run_commands（脚本输出入上下文，代码不入） | 高 | 已对齐 |
| 4.4.17 | Level 3 脚本路径发现 | LLM 按 SKILL.md 引用自行调用（skills.mdx L213-221） | **Charles 自动扫描** skill 目录下 .py 文件，路径列表注入 Level 2 指令末尾（loader.py L300-342 `_discover_scripts`） | 中 | Charles 额外扩展（Phase 33.4） |
| 4.4.18 | Level 3 脚本路径注入格式 | 无（依赖 LLM 读 SKILL.md 引用） | `## 可用脚本（可直接复制执行）\n- \`python {path}\``（loader.py L199-212） | 中 | Charles 独有 |
| 4.4.19 | always 技能预加载 | **无**（skills.mdx L9 明确："skills load on-demand"，与 rules 区分） | **Charles 独有**：`always: true` 的技能在启动时通过 `load_always_instructions` 预加载（registry.py L183-208） | 低 | Charles 概念源自 nanobot（见 4.4.30） |
| 4.4.20 | always 段注入位置 | 无 | system prompt 增强层 `charles-always-skills` rule（context.py L632-636） | 低 | Charles 独有 |
| 4.4.21 | always 段开关 | 无 | `enhancements.always_skills` 配置项（context.py L312, L632） | 低 | Charles 独有 |
| 4.4.22 | always 段拼接格式 | 无 | `### 技能: {name}\n\n{instructions}` 多技能用 `\n\n---\n\n` 分隔（registry.py L202-208） | 低 | Charles 独有 |
| 4.4.23 | disabled 字段读取 | `data.disabled ?? (data.enabled === false)`（user-instruction-config-loader.ts L304-306） | `frontmatter.get("disabled", False)` + `frontmatter.get("enabled", True) is False`（loader.py L239-241） | 高 | 完全对齐（双写法兼容） |
| 4.4.24 | disabled 工具调用拦截 | 返回 `Skill "${name}" is configured but disabled.`（user-instruction-plugin.ts L123-127） | 返回 `Skill "{skill_name}" is configured but disabled.`（skill_tool.py L163-170） | 高 | 字面量对齐 |
| 4.4.25 | disabled 在 list 中过滤 | `listAvailableSkillNames` 中 `.filter((skill) => !skill.disabled)`（user-instruction-plugin.ts L100） | `list_skills` 中 `[s for s in all_skills if not s.disabled]`（registry.py L157） | 高 | 完全对齐 |
| 4.4.26 | disabled 字段运行时写入 | `toggleSkillFrontmatter` 支持运行时改写 SKILL.md（skill-frontmatter-toggle.ts L76-89） | **未实现**（仅运行时读取） | 低 | **Charles 缺失** |
| 4.4.27 | 工具白名单机制 | `allowedSkillNames` + `toAllowedSkillSet` + `isSkillAllowed` 4 形式匹配（user-instruction-plugin.ts L39-73） | 完全对齐：`_to_allowed_skill_set` + `_is_skill_allowed` 4 形式匹配（registry.py L41-96） | 高 | 字段名映射 + 4 形式检查完全一致 |
| 4.4.28 | skills 工具 description 动态化 | `Object.defineProperty(tool, "description", { get() { ... })`（definitions.ts L754-766） | `_build_description()` 方法在 `description` property 中调用（skill_tool.py L80-81, L225-253） | 高 | 语义等价（getter vs property 方法） |
| 4.4.29 | skills 工具 retryable | `retryable: false, maxRetries: 0`（definitions.ts L738-739） | 默认 BaseTool 行为（未显式覆盖） | 中 | Charles 未显式禁用重试，但 skills 工具无副作用，重试无害 |
| 4.4.30 | always 预加载概念来源 | 无（Cline 无 always frontmatter 字段处理逻辑） | nanobot `get_always_skills()`（registry.py L184 docstring 明确标注） | 低 | **nanobot 实现逻辑残留** |
| 4.4.31 | fallback YAML 解析来源 | 无（Cline 仅用 YAML.parse，失败抛错） | nanobot fallback 简单解析（loader.py L392 注释明确标注） | 中 | nanobot 实现逻辑残留（防御性，无害） |
| 4.4.32 | Plan 模式技能拦截 | 无 | Plan 模式下禁止调用 `write-report` 技能（skill_tool.py L138-150） | 低 | Charles 独有扩展 |
| 4.4.33 | skills_summary 段格式 | 无（Cline 通过工具 description 暴露） | Markdown 列表：`- {name} ({when_to_use}): {desc}`（registry.py L210-252） | 中 | Charles 独有增强层 |
| 4.4.34 | 多目录 skills 加载 | 多源聚合：用户级 + 项目级 + 插件级，按 owner 去重（user-instruction-config-loader.ts L528+） | `load_skills_multi_dir` 多目录加载，靠后目录覆盖靠前（loader.py L443-485） | 中 | Charles 简化版（无 owner 去重） |
| 4.4.35 | skills 工具 read_only | 未显式标注 | `read_only = True`（skill_tool.py L100-102） | 中 | Charles 显式标注（仅加载指令，无副作用） |

**一致性总评**：35 项中，高一致性 19 项、中一致性 11 项、低一致性 5 项。低一致性项集中在 always 预加载（Charles 独有 + nanobot 溯源）、disabled 运行时写入（Charles 缺失）、Plan 模式拦截（Charles 独有）。

---

## 三、重点差距详细说明

### 差距 1：always 技能预加载 — Charles 独有 + nanobot 溯源（4.4.19 / 4.4.20 / 4.4.21 / 4.4.22 / 4.4.30）

**Cline 实现**：

Cline **无 always 技能预加载概念**。`skills.mdx` L9 明确说明：

> Unlike rules (which are always active), skills load on-demand so they don't consume context when you're working on something unrelated.

Cline 的 SkillConfig 接口（user-instruction-config-loader.ts L42-48）仅包含 `name / description / disabled / instructions / frontmatter`，无 `always` 字段。grep 全量搜索 `always.*skill|skill.*always` 在 Cline 源码中无匹配（Cline 的 `alwaysEnabled` 是远程企业配置的"管理员锁定"标志，file.proto L310 注释 `// Whether the skill is always enabled (remote only, user cannot toggle off)`，与 frontmatter `always` 字段无关）。

**Charles 实现**（registry.py L183-208 + context.py L632-636）：

```python
def get_always_skills(self) -> list[str]:
    """获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()"""
    if not self._skills:
        self.discover()
    return [name for name, meta in self._skills.items() if meta.always]

def load_always_instructions(self) -> str:
    always_names = self.get_always_skills()
    if not always_names:
        return ""
    parts: list[str] = []
    for name in always_names:
        instructions = self.load_instructions(name)
        if instructions:
            parts.append(f"### 技能: {name}\n\n{instructions}")
    return "\n\n---\n\n".join(parts) if parts else ""
```

`always=True` 的技能在启动时通过 `load_always_instructions` 预加载到 system prompt 的 `charles-always-skills` rule 段（context.py L632-636），LLM 无需调用 `skills` 工具即可看到指令。

**nanobot 溯源**：

registry.py L184 docstring 明确标注：`"""获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()``。loader.py L70 SkillMetadata 字段 `always: bool = False` 是 frontmatter `always` 字段的解析结果，整个 always 预加载链路（frontmatter 解析 → get_always_skills → load_always_instructions → system prompt 注入）源自 nanobot，非 Cline 移植。

**影响**：

- Charles 的 always 预加载会**常驻消耗 system prompt token**（每个 always 技能 ~5k tokens），与 Cline "skills load on-demand" 设计哲学相悖。
- 适用于"必须始终生效"的技能（如安全规则、品牌口径），但滥用会导致 context 膨胀。
- Charles 通过 `enhancements.always_skills` 开关（默认关闭，context.py L312）控制是否启用，与 Cline 默认行为对齐。

**建议**：保留，但建议在文档中明确"always 字段源自 nanobot，Cline 无对应实现"，避免后续维护者误以为是对齐 Cline 的设计。

### 差距 2：Level 3 脚本自动发现 — Charles 独有扩展（4.4.17 / 4.4.18）

**Cline 实现**：

Cline 不自动扫描脚本。`skills.mdx` L213-221 说明 LLM 按 SKILL.md 中的引用自行调用：

```markdown
For initial setup, follow [setup.md](docs/setup.md).
Use the config template at `templates/config.yaml` as a starting point.
Run the validation script to check your configuration:

python scripts/validate.py
```

LLM 看到 SKILL.md 中的 `python scripts/validate.py` 引用后，通过 `run_commands` 工具执行，仅脚本输出入上下文（skills.mdx L209：`only their output enters context, not the code itself`）。

**Charles 实现**（loader.py L300-342）：

`_discover_scripts` 递归扫描 skill 目录下所有 `.py` 文件（排除 `__pycache__` 和隐藏文件），返回相对项目根目录的完整路径列表。`load_instructions` 在返回 Level 2 指令时自动追加脚本路径块（loader.py L176-182）：

```python
scripts = self._get_skill_scripts(name)
if scripts:
    scripts_block = self._build_scripts_block(scripts, skill_file.parent)
    if scripts_block:
        instructions = f"{instructions}\n\n{scripts_block}"
```

输出格式（loader.py L209-211）：

```markdown
## 可用脚本（可直接复制执行）
- `python agent_config/skills/stock-price/scripts/get_kline.py`
```

**影响**：

- Charles 的自动发现降低了 SKILL.md 作者的负担（无需手动维护脚本列表），但与 Cline 的"LLM 按 SKILL.md 引用自行调用"设计不同。
- Charles 自动发现的脚本路径是**完整相对路径**（如 `agent_config/skills/stock-price/scripts/get_kline.py`），LLM 可直接复制执行；Cline 依赖 SKILL.md 作者写明完整命令。
- 若 SKILL.md 未引用某脚本但脚本存在于目录下，Charles 仍会列出（可能引入噪音）；Cline 不会（LLM 看不到）。

**建议**：保留，是 Charles 的合理增强（Phase 33.4），降低用户维护成本。

### 差距 3：disabled 字段运行时写入 — Charles 缺失（4.4.26）

**Cline 实现**（skill-frontmatter-toggle.ts L51-89）：

`toggleSkillFrontmatter({filePath, enabled})` 支持运行时改写 SKILL.md 的 frontmatter：

- `enabled: true` 时删除 `disabled` 字段（若 `enabled: false` 也删除），frontmatter 空则整体移除。
- `enabled: false` 时设置 `disabled: true`。
- 通过 `readFile` + `writeFile` 原子写入。

UI 层调用此函数实现"技能开关"功能（skills.mdx L93-97：Every skill has a toggle to enable or disable it）。

**Charles 实现**：

Charles 仅支持运行时读取 `disabled` 字段（loader.py L239-241），不支持运行时写入。禁用技能需手动编辑 SKILL.md 的 frontmatter。

**影响**：

- Charles 无 UI 层"技能开关"功能，用户必须编辑 SKILL.md 才能禁用技能。
- Charles 的 disabled 过滤在 list_skills（registry.py L157）和 SkillsTool（skill_tool.py L163-170）两层生效，功能上等价。

**建议**：不强制补齐。Charles 是 CLI 工具，无 UI 层开关需求。手动编辑 frontmatter 已能满足需求。

### 差距 4：Plan 模式技能拦截 — Charles 独有扩展（4.4.32）

**Cline 实现**：无 Plan 模式拦截逻辑。

**Charles 实现**（skill_tool.py L138-150）：

```python
if skill_name == "write-report" and context.session_id is not None:
    from agent.state import get_mode
    if get_mode(context.session_id) == "plan":
        return AgentToolResult(
            output={
                "error": 'Plan 模式下禁止调用 write-report。'
                '请在 Act 模式下执行此技能，或先切换到 Act 模式。'
            },
            is_error=True,
        )
```

Plan 模式下禁止调用 `write-report` 技能，避免 Plan 模式被当作 Act 模式直接生成最终产物。

**影响**：

- Charles 独有的业务逻辑，与 Cline 的通用 skills 工具不同。
- 仅对 `write-report` 技能生效，其他技能不受影响。

**建议**：保留，是 Charles 业务场景特定的扩展。

### 差距 5：Level 1 暴露方式 — Charles 双通道（4.4.4 / 4.4.33）

**Cline 实现**（definitions.ts L754-766）：

Level 1 metadata 通过 `skills` 工具的 description 动态后缀暴露：

```typescript
Object.defineProperty(tool, "description", {
    get() {
        const skills = executor.configuredSkills
            ?.filter((s) => !s.disabled)
            .map((s) => s.name);
        if (skills && skills.length > 0) {
            return `${baseDescription} Available skills: ${skills.join(", ")}.`;
        }
        return baseDescription;
    },
});
```

LLM 在工具列表中看到 `skills` 工具的 description 末尾有 `Available skills: name1, name2, ...`，据此判断是否调用。Cline **不在 system prompt 中预注入技能清单**。

**Charles 实现**（skill_tool.py L225-253 + context.py L638-642）：

Charles **双通道**暴露：

1. **通道 1**（默认开启）：`skills` 工具 description 后缀 `可用技能: name1, name2, ...`（skill_tool.py L249），与 Cline 完全对齐。
2. **通道 2**（默认关闭，需 `enhancements.skills_summary=true`）：system prompt 增强层 `charles-skills-summary` rule（context.py L638-642），注入 Markdown 列表格式：

```markdown
# 技能目录（这些不是可直接调用的工具，需先调用 skills 工具加载详细指令）

当用户任务与某个技能匹配时，你必须先调用 skills 工具加载该技能指令，然后严格按照指令执行。

- write-report (何时使用): 按照国泰君安五步法撰写深度分析研报
- financial-analysis (何时使用): 财务指标分析
```

**影响**：

- Charles 的通道 2 在 `enhancements.enabled=true` 时启用，提供更详细的技能描述（含 `when_to_use` 列）。
- 通道 2 会常驻消耗 system prompt token（~100 tokens/技能），与 Cline 默认行为不同。
- Charles 默认关闭通道 2（context.py L320 `enabled: False`），与 Cline 默认行为对齐。

**建议**：保留双通道设计。通道 1 与 Cline 对齐，通道 2 是 Charles 的可选增强（默认关闭，不破坏 Cline 兼容性）。

---

## 四、nanobot 残留检查

针对 P4.4 核心文件执行 `grep -ri "nanobot"` 扫描，区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑源自 nanobot）。

### 4.1 P4.4 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/skills/__init__.py` | **2** | 注释残留 | L2 docstring `对标 Cline skills + nanobot SkillsLoader`；L23 docstring `对标 nanobot: agent/skills.py: SkillsLoader 类...` |
| `agent/skills/loader.py` | **8** | 注释残留 + 1 处实现逻辑残留 | 见 4.2 详述 |
| `agent/skills/registry.py` | **4** | 注释残留 + 1 处实现逻辑残留 | 见 4.3 详述 |
| `agent/skills/skill_tool.py` | **1** | 注释残留 | L18 docstring `这与 nanobot 的"子 agent 隔离执行"有本质区别` |
| `agent/context.py`（skills 相关段） | **0** | 无 | 增强层段落无 nanobot 引用 |

### 4.2 loader.py 残留详述

#### 注释残留（7 处）

| 行号 | 内容 | 类型 |
|------|------|------|
| L2 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | docstring 溯源 |
| L29-31 | `对标 nanobot: agent/skills.py SkillsLoader: list_skills / load_skill / _parse_frontmatter; PyYAML 解析 + fallback 简单解析` | docstring 溯源 |
| L48 | `"""技能元数据 — 对标 Cline frontmatter + nanobot metadata` | docstring 溯源 |
| L96 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | docstring 溯源 |
| L167 | `对标 nanobot: load_skill() + _strip_frontmatter()` | docstring 溯源 |
| L222 | `"""解析 SKILL.md 文件 — 对标 nanobot get_skill_metadata()` | docstring 溯源 |
| L423 | `"""去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()` | docstring 溯源 |

#### 实现逻辑残留（1 处）

| 行号 | 内容 | 类型 | 说明 |
|------|------|------|------|
| L392 | `# Fallback: 简单 YAML 解析 — 对标 nanobot fallback` + L393-420 简单 YAML 解析实现 | 实现逻辑残留 | Cline 仅用 `YAML.parse`（user-instruction-config-loader.ts L289），失败抛错；Charles 的 fallback 简单解析（按行 split + 键值对解析）源自 nanobot。**防御性代码，无害**：PyYAML 失败时启用，提升鲁棒性。 |

### 4.3 registry.py 残留详述

#### 注释残留（3 处）

| 行号 | 内容 | 类型 |
|------|------|------|
| L2 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 溯源 |
| L20 | `对标 nanobot: build_skills_summary(): XML 格式技能列表` | **stale docstring**（见 4.4 详述） |
| L100 | `"""技能注册表 — 对标 Cline skills registry + nanobot SkillsLoader` | docstring 溯源 |

#### 实现逻辑残留（1 处）

| 行号 | 内容 | 类型 | 说明 |
|------|------|------|------|
| L183-191 | `get_always_skills()` 方法实现 | 实现逻辑残留 | Cline 无 always 预加载概念（skills.mdx L9 明确 skills load on-demand），Charles 的 `always=True` 预加载机制源自 nanobot `get_always_skills()`，L184 docstring 明确标注。**功能保留**：Charles 业务场景需要常驻技能（如安全规则），非缺陷。 |

### 4.4 stale docstring 详述

| 文件 | 行号 | 内容 | 问题 |
|------|------|------|------|
| `agent/skills/registry.py` | L20 | `对标 nanobot: build_skills_summary(): XML 格式技能列表` | **stale**：实际 `build_summary()`（L210-252）返回 Markdown 列表格式，非 XML 格式。docstring 描述与实现不符。 |
| `agent/skills/__init__.py` | L13 | `SkillTool: use_skill 工具，LLM 通过 tool_call 加载技能指令` | **stale**：实际工具名为 `skills`（skill_tool.py L77），非 `use_skill`。docstring 描述与实现不符。 |

### 4.5 残留分类汇总

#### 注释残留（13 处）

P4.4 核心文件中**13 处 nanobot 注释残留**，全部为 docstring/行内注释溯源引用，标注"对标 nanobot"或"对标 Cline + nanobot"。这些残留**不影响功能**，仅是历史溯源信息。

#### 实现逻辑残留（2 处）

P4.4 核心文件中**2 处 nanobot 实现逻辑残留**：

1. **`loader.py` L392-420 fallback 简单 YAML 解析**：源自 nanobot fallback，Cline 无对应实现。**防御性代码，无害**，PyYAML 失败时启用，提升鲁棒性。建议保留。
2. **`registry.py` L183-208 always 预加载机制**：`get_always_skills` + `load_always_instructions` 源自 nanobot，Cline 无对应实现。**业务功能，建议保留**，Charles 需要常驻技能场景。

### 4.6 P4.4 范围外但相关的 nanobot 残留

P4.4 核心文件扫描已完成，无范围外残留需处理。`agent/context.py` 的增强层段落（L304-343, L611-647）无 nanobot 引用。

---

## 五、修复建议

### 建议 1：保留 always 预加载机制 [P0 不变]

**理由**：

- Charles 的 `always=True` 预加载机制源自 nanobot，但满足业务需求（常驻安全规则、品牌口径等）。
- 通过 `enhancements.always_skills` 开关（默认关闭）控制启用，与 Cline 默认行为（on-demand）对齐。
- always 技能会常驻消耗 system prompt token（~5k tokens/技能），但由用户显式声明 `always: true` 才生效，非默认行为。

**保留条件**：建议在 `registry.py` L184 docstring 中补充说明"always 字段源自 nanobot，Cline 无对应实现（Cline skills 均 on-demand）"，避免后续维护者误解。

### 建议 2：保留 fallback 简单 YAML 解析 [P0 不变]

**理由**：

- fallback 解析源自 nanobot，但**防御性代码，无害**：PyYAML 失败时启用，提升鲁棒性。
- Cline 仅用 `YAML.parse` 失败抛错，Charles 的 fallback 是增强，非缺陷。
- fallback 实现简单（按行 split + 键值对解析），维护成本低。

**保留条件**：若未来 PyYAML 依赖稳定性问题解决，可考虑移除 fallback。当前保留。

### 建议 3：清理 stale docstring [P3 可选]

**理由**：

- `registry.py` L20 描述 `build_skills_summary(): XML 格式技能列表`，实际实现是 Markdown 列表。
- `__init__.py` L13 描述 `use_skill 工具`，实际工具名是 `skills`。

**修复方案**：

- `registry.py` L20：改为 `对标 Cline skills 概览（列表形式）`，移除 nanobot XML 格式描述。
- `__init__.py` L13：改为 `SkillsTool: skills 工具，LLM 通过 tool_call 加载技能指令`。

**优先级**：P3（不影响功能，仅文档准确性）。

### 建议 4：不强制补齐 disabled 字段运行时写入 [P4 不修复]

**理由**：

- Charles 是 CLI 工具，无 UI 层"技能开关"功能需求。
- 手动编辑 SKILL.md frontmatter 已能满足禁用需求。
- 运行时写入需要文件锁 + 原子写，增加复杂度。

**保留条件**：若未来 Charles 引入 Web UI 层技能管理功能，可参考 Cline `skill-frontmatter-toggle.ts` 实现。

### 建议 5：保留 Level 3 脚本自动发现 [P0 不变]

**理由**：

- Charles 的 `_discover_scripts`（Phase 33.4）降低 SKILL.md 作者维护成本，是合理增强。
- 自动发现的脚本路径是完整相对路径，LLM 可直接复制执行。
- 与 Cline 的"LLM 按 SKILL.md 引用自行调用"设计不同，但功能等价（都能让 LLM 找到脚本）。

**保留条件**：若未来发现自动发现引入噪音（如 SKILL.md 未引用的脚本被列出），可考虑改为"仅列出 SKILL.md 中引用的脚本"。

### 建议 6：保留 Plan 模式技能拦截 [P0 不变]

**理由**：

- Charles 独有的业务逻辑，避免 Plan 模式被当作 Act 模式直接生成最终产物。
- 仅对 `write-report` 技能生效，不影响其他技能。
- 是 Charles Plan/Act 模式分离设计的必要补充。

### 建议 7：保留双通道 Level 1 暴露 [P0 不变]

**理由**：

- 通道 1（`skills` 工具 description 后缀）与 Cline 完全对齐。
- 通道 2（`charles-skills-summary` rule）是可选增强，默认关闭，不破坏 Cline 兼容性。
- 通道 2 启用时提供更详细的技能描述（含 `when_to_use` 列），适合技能数较多的场景。

---

## 六、验证方法建议

### 验证方法 1：三级加载机制验证

确认 Charles 的三级加载与 Cline 对齐：

```powershell
# Charles 侧：确认三级加载说明
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\__init__.py" -Pattern "Metadata|Instructions|Resources|100 tokens|5k tokens"
# 预期：三级加载说明 + token 预算

# Cline 侧：确认三级加载说明
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\docs\customization\skills.mdx" -Pattern "Metadata|Instructions|Resources|100 tokens|5k tokens"
# 预期：三级加载说明 + token 预算
```

### 验证方法 2：Level 2 返回格式字节级对齐验证

确认 Charles 的 skills 工具返回格式与 Cline 完全一致：

```powershell
# Charles 侧：确认 XML 返回格式
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\skill_tool.py" -Pattern "command-name|command-args|command-instructions"
# 预期：3 个 XML 标签

# Cline 侧：确认 XML 返回格式
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-plugin.ts" -Pattern "command-name|command-args|command-instructions"
# 预期：3 个 XML 标签
```

### 验证方法 3：runningSkills 去重机制验证

确认 Charles 的 runningSkills 去重与 Cline 语义等价：

```powershell
# Charles 侧：确认 runningSkills Set + 重复提示 + finally 释放
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\skill_tool.py" -Pattern "_running_skills|already running|discard"
# 预期：set[str] + "already running" 提示 + finally discard

# Cline 侧：确认 runningSkills Set + 重复提示 + finally 释放
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-plugin.ts" -Pattern "runningSkills|already running|delete"
# 预期：Set<string> + "already running" 提示 + finally delete
```

### 验证方法 4：always 预加载 Charles 独有验证

确认 Cline 无 always 预加载，Charles 独有：

```powershell
# Cline 侧：确认无 always 预加载逻辑（预期 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-plugin.ts" -Pattern "always|preload|loadAlways"
# 预期：0 匹配

# Charles 侧：确认 always 预加载实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\registry.py" -Pattern "get_always_skills|load_always_instructions"
# 预期：2 个方法定义
```

### 验证方法 5：Level 3 脚本自动发现验证

确认 Charles 的脚本自动发现是独有扩展：

```powershell
# Charles 侧：确认 _discover_scripts 实现
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "_discover_scripts|_build_scripts_block|可用脚本"
# 预期：方法定义 + 脚本块构建 + 中文标题

# Cline 侧：确认无自动发现逻辑（预期 0 匹配）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-config-loader.ts" -Pattern "discover|scripts|auto.*scan"
# 预期：0 匹配
```

### 验证方法 6：disabled 字段双写法兼容验证

确认 Charles 与 Cline 都支持 `disabled: true` 和 `enabled: false` 两种写法：

```powershell
# Charles 侧：确认双写法兼容
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "disabled|enabled"
# 预期：L239 disabled + L240-241 enabled is False

# Cline 侧：确认双写法兼容
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-config-loader.ts" -Pattern "disabled|enabled"
# 预期：L304 disabled + L305 enabled === false
```

### 验证方法 7：工具白名单 4 形式匹配验证

确认 Charles 与 Cline 的工具白名单 4 形式匹配逻辑对齐：

```powershell
# Charles 侧：确认 4 形式检查
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\registry.py" -Pattern "normalized_id|normalized_name|bare_id|bare_name|allowed_skills"
# 预期：4 个变量 + 4 个 in 检查

# Cline 侧：确认 4 形式检查
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-plugin.ts" -Pattern "normalizedId|normalizedName|bareId|bareName|allowedSkills"
# 预期：4 个变量 + 4 个 has 检查
```

### 验证方法 8：skills 工具超时验证

确认 Charles 与 Cline 的 skills 工具超时一致：

```powershell
# Charles 侧：确认 15000ms 超时
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\skill_tool.py" -Pattern "15000|skills_timeout_ms"
# 预期：默认 15000

# Cline 侧：确认 15000ms 超时
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\tools\definitions.ts" -Pattern "15000|skillsTimeoutMs"
# 预期：skillsTimeoutMs ?? 15000
```

### 验证方法 9：nanobot 残留扫描

```powershell
# P4.4 核心文件扫描（预期 15 处注释 + 实现残留）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\*.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期：__init__.py 2 处 + loader.py 8 处 + registry.py 4 处 + skill_tool.py 1 处 = 15 处
```

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L14-23 | SkillsExecutorMetadataItem / ConfiguredSkill 类型 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L35-49 | normalizeSkillToken + toAllowedSkillSet |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L51-73 | isSkillAllowed — 4 形式匹配 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L75-93 | getConfiguredSkillsFromWatcher — Level 1 metadata 提取 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L95-104 | listAvailableSkillNames — disabled 过滤 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L106-172 | resolveSkillRecord — 技能名解析 + disabled 错误提示 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L174-217 | createUserInstructionSkillsExecutor — Level 2 加载 + runningSkills 去重 + XML 返回格式 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L219-277 | createUserInstructionPlugin — 插件注册入口 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L42-48 | SkillConfig 接口（name + description + disabled + instructions + frontmatter） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L198-209 | parseMarkdownFrontmatter — BOM 剥离 + CRLF 兼容 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L283-310 | parseSkillConfigFromMarkdown — frontmatter 解析 + disabled 双写法兼容 |
| `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L22-41 | parseMarkdownFrontmatter（局部实现） |
| `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L51-74 | updateSkillMarkdownEnabledState — disabled 字段运行时改写 |
| `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L76-89 | toggleSkillFrontmatter — readFile + writeFile 原子写入 |
| `sdk/packages/core/src/extensions/tools/definitions.ts` | L719-769 | createSkillsTool — skills 工具工厂 + 15s 超时 + 动态 description getter |
| `sdk/packages/core/src/extensions/tools/types.ts` | L135-139 | SkillsExecutor 类型 |
| `sdk/packages/core/src/extensions/tools/types.ts` | L158-167 | SkillsExecutorSkillMetadata 接口 |
| `sdk/packages/core/src/extensions/tools/types.ts` | L172-179 | SkillsExecutorWithMetadata 接口 |
| `docs/customization/skills.mdx` | L17-23 | 三级加载机制说明表（Metadata / Instructions / Resources） |
| `docs/customization/skills.mdx` | L9 | "skills load on-demand" 设计哲学（与 rules 区分） |
| `docs/customization/skills.mdx` | L213-221 | Level 3 资源引用方式（LLM 按 SKILL.md 引用自行调用） |
| `docs/customization/skills.mdx` | L93-97 | 技能开关（toggle）功能说明 |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/skills/__init__.py` | L1-37 | 模块导出 + 三级加载说明（含 stale docstring L13） |
| `agent/skills/loader.py` | L46-81 | SkillMetadata dataclass（Level 1 字段集合） |
| `agent/skills/loader.py` | L84-92 | _strip_utf8_bom — BOM 剥离 |
| `agent/skills/loader.py` | L95-117 | SkillLoader 构造 + _cache 字段 |
| `agent/skills/loader.py` | L119-144 | list_skills — 扫描 skills 目录 + SKILL.md 解析 |
| `agent/skills/loader.py` | L146-157 | get_skill — 单技能元数据查询 |
| `agent/skills/loader.py` | L159-184 | load_instructions — Level 2 加载 + 脚本块追加 |
| `agent/skills/loader.py` | L186-212 | _get_skill_scripts + _build_scripts_block — Level 3 脚本路径块构建 |
| `agent/skills/loader.py` | L221-298 | _parse_skill_file — frontmatter 解析 + disabled 双写法 + when_to_use |
| `agent/skills/loader.py` | L300-342 | _discover_scripts — Level 3 脚本自动发现（Charles 独有） |
| `agent/skills/loader.py` | L344-362 | _find_project_root — 项目根目录查找 |
| `agent/skills/loader.py` | L364-420 | _parse_frontmatter — PyYAML + fallback 简单解析（nanobot 残留） |
| `agent/skills/loader.py` | L422-434 | _strip_frontmatter — 去除 frontmatter |
| `agent/skills/loader.py` | L443-485 | load_skills_multi_dir — 多目录加载 + override 解析 |
| `agent/skills/loader.py` | L488-508 | load_skills_with_dirs — primary_dir 优先级最高封装 |
| `agent/skills/registry.py` | L33-38 | _normalize_skill_token — 规范化技能名 |
| `agent/skills/registry.py` | L41-54 | _to_allowed_skill_set — 白名单集合转换 |
| `agent/skills/registry.py` | L57-96 | _is_skill_allowed — 4 形式匹配 |
| `agent/skills/registry.py` | L99-158 | SkillRegistry 构造 + discover + list_skills（白名单 + disabled 过滤） |
| `agent/skills/registry.py` | L160-174 | get_skill — 单技能查询（disabled 不过滤） |
| `agent/skills/registry.py` | L176-181 | load_instructions — Level 2 加载委托 |
| `agent/skills/registry.py` | L183-191 | get_always_skills — always 技能列表（nanobot 实现逻辑残留） |
| `agent/skills/registry.py` | L193-208 | load_always_instructions — always 技能指令拼接 |
| `agent/skills/registry.py` | L210-252 | build_summary — Level 1 摘要（Markdown 列表 + when_to_use） |
| `agent/skills/registry.py` | L254-263 | build_summary_as_rule — rule 格式包装 |
| `agent/skills/registry.py` | L265-270 | build_tool_hint — 返回 None |
| `agent/skills/registry.py` | L272-285 | load_always_instructions_as_rule — always 段 rule 包装 |
| `agent/skills/registry.py` | L287-292 | has_skill — 技能存在性检查 |
| `agent/skills/skill_tool.py` | L38-73 | SkillsTool 类 + running_skills Set |
| `agent/skills/skill_tool.py` | L75-114 | name/description/input_schema/read_only/timeout_ms 属性 |
| `agent/skills/skill_tool.py` | L116-223 | _execute — Level 2 加载主逻辑（Plan 拦截 + disabled 拦截 + runningSkills 去重 + XML 返回） |
| `agent/skills/skill_tool.py` | L225-253 | _build_description — 动态 description + Available skills 后缀 |
| `agent/skills/skill_tool.py` | L255-267 | configured_skills — 元数据列表导出 |
| `agent/context.py` | L304-343 | _load_enhancements — 增强层开关（skills_summary + always_skills） |
| `agent/context.py` | L611-647 | _build_enhancement_rules — charles-skills-summary + charles-always-skills rule 注入 |

---

## 八、结论

P4.4 渐进式技能加载对比的核心结论：

1. **三级加载范式完全对齐**：Cline 与 Charles 都采用 Metadata（~100 tokens，启动时）→ Instructions（<5k tokens，触发时）→ Resources（按需）的渐进式加载机制。Level 1 字段、Level 2 触发工具名（`skills`）、Level 2 返回格式（XML 三标签）、Level 2 超时（15000ms）、Level 2 runningSkills 去重、Level 3 加载方式（read_file/run_commands）均字节级或语义级对齐。

2. **Charles 在三点上为独有扩展**（非缺陷）：
   - **always 技能预加载**（registry.py L183-208）：源自 nanobot，Cline 无对应实现。通过 `enhancements.always_skills` 开关（默认关闭）控制，不破坏 Cline 兼容性。
   - **Level 3 脚本自动发现**（loader.py L300-342）：Charles 独有增强（Phase 33.4），降低 SKILL.md 作者维护成本。
   - **Plan 模式技能拦截**（skill_tool.py L138-150）：Charles 独有业务逻辑，避免 Plan 模式被当作 Act 模式。

3. **Cline 在一点上独有**（Charles 缺失，建议不修复）：
   - **disabled 字段运行时写入**（skill-frontmatter-toggle.ts）：Cline 支持运行时改写 SKILL.md frontmatter 实现 UI 层技能开关；Charles 仅运行时读取，需手动编辑 SKILL.md。Charles 是 CLI 工具，无 UI 层开关需求。

4. **工具白名单 4 形式匹配完全对齐**：Charles 的 `_is_skill_allowed`（registry.py L57-96）与 Cline 的 `isSkillAllowed`（user-instruction-plugin.ts L51-73）在 4 形式检查（normalizedId / normalizedName / bareId / bareName）上字节级对齐，仅语言差异（Python `in` vs TypeScript `has`）。

5. **disabled 双写法兼容完全对齐**：Charles（loader.py L239-241）与 Cline（user-instruction-config-loader.ts L304-306）都支持 `disabled: true` 和 `enabled: false` 两种写法。

6. **nanobot 残留**：P4.4 核心文件共 **15 处 nanobot 残留**：
   - **13 处注释残留**：全部为 docstring/行内注释溯源引用，标注"对标 nanobot"或"对标 Cline + nanobot"。其中 2 处为 stale docstring（registry.py L20 描述 XML 格式实际是 Markdown；__init__.py L13 描述 `use_skill` 工具名实际是 `skills`）。
   - **2 处实现逻辑残留**：loader.py L392-420 fallback 简单 YAML 解析（防御性，无害）；registry.py L183-208 always 预加载机制（业务功能，建议保留）。

7. **Level 1 暴露方式差异**：Cline 单通道（`skills` 工具 description 后缀），Charles 双通道（工具 description 后缀 + 可选 `charles-skills-summary` rule）。Charles 通道 2 默认关闭，与 Cline 默认行为对齐。

**整体一致性等级**：**中高**。P4.4 是 P4.x 系列中一致性较高的子阶段（35 项中 19 项高一致性），三级加载核心机制完全对齐。低一致性项（5 项）集中在 always 预加载（Charles 独有 + nanobot 溯源）、disabled 运行时写入（Charles 缺失）、Plan 模式拦截（Charles 独有），均为已知差异且建议保留/不修复。P4.4 范围内无阻塞性问题。
