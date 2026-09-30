"""Tests for the null strategy: the engine must charge costs, no free lunch."""


from tradingv2.config import Market
from tradingv2.core.types import PriceBar
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategies.null import NullStrategy

S = 1_000_000_000

RULES = InstrumentRules(
    symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
)

MAKER_BPS, TAKER_BPS = 2.0, 5.0


def make_bars(n: int) -> list[PriceBar]:
    # alternating noise: no drift, so the null strategy's expected gross is ~0
    return [
        PriceBar(
            ts_open_ns=i * S,
            open=5000.0 + (0.2 if i % 2 else -0.2),
            high=5001.0,
            low=4999.0,
            close=5000.0 + (0.1 if i % 3 else -0.1),
            ts_close_ns=(i + 1) * S,
        )
        for i in range(n)
    ]


def run_null(n_bars: int, seed: int, hold_bars: int = 10, qty: float = 0.01) -> tuple[float, int]:
    exchange = SimulatedExchange(
        rules=RULES,
        account=MarginAccount(balance=10_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=MAKER_BPS, taker_bps=TAKER_BPS),
        slippage=SlippageModel(bps=0.0),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )
    strategy = NullStrategy(seed=seed, hold_bars=hold_bars, qty=qty)
    from tradingv2.backtest.engine import Engine

    result = Engine(exchange=exchange, strategy=strategy, bars=make_bars(n_bars)).run()
    return result.final_equity, len(result.fill_events)


def test_null_strategy_is_deterministic() -> None:
    eq1, fills1 = run_null(100, seed=7)
    eq2, fills2 = run_null(100, seed=7)
    assert eq1 == eq2
    assert fills1 == fills2


def test_null_strategy_different_seeds_differ() -> None:
    _, fills_a = run_null(400, seed=7)
    _, fills_b = run_null(400, seed=13)
    assert fills_a != fills_b  # different random decisions


def test_null_strategy_loses_costs_over_many_runs() -> None:
    # with no drift, expected gross PnL ~ 0; net must be clearly negative (fees)
    equities = [run_null(150, seed=seed)[0] for seed in range(20)]
    losses = [10_000.0 - e for e in equities]
    mean_loss = sum(losses) / len(losses)
    assert mean_loss > 0, "null strategy must lose on average (fees)"
    # every single run must lose (fees dominate; no free lunch at 10s horizon)
    assert all(loss > 0 for loss in losses)


def test_null_loss_matches_fees_not_random_ruin() -> None:
    # estimate: ~ (150/hold_bars) round trips * 2 sides * taker fee on notional
    equity, fills = run_null(150, seed=3)
    loss = 10_000.0 - equity
    fee_estimate = fills * 0.01 * 5000.0 * TAKER_BPS / 10_000
    # the loss should be dominated by fees (within a tolerance for gross noise)
    assert fills > 5
    assert abs(loss - fee_estimate) < 0.5 * fee_estimate + 1.0
