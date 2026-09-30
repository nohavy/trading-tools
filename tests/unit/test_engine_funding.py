"""Tests for funding events and round-trip accounting inside the engine."""

import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import FundingEvent, PriceBar, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategy.base import Context, Strategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def make_bars(n: int, drift: float = 0.0) -> list[PriceBar]:
    return [
        PriceBar(
            ts_open_ns=i * S,
            open=5000.0 + drift * i,
            high=5000.5 + drift * i,
            low=4999.5 + drift * i,
            close=5000.0 + drift * (i + 0.5),
            ts_close_ns=(i + 1) * S,
        )
        for i in range(n)
    ]


def make_engine(
    strategy: Strategy, n_bars: int, balance: float = 10_000.0, drift: float = 0.0
) -> tuple[Engine, MarginAccount]:
    account = MarginAccount(balance=balance, leverage=5)
    exchange = SimulatedExchange(
        rules=RULES,
        account=account,
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    return Engine(exchange=exchange, strategy=strategy, bars=make_bars(n_bars, drift)), account


class OneTripStrategy(Strategy):
    """Buys at the first bar, sells at the second: exactly one round trip."""

    def __init__(self) -> None:
        self._bought = False
        self._sold = False

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        if not self._bought:
            ctx.submit_market(Side.BUY, qty=0.002)
            self._bought = True
        elif not self._sold:
            ctx.submit_market(Side.SELL, qty=0.002)
            self._sold = True


def test_round_trip_recorded_on_close() -> None:
    engine, _account = make_engine(OneTripStrategy(), n_bars=6, drift=0.1)
    result = engine.run()
    assert len(result.round_trips) == 1
    trip = result.round_trips[0]
    assert trip.side == "buy"
    assert trip.qty == pytest.approx(0.002)
    # entry filled at bar1 open (5000.1), exit at bar2 open (5000.2)
    assert trip.entry_price == pytest.approx(5000.1)
    assert trip.exit_price == pytest.approx(5000.2)
    assert trip.gross == pytest.approx(0.1 * 0.002)
    assert trip.fees > 0
    assert trip.net == pytest.approx(trip.gross - trip.fees - trip.slippage - trip.funding)
    assert result.ledger_totals is not None
    assert result.ledger_totals.n_trades == 1


def test_two_round_trips() -> None:
    class TwoTripsStrategy(Strategy):
        def __init__(self) -> None:
            self._count = 0

        def on_bar(self, ctx: Context, bar: PriceBar) -> None:
            del bar
            self._count += 1
            if self._count in (1, 3):
                ctx.submit_market(Side.BUY, qty=0.002)
            elif self._count in (2, 4):
                ctx.submit_market(Side.SELL, qty=0.002)

    engine, _ = make_engine(TwoTripsStrategy(), n_bars=8, drift=0.1)
    result = engine.run()
    assert len(result.round_trips) == 2


def test_funding_applied_and_tracked_during_position() -> None:
    class HoldStrategy(Strategy):
        """Buys at first bar, sells at the last: funding applies mid-hold."""

        def __init__(self, n_bars: int) -> None:
            self._n_bars = n_bars
            self._count = 0

        def on_bar(self, ctx: Context, bar: PriceBar) -> None:
            del bar
            self._count += 1
            if self._count == 1:
                ctx.submit_market(Side.BUY, qty=0.002)
            elif self._count == self._n_bars:
                ctx.submit_market(Side.SELL, qty=0.002)

    strategy = HoldStrategy(n_bars=6)
    engine, account = make_engine(strategy, n_bars=6)
    # funding at bar 3 close (position open since bar1 fill): rate 1 bp/day-equivalent
    funding = [FundingEvent(ts_ns=3 * S, rate=0.0001)]
    result = engine.run(funding_events=funding)
    assert len(result.round_trips) == 1
    trip = result.round_trips[0]
    # funding = rate * mark * position = 0.0001 * ~5000 * 0.002 ~ 0.001 (paid)
    assert trip.funding > 0
    assert account.balance < 10_000.0  # fees + funding paid
    assert trip.net == pytest.approx(trip.gross - trip.fees - trip.slippage - trip.funding)


def test_funding_before_position_not_in_trip() -> None:
    engine, _ = make_engine(OneTripStrategy(), n_bars=6)
    result = engine.run(funding_events=[FundingEvent(ts_ns=0, rate=0.0001)])
    # funding at ts 0: position not yet open (no mark price known) -> not tracked
    assert result.round_trips[0].funding == pytest.approx(0.0)


def test_funding_receiving_for_short() -> None:
    class ShortStrategy(Strategy):
        def __init__(self, n_bars: int) -> None:
            self._n_bars = n_bars
            self._count = 0

        def on_bar(self, ctx: Context, bar: PriceBar) -> None:
            del bar
            self._count += 1
            if self._count == 1:
                ctx.submit_market(Side.SELL, qty=0.002)
            elif self._count == self._n_bars:
                ctx.submit_market(Side.BUY, qty=0.002)

    engine, _ = make_engine(ShortStrategy(n_bars=6), n_bars=6)
    result = engine.run(funding_events=[FundingEvent(ts_ns=3 * S, rate=0.0001)])
    trip = result.round_trips[0]
    assert trip.side == "sell"
    assert trip.funding < 0  # shorts RECEIVE on positive rates
