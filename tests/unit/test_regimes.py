"""Tests for volatility regime splits (terciles of realized vol)."""

import polars as pl
import pytest

from tradingv2.metrics.compute import regime_split

S = 1_000_000_000


def make_series(closes: list[float], equities: list[float]) -> tuple[pl.Series, pl.DataFrame]:
    assert len(closes) == len(equities)
    ts = [(i + 1) * S for i in range(len(closes))]
    equity = pl.DataFrame({"ts_ns": ts, "equity": equities})
    return pl.Series(closes), equity


def test_three_regimes_ordered_by_volatility() -> None:
    n = 30
    closes = (
        [5000.0] * n  # block A: zero volatility
        + [5000.0 + (2.0 if i % 2 else -2.0) for i in range(n)]  # block B: high vol
        + [5000.0 + (0.4 if i % 2 else -0.4) for i in range(n)]  # block C: medium vol
    )
    equities = [1000.0 + 0.1 * i for i in range(3 * n)]
    close, equity = make_series(closes, equities)
    regimes = regime_split(equity, close, interval_ns=S, vol_window=5)
    assert len(regimes) == 3
    labels = {r.label for r in regimes}
    assert labels == {"low", "mid", "high"}
    by_label = {r.label: r for r in regimes}
    # terciles split by VALUE: blocks are not exactly thirds, but all defined
    # bars are accounted for, zero-vol bars all fall in "low", and the regimes
    # are strictly ordered by mean volatility
    assert sum(r.n_bars for r in regimes) == 85  # 90 bars - 5 undefined
    assert by_label["low"].n_bars >= 25
    assert by_label["low"].vol_mean is not None
    assert by_label["mid"].vol_mean is not None
    assert by_label["high"].vol_mean is not None
    assert by_label["low"].vol_mean < by_label["mid"].vol_mean < by_label["high"].vol_mean
    assert by_label["low"].max_drawdown == pytest.approx(0.0)


def test_regime_metrics_have_core_fields() -> None:
    n = 30
    closes = [5000.0 + 0.1 * i for i in range(3 * n)]
    equities = [1000.0 + 0.5 * i for i in range(3 * n)]
    close, equity = make_series(closes, equities)
    regimes = regime_split(equity, close, interval_ns=S, vol_window=5)
    for regime in regimes:
        assert regime.n_bars > 0
        assert regime.total_return is not None
        assert regime.max_drawdown is not None
        assert regime.sharpe is not None


def test_too_few_bars_single_regime() -> None:
    closes = [5000.0] * 8
    equities = [1000.0 + 0.1 * i for i in range(8)]
    close, equity = make_series(closes, equities)
    regimes = regime_split(equity, close, interval_ns=S, vol_window=5)
    assert len(regimes) == 1
    assert regimes[0].label == "low"  # all bars in one bucket
    assert regimes[0].n_bars == 3  # 8 bars - 5 window


def test_regimes_deterministic() -> None:
    n = 30
    closes = [5000.0 + (1.0 if i % 3 else -1.0) for i in range(3 * n)]
    equities = [1000.0 + 0.2 * i for i in range(3 * n)]
    close, equity = make_series(closes, equities)
    r1 = regime_split(equity, close, interval_ns=S, vol_window=5)
    r2 = regime_split(equity, close, interval_ns=S, vol_window=5)
    assert r1 == r2
