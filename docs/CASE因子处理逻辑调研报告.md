# 各CASE因子处理逻辑调研报告

> 创建时间: 2026-08-10
> 任务: 因子库优化目标任务 - 任务二
> 状态: **已完成** — 调研结论已落地(评价方式路由改造/表达式设计/因子库分类), 见 [因子评价方式适配性审计与路由改造计划.md](./因子评价方式适配性审计与路由改造计划.md) 与 [因子库F阶段-综合多因子分析设计文档.md](./因子库F阶段-综合多因子分析设计文档.md)
> 调研范围: 10个CASE工程 + 主系统评价引擎

---

## 一、各CASE因子处理能力对比矩阵

| CASE工程 | 因子数 | 计算方式 | 评价方式 | 预处理 | 组合方式 | 数据频率 | 特有功能 |
|----------|--------|---------|---------|--------|---------|---------|---------|
| ml_strategy / 机器学习因子挖掘 | 50+ | Talib+Python | 无(供ML) | MAD+Z-score+中性化 | ML模型(XGBoost) | 日K | 6类因子分类体系, 交互因子 |
| morning_brief | 复用ml_strategy | 复用 | IC+分层 | 复用 | 等权 | 日K | 晨会因子报告生成 |
| CASE-C-多因子选股 | 10 | 纯Python | IC/IR/分层回测/多空 | MAD+Z-score+行业中性化 | 等权/IC加权/Lasso | 日K(xtquant) | 完整pipeline教学 |
| CASE-网格与多因子 | 8 | Talib | 因子打分选股 | 无 | 加权求sum(FACTOR_CONFIG) | 日K | 网格策略+因子选股联动 |
| CASE-基于RL交易策略-2 | 10 | Numpy(tick级) | RF分类 | 无 | 单分类器 | Tick | 主力行为识别, RL做市商模拟 |
| CASE-缠论精华量化 | 7 | 结构分析+Talib.MACD | 策略回测 | 无 | 信号触发 | 日K | 缠论笔/中枢/三买三卖 |
| dragon_strategy | 6 | 手工打分 | 筛选排名 | 硬过滤(ST/新股) | 加权打分 | 日K | 板块共振, 龙头识别 |
| CASE-Talib技术指标库 | 158 | Talib | 无(演示库) | 无 | 无 | 日K | 68种CDL形态, MACD底背离 |
| qinghua WorldQuant | 5 | ts_*算子 | PerformanceWithCost | ts_Decay时间衰减 | 表达式组合 | 日K | WQ表达式因子体系 |
| Barra风格因子 | 10 | 回归暴露 | 因子收益分析 | 无 | 风险模型 | 日K+财务 | 多因子风险分解 |
| CASE-论文复现(MASTER) | 50+ | Talib+Python | MASTER截面预测 | RobustZScoreNorm | ML模型 | 日K | MASTER框架, 鲁棒标准化 |
| **主系统 factor_engine** | **12+表达式** | **Python+表达式** | **IC/IR/分层回测** | **MAD+Z-score+中性化** | **等权/IC加权/Lasso** | **日K** | **表达式引擎evaluate_expression** |

---

## 二、各CASE详细调研

### 1. ml_strategy / CASE-机器学习因子挖掘 (feature_engine.py)

**文件**: `CASE-AI量化系统/ml_strategy/feature_engine.py` / `CASE-机器学习因子挖掘/feature_engine.py` / `CASE-论文复现与策略进化/feature_engine.py`
(三处内容基本一致, 是同一套特征工程的不同副本)

**因子计算方式**:
- 数据: OHLCV日K线
- 计算: Python + Talib库
- 50+因子, 分6类:
  - 价量(10): ret_1d/3d/5d/10d, amplitude_5d/10d, vol_ratio_5d/10d, price_volume_corr_10d, turnover_change_5d
  - 动量(8): momentum_5d/10d/20d/60d, momentum_slope_10d/20d, momentum_accel_10d/20d
  - 波动率(6): atr_norm_14, hist_vol_10d/20d/60d, vol_change_10d/20d
  - 技术指标(12): rsi_14/6, adx_14, macd_dif/signal/hist, bbands_position, kdj_k/d, cci_14, willr_14, obv_slope_10d
  - 均线形态(11): ma5/10/20/60_bias, ma_bull_score, upper/lower_shadow_ratio, body_ratio, new_high/low_20d
  - 交互因子(6): mom_vol_cross, adx_rsi_cross, vol_ratio_mom_cross, rsi_bbands_cross, macd_adx_cross, vol_mom_accel_cross

**评价方式**: 本模块不含评价, 供下游ML模型使用

**预处理**(在`1-MASTER数据与因子.py`中):
- MAD去极值(3倍中位绝对偏差)
- Z-score标准化
- 行业市值中性化

**组合方式**: XGBoost/LightGBM机器学习模型

**数据频率**: 日K

**特有功能**:
- 6类因子分类体系(FACTOR_TAXONOMY)
- 交互因子(因子间非线性关系)
- SHAP因子重要性分析

---

### 2. CASE-C-多因子选股

**文件**: `factor_lib.py` + `preprocessor.py` + `layered_backtest.py` + `synthesizer.py`

**因子计算方式**:
- 数据: OHLCV日K线 (通过xtquant/xtdata下载)
- 计算: 纯Python (不依赖Talib)
- 10个核心因子:
  - 动量: MOM_1M(21日), MOM_3M(63日), MOM_6M(126日) — `close.pct_change()`
  - 反转: REV_5D — `-close.pct_change(5)`
  - 波动率: VOL_20/60 — `-returns.tail(N).std() * sqrt(250)`
  - 流动性: LIQ_20 — `-log(amount.tail(20).mean())`, TURN_20 — `-volume/mean(volume)`
  - 技术: RSI_14 — `RSI(close,14)-50`, BIAS_20 — `-(close-MA20)/MA20`

**评价方式** (layered_backtest.py):
- 单因子IC测试: Pearson IC + Spearman Rank IC
- IR = IC均值 / IC标准差
- 5层分层回测: 按因子值分5层, 看各层收益单调性
- 多空收益 = 第5层 - 第1层
- 调仓周期: 21日, 最小预热: 130日

**预处理** (preprocessor.py):
- 三件套: MAD去极值(3倍) → Z-score标准化 → 行业中性化(行业内Z-score)
- `preprocess_factors()` 一行调用

**组合方式** (synthesizer.py):
- 等权合成: `factor_df.mean(axis=1)`
- IC加权合成: 按各因子IC值加权
- Lasso回归合成: sklearn.linear_model.Lasso

**数据频率**: 日K

**特有功能**: 完整的因子pipeline教学(计算→预处理→评价→合成), 是主系统factor_engine.py的主要来源

---

### 3. CASE-网格与多因子

**文件**: `factor_engine.py`

**因子计算方式**:
- 数据: OHLCV日K线
- 计算: Talib库
- 8个因子:
  - momentum_20d/60d: `talib.ROC(c, 20/60)`
  - volatility: `talib.ATR(h,l,c,14) / close`
  - rsi_14: `talib.RSI(c, 14)`
  - adx_14: `talib.ADX(h,l,c, 14)`
  - turnover_ratio: `volume[-1] / talib.SMA(v, 20)`
  - price_position: `(close - low_60) / (high_60 - low_60)`
  - macd_signal: `talib.MACD(c)[2]` (柱状图)

**评价方式**: 因子打分(加权求和), 按得分排名选股

**预处理**: 无(直接用原始值打分)

**组合方式**: FACTOR_CONFIG配置权重, 加权求和
```
score = Σ(weight_i × direction_i × factor_i)
```
权重: momentum_20d=0.20, momentum_60d=0.15, volatility=0.15, rsi_14=0.10, adx_14=0.10, turnover_ratio=0.10, price_position=0.10, macd_signal=0.10

**数据频率**: 日K

**特有功能**: 因子选股与网格策略联动

---

### 4. CASE-基于RL的交易策略-2 (主力行为识别)

**文件**: `7-主力行为识别.py`

**因子计算方式**:
- 数据: Tick级数据 (price, volume, direction, timestamp, cancel, order_type)
- 计算: Numpy
- 10个微观结构因子:
  - ofi_abs: 订单流不平衡 `|buy_vol - sell_vol| / total_vol`
  - large_ratio: 大单比例(成交额>3倍均值)
  - cancel_rate: 撤单率
  - interval_cv: 成交间隔变异系数
  - recovery_speed: 价格冲击恢复速度
  - run_length: 方向持续性(连续同向交易平均长度)
  - vol_cv: 成交量变异系数
  - direction_symmetry: 买卖笔数对称性
  - limit_ratio: 限价单比例
  - price_volatility: 价格波动率(归一化)

**评价方式**: RandomForest分类器(识别主力/散户/拆单), 非IC评价

**预处理**: 无

**组合方式**: 单一分类器, 无多因子组合

**数据频率**: Tick级

**特有功能**: RL做市商行为模拟器, tick级高频特征提取

---

### 5. CASE-缠论精华量化

**文件**: `chan_analyzer.py`

**因子计算方式**:
- 数据: OHLCV日K线
- 计算: 结构分析(K线包含→分型→笔→中枢→买卖点) + Talib.MACD
- 7个因子:
  - chan_buy1/2/3: 一/二/三类买点(0/1信号)
  - chan_sell1/2/3: 一/二/三类卖点(0/1信号)
  - chan_divergence: 背驰(MACD柱状图与价格背离)

**核心算法**:
- `_identify_bi()`: 基于分型的笔识别
- `_identify_zhongshu()`: 中枢识别(至少3笔重叠)
- `_detect_third_buy/sell()`: 第三类买卖点检测

**评价方式**: 策略回测(非IC/分层)

**预处理**: 无

**组合方式**: 信号触发(买卖点出现即交易)

**数据频率**: 日K

**特有功能**: 缠论结构分析体系, 完全不同于传统量化因子

---

### 6. dragon_strategy (龙头战法)

**文件**: `CASE-AI量化系统/dragon_strategy/dragon_picker.py`

**因子计算方式**:
- 数据: OHLCV日K + 市值 + 涨幅榜
- 计算: 手工打分函数
- 6个打分维度:
  - 当日涨幅(0.5分, >9%扣分)
  - 量比(1.5分)
  - 市值(50-200亿最优, 1.0分)
  - 涨幅榜排名(前5=1.0分, 前20=0.5分)
  - 价格(<20元+0.5, 20-30元+0.2)
  - 板块共振(加分)

**评价方式**: 筛选+排名(filter_dragon_candidates → calc_dragon_score)

**预处理**: 硬过滤(ST股, 次新股<60日, 涨停>9.5%)

**组合方式**: 加权打分求和

**数据频率**: 日K

**特有功能**: 板块共振(板块涨幅+上涨家数占比), 龙头股识别

---

### 7. CASE-Talib技术指标库

**文件**: `2-Talib基础用法.py`, `3-K线形态识别.py`, `9-形态选股雷达.py`

**因子计算方式**:
- 数据: OHLCV日K线
- 计算: Talib库
- 158个指标:
  - 均线类(9): SMA/EMA/DEMA/TEMA/WMA/KAMA/MAMA/SAR/TRIMA
  - 动量类(11): RSI/MACD/ADX/CCI/KDJ/AROON/MFI/UO/STOCH等
  - 波动率(3): ATR/NATR/TRANGE
  - 成交量(3): OBV/AD/ADOSC
  - 价格(4): AVGPRICE/MEDPRICE/TYPPRICE/WCLPRICE
  - 统计(5): BETA/CORREL/STDDEV/VAR/LINREG
  - 周期(6): HT_*希尔伯特变换
  - K线形态(68): CDL_* (0/100离散值)
  - 形态确认(9): CDL_*_CONFIRMED

**评价方式**: 无(演示库), `9-形态选股雷达.py`有MACD底背离+形态双重共振扫描

**预处理**: 无

**组合方式**: 无

**数据频率**: 日K

**特有功能**: 68种K线形态识别, MACD底背离检测, 全市场截面扫描

---

### 8. qinghua 清华量化教学体系 (重点解析)

**文件目录**: `qinghua/` 下5个notebook, 构成完整的量化因子教学体系

| notebook | 主题 | 核心内容 |
|----------|------|---------|
| day1_A.ipynb | 基础:因子构建与评价 | 算子定义/PerformanceWithCost/参数优化/多因子组合 |
| day2_M.ipynb | 进阶:Barra中性化与ML | Barra风险暴露/F_GetResidual/IdioRet/LightGBM组合 |
| gl23_day2_fin.ipynb | 财务因子 | PE/PB/ROE/ROA/杜邦分析/行业中性化 |
| gl23_day2_min.ipynb | 分钟级因子 | 日内波动率/集体行为/Smart因子/分钟转日频 |
| gl23_day3_tick.ipynb | Tick级因子 | 5档买卖价量/订单簿因子/因子去冗余 |

#### 8.1 day1_A.ipynb - 基础因子构建与评价

**数据加载**: 从.mat文件加载面板数据
- Px.mat: Open/High/Low/Close/Volume/Value/TotalRet/VWAP (index=日期, columns=股票代码)
- 删除新股前30日数据 (listed = Volume.cumsum().shift(30))
- IdioRet = TotalRet - 截面均值 (特质收益)

**算子定义** (与主系统factor_engine.py一致):
- ts_Delay/ts_Mean/ts_Decay/ts_DecayExp/ts_Max/ts_Min/ts_Delta/ts_Stdev/ts_Sum/ts_Kurtosis/ts_Skewness/ts_Median
- pn_TransNorm: 截面排名→正态分位数变换 (rank→norm.ppf)

**核心评价函数 PerformanceWithCost**:
```python
def PerformanceWithCost(f1, TotalRet, delayNum, cost, fig, SDate, EDate):
    f1_stand = pn_TransNorm(f1.round(4))        # 截面标准化
    f1_stand_D2 = ts_Delay(f1_stand, delayNum)  # 延迟delayNum天(信息日t0→交易日t1→收益日t2)
    factorRet = f1_stand_D2 * TotalRet           # 因子收益 = 持仓 × 个股收益
    dire = 1
    if factorRet.mean(1).mean() < 0:             # 自动判断多空方向
        factorRet = factorRet * -1
        dire = -1
    Cost = GetCost(f1_stand_D2, cost)            # 交易成本 = cost × |持仓变化|
    factorRet = factorRet - Cost                 # 扣除成本
    sr1 = factorRetLine.mean() / factorRetLine.std() * 15  # 年化夏普(×15≈√250/√16)
    ret1 = factorRetLine.mean() * 250            # 年化收益
    # 返回: SR, AR, TO(换手率), Dir(方向)
```

**参数优化 (Optuna)**:
```python
def objective(trial):
    x = trial.suggest_int("x", 2, 20)    # 短期衰减周期
    y = trial.suggest_int("y", 10, 50)   # 长期衰减周期
    f1 = -1*ts_Decay((ts_Decay(Volume,x)-ts_Decay(VWAP,x))/VWAP*(High-Low), y)
    [sr1,...] = PerformanceWithCost(f1, TotalRet, delayNum, cost, 0, SDate, EDate)
    return sr1  # 最大化夏普比率
study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=15)
```

**多因子组合方法** (4种):
| 方法 | 权重 | 实现 |
|------|------|------|
| 等权 | [1,1,1,...] | F_CompositeF(fs_v, fs_w) |
| 夏普加权 | srs(各因子SR) | F_CompositeF(fs_v, srs) |
| 收益加权 | rets(各因子AR) | F_CompositeF(fs_v, rets) |
| Markowitz优化 | w_mar(最大夏普) | scipy.optimize.minimize(最大夏普, 约束sum(w)=1, max(w)<=0.5) |

**10个WQ因子表达式**:
```python
f_formulas = [
    '-1*ts_Decay((ts_Decay(Close,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)',
    '-1*ts_Decay(IdioRet*(Volume/ts_Delay(Volume,1)),40)',
    '-1*ts_Decay(IdioRet*(High-Low)/Close*(Volume/ts_Delay(Volume,1)),60)',
    '-1*ts_Decay(VWAP/Close*(High-Low)/Close*(Volume/ts_Delay(Volume,1)),10)',
    '-1*ts_Mean((ts_Decay(Close,10)-ts_Decay(VWAP,10))/VWAP*(High-Low)/Close,20)',
    '-1*ts_Decay((ts_Decay(Value,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)',
    '-1*ts_Decay((ts_Decay(Volume,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)',
    '-1*ts_Decay((ts_Decay(High,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)',
    '-1*ts_Decay((ts_Decay(TotalRet,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)',
    '-1*ts_Decay(Volume/(High-Low),20)',
]
# 用eval()批量计算
fs_v = [eval(v) for v in f_formulas]
```

#### 8.2 day2_M.ipynb - Barra中性化与机器学习

**Barra因子风险暴露**:
```python
# 从BarraFactors.mat加载10个Barra风格因子
# 因子暴露 = 持仓权重 × Barra因子值 的截面均值
factor_exposure_factor[barraF] = (f1_stand * barraFV).mean(1)  # 因子暴露
factor_exposure_port[barraF] = (f1_port * barraFV).sum(1)      # 持仓暴露
```

**Barra中性化 F_GetResidual**:
```python
def F_GetResidual(x, y, SDate, EDate):
    # 逐日回归: y = beta * x + residual, 取残差作为中性化后的因子
    for v in range(len(x.index)):
        x_ = np.array(x.iloc[v]).reshape((-1, 1))
        y_ = np.array(y.iloc[v])
        Model = LinearRegression().fit(x_, y_)
        residual.iloc[v] = y_ - Model.predict(x_)
    return residual

# 逐个Barra因子中性化
for v in range(len(barraFV)):
    f1_stand2 = F_GetResidual(barraFV[v], f1_stand2, SDate, EDate)
    f1_stand2 = pn_TransNorm(f1_stand2)
```

**IdioRet 特质收益** (来自BarraRiskStats.mat):
- 剔除Barra风格因子影响后的个股残差收益
- 可用于评价因子的纯alpha能力

**LightGBM机器学习组合**:
```python
# 1. 矩阵转表格 (F_mat2fit): 面板数据→长表(date, code, f1...f5, Y, Vol)
# 2. 训练LightGBM回归模型 (预测未来pre_num=20日收益)
# 3. 表格转矩阵 (F_fit2mat): 预测值→面板
# 4. 评价: PerformanceWithCost(CF_lgb, TotalRet, ...)
params = {
    'boosting_type': 'gbdt', 'objective': 'regression',
    'num_leaves': 10, 'learning_rate': 0.1,
    'feature_fraction': 0.9, 'bagging_fraction': 0.8,
}
gbm = lgb.train(params, lgb_train, num_boost_round=100,
                valid_sets=lgb_valid, early_stopping_rounds=10)
```

#### 8.3 gl23_day2_fin.ipynb - 财务因子

**数据源**: CSV财务报表 (PIT时点数据, 避免未来函数)
- bs.csv: 资产负债表 (NetAsset, T_ASSETS, T_LIAB, T_SH_EQUITY等)
- is.csv: 利润表 (NetProfitTTM, N_INCOME, T_REVENUE, COGS等)
- cs.csv: 现金流量表 (N_CF_OPERATE_A等)

**财务因子计算**:
| 因子 | 公式 | 数据来源 |
|------|------|---------|
| PE | TotalCap / NetProfitTTM | 市值/净利润 |
| PB | TotalCap / NetAsset | 市值/净资产 |
| ROE | N_INCOME / T_SH_EQUITY | 净利润/股东权益 |
| ROA | ope_m / oa_m | 营业利润/总资产 |
| NPM | ope_m / rv_m | 净利润/销售额 (销售净利率) |
| ATR | rv_m / oa_m | 销售额/总资产 (资产周转率) |
| EM | oa_m / noa_m | 总资产/净资产 (权益乘数) |
| ROE_chg | ROE - ROE_1 | ROE变化 (fin_Delay取上期) |

**关键函数**:
- `fin_Delay(tmp, val, Nrd)`: 获取前Nrd期财报数据 (shift + code匹配, 避免未来函数)
- `F_fit2mat2(df, col, date)`: 表格数据转面板矩阵 (unstack)
- `getTargetMatrix(a, b)`: 对齐到目标矩阵的index/columns, ffill填充

**行业中性化** (按BarraIndLabel分组):
```python
def groupby_Rank(roe, BarraIndLabel):
    out = roe.copy() * np.nan
    for v in np.unique(BarraIndLabel):  # 逐行业
        tmp = roe.copy()
        tmp[BarraIndLabel != v] = np.nan
        tmp = tmp.rank(ascending=True, pct=True, axis=1)  # 行业内排名
        out[BarraIndLabel == v] = tmp[BarraIndLabel == v]
    return out
# 用法: pe_groupNorn = groupby_Rank(pe, BarraIndLabel)
```

#### 8.4 gl23_day2_min.ipynb - 分钟级因子

**数据加载**: 分钟K线 (.mat文件, GetMinuData)
- 降采样: 分钟→5min (resample('5T'))
- VWAP = Amount / Volume

**分钟因子**:
| 因子 | 公式 | 含义 |
|------|------|------|
| std_Amount | -ts_Stdev(Amount, 20) | 日内成交额波动率(取负) |
| 集体一致交易 | Volume_daily_col / volume_daily | 一致卖出K线成交量占比 |
| Smart因子 | VWAP[S > quantile(0.8)] | 大单VWAP (S=delta/sqrt(Volume)) |
| VWAP/Volume-1 | 截面比值 | 分钟级价量关系 |

**分钟转日频** (6种聚合方式):
```python
for v in all_factors.keys():
    all_factors_daily[v + '_last'] = all_factors[v].resample('1D').last()
    all_factors_daily[v + '_mean'] = all_factors[v].resample('1D').mean()
    all_factors_daily[v + '_high'] = all_factors[v].resample('1D').max()
    all_factors_daily[v + '_low'] = all_factors[v].resample('1D').min()
    all_factors_daily[v + '_std'] = all_factors[v].resample('1D').std()
    all_factors_daily[v + '_median'] = all_factors[v].resample('1D').median()
```

#### 8.5 gl23_day3_tick.ipynb - Tick级因子

**数据加载**: h5py读取H5文件 (5档买卖价量)
- BidPrice0-4 / BidVolume0-4 (买方5档)
- AskPrice0-4 / AskVolume0-4 (卖方5档)
- LastPrice / Volume / Amount

**Tick中间数据**:
- midPrice0 = (AskPrice0 + BidPrice0) / 2
- midPrice1 = (AskAmount0 + BidAmount0) / (AskVolume0 + BidVolume0)
- spread0 = AskPrice0 - BidPrice0 (买卖价差)
- AskThick = AskVolumnSum / (AskDistanse * 100) (订单簿厚度)

**Tick因子** (15+个):
| 因子类别 | 因子示例 | 含义 |
|---------|---------|------|
| 量价缺口 | tickGap0, tickGapSum | 买方挂单占比 |
| 中间价比 | midOnmid0/1/2 | 不同中间价之比 |
| 波动/价差 | stdOnSpread0-5 | 价格波动/买卖价差 |
| 成交/挂单 | volOnThick | 成交量/总挂单量 |
| 收盘/中间 | closeOnMid0/1/2 | 收盘价偏离中间价 |
| 收盘/VWAP | closeOnVwap | 收盘价偏离VWAP |
| 距离缺口 | DistanseGap | 买卖方订单簿距离差 |

**因子去冗余 cutFactors**:
```python
def cutFactors(srs, returns2, corGap):
    cor = returns2.corr()  # 因子收益相关性矩阵
    deleList = []
    for vvv in range(len(srs)):
        if vvv in deleList: continue
        cor_ = cor[vvv]
        cor_ = cor_[cor_.index != vvv]
        cor_ = cor_[cor_.values > corGap]  # 相关性>0.7的剔除
        deleList += list(cor_.index)
    return srs[~srs.index.isin(deleList)]
```

**增量因子筛选**: 与旧因子相关性对比
- cor_max = cor[tick_factorRet, old_factor].max(0)
- 筛选 cor_max < 0.6 的因子作为增量因子

---

### 9. Barra 风格因子

**文件**: `qinghua/BarraFactors.mat`, `qinghua/BarraRiskStats.mat`

**因子计算方式**:
- 数据: 日K + 财务数据
- 计算: 回归暴露(时间序列回归 + 截面回归)
- 10个风格因子:
  - BARRA_BETA: 个股vs市场Beta
  - BARRA_SIZE: 市值因子(log市值)
  - BARRA_MOMENTUM: 动量因子
  - BARRA_RESVOL: 残差波动率(去除Beta后的波动)
  - BARRA_BTOP: 账面市值比
  - BARRA_GROWTH: 成长因子
  - BARRA_LEVERAGE: 杠杆因子
  - BARRA_LIQUIDITY: 流动性因子
  - BARRA_PROFIT: 盈利因子
  - BARRA_NONLINEAR_MV: 非线性市值

**评价方式**: 因子收益率分析(截面回归系数), IdioRet特质收益

**预处理**: F_GetResidual逐Barra因子回归中性化

**组合方式**: 风险模型(因子协方差矩阵), Markowitz优化

**数据频率**: 日K + 财务(季度)

**特有功能**: 多因子风险分解, IdioRet特质收益, BarraIndLabel行业分类

---

### 10. CASE-论文复现与策略进化 (MASTER)

**文件**: `feature_engine.py`, `1-MASTER数据与因子.py`, `master.py`

**因子计算方式**: 同ml_strategy(50+因子, Talib+Python)

**评价方式**: MASTER截面预测模型(多源数据自适应)

**预处理** (核心特色):
- RobustZScoreNorm (MASTER方法): 截面排名→正态分位数变换→Z-score
- 对比: MAD+Z-score (华泰标准方法)
- 行业市值中性化

**组合方式**: ML模型(MASTER/XGBoost)

**数据频率**: 日K

**特有功能**: MASTER框架, 鲁棒标准化(RobustZScoreNorm), 因子相关性分析+冗余因子识别

---

### 11. 主系统 factor_engine.py (当前评价引擎, 重点解析)

**文件**: `CASE-AI量化系统/lib/factor_engine.py` (546行)

**合并来源**: WorldQuant ts_*算子(清华day1_A) + CASE-C预处理/IC/分层 + 表达式安全解析

#### 11.1 模块结构 (8大功能块)

```
factor_engine.py
├── 一、ts_* 时序算子 (12个)        ← 来源: qinghua/day1_A.ipynb
├── 二、cs_* 截面算子 (3个)         ← 来源: qinghua + 华泰规划
├── 三、因子预处理三件套             ← 来源: CASE-C/preprocessor.py
├── 四、IC/IR 评价                   ← 来源: CASE-C/synthesizer.py
├── 五、因子合成 (3种)              ← 来源: CASE-C/synthesizer.py
├── 六、分层回测                     ← 来源: CASE-C/layered_backtest.py
├── 七、表达式安全解析               ← 主系统自研
└── 八、基础因子计算 (12个)          ← 来源: CASE-C/factor_lib.py + 主系统
```

#### 11.2 ts_* 时序算子详解 (12个)

| 算子 | 实现 | min_periods | 与清华差异 |
|------|------|------------|-----------|
| ts_Delay(df, n) | df.shift(n) | - | 一致 |
| ts_Mean(df, n) | rolling(n).mean() | 1 | 一致 |
| ts_Decay(df, n) | rolling.apply(线性衰减权重) | 1 | 清华用循环累加, 效果一致 |
| ts_DecayExp(df, n) | rolling.apply(正态分位数权重) | 1 | 一致 |
| ts_Max/ts_Min(df, n) | rolling(n).max/min() | 1 | 一致 |
| ts_Delta(df, n) | df - df.shift(n) | - | 一致 |
| ts_Stdev(df, n) | rolling(n).std() | 2 | 一致 |
| ts_Sum(df, n) | rolling(n).sum() | 1 | 一致 |
| ts_Kurtosis(df, n) | rolling(n).kurt() | 4 | 一致 |
| ts_Skewness(df, n) | rolling(n).skew() | 3 | 一致 |
| ts_Median(df, n) | rolling(n).median() | 1 | 一致 |

**注意**: 所有算子接受DataFrame (index=日期, columns=股票), 返回同形状DataFrame

#### 11.3 cs_* 截面算子详解 (3个)

| 算子 | 实现 | 用途 |
|------|------|------|
| cs_Rank(df) | df.rank(axis=1, pct=True) | 截面排名(0~1) |
| cs_Zscore(df) | (df - row_mean) / row_std | 截面Z-score标准化 |
| cs_TransNorm(df) | norm.ppf(rank.clip(0.001, 0.999)) | 截面排名→正态分位数变换 |

**注意**: 截面算子沿 axis=1 (跨股票) 操作, 每行是一个时间截面

#### 11.4 因子预处理三件套

```python
# 1. MAD去极值 (中位数 ± 3×1.4826×MAD)
def winsorize_mad(series, n=3.0):
    median = series.median()
    mad = (series - median).abs().median()
    upper = median + n * 1.4826 * mad
    lower = median - n * 1.4826 * mad
    return series.clip(lower=lower, upper=upper)

# 2. Z-score标准化
def zscore(series):
    return (series - series.mean()) / series.std(ddof=1)

# 3. 行业中性化 (行业内Z-score)
def industry_neutralize(factor_series, industry_map):
    for ind, group in df.groupby("industry"):
        result[group.index] = zscore(group["factor"])

# 一键预处理
def preprocess_factors(factor_df, industry_map=None, neutralize=True):
    for col in factor_df.columns:
        factor_df[col] = winsorize_mad(factor_df[col])
        if neutralize and industry_map:
            factor_df[col] = industry_neutralize(factor_df[col], industry_map)
        else:
            factor_df[col] = zscore(factor_df[col])
```

**与清华差异**:
- 清华用 pn_TransNorm (rank→norm.ppf) 做截面标准化
- 主系统用 MAD+Z-score (华泰标准方法)
- 主系统支持行业中性化, 清华用 groupby_Rank (行业内排名)

#### 11.5 IC/IR 评价

```python
# 单期IC (信息系数)
def calc_ic(factor_series, future_return, method="spearman"):
    # method: "pearson" 或 "spearman"
    return df["f"].corr(df["r"], method=method)

# IR = IC均值 / IC标准差
def calc_ir(ic_series):
    return ic_series.mean() / ic_series.std(ddof=1)
```

**与清华差异**:
- 清华的 PerformanceWithCost 用 factorRet = factor × TotalRet 直接算收益
- 主系统用 IC (因子值与未来收益的相关系数) 评价
- 清华输出 SR/AR/TO/Dir, 主系统输出 IC/IR

#### 11.6 因子合成 (3种)

| 方法 | 函数 | 实现 |
|------|------|------|
| 等权 | equal_weight_synthesis(df) | df.mean(axis=1) |
| IC加权 | ic_weighted_synthesis(df, ic_dict) | Σ(ic_i × factor_i) / Σ|ic_i| |
| Lasso回归 | lasso_synthesis(X_train, y_train, X_predict) | sklearn.Lasso预测 |

#### 11.7 分层回测

```python
# 单期分层回测 (简化版)
def run_layered_backtest(factor_values, future_returns, n_layers=5):
    df["layer"] = pd.qcut(df["f"], n_layers, labels=False, duplicates="drop")
    layer_mean = df.groupby("layer")["r"].mean()
    long_short = layer_mean[最高层] - layer_mean[最低层]
    # 返回: {layer_returns, ic, long_short}

# IC时序回测 (多期)
def run_ic_timeseries(prices_panel, calc_factor_fn, rebal_period=21, min_warmup=130):
    for end_idx in rebal_dates:
        factor_df = calc_factor_snapshot(prices_panel, end_idx)
        factor_processed = preprocess_factors(factor_df, industry_map)
        future_ret = calc_next_period_returns(prices_panel, end_idx, rebal_period)
        alpha = factor_processed.mean(axis=1)  # 等权合成
        ic = calc_ic(alpha, future_ret)
    # 返回: {ic_series, ic_mean, ic_std, ir, rank_ic_series, ...}
```

**与CASE-C差异**:
- CASE-C的layered_backtest.py是完整版(支持IC加权walk-forward, Top-N回测, 基准对照)
- 主系统是简化版(单期分层, 多期IC时序)
- CASE-C参数: rebal_period=21, min_warmup=130, n_layers=5, ic_lookback=6

#### 11.8 表达式安全解析引擎

**白名单机制**:
```python
# 允许的函数 (15个)
_SAFE_FUNCTIONS = {
    "ts_Delay", "ts_Mean", "ts_Decay", "ts_DecayExp", "ts_Max", "ts_Min",
    "ts_Delta", "ts_Stdev", "ts_Sum", "ts_Kurtosis", "ts_Skewness", "ts_Median",
    "cs_Rank", "cs_Zscore", "cs_TransNorm",
}

# 允许的字段 (11个)
_SAFE_FIELDS = {
    "Open", "High", "Low", "Close", "Volume", "Amount", "VWAP",
    "Turnover", "PE", "PB", "ROE",
}

# 允许的内置 (5个)
_SAFE_NAMES = {"abs", "max", "min", "pow", "round", "np", "pd"}
```

**验证逻辑 validate_expression**:
1. 检查空表达式
2. 检查危险字符: `[;{}\[\]]`
3. 检查危险关键字: `import|exec|eval|open|file|os|sys|subprocess`
4. 提取所有标识符, 逐个检查是否在白名单中

**执行逻辑 evaluate_expression**:
```python
def evaluate_expression(expr, panel):
    # 1. 验证表达式
    is_valid, msg = validate_expression(expr)

    # 2. 构建字段DataFrame (index=日期, columns=股票代码)
    for field in _SAFE_FIELDS:
        for code, df in panel.items():
            cols[code] = df[src_col]  # Open→open, Close→close...
        field_dfs[field] = pd.DataFrame(cols)

    # 3. 构建命名空间
    namespace = {**_SAFE_NAMES, **_SAFE_FUNCTIONS, **field_dfs}

    # 4. 执行 (禁用builtins)
    result = eval(expr, {"__builtins__": {}}, namespace)
    # 返回: DataFrame (index=日期, columns=股票代码)
```

**当前限制**:
1. **不支持Talib函数**: 无法计算RSI/MACD/KDJ等技术指标
2. **不支持多返回值**: MACD返回(DIF, DEA, HIST)无法用表达式表示
3. **不支持因子间引用**: 交互因子(如adx_rsi_cross = adx_14 × rsi_14)无法引用其他因子
4. **PE/PB/ROE无数据源**: 字段在白名单中但panel中无对应数据
5. **未接入评价**: evaluate_expression只用于因子构建tab, 未接入IC/分层评价
6. **字段映射固定**: Open→open, Close→close, 无法自定义字段名

#### 11.9 基础因子计算 calc_basic_factors (12个)

```python
def calc_basic_factors(df):  # df: 单只股票日K, 返回 {factor_name: value}
    factors = {}
    # 动量类 (3个)
    factors["MOM_1M"] = close.pct_change(21)
    factors["MOM_3M"] = close.pct_change(63)
    factors["MOM_6M"] = close.pct_change(126)
    # 反转类 (1个)
    factors["REV_5D"] = -close.pct_change(5)
    # 波动率类 (2个, 取负)
    factors["VOL_20"] = -returns.rolling(20).std() * sqrt(252)
    factors["VOL_60"] = -returns.rolling(60).std() * sqrt(252)
    # 流动性类 (2个, 取负)
    factors["LIQ_20"] = -log(amount.rolling(20).mean())
    factors["TURN_20"] = -volume[-1] / volume.rolling(20).mean()
    # 技术指标类 (3个)
    factors["RSI_14"] = RSI(close, 14) - 50
    factors["BIAS_20"] = -(close / MA20 - 1)
    factors["ATR_NORM_14"] = -ATR(14) / close
    # MACD (1个, 只取DIF)
    factors["MACD_DIF"] = (EMA12 - EMA26) / close
    # 量比 (1个)
    factors["VOL_RATIO_20"] = volume[-1] / volume.rolling(20).mean()
    return factors
```

**与库中235个因子的差距**:
- calc_basic_factors只支持12个因子, 库中235个因子无法评价
- 技术指标只实现了RSI(手写)和MACD(只取DIF), 未用Talib
- 库中的ADX/CCI/KDJ/威廉/布林带等均未实现
- 交互因子/复合因子/WQ因子均不支持

#### 11.10 数据流与接口

**输入数据格式** (panel):
```python
panel = {
    "000001": DataFrame(open/high/low/close/volume/amount, index=日期),
    "000002": DataFrame(...),
    ...
}
```

**evaluate_expression输出**:
```python
# DataFrame: index=日期, columns=股票代码, values=因子值
```

**calc_basic_factors输出**:
```python
# dict: {factor_name: float}  (单只股票单时点的因子快照)
```

**run_ic_timeseries输出**:
```python
{
    "ic_series": [{"date": "2024-01-01", "ic": 0.05}, ...],
    "ic_mean": 0.04, "ic_std": 0.02, "ir": 2.0,
    "rank_ic_series": [...], "rank_ic_ir": 1.8,
    "ic_positive_ratio": 0.7, "samples": 24
}
```

#### 11.11 核心问题总结

| 问题 | 现状 | 影响 | 解决方向 |
|------|------|------|---------|
| 因子覆盖率 | calc_basic_factors仅12个 | 223个因子无法评价 | 扩展表达式引擎 |
| Talib支持 | 不支持 | 技术指标因子无法计算 | 新增ts_RSI/ts_MACD等 |
| 多返回值 | 不支持 | MACD的DEA/HIST无法表示 | 设计多输出语法 |
| 因子引用 | 不支持 | 交互因子无法计算 | 支持dependencies引用 |
| 财务数据 | PE/PB/ROE无数据源 | 估值因子无法计算 | 接入财务数据表 |
| 评价接入 | 表达式引擎未接入评价 | 表达式只用于构建 | 改造评价接口读formula |
| 离散因子 | IC不适合 | CDL形态/缠论无法评价 | 新增信号评价体系 |
| tick数据 | 不支持 | 微观结构因子无法计算 | 标记为暂不支持 |

---

## 三、因子类型-计算方式-评价方式映射表

| 因子类型 | 因子示例 | 计算方式 | 评价方式 | 预处理 | 备注 |
|---------|---------|---------|---------|--------|------|
| 价量因子 | ret_1d, vol_ratio_5d | pandas表达式 | IC/分层 | MAD+Z-score | 可表达式化 |
| 动量因子 | momentum_20d, MOM_3M | ROC/pct_change | IC/分层 | MAD+Z-score | 可表达式化 |
| 波动率因子 | hist_vol_20d, atr_norm_14 | rolling.std/ATR | IC/分层 | MAD+Z-score | 可表达式化 |
| 流动性因子 | LIQ_20, TURN_20 | log(amount)/volume比 | IC/分层 | MAD+Z-score | 可表达式化 |
| 技术指标(RSI/MACD/KDJ) | rsi_14, macd_hist | Talib函数 | IC/分层 | MAD+Z-score | 需封装ts_RSI/ts_MACD |
| 均线乖离 | ma5_bias, ma_bull_score | (close-MA)/MA | IC/分层 | MAD+Z-score | 可表达式化 |
| Talib均线 | TALIB_SMA/EMA/KAMA | Talib函数 | IC/分层 | MAD+Z-score | 需封装ts_SMA/ts_EMA |
| 交互因子 | adx_rsi_cross, mom_vol_cross | 因子乘积 | IC/分层 | MAD+Z-score | 可表达式化(引用其他因子) |
| WorldQuant复合 | WQ_PRICE_VOLUME | ts_Decay/ts_Delta | IC/分层 | ts_Decay | 已支持表达式 |
| Talib形态(68个CDL) | CDL_HAMMER, CDL_DOJI | Talib CDL函数 | 频率统计/胜率 | 无 | 离散值, 不适合IC |
| 缠论因子 | chan_buy1, chan_divergence | 结构分析 | 策略回测 | 无 | 需独立计算引擎 |
| 微观结构 | ofi_abs, cancel_rate | tick级Numpy | 分类(ML) | 无 | 需tick数据 |
| 龙头因子 | DRAGON_SCORE | 手工打分 | 筛选排名 | 硬过滤 | 需独立打分函数 |
| Barra风格 | BARRA_BETA, BARRA_SIZE | 回归暴露 | 因子收益分析 | 回归中性化 | 需回归引擎 |
| 基本面因子 | FN_PB, FN_PE, FN_ROE | 财务字段引用 | IC/分层 | MAD+Z-score+中性化 | 需财务数据接口 |

---

## 四、统一因子评价框架设计草案

### 4.1 核心思路

根据因子类型自动匹配计算引擎和评价方式:

```
用户点击"评价"
  → 读取factor的formula + factor_type + category
  → 根据类型选择计算引擎
  → 计算因子值
  → 预处理(去极值/标准化/中性化)
  → 评价(IC/分层/多空收益)
  → 返回结果
```

### 4.2 计算引擎分层

| 引擎层 | 适用因子 | 实现 |
|--------|---------|------|
| **表达式引擎** | 价量/动量/波动/流动性/均线/交互/WQ复合 | 扩展evaluate_expression(), 支持更多函数 |
| **Talib引擎** | RSI/MACD/KDJ/ADX/CCI/均线类/形态类 | 封装talib函数为ts_RSI/ts_MACD等 |
| **财务引擎** | FN_PB/PE/PS/ROE | 接入财务数据表, field引用 |
| **结构引擎** | 缠论因子 | 封装chan_analyzer, 输出连续值 |
| **打分引擎** | 龙头因子 | 封装dragon_picker打分逻辑 |
| **回归引擎** | Barra因子 | 封装回归暴露计算 |
| **不可计算** | 微观结构(需tick) | 标记为"需tick数据", 暂不支持 |

### 4.3 评价方式匹配

| 因子特征 | 评价方式 |
|---------|---------|
| 连续数值型(价量/动量/波动/技术/均线) | IC + 分层回测 + 多空收益 |
| 离散信号型(CDL形态/缠论买卖点) | 出现频率 + 信号后收益统计 + 胜率 |
| 打分型(龙头) | 高分组 vs 低分组收益对比 |
| 回归型(Barra) | 因子收益率时序 + 风险贡献 |

### 4.4 表达式函数清单(需扩展)

当前已支持: ts_Delay/ts_Mean/ts_Decay/ts_DecayExp/ts_Max/ts_Min/ts_Delta/ts_Stdev/ts_Sum/ts_Kurtosis/ts_Skewness/ts_Median + cs_Rank/cs_Zscore/cs_TransNorm

需新增:
| 函数 | 用途 | 对应Talib |
|------|------|----------|
| ts_RSI(close, n) | RSI指标 | talib.RSI |
| ts_MACD(close, fast, slow, signal) | MACD(返回DIF/DEA/HIST) | talib.MACD |
| ts_ADX(high, low, close, n) | ADX趋势强度 | talib.ADX |
| ts_KDJ(high, low, close, fastk, slowk) | KDJ随机指标 | talib.STOCH |
| ts_CCI(high, low, close, n) | CCI顺势指标 | talib.CCI |
| ts_WILLR(high, low, close, n) | 威廉指标 | talib.WILLR |
| ts_ATR(high, low, close, n) | ATR真实波幅 | talib.ATR |
| ts_BOLL(close, n, nbdev) | 布林带位置 | talib.BBANDS |
| ts_OBV(close, volume) | OBV能量潮 | talib.OBV |
| ts_SMA(close, n) | 简单移动平均 | talib.SMA |
| ts_EMA(close, n) | 指数移动平均 | talib.EMA |
| ts_ROC(close, n) | 变化率 | talib.ROC |
| ts_PctChange(close, n) | 百分比变化 | close.pct_change(n) |
| ta_CDL*(o,h,l,c) | K线形态(68个) | talib.CDL* |

### 4.5 实施路径 (基于深化调研细化)

#### 阶段一: 扩展表达式引擎 (优先)

**目标**: 让evaluate_expression支持Talib技术指标和多返回值

**新增函数** (封装Talib为ts_*算子):
```python
# 技术指标 (单返回值)
def ts_RSI(close_df, n):           # 遍历股票, talib.RSI
def ts_ADX(high_df, low_df, close_df, n):
def ts_CCI(high_df, low_df, close_df, n):
def ts_WILLR(high_df, low_df, close_df, n):
def ts_ATR(high_df, low_df, close_df, n):
def ts_ROC(close_df, n):
def ts_OBV(close_df, volume_df):

# 均线类 (单返回值)
def ts_SMA(close_df, n):
def ts_EMA(close_df, n):
def ts_WMA(close_df, n):
def ts_KAMA(close_df, n):

# 多返回值 (需设计语法)
def ts_MACD(close_df, fast, slow, signal):  # 返回(DIF, DEA, HIST)
def ts_KDJ(high_df, low_df, close_df, fastk, slowk):  # 返回(K, D)
def ts_BOLL(close_df, n, nbdev):  # 返回(upper, middle, lower, position)

# 百分比变化 (非Talib)
def ts_PctChange(close_df, n):    # close.pct_change(n)
def ts_Bias(close_df, n):         # (close - MA) / MA
```

**多返回值语法设计** (两种方案):
```
方案A: 索引访问  ts_MACD(Close, 12, 26, 9)[0]  → DIF
方案B: 后缀函数  ts_MACD_DIF(Close, 12, 26, 9) → DIF (内部调用ts_MACD)
推荐方案B: 更安全, 无需修改eval逻辑
```

**因子间引用** (交互因子支持):
```python
# 扩展evaluate_expression, 支持引用其他因子
# 1. 读取factor的dependencies字段
# 2. 先计算依赖因子的值
# 3. 将依赖因子值注入命名空间
# 示例: adx_rsi_cross = adx_14 * (rsi_14 - 50) / 50
# dependencies = ["adx_14", "rsi_14"]
# 先算 adx_14 = ts_ADX(High, Low, Close, 14)
# 再算 rsi_14 = ts_RSI(Close, 14)
# 最后算 adx_14 * (rsi_14 - 50) / 50
```

#### 阶段二: 为235个因子编写标准formula

**按类型分批编写** (参考因子类型-计算方式映射表):

| 批次 | 因子类型 | 数量 | 表达式示例 | 依赖 |
|------|---------|------|-----------|------|
| 1 | 价量因子 | ~20 | `ts_PctChange(Close, 5)` | 无 |
| 2 | 动量因子 | ~15 | `ts_ROC(Close, 20)` | 无 |
| 3 | 波动率因子 | ~10 | `ts_Stdev(ts_PctChange(Close,1), 20) * sqrt(252)` | 无 |
| 4 | 均线乖离 | ~15 | `ts_Bias(Close, 20)` | 无 |
| 5 | 技术指标(单值) | ~30 | `ts_RSI(Close, 14)` | Talib封装 |
| 6 | 技术指标(多值) | ~10 | `ts_MACD_HIST(Close, 12, 26, 9)` | 多返回值 |
| 7 | 交互因子 | ~10 | `ts_ADX(High,Low,Close,14) * (ts_RSI(Close,14)-50)/50` | 因子引用 |
| 8 | WQ复合因子 | ~5 | `-1*ts_Decay((ts_Decay(Close,10)-ts_Decay(VWAP,10))/VWAP*(High-Low),40)` | 已支持 |
| 9 | Talib形态 | ~68 | `ta_CDLHAMMER(Open, High, Low, Close)` | 离散值 |
| 10 | 基本面因子 | ~15 | `Close / FN(eps)` | 财务数据 |
| 11 | 龙头因子 | ~6 | dragon_score() | 打分引擎 |
| 12 | 缠论因子 | ~7 | chan_signal() | 结构引擎 |

#### 阶段三: 改造评价接口

**当前流程** (割裂):
```
用户点击"评价"
  → 调用 calc_basic_factors() (只支持12个)
  → preprocess_factors()
  → calc_ic() / run_layered_backtest()
```

**目标流程** (统一):
```
用户点击"评价"
  → 读取 factor 的 formula + factor_type + dependencies
  → 根据factor_type选择计算引擎:
      - 价量/动量/波动/均线/WQ → evaluate_expression()
      - 技术指标 → evaluate_expression() (含ts_RSI等)
      - 交互因子 → evaluate_expression() (含依赖因子)
      - 基本面 → evaluate_expression() (含FN字段)
      - Talib形态 → evaluate_expression() (含ta_CDL*)
      - 缠论 → chan_engine.calc()
      - 龙头 → dragon_engine.calc()
      - 微观结构 → 标记"需tick数据"
  → 计算因子值 (DataFrame: index=日期, columns=股票)
  → preprocess_factors() (MAD+Z-score+行业中性化)
  → 评价:
      - 连续值 → calc_ic() + run_layered_backtest()
      - 离散值 → 信号评价(频率/胜率/信号后收益)
  → 返回结果
```

**接口设计**:
```python
def evaluate_factor(factor_id, prices_panel, industry_map, ...):
    # 1. 读取因子信息
    factor = get_factor(factor_id)
    formula = factor["formula"]
    factor_type = factor["factor_type"]
    dependencies = factor.get("dependencies", [])

    # 2. 选择计算引擎
    if factor_type in ["basic", "composite"] and formula:
        if "ts_RSI" in formula or "ts_MACD" in formula:  # Talib引擎
            factor_values = evaluate_expression_talib(formula, panel)
        elif dependencies:  # 交互因子
            factor_values = evaluate_expression_with_deps(formula, panel, dependencies)
        else:  # 普通表达式
            factor_values = evaluate_expression(formula, panel)
    elif factor["category"] == "缠论":
        factor_values = chan_engine.calc(panel)
    elif factor["category"] == "龙头":
        factor_values = dragon_engine.calc(panel)
    else:
        return {"error": "暂不支持的因子类型"}

    # 3. 预处理
    factor_processed = preprocess_factors(factor_values, industry_map)

    # 4. 评价
    if factor_values离散:
        result = evaluate_signal(factor_processed, returns)
    else:
        result = {
            "ic": calc_ic(factor_processed, future_returns),
            "layered": run_layered_backtest(factor_processed, future_returns),
        }
    return result
```

#### 阶段四: 补充数据源 (财务/缠论)

**财务因子数据** (参考清华gl23_day2_fin):
- 接入财务数据表 (资产负债表/利润表/现金流量表)
- 实现 FN(field) 函数, 按日期对齐到日K (ffill)
- 实现 fin_Delay 取前N期财报 (避免未来函数)
- 支持 PE/PB/ROE/ROA/NPM/ATR/EM 等财务因子

**缠论因子** (参考CASE-缠论精华量化):
- 封装 chan_analyzer 为连续值输出
- chan_divergence (背驰) 可能量化为连续值
- chan_buy/sell (买卖点) 作为离散信号评价

#### 阶段五: 暂缓项

- **微观结构因子**: 需tick级数据 (参考清华gl23_day3_tick), 日K无法计算
- **Barra因子**: 需回归框架 (参考清华day2_M的F_GetResidual), 复杂度高
- **分钟因子**: 需分钟数据 (参考清华gl23_day2_min), 数据量大

### 4.6 清华CASE对主系统的借鉴价值

| 清华功能 | 主系统现状 | 借鉴方向 |
|---------|-----------|---------|
| PerformanceWithCost (含成本评价) | 只算IC, 不含成本 | 评价接口增加cost参数 |
| pn_TransNorm (正态分位数变换) | 用Z-score | 可选pn_TransNorm作为预处理选项 |
| Optuna参数优化 | 无 | 因子参数自动寻优 |
| Markowitz组合优化 | 等权/IC加权/Lasso | 新增Markowitz优化 |
| F_GetResidual (Barra中性化) | 行业中性化 | 可选Barra因子中性化 |
| LightGBM因子组合 | 无 | ML因子组合 |
| cutFactors (因子去冗余) | 无 | 因子相关性去冗余 |
| fin_Delay (财报延迟) | 无 | 财务因子避免未来函数 |
| 分钟转日频 (6种聚合) | 无 | 支持分钟因子 |
| Tick因子 (5档买卖价量) | 无 | 微观结构因子 |
| groupby_Rank (行业排名) | 行业Z-score | 行业内排名中性化 |
| IdioRet (特质收益) | 无 | 因子纯alpha评价 |

---

## 五、功能重叠与缺口分析

### 功能重叠
1. **因子计算**: ml_strategy/机器学习因子挖掘/论文复现 三处feature_engine.py内容相同
2. **预处理**: CASE-C/preprocessor.py 已合并到主系统factor_engine.py
3. **IC/分层**: CASE-C/layered_backtest.py + synthesizer.py 已合并到主系统
4. **ts_*算子**: qinghua WQ算子已合并到主系统

### 功能缺口
1. **Talib函数封装**: 表达式引擎不支持ts_RSI/ts_MACD等, 无法评价技术指标因子
2. **财务数据接口**: 表达式引擎的PE/PB/ROE字段无实际数据源
3. **离散因子评价**: CDL形态/缠论买卖点不适合IC, 需信号评价体系
4. **多返回值**: MACD返回3个值(DIF/DEA/HIST), 表达式引擎不支持
5. **因子间引用**: 交互因子(如adx_rsi_cross = adx_14 * rsi_14)需要引用其他因子值
6. **表达式校验**: 当前只做白名单检查, 不做语法/参数校验
