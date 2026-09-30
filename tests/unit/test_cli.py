"""Tests for the tv2 CLI skeleton."""

from typer.testing import CliRunner

from tradingv2.cli import app

runner = CliRunner()


def test_cli_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("data", "research", "backtest", "compare"):
        assert command in result.output
