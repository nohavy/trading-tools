"""One-shot September 2026 holdout for the frozen 60d long-flat candidate."""

import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from tradingv2.backtest.runner import run_backtest
from tradingv2.backtest.validate import read_holdout_attempts
from tradingv2.research.time_series_trend import (
    holdout_screen,
    summarize_daily_equity_curve,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT")
BASE_CONFIG = Path("configs/research-trend-holdout-2026-09.yaml")
HOLDOUT_START = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
HOLDOUT_END = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
HOLDOUT_COUNTER = Path("data/holdout_attempts.json")
STARTED_MARKER = Path("data/trend-holdout-2026-09.started.json")
RESULT_PATH = Path("data/trend-holdout-2026-09.json")


def _ns(value: dt.datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000


def _oos_curve(run_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    equity = pl.read_csv(run_dir / "equity.csv").sort("ts_ns")
    daily = (
        equity.filter(
            (pl.col("ts_ns") >= _ns(HOLDOUT_START))
            & (pl.col("ts_ns") <= _ns(HOLDOUT_END))
            & (pl.col("ts_ns") % 86_400_000_000_000 == 0)
        )
        .unique(subset=["ts_ns"], keep="last")
        .sort("ts_ns")
    )
    return daily["ts_ns"].to_numpy(), daily["equity"].to_numpy()


def _run_config(
    symbol: str, mode: str, *, runs_root: Path, data_root: Path
) -> tuple[Path, dict[str, Any]]:
    config = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8"))
    config["data"]["symbol"] = symbol
    config["strategy"]["params"]["mode"] = mode
    config["strategy"]["params"]["lookback_days"] = 60
    with tempfile.TemporaryDirectory(prefix="tv2-holdout-config-") as tmp:
        cfg_path = Path(tmp) / f"{symbol}-{mode}.yaml"
        cfg_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        run_dir = run_backtest(cfg_path, data_root=data_root, runs_root=runs_root)

    timestamps, levels = _oos_curve(run_dir)
    summary = summarize_daily_equity_curve(
        timestamps,
        levels,
        start_ns=_ns(HOLDOUT_START),
        end_ns=_ns(HOLDOUT_END),
        hac_lag=5,
    )
    fills = pl.read_csv(run_dir / "trades.csv")
    orders = pl.read_csv(run_dir / "orders.csv")
    summary.update(
        {
            "run_dir": str(run_dir),
            "fills": fills.height,
            "fees_usdt": float(fills["fee"].sum() or 0.0),
            "slippage_usdt": float(fills["slippage_cost"].sum() or 0.0),
            "rejected_exits": orders.filter(
                (pl.col("side") == "sell") & (pl.col("status") == "rejected")
            ).height,
        }
    )
    return run_dir, summary


def _portfolio(run_dirs: list[Path]) -> dict[str, Any]:
    curves = [_oos_curve(path) for path in run_dirs]
    timestamps = curves[0][0]
    if any(not np.array_equal(ts, timestamps) for ts, _ in curves[1:]):
        raise ValueError("BTC and ETH holdout daily marks do not align")
    daily_returns = np.mean([values[1:] / values[:-1] - 1.0 for _, values in curves], axis=0)
    portfolio_equity = np.r_[1.0, np.cumprod(1.0 + daily_returns)]
    return summarize_daily_equity_curve(
        timestamps,
        portfolio_equity,
        start_ns=_ns(HOLDOUT_START),
        end_ns=_ns(HOLDOUT_END),
        hac_lag=5,
    )


def _check_preregistered_inputs(data_root: Path) -> None:
    if read_holdout_attempts(HOLDOUT_COUNTER) != 2:
        raise RuntimeError("expected exactly two pre-registered September holdout runs")
    if STARTED_MARKER.exists() or RESULT_PATH.exists():
        raise RuntimeError("September holdout has already been opened; refusing a rerun")
    for symbol in SYMBOLS:
        daily_dir = data_root / "parquet" / "um" / "klines" / symbol / "1m"
        daily_files = [
            daily_dir / f"{symbol}-1m-2026-09-{day:02d}.parquet"
            for day in range(1, 31)
        ]
        funding_file = (
            data_root
            / "parquet"
            / "um"
            / "fundingRate"
            / symbol
            / f"{symbol}-fundingRate-2026-09.parquet"
        )
        for relative in [*daily_files, funding_file]:
            if not relative.is_file():
                raise FileNotFoundError(f"holdout input missing: {relative}")


def main() -> None:
    data_root = Path("data")
    runs_root = Path("runs/trend-holdout-2026-09")
    _check_preregistered_inputs(data_root)
    STARTED_MARKER.write_text(
        json.dumps(
            {
                "registered_attempts": 2,
                "started_at": dt.datetime.now(dt.UTC).isoformat(),
                "strategy": "60d long_flat, frozen",
                "holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    asset_results: dict[str, dict[str, Any]] = {}
    run_paths: dict[str, list[Path]] = {"long_flat": [], "buy_hold": []}
    for symbol in SYMBOLS:
        for mode in ("long_flat", "buy_hold"):
            print(f"holdout run {symbol} {mode}", flush=True)
            run_dir, summary = _run_config(
                symbol, mode, runs_root=runs_root, data_root=data_root
            )
            asset_results[f"{symbol}:{mode}"] = summary
            run_paths[mode].append(run_dir)
            print(
                f"  return={summary['total_return']:.2%} "
                f"fills={summary['fills']} fees=${summary['fees_usdt']:.2f} "
                f"rejected exits={summary['rejected_exits']}",
                flush=True,
            )

    portfolio = {mode: _portfolio(paths) for mode, paths in run_paths.items()}
    candidate_returns = {
        symbol: asset_results[f"{symbol}:long_flat"]["total_return"]
        for symbol in SYMBOLS
    }
    rejected_exits = sum(
        asset_results[f"{symbol}:long_flat"]["rejected_exits"] for symbol in SYMBOLS
    )
    screen = holdout_screen(
        candidate_returns,
        candidate_portfolio_return=portfolio["long_flat"]["total_return"],
        benchmark_portfolio_return=portfolio["buy_hold"]["total_return"],
        rejected_exits=rejected_exits,
    )
    payload = {
        "holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
        "registered_attempts": 2,
        "candidate": "60d long_flat, frozen before download",
        "asset_results": asset_results,
        "portfolio_results": portfolio,
        "preregistered_screen": screen,
        "paper_live_go": False,
    }
    RESULT_PATH.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(f"holdout screen: {screen['candidate_survives_month']}")
    print(f"written: {RESULT_PATH}")


if __name__ == "__main__":
    main()
