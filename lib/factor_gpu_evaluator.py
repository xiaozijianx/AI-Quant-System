# -*- coding: utf-8 -*-
# GPU 整树张量求值器: TensorPanel + 表达式树编译 + QuantGplearn 语义适应度
"""
复刻 QuantGplearn 的 GPU 计算架构:
  1. TensorPanel: 一次构建 [T, N, F] 密集张量并传输到 GPU, 所有树共享;
  2. PanelTensorCompiler: 把 factor_gp 的 dict 表达式树编译为 torch 算子序列,
     整树在 [T, N] 张量上执行, 无 pandas 逐股循环;
  3. 适应度: QuantGplearn 语义 —— normalize_by_day(每日截面zscore) +
     mean_rank_ic(全样本逐日截面 Spearman RankIC 均值); 未来收益 = close[t+d]/close[t]-1
     (d=rebal_period, 调仓对齐)。
  4. 市值中性化(可选): 每截面 ln(成交额代理) 回归取残差后 zscore (对齐 factor_engine
     neutralize_regression 的无分组语义, 处理 A 股小市值效应问题A)。

搜索空间内算子已全部 GPU 化; 仅 warm-start 注入的库内因子公式(字符串,
tree=None)或库内公式含 GPU 未覆盖字段/算子时, 由调用方 fallback 到
evaluate_expression 原路径 (见 factor_gp._eval_all)。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import math
import numpy as np
import pandas as pd
import torch

from lib.factor_gpu_torch import (
    TORCH_ARITH, TORCH_TS, TORCH_TS_RAW, TORCH_CS,
)
from lib.factor_engine import BASE_OPERATOR_MAP

EPS = 1e-12


# ============================================================
# TensorPanel: 面板张量化 (一次构建, 一次传输)
# ============================================================

class TensorPanel:
    """密集张量面板: values [T, N, F], mask [T, N]

    构建: from_panel(panel_dict, fields, rebal_period, device)
    其中 fields 为表达式引擎支持的基础字段名; 派生字段(IdioRet/Value/TotalRet)
    在构建时用 factor_engine 的字段构建逻辑预计算, 作为额外 F 维度。
    """

    def __init__(self, values: torch.Tensor, dates: pd.Index,
                 symbols: pd.Index, field_names: List[str]):
        self.values = values          # [T, N, F]
        self.dates = dates            # pd.Index
        self.symbols = symbols        # pd.Index
        self.field_names = list(field_names)
        self._field_pos = {f: i for i, f in enumerate(field_names)}

    @property
    def device(self):
        return self.values.device

    @property
    def shape(self) -> Tuple[int, int, int]:
        return tuple(self.values.shape)

    @property
    def n_times(self) -> int:
        return int(self.values.shape[0])

    @property
    def n_symbols(self) -> int:
        return int(self.values.shape[1])

    @property
    def n_features(self) -> int:
        return int(self.values.shape[2])

    def field(self, name: str) -> torch.Tensor:
        """取单个字段 [T, N] 张量"""
        return self.values[:, :, self._field_pos[name]]

    @classmethod
    def from_panel(cls, panel: Dict[str, pd.DataFrame],
                   fields: List[str],
                   device: Optional[str] = None,
                   dtype=None) -> "TensorPanel":
        """从 {stock_code: DataFrame(index=日期, columns=行情)} 构建张量面板

        说明:
          - 统一日期轴取所有股票日期并集; 统一股票轴按传入顺序;
          - 基础字段直接从每只股票的 DataFrame 列提取;
          - 派生字段 IdioRet/Value/TotalRet 用 factor_engine._build_field_dfs 计算;
          - 一次 to(device) 传输。
        """
        torch = _torch_mod()
        if dtype is None:
            # 阶段6.3 加速: 消费级 GPU 的 FP64 吞吐仅为 FP32 的 1/64, 搜索阶段默认 float32 提速;
            # CPU 路径保持 float64 与 pandas 逐位一致。落库/展示因子值仍由 float64 引擎
            # (evaluate_expression) 计算, 搜索阶段的微小数值差可接受 (对齐 QuantGplearn float32)。
            dtype = torch.float32 if (device or "").startswith("cuda") else torch.float64

        from lib.factor_engine import _build_field_dfs
        field_dfs = _build_field_dfs(panel)          # {field: DataFrame}
        if not field_dfs:
            raise ValueError("面板数据中无可用字段")

        # 统一日期轴 (并集排序) 与股票轴 (保留 panel 顺序)
        all_dates = sorted(set().union(*[list(df.index) for df in panel.values()]))
        dates = pd.Index(all_dates)
        symbols = pd.Index(list(panel.keys()))

        # 每个字段: wide DataFrame (index=日期, columns=股票), 对齐到统一网格
        cols = []
        for f in fields:
            if f in field_dfs:
                wide = field_dfs[f].reindex(index=dates, columns=symbols)
                cols.append(wide.to_numpy(dtype=np.float64, copy=False))
            else:
                cols.append(np.full((len(dates), len(symbols)), np.nan, dtype=np.float64))
        values_np = np.stack(cols, axis=-1)          # [T, N, F]
        values = torch.as_tensor(values_np, dtype=dtype, device=device)
        return cls(values, dates, symbols, fields)

    def future_returns(self, rebal_period: int) -> torch.Tensor:
        """构建未来收益 [T, N]: close[t+d]/close[t]-1 (d=rebal_period), 末尾 d 行 NaN"""
        close = self.field("Close")
        d = int(rebal_period)
        T = close.shape[0]
        out = torch.full_like(close, float("nan"))
        if T > d:
            fut = close[d:, :]
            now = close[:T - d, :]
            out[:T - d, :] = fut / torch.where(now.abs() > EPS, now, torch.full_like(now, float("nan"))) - 1.0
        return out

    def marketcap_proxy(self, lookback: int) -> torch.Tensor:
        """构建市值代理矩阵 [T, N]: 每只股票在 t 日之前(含)最近 lookback 个非NaN
        成交额均值 (对齐 factor_engine.build_marketcap_proxy_map 语义: dropna().tail(lookback).mean())。

        实现: 先对每列非NaN值做 rolling 最后 k 个均值, 再前向填充回原始时间轴;
        一次构建 (构建期 pandas 计算, 求值期 GPU 复用), 保证与既有引擎逐位一致。
        """
        amount_np = self.field("Amount").cpu().numpy()          # [T, N]
        T, N = amount_np.shape
        out = np.full((T, N), np.nan, dtype=np.float64)
        amt_df = pd.DataFrame(amount_np, index=self.dates, columns=list(self.symbols))
        for j, col in enumerate(amt_df.columns):
            s = amt_df[col]
            vals = s.dropna()
            if vals.empty:
                continue
            w = vals.rolling(int(lookback), min_periods=1).mean()   # 每个非NaN位置的最后k个均值
            m = w.reindex(s.index).ffill()                          # 前向填充到每个 t
            out[:, j] = m.to_numpy(dtype=np.float64)
        return torch.as_tensor(out, dtype=self.values.dtype, device=self.device)

    def style_proxy(self,
                    mc_lookback: Optional[int] = None,
                    ret_window: int = 20,
                    vol_window: int = 20,
                    use_turnover: bool = True,
                    use_industry: bool = True,
                    industry_map: Optional[Dict[str, str]] = None) -> torch.Tensor:
        """构建风格中性化矩阵 [T, N, K] (阶段5.2 #6, 来源华泰证券 GP 金工系列21)

        每列为一种风格因子, 供 neutralize_by_styles 多因子回归取残差:
            - ln市值代理 (mc_lookback 提供时, 对齐 marketcap_proxy)
            - 过去 ret_window 日收益 (close[t]/close[t-ret_window]-1, 点-in-time)
            - 换手率 Turnover (use_turnover=True, 面板字段)
            - 历史波动率 (近 vol_window 日收益 std, use 窗口内)
            - 行业哑变量 one-hot (use_industry 且 industry_map 提供时; 申万一级,
              只保留面板内 >=3 只的行业, 并 drop 参照组列避免与常数共线)
        返回 [T, N, K] 张量 (device/dtype 与面板一致); K 由启用的风格维度决定,
        至少 1 列。全部风格不可用时返回 None (由调用方回退为不中性化)。
        """
        torch = _torch_mod()
        T, N = self.shape[0], self.shape[1]
        cols: List[np.ndarray] = []  # 用 numpy 构建再统一转张量 (与 marketcap_proxy 同款)
        # 1) ln 市值代理
        if mc_lookback:
            mc = self.marketcap_proxy(int(mc_lookback)).cpu().numpy()
            with np.errstate(all="ignore"):
                cols.append(np.log(np.where(mc > 0, mc, np.nan)))
        # 2) 过去收益 (点-in-time: t 日用 t 与 t-ret_window 的 close, 无前视)
        close_np = self.field("Close").cpu().numpy()
        ret = np.full_like(close_np, np.nan)
        if ret_window >= 1:
            with np.errstate(all="ignore"):
                prev = np.roll(close_np, int(ret_window), axis=0)
                if int(ret_window) > 0:
                    prev[:int(ret_window), :] = np.nan
                ret = close_np / np.where(prev > 0, prev, np.nan) - 1.0
        cols.append(ret)
        # 3) 换手率
        if use_turnover:
            cols.append(self.field("Turnover").cpu().numpy())
        # 4) 历史波动率 (近 vol_window 日收益 std, 滚动)
        retd = np.full_like(close_np, np.nan)
        with np.errstate(all="ignore"):
            pc = close_np[1:, :] / np.where(close_np[:-1, :] > 0, close_np[:-1, :], np.nan) - 1.0
            if len(pc) > 0:
                retd[1:, :] = pc
        vol = np.full_like(close_np, np.nan)
        for j in range(N):
            s = pd.Series(retd[:, j])
            vol[:, j] = s.rolling(int(vol_window), min_periods=2).std().to_numpy(dtype=np.float64)
        cols.append(vol)
        # 5) 行业哑变量 (one-hot, drop 参照组)
        if use_industry and industry_map:
            ind_col = np.array([industry_map.get(c, "unknown") for c in self.symbols])
            uniq, counts = np.unique(ind_col, return_counts=True)
            # 只保留面板内 >=3 只的行业 (样本过少易与常数共线且信息量低)
            keep = [u for u, cnt in zip(uniq, counts) if cnt >= 3 and u != "unknown"]
            if len(keep) >= 2:
                keep_sorted = sorted(keep)
                ref = keep_sorted[-1]  # drop 参照组避免与常数共线
                for ind in keep_sorted[:-1]:
                    one_hot = (ind_col == ind).astype(np.float64)          # [N]
                    cols.append(np.repeat(one_hot[None, :], T, axis=0))    # [T, N]
        if not cols:
            return None
        # 统一转张量 [T, N, K]
        arr = np.stack(cols, axis=2)  # [T, N, K]
        return torch.as_tensor(arr, dtype=self.values.dtype, device=self.device)

    @staticmethod
    def _global_mask(values: torch.Tensor) -> torch.Tensor:
        """全字段有限性 mask [T, N] (对齐 QuantGplearn TensorPanelData.mask)"""
        return torch.isfinite(values).all(dim=2)


# ============================================================
# 适应度: QuantGplearn 语义 (mean_rank_ic + normalize_by_day)
# ============================================================

def _masked_mean(x: torch.Tensor, mask: torch.Tensor, dim: int, keepdim: bool = True) -> torch.Tensor:
    safe = torch.where(mask, x, torch.zeros_like(x))
    cnt = mask.sum(dim=dim, keepdim=keepdim).clamp_min(1)
    return safe.sum(dim=dim, keepdim=keepdim) / cnt


def _masked_std(x: torch.Tensor, mask: torch.Tensor, dim: int, keepdim: bool = True,
                unbiased: bool = False) -> torch.Tensor:
    mean = _masked_mean(x, mask, dim, keepdim=True)
    diff2 = torch.where(mask, (x - mean) ** 2, torch.zeros_like(x))
    cnt = mask.sum(dim=dim, keepdim=True).clamp_min(1)
    denom = (cnt - 1).clamp_min(1) if unbiased else cnt
    out = torch.sqrt((diff2.sum(dim=dim, keepdim=True) / denom).clamp_min(0.0))
    if not keepdim and dim is not None:
        out = out.squeeze(dim)
    return out


def _neutralize_marketcap_loop(factor: torch.Tensor,
                               lnm: torch.Tensor,
                               mc_proxy: torch.Tensor,
                               out: torch.Tensor,
                               min_valid: int) -> torch.Tensor:
    """市值中性化逐截面循环实现 (保留原逻辑, 批量 solve 异常时的兜底)"""
    torch = _torch_mod()
    N = factor.shape[1]
    for t in range(factor.shape[0]):
        f = factor[t]
        m = lnm[t]
        valid = (~torch.isnan(f)) & (~torch.isnan(m)) & (mc_proxy[t] > 0)
        if int(valid.sum()) < min_valid:
            # 数据不足: 退化为截面 zscore (只对 f 有效样本)
            mv = ~torch.isnan(f)
            if int(mv.sum()) < 2:
                continue
            mean = f[mv].mean()
            std = f[mv].std()
            if std <= 0 or not torch.isfinite(std):
                continue
            out[t] = torch.where(mv, (f - mean) / std, torch.full_like(f, float("nan")))
            continue
        X = torch.stack([torch.ones(N, device=f.device, dtype=f.dtype),
                         torch.where(valid, m, torch.zeros_like(m))], dim=1)   # [N, 2]
        y = torch.where(valid, f, torch.zeros_like(f))
        # 最小二乘残差 (对齐 np.linalg.lstsq): coef = (X^T X)^-1 X^T y
        XtX = X.T @ X
        Xty = X.T @ y
        coef = torch.linalg.solve(XtX + 1e-12 * torch.eye(2, device=f.device, dtype=f.dtype), Xty)
        resid = torch.where(valid, y - X @ coef, torch.full_like(f, float("nan")))
        # 残差后截面 zscore
        rv = resid[valid]
        mean = rv.mean()
        std = rv.std()
        if std > 0 and torch.isfinite(std):
            out[t] = torch.where(valid, (resid - mean) / std, torch.full_like(f, float("nan")))
        else:
            out[t] = resid
    return out


def neutralize_by_marketcap(factor: torch.Tensor,
                            mc_proxy: torch.Tensor,
                            min_valid: int = 10) -> torch.Tensor:
    """每截面市值中性化 (对齐 factor_engine.neutralize_regression 无分组语义)

    对每个截面 t: factor ~ [1, ln(市值代理)] 回归取残差; 有效样本<min_valid 时
    退化为该截面 zscore。残差后再做一次截面 zscore (对齐 preprocess_factors)。

    阶段 P1#6 加速: 原逐截面 torch.linalg.solve 改为批量矩阵求解
    (X^T X / X^T y 一次性构造 [T,2,2]/[T,2], 批内并行); 数学上与逐截面逐位一致
    (常数列保持全 1, 无效位置置 0, 与原 X 构造一致)。solve 异常时退回原逐截面循环。
    """
    torch = _torch_mod()
    T, N = factor.shape
    lnm = torch.log(torch.where(mc_proxy > 0, mc_proxy, torch.full_like(mc_proxy, float("nan"))))
    out = torch.full_like(factor, float("nan"))

    # 有效样本掩码与每截面样本数
    valid = (~torch.isnan(factor)) & (~torch.isnan(lnm)) & (mc_proxy > 0)   # [T, N]
    cnt = valid.sum(dim=1)                     # [T]
    enough = cnt >= min_valid                  # [T]

    # 批量构造设计矩阵 [T, N, 2] (常数列全 1, lnm 列无效位置置 0, 与逐截面 X 一致)
    X = torch.stack([torch.ones_like(factor),
                     torch.where(valid, lnm, torch.zeros_like(factor))], dim=2)
    y = torch.where(valid, factor, torch.zeros_like(factor))          # [T, N]
    XtX = torch.einsum("tni,tnj->tij", X, X)   # [T, 2, 2]
    Xty = torch.einsum("tni,tn->ti", X, y)     # [T, 2]
    reg = 1e-12 * torch.eye(2, device=factor.device, dtype=factor.dtype)
    try:
        coef = torch.linalg.solve(XtX + reg, Xty)                      # [T, 2]
    except Exception:
        # 存在奇异截面: 退回原逐截面循环 (保留原 try 语义)
        return _neutralize_marketcap_loop(factor, lnm, mc_proxy, out, min_valid)
    resid = y - torch.einsum("tni,ti->tn", X, coef)                    # [T, N]

    # 正常截面: 残差后截面 zscore (对齐 rv.mean()/rv.std(), std 用 n-1 无偏)
    mean_r = (resid * valid).sum(dim=1) / cnt.clamp_min(1)             # [T]
    diff2 = torch.where(valid, (resid - mean_r.unsqueeze(1)) ** 2, torch.zeros_like(resid))
    std_r = torch.sqrt((diff2.sum(dim=1) / (cnt - 1).clamp_min(1)).clamp_min(0.0))  # [T]
    z_r = torch.where(std_r.unsqueeze(1) > 0,
                      (resid - mean_r.unsqueeze(1)) / std_r.unsqueeze(1),
                      resid)
    norm_out = torch.where(valid, z_r, torch.full_like(z_r, float("nan")))

    # 退化截面: 对 f 直接 zscore (对齐原 mv.sum()<2 或 std 无效时保持 nan 的语义)
    mv = ~torch.isnan(factor)                                          # [T, N]
    mvcnt = mv.sum(dim=1)
    fmean = (torch.where(mv, factor, torch.zeros_like(factor))).sum(dim=1) / mvcnt.clamp_min(1)
    fdiff2 = torch.where(mv, (factor - fmean.unsqueeze(1)) ** 2, torch.zeros_like(factor))
    fstd = torch.sqrt((fdiff2.sum(dim=1) / (mvcnt - 1).clamp_min(1)).clamp_min(0.0))
    z_f = torch.where(fstd.unsqueeze(1) > 0,
                      (factor - fmean.unsqueeze(1)) / fstd.unsqueeze(1),
                      torch.full_like(factor, float("nan")))
    deg_out = torch.where(mv, z_f, torch.full_like(z_f, float("nan")))

    return torch.where(enough.unsqueeze(1), norm_out, deg_out)


def _neutralize_styles_loop(factor: torch.Tensor,
                            X_styles: torch.Tensor,
                            out: torch.Tensor,
                            min_valid: int) -> torch.Tensor:
    """风格中性化逐截面循环实现 (保留原逻辑, 批量 solve 异常时的兜底)"""
    torch = _torch_mod()
    N = factor.shape[1]
    K = int(X_styles.shape[2])
    eyeK = torch.eye(K + 1, device=factor.device, dtype=factor.dtype) * 1e-10
    for t in range(factor.shape[0]):
        f = factor[t]
        valid = ~torch.isnan(f)
        for k in range(K):
            valid &= ~torch.isnan(X_styles[t, :, k])
        if int(valid.sum()) < min_valid:
            # 数据不足: 退化为截面 zscore
            mv = ~torch.isnan(f)
            if int(mv.sum()) < 2:
                continue
            mean = f[mv].mean()
            std = f[mv].std()
            if std <= 0 or not torch.isfinite(std):
                continue
            out[t] = torch.where(mv, (f - mean) / std, torch.full_like(f, float("nan")))
            continue
        cols = [torch.ones(N, device=f.device, dtype=f.dtype)]
        for k in range(K):
            cols.append(torch.where(valid, X_styles[t, :, k],
                                    torch.zeros_like(X_styles[t, :, k])))
        X = torch.stack(cols, dim=1)            # [N, K+1]
        y = torch.where(valid, f, torch.zeros_like(f))
        XtX = X.T @ X
        Xty = X.T @ y
        try:
            coef = torch.linalg.solve(XtX + eyeK, Xty)
        except Exception:
            continue
        resid = torch.where(valid, y - X @ coef, torch.full_like(f, float("nan")))
        # 残差后截面 zscore
        rv = resid[valid]
        mean = rv.mean()
        std = rv.std()
        if std > 0 and torch.isfinite(std):
            out[t] = torch.where(valid, (resid - mean) / std, torch.full_like(f, float("nan")))
        else:
            out[t] = resid
    return out


def neutralize_by_styles(factor: torch.Tensor,
                         X_styles: torch.Tensor,
                         min_valid: int = 10) -> torch.Tensor:
    """每截面多因子风格中性化 (阶段5.2 #6, 来源华泰证券 GP 金工系列21)

    对每个截面 t: factor ~ [1, X_styles(t,:,:)] 多列回归取残差 + 截面 zscore。
    X_styles: [T, N, K] 张量, K 为风格列数 (如 ln市值/过去收益/换手/波动/行业哑变量;
    不含常数列, 函数内自动添加)。K=1 时数值等价于 neutralize_by_marketcap。
    有效样本<min_valid 时退化为截面 zscore; 用 (X^T X + eps·I) 正则保证秩亏安全。

    阶段 P1#6 加速: 原逐截面 solve 改为批量矩阵求解 (X^T X 为 [T,K+1,K+1],
    X^T y 为 [T,K+1], 批内并行); 常数列保持全 1, 无效位置置 0, 与原构造一致。
    solve 异常时退回原逐截面循环 (保留原 try-except 逐截面兜底语义)。
    """
    torch = _torch_mod()
    T, N = factor.shape
    K = int(X_styles.shape[2])
    out = torch.full_like(factor, float("nan"))

    # 有效样本掩码 (factor 非 NaN 且所有风格列非 NaN, 与原循环逐列检查一致)
    valid = ~torch.isnan(factor)                                       # [T, N]
    if K > 0:
        valid = valid & (~torch.isnan(X_styles)).all(dim=2)
    cnt = valid.sum(dim=1)                                             # [T]
    enough = cnt >= min_valid                                          # [T]

    # 批量构造设计矩阵 [T, N, K+1] (常数列全 1, 风格列无效位置置 0)
    X = torch.cat([torch.ones_like(factor).unsqueeze(2),
                   torch.where(valid.unsqueeze(2), X_styles, torch.zeros_like(X_styles))],
                  dim=2)
    y = torch.where(valid, factor, torch.zeros_like(factor))           # [T, N]
    XtX = torch.einsum("tni,tnj->tij", X, X)                           # [T, K+1, K+1]
    Xty = torch.einsum("tni,tn->ti", X, y)                             # [T, K+1]
    eyeK = torch.eye(K + 1, device=factor.device, dtype=factor.dtype) * 1e-10
    try:
        coef = torch.linalg.solve(XtX + eyeK, Xty)                     # [T, K+1]
    except Exception:
        # 存在奇异截面: 退回原逐截面循环 (保留原 try-except 逐截面 continue 语义)
        return _neutralize_styles_loop(factor, X_styles, out, min_valid)
    resid = y - torch.einsum("tni,ti->tn", X, coef)                    # [T, N]

    # 正常截面: 残差后截面 zscore (对齐 rv.mean()/rv.std(), std 用 n-1 无偏)
    mean_r = (resid * valid).sum(dim=1) / cnt.clamp_min(1)             # [T]
    diff2 = torch.where(valid, (resid - mean_r.unsqueeze(1)) ** 2, torch.zeros_like(resid))
    std_r = torch.sqrt((diff2.sum(dim=1) / (cnt - 1).clamp_min(1)).clamp_min(0.0))  # [T]
    z_r = torch.where(std_r.unsqueeze(1) > 0,
                      (resid - mean_r.unsqueeze(1)) / std_r.unsqueeze(1),
                      resid)
    norm_out = torch.where(valid, z_r, torch.full_like(z_r, float("nan")))

    # 退化截面: 对 f 直接 zscore (对齐原 mv.sum()<2 或 std 无效时保持 nan 的语义)
    mv = ~torch.isnan(factor)                                          # [T, N]
    mvcnt = mv.sum(dim=1)
    fmean = (torch.where(mv, factor, torch.zeros_like(factor))).sum(dim=1) / mvcnt.clamp_min(1)
    fdiff2 = torch.where(mv, (factor - fmean.unsqueeze(1)) ** 2, torch.zeros_like(factor))
    fstd = torch.sqrt((fdiff2.sum(dim=1) / (mvcnt - 1).clamp_min(1)).clamp_min(0.0))
    z_f = torch.where(fstd.unsqueeze(1) > 0,
                      (factor - fmean.unsqueeze(1)) / fstd.unsqueeze(1),
                      torch.full_like(factor, float("nan")))
    deg_out = torch.where(mv, z_f, torch.full_like(z_f, float("nan")))

    return torch.where(enough.unsqueeze(1), norm_out, deg_out)


def normalize_by_day(x: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
    """每日截面 zscore (对齐 QuantGplearn tensor_fitness.normalize_by_day, unbiased=False)"""
    torch = _torch_mod()
    if mask is None:
        mask = torch.isfinite(x)
    else:
        mask = mask & torch.isfinite(x)
    mean = _masked_mean(x, mask, dim=1, keepdim=True)
    std = _masked_std(x, mask, dim=1, keepdim=True, unbiased=False)
    out = torch.where(std > EPS, (x - mean) / std, torch.zeros_like(x))
    return torch.where(mask, out, torch.full_like(out, float("nan")))


def _rank_2d(x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """逐行(截面)平均秩 [0..n-1] (对齐 QuantGplearn rank_2d 的 stable argsort 顺序秩)"""
    torch = _torch_mod()
    x_fill = torch.where(mask, x, torch.full_like(x, float("inf")))
    # torch 1.11 兼容: argsort 无 stable 参数, 但 torch.sort(..., stable=True) 可用,
    # 输出 indices 即稳定 argsort 结果, 语义与 torch.argsort(stable=True) 完全一致
    _, order = torch.sort(x_fill, dim=1, stable=True)
    _, ranks = torch.sort(order, dim=1, stable=True)
    ranks = ranks.to(x.dtype) + 1.0
    return torch.where(mask, ranks, torch.full_like(ranks, float("nan")))


def batch_spearmanr(x: torch.Tensor, y: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
    """逐截面 Spearman RankIC [T] (对齐 QuantGplearn batch_spearmanr)"""
    torch = _torch_mod()
    mask = torch.isfinite(x) & torch.isfinite(y)
    if mask is None:
        mask = torch.isfinite(x) & torch.isfinite(y)
    rx = _rank_2d(x, mask)
    ry = _rank_2d(y, mask)
    # 对 rx/ry 做逐行 pearson
    m = torch.isfinite(rx) & torch.isfinite(ry)
    mx = _masked_mean(rx, m, dim=1, keepdim=True)
    my = _masked_mean(ry, m, dim=1, keepdim=True)
    cx = torch.where(m, rx - mx, torch.zeros_like(rx))
    cy = torch.where(m, ry - my, torch.zeros_like(ry))
    n = m.sum(dim=1).clamp_min(1).to(x.dtype)
    cov = (cx * cy).sum(dim=1) / n
    vx = (cx * cx).sum(dim=1) / n
    vy = (cy * cy).sum(dim=1) / n
    corr = cov / torch.sqrt(vx * vy + EPS)
    return torch.where(m.sum(dim=1) >= 2, corr, torch.full_like(corr, float("nan")))


@torch.no_grad()
def _ts_normalize_gpu(factor: torch.Tensor, window: int,
                      min_periods: Optional[int] = None) -> torch.Tensor:
    """GPU 时序标准化: 每日每股因子值对自身近 window 日历史做滚动分位 [0,1]

    对齐 CPU run_ic_timeseries_panel 的 `factor.rolling(window, min_periods).rank(pct=True)`
    (含当日, 无前视): 窗口内非 NaN 值按平均秩计算 pct, 有效样本 < min_periods 输出 NaN。
    输入/输出均为 [T, N] (日期 x 股票)。
    """
    torch = _torch_mod()
    if min_periods is None:
        min_periods = max(20, window // 2)
    T, N = factor.shape
    if T <= min_periods:
        return torch.full_like(factor, float("nan"))
    xs = factor.permute(1, 0).unsqueeze(0)            # [1, N, T]
    pad = torch.nn.functional.pad(xs, (window - 1, 0), value=float("nan"))
    windows = pad.unfold(2, window, 1)                # [1, N, T, window]
    valid = torch.isfinite(windows)
    cnt = valid.sum(dim=-1, dtype=torch.float32)      # 窗口有效数
    cur = windows[..., -1:]                           # 当日值 [1,N,T,1]
    below = ((windows < cur) & valid).sum(dim=-1, dtype=torch.float32)
    ties = ((windows == cur) & valid).sum(dim=-1, dtype=torch.float32)
    rank = below + (ties - 1.0).clamp_min(0.0) / 2.0 + 1.0   # 平均秩(1-based)
    denom = (cnt - 1.0).clamp_min(1.0)
    pct = ((rank - 1.0) / denom).clamp(0.0, 1.0)
    pct = torch.where(cnt >= min_periods, pct, torch.full_like(pct, float("nan")))
    out = pct[0]                                      # [N, T]
    out = torch.where(torch.isfinite(factor.permute(1, 0)),
                      out, torch.full_like(out, float("nan")))
    return out.permute(1, 0)                          # [T, N]


def mean_rank_ic(factor: torch.Tensor,
                 target: torch.Tensor,
                 mask: Optional[torch.Tensor] = None,
                 mc_proxy: Optional[torch.Tensor] = None,
                 style_proxy: Optional[torch.Tensor] = None,
                 fitness_mode: str = "rank_ic",
                 ts_normalize_window: Optional[int] = None) -> float:
    """QuantGplearn 语义适应度 (阶段5.2 #9 扩展: 支持 rank_icir / long_short_sharpe 多目标)

    来源: QuantGplearn tensor_fitness.py rank_icir / long_short_sharpe (GinkGO 策略3, arXiv:2002.08245)
    fitness_mode: "rank_ic"(默认, 原行为), "rank_icir"(IC 均值/IC 标准差, 抗噪), "long_short_sharpe"(多空组合夏普)
    ts_normalize_window: technical_ts 候选的时序标准化窗口 (None 不启用)。
        启用时先对因子做 GPU 滚动分位标准化(每股票自身历史分位), 再走中性化/截面管线,
        与 CPU run_ic_timeseries_panel 的 ts_normalize_window 口径一致。
    """
    torch = _torch_mod()
    if ts_normalize_window:
        factor = _ts_normalize_gpu(factor, ts_normalize_window)
    if style_proxy is not None:
        # 阶段5.2 #6 多因子风格中性化 (华泰): 优先于单市值
        factor = neutralize_by_styles(factor, style_proxy)
    elif mc_proxy is not None:
        factor = neutralize_by_marketcap(factor, mc_proxy)
    factor = normalize_by_day(factor, mask)
    ic = batch_spearmanr(factor, target, mask)          # [T] 逐截面 RankIC

    if fitness_mode == "rank_icir":
        # ICIR = mean(IC) / std(IC) (对齐 QuantGplearn rank_icir, 无偏)
        mean_ic = torch.nanmean(ic)
        std_ic = torch.sqrt(torch.nanmean((ic - mean_ic) ** 2))
        out = torch.clamp(mean_ic / (std_ic + EPS), -100.0, 100.0)
    elif fitness_mode == "long_short_sharpe":
        # 多空组合夏普: 每日截面 top-k 做多 / bottom-k 做空, 净收益/标准差 * sqrt(252)
        # 对齐 QuantGplearn long_short_sharpe (quantile=0.3, fee=3e-4, annualization=252)
        # 两端都基于因子预测值(对齐 QuantGplearn 用 pred 不做空 target), 收益来源为 target
        mask2 = torch.isfinite(factor) & torch.isfinite(target)
        T, N = factor.shape
        k = max(1, int(round(N * 0.3)))
        k = min(k, max(1, N // 2))
        fact_fill = torch.where(mask2, factor, torch.full_like(factor, -float("inf")))
        # 多空两端都用因子值: top-k 做多, bottom-k 做空 (对齐 QuantGplearn pred 选股)
        long_idx = torch.topk(fact_fill, k=k, dim=1).indices
        short_idx = torch.topk(-fact_fill, k=k, dim=1).indices
        weights = torch.zeros_like(factor)
        weights.scatter_(1, long_idx, 0.5 / k)
        weights.scatter_(1, short_idx, -0.5 / k)
        valid_cnt = mask2.sum(dim=1)
        weights = torch.where(mask2 & (valid_cnt[:, None] >= 2 * k), weights, torch.zeros_like(weights))
        gross_ret = (weights * torch.where(torch.isfinite(target), target, torch.zeros_like(target))).sum(dim=1)
        turnover = torch.zeros(T, device=factor.device, dtype=factor.dtype)
        if T > 1:
            turnover[0] = torch.abs(weights[0]).sum()
            turnover[1:] = torch.abs(weights[1:] - weights[:-1]).sum(dim=1)
        net_ret = gross_ret - turnover * 3e-4
        vr = torch.isfinite(net_ret)
        if vr.sum() < 3:
            return 0.0
        r = net_ret[vr]
        out = r.mean() / (r.std(unbiased=False) + EPS) * math.sqrt(252.0)
    else:
        # 默认 rank_ic (原行为)
        out = torch.nanmean(ic)

    return 0.0 if not torch.isfinite(out) else float(out.item())


def gpu_rank_ic_metrics(factor: torch.Tensor,
                        target: torch.Tensor,
                        mask: Optional[torch.Tensor] = None,
                        mc_proxy: Optional[torch.Tensor] = None,
                        style_proxy: Optional[torch.Tensor] = None) -> Optional[dict]:
    """GPU 完整展示指标 (与 CPU run_ic_timeseries_panel 口径对齐)

    用于 GPU 求值路径在 GPU 上直接产出候选的完整展示指标, 避免"GPU 求值 +
    CPU 回填"的割裂:
      rank_ic_mean: 逐日截面 RankIC 均值
      rank_ic_ir:   RankIC 均值 / 标准差 (ddof=1, 与 CPU 一致)
      layered:      {"long_short": 分5档 top-bot 层日均多空收益}
      samples:      有效截面数

    中性化/标准化口径与 mean_rank_ic 完全一致 (风格中性化 > 市值中性化 > 原值),
    因此返回的 rank_ic_mean 与 mean_rank_ic(rank_ic) 一致。
    """
    torch = _torch_mod()
    try:
        if style_proxy is not None:
            factor = neutralize_by_styles(factor, style_proxy)
        elif mc_proxy is not None:
            factor = neutralize_by_marketcap(factor, mc_proxy)
        factor = normalize_by_day(factor, mask)

        ic = batch_spearmanr(factor, target, mask)  # [T] 逐日截面 RankIC
        ok = torch.isfinite(ic)
        n_day = int(ok.sum().item())
        if n_day == 0 or not bool(ok.any()):
            return None
        mean_ic = ic[ok].mean()
        rank_ic_mean = float(mean_ic.item()) if torch.isfinite(mean_ic) else None
        rank_ic_ir = None
        if n_day > 1:
            var = ((ic[ok] - mean_ic) ** 2).sum() / (n_day - 1)  # ddof=1 对齐 CPU
            std = var.sqrt()
            if std.item() > EPS:
                ir = mean_ic / std
                rank_ic_ir = float(ir.item()) if torch.isfinite(ir) else None

        # 分层多空: 每截面按因子分 5 档, top - bottom 层目标未来收益日均
        layered = {"long_short": None}
        try:
            T, N = factor.shape
            valid = mask if mask is not None else (
                torch.isfinite(factor) & torch.isfinite(target))
            f_safe = torch.where(
                torch.isfinite(factor), factor,
                torch.full_like(factor, float("-inf")))
            sorted_idx = torch.argsort(f_safe, dim=1)
            ranks = torch.empty_like(sorted_idx, dtype=factor.dtype)
            r_ar = torch.arange(N, device=factor.device, dtype=factor.dtype).unsqueeze(0).expand(T, N)
            ranks.scatter_(1, sorted_idx, r_ar)
            bucket = (ranks * 5 // max(N, 1)).long().clamp(0, 4)
            t_safe = torch.where(torch.isfinite(target), target, torch.zeros_like(target))
            sums = torch.zeros((T, 5), dtype=factor.dtype, device=factor.device)
            cnts = torch.zeros((T, 5), dtype=factor.dtype, device=factor.device)
            for li in range(5):
                m = (bucket == li) & valid
                cnts[:, li] = m.sum(dim=1).to(factor.dtype)
                sums[:, li] = torch.where(m, t_safe, torch.zeros_like(t_safe)).sum(dim=1)
            means = torch.where(cnts > 0, sums / cnts.clamp_min(1.0),
                                torch.full_like(sums, float("nan")))
            good = (cnts.min(dim=1).values > 0) & (valid.sum(dim=1) >= 5)
            ls_ok = (means[:, 4] - means[:, 0])[good]
            if ls_ok.numel() > 0:
                ls_mean = torch.nanmean(ls_ok)
                if torch.isfinite(ls_mean):
                    layered["long_short"] = round(float(ls_mean.item()), 6)
        except Exception:
            layered = {"long_short": None}

        return {
            "rank_ic_mean": rank_ic_mean,
            "rank_ic_ir": rank_ic_ir,
            "layered": layered,
            "samples": n_day,
        }
    except Exception:
        return None


def batch_mean_rank_ic(factors: List[torch.Tensor],
                       target: torch.Tensor,
                       mask: Optional[torch.Tensor] = None,
                       mc_proxy: Optional[torch.Tensor] = None,
                       style_proxy: Optional[torch.Tensor] = None,
                       fitness_mode: str = "rank_ic") -> List[float]:
    """批量计算多个因子面板的 mean_rank_ic (每个因子独立, 便于调用方映射)"""
    return [mean_rank_ic(f, target, mask, mc_proxy, style_proxy, fitness_mode) for f in factors]


# ============================================================
# 表达式树编译 (dict 树 -> torch 求值函数)
# ============================================================

class PanelTensorCompiler:
    """把 factor_gp 的 dict 表达式树编译为 torch 求值函数

    编译结果: 一个可调用 f(panel: TensorPanel) -> [T, N] 因子值张量。
    同一表达式编译一次后可重复执行(缓存由调用方持有), 全程纯 torch。
    """

    def __init__(self, panel: TensorPanel):
        self.panel = panel
        self.T, self.N = panel.shape[0], panel.shape[1]
        self.device = panel.device
        self.dtype = panel.values.dtype

    def _const_tensor(self, val) -> torch.Tensor:
        return torch.full((self.T, self.N), float(val), dtype=self.dtype, device=self.device)

    def compile(self, node: Dict[str, Any]) -> Callable[[], torch.Tensor]:
        """编译节点, 返回无参函数 f() -> [T,N] (panel 已绑定)"""
        torch = _torch_mod()
        t = node["t"]
        if t == "field":
            fname = node["name"]
            idx = self.panel._field_pos.get(fname)
            if idx is None:
                raise ValueError(f"GPU 求值器不支持字段: {fname}")
            return (lambda i=idx: self.panel.values[:, :, i])
        if t == "const":
            v = float(node["val"])
            return (lambda vv=v: self._const_tensor(vv))
        if t == "op":
            name = node["name"]
            fn = TORCH_ARITH.get(name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持算术算子: {name}")
            subs = [self.compile(a) for a in node["args"]]
            if len(subs) == 1:
                return (lambda: fn(subs[0]()))
            if len(subs) == 2:
                return (lambda: fn(subs[0](), subs[1]()))
            if len(subs) == 3:
                # 三元算子 (gate / if_gt): 3 个 args 时调用 TORCH_ARITH 的三参实现
                return (lambda: fn(subs[0](), subs[1](), subs[2]()))
            raise ValueError(f"GPU 求值器不支持 {len(subs)} 元算术算子: {name}")
        if t == "ts":
            name = node["name"]
            fn = TORCH_TS.get(name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持带窗时序算子: {name}")
            arg_f = self.compile(node["arg"])
            window = int(node["window"])
            return (lambda: fn(arg_f(), window))
        if t == "ts_multi":
            # 多参带窗时序算子 (双字段/子表达式 + 窗口): ts_Corr(字段A,字段B,窗口)
            name = node["name"]
            fn = TORCH_TS.get(name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持多参时序算子: {name}")
            subs = [self.compile(a) for a in node["args"]]
            window = int(node["window"])
            return (lambda: fn(subs[0](), subs[1](), window))
        if t == "ts_params":
            # 多定参时序算子 (字段/子表达式 + 尾部多个定参): ts_MACD_HIST(Close,12,26,9) 等
            name = node["name"]
            fn = TORCH_TS.get(name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持多定参时序算子: {name}")
            subs = [self.compile(a) for a in node["args"]]
            params = list(node.get("params") or [])
            return (lambda: fn(*(f() for f in subs), *params))
        if t == "ts_raw":
            name = node["name"]
            fn = TORCH_TS_RAW.get(name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持无窗时序算子: {name}")
            arg_f = self.compile(node["arg"])
            return (lambda: fn(arg_f()))
        if t == "cs":
            name = node["name"]
            fn = TORCH_CS.get(name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持截面算子: {name}")
            arg_f = self.compile(node["arg"])
            return (lambda: fn(arg_f()))
        if t == "base_leaf":
            # 基类叶子: 从引擎 BASE_OPERATOR_MAP 取算子+所需字段, 绑定多字段张量后调用
            # (name -> (ts_算子, [字段], 参数个数)); 参数化基类带窗口参数, 固定参数基类用算子默认。
            name = node["name"]
            entry = BASE_OPERATOR_MAP.get(name)
            if entry is None:
                raise ValueError(f"GPU 求值器不支持基类叶子: {name}")
            op_name, fields, _nparams = entry
            fn = TORCH_TS.get(op_name)
            if fn is None:
                raise ValueError(f"GPU 求值器不支持基类叶子算子: {op_name}")
            field_tensors = []
            for f in fields:
                idx = self.panel._field_pos.get(f)
                if idx is None:
                    raise ValueError(f"GPU 求值器面板缺字段: {f}")
                field_tensors.append(self.panel.values[:, :, idx])
            params = node.get("params") or []
            # 特殊基类包裹 (对齐 factor_engine._make_base_callable):
            #   reversal = -ts_PctChange;  atr = ts_ATR / Close (Close 的 0 -> NaN)
            if name == "reversal":
                if params:
                    window = int(params[0])
                    return (lambda: -fn(*field_tensors, window))
                return (lambda: -fn(*field_tensors))
            if name == "atr":
                close = self.panel.values[:, :, self.panel._field_pos["Close"]]
                safe_close = torch.where(close != 0.0, close,
                                         torch.full_like(close, float("nan")))
                if params:
                    window = int(params[0])
                    return (lambda: fn(*field_tensors, window) / safe_close)
                return (lambda: fn(*field_tensors) / safe_close)
            if params:
                window = int(params[0])
                return (lambda: fn(*field_tensors, window))
            return (lambda: fn(*field_tensors))
        if t == "ts_fixed":
            raise ValueError("GPU 求值器不支持 ts_fixed (L2 未启用)")
        raise ValueError(f"GPU 求值器未知节点类型: {t}")


# ============================================================
# 高层: 对一批表达式做 GPU 整树求值 + 适应度
# ============================================================

def gpu_supported(expr_tree: Dict[str, Any]) -> bool:
    """检查表达式树是否全部可 GPU 化 (任一不支持节点返回 False)"""
    t = expr_tree["t"]
    if t == "field":
        # 阶段5.1.1 修复: 校验字段名在 GPU 字段表内 (warm 公式字符串作字段/未知字段
        # 会被误判可 GPU → compile 抛异常 → 个体判死; 此处返回 False 使树回退 CPU evaluate_expression)
        return expr_tree["name"] in _GPU_FIELDS
    if t == "const":
        return True
    if t == "op":
        name = expr_tree["name"]
        if name not in TORCH_ARITH:
            return False
        return all(gpu_supported(a) for a in expr_tree["args"])
    if t == "ts":
        name = expr_tree["name"]
        if name not in TORCH_TS:
            return False
        return gpu_supported(expr_tree["arg"])
    if t == "ts_multi":
        # 多参带窗时序算子 (双字段+窗口): 算子须在 GPU 表中, 且两个子参数均可 GPU 化
        name = expr_tree["name"]
        if name not in TORCH_TS:
            return False
        return all(gpu_supported(a) for a in expr_tree["args"])
    if t == "ts_params":
        # 多定参时序算子 (字段/子表达式 + 多个定参): 算子须在 GPU 表中, 子参数均可 GPU 化
        name = expr_tree["name"]
        if name not in TORCH_TS:
            return False
        return all(gpu_supported(a) for a in expr_tree["args"])
    if t == "ts_raw":
        return expr_tree["name"] in TORCH_TS_RAW and gpu_supported(expr_tree["arg"])
    if t == "cs":
        name = expr_tree["name"]
        if name not in TORCH_CS:
            return False
        return gpu_supported(expr_tree["arg"])
    if t == "base_leaf":
        entry = BASE_OPERATOR_MAP.get(expr_tree["name"])
        if entry is None:
            return False
        return entry[0] in TORCH_TS
    return False


def _torch_mod():
    import torch as _m
    return _m


# ============================================================
# 高层: 对字符串表达式列表做新语义适应度 (供 OOS/WF 复核, 与主循环口径一致)
# ============================================================

_GPU_FIELDS = ["Open", "High", "Low", "Close", "Volume", "Amount", "VWAP",
               "Turnover", "IdioRet", "Value", "TotalRet"]


def batch_mean_rank_ic_exprs(exprs: List[str],
                             panel: Dict[str, pd.DataFrame],
                             rebal_period: int = 21,
                             mc_lookback: Optional[int] = None,
                             device: Optional[str] = None,
                             style_cfg: Optional[Dict[str, Any]] = None,
                             fitness_mode: str = "rank_ic",
                             ts_normalize_window: Optional[int] = None) -> List[float]:
    """对一批表达式字符串, 用 evaluate_expression(pandas) 求因子面板,
    再按 QuantGplearn 语义 mean_rank_ic 计算适应度 (与主循环 GPU 求值器同口径)。

    候选为字符串(非 dict 树), 不直接 GPU 求值, 故走 evaluate_expression 求值;
    语义与新主循环完全一致(mean_rank_ic + normalize_by_day + 市值/风格中性化可选)。
    style_cfg: 阶段5.2 #6 风格中性化配置 dict, 如
        {"mc_lookback":20,"ret_window":20,"vol_window":20,"use_turnover":True,
         "use_industry":True,"industry_map":{...}}; 提供时用多因子风格回归。
    fitness_mode: 阶段5.2 #9 适应度目标 ("rank_ic"默认 / "rank_icir" / "long_short_sharpe")
    ts_normalize_window: technical_ts 候选的时序标准化窗口; 仅对判定为 technical_ts
        的表达式应用 (GPU 滚动分位), technical 不加, 与 fitness_expr 按类型路由一致。
    """
    from lib.factor_engine import evaluate_expression, _is_technical_ts_expression
    torch = _torch_mod()
    if not exprs:
        return []
    tp = TensorPanel.from_panel(panel, fields=_GPU_FIELDS, device=device)
    target = tp.future_returns(rebal_period)
    mask = tp._global_mask(tp.values)
    mc = tp.marketcap_proxy(mc_lookback) if mc_lookback else None
    # 阶段5.2 #6: 多因子风格中性化 (优先于单市值)
    style = None
    if style_cfg:
        style = tp.style_proxy(
            mc_lookback=style_cfg.get("mc_lookback", mc_lookback),
            ret_window=style_cfg.get("ret_window", 20),
            vol_window=style_cfg.get("vol_window", 20),
            use_turnover=style_cfg.get("use_turnover", True),
            use_industry=style_cfg.get("use_industry", True),
            industry_map=style_cfg.get("industry_map"),
        )
    out: List[float] = []
    for expr in exprs:
        try:
            fv = evaluate_expression(expr, panel)
            wide = fv.reindex(index=tp.dates, columns=tp.symbols)
            _arr = wide.to_numpy(dtype=np.float64)
            if not _arr.flags.writeable:
                _arr = _arr.copy()  # PyTorch 张量要求可写, 只读缓冲需复制
            f = torch.as_tensor(_arr, dtype=torch.float64, device=target.device)
            _tsw = ts_normalize_window if (
                ts_normalize_window and _is_technical_ts_expression(expr)) else None
            ic = mean_rank_ic(f, target, mask, mc, style, fitness_mode, ts_normalize_window=_tsw)
        except Exception:
            ic = float("nan")
        out.append(ic)
    return out
