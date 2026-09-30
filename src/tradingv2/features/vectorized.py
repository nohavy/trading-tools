"""Vectorized indicators (lot mode, research). Conventions:

- EMA: alpha = 2/(span+1), seeded with the first value, defined from bar 1.
- Z-score: rolling mean/std (population, ddof=0), undefined until the window
  is full of defined values.
- VWAP: session (UTC day) cumulative price*volume/volume, resets at midnight,
  undefined while the cumulative volume is zero.
- Realized volatility: rolling std (population) of simple returns, defined
  once `window` returns exist.
- Flow imbalance: 2 * sum(taker_buy)/sum(volume) - 1 over the window, in
  [-1, 1], undefined when the window volume is zero.

NOTE: polars rolling_sum uses a sliding add/remove accumulator that drifts on
magnitude jumps (a [0, 0] window after 524288 returns ~5.8e-11, not 0) —
flow_imbalance therefore uses direct per-window sums (numpy) so that the lot
and incremental implementations agree bit-for-bit on realistic data.
"""

import numpy as np
import polars as pl


def ema(values: pl.Series, span: int) -> pl.Series:
    """Exponential moving average, seeded with the first value."""
    if span <= 0:
        raise ValueError(f"span must be positive, got {span}")
    return values.ewm_mean(span=span, adjust=False, ignore_nulls=False)


def zscore(values: pl.Series, window: int) -> pl.Series:
    """Rolling z-score over direct per-window sums (population std, ddof=0)."""
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    v = values.to_numpy()
    n = len(v)
    out = np.full(n, np.nan)
    if n >= window:
        windows = np.lib.stride_tricks.sliding_window_view(v, window)
        mean = windows.mean(axis=1)
        std = windows.std(axis=1)
        x = v[window - 1 :]
        safe_std = np.where(std > 0, std, 1.0)
        out[window - 1 :] = np.where(std > 0, (x - mean) / safe_std, np.nan)
    return pl.Series(out)


def vwap_session(ts_ns: pl.Series, price: pl.Series, volume: pl.Series) -> pl.Series:
    """Session VWAP (UTC day), cumulative within each day, reset at midnight."""
    day = ts_ns // 86_400_000_000_000
    pv = price * volume
    df = pl.DataFrame({"day": day, "pv": pv, "cv": volume})
    result = df.with_columns(
        (pl.col("pv").cum_sum().over("day") / pl.col("cv").cum_sum().over("day")).alias("vwap")
    )
    return result["vwap"]


def realized_vol(close: pl.Series, window: int) -> pl.Series:
    """Rolling std (population) of simple returns over direct windows."""
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    v = close.to_numpy()
    n = len(v)
    out = np.full(n, np.nan)
    if n >= 2:
        returns = np.diff(v) / v[:-1]
        if len(returns) >= window:
            windows = np.lib.stride_tricks.sliding_window_view(returns, window)
            out[window:] = windows.std(axis=1)
    return pl.Series(out)


def flow_imbalance(volume: pl.Series, taker_buy_volume: pl.Series, window: int) -> pl.Series:
    """Taker-buy share over the window mapped to [-1, 1] (exact window sums)."""
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    v = volume.to_numpy()
    b = taker_buy_volume.to_numpy()
    n = len(v)
    out = np.full(n, np.nan)
    if n >= window:
        windows_v = np.lib.stride_tricks.sliding_window_view(v, window)
        windows_b = np.lib.stride_tricks.sliding_window_view(b, window)
        total = windows_v.sum(axis=1)
        buy = windows_b.sum(axis=1)
        valid = total > 0
        safe_total = np.where(valid, total, 1.0)
        ratio = np.where(valid, buy / safe_total, 0.0)
        out[window - 1 :] = np.where(valid, 2 * ratio - 1, np.nan)
    return pl.Series(out)
