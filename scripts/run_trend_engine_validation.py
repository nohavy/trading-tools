"""Execute the exploratory 60d daily trend candidate and buy-hold on 1m bars."""

import argparse
import datetime as dt
import gc
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from tradingv2.backtest.runner import run_backtest
from tradingv2.research.time_series_trend import summarize_daily_equity_curve

SYMBOLS = ("BTCUSDT", "ETHUSDT")
BASE_CONFIG = Path("configs/research-trend-engine.yaml")
OOS_START = dt.datetime(2023, 7, 1, tzinfo=dt.UTC)
OOS_END = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
OOS_SUBPERIODS = {
    "2023H2": (dt.datetime(2023, 7, 1, tzinfo=dt.UTC), dt.datetime(2024, 1, 1, tzinfo=dt.UTC)),
    "2024": (dt.datetime(2024, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 1, 1, tzinfo=dt.UTC)),
    "2025": (dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
    "2026YTD": (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 9, 1, tzinfo=dt.UTC)),
}


def _ns(value: dt.datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000


def _daily_curve(run_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    equity = pl.read_csv(run_dir / "equity.csv").sort("ts_ns")
    daily = (
        equity.filter(
            (pl.col("ts_ns") >= _ns(OOS_START))
            & (pl.col("ts_ns") <= _ns(OOS_END))
            & (pl.col("ts_ns") % 86_400_000_000_000 == 0)
        )
        .unique(subset=["ts_ns"], keep="last")
        .sort("ts_ns")
    )
    return daily["ts_ns"].to_numpy(), daily["equity"].to_numpy()


def _daily_metrics(run_dir: Path) -> dict[str, Any]:
    timestamps, values = _daily_curve(run_dir)
    return summarize_daily_equity_curve(
        timestamps,
        values,
        start_ns=_ns(OOS_START),
        end_ns=_ns(OOS_END),
        hac_lag=20,
    )


def _equal_weight_portfolio(run_dirs: list[Path]) -> dict[str, Any]:
    if not run_dirs:
        raise ValueError("portfolio needs at least one run")
    curves = [_daily_curve(path) for path in run_dirs]
    timestamps = curves[0][0]
    if any(not np.array_equal(ts, timestamps) for ts, _ in curves[1:]):
        raise ValueError("asset OOS daily marks do not align")
    asset_returns = [values[1:] / values[:-1] - 1.0 for _, values in curves]
    portfolio_returns = np.mean(asset_returns, axis=0)
    portfolio_equity = np.r_[1.0, np.cumprod(1.0 + portfolio_returns)]

    def summarize(start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
        return summarize_daily_equity_curve(
            timestamps,
            portfolio_equity,
            start_ns=_ns(start),
            end_ns=_ns(end),
            hac_lag=20,
        )

    return {
        "full": summarize(OOS_START, OOS_END),
        "subperiods": {
            name: summarize(start, end)
            for name, (start, end) in OOS_SUBPERIODS.items()
        },
    }


def _attach_portfolio_summary(payload: dict[str, Any]) -> None:
    results = payload["results"]
    assets = results.get("assets", results)
    for mode in ("long_flat", "buy_hold"):
        paths = [
            Path(assets[f"{symbol}:{mode}"]["run_dir"])
            for symbol in SYMBOLS
        ]
        results.setdefault("BTC_ETH_equal_weight", {})[mode] = _equal_weight_portfolio(paths)


def _run_one(
    symbol: str, mode: str, *, data_root: Path, runs_root: Path
) -> dict[str, Any]:
    config = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8"))
    config["data"]["symbol"] = symbol
    config["strategy"]["params"]["mode"] = mode
    config["strategy"]["params"]["lookback_days"] = 60
    with tempfile.TemporaryDirectory(prefix="tv2-trend-config-") as tmp:
        cfg_path = Path(tmp) / f"{symbol}-{mode}.yaml"
        cfg_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        run_dir = run_backtest(cfg_path, data_root=data_root, runs_root=runs_root)
    stats = _daily_metrics(run_dir)
    fills = pl.read_csv(run_dir / "trades.csv")
    stats.update(
        {
            "run_dir": str(run_dir),
            "n_fills": fills.height,
            "buys": fills.filter(pl.col("side") == "buy").height,
            "sells": fills.filter(pl.col("side") == "sell").height,
            "fees_usdt": float(fills["fee"].sum() or 0.0),
            "slippage_usdt": float(fills["slippage_cost"].sum() or 0.0),
        }
    )
    del fills
    gc.collect()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--runs-root", type=Path, default=Path("runs/trend-engine-2026-10"))
    parser.add_argument("--out", type=Path, default=Path("data/trend_engine_oos.json"))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument(
        "--summarize-existing",
        action="store_true",
        help="add equal-weight portfolio summaries from run_dir entries without re-running",
    )
    args = parser.parse_args()

    if args.summarize_existing:
        payload = json.loads(args.out.read_text(encoding="utf-8"))
        _attach_portfolio_summary(payload)
        args.out.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
        for mode, summaries in payload["results"]["BTC_ETH_equal_weight"].items():
            stats = summaries["full"]
            print(
                f"equal-weight {mode}: CAGR={stats['cagr']:.1%} "
                f"Sharpe={stats['sharpe']} NW-t={stats['t_stat_nw']:.2f} "
                f"DD={stats['max_drawdown']:.1%}"
            )
        print(f"updated: {args.out}")
        return

    results: dict[str, Any] = {"assets": {}}
    portfolio_run_dirs: dict[str, list[Path]] = {"long_flat": [], "buy_hold": []}
    for symbol in args.symbols.split(","):
        for mode in ("long_flat", "buy_hold"):
            print(f"running {symbol} {mode} on 1m bars...", flush=True)
            stats = _run_one(
                symbol.strip(), mode, data_root=args.data_root, runs_root=args.runs_root
            )
            results["assets"][f"{symbol.strip()}:{mode}"] = stats
            portfolio_run_dirs[mode].append(Path(stats["run_dir"]))
            print(
                f"  CAGR={stats['cagr']:.1%} Sharpe={stats['sharpe']} "
                f"NW-t={stats['t_stat_nw']:.2f} DD={stats['max_drawdown']:.1%} "
                f"fills={stats['n_fills']} fees=${stats['fees_usdt']:.2f}",
                flush=True,
            )

    results["BTC_ETH_equal_weight"] = {
        mode: _equal_weight_portfolio(run_dirs)
        for mode, run_dirs in portfolio_run_dirs.items()
    }
    for mode, summaries in results["BTC_ETH_equal_weight"].items():
        stats = summaries["full"]
        print(
            f"equal-weight {mode}: CAGR={stats['cagr']:.1%} "
            f"Sharpe={stats['sharpe']} NW-t={stats['t_stat_nw']:.2f} "
            f"DD={stats['max_drawdown']:.1%}",
            flush=True,
        )

    payload = {
        "period": {"start": OOS_START.isoformat(), "end": OOS_END.isoformat()},
        "candidate": "60d long_flat; vectorized OOS already explored",
        "costs": "taker 5 bps + slippage 1 bp per side; latency 150±50ms",
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
