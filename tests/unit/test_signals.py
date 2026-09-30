"""Tests for research signal generators (exact crossing events)."""

import polars as pl

from tradingv2.research.signals import SignalEvent, signal_breakout, signal_flow, signal_meanrev

S = 1_000_000_000


def ts_series(n: int) -> pl.Series:
    return pl.Series([i * S for i in range(n)], dtype=pl.Int64)


def test_meanrev_events_on_extreme_low_z() -> None:
    closes = pl.Series([5000.0, 5000.0, 4990.0, 4991.0, 4994.0, 4994.0])
    events = signal_meanrev(closes, ts_series(6), window=3, entry_z=1.0)
    assert events == [
        SignalEvent(ts_ns=2 * S, direction="buy"),
        SignalEvent(ts_ns=4 * S, direction="sell"),
    ]


def test_meanrev_event_only_on_crossing_not_every_bar() -> None:
    # z re-crosses at index 4 (briefly back inside the band at index 3), then
    # swings high at index 5: three crossings, one per crossing — never repeated
    closes = pl.Series([5000.0, 5000.0, 4990.0, 4989.0, 4988.0, 4994.0])
    events = signal_meanrev(closes, ts_series(6), window=3, entry_z=1.0)
    assert events == [
        SignalEvent(ts_ns=2 * S, direction="buy"),
        SignalEvent(ts_ns=4 * S, direction="buy"),
        SignalEvent(ts_ns=5 * S, direction="sell"),
    ]


def test_meanrev_sell_on_extreme_high_z() -> None:
    closes = pl.Series([5000.0, 5000.0, 5010.0, 5009.0, 5006.0])
    events = signal_meanrev(closes, ts_series(5), window=3, entry_z=1.0)
    assert events == [
        SignalEvent(ts_ns=2 * S, direction="sell"),
        SignalEvent(ts_ns=4 * S, direction="buy"),
    ]


def test_breakout_events_with_volume_confirmation() -> None:
    closes = pl.Series([5000.0, 5000.0, 5000.0, 5005.0, 5006.0])
    highs = pl.Series([5000.1, 5000.1, 5000.1, 5005.1, 5006.1])
    lows = pl.Series([4999.9, 4999.9, 4999.9, 4999.9, 5004.9])
    volumes = pl.Series([10.0, 10.0, 10.0, 30.0, 10.0])
    events = signal_breakout(
        highs, lows, closes, volumes, ts_series(5), lookback=3, volume_factor=2.0
    )
    assert SignalEvent(ts_ns=3 * S, direction="buy") in events


def test_breakout_needs_volume() -> None:
    closes = pl.Series([5000.0, 5000.0, 5000.0, 5005.0])
    highs = pl.Series([5000.1, 5000.1, 5000.1, 5005.1])
    lows = pl.Series([4999.9, 4999.9, 4999.9, 4999.9])
    volumes = pl.Series([10.0, 10.0, 10.0, 12.0])  # 12 < 2 * mean(10)
    events = signal_breakout(
        highs, lows, closes, volumes, ts_series(4), lookback=3, volume_factor=2.0
    )
    assert events == []


def test_breakout_short_symmetric() -> None:
    closes = pl.Series([5010.0, 5010.0, 5010.0, 5004.0])
    highs = pl.Series([5010.1, 5010.1, 5010.1, 5010.1])
    lows = pl.Series([5009.9, 5009.9, 5009.9, 5003.9])
    volumes = pl.Series([10.0, 10.0, 10.0, 30.0])
    events = signal_breakout(
        highs, lows, closes, volumes, ts_series(4), lookback=3, volume_factor=2.0
    )
    assert events == [SignalEvent(ts_ns=3 * S, direction="sell")]


def test_flow_events_on_crossing() -> None:
    volumes = pl.Series([10.0] * 8)
    taker_buy = pl.Series([10.0, 10.0, 10.0, 10.0, 5.0, 2.0, 1.0, 1.0])
    events = signal_flow(volumes, taker_buy, ts_series(8), window=3, threshold=0.6)
    # flow: idx2 = +1.0 (cross), idx3/4 stay high, idx5 = 0.133, idx6 = -0.467,
    # idx7 = -0.733 (cross below -0.6)
    assert events == [
        SignalEvent(ts_ns=2 * S, direction="buy"),
        SignalEvent(ts_ns=7 * S, direction="sell"),
    ]


def test_flow_no_event_below_threshold() -> None:
    volumes = pl.Series([10.0] * 6)
    taker_buy = pl.Series([5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    events = signal_flow(volumes, taker_buy, ts_series(6), window=3, threshold=0.6)
    assert events == []


def test_signal_event_fields() -> None:
    event = SignalEvent(ts_ns=1, direction="buy")
    assert event.ts_ns == 1
    assert event.direction == "buy"


def test_meanrev_needs_full_window() -> None:
    closes = pl.Series([4990.0, 4990.0])  # shorter than window
    events = signal_meanrev(closes, ts_series(2), window=3, entry_z=1.0)
    assert events == []
