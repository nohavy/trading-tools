"""Tests for per-asset metrics (volatility, liquidity, breakouts, funding)."""

import polars as pl
import pytest

from tradingv2.research.asset_metrics import asset_metrics

S = 1_000_000_000


def make_bars(
    n: int, closes: list[float] | None = None, volumes: list[float] | None = None
) -> pl.DataFrame:
    values = closes or [5000.0 + 0.1 * i for i in range(n)]
    vols = volumes or [10.0] * n
    return pl.DataFrame(
        {
            "ts_open_ns": [i * S for i in range(len(values))],
            "open": values,
            "high": [c + 0.3 for c in values],
            "low": [c - 0.3 for c in values],
            "close": values,
            "volume": vols,
            "quote_volume": [c * v for c, v in zip(values, vols, strict=True)],
            "n_trades": [1] * len(values),
            "taker_buy_volume": [v / 2 for v in vols],
            "taker_buy_quote_volume": [c * v / 2 for c, v in zip(values, vols, strict=True)],
        }
    )


def test_volatility_bps_1m() -> None:
    # alternating ±1/5000: returns alternate ±4 bps → std ≈ 4 bps
    closes = [5000.0 + (1.0 if i % 2 else -1.0) for i in range(100)]
    metrics = asset_metrics(make_bars(100, closes=closes))
    assert metrics["vol_bps_1m"] is not None
    assert 3.0 < metrics["vol_bps_1m"] < 5.0


def test_volatility_bps_1h_aggregated() -> None:
    metrics = asset_metrics(make_bars(120))  # 2 hours of drifting bars
    assert metrics["vol_bps_1h"] is not None


def test_liquidity_metrics() -> None:
    bars = make_bars(120, volumes=[10.0] * 120)
    metrics = asset_metrics(bars)
    # 120 bars all in one UTC day: the daily mean = that day's total
    assert metrics["quote_volume_daily"] == pytest.approx(50000.0 * 120, rel=0.01)
    assert metrics["n_trades_daily"] == pytest.approx(120, rel=0.01)


def test_breakout_frequency() -> None:
    # repeated range breaks with volume confirmation every 31 bars
    closes: list[float] = []
    volumes: list[float] = []
    for i in range(93):
        base = 5000.0 + (i // 31) * 20.0
        closes.append(base)
        volumes.append(50.0 if i in (31, 62) else 10.0)  # spikes on break bars
    metrics = asset_metrics(make_bars(93, closes=closes, volumes=volumes))
    assert metrics["breakout_freq"] is not None
    assert metrics["breakout_freq"] > 0
    assert metrics["breakout_freq"] < 5.0  # a few breaks per day, not thousands


def test_funding_metrics_present() -> None:
    funding = pl.DataFrame(
        {
            "ts_ns": [i * 8 * 3600 * S for i in range(5)],
            "rate": [0.0001, 0.0002, -0.0001, 0.0003, 0.0],
        }
    )
    metrics = asset_metrics(make_bars(100), funding=funding)
    assert metrics["funding_mean_bps"] is not None
    assert metrics["funding_p95_bps"] is not None


def test_funding_absent_gives_none() -> None:
    metrics = asset_metrics(make_bars(100), funding=None)
    assert metrics["funding_mean_bps"] is None
    assert metrics["funding_p95_bps"] is None


def test_dead_asset_marked() -> None:
    # tiny volumes: quote volume daily far below the threshold
    bars = make_bars(120, volumes=[0.0001] * 120)
    metrics = asset_metrics(bars, min_quote_volume_daily=1_000_000.0)
    assert metrics["dead"] is True


def test_alive_asset_not_dead() -> None:
    metrics = asset_metrics(make_bars(120), min_quote_volume_daily=1_000_000.0, min_days=0.001)
    assert metrics["dead"] is False


def test_too_few_days_marked_dead() -> None:
    # 120 one-minute bars = ~0.08 days of span: dead with the default 20-day rule
    metrics = asset_metrics(make_bars(120), min_quote_volume_daily=0.0)
    assert metrics["dead"] is True
    assert metrics["n_bars"] == 120


def test_metrics_is_json_safe() -> None:
    import json

    metrics = asset_metrics(make_bars(100), funding=None)
    json.dumps(metrics)  # must not raise
