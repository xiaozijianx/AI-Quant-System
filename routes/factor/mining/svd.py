# -*- coding: utf-8 -*-
"""
routes/factor/mining/svd.py -- SVD 因子挖掘路由
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from fastapi import APIRouter, Body, HTTPException

router = APIRouter()


@router.post("/mine_svd")
def mine_svd_factors(body: Dict[str, Any] = Body(...)):
    """
    SVD 隐因子挖掘
    来源: CASE-QuantStats/2-SVD因子挖掘与分析.py
    """
    stock_codes = body.get("stock_codes", [])
    start_date = body.get("start_date", "2024-01-01")
    end_date = body.get("end_date", "2025-12-31")
    n_factors = body.get("n_factors", 5)
    pool_type = body.get("pool_type", "")
    pool_ref = body.get("pool_ref", "")

    if pool_type:
        from lib.factor_evaluator import get_pool_stocks
        try:
            pool_codes = get_pool_stocks(pool_type, pool_ref, n=80, min_days=200)
            if pool_codes:
                stock_codes = pool_codes
        except Exception:
            pass

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
    panel = {}
    for code in stock_codes[:100]:
        try:
            df = load_daily_kline(code, start_date, end_date, prefer="mysql")
            if df is not None and len(df) > 60:
                panel[code] = df
        except Exception:
            pass

    if len(panel) < 10:
        raise HTTPException(status_code=400, detail=f"有效股票数据不足10只 (当前 {len(panel)} 只)")

    returns_df = pd.DataFrame({code: df["close"].pct_change() for code, df in panel.items()})
    returns_df = returns_df.dropna(how="all").fillna(0)

    returns_mean = returns_df.mean(axis=1)
    R = returns_df.sub(returns_mean, axis=0)

    U, s, Vt = np.linalg.svd(R.values, full_matrices=False)

    total_var = (s ** 2).sum()
    cumvar = np.cumsum(s ** 2) / total_var

    n = min(n_factors, len(s))
    factors = {}
    for i in range(n):
        exposure = Vt[i]
        factors[f"svd_factor_{i+1}"] = {
            "singular_value": float(s[i]),
            "variance_explained": float(s[i] ** 2 / total_var),
            "cumulative_variance": float(cumvar[i]),
            "exposure": {code: float(exposure[j]) for j, code in enumerate(returns_df.columns)},
        }

    dates = list(returns_df.index)
    factor_ts = []
    for i in range(n):
        ts = U[:, i] * s[i]
        factor_ts.append({
            "name": f"svd_factor_{i+1}",
            "dates": [str(d)[:10] for d in dates],
            "values": [float(v) for v in ts],
        })

    R_hat = (U[:, :n] * s[:n]) @ Vt[:n, :]
    residual = R.values - R_hat
    denom = float((R.values ** 2).sum()) or 1e-12
    residual_var_ratio = float((residual ** 2).sum() / denom)
    residual = {
        "residual_var_ratio": round(residual_var_ratio, 6),
        "residual_std": float(np.std(residual)),
        "explained_var_ratio": round(1.0 - residual_var_ratio, 6),
    }

    n_dates = len(dates)
    seg_idx = [0, n_dates // 3, 2 * n_dates // 3, n_dates]
    rolling = []
    for k in range(3):
        a, b = seg_idx[k], seg_idx[k + 1]
        if b - a < 2:
            continue
        Rs = R.values[a:b]
        ss = np.linalg.svd(Rs, full_matrices=False)[1]
        tv = float((ss ** 2).sum()) or 1e-12
        cum = np.cumsum(ss ** 2) / tv
        rolling.append({
            "start": str(dates[a])[:10],
            "end": str(dates[b - 1])[:10],
            "top_var": [round(float(ss[i] ** 2 / tv), 6) for i in range(min(n, len(ss)))],
            "top_cum": [round(float(cum[i]), 6) for i in range(min(n, len(cum)))],
        })

    return {
        "n_stocks": len(panel),
        "n_dates": len(returns_df),
        "total_factors_available": len(s),
        "factors": factors,
        "factor_ts": factor_ts,
        "residual": residual,
        "rolling": rolling,
        "variance_curve": [{"index": i, "singular_value": float(s[i]),
                            "cumulative": float(cumvar[i])} for i in range(min(20, len(s)))],
    }
