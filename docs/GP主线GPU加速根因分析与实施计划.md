# GP 主线 GPU 加速：根因分析、QuantGplearn 对比与实施计划

> 版本：v1（2026-08-19）
> 定位：承接"GP 主线已开 GPU 仍慢"的根因分析，逐条对照 QuantGplearn 定位差距，并纳入 AlphaMaster / RL 阶段补充的算子与因子（需做 Tensor/torch 处理 + 分类），给出与既有架构适配后的实施计划。
> 依据代码：`lib/factor_gp.py` / `lib/factor_gpu_evaluator.py` / `lib/factor_gpu_torch.py` / `third_party/QuantGplearn/QuantGplearn/*` / `docs/AlphaMaster特征算子与因子库映射方案.md` / `docs/因子挖掘RL引擎实施方案.md`。

---

## 一、一句话结论

GP 主线不是"没上 GPU"，而是 **GPU 利用率极低**：单棵树的求值被大量 Python 级循环、CPU↔GPU 往返、autograd 计算图构建，以及约一半随机树回退 pandas 路径所拖垮。与 QuantGplearn 相比，**单树求值开销差几十到上百倍**，所以即使张量在 CUDA 上，整体依然慢。

三类根因按影响排序：

1. **GPU 算力没用起来**（差距 1~3，不改则其余优化收效甚微）：
   - 全链路未关 autograd，每棵树都在构建计算图；
   - 面板 dtype=float64，消费级 GPU 的 FP64 吞吐仅为 FP32 的 1/64；
   - AlphaMaster/RL 阶段新增的 15 个算子进了 GP 搜索空间但未 GPU 化，随机树 GPU 覆盖率仅约一半，另一半回退 pandas。
2. **单树 GPU 求值成本高**（差距 4~6）：滚动预热区逐时刻 Python 循环、ts_Median 走 numpy 往返、中性化逐截面 solve 循环。
3. **并发与复用缺失**（差距 7~9）：GPU 分支独占主线程并旁路进程池、单树无编译缓存、PCA-QD 每树 SVD。

---

## 二、与 QuantGplearn 的差距清单（9 项）

> 适配性复核：每一行标注"是否真问题 / 是否需要改既有设计 / 修复成本"。结论：**9 项中 8 项是真问题**，1 项（#9）仅在开启 PCA-QD 时是问题。

| # | 差距 | 本系统现状（代码锚点） | QuantGplearn 做法 | 是否真问题 | 是否需改既有设计 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | **autograd 未关** | `factor_gpu_torch.py` 全部算子、`factor_gpu_evaluator.py` 的 `mean_rank_ic` 等均无 `torch.no_grad()`，逐算子建图、保活中间张量 | `ProgramEvaluator.evaluate/evaluate_factor/evaluate_population` 全部 `@torch.no_grad()` | ✅ 真问题（最致命） | 否，就地加 `no_grad` 即可 | P0 |
| 2 | **dtype=float64** | `TensorPanel.from_panel` 默认 `torch.float64`（[factor_gpu_evaluator.py L93-L95](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_evaluator.py#L93-L95)） | 默认 `torch.float32`（tensor_data.py） | ✅ 真问题（消费级 GPU 上 FP64 是死穴） | 需在"入库值用 float64 与 pandas 逐位一致"与"搜索阶段用 float32 提速"之间解耦 | P0 |
| 3 | **AlphaMaster 新增算子未 GPU 化** | `GP_ARITH_UNARY` 新增 10 个一元算子、`GP_TS_OPS` 新增 4 个、`GP_TS_RAW` 新增 `ts_Scale`（[factor_gp.py L45-L65](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py#L45-L65)），但 `TORCH_ARITH/TORCH_TS/TORCH_TS_RAW` 均未覆盖（[factor_gpu_torch.py L1763-L1815](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_torch.py#L1763-L1815)）→ `gpu_supported` 判 False → 回退 pandas | `_build_function_dict` 初始化即校验每个 function 都有 torch 后端，没有直接报错，绝不静默回退 | ✅ 真问题（随机树 GPU 覆盖率仅约 52%） | 否，补 torch 实现 + 注册即自动生效 | P0 |
| 4 | **滚动预热区 Python 循环** | `_rolling_map` 预热区 `for t_idx in range(min(window-1, T))` 逐时刻做小张量算子（[factor_gpu_torch.py L80-L92](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_torch.py#L80-L92)），窗口 250 → 249 次循环 × 多次内核启动 | `_window` 一次 unfold + `_pad_front` 全向量化，无逐时刻循环 | ✅ 真问题 | 需保留"pandas 前缀 min_periods=1"语义，改为向量化前缀计算（cumsum/cummax/cummin 等） | P1 |
| 5 | **ts_Median 走 numpy** | `_ts_median_full` 把窗口 `.cpu().numpy()` 后 Python 循环算中位数再传回 GPU（[factor_gpu_torch.py L209-L218](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_torch.py#L209-L218)） | 无此类往返 | ✅ 真问题（仅 median 树，占比低） | 否，换全 torch 实现（sort 取中位数，偶数取平均以对齐 pandas） | P2 |
| 6 | **中性化逐截面 solve 循环** | `neutralize_by_marketcap` / `neutralize_by_styles` 对每个截面 t 单独 `torch.linalg.solve`（[factor_gpu_evaluator.py L249-L347](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_evaluator.py#L249-L347)），启用中性化后**每棵树**多 T 天小矩阵求解 | 默认不做市值中性化（本系统为华泰 GP 扩展，保留但需向量化） | ✅ 真问题（开启中性化时） | 需把逐截面 OLS 批量化（[T,K+1,K+1] 批量 solve），语义不变 | P1 |
| 7 | **单树编译无缓存** | `_eval_one_gpu` 每棵唯一树每代 `compiler.compile(tree)()` 现编闭包（[factor_gp.py L1231](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py#L1231)） | `execute_tensor` 零编译栈式解释 + 按表达式字符串 score_cache（本系统 fitness_cache 已按 expr_hash 缓存，等效） | ⚠️ 轻微真问题（compile 本身是廉价 Python，重的是执行；fitness_cache 已兜住跨代重复） | 否，加 expr_hash→编译函数缓存即可 | P2 |
| 8 | **GPU 开启后进程池被旁路** | `_eval_all` 中 `if _gpu_ctx is not None and len>=3:` 走 GPU 串行分支并直接 return（[factor_gp.py L1279-L1284](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py#L1279-L1284)），**n_jobs 进程池永不生效**；回退 pandas 的树也在主线程串行 | 单进程 GPU，但无回退路径、单树成本低 | ✅ 真问题（架构级） | 需把 todo 拆成"可 GPU"与"回退"两组，GPU 组主线程、回退组交进程池，并发执行 | P1 |
| 9 | **PCA-QD 每树 SVD** | `_factor_behavior_desc` 对每棵未缓存树做 `torch.linalg.svd([T,N])` 并 `.cpu().numpy()`（[factor_gp.py L968-L1004](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py#L968-L1004)） | 无 QD 机制 | ⚠️ 仅开启 PCA-QD 时真问题 | 否，SVD 前对 T/N 降采样，行为描述子缓存已存在 | P3（可选） |

补充差距（未列入 9 项但同样与 QuantGplearn 有差异）：

- **无 `max_samples` 数据降采样**：QuantGplearn 支持按比例对 [T,N] 面板降采样提速；本系统 GP 主线无此参数（`factor_gp.py` 中无 max_samples）。若追求极限速度可后续加，属 P3。

---

## 三、AlphaMaster / RL 补充算子与因子的 GPU 化清单（对应差距 #3）

> 依据：[AlphaMaster特征算子与因子库映射方案.md] 阶段二步骤 3 已把 17 个算子注册进 `factor_engine.py`（含 `_SAFE_FUNCTIONS` 白名单与 GP 搜索空间），但其备注明确：**GPU 求值器（TORCH_TS/TORCH_ARITH）暂未覆盖，使用时会回退 CPU**。本清单解决这一遗留缺口。

### 3.1 已进 GP 搜索空间、必须补 GPU 实现的算子（15 个）

| 分类 | 算子 | 归属 GPU 字典 | 需新增 torch 函数 |
|---|---|---|---|
| 一元算术（10） | `sign` | TORCH_ARITH | `t_sign` |
| | `jump`（因果 expanding zscore + tanh 软化） | TORCH_ARITH | `t_jump` |
| | `max3` | TORCH_ARITH | `t_max3` |
| | `power`（带符号乘方） | TORCH_ARITH | `t_power` |
| | `signed_log`（带符号对数） | TORCH_ARITH | `t_signed_log` |
| | `sqrt`（带符号开方） | TORCH_ARITH | `t_sqrt` |
| | `clip` | TORCH_ARITH | `t_clip` |
| | `sigmoid` | TORCH_ARITH | `t_sigmoid` |
| | `tanh_squash` | TORCH_ARITH | `t_tanh_squash` |
| | `winsorize` | TORCH_ARITH | `t_winsorize` |
| 带窗时序（4） | `ts_ArgMax` | TORCH_TS | `t_ts_ArgMax` |
| | `ts_ArgMin` | TORCH_TS | `t_ts_ArgMin` |
| | `ts_Product` | TORCH_TS | `t_ts_Product` |
| | `ts_DecayLinear` | TORCH_TS | `t_ts_DecayLinear` |
| 无窗时序（1） | `ts_Scale`（因果 L1 归一化） | TORCH_TS_RAW | `t_ts_Scale` |

> 说明：`gate` / `if_gt` 是 3 元算子，GP 搜索空间（GP_ARITH_BINARY/UNARY）只承载 1/2 元，天然不在 GP 主线搜索空间内，无需在 GP 主线 GPU 化；RL 引擎走 StackVM（token 执行），不依赖 `factor_gpu_torch`，故也不在此列。`signed_power` 未进 GP 搜索空间，同理排除。

**实现与分类原则（与既有算子一致）**：
1. 每个算子按 `factor_engine.py` 中已注册的语义在 `factor_gpu_torch.py` 写 `t_*` torch 实现，数值对齐引擎 pandas 行为（除零/NaN 处理、clip 边界、signed 语义）。
2. 加入对应 TORCH_* 字典后，`gpu_supported`（[factor_gpu_evaluator.py L583-L620](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gpu_evaluator.py#L583-L620)）与 `PanelTensorCompiler.compile` 均按字典自动分发，**无需改判责代码**，GPU 覆盖率自动提升。
3. 带窗算子统一走 `_rolling_map`（min_periods 语义与既有 ts_* 一致）；`ts_ArgMax/ArgMin` 用 unfold + argmax/argmin 并在 NaN 处置 NaN；`ts_Product` 用 `nanprod`（空窗 NaN 语义与 pandas `prod(skipna)` 对齐）；`ts_DecayLinear` 权重用 `arange` 构造滑动加权，与引擎 `ts_DecayLinear` 对齐。
4. 补齐后对 L0 搜索空间随机树做一次 GPU 覆盖率自查（期望 ≈100%，不再有随机树因一元/新增 ts 算子回退）。

### 3.2 AlphaMaster 补充因子：能挪进来的挪进来，挪不进来的照旧过滤

现状（对齐 [factor_gp.py L99-L161 的 GP_BASE_LEAF 注释](file:///e:/jikeAI/code/CASE-AI量化系统/lib/factor_gp.py#L99-L161)）：L2 基类叶子只纳入**技术类**（参数化基类 + 固定参数基类 + TALIB 族），形态类（CDL_*）、Barra/缠论/微观结构/财务类因依赖特殊数据源、GP 行情面板算不出而**不纳入**（被过滤，不进树阶段）。

AlphaMaster/RL 阶段补充的 22 个参数化基类 + 27 个复合因子，按同一原则决策：

- **能挪进来（技术类、面板可算、可 GPU 化）**：如 `autocorr` / `typical_dev` / `dmi_diff` / `trix` / `amihud_illiq` / `kyle_lambda` / `cmf` / `ad_line_slope` / `price_position`（已退化）等，语义与现有参数化基类同类，可参照 `GP_BASE_LEAF` 机制纳入 L2：
  1. `factor_engine.py` 确保有对应 `ts_*` 引擎算子（已在 RL 阶段注册）；
  2. `factor_gpu_torch.py` 补对应 `t_ts_*` torch 实现并加入 TORCH_TS；
  3. 加入 `GP_BASE_LEAF` 并配窗口参数池（如 `autocorr: [10, 20, 60]`），与现有参数化基类同机制。
- **挪不进来（复杂估计 / 多字段强耦合 / 依赖特殊数据）**：如 `hurst` / `fractal_dim`（对数-对数回归、滑动分段估计）、`ichimoku` / `supertrend`（多字段 + 循环追赶逻辑，GPU 向量化成本高）、`trend_strength`（斜率×R² 复合估计）等，**保持现状：不进入 GP 搜索空间/树阶段**，与现有"形态类/财务类不纳入"的过滤行为一致，不为其加 CPU/GPU 兼容分支。

> 注：3.2 的逐因子"能/不能"最终清单需在实施时按 `factor_engine` 实际算子实现逐项核对后再敲定；本计划先给出判定标准与候选方向，避免过度承诺。

---

## 四、1~9 项的处理思路（含是否需要改既有设计）

### P0 三项（根因，先做）

**#1 关 autograd**
- 做法：在 GPU 求值最外层包 `with torch.no_grad():`（`_eval_one_gpu` 的 GPU 分支 + `mean_rank_ic`），或在 `factor_gpu_torch.py` 各 `t_*` 函数上加 `@torch.no_grad()`。推荐前者（一处收口，LLM-GP 复用同函数自动受益）。
- 适配性：不改任何既有设计，纯性能修复。风险极低。

**#2 dtype 解耦 float32 / float64**
- 做法：`TensorPanel.from_panel` 增加 dtype 参数（默认 CUDA 上 float32、CPU 上 float64）；GPU 求值/适应度计算用 float32，入库因子值与 pandas 对齐仍由 float64 引擎（`evaluate_expression`）计算。
- 数值影响：此前验证 float32 CUDA 与 float64 CPU 的 RankIC 差异最大约 5e-5，搜索阶段完全可接受。
- 适配性：**需要小改既有设计**——把"面板 dtype"与"入库精度"解耦。这是唯一会触碰"逐位一致"约定的点，需在文档/代码注释中明确：搜索用 float32，落库用 float64。

**#3 AlphaMaster 算子 GPU 化**
- 做法：见第三节 3.1 清单，一次性补齐 15 个算子。
- 适配性：不改既有设计。补齐后随机树 GPU 覆盖率≈100%，回退 pandas 的树趋近于零（仅剩 ts_Median 等极少数仍走 CPU 的算子，见 #5）。

### P1 三项（单树成本，紧接着做）

**#4 滚动预热区向量化**
- 做法：对常用算子（Mean/Sum/Max/Min/Decay/DecayLinear/Product）用 cumsum/cummax/cummin/cumprod/expanding 一次算完预热区，替换 `_rolling_map` 里 `for t_idx` 循环；保持 pandas `min_periods=1` 前缀语义不变。中位数/分位/偏度等难向量化的算子可保留循环（占比低）。
- 适配性：**需要小改既有实现**（`_rolling_map` 签名或新增逐算子前缀向量化入口），但语义与对外行为不变。

**#6 中性化向量化**
- 做法：把 `neutralize_by_marketcap` / `neutralize_by_styles` 的逐截面 OLS 改为批量：构造 `X:[T,N,K+1]`（NaN 置 0 + 掩码），`XtX = X.transpose(-1,-2) @ X + eps·I`，`Xty = X.transpose(-1,-2) @ y`，一次 `torch.linalg.solve` 得 `[T,K+1,1]`；`<min_valid` 的截面用 `torch.where` 走退化 zscore 分支。语义不变。
- 适配性：**需要小改既有实现**，属于本系统华泰 GP 扩展的自身优化，与 QuantGplearn 无冲突（QG 本来不做）。

**#8 GPU 与进程池并发**
- 做法：`_eval_all` 把 todo 拆成"可 GPU"与"回退"两组；GPU 组在主线程串行求值，回退组提交给进程池（`_pool_eval_expr`），两组用 `concurrent.futures` 并发收尾。`n_jobs>1` 时才能并发；`n_jobs=1` 时保持现状。
- 适配性：**需要小改既有 `_eval_all` 调度逻辑**。这是"开 GPU 就关掉多进程"这一架构问题的正面修复。
- 备注：当 #3 补齐后回退组趋近于空，#8 的收益会自然减小；但保留并发分支对"GPU 覆盖率不满 100%"的场景仍稳。

### P2 两项

**#5 ts_Median 全 torch 化**
- 做法：用 `torch.sort` 沿窗口维排序后取中间两个非 NaN 值的平均（对齐 pandas 偶数取平均语义），去掉 `.cpu().numpy()` 往返。注意：不能直接用 `torch.nanmedian`（偶数长度取的是下中位而非平均，与 pandas 不一致）。
- 适配性：不改既有设计。

**#7 compile 缓存**
- 做法：`_eval_all` 内维护 `expr_hash -> compiled callable` 字典，同一表达式跨代/同代内（交叉克隆、Warm 注入）复用编译结果。fitness_cache 已兜住跨代重复求值，此缓存进一步省掉重复编译。
- 适配性：不改既有设计，收益边际（compile 本身便宜），但实现成本低、无害。

### P3 可选

**#9 PCA-QD 描述子降采样**：SVD 前对 T/N 降采样（如保留 60 个时间点），或对行为描述子缓存扩大复用范围。仅开启 PCA-QD 时生效。
**max_samples 降采样**：对齐 QuantGplearn，增加按比例降采样 [T,N] 求值（可选开关）。

---

## 五、需要突破的既有架构限制（忠实于 QuantGplearn 所需的改动）

用户指出：当前系统很多问题源自实施 GP 因子挖掘时被**因子库等页面的既有架构设计**限制；若需改动既有设计才能忠实于 QuantGplearn 的思想，应当改动。逐一列出：

1. **GPU 覆盖率不是一等公民 → 改为 fail-fast**。QuantGplearn 的做法是：进搜索空间的每个 function 必须同时有 torch 后端，否则初始化直接报错。本系统目前是"GPU 覆盖多少算多少，剩下静默回退 pandas"，这直接导致 #3 的缺口长期存在。
   - **设计变更**：规定"凡是进入 GP 搜索空间（SPACE_L0/L1/L2 或 GP_BASE_LEAF）的算子/基类，必须同时完成三处同步注册（factor_engine 算子表 → factor_gpu_torch TORCH_* → GP 搜索空间），并在提交时提供 GPU 覆盖率自查"。新增因子/算子流程从此把 GPU 覆盖纳入强制项，而不是事后补。
2. **搜索空间受 factor_base 语义约束 → 放开"可 GPU 化技术类"的纳入，过滤规则不变**。GP_BASE_LEAF 目前只纳技术类，过滤机制（面板算不出/依赖特殊数据源 → 不进树阶段）保持不变；AlphaMaster 补充因子按 3.2 原则"能挪进来的就挪进来"。这属于**扩展既有规则**，不推翻现有架构。
3. **"逐位一致"与"GPU 提速"的矛盾 → 明确分层精度**。#2 的 dtype 解耦即为此设计变更：搜索阶段允许 float32 的微小数值差，落库/展示仍走 float64 引擎，保证因子库与页面口径不变。
4. **面板求值与组合级指标**：本系统已支持多股面板 [T,N,F] 与 `rank_icir` / `long_short_sharpe`（top-k 多空、含 3e-4 成本），与 QuantGplearn 的多标的/持仓类能力对齐。若后续需要**组合级多池联合评价、自定义持仓成本/换手惩罚、或 QG 的 `max_samples` 数据降采样**等能力，需新增对应 fitness_mode / 面板接口参数——这些属于明确的设计变更点，按需再议（当前不改）。

---

## 六、实施步骤（顺序执行）

1. **P0：#1 关 autograd**（`_eval_one_gpu` GPU 分支包 `no_grad`）→ 立即生效。
2. **P0：#2 dtype 解耦**（from_panel 支持 dtype，CUDA 默认 float32；`_eval_one_gpu` 回退分支同步）。
3. **P0：#3 AlphaMaster 15 算子 GPU 化**（c 3.1 清单 + 注册 + 覆盖率自查）。
4. **P1：#4 预热区向量化**（常用算子 cumsum/cummax/cummin/cumprod 化）。
5. **P1：#6 中性化向量化**（批量 solve）。
6. **P1：#8 GPU/进程池并发**（todo 拆分 + 并发收尾）。
7. **P2：#5 ts_Median 全 torch**、**#7 compile 缓存**。
8. **P3（可选）**：#9 PCA-QD 降采样、max_samples。
9. **因子侧（3.2）**：按判定标准把"能挪进来"的 AlphaMaster 技术类参数化基类纳入 L2 base_leaf（含 t_ts_* 实现 + GP_BASE_LEAF 注册），"挪不进来"的保持过滤。

> 说明：实施过程不引入 fallback 分支（沿用现有"GPU 不可用回退 CPU"的既有兜底，不新增条件分支）；不在本计划内增加测试脚本（用户未要求，验证方式由页面实测 / 既有流程承担）。
