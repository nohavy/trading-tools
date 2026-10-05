import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import yaml

from tradingv2.backtest.config import BacktestConfig, load_backtest_config
from tradingv2.backtest.engine import Engine, EngineResult
from tradingv2.core.types import FundingEvent, PriceBar
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.convert import parse_interval_ns
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.metrics.compute import MetricsReport
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.portfolio.spot import SpotAccount
from tradingv2.strategies.builtin import build_strategy

_EPOCH = date(1970, 1, 1)


def _file_overlaps_bounds(path: Path, bounds: tuple[int, int]) -> bool:
    """Monthly file stem 'SYMBOL-interval-YYYY-MM' overlaps [lower, upper] ns?"""
    match = __import__("re").search(r"-(\d{4}-\d{2})\.parquet$", path.name)
    if match is None:
        return True  # unknown stem: keep (daily files handled by caller filtering)
    year, month = int(match.group(1)[:4]), int(match.group(1)[5:7])
    from datetime import date as _date

    month_start = int((_date(year, month, 1) - _EPOCH).total_seconds() * 1e9)
    next_month = _date(year + (month == 12), month % 12 + 1, 1)
    month_end = int((next_month - _EPOCH).total_seconds() * 1e9)
    lower, upper = bounds
    return month_start <= upper and month_end >= lower


class RunnerError(Exception):
    """Raised when a backtest cannot be prepared (data, strategy, catalog)."""


def _load_bars(
    cfg: BacktestConfig, data_root: Path, bar_bounds: tuple[int, int] | None = None
) -> list[PriceBar]:
    catalog_path = data_root / "catalog.json"
    if not catalog_path.is_file():
        raise RunnerError(
            f"data catalog not found under {data_root}: run 'tv2 data download' first"
        )
    interval = cfg.data.interval
    if interval is None:
        raise RunnerError("data.interval is required for a backtest")
    directory = data_root / "parquet" / cfg.data.market / "klines" / cfg.data.symbol / interval
    files = sorted(directory.glob("*.parquet")) if directory.is_dir() else []
    if not files:
        raise RunnerError(f"no bar data under {directory}: download data first")
    if bar_bounds is not None:
        files = [f for f in files if _file_overlaps_bounds(f, bar_bounds)]
    from datetime import timedelta

    lower_ns = int((cfg.data.start - _EPOCH).total_seconds() * 1e9)
    upper_ns = int((cfg.data.end - _EPOCH + timedelta(days=1)).total_seconds() * 1e9) - 1
    bars: list[PriceBar] = []
    interval_ns = parse_interval_ns(interval)
    for path in files:
        df = pl.read_parquet(path)
        for row in df.iter_rows(named=True):
            bars.append(
                PriceBar(
                    ts_open_ns=int(row["ts_open_ns"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    ts_close_ns=int(row["ts_open_ns"]) + interval_ns,
                    volume=float(row["volume"]),
                    taker_buy_volume=float(row["taker_buy_volume"]),
                )
            )
    bars = [b for b in bars if lower_ns <= b.ts_close_ns <= upper_ns]
    if bar_bounds is not None:
        lower, upper = bar_bounds
        bars = [b for b in bars if lower <= b.ts_close_ns <= upper]
    bars.sort(key=lambda b: b.ts_close_ns)
    return bars


def _load_tape(cfg: BacktestConfig, data_root: Path) -> pl.DataFrame | None:
    if cfg.data.tape is None:
        return None
    directory = data_root / "parquet" / cfg.data.market / cfg.data.tape / cfg.data.symbol
    files = sorted(directory.glob("*.parquet")) if directory.is_dir() else []
    if not files:
        raise RunnerError(f"no tape data under {directory}: download {cfg.data.tape} first")
    frames = [pl.read_parquet(path) for path in files]
    return pl.concat(frames).sort("ts_ns")


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return "unknown"


def run_backtest(
    config_path: Path,
    data_root: Path,
    runs_root: Path,
    *,
    bar_bounds: tuple[int, int] | None = None,
) -> Path:
    """Run one backtest from a config file; return the run directory.

    bar_bounds optionally restricts the bars by close timestamp (walk-forward
    folds, sweeps on segments).
    """
    cfg = load_backtest_config(config_path)
    strategy = build_strategy(cfg.strategy.name, cfg.strategy.params)
    bars = _load_bars(cfg, data_root, bar_bounds)
    tape = _load_tape(cfg, data_root)

    account: MarginAccount | SpotAccount
    if cfg.account.type == "margin":
        account = MarginAccount(
            balance=cfg.account.balance, leverage=cfg.account.leverage, mmr=cfg.account.mmr
        )
    else:
        account = SpotAccount(quote_balance=cfg.account.balance)
    exchange = SimulatedExchange(
        rules=_rules_for(cfg, data_root),
        account=account,
        fees=FeeSchedule(maker_bps=cfg.costs.maker_bps, taker_bps=cfg.costs.taker_bps),
        slippage=SlippageModel(bps=cfg.costs.slippage_bps),
        latency=LatencyModel(
            mean_ms=cfg.costs.latency.mean_ms,
            jitter_ms=cfg.costs.latency.jitter_ms,
            seed=cfg.costs.latency.seed,
        ),
        tape=tape,
    )
    engine = Engine(exchange=exchange, strategy=strategy, bars=bars)
    interval_ns = parse_interval_ns(cfg.data.interval or "1s")
    result = engine.run(
        funding_events=_load_funding(cfg, data_root) if cfg.account.type == "margin" else None
    )
    from tradingv2.metrics.compute import compute_metrics, metrics_to_json

    metrics = compute_metrics(
        pl.DataFrame(
            {
                "ts_ns": [ts for ts, _ in result.equity_curve],
                "equity": [e for _, e in result.equity_curve],
            }
        ),
        result.round_trips,
        interval_ns,
    )
    return _record(
        cfg,
        result,
        metrics,
        data_root,
        runs_root,
        metrics_json=metrics_to_json(metrics),
        render=True,
    )


def _rules_for(cfg: BacktestConfig, data_root: Path) -> InstrumentRules:
    from tradingv2.config import Market
    from tradingv2.data.instruments import InstrumentError, load_instrument_rules


    market = Market(cfg.data.market)
    try:
        return load_instrument_rules(data_root, market, cfg.data.symbol)
    except InstrumentError:
        # sensible defaults when instruments were not fetched yet (tests, first runs)
        return InstrumentRules(
            symbol=cfg.data.symbol, market=market, tick_size=0.1, step_size=0.001, min_notional=5.0
        )


def _load_funding(cfg: BacktestConfig, data_root: Path) -> list[FundingEvent] | None:
    """Load funding events from the catalogue when the account is a margin one."""
    directory = data_root / "parquet" / cfg.data.market / "fundingRate" / cfg.data.symbol
    files = sorted(directory.glob("*.parquet")) if directory.is_dir() else []
    if not files:
        return None
    frames = [pl.read_parquet(path) for path in files]
    df = pl.concat(frames).sort("ts_ns")
    return [
        FundingEvent(ts_ns=int(row["ts_ns"]), rate=float(row["rate"]))
        for row in df.iter_rows(named=True)
    ]


def _record(
    cfg: BacktestConfig,
    result: EngineResult,
    metrics: "MetricsReport",
    data_root: Path,
    runs_root: Path,
    *,
    metrics_json: dict[str, float | int | None],
    render: bool = False,
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    run_dir = runs_root / f"{stamp}-{cfg.strategy.name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    trades = pl.DataFrame(
        {
            "ts_ns": [e.fill.ts_ns for e in result.fill_events],
            "order_id": [e.fill.order_id for e in result.fill_events],
            "side": [e.fill.side.value for e in result.fill_events],
            "price": [e.fill.price for e in result.fill_events],
            "qty": [e.fill.qty for e in result.fill_events],
            "fee": [e.fill.fee for e in result.fill_events],
            "role": [e.fill.role.value for e in result.fill_events],
            "realized_gross": [e.realized_gross for e in result.fill_events],
            "slippage_cost": [e.slippage_cost for e in result.fill_events],
        }
    )
    trades.write_csv(run_dir / "trades.csv")
    equity = pl.DataFrame(
        {
            "ts_ns": [ts for ts, _ in result.equity_curve],
            "equity": [e for _, e in result.equity_curve],
        }
    )
    equity.write_csv(run_dir / "equity.csv")
    orders = pl.DataFrame(
        {
            "id": [o.id for o in result.orders],
            "side": [o.side.value for o in result.orders],
            "type": [o.type.value for o in result.orders],
            "qty": [o.qty for o in result.orders],
            "limit_price": [o.limit_price for o in result.orders],
            "stop_price": [o.stop_price for o in result.orders],
            "submitted_ns": [o.submitted_ns for o in result.orders],
            "arrive_ns": [o.arrive_ns for o in result.orders],
            "status": [o.status.value for o in result.orders],
            "reject_reason": [o.reject_reason for o in result.orders],
        }
    )
    orders.write_csv(run_dir / "orders.csv")
    trips = pl.DataFrame(
        {
            "entry_ts": [t.entry_ts for t in result.round_trips],
            "exit_ts": [t.exit_ts for t in result.round_trips],
            "side": [t.side for t in result.round_trips],
            "qty": [t.qty for t in result.round_trips],
            "entry_price": [t.entry_price for t in result.round_trips],
            "exit_price": [t.exit_price for t in result.round_trips],
            "gross": [t.gross for t in result.round_trips],
            "fees": [t.fees for t in result.round_trips],
            "slippage": [t.slippage for t in result.round_trips],
            "funding": [t.funding for t in result.round_trips],
            "net": [t.net for t in result.round_trips],
            "hold_ns": [t.hold_ns for t in result.round_trips],
        }
    )
    trips.write_csv(run_dir / "trips.csv")
    summary = {
        "n_bars": result.n_bars,
        "n_fills": len(result.fill_events),
        "final_equity": result.final_equity,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "metrics.json").write_text(json.dumps(metrics_json, indent=2), encoding="utf-8")
    catalog_path = data_root / "catalog.json"
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "seeds": {"latency": cfg.costs.latency.seed},
        "config": cfg.model_dump(mode="json"),
        "data_files": catalog_path.read_text(encoding="utf-8") if catalog_path.is_file() else "{}",
        "engine_version": 1,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if render:
        from tradingv2.report.render import render_report

        render_report(run_dir)
    return run_dir


def _unused() -> None:
    json.dumps({})
