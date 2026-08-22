# Phase 7.19 nanobot 残留清理对比

> 对比范围：汇总 Phase 3-7 所有阶段发现的 nanobot 残留，进行整体清理状态评估。覆盖 `agent/` 目录下 12 个含 nanobot 引用的源文件、`agent_config/skills/` 下 8 个 SKILL.md、`agent/skills/__pycache__/` 下 3 个 .pyc 死文件、1 个孤儿工具文件，以及 18 个技能脚本。
>
> 验证方法：Grep 搜索 `nanobot` 在 `e:\jikeAI\code\CASE-AI量化系统\agent\` 目录 + 交叉核对 Phase 3-7 各阶段报告（重点：P4.20 nanobot 残留专项审计、P5.10 Always Skills 段、P7.4 LLM Provider、P7.11 Sub-agent、P3.1 Tool Infrastructure 等）。
>
> 本报告未修改任何源码，仅输出审计报告文件。

---

## 一、执行摘要

### 1.1 总体结论

Charles 实现（即当前 `agent/` 目录代码）在 Phase 3-7 对标 Cline 的过程中，已**完成 sub-agent 机制源码删除**（`sub_agent.py` / `sub_agent_worker.py` 已不存在），但仍存在**大量 nanobot 风格残留**，分两层：

1. **注释残留（55 处）**：分散在 12 个 Python 源文件的 docstring/注释中，以"对标 nanobot ..."句式记录历史溯源，不影响运行时行为，但增加代码阅读噪音。
2. **实现逻辑残留（约 57 处）**：集中在 skills 系统（always 预加载机制、when_to_use 字段、SKILL.md 三段式章节、PyYAML fallback）和 sub-agent 遗留物（孤儿工具、.pyc 缓存、死代码字段），**影响运行时行为或文件系统整洁度**。

### 1.2 与 Cline 的对比

| # | 对比项 | Cline | Charles | 关键差异 |
|---|--------|-------|---------|---------|
| 7.19.1 | nanobot 引用清理 | 无 | 有（12 个源文件 + 8 个 SKILL.md） | F-base 差距 |
| 7.19.2 | 遗留 sub_agent.py | 无 | 源码已删除，仅剩 .pyc 缓存（3 个） | Charles 部分清理 |
| 7.19.3 | 遗留 sub_agent_worker.py | 无 | 源码已删除，仅剩 .pyc 缓存（1 个） | Charles 部分清理 |
| 7.19.4 | 遗留 server.py::_handle_sub_agent_event | 无 | 无（已删除） | 已对齐 |
| 7.19.5 | 孤儿工具 attempt_completion.py | 无 | 有（96 行未注册） | Charles 待清理 |
| 7.19.6 | always 预加载机制 | 无 | 有（完整实现链路） | nanobot 实现逻辑残留 |
| 7.19.7 | when_to_use 字段 | 无（用 description 内嵌） | 有（字段+解析+消费） | nanobot 实现逻辑残留 |
| 7.19.8 | SKILL.md 三段式章节 | 无（用 Workflow 步骤内嵌） | 有（8 个 SKILL.md 全部命中） | nanobot 指令文档残留 |

### 1.3 计划文件状态修正

AGENT_COMPARISON_PLAN_V2.md L2972 标注 "`agent/tools/base.py` L2/L11/L37/L188 仍有 nanobot 引用"——**此标注已过时**。当前 `agent/tools/` 目录下已无 `base.py` 文件，nanobot 引用实际分布在 `__init__.py` / `exec_tool.py` / `file_tools.py` / `web_tool.py` 四个文件（详见第 4 节）。L2977 "遗留 sub_agent.py ~1650 行"也已过时——源码已删除。

---

## 二、全局 nanobot 残留统计

### 2.1 注释残留 vs 实现逻辑残留

| 模块 | 注释残留数 | 实现逻辑残留数 | 总计 |
|---|---|---|---|
| agent/skills/（4 个 Python 文件） | 15 | 10 | 25 |
| agent_config/skills/（8 个 SKILL.md） | 0 | 33 | 33 |
| agent_config/skills/（18 个脚本） | 0 | 2 | 2 |
| agent/tools/（4 个 Python 文件） | 27 | 1 | 28 |
| agent/providers/（qwen.py） | 7 | 0 | 7 |
| agent/server.py | 3 | 0 | 3 |
| agent/session.py | 2 | 0 | 2 |
| agent/context.py | 1 | 0 | 1 |
| agent/skills/__pycache__/（3 个 .pyc） | — | 3 | 3 |
| agent/tools/attempt_completion.py（孤儿） | — | 1 | 1 |
| **合计** | **55** | **50** | **105** |

> 注：实现逻辑残留按"残留点"计数，一个机制（如 always 预加载）可能跨多文件多方法但仍计为多个残留点（字段定义、解析、查询、加载、注入各计 1 处）。本表与 P4.20 的 60 处（15 注释 + 45 实现）略有差异，因本报告额外计入 sub_agent 遗留物（.pyc + 孤儿工具 + 死代码）和 tools/providers/server/session/context 的注释残留（P4.20 仅覆盖 skills 系统）。

### 2.2 按严重程度分类

| 严重程度 | 注释残留 | 实现逻辑残留 | 总计 | 典型项目 |
|---|---|---|---|---|
| 高（影响功能行为/与 Cline 设计哲学冲突） | 0 | 35 | 35 | always 机制（7 处）、when_to_use 字段（11 处）、三段式章节（24 处）、PyYAML fallback（1 处）、孤儿工具（1 处）|
| 中（影响代码整洁度/文件系统残留） | 0 | 7 | 7 | .pyc 死文件（3 处）、allowed_tools 死代码（1 处）、脚本 fallback（2 处）、skill_tool 静默异常（1 处，计低）|
| 低（文档性引用） | 55 | 1 | 56 | docstring 提到 nanobot（55 处）、except Exception 静默（1 处）|

### 2.3 按 nanobot 风格特征分类

| 特征编号 | 特征名称 | 是否残留 | 残留数 | 严重程度 |
|---|---|---|---|---|
| 1 | camelCase 命名 | 否 | 0 | 无 |
| 2 | dict 而非 dataclass | 否 | 0 | 无 |
| 3 | try/except + fallback | 是 | 5 | 中 |
| 4 | JSON 而非 YAML | 否 | 0 | 无 |
| 5 | import 而非 subprocess | 否 | 0 | 无 |
| 6 | 字符串而非 AgentToolResult | 否 | 0 | 无 |
| 7 | docstring 提到 nanobot | 是 | 55 | 低（数量多） |
| 8 | always 预加载机制（nanobot 独有） | 是 | 7 | 高 |
| 9 | when_to_use 字段（nanobot 风格） | 是 | 11 | 高 |
| 10 | 三段式章节（nanobot 风格） | 是 | 24 | 高 |
| 11 | sub-agent 孤儿工具/.pyc（nanobot 遗留物） | 是 | 4 | 中 |
| 12 | allowed_tools 死代码（nanobot sub-agent 配置） | 是 | 1 | 中 |

---

## 三、逐模块残留清单

### 3.1 tools 模块（agent/tools/）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/tools/__init__.py` | 1 | 0 | L2: `"""工具系统 — 对标 Cline extensions/tools 和 nanobot agent/tools` |
| `agent/tools/exec_tool.py` | 12 | 0 | L2/L8/L9/L10/L18/L19/L41/L57/L123/L165/L181/L263：docstring 与行内注释多次"对标 nanobot shell.py / _guard_command / _MAX_OUTPUT / deny_patterns" |
| `agent/tools/file_tools.py` | 7 | 0 | L2/L7/L12/L27/L115/L130/L165：docstring 与行内注释"对标 nanobot FilesystemTool / filesystem.py L150-176 / 行号格式" |
| `agent/tools/web_tool.py` | 7 | 0 | L2/L9/L10/L13/L28/L111/L165：docstring 与行内注释"对标 nanobot WebSearchTool / web.py L124-140 / _search_duckduckgo / _format_results / fallback 方案" |
| `agent/tools/attempt_completion.py` | 0 | 1（孤儿工具） | 全文 96 行 `AttemptCompletionTool` 完整类定义，**未在任何位置注册**（不在 `__init__.py` 的 `create_default_tools()` / `__all__` / `routing.py` 中）|
| **小计** | **27** | **1** | **28** |

**说明**：tools 模块的 nanobot 残留**以注释为主**（27 处 docstring 对标说明），实现逻辑残留仅 1 处（孤儿工具 `attempt_completion.py`）。tools 核心实现（exec_tool / file_tools / web_tool）的运行时逻辑已对齐 Cline，注释残留属历史溯源文档。

### 3.2 skills 模块（agent/skills/）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/skills/__init__.py` | 2 | 0 | L2: `"""技能系统 — 对标 Cline skills + nanobot SkillsLoader`；L23-26: `对标 nanobot: agent/skills.py: SkillsLoader 类; frontmatter 解析: PyYAML + fallback` |
| `agent/skills/loader.py` | 8 | 4 | 注释：L2/L29/L48/L96/L167/L222/L392/L423 docstring "对标 nanobot SkillsLoader / load_skill / _strip_frontmatter / get_skill_metadata / fallback"。实现：① L70 `always: bool = False` 字段；② L81 `when_to_use: str = ""` 字段；③ L282 `when_to_use` 解析；④ L384-420 PyYAML fallback 简单解析 |
| `agent/skills/registry.py` | 4 | 4 | 注释：L2/L20/L100/L184 docstring "对标 nanobot SkillsLoader / build_skills_summary / get_always_skills"。实现：① L183-191 `get_always_skills()`；② L193-208 `load_always_instructions()`；③ L272-285 `load_always_instructions_as_rule()`；④ L245-250 `build_summary()` 拼接 `when_to_use` |
| `agent/skills/skill_tool.py` | 1 | 2 | 注释：L18-22 "这与 nanobot 的子 agent 隔离执行有本质区别"。实现：① L245-253 `except Exception: pass`；② L255-267 `except Exception: return []` |
| `agent/skills/__pycache__/sub_agent.cpython-310.pyc` | — | 1 | 死文件（源码已删） |
| `agent/skills/__pycache__/sub_agent.cpython-311.pyc` | — | 1 | 死文件（源码已删） |
| `agent/skills/__pycache__/sub_agent_worker.cpython-310.pyc` | — | 1 | 死文件（源码已删） |
| **小计** | **15** | **13** | **28** |

**说明**：skills 模块是 nanobot 残留**最密集**的区域。注释残留 15 处 + 实现逻辑残留 13 处（含 3 个 .pyc 死文件）。其中 always 预加载机制（3 个方法 + 1 个字段 + 1 个 frontmatter 配置）和 when_to_use 字段（1 个字段 + 1 个解析 + 1 个消费）是**完整的 nanobot 实现链路**，与 Cline 的 on-demand 设计哲学冲突（详见 P5.10）。

### 3.3 prompt 模块（agent_config/skills/ SKILL.md）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `bond-credit-review/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L59）；"## 脚本调用规则"（L65）；"## 禁止行为"（L70） |
| `compare-reports/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L56）；"## 脚本调用规则"（L62）；"## 禁止行为"（L74） |
| `financial-analysis/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L85）；"## 脚本调用规则"（L93）；"## 禁止行为"（L107） |
| `read-pdf/SKILL.md` | 0 | 5 | frontmatter `when_to_use`（L4）+ `always: true`（L5）；正文"## 脚本角色说明"（L73）；"## 脚本调用规则"（L87）；"## 禁止行为"（L118） |
| `sentiment-analysis/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L73）；"## 脚本调用规则"（L81）；"## 禁止行为"（L87） |
| `stock-price/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L49）；"## 脚本调用规则"（L55）；"## 禁止行为"（L61） |
| `web-search/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L58）；"## 脚本调用规则"（L64）；"## 禁止行为"（L70） |
| `write-report/SKILL.md` | 0 | 4 | frontmatter `when_to_use`（L4）；正文"## 脚本角色说明"（L81）；"## 脚本调用规则"（隐含在 Step 中）；"## 禁止行为"（L98） |
| **小计** | **0** | **33** | **33** |

**说明**：8 个 SKILL.md 全部命中三类 nanobot 风格残留：① `when_to_use` frontmatter 字段（Cline 用 description 内嵌 "Use when..." 句式）；② `always: true` frontmatter 字段（仅 read-pdf，Cline 无此概念）；③ "脚本角色说明 / 脚本调用规则 / 禁止行为"三段式章节（Cline 用 Workflow Step 内嵌说明）。这些残留**直接影响 LLM 行为**——LLM 会按照三段式章节组织指令理解，而非 Cline 的 Workflow 步骤内嵌模式。

### 3.4 context 模块（agent/context.py）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/context.py` | 1 | 0 | L275: `extra_sections: [已废弃] nanobot 风格的额外段落，Cline 无此概念。保留参数签名仅为向后兼容，当前无调用方传入。` |
| **小计** | **1** | **0** | **1** |

**说明**：context 模块仅 1 处注释残留，`extra_sections` 参数已废弃且无调用方，但参数签名保留。always_skills 段的注入逻辑（`_build_enhancement_rules` 中 `charles-always-skills` rule 生成）虽属 nanobot 实现逻辑残留，但其 nanobot 字面引用已在 skills 模块计数，此处不重复。

### 3.5 providers 模块（agent/providers/qwen.py）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/providers/qwen.py` | 7 | 0 | L21: `兼容 nanobot 现有配置`；L49: `# 默认流式空闲超时（秒），与 nanobot 一致`；L116: `对标 nanobot openai_compat_provider.py 的客户端创建逻辑`；L214: `对标 nanobot openai_compat_provider.py _build_kwargs() 方法`；L253: `对标 nanobot _parse_chunks 的单 chunk 处理`；L385: `对标 nanobot _maybe_mapping() 方法`；L406: `对标 nanobot _get_nested_int() 但更通用` |
| **小计** | **7** | **0** | **7** |

**说明**：providers 模块**仅注释残留**，无实现逻辑残留。QwenModel 的运行时逻辑（tool_call_id 稳定性、reasoning_content 解析、apply_capability_downgrade）已对齐 Cline，注释残留属历史溯源文档（P7.4 结论）。

### 3.6 server 模块（agent/server.py）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/server.py` | 3 | 0 | L2: `"""SSE 服务端 — 对标 Cline server + nanobot routes/chat.py`；L4: `提供 /api/chat/stream SSE 端点，用 AgentRuntime 替换 nanobot。`；L28: `对标 nanobot: routes/chat.py _sse_generator() + _StreamCollectorHook` |
| **小计** | **3** | **0** | **3** |

**说明**：server 模块**仅注释残留**，无实现逻辑残留。SSE 端点实现已用 `AgentRuntime` 替换 nanobot，`_handle_sub_agent_event` 已删除（P7.11 确认），注释残留属历史溯源文档。

### 3.7 runtime 模块（agent/runtime.py）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/runtime.py` | 0 | 0 | L2362 系统提示词提及 `attempt_completion`，但属"工具名引用"而非"nanobot 字面引用"，不计入 nanobot 残留（P7.11 §4.1 已归类为 sub-agent 注释残留） |
| **小计** | **0** | **0** | **0** |

**说明**：runtime 模块无 nanobot 字面引用。L2362 的 `attempt_completion` 提及属工具名引用，归 P7.11 sub-agent 残留主题，本报告不计入。

### 3.8 session 模块（agent/session.py）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `agent/session.py` | 2 | 0 | L2: `"""会话管理 — 对标 Cline session persistence + nanobot session_key`；L22-24: `对标 nanobot: session_key 参数，内存存储` |
| **小计** | **2** | **0** | **2** |

**说明**：session 模块**仅注释残留**，无实现逻辑残留。会话持久化逻辑已对齐 Cline（P7.5 结论），`session_key` 仅在 docstring 中作为历史溯源提及。

### 3.9 其他模块（agent_config/skills/ 脚本）

| 文件 | 注释残留 | 实现逻辑残留 | 残留详情 |
|---|---|---|---|
| `read-pdf/scripts/parse_pdf_ocr.py` | 0 | 1 | L48/L66 `_pdf_page_to_base64_fallback` 函数：PyMuPDF 不可用时回退到 pdf2image（try/except + fallback 模式） |
| `sentiment-analysis/scripts/sentiment_scorer.py` | 0 | 1 | L198 `"fallback": True`：LLM 解析失败时手动计算基础统计作为 fallback |
| 其他 16 个脚本 | 0 | 0 | 未发现 nanobot 风格残留 |
| **小计** | **0** | **2** | **2** |

**说明**：脚本层面的 nanobot 残留较少（仅 2 处 fallback 模式），主要因脚本本身是命令行工具，通过 `argparse + main()` 模式组织，天然符合 Cline 的 subprocess 调用模型。

---

## 四、实现逻辑残留详细说明

### 4.1 always 预加载机制（高严重程度，7 处）

**残留位置**：
- `agent/skills/loader.py` L70（`SkillMetadata.always: bool = False` 字段定义）
- `agent/skills/loader.py` L234（`always = bool(frontmatter.get("always", False))` 解析逻辑）
- `agent/skills/loader.py` L288（`always=always` 传入 SkillMetadata 构造）
- `agent/skills/registry.py` L183-191（`get_always_skills()` 方法）
- `agent/skills/registry.py` L193-208（`load_always_instructions()` 方法）
- `agent/skills/registry.py` L272-285（`load_always_instructions_as_rule()` 方法，含"已自动加载"标注）
- `agent_config/skills/read-pdf/SKILL.md` L5（`always: true` frontmatter 字段，唯一实际配置）

**影响评估**：
- **与 Cline 设计哲学冲突**：Cline `docs/customization/skills.mdx` L9 明确"skills load on-demand"，`SkillConfig` / `SkillMetadata` 均无 `always` 字段。Charles 打破了 rules/skills 边界，将 rules 的 `alwaysApply` 概念引入 skills。
- **运行时行为差异**：启用 `enhancements.enabled=true` 时，always 技能的完整 Level 2 指令在 System Prompt 构建时预加载，增加 token 消耗。
- **当前默认关闭**：`agent_config/system_prompt.yaml` 配置 `enhancements.enabled: false`，always_skills 段**实际未注入** System Prompt。但代码层面具备注入能力。
- **nanobot 1:1 复刻**：溯源到 `nanobot/agent/skills.py` L203-211 `get_always_skills()` + `nanobot/agent/context.py` L53-57 `# Active Skills` 段注入，Charles 仅将包装格式从 `# Active Skills` 改为 `## charles-always-skills` rule。

### 4.2 when_to_use 字段（高严重程度，11 处）

**残留位置**：
- `agent/skills/loader.py` L79-81（`SkillMetadata.when_to_use: str = ""` 字段定义，注释自承"对标 Cline description 字段中隐含的'何时使用'语义"）
- `agent/skills/loader.py` L282（`when_to_use = str(frontmatter.get("when_to_use", ""))` 解析逻辑）
- `agent/skills/loader.py` L297（`when_to_use=when_to_use` 传入 SkillMetadata 构造）
- `agent/skills/registry.py` L245-250（`build_summary()` 中拼接 `when_to_use` 到技能摘要，**被 system prompt 消费**）
- 8 个 SKILL.md frontmatter 全部有 `when_to_use` 字段（bond-credit-review / compare-reports / financial-analysis / read-pdf / sentiment-analysis / stock-price / web-search / write-report）

**影响评估**：
- **生产环境被消费**：`build_summary()` 将 `when_to_use` 拼接到技能摘要，技能摘要经 `{{CHARLES_RULES}}` 占位符注入 System Prompt，LLM 可见。
- **与 Cline 不一致**：Cline 用 description 字段内嵌 "Use when..." 句式表达"何时使用"语义，无单独字段。
- **LLM 行为影响**：LLM 会看到独立的 `when_to_use` 列，可能影响技能选择决策（与 Cline 的 description 内嵌模式不同）。

### 4.3 SKILL.md 三段式章节（高严重程度，24 处）

**残留位置**：8 个 SKILL.md 全部命中，每个 SKILL.md 含 3 个章节（"## 脚本角色说明" / "## 脚本调用规则" / "## 禁止行为"），共 8×3=24 处。

**影响评估**：
- **直接影响 LLM 行为**：LLM 按 SKILL.md 指令组织理解，三段式章节是 nanobot 风格的指令文档结构。
- **与 Cline 不一致**：Cline 用 Workflow Step 内嵌说明（如"Step 1: ...（注意：股票代码必须带交易所后缀）"），规则分散到对应步骤的"前置条件 / 失败处理 / 唯一性约束"中。
- **可读性差异**：三段式章节将规则集中化，但与具体 Step 脱节，LLM 可能忽略规则上下文。

### 4.4 PyYAML fallback 简单解析（中严重程度，1 处）

**残留位置**：`agent/skills/loader.py` L384-420

**代码模式**：
```python
try:
    import yaml
    # ...
except Exception:
    pass
# 手写简单 YAML 解析（L392-420）
```

**影响评估**：
- **违反用户规则**：用户规则明确"代码中不要有 fallback"，此实现违反规则。
- **与 Cline 不一致**：Cline 原生直接用 yaml 解析，无手写 fallback。
- **维护成本**：手写 YAML 解析易出 bug，维护成本高。
- **运行时影响**：PyYAML 不可用时静默回退到手写解析，可能解析错误但无报错。

### 4.5 孤儿工具 attempt_completion.py（中严重程度，1 处）

**残留位置**：`agent/tools/attempt_completion.py`（全文 96 行）

**影响评估**：
- **代码完整但无调用路径**：`AttemptCompletionTool` 类定义完整（含 `completes_run=True` 生命周期），但未在 `agent/tools/__init__.py` 的 `create_default_tools()` / `__all__` / `routing.py` 中注册。
- **sub-agent 遗留物**：该工具是 sub-agent 机制的返回结果工具，因 `sub_agent.py` 已删除，该工具成为孤儿。
- **误导风险**：完整代码可能误导开发者以为该工具已注册，实际无任何 runtime 使用。
- **附带残留**：`agent/approval_policy.py` L42 `READ_ONLY_TOOLS` 集合仍包含 `"attempt_completion"`（死配置）。

### 4.6 __pycache__/*.pyc 死文件（低严重程度，3 处）

**残留位置**：
- `agent/skills/__pycache__/sub_agent.cpython-310.pyc`
- `agent/skills/__pycache__/sub_agent.cpython-311.pyc`
- `agent/skills/__pycache__/sub_agent_worker.cpython-310.pyc`

**影响评估**：
- **无运行时影响**：源码已删除，Python 不会加载这些 .pyc（因 .py 源文件不存在）。
- **文件系统残留**：占用磁盘空间，增加目录浏览噪音。
- **清理无风险**：直接删除即可，无副作用。

### 4.7 allowed_tools 死代码字段（低严重程度，1 处）

**残留位置**：
- `agent/skills/loader.py` L74（`allowed_tools: list[str] | None = None` 字段声明）
- `agent/skills/loader.py` L259-266（frontmatter 解析逻辑）

**影响评估**：
- **死代码**：字段被解析但无运行时消费方（因 `sub_agent.py` 已删除，无 sub-agent runtime 使用 `allowed_tools` 限制工具集）。
- **frontmatter 规范残留**：属 sub-agent 机制的配置字段，sub-agent 删除后该字段无意义。
- **保留理由**：属 frontmatter 规范，未来若重新引入 sub-agent 可能复用；或删除以保持代码整洁。

### 4.8 skill_tool.py 静默异常（低严重程度，2 处）

**残留位置**：
- `agent/skills/skill_tool.py` L245-253（`except Exception: pass`）
- `agent/skills/skill_tool.py` L255-267（`except Exception: return []`）

**影响评估**：
- **静默 fallback**：捕获异常后静默忽略或返回空列表，属轻微 fallback 行为。
- **与 Cline 不一致**：Cline 风格应让异常抛出或返回明确错误。
- **调试困难**：异常被吞掉，问题难以定位。

### 4.9 脚本 fallback（低严重程度，2 处）

**残留位置**：
- `read-pdf/scripts/parse_pdf_ocr.py` L48/L66（PyMuPDF → pdf2image fallback）
- `sentiment-analysis/scripts/sentiment_scorer.py` L198（LLM 解析失败 → 手动统计 fallback，含 `"fallback": True` 标记）

**影响评估**：
- **工程合理性**：依赖回退和业务降级属合理工程实践，但风格上仍可识别为 nanobot 特征（try/except + fallback）。
- **运行时影响**：`parse_pdf_ocr.py` 的依赖回退确保 PDF 解析可用性；`sentiment_scorer.py` 的手动统计确保结果可用性。
- **标记问题**：`sentiment_scorer.py` 的 `"fallback": True` 标记暴露 nanobot 风格，可改为中性描述。

---

## 五、清理优先级矩阵

| 优先级 | 残留项 | 数量 | 严重程度 | 清理难度 | 影响范围 | 建议动作 |
|---|---|---|---|---|---|---|
| **P0** | always 预加载机制 | 7 | 高 | 中 | skills/loader.py + registry.py + context.py + read-pdf/SKILL.md | 移除字段+方法+配置，或保留但修正 docstring |
| **P0** | when_to_use 字段 | 11 | 高 | 中 | skills/loader.py + registry.py + 8 个 SKILL.md | 合并到 description 字段（"Use when..."句式） |
| **P0** | SKILL.md 三段式章节 | 24 | 高 | 高 | 8 个 SKILL.md | 重构为 Workflow Step 内嵌说明 |
| **P1** | PyYAML fallback 简单解析 | 1 | 中 | 低 | skills/loader.py L384-420 | 删除 fallback，直接用 PyYAML |
| **P1** | 孤儿工具 attempt_completion.py | 1 | 中 | 低 | agent/tools/attempt_completion.py + approval_policy.py L42 | 删除文件 + 移除 approval_policy 引用 |
| **P1** | allowed_tools 死代码字段 | 1 | 中 | 低 | skills/loader.py L74/L259-266 | 删除字段+解析逻辑（或保留待未来复用） |
| **P2** | __pycache__/*.pyc 死文件 | 3 | 低 | 极低 | agent/skills/__pycache__/ | 直接删除 3 个 .pyc 文件 |
| **P2** | skill_tool.py 静默异常 | 2 | 低 | 低 | skills/skill_tool.py L245-267 | 改为 `logger.warning` 记录日志 |
| **P2** | 脚本 fallback | 2 | 低 | 低 | parse_pdf_ocr.py + sentiment_scorer.py | 保留回退逻辑，移除 `"fallback": True` 标记 |
| **P3** | docstring nanobot 对标说明 | 55 | 低 | 低 | 12 个 Python 源文件 | 统一清理或保留作为设计溯源 |

---

## 六、修复建议

### 6.1 P0 优先级（高严重程度，影响功能行为）

#### P0-1: always 预加载机制清理

**方案 A（推荐：保留但修正溯源）**：
1. 保留 `SkillMetadata.always` 字段、`get_always_skills()` / `load_always_instructions()` / `load_always_instructions_as_rule()` 方法、`_build_enhancement_rules()` 中的 `charles-always-skills` rule 生成。
2. 修正 docstring：将"对标 nanobot get_always_skills()"改为"Charles 独有增强（Cline 无等价物）"。
3. 理由：read-pdf 预加载有业务价值（高频年报查询），默认关闭（`enhancements.enabled=false`）不影响运行时。

**方案 B（严格对齐 Cline）**：
1. 从 `SkillMetadata` 移除 `always` 字段。
2. 从 `_parse_skill_file` 移除 `always` 解析逻辑。
3. 从 `SkillRegistry` 移除 `get_always_skills()` / `load_always_instructions()` / `load_always_instructions_as_rule()` 三个方法。
4. 从 `read-pdf/SKILL.md` 移除 `always: true` frontmatter 字段。
5. 全局搜索调用点，移除或改造为 Cline 风格的 use_skill 工具触发加载。

#### P0-2: when_to_use 字段清理

1. 将 8 个 SKILL.md 中的 `when_to_use` 内容合并到 `description` 字段，采用 Cline 风格的 "Use when ..." 句式。
2. 从 `SkillMetadata` 移除 `when_to_use` 字段。
3. 从 `_parse_skill_file` 移除 `when_to_use` 解析逻辑。
4. 从 `build_summary()` 移除 `when_to_use` 拼接逻辑，仅展示 `description`。

**示例**（read-pdf/SKILL.md frontmatter 修改后）：
```yaml
name: read-pdf
description: "查询上市公司年报/季报/公告等PDF叙述性内容，支持本地RAG查询；若本地无索引/PDF，自动下载并构建索引。Use when 用户询问年报/季报/公告内容、公司业务/订单/客户/供应商/风险因素等叙述性内容时"
```

#### P0-3: SKILL.md 三段式章节重构

1. 删除"## 脚本角色说明"章节，将脚本角色信息内嵌到对应 Step 的描述中。
2. 删除"## 脚本调用规则"章节，将规则内嵌到对应 Step 的命令说明中。
3. 删除"## 禁止行为"章节，将禁止事项分散到对应 Step 的"失败处理"或"跳过条件"中。

**示例**（stock-price/SKILL.md 修改后）：
```markdown
### Step 1: 获取 K 线数据
- **何时执行**: 用户询问股价/K线/走势/成交量时
- **前置条件**: MiniQMT 客户端已运行并登录
- **命令**:
  ```bash
  python agent_config/skills/stock-price/scripts/get_kline.py <股票代码> [周期] [条数]
  ```
- **参数约束**:
  - `<股票代码>` (必填): 带交易所后缀，如 `600519.SH`、`000858.SZ`、`688981.SH`。用户说公司名称时先转换为代码。
  - `[周期]` (可选): 默认 `1d`
  - `[条数]` (可选): 默认 `100`
- **预期输出**: K 线数据表格
- **失败处理**:
  - `xtquant not found` → 提示用户安装 xtquant 包
  - MiniQMT 连接失败 → 提示用户启动 MiniQMT 客户端
- **唯一性约束**: 本技能是查询股价的唯一正确途径，禁止用 `web_search` 查询股价/K线数据
```

### 6.2 P1 优先级（中严重程度，影响代码整洁度）

#### P1-1: 移除 PyYAML fallback 简单解析

1. 删除 `agent/skills/loader.py` L384-420 的 `try: import yaml; ... except Exception: pass` + 手写简单 YAML 解析。
2. 直接使用 PyYAML，若 PyYAML 不可用则抛出明确异常（`ImportError: PyYAML is required to parse SKILL.md frontmatter`）。
3. 同步更新 docstring，移除"对标 nanobot fallback"等注释。

#### P1-2: 删除孤儿工具 attempt_completion.py

1. 删除 `agent/tools/attempt_completion.py` 文件（96 行）。
2. 移除 `agent/approval_policy.py` L42 `READ_ONLY_TOOLS` 集合中的 `"attempt_completion"` 条目。
3. 评估 `agent/runtime.py` L2362 系统提示词是否需要修改（若仅保留 `submit_and_exit` 则修改提示词）。

#### P1-3: 清理 allowed_tools 死代码字段

**方案 A（删除）**：
1. 从 `SkillMetadata` 移除 `allowed_tools` 字段（loader.py L74）。
2. 从 `_parse_skill_file` 移除 `allowed_tools` 解析逻辑（loader.py L259-266）。
3. 全局搜索调用点，确认无消费方。

**方案 B（保留）**：保留作为 frontmatter 规范，未来若重新引入 sub-agent 可复用。但需在 docstring 中标注"当前无运行时消费方，属预留字段"。

### 6.3 P2 优先级（低严重程度，工程优化）

#### P2-1: 删除 __pycache__/*.pyc 死文件

直接删除以下 3 个文件：
- `agent/skills/__pycache__/sub_agent.cpython-310.pyc`
- `agent/skills/__pycache__/sub_agent.cpython-311.pyc`
- `agent/skills/__pycache__/sub_agent_worker.cpython-310.pyc`

#### P2-2: 重构 skill_tool.py 静默异常

将 `except Exception: pass` 改为 `except Exception as e: logger.warning("...", e)`，记录日志而非静默忽略。

#### P2-3: 重构脚本 fallback 标记

- `parse_pdf_ocr.py`：保留依赖回退（工程合理），但改写为显式依赖检测。
- `sentiment_scorer.py`：保留 LLM 失败时的手动统计（业务合理），但移除 `"fallback": True` 标记，改为 `"aggregation_method": "manual_stat"` 等中性描述。

### 6.4 P3 优先级（低严重程度，文档清理）

#### P3-1: 清理 docstring 中的 nanobot 对标说明

1. 移除所有"对标 nanobot"、"nanobot SkillsLoader"、"nanobot fallback"等注释（55 处，12 个文件）。
2. 保留"对标 Cline"部分（有价值的对照说明）。
3. 对于必要的历史对比（如 `skill_tool.py` L18-22 关于"与 nanobot 子 agent 隔离执行的区别"），可改写为直接陈述 Cline 设计，不提 nanobot。

---

## 七、验证方法

### 7.1 自动化验证（关键字检索）

```powershell
# 期望：无匹配（清理完成后）
Grep pattern="nanobot" path="e:\jikeAI\code\CASE-AI量化系统\agent"
Grep pattern="nanobot" path="e:\jikeAI\code\CASE-AI量化系统\agent_config\skills"
Grep pattern="when_to_use" path="e:\jikeAI\code\CASE-AI量化系统\agent\skills"
Grep pattern="when_to_use" path="e:\jikeAI\code\CASE-AI量化系统\agent_config\skills"
Grep pattern="always:\s*true" path="e:\jikeAI\code\CASE-AI量化系统\agent_config\skills"
Grep pattern="脚本角色说明|脚本调用规则|禁止行为" path="e:\jikeAI\code\CASE-AI量化系统\agent_config\skills"
Grep pattern="attempt_completion" path="e:\jikeAI\code\CASE-AI量化系统\agent\tools"
Grep pattern="sub_agent" path="e:\jikeAI\code\CASE-AI量化系统\agent\skills\__pycache__"
```

### 7.2 导入与单元测试

```powershell
python -c "from agent.skills import SkillLoader, SkillRegistry, SkillsTool, SkillMetadata; print('OK')"
python -c "from agent.tools import create_default_tools; tools = create_default_tools(); assert 'attempt_completion' not in [t.name for t in tools]; print('OK')"
python -m pytest tests/skills/ -v
```

### 7.3 SKILL.md frontmatter 校验

```powershell
python -c "
from agent.skills.loader import SkillLoader
loader = SkillLoader('agent_config/skills')
for s in loader.list_skills():
    assert not s.always, f'{s.name} still has always=True'
    assert not s.when_to_use, f'{s.name} still has when_to_use'
    print(f'{s.name}: OK')
"
```

### 7.4 功能验证

1. **技能加载验证**：启动 agent，确认 8 个技能均能通过 `skills` 工具加载指令。
2. **read-pdf 技能验证**：确认移除 `always: true` 后，read-pdf 技能不再自动注入 system prompt，而是通过 `skills` 工具按需加载。
3. **技能摘要验证**：调用 `SkillRegistry.build_summary()`，确认输出中不再包含 `when_to_use` 列。
4. **LLM 行为验证**：让 LLM 执行 stock-price 技能任务，确认 LLM 能从 Workflow Step 1 中正确获取"股票代码必须带交易所后缀"的约束（验证三段式章节重构后规则仍可被 LLM 理解）。
5. **孤儿工具验证**：确认 `attempt_completion.py` 删除后，`create_default_tools()` 返回的工具列表无变化（因该工具本就未注册）。

### 7.5 回归验证

1. 运行现有技能系统测试套件（如存在）。
2. 执行一轮完整的研报生成任务（write-report 技能），确认研报正文输出正常。
3. 执行一轮财报查询任务（financial-analysis 技能），确认 CSV 下载与指标计算正常。
4. 执行一轮年报查询任务（read-pdf 技能），确认 PDF 解析与 RAG 查询正常。

---

## 八、附录

### 8.1 检查覆盖声明

- **Phase 3-7 报告交叉核对**：100% 完整审阅 P4.20（nanobot 残留专项审计）、P5.10（Always Skills 段）、P7.4（LLM Provider）、P7.11（Sub-agent）四份关键报告。
- **Grep 搜索**：在 `agent/` 目录下搜索 `nanobot` 关键字，覆盖 12 个 Python 源文件、55 行匹配。
- **__pycache__ 检查**：确认 `agent/skills/__pycache__/` 下 3 个 sub_agent*.pyc 死文件。
- **SKILL.md 检查**：8 个 SKILL.md 100% 完整审阅（引用 P4.20 结论）。
- **脚本检查**：18 个技能脚本 100% 完整审阅（引用 P4.20 结论）。

### 8.2 与各阶段报告的关联

| 阶段报告 | 覆盖范围 | 本报告引用点 |
|---|---|---|
| P3.1 Tool Infrastructure | tools/__init__.py 工具系统架构 | §3.1 tools 模块注释残留 |
| P4.20 nanobot 残留专项审计 | skills 系统 4 个 Python 文件 + 8 个 SKILL.md + 18 个脚本 | §2 统计、§3.2-3.3、§4.1-4.3、§4.8-4.9 |
| P5.10 Always Skills 段 | context.py + registry.py always_skills 注入链路 | §4.1 always 预加载机制详细说明 |
| P7.4 LLM Provider | providers/qwen.py Provider 适配 | §3.5 providers 模块注释残留 |
| P7.11 Sub-agent | sub_agent.py 删除状态 + attempt_completion.py 孤儿 + .pyc 缓存 | §3.2 skills 模块 .pyc 残留、§4.5-4.6 孤儿工具与死文件 |
| P7.5 Session Persistence | session.py 会话管理 | §3.8 session 模块注释残留 |

### 8.3 计划文件状态修正记录

| 计划文件位置 | 原标注 | 实际状态 | 修正说明 |
|---|---|---|---|
| L2972 `agent/tools/base.py` L2/L11/L37/L188 有 nanobot 引用 | F-base 差距 | `base.py` 文件不存在 | 标注已过时，实际分布在 `__init__.py` / `exec_tool.py` / `file_tools.py` / `web_tool.py` |
| L2977 遗留 sub_agent.py ~1650 行 | Charles 待清理 | 源码已删除，仅剩 .pyc 缓存 | 标注已过时，源码清理完成 |
| L2978 遗留 sub_agent_worker.py | Charles 待清理 | 源码已删除，仅剩 .pyc 缓存 | 标注已过时，源码清理完成 |
| L2979 遗留 server.py::_handle_sub_agent_event | Charles 待清理 | 已删除 | 标注已过时，清理完成 |

---

## 九、总体结论

1. **Charles 已完成 sub-agent 源码清理**：`sub_agent.py` / `sub_agent_worker.py` 源文件已删除，`server.py::_handle_sub_agent_event` 已删除。计划文件 L2977-2979 的"待清理"标注已过时。

2. **nanobot 残留分两层**：
   - **注释残留（55 处）**：分散在 12 个 Python 源文件，以"对标 nanobot ..."句式记录历史溯源，不影响运行时行为。
   - **实现逻辑残留（约 50 处）**：集中在 skills 系统（always 预加载机制 7 处 + when_to_use 字段 11 处 + 三段式章节 24 处 + PyYAML fallback 1 处 + 脚本 fallback 2 处 + skill_tool 静默异常 2 处）和 sub-agent 遗留物（孤儿工具 1 处 + .pyc 死文件 3 处 + allowed_tools 死代码 1 处）。

3. **清理优先级**：
   - **P0（高）**：always 机制 + when_to_use 字段 + 三段式章节（共 42 处），与 Cline 设计哲学冲突，影响 LLM 行为。
   - **P1（中）**：PyYAML fallback + 孤儿工具 + allowed_tools 死代码（共 3 处），影响代码整洁度。
   - **P2（低）**：.pyc 死文件 + 静默异常 + 脚本 fallback 标记（共 7 处），工程优化。
   - **P3（低）**：docstring nanobot 对标说明（55 处），文档清理。

4. **建议策略**：
   - **保守策略**（推荐）：保留 always 机制（业务有价值，默认关闭）+ 清理 when_to_use + 重构三段式章节 + 删除孤儿工具 + 删除 .pyc + 清理 docstring。此策略保留 Charles 独有增强，同时向 Cline 对齐。
   - **严格策略**：全部清理，Charles 行为完全对齐 Cline 的 on-demand 设计哲学。

5. **本报告未修改任何源码**，仅输出审计报告文件。清理动作需在后续阶段按优先级逐步执行，每步清理后需运行验证方法确认功能正常。
