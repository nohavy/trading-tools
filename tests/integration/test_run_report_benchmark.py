"""Benchmark: full run (engine + metrics + report) under 60s on real month data."""

from pathlib import Path

import pytest

from tradingv2.backtest.runner import run_backtest

pytestmark = pytest.mark.slow


def test_full_month_run_with_report_under_60s(tmp_path: Path) -> None:
    import time

    bars_path = Path("data/parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet")
    if not bars_path.is_file():
        pytest.skip("august 2026 data not downloaded yet")
    cfg = tmp_path / "bt.yaml"
    cfg.write_text(
        "data:\n"
        "  market: spot\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-31\n  tape: aggTrades\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 50\n    seed: 42\n"
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 60\n",
        encoding="utf-8",
    )
    start = time.perf_counter()
    run_dir = run_backtest(cfg, data_root=Path("data"), runs_root=tmp_path / "runs")
    elapsed = time.perf_counter() - start
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "metrics.json").is_file()
    assert elapsed < 60, f"full month run took {elapsed:.0f}s (limit 60s)"
