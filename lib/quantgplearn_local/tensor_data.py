"""Tensor data containers for GPU/CPU factor mining.

This module intentionally has no dependency on qlib.  It converts the panel
DataFrame format used by QuantGplearn into dense tensors with shape [T, N, F],
where T is time, N is instrument/security and F is feature count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

try:  # torch is optional for the legacy CPU package path
    import torch
except Exception:  # pragma: no cover - handled at runtime by _require_torch
    torch = None


def _require_torch():
    if torch is None:
        raise ImportError(
            "GpuSymbolicTransformer requires PyTorch. Install torch or use the "
            "legacy CPU SymbolicTransformer."
        )
    return torch


@dataclass
class TensorPanelData:
    """Dense tensor representation of panel data.

    Parameters
    ----------
    values:
        Tensor with shape ``[T, N, F]``.
    target:
        Optional tensor with shape ``[T, N]``.
    mask:
        Boolean tensor with shape ``[T, N]``. True means the sample is valid.
    dates:
        Ordered time labels corresponding to dimension T.
    symbols:
        Ordered symbol/security labels corresponding to dimension N.
    feature_names:
        Feature names corresponding to dimension F.
    """

    values: "torch.Tensor"
    target: Optional["torch.Tensor"]
    mask: "torch.Tensor"
    dates: pd.Index
    symbols: pd.Index
    feature_names: list[str]
    time_index: str = "datetime"
    security_index: str = "symbol"

    @property
    def device(self):
        return self.values.device

    @property
    def dtype(self):
        return self.values.dtype

    @property
    def shape(self) -> tuple[int, int, int]:
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

    def to(self, device: str | None = None, dtype=None) -> "TensorPanelData":
        t = _require_torch()
        if dtype is None:
            dtype = self.values.dtype
        if device is None:
            device = self.values.device
        return TensorPanelData(
            values=self.values.to(device=device, dtype=dtype),
            target=None if self.target is None else self.target.to(device=device, dtype=dtype),
            mask=self.mask.to(device=device),
            dates=self.dates,
            symbols=self.symbols,
            feature_names=list(self.feature_names),
            time_index=self.time_index,
            security_index=self.security_index,
        )

    @classmethod
    def from_panel_df(
        cls,
        df: pd.DataFrame,
        feature_names: Sequence[str],
        target_col: Optional[str] = None,
        y: Optional[Sequence[float] | pd.Series | pd.DataFrame] = None,
        time_index: str = "datetime",
        security_index: str = "symbol",
        device: str = "cuda",
        dtype=None,
        sort: bool = True,
    ) -> "TensorPanelData":
        """Build a tensor panel from a QuantGplearn-style DataFrame.

        ``df`` may either contain ``time_index`` and ``security_index`` columns
        or use them as a two-level MultiIndex. The returned dense layout follows
        sorted unique times and symbols.
        """
        t = _require_torch()
        if dtype is None:
            dtype = t.float32
        if not isinstance(df, pd.DataFrame):
            raise TypeError("df must be a pandas DataFrame")
        feature_names = list(feature_names)
        missing = [c for c in feature_names if c not in df.columns]
        if missing:
            raise ValueError(f"feature columns not found: {missing}")

        panel = _ensure_panel_index(df.copy(), time_index, security_index)
        if sort:
            panel = panel.sort_index()

        if target_col is not None:
            if target_col not in panel.columns:
                raise ValueError(f"target_col {target_col!r} is not in df.columns")
            target_series = panel[target_col]
        elif y is not None:
            if isinstance(y, pd.DataFrame):
                if y.shape[1] != 1:
                    raise ValueError("y DataFrame must have exactly one column")
                y = y.iloc[:, 0]
            if isinstance(y, pd.Series):
                yy = y.copy()
                if not isinstance(yy.index, pd.MultiIndex):
                    yy.index = panel.index
                yy = _ensure_panel_index(yy.to_frame("_target"), time_index, security_index)["_target"]
                target_series = yy.reindex(panel.index)
            else:
                arr = np.asarray(y, dtype=float)
                if len(arr) != len(panel):
                    raise ValueError("len(y) must match len(df)")
                target_series = pd.Series(arr, index=panel.index, name="_target")
        else:
            target_series = None

        dates = pd.Index(panel.index.get_level_values(time_index).unique(), name=time_index)
        symbols = pd.Index(panel.index.get_level_values(security_index).unique(), name=security_index)

        feature_arrays = []
        for col in feature_names:
            wide = panel[col].unstack(security_index).reindex(index=dates, columns=symbols)
            feature_arrays.append(wide.to_numpy(dtype=np.float32, copy=False))
        values_np = np.stack(feature_arrays, axis=-1)  # [T, N, F]

        values = t.as_tensor(values_np, dtype=dtype, device=device)
        finite_features = t.isfinite(values).all(dim=-1)

        if target_series is not None:
            target_wide = target_series.unstack(security_index).reindex(index=dates, columns=symbols)
            target_np = target_wide.to_numpy(dtype=np.float32, copy=True)
            target = t.as_tensor(target_np, dtype=dtype, device=device)
            mask = finite_features & t.isfinite(target)
        else:
            target = None
            mask = finite_features

        return cls(
            values=values,
            target=target,
            mask=mask,
            dates=dates,
            symbols=symbols,
            feature_names=feature_names,
            time_index=time_index,
            security_index=security_index,
        )

    def factor_to_dataframe(self, factor: "torch.Tensor", name: str = "factor") -> pd.DataFrame:
        """Convert a ``[T, N]`` factor tensor to a long panel DataFrame."""
        t = _require_torch()
        if factor.shape != self.mask.shape:
            raise ValueError(f"factor shape {tuple(factor.shape)} != mask shape {tuple(self.mask.shape)}")
        values = factor.detach().to("cpu").numpy()
        wide = pd.DataFrame(values, index=self.dates, columns=self.symbols)
        long = wide.stack().rename(name).to_frame()
        long.index = long.index.set_names([self.time_index, self.security_index])
        return long

    def factors_to_dataframe(self, factors: Sequence["torch.Tensor"], names: Optional[Sequence[str]] = None) -> pd.DataFrame:
        if names is None:
            names = [f"factor_{i}" for i in range(len(factors))]
        frames = [self.factor_to_dataframe(f, name=n) for f, n in zip(factors, names)]
        return pd.concat(frames, axis=1)


def _ensure_panel_index(df: pd.DataFrame, time_index: str, security_index: str) -> pd.DataFrame:
    """Return a DataFrame indexed by ``[time_index, security_index]``."""
    if isinstance(df.index, pd.MultiIndex):
        names = list(df.index.names)
    else:
        names = [df.index.name]

    has_time_col = time_index in df.columns
    has_sec_col = security_index in df.columns
    has_time_idx = time_index in names
    has_sec_idx = security_index in names

    if not (has_time_col or has_time_idx):
        raise ValueError(f"time_index {time_index!r} not found in columns or index")
    if not (has_sec_col or has_sec_idx):
        raise ValueError(f"security_index {security_index!r} not found in columns or index")

    if has_time_col and has_sec_col:
        df = df.set_index([time_index, security_index])
    elif has_time_col and not has_time_idx:
        df = df.set_index(time_index, append=True)
    elif has_sec_col and not has_sec_idx:
        df = df.set_index(security_index, append=True)

    if not isinstance(df.index, pd.MultiIndex):
        raise ValueError("panel data must have a MultiIndex after normalization")
    df = df.reorder_levels([time_index, security_index])
    if df.index.has_duplicates:
        raise ValueError("panel index contains duplicate (time, security) pairs")
    return df
