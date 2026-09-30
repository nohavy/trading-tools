"""Tests for the tv2 CLI skeleton."""

from pathlib import Path

import polars as pl
from typer.testing import CliRunner, Result

from tradingv2.cli import app

runner = CliRunner()


def test_cli_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("data", "research", "backtest", "compare"):
        assert command in result.output


def test_cli_data_lists_data_commands() -> None:
    result = runner.invoke(app, ["data", "--help"])
    assert result.exit_code == 0
    for command in ("download", "check", "instruments"):
        assert command in result.output


def test_cli_download_reports_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["data", "download", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_cli_instruments_invalid_market_exits_two(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "data",
            "instruments",
            "--market",
            "binance",
            "--symbol",
            "BTCUSDT",
            "--data-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2


def test_cli_instruments_requires_options() -> None:
    result = runner.invoke(app, ["data", "instruments"])
    assert result.exit_code != 0


def test_cli_backtest_run_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["backtest", "run", "--config", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2
    assert "not found" in result.output


def test_cli_check_clean_dataset_exits_zero(tmp_path: Path) -> None:
    _write_bars(tmp_path, clean=True)
    result = _invoke_check(tmp_path)
    assert result.exit_code == 0
    assert "clean" in result.output


def test_cli_check_reports_anomalies_and_exits_one(tmp_path: Path) -> None:
    _write_bars(tmp_path, clean=False)
    result = _invoke_check(tmp_path)
    assert result.exit_code == 1
    assert "gap" in result.output


def _invoke_check(tmp_path: Path) -> "Result":
    return runner.invoke(
        app,
        ["data", "check", "--config", str(_write_config(tmp_path)), "--data-root", str(tmp_path)],
    )


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "cfg.yaml"
    path.write_text(
        "data:\n  market: spot\n  kind: klines\n  symbol: BTCUSDT\n"
        "  interval: 1s\n  start: 2026-08-01\n  end: 2026-08-31\n",
        encoding="utf-8",
    )
    return path


def _write_bars(root: Path, *, clean: bool) -> None:
    from tradingv2.data.store import write_parquet

    second = 1_000_000_000
    ts = [(1_735_689_600 + i) * second for i in range(10)]
    if not clean:
        ts.pop(4)
    df = pl.DataFrame(
        {
            "ts_open_ns": ts,
            "open": [100.0] * len(ts),
            "high": [100.0] * len(ts),
            "low": [100.0] * len(ts),
            "close": [100.0] * len(ts),
            "volume": [1.0] * len(ts),
            "quote_volume": [100.0] * len(ts),
            "n_trades": [1] * len(ts),
            "taker_buy_volume": [0.5] * len(ts),
            "taker_buy_quote_volume": [50.0] * len(ts),
        }
    )
    write_parquet(df, root / "parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08-01.parquet")
