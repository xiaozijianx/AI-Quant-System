# Phase 5.12 Memory 段对比

> 对比范围：Cline 与 Charles 的 System Prompt 中 "Memory 段" 是否存在、内容来源、注入方式；区分注释残留与实现逻辑残留；nanobot 风格残留专项检查。
>
> 本阶段聚焦 Cline 的 "Memory 段"（持久化记忆注入）在 Charles 中的对应实现，深入到 memory 参数来源、文件加载链路、enhancement 注入机制级别，区分"memory 参数形态"与"MEMORY.md 文件加载逻辑"两个层次。
>
> Cline 源码：
> - `sdk/packages/shared/src/prompt/cline.ts` L110-166（buildClineSystemPrompt 纯组装器，无 memory 占位符）
> - `sdk/packages/shared/src/prompt/system.ts` L1-68（base prompt 模板，无 memory 段）
> - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts` L103-116 / L680-689（composeSystemPrompt 编排器，无 memory 合并逻辑）
>
> Charles 源码：
> - `agent/context.py` L78-127（build_charles_system_prompt 纯组装器，无 memory 占位符）+ L214-300（SystemPromptBuilder 编排器，memory 参数 L252/L289）+ L611-647（_build_enhancement_rules，charles-memory 段 L644-645）+ L304-346（_load_enhancements，memory 开关）
> - `agent/server.py` L541-548（SystemPromptBuilder 实例化，未传入 memory 参数）
> - `agent_config/system_prompt.yaml` L1-10（enhancements.enabled=false，memory=true）
>
> nanobot 溯源：
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/memory.py` L75-130（MemoryStore 类，管理 memory/MEMORY.md + memory/HISTORY.md）
> - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py` L29 / L48-50（self.memory = MemoryStore(workspace) + 注入 "# Memory" 段）
> - `third_party/charles_bundle/charles-nanobot/agent.py` L56-71（_inject_time_context 写入 memory/MEMORY.md）

---

## 一、执行摘要

本阶段对比 Cline 与 Charles 的 System Prompt 中 "Memory 段" 的存在性、内容来源、注入方式。**核心结论：Cline system prompt 中无独立 Memory 段，也无 MEMORY.md 文件加载机制；Charles 通过 enhancement 机制保留了 `charles-memory` 段的注入形态，但已剥离 nanobot 的 MemoryStore 文件加载逻辑，仅保留 `self.memory` 参数（无调用方传入，无文件读取），属于"形态保留、逻辑缺失"的 nanobot 风格残留。计划文件 L2022-2035 标注"Cline 有 memory/MEMORY.md"是错误的，该机制属于 nanobot，Cline 从未实现。**

### 核心结论

1. **存在性差异**：
   - **Cline**：**不存在** Memory 段。Cline system prompt 文本中无独立 memory 段，无 `{{CLINE_MEMORY}}` 占位符，无 MEMORY.md 文件加载机制。memory 相关内容（若有）只能通过 rules 或 extension contributions 注入。
   - **Charles**：**存在** enhancement `charles-memory` 段（context.py L644-645），但默认关闭（`enhancements.enabled=false`）。注入条件为 `enhancements.enabled=true` 且 `memory=true` 且 `self.memory` 非空。

2. **内容来源差异**：
   - **Cline**：无 memory 内容来源（无此段）。
   - **Charles**：memory 内容来源为 `SystemPromptBuilder.__init__(memory="")` 参数（context.py L252 / L289），但 **server.py L541-548 的实际调用中未传入 memory 参数**，因此 `self.memory=""` 默认空。Charles **无从磁盘加载 MEMORY.md 的逻辑**（无 `load_memory` / `read_memory` 函数，`agent_config/memory/` 目录不存在）。

3. **注入方式差异**：
   - **Cline**：无注入（无此段）。
   - **Charles**：通过 `_build_enhancement_rules()`（context.py L644-645）将 `self.memory` 文本包装为 `charles-memory` rule，经 `format_rules_content()` 统一添加 `## charles-memory` 标题后注入到 `{{CHARLES_RULES}}` 占位符内，位于 rules 段末尾（tools-overview → mcp-overview → always-skills → skills-summary → **memory**）。

4. **段落位置勘误**：计划表 L2034 标注 "段落位置 第 10 段 / 第 9 段，顺序偏移"，但实际：
   - Cline 无 Memory 段，不存在"第 10 段"。
   - Charles 的 charles-memory 段在 `{{CHARLES_RULES}}` 占位符内（rules 段尾部），是 rules 内部的第 5 个 enhancement 子段，非顶层第 9 段。

5. **nanobot 残留**：Memory 段对比层面 **0 处注释残留**（memory 参数 docstring 未直接提到 nanobot），**2 处实现逻辑残留**：
   - `self.memory` 参数（context.py L252 / L289）：保留 nanobot 的 memory 参数形态，但无文件加载逻辑。
   - `charles-memory` enhancement 段（context.py L644-645）：保留 nanobot 的 memory 注入形态，但无内容来源（`self.memory=""` 时不注入）。
   这两处是 nanobot MemoryStore 机制的**形态残留**，nanobot 原生有完整的 `MemoryStore` 类（`memory.py` L75-130）管理 `memory/MEMORY.md` 文件，Charles 仅保留了参数和注入点，剥离了文件加载和 LLM 整合逻辑。

### 一致性总体评估

- **Memory 段存在性**：**未对齐**（Cline 无，Charles 有 enhancement 段但默认关闭）
- **MEMORY.md 文件加载**：**未对齐**（Cline 无此机制，Charles 也无此机制；nanobot 有但 Charles 未继承）
- **memory 参数来源**：**未对齐**（Cline 无 memory 参数，Charles 有但无调用方传入）
- **注入位置**：**未对齐**（Cline 无注入，Charles 通过 `{{CHARLES_RULES}}` 注入 rules 内部末尾）
- **加载时机**：**未对齐**（Cline 无加载，Charles 无加载；计划表标注"启动时"错误）
- **无 Memory 时行为**：**部分对齐**（Cline 不注入，Charles 在 `self.memory=""` 时不注入）
- **nanobot 残留**：0 处注释残留，2 处实现逻辑残留（形态保留、逻辑缺失）

---

## 二、逐项对比表

| # | 对比项 | Cline 实现 | Charles 实现 | 一致性等级 | 说明 |
|---|--------|-----------|-------------|-----------|------|
| 5.12.1 | Memory 段存在性 | **不存在**。system prompt 文本中无独立 memory 段，无 `{{CLINE_MEMORY}}` 占位符，无 memory 合并逻辑 | **存在**（默认关闭）。enhancement `charles-memory` 段（context.py L644-645），注入条件 `enhancements.enabled=true` 且 `memory=true` 且 `self.memory` 非空 | 未对齐 | 计划表 L2031 标注"是/是/已对齐"错误；Cline 无此段，Charles 有但默认关闭 |
| 5.12.2 | Memory 文件加载 | **无** MEMORY.md 加载机制。Cline 从未实现 memory 文件加载 | **无** MEMORY.md 加载机制。Charles 无 `load_memory` / `read_memory` 函数，`agent_config/memory/` 目录不存在（Glob 无结果） | 对齐（均无） | 计划表 L2032 标注"memory/MEMORY.md / agent_config/memory/MEMORY.md / 路径不同"错误；这是 nanobot 的路径，Cline 和 Charles 均无此文件加载机制 |
| 5.12.3 | 加载时机 | **无**（无加载逻辑） | **无**（无加载逻辑）。`self.memory` 参数在 `__init__()` 时静态传入，但 server.py L541-548 未传入，因此始终为空字符串 | 对齐（均无） | 计划表 L2033 标注"启动时/启动时/已对齐"错误；两者均无启动时加载 MEMORY.md 的逻辑 |
| 5.12.4 | 段落位置 | **无此段** | `{{CHARLES_RULES}}` 占位符内，effectiveRules 末尾。顺序：tools-overview → mcp-overview → always-skills → skills-summary → **memory**（context.py L620-646） | 未对齐 | 计划表 L2034 标注"第 10 段/第 9 段/顺序偏移"错误；Cline 无此段，Charles 在 rules 段尾部 |
| 5.12.5 | 无 Memory 时行为 | **不注入**（无此段） | **不注入**。`_build_enhancement_rules()` L644 条件 `if self._enhancements.get("memory") and self.memory:` 不满足时跳过 | 部分对齐 | 计划表 L2035 标注"不注入/不注入/已对齐"部分正确；两者均不注入，但原因不同（Cline 无此段，Charles 条件不满足） |
| 5.12.6 | memory 参数来源 | **无** memory 参数 | `SystemPromptBuilder.__init__(memory="")`（context.py L252 / L289），默认空字符串。server.py L541-548 实际调用未传入 | 未对齐 | Charles 保留参数形态但无内容来源；nanobot 原生通过 `MemoryStore.get_memory_context()` 动态读取 MEMORY.md |
| 5.12.7 | enhancement 开关 | **无** enhancement 机制 | `system_prompt.yaml` L5 `enhancements.enabled: false`（总开关关闭），L10 `memory: true`（子开关，总开关关闭时强制 false） | 未对齐 | Charles 有 enhancement 开关但默认关闭；Cline 无 enhancement 机制 |
| 5.12.8 | MemoryStore 类 | **无** | **无**。Charles 无 `MemoryStore` 等价类，无 `read_long_term()` / `write_long_term()` / `consolidate()` 方法 | 对齐（均无） | nanobot 有完整 MemoryStore（memory.py L75-130），Charles 未继承 |
| 5.12.9 | LLM 整合记忆 | **无** | **无**。Charles 无 `consolidate()` 等价方法，无将对话整合到 MEMORY.md 的 LLM 调用 | 对齐（均无） | nanobot 有 `MemoryStore.consolidate()`（memory.py L114-130）用 LLM 整合对话，Charles 未继承 |
| 5.12.10 | 时间上下文注入 | **无** | **无**。Charles 无 `_inject_time_context()` 等价函数 | 对齐（均无） | nanobot 的 charles-nanobot/agent.py L56-71 有 `_inject_time_context()` 写入 memory/MEMORY.md，Charles 未继承 |

---

## 三、重点差距详细说明

### 3.1 Cline 的 Memory 段缺失（5.12.1 / 5.12.2 / 5.12.3）

Cline 的 system prompt 组装链路中**完全不存在 Memory 段**：

**纯组装器**：`buildClineSystemPrompt()`（cline.ts L110-166）仅替换 `{{PLATFORM_NAME}}` / `{{CURRENT_DATE}}` / `{{IDE_NAME}}` / `{{CWD}}` / `{{CLINE_RULES}}` / `{{CLINE_METADATA}}` 占位符，无 `{{CLINE_MEMORY}}` 占位符。

**编排器**：`composeSystemPrompt()`（orchestrator.ts L680-689）仅遍历 `contributionRegistry.getRegisteredRules()` 并通过 `mergeSystemPromptRules()` 追加到 base 末尾，无 memory 专项合并逻辑。

**base 模板**：`DEFAULT_CLINE_SYSTEM_PROMPT`（system.ts L1-68）中无 `# Memory` 段落，无 memory 占位符。

**关键澄清**：Cline 的 memory 相关功能（若有）通过以下间接途径实现：
- **对话历史压缩**：`compaction.ts` 将旧对话压缩为摘要消息（非 system prompt 段），Charles 的 `ContextCompactor` 已对齐此机制（见 P2.x 阶段）。
- **checkpoint**：Cline 通过 checkpoint 机制持久化会话状态，非 system prompt 段。
- **extension contributions**：第三方扩展可通过 `api.registerRule()` 注册含 memory 内容的 rule，但 Cline 官方未提供此扩展。

**计划表 L2022 标注错误**：计划表标注 "Cline 实现：memory/MEMORY.md 内容 + 持久化记忆"，实际 Cline 从未实现 MEMORY.md 加载机制。该机制是 **nanobot** 的设计（见 3.3 节），被误标为 Cline 实现。

### 3.2 Charles 的 enhancement memory 段（5.12.1 / 5.12.6 / 5.12.7）

Charles 通过 enhancement 机制保留了 memory 段的注入形态，但已剥离文件加载逻辑：

**注入点**：`_build_enhancement_rules()`（context.py L611-647）
```python
def _build_enhancement_rules(self) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    # ... tools_section / mcp_section / always_skills / skills_summary ...
    if self._enhancements.get("memory") and self.memory:
        rules.append(("charles-memory", self.memory))
    return rules
```

**参数来源**：`SystemPromptBuilder.__init__(memory="")`（context.py L252 / L289）
```python
def __init__(
    self, identity="", agents_path=None, memory="", skills_registry=None,
    rules_dir=None, extra_sections=None, session_id=None, tools=None,
    working_dir=None, business_modes=None, rule_paths=None,
    rule_toggles=None, ide_name="Charles Web", config_path=None,
) -> None:
    # ...
    self.memory = memory
```

**实际调用**：`server.py` L541-548
```python
builder = SystemPromptBuilder(
    agents_path=agents_path if agents_path.exists() else None,
    skills_registry=registry,
    session_id=session_id,
    tools=tools,
    working_dir=str(project_root),
    rules_dir=rules_dir if rules_dir.exists() else None,
)
# 注意：未传入 memory 参数，因此 self.memory="" 默认空
```

**配置开关**：`agent_config/system_prompt.yaml`
```yaml
enhancements:
  enabled: false       # 总开关；false 时所有子开关强制关闭
  tools_section: true
  skills_summary: true
  always_skills: true
  mcp_section: true
  memory: true         # 子开关，总开关关闭时强制 false
```

**关键差距**：
- Charles 的 `self.memory` 参数**无内容来源**：server.py 未传入 memory 参数，无文件加载逻辑，无 LLM 整合逻辑，因此 `self.memory=""` 始终为空。
- 即使 `enhancements.enabled=true` 且 `memory=true`，由于 `self.memory=""`，`_build_enhancement_rules()` L644 的 `and self.memory` 条件不满足，`charles-memory` 段不会被注入。
- `agent_config/memory/` 目录**不存在**（Glob 无结果），Charles 无从该路径加载 MEMORY.md 文件。

### 3.3 nanobot 的 MemoryStore 机制（溯源）

nanobot 有完整的 MemoryStore 机制，Charles 仅保留了形态残留：

**MemoryStore 类**：`third_party/charles_bundle/nanobot-main/nanobot/agent/memory.py` L75-130
```python
class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    async def consolidate(self, messages, provider, model) -> bool:
        """Consolidate the provided message chunk into MEMORY.md + HISTORY.md."""
        # 用 LLM 整合对话到 MEMORY.md
        ...
```

**注入点**：`nanobot/agent/context.py` L29 / L48-50
```python
class ContextBuilder:
    def __init__(self, workspace: Path, timezone: str | None = None):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)  # L29

    def build_system_prompt(self, ...):
        parts = [self._get_identity()]
        # ...
        memory = self.memory.get_memory_context()  # L48
        if memory:
            parts.append(f"# Memory\n\n{memory}")  # L50
        # ...
```

**时间上下文注入**：`charles-nanobot/agent.py` L56-71
```python
def _inject_time_context():
    """将当前日期写入 memory/MEMORY.md"""
    memory_file = WORKSPACE / "memory" / "MEMORY.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    # 写入当前日期时间上下文
    memory_file.write_text(...)
```

**Charles 与 nanobot 的关系**：

| 维度 | nanobot | Charles |
|------|---------|---------|
| MemoryStore 类 | 有（memory.py L75-130） | **无** |
| memory/MEMORY.md 文件加载 | 有（`read_long_term()`） | **无** |
| memory/HISTORY.md 日志 | 有（`append_history()`） | **无** |
| LLM 整合记忆 | 有（`consolidate()`） | **无** |
| 时间上下文注入 | 有（`_inject_time_context()`） | **无** |
| memory 参数 | 无（通过 MemoryStore 动态读取） | 有（`self.memory=""`，静态传入） |
| 注入点 | `# Memory` 段（parts.append） | `charles-memory` enhancement rule |
| 注入条件 | `memory` 非空时注入 | `enhancements.enabled=true` 且 `memory=true` 且 `self.memory` 非空 |

**关键结论**：Charles 的 `self.memory` 参数和 `charles-memory` enhancement 段是 nanobot MemoryStore 机制的**形态残留**：
- 保留了"将 memory 文本作为 rule 注入"的形态
- 剥离了 MemoryStore 类、文件加载、LLM 整合、时间注入等全部实质逻辑
- 导致 `self.memory=""` 始终为空，`charles-memory` 段永远不会被注入

### 3.4 计划表标注勘误（5.12.1 / 5.12.2 / 5.12.3 / 5.12.4）

计划表 L2022-2035 的标注存在系统性错误，将 nanobot 的 MemoryStore 机制误标为 Cline 实现：

| 计划表行号 | 标注内容 | 实际情况 | 错误性质 |
|-----------|---------|---------|---------|
| L2022 | Cline 实现：`memory/MEMORY.md` 内容 + 持久化记忆 | Cline 无 MEMORY.md 加载机制；这是 nanobot 的机制 | 误标归属 |
| L2026 | Charles 实现：`agent_config/memory/MEMORY.md` 内容 + 持久化记忆 | Charles 无从 `agent_config/memory/MEMORY.md` 加载的逻辑；`agent_config/memory/` 目录不存在 | 误标路径 |
| L2031 | Memory 段：是 / 是 / 已对齐 | Cline 无此段，Charles 有 enhancement 段但默认关闭 | 误标存在性 |
| L2032 | Memory 文件：`memory/MEMORY.md` / `agent_config/memory/MEMORY.md` / 路径不同 | Cline 无此文件，Charles 无此文件加载逻辑；`memory/MEMORY.md` 是 nanobot 路径 | 误标归属 |
| L2033 | 加载时机：启动时 / 启动时 / 已对齐 | 两者均无启动时加载 MEMORY.md 的逻辑 | 误标行为 |
| L2034 | 段落位置：第 10 段 / 第 9 段 / 顺序偏移 | Cline 无此段；Charles 在 rules 段尾部（非顶层第 9 段） | 误标位置 |
| L2035 | 无 Memory 时行为：不注入 / 不注入 / 已对齐 | 部分正确：两者均不注入，但原因不同（Cline 无此段，Charles 条件不满足） | 部分正确 |

**勘误建议**：
- L2022 应改为：Cline 无 MEMORY.md 加载机制（nanobot 有）
- L2026 应改为：Charles 有 `charles-memory` enhancement 段但无文件加载逻辑（形态残留）
- L2031 应改为：Memory 段：否 / 是（默认关闭）/ 未对齐
- L2032 应改为：Memory 文件：无 / 无（`agent_config/memory/` 目录不存在）/ 对齐（均无）
- L2033 应改为：加载时机：无 / 无 / 对齐（均无）
- L2034 应改为：段落位置：无 / rules 段尾部 / 未对齐
- L2035 保留：不注入 / 不注入 / 部分对齐

---

## 四、nanobot 残留专项检查

### 4.1 注释残留（0 处）

**Memory 段对比层面的注释残留：无**。

逐项验证：
- `agent/context.py` L252（`memory: str = ""` 参数签名）：无 nanobot 注释，仅标注"记忆上下文文本"。
- `agent/context.py` L272（`memory` 参数 docstring）：仅标注"记忆上下文文本"，未提到 nanobot。
- `agent/context.py` L289（`self.memory = memory` 初始化）：无注释。
- `agent/context.py` L314（`_load_enhancements` docstring 中 `memory: true`）：仅标注"记忆段"，未提到 nanobot。
- `agent/context.py` L644-645（`charles-memory` rule 注入）：无注释。
- `agent_config/system_prompt.yaml` L10（`memory: true`）：仅标注"在 system prompt 中注入记忆段"，未提到 nanobot。

**关联说明**：`extra_sections` 参数的 nanobot 注释残留（context.py L275）已在 P5.11 报告 4.1 节记录，本阶段不重复。

### 4.2 实现逻辑残留（2 处，1 个文件）

| 文件 | 行号 | 残留内容 | 性质 | 溯源 |
|------|------|---------|------|------|
| `agent/context.py` | L252 / L289 | `memory: str = ""` 参数 + `self.memory = memory` 初始化 | dead code 形态残留 | nanobot `MemoryStore.get_memory_context()` 动态读取 MEMORY.md，Charles 改为静态参数传入但无调用方传入 |
| `agent/context.py` | L644-645 | `if self._enhancements.get("memory") and self.memory: rules.append(("charles-memory", self.memory))` | dead code 形态残留 | nanobot `context.py` L48-50 `parts.append(f"# Memory\n\n{memory}")`，Charles 改为 enhancement rule 但无内容来源 |

**实现逻辑残留说明**：

**残留 1：`self.memory` 参数（L252 / L289）**
- nanobot 原生通过 `MemoryStore(workspace)` 动态管理 memory，`get_memory_context()` 实时读取 `memory/MEMORY.md` 文件内容。
- Charles 将动态读取改为静态参数传入（`memory: str = ""`），但：
  - server.py L541-548 的实际调用**未传入 memory 参数**，因此 `self.memory=""` 始终为空。
  - 无 `load_memory()` / `read_memory()` 等文件加载函数。
  - 无 `MemoryStore` 等价类。
- 这是 nanobot memory 机制的**形态残留**：保留了参数签名，剥离了文件加载逻辑。

**残留 2：`charles-memory` enhancement 段（L644-645）**
- nanobot 原生通过 `parts.append(f"# Memory\n\n{memory}")` 直接追加 `# Memory` 段到 system prompt。
- Charles 改为通过 enhancement 机制注入（`rules.append(("charles-memory", self.memory))`），但：
  - 注入条件 `if self._enhancements.get("memory") and self.memory:` 需要两个条件同时满足。
  - `enhancements.enabled=false`（默认关闭）导致 `self._enhancements.get("memory")` 为 False。
  - 即使开启总开关，`self.memory=""` 导致 `and self.memory` 条件不满足。
  - 因此 `charles-memory` 段**永远不会被注入**。
- 这是 nanobot memory 注入点的**形态残留**：保留了注入逻辑骨架，剥离了内容来源。

**dead code 性质确认**：
- 通过 Grep 验证 `memory=` 在 Charles 源码中的调用：仅 `context.py` L252（参数定义）和 L289（初始化），**无外部调用方传入 memory 参数**。
- server.py L541-548 构造 `SystemPromptBuilder` 时未传入 `memory=...`，因此 `self.memory` 始终为默认空字符串。
- 这两处残留属于 **dead code**：代码存在但永远不会产生实际效果。

### 4.3 nanobot 残留总结

| 类别 | 数量 | 严重性 | 建议 |
|------|------|--------|------|
| 注释残留（docstring 提到 nanobot） | 0 处 | 无 | 无需处理 |
| 实现逻辑残留（memory 段层面） | 2 处（context.py L252/L289 + L644-645） | 低（dead code） | 可保留作为 enhancement 扩展点，或统一清理 |

### 4.4 注释残留 vs 实现逻辑残留的区分

本阶段严格区分两类残留：

**注释残留**（0 处）：Memory 段对比层面无 nanobot 注释残留。`memory` 参数和 `charles-memory` 段的 docstring 均未直接提到 nanobot。

**实现逻辑残留**（2 处）：
- `self.memory` 参数（L252 / L289）：保留 nanobot 的参数形态，但无文件加载逻辑，无调用方传入，属于 dead code。
- `charles-memory` enhancement 段（L644-645）：保留 nanobot 的注入形态，但因 `self.memory=""` 永远不注入，属于 dead code。

**与 P5.11 的区分**：P5.11 发现的 `extra_sections` nanobot 注释残留是 docstring 层面的历史溯源说明；本阶段发现的 memory 残留是实现逻辑层面的形态保留（参数 + 注入点），两者性质不同。

---

## 五、Memory 机制完整性矩阵

### 5.1 Cline Memory 机制清单

| 机制编号 | 机制名称 | 存在性 | 位置 | 说明 |
|---------|---------|--------|------|------|
| MEM-C-1 | Memory 段 | **不存在** | — | Cline system prompt 无独立 memory 段 |
| MEM-C-2 | MEMORY.md 文件加载 | **不存在** | — | Cline 无此文件加载机制 |
| MEM-C-3 | memory 参数 | **不存在** | — | Cline 无 memory 参数 |
| MEM-C-4 | MemoryStore 类 | **不存在** | — | Cline 无等价类 |
| MEM-C-5 | LLM 整合记忆 | **不存在** | — | Cline 无 consolidate 等价方法（有 compaction 但属于对话压缩，非持久化记忆） |
| MEM-C-6 | 时间上下文注入 | **不存在** | — | Cline 无 _inject_time_context 等价函数 |

### 5.2 Charles Memory 机制清单

| 机制编号 | 机制名称 | 存在性 | 位置 | 说明 |
|---------|---------|--------|------|------|
| MEM-S-1 | Memory 段（enhancement） | 存在（默认关闭，dead code） | context.py L644-645 | `charles-memory` rule，注入条件 `enhancements.enabled=true` 且 `memory=true` 且 `self.memory` 非空 |
| MEM-S-2 | MEMORY.md 文件加载 | **不存在** | — | 无 `load_memory` / `read_memory` 函数，`agent_config/memory/` 目录不存在 |
| MEM-S-3 | memory 参数 | 存在（dead code） | context.py L252 / L289 | `memory: str = ""`，默认空字符串，无调用方传入 |
| MEM-S-4 | MemoryStore 类 | **不存在** | — | 无等价类 |
| MEM-S-5 | LLM 整合记忆 | **不存在** | — | 无 consolidate 等价方法 |
| MEM-S-6 | 时间上下文注入 | **不存在** | — | 无 _inject_time_context 等价函数 |
| MEM-S-7 | enhancement 开关 | 存在 | system_prompt.yaml L5 / L10 | `enhancements.enabled: false`（总开关）+ `memory: true`（子开关），总开关关闭时强制 false |

### 5.3 nanobot Memory 机制清单（溯源参考）

| 机制编号 | 机制名称 | 存在性 | 位置 | 说明 |
|---------|---------|--------|------|------|
| MEM-N-1 | Memory 段 | 存在 | nanobot/agent/context.py L48-50 | `parts.append(f"# Memory\n\n{memory}")` |
| MEM-N-2 | MEMORY.md 文件加载 | 存在 | nanobot/agent/memory.py L86-89 | `read_long_term()` 读取 `memory/MEMORY.md` |
| MEM-N-3 | memory 参数 | **不存在** | — | nanobot 通过 MemoryStore 动态读取，无静态参数 |
| MEM-N-4 | MemoryStore 类 | 存在 | nanobot/agent/memory.py L75-130 | 完整的 MemoryStore 类，管理 MEMORY.md + HISTORY.md |
| MEM-N-5 | LLM 整合记忆 | 存在 | nanobot/agent/memory.py L114-130 | `consolidate()` 用 LLM 整合对话到 MEMORY.md |
| MEM-N-6 | 时间上下文注入 | 存在 | charles-nanobot/agent.py L56-71 | `_inject_time_context()` 写入 memory/MEMORY.md |

### 5.4 机制存在性对比矩阵

| 机制类型 | Cline | Charles | nanobot | 差异 |
|---------|-------|---------|---------|------|
| Memory 段 | **无** | 有（dead code） | 有 | Charles 保留形态但无内容来源；nanobot 有完整实现 |
| MEMORY.md 文件加载 | **无** | **无** | 有 | Cline 和 Charles 均无；nanobot 有 |
| memory 参数 | **无** | 有（dead code） | 无（用 MemoryStore） | Charles 独有，nanobot 用动态读取替代 |
| MemoryStore 类 | **无** | **无** | 有 | 仅 nanobot 有完整类 |
| LLM 整合记忆 | **无** | **无** | 有 | 仅 nanobot 有 consolidate |
| 时间上下文注入 | **无** | **无** | 有 | 仅 nanobot 有 _inject_time_context |
| enhancement 开关 | **无** | 有 | 无 | Charles 独有，用于控制 enhancement 段 |

---

## 六、修复建议

### 6.1 高优先级（P1）

#### P1-1: 勘误计划表的 Memory 段标注（3.4）

**问题**：计划表 L2022-2035 将 nanobot 的 MemoryStore 机制误标为 Cline 实现，导致对比基准错误。

**影响范围**：`AGENT_COMPARISON_PLAN_V2.md` L2022-2035（P5.12 节全部对比项）

**修复方案**：
- L2022 改为：`Cline 实现：无 MEMORY.md 加载机制（nanobot 有此机制）`
- L2026 改为：`Charles 实现：charles-memory enhancement 段（默认关闭，无文件加载逻辑）`
- L2031 改为：`Memory 段 | 否 | 是（默认关闭） | 未对齐`
- L2032 改为：`Memory 文件 | 无 | 无（agent_config/memory/ 目录不存在） | 对齐（均无）`
- L2033 改为：`加载时机 | 无 | 无（self.memory="" 始终为空） | 对齐（均无）`
- L2034 改为：`段落位置 | 无此段 | rules 段尾部 | 未对齐`
- L2035 保留：`无 Memory 时行为 | 不注入 | 不注入 | 部分对齐`

**理由**：计划表是后续修复的基准，标注错误会导致修复方向偏差。本项与 P5.11 阶段 P2-2 勘误建议一致，统一处理。

### 6.2 中优先级（P2）

#### P2-1: 评估 memory 参数和 charles-memory 段的保留必要性（4.2）

**问题**：Charles 的 `self.memory` 参数（L252 / L289）和 `charles-memory` enhancement 段（L644-645）属于 dead code，永远不会产生实际效果。

**影响范围**：
- `agent/context.py` L252（参数签名）+ L289（初始化）+ L644-645（注入逻辑）
- `agent_config/system_prompt.yaml` L10（memory: true 子开关）

**修复方案**：
- **保留方案**（推荐）：若未来计划补建 MEMORY.md 文件加载机制（对齐 nanobot 的 MemoryStore），可保留 `self.memory` 参数和 `charles-memory` 段作为扩展点。在 docstring 中明确标注"当前 memory 参数无调用方传入，charles-memory 段永远不会被注入；保留作为未来 MEMORY.md 加载机制的扩展点"。
- **清理方案**：若确认不补建 MEMORY.md 加载机制，可移除 `memory` 参数、`charles-memory` 注入逻辑、`system_prompt.yaml` 的 `memory` 子开关。

**建议**：保留方案更务实（Charles 的 enhancement 机制设计为可扩展，memory 段作为扩展点保留符合架构设计），但应在 docstring 中明确标注当前为 dead code。

#### P2-2: 若保留 memory 参数，补充文件加载逻辑（4.2）

**问题**：若 P2-1 选择保留方案，应补建 MEMORY.md 文件加载逻辑，使 `charles-memory` 段能实际生效。

**影响范围**：
- `agent/context.py` L289（`self.memory = memory` 初始化处）
- 新增 `agent_config/memory/MEMORY.md` 文件

**修复方案**：
1. 在 `SystemPromptBuilder.__init__()` 中新增 memory 文件加载逻辑：
   ```python
   # 若未显式传入 memory，尝试从 agent_config/memory/MEMORY.md 加载
   if not memory:
       memory_path = Path("agent_config") / "memory" / "MEMORY.md"
       if memory_path.exists():
           try:
               memory = memory_path.read_text(encoding="utf-8").strip()
           except Exception as e:
               logger.debug("加载 MEMORY.md 失败（已忽略）: %s", e)
   self.memory = memory
   ```
2. 创建 `agent_config/memory/MEMORY.md` 文件（可参考 nanobot 的 `_inject_time_context()` 写入时间上下文）。

**理由**：若保留 memory 参数和 charles-memory 段，应使其能实际生效，否则属于 dead code。此方案对齐 nanobot 的 MemoryStore 文件加载机制（简化版，不含 LLM 整合）。

**注意**：此方案与用户规则"代码中不要有 fallback"可能冲突（`if not memory` 是 fallback 逻辑）。若严格遵循用户规则，应改为显式传入 memory 参数，由调用方决定是否加载文件。

### 6.3 低优先级（P3）

#### P3-1: 补充 Memory 机制的架构文档（5.1 / 5.2）

**问题**：Charles 与 Cline / nanobot 在 Memory 机制上的架构差异未在代码文档中明确说明。

**修复方案**：在 `SystemPromptBuilder` 类 docstring 或 `_build_enhancement_rules` 方法 docstring 中补充：
- "Cline system prompt 无独立 Memory 段，无 MEMORY.md 加载机制"
- "Charles 的 charles-memory 段源自 nanobot MemoryStore 机制的形态残留，当前无文件加载逻辑"
- "nanobot 有完整 MemoryStore 类（memory.py），Charles 仅保留参数和注入点"

**理由**：明确架构差异有助于后续开发者理解 Charles 与 Cline / nanobot 的设计取舍。

---

## 七、验证方法建议

### 7.1 Cline Memory 机制缺失验证

1. **Cline 无 memory 占位符**：
   ```
   Grep "CLINE_MEMORY|{{MEMORY" third_party/cline/sdk/packages/shared/src/prompt/
   # 预期：0 命中
   ```

2. **Cline 无 MemoryStore 等价类**：
   ```
   Grep "MemoryStore|memory_store" third_party/cline/sdk/
   # 预期：0 命中
   ```

3. **Cline 无 MEMORY.md 加载**：
   ```
   Grep "MEMORY.md|memory_file" third_party/cline/sdk/
   # 预期：0 命中
   ```

### 7.2 Charles Memory 机制验证

1. **Charles 有 charles-memory 段**：
   ```
   Grep "charles-memory" agent/context.py
   # 预期：命中 L645（注入点）
   ```

2. **Charles 有 memory 参数**：
   ```
   Grep "memory: str = \"\"" agent/context.py
   # 预期：命中 L252（参数签名）
   ```

3. **Charles 无 MemoryStore 类**：
   ```
   Grep "MemoryStore|memory_store|class.*Memory" agent/
   # 预期：0 命中
   ```

4. **Charles 无 MEMORY.md 加载**：
   ```
   Grep "MEMORY.md|memory_file|load_memory|read_memory" agent/
   # 预期：0 命中
   ```

5. **agent_config/memory/ 目录不存在**：
   ```
   Glob "agent_config/memory/*"
   # 预期：No file found
   ```

6. **server.py 未传入 memory 参数**：
   ```
   Grep "memory=" agent/server.py
   # 预期：0 命中（server.py L541-548 构造 SystemPromptBuilder 时未传入 memory）
   ```

### 7.3 nanobot 溯源验证

1. **nanobot 有 MemoryStore 类**：
   ```
   Grep "class MemoryStore" third_party/charles_bundle/nanobot-main/nanobot/agent/memory.py
   # 预期：命中 L75
   ```

2. **nanobot 有 memory/MEMORY.md 加载**：
   ```
   Grep "MEMORY.md|memory_file" third_party/charles_bundle/nanobot-main/nanobot/agent/memory.py
   # 预期：命中 L82 / L87 / L92
   ```

3. **nanobot context.py 注入 # Memory 段**：
   ```
   Grep "# Memory" third_party/charles_bundle/nanobot-main/nanobot/agent/context.py
   # 预期：命中 L50
   ```

### 7.4 dead code 验证

```python
# 验证 self.memory 始终为空
# 1. server.py 构造 SystemPromptBuilder 时未传入 memory 参数
Grep "SystemPromptBuilder(" agent/server.py
# 预期：命中 L541，参数列表无 memory=...

# 2. system_prompt.yaml 总开关关闭
Read agent_config/system_prompt.yaml
# 预期：enhancements.enabled: false

# 3. agent_config/memory/ 目录不存在
Glob "agent_config/memory/*"
# 预期：No file found
```

---

## 八、与 P5.2 及其他阶段的衔接

### 8.1 与 P5.2 的衔接

P5.2（System Prompt 段落清单对比）在 5.2.10 项已发现 Memory 段差异，本阶段（P5.12）在段落清单基础上深入到机制级别，**确认并细化了以下发现**：

| P5.2 发现 | P5.12 深化 |
|----------|----------|
| Charles 有 enhancement `charles-memory` 段，默认关闭 | 确认 charles-memory 段是 dead code：`self.memory=""` 始终为空，即使开启 enhancement 也不会注入 |
| Cline 无独立 memory 段 | 确认 Cline 不仅无 memory 段，还无 MEMORY.md 加载机制、无 MemoryStore 类、无 LLM 整合记忆 |
| Charles 的 memory 段在 rules 内部末尾 | 确认顺序为 tools-overview → mcp-overview → always-skills → skills-summary → memory（context.py L620-646） |

### 8.2 与 P5.11 的衔接

| P5.11 发现 | P5.12 衔接 |
|----------|----------|
| `extra_sections` 参数是 nanobot 风格已废弃残留（dead code） | `memory` 参数同样是 nanobot 风格 dead code，但性质更严重：extra_sections 无消费方，memory 参数无内容来源 |
| Cline 有扩展 rule 合并机制，Charles 缺失 | Cline 的扩展 rule 机制不包含 memory 段；Charles 的 enhancement 机制包含 memory 段但无内容 |
| nanobot 注释残留 1 处（context.py L275） | Memory 段层面 nanobot 注释残留 0 处，但实现逻辑残留 2 处（L252/L289 + L644-645） |

### 8.3 与 P5.10 的衔接

| P5.10 发现 | P5.12 衔接 |
|----------|----------|
| always-skills 段是 Charles 独有 enhancement，Cline 无 | memory 段同样是 Charles 独有 enhancement，Cline 无；但 always-skills 段有实际内容来源（skills_registry.load_always_instructions()），memory 段无内容来源 |
| always-skills 段在 rules 内部倒数第二 | memory 段在 rules 内部最后（always-skills → skills-summary → memory） |

### 8.4 本阶段新增发现（P5.1 / P5.2 / P5.11 未覆盖）

1. **计划表系统性误标**（3.4）：计划表 L2022-2035 将 nanobot 的 MemoryStore 机制误标为 Cline 实现，这是 P5.2 未覆盖的发现。
2. **memory 参数的 dead code 性质确认**（4.2）：虽溯源 nanobot，但 server.py 未传入 memory 参数，`self.memory=""` 始终为空，charles-memory 段永远不会被注入，这是 P5.2 未明确的发现。
3. **nanobot MemoryStore 完整机制溯源**（3.3）：nanobot 有完整的 MemoryStore 类（memory.py L75-130）+ LLM 整合记忆（consolidate）+ 时间上下文注入（_inject_time_context），Charles 仅保留了参数和注入点，这是 P5.2 未细化的发现。
4. **`agent_config/memory/` 目录不存在**（3.2）：计划表 L2026 标注 Charles 从 `agent_config/memory/MEMORY.md` 加载，但该目录实际不存在，这是 P5.2 未验证的发现。

---

## 附录：检查覆盖声明

- **Cline 源码**：
  - `sdk/packages/shared/src/prompt/cline.ts`（L1-166）：通过 P5.1 / P5.2 已审阅，确认无 memory 占位符（本阶段引用结论）
  - `sdk/packages/shared/src/prompt/system.ts`（L1-68）：通过 P5.1 / P5.2 已审阅，确认无 memory 段（本阶段引用结论）
  - `sdk/packages/core/src/runtime/orchestration/session-runtime-orchestrator.ts`（L103-116 / L680-689）：通过 P5.11 已审阅，确认无 memory 专项合并逻辑（本阶段引用结论）

- **Charles 源码**：
  - `agent/context.py`（L1-2666）：100% 完整审阅（含 SystemPromptBuilder + ContextCompactor，确认 memory 参数 L252/L289、charles-memory 段 L644-645、_load_enhancements L304-346）
  - `agent/server.py`（L520-549 关键段落）：100% 完整审阅（SystemPromptBuilder 实例化，确认未传入 memory 参数）
  - `agent_config/system_prompt.yaml`（L1-10）：100% 完整审阅（enhancements.enabled=false，memory=true）
  - `agent/prompts/charles_system_prompt.py`：通过 P5.1 / P5.2 已审阅，确认无 memory 占位符（本阶段引用结论）

- **nanobot 溯源**：
  - `third_party/charles_bundle/nanobot-main/nanobot/agent/memory.py`（L1-130）：100% 完整审阅（MemoryStore 类，read_long_term / write_long_term / get_memory_context / consolidate）
  - `third_party/charles_bundle/nanobot-main/nanobot/agent/context.py`（L20-96）：100% 完整审阅（ContextBuilder，self.memory = MemoryStore(workspace) + # Memory 段注入）
  - `third_party/charles_bundle/charles-nanobot/agent.py`（L40-119）：100% 完整审阅（_inject_time_context 写入 memory/MEMORY.md）

- **10 项对比项**（5.12.1 - 5.12.10）：100% 逐项核对
- **nanobot 残留**：注释残留 0 处，实现逻辑残留 2 处（context.py L252/L289 + L644-645）
- **计划表勘误**：L2022-2035 共 7 处标注错误，已逐项勘误

本报告未修改任何源码，仅输出审计报告文件。
