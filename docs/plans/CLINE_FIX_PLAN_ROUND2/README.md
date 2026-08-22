# Cline 对齐修改方案总索引（第二轮：P1+P2 剩余差距）

> 生成时间：2026-07-26
> 基于评估报告：[CLINE_DIFF/SUMMARY_v2.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_DIFF/SUMMARY_v2.md)
> 覆盖范围：P1 剩余 6 项 + P2 剩余 22 项 = 28 项独立任务
> 排除项：有意不实施的 18 项（Sub-agent / Plugin / Hub / sandbox / workflows / external-rules 等）不再纳入计划

---

## 一、阶段总览

| 阶段 | 优先级 | 主题 | 任务数 | 依赖 |
|------|--------|------|--------|------|
| **Stage 9** | P1 | 紧急补全（MCP/Abort/会话迁移/Checkpoint/审批记忆） | 6 | 无 |
| **Stage 10** | P2 | 核心架构补全（流式 metadata / reminder / hook stop / 类型字段） | 6 | 无 |
| **Stage 11** | P2 | 上下文与压缩补全（行号 / abort 透传 / 状态投影 / 截断） | 4 | Stage 10 |
| **Stage 12** | P2 | 工具与文件 Hooks 补全（run_commands / apply_patch / context-injection / Hook 基础设施） | 5 | 无 |
| **Stage 13** | P2 | LLM Provider 与 Rules 补全（capabilities 透传 / provider 持久化 / toggle 分离 / skills multi-source） | 4 | 无 |
| **Stage 14** | P2 | 遥测与调度补全（OTLP exporter / Cron 完整架构 / distinctId + 事件枚举） | 3 | 无 |

---

## 二、执行顺序建议

### 2.1 立即执行（P1，Stage 9）
Stage 9 的 6 项是 v2 评估中确认的 P1 级剩余差距，影响功能正确性或数据安全，建议优先执行。

### 2.2 并行执行（P2，Stage 10-14）
Stage 10-14 之间无强依赖关系，可按模块熟悉度选择执行顺序：
- Stage 10/11 偏核心架构与上下文管理（建议先做，影响面广）
- Stage 12 偏工具与 Hooks（可与其他并行）
- Stage 13/14 偏 Provider/Rules/遥测（独立性高，可最后做）

### 2.3 推荐执行序列
```
Stage 9 (P1) → Stage 10 → Stage 11 → Stage 12 → Stage 13 → Stage 14
```

---

## 三、任务索引

### Stage 9: P1 紧急补全
| 任务 | Phase | 差距 | 文件 |
|------|-------|------|------|
| 9.1 | Q8 | MCP auto_approve 对接 approval 流程 | [stage_9_p1_emergency.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN_ROUND2/stage_9_p1_emergency.md) |
| 9.2 | N12 | 子进程 kill on abort | 同上 |
| 9.3 | S6/S12 | 会话版本迁移机制 | 同上 |
| 9.4 | T3/T6 | Checkpoint git ref 持久化 | 同上 |
| 9.5 | T5 | Checkpoint 回滚联动 | 同上 |
| 9.6 | U10 | 审批记忆跨会话持久化 | 同上 |

### Stage 10: P2 核心架构补全
| 任务 | Phase | 差距 | 文件 |
|------|-------|------|------|
| 10.1 | C8/C18 | 流式 metadata 合并链路 | [stage_10_p2_core_arch.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN_ROUND2/stage_10_p2_core_arch.md) |
| 10.2 | C19 | captureUnexpectedReasoningTokens | 同上 |
| 10.3 | B9 | reminder 循环前预注入 | 同上 |
| 10.4 | B33 | hook stop 状态分类 | 同上 |
| 10.5 | A7 | AgentToolContext.metadata 字段 | 同上 |
| 10.6 | A16 | AgentRuntimeConfig 缺失字段 | 同上 |

### Stage 11: P2 上下文与压缩补全
| 任务 | Phase | 差距 | 文件 |
|------|-------|------|------|
| 11.1 | J7 | 工具活动摘要行号范围 | [stage_11_p2_context_compaction.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN_ROUND2/stage_11_p2_context_compaction.md) |
| 11.2 | J12 | abort signal 透传 | 同上 |
| 11.3 | J13 | CompactionStateManager 状态投影 | 同上 |
| 11.4 | J18 | file/image 截断 | 同上 |

### Stage 12: P2 工具与文件 Hooks 补全
| 任务 | Phase | 差距 | 文件 |
|------|-------|------|------|
| 12.1 | G2.3/G2.4/G2.5 | run_commands 运行时行为 | [stage_12_p2_tools_hooks.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN_ROUND2/stage_12_p2_tools_hooks.md) |
| 12.2 | G4.1/G4.2/G4.5 | apply_patch 鲁棒性 | 同上 |
| 12.3 | P9 | context-injection before_tool 注入 | 同上 |
| 12.4 | P11/P12/P14 | Hook 基础设施 | 同上 |
| 12.5 | P16 | hook 并发执行 | 同上 |

### Stage 13: P2 LLM Provider 与 Rules 补全
| 任务 | Phase | 差距 | 文件 |
|------|-------|------|------|
| 13.1 | R5 | capabilities 透传到 AgentModelRequest | [stage_13_p2_provider_rules.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN_ROUND2/stage_13_p2_provider_rules.md) |
| 13.2 | R10 | provider-settings 持久化 | 同上 |
| 13.3 | X7 | global/local toggle 分离 | 同上 |
| 13.4 | X10 | skills multi-source | 同上 |

### Stage 14: P2 遥测与调度补全
| 任务 | Phase | 差距 | 文件 |
|------|-------|------|------|
| 14.1 | Z2 | OTLP exporter 完整实现 | [stage_14_p2_telemetry_cron.md](file:///e:/jikeAI/code/CASE-AI量化系统/CLINE_FIX_PLAN_ROUND2/stage_14_p2_telemetry_cron.md) |
| 14.2 | Z11 | Cron 完整架构 | 同上 |
| 14.3 | Z3/Z4 | distinctId + 事件枚举覆盖率 | 同上 |

---

## 四、执行原则

1. **每个 stage 可独立执行**：agent 读取 stage 文件后可独立完成，不依赖其他 stage
2. **保留原有功能**：修改某个函数时，先理解原有逻辑，在原有基础上修改，不移除已有逻辑
3. **中文注释 UTF-8 编码**：所有新增注释用中文，文件用 UTF-8 编码
4. **不写 fallback**：不添加降级逻辑，让错误自然抛出
5. **不写测试脚本**：除非用户明确要求，不编写测试脚本
6. **不写项目说明 md**：除非用户明确要求，不创建文档文件
7. **plan 是指引不是死命令**：每步执行后根据实际结果决定下一步，发现意外信息可调整后续步骤
8. **每步回顾上一步结果**：执行时根据发现调整，不盲目按 plan 执行

---

**索引结束。建议按 Stage 9 → 10 → 11 → 12 → 13 → 14 顺序推进。**
