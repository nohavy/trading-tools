"""Tests for the order-flow imbalance strategy."""

import pytest

from tradingv2.backtest.engine import Engine, EngineResult
from tradingv2.config import Market
from tradingv2.core.types import PriceBar, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategies.flow import OrderFlowImbalance

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def craft_bars(volumes: list[float], taker_buy: list[float]) -> list[PriceBar]:
    closes = [5000.0 + 0.1 * i for i in range(len(volumes))]
    bars: list[PriceBar] = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i > 0 else close
        bars.append(
            PriceBar(
                ts_open_ns=i * S,
                open=open_,
                high=max(open_, close) + 0.1,
                low=min(open_, close) - 0.1,
                close=close,
                ts_close_ns=(i + 1) * S,
                volume=volumes[i],
                taker_buy_volume=taker_buy[i],
            )
        )
    return bars


def run(
    volumes: list[float], taker_buy: list[float], strategy: OrderFlowImbalance
) -> EngineResult:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    engine = Engine(exchange=exchange, strategy=strategy, bars=craft_bars(volumes, taker_buy))
    return engine.run()


def test_enters_long_on_strong_buy_flow() -> None:
    # window 3: all-buy volume -> imbalance +1 >= 0.6
    volumes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    taker_buy = [10.0, 10.0, 10.0, 10.0, 5.0, 2.0, 1.0, 1.0]
    strategy = OrderFlowImbalance(window=3, threshold=0.6, qty=0.002)
    result = run(volumes, taker_buy, strategy)
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert buys
    assert buys[0].price == pytest.approx(5000.2)  # fills at bar3 open


def test_exits_when_flow_turns_against() -> None:
    volumes = [10.0] * 8
    taker_buy = [10.0, 10.0, 10.0, 10.0, 5.0, 2.0, 1.0, 1.0]
    strategy = OrderFlowImbalance(window=3, threshold=0.6, qty=0.002)
    result = run(volumes, taker_buy, strategy)
    trips = result.round_trips
    assert len(trips) == 1
    assert trips[0].side == "buy"
    # exit signal at bar6 close, fills at bar7 open
    assert trips[0].exit_price == pytest.approx(5000.6)


def test_enters_short_on_strong_sell_flow() -> None:
    volumes = [10.0] * 8
    taker_buy = [0.0, 0.0, 0.0, 0.0, 5.0, 8.0, 9.0, 9.0]
    strategy = OrderFlowImbalance(window=3, threshold=0.6, qty=0.002)
    result = run(volumes, taker_buy, strategy)
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert sells
    trips = result.round_trips
    assert trips and trips[0].side == "sell"


def test_no_entry_below_threshold() -> None:
    volumes = [10.0] * 6
    taker_buy = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0]  # imbalance 0 < 0.6
    strategy = OrderFlowImbalance(window=3, threshold=0.6, qty=0.002)
    result = run(volumes, taker_buy, strategy)
    assert result.fill_events == []


def test_max_hold_forces_exit() -> None:
    volumes = [10.0] * 10
    taker_buy = [10.0] * 10  # flow stays +1: exit only via max_hold
    strategy = OrderFlowImbalance(window=3, threshold=0.6, qty=0.002, max_hold_bars=4)
    result = run(volumes, taker_buy, strategy)
    trips = result.round_trips
    assert len(trips) == 1
    # entered at bar3 fill, forced exit 4 bars later
    assert trips[0].hold_ns == pytest.approx(4 * S)
