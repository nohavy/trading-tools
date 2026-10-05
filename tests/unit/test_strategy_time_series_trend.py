"""Event-engine tests for daily-close time-series trend following."""

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
from tradingv2.strategies.time_series_trend import TimeSeriesTrend

DAY_NS = 86_400_000_000_000
RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def craft_daily(closes: list[float], opens: list[float] | None = None) -> list[PriceBar]:
    if opens is None:
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


def run(
    closes: list[float], strategy: TimeSeriesTrend, *, opens: list[float] | None = None
) -> EngineResult:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=1),
        fees=FeeSchedule(maker_bps=2.0, taker_bps=5.0),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=0.0, jitter_ms=0.0, seed=1),
    )
    return Engine(exchange, strategy, craft_daily(closes, opens)).run()


def test_waits_for_full_daily_lookback_then_fills_after_decision() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0]
    opens = [100.0, 100.0, 110.0, 119.0, 130.0]
    result = run(closes, TimeSeriesTrend(lookback_days=2), opens=opens)
    buys = [event.fill for event in result.fill_events if event.fill.side == Side.BUY]
    assert len(buys) == 1
    # Signal at the third daily close (3d); fill at the next daily bar's open.
    assert buys[0].price == pytest.approx(119.0)
    assert buys[0].ts_ns >= 3 * DAY_NS
    assert result.orders[0].submitted_ns == 3 * DAY_NS


def test_exits_on_nonpositive_trend_and_does_not_use_future_close() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 100.0, 90.0]
    opens = [100.0, 100.0, 110.0, 120.0, 130.0, 100.0]
    result = run(closes, TimeSeriesTrend(lookback_days=2), opens=opens)
    assert [event.fill.side for event in result.fill_events] == [Side.BUY, Side.SELL]
    assert result.fill_events[0].fill.price == pytest.approx(120.0)
    assert result.fill_events[1].fill.price == pytest.approx(100.0)
    assert len(result.round_trips) == 1


def test_oos_start_suppresses_orders_during_warmup() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0]
    strategy = TimeSeriesTrend(lookback_days=2, trade_start_ns=4 * DAY_NS)
    result = run(closes, strategy)
    assert result.orders
    assert all(order.submitted_ns >= 4 * DAY_NS for order in result.orders)


def test_daily_close_history_keeps_growing_while_an_order_is_pending() -> None:
    closes = [100.0 + 10.0 * i for i in range(8)]
    strategy = TimeSeriesTrend(lookback_days=2)
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=1),
        fees=FeeSchedule(maker_bps=2.0, taker_bps=5.0),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=2.5 * 86_400_000.0, jitter_ms=0.0, seed=1),
    )
    Engine(exchange, strategy, craft_daily(closes)).run()
    assert len(strategy._daily_closes) == len(closes)


def test_long_flat_never_shorts_and_buy_hold_enters_once_then_holds() -> None:
    falling = run(
        [120.0, 110.0, 100.0, 90.0],
        TimeSeriesTrend(lookback_days=1, mode="long_flat"),
    )
    assert falling.fill_events == []

    benchmark = run(
        [100.0, 90.0, 80.0, 70.0, 60.0],
        TimeSeriesTrend(lookback_days=2, mode="buy_hold", trade_start_ns=2 * DAY_NS),
    )
    assert [event.fill.side for event in benchmark.fill_events] == [Side.BUY]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"lookback_days": 0}, "lookback_days"),
        ({"lookback_days": 2, "mode": "short_only"}, "mode"),
        ({"lookback_days": 2, "target_exposure": 1.1}, "target_exposure"),
    ],
)
def test_invalid_configuration_raises(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        TimeSeriesTrend(**kwargs)  # type: ignore[arg-type]


def test_strategy_is_registered_in_builtin_factory() -> None:
    from tradingv2.strategies.builtin import build_strategy

    strategy = build_strategy("time_series_trend", {"lookback_days": 60})
    assert isinstance(strategy, TimeSeriesTrend)
