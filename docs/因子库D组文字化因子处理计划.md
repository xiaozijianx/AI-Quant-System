# 因子库 D 组文字化因子处理计划

> 创建时间: 2026-08-15
> 状态: **D1-D5 已全部完成 (2026-08-15)** — 原"计划已定稿, 待实施", 落地后状态更新(实施记录见各阶段末)
> 前置: 本计划是 [因子评价方式适配性审计与路由改造计划.md](./因子评价方式适配性审计与路由改造计划.md) 中"阶段5: D组逐个配引擎"的展开实现方案。
> 背景: 因子库现有 34 个文字化(不可计算)因子, 分布在 Barra风格/龙头/微观结构/缠论/ML-SVD 五类。目标: 在"单因子分析阶段全面覆盖"的前提下, 逐类甄别其量化适配性、归类(基础/复合/鸡肋)、计算方式与评价方式。

---

## 〇·五、整体规划定位 (2026-08-15 用户确认)

本计划(D组)是用户对因子体系整体改造的**第一阶段(因子库补全)**。后续大阶段依次为:

| 阶段 | 内容 | 状态 |
|---|---|---|
| **D1-D4** | 因子库补全: 34 个文字化因子甄别/落地/下架, 提升因子覆盖率 | 本计划, 待实施 |
| **D5** | 单因子分析优化: 中性化前后IC对比 / 多持有期衰减 / 分年度IC稳定性 | 本计划, 见第九节 |
| **F** | 多因子分析优化: 更专业化, 优化"生成因子包"流程 | 后续, 未排期 |
| **G** | 因子构建 | 后续, 未排期 |
| **H** | 因子挖掘(可能用到 SVD / 机器学习) | 后续, 未排期 |
| **E** | 组合风险分析(风险模型) | 已由 F 阶段(F1)落地, 详见 [因子库F阶段-综合多因子分析设计文档.md](./因子库F阶段-综合多因子分析设计文档.md) |

> 本文件只含 D 阶段(D1-D5)内容; E 阶段已独立成文, 本文件不再包含。

---

## 〇、决策摘要 (与用户讨论确认)

| 类别 | 数量 | 处理结论 |
|---|---|---|
| Barra 风格 | 10 | **全部保留**, 均为基础因子; 6 个走 technical + 4 个走 financial; 基于现有数据源实现 |
| 龙头 | 7 | **只保留 DRAGON_DAY_CHANGE**; 其余 6 个从因子库下架(不删策略代码) |
| 微观结构 | 10 | **全部保留**, 标 evaluation_type=none(缺 tick 数据), 本期不计算不评价 |
| 缠论 | 5 | 落地 3 个 signal 型(顶分型/底分型/笔方向); 中枢 ZG/ZD **暂缓** |
| ML / SVD | 2 | **从因子库下架**; 未来规划独立的"ML因子/隐因子"页面 |

净增可评价因子: Barra 10 + 龙头 1 + 缠论 3 = **14 个**; 下架: 龙头 6 + ML/SVD 2 = 8 个; 保留不处理: 微观结构 10 个。

> 2026-08-15 追加: 用户确认**单因子阶段 3 项诊断增强**(中性化前后IC对比/多持有期衰减/分年度IC稳定性)记入本计划, 作为 **D5 阶段**(见第九节)。
> 2026-08-15 追加: **E 阶段(组合风险分析/风险模型)最初独立成文, 后由 F 阶段(F1)落地**(Barra 风格暴露/风险分解/组合中性化/归因), 详见 [因子库F阶段-综合多因子分析设计文档.md](./因子库F阶段-综合多因子分析设计文档.md); 早期规划存档见 [因子库E阶段-组合风险分析计划.md](./因子库E阶段-组合风险分析计划.md)。

---

## 一、Barra 风格因子 (10个, 全部保留)

### 1.1 是什么
Barra 是一套"风格风险模型"(MSCI, A股版 CNE5): 把股票收益拆解为对若干风格因子的暴露。10 个因子**横跨两类**:
- **市场数据类(6个, technical)**: SIZE / NONLINEAR_MV / BETA / MOMENTUM / RESVOL / LIQUIDITY —— 日频连续、截面可比
- **财务驱动类(4个, financial)**: BTOP / GROWTH / PROFIT / LEVERAGE —— 分子为季度财报字段

### 1.2 归类判断: 全部为基础因子
依据《因子基础_复合分类盘点.md》, Barra 风格因子被明确列为典型基础因子——每个都有 MSCI 官方独立金融定义, 语义不依赖事后附加的时间周期。**不降级为复合因子**。

### 1.3 与现有因子冗余检查

| Barra | 与现有因子重叠 | 处理 |
|---|---|---|
| SIZE / NONLINEAR_MV / BETA | 库中无规模/非线性市值/Beta因子 | 全新, 保留 |
| RESVOL | 与 hist_vol_* 相关但不同(特质波动 vs 总波动) | 保留, 标注差异 |
| MOMENTUM | 与 momentum_* / MOM_* 同族, 但为 504日加权累计口径 | 保留 |
| LIQUIDITY | 与 TURN_20 / turnover_rate_20 高度同源 | 保留, 标注冗余 |
| BTOP | 库中无账面市值比(PB) | 全新, 保留 |
| GROWTH/PROFIT/LEVERAGE | 与 NetProfit_YoY / ROE / debt_ratio 重叠 | 保留(Barra标准组合口径) |

注: 按用户确认"不是不能留下来", Barra 全部保留, 冗余关系仅在文档标注, 不去重删除。

### 1.4 计算方式 (全部基于现有数据源, 不依赖清华 .mat)

| 因子 | 公式 | 实现要点(复用现有能力) |
|---|---|---|
| BARRA_SIZE | `ln(市值代理)` | 复用 `build_marketcap_proxy_map` 点-in-time 市值代理(成交额滚动均值, 无前视) |
| BARRA_NONLINEAR_MV | `ln(size)^3` 对 `ln(size)+行业哑变量` 回归取残差 | 复用 `neutralize_regression` + `stock_classify` 行业 |
| BARRA_BETA | 个股日收益对市场收益(股票池等权/沪深300)的 250日回归斜率, 含市场 lag 项 | 扩展 `ts_BETA` 支持基准面板 |
| BARRA_MOMENTUM | 约504日加权累计超额收益(剔除近21日) | `ts_Sum` + 衰减权重 |
| BARRA_RESVOL | BETA 回归残差收益的近250日标准差 | 复用 BETA 残差序列 + `ts_Stdev` |
| BARRA_LIQUIDITY | `-ln(近21日换手率均值)` | 直接读 `trade_stock_daily.turnover_rate`, 最简 |
| BARRA_BTOP | `FN('total_equity') / 市值` (财报可用日取快照市值) | `FN` + 市值面板, asof 对齐无前视 |
| BARRA_GROWTH | `z(营收同比)+z(净利同比)` 组合 | `FN('revenue')/FN('net_profit')` 同比派生 |
| BARRA_PROFIT | `z(roe)+z(roa)+z(net_margin)` 组合 | `FN` 字段组合 |
| BARRA_LEVERAGE | `z(1/BTOP)+z(debt_ratio)` 组合 | `FN('debt_ratio')` 等 |

### 1.5 评价方式路由

- BARRA_SIZE / NONLINEAR_MV / BETA / MOMENTUM / RESVOL / LIQUIDITY → `technical` (日变连续、截面可比)
- BARRA_BTOP / GROWTH / PROFIT / LEVERAGE → `financial` (财报期对齐IC; formula 含 `FN(` 自动路由)
- 注意: 若做市值中性化, SIZE/NONLINEAR_MV 会被自身消掉, 评价时提示裸评或仅行业中性化

---

## 二、龙头因子 (7个, 只保留 1 个)

来源 `dragon_strategy/dragon_picker.py` (首板战法选股打分)。结论: 属策略层选股引擎, 多数子项不是独立因子。

| 因子 | 处理 | 原因 |
|---|---|---|
| DRAGON_DAY_CHANGE | **保留**, 基础因子, technical | 库中无"涨幅分段打分"形式因子, 不重复 |
| DRAGON_VOL_RATIO | **下架** | 与 vol_ratio_5d/10d/20 冗余 |
| DRAGON_MCAP | **下架** | 与 BARRA_SIZE 冗余, 分段打分主观 |
| DRAGON_RANK | **下架** | 策略层逻辑(依赖股票池/全市场排名), 非因子得分 |
| DRAGON_PRICE | **下架** | 绝对价格量纲不可比 |
| DRAGON_SECTOR | **下架** | 无板块日行情数据 |
| DRAGON_SCORE | **下架** | 多因子组合打分, 语义奇怪; 策略能力保留在 dragon_strategy 不删 |

实现要点: 新增 `barra`/`dragon` 基础算子时, DRAGON_DAY_CHANGE 作为 `dragon_day_change` 基类注册; 下架因子从 factor_init.py 数据清单移除并在初始化时处理已有记录。

---

## 三、微观结构因子 (10个, 保留但不处理)

- ofi_abs / large_ratio / cancel_rate / interval_cv / recovery_speed / run_length / vol_cv / direction_symmetry / limit_ratio / price_volatility_tick
- 全部登记 `period=tick, data_source=tick`。系统数据层仅日K(`trade_stock_daily`), 无逐笔/委托/快照历史数据, 本地暂无高频因子处理能力。
- 处理: **保留在库中, 标 `evaluation_type=none`(原因=缺tick数据), 本期不计算不评价**。
- 预留: 将来接入 xtdata 逐笔/快照采集后整体启用, 届时均为基础因子, 走 technical 截面评价。

---

## 四、缠论因子 (5个, 落地 3 个)

### 4.1 稳定性分层
缠论"天生模糊"主要来自: 分型确认滞后1根、笔的包含合并规则分歧、中枢事后动态修正、线段/背驰/买卖点规则最主观。因此按稳定性拆分处理。

### 4.2 量化定位与处理

| 因子 | 量化定位 | 处理 | evaluation_type |
|---|---|---|---|
| CHAN_TOP_FRACTAL 顶分型 | 形态/信号型(同 CDL): 0/1, 方向=negative | **落地** | signal |
| CHAN_BOTTOM_FRACTAL 底分型 | 形态/信号型: 0/1, 方向=positive | **落地** | signal |
| CHAN_STROKE 笔方向 | 结构状态信号: -1/0/+1, 按符号定方向 | **落地** | signal |
| CHAN_ZG / CHAN_ZD 中枢 | 动态修正 + 绝对价格量纲 | **暂缓**(不纳入本期) | none(暂缓) |

### 4.3 计算约定(稳定化)
- 顶/底分型: 仅简单 OHLC 比较(`High>两侧High 且 Low>两侧Low`), **不做包含合并**; 信号日对齐到**确认日**(T+1), 避免未来函数。与 68 个 `CDL_*` 形态同管线。
- 笔方向: 在分型序列上固定规则推笔(间隔>=4根、顶底交替、极值保留), 规则写死保证可复现。
- 中枢后续形态化方向(记入文档备选): "中枢内位置" `(close-ZD)/(ZG-ZD)`(0~1 跨股可比) 或 "上破ZG/下破ZD"突破信号。

---

## 五、ML / SVD 因子 (2个, 下架)

- ML_PROB: 每只股票独立模型滚动训练 → 无固定计算方式, 跨股概率不可比。
- SVD_HIDDEN: 隐因子/因子分解, 针对单股单独训练, 不同股票隐因子不同、无统一标签。
- 结论: **不适合作为固定基础因子, 从因子库下架**。未来规划独立"ML因子/隐因子"页面(ml_strategy 训练能力已存在), 按股票单独训练、单独评估。本期不动 ml_strategy 代码。

---

## 六、实施改动点

### 6.1 引擎层 `lib/factor_engine.py`
- 新增算子: `barra_size` / `barra_nonlinear_mv` / `barra_beta` / `barra_momentum` / `barra_resvol` / `barra_liquidity` / `barra_btop` / `barra_growth` / `barra_profit` / `barra_leverage` / `dragon_day_change` / `chan_top_fractal` / `chan_bottom_fractal` / `chan_stroke`
- 扩展 `ts_BETA` 支持基准面板(供 BARRA_BETA/RESVOL 用)
- 缠论分型/笔实现注意确认日对齐(T+1), 避免未来函数
- `BASE_OPERATOR_MAP` 注册新基类(barra_* / dragon_day_change / chan_*)

### 6.2 因子定义 `lib/factor_init.py`
- 新增 14 个因子的基础因子定义(含 base_id / formula / evaluation_type)
- 从清单移除下架因子: DRAGON_VOL_RATIO / DRAGON_MCAP / DRAGON_RANK / DRAGON_PRICE / DRAGON_SECTOR / DRAGON_SCORE / ML_PROB / SVD_HIDDEN (初始化时处理已有记录)
- 微观结构 10 个: 补标 evaluation_type=none + 原因

### 6.3 评价路由
- 新因子显式标定 evaluation_type: Barra 6个 technical / 4个 financial, 龙头 DAY_CHANGE technical, 缠论 3个 signal, 中枢2个 none
- 前端 factor.html 自动适配(已有评价方式徽章列+筛选, 无需新改)

### 6.4 文档
- 本计划落地后, 在《因子评价方式适配性审计与路由改造计划.md》阶段5 勾选

---

## 七、阶段划分

- **D1**: Barra 10 个算子 + 因子定义 + 评价路由 (收益最大) —— **✅ 已完成 (2026-08-15)**
- **D2**: 缠论 3 个 signal 因子 + 确认日对齐 —— **✅ 已完成 (2026-08-15)**
- **D3**: 龙头 DAY_CHANGE 落地 + 其余龙头/ML/SVD 下架 —— **✅ 已完成 (2026-08-15)**
- **D4**: 微观结构 10 个标 none 收尾, 全库回归(单因子评价/批量评估/多因子分析) —— **✅ 已完成 (2026-08-15)**
- **D5**: 单因子诊断增强(中性化前后IC对比/多持有期衰减/分年度IC稳定性), 见第九节 —— **✅ 已完成 (2026-08-15)**

> E 阶段(组合风险分析)已由 F 阶段(F1)落地, 详见 [因子库F阶段-综合多因子分析设计文档.md](./因子库F阶段-综合多因子分析设计文档.md); 早期规划存档见 [因子库E阶段-组合风险分析计划.md](./因子库E阶段-组合风险分析计划.md), 本文件不包含。

### D1 实施记录 (2026-08-15)
- `lib/factor_engine.py`: 新增 `ts_BarraMomentum(Close,504)`(剔除近21日、几何衰减加权超额累计) 与 `ts_RESVOL(Close,250)`(beta残差年化波动), 均为 `ts_` 前缀自动注册
- `lib/factor_init.py`: 10 个 Barra 因子 formula 由文字描述改为可计算公式; **SIZE/NONLINEAR_MV category fundamental→price_volume**(避免 category=fundamental→financial 默认路由误判)
- 关键口径: 市值代理=近20日成交额均值 `ts_Mean(Amount,20)`(与 build_marketcap_proxy_map 同口径, 点-in-time 无前视); 市场代理=截面均值收益率(与 ts_BETA 同口径)
- 分类: 全部 base_id=自身, factor_type=basic, 已由 sync_bases 注册到 factor_base(基类=参数化基类+基础因子)
- 路由: 6 个 technical / 4 个 financial(经 classify_factor_type 公式推断验证); DB evaluation_type 保持为空(默认路由正确, 无需显式回填)
- 验证: py_compile / 合成面板 evaluate(6个市场数据因子出真实值) / validate(4个财务因子) / 分类 / 路由 / DB 同步 全部通过

### D2 实施记录 (2026-08-15)
- `lib/factor_engine.py`: 新增 `ts_ChanTopFractal(High,Low)` / `ts_ChanBottomFractal(High,Low)` / `ts_ChanStroke(High,Low)` 三个缠论形态算子, 均为 `ts_` 前缀自动注册
- 确认日对齐: 分型先做 `shift(-1)` 提取原始信号, 再 `shift(1)` 对齐到确认日(T+1), 避免未来函数(验证: 信号日与原始峰值错位为0)
- 笔方向: 简化约定(不做包含合并), 同型取更极端, 交替且间隔>=4确认, 输出 -1/0/+1
- `lib/factor_init.py`: 3 个缠论因子 formula 更新为可计算表达式; CHAN_ZG/CHAN_ZD 保持文字formula + 评价标签回填为 signal(3个) / none(2个)
- DB 运行 run_init 后路由: 3 signal / 2 none, 全部验证通过

### D3 实施记录 (2026-08-15)
- `lib/factor_engine.py`: 新增 `ts_DragonDayChange(Close)` 算子(涨幅分段打分: 5-9%线性加权, >9%减分0.5)
- `lib/factor_init.py`: DRAGON_DAY_CHANGE formula 更新; 下架 6 个龙头因子 + 2 个 ML/SVD 因子; 清理 SPECIAL_CLASSIFY 映射
- `run_init` 硬删除列表含 12 个因子, 幂等执行; 因子总数 255→247, 基类表清理 7 个伪基类
- 验证: 涨幅分打分正确(5%→0.5, 8%→0.8, 12%→0.5); 8 下架因子全部不在因子库/基类表; DRAGON_DAY_CHANGE 路由 technical

### D4 实施记录 (2026-08-15)
- 微观结构 10 个因子回填 evaluation_type=none, 运行 run_init 后验证 10 个全部 et=none
- 全库回归: 分类分布 technical=106/signal=74/financial=26/none=22/technical_ts=19(合理)
- 14 新增因子定向评估(含 Barra 10 + 缠论 3 + 龙头 1): 3 个 signal 出 hit_rate, 其余因数据量不足输出 no_data(非 bug)
- 全库批量评估冒烟: 39 ok + 22 not_evaluable 显式列出 + 1 no_data, 无 error

### D5 实施记录 (2026-08-15)
- `lib/factor_evaluator.py`: 新增 `compute_ic_decay()`(多持有期IC衰减, 1/5/10/20日) 与 `compute_yearly_ic()`(分年度IC稳定性聚合)
- `routes/factor.py` /evaluate: 在 technical/technical_ts 分支接入 D5 诊断; neutralize 非 none 时追加未中性化IC对比
- `templates/factor.html`: 评价结果区新增 3 列诊断卡片(中性化前后对比 / 持有期衰减 table / 分年度IC table), 仅在 technical/technical_ts 且数据存在时显式
- 验证: 合成面板 40 股 420 日, 衰减曲线 1/5/10/20 日产出真实 IC 值, 分年度 2022/2023 产出; py_compile 全部通过

## 八、风险与注意

1. Barra 用市值中性化会消掉 SIZE/NONLINEAR_MV 自身 → 评价页提示裸评或仅行业中性化
2. BARRA_BETA/MOMENTUM 需市场基准(股票池等权/沪深300), 基准选取会影响结果
3. 缠论分型信号滞后 1 根, 必须对齐确认日, 否则引入未来函数
4. 下架因子若被历史评价结果/组合引用, 需在 DB 侧处理(保留历史记录, 仅标记不可用)
5. 中文注释 UTF-8, 不引入 emoji

---

## 九、单因子诊断增强 (D5) —— 2026-08-15 用户确认追加

> 状态: **D5 已落地 (2026-08-15)**。背景: 对照清华专业流程(gl23_day2_M.ipynb), 当前单因子评价已覆盖 因子计算→预处理(中性化)→有效性检验(IC/IR/分层/多空), 但缺 2 个诊断视角 + 1 个稳定性视图。这三项均为**单因子诊断增强**(改评价输出+图表), **不属于风险模型**(风险模型独立为 E 阶段, 已由 F 阶段 F1 落地)。

### 9.1 三项增强

| 增强 | 内容 | 对应清华 |
|---|---|---|
| 中性化前后 IC 对比 | 同一因子同时输出"原始IC"与"中性化后IC", 判断因子收益是真 alpha 还是风格暴露 | `F_GetResidual` 后比较 f1_stand vs f1_stand2 绩效 |
| 多持有期衰减 | IC 随持有期(1/5/10/20 日)变化曲线, 辅助选择最优调仓周期 | `GetRets` 的 `delayNum` 参数思路 |
| 分年度 IC 稳定性 | 按年度聚合 IC, 看因子是否逐年稳定, 避免靠单一年份撑起来 | 行业标准做法 |

### 9.2 实施要点
- 中性化前后对比: 在 `evaluate_single_factor` 中, 当配置了中性化(行业/板块/概念/市值)时, 额外输出"未中性化 IC"与"中性化后 IC"两个标量供前端对比展示; 中性化为 none 时该项不重复输出
- 多持有期衰减: 复用截面 IC 管线, 对持有期 horizon ∈ {1,5,10,20} 分别计算 IC 均值, 输出衰减曲线数据
- 分年度稳定性: 对已有 ic_series 按年份聚合(mean/std/正IC占比), 输出逐年表
- 前端 factor.html: 单因子评价结果区新增"中性化前后对比"卡片、"持有期衰减"折线、"分年度IC"表格(若已有图表组件则复用)

### 9.3 注意
- 持有期衰减的多持有期计算会增加耗时, 建议只在用户显式勾选时启用
- 分年度稳定性仅在样本跨 ≥2 个完整年度时有意义, 样本不足时前端提示
- 中文注释 UTF-8, 不引入 emoji
