"""Tests for the funding-momentum strategy (rolling percentile, hold, single position)."""

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
from tradingv2.strategies.funding import FundingMomentum
from tradingv2.strategy.base import Strategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def make_bars(n: int = 300) -> list[PriceBar]:
    return [
        PriceBar(
            ts_open_ns=i * S, open=5000.0, high=5000.4, low=4999.6,
            close=5000.0, ts_close_ns=(i + 1) * S, volume=10.0,
        )
        for i in range(n)
    ]


def make_engine(strategy: Strategy, account: MarginAccount | None = None) -> Engine:
    exchange = SimulatedExchange(
        rules=RULES,
        account=account or MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    return Engine(exchange=exchange, strategy=strategy, bars=make_bars())


def funding_at(seconds: list[int], rates: list[float]) -> list[FundingEvent]:
    return [FundingEvent(ts_ns=t * S, rate=r) for t, r in zip(seconds, rates, strict=True)]


def test_enters_when_rate_above_rolling_percentile() -> None:
    # 6 calm rates, then a spike far above the rolling p90
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=50, qty=0.002)
    rates = [0.0001] * 6 + [0.001]
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at(list(range(1, 8)), rates))
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert buys, "the spike above the rolling percentile must trigger an entry"
    # the entry fill lands at the bar close right after the spike settlement (7s)
    assert buys[0].ts_ns == 8 * S


def test_no_entry_before_enough_history() -> None:
    # the spike arrives as the 2nd settlement: history too short (min = window//2)
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=50, qty=0.002)
    rates = [0.0001, 0.001]
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at([1, 2], rates))
    assert result.fill_events == []


def test_exit_after_hold_bars() -> None:
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=30, qty=0.002)
    rates = [0.0001] * 6 + [0.001]
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at(list(range(1, 8)), rates))
    trips = result.round_trips
    assert len(trips) == 1
    # entered at 8s (fill), held 30 one-second bars, exit fills at the next close
    assert trips[0].hold_ns == pytest.approx(31 * S)
    assert engine.exchange.position_qty == pytest.approx(0.0)


def test_single_position_no_piling() -> None:
    # two spikes 10s apart while the position is held: only one buy
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=100, qty=0.002)
    rates = [0.0001] * 6 + [0.001, 0.0005, 0.001]
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at(list(range(1, 10)), rates))
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert len(buys) == 1


def test_constant_rates_never_enter() -> None:
    # a rate equal to the whole history exceeds nothing meaningful: no trade
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=30, qty=0.002)
    rates = [0.0001] * 12
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at(list(range(1, 13)), rates))
    assert result.fill_events == []


def test_negative_extreme_not_entered_buy_only() -> None:
    # v1 is buy-only: a very negative rate does not open a short
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=30, qty=0.002)
    rates = [0.0001] * 6 + [-0.005]
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at(list(range(1, 8)), rates))
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert sells == []


def test_nan_rates_ignored() -> None:
    strategy = FundingMomentum(window_events=10, threshold_pct=90, hold_bars=30, qty=0.002)
    rates = [0.0001] * 6 + [float("nan"), 0.001]
    engine = make_engine(strategy)
    result = engine.run(funding_events=funding_at(list(range(1, 9)), rates))
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert len(buys) == 1  # the NaN did not break anything; the spike still fires
