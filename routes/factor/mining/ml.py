# -*- coding: utf-8 -*-
"""
routes/factor/mining/ml.py -- ML 因子挖掘路由
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from fastapi import APIRouter, Body, HTTPException

router = APIRouter()


@router.post("/mine_ml")
def mine_ml_factors(body: Dict[str, Any] = Body(...)):
    """
    ML 因子训练 (XGBoost 特征重要性)
    来源: CASE-AI量化系统/ml_strategy/feature_engine.py

    body: {
        stock_codes: [...],
        start_date: "2024-01-01",
        end_date: "2025-12-31",
        target: "forward_return_5d"
    }
    """
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2025-12-31")
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    # 支持股票池类型 (修复: 原实现只收 stock_codes, 页面直达时无池可用)
    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception:
            pass

    # 股票不足 30 只时, 自动补足活跃股, 保证 ML 样本足够
    if not stock_codes or len(stock_codes) < 30:
        from lib.factor_evaluator import get_active_stock_pool
        auto_pool = get_active_stock_pool(n=80, min_days=200)
        if stock_codes:
            seen = set(stock_codes)
            for c in auto_pool:
                if c not in seen:
                    stock_codes.append(c)
                    seen.add(c)
        else:
            stock_codes = auto_pool

    from lib.backtest_data import load_daily_kline
    from lib.factor_engine import calc_basic_factors

    # 收集因子矩阵
    records = []
    for code in stock_codes[:100]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is None or len(df) < 130:
                continue
            # 目标: 未来5日收益
            # 修复: 原实现取 iloc[-1]/iloc[-5]-1 (过去5日收益) 当标签, 即用 t 时刻特征
            #       预测 t 之前已发生的收益, 方向性错误且样本内R²虚高; 现改为:
            #       特征取 t 时刻快照(切片去掉最后5日, 快照点 t = len-6),
            #       标签 = close[t+5]/close[t]-1 = 从 t 往后的5日收益, 方向正确。
            if len(df) > 5:
                feat_df = df.iloc[:-5]                  # 特征时点 t (保证 t+5 在样本内)
                factors = calc_basic_factors(feat_df)
                if not factors:
                    continue
                future_ret = df["close"].iloc[-1] / df["close"].iloc[-6] - 1
                factors["_target"] = float(future_ret)
                factors["_code"] = code
                records.append(factors)
        except Exception:
            pass

    if len(records) < 20:
        raise HTTPException(status_code=400, detail="有效样本不足20条")

    df_records = pd.DataFrame(records)
    target = df_records["_target"]
    features = df_records.drop(columns=["_target", "_code"])

    # XGBoost 训练
    try:
        from xgboost import XGBRegressor
        model = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.1)
        model.fit(features, target)
        importance = dict(zip(features.columns, model.feature_importances_))
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
    except ImportError:
        from sklearn.ensemble import RandomForestRegressor
        model = RandomForestRegressor(n_estimators=50, max_depth=4)
        model.fit(features, target)
        importance = dict(zip(features.columns, model.feature_importances_))
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

    return {
        "n_samples": len(records),
        "n_features": len(features.columns),
        "feature_importance": {k: float(v) for k, v in importance.items()},
        "r2_score": float(model.score(features, target)),
    }
