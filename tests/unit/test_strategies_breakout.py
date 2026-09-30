"""Tests for the breakout strategy (range break + volume confirmation)."""

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
from tradingv2.strategies.breakout import BreakoutVolume

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def craft_bars(closes: list[float], volumes: list[float]) -> list[PriceBar]:
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
            )
        )
    return bars


def run(closes: list[float], volumes: list[float], strategy: BreakoutVolume) -> EngineResult:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    engine = Engine(exchange=exchange, strategy=strategy, bars=craft_bars(closes, volumes))
    return engine.run()


# flat range 5000 x3, breakout to 5005 on 3x volume, then fall back in range
UP_BREAK = ([5000.0, 5000.0, 5000.0, 5005.0, 5001.0, 4999.0, 4999.0, 4999.0],
            [10.0, 10.0, 10.0, 30.0, 10.0, 10.0, 10.0, 10.0])


def test_breakout_long_with_volume_confirmation() -> None:
    closes, volumes = UP_BREAK
    strategy = BreakoutVolume(lookback=3, volume_factor=2.0, qty=0.002)
    result = run(closes, volumes, strategy)
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert buys, "breakout with volume must enter long"
    assert buys[0].price == pytest.approx(5005.0)  # fills at the next bar open
    # the entry bar is the 4th (index 3): only one entry
    assert len(buys) == 1


def test_no_entry_without_volume_confirmation() -> None:
    closes, _ = UP_BREAK
    volumes = [10.0, 10.0, 10.0, 15.0, 10.0, 10.0, 10.0, 10.0]  # 15 < 2*mean(10)
    strategy = BreakoutVolume(lookback=3, volume_factor=2.0, qty=0.002)
    result = run(closes, volumes, strategy)
    assert not [e.fill for e in result.fill_events if e.fill.side == Side.BUY]


def test_no_entry_without_break() -> None:
    closes = [5000.0] * 6
    volumes = [10.0] * 6
    strategy = BreakoutVolume(lookback=3, volume_factor=2.0, qty=0.002)
    result = run(closes, volumes, strategy)
    assert result.fill_events == []


def test_breakout_short_symmetric() -> None:
    closes = [5010.0, 5010.0, 5010.0, 5004.0, 5008.0, 5011.0, 5011.0, 5011.0]
    volumes = [10.0, 10.0, 10.0, 30.0, 10.0, 10.0, 10.0, 10.0]
    strategy = BreakoutVolume(lookback=3, volume_factor=2.0, qty=0.002)
    result = run(closes, volumes, strategy)
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert sells
    assert sells[0].price == pytest.approx(5004.0)
    trips = result.round_trips
    assert trips and trips[0].side == "sell"
    # exit when price re-enters the range (min_low was 5010): exit at 5011
    assert trips[0].exit_price == pytest.approx(5011.0)


def test_long_exit_when_price_returns_to_range() -> None:
    closes, volumes = UP_BREAK
    strategy = BreakoutVolume(lookback=3, volume_factor=2.0, qty=0.002)
    result = run(closes, volumes, strategy)
    trips = result.round_trips
    assert len(trips) == 1
    # entry range max_high = 5000.1: exit when close < 5000.1 -> at 4999 (bar 5)
    assert trips[0].exit_price == pytest.approx(4999.0)
    assert trips[0].side == "buy"
