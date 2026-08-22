# Phase 4.5 SKILL.md frontmatter 对比

> 对比范围：Cline `parseMarkdownFrontmatter` + `parseSkillConfigFromMarkdown` + `skill-frontmatter-toggle.ts` 与 Charles `SkillLoader._parse_frontmatter` + `_parse_skill_file` 的 frontmatter 解析实现差异；frontmatter 字段清单、字段类型、disabled toggle、always 标记、description 字段、name 字段、when_to_use 字段、frontmatter 解析方式逐项对标；nanobot 残留专项检查（区分注释残留与实现逻辑残留）。
>
> Cline 源码：
> - `sdk/packages/core/src/extensions/config/user-instruction-config-loader.ts` L35-48（`ParseMarkdownFrontmatterResult` + `SkillConfig` 接口定义）+ L194-225（`parseMarkdownFrontmatter` 实现：BOM 剥离 + 正则 + YAML.parse + parseError）+ L227-259（`parseStringField` + `parseBooleanField` 类型校验）+ L284-311（`parseSkillConfigFromMarkdown` 字段提取）+ L385-437（`discoverSkillFiles` 目录扫描）
> - `sdk/packages/core/src/extensions/config/skill-frontmatter-toggle.ts` 全文 89 行（`toggleSkillFrontmatter` 写入 SKILL.md 实现 enable/disable 切换 + `updateSkillMarkdownEnabledState` 状态机）
> - `sdk/packages/core/src/extensions/config/user-instruction-plugin.ts` L75-172（`getConfiguredSkillsFromWatcher` + `resolveSkillRecord` 含 disabled/ambiguous 错误路径）
> - `docs/customization/skills.mdx` L37-71（Skill Structure + SKILL.md 示例 + Required fields 规范）
> - Cline SKILL.md 示例文件 6 个：`.agents/skills/cline-sdk/SKILL.md` + `.agents/skills/create-pull-request/SKILL.md` + `.agents/skills/opentui/SKILL.md` + `.cline/skills/publish-cli/SKILL.md` + `.cline/skills/publish-desktop/SKILL.md` + `.cline/skills/publish-ui/SKILL.md`
>
> Charles 源码：
> - `agent/skills/loader.py` L46-82（`SkillMetadata` dataclass 字段定义）+ L84-92（`_strip_utf8_bom`）+ L221-298（`_parse_skill_file` 字段提取）+ L300-342（`_discover_scripts` 自动扫描）+ L364-420（`_parse_frontmatter` 实现：BOM 剥离 + 正则 + PyYAML + fallback 简单解析）+ L422-434（`_strip_frontmatter`）
> - `agent/skills/registry.py` L141-160（`list_skills` disabled 过滤）+ L183-210（`get_always_skills` + `load_always_instructions` 实现 always 标记语义）+ L240-250（`skills_summary` 表格使用 `when_to_use` 字段）
> - `agent_config/skills/*/SKILL.md` 8 个技能 frontmatter 实例

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 SKILL.md frontmatter 解析与字段处理。两者在**核心解析流程**（BOM 剥离 + `---` 分隔正则 + YAML 解析 + 字段提取）和**disabled/enabled 双字段兼容**上**已对齐**（Phase 31.4 已修复 disabled 字段，Phase 3.5/I12 已修复 BOM + CRLF）。剩余差异主要集中在**字段清单扩展**（Charles 新增 `when_to_use`/`always`/`keywords`/`capabilities`/`allowed_tools`/`scripts` 共 6 个字段，Cline 仅 `name`/`description`/`disabled`/`enabled`/`metadata` 共 5 个字段）、**toggle 写入功能**（Cline 有 `toggleSkillFrontmatter` 写回文件，Charles 仅读取）、**解析容错策略**（Cline 抛错，Charles 静默 fallback）。

### 核心结论

1. **frontmatter 解析流程对齐**：两者均为「BOM 剥离 → `^---\r?\n(.*?)\r?\n---\r?\n?` 正则匹配 → YAML 解析 → 字段提取」。Cline 用 `yaml` npm 包，Charles 用 `PyYAML`（优先）+ 自研简单解析器（fallback）。
2. **disabled/enabled 双字段兼容对齐**（Phase 31.4）：两者均支持 `disabled: true`（推荐）和 `enabled: false`（legacy）两种写法，逻辑完全一致：`disabled = parseBoolean(disabled) ?? (parseBoolean(enabled) === false ? true : undefined)`。
3. **字段清单差异显著**：Cline 字段极简（`name` + `description` + `disabled`/`enabled` + 任意 `metadata` 透传），Charles 扩展 6 个字段（`when_to_use`/`always`/`keywords`/`capabilities`/`allowed_tools`/`scripts`），其中 `always` 和 `when_to_use` 被实际使用，`keywords`/`capabilities`/`allowed_tools` 为解析但未消费的 dead metadata。
4. **always 标记 Charles 独有**：Cline 无 `always` 字段概念，skills 一律按需加载（Level 2 use_skill 触发）。Charles `always: true` 触发 `load_always_instructions()` 在启动时将指令注入 system prompt（registry.py L183-210），概念源自 nanobot `get_always_skills()`。
5. **when_to_use 字段 Charles 独有**（Phase P5）：Cline 无此字段，"何时使用"语义隐含在 `description` 中（skills.mdx L70 "description tells Cline when to use this skill"）。Charles 将其拆为独立字段，用于 `skills_summary` 表格的"何时使用"列填充（registry.py L245-250）。
6. **toggle 写入功能缺失**：Cline `skill-frontmatter-toggle.ts` 提供 `toggleSkillFrontmatter()` 修改 SKILL.md 文件的 `disabled` 字段并写回（L76-89）。Charles `loader.py` 仅读取 `disabled`/`enabled`，无写入接口。
7. **解析容错策略相反**：Cline 严格模式（YAML 解析失败抛 `Failed to parse YAML frontmatter` 错误，类型不符抛 `must be a string/boolean` 错误）；Charles 宽松模式（PyYAML 失败后 fallback 到自研简单解析器，类型不符静默降级）。
8. **name 字段 fallback 一致**：两者均支持 frontmatter `name` 缺失时回退到目录名（Cline L296-297 + Charles L231）。
9. **description 字段约束差异**：Cline skills.mdx 文档规范 `description` 必填且 max 1024 字符；代码中 `parseStringField(description, false)` 标记为可选。Charles 代码中标记为可选，无长度限制。
10. **nanobot 残留**：**8 处注释残留**（loader.py 1 个文件），**1 处实现逻辑残留**（`_parse_frontmatter` 的 fallback 简单 YAML 解析器，对标 nanobot fallback）。`always` 字段语义源自 nanobot `get_always_skills()`，但已被 Charles registry.py 实际使用，不算残留。

### 一致性总体评估

- **核心解析流程**：**高**。BOM + 正则 + YAML + 字段提取对齐。
- **字段清单**：**低**。Charles 扩展 6 个字段，Cline 仅 5 个字段（其中 `metadata` 为透传）。
- **toggle 写入**：**低**。Charles 缺失写入功能。
- **容错策略**：**中**。Cline 严格 vs Charles 宽松，语义不同但都合理。

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 4.5.1 | BOM 剥离 | `stripUtf8Bom(content)`（user-instruction-config-loader.ts L200，shared 工具） | `_strip_utf8_bom(content)`（loader.py L84-92，自实现 `if content.startswith("\ufeff"): return content[1:]`） | 高 | 已对齐（Phase 3.5/I12）。两者均处理 Windows Notepad "UTF-8 with BOM" 文件 |
| 4.5.2 | frontmatter 正则 | `/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/`（L202） | `r"^---\r?\n(.*?)\r?\n---\r?\n?"`（L377） | 高 | 已对齐（Phase 3.5/I12）。两者均支持 CRLF + LF。Charles 用 `re.DOTALL` 使 `.*?` 匹配换行，Cline 用 `[\s\S]*?` |
| 4.5.3 | YAML 解析库 | `YAML.parse(yamlContent)`（L210，`yaml` npm 包） | `yaml.safe_load(raw)`（L386，PyYAML） | 高 | 库不同但语义等价 |
| 4.5.4 | YAML 解析失败处理 | 抛错：`throw new Error('Failed to parse YAML frontmatter: ${parseError}')`（L289-291） | 静默 fallback 到自研简单解析器（L389-420） | 中 | 策略相反。Cline 严格模式，Charles 宽松模式 |
| 4.5.5 | 无 frontmatter 处理 | 返回 `{ data: {}, body: content, hadFrontmatter: false }`（L205），body 仍可作为 instructions | 返回 `None`（loader.py L378-379），`_parse_skill_file` 返回 `None` 跳过该技能 | 中 | Cline 允许无 frontmatter 的 SKILL.md（instructions 仍可用），Charles 要求必须有 frontmatter |
| 4.5.6 | name 字段 | `parseStringField(data.name, "name", false)`（L296），可选，缺失时 fallback 到 `basename(directoryPath)`（L544） | `frontmatter.get("name", skill_file.parent.name)`（L231），缺失时 fallback 到目录名 | 高 | 完全一致 |
| 4.5.7 | name 类型校验 | `parseStringField` 校验 `typeof value !== "string"` 抛错（L238-240） | `frontmatter.get("name", ...)` 无类型校验 | 中 | Charles 不校验类型，但 PyYAML 已保证基本类型安全 |
| 4.5.8 | name 必填性 | 代码标记可选（`isRequired: false`），但 fallback 为空时抛 `Missing skill name`（L298-300） | 代码标记可选，fallback 到目录名后无二次校验 | 高 | 语义等价（fallback 总能提供值） |
| 4.5.9 | description 字段 | `parseStringField(data.description, "description", false)`（L304），可选 | `frontmatter.get("description", "")`（L232），可选，默认空字符串 | 高 | 完全一致 |
| 4.5.10 | description 文档约束 | skills.mdx L70 "Required fields: description tells Cline when to use this skill (max 1024 characters)" | 无文档约束，无长度限制 | 中 | Cline 文档规范更严，代码层面两者均为可选 |
| 4.5.11 | description 类型校验 | `parseStringField` 校验 string 类型 + trim + 空字符串处理（L227-246） | 无类型校验，直接 `frontmatter.get` | 中 | Charles 不校验，但 PyYAML 保证类型 |
| 4.5.12 | disabled 字段 | `parseBooleanField(data.disabled, "disabled")`（L305-306），boolean 类型，可选 | `bool(frontmatter.get("disabled", False))`（L239），bool 强转，可选 | 高 | 已对齐（Phase 31.4）。类型校验不同：Cline 严格 boolean，Charles `bool()` 强转 |
| 4.5.13 | enabled 字段（legacy） | `parseBooleanField(data.enabled, "enabled") === false ? true : undefined`（L307），仅当 `enabled: false` 时视为 disabled | `if frontmatter.get("enabled", True) is False: disabled = True`（L240-241），相同逻辑 | 高 | 已对齐（Phase 31.4）。两者均支持 `enabled: false` legacy 写法 |
| 4.5.14 | disabled 优先级 | `disabled` 优先，`enabled: false` fallback（L305-307 `??` 运算符） | `disabled` 优先，`enabled: false` 覆盖（L239-241 if 语句） | 高 | 完全一致 |
| 4.5.15 | always 字段 | **无**（Cline skills 一律按需加载，无 always 概念） | `bool(frontmatter.get("always", False))`（L234），boolean 类型 | 低 | Charles 独有增强，概念源自 nanobot `get_always_skills()` |
| 4.5.16 | always 字段使用 | — | `registry.py` L183-210 `get_always_skills()` + `load_always_instructions()`：always=True 的技能在启动时自动加载指令到 system prompt | — | Charles 独有机制。Cline 无此功能 |
| 4.5.17 | when_to_use 字段 | **无**（"何时使用"语义隐含在 description 中，skills.mdx L70） | `str(frontmatter.get("when_to_use", ""))`（L282），string 类型 | 低 | Charles 独有增强（Phase P5） |
| 4.5.18 | when_to_use 字段使用 | — | `registry.py` L245-250 `skills_summary` 表格"何时使用"列填充：`when_to_use = skill.when_to_use or "(见 SKILL.md)"`，超 60 字符截断 | — | Charles 独有机制。Cline 无此功能 |
| 4.5.19 | keywords 字段 | **无** | `frontmatter.get("keywords", "")`（L233），支持逗号分隔字符串或列表（L244-249） | 低 | Charles 独有增强，但**未被实际使用**（dead metadata） |
| 4.5.20 | capabilities 字段 | **无** | `frontmatter.get("capabilities", [])`（L235），支持列表或逗号分隔字符串（L252-255） | 低 | Charles 独有增强，但**未被实际使用**（dead metadata） |
| 4.5.21 | allowed_tools 字段 | **无**（Cline 子 agent 工具集通过 `config.subAgentTools` 全局配置，非 per-skill） | `frontmatter.get("allowed_tools", None)`（L236），支持列表或逗号分隔字符串（L259-266） | 低 | Charles 独有增强（Phase 20），但**未被实际使用**（dead metadata，SkillsTool 不创建子 agent） |
| 4.5.22 | scripts 字段 | **无**（Cline 不解析 scripts，scripts/ 目录由 LLM 通过 `read_file` 自主发现） | `frontmatter.get("scripts", None)`（L270），支持列表或逗号分隔字符串；缺失时自动扫描目录（L278-279 `_discover_scripts`） | 低 | Charles 独有增强（Phase 33.4），被 SkillsTool 实际使用（skill_tool.py L212-213 返回 metadata） |
| 4.5.23 | metadata 透传字段 | 支持：cline-sdk + opentui SKILL.md 使用 `metadata: references: agent, clinecore`（任意嵌套对象，透传到 `frontmatter: Record<string, unknown>`） | **无**（Charles `SkillMetadata` 不保留原始 frontmatter dict，仅提取已知字段） | 中 | Cline 保留 `frontmatter: data` 完整字典（L309），Charles 丢弃未知字段 |
| 4.5.24 | frontmatter 完整字典保留 | `SkillConfig.frontmatter: Record<string, unknown>`（L47），保留全部解析结果 | `SkillMetadata` 不保留 `frontmatter` 字段，仅保留已知字段 | 中 | Cline 允许下游访问任意 frontmatter 字段，Charles 仅访问已知字段 |
| 4.5.25 | 字段类型校验 | `parseStringField` + `parseBooleanField` 严格校验类型，不符抛错（L227-259） | 无类型校验，依赖 PyYAML 解析结果 + `bool()`/`str()` 强转 | 中 | Cline 严格，Charles 宽松 |
| 4.5.26 | instructions body 提取 | `body.trim()`（L292），空 body 抛 `Missing instructions body in skill file`（L293-295） | `_strip_frontmatter(content)` 后 `.strip()`（L173-174），无空 body 校验 | 中 | Cline 严格校验，Charles 不校验 |
| 4.5.27 | toggle 写入功能 | `skill-frontmatter-toggle.ts` L76-89 `toggleSkillFrontmatter`：读取 → 解析 → 修改 `disabled` → 序列化 → 写回文件 | **无**（loader.py 仅读取，无写入接口） | 低 | Charles 缺失 toggle 写入功能 |
| 4.5.28 | toggle 序列化 | `YAML.stringify(data).trimEnd()` + `---\n${yaml}\n---\n${body}`（L43-49） | — | — | Charles 无此功能 |
| 4.5.29 | toggle 状态机 | `updateSkillMarkdownEnabledState`（L51-74）：enabled 时删除 `disabled` 字段 + 清理 `enabled: false`；disabled 时设置 `disabled: true`；无 frontmatter 时按需新增 | — | — | Charles 无此功能 |
| 4.5.30 | 文件发现逻辑 | `discoverSkillFiles`（L385-437）：扫描目录下的 `SKILL.md` 文件 + 子目录中的 `SKILL.md` + `.cline` managed plugin 嵌套扫描 | `list_skills`（L119-144）：扫描 `skills_dir` 下的子目录，找包含 `SKILL.md` 的目录 | 中 | Cline 支持多层嵌套 + managed plugin，Charles 仅一层子目录 |
| 4.5.31 | 多目录加载 | `resolveSkillDirectories`（L135-154）支持 workspace + global + plugin 多目录，`dedupeDirectoryPaths` 去重 | `load_skills_multi_dir`（L443-485）+ `load_skills_with_dirs`（L488-508）支持多目录，后加载覆盖先加载 | 高 | 两者均支持多目录加载，覆盖策略不同：Cline dedupe + 同名冲突由 watcher 处理，Charles 显式 override |
| 4.5.32 | 文件名固定 | `SKILL_FILE_NAME = "SKILL.md"`（L24） | `skill_file = skill_dir / "SKILL.md"`（L135） | 高 | 完全一致 |

---

## 三、重点差距详细说明

### 3.1 字段清单差异：Charles 扩展 6 个字段，Cline 仅 5 个字段

#### Cline frontmatter 字段清单（5 个）

| 字段 | 类型 | 必填 | 来源 | 实际使用 |
|------|------|------|------|---------|
| `name` | string | 代码可选 / 文档必填 | user-instruction-config-loader.ts L296 | 用于 skill id 解析 + description 展示 |
| `description` | string | 代码可选 / 文档必填（max 1024） | L304 | 用于 LLM 判断是否触发 skill |
| `disabled` | boolean | 可选 | L305-306 | 用于禁用 skill |
| `enabled` | boolean | 可选（legacy） | L307 | 用于禁用 skill（legacy 写法） |
| `metadata` | 任意对象 | 可选 | cline-sdk/SKILL.md + opentui/SKILL.md 示例 | 透传到 `frontmatter` 字段，下游可访问 |

Cline SKILL.md 示例（`.agents/skills/cline-sdk/SKILL.md` L1-6）：
```yaml
---
name: cline-sdk
description: Comprehensive Cline SDK skill for building AI agents...
metadata:
   references: agent, clinecore
---
```

#### Charles frontmatter 字段清单（11 个 = Cline 5 个 + Charles 扩展 6 个）

| 字段 | 类型 | 必填 | 来源 | 实际使用 |
|------|------|------|------|---------|
| `name` | string | 可选 | loader.py L231 | 用于 skill id 解析 |
| `description` | string | 可选 | L232 | 用于 skills_summary 表格展示 |
| `disabled` | boolean | 可选 | L239 | 用于禁用 skill（Phase 31.4） |
| `enabled` | boolean | 可选（legacy） | L240-241 | 用于禁用 skill（legacy 写法） |
| `always` | boolean | 可选 | L234 | **实际使用**：registry.py L183-210 启动时加载指令 |
| `when_to_use` | string | 可选 | L282 | **实际使用**：registry.py L245-250 skills_summary 表格 |
| `keywords` | string/list | 可选 | L233 | **dead metadata**：解析但未消费 |
| `capabilities` | string/list | 可选 | L235 | **dead metadata**：解析但未消费 |
| `allowed_tools` | string/list | 可选 | L236 | **dead metadata**：解析但未消费（Phase 20） |
| `scripts` | string/list | 可选 | L270 | **实际使用**：skill_tool.py L212-213 返回 metadata |
| `source_dir` | — | — | L296 | 运行时填充，非 frontmatter 字段 |

Charles SKILL.md 示例（`agent_config/skills/read-pdf/SKILL.md` L1-6）：
```yaml
---
name: read-pdf
description: "查询上市公司年报/季报/公告等PDF叙述性内容..."
when_to_use: "用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"
always: true
---
```

#### Charles 8 个技能 frontmatter 字段使用统计

| 技能 | name | description | when_to_use | always | 其他扩展字段 |
|------|------|-------------|-------------|--------|-------------|
| bond-credit-review | ✓ | ✓ | ✓ | — | — |
| compare-reports | ✓ | ✓ | ✓ | — | — |
| financial-analysis | ✓ | ✓ | ✓ | — | — |
| read-pdf | ✓ | ✓ | ✓ | ✓ | — |
| sentiment-analysis | ✓ | ✓ | ✓ | — | — |
| stock-price | ✓ | ✓ | ✓ | — | — |
| web-search | ✓ | ✓ | ✓ | — | — |
| write-report | ✓ | ✓ | ✓ | — | — |

统计：
- `name` + `description` + `when_to_use`：8/8 技能使用（100%）
- `always: true`：1/8 技能使用（12.5%，仅 read-pdf）
- `keywords`/`capabilities`/`allowed_tools`/`scripts`：0/8 技能使用（0%，均为 dead metadata）

### 3.2 always 标记：Charles 独有机制（源自 nanobot）

**Cline 无 always 字段**。Cline skills 一律按需加载：LLM 根据 description 判断是否触发 `use_skill` 工具，触发后才加载 SKILL.md body（skills.mdx L17-25 Progressive Loading 表格）。

**Charles always 字段**源自 nanobot `get_always_skills()`（registry.py L184 注释），实现"Level 2 始终加载"语义：

```python
# registry.py L183-210
def get_always_skills(self) -> list[str]:
    """获取 always=True 的技能名称列表 — 对标 nanobot get_always_skills()"""
    return [name for name, meta in self._skills.items() if meta.always]

def load_always_instructions(self) -> str:
    """加载所有 always=True 技能的指令"""
    always_names = self.get_always_skills()
    if not always_names:
        return ""
    parts = []
    for name in always_names:
        ...
    return "\n\n".join(parts)
```

`always=True` 的技能指令在 system prompt 增强层注入（context.py L632-636）：
```python
if self._enhancements.get("always_skills") and self.skills_registry:
    body = self.skills_registry.load_always_instructions()
    if body:
        rules.append(("charles-always-skills", body))
```

**评估**：此为 Charles 独有增强，非 nanobot 残留。`always` 字段被 registry.py 实际消费，构成 Charles 的"Level 1 元数据 + Level 2 always 指令 + Level 3 use_skill 触发"三层加载模型的一部分。Cline 仅有 Level 1 + Level 2 两层。

### 3.3 when_to_use 字段：Charles 独有增强（Phase P5）

**Cline 无 when_to_use 字段**。Cline "何时使用"语义隐含在 `description` 字段中（skills.mdx L70 "description tells Cline when to use this skill"）。skills.mdx L121-141 给出的 description 范例均包含触发条件："Use when deploying, updating infrastructure, or managing AWS resources"。

**Charles when_to_use 字段**为 Phase P5 新增，将"何时使用"从 description 中拆分为独立字段，用于 `skills_summary` 表格的"何时使用"列填充：

```python
# registry.py L240-250
def skills_summary(self) -> str:
    ...
    for skill in all_skills:
        desc = skill.description or "(无描述)"
        # Phase P5: 何时使用 — 从 when_to_use 字段填充，与描述合并展示
        when_to_use = skill.when_to_use or "(见 SKILL.md)"
        if len(when_to_use) > 60:
            when_to_use = when_to_use[:60] + "..."
        when_to_use = when_to_use.replace("\n", " ")
        lines.append(f"- {skill.name} ({when_to_use}): {desc}")
```

**评估**：此为 Charles 独有增强，非 nanobot 残留。Charles 8 个技能的 frontmatter 均使用 `when_to_use` 字段（100%），说明这是 Charles 项目主动设计的字段拆分策略，而非残留。

### 3.4 dead metadata：keywords / capabilities / allowed_tools 三个字段解析但未消费

Charles `SkillMetadata` 解析了 3 个字段但下游从未访问：

- `keywords`（loader.py L233 + L244-249）：解析为 `list[str]`，但 `grep -r "\.keywords"` 在 `agent/` 目录下无任何 `skill.keywords` 访问。
- `capabilities`（loader.py L235 + L252-255）：解析为 `list[str]`，但 `grep -r "\.capabilities"` 在 `agent/` 目录下的匹配均为 `model.capabilities` / `provider.capabilities`，无 `skill.capabilities` 访问。
- `allowed_tools`（loader.py L236 + L259-266）：解析为 `list[str] | None`，但 `grep -r "\.allowed_tools"` 在 `agent/` 目录下无任何 `skill.allowed_tools` 访问。SkillsTool 不创建子 agent（skill_tool.py L18-22 明确说明），因此 `allowed_tools` 永远不会被消费。

**来源评估**：
- `keywords` + `capabilities`：源自 nanobot SkillsLoader 的 fallback 匹配机制（loader.py L5 注释 "提取 name / description / keywords / always / capabilities 等元数据"）。nanobot 原始实现中 `keywords` 用于关键词匹配 fallback，`capabilities` 用于能力声明。Charles 从未实现 fallback 匹配，这两个字段成为 dead metadata。**属于实现逻辑残留**（nanobot 设计残留，非代码残留）。
- `allowed_tools`：Phase 20 新增（loader.py L74 注释），概念源自 Cline `config.subAgentTools`（per-skill 工具集）。但 Charles SkillsTool 不创建子 agent（skill_tool.py L18-22），此字段永远不会被消费。**属于设计残留**（Phase 20 设计残留，非 nanobot 残留）。

### 3.5 toggle 写入功能缺失

**Cline** 提供 `skill-frontmatter-toggle.ts`（全文 89 行）实现 SKILL.md 文件的 enable/disable 切换：

```typescript
// skill-frontmatter-toggle.ts L51-74
export function updateSkillMarkdownEnabledState(content, enabled) {
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

export async function toggleSkillFrontmatter({ filePath, enabled }) {
    const content = await readFile(filePath, "utf8");
    const updated = updateSkillMarkdownEnabledState(content, enabled);
    await writeFile(filePath, updated);
    return { filePath, enabled, disabled: !enabled };
}
```

**Charles** `loader.py` 仅提供 `disabled`/`enabled` 字段的**读取**（L239-241），无写入接口。Charles 的 enable/disable 切换通过删除 SKILL.md 文件或重命名目录实现，而非修改 frontmatter。

**影响**：Charles 无法通过 API 动态切换 skill 状态。Cline 的 Skills 菜单 UI（skills.mdx L93-97 "Toggling Skills"）依赖此功能。Charles 无此 UI 需求，因此缺失可接受。

### 3.6 解析容错策略相反

**Cline 严格模式**：
- YAML 解析失败：`throw new Error('Failed to parse YAML frontmatter: ${parseError}')`（L289-291）
- 字段类型不符：`throw new Error("Frontmatter field '${fieldName}' must be a string/boolean.")`（L239, L256）
- instructions body 为空：`throw new Error("Missing instructions body in skill file.")`（L294）

**Charles 宽松模式**：
- YAML 解析失败：`except Exception: pass` 后 fallback 到自研简单解析器（L389-420）
- 字段类型不符：无校验，依赖 PyYAML 解析结果 + `bool()`/`str()` 强转
- instructions body 为空：无校验，返回空字符串

**评估**：两种策略都合理。Cline 严格模式适合 IDE 集成（错误立即暴露），Charles 宽松模式适合生产环境（避免单个技能解析失败影响整体加载）。Charles 的 fallback 简单解析器（L392-420）为 nanobot 残留实现（L392 注释 "Fallback: 简单 YAML 解析 — 对标 nanobot fallback"），但功能合理，不算负面残留。

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（8 处，loader.py 1 个文件）

| # | 文件 | 行号 | 残留内容 | 类型 | 影响 |
|---|------|------|---------|------|------|
| 1 | loader.py | L2 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | 模块 docstring | 无功能影响，文档残留 |
| 2 | loader.py | L29 | `对标 nanobot:` + L30 `agent/skills.py SkillsLoader: list_skills / load_skill / _parse_frontmatter` + L31 `PyYAML 解析 + fallback 简单解析` | 模块 docstring | 无功能影响，文档残留 |
| 3 | loader.py | L48 | `"""技能元数据 — 对标 Cline frontmatter + nanobot metadata` | 类 docstring | 无功能影响，文档残留 |
| 4 | loader.py | L96 | `"""技能加载器 — 对标 Cline skills discovery + nanobot SkillsLoader` | 类 docstring | 无功能影响，文档残留 |
| 5 | loader.py | L167 | `对标 nanobot: load_skill() + _strip_frontmatter()` | 方法 docstring | 无功能影响，文档残留 |
| 6 | loader.py | L222 | `"""解析 SKILL.md 文件 — 对标 nanobot get_skill_metadata()` | 方法 docstring | 无功能影响，文档残留 |
| 7 | loader.py | L392 | `# Fallback: 简单 YAML 解析 — 对标 nanobot fallback` | 行内注释 | 无功能影响，文档残留 |
| 8 | loader.py | L423 | `"""去除 YAML frontmatter — 对标 nanobot _strip_frontmatter()` | 方法 docstring | 无功能影响，文档残留 |

**评估**：8 处均为注释/docstring 残留，无功能影响。这些注释记录了 Charles 技能加载器的设计来源（Cline + nanobot 双重对标），属于历史文档。建议保留，不需清理。

### 4.2 实现逻辑残留（1 处）

| # | 文件 | 行号 | 残留内容 | 类型 | 影响 |
|---|------|------|---------|------|------|
| 1 | loader.py | L392-420 | `_parse_frontmatter` 的 fallback 简单 YAML 解析器：PyYAML 失败后用自研解析器解析 `key: value` + `- item` 列表 | 实现逻辑残留 | **中性**。功能合理（容错），但实现源自 nanobot |

**详细分析**：

Charles `_parse_frontmatter`（L364-420）的 fallback 解析器（L392-420）为 nanobot 残留实现：

```python
# L384-390：优先 PyYAML
try:
    import yaml
    result = yaml.safe_load(raw)
    if isinstance(result, dict):
        return result
except Exception:
    pass

# L392-420：fallback 简单解析 — 对标 nanobot fallback
metadata: dict[str, Any] = {}
current_key: str | None = None
for line in raw.split("\n"):
    stripped = line.rstrip("\r").strip()
    if stripped.startswith("- ") and current_key:
        ...
    if ":" in line and not stripped.startswith("-"):
        key, value = line.split(":", 1)
        ...
```

**评估**：此 fallback 解析器为 nanobot 残留，但**功能合理**：
- PyYAML 在正常情况下都能成功解析，fallback 极少触发
- fallback 解析器处理了基本的 `key: value` 和 `- item` 列表语法，覆盖常见 frontmatter
- 解析失败时返回空 dict，不会导致技能加载崩溃

**建议**：保留此 fallback 解析器。虽然源自 nanobot，但它提供了容错能力，符合 Charles 的宽松解析策略。注释 "对标 nanobot fallback" 可保留作为设计来源记录。

### 4.3 设计残留（非代码残留，3 处）

| # | 字段 | 来源 | 当前状态 | 评估 |
|---|------|------|---------|------|
| 1 | `keywords` | nanobot SkillsLoader fallback 匹配 | dead metadata，解析但未消费 | 设计残留，建议清理或实现 fallback 匹配 |
| 2 | `capabilities` | nanobot SkillsLoader 能力声明 | dead metadata，解析但未消费 | 设计残留，建议清理 |
| 3 | `allowed_tools` | Phase 20 子 agent 工具集（对标 Cline `config.subAgentTools`） | dead metadata，SkillsTool 不创建子 agent | 设计残留，建议清理 |

**注意**：`always` 字段虽然源自 nanobot `get_always_skills()`，但已被 Charles registry.py 实际使用（L183-210），**不算残留**，属于 Charles 独有增强。

---

## 五、与 AGENT_COMPARISON_PLAN_V2.md 计划表对标

| 计划表项 | 计划表描述 | 实际状态 | 说明 |
|---------|-----------|---------|------|
| 4.5 frontmatter 字段清单 | 对比 Cline + Charles frontmatter 字段 | 已完成 | Cline 5 个字段，Charles 11 个字段（含 6 个扩展） |
| 4.5 字段类型 | 对比字段类型校验 | 已完成 | Cline 严格校验（parseStringField + parseBooleanField），Charles 无校验 |
| 4.5 disabled toggle | 对比 disabled 字段 + toggle 功能 | 已完成 | 读取对齐（Phase 31.4），Charles 缺失 toggle 写入功能 |
| 4.5 always 标记 | 对比 always 字段 | 已完成 | Charles 独有，Cline 无 always 概念 |
| 4.5 description 字段 | 对比 description 字段 | 已完成 | 两者均可选，Cline 文档规范 max 1024 字符 |
| 4.5 name 字段 | 对比 name 字段 | 已完成 | 两者均支持 fallback 到目录名 |
| 4.5 when_to_use 字段 | 对比 when_to_use 字段 | 已完成 | Charles 独有（Phase P5），Cline 无此字段 |
| 4.5 frontmatter 解析方式 | 对比解析流程 | 已完成 | BOM + 正则 + YAML 对齐，容错策略相反 |

---

## 六、结论

### 6.1 已对齐项（Phase 31.4 + Phase 3.5/I12 已修复）

1. **BOM 剥离**：两者均处理 Windows Notepad "UTF-8 with BOM" 文件
2. **frontmatter 正则**：两者均用 `^---\r?\n(.*?)\r?\n---\r?\n?` 支持 CRLF + LF
3. **YAML 解析库**：Cline `yaml` npm 包 vs Charles PyYAML，语义等价
4. **name 字段 fallback**：两者均支持 fallback 到目录名
5. **description 字段**：两者均为可选 string
6. **disabled 字段**：两者均支持 `disabled: true`（推荐）
7. **enabled 字段（legacy）**：两者均支持 `enabled: false` legacy 写法
8. **disabled 优先级**：`disabled` 优先，`enabled: false` fallback，逻辑完全一致
9. **文件名固定**：两者均固定 `SKILL.md`

### 6.2 Charles 独有增强（非残留）

1. **always 字段**：always=True 的技能在启动时自动加载指令到 system prompt（registry.py L183-210）
2. **when_to_use 字段**：用于 skills_summary 表格"何时使用"列填充（registry.py L245-250）
3. **scripts 字段**：自动发现技能目录下的 .py 脚本（loader.py L300-342），SkillsTool 返回 metadata
4. **多目录加载 override**：`load_skills_multi_dir` + `load_skills_with_dirs` 支持多目录覆盖（loader.py L443-508）

### 6.3 待修复差距

1. **toggle 写入功能缺失**：Charles 无 `toggleSkillFrontmatter` 写入接口。**影响**：无法通过 API 动态切换 skill 状态。**优先级**：低（Charles 无 UI 需求）。
2. **dead metadata 清理**：`keywords`/`capabilities`/`allowed_tools` 三个字段解析但未消费。**影响**：代码冗余，SkillMetadata dataclass 字段误导。**优先级**：低（不影响功能）。
3. **metadata 透传缺失**：Charles 不保留原始 frontmatter dict，仅提取已知字段。**影响**：无法访问未知 frontmatter 字段。**优先级**：低（Charles frontmatter 字段已固定）。

### 6.4 nanobot 残留总结

- **注释残留**：8 处（loader.py 1 个文件），均为 docstring/注释，无功能影响，建议保留作为设计来源记录。
- **实现逻辑残留**：1 处（`_parse_frontmatter` 的 fallback 简单 YAML 解析器，L392-420），功能合理（容错），建议保留。
- **设计残留**：3 处（`keywords`/`capabilities`/`allowed_tools` 三个 dead metadata 字段），建议清理或实现消费逻辑。
- **非残留**：`always` 字段虽源自 nanobot，但已被 Charles registry.py 实际使用，属于 Charles 独有增强。
