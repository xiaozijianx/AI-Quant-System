# Phase 4.2 技能加载器（SkillLoader）对比

> 对比范围：Cline `user-instruction-config-loader.ts`（SKILL.md 扫描 + frontmatter 解析 + SkillConfig 数据结构 + 多源加载 + UnifiedConfigFileWatcher 集成）+ `skill-frontmatter-toggle.ts`（disabled toggle 写回）+ `unified-config-file-watcher.ts`（文件监听 + 热重载）+ `user-instruction-plugin.ts`（getConfiguredSkillsFromWatcher 过滤链）与 Charles `agent/skills/loader.py`（SkillLoader 类 + SkillMetadata + load_skills_multi_dir + load_skills_with_dirs）+ `agent/rules_loader.py` 的 `parse_yaml_frontmatter` 函数（独立 frontmatter 解析路径）的实现差异；nanobot 风格残留扫描（注释 vs 实现逻辑）。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L1-634（SkillConfig 类型 + parseMarkdownFrontmatter + parseSkillConfigFromMarkdown + discoverSkillFiles + createSkillsConfigDefinition + createUserInstructionConfigWatcher）
> - `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` L1-89（toggleSkillFrontmatter + updateSkillMarkdownEnabledState 写回文件）
> - `sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts` L94-248（UnifiedConfigFileWatcher 类 + fs.watch + 75ms debounce + subscribe/emit 事件流）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L1-100（getConfiguredSkillsFromWatcher + isSkillAllowed 白名单 4 形式匹配）
> - `sdk/packages/shared/src/storage/paths.ts` L358-370（resolveSkillsConfigSearchPaths 多源目录解析：workspace + ~/.cline/skills + ~/.agent/skills）
>
> Charles 源码：
> - `agent/skills/loader.py` L1-508（SkillMetadata + SkillLoader 类 + _parse_frontmatter + _strip_frontmatter + load_skills_multi_dir + load_skills_with_dirs）
> - `agent/rules_loader.py` L131-181（parse_yaml_frontmatter 独立 fail-open 解析路径，返回 FrontmatterParseResult）
> - `agent/skills/registry.py` L99-208（SkillRegistry 包装 SkillLoader，含 disabled / 白名单过滤链）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的技能加载器实现。两侧**核心解析路径已对齐**（YAML frontmatter + BOM 剥离 + CRLF 支持 + SKILL.md 文件名约定），但在**目录扫描覆盖面、disabled toggle 写回、热重载、metadata 字段集合**四个维度存在系统性差异，且 Charles 在 `loader.py` 中保留了 nanobot 风格的 fallback 简单 YAML 解析（**实现逻辑残留**，非纯注释残留）。

### 1. SKILL.md 加载方式

- **Cline** 用 `discoverSkillFiles()`（user-instruction-config-loader.ts L385-437）扫描 `skills/*/SKILL.md`，支持两类入口：(a) 顶层 `skills/<name>/SKILL.md` 目录形式；(b) `.cline/` 目录下含 `managed.json` manifest 的 managed plugin roots（L156-192 `discoverManagedPluginRoots`），managed plugin 的 skills 通过 `join(pluginRoot, "skills")` 二级嵌套加载。文件名硬匹配 `SKILL_FILE_NAME = "SKILL.md"`。
- **Charles** 用 `list_skills()`（loader.py L119-144）扫描 `skills/*/SKILL.md`，仅支持目录形式（`iterdir` + `is_dir` 过滤）。**无 managed plugin 概念**，无 manifest 文件读取。文件名硬编码 `"SKILL.md"`。

### 2. frontmatter 解析（双路径分裂）

Charles 存在**两条独立的 frontmatter 解析路径**，语义不一致：

- **路径 A（loader.py L364-420 `_parse_frontmatter`）**：PyYAML 优先，**失败时 fallback 到简单 YAML 解析**（L392-420，逐行 split + 列表项识别），返回 `dict | None`。这是 nanobot 风格的双轨实现（见 §4.2）。
- **路径 B（rules_loader.py L131-181 `parse_yaml_frontmatter`）**：仅用 PyYAML，**无 fallback**，返回 `FrontmatterParseResult`（含 `parse_error` 字段，fail-open 语义）。

- **Cline** 仅有单路径（user-instruction-config-loader.ts L194-225 `parseMarkdownFrontmatter`）：用 `yaml` 包的 `YAML.parse`，**无 fallback**；解析失败时返回 `parseError` 字符串，由调用方 `parseSkillConfigFromMarkdown`（L289-291）抛 `Error`。

### 3. disabled toggle

- **Cline** 提供 `toggleSkillFrontmatter()`（skill-frontmatter-toggle.ts L76-89）**写回 SKILL.md 文件**：读取 → 修改 frontmatter（`delete data.disabled` 或 `data.disabled = true`）→ 序列化 → `writeFile`。这是用户可在 UI 中点击 toggle 直接持久化到磁盘的机制。
- **Charles** 仅在 `_parse_skill_file` 中**读取** `disabled` / `enabled` 字段（loader.py L239-241），**无对应的写回函数**。Charles 的 toggle 持久化由 `rules_loader.py` 的 `rule_toggles.json`（L836-887）承担，但那是 rules 系统的 toggle，**skills 系统无独立 toggle 持久化**——要禁用 skill 只能手动编辑 SKILL.md frontmatter。

### 4. always 标记（关键架构差异）

**Cline 的 SkillConfig 无 `always` 字段**。Cline 文档（skills.mdx L9）明确："Unlike rules (which are always active), skills load on-demand"——Cline 的设计哲学是 skills 永远按需加载，rules 才有 `alwaysApply` 字段。Cline 中的 `alwaysApply: true` 仅出现在 `sdk/AGENTS.md` 等 rules 文件的 frontmatter（见 Grep 结果），不出现在 SkillConfig 类型定义中。

**Charles 的 SkillMetadata 有 `always: bool` 字段**（loader.py L70），并由 `SkillRegistry.get_always_skills()` / `load_always_instructions()`（registry.py L183-208）将 always=True 的 skill 指令**预注入 system prompt**。

**这是 Charles 独有的设计选择**，方向与 Cline 相反：Charles 把 Cline rules 的 `alwaysApply` 概念混入了 skills。计划 P4.2 表 4.2.7 标注 "always 字段 已对齐" 与实际源码不符——**实际是 Charles 独有，Cline 缺失**。

### 5. metadata 提取

- **Cline SkillConfig**（user-instruction-config-loader.ts L42-48）仅 4 个显式字段：`name` / `description` / `disabled` / `instructions` + 保留 `frontmatter: Record<string, unknown>` 原始数据。
- **Charles SkillMetadata**（loader.py L46-81）有 11+ 个显式字段：`name` / `description` / `keywords` / `always` / `capabilities` / `file_path` / `source` / `allowed_tools` / `disabled` / `scripts` / `source_dir` / `when_to_use`。

Charles 的额外字段中，`keywords` / `capabilities` / `allowed_tools` / `scripts` / `source_dir` / `when_to_use` 均为 Cline 无的对标扩展。

### 6. 技能目录扫描（多源）

- **Cline** 通过 `resolveSkillsConfigSearchPaths()`（shared/storage/paths.ts L358-370）聚合 3 类源：(1) workspace 内 `.cline/skills/`；(2) `~/.cline/skills/`（用户全局）；(3) `~/.agent/skills/`（legacy 路径）。再加 managed plugin roots（L156-192）和 `includePluginSkills` 选项（L142-152）。
- **Charles** 通过 `load_skills_multi_dir(dirs)`（loader.py L443-485）支持多目录加载 + 后覆盖前优先级，但**无内置全局目录解析**——调用方需显式传入 `dirs` 列表。实际生产用法（registry.py L123）仅传单目录 `agent_config/skills/`，**无 `~/.jike/skills/` 等用户全局 skills 概念**。

### 7. 错误处理

- **Cline** 在 frontmatter 解析失败时通过 `parseSkillConfigFromMarkdown`（L289-291）抛 `Error("Failed to parse YAML frontmatter: ...")`；instructions body 为空抛 `Error("Missing instructions body in skill file.")`；name 缺失抛 `Error("Missing skill name.")`。目录扫描错误用 `isIgnorableDirectoryError`（L107-115）吞掉 ENOENT/EACCES/EPERM/ELOOP，其余 rethrow。
- **Charles** `_parse_frontmatter` 失败返回 `None`（L378-379），`_parse_skill_file` 收到 None 时返回 None（L228-229），`list_skills` 跳过 None（L140-141）。**无显式错误抛出**，无 instructions body 非空校验。`_discover_scripts` 用 `except Exception: return []`（L341-342）吞掉所有异常。

### 8. 文件监听 + 热重载

- **Cline** 通过 `UnifiedConfigFileWatcher`（unified-config-file-watcher.ts L94-248）实现：`fs.watch` 监听目录 + 75ms debounce（L134）+ `subscribe(listener)` 事件流（L160-167）+ `start()` / `stop()` 生命周期（L169-190）+ `refreshAll()` 全量重扫（L192-198）+ `getSnapshot(type)` 快照查询（L210-218）。这是真正的文件系统监听 + 增量更新。
- **Charles** **无文件监听机制**。`rules_loader.py` 的 `_read_with_mtime_cache`（L524-556）用 `st_mtime_ns` 做模块级 mtime 缓存（L65 `_RULES_MTIME_CACHE`），但每次 build 仍重读文件——这是性能优化而非热重载。Charles 是 Web 请求-响应模型，每次请求重建 registry，等价"每次都热重载"，但无 watcher 事件流。

### 9. nanobot 残留

- **`agent/skills/loader.py`**：**8 处** nanobot 残留，其中 **7 处为注释残留**（docstring + 行内注释）、**1 处为实现逻辑残留**（L392-420 fallback 简单 YAML 解析）。
- **`agent/rules_loader.py`**：**0 处** nanobot 残留（实现完全对标 Cline fail-open 语义）。
- **`agent/skills/registry.py`**：4 处注释残留（不在本阶段对比范围，将在 P4.3 报告中详述）。

### 10. 一致性总体评估

- **核心解析路径**（frontmatter 正则 + BOM 剥离 + CRLF 支持）：**高一致性**。
- **目录扫描覆盖面**：**低一致性**（Charles 缺全局目录、缺 managed plugin）。
- **disabled toggle 写回**：**低一致性**（Charles 仅读不写）。
- **热重载**：**低一致性**（Charles 无 watcher）。
- **metadata 字段集合**：**中低一致性**（Charles 多出 always/keywords/capabilities/allowed_tools/scripts/when_to_use/source_dir 等 7+ 字段）。
- **always 字段**：**反向差异**（Charles 独有，Cline 缺失，方向相反）。
- **错误处理**：**中一致性**（Cline 严格抛错，Charles fail-silent）。

---

## 二、逐项对比表

### 2.1 SKILL.md 加载与目录扫描

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.1 | 扫描目录 | `.cline/skills/` + `~/.cline/skills/` + `~/.agent/skills/` + managed plugin roots（paths.ts L358-370 + loader.ts L156-192） | `agent_config/skills/`（registry.py L123 单目录传入） | **低** | Charles 缺全局 skills 目录、缺 managed plugin；多源加载能力存在（load_skills_multi_dir）但生产未启用 |
| 4.2.2 | 扫描入口文件名 | `SKILL_FILE_NAME = "SKILL.md"` 硬编码（loader.ts L24） | `"SKILL.md"` 硬编码（loader.py L135） | 高 | 完全一致 |
| 4.2.3 | 目录形式 skill | `skills/<name>/SKILL.md`（loader.ts L410-428） | `skills/<name>/SKILL.md`（loader.py L132-137） | 高 | 完全一致 |
| 4.2.4 | 平铺形式 skill | 不支持（仅目录形式 + 文件名硬匹配 SKILL.md） | 不支持（仅目录形式） | 高 | 两侧均仅支持目录形式 |
| 4.2.5 | managed plugin | `discoverManagedPluginRoots` 读取 `managed.json` manifest（loader.ts L156-192） | **无** | **低** | Charles 缺 managed plugin 概念 |
| 4.2.6 | 多源加载 | `resolveSkillsConfigSearchPaths` 聚合多目录 + `dedupeDirectoryPaths` 去重（loader.ts L121-133） | `load_skills_multi_dir(dirs)` 后覆盖前 + `source_dir` 记录来源（loader.py L443-485） | 中 | 两侧均支持多源 + 去重/覆盖，但 Charles 无内置路径解析 |
| 4.2.7 | 全局 skills 目录 | `~/.cline/skills/` + `~/.agent/skills/`（paths.ts L363-368） | **无** | **低** | Charles 缺用户级全局 skills |
| 4.2.8 | 同名 skill 覆盖 | `resolveId: (skill) => normalizeName(skill.name)` + Map 后写覆盖（loader.ts L546 + watcher 内部 Map） | `skills_by_name[skill.name] = skill` 后写覆盖 + 日志记录（loader.py L476-483） | 高 | 两侧均后注册覆盖，Charles 额外记录 override 日志 |
| 4.2.9 | 目录扫描排序 | `entries` 未显式排序（依赖 readdir 顺序） | `sorted(self.skills_dir.iterdir())`（loader.py L132） | 中 | Charles 显式排序保证确定性，Cline 依赖 watcher 内部 Map 保持插入顺序 |
| 4.2.10 | 符号链接处理 | `entry.isSymbolicLink()` + `stat(entryPath).isDirectory()` 双重判定（loader.ts L412-421） | `skill_dir.is_dir()`（loader.py L133）跟随符号链接 | 中 | Cline 显式处理 symlink，Charles 由 `Path.is_dir()` 隐式跟随 |

### 2.2 frontmatter 解析

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.11 | 解析入口 | `parseMarkdownFrontmatter(content)`（loader.ts L194-225）单路径 | `_parse_frontmatter(content)`（loader.py L364-420）+ `parse_yaml_frontmatter`（rules_loader.py L131-181）双路径 | **低** | Charles 双路径语义不一致，loader.py 有 fallback，rules_loader.py 无 fallback |
| 4.2.12 | YAML 库 | `yaml` npm 包的 `YAML.parse`（loader.ts L210） | `PyYAML` 的 `yaml.safe_load`（loader.py L386） | 高 | 两侧均用主流 YAML 库 |
| 4.2.13 | BOM 剥离 | `stripUtf8Bom(content)`（loader.ts L200，引用 @cline/shared） | `_strip_utf8_bom(content)`（loader.py L84-92） | 高 | 完全一致，两侧均处理 Windows Notepad "UTF-8 with BOM" |
| 4.2.14 | CRLF 支持 | 正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?`（loader.ts L202） | 正则 `^---\r?\n(.*?)\r?\n---\r?\n?`（loader.py L377） | 高 | 完全一致（Stage 31.4 / I12 已对齐） |
| 4.2.15 | 顶层非 dict 处理 | `parsed && typeof parsed === "object" && !Array.isArray(parsed)` 校验，否则视为空 dict（loader.ts L211-214） | `isinstance(result, dict)` 校验，否则返回 None 触发 fallback（loader.py L387-388） | 中 | Cline 视为空 dict，Charles 触发 fallback 简单解析 |
| 4.2.16 | 解析失败处理 | 返回 `parseError` 字符串，调用方抛 `Error`（loader.ts L216-224 + L289-291） | PyYAML 失败时 `except Exception: pass` 进入 fallback 简单解析（loader.py L389-390） | **低** | Cline 严格抛错，Charles fail-silent 进 fallback |
| 4.2.17 | fallback 简单解析 | **无** | 逐行 split + 列表项识别 + 键值对解析（loader.py L392-420） | **低** | Charles 保留 nanobot 风格 fallback，Cline 无此设计 |
| 4.2.18 | 返回值结构 | `ParseMarkdownFrontmatterResult { data, body, hadFrontmatter, parseError? }`（loader.ts L35-40） | `dict | None`（loader.py L364） | 中 | Cline 返回结构化结果含错误信息，Charles 仅返回 dict 或 None |
| 4.2.19 | body 提取 | 正则 group(2)（loader.ts L208） | `_strip_frontmatter` 单独方法（loader.py L422-434） | 高 | 两侧均从 frontmatter 后提取 body |
| 4.2.20 | instructions 非空校验 | `if (!instructions) throw new Error("Missing instructions body")`（loader.ts L293-295） | **无校验** | **低** | Charles 缺 instructions body 非空校验 |
| 4.2.21 | name 缺失处理 | `if (!name) throw new Error("Missing skill name.")`（loader.ts L298-300） | `frontmatter.get("name", skill_file.parent.name)` fallback 到目录名（loader.py L231） | 中 | Cline 严格抛错，Charles fallback 到目录名（与 Cline fallbackName 参数等价但路径不同） |

### 2.3 disabled toggle

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.22 | disabled 字段读取 | `parseBooleanField(data.disabled, "disabled")`（loader.ts L305-307） | `bool(frontmatter.get("disabled", False))`（loader.py L239） | 高 | 完全一致 |
| 4.2.23 | enabled 字段兼容 | `parseBooleanField(data.enabled, "enabled") === false ? true : undefined`（loader.ts L306-307） | `if frontmatter.get("enabled", True) is False: disabled = True`（loader.py L240-241） | 高 | 两侧均支持 `disabled: true` 和 `enabled: false` 两种写法 |
| 4.2.24 | disabled 写回文件 | `toggleSkillFrontmatter({filePath, enabled})` 读 → 改 → 写（skill-frontmatter-toggle.ts L76-89） | **无** | **低** | Charles 缺 disabled toggle 写回机制 |
| 4.2.25 | frontmatter 序列化 | `YAML.stringify(data).trimEnd()` + `---\n${yaml}\n---\n${body}`（skill-frontmatter-toggle.ts L43-49） | **无** | **低** | Charles 无 frontmatter 序列化回写能力 |
| 4.2.26 | enabled=true 时清理 | `delete data.disabled` + `delete data.enabled`（若 enabled===false）+ 空 frontmatter 时返回纯 body（skill-frontmatter-toggle.ts L61-69） | **无** | **低** | Cline 在 enabled 时智能清理冗余字段，Charles 不支持 |
| 4.2.27 | enabled=false 时设置 | `data.disabled = true`（skill-frontmatter-toggle.ts L72） | **无** | **低** | Charles 不支持通过 API 设置 disabled |
| 4.2.28 | disabled 过滤位置 | `getConfiguredSkillsFromWatcher` L100 `.filter((skill) => !skill.disabled)` + `listAvailableSkillNames` L100（user-instruction-plugin.ts） | `SkillRegistry.list_skills()` L157 `all_skills = [s for s in all_skills if not s.disabled]`（registry.py） | 高 | 两侧均在 list 阶段过滤，在 get 阶段保留 disabled 用于错误提示 |

### 2.4 always 标记（反向差异）

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.29 | always 字段定义 | **无**（SkillConfig 类型无 always 字段，loader.ts L42-48） | `always: bool = False`（loader.py L70） | **低（反向）** | Charles 独有，Cline 缺失 |
| 4.2.30 | always frontmatter 解析 | **无** | `bool(frontmatter.get("always", False))`（loader.py L234） | **低（反向）** | Charles 独有 |
| 4.2.31 | always 技能预加载 | **无**（skills 永远 on-demand，skills.mdx L9 明确） | `get_always_skills()` + `load_always_instructions()` 预注入 system prompt（registry.py L183-208） | **低（反向）** | Charles 把 Cline rules 的 alwaysApply 概念混入 skills |
| 4.2.32 | always 与 rules alwaysApply 关系 | rules 文件有 `alwaysApply: true` frontmatter（sdk/AGENTS.md L4） | rules 系统无 alwaysApply 字段，skills 系统有 always 字段 | **低** | 两侧的 always 概念分布相反：Cline 在 rules，Charles 在 skills |
| 4.2.33 | always 字段对标位置 | Cline rules 的 `alwaysApply`（非 skills） | Charles skills 的 `always` | — | Charles 的 always 实际对标的是 Cline rules.alwaysApply，但放在了 skills 上 |

### 2.5 metadata 提取与数据结构

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.34 | 数据结构类型 | `interface SkillConfig`（loader.ts L42-48） | `@dataclass class SkillMetadata`（loader.py L46-81） | 高 | 两侧均用结构化类型，TS interface vs Python dataclass |
| 4.2.35 | name 字段 | `name: string` 必填（loader.ts L43） | `name: str` 必填（loader.py L67） | 高 | 完全一致 |
| 4.2.36 | description 字段 | `description?: string` 可选（loader.ts L44） | `description: str = ""` 默认空串（loader.py L68） | 高 | 语义等价 |
| 4.2.37 | disabled 字段 | `disabled?: boolean` 可选（loader.ts L45） | `disabled: bool = False` 默认 False（loader.py L75） | 高 | 完全一致 |
| 4.2.38 | instructions 字段 | `instructions: string` 必填（loader.ts L46） | 通过 `load_instructions(name)` 单独加载（loader.py L159-184） | 中 | Cline 在 metadata 中持有 instructions，Charles 按需加载 |
| 4.2.39 | frontmatter 原始数据 | `frontmatter: Record<string, unknown>` 保留原始 dict（loader.ts L47） | **无**（仅提取显式字段，不保留原始 frontmatter） | **低** | Charles 缺原始 frontmatter 保留，无法做 forward compatibility |
| 4.2.40 | keywords 字段 | **无** | `keywords: list[str]`（loader.py L69） | **低（反向）** | Charles 独有，用于 fallback 匹配 |
| 4.2.41 | capabilities 字段 | **无** | `capabilities: list[str]`（loader.py L71） | **低（反向）** | Charles 独有 |
| 4.2.42 | allowed_tools 字段 | **无**（Cline 的 subAgentTools 在 tool 层配置，非 skill metadata） | `allowed_tools: list[str] | None`（loader.py L74，Phase 20） | **低（反向）** | Charles 独有，每个 skill 可自定义子 agent 工具集 |
| 4.2.43 | scripts 字段 | **无** | `scripts: list[str]`（loader.py L76，Phase 33.4 自动发现 .py） | **低（反向）** | Charles 独有，自动扫描技能目录下 .py 文件 |
| 4.2.44 | source_dir 字段 | **无**（Cline 通过 watcher recordsByType 内部跟踪） | `source_dir: str`（loader.py L78，Stage 13.4） | 中 | Charles 显式记录来源目录，Cline 由 watcher 内部管理 |
| 4.2.45 | when_to_use 字段 | **无**（Cline 用 description 隐含表达） | `when_to_use: str`（loader.py L81，Phase P5） | **低（反向）** | Charles 独有，显式"何时使用"字段 |
| 4.2.46 | file_path 字段 | **无**（Cline 通过 UnifiedConfigFileCandidate.filePath 传递，不进 SkillConfig） | `file_path: str`（loader.py L72） | 中 | Charles 在 metadata 中持有路径，Cline 在外部 candidate 中持有 |
| 4.2.47 | source 字段 | **无** | `source: str = "workspace"`（loader.py L73） | **低（反向）** | Charles 独有，标注 workspace/builtin 来源 |

### 2.6 文件监听与热重载

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.48 | 文件监听机制 | `UnifiedConfigFileWatcher` + `fs.watch` 监听目录（unified-config-file-watcher.ts L110 + L284） | **无** | **低** | Charles 无文件系统监听 |
| 4.2.49 | debounce | `debounceMs = 75`（unified-config-file-watcher.ts L134） | **无** | **低** | Charles 无 debounce 机制 |
| 4.2.50 | 事件流 | `subscribe(listener) → () => void` + `emit(event)` 推送 add/update/remove 事件（unified-config-file-watcher.ts L160-167 + L239-243） | **无** | **低** | Charles 无事件订阅机制 |
| 4.2.51 | 生命周期 | `start()` / `stop()` / `refreshAll()` / `refreshType(type)`（unified-config-file-watcher.ts L169-208） | **无** | **低** | Charles 无 watcher 生命周期管理 |
| 4.2.52 | 快照查询 | `getSnapshot(type)` / `getAllSnapshots()` 返回 Map（unified-config-file-watcher.ts L210-237） | **无**（Charles 直接调用 `list_skills()` 重扫） | **低** | Cline 维护内存快照，Charles 每次重扫 |
| 4.2.53 | mtime 缓存 | watcher 内部 `recordsByType` 维护记录 | `_RULES_MTIME_CACHE`（rules_loader.py L65，仅 rules 系统） | 中 | Charles rules 系统有 mtime 缓存，skills 系统无 |
| 4.2.54 | 热重载触发 | fs.watch 事件 → debounce 75ms → refreshType → emit | Web 请求 → 重建 registry → 重读所有文件 | **低** | Cline 事件驱动，Charles 请求驱动 |

### 2.7 错误处理

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.55 | YAML 解析失败 | 返回 `parseError`，调用方抛 `Error("Failed to parse YAML frontmatter: ...")`（loader.ts L216-224 + L289-291） | PyYAML 失败进 fallback 简单解析（loader.py L389-390），fallback 失败返回 None | **低** | Cline 严格抛错，Charles fail-silent |
| 4.2.56 | instructions body 为空 | `throw new Error("Missing instructions body in skill file.")`（loader.ts L293-295） | **无校验**，返回空 instructions | **低** | Charles 缺校验 |
| 4.2.57 | name 缺失 | `throw new Error("Missing skill name.")`（loader.ts L298-300） | fallback 到目录名（loader.py L231） | 中 | Cline 严格，Charles 宽松 |
| 4.2.58 | 目录不存在 | `isIgnorableDirectoryError` 吞掉 ENOENT/EACCES/EPERM/ELOOP（loader.ts L107-115 + L432-436） | `if not self.skills_dir.exists(): return []`（loader.py L128-129） | 高 | 两侧均优雅处理目录不存在 |
| 4.2.59 | 文件读取失败 | rethrow 非 ignorable 错误（loader.ts L434-436） | `Path.read_text(encoding="utf-8")` 未捕获异常时向上传播（loader.py L226） | 中 | Cline 显式分类处理，Charles 依赖默认异常传播 |
| 4.2.60 | _discover_scripts 异常 | **无对应**（Cline 无 scripts 概念） | `except Exception: return []`（loader.py L341-342）吞掉所有异常 | — | Charles fail-silent，可能掩盖真实错误 |
| 4.2.61 | parseError 暴露选项 | `emitParseErrors?: boolean` 控制是否在事件中暴露 parseError（loader.ts L82 + L135） | **无** | **低** | Charles 无 parseError 暴露控制 |
| 4.2.62 | 字段类型校验 | `parseStringField` 校验 string 类型 + trim + 非空（loader.ts L227-246）；`parseBooleanField` 校验 boolean 类型（loader.ts L248-259） | `str(frontmatter.get(...))` 强转（loader.py L282） | 中 | Cline 严格类型校验，Charles 强转宽松 |

### 2.8 多源加载与覆盖

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.2.63 | 多源加载 API | `createSkillsConfigDefinition({directories, pluginSkillDirectories, includePluginSkills, pluginPaths, workspacePath, cwd})`（loader.ts L84-91 + L526-548） | `load_skills_multi_dir(dirs: list)` + `load_skills_with_dirs(primary_dir, extra_dirs)`（loader.py L443-508） | 中 | 两侧均支持多源，Cline 选项更丰富 |
| 4.2.64 | 目录去重 | `dedupeDirectoryPaths` 用 `resolve()` 规范化后 Set 去重（loader.ts L121-133） | **无显式去重**（loader.py L465 直接遍历 dirs） | **低** | Charles 缺目录去重，重复目录会重复扫描 |
| 4.2.65 | 覆盖优先级 | watcher 内部 Map 后写覆盖 + `resolveId` 规范化 id（loader.ts L546） | `dirs` 列表靠后优先级高 + `skills_by_name[skill.name] = skill` 后写覆盖（loader.py L455 + L483） | 高 | 两侧均后写覆盖，Charles 文档明确"靠后优先级高" |
| 4.2.66 | override 日志 | **无** | `logger.info("Stage 13.4: skill override: %s from %s -> %s", ...)`（loader.py L479-482） | 中 | Charles 额外记录 override 日志 |
| 4.2.67 | pluginSkillDirectories 选项 | `options.pluginSkillDirectories` 直接传入目录列表（loader.ts L142-143） | **无** | **低** | Charles 缺 plugin skill directories 概念 |
| 4.2.68 | includePluginSkills 选项 | `options.includePluginSkills` 触发 `resolveAgentPluginSkillDirectories`（loader.ts L144-152） | **无** | **低** | Charles 缺 plugin 自动解析 |

---

## 三、重点差距详细说明

### 差距 1：Charles 双路径 frontmatter 解析语义不一致（4.2.11 / 4.2.16 / 4.2.17）

**这是本阶段最核心的架构差距，属于实现逻辑层面，非注释残留。**

Charles 存在两条独立的 frontmatter 解析路径，语义不一致：

**路径 A：`agent/skills/loader.py` L364-420 `_parse_frontmatter`**

```python
def _parse_frontmatter(self, content: str) -> dict[str, Any] | None:
    content = _strip_utf8_bom(content)
    if not content.startswith("---"):
        return None
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", content, re.DOTALL)
    if not match:
        return None
    raw = match.group(1)
    # 优先使用 PyYAML
    try:
        import yaml
        result = yaml.safe_load(raw)
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    # Fallback: 简单 YAML 解析 — 对标 nanobot fallback
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    for line in raw.split("\n"):
        # ... 逐行解析键值对 + 列表项 ...
    return metadata
```

**路径 B：`agent/rules_loader.py` L131-181 `parse_yaml_frontmatter`**

```python
def parse_yaml_frontmatter(markdown: str) -> FrontmatterParseResult:
    # ... BOM 剥离 + 正则匹配 ...
    try:
        import yaml
        data = yaml.safe_load(yaml_content) or {}
        if not isinstance(data, dict):
            return FrontmatterParseResult(
                body=normalized, had_frontmatter=True,
                parse_error=f"frontmatter top-level must be a mapping, got {type(data).__name__}",
            )
        return FrontmatterParseResult(data=data, body=body, had_frontmatter=True)
    except Exception as e:
        return FrontmatterParseResult(
            body=normalized, had_frontmatter=True, parse_error=str(e),
        )
```

**Cline 单路径**（user-instruction-config-loader.ts L194-225）：

```typescript
function parseMarkdownFrontmatter(content: string): ParseMarkdownFrontmatterResult {
    const normalizedContent = stripUtf8Bom(content);
    const match = normalizedContent.match(frontmatterRegex);
    if (!match) return { data: {}, body: normalizedContent, hadFrontmatter: false };
    const [, yamlContent, body] = match;
    try {
        const parsed = YAML.parse(yamlContent);
        const data = parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>) : {};
        return { data, body, hadFrontmatter: true };
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return { data: {}, body: normalizedContent, hadFrontmatter: true, parseError: message };
    }
}
```

**三路径语义对比**：

| 场景 | Cline | Charles 路径 A（loader.py） | Charles 路径 B（rules_loader.py） |
|------|-------|----------------------------|-----------------------------------|
| PyYAML 解析成功 + dict | 返回 data | 返回 dict | 返回 FrontmatterParseResult(data) |
| PyYAML 解析成功 + 非 dict | 视为空 dict | 触发 fallback 简单解析 | 返回 parse_error |
| PyYAML 抛异常 | 返回 parseError | 触发 fallback 简单解析 | 返回 parse_error |
| fallback 简单解析失败 | — | 返回 None | — |
| 无 frontmatter | `{data: {}, body, hadFrontmatter: false}` | 返回 None | `FrontmatterParseResult(body, had_frontmatter=False)` |

**影响**：
- Charles 路径 A 的 fallback 简单解析是 nanobot 风格残留（L392 注释明确"对标 nanobot fallback"），当 PyYAML 失败时会用简化解析"猜"出一个 dict，可能产生错误结果（如嵌套 dict、引号转义、多行字符串等场景）。
- Charles 路径 B 完全对标 Cline fail-open 语义，但仅用于 rules 系统，未用于 skills 系统。
- 两条路径分裂导致维护负担：修复 frontmatter 解析 bug 需在两处同步。

**建议**：P2 级别。统一为路径 B 的 `parse_yaml_frontmatter` 语义，移除路径 A 的 fallback 简单解析（同时消除 nanobot 实现逻辑残留）。

### 差距 2：Charles 无 disabled toggle 写回机制（4.2.24 - 4.2.27）

**Cline 实现**（skill-frontmatter-toggle.ts L51-74 + L76-89）：

```typescript
export function updateSkillMarkdownEnabledState(content: string, enabled: boolean): string {
    const { data, body, hadFrontmatter } = parseMarkdownFrontmatter(content);
    if (!hadFrontmatter && enabled) return content;
    if (enabled) {
        delete data.disabled;
        if (data.enabled === false) delete data.enabled;
        if (Object.keys(data).length === 0) return body;
        return serializeMarkdownFrontmatter(data, body);
    }
    data.disabled = true;
    return serializeMarkdownFrontmatter(data, body);
}

export async function toggleSkillFrontmatter({ filePath, enabled }): Promise<ToggleSkillFrontmatterResult> {
    const content = await readFile(filePath, "utf8");
    const updated = updateSkillMarkdownEnabledState(content, enabled);
    await writeFile(filePath, updated);
    return { filePath, enabled, disabled: !enabled };
}
```

Cline 的 `toggleSkillFrontmatter` 是 UI toggle 按钮的后端实现：用户在 UI 点击启用/禁用 skill → 调用此函数 → 读取 SKILL.md → 修改 frontmatter（`delete data.disabled` 或 `data.disabled = true`）→ 序列化 → `writeFile` 写回磁盘。序列化时智能清理冗余字段（enabled=true 时若 `enabled: false` 存在则删除，若 frontmatter 为空则返回纯 body）。

**Charles 实现**：loader.py 仅在 `_parse_skill_file`（L239-241）**读取** disabled 字段，**无任何写回函数**。Charles 的 toggle 持久化由 `rules_loader.py` 的 `rule_toggles.json`（L836-887 `load_toggles` / `save_toggles` / `synchronize_rule_toggles`）承担，但那是 rules 系统的 toggle 文件，**skills 系统无独立 toggle 持久化**。要禁用 Charles 的 skill，只能手动编辑 SKILL.md 的 frontmatter 加 `disabled: true`。

**影响**：
- Charles 的 skills 系统无 UI toggle 持久化能力，用户体验落后于 Cline。
- Charles 的 rules toggle 通过外部 JSON 文件（`rule_toggles.json`）实现，不修改原 .md 文件；Cline 的 skills toggle 直接修改原 SKILL.md 文件。两种设计哲学不同：Charles 是"叠加层"toggle，Cline 是"原位修改"toggle。

**建议**：P3 级别（不强制对齐）。Charles 的 rules toggle 模式（外部 JSON）若要扩展到 skills 系统，可在 `agent_config/skill_toggles.json` 中实现，复用 `rules_loader.py` 的 `load_toggles` / `save_toggles` 模式。但当前 Charles skills 数量少（8 个），手动编辑 frontmatter 可接受。

### 差距 3：Charles always 字段方向与 Cline 相反（4.2.29 - 4.2.33）

**这是 Charles 独有的设计选择，方向与 Cline 相反。**

**Cline 设计哲学**（docs/customization/skills.mdx L9）：
> "Unlike rules (which are always active), skills load on-demand so they don't consume context when you're working on something unrelated."

Cline 明确区分：
- **rules** = always active（始终注入 system prompt），frontmatter 有 `alwaysApply: true` 字段
- **skills** = on-demand（按需加载），**无 always 字段**

Cline 的 `SkillConfig` 类型（loader.ts L42-48）仅有 `name` / `description` / `disabled` / `instructions` / `frontmatter`，**无 always 字段**。

**Charles 实现**（loader.py L70 + registry.py L183-208）：

```python
@dataclass
class SkillMetadata:
    # ...
    always: bool = False  # 是否始终加载指令（Level 2）

class SkillRegistry:
    def get_always_skills(self) -> list[str]:
        """获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()"""
        return [name for name, meta in self._skills.items() if meta.always]

    def load_always_instructions(self) -> str:
        """加载所有 always=True 技能的指令"""
        always_names = self.get_always_skills()
        # ... 拼接所有 always skill 的 instructions 注入 system prompt ...
```

Charles 的 `always=True` skill 会在启动时通过 `load_always_instructions()` 将指令预注入 system prompt，无需 LLM 通过 `use_skill` 工具触发。这本质上是把 Cline rules 的 `alwaysApply` 概念混入了 skills。

**Charles 的 always 实际对标位置**：registry.py L184 docstring 明确"对标 nanobot get_always_skills()"——这是 nanobot 风格残留（实现逻辑层面：always 字段 + 预加载机制均来自 nanobot，非 Cline）。

**影响**：
- Charles 的 always skill 会消耗 system prompt token（即使 LLM 不需要该技能），与 Cline "skills load on-demand" 设计哲学相悖。
- 但在量化场景下，某些核心技能（如 write-report）确实需要始终可用，always 字段有实际价值。

**建议**：P3 级别（不强制对齐）。Charles 的 always 字段是合理的设计选择，但应明确文档说明"这是 nanobot 风格残留，非 Cline 对标"，避免误导。若未来要严格对齐 Cline，可将 always=True 的 skill 改为 rules 文件（rules 系统 alwaysApply），但当前 8 个 skill 已稳定，改动成本高于收益。

### 差距 4：Charles 缺全局 skills 目录与 managed plugin（4.2.1 / 4.2.5 / 4.2.7）

**Cline 多源目录解析**（shared/storage/paths.ts L358-370）：

```typescript
export function resolveSkillsConfigSearchPaths(workspacePath?: string): string[] {
    return dedupePaths([
        ...getWorkspaceSkillDirectories(workspacePath),  // workspace 内 .cline/skills/
        join(resolveClineDir(), SKILLS_CONFIG_DIRECTORY_NAME),  // ~/.cline/skills/
        join(HOME_DIR, LEGACY_AGENT_SKILLS_CONFIG_DIR, SKILLS_CONFIG_DIRECTORY_NAME),  // ~/.agent/skills/
    ]);
}
```

Cline 聚合 3 类源：
1. workspace 内 `.cline/skills/`（项目级）
2. `~/.cline/skills/`（用户全局）
3. `~/.agent/skills/`（legacy 全局，向后兼容）

外加 managed plugin roots（loader.ts L156-192 `discoverManagedPluginRoots`）扫描 `.cline/<plugin>/managed.json` manifest，加载 `plugin/skills/` 二级嵌套目录。

**Charles 实现**（registry.py L123）：

```python
def __init__(self, skills_dir: Path | str | None = None, ...):
    self.loader = SkillLoader(skills_dir)
```

Charles 仅接受单目录 `skills_dir`，生产用法（server.py L188 附近）传入 `agent_config/skills/`。**无全局 skills 目录、无 managed plugin、无 legacy 路径兼容**。

Charles 的 `load_skills_multi_dir(dirs)`（loader.py L443-485）支持多目录加载，但调用方需显式传入 `dirs` 列表，无内置全局目录解析。

**影响**：
- Charles 不支持用户级全局 skills（如 `~/.jike/skills/`），所有 skills 必须在 `agent_config/skills/` 中。
- Charles 不支持 managed plugin（如通过 manifest 管理第三方 skill 包）。
- 在量化场景下，单目录足够（8 个 skill 全部在 `agent_config/skills/`），全局 skills 与 managed plugin 的缺失不影响当前功能。

**建议**：P3 级别（不强制对齐）。若未来需要支持用户级全局 skills（如用户自定义 skill 跨项目共享），可扩展 `resolve_skills_search_paths()` 函数聚合 `~/.jike/skills/` 等目录。当前单目录模式足够。

### 差距 5：Charles 无文件监听与热重载（4.2.48 - 4.2.54）

**Cline 实现**（unified-config-file-watcher.ts L94-248）：

```typescript
export class UnifiedConfigFileWatcher<TType extends string, TItem> {
    private readonly debounceMs: number;  // 默认 75ms
    private readonly watchersByDirectory = new Map<string, FSWatcher>();
    private readonly listeners = new Set<(event) => void>();

    async start(): Promise<void> {
        await this.refreshAll();        // 全量扫描
        this.startDirectoryWatchers();  // 启动 fs.watch
    }

    subscribe(listener): () => void { /* 订阅事件 */ }

    private emit(event): void {
        for (const listener of this.listeners) listener(event);
    }
    // fs.watch 事件 → debounce 75ms → refreshType → emit add/update/remove
}
```

Cline 通过 `fs.watch` 监听目录变化，75ms debounce 后触发增量刷新，通过 `subscribe(listener)` 推送 add/update/remove 事件给订阅者。这是真正的文件系统监听 + 增量更新 + 事件驱动架构。

**Charles 实现**：**无文件监听机制**。Charles 是 Web 请求-响应模型，每次请求重建 `SkillRegistry`（server.py L188 `global _skill_registry`），重读所有 SKILL.md 文件。`rules_loader.py` 的 `_read_with_mtime_cache`（L524-556）用 `st_mtime_ns` 做模块级 mtime 缓存减少重复 I/O，但仅用于 rules 系统，skills 系统无 mtime 缓存。

**影响**：
- Charles 的 skills 系统无热重载能力：编辑 SKILL.md 后需重启服务或等待下次请求重建 registry。
- 但在量化场景下，skills 变更频率低（8 个 skill 基本稳定），热重载的缺失不影响开发体验。
- Charles 的 mtime 缓存（rules 系统）是性能优化，非热重载——每次 build 仍重读文件，仅避免无变更文件的重复解析。

**建议**：P3 级别（不强制对齐）。Charles 的请求-响应模型天然等价"每次都热重载"，无需引入 fs.watch。若未来 skills 数量增长导致性能问题，可将 rules_loader 的 mtime 缓存模式扩展到 skills 系统。

---

## 四、nanobot 残留检查

针对 P4.2 核心文件执行 nanobot 残留扫描，严格区分**注释残留**（docstring / 行内注释）和**实现逻辑残留**（实际代码逻辑引用 nanobot 模块或保留 nanobot 风格实现）。

### 4.1 P4.2 核心文件扫描结果

| 文件 | nanobot 匹配数 | 残留类型 | 详情 |
|------|---------------|---------|------|
| `agent/skills/loader.py` | **8** | 7 注释 + **1 实现逻辑** | 详见 4.2 |
| `agent/rules_loader.py` | **0** | 无 | 完全对标 Cline fail-open 语义，无 nanobot 引用 |
| `agent/skills/registry.py` | 4 | 全部注释 | 不在本阶段范围（P4.3 详述） |

### 4.2 loader.py nanobot 残留分类

#### 注释残留（7 处，全部为 docstring / 行内注释）

| 行号 | 内容 | 类型 |
|------|------|------|
| L2 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | 模块 docstring |
| L29 | `对标 nanobot:` + L30 `agent/skills.py SkillsLoader: list_skills / load_skill / _parse_frontmatter` + L31 `PyYAML 解析 + fallback 简单解析` | 模块 docstring |
| L48 | `"""技能元数据 — 对标 Cline frontmatter + nanobot metadata` | SkillMetadata docstring |
| L96 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | SkillLoader 类 docstring |
| L167 | `对标 nanobot: load_skill() + _strip_frontmatter()` | load_instructions docstring |
| L222 | `"""解析 SKILL.md 文件 — 对标 nanobot get_skill_metadata()` | _parse_skill_file docstring |
| L423 | `"""去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()` | _strip_frontmatter docstring |

#### 实现逻辑残留（1 处）

**L392-420 `_parse_frontmatter` 的 fallback 简单 YAML 解析**：

```python
# Fallback: 简单 YAML 解析 — 对标 nanobot fallback
metadata: dict[str, Any] = {}
current_key: str | None = None

# Phase 3.5: split 时处理 \r\n 残留
for line in raw.split("\n"):
    stripped = line.rstrip("\r").strip()
    # 列表项
    if stripped.startswith("- ") and current_key:
        item = stripped[2:].strip()
        if isinstance(metadata.get(current_key), list):
            metadata[current_key].append(item)
        else:
            metadata[current_key] = [item]
        continue

    # 键值对
    if ":" in line and not stripped.startswith("-"):
        key, value = line.split(":", 1)
        # ... 简单解析键值对 ...
```

**为何这是实现逻辑残留而非纯注释**：

1. **L392 注释明确标注"对标 nanobot fallback"**，且 docstring L29-31 也明确"对标 nanobot: PyYAML 解析 + fallback 简单解析"——这是 nanobot `agent/skills.py` 的双轨实现模式。
2. **Cline 无此 fallback 设计**：Cline 的 `parseMarkdownFrontmatter`（loader.ts L194-225）仅用 `YAML.parse`，失败时返回 `parseError`，**无 fallback 简单解析**。
3. **Charles 的 fallback 简单解析是实际运行的代码逻辑**：当 PyYAML 失败时（L389 `except Exception: pass`），会进入 L392-420 的 fallback 分支，逐行 split + 列表项识别 + 键值对解析，返回一个"猜测"的 dict。这个 dict 会被 `_parse_skill_file` 当作合法 frontmatter 使用，可能产生错误结果（如嵌套 dict、引号转义、多行字符串等场景）。
4. **Charles 自己的 `rules_loader.py` 已放弃此 fallback**：`parse_yaml_frontmatter`（L131-181）仅用 PyYAML，失败时返回 `parse_error`，无 fallback——这是对标 Cline 的正确实现。但 `loader.py` 仍保留 nanobot 风格 fallback。

**fallback 简单解析的局限性**：

- 不支持嵌套 dict（仅支持单层 key-value + 列表项）
- 不支持引号转义（`description: "Hello, world"` 中的引号会被 `strip("\"'")` 剥离，但嵌套引号会出错）
- 不支持多行字符串（`|` / `>` 块标量）
- 不支持 YAML 锚点 / 别名（`&anchor` / `*alias`）
- 不支持 inline list（`keywords: [a, b, c]` 会被解析为空字符串）

当 SKILL.md frontmatter 使用上述高级 YAML 特性且 PyYAML 因某种原因失败时，fallback 简单解析会返回错误结果，但 Charles 不会报错（fail-silent），可能导致 skill 元数据错误。

### 4.3 残留处理建议

| 文件 | 残留类型 | 处理建议 | 优先级 |
|------|---------|---------|--------|
| `agent/skills/loader.py` L2 | 注释 | 移除 `+ nanobot SkillsLoader` 段落，保留 `对标 Cline skills discovery` | P2 |
| `agent/skills/loader.py` L29-31 | 注释 | 移除整个"对标 nanobot:"段落（含 PyYAML + fallback 说明） | P2 |
| `agent/skills/loader.py` L48 | 注释 | 移除 `+ nanobot metadata`，保留 `对标 Cline frontmatter` | P2 |
| `agent/skills/loader.py` L96 | 注释 | 移除 `+ nanobot SkillsLoader`，保留 `对标 Cline skills discovery` | P2 |
| `agent/skills/loader.py` L167 | 注释 | 移除 `对标 nanobot: load_skill() + _strip_frontmatter()` 行 | P2 |
| `agent/skills/loader.py` L222 | 注释 | 移除 `对标 nanobot get_skill_metadata()`，保留 `解析 SKILL.md 文件` | P2 |
| `agent/skills/loader.py` L423 | 注释 | 移除 `对标 nanobot _strip_frontmatter()`，保留 `去除 YAML frontmatter` | P2 |
| `agent/skills/loader.py` L392-420 | **实现逻辑** | **移除 fallback 简单解析分支**，PyYAML 失败时返回 None 或抛错（与 rules_loader.py 的 fail-open 语义对齐） | **P2** |
| `agent/rules_loader.py` | 无 | 无需处理（0 残留） | — |

**注**：L392-420 的 fallback 简单解析移除后，`_parse_frontmatter` 应改为：
- PyYAML 解析成功 + dict → 返回 dict
- PyYAML 解析成功 + 非 dict → 返回 None（或返回空 dict）
- PyYAML 抛异常 → 返回 None（或返回空 dict + 日志 warning）

这与 `rules_loader.py` 的 `parse_yaml_frontmatter` fail-open 语义一致，且与 Cline 的 `parseMarkdownFrontmatter` 行为更接近（Cline 返回 parseError，Charles 可选择返回 None 或抛错）。

---

## 五、修复建议

### 建议 1：统一 frontmatter 解析路径，移除 nanobot fallback [P2]

**文件**：`agent/skills/loader.py`
**位置**：L364-420 `_parse_frontmatter` 方法

**修改方向**：
1. 移除 L392-420 的 fallback 简单解析分支（nanobot 实现逻辑残留）
2. PyYAML 失败时返回 None（与现有 `if frontmatter is None: return None` 调用链兼容）
3. 可选：将 `_parse_frontmatter` 改为调用 `rules_loader.parse_yaml_frontmatter`，复用 fail-open 语义（但需注意返回值类型差异：`dict | None` vs `FrontmatterParseResult`）

**理由**：
- 消除 nanobot 实现逻辑残留（L392-420 fallback 简单解析）
- 统一 Charles 内部 frontmatter 解析语义（loader.py 与 rules_loader.py 一致）
- 与 Cline 行为对齐（Cline 无 fallback，PyYAML 失败直接报错）
- 避免 fallback 简单解析在高级 YAML 特性场景下产生错误结果

**风险**：若现有 SKILL.md 依赖 fallback 简单解析（如 PyYAML 因某种原因无法解析但 fallback 能解析），移除后这些 SKILL.md 会变成 None（被 `list_skills` 跳过）。需先扫描 `agent_config/skills/*/SKILL.md` 确认 PyYAML 均能正确解析。

### 建议 2：清理 loader.py 的 nanobot 注释残留 [P2]

**文件**：`agent/skills/loader.py`
**位置**：L2 / L29-31 / L48 / L96 / L167 / L222 / L423（共 7 处）

**修改方向**：移除所有 `对标 nanobot ...` / `+ nanobot ...` 段落，保留 `对标 Cline ...` 部分。

**理由**：与 P3.24 exec_tool.py 的 nanobot 注释清理一致，保持源码溯源清洁度。注释清理可与建议 1 的实现逻辑清理一并执行。

### 建议 3：不强制对齐 disabled toggle 写回 [P3 不修复]

**理由**：
- Cline 的 `toggleSkillFrontmatter` 是 UI toggle 按钮的后端实现，Charles 无对应 UI 入口。
- Charles 的 rules 系统已有 `rule_toggles.json` 外部 toggle 持久化模式，若要扩展到 skills 系统可复用此模式。
- 当前 8 个 skill 数量少，手动编辑 frontmatter `disabled: true` 可接受。
- 强制对齐需要引入 SKILL.md frontmatter 序列化能力（Cline 的 `serializeMarkdownFrontmatter`），改动较大。

**保留条件**：若未来 Charles 引入 skill 管理 UI，可参考 Cline `skill-frontmatter-toggle.ts` 实现 disabled toggle 写回，或参考 Charles rules 的 `rule_toggles.json` 模式实现外部 toggle。

### 建议 4：不强制对齐 always 字段 [P3 不修复]

**理由**：
- Charles 的 `always` 字段是合理的设计选择（量化场景下某些核心技能需始终可用），但本质是 nanobot 风格残留（registry.py L184 docstring "对标 nanobot get_always_skills()"）。
- Cline 的设计哲学是 skills 永远 on-demand，rules 才有 alwaysApply。若强制对齐 Cline，需将 always=True 的 skill 改为 rules 文件，改动涉及 8 个 SKILL.md 重构，成本高于收益。
- 当前 always 字段有实际价值（如 write-report skill 需始终可用），移除会影响功能。

**保留条件**：在文档中明确说明"always 字段是 nanobot 风格残留，非 Cline 对标"，避免误导。若未来要严格对齐 Cline，可将 always=True 的 skill 改为 rules 文件（rules 系统 alwaysApply）。

### 建议 5：不强制对齐全局 skills 目录与 managed plugin [P3 不修复]

**理由**：
- Charles 当前 8 个 skill 全部在 `agent_config/skills/`，无用户级全局 skills 需求。
- managed plugin 是 Cline 企业版功能（manifest 文件管理第三方 skill 包），Charles 无对应场景。
- Charles 的 `load_skills_multi_dir(dirs)` 已支持多目录加载，若未来需要全局 skills，调用方可显式传入 `~/.jike/skills/` 等目录。

**保留条件**：若未来需要支持用户级全局 skills，可扩展 `resolve_skills_search_paths()` 函数聚合多源目录，对标 Cline `resolveSkillsConfigSearchPaths`。

### 建议 6：不强制对齐文件监听与热重载 [P3 不修复]

**理由**：
- Charles 是 Web 请求-响应模型，每次请求重建 registry，等价"每次都热重载"，无需 fs.watch。
- Cline 的 `UnifiedConfigFileWatcher` 是 IDE 场景的设计（VS Code 需要在用户编辑文件时实时更新），Charles 服务端无需此能力。
- Charles 的 rules 系统已有 mtime 缓存（`_RULES_MTIME_CACHE`）减少重复 I/O，若 skills 系统性能瓶颈可复用此模式。

**保留条件**：若未来 skills 数量增长导致每次请求重建 registry 性能问题，可将 rules_loader 的 mtime 缓存模式扩展到 skills 系统。

### 建议 7：补充 instructions body 非空校验 [P2]

**文件**：`agent/skills/loader.py`
**位置**：L221-298 `_parse_skill_file` 方法

**修改方向**：在 `_parse_frontmatter` 返回后，增加 instructions body 非空校验。当前 `_parse_skill_file` 仅解析 frontmatter，不读取 body（body 由 `load_instructions` 单独加载）。可在 `load_instructions` 中增加校验：

```python
def load_instructions(self, name: str) -> str | None:
    skill_file = self.skills_dir / name / "SKILL.md"
    if not skill_file.exists():
        return None
    content = skill_file.read_text(encoding="utf-8")
    instructions = self._strip_frontmatter(content)
    if not instructions.strip():
        logger.warning("Skill %s instructions body is empty", name)
        return None  # 或返回空串，由调用方决定
    # ...
```

**理由**：Cline 在 `parseSkillConfigFromMarkdown`（loader.ts L293-295）显式校验 instructions body 非空并抛错，Charles 缺此校验可能导致空 instructions 被注入 system prompt。

### 建议 8：保留 Charles 额外 metadata 字段 [P0 不变]

**理由**：Charles 的 `keywords` / `capabilities` / `allowed_tools` / `scripts` / `source_dir` / `when_to_use` 字段均有实际用途：
- `keywords` / `capabilities`：用于 fallback 匹配（当 LLM description 不够明确时）
- `allowed_tools`：Phase 20 子 agent 工具白名单（每个 skill 可自定义工具集）
- `scripts`：Phase 33.4 自动发现 .py 脚本（LLM 可直接复制执行）
- `source_dir`：Stage 13.4 多目录加载来源记录
- `when_to_use`：Phase P5 skills_summary 表格"何时使用"列

这些字段是 Charles 的合理扩展，不应为了对齐 Cline 而移除。Cline 的 `frontmatter: Record<string, unknown>` 保留原始数据，理论上也支持这些字段，只是未显式声明。

---

## 六、验证方法建议

### 验证方法 1：frontmatter 解析路径一致性检查

确认 Charles loader.py 的 `_parse_frontmatter` 与 rules_loader.py 的 `parse_yaml_frontmatter` 语义差异：

```powershell
# 检查 loader.py 是否有 fallback 简单解析
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "fallback|简单 YAML 解析|nanobot fallback"
# 预期：L392 匹配 "# Fallback: 简单 YAML 解析 — 对标 nanobot fallback"

# 检查 rules_loader.py 是否有 fallback
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "fallback|简单 YAML 解析"
# 预期：无匹配（rules_loader.py 无 fallback）
```

### 验证方法 2：disabled toggle 写回能力检查

确认 Charles 无 disabled toggle 写回函数：

```powershell
# 检查 loader.py 是否有 toggle / write_back / serialize_frontmatter 函数
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "toggle|write_back|serialize_frontmatter|updateSkillMarkdown"
# 预期：无匹配

# 对比 Cline 的 toggleSkillFrontmatter
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\skill-frontmatter-toggle.ts" -Pattern "toggleSkillFrontmatter|updateSkillMarkdownEnabledState|writeFile"
# 预期：L51 / L76 / L82 匹配
```

### 验证方法 3：always 字段对标位置检查

确认 Cline SkillConfig 无 always 字段，Charles SkillMetadata 有 always 字段：

```powershell
# Cline SkillConfig 字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-config-loader.ts" -Pattern "always" -CaseSensitive:$false
# 预期：无匹配（SkillConfig 无 always 字段）

# Charles SkillMetadata 字段
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "always:\s*bool"
# 预期：L70 匹配 `always: bool = False`
```

### 验证方法 4：全局 skills 目录检查

确认 Cline 有全局 skills 目录解析，Charles 无：

```powershell
# Cline resolveSkillsConfigSearchPaths
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\shared\src\storage\paths.ts" -Pattern "resolveSkillsConfigSearchPaths|HOME_DIR|LEGACY_AGENT_SKILLS"
# 预期：L358 / L363 / L365 匹配

# Charles 是否有全局 skills 目录解析
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "HOME|expanduser|~/.jike|global.*skill"
# 预期：无匹配（Charles 无全局目录解析）
```

### 验证方法 5：文件监听机制检查

确认 Cline 有 UnifiedConfigFileWatcher，Charles 无：

```powershell
# Cline watcher
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\unified-config-file-watcher.ts" -Pattern "class UnifiedConfigFileWatcher|fs\.watch|debounceMs|subscribe|emit\("
# 预期：L94 / L110 / L134 / L160 / L239 匹配

# Charles 是否有 watcher
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "watch|fs\.watch|observer|notify|emit"
# 预期：无匹配（Charles 无文件监听）
```

### 验证方法 6：nanobot 残留扫描

```powershell
# loader.py 应为 8 处（7 注释 + 1 实现逻辑）
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期：L2 / L29 / L48 / L96 / L167 / L222 / L392 / L423 共 8 处匹配

# rules_loader.py 应为 0 处
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\rules_loader.py" -Pattern "nanobot" -CaseSensitive:$false
# 预期：无匹配
```

### 验证方法 7：fallback 简单解析实现逻辑残留检查

确认 L392-420 的 fallback 简单解析是实际运行的代码逻辑：

```powershell
# 检查 fallback 分支是否有 except Exception: pass 进入
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "except Exception|pass|Fallback" -Context 0,2
# 预期：L389-390 `except Exception: pass` + L392 `# Fallback: 简单 YAML 解析`

# 检查 fallback 分支的解析逻辑
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "current_key|stripped.startswith|metadata\[current_key\]"
# 预期：L394 / L400 / L403 / L405 匹配（fallback 简单解析的实际代码）
```

### 验证方法 8：Cline managed plugin 检查

确认 Cline 有 managed plugin 概念，Charles 无：

```powershell
# Cline managed plugin
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\third_party\cline\sdk\packages\core\src\extensions\config\user-instruction-config-loader.ts" -Pattern "managed|managedPlugin|managed\.json|discoverManagedPluginRoots"
# 预期：L25 / L156 / L167 / L388 等多处匹配

# Charles managed plugin
Select-String -Path "e:\jikeAI\code\CASE-AI量化系统\agent\skills\loader.py" -Pattern "managed|manifest"
# 预期：无匹配
```

---

## 七、附录：源码引用索引

### Cline 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L24 | `SKILL_FILE_NAME = "SKILL.md"` 常量 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L35-40 | `ParseMarkdownFrontmatterResult` 接口（data / body / hadFrontmatter / parseError） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L42-48 | `SkillConfig` 接口（name / description / disabled / instructions / frontmatter，**无 always 字段**） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L84-91 | `CreateSkillsConfigDefinitionOptions`（directories / pluginSkillDirectories / includePluginSkills / pluginPaths / workspacePath / cwd） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L107-115 | `isIgnorableDirectoryError` 错误分类处理 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L121-133 | `dedupeDirectoryPaths` 目录去重 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L135-154 | `resolveSkillDirectories` 多源目录解析 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L156-192 | `discoverManagedPluginRoots` managed plugin manifest 扫描 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L194-225 | `parseMarkdownFrontmatter` 单路径 YAML 解析（无 fallback） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L227-259 | `parseStringField` / `parseBooleanField` 严格类型校验 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L284-311 | `parseSkillConfigFromMarkdown` SKILL.md 解析入口（含 instructions body 非空校验 + name 缺失校验） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L367-371 | `resolveSkillsConfigSearchPaths` 转发到 shared/storage/paths.ts |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L385-437 | `discoverSkillFiles` 目录扫描（含 symlink 处理 + managed plugin 嵌套） |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L526-548 | `createSkillsConfigDefinition` 技能配置定义工厂 |
| `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L608-634 | `createUserInstructionConfigWatcher` 创建 watcher |
| `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L1-49 | `toggleSkillFrontmatter` / `updateSkillMarkdownEnabledState` / `serializeMarkdownFrontmatter` disabled toggle 写回 |
| `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L51-74 | `updateSkillMarkdownEnabledState` enabled 时清理 disabled/enabled 字段，disabled 时设置 `data.disabled = true` |
| `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L76-89 | `toggleSkillFrontmatter` 读 → 改 → 写回文件 |
| `sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts` | L94-158 | `UnifiedConfigFileWatcher` 类定义 + 构造函数（debounceMs 默认 75） |
| `sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts` | L160-248 | `subscribe` / `start` / `stop` / `refreshAll` / `getSnapshot` / `emit` 生命周期与事件流 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L14-23 | `SkillsExecutorMetadataItem` / `ConfiguredSkill` 类型 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L39-73 | `toAllowedSkillSet` / `isSkillAllowed` 白名单 4 形式匹配 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L75-93 | `getConfiguredSkillsFromWatcher` 从 watcher snapshot 提取 ConfiguredSkill 列表 |
| `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L100 | `.filter((skill) => !skill.disabled)` disabled 过滤 |
| `sdk/packages/shared/src/storage/paths.ts` | L358-370 | `resolveSkillsConfigSearchPaths` 多源目录聚合（workspace + ~/.cline/skills + ~/.agent/skills） |

### Charles 源码

| 文件 | 关键行 | 内容 |
|------|-------|------|
| `agent/skills/loader.py` | L1-32 | 模块 docstring（含 nanobot 残留 L2 / L29-31） |
| `agent/skills/loader.py` | L46-81 | `SkillMetadata` dataclass（11+ 字段，含 always / keywords / capabilities / allowed_tools / scripts / source_dir / when_to_use） |
| `agent/skills/loader.py` | L84-92 | `_strip_utf8_bom` BOM 剥离（对标 Cline stripUtf8Bom） |
| `agent/skills/loader.py` | L95-117 | `SkillLoader.__init__` 初始化（单目录 + _cache 字典） |
| `agent/skills/loader.py` | L119-144 | `list_skills` 扫描目录（sorted iterdir + is_dir 过滤，返回含 disabled 的全部技能） |
| `agent/skills/loader.py` | L146-157 | `get_skill` 单技能查询（含 _cache 命中） |
| `agent/skills/loader.py` | L159-184 | `load_instructions` Level 2 加载（含 _strip_frontmatter + scripts block 追加） |
| `agent/skills/loader.py` | L186-212 | `_get_skill_scripts` / `_build_scripts_block` 脚本路径提示块 |
| `agent/skills/loader.py` | L221-298 | `_parse_skill_file` SKILL.md 解析（含 disabled / enabled 兼容 + scripts 自动发现 + when_to_use 提取） |
| `agent/skills/loader.py` | L300-342 | `_discover_scripts` 递归扫描 .py 文件 |
| `agent/skills/loader.py` | L344-362 | `_find_project_root` 向上查找项目根目录 |
| `agent/skills/loader.py` | L364-420 | `_parse_frontmatter` YAML 解析（PyYAML + **nanobot fallback 简单解析 L392-420**） |
| `agent/skills/loader.py` | L422-434 | `_strip_frontmatter` 去除 frontmatter |
| `agent/skills/loader.py` | L443-485 | `load_skills_multi_dir` 多目录加载（后覆盖前 + source_dir 记录 + override 日志） |
| `agent/skills/loader.py` | L488-508 | `load_skills_with_dirs` primary_dir 优先级最高封装 |
| `agent/rules_loader.py` | L131-181 | `parse_yaml_frontmatter` 独立 fail-open 解析路径（无 fallback，返回 FrontmatterParseResult） |
| `agent/rules_loader.py` | L65 | `_RULES_MTIME_CACHE` 模块级 mtime 缓存（仅 rules 系统） |
| `agent/rules_loader.py` | L524-556 | `_read_with_mtime_cache` mtime 缓存读取 |
| `agent/skills/registry.py` | L99-128 | `SkillRegistry.__init__`（含 allowed_skill_names 白名单） |
| `agent/skills/registry.py` | L130-158 | `discover` / `list_skills`（白名单 + disabled 过滤） |
| `agent/skills/registry.py` | L183-208 | `get_always_skills` / `load_always_instructions` always 技能预加载（对标 nanobot get_always_skills） |

---

## 八、结论

P4.2 技能加载器对比的核心结论：

### 8.1 核心解析路径已对齐

1. **frontmatter 正则对齐**：两侧均用 `^---\r?\n(...)\r?\n---\r?\n?` 正则，支持 CRLF（Stage 31.4 / I12 已对齐）。
2. **BOM 剥离对齐**：两侧均处理 Windows Notepad "UTF-8 with BOM"（Charles `_strip_utf8_bom` 对标 Cline `stripUtf8Bom`）。
3. **SKILL.md 文件名对齐**：两侧均硬编码 `"SKILL.md"`。
4. **目录形式对齐**：两侧均仅支持 `skills/<name>/SKILL.md` 目录形式。
5. **多源加载 + 后覆盖前对齐**：两侧均支持多目录加载 + 后写覆盖（Charles Stage 13.4 已对齐）。
6. **disabled 字段读取对齐**：两侧均支持 `disabled: true` 和 `enabled: false` 两种写法（Stage 31.4 已对齐）。

### 8.2 系统性差异（5 项）

1. **frontmatter 解析双路径分裂**（4.2.11 / 4.2.16 / 4.2.17）：Charles `loader.py` 有 nanobot fallback 简单解析（**实现逻辑残留**），`rules_loader.py` 无 fallback。Cline 单路径无 fallback。**建议 P2 级别统一**。
2. **disabled toggle 写回缺失**（4.2.24 - 4.2.27）：Cline 有 `toggleSkillFrontmatter` 写回文件，Charles 仅读取 disabled 字段。**建议 P3 不强制对齐**。
3. **always 字段反向差异**（4.2.29 - 4.2.33）：Cline SkillConfig 无 always 字段（skills 永远 on-demand），Charles 有 always 字段（对标 nanobot get_always_skills）。**建议 P3 不强制对齐**，文档说明即可。
4. **全局 skills 目录与 managed plugin 缺失**（4.2.1 / 4.2.5 / 4.2.7）：Cline 聚合 workspace + ~/.cline/skills + ~/.agent/skills + managed plugin，Charles 仅单目录。**建议 P3 不强制对齐**。
5. **文件监听与热重载缺失**（4.2.48 - 4.2.54）：Cline 有 `UnifiedConfigFileWatcher`（fs.watch + 75ms debounce + 事件流），Charles 无。**建议 P3 不强制对齐**（请求-响应模型天然等价热重载）。

### 8.3 Charles 独有扩展（合理保留）

- `always` 字段 + `load_always_instructions` 预加载（对标 nanobot，量化场景有实际价值）
- `keywords` / `capabilities` 字段（fallback 匹配）
- `allowed_tools` 字段（Phase 20 子 agent 工具白名单）
- `scripts` 字段 + `_discover_scripts` 自动发现 .py（Phase 33.4）
- `source_dir` 字段（Stage 13.4 多目录加载来源记录）
- `when_to_use` 字段（Phase P5 skills_summary 表格）
- `load_skills_multi_dir` / `load_skills_with_dirs` 多源加载便捷封装

### 8.4 nanobot 残留总结

- **`agent/skills/loader.py`**：8 处残留 = 7 注释 + **1 实现逻辑**（L392-420 fallback 简单 YAML 解析）。建议 P2 级别清理。
- **`agent/rules_loader.py`**：0 处残留，完全对标 Cline fail-open 语义。

### 8.5 整体一致性等级

- **核心解析路径**（frontmatter 正则 + BOM + CRLF + SKILL.md 文件名 + 目录形式 + 多源覆盖 + disabled 读取）：**高一致性**。
- **目录扫描覆盖面**（全局目录 + managed plugin）：**低一致性**。
- **disabled toggle 写回**：**低一致性**。
- **热重载**：**低一致性**（架构差异，非缺陷）。
- **metadata 字段集合**：**中低一致性**（Charles 多出 7+ 字段，均为合理扩展）。
- **always 字段**：**反向差异**（Charles 独有，方向与 Cline 相反）。
- **错误处理**：**中一致性**（Cline 严格抛错，Charles fail-silent）。
- **frontmatter 解析路径统一性**：**低一致性**（Charles 双路径分裂，loader.py 有 nanobot fallback）。

### 8.6 阻塞性问题

**无阻塞性问题**。所有差异均为已知设计选择或 nanobot 残留，不影响现有功能：
- frontmatter 解析双路径分裂在 PyYAML 正常工作时无影响（fallback 仅在 PyYAML 失败时触发）。
- disabled toggle 写回缺失不影响 skill 加载（仅影响 UI toggle 持久化）。
- always 字段反向差异是合理设计选择（量化场景需 always skill）。
- 全局 skills 目录缺失不影响当前 8 个 skill 的加载。
- 文件监听缺失不影响请求-响应模型的热重载（每次请求重建 registry）。

所有修复建议均为 P2 / P3 级别，可在后续清理批次中统一处理。**P2 优先项**：清理 loader.py 的 nanobot fallback 简单解析（实现逻辑残留）+ 7 处注释残留 + 补充 instructions body 非空校验。
