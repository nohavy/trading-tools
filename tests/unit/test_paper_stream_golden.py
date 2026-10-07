"""Golden test: streaming (paper) processing matches the backtest Engine exactly."""

import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import FundingEvent, PriceBar
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategies.time_series_trend import TimeSeriesTrend

DAY_NS = 86_400_000_000_000
RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def craft_daily(closes: list[float]) -> list[PriceBar]:
    opens = [closes[0], *closes[:-1]]
    return [
        PriceBar(
            ts_open_ns=i * DAY_NS,
            open=opens[i],
            high=max(opens[i], closes[i]) + 0.1,
            low=min(opens[i], closes[i]) - 0.1,
            close=closes[i],
            ts_close_ns=(i + 1) * DAY_NS,
        )
        for i in range(len(closes))
    ]


def _exchange() -> SimulatedExchange:
    return SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=1),
        fees=FeeSchedule(maker_bps=2.0, taker_bps=5.0),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=0.0, jitter_ms=0.0, seed=1),
    )


def _strategy() -> TimeSeriesTrend:
    return TimeSeriesTrend(lookback_days=2, mode="long_flat")


FUNDING = [
    FundingEvent(ts_ns=DAY_NS // 2, rate=0.0001),
    FundingEvent(ts_ns=DAY_NS + DAY_NS // 2, rate=-0.0001),
]


def test_streaming_engine_reproduces_backtest_engine_exactly() -> None:
    bars = craft_daily([100.0, 110.0, 120.0, 130.0, 100.0, 90.0, 120.0, 140.0])

    backtest = Engine(_exchange(), _strategy(), bars)
    result_backtest = backtest.run(FUNDING)

    streaming = Engine(_exchange(), _strategy())
    for bar in bars:
        settlements = [f for f in FUNDING if bar.ts_close_ns - DAY_NS < f.ts_ns <= bar.ts_close_ns]
        streaming.process_bar(bar, settlements)
    result_streaming = streaming.finish(final_mark=bars[-1].close)

    assert len(result_streaming.fill_events) == len(result_backtest.fill_events)
    for fill_a, fill_b in zip(
        result_backtest.fill_events, result_streaming.fill_events, strict=True
    ):
        assert (fill_a.fill.ts_ns, fill_a.fill.side, fill_a.fill.qty) == (
            fill_b.fill.ts_ns, fill_b.fill.side, fill_b.fill.qty
        )
        assert fill_a.fill.price == pytest.approx(fill_b.fill.price)
    assert result_streaming.equity_curve == result_backtest.equity_curve
    assert result_streaming.final_equity == pytest.approx(result_backtest.final_equity)
    assert len(result_streaming.round_trips) == len(result_backtest.round_trips)
    if result_backtest.round_trips:
        assert (
            result_streaming.round_trips[0].net
            == pytest.approx(result_backtest.round_trips[0].net)
        )


def test_streaming_engine_starts_lazily_and_ends_once() -> None:
    bars = craft_daily([100.0, 110.0, 120.0])
    engine = Engine(_exchange(), _strategy())
    ends: list[int] = []
    strategy = engine.strategy

    def counting_end(ctx: object) -> None:
        ends.append(1)
        del ctx

    strategy.on_end = counting_end  # type: ignore[method-assign]
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    engine.process_bar(bars[2])
    engine.finish()
    engine.finish()  # second finish must not call on_end again
    assert len(ends) == 1
