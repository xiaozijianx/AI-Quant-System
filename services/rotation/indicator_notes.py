# -*- coding: utf-8 -*-
"""轮动指标中文注释 (板块/概念共用).

合并自 sector_rotation/indicator_notes.py 与 concept_rotation/indicator_notes.py。
公共指标文案一字不差; 维度差异 (指标键名/窗口/文案) 按维度生成。
"""

# 公共指标注释 (两侧原样一致的部分)
_COMMON_NOTES = {
    "composite_score": {
        "name": "综合得分",
        "note": "强度得分加上 phase 阶段加分。用于综合排名, 反映{label}当前所处周期位置。",
    },
    "phase": {
        "name": "轮动象限",
        "note": "基于速度和加速度投票判定: 主升加速、高位钝化、主跌、左侧抄底、中性。",
    },
    "VOL_RATIO": {
        "name": "成交量比率",
        "note": "{label}近期成交{vol_word}相对 {vol_long} 日均{vol_word}的比值, 衡量资金关注度。",
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
        "note": "当前{label}包含的成分股数量。",
    },
}


def _build_notes(dim) -> dict:
    """按维度生成完整注释字典 (文案模板中的占位符按维度填充)."""
    label = dim.label
    notes = {}

    # score (合成方式文案两侧不同: 等权 vs 加权)
    if dim.score_equal_weight:
        score_note = (f"MOM_{dim.mom_window}_z、RS_{dim.rs_window}_z、VOL_RATIO_z 三因子等权合成。"
                      f"数值越高表示{label}近期动能越强。")
    else:
        score_note = (f"MOM_{dim.mom_window}_z、RS_{dim.rs_window}_z、VOL_RATIO_z 三因子加权合成。"
                      f"数值越高表示{label}近期动能越强。")
    notes["score"] = {"name": "强度得分", "note": score_note}

    # 公共模板填充
    vol_word = "量" if dim.key == "sector" else "额"
    for k, v in _COMMON_NOTES.items():
        notes[k] = {
            "name": v["name"],
            "note": v["note"].format(label=label, vol_word=vol_word, vol_long=dim.vol_long),
        }

    # MOM (窗口/文案两侧不同)
    mom_name = f"{dim.mom_window}日动量"
    notes[f"MOM_{dim.mom_window}"] = {
        "name": mom_name,
        "note": f"{label}指数过去 {dim.mom_window} 个交易日收益率, 衡量短期趋势强度。",
    }
    mom_z_note = (f"{dim.mom_window}日动量经行业中性化并标准化后的分值, 便于横向比较。"
                  if dim.key == "sector" else
                  f"{dim.mom_window}日动量经标准化后的分值, 便于横向比较。")
    notes[f"MOM_{dim.mom_window}_z"] = {"name": f"{mom_name} Z-score", "note": mom_z_note}

    # RS (窗口/基准口径两侧不同)
    rs_name = f"{dim.rs_window}日相对强度"
    rs_note = (f"{label}指数相对沪深全 A 的 {dim.rs_window} 日超额收益, 衡量{label}相对大盘的强势程度。"
               if dim.key == "sector" else
               f"{label}指数相对全市场概念等权基准的 {dim.rs_window} 日超额收益, 衡量{label}相对大盘的强势程度。")
    notes[f"RS_{dim.rs_window}"] = {"name": rs_name, "note": rs_note}
    notes[f"RS_{dim.rs_window}_z"] = {
        "name": f"{rs_name} Z-score",
        "note": f"{rs_name}经标准化后的分值。",
    }

    # 概念特有三字段
    if dim.has_concept_meta:
        notes["concept_code"] = {
            "name": "概念编码",
            "note": "概念唯一编码, 用于标识同名概念的不同来源。",
        }
        notes["concept_name"] = {
            "name": "概念名称",
            "note": "概念显示名称。",
        }
        notes["source_prefix"] = {
            "name": "来源前缀",
            "note": "概念来源前缀(TGN/TDGN/GN), 用于区分同名概念。",
        }

    return notes


from .dimension import SECTOR, CONCEPT  # noqa: E402

# 维度实例注释表 (sector 版键集 = 原 sector_rotation.indicator_notes.INDICATOR_NOTES;
#                 concept 版键集 = 原 concept_rotation.indicator_notes.INDICATOR_NOTES)
INDICATOR_NOTES_SECTOR = _build_notes(SECTOR)
INDICATOR_NOTES_CONCEPT = _build_notes(CONCEPT)

# 兼容导出: 各维度的 get_note (旧包 sector_rotation/concept_rotation 的对外形态)
def get_note_sector(field: str) -> dict:
    """获取指标注释 (板块), 找不到则返回原字段名和空注释."""
    return INDICATOR_NOTES_SECTOR.get(field, {"name": field, "note": ""})


def get_note_concept(field: str) -> dict:
    """获取指标注释 (概念), 找不到则返回原字段名和空注释."""
    return INDICATOR_NOTES_CONCEPT.get(field, {"name": field, "note": ""})
