"""Per-asset potential metrics: volatility, liquidity, breakouts, funding.

Definitions (documented decisions):
- vol_bps_1m: population std of 1-minute returns × 1e4.
- vol_bps_1h: same on 60-bar aggregated closes.
- quote_volume_daily / n_trades_daily: mean daily sums over the window.
- breakout_freq: breakout events (lookback 30, volume_factor 2) per day.
- funding_mean_bps / funding_p95_bps: mean and p95 of rates × 1e4 (None when
  funding is absent for the asset).
- dead: daily quote volume below a threshold OR the time span of the bars
  below `min_days` (too little data for a scan).
"""

from typing import Any

import numpy as np
import polars as pl

_S = 1_000_000_000


def _std_bps(values: np.ndarray) -> float:
    if len(values) < 2:
        return 0.0
    returns = np.diff(values) / values[:-1]
    return float(np.std(returns) * 1e4)


def _daily_mean(bars: pl.DataFrame, column: str) -> float:
    day = bars["ts_open_ns"] // (86_400 * _S)
    sums = bars.group_by(day).agg(pl.col(column).sum())
    mean: float = float(sums[column].mean())  # type: ignore[arg-type]
    return mean


def asset_metrics(
    bars: pl.DataFrame,
    funding: pl.DataFrame | None = None,
    min_quote_volume_daily: float = 0.0,
    min_days: float = 20.0,
) -> dict[str, Any]:
    """Compute the potential metrics of one asset from its 1m bars."""
    n_bars = bars.height
    close = bars["close"].to_numpy()
    # polars stubs widen to_numpy() to a wide union; the column is Float64 here.
    vol_bps_1m: float = _std_bps(np.asarray(close, dtype=np.float64))

    # 1h aggregation: group by hour bucket, take the last close of each bucket
    hour_ns = 3600 * _S
    hour_bucket = bars["ts_open_ns"] // hour_ns
    hourly_close = (
        bars.with_columns(hour_bucket.alias("_bucket"))
        .group_by("_bucket", maintain_order=True)
        .agg(pl.col("close").last())
    )
    vol_bps_1h = _std_bps(hourly_close["close"].to_numpy())

    quote_volume_daily = _daily_mean(bars, "quote_volume")
    n_trades_daily = _daily_mean(bars, "n_trades")

    breakout_freq = None
    from tradingv2.research.signals import signal_breakout

    events = signal_breakout(
        bars["high"], bars["low"], bars["close"], bars["volume"], bars["ts_open_ns"],
        lookback=30, volume_factor=2.0,
    )
    n_days = max(1.0, n_bars / 1440.0)
    breakout_freq = len(events) / n_days

    funding_mean_bps = None
    funding_p95_bps = None
    if funding is not None and funding.height > 0:
        rates = funding["rate"].to_numpy()
        rates = rates[~np.isnan(rates)]
        if rates.size > 0:
            funding_mean_bps = float(np.mean(rates) * 1e4)
            funding_p95_bps = float(np.percentile(rates, 95) * 1e4)

    span_days = 0.0
    if n_bars >= 2:
        span_ns = float(bars["ts_open_ns"][-1] - bars["ts_open_ns"][0])
        span_days = span_ns / (86_400.0 * _S)
    dead = quote_volume_daily < min_quote_volume_daily or span_days < min_days

    out: dict[str, Any] = {
        "n_bars": n_bars,
        "vol_bps_1m": vol_bps_1m,
        "vol_bps_1h": vol_bps_1h,
        "quote_volume_daily": quote_volume_daily,
        "n_trades_daily": n_trades_daily,
        "breakout_freq": breakout_freq,
        "funding_mean_bps": funding_mean_bps,
        "funding_p95_bps": funding_p95_bps,
        "dead": dead,
    }
    return out
