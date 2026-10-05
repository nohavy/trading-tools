"""Validate the always-covered spot/perp carry hedge in the event engine.

For each symbol the runner sizes one hedge quantity from the 2023-06-30
closes, executes the spot leg (cash account) and the perp leg (margin
account, funding) in the 1m event engine, sums the daily equity curves and
reports Newey-West OOS statistics plus execution fidelity checks.
"""

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
from tradingv2.research.cash_carry import combine_leg_equities, hedge_qty
from tradingv2.research.time_series_trend import summarize_daily_equity_curve

SYMBOLS = ("BTCUSDT", "ETHUSDT")
OOS_START = dt.datetime(2023, 7, 1, tzinfo=dt.UTC)
OOS_END = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)  # exclusive bound on midnight marks
DECISION_DATE = dt.date(2023, 6, 30)
DAY_NS = 86_400_000_000_000
OOS_SUBPERIODS = {
    "2023H2": (dt.datetime(2023, 7, 1, tzinfo=dt.UTC), dt.datetime(2024, 1, 1, tzinfo=dt.UTC)),
    "2024": (dt.datetime(2024, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 1, 1, tzinfo=dt.UTC)),
    "2025": (dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
    "2026YTD": (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), dt.datetime(2026, 9, 1, tzinfo=dt.UTC)),
}
COVERAGE_RATIO_MIN = 0.99


def _ns(value: dt.datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000


def _daily_close(
    data_root: Path, directory: Path, symbol: str, filename: str, date: dt.date
) -> float:
    bars = pl.read_parquet(directory / filename)
    boundary = int(
        dt.datetime.combine(date, dt.time(0, 0), tzinfo=dt.UTC).timestamp()
    ) * 1_000_000_000
    rows = (
        bars.sort("ts_open_ns")
        .filter(pl.col("ts_open_ns") <= boundary - 1)
        .tail(1)
    )
    if rows.height != 1:
        raise FileNotFoundError(
            f"no daily bar of {date} for {symbol} under {directory}"
        )
    return float(rows["close"][0])


def _hedge_qty_for(data_root: Path, symbol: str, cfg: dict[str, Any]) -> float:
    spot_close = _daily_close(
        data_root,
        data_root / "parquet" / "spot" / "klines" / symbol / "1d",
        symbol,
        f"{symbol}-1d-{DECISION_DATE.year}-{DECISION_DATE.month:02d}.parquet",
        DECISION_DATE,
    )
    perp_close = _daily_close(
        data_root,
        data_root / "daily" / "um" / symbol,
        symbol,
        f"{symbol}-1d-{DECISION_DATE.year}-{DECISION_DATE.month:02d}.parquet",
        DECISION_DATE,
    )
    return hedge_qty(
        spot_close,
        perp_close,
        float(cfg["total_capital"]),
        float(cfg["hedge_fraction"]),
    )


def _run_leg(
    symbol: str,
    leg_name: str,
    leg_cfg: dict[str, Any],
    qty: float,
    trade_start_ns: int,
    *,
    data_root: Path,
    runs_root: Path,
) -> Path:
    tv2_cfg: dict[str, Any] = {
        "data": {**leg_cfg["data"], "symbol": symbol},
        "account": leg_cfg["account"],
        "costs": leg_cfg["costs"],
        "strategy": {
            "name": leg_cfg["strategy"],
            "params": {"qty": qty, "trade_start_ns": trade_start_ns},
        },
    }
    with tempfile.TemporaryDirectory(prefix="tv2-carry-config-") as tmp:
        cfg_path = Path(tmp) / f"{symbol}-{leg_name}.yaml"
        cfg_path.write_text(yaml.safe_dump(tv2_cfg, sort_keys=False), encoding="utf-8")
        return Path(run_backtest(cfg_path, data_root=data_root, runs_root=runs_root))


def _leg_stats(run_dir: Path) -> dict[str, Any]:
    fills = pl.read_csv(run_dir / "trades.csv")
    orders = pl.read_csv(run_dir / "orders.csv")
    rejected = orders.filter(pl.col("reject_reason") != "")
    return {
        "run_dir": str(run_dir),
        "n_orders": orders.height,
        "n_rejected": rejected.height,
        "n_fills": fills.height,
        "fill_qty": float(fills["qty"].sum()) if fills.height else 0.0,
        "fees_usdt": float(fills["fee"].sum()) if fills.height else 0.0,
        "slippage_usdt": (
            float(fills["slippage_cost"].sum()) if fills.height else 0.0
        ),
    }


def _daily_curve(run_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    equity = pl.read_csv(run_dir / "equity.csv").sort("ts_ns")
    daily = (
        equity.filter(
            (pl.col("ts_ns") >= _ns(OOS_START))
            & (pl.col("ts_ns") < _ns(OOS_END))
            & (pl.col("ts_ns") % DAY_NS == 0)
        )
        .unique(subset=["ts_ns"], keep="last")
        .sort("ts_ns")
    )
    return daily["ts_ns"].to_numpy(), daily["equity"].to_numpy()


def _summarize(ts: np.ndarray, equity: np.ndarray) -> dict[str, Any]:
    def _one(start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
        return summarize_daily_equity_curve(
            ts, equity, start_ns=_ns(start), end_ns=_ns(end), hac_lag=20
        )

    return {
        "full": _one(OOS_START, OOS_END),
        "subperiods": {
            name: _one(start, end) for name, (start, end) in OOS_SUBPERIODS.items()
        },
    }


def run_symbol(data_root: Path, runs_root: Path, config_path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    symbol = str(cfg["symbol"])
    qty = _hedge_qty_for(data_root, symbol, cfg)
    trade_start_ns = int(cfg["trade_start_ns"])

    legs: dict[str, dict[str, Any]] = {}
    curves: list[tuple[np.ndarray, np.ndarray]] = []
    fill_qtys: list[float] = []
    for leg_name in ("spot", "perp"):
        print(f"running {symbol} {leg_name} leg on 1m bars (qty={qty:.8f})...", flush=True)
        run_dir = _run_leg(
            symbol, leg_name, cfg["legs"][leg_name], qty, trade_start_ns,
            data_root=data_root, runs_root=runs_root,
        )
        stats = _leg_stats(run_dir)
        legs[leg_name] = stats
        curves.append(_daily_curve(run_dir))
        fill_qtys.append(stats["fill_qty"])
        print(f"  fills={stats['n_fills']} rejected={stats['n_rejected']}", flush=True)
        del run_dir
        gc.collect()

    if legs["spot"]["n_fills"] != 1 or legs["perp"]["n_fills"] != 1:
        raise RuntimeError(f"{symbol}: expected exactly one fill per leg, got {legs}")
    if legs["spot"]["n_rejected"] != 0 or legs["perp"]["n_rejected"] != 0:
        raise RuntimeError(f"{symbol}: rejected orders present, got {legs}")
    coverage = min(fill_qtys) / max(fill_qtys) if min(fill_qtys) > 0.0 else 0.0
    if coverage < COVERAGE_RATIO_MIN:
        raise RuntimeError(f"{symbol}: legs coverage ratio {coverage:.4f} < {COVERAGE_RATIO_MIN}")

    ts, combined = combine_leg_equities(*curves[0], *curves[1])
    return {
        "symbol": symbol,
        "hedge_qty": qty,
        "coverage_ratio": coverage,
        "legs": legs,
        "oos": _summarize(ts, combined),
        "combined_equity_end_usdt": float(combined[-1]),
        "combined_equity_start_usdt": float(combined[0]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--runs-root", type=Path, default=Path("runs/carry-engine-2026-10"))
    parser.add_argument("--out", type=Path, default=Path("data/carry_engine_oos.json"))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    for symbol in args.symbols.split(","):
        stem = symbol.strip().lower().removesuffix("usdt")
        config_path = Path(f"configs/research-carry-engine-{stem}.yaml")
        results.append(run_symbol(args.data_root, args.runs_root, config_path))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    for result in results:
        stats = result["oos"]["full"]
        substats = result["oos"]["subperiods"]
        subtext = " ".join(
            f"{name}={sub['total_return']:+.1%}" for name, sub in substats.items()
        )
        print(f"\n{result['symbol']} combined OOS: "
              f"total={stats['total_return']:+.2%} CAGR={stats['cagr']:+.2%} "
              f"NW-t={stats['t_stat_nw']} DD={stats['max_drawdown']:.2%}")
        print(f"  subperiods: {subtext}")
        print(f"  equity: {result['combined_equity_start_usdt']:.0f} → "
              f"{result['combined_equity_end_usdt']:.0f} USDT")
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
