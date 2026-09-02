# QuantGP 复刻页面增强功能梳理

> 目标：以复刻 quantgp 页面（基于原版 GpuSymbolicTransformer，位于 third_party/QuantGplearn）为基础，
> 参考本系统自研 GP 页面（lib/factor_gp.py + factor.html 的 GP 子Tab）的附加功能，逐项评估可迁移性。
> 原则：新增功能一律做成**可配置项**（页面参数 + 路由透传），默认值对齐原版，不固定写死；尽量不改动第三方源码。

---

## 0. 三个关键疑问的澄清（先厘清事实，再谈功能）

### 0.1 标准化 / 中性化，原版到底内置了什么？

| 能力 | 原版 QuantGplearn | 自研 GP 页面 |
|---|---|---|
| 标准化 | 有：`normalize=True`（**默认开启**），对每个候选因子做**逐日横截面 z-score**（`normalize_by_day`：每个交易日所有股票减当日均值、除当日标准差）后再算 IC。代码：`evaluator.py` 的 `ProgramEvaluator`。 | 有：`gpUseTsNorm` + `gpTsNormWindow`，是**时序滚动标准化**（对每只股票按历史窗口做分位/z-score），两者**不是一回事**。 |
| 风格/市值中性化 | **没有**。全库无 neutral/market_cap/style 残差化预处理；只有 `cs_demean` 这个**函数算子**（表达式内部可调，属于函数集）和回测 docstring 里的 "dollar-neutral"（指多空头寸中性，非风格中性化）。 | 有：`gpMarketcapNeutralize`、`gpNeutralizeStyles`、`gpOrthogonalize`，用 `_panel_residualize`（numpy lstsq 残差化）。原版完全没有此能力。 |

结论：**标准化内置了一部分（截面 z-score），风格中性化原版没有**。截面 z-score 属 C 档（透传开关即可）；风格中性化若要做属 A/B 档（需外部后处理或改求值）——复刻页已移除中性化（理由见 2.5），自研页面保留（训练内，`gpMarketcapNeutralize`/`gpNeutralizeStyles`）。

### 0.2 为什么原版没有 walk-forward？它不是"默认该做的"吗？

- walk-forward 严格说**不是后处理**，而是"**多次 fit 的组织方式**"：滚动窗口（前段 fit、后段验证、窗口前移重复）。
- 原版 quantgplearn 是**通用 GPU 符号回归库**（对标 sklearn 的 SymbolicTransformer）：只做"给一份面板 → 进化出因子"，`fit_panel` 一次阻塞跑完整个训练循环（`_fit_tensor`），不绑定金融时序验证方法论。
- 类比：sklearn 的模型不带 `cross_val_score`，交叉验证在 `model_selection` 里，属于**调用方职责**。所以原版"没做"是**刻意的通用性设计，不是遗漏**。
- 你在自研页面做 `walk_forward_recheck`，正是在调用层补上了这个"金融里默认该做的验证步骤"。复刻页面要加，也是在 `mine_quantgp` 外层做滚动循环 + 用 `transform_panel(X_test)` 算验证表现，**不需要动第三方源码**。

### 0.3 原版是不是也有 warm_start，只是方式不同？

- **对，猜对了**。原版 `warm_start=True`（默认 False）语义 = **续训**：再次 fit 时不清空 `_programs`，`prior_generations = len(self._programs)`，parents 取上一次最后一代继续进化，并通过跳过 randint 保持随机序列连续（`_fit_tensor` 第 377-383 行）。
- 自研页面 warm_start 语义 = **热启动注入**：`warm_start_formulas`（如 `rsi(14)/ts_Mean(Close,5)`）或 `warm_start_trees` 作为**初始种群**注入（`factor_gp.py` L1468-1479）。
- 两者机制不同：原版是"接着上次跑"，自研版是"预置种子"。**原版没有注入自定义公式的能力**，要注入需改初始化种群逻辑（属 B 档）。

---

## 1. C 档：原版已内置、直接透传参数即可启用（零改动第三方）【已实现】

> 适配性：前端补配置项 → 路由 `qg_params` 补透传 → `mine_quantgp` 过滤后传给 `GpuSymbolicTransformer`，全程不改第三方源码。
> 不扰乱原则：**新增配置项默认值 = 原版默认值**，不改默认行为，纯净基线保持。
> 状态：除 warm_start（页面机制不支持）与 n_jobs（无效）外，其余 C 档参数均已在前端"收敛与预处理"区暴露，路由与 lib 层透传，可 500ms 防抖持久化、多实例共享、重启保留。

### 1.1 求值口径类

#### 1.1.1 metric / objective（适应度函数）
- **作用**：选择进化用适应度。原版支持 6 种（`tensor_fitness.py` 的 `_FITNESS_MAP`）：`ic`/`pearson`（Pearson IC 均值）、`rank_ic`/`spearman`（Spearman 均值）、`icir`、`rank_icir`（IC 均值/IC 标准差）、`long_short_sharpe`/`sharpe`（GPU 多空组合 Sharpe，已内置 `long_short_sharpe`）。
- **原版默认**：`objective="icir"`；`metric` 为空时取 `objective`（`_prepare_metric`）。
- **页面现状**：quant_gp.html 已暴露 `objective`（页面当前默认 rank_ic，原版默认 icir），路由已透传。
- **适配性**：扩展前端下拉选项（ic / rank_ic / icir / rank_icir / sharpe）即可，后端 `get_tensor_fitness` 已支持（下拉已含全部 5 项）。
- **是否扰乱原版**：否。默认值保持页面当前 rank_ic，不改行为；多选只是放开能力。
- **价值**：高。不同目标（相关性 vs 稳定性 vs 组合收益）直接影响挖掘结果，属核心算法参数。

#### 1.1.2 transformer（因子值变换）
- **作用**：算 IC 前对因子值先做变换。支持 `None`（恒等，默认）/ `"sigmoid"` / 自定义 `_Function`（`_prepare_transformer`）。sigmoid 走 torch `sig`。
- **页面现状**：已暴露（下拉：无 / sigmoid，默认无）。
- **适配性**：已实现。前端"因子变换"下拉 + 路由透传 `transformer`（空值转 None）。
- **是否扰乱原版**：否。默认 None = 原版行为。
- **价值**：中。sigmoid 可压缩极端值、缓解异常值对 IC 的影响。

#### 1.1.3 normalize（逐日截面 z-score）
- **作用**：对候选因子值做**逐日横截面 z-score** 后再算 IC（`evaluator.py` `ProgramEvaluator`，`normalize_by_day`）。**默认 True**。
- **页面现状**：已暴露（勾选"逐日截面标准化"，默认 True）。
- **适配性**：已实现。前端勾选 + 路由透传 `normalize`。
- **是否扰乱原版**：否。默认 True = 原版行为。
- **价值**：中。关闭它可观察"原始值 IC"口径，方便与自研页面（gpUseTsNorm 时序标准化）做口径对比。
- **注意**：这与自研页面 `gpUseTsNorm`（时序滚动标准化）不是一回事，勿混淆。若要在复刻页补时序标准化，属 A 档外部后处理。

### 1.2 收敛控制类

#### 1.2.1 stopping_criteria（绝对阈值早停）
- **作用**：当 best `raw_fitness` ≥ 阈值（对"越大越好"的 metric）提前结束进化（`_fit_tensor` 第 435-439 行）。**默认 1.0**。
- **页面现状**：已暴露（数字输入"适应度早停阈值"，默认 1.0）。
- **适配性**：已实现。前端数字输入 + 路由透传 `stopping_criteria`。
- **是否扰乱原版**：否。默认 1.0 = 原版行为。
- **价值**：中高。能省算力，配合 generations 上限控制收敛节奏。
- **注意**：这是"绝对阈值"早停，**不是**自研页面的"验证集 N 代未突破"突破式早停（后者属 B 档）。

### 1.3 去冗余类

#### 1.3.1 tolerable_corr（候选去冗余）
- **作用**：`_select_best_programs` 收尾阶段，在 hall_of_fame 内按 raw_fitness 排序，逐个与已选因子比较**全时段平均 |Pearson corr|**，超过阈值则跳过，选满 n_components（不足则用最优补齐）。**默认 0.7**。
- **页面现状**：已暴露（tolerableCorr），路由已透传。
- **适配性**：无需改动，仅需确认"置为 null 可关闭去冗余"（`tolerable_corr=None` 时不比较）。
- **是否扰乱原版**：否。
- **价值**：已有。
- **注意**：这是"全时段平均绝对相关"去冗余（Auto-Alpha 收尾的相关过滤同源）；复刻页已在此基础上改为 **target 正交化**（对齐 Auto-Alpha-Finding，见 2.6），`ortho_dedup` 已移除。

### 1.4 训练规模与资源类

#### 1.4.1 max_samples（样本降采样）
- **作用**：随机抽部分样本参与训练（默认 1.0 = 全量）。用于大面板提速。
- **页面现状**：已暴露（maxSamples），路由已透传。
- **适配性**：无需改动。
- **价值**：已有。

#### 1.4.2 max_length（节点数上限）
- **作用**：单棵树最大节点数（默认 24，`_fit_tensor` 传给 `_generate_population`）。
- **页面现状**：已暴露（maxLength）。
- **价值**：已有。

#### 1.4.3 warm_start（续训）
- **作用**：**续训**上次模型的种群继续进化（语义见 0.3）。默认 False。
- **页面现状**：未暴露。
- **适配性**：**不暴露（最终决定）**。原版续训需在**同一个 `GpuSymbolicTransformer` 实例上多次调用 fit**（`prior_generations = len(self._programs)`，实例状态须跨调用保留）；而本页面每次点击"开始挖掘"都新建实例、SSE 流结束即释放，续训状态无法跨次保留，暴露该开关只会让用户误以为"接着上次跑"实际却无效。若真要续训，需后端在进程内缓存上次模型实例（属 A/B 档改造），非当前 C 档范畴。
- **是否扰乱原版**：否（未暴露，等于原版默认 False）。
- **价值**：原版语义下需配套"模型实例持久化"才有意义，暂缓。
- **注意**：若想实现"注入自定义公式作初始种群"（自研页面 warm_start_formulas 语义），属 B 档（改初始化种群逻辑）。

#### 1.4.4 low_memory（内存优化）
- **作用**：低内存模式下只保留最近一代种群（`_fit_tensor` 第 432-433 行）。默认 True。
- **页面现状**：已暴露（勾选"内存优化"，默认 True）。
- **适配性**：已实现。前端勾选 + 路由透传 `low_memory`。
- **是否扰乱原版**：否。默认 True = 原版行为（若前端传 False 反而偏离原版，需谨慎）。
- **价值**：低。默认已 True，一般不调。

#### 1.4.5 cache_scores / cache_factors（求值缓存）
- **作用**：因子/得分缓存开关（默认 cache_scores=True，cache_factors=False），影响重复求值速度与内存。
- **页面现状**：已暴露（勾选"得分缓存"默认 True、"因子缓存"默认 False）。
- **适配性**：已实现。前端两个勾选 + 路由透传 `cache_scores` / `cache_factors`。
- **价值**：低。

#### 1.4.6 n_jobs（多进程）
- **作用**：init 有该参数（默认 1），但 `_fit_tensor` **实际未使用**（GPU 向量化为主）。
- **结论**：**不建议暴露**，属无效参数。真正多进程并行评估需改求值循环（B 档）。

### 1.5 C 档小结

| 参数 | 原版默认 | 落地状态 | 价值 |
|---|---|---|---|
| objective/metric | icir | 已暴露（下拉含 ic/rank_ic/icir/rank_icir/long_short_sharpe，页面默认 rank_ic） | 高 |
| transformer | None | 已暴露（下拉 无/sigmoid，默认无） | 中 |
| normalize | True | 已暴露（勾选，默认开） | 中 |
| stopping_criteria | 1.0 | 已暴露（数字输入，默认 1.0） | 中高 |
| tolerable_corr | 0.7 | 已暴露（原有） | - |
| max_samples | 1.0 | 已暴露（原有） | - |
| max_length | 24 | 已暴露（原有） | - |
| warm_start | False | **不暴露**（需同一实例多次 fit，页面每次新建实例不生效） | - |
| low_memory | True | 已暴露（勾选，默认开） | 低 |
| cache_scores | True | 已暴露（勾选，默认开） | 低 |
| cache_factors | False | 已暴露（勾选，默认关） | 低 |
| n_jobs | 1 | **不暴露**（原版 `_fit_tensor` 未使用，无效） | - |

---

## 2. A 档：外部适配层实现，第三方源码零改动【已实现】

> 全部在 `mine_quantgp` 外层 / 路由层实现，可复用自研页面现成后处理函数。
> 适配性：`lib/quant_gp.py` 的 `mine_quantgp` 新增 A 档参数（默认关闭），`routes/quant_gp.py` 的
> `quantgp_mine_stream` 透传并在 done 事件返回报告，`quant_gp.html` 新增"A档增强"配置区 + 报告展示区，
> 参数走 `namespace=quantgp_page` 的 500ms 防抖持久化（多实例共享、重启保留），前后端解耦、逻辑在后端。
> 不扰乱原则：**所有 A 档开关默认关闭**，默认行为与原版完全一致。

### 2.1 数据分段（train/test）
- **作用**：把面板按时间切**训练/测试两段**，fit 用训练段，测试段专供 OOS / Permutation 复核。
- **实现**：`mine_quantgp` 外层按 `train_ratio` 比例切段（复用自研 `factor_gp.split_train_test_dates`，`val_ratio` 固定 0 即退化为两段），`train_ratio<1` 才启用，否则全量 = 原版行为。
- **是否扰乱原版**：否（默认 `train_ratio=1.0` = 原版全量 fit）。
- **价值**：高，是 OOS / Permutation 的基础。
- **注意**：验证段已移除（原先"切而未用"，无任何计算用途）；若将来做 B 档验证集突破式早停，需重新引入。

### 2.2 OOS 复核（样本外检验）
- **来源 case 核实**：OOS 复核的参考来源为 **QuantAlpha LGBM 递归自我改进（saulius.io）**，https://saulius.io/blog/quanta-alpha-lgbm-recursive-self-improvement 。该 case 为博客文章、未开源完整代码，已从原文核实机制：walk-forward **三重分段**（Train 6 年 / Validation 1 年 / OOS 1 年），OOS 段**进化全程不碰、最后才评价**。
- **引擎差异说明**：原版是 LightGBM 引擎，LGBM 训练后需独立验证集评估 RankIC 来选代/选个体，故必须有 Validation 段；复刻页是 QuantGplearn（GP）引擎，GP 适应度 = 因子 IC，直接在训练段算即可，无需独立验证段。**复刻页"测试段"对应原版"OOS 段"，角色一致（纯样本外、进化全程不碰），OOS 口径与原版一致**。
- **作用**：fit 完成后，用测试段**原版机制**（`ProgramEvaluator` + `TensorFitness`）重算候选 IC/ICIR/RankIC/RankICIR，判断是否过拟合。
- **实现**：`oos_recheck_quantgp`；因子值经原版 `execute_tensor -> transformer -> clean_factor -> normalize_by_day` 同口径求值，指标用原版 `mean_ic/mean_rank_ic/icir/rank_icir`。
- **是否扰乱原版**：否（默认关闭）。
- **价值**：高（唯一干净的"训练 vs 样本外"对比，是复核主链路）。

### 2.3 Walk-forward 重验证【已移除】
- **原实现**：单次 fit 后对全区间滚动切 `wf_folds` 段、每段尾部测试子段评估候选 RankIC。
- **移除原因（用户评审结论）**：
  1. 它用**全区间**（含训练段时间范围）滚动，早期 fold 的"测试子段"落在训练段内——树正是在那些时段被优化过的，IC 高是"背书"而非泛化，混进 `mean_ic` 会系统性高估稳健性；
  2. 它没有重训（轻量复评），并非严格意义的 walk-forward，只是"把整段 IC 拆成段再平均"，不产生独立于 OOS 的样本外信息；
  3. 与"训练段/测试段区分"直接矛盾：既然已用测试段做干净的样本外评价（OOS），再混入训练段区间数据反而污染口径。
- **结论**：已从 `lib/quant_gp.py`（`walk_forward_recheck_quantgp` 函数 + 相关参数）、路由、前端配置/报告区全部移除。若将来需要真正的"跨时段稳健性"，应实现**严格重训式 WF**（每段用该段之前的数据重训、该段之后测试，算力 ×N）或**仅测试段内部滚动**（全样本外），二者需按 B 档重做。

### 2.4 Permutation 显著性 + 假发现门闸
- **来源 case 核实**：与 OOS 同源，参考 **QuantAlpha LGBM 递归自我改进（saulius.io）**。原版对最终 best model 跑**五项互补检验 + 预设阈值分级**（False Discovery Gauntlet）：
  1. **Permutation Test（1000 次）**：原文"shuffle the date labels on predictions 1000 times and recompute RankIC each time"（打乱预测值日期标签 1000 次重算 RankIC，看真实 RankIC 是否落在空分布极端尾部）；
  2. **Deflated Sharpe Ratio（Bailey & Lopez de Prado 2014）**：用试验次数 N（96 个体）调整观测 Sharpe，纯噪声下期望最大 Sharpe≈2.58，观测需超过该门槛——多重试验检验，对 GP 挖掘同样适用（GP 也是从大量候选挑最优）；
  3. **Instrument Subsample Stability（20 次随机对半）**：把标的随机对半 20 次，各半算 RankIC，检验信号是否广基（>50% 稳定）；
  4. **Decay Analysis**：在 horizon [1,2,5,10,20] 算 RankIC——真实信号平滑衰减、噪声信号非单调杂乱；
  5. **CV Consistency**：训练内 expanding folds 验证段 RankIC 为正的比例（≥75% 判定稳健）。
  6. **Verdict 分级**：ROBUST（CV≥75% 且 perm p<0.05 且 subsample>50% 且 DSR 通过）/ MARGINAL（CV≥50% 且 perm p<0.10）/ UNSTABLE。
- **本页实现（两项）**：
  - `permutation_significance_quantgp`：单独 Permutation（可独立开启，默认 `n_perm=1000` 对齐原版），对测试段 target 行打乱、复用原版 `mean_rank_ic`，p<0.05 记显著；
  - `fdr_gauntlet_quantgp`：假发现门闸（`enable_fdr`，默认关闭），对已训练好的 `_best_programs` 在**测试段（perm/subsample/decay）+ 训练段（CV consistency）**上只读评估，产出 `fdr_report`（每候选含 perm/deflated_sharpe/subsample/decay/cv/verdict）。
- **是否扰乱原版**：否（默认关闭；只读评估已训练候选，不改训练段、不改第三方源码、不改候选列表）。
- **价值**：中高（Permutation 看单因子显著性；门闸补上多重试验/子样本/衰减/跨期稳健性，与 OOS 互补）。
- **注意**：FDR 门闸的五项检验是一套互补门闸、统一产出 Verdict，**不可拆开单独有意义**，故做成单个 `enable_fdr` 开关；内部参数（DSR 试验次数 / Subsample 次数 / CV 折数 / Decay horizons）跟随该配置。

### 2.5 中性化（市值）+ 时序标准化【已移除】
- **原实现**：对候选因子值在评价前做**市值中性化**（逐截面 ln(市值) OLS 残差化）或**时序滚动分位标准化**后再算指标（OOS/Permutation 链路）。
- **移除原因（用户评审结论）**：
  1. **时序标准化**对 GP 挖掘无意义：适应度是截面 RankIC（Spearman 对量纲不敏感），且它是一刀切作用于所有候选——自研页面只对 technical-ts 类相对量字段用，给不需要它的因子强加非线性变换会**扭曲截面排序、削弱信号**，弊端大于利处；
  2. **市值中性化**在复刻页只作用于复核层（不改训练/挖掘），对挖掘结果零影响，绝对 IC 会变但候选相对排序基本不变，属于"诊断"而非"决定"；其市值代理（当期 amount）比因子评价页的 point-in-time 成交额代理更粗糙。
- **结论**：两者已从 `lib/quant_gp.py`（函数 + 参数）、路由、前端配置区全部移除。**专业的中性化交给因子评价页**（含 point-in-time 成交额代理 + 分组维度 + 中性化前后 IC 对比）；若将来要让挖掘避开市值暴露，应在训练循环内中性化（B 档，改原版内核）。

### 2.6 target 正交化 + 收尾筛选（完全复刻 Auto-Alpha-Finding）
- **来源 case 核实**：残差正交化的标注来源为 **Auto-Alpha-Finding（sw0843）**，github.com/sw0843/Auto-Alpha-Finding。该 case **未下载到本地**（参考文件索引无本地路径），已从 GitHub 抓取原始实现 `alpha_miner.py` 核实机制。
- **关于"增量 IC 去冗余"**：它是自研页 `dedup_by_corr` 的 ortho_mode / 复刻页 `ortho_dedup_quantgp` 的实现——"对因子值残差化 + 残差增量 IC 门槛"。**Auto-Alpha 原版并没有这个功能**；原版 `mine()` 里与去冗余对应的是"**收尾全时段相关过滤 + \|IC\| 阈值**"（见下方收尾筛选）。因此"增量 IC 去冗余"≠"残差正交化"：前者是我方旧设计、已移除，后者是原版机制、现按原版复刻。
- **Auto-Alpha-Finding 原始机制（两段）**：
  1. **target 正交化（驱动挖掘）**：用已有因子池（smart_factor_pool.json）对**目标收益 y** 做 `LinearRegression().fit(X_exist, y)` 取残差（`y = y - reg.predict`），再让 GP 在残差 target 上挖掘 → 挖出的因子与池正交（保证增量 alpha）；每轮挖到新因子后继续残差化 y（顺序正交化）。
  2. **收尾筛选（mine() 收尾段）**：`all_candidates = 既有池 + 新公式`，逐个求因子值并算**池化 Spearman 秩相关 IC**（`calculate_ic`，非逐日截面均值）→ 按 \|IC\| 降序 → 贪婪挑选（与已选因子全时段 \|Pearson corr\| < 0.9 才保留）→ \|IC\| ≥ 0.03 → 不足 8 个兜底取前 8 / 否则取前 15 → `save_pool` 写回因子池。
- **原实现的问题**：复刻页 `ortho_dedup_quantgp`（以及自研页 `dedup_by_corr` 的 ortho_mode）实现的是"对因子值残差化 + 残差增量 IC 门槛"——正交化对象是因子值、且发生在挖掘完成后的筛选层，**与 Auto-Alpha 的"对 target 残差化、驱动挖掘"机制本质不同**。按用户评审结论，机制必须与原始 case 一致，故移除 `ortho_dedup_quantgp`。
- **对齐实现（target 正交化）**：新增 `orthogonalize_target`——在 `build_quantgp_input` 之后、`fit_panel` 之前，用已有 **qgp_\* 因子池**（`_load_qgp_pool_formulas` 从 factor_library 读取，对应 smart_factor_pool）对 target 逐截面回归取残差，再喂给原版 fit（**零改动第三方**）。
- **多轮迭代**：`n_rounds`（Auto-Alpha MINING_ROUNDS）——每轮 fit 后把本轮新因子（翻译为本系统公式）加入池，下一轮重新正交化 target 再 fit（顺序正交化，类似 Gram-Schmidt，新因子与之前所有轮正交）；候选跨轮去重汇总，进化曲线 gen 全局续接。
- **为什么正交化不改训练逻辑、在数据准备阶段即可完成（原理）**：GP 训练只认"输入 X、输出 y"这一对数据，训练循环（进化/适应度/选择/遗传算子）只做一件事——最大化 `corr(f(X), y)`，完全不关心 y 的来源。target 正交化的对象是**目标收益 y** 而非因子值：设池因子张成子空间 P，`y = y_parallel + y_orth`（前者 ∈ span(P)，后者 ⊥ span(P)），正交化后喂给 GP 的是 `y_orth`（残差）。任意候选因子 `f = f_P + f_res`（f_P ∈ span(P)，f_res ⊥ span(P)），因 `y_orth ⊥ span(P)`，故 `corr(f, y_orth) = corr(f_res, y_orth) + corr(f_P, y_orth) ≈ corr(f_res, y_orth)`——**适应度只由 f 中与池正交的成分 f_res 决定**，复刻池因子的树拿不到适应度收益、会被自然淘汰，GP 只能主动去挖与池正交的新 alpha。因此把 y 换成残差后训练逻辑原样跑即可，属**输入准备层**改动，做到"零改动第三方"。这也正解释了与旧设计的本质区别：**改 target 是"驱动挖掘"（挖掘前改变优化目标）**，而**改因子值是"事后筛选"（挖掘后过滤结果，挖掘方向已定死）**。
- **对齐实现（收尾筛选）**：新增 `final_screen_quantgp`——在多轮循环结束后，用训练段面板对"既有池 + 全部候选"求因子值，算池化 Spearman IC（对齐 `calculate_ic`），按 \|IC\| 降序贪婪挑选（\|Pearson corr\| < corr_threshold），再按 \|IC\| 阈值过滤、不足兜底、超上限截断（参数默认 0.03 / 0.9 / 8 / 15，对齐 Auto-Alpha 配置）；幸存候选返回，`final_screen_report` 透传前端展示。**默认关闭**。
- **是否扰乱原版**：否（默认关闭；开启时原版 fit 仍原样执行，只是 target 输入为正交化残差 / 候选按原版收尾逻辑筛选）。
- **价值**：高（对齐参考 case 机制，保证挖掘出的因子相对已入库池有增量 alpha，且收尾去除与既有池高度相关的冗余候选）。

### 2.7 A 档小结

| 功能 | 前端配置（quant_gp.html "A档增强"区） | 后端参数（mine_quantgp） | 默认 | 价值 |
|---|---|---|---|---|
| 数据分段 | 训练段占比 | train_ratio | 1.0 | 高 |
| OOS 复核 | 样本外复核（勾选） | enable_oos | False | 高 |
| Permutation | Permutation 勾选 / 次数 | enable_perm / n_perm | False / 1000 | 中高 |
| target 正交化 | target 正交化（勾选） / 正交化轮数 | enable_target_ortho / n_rounds | False / 1 | 高 |
| 收尾筛选 | 收尾筛选（勾选）/ \|IC\|阈值 / 相关阈值 / 兜底 / 上限 | enable_final_screen / final_ic_threshold / final_corr_threshold / final_min_factors_fallback / final_max_factors_in_pool | False / 0.03 / 0.9 / 8 / 15 | 高 |
| 假发现门闸 | 假发现门闸（勾选）/ DSR试验次数 / Subsample次数 / CV折数 / Decay horizons | enable_fdr / fdr_n_trials / fdr_n_subsample / fdr_cv_folds / fdr_decay_horizons | False / 96 / 20 / 3 / [1,2,5,10,20] | 中高 |

> 说明：A 档报告（segments / oos_report / perm_report / ortho_info / final_screen_report / fdr_report）在 `mine_quantgp`
> 返回后由路由透传，前端在结果区下方"A档复核报告"区域分块展示；任一复核失败不影响主流程（外层 try 兜底）。


---

## 3. B 档：需改第三方训练循环内部（已决策：本地化复制用到的部分）

> 这些功能原版 `_fit_tensor` 内部没有，必须在训练循环内插入逻辑。
> **决策（2026-08-31）：放弃"引用第三方 + 子类覆盖"路线，改为把本项目实际用到的部分复制到系统内部再改**（方案见 3.6）。
> 原因：B 档功能要动的内部点不止一处（如 PCA-QD 需在"孩子替换判断 + 收尾去冗余"至少两处插入），
> 子类覆盖只能整体重写 `_fit_tensor`，会退化成"复制粘贴整个方法"，失去可维护性；"不改第三方源码"的初衷与"必须改内核"冲突。

### 3.1 验证集突破式早停（N 代未突破）
- **作用**：与 1.2.1 的"绝对阈值早停"不同，这里每代用验证段计算 best，连续 N 代未突破则提前停。
- **适配性**：需在 `_fit_tensor` 内每代加验证段计算（传入 val 数据 + early_stop_gens）。
- **是否扰乱原版**：默认关闭则不影响；开启在本地化复制包（见 3.6）的训练循环内实现。
- **价值**：高（防过拟合、省算力）。

### 3.2 GPU 多流并发（gpu_streams）
- **作用**：多棵树在多个 CUDA stream 上异步求值（自研页面已有 `gpu_streams` 机制）。
- **适配性**：需改 `evaluator_` 求值路径（`ProgramEvaluator.evaluate_population` / `torch_functions`）。
- **价值**：中（加速取决于 GPU 与树规模）。

### 3.3 多样性保持（PCA-QD / novelty / archive / replacement 防早熟）
- **来源判定（源码查证）**：**原版 QuantGplearn 没有多样性保持机制**——全库仅见遗传算法常规的 `last_train_elites`（精英保留）与收尾 `tolerable_corr`（相关去冗余），无 archive/novelty/PCA-QD 等多样性引导。故 3.3 为**第三方 case 参考**，非原版自带。
- **真正参考 case（已核实）**：**AutoAlpha（清华，arXiv:2002.08245，2020-04）**，开源实现 xuzhiquan/AutoAlpha（`autalpha/genetic.py`）。其多样性机制为 **PCA-QD（Quality Diversity + 主成分相似度）**：
  1. **PCA 相似度**：不用表达式结构比较（慢），对每个 alpha 的**因子值矩阵 [T×N]** 用幂迭代（5 轮）求**第一主成分 PC1**，两 alpha 的 PC1 序列相关性即相似度 `sim = |corr(pc_a, pc_b)|`；
  2. **拒绝机制**（`pca_qd_accept`）：维护 `record`（已发现多样 alpha）+ `record_values`（各自因子值），新候选与 record 中**任一** alpha 的 PCA 相似度 ≥ 阈值（默认 **0.9**）→ 拒绝（适应度惩罚为 0，不进下一代）；
  3. **三处应用**：每代"孩子 IC 高于父代才替换 + 必须过 pca_qd_accept 否则保留父代"（防早熟+多样性双保险）；收尾按 IC 排序后再按 PCA 相似度 **<0.7** 过滤出最终去冗余池；配合分层结构（depth1 枚举 → depth2/3 逐层）与 warm start（K× 种群按 IC 取前 1/K）。
- **我方自研页面的实现差异（参考，非权威）**：自研页 `pca_qd`/`diversity_weight`/`replacement_thresh`/`hierarchical` 是本系统自行实现，机制与 AutoAlpha 原始实现**不完全一致**（如多样性权重/层级构造方式），仅作参考，不以此作为复刻依据。
- **适配性**：AutoAlpha 的 PCA-QD 是改**进化过程每代的选择/替换**（B 档，需动 `_fit_tensor`/`_generate_population` 内部），会改变挖掘流程本身；核心"因子值 PC1 相关拒绝"与引擎解耦，在本地化复制包（见 3.6）中实现。
- **价值**：中（改善搜索覆盖，避免早熟；对"有效 alpha 稀疏"的大搜索空间收益明显——AutoAlpha 原论文对比：gplearn 得 35 个有效因子，AutoAlpha 得 434 个）。

### 3.4 自定义 warm 种群注入（公式/LLM 基因）
- **作用**：把 `warm_start_formulas` / `warm_start_trees` / LLM 基因注入初始种群（区别于 1.4.3 的续训）。
- **适配性**：需改初始化种群逻辑（`_generate_population` 入口注入）。
- **价值**：高（结合 LLM 增强 GP 的前置能力）。

### 3.5 真多进程并行评估（n_jobs）
- **作用**：真正多进程评估种群（原版 n_jobs 未生效）。
- **来源核实（2026-08 源码查证）**：原版 `GpuSymbolicTransformer.__init__` 接收 `n_jobs`（默认 1）并 `self.n_jobs = n_jobs` 存储，但 **GPU 训练路径（fit_panel / _fit_tensor / 求值循环）全文无一处引用 `self.n_jobs`**——属于"接收但不用"的死参数（gplearn 历史 API 遗产）。真正的 `Parallel(n_jobs=...)` 多进程只在旧版 CPU `genetic.py` 的 `SymbolicTransformer`（扁平 X→y、numpy 逐样本）路径里存在：把种群按 `n_jobs` 拆给多个进程各自跑 `_parallel_evolve`。
- **为什么 GPU 版不需要**：GPU 路径把整棵树编译成 torch 张量算子序列、整个种群在 GPU 上向量化批量求值（batch），GPU 并行度远超多进程 CPU，且省去进程间数据序列化/传输开销；再叠加多进程反而有害（序列化 + 进程通信 + GPU 竞争）。"GPU 向量化已经消化了多进程要做的事"。
- **适配性**：无需做（原版 GPU 路径本就不用）。仅当"GPU 显存装不下整个种群、被迫退回 CPU"场景才有价值。
- **价值**：低（GPU 向量化已覆盖，进程池收益有限；复刻页不暴露 `n_jobs` 是正确的）。

### 3.6 本地化复制方案（决策结论：把"用到的部分"复制进系统内部再改）

**背景 / 为什么不能一直"引用第三方"**：
- 现状：复刻页通过 `_QP_PATH` 把 `third_party/QuantGplearn` 加进 `sys.path`，`mine_quantgp` 只在输入/输出边界做适配，第三方零改动。这在 C 档（纯透传）和 A 档（外部适配层）成立。
- 问题：B 档功能（3.1 验证集早停 / 3.2 GPU 多流 / 3.3 PCA-QD 多样性 / 3.4 自定义 warm 注入）都要在训练循环内部（`_fit_tensor` / `_generate_population` / 选择替换 / 收尾）插入逻辑。"子类覆盖"只能整体重写 `_fit_tensor`，一旦要动多个内部点（如 PCA-QD 需在"孩子替换判断 + 收尾去冗余"至少两处插入），覆盖就退化成"把整个方法复制粘贴过来改"，既失去可维护性，也违背"不改第三方源码"的初衷。

**决策**：
- **不复制整个包**，只把本项目实际用到的部分（依赖闭包）复制到系统内部（**已落地 `lib/quantgplearn_local/`**）作为本地包管理，然后再开始 B 档改动。
- 原版 `third_party/QuantGplearn` 保留作**参考对照基线**，不删除。

**实际引用面核实（2026-08-31）**：
- 生产代码唯一消费者是 `lib/quant_gp.py`：
  - `_QP_PATH = PROJECT_ROOT/third_party/QuantGplearn` 加入 `sys.path`；
  - `_load_quantgplearn()`：`GpuSymbolicTransformer`（gpu_transformer）、`TensorPanelData`（tensor_data）；
  - A 档复核懒加载：`ProgramEvaluator`（evaluator）、`mean_ic / mean_rank_ic / icir / rank_icir / batch_spearmanr`（tensor_fitness）。
- 另有一次性诊断脚本 `_diag_fit.py` / `tmp_smoke_quantgp_import.py` 直连 QuantGplearn（非生产，不纳入本地化）。

**需要复制的文件（依赖闭包，8/12）**：

| 文件 | 被引用的符号 | 内部依赖 |
|---|---|---|
| gpu_transformer.py | GpuSymbolicTransformer（`__init__`/`fit_panel`/`_fit_tensor`/`_select_best_programs`/`transform_panel`） | _program / functions / tensor_data / tensor_fitness / torch_functions / evaluator / utils |
| evaluator.py | ProgramEvaluator（+ `normalize_by_day`） | tensor_fitness |
| tensor_fitness.py | mean_ic / mean_rank_ic / icir / rank_icir / batch_spearmanr / get_tensor_fitness / clean_factor / normalize_by_day | 无内部相对依赖 |
| tensor_data.py | TensorPanelData | 无内部相对依赖 |
| torch_functions.py | GPU_SAFE_PANEL_FUNCTIONS / register_torch_functions | functions |
| _program.py | _Program（树表示 / 交叉变异） | functions / utils |
| functions.py | _Function / _function_map / sig1（算子集合） | 无内部相对依赖 |
| utils.py | check_random_state | 无内部相对依赖 |

**不需要复制的文件（4/12，旧版 CPU 路径或未用）**：
- genetic.py（旧版扁平 X→y 的 CPU SymbolicTransformer 路径，依赖 pathos + joblib Parallel，GPU 版未用）；
- fitness.py（仅供 genetic.py 用）；
- common.py（未用）；
- alpha_pool.py（未用，仅自引用 tensor_fitness）。

**落地步骤（已执行，2026-09-01）**：
1. 新建本地包目录 `lib/quantgplearn_local/`，原样拷入 8 个文件 + 自定义 `__init__.py`（只导出 `GpuSymbolicTransformer`）；✓
2. 改 `lib/quant_gp.py`：删除 `_QP_PATH` / sys.path 注入，8 处 `from QuantGplearn.xxx` 全部改为 `from lib.quantgplearn_local.xxx`（收敛于本文件）；✓
3. 冒烟验证（Agu-2 环境，CPU，population=6 / generations=2 / random_state=42，合成面板）：8 个文件 MD5 与原版逐字节一致；本地包与原版候选公式逐项一致（`EXPR_MATCH: True`）、score 逐项一致（`SCORE_MATCH: True`），零漂移；✓
4. 之后所有 B 档改动只落在本地包内，原版目录留作对照（B 档暂未开始）。

**风险与注意**：
- 本地包与原版是两份代码，须防"悄悄漂移"：约定本地包只在原版基础上做 B 档功能扩展，任何算子语义 / 适应度口径改动必须同步更新本文档与代码注释（中文）；
- 本系统其它模块（factor_gpu_torch.py / factor_gpu_evaluator.py 等）以"对齐 QuantGplearn 语义"的方式注释引用，不 import 原版，只做数值口径对齐，不受本地化影响；
- 翻译器（lib/quant_gp.py 第三部分）依赖 `generate_my_output` 字符串格式与函数名（来自 functions.py 的 `_function_map`）——复制后算子集合保持一致，翻译不受影响。

---

## 4. 落地建议

1. **C 档已完成**（零改动第三方，全部可配置、默认值对齐原版）：objective 下拉已含 5 项；新增"收敛与预处理"区暴露 transformer / normalize / stopping_criteria / low_memory / cache_scores / cache_factors，前端 500ms 防抖持久化（namespace=quantgp_page）+ 路由透传 + lib `**params` 直传；warm_start 因页面机制不支持**不暴露**，n_jobs 无效**不暴露**。
2. **A 档已完成**（外部适配层，零改动第三方，全部可配置、默认关闭）：数据分段（train/test 两段）、OOS 复核、Permutation（默认 1000 次）、**target 正交化（多轮迭代）+ 收尾筛选 + 假发现门闸（Permutation + Deflated Sharpe + Subsample + Decay + CV Consistency → Verdict，均完全复刻参考 case）**，全部在 `mine_quantgp` 外层实现、复用原版 `ProgramEvaluator`/`TensorFitness` 机制，前端"A档增强"区可配 + 报告区展示，参数持久化同 C 档。**Walk-forward 已移除**（全区间滚动与训练/测试区分矛盾、混入训练段背书，理由见 2.3），验证段已移除（切而未用），**市值中性化 / 时序标准化已移除**（前者仅复核层诊断、专业评价交给因子评价页；后者一刀切扭曲不需要它的因子，理由见 2.5），**增量去冗余(ortho_dedup) 已移除**（机制与 Auto-Alpha 不符，改为 target 正交化 + 收尾筛选，理由见 2.6）。
3. **B 档按需推进**：优先"验证集突破式早停"和"自定义 warm 注入"（价值高），在**本地化复制包（见 3.6）**上直接改训练循环内部实现，不再用子类覆盖绕弯。
4. **第三方引用原则（已更新，见 3.6）**：不再"引用第三方 + 子类覆盖"；改为**只把本项目实际用到的部分（8 个文件的依赖闭包）复制进系统内部**（**已落地 `lib/quantgplearn_local/`**）再改。原版 `third_party/QuantGplearn` 保留作对照基线；复制后冒烟对齐已通过（候选公式 + score 逐项一致，零漂移）。

---

## 5. 参考代码位置

- 第三方核心（原版对照基线，不删除）：`third_party/QuantGplearn/QuantGplearn/gpu_transformer.py`（`__init__`/`fit_panel`/`_fit_tensor`/`_select_best_programs`/`transform_panel`）、`evaluator.py`（`ProgramEvaluator` + `normalize_by_day`）、`tensor_fitness.py`（6 种 metric + `_FITNESS_MAP`）。
- **本地化复制包（已落地，见 3.6）**：`lib/quantgplearn_local/`，仅含 8 个被引用文件（gpu_transformer / evaluator / tensor_fitness / tensor_data / torch_functions / _program / functions / utils）+ 自定义 `__init__.py`；`lib/quant_gp.py` 的 8 处懒导入已全部改指向此处，冒烟对齐通过。
- 复刻页后端：`lib/quant_gp.py`（`mine_quantgp` + `_load_quantgplearn`）、`routes/quant_gp.py`（`quantgp_mine_stream` 透传）。
- 复刻页前端：`templates/quant_gp.html`（`quantGpApp`）。
- 自研 GP 参考实现：`lib/factor_gp.py`（`evolve`/`walk_forward_recheck`/`oos_recheck`/`permutation_significance`/`_panel_residualize`/warm 注入）、`templates/factor.html`（GP 子Tab 参数区）。
- 参考 case：
  - **Auto-Alpha-Finding（sw0843）**：github.com/sw0843/Auto-Alpha-Finding（`alpha_miner.py`，target 正交化 + 收尾筛选来源，已核实）
  - **QuantAlpha LGBM 递归自我改进（saulius.io）**：https://saulius.io/blog/quanta-alpha-lgbm-recursive-self-improvement （OOS 三重分段 + 假发现门闸来源，已核实；博客文章、未开源完整代码）

---

## 6. 全局工作流与判断流程合理性分析

> 本章把 C 档（原版内置透传）+ A 档（外部适配层）+ 下游（评价/入库）所有功能**叠加后的完整链路**串起来，
> 逐环节核对"输入是否合理、输出是否与后续逻辑适配、嵌入前后是否影响后续功能实现"，最后对整体判断流程做合理性评估。

### 6.1 全局工作流（所有功能叠加后的完整链路）

```
┌─ 阶段0 输入准备 ──────────────────────────────────────────────┐
│ 股票池(自选/活跃/池) + 日期区间 + rebal_period + feature_names  │
│ 加载 {股票:DataFrame} 面板 → 有效股票数 ≥10 才可进入挖掘          │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段1 A档数据分段（可选, train_ratio<1 才启用）────────────────┐
│ 按比例切 训练/测试 两段 → fit_panel = 训练段                     │
│ 测试段专供 OOS / Permutation 复核（验证段已移除, 无死代码）       │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段2 原版 GP 挖掘（C档参数全程控制）──────────────────────────┐
│ GpuSymbolicTransformer.fit_panel(训练段)                        │
│ 控制: population/hall_of_fame/generations/objective/normalize/ │
│       stopping_criteria/tolerable_corr/max_length/…             │
│ 产出: _best_programs(按fitness排序) + run_details(逐代曲线)      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段3 A档复核（可选, 单次fit + 测试段评估, 全部基于原版机制）─────┐
│ OOS:        测试段重算 候选 IC/RankIC/ICIR/RankICIR              │
│ Permutation:测试段 target 行打乱 → RankIC 空分布 → 经验 p 值      │
│ 产出: oos_report / perm_report                                  │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段4 A档 target 正交化 + 多轮（可选, fit 输入准备层, 对齐 Auto-Alpha）─┐
│ 每轮: 用当前 qgp_* 池对 target 逐截面回归取残差 → 原版 fit → 新因子入池     │
│ 产出: ortho_info{pool_before/after, rounds} (候选跨轮去重, 不受拦截)      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段4.5 A档收尾筛选（可选, 多轮后训练段, 对齐 Auto-Alpha 收尾段）─────────┐
│ 既有池 + 全部候选: 求因子值 → 池化 Spearman IC → |IC| 降序贪婪挑选           │
│ (|Pearson corr| < 阈值) → |IC| 阈值 → 兜底/上限 → 幸存候选返回              │
│ 产出: final_screen_report{n_total/n_kept/scored} (best_programs同步过滤)  │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段4.6 A档假发现门闸（可选, 对齐 QuantAlpha False Discovery Gauntlet）───┐
│ 测试段: Permutation(1000) + Deflated Sharpe(N试验) + Subsample + Decay      │
│ 训练段: CV Consistency (expanding folds) → Verdict ROBUST/MARGINAL/UNSTABLE │
│ 产出: fdr_report[{qg_expr, perm, deflated_sharpe, subsample, decay, cv, verdict}]│
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段5 候选翻译 + 前端展示 ────────────────────────────────────┐
│ 原版表达式 → 本系统 formula（翻译器）                            │
│ 展示: 候选表 + 进化曲线 + 训练score + A档复核报告(5块)             │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段6 批量单因子评价（下游深度链路, 全区间口径）─────────────────┐
│ /evaluate/stream: IC时序 + 分层回测 + 分位收益 + PerformanceWithCost│
│ 注意: 此链路用全区间(start~end), 与 A档复核的"测试段"口径不同      │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ 阶段7 入库 factor_library（下游落地链路）─────────────────────┐
│ /import: 翻译 + 非空率≥0.2 + 公式去重 + base_id解析 + upsert      │
│ 入库后因子可在因子库页复用（评价/回测/组合）                       │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 输入合理性核对

| 功能 | 输入 | 是否合理 | 说明 |
|---|---|---|---|
| 数据分段 | 全面板 + train_ratio | 合理 | 0<train_ratio<1 且测试段非空才启用；`train_ratio=1.0` 回退原版全量 fit |
| OOS 复核 | 已训练 model + 测试段面板 | 合理 | 测试段由分段切出，与训练段无重叠；需 `test_n_days≥5` 才可算 |
| Permutation | 已训练 model + 测试段面板 | 合理 | 因子值只求值一次，之后仅打乱 target 行，空分布口径与训练一致；需 `test_n_days≥40` |
| target 正交化 | 已有 qgp_* 池 + 训练段面板 | 合理 | 池公式在训练段求值后逐截面回归 target 取残差；池为空时退化为原版 target |
| 收尾筛选 | 既有池 + 全部候选 + 训练段面板 | 合理 | 候选翻译为本系统公式在训练段求值，算池化 Spearman IC + 池化 Pearson 相关（对齐 Auto-Alpha）；池为空时只在新候选内部去冗余 |
| 假发现门闸 | 已训练 model + 测试段 + 训练段面板 | 合理 | Perm/Subsample/Decay 用测试段、CV Consistency 用训练段 expanding folds（不碰测试段、不污染 OOS）；需 `test_n_days≥40` 且 `train_n_days≥30` |

### 6.3 输出适配性核对

| 功能 | 输出 | 下游适配 | 是否适配 |
|---|---|---|---|
| 数据分段 | segments{train/test 起止} | 路由透传 → 前端"A档复核报告"展示；测试段供 OOS/perm 使用 | 适配 |
| OOS 复核 | [{qg_expr, ic, rank_ic, icir, rank_icir, oos_ok}] | 前端分块展示；oos_ok 标记"样本外可计算"，无效值置 None 兜底 | 适配 |
| Permutation | [{qg_expr, real_ic, null_mean, null_std, p_value, significant}] | 前端展示；p<0.05 记显著 | 适配 |
| target 正交化 | ortho_info{enabled, n_rounds, pool_before, pool_after, rounds} | 前端展示轮次/池大小；候选跨轮去重汇总 | 适配 |
| 收尾筛选 | final_screen_report{n_total, n_kept, ic_threshold, corr_threshold, fallback_used, scored:[{formula, ic, max_corr, kept, reason}]} | 前端"A档复核报告"新增"收尾筛选"块展示；幸存候选即返回的 candidates，best_programs/best_scores 同步过滤 | 适配 |
| 假发现门闸 | fdr_report[{qg_expr, perm, deflated_sharpe, subsample, decay, cv, verdict}] | 前端"A档复核报告"新增"假发现门闸"块展示 Verdict 与各检验指标；只读评估、不影响候选/入库 | 适配 |

### 6.4 功能嵌入对后续功能的影响

1. **数据分段只改变 fit 输入**：`train_ratio<1` 时 fit 用训练段，候选的 score 基于训练段；默认 `1.0` 时与原版完全一致，不改变后续评价/入库链路。
2. **A档复核是"只读评估"**：OOS/Permutation/FDR 均只对已训练好的 `_best_programs` 做重算，不改 model、不重训、不改候选列表，对主流程零侵入。
3. **任一 A档复核失败不影响主流程**：`mine_quantgp` 外层对每个复核块 `try/except` 兜底，失败仅该报告为空。
4. **target 正交化只改 fit 的 target 输入**：不影响候选公式、评价、入库逻辑；候选跨轮去重汇总、进化曲线 gen 全局续接；真正入库拦截靠 `import_quantgp_candidates` 的公式去重兜底。
5. **收尾筛选只过滤候选输出**：在挖掘完成后对候选做"去冗余 + |IC| 门槛"筛选（对齐 Auto-Alpha 收尾），不影响 fit、评价、翻译、入库逻辑；被筛掉的候选不再进入前端候选表，幸存候选及其 best_programs/best_scores 同步对齐；单独开启、默认关闭。
6. **假发现门闸是纯评估**：Perm/Subsample/Decay 用测试段、CV Consistency 用训练段内部折叠（expanding，不碰测试段、不污染 OOS 口径），对候选列表、翻译、入库零影响；独立开关、默认关闭。
7. **两条评价链路并存**：A档复核（原版机制、测试段、快）与批量评价（本系统体系、全区间、深）互不干扰，用户在阶段5查看复核报告、阶段6做深度评价，决策链清晰。

### 6.5 判断流程的合理性分析

**宏观结论**：训练段/测试段区分是正确且必要的——树在训练段被优化，测试段 IC 反映真实泛化，"train 高 / test 低"的对比本身就是最有价值的诊断信号。A 档复核全部收敛到**测试段（纯样本外）**，口径统一、无泄漏。Walk-forward 与验证段已移除（理由见 2.3 / 2.1），市值中性化 / 时序标准化已移除（理由见 2.5），增量去冗余已改为**对齐 Auto-Alpha-Finding 的 target 正交化**（理由见 2.6）——所有增强均收敛到有独立依据的机制。

判断流程：**挖掘（训练段）→ 快评（测试段：OOS + Permutation）→ 深评（全区间）→ 入库（去重兜底）**，闭环合理。需留意的判断细节：

1. **OOS 门槛偏松**：`test_n_days≥5` 即可算 OOS，5 个交易日的 IC 统计意义弱；而 Permutation 门槛为 `≥40`，两处不一致。建议 OOS 至少对齐 `≥20`（或 `≥40`）。

> 结论：功能叠加后的工作流在数据流、口径、降级策略上整体自洽；唯一建议是处理 OOS 门槛对齐，
> 其余不影响主链路正确性。
