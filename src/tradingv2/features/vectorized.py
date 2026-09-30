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
"""

import polars as pl


def ema(values: pl.Series, span: int) -> pl.Series:
    """Exponential moving average, seeded with the first value."""
    if span <= 0:
        raise ValueError(f"span must be positive, got {span}")
    return values.ewm_mean(span=span, adjust=False, ignore_nulls=False)


def zscore(values: pl.Series, window: int) -> pl.Series:
    """Rolling z-score of the values over a bar-count window."""
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    mean = values.rolling_mean(window, min_samples=window)
    std = values.rolling_std(window, ddof=0, min_samples=window)
    return (values - mean) / std


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
    """Rolling std (population) of simple returns over a bar-count window."""
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    returns = close.pct_change()
    return returns.rolling_std(window, ddof=0, min_samples=window)


def flow_imbalance(volume: pl.Series, taker_buy_volume: pl.Series, window: int) -> pl.Series:
    """Taker-buy share over the window mapped to [-1, 1]."""
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    total = volume.rolling_sum(window, min_samples=window)
    buy = taker_buy_volume.rolling_sum(window, min_samples=window)
    return 2 * buy / total - 1
