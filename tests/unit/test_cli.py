"""Tests for the tv2 CLI skeleton."""

from pathlib import Path

from typer.testing import CliRunner

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
