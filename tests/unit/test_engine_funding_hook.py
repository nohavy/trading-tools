"""Tests for the on_funding strategy hook (deliveries in order, before bars)."""

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
from tradingv2.portfolio.spot import SpotAccount
from tradingv2.strategy.base import Context, Strategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def make_bars(n: int = 10) -> list[PriceBar]:
    return [
        PriceBar(
            ts_open_ns=i * S, open=5000.0, high=5000.4, low=4999.6,
            close=5000.0, ts_close_ns=(i + 1) * S, volume=10.0,
        )
        for i in range(n)
    ]


def make_engine(account, strategy: Strategy) -> Engine:
    exchange = SimulatedExchange(
        rules=RULES,
        account=account,
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    return Engine(exchange=exchange, strategy=strategy, bars=make_bars())


class FundingProbe(Strategy):
    def __init__(self) -> None:
        self.seen: list[tuple[int, float]] = []
        self.order: list[str] = []

    def on_funding(self, ctx: Context, rate: float) -> None:  # noqa: B027
        self.seen.append((ctx.now_ns, rate))
        self.order.append(f"funding@{ctx.now_ns // S}s")

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:  # noqa: B027
        del ctx
        if bar.ts_close_ns == 3 * S:
            self.order.append(f"bar@{bar.ts_close_ns // S}s")


FUNDING = [
    FundingEvent(ts_ns=3 * S, rate=0.0001),
    FundingEvent(ts_ns=6 * S, rate=-0.0002),
]


def test_strategy_receives_exact_rates_in_order() -> None:
    probe = FundingProbe()
    account = MarginAccount(balance=10_000.0, leverage=5)
    engine = make_engine(account, probe)
    engine.run(funding_events=FUNDING)
    assert probe.seen == [(3 * S, 0.0001), (6 * S, -0.0002)]
    # accounting still applied: +0.0001*5000*0 position = 0 (flat) → balance unchanged
    assert account.position == pytest.approx(0.0)
    assert account.balance == pytest.approx(10_000.0)


def test_funding_hook_fires_before_bar_at_same_ts() -> None:
    probe = FundingProbe()
    engine = make_engine(MarginAccount(balance=10_000.0, leverage=5), probe)
    engine.run(funding_events=[FundingEvent(ts_ns=3 * S, rate=0.0001)])
    # the funding at 3s is delivered BEFORE the bar closing at 3s
    assert probe.order == ["funding@3s", "bar@3s"]


def test_funding_accounting_applied_on_open_position() -> None:
    class HoldLong(FundingProbe):
        def __init__(self) -> None:
            super().__init__()
            self.position_taken: bool = False

        def on_bar(self, ctx: Context, bar: PriceBar) -> None:  # noqa: B027
            if bar.ts_close_ns == 1 * S and not self.position_taken:
                ctx.submit_market(Side.BUY, qty=0.002)
                self.position_taken = True

    probe = HoldLong()
    account = MarginAccount(balance=10_000.0, leverage=5)
    engine = make_engine(account, probe)
    engine.run(funding_events=[FundingEvent(ts_ns=6 * S, rate=0.0001)])
    # funding on the open long: 0.0001 * 5000 * 0.002 = 0.001 paid
    assert account.balance == pytest.approx(10_000.0 - 0.001)


def test_spot_account_receives_hook_without_accounting() -> None:
    probe = FundingProbe()
    account = SpotAccount(quote_balance=10_000.0)
    engine = make_engine(account, probe)
    engine.run(funding_events=FUNDING)
    assert probe.seen == [(3 * S, 0.0001), (6 * S, -0.0002)]
    assert account.quote_balance == pytest.approx(10_000.0)
