# Cline 对齐修改方案总索引

> 生成时间：2026-07-26
> 基础：CLINE_DIFF/ 下 26 份对比报告 + SUMMARY.md
> 目标：按优先级 + 模块划分小阶段，每阶段任务可独立由 agent 执行
> 原则：基于差距分析但需结合实际代码，避免死板照搬计划

---

## 一、方案结构

按 **优先级** 划分 8 个大阶段，每大阶段内按 **模块** 划分小阶段：

| 大阶段 | 主题 | 优先级 | 预估工作量 | 小阶段数 |
|--------|------|--------|-----------|---------|
| [stage_1_p0_emergency.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_1_p0_emergency.md) | P0 紧急修复 - 阻塞核心功能 | P0 | 1-2 天 | 2 |
| [stage_2_p1_core_arch.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_2_p1_core_arch.md) | P1 核心架构对齐 | P1 | 1 周 | 8 |
| [stage_3_p1_tools_skills.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_3_p1_tools_skills.md) | P1 工具与技能修复 | P1 | 1-2 周 | 8 |
| [stage_4_p1_context_prompt.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_4_p1_context_prompt.md) | P1 上下文与提示对齐 | P1 | 1 周 | 8 |
| [stage_5_p1_security_stability.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_5_p1_security_stability.md) | P1 安全与稳定性 | P1 | 1 周 | 8 |
| [stage_6_p2_persistence.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_6_p2_persistence.md) | P2 持久化与历史管理 | P2 | 1-2 月 | 8 |
| [stage_7_p2_extension.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_7_p2_extension.md) | P2 扩展机制完善 | P2 | 1-2 月 | 8 |
| [stage_8_p3_longterm.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN/stage_8_p3_longterm.md) | P3 长期评估项 | P3 | 按需 | 8 |

---

## 二、任务执行规范

### 2.1 每个小阶段任务包含

1. **任务背景**：来源 CLINE_DIFF 报告 + 差距描述
2. **目标**：明确对齐 Cline 的具体行为
3. **当前实现位置**：我的源代码文件:行号
4. **目标源代码位置**：Cline 源代码文件:行号
5. **修复步骤建议**：分步骤的实施路径
6. **验证方法**：如何验证修复成功
7. **注意事项**：提醒 agent 需结合实际代码判断，不能死板照搬

### 2.2 执行原则

1. **基于差距但不死板**：CLINE_DIFF 报告是参考，实际代码可能有差异，需 Read 后判断
2. **保留合理增强**：标为"额外增强"的项不应删除
3. **量化场景特化**：标为"合理特化"的项不需对齐
4. **小步快跑**：每个小阶段独立可执行，完成后可单独验证
5. **不破坏现有功能**：修改前先理解原函数逻辑，在原基础上修改
6. **中文注释 UTF-8**：所有新增注释中文，文件 UTF-8 编码
7. **无 emoji**：代码与文档均不使用 emoji
8. **不写 fallback**：除非必要，不添加降级逻辑

### 2.3 依赖关系

- stage_1 → 独立可执行（P0 紧急）
- stage_2 → 部分依赖 stage_1（核心架构）
- stage_3 → 依赖 stage_2（工具技能）
- stage_4 → 依赖 stage_2（上下文提示）
- stage_5 → 独立可执行（安全稳定）
- stage_6 → 独立可执行（持久化）
- stage_7 → 依赖 stage_2/stage_4（扩展机制）
- stage_8 → 评估后决定是否实施

---

## 三、覆盖范围

本方案覆盖 CLINE_DIFF/SUMMARY.md 中识别的全部差距：

| 差距类型 | 数量 | 分布 |
|---------|------|------|
| P0 紧急 | 2 项 | stage_1 |
| P1 短期 | 31 项 | stage_2-5 |
| P2 中期 | 约 30 项 | stage_6-7 |
| P3 长期 | 约 20 项 | stage_8 |
| 语义不等价 | 13 项 | 分布在各阶段 |
| 合理特化（不对齐） | 8 项 | 标注但不实施 |
| 额外增强（保留） | 14 项 | 标注但保留 |

---

## 四、执行建议

### 4.1 推荐执行顺序

1. **第 1 周**：stage_1（P0）→ stage_2（P1 核心架构）
2. **第 2 周**：stage_3（P1 工具技能）+ stage_4（P1 上下文提示）并行
3. **第 3 周**：stage_5（P1 安全稳定）
4. **第 1-2 月**：stage_6 + stage_7（P2）
5. **按需**：stage_8（P3 评估）

### 4.2 质量保证

- 每个小阶段完成后，运行 `python tests/test_agent_e2e.py` 验证
- 涉及工具修改的，需补充针对性测试
- 修改后更新对应 CLINE_DIFF 报告的对齐度

---

**总索引结束。请按 stage_1 → stage_8 顺序执行，每阶段内小阶段可并行。**
