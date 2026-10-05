"""Research daily time-series trend on Binance UM BTC/ETH with actual funding."""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tradingv2.research.time_series_trend import (
    TrendResult,
    funding_mark_prices,
    simulate_time_series_trend,
    summarize_equal_weight_portfolio,
    summarize_trend,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT")
LOOKBACKS = (20, 60, 90, 180, 252)
MODES = ("long_short", "long_flat")
ALL_MODES = (*MODES, "buy_hold")
IS_START = "2020-01-01"
IS_END = "2023-06-30"
OOS_START = "2023-07-01"
OOS_END = "2026-08-31"
OOS_SUBPERIODS = {
    "2023H2": ("2023-07-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
    "2026YTD": ("2026-01-01", "2026-08-31"),
}
MAX_LOOKBACK = max(LOOKBACKS)
DAY_NS = 86_400_000_000_000


def _date_ns(value: str) -> int:
    day = dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(day.timestamp()) * 1_000_000_000


def _load_symbol(
    root: Path, symbol: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    daily_dir = root / "daily" / "um" / symbol
    funding_dir = root / "parquet" / "um" / "fundingRate" / symbol
    minute_dir = root / "parquet" / "um" / "klines" / symbol / "1m"
    daily_files = sorted(daily_dir.glob("*.parquet"))
    funding_files = sorted(funding_dir.glob("*.parquet"))
    minute_files = sorted(minute_dir.glob("*.parquet"))
    if not daily_files:
        raise FileNotFoundError(f"no daily klines under {daily_dir}")
    if not funding_files:
        raise FileNotFoundError(f"no funding history under {funding_dir}")
    if not minute_files:
        raise FileNotFoundError(f"no 1m bars under {minute_dir}")

    bars = pl.concat([pl.read_parquet(path) for path in daily_files]).sort("ts_open_ns")
    funding = pl.concat([pl.read_parquet(path) for path in funding_files]).sort("ts_ns")
    minute = pl.concat(
        [pl.read_parquet(path, columns=["ts_open_ns", "open", "close"]) for path in minute_files]
    ).sort("ts_open_ns")
    if bars["ts_open_ns"].n_unique() != bars.height:
        raise ValueError(f"duplicate daily bars for {symbol}")
    if funding["ts_ns"].n_unique() != funding.height:
        raise ValueError(f"duplicate funding settlements for {symbol}")
    if minute["ts_open_ns"].n_unique() != minute.height:
        raise ValueError(f"duplicate 1m bars for {symbol}")
    funding_prices = funding_mark_prices(
        funding["ts_ns"].to_numpy(),
        minute["ts_open_ns"].to_numpy(),
        minute["open"].to_numpy(),
        minute["close"].to_numpy(),
    )
    return (
        bars["ts_open_ns"].to_numpy(),
        bars["close"].to_numpy(),
        funding["ts_ns"].to_numpy(),
        funding["rate"].to_numpy(),
        funding_prices,
    )


def _periods(
    result: TrendResult, valid_start_ns: int
) -> dict[str, dict[str, float | int | None]]:
    periods = {
        "full": summarize_trend(result, start_ns=valid_start_ns, hac_lag=20),
        "is": summarize_trend(
            result,
            start_ns=max(valid_start_ns, _date_ns(IS_START)),
            end_ns=_date_ns(IS_END),
            hac_lag=20,
        ),
        "oos": summarize_trend(
            result,
            start_ns=_date_ns(OOS_START),
            end_ns=_date_ns(OOS_END),
            hac_lag=20,
        ),
    }
    for name, (start, end) in OOS_SUBPERIODS.items():
        periods[name] = summarize_trend(
            result, start_ns=_date_ns(start), end_ns=_date_ns(end), hac_lag=20
        )
    return periods


def _portfolio_periods(
    results: list[TrendResult], valid_start_ns: int
) -> dict[str, dict[str, float | int | None]]:
    periods = {
        "full": summarize_equal_weight_portfolio(
            results, start_ns=valid_start_ns, hac_lag=20
        ),
        "is": summarize_equal_weight_portfolio(
            results,
            start_ns=max(valid_start_ns, _date_ns(IS_START)),
            end_ns=_date_ns(IS_END),
            hac_lag=20,
        ),
        "oos": summarize_equal_weight_portfolio(
            results,
            start_ns=_date_ns(OOS_START),
            end_ns=_date_ns(OOS_END),
            hac_lag=20,
        ),
    }
    for name, (start, end) in OOS_SUBPERIODS.items():
        periods[name] = summarize_equal_weight_portfolio(
            results,
            start_ns=_date_ns(start),
            end_ns=_date_ns(end),
            hac_lag=20,
        )
    return periods


def run_study(data_root: Path) -> list[dict[str, Any]]:
    histories = {symbol: _load_symbol(data_root, symbol) for symbol in SYMBOLS}
    reference_ts = histories[SYMBOLS[0]][0]
    for symbol, history in histories.items():
        if not np.array_equal(history[0], reference_ts):
            raise ValueError(f"daily timestamps do not align for {symbol}")
    if reference_ts.size <= MAX_LOOKBACK + 1:
        raise ValueError("not enough daily history for the longest lookback")
    valid_start_ns = int(reference_ts[MAX_LOOKBACK])

    rows: list[dict[str, Any]] = []
    portfolio_candidates: dict[str, list[dict[str, Any]]] = {"maker": [], "taker": []}
    cost_scenarios = {"maker": (2.0, 1.0), "taker": (5.0, 1.0)}
    for cost_name, (fee_bps, slippage_bps) in cost_scenarios.items():
        for lookback in LOOKBACKS:
            for mode in ALL_MODES:
                by_symbol: dict[str, TrendResult] = {}
                for symbol, (ts, close, funding_ts, rates, mark_prices) in histories.items():
                    result = simulate_time_series_trend(
                        ts,
                        close,
                        funding_ts,
                        rates,
                        lookback_days=lookback,
                        mode=mode,
                        fee_per_side_bps=fee_bps,
                        slippage_per_side_bps=slippage_bps,
                        funding_prices=mark_prices,
                    )
                    by_symbol[symbol] = result
                    rows.append(
                        {
                            "scope": symbol,
                            "cost": cost_name,
                            "fee_per_side_bps": fee_bps,
                            "slippage_per_side_bps": slippage_bps,
                            "mode": mode,
                            "lookback_days": lookback,
                            "periods": _periods(result, valid_start_ns),
                        }
                    )

                portfolio = [by_symbol[symbol] for symbol in SYMBOLS]
                portfolio_row: dict[str, Any] = {
                    "scope": "BTC_ETH_equal_weight",
                    "cost": cost_name,
                    "fee_per_side_bps": fee_bps,
                    "slippage_per_side_bps": slippage_bps,
                    "mode": mode,
                    "lookback_days": lookback,
                    "periods": _portfolio_periods(portfolio, valid_start_ns),
                }
                rows.append(portfolio_row)
                if mode in MODES:
                    portfolio_candidates[cost_name].append(portfolio_row)

        # Select only on the chronological IS Sharpe; OOS is then disclosed.
        eligible = [
            row for row in portfolio_candidates[cost_name]
            if row["periods"]["is"]["sharpe"] is not None
        ]
        selected = max(eligible, key=lambda row: float(row["periods"]["is"]["sharpe"]))
        selected["selected_on_is"] = True
        selected["selection_metric"] = "portfolio IS Sharpe"

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("data/time_series_trend_results.json"))
    args = parser.parse_args()
    rows = run_study(args.data_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2, allow_nan=False), encoding="utf-8")
    for row in rows:
        if row["scope"] != "BTC_ETH_equal_weight":
            continue
        periods = row["periods"]
        is_stats = periods["is"]
        oos_stats = periods["oos"]
        selected = " *IS SELECTED*" if row.get("selected_on_is") else ""
        print(
            f"{row['cost']:>5} lb={row['lookback_days']:>3} {row['mode']:<10} "
            f"IS Sharpe={is_stats['sharpe']!s:>7} IS CAGR={is_stats['cagr']!s:>8} "
            f"OOS Sharpe={oos_stats['sharpe']!s:>7} OOS CAGR={oos_stats['cagr']!s:>8} "
            f"OOS DD={oos_stats['max_drawdown']!s:>7}{selected}"
        )
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
