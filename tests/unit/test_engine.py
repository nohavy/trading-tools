"""Tests for the backtest event engine: ordering, latency, lookback, end."""

import polars as pl
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

MS = 1_000_000
S = 1_000 * MS

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def make_exchange(tape: pl.DataFrame | None, latency_ms: float = 150) -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=latency_ms, jitter_ms=0, seed=1),
        tape=tape,
    )


def make_bars(n: int, interval_ns: int, start_open: float = 5000.0) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for i in range(n):
        o = start_open + i * 0.1
        bars.append(
            PriceBar(
                ts_open_ns=i * interval_ns,
                open=o,
                high=o + 0.5,
                low=o - 0.5,
                close=o + 0.2,
                ts_close_ns=(i + 1) * interval_ns,
            )
        )
    return bars


class OrderingStrategy(Strategy):
    """Submits a market order and a timer at 0.5s; records callback order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        self.calls.append(f"bar@{bar.ts_close_ns // MS}")
        if bar.ts_close_ns == 500 * MS:
            ctx.submit_market(Side.BUY, qty=0.002)
            ctx.set_timer(500 * MS)

    def on_fill(self, ctx: Context, event: FillEvent) -> None:
        self.calls.append(f"fill@{event.fill.ts_ns // MS}")

    def on_timer(self, ctx: Context) -> None:
        self.calls.append(f"timer@{ctx.now_ns // MS}")


def test_fill_before_bar_before_timer_at_same_ts() -> None:
    tape = pl.DataFrame(
        {
            "ts_ns": [1_000 * MS],
            "price": [5001.0],
            "qty": [1.0],
            "buyer_is_maker": [False],
        }
    )
    strategy = OrderingStrategy()
    engine = Engine(
        exchange=make_exchange(tape=tape, latency_ms=0),
        strategy=strategy,
        bars=make_bars(5, 500 * MS),
    )
    engine.run()
    assert "bar@500" in strategy.calls
    fill_idx = strategy.calls.index("fill@1000")
    bar_idx = strategy.calls.index("bar@1000")
    timer_idx = strategy.calls.index("timer@1000")
    assert fill_idx < bar_idx < timer_idx


class FillTimestampStrategy(Strategy):
    def __init__(self) -> None:
        self.fill_ts: int | None = None
        self.submitted = False

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        if not self.submitted:
            self.submitted = True
            ctx.submit_market(Side.BUY, qty=0.002)

    def on_fill(self, ctx: Context, event: FillEvent) -> None:
        self.fill_ts = event.fill.ts_ns


@pytest.mark.parametrize(("latency_ms", "expected_fill_s"), [(150, 2), (1500, 3)])
def test_latency_shifts_fill_window(latency_ms: float, expected_fill_s: int) -> None:
    strategy = FillTimestampStrategy()
    engine = Engine(
        exchange=make_exchange(tape=None, latency_ms=latency_ms),
        strategy=strategy,
        bars=make_bars(5, S),
    )
    engine.run()
    assert strategy.fill_ts == expected_fill_s * S


class LookbackStrategy(Strategy):
    def __init__(self) -> None:
        self.sizes: list[int] = []
        self.max_close_seen = 0

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        lookback = ctx.lookback(3)
        self.sizes.append(len(lookback))
        self.max_close_seen = max(self.max_close_seen, max(b.ts_close_ns for b in lookback))
        assert lookback[-1].ts_close_ns == bar.ts_close_ns


def test_lookback_returns_closed_bars_capped() -> None:
    strategy = LookbackStrategy()
    engine = Engine(exchange=make_exchange(None), strategy=strategy, bars=make_bars(5, S))
    engine.run()
    assert strategy.sizes == [1, 2, 3, 3, 3]
    assert strategy.max_close_seen == 5 * S


class MomentumRecorder(Strategy):
    """Logs a decision per closed bar from the second one on (needs 2 bars)."""

    def __init__(self) -> None:
        self.log: list[tuple[int, str]] = []

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        lookback = ctx.lookback(2)
        if len(lookback) < 2:
            return
        rose = lookback[0].close < lookback[1].close
        if rose:
            ctx.submit_market(Side.BUY, qty=0.002)
        self.log.append((bar.ts_close_ns, "buy" if rose else "hold"))


def _run_rule(bars: list[PriceBar]) -> MomentumRecorder:
    strategy = MomentumRecorder()
    Engine(exchange=make_exchange(None), strategy=strategy, bars=bars).run()
    return strategy


def test_truncation_preserves_decisions() -> None:
    bars = make_bars(8, S)
    full = _run_rule(bars)
    truncated = _run_rule(bars[:4])
    assert truncated.log == full.log[: len(truncated.log)]
    assert len(truncated.log) == 3


class EndProbe(Strategy):
    def __init__(self) -> None:
        self.on_end_called = False
        self.equity_at_end: float | None = None
        self.submitted = False

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        if not self.submitted:
            self.submitted = True
            ctx.submit_market(Side.BUY, qty=0.01)

    def on_end(self, ctx: Context) -> None:
        self.on_end_called = True
        self.equity_at_end = ctx.equity()


def test_end_valuates_open_position_and_calls_on_end() -> None:
    strategy = EndProbe()
    engine = Engine(exchange=make_exchange(None), strategy=strategy, bars=make_bars(3, S))
    result = engine.run()
    assert strategy.on_end_called
    assert result.n_bars == 3
    assert len(result.equity_curve) == 3
    final_ts, _final_equity = result.equity_curve[-1]
    assert final_ts == 3 * S
    assert result.final_equity == pytest.approx(strategy.equity_at_end)
    # an open position plus fees mean the equity moved away from the initial balance
    assert result.final_equity != pytest.approx(10_000.0)
    assert len(result.fill_events) == 1
