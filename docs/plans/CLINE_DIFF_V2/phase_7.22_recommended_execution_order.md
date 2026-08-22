# Phase 7.22 推荐执行顺序

> 本报告基于 P7.21 优先级矩阵（计划文件 L2998-3016）的 14 项差距条目，结合 P7.20 整体对齐度评估（核心引擎层 90% / 辅助系统层 66% / 生态扩展层 12%）与计划文件 P7.22（L3017-3044）的三阶段划分，给出可落地的修复推荐执行顺序、依赖关系图、逐项执行步骤与风险评估。
>
> 输入来源：
> - P7.21 优先级矩阵：14 项差距（Q8 / F-base / M1 / M2 / A1 / L1 / L4 / L5 / L6 / L7 / L8 / S1 / S2 / L3-new）
> - P7.22 三阶段划分：Stage 1 架构重构 → Stage 2 P1+P2 补全 → Stage 3 P3 语义优化
> - 预期对齐度提升：93% →（Stage 1+2）96% →（Stage 3）99%
>
> 本报告只输出修复顺序与执行步骤，不修改任何源码。

---

## 一、执行摘要

P7.21 优先级矩阵共列出 14 项差距，按优先级分布为：P1 级 1 项（Q8）、P2 级 3 项（F-base / M1 / M2）、P3 级 10 项（A1 / L1 / L4 / L5 / L6 / L7 / L8 / S1 / S2 / L3-new）。按工作量分布为：4 行以内 5 项、5-30 行 6 项、50 行以上 2 项、0 行（合理差异）1 项。

计划文件 P7.22 将 14 项差距划分为三个执行阶段：

1. **Stage 1 架构重构（最先执行）**：A1 SystemPromptBuilder 职责分离（100 行，P3 优先级但属架构基础，必须先于 M1/M2/L1-L8 执行）。
2. **Stage 2 P1+P2 补全（立即执行）**：Q8 MCP approval 对接（30 行）+ F-base nanobot 清理（4 行）+ M1 mode_notice 机制（20 行）+ M2 user_input 包装下沉（15 行），合计 69 行。
3. **Stage 3 P3 语义优化（按需执行）**：L1 / L4 / L5 / L6 / L7 / L8 / S1 / S2 共 8 项语义层细节对齐，合计 97 行；L3-new 为合理差异不实施。

**执行顺序核心原则**：A1 虽标记为 P3 优先级，但其重构 SystemPromptBuilder 职责分层是 M1（mode_notice 注入点）/ M2（user_input 包装下沉至 runtime）/ L1-L8（prompt 字段与标签格式）的共同前置依赖，因此必须在 Stage 1 最先执行。Q8（mcp.py）与 F-base（base.py）不涉及 prompt 构建链路，可与 Stage 1 并行立即执行。

**预期对齐度提升路径**：
- 当前基线：约 93%（核心引擎层，含 prompt 构建层细节差距）
- Stage 1 完成后：架构分层对齐 Cline（SystemPromptBuilder 拆分为纯组装器 + 编排器）
- Stage 2 完成后：整体对齐度 93% → 96%（补齐 P1+P2 关键缺口）
- Stage 3 完成后：整体对齐度 96% → 99%（语义层细节全部对齐）

---

## 二、修复阶段划分

### 2.1 三阶段总览

| 阶段 | 名称 | 执行时机 | 包含差距项 | 工作量 | 优先级 | 依赖 |
|------|------|---------|-----------|--------|--------|------|
| Stage 1 | 架构重构 | 最先执行 | A1 | 100 行 | P3（架构基础） | 无 |
| Stage 2 | P1+P2 补全 | 立即执行（Stage 1 后） | Q8 / F-base / M1 / M2 | 69 行 | P1+P2 | M1/M2 依赖 A1；Q8/F-base 独立 |
| Stage 3 | P3 语义优化 | 按需执行（Stage 1 后） | L1 / L4 / L5 / L6 / L7 / L8 / S1 / S2 / L3-new | 97 行（含 0 行合理差异） | P3 | 全部依赖 A1 |

### 2.2 阶段映射到修复层级

本报告将三阶段进一步映射到"快速修复 / 中期修复 / 长期优化"三个执行层级，便于按团队节奏排期：

| 执行层级 | 对应阶段 | 选取标准 | 包含差距项 | 可立即执行 |
|---------|---------|---------|-----------|-----------|
| 快速修复（P0 级） | Stage 2 子集 | 无架构依赖 + 工作量 ≤ 30 行 + 独立模块 | Q8 / F-base | 是 |
| 中期修复（P1 级） | Stage 1 + Stage 2 剩余 | 需架构前置 + 工作量 15-100 行 + 跨文件 | A1 / M1 / M2 | 否（需 A1 先行） |
| 长期优化（P2/P3 级） | Stage 3 全部 | 语义层细节 + 工作量分散 + 可选 | L1 / L4 / L5 / L6 / L7 / L8 / S1 / S2 / L3-new | 否（需 A1 先行） |

**说明**：P7.21 优先级矩阵中的 P1/P2/P3 是"业务影响优先级"，而本报告的 P0/P1/P2 是"执行节奏层级"，二者维度不同。Q8 虽业务优先级为 P1，但因独立可立即执行，归入快速修复层；A1 虽业务优先级为 P3，但因属架构基础且 M1/M2/L1-L8 均依赖它，归入中期修复层并需最先启动。

---

## 三、快速修复清单（P0 级，可立即执行）

本层包含 2 项差距，均不涉及 SystemPromptBuilder 架构链路，可在 Stage 1 架构重构期间并行执行。

| 序号 | 差距 ID | 模块 | 优先级 | 工作量 | 影响文件 | 依赖 |
|------|---------|------|--------|--------|---------|------|
| 1 | Q8 | MCP auto_approve | P1 | 30 行 | mcp.py | 无 |
| 2 | F-base | nanobot 清理 | P2 | 4 行 | base.py | 无 |

**本层合计**：34 行，2 项，预计耗时 0.5-1 人日。

**本层完成后效果**：补齐 MCP 审批对接缺口 + 清理 nanobot 残留，不影响 prompt 构建链路，可独立验证。

---

## 四、中期修复清单（P1 级，需规划）

本层包含 3 项差距，其中 A1 是架构基础必须最先启动，M1/M2 依赖 A1 完成后才能接入。

| 序号 | 差距 ID | 模块 | 优先级 | 工作量 | 影响文件 | 依赖 |
|------|---------|------|--------|--------|---------|------|
| 1 | A1 | SystemPromptBuilder 职责分离 | P3（架构基础） | 100 行 | context.py + charles_system_prompt.py | 无（但 M1/M2/L1-L8 依赖它） |
| 2 | M1 | mode_notice 机制 | P2 | 20 行 | state.py + server.py | A1 |
| 3 | M2 | user_input 包装下沉 | P2 | 15 行 | runtime.py | A1 |

**本层合计**：135 行，3 项，预计耗时 2-3 人日。

**本层完成后效果**：
- A1 完成：SystemPromptBuilder 拆分为"纯组装器（组装 sections）+ 编排器（决定注入哪些 sections）"双层，架构分层对齐 Cline。
- M1+M2 完成：mode_notice 机制 + user_input 包装下沉，System Prompt 动态注入链路对齐 Cline。
- 整体对齐度：93% → 96%。

**执行顺序约束**：A1 必须先于 M1/M2 完成。M1 与 M2 之间无相互依赖，可并行。

---

## 五、长期优化清单（P2/P3 级，可选）

本层包含 9 项差距，全部依赖 A1 完成后的 SystemPromptBuilder 新结构。L3-new 为合理差异，仅记录不实施。

| 序号 | 差距 ID | 模块 | 优先级 | 工作量 | 影响文件 | 依赖 |
|------|---------|------|--------|--------|---------|------|
| 1 | L1 | env 字段名英文 | P3 | 4 行 | charles_system_prompt.py | A1 |
| 2 | L4 | metadata provider 条件 | P3 | 10 行 | context.py | A1 |
| 3 | L5 | metadata 标签格式 | P3 | 4 行 | context.py | A1 |
| 4 | L6 | PLAN_MODE run_commands 描述 | P3 | 2 行 | plan_mode.py | A1 |
| 5 | L7 | MODE_TAG 移除工具名 | P3 | 2 行 | context.py | A1 |
| 6 | L8 | yolo base prompt | P3 | 50 行 | charles_system_prompt.py | A1 |
| 7 | S1 | skill 白名单 4 形式 | P3 | 20 行 | registry.py | A1（弱依赖） |
| 8 | S2 | skillsTimeoutMs 可配置 | P3 | 5 行 | skill_tool.py | 无 |
| 9 | L3-new | rule name 文件 stem | P3 | 0 行 | 合理差异 | 不实施 |

**本层合计**：97 行（含 L3-new 0 行），9 项，预计耗时 1.5-2 人日。

**本层完成后效果**：System Prompt 语义层细节（字段名/标签格式/条件注入/yolo 模式/技能白名单/超时配置）全部对齐 Cline，整体对齐度 96% → 99%。

**执行顺序约束**：L1/L4/L5/L7 均涉及 context.py 与 charles_system_prompt.py，建议按文件聚集执行避免合并冲突；L6（plan_mode.py）与 S1/S2（registry.py / skill_tool.py）独立可并行。L3-new 不实施。

---

## 六、修复依赖关系图

### 6.1 依赖关系文字图

```
[Stage 1 架构基础]
  A1 SystemPromptBuilder 职责分离 (context.py + charles_system_prompt.py, 100行)
  │
  ├──┬──> [Stage 2 中期修复 - 依赖 A1]
  │  │      M1 mode_notice 机制 (state.py + server.py, 20行)
  │  │      M2 user_input 包装下沉 (runtime.py, 15行)
  │  │
  │  └──> [Stage 3 长期优化 - 依赖 A1]
  │         L1 env 字段名英文 (charles_system_prompt.py, 4行)
  │         L4 metadata provider 条件 (context.py, 10行)
  │         L5 metadata 标签格式 (context.py, 4行)
  │         L6 PLAN_MODE run_commands 描述 (plan_mode.py, 2行)
  │         L7 MODE_TAG 移除工具名 (context.py, 2行)
  │         L8 yolo base prompt (charles_system_prompt.py, 50行)
  │         S1 skill 白名单 4 形式 (registry.py, 20行, 弱依赖)
  │
  └──> [Stage 3 - 不依赖 A1]
            S2 skillsTimeoutMs 可配置 (skill_tool.py, 5行)
            L3-new rule name 文件 stem (0行, 合理差异, 不实施)

[快速修复 - 与 Stage 1 并行, 独立无依赖]
  Q8  MCP auto_approve (mcp.py, 30行)
  F-base nanobot 清理 (base.py, 4行)
```

### 6.2 依赖关系矩阵

| 修复项 | 前置依赖 | 后续被依赖 | 可并行项 |
|--------|---------|-----------|---------|
| A1 | 无 | M1 / M2 / L1 / L4 / L5 / L6 / L7 / L8 / S1 | Q8 / F-base / S2 / L3-new |
| Q8 | 无 | 无 | A1 / F-base / 全部 Stage 3 |
| F-base | 无 | 无 | A1 / Q8 / 全部 Stage 3 |
| M1 | A1 | 无 | M2 / Q8 / F-base / Stage 3 |
| M2 | A1 | 无 | M1 / Q8 / F-base / Stage 3 |
| L1 | A1 | 无 | L4-L8 / S1 / S2 / M1 / M2 |
| L4 | A1 | 无 | L1 / L5-L8 / S1 / S2 / M1 / M2 |
| L5 | A1 | 无 | L1-L4 / L6-L8 / S1 / S2 / M1 / M2 |
| L6 | A1 | 无 | 全部其他（独立文件 plan_mode.py） |
| L7 | A1 | 无 | 全部其他 |
| L8 | A1 | 无 | 全部其他（与 L1 同文件建议串行） |
| S1 | A1（弱依赖） | 无 | 全部其他（独立文件 registry.py） |
| S2 | 无 | 无 | 全部其他（独立文件 skill_tool.py） |
| L3-new | 无 | 无 | 不实施 |

### 6.3 关键路径

**关键路径**（决定整体工期的最长依赖链）：

```
A1 (100行) → M1 (20行) + M2 (15行) → Stage 3 (L1-L8 + S1, 92行)
```

A1 是关键路径的起点与瓶颈，必须最先启动。A1 完成后 M1/M2 与 Stage 3 可并行推进。

**非关键路径**（可并行执行）：

```
Q8 (30行) ∥ F-base (4行) ∥ S2 (5行) ∥ L3-new (不实施)
```

这 4 项与关键路径无依赖关系，可在 A1 执行期间任意时间点并行完成。

---

## 七、每个修复项的详细执行步骤

### 7.1 A1 - SystemPromptBuilder 职责分离（Stage 1，架构基础）

**差距 ID**：A1
**优先级**：P3（架构基础，执行优先级最高）
**工作量**：100 行
**影响文件**：context.py + charles_system_prompt.py
**前置依赖**：无
**后续被依赖**：M1 / M2 / L1 / L4 / L5 / L6 / L7 / L8 / S1

**执行步骤**：

1. **阅读现状**：读取 context.py 中 SystemPromptBuilder 当前实现，确认其同时承担"sections 组装"与"注入决策"两类职责。
2. **拆分设计**：将 SystemPromptBuilder 拆分为两个类：
   - `SystemPromptAssembler`（纯组装器）：只负责按顺序拼接 sections 字符串，不决定注入哪些 section。
   - `SystemPromptOrchestrator`（编排器）：根据 env / metadata / skills / mcp / mode / user_input 等条件决定调用哪些 section 构建方法，再委托 Assembler 组装。
3. **context.py 改造**：保留 SystemPromptBuilder 类名作为兼容入口（或直接替换为 Orchestrator），将组装逻辑下沉到 Assembler。
4. **charles_system_prompt.py 改造**：将各 section 构建函数（base / env / tools / metadata / mcp / cline_rules / skills_overview 等）调整为接受 context 参数的纯函数，由 Orchestrator 调用。
5. **验证**：运行现有 system prompt 单元测试（若有），确认输出与重构前字节级一致；若无测试则手动对比一次完整 prompt 输出。
6. **不引入新行为**：A1 是纯结构重构，不改 prompt 内容，所有内容性变更留给 M1/M2/L1-L8。

**验收标准**：SystemPromptBuilder 拆分为组装器 + 编排器双层；重构前后 system prompt 输出完全一致。

---

### 7.2 Q8 - MCP auto_approve 对接（快速修复，P0 级）

**差距 ID**：Q8
**优先级**：P1
**工作量**：30 行
**影响文件**：mcp.py
**前置依赖**：无

**执行步骤**：

1. **阅读现状**：读取 mcp.py 中 MCP 工具调用前的审批逻辑，确认当前是否跳过 auto_approve 检查。
2. **对接审批模块**：在 MCP 工具执行前调用审批模块（与 builtin tools 相同的 approval 检查路径），支持 per-tool 策略 + 自动批准 + 用户审批 + 拒绝跳过。
3. **MCP 粒度对齐**：参考 P3.8 工具审批报告，确认 Charles 已支持 MCP per-tool 粒度（P7.20 评估显示 Charles 在 MCP 粒度上强于 Cline），此处仅需补齐 auto_approve 对接。
4. **错误处理**：审批被拒绝时返回与 builtin tools 相同的拒绝语义（skip tool call）。
5. **验证**：手动触发一次 MCP 工具调用，确认审批流程正确触发。

**验收标准**：MCP 工具调用前经过审批模块检查，auto_approve / 用户审批 / 拒绝跳过三种路径均可走通。

---

### 7.3 F-base - nanobot 残留清理（快速修复，P0 级）

**差距 ID**：F-base
**优先级**：P2
**工作量**：4 行
**影响文件**：base.py
**前置依赖**：无

**执行步骤**：

1. **定位残留**：在 base.py 中搜索 "nanobot" 关键字，定位残留注释或残留导入。
2. **清理残留**：删除 nanobot 相关的 4 行残留代码（注释 / 导入 / 死代码）。
3. **验证**：运行 base.py 相关模块导入测试，确认无导入错误。

**验收标准**：base.py 中无 nanobot 关键字残留；模块导入正常。

---

### 7.4 M1 - mode_notice 机制（中期修复，P1 级）

**差距 ID**：M1
**优先级**：P2
**工作量**：20 行
**影响文件**：state.py + server.py
**前置依赖**：A1

**执行步骤**：

1. **阅读现状**：读取 state.py 中 SessionState 的 mode 字段管理逻辑，确认当前是否在 mode 切换时发送 mode_notice 事件。
2. **设计 mode_notice**：在 mode 切换（如 plan → act → ask）时，通过 server.py 发送一个 system_notice 类事件，告知 LLM 当前已进入新 mode。
3. **state.py 改造**：在 mode setter 或 mode 切换函数中追加 mode_notice 触发逻辑（约 10 行）。
4. **server.py 改造**：新增 mode_notice 事件发送端点或复用现有 system_notice 通道（约 10 行）。
5. **接入编排器**：在 A1 拆分后的 SystemPromptOrchestrator 中，确认 mode_notice 注入点与 Cline 一致。
6. **验证**：手动切换一次 mode，确认 mode_notice 事件正确发送并被 LLM 感知。

**验收标准**：mode 切换时自动发送 mode_notice；LLM 能感知 mode 变化。

---

### 7.5 M2 - user_input 包装下沉（中期修复，P1 级）

**差距 ID**：M2
**优先级**：P2
**工作量**：15 行
**影响文件**：runtime.py
**前置依赖**：A1

**执行步骤**：

1. **阅读现状**：读取 runtime.py 中 user_input 消息的处理逻辑，确认当前是否在 runtime 层包装 user_input（如包裹 mode 标签 / user_input_mode section）。
2. **下沉包装**：将 user_input 的包装逻辑从调用方下沉到 runtime.py 的统一入口，确保所有 user_input 都经过包装。
3. **接入编排器**：在 A1 拆分后的 SystemPromptOrchestrator 中，确认 user_input 包装注入点与 Cline 一致。
4. **验证**：手动发送一条 user_input 消息，确认包装格式正确。

**验收标准**：user_input 在 runtime 层统一包装；包装格式与 Cline 一致。

---

### 7.6 L1 - env 字段名英文（长期优化，P2/P3 级）

**差距 ID**：L1
**优先级**：P3
**工作量**：4 行
**影响文件**：charles_system_prompt.py
**前置依赖**：A1

**执行步骤**：

1. **定位中文字段名**：在 charles_system_prompt.py 的 env section 构建函数中，搜索中文字段名（如"模型"/"会话"等）。
2. **替换为英文**：将中文字段名替换为英文（如 model / session），对齐 Cline env section 字段名。
3. **验证**：确认 env section 输出字段名全英文。

**验收标准**：env section 字段名全英文，与 Cline 一致。

---

### 7.7 L4 - metadata provider 条件（长期优化，P2/P3 级）

**差距 ID**：L4
**优先级**：P3
**工作量**：10 行
**影响文件**：context.py
**前置依赖**：A1

**执行步骤**：

1. **阅读现状**：读取 context.py 中 metadata section 的 provider 字段注入逻辑。
2. **添加条件**：为 provider 字段添加条件注入（如 provider 存在且非默认值时才注入），对齐 Cline 条件注入策略。
3. **验证**：确认 provider 字段在条件不满足时不注入。

**验收标准**：metadata provider 字段条件注入，与 Cline 一致。

---

### 7.8 L5 - metadata 标签格式（长期优化，P2/P3 级）

**差距 ID**：L5
**优先级**：P3
**工作量**：4 行
**影响文件**：context.py
**前置依赖**：A1

**执行步骤**：

1. **定位标签格式**：在 context.py 中定位 metadata section 的标签格式（如 `<metadata>` vs `## Metadata`）。
2. **对齐格式**：将标签格式调整为与 Cline 一致。
3. **验证**：确认 metadata section 标签格式与 Cline 一致。

**验收标准**：metadata 标签格式与 Cline 一致。

---

### 7.9 L6 - PLAN_MODE run_commands 描述（长期优化，P2/P3 级）

**差距 ID**：L6
**优先级**：P3
**工作量**：2 行
**影响文件**：plan_mode.py
**前置依赖**：A1

**执行步骤**：

1. **定位描述**：在 plan_mode.py 中定位 run_commands 工具的描述文本。
2. **对齐描述**：将描述文本调整为与 Cline PLAN_MODE 下 run_commands 描述一致。
3. **验证**：确认描述文本与 Cline 一致。

**验收标准**：PLAN_MODE 下 run_commands 描述与 Cline 一致。

---

### 7.10 L7 - MODE_TAG 移除工具名（长期优化，P2/P3 级）

**差距 ID**：L7
**优先级**：P3
**工作量**：2 行
**影响文件**：context.py
**前置依赖**：A1

**执行步骤**：

1. **定位 MODE_TAG**：在 context.py 中定位 MODE_TAG 常量或 mode 标签生成逻辑。
2. **移除工具名**：从 MODE_TAG 中移除工具名（mode 标签不应包含工具名，仅包含 mode 名）。
3. **验证**：确认 MODE_TAG 输出不含工具名。

**验收标准**：MODE_TAG 不含工具名，与 Cline 一致。

---

### 7.11 L8 - yolo base prompt（长期优化，P2/P3 级）

**差距 ID**：L8
**优先级**：P3
**工作量**：50 行
**影响文件**：charles_system_prompt.py
**前置依赖**：A1

**执行步骤**：

1. **阅读现状**：读取 charles_system_prompt.py 中 base prompt 的构建逻辑，确认当前是否区分 yolo 模式。
2. **添加 yolo base prompt**：在 yolo 模式（自动批准所有工具）下，使用独立的 base prompt 文本（对齐 Cline yolo base prompt），告知 LLM 当前为自动批准模式。
3. **条件注入**：在 SystemPromptOrchestrator 中根据 mode 切换 base prompt。
4. **验证**：在 yolo 模式下确认 base prompt 输出正确。

**验收标准**：yolo 模式下使用独立 base prompt，与 Cline 一致。

---

### 7.12 S1 - skill 白名单 4 形式（长期优化，P2/P3 级）

**差距 ID**：S1
**优先级**：P3
**工作量**：20 行
**影响文件**：registry.py
**前置依赖**：A1（弱依赖）

**执行步骤**：

1. **阅读现状**：读取 registry.py 中 skill 白名单匹配逻辑。
2. **对齐 4 形式**：确认白名单支持 4 种匹配形式（精确匹配 / 前缀通配 / 后缀通配 / 全通配），对齐 Cline。
3. **补充缺失形式**：若 Charles 缺某形式则补充。
4. **验证**：用 4 种形式各测一次匹配。

**验收标准**：skill 白名单支持 4 种匹配形式，与 Cline 一致。

**说明**：P7.20 评估显示 Charles 技能系统对齐度 95%，S1/S2 差距"已修复"——此处执行前需先二次确认是否仍存在差距，若已修复则跳过。

---

### 7.13 S2 - skillsTimeoutMs 可配置（长期优化，P2/P3 级）

**差距 ID**：S2
**优先级**：P3
**工作量**：5 行
**影响文件**：skill_tool.py
**前置依赖**：无（独立）

**执行步骤**：

1. **阅读现状**：读取 skill_tool.py 中技能超时常量（当前硬编码 15s）。
2. **改为可配置**：将超时改为从配置读取（skillsTimeoutMs），默认值保持 15s。
3. **验证**：修改配置后确认超时生效。

**验收标准**：技能超时可通过 skillsTimeoutMs 配置，与 Cline 一致。

**说明**：同 S1，P7.20 评估显示"已修复"，执行前需二次确认。

---

### 7.14 L3-new - rule name 文件 stem（不实施）

**差距 ID**：L3-new
**优先级**：P3
**工作量**：0 行（合理差异）
**影响文件**：无
**前置依赖**：无

**结论**：P7.21 优先级矩阵明确标注为"合理差异"，无需修复。Charles 的 rule name 命名规则与 Cline 不同（Charles 用业务语义名，Cline 用文件 stem），属架构选择，不对齐。

**动作**：仅在文档中记录差异，不修改代码。

---

## 八、风险评估

### 8.1 风险矩阵

| 风险项 | 概率 | 影响 | 风险等级 | 缓解措施 |
|--------|------|------|---------|---------|
| A1 重构引入 prompt 内容回归 | 中 | 高（影响所有 LLM 调用） | 高 | 重构前保存一份完整 prompt 输出作为黄金基线；重构后字节级对比；A1 不改内容只改结构 |
| A1 重构后 M1/M2 接入点偏移 | 中 | 中（M1/M2 需返工） | 中 | A1 完成后明确文档化 Orchestrator 的扩展点；M1/M2 开发前先对齐扩展点设计 |
| Q8 审批对接阻塞 MCP 工具调用 | 低 | 中（MCP 工具不可用） | 中 | 保留 auto_approve 配置项；默认行为与重构前一致；灰度验证 |
| M1 mode_notice 事件被 LLM 误解 | 低 | 中（LLM 行为异常） | 中 | mode_notice 文案明确告知"已进入 X mode，请遵循 X mode 规则"；小范围验证 |
| M2 user_input 包装下沉遗漏调用点 | 中 | 中（部分 user_input 未包装） | 中 | 全局搜索 user_input 所有调用点；统一走 runtime 入口 |
| L8 yolo base prompt 与默认 base prompt 不一致 | 低 | 低（仅 yolo 模式） | 低 | yolo base prompt 独立维护；仅在 yolo 模式注入 |
| Stage 3 多项同改 context.py 合并冲突 | 高 | 低（合并耗时增加） | 中 | 按文件聚集执行 L1/L4/L5/L7（context.py + charles_system_prompt.py）；L6/S1/S2 独立文件可并行 |
| S1/S2 已修复但仍列入计划 | 中 | 低（重复劳动） | 低 | 执行前二次确认 P7.20 评估结论"已修复"；若确认已修复则跳过 |
| L3-new 被误修复 | 低 | 低（架构偏离） | 低 | 在代码注释中标注"合理差异，不对齐" |

### 8.2 高风险项详解

**风险 1：A1 重构引入 prompt 内容回归（高风险）**

A1 是 100 行的结构重构，涉及 SystemPromptBuilder 拆分为组装器 + 编排器。虽然设计上是"纯结构重构不改内容"，但拆分过程中极易引入隐式的内容变更（如 section 顺序错位、空白字符变化、占位符替换遗漏）。

**缓解措施**：
1. 重构前导出一份完整 system prompt 输出（覆盖所有 mode / env / metadata / skills / mcp 组合）作为黄金基线。
2. 重构后对每组组合字节级对比，任何差异都需明确归因（是预期变更还是回归）。
3. A1 提交时附带黄金基线对比报告。
4. A1 不在同一次提交中混入 M1/M2/L1-L8 的内容性变更，确保回归可定位。

**风险 2：Stage 3 多项同改 context.py 合并冲突（中风险）**

L4 / L5 / L7 均涉及 context.py，L1 / L8 均涉及 charles_system_prompt.py。若并行开发易产生合并冲突。

**缓解措施**：
1. 按文件聚集执行：先合并所有 context.py 改动（L4+L5+L7），再合并所有 charles_system_prompt.py 改动（L1+L8）。
2. L6（plan_mode.py）/ S1（registry.py）/ S2（skill_tool.py）独立文件可并行。
3. 单人串行执行同文件项，避免多人并行同文件。

### 8.3 回滚策略

| 修复项 | 回滚难度 | 回滚方式 |
|--------|---------|---------|
| A1 | 中 | 保留重构前 SystemPromptBuilder 备份；回滚时整体替换 |
| Q8 | 低 | 审批对接为新增调用，删除调用即回滚 |
| F-base | 低 | 删除的 4 行可从 git 历史恢复 |
| M1 | 低 | mode_notice 为新增事件，移除即回滚 |
| M2 | 低 | user_input 包装为新增逻辑，移除即回滚 |
| L1-L8 | 低 | 字段名/标签/描述/条件均为小改动，逐项回滚 |
| S1/S2 | 低 | 白名单/超时配置为小改动，逐项回滚 |

**整体回滚原则**：A1 是架构重构，回滚需整体替换；其余项均为增量改动，可逐项独立回滚。建议每项修复独立提交，便于精准回滚。

---

## 九、执行排期建议

### 9.1 排期总览（单人执行）

| 阶段 | 工作量 | 预计耗时 | 累计对齐度 |
|------|--------|---------|-----------|
| Stage 1（A1） | 100 行 | 1.5-2 人日 | 架构分层对齐 |
| 快速修复（Q8 + F-base，与 Stage 1 并行） | 34 行 | 0.5-1 人日 | — |
| Stage 2（M1 + M2，Stage 1 后） | 35 行 | 0.5-1 人日 | 93% → 96% |
| Stage 3（L1-L8 + S1 + S2） | 97 行 | 1.5-2 人日 | 96% → 99% |
| **合计** | **266 行** | **4-6 人日** | **93% → 99%** |

### 9.2 排期总览（双人并行执行）

| 时间窗 | 人员 A | 人员 B |
|--------|--------|--------|
| Day 1-2 | A1 架构重构 | Q8 + F-base 快速修复 |
| Day 3 | M1 mode_notice | S2 skillsTimeoutMs + L6 PLAN_MODE 描述 |
| Day 4 | M2 user_input 包装 | L1 env 字段名 + L5 metadata 标签 + L7 MODE_TAG |
| Day 5 | L8 yolo base prompt | L4 metadata provider 条件 + S1 skill 白名单 |
| Day 6 | 集成验证 + 黄金基线对比 | 集成验证 + 黄金基线对比 |

**双人并行注意事项**：Day 3 起人员 B 的 Stage 3 项依赖人员 A 的 A1 完成，需 A1 在 Day 2 末完成并合并。同文件项（context.py / charles_system_prompt.py）需错开日期避免冲突。

---

## 十、附录：差距项与阶段映射总表

| 差距 ID | 模块 | P7.21 优先级 | 工作量 | 影响文件 | 执行阶段 | 执行层级 | 前置依赖 |
|---------|------|-------------|--------|---------|---------|---------|---------|
| A1 | SystemPromptBuilder 职责分离 | P3 | 100 行 | context.py + charles_system_prompt.py | Stage 1 | 中期修复（P1） | 无 |
| Q8 | MCP auto_approve | P1 | 30 行 | mcp.py | Stage 2 | 快速修复（P0） | 无 |
| F-base | nanobot 清理 | P2 | 4 行 | base.py | Stage 2 | 快速修复（P0） | 无 |
| M1 | mode_notice 机制 | P2 | 20 行 | state.py + server.py | Stage 2 | 中期修复（P1） | A1 |
| M2 | user_input 包装下沉 | P2 | 15 行 | runtime.py | Stage 2 | 中期修复（P1） | A1 |
| L1 | env 字段名英文 | P3 | 4 行 | charles_system_prompt.py | Stage 3 | 长期优化（P2/P3） | A1 |
| L4 | metadata provider 条件 | P3 | 10 行 | context.py | Stage 3 | 长期优化（P2/P3） | A1 |
| L5 | metadata 标签格式 | P3 | 4 行 | context.py | Stage 3 | 长期优化（P2/P3） | A1 |
| L6 | PLAN_MODE run_commands 描述 | P3 | 2 行 | plan_mode.py | Stage 3 | 长期优化（P2/P3） | A1 |
| L7 | MODE_TAG 移除工具名 | P3 | 2 行 | context.py | Stage 3 | 长期优化（P2/P3） | A1 |
| L8 | yolo base prompt | P3 | 50 行 | charles_system_prompt.py | Stage 3 | 长期优化（P2/P3） | A1 |
| S1 | skill 白名单 4 形式 | P3 | 20 行 | registry.py | Stage 3 | 长期优化（P2/P3） | A1（弱） |
| S2 | skillsTimeoutMs 可配置 | P3 | 5 行 | skill_tool.py | Stage 3 | 长期优化（P2/P3） | 无 |
| L3-new | rule name 文件 stem | P3 | 0 行 | 合理差异 | 不实施 | 不实施 | 无 |

**预期对齐度提升路径**：93%（基线）→ Stage 1 架构分层对齐 → Stage 2 完成后 96% → Stage 3 完成后 99%。
