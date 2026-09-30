"""Benchmark: one month of 1s bars + tape must run under 10 minutes (SC-003)."""

from datetime import date
from pathlib import Path

import polars as pl
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
from tradingv2.strategies.builtin import TrivialStrategy

pytestmark = [pytest.mark.slow, pytest.mark.net]

SECOND = 1_000_000_000


def test_month_bars_with_tape_under_ten_minutes(tmp_path: Path) -> None:
    import time

    # real data must be present (feature 001): august 2026 spot klines + tape
    bars_path = Path("data/parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet")
    tape_path = Path("data/parquet/spot/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-08.parquet")
    if not bars_path.is_file() or not tape_path.is_file():
        pytest.skip("august 2026 data not downloaded yet")
    bars_df = pl.read_parquet(bars_path)
    tape_df = pl.read_parquet(tape_path)
    bars = [
        PriceBar(
            ts_open_ns=int(row["ts_open_ns"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            ts_close_ns=int(row["ts_open_ns"]) + SECOND,
        )
        for row in bars_df.iter_rows(named=True)
    ]
    exchange = SimulatedExchange(
        rules=InstrumentRules(symbol="BTCUSDT", market=Market.SPOT, tick_size=0.01, step_size=1e-5, min_notional=5.0),
        account=MarginAccount(balance=1_000.0, leverage=5),
        fees=FeeSchedule(maker_bps=2, taker_bps=5),
        slippage=SlippageModel(bps=0.5),
        latency=LatencyModel(mean_ms=150, jitter_ms=50, seed=42),
        tape=tape_df,
    )
    strategy = TrivialStrategy(hold_bars=60)
    engine = Engine(exchange=exchange, strategy=strategy, bars=bars)
    start = time.perf_counter()
    result = engine.run()
    elapsed = time.perf_counter() - start
    assert result.n_bars == bars_df.height
    assert elapsed < 600, f"one month took {elapsed:.0f}s (limit 600s)"
    print(f"\nmonth benchmark: {bars_df.height:,} bars, {tape_df.height:,} trades -> {elapsed:.1f}s")