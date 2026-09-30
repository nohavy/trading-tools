"""Tests for bracket double-fire: stop and pending exit must not both fire."""

import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import PriceBar, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import FillEvent, SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategy.base import Context, Strategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def _bars_for_test(n: int = 5) -> list[PriceBar]:
    """Flat bars; from bar 2 the low reaches 4998 (below the stop 4999)."""
    bars: list[PriceBar] = []
    for i in range(n):
        low = 4999.6 if i < 2 else 4998.0
        bars.append(
            PriceBar(
                ts_open_ns=i * S,
                open=5000.0,
                high=5000.4,
                low=low,
                close=5000.0,
                ts_close_ns=(i + 1) * S,
                volume=10.0,
            )
        )
    return bars


def make_engine(strategy: Strategy, bars: list[PriceBar]) -> Engine:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    return Engine(exchange=exchange, strategy=strategy, bars=bars)


class BracketStrategy(Strategy):
    """Entry at bar0; at bar1 (position open): stop + exit market both armed.

    The stop triggers at bar2's close (low <= stop). The exit market, still
    pending, must be canceled by the on_fill guard — never double-fire.
    """

    def __init__(self) -> None:
        self._bars = 0
        self._armed = False
        self._stop_id: int | None = None
        self._exit_id: int | None = None

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        self._bars += 1
        if self._bars == 1:
            ctx.submit_market(Side.BUY, qty=0.002)
        elif self._bars == 2 and not self._armed:
            self._armed = True
            self._stop_id = ctx.submit_stop(Side.SELL, qty=0.002, stop_price=4999.0)
            self._exit_id = ctx.submit_market(Side.SELL, qty=0.002)

    def on_fill(self, ctx: Context, event: FillEvent) -> None:
        if ctx.exchange.position_qty == 0.0 and self._exit_id is not None:
            ctx.cancel(self._exit_id)
            self._exit_id = None
        if ctx.exchange.position_qty == 0.0 and self._armed:
            self._armed = False
            self._stop_id = None


def test_bracket_does_not_double_fire() -> None:
    engine = make_engine(BracketStrategy(), _bars_for_test())
    result = engine.run()
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert len(sells) == 1, f"expected exactly one sell (the stop), got {len(sells)}"
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert len(buys) == 1
    # final position flat: no flip from a double sell
    assert engine.exchange.position_qty == pytest.approx(0.0)


def test_meanrev_bracket_stop_wins_over_pending_exit() -> None:
    """Stop fires at bar5 close while the exit market (submitted at bar4) is
    still pending: the guard cancels it — no involuntary flip."""
    from tradingv2.strategies.meanrev import MeanRevZScore

    closes = [5000.0, 5000.0, 4990.0, 4991.0, 4994.0, 4990.0, 4990.0]
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002, stop_bps=5.0)
    engine = make_engine(strategy, _bars_with_violent_low(closes, drop_index=5))
    result = engine.run()
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    # exactly one sell: either the stop or the exit, never both
    assert len(sells) == 1, f"got {len(sells)} sells: {[s.price for s in sells]}"
    assert engine.exchange.position_qty == pytest.approx(0.0)


def _bars_with_violent_low(closes: list[float], drop_index: int) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i > 0 else close
        low = open_ - 10.0 if i == drop_index else min(open_, close) - 0.5
        bars.append(
            PriceBar(
                ts_open_ns=i * S,
                open=open_,
                high=max(open_, close) + 0.5,
                low=low,
                close=close,
                ts_close_ns=(i + 1) * S,
                volume=10.0,
            )
        )
    return bars
