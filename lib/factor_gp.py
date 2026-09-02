# -*- coding: utf-8 -*-
# GP 遗传规划自动因子挖掘内核
"""
以 QuantGplearn(gplearn 家族)的进化循环为骨架, 自写轻量 GP 内核:
    - 搜索空间: L0 受限子集 (8 字段 + 6 常数 + 4 二元算术 + 1 一元 abs + 16 时序 + 4 截面)
    - 表达式 = 树: 终端集(字段/常数) + 函数集(算术/时序/截面), 复用因子构建 DSL 语义
    - 适应度: 复用 evaluate_expression + run_ic_timeseries_panel 的 RankIC (训练段)
    - 进化: 锦标赛选择 + 子树交叉 + 点变异/子树变异/Hoist变异 + 精英保留 + 早停
    - OOS: 训练段进化, 收尾对 Top-N 在测试段复核 (报告训练/测试 IC 对比)
    - Warm-Start: 库内因子 formula 注入初始种群 (默认 30%)

设计依据: docs/因子挖掘页面设计方案.md 4.6.1~4.6.4
参照代码: third_party/QuantGplearn/genetic.py (进化循环结构), _program.py (树表示/交叉变异)
不引入 gplearn/sklearn 依赖: 表达式生成与适应度完全复用现有因子引擎。
"""

from __future__ import annotations
import hashlib
import random
import re
import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from lib.factor_screening import (
    split_train_test_dates, trim_panel_to_dates,
    oos_recheck, walk_forward_recheck,
    permutation_significance, dedup_by_corr,
)
from lib.factor_engine import (
    validate_expression, evaluate_expression, run_ic_timeseries_panel,
    BASE_OPERATOR_MAP,
)

# ============================================================
# 一、搜索空间 (L0 受限子集, 前端可按算子层级开关切换)
# ============================================================
# 基础字段 (终端) + 派生字段 (IdioRet/Value/TotalRet 为引擎 _SAFE_FIELDS 内置,
# 2026-08-16 测试发现 L0 无派生字段导致搜索空间薄, 故纳入以增加表达式深度)
GP_FIELDS: List[str] = [
    "Open", "High", "Low", "Close", "Volume", "Amount", "VWAP", "Turnover",
    "IdioRet", "Value", "TotalRet",
]
# 常数 (终端)
GP_CONSTANTS: List[int] = [0, 1, 2, 3, 5, 10]
# 二元算术算子 (函数)
GP_ARITH_BINARY: List[str] = ["add", "sub", "mul", "div"]
# 一元算术算子 (函数)
GP_ARITH_UNARY: List[str] = ["abs",
    # AlphaMaster 映射补充一元算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1)
    "sign", "jump", "max3", "power", "signed_log", "sqrt",
    "clip", "sigmoid", "tanh_squash", "winsorize",
]
# 单参带窗时序算子 (函数, 需窗口参数)
GP_TS_OPS: List[str] = [
    "ts_Delay", "ts_Mean", "ts_Decay", "ts_Max", "ts_Min", "ts_Delta",
    "ts_Stdev", "ts_Sum", "ts_Median", "ts_PctChange", "ts_ROC",
    "ts_Bias", "ts_VolRatio", "ts_HistVol", "ts_Rank",
    "ts_Skewness", "ts_Kurtosis",
    # 阶段5.1.1 补充 (审计: 因子库用到, 引擎/GPU 均已实现, 补齐搜索空间)
    "ts_MOM", "ts_RESVOL",
    # AlphaMaster 映射补充带窗时序算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1)
    "ts_ArgMax", "ts_ArgMin", "ts_Product", "ts_DecayLinear",
]
# 单参无窗时序算子 (函数)
GP_TS_RAW: List[str] = ["ts_Log", "ts_Identity",
    # AlphaMaster 映射补充无窗时序算子 (见 AlphaMaster特征算子与因子库映射方案.md 3.1)
    "ts_Scale",
]
# 截面算子 (函数)
GP_CS_OPS: List[str] = ["cs_Rank", "cs_Demean", "cs_Zscore", "cs_TransNorm"]
# 窗口参数域 (离散化, 压缩搜索空间)
WINDOW_POOL: List[int] = [3, 5, 10, 20, 60, 120, 250]

# 算子层级包 (L0 首版默认; L1/L2 供前端开关扩展)
SPACE_L0: Dict[str, List] = {
    "fields": GP_FIELDS,
    "constants": GP_CONSTANTS,
    "arith_binary": GP_ARITH_BINARY,
    "arith_unary": GP_ARITH_UNARY,
    "ts": GP_TS_OPS,
    "ts_raw": GP_TS_RAW,
    "cs": GP_CS_OPS,
}

# L1 扩展: 新时序算子 (阶段3.4) —— 引擎单字段带窗函数, 库内无对应基类, 作"算子"吃子树+窗口
# 注: ts_RSI/ts_SMA/ts_EMA/ts_WMA/ts_MOM 已在 L2 以"参数化基类叶子"承载(绑定 Close),
#     不再作算子形态 (2026-08-16 对齐因子库"基类=指标类型模板"语义, 去重收敛)。
GP_TS_OPS_L1: List[str] = [
    "ts_DecayExp", "ts_CumReturn", "ts_Shift", "ts_Count", "ts_VAR",
    "ts_LINEARREG", "ts_LINEARREG_SLOPE", "ts_LINEARREG_ANGLE",
    "ts_LINEARREG_INTERCEPT", "ts_LINEARREG_R2",
]
SPACE_L1: Dict[str, List] = {
    **SPACE_L0,
    "ts": GP_TS_OPS + GP_TS_OPS_L1,
}

# L2 固定参数技术指标算子: 已全部改由"固定参数基类叶子"(GP_BASE_LEAF)承载 (2026-08-16 收敛),
# 不再以算子形态出现; 保留空列表与 T_TS_FIXED 节点类型定义以兼容现有代码路径。
GP_TS_FIXED: List[str] = []

# L2 基类叶子 (仅技术类, 财务/信号类不入): 基类=指标类型模板, 内部绑定所需字段
# (如 adx/amplitude/sar 绑定 High/Low/Close), 作"叶子"嵌入树, GP 不注入子树;
# 分两类 (对齐 factor_base 语义, 见 docs/因子基础_复合分类盘点.md):
#   - 参数化基类 (周期是参数, 值->窗口参数池): rsi/sma/ema/wma/momentum/volume_ratio/volatility/bias/
#     dema/tema/kama/trima/amplitude/price_volume_corr/reversal/returns
#   - 固定参数基类 (参数固定=标准参数, 实例即基础因子, None=用引擎默认): adx/cci/willr/atr/macd/kdj/bbands/mama/sar
#     注: mama(引擎 fast/slow) 与 sar(引擎 step/max_step) 非周期参数, 按固定参数处理。
# 未纳入(暂不处理): 形态类(CDL_*)、Barra/缠论/微观结构/龙头分、财务类 —— 依赖特殊数据源, GP 行情面板算不出, 且违反类型隔离。
GP_BASE_LEAF: Dict[str, Optional[List[int]]] = {
    # 参数化基类: 周期可调, 换周期仍是同一指标 (归并规则见因子基础_复合分类盘点.md 一·五)
    "rsi": [6, 14, 21],
    "sma": [5, 10, 20, 60],
    "ema": [5, 10, 20, 60],
    "wma": [5, 10, 20, 60],
    "momentum": [5, 10, 20],
    "volume_ratio": [5, 10, 20],
    "volatility": [10, 20, 60],
    "bias": [10, 20, 60],
    "dema": [5, 10, 20, 60],
    "tema": [5, 10, 20, 60],
    "kama": [5, 10, 20, 60],
    "trima": [5, 10, 20, 60],
    "amplitude": [5, 10, 20],
    "price_volume_corr": [10, 20, 60],
    "reversal": [5, 10, 20],
    "returns": [3, 5, 10, 20],
    # 因子侧 3.2: AlphaMaster 补充技术类参数化基类 (能挪进来的挪进来, 面板可算可 GPU 化;
    # 对应 t_ts_* 已实现并注册 TORCH_TS)
    "autocorr": [10, 20, 60],
    "typical_dev": [10, 20, 60],
    "dmi_diff": [10, 14, 21],
    "trix": [10, 15, 20],
    "amihud_illiq": [10, 20, 60],
    "kyle_lambda": [10, 20, 60],
    "cmf": [10, 20, 60],
    "ad_line_slope": [10, 20, 60],
    "price_position": [20, 50, 60],
    # 因子侧 3.2 续: 补充库内已存在、引擎/GPU 均实现的复杂估计类参数化基类
    # (此前因"复杂估计/多字段强耦合"暂不入搜索空间, 但 warm 注入审计确认它们已能
    # GPU 化并被注入, 导致搜索空间与计算空间不统一; 现统一补入, 窗口池对齐库内实例参数)
    "trend_strength": [20, 50, 60],
    "hurst": [20, 50, 60],
    "fractal_dim": [20, 50, 60],
    "ret_entropy": [10, 20, 60],
    "keltner": [10, 20, 60],
    "ichimoku_kijun": [9, 26, 52],
    "ichimoku_tenkan": [9, 26, 52],
    "supertrend": [10, 14, 20],
    "gk_vol": [10, 20, 60],
    "parkinson_vol": [10, 20, 60],
    "yang_zhang_vol": [10, 20, 60],
    "rs_vol": [10, 20, 60],
    # 固定参数基类 (标准参数, 参数变了语义就变味; 无窗, 实例化时用引擎默认参数)
    "adx": None,
    "cci": None,
    "willr": None,
    "atr": None,
    "macd": None,
    "kdj": None,
    "bbands": None,
    "mama": None,
    "sar": None,
    "bbands_width": None,
    "sar_dist": None,
    # ---- TALIB 族具体技术基础因子 (固定参数基类叶子, None=用引擎默认标准参数) ----
    # 引擎已注册 BASE_OPERATOR_MAP (见 factor_engine.py), 实例即基础因子;
    # 已去重: TALIB_SMA/EMA/WMA/DEMA/TEMA/KAMA/TRIMA/MAMA/SAR/MOM/ROC/STDDEV/VAR/
    #        LINREG* 与现有基类(参数化)或时序算子重复, 不入; 以下 22 个均不与现有重复。
    "TALIB_MFI": None,
    "TALIB_OBV": None,
    "TALIB_AD": None,
    "TALIB_ADOSC": None,
    "TALIB_NATR": None,
    "TALIB_TRANGE": None,
    "TALIB_STOCHF": None,
    "TALIB_STOCHRSI": None,
    "TALIB_AROON": None,
    "TALIB_AROONOSC": None,
    "TALIB_ADXR": None,
    "TALIB_UO": None,
    "TALIB_AVGPRICE": None,
    "TALIB_MEDPRICE": None,
    "TALIB_TYPPRICE": None,
    "TALIB_WCLPRICE": None,
    "TALIB_HT_DCPERIOD": None,
    "TALIB_HT_DCPHASE": None,
    "TALIB_HT_TRENDMODE": None,
    "TALIB_PPO": None,
    "TALIB_BETA": None,
    "TALIB_CORREL": None,
}

SPACE_L2: Dict[str, Any] = {
    **SPACE_L1,
    "ts_fixed": GP_TS_FIXED,
    "base_leaf": GP_BASE_LEAF,
}

# 空间选择 (默认 L0; L1 追加新时序算子; L2 追加基类叶子(参数化基类+固定参数基类))
SPACE_LEVELS: Dict[str, Dict[str, Any]] = {"L0": SPACE_L0, "L1": SPACE_L1, "L2": SPACE_L2}

# 搜索空间单参带窗时序算子全集 (跨全部层级; formula_to_tree 解析校验用:
# 统一"搜索空间"与"计算空间(引擎/GPU)", 非搜索空间算子不得解析为可打散的 ts 节点,
# 只允许折叠为 L2 基类叶子(原子)或剔除)
_TS_OPS_IN_SPACE: set = set(GP_TS_OPS + GP_TS_OPS_L1)

# 节点类型常量
T_FIELD = "field"
T_CONST = "const"
T_OP = "op"        # 算术 (二元/一元)
T_TS = "ts"        # 时序 (带窗)
T_TS_RAW = "ts_raw"  # 时序 (无窗)
T_TS_FIXED = "ts_fixed"  # 时序 (固定参数, L2; 只渲染函数名, 参数用引擎默认值; 当前未启用)
T_BASE_LEAF = "base_leaf"  # 基类叶子 (L2; 参数化基类带自身窗口参数 / 固定参数基类无参)
T_CS = "cs"        # 截面
T_TS_MULTI = "ts_multi"  # 多参带窗时序算子 (双字段+窗口, 如 ts_Corr(A,B,N); GPU 可编译)
T_TS_PARAMS = "ts_params"  # 多定参时序算子 (字段/子表达式 + 尾部多个定参, 如 ts_MACD_HIST(A,12,26,9);
                          # 阶段 P0 收尾新增, GPU 可编译)


# ============================================================
# 二、表达式树: 生成 / 转字符串 / 深度 / 去重
# ============================================================
# 节点表示 (dict):
#   {'t': 'field', 'name': 'Close'}
#   {'t': 'const', 'val': 5}
#   {'t': 'op', 'name': 'add'|'sub'|'mul'|'div', 'args': [left, right]}
#   {'t': 'op', 'name': 'abs', 'args': [child]}
#   {'t': 'ts', 'name': 'ts_Mean', 'arg': child, 'window': n}
#   {'t': 'ts_raw', 'name': 'ts_Log', 'arg': child}
#   {'t': 'ts_fixed', 'name': 'ts_MACD_DIF', 'arg': child}   (固定参数算子, 当前未启用: 基类已改走 base_leaf)
#   {'t': 'base_leaf', 'name': 'rsi', 'params': [14]}        (基类叶子: 参数化基类带自身窗口参数 / 固定参数基类无参)
#   {'t': 'cs', 'name': 'cs_Rank', 'arg': child}

ARITH_BINARY_SET = set(GP_ARITH_BINARY)


def _terminal(rng: random.Random, space: Dict[str, List]) -> Dict:
    """随机生成一个终端节点 (字段 或 常数, L2 时含参数化基类叶子)"""
    if space.get("base_leaf") and rng.random() < 0.2:
        return _base_leaf(rng, space)
    if rng.random() < 0.8:
        return {"t": T_FIELD, "name": rng.choice(space["fields"])}
    return {"t": T_CONST, "val": rng.choice(space["constants"])}


def _base_leaf(rng: random.Random, space: Dict[str, List]) -> Dict:
    """生成一个参数化基类叶子节点 (L2)

    base_leaf 是自包含的: 基类内部已绑定所需字段(如 adx 用 High/Low/Close),
    因此作为"叶子"嵌入树, 只携带自身窗口参数(或固定参数 None)。
    """
    name = rng.choice(list(space["base_leaf"].keys()))
    pool = space["base_leaf"][name]
    params = [rng.choice(pool)] if pool else []
    return {"t": T_BASE_LEAF, "name": name, "params": params}


def _grow_arg(rng: random.Random, space: Dict[str, List], max_depth: int) -> Dict:
    """生成函数节点的子节点: 只允许 字段 或 算子结果, 禁止纯常数
    (否则 ts_VolRatio(2,250) 这类常数入算子会 AttributeError)"""
    if max_depth <= 0:
        if space.get("base_leaf") and rng.random() < 0.2:
            return _base_leaf(rng, space)
        return {"t": T_FIELD, "name": rng.choice(space["fields"])}
    if max_depth >= 2 and rng.random() < 0.35:
        if space.get("base_leaf") and rng.random() < 0.25:
            return _base_leaf(rng, space)
        return {"t": T_FIELD, "name": rng.choice(space["fields"])}
    # max_depth==1: 再递归会到 _function_node(0) 落到常数终端,
    # 这里直接给字段/基类叶子, 保证算子子节点必为字段/算子结果而非常数
    if max_depth <= 1:
        if space.get("base_leaf") and rng.random() < 0.25:
            return _base_leaf(rng, space)
        return {"t": T_FIELD, "name": rng.choice(space["fields"])}
    return _function_node(rng, space, max_depth - 1)


def _function_node(rng: random.Random, space: Dict[str, List], max_depth: int) -> Dict:
    """随机生成一个函数节点 (算术/时序/截面), 递归生成子节点"""
    if max_depth <= 0:
        return _terminal(rng, space)
    choices: List[str] = []
    choices += ["bin"] * len(space["arith_binary"])
    choices += ["un"] * len(space["arith_unary"])
    choices += ["ts"] * len(space["ts"])
    choices += ["ts_raw"] * len(space["ts_raw"])
    choices += ["ts_fixed"] * len(space.get("ts_fixed", []))
    choices += ["cs"] * len(space["cs"])
    kind = rng.choice(choices)
    if kind == "bin":
        name = rng.choice(space["arith_binary"])
        return {
            "t": T_OP, "name": name,
            "args": [_grow_arg(rng, space, max_depth - 1),
                     _grow_arg(rng, space, max_depth - 1)],
        }
    if kind == "un":
        name = rng.choice(space["arith_unary"])
        return {"t": T_OP, "name": name, "args": [_grow_arg(rng, space, max_depth - 1)]}
    if kind == "ts":
        name = rng.choice(space["ts"])
        return {
            "t": T_TS, "name": name,
            "arg": _grow_arg(rng, space, max_depth - 1),
            "window": rng.choice(WINDOW_POOL),
        }
    if kind == "ts_raw":
        name = rng.choice(space["ts_raw"])
        return {"t": T_TS_RAW, "name": name, "arg": _grow_arg(rng, space, max_depth - 1)}
    if kind == "ts_fixed":
        name = rng.choice(space["ts_fixed"])
        return {"t": T_TS_FIXED, "name": name, "arg": _grow_arg(rng, space, max_depth - 1)}
    # cs
    name = rng.choice(space["cs"])
    return {"t": T_CS, "name": name, "arg": _grow_arg(rng, space, max_depth - 1)}


def _grow(rng: random.Random, space: Dict[str, List], max_depth: int) -> Dict:
    """grow 法生成子树: 深度不足时以概率选终端或函数, 深度到底只能终端"""
    if max_depth <= 0 or (max_depth < 2 and rng.random() < 0.5):
        return _terminal(rng, space)
    if max_depth >= 2 and rng.random() < 0.35:
        return _terminal(rng, space)
    return _function_node(rng, space, max_depth)


def random_tree(rng: random.Random, max_depth: int,
                space: Optional[Dict[str, List]] = None) -> Dict:
    """ramped half-and-half 初始化: 一半 grow / 一半 full (参照 gplearn init_method)
    full 法: 深度固定 = 目标深度, 只有最底层才允许终端
    """
    space = space or SPACE_L0
    depth = rng.randint(2, max(2, max_depth))
    if rng.random() < 0.5:
        # grow: 根节点强制为函数节点, 保证生成的是"因子"而非裸字段/常数
        return _function_node(rng, space, depth - 1)
    # full: 递归到深度 1 才终端
    def _full(d: int) -> Dict:
        if d <= 1:
            return _terminal(rng, space)
        return _function_node_full(rng, space, d)

    def _function_node_full(rng_, space_, d: int) -> Dict:
        if d <= 1:
            return _terminal(rng_, space_)
        # full 法: 若已到最深一层则必须选终端, 否则函数
        if d == 1:
            return _terminal(rng_, space_)
        # 构建函数节点但子节点用 full 递归 (深度-1)
        node = _function_node_skel(rng_, space_)
        node = _fill_full(rng_, space_, node, d - 1)
        return node

    def _function_node_skel(rng_, space_):
        # 仅生成骨架, 子节点位置先占位
        kind = rng_.choice(
            ["bin"] * len(space_["arith_binary"]) +
            ["un"] * len(space_["arith_unary"]) +
            ["ts"] * len(space_["ts"]) +
            ["ts_raw"] * len(space_["ts_raw"]) +
            ["ts_fixed"] * len(space_.get("ts_fixed", [])) +
            ["cs"] * len(space_["cs"])
        )
        if kind == "bin":
            return {"t": T_OP, "name": rng_.choice(space_["arith_binary"]),
                    "args": [None, None]}
        if kind == "un":
            return {"t": T_OP, "name": rng_.choice(space_["arith_unary"]),
                    "args": [None]}
        if kind == "ts":
            return {"t": T_TS, "name": rng_.choice(space_["ts"]),
                    "arg": None, "window": rng_.choice(WINDOW_POOL)}
        if kind == "ts_raw":
            return {"t": T_TS_RAW, "name": rng_.choice(space_["ts_raw"]),
                    "arg": None}
        if kind == "ts_fixed":
            return {"t": T_TS_FIXED, "name": rng_.choice(space_["ts_fixed"]),
                    "arg": None}
        return {"t": T_CS, "name": rng_.choice(space_["cs"]), "arg": None}

    def _fill_full(rng_, space_, node, d: int) -> Dict:
        # 把节点占位子节点填满 (full 法: 深度 1 以下全函数, 到底层才终端)
        # 底层终端强制用字段 (避免常数入算子导致 AttributeError)
        def _fill_one():
            if d <= 1:
                if space_.get("base_leaf") and rng_.random() < 0.2:
                    return _base_leaf(rng_, space_)
                return {"t": T_FIELD, "name": rng_.choice(space_["fields"])}
            skel = _function_node_skel(rng_, space_)
            return _fill_full(rng_, space_, skel, d - 1)
        if node["t"] == T_OP and node["name"] in ARITH_BINARY_SET:
            node["args"] = [_fill_one(), _fill_one()]
        elif node["t"] == T_OP:
            node["args"] = [_fill_one()]
        elif node["t"] in (T_TS, T_TS_RAW, T_TS_FIXED):
            node["arg"] = _fill_one()
        else:
            node["arg"] = _fill_one()
        return node

    return _full(depth)


def tree_to_str(node: Dict) -> str:
    """表达式树 -> 因子构建 DSL 字符串 (可被 factor_engine 执行)"""
    t = node["t"]
    if t == T_FIELD:
        return node["name"]
    if t == T_CONST:
        return str(node["val"])
    if t == T_BASE_LEAF:
        # 参数化基类叶子: rsi(14) 带窗口参数; macd/kdj/bbands 等固定参数基类
        # 在引擎命名空间中是函数对象, 必须带空括号调用 macd() 才返回 DataFrame
        if node.get("params"):
            return f"{node['name']}({node['params'][0]})"
        return f"{node['name']}()"
    if t == T_OP:
        name = node["name"]
        if name in ARITH_BINARY_SET:
            l = tree_to_str(node["args"][0])
            r = tree_to_str(node["args"][1])
            op_sym = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[name]
            return f"({l}{op_sym}{r})"
        return f"abs({tree_to_str(node['args'][0])})"
    if t == T_TS:
        return f"{node['name']}({tree_to_str(node['arg'])}, {node['window']})"
    if t == T_TS_MULTI:
        # 多参带窗时序算子: ts_Corr(字段A, 字段B, 窗口) (与引擎 ts_Corr(df1,df2,n) 语义一致)
        return f"{node['name']}({tree_to_str(node['args'][0])}, {tree_to_str(node['args'][1])}, {node['window']})"
    if t == T_TS_PARAMS:
        # 多定参时序算子: ts_MACD_HIST(字段A, 12, 26, 9) (还原可被引擎执行的形态)
        s = ", ".join(tree_to_str(a) for a in node["args"])
        if node.get("params"):
            s = f"{s}, " + ", ".join(str(p) for p in node["params"])
        return f"{node['name']}({s})"
    if t == T_TS_RAW:
        return f"{node['name']}({tree_to_str(node['arg'])})"
    if t == T_TS_FIXED:
        # 固定参数: 只渲染函数名 + 子表达式, 参数用引擎默认值
        return f"{node['name']}({tree_to_str(node['arg'])})"
    # cs
    return f"{node['name']}({tree_to_str(node['arg'])})"


# ============================================================
# 5.1.1 Warm-Start 可解析化: 字符串公式 -> dict 树 (注入前筛选/解析)
# ============================================================
# GPU 可编译字段集 (与 factor_gpu_evaluator._GPU_FIELDS 一致; 因子库公式里的大写字段)
_GPU_FIELD_SET = set(GP_FIELDS)
# 无窗时序算子 / 截面算子 (GPU 端 TORCH_TS_RAW / TORCH_CS 的键, 单参调用)
_TS_RAW_NAMES = {"ts_Log", "ts_Identity"}
_CS_NAMES = {"cs_Rank", "cs_Demean", "cs_Zscore", "cs_TransNorm"}

# 多参带窗时序算子白名单 (双字段/子表达式 + 窗口, GPU 端 TORCH_TS 支持 2 字段签名):
# 引擎 ts_Corr(df1, df2, n) 与 ts_Cov(df1, df2, n) 为真正的双字段算子
# (LLM 提示词量价协同维度 / RL ts_Cov_10 使用), 其余 ts_* 均为单参。
_TS_MULTI_ARG_OPS: set = {"ts_Corr", "ts_Cov"}

# 多参/多字段时序函数名 -> L2 基类叶子名 反向映射 (阶段5.1.1 折叠注入)
# ------------------------------------------------------------------
# 因子库 formula 里大量 ts_* 是"基类指标"的展开形态 (多参或多字段), 例如
#   ts_MACD_DIF(Close,12,26,9) == macd() 基类 (固定参数, 引擎默认 12/26/9)
#   ts_KDJ_K(High,Low,Close,9,3)  == kdj()  基类
#   ts_OBV(Close,Volume)          == TALIB_OBV() 基类
# 这些形态当前解析器只认"单参+窗口" (ts_Name(子表达式,N)), 其余直接抛错剔除,
# 导致整条公式无法注入。此处把这些函数名折叠映射到 L2 已定义的基类叶子
# (GP_BASE_LEAF 的键), 注入后生成的树为 {"t":"base_leaf","name":...,"params":[]},
# 与随机树生成的固定参数基类叶子完全同构 —— 可 GPU 整树求值、可交叉/变异/嫁接,
# 与随机生成的因子完全共享计算逻辑, 不存在原子级/残缺个体。
# 前提: 库内公式均使用引擎默认参数 (已逐一核对 factor_init.py), 折叠后语义零偏差。
# 未纳入 (无对应基类/引擎无基类定义): ts_MACD_DEA/ts_MACD_HIST/ts_KDJ_D/ts_BarraMomentum 等,
#   以及财务 FN/缠论/比较运算符等特殊语法 —— 维持剔除 (类型隔离/依赖特殊数据源)。
_TS_MULTI_TO_BASE: Dict[str, str] = {
    # ---- 固定参数基类 (对应 GP_BASE_LEAF 中 None 键) ----
    "ts_MACD_DIF": "macd",
    "ts_BOLL_POS": "bbands",
    "ts_KDJ_K": "kdj",
    # ---- TALIB 族固定参数基类 (对应 GP_BASE_LEAF 中 TALIB_* 键) ----
    "ts_PPO": "TALIB_PPO",
    "ts_STOCHRSI_K": "TALIB_STOCHRSI",
    "ts_STOCHF_K": "TALIB_STOCHF",
    "ts_AROON_UP": "TALIB_AROON",
    "ts_AROONOSC": "TALIB_AROONOSC",
    "ts_MFI": "TALIB_MFI",
    "ts_ULTOSC": "TALIB_UO",
    "ts_ADXR": "TALIB_ADXR",
    "ts_NATR": "TALIB_NATR",
    "ts_TRANGE": "TALIB_TRANGE",
    "ts_AD": "TALIB_AD",
    "ts_ADOSC": "TALIB_ADOSC",
    "ts_OBV": "TALIB_OBV",
    "ts_AVGPRICE": "TALIB_AVGPRICE",
    "ts_MEDPRICE": "TALIB_MEDPRICE",
    "ts_TYPPRICE": "TALIB_TYPPRICE",
    "ts_WCLPRICE": "TALIB_WCLPRICE",
    "ts_BETA": "TALIB_BETA",
    "ts_CORREL": "TALIB_CORREL",
    "ts_HT_DCPERIOD": "TALIB_HT_DCPERIOD",
    "ts_HT_DCPHASE": "TALIB_HT_DCPHASE",
    "ts_HT_TRENDMODE": "TALIB_HT_TRENDMODE",
}


def _tokenize_formula(s: str) -> List[Tuple[str, str]]:
    """公式字符串 -> token 列表 [(kind, value)], kind ∈ num/id/运算符/括号/逗号
    不识别比较运算符(> < >= <=)与 np. 等符号: 直接抛错 -> 途径A 筛选剔除。"""
    toks: List[Tuple[str, str]] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit():
            j = i
            while j < n and (s[j].isdigit() or s[j] == "."):
                j += 1
            toks.append(("num", s[i:j]))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (s[j].isalnum() or s[j] in "._"):
                j += 1
            toks.append(("id", s[i:j]))
            i = j
            continue
        if ch in "+-*/(),":
            toks.append((ch, ch))
            i += 1
            continue
        raise ValueError(f"公式含无法识别的字符: {ch!r} (位置 {i})")
    return toks


def _fold_const_value(node: Optional[Dict]) -> Optional[float]:
    """把常数/常数表达式 (一元负号 -x 解析为 -1*x) 折叠为数值; 不可折叠返回 None"""
    if node is None:
        return None
    if node.get("t") == T_CONST:
        return float(node["val"])
    if node.get("t") == T_OP and node["name"] == "mul" and len(node.get("args", [])) == 2:
        a = _fold_const_value(node["args"][0])
        b = _fold_const_value(node["args"][1])
        if a is not None and b is not None:
            return a * b
    return None


def _build_call_node(name: str, args: List[Dict]) -> Dict:
    """把函数调用名+参数列表转 dict 树节点 (仅 GPU 兼容语法子集)"""
    if name == "abs":
        if len(args) != 1:
            raise ValueError(f"{name} 需 1 个参数, 实际 {len(args)}")
        return {"t": T_OP, "name": "abs", "args": args}
    if name in ("gate", "if_gt"):
        # 三目条件算子 (RL 因子挖掘解码产物的 GPU 兼容入口; GP 搜索空间不生成,
        # 因子库公式亦不含 —— 仅收尾 GPU 编译路径消费, 不影响 GP 行为)
        if len(args) != 3:
            raise ValueError(f"{name} 需 3 个参数, 实际 {len(args)}")
        return {"t": T_OP, "name": name, "args": args}
    if name in ("sign", "jump", "max3", "signed_log", "sqrt",
                "sigmoid", "tanh_squash", "power", "clip", "winsorize"):
        # AlphaMaster 映射补充算术算子 (RL 解码产物 / GP_ARITH_UNARY 同源):
        # 首参为表达式, 其余为尾部常数默认参数 (power(x[,a]) / clip(x[,lo,hi]) /
        # winsorize(x[,lo,hi])); 尾部参数允许 "-3" 等一元负号形式, 先常量折叠。
        if len(args) == 0:
            raise ValueError(f"{name} 至少需 1 个参数")
        if name in ("sign", "jump", "max3", "signed_log", "sqrt",
                    "sigmoid", "tanh_squash"):
            if len(args) != 1:
                raise ValueError(f"{name} 需 1 个参数, 实际 {len(args)}")
        folded = [args[0]]
        for a in args[1:]:
            v = _fold_const_value(a)
            if v is None:
                raise ValueError(f"{name} 除首参外参数需为常数")
            folded.append({"t": T_CONST, "val": float(v)})
        return {"t": T_OP, "name": name, "args": folded}
    if name in _TS_RAW_NAMES:
        if len(args) != 1:
            raise ValueError(f"{name} 需 1 个参数, 实际 {len(args)}")
        return {"t": T_TS_RAW, "name": name, "arg": args[0]}
    if name in _CS_NAMES:
        if len(args) != 1:
            raise ValueError(f"{name} 需 1 个参数, 实际 {len(args)}")
        return {"t": T_CS, "name": name, "arg": args[0]}
    if name.startswith("ts_"):
        # 多参带窗时序算子 (双字段/子表达式 + 窗口): ts_Corr(字段A,字段B,窗口)
        # —— 作 ts_multi 节点, GPU 整树求值 (双字段张量 + 窗口); 非白名单内一律剔除。
        if name in _TS_MULTI_ARG_OPS:
            if len(args) == 3 and args[2].get("t") == T_CONST:
                return {"t": T_TS_MULTI, "name": name, "args": [args[0], args[1]],
                        "window": int(args[2]["val"])}
            raise ValueError(f"{name} 需 双参+窗口 形态: {name}(字段A,字段B,窗口)")
        # 单参带窗时序算子: ts_Name(子表达式, 窗口) —— 必须为搜索空间算子 (统一
        # 搜索空间与计算空间), 否则折叠为 L2 已定义基类叶子(原子, 如 ts_BETA->TALIB_BETA)
        # 或剔除, 杜绝"非搜索空间算子被解析为可打散节点注入"。
        if len(args) == 2 and args[1].get("t") == T_CONST:
            if name in _TS_OPS_IN_SPACE:
                return {"t": T_TS, "name": name, "arg": args[0],
                        "window": int(args[1]["val"])}
            base_name = _TS_MULTI_TO_BASE.get(name)
            if base_name is not None:
                return {"t": T_BASE_LEAF, "name": base_name, "params": []}
            raise ValueError(f"{name} 不在搜索空间, 剔除")
        # 多参/多字段形态 (ts_MACD_DIF(Close,12,26,9) 等):
        # 阶段5.1.1 折叠注入 —— 折叠映射为 L2 已定义的基类叶子 (固定参数 base_leaf,
        # params=[] 用引擎默认参数, 与随机树生成的同构); 库内公式均为默认参数, 语义零偏差。
        base_name = _TS_MULTI_TO_BASE.get(name)
        if base_name is not None:
            return {"t": T_BASE_LEAF, "name": base_name, "params": []}
        # 多定参时序算子兜底 (阶段 P0: ts_MACD_HIST(Close,12,26,9) /
        # ts_KDJ_D(High,Low,Close,9,3) / ts_BOLL_WIDTH(Close,20,2) 等):
        # 拆分为 前部子树参数 + 尾部定参, 作 ts_params 节点, GPU 端整树求值。
        # 仅当前部参数全部为非定参(字段/子树)且尾部定参非空时可用。
        const_tail = 0
        for a in reversed(args):
            if a.get("t") == T_CONST:
                const_tail += 1
            else:
                break
        if const_tail > 0:
            tree_args = args[:-const_tail]
            if tree_args and all(a.get("t") != T_CONST for a in tree_args):
                # 阶段 P5: 多定参算子也必须属于搜索空间 (统一搜索空间与计算空间);
                # 搜索空间当前无多定参算子, 故非空间多参算子一律剔除 (防可打散节点注入)
                if name not in _TS_OPS_IN_SPACE:
                    raise ValueError(f"{name} 不在搜索空间, 剔除")
                params = [int(a["val"]) for a in args[-const_tail:]]
                return {"t": T_TS_PARAMS, "name": name, "args": tree_args, "params": params}
        raise ValueError(f"{name} 需 单参+窗口 形态 (多参/多字段 GPU 不支持, 剔除)")
    if name in BASE_OPERATOR_MAP:
        # 基类叶子: 参数化基类带窗口(returns(5)), 固定参数基类无参(macd())
        params = []
        for a in args:
            if a.get("t") != T_CONST:
                raise ValueError(f"基类 {name} 参数需为常数")
            params.append(int(a["val"]))
        return {"t": T_BASE_LEAF, "name": name, "params": params}
    raise ValueError(f"不支持的函数: {name}")


def formula_to_tree(formula: str) -> Optional[Dict]:
    """把因子库 formula 字符串解析为 factor_gp 的 dict 树 (仅 GPU 兼容语法子集)

    覆盖: 字段 / 常数 / + - * / 与一元负号 / abs() / 单参带窗 ts_*(X,N) / 无窗
    ts_Log|ts_Identity / 截面 cs_* / 基类叶子(参数化+固定参数, BASE_OPERATOR_MAP)。
    不覆盖(返回 None, 供途径A筛选剔除): 多参时序(ts_MACD_DIF(Close,12,26,9) 等) /
          np.maximum / 比较运算符 / 缠论龙头等引擎特殊算子 / 中文伪公式。
    返回树可被 tree_to_str 还原为引擎可执行表达式; gpu_supported(树)=True 时
    可 GPU 整树求值 (由 formula_parseable_gpu 保证)。
    """
    try:
        toks = _tokenize_formula(str(formula))
        pos = [0]

        def _peek() -> Optional[str]:
            return toks[pos[0]][0] if pos[0] < len(toks) else None

        def _peek_val() -> Optional[str]:
            return toks[pos[0]][1] if pos[0] < len(toks) else None

        def _advance() -> Tuple[str, str]:
            t = toks[pos[0]]
            pos[0] += 1
            return t

        def _parse_expr() -> Dict:
            left = _parse_term()
            while _peek() in ("+", "-"):
                op = _advance()[0]
                right = _parse_term()
                left = {"t": T_OP, "name": {"+": "add", "-": "sub"}[op],
                        "args": [left, right]}
            return left

        def _parse_term() -> Dict:
            left = _parse_factor()
            while _peek() in ("*", "/"):
                op = _advance()[0]
                right = _parse_factor()
                left = {"t": T_OP, "name": {"*": "mul", "/": "div"}[op],
                        "args": [left, right]}
            return left

        def _parse_factor() -> Dict:
            kind = _peek()
            if kind is None:
                raise ValueError("表达式意外结束")
            if kind == "num":
                return {"t": T_CONST, "val": float(_advance()[1])}
            if kind == "-":
                _advance()  # 一元负号: -x -> -1 * x
                sub = _parse_factor()
                return {"t": T_OP, "name": "mul",
                        "args": [{"t": T_CONST, "val": -1.0}, sub]}
            if kind == "(":
                _advance()
                node = _parse_expr()
                if _peek() != ")":
                    raise ValueError("缺右括号")
                _advance()
                return node
            if kind == "id":
                name = _advance()[1]
                if _peek() == "(":
                    _advance()
                    args = []
                    if _peek() != ")":
                        args.append(_parse_expr())
                        while _peek() == ",":
                            _advance()
                            args.append(_parse_expr())
                    if _peek() != ")":
                        raise ValueError("函数缺右括号")
                    _advance()
                    return _build_call_node(name, args)
                if name in _GPU_FIELD_SET:
                    return {"t": T_FIELD, "name": name}
                if name in BASE_OPERATOR_MAP:
                    # 固定参数基类无参调用 (macd()/kdj()/bbands())
                    return {"t": T_BASE_LEAF, "name": name, "params": []}
                raise ValueError(f"未知字段/函数: {name}")
            raise ValueError(f"意外的 token: {kind}")

        node = _parse_expr()
        if pos[0] != len(toks):
            raise ValueError(f"存在多余 token: {_peek_val()}")
        return node
    except Exception:
        return None


def formula_parseable_gpu(formula: str) -> Optional[Dict]:
    """途径A 白名单检查: 公式可解析成树 且 gpu_supported 通过 -> 返回树; 否则 None

    None 表示该公式不注入 (无法解析 / GPU 不可编译)。
    """
    tree = formula_to_tree(formula)
    if tree is None:
        return None
    try:
        from lib.factor_gpu_evaluator import gpu_supported
        if gpu_supported(tree):
            return tree
    except Exception:
        return None
    return None


def tree_depth(node: Dict) -> int:
    """返回树深度 (根=1)"""
    t = node["t"]
    if t in (T_FIELD, T_CONST, T_BASE_LEAF):
        return 1
    if t == T_OP:
        return 1 + max(tree_depth(a) for a in node["args"])
    if t in (T_TS_MULTI, T_TS_PARAMS):
        return 1 + max(tree_depth(a) for a in node["args"])
    return 1 + tree_depth(node["arg"])


def tree_size(node: Dict) -> int:
    """返回节点总数 (复杂度)"""
    t = node["t"]
    if t in (T_FIELD, T_CONST, T_BASE_LEAF):
        return 1
    if t == T_OP:
        return 1 + sum(tree_size(a) for a in node["args"])
    if t in (T_TS_MULTI, T_TS_PARAMS):
        return 1 + sum(tree_size(a) for a in node["args"])
    return 1 + tree_size(node["arg"])


def expr_hash(expr: str) -> str:
    """表达式规范化哈希 (去重用): 排序标识符 + 数值取整归一, 降低同构变体误判"""
    # 提取所有标识符与数字, 排序拼接后哈希
    idents = sorted(set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr)))
    nums = sorted(int(float(x)) for x in re.findall(r"\d+", expr) if x.isdigit())
    # 绝对值归一: 负数常数 (-1*X 与 X) 视为不同结构, 保留; 但同值常数取整归一
    return hashlib.md5(f"{idents}|{nums}".encode("utf-8")).hexdigest()


def expr_length_penalty(expr: str, coefficient: float = 0.001,
                        tree: Optional[Dict] = None) -> float:
    """parsimony 复杂度惩罚 (按节点数, 对齐 gplearn parsimony_coefficient * len(program))

    tree 已解析时直接取其节点数 (GPU 热路径/验证段, 避免重复解析);
    tree 为 None 时内部解析表达式 (fitness_expr/worker 路径);
    解析失败回退旧口径 (括号逗号计数), 与历史行为一致。
    """
    if tree is None:
        tree = formula_to_tree(expr)
    if tree is not None:
        return coefficient * tree_size(tree)
    return coefficient * len(re.findall(r"[(),]", expr))


def _is_bare_field(expr: str) -> bool:
    """判断表达式是否为纯裸字段/常数 (不含算子调用)

    2026-08-16 实测: GP 在无中性化时容易收敛到裸字段(如 Amount, |IC|≈0.126),
    这些因子无增量信息且已被库内因子覆盖, 候选输出时应过滤掉.

    注意: tree_to_str 将算术算子渲染为符号 (add→+, mul→*, div→/), 所以
    正则必须同时匹配算子名和渲染符号, 否则 (VWAP/Open) 等复合表达式会被误判为裸字段.
    基类叶子 (rsi(14)/macd()/TALIB_MFI()) 是函数调用形式, 含 '(' 即可识别, 不算裸字段.
    """
    return not bool(re.search(r"(add|sub|mul|div|abs|ts_|cs_|[+\-*/]|\()", expr))


# ============================================================
# 三、遗传算子: 交叉 / 变异 (参照 QuantGplearn _program.py)
# ============================================================
def _all_nodes(node: Dict) -> List[Tuple[int, Dict]]:
    """返回 (id, node) 列表, 用于随机选点"""
    out: List[Tuple[int, Dict]] = []
    _idx = [0]

    def _walk(n: Dict):
        nid = _idx[0]
        _idx[0] += 1
        out.append((nid, n))
        t = n["t"]
        if t in (T_OP, T_TS_MULTI, T_TS_PARAMS):
            for a in n["args"]:
                _walk(a)
        elif t in (T_TS, T_TS_RAW, T_TS_FIXED, T_CS):
            _walk(n["arg"])
    _walk(node)
    return out


def _replace_subtree(root: Dict, old_sub: Dict, new_sub: Dict) -> None:
    """用 new_sub 替换 root 中与 old_sub 相同引用的节点 (原地)"""
    if root is old_sub:
        root.clear()
        root.update(new_sub)
        return

    def _walk(n: Dict) -> bool:
        t = n["t"]
        if t in (T_OP, T_TS_MULTI, T_TS_PARAMS):
            for i, a in enumerate(n["args"]):
                if a is old_sub:
                    n["args"][i] = new_sub
                    return True
                if _walk(a):
                    return True
        elif t in (T_TS, T_TS_RAW, T_TS_FIXED, T_CS):
            if n["arg"] is old_sub:
                n["arg"] = new_sub
                return True
            if _walk(n["arg"]):
                return True
        return False
    _walk(root)


def crossover(rng: random.Random, parent_a: Dict, parent_b: Dict,
              max_depth: int) -> Dict:
    """子树交叉: 交换两个父代随机子树 (参照 gplearn crossover)
    若交换后深度超限, 回退为直接复制 parent_a
    """
    child = copy_tree(parent_a)
    donor = copy_tree(parent_b)
    if tree_depth(child) <= 1 or tree_depth(donor) <= 1:
        return child
    nodes_a = _all_nodes(child)
    nodes_b = _all_nodes(donor)
    sub_a_id, sub_a = rng.choice(nodes_a)
    _, sub_b = rng.choice(nodes_b)
    # 计算替换后深度: 找到 sub_a 在 child 中的深度位置
    pos_depth = _node_depth(child, sub_a)
    new_depth = pos_depth - tree_depth(sub_a) + tree_depth(sub_b)
    if new_depth > max_depth:
        return child  # 超限回退 (直接复制 parent_a)
    _replace_subtree(child, sub_a, sub_b)
    # 阶段 P5: 替换后实测整树深度兜底 (原 new_depth 仅按替换点估算, 未计入 child 其他
    # 更深分支, 会漏检导致深度超限膨胀; 实测超限则回退复制 parent_a)
    if tree_depth(child) > max_depth:
        return copy_tree(parent_a)
    return child


def _node_depth(root: Dict, sub: Dict) -> int:
    """返回 sub 在 root 中的深度 (根=1)"""
    def _walk(n: Dict, d: int):
        if n is sub:
            return d
        t = n["t"]
        if t in (T_OP, T_TS_MULTI, T_TS_PARAMS):
            for a in n["args"]:
                r = _walk(a, d + 1)
                if r:
                    return r
        elif t in (T_TS, T_TS_RAW, T_TS_FIXED, T_CS):
            return _walk(n["arg"], d + 1)
        return None
    return _walk(root, 1) or 1


def point_mutation(rng: random.Random, node: Dict,
                   space: Optional[Dict[str, List]] = None) -> Dict:
    """点变异: 随机替换一个节点 (算子/字段/窗口/常数) (参照 gplearn point_mutation)"""
    space = space or SPACE_L0
    child = copy_tree(node)
    _, sub = rng.choice(_all_nodes(child))
    t = sub["t"]
    if t == T_FIELD:
        sub["name"] = rng.choice(space["fields"])
    elif t == T_CONST:
        sub["val"] = rng.choice(space["constants"])
    elif t == T_BASE_LEAF:
        # 基类叶子: 50% 换基类名, 50% 换窗口参数 (若有)
        if rng.random() < 0.5 and space.get("base_leaf"):
            name = rng.choice(list(space["base_leaf"].keys()))
            pool = space["base_leaf"][name]
            sub["name"] = name
            sub["params"] = [rng.choice(pool)] if pool else []
        else:
            pool = space.get("base_leaf", {}).get(sub["name"])
            if pool:
                sub["params"] = [rng.choice(pool)]
    elif t == T_OP:
        # 二元/一元互换时要同步 args 数量
        if sub["name"] in ARITH_BINARY_SET:
            # 40% 换同类二元, 其余换字段/常数? 这里只换二元算术算子
            sub["name"] = rng.choice(space["arith_binary"])
        else:
            sub["name"] = rng.choice(space["arith_unary"])
    elif t == T_TS:
        # 改窗口
        sub["window"] = rng.choice(WINDOW_POOL)
    elif t == T_TS_RAW:
        sub["name"] = rng.choice(space["ts_raw"])
    elif t == T_TS_FIXED:
        # 换一个固定参数算子 (参数保持引擎默认值)
        if space.get("ts_fixed"):
            sub["name"] = rng.choice(space["ts_fixed"])
    elif t == T_CS:
        sub["name"] = rng.choice(space["cs"])
    return child


def subtree_mutation(rng: random.Random, node: Dict, max_depth: int,
                     space: Optional[Dict[str, List]] = None) -> Dict:
    """子树变异: 用随机新树替换某子树 (参照 gplearn subtree_mutation)"""
    space = space or SPACE_L0
    child = copy_tree(node)
    if tree_depth(child) <= 1:
        # 只有终端: 直接换成随机新树
        new_sub = random_tree(rng, max_depth, space)
        child.clear()
        child.update(new_sub)
        return child
    _, sub = rng.choice(_all_nodes(child))
    new_sub = random_tree(rng, max(1, max_depth - 2), space)
    if tree_depth(child) - tree_depth(sub) + tree_depth(new_sub) > max_depth:
        # 超限: 用更浅的新树
        new_sub = _grow(rng, space, 1)
    _replace_subtree(child, sub, new_sub)
    # 阶段 P5: 替换后实测整树深度兜底 (原公式仅按整树深度估算, 会漏检导致深度超限膨胀;
    # 实测超限则改用更浅的 grow 树重试, 仍超限则保持原树)
    if tree_depth(child) > max_depth:
        child = copy_tree(node)
        _, sub = rng.choice(_all_nodes(child))
        _replace_subtree(child, sub, _grow(rng, space, 1))
        if tree_depth(child) > max_depth:
            return copy_tree(node)
    return child


def hoist_mutation(rng: random.Random, node: Dict, max_depth: int) -> Dict:
    """Hoist 变异: 提升某子树为根 (简化树, 参照 gplearn hoist_mutation)"""
    child = copy_tree(node)
    if tree_depth(child) <= 1:
        return child
    nodes = _all_nodes(child)
    # 选一个非根子树提升
    candidates = [(i, n) for i, n in nodes if i > 0]
    if not candidates:
        return child
    _, sub = rng.choice(candidates)
    if tree_depth(sub) > max_depth:
        return child
    child.clear()
    child.update(sub)
    return child


def copy_tree(node: Dict) -> Dict:
    """深拷贝树 (避免交叉/变异污染原个体)"""
    import copy
    return copy.deepcopy(node)


# ============================================================
# 四、适应度评估 (复用现有因子引擎)
# ============================================================
def fitness_expr(expr: str,
                 panel: Dict[str, pd.DataFrame],
                 prices_panel: Dict[str, pd.DataFrame],
                 rebal_period: int = 21,
                 min_warmup: int = 130,
                 ts_normalize_window: Optional[int] = None,
                 marketcap_proxy_lookback: Optional[int] = None,
                 parsimony: float = 0.001,
                 route_ts_by_type: bool = True) -> Tuple[Optional[float], Optional[Dict]]:
    """计算单个表达式适应度 (RankIC) 与完整评价结果

    返回 (fitness, result):
        fitness: |RankIC均值| - 复杂度惩罚; 无效/异常返回 None
        result:  run_ic_timeseries_panel 的完整结果 (用于展示/测试段复核)

    route_ts_by_type: 启用「TS标准化」时是否按候选类型路由:
      - True (默认, 进化/OOS/WF/worker 用): 仅对快速判定为 technical_ts 的表达式
        应用 ts_normalize_window; technical(量纲可比) 不加 TS, 避免误伤其截面信号。
      - False (仅展示层双口径计算用): 对所有表达式显式应用 ts_normalize_window,
        用于产出"若按 TS 口径评价"的展示指标。

    marketcap_proxy_lookback: 点-in-time 市值中性化窗口 (None=不中性化)。
        2026-08-16 实测: A 股训练段小市值效应极强, 不中性化时 GP 会收敛到裸规模因子
        (如 Amount, |IC|≈0.126); 接入 20 日成交额代理后 Amount |IC| 降到 0.044,
        规模干扰被压制, GP 才能去挖"非规模信号"。
    """
    ok, msg = validate_expression(expr)
    if not ok:
        return None, None
    try:
        fv = evaluate_expression(expr, panel)
    except Exception:
        return None, None
    if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
        return None, None
    # 非空率检查 (避免全 NaN / 病态表达式浪费评价)
    # 门槛 0.2: 除零病态公式(如 ts_VAR 产生大量 0 后 ts_PctChange)会让因子值大面积 NaN,
    # 非空率仅 ~5%, 有效截面过少时 RankIC 虚高, 直接判无效 (RankIC 假相关修复配套)
    non_null = float(fv.notna().mean().mean()) if len(fv) else 0.0
    if non_null < 0.2:
        return None, None
    # 按类型路由 TS: technical_ts 才应用 ts_normalize_window
    _ts_eff = ts_normalize_window
    if route_ts_by_type and ts_normalize_window:
        try:
            from lib.factor_engine import _is_technical_ts_expression
            if not _is_technical_ts_expression(expr):
                _ts_eff = None
        except Exception:
            _ts_eff = None
    try:
        result = run_ic_timeseries_panel(
            fv, prices_panel, rebal_period=rebal_period,
            min_warmup=min_warmup, ts_normalize_window=_ts_eff,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
        )
    except Exception:
        return None, None
    rank_ic = result.get("rank_ic_mean")
    if rank_ic is None or not np.isfinite(rank_ic):
        return None, result
    fitness = float(abs(rank_ic)) - expr_length_penalty(expr, parsimony)
    return fitness, result


# 价格/量类"水平"字段: 整体缩放它们可探测因子是否对水平敏感 (technical_ts 判据)
# 同时覆盖大写(合成面板)与小写(load_daily_kline 真实列: open/close/.../turnover_rate)
_PRICE_LEVEL_COLS = (
    "Open", "High", "Low", "Close", "VWAP", "Amount", "Volume", "Turnover",
    "open", "high", "low", "close", "vwap", "amount", "volume",
    "turnover", "turnover_rate",
)


def detect_ts_by_scale(expr: str, panel: Dict[str, pd.DataFrame],
                       n_stocks: int = 8, n_dates: int = 120,
                       scale: float = 2.0) -> Optional[str]:
    """尺度不变性探测: 客观判定表达式属于 technical 还是 technical_ts

    原理: 把全体价格/量类字段整体放大 scale 倍 (保留相对走势), 重算因子值:
      - technical (returns/momentum/ratio/rank 等量纲可比): 输出基本不变
      - technical_ts (均价/OBV/AD/累积量/绝对波动等水平敏感): 输出近似随之放大 scale 倍
    用 f1/f0 的对数中位数判断 (tech -> 0, ts -> log(scale)); 无法判定返回 None,
    由调用方回退到关键词启发式 _is_technical_ts_expression 或默认 technical。
    """
    if not expr or not panel:
        return None
    codes = [c for c in panel if panel[c] is not None][:n_stocks]
    if not codes:
        return None
    sub = {}
    for c in codes:
        df = panel[c]
        sub[c] = df.iloc[max(0, len(df) - n_dates):]
    try:
        from lib.factor_engine import evaluate_expression
        f0 = evaluate_expression(expr, sub)
        sub2 = {}
        for c, df in sub.items():
            d2 = df.copy()
            for col in _PRICE_LEVEL_COLS:
                if col in d2.columns:
                    d2[col] = d2[col] * scale
            sub2[c] = d2
        f1 = evaluate_expression(expr, sub2)
    except Exception:
        return None
    if f0 is None or f1 is None or len(f0) == 0 or len(f1) == 0:
        return None
    idx = f0.index.intersection(f1.index)
    cols = f0.columns.intersection(f1.columns)
    if len(idx) == 0 or len(cols) == 0:
        return None
    try:
        a0 = f0.loc[idx, cols].to_numpy(dtype=float)
        a1 = f1.loc[idx, cols].to_numpy(dtype=float)
    except Exception:
        return None
    m = np.isfinite(a0) & np.isfinite(a1) & (np.abs(a0) > 1e-9)
    if int(m.sum()) < 20:
        return None
    logr = np.log(np.abs(a1[m] / a0[m]))
    med = float(np.median(logr))
    lg = float(np.log(scale))
    if abs(med) < 0.08:
        return "technical"
    if abs(med - lg) < 0.08:
        return "technical_ts"
    return None  # 混合/不确定, 交给调用方回退


# ============================================================
# 阶段3.3 并行加速: ProcessPool worker (Windows spawn 需顶层可 pickle 函数)
# 候选表达式评估彼此独立, 天然可多进程并行; panel 经 initializer 只传一次,
# 任务只传表达式字符串, 大幅降低序列化开销。
# ============================================================
_POOL_CTX: Dict[str, Any] = {}


def _pool_init(panel: Dict[str, pd.DataFrame], prices_panel: Dict[str, pd.DataFrame],
               rebal_period: int, min_warmup: int,
               ts_normalize_window: Optional[int],
               marketcap_proxy_lookback: Optional[int],
               parsimony: float,
               gpu_new_ctx: Optional[Dict[str, Any]] = None) -> None:
    """worker 进程初始化: 把共享面板与评价参数存入进程全局

    gpu_new_ctx: 阶段 P1#8 并发新增 (可选, 默认 None 兼容既有调用):
        新语义(mean_rank_ic)求值所需的 CPU 版上下文构建参数, 供
        _pool_eval_expr_new 懒构建 worker 内 CPU 求值上下文。
    """
    _POOL_CTX["panel"] = panel
    _POOL_CTX["prices_panel"] = prices_panel
    _POOL_CTX["rebal_period"] = rebal_period
    _POOL_CTX["min_warmup"] = min_warmup
    _POOL_CTX["ts_normalize_window"] = ts_normalize_window
    _POOL_CTX["marketcap_proxy_lookback"] = marketcap_proxy_lookback
    _POOL_CTX["parsimony"] = parsimony
    _POOL_CTX["gpu_new_ctx"] = gpu_new_ctx


def _pool_eval_expr(expr: str) -> Tuple[Optional[float], Optional[Dict]]:
    """worker 任务: 用进程全局面板评估单个表达式 (返回可 pickle 的轻量结果)"""
    try:
        fit, res = fitness_expr(
            expr, _POOL_CTX["panel"], _POOL_CTX["prices_panel"],
            _POOL_CTX["rebal_period"], _POOL_CTX["min_warmup"],
            _POOL_CTX["ts_normalize_window"], _POOL_CTX["marketcap_proxy_lookback"],
            _POOL_CTX["parsimony"],
        )
    except Exception:
        return None, None
    # res 里含 DataFrame (layered 等), 主进程只需标量/轻量字段; 简化返回
    return fit, (res if res else None)


# ============================================================
# 阶段 P1#8 GPU 与进程池并发: 回退组新语义 worker
# ============================================================
# 并发时回退组(字符串/不可 GPU 编译个体)在进程池内用与 _eval_one_gpu fallback
# 完全同口径的 mean_rank_ic 求值, 保证同一代内所有个体适应度语义一致
# (不能复用旧 fitness_expr, 否则 warm 个体口径与 GPU 组不同, 破坏进化)。
_POOL_GPU_NEW: Dict[str, Any] = {}


def _pool_build_gpu_new(ctx: Dict[str, Any]) -> None:
    """懒构建 worker 内的 CPU 版新语义求值上下文 (TensorPanel + target/mask/mc/style)

    与主进程 _gpu_ctx 初始化对齐: device="cpu" 但 dtype 保持 float32 (对齐 CUDA 分支
    _eval_one_gpu fallback 的 ctx["target"].dtype), 保证并发结果与主线程同口径。
    """
    import torch as _t
    from lib.factor_gpu_evaluator import TensorPanel
    dtype = _t.float32 if str(ctx.get("dtype", "float32")) == "float32" else _t.float64
    gpu_panel = TensorPanel.from_panel(_POOL_CTX["panel"], fields=ctx["fields"],
                                       device="cpu", dtype=dtype)
    g = {
        "panel": _POOL_CTX["panel"],
        "dates": gpu_panel.dates,
        "symbols": gpu_panel.symbols,
        "target": gpu_panel.future_returns(int(ctx["rebal_period"])),
        "mask": gpu_panel._global_mask(gpu_panel.values),
        "mc_proxy": gpu_panel.marketcap_proxy(int(ctx["marketcap_proxy_lookback"]))
            if ctx.get("marketcap_proxy_lookback") else None,
        "style_proxy": None,
        "dtype": dtype,
        "fitness_mode": ctx.get("fitness_mode", "rank_ic"),
    }
    if ctx.get("neutralize_styles"):
        g["style_proxy"] = gpu_panel.style_proxy(
            mc_lookback=ctx.get("marketcap_proxy_lookback"),
            ret_window=int((ctx.get("style_cfg") or {}).get("ret_window", 20)),
            vol_window=int((ctx.get("style_cfg") or {}).get("vol_window", 20)),
            use_turnover=bool((ctx.get("style_cfg") or {}).get("use_turnover", True)),
            use_industry=bool((ctx.get("style_cfg") or {}).get("use_industry", True)),
            industry_map=(ctx.get("style_cfg") or {}).get("industry_map"),
        )
    _POOL_GPU_NEW.update(g)


def _pool_eval_expr_new(expr: str) -> Tuple[Optional[float], Optional[Dict]]:
    """worker 任务: 新语义 (mean_rank_ic) 求值单个表达式

    与 _eval_one_gpu 的 fallback 分支同口径 (evaluate_expression + 重排 +
    float32 张量 + mean_rank_ic); GPU 上下文缺失时退回旧 worker _pool_eval_expr。
    """
    try:
        ctx = _POOL_CTX.get("gpu_new_ctx")
        if ctx is None:
            return _pool_eval_expr(expr)
        if not _POOL_GPU_NEW:
            _pool_build_gpu_new(ctx)
        import torch as _t
        from lib.factor_engine import evaluate_expression
        from lib.factor_gpu_evaluator import mean_rank_ic
        g = _POOL_GPU_NEW
        fv = evaluate_expression(expr, g["panel"])
        if fv is None or len(fv) == 0:
            return None, None
        wide = fv.reindex(index=g["dates"], columns=g["symbols"])
        f = _t.as_tensor(wide.to_numpy(dtype=np.float64),
                         dtype=g["dtype"], device="cpu")
        fit = mean_rank_ic(f, g["target"], g["mask"], g["mc_proxy"],
                           g["style_proxy"], g["fitness_mode"])
        if not np.isfinite(fit):
            return None, None
        return (abs(fit) - expr_length_penalty(expr, _POOL_CTX["parsimony"]),
                {"expr": expr, "rank_ic_mean": float(fit)})
    except Exception:
        return None, None


# ============================================================
# 五、进化主循环 (参照 QuantGplearn genetic.py 结构)
# ============================================================

# ---- 阶段5.2 #7 PCA-QD 多样性辅助 (来源 AutoAlpha, arXiv:2002.08245) ----
# AutoAlpha 的 Quality-Diversity: 因子"行为"相似度 = 逐日截面相关均值 sim(i,j)=mean_t corr(a_i,a_j);
# 用 PCA 把每个因子的值矩阵 [T,N] 压缩为主成分 score 时序(复杂度 O(N)->O(pT)), 新因子与"档案库"
# 中已发现 alpha 相似度过高则降权/拒绝。本实现据此把 Jaccard token 新颖性升级为 PCA 行为空间距离。


def _factor_behavior_desc(f) -> np.ndarray:
    """把因子值矩阵 f [T,N] 压缩为行为描述子向量 (AutoAlpha 主成分 score 时序)

    对 f 做列中心化(去截面均值)后取前 _PCA_QD_P 个主成分的时间 score 时序 [T] 各一,
    按行(日期)降采样为 _PCA_QD_BINS 段均值, 拼接成 [_PCA_QD_BINS*_PCA_QD_P] 向量。
    只依赖 torch 张量 SVD, 无需 sklearn; NaN 按截面跳过。
    """
    _PCA_QD_P = 3     # 主成分个数
    _PCA_QD_BINS = 8  # 日期降采样段数
    # 阶段 P3#9: SVD 前对 T/N 降采样上限 (仅 PCA-QD 开启时生效, 控制单树 SVD 开销;
    # 行为描述子只刻画"时序形态", 时间降采样不改变主成分方向, 与 BINS 分段语义一致)
    _PCA_QD_MAX_T = 60
    _PCA_QD_MAX_N = 200
    torch = _torch_mod()
    T, N = int(f.shape[0]), int(f.shape[1])
    if T < 4 or N < 3:
        # 面板过小: 回退为逐日均值/非空占比的简单描述子, 保证有值可算
        fn = np.asarray(f.detach().cpu().numpy())
        m = np.isfinite(fn)
        mean_s = np.where(m.sum(1) > 0, np.nanmean(fn, axis=1), 0.0)
        return np.concatenate([mean_s, (m.sum(1) / max(1, N))])
    # 逐列(股票)中心化: 消除截面绝对水平, 使主成分捕捉"时序形态"而非量纲
    fm = f.clone()
    cnt = torch.isfinite(fm).sum(dim=1, keepdim=True).clamp_min(1)
    mu = torch.where(torch.isfinite(fm), fm, torch.zeros_like(fm)).sum(dim=1, keepdim=True) / cnt
    fc = torch.where(torch.isfinite(fm), fm - mu, torch.zeros_like(fm))
    # 阶段 P3#9: SVD 前时间/截面降采样 (等间隔抽样, 保留时序形态, 大幅降 SVD 开销)
    if T > _PCA_QD_MAX_T:
        tidx = np.floor(np.linspace(0, T - 1, _PCA_QD_MAX_T)).astype(int)
        fc = fc[tidx]
        T = int(fc.shape[0])
    if N > _PCA_QD_MAX_N:
        nidx = np.floor(np.linspace(0, N - 1, _PCA_QD_MAX_N)).astype(int)
        fc = fc[:, nidx]
        N = int(fc.shape[1])
    # 缺失格记 0, 不影响主成分方向; SVD: fc = U S V^T, U 列为时间基 -> score = U*S
    try:
        u, ss, _ = torch.linalg.svd(fc, full_matrices=False)
    except Exception:
        u, ss, _ = torch.svd(fc)
    p = min(_PCA_QD_P, int(ss.shape[0]))
    score_t = u[:, :p] * ss[:p].unsqueeze(0)          # [T, p] 主成分时间 score
    # 按日期降采样为 BINS 段均值
    B = _PCA_QD_BINS
    seg = np.linspace(0, T, B + 1).astype(int)
    cols = []
    for i in range(B):
        a, b = seg[i], max(seg[i] + 1, seg[i + 1])
        cols.append(score_t[a:b].mean(dim=0).cpu().numpy())
    return np.concatenate(cols) if cols else np.zeros(p, dtype=np.float64)


def _fit_pca_projection(X: np.ndarray, n_comp: int) -> Optional[np.ndarray]:
    """对 [n, d] 描述子矩阵做 PCA (numpy SVD, 去均值), 返回投影后 [n, n_comp]"""
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[0] < 3 or X.shape[1] < 1:
        return None
    Xc = X - X.mean(axis=0, keepdims=True)
    n_comp = max(1, min(n_comp, X.shape[0] - 1, X.shape[1]))
    try:
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        return U[:, :n_comp] * S[:n_comp]
    except Exception:
        return None


def _knn_novelty(proj: np.ndarray, k: int = 5) -> np.ndarray:
    """PCA 空间中到 k 近邻的平均距离 (排除自身), 按全局最大距离归一化到 [0,1]"""
    n = proj.shape[0]
    if n < 2:
        return np.zeros(n, dtype=np.float64)
    k = max(1, min(k, n - 1))
    # 欧氏距离矩阵 (批内足够小, 直接广播)
    diff = proj[:, None, :] - proj[None, :, :]
    dist = np.sqrt(np.nansum(diff ** 2, axis=2))
    dist[np.arange(n), np.arange(n)] = np.inf          # 排除自身
    knn = np.sort(dist, axis=1)[:, :k]
    novelty = knn.mean(axis=1)
    mx = float(np.nanmax(novelty)) if n > 1 else 0.0
    if mx > 0 and np.isfinite(mx):
        novelty = novelty / mx
    return np.asarray(novelty, dtype=np.float64)


def _torch_mod():
    """惰性导入 torch (与 factor_gpu_evaluator 同款, 避免顶层 import 依赖)"""
    global _TORCH_MOD
    if _TORCH_MOD is None:
        import torch as _m
        _TORCH_MOD = _m
    return _TORCH_MOD


_TORCH_MOD = None


def evolve(
    panel: Dict[str, pd.DataFrame],
    prices_panel: Dict[str, pd.DataFrame],
    population_size: int = 150,
    generations: int = 40,
    max_depth: int = 4,
    rebal_period: int = 21,
    min_warmup: int = 130,
    ts_normalize_window: Optional[int] = None,
    marketcap_proxy_lookback: Optional[int] = None,
    tournament_size: int = 5,
    p_crossover: float = 0.9,
    p_subtree_mutation: float = 0.02,
    p_hoist_mutation: float = 0.01,
    p_point_mutation: float = 0.02,
    parsimony: float = 0.001,
    max_length: int = 32,
    warm_start_formulas: Optional[List[str]] = None,
    warm_start_trees: Optional[List[Dict]] = None,
    warm_start_ratio: float = 0.3,
    max_exprs_seen: int = 40000,
    early_stop_gens: int = 5,
    filter_bare_fields: bool = True,
    corr_thresh: float = 0.8,
    space_level: str = "L0",
    diversity_weight: float = 0.02,
    n_jobs: int = 1,
    progress_cb: Optional[Callable[[int, Dict[str, Any]], None]] = None,
    random_state: Optional[int] = None,
    verbose: bool = False,
    use_gpu_tensor: bool = False,
    gpu_streams: int = 2,
    val_panel: Optional[Dict[str, pd.DataFrame]] = None,
    val_prices_panel: Optional[Dict[str, pd.DataFrame]] = None,
    ortho_mode: bool = False,
    min_incremental_ic: float = 0.01,
    neutralize_styles: bool = False,
    style_cfg: Optional[Dict[str, Any]] = None,
    pca_qd: bool = False,
    replacement_thresh: Optional[float] = None,
    fitness_mode: str = "rank_ic",
    max_samples: Optional[float] = None,
) -> Dict[str, Any]:
    """GP 进化主循环

    panel:        {stock_code: DataFrame} 用于 evaluate_expression
    prices_panel: {stock_code: DataFrame} 用于 run_ic_timeseries_panel (未来收益)
    warm_start_formulas: 库内因子 formula 列表 (注入初始种群, 如 rsi(14)/ts_Mean(Close,5))
    marketcap_proxy_lookback: 点-in-time 市值中性化窗口 (None=不中性化, 传入 fitness_expr)
    filter_bare_fields: 收尾过滤纯裸字段表达式 (仅含字段/常数, 无算子, 无增量信息; 默认开启)
    corr_thresh: 候选去冗余阈值 (复刻 QuantGplearn tolerable_corr; |corr|>阈值保留高 IC 项; None/<=0=关闭)
    space_level: 搜索空间层级 ("L0"=默认受限子集, "L1"=追加新时序算子, "L2"=追加基类叶子(参数化基类+固定参数基类))
    diversity_weight: 多样性奖励权重 (阶段3.2; 锦标赛选择时 调整适应度 = 原始适应度 + 权重*新颖性得分,
        鼓励探索不同算子组合, 缓解早熟收敛/同质化; 权重随代数线性衰减)
    n_jobs: 并行评估进程数 (阶段3.3; 默认1=串行; >1时用 ProcessPoolExecutor 批量评估无缓存表达式,
        Windows spawn 下需 __main__ 保护, 池创建失败自动回退串行; 种群>60时效果明显)
    progress_cb: 每代完成后的进度回调 (gen, stats_dict), 用于 SSE 流式进度 (阶段3.3); None=不回调
    val_panel / val_prices_panel: 验证段面板 (阶段5.1 三重分段; 提供后早停/多样性衰减判断
        迁移到验证段, 避免超参选择只盯训练段; None 时沿用训练段指标, 与历史行为一致)
    ortho_mode / min_incremental_ic: 候选去冗余残差正交化 (阶段5.2 #5, 来源
        Auto-Alpha-Finding; 透传 dedup_by_corr; False 时零行为变化)
    neutralize_styles / style_cfg: 多因子风格中性化 (阶段5.2 #6, 来源华泰证券 GP
        金工系列21)。True 时 GPU 求值改为"行业哑变量 + 过去收益 + 换手 + 波动 +
        ln市值 多列回归取残差" (style_cfg 传构建参数, 含 industry_map); False 时
        按 marketcap_proxy_lookback 单市值中性化, 与历史行为一致。
    pca_qd: 阶段5.2 #7 PCA-QD 多样性引导 (来源 AutoAlpha, arXiv:2002.08245)。
        True 时把 Jaccard token 新颖性奖励升级为"PCA 特征空间距离奖励"(新奇性搜索):
        每个因子值矩阵 [T,N] 用主成分 score 时序压缩为行为描述子, 每代对种群描述子做
        PCA 投影, 与跨代档案库求 k 近邻平均距离作为新颖性, 进入锦标赛选择 (同 Jaccard
        钩子, 共享 gen_div_weight); False 时沿用 Jaccard, 与历史行为一致。
    fitness_mode: 阶段5.2 #9 适应度目标 (来源 QuantGplearn tensor_fitness / GinkGO):
        "rank_ic"(默认, 原行为) / "rank_icir"(IC均值/IC标准差, 抗噪) /
        "long_short_sharpe"(多空组合夏普, top/bottom 30% 组合净收益夏普)。
    replacement_thresh: 阶段5.2 #8 replacement 防早熟 (来源 AutoAlpha, arXiv:2002.08245)。
        None(默认)/<=0 关闭; 启用时种群更替段对"新生个体"与"已入下一代个体"做 token
        Jaccard 相似度检查, 相似度 >= 阈值的同质个体被变异再生 (替换为多样化变体),
        避免种群被少数高适应度同质基因统治导致早熟收敛 (0.9 对齐 AutoAlpha 相似度红线)。
    max_samples: 阶段 P3 数据降采样 (可选, 对齐 QuantGplearn 按比例抽样子样本求值提速)。
        None/<=0/>=1 关闭; 0<比例<1 时对股票维 N 按比例随机抽样 (保留每只股票完整时间序列,
        滚动时序算子/截面算子语义不受影响), 仅作用于搜索阶段, OOS/WF 复核仍用全量面板。
    max_length: 阶段 P4 节点数上限 (对齐 QuantGplearn max_length, 默认 32)。
        交叉/变异生成的子代节点数 (tree_size) 超过该值时回退为复制父代,
        防止 GP 生成超长过拟合因子 (如深度 13/节点 36 的复合因子);
        <=0 关闭 (不限制)。
    """
    rng = random.Random(random_state)
    space = SPACE_LEVELS.get(space_level, SPACE_L0)
    _fitness_mode = fitness_mode if fitness_mode in ("rank_icir", "long_short_sharpe") else "rank_ic"

    # ---- 阶段 P3: max_samples 数据降采样 (可选, 仅影响搜索阶段, OOS/WF 复核用全量面板) ----
    # 面板 [T,N,F] 中滚动时序算子要求时间连续、截面算子要求每期有横截面, 故对股票维 N
    # 按比例随机抽样 (保留每只股票完整时间序列), 直接降低 T*N 求值开销。
    if max_samples is not None and 0.0 < float(max_samples) < 1.0:
        _stocks = list(panel.keys())
        _n_keep = max(1, int(round(len(_stocks) * float(max_samples))))
        _rng = random.Random((random_state if random_state is not None else 0) + 987654)
        _keep = set(_rng.sample(_stocks, _n_keep))
        panel = {k: v for k, v in panel.items() if k in _keep}
        if prices_panel is not None:
            prices_panel = {k: v for k, v in prices_panel.items() if k in _keep}
        if val_panel is not None:
            val_panel = {k: v for k, v in val_panel.items() if k in _keep}
        if val_prices_panel is not None:
            val_prices_panel = {k: v for k, v in val_prices_panel.items() if k in _keep}

    # ---- 初始化种群 (随机 + Warm-Start 注入) ----
    population: List[Dict] = []
    warm_count = 0
    if warm_start_trees:
        # 阶段5.1.1: 注入"已解析的 dict 树" (与随机树同构, 非 _warm 原子) —— 可 GPU 整树
        # 求值、可被交叉/变异拆解重组、可作 donor 嫁接, 完整参与遗传算法
        warm_count = int(population_size * warm_start_ratio)
        for tree in list(warm_start_trees)[:warm_count]:
            # 阶段 P4: 注入前按 max_length 过滤超限基因 (防止超长因子以精英保留存活)
            if max_length and max_length > 0 and tree_size(tree) > max_length:
                continue
            population.append(copy_tree(tree))
    elif warm_start_formulas:
        warm_count = int(population_size * warm_start_ratio)
        for formula in list(warm_start_formulas)[:warm_count]:
            # 阶段 P4: 注入前按 max_length 过滤超限基因 (解析公式统计节点数)
            if max_length and max_length > 0:
                _ct = formula_to_tree(formula)
                if _ct is not None and tree_size(_ct) > max_length:
                    continue
            # 以公式字符串作为"叶子"注入 (变异时会被替换/交叉时可被拆)
            population.append({"t": "field", "name": formula, "_warm": True})
    while len(population) < population_size:
        population.append(random_tree(rng, max_depth, space))

    # 已见表达式集合 (去重) 与 fitness 缓存 (进化中大量近亲个体可复用)
    seen_exprs: set = set()
    fitness_cache: Dict[str, Tuple[Optional[float], Optional[Dict]]] = {}
    # 阶段 P2#7: GPU 编译缓存 (expr_hash -> compiled callable), 同一表达式跨代/
    # 同代内(交叉克隆/Warm 注入)复用编译结果, 省掉重复整树编译。
    _compile_cache: Dict[str, Callable[[], Any]] = {}
    for ind in population:
        expr = tree_to_str(ind)
        if ind.get("_warm"):
            expr = ind["name"]
        if expr_hash(expr) not in seen_exprs:
            seen_exprs.add(expr_hash(expr))

    # ---- 评估 (串行/并行) ----
    # 阶段 P1#8: 进程池创建移至 GPU 上下文初始化之后, 以便并发时 worker 持有
    # 新语义(mean_rank_ic)的 CPU 求值参数 (回退组与 GPU 组同口径)。
    _executor = None
    _use_parallel = False

    # ---- GPU 整树张量评估上下文 (use_gpu_tensor=True 时启用, 阶段4.1) ----
    # 适应度切换为 QuantGplearn 语义: mean_rank_ic (全样本逐日截面 Spearman RankIC 均值)
    # + normalize_by_day (每日截面zscore); 市值中性化(问题A修复)按 marketcap_proxy_lookback 可选。
    # 搜索空间内全部算子均已 GPU 化; 仅 warm-start 注入的库内因子公式(字符串, tree=None)
    # 或库内公式含 GPU 未覆盖字段/算子时 fallback 到 evaluate_expression + 新语义。
    _gpu_ctx: Optional[Dict[str, Any]] = None
    _GPU_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount", "VWAP",
                   "Turnover", "IdioRet", "Value", "TotalRet"]
    if use_gpu_tensor:
        try:
            from lib.factor_gpu_evaluator import (
                TensorPanel, PanelTensorCompiler, gpu_supported, mean_rank_ic,
            )
            import torch as _t
            # 数据真正上 GPU: 此前 from_panel 未传 device, 面板建在 CPU 上,
            # "GPU 加速"实为 torch CPU 向量化, CUDA 完全未使用 (阶段4.1 修复);
            # CUDA 不可用时回退 CPU (与原行为一致)。
            _gpu_device = "cuda" if _t.cuda.is_available() else "cpu"
            _gpu_panel = TensorPanel.from_panel(panel, fields=_GPU_FIELDS, device=_gpu_device)
            _gpu_compiler = PanelTensorCompiler(_gpu_panel)
            _gpu_target = _gpu_panel.future_returns(rebal_period)
            _gpu_mask = _gpu_panel._global_mask(_gpu_panel.values)
            _gpu_mc = _gpu_panel.marketcap_proxy(marketcap_proxy_lookback) \
                if marketcap_proxy_lookback else None
            # 阶段5.2 #6 多因子风格中性化 (华泰): 构建 [T,N,K] 风格矩阵, 优先于单市值
            _gpu_style = None
            if neutralize_styles:
                _gpu_style = _gpu_panel.style_proxy(
                    mc_lookback=marketcap_proxy_lookback,
                    ret_window=int((style_cfg or {}).get("ret_window", 20)),
                    vol_window=int((style_cfg or {}).get("vol_window", 20)),
                    use_turnover=bool((style_cfg or {}).get("use_turnover", True)),
                    use_industry=bool((style_cfg or {}).get("use_industry", True)),
                    industry_map=(style_cfg or {}).get("industry_map"),
                )
            _gpu_ctx = {
                "compiler": _gpu_compiler, "target": _gpu_target,
                "mask": _gpu_mask, "mc_proxy": _gpu_mc, "style_proxy": _gpu_style,
                "dates": _gpu_panel.dates, "symbols": _gpu_panel.symbols,
                "gpu_supported": gpu_supported, "mean_rank_ic": mean_rank_ic,
            }
        except Exception:
            _gpu_ctx = None  # GPU 求值器初始化失败回退原路径

    # 阶段 P1#8: 构建进程池 (n_jobs>1 时)。initializer 传入 gpu_new_ctx, 供回退组
    # 在新语义 worker(_pool_eval_expr_new)中懒构建 CPU 求值上下文; 创建失败回退串行。
    _gpu_new_ctx: Optional[Dict[str, Any]] = None
    if use_gpu_tensor and _gpu_ctx is not None:
        _gpu_new_ctx = {
            "fields": _GPU_FIELDS,
            "dtype": str(_gpu_panel.values.dtype),   # float32 (CUDA 默认) 或 float64 (CPU)
            "rebal_period": rebal_period,
            "marketcap_proxy_lookback": marketcap_proxy_lookback,
            "neutralize_styles": neutralize_styles,
            "style_cfg": style_cfg,
            "fitness_mode": _fitness_mode,
        }
    if n_jobs and n_jobs > 1:
        try:
            from concurrent.futures import ProcessPoolExecutor
            _executor = ProcessPoolExecutor(
                max_workers=n_jobs,
                initializer=_pool_init,
                initargs=(panel, prices_panel, rebal_period, min_warmup,
                          ts_normalize_window, marketcap_proxy_lookback, parsimony,
                          _gpu_new_ctx),
            )
            _use_parallel = True
        except Exception:
            _executor = None
            _use_parallel = False

    # 阶段5.2 #7 PCA-QD: 行为描述子缓存 (expr_hash -> np.ndarray) 与启用开关
    _pca_qd = bool(pca_qd)
    _behav_cache: Dict[str, np.ndarray] = {}
    _pca_archive: Dict[str, np.ndarray] = {}   # 跨代档案库: 记录已探索行为 (expr_hash -> 描述子)

    def _eval_one_gpu(expr: str, tree: Optional[Dict]) -> Tuple[Optional[float], Optional[Dict]]:
        """GPU 求值器: 整树 torch 求值 / fallback evaluate_expression, 统一新语义 mean_rank_ic"""
        try:
            from lib.factor_engine import evaluate_expression, _is_technical_ts_expression
            import torch as _t
            ctx = _gpu_ctx
            # 阶段6.3 加速: GPU 求值无需梯度, 关闭 autograd 免构建计算图 (对齐 QuantGplearn no_grad)
            with _t.no_grad():
                if tree is not None and ctx["gpu_supported"](tree):
                    # 阶段 P2#7: 复用已编译求值函数, 避免同一表达式重复整树编译
                    h = expr_hash(expr)
                    f_compiled = _compile_cache.get(h)
                    if f_compiled is None:
                        f_compiled = ctx["compiler"].compile(tree)
                        _compile_cache[h] = f_compiled
                    f = f_compiled()
                else:
                    fv = evaluate_expression(expr, panel)
                    wide = fv.reindex(index=ctx["dates"], columns=ctx["symbols"])
                    _arr = wide.to_numpy(dtype=np.float64)
                    if not _arr.flags.writeable:
                        _arr = _arr.copy()  # PyTorch 张量要求可写
                    f = _t.as_tensor(_arr,
                                     dtype=ctx["target"].dtype,
                                     device=ctx["target"].device)
                # 非空率硬门槛 (与 CPU fitness_expr 一致, 0.2): 除零等病态公式大面积
                # NaN/Inf, 有效截面过少会虚高 RankIC, 直接判无效 (RankIC 假相关修复配套)
                if float(_t.isfinite(f).sum().item()) / float(f.numel()) < 0.2:
                    return None, None
                fitness = ctx["mean_rank_ic"](f, ctx["target"], ctx["mask"],
                                              ctx["mc_proxy"], ctx.get("style_proxy"),
                                              _fitness_mode,
                                              ts_normalize_window=(ts_normalize_window
                                                                   if _is_technical_ts_expression(expr) else None))
                # 阶段5.2 #7 PCA-QD: 评估时免费提取行为描述子 (缓存供多样性计算复用, 避免重复求值)
                if _pca_qd:
                    try:
                        _behav_cache[expr_hash(expr)] = _factor_behavior_desc(f)
                    except Exception:
                        pass
                if not np.isfinite(fitness):
                    return None, None
                return (abs(fitness) - expr_length_penalty(expr, parsimony, tree),
                        {"expr": expr, "rank_ic_mean": float(fitness)})
        except Exception:
            return None, None

    def _gpu_forward(expr: str, tree: Dict) -> Optional[Any]:
        """GPU 树间多流并发: 仅前向整树张量求值 (compile 缓存复用 + 闭包执行), 无同步

        返回 [T,N] 因子张量; 编译/求值失败返回 None (与 _eval_one_gpu 异常语义一致)。
        前向是纯张量运算 (无 .item()/numpy), 可在指定 CUDA 流上异步执行,
        使多棵树的 kernel 交错运行 (树间并行, 无需深度对齐/批量化)。
        """
        try:
            import torch as _t
            ctx = _gpu_ctx
            with _t.no_grad():
                h = expr_hash(expr)
                f_compiled = _compile_cache.get(h)
                if f_compiled is None:
                    f_compiled = ctx["compiler"].compile(tree)
                    _compile_cache[h] = f_compiled
                return f_compiled()
        except Exception:
            return None

    def _gpu_fitness(expr: str, f: Optional[Any],
                     tree: Optional[Dict] = None) -> Tuple[Optional[float], Optional[Dict]]:
        """GPU 树间多流并发: 仅适应度 (mean_rank_ic + 惩罚 + 行为描述子), 含同步点

        前向已完成 (f 就绪张量); 此处为标量提取/描述子取 numpy 等同步点, 逐棵调用。
        f 为 None 时返回 (None, None) (前向失败个体, 与原异常语义一致)。
        """
        if f is None:
            return None, None
        try:
            import torch as _t
            from lib.factor_engine import _is_technical_ts_expression
            ctx = _gpu_ctx
            with _t.no_grad():
                # 非空率硬门槛 (与 CPU fitness_expr 一致, 0.2): 除零等病态公式大面积
                # NaN/Inf, 有效截面过少会虚高 RankIC, 直接判无效 (RankIC 假相关修复配套)
                if float(_t.isfinite(f).sum().item()) / float(f.numel()) < 0.2:
                    return None, None
                fitness = ctx["mean_rank_ic"](f, ctx["target"], ctx["mask"],
                                              ctx["mc_proxy"], ctx.get("style_proxy"),
                                              _fitness_mode,
                                              ts_normalize_window=(ts_normalize_window
                                                                   if _is_technical_ts_expression(expr) else None))
                if _pca_qd:
                    try:
                        _behav_cache[expr_hash(expr)] = _factor_behavior_desc(f)
                    except Exception:
                        pass
                if not np.isfinite(fitness):
                    return None, None
                return (abs(fitness) - expr_length_penalty(expr, parsimony, tree),
                        {"expr": expr, "rank_ic_mean": float(fitness)})
        except Exception:
            return None, None

    def _eval_all(pop: List[Dict]) -> List[Optional[Tuple[Optional[float], Optional[Dict]]]]:
        # nonlocal: 并行中途失败时回退串行, 需改写外层 _use_parallel (否则视为局部变量)
        nonlocal _use_parallel
        # 先收集所有未缓存表达式 (warm 个体与近亲个体命中缓存, 避免重复评估)
        results: List[Optional[Tuple[Optional[float], Optional[Dict]]]] = []
        todo_exprs: List[str] = []
        todo_idx: List[int] = []
        todo_trees: List[Optional[Dict]] = []
        for idx, ind in enumerate(pop):
            if ind.get("_warm"):
                expr = ind["name"]
                tree = None
            else:
                expr = tree_to_str(ind)
                tree = ind
            h = expr_hash(expr)
            if h in fitness_cache:
                results.append(fitness_cache[h])
            else:
                results.append(None)
                todo_exprs.append(expr)
                todo_idx.append(idx)
                todo_trees.append(tree)
        if not todo_exprs:
            return results  # type: ignore
        # ---- GPU 整树求值 (新语义 mean_rank_ic; 未GPU化表达式 fallback evaluate_expression) ----
        if _gpu_ctx is not None and len(todo_exprs) >= 3:
            # 阶段 P1#8: 拆分为"可 GPU 组"(主线程整树求值) 与"回退组"
            # (进程池新语义 worker 并发 / 进程池不可用时主线程兜底)。
            gpu_idx: List[int] = []
            gpu_exprs: List[str] = []
            gpu_trees: List[Dict] = []
            fb_idx: List[int] = []
            fb_exprs: List[str] = []
            fb_trees: List[Optional[Dict]] = []
            for idx, expr, tree in zip(todo_idx, todo_exprs, todo_trees):
                if tree is not None and _gpu_ctx["gpu_supported"](tree):
                    gpu_idx.append(idx)
                    gpu_exprs.append(expr)
                    gpu_trees.append(tree)
                else:
                    fb_idx.append(idx)
                    fb_exprs.append(expr)
                    fb_trees.append(tree)
            # 回退组先异步提交进程池 (新语义 worker, 与 GPU 组并发执行)
            fb_futures: Optional[Dict[str, Any]] = None
            if fb_exprs and _use_parallel and _executor is not None:
                try:
                    fb_futures = {e: _executor.submit(_pool_eval_expr_new, e)
                                  for e in fb_exprs}
                except Exception:
                    fb_futures = None
                    _use_parallel = False
            # GPU 组主线程整树求值 (GPU 核执行, 与进程池回退组的 CPU 计算并发)
            # 阶段 P2#8: 树间多流并发 (CUDA stream, 不 pad/不对齐深度; 多棵树 kernel 交错)。
            # 前向段批量异步提交到 gpu_streams 个流 (无同步, kernel 交错执行);
            # 适应度段逐棵取标量 (每棵 .item() 只等本流尾部, 其余流继续);
            # 分波 W=2*gpu_streams 限流, 控制整代 [T,N] 结果张量驻留显存上界。
            if _gpu_panel.device.type == "cuda" and gpu_streams >= 2:
                import torch as _t
                streams = [_t.cuda.Stream() for _ in range(gpu_streams)]
                W = max(gpu_streams, min(2 * gpu_streams, len(gpu_trees)))
                gpu_all = list(zip(gpu_idx, gpu_exprs, gpu_trees))
                for base in range(0, len(gpu_all), W):
                    seg = gpu_all[base:base + W]
                    fwd: List[Optional[Any]] = [None] * len(seg)
                    # 阶段1: 本波所有树前向异步提交到各自流 (无同步, kernel 交错)
                    for j, (idx, expr, tree) in enumerate(seg):
                        s = streams[j % gpu_streams]
                        with _t.cuda.stream(s):
                            fwd[j] = _gpu_forward(expr, tree)
                    # 阶段2: 本波各树适应度 (逐棵 .item() 只等本流尾部, 其余流继续)
                    for j, (idx, expr, tree) in enumerate(seg):
                        with _t.cuda.stream(streams[j % gpu_streams]):
                            pair = _gpu_fitness(expr, fwd[j], tree)
                        fitness_cache[expr_hash(expr)] = pair
                        results[idx] = pair
            else:
                # 原串行路径 (CPU 设备 / gpu_streams<2): 逐棵整树求值兜底
                for idx, expr, tree in zip(gpu_idx, gpu_exprs, gpu_trees):
                    pair = _eval_one_gpu(expr, tree)
                    fitness_cache[expr_hash(expr)] = pair
                    results[idx] = pair
            # 收集回退组结果
            if fb_futures is not None:
                for idx, expr in zip(fb_idx, fb_exprs):
                    try:
                        pair = fb_futures[expr].result()
                    except Exception:
                        pair = (None, None)
                    fitness_cache[expr_hash(expr)] = pair
                    results[idx] = pair
            else:
                for idx, expr, tree in zip(fb_idx, fb_exprs, fb_trees):
                    pair = _eval_one_gpu(expr, tree)
                    fitness_cache[expr_hash(expr)] = pair
                    results[idx] = pair
            return results  # type: ignore
        # ---- 并行批量评估 (进程内各自算 fitness_expr, 返回 (fit, result)) ----
        if _use_parallel and _executor is not None:
            try:
                futures = list(_executor.map(_pool_eval_expr, todo_exprs))
                for idx, expr, (fit, res) in zip(todo_idx, todo_exprs, futures):
                    pair = (fit, res)
                    fitness_cache[expr_hash(expr)] = pair
                    results[idx] = pair
                return results  # type: ignore
            except Exception:
                # 并行中途失败: 未完成项回退串行
                _use_parallel = False
        for idx, expr in zip(todo_idx, todo_exprs):
            fit = fitness_expr(expr, panel, prices_panel,
                               rebal_period, min_warmup,
                               ts_normalize_window, marketcap_proxy_lookback,
                               parsimony)
            fitness_cache[expr_hash(expr)] = fit
            results[idx] = fit
        return results  # type: ignore

    # ---- 验证段评估 (阶段5.1 三重分段): 仅用于早停/多样性衰减判断 ----
    # 提供 val_panel 时, 每代对"当前最优个体"在验证段单独评估一次验证适应度,
    # 早停 no_improve 基于验证段最优更新, 避免超参/早停选择只盯训练段 (过拟合训练段)。
    # 不提供验证段时沿用训练段指标, 与历史行为完全一致。
    _val_ctx: Optional[Dict[str, Any]] = None
    _use_val = bool(val_panel and val_prices_panel)
    if _use_val:
        try:
            from lib.factor_gpu_evaluator import (
                TensorPanel, PanelTensorCompiler, gpu_supported, mean_rank_ic,
            )
            _val_panel = TensorPanel.from_panel(val_panel, fields=_GPU_FIELDS)
            _val_compiler = PanelTensorCompiler(_val_panel)
            _val_target = _val_panel.future_returns(rebal_period)
            _val_mask = _val_panel._global_mask(_val_panel.values)
            _val_mc = _val_panel.marketcap_proxy(marketcap_proxy_lookback) \
                if marketcap_proxy_lookback else None
            # 阶段5.2 #6 风格中性化 (验证段与训练段同口径)
            _val_style = None
            if neutralize_styles:
                _val_style = _val_panel.style_proxy(
                    mc_lookback=marketcap_proxy_lookback,
                    ret_window=int((style_cfg or {}).get("ret_window", 20)),
                    vol_window=int((style_cfg or {}).get("vol_window", 20)),
                    use_turnover=bool((style_cfg or {}).get("use_turnover", True)),
                    use_industry=bool((style_cfg or {}).get("use_industry", True)),
                    industry_map=(style_cfg or {}).get("industry_map"),
                )
            _val_ctx = {
                "compiler": _val_compiler, "target": _val_target,
                "mask": _val_mask, "mc_proxy": _val_mc, "style_proxy": _val_style,
                "dates": _val_panel.dates, "symbols": _val_panel.symbols,
                "gpu_supported": gpu_supported, "mean_rank_ic": mean_rank_ic,
            }
        except Exception:
            _val_ctx = None  # 验证段 GPU 上下文初始化失败则回退训练段判断
    else:
        _val_ctx = None

    def _val_fitness(expr: str, tree: Optional[Dict]) -> Optional[float]:
        """在验证段对单个表达式求适应度 (验证段指标, 供早停判断)"""
        try:
            from lib.factor_engine import evaluate_expression
            import torch as _t
            ctx = _val_ctx
            if ctx is None:
                return None
            # 阶段6.3 加速: 验证段求值无需梯度, 关闭 autograd 免建计算图
            with _t.no_grad():
                if tree is not None and ctx["gpu_supported"](tree):
                    f = ctx["compiler"].compile(tree)()
                else:
                    fv = evaluate_expression(expr, val_panel)
                    wide = fv.reindex(index=ctx["dates"], columns=ctx["symbols"])
                    f = _t.as_tensor(wide.to_numpy(dtype=np.float64),
                                     dtype=ctx["target"].dtype,
                                     device=ctx["target"].device)
                fitness = ctx["mean_rank_ic"](f, ctx["target"], ctx["mask"],
                                              ctx["mc_proxy"], ctx.get("style_proxy"),
                                              _fitness_mode)
                if not np.isfinite(fitness):
                    return None
                return abs(fitness) - expr_length_penalty(expr, parsimony, tree)
        except Exception:
            return None

    best_overall: Tuple[Optional[float], Optional[str]] = (None, None)
    best_val_fit: Optional[float] = None  # 验证段全局最优 (三重分段早停依据)
    no_improve = 0
    no_improve_val = 0  # 验证段无改善代数 (阶段5.1 三重分段; 启用验证段时用于早停)
    evolution_curve: List[Dict] = []
    # 跨代候选池 (hall_of_fame): 每代收集高 fitness 个体 (按表达式去重),
    # 收尾时从中取多样候选, 避免只取最后一代 (收敛后同质化严重, 候选不足)
    hall_of_fame: Dict[str, Dict[str, Any]] = {}
    # 阶段5.2 #8 replacement 防早熟: 更替段同质个体替换计数 (供报告/SSE)
    replacement_count = 0

    # ---- 多样性奖励准备 ----
    # 多样性权重: 初始 = diversity_weight, 线性衰减到 0.25*diversity_weight
    # 在锦标赛选择中, 调整适应度 = 原始适应度 + diversity_weight * 新颖性得分
    # 新颖性 = 1 - 个体 token 集与种群其他个体的最大 Jaccard 相似度
    # (经验值 0.02: 原始适应度 ~0.05-0.15, 新颖性 ~0-0.3, 乘权重后 ~0-0.006, 小幅扰动)

    def _token_set(expr: str) -> set:
        """提取表达式的 token 集合 (标识符 + 数字, 用于 Jaccard 多样性计算)"""
        idents = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr))
        nums = set(str(int(float(x))) for x in re.findall(r"\d+", expr) if x.isdigit())
        # 排除通用字段名 (Close/Open 等太常见, 不贡献多样性信息)
        common = {"Close", "Open", "High", "Low", "Volume", "Amount", "VWAP", "Turnover",
                  "IdioRet", "Value", "TotalRet"}
        return (idents - common) | nums

    def _token_similarity(e1: str, e2: str) -> float:
        """Jaccard 相似度 = |交集| / |并集| (省略时返回0)"""
        s1, s2 = _token_set(e1), _token_set(e2)
        if not s1 and not s2:
            return 0.0
        union = s1 | s2
        if not union:
            return 0.0
        return len(s1 & s2) / len(union)

    def _diversity_scores(pop: List[Dict]) -> List[float]:
        """对每个个体计算新颖性得分: 1 - 与种群其他个体的最大 Jaccard 相似度"""
        exprs = []
        for ind in pop:
            if ind.get("_warm"):
                exprs.append(ind["name"])
            else:
                exprs.append(tree_to_str(ind))
        scores = []
        n = len(exprs)
        # 用随机子集加速 (种群 > 50 时, 只对比 30 个随机样本)
        sample_size = min(30, n)
        for i in range(n):
            # 选其他个体 (排除自身)
            others = [j for j in rng.sample(range(n), min(sample_size, n - 1)) if j != i][:sample_size]
            max_sim = max((_token_similarity(exprs[i], exprs[j]) for j in others), default=0.0)
            scores.append(1.0 - max_sim)
        return scores

    # ---- 阶段5.2 #7 PCA-QD: 行为描述子补算 + PCA 特征空间新颖性 (新奇性搜索) ----
    # AutoAlpha 用主成分压缩因子值矩阵, 新因子相对"档案库"已探索行为的相似度判多样性;
    # 本实现: 描述子已在 GPU 评估时免费缓存(_eval_one_gpu), 此处只补算缓存未覆盖个体
    # (warm 字符串/命中 fitness_cache 的个体), 每代对种群+档案库描述子做 PCA 投影,
    # 以 k 近邻平均距离(PCA 特征空间距离)作为新颖性, 归一化到 [0,1] 进入锦标赛选择钩子。
    _PCA_QD_ARCHIVE_MAX = 300  # 档案库上限 (超限时按"最旧优先"淘汰)
    _PCA_QD_N_COMP = 6         # PCA 投影维数
    _PCA_QD_KNN = 5            # k 近邻数

    def _collect_behavior_descs(pop: List[Dict]) -> None:
        """为种群中缺行为描述子的个体补算描述子 (复用 GPU 编译, 未覆盖时用 evaluate_expression)"""
        todo = []
        for ind in pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            h = expr_hash(expr)
            if h in _behav_cache:
                continue
            todo.append((h, expr, None if ind.get("_warm") else ind))
        if not todo:
            return
        import torch as _t
        for h, expr, tree in todo:
            try:
                if _gpu_ctx is not None:
                    if tree is not None and _gpu_ctx["gpu_supported"](tree):
                        f = _gpu_ctx["compiler"].compile(tree)()
                    else:
                        from lib.factor_engine import evaluate_expression
                        fv = evaluate_expression(expr, panel)
                        wide = fv.reindex(index=_gpu_ctx["dates"], columns=_gpu_ctx["symbols"])
                        f = _t.as_tensor(wide.to_numpy(dtype=np.float64), dtype=_t.float64,
                                         device=_gpu_ctx["target"].device)
                else:
                    from lib.factor_engine import evaluate_expression
                    fv = evaluate_expression(expr, panel)
                    arr = fv.to_numpy(dtype=np.float64)
                    f = _t.as_tensor(np.where(np.isfinite(arr), arr, np.nan), dtype=_t.float64)
                _behav_cache[h] = _factor_behavior_desc(f)
            except Exception:
                continue

    def _update_archive(pop: List[Dict]) -> None:
        """把当代表现较好的个体描述子并入跨代档案库 (有界; 保高适应度+多样行为)"""
        if not _pca_qd:
            return
        ranked_idx = sorted(range(len(pop)),
                            key=lambda i: (fit_list[i][0] if fit_list[i] and fit_list[i][0] is not None else -1e9),
                            reverse=True)[:max(10, population_size // 4)]
        for i in ranked_idx:
            ind = pop[i]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            h = expr_hash(expr)
            desc = _behav_cache.get(h)
            if desc is None:
                continue
            # 同行为已入档案则保留原记录 (描述子近似相等视为同一行为)
            dup = any(np.allclose(desc, d, atol=1e-9) for d in _pca_archive.values())
            if not dup:
                _pca_archive[h] = desc
        # 超限: 按插入序淘汰最旧 (dict 保插入序)
        while len(_pca_archive) > _PCA_QD_ARCHIVE_MAX:
            _pca_archive.pop(next(iter(_pca_archive)))

    def _pca_diversity_scores(pop: List[Dict]) -> Optional[List[float]]:
        """PCA 特征空间新颖性: 描述子补算 -> 种群+档案库 PCA 投影 -> k 近邻平均距离"""
        if not _pca_qd:
            return None
        _collect_behavior_descs(pop)
        descs: List[Optional[np.ndarray]] = []
        for ind in pop:
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            descs.append(_behav_cache.get(expr_hash(expr)))
        valid = [d for d in descs if d is not None]
        if len(valid) < 3:
            return None  # 描述子不足: 回退 Jaccard
        # 种群描述子 + 档案库描述子合并做 PCA 特征空间
        arch = list(_pca_archive.values())
        X = np.vstack(valid + arch)
        n_arch = len(arch)
        proj = _fit_pca_projection(X, _PCA_QD_N_COMP)
        if proj is None:
            return None
        # 只取种群对应的投影行 (前 len(valid) 行), 与档案库一起算 k 近邻距离
        pop_proj = proj[:len(valid)]
        all_proj = proj
        n = pop_proj.shape[0]
        diff = all_proj[None, :, :] - pop_proj[:, None, :]
        dist = np.sqrt(np.nansum(diff ** 2, axis=2))
        k = max(1, min(_PCA_QD_KNN, all_proj.shape[0] - 1))
        dist[:, np.arange(n)] = np.inf  # 排除"自身"(种群行)
        knn = np.sort(dist, axis=1)[:, :k]
        novelty = knn.mean(axis=1)
        mx = float(np.nanmax(novelty)) if n > 1 else 0.0
        if mx > 0 and np.isfinite(mx):
            novelty = novelty / mx
        # 映射回种群位置 (无描述子的个体给 0 新颖性, 不参与加成)
        out: List[float] = []
        pos = 0
        for d in descs:
            if d is None:
                out.append(0.0)
            else:
                out.append(float(novelty[pos]))
                pos += 1
        return out

    for gen in range(generations):
        fit_list = _eval_all(population)
        # 提取有效适应度
        valid = [(i, f) for i, (f, _r) in enumerate(fit_list) if f is not None]
        if not valid:
            # 全无效: 全变异重来 (避免卡死)
            population = [random_tree(rng, max_depth, space) for _ in range(population_size)]
            continue

        # 计算多样性得分 (用于锦标赛选择)
        # 阶段5.2 #7: pca_qd 开启时优先用 PCA 特征空间新颖性 (描述子不足自动回退 Jaccard);
        # 关闭时沿用 Jaccard, 与历史行为一致。
        div_scores = None
        pca_div_scores = _pca_diversity_scores(population) if diversity_weight > 0 else None
        if pca_div_scores is not None:
            div_scores = pca_div_scores
        elif diversity_weight > 0:
            div_scores = _diversity_scores(population)
        # PCA-QD: 把当代表现较好的个体描述子并入跨代档案库 (新奇性搜索的记忆)
        _update_archive(population)
        # 当前代权重: 线性衰减 (初始 diversity_weight, 末代 0.25*diversity_weight)
        gen_div_weight = diversity_weight * (1.0 - 0.75 * gen / max(1, generations - 1))
        # 同质化自适应放大 (多样性增强): 种群平均新颖性越低(=越同质), 放大多样性权重,
        # 打破裸字段/同构收敛 (novelty 范围 ~0-1, 平均<0.5 视为同质化, 权重最多放大 3 倍)
        if div_scores is not None and len(div_scores) > 0:
            avg_novelty = float(np.mean(div_scores))
            homogeneity_factor = 1.0 + 2.0 * max(0.0, 1.0 - avg_novelty * 2.0)
            gen_div_weight *= homogeneity_factor

        # 排序用原始适应度 (记录曲线, 更新全局最优)
        valid.sort(key=lambda x: x[1], reverse=True)
        gen_best_fit = valid[0][1]
        gen_avg_fit = float(np.mean([f for _, f in valid]))

        # 更新全局最优
        if best_overall[0] is None or gen_best_fit > best_overall[0]:
            best_idx = valid[0][0]
            ind = population[best_idx]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            best_overall = (gen_best_fit, expr)
            no_improve = 0
        else:
            no_improve += 1

        # 三重分段: 早停判断迁移到验证段 (阶段5.1)
        # 提供验证段时, 计算所有有效个体在验证段的适应度, 取最优用于早停判断, 取平均用于监控
        # 连续无改善代数以验证段最优为准; 未提供验证段时沿用训练段 no_improve, 行为不变。
        val_improved = None  # None=未启用验证段
        avg_val_fit = None   # 验证集平均适应度 (用于监控整体泛化趋势)
        cur_best_val = None  # 验证集当代表现最优 (未提供验证段时为 None)
        if _val_ctx is not None and valid:
            val_fits = []
            for _i, _f in valid:
                _bind = population[_i]
                _bexpr = _bind["name"] if _bind.get("_warm") else tree_to_str(_bind)
                _btree = None if _bind.get("_warm") else _bind
                vf = _val_fitness(_bexpr, _btree)
                if vf is not None:
                    val_fits.append(vf)
            if val_fits:
                cur_best_val = max(val_fits)
                avg_val_fit = float(np.mean(val_fits))
                if best_val_fit is None or cur_best_val > best_val_fit:
                    best_val_fit = cur_best_val
                    val_improved = True
                    no_improve_val = 0
                else:
                    val_improved = False
                    no_improve_val += 1

        evolution_curve.append({
            "gen": gen + 1,
            "best_fitness": round(float(gen_best_fit), 6),
            "avg_fitness": round(float(gen_avg_fit), 6),
            # 曲线口径与训练集一致: 画"当代表现最优" (cur_best_val), 而非历史累积最优 (best_val_fit),
            # 否则验证集曲线会是单调台阶线, 掩盖每代真实波动; 早停判断仍用 best_val_fit。
            "best_val_fitness": round(float(cur_best_val), 6) if cur_best_val is not None else None,
            "avg_val_fitness": round(float(avg_val_fit), 6) if avg_val_fit is not None else None,
            "best_expr": (best_overall[1] if best_overall[1] else ""),
        })

        # 跨代候选收集: 每代把当代表现最好的若干个体 (含精英) 加入 hall_of_fame,
        # 按表达式去重并保留最高 fitness, 保证收尾候选覆盖整个进化过程而非仅最后一代
        for i, f in valid[:max(10, population_size // 4)]:
            ind = population[i]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            if _is_bare_field(expr):
                continue
            old = hall_of_fame.get(expr)
            if old is None or f > old.get("fitness", -1e9):
                hall_of_fame[expr] = {"expr": expr, "fitness": f,
                                      "result": fit_list[i][1] or {}}

        # 进度回调 (阶段3.3 SSE 流式进度; 每代完成推送轻量统计, None=不回调)
        if progress_cb is not None:
            progress_cb(gen + 1, {
                "gen": gen + 1,
                "generations": generations,
                "best_fitness": round(float(gen_best_fit), 6),
                "avg_fitness": round(float(gen_avg_fit), 6),
                # 曲线口径与训练集一致 (当代表现最优 cur_best_val), 与 evolution_curve 同步
                "best_val_fitness": round(float(cur_best_val), 6) if cur_best_val is not None else None,
                "avg_val_fitness": round(float(avg_val_fit), 6) if avg_val_fit is not None else None,
                "n_valid": len(valid),
                "diversity_weight": round(float(gen_div_weight), 6),
                "replacement_count": replacement_count,
            })

        if verbose:
            print(f"[GP] gen {gen+1}: best={gen_best_fit:.5f} avg={gen_avg_fit:.5f}")

        # 早停: 连续 no_improve 代无改善 (启用验证段时以验证段无改善为准, 阶段5.1)
        # early_stop_gens<=0 表示关闭早停, 跑满 generations
        if early_stop_gens > 0:
            if no_improve_val > 0:
                if no_improve_val >= early_stop_gens:
                    break
            else:
                if no_improve >= early_stop_gens:
                    break

        # ---- 生成下一代 (精英保留 + 锦标赛选择 + 交叉/变异) ----
        elite_size = max(1, int(population_size * 0.1))
        elite_idx = [i for i, _ in valid[:elite_size]]
        new_pop = [copy_tree(population[i]) for i in elite_idx]

        # 锦标赛选择函数: 用 原始适应度 + 代权重*多样性得分 作为选择压
        # (多样性得分越大=越新颖, 给小幅正加成; 鼓励探索不同算子组合)
        # 裸字段/常数 无算子调用, 无增量信息 (已被库内因子覆盖), 选择压降权, 避免统治种群
        def _select_fitness(idx: int) -> float:
            f = fit_list[idx][0]
            if f is None:
                return -1e9
            ind = population[idx]
            expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
            if _is_bare_field(expr):
                f = f * 0.3
            if div_scores is not None:
                return f + gen_div_weight * div_scores[idx]
            return f

        def _tournament() -> Dict:
            contenders = [rng.choice(valid) for _ in range(min(tournament_size, len(valid)))]
            best = max(contenders, key=lambda x: _select_fitness(x[0]))[0]
            return population[best]

        while len(new_pop) < population_size:
            r = rng.random()
            if r < p_crossover:
                a = _tournament()
                b = _tournament()
                child = crossover(rng, a, b, max_depth)
            elif r < p_crossover + p_subtree_mutation:
                a = _tournament()
                child = subtree_mutation(rng, a, max_depth, space)
            elif r < p_crossover + p_subtree_mutation + p_hoist_mutation:
                a = _tournament()
                child = hoist_mutation(rng, a, max_depth)
            elif r < p_crossover + p_subtree_mutation + p_hoist_mutation + p_point_mutation:
                a = _tournament()
                child = point_mutation(rng, a, space)
            else:
                # reproduction 直接复制
                a = _tournament()
                child = copy_tree(a)
            expr = child["name"] if child.get("_warm") else tree_to_str(child)
            h = expr_hash(expr)
            if h in seen_exprs and len(seen_exprs) > max_exprs_seen // 4:
                # 已见过: 变异一下保证多样性
                child = point_mutation(rng, child, space)
                expr = child["name"] if child.get("_warm") else tree_to_str(child)
                h = expr_hash(expr)
            seen_exprs.add(h)
            # 阶段5.2 #8 replacement 防早熟 (来源 AutoAlpha): 同质个体替换 ——
            # 新生个体与"已入下一代个体" token Jaccard 相似度 >= 阈值时, 变异再生
            # 为多样化变体 (替换掉同质新生个体), 防止种群被高适应度同质基因统治早熟。
            if replacement_thresh is not None and new_pop:
                _max_sim = 0.0
                for _prev in new_pop:
                    _pe = _prev["name"] if _prev.get("_warm") else tree_to_str(_prev)
                    _s = _token_similarity(expr, _pe)
                    if _s > _max_sim:
                        _max_sim = _s
                if _max_sim >= replacement_thresh:
                    child = point_mutation(rng, child, space)
                    expr = child["name"] if child.get("_warm") else tree_to_str(child)
                    h = expr_hash(expr)
                    seen_exprs.add(h)
                    replacement_count += 1
            # 阶段 P4: max_length 节点数上限 —— 超限回退复制父代 (对齐 QuantGplearn max_length)
            # 兼容 _warm 字符串个体: 解析其公式统计节点数, 解析失败视为 0 (跳过检查)。
            if max_length and max_length > 0:
                if child.get("_warm"):
                    _ct = formula_to_tree(child["name"])
                    _n = tree_size(_ct) if _ct is not None else 0
                else:
                    _n = tree_size(child)
                if _n > max_length:
                    child = copy_tree(a)
                    expr = child["name"] if child.get("_warm") else tree_to_str(child)
                    h = expr_hash(expr)
                    seen_exprs.add(h)
            new_pop.append(child)

        population = new_pop

    # ---- 收尾: 候选精评 (hall_of_fame + 最后一代 Top-N + 历史各代最优, 合并去重) ----
    final_fit = _eval_all(population)
    ranked = sorted(
        [(i, f) for i, (f, _r) in enumerate(final_fit) if f is not None],
        key=lambda x: x[1], reverse=True,
    )
    # 候选池来源 1: hall_of_fame (跨代收集, 覆盖整个进化过程, 保证结构多样性)
    candidate_exprs: List[str] = []
    candidate_fit: Dict[str, float] = {}
    candidate_result: Dict[str, Dict] = {}
    hof_sorted = sorted(hall_of_fame.values(), key=lambda x: x.get("fitness", 0), reverse=True)
    for h in hof_sorted:
        expr = h["expr"]
        candidate_exprs.append(expr)
        candidate_fit[expr] = h["fitness"]
        candidate_result[expr] = h["result"] or {}
    # 候选池来源 2: 最后一代 Top-N (补充 hall 未覆盖的最终代表现)
    top_n = ranked[:max(10, population_size // 2)]
    for i, f in top_n:
        ind = population[i]
        expr = ind["name"] if ind.get("_warm") else tree_to_str(ind)
        if expr in candidate_fit:
            continue
        candidate_exprs.append(expr)
        candidate_fit[expr] = f
        candidate_result[expr] = final_fit[i][1] or {}
    # 候选池来源 3: 历史各代最优 (若未出现)
    for gen_info in evolution_curve:
        expr = gen_info.get("best_expr")
        if expr and expr not in candidate_fit and expr not in candidate_exprs:
            # 历史最优未收集到: 单独补评
            fit, res = fitness_expr(expr, panel, prices_panel,
                                    rebal_period, min_warmup,
                                    ts_normalize_window, marketcap_proxy_lookback,
                                    parsimony)
            if fit is not None:
                candidate_exprs.append(expr)
                candidate_fit[expr] = fit
                candidate_result[expr] = res or {}
    candidates = []
    for expr in candidate_exprs:
        res = candidate_result[expr] or {}
        # GPU/新语义最小求值路径只产出 rank_ic_mean, 不返回 ICIR/分层多空等展示指标。
        # 这里优先用 GPU 整树求值直接补齐完整指标 (全程 GPU, 不依赖 CPU 回填);
        # 仅当 GPU 不可用或该表达式 GPU 求值失败时, 才回退 CPU 完整评价 (fitness_expr)。
        if res.get("rank_ic_ir") is None and not res.get("layered"):
            filled = False
            if _gpu_ctx is not None:
                try:
                    import torch as _t
                    h = expr_hash(expr)
                    f_compiled = _compile_cache.get(h)
                    if f_compiled is None:
                        tree = formula_parseable_gpu(expr)
                        if tree is not None:
                            f_compiled = _gpu_ctx["compiler"].compile(tree)
                            _compile_cache[h] = f_compiled
                    if f_compiled is not None:
                        with _t.no_grad():
                            f = f_compiled()
                        if f is not None:
                            from lib.factor_gpu_evaluator import gpu_rank_ic_metrics
                            metrics = gpu_rank_ic_metrics(
                                f, _gpu_ctx["target"], _gpu_ctx["mask"],
                                _gpu_ctx.get("mc_proxy"), _gpu_ctx.get("style_proxy"))
                            if metrics:
                                merged = dict(res)
                                for _k in ("rank_ic_mean", "rank_ic_ir", "layered", "samples"):
                                    _v = metrics.get(_k)
                                    if _v not in (None, {}, []):
                                        merged[_k] = _v
                                res = merged
                                filled = True
                except Exception:
                    filled = False
            if not filled:
                try:
                    _, full = fitness_expr(expr, panel, prices_panel,
                                           rebal_period, min_warmup,
                                           ts_normalize_window, marketcap_proxy_lookback,
                                           parsimony)
                    if full:
                        merged = dict(res)
                        for _k in ("rank_ic_ir", "layered", "samples"):
                            if not merged.get(_k):
                                merged[_k] = full.get(_k)
                        # 逐项补齐仍缺时整份替换, 保证展示指标齐全
                        if merged.get("rank_ic_ir") is None and not merged.get("layered"):
                            merged = full
                        res = merged
                except Exception:
                    pass
        candidates.append({
            "expr": expr,
            "fitness": round(float(candidate_fit[expr]), 6),
            "rank_ic_mean": res.get("rank_ic_mean"),
            "rank_ic_ir": res.get("rank_ic_ir"),
            "layered": res.get("layered", {}),
            "samples": res.get("samples"),
        })
    # 过滤裸字段 (仅含字段/常数, 无算子; 无增量信息, 2026-08-16 实测 GP 常收敛到 Amount 等规模裸字段)
    if filter_bare_fields:
        candidates = [c for c in candidates if not _is_bare_field(c["expr"])]
    # 去重 (按表达式规范化哈希)
    seen_c = set()
    dedup = []
    for c in candidates:
        h = expr_hash(c["expr"])
        if h not in seen_c:
            seen_c.add(h)
            dedup.append(c)
    candidates = dedup
    # 候选去冗余 (复刻 QuantGplearn hall_of_fame + tolerable_corr; |corr|>阈值保留高 IC 项)
    dedup_report: Dict[str, Any] = {"enabled": False, "corr_thresh": None,
                                    "removed_n": 0, "removed": []}
    if corr_thresh and corr_thresh > 0 and len(candidates) >= 2:
        candidates, dedup_report = dedup_by_corr(
            candidates, panel, prices_panel,
            rebal_period=rebal_period, min_warmup=min_warmup,
            ts_normalize_window=ts_normalize_window,
            corr_thresh=corr_thresh,
            ortho_mode=ortho_mode,
            min_incremental_ic=min_incremental_ic,
        )
        dedup_report["enabled"] = True

    return {
        "candidates": candidates,
        "evolution_curve": evolution_curve,
        "population_size": population_size,
        "generations": len(evolution_curve),
        "requested_generations": generations,
        "early_stopped": len(evolution_curve) < generations,
        "best": best_overall[1],
        "best_fitness": best_overall[0],
        "dedup_report": dedup_report,
        "pca_qd": bool(_pca_qd),
        "pca_archive_size": len(_pca_archive),
        "replacement_thresh": replacement_thresh,
        "replacement_count": replacement_count,
        "fitness_mode": _fitness_mode,
    }


# ============================================================
# 六、训练/测试分段 + OOS 复核 (参照 QuantAlpha/DolphinDB 口径)
# ============================================================
# split_train_test_dates / trim_panel_to_dates 已迁移到 lib/factor_screening.py
# 这里通过顶部 import 继续暴露给本模块使用, 保持 GP 内部调用不变。

# oos_recheck / walk_forward_recheck 已迁移到 lib/factor_screening.py
