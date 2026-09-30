"""Tests for the mean-reversion strategy (entry/exit/stop/max-hold rules)."""

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
from tradingv2.strategies.meanrev import MeanRevZScore

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def craft_bars(closes: list[float], extra_low_drop: int | None = None) -> list[PriceBar]:
    """Deterministic bars: open = previous close, low/high tight around close.

    extra_low_drop: index whose bar gets a violently low low (stop trigger).
    """
    bars: list[PriceBar] = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i > 0 else close
        low = open_ - 10.0 if i == extra_low_drop else min(open_, close) - 0.5
        high = max(open_, close) + 0.5
        bars.append(
            PriceBar(
                ts_open_ns=i * S,
                open=open_,
                high=high,
                low=low,
                close=close,
                ts_close_ns=(i + 1) * S,
            )
        )
    return bars


def run(
    closes: list[float], strategy: MeanRevZScore, extra_low_drop: int | None = None
) -> EngineResult:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    engine = Engine(exchange=exchange, strategy=strategy, bars=craft_bars(closes, extra_low_drop))
    return engine.run()


# closes: flat, flat, deep dip (z = -1.41 at index 2 with window 3)
DIP_CLOSES = [5000.0, 5000.0, 4990.0, 4991.0, 4994.0, 4994.0, 4994.0]


def test_enters_long_on_extreme_low_z() -> None:
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002)
    result = run(DIP_CLOSES, strategy)
    buy_fills = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert len(buy_fills) >= 1
    # the first buy fills at the open of the bar after the dip bar (4990)
    assert buy_fills[0].price == pytest.approx(4990.0)


def test_exits_when_z_returns_to_exit_threshold() -> None:
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002)
    result = run(DIP_CLOSES, strategy)
    trips = result.round_trips
    assert len(trips) == 1
    assert trips[0].side == "buy"
    # entered at 4990, exited above (mean reversion captured)
    assert trips[0].exit_price > trips[0].entry_price
    # the round trip closed: the engine accounted for it in the ledger
    assert result.ledger_totals is not None


def test_stop_triggers_on_violent_adverse_move() -> None:
    # entry fills at bar3 open (4990); the stop (4987.5) is placed at bar3 close;
    # bar4 gets a violent low (4981 < stop): triggered before any normal exit.
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002, stop_bps=5.0)
    result = run(DIP_CLOSES + [4990.0, 4990.0], strategy, extra_low_drop=4)
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert sells, "the stop must have closed the position"
    # the stop fill is a taker fill at the stop level (5 bps below entry close 4990)
    assert sells[0].price == pytest.approx(4990.0 * (1 - 5.0 / 10_000))
    trips = result.round_trips
    assert trips and trips[0].net < 0  # stopped out at a loss


def test_max_hold_forces_exit() -> None:
    closes = [5000.0, 5000.0, 4990.0] + [4990.5] * 8
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002, max_hold_bars=4)
    result = run(closes, strategy)
    trips = result.round_trips
    assert len(trips) == 1
    # forced exit after 4 bars: the round trip is closed (position flat at end)
    assert trips[0].entry_price == pytest.approx(4990.0)


def test_no_pyramiding_while_position_open() -> None:
    # z stays extreme while long: no second buy before the exit
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002, max_hold_bars=5)
    closes = [5000.0, 5000.0, 4990.0, 4989.0, 4988.0, 4987.0, 4990.0, 4994.0, 4994.0]
    result = run(closes, strategy)
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    assert len(buys) == 1


def test_shorts_on_extreme_high_z() -> None:
    spike = [5000.0, 5000.0, 5010.0, 5009.0, 5006.0, 5006.0, 5006.0]
    strategy = MeanRevZScore(window=3, entry_z=1.0, exit_z=0.2, qty=0.002)
    result = run(spike, strategy)
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert sells
    assert sells[0].price == pytest.approx(5010.0)
    trips = result.round_trips
    assert trips and trips[0].side == "sell"
    assert trips[0].exit_price < trips[0].entry_price  # short captured the reversion
