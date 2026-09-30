"""Tests for exchange filter rounding and order value validation."""

import pytest

from tradingv2.core.rounding import (
    RoundingError,
    order_values_pass_filters,
    round_price_to_tick,
    round_qty_to_step,
)


def test_round_qty_down_to_step() -> None:
    # 0.00159 is an exact multiple of 0.00001 (float division would say otherwise)
    assert round_qty_to_step(0.00159, 0.00001) == 0.00159
    assert round_qty_to_step(0.001599, 0.00001) == 0.00159


def test_round_price_down_to_tick() -> None:
    assert round_price_to_tick(84410.249, 0.01) == 84410.24
    assert round_price_to_tick(84410.2, 0.1) == 84410.2


def test_zero_or_negative_step_raises() -> None:
    with pytest.raises(RoundingError):
        round_qty_to_step(1.0, 0.0)
    with pytest.raises(RoundingError):
        round_price_to_tick(1.0, -0.01)


def test_zero_or_negative_values_raise() -> None:
    with pytest.raises(RoundingError):
        round_qty_to_step(0.0, 0.001)
    with pytest.raises(RoundingError):
        round_price_to_tick(-1.0, 0.01)


def test_order_values_pass() -> None:
    ok, reason = order_values_pass_filters(0.001, 84410.0, 0.001, 0.01, 5.0)
    assert ok and reason is None


def test_order_qty_below_step_fails() -> None:
    ok, reason = order_values_pass_filters(0.0005, 84410.0, 0.001, 0.01, 5.0)
    assert not ok
    assert reason is not None
    assert "step" in reason


def test_order_notional_below_min_fails() -> None:
    ok, reason = order_values_pass_filters(0.00001, 84410.0, 0.00001, 0.01, 5.0)
    assert not ok
    assert reason is not None
    assert "notional" in reason


def test_order_zero_qty_fails() -> None:
    ok, reason = order_values_pass_filters(0.0, 84410.0, 0.001, 0.01, 5.0)
    assert not ok
    assert reason is not None
    assert "qty" in reason
