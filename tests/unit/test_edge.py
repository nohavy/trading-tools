"""Tests for the edge study: forward returns and the edge-vs-cost table (SC-001)."""

import numpy as np
import pytest

from tradingv2.research.edge import edge_table, forward_returns
from tradingv2.research.signals import SignalEvent

S = 1_000_000_000


def make_up_series(
    n: int = 10, base: float = 100.0, step: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """close[i] = base + i*step: +step/base*1e4 bps per second (known drift)."""
    ts = np.arange(n, dtype=np.int64) * S
    close = base + np.arange(n, dtype=np.float64) * step
    return ts, close


def test_forward_returns_known_drift() -> None:
    ts, close = make_up_series()
    rets = forward_returns(ts, close, event_ts=0, horizons_ns=[S, 2 * S])
    assert rets[S] == pytest.approx(100.0)  # +1 on 100 = 100 bps
    assert rets[2 * S] == pytest.approx(200.0)


def test_forward_returns_price_at_event_is_last_known() -> None:
    ts, close = make_up_series()
    # event between bars (600ms): last known price = close[0]
    rets = forward_returns(ts, close, event_ts=600_000_000, horizons_ns=[S])
    assert rets[S] == pytest.approx(100.0)


def test_forward_returns_undefined_beyond_data() -> None:
    ts, close = make_up_series(n=10)
    # event on the very last bar: no price after it -> not measurable
    rets = forward_returns(ts, close, event_ts=9 * S, horizons_ns=[5 * S])
    assert rets[5 * S] is None
    # event 1s before the end with a 5s horizon: measured at the last known price
    rets2 = forward_returns(ts, close, event_ts=8 * S, horizons_ns=[5 * S])
    assert rets2[5 * S] == pytest.approx(1.0 / 108.0 * 1e4)  # (109-108)/108 in bps


def test_forward_returns_direction_sign() -> None:
    # a sell event profits from DOWN moves: negate returns
    ts, close = make_up_series()
    rets = forward_returns(ts, close, event_ts=0, horizons_ns=[S], direction="sell")
    assert rets[S] == pytest.approx(-100.0)


def test_edge_table_golden() -> None:
    ts, close = make_up_series(n=10)
    events = [SignalEvent(ts_ns=0, direction="buy")]
    rows = edge_table(
        events,
        ts,
        close,
        horizons_ns=[S, 2 * S],
        cost_pairs=[("test_cost", 50.0)],
    )
    by_horizon = {row["horizon_s"]: row for row in rows}
    row1 = by_horizon[1]
    assert row1["n"] == 1
    assert row1["mean_bps"] == pytest.approx(100.0)
    assert row1["median_bps"] == pytest.approx(100.0)
    assert row1["hit_rate"] == pytest.approx(1.0)
    assert row1["mfe_bps"] == pytest.approx(100.0)
    assert row1["mae_bps"] == pytest.approx(0.0)
    assert row1["edges"] == {"test_cost": pytest.approx(50.0)}
    row2 = by_horizon[2]
    assert row2["mean_bps"] == pytest.approx(200.0)
    assert row2["mfe_bps"] == pytest.approx(200.0)
    assert row2["edges"] == {"test_cost": pytest.approx(150.0)}


def test_edge_table_mixed_outcomes() -> None:
    # prices go up then down: two events with different outcomes
    ts = np.arange(6, dtype=np.int64) * S
    close = np.array([100.0, 102.0, 101.0, 99.0, 100.0, 103.0])
    events = [SignalEvent(ts_ns=0, direction="buy"), SignalEvent(ts_ns=2 * S, direction="buy")]
    rows = edge_table(events, ts, close, horizons_ns=[S], cost_pairs=[])
    row = rows[0]
    assert row["n"] == 2
    # base = price AT the event: event1 100->102 (+200), event2 101->99 (-198)
    assert row["mean_bps"] == pytest.approx((200.0 - 198.01980198019802) / 2)
    assert row["hit_rate"] == pytest.approx(0.5)
    assert row["median_bps"] == pytest.approx(row["mean_bps"])  # 2 values: median = mean


def test_edge_table_no_events_is_clean() -> None:
    ts, close = make_up_series()
    rows = edge_table([], ts, close, horizons_ns=[S], cost_pairs=[("c", 10.0)])
    assert len(rows) == 1
    assert rows[0]["n"] == 0
    assert rows[0]["mean_bps"] is None
    assert rows[0]["edges"] == {"c": None}


def test_edge_table_undefined_horizons_excluded() -> None:
    ts, close = make_up_series(n=10)
    events = [
        SignalEvent(ts_ns=0, direction="buy"),
        SignalEvent(ts_ns=9 * S, direction="buy"),  # no data after
    ]
    rows = edge_table(events, ts, close, horizons_ns=[S], cost_pairs=[])
    row = rows[0]
    assert row["n"] == 2
    assert row["n_defined"] == 1
    assert row["mean_bps"] == pytest.approx(100.0)
