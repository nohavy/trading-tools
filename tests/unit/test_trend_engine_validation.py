"""Tests for daily OOS aggregation of event-engine equity curves."""

import numpy as np
import pytest

from tradingv2.research.time_series_trend import summarize_daily_equity_curve

DAY_NS = 86_400_000_000_000
START_NS = 1_688_169_600_000_000_000
END_NS = 1_788_192_000_000_000_000


def test_daily_metrics_uses_only_complete_oos_midnight_marks() -> None:
    timestamps = np.arange(START_NS, END_NS + 1, DAY_NS, dtype=np.int64)
    equity = 10_000.0 * np.power(1.001, np.arange(timestamps.size))

    stats = summarize_daily_equity_curve(
        timestamps, equity, start_ns=START_NS, end_ns=END_NS
    )
    assert stats["n_days"] == timestamps.size - 1
    assert stats["total_return"] == pytest.approx(equity[-1] / equity[0] - 1.0)
    assert stats["cagr"] == pytest.approx(1.001**365 - 1.0, rel=1e-8)
    assert stats["max_drawdown"] == pytest.approx(0.0, abs=1e-12)
    assert stats["t_stat_nw"] is not None


def test_daily_metrics_rejects_a_gap_in_oos_midnight_marks() -> None:
    timestamps = np.array(
        [START_NS, START_NS + DAY_NS, START_NS + 3 * DAY_NS], dtype=np.int64
    )
    with pytest.raises(ValueError, match="missing daily OOS"):
        summarize_daily_equity_curve(
            timestamps,
            np.array([100.0, 101.0, 102.0]),
            start_ns=START_NS,
            end_ns=END_NS,
        )
