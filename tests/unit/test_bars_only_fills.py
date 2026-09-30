"""Tests for bars-only fill mode (no trade tape): OHLC-based conservative fills."""

import pytest

from tradingv2.config import Market
from tradingv2.core.types import FillRole, Order, OrderStatus, OrderType, PriceBar, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)

# five 1s bars; bar i opens at i*s and closes at (i+1)*s
BARS = [
    PriceBar(ts_open_ns=0, open=5000.0, high=5000.5, low=4999.8, close=5000.2, ts_close_ns=1 * S),
    PriceBar(
        ts_open_ns=1 * S, open=5000.2, high=5001.0, low=5000.0, close=5000.8, ts_close_ns=2 * S
    ),
    PriceBar(
        ts_open_ns=2 * S, open=5000.8, high=5001.2, low=5000.6, close=5001.0, ts_close_ns=3 * S
    ),
    PriceBar(
        ts_open_ns=3 * S, open=5001.0, high=5001.5, low=5000.9, close=5001.2, ts_close_ns=4 * S
    ),
    PriceBar(
        ts_open_ns=4 * S, open=5001.2, high=5001.6, low=5001.0, close=5001.4, ts_close_ns=5 * S
    ),
]

SLIP = SlippageModel(bps=0.5)


def make_exchange(mode: str = "pessimistic") -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=1_000_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SLIP,
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
        limit_fill_mode=mode,
    )


def make_order(**overrides: object) -> Order:
    kwargs: dict[str, object] = {
        "id": 1,
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "type": OrderType.MARKET,
        "qty": 0.002,
        "submitted_ns": 0,
    }
    kwargs.update(overrides)
    return Order(**kwargs)  # type: ignore[arg-type]


def test_market_fills_at_window_open_with_slippage() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order())
    events = exchange.on_bar_close(BARS[0])
    assert order.status == OrderStatus.FILLED
    # arrived at 150ms inside bar0's window: fills at bar0 open + 0.5 bps
    assert events[0].fill.price == pytest.approx(5000.0 * (1 + 0.5 / 10_000))
    assert events[0].fill.ts_ns == 1 * S
    assert events[0].fill.role == FillRole.TAKER
    assert events[0].slippage_cost == pytest.approx(5000.0 * 0.5 / 10_000 * 0.002)


def test_market_fills_at_next_window_after_decision_close() -> None:
    exchange = make_exchange()
    exchange.on_bar_close(BARS[0])  # bar0 closed: first decisions happen here
    order = exchange.submit(make_order(submitted_ns=1 * S))
    events = exchange.on_bar_close(BARS[1])
    assert order.status == OrderStatus.FILLED
    # arrived at 1.15s inside bar1's window: fills at bar1 open + slippage
    assert events[0].fill.price == pytest.approx(5000.2 * (1 + 0.5 / 10_000))
    assert events[0].fill.ts_ns == 2 * S


def test_limit_pessimistic_touch_only_rests() -> None:
    exchange = make_exchange()
    order = exchange.submit(
        make_order(type=OrderType.LIMIT, limit_price=4999.8)
    )
    for bar in BARS:
        exchange.on_bar_close(bar)  # lows: 4999.8, 5000.0... never strictly below
    assert order.status == OrderStatus.ACTIVE


def test_limit_optimistic_touch_fills() -> None:
    exchange = make_exchange(mode="optimistic")
    order = exchange.submit(make_order(type=OrderType.LIMIT, limit_price=4999.8))
    events = exchange.on_bar_close(BARS[0])
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.price == pytest.approx(4999.8)
    assert events[0].fill.role == FillRole.MAKER
    assert events[0].fill.ts_ns == 1 * S


def test_limit_through_fills_at_limit_maker() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order(type=OrderType.LIMIT, limit_price=5000.7))
    events = exchange.on_bar_close(BARS[0])  # bar0 low 4999.8 < 5000.7: through
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.price == pytest.approx(5000.7)
    assert events[0].fill.role == FillRole.MAKER


def test_stop_triggers_at_stop_plus_slippage() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order(type=OrderType.STOP_MARKET, stop_price=5000.4))
    events = exchange.on_bar_close(BARS[0])  # bar0 high 5000.5 >= 5000.4
    assert order.status == OrderStatus.FILLED
    # no gap (open 5000.0 < stop): filled at stop + slippage
    assert events[0].fill.price == pytest.approx(5000.4 * (1 + 0.5 / 10_000))
    assert events[0].fill.role == FillRole.TAKER


def test_stop_gap_open_fills_at_open() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order(type=OrderType.STOP_MARKET, stop_price=4999.5))
    events = exchange.on_bar_close(BARS[0])  # open 5000.0 above stop: gap
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.price == pytest.approx(5000.0 * (1 + 0.5 / 10_000))


def test_order_arriving_after_close_not_evaluated_on_that_bar() -> None:
    exchange = make_exchange()
    exchange.on_bar_close(BARS[0])
    order = exchange.submit(
        make_order(type=OrderType.LIMIT, submitted_ns=1 * S, limit_price=5000.9)
    )
    # bar0 low 4999.8 < 5000.9 but the order arrives at 1.15s, after bar0 closed
    assert exchange.on_bar_close(BARS[0]) == []  # re-closing bar0: not evaluated
    events = exchange.on_bar_close(BARS[1])  # bar1 low 5000.0 < 5000.9: fills
    assert order.status == OrderStatus.FILLED
    assert events[0].fill.ts_ns == 2 * S
