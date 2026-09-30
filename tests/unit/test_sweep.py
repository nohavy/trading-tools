"""Tests for the parameter grid sweep (parallel, deterministic, ranked)."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tradingv2.backtest.sweep import SweepEntry, parse_grid, sweep_grid

SECOND = 1_000_000_000


def make_env(tmp_path: Path, n_bars: int = 20) -> tuple[Path, Path, Path]:
    """Synthetic data + base config; returns (data_root, config_path, runs_root)."""
    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    bars = pl.DataFrame(
        {
            "ts_open_ns": [base_ns + i * SECOND for i in range(n_bars)],
            "open": [5000.0 + 0.1 * i for i in range(n_bars)],
            "high": [5000.3 + 0.1 * i for i in range(n_bars)],
            "low": [4999.9 + 0.1 * i for i in range(n_bars)],
            "close": [5000.2 + 0.1 * i for i in range(n_bars)],
            "volume": [10.0] * n_bars,
            "quote_volume": [50000.0] * n_bars,
            "n_trades": [1] * n_bars,
            "taker_buy_volume": [5.0] * n_bars,
            "taker_buy_quote_volume": [25000.0] * n_bars,
        }
    )
    directory = tmp_path / "parquet/um/klines/BTCUSDT/1s"
    directory.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(directory / "BTCUSDT-1s-2026-08-01.parquet")
    (tmp_path / "catalog.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    cfg = tmp_path / "bt.yaml"
    cfg.write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 0\n    seed: 42\n"
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 5\n",
        encoding="utf-8",
    )
    return tmp_path, cfg, tmp_path / "runs"


def test_parse_grid_ranges_and_explicit() -> None:
    grid = parse_grid("hold_bars=2..6:2,qty=0.001,0.003")
    assert grid == {"hold_bars": [2, 4, 6], "qty": [0.001, 0.003]}


def test_parse_grid_float_range() -> None:
    grid = parse_grid("entry_z=1.5..2.5:0.5")
    assert grid == {"entry_z": [1.5, 2.0, 2.5]}


def test_parse_grid_invalid_raises() -> None:
    with pytest.raises(ValueError, match="grid"):
        parse_grid("hold_bars=oops")


def test_sweep_runs_all_combinations_ranked(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    result = sweep_grid(cfg, {"hold_bars": [2, 4]}, data_root=data_root, runs_root=runs, workers=2)
    assert len(result.entries) == 2
    expectancies = [e.expectancy_bps for e in result.entries]
    assert expectancies == sorted(expectancies, reverse=True) or all(
        e is None for e in expectancies
    )
    for entry in result.entries:
        assert isinstance(entry, SweepEntry)
        assert entry.run_dir.is_dir()
        assert (entry.run_dir / "metrics.json").is_file()


def test_sweep_is_deterministic(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    result1 = sweep_grid(cfg, {"hold_bars": [2, 4]}, data_root=data_root, runs_root=runs, workers=1)
    result2 = sweep_grid(
        cfg, {"hold_bars": [2, 4]}, data_root=data_root, runs_root=runs, workers=1
    )
    assert [e.params for e in result1.entries] == [e.params for e in result2.entries]
    assert [e.expectancy_bps for e in result1.entries] == [
        e.expectancy_bps for e in result2.entries
    ]


def test_sweep_marks_few_trades(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path, n_bars=20)
    result = sweep_grid(
        cfg, {"hold_bars": [2]}, data_root=data_root, runs_root=runs, workers=1, min_trades=5
    )
    assert result.entries[0].few_trades  # 1-2 trips < 5


def test_sweep_writes_html(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    result = sweep_grid(cfg, {"hold_bars": [2, 4]}, data_root=data_root, runs_root=runs, workers=1)
    assert result.html_path is not None
    assert result.html_path.is_file()
    content = result.html_path.read_text(encoding="utf-8")
    assert 'src="http' not in content
    assert "hold_bars" in content


def test_sweep_single_point_grid(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    result = sweep_grid(cfg, {"hold_bars": [3]}, data_root=data_root, runs_root=runs, workers=1)
    assert len(result.entries) == 1
