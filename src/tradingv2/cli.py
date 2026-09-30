"""tv2 command line interface."""

import typer

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


def main() -> None:
    """Entry point for the tv2 script."""
    app()


if __name__ == "__main__":
    main()
