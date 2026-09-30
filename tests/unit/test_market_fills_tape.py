"""Tests for market order fills against the trade tape (side-aware, VWAP)."""

import polars as pl
import pytest

from tradingv2.core.types import FillRole, OrderStatus, OrderType, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount

MS = 1_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market="um", tick_size=0.1, step_size=0.001, min_notional=5.0
)

# aggressor-buy trades (buyer_is_maker False): ts 100, 300, 400
# aggressor-sell trades (buyer_is_maker True): ts 200, 500
TAPE = pl.DataFrame(
    {
        "ts_ns": [100 * MS, 200 * MS, 300 * MS, 400 * MS, 500 * MS],
        "price": [5000.0, 5000.1, 5000.2, 5000.3, 5000.4],
        "qty": [1.0, 2.0, 1.5, 3.0, 1.0],
        "buyer_is_maker": [False, True, False, False, True],
    }
)


def make_exchange(account: MarginAccount | None = None) -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=account or MarginAccount(balance=1_000_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=100, jitter_ms=0, seed=1),
        tape=TAPE,
    )


def make_order(**overrides: object) -> object:
    from tradingv2.core.types import Order

    kwargs: dict[str, object] = {
        "id": 1,
        "symbol": "BTCUSDT",
        "side": Side.BUY,
        "type": OrderType.MARKET,
        "qty": 0.5,
        "submitted_ns": 0,
    }
    kwargs.update(overrides)
    return Order(**kwargs)  # type: ignore[arg-type]


def test_buy_fills_at_first_aggressor_trade() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order())
    events = exchange.advance_to(200 * MS)
    assert order.status == OrderStatus.FILLED
    assert len(events) == 1
    fill = events[0].fill
    assert fill.price == pytest.approx(5000.0)
    assert fill.qty == pytest.approx(0.5)
    assert fill.role == FillRole.TAKER
    assert fill.ts_ns == 100 * MS
    assert fill.fee == pytest.approx(0.5 * 5000.0 * 5 / 10_000)


def test_buy_vwap_across_aggressor_trades() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order(qty=2.5))
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    # consumes trades at 100ms (1.0 @ 5000.0) and 300ms (1.5 @ 5000.2)
    fill = events[0].fill
    vwap = (1.0 * 5000.0 + 1.5 * 5000.2) / 2.5
    assert fill.price == pytest.approx(vwap)
    assert fill.ts_ns == 300 * MS  # last consumed trade
    assert fill.qty == pytest.approx(2.5)


def test_sell_fills_from_buyer_maker_trades() -> None:
    exchange = make_exchange()
    order = exchange.submit(make_order(side=Side.SELL, qty=3.0))
    events = exchange.advance_to(1_000 * MS)
    assert order.status == OrderStatus.FILLED
    # consumes maker-buy trades at 200ms (2.0 @ 5000.1) and 500ms (1.0 @ 5000.4)
    vwap = (2.0 * 5000.1 + 1.0 * 5000.4) / 3.0
    assert events[0].fill.price == pytest.approx(vwap)
    assert events[0].fill.ts_ns == 500 * MS


def test_market_fill_applied_to_account() -> None:
    account = MarginAccount(balance=1_000_000.0, leverage=5)
    exchange = make_exchange(account=account)
    exchange.submit(make_order(qty=0.5))
    exchange.advance_to(200 * MS)
    assert account.position == pytest.approx(0.5)
    assert account.balance == pytest.approx(1_000_000.0 - 0.5 * 5000.0 * 5 / 10_000)


def test_slippage_vs_reference_recorded() -> None:
    exchange = make_exchange()
    exchange.submit(make_order(qty=0.5))
    events = exchange.advance_to(200 * MS)
    # reference = last trade price before arrival (100ms): no earlier trade -> tape start
    # here tape starts at 100ms itself; reference = 5000.0 -> slippage 0
    assert events[0].slippage_cost == pytest.approx(0.0)


def test_order_rests_without_aggressor_trades() -> None:
    empty_tape = pl.DataFrame(
        {
            "ts_ns": [100 * MS],
            "price": [5000.0],
            "qty": [1.0],
            "buyer_is_maker": [True],  # only maker-buy trades: no aggressor for buys
        }
    )
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=1_000_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=100, jitter_ms=0, seed=1),
        tape=empty_tape,
    )
    order = exchange.submit(make_order(qty=0.5))
    assert exchange.advance_to(500 * MS) == []
    assert order.status == OrderStatus.ACTIVE
