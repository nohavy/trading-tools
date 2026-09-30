"""Tests for the buy-and-hold benchmark and the strategy registry."""

import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import PriceBar, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategies.builtin import STRATEGIES, build_strategy
from tradingv2.strategies.buyhold import BuyHold
from tradingv2.strategy.base import Context, Strategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)


def make_bars(n: int) -> list[PriceBar]:
    return [
        PriceBar(
            ts_open_ns=i * S,
            open=5000.0 + i,
            high=5000.5 + i,
            low=4999.5 + i,
            close=5000.2 + i,
            ts_close_ns=(i + 1) * S,
            volume=10.0,
        )
        for i in range(n)
    ]


def test_buy_hold_buys_once_and_never_sells() -> None:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    result = Engine(exchange=exchange, strategy=BuyHold(qty=0.002), bars=make_bars(5)).run()
    buys = [e.fill for e in result.fill_events if e.fill.side == Side.BUY]
    sells = [e.fill for e in result.fill_events if e.fill.side == Side.SELL]
    assert len(buys) == 1
    assert sells == []
    assert result.round_trips == []  # never closed
    # the position rides the uptrend: final equity above balance minus fees
    assert result.final_equity > 10_000.0 - 1.0


class _Probe(Strategy):
    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar, ctx


def test_registry_has_all_four_strategies() -> None:
    for name in ("meanrev_zscore", "breakout_volume", "orderflow_imbalance", "buy_hold"):
        assert name in STRATEGIES, name
        strategy = build_strategy(name, {})
        assert isinstance(strategy, Strategy)


def test_registry_builds_with_params() -> None:
    strategy = build_strategy(
        "meanrev_zscore", {"window": 5, "entry_z": 2.0, "exit_z": 0.5, "qty": 0.001}
    )
    assert isinstance(strategy, Strategy)


def test_registry_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        build_strategy("martingale", {})


def test_registry_params_pass_through() -> None:
    # buy_hold accepts qty
    strategy = build_strategy("buy_hold", {"qty": 0.005})
    assert isinstance(strategy, BuyHold)
