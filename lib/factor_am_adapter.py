# -*- coding: utf-8 -*-
"""
lib/factor_am_adapter.py -- 完全复刻 AlphaMaster 单股 RL 因子挖掘的接入适配器

做法: 直接引用 third_party/AlphaMaster-main 的 model_core 原包 (零改动、零复制),
只做两处对接:
  1. 数据接入: 我的单股日K -> AlphaEngine 需要的 data_manager
     (raw_dict / feat_tensor / target_ret, 语义对齐 ParquetDataManager)
  2. 输出映射: AlphaMaster token 公式 -> 可读表达式 -> 本系统表达式 (便于入库/选股)
"""
from __future__ import annotations

import os
import sys
import numpy as np
import torch

# 指向 AlphaMaster 源码根目录, 使其 model_core / strategy_manager 可作为顶层包导入
_ALPHA_MASTER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "third_party", "AlphaMaster-main",
)
if _ALPHA_MASTER_DIR not in sys.path:
    sys.path.insert(0, _ALPHA_MASTER_DIR)


class SingleStockDataManager:
    """单股数据适配器 (接口对齐 AlphaMaster ParquetDataManager)"""

    def __init__(self, df, code: str = ""):
        self.symbol = code or "single"
        self.df = df
        self._raw_dict = None
        self._target_ret = None
        self._feat_tensor = None

    def load(self):
        df = self.df.sort_index()
        def col(name):
            return torch.tensor(df[name].to_numpy(dtype=np.float32).reshape(1, -1),
                                dtype=torch.float32)
        raw = {
            "open": col("open"), "high": col("high"), "low": col("low"),
            "close": col("close"), "volume": col("volume"),
        }
        ts = df.index
        if hasattr(ts, "asi8"):  # DatetimeIndex: 纳秒整除 1e9 得 unix 秒
            unix_sec = (ts.asi8 // 10 ** 9).astype(np.int64)
        else:
            import pandas as pd
            unix_sec = np.array([pd.Timestamp(x).timestamp() for x in ts], dtype=np.int64)
        raw["time"] = torch.tensor(unix_sec.reshape(1, -1), dtype=torch.int64)
        self._raw_dict = raw
        self._target_ret = self._compute_target_ret(raw["open"])
        return self

    @staticmethod
    def _compute_target_ret(open_tensor: torch.Tensor) -> torch.Tensor:
        """AlphaMaster 约定: log(open[t+2]/open[t+1]), 最后2位补0"""
        N, T = open_tensor.shape
        target = torch.zeros(N, T, dtype=torch.float32)
        if T >= 3:
            target[:, :T - 2] = torch.log(open_tensor[:, 2:] / open_tensor[:, 1:-1])
        return target

    @property
    def raw_dict(self):
        return self._raw_dict

    @property
    def target_ret(self):
        return self._target_ret

    @property
    def feat_tensor(self):
        """懒计算特征张量 [N, F, T] (65 特征, 与原包一致)"""
        if self._feat_tensor is None:
            from model_core.features import MT5FeatureEngineer
            self._feat_tensor = MT5FeatureEngineer.compute_features(self._raw_dict)
        return self._feat_tensor

    @property
    def symbols(self):
        return [self.symbol]

    @property
    def bar_time(self):
        return self._raw_dict["time"]


def run_am_pipeline(body: dict):
    """单股 AlphaMaster RL 因子挖掘主流程

    body: {stock_code, start_date, end_date, train_steps, batch_size,
           max_formula_len, reward_mode, random_state, return_candidates}
    返回: {candidates, best, training_state, vocab, ...}
    """
    stock_code = (body.get("stock_code") or "").strip()
    start_date = body.get("start_date", "2023-01-01")
    end_date = body.get("end_date", "2025-12-31")
    train_steps = int(body.get("train_steps", 300))
    batch_size = int(body.get("batch_size", 64))
    max_formula_len = int(body.get("max_formula_len", 8))
    reward_mode = (body.get("reward_mode") or "ftmo").strip()
    random_state = int(body.get("random_state", 42))
    return_candidates = int(body.get("return_candidates", 10))
    n_folds = int(body.get("n_folds", 5))

    if not stock_code:
        raise ValueError("单股模式请输入有效股票代码, 如 600519.SH")

    # 1. 加载单股日K
    from lib.factor_evaluator import _normalize_custom_code
    from lib.backtest_data import load_daily_kline
    code = _normalize_custom_code(stock_code)
    df = load_daily_kline(code, start_date, end_date, prefer="mysql")
    if df is None or len(df) < 150:
        got = 0 if df is None else len(df)
        raise ValueError(f"标的 {code} 数据不足 (需>=150个交易日, 当前 {got})")

    # 2. 数据适配
    mgr = SingleStockDataManager(df, code=code).load()
    T = mgr.target_ret.shape[1]

    # 3. 配置原包超参 + 随机种子
    import random
    from model_core.config import ModelConfig
    np.random.seed(random_state); random.seed(random_state); torch.manual_seed(random_state)
    ModelConfig.TRAIN_STEPS = train_steps
    ModelConfig.BATCH_SIZE = batch_size
    ModelConfig.MAX_FORMULA_LEN = max_formula_len
    ModelConfig.REWARD_MODE = reward_mode

    # 4. 训练 (原包 AlphaEngine)
    from model_core.engine import AlphaEngine
    engine = AlphaEngine(data_manager=mgr, target_symbol=code, n_folds=n_folds)
    engine.train(end_step=train_steps)

    # 5. 解码候选公式 (AlphaMaster token -> 可读表达式)
    candidates_raw = []
    seen = set()
    if engine.best_formula:
        candidates_raw.append(engine.best_formula)
    for sc, cnt, toks, birth in getattr(engine, "_elite_pool", []):
        candidates_raw.append(toks)

    candidates = []
    for toks in candidates_raw:
        key = tuple(toks)
        if key in seen:
            continue
        seen.add(key)
        expr = engine._decode_formula(toks)
        if expr:
            candidates.append({
                "expr": expr,                      # AlphaMaster 可读表达式
                "expr_native": _map_to_native(expr),  # 本系统表达式
                "tokens": list(toks),              # 用于排序(按长度)
                "is_best": toks == engine.best_formula,
            })
    candidates.sort(key=lambda c: (0 if c.get("is_best") else 1, -len(c["tokens"])))
    candidates = candidates[:return_candidates]

    best_expr = engine._decode_formula(engine.best_formula) if engine.best_formula else ""
    from model_core.vocab import FORMULA_VOCAB
    return {
        "candidates": candidates,
        "best_score": float(engine.best_score) if engine.best_score is not None else None,
        "best_formula": best_expr,
        "best_formula_native": _map_to_native(best_expr) if best_expr else "",
        "elite_pool_size": len(getattr(engine, "_elite_pool", [])),
        "restart_count": getattr(engine, "restart_count", 0),
        "n_folds": n_folds,
        "stock_code": code,
        "n_dates": T,
        "vocab": {
            "size": FORMULA_VOCAB.size,
            "feature_count": FORMULA_VOCAB.feature_count,
            "operator_count": len(FORMULA_VOCAB.operator_names),
        },
        "training_history": getattr(engine, "training_history", []),
    }


# ============================================================
# 输出映射: AlphaMaster 算子表达式 -> 本系统算子表达式
# (本系统已补全这些算子和因子, 便于入库后被本系统 evaluate_expression 求值)
# ============================================================
_AM_TO_NATIVE = {
    "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/",
    "NEG": "neg", "ABS": "abs", "SIGN": "sign",
    "GATE": "gate", "JUMP": "jump", "DECAY": "ts_Decay", "DELAY1": "ts_Delay", "MAX3": "max3",
    "POWER": "power", "SIGNED_LOG": "signed_log", "SQRT": "sqrt", "CLIP": "clip",
    "SIGMOID": "sigmoid", "TANH_SQUASH": "tanh_squash", "IF_GT": "if_gt", "WINSORIZE": "winsorize",
    "TS_MEAN_5": "ts_Mean", "TS_MEAN_10": "ts_Mean", "TS_MEAN_20": "ts_Mean",
    "TS_STD_5": "ts_Stdev", "TS_STD_10": "ts_Stdev", "TS_STD_20": "ts_Stdev",
    "TS_RANK_5": "ts_Rank", "TS_RANK_10": "ts_Rank", "TS_RANK_20": "ts_Rank",
    "TS_SUM_5": "ts_Sum", "TS_SUM_10": "ts_Sum", "TS_SUM_20": "ts_Sum",
    "TS_MAX_10": "ts_Max", "TS_MAX_20": "ts_Max",
    "TS_MIN_10": "ts_Min", "TS_MIN_20": "ts_Min",
    "TS_ZSCORE_10": "ts_Zscore", "TS_ZSCORE_20": "ts_Zscore",
    "TS_QUANTILE_10": "ts_Quantile", "TS_SKEW_10": "ts_Skewness",
    "TS_ARGMAX_5": "ts_ArgMax", "TS_ARGMIN_5": "ts_ArgMin",
    "DECAY_LINEAR_5": "ts_DecayLinear", "DECAY_EXP_5": "ts_DecayExp",
    "SCALE": "ts_Scale", "COVARIANCE_10": "ts_Cov", "PRODUCT_5": "ts_Product",
    "SIGNED_POWER_2": "power", "DELTA": "ts_Delta", "DELTA_5": "ts_Delta",
    "WMA": "ts_WMA", "EMA_5": "ts_EMA", "EMA_20": "ts_EMA",
    "TS_CORR_10": "ts_Corr", "MOMENTUM_5": "momentum", "MOMENTUM_10": "momentum",
    "CS_RANK": "cs_Rank", "CS_SCALE": "cs_TransNorm", "CS_NEUTRALIZE": "cs_Demean",
}


def _map_to_native(am_expr: str) -> str:
    """把 AlphaMaster 可读表达式做词级算子名映射, 得到近似的本系统表达式(供展示/入库)"""
    if not am_expr:
        return ""
    out = am_expr
    for am, native in _AM_TO_NATIVE.items():
        out = out.replace(am, native)
    return out
