"""Tests for simulated exchange order validation (at arrival, like Binance)."""

import polars as pl
import pytest

from tradingv2.config import Market
from tradingv2.core.types import Order, OrderStatus, OrderType, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def _status(order: Order) -> OrderStatus:
    return order.status


def make_exchange(**overrides: object) -> SimulatedExchange:
    kwargs: dict[str, object] = {
        "rules": RULES,
        "account": MarginAccount(balance=10_000.0, leverage=5),
        "fees": FeeSchedule(maker_bps=2, taker_bps=5),
        "slippage": SlippageModel(bps=0.5),
        "latency": LatencyModel(mean_ms=100, jitter_ms=0, seed=1),
        "tape": None,
    }
    kwargs.update(overrides)
    return SimulatedExchange(**kwargs)  # type: ignore[arg-type]


def make_order(**overrides: object) -> Order:
    kwargs: dict[str, object] = {
        "id": 1,
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "type": OrderType.MARKET,
        "qty": 0.001,
        "submitted_ns": 0,
    }
    kwargs.update(overrides)
    return Order(**kwargs)  # type: ignore[arg-type]


TAPE = pl.DataFrame(
    {
        "ts_ns": [500_000_000, 600_000_000, 700_000_000],
        "price": [5000.0, 5000.1, 5000.2],
        "qty": [1.0, 2.0, 1.5],
        "buyer_is_maker": [False, True, False],
    }
)


def test_order_becomes_active_after_latency() -> None:
    exchange = make_exchange(tape=TAPE)
    order = exchange.submit(make_order())
    assert _status(order) == OrderStatus.PENDING
    exchange.advance_to(100_000_000)
    assert _status(order) == OrderStatus.ACTIVE
    assert order.arrive_ns == 100_000_000


def test_qty_below_step_rejected() -> None:
    exchange = make_exchange(tape=TAPE)
    order = exchange.submit(make_order(qty=0.0005))
    exchange.advance_to(200_000_000)
    assert _status(order) == OrderStatus.REJECTED
    assert order.reject_reason is not None
    assert "step" in order.reject_reason


def test_qty_rounded_down_to_step() -> None:
    exchange = make_exchange(tape=TAPE)
    order = exchange.submit(make_order(qty=0.0015))
    exchange.advance_to(200_000_000)
    assert _status(order) == OrderStatus.ACTIVE
    assert order.qty == 0.001


def test_notional_below_min_rejected() -> None:
    low_tape = pl.DataFrame(
        {
            "ts_ns": [500_000_000],
            "price": [4000.0],
            "qty": [1.0],
            "buyer_is_maker": [False],
        }
    )
    exchange = make_exchange(tape=low_tape)
    order = exchange.submit(make_order(qty=0.001))  # 0.001 * 4000 = 4 < 5
    exchange.advance_to(200_000_000)
    assert _status(order) == OrderStatus.REJECTED
    assert order.reject_reason is not None
    assert "notional" in order.reject_reason


def test_limit_price_rounded_down_to_tick() -> None:
    exchange = make_exchange(tape=TAPE)
    order = exchange.submit(make_order(type=OrderType.LIMIT, qty=0.001, limit_price=5000.05))
    exchange.advance_to(200_000_000)
    assert _status(order) == OrderStatus.ACTIVE
    assert order.limit_price == 5000.0


def test_insufficient_margin_rejected() -> None:
    poor = MarginAccount(balance=100.0, leverage=5)
    exchange = make_exchange(tape=TAPE, account=poor)
    order = exchange.submit(make_order(qty=10.0))  # notional 50_000, margin 10_000 > 100
    exchange.advance_to(200_000_000)
    assert _status(order) == OrderStatus.REJECTED
    assert order.reject_reason is not None
    assert "margin" in order.reject_reason


def test_cancel_before_arrival() -> None:
    exchange = make_exchange(tape=TAPE)
    order = exchange.submit(make_order())
    exchange.cancel(order.id, now_ns=50_000_000)
    exchange.advance_to(200_000_000)
    assert _status(order) == OrderStatus.CANCELED


def test_cancel_unknown_order_raises() -> None:
    exchange = make_exchange()
    with pytest.raises(Exception, match="unknown"):
        exchange.cancel(999, now_ns=0)
