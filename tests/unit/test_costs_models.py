"""Tests for slippage and latency cost models."""

import pytest

from tradingv2.core.types import Side
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel


def test_slippage_buy_pays_up() -> None:
    model = SlippageModel(bps=1.0)
    assert model.adjust(100.0, Side.BUY) == pytest.approx(100.0 * (1 + 1e-4))
    assert model.adjust(100.0, Side.SELL) == pytest.approx(100.0 * (1 - 1e-4))


def test_slippage_zero_is_identity() -> None:
    model = SlippageModel(bps=0.0)
    assert model.adjust(100.0, Side.BUY) == 100.0


def test_negative_slippage_rejected() -> None:
    with pytest.raises(ValueError):
        SlippageModel(bps=-1.0)


def test_latency_deterministic_with_seed() -> None:
    a = LatencyModel(mean_ms=150, jitter_ms=50, seed=42)
    b = LatencyModel(mean_ms=150, jitter_ms=50, seed=42)
    samples_a = [a.sample_ns() for _ in range(100)]
    samples_b = [b.sample_ns() for _ in range(100)]
    assert samples_a == samples_b


def test_latency_non_negative() -> None:
    model = LatencyModel(mean_ms=5, jitter_ms=50, seed=1)
    assert all(model.sample_ns() >= 0 for _ in range(200))


def test_latency_zero_jitter_is_mean() -> None:
    model = LatencyModel(mean_ms=150, jitter_ms=0, seed=7)
    assert model.sample_ns() == 150_000_000


def test_negative_mean_rejected() -> None:
    with pytest.raises(ValueError):
        LatencyModel(mean_ms=-1, jitter_ms=10, seed=1)
