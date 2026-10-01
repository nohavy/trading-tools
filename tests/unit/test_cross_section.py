"""Tests for cross-sectional momentum quintile studies (Way A core)."""

import numpy as np
import polars as pl
import pytest

from tradingv2.research.cross_section import (
    liquidity_filter,
    newey_west_tstat,
    quintile_spreads,
    top_minus_universe,
)

DAY = 86_400_000_000_000


def daily_frame(growth: dict[str, float], n_days: int) -> pl.DataFrame:
    """Long (ts_open_ns, symbol, close) frame: symbol s starts at 100, grows `growth[s]`/day."""
    return pl.DataFrame(
        {
            "ts_open_ns": [i * DAY for i in range(n_days) for _ in growth],
            "symbol": [s for _ in range(n_days) for s in growth],
            "close": [
                100.0 * growth[s] ** i for i in range(n_days) for s in growth
            ],
        }
    ).with_columns(pl.col("close").cast(pl.Float64))


def test_top_quintile_beats_bottom_with_forced_persistence() -> None:
    """4 assets with a constant daily drift: ranks never change, so the top
    bucket is the fastest riser and the bottom the fastest faller."""
    frame = daily_frame({"A": 1.01, "B": 1.005, "C": 1.0025, "D": 0.99}, n_days=40)
    result = quintile_spreads(frame, lookback_days=7, horizon_days=1)
    assert result.top_mean_bps == pytest.approx(100.0, abs=5.0)
    assert result.bottom_mean_bps == pytest.approx(-100.0, abs=5.0)
    assert result.spread_mean_bps == pytest.approx(200.0, abs=10.0)
    assert result.spread_hit_rate == pytest.approx(1.0)
    assert result.n_assets == 4


def test_n_dates_and_series_length() -> None:
    n_days = 30
    frame = daily_frame({"A": 1.004, "B": 1.001}, n_days=n_days)
    result = quintile_spreads(frame, lookback_days=5, horizon_days=1)
    # t runs over [lookback, n_days - horizon) -> 30 - 5 - 1 = 24 usable dates
    assert result.n_dates == 24
    assert result.spread_series is not None
    assert len(result.spread_series) == 24
    assert result.spread_median_bps is not None
    assert result.spread_hit_rate is not None


def test_spread_is_zero_without_persistence() -> None:
    """Identical drift for every asset: no cross-sectional dispersion to exploit."""
    frame = daily_frame({s: 1.005 for s in "ABCD"}, n_days=40)
    result = quintile_spreads(frame, lookback_days=7, horizon_days=1)
    assert result.spread_mean_bps == pytest.approx(0.0, abs=1.0)


def test_neutral_band_is_excluded_from_spread() -> None:
    """5 assets, 1%/day spread between the extremes -> 100 bps minus 20 bps."""
    frame = daily_frame(
        {"A": 0.998, "B": 1.0, "C": 1.002, "D": 1.005, "E": 1.01}, n_days=30
    )
    result = quintile_spreads(frame, lookback_days=5, horizon_days=1)
    assert result.top_mean_bps == pytest.approx(100.0, abs=10.0)
    assert result.bottom_mean_bps == pytest.approx(-20.0, abs=10.0)
    assert result.spread_mean_bps == pytest.approx(120.0, abs=20.0)


def test_cost_adjustment_reduces_spread() -> None:
    frame = daily_frame({"A": 1.01, "B": 1.005, "C": 1.0025, "D": 0.99}, n_days=40)
    gross = quintile_spreads(frame, lookback_days=7, horizon_days=1)
    net = quintile_spreads(frame, lookback_days=7, horizon_days=1, round_trip_bps=4.0)
    assert gross.spread_mean_bps is not None
    assert net.spread_mean_bps == pytest.approx(gross.spread_mean_bps - 4.0)


def test_gap_in_one_asset_is_tolerated() -> None:
    """Asset B is listed 3 days late: the study still runs on the other dates."""
    n_days = 30
    ts = [i * DAY for i in range(n_days)]
    frame = pl.DataFrame(
        {
            "ts_open_ns": ts + ts + ts[3:],
            "symbol": ["A"] * n_days + ["B"] * n_days + ["C"] * (n_days - 3),
            "close": (
                [100.0 * 1.004 ** i for i in range(n_days)]
                + [100.0 * 1.001 ** i for i in range(n_days)]
                + [100.0 * 0.999 ** i for i in range(3, n_days)]
            ),
        }
    )
    result = quintile_spreads(frame, lookback_days=5, horizon_days=1)
    assert result.n_dates > 0
    assert result.n_assets == 3
    assert result.spread_mean_bps is not None


def test_insufficient_assets_raises() -> None:
    frame = daily_frame({"A": 1.01, "B": 0.99}, n_days=20)
    with pytest.raises(ValueError, match="assets"):
        quintile_spreads(frame, lookback_days=5, horizon_days=1, min_assets=3)


def test_empty_result_when_no_usable_date() -> None:
    frame = daily_frame({"A": 1.01, "B": 0.99, "C": 1.0}, n_days=4)
    result = quintile_spreads(frame, lookback_days=5, horizon_days=1)
    assert result.n_dates == 0
    assert result.spread_mean_bps is None
    assert result.spread_series is None


def _long_with_volumes(volumes: dict[str, float], n_days: int = 40) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_open_ns": [i * DAY for i in range(n_days) for _ in volumes],
            "symbol": [s for _ in range(n_days) for s in volumes],
            "close": [
                100.0 * 1.002**i for i in range(n_days) for _ in volumes
            ],
            "quote_volume": [volumes[s] for _ in range(n_days) for s in volumes],
        }
    )


def test_liquidity_filter_drops_the_illiquid_tail() -> None:
    volumes = {f"A{i}": 1_000_000.0 for i in range(8)}
    volumes["A0"] = 1_000.0
    volumes["A1"] = 2_000.0
    filtered = liquidity_filter(_long_with_volumes(volumes), quantile=0.2)
    survivors = set(filtered["symbol"].unique().to_list())
    assert survivors == set(f"A{i}" for i in range(2, 8))


def test_liquidity_filter_keeps_everything_when_uniform() -> None:
    volumes = {f"A{i}": 5_000_000.0 for i in range(6)}
    filtered = liquidity_filter(_long_with_volumes(volumes), quantile=0.2)
    assert filtered["symbol"].n_unique() == 6


def test_liquidity_filter_uses_trailing_median() -> None:
    """The asset whose volume dies (HOT) is dropped once its trailing median sags."""
    n_days = 60
    ts = [i * DAY for i in range(n_days)]
    frame = pl.DataFrame(
        {
            "ts_open_ns": ts * 2,
            "symbol": ["HOT"] * n_days + ["COLD"] * n_days,
            "close": [100.0] * (n_days * 2),
            "quote_volume": [1_000_000.0] * 40 + [1.0] * 20 + [1_000_000.0] * n_days,
        }
    )
    filtered = liquidity_filter(frame, quantile=0.5, lookback=30)
    last_dates = filtered.filter(pl.col("ts_open_ns") == ts[-1])["symbol"].to_list()
    assert last_dates == ["COLD"]
    early_dates = set(filtered.filter(pl.col("ts_open_ns") == ts[35])["symbol"].to_list())
    assert early_dates == {"HOT", "COLD"}


def test_newey_west_tstat_matches_iid_expectation() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(0.5, 1.0, size=500).tolist()
    t = newey_west_tstat(x, lag=1)
    naive = np.mean(x) / (np.std(x, ddof=1) / np.sqrt(len(x)))
    assert t == pytest.approx(naive, rel=0.15)
    assert t > 2.0


def test_newey_west_penalises_positive_autocorrelation() -> None:
    """Overlapping forward windows inflate the naive t-stat; NW must shrink it."""
    rng = np.random.default_rng(11)
    shocks = rng.normal(0.0, 1.0, size=400)
    x = np.cumsum(shocks) * 0.1 + 0.2  # strong positive autocorrelation
    naive = float(np.mean(x) / (np.std(x, ddof=1) / np.sqrt(x.size)))
    t = newey_west_tstat(x.tolist(), lag=5)
    assert abs(t) < abs(naive)


def test_newey_west_tstat_nan_when_series_too_short() -> None:
    assert np.isnan(newey_west_tstat([0.1, 0.2], lag=5))


def test_top_minus_universe_isolates_selection_from_beta() -> None:
    """The universe drifts up but the top bucket drifts up more: the difference
    is the selection effect, independent of the market's own drift."""
    frame = daily_frame({"A": 1.02, "B": 1.01, "C": 1.0, "D": 0.99, "E": 0.98}, n_days=40)
    result = top_minus_universe(frame, lookback_days=7, horizon_days=1, top_fraction=0.2)
    # top = A (+200 bps/day forward), universe mean = (200+100+0-100-200)/5 = 0
    assert result.top_mean_bps == pytest.approx(200.0, abs=10.0)
    assert result.benchmark_mean_bps == pytest.approx(0.0, abs=10.0)
    assert result.difference_mean_bps == pytest.approx(200.0, abs=20.0)
    assert result.n_dates == 40 - 7 - 1


def test_top_minus_universe_zero_without_persistence() -> None:
    frame = daily_frame({s: 1.005 for s in "ABCDE"}, n_days=30)
    result = top_minus_universe(frame, lookback_days=5, horizon_days=1)
    assert result.difference_mean_bps == pytest.approx(0.0, abs=1.0)


def test_top_minus_universe_subtracts_one_leg_round_trip() -> None:
    frame = daily_frame({"A": 1.02, "B": 1.01, "C": 1.0, "D": 0.99, "E": 0.98}, n_days=40)
    gross = top_minus_universe(frame, lookback_days=7, horizon_days=1)
    net = top_minus_universe(frame, lookback_days=7, horizon_days=1, round_trip_bps=4.0)
    assert gross.difference_mean_bps is not None
    assert net.difference_mean_bps == pytest.approx(gross.difference_mean_bps - 4.0)
    # the cost hits the difference, not the raw top return
    assert net.top_mean_bps == pytest.approx(gross.top_mean_bps)


def test_top_minus_universe_returns_empty_when_no_usable_date() -> None:
    frame = daily_frame({s: 1.01 for s in "ABC"}, n_days=4)
    result = top_minus_universe(frame, lookback_days=5, horizon_days=1)
    assert result.n_dates == 0
    assert result.difference_mean_bps is None
