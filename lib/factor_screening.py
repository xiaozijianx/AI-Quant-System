# -*- coding: utf-8 -*-
"""
lib/factor_screening.py -- 因子筛选/评价公共能力

从原 lib/factor_gp.py 中逐步抽出的、与具体挖掘引擎无关的公共函数。
目标: GP / RL / LLM-GP / SVD / ML 等页面都只依赖这里的公共能力,
     不依赖某一个挖掘引擎的专属文件。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import random
import warnings

import numpy as np
import pandas as pd

from lib.factor_engine import (
    validate_expression, evaluate_expression, run_ic_timeseries_panel,
)


def split_train_test_dates(prices_panel: Dict[str, pd.DataFrame],
                           start_date: str, end_date: str,
                           train_ratio: float = 0.7,
                           val_ratio: float = 0.0) -> Tuple[str, str, str, str, str, str]:
    """把 [start_date, end_date] 切分为 训练/验证/测试 三段, 返回 6 个日期
    (train_start, train_end, val_start, val_end, test_start, test_end)

    val_ratio=0 时退化为两段 (验证段为空, 与历史行为一致):
      - 进化期只在训练段评适应度
      - val_ratio>0 时, evolve 早停/多样性衰减用验证段指标
      - 收尾对 Top-N 在测试段做 OOS 复核 (只碰测试段)
    """
    first = next(iter(prices_panel))
    idx = prices_panel[first].index
    mask = (idx >= pd.Timestamp(start_date)) & (idx <= pd.Timestamp(end_date))
    dates = idx[mask]
    if len(dates) < 40:
        return start_date, end_date, end_date, end_date, end_date, end_date
    n = len(dates)
    val_ratio = max(0.0, min(float(val_ratio), 1.0 - float(train_ratio)))
    split_pos = int(n * train_ratio)
    train_end = dates[split_pos - 1]
    if val_ratio > 0 and split_pos < n - 20:
        val_start = dates[split_pos]
        val_pos = min(n - 1, split_pos + max(1, int(n * val_ratio)))
        val_end = dates[val_pos - 1]
        test_start = dates[val_pos]
    else:
        val_start, val_end = dates[split_pos], dates[split_pos]
        test_start = dates[split_pos]
    return (str(dates[0]), str(train_end), str(val_start), str(val_end),
            str(test_start), str(dates[-1]))


def trim_panel_to_dates(panel: Dict[str, pd.DataFrame],
                        start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """把面板裁剪到 [start_date, end_date] 区间 (OOS 复核用测试段面板)"""
    out = {}
    for code, df in panel.items():
        m = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
        d = df.loc[m]
        if len(d) >= 30:
            out[code] = d
    return out


def _screening_rank_ic_result(expr: str,
                                panel: Dict[str, pd.DataFrame],
                                prices_panel: Dict[str, pd.DataFrame],
                                rebal_period: int,
                                min_warmup: int,
                                ts_normalize_window: Optional[int] = None,
                                marketcap_proxy_lookback: Optional[int] = None):
    """计算单个表达式的 RankIC 评价结果（不含 parsimony 惩罚）

    等价于 factor_gp.fitness_expr 的有效性/评价逻辑，供 OOS/WF 公共筛选使用，
    避免筛选层依赖 GP 专用实现。
    """
    ok = validate_expression(expr)
    if not ok:
        return None
    try:
        fv = evaluate_expression(expr, panel)
    except Exception:
        return None
    if fv is None or len(fv) == 0 or fv.dropna(how="all").empty:
        return None
    non_null = float(fv.notna().mean().mean()) if len(fv) else 0.0
    if non_null < 0.2:
        return None
    _ts_eff = ts_normalize_window
    if ts_normalize_window:
        try:
            from lib.factor_engine import _is_technical_ts_expression
            if not _is_technical_ts_expression(expr):
                _ts_eff = None
        except Exception:
            _ts_eff = None
    try:
        result = run_ic_timeseries_panel(
            fv, prices_panel,
            rebal_period=rebal_period,
            min_warmup=min_warmup,
            ts_normalize_window=_ts_eff,
            marketcap_proxy_lookback=marketcap_proxy_lookback,
        )
    except Exception:
        return None
    return result




# ============================================================
# OOS / Walk-Forward 公共筛选（从 factor_gp 迁移）
# ============================================================

def oos_recheck(candidate_exprs: List[str],
                panel: Dict[str, pd.DataFrame],
                prices_panel: Dict[str, pd.DataFrame],
                test_start: str, test_end: str,
                rebal_period: int = 21,
                min_warmup: int = 60,
                ts_normalize_window: Optional[int] = None,
                marketcap_proxy_lookback: Optional[int] = None,
                style_cfg: Optional[Dict[str, Any]] = None,
                parsimony: float = 0.0,
                use_gpu: bool = False,
                fitness_mode: str = "rank_ic") -> List[Dict]:
    """在测试段对 Top-N 候选做 OOS 复核 (报告训练/测试 IC 对比)

    返回 [{expr, train_rank_ic, test_rank_ic, oos_ok}]
    style_cfg: 阶段5.2 #6 多因子风格中性化配置 (与 evolve 同口径; None=仅市值/不中性化)
    fitness_mode: 阶段5.2 #9 适应度目标 (与 evolve 同口径, 默认 "rank_ic")
    """
    test_panel = trim_panel_to_dates(prices_panel, test_start, test_end)
    if len(test_panel) < 5:
        return []
    # GPU/新语义批量评估 (OOS 精评候选多, 与主循环 mean_rank_ic 口径一致; 市值/风格中性化可选)
    if use_gpu:
        try:
            from lib.factor_gpu_evaluator import batch_mean_rank_ic_exprs
            ics = batch_mean_rank_ic_exprs(
                candidate_exprs, test_panel,
                rebal_period=rebal_period, mc_lookback=marketcap_proxy_lookback,
                style_cfg=style_cfg, fitness_mode=fitness_mode,
                ts_normalize_window=ts_normalize_window)
            out = []
            for expr, ic in zip(candidate_exprs, ics):
                ok = bool(np.isfinite(ic))
                out.append({"expr": expr,
                            "test_rank_ic": float(ic) if ok else None,
                            "test_rank_ic_ir": None,
                            "oos_ok": ok})
            return out
        except Exception:
            pass  # 失败回退逐表达式
    out = []
    for expr in candidate_exprs:
        res = _screening_rank_ic_result(
            expr, test_panel, test_panel,
            rebal_period, min_warmup,
            ts_normalize_window, marketcap_proxy_lookback,
        )
        fit = res is not None
        out.append({
            "expr": expr,
            "test_rank_ic": (res or {}).get("rank_ic_mean"),
            "test_rank_ic_ir": (res or {}).get("rank_ic_ir"),
            "oos_ok": fit is not None,
        })
    return out


def walk_forward_recheck(candidate_exprs: List[str],
                         panel: Dict[str, pd.DataFrame],
                         prices_panel: Dict[str, pd.DataFrame],
                         start_date: str, end_date: str,
                         n_folds: int = 3,
                         fold_train_ratio: float = 0.6,
                         rebal_period: int = 21,
                         min_warmup: int = 60,
                         ts_normalize_window: Optional[int] = None,
                         marketcap_proxy_lookback: Optional[int] = None,
                         style_cfg: Optional[Dict[str, Any]] = None,
                         parsimony: float = 0.0,
                         min_test_ic: float = 0.03,
                         use_gpu: bool = False,
                         fitness_mode: str = "rank_ic") -> List[Dict]:
    """多段 walk-forward 重验证 (阶段3.1, OOS 复核增强)

    把 [start_date, end_date] 滚动切分为 n_folds 段, 每段内部再按
    fold_train_ratio 切分 训练/测试 两个子段; 对每个候选在每段"测试子段"上
    单独评估 RankIC, 得到跨多段的 OOS IC 分布, 判断候选是否稳健
    (而不是只在单一测试段上一次成败定生死, 缓解单段过拟合/运气成分)。

    返回 [{expr, fold_ics:[...], mean_ic, fold_ir_mean, pass_ratio, n_folds, wf_ok}]:
        fold_ics:     各段测试子段的 RankIC 列表 (无效段剔除)
        mean_ic:      各段 RankIC 均值 (符号即候选稳健方向)
        fold_ir_mean: 各段 RankIC_IR 均值
        pass_ratio:   |RankIC| >= min_test_ic 的段占比
        wf_ok:        abs(mean_ic) >= min_test_ic 且 pass_ratio >= 0.5 (多数段通过才算稳健)

    fitness_mode: 阶段5.2 #9 适应度目标 (与 evolve 同口径, 默认 "rank_ic")
    """
    first = next(iter(prices_panel))
    idx = prices_panel[first].index
    mask = (idx >= pd.Timestamp(start_date)) & (idx <= pd.Timestamp(end_date))
    dates = idx[mask]
    n_dates = len(dates)
    if n_dates < 60:
        return []  # 数据不足, 无法做多段重验证

    # 动态 fold 数: 保证每段"测试子段"长度足够可算 (否则自动减少段数)
    # 测试子段目标长度 = max(60, min_warmup + rebal_period), 否则窗口大的表达式
    # (如 ts_VAR(.,60)) 在短段上预热期占满, 无法产出有效 IC 截面。
    min_test_len = max(60, min_warmup + rebal_period)
    max_supported = int(n_dates * (1 - fold_train_ratio) / min_test_len)
    eff_folds = max(1, min(n_folds, max_supported))
    # 滚动切段 (等分 eff_folds 段, 每段内 fold_train_ratio 训练 / 余下测试)
    edges = np.linspace(0, n_dates, eff_folds + 1).astype(int)
    folds: List[Tuple[str, str, str, str]] = []
    for i in range(eff_folds):
        s, e = int(edges[i]), int(edges[i + 1])
        mid = int(s + (e - s) * fold_train_ratio)
        if mid <= s or mid >= e:
            continue
        folds.append((str(dates[s]), str(dates[mid - 1]), str(dates[mid]), str(dates[e - 1])))
    if not folds:
        return []

    out: List[Dict] = []
    # GPU/新语义批量: 逐 fold 对全部候选评估 (与主循环 mean_rank_ic 口径一致)
    if use_gpu:
        try:
            from lib.factor_gpu_evaluator import batch_mean_rank_ic_exprs
            # 预收集各 fold 的测试面板
            fold_panels: List[pd.DataFrame] = []
            for (_ts, _te, ss, ee) in folds:
                test_panel = trim_panel_to_dates(prices_panel, ss, ee)
                if len(test_panel) < 5:
                    continue
                fold_panels.append(test_panel)
            # 候选 -> fold_ics 累加器
            acc: Dict[str, Dict[str, list]] = {e: {"ics": [], "irs": []} for e in candidate_exprs}
            for test_panel in fold_panels:
                ics = batch_mean_rank_ic_exprs(
                    candidate_exprs, test_panel,
                    rebal_period=rebal_period, mc_lookback=marketcap_proxy_lookback,
                    style_cfg=style_cfg, fitness_mode=fitness_mode,
                    ts_normalize_window=ts_normalize_window)
                for expr, ic in zip(candidate_exprs, ics):
                    if not np.isfinite(ic):
                        continue
                    acc[expr]["ics"].append(float(ic))
            for expr in candidate_exprs:
                fold_ics = acc[expr]["ics"]
                fold_irs = acc[expr]["irs"]
                if not fold_ics:
                    out.append({
                        "expr": expr, "fold_ics": [], "mean_ic": None,
                        "fold_ir_mean": None, "pass_ratio": 0.0,
                        "n_folds": 0, "wf_ok": False,
                    })
                    continue
                mean_ic = float(np.mean(fold_ics))
                n_pass = sum(1 for x in fold_ics if abs(x) >= min_test_ic)
                pass_ratio = n_pass / len(fold_ics)
                out.append({
                    "expr": expr,
                    "fold_ics": [round(x, 6) for x in fold_ics],
                    "mean_ic": round(mean_ic, 6),
                    "fold_ir_mean": round(float(np.mean(fold_irs)), 6) if fold_irs else None,
                    "pass_ratio": round(pass_ratio, 4),
                    "n_folds": len(fold_ics),
                    "wf_ok": bool(abs(mean_ic) >= min_test_ic and pass_ratio >= 0.5),
                })
            return out
        except Exception:
            pass  # GPU 失败回退逐表达式

    for expr in candidate_exprs:
        fold_ics: List[float] = []
        fold_irs: List[float] = []
        for (_ts, _te, ss, ee) in folds:
            test_panel = trim_panel_to_dates(prices_panel, ss, ee)
            if len(test_panel) < 5:
                continue
            # 自适应降窗: 测试子段较短时降低 warmup, 保证有足够 IC 期
            # (参考 resolve_ts_window 降窗模式; 否则短段 IC 全空导致 wf 无法判定)
            fmw = min(min_warmup, max(20, len(test_panel) - rebal_period * 2))
            res = _screening_rank_ic_result(
            expr, test_panel, test_panel,
            rebal_period, fmw,
            ts_normalize_window, marketcap_proxy_lookback,
        )
            ic = (res or {}).get("rank_ic_mean")
            ir = (res or {}).get("rank_ic_ir")
            if ic is None or not np.isfinite(ic):
                continue
            fold_ics.append(float(ic))
            if ir is not None and np.isfinite(ir):
                fold_irs.append(float(ir))
        if not fold_ics:
            out.append({
                "expr": expr, "fold_ics": [], "mean_ic": None,
                "fold_ir_mean": None, "pass_ratio": 0.0,
                "n_folds": 0, "wf_ok": False,
            })
            continue
        mean_ic = float(np.mean(fold_ics))
        n_pass = sum(1 for x in fold_ics if abs(x) >= min_test_ic)
        pass_ratio = n_pass / len(fold_ics)
        out.append({
            "expr": expr,
            "fold_ics": [round(x, 6) for x in fold_ics],
            "mean_ic": round(mean_ic, 6),
            "fold_ir_mean": round(float(np.mean(fold_irs)), 6) if fold_irs else None,
            "pass_ratio": round(pass_ratio, 4),
            "n_folds": len(fold_ics),
            "wf_ok": bool(abs(mean_ic) >= min_test_ic and pass_ratio >= 0.5),
        })
    return out

# permutation_significance / dedup_by_corr 已迁移到 lib/factor_screening.py

# ============================================================
# 以下实现从 lib/factor_gp.py 迁移而来
# ============================================================

def permutation_significance(candidate_exprs: List[str],
                             panel: Dict[str, pd.DataFrame],
                             prices_panel: Dict[str, pd.DataFrame],
                             start_date: str, end_date: str,
                             n_perm: int = 200,
                             rebal_period: int = 21,
                             marketcap_proxy_lookback: Optional[int] = None,
                             style_cfg: Optional[Dict[str, Any]] = None,
                             random_state: Optional[int] = None,
                             use_gpu: bool = False,
                             fitness_mode: str = "rank_ic") -> List[Dict]:
    """permutation 假发现检验 (阶段5.1, 来源 QuantAlpha)

    对每个候选表达式, 打乱"目标收益的日期" N 次得到 IC 空分布, 用真实 IC 与之比较
    计算经验 p 值, 输出显著性标记 (缓解多个候选同时检验时的假发现风险)。

    实现要点 (性能关键): 候选表达式只 evaluate 一次得到因子面板;
    之后每次 permutation 只打乱目标收益 target 的行(日期)顺序、重算逐日截面
    Spearman RankIC 的均值 —— 不打乱因子面板, 因此成本低 (与 mean_rank_ic 同口径)。

    返回 [{expr, real_ic, null_mean, null_std, p_value, significant}]:
        real_ic:    真实 (未打乱) 目标收益下的 RankIC
        null_mean / null_std: 空分布 IC 的均值 / 标准差 (反映打乱后的偶然水平)
        p_value:    经验 p 值 = (1 + #{|null_ic| >= |real_ic|}) / (1 + n_perm)
        significant: p_value < 0.05 (双侧, |real_ic| 显著大于打乱后的偶然水平)
    """
    if not candidate_exprs:
        return []
    rng = random.Random(random_state)
    first = next(iter(prices_panel))
    idx = prices_panel[first].index
    mask = (idx >= pd.Timestamp(start_date)) & (idx <= pd.Timestamp(end_date))
    dates = idx[mask]
    n_dates = len(dates)
    if n_dates < 40:
        return []  # 数据不足, 无法做 permutation 检验

    # 裁剪面板到检验区间 (日期段)
    sub_panel = trim_panel_to_dates(prices_panel, start_date, end_date)
    if len(sub_panel) < 5:
        return []

    # 统一走 GPU/新语义 mean_rank_ic (与主循环同口径; GPU 不可用时回退 CPU 面板 + 张量语义)
    try:
        from lib.factor_gpu_evaluator import TensorPanel, mean_rank_ic
        import torch as _t
        tp = TensorPanel.from_panel(sub_panel,
                                    fields=["Open", "High", "Low", "Close", "Volume",
                                            "Amount", "VWAP", "Turnover", "IdioRet",
                                            "Value", "TotalRet"])
        target = tp.future_returns(rebal_period)
        mask_t = tp._global_mask(tp.values)
        mc = tp.marketcap_proxy(marketcap_proxy_lookback) if marketcap_proxy_lookback else None
        # 阶段5.2 #6 多因子风格中性化 (与主循环同口径; 优先于单市值)
        style = None
        if style_cfg:
            style = tp.style_proxy(
                mc_lookback=style_cfg.get("mc_lookback", marketcap_proxy_lookback),
                ret_window=style_cfg.get("ret_window", 20),
                vol_window=style_cfg.get("vol_window", 20),
                use_turnover=style_cfg.get("use_turnover", True),
                use_industry=style_cfg.get("use_industry", True),
                industry_map=style_cfg.get("industry_map"),
            )

        # 每候选: 因子面板 [T,N] 张量 (只 evaluate 一次)
        expr_factors: Dict[str, Optional[_t.Tensor]] = {}
        for expr in candidate_exprs:
            try:
                from lib.factor_engine import evaluate_expression
                fv = evaluate_expression(expr, sub_panel)
                wide = fv.reindex(index=tp.dates, columns=tp.symbols)
                _arr = wide.to_numpy(dtype=np.float64)
                if not _arr.flags.writeable:
                    _arr = _arr.copy()  # PyTorch 张量要求可写, 只读缓冲需复制
                expr_factors[expr] = _t.as_tensor(_arr, dtype=_t.float64,
                                                  device=target.device)
            except Exception:
                expr_factors[expr] = None

        out: List[Dict] = []
        for expr in candidate_exprs:
            f = expr_factors[expr]
            if f is None:
                out.append({"expr": expr, "real_ic": None, "null_mean": None,
                            "null_std": None, "p_value": None, "significant": None})
                continue
            real_ic = float(mean_rank_ic(f, target, mask_t, mc, style, fitness_mode))
            if not np.isfinite(real_ic):
                out.append({"expr": expr, "real_ic": None, "null_mean": None,
                            "null_std": None, "p_value": None, "significant": None})
                continue
            # 打乱目标收益行(日期)顺序 n_perm 次, 重算 IC 得空分布
            null_ics = np.empty(n_perm, dtype=np.float64)
            n_rows = target.shape[0]
            for k in range(n_perm):
                perm_idx = _t.randperm(n_rows, device=target.device)
                t_perm = target.index_select(0, perm_idx)
                null_ics[k] = float(mean_rank_ic(f, t_perm, mask_t, mc, style, fitness_mode))
            null_mean = float(np.nanmean(null_ics))
            null_std = float(np.nanstd(null_ics)) if null_ics.size else 0.0
            # 经验 p 值 (双侧): 空分布中 |null| >= |real| 的比例 (加 1 平滑避免 0)
            denom = int(np.sum(np.abs(null_ics) >= abs(real_ic)))
            p_value = (1.0 + denom) / (1.0 + n_perm)
            out.append({
                "expr": expr,
                "real_ic": round(real_ic, 6),
                "null_mean": round(null_mean, 6),
                "null_std": round(null_std, 6),
                "p_value": round(p_value, 6),
                "significant": bool(p_value < 0.05),
            })
        return out
    except Exception:
        pass  # GPU 不可用回退逐表达式 CPU 计算

    # ---- CPU 回退 (纯 numpy 实现, 与 GPU mean_rank_ic 同语义) ----
    out_cpu: List[Dict] = []
    # 预计算目标收益面板 [T,N] (每只股票 close[t+d]/close[t]-1)
    from scipy.stats import spearmanr
    target_cpu = None  # [T,N] ndarray
    target_dates = None
    target_symbols = None
    try:
        sorted_codes = sorted(sub_panel.keys())
        first_df = sub_panel[sorted_codes[0]]
        all_dates = first_df.index[(first_df.index >= pd.Timestamp(start_date)) &
                                   (first_df.index <= pd.Timestamp(end_date))]
        n = len(all_dates)
        tgt = np.full((n, len(sorted_codes)), np.nan, dtype=np.float64)
        for j, code in enumerate(sorted_codes):
            close = sub_panel[code]["close"].reindex(all_dates)
            ret = close.shift(-rebal_period) / close - 1.0
            tgt[:, j] = ret.values
        target_cpu = tgt
        target_dates = all_dates
        target_symbols = sorted_codes
    except Exception:
        target_cpu = None

    if target_cpu is None or target_cpu.shape[0] < 40:
        return []  # 目标收益不可用

    def _mean_rank_ic_cpu(factor_vals: np.ndarray, tgt: np.ndarray) -> float:
        """CPU 版 mean_rank_ic: 逐日截面 zscore 因子, 算 Spearman RankIC 均值"""
        ics = []
        T = factor_vals.shape[0]
        for t in range(T):
            f_row = factor_vals[t]
            t_row = tgt[t]
            m = np.isfinite(f_row) & np.isfinite(t_row)
            # 截面有效样本下限 30: 与 CPU run_ic_timeseries_panel / GPU batch_spearmanr
            # 口径一致, 少样本截面(5~29 只)在 Spearman 下易虚高 (RankIC 假相关修复)
            if m.sum() < 30:
                continue
            f_ok = f_row[m]
            t_ok = t_row[m]
            if len(np.unique(f_ok)) < 2 or len(np.unique(t_ok)) < 2:
                continue
            # 每日截面 zscore (normalize_by_day, 与 mean_rank_ic 同口径)
            f_znorm = (f_ok - np.nanmean(f_ok)) / (np.nanstd(f_ok) + 1e-10)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # 兜底抑制 scipy ConstantInputWarning
                with np.errstate(all="ignore"):
                    rho, _ = spearmanr(f_znorm, t_ok)
            if np.isfinite(rho):
                ics.append(float(rho))
        return float(np.mean(ics)) if ics else float("nan")

    for expr in candidate_exprs:
        try:
            fv = evaluate_expression(expr, sub_panel)
        except Exception:
            out_cpu.append({"expr": expr, "real_ic": None, "null_mean": None,
                            "null_std": None, "p_value": None, "significant": None})
            continue
        if fv is None or len(fv) == 0:
            out_cpu.append({"expr": expr, "real_ic": None, "null_mean": None,
                            "null_std": None, "p_value": None, "significant": None})
            continue
        # 对齐到目标面板的股票列
        common = [c for c in target_symbols if c in fv.columns]
        if len(common) < 5:
            out_cpu.append({"expr": expr, "real_ic": None, "null_mean": None,
                            "null_std": None, "p_value": None, "significant": None})
            continue
        fv_aligned = fv[common].reindex(target_dates)
        fv_arr = fv_aligned.to_numpy(dtype=np.float64)
        tgt_expr = target_cpu[:, [target_symbols.index(c) for c in common]]
        real_ic = _mean_rank_ic_cpu(fv_arr, tgt_expr)
        if not np.isfinite(real_ic):
            out_cpu.append({"expr": expr, "real_ic": None, "null_mean": None,
                            "null_std": None, "p_value": None, "significant": None})
            continue
        # 打乱目标收益行(日期)顺序 n_perm 次
        null_ics_cpu = np.empty(n_perm, dtype=np.float64)
        n_rows = tgt_expr.shape[0]
        for k in range(n_perm):
            perm_idx = rng.sample(range(n_rows), n_rows)
            t_perm = tgt_expr[perm_idx]
            null_ics_cpu[k] = _mean_rank_ic_cpu(fv_arr, t_perm)
        null_mean = float(np.nanmean(null_ics_cpu))
        null_std = float(np.nanstd(null_ics_cpu)) if null_ics_cpu.size else 0.0
        denom_cpu = int(np.sum(np.abs(null_ics_cpu) >= abs(real_ic)))
        p_cpu = (1.0 + denom_cpu) / (1.0 + n_perm)
        out_cpu.append({
            "expr": expr,
            "real_ic": round(real_ic, 6),
            "null_mean": round(null_mean, 6),
            "null_std": round(null_std, 6),
            "p_value": round(p_cpu, 6),
            "significant": bool(p_cpu < 0.05),
        })
    return out_cpu


# ============================================================
# 七、候选去冗余 (复刻 QuantGplearn hall_of_fame + tolerable_corr)
# ============================================================
def dedup_by_corr(candidates: List[Dict],
                  panel: Dict[str, pd.DataFrame],
                  prices_panel: Dict[str, pd.DataFrame],
                  rebal_period: int = 21,
                  min_warmup: int = 130,
                  ts_normalize_window: Optional[int] = None,
                  corr_thresh: float = 0.8,
                  ic_metric: str = "rank_ic_mean",
                  ortho_mode: bool = False,
                  min_incremental_ic: float = 0.01) -> Tuple[List[Dict], Dict[str, Any]]:
    """候选去冗余: 两两算因子值 Spearman 相关, |corr|>阈值 时保留 |IC| 更高者

    复刻 QuantGplearn SymbolicTransformer 的 hall_of_fame + tolerable_corr 逻辑
    (genetic.py L867-897): 对候选因子面板两两算相关矩阵, 剔除高度相关的低分项,
    直到剩余候选两两相关均低于阈值。等价于多因子页 `_redundancy_remove` 思路。

    阶段5.2 #5 残差正交化 (来源 Auto-Alpha-Finding): ortho_mode=True 时, 在相关
    剔除基础上, 对每个待保留候选相对"已保留因子池"做逐截面 OLS 回归取残差, 计算
    残差因子的增量 IC (与未来收益 RankIC 均值); |增量IC| 低于 min_incremental_ic
    视为"相对已选池无增量信息"而剔除 —— 比纯相关阈值更严格保证增量 alpha。
    ortho_mode=False 时行为与历史完全一致。

    参数:
        candidates:      [{expr, fitness, rank_ic_mean, ...}]
        panel:           字段面板 (evaluate_expression 用)
        prices_panel:    价格面板 (残差正交化模式下用于算未来收益的增量 IC)
        rebal_period:    调仓周期 (面板对齐/未来收益用)
        min_warmup:      预热天数 (面板对齐/IC 计算用)
        corr_thresh:     相关性阈值 (默认 0.8, 同多因子页/原版默认)
        ic_metric:       保留依据的 IC 字段 (默认 rank_ic_mean)
        ortho_mode:      残差正交化模式 (阶段5.2 #5; 默认 False, 关闭时零行为变化)
        min_incremental_ic: 残差增量 IC 阈值 (默认 0.01)

    返回 (kept_candidates, report)
        report = {corr_thresh, removed: [{expr, corr_with, corr, ic}], kept_n,
                  ortho_mode, min_incremental_ic, incremental_ics}
    """
    if len(candidates) < 2:
        return candidates, {"corr_thresh": corr_thresh, "removed": [], "kept_n": len(candidates),
                            "ortho_mode": ortho_mode, "min_incremental_ic": min_incremental_ic,
                            "incremental_ics": []}
    if corr_thresh is None or corr_thresh <= 0:
        return candidates, {"corr_thresh": corr_thresh, "removed": [], "kept_n": len(candidates),
                            "ortho_mode": ortho_mode, "min_incremental_ic": min_incremental_ic,
                            "incremental_ics": []}

    # 按 IC 绝对值降序排列 (优先保留高 IC 项, 与 _redundancy_remove 一致)
    def _ic_abs(c):
        v = c.get(ic_metric)
        return abs(float(v)) if v is not None and np.isfinite(v) else 0.0

    ordered = sorted(candidates, key=_ic_abs, reverse=True)

    # 预计算候选因子面板 (避免重复 evaluate; 失败项跳过)
    def _panel_of(expr):
        try:
            fv = evaluate_expression(expr, panel)
        except Exception:
            return None
        if fv is None or len(fv) == 0:
            return None
        # 时序标准化 (与评价管线一致: 仅 technical_ts 类先滚动分位; technical 不套)
        if ts_normalize_window:
            try:
                from lib.factor_engine import _is_technical_ts_expression
                _ts_eff = ts_normalize_window if _is_technical_ts_expression(expr) else None
            except Exception:
                _ts_eff = ts_normalize_window
            if _ts_eff:
                try:
                    fv = fv.rolling(
                        _ts_eff,
                        min_periods=max(20, _ts_eff // 2),
                    ).rank(pct=True)
                except Exception:
                    pass
        return fv

    panels = {}
    for c in ordered:
        fv = _panel_of(c["expr"])
        if fv is not None and fv.notna().any().any():
            panels[c["expr"]] = fv

    kept: List[Dict] = []
    removed: List[Dict] = []
    # 阶段5.2 #5 残差正交化: 已保留因子池面板 (用于对新候选逐截面回归取残差)
    pool_panels: List[pd.DataFrame] = []
    incremental_ics: List[Dict[str, Any]] = []
    for c in ordered:
        expr = c["expr"]
        if expr not in panels:
            # 无法求值: 直接剔除 (无有效因子面板)
            removed.append({"expr": expr, "reason": "invalid_panel", "corr": None,
                            "ic": c.get(ic_metric)})
            continue
        cur = panels[expr]
        drop = False
        for k in kept:
            if k["expr"] not in panels:
                continue
            ref = panels[k["expr"]]
            corr = _panel_spearman(cur, ref)
            if corr is not None and abs(corr) > corr_thresh:
                removed.append({"expr": expr, "corr_with": k["expr"],
                                "corr": round(float(corr), 4), "ic": c.get(ic_metric)})
                drop = True
                break
        if drop:
            continue
        # 阶段5.2 #5 残差正交化: 相对"已保留池"逐截面回归取残差, 增量 IC 过低则剔除
        # (比纯相关阈值更严格: 相关略低于阈值但相对池已无增量信息的候选会被筛掉)
        inc_ic = None
        if ortho_mode and pool_panels:
            resid = _panel_residualize(cur, pool_panels)
            if resid is not None and resid.notna().any().any():
                inc_ic = _panel_rank_ic_mean(resid, prices_panel, rebal_period, min_warmup)
                if inc_ic is not None and abs(inc_ic) < min_incremental_ic:
                    removed.append({"expr": expr, "reason": "low_incremental_ic",
                                    "incremental_ic": round(float(inc_ic), 4),
                                    "ortho_pool_size": len(pool_panels),
                                    "ic": c.get(ic_metric)})
                    continue
        kept.append(c)
        if ortho_mode:
            c["incremental_ic"] = (round(float(inc_ic), 4) if inc_ic is not None else None)
            c["ortho_pool_size"] = len(pool_panels)
            incremental_ics.append({"expr": expr,
                                    "incremental_ic": c["incremental_ic"],
                                    "ortho_pool_size": len(pool_panels)})
        pool_panels.append(cur)

    report = {
        "corr_thresh": corr_thresh,
        "kept_n": len(kept),
        "removed_n": len(removed),
        "removed": removed,
        "ortho_mode": ortho_mode,
        "min_incremental_ic": min_incremental_ic,
        "incremental_ics": incremental_ics,
    }
    return kept, report


def _panel_spearman(fv_a: pd.DataFrame, fv_b: pd.DataFrame) -> Optional[float]:
    """两个因子面板(日期×股票)的 Spearman 相关: 公共列(股票)对齐后逐截面求秩相关再平均

    等价于 QuantGplearn 的"evaluation 面板两两相关"(其 flatten 后 corrcoef 对应
    截面秩相关均值), 且对逐股时间序列滚动均适用。
    """
    try:
        common_cols = [c for c in fv_a.columns if c in fv_b.columns]
        if len(common_cols) < 3:
            return None
        a = fv_a[common_cols]
        b = fv_b[common_cols]
        # 逐截面(日期)计算 Spearman, 取均值
        corrs = []
        idx = a.index.intersection(b.index)
        if len(idx) < 5:
            return None
        a = a.loc[idx]
        b = b.loc[idx]
        from scipy.stats import spearmanr
        for t in idx:
            ra = a.loc[t]
            rb = b.loc[t]
            m = ra.notna() & rb.notna()
            if m.sum() < 5:
                continue
            # 过滤截面常数 (任一序列全部相等时 Spearman 无定义, 跳过该截面)
            if ra[m].nunique() < 2 or rb[m].nunique() < 2:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # 兜底抑制 scipy ConstantInputWarning
                with np.errstate(all="ignore"):
                    rho, _ = spearmanr(ra[m], rb[m])
            if np.isfinite(rho):
                corrs.append(rho)
        if not corrs:
            return None
        return float(np.mean(corrs))
    except Exception:
        return None


def _panel_residualize(fv: pd.DataFrame,
                       pool_panels: List[pd.DataFrame]) -> pd.DataFrame:
    """对单因子面板做"相对已选池逐截面 OLS 回归取残差" (阶段5.2 #5 残差正交化)

    对每个日期 t: Y = fv 截面值, X = [1, 池因子截面值...], 残差 r_t = Y - Xβ。
    β 用 numpy.linalg.lstsq 最小二乘解 (与 neutralize_regression 同款无 statsmodels
    依赖; 残差在回归列空间正交, 即"相对已选池的增量部分")。
    返回与 fv 同形状残差面板 (有效样本处有值, 其余 NaN); 池为空时返回原面板副本。
    """
    if not pool_panels:
        return fv.copy()
    cols = list(fv.columns)
    pool_list = []
    for p in pool_panels:
        try:
            pool_list.append(p.reindex(index=fv.index, columns=cols))
        except Exception:
            return fv.copy()
    out = pd.DataFrame(index=fv.index, columns=cols, dtype=float)
    for t in fv.index:
        y = fv.loc[t].to_numpy(dtype=float)
        valid = np.isfinite(y)
        for p in pool_list:
            valid &= np.isfinite(p.loc[t].to_numpy(dtype=float))
        if valid.sum() < max(10, len(cols) // 2):
            continue
        X = np.column_stack([np.ones(valid.sum())]
                            + [p.loc[t].to_numpy(dtype=float)[valid] for p in pool_list])
        try:
            coef, *_ = np.linalg.lstsq(X, y[valid], rcond=None)
            resid = y[valid] - X @ coef
        except Exception:
            continue
        row = np.full(len(cols), np.nan)
        row[valid] = resid
        out.loc[t] = row
    return out


def _panel_rank_ic_mean(fv: pd.DataFrame,
                        prices_panel: Dict[str, pd.DataFrame],
                        rebal_period: int = 21,
                        min_warmup: int = 130) -> Optional[float]:
    """面板 RankIC 时序均值 (逐调仓日截面 Spearman, 与主循环 mean_rank_ic 同口径)

    供残差正交化算"残差因子的增量 IC"使用: 残差面板 vs 未来收益 (t → t+rebal_period)
    逐调仓日 Spearman 均值; 数据不足时返回 None。
    """
    try:
        from scipy.stats import spearmanr
        first_code = next(iter(prices_panel))
        idx = list(prices_panel[first_code].index)
        ics = []
        for i in range(min_warmup, len(idx) - rebal_period):
            d0 = idx[i]
            d1 = idx[i + rebal_period]
            fut = {}
            for code, df in prices_panel.items():
                if d0 in df.index and d1 in df.index:
                    p0 = df.at[d0, "close"]
                    p1 = df.at[d1, "close"]
                    if pd.notna(p0) and p0 > 0 and pd.notna(p1):
                        fut[code] = p1 / p0 - 1
            if len(fut) < 5:
                continue
            if d0 not in fv.index:
                continue
            row = fv.loc[d0]
            common = [c for c in fut if c in row.index and pd.notna(row[c])
                      and np.isfinite(fut[c])]
            if len(common) < 5:
                continue
            a = row[common].to_numpy(dtype=float)
            b = np.array([fut[c] for c in common], dtype=float)
            if len(np.unique(a)) < 2 or len(np.unique(b)) < 2:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # 兜底抑制 scipy ConstantInputWarning
                with np.errstate(all="ignore"):
                    rho, _ = spearmanr(a, b)
            if np.isfinite(rho):
                ics.append(rho)
        if not ics:
            return None
        return float(np.mean(ics))
    except Exception:
        return None
