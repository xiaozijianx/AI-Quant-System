# Charles System Prompt 彻底重构计划（对齐 Cline）

> 生成时间：2026-07-27
> 目标：将 Charles 的 system prompt 构造方式从 nanobot 风格的 11 层显式拼接，彻底重构为 Cline 风格的 base prompt + rules 两层结构
> 原则：结构性对齐优先，合理增强保留，不追求字节级一致

---

## 一、Cline 的 system prompt 构造方式（源码确认）

### 1.1 构造链路

```
VSCode/CLI 入口
  ↓
buildClineSystemPrompt({ide, workspaceRoot, workspaceName, mode, providerId, platform})
  位置: sdk/packages/shared/src/prompt/cline.ts:110-165
  ↓
选择 base prompt 模板:
  - DEFAULT_CLINE_SYSTEM_PROMPT (sdk/packages/shared/src/prompt/system.ts)
  - YOLO_CLINE_SYSTEM_PROMPT
  ↓
替换占位符:
  {{PLATFORM_NAME}} / {{CURRENT_DATE}} / {{IDE_NAME}} / {{CWD}}
  {{CLINE_METADATA}}  ← workspace metadata
  {{CLINE_RULES}}     ← effectiveRules = [rules, MODE_TAG_INSTRUCTIONS, PLAN_MODE_INSTRUCTIONS]
  ↓
返回 config.systemPrompt
  ↓
SessionRuntimeOrchestrator.composeSystemPrompt()
  位置: sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts:680-688
  ↓
从 ContributionRegistry 获取 registered rules
  ↓
mergeSystemPromptRules(base, rules)
  位置: sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts:103-116
  ↓
最终 system prompt = base + "\n\n" + 所有 rules 拼接
```

### 1.2 最终结构

```text
[Base Prompt]
- 身份定义（You are Cline...）
- 通用行为规则（gather context / use tools / parallelism / absolute paths）
- <env>（Platform / Date / IDE / CWD）
- MODE_TAG_INSTRUCTIONS
- PLAN_MODE_INSTRUCTIONS（仅 plan 模式）
- {{CLINE_METADATA}}（workspace metadata，JSON）

[Rules]
- # Rules
- ## rule_name_1
- content_1
- ## rule_name_2
- content_2
- ...
```

### 1.3 Rules 的来源

Cline 的 rules 统一通过 ContributionRegistry 注册：

1. `user-instruction-plugin` 注册 rules 条目：
   ```ts
   api.registerRule({
     id: "cline-user-instructions:rules",
     source: "user-instruction-watcher",
     content: () => loadRulesForSystemPromptFromWatcher(options.watcher),
   });
   ```
2. watcher 发现规则文件：
   - `AGENTS.md`
   - `.clinerules` / `.clinerules.md`
   - `.cline/rules.md`
   - `.cline/rules/*.md`
3. `formatRulesForSystemPrompt` 统一格式化为：
   ```text
   # Rules
   ## rule_name
   instructions
   ```

### 1.4 Skills 在 system prompt 中的处理

Cline **不在 system prompt 中注入技能摘要或 always skills**：
- 没有 always skills 自动注入机制
- 没有 skills_summary 表格
- skills 工具 description 动态追加 `Available skills: name1, name2`（通过工具 API 暴露）
- LLM 通过 tools 字段看到可用技能列表

位置：`sdk/packages/core/src/extensions/tools/definitions.ts:719-763`

---

## 二、Charles 现状

### 2.1 当前构造方式

[agent/context.py:160-243](file:///e:/jikeAI/code/CASE-AI量化系统/agent/context.py#L160-L243)

11 层显式拼接：

```text
1. <env> 段
2. identity 身份定义
3. AGENTS.md 引导文件
4. memory 记忆
5. always_skills 常驻技能指令
6. skills_summary 技能目录表格
7. tools_section 工具列表
8. mcp_section MCP 概览
9. rules 任务规则文件
10. extra_sections 额外段落
11. mode_tag_instructions
12. mode_prompt（plan 模式）
```

用 `\n\n---\n\n` 分隔。

### 2.2 当前 rules 格式化

[agent/rules_loader.py:686-714](file:///e:/jikeAI/code/CASE-AI量化系统/agent/rules_loader.py#L686-L714)

```python
parts.append(f"## 规则: {name}\n\n{body}")
return "\n\n".join(parts)
```

没有统一的 `# Rules` 标题。

### 2.3 当前 AGENTS.md 加载

[agent/context.py:544-578](file:///e:/jikeAI/code/CASE-AI量化系统/agent/context.py#L544-L578)

AGENTS.md 作为独立段加载，放在 identity 之后、skills 之前，与 rules 分开。

---

## 三、完整差异矩阵（phase_L + 新增）

| # | 维度 | Cline | Charles 现状 | 类型 | 处理方案 |
|---|------|-------|-------------|------|---------|
| L1 | 构造方式 | base prompt 模板 + 占位符替换 | 11 段显式列表拼接 | 必须对齐 | 创建 DEFAULT_CHARLES_SYSTEM_PROMPT 模板 |
| L2 | `<env>` 段 | Platform / Date / IDE / CWD | 工作目录 / 平台 / 日期 / IDE / Git 信息 | 必须对齐 | 改为 Cline 4 字段格式，Git 信息移入 metadata |
| L3 | 工具列表段 | 不在 system prompt 中列工具 | 有独立 tools_section | 合理增强保留 | 保留为 Charles 增强，但改为 rule 格式注入 |
| L4 | `<user_input mode>` | MODE_TAG_INSTRUCTIONS 在 base prompt rules 段 | mode_tag 在最后 | 必须对齐 | 合并入 effectiveRules |
| L5 | MCP 概览 | 无（MCP 工具作为普通 AgentTool 注册） | 有独立 mcp_section | 合理增强保留 | 保留为 Charles 增强，改为 rule 格式注入 |
| L6 | rules 段 | `# Rules\n## name\ncontent` 统一追加 | `## 规则: name\n\ncontent` 独立段 | 必须对齐 | 统一为 Cline 格式 |
| L7 | frontmatter 解析 | parseMarkdownFrontmatter | parse_yaml_frontmatter | 已对齐 | 无需修改 |
| L8 | rule 条件过滤 | 仅 paths（picomatch） | applyTo + mode + paths | 合理增强保留 | 保留，但规则输出格式对齐 |
| L9 | external-rules | 支持 .cursorrules/.windsurfrules | 无 | 可选 | 本次不做 |
| L10 | workflows | 支持 workflows 目录 | 无 | 可选 | 本次不做 |
| L11 | always skills 注入 | 无 | 自动注入 always=True 技能 | 合理增强保留 | 改为 rule 格式注入，明确标注已自动加载 |
| L12 | skills 概览 | 仅 skills 工具 description | 注入 skills_summary 表格 | 合理增强保留 | 改为 rule 格式注入，表格改列表 |
| L13 | plan mode 契约 | PLAN_MODE_INSTRUCTIONS 在 base prompt | mode_prompt 在最后 | 必须对齐 | 合并入 effectiveRules |
| L14 | AGENTS.md 角色 | 是 rules 之一 | 是独立引导文件 | 必须对齐 | 移入 rules 统一加载 |
| L15 | memory 段 | 无 | 有 # 记忆 段 | 合理增强保留 | 保留，位置可调整 |
| L16 | 工具描述截断 | 无 | 150 字符截断 | 合理增强保留 | 保留在 tools_section 中 |
| L17 | system prompt 顺序 | base → rules | env → identity → AGENTS → memory → skills → tools → mcp → rules → extra → mode | 必须对齐 | 改为 base + rules 两层 |
| L18 | metadata | workspaceMetadata JSON | 仅 git 信息 | 必须对齐 | 构建 Cline 格式的 metadata |
| 新增 1 | contribution registry | 有 ContributionRegistry + registerRule API | 无，rules_loader 直接返回字符串 | 架构差异 | 本次不引入 registry，但规则输出格式对齐 |
| 新增 2 | rules 发现位置 | `.cline/rules.md`、`.cline/rules/*.md`、AGENTS.md | `agent_config/rules/*.md` + AGENTS.md | 必须对齐 | AGENTS.md 移入 rules 目录扫描 |
| 新增 3 | rules 标题格式 | `# Rules\n## name\ncontent` | 无统一标题 | 必须对齐 | 统一加 `# Rules` 标题 |
| 新增 4 | base prompt 身份 | 固定在模板中 | 通过 identity 参数传入 | 必须对齐 | 写入 DEFAULT_CHARLES_SYSTEM_PROMPT |

### 类型说明

- **必须对齐**：直接重构为 Cline 方式
- **合理增强保留**：保留功能，但输出格式和位置对齐 Cline（作为 rule 注入或 base prompt 的一部分）
- **可选**：本次不做，后续按需实施

---

## 四、目标架构设计

### 4.1 重构后的 system prompt 结构

默认状态（与 Cline 完全对齐，无增强层）：

```text
[Base Prompt]  ← DEFAULT_CHARLES_SYSTEM_PROMPT 模板
- 身份定义（You are Charles，AI 投研情报官...）
- 通用行为规则
- <env>（Platform / Date / IDE / CWD）
- MODE_TAG_INSTRUCTIONS
- PLAN_MODE_INSTRUCTIONS（仅 plan 模式）
- {{CHARLES_METADATA}}（workspace metadata JSON）
- {{CHARLES_RULES}} 占位符

[Rules]  ← 运行时统一追加
# Rules

## AGENTS.md
{AGENTS.md body}

## general
{general.md body}

## plan-mode-rules
{plan-mode-rules.md body}
```

启用增强层后（通过配置开关），在 Rules 末尾追加：

```text
## charles-tools-overview
{tools_section 内容}

## charles-mcp-overview
{mcp_section 内容}

## charles-always-skills
{always_skills 内容}

## charles-skills-summary
{skills_summary 内容}

## charles-memory
{memory 内容}
```

### 4.1.1 增强层配置方式

新增配置文件 `agent_config/system_prompt.yaml`：

```yaml
# Charles System Prompt 增强层配置
# 默认全部 false，与 Cline 完全对齐
enhancements:
  enabled: false       # 总开关
  tools_section: true  # 在 system prompt 中列出工具名和描述
  skills_summary: true # 在 system prompt 中列出技能目录
  always_skills: true  # 在 system prompt 中注入 always=True 技能指令
  mcp_section: true    # 在 system prompt 中列出 MCP 服务器
  memory: true         # 在 system prompt 中注入记忆段
```

- `enabled: false` 时，所有增强层不注入，system prompt 与 Cline 结构完全一致
- `enabled: true` 时，根据各子开关决定是否注入对应增强层
- 未创建该文件时，默认等价于 `enabled: false`

SystemPromptBuilder 在初始化时读取此配置，按配置决定是否生成增强层 rule。

### 4.2 占位符替换逻辑

仿照 Cline `buildClineSystemPrompt`：

```python
base_prompt = DEFAULT_CHARLES_SYSTEM_PROMPT
base_prompt = base_prompt.replace("{{PLATFORM_NAME}}", platform)
base_prompt = base_prompt.replace("{{CURRENT_DATE}}", date)
base_prompt = base_prompt.replace("{{IDE_NAME}}", ide_name)
base_prompt = base_prompt.replace("{{CWD}}", working_dir)
base_prompt = base_prompt.replace("{{CHARLES_METADATA}}", metadata_json)
base_prompt = base_prompt.replace("{{CHARLES_RULES}}", rules_content)
```

### 4.3 Rules 统一格式化

```python
def format_rules_content(results: list[RuleLoadResult]) -> str:
    parts = []
    for r in results:
        if not r.activated:
            continue
        body = r.body.strip()
        if not body:
            continue
        name = r.path.stem
        parts.append(f"## {name}\n{body}")
    if not parts:
        return ""
    return "# Rules\n\n" + "\n\n".join(parts)
```

---

## 五、具体修改清单

### 5.1 新增/修改文件

| 文件 | 修改内容 | 类型 |
|------|---------|------|
| `agent/prompts/charles_system_prompt.py` | 新增 DEFAULT_CHARLES_SYSTEM_PROMPT 模板 | 新增 |
| `agent/context.py` | 重写 SystemPromptBuilder.build() 为 base + rules 两层；读取增强层配置 | 重构 |
| `agent/rules_loader.py` | format_rules_content 统一加 `# Rules` 标题，AGENTS.md 纳入扫描 | 修改 |
| `agent_config/AGENTS.md` | 移动到 `agent_config/rules/AGENTS.md` 或作为 rules 目录扫描的一部分 | 移动/修改 |
| `agent_config/system_prompt.yaml` | 新增增强层配置开关（默认 enabled: false） | 新增 |
| `agent/skills/registry.py` | build_summary 改为列表形式（非表格），新增生成 rule 格式的方法 | 修改 |
| `agent/skills/skill_tool.py` | 确认 description 动态追加 Available skills 逻辑不变 | 无需修改 |

### 5.2 不修改的文件

| 文件 | 原因 |
|------|------|
| `agent/tools/run_commands.py` | 与 system prompt 结构无关 |
| `agent/tools/plan_mode.py` | PLAN_MODE_PROMPT 内容可复用，但注入位置改变 |
| `agent/skills/loader.py` | SkillMetadata 结构无需改变 |
| `agent_config/skills/*/SKILL.md` | 已完成优化，无需修改 |

### 5.3 AGENTS.md 处理方式

两种选择：

**选择 A（推荐）**：将 `agent_config/AGENTS.md` 移动到 `agent_config/rules/AGENTS.md`
- 优点：rules_loader 自动扫描，完全对齐 Cline
- 缺点：文件位置变化

**选择 B**：保留 `agent_config/AGENTS.md` 原位，但 `_load_agents_file` 返回的结果合并到 rules 中
- 优点：路径不变
- 缺点：逻辑上仍区分 AGENTS.md 和 rules

建议 **选择 A**。

---

## 六、执行顺序

```
Step 1: 创建 agent/prompts/charles_system_prompt.py
        - DEFAULT_CHARLES_SYSTEM_PROMPT 模板
        - 包含身份、通用规则、env 占位符、mode tag、plan mode、metadata 占位符

Step 2: 修改 agent/rules_loader.py
        - format_rules_content 输出统一加 # Rules 标题
        - AGENTS.md 纳入 rules 目录扫描（或兼容现有 agents_path）

Step 3: 移动/重命名 AGENTS.md
        - 从 agent_config/AGENTS.md 移动到 agent_config/rules/AGENTS.md
        - 调整 frontmatter 为 Cline 风格（alwaysApply: true / globs: "*"）

Step 4: 重写 agent/context.py SystemPromptBuilder
        - 移除 11 层拼接
        - 改为 base + rules 两层
        - always_skills / skills_summary / tools_section / mcp_section / memory 作为 rule 注入

Step 5: 修改 agent/skills/registry.py
        - build_summary 改为列表形式
        - 新增生成 rule 格式内容的方法

Step 6: 运行导入测试和 system prompt 构造测试

Step 7: 端到端验证
        - 验证 LLM 仍能通过 skills 工具正确调用技能
        - 验证 Plan 模式行为正常
        - 验证 rules 按条件过滤正常
```

---

## 七、风险评估

### 7.1 主要风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 移除 always_skills 独立层导致 Qwen 模型不读技能指令 | 高 | 改为 rule 格式保留，明确标注"已自动加载" |
| skills_summary 从表格改列表后不够醒目 | 中 | 列表形式配合"何时使用"说明，保持信息完整 |
| tools_section 从独立段改 rule 后 LLM 忽略 | 中 | 保留 tools_section，但位置调整到 rules 中靠前 |
| AGENTS.md 移动后 rules_loader 加载逻辑出错 | 中 | 充分测试路径解析和 frontmatter 剥离 |
| base prompt 模板中通用规则丢失 | 低 | 完整迁移现有 tools_section 中的通用规则 |

### 7.2 回滚策略

- 在重构期间保留原 `SystemPromptBuilder` 为 `LegacySystemPromptBuilder`
- 测试通过后再删除 legacy 代码
- 若发现 LLM 行为明显退化，可快速切换回 legacy

---

## 八、验证方法

### 8.1 单元测试

1. 导入测试：`python -c "from agent.context import SystemPromptBuilder; print('OK')"`
2. system prompt 构造测试：检查输出包含：
   - `You are Charles`
   - `<env>` 段
   - `# Rules` 标题
   - `## AGENTS` 或 `## AGENTS.md`
   - `MODE_TAG_INSTRUCTIONS`

### 8.2 端到端测试

1. 输入"获取 600519.SH 的 K 线" → 应调用 `skills(skill="stock-price")`
2. 输入"读取 README.md" → 应直接调用 `read_files`
3. 切换到 Plan 模式 → system prompt 中应包含 plan mode 契约
4. 输入"分析贵州茅台氢能业务" → 应按 read-pdf Workflow 执行

### 8.3 输出格式检查

```python
system_prompt = builder.build()
assert "# Rules" in system_prompt
assert "## " in system_prompt
assert "<env>" in system_prompt
assert "MODE_TAG_INSTRUCTIONS" not in system_prompt or "Plan / Act Modes" in system_prompt
```

---

## 九、与历史计划的关系

- 本计划基于 [AGENT_PROMPT_FIX_PLAN.md](file:///e:/jikeAI/code/CASE-AI量化系统/AGENT_PROMPT_FIX_PLAN.md) 中已完成的 P1-P5
- 本计划基于 [CLINE_DIFF/phase_L_system_prompt.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/phase_L_system_prompt.md) 的 18 项对比
- 本计划将之前"逐项补齐字段"的方式升级为"重构底层构造架构"
- 本计划不推翻 SKILL.md 优化成果，但会调整其在 system prompt 中的注入方式

---

**下一步：用户确认本计划后，按 Step 1-7 执行。**
