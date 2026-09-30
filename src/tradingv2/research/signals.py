"""Research signal generators: exact threshold-crossing events on bars."""

from dataclasses import dataclass

import numpy as np
import polars as pl

from tradingv2.features.vectorized import zscore


@dataclass(frozen=True)
class SignalEvent:
    """One signal detection: timestamp and trade direction."""

    ts_ns: int
    direction: str  # "buy" | "sell"


def _crossings(values: np.ndarray, low: float, high: float) -> tuple[np.ndarray, np.ndarray]:
    """Indices where the value crosses below `low` or above `high`.

    Fires once per crossing: entering the band from below/above or switching
    sides directly both count; staying outside does not repeat. Undefined
    (NaN, window not full) resets to neutral. Returns (below_idx, above_idx).
    """
    n = len(values)
    below_idx: list[int] = []
    above_idx: list[int] = []
    state = 0  # -1 below, 0 inside/undefined, +1 above
    for i in range(n):
        value = values[i]
        if value != value:  # NaN
            state = 0
            continue
        if value <= low:
            if state != -1:
                below_idx.append(i)
                state = -1
        elif value >= high:
            if state != 1:
                above_idx.append(i)
                state = 1
        else:
            state = 0
    return np.array(below_idx), np.array(above_idx)


def signal_meanrev(
    close: pl.Series, ts_ns: pl.Series, window: int, entry_z: float
) -> list[SignalEvent]:
    """Events when the z-score of the close crosses ±entry_z (opposite side)."""
    z = zscore(close, window).to_numpy()
    below_idx, above_idx = _crossings(z, -entry_z, entry_z)
    ts = ts_ns.to_numpy()
    events = (
        [SignalEvent(ts_ns=int(ts[i]), direction="buy") for i in below_idx]
        + [SignalEvent(ts_ns=int(ts[i]), direction="sell") for i in above_idx]
    )
    return sorted(events, key=lambda e: e.ts_ns)


def signal_breakout(
    highs: pl.Series,
    lows: pl.Series,
    closes: pl.Series,
    volumes: pl.Series,
    ts_ns: pl.Series,
    lookback: int,
    volume_factor: float,
) -> list[SignalEvent]:
    """Events on range break with above-average volume confirmation."""
    h = highs.to_numpy()
    lows_np = lows.to_numpy()
    c = closes.to_numpy()
    v = volumes.to_numpy()
    t = ts_ns.to_numpy()
    events: list[SignalEvent] = []
    for i in range(lookback, len(c)):
        range_high = h[i - lookback : i].max()
        range_low = lows_np[i - lookback : i].min()
        avg_volume = v[i - lookback : i].mean()
        confirmed = v[i] > volume_factor * avg_volume
        if confirmed and c[i] > range_high:
            events.append(SignalEvent(ts_ns=int(t[i]), direction="buy"))
        elif confirmed and c[i] < range_low:
            events.append(SignalEvent(ts_ns=int(t[i]), direction="sell"))
    return events


def signal_flow(
    volume: pl.Series,
    taker_buy_volume: pl.Series,
    ts_ns: pl.Series,
    window: int,
    threshold: float,
) -> list[SignalEvent]:
    """Events when the taker-buy imbalance crosses ±threshold."""
    from tradingv2.features.vectorized import flow_imbalance

    flow = flow_imbalance(volume, taker_buy_volume, window).to_numpy()
    below_idx, above_idx = _crossings(flow, -threshold, threshold)
    ts = ts_ns.to_numpy()
    # flow above the threshold = aggressive buying -> buy; below = selling -> sell
    events = (
        [SignalEvent(ts_ns=int(ts[i]), direction="buy") for i in above_idx]
        + [SignalEvent(ts_ns=int(ts[i]), direction="sell") for i in below_idx]
    )
    return sorted(events, key=lambda e: e.ts_ns)


def signal_momentum(
    close: pl.Series, ts_ns: pl.Series, lookback: int, threshold: float
) -> list[SignalEvent]:
    """Time-series momentum: events when the lookback return crosses ±threshold.

    Positive momentum expects continuation (buy on upside break, sell on
    downside break) — the opposite of mean reversion.
    """
    values = close.to_numpy()
    lookback_ret = np.full(len(values), np.nan)
    if len(values) > lookback:
        lookback_ret[lookback:] = values[lookback:] / values[:-lookback] - 1.0
    below_idx, above_idx = _crossings(lookback_ret, -threshold, threshold)
    t = ts_ns.to_numpy()
    events = (
        [SignalEvent(ts_ns=int(t[i]), direction="buy") for i in above_idx]
        + [SignalEvent(ts_ns=int(t[i]), direction="sell") for i in below_idx]
    )
    return sorted(events, key=lambda e: e.ts_ns)


def signal_funding_extreme(
    funding_ts: pl.Series, funding_rate: pl.Series, threshold: float
) -> list[SignalEvent]:
    """Funding-rate extremes as crowding signals (mean reversion).

    A large positive rate = crowded longs paying: sell. A large negative
    rate = crowded shorts: buy. Events fire at each funding settlement whose
    rate crosses the threshold (one per settlement — no crossing logic).
    """
    t = funding_ts.to_numpy()
    r = funding_rate.to_numpy()
    events: list[SignalEvent] = []
    for i in range(len(t)):
        rate = r[i]
        if rate != rate:
            continue
        if rate >= threshold:
            events.append(SignalEvent(ts_ns=int(t[i]), direction="sell"))
        elif rate <= -threshold:
            events.append(SignalEvent(ts_ns=int(t[i]), direction="buy"))
    return events


def signal_basis(
    spot_close: pl.Series, perp_close: pl.Series, ts_ns: pl.Series, window: int, entry_z: float
) -> list[SignalEvent]:
    """Spot-perp basis z-score extremes (perp convergence, single-leg proxy).

    Basis above its rolling mean (perp overpriced) → sell the perp; below →
    buy. The hedge leg (spot) is out of scope for the single-instrument
    engine: this measures the perp-side timing.
    """
    spot = spot_close.to_numpy()
    perp = perp_close.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        basis = perp / spot - 1.0
    basis_series = pl.Series(np.where(np.isfinite(basis), basis, np.nan))
    z = zscore(basis_series, window).to_numpy()
    # basis extreme HIGH → sell perp (mean reversion of the basis)
    below_idx, above_idx = _crossings(z, -entry_z, entry_z)
    t = ts_ns.to_numpy()
    events = (
        [SignalEvent(ts_ns=int(t[i]), direction="sell") for i in above_idx]
        + [SignalEvent(ts_ns=int(t[i]), direction="buy") for i in below_idx]
    )
    return sorted(events, key=lambda e: e.ts_ns)
