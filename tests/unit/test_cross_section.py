"""Tests for cross-sectional momentum quintile studies (Way A core)."""

import polars as pl
import pytest

from tradingv2.research.cross_section import quintile_spreads

DAY = 86_400_000_000_000


def daily_frame(growth: dict[str, float], n_days: int) -> pl.DataFrame:
    """Long (ts_ns, symbol, close) frame: symbol s starts at 100, grows `growth[s]`/day."""
    return pl.DataFrame(
        {
            "ts_ns": [i * DAY for i in range(n_days) for _ in growth],
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
            "ts_ns": ts + ts + ts[3:],
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
