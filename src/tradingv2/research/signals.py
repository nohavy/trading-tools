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
