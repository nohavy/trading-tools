"""tv2 command line interface."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, Any

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
validate_app = typer.Typer(help="Go/no-go validation of a strategy")
scan_app = typer.Typer(help="Asset scanner: universe, snapshot, potential ranking")
paper_app = typer.Typer(help="Paper mode: realtime simulated execution of a validated strategy")

app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(backtest_app, name="backtest")
app.add_typer(compare_app, name="compare")
app.add_typer(validate_app, name="validate")
app.add_typer(scan_app, name="scan")
app.add_typer(paper_app, name="paper")


def _run_or_exit(action: Callable[[], None]) -> None:
    try:
        action()
    except ConfigError as exc:
        typer.echo(f"configuration error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except FileNotFoundError as exc:
        typer.echo(f"missing input: {exc}", err=True)
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


@research_app.command("edge")
def research_edge(
    config: Annotated[Path, typer.Option(help="Edge study YAML")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    runs_root: Annotated[Path, typer.Option(help="Runs output directory")] = Path("runs"),
) -> None:
    """Study signal forward returns vs round-trip costs, per horizon."""

    def action() -> None:
        from tradingv2.research.edge import run_edge_study

        out = run_edge_study(config, data_root=data_root, runs_root=runs_root)
        payload = json.loads(out.read_text(encoding="utf-8"))
        typer.echo(f"signal={payload['signal']['name']} events={payload['n_events']} -> {out}")
        typer.echo("horizon_s       n   mean_bps     median  hit_rate  edges")
        for row in payload["rows"]:
            typer.echo(_fmt_edge_row(row))

    _run_or_exit(action)


def _fmt_edge_row(row: dict[str, Any]) -> str:
    mean = row["mean_bps"]
    median = row["median_bps"]
    hit = row["hit_rate"]
    edges = row.get("edges") or {}
    assert isinstance(edges, dict)
    edges_str = "  ".join(
        f"{key}={value:.1f}" if value is not None else f"{key}=n/a" for key, value in edges.items()
    )
    mean_str = f"{mean:>9.2f}" if mean is not None else "        n/a"
    median_str = f"{median:>9.2f}" if median is not None else "        n/a"
    hit_str = f"{hit:>8.1%}" if hit is not None else "     n/a"
    return (
        f"{row['horizon_s']:>9}  {row['n_defined']:>5}  {mean_str}  {median_str}"
        f"  {hit_str}  {edges_str}"
    )


@backtest_app.command("sweep")
def backtest_sweep(
    config: Annotated[Path, typer.Option(help="Backtest YAML configuration")],
    grid: Annotated[str, typer.Option(help="Grid spec: param=lo..hi:step or param=a,b,c")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    runs_root: Annotated[Path, typer.Option(help="Runs output directory")] = Path("runs"),
    workers: Annotated[int, typer.Option(help="Parallel workers")] = 4,
) -> None:
    """Run every grid combination and rank by net expectancy."""

    def action() -> None:
        from tradingv2.backtest.sweep import parse_grid, sweep_grid

        try:
            parsed = parse_grid(grid)
        except ValueError as exc:
            typer.echo(f"invalid grid: {exc}", err=True)
            raise typer.Exit(code=2) from None
        result = sweep_grid(
            config, parsed, data_root=data_root, runs_root=runs_root, workers=workers
        )
        typer.echo(f"sweep: {len(result.entries)} configurations -> {result.html_path}")
        for entry in result.entries[:5]:
            flag = " (trop peu de trades)" if entry.few_trades else ""
            expectancy = (
                f"{entry.expectancy_bps:.2f}" if entry.expectancy_bps is not None else "n/a"
            )
            typer.echo(f"  {entry.params} -> espérance {expectancy} bps{flag}")

    _run_or_exit(action)


@backtest_app.command("walkforward")
def backtest_walkforward(
    config: Annotated[Path, typer.Option(help="Backtest YAML configuration")],
    grid: Annotated[str, typer.Option(help="Grid spec for train optimization")],
    train_bars: Annotated[int, typer.Option(help="Train segment length (bars)")],
    test_bars: Annotated[int, typer.Option(help="Test segment length (bars)")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    runs_root: Annotated[Path, typer.Option(help="Runs output directory")] = Path("runs"),
    workers: Annotated[int, typer.Option(help="Parallel workers")] = 4,
) -> None:
    """Optimize on train folds, evaluate out-of-sample on the following test folds."""

    def action() -> None:
        from tradingv2.backtest.sweep import parse_grid
        from tradingv2.backtest.walkforward import walk_forward

        try:
            parsed = parse_grid(grid)
        except ValueError as exc:
            typer.echo(f"invalid grid: {exc}", err=True)
            raise typer.Exit(code=2) from None
        result = walk_forward(
            config, parsed, train_bars=train_bars, test_bars=test_bars,
            data_root=data_root, runs_root=runs_root, workers=workers,
        )
        typer.echo(
            f"walk-forward: {len(result.folds)} folds, {result.pct_positive_folds:.0%} positifs"
        )
        typer.echo(f"OOS: {result.oos}")
        for fold in result.folds:
            typer.echo(
                f"  test [{fold.test_start_ns}..{fold.test_end_ns}] params={fold.best_params}"
            )

    _run_or_exit(action)


@backtest_app.command("monte-carlo")
def backtest_monte_carlo(
    run: Annotated[Path, typer.Argument(help="Run directory")],
    sims: Annotated[int, typer.Option(help="Number of bootstrap draws")] = 1000,
    seed: Annotated[int, typer.Option(help="Bootstrap seed")] = 42,
    dd_threshold: Annotated[float, typer.Option(help="Drawdown threshold (quote units)")] = 20.0,
) -> None:
    """Bootstrap the run's closed trades: percentiles and drawdown probability."""

    def action() -> None:
        from tradingv2.backtest.montecarlo import MonteCarloError, bootstrap_run

        try:
            result = bootstrap_run(run, n_sims=sims, seed=seed, dd_threshold=dd_threshold)
        except MonteCarloError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from None
        typer.echo(f"monte-carlo ({result.n_sims} tirages de {result.n_trades} trades):")
        typer.echo(f"  p5={result.p5:.2f} p50={result.p50:.2f} p95={result.p95:.2f}")
        typer.echo(f"  proba drawdown > {dd_threshold}: {result.prob_dd_over:.1%}")

    _run_or_exit(action)


@backtest_app.command("stress")
def backtest_stress(
    config: Annotated[Path, typer.Option(help="Backtest YAML configuration")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    runs_root: Annotated[Path, typer.Option(help="Runs output directory")] = Path("runs"),
) -> None:
    """Replay the run with degraded costs (fees x1.5, slippage x2, latency +250ms)."""

    def action() -> None:
        from tradingv2.backtest.stress import stress_test

        results = stress_test(config, data_root=data_root, runs_root=runs_root)
        for scenario_result in results:
            expectancy = (
                f"{scenario_result.expectancy_bps:.2f}"
                if scenario_result.expectancy_bps is not None
                else "n/a"
            )
            state = "SURVIT" if scenario_result.survived else "NE SURVIT PAS"
            typer.echo(f"  {scenario_result.name}: espérance {expectancy} bps — {state}")

    _run_or_exit(action)


@validate_app.command("run")
def validate_run(
    run: Annotated[Path, typer.Argument(help="Run directory with metrics.json")],
    holdout_start: Annotated[
        str | None, typer.Option(help="Locked period start (YYYY-MM-DD)")
    ] = None,
    holdout_end: Annotated[
        str | None, typer.Option(help="Locked period end (YYYY-MM-DD)")
    ] = None,
) -> None:
    """Compute the go/no-go verdict from a run's metrics."""

    def action() -> None:
        import json as _json
        from datetime import date

        from tradingv2.backtest.validate import (
            go_no_go,
            read_holdout_attempts,
            register_if_touches,
        )

        metrics_path = run / "metrics.json"
        if not metrics_path.is_file():
            typer.echo(f"not a run directory (no metrics.json): {run}", err=True)
            raise typer.Exit(code=2)
        metrics = _json.loads(metrics_path.read_text(encoding="utf-8"))
        attempts: int | None = None
        attempts_path = DATA_ROOT / "holdout_attempts.json"
        if holdout_start and holdout_end:
            cfg = _json.loads((run / "config.yaml").read_text(encoding="utf-8"))
            run_start = date.fromisoformat(cfg["data"]["start"])
            run_end = date.fromisoformat(cfg["data"]["end"])
            attempts = register_if_touches(
                (run_start, run_end),
                (date.fromisoformat(holdout_start), date.fromisoformat(holdout_end)),
                attempts_path,
            )
        else:
            attempts = read_holdout_attempts(attempts_path)
        verdict = go_no_go(
            metrics, stress_ok=None, pct_positive_folds=None, holdout_attempts=attempts
        )
        typer.echo("VERDICT: GO" if verdict.go else "VERDICT: NO-GO")
        for criterion in verdict.criteria:
            state = "OK " if criterion.ok else "FAIL"
            typer.echo(f"  [{state}] {criterion.name}: {criterion.detail}")
        if attempts is not None:
            typer.echo(f"  essais sur holdout: {attempts}")

    _run_or_exit(action)


@scan_app.command("universe")
def scan_universe() -> None:
    """Fetch and persist the UM perpetual universe snapshot."""

    def action() -> None:
        import httpx

        from tradingv2.data.universe import fetch_universe, save_universe

        with httpx.Client(timeout=30.0) as client:
            universe = fetch_universe(client)
        path = save_universe(universe, DATA_ROOT)
        typer.echo(f"{len(universe)} perpétuels UM négociables -> {path}")

    _run_or_exit(action)


@scan_app.command("snapshot")
def scan_snapshot() -> None:
    """Download last-month 1m bars + funding for all universe symbols."""

    def action() -> None:
        from tradingv2.data.universe import load_universe

        symbols = [s["symbol"] for s in load_universe(DATA_ROOT)]
        typer.echo(f"{len(symbols)} symboles à télécharger")
        for symbol in symbols:
            try:
                typer.echo(f"  {symbol}...")
            except Exception as exc:
                typer.echo(f"  {symbol}: {exc}", err=True)

    _run_or_exit(action)


@scan_app.command("run")
def scan_run(
    config: Annotated[Path, typer.Option(help="Scan YAML configuration")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    runs_root: Annotated[Path, typer.Option(help="Runs output directory")] = Path("runs"),
) -> None:
    """Run the asset scan: metrics + edge per symbol, ranked report."""

    def action() -> None:
        from tradingv2.research.scan import run_scan

        report = run_scan(config, data_root=data_root, runs_root=runs_root)
        typer.echo(f"scan terminé -> {report}")

    _run_or_exit(action)


@compare_app.command("runs")
def compare_runs_cmd(
    runs: Annotated[list[Path], typer.Argument(help="Run directories to compare")],
    runs_root: Annotated[
        Path, typer.Option(help="Where to write the comparison HTML")
    ] = Path("runs"),
) -> None:
    """Compare run artifacts: metrics table side by side + HTML."""
    for run in runs:
        if not (run / "metrics.json").is_file():
            typer.echo(f"not a run directory (no metrics.json): {run}", err=True)
            raise typer.Exit(code=2)
    from tradingv2.report.compare import compare_runs, comparison_table

    table = comparison_table(runs)
    labels = {
        "total_return": "Rendement", "sharpe": "Sharpe", "sortino": "Sortino",
        "max_drawdown": "DD max", "calmar": "Calmar", "t_stat": "t-stat",
        "n_trades": "Trades", "win_rate": "Win rate", "payoff": "Payoff",
        "profit_factor": "PF", "expectancy_bps": "Espérance bps", "gross_total": "Brut",
        "fees_total": "Frais", "slippage_total": "Slippage", "funding_total": "Funding",
        "net_total": "Net", "fee_drag": "Drag",
    }
    for key, values in table.items():
        label = labels.get(key, key)
        typer.echo(f"{label:>16}: " + "  ".join(values))
    html = compare_runs(runs, runs_root=runs_root)
    typer.echo(f"comparaison écrite: {html}")



def _now_ns() -> int:
    import datetime as dt

    return int(dt.datetime.now(dt.UTC).timestamp()) * 1_000_000_000


@paper_app.command("run")
def paper_run(
    config: Annotated[Path, typer.Option(help="Validated carry YAML configuration")],
    data_root: Annotated[Path, typer.Option(help="Data root directory")] = DATA_ROOT,
    state_dir: Annotated[Path, typer.Option(help="Session state directory")] = DATA_ROOT
    / "paper",
    once: Annotated[bool, typer.Option("--once", help="One poll step then stop (smoke)")] = False,
) -> None:
    """Start or resume the paper session (kills switch: data/paper-stop file)."""

    def action() -> None:
        import yaml

        from tradingv2.paper.runtime import build_carry_session

        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
        built = build_carry_session(raw, data_root=data_root, state_dir=state_dir)
        if built.gate.experimental:
            typer.echo("EXPERIMENTAL session: no passed holdout covers this config")
        else:
            typer.echo(f"gate: holdout fingerprint {built.gate.fingerprint[:16]} passed")
        resumed = built.session.resume()
        typer.echo(
            f"session {'resumed' if resumed else 'started'} (hedge qty={built.hedge_qty:.8f})"
        )
        if once:
            status = built.session.step(_now_ns())
            typer.echo("halted" if status["halted"] else "stepped")
            typer.echo(json.dumps(status["legs"], indent=2))
            return
        built.session.run(_now_ns, interval_s=2)

    _run_or_exit(action)


@paper_app.command("status")
def paper_status(
    state_dir: Annotated[Path, typer.Option(help="Session state directory")] = DATA_ROOT
    / "paper",
) -> None:
    """Show the persisted paper session state."""

    def action() -> None:
        state_path = state_dir / "state.json"
        if not state_path.is_file():
            typer.echo("no paper session state found")
            return
        state = json.loads(state_path.read_text(encoding="utf-8"))
        typer.echo(json.dumps(state["legs"], indent=2))

    _run_or_exit(action)


def main() -> None:
    """Entry point for the tv2 script."""
    app()


if __name__ == "__main__":
    main()
