"""Event-engine tests for the single-entry legs of the spot/perp carry hedge."""

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
from tradingv2.portfolio.spot import SpotAccount
from tradingv2.strategies.cash_carry import CashCarryPerpLeg, CashCarrySpotLeg

DAY_NS = 86_400_000_000_000
SPOT_RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.SPOT, tick_size=0.01, step_size=1e-5, min_notional=5.0
)
UM_RULES = InstrumentRules(
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


def _run(
    closes: list[float],
    strategy: CashCarrySpotLeg | CashCarryPerpLeg,
    *,
    spot: bool,
    balance: float = 10_000.0,
) -> EngineResult:
    if spot:
        account: SpotAccount | MarginAccount = SpotAccount(quote_balance=balance)
        rules = SPOT_RULES
    else:
        account = MarginAccount(balance=balance, leverage=2)
        rules = UM_RULES
    exchange = SimulatedExchange(
        rules=rules,
        account=account,
        fees=FeeSchedule(maker_bps=2.0, taker_bps=5.0),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=0.0, jitter_ms=0.0, seed=1),
    )
    return Engine(exchange, strategy, craft_daily(closes)).run()


def test_spot_leg_buys_the_hedge_qty_once_after_trade_start() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    strategy = CashCarrySpotLeg(qty=0.1, trade_start_ns=3 * DAY_NS)
    result = _run(closes, strategy, spot=True)
    buys = [event.fill for event in result.fill_events if event.fill.side == Side.BUY]
    assert len(buys) == 1
    # Decision at the daily close boundary 3d; fill at the next bar's open.
    assert result.orders[0].submitted_ns == 3 * DAY_NS
    assert buys[0].ts_ns >= 3 * DAY_NS
    assert buys[0].qty == pytest.approx(0.1)


def test_perp_leg_shorts_the_hedge_qty_once_after_trade_start() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    strategy = CashCarryPerpLeg(qty=0.1, trade_start_ns=3 * DAY_NS)
    result = _run(closes, strategy, spot=False)
    sells = [event.fill for event in result.fill_events if event.fill.side == Side.SELL]
    assert len(sells) == 1
    assert result.orders[0].submitted_ns == 3 * DAY_NS
    assert sells[0].qty == pytest.approx(0.1)


def test_legs_never_exit_and_never_resubmit() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0, 130.0, 120.0, 110.0, 100.0, 90.0]
    spot_result = _run(closes, CashCarrySpotLeg(qty=0.1, trade_start_ns=1 * DAY_NS), spot=True)
    perp_result = _run(closes, CashCarryPerpLeg(qty=0.1, trade_start_ns=1 * DAY_NS), spot=False)
    for result in (spot_result, perp_result):
        assert len(result.fill_events) == 1
        assert len(result.orders) == 1
        assert result.round_trips == []


def test_rejected_order_is_not_retried() -> None:
    closes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    spot_result = _run(
        closes, CashCarrySpotLeg(qty=100.0, trade_start_ns=1 * DAY_NS),
        spot=True, balance=10.0,
    )
    perp_result = _run(
        closes, CashCarryPerpLeg(qty=100.0, trade_start_ns=1 * DAY_NS),
        spot=False, balance=10.0,
    )
    for result in (spot_result, perp_result):
        assert result.fill_events == []
        assert len(result.orders) == 1  # exactly one attempt, never retried
        assert result.orders[0].status.name == "REJECTED"


def test_first_daily_close_exactly_at_trade_start_is_eligible() -> None:
    closes = [100.0, 110.0]
    spot_result = _run(closes, CashCarrySpotLeg(qty=0.1, trade_start_ns=1 * DAY_NS), spot=True)
    assert len(spot_result.fill_events) == 1


def test_invalid_configuration_raises() -> None:
    with pytest.raises(ValueError, match="qty"):
        CashCarrySpotLeg(qty=0.0)
    with pytest.raises(ValueError, match="trade_start_ns"):
        CashCarryPerpLeg(qty=0.1, trade_start_ns=-1)


def test_strategies_are_registered_in_builtin_factory() -> None:
    from tradingv2.strategies.builtin import build_strategy

    spot_strategy = build_strategy("carry_spot_leg", {"qty": 0.1, "trade_start_ns": 0})
    perp_strategy = build_strategy("carry_perp_leg", {"qty": 0.1, "trade_start_ns": 0})
    assert isinstance(spot_strategy, CashCarrySpotLeg)
    assert isinstance(perp_strategy, CashCarryPerpLeg)
