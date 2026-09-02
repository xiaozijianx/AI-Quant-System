from copy import deepcopy
import warnings

import numpy as np
import pandas as pd

try:
    import numba as nb
except Exception:  # pragma: no cover - numba is optional at import time
    nb = None
from joblib import wrap_non_picklable_objects

warnings.filterwarnings("ignore")

__all__ = [
    "make_function",
    "raw_function_list",
    "section_function",
    "time_series_function",
    "panel_function",
    "all_function",
]

NoneType = type(None)
EPS = 1e-12
para_list = [24, 24 * 3, 24 * 7, 24 * 14, 24 * 21, 24 * 30]


class _Function(object):
    """Function metadata used by the genetic-programming tree builder.

    ``torch_function`` is optional and is only used by the new GPU execution
    path. The legacy NumPy/Pandas path remains unchanged.
    """

    def __init__(self, function, name, arity, param_type=None,
                 return_type="number", function_type="all", torch_function=None):
        self.function = function
        self.torch_function = torch_function
        self.name = name
        self.arity = arity
        if param_type is None:
            param_type = [
                {
                    "vector": {"number": (None, None)},
                    "scalar": {"int": (None, None), "float": (None, None)},
                }
                for _ in range(arity)
            ]
        if len(param_type) != arity:
            raise ValueError(
                "length of param_type should be equal to arity, it should be "
                "{}, not {}".format(arity, len(param_type))
            )
        self.param_type = deepcopy(param_type)
        if return_type not in ("number", "category"):
            raise ValueError(
                "return_type of function {} should be number or category, NOT {}"
                .format(name, return_type)
            )
        self.return_type = return_type
        self.function_type = function_type

    def __call__(self, *args):
        converted = []
        for param, param_type in zip(args, self.param_type):
            if set(param_type.keys()) == {"scalar"} and isinstance(param, (list, np.ndarray)):
                converted.append(np.asarray(param).ravel()[0])
            else:
                converted.append(param)
        return self.function(*converted)

    def call_torch(self, *args):
        if self.torch_function is None:
            raise NotImplementedError(f"Function {self.name!r} has no torch backend")
        converted = []
        for param, param_type in zip(args, self.param_type):
            if set(param_type.keys()) == {"scalar"} and hasattr(param, "numel"):
                converted.append(param.flatten()[0] if param.numel() else param)
            else:
                converted.append(param)
        return self.torch_function(*converted)

    def add_range(self, const_range):
        """Apply global scalar ranges while preserving explicit value lists."""
        if const_range is None:
            for i, param in enumerate(self.param_type):
                if "vector" not in param:
                    raise ValueError("for None const range, vector type should in all function param")
                self.param_type[i].pop("scalar", None)
            return

        if not isinstance(const_range, tuple) or len(const_range) != 2:
            raise ValueError("const_range must be a tuple with length two")
        range_min, range_max = const_range
        if not isinstance(range_min, (int, float)) or not isinstance(range_max, (int, float)):
            raise ValueError("const_range bounds must be int or float")
        if range_min > range_max:
            raise ValueError("const_range left should le right")

        for param in self.param_type:
            scalar = param.get("scalar")
            if not scalar:
                continue
            if "int" in scalar and isinstance(scalar["int"], tuple):
                left, right = scalar["int"]
                left = int(range_min) if left is None else int(left)
                right = int(range_max) if right is None else int(right)
                scalar["int"] = (left, right)
            if "float" in scalar:
                left, right = scalar["float"]
                left = float(range_min) if left is None else float(left)
                right = float(range_max) if right is None else float(right)
                scalar["float"] = (left, right)

    def is_point_mutation(self, candidate_func):
        if not isinstance(candidate_func, _Function):
            raise ValueError("wrong type, it should be _Function style")
        if len(candidate_func.param_type) != len(self.param_type):
            return False
        return self.return_type == candidate_func.return_type


def _as_float_array(x):
    return np.asarray(x, dtype=float)


def _as_int_window(d, n=None):
    if isinstance(d, (np.ndarray, list, tuple, pd.Series)):
        d = np.asarray(d).ravel()[0]
    d = int(d)
    d = max(d, 1)
    if n is not None:
        d = min(d, max(int(n), 1))
    return d


def _safe_series(x):
    return pd.Series(_as_float_array(x))


def _rank_pct(values):
    values = _as_float_array(values)
    mask = np.isfinite(values)
    out = np.full(values.shape, np.nan, dtype=float)
    if mask.sum() == 0:
        return out
    out[mask] = pd.Series(values[mask]).rank(method="average", pct=True).values
    return out


def _safe_zscore(values):
    values = _as_float_array(values)
    mean = np.nanmean(values)
    std = np.nanstd(values, ddof=1)
    if not np.isfinite(std) or std < EPS:
        return np.zeros_like(values, dtype=float)
    return (values - mean) / std


def _safe_scale(values):
    values = _as_float_array(values)
    denom = np.nansum(np.abs(values))
    if not np.isfinite(denom) or denom < EPS:
        return np.zeros_like(values, dtype=float)
    return values / denom


if nb is not None:
    @nb.njit(cache=True)
    def _rolling_argmax_fast(arr, window):
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            out[i] = np.nan
        for i in range(window - 1, n):
            best = 0.0
            best_idx = -1
            found = False
            start = i - window + 1
            for j in range(window):
                v = arr[start + j]
                if np.isfinite(v):
                    if (not found) or v > best:
                        best = v
                        best_idx = j
                        found = True
            if found:
                out[i] = float(best_idx)
        return out

    @nb.njit(cache=True)
    def _rolling_argmin_fast(arr, window):
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            out[i] = np.nan
        for i in range(window - 1, n):
            best = 0.0
            best_idx = -1
            found = False
            start = i - window + 1
            for j in range(window):
                v = arr[start + j]
                if np.isfinite(v):
                    if (not found) or v < best:
                        best = v
                        best_idx = j
                        found = True
            if found:
                out[i] = float(best_idx)
        return out

    @nb.njit(cache=True)
    def _rolling_rank_last_fast(arr, window):
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            out[i] = np.nan
        for i in range(window - 1, n):
            last = arr[i]
            if not np.isfinite(last):
                continue
            start = i - window + 1
            less = 0
            equal = 0
            count = 0
            for j in range(window):
                v = arr[start + j]
                if np.isfinite(v):
                    count += 1
                    if v < last:
                        less += 1
                    elif v == last:
                        equal += 1
            if count > 0:
                rank_avg = less + (equal + 1.0) / 2.0
                out[i] = rank_avg / count
        return out

    @nb.njit(cache=True)
    def _rolling_freq_fast(arr, window):
        n = arr.shape[0]
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            out[i] = np.nan
        for i in range(window - 1, n):
            last = arr[i]
            if not np.isfinite(last):
                continue
            start = i - window + 1
            cnt = 0
            for j in range(window):
                if arr[start + j] == last:
                    cnt += 1
            out[i] = float(cnt)
        return out
else:
    def _rolling_argmax_fast(arr, window):
        arr = np.asarray(arr, dtype=float)
        out = np.full(arr.shape[0], np.nan, dtype=float)
        for i in range(window - 1, arr.shape[0]):
            win = arr[i - window + 1:i + 1]
            if np.isfinite(win).any():
                out[i] = float(np.nanargmax(win))
        return out

    def _rolling_argmin_fast(arr, window):
        arr = np.asarray(arr, dtype=float)
        out = np.full(arr.shape[0], np.nan, dtype=float)
        for i in range(window - 1, arr.shape[0]):
            win = arr[i - window + 1:i + 1]
            if np.isfinite(win).any():
                out[i] = float(np.nanargmin(win))
        return out

    def _rolling_rank_last_fast(arr, window):
        arr = np.asarray(arr, dtype=float)
        out = np.full(arr.shape[0], np.nan, dtype=float)
        for i in range(window - 1, arr.shape[0]):
            win = arr[i - window + 1:i + 1]
            last = win[-1]
            mask = np.isfinite(win)
            if np.isfinite(last) and mask.any():
                less = np.sum(win[mask] < last)
                equal = np.sum(win[mask] == last)
                out[i] = (less + (equal + 1.0) / 2.0) / mask.sum()
        return out

    def _rolling_freq_fast(arr, window):
        arr = np.asarray(arr, dtype=float)
        out = np.full(arr.shape[0], np.nan, dtype=float)
        for i in range(window - 1, arr.shape[0]):
            win = arr[i - window + 1:i + 1]
            last = win[-1]
            if np.isfinite(last):
                out[i] = float(np.sum(win == last))
        return out


def _groupby(gbx, func, *args, **kwargs):
    """Apply a vector function independently to each group label."""
    gbx = np.asarray(gbx)
    if len(gbx) == 0:
        return np.array([], dtype=float)
    order = np.argsort(gbx, kind="mergesort")
    sorted_labels = gbx[order]
    sorted_args = [np.asarray(arg)[order] for arg in args]
    result = np.empty(len(gbx), dtype=float)
    starts = np.r_[0, np.flatnonzero(sorted_labels[1:] != sorted_labels[:-1]) + 1]
    ends = np.r_[starts[1:], len(gbx)]
    for start, end in zip(starts, ends):
        group_args = [arg[start:end] for arg in sorted_args]
        group_res = np.asarray(func(*group_args, **kwargs), dtype=float)
        if group_res.shape != (end - start,):
            raise ValueError("grouped function {} returned wrong shape".format(func.name))
        result[order[start:end]] = group_res
    return result


def make_function(*, function, name, arity, param_type=None, wrap=True,
                  return_type="number", function_type="all"):
    if not isinstance(arity, int):
        raise ValueError("arity must be an int, got %s" % type(arity))
    if not isinstance(name, str):
        raise ValueError("name must be a string, got %s" % type(name))
    if not isinstance(wrap, bool):
        raise ValueError("wrap must be an bool, got %s" % type(wrap))
    if param_type is None:
        param_type = [
            {
                "vector": {"number": (None, None)},
                "scalar": {"int": (None, None), "float": (None, None)},
            }
            for _ in range(arity)
        ]
    if not isinstance(param_type, list) or len(param_type) != arity:
        raise ValueError("param_type must be a list with length arity")

    param_type = deepcopy(param_type)
    vector_flag = False
    test_args = []
    for idx, param in enumerate(param_type):
        if param is None:
            param = {
                "vector": {"number": (None, None)},
                "scalar": {"int": (None, None), "float": (None, None)},
            }
            param_type[idx] = param
        if not isinstance(param, dict):
            raise ValueError("element in param_type {} must be dict".format(idx + 1))
        if "vector" in param:
            vector_flag = True
            if not isinstance(param["vector"], dict):
                raise ValueError("vector param_type must be dict")
            for lower in param["vector"]:
                if lower not in ("number", "category"):
                    raise ValueError("vector lower type must be number or category")
            test_args.append(np.ones(10, dtype=float))
        elif "scalar" in param:
            scalar = param["scalar"]
            if "int" in scalar:
                spec = scalar["int"]
                if isinstance(spec, list):
                    test_args.append(int(spec[0]))
                elif isinstance(spec, tuple) and len(spec) == 2:
                    left = 1 if spec[0] is None else int(spec[0])
                    right = left if spec[1] is None else int(spec[1])
                    test_args.append(max(left, min(right, left)))
                else:
                    raise ValueError("scalar int must be list or tuple")
            elif "float" in scalar:
                spec = scalar["float"]
                if not isinstance(spec, tuple) or len(spec) != 2:
                    raise ValueError("scalar float must be tuple")
                left = 1.0 if spec[0] is None else float(spec[0])
                right = left if spec[1] is None else float(spec[1])
                test_args.append((left + right) / 2)
            else:
                raise ValueError("scalar lower type must be int or float")
        else:
            raise ValueError("param_type element must include vector or scalar")
    if not vector_flag:
        raise ValueError("there is at least 1 vector in param_type")

    try:
        result = np.asarray(function(*test_args))
    except (ValueError, TypeError) as exc:
        raise ValueError("supplied function %s does not support arity of %d" % (name, arity)) from exc
    if result.shape != (10,):
        raise ValueError("supplied function %s does not return same shape as input vectors" % name)
    if not np.all(np.isnan(result) | np.isfinite(result)):
        raise ValueError("supplied function %s does not have numeric closure" % name)

    if wrap:
        function = wrap_non_picklable_objects(function)
    return _Function(
        function=function,
        name=name,
        arity=arity,
        param_type=param_type,
        return_type=return_type,
        function_type=function_type,
    )


def _protected_division(x1, x2):
    x1 = _as_float_array(x1)
    x2 = _as_float_array(x2)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.divide(x1, x2, out=np.ones_like(x1, dtype=float), where=np.abs(x2) > 1e-3)
    return np.where(np.isfinite(out), out, 1.0)


def _protected_sqrt(x1):
    return np.sqrt(np.abs(_as_float_array(x1)))


def _protected_log(x1):
    x1 = np.abs(_as_float_array(x1))
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(x1 > 1e-3, np.log(x1), 0.0)
    return np.where(np.isfinite(out), out, 0.0)


def _protected_inverse(x1):
    x1 = _as_float_array(x1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.divide(1.0, x1, out=np.zeros_like(x1, dtype=float), where=np.abs(x1) > 1e-3)
    return np.where(np.isfinite(out), out, 0.0)


def _sigmoid(x1):
    x1 = np.clip(_as_float_array(x1), -50, 50)
    return 1.0 / (1.0 + np.exp(-x1))


add2 = _Function(function=np.add, name="add", arity=2)
sub2 = _Function(function=np.subtract, name="sub", arity=2)
mul2 = _Function(function=np.multiply, name="mul", arity=2)
div2 = _Function(function=_protected_division, name="div", arity=2)
sqrt1 = _Function(function=_protected_sqrt, name="sqrt", arity=1)
log1 = _Function(function=_protected_log, name="log", arity=1)
neg1 = _Function(function=np.negative, name="neg", arity=1)
inv1 = _Function(function=_protected_inverse, name="inv", arity=1)
abs1 = _Function(function=np.abs, name="abs", arity=1)
max2 = _Function(function=np.maximum, name="max", arity=2)
min2 = _Function(function=np.minimum, name="min", arity=2)
sin1 = _Function(function=np.sin, name="sin", arity=1)
cos1 = _Function(function=np.cos, name="cos", arity=1)
tan1 = _Function(function=np.tan, name="tan", arity=1)
sig1 = _Function(function=_sigmoid, name="sig", arity=1)


def _ts_shift(x, d):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    out = np.full(len(x), np.nan, dtype=float)
    if d < len(x):
        out[d:] = x[:-d]
    return out


def _ts_delta(x, d):
    shifted = _ts_shift(x, d)
    return _as_float_array(x) - shifted


def _ts_mom(x, d):
    shifted = _ts_shift(x, d)
    return _protected_division(_as_float_array(x), shifted) - 1.0


def _rolling(x, d, method):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    return getattr(_safe_series(x).rolling(d), method)().values


def _ts_min(x, d):
    return _rolling(x, d, "min")


def _ts_max(x, d):
    return _rolling(x, d, "max")


def _ts_argmax(x, d):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    return _rolling_argmax_fast(x, d)



def _ts_argmin(x, d):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    return _rolling_argmin_fast(x, d)



def _ts_rank(x, d):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    return _rolling_rank_last_fast(x, d)



def _ts_sum(x, d):
    return _rolling(x, d, "sum")


def _ts_std(x, d):
    return _rolling(x, d, "std")


def _ts_mean(x, d):
    return _rolling(x, d, "mean")


def _ts_skew(x, d):
    return _rolling(x, d, "skew")


def _ts_kurt(x, d):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    return _safe_series(x).rolling(d).kurt().values


def _ts_corr(x, y, d):
    x = _as_float_array(x)
    y = _as_float_array(y)
    d = _as_int_window(d, len(x))
    return pd.Series(x).rolling(d).corr(pd.Series(y)).values


def _ts_zscore(x, d):
    mean = _ts_mean(x, d)
    std = _ts_std(x, d)
    return _protected_division(_as_float_array(x) - mean, std)


def _ts_cdlbodym(open_, close, d):
    body = _as_float_array(close) - _as_float_array(open_)
    up = np.where(body > 0, 1.0, 0.0)
    down = np.where(body < 0, 1.0, 0.0)
    return _protected_division(_ts_sum(up, d), _ts_sum(up + down, d))


def _ts_bar_bs(high, low, d):
    high = _as_float_array(high)
    low = _as_float_array(low)
    high_delta = np.r_[np.nan, np.diff(high)]
    low_delta = np.r_[np.nan, np.diff(low)]
    outside_up = np.where((high_delta > 0) & (low_delta < 0), 1.0, 0.0)
    outside_down = np.where((high_delta < 0) & (low_delta > 0), 1.0, 0.0)
    return _protected_division(_ts_sum(outside_up, d), _ts_sum(outside_up + outside_down, d))


def _ts_aroon(high, low, d):
    return (_ts_argmax(high, d) - _ts_argmin(low, d)) / _as_int_window(d, len(high))


def _ts_adx(high, low, close, d):
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    prev_close = _ts_shift(close, 1)
    tr = np.nanmax(np.vstack([np.abs(high - low), np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0)
    atr = _ts_mean(tr, d)
    up_move = np.r_[np.nan, np.diff(high)]
    down_move = -np.r_[np.nan, np.diff(low)]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = 100 * _protected_division(_ts_mean(plus_dm, d), atr)
    minus_di = 100 * _protected_division(_ts_mean(minus_dm, d), atr)
    dx = 100 * _protected_division(np.abs(plus_di - minus_di), plus_di + minus_di)
    return _ts_mean(dx, d)


def _ts_bopr(open_, high, low, close, d):
    bop = _protected_division(_as_float_array(close) - _as_float_array(open_),
                              _as_float_array(high) - _as_float_array(low))
    return _ts_mean(bop, d)


def _ts_one_ols_k(x, y, d):
    """Rolling OLS slope of y on x using rolling sums.

    This replaces the previous per-window polyfit loop with the closed-form
    beta = cov(x, y) / var(x). Windows with a near-zero denominator return 0.
    """
    x = _as_float_array(x)
    y = _as_float_array(y)
    d = _as_int_window(d, len(x))
    sx = _ts_sum(x, d)
    sy = _ts_sum(y, d)
    sxy = _ts_sum(x * y, d)
    sx2 = _ts_sum(x * x, d)
    numerator = d * sxy - sx * sy
    denominator = d * sx2 - sx * sx
    beta = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=np.abs(denominator) > EPS)
    return np.where(np.isfinite(beta), beta, 0.0)



def _ts_one_ols_resid(x, y, d):
    """Current-point residual from a rolling one-factor OLS of y on x."""
    x = _as_float_array(x)
    y = _as_float_array(y)
    d = _as_int_window(d, len(x))
    beta = _ts_one_ols_k(x, y, d)
    intercept = _ts_mean(y, d) - beta * _ts_mean(x, d)
    resid = y - (beta * x + intercept)
    return np.where(np.isfinite(resid), resid, np.nan)



def _ts_stochf(high, low, close, d):
    low_min = _ts_min(low, d)
    high_max = _ts_max(high, d)
    return _protected_division(_as_float_array(close) - low_min, high_max - low_min)


def _ts_cmo(x, d):
    delta = np.r_[np.nan, np.diff(_as_float_array(x))]
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    return _protected_division(_ts_sum(up, d) - _ts_sum(down, d), _ts_sum(up, d) + _ts_sum(down, d))


def _ts_ema(x, d):
    d = _as_int_window(d, len(x))
    return _safe_series(x).ewm(span=d, adjust=False, min_periods=d).mean().values


def _ts_rsi(x, d):
    delta = np.r_[np.nan, np.diff(_as_float_array(x))]
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    rs = _protected_division(_ts_mean(up, d), _ts_mean(down, d))
    return 100.0 - 100.0 / (1.0 + rs)


def _ts_xs_ratio(x, d):
    """Efficiency-ratio style trend strength: abs(x_t - x_{t-d}) / sum(abs(delta_1), d)."""
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    directional = np.abs(x - _ts_shift(x, d))
    volatility = _ts_sum(np.abs(x - _ts_shift(x, 1)), d)
    return _protected_division(directional, volatility)



def _ts_macd(x, d1, d2, d3):
    """Rolling-MA MACD variant from the optimized operator set."""
    d1 = _as_int_window(d1, len(x))
    d2 = _as_int_window(d2, len(x))
    d3 = _as_int_window(d3, len(x))
    short_ma = _ts_mean(x, d1)
    long_ma = _ts_mean(x, d2)
    cd = short_ma - long_ma
    return _ts_mean(cd, d3)



def _ts_atr(high, low, close, d1, d2):
    """Range expansion ratio from the optimized operator set."""
    high = _as_float_array(high)
    low = _as_float_array(low)
    close = _as_float_array(close)
    d1 = _as_int_window(d1, len(high))
    d2 = _as_int_window(d2, len(high))
    high_max = _ts_max(high, d1)
    low_min = _ts_min(low, d1)
    prev_close = _ts_shift(close, d1)
    tr = np.nanmax(np.vstack([
        np.abs(high_max - prev_close),
        np.abs(low_min - prev_close),
        high_max - low_min,
    ]), axis=0)
    return _protected_division(_ts_mean(tr, d2), close)



def _ts_hedge(x, y, d1, d2):
    beta = _ts_one_ols_k(y, x, d1)
    resid = _as_float_array(x) - beta * _as_float_array(y)
    return _ts_zscore(resid, d2)


def _ts_bband(x, d1, d2):
    return _ts_mean(x, d1) + _as_int_window(d2, len(x)) * _ts_std(x, d1)


def _ts_freq(x, d):
    x = _as_float_array(x)
    d = _as_int_window(d, len(x))
    return _rolling_freq_fast(x, d)



def _cs_rank(x):
    return _rank_pct(x)


def _cs_zscore(x):
    return _safe_zscore(x)


def _cs_demean(x):
    x = _as_float_array(x)
    return x - np.nanmean(x)


def _cs_scale(x):
    return _safe_scale(x)


def _cs_winsorize(x):
    x = _as_float_array(x)
    if np.isfinite(x).sum() == 0:
        return x
    lower, upper = np.nanpercentile(x, [5, 95])
    return np.clip(x, lower, upper)


def _num_param():
    return [
        {"vector": {"number": (None, None)}},
        {"scalar": {"int": para_list}},
    ]


ts_shift = make_function(function=_ts_shift, name="ts_shift", arity=2, function_type="time_series",
                         param_type=_num_param())
ts_delta = make_function(function=_ts_delta, name="ts_delta", arity=2, function_type="time_series",
                         param_type=_num_param())
ts_mom = make_function(function=_ts_mom, name="ts_mom", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_min = make_function(function=_ts_min, name="ts_min", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_max = make_function(function=_ts_max, name="ts_max", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_argmax = make_function(function=_ts_argmax, name="ts_argmax", arity=2, function_type="time_series",
                          param_type=_num_param())
ts_argmin = make_function(function=_ts_argmin, name="ts_argmin", arity=2, function_type="time_series",
                          param_type=_num_param())
ts_rank = make_function(function=_ts_rank, name="ts_rank", arity=2, function_type="time_series",
                        param_type=_num_param())
ts_sum = make_function(function=_ts_sum, name="ts_sum", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_std = make_function(function=_ts_std, name="ts_std", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_corr = make_function(function=_ts_corr, name="ts_corr", arity=3, function_type="time_series",
                        param_type=[{"vector": {"number": (None, None)}},
                                    {"vector": {"number": (None, None)}},
                                    {"scalar": {"int": para_list}}])
ts_mean = make_function(function=_ts_mean, name="ts_mean", arity=2, function_type="time_series",
                        param_type=_num_param())
ts_zscore = make_function(function=_ts_zscore, name="ts_zscore", arity=2, function_type="time_series",
                          param_type=_num_param())
ts_freq = make_function(function=_ts_freq, name="ts_freq", arity=2, function_type="time_series",
                        param_type=_num_param())
ts_cdlbodym = make_function(function=_ts_cdlbodym, name="ts_cdlbodym", arity=3, function_type="time_series",
                            param_type=[{"vector": {"number": (None, None)}},
                                        {"vector": {"number": (None, None)}},
                                        {"scalar": {"int": para_list}}])
ts_bar_bs = make_function(function=_ts_bar_bs, name="ts_bar_bs", arity=3, function_type="time_series",
                          param_type=[{"vector": {"number": (None, None)}},
                                      {"vector": {"number": (None, None)}},
                                      {"scalar": {"int": para_list}}])
ts_adx = make_function(function=_ts_adx, name="ts_adx", arity=4, function_type="time_series",
                       param_type=[{"vector": {"number": (None, None)}},
                                   {"vector": {"number": (None, None)}},
                                   {"vector": {"number": (None, None)}},
                                   {"scalar": {"int": para_list}}])
ts_aroon = make_function(function=_ts_aroon, name="ts_aroon", arity=3, function_type="time_series",
                         param_type=[{"vector": {"number": (None, None)}},
                                     {"vector": {"number": (None, None)}},
                                     {"scalar": {"int": para_list}}])
ts_bopr = make_function(function=_ts_bopr, name="ts_bopr", arity=5, function_type="time_series",
                        param_type=[{"vector": {"number": (None, None)}},
                                    {"vector": {"number": (None, None)}},
                                    {"vector": {"number": (None, None)}},
                                    {"vector": {"number": (None, None)}},
                                    {"scalar": {"int": para_list}}])
ts_cmo = make_function(function=_ts_cmo, name="ts_cmo", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_ema = make_function(function=_ts_ema, name="ts_ema", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_macd = make_function(function=_ts_macd, name="ts_macd", arity=4, function_type="time_series",
                        param_type=[{"vector": {"number": (None, None)}},
                                    {"scalar": {"int": para_list}},
                                    {"scalar": {"int": para_list}},
                                    {"scalar": {"int": para_list}}])
ts_rsi = make_function(function=_ts_rsi, name="ts_rsi", arity=2, function_type="time_series",
                       param_type=_num_param())
ts_stochf = make_function(function=_ts_stochf, name="ts_stochf", arity=4, function_type="time_series",
                          param_type=[{"vector": {"number": (None, None)}},
                                      {"vector": {"number": (None, None)}},
                                      {"vector": {"number": (None, None)}},
                                      {"scalar": {"int": para_list}}])
ts_xs_ratio = make_function(function=_ts_xs_ratio, name="ts_xs_ratio", arity=2, function_type="time_series",
                            param_type=_num_param())
ts_one_ols_k = make_function(function=_ts_one_ols_k, name="ts_one_ols_k", arity=3, function_type="time_series",
                             param_type=[{"vector": {"number": (None, None)}},
                                         {"vector": {"number": (None, None)}},
                                         {"scalar": {"int": para_list}}])
ts_one_ols_resid = make_function(function=_ts_one_ols_resid, name="ts_one_ols_resid", arity=3,
                                 function_type="time_series",
                                 param_type=[{"vector": {"number": (None, None)}},
                                             {"vector": {"number": (None, None)}},
                                             {"scalar": {"int": para_list}}])
ts_skew = make_function(function=_ts_skew, name="ts_skew", arity=2, function_type="time_series",
                        param_type=_num_param())
ts_kurt = make_function(function=_ts_kurt, name="ts_kurt", arity=2, function_type="time_series",
                        param_type=_num_param())
ts_atr = make_function(function=_ts_atr, name="ts_atr", arity=5, function_type="time_series",
                       param_type=[{"vector": {"number": (None, None)}},
                                   {"vector": {"number": (None, None)}},
                                   {"vector": {"number": (None, None)}},
                                   {"scalar": {"int": para_list}},
                                   {"scalar": {"int": para_list}}])
ts_hedge = make_function(function=_ts_hedge, name="ts_hedge", arity=4, function_type="time_series",
                         param_type=[{"vector": {"number": (None, None)}},
                                     {"vector": {"number": (None, None)}},
                                     {"scalar": {"int": para_list}},
                                     {"scalar": {"int": para_list}}])
ts_bband = make_function(function=_ts_bband, name="ts_bband", arity=3, function_type="time_series",
                         param_type=[{"vector": {"number": (None, None)}},
                                     {"scalar": {"int": para_list}},
                                     {"scalar": {"int": para_list}}])

cs_rank = make_function(function=_cs_rank, name="cs_rank", arity=1, function_type="section",
                        param_type=[{"vector": {"number": (None, None)}}])
cs_zscore = make_function(function=_cs_zscore, name="cs_zscore", arity=1, function_type="section",
                          param_type=[{"vector": {"number": (None, None)}}])
cs_demean = make_function(function=_cs_demean, name="cs_demean", arity=1, function_type="section",
                          param_type=[{"vector": {"number": (None, None)}}])
cs_scale = make_function(function=_cs_scale, name="cs_scale", arity=1, function_type="section",
                         param_type=[{"vector": {"number": (None, None)}}])
cs_winsorize = make_function(function=_cs_winsorize, name="cs_winsorize", arity=1, function_type="section",
                             param_type=[{"vector": {"number": (None, None)}}])


_function_map = {
    "add": add2,
    "sub": sub2,
    "mul": mul2,
    "div": div2,
    "sqrt": sqrt1,
    "log": log1,
    "abs": abs1,
    "neg": neg1,
    "inv": inv1,
    "max": max2,
    "min": min2,
    "sin": sin1,
    "cos": cos1,
    "tan": tan1,
    "sig": sig1,
    "ts_shift": ts_shift,
    "ts_delta": ts_delta,
    "ts_mom": ts_mom,
    "ts_min": ts_min,
    "ts_max": ts_max,
    "ts_argmax": ts_argmax,
    "ts_argmin": ts_argmin,
    "ts_rank": ts_rank,
    "ts_sum": ts_sum,
    "ts_std": ts_std,
    "ts_corr": ts_corr,
    "ts_mean": ts_mean,
    "ts_zscore": ts_zscore,
    "ts_freq": ts_freq,
    "ts_cdlbodym": ts_cdlbodym,
    "ts_bar_bs": ts_bar_bs,
    "ts_adx": ts_adx,
    "ts_aroon": ts_aroon,
    "ts_bopr": ts_bopr,
    "ts_cmo": ts_cmo,
    "ts_ema": ts_ema,
    "ts_macd": ts_macd,
    "ts_rsi": ts_rsi,
    "ts_stochf": ts_stochf,
    "ts_xs_ratio": ts_xs_ratio,
    "ts_one_ols_k": ts_one_ols_k,
    "ts_one_ols_resid": ts_one_ols_resid,
    "ts_skew": ts_skew,
    "ts_kurt": ts_kurt,
    "ts_atr": ts_atr,
    "ts_hedge": ts_hedge,
    "ts_bband": ts_bband,
    "cs_rank": cs_rank,
    "cs_zscore": cs_zscore,
    "cs_demean": cs_demean,
    "cs_scale": cs_scale,
    "cs_winsorize": cs_winsorize,
}

raw_function_list = [
    "add",
    "sub",
    "mul",
    "div",
    "sqrt",
    "log",
    "abs",
    "neg",
    "inv",
    "max",
    "min",
    "sig",
]

section_function = [
    "cs_rank",
    "cs_zscore",
    "cs_demean",
    "cs_scale",
    "cs_winsorize",
]

time_series_function = [
    "ts_shift",
    "ts_delta",
    "ts_mom",
    "ts_min",
    "ts_max",
    "ts_argmax",
    "ts_argmin",
    "ts_rank",
    "ts_sum",
    "ts_std",
    "ts_corr",
    "ts_mean",
    "ts_zscore",
    "ts_freq",
    "ts_cdlbodym",
    "ts_bar_bs",
    "ts_adx",
    "ts_aroon",
    "ts_bopr",
    "ts_cmo",
    "ts_ema",
    "ts_macd",
    "ts_rsi",
    "ts_stochf",
    "ts_xs_ratio",
    "ts_one_ols_k",
    "ts_one_ols_resid",
    "ts_skew",
    "ts_kurt",
    "ts_atr",
    "ts_hedge",
    "ts_bband",
]

panel_function = raw_function_list + time_series_function + section_function
all_function = raw_function_list.copy()
all_function.extend(time_series_function)
