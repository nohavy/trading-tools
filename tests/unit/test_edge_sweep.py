"""Tests for the edge sweep: signal parameter grids in research mode (fast)."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tradingv2.research.edge import EdgeSweepEntry, edge_sweep

SECOND = 1_000_000_000


def make_env(tmp_path: Path, n_bars: int = 300) -> Path:
    """Data with periodic deep dips: meanrev signals fire on short windows."""
    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    closes = [5000.0 + (0.1 * i) - (5.0 if i % 25 == 0 else 0.0) for i in range(n_bars)]
    bars = pl.DataFrame(
        {
            "ts_open_ns": [base_ns + i * SECOND for i in range(n_bars)],
            "open": [closes[max(i - 1, 0)] for i in range(n_bars)],
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
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
    return tmp_path


def write_research(tmp_path: Path, window: int = 5, entry_z: float = 1.0) -> Path:
    path = tmp_path / "research.yaml"
    path.write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        f"signal:\n  name: meanrev\n  window: {window}\n  entry_z: {entry_z}\n"
        "horizons_s: [1, 60]\n"
        "cost_pairs:\n  - name: um_mm\n    maker_bps: 2\n    taker_bps: 5\n",
        encoding="utf-8",
    )
    return path


def test_edge_sweep_ranks_by_target_horizon(tmp_path: Path) -> None:
    make_env(tmp_path)
    result = edge_sweep(
        write_research(tmp_path), {"window": [3, 30]},
        data_root=tmp_path, runs_root=tmp_path / "runs", target_horizon_s=60, min_events=5,
    )
    assert len(result.entries) == 2
    assert isinstance(result.entries[0], EdgeSweepEntry)
    windows = {e.params["window"]: e for e in result.entries}
    assert windows[3].n_events > 0
    assert windows[30].n_events > 0
    # ranked by score at the target horizon; no score ranks last
    scores = [e.score_bps for e in result.entries]
    defined = [s for s in scores if s is not None]
    assert defined == sorted(defined, reverse=True) or not defined


def test_edge_sweep_few_events_flag(tmp_path: Path) -> None:
    make_env(tmp_path)
    result = edge_sweep(
        write_research(tmp_path), {"window": [3]},
        data_root=tmp_path, runs_root=tmp_path / "runs", target_horizon_s=60, min_events=10_000,
    )
    assert result.entries[0].few_events


def test_edge_sweep_deterministic_and_writes_html(tmp_path: Path) -> None:
    make_env(tmp_path)
    grid: dict[str, list[float | int]] = {"window": [3, 5]}
    runs = tmp_path / "runs"
    r1 = edge_sweep(write_research(tmp_path), grid, data_root=tmp_path, runs_root=runs)
    r2 = edge_sweep(write_research(tmp_path), grid, data_root=tmp_path, runs_root=runs)
    assert [(e.params, e.score_bps) for e in r1.entries] == [
        (e.params, e.score_bps) for e in r2.entries
    ]
    assert r1.html_path.is_file()
    content = r1.html_path.read_text(encoding="utf-8")
    assert 'src="http' not in content
    assert "window" in content


def test_edge_sweep_unknown_signal_raises(tmp_path: Path) -> None:
    make_env(tmp_path)
    research = tmp_path / "research.yaml"
    research.write_text(
        "data:\n  market: um\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        "signal:\n  name: martingale\nhorizons_s: [1]\ncost_pairs: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown signal"):
        edge_sweep(research, {"window": [3]}, data_root=tmp_path, runs_root=tmp_path / "runs")
