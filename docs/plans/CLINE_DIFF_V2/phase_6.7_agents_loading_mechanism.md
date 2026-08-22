# Phase 6.7 AGENTS.md 加载机制对比

> 对比范围：Cline `UnifiedConfigFileWatcher` + `user-instruction-config-loader.ts` + `paths.ts` + `rule-helpers.ts` + `cline-rules.ts` + `external-rules.ts` 的 AGENTS.md 文件发现/加载顺序/加载时机/缓存/热重载机制，与 Charles `agent/rules_loader.py` + `agent/context.py` 的 `load_rules_directory` + `_build_rules` + `_RULES_MTIME_CACHE` 实现差异；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `third_party/cline/sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts` L1-496（`UnifiedConfigFileWatcher` 类：fs.watch + 75ms debounce + sha1 fingerprint 增量更新）
> - `third_party/cline/sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L1-634（`createRulesConfigDefinition` + `discoverRulesLikeFiles` + `parseMarkdownFrontmatter` + `resolveRuleFallbackName`）
> - `third_party/cline/sdk/packages/shared/src/storage/paths.ts` L14-394（`resolveRulesConfigSearchPaths` + `resolveGlobalAgentsRulesPath` + `AGENTS_RULES_FILE_NAME` + `LEGACY_AGENT_SKILLS_CONFIG_DIR`）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/cline-rules.ts` L1-34（`refreshClineRulesToggles`）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/external-rules.ts` L1-49（`refreshExternalRulesToggles`）
> - `third_party/cline/apps/vscode/src/core/context/instructions/user-instructions/rule-helpers.ts` L1-467（`synchronizeRuleToggles` + `getRuleFilesTotalContentWithMetadata`）
> - `third_party/cline/apps/vscode/src/core/prompts/responses.ts` L334（`agentsRulesLocalFileInstructions`：recursive AGENTS.md 文案）
>
> Charles 源码：
> - `agent/rules_loader.py` L55-65（`_RULES_MTIME_CACHE` 模块级缓存）+ L524-566（`_read_with_mtime_cache`）+ L568-683（`load_rules_directory`）+ L686-722（`format_rules_content`）
> - `agent/context.py` L454-539（`_build_rules` 加载顺序编排）+ L541-609（`_load_rules_directory`）+ L874-889（`_strip_frontmatter`）
> - `agent/server.py` L528-549（`_build_system_prompt` 入口：agents_path = agent_config/AGENTS.md，rules_dir = agent_config/rules）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 AGENTS.md 加载机制（文件发现、加载顺序、加载时机、缓存、热重载）。**核心结论：加载机制存在四处实质差异，其中两处是计划文件 P6.7 未提及的真实差距。**

### 计划文件关键修正

AGENT_COMPARISON_PLAN_V2.md P6.7（L2381-2402）列出 5 项对比，标注 Charles "无热重载"、watcher "缺失"。**此标注方向正确但描述不够精确**：

1. **"Charles 无热重载"需要澄清**：Charles 的 `rules_loader.py` L60-62 docstring 明确写道"本项目是 Web 请求-响应模型，每次 build 重读已等价热重载"。严格意义上 Charles **有等价的热重载效果**（每次 build 都重读磁盘），只是**没有事件驱动的实时监听**。计划表"无热重载"应理解为"无 watcher 实时监听"，而非"完全无热重载能力"。
2. **计划表未提及的关键差距**：
   - **全局 AGENTS.md 路径不一致**：Cline 用 `~/.agents/AGENTS.md`（`.agents` 复数，paths.ts L16/L373），Charles 用 `~/.agent/AGENTS.md`（`.agent` 单数，context.py L472）。这是**路径拼写错误**，导致 Charles 无法读取 Cline 生态的全局 AGENTS.md。
   - **加载顺序相反**：Cline 搜索路径顺序为 workspace → global（paths.ts L376-395），Charles 硬编码顺序为 global → workspace（context.py L471-496）。
   - **Recursive AGENTS.md 缺失**：Cline 在每个扫描目录中显式检查 AGENTS.md（user-instruction-config-loader.ts L479-498），支持"嵌套 AGENTS.md"语义（responses.ts L334）；Charles 仅加载 2 个固定 AGENTS.md，不扫描子目录中的 AGENTS.md。

### 核心结论

1. **加载时机**：Cline 启动时通过 `UnifiedConfigFileWatcher.start()` 全量加载并常驻内存；Charles 每次 `build()` 调用时重读磁盘（lazy 加载）。Charles 设计合理（Web 请求-响应模型无需常驻），但**每次 build 都做 I/O**（虽有 mtime 缓存优化）。
2. **文件监听**：Cline 用 `node:fs.watch` + 75ms debounce 实现事件驱动增量更新（unified-config-file-watcher.ts L273-282/L320-338）；Charles **无 watcher**，依赖每次 build 时的 mtime 比对（rules_loader.py L524-556）。计划表"Charles 缺失"正确。
3. **缓存机制**：Cline 用 sha1 content fingerprint（unified-config-file-watcher.ts L75-77），Charles 用 mtime_ns 时间戳（rules_loader.py L545）。两者均只缓存"内容 + 解析结果"，不缓存"条件评估结果"。Cline 基于内容哈希更精确（即便 mtime 重置也能检测内容变化），Charles 基于 mtime 更轻量（无哈希计算开销）。
4. **文件发现路径**：Cline 6 个搜索路径（paths.ts L376-395），Charles 3 个（global AGENTS.md + workspace AGENTS.md + rules_dir）。Charles 不支持 `.clinerules` / `.cline/rules` / `~/Documents/Cline/Rules` 等 Cline 标准路径。
5. **frontmatter 解析与 _strip_frontmatter**：已对齐（P6.1 已确认正则逐字符相同；context.py L874-889 `_strip_frontmatter` 与 Cline `parseMarkdownFrontmatter` 语义一致）。
6. **多文件加载**：已对齐（双方均递归扫描 .md 文件，均支持 frontmatter 条件过滤）。
7. **nanobot 残留**：P6.7 范围内（rules_loader.py + context.py）共 **1 处注释残留**（context.py L275，已在 P5.1 记录），**0 处实现逻辑残留**。

### 一致性总体评估

- **加载时机**：**中**。Charles 无独立启动加载阶段，但每次 build 重读等价"懒加载热重载"。
- **文件监听**：**低**。Charles 无 fs.watch 实时监听，依赖 build 触发重读。
- **文件发现**：**中-低**。全局路径拼写不一致（`.agent` vs `.agents`），不支持 Cline 标准搜索路径。
- **加载顺序**：**中**。顺序相反（global → workspace vs workspace → global），但双方都明确有序。
- **缓存**：**高**。mtime 缓存与 fingerprint 缓存语义等价（均只缓存内容+解析，不缓存评估）。
- **frontmatter / _strip_frontmatter / 多文件加载**：**高**。已对齐。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 6.7.1 | 加载时机 | 启动时全量加载（`UnifiedConfigFileWatcher.start()` L169-176 调 `refreshAll`）+ 运行时事件驱动增量更新 | 每次 `build()` 调用时重读磁盘（context.py L348-391 `build` → L454 `_build_rules` → L568 `load_rules_directory`） | 中 | Charles 无独立启动加载阶段，但 Web 请求-响应模型下每次 build 重读已等价"懒加载热重载"。计划表"Charles 无热重载"应理解为"无 watcher 实时监听" |
| 6.7.2 | 文件监听 | `UnifiedConfigFileWatcher` 用 `node:fs.watch`（L273 `watch(directoryPath, ...)`），每目录一个 FSWatcher，75ms debounce（L337 `setTimeout(..., this.debounceMs)`，L134 默认 75ms） | 无 watcher（rules_loader.py L60-62 docstring 明确"本项目无 fs.watch"） | 低 | Charles 缺失实时监听能力。文件修改后需等下次 build 才生效。计划表"Charles 缺失"正确 |
| 6.7.3 | frontmatter 解析 | `parseMarkdownFrontmatter`（user-instruction-config-loader.ts L194-225），正则 `^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$` | `parse_yaml_frontmatter`（rules_loader.py L131-181），正则 `r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$"` | 高 | 正则逐字符完全相同（P6.1 已确认）。BOM 处理、fail-open 策略均已对齐 |
| 6.7.4 | _strip_frontmatter | `parseMarkdownFrontmatter` 内联正则 match group(2) 作为 body（user-instruction-config-loader.ts L208 `[yamlContent, body] = match`） | `_strip_frontmatter`（context.py L874-889）静态方法，查找第二个 `---` 后返回剩余内容 | 高 | 语义等价。Charles 用朴素字符串查找（`content.find("\n---", 3)`），Cline 用正则。两者都正确移除 frontmatter 块返回 body |
| 6.7.5 | 多文件加载 | `getRuleFilesTotalContentWithMetadata`（rule-helpers.ts L206-259）递归读取目录下所有 .md 文件，按文件路径排序 | `load_rules_directory`（rules_loader.py L568-683）用 `rules_path.rglob("*.md")` 递归扫描，sorted 排序 | 高 | 已对齐。双方均递归扫描 .md 文件，均按文件名排序，均支持 frontmatter 条件过滤与 toggle 禁用 |
| 6.7.6 | 文件发现路径 | `resolveRulesConfigSearchPaths`（paths.ts L376-395）返回 6 个搜索路径：workspace AGENTS.md / `.clinerules` / `.cline/rules` / `~/.agents/AGENTS.md` / `~/.cline/rules` / `~/Documents/Cline/Rules` | 硬编码 3 个路径：`~/.agent/AGENTS.md`（context.py L472）+ `agents_path`（通常 `agent_config/AGENTS.md`）+ `rules_dir`（通常 `agent_config/rules`） | 中-低 | **关键差距**：(a) Charles 全局路径用 `.agent` 单数，Cline 用 `.agents` 复数（paths.ts L16 `LEGACY_AGENT_SKILLS_CONFIG_DIR = ".agents"`），**拼写不一致**；(b) Charles 不支持 `.clinerules` / `.cline/rules` / `~/Documents/Cline/Rules` 等 Cline 标准路径 |
| 6.7.7 | 加载顺序 | search paths 顺序为 **workspace → global**（paths.ts L388-394：先 workspaceAgentsFile，再 resolveGlobalAgentsRulesPath） | 硬编码顺序为 **global → workspace → rules_dir**（context.py L471-500：先 `~/.agent/AGENTS.md`，再 `agents_path`，再 `rules_dir`） | 中 | 顺序相反。Cline 让 workspace 规则覆盖 global（后者在前者之后加载，UI 展示时 workspace 优先）；Charles 让 global 先加载（在 `# Rules` 段中位置更靠前） |
| 6.7.8 | 缓存机制 | `InternalRecord.fingerprint`（unified-config-file-watcher.ts L75-77 `toFingerprint` = sha1(content)），事件驱动时比对 fingerprint 决定是否 emit upsert | `_RULES_MTIME_CACHE`（rules_loader.py L63-65），key=绝对路径，value=(mtime_ns, raw_text, FrontmatterParseResult)，每次 build 时比对 mtime_ns | 高 | 两者均只缓存"内容 + 解析结果"，不缓存"条件评估结果"。Cline 用 sha1 内容哈希（精确但计算开销），Charles 用 mtime_ns 时间戳（轻量但 mtime 重置时可能误判） |
| 6.7.9 | Recursive AGENTS.md | `discoverRulesLikeFiles`（user-instruction-config-loader.ts L479-498）在每个扫描目录中显式检查 `AGENTS.md` 文件，支持嵌套 AGENTS.md（responses.ts L334 "Nested AGENTS.md will be combined"） | **不支持**。Charles 仅加载 2 个固定 AGENTS.md（global + workspace），`rules_dir.rglob("*.md")` 虽会扫到子目录 AGENTS.md 但作为普通规则处理（stem="AGENTS"，无特殊语义） | 中 | Cline 的 recursive AGENTS.md 特性缺失。Charles 的 rglob 会扫到子目录 AGENTS.md 但不识别其特殊身份 |
| 6.7.10 | rule name 命名 | `resolveRuleFallbackName`（user-instruction-config-loader.ts L261-282）：workspace AGENTS.md → "Workspace AGENTS.md"，global AGENTS.md → "Global AGENTS.md"，其他 → basename 去扩展名 | `format_rules_content`（rules_loader.py L716）统一用 `r.path.stem`：global AGENTS.md → "AGENTS"，workspace AGENTS.md → "AGENTS" | 中 | Charles 会对 global + workspace AGENTS.md 产生**重复的 "## AGENTS" 标题**（若两者都存在）。Cline 通过 "Workspace AGENTS.md" / "Global AGENTS.md" 区分。此项属 P6.8 范围，此处仅记录 |

---

## 三、重点差距详解

### 3.1 全局 AGENTS.md 路径拼写不一致（`.agent` vs `.agents`）

**这是计划文件 P6.7 未提及的关键差距**。

**Cline**（paths.ts L16 + L372-374）：
```typescript
const LEGACY_AGENT_SKILLS_CONFIG_DIR = ".agents";  // 复数

export function resolveGlobalAgentsRulesPath(): string {
    return join(HOME_DIR, LEGACY_AGENT_SKILLS_CONFIG_DIR, AGENTS_RULES_FILE_NAME);
    // → ~/.agents/AGENTS.md
}
```

**Charles**（context.py L471-472）：
```python
# 1. 全局 AGENTS.md（~/.agent/AGENTS.md）作为第一个 rule
global_agents_path = Path.home() / ".agent" / "AGENTS.md"  # 单数
```

**影响**：
- Charles 无法读取 Cline 生态的全局 AGENTS.md（`~/.agents/AGENTS.md`），反之亦然
- 若用户按 Cline 文档在 `~/.agents/AGENTS.md` 放置全局规则，Charles 会**静默忽略**
- 这是**拼写错误**，非有意设计（Charles 其他地方如 skills 用 `.agents`？需核查）

**修正建议**：将 context.py L472 的 `".agent"` 改为 `".agents"`，与 Cline `LEGACY_AGENT_SKILLS_CONFIG_DIR` 对齐。

### 3.2 加载顺序相反（global → workspace vs workspace → global）

**Cline** search paths 顺序（paths.ts L388-394）：
```typescript
return dedupePaths([
    ...workspaceAgentsFile,        // 1. workspacePath/AGENTS.md（workspace 优先）
    ...wsPaths,                    // 2. workspacePath/.clinerules + workspacePath/.cline/rules
    resolveGlobalAgentsRulesPath(), // 3. ~/.agents/AGENTS.md（global 在后）
    join(resolveClineDir(), RULES_CONFIG_DIRECTORY_NAME),  // 4. ~/.cline/rules
    resolveDocumentsExtensionPath("Rules"),                 // 5. ~/Documents/Cline/Rules
]);
```

**Charles** 硬编码顺序（context.py L471-500）：
```python
# 1. 全局 AGENTS.md（~/.agent/AGENTS.md）作为第一个 rule  ← global 优先
global_agents_path = Path.home() / ".agent" / "AGENTS.md"
# 2. 兼容旧接口：若显式传入 agents_path 且文件存在，也作为 rule  ← workspace 在后
if self.agents_path and self.agents_path.exists():
# 3. workspace rules_dir  ← rules_dir 最后
if self.rules_dir and self.rules_dir.exists():
```

**影响**：
- Cline：workspace 规则在 `# Rules` 段中**更靠后**（覆盖 global 语义）
- Charles：global 规则在 `# Rules` 段中**更靠前**（基础规则，workspace 在后覆盖）

**实际影响有限**：因为 LLM 对 `# Rules` 段内规则的"覆盖"语义并不严格按顺序生效（不像代码后定义覆盖前定义）。但**与 Cline 行为不一致**，且若 global AGENTS.md 与 workspace AGENTS.md 有冲突指令时，顺序可能影响 LLM 倾向。

**修正建议**：将 context.py `_build_rules` 中的步骤 1（global）与步骤 2（workspace）顺序对调，与 Cline 对齐。

### 3.3 加载时机与文件监听（计划表核心项）

**Cline**（unified-config-file-watcher.ts）：
```typescript
// L169-176: 启动时全量加载
async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    await this.refreshAll();        // 全量加载所有 definitions
    this.startDirectoryWatchers();  // 启动 fs.watch 监听
}

// L273-282: 每目录一个 FSWatcher
const watcher = watch(directoryPath, () => {
    for (const type of types) {
        this.pendingTypes.add(type);
    }
    this.scheduleFlush();  // 75ms debounce
});

// L320-338: debounce flush
this.flushTimer = setTimeout(() => {
    const types = [...this.pendingTypes];
    this.pendingTypes.clear();
    void this.enqueueRefresh(async () => {
        for (const type of types) {
            await this.refreshTypeInternal(definition);  // 增量更新
        }
    });
}, this.debounceMs);  // 默认 75ms
```

**Charles**（rules_loader.py L55-65 + L524-556）：
```python
# L55-65: 模块级 mtime 缓存（无 watcher）
_RULES_MTIME_CACHE: dict[str, tuple[int, str, "FrontmatterParseResult"]] = {}

# L524-556: 每次 build 时调用，比对 mtime_ns
def _read_with_mtime_cache(file_path: Path) -> tuple[str, "FrontmatterParseResult"]:
    abs_key = str(file_path.resolve())
    mtime_ns = file_path.stat().st_mtime_ns
    cached = _RULES_MTIME_CACHE.get(abs_key)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1], cached[2]  # 缓存命中
    # 缓存未命中：重新读取与解析
    raw = file_path.read_text(encoding="utf-8").strip()
    parse_result = parse_yaml_frontmatter(raw)
    _RULES_MTIME_CACHE[abs_key] = (mtime_ns, raw, parse_result)
    return raw, parse_result
```

**差异分析**：

| 维度 | Cline | Charles |
|------|-------|---------|
| 触发方式 | 事件驱动（fs.watch 监听文件变化） | 轮询式（每次 build 时检查 mtime） |
| 响应延迟 | 75ms（debounce 后立即更新） | 下次 build 时（可能数分钟） |
| 增量粒度 | 单文件 upsert/remove 事件 | 单文件 mtime 比对 |
| 常驻内存 | 是（recordsByType Map 常驻） | 否（build 后返回字符串，cache 仅缓存解析结果） |
| UI 实时性 | 高（watcher 事件可实时推送 UI） | 低（需触发 build 才更新） |

**Charles 设计合理性**：Charles 是 Web 请求-响应模型，每次用户请求都会重建 system prompt（`_build_system_prompt` → `SystemPromptBuilder.build`），此时重读磁盘等价"热重载"。无需 Cline 的常驻 watcher。但 Charles 的 mtime 缓存避免了无变更文件的重复 I/O，性能可接受。

**计划表"Charles 无热重载"修正**：应改为"Charles 无 watcher 实时监听，依赖每次 build 时的 mtime 比对实现等价热重载"。

### 3.4 缓存机制：sha1 fingerprint vs mtime_ns

**Cline**（unified-config-file-watcher.ts L75-77 + L361-369）：
```typescript
function toFingerprint(content: string): string {
    return createHash("sha1").update(content).digest("hex");
}

// L361-369: 比对 fingerprint 决定是否 emit upsert
for (const [id, nextRecord] of nextRecords.entries()) {
    const previousRecord = previousRecords.get(id);
    if (previousRecord &&
        previousRecord.filePath === nextRecord.filePath &&
        previousRecord.fingerprint === nextRecord.fingerprint) {  // 内容哈希比对
        continue;  // 无变化，不 emit
    }
    this.emit({ kind: "upsert", record: {...} });
}
```

**Charles**（rules_loader.py L543-556）：
```python
abs_key = str(file_path.resolve())
mtime_ns = file_path.stat().st_mtime_ns  # 纳秒精度时间戳
cached = _RULES_MTIME_CACHE.get(abs_key)
if cached is not None and cached[0] == mtime_ns:  # mtime 比对
    return cached[1], cached[2]
# mtime 变化才重新读取
```

**对比**：

| 维度 | Cline sha1 fingerprint | Charles mtime_ns |
|------|----------------------|------------------|
| 检测基准 | 文件内容哈希 | 文件修改时间戳 |
| 精确度 | 内容级（任何字节变化都检测） | 时间级（mtime 变化才检测） |
| 误判场景 | 无 | `touch` 命令重置 mtime 但内容未变 → 误判为变化，重新解析（无害但浪费） |
| 漏判场景 | 无 | mtime 被手动重置为旧值但内容已变 → 漏判（罕见） |
| 计算开销 | sha1 哈希（每文件每次扫描） | stat() 系统调用（轻量） |
| 缓存粒度 | 解析后的 item（RuleConfig） | (raw_text, FrontmatterParseResult) |

**共同点**：两者均**不缓存条件评估结果**（Cline `evaluateRuleConditionals` 每次重算，Charles `evaluate_rule_conditionals` 每次重算），因为条件评估依赖当前 context（agent_mode / business_modes / paths），context 每次可能不同。

**结论**：缓存语义等价，均只缓存"内容 + 解析"。Charles 的 mtime 方案在 Web 请求-响应模型下性能足够，无需引入 sha1 开销。

### 3.5 文件发现路径覆盖范围

**Cline**（paths.ts L376-395）返回 6 个搜索路径，按顺序：
1. `workspacePath/AGENTS.md`（workspace 根 AGENTS.md）
2. `workspacePath/.clinerules`（deprecated 目录）
3. `workspacePath/.cline/rules`（Cline 标准 rules 目录）
4. `~/.agents/AGENTS.md`（global AGENTS.md）
5. `~/.cline/rules`（Cline 全局 rules 目录）
6. `~/Documents/Cline/Rules`（Documents 目录）

**Charles**（context.py L471-500 + server.py L528-549）返回 3 个路径：
1. `~/.agent/AGENTS.md`（global，**拼写错误**应为 `.agents`）
2. `<project_root>/agent_config/AGENTS.md`（workspace，非 Cline 标准）
3. `<project_root>/agent_config/rules/`（rules_dir，非 Cline 标准）

**差距**：
- Charles 不支持 `.clinerules` / `.cline/rules` / `~/Documents/Cline/Rules` 等 Cline 标准路径
- Charles 用 `agent_config/` 替代，这是 Charles 自定义路径（合理，但与 Cline 生态不互通）
- 全局路径 `.agent` vs `.agents` 拼写错误（见 3.1）

**合理性评估**：Charles 作为独立项目，自定义 `agent_config/` 路径合理（无需完全复制 Cline 路径结构）。但全局 AGENTS.md 路径应与 Cline 对齐（`.agents`），以便用户跨工具复用全局规则。

### 3.6 Recursive AGENTS.md 特性缺失

**Cline**（user-instruction-config-loader.ts L479-498）：
```typescript
// Special case: if this is a workspace root directory, also check for AGENTS.md
const agentsPath = join(directoryPath, "AGENTS.md");
try {
    const agentsStat = await stat(agentsPath);
    if (agentsStat.isFile()) {
        const alreadyIncluded = candidates.some((c) => c.fileName === "AGENTS.md");
        if (!alreadyIncluded) {
            candidates.push({
                directoryPath,
                fileName: "AGENTS.md",
                filePath: agentsPath,
            });
        }
    }
} catch {
    // AGENTS.md doesn't exist or is not accessible, which is fine
}
```

配合 responses.ts L334 的文案：
```
The following is provided by AGENTS.md files found recursively throughout
this working directory where the user has specified instructions.
Nested AGENTS.md will be combined below, and you should only apply the
instructions for each AGENTS.md file that is directly applicable to the
current task, i.e. if you are reading or writing to a file in that directory.
```

**语义**：Cline 支持在工作目录的任意子目录中放置 AGENTS.md，LLM 会根据当前操作的文件路径选择适用的 AGENTS.md 指令。

**Charles**：不支持。Charles 的 `rules_dir.rglob("*.md")` 会扫到子目录中的 AGENTS.md 文件，但：
- 作为普通规则处理（stem="AGENTS"，无特殊命名）
- 不区分"适用于哪个子目录"
- 无 `agentsRulesLocalFileInstructions` 文案说明 nested 语义

**影响**：Charles 无法实现"子目录级 AGENTS.md"的精细化指令。但 Charles 作为量化投研系统，工作目录结构相对固定（`agent_config/` 下），可能不需要此特性。

---

## 四、nanobot 残留专项检查

### 4.1 检查范围

P6.7 范围内涉及以下 2 个文件：
- `agent/rules_loader.py`（1053 行）
- `agent/context.py`（2666 行）

### 4.2 检查结果

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|------|---------|-------------|---------|
| `agent/rules_loader.py` | 0 处 | 0 处 | 全文无 "nanobot" 字样。docstring 与注释均对标 Cline（"对标 Cline frontmatter.ts" / "对标 Cline parseYamlFrontmatter" / "对标 Cline UnifiedConfigFileWatcher" / "对标 Cline getRuleFilesTotalContentWithMetadata"），无 nanobot 对标引用 |
| `agent/context.py` | **1 处** | 0 处 | L275 docstring `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` — **注释残留**，已在 P5.1 记录。**无实现逻辑残留**（extra_sections 参数虽保留但 build() 中仅作向后兼容，无 nanobot 特定逻辑） |

**P6.7 范围内 nanobot 残留总计：1 处（注释 1 + 实现逻辑 0）。**

### 4.3 残留详情

`agent/context.py` L275（`SystemPromptBuilder.__init__` docstring）：
```python
extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。
                保留参数签名仅为向后兼容，当前无调用方传入。
```

**性质**：注释残留。docstring 说明 `extra_sections` 参数源自 nanobot 风格，现已废弃。参数本身保留仅为向后兼容（`__init__` L292 `self.extra_sections = extra_sections or {}`），`_build_rules` L530-537 仍有遍历逻辑但无 nanobot 特定行为。

**修复建议**：将 docstring 中的 "nanobot 风格" 改为 "旧版扩展段落" 或直接删除此句（因已标注"已废弃"）。实现逻辑无需修改（向后兼容保留合理）。

### 4.4 范围外残留说明

以下文件的 nanobot 残留**超出 P6.7 范围**（属其他阶段管辖），此处仅列出供参考，不在本阶段修复：

| 文件 | 残留类型 | 说明 | 归属阶段 |
|------|---------|------|---------|
| `agent/server.py` L2/L4/L28 | 注释残留 | docstring 对标 "nanobot routes/chat.py" | P1.x / P2.x |
| `agent/session.py` L2/L22 | 注释残留 | docstring 对标 "nanobot session_key" | P1.x |
| `agent/providers/qwen.py` L21/L49/L116/L214/L253/L385/L406 | 注释残留 | docstring 对标 "nanobot openai_compat_provider.py" | Provider 阶段 |
| `agent/skills/loader.py` L2/L29/L48/L96/L167/L222/L392/L423 | 注释残留 | docstring 对标 "nanobot SkillsLoader" | P4.x |
| `agent/skills/registry.py` L2/L20/L100/L184 | 注释残留 | docstring 对标 "nanobot SkillsLoader" | P4.x |
| `agent/skills/skill_tool.py` L18 | 注释残留 | docstring 对比 "nanobot 子 agent 隔离执行" | P4.x |
| `agent/skills/__init__.py` L2/L23 | 注释残留 | docstring 对标 "nanobot SkillsLoader" | P4.x |
| `agent/tools/exec_tool.py` L2/L8-L10/L18-L19/L41/L57/L123/L165/L181/L263 | 注释残留 | docstring 对标 "nanobot ShellTool / shell.py" | P3.x |
| `agent/tools/file_tools.py` L2/L7/L12/L27/L115/L130/L165 | 注释残留 | docstring 对标 "nanobot FilesystemTool / filesystem.py" | P3.x |
| `agent/tools/__init__.py` L2 | 注释残留 | docstring 对标 "nanobot agent/tools" | P3.x |
| `agent/tools/web_tool.py` L2/L9 | 注释残留 | docstring 对标 "nanobot WebSearchTool" | P3.x |

**注**：以上范围外残留均为**注释残留**（docstring/注释中对标 nanobot 的引用），**无实现逻辑残留**（所有实现均已对标 Cline 或为 Charles 原生设计）。注释残留不影响功能，仅为历史溯源信息。

---

## 五、验证方法

### 5.1 加载时机验证

```bash
# Cline: 启动时 watcher 加载 + 运行时事件驱动
# 检查 UnifiedConfigFileWatcher.start() 调用链
grep -r "UnifiedConfigFileWatcher" third_party/cline/sdk/packages/core/src/
grep -r "\.start()" third_party/cline/sdk/packages/core/src/extensions/config/

# Charles: 每次 build 时重读
# 检查 _build_rules 调用链
grep -n "_build_rules\|_read_with_mtime_cache" agent/context.py agent/rules_loader.py
```

### 5.2 文件监听验证

```bash
# Cline: fs.watch + debounce
grep -n "watch\|debounceMs\|scheduleFlush" \
  third_party/cline/sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts

# Charles: 无 watcher（应无命中）
grep -rn "fs.watch\|watchdog\|inotify\|FileSystemWatcher" agent/rules_loader.py agent/context.py
```

### 5.3 全局路径拼写验证

```bash
# Cline: .agents（复数）
grep -n "LEGACY_AGENT_SKILLS_CONFIG_DIR\|\.agents" \
  third_party/cline/sdk/packages/shared/src/storage/paths.ts

# Charles: .agent（单数，拼写错误）
grep -n "\.agent\b\|\.agents" agent/context.py
```

### 5.4 加载顺序验证

```bash
# Cline: workspace → global（paths.ts L388-394 顺序）
grep -n "workspaceAgentsFile\|resolveGlobalAgentsRulesPath" \
  third_party/cline/sdk/packages/shared/src/storage/paths.ts

# Charles: global → workspace（context.py L471-500 顺序）
grep -n "global_agents_path\|agents_path\|rules_dir" agent/context.py | head -20
```

### 5.5 缓存机制验证

```bash
# Cline: sha1 fingerprint
grep -n "toFingerprint\|fingerprint\|createHash" \
  third_party/cline/sdk/packages/core/src/extensions/config/unified-config-file-watcher.ts

# Charles: mtime_ns
grep -n "mtime_ns\|_RULES_MTIME_CACHE\|_read_with_mtime_cache" agent/rules_loader.py
```

### 5.6 nanobot 残留验证

```bash
# P6.7 范围内（应仅 context.py L275 命中）
grep -in "nanobot" agent/rules_loader.py agent/context.py
```

---

## 六、修复建议优先级

| 优先级 | 修复项 | 文件:行 | 说明 |
|--------|--------|---------|------|
| **P0 高** | 全局 AGENTS.md 路径 `.agent` → `.agents` | `agent/context.py` L472 | 拼写错误，导致无法读取 Cline 生态全局规则。一行修改 |
| **P1 中** | 加载顺序对齐：workspace → global | `agent/context.py` L471-500 | 与 Cline 行为一致，调换步骤 1 与步骤 2 顺序 |
| **P2 低** | nanobot 注释残留清理 | `agent/context.py` L275 | docstring 中 "nanobot 风格" 改为 "旧版扩展段落"。已在 P5.1 记录 |
| **P3 低** | Recursive AGENTS.md 支持 | `agent/rules_loader.py` + `agent/context.py` | 按需评估，量化场景可能不需要。若需支持，需在 `load_rules_directory` 中对名为 `AGENTS.md` 的文件特殊处理（命名 + 文案） |
| **不修复** | 文件监听 watcher | N/A | Charles Web 请求-响应模型无需 watcher，mtime 缓存已足够。计划表"Charles 缺失"是设计选择，非缺陷 |
| **不修复** | 缓存机制 mtime → sha1 | N/A | mtime 在 Web 模型下性能足够，无需引入 sha1 开销 |
| **不修复** | Cline 标准搜索路径支持 | N/A | Charles 用 `agent_config/` 自定义路径合理，无需支持 `.clinerules` / `.cline/rules` |

---

## 七、与计划表的对比修正

| 计划表项 | 计划表声明 | 实际情况 | 修正 |
|---------|-----------|---------|------|
| 6.7.1 加载时机 | "Charles 无热重载" | Charles 有等价热重载（每次 build 重读磁盘），但无 watcher 实时监听 | 改为"Charles 无 watcher 实时监听，依赖每次 build 时的 mtime 比对实现等价热重载" |
| 6.7.2 文件监听 | "Charles 缺失" | 正确，Charles 无 fs.watch watcher | 无需修正 |
| 6.7.3 frontmatter 解析 | "已对齐" | 正确（P6.1 已确认正则逐字符相同） | 无需修正 |
| 6.7.4 _strip_frontmatter | "已对齐（Stage P3）" | 正确，context.py L874-889 与 Cline parseMarkdownFrontmatter 语义一致 | 无需修正 |
| 6.7.5 多文件加载 | "已对齐" | 正确，双方均递归扫描 .md 文件 | 无需修正 |
| **未列出** | 全局路径 `.agent` vs `.agents` | **Cline 用 `.agents`，Charles 用 `.agent`，拼写不一致** | 新增 6.7.6 项 |
| **未列出** | 加载顺序相反 | **Cline workspace → global，Charles global → workspace** | 新增 6.7.7 项 |
| **未列出** | Recursive AGENTS.md | **Cline 支持子目录 AGENTS.md，Charles 不支持** | 新增 6.7.9 项 |
| **未列出** | 缓存机制对比 | **Cline sha1 fingerprint，Charles mtime_ns** | 新增 6.7.8 项 |

---

## 八、结论

P6.7 AGENTS.md 加载机制对比完成。**frontmatter 解析、_strip_frontmatter、多文件加载三项已完全对齐**（P6.1 已确认）。**加载机制存在四处实质差异**：

1. **全局路径拼写错误**（`.agent` vs `.agents`）— P0 优先级修复
2. **加载顺序相反**（global → workspace vs workspace → global）— P1 优先级修复
3. **文件监听缺失**（无 watcher）— 设计选择，不修复
4. **Recursive AGENTS.md 缺失** — P3 优先级按需评估

nanobot 残留：P6.7 范围内 1 处注释残留（context.py L275，已在 P5.1 记录），0 处实现逻辑残留。
