"""Tests for the daily time-series trend research model."""

import numpy as np
import pytest

from tradingv2.research.time_series_trend import (
    funding_mark_prices,
    holdout_screen,
    simulate_time_series_trend,
    summarize_equal_weight_portfolio,
    summarize_trend,
)

DAY_NS = 86_400_000_000_000
HOUR_NS = 3_600_000_000_000


def _timestamps(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.int64) * DAY_NS


def test_signal_uses_only_closed_lookback_and_applies_to_next_interval() -> None:
    ts = _timestamps(7)
    close = 100.0 * np.power(1.1, np.arange(7))
    result = simulate_time_series_trend(
        ts, close, np.array([], dtype=np.int64), np.array([]),
        lookback_days=2, mode="long_short", fee_per_side_bps=0.0,
    )
    assert result.positions.tolist() == [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    assert result.market_returns[2] == pytest.approx(close[3] / close[2] - 1.0)
    assert result.net_returns[2] == pytest.approx(result.market_returns[2])


def test_negative_trend_is_short_or_flat_by_mode() -> None:
    ts = _timestamps(6)
    close = 100.0 * np.power(0.9, np.arange(6))
    empty_ts = np.array([], dtype=np.int64)
    empty_rates = np.array([], dtype=float)
    short = simulate_time_series_trend(
        ts, close, empty_ts, empty_rates, lookback_days=2,
        mode="long_short", fee_per_side_bps=0.0,
    )
    long_flat = simulate_time_series_trend(
        ts, close, empty_ts, empty_rates, lookback_days=2,
        mode="long_flat", fee_per_side_bps=0.0,
    )
    assert short.positions[2:].tolist() == [-1.0] * 3
    assert all(value > 0.0 for value in short.net_returns[2:])
    assert long_flat.positions[2:].tolist() == [0.0] * 3
    assert long_flat.net_returns[2:].tolist() == pytest.approx([0.0] * 3)


def test_turnover_charges_each_side_and_a_flip_is_two_units() -> None:
    ts = _timestamps(5)
    close = np.array([100.0, 101.0, 99.0, 102.0, 100.0])
    result = simulate_time_series_trend(
        ts, close, np.array([], dtype=np.int64), np.array([]),
        lookback_days=1, mode="long_short", fee_per_side_bps=2.0,
    )
    # Position flips incur close+open; short exposure drift adds rebalance turnover.
    assert result.positions.tolist() == [0.0, 1.0, -1.0, 1.0]
    assert result.turnover[0] == 0.0
    assert result.turnover[1] == pytest.approx(1.0)
    assert result.turnover[2] > 2.0
    assert result.turnover[3] > 2.0
    assert result.fee_returns.sum() * 1e4 > 10.0


def test_funding_settlements_are_applied_to_the_position_in_force() -> None:
    ts = _timestamps(4)
    close = np.array([100.0, 110.0, 121.0, 133.1])
    settlements = np.array(
        [ts[2], ts[2] + 8 * HOUR_NS, ts[2] + 16 * HOUR_NS, ts[2] + DAY_NS],
        dtype=np.int64,
    )
    rates = np.array([0.001, 0.002, 0.003, 0.004])
    long = simulate_time_series_trend(
        ts, close, settlements, rates, lookback_days=1, mode="long_short",
        fee_per_side_bps=0.0,
    )
    assert long.positions[1] == 1.0
    assert long.funding_returns[1] == pytest.approx(-0.009)
    assert long.net_returns[1] == pytest.approx(long.market_returns[1] - 0.009)

    falling = simulate_time_series_trend(
        ts, close[::-1], settlements, rates, lookback_days=1, mode="long_short",
        fee_per_side_bps=0.0,
    )
    assert falling.positions[1] == -1.0
    assert falling.funding_returns[1] == pytest.approx(0.009)


def test_funding_notional_uses_last_completed_minute_price() -> None:
    ts = _timestamps(4)
    close = np.array([100.0, 110.0, 121.0, 133.1])
    settlements = np.array(
        [ts[2], ts[2] + 8 * HOUR_NS, ts[2] + 16 * HOUR_NS, ts[3]], dtype=np.int64
    )
    rates = np.array([0.001, 0.002, 0.003, 0.004])
    funding_prices = np.array([110.0, 121.0, 132.0, 133.0])
    result = simulate_time_series_trend(
        ts,
        close,
        settlements,
        rates,
        lookback_days=1,
        mode="long_short",
        fee_per_side_bps=0.0,
        funding_prices=funding_prices,
    )
    # A settlement exactly at the interval start precedes the new decision;
    # +8h, +16h and the end-boundary settle against this position.
    expected = -(0.002 * 121.0 + 0.003 * 132.0 + 0.004 * 133.0) / 110.0
    assert result.funding_returns[1] == pytest.approx(expected)


def test_funding_mark_uses_last_completed_minute_without_lookahead() -> None:
    minute_ns = 60_000_000_000
    funding_ts = np.array([minute_ns + 2_000_000, 2 * minute_ns], dtype=np.int64)
    minute_ts = np.array([0, minute_ns, 2 * minute_ns], dtype=np.int64)
    minute_open = np.array([10.0, 11.0, 12.0])
    minute_close = np.array([10.5, 11.5, 12.5])
    assert funding_mark_prices(
        funding_ts, minute_ts, minute_open, minute_close
    ).tolist() == [10.5, 11.5]


def test_funding_mark_falls_back_to_settlement_minute_open_at_data_start() -> None:
    assert funding_mark_prices(
        np.array([2_000_000], dtype=np.int64),
        np.array([0], dtype=np.int64),
        np.array([9.5]),
        np.array([10.5]),
    ).tolist() == [9.5]


def test_buy_and_hold_benchmark_is_long_from_first_interval() -> None:
    result = simulate_time_series_trend(
        _timestamps(4), np.array([100.0, 101.0, 99.0, 102.0]),
        np.array([], dtype=np.int64), np.array([]), lookback_days=2,
        mode="buy_hold", fee_per_side_bps=3.0,
    )
    assert result.positions.tolist() == [1.0, 1.0, 1.0]
    assert result.turnover[0] == pytest.approx(1.0)
    assert result.turnover[1] < 0.001  # restore 1x after entry fee
    assert result.turnover[2] < 0.001
    assert result.fee_returns.sum() * 1e4 == pytest.approx(3.001, abs=0.002)


def test_bad_or_non_daily_inputs_raise_clear_errors() -> None:
    ts = _timestamps(4)
    with pytest.raises(ValueError, match="strictly increasing"):
        simulate_time_series_trend(
            np.array([0, DAY_NS, DAY_NS, 3 * DAY_NS]), np.ones(4),
            np.array([], dtype=np.int64), np.array([]), lookback_days=1,
            mode="long_short", fee_per_side_bps=0.0,
        )
    with pytest.raises(ValueError, match="positive"):
        simulate_time_series_trend(
            ts, np.array([100.0, 101.0, 0.0, 102.0]),
            np.array([], dtype=np.int64), np.array([]), lookback_days=1,
            mode="long_short", fee_per_side_bps=0.0,
        )


def test_summary_reports_compounded_return_costs_and_exposure() -> None:
    ts = _timestamps(5)
    close = np.array([100.0, 102.0, 104.04, 103.0, 105.0])
    result = simulate_time_series_trend(
        ts, close, np.array([], dtype=np.int64), np.array([]),
        lookback_days=1, mode="long_flat", fee_per_side_bps=2.0,
    )
    summary = summarize_trend(result, hac_lag=1)
    assert summary["n_days"] == 4
    assert summary["total_return"] is not None
    assert summary["fees_bps"] == pytest.approx(4.0004, abs=0.001)
    assert summary["average_exposure"] == pytest.approx(0.5)
    assert summary["max_drawdown"] is not None
    assert summary["max_drawdown"] >= 0.0


def test_equal_weight_portfolio_averages_asset_level_net_returns() -> None:
    ts = _timestamps(4)
    empty_ts = np.array([], dtype=np.int64)
    empty_rates = np.array([], dtype=float)
    rising = simulate_time_series_trend(
        ts, np.array([100.0, 110.0, 121.0, 133.1]), empty_ts, empty_rates,
        lookback_days=1, mode="buy_hold", fee_per_side_bps=0.0,
    )
    falling = simulate_time_series_trend(
        ts, np.array([100.0, 90.0, 81.0, 72.9]), empty_ts, empty_rates,
        lookback_days=1, mode="buy_hold", fee_per_side_bps=0.0,
    )
    summary = summarize_equal_weight_portfolio([rising, falling], hac_lag=1)
    assert summary["total_return"] == pytest.approx(0.0, abs=1e-12)
    assert summary["average_exposure"] == pytest.approx(1.0)


def test_holdout_screen_requires_both_assets_positive_and_beats_benchmark() -> None:
    result = holdout_screen(
        {"BTCUSDT": 0.03, "ETHUSDT": 0.05},
        candidate_portfolio_return=0.04,
        benchmark_portfolio_return=0.02,
        rejected_exits=0,
    )
    assert result["candidate_survives_month"] is True
    checks = result["checks"]
    assert isinstance(checks, dict)
    assert all(checks.values())


def test_holdout_screen_fails_on_any_preregistered_condition() -> None:
    negative_asset = holdout_screen(
        {"BTCUSDT": 0.1, "ETHUSDT": -0.01},
        candidate_portfolio_return=0.05,
        benchmark_portfolio_return=-0.02,
        rejected_exits=0,
    )
    underperform = holdout_screen(
        {"BTCUSDT": 0.2, "ETHUSDT": 0.0},
        candidate_portfolio_return=0.05,
        benchmark_portfolio_return=0.02,
        rejected_exits=0,
    )
    rejected_exit = holdout_screen(
        {"BTCUSDT": 0.1, "ETHUSDT": 0.1},
        candidate_portfolio_return=0.05,
        benchmark_portfolio_return=0.02,
        rejected_exits=1,
    )
    assert negative_asset["candidate_survives_month"] is False
    assert underperform["candidate_survives_month"] is False
    assert rejected_exit["candidate_survives_month"] is False
