# 因子系统与 QuantGplearn 对齐改进规划（分阶段）

> 文档定位：基于对本地 `third_party/QuantGplearn` 源码与当前因子系统（`lib/factor_gp.py` / `lib/factor_gpu_evaluator.py` / `routes/factor.py`）的逐项对比，梳理三类不一致，并给出分阶段改进规划。本文档只做规划与结论，不含具体代码改动；改动均按"阶段完成后单独评审、独立可回退"推进。

---

## 一、背景与目标

当前因子挖掘系统（GP / RL / LLM-GP）在**搜索空间**上与 QuantGplearn 明显不同（这是有意为之，保留）。但除了搜索空间外，还存在三方面值得审视的差异，可能带来"挖掘结果与评价结果不一致""收尾耗时过长""因子类型支持受限"等问题：

1. **因子类型体系**：QuantGplearn 有 number/category 两类向量 + 类型约束建树；当前系统只有数值型因子，分类/信号型因子尚未进入挖掘管线。
2. **计算口径与流程**：数据组织、parsimony 惩罚、早停机制、是否分段等存在差异，部分需要确认是否需要统一。
3. **收尾评价**：候选精评、去冗余、OOS/WF/permutation、双口径指标等步骤叠加，计算冗长，存在明显可优化空间。

本规划分三个阶段推进，优先级从"收尾提速（见效最快）"到"类型系统扩展（价值最大）"再到"口径统一（收尾兜底）"。

---

## 二、现状调研结论

### 2.1 因子类型体系（方向 1）

**QuantGplearn 侧**（`third_party/QuantGplearn/QuantGplearn/_program.py`、`functions.py`、`genetic.py`）：

- `_Function` 携带 `param_type`（参数可接受 `vector: number/category` 与 `scalar: int/float`）和 `return_type`（`number` / `category`）——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) `_Function.__init__`。
- 建树时按类型约束：`build_program` 依据 `terminal_stack[-1][0]` 的类型决定插入"数值函数 / 分类函数 / 数值向量 / 分类向量 / 常量"，**分类与数值在树上被类型系统隔离**——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) `build_program`。
- 面板执行时按 `function_type` 分组：截面函数按 time 分组、时序函数按 security 分组（`_groupby`）——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) `_groupby`；支持 `category_features`（LabelEncoder 编码后作为分类向量叶子参与进化）——[genetic.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/genetic.py) `fit`。

**当前系统侧**：

- 因子库已有**类别概念**：`factor_library.category`（技术指标 / K线形态 / 财务 / Barra 风格等）、`factor_type`（basic/composite）、`evaluation_type`（technical / technical_ts / signal / financial / none）——[factor_db.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_db.py)。
- **评价层已支持多类型**：
  - `technical`（截面连续型，RankIC 口径）；
  - `technical_ts`（先滚动分位标准化再截面，`ts_rank_normalize`）——[routes/factor.py](file:///e:/jikeAI/code/CASE-AI量化系统/routes/factor.py) 单股/多股管线；
  - `signal`（事件信号，`evaluate_pattern_factor` 命中率/条件收益）——[routes/factor.py](file:///e:/jikeAI/code/CASE-AI量化系统/routes/factor.py) 单股分支；
  - `financial`（财务报告对齐调仓点，`financial_report_rebal_dates`）——[routes/factor.py](file:///e:/jikeAI/code/CASE-AI量化系统/routes/factor.py)；
  - `none`（不可独立评价，明确拒绝）。
- **但挖掘层只有数值因子**：GP 搜索空间 `GP_FIELDS` 全为数值字段，`GP_TS_OPS` / `GP_CS_OPS` / `GP_ARITH_*` 全为数值算子，无 number/category 类型系统、无分类向量叶子、无类型约束建树。

**结论**：类型能力"评价层已具备、挖掘层未接入"。要做的是把 `signal`/`financial` 等类型的**算子与叶子**接入 GP 搜索空间，并引入轻量类型约束避免无效嵌套（如"截面算子直接作为带窗时序算子的内部参数"这类语义混叠）。

### 2.2 树构建流程对比（方向 2 核心：决定因子生成是否与 QuantGplearn 一致）

> 用户强调：方向 2 的核心不是"因子值怎么算"，而是**"树怎么建"**——这决定因子生成机制是否与 QuantGplearn 对齐。按四个子问题逐项对比。

#### 2.2.1 空间构成：底层元素与分类方式是否一致？

| 维度 | QuantGplearn | 当前系统 | 结论 |
|---|---|---|---|
| 终端（叶子） | 字段向量（`X1..Xn`，1-based 特征索引）+ 连续标量常量（`const_range` 默认 (-1,1) 均匀采样） | 字段（`GP_FIELDS`：11 个价量/派生字段，**命名字符串**）+ **离散**常量池 `[0,1,2,3,5,10]`——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) | **不同**：常量 QuantGplearn 连续随机，本系统离散池（有意设计，利于金融语义）；字段本系统有派生字段（IdioRet/Value/TotalRet），QuantGplearn 无 |
| 函数分类方式 | **按返回类型**分类：`number` / `category`（`return_type`），且每参数声明 `param_type`（vector number/category / scalar int/float）——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) | **按算子类别**分类：`arith_binary` / `arith_unary` / `ts` / `ts_raw` / `ts_fixed` / `cs` / `base_leaf`——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `SPACE_L0` | **不同**：QuantGplearn 用"返回类型"分类，本系统用"算子类别"分类；本系统**无类型系统**（所有算子都输出数值面板），即缺少 number/category 隔离 |
| 带窗时序算子 | 以"函数 + 标量 int 参数"形式存在（如 `ts_std(x, d)`，arity=2），窗口作为标量参数在建树时生成 | 以 `T_TS` 节点（`arg` + `window`）承载，窗口从 `WINDOW_POOL=[3,5,10,20,60,120,250]` **离散池**抽取——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) | **不同**：QuantGplearn 窗口连续随机 int（`_as_int_window` 还做上下界裁剪），本系统窗口固定 7 档（有意设计，控制搜索空间） |
| 截面算子 | `cs_rank/cs_zscore/cs_demean/cs_scale/cs_winsorize`，函数声明 `function_type` 分组执行 | `cs_Rank/cs_Demean/cs_Zscore/cs_TransNorm`——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `GP_CS_OPS` | 基本一致（本系统多 cs_TransNorm，少 cs_winsorize/cs_scale） |
| 复合原子（叶子级因子） | 无（叶子只能是字段/常量/分类向量） | **基类叶子** `base_leaf`（L2：rsi(14)/macd()/TALIB_* 等 70+ 个，作原子嵌入树）——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `GP_BASE_LEAF` | **不同**：本系统有"复合因子作叶子"机制，QuantGplearn 没有——这是本系统 L2 空间特有，直接影响树形分布 |

**小结**：空间底层元素**分类方式不同**（返回类型 vs 算子类别）、**常量/窗口取值方式不同**（连续 vs 离散池）、**额外有基类叶子**。这三点决定了即使算子名相同，树的形态分布也不同。

#### 2.2.2 建树方式（初始化算法）是否一致？

| 维度 | QuantGplearn | 当前系统 |
|---|---|---|
| 初始方法 | `init_method` 支持 `half and half`（随机 full/grow）+ `grow` + `full`；`init_depth=(min,max)` 随机取深度——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) `build_program` | `random_tree`：50% grow / 50% full，深度 `randint(2, max_depth)`——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `random_tree` |
| 根节点 | **强制函数节点**（避免退化程序）；随机选 number 函数，排除 ts_std/ts_kurt/ts_atr——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) `build_program` L136-139 | **强制函数节点**（grow 分支 `_function_node`）；`_grow_arg` 禁止纯常数入算子——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) |
| 深度处理 | `self.init_depth = (init_depth[0], init_depth[1]+1)`；用 `terminal_stack` + `depth=len(terminal_stack)` 控制 | 递归传 `max_depth-1`，`_fill_full`/`_grow_arg` 控制 |
| 类型约束建树 | **有**：`build_program` 按 `terminal_stack[-1][0]` 的 param_type 决定插入数值函数/分类函数/数值向量/分类向量/常量，**类型严格匹配**——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) | **无**：`_function_node_skel` 按算子类别权重随机选，子节点槽位可放任意子树（含 cs 算子嵌入 ts 算子内部） |

**小结**：建树框架（half and half + 根强制函数 + 深度控制）**一致**；核心差异是 **QuantGplearn 有类型约束建树、本系统没有**，导致本系统会出现"截面算子直接作为带窗时序算子内部参数"这类 QuantGplearn 类型系统会拒绝的语义混叠组合。

#### 2.2.3 随机生成树"组合方式"是否一致？

| 维度 | QuantGplearn | 当前系统 |
|---|---|---|
| 算子选择概率 | 每个候选函数等概率（`function_dict` 列表随机索引）；受 param_type 过滤——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) `build_program` | **按类别加权**：`kind = rng.choice(["bin"]*len(bin)+["un"]*len(un)+["ts"]*len(ts)+...)`，即每类内部等概率、类别间按数量加权——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `_function_node_skel` |
| 常量/字段选择 | 字段/常量混合随机；常量均匀采样 const_range | `_terminal`：80% 字段 / 20% 常量；`_grow_arg`：深度≥2 时 35% 提前落字段——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) |
| 交叉/变异随机点 | `get_random_subtree`：**函数节点权重 0.9 / 向量叶子 0.1**（Koza 惯例），按类型过滤——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) | `_all_nodes` 后 `rng.choice` **等概率选任意节点**——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `crossover/subtree_mutation` |
| 深度检查 | **无**：crossover/subtree_mutation 只检查 `parent.length_ <= max_length`，不查深度 | **有**：快速检查 + 替换后实测 `tree_depth` 兜底（已修复）——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) |

**小结**：随机组合方式的**概率分布不同**（类别加权 vs 等概率；交叉点 0.9/0.1 vs 等概率）。这影响树的算子构成倾向：本系统时序算子数量多导致 ts 类占比高（与用户观察到的 `ts_PctChange`/`ts_Sum` 高频一致），QuantGplearn 则对函数节点偏好更强。

#### 2.2.4 Warm-Start 引入方式与交互是否一致？

| 维度 | QuantGplearn | 当前系统 |
|---|---|---|
| warm_start 语义 | **继续训练**：`warm_start=True` 时保留已训练 `_programs` 继续跑剩余代数（sklearn 惯例），**不是注入外部因子**——[genetic.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/genetic.py) `fit` | **注入库内因子**：`warm_start_trees`（解析为 dict 树，可 GPU 化）或 `warm_start_formulas`（字符串 `_warm` 原子）按 30% 比例注入初始种群——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `evolve` |
| 交互方式 | 无注入，无"与随机树交换"概念 | **两套交互**：
  - `warm_start_trees`：完整 dict 树，**与随机树同构**，可被交叉/变异拆解、可作 donor 嫁接、参与遗传——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) L1468-1476；
  - `warm_start_formulas`：`_warm` 字符串原子，GP 视作深度 1 叶子，变异/交叉可替换，**不拆基因内部**（与 LLM 基因同机制）——L1485-1486 |
| 约束 | 无（本身无注入） | 注入前按 `max_length` 过滤超限；`formula_parseable_gpu` 白名单（可解析成树 + GPU 化）——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) |

**小结**：**本质不同**——QuantGplearn 的 warm_start 是"续跑"，本系统的 warm_start 是"库内先验注入"。本系统是更贴合金融场景的设计（复用已验证因子作先验），但**注入的树若与随机树结构不一致（字符串 `_warm` 原子 vs dict 树），会在 GPU 编译/交叉拆解上出现语义差异**（此前已修复过：确保 warm 树可解析为与随机生成一致的 dict 结构）。

#### 2.2.5 额外功能对系统的影响评估

> 用户要求评估：本系统从其他案例（AlphaMaster/AutoAlpha/QuantAlpha 等）引入的功能对系统产生的影响。

| 功能 | 来源 | 影响位置 | 与 QuantGplearn 对比 | 影响评估 |
|---|---|---|---|---|
| 多样性权重（Jaccard/PCA-QD） | 阶段3.2/5.2#7（AutoAlpha） | 锦标赛选择：`fitness + gen_div_weight × novelty`——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) | QuantGplearn 无 | **改变选择压力**：会选入更多新颖但非最优个体，种群多样性↑、收敛速度↓。这是本系统**有意偏离** QuantGplearn 的部分，需确认与"对齐 QuantGplearn"的目标是否冲突 |
| 市值/风格中性化 | 阶段4.1/5.2#6（华泰） | 适应度计算：`mean_rank_ic` 前对因子做市值/风格回归取残差——[factor_gpu_evaluator.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_evaluator.py) | QuantGplearn 无 | **改变适应度景观**：中性化后排名因子（规模/风格暴露）被压制，GP 去挖非规模信号。本系统独有、有实证价值（Amount |IC| 0.126→0.044），但**使"与 QuantGplearn 同配置同结果"不可能成立** |
| 三重分段 + 验证段早停 | 阶段5.1（QuantAlpha） | 早停判断迁移到验证段最优——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) | QuantGplearn 无分段、绝对阈值早停 | **改变进化轨迹**：早停基于验证段而非训练段，更抗过拟合，但也意味着"最优代数"定义不同 |
| replacement 防早熟 | 阶段5.2#8（AutoAlpha） | 后代生成：同质个体被变异再生——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) | QuantGplearn 无 | 降低同质化早熟，与多样性权重协同 |
| hierarchical 分层搜索 | 阶段5.2#8（AutoAlpha） | 两次 evolve：粗搜 L0 → 细搜扩算子，粗搜候选作细搜 warm 基因——[routes/factor.py](file:///e:/jikeAI/code/CASE-AI量化系统/routes/factor.py) | QuantGplearn 无 | 增加一次完整进化，**收尾耗时翻倍**（与 2.3 冗杂叠加）；也是收尾变慢的来源之一 |
| permutation/WF/OOS 复核 | 阶段3.1/5.1（QuantAlpha） | 收尾对候选做多段验证——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) | QuantGplearn 无（只有 OOB） | 提高候选稳健性，但**大幅拉长收尾** |

**影响结论**：本系统相对 QuantGplearn 的核心差异**不仅是搜索空间**，还包括：
1. **选择机制**（多样性权重、replacement）——改变"哪些个体被选中繁殖"；
2. **适应度景观**（中性化）——改变"什么是好因子"；
3. **进化轨迹**（验证段早停、hierarchical 两阶段）——改变"何时停、搜几遍"；
4. **收尾**（OOS/WF/permutation/双口径）——改变"最终输出哪些候选"。

这些功能多为**有意增强**（对应已修复的过拟合/规模效应/假相关等真实问题），不应回退；但在"因子生成是否与 QuantGplearn 理想一致"的语境下，它们是**系统性偏离来源**——评估时应区分"树构建机制对齐"（2.2.1~2.2.4，决定生成形态）与"选择/评价增强"（2.2.5，决定生成方向）两个层面。

#### 2.2.6 计算口径与流程（方向 2 补充：数值计算层）

| 维度 | QuantGplearn | 当前系统 | 是否需统一 |
|---|---|---|---|
| 数据组织 | 面板展平 `[n_samples, n_features+3]`（含 security/time 编码列），`_groupby` 分组执行截面/时序 | `{股票: DataFrame}` 面板；CPU 逐股 eval；GPU 用 `[T,N,F]` 张量 | 语义已对齐，**不建议改架构**（GPU 张量化已是更优形态）；仅需保证 CPU/GPU 两路径结果一致（已有 `batch_spearmanr` 与 CPU 对齐样本量阈值） |
| parsimony 惩罚 | `parsimony_coefficient * len(program)`（按节点数） | `coeff * tree_size`（按节点数，解析失败回退旧口径）——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `expr_length_penalty` | 已对齐，无需改 |
| 早停 | **绝对阈值**早停（best 达 `stopping_criteria` 即停） | **相对无改善**早停（验证集连续 N 代未突破，N 默认 5）——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) 主循环 | **保持当前系统**：相对无改善更贴合量化过拟合控制；绝对阈值易被训练段虚高欺骗（已修复的"训练 0.9 / 测试 0.01"问题即此） |
| 分段 | 无分段（train + OOB 袋外监控） | train/val/test 三重分段 + OOS/WF/permutation 复核 | **保留分段**（val 早停 + test 独立复核是有价值的，用户已认可）；但**收尾复核的计算量需精简**（见 2.3） |
| 技术/时序标准化 | 无内置 | `technical_ts` 先滚动分位再截面，且展示层对每个候选**双口径各算一遍**（`route_ts_by_type=False`） | **重点优化**：双口径重复计算是收尾耗时主因之一（见 2.3） |

### 2.3 收尾评价冗杂（方向 3）

当前一条 GP 挖掘链路在收尾阶段依次执行：

1. **候选精评**（`evolve` 收尾）：hall_of_fame + 最后一代 Top-N + 历史各代最优合并 → 对缺展示指标的候选做 **GPU 整树求值补全或 CPU `fitness_expr` 回退**——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) 收尾段；
2. **去冗余**（`dedup_by_corr`）：对候选两两 `evaluate_expression` 算 Spearman 相关，`ortho_mode=True` 时还做**逐截面 OLS 残差 + 增量 IC**——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `dedup_by_corr`；
3. **OOS 复核**（测试段 Top-N）——[factor_gp.py](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py) `oos_recheck`；
4. **WF 多段复核**（`wf_folds` 折滚动）——`walk_forward_recheck`；
5. **permutation 检验**（`perm_n` 次打乱）——`permutation_significance`；
6. **双口径指标**：对每个候选再用 `fitness_expr(route_ts_by_type=False)` 全量算一遍 TS 口径（technical + technical_ts 各算一次）——[routes/factor.py](file:///e:/jikeAI/code/CASE-AI量化系统/routes/factor.py) 收尾段。

**问题**：
- 同一个候选因子值在收尾阶段可能被 `evaluate_expression` / GPU 编译求值多次（精评、去冗余、OOS、WF、permutation、双口径）——**缺少跨步骤的因子面板/指标缓存**；
- `technical_ts` 双口径对**全部候选**重复全量评价，`permutation` 又按 `perm_n`（默认 200）倍放大，二者叠加使收尾耗时远超挖掘本身。

---

## 三、QuantGP 独立复刻页面方案（当前优先方向）

> 用户选定方向：**完全复刻 QuantGplearn 原版 GP 因子挖掘，零扩充**，作为独立页面"QuantGP"运行。数据用本系统行情，结果解析回本系统因子库。中间所有过程（搜索空间/建树/遗传/执行/适应度/收尾）**全部是 QuantGplearn 原版，不做任何改造**。

### 3.1 目标与范围边界

**目标**：在系统内新增一个独立页面"QuantGP（GP 因子挖掘）"，用本系统行情数据跑 QuantGplearn 原版算法，输出能被本系统因子库解析/评价的因子。作为"纯净基线"，与现有 GP 挖掘页面（含中性化/多样性/分段等增强）形成对照，用于验证本系统各增强功能的实际效果。

**范围边界**：
- **算法层**：完全使用 `third_party/QuantGplearn` 原版（`GpuSymbolicTransformer`，GPU 整树张量求值），源码零改动；
- **只做两层接口**：①数据接入层（本系统面板 → QuantGplearn 输入）；②结果解析层（QuantGplearn 产出 → 本系统因子库结构）；
- **不引入**本系统的中性化、多样性权重、分段、双口径、warm-start 等任何增强；
- **后续不做算子/因子扩充**：复刻版价值就是纯净基准，扩充需求应做在现有 GP 挖掘页面，不污染基准实现。

### 3.2 架构

```
templates/quant_gp.html            (新页面, 独立于现有 factor 页面)
  └ routes/quant_gp.py             (新路由, /api/quantgp/*)
       ├ 数据适配器: 本系统 {股票:DataFrame} → long panel [datetime,symbol] + 特征列 + target 列
       ├ GpuSymbolicTransformer.fit_panel(X, target_col=...)   ← 原版调用, 零改造
       └ 结果解析器: _best_programs → 字符串表达式 → 本系统 formula → validate_expression → 入库 factor_library
```

- `app.py` 注册 `quant_gp` 路由与页面；
- 页面参数：种群/代数/深度/目标(objective)/rebal_period/字段选择/设备(cuda/cpu)等，全部透传原版参数，不加额外逻辑。

### 3.3 数据接入层（层 1）

- **输入**：本系统面板 `panel = {code: df(index=日期, columns=行情)}`（`load_daily_kline` 输出，含 open/high/low/close/volume/amount/vwap/turnover 等列）。
- **转换**：每只股票 df 加 `symbol` 列 → 合并 → 设 `[datetime, symbol]` MultiIndex → 提取特征列 → 交给 `TensorPanelData.from_panel_df`。
- **target**：未来收益 = close 前移 `rebal_period` 期的收益率（复用本系统 `prices_panel` 口径），作为 `target_col` 传入（QuantGplearn 需要 target 才能算 IC/ICIR）。
- **字段集**：默认喂基础行情列（open/high/low/close/volume/amount/vwap/turnover）；派生字段（Value/IdioRet/TotalRet）暂不喂入，保持原版字段集纯净。若需扩可后续开关。

### 3.4 结果解析层（层 2）

- QuantGplearn 产出 `_Program` 列表，`generate_my_output()` 得到字符串表达式（特征以 `X{i}` 索引表示，算子名 `ts_*`/`cs_*`/算术 与引擎一致）。
- **解析**：`X{i}` → 映射回本系统字段名；算子名对齐本系统 `factor_engine` 命名（add/sub/mul/div/ts_*/cs_* 已一致）。
- **验证**：`validate_expression` 校验语法 + `evaluate_expression` 试算非空率（≥ 0.2），通过才视为有效候选。
- **入库**：写入 `factor_library`（生成 factor_id、name、formula、category=技术、factor_type、evaluation_type 推断），使候选可在因子库/单因子评价页面被解析和评价。
- **展示**：页面展示候选列表 + 表达式 + fitness/IC 等（来自原版 `_best_scores`）。

### 3.5 依赖与前置

- **已验证**：`GpuSymbolicTransformer` 在 Agu-2 环境（缺 numba/pathos/dill/tables/pyarrow）下**可正常 import**——[functions.py](file:///e:/jikeAI/code/CASE-AI量化系统/third_party/QuantGplearn/QuantGplearn/functions.py) 在 numba 缺失时走纯 Python 回退实现（`nb=None` 分支），GPU 整树求值路径不依赖 pathos。因此 **复刻 GPU 版无需新装任何依赖**。
- CPU 版 `SymbolicTransformer`（genetic.py）才依赖 pathos/joblib——本方案用 GPU 版，天然回避该依赖。
- 需确认：Agu-2 的 torch 版本与本库 `torch_functions.py` 兼容（torch 2.6.0 已通过 import 验证，运行时算子兼容待实测）。

### 3.6 验收标准

- 用一段真实行情面板跑通 QuantGP，产出候选因子（不要求高质量，要求流程完整）；
- 候选公式可被本系统 `evaluate_expression` 执行（非空率 ≥ 0.2），`validate_expression` 通过；
- 入库后可在因子库/单因子评价页面看到并评价（technical 口径）；
- 与现有 GP 挖掘页面在同一数据/参数下可对比，展示"原版 vs 增强"差异。

### 3.7 与"对齐重构"的关系

本方案是**独立基线**，不与现有 GP 挖掘页面冲突，也不作为"融合重构"的前置。后续若要做"完全对齐重构"（把本系统增强回退到 QuantGplearn 原版机制），可直接以本复刻版为参照；若不做，本复刻版本身也是可用的对照工具。用户当前倾向：**先落地复刻版，暂不做对齐重构，也不做算子/因子扩充**。

---

## 四、分阶段规划

> 阶段顺序按"见效快 → 价值大 → 兜底收敛"排列。每个阶段完成后应单独验证（挖掘结果与优化前一致，仅耗时/类型/口径变化），再进入下一阶段。所有阶段均不改动已验证正确的搜索空间算子与遗传算子深度检查。

### 阶段零（P0）：建树机制与 QuantGplearn 对齐评估 —— 明确"生成形态"差距

> 方向 2 核心（2.2.1~2.2.4）揭示：本系统树的**生成形态**与 QuantGplearn 有系统性差异。此阶段**只做对齐评估与可选项切换**，不改默认行为，产出结论后决定哪些差异保留、哪些收敛。

**具体任务**：

1. **空间构成对齐评估**（2.2.1）：
   - 梳理"按算子类别分类" vs "按返回类型分类"的影响：确认是否要引入**轻量类型系统**（number/category 隔离），使截面算子不能直接作为带窗时序算子的内部参数（消除 `ts_PctChange(cs_TransNorm(...), 120)` 这类语义混叠）；
   - 常量池离散化、窗口 7 档离散池：评估是否保留（有意设计）还是向 QuantGplearn 连续取值收敛；**建议保留离散池**（控制搜索空间、金融语义更清晰），仅文档化差异。

2. **随机组合概率对齐评估**（2.2.3）：
   - 对比"类别加权选择" vs "等概率选择"：量化 ts 类算子占比（当前偏高，与 `ts_Sum/ts_PctChange` 高频一致），评估是否需要调整算子选择权重使其分布更均衡；
   - 交叉/变异随机点选择：评估是否引入"函数节点 0.9 / 叶子 0.1"的 Koza 惯例（当前等概率）。

3. **Warm-Start 交互对齐评估**（2.2.4）：
   - 确认 `warm_start_trees`（dict 树，同构可拆解）与 `warm_start_formulas`（`_warm` 原子，不可拆）两套机制并存时的行为一致性；
   - 评估是否统一为"只注入可解析 dict 树"（消除字符串原子在 GPU 编译/交叉拆解上的语义差异），或明确保留 `_warm` 原子作为"整块先验"的语义。

4. **结论产出**：每个差异点标记 `保留（有意设计）/ 收敛（向 QuantGplearn 对齐）/ 待定`，形成一张对齐决策表，作为后续阶段是否改动的依据。

**验收标准**：
- 产出对齐决策表（空间构成/建树/随机组合/warm-start 四维度，每项 `保留/收敛/待定` + 理由）；
- 默认搜索空间与遗传算子**零改动**，现有挖掘结果不受影响。

### 阶段一（P0）：收尾评价提速 —— 消除重复计算

**目标**：在**结果口径完全不变**的前提下，把收尾阶段耗时降下来。

**具体任务**：

1. **引入"候选因子面板/指标缓存"**：
   - 在 `routes/factor.py` 收尾段与 `lib/factor_gp.py` 的收尾函数（`oos_recheck` / `walk_forward_recheck` / `permutation_significance` / `dedup_by_corr`）间，统一接入一个**按 expr_hash 为键的因子面板缓存**（`dict[str, DataFrame]`），同一表达式只 `evaluate_expression` 一次。
   - GPU 路径同样复用 `_compile_cache`（已存在），把"GPU 编译求值"与"CPU 求值"两套结果分开缓存，避免双路径重复。

2. **双口径计算改为按需**：
   - 展示层 `technical`/`technical_ts` 双口径目前对**每个候选**都全量算一遍。改为：仅对 `chosen_type` 为 `technical_ts` 的候选补算 TS 口径；对 `technical` 候选直接复用训练段已有指标（避免 `route_ts_by_type=False` 的全量重算）。
   - 若仍需给 technical 候选展示 TS 口径对比，可改为"复用同一 `fv` 做滚动分位"（一次求值、两次变换），而不是二次全量评价。

3. **permutation 降档**：
   - `perm_n` 默认 200 较大；改为按候选数自适应（如 `perm_n = min(200, max(50, 50 + 10*候选数))`），并在面板缓存基础上复用 `evaluate_expression` 结果（打乱的是收益，因子面板可复用）。
   - 前端暴露 `perm_n` 已支持，保持用户可调。

4. **验证方式**：同一配置下优化前后 `candidates` 内容逐字段一致（fitness/rank_ic/ir/layered/oos_ok/perm 标记），仅耗时下降。

**验收标准**：
- 收尾耗时显著下降（目标 ≥ 50%，以用户同配置实测为准）；
- 候选列表与各项指标与优化前逐字段一致；
- 无任何搜索空间/遗传算子改动。

### 阶段二（P1）：因子类型体系扩展 —— 接入信号/财务类因子

**目标**：让挖掘层具备"分类/信号型因子"能力，与评价层已有类型体系打通，使 GP 能挖掘出 `signal`/`financial` 类因子并正确评价。

**具体任务**：

1. **调研定界（先做）**：
   - 盘点评价层 `evaluate_pattern_factor`（signal）依赖的字段/算子（K线形态 CDL、事件信号），以及 `financial_report_rebal_dates`（财务）依赖的数据源；
   - 确认 GP 行情面板（`load_daily_kline` 输出）能否提供这些输入；不能提供的类型标记为"仅评价不挖掘"。

2. **轻量类型系统**（最小侵入，不照搬 QuantGplearn 全量类型系统）：
   - 为搜索空间增加 `category` 叶子集合（如形态信号、分类字段），并给算子声明"接受 number/category 向量"的类型约束；
   - 在 `random_tree` 与遗传算子（crossover/subtree_mutation/point_mutation）的节点生成处增加类型匹配检查，避免 number/category 混接与"截面算子直接作带窗时序参数"的语义混叠；
   - 复用现有 `validate_expression` 三道闸扩展类型校验。

3. **评价管线打通**：
   - 挖掘产出的候选带 `evaluation_type` 标签（沿用评价层 `classify_factor_type`），收尾评价按标签路由到 `technical/technical_ts/signal/financial` 对应管线；
   - 多因子分析合成时，对 `signal` 类型采用事件信号合成（或明确降级为不参与合成），避免数值/信号混算。

4. **风险控制**：
   - 类型系统改动集中在 `lib/factor_gp.py` 的 `random_tree` / 遗传算子与 `SPACE_L*` 定义；不触碰已验证的数值因子路径（默认空间不启用类型约束时行为与现一致）。

**验收标准**：
- 搜索空间出现新 `category` 类型后，数值因子挖掘结果与未开启类型扩展时一致（默认开关关闭）；
- 启用后可挖出 signal 类候选，且收尾评价走对管线（命中率/条件收益），展示与单因子评价口径一致。

### 阶段三（P1/P2）：计算口径与流程统一 —— 收尾兜底

**目标**：把 2.2 中"建议保留但需要确认"的项收敛成明确约定，并做最后的边界清理。

**具体任务**：

1. **CPU / GPU 双路径口径回归**：
   - 用一组固定表达式在 CPU（`fitness_expr`）与 GPU（`mean_rank_ic`）两侧跑出指标，逐项核对 `rank_ic_mean` / `rank_ic_ir` / `layered` / `samples`，确认阈值（样本量 ≥ 30、常数截面置 NaN、非空率 ≥ 0.2）完全一致，输出一份口径对照结论入文档。

2. **早停/分段策略文档化**：
   - 把"相对无改善早停（验证集）+ 三重分段 + OOS/WF/permutation"的取舍写入本规划附录（保持现状，不降级），避免后续误改成绝对阈值早停/去掉分段。

3. **收尾步骤统一调度**：
   - 把阶段一的缓存机制固化为独立模块（如 `lib/factor_tail_cache.py`），`oos_recheck` / `walk_forward_recheck` / `permutation_significance` / `dedup_by_corr` 统一走缓存接口；
   - 收尾各步骤的开关（wf_folds / perm_n / corr_thresh / ortho_mode）保持前端可调，默认值在阶段一结论基础上重定。

**验收标准**：
- CPU/GPU 口径对照表入文档，无残差；
- 收尾模块化后运行稳定，且不再出现"同一表达式被重复求值"；
- 早停/分段策略有明确文档说明。

---

## 五、风险与取舍

| 项 | 取舍 | 说明 |
|---|---|---|
| 数据组织统一 | **不改** | GPU `[T,N,F]` 张量化是更优形态，改回展平/groupby 属倒退；只需保证双路径口径一致（阶段三） |
| 早停机制 | **保持相对无改善** | 绝对阈值早停对训练段虚高敏感，与已修复的过拟合问题冲突 |
| 分段 | **保留** | val 早停 + test 独立复核有价值；优化点是收尾复核计算量而非去掉分段 |
| 类型系统 | **轻量引入** | 不照搬 QuantGplearn 全量 number/category 系统（侵入大）；只加最小类型约束 + 分类叶子 |
| 双口径 | **按需计算** | 保留 technical/technical_ts 两种口径的展示能力，但改为单次求值两次变换 |
| QuantGP 复刻版 | **零扩充、独立基线** | 算法层原版不动；只做数据接入/结果解析两层接口；后续不做算子/因子扩充，扩充走现有 GP 页面 |

---

## 六、附录：QuantGplearn 关键代码位置（供复查）

- 类型系统与类型约束建树：`QuantGplearn/functions.py`（`_Function` / `make_function` / `build_program`）
- 分组执行：`QuantGplearn/functions.py`（`_groupby`）
- 分类特征：`QuantGplearn/genetic.py`（`fit` 中 `category_features` / LabelEncoder）
- 遗传算子（不含深度检查）：`QuantGplearn/_program.py`（`crossover` / `subtree_mutation` / `hoist_mutation` / `point_mutation`）
- 早停（绝对阈值）：`QuantGplearn/genetic.py`（`fit` 中 `stopping_criteria`）
- GPU 适应度：`QuantGplearn/tensor_fitness.py`（`normalize_by_day` / `batch_spearmanr` / `mean_rank_ic` / `rank_icir` / `long_short_sharpe`）
- 当前系统对应实现：`lib/factor_gpu_evaluator.py`（已对齐）
