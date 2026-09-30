"""Tests for long-horizon research signals: momentum, funding extremes, basis."""

import polars as pl

from tradingv2.research.signals import (
    SignalEvent,
    signal_basis,
    signal_funding_extreme,
    signal_momentum,
)

M = 60_000_000_000  # one minute


def ts_series(n: int, step_ns: int = M) -> pl.Series:
    return pl.Series([i * step_ns for i in range(n)], dtype=pl.Int64)


def test_momentum_buys_on_upward_break_of_threshold() -> None:
    # +0.2%/bar over lookback 5 = +1% >= threshold 0.005 → buy
    closes = pl.Series([100.0 + 0.2 * i for i in range(12)])
    events = signal_momentum(closes, ts_series(12), lookback=5, threshold=0.005)
    assert events
    first = events[0]
    assert first.direction == "buy"
    # momentum stays positive: no repeat event while it remains above threshold
    assert all(e.direction == "buy" for e in events)


def test_momentum_sells_on_downward_break() -> None:
    closes = pl.Series([100.0 - 0.2 * i for i in range(12)])
    events = signal_momentum(closes, ts_series(12), lookback=5, threshold=0.005)
    assert events
    assert events[0].direction == "sell"


def test_momentum_reversal_generates_opposite_event() -> None:
    up = [100.0 + 0.3 * i for i in range(8)]
    down = [up[-1] - 0.3 * (i + 1) for i in range(8)]
    closes = pl.Series(up + down)
    events = signal_momentum(closes, ts_series(16), lookback=5, threshold=0.005)
    directions = [e.direction for e in events]
    assert "buy" in directions and "sell" in directions
    assert directions.index("buy") < directions.index("sell")  # reversal comes after


def test_momentum_needs_full_lookback() -> None:
    closes = pl.Series([100.0 + 0.2 * i for i in range(4)])
    assert signal_momentum(closes, ts_series(4), lookback=5, threshold=0.005) == []


def test_funding_extreme_sells_on_positive_rate() -> None:
    # funding every 8h; a large positive rate = crowded longs → sell
    rates = [0.0001, 0.0001, 0.0012, 0.0001]
    ts = ts_series(4, step_ns=8 * 3600 * 1_000_000_000)
    events = signal_funding_extreme(ts, pl.Series(rates), threshold=0.0005)
    assert events == [SignalEvent(ts_ns=2 * 8 * 3600 * 1_000_000_000, direction="sell")]


def test_funding_extreme_buys_on_negative_rate() -> None:
    rates = [0.0001, -0.002, 0.0001]
    ts = ts_series(3, step_ns=8 * 3600 * 1_000_000_000)
    events = signal_funding_extreme(ts, pl.Series(rates), threshold=0.0005)
    assert events == [SignalEvent(ts_ns=8 * 3600 * 1_000_000_000, direction="buy")]


def test_funding_extreme_no_event_near_zero() -> None:
    rates = [0.0001, -0.0001, 0.0002]
    ts = ts_series(3, step_ns=8 * 3600 * 1_000_000_000)
    assert signal_funding_extreme(ts, pl.Series(rates), threshold=0.0005) == []


def test_basis_sells_perp_when_basis_extreme_high() -> None:
    spot = pl.Series([100.0] * 8)
    perp = pl.Series([100.0, 100.0, 100.5, 103.0, 100.5, 100.0, 100.0, 100.0])
    events = signal_basis(spot, perp, ts_series(8), window=3, entry_z=1.0)
    # the z crosses at index 2 (window full): the earliest crossing wins
    assert SignalEvent(ts_ns=2 * M, direction="sell") in events


def test_basis_buys_perp_when_basis_extreme_low() -> None:
    spot = pl.Series([100.0] * 8)
    perp = pl.Series([100.0, 100.0, 100.0, 96.0, 99.0, 100.0, 100.0, 100.0])
    events = signal_basis(spot, perp, ts_series(8), window=3, entry_z=1.0)
    assert SignalEvent(ts_ns=3 * M, direction="buy") in events


def test_basis_no_event_when_flat() -> None:
    spot = pl.Series([100.0] * 6)
    perp = pl.Series([100.0] * 6)
    assert signal_basis(spot, perp, ts_series(6), window=3, entry_z=1.0) == []
