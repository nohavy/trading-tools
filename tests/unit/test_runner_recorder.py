"""Tests for the backtest runner: data loading, artifacts, manifest."""

import json
from pathlib import Path

import polars as pl
import pytest

from tradingv2.backtest.runner import run_backtest

SECOND = 1_000_000_000


def write_catalog_data(root: Path, n_bars: int = 40) -> None:
    """Write one window of synthetic bars + tape as if feature 001 had converted it.

    Timestamps: 2026-08-01T00:00:00Z + i seconds (the configured backtest window).
    """
    from datetime import date

    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    bars = pl.DataFrame(
        {
            "ts_open_ns": [base_ns + i * SECOND for i in range(n_bars)],
            "open": [5000.0 + 0.1 * i for i in range(n_bars)],
            "high": [5000.5 + 0.1 * i for i in range(n_bars)],
            "low": [4999.5 + 0.1 * i for i in range(n_bars)],
            "close": [5000.2 + 0.1 * i for i in range(n_bars)],
            "volume": [1.0] * n_bars,
            "quote_volume": [5000.0] * n_bars,
            "n_trades": [1] * n_bars,
            "taker_buy_volume": [0.5] * n_bars,
            "taker_buy_quote_volume": [2500.0] * n_bars,
        }
    )
    bars_dir = root / "parquet/um/klines/BTCUSDT/1s"
    bars_dir.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(bars_dir / "BTCUSDT-1s-2026-08-01.parquet")

    tape = pl.DataFrame(
        {
            "ts_ns": [base_ns + i * SECOND + 500_000_000 for i in range(n_bars)],
            "price": [5000.0 + 0.1 * i for i in range(n_bars)],
            "qty": [10.0] * n_bars,
            "buyer_is_maker": [False] * n_bars,
        }
    )
    tape_dir = root / "parquet/um/aggTrades/BTCUSDT"
    tape_dir.mkdir(parents=True, exist_ok=True)
    tape.write_parquet(tape_dir / "BTCUSDT-aggTrades-2026-08-01.parquet")

    catalog = {"updated_at": "x", "entries": []}
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def write_config(tmp_path: Path, strategy_name: str = "trivial") -> Path:
    path = tmp_path / "bt.yaml"
    path.write_text(
        "data:\n"
        "  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n  tape: aggTrades\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 0\n    seed: 42\n"
        f"strategy:\n  name: {strategy_name}\n  params:\n    hold_bars: 5\n",
        encoding="utf-8",
    )
    return path


def test_run_produces_artifacts(tmp_path: Path) -> None:
    write_catalog_data(tmp_path)
    cfg_path = write_config(tmp_path)
    runs_dir = tmp_path / "runs"
    run_dir = run_backtest(cfg_path, data_root=tmp_path, runs_root=runs_dir)
    assert run_dir.is_dir()
    names = {p.name for p in run_dir.iterdir()}
    expected = {
        "config.yaml",
        "trades.csv",
        "equity.csv",
        "orders.csv",
        "summary.json",
        "manifest.json",
    }
    assert expected <= names
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config"]["strategy"]["name"] == "trivial"
    assert manifest["seeds"]["latency"] == 42
    assert manifest["data_files"]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["n_bars"] == 40
    equity = pl.read_csv(run_dir / "equity.csv")
    assert equity.height == 40


def test_run_is_deterministic(tmp_path: Path) -> None:
    write_catalog_data(tmp_path)
    cfg_path = write_config(tmp_path)
    runs_dir = tmp_path / "runs"
    run1 = run_backtest(cfg_path, data_root=tmp_path, runs_root=runs_dir)
    run2 = run_backtest(cfg_path, data_root=tmp_path, runs_root=runs_dir)
    summary1 = (run1 / "summary.json").read_bytes()
    summary2 = (run2 / "summary.json").read_bytes()
    assert summary1 == summary2
    trades1 = (run1 / "trades.csv").read_bytes()
    trades2 = (run2 / "trades.csv").read_bytes()
    assert trades1 == trades2


def test_missing_data_fails_early(tmp_path: Path) -> None:
    write_config(tmp_path)
    with pytest.raises(Exception, match="catalog"):
        run_backtest(write_config(tmp_path), data_root=tmp_path, runs_root=tmp_path / "runs")


def test_unknown_strategy_fails_early(tmp_path: Path) -> None:
    write_catalog_data(tmp_path)
    with pytest.raises(Exception, match="unknown strategy"):
        run_backtest(
            write_config(tmp_path, strategy_name="does_not_exist"),
            data_root=tmp_path,
            runs_root=tmp_path / "runs",
        )
