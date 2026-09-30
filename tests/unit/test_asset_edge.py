"""Tests for per-asset edge scoring (signals vs maker costs, ranked)."""

import polars as pl
import pytest

from tradingv2.research.scan import asset_edge

S = 1_000_000_000


def make_bars(
    n: int = 400, drift: float = 0.0, spike_every: int = 0, spike_size: float = 0.0
) -> pl.DataFrame:
    closes = []
    volumes = []
    for i in range(n):
        base = 5000.0 + drift * i
        if spike_every and i > 30 and i % spike_every == 0:
            base += spike_size
        closes.append(base)
        volumes.append(200.0 if spike_every and i % spike_every == 0 else 10.0)
    return pl.DataFrame(
        {
            "ts_open_ns": [i * S for i in range(n)],
            "open": [closes[max(i - 1, 0)] for i in range(n)],
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
            "quote_volume": [c * v for c, v in zip(closes, volumes, strict=True)],
            "n_trades": [1] * n,
            "taker_buy_volume": [v / 2 for v in volumes],
            "taker_buy_quote_volume": [c * v / 2 for c, v in zip(closes, volumes, strict=True)],
        }
    )


def test_asset_edge_returns_scores_for_all_signals() -> None:
    result = asset_edge(make_bars(400, drift=0.05, spike_every=25, spike_size=8.0))
    assert set(result["signals"]) == {"breakout", "meanrev", "flow"}
    for signal in result["signals"].values():
        assert "mean_bps" in signal
        assert "hit_rate" in signal
    assert result["score_bps"] is not None
    assert result["edge_net_bps"] == pytest.approx(result["score_bps"] - 4.0)
    assert result["n_events"] > 0


def test_asset_edge_upward_market_prefers_breakout() -> None:
    # a steady uptrend with breakouts: breakout should be the best signal
    result = asset_edge(make_bars(400, drift=0.05, spike_every=25, spike_size=8.0))
    assert result["best_signal"] == "breakout"


def test_asset_edge_flat_market_low_scores() -> None:
    # a steady drift fires no signal crossing: no score, no events
    result = asset_edge(make_bars(400))
    assert result["score_bps"] is None
    assert result["n_events"] == 0
    assert result["few_events"] is True


def test_asset_edge_few_events_flag() -> None:
    result = asset_edge(make_bars(400), min_events=10_000)
    assert result["few_events"] is True


def test_asset_edge_json_safe() -> None:
    import json

    result = asset_edge(make_bars(400, drift=0.05, spike_every=25, spike_size=8.0))
    json.dumps(result)  # must not raise
