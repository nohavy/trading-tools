"""Tests for clean margin rejection: no corruption, no illegal transitions."""

import polars as pl
import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import Fill, FillRole, Order, OrderStatus, OrderType, PriceBar, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.portfolio.spot import AccountError
from tradingv2.strategy.base import Context, Strategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


class BurstStrategy(Strategy):
    """Opens a big position on an adverse move: the margin check must fire
    DURING the run without corrupting the account or crashing the engine."""

    def __init__(self, qty: float) -> None:
        self._qty = qty
        self._bars = 0

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        self._bars += 1
        if self._bars == 1:
            ctx.submit_market(Side.BUY, qty=self._qty)


def test_margin_rejection_mid_run_is_clean(tmp_path_filler: None = None) -> None:
    bars = [
        PriceBar(
            ts_open_ns=i * S,
            open=5000.0,
            high=5000.4,
            low=4999.6,
            close=5000.0,
            ts_close_ns=(i + 1) * S,
            volume=10.0,
        )
        for i in range(5)
    ]
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=100.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    # 0.2 * 5000 = 1000 notional; margin used 200 > equity 100 -> must reject
    strategy = BurstStrategy(qty=0.2)
    engine = Engine(exchange=exchange, strategy=strategy, bars=bars)
    result = engine.run()  # must NOT raise
    rejected = [o for o in result.orders if o.status == OrderStatus.REJECTED]
    assert rejected, "the oversized order must be rejected at fill time"
    # the account is uncorrupted: no position, balance untouched by the rejected fill
    account = exchange.account
    assert account.position == pytest.approx(0.0)  # type: ignore[attr-defined]
    assert account.balance == pytest.approx(100.0)  # type: ignore[attr-defined]


def test_margin_check_happens_before_mutation() -> None:
    account = MarginAccount(balance=100.0, leverage=5)
    from tradingv2.core.types import Fill, FillRole

    fill = Fill(
        order_id=1, ts_ns=0, price=5000.0, qty=0.5, fee=0.0, role=FillRole.TAKER, side=Side.BUY
    )
    with pytest.raises(AccountError):
        account.apply_fill(fill)  # 0.5*5000/5 = 500 > 100
    # no partial mutation: balance and position untouched
    assert account.balance == pytest.approx(100.0)
    assert account.position == pytest.approx(0.0)


def test_closing_a_position_below_initial_margin_is_allowed() -> None:
    """An exit releases margin and must not be rejected as a new full-size trade."""
    account = MarginAccount(balance=10_000.0, leverage=1)
    entry = Fill(
        order_id=1,
        ts_ns=0,
        price=10_000.0,
        qty=1.0,
        fee=5.0,
        role=FillRole.TAKER,
        side=Side.BUY,
    )
    account.apply_fill(entry)
    assert account.equity(9_000.0) == pytest.approx(8_995.0)

    tape = pl.DataFrame(
        {
            "ts_ns": [S],
            "price": [9_000.0],
            "qty": [2.0],
            "buyer_is_maker": [True],
        }
    )
    exchange = SimulatedExchange(
        rules=RULES,
        account=account,
        fees=FeeSchedule(maker_bps=2.0, taker_bps=5.0),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=0.0, jitter_ms=0.0, seed=1),
        tape=tape,
    )
    exit_order = Order(
        id=1,
        symbol="BTCUSDT",
        side=Side.SELL,
        type=OrderType.MARKET,
        qty=1.0,
        submitted_ns=0,
    )
    exchange.submit(exit_order)
    exchange.advance_to(0)
    assert exit_order.status.value == OrderStatus.ACTIVE.value
    fills = exchange.advance_to(S)
    assert len(fills) == 1
    assert exit_order.status.value == OrderStatus.FILLED.value
    assert account.position == pytest.approx(0.0)
