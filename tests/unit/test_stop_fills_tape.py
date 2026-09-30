"""Tests for stop-market order fills against the trade tape."""

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

TAPE = pl.DataFrame(
    {
        "ts_ns": [100 * MS, 200 * MS, 300 * MS, 400 * MS, 500 * MS],
        "price": [5000.0, 5000.4, 5001.0, 4999.5, 5000.2],
        "qty": [1.0, 1.0, 1.0, 1.0, 1.0],
        "buyer_is_maker": [False, False, True, False, False],
    }
)


def make_exchange() -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=1_000_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=100, jitter_ms=0, seed=1),
        tape=TAPE,
    )


def make_stop(side: Side, stop_price: float, qty: float = 0.001) -> Order:
    return Order(
        id=1, symbol="BTCUSDT", side=side, type=OrderType.STOP_MARKET,
        qty=qty, submitted_ns=0, stop_price=stop_price,
    )


def test_buy_stop_triggers_on_first_crossing() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_stop(Side.BUY, 5000.5))
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    fill = events[0].fill
    assert fill.ts_ns == 300 * MS  # first trade >= 5000.5 is 5001.0 at 300ms
    assert fill.price == pytest.approx(5001.0)
    assert fill.role == FillRole.TAKER
    assert fill.fee == pytest.approx(0.001 * 5001.0 * 5 / 10_000)


def test_sell_stop_triggers_below() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_stop(Side.SELL, 4999.7))
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.ts_ns == 400 * MS  # first trade <= 4999.7 is 4999.5 at 400ms
    assert events[0].fill.price == pytest.approx(4999.5)


def test_stop_rests_until_crossing() -> None:
    exchange = make_exchange()
    exchange.submit(make_stop(Side.BUY, 5000.5))
    assert exchange.advance_to(200 * MS) == []  # trades so far: 5000.0, 5000.4


def test_stop_fill_reaches_account() -> None:
    account = MarginAccount(balance=1_000_000.0, leverage=5)
    exchange = SimulatedExchange(
        rules=RULES,
        account=account,
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=100, jitter_ms=0, seed=1),
        tape=TAPE,
    )
    exchange.submit(make_stop(Side.BUY, 5000.5, qty=0.01))
    exchange.advance_to(1_000 * MS)
    assert account.position == pytest.approx(0.01)


def test_stop_slippage_recorded() -> None:
    exchange = make_exchange()
    exchange.submit(make_stop(Side.BUY, 5000.5))
    events = exchange.advance_to(1_000 * MS)
    # reference at arrival = 5000.0 (tape start); fill at 5001.0
    assert events[0].slippage_cost == pytest.approx((5001.0 - 5000.0) * 0.001)
