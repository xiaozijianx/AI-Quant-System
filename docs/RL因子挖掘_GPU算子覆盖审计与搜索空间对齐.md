# RL 因子挖掘 · GPU 算子覆盖审计与搜索空间对齐核查

> 版本：v1（2026-08-19）→ **v2（2026-08-19，补齐执行完成）**
> 目的：针对"补充的算子/因子/基类是否做了 torch 化"这一重点问题做深度审计。
> 涉及体系：因子库/基类（factor_init）→ CPU 表达式引擎（factor_engine）→ GPU 编译求值（factor_gpu_torch / factor_gpu_evaluator）→ GP / LLM-GP 搜索空间（factor_gp / factor_llm_gp）→ RL 搜索空间（factor_rl）。
> 结论速览：**GP / LLM-GP 的"torch 化"是独立完整的一条线（在其搜索空间内 100% GPU 覆盖）；RL 训练用的是自带的 StackVM（纯 torch，与 GPU 编译器无关）；RL 收尾复用 GP 的 GPU 求值器，缺口发生在这里——RL 的搜索空间覆盖了 GPU 表未实现的 22 处算子/字段。**
> **v2 更新（2026-08-19）：缺口已全部补齐并通过 GPU/CPU 数值对照（29/29 corr=1.0），详见第八节。**

---

## 一、架构分层（先厘清"五层"谁是谁）

| 层 | 文件 | 职责 | 算子/字段来源 |
|---|---|---|---|
| L0 因子库/基类 | `lib/factor_init.py` + DB（factor_library / factor_base） | 因子定义、基类定义、映射标注 | BASIC_FACTORS / BASE_FACTORS（含 AlphaMaster 映射补充的 23 个参数化基类、2 个固定基类） |
| L1 CPU 表达式引擎 | `lib/factor_engine.py` | `evaluate_expression` 唯一求值入口；`BASE_OPERATOR_MAP` 展开基类 | 全部算术/时序/截面算子 + 全部基类（**全覆盖**） |
| L2 GPU 编译求值 | `lib/factor_gpu_torch.py`（算子表 t_*）+ `lib/factor_gpu_evaluator.py`（TensorPanel / PanelTensorCompiler / gpu_supported） | 把表达式 dict 树整树编译为 torch 张量批量求值 | TORCH_ARITH(15) / TORCH_TS(79) / TORCH_TS_RAW(3) / TORCH_CS(4)；基类映射复用 L1 的 BASE_OPERATOR_MAP |
| L3 GP / LLM-GP 搜索空间 | `lib/factor_gp.py` / `lib/factor_llm_gp.py` | 遗传算法与大模型增强 GP 的算子/基类叶子集合 | GP_FIELDS(11) / GP_ARITH_* / GP_TS_OPS / GP_TS_RAW / GP_CS_OPS / GP_BASE_LEAF(45) |
| L4 RL 搜索空间 | `lib/factor_rl/`（features/ops/vm/trainer/pipeline） | 强化学习因子挖掘的词表与执行 | FEATURE_SPECS(65) / OPERATOR_REGISTRY(65) |

**关键关系**：
- L1 是唯一求值底座；L3 的树节点、L4 的解码表达式最终都要落到 L1 语义。
- L2 是 L1 的 GPU 加速侧；`gpu_supported`（factor_gpu_evaluator L699-736）逐节点预检，任一节点不受支持 → 整树返回 False → 调用方回退 L1（单树粒度，见第四节）。

---

## 二、"GP 的 torch 化"与"RL 的 torch 化"是不是两套独立的东西？—— 是

### 2.1 GP / LLM-GP 的 torch 化（L2，一条已闭环的线）

- GP 主线（`factor_gp.evolve`，`use_gpu_tensor` 参数 L1188）与 **LLM-GP（`factor_llm_gp.run_llm_gp_evolution`，`use_gpu_tensor` L695）复用同一个 GPU 求值器**（TensorPanel / PanelTensorCompiler / gpu_supported / mean_rank_ic），仅评估调度各自实现。
- **阶段6.3 已把 GP 搜索空间内的算子全部 GPU 化**：
  - TORCH_ARITH：add/sub/mul/div/abs + sign/jump/max3/power/signed_log/sqrt/clip/sigmoid/tanh_squash/winsorize（L2160-2166）
  - TORCH_TS：含 ts_ArgMax/ts_ArgMin/ts_Product/ts_DecayLinear（L2209-2210）与 9 个纳入 GP_BASE_LEAF 的 AlphaMaster 基类（ts_PricePosition/ts_Autocorr/ts_TypicalDev/ts_DmiDiff/ts_Trix/ts_AmihudIlliq/ts_KyleLambda/ts_CMF/ts_ADLineSlope，L2212-2216）+ Hilbert 族
  - TORCH_TS_RAW：ts_Log/ts_Identity/ts_Scale
  - TORCH_CS：cs_Rank/cs_Demean/cs_Zscore/cs_TransNorm
- **CRP_BASE_LEAF 全部 45 个基类键逐条核对：`entry[0] in TORCH_TS` 均成立** → **GP 搜索空间内 GPU 覆盖 = 100%**，无逐树回退。
- GP 刻意排除的 13 个重计算基类（hurst/fractal_dim/trend_strength/supertrend/ichimoku 等，factor_gp.py L125-127"复杂估计/多字段强耦合保持过滤"）——**不在搜索空间里，所以 GPU 表没有它们是"设计使然"，不是遗漏**。

### 2.2 RL 训练的 torch 化（factor_rl 自带的 StackVM，与 L2 无关）

- `factor_rl/vm.py` 的 StackVM 本身就是 torch 算子实现（CPU），RL 训练主循环（trainer）固定 CPU，**与 factor_gpu_torch 完全独立**。
- RL 词表 65 个算子在 VM 内全部有实现 = "RL 训练的 torch 化"是完整的。

### 2.3 RL 收尾的 torch 化（复用 L2 → 缺口发生地）

- `factor_rl/pipeline.py` 收尾筛选（oos_recheck / walk_forward_recheck / permutation_significance / dedup_by_corr）带 `use_gpu` 参数，**复用 factor_gp 的 GPU 求值器**。
- RL 解码后的表达式（FEATURE_EXPRS + DECODE_MAP）**覆盖了 GPU 表未实现的一批算子** → 这里就是"补充的算子没有 torch 化"的真实含义。

### 2.4 根因

映射方案阶段二补的是 L0/L1（因子库 + CPU 引擎）；阶段6.3 补 GPU 时以 **GP 搜索空间为基准**；而 RL 是"AlphaMaster 65 特征全量驱动"，需要 GP 特意过滤的重计算基类。**L2 的覆盖以 L3 为准绳，从未以 L4 为准绳——两套体系各自演进、没有做一次"RL 词表 ↔ GPU 表"的对齐审计**，本次审计补上这一步。

---

## 三、RL 用例的 GPU 缺口清单（共 22 处）

> 判定标准：RL 特征表达式 / 算子解码表达式里的函数名 → GPU 表（TORCH_ARITH / TORCH_TS / TORCH_TS_RAW / TORCH_CS）是否存在。

### 3.1 轻量级缺失（4 个，基本是已有算子的组合/wrapper，实现成本低）

| GPU 缺失算子 | 被哪个 RL 特征/算子使用 | 建议实现 |
|---|---|---|
| `ts_MACD_HIST` | 特征 MACD_HIST | 由已有 ts_MACD_DIF 现算（DIF − signal） |
| `ts_KDJ_D` | 特征 STOCH_D_3 | 由已有 ts_KDJ_K 的 slowd 平滑现算 |
| `ts_BOLL_WIDTH` | 特征 BOLL_WIDTH（bbands_width()） | 由 ts_BOLL_POS 的 (upper−lower)/ma 现算 |
| `ts_SAR_DIST` | 特征 SAR_DIST（sar_dist()） | close − ts_SAR 现值 |

### 3.2 窗口统计/双序列（2 个，成本中等）

| GPU 缺失算子 | 被谁使用 | 建议 |
|---|---|---|
| `ts_Quantile` | 算子 ts_Quantile_10 | 仿 ts_Rank 的窗口实现 |
| `ts_Cov` | 算子 ts_Cov_10（原版 COVARIANCE_10） | 仿已有 t_ts_Corr 的窗口协方差 |

### 3.3 重计算型基类（12 个，AlphaMaster 特征池全量必需，成本高）

`ts_TrendStrength`、`ts_GKVol`、`ts_ParkinsonVol`、`ts_YangZhangVol`、`ts_RSVol`、`ts_RetEntropy`、`ts_KeltnerPos`、`ts_IchimokuKijun`、`ts_IchimokuTenkan`、`ts_SuperTrend`、`ts_Hurst`、`ts_FractalDim`

> 这 12 个正是 GP 在 L3 过滤掉的"复杂估计/多字段强耦合"类（factor_gp.py L125-127），但在 RL 的 65 特征池里是**必含特征叶子**（TREND_STRENGTH_50/GK_VOL/PARKINSON_VOL/YANG_ZHANG_VOL/RS_VOL/RET_ENTROPY_20/KELTNER_POS_20/ICHIMOKU_KIJUN_DEV/ICHIMOKU_TENKAN_DEV/SUPERTREND_DIR/HURST_50/FRACTAL_DIM_30）。

### 3.4 算术/解码写法（4 处）

| 缺失/问题 | 被谁使用 | 处理 |
|---|---|---|
| `neg` 一元取负 | 算子 neg（解码为 `(-{a})`） | 合成 `((-1) * {a})` 即可 GPU 编译 |
| `gate` / `if_gt` 三目 | 算子 gate / if_gt | GPU 编译器仅支持一元/二元 op 节点，需扩展三目节点或收尾时接受回退 |
| `np.abs` 写法 | 算子 max/min 解码 | 改为 `abs`（引擎与 GPU 均支持），一行修复 |

> 注：max/min 若保留 `np.abs` 写法，即使修好上面全部算子，含 max/min 的候选仍会整树回退——**这是成本最低但必做的一个改动**。

### 3.5 特征级覆盖统计（65 特征）

- **可 GPU 编译：49/65**（RET 系/ATR/RVOL/HL_RANGE/VOL_REGIME/DEV/RSI/PRESSURE/AC1/AC2/VOL_RATIO/VOL_Z/PV_CORR/REL_*/VWAP_DEV/BOLL_POS/MFI14/OBV_SLOPE/WILLR/CCI/ROC/TYPICAL_DEV/EMA_RATIO/PRICE_POS_50/DONCHIAN/STOCH_K/AROON_OSC/DMI_ADX/DMI_DIFF/TRIX/PPO/ULT_OSC/RET_ACCEL/AMIHUD/KYLE/CMF/AD_LINE/TRIX_SIGNAL/ROLL_SKEW/ROLL_KURT/CS_RANK_RET5/CS_ZSCORE_RET20 等）
- **含 GPU 缺失算子需回退：16/65**（MACD_HIST/STOCH_D_3/SAR_DIST/BOLL_WIDTH/TREND_STRENGTH_50/GK_VOL/PARKINSON_VOL/YANG_ZHANG_VOL/RS_VOL/HURST_50/FRACTAL_DIM_30/RET_ENTROPY_20/KELTNER_POS_20/ICHIMOKU_KIJUN_DEV/ICHIMOKU_TENKAN_DEV/SUPERTREND_DIR）

---

## 四、回退行为（已核对 factor_gp.py / factor_gpu_evaluator.py）

- **粒度：单树**。`_eval_all`（factor_gp.py L1457）按 `gpu_supported(tree)` 把无缓存的个体拆成 GPU 组 / 回退组，两组同代并发，回退组走进程池或主线程 `evaluate_expression` + **同口径新语义 mean_rank_ic**（L1388-1396）——适应度语义一致，不影响正确性。
- **整批回退**只发生在 `_gpu_ctx is None`（未开/初始化失败）或待求值 < 3 条时。
- 预检放行但编译仍抛错的"非正常路径"会把个体判死（`(None, None)`），正常情况不触发。
- **对 RL 收尾的影响**：候选里只要包含 3.1~3.4 任一函数 → 整棵树回退 CPU。实测收尾 ~320s（80 股×489 天×25 候选，纯 CPU）；GPU 全覆盖后预计 **30~90s（3~10 倍）**。
- 初始 GPU 上下文构建失败会自动整体降级 CPU（不中断流程）。

---

## 五、RL 搜索空间对齐核查（任务三：对齐定义后再查 RL 的算子/字段）

### 5.1 与 AlphaMaster 对齐（已有脚本验证）

- 特征：**65/65 命名完全一致**（顺序与原版 `_FEATURE_DEFS` 一致），映射遵循《AlphaMaster特征算子与因子库映射方案》。
- 算子：65（原版 62 的**语义超集**，62/62 覆盖，另含 cs_Zscore/ts_Log/ts_ArgMax_10 等增量）。
- 已知语义近似（映射方案批准）：MA_DIFF/SLOPE20/OBV_SLOPE/AC1/AC2 特征、CS_SCALE→cs_TransNorm、DECAY→ts_Decay_5。

### 5.2 与 CPU 表达式引擎对齐（冒烟已验证）

- 65 特征表达式全部可 `evaluate_expression` 求值（真实面板冒烟 65/65 存活、无 NaN/Inf）。
- 65 算子解码表达式全部可求值（新算子含解析式 max/min、ts_Shift 延迟）。

### 5.3 与 GPU 表对齐（本审计结论）

- **49/65 特征、约 58/65 算子**可 GPU 编译；
- 26~30 个解码函数名依赖 3.1~3.4 的 22 处缺口 → 收尾开 GPU 时相关候选整树回退 CPU。

### 5.4 影响评估

- 训练环节不受影响（独立 VM，CPU）。
- 收尾环节 GPU 加速收益当前被缺口大幅稀释；补齐 3.1+3.2（6 个）+ 3.4（4 处）后，绝大多数候选可 GPU 编译；补齐 3.3（12 个）后全覆盖。

---

## 六、勘误与一致性标注

- 《AlphaMaster特征算子与因子库映射方案.md》阶段二第 3 步的备注
  「⚠️ GPU 求值器暂未覆盖这些新算子，使用时会回退 CPU 求值（GPU 加速待后续补齐）」
  **已过时**：阶段6.3 已按 GP 搜索空间补齐（TORCH_ARITH/TS/TS_RAW 均已含），该备注已修正并指向本文档。
- GP 搜索空间（L3）与 GPU 表（L2）**已 100% 对齐**；未对齐的仅是 RL 搜索空间（L4）与 GPU 表。
- 本文档所引文件行号以 2026-08-19 工作区状态为准。

---

## 七、结论与行动建议（分级）

| 优先级 | 内容 | 预估收益 | 风险 |
|---|---|---|---|
| P0 | max/min 解码 `np.abs → abs`；neg 合成 `(-1*{a})` | 让含 max/min/neg 的候选可 GPU；一行级改动 | 极低 |
| P1 | GPU 补齐 6 个：ts_MACD_HIST / ts_KDJ_D / ts_BOLL_WIDTH / ts_SAR_DIST / ts_Quantile / ts_Cov | 16 个回退特征减到 12 个；收尾 GPU 命中率大幅提升 | 低（多为已有算子组合） |
| P2 | GPU 补齐 10 个轻-中重计算基类：TrendStrength / GK / Parkinson / YangZhang / RS / RetEntropy / Keltner / Ichimoku×2 / SuperTrend | 收尾基本全覆盖；估计 320s → 60~120s | 中（需逐算子向量化） |
| P3 | GPU 补齐 Hurst / FractalDim（滚动重计算，GPU 化收益最大） | 全覆盖；收尾 320s → 30~90s | 高（实现复杂，建议独立任务） |

> 建议执行顺序：P0 → P1 →（若经常跑小步数短任务）P2 → P3。P2/P3 全部落完后，配合特征张量 LRU 缓存与 use_gpu 开关注入，RL 收尾环节可与 GP 同速。

---

## 八、补齐执行记录（2026-08-19，v2 已落地）

### 8.1 代码改动

| 文件 | 改动 |
|---|---|
| `lib/factor_rl/ops.py` | **P0**：`max/min` 解码 `np.abs→abs`；`neg` 由 `(-x)` 改为 `((-1)*(x))`（GPU 编译器可识别） |
| `lib/factor_gpu_torch.py` | **P1~P3**：新增 18 个 `t_*`（t_ts_MACD_HIST/KDJ_D/BOLL_WIDTH/SAR_DIST/Quantile/Cov/TrendStrength/GKVol/ParkinsonVol/YangZhangVol/RSVol/RetEntropy/KeltnerPos/IchimokuKijun/IchimokuTenkan/SuperTrend/Hurst/FractalDim）+ 三目 `t_gate/t_if_gt`；注册进 TORCH_TS/TORCH_ARITH |
| `lib/factor_gpu_evaluator.py` | compile 支持三元 op 分发；支持 `ts_params` 节点；修复 `_rank_2d` 的 torch 1.11 `argsort(stable)` 兼容性 |
| `lib/factor_gp.py` | `formula_to_tree/_build_call_node` 扩展：`gate/if_gt` 三参 op、10 个命名算术算子（sign/jump/max3/power/signed_log/sqrt/clip/sigmoid/tanh_squash/winsorize，尾部常数折叠）、`ts_params` 节点（ts_MACD_HIST 等多定参时序）+ 树遍历助手同步支持 |

### 8.2 验证结果（合成面板 80 股×300 日，GPU/CPU 数值对照）

- **29/29 全部 corr=1.0 达标**：18 个新算子（含 hurst/gk_vol/parkinson_vol/yang_zhang_vol/rs_vol/trend_strength/ret_entropy/keltner/ichimoku×2/supertrend/fractal_dim/sar_dist/ts_Quantile/ts_Cov/ts_MACD_HIST/ts_KDJ_D/ts_BOLL_WIDTH/bbands_width/VOL_REGIME）+ gate/if_gt（三目）+ RL max/min/neg 解码 + 回归 rsi/macd/bias。max_abs_diff 均 ≤ 2.4e-13，NaN 掩码逐位一致。
- **字符串全链路**：`gate(...)`/`if_gt(...)`（三参函数调用形式）、10 个命名算子、`ts_MACD_HIST(Close,12,26,9)` 等多定参时序，均能被 formula_to_tree 解析 → gpu_supported=True → GPU 编译，结果与 CPU evaluate_expression 一致。
- **GP 解析器回归**：rsi/macd/bias/ts_Corr/ts_MACD_DIF/momentum-shift/sma/ema/cs_Demean/abs/除法/ts_params 往返 全部 OK。
- **端到端**：`factor_gp.oos_recheck(use_gpu=True)` 跑含新算子候选不抛错。

### 8.3 边界与说明

1. **gate/if_gt 三目**：现在可作字符串解析（op 三参）；GP 搜索空间仍不生成（GP_ARITH_UNARY 无三目，模板不支持），仅 RL 收尾路径消费，对 GP 行为零影响。
2. **常量折叠**：`clip(x,-3,3)` 的 `-3`（解析为 `-1*3` 表达式）已折叠为 T_CONST 再入 op 节点。
3. **supertrtrend 递推**：GPU 版为逐 t 循环（与引擎 numpy 递减语义一致，已验证）。
4. **Keltner ewm**：按 pandas `ewm(span, adjust=False)` 递推实现（含 NaN carry），数值一致。
5. **fractal_dim/hurst**：CPU 版的 `max(-1,min(1,v))` NaN 边界特性已显式复刻（NaN→1.0 与引擎一致）。
6. **`_rank_2d` 修复**：torch 1.11 无 `argsort(stable=True)`，改用 `sort(stable=True).indices`，语义一致。

### 8.4 效果

- RL 收尾环节候选公式（含 65 特征池全量叶子 + 65 算子解码）**基本全部可 GPU 编译**，GPU→CPU 整树回退仅剩：任务外生成的非标准表达式（如 np.* 直接调用、比较运算符、缠论/财务类——均不在 RL 解码产物内）。
- 实测收益预期：收尾 320s（纯 CPU）→ GPU 全覆盖约 30~90s。
- 使用方式不变：RL 收尾筛选（oos_recheck/walk_forward_recheck 等）的 `use_gpu` 开关已存在（前端 rlUseGpu），开之即得。