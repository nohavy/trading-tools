"""Tests for the Monte Carlo bootstrap of trade sequences."""

import math

import pytest

from tradingv2.backtest.montecarlo import MonteCarloError, bootstrap_trips


def test_bootstrap_golden_exact_small() -> None:
    nets = [1.0, -1.0]
    result = bootstrap_trips(nets, n_sims=4, seed=0, dd_threshold=1.5)
    # recompute the exact draws with the same rng logic
    import numpy as np

    rng = np.random.default_rng(0)
    draws = rng.choice(np.array(nets), size=(4, 2), replace=True)
    finals = draws.sum(axis=1)
    cum = np.cumsum(draws, axis=1)
    peaks = np.maximum.accumulate(cum, axis=1)
    dd = (peaks - cum).max(axis=1)
    assert result.p5 == pytest.approx(float(np.percentile(finals, 5)))
    assert result.p50 == pytest.approx(float(np.percentile(finals, 50)))
    assert result.p95 == pytest.approx(float(np.percentile(finals, 95)))
    assert result.prob_dd_over == pytest.approx(float((dd > 1.5).mean()))
    assert result.n_sims == 4


def test_bootstrap_deterministic_with_seed() -> None:
    r1 = bootstrap_trips([1.0, -0.5, 2.0, 0.3], n_sims=100, seed=7, dd_threshold=1.0)
    r2 = bootstrap_trips([1.0, -0.5, 2.0, 0.3], n_sims=100, seed=7, dd_threshold=1.0)
    assert (r1.p5, r1.p50, r1.p95, r1.prob_dd_over) == (r2.p5, r2.p50, r2.p95, r2.prob_dd_over)


def test_bootstrap_percentiles_ordered_and_bounded() -> None:
    nets = [1.0, -0.5, 2.0, 0.3, -1.2, 0.8]
    result = bootstrap_trips(nets, n_sims=1000, seed=3, dd_threshold=1.0)
    assert result.p5 <= result.p50 <= result.p95
    lo, hi = min(nets) * len(nets), max(nets) * len(nets)
    assert lo <= result.p5 and result.p95 <= hi
    assert 0.0 <= result.prob_dd_over <= 1.0


def test_bootstrap_all_winning_no_drawdown() -> None:
    result = bootstrap_trips([1.0] * 10, n_sims=50, seed=1, dd_threshold=0.5)
    assert result.prob_dd_over == 0.0  # monotone gains: no drawdown ever
    assert result.p5 == pytest.approx(10.0)
    assert result.p95 == pytest.approx(10.0)


def test_bootstrap_empty_raises() -> None:
    with pytest.raises(MonteCarloError, match="no trades"):
        bootstrap_trips([], n_sims=10, seed=1, dd_threshold=1.0)


def test_bootstrap_fast_1000_sims() -> None:
    import time

    nets = [0.1 * math.sin(i) for i in range(500)]
    start = time.perf_counter()
    bootstrap_trips(nets, n_sims=1000, seed=1, dd_threshold=1.0)
    assert time.perf_counter() - start < 10.0
