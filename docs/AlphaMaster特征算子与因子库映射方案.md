# AlphaMaster 特征/算子 与 本系统因子库 定义关系与映射方案（v4）

> 版本：v4（2026-08-18）
> 目的：为深度复刻 AlphaMaster 的 RL 因子挖掘引擎，先厘清两套系统的"特征/算子"定义差异，并给出 AlphaMaster 特征/算子 → 本系统因子库的完整映射关系，以及缺失项的补充方案。
> v3 修正（关键）：按用户确认的本系统设计，**参数化基类的所有实例都是复合因子，不是基础因子**；**基础因子 = 固定参数基类的实例（instance_type=basic）**。彻底修正 v2 中把 `returns(5)`/`bias(20)`/`rsi(14)` 等误标为"基础因子"的矛盾。
> v4 更新（2026-08-18）：**阶段一、阶段二已全部落地**（基类体系修正 + 算子/因子补充），详见"五、后续执行"各步骤的 ✅ 完成标记；阶段三（RL 复刻对接）待 RL 引擎实施时执行。
> 依据：AlphaMaster 本地源码 `third_party/AlphaMaster-main/model_core/`（features.py 65 特征 / ops.py 62 算子）+ 本系统 `lib/factor_engine.py`（BASE_OPERATOR_MAP / ts_* 算子 / calc_factor）+ `lib/factor_gp.py`（SPACE_LEVELS / GP_BASE_LEAF）+ `lib/factor_init.py`（factor_base 基类 / factor_library 因子 / sync_bases）+ `docs/因子基础_复合分类盘点.md`。

---

## 〇、本系统设计（用户确认，映射必须遵循）

### 0.1 因子与基类的区别（核心）

| 概念 | 定义 | 计算方式 | 存储 |
|---|---|---|---|
| **基础因子** | **固定参数基类的实例**（instance_type=basic），有独立金融语义，能直接计算 | formula 是单个固定参数基类实例，如 `macd()`、`kdj()`、`bbands()`、`TALIB_MFI()` | **同时注册因子表 + 基类表** |
| **复合因子** | **参数化基类的实例**（instance_type=composite）+ **多基类组合** | 依赖基类，通过基础因子派生的方式不断叠加计算 | 因子表（base_id 指向所引用基类） |
| **基类（factor_base）** | 指标类型模板，绑定字段 | 分两类 | 基类表 |
| ├─ **参数化基类（periodic）** | 周期是参数，**所有实例都是复合因子** | returns/momentum/amplitude/volume_ratio/volatility/price_volume_corr/bias/liquidity/sma/ema/wma/dema/tema/kama/trima/mama/sar + **rsi/adx/cci/willr/atr/reversal（见 3.5，type 从 fixed 改为 periodic）** | 基类表（instance_type=composite） |
| └─ **固定参数基类（fixed）** | 参数固定=标准参数，**实例是基础因子** | macd/kdj/bbands + TALIB_* 22 个 + 行情字段 | 基类表（instance_type=basic） |

> **关于"可调周期固定基类"的澄清与问题标注**（见 3.5）：
> - 原设计中 `rsi/adx/cci/willr/atr/reversal` 被标为 `type=fixed`（固定参数基类）但 `instance_type=composite`（实例是复合因子），且周期可调。这是**自相矛盾**的：既然实例是复合因子（周期可调），那 type 就应该是 `periodic`（参数化基类），而不是 `fixed`。
> - **调整方案**：把 `rsi/adx/cci/willr/atr/reversal` 的 `type` 从 `fixed` 改为 `periodic`（参数化基类），因为它们的周期可调、实例是复合因子，本质是参数化基类。详见 3.5。
> - 调整后，`type=fixed`（固定参数基类）只保留**固定参数型**（macd/kdj/bbands + TALIB_* + 行情字段），其实例都是基础因子（instance_type=basic），语义自洽。
> - **"可调周期固定基类"这个表述已废弃**：调整后不存在"可调周期型固定基类"，所有周期可调、实例为复合因子的基类都归入参数化基类（periodic）。
> - **行情字段也是基类**：`open/high/low/close/volume/amount/vwap/turnover_rate/value/idioret/totalret` 这些行情字段**已注册为基类**（type=fixed, instance_type=basic，见 factor_init.py BASE_FACTORS），其实例是基础因子。因此复合因子若引用这些字段（如 `(Close-Open)/(High-Low)`），其依赖基类就是这些**字段基类**，不是笼统的"字段"。
> - 判定实例类型只看 `instance_type`：`composite` → 复合因子；`basic` → 基础因子。与 `type`（periodic/fixed）无关。

### 0.2 关键判定（用户强调，必须遵循）

1. **参数化基类的所有实例都不是基础因子，一定是复合因子**。因为参数化基类需要指定周期才能计算，它本身是"鸡肋"（不完整的具体因子），实例是复合因子。
2. **基础因子如果是"鸡肋"（需要参数才能算），就不可能是参数化基类**——这是矛盾。基础因子 = 固定参数基类的实例（instance_type=basic），能直接计算。
3. **判定依据 = 基类的 `instance_type`**：
   - `instance_type=composite` 的基类实例 → **复合因子**
   - `instance_type=basic` 的基类实例 → **基础因子**

### 0.3 与 AlphaMaster 的对应

- AlphaMaster 的**特征**（叶子）→ 本系统的**基础因子**（若 instance_type=basic）或**复合因子**（若 instance_type=composite）。
- AlphaMaster 的**算子**（函数节点）→ 本系统的**算子表**（ts_* / cs_* / 算术）。

---

## 一、AlphaMaster 特征 → 本系统映射表（65 个，按 instance_type 归类）

> 判定标准：本系统对应基类的 `instance_type`。`composite` → 复合因子；`basic` → 基础因子。

### 1.1 趋势类（8 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| RET | log(close[t]/close[t-1]) | `returns(1)` | **复合因子** | returns（参数化基类，已有） | ✅ 已有 |
| RET5 | log(close[t]/close[t-5]) | `returns(5)` | **复合因子** | returns（已有） | ✅ 已有 |
| RET20 | log(close[t]/close[t-20]) | `returns(20)` | **复合因子** | returns（已有） | ✅ 已有 |
| MA_DIFF | MA10/MA30 - 1 | `bias(10)/bias(30)-1` | **复合因子** | bias（参数化基类，已有） | ✅ 已有（可组合） |
| SLOPE20 | 20期线性回归斜率 | `momentum_slope_20d` | **复合因子** | momentum_slope（参数化基类，已有） | ✅ 已有 |
| EMA_RATIO_12_26 | EMA12/EMA26 - 1 | `ema(12)/ema(26)-1` | **复合因子** | ema（参数化基类，已有） | ⚠️ 需新增复合因子 |
| TREND_STRENGTH_50 | SLOPE50 × R² | `trend_strength(50)` | **复合因子** | trend_strength（**需新增参数化基类**） | ❌ 需新增 |
| PRICE_POS_50 | (close-min50)/(max50-min50) | `price_position(50)` | **复合因子** | price_position（**退化为参数化基类**） | ⚠️ 需退化基类 + 补实例 |

### 1.2 波动类（9 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| ATR | 真实波幅均值(14) | `atr(14)` | **复合因子** | atr（参数化基类，已有，见 3.5） | ✅ 已有 |
| RVOL | 20期对数收益滚动std | `volatility(20)` | **复合因子** | volatility（参数化基类，已有） | ✅ 已有 |
| HL_RANGE | (H-L)/C | `amplitude(1)` | **复合因子** | amplitude（参数化基类，已有） | ✅ 已有 |
| VOL_REGIME | ATR/MA20(ATR) - 1 | `atr(14)/ts_Mean(atr(14),20)-1` | **复合因子** | atr（已有） | ⚠️ 需新增复合因子 |
| BOLL_WIDTH | (upper-lower)/MA | `bbands_width()` | **基础因子** | bbands_width（**需新增固定参数基类**） | ❌ 需新增 |
| GK_VOL | Garman-Klass 波动 | `gk_vol(20)` | **复合因子** | gk_vol（**需新增参数化基类**） | ❌ 需新增 |
| PARKINSON_VOL | Parkinson 波动 | `parkinson_vol(20)` | **复合因子** | parkinson_vol（**需新增参数化基类**） | ❌ 需新增 |
| YANG_ZHANG_VOL | Yang-Zhang 波动 | `yang_zhang_vol(20)` | **复合因子** | yang_zhang_vol（**需新增参数化基类**） | ❌ 需新增 |
| RS_VOL | Rogers-Satchell 波动 | `rs_vol(20)` | **复合因子** | rs_vol（**需新增参数化基类**） | ❌ 需新增 |

### 1.3 反转类（14 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| DEV | (close-MA20)/MA20 | `bias(20)` | **复合因子** | bias（参数化基类，已有） | ✅ 已有 |
| DEV60 | (close-MA60)/MA60 | `bias(60)` | **复合因子** | bias（已有） | ✅ 已有 |
| RSI14 | RSI 归一化[-1,1] | `rsi(14)` | **复合因子** | rsi（参数化基类，已有，见 3.5） | ✅ 已有 |
| PRESSURE | (close-open)/(high-low) | `(Close-Open)/(High-Low)` | **复合因子** | open/high/low/close 基类（固定参数基类，已有） | ⚠️ 需新增复合因子 |
| AC1 | 20期收益自相关 | `autocorr(20,1)` | **复合因子** | autocorr（**需新增参数化基类**） | ❌ 需新增 |
| WILLR_14 | 威廉指标 | `willr(14)` | **复合因子** | willr（参数化基类，已有，见 3.5） | ✅ 已有 |
| CCI_14 | 商品通道指标 | `cci(14)` | **复合因子** | cci（参数化基类，已有，见 3.5） | ✅ 已有 |
| TYPICAL_DEV | (typical-MA20)/MA20 | `typical_dev(20)` | **复合因子** | typical_dev（**需新增参数化基类**） | ❌ 需新增 |
| STOCH_K_14 | 随机指标%K | `kdj()` | **基础因子** | kdj（固定参数基类，已有） | ✅ 已有 |
| STOCH_D_3 | %K 的 3 期均值 | `kdj()` | **基础因子** | kdj（已有） | ✅ 已有 |
| AROON_OSC_25 | Aroon 振荡器 | `TALIB_AROONOSC()` | **基础因子** | TALIB_AROONOSC（固定参数基类，已有） | ✅ 已有 |
| DMI_ADX_14 | ADX 趋势强度 | `adx(14)` | **复合因子** | adx（参数化基类，已有，见 3.5） | ✅ 已有 |
| DMI_DIFF_14 | DI+ - DI- | `dmi_diff(14)` | **复合因子** | dmi_diff（**需新增参数化基类**） | ❌ 需新增 |
| TRIX_SIGNAL | TRIX - MA9(TRIX) | `trix(15)-ts_Mean(trix(15),9)` | **复合因子** | trix（**需新增参数化基类**） | ❌ 需新增 |

### 1.4 量能类（12 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| VOL_RATIO | volume/MA20(volume) | `volume_ratio(20)` | **复合因子** | volume_ratio（参数化基类，已有） | ✅ 已有 |
| VOL_Z | (volume-MA20)/std20 | `(volume_ratio(20)-1)/ts_Stdev(volume_ratio(20),20)` | **复合因子** | volume_ratio（已有） | ⚠️ 需新增复合因子 |
| PV_CORR | 10期价量相关 | `price_volume_corr(10)` | **复合因子** | price_volume_corr（参数化基类，已有） | ✅ 已有 |
| VWAP_DEV | (close-VWAP)/VWAP | `(Close-VWAP)/VWAP` | **复合因子** | close/vwap 基类（固定参数基类，已有） | ⚠️ 需新增复合因子 |
| BOLL_POS | 布林位置[0,1] | `bbands()` | **基础因子** | bbands（固定参数基类，已有） | ✅ 已有 |
| MACD_HIST | MACD 柱 | `macd()` | **基础因子** | macd（固定参数基类，已有） | ✅ 已有 |
| OBV_SLOPE | OBV 20期斜率 | `obv_slope_10d` | **基础因子** | obv_slope（固定参数基类，已有） | ✅ 已有 |
| MFI14 | 资金流量指标 | `TALIB_MFI()` | **基础因子** | TALIB_MFI（固定参数基类，已有） | ✅ 已有 |
| AMIHUD_ILLIQ | Amihud 非流动性 | `amihud_illiq(20)` | **复合因子** | amihud_illiq（**需新增参数化基类**） | ❌ 需新增 |
| KYLE_LAMBDA | Kyle lambda | `kyle_lambda(20)` | **复合因子** | kyle_lambda（**需新增参数化基类**） | ❌ 需新增 |
| CMF_20 | Chaikin Money Flow | `cmf(20)` | **复合因子** | cmf（**需新增参数化基类**） | ❌ 需新增 |
| AD_LINE_SLOPE | A/D line 斜率 | `ad_line_slope(20)` | **复合因子** | ad_line_slope（**需新增参数化基类**） | ❌ 需新增 |

### 1.5 动量类（5 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| ROC_12 | 12期变化率 | `momentum(12)` | **复合因子** | momentum（参数化基类，已有） | ✅ 已有 |
| TRIX_15 | 三重EMA变化率 | `trix(15)` | **复合因子** | trix（**需新增参数化基类**） | ❌ 需新增 |
| PPO | (EMA12-EMA26)/EMA26 | `TALIB_PPO()` | **基础因子** | TALIB_PPO（固定参数基类，已有） | ✅ 已有 |
| ULT_OSC | Ultimate Oscillator | `TALIB_UO()` | **基础因子** | TALIB_UO（固定参数基类，已有） | ✅ 已有 |
| RET_ACCEL | RET5 - RET5[t-5] | `momentum_accel_10d` | **复合因子** | momentum_accel（参数化基类，已有） | ✅ 已有 |

### 1.6 通道类（6 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| DONCHIAN_POS_20 | (close-min20)/(max20-min20) | `price_position(20)` | **复合因子** | price_position（**退化为参数化基类**） | ⚠️ 需退化基类 + 补实例 |
| KELTNER_POS_20 | Keltner 通道位置 | `keltner(20)` | **复合因子** | keltner（**需新增参数化基类**） | ❌ 需新增 |
| ICHIMOKU_KIJUN_DEV | close 相对 Kijun 偏离 | `ichimoku_kijun(26)` | **复合因子** | ichimoku（**需新增参数化基类**） | ❌ 需新增 |
| ICHIMOKU_TENKAN_DEV | close 相对 Tenkan 偏离 | `ichimoku_tenkan(9)` | **复合因子** | ichimoku（**需新增参数化基类**） | ❌ 需新增 |
| SUPERTREND_DIR | SuperTrend 方向 | `supertrend(14)` | **复合因子** | supertrend（**需新增参数化基类**） | ❌ 需新增 |
| SAR_DIST | close 相对 SAR 距离 | `sar_dist()` | **基础因子** | sar_dist（**需新增固定参数基类**） | ❌ 需新增 |

### 1.7 统计类（6 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| ROLL_SKEW_20 | 20期收益偏度 | `ts_Skewness(returns(1),20)` | **复合因子** | returns + ts_Skewness（已有） | ✅ 已有（可组合） |
| ROLL_KURT_20 | 20期收益峰度 | `ts_Kurtosis(returns(1),20)` | **复合因子** | returns + ts_Kurtosis（已有） | ✅ 已有（可组合） |
| HURST_50 | Hurst 指数 | `hurst(50)` | **复合因子** | hurst（**需新增参数化基类**） | ❌ 需新增 |
| FRACTAL_DIM_30 | 分形维 | `fractal_dim(30)` | **复合因子** | fractal_dim（**需新增参数化基类**） | ❌ 需新增 |
| AC2 | 二阶自相关 | `autocorr(20,2)` | **复合因子** | autocorr（**需新增参数化基类**） | ❌ 需新增 |
| RET_ENTROPY_20 | 收益符号熵 | `ret_entropy(20)` | **复合因子** | ret_entropy（**需新增参数化基类**） | ❌ 需新增 |

### 1.8 截面类（5 个）

| AlphaMaster 特征 | 计算方式 | 本系统映射 | 类型 | 依赖基类 | 状态 |
|---|---|---|---|---|---|
| REL_RET5 | RET5 - 截面均值 | `cs_Demean(returns(5))` | **复合因子** | returns + cs_Demean（已有） | ✅ 已有（可组合） |
| REL_RET20 | RET20 - 截面均值 | `cs_Demean(returns(20))` | **复合因子** | returns + cs_Demean（已有） | ✅ 已有（可组合） |
| REL_VOL | RVOL - 截面均值 | `cs_Demean(volatility(20))` | **复合因子** | volatility + cs_Demean（已有） | ✅ 已有（可组合） |
| CS_RANK_RET5 | RET5 截面排名 | `cs_Rank(returns(5))` | **复合因子** | returns + cs_Rank（已有） | ✅ 已有（可组合） |
| CS_ZSCORE_RET20 | RET20 截面 zscore | `cs_Zscore(returns(20))` | **复合因子** | returns + cs_Zscore（已有） | ✅ 已有（可组合） |

---

## 二、AlphaMaster 算子 → 本系统映射表（62 个）

> 算子映射到本系统**算子表**（ts_* / cs_* / 算术），不涉及基类。

### 2.1 算术类（22 个）

| AlphaMaster 算子 | 本系统映射 | 类型 | 说明 |
|---|---|---|---|
| ADD | `add` | ✅ 已有 | 本系统 GP_ARITH_BINARY |
| SUB | `sub` | ✅ 已有 | 同上 |
| MUL | `mul` | ✅ 已有 | 同上 |
| DIV | `div` | ✅ 已有 | 同上 |
| NEG | `neg` | ✅ 已有 | 本系统 GP_ARITH_UNARY |
| ABS | `abs` | ✅ 已有 | 同上 |
| SIGN | `sign` | ❌ 需新增 | 本系统无 sign 算子 |
| GATE | `gate` | ❌ 需新增 | 条件门（3元） |
| JUMP | `jump` | ❌ 需新增 | 因果 expanding zscore + tanh |
| DECAY | `ts_Decay` | ✅ 已有 | 本系统 ts_Decay |
| DELAY1 | `ts_Delay` | ✅ 已有 | 本系统 ts_Delay |
| MAX3 | `max3` | ❌ 需新增 | 3期最大值 |
| MIN | `ts_Min` | ✅ 已有 | 本系统 ts_Min |
| MAX | `ts_Max` | ✅ 已有 | 本系统 ts_Max |
| POWER | `power` | ❌ 需新增 | 带符号乘方 |
| SIGNED_LOG | `signed_log` | ❌ 需新增 | 带符号对数 |
| SQRT | `sqrt` | ❌ 需新增 | 带符号开方 |
| CLIP | `clip` | ❌ 需新增 | 固定裁剪 |
| SIGMOID | `sigmoid` | ❌ 需新增 | sigmoid 压缩 |
| TANH_SQUASH | `tanh_squash` | ❌ 需新增 | tanh 压缩 |
| IF_GT | `if_gt` | ❌ 需新增 | 条件选择（3元） |
| WINSORIZE | `winsorize` | ❌ 需新增 | 去极值（算子形态） |

### 2.2 时序类（33 个）

| AlphaMaster 算子 | 本系统映射 | 类型 | 说明 |
|---|---|---|---|
| TS_MEAN_5/10/20 | `ts_Mean` | ✅ 已有 | 本系统 ts_Mean |
| TS_STD_5/10/20 | `ts_Stdev` | ✅ 已有 | 本系统 ts_Stdev |
| TS_RANK_5/10/20 | `ts_Rank` | ✅ 已有 | 本系统 ts_Rank |
| TS_CORR_10 | `ts_Corr` | ✅ 已有 | 本系统 ts_Corr |
| MOMENTUM_5/10 | `ts_Mean(5)-ts_Mean(20)` | ✅ 已有 | 本系统可组合 |
| TS_MAX_10/20 | `ts_Max` | ✅ 已有 | 本系统 ts_Max |
| TS_MIN_10/20 | `ts_Min` | ✅ 已有 | 本系统 ts_Min |
| WMA | `ts_WMA` | ✅ 已有 | 本系统 ts_WMA |
| DELAY4 | `ts_Delay` | ✅ 已有 | 本系统 ts_Delay |
| EMA_5/20 | `ts_EMA` | ✅ 已有 | 本系统 ts_EMA |
| TS_QUANTILE_10 | `ts_Quantile` | ✅ 已有 | 本系统 ts_Quantile |
| TS_SKEW_10 | `ts_Skewness` | ✅ 已有 | 本系统 ts_Skewness |
| DELTA | `ts_Delta` | ✅ 已有 | 本系统 ts_Delta |
| DELTA_5 | `ts_Delta` | ✅ 已有 | 本系统 ts_Delta |
| TS_ARG_MAX_5 | `ts_ArgMax` | ❌ 需新增 | 本系统无 argmax |
| TS_ARG_MIN_5 | `ts_ArgMin` | ❌ 需新增 | 本系统无 argmin |
| DECAY_LINEAR_5 | `ts_DecayLinear` | ❌ 需新增 | 本系统 ts_Decay 是 exp 衰减 |
| SCALE | `ts_Scale` | ❌ 需新增 | 因果 L1 归一化 |
| COVARIANCE_10 | `ts_Cov` | ✅ 已有 | 本系统 ts_Cov |
| PRODUCT_5 | `ts_Product` | ❌ 需新增 | 滑动乘积 |
| SIGNED_POWER_2 | `signed_power` | ❌ 需新增 | 带符号乘方 |
| TS_DECAY_EXP_5 | `ts_DecayExp` | ✅ 已有 | 本系统 ts_DecayExp |
| TS_SUM_5/10/20 | `ts_Sum` | ✅ 已有 | 本系统 ts_Sum |
| TS_ZSCORE_10/20 | `ts_rank_normalize` / `cs_Zscore` | ✅ 已有 | 本系统有 |

### 2.3 截面类（3 个）

| AlphaMaster 算子 | 本系统映射 | 类型 | 说明 |
|---|---|---|---|
| CS_RANK | `cs_Rank` | ✅ 已有 | 本系统 cs_Rank |
| CS_SCALE | `cs_TransNorm` | ⚠️ 语义相近 | 本系统 cs_TransNorm 是正态分位，AlphaMaster 是 min-max 缩放 |
| CS_NEUTRALIZE | `cs_Demean` | ✅ 已有 | 本系统 cs_Demean |

---

## 三、缺失项汇总与补充方案（按本系统设计）

### 3.1 需新增的算子（本系统算子表缺失，约 17 个）

> 补充到 `factor_engine.py` 算子表（含 GPU torch 算子对齐）。

| 算子 | 语义 | 补充位置 |
|---|---|---|
| `sign` | 符号函数 | factor_engine.py 算子表 |
| `gate` | 条件门（3元） | factor_engine.py 算子表 |
| `jump` | 因果 expanding zscore + tanh | factor_engine.py 算子表 |
| `max3` | 3期最大值 | factor_engine.py 算子表 |
| `power` | 带符号乘方 | factor_engine.py 算子表 |
| `signed_log` | 带符号对数 | factor_engine.py 算子表 |
| `sqrt` | 带符号开方 | factor_engine.py 算子表 |
| `clip` | 固定裁剪 | factor_engine.py 算子表 |
| `sigmoid` | sigmoid 压缩 | factor_engine.py 算子表 |
| `tanh_squash` | tanh 压缩 | factor_engine.py 算子表 |
| `if_gt` | 条件选择（3元） | factor_engine.py 算子表 |
| `winsorize` | 去极值（算子形态） | factor_engine.py 算子表 |
| `ts_ArgMax` | 窗口内最大值位置 | factor_engine.py 算子表 |
| `ts_ArgMin` | 窗口内最小值位置 | factor_engine.py 算子表 |
| `ts_Scale` | 因果 L1 归一化 | factor_engine.py 算子表 |
| `ts_Product` | 滑动乘积 | factor_engine.py 算子表 |
| `ts_DecayLinear` | 线性衰减加权 | factor_engine.py 算子表 |

### 3.2 需新增的基础因子（instance_type=basic，需同时注册因子表 + 基类表）

> 按用户要求：补充基础因子时，**同时注册因子表（factor_library）+ 基类表（factor_base）**。基础因子 = 固定参数基类的实例。

| 特征 | 语义 | 新增基类 | 基类类型 | 需注册 |
|---|---|---|---|---|
| BOLL_WIDTH | 布林宽度 | `bbands_width` | 固定参数基类 | 因子表 + 基类表 |
| SAR_DIST | close 相对 SAR 距离 | `sar_dist` | 固定参数基类 | 因子表 + 基类表 |

> 注：其余需新增的 AlphaMaster 特征（TREND_STRENGTH/GK_VOL/PARKINSON_VOL/YANG_ZHANG_VOL/RS_VOL/AC1/AC2/TYPICAL_DEV/DMI_DIFF/TRIX/AMIHUD/KYLE/CMF/AD_LINE/HURST/FRACTAL_DIM/RET_ENTROPY/KELTNER/ICHIMOKU/SUPERTREND）均为**参数化基类**，其实例是**复合因子**，见 3.3。

### 3.3 需新增的复合因子（instance_type=composite，依赖基类）

> 按用户要求：复合因子必须依赖已存在的基类（参数化基类/固定参数基类/技术因子），或本轮补充的基类。**参数化基类的实例都是复合因子**。

#### 3.3.1 依赖已有基类（可直接新增复合因子）

| 特征 | 复合因子 formula | 依赖基类 | 状态 |
|---|---|---|---|
| EMA_RATIO_12_26 | `ema(12)/ema(26)-1` | ema（参数化基类，已有） | ⚠️ 需新增复合因子 |
| VOL_REGIME | `atr(14)/ts_Mean(atr(14),20)-1` | atr（已有） | ⚠️ 需新增复合因子 |
| PRESSURE | `(Close-Open)/(High-Low)` | open/high/low/close 基类（已有） | ⚠️ 需新增复合因子 |
| VOL_Z | `(volume_ratio(20)-1)/ts_Stdev(volume_ratio(20),20)` | volume_ratio（已有） | ⚠️ 需新增复合因子 |
| VWAP_DEV | `(Close-VWAP)/VWAP` | close/vwap 基类（已有） | ⚠️ 需新增复合因子 |

#### 3.3.2 依赖需补充的参数化基类（先补基类，再补复合因子实例）

| 特征 | 复合因子 formula | 需新增参数化基类 | 状态 |
|---|---|---|---|
| TREND_STRENGTH_50 | `trend_strength(50)` | `trend_strength` | ❌ 需先补基类 |
| GK_VOL | `gk_vol(20)` | `gk_vol` | ❌ 需先补基类 |
| PARKINSON_VOL | `parkinson_vol(20)` | `parkinson_vol` | ❌ 需先补基类 |
| YANG_ZHANG_VOL | `yang_zhang_vol(20)` | `yang_zhang_vol` | ❌ 需先补基类 |
| RS_VOL | `rs_vol(20)` | `rs_vol` | ❌ 需先补基类 |
| AC1 | `autocorr(20,1)` | `autocorr` | ❌ 需先补基类 |
| AC2 | `autocorr(20,2)` | `autocorr` | ❌ 需先补基类 |
| TYPICAL_DEV | `typical_dev(20)` | `typical_dev` | ❌ 需先补基类 |
| DMI_DIFF_14 | `dmi_diff(14)` | `dmi_diff` | ❌ 需先补基类 |
| TRIX_15 | `trix(15)` | `trix` | ❌ 需先补基类 |
| TRIX_SIGNAL | `trix(15)-ts_Mean(trix(15),9)` | `trix` | ❌ 需先补基类 |
| AMIHUD_ILLIQ | `amihud_illiq(20)` | `amihud_illiq` | ❌ 需先补基类 |
| KYLE_LAMBDA | `kyle_lambda(20)` | `kyle_lambda` | ❌ 需先补基类 |
| CMF_20 | `cmf(20)` | `cmf` | ❌ 需先补基类 |
| AD_LINE_SLOPE | `ad_line_slope(20)` | `ad_line_slope` | ❌ 需先补基类 |
| HURST_50 | `hurst(50)` | `hurst` | ❌ 需先补基类 |
| FRACTAL_DIM_30 | `fractal_dim(30)` | `fractal_dim` | ❌ 需先补基类 |
| RET_ENTROPY_20 | `ret_entropy(20)` | `ret_entropy` | ❌ 需先补基类 |
| KELTNER_POS_20 | `keltner(20)` | `keltner` | ❌ 需先补基类 |
| ICHIMOKU_KIJUN_DEV | `ichimoku_kijun(26)` | `ichimoku` | ❌ 需先补基类 |
| ICHIMOKU_TENKAN_DEV | `ichimoku_tenkan(9)` | `ichimoku` | ❌ 需先补基类 |
| SUPERTREND_DIR | `supertrend(14)` | `supertrend` | ❌ 需先补基类 |
| PRICE_POS_50 | `price_position(50)` | `price_position`（**退化为参数化基类**） | ⚠️ 需退化基类 + 补实例 |
| DONCHIAN_POS_20 | `price_position(20)` | `price_position`（**退化为参数化基类**） | ⚠️ 需退化基类 + 补实例 |

### 3.4 固定参数基类的周期变体矛盾（price_position 案例，采用方案 B）

> **问题**：`price_position` 是**固定参数基类**（formula 硬编码 60 日，如 `(Close - ts_Min(Close,60)) / (ts_Max(Close,60) - ts_Min(Close,60))`），其实例是**基础因子**。但 AlphaMaster 的 `PRICE_POS_50`（50 日）和 `DONCHIAN_POS_20`（20 日）需要**不同周期**的区间位置。
>
> **矛盾**：固定参数基类不允许换参数。若把 `price_position(50)` 标成"基础因子"，它依赖的基类 `price_position` 是固定参数基类（60日），但 50 日 ≠ 60 日，参数变了语义就变了——**它就不是同一个基类的实例了**。因此 `price_position(50)` 与 `price_position`（60日）是**两个完全独立的基础因子**，之间没有关系。
>
> **解决方案（用户确认采用方案 B）**：把 `price_position` 从**固定参数基类退化为参数化基类**（periodic），则 `price_position(20/50/60)` 都是同一个参数化基类的不同实例（**复合因子**）。原本的 `price_position`（60日）基础因子变为复合因子 `price_position(60)`。
>
> **依赖检查（关键）**：退化前必须确认 `price_position` 是否被其他因子依赖。经核查：
> - `factor_init.py` 中 `price_position` 仅出现在：定义（L237）、分类规则（L1123）、基类分组（L1369），**没有任何复合因子的 formula 引用它**，也没有任何因子的 base_id 指向它。
> - `factor_engine.py` 中 `price_position` 仅出现在 `_TS_NORMALIZED_OPS` 列表（L3862，评价路由启发式），**不是因子依赖**。
> - `factor_gp.py` 中无 `price_position` 引用。
> - **结论：`price_position` 未被任何其他因子依赖**，退化为参数化基类是安全的，无需同步调整其他因子。
>
> **退化步骤**：
> 1. 在 `factor_base` 中把 `price_position` 的 `type` 从 `fixed` 改为 `periodic`，`instance_type` 从 `basic` 改为 `composite`。
> 2. 在 `factor_library` 中把 `price_position`（60日）的 `factor_type` 从 `basic` 改为 `composite`，formula 改为 `price_position(60)`（参数化基类实例）。
> 3. 新增 `price_position(20)`、`price_position(50)` 复合因子实例（依赖退化的参数化基类）。
> 4. 若未来发现其他因子依赖 `price_position`，需同步调整其 formula 为 `price_position(60)` 形式。

### 3.5 可调周期型基类的 type 矛盾（rsi/adx/cci/willr/atr/reversal）

> **问题**：原设计中 `rsi/adx/cci/willr/atr/reversal` 这 6 个基类被标为 `type=fixed`（固定参数基类）但 `instance_type=composite`（实例是复合因子），且周期可调（如 `atr(14)`、`atr(20)`）。这是**自相矛盾**的：
> - "固定参数基类"（type=fixed）的语义是"参数固定=标准参数，实例是基础因子"（如 macd/kdj/bbands）。
> - 但这 6 个基类的周期**可调**，实例是**复合因子**（instance_type=composite），与"固定参数"语义冲突。
> - 既然实例是复合因子（周期可调），那 type 就应该是 `periodic`（参数化基类），而不是 `fixed`。
>
> **调整方案**：把 `rsi/adx/cci/willr/atr/reversal` 的 `type` 从 `fixed` 改为 `periodic`（参数化基类），因为它们的周期可调、实例是复合因子，本质是参数化基类。
>
> **调整后**：
> - `type=periodic`（参数化基类）：returns/momentum/amplitude/volume_ratio/volatility/price_volume_corr/bias/liquidity/sma/ema/wma/dema/tema/kama/trima/mama/sar + **rsi/adx/cci/willr/atr/reversal**，实例都是复合因子（instance_type=composite）。
> - `type=fixed`（固定参数基类）：只保留**固定参数型**（macd/kdj/bbands + TALIB_* + 行情字段），实例都是基础因子（instance_type=basic），语义自洽。
>
> **依赖检查**：调整前需确认这 6 个基类是否被其他因子依赖（作为 base_id 或 formula 引用）。经核查：
> - `rsi/adx/cci/willr/atr/reversal` 被大量复合因子引用（如 `adx_rsi_cross` 依赖 adx/rsi，`mom_vol_cross` 依赖 atr，`rsi_bbands_cross` 依赖 rsi/bbands 等）。
> - 但这些复合因子的 formula 已经是"基类实例"形式（如 `adx(14) * (rsi(14)-50)/50`），**type 从 fixed 改为 periodic 不影响 formula 的求值**（因为 formula 是自包含的基类实例，不依赖 type 字段）。
> - `type` 字段只影响"基类分类展示"和"构造生成"（构建页选基类时区分参数化/固定参数），不影响已存在因子的计算。
> - **结论：type 调整不影响现有因子计算**，只需同步更新 factor_base 的 type 字段和前端基类分类展示。
>
> **调整步骤**：
> 1. 在 `factor_base` 中把 `rsi/adx/cci/willr/atr/reversal` 的 `type` 从 `fixed` 改为 `periodic`（`instance_type` 保持 `composite` 不变）。
> 2. 同步更新前端基类分类展示（构建页"参数化基类"面板应包含这 6 个）。
> 3. 现有复合因子 formula 无需改动（自包含基类实例，不依赖 type 字段）。

---

## 四、结论

1. **定义关系（关键修正）**：
   - **参数化基类的所有实例都是复合因子**（instance_type=composite），不是基础因子。
   - **基础因子 = 固定参数基类的实例**（instance_type=basic），能直接计算。
   - 判定依据 = 基类的 `instance_type`。

2. **基础因子 vs 复合因子**：
   - **基础因子**（instance_type=basic）：MACD_HIST/BOLL_POS/STOCH_K/STOCH_D/AROON_OSC/MFI/PPO/ULT_OSC/OBV_SLOPE + 行情字段 → 大部分已有。
   - **复合因子**（instance_type=composite）：RET/RET5/RET20/MA_DIFF/SLOPE20/ATR/RVOL/HL_RANGE/RSI14/WILLR/CCI/ADX/VOL_RATIO/PV_CORR/ROC/RET_ACCEL/DEV/DEV60 + 截面类 → 大部分已有（参数化基类实例，含 rsi/adx/cci/willr/atr/reversal 见 3.5）。

3. **算子映射**：62 个算子中约 **40 个已存在**，约 **17 个需新增**到算子表。✅ 已全部落地（见 3.1）。

4. **基础因子补充**：约 **2 个需新增基础因子**（BOLL_WIDTH/SAR_DIST，固定参数基类），**同时注册因子表 + 基类表**。✅ 已全部落地（见 3.2）。

5. **复合因子补充**：约 **5 个依赖已有基类**（EMA_RATIO/VOL_REGIME/PRESSURE/VOL_Z/VWAP_DEV）+ **22 个依赖需补充的参数化基类**（TREND_STRENGTH/GK_VOL/PARKINSON_VOL/YANG_ZHANG_VOL/RS_VOL/AC1/AC2/TYPICAL_DEV/DMI_DIFF/TRIX/AMIHUD/KYLE/CMF/AD_LINE/HURST/FRACTAL_DIM/RET_ENTROPY/KELTNER/ICHIMOKU/SUPERTREND）+ **2 个依赖退化的 price_position 参数化基类**（PRICE_POS_50/DONCHIAN_POS_20）。✅ 已全部落地（见 3.3）。

6. **固定参数基类周期变体矛盾**：`price_position` 是固定参数基类（60日），无法承载 20/50 日变体。采用**方案 B**——把 `price_position` 退化为参数化基类，其 20/50/60 日实例均为复合因子。**依赖检查确认 `price_position` 未被任何其他因子依赖**，退化安全，无需同步调整其他因子。✅ 已落地。

7. **可调周期型基类 type 矛盾**：`rsi/adx/cci/willr/atr/reversal` 被标为 `type=fixed` 但 `instance_type=composite`（实例是复合因子）且周期可调，**自相矛盾**。调整方案：把它们的 `type` 从 `fixed` 改为 `periodic`（参数化基类）。**依赖检查确认 type 调整不影响现有因子计算**（formula 是自包含基类实例，不依赖 type 字段），只需同步更新 factor_base 的 type 字段和前端基类分类展示。✅ 已落地。

8. **补充原则**：
   - 算子缺失 → 在 `factor_engine.py` 算子表补充（含 GPU torch 算子对齐）。
   - 基础因子缺失 → 在 `factor_init.py` 补充，**同时注册因子表 + 基类表**（固定参数基类实例）。
   - 复合因子缺失 → 在 `factor_init.py` 补充，**依赖已存在的基类或本轮补充的基类**（参数化基类实例）；若依赖字段系统里没有，先补基类。
   - **固定参数基类无法承载不同周期** → 退化为参数化基类（方案 B），退化前必须检查是否被其他因子依赖，若被依赖需同步调整。
   - **可调周期型基类 type 矛盾** → 把 `rsi/adx/cci/willr/atr/reversal` 的 type 从 fixed 改为 periodic（见 3.5）。

---

## 五、后续执行（对应 RL 复刻）

> **执行顺序说明**：优先完成本系统基类体系的修正（第 1~2 步），再补充算子/因子（第 3~6 步）。因为基类 type 调整是本系统基类体系本身的修正，是后续补充算子/因子的基础，必须先做。
>
> **执行状态**：阶段一、阶段二已全部落地（2026-08-18 完成），阶段三（RL 复刻对接）待 RL 引擎实施时执行。

### 阶段一：优先修正本系统基类体系（必须先做）✅ 已完成

1. **按 3.5 调整可调周期型基类 type**：把 `rsi/adx/cci/willr/atr/reversal` 的 `type` 从 `fixed` 改为 `periodic`（参数化基类），同步更新前端基类分类展示（构建页"参数化基类"面板应包含这 6 个）。**依赖检查确认不影响现有因子计算**（formula 是自包含基类实例，不依赖 type 字段）。
   - ✅ 已落地：`factor_base` 中 6 个基类 type 已改为 `periodic`（instance_type 保持 `composite`），构建页"参数化基类"面板已包含这 6 个。
2. **按 3.4 方案 B 退化 `price_position` 为参数化基类**：改 factor_base type/instance_type，改 factor_library 的 price_position(60) 为复合因子，新增 price_position(20)/price_position(50) 实例。**依赖检查确认 `price_position` 未被任何其他因子依赖**，退化安全。
   - ✅ 已落地：`factor_base` 中 `price_position` type 已改为 `periodic`、instance_type 改为 `composite`；`factor_library` 中 `price_position`(60) 已改为复合因子，新增 `price_position_20`/`price_position_50` 实例。

### 阶段二：补充算子/因子（基类体系修正后）✅ 已完成

3. 在 `factor_engine.py` 算子表补充 3.1 的 17 个算子（含 GPU torch 算子对齐）。
   - ✅ 已落地：`factor_engine.py` 已实现并注册 17 个算子（sign/gate/jump/max3/power/signed_log/sqrt/clip/sigmoid/tanh_squash/if_gt/winsorize/ts_ArgMax/ts_ArgMin/ts_Scale/ts_Product/ts_DecayLinear），已加入 `_SAFE_FUNCTIONS` 白名单与 GP 搜索空间；构建页 `OPERATORS` 面板已补充（5 时序 + 12 算术）。
   - ✅ GPU 覆盖状态已更新（2026-08-19）：后续"阶段6.3"已按 GP 搜索空间把这些新算子 GPU 化（TORCH_ARITH/TORCH_TS/TORCH_TS_RAW 均含），**GP/LLM-GP 搜索空间内 GPU 覆盖 100%**（含 9 个进入 GP_BASE_LEAF 的 AlphaMaster 新基类）。RL 收尾侧仍存在 22 处 GPU 缺口（重计算型基类/三目/ts_Quantile/ts_Cov/np.abs 写法等），详见 `docs/RL因子挖掘_GPU算子覆盖审计与搜索空间对齐.md`。
4. 在 `factor_init.py` / `factor_base` 补充 3.2 的 2 个基础因子（**同时注册因子表 + 基类表**）。
   - ✅ 已落地：`BOLL_WIDTH`/`SAR_DIST` 已同时注册 `factor_library`（factor_type=basic）+ `factor_base`（type=fixed, instance_type=basic）。
5. 在 `factor_init.py` 补充 3.3.1 的 5 个复合因子（依赖已有基类）。
   - ✅ 已落地：`EMA_RATIO_12_26`/`VOL_REGIME`/`PRESSURE`/`VOL_Z`/`VWAP_DEV` 已注册 `factor_library`（factor_type=composite），并显式回填 `evaluation_type=technical`。
6. 在 `factor_init.py` 补充 3.3.2 的 22 个参数化基类 + 其复合因子实例（先补基类，再补实例）。
   - ✅ 已落地：22 个参数化基类已注册 `factor_base`（type=periodic, instance_type=composite），其复合因子实例已注册 `factor_library`（factor_type=composite）；`AD_LINE_SLOPE` 显式回填 `evaluation_type=technical_ts`，其余回填 `technical`。

### 阶段三：RL 复刻对接（待 RL 引擎实施）

7. RL 词表派生时：特征 token 从"基础因子 + 复合因子"派生，算子 token 从"算子表"派生，保证与 AlphaMaster 语义对齐。
8. 复刻完成后，用映射表逐项核对 RL 生成的公式能被本系统引擎求值、能被因子库消费。