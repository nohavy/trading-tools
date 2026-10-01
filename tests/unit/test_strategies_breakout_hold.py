"""Tests for the fixed-hold breakout strategy (faithful scan reproduction)."""

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
from tradingv2.strategies.breakout_hold import BreakoutFixedHold

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def craft(closes: list[float], volumes: list[float]) -> list[PriceBar]:
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


def run(closes: list[float], volumes: list[float], strategy: BreakoutFixedHold) -> EngineResult:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    engine = Engine(exchange=exchange, strategy=strategy, bars=craft(closes, volumes))
    return engine.run()


def test_enters_on_breakout_and_exits_after_exact_hold() -> None:
    closes = [5000.0, 5000.0, 5000.0, 5005.0, 5006.0, 5007.0, 5008.0, 5009.0]
    volumes = [10.0, 10.0, 10.0, 200.0, 10.0, 10.0, 10.0, 10.0]
    strategy = BreakoutFixedHold(lookback=3, volume_factor=2.0, hold_bars=2, qty=0.002)
    result = run(closes, volumes, strategy)
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert len(buys) == 1 and len(sells) == 1
    trips = result.round_trips
    assert len(trips) == 1
    # entry fill at bar4 close (5s), exit fill at bar6 close (7s): hold = 2 bars
    assert trips[0].hold_ns == pytest.approx(2 * S)
    assert trips[0].entry_price == pytest.approx(5005.0)  # bar4 open
    assert trips[0].exit_price == pytest.approx(5007.0)  # bar6 open
    assert trips[0].side == "buy"


def test_reenters_after_exit_on_new_breakout() -> None:
    closes = [
        5000.0, 5000.0, 5000.0,  # warmup
        5005.0,  # breakout 1 (vol spike)
        5006.0, 5007.0, 5008.0,  # hold + exit
        5001.0,  # back inside
        5010.0,  # breakout 2 (vol spike)
        5011.0, 5012.0, 5013.0, 5014.0,  # hold + exit
    ]
    volumes = [10.0] * 13
    volumes[3] = 200.0
    volumes[8] = 200.0
    strategy = BreakoutFixedHold(lookback=3, volume_factor=2.0, hold_bars=2, qty=0.002)
    result = run(closes, volumes, strategy)
    trips = result.round_trips
    assert len(trips) == 2
    assert all(t.side == "buy" for t in trips)


def test_no_pyramiding_while_holding() -> None:
    closes = [5000.0, 5000.0, 5000.0, 5005.0, 5006.0, 5007.0, 5008.0, 5009.0]
    volumes = [10.0, 10.0, 10.0, 200.0, 200.0, 200.0, 200.0, 200.0]
    strategy = BreakoutFixedHold(lookback=3, volume_factor=2.0, hold_bars=5, qty=0.002)
    result = run(closes, volumes, strategy)
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert len(buys) == 1


def test_short_symmetric() -> None:
    # big drop after the break: gross (2 pts x 0.002 = 0.004... make it larger)
    closes = [5010.0, 5010.0, 5010.0, 5004.0, 4990.0, 4988.0, 4986.0, 4984.0]
    volumes = [10.0, 10.0, 10.0, 200.0, 10.0, 10.0, 10.0, 10.0]
    strategy = BreakoutFixedHold(lookback=3, volume_factor=2.0, hold_bars=2, qty=0.002)
    result = run(closes, volumes, strategy)
    trips = result.round_trips
    assert len(trips) == 1
    assert trips[0].side == "sell"
    assert trips[0].entry_price == pytest.approx(5004.0)
    assert trips[0].exit_price == pytest.approx(4988.0)
    assert trips[0].net > 0  # (5004-4988) x 0.002 = 0.032 gross > fees


def test_warmup_no_entry_before_lookback() -> None:
    closes = [5000.0, 5005.0]  # breakout on bar 1 but lookback 3 not filled
    volumes = [200.0, 200.0]
    strategy = BreakoutFixedHold(lookback=3, volume_factor=2.0, hold_bars=2, qty=0.002)
    result = run(closes, volumes, strategy)
    assert result.fill_events == []


def test_registered_in_registry() -> None:
    from tradingv2.strategies.builtin import build_strategy

    strategy = build_strategy("breakout_hold", {"lookback": 10, "hold_bars": 3})
    assert isinstance(strategy, BreakoutFixedHold)


def test_buy_only_direction_skips_sell_breaks() -> None:
    # down-break with volume: no short when direction="buy"
    closes = [5010.0, 5010.0, 5010.0, 5004.0, 5003.0, 5002.0, 5001.0, 5000.0]
    volumes = [10.0, 10.0, 10.0, 200.0, 10.0, 10.0, 10.0, 10.0]
    strategy = BreakoutFixedHold(
        lookback=3, volume_factor=2.0, hold_bars=2, qty=0.002, direction="buy"
    )
    result = run(closes, volumes, strategy)
    assert result.fill_events == []


def test_sell_only_direction_skips_buy_breaks() -> None:
    closes = [5000.0, 5000.0, 5000.0, 5005.0, 5006.0, 5007.0, 5008.0, 5009.0]
    volumes = [10.0, 10.0, 10.0, 200.0, 10.0, 10.0, 10.0, 10.0]
    strategy = BreakoutFixedHold(
        lookback=3, volume_factor=2.0, hold_bars=2, qty=0.002, direction="sell"
    )
    result = run(closes, volumes, strategy)
    assert result.fill_events == []


def test_invalid_direction_rejected() -> None:
    with pytest.raises(ValueError, match="direction"):
        BreakoutFixedHold(lookback=3, volume_factor=2.0, hold_bars=2, direction="both_ways")
