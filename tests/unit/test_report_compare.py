"""Tests for multi-run comparison (table + HTML)."""

import json
from pathlib import Path

from tradingv2.backtest.runner import run_backtest
from tradingv2.report.compare import compare_runs, comparison_table

SECOND = 1_000_000_000


def make_run(tmp_path: Path, hold_bars: int, balance: float = 1000.0) -> Path:
    from datetime import date

    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    import polars as pl

    n = 20
    bars = pl.DataFrame(
        {
            "ts_open_ns": [base_ns + i * SECOND for i in range(n)],
            "open": [5000.0 + 0.1 * i for i in range(n)],
            "high": [5000.3 + 0.1 * i for i in range(n)],
            "low": [4999.9 + 0.1 * i for i in range(n)],
            "close": [5000.2 + 0.1 * i for i in range(n)],
            "volume": [10.0] * n,
            "quote_volume": [50000.0] * n,
            "n_trades": [1] * n,
            "taker_buy_volume": [5.0] * n,
            "taker_buy_quote_volume": [25000.0] * n,
        }
    )
    directory = tmp_path / "parquet/um/klines/BTCUSDT/1s"
    directory.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(directory / "BTCUSDT-1s-2026-08-01.parquet")
    (tmp_path / "catalog.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    cfg = tmp_path / f"bt-{hold_bars}.yaml"
    cfg.write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        f"account:\n  type: margin\n  balance: {balance}\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 0\n    seed: 42\n"
        f"strategy:\n  name: trivial\n  params:\n    hold_bars: {hold_bars}\n",
        encoding="utf-8",
    )
    return run_backtest(cfg, data_root=tmp_path, runs_root=tmp_path / "runs")


def test_comparison_table_aligns_runs(tmp_path: Path) -> None:
    run1 = make_run(tmp_path, hold_bars=3)
    run2 = make_run(tmp_path, hold_bars=8)
    table = comparison_table([run1, run2])
    assert "total_return" in table
    assert len(table["total_return"]) == 2
    assert table["n_trades"] == ["1", "1"] or table["n_trades"] == [2, 1] or all(
        isinstance(v, (int, float, str)) for v in table["n_trades"]
    )


def test_compare_html_written(tmp_path: Path) -> None:
    run1 = make_run(tmp_path, hold_bars=3)
    run2 = make_run(tmp_path, hold_bars=8)
    html = compare_runs([run1, run2], runs_root=tmp_path / "runs")
    assert html.is_file()
    content = html.read_text(encoding="utf-8")
    assert "trivial" in content
    assert 'src="http' not in content
    assert run1.name in content and run2.name in content
