"""Tests for limit order fills against the trade tape."""

import polars as pl
import pytest

from tradingv2.config import Market
from tradingv2.core.types import FillRole, Order, OrderStatus, OrderType, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount

MS = 1_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)

# prices: 5000.0, 4999.9, 5000.3, 5000.0, 4999.8
TAPE = pl.DataFrame(
    {
        "ts_ns": [100 * MS, 200 * MS, 300 * MS, 400 * MS, 500 * MS],
        "price": [5000.0, 4999.9, 5000.3, 5000.0, 4999.8],
        "qty": [1.0, 1.0, 1.0, 1.0, 1.0],
        "buyer_is_maker": [False, False, True, False, False],
    }
)


def make_exchange(mode: str = "pessimistic") -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=1_000_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=100, jitter_ms=0, seed=1),
        tape=TAPE,
        limit_fill_mode=mode,
    )


def make_buy_limit(
    price: float, qty: float = 0.001, post_only: bool = False, submitted_ns: int = 0
) -> Order:

    return Order(
        id=1, symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT,
        qty=qty, submitted_ns=submitted_ns, limit_price=price, post_only=post_only,
    )


def test_pessimistic_needs_trade_through_not_touch() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(5000.0))
    events = exchange.advance_to(1_000 * MS)
    # trade at 100ms touches 5000.0 but does not go through: no fill then
    assert order.status == OrderStatus.FILLED
    # first STRICT below 5000.0 is the trade at 200ms (4999.9)
    assert events[0].fill.ts_ns == 200 * MS
    assert events[0].fill.price == pytest.approx(5000.0)  # filled AT the limit


def test_optimistic_fills_on_touch() -> None:
    exchange = make_exchange(mode="optimistic")
    order = exchange.submit(make_buy_limit(5000.0))
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.ts_ns == 100 * MS  # touch at 5000.0 fills


def test_limit_fill_is_maker_with_limit_price() -> None:
    exchange = make_exchange()
    exchange.submit(make_buy_limit(5000.0, qty=0.001))
    events = exchange.advance_to(1_000 * MS)
    fill = events[0].fill
    assert fill.role == FillRole.MAKER
    assert fill.price == pytest.approx(5000.0)
    assert fill.fee == pytest.approx(0.001 * 5000.0 * 2 / 10_000)


def test_sell_limit_pessimistic_through() -> None:
    exchange = make_exchange()
    from tradingv2.core.types import Order

    order = exchange.submit(
        Order(
            id=1, symbol="BTCUSDT", side=Side.SELL, type=OrderType.LIMIT,
            qty=0.001, submitted_ns=0, limit_price=5000.2,
        )
    )
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.ts_ns == 300 * MS  # 5000.3 > 5000.2
    assert events[0].fill.price == pytest.approx(5000.2)


def test_post_only_rejected_when_crossing() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(5000.0, post_only=True))
    exchange.advance_to(200 * MS)
    # reference price 5000.0 <= limit: a buy at 5000.0 would cross immediately
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason is not None
    assert "post-only" in order.reject_reason


def test_post_only_accepted_when_resting_below() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(4999.5, qty=0.002, post_only=True))
    exchange.advance_to(200 * MS)
    assert order.status == OrderStatus.ACTIVE


def test_cancel_before_scheduled_fill_cancels() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(5000.0))
    # order active at 100ms; fill scheduled at 200ms; cancel at 50ms arrives at 150ms < 200ms
    exchange.cancel(1, now_ns=50 * MS)
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.CANCELED
    assert events == []


def test_cancel_late_does_not_prevent_fill() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(5000.0))
    # world at 150ms (order active since 100ms); cancel sent at 150ms arrives at
    # 250ms, after the fill scheduled at 200ms: the fill wins, like reality.
    exchange.advance_to(150 * MS)
    exchange.cancel(1, now_ns=150 * MS)
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    assert len(events) == 1


def test_invalid_fill_mode_rejected() -> None:
    with pytest.raises(ValueError, match="mode"):
        make_exchange(mode="optimiste")
