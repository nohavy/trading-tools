"""Cross-sectional momentum studies: quintile spreads net of costs (Way A).

Method (documented in docs/plan.md): at each date, rank assets by their
lookback-day past return; the top bucket is bought (equal weight), the
bottom bucket shorted (or used as a benchmark when shorting is impossible);
the spread's forward return is the strategy's daily PnL.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass(frozen=True)
class QuintileResult:
    """Summary of a cross-sectional quintile study."""

    n_dates: int
    n_assets: int
    top_mean_bps: float | None
    bottom_mean_bps: float | None
    spread_mean_bps: float | None
    spread_median_bps: float | None
    spread_hit_rate: float | None
    spread_series: list[float] | None


def _pivot_close(frame: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Wide close matrix (dates × assets) from long (ts_open_ns, symbol, close)."""
    wide = frame.pivot(on="symbol", index="ts_open_ns", values="close").sort("ts_open_ns")
    symbols = [c for c in wide.columns if c != "ts_open_ns"]
    close = wide.select(symbols).to_numpy()
    ts = wide["ts_open_ns"].to_numpy()
    return ts, close, np.array(symbols)


def quintile_spreads(
    frame: pl.DataFrame,
    *,
    lookback_days: int,
    horizon_days: int,
    n_buckets: int = 5,
    round_trip_bps: float = 0.0,
    min_assets: int = 2,
) -> QuintileResult:
    """Study top-vs-bottom cross-sectional momentum over the frame.

    `frame` is long (ts_open_ns, symbol, close) — the canonical bar schema.

    At each date t (with lookback history and forward data available):
    - past return_i = close[t]/close[t-lookback] - 1
    - forward return_i = close[t+horizon]/close[t] - 1
    - top bucket = the highest `1/n_buckets` of past returns, bottom the lowest.
    Spread = mean(forward of top) - mean(forward of bottom), minus costs.

    Only dates where at least two assets have a defined past and forward return
    are used (one member minimum in the top and in the bottom bucket).
    """
    ts, close, symbols = _pivot_close(frame)
    n_assets = len(symbols)
    if n_assets < min_assets:
        raise ValueError(f"need at least {min_assets} assets, got {n_assets}")
    n_days = len(ts)
    bucket_size = max(1, n_assets // n_buckets)

    spreads: list[float] = []
    top_means: list[float] = []
    bottom_means: list[float] = []
    for t in range(lookback_days, n_days - horizon_days):
        past = close[t] / close[t - lookback_days] - 1.0
        forward = close[t + horizon_days] / close[t] - 1.0
        defined = ~np.isnan(past) & ~np.isnan(forward)
        if defined.sum() < 2:
            continue
        past_d, forward_d = past[defined], forward[defined]
        order = np.argsort(past_d)  # ascending
        top_idx = order[-bucket_size:]
        bottom_idx = order[:bucket_size]
        top_ret = float(np.mean(forward_d[top_idx])) * 1e4
        bottom_ret = float(np.mean(forward_d[bottom_idx])) * 1e4
        top_means.append(top_ret)
        bottom_means.append(bottom_ret)
        spreads.append(top_ret - bottom_ret - round_trip_bps)

    if not spreads:
        return QuintileResult(
            n_dates=0,
            n_assets=n_assets,
            top_mean_bps=None,
            bottom_mean_bps=None,
            spread_mean_bps=None,
            spread_median_bps=None,
            spread_hit_rate=None,
            spread_series=None,
        )
    arr = np.array(spreads)
    return QuintileResult(
        n_dates=len(spreads),
        n_assets=n_assets,
        top_mean_bps=float(np.mean(top_means)),
        bottom_mean_bps=float(np.mean(bottom_means)),
        spread_mean_bps=float(arr.mean()),
        spread_median_bps=float(np.median(arr)),
        spread_hit_rate=float((arr > 0).mean()),
        spread_series=spreads,
    )


def liquidity_filter(
    long: pl.DataFrame,
    *,
    lookback: int = 30,
    quantile: float = 0.2,
) -> pl.DataFrame:
    """Drop assets that are not liquid enough to trade at the modelled costs.

    An asset stays eligible on a date when its trailing median quote volume is
    at or above the `quantile` of that date's cross-section. Returns only
    (ts_open_ns, symbol, close), which quintile_spreads pivots into a matrix
    where the removed assets simply become NaN.
    """
    ordered = long.sort(["symbol", "ts_open_ns"]).with_columns(
        pl.col("quote_volume")
        .rolling_median(window_size=lookback, min_samples=7)
        .over("symbol")
        .alias("med_vol")
    )
    thresholds = ordered.group_by("ts_open_ns").agg(
        pl.col("med_vol")
        .quantile(quantile, interpolation="higher")
        .alias("cutoff")
    )
    return (
        ordered.join(thresholds, on="ts_open_ns")
        .filter(pl.col("med_vol") >= pl.col("cutoff"))
        .select("ts_open_ns", "symbol", "close")
    )


def newey_west_tstat(spread: list[float], lag: int) -> float:
    """t-statistic of the mean, corrected for autocorrelation up to `lag`.

    Overlapping forward windows make neighbouring spreads correlated, so the
    naive t-stat overstates significance; the Newey-West bandwidth shrinks it.
    """
    x = np.asarray(spread, dtype=float)
    n = x.size
    if n < lag + 2:
        return float("nan")
    dev = x - x.mean()
    var = float(dev @ dev) / n
    for k in range(1, lag + 1):
        cov = float(dev[k:] @ dev[:-k]) / n
        var += 2.0 * (1.0 - k / (lag + 1.0)) * cov
    if var <= 0:
        return float("nan")
    return float(x.mean() / np.sqrt(var / n))
