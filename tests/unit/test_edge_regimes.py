"""Tests for regime-conditioned edge studies (volatility, time-of-day)."""

import numpy as np
import pytest

from tradingv2.research.edge import edge_by_regime, session_labels
from tradingv2.research.signals import SignalEvent

S = 1_000_000_000
H = 3_600 * S  # one hour in ns


def make_up(n: int = 10) -> tuple[np.ndarray, np.ndarray]:
    ts = np.arange(n, dtype=np.int64) * S
    close = 100.0 + np.arange(n, dtype=np.float64)
    return ts, close


def test_edge_by_session_labels() -> None:
    """Events labeled by UTC hour bucket: stats per bucket are consistent."""
    n = 25 * 3600 + 1  # 25 hours
    ts = np.arange(n, dtype=np.int64) * S
    close = 100.0 * np.power(1.01, np.arange(n, dtype=np.float64))  # +1%/s: 100 bps everywhere
    # buy events in sessions 0-8, 8-16, 16-24 (hours 0, 10, 20)
    events = [
        SignalEvent(ts_ns=0, direction="buy"),
        SignalEvent(ts_ns=10 * H, direction="buy"),
        SignalEvent(ts_ns=20 * H, direction="buy"),
    ]
    rows = edge_by_regime(
        events, ts, close, horizons_ns=[S], cost_pairs=[("c", 50.0)],
        label_fn=lambda event_ts: session_labels(np.array([event_ts]))[0],
    )
    assert set(rows) == {"0-8", "8-16", "16-24"}
    for _label, label_rows in rows.items():
        assert len(label_rows) == 1
        row = label_rows[0]
        assert row["n"] == 1
        assert row["mean_bps"] is not None
        assert row["mean_bps"] == pytest.approx(100.0)  # +1/100 up drift everywhere
        assert row["edges"]["c"] == pytest.approx(50.0)


def test_edge_by_regime_splits_statistics() -> None:
    """Different drift per regime: each regime sees its own mean return."""
    ts = np.arange(8, dtype=np.int64) * S
    # bars 0-3: +2/s (+200 bps), bars 4-7: flat
    close = np.array([100.0, 102.0, 104.0, 106.0, 106.0, 106.0, 106.0, 106.0])
    events = [
        SignalEvent(ts_ns=0, direction="buy"),
        SignalEvent(ts_ns=4 * S, direction="buy"),
    ]
    rows = edge_by_regime(
        events, ts, close, horizons_ns=[S], cost_pairs=[("c", 10.0)],
        label_fn=lambda event_ts: "up" if event_ts < 4 * S else "flat",
    )
    assert rows["up"][0]["mean_bps"] == pytest.approx(200.0)
    assert rows["flat"][0]["mean_bps"] == pytest.approx(0.0, abs=1e-9)


def test_edge_by_regime_empty_group_excluded() -> None:
    ts, close = make_up(n=10)
    rows = edge_by_regime(
        [SignalEvent(ts_ns=0, direction="buy")], ts, close, horizons_ns=[S],
        cost_pairs=[], label_fn=lambda event_ts: "a" if event_ts < 5 * S else "b",
    )
    assert set(rows) == {"a"}  # no events in "b": the group is absent


def test_session_of_day_labels_helper() -> None:
    from tradingv2.research.edge import session_labels

    labels = session_labels(
        np.array([0, 7 * H, 8 * H, 15 * H, 16 * H, 23 * H], dtype=np.int64)
    )
    assert labels == ["0-8", "0-8", "8-16", "8-16", "16-24", "16-24"]


def test_vol_regime_labels_helper() -> None:
    from tradingv2.research.edge import vol_regime_labels

    ts = np.arange(12, dtype=np.int64) * S
    close = np.array([100.0] * 6 + [100.0 + 2.0 * (i % 2) for i in range(6)])
    labels = vol_regime_labels(ts, close, window=2)
    # flat bars = zero vol; swinging bars = high vol: two distinct labels expected
    assert len(set(labels)) == 2
    assert labels[2] != labels[8]
    assert len(labels) == 12
