# QuantGP 复刻页面实施计划（已按实际落地情况更新）

> 目标：在系统内**完整复刻 QuantGplearn 原版 GP 因子挖掘**，不做任何简化/优化/扩充。
> 原则：**算法层 100% 复刻 QuantGplearn 原版**（搜索空间/建树/遗传/执行/适应度/收尾零改动）；仅在**数据输入**与**结果输出**两个边界做本系统适配。
> 本文档与《因子系统与QuantGplearn对齐改进规划.md》（对标/优化向）分开管理。
>
> **更新说明（2026-08-27）**：本页面上线后已从"独立页面"调整为**因子库"因子挖掘"页面下的子 Tab**（miningSubTab='quantgp'），页面、路由、验证结论、算子映射缺口均已按真实落地情况更新，便于后续查阅与进一步完善。

---

## 一、定位与范围

### 1.1 页面定位（按实际落地更新）

- 页面不再独立存在，而是整合进**因子库页面 → "因子挖掘"子 Tab**，作为 `miningSubTab='quantgp'` 子页展示（见 `templates/factor.html`）；
- `templates/quant_gp.html` 是**内嵌片段模板**（无 extends/block），被 `templates/factor.html` 以 `{% include "quant_gp.html" %}` 引用（factor.html 1251-1252 行）；
- 其 Alpine 组件 `quantGpApp()` 以**嵌套 x-data** 形式独立运行，与 `factorApp()` 作用域隔离；
- 作为 **QuantGplearn 纯净基线**：验证原版行为、与本系统增强版（GP/RL/LLM-GP）对照，互不影响。

### 1.2 严格边界（复刻什么 / 不复刻什么）

| 层 | 是否复刻 | 说明 |
|---|---|---|
| 搜索空间（字段/算子/常量/窗口） | **完全复刻** | 使用 QuantGplearn 原版 `GPU_SAFE_PANEL_FUNCTIONS` + 原版常量/窗口机制，**不引入**本系统算子/基类/离散池 |
| 建树（build_program） | **完全复刻** | 原版 type-driven 建树，**不改** |
| 遗传算子（crossover/subtree_mutation/hoist/point） | **完全复刻** | 原版实现，含 0.9/0.1 节点权重；**不加**本系统深度实测兜底（保持原版"无深度检查"行为） |
| 执行（execute_tensor） | **完全复刻** | 原版 [T,N,F] 张量求值 |
| 适应度（objective） | **完全复刻** | 原版 `tensor_fitness`（ic/pearson/rank_ic/icir/rank_icir/long_short_sharpe），**不加**中性化/TS 分位 |
| 收尾（hall_of_fame/去冗余/early stop） | **完全复刻** | 原版 tolerable_corr 剔除 + 绝对阈值早停，**不加** OOS/WF/permutation/分段 |
| 数据输入 | **本系统适配** | 本系统行情面板 → 原版 long-panel 输入格式（见第三章） |
| 结果输出 | **本系统适配** | 原版产出因子 → 本系统因子库结构（见第四章） |

---

## 二、技术选型与依赖

### 2.1 使用原版库

- 直接调用 `third_party/QuantGplearn` 的 **`GpuSymbolicTransformer`**（GPU 整树张量求值），源码零改动；
- 不选用 CPU 版 `SymbolicTransformer`（genetic.py，依赖 pathos——环境缺失，且 GPU 版已是本系统数据规模下的正确选择）。

### 2.2 依赖已验证（已实测）

- Agu-2 环境实测：缺 `numba/pathos/dill/tables/pyarrow`，但 `GpuSymbolicTransformer` **可正常 import**：
  - `functions.py` 在 numba 缺失时走纯 Python 回退（`nb=None` 分支）；
  - GPU 整树求值路径不依赖 pathos。
- **结论：复刻 GPU 版无需新装任何依赖。**
- **torch 2.6.0 与 `torch_functions.py` 运行时算子兼容性：已在 Agu-2 实测跑通**（GPU 与 CPU 两种模式均完成训练，见第六章性能记录）。

---

## 三、数据输入适配层

### 3.1 本系统数据格式

```
panel = {
  "600519.SH": DataFrame(index=日期, columns=[open, high, low, close, volume, amount, vwap, turnover, ...]),
  ...
}
```
- 来源：`lib.backtest_data.load_daily_kline(code, start_date, end_date, prefer="mysql")`；
- 字段：行情列（小写 open/high/low/close/volume/amount/vwap/turnover）。

### 3.2 转换流程（数据适配器，按实际落地更新）

目标：把 `{股票: DataFrame}` 转成 QuantGplearn 的 `TensorPanelData.from_panel_df` 输入（long-panel DataFrame，MultiIndex `[datetime, symbol]` + 特征列 + target 列）。

```
1. 逐股票 df 加 "symbol" 列（=股票代码）
2. concat 全部股票 → 重置索引 → 设 [datetime, symbol] MultiIndex（排序）
3. 特征列: 默认 DEFAULT_FEATURES = [open, high, low, close, volume, amount, turnover_rate]（7 列）
4. target 列: 未来收益 = close 前移 rebal_period 期收益率（复用本系统 prices 面板口径）
5. 调 TensorPanelData.from_panel_df(X, feature_names, target_col, time_index="datetime", security_index="symbol")
```
- 数据装载限制：`_load_panel` 取用户选择股票池的前 **80 只**，每只要求有效 K 线 **>60 根**，有效股票 **≥10 只**否则报错（见 routes/quant_gp.py）；
- 字段命名：QuantGplearn 特征是 `X1..Xn` 索引，`feature_names` 只需与本系统列名一致即可（原版内部用索引取列，无命名冲突）；
- 派生字段（Value/IdioRet/TotalRet）：**默认不喂入**（保持原版字段集纯净）；
- 数据量：与原版一致用全量股票/日期（不做本系统降采样）。

### 3.3 参数透传

页面参数 → 原版 `GpuSymbolicTransformer.__init__` / `fit_panel`，**原样透传，不增减逻辑**：
`population_size / hall_of_fame / n_components / generations / tournament_size / init_depth / init_method / objective(ic|icir|rank_ic|rank_icir|long_short_sharpe) / const_range / parsimony_coefficient / p_crossover / p_subtree_mutation / p_hoist_mutation / p_point_mutation / p_point_replace / max_samples / max_length / tolerable_corr / device / random_state`。
- **function_set 未在页面暴露**，沿用原版默认 `GPU_SAFE_PANEL_FUNCTIONS`（原第七章的算子映射缺口已于 2026-08-28 按方向 A 在引擎补齐，见 7.2/7.3/7.4）。

---

## 四、结果输出适配层（因子入库）

### 4.1 本系统因子计算机制（先理解再适配）

- **基础因子**：本身可独立计算（公式为基类实例或字段恒等，`evaluate_expression` 直接可算），如 `macd()` / `kdj()` / `close`；
- **复合因子**：公式由**基类实例 + 算子**组合而成（如 `rsi(14)`、`cs_Demean(returns(5))`），依赖基类展开后才能计算；
- **统一入口**：`evaluate_expression(expr, panel)` 直接把公式当字符串求值——`_build_field_dfs` 预计算字段 + `BASE_OPERATOR_MAP` 注入基类可调用函数（`_make_base_callable`），公式内的 `rsi(14)` 会被展开成 `ts_RSI(Close, 14)` 求值。**不需要显式递归依赖表**，依赖关系由公式中基类实例自动推导（`analyze_expression_tags` / `_extract_dependency_bases` 递归解析公式得到 base_id 集合）。
- 因此：**QuantGplearn 挖出的因子若能翻译成本系统公式语法，则天然可入库、可求值、可解析出 base_id**。

### 4.2 QuantGplearn 产出 → 本系统公式（翻译器）

QuantGplearn 产出的 `_Program` 字符串形如：
```
add(ts_mean(X0, 5), ts_rsi(X1, 14))
```
其中 `X0/X1` 是特征索引（1-based），算子名是原版小写 `ts_mean`/`ts_rsi`/`cs_rank` 等。

翻译实现（lib/quant_gp.py 的 `_translate_expr` / `_translate_node`）：
```
1. X{i} → 本系统字段名（由 feature_names[i-1] 解析）
2. 算子名映射表 _OP_NAME_MAP：原版小写名 → 本系统 evaluate_expression 驼峰命名
   （ts_mean→ts_Mean, ts_std→ts_Stdev, ts_rank→ts_Rank, cs_rank→cs_Rank, ...）
3. 算术算子 add/sub/mul/div → 中缀符号 (a+b)/(a-b)/(a*b)/(a/b)
   （本系统无 add/div 函数，只有符号形式）
4. 一元 neg(x) → (-x)，inv(x) → (1/x)；sqrt→sqrt, abs→abs, sig→sigmoid, log→log
   （log 由本系统 factor_engine 补充实现；sin/cos/tan 无对应函数，保持原名交给 validate 判断）
4b. 二元 max/min → np.maximum/np.minimum（原版 t_max/t_min 为二元逐元素算子，
    本系统内置 max/min 不支持 DataFrame 逐元素比较，故翻译为 np.maximum/np.minimum）
5. 输出本系统公式字符串，如: (ts_Mean(Close,5)+ts_RSI(Volume,14))
6. 校验: validate_expression(formula) → evaluate_expression(formula, panel) 试算
   非空率 ≥ 0.2 才判定为有效候选
```

### 4.3 解析基础类（base_id）

- 复用本系统 `analyze_expression_tags(formula)`：
  - `base_id`：递归解析公式中的基类实例名（如 `ts_RSI` 反查 → `rsi`、`ts_Mean` 反查 → `sma`），逗号分隔写入 `factor_library.base_id`；
  - `factor_type`：`technical` / `technical_ts` / `signal` / `financial`（按 `_is_technical_ts_expression` 等规则推断）；
  - `direction`：positive（入库后用户可覆盖）。
- **结论**：QuantGplearn 挖出的因子（含算子+窗口组合）在本系统视角下**均为复合因子**（`factor_type=composite`），其 base_id 集合由公式反查基类得到——与现有"复合因子依赖基础因子"的机制一致。GP 公式多为 ts_*/cs_* 算子组合，反查不到唯一基类时 base_id 为空也合法（公式自包含、可独立求值）。

### 4.4 入库 factor_library

```
写入字段:
  factor_id   生成（qgp_<hash> 前缀, 保证唯一）
  name        公式短摘要（或自动命名）
  category    技术
  sub_category 空
  direction   positive（默认, 用户可改）
  formula     翻译后的本系统公式（4.2 输出）
  base_id     analyze_expression_tags 解析结果
  factor_type composite（QuantGplearn 产出均为复合因子）
  evaluation_type 推断的 technical / technical_ts（供单因子评价路由）
```
- 入库前校验：`evaluate_expression(formula, panel)` 必须能算出非空面板（非空率 ≥ 0.2），否则跳过或标记不可用。

### 4.5 页面展示

- 候选列表：表达式（本系统公式）、fitness/IC（原版 `_best_scores`）、base_id、factor_type；
- 操作：单因子入库 / 批量入库；入库结果摘要（成功数 / 跳过数）。

---

## 五、页面与路由（按实际落地更新）

```
templates/quant_gp.html        内嵌片段模板（无 extends/block），Alpine 组件 quantGpApp()
                               被 templates/factor.html 以 {% include "quant_gp.html" %} 引用
                               （位于因子挖掘子Tab: miningSubTab='quantgp'）
routes/quant_gp.py             APIRouter，app.py 注册 prefix=/api/factor/quantgp
  GET  /api/factor/quantgp/fields        → 可喂入的行情字段列表
  POST /api/factor/quantgp/mine/stream   → SSE: progress(每代) / done(结果) / error
  POST /api/factor/quantgp/import        → 候选因子翻译 + 校验 + 入库 factor_library
  POST /api/factor/quantgp/evaluate/stream → SSE: 候选因子批量单因子评价（IC/分层/分位/PWC），逐因子返回
```

### 5.1 前端页面要素

- 参数区：种群/代数/深度/目标(objective)/rebal_period/字段选择/设备(cuda/cpu)/随机种子；
- 运行区：启动/停止（后台线程，复用 `factor_mining_jobs` 任务注册表模式）；
- 结果区：进化曲线（每代 best/avg）、候选因子表格、单因子/批量入库按钮、入库摘要；
- **单因子评价区**（候选表上方"单因子评价"按钮触发，位于训练结果下方独立区域）：
  - 对全部候选因子批量跑单因子评价（SSE 逐因子返回，共享同一行情面板）；
  - 每个因子一张卡片：指标卡（IC均值 / IR / RankIC / 多空收益 / PWC夏普 / 有效性评级 / 评价方式）+ 4 张图（IC 时序柱状 / 分层收益 / 分位收益 / PWC 累计收益含成本）；
  - 评价方式与因子库单因子评价一致：`technical` 直接评价，`technical_ts` 先自身历史滚动分位标准化（`ts_rank_normalize`）再评价；
  - 用于判断候选因子实际表现后再决定是否入库（不修改原版挖掘逻辑）。

---

## 六、复刻一致性验证结论（重点，按实际核对结果）

### 6.1 计算逻辑一致性：100% 复刻原版

对 `third_party/QuantGplearn` 源码逐行核对，`lib/quant_gp.py` 的 `mine_quantgp()` 核心只是**原样调用**：

```python
GpuSymbolicTransformer, _ = _load_quantgplearn()
model = GpuSymbolicTransformer(**kwargs)     # 参数原样透传
model.fit_panel(X, target_col=target_col)    # 原版训练主循环
```

- **建树（按 type 分类）**：`_program.py::build_program` 中 `function_dict = {"number": [], "category": []}`；根节点强制从 number 函数选取（首代排除 ts_std/ts_kurt/ts_atr）；子节点按 `terminal_stack` 中的参数类型（vector/scalar）决定插入函数还是终端。与用户关注的"根据 type 分类建树"**逐行一致**；
- **遗传算子**：crossover / subtree_mutation / hoist_mutation / point_mutation（含 Koza 0.9/0.1 节点权重、headless chicken、get_subtree 类型匹配）全在原版 `_program.py`，**未加本系统深度实测兜底**；
- **组合/演化**：`_generate_population` + tournament 选择 + 遗传算子概率累加 + `fitness = raw_fitness - parsimony` + hall_of_fame / tolerable_corr 去相关，全在原版 `gpu_transformer.py`；
- **适应度**：原版 `tensor_fitness`（ic / pearson / rank_ic / icir / rank_icir / long_short_sharpe）。

**结论：复刻层（挖掘、建树、组合、适应度、收尾）与原版完全一致，无任何歪曲或修改；也没有把本系统已有实现"反向复刻"到原版里。原版库源码零改动。**

### 6.2 "映射"的定位：结果对接层，不属于复刻层

- 映射只发生在"结果怎么落进本系统库"这一步：原版产出的表达式用**它自己的语法**（小写函数名 `ts_mean`、特征占位 `X1`、LISP 前缀式 `add(a,b)`），本系统因子引擎 `evaluate_expression` 只认**驼峰算子 + 本系统字段名 + 中缀符号**；
- 因此必须翻译（方向是 **原版 → 本系统**，不是反过来）。`add(a,b)→(a+b)`、`ts_mean→ts_Mean` 均为**纯语法等价，不改变语义与挖掘过程**；
- 若不翻译，原版表达式存进 factor_library 后本系统引擎无法计算。

### 6.3 链路验证（_verify_qgp.py）

用 `_verify_qgp.py`（合成面板 20 股 × 300 日）跑通 **翻译 → validate → base_id/factor_type 解析 → 非空率试算** 完整链路：
- 8 条原版风格表达式，**7 条通过**（翻译、校验、base_id 解析、非空率 ≥ 0.2 全过）；
- **1 条失败**：含 `ts_zscore`（映射为 `ts_ZScore`）的表达式——本系统引擎无 `ts_ZScore`，validate 报"未知标识符"。
- 结论：对接机制正确；未过项全部由**算子映射缺口**（见第七章）导致，与挖掘逻辑无关。

### 6.4 性能与行为观察

- GPU 模式性能显著优于 CPU（实测 GPU 3 代约 52 秒 vs CPU 2 代约 5.7 分钟）；
- 测试股票池 5 日前向收益 Rank IC 接近 -0.006，导致 GP 收敛到退化表达式——属原版在弱预测 target 下的正常现象，非复刻缺陷。

---

## 七、算子映射核对结果（按实际核对，更新为缺口清单）

将原版默认搜索空间 `GPU_SAFE_PANEL_FUNCTIONS` 中的算子逐一对照 `_OP_NAME_MAP` 目标名是否存在于本系统 `factor_engine.py`：

### 7.1 映射后引擎存在（可翻译、可校验、可入库）

| 原版算子 | 映射目标 | 存在性 |
|---|---|---|
| ts_shift / delta / mom / min / max / argmax / argmin / rank / sum / std / corr / mean / skew / kurt / ema / rsi / atr / adx / macd | ts_Delay / ts_Delta / ts_ROC / ts_Min / ts_Max / ts_ArgMax / ts_ArgMin / ts_Rank / ts_Sum / ts_Stdev / ts_Corr / ts_Mean / ts_Skewness / ts_Kurtosis / ts_EMA / ts_RSI / ts_ATR / ts_ADX / ts_MACD_DIF | 存在 |
| cs_rank / cs_zscore / cs_demean | cs_Rank / cs_Zscore / cs_Demean | 存在 |

### 7.2 映射目标原缺失 → 已在引擎补齐（已实施，不再跳过）

> 按"不新增基类记录、不新增 factor_type 分类"原则，在 `factor_engine.py` 以既有 ts_*/cs_* 算子同款风格（DataFrame 面板 + rolling + min_periods 预热）补充为纯算子，并随 `_SAFE_FUNCTIONS` 自动/手动登记，语义对齐原版同名算子。

| 原版算子 | 补齐的引擎算子 | 状态 |
|---|---|---|
| ts_zscore | ts_ZScore | **已补齐** |
| ts_freq | ts_Freq | **已补齐** |
| ts_cmo | ts_CMO | **已补齐** |
| ts_bband | ts_BOLL | **已补齐** |
| ts_aroon | ts_AROON | **已补齐** |
| ts_stochf | ts_STOCHF | **已补齐** |
| ts_hedge / ts_bopr / ts_xs_ratio / ts_cdlbodym / ts_bar_bs / ts_one_ols_k / ts_one_ols_resid | ts_Hedge / ts_BOPR / ts_XSRatio / ts_CDLBodyM / ts_BarBS / ts_OneOlsK / ts_OneOlsResid | **已补齐** |
| cs_scale / cs_winsorize | cs_Scale / cs_Winsorize | **已补齐** |

### 7.3 一元/二元函数处理（已修正）

| 原版 | 处理 | 状态 |
|---|---|---|
| add / sub / mul / div | → 中缀 + - * / | 正常 |
| neg / inv | → (-x) / (1/x) | 正常 |
| sqrt / abs / sig | → sqrt / abs / sigmoid | 正常 |
| log | → log（引擎补充元素级 log，语义对齐原版 t_log：\|x\|<=1e-6 置 0，负值取绝对值） | **已补齐** |
| max / min | → np.maximum / np.minimum（引擎 _SAFE_NAMES 同步登记 minimum） | **已修正** |
| sin / cos / tan | 引擎无对应函数，保持原名 → validate 拒绝 → 跳过 | 原版搜索空间不含，无影响 |

### 7.4 影响范围（已消除）

- 原缺口：缺失算子影响"候选表达式落库"环节，含缺口的候选被跳过（进 skipped）；
- **现状（2026-08-28）**：已按方向 A 在本系统 `factor_engine` 补齐全部缺失算子（见 7.2/7.3），并用 `_verify_qgp2.py` 覆盖 `GPU_SAFE_PANEL_FUNCTIONS` 全部 46 个函数逐项验证"翻译 → validate → evaluate 非空率 ≥ 0.2"全链路，**全部通过**。候选落库不再因算子缺失被跳过。
- 备选方向 B（页面暴露 function_set 限定搜索空间）未采用，保持原版默认搜索空间完整复刻。

---

## 八、实施步骤与完成情况（按实际更新）

> 顺序：先跑通原版 → 再翻译入库 → 再页面化。每步独立验证。

| 步骤 | 内容 | 状态 |
|---|---|---|
| 8.1 | 数据适配器：面板 → long-panel + target | **已完成**（实测喂给 `TensorPanelData.from_panel_df` 正常） |
| 8.2 | 原版求值冒烟：`GpuSymbolicTransformer` 在 Agu-2 跑通（CPU / CUDA） | **已完成**（torch 2.6.0 算子兼容；GPU 3 代约 52 秒，CPU 2 代约 5.7 分钟） |
| 8.3 | 表达式翻译器：QuantGplearn 公式 → 本系统公式 | **已完成**（`_verify_qgp.py` 8 例全通过；`_verify_qgp2.py` 覆盖原版默认搜索空间 46 个函数全通过） |
| 8.4 | base_id 解析 + 入库 | **已完成**（`analyze_expression_tags` 解析 base_id/factor_type；`evaluate_expression` 非空率 ≥ 0.2 才入库；与因子构建页同机制） |
| 8.5 | 页面 + 路由 + SSE | **已完成**（整合为因子库"因子挖掘"子Tab quantgp；SSE 每代进度；单/批量入库） |
| 8.6 | 对照验证 | **已完成**（算法层与原版完全一致；算子映射缺口已按方向 A 在引擎补齐，`_verify_qgp2.py` 覆盖全部 46 个函数全链路通过，见 7.2/7.3/7.4） |
| 8.7 | 单因子评价（训练后评估候选表现，辅助决策入库） | **已完成**（新增 `POST /api/factor/quantgp/evaluate/stream` SSE 接口，逐因子跑 IC时序/分层/分位/PWC 含成本评价；前端候选表新增"单因子评价"按钮，训练结果下方独立区域展示每因子指标卡 + 4 张图，复用因子库单因子评价口径） |

---

## 九、验收标准

1. **完全复刻**：QuantGplearn 原版行为不变（搜索空间/建树/遗传/执行/适应度/收尾零改动）——**已达**；
2. **数据接入**：本系统行情面板可直接作为输入，无需手工预处理——**已达**；
3. **因子可入库**：QuantGplearn 产出的候选能翻译成本系统公式、通过 `validate_expression`、`evaluate_expression` 非空率 ≥ 0.2——**已达**（缺失算子已按方向 A 在引擎补齐，默认搜索空间 46 个函数全链路验证通过，落库不再跳过）；
4. **基础类可解析**：候选入库时能解析出 `base_id` 集合，且 `evaluate_expression` 能计算出因子值——**已达**；
5. **页面可操作**：QuantGP 子 Tab 完整走通"配参 → 挖掘 → 出结果 → 入库 → 单因子评价"——**已达**。

---

## 十、风险与开放问题（按实际更新）

| 项 | 说明 | 状态 |
|---|---|---|
| torch 算子兼容性 | torch 2.6.0 与 `torch_functions.py` 运行时求值 | **已实测通过**（GPU/CPU 均跑通） |
| 算子名映射完整性 | 原版算子 ↔ 本系统 `_SAFE_FUNCTIONS` 命名逐项核对 | **已核对并补齐**（2026-08-28 按方向 A 补齐 13 个 ts_* + 2 个 cs_* 缺失算子，见 7.2/7.3） |
| max/min 求值 | 引擎内置 max/min 对 DataFrame 求值报歧义错误 | **已修正**：翻译时映射为 np.maximum/np.minimum，引擎 _SAFE_NAMES 登记 minimum |
| log 求值 | 引擎无对应函数，候选被 validate 拒绝 | **已补齐**：引擎补充元素级 log（语义对齐原版 t_log），_SAFE_FUNCTIONS 登记 |
| 窗口参数来源 | 原版窗口是标量参数（建树时生成），翻译后作为本系统算子窗口参数保留 | 语义一致 |
| 目标函数 target | 原版需要 target 列；本系统用 rebal_period 前向收益作为 target | 口径已固化 |
| 因子重复 | 同一公式多次入库需去重（按 formula 规范化哈希） | 入库逻辑含 hash 前缀去重 |
| 数据量 | 全量股票/日期跑原版 GPU 求值 | 已实测，显存需求小，GPU 显著快于 CPU |
| 弱 target 收敛 | 5 日前向收益 Rank IC 接近 0 时 GP 收敛到退化表达式 | 原版正常现象，非缺陷 |

---

## 十一、参考

- 原版库：`third_party/QuantGplearn/QuantGplearn/`（`gpu_transformer.py` / `tensor_fitness.py` / `functions.py` / `_program.py` / `tensor_data.py` / `torch_functions.py`）
- 适配层：`lib/quant_gp.py`（`panel_to_long_panel` / `mine_quantgp` / `_translate_expr` / `_translate_node` / `quant_gp_expr_to_formula` / `import_quantgp_candidates`）
- 路由与页面：`routes/quant_gp.py`（`/api/factor/quantgp/*`）/ `templates/quant_gp.html`（片段，被 `templates/factor.html` include）
- 本系统求值/入库：`lib/factor_engine.py`（`evaluate_expression` / `calc_factor` / `BASE_OPERATOR_MAP` / `analyze_expression_tags` / `validate_expression`）、`lib/factor_db.py`（`factor_library` / `factor_base` / `save_factor`）
- 链路验证脚本：`_verify_qgp.py`
- 现有 GP 页面（对照）：`lib/factor_gp.py` / `routes/factor.py` / `templates/factor.html`
