"""tv2 command line interface."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import httpx
import polars as pl
import typer

from tradingv2.backtest.runner import run_backtest
from tradingv2.config import ConfigError, DataKind, Market, load_config
from tradingv2.data.convert import parse_interval_ns
from tradingv2.data.instruments import (
    extract_instrument_rules,
    fetch_exchange_info,
    save_instrument_rules,
)
from tradingv2.data.pipeline import run_download_pipeline
from tradingv2.data.quality import Anomaly, check_bars

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
def data_check(
    config: Annotated[Path, typer.Option(help="YAML configuration file")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
) -> None:
    """Report data quality anomalies for downloaded bar data."""

    def action() -> None:
        cfg = load_config(config)
        if cfg.data.kind != DataKind.KLINES:
            typer.echo("quality check currently supports klines only", err=True)
            raise typer.Exit(code=2)
        market_dir = cfg.data.market.value
        interval = cfg.data.interval
        assert interval is not None  # guaranteed by DataConfig for klines
        directory = data_root / "parquet" / market_dir / "klines" / cfg.data.symbol / interval
        files = sorted(directory.glob("*.parquet")) if directory.is_dir() else []
        if not files:
            typer.echo(f"no parquet files under {directory}", err=True)
            raise typer.Exit(code=2)
        interval_ns = parse_interval_ns(cfg.data.interval or "")
        anomalies: list[Anomaly] = []
        for path in files:
            anomalies.extend(check_bars(pl.read_parquet(path), interval_ns))
        if not anomalies:
            typer.echo(f"clean: {len(files)} file(s), no anomalies")
            return
        for anomaly in anomalies[:50]:
            typer.echo(f"{anomaly.kind.value} at ts={anomaly.ts_ns}: {anomaly.detail}")
        if len(anomalies) > 50:
            typer.echo(f"... and {len(anomalies) - 50} more")
        raise typer.Exit(code=1)

    _run_or_exit(action)


@backtest_app.command("run")
def backtest_run(
    config: Annotated[Path, typer.Option(help="Backtest YAML configuration file")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    runs_root: Annotated[Path, typer.Option(help="Runs output directory")] = Path("runs"),
) -> None:
    """Run a backtest and write its artifacts under runs/."""

    def action() -> None:
        run_dir = run_backtest(config, data_root=data_root, runs_root=runs_root)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        typer.echo(f"run: {run_dir}")
        typer.echo(
            f"bars={summary['n_bars']} fills={summary['n_fills']}"
            f" final_equity={summary['final_equity']:.2f}"
        )

    _run_or_exit(action)


@data_app.command("instruments")
def data_instruments(
    market: Annotated[str, typer.Option(help="Market: spot|um")],
    symbol: Annotated[str, typer.Option(help="Symbol, e.g. BTCUSDT")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
) -> None:
    """Fetch and store exchange trading rules for a symbol."""

    def action() -> None:
        try:
            market_kind = Market(market)
        except ValueError:
            typer.echo(f"invalid market '{market}': expected spot|um", err=True)
            raise typer.Exit(code=2) from None
        with httpx.Client(timeout=30.0) as client:
            raw = fetch_exchange_info(market_kind, client)
        rules = extract_instrument_rules(market_kind, raw, symbol)
        path = save_instrument_rules(rules, data_root)
        typer.echo(
            f"{rules.symbol} ({rules.market.value}): tick_size={rules.tick_size} "
            f"step_size={rules.step_size} min_notional={rules.min_notional} -> {path}"
        )

    _run_or_exit(action)


def main() -> None:
    """Entry point for the tv2 script."""
    app()


if __name__ == "__main__":
    main()
