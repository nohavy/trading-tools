"""Cross-sectional momentum study on UM daily klines (Way A).

Loads the daily 1d archive (per-month Parquet, includes delisted symbols),
builds a dates x assets close matrix, applies a per-date liquidity filter
(dropping the illiquid tail so the study is tradeable), then measures the
top-minus-bottom quintile spread over a lookback/horizon grid.

Survivorship: symbols come from the archive listing, not from the live
exchangeInfo, so delisted perps stay in the cross-section.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import polars as pl

from tradingv2.research.cross_section import (
    QuintileResult,
    liquidity_filter,
    newey_west_tstat,
    quintile_spreads,
)

DAILY = Path("data/daily/um")
MATRIX = Path("data/daily_close_matrix.parquet")
DAILY_NS = 86_400_000_000_000


def date_ns(text: str) -> int:
    """UTC midnight of a YYYY-MM-DD string, in nanoseconds."""
    day = dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(day.timestamp()) * 1_000_000_000


def load_long() -> pl.DataFrame:
    """All daily bars as (ts_open_ns, symbol, close, quote_volume)."""
    files = sorted(str(p) for p in DAILY.rglob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet under {DAILY}; run scripts/fetch_daily.py first")
    frame = pl.read_parquet(files, columns=["ts_open_ns", "close", "quote_volume"])
    symbol = np.array([Path(f).parent.name for f in files], dtype=object)
    return (
        frame.with_columns(
            pl.Series("symbol", np.repeat(symbol, frame.height)),
        )
        .select("ts_open_ns", "symbol", "close", "quote_volume")
        .unique(subset=["ts_open_ns", "symbol"], keep="first")
        .sort(["ts_open_ns", "symbol"])
    )


def build_matrix(long: pl.DataFrame) -> pl.DataFrame:
    """Wide close matrix (one row per day, one column per symbol)."""
    matrix = long.pivot(on="symbol", index="ts_open_ns", values="close").sort("ts_open_ns")
    matrix.write_parquet(MATRIX)
    return matrix




def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def describe(result: QuintileResult, horizon: int, cost: float) -> dict[str, object]:
    series = result.spread_series or []
    return {
        "lookback_days": None,
        "horizon_days": horizon,
        "round_trip_bps": cost,
        "n_dates": result.n_dates,
        "n_assets": result.n_assets,
        "top_mean_bps": _r(result.top_mean_bps),
        "bottom_mean_bps": _r(result.bottom_mean_bps),
        "spread_mean_bps": _r(result.spread_mean_bps),
        "spread_median_bps": _r(result.spread_median_bps),
        "hit_rate": _r(result.spread_hit_rate, 3),
        "t_stat_nw": _r(newey_west_tstat(series, max(1, horizon - 1))) if series else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookbacks", default="7,14,30,60,90")
    parser.add_argument("--horizons", default="1,3,7,14")
    parser.add_argument("--costs", default="4.0,10.0", help="round-trip bps per rebalance")
    parser.add_argument("--liquidity-quantile", type=float, default=0.2)
    parser.add_argument("--from", dest="start", default="", help="YYYY-MM-DD inclusive")
    parser.add_argument("--to", dest="end", default="", help="YYYY-MM-DD inclusive")
    parser.add_argument("--out", default="data/cross_section_results.json")
    args = parser.parse_args()

    long = load_long()
    if args.start:
        long = long.filter(pl.col("ts_open_ns") >= date_ns(args.start))
    if args.end:
        long = long.filter(pl.col("ts_open_ns") <= date_ns(args.end))
    print(f"bars: {long.height:,} symbols: {long['symbol'].n_unique()} "
          f"days: {long['ts_open_ns'].n_unique()}", flush=True)

    filtered = liquidity_filter(long, quantile=args.liquidity_quantile)
    print(f"after liquidity filter: {filtered.height:,} bars, "
          f"{filtered['symbol'].n_unique()} symbols", flush=True)

    rows: list[dict[str, object]] = []
    costs = [float(c) for c in args.costs.split(",")]
    for horizon in (int(h) for h in args.horizons.split(",")):
        for lookback in (int(x) for x in args.lookbacks.split(",")):
            for cost in costs:
                result = quintile_spreads(
                    filtered, lookback_days=lookback, horizon_days=horizon,
                    round_trip_bps=cost,
                )
                row = describe(result, horizon, cost)
                row["lookback_days"] = lookback
                row["from"] = args.start or "start"
                row["to"] = args.end or "end"
                rows.append(row)
                print(f"  lb={lookback:>3} h={horizon:>2} cost={cost:>4.1f} "
                      f"n={result.n_dates:>4} top={row['top_mean_bps']} "
                      f"spread={row['spread_mean_bps']} hit={row['hit_rate']} "
                      f"t={row['t_stat_nw']}", flush=True)

    Path(args.out).write_text(json.dumps(rows, indent=1))
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
