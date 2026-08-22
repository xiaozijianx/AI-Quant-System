# -*- coding: utf-8 -*-
# 因子库初始化脚本
"""
从各 CASE 工程导入全部已实现因子到 PostgreSQL
来源:
    - CASE-AI量化系统/ml_strategy/feature_engine.py (50 因子)
    - CASE-AI量化系统/morning_brief/lib/factor_runner.py (14 因子)
    - CASE-C-多因子选股/factor_lib.py (10 因子)
    - CASE-网格与多因子/factor_engine.py (8 因子)
    - CASE-基于RL的交易策略-2/7-主力行为识别.py (10 因子)
    - CASE-缠论精华量化/chan_analyzer.py (7 因子)
    - CASE-AI量化系统/dragon_strategy/dragon_picker.py (6 因子)
    - CASE-Talib技术指标库 (158 指标)
    - qinghua WorldQuant 示例因子 (5 因子)
    - Barra 风格因子 (10 因子)
    - 金融工程规划因子 (华泰231/Qlib Alpha158/MASTER, 标注为规划)
"""

from __future__ import annotations
from lib.factor_db import (
    init_tables, upsert_factor, list_factors, upsert_base, list_bases,
    _get_conn, hard_delete_factor,
)

# ============================================================
# 因子定义数据 (全量)
# ============================================================

BASIC_FACTORS = [
    # ============================================================
    # 一、价量因子 (来源: ml_strategy/feature_engine.py)
    # formula统一为表达式引擎可执行格式: ts_*(Close/Volume/High/Low)
    # ============================================================
    {"factor_id": "ret_1d", "name": "1日收益率", "category": "price_volume", "sub_category": "收益率",
     "direction": "neutral", "formula": "returns(1)", "period": "1d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ret_3d", "name": "3日收益率", "category": "price_volume", "sub_category": "收益率",
     "direction": "neutral", "formula": "returns(3)", "period": "3d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ret_5d", "name": "5日收益率", "category": "price_volume", "sub_category": "收益率",
     "direction": "neutral", "formula": "returns(5)", "period": "5d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ret_10d", "name": "10日收益率", "category": "price_volume", "sub_category": "收益率",
     "direction": "neutral", "formula": "returns(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "amplitude_5d", "name": "5日振幅", "category": "price_volume", "sub_category": "振幅",
     "direction": "neutral", "formula": "amplitude(5)", "period": "5d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "amplitude_10d", "name": "10日振幅", "category": "price_volume", "sub_category": "振幅",
     "direction": "neutral", "formula": "amplitude(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "vol_ratio_5d", "name": "5日量比", "category": "price_volume", "sub_category": "量比",
     "direction": "positive", "formula": "volume_ratio(5)", "period": "5d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "vol_ratio_10d", "name": "10日量比", "category": "price_volume", "sub_category": "量比",
     "direction": "positive", "formula": "volume_ratio(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "price_volume_corr_10d", "name": "10日价量相关", "category": "price_volume", "sub_category": "价量相关",
     "direction": "neutral", "formula": "price_volume_corr(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    # 注: 原 turnover_change_5d(实为量比变化)已由 vol_ratio_change_5d 取代, 旧 ID 在 run_init 硬删除

    # ============================================================
    # 二、动量因子 (来源: ml_strategy/feature_engine.py + CASE-C + 网格)
    # ============================================================
    {"factor_id": "momentum_5d", "name": "5日动量", "category": "momentum", "sub_category": "ROC",
     "direction": "positive", "formula": "momentum(5)", "period": "5d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_10d", "name": "10日动量", "category": "momentum", "sub_category": "ROC",
     "direction": "positive", "formula": "momentum(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_20d", "name": "20日动量", "category": "momentum", "sub_category": "ROC",
     "direction": "positive", "formula": "momentum(20)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_60d", "name": "60日动量", "category": "momentum", "sub_category": "ROC",
     "direction": "positive", "formula": "momentum(60)", "period": "60d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_slope_10d", "name": "10日动量斜率", "category": "momentum", "sub_category": "斜率",
     "direction": "positive", "formula": "momentum(10) - ts_Shift(momentum(10), 5)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_slope_20d", "name": "20日动量斜率", "category": "momentum", "sub_category": "斜率",
     "direction": "positive", "formula": "momentum(20) - ts_Shift(momentum(20), 10)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_accel_10d", "name": "10日动量加速度", "category": "momentum", "sub_category": "加速度",
     "direction": "neutral", "formula": "(momentum(10) - ts_Shift(momentum(10), 5)) - ts_Shift(momentum(10) - ts_Shift(momentum(10), 5), 5)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "momentum_accel_20d", "name": "20日动量加速度", "category": "momentum", "sub_category": "加速度",
     "direction": "neutral", "formula": "(momentum(20) - ts_Shift(momentum(20), 10)) - ts_Shift(momentum(20) - ts_Shift(momentum(20), 10), 10)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "MOM_1M", "name": "一月动量", "category": "momentum", "sub_category": "累计收益",
     "direction": "positive", "formula": "returns(21)", "period": "21d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    {"factor_id": "MOM_3M", "name": "三月动量", "category": "momentum", "sub_category": "累计收益",
     "direction": "positive", "formula": "returns(63)", "period": "63d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    {"factor_id": "MOM_6M", "name": "六月动量", "category": "momentum", "sub_category": "累计收益",
     "direction": "positive", "formula": "returns(126)", "period": "126d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},

    # ============================================================
    # 三、反转因子
    # ============================================================
    {"factor_id": "REV_5D", "name": "五日反转", "category": "reversal", "sub_category": "短期反转",
     "direction": "positive", "formula": "reversal(5)", "period": "5d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},

    # ============================================================
    # 四、波动率因子 (来源: ml_strategy + CASE-C + 网格)
    # ============================================================
    {"factor_id": "atr_norm_14", "name": "ATR归一化波动", "category": "volatility", "sub_category": "ATR",
     "direction": "negative", "formula": "atr(14)", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "hist_vol_10d", "name": "10日历史波动率", "category": "volatility", "sub_category": "历史波动",
     "direction": "negative", "formula": "volatility(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "hist_vol_20d", "name": "20日历史波动率", "category": "volatility", "sub_category": "历史波动",
     "direction": "negative", "formula": "volatility(20)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "hist_vol_60d", "name": "60日历史波动率", "category": "volatility", "sub_category": "历史波动",
     "direction": "negative", "formula": "volatility(60)", "period": "60d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "vol_change_10d", "name": "10日波动变化", "category": "volatility", "sub_category": "波动变化",
     "direction": "neutral", "formula": "volatility(10) / ts_Shift(volatility(10), 10) - 1", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "vol_change_20d", "name": "20日波动变化", "category": "volatility", "sub_category": "波动变化",
     "direction": "neutral", "formula": "volatility(20) / ts_Shift(volatility(20), 20) - 1", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "VOL_20", "name": "20日年化波动率", "category": "volatility", "sub_category": "年化波动",
     "direction": "positive", "formula": "-volatility(20)", "period": "20d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    {"factor_id": "VOL_60", "name": "60日年化波动率", "category": "volatility", "sub_category": "年化波动",
     "direction": "positive", "formula": "-volatility(60)", "period": "60d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},

    # ============================================================
    # 五、流动性因子 (来源: CASE-C + 晨会 + 网格)
    # ============================================================
    {"factor_id": "LIQ_20", "name": "20日流动性", "category": "liquidity", "sub_category": "成交额",
     "direction": "positive", "formula": "-ts_Log(ts_Mean(amount(), 20))", "period": "20d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    # ---- 量比系列 (统一命名: 与 vol_ratio_5d/10d 同族, 前缀规则自动挂 volume_ratio 基类) ----
    # 注: 原 TURN_20/turnover_ratio/turnover_change_5d 三个"换手"命名的量比因子已由新 ID 取代
    #      (旧 ID 在 run_init 中软停用, 保留历史与旧因子包兼容);
    #      真换手率由 turnover_rate/turnover_rate_20 承载 (见行情字段区)。
    {"factor_id": "vol_ratio_20", "name": "20日量比", "category": "liquidity", "sub_category": "量比",
     "direction": "positive", "formula": "volume_ratio(20)", "period": "20d",
     "data_source": "日K", "origin": "CASE-网格与多因子", "is_custom": False},
    {"factor_id": "vol_ratio_20_low", "name": "20日量比(反向)", "category": "liquidity", "sub_category": "量比",
     "direction": "negative", "formula": "volume_ratio(20)", "period": "20d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    {"factor_id": "vol_ratio_change_5d", "name": "5日量比变化", "category": "price_volume", "sub_category": "量比",
     "direction": "neutral", "formula": "volume_ratio(5) / volume_ratio(20)", "period": "5d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},

    # ============================================================
    # 六、技术指标因子 (来源: ml_strategy + CASE-C + 网格 + Talib)
    # ============================================================
    {"factor_id": "rsi_14", "name": "14日RSI", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "rsi(14)", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "rsi_6", "name": "6日RSI", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "rsi(6)", "period": "6d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "RSI_14", "name": "14日RSI(偏离50)", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "rsi(14) - 50", "period": "14d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    {"factor_id": "adx_14", "name": "14日ADX", "category": "momentum", "sub_category": "趋势强度",
     "direction": "positive", "formula": "adx(14)", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "macd_dif", "name": "MACD DIF", "category": "momentum", "sub_category": "趋势",
     "direction": "positive", "formula": "ts_MACD_DIF(Close, 12, 26, 9)", "period": "26d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "macd_signal", "name": "MACD DEA", "category": "momentum", "sub_category": "趋势",
     "direction": "positive", "formula": "ts_MACD_DEA(Close, 12, 26, 9)", "period": "26d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "macd_hist", "name": "MACD柱状图", "category": "momentum", "sub_category": "趋势",
     "direction": "positive", "formula": "ts_MACD_HIST(Close, 12, 26, 9)", "period": "26d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "bbands_position", "name": "布林位置", "category": "volatility", "sub_category": "布林带",
     "direction": "neutral", "formula": "ts_BOLL_POS(Close, 20, 2)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "BOLL_WIDTH", "name": "布林带宽度", "category": "volatility", "sub_category": "布林带",
     "direction": "neutral", "formula": "bbands_width()", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "kdj_k", "name": "KDJ-K", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "ts_KDJ_K(High, Low, Close, 9, 3)", "period": "9d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "kdj_d", "name": "KDJ-D", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "ts_KDJ_D(High, Low, Close, 9, 3)", "period": "9d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "cci_14", "name": "14日CCI", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "cci(14)", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "willr_14", "name": "14日威廉指标", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "willr(14)", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "obv_slope_10d", "name": "OBV斜率10日", "category": "price_volume", "sub_category": "量价",
     "direction": "positive", "formula": "(ts_OBV(Close, Volume) - ts_Mean(ts_OBV(Close, Volume), 10)) / ts_Mean(ts_OBV(Close, Volume), 10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "BIAS_20", "name": "20日乖离率", "category": "price_volume", "sub_category": "均线",
     "direction": "positive", "formula": "-bias(20)", "period": "20d",
     "data_source": "日K", "origin": "CASE-C-多因子选股", "is_custom": False},
    # macd_signal_grid 已删除: 金叉/死叉信号, 非数值因子

    # ============================================================
    # 七、均线与形态因子 (来源: ml_strategy/feature_engine.py)
    # ============================================================
    {"factor_id": "ma5_bias", "name": "5日均线乖离", "category": "pattern", "sub_category": "均线",
     "direction": "neutral", "formula": "bias(5)", "period": "5d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ma10_bias", "name": "10日均线乖离", "category": "pattern", "sub_category": "均线",
     "direction": "neutral", "formula": "bias(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ma20_bias", "name": "20日均线乖离", "category": "pattern", "sub_category": "均线",
     "direction": "neutral", "formula": "bias(20)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ma60_bias", "name": "60日均线乖离", "category": "pattern", "sub_category": "均线",
     "direction": "neutral", "formula": "bias(60)", "period": "60d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "ma_bull_score", "name": "均线多头排列", "category": "pattern", "sub_category": "均线排列",
     "direction": "positive",
     "formula": "(1*(Close > sma(5)) + 1*(Close > sma(10)) + 1*(Close > sma(20)) + 1*(Close > sma(60)) + 1*(sma(5) > sma(10)) + 1*(sma(10) > sma(20))) / 6",
     "period": "60d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "upper_shadow_ratio", "name": "上影线比", "category": "pattern", "sub_category": "K线形态",
     "direction": "negative", "formula": "np.maximum(High - Close, High - Open) / (High - Low)", "period": "1d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "lower_shadow_ratio", "name": "下影线比", "category": "pattern", "sub_category": "K线形态",
     "direction": "positive", "formula": "np.maximum(Close - Low, Open - Low) / (High - Low)", "period": "1d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "body_ratio", "name": "实体比", "category": "pattern", "sub_category": "K线形态",
     "direction": "neutral", "formula": "abs(Close - Open) / (High - Low)", "period": "1d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "new_high_20d", "name": "20日新高", "category": "pattern", "sub_category": "新高新低",
     "direction": "positive", "formula": "(High >= ts_Max(High, 20)) * 1.0", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "new_low_20d", "name": "20日新低", "category": "pattern", "sub_category": "新高新低",
     "direction": "negative", "formula": "(Low <= ts_Min(Low, 20)) * 1.0", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "price_position", "name": "区间位置", "category": "pattern", "sub_category": "箱体位置",
     "direction": "negative", "formula": "price_position(60)", "period": "60d",
     "data_source": "日K", "origin": "CASE-网格与多因子", "is_custom": False},
    # 区间位置 20/50 日实例 (依赖 price_position 参数化基类, 复合因子, 见 AlphaMaster特征算子与因子库映射方案.md 3.4)
    {"factor_id": "price_position_20", "name": "区间位置20日", "category": "pattern", "sub_category": "箱体位置",
     "direction": "negative", "formula": "price_position(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "price_position_50", "name": "区间位置50日", "category": "pattern", "sub_category": "箱体位置",
     "direction": "negative", "formula": "price_position(50)", "period": "50d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},

    # ============================================================
    # 八、交互因子 (来源: ml_strategy/feature_engine.py)
    # ============================================================
    {"factor_id": "mom_vol_cross", "name": "动量波动交叉", "category": "composite", "sub_category": "交叉",
     "direction": "neutral", "formula": "momentum(20) * atr(14)", "period": "20d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "adx_rsi_cross", "name": "ADX-RSI交叉", "category": "composite", "sub_category": "交叉",
     "direction": "neutral", "formula": "adx(14) * (rsi(14)-50)/50", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "vol_ratio_mom_cross", "name": "量比动量交叉", "category": "composite", "sub_category": "交叉",
     "direction": "neutral", "formula": "volume_ratio(5) * momentum(10)", "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "rsi_bbands_cross", "name": "RSI布林交叉", "category": "composite", "sub_category": "交叉",
     "direction": "neutral", "formula": "(rsi(14)-50)/50 * bbands()", "period": "14d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "macd_adx_cross", "name": "MACD-ADX交叉", "category": "composite", "sub_category": "交叉",
     "direction": "neutral", "formula": "macd() * adx(14)", "period": "26d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},
    {"factor_id": "vol_mom_accel_cross", "name": "波动动量加速交叉", "category": "composite", "sub_category": "交叉",
     "direction": "neutral",
     "formula": "volatility(10) * ((momentum(10) - ts_Shift(momentum(10), 5)) - ts_Shift((momentum(10) - ts_Shift(momentum(10), 5)), 5))",
     "period": "10d",
     "data_source": "日K", "origin": "ml_strategy/feature_engine", "is_custom": False},

    # ============================================================
    # AlphaMaster 映射补充复合因子 (依赖已有基类, 见 AlphaMaster特征算子与因子库映射方案.md 3.3.1)
    # ============================================================
    {"factor_id": "EMA_RATIO_12_26", "name": "EMA12/EMA26比值", "category": "composite", "sub_category": "趋势",
     "direction": "neutral", "formula": "ema(12)/ema(26)-1", "period": "26d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "VOL_REGIME", "name": "波动状态", "category": "composite", "sub_category": "波动率",
     "direction": "neutral", "formula": "atr(14)/ts_Mean(atr(14),20)-1", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "PRESSURE", "name": "买卖压力", "category": "composite", "sub_category": "K线形态",
     "direction": "neutral", "formula": "(Close-Open)/(High-Low)", "period": "1d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "VOL_Z", "name": "量能zscore", "category": "composite", "sub_category": "量比",
     "direction": "neutral", "formula": "(volume_ratio(20)-1)/ts_Stdev(volume_ratio(20),20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "VWAP_DEV", "name": "VWAP偏离", "category": "composite", "sub_category": "价量",
     "direction": "neutral", "formula": "(Close-VWAP)/VWAP", "period": "1d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},

    # ============================================================
    # AlphaMaster 映射补充参数化基类实例 (复合因子, 见 AlphaMaster特征算子与因子库映射方案.md 3.3.2)
    # ============================================================
    {"factor_id": "TREND_STRENGTH_50", "name": "趋势强度50", "category": "composite", "sub_category": "趋势",
     "direction": "neutral", "formula": "trend_strength(50)", "period": "50d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "GK_VOL", "name": "Garman-Klass波动", "category": "composite", "sub_category": "波动率",
     "direction": "neutral", "formula": "gk_vol(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "PARKINSON_VOL", "name": "Parkinson波动", "category": "composite", "sub_category": "波动率",
     "direction": "neutral", "formula": "parkinson_vol(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "YANG_ZHANG_VOL", "name": "Yang-Zhang波动", "category": "composite", "sub_category": "波动率",
     "direction": "neutral", "formula": "yang_zhang_vol(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "RS_VOL", "name": "Rogers-Satchell波动", "category": "composite", "sub_category": "波动率",
     "direction": "neutral", "formula": "rs_vol(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "AC1", "name": "一阶自相关", "category": "composite", "sub_category": "统计",
     "direction": "neutral", "formula": "autocorr(20,1)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "AC2", "name": "二阶自相关", "category": "composite", "sub_category": "统计",
     "direction": "neutral", "formula": "autocorr(20,2)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "TYPICAL_DEV", "name": "典型价偏离", "category": "composite", "sub_category": "反转",
     "direction": "neutral", "formula": "typical_dev(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "DMI_DIFF_14", "name": "DMI差值14", "category": "composite", "sub_category": "趋势",
     "direction": "neutral", "formula": "dmi_diff(14)", "period": "14d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "TRIX_15", "name": "TRIX15", "category": "composite", "sub_category": "动量",
     "direction": "neutral", "formula": "trix(15)", "period": "15d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "TRIX_SIGNAL", "name": "TRIX信号", "category": "composite", "sub_category": "动量",
     "direction": "neutral", "formula": "trix(15)-ts_Mean(trix(15),9)", "period": "15d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "AMIHUD_ILLIQ", "name": "Amihud非流动性", "category": "composite", "sub_category": "流动性",
     "direction": "neutral", "formula": "amihud_illiq(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "KYLE_LAMBDA", "name": "Kyle lambda", "category": "composite", "sub_category": "流动性",
     "direction": "neutral", "formula": "kyle_lambda(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "CMF_20", "name": "Chaikin资金流", "category": "composite", "sub_category": "量能",
     "direction": "neutral", "formula": "cmf(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "AD_LINE_SLOPE", "name": "A/D线斜率", "category": "composite", "sub_category": "量能",
     "direction": "neutral", "formula": "ad_line_slope(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "HURST_50", "name": "Hurst指数50", "category": "composite", "sub_category": "统计",
     "direction": "neutral", "formula": "hurst(50)", "period": "50d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "FRACTAL_DIM_30", "name": "分形维30", "category": "composite", "sub_category": "统计",
     "direction": "neutral", "formula": "fractal_dim(30)", "period": "30d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "RET_ENTROPY_20", "name": "收益熵20", "category": "composite", "sub_category": "统计",
     "direction": "neutral", "formula": "ret_entropy(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "KELTNER_POS_20", "name": "Keltner位置20", "category": "composite", "sub_category": "通道",
     "direction": "neutral", "formula": "keltner(20)", "period": "20d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "ICHIMOKU_KIJUN_DEV", "name": "Ichimoku基准线偏离", "category": "composite", "sub_category": "通道",
     "direction": "neutral", "formula": "ichimoku_kijun(26)", "period": "26d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "ICHIMOKU_TENKAN_DEV", "name": "Ichimoku转换线偏离", "category": "composite", "sub_category": "通道",
     "direction": "neutral", "formula": "ichimoku_tenkan(9)", "period": "9d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    {"factor_id": "SUPERTREND_DIR", "name": "SuperTrend方向", "category": "composite", "sub_category": "通道",
     "direction": "neutral", "formula": "supertrend(14)", "period": "14d",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},

    # ============================================================
    # 九、价值/质量/成长因子 (来源: 晨会 + ML)
    # formula统一为FN(field)格式, 通过财务数据引擎读取
    # ============================================================
    {"factor_id": "ROE", "name": "净资产收益率", "category": "fundamental", "sub_category": "盈利",
     "direction": "positive", "formula": "FN(roe)", "period": "财务",
     "data_source": "财务", "origin": "晨会分析/factor_runner", "is_custom": False},
    {"factor_id": "NetProfit_YoY", "name": "净利润同比", "category": "fundamental", "sub_category": "成长",
     "direction": "positive", "formula": "FN(net_profit)", "period": "财务",
     "data_source": "财务", "origin": "晨会分析/factor_runner", "is_custom": False},
    {"factor_id": "GrossMargin", "name": "毛利率", "category": "fundamental", "sub_category": "盈利",
     "direction": "positive", "formula": "FN(gross_margin)", "period": "财务",
     "data_source": "财务", "origin": "晨会分析/factor_runner", "is_custom": False},
    {"factor_id": "NegDebtRatio", "name": "负资产负债率", "category": "fundamental", "sub_category": "杠杆",
     "direction": "positive", "formula": "-FN(debt_ratio)", "period": "财务",
     "data_source": "财务", "origin": "晨会分析/factor_runner", "is_custom": False},

    # ============================================================
    # 十、龙头因子 (来源: dragon_strategy/dragon_picker.py)
    #   仅保留 DRAGON_DAY_CHANGE(涨幅分段打分, 库中无同源因子); 其余6个按计划下架
    #   详情见 docs/因子库D组文字化因子处理计划.md
    # ============================================================
    {"factor_id": "DRAGON_DAY_CHANGE", "name": "龙头涨幅分", "category": "dragon", "sub_category": "涨幅",
     "direction": "positive", "formula": "ts_DragonDayChange(Close)", "period": "1d",
     "data_source": "日K", "origin": "dragon_strategy/dragon_picker", "is_custom": False},

    # ============================================================
    # 十一、微观结构因子 (来源: CASE-基于RL的交易策略-2/7-主力行为识别.py)
    # ============================================================
    {"factor_id": "ofi_abs", "name": "订单流不平衡", "category": "microstructure", "sub_category": "订单流",
     "direction": "neutral", "formula": "abs(买量-卖量)/总量", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "large_ratio", "name": "大单比例", "category": "microstructure", "sub_category": "大单",
     "direction": "neutral", "formula": "成交额>均值3倍的比例", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "cancel_rate", "name": "撤单率", "category": "microstructure", "sub_category": "交易行为",
     "direction": "neutral", "formula": "撤单数/总交易数", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "interval_cv", "name": "成交间隔变异系数", "category": "microstructure", "sub_category": "时间序列",
     "direction": "neutral", "formula": "成交时间间隔std/mean", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "recovery_speed", "name": "冲击恢复速度", "category": "microstructure", "sub_category": "价格冲击",
     "direction": "neutral", "formula": "大单后价格恢复速度", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "run_length", "name": "方向持续性", "category": "microstructure", "sub_category": "趋势",
     "direction": "neutral", "formula": "连续同向交易平均长度", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "vol_cv", "name": "量变异系数", "category": "microstructure", "sub_category": "交易规模",
     "direction": "neutral", "formula": "成交量std/mean", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "direction_symmetry", "name": "方向对称性", "category": "microstructure", "sub_category": "交易行为",
     "direction": "neutral", "formula": "少方向交易数/多方向交易数", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "limit_ratio", "name": "限价单比例", "category": "microstructure", "sub_category": "交易行为",
     "direction": "neutral", "formula": "限价单数/总交易数", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},
    {"factor_id": "price_volatility_tick", "name": "tick价格波动", "category": "microstructure", "sub_category": "价格波动",
     "direction": "neutral", "formula": "价格变化std/mean(price)", "period": "tick",
     "data_source": "tick", "origin": "CASE-基于RL的交易策略", "is_custom": False},

    # ============================================================
    # 十二、缠论形态因子 (来源: CASE-缠论精华量化/chan_analyzer.py)
    #   归类: 独立完整指标, base_id=自身, factor_type=basic
    #   顶/底分型、笔方向 -> signal 事件信号(形态型, 与CDL同管线); 确认日对齐T+1避免未来函数
    #   中枢 ZG/ZD 动态修正+绝对价格量纲, 暂缓不纳入(evaluation_type=none)
    # ============================================================
    {"factor_id": "CHAN_TOP_FRACTAL", "name": "顶分型", "category": "chan", "sub_category": "分型",
     "direction": "negative", "formula": "ts_ChanTopFractal(High, Low)", "period": "1d",
     "data_source": "日K", "origin": "CASE-缠论精华量化", "is_custom": False},
    {"factor_id": "CHAN_BOTTOM_FRACTAL", "name": "底分型", "category": "chan", "sub_category": "分型",
     "direction": "positive", "formula": "ts_ChanBottomFractal(High, Low)", "period": "1d",
     "data_source": "日K", "origin": "CASE-缠论精华量化", "is_custom": False},
    {"factor_id": "CHAN_STROKE", "name": "笔方向", "category": "chan", "sub_category": "笔",
     "direction": "neutral", "formula": "ts_ChanStroke(High, Low)", "period": "1d",
     "data_source": "日K", "origin": "CASE-缠论精华量化", "is_custom": False},
    {"factor_id": "CHAN_ZG", "name": "中枢上沿", "category": "chan", "sub_category": "中枢",
     "direction": "neutral", "formula": "min(各笔高点) >=3笔重叠", "period": "1d",
     "data_source": "日K", "origin": "CASE-缠论精华量化", "is_custom": False},
    {"factor_id": "CHAN_ZD", "name": "中枢下沿", "category": "chan", "sub_category": "中枢",
     "direction": "neutral", "formula": "max(各笔低点) >=3笔重叠", "period": "1d",
     "data_source": "日K", "origin": "CASE-缠论精华量化", "is_custom": False},
    # CHAN_BUY1/2/3, CHAN_SELL3 已删除: 买卖点是交易信号, 非连续数值因子

    # ============================================================
    # 十三、Barra 风格因子 (来源: qinghua/BarraFactors.mat)
    #   归类: Barra 属"独立完整指标"而非参数化基类, 每个 base_id=自身, factor_type=basic
    #   (由 FIXED_PREFIX_RULES ("BARRA_","barra") 自动分类, 注册到 factor_base 成为基础因子)
    #   市值代理: 近20日成交额均值 ts_Mean(Amount,20) (与 build_marketcap_proxy_map 同口径, 点-in-time 无前视)
    #   市场代理: 截面均值收益率 (与 ts_BETA 同口径, 面板无独立指数)
    #   注意: SIZE/NONLINEAR_MV 归 price_volume(量价) 而非 fundamental, 避免被
    #         category=fundamental -> financial 的默认路由误判为财务因子
    # ============================================================
    {"factor_id": "BARRA_SIZE", "name": "规模因子", "category": "price_volume", "sub_category": "风格",
     "direction": "neutral", "formula": "ts_Log(ts_Mean(Amount, 20))", "period": "日K",
     "data_source": "日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_BETA", "name": "Beta因子", "category": "volatility", "sub_category": "风格",
     "direction": "neutral", "formula": "ts_BETA(Close, 250)", "period": "日K",
     "data_source": "日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_MOMENTUM", "name": "Barra动量", "category": "momentum", "sub_category": "风格",
     "direction": "positive", "formula": "ts_BarraMomentum(Close, 504)", "period": "日K",
     "data_source": "日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_RESVOL", "name": "残差波动率", "category": "volatility", "sub_category": "风格",
     "direction": "negative", "formula": "ts_RESVOL(Close, 250)", "period": "日K",
     "data_source": "日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_NONLINEAR_MV", "name": "非线性市值", "category": "price_volume", "sub_category": "风格",
     "direction": "neutral", "formula": "ts_Log(ts_Mean(Amount, 20)) ** 3", "period": "日K",
     "data_source": "日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_BTOP", "name": "账面市值比", "category": "fundamental", "sub_category": "风格",
     "direction": "positive", "formula": "FN(total_equity) / ts_Mean(Amount, 20)", "period": "日K",
     "data_source": "财务+日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_LIQUIDITY", "name": "Barra流动性", "category": "liquidity", "sub_category": "风格",
     "direction": "negative", "formula": "-ts_Log(ts_Mean(Turnover, 21))", "period": "日K",
     "data_source": "日K", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_PROFIT", "name": "Barra盈利", "category": "fundamental", "sub_category": "风格",
     "direction": "positive", "formula": "cs_Zscore(FN(roe)) + cs_Zscore(FN(roa)) + cs_Zscore(FN(net_margin))", "period": "财务",
     "data_source": "财务", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_GROWTH", "name": "Barra成长", "category": "fundamental", "sub_category": "风格",
     "direction": "positive", "formula": "cs_Zscore(ts_PctChange(FN(revenue), 252)) + cs_Zscore(ts_PctChange(FN(net_profit), 252))", "period": "财务",
     "data_source": "财务", "origin": "qinghua/BarraFactors", "is_custom": False},
    {"factor_id": "BARRA_LEVERAGE", "name": "Barra杠杆", "category": "fundamental", "sub_category": "风格",
     "direction": "neutral", "formula": "cs_Zscore(1 / (FN(total_equity) / ts_Mean(Amount, 20))) + cs_Zscore(FN(debt_ratio))", "period": "财务",
     "data_source": "财务", "origin": "qinghua/BarraFactors", "is_custom": False},

    # ============================================================
    # 十四、WorldQuant 示例复合因子 (来源: qinghua/day2_M.ipynb)
    # ============================================================
    {"factor_id": "WQ_PRICE_VOLUME", "name": "量价混合因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay((ts_Decay(close(),10)-ts_Decay(vwap(),10))/vwap()*(high()-low()),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day2_M", "is_custom": False},
    {"factor_id": "WQ_VOL_ANOMALY", "name": "量能异常因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay(ts_Decay(volume(),5)/vwap()*(high()-low()),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day2_M", "is_custom": False},
    # 注: WQ_IDIO_RET 已删除 (2026-08-15) -- 清华原版中 IdioRet 仅是中间变量,
    #     与库中 idioret() 字段因子完全等值, 冗余; 旧 ID 在 run_init 中硬删除
    {"factor_id": "WQ_MOMENTUM_DECAY", "name": "动量衰减因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "negative", "formula": "ts_Decay(ts_Delta(close(),5),20)",
     "period": "20d", "data_source": "日K", "origin": "qinghua/day2_M", "is_custom": False},
    {"factor_id": "WQ_VOL_PRICE_DECAY", "name": "量价衰减因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay(close()*volume(),20)",
     "period": "20d", "data_source": "日K", "origin": "qinghua/day2_M", "is_custom": False},

    # ============================================================
    # 一-bis、清华day1_A 的 10 个 WQ 复杂因子 (除与WQ_PRICE_VOLUME重叠的第1个外)
    # 字段: Close/High/Low/Volume/VWAP(自动) + 派生字段 IdioRet/Value/TotalRet
    # ============================================================
    {"factor_id": "WQ_IDIO_VOL", "name": "特异量比因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay(idioret()*(volume()/ts_Delay(volume(),1)),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_IDIO_AMPLITUDE_VOL", "name": "特异振幅量比因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay(idioret()*(high()-low())/close()*(volume()/ts_Delay(volume(),1)),60)",
     "period": "60d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_VWAP_AMPLITUDE", "name": "VWAP振幅量比因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay(vwap()/close()*(high()-low())/close()*(volume()/ts_Delay(volume(),1)),10)",
     "period": "10d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_PRICE_AMPLITUDE_MEAN", "name": "量价振幅均值因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Mean((ts_Decay(close(),10)-ts_Decay(vwap(),10))/vwap()*(high()-low())/close(),20)",
     "period": "20d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_VALUE_DECAY", "name": "成交额衰减因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay((ts_Decay(value(),10)-ts_Decay(vwap(),10))/vwap()*(high()-low()),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_VOL_DECAY", "name": "量能衰减因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay((ts_Decay(volume(),10)-ts_Decay(vwap(),10))/vwap()*(high()-low()),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_HIGH_DECAY", "name": "最高价衰减因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay((ts_Decay(high(),10)-ts_Decay(vwap(),10))/vwap()*(high()-low()),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_TOTALRET_DECAY", "name": "总收益衰减因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay((ts_Decay(totalret(),10)-ts_Decay(vwap(),10))/vwap()*(high()-low()),40)",
     "period": "40d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},
    {"factor_id": "WQ_VOL_AMPLITUDE_RATIO", "name": "量幅比因子", "category": "composite", "sub_category": "WorldQuant",
     "direction": "positive", "formula": "-1*ts_Decay(volume()/(high()-low()),20)",
     "period": "20d", "data_source": "日K", "origin": "qinghua/day1_A", "is_custom": False},

    # ============================================================
    # 十四-bis、最基础行情字段因子 (来源: 内置)
    #   无时间周期本身即是因子的 fixed 基类, 同时登记为基础因子(base_id=自身)。
    #   open/high/low/close/volume/amount/vwap: 原始行情字段(恒等变换)
    #   value/idioret/totalret: 派生字段(由引擎在_build_field_dfs计算)
    #   这些是其他因子(尤其WQ量价因子)的最根本底层单元。
    # ============================================================
    {"factor_id": "open", "name": "开盘价", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "open()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "high", "name": "最高价", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "high()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "low", "name": "最低价", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "low()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "close", "name": "收盘价", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "close()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "volume", "name": "成交量", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "volume()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "amount", "name": "成交额", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "amount()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "vwap", "name": "均价VWAP", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "vwap()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "value", "name": "规模代理值", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "value()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "idioret", "name": "特异质收益", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "idioret()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "totalret", "name": "日收益率", "category": "price_volume", "sub_category": "行情字段",
     "direction": "neutral", "formula": "totalret()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    # ---- 换手率: 真实换手率行情字段 (固定基础因子, 不参数化) + 时间平均派生复合因子 ----
    # 注: 数据完备性 —— turnover_rate 近期(近45天)非空率约92%, 2025/2026年约91%,
    #     长历史(2015-2020)缺失20-42%; 原 TURN_20 等"换手"命名因子实为量比, 已改挂 volume_ratio。
    {"factor_id": "turnover_rate", "name": "换手率", "category": "price_volume", "sub_category": "换手率",
     "direction": "neutral", "formula": "turnover_rate()", "period": "无",
     "data_source": "日K", "origin": "内置", "is_custom": False},
    {"factor_id": "turnover_rate_20", "name": "20日平均换手率(反向)", "category": "liquidity", "sub_category": "换手率",
     "direction": "positive", "formula": "-ts_Mean(Turnover, 20)", "period": "20d",
     "data_source": "日K", "origin": "因子库重构", "is_custom": False},

    # ============================================================
    # 十五、ML/隐因子 (来源: 主系统 + QuantStats)
    #   已下架: ML_PROB(每股独立模型,跨股不可比) / SVD_HIDDEN(隐因子,无固定计算)
    #   未来规划独立"ML因子/隐因子"页面; 详见 docs/因子库D组文字化因子处理计划.md
    # ============================================================

    # ============================================================
    # 十六、TA-Lib 技术指标库 (来源: CASE-Talib技术指标库, 158种)
    # ============================================================
    # 均线类 (Overlap)
    {"factor_id": "TALIB_SMA", "name": "简单移动平均(20日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "sma(20)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_EMA", "name": "指数移动平均(20日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "ema(20)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_WMA", "name": "加权移动平均(20日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "wma(20)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_DEMA", "name": "双指数移动平均(30日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "dema(30)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_TEMA", "name": "三指数移动平均(30日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "tema(30)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_KAMA", "name": "考夫曼自适应均线(30日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "kama(30)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_TRIMA", "name": "三角移动平均(30日)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "trima(30)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_MAMA", "name": "MESA自适应均线(自适应)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "mama()", "period": "自适应",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_SAR", "name": "抛物线SAR(自适应)", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "sar()", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "SAR_DIST", "name": "SAR距离", "category": "moving_average", "sub_category": "均线",
     "direction": "neutral", "formula": "sar_dist()", "period": "可配",
     "data_source": "日K", "origin": "AlphaMaster映射", "is_custom": False},
    # 动量类 (Momentum)
    {"factor_id": "TALIB_MOM", "name": "动量", "category": "momentum", "sub_category": "动量",
     "direction": "positive", "formula": "ts_MOM(Close, 10)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_ROC", "name": "变化率", "category": "momentum", "sub_category": "动量",
     "direction": "positive", "formula": "ts_ROC(Close, 10)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_PPO", "name": "价格震荡百分比", "category": "momentum", "sub_category": "动量",
     "direction": "neutral", "formula": "ts_PPO(Close, 12, 26)", "period": "26d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_STOCHRSI", "name": "随机RSI", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "ts_STOCHRSI_K(Close, 14, 3, 3)", "period": "14d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_STOCHF", "name": "快速随机", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "ts_STOCHF_K(High, Low, Close, 5, 3)", "period": "9d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_AROON", "name": "阿隆指标", "category": "momentum", "sub_category": "趋势",
     "direction": "positive", "formula": "ts_AROON_UP(High, Low, 25)", "period": "25d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_AROONOSC", "name": "阿隆震荡", "category": "momentum", "sub_category": "趋势",
     "direction": "neutral", "formula": "ts_AROONOSC(High, Low, 25)", "period": "25d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_MFI", "name": "资金流向指标", "category": "momentum", "sub_category": "量价",
     "direction": "neutral", "formula": "ts_MFI(High, Low, Close, Volume, 14)", "period": "14d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_UO", "name": "终极震荡", "category": "momentum", "sub_category": "超买超卖",
     "direction": "neutral", "formula": "ts_ULTOSC(High, Low, Close)", "period": "28d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_ADXR", "name": "ADX评级", "category": "momentum", "sub_category": "趋势强度",
     "direction": "positive", "formula": "ts_ADXR(High, Low, Close, 14)", "period": "14d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    # 波动率类 (Volatility)
    {"factor_id": "TALIB_NATR", "name": "归一化ATR", "category": "volatility", "sub_category": "波动率",
     "direction": "negative", "formula": "ts_NATR(High, Low, Close, 14)", "period": "14d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_TRANGE", "name": "真实波幅", "category": "volatility", "sub_category": "波动率",
     "direction": "neutral", "formula": "ts_TRANGE(High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    # 成交量类 (Volume)
    {"factor_id": "TALIB_OBV", "name": "能量潮", "category": "price_volume", "sub_category": "量价",
     "direction": "positive", "formula": "ts_OBV(Close, Volume)", "period": "累积",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_AD", "name": "累积派发线", "category": "price_volume", "sub_category": "量价",
     "direction": "positive", "formula": "ts_AD(High, Low, Close, Volume)", "period": "累积",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_ADOSC", "name": "累积震荡", "category": "price_volume", "sub_category": "量价",
     "direction": "neutral", "formula": "ts_ADOSC(High, Low, Close, Volume)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    # 价格变换 (Price Transform)
    {"factor_id": "TALIB_AVGPRICE", "name": "均价", "category": "price_volume", "sub_category": "价格",
     "direction": "neutral", "formula": "ts_AVGPRICE(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_MEDPRICE", "name": "中价", "category": "price_volume", "sub_category": "价格",
     "direction": "neutral", "formula": "ts_MEDPRICE(High, Low)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_TYPPRICE", "name": "典型价", "category": "price_volume", "sub_category": "价格",
     "direction": "neutral", "formula": "ts_TYPPRICE(High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_WCLPRICE", "name": "加权收盘价", "category": "price_volume", "sub_category": "价格",
     "direction": "neutral", "formula": "ts_WCLPRICE(High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    # 统计类 (Statistic)
    {"factor_id": "TALIB_BETA", "name": "Beta系数", "category": "volatility", "sub_category": "统计",
     "direction": "neutral", "formula": "ts_BETA(Close, 20)", "period": "20d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_CORREL", "name": "相关系数", "category": "volatility", "sub_category": "统计",
     "direction": "neutral", "formula": "ts_CORREL(Close, 20)", "period": "20d",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_STDDEV", "name": "标准差", "category": "volatility", "sub_category": "统计",
     "direction": "neutral", "formula": "ts_Stdev(Close, 20)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_VAR", "name": "方差", "category": "volatility", "sub_category": "统计",
     "direction": "neutral", "formula": "ts_VAR(Close, 5)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_LINREG", "name": "线性回归", "category": "momentum", "sub_category": "回归",
     "direction": "neutral", "formula": "ts_LINEARREG(Close, 14)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_LINREG_SLOPE", "name": "回归斜率", "category": "momentum", "sub_category": "回归",
     "direction": "neutral", "formula": "ts_LINEARREG_SLOPE(Close, 14)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_LINREG_ANGLE", "name": "回归角度", "category": "momentum", "sub_category": "回归",
     "direction": "neutral", "formula": "ts_LINEARREG_ANGLE(Close, 14)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_LINREG_INTERCEPT", "name": "回归截距", "category": "volatility", "sub_category": "回归",
     "direction": "neutral", "formula": "ts_LINEARREG_INTERCEPT(Close, 14)", "period": "可配",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_LINREG_R2", "name": "回归R2", "category": "volatility", "sub_category": "回归",
     "direction": "neutral", "formula": "ts_LINEARREG_R2(Close, 14)", "period": "可配",
     "evaluation_type": "technical_ts", "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    # 循环类 (Cycle)
    {"factor_id": "TALIB_HT_DCPERIOD", "name": "希尔伯特周期", "category": "momentum", "sub_category": "循环",
     "direction": "neutral", "formula": "ts_HT_DCPERIOD(Close)", "period": "自适应",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_HT_DCPHASE", "name": "希尔伯特相位", "category": "momentum", "sub_category": "循环",
     "direction": "neutral", "formula": "ts_HT_DCPHASE(Close)", "period": "自适应",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},
    {"factor_id": "TALIB_HT_TRENDMODE", "name": "希尔伯特趋势模式", "category": "momentum", "sub_category": "循环",
     "direction": "neutral", "formula": "ts_HT_TRENDMODE(Close)", "period": "自适应",
     "data_source": "日K", "origin": "CASE-Talib技术指标库", "is_custom": False},

    # ============================================================
    # 十七、K线形态因子 (来源: CASE-Talib/3-K线形态识别.py, 61种CDL指标)
    # ============================================================
    {"factor_id": "CDL_HAMMER", "name": "锤子线", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLHAMMER(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_ENGULFING", "name": "吞没形态", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLENGULFING(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_MORNINGSTAR", "name": "晨星", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLMORNINGSTAR(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_EVENINGSTAR", "name": "暮星", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLEVENINGSTAR(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_DOJI", "name": "十字星", "category": "pattern", "sub_category": "犹豫",
     "direction": "neutral", "formula": "ta_CDLDOJI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_SHOOTINGSTAR", "name": "流星线", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLSHOOTINGSTAR(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_HARAMI", "name": "孕线", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLHARAMI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_PIERCING", "name": "刺穿线", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLPIERCING(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_DARKCLOUD", "name": "乌云盖顶", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLDARKCLOUDCOVER(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_THREEWHITESOLDIERS", "name": "三白兵", "category": "pattern", "sub_category": "看涨持续",
     "direction": "positive", "formula": "ta_CDL3WHITESOLDIERS(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_THREEBLACKCROWS", "name": "三乌鸦", "category": "pattern", "sub_category": "看跌持续",
     "direction": "negative", "formula": "ta_CDL3BLACKCROWS(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_ABANDONEDBABY", "name": "弃婴", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLABANDONEDBABY(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_DRAGONFLYDOJI", "name": "蜻蜓十字", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLDRAGONFLYDOJI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_GRAVESTONEDOJI", "name": "墓碑十字", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLGRAVESTONEDOJI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_HANGINGMAN", "name": "上吊线", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLHANGINGMAN(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_INVERTEDHAMMER", "name": "倒锤子线", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLINVERTEDHAMMER(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_MARUBOZU", "name": "光头光脚", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLMARUBOZU(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_SPINNINGTOP", "name": "纺锤顶", "category": "pattern", "sub_category": "犹豫",
     "direction": "neutral", "formula": "ta_CDLSPINNINGTOP(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_RICKSHAWMAN", "name": "黄包车夫", "category": "pattern", "sub_category": "犹豫",
     "direction": "neutral", "formula": "ta_CDLRICKSHAWMAN(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_LONGLEGGEDDOJI", "name": "长腿十字", "category": "pattern", "sub_category": "犹豫",
     "direction": "neutral", "formula": "ta_CDLLONGLEGGEDDOJI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_TASUKIGAP", "name": "跳空缺口", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLTASUKIGAP(Open, High, Low, Close)", "period": "2d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_SEPARATOR", "name": "分离线", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLSEPARATINGLINES(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_BREAKAWAY", "name": "脱离线", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLBREAKAWAY(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_LONGLINE", "name": "长线", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLLONGLINE(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_SHORTLINE", "name": "短线", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLSHORTLINE(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_HOMINGPIGEON", "name": "家鸽", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLHOMINGPIGEON(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_IDENTICALCROWS", "name": "相同乌鸦", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLIDENTICAL3CROWS(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_UPSIDEGAP2CROWS", "name": "向上跳空两乌鸦", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLUPSIDEGAP2CROWS(Open, High, Low, Close)", "period": "2d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_DOWNSIDEGAP3", "name": "向下跳空三法", "category": "pattern", "sub_category": "看跌持续",
     "direction": "negative", "formula": "ta_CDLDOWNSIDEGAP3METHODS(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_HIGHWAVE", "name": "长腿十字(高波)", "category": "pattern", "sub_category": "犹豫",
     "direction": "neutral", "formula": "ta_CDLHIGHWAVE(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_INNECK", "name": "颈内线", "category": "pattern", "sub_category": "看跌持续",
     "direction": "negative", "formula": "ta_CDLINNECK(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_ONNECK", "name": "颈上线", "category": "pattern", "sub_category": "看跌持续",
     "direction": "negative", "formula": "ta_CDLONNECK(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_THRUSTING", "name": "插入线", "category": "pattern", "sub_category": "看跌持续",
     "direction": "negative", "formula": "ta_CDLTHRUSTING(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_COUNTERATTACK", "name": "反击线", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLCOUNTERATTACK(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_LADDERBOTTOM", "name": "梯底", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLLADDERBOTTOM(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_STICKSANDWICH", "name": "条形三明治", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLSTICKSANDWICH(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_STALLEDPATTERN", "name": "停滞形态", "category": "pattern", "sub_category": "看跌持续",
     "direction": "negative", "formula": "ta_CDLSTALLEDPATTERN(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_ADVANCEBLOCK", "name": "大敌当前", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLADVANCEBLOCK(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_BELTHOLD", "name": "捉腰带", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLBELTHOLD(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_CLOSINGMARUBOZU", "name": "收盘光头光脚", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLCLOSINGMARUBOZU(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_MATCHINGLOW", "name": "相同低价", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLMATCHINGLOW(Open, High, Low, Close)", "period": "2d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_MATHOLD", "name": "三兵前阻", "category": "pattern", "sub_category": "看涨持续",
     "direction": "positive", "formula": "ta_CDLMATHOLD(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_UNIQUE3RIVER", "name": "奇特三河床", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLUNIQUE3RIVER(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_TWO_CROWS", "name": "两只乌鸦", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDL2CROWS(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_THREE_STARS_SOUTH", "name": "南方三星", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDL3STARSINSOUTH(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_3OUTSIDE", "name": "三外升/降", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDL3OUTSIDE(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_3INSIDE", "name": "三内升/降", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDL3INSIDE(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_3LINE_STRIKE", "name": "三线打击", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDL3LINESTRIKE(Open, High, Low, Close)", "period": "4d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_HIKKAKE_MOD", "name": "Hikkake修正", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLHIKKAKEMOD(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_TRISTAR", "name": "三星", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLTRISTAR(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_GAPSIDEBYSIDEWHITE", "name": "跳空并列白线", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLGAPSIDESIDEWHITE(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_CONCEALBABYSWALL", "name": "藏婴吞没", "category": "pattern", "sub_category": "看跌反转",
     "direction": "negative", "formula": "ta_CDLCONCEALBABYSWALL(Open, High, Low, Close)", "period": "4d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_KICKING", "name": "反冲", "category": "pattern", "sub_category": "反转",
     "direction": "neutral", "formula": "ta_CDLKICKING(Open, High, Low, Close)", "period": "2d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_TAKURI", "name": "探水竿", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLTAKURI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_XSIDEGAP3METHODS", "name": "向上/向下跳空三法", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLXSIDEGAP3METHODS(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_RISEFALL3METHODS", "name": "上升/下降三法", "category": "pattern", "sub_category": "持续",
     "direction": "neutral", "formula": "ta_CDLRISEFALL3METHODS(Open, High, Low, Close)", "period": "5d",
     "data_source": "日K", "origin": "CASE-Talib/3-K线形态识别", "is_custom": False},
    {"factor_id": "CDL_INVERTEDHAMMER_CONFIRMED", "name": "倒锤确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLINVERTEDHAMMER(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_LONGLEGGEDDOJI_CONFIRMED", "name": "长腿十字确认", "category": "pattern", "sub_category": "犹豫",
     "direction": "neutral", "formula": "ta_CDLLONGLEGGEDDOJI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_DRAGONFLYDOJI_CONFIRMED", "name": "蜻蜓十字确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLDRAGONFLYDOJI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_PIERCING_CONFIRMED", "name": "刺穿线确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLPIERCING(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_HAMMER_CONFIRMED", "name": "锤子线确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLHAMMER(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_MORNINGSTAR_CONFIRMED", "name": "晨星确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLMORNINGSTAR(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_MORNINGDOJISTAR_CONFIRMED", "name": "十字晨星确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLMORNINGDOJISTAR(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_3INSIDE_CONFIRMED", "name": "三内升确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDL3INSIDE(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_3OUTSIDE_CONFIRMED", "name": "三外升确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDL3OUTSIDE(Open, High, Low, Close)", "period": "3d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_ENGULFING_CONFIRMED", "name": "看涨吞没确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLENGULFING(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
    {"factor_id": "CDL_HARAMI_CONFIRMED", "name": "看涨孕线确认", "category": "pattern", "sub_category": "看涨反转",
     "direction": "positive", "formula": "ta_CDLHARAMI(Open, High, Low, Close)", "period": "1d",
     "data_source": "日K", "origin": "CASE-Talib/9-形态选股雷达", "is_custom": False},
]


# ============================================================
# 财务因子 (阶段B扩充, 来源: trade_stock_financial 表)
#   基础因子: 语义独立的标准化财务指标
#   复合因子: 成长(同比派生) / 估值(结合行情)
# ============================================================
FINANCIAL_FACTORS = [
    # ---- 基础因子: 盈利能力 ----
    {"factor_id": "FN_ROA", "name": "总资产报酬率(ROA)", "category": "fundamental", "sub_category": "盈利能力",
     "direction": "positive", "formula": "FN(roa)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_NET_MARGIN", "name": "销售净利率", "category": "fundamental", "sub_category": "盈利能力",
     "direction": "positive", "formula": "FN(net_margin)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_OP_MARGIN", "name": "营业利润率", "category": "fundamental", "sub_category": "盈利能力",
     "direction": "positive", "formula": "FN(op_margin)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_EPS", "name": "每股收益(EPS)", "category": "fundamental", "sub_category": "盈利能力",
     "direction": "positive", "formula": "FN(eps)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    # ---- 基础因子: 偿债/杠杆 ----
    {"factor_id": "FN_DEBT_RATIO", "name": "资产负债率", "category": "fundamental", "sub_category": "偿债能力",
     "direction": "negative", "formula": "FN(debt_ratio)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_CURRENT_RATIO", "name": "流动比率", "category": "fundamental", "sub_category": "偿债能力",
     "direction": "positive", "formula": "FN(current_ratio)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_QUICK_RATIO", "name": "速动比率", "category": "fundamental", "sub_category": "偿债能力",
     "direction": "positive", "formula": "FN(quick_ratio)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    # ---- 基础因子: 营运 ----
    {"factor_id": "FN_ASSETS_TURN", "name": "总资产周转率", "category": "fundamental", "sub_category": "营运能力",
     "direction": "positive", "formula": "FN(assets_turn)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    # ---- 基础因子: 现金流 ----
    {"factor_id": "FN_OCF_TO_REV", "name": "经营现金流/营收", "category": "fundamental", "sub_category": "现金流",
     "direction": "positive", "formula": "FN(ocf_to_revenue)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_OCF_TO_PROFIT", "name": "经营现金流/净利润", "category": "fundamental", "sub_category": "现金流",
     "direction": "positive", "formula": "FN(ocf_to_profit)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_OCFPS", "name": "每股经营现金流", "category": "fundamental", "sub_category": "现金流",
     "direction": "positive", "formula": "FN(ocfps)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    # ---- 基础因子: 每股/规模 ----
    {"factor_id": "FN_BPS", "name": "每股净资产", "category": "fundamental", "sub_category": "每股指标",
     "direction": "positive", "formula": "FN(bps)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    # ---- 复合因子: 成长(同比派生, 简化为当期值, 后续可扩展fin_YoY函数) ----
    {"factor_id": "FN_REVENUE_YOY", "name": "营收同比增速", "category": "fundamental", "sub_category": "成长",
     "direction": "positive", "formula": "FN(revenue)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_ROE_YOY", "name": "ROE变化", "category": "fundamental", "sub_category": "成长",
     "direction": "positive", "formula": "FN(roe)", "period": "季度",
     "data_source": "财务", "origin": "trade_stock_financial", "is_custom": False},
    # ---- 复合因子: 估值(结合行情) ----
    {"factor_id": "FN_PE", "name": "市盈率(PE)", "category": "fundamental", "sub_category": "估值",
     "direction": "negative", "formula": "Close / FN(eps)", "period": "季度",
     "data_source": "财务+行情", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_PB", "name": "市净率(PB)", "category": "fundamental", "sub_category": "估值",
     "direction": "negative", "formula": "Close / FN(bps)", "period": "季度",
     "data_source": "财务+行情", "origin": "trade_stock_financial", "is_custom": False},
    {"factor_id": "FN_PS", "name": "市销率(PS)", "category": "fundamental", "sub_category": "估值",
     "direction": "negative", "formula": "Close / (FN(revenue) / FN(total_shares))", "period": "季度",
     "data_source": "财务+行情", "origin": "trade_stock_financial", "is_custom": False},
]


# ============================================================
# 因子基类定义 (factor_base)
#   type=periodic: 需指定周期才生效 (收益率/动量等, 剥离周期无意义)
#   type=fixed:    本身即基础因子, 无周期参数 (MACD/RSI/缠论等)
# ============================================================

# 参数化指标基类: 需绑定周期/参数才能生成因子实例
#   type=periodic(需指定周期) / fixed(需指定参数, 如 MACD 12/26)
#   instance_type=composite(该基类的实例是复合因子, 如 rsi_14) / basic(该基类的实例是基础因子, 如 macd_dif)
# 注意: 只有"本身依赖周期/参数才能存在"的才是基类; 独立完整的指标(Talib形态/Barra/缠论/龙头/微观结构/基本面)
#       不是基类, 它们各自本身就是基础因子(base_id=自己), 属于独立的 category 分类。
BASE_FACTORS = [
    # ---- periodic: 需指定周期, 实例均为复合因子 ----
    {"base_id": "returns", "name": "收益率", "type": "periodic", "instance_type": "composite",
     "formula_template": "close.pct_change(period)", "description": "N日收益率, 需指定周期"},
    {"base_id": "momentum", "name": "动量", "type": "periodic", "instance_type": "composite",
     "formula_template": "ROC(close, period)", "description": "N日动量, 需指定周期"},
    {"base_id": "amplitude", "name": "振幅", "type": "periodic", "instance_type": "composite",
     "formula_template": "(high.max(n)-low.min(n))/close.mean(n)", "description": "N日振幅, 需指定周期"},
    {"base_id": "volume_ratio", "name": "量比", "type": "periodic", "instance_type": "composite",
     "formula_template": "volume/volume.rolling(n).mean()", "description": "N日量比, 需指定周期"},
    {"base_id": "volatility", "name": "波动率", "type": "periodic", "instance_type": "composite",
     "formula_template": "returns.rolling(n).std()*sqrt(252)", "description": "N日历史波动率, 需指定周期"},
    {"base_id": "price_volume_corr", "name": "价量相关", "type": "periodic", "instance_type": "composite",
     "formula_template": "close.rolling(n).corr(volume)", "description": "N日价量相关系数, 需指定周期"},
    # ---- periodic: 可调周期指标 (实例为复合因子) ----
    # 注: 原 type=fixed 但 instance_type=composite 且周期可调, 自相矛盾;
    #     已按 3.5 调整为 periodic (周期可调、实例为复合因子, 本质是参数化基类)。
    {"base_id": "rsi", "name": "RSI", "type": "periodic", "instance_type": "composite",
     "formula_template": "RSI(close, period)", "description": "相对强弱指标, 可调周期(如 6/14)"},
    {"base_id": "adx", "name": "ADX", "type": "periodic", "instance_type": "composite",
     "formula_template": "ADX(high,low,close, period)", "description": "趋势强度指标, 可调周期"},
    {"base_id": "cci", "name": "CCI", "type": "periodic", "instance_type": "composite",
     "formula_template": "CCI(close, period)", "description": "顺势指标, 可调周期"},
    {"base_id": "willr", "name": "威廉", "type": "periodic", "instance_type": "composite",
     "formula_template": "WILLR(close, period)", "description": "威廉指标, 可调周期"},
    {"base_id": "atr", "name": "ATR", "type": "periodic", "instance_type": "composite",
     "formula_template": "ATR(period)/Close", "description": "归一化真实波幅, 可调周期"},
    {"base_id": "reversal", "name": "反转", "type": "periodic", "instance_type": "composite",
     "formula_template": "-close.pct_change(period)", "description": "短期反转因子, 可调周期"},
    # ---- fixed 固定参数: 其实例即基础因子 ----
    {"base_id": "macd", "name": "MACD", "type": "fixed", "instance_type": "basic",
     "formula_template": "EMA(12)-EMA(26)", "description": "MACD 指标, 固定参数 12/26"},
    {"base_id": "kdj", "name": "KDJ", "type": "fixed", "instance_type": "basic",
     "formula_template": "KDJ(9,3,3)", "description": "随机指标, 固定参数"},
    {"base_id": "bbands", "name": "布林带", "type": "fixed", "instance_type": "basic",
     "formula_template": "(close-lower)/(upper-lower)", "description": "布林带位置, 固定参数"},
    {"base_id": "bbands_width", "name": "布林带宽度", "type": "fixed", "instance_type": "basic",
     "formula_template": "(upper-lower)/middle", "description": "布林带宽度, 固定参数 (AlphaMaster BOLL_WIDTH 映射)"},
    # ---- periodic: 乖离率/流动性 (实例为复合因子) ----
    # 注: 原 turnover 参数化基类已删除 —— 其实现实为"量比"(Volume/Volume均量),
    #     与 volume_ratio 基类完全重复; 真换手率改由 Turnover 行情字段
    #     作为 fixed 基础因子基类(turnover_rate)承载, 见下方行情字段区。
    {"base_id": "bias", "name": "乖离率", "type": "periodic", "instance_type": "composite",
     "formula_template": "(Close-ts_Mean(Close,{period}))/ts_Mean(Close,{period})",
     "description": "价格偏离均线的比率, 需指定周期"},
    {"base_id": "liquidity", "name": "流动性", "type": "periodic", "instance_type": "composite",
     "formula_template": "Amount.rolling({period}).mean()/(MarketCap)",
     "description": "流动性指标, 需指定周期"},
    # ---- periodic: Talib均线算法 (实例为复合因子) ----
    {"base_id": "sma", "name": "简单移动平均", "type": "periodic", "instance_type": "composite",
     "formula_template": "ts_Mean(Close,{period})", "description": "SMA简单移动平均"},
    {"base_id": "ema", "name": "指数移动平均", "type": "periodic", "instance_type": "composite",
     "formula_template": "EMA(Close,{period})", "description": "EMA指数移动平均"},
    {"base_id": "dema", "name": "双指数移动平均", "type": "periodic", "instance_type": "composite",
     "formula_template": "DEMA(Close,{period})", "description": "DEMA双指数移动平均"},
    {"base_id": "tema", "name": "三指数移动平均", "type": "periodic", "instance_type": "composite",
     "formula_template": "TEMA(Close,{period})", "description": "TEMA三指数移动平均"},
    {"base_id": "wma", "name": "加权移动平均", "type": "periodic", "instance_type": "composite",
     "formula_template": "WMA(Close,{period})", "description": "WMA加权移动平均"},
    {"base_id": "kama", "name": "考夫曼自适应均线", "type": "periodic", "instance_type": "composite",
     "formula_template": "KAMA(Close,{period})", "description": "KAMA考夫曼自适应均线"},
    {"base_id": "mama", "name": "MESA自适应均线", "type": "periodic", "instance_type": "composite",
     "formula_template": "MAMA(Close,{period})", "description": "MAMA自适应均线"},
    {"base_id": "sar", "name": "抛物线SAR", "type": "periodic", "instance_type": "composite",
     "formula_template": "SAR(High,Low,{period})", "description": "抛物线SAR指标"},
    {"base_id": "sar_dist", "name": "SAR距离", "type": "fixed", "instance_type": "basic",
     "formula_template": "(Close-SAR)/Close", "description": "close相对SAR的归一化距离, 固定参数 (AlphaMaster SAR_DIST 映射)"},
    {"base_id": "trima", "name": "三角移动平均", "type": "periodic", "instance_type": "composite",
     "formula_template": "TRIMA(Close,{period})", "description": "TRIMA三角移动平均"},
    # ---- 最基础的价格字段(作为基类, 供WQ等复合因子引用) ----
    # 开盘/最高/最低/收盘价是构造其他因子(尤其WQ量价因子)的最基础单元
    {"base_id": "open", "name": "开盘价", "type": "fixed", "instance_type": "basic",
     "formula_template": "Open", "description": "开盘价, 最基础行情字段"},
    {"base_id": "high", "name": "最高价", "type": "fixed", "instance_type": "basic",
     "formula_template": "High", "description": "最高价, 最基础行情字段"},
    {"base_id": "low", "name": "最低价", "type": "fixed", "instance_type": "basic",
     "formula_template": "Low", "description": "最低价, 最基础行情字段"},
    {"base_id": "close", "name": "收盘价", "type": "fixed", "instance_type": "basic",
     "formula_template": "Close", "description": "收盘价, 最基础行情字段"},
    # ---- 最基础的成交量/成交额/均价字段(作为基类, 供WQ等复合因子引用) ----
    {"base_id": "volume", "name": "成交量", "type": "fixed", "instance_type": "basic",
     "formula_template": "Volume", "description": "成交量, 最基础行情字段"},
    {"base_id": "amount", "name": "成交额", "type": "fixed", "instance_type": "basic",
     "formula_template": "Amount", "description": "成交额, 最基础行情字段"},
    {"base_id": "vwap", "name": "均价VWAP", "type": "fixed", "instance_type": "basic",
     "formula_template": "VWAP", "description": "成交量加权均价, 最基础行情字段"},
    {"base_id": "turnover_rate", "name": "换手率", "type": "fixed", "instance_type": "basic",
     "formula_template": "Turnover", "description": "当日换手率(日K turnover_rate 列), 最基础行情字段"},
    # ---- 派生字段(供清华WQ复杂因子引用, 由引擎在_build_field_dfs中计算) ----
    {"base_id": "value", "name": "规模代理值", "type": "fixed", "instance_type": "basic",
     "formula_template": "Value", "description": "成交额规模代理(派生字段)"},
    {"base_id": "idioret", "name": "特异质收益", "type": "fixed", "instance_type": "basic",
     "formula_template": "IdioRet", "description": "截面去均值日收益率(派生字段)"},
    {"base_id": "totalret", "name": "日收益率", "type": "fixed", "instance_type": "basic",
     "formula_template": "TotalRet", "description": "日收益率面板(清华原版语义, 派生字段)"},
    # ---- periodic: 区间位置 (原固定参数基类, 按 3.4 方案 B 退化为参数化基类) ----
    # 原 price_position 为固定参数基类(formula 硬编码 60 日), 实例是基础因子;
    # 但需承载 20/50/60 日不同周期, 固定参数基类无法换参数, 故退化为参数化基类,
    # 其 20/50/60 日实例均为复合因子 (见 AlphaMaster特征算子与因子库映射方案.md 3.4)。
    {"base_id": "price_position", "name": "区间位置", "type": "periodic", "instance_type": "composite",
     "formula_template": "(Close-ts_Min(Close,{period}))/(ts_Max(Close,{period})-ts_Min(Close,{period}))",
     "description": "价格在N日区间内的位置, 需指定周期"},
    # ---- AlphaMaster 映射补充参数化基类 (见 AlphaMaster特征算子与因子库映射方案.md 3.3.2) ----
    {"base_id": "trend_strength", "name": "趋势强度", "type": "periodic", "instance_type": "composite",
     "formula_template": "SLOPE({period})*R2", "description": "线性回归斜率乘拟合优度, 需指定周期"},
    {"base_id": "gk_vol", "name": "Garman-Klass波动", "type": "periodic", "instance_type": "composite",
     "formula_template": "GK({period})", "description": "Garman-Klass波动率估计量, 需指定周期"},
    {"base_id": "parkinson_vol", "name": "Parkinson波动", "type": "periodic", "instance_type": "composite",
     "formula_template": "PK({period})", "description": "Parkinson波动率估计量, 需指定周期"},
    {"base_id": "yang_zhang_vol", "name": "Yang-Zhang波动", "type": "periodic", "instance_type": "composite",
     "formula_template": "YZ({period})", "description": "Yang-Zhang波动率估计量, 需指定周期"},
    {"base_id": "rs_vol", "name": "Rogers-Satchell波动", "type": "periodic", "instance_type": "composite",
     "formula_template": "RS({period})", "description": "Rogers-Satchell波动率估计量, 需指定周期"},
    {"base_id": "autocorr", "name": "自相关", "type": "periodic", "instance_type": "composite",
     "formula_template": "AC({period})", "description": "收益自相关, 需指定周期"},
    {"base_id": "typical_dev", "name": "典型价偏离", "type": "periodic", "instance_type": "composite",
     "formula_template": "TYPICAL_DEV({period})", "description": "典型价偏离其均线, 需指定周期"},
    {"base_id": "dmi_diff", "name": "DMI差值", "type": "periodic", "instance_type": "composite",
     "formula_template": "DMI_DIFF({period})", "description": "DI+减DI-, 需指定周期"},
    {"base_id": "trix", "name": "TRIX", "type": "periodic", "instance_type": "composite",
     "formula_template": "TRIX({period})", "description": "三重EMA变化率, 需指定周期"},
    {"base_id": "amihud_illiq", "name": "Amihud非流动性", "type": "periodic", "instance_type": "composite",
     "formula_template": "AMIHUD({period})", "description": "Amihud非流动性, 需指定周期"},
    {"base_id": "kyle_lambda", "name": "Kyle lambda", "type": "periodic", "instance_type": "composite",
     "formula_template": "KYLE({period})", "description": "Kyle价格冲击斜率, 需指定周期"},
    {"base_id": "cmf", "name": "Chaikin资金流", "type": "periodic", "instance_type": "composite",
     "formula_template": "CMF({period})", "description": "Chaikin Money Flow, 需指定周期"},
    {"base_id": "ad_line_slope", "name": "A/D线斜率", "type": "periodic", "instance_type": "composite",
     "formula_template": "AD_SLOPE({period})", "description": "A/D线线性回归斜率, 需指定周期"},
    {"base_id": "hurst", "name": "Hurst指数", "type": "periodic", "instance_type": "composite",
     "formula_template": "HURST({period})", "description": "Hurst指数, 需指定周期"},
    {"base_id": "fractal_dim", "name": "分形维", "type": "periodic", "instance_type": "composite",
     "formula_template": "FRACTAL({period})", "description": "分形维, 需指定周期"},
    {"base_id": "ret_entropy", "name": "收益熵", "type": "periodic", "instance_type": "composite",
     "formula_template": "ENTROPY({period})", "description": "收益符号香农熵, 需指定周期"},
    {"base_id": "keltner", "name": "Keltner通道", "type": "periodic", "instance_type": "composite",
     "formula_template": "KELTNER({period})", "description": "Keltner通道位置, 需指定周期"},
    {"base_id": "ichimoku_kijun", "name": "Ichimoku基准线偏离", "type": "periodic", "instance_type": "composite",
     "formula_template": "KIJUN({period})", "description": "close相对Kijun偏离, 需指定周期"},
    {"base_id": "ichimoku_tenkan", "name": "Ichimoku转换线偏离", "type": "periodic", "instance_type": "composite",
     "formula_template": "TENKAN({period})", "description": "close相对Tenkan偏离, 需指定周期"},
    {"base_id": "supertrend", "name": "SuperTrend", "type": "periodic", "instance_type": "composite",
     "formula_template": "SUPERTREND({period})", "description": "SuperTrend方向, 需指定周期"},
]


# ============================================================
# 因子分类: 回填 base_id / factor_type
#   factor_type: basic(基础) / composite(复合) / custom(自定义)
#   说明: 所有因子公式均为"基类+算子"自包含形式(base_id指向基类表中的记录),
#         不再维护 dependencies 字段, 依赖关系由公式中的基类实例自动推导。
# ============================================================

# 财务因子 base_id 映射 (按 category)
FINANCIAL_BASE_BY_CATEGORY = {
    "fundamental": "fundamental",
}

# ============================================================
# 特殊分类映射: 因子ID -> {factor_type, base_id}
#   优先级最高, 用于处理不符合前缀规则的因子
# ============================================================
SPECIAL_CLASSIFY = {
    # --- MOM累计收益动量: 原formula为ts_PctChange(returns), 基类应为returns而非momentum ---
    "MOM_1M": {"factor_type": "composite", "base_id": "returns"},
    "MOM_3M": {"factor_type": "composite", "base_id": "returns"},
    "MOM_6M": {"factor_type": "composite", "base_id": "returns"},
    # --- 乖离率 -> bias基类 (复合因子, formula自包含ts_Bias) ---
    "ma5_bias":  {"factor_type": "composite", "base_id": "bias"},
    "ma10_bias": {"factor_type": "composite", "base_id": "bias"},
    "ma20_bias": {"factor_type": "composite", "base_id": "bias"},
    "ma60_bias": {"factor_type": "composite", "base_id": "bias"},
    "BIAS_20":   {"factor_type": "composite", "base_id": "bias"},

    # --- 量比系列: vol_ratio_* 由 PERIODIC_PREFIX_RULES 自动挂 volume_ratio 基类, 无需特例 ---
    # (原 TURN_20/turnover_ratio/turnover_change_5d 三个旧 ID 已硬删除, 此处不再登记)
    # ---- 真换手率体系 (2026 重构): turnover_rate = fixed 基础因子(行情字段, 不参数化);
    #      turnover_rate_20 = 时间平均派生复合因子 ----
    "turnover_rate":      {"factor_type": "basic", "base_id": "turnover_rate"},
    "turnover_rate_20":   {"factor_type": "composite", "base_id": "turnover_rate"},

    # --- 流动性 -> liquidity基类 (复合因子, formula自包含ts_Log/ts_Mean) ---
    "LIQ_20": {"factor_type": "composite", "base_id": "amount"},

    # --- Talib均线 -> 各自参数化基类 (复合因子, formula自包含ts_SMA等) ---
    "TALIB_SMA":   {"factor_type": "composite", "base_id": "sma"},
    "TALIB_EMA":   {"factor_type": "composite", "base_id": "ema"},
    "TALIB_DEMA":  {"factor_type": "composite", "base_id": "dema"},
    "TALIB_TEMA":  {"factor_type": "composite", "base_id": "tema"},
    "TALIB_WMA":   {"factor_type": "composite", "base_id": "wma"},
    "TALIB_KAMA":  {"factor_type": "composite", "base_id": "kama"},
    "TALIB_MAMA":  {"factor_type": "composite", "base_id": "mama"},
    "TALIB_SAR":   {"factor_type": "composite", "base_id": "sar"},
    "TALIB_TRIMA": {"factor_type": "composite", "base_id": "trima"},

    # --- AlphaMaster 映射补充基础因子 (固定参数基类实例, base_id指向基类表) ---
    "BOLL_WIDTH": {"factor_type": "basic", "base_id": "bbands_width"},
    "SAR_DIST":   {"factor_type": "basic", "base_id": "sar_dist"},

    # --- 财务估值 -> 基础因子 ---
    "FN_PB":          {"factor_type": "basic", "base_id": "FN_PB"},
    "FN_PE":          {"factor_type": "basic", "base_id": "FN_PE"},
    "FN_PS":          {"factor_type": "basic", "base_id": "FN_PS"},
    "FN_REVENUE_YOY": {"factor_type": "basic", "base_id": "FN_REVENUE_YOY"},
    "FN_ROE_YOY":     {"factor_type": "basic", "base_id": "FN_ROE_YOY"},

    # --- 龙头/评分 -> 基础因子 ---
    "obv_slope_10d":{"factor_type": "basic", "base_id": "obv_slope_10d"},

    # --- 多因子组合 -> base_id=所引用基类(逗号分隔, 必须指向factor_base表)
    #   formula 已改写为基类实例形式(如 adx(14)*(rsi(14)-50)/50), 引擎可自展开,
    #   无需 dependencies 字段.
    "ma_bull_score":       {"factor_type": "composite", "base_id": "sma"},
    "adx_rsi_cross":       {"factor_type": "composite", "base_id": "adx,rsi"},
    "macd_adx_cross":      {"factor_type": "composite", "base_id": "macd,adx"},
    "mom_vol_cross":       {"factor_type": "composite", "base_id": "momentum,atr"},
    "rsi_bbands_cross":    {"factor_type": "composite", "base_id": "rsi,bbands"},
    "vol_mom_accel_cross": {"factor_type": "composite", "base_id": "volatility,momentum"},
    "vol_ratio_mom_cross": {"factor_type": "composite", "base_id": "volume_ratio,momentum"},
    # --- 波动变化 -> volatility基类 (复合因子, formula自包含ts_HistVol) ---
    "vol_change_10d":      {"factor_type": "composite", "base_id": "volatility"},
    "vol_change_20d":      {"factor_type": "composite", "base_id": "volatility"},

    # WQ 系列: base_id 严格等于 formula 实际调用的基类实例集合
    # (WQ_IDIO_RET 已删除: 清华原版中 IdioRet 仅是中间变量, 与 idioret() 字段因子等值冗余)
    "WQ_PRICE_VOLUME":    {"factor_type": "composite", "base_id": "close,vwap,high,low"},
    "WQ_VOL_ANOMALY":     {"factor_type": "composite", "base_id": "volume,vwap,high,low"},
    "WQ_MOMENTUM_DECAY":  {"factor_type": "composite", "base_id": "close"},
    "WQ_VOL_PRICE_DECAY": {"factor_type": "composite", "base_id": "close,volume"},

    # --- 清华day1_A 的 WQ 复杂因子 (base_id 与 formula 基类实例严格对齐) ---
    "WQ_IDIO_VOL":        {"factor_type": "composite", "base_id": "idioret,volume"},
    "WQ_IDIO_AMPLITUDE_VOL": {"factor_type": "composite", "base_id": "idioret,high,low,close,volume"},
    "WQ_VWAP_AMPLITUDE":  {"factor_type": "composite", "base_id": "vwap,close,high,low,volume"},
    "WQ_PRICE_AMPLITUDE_MEAN": {"factor_type": "composite", "base_id": "close,vwap,high,low"},
    "WQ_VALUE_DECAY":     {"factor_type": "composite", "base_id": "value,vwap,high,low"},
    "WQ_VOL_DECAY":       {"factor_type": "composite", "base_id": "volume,vwap,high,low"},
    "WQ_HIGH_DECAY":      {"factor_type": "composite", "base_id": "high,vwap,low"},
    "WQ_TOTALRET_DECAY":  {"factor_type": "composite", "base_id": "totalret,vwap,high,low"},
    "WQ_VOL_AMPLITUDE_RATIO": {"factor_type": "composite", "base_id": "volume,high,low"},

    # --- 区间位置 (原固定参数基类, 按 3.4 方案 B 退化为参数化基类) ---
    # price_position 现为参数化基类(periodic), 其 20/50/60 日实例均为复合因子
    "price_position":     {"factor_type": "composite", "base_id": "price_position"},
    "price_position_20":  {"factor_type": "composite", "base_id": "price_position"},
    "price_position_50":  {"factor_type": "composite", "base_id": "price_position"},

    # --- AlphaMaster 映射补充复合因子 (依赖已有基类, 见 AlphaMaster特征算子与因子库映射方案.md 3.3.1) ---
    "EMA_RATIO_12_26": {"factor_type": "composite", "base_id": "ema"},
    "VOL_REGIME":      {"factor_type": "composite", "base_id": "atr"},
    "PRESSURE":        {"factor_type": "composite", "base_id": "open,high,low,close"},
    "VOL_Z":           {"factor_type": "composite", "base_id": "volume_ratio"},
    "VWAP_DEV":        {"factor_type": "composite", "base_id": "close,vwap"},

    # --- AlphaMaster 映射补充参数化基类实例 (复合因子, 见 AlphaMaster特征算子与因子库映射方案.md 3.3.2) ---
    "TREND_STRENGTH_50":   {"factor_type": "composite", "base_id": "trend_strength"},
    "GK_VOL":              {"factor_type": "composite", "base_id": "gk_vol"},
    "PARKINSON_VOL":       {"factor_type": "composite", "base_id": "parkinson_vol"},
    "YANG_ZHANG_VOL":      {"factor_type": "composite", "base_id": "yang_zhang_vol"},
    "RS_VOL":              {"factor_type": "composite", "base_id": "rs_vol"},
    "AC1":                 {"factor_type": "composite", "base_id": "autocorr"},
    "AC2":                 {"factor_type": "composite", "base_id": "autocorr"},
    "TYPICAL_DEV":         {"factor_type": "composite", "base_id": "typical_dev"},
    "DMI_DIFF_14":         {"factor_type": "composite", "base_id": "dmi_diff"},
    "TRIX_15":             {"factor_type": "composite", "base_id": "trix"},
    "TRIX_SIGNAL":         {"factor_type": "composite", "base_id": "trix"},
    "AMIHUD_ILLIQ":        {"factor_type": "composite", "base_id": "amihud_illiq"},
    "KYLE_LAMBDA":         {"factor_type": "composite", "base_id": "kyle_lambda"},
    "CMF_20":              {"factor_type": "composite", "base_id": "cmf"},
    "AD_LINE_SLOPE":       {"factor_type": "composite", "base_id": "ad_line_slope"},
    "HURST_50":            {"factor_type": "composite", "base_id": "hurst"},
    "FRACTAL_DIM_30":      {"factor_type": "composite", "base_id": "fractal_dim"},
    "RET_ENTROPY_20":      {"factor_type": "composite", "base_id": "ret_entropy"},
    "KELTNER_POS_20":      {"factor_type": "composite", "base_id": "keltner"},
    "ICHIMOKU_KIJUN_DEV":  {"factor_type": "composite", "base_id": "ichimoku_kijun"},
    "ICHIMOKU_TENKAN_DEV": {"factor_type": "composite", "base_id": "ichimoku_tenkan"},
    "SUPERTREND_DIR":      {"factor_type": "composite", "base_id": "supertrend"},

    # --- 财务成长 -> 基础因子 (净利润同比是独立完整指标, base_id=自身, 归基础) ---
    "NetProfit_YoY":      {"factor_type": "basic", "base_id": "NetProfit_YoY"},
}

# periodic 基类前缀规则: (前缀, base_id)
PERIODIC_PREFIX_RULES = [
    ("ret_", "returns"),
    ("momentum_", "momentum"),
    ("MOM_", "momentum"),
    ("amplitude_", "amplitude"),
    ("vol_ratio_", "volume_ratio"),
    ("hist_vol_", "volatility"),
    ("VOL_", "volatility"),
    ("price_volume_corr_", "price_volume_corr"),
]

# fixed 基类前缀规则: (前缀, base_id)
FIXED_PREFIX_RULES = [
    ("macd_", "macd"),
    ("rsi_", "rsi"),
    ("RSI_", "rsi"),
    ("kdj_", "kdj"),
    ("adx_", "adx"),
    ("cci_", "cci"),
    ("willr", "willr"),
    ("atr_norm", "atr"),
    ("volatility_grid", "atr"),
    ("bbands", "bbands"),
    ("upper_shadow", "candle_pattern"),
    ("lower_shadow", "candle_pattern"),
    ("body_ratio", "candle_pattern"),
    ("new_high", "candle_pattern"),
    ("new_low", "candle_pattern"),
    ("price_position", "candle_pattern"),
    ("REV_", "reversal"),
    ("CHAN_", "chan"),
    ("BARRA_", "barra"),
    ("DRAGON_", "dragon"),
    ("ROE", "fundamental_q"),
    ("GrossMargin", "fundamental_q"),
    ("NegDebtRatio", "fundamental_q"),
    ("NetProfit_YoY", "fundamental_g"),
    ("PE_RATIO", "fundamental_v"),
    ("ofi_", "microstructure"),
    ("large_ratio", "microstructure"),
    ("cancel_rate", "microstructure"),
    ("interval_cv", "microstructure"),
    ("recovery_speed", "microstructure"),
    ("run_length", "microstructure"),
    ("vol_cv", "microstructure"),
    ("direction_symmetry", "microstructure"),
    ("limit_ratio", "microstructure"),
    ("price_volatility_tick", "microstructure"),
    ("TALIB_MOM", "talib_momentum"),
    ("TALIB_ROC", "talib_momentum"),
    ("TALIB_PPO", "talib_momentum"),
    ("TALIB_STOCH", "talib_momentum"),
    ("TALIB_AROON", "talib_momentum"),
    ("TALIB_MFI", "talib_momentum"),
    ("TALIB_UO", "talib_momentum"),
    ("TALIB_ADXR", "talib_momentum"),
    ("TALIB_NATR", "talib_volatility"),
    ("TALIB_TRANGE", "talib_volatility"),
    ("TALIB_OBV", "talib_volume"),
    ("TALIB_AD", "talib_volume"),
    ("TALIB_AVGPRICE", "talib_price"),
    ("TALIB_MEDPRICE", "talib_price"),
    ("TALIB_TYPPRICE", "talib_price"),
    ("TALIB_WCLPRICE", "talib_price"),
    ("TALIB_BETA", "talib_stat"),
    ("TALIB_CORREL", "talib_stat"),
    ("TALIB_STDDEV", "talib_stat"),
    ("TALIB_VAR", "talib_stat"),
    ("TALIB_LINREG", "talib_stat"),
    ("TALIB_HT_", "talib_cycle"),
    ("CDL_", "talib_pattern"),
]


# 参数化基类集合: 只有这些才是真基类(本身依赖周期/参数才能存在)
#   instance_type=composite -> 该基类的具体实例是复合因子 (如 rsi_14, ret_5d)
#   instance_type=basic    -> 该基类的具体实例是基础因子 (如 macd_dif, kdj_k)
# 注意: candle_pattern/chan/barra/dragon/fundamental/microstructure/talib_* 等不是基类,
#       它们是独立完整指标, 每个具体因子 base_id=自己, 属于独立的 category 分类。
PARA_BASES = {b["base_id"]: b for b in BASE_FACTORS}


# 因子类别(category)中文映射: category 是独立的领域分类, 与基类彻底分离
# 12个分类, 按金融含义划分, 不按来源库(Talib/Barra/CASE)划分
CATEGORY_CN = {
    "price_volume": "量价",
    "momentum": "动量",
    "moving_average": "均线",
    "reversal": "反转",
    "volatility": "波动率",
    "liquidity": "流动性",
    "pattern": "K线形态",
    "fundamental": "基本面",
    "dragon": "龙头",
    "microstructure": "微观结构",
    "chan": "缠论",
    "composite": "复合",
}


# ============================================================
# 评价方式标签回填表 (2026-08-15 路由改造, 详见 docs/因子评价方式适配性审计与路由改造计划.md)
#   evaluation_type: technical / technical_ts / signal / financial / none
#   只回填"需要改变默认路由"的因子; 不列出的因子留空, 由公式规则自动推断
#   (FN(→financial, CDL/ta_cdl→signal, 其余→technical), 与显式回填结果一致。
#   D组34个不可计算因子(dragon/微观结构/缠论/Barra/ML)本期不动, 留空维持现状。
# ============================================================
EVALUATION_TYPE_BACKFILL = {
    # ---- technical_ts: 时序标准化截面评价 (量纲不可比: 价格水平/累积量纲/绝对波动) ----
    # 均线绝对值(9): 截面排序实为高价股vs低价股, 需先对自身历史做滚动分位
    "TALIB_SMA": "technical_ts", "TALIB_EMA": "technical_ts", "TALIB_WMA": "technical_ts",
    "TALIB_DEMA": "technical_ts", "TALIB_TEMA": "technical_ts", "TALIB_KAMA": "technical_ts",
    "TALIB_TRIMA": "technical_ts", "TALIB_MAMA": "technical_ts", "TALIB_SAR": "technical_ts",
    # 价格变换(4): 同为价格水平量纲
    "TALIB_AVGPRICE": "technical_ts", "TALIB_MEDPRICE": "technical_ts",
    "TALIB_TYPPRICE": "technical_ts", "TALIB_WCLPRICE": "technical_ts",
    # 回归价格量纲(3): 回归投影值/截距/R2 为价格量纲或有界绝对量纲, 需时序标准化
    "TALIB_LINREG": "technical_ts", "TALIB_LINREG_INTERCEPT": "technical_ts",
    "TALIB_LINREG_R2": "technical_ts",
    # 累积量纲(2): 随时间单调累积, 截面比较=规模代理
    "TALIB_OBV": "technical_ts", "TALIB_AD": "technical_ts",
    # 绝对波动(2): 价格量纲的绝对波动, 高价股天然大 (NATR是归一化版本)
    "TALIB_STDDEV": "technical_ts", "TALIB_VAR": "technical_ts",

    # ---- signal: 事件信号评价 (二值离散; CDL形态已由公式规则自动覆盖, 此处只列非CDL) ----
    "new_high_20d": "signal",          # 0/1 二值, 看涨事件 (direction=positive)
    "new_low_20d": "signal",           # 0/1 二值, 看跌事件 (direction=negative, 需方向感知)
    "TALIB_HT_TRENDMODE": "signal",    # 0/1 二值, 趋势模式事件
    # ---- 缠论形态信号: 顶/底分型0/1 + 笔方向-1/0/1 (确认日对齐T+1, 无未来函数) ----
    "CHAN_TOP_FRACTAL": "signal",      # 0/1, 方向=negative(顶=看跌形态)
    "CHAN_BOTTOM_FRACTAL": "signal",   # 0/1, 方向=positive(底=看涨形态)
    "CHAN_STROKE": "signal",           # -1/0/+1, 双极性按符号定方向
    # ---- 缠论中枢: 动态修正+绝对价格量纲, 暂缓不纳入 (D组计划 D2) ----
    "CHAN_ZG": "none",
    "CHAN_ZD": "none",

    # ---- none: 构造中间字段, 无独立评价意义 (截面IC=纯规模效应或与已有因子等值) ----
    "open": "none", "high": "none", "low": "none", "close": "none",
    "volume": "none", "amount": "none", "vwap": "none",
    "value": "none", "idioret": "none", "totalret": "none",
    # ---- 微观结构 10 个: 缺tick数据(系统数据层仅日K), 保留但不可评价 (D组计划 D4) ----
    "ofi_abs": "none", "large_ratio": "none", "cancel_rate": "none",
    "interval_cv": "none", "recovery_speed": "none", "run_length": "none",
    "vol_cv": "none", "direction_symmetry": "none", "limit_ratio": "none",
    "price_volatility_tick": "none",
    # 注: turnover_rate 保持 technical (真换手率截面可比)

    # ---- AlphaMaster 映射补充因子 (见 AlphaMaster特征算子与因子库映射方案.md) ----
    # technical_ts: 量纲不可比, 需时序标准化 (绝对波动/流动性/价格量纲/统计量)
    "GK_VOL": "technical_ts", "PARKINSON_VOL": "technical_ts",
    "YANG_ZHANG_VOL": "technical_ts", "RS_VOL": "technical_ts",
    "AMIHUD_ILLIQ": "technical_ts", "KYLE_LAMBDA": "technical_ts",
    "BOLL_WIDTH": "technical_ts", "SAR_DIST": "technical_ts",
    "HURST_50": "technical_ts", "FRACTAL_DIM_30": "technical_ts",
    "RET_ENTROPY_20": "technical_ts",
    # AD_LINE_SLOPE: A/D线为累积量纲(成交量累积), 其斜率底层仍为累积量纲,
    #   不同股票量纲差异大(规模效应), 与 TALIB_AD 同类, 需时序标准化
    "AD_LINE_SLOPE": "technical_ts",
    # ---- AlphaMaster 补充因子: 比率/有界/归一化, 量纲可比, 显式回填 technical ----
    # (此前为 NULL 依赖公式推断, 现显式回填使评价口径与已标记因子统一)
    "EMA_RATIO_12_26": "technical", "VOL_REGIME": "technical",
    "PRESSURE": "technical", "VOL_Z": "technical", "VWAP_DEV": "technical",
    "AC1": "technical", "AC2": "technical", "TYPICAL_DEV": "technical",
    "DMI_DIFF_14": "technical", "TRIX_15": "technical", "TRIX_SIGNAL": "technical",
    "CMF_20": "technical", "KELTNER_POS_20": "technical",
    "ICHIMOKU_KIJUN_DEV": "technical", "ICHIMOKU_TENKAN_DEV": "technical",
    "SUPERTREND_DIR": "technical",
    "price_position": "technical", "price_position_20": "technical",
    "price_position_50": "technical",
}


def backfill_evaluation_types() -> int:
    """回填评价方式标签 (仅在 evaluation_type 为空时写入, 不覆盖用户手工值)"""
    from lib.factor_db import _get_conn
    conn = _get_conn()
    n = 0
    try:
        cur = conn.cursor()
        for fid, etype in EVALUATION_TYPE_BACKFILL.items():
            cur.execute(
                """UPDATE factor_library SET evaluation_type = %s, updated_at = NOW()
                   WHERE factor_id = %s AND (evaluation_type IS NULL OR evaluation_type = '')""",
                (etype, fid))
            n += cur.rowcount
        # CDL 形态系列: 以 CDL_ 开头的因子全部回填为 signal (评价函数按值符号判多空)
        cur.execute(
            """UPDATE factor_library SET evaluation_type = 'signal', updated_at = NOW()
               WHERE factor_id LIKE 'CDL\\_%' AND (evaluation_type IS NULL OR evaluation_type = '')""")
        n += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return n


def _category_cn(cat: str) -> str:
    """将英文 category 映射为中文, 未映射则原样返回"""
    return CATEGORY_CN.get(cat, cat)


def _classify_factor(f: Dict) -> Dict:
    """
    为具体因子回填 base_id / factor_type。
    规则 (基础=独立完整指标, base_id指向基类表中自己的记录; 复合=基类+算子组合或多因子组合):
      0. SPECIAL_CLASSIFY 特殊映射 -> 直接使用预设的 base_id/factor_type
      1. is_custom=True -> custom
      2. periodic 前缀规则(ret_/momentum_/MOM_/amplitude_/vol_ratio_/hist_vol_/VOL_/price_volume_corr_)
         -> composite + base_id=参数化基类 (周期基类的具体实例)
      3. fixed 前缀规则:
         - base_id 是参数化基类:
             instance_type=composite -> composite + base_id=基类 (如 rsi_14)
             instance_type=basic    -> basic + base_id=因子自身 (如 macd_dif, 在基类表中有独立记录)
         - base_id 不是参数化基类(独立指标) -> basic + base_id=自己 (如 CDL_* / BARRA_* / CHAN_*)
      4. 兜底 -> basic, base_id=自己
    """
    fid = f.get("factor_id", "")
    out = {"base_id": None, "factor_type": "basic"}

    # 自定义
    if f.get("is_custom"):
        out["factor_type"] = "custom"
        return out

    # 0. 特殊分类映射 (最高优先级, 覆盖所有不符合前缀规则的复合因子)
    if fid in SPECIAL_CLASSIFY:
        spec = SPECIAL_CLASSIFY[fid]
        out["factor_type"] = spec["factor_type"]
        out["base_id"] = spec.get("base_id")
        return out

    # periodic 前缀 -> 周期基类的具体实例 (复合因子)
    for prefix, base_id in PERIODIC_PREFIX_RULES:
        if fid.startswith(prefix):
            out["base_id"] = base_id
            out["factor_type"] = "composite"
            return out

    # fixed 前缀
    for prefix, base_id in FIXED_PREFIX_RULES:
        if fid.startswith(prefix):
            # 参数化基类: 按 instance_type 决定实例是基础还是复合
            if base_id in PARA_BASES:
                if PARA_BASES[base_id].get("instance_type") == "composite":
                    # instance_type=composite: 实例是复合因子, base_id指向参数化基类 (如 rsi_14)
                    out["base_id"] = base_id
                    out["factor_type"] = "composite"
                else:
                    # instance_type=basic: 实例是基础因子, base_id指向自身在基类表中的记录 (如 macd_dif)
                    out["base_id"] = fid
                    out["factor_type"] = "basic"
            # 独立完整指标: 基础因子, base_id=自己
            else:
                out["base_id"] = fid
                out["factor_type"] = "basic"
            return out

    # 兜底: 独立基础因子, base_id=自己
    out["base_id"] = fid
    out["factor_type"] = "basic"
    return out


def init_bases() -> int:
    """初始化因子基类表"""
    for b in BASE_FACTORS:
        upsert_base(b)
    return len(list_bases())


# ============================================================
# 基类分组回填 (category)
#   供因子构建页"基础因子"面板分类下拉筛选 (2026-08-15)
#   分类规则按 base_id 前缀/白名单映射, 参数化基类按 type/name 归入"技术指标"
# ============================================================
BASE_CATEGORY_RULES = [
    # (匹配类型, 匹配内容, 分类名)
    ("prefix", "CDL_", "K线形态"),
    ("prefix", "BARRA_", "Barra风格"),
    ("prefix", "FN_", "财务"),
    ("prefix", "CHAN_", "缠论"),
    ("prefix", "DRAGON_", "龙头"),
    ("prefix", "TALIB_", "技术指标"),
]
# 白名单: 行情字段 / 派生字段 / 财务 / K线形态 / 微观结构 / 技术指标
BASE_CATEGORY_FIELD = {
    "open": "行情字段", "high": "行情字段", "low": "行情字段", "close": "行情字段",
    "volume": "行情字段", "amount": "行情字段", "vwap": "行情字段", "turnover_rate": "行情字段",
}
BASE_CATEGORY_DERIVED = {
    "value": "派生字段", "idioret": "派生字段", "totalret": "派生字段",
}
BASE_CATEGORY_FINANCIAL = {
    "GrossMargin", "NegDebtRatio", "NetProfit_YoY", "PE_RATIO", "ROE",
}
BASE_CATEGORY_PATTERN = {
    "body_ratio", "upper_shadow_ratio", "lower_shadow_ratio",
    "new_high_20d", "new_low_20d", "price_position", "obv_slope_10d",
}
BASE_CATEGORY_MICRO = {
    "interval_cv", "vol_cv", "price_volatility_tick", "cancel_rate",
    "direction_symmetry", "limit_ratio", "ofi_abs", "large_ratio",
    "recovery_speed", "run_length",
}


def base_category(bid: str) -> str:
    """按 base_id 推断基类分组 (行情字段/技术指标/K线形态/财务/Barra风格/缠论/龙头/微观结构/派生字段)"""
    bid = (bid or "").strip()
    if not bid:
        return "技术指标"
    if bid in BASE_CATEGORY_FIELD:
        return BASE_CATEGORY_FIELD[bid]
    if bid in BASE_CATEGORY_DERIVED:
        return BASE_CATEGORY_DERIVED[bid]
    if bid in BASE_CATEGORY_FINANCIAL:
        return "财务"
    if bid in BASE_CATEGORY_PATTERN:
        return "K线形态"
    if bid in BASE_CATEGORY_MICRO:
        return "微观结构"
    for _kind, prefix, cat in BASE_CATEGORY_RULES:
        if bid.startswith(prefix):
            return cat
    return "技术指标"


def sync_bases() -> Dict[str, int]:
    """
    同步因子基类表(factor_base)到"完整基类集合"。
    基类(鸡肋) = 全部参数化基类(BASE_FACTORS) + 全部基础因子(base_id指向基类表中自己的记录)。
    复合因子若 base_id=None (多因子组合) 则不是基类, 不登记到基类表。
    同步时按 base_id 回填 category 分组, 供构建页基础因子面板分类筛选。
    返回 {"kept": 保留数, "added": 新增数, "removed": 移除伪基类数}。
    """
    # 完整基类集合 = 参数化基类 + 基础因子(在因子表中factor_type=basic, base_id=自身)
    valid = {b["base_id"] for b in BASE_FACTORS}
    self_basic = {}
    for f in list_factors():
        bid = f.get("base_id")
        fid = f["factor_id"]
        # base_id 可能是逗号分隔的多个基类(多因子组合)
        # 只有 base_id 是单个值且等于自身 factor_id 的因子才是基类
        if bid and "," not in bid and bid == fid:
            valid.add(fid)
            self_basic[fid] = f
        # 多基类的复合因子(逗号分隔)的各个基类已在参数化基类或基础因子基类中

    # upsert 参数化基类
    for b in BASE_FACTORS:
        b = dict(b)
        b.setdefault("category", base_category(b["base_id"]))
        upsert_base(b)

    added = 0
    removed = 0
    conn = _get_conn()
    try:
        cur = conn.cursor()
        # upsert 自引用因子基类 (基础因子或复合因子, 只要 base_id=自身 就是基类)
        for bid, f in self_basic.items():
            inst = "basic" if f.get("factor_type") == "basic" else "composite"
            cur.execute("SELECT 1 FROM factor_base WHERE base_id=%s", (bid,))
            if cur.fetchone():
                # 已存在则更新 instance_type + category + formula_template(随因子公式刷新,
                # 幂等; 修复 CDL_HIGHWAVE 等历史公式映射错误)
                cur.execute(
                    "UPDATE factor_base SET name=%s, instance_type=%s, category=%s, "
                    "formula_template=%s WHERE base_id=%s",
                    (f.get("name") or bid, inst, base_category(bid), f.get("formula") or "", bid),
                )
                continue
            cur.execute(
                "INSERT INTO factor_base (base_id, name, type, instance_type, formula_template, description, category) "
                "VALUES (%s, %s, 'fixed', %s, %s, %s, %s) ON CONFLICT (base_id) DO NOTHING",
                (bid, f.get("name") or bid, inst, f.get("formula") or "",
                 f.get("category") or "", base_category(bid)),
            )
            added += 1
        # 对已有但缺 category 的基类兜底回填 (防止历史数据无分组)
        cur.execute(
            "UPDATE factor_base SET category=%s "
            "WHERE category IS NULL OR category = ''",
            ("技术指标",),
        )
        # 删除不在完整集合中的残留伪基类(旧分类伪基类)
        for b in list_bases():
            if b["base_id"] not in valid:
                cur.execute("DELETE FROM factor_base WHERE base_id=%s", (b["base_id"],))
                removed += 1
        conn.commit()
    finally:
        conn.close()

    return {"kept": len(valid), "added": added, "removed": removed}


def backfill_factor_types() -> int:
    """
    回填已导入因子的 base_id / factor_type / category(中文) (幂等)。
    返回更新的因子数量。
    """
    count = 0
    for f in BASIC_FACTORS + FINANCIAL_FACTORS:
        meta = _classify_factor(f)
        original = dict(f)
        original["base_id"] = meta["base_id"]
        original["factor_type"] = meta["factor_type"]
        original["category"] = _category_cn(f.get("category", ""))
        upsert_factor(original)
        count += 1
    return count


def run_init():
    """初始化因子库: 建表 + 导入因子 + 初始化基类 + 回填因子类型"""
    print("[factor_init] 创建数据库表...")
    init_tables()

    print(f"[factor_init] 导入 {len(BASIC_FACTORS)} 个基础因子...")
    for factor in BASIC_FACTORS:
        upsert_factor(factor)

    print(f"[factor_init] 导入 {len(FINANCIAL_FACTORS)} 个财务因子...")
    for factor in FINANCIAL_FACTORS:
        upsert_factor(factor)

    # 硬删除已被新 ID 取代的旧版量比命名因子 (无因子包引用、因子库公式自包含不互引,
    # 用户确认无需保留; factor_metrics 随 FK 级联删除)
    # WQ_IDIO_RET: 冗余因子(清华原版 IdioRet 仅是中间变量, 与 idioret() 等值), 用户确认删除
    # D3 下架: 龙头6个(冗余/策略层/量纲问题) + ML_PROB/SVD_HIDDEN(不适合作为固定因子)
    #   详情见 docs/因子库D组文字化因子处理计划.md; factor_eval_result 历史快照成孤儿(无害)
    # 2026-08-15 审计收尾追加删除(DB残留, 均不在定义清单):
    #   TEST_CUSTOM_001(测试残留) / macd_signal_grid(金叉死叉信号, 非数值因子)
    #   returns_20/returns_30(旧 pandas 风格公式, 未登记) / CHAN_BUY1/2/3、CHAN_SELL3(缠论买卖点, 交易信号)
    # 2026-08-15 审计-重复因子删除(定义已从清单移除, 此处清理DB记录):
    #   volatility_grid(=atr(14), 重复atr_norm_14) / PE_RATIO(=Close/FN(eps), 重复FN_PE)
    #   TALIB_STOCH(=ts_KDJ_K(9,3), 重复kdj_k) / CDL_RISINGFALLING3(=ta_CDLRISEFALL3METHODS, 重复CDL_RISEFALL3METHODS)
    _LEGACY_REMOVED_FACTOR_IDS = [
        "TURN_20", "turnover_ratio", "turnover_change_5d", "WQ_IDIO_RET",
        "DRAGON_VOL_RATIO", "DRAGON_MCAP", "DRAGON_RANK", "DRAGON_PRICE",
        "DRAGON_SECTOR", "DRAGON_SCORE", "ML_PROB", "SVD_HIDDEN",
        "TEST_CUSTOM_001", "macd_signal_grid", "returns_20", "returns_30",
        "CHAN_BUY1", "CHAN_BUY2", "CHAN_BUY3", "CHAN_SELL3",
        "volatility_grid", "PE_RATIO", "TALIB_STOCH", "CDL_RISINGFALLING3",
    ]
    n_removed = 0
    for fid in _LEGACY_REMOVED_FACTOR_IDS:
        try:
            if hard_delete_factor(fid):
                n_removed += 1
        except Exception:
            pass
    print(f"[factor_init] 硬删除旧版量比命名因子: {n_removed} 个")

    # 初始化因子基类 + 回填 base_id/factor_type + 同步完整基类集合
    n_bases = init_bases()
    print(f"[factor_init] 初始化参数化基类: {n_bases} 个")

    n_backfilled = backfill_factor_types()
    print(f"[factor_init] 回填因子类型: {n_backfilled} 个")

    n_eval = backfill_evaluation_types()
    print(f"[factor_init] 回填评价方式标签: {n_eval} 个")

    sync = sync_bases()
    print(f"[factor_init] 同步完整基类集合: 保留 {sync['kept']} 个, "
          f"新增基础因子基类 {sync['added']} 个, 移除伪基类 {sync['removed']} 个")

    existing = list_factors()
    print(f"[factor_init] 完成! 因子库现有 {len(existing)} 个因子")

    # 按分类统计
    from collections import Counter
    cat_counts = Counter(f.get("category", "") for f in existing)
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat}: {count} 个")

    # 按因子类型统计
    type_counts = Counter(f.get("factor_type", "basic") for f in existing)
    print(f"[factor_init] 因子类型分布: " + ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items())))

    return len(existing)
