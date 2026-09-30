"""Tests for cancellation racing against predictive scheduled fills."""

import polars as pl
import pytest

from tradingv2.config import Market
from tradingv2.core.types import Fill, FillRole, Order, OrderStatus, OrderType, Side
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

TAPE = pl.DataFrame(
    {
        "ts_ns": [100 * MS, 200 * MS, 300 * MS, 400 * MS, 500 * MS],
        "price": [5000.0, 4999.9, 4999.8, 4999.7, 4999.6],
        "qty": [1.0, 1.0, 1.0, 1.0, 1.0],
        "buyer_is_maker": [False, False, False, False, False],
    }
)


def make_exchange(jitter_ms: float = 0, seed: int = 1) -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=1_000_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=100, jitter_ms=jitter_ms, seed=seed),
        tape=TAPE,
    )


def make_buy_limit(price: float, id: int = 1, submitted_ns: int = 0) -> Order:
    return Order(
        id=id, symbol="BTCUSDT", side=Side.BUY, type=OrderType.LIMIT,
        qty=0.002, submitted_ns=submitted_ns, limit_price=price,
    )


def test_cancel_arriving_before_fill_prevents_it() -> None:
    exchange = make_exchange()
    exchange.submit(make_buy_limit(5000.0))
    exchange.advance_to(100 * MS)  # order active; fill scheduled at 200ms
    # cancel at 100ms with zero jitter arrives at 200ms; tie: fill survives.
    # Send one full window earlier instead:
    exchange2 = make_exchange()
    order2 = exchange2.submit(make_buy_limit(5000.0))
    exchange2.advance_to(100 * MS)
    exchange2.cancel(order2.id, now_ns=50 * MS)  # arrives at 150ms < 200ms
    events = exchange2.advance_to(1_000 * MS)
    assert order2.status == OrderStatus.CANCELED
    assert events == []


def test_fill_already_happened_reports_via_onfill_path() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(5000.0))
    events = exchange.advance_to(300 * MS)  # fill executed at 200ms
    assert order.status == OrderStatus.FILLED
    assert len(events) == 1
    # canceling a filled order is a no-op at exchange level (idempotent)
    exchange.cancel(order.id, now_ns=300 * MS)
    assert order.status == OrderStatus.FILLED


def test_tie_goes_to_fill() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_buy_limit(5000.0))
    exchange.advance_to(100 * MS)  # active; fill scheduled at 200ms
    # cancel now with zero latency arrives exactly at 200ms == fill time
    exchange.cancel(order.id, now_ns=100 * MS)
    events = exchange.advance_to(1_000 * MS)
    # at equal timestamps the fill wins (matches the plan's ordering: exchange first)
    assert order.status == OrderStatus.FILLED
    assert len(events) == 1


def test_second_order_scheduled_independently() -> None:
    exchange = make_exchange()
    first = exchange.submit(make_buy_limit(5000.0, id=1))
    second = exchange.submit(make_buy_limit(4999.9, id=2))
    exchange.advance_to(100 * MS)
    assert first.status == OrderStatus.ACTIVE
    assert second.status == OrderStatus.ACTIVE
    exchange.cancel(first.id, now_ns=50 * MS)
    events = exchange.advance_to(1_000 * MS)
    assert first.status == OrderStatus.CANCELED
    assert second.status == OrderStatus.FILLED
    assert len(events) == 1
    assert events[0].fill.price == pytest.approx(4999.9)


def test_fill_event_roles_and_costs() -> None:
    exchange = make_exchange()
    exchange.submit(make_buy_limit(4999.9, id=3, submitted_ns=0))
    events = exchange.advance_to(1_000 * MS)
    fill = events[0].fill
    assert fill.role == FillRole.MAKER
    assert fill.price == pytest.approx(4999.9)
    assert events[0].slippage_cost == 0.0
    assert isinstance(fill, Fill)
