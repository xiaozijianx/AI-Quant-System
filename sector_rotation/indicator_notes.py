# -*- coding: utf-8 -*-
"""板块轮动指标中文注释.

用于板块轮动页面右侧明细面板, 对每个指标给出简短解释。
"""

INDICATOR_NOTES = {
    "score": {
        "name": "强度得分",
        "note": "MOM_21_z、RS_60_z、VOL_RATIO_z 三因子等权合成。数值越高表示板块近期动能越强。",
    },
    "composite_score": {
        "name": "综合得分",
        "note": "强度得分加上 phase 阶段加分。用于综合排名, 反映板块当前所处周期位置。",
    },
    "phase": {
        "name": "轮动象限",
        "note": "基于速度和加速度投票判定: 主升加速、高位钝化、主跌、左侧抄底、中性。",
    },
    "MOM_21": {
        "name": "21日动量",
        "note": "板块指数过去 21 个交易日收益率, 衡量短期趋势强度。",
    },
    "MOM_21_z": {
        "name": "21日动量 Z-score",
        "note": "21日动量经行业中性化并标准化后的分值, 便于横向比较。",
    },
    "RS_60": {
        "name": "60日相对强度",
        "note": "板块指数相对沪深全 A 的 60 日超额收益, 衡量板块相对大盘的强势程度。",
    },
    "RS_60_z": {
        "name": "60日相对强度 Z-score",
        "note": "60日相对强度经标准化后的分值。",
    },
    "VOL_RATIO": {
        "name": "成交量比率",
        "note": "板块近期成交量相对 60 日均量的比值, 衡量资金关注度。",
    },
    "VOL_RATIO_z": {
        "name": "成交量比率 Z-score",
        "note": "成交量比率经标准化后的分值。",
    },
    "ROC_20": {
        "name": "20日变化率",
        "note": "(close_t - close_t-20) / close_t-20 * 100, 一阶导速度类指标。",
    },
    "MA20_SLOPE": {
        "name": "MA20 斜率",
        "note": "对 MA20 做 10 日最小二乘线性回归, 斜率年化为 %/年。反映中期趋势速度。",
    },
    "MA20_ACCEL": {
        "name": "MA20 加速度",
        "note": "当前 MA20 斜率与 5 日前斜率之差, 反映趋势加速度。",
    },
    "MACD_HIST": {
        "name": "MACD 柱状值",
        "note": "DIF - DEA, 速度差的变化, 二阶导代理指标。",
    },
    "HIST_DELTA": {
        "name": "MACD 柱变化",
        "note": "当日 MACD 柱状值相对上一日变化, 判断加速或减速。",
    },
    "member_count": {
        "name": "成分股数",
        "note": "当前板块包含的成分股数量。",
    },
}


def get_note(field: str) -> dict:
    """获取指标注释, 找不到则返回原字段名和空注释."""
    return INDICATOR_NOTES.get(field, {"name": field, "note": ""})
