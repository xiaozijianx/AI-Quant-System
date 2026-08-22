# -*- coding: utf-8 -*-
"""概念轮动指标中文注释.

用于概念轮动页面右侧明细面板, 对每个指标给出简短解释。
"""

INDICATOR_NOTES = {
    "concept_code": {
        "name": "概念编码",
        "note": "概念唯一编码, 用于标识同名概念的不同来源。",
    },
    "concept_name": {
        "name": "概念名称",
        "note": "概念显示名称。",
    },
    "source_prefix": {
        "name": "来源前缀",
        "note": "概念来源前缀(TGN/TDGN/GN), 用于区分同名概念。",
    },
    "score": {
        "name": "强度得分",
        "note": "MOM_10_z、RS_20_z、VOL_RATIO_z 三因子加权合成。数值越高表示概念近期动能越强。",
    },
    "composite_score": {
        "name": "综合得分",
        "note": "强度得分加上 phase 阶段加分。用于综合排名, 反映概念当前所处周期位置。",
    },
    "phase": {
        "name": "轮动象限",
        "note": "基于速度和加速度投票判定: 主升加速、高位钝化、主跌、左侧抄底、中性。",
    },
    "MOM_10": {
        "name": "10日动量",
        "note": "概念指数过去 10 个交易日收益率, 衡量短期趋势强度。",
    },
    "MOM_10_z": {
        "name": "10日动量 Z-score",
        "note": "10日动量经标准化后的分值, 便于横向比较。",
    },
    "RS_20": {
        "name": "20日相对强度",
        "note": "概念指数相对全市场概念等权基准的 20 日超额收益, 衡量概念相对大盘的强势程度。",
    },
    "RS_20_z": {
        "name": "20日相对强度 Z-score",
        "note": "20日相对强度经标准化后的分值。",
    },
    "VOL_RATIO": {
        "name": "成交量比率",
        "note": "概念近期成交额相对 20 日均额的比值, 衡量资金关注度。",
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
        "note": "当前概念包含的成分股数量。",
    },
}


def get_note(field: str) -> dict:
    """获取指标注释, 找不到则返回原字段名和空注释."""
    return INDICATOR_NOTES.get(field, {"name": field, "note": ""})
