"""Tests for incremental indicators (step mode — the live-parity contract)."""

import pytest

from tradingv2.features.incremental import (
    EmaIncr,
    FlowImbalanceIncr,
    RealizedVolIncr,
    VwapIncr,
    ZScoreIncr,
)

DAY_NS = 86_400_000_000_000


def test_ema_incr_golden_span3() -> None:
    ema = EmaIncr(span=3)
    assert ema.update(1.0) == pytest.approx(1.0)
    assert ema.update(2.0) == pytest.approx(1.5)
    assert ema.update(3.0) == pytest.approx(2.25)
    assert ema.update(4.0) == pytest.approx(3.125)


def test_zscore_incr_undefined_until_window_full() -> None:
    z = ZScoreIncr(window=3)
    assert z.update(1.0) is None
    assert z.update(2.0) is None
    expected = 1 / (2 / 3) ** 0.5
    assert z.update(3.0) == pytest.approx(expected)
    assert z.update(4.0) == pytest.approx(expected)
    assert z.update(5.0) == pytest.approx(expected)


def test_zscore_incr_constant_is_undefined() -> None:
    z = ZScoreIncr(window=3)
    for _ in range(5):
        assert z.update(5.0) is None


def test_vwap_incr_resets_at_utc_midnight() -> None:
    vwap = VwapIncr()
    assert vwap.update(0, 100.0, 1.0) == pytest.approx(100.0)
    assert vwap.update(DAY_NS - 1, 110.0, 1.0) == pytest.approx(105.0)
    assert vwap.update(DAY_NS, 200.0, 1.0) == pytest.approx(200.0)  # reset
    assert vwap.update(DAY_NS + 60_000_000_000, 220.0, 1.0) == pytest.approx(210.0)


def test_vwap_incr_undefined_before_volume() -> None:
    vwap = VwapIncr()
    assert vwap.update(0, 100.0, 0.0) is None
    assert vwap.update(1, 100.0, 0.0) is None
    assert vwap.update(2, 100.0, 5.0) == pytest.approx(100.0)


def test_realized_vol_incr_undefined_until_returns() -> None:
    vol = RealizedVolIncr(window=3)
    assert vol.update(100.0) is None  # first close: no return yet
    assert vol.update(101.0) is None
    assert vol.update(102.0) is None  # 2 returns, need 3
    r = [101 / 100 - 1, 102 / 101 - 1, 100 / 102 - 1]
    mean = sum(r) / 3
    std = (sum((x - mean) ** 2 for x in r) / 3) ** 0.5
    assert vol.update(100.0) == pytest.approx(std)


def test_flow_imbalance_incr_golden_window2() -> None:
    flow = FlowImbalanceIncr(window=2)
    assert flow.update(10.0, 10.0) is None
    assert flow.update(10.0, 0.0) == pytest.approx(0.0)
    assert flow.update(10.0, 5.0) == pytest.approx(-0.5)
    assert flow.update(10.0, 2.0) == pytest.approx(-0.3)


def test_flow_imbalance_incr_zero_volume_undefined() -> None:
    flow = FlowImbalanceIncr(window=2)
    flow.update(0.0, 0.0)
    assert flow.update(0.0, 0.0) is None
