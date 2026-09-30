"""Tests for core order/fill types and status transitions."""

import pytest

from tradingv2.core.types import (
    Fill,
    FillRole,
    InvalidTransitionError,
    Order,
    OrderError,
    OrderStatus,
    OrderType,
    Side,
)

T_NS = 1_790_294_400_000_000_000


def _mk(**overrides: object) -> Order:
    kwargs: dict = {
        "id": 1,
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "type": OrderType.MARKET,
        "qty": 0.001,
        "submitted_ns": T_NS,
    }
    kwargs.update(overrides)
    return Order(**kwargs)  # type: ignore[arg-type]


def test_market_order_defaults() -> None:
    order = _mk()
    assert order.status == OrderStatus.PENDING
    assert order.arrive_ns is None
    assert order.limit_price is None and order.stop_price is None
    assert order.post_only is False


def test_limit_order_requires_price() -> None:
    with pytest.raises(OrderError, match="limit_price"):
        _mk(type=OrderType.LIMIT)


def test_stop_order_requires_stop_price() -> None:
    with pytest.raises(OrderError, match="stop_price"):
        _mk(type=OrderType.STOP_MARKET)


def test_market_order_rejects_limit_price() -> None:
    with pytest.raises(OrderError, match="limit_price"):
        _mk(limit_price=100.0)


def test_post_only_requires_limit_type() -> None:
    with pytest.raises(OrderError, match="post_only"):
        _mk(post_only=True)


def test_non_positive_qty_rejected() -> None:
    with pytest.raises(OrderError, match="qty"):
        _mk(qty=0.0)


def test_valid_transition_chain() -> None:
    order = _mk()
    order.transition(OrderStatus.ACTIVE)
    order.transition(OrderStatus.FILLED)
    assert order.status == OrderStatus.FILLED


def test_pending_to_filled_is_invalid() -> None:
    order = _mk()
    with pytest.raises(InvalidTransitionError):
        order.transition(OrderStatus.FILLED)


def test_terminal_state_is_immutable() -> None:
    order = _mk()
    order.transition(OrderStatus.REJECTED)
    with pytest.raises(InvalidTransitionError):
        order.transition(OrderStatus.ACTIVE)


def test_fill_fields() -> None:
    fill = Fill(
        order_id=1, ts_ns=T_NS, price=84410.0, qty=0.001,
        fee=0.042, role=FillRole.TAKER, side=Side.BUY,
    )
    assert fill.role == FillRole.TAKER
    assert fill.fee >= 0
