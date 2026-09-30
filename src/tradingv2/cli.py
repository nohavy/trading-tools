"""tv2 command line interface."""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from tradingv2.config import ConfigError, load_config
from tradingv2.data.pipeline import run_download_pipeline

DATA_ROOT = Path("data")

app = typer.Typer(
    help="tradingv2 — crypto microtrading toolkit (Binance spot + USDT-M futures)",
    no_args_is_help=True,
)

data_app = typer.Typer(help="Historical data: download, quality check, instrument rules")
research_app = typer.Typer(help="Edge research: signal vs costs analysis")
backtest_app = typer.Typer(help="Backtest engine: run, sweep, walk-forward")
compare_app = typer.Typer(help="Compare backtest runs")

app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(backtest_app, name="backtest")
app.add_typer(compare_app, name="compare")


def _run_or_exit(action: Callable[[], None]) -> None:
    try:
        action()
    except ConfigError as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@data_app.command("download")
def data_download(
    config: Annotated[Path, typer.Option(help="YAML configuration file")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
) -> None:
    """Download and convert historical data from data.binance.vision."""

    def action() -> None:
        cfg = load_config(config)
        summary = run_download_pipeline(cfg.data, data_root, today=date.today())
        typer.echo(
            f"downloaded={summary.downloaded} skipped={summary.skipped} "
            f"converted={summary.converted} failed={summary.failed}"
        )
        if summary.failed:
            raise typer.Exit(code=1)

    _run_or_exit(action)


@data_app.command("check")
def data_check(config: Annotated[Path, typer.Option(help="YAML configuration file")]) -> None:
    """Report data quality anomalies for a downloaded dataset."""
    typer.echo("not implemented yet")


@data_app.command("instruments")
def data_instruments(
    market: Annotated[str, typer.Option(help="Market: spot|um")],
    symbol: Annotated[str, typer.Option(help="Symbol, e.g. BTCUSDT")],
) -> None:
    """Fetch and store exchange trading rules for a symbol."""
    typer.echo("not implemented yet")


def main() -> None:
    """Entry point for the tv2 script."""
    app()


if __name__ == "__main__":
    main()
