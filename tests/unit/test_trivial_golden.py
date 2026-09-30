"""Golden test: trivial buy-then-sell strategy must match a hand computation."""

import json
from pathlib import Path

import polars as pl
import pytest

from tradingv2.backtest.config import BacktestConfig, load_backtest_config
from tradingv2.backtest.engine import Engine
from tradingv2.backtest.runner import run_backtest
from tradingv2.config import Market
from tradingv2.core.types import PriceBar
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategies.builtin import TrivialStrategy

S = 1_000_000_000
QTY = 0.002
MAKER_BPS, TAKER_BPS = 2.0, 5.0
SLIP_BPS = 0.0  # keep the hand computation simple: no slippage, tape-less fills


def make_bars(n: int) -> list[PriceBar]:
    # linear drift +0.1 per bar (close = open + 0.2): a long earns +0.2 per bar held
    return [
        PriceBar(
            ts_open_ns=i * S,
            open=5000.0 + 0.1 * i,
            high=5000.3 + 0.1 * i,
            low=4999.9 + 0.1 * i,
            close=5000.2 + 0.1 * i,
            ts_close_ns=(i + 1) * S,
        )
        for i in range(n)
    ]


def hand_computed_final_equity(n_bars: int, hold_bars: int, balance: float) -> float:
    """Manual accounting of TrivialStrategy(hold_bars) on the drifting bars.

    Timeline: the buy is submitted at bar0's CLOSE (arrives 150ms later, inside
    bar1's window) -> filled at bar1's open. The sell fires when bars_seen
    reaches hold_bars, i.e. at bar (hold_bars - 1)'s close, and fills at bar
    hold_bars' open.
    """
    entry_open = 5000.0 + 0.1 * 1  # bar1 open
    exit_bar = min(hold_bars, n_bars - 1)
    exit_open = 5000.0 + 0.1 * exit_bar
    gross = (exit_open - entry_open) * QTY
    entry_fee = entry_open * QTY * TAKER_BPS / 10_000
    exit_fee = exit_open * QTY * TAKER_BPS / 10_000
    return balance + gross - entry_fee - exit_fee


def test_trivial_golden_exact_pnl() -> None:
    n_bars, hold_bars, balance = 10, 6, 1_000.0
    exchange = make_exchange(balance)
    result = Engine(
        exchange=exchange, strategy=TrivialStrategy(hold_bars=hold_bars), bars=make_bars(n_bars)
    ).run()
    expected = hand_computed_final_equity(n_bars, hold_bars, balance)
    assert result.final_equity == pytest.approx(expected, rel=1e-9)


def make_exchange(balance: float) -> SimulatedExchange:
    return SimulatedExchange(
        rules=InstrumentRules(
            symbol="BTCUSDT", market=Market.UM, tick_size=0.1, step_size=0.001, min_notional=5.0
        ),
        account=MarginAccount(balance=balance, leverage=5),
        fees=FeeSchedule(maker_bps=MAKER_BPS, taker_bps=TAKER_BPS),
        slippage=SlippageModel(bps=SLIP_BPS),
        latency=LatencyModel(mean_ms=150, jitter_ms=0, seed=1),
        tape=None,
    )


def test_trivial_golden_two_holds() -> None:
    for hold in (2, 5, 9):
        exchange = make_exchange(1_000.0)
        result = Engine(
            exchange=exchange, strategy=TrivialStrategy(hold_bars=hold), bars=make_bars(10)
        ).run()
        expected = hand_computed_final_equity(10, hold, 1_000.0)
        assert result.final_equity == pytest.approx(expected, rel=1e-9), f"hold={hold}"


def write_env(tmp_path: Path, n_bars: int = 12) -> None:
    from datetime import date

    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * S)
    bars = pl.DataFrame(
        {
            "ts_open_ns": [base_ns + i * S for i in range(n_bars)],
            "open": [5000.0 + 0.1 * i for i in range(n_bars)],
            "high": [5000.3 + 0.1 * i for i in range(n_bars)],
            "low": [4999.9 + 0.1 * i for i in range(n_bars)],
            "close": [5000.2 + 0.1 * i for i in range(n_bars)],
            "volume": [1.0] * n_bars,
            "quote_volume": [5000.0] * n_bars,
            "n_trades": [1] * n_bars,
            "taker_buy_volume": [0.5] * n_bars,
            "taker_buy_quote_volume": [2500.0] * n_bars,
        }
    )
    directory = tmp_path / "parquet/um/klines/BTCUSDT/1s"
    directory.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(directory / "BTCUSDT-1s-2026-08-01.parquet")
    (tmp_path / "catalog.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    (tmp_path / "bt.yaml").write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 0\n    seed: 42\n"
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 6\n",
        encoding="utf-8",
    )


def test_runner_determinism_byte_exact(tmp_path: Path) -> None:
    write_env(tmp_path)
    runs = tmp_path / "runs"
    cfg_path = tmp_path / "bt.yaml"
    run1 = run_backtest(cfg_path, data_root=tmp_path, runs_root=runs)
    run2 = run_backtest(cfg_path, data_root=tmp_path, runs_root=runs)
    for name in ("trades.csv", "orders.csv", "equity.csv", "summary.json"):
        assert (run1 / name).read_bytes() == (run2 / name).read_bytes(), name


def test_config_type_exported() -> None:
    assert load_backtest_config is not None
    assert BacktestConfig is not None
