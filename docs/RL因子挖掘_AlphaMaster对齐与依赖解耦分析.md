# RL 因子挖掘：AlphaMaster 对齐、依赖/耦合分析与增量功能

> 生成日期：2026-08-22  
> 适用范围：`CASE-AI量化系统` 的 RL 因子挖掘子页面  
> 参考文档：
> - `docs/因子挖掘RL引擎实施方案.md`
> - `docs/RL因子挖掘_GPU算子覆盖审计与搜索空间对齐.md`
> - `docs/AlphaMaster特征算子与因子库映射方案.md`
> - 原版代码：`third_party/AlphaMaster-main/model_core/*`

---

## 一、与 AlphaMaster 的对齐情况

### 1.1 总体结论

RL 因子挖掘的主体算法链路与原版 AlphaMaster **高度一致**，核心机制包括：

- token 词表 + StackVM
- ConstrainedSampler 约束采样
- AlphaGPT（Looped Transformer）
- REINFORCE 策略梯度
- Elite Replay
- 熵坍塌检测/重启
- Checkpoint 断点续训
- Island 多岛迁移

但严格来说，**“唯一差异是单股票 vs 股票池”并不完全准确**。除业务口径外，还存在若干有意的适配差异，以及少量需要后续逐位对齐的微观实现差异。

### 1.2 有意的适配差异

| 维度 | AlphaMaster 原版 | 当前 RL 页面 |
|---|---|---|
| 数据维度 | 单标的或多标的，常以单标的择时为主 | 股票池截面选股，`[N, 股票数, T]` |
| 目标收益 | `log(open[t+2]/open[t+1])` | `close[t+rebal]/close[t]-1`，默认 5 日 |
| 评价/奖励 | MT5Backtest：组合 Sortino/Calmar/时序 IC/换手/成本 | 截面 RankIC + ICIR + 分层单调性 |
| 特征来源 | AlphaMaster 自带的 65 个特征计算 | 65 个特征映射为本系统表达式，通过 `evaluate_expression` 计算 |
| 算子词表 | 62 个算子 | 66 个算子，语义超集 |
| 训练后输出 | 保存 best strategy token JSON | 解码为表达式，并做 OOS/WF/置换检验/去冗余/候选入库 |
| 工程形态 | 独立 Web 控制台 | 嵌入现有因子挖掘页，SSE 流式交互 |

### 1.3 需要后续逐位对齐的微观差异

如果目标是“完全复刻、逐位对齐”，以下差异需要逐一确认和修正：

1. **`ts_Rank` 语义不同**
   - AlphaMaster：`TS_RANK` = 当前值在窗口内“严格小于当前值的比例”，值域 `[0,1)`。
   - 本地：`ts_Rank_*` 使用 argsort 排名 `rank/(d-1)`，最高值会得到 1.0。
   - 本地另有 `ts_Quantile_10` 更接近原版 `TS_RANK` 的严格小于比例语义。

2. **感染链在特征 token 处的处理不同**
   - AlphaMaster：特征 token 不改变感染状态。
   - 本地：特征 token 会把感染链重置为 0。
   - 该差异会影响 ConstrainedSampler 的后续采样约束。

3. **Elite Replay 采样权重公式不同**
   - AlphaMaster：使用 `2.0 ** (normalized / temp)`。
   - 本地：使用 `np.exp(normalized / 0.5)`。
   - 两者等价底数不同，会导致精英池采样偏好有差异。

4. **Walk-Forward 折叠构造细节不同**
   - 原版 `_build_walk_forward_folds` 与本地 `build_walk_forward_folds` 在折数、区间划分公式上不完全相同。

5. **单标的时序标准化细节不同**
   - 原版 `_normalize_output` 的滚动 std 使用 `torch.std` 默认 `unbiased=True`。
   - 本地使用 `unbiased=False`。
   - 对股票池 N>1 的截面场景影响不大，但单标的/择时模式会不一致。

6. **并行评估缺失**
   - 原版有 ThreadPoolExecutor 并行公式评估。
   - 本地当前训练循环为串行评估，属于性能差异，不影响逻辑，但若要完全复刻也需要补上。

---

## 二、RL 页面是否依赖 GP / LLM 增强 GP？

### 2.1 结论

**RL 算法本身是独立的，不依赖 GP 因子挖掘引擎，也不依赖 LLM 增强 GP 引擎。**

代码证据：

- `lib/factor_rl/` 下没有任何对 `factor_llm_gp` 的引用。
- `lib/factor_rl/` 下没有调用 `factor_gp.evolve()`，也没有调用 `run_llm_gp_evolution()`。
- `/mine_rl/stream` 是独立路由，不走 GP / LLM-GP 的 stream 路由。
- 前端 RL 子 Tab 的 `runRl()` 只调用 `/api/factor/mine_rl/stream`。

### 2.2 确实存在的公共函数依赖

RL 的 `pipeline.py` 在**训练后筛选阶段**使用了 `lib/factor_gp.py` 中的公共函数：

- `split_train_test_dates`
- `trim_panel_to_dates`
- `oos_recheck`
- `walk_forward_recheck`
- `permutation_significance`
- `dedup_by_corr`

这些函数虽然位于 `factor_gp.py`，但它们属于**因子评价/筛选公共能力**，不是 GP 进化引擎本身。

此外，RL 还依赖以下共享底层设施：

- `lib/factor_engine.evaluate_expression`：RL 特征计算和候选表达式求值。
- `lib/factor_evaluator.get_pool_stocks / get_active_stock_pool`：股票池加载。
- `lib/backtest_data.load_daily_kline`：行情加载。
- `lib/factor_mining_jobs`：任务状态管理。
- `lib/factor_gpu_evaluator / factor_gpu_torch`：收尾筛选的 GPU 求值。

### 2.3 如果屏蔽或删除 GP / LLM 页面，会发生什么？

| 操作 | 对 RL 的影响 |
|---|---|
| 只隐藏 GP / LLM 页面入口、路由，但保留代码文件 | **无影响**，RL 可以正常运行 |
| 直接删除 `factor_llm_gp.py` | **无影响**，RL 不引用它 |
| 直接删除 `factor_gp.py` | **会影响 RL 收尾筛选**，因为 `pipeline.py` 从 `factor_gp.py` 导入了 OOS/WF/permutation/dedup 等公共函数 |
| 删除 `factor_engine.py` | **会影响 RL 训练**，因为 RL 特征表达式要通过 `evaluate_expression` 计算 |
| 删除 `factor_db.py` 或清空因子库 | **不影响 RL 训练与候选生成**；只影响“候选入库”到因子库的保存动作 |
| 删除 `factor_evaluator.py` / `backtest_data.py` | **会影响 RL 数据加载**，这些是核心数据层 |

所以准确表述是：

> **RL 不依赖 GP 挖掘引擎、不依赖 LLM 挖掘引擎；但它依赖 `factor_gp.py` 中的公共筛选工具函数。如果未来要彻底解耦，需要把这些公共函数从 `factor_gp.py` 下沉到独立模块，例如 `factor_screening.py`。**

---

## 三、RL 训练是否依赖因子库内容和 GP 搜索空间？

### 3.1 结论

**RL 训练过程本身不依赖因子库数据内容，也不依赖 GP 搜索空间。**

依据：

- `lib/factor_rl/features.py` 中的 65 个特征是**硬编码在 RL 包内**的 `FEATURE_SPECS`，映射为本系统表达式。
- `lib/factor_rl/ops.py` 中的 66 个算子是**RL 自有的算子注册表**。
- `lib/factor_rl/vocab.py` 从 `FEATURE_NAMES + OPERATOR_NAMES` 派生词表，不读取 GP 的 `GP_FIELDS / GP_BASE_LEAF / SPACE_LEVELS`。
- `lib/factor_rl/trainer.py` 训练时只使用：
  - 自己的 `AlphaGPT`
  - 自己的 `StackVM`
  - 自己的 `ConstrainedSampler`
  - 自己的 `RLBacktest`
  - `FeatureEngine` 产出的特征张量
- RL 包内没有直接查询 `factor_library / factor_base / factor_db`。
- RL 包内没有引用 GP 搜索空间常量。

### 3.2 “训练后映射到本地空间”的依赖

训练结束后，RL 需要把 token 公式解码为本系统表达式：

- 解码映射表在 `lib/factor_rl/ops.py` 的 `DECODE_MAP` 中。
- 特征 token 到本地表达式的映射在 `lib/factor_rl/features.py` 的 `FEATURE_EXPRS` 中。
- 所以“token → 本地表达式”的映射是 **RL 包自包含**的，不依赖 GP/LLM 页面。

但映射后的表达式，在收尾筛选阶段会进入共享评价链路：

- 使用 `lib/factor_engine.evaluate_expression` 求值。
- 使用 `lib/factor_gp.oos_recheck / walk_forward_recheck / permutation_significance / dedup_by_corr` 做筛选。

因此：

> RL 的训练和内部搜索空间是独立的；  
> RL 的收尾筛选复用了系统公共评价/去冗余设施。  
> 这属于“共享公共服务”，不是“依赖 GP 页面引擎”。

---

## 四、当前 RL 页面相对原版 AlphaMaster 的增量功能

### 4.1 业务层

- 股票池截面选股，替代单标的择时。
- 支持行业/板块/概念/自定义股票池。
- 候选因子可直接入库因子库。
- 使用截面 RankIC 系作为主奖励。

### 4.2 训练/筛选流水线

- 训练后 OOS 复核。
- Walk-Forward 复核。
- 置换显著性检验。
- 低相关去冗余。
- Top-N 候选排序。
- 更安全的断点续训：超参指纹 + 数据域指纹校验。

### 4.3 工程/交互

- SSE 流式事件：`heartbeat / progress / restart / elite / done / error`。
- 前端训练曲线实时绘制。
- 前端熵坍塌重启日志。
- 参数自动保存/恢复。
- 候选结果展示与入库。
- GPU 收尾求值支持。

### 4.4 搜索空间/算子

- 原版 AlphaMaster：62 个算子。
- 当前 RL：66 个算子，属于语义超集。
- 新增/扩展典型算子：
  - `cs_Zscore`
  - `cs_Scale`（用于严格对齐原版 `CS_SCALE`）
  - `ts_Log`
  - `ts_ArgMax_10`
  - `ts_ArgMin_10`
  - 本系统风格 `ts_*` / `cs_*` 映射算子

---

## 五、后续行动建议

1. **逐位对齐清单**
   - 对齐 `ts_Rank` 语义。
   - 确认并统一感染链在特征 token 处的行为。
   - 统一 Elite Replay 采样权重公式。
   - 对齐 Walk-Forward 折叠构造。
   - 对齐单标的滚动标准化 `unbiased` 参数。
   - 可选：补回并行公式评估。

2. **解耦建议**
   - 将 `split_train_test_dates / trim_panel_to_dates / oos_recheck / walk_forward_recheck / permutation_significance / dedup_by_corr` 从 `factor_gp.py` 抽到独立公共模块。
   - 让 `lib/factor_rl` 只依赖公共评价模块，不依赖 GP 模块文件。
   - 这样即使后续删除 GP 页面或 GP 引擎，RL 仍可独立运行。

3. **验证方式**
   - 用同一批公式，在 RL 的 StackVM 与原版 StackVM 上做数值对照。
   - 用相同 `random_state` 跑小规模训练，对比 token 分布、精英池、loss 曲线。
   - 对每个算子做 GPU/CPU/原版三方数值对照。

---

## 六、搜索空间超集与增量必要性分析

### 6.1 当前搜索空间相对 AlphaMaster 的关系

**特征：65 = 65，不是超集，而是 1:1 映射。**

- 本地 `FEATURE_NAMES` 与原版 `FEATURE_NAMES` 完全同名，都是 65 个。
- 但部分特征表达式是本地近似，例如 `MA_DIFF`、`SLOPE20`、`OBV_SLOPE`、`AC1/AC2`、`CS_SCALE` 等。
- 因此特征层面没有“新增特征”，只有“同名的本地化实现”。

**算子：66 > 62，是超集。**

- 原版 62 个算子都有本地对应实现（含本次为对齐 `CS_SCALE` 新增的 `cs_Scale`）。
- 本地额外增加了 4 个算子：
  - `ts_Log`
  - `ts_ArgMax_10`
  - `ts_ArgMin_10`
  - `cs_Zscore`

### 6.2 增量算子是否会影响原有部分？

**不会修改原有 62 个算子的执行函数。**

每个算子在 `OPERATOR_REGISTRY` 中是独立注册的，新增算子不会覆盖或改变原算子的实现。

但会带来以下间接影响：

1. **词表大小和版本变化**
   - 原版词表：65 特征 + 62 算子 = 127。
   - 本地词表：65 特征 + 65 算子 = 130。
   - `VOCAB_VERSION` 会不同，旧 checkpoint / 原版 checkpoint 无法直接复用。

2. **token id 顺序变化**
   - 本地算子顺序与原版不完全一致，因此即使保留 62 个算子，token id 也未必与原版一致。
   - 如果要逐位对齐，不仅要去掉 4 个增量算子，还需要让 62 个算子的顺序与原版 `OPS_CONFIG` 完全一致。

3. **搜索空间扩大**
   - 新算子会进入 RL 可采样空间，可能影响策略分布和最终挖出的公式。
   - 但不会让原有公式“失效”，原有 62 个算子能表达的公式仍然能表达。

### 6.3 是否有必要增量？

**如果目标是“完全复刻 AlphaMaster”：不必要，甚至不建议保留。**

- 原版 62 个算子已经是一个完整可用的搜索空间。
- 4 个增量算子不属于 AlphaMaster 原始定义。
- 保留它们会让“完全复刻”变得不严格。

**如果目标是“本地 A 股选股增强”：有一定价值。**

- `cs_Zscore`：符合本地截面选股评价体系，和 `cs_Rank` / `cs_Demean` 是同一族。
- `ts_Log`：基础变换，原版没有，但对数值分布处理有用。
- `ts_ArgMax_10` / `ts_ArgMin_10`：是原版 `TS_ARG_MAX_5` / `TS_ARG_MIN_5` 的窗口扩展。

建议：

> 默认训练使用“原版 62 算子模式”，严格对齐 AlphaMaster；  
> 4 个增量算子作为“本地扩展模式”可选开启，不污染默认复刻结果。

### 6.4 如果不增量会怎么样？

- 搜索空间回到原版 62 算子，词表大小变为 127。
- 更容易和 AlphaMaster 做逐位对齐。
- checkpoint / 词表版本可以更接近原版。
- 本地 RL 仍然完整可用，因为原版 62 个算子本身就是完整搜索空间。
- 代价是少了 4 个本地化算子，但不会影响“因子挖掘”这一核心能力。

### 6.5 如果增量，增量和原本的形式逻辑是否一致？

**形式一致：**

- 都是 RPN token 表示。
- 都有明确的 arity。
- 都走 StackVM 执行。
- 都满足 `[N, T] -> [N, T]` 张量契约。
- 都能通过 `DECODE_MAP` 解码成本地表达式。

**逻辑上属于原算子族的自然扩展：**

- `ts_ArgMax_10` / `ts_ArgMin_10`：原版只有 5 日窗口，扩展 10 日窗口，逻辑一致。
- `cs_Zscore`：原版有 `CS_NEUTRALIZE` / `CS_RANK` / `CS_SCALE`，新增 `cs_Zscore` 属于截面标准化族，逻辑一致。
- `ts_Log`：原版有 `SIGNED_LOG`，新增 `ts_Log` 是更直接的对数变换，虽非原版，但形式一致。

**但严格说：**

> 增量部分不是 AlphaMaster 原始内容。  
> 如果“完全复刻”是硬标准，它们应被移除或默认关闭。  
> 另外，当前真正需要优先对齐的不是这 4 个增量，而是 62 个算子中已有的微观差异：
> - `ts_Rank` 语义
> - `DECAY` / `TS_DECAY_EXP_5` 的本地近似
> - `JUMP` warm-up 行为
> - 感染链在特征 token 处的行为
> - `_normalize_output` 的 `unbiased` 参数
> - Walk-Forward 折叠构造
> - Elite Replay 采样权重公式

---

## 七、已执行的逐位对齐修改（2026-08-22）

> 以下修改已落到代码中，目标是与 AlphaMaster 原版逐位对齐。

### 7.1 已修改文件

| 文件 | 修改内容 |
|---|---|
| `lib/factor_rl/ops.py` | `ts_Rank` 改为严格小于比例；`ts_Std/ts_Zscore/ts_Skew` 对齐原版公式；`JUMP` 补 warm-up；`SIGMOID` 改为 `2*sigmoid-1`；`WINSORIZE` 改为 20 期滚动分位裁剪；`DECAY`/`TS_DECAY_EXP_5` 对齐原版实现；`POWER` 补 clamp；新增 `cs_Scale` 对齐原版 `CS_SCALE` |
| `lib/factor_rl/vm.py` | 单标的滚动标准化 `unbiased` 与原版一致；感染链校验中特征 token 不再重置感染状态 |
| `lib/factor_rl/sampler.py` | `update_infection` 中特征 token 不再重置感染状态，与原版一致 |
| `lib/factor_rl/trainer.py` | Elite Replay 采样权重改为原版 `2.0 ** (norm / temp)` |
| `lib/factor_rl/backtest.py` | Walk-Forward 折叠构造逐位对齐原版 `_build_walk_forward_folds` |

### 7.2 影响说明

- 算子数从 65 增至 66：新增 `cs_Scale` 用于严格对齐原版 `CS_SCALE`。
- 词表版本因此变化为 `vb60538909c71`，旧 checkpoint 不兼容属于预期；新训练可正常生成新 checkpoint。
- 增量算子仍保留 4 个：`ts_Log`、`ts_ArgMax_10`、`ts_ArgMin_10`、`cs_Zscore`。
- 本次先处理了已列出的微观差异；后续仍需验证：
  - RL 训练 smoke 测试。
  - 算子 GPU/CPU/原版三方数值对照。
  - 候选解码后表达式与 StackVM 数值一致性（特别是 warm-up 期 NaN/0 语义）。

### 7.3 本次未处理的项

- **并行公式评估**：原版有 ThreadPoolExecutor，本地仍为串行训练。这是性能差异，不影响数值/逻辑；如需完全一致可后续补。
- **候选解码后与 StackVM 的数值一致性**：本地训练用 StackVM，收尾/入库用 `evaluate_expression` 解码表达式。两者在 warm-up 期以及部分算子（如 `winsorize`、`sigmoid`、滚动窗口 zero-padding）上仍可能存在差异。这属于“本地表达式引擎对齐”问题，建议作为独立任务处理。

---

## 八、第二轮修复：并行评估与解码一致性（2026-08-22）

### 8.1 并行公式评估

- `lib/factor_rl/trainer.py` 已实现 `ThreadPoolExecutor` 并行公式评估。
- 默认启用 `parallel_eval=True`，线程数默认 `min(cpu_count, 8)`。
- `_eval_formula_task` 使用只读的 `StackVM/RLBacktest` 和 `factor_pool` 快照，线程安全。
- 与原版 AlphaMaster 的并行评估机制对齐。

### 8.2 解码/最终评估一致性

发现并修复了一个关键功能问题：

- RL 训练时，特征 token 使用 `FeatureEngine` 计算并经过 **robust 归一化**（median/MAD, clip ±5, warm-up 0）。
- 但旧版 `_decode_formula` 解码时直接使用原始特征表达式：
  - `RET -> returns(1)`
  - 没有套 robust 归一化。
- 导致：
  - 训练时 StackVM 输入的是归一化特征；
  - 最终评估/入库时 `evaluate_expression` 计算的是未归一化特征；
  - 两者取值不一致。

已修复：

- `lib/factor_engine.py` 新增 `ts_RobustNorm`，与 RL `FeatureEngine._robust_norm` 使用完全相同的 torch 实现。
- `lib/factor_rl/features.py` 新增 `FEATURE_DECODE_EXPRS`：
  - 例如 `RET -> ts_RobustNorm(returns(1), 200)`
- `lib/factor_rl/pipeline.py` 的 `_decode_formula` 改用 `FEATURE_DECODE_EXPRS`。
- 这样最终评估和入库表达式会先做 robust 归一化，再进入算子计算，与 RL 训练取值一致。

### 8.3 其他解码一致性修复

- `sigmoid`
  - RL StackVM 现在是 `2*sigmoid(x)-1`。
  - 新增 `sigmoid_squash`，`DECODE_MAP` 改用 `sigmoid_squash`。
- `winsorize`
  - RL StackVM 现在是 20 期滚动分位裁剪。
  - 新增 `ts_Winsorize`，`DECODE_MAP` 改用 `ts_Winsorize({a}, 20)`。
- `cs_Scale`
  - RL 内部新增 `cs_Scale`（min-max）。
  - 由于原系统 `cs_Scale` 是 L1 归一化，不能直接复用。
  - 新增 `cs_MinMaxScale` 作为 RL 专用 min-max 缩放，`DECODE_MAP` 改用 `cs_MinMaxScale`。

### 8.4 验证

- `ts_RobustNorm` 与 `FeatureEngine._robust_norm` 数值对照：`max_abs_diff = 0.0`。
- 解码后的 `sigmoid / winsorize / cs_Scale / ts_Decay_5 / ts_DecayExp_5` 表达式均通过 `validate_expression`。
- 并行评估小规模 smoke 训练通过。

---

## 九、端到端测试结果（2026-08-22）

### 9.1 测试方式

- 启动新实例：`python app.py --port 18090 --no-auto-port`
- 使用真实数据库股票池 10 只股票，日期区间 2023-01-01 ~ 2024-12-31
- 构造 RL 公式 token：
  - `RET ts_Mean_5`
  - `RET RET5 div`
- 分别：
  1. 用 `FeatureEngine + StackVM` 计算 RL 训练侧因子值；
  2. 用 `_decode_formula` 解码为入库表达式；
  3. 通过 `POST /api/factor/save` 保存到因子库；
  4. 通过 `calc_factor` 重新计算入库后的因子值；
  5. 对比两侧数值。

### 9.2 测试结论

| 公式 | RL 训练侧 | 入库后 calc_factor | 最大绝对误差 |
|---|---|---|---|
| `ts_Mean_5(RET)` | 10×484 张量 | 10×484 张量 | 0.0 |
| `RET / RET5` | 10×484 张量 | 10×484 张量 | 0.0 |

- 保存接口：`POST /api/factor/save` 返回成功，自动解析 `base_id=returns`、`factor_type=technical`。
- 试算接口：`POST /api/factor/trial` 返回 `ok=true`。
- 删除接口：测试后已清理因子。

### 9.3 覆盖情况

- 对全部一元/二元/三元 RL 算子做了合成面板数值对照，除已修复项外，当前最大误差均 < 1e-4。
- 特别修复：
  - `ts_ShiftZero`：解决 `ts_Shift` 在 warm-up 期产生 NaN 与 StackVM 左侧补 0 不一致的问题。
  - `ts_RL*` 系列：把 RL StackVM 的时序/截面算子语义完整映射到表达式引擎。
  - `cs_RankRL / cs_ZscoreRL / cs_TransNormRL`：解决截面算子在 all-zero warm-up 行上的 NaN/排名差异。
  - `div`：解码为 `((a)/((b)+1e-6))`，与 StackVM 安全除法一致。

---

## 十、结构重构第一阶段（2026-08-22）

### 10.1 已完成

1. **新增 `lib/factor_screening.py`**
   - 从 `factor_gp.py` 抽出纯公共函数：
     - `split_train_test_dates`
     - `trim_panel_to_dates`
   - `factor_gp.py` 保留对外兼容，改为从 `factor_screening.py` 导入。
   - `lib/factor_rl/pipeline.py` 改为从 `factor_screening.py` 导入这两个函数。

2. **新增 `routes/factor_common.py`**
   - 抽出路由公共工具：
     - `_json_safe`
     - `_json_safe_response`
   - `routes/factor.py` 改为从 `factor_common.py` 导入。

3. **新增 `routes/factor_rl.py`**
   - 把 `/mine_rl/stream` 从 `routes/factor.py` 独立出来。
   - `app.py` 挂载 `factor_rl.router`，路径仍为 `/api/factor/mine_rl/stream`。
   - 已验证：
     - `/api/factor/categories` 正常
     - `/api/factor/mine_rl/stream` 在 OpenAPI 中正常出现

### 10.2 效果

- RL 挖掘的后端入口已经从“所有页面共用的 `factor.py`”中拆出。
- RL 不再直接 import `factor_gp.py` 中的 `split_train_test_dates / trim_panel_to_dates`。
- 但 RL 仍会通过 `factor_gp.py` 使用 `oos_recheck / walk_forward_recheck / permutation_significance / dedup_by_corr`，这些是下一阶段需要继续抽到 `factor_screening.py` 的函数。

### 10.3 后续建议

- 继续把 `oos_recheck`、`walk_forward_recheck`、`permutation_significance`、`dedup_by_corr` 从 `factor_gp.py` 迁移到 `factor_screening.py`。
- 继续把 `routes/factor.py` 拆分为：
  - `routes/factor_library.py`
  - `routes/factor_construction.py`
  - `routes/factor_evaluation.py`
  - `routes/factor_multifactor.py`
  - `routes/factor_mining/*.py`
- 继续把 `templates/factor.html` 拆分为：
  - `templates/factor/library.html`
  - `templates/factor/construction.html`
  - `templates/factor/evaluation.html`
  - `templates/factor/mining/gp.html`
  - `templates/factor/mining/rl.html`
  - `templates/factor/mining/llm_gp.html`
  - `templates/factor/mining/svd.html`
  - `templates/factor/mining/ml.html`
