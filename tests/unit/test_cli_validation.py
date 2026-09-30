"""Tests for validation CLI commands: research edge, sweep, walkforward, MC, stress, validate."""

import json
from datetime import date
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from tradingv2.backtest.runner import run_backtest
from tradingv2.cli import app

runner = CliRunner()

SECOND = 1_000_000_000


def make_env(tmp_path: Path, n_bars: int = 40) -> tuple[Path, Path, Path]:
    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    closes = [5000.0 + 0.1 * i - (2.0 if i % 7 == 0 else 0.0) for i in range(n_bars)]
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
    bt = tmp_path / "bt.yaml"
    bt.write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 0\n    seed: 42\n"
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 5\n",
        encoding="utf-8",
    )
    return tmp_path, bt, tmp_path / "runs"


RESEARCH_YAML = """\
data:
  market: um
  kind: klines
  symbol: BTCUSDT
  interval: 1s
  start: 2026-08-01
  end: 2026-08-01
signal:
  name: meanrev
  window: 3
  entry_z: 1.0
horizons_s: [1, 5]
cost_pairs:
  - name: um_market
    maker_bps: 2
    taker_bps: 5
"""


def test_cli_research_edge_end_to_end(tmp_path: Path) -> None:
    data_root, _bt, runs = make_env(tmp_path)
    research = tmp_path / "research.yaml"
    research.write_text(RESEARCH_YAML, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "research",
            "edge",
            "--config",
            str(research),
            "--data-root",
            str(data_root),
            "--runs-root",
            str(runs),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "meanrev" in result.output
    assert "horizon" in result.output.lower()
    edges = list(runs.glob("edge-*.json"))
    assert edges
    payload = json.loads(edges[0].read_text(encoding="utf-8"))
    assert payload["signal"]["name"] == "meanrev"
    assert payload["rows"]


def test_cli_research_edge_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["research", "edge", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2


def test_cli_backtest_sweep(tmp_path: Path) -> None:
    data_root, bt, runs = make_env(tmp_path)
    result = runner.invoke(
        app,
        ["backtest", "sweep", "--config", str(bt), "--grid", "hold_bars=2,4",
         "--data-root", str(data_root), "--runs-root", str(runs)],
    )
    assert result.exit_code == 0, result.output
    assert "2" in result.output


def test_cli_backtest_sweep_bad_grid(tmp_path: Path) -> None:
    data_root, bt, runs = make_env(tmp_path)
    result = runner.invoke(
        app,
        ["backtest", "sweep", "--config", str(bt), "--grid", "hold_bars=oops",
         "--data-root", str(data_root), "--runs-root", str(runs)],
    )
    assert result.exit_code == 2
    assert "grid" in result.output


def test_cli_backtest_walkforward(tmp_path: Path) -> None:
    data_root, bt, runs = make_env(tmp_path)
    result = runner.invoke(
        app,
        ["backtest", "walkforward", "--config", str(bt), "--grid", "hold_bars=2,3",
         "--train-bars", "4", "--test-bars", "2",
         "--data-root", str(data_root), "--runs-root", str(runs)],
    )
    assert result.exit_code == 0, result.output
    assert "folds" in result.output.lower()


def test_cli_backtest_monte_carlo(tmp_path: Path) -> None:
    data_root, bt, runs = make_env(tmp_path)
    run_dir = run_backtest(bt, data_root=data_root, runs_root=runs)
    result = runner.invoke(
        app, ["backtest", "monte-carlo", str(run_dir), "--sims", "100"]
    )
    assert result.exit_code == 0, result.output
    assert "p50" in result.output


def test_cli_backtest_stress(tmp_path: Path) -> None:
    data_root, bt, runs = make_env(tmp_path)
    result = runner.invoke(
        app, ["backtest", "stress", "--config", str(bt),
              "--data-root", str(data_root), "--runs-root", str(runs)]
    )
    assert result.exit_code == 0, result.output
    assert "combined" in result.output


def test_cli_validate_reports_go_or_no_go(tmp_path: Path) -> None:
    data_root, bt, runs = make_env(tmp_path)
    run_dir = run_backtest(bt, data_root=data_root, runs_root=runs)
    result = runner.invoke(app, ["validate", "run", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert "GO" in result.output  # GO or NO-GO
    # without walk-forward and stress the verdict must be NO-GO
    assert "NO-GO" in result.output
