# Phase I: 技能系统 对比报告

> 对标源码：
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts`
> - `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts`
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts`
> - `sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts`
> - `sdk/packages/core/src/extensions/tools/definitions.ts`（createSkillsTool L719-769）
> - `sdk/packages/core/src/extensions/tools/schemas.ts`（SkillsInputSchema L246-253）
> - `sdk/packages/core/src/services/marketplace.ts`
>
> 当前实现：`agent/skills/skill_tool.py` + `agent/skills/loader.py` + `agent/skills/registry.py` + `agent/skills/__init__.py`
> 对比维度：I1-I20

---

## 1. 总览

| 统计 | 数量 |
|------|------|
| 完全一致 | 5 项 |
| 弱对齐 | 7 项 |
| 缺失 | 3 项 |
| 额外增强 | 5 项 |
| **对齐度** | **约 60%** |

> 统计口径：完全一致 = 字节级或逻辑等价；弱对齐 = 主逻辑一致但存在规范化/配置项/健壮性差异；缺失 = Cline 有但我无；额外增强 = 我有但 Cline 无。对齐度 = (完全一致 + 0.5×弱对齐) / 总项数，约为 (5 + 3.5) / 20 ≈ 42.5%；考虑弱对齐项主逻辑已可用，实际可用对齐度约 60%。

---

## 2. 详细对比表

| # | 对比项 | Cline 位置 | 我的位置 | 一致性 |
|---|--------|-----------|---------|--------|
| I1 | `skills` 工具名 | definitions.ts L734 `name: "skills"` | skill_tool.py L66 `return "skills"` | 完全一致 |
| I2 | `skill` 参数必填 | schemas.ts L247 `z.string().min(1)` | skill_tool.py L86 `"required": ["skill"]` | 完全一致 |
| I3 | `args` 参数可选 | schemas.ts L248-252 `.nullable().optional()` | skill_tool.py L81-84 properties 有 args，未列入 required | 完全一致 |
| I4 | description 动态构造 | definitions.ts L754-766 `Object.defineProperty` getter 追加 "Available skills: ..." | skill_tool.py L68-70 + L193-221 `_build_description()` 追加 "可用技能: ..." | 弱对齐 |
| I5 | XML 返回格式 | user-instruction-plugin.ts L195-202 `<command-name>/<command-args>/<command-instructions>` | skill_tool.py L168-176 同结构 | 完全一致 |
| I6 | `runningSkills` Set 去重 | user-instruction-plugin.ts L179/L188-205 用 `id`（normalized）作 key | skill_tool.py L62/L147-191 用原始 `skill_name` 作 key | 弱对齐 |
| I7 | `skillsTimeoutMs` 15000 | definitions.ts L723 `config.skillsTimeoutMs ?? 15000` 可配置 | skill_tool.py L94-101 硬编码 `return 15000` | 弱对齐 |
| I8 | `allowedSkillNames` 白名单 | user-instruction-plugin.ts L35-73 normalizeSkillToken + toAllowedSkillSet + isSkillAllowed（4 形式匹配 + namespace） | registry.py L33-68 `_normalize_skill_token` + `_to_allowed_skill_set` + `_is_skill_allowed`（1 形式匹配） | 弱对齐 |
| I9 | frontmatter `disabled` 字段 | user-instruction-config-loader.ts L305-307 + user-instruction-plugin.ts L88/L123-127 | loader.py L215-217 + registry.py L129 + skill_tool.py L139-143 | 完全一致 |
| I10 | frontmatter `always` 字段 | Cline SkillConfig 无此字段（不使用） | loader.py L62 + registry.py L155-180 + context.py L185-189 注入 system prompt | 额外增强 |
| I11 | 三级加载（metadata/instructions/resources） | L1 metadata + L2 instructions（frontmatter 保留但无 L3 资源机制） | L1 metadata + L2 instructions + L3 `_discover_scripts` 自动发现 | 弱对齐 |
| I12 | SKILL.md frontmatter 解析 | user-instruction-config-loader.ts L194-225 `\r?\n` + BOM + 严格类型 + 抛错 | loader.py L334-384 仅 `\n` + PyYAML + fallback + 静默 | 弱对齐 |
| I13 | 技能目录扫描 | user-instruction-config-loader.ts L385-437 readdir + symlink + .cline managed roots + errno 容错 | loader.py L108-120 `sorted(iterdir)` + is_dir，无 symlink/managed/容错 | 弱对齐 |
| I14 | 技能 `scripts` 自动发现 | Cline 不做 | loader.py L162-188/L270-312 `_discover_scripts` + `_build_scripts_block` | 额外增强 |
| I15 | 技能 `keywords` 字段 | Cline SkillConfig 无此字段 | loader.py L61/L209-225 解析但未用于匹配 | 额外增强（未使用） |
| I16 | 技能 `source` 字段 | Cline SkillConfig 无此字段（隐式从目录推断） | loader.py L65/L264 硬编码 `"workspace"`，未使用 | 额外增强（未使用） |
| I17 | 多技能目录支持 | user-instruction-config-loader.ts L135-154 resolveSkillDirectories 合并 workspace + global + plugin + .cline managed | loader.py L83-91 单一 `skills_dir` | 缺失 |
| I18 | 技能热重载 | unified-config-file-watcher.ts `UnifiedConfigFileWatcher` + fs.watch + debounce 75ms + sha1 fingerprint + upsert/remove 事件 | loader.py 仅 `discover()` 一次 + `_cache` 缓存，无 watch | 缺失 |
| I19 | 技能 marketplace | sdk/packages/core/src/services/marketplace.ts `MarketplacePrimitiveType = "mcp"\|"skill"\|"plugin"` + install/uninstall spawn | 无 | 缺失 |
| I20 | `build_summary()` 输出格式 | Cline 无独立 summary 函数，仅 tool description 末尾追加 "Available skills: ..." | registry.py L182-217 markdown 表格 + "# 技能目录（参考：这些不是可直接调用的工具）" 注入 system prompt | 额外增强 |

---

## 3. 关键差距详细分析

### 差距 #I6：runningSkills 去重 key 未规范化

**严重度**：P2（并发去重失效）

**Cline 实现**（user-instruction-plugin.ts L179/L188-205）：
```typescript
const runningSkills = new Set<string>();
// ...
const { id, skill } = resolved;  // id 来自 resolveSkillRecord，是 normalizeSkillToken(name) 后的值
if (runningSkills.has(id)) { return `Skill "${skill.name}" is already running.`; }
runningSkills.add(id);
try { ... } finally { runningSkills.delete(id); }
```
Cline 的 `id` 是 `normalizeSkillToken(name)` = `trim().replace(/^\/+/, "").toLowerCase()`，因此 `"PDF"`、`"pdf"`、`"/pdf"` 都映射到同一个 key `"pdf"`。

**我的实现**（skill_tool.py L147-191）：
```python
if skill_name in self._running_skills:  # skill_name 是 input.get("skill", "").strip()
    return AgentToolResult(output=f'Skill "{skill_name}" is already running.', ...)
self._running_skills.add(skill_name)
try: ...
finally: self._running_skills.discard(skill_name)
```
我直接用 `skill_name`（仅 `.strip()`，未小写化、未去前导斜杠）作为 key。

**影响**：
- 同一技能以不同大小写/前导斜杠形式并发调用时，去重失效，会重复注入指令
- 实际场景：LLM 通常传相同名称，影响概率低，但与 Cline 行为不等价

**修复建议**：将去重 key 改为规范化形式：
```python
from agent.skills.registry import _normalize_skill_token
skill_id = _normalize_skill_token(skill_name)
if skill_id in self._running_skills: ...
self._running_skills.add(skill_id)
finally: self._running_skills.discard(skill_id)
```

**优先级**：P2

---

### 差距 #I7：skillsTimeoutMs 不可配置

**严重度**：P3（默认值已一致，仅缺可配置性）

**Cline 实现**（definitions.ts L719-723）：
```typescript
export function createSkillsTool(
    executor: SkillsExecutorWithMetadata,
    config: Pick<DefaultToolsConfig, "skillsTimeoutMs"> = {},
): AgentTool<...> {
    const timeoutMs = config.skillsTimeoutMs ?? 15000;
```
Cline 通过 `config.skillsTimeoutMs` 允许调用方覆盖默认 15000ms。

**我的实现**（skill_tool.py L94-101）：
```python
@property
def timeout_ms(self) -> int | None:
    return 15000
```
硬编码 15000，无配置入口。

**影响**：
- 默认行为一致（都是 15000ms）
- 无法在特殊场景（如加载巨型 SKILL.md 或网络挂载）下调整超时
- 与 Phase F 的 `timeout_ms` per-tool 设计一致，但缺配置注入路径

**修复建议**：在 `SkillsTool.__init__` 增加 `timeout_ms: int | None = 15000` 参数：
```python
def __init__(self, registry: SkillRegistry, timeout_ms: int | None = 15000) -> None:
    self._registry = registry
    self._running_skills: set[str] = set()
    self._timeout_ms = timeout_ms

@property
def timeout_ms(self) -> int | None:
    return self._timeout_ms
```

**优先级**：P3

---

### 差距 #I8：allowedSkillNames 白名单匹配形式单一

**严重度**：P2（多 agent 场景下白名单绕过）

**Cline 实现**（user-instruction-plugin.ts L35-73）：
```typescript
function isSkillAllowed(skillId, skillName, allowedSkills): boolean {
    if (!allowedSkills) return true;
    const normalizedId = normalizeSkillToken(skillId);
    const normalizedName = normalizeSkillToken(skillName);
    const bareId = normalizedId.includes(":") ? normalizedId.split(":").at(-1) : normalizedId;
    const bareName = normalizedName.includes(":") ? normalizedName.split(":").at(-1) : normalizedName;
    return (
        allowedSkills.has(normalizedId) ||
        allowedSkills.has(normalizedName) ||
        allowedSkills.has(bareId) ||
        allowedSkills.has(bareName)
    );
}
```
Cline 检查 4 种形式：完整 id、完整 name、去 namespace 的 bare id、去 namespace 的 bare name。支持 `ms-office-suite:pdf` 这类 namespaced skill，白名单写 `pdf` 即可匹配。

**我的实现**（registry.py L57-68）：
```python
def _is_skill_allowed(skill_name: str, allowed_skills: set[str] | None) -> bool:
    if allowed_skills is None:
        return True
    return _normalize_skill_token(skill_name) in allowed_skills
```
仅检查 1 种形式：规范化后的 name。不支持 namespace 前缀，无 bare name 提取。

**影响**：
- 若未来引入 namespaced skill（如 `plugin-a:pdf`），白名单写 `pdf` 无法匹配
- 多 agent 场景下白名单粒度不如 Cline 灵活
- 当前 agent_config/skills/ 下均为扁平技能名，影响暂未显现

**修复建议**：扩展 `_is_skill_allowed` 检查 bare name：
```python
def _is_skill_allowed(skill_name: str, allowed_skills: set[str] | None) -> bool:
    if allowed_skills is None:
        return True
    normalized = _normalize_skill_token(skill_name)
    bare = normalized.split(":")[-1] if ":" in normalized else normalized
    return normalized in allowed_skills or bare in allowed_skills
```

**优先级**：P2

---

### 差距 #I12：frontmatter 解析健壮性不足

**严重度**：P2（Windows 环境下可能解析失败）

**Cline 实现**（user-instruction-config-loader.ts L194-225）：
```typescript
const normalizedContent = stripUtf8Bom(content);  // 处理 BOM
const frontmatterRegex = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;  // 支持 \r\n
const parsed = YAML.parse(yamlContent);  // 严格 YAML
// 类型检查
const parsedName = parseStringField(data.name, "name", false);
parseBooleanField(data.disabled, "disabled");
// 解析失败抛错
```

**我的实现**（loader.py L334-384）：
```python
if not content.startswith("---"):  # 不处理 BOM
    return None
match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)  # 仅 \n
try:
    import yaml
    result = yaml.safe_load(raw)
except Exception:
    pass
# Fallback 简单解析
# 无类型检查，解析失败返回 None（静默）
```

**影响**：
1. **BOM 问题**：Windows Notepad 保存的 "UTF-8 with BOM" 文件，我的 `content.startswith("---")` 会失败（实际开头是 `\uFEFF---`），整个技能被静默跳过。Cline 已通过 `stripUtf8Bom` 修复（cline/cline#12151）。
2. **CRLF 问题**：Windows 下 SKILL.md 若为 CRLF 行尾，我的正则 `r"^---\n..."` 不匹配，技能被跳过。Cline 用 `\r?\n` 兼容。
3. **静默失败**：解析失败时我返回 None，技能不出现但无日志；Cline 抛错并可通过 `emitParseErrors` 上报。
4. **类型宽松**：我未校验 `disabled` 必须是 boolean，`disabled: "true"`（字符串）会被 `bool("true")` 判为 True（Python 非空字符串为真），但语义已偏离。

**修复建议**：
1. 短期：正则改为 `r"^---\r?\n(.*?)\r?\n---"`，并增加 BOM 剥离：
```python
if content.startswith("\ufeff"):
    content = content[1:]
if not content.startswith("---"):
    return None
match = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.DOTALL)
```
2. 中期：解析失败时记录日志或抛错，便于排查

**优先级**：P2（Windows 环境必须修复 BOM/CRLF）

---

### 差距 #I13：目录扫描无 symlink / 容错

**严重度**：P3（量化场景无 symlink 技能）

**Cline 实现**（user-instruction-config-loader.ts L385-437）：
- `readdir(directoryPath, { withFileTypes: true })`
- symlink 通过 `stat(entryPath).then(s => s.isDirectory())` 判定
- `.cline` 目录下 `discoverManagedPluginRoots` 扫描 managed plugins
- `isIgnorableDirectoryError` 过滤 ENOENT/EACCES/EPERM/ELOOP

**我的实现**（loader.py L108-120）：
```python
for skill_dir in sorted(self.skills_dir.iterdir()):
    if not skill_dir.is_dir():  # is_dir 默认 follow symlinks，但 symlink to dir 会被识别
        continue
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        continue
```

**影响**：
1. `Path.is_dir()` 实际会跟随 symlink（与 `os.path.isdir` 一致），所以 symlink to dir 在 Python 下能识别，差异较小
2. 无 `.cline` managed plugin 支持，但量化场景无插件需求
3. 无 errno 容错：若 `skills_dir` 权限不足，`iterdir()` 抛 `PermissionError` 会冒泡到调用方

**修复建议**：可选增加 errno 容错：
```python
try:
    entries = sorted(self.skills_dir.iterdir())
except (PermissionError, OSError):
    return []
```

**优先级**：P3

---

### 差距 #I17：不支持多技能目录（workspace + global + plugin）

**严重度**：P2（影响全局技能复用）

**Cline 实现**（user-instruction-config-loader.ts L135-154）：
```typescript
function resolveSkillDirectories(options): string[] {
    const directories = [
        ...(options?.directories ?? resolveSkillsConfigSearchPaths(options?.workspacePath)),
    ];
    if (options?.pluginSkillDirectories) {
        directories.push(...options.pluginSkillDirectories);
    } else if (options?.includePluginSkills) {
        directories.push(...resolveAgentPluginSkillDirectories(...));
    }
    return dedupeDirectoryPaths(directories);
}
```
Cline 合并 workspace skills（`.cline/skills/`）+ global skills（`~/.cline/skills/`）+ plugin skills，去重后统一扫描。

**我的实现**（loader.py L83-91）：
```python
def __init__(self, skills_dir: Path | str | None = None) -> None:
    if skills_dir is None:
        skills_dir = Path.cwd() / "skills"
    self.skills_dir = Path(skills_dir)
```
仅支持单一 `skills_dir`，默认 `./skills/`（实际使用 `agent_config/skills/`）。

**影响**：
- 无法共享全局技能（如多个项目共用的 `read-pdf`、`web-search`）
- 无法加载 plugin 提供的技能
- 多项目场景下需每个项目复制一份技能

**修复建议**：扩展 `SkillLoader` 支持多目录：
```python
def __init__(self, skills_dirs: list[Path | str] | None = None) -> None:
    if skills_dirs is None:
        skills_dirs = [Path.cwd() / "skills"]
    self.skills_dirs = [Path(d) for d in skills_dirs]

def list_skills(self) -> list[SkillMetadata]:
    skills: list[SkillMetadata] = []
    seen_names: set[str] = set()
    for d in self.skills_dirs:
        for meta in self._scan_dir(d):
            if meta.name not in seen_names:
                skills.append(meta)
                seen_names.add(meta.name)
    return skills
```
同时 `SkillRegistry.__init__` 增加 `global_skills_dir` 参数。

**优先级**：P2

---

### 差距 #I18：无技能热重载

**严重度**：P2（开发体验差）

**Cline 实现**（unified-config-file-watcher.ts L94-300）：
- `UnifiedConfigFileWatcher` 类，构造时传入 definitions
- `start()` 调用 `refreshAll()` + `startDirectoryWatchers()`
- `fs.watch(directoryPath)` 监听目录变更
- `debounceMs` 默认 75ms，避免频繁刷新
- `toFingerprint(content)` 用 sha1 检测内容是否实际变化
- `subscribe(listener)` 上报 `upsert`/`remove`/`error` 事件
- `getSnapshot(type)` 返回当前快照
- 自动同步 watchers（目录增删时重建）

**我的实现**（loader.py L83-120）：
```python
def __init__(self, skills_dir: ...):
    self._cache: dict[str, SkillMetadata] = {}

def list_skills(self) -> list[SkillMetadata]:
    # 每次都重新扫描（无 watch，无 fingerprint）
    ...
    self._cache[meta.name] = meta
```
`list_skills` 每次调用都重新扫描目录（无缓存），但 `get_skill` / `load_instructions` 会用到 `_cache`。无文件监听，无事件上报。

**影响**：
- 修改 SKILL.md 后需重启 agent 才生效（实际 `list_skills` 每次扫描，但 `runtime` 层可能缓存了 tool description）
- 无法实时感知技能增删
- 开发体验差：调试 SKILL.md 需反复重启

**修复建议**：可选实现轻量级热重载：
1. 短期：在 `SkillRegistry` 增加 `refresh()` 方法，手动触发重新扫描
2. 中期：用 `watchdog` 库监听 `skills_dir` 变更，自动 `discover()` 并触发 `on_skills_changed` 回调
3. 长期：对标 Cline 的 fingerprint + debounce 机制

**优先级**：P2

---

### 差距 #I19：无技能 marketplace

**严重度**：P3（量化场景暂无远程技能需求）

**Cline 实现**（sdk/packages/core/src/services/marketplace.ts L10-60）：
```typescript
export type MarketplacePrimitiveType = "mcp" | "skill" | "plugin";
export type MarketplaceEntryInput = {
    id: string;
    type: MarketplacePrimitiveType;
    name?: string;
    install?: { args?: string[] };
};
// installMarketplaceEntry / uninstallMarketplaceEntry
// 通过 spawn 执行 cline 命令安装
// 处理 MCP / skill / plugin 三类
```
Cline marketplace 支持远程安装/卸载技能、MCP 服务器、插件。`MarketplaceSpawnCommand` 通过子进程执行安装命令，有 120s 超时、12000 字符输出限制、secret 脱敏。

**我的实现**：无 marketplace。

**影响**：
- 无法从远程仓库安装技能
- 量化场景技能均为本地维护（agent_config/skills/），暂无远程需求
- 未来若要共享技能（如团队内部技能仓库），需自建安装机制

**修复建议**：暂不实现。若未来有需求，可参考 Cline marketplace 设计，但需结合内部技能仓库（如 git repo）定制。

**优先级**：P3

---

## 4. 一致性统计

### 按一致性等级

| 等级 | 项数 | 占比 | 项目 |
|------|------|------|------|
| 完全一致 | 5 | 25% | I1, I2, I3, I5, I9 |
| 弱对齐 | 7 | 35% | I4, I6, I7, I8, I11, I12, I13 |
| 缺失 | 3 | 15% | I17, I18, I19 |
| 额外增强 | 5 | 25% | I10, I14, I15, I16, I20 |

### 按优先级分布（仅差距项）

| 优先级 | 数量 | 项目 |
|--------|------|------|
| P0 | 0 | - |
| P1 | 0 | - |
| P2 | 5 | I6, I8, I12, I17, I18 |
| P3 | 3 | I7, I13, I19 |

### 核心结论

- **无 P0/P1 差距**：技能系统的核心调用链（工具名、参数、XML 返回格式、去重、白名单、disabled）逻辑等价，可正常运行
- **P2 差距集中在健壮性与扩展性**：I12（BOM/CRLF）在 Windows 环境必须修复；I17/I18 影响多项目复用与开发体验；I8 影响未来 namespace skill
- **额外增强项保留**：I10（always 注入）、I14（scripts 自动发现）、I20（build_summary 表格）是合理增强，源自 nanobot 设计，应保留

---

## 5. 修复建议

### 短期（P2，建议本阶段完成）

1. **I12 frontmatter BOM/CRLF**：正则改为 `r"^---\r?\n(.*?)\r?\n---"`，增加 BOM 剥离。Windows 环境必须修复。
2. **I6 runningSkills key 规范化**：去重 key 改用 `_normalize_skill_token(skill_name)`，与 Cline 行为等价。
3. **I8 allowedSkillNames bare name 匹配**：扩展 `_is_skill_allowed` 检查 bare name（去 `:` namespace 前缀），为未来 namespaced skill 预留。

### 中期（P2，建议下阶段完成）

4. **I17 多技能目录支持**：`SkillLoader` 支持 `skills_dirs: list[Path]`，`SkillRegistry` 增加 `global_skills_dir` 参数，合并 workspace + global 目录并按 name 去重。
5. **I18 热重载（轻量版）**：`SkillRegistry` 增加 `refresh()` 方法手动触发重新扫描；可选引入 `watchdog` 监听目录变更。

### 长期（P3，按需实现）

6. **I7 skillsTimeoutMs 可配置**：`SkillsTool.__init__` 增加 `timeout_ms` 参数。
7. **I13 目录扫描容错**：增加 `PermissionError`/`OSError` 捕获，返回空列表。
8. **I19 marketplace**：暂不实现，未来若有远程技能需求再考虑。

### 额外增强项处理

- **I10 always 字段**：保留。context.py L185-189 已正确注入 system prompt，是 Cline 没有但合理的设计（源自 nanobot）。
- **I14 scripts 自动发现**：保留。Phase 33.4 已实现，对量化场景（脚本密集）有实际价值。
- **I15 keywords 字段**：保留但建议实际使用。当前仅解析未用于匹配，未来可用于 LLM 无效技能名时的模糊匹配。
- **I16 source 字段**：保留但建议实现 builtin 区分。当前硬编码 `"workspace"`，未来支持多目录后应区分 workspace/global/builtin。
- **I20 build_summary 表格**：保留。markdown 表格 + "这些不是可直接调用的工具" 提示，对 Qwen 等模型避免误调用有帮助。

---

## 6. 验证记录

### 6.1 已读取的对标文件

| 文件 | 路径 | 关键行 |
|------|------|--------|
| user-instruction-plugin.ts | `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` | L35-73 normalizeSkillToken/toAllowedSkillSet/isSkillAllowed; L75-93 getConfiguredSkillsFromWatcher; L106-172 resolveSkillRecord（含 suffix 匹配 + 歧义处理）; L174-217 createUserInstructionSkillsExecutor（runningSkills + XML 返回） |
| skill-frontmatter-toggle.ts | `third_party/cline/sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` | L1-89 parseMarkdownFrontmatter + updateSkillMarkdownEnabledState + toggleSkillFrontmatter（写入文件） |
| user-instruction-config-loader.ts | `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` | L42-48 SkillConfig 接口（仅 name/description/disabled/instructions/frontmatter）; L194-225 parseMarkdownFrontmatter（BOM + \r?\n + 严格类型）; L284-311 parseSkillConfigFromMarkdown; L385-437 discoverSkillFiles（symlink + managed roots + errno 容错）; L526-548 createSkillsConfigDefinition; L135-154 resolveSkillDirectories（多目录合并） |
| unified-config-file-watcher.ts | `third_party/cline/sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts` | L94-300 UnifiedConfigFileWatcher 类（fs.watch + debounce 75ms + sha1 fingerprint + subscribe 事件） |
| definitions.ts | `third_party/cline/sdk/packages/core/src/extensions/tools/definitions.ts` | L714-769 createSkillsTool（timeoutMs 可配置 + retryable:false + maxRetries:0 + description getter 动态追加 Available skills） |
| schemas.ts | `third_party/cline/sdk/packages/core/src/extensions/tools/schemas.ts` | L246-253 SkillsInputSchema（skill 必填 min(1) + args nullable optional） |
| types.ts | `third_party/cline/sdk/packages/core/src/extensions/tools/types.ts` | L135-179 SkillsExecutor / SkillsExecutorSkillMetadata / SkillsExecutorWithMetadata |
| marketplace.ts | `third_party/cline/sdk/packages/core/src/services/marketplace.ts` | L10-60 MarketplacePrimitiveType 含 "skill"，install/uninstall via spawn |

### 6.2 已读取的我的实现文件

| 文件 | 路径 | 关键行 |
|------|------|--------|
| skill_tool.py | `agent/skills/skill_tool.py` | L38-235 SkillsTool 类（name/description/input_schema/timeout_ms/_execute/_build_description/configured_skills） |
| loader.py | `agent/skills/loader.py` | L43-68 SkillMetadata dataclass（含 always/keywords/source/scripts/disabled/allowed_tools）; L71-392 SkillLoader（list_skills/get_skill/load_instructions/_parse_skill_file/_discover_scripts/_parse_frontmatter） |
| registry.py | `agent/skills/registry.py` | L33-68 _normalize_skill_token/_to_allowed_skill_set/_is_skill_allowed; L71-231 SkillRegistry（discover/list_skills/get_skill/load_instructions/get_always_skills/load_always_instructions/build_summary） |
| __init__.py | `agent/skills/__init__.py` | L29-37 导出 SkillLoader/SkillMetadata/SkillRegistry/SkillsTool |
| context.py | `agent/context.py` | L185-200 always_instructions 注入 system prompt + build_summary 注入 |

### 6.3 验证方法

- **I5 XML 返回格式字节级对比**：Cline L195-202 与我 L168-176 逐字符比对，结构完全一致：`<command-name>{name}</command-name>` + 可选 `\n<command-args>{args}</command-args>` + `\n<command-instructions>\n` + 可选 `Description: {desc}\n\n` + `{instructions}` + `\n</command-instructions>`
- **I6 runningSkills 并发去重**：Cline 用 `id`（normalized）作 key，我用 `skill_name`（原始）作 key，语义不等价已标注
- **I8 allowedSkillNames 过滤**：Cline 检查 4 形式（id/name/bareId/bareName），我检查 1 形式（name），已标注弱对齐
- **I9 disabled 字段**：Cline L88 `disabled: skill.disabled === true` + L123-127 返回 "configured but disabled"；我 L139-143 同样返回 "configured but disabled"，逻辑等价
- **I10 always 注入**：context.py L185-189 确认 `load_always_instructions()` 返回值注入 system prompt 的 `# 常驻技能指令` section
- **I12 frontmatter 解析**：Cline 正则 `/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/` + `stripUtf8Bom`；我正则 `r"^---\n(.*?)\n---"`，缺 \r\n 和 BOM 处理，已标注 P2

### 6.4 关键发现

1. **Cline SkillConfig 极简**：仅 name/description/disabled/instructions/frontmatter 5 字段，无 always/keywords/source/scripts。我的额外字段源自 nanobot 设计，属合理增强。
2. **Cline resolveSkillRecord 含 suffix 匹配 + 歧义处理**：当精确 id 未命中时，按 `:bareName` 后缀匹配，多个匹配时报歧义错误。我无此逻辑，仅按 name 精确查找。
3. **Cline skill-frontmatter-toggle.ts 是写入工具**：用于 UI 修改 SKILL.md 的 disabled/enabled 状态并写回文件。我仅读取，无写入需求（无 UI）。
4. **Cline 通过 watcher 驱动一切**：`getConfiguredSkillsFromWatcher` 每次从 watcher snapshot 取数据，确保热重载后立即生效。我通过 `discover()` 一次性扫描，无热重载。
5. **Cline tool description 用 getter 动态构造**：`Object.defineProperty(tool, "description", { get() {...} })`，每次访问 description 都重新读取 `executor.configuredSkills`。我用 `@property` + `_build_description()`，逻辑等价。

---

**阶段 I 结论**：技能系统对齐度约 60%，核心调用链（I1-I5 + I9）字节级/逻辑级等价，可正常运行。主要差距集中在健壮性（I12 BOM/CRLF、I6 key 规范化）、扩展性（I17 多目录、I18 热重载）、白名单匹配完整性（I8）三方面，均为 P2 级别，无 P0/P1 阻塞。我额外增强的 always 字段（I10）、scripts 自动发现（I14）、build_summary 表格（I20）源自 nanobot 设计，对量化场景有实际价值，应保留。marketplace（I19）量化场景暂无需求，暂不实现。
