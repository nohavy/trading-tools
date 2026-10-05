"""Preregistered neutral spot/perp cash-and-carry screen on BTC/ETH.

Cellules figées dans docs/spot-perp-carry-2026-10-prereg.md avant tout calcul :
cellule primaire taker + benchmark toujours couvert + sensibilités reportées
(seuil 8 bps, fenêtre 3 jours, jambe perp maker). Aucun nouveau seuil n'est
choisi après lecture des résultats.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from tradingv2.research.cash_carry import CarryResult, simulate_cash_and_carry
from tradingv2.research.time_series_trend import summarize_daily_series

SYMBOLS = ("BTCUSDT", "ETHUSDT")
IS_START = "2020-01-01"
IS_END = "2023-06-30"
OOS_START = "2023-07-01"
OOS_END = "2026-08-31"
DAY_NS = 86_400_000_000_000

# Frozen primary cell: entry when the trailing 7d funding sum >= 15 bps and
# basis >= 0; exit when the sum <= 0 or basis <= -20 bps. Costs per side per
# transaction: spot 10 bps + 1 bp slippage, perp taker 5 bps + 1 bp.
PRIMARY: dict[str, Any] = {
    "mode": "filtered",
    "lookback_days": 7,
    "entry_funding_sum": 0.0015,
    "exit_funding_sum": 0.0,
    "entry_basis": 0.0,
    "exit_basis": -0.002,
    "spot_cost_bps": 10.0 + 1.0,
    "perp_cost_bps": 5.0 + 1.0,
}
# Disclosed sensitivities and the always-covered benchmark; never used to
# select or retune the primary cell.
SENSITIVITIES: list[dict[str, Any]] = [
    {**PRIMARY, "label": "primary_15bps_7d", "verdict_cell": True},
    {**PRIMARY, "label": "benchmark_always_covered", "mode": "always"},
    {**PRIMARY, "label": "sens_threshold_8bps", "entry_funding_sum": 0.0008},
    {**PRIMARY, "label": "sens_window_3d", "lookback_days": 3},
    {**PRIMARY, "label": "sens_perp_maker", "perp_cost_bps": 2.0 + 1.0},
]


def _date_ns(value: str) -> int:
    day = dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(day.timestamp()) * 1_000_000_000


def _load_symbol(
    root: Path, symbol: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return spot/perp daily closes, funding settlements and aligned timestamps."""
    spot_dir = root / "parquet" / "spot" / "klines" / symbol / "1d"
    perp_dir = root / "daily" / "um" / symbol
    funding_dir = root / "parquet" / "um" / "fundingRate" / symbol
    spot_files = sorted(spot_dir.glob("*.parquet"))
    perp_files = sorted(perp_dir.glob("*.parquet"))
    funding_files = sorted(funding_dir.glob("*.parquet"))
    if not spot_files:
        raise FileNotFoundError(f"no spot 1d klines under {spot_dir}")
    if not perp_files:
        raise FileNotFoundError(f"no perpetual 1d klines under {perp_dir}")
    if not funding_files:
        raise FileNotFoundError(f"no funding history under {funding_dir}")

    spot = pl.concat([pl.read_parquet(path) for path in spot_files]).sort("ts_open_ns")
    perp = pl.concat([pl.read_parquet(path) for path in perp_files]).sort("ts_open_ns")
    funding = pl.concat([pl.read_parquet(path) for path in funding_files]).sort("ts_ns")
    if spot["ts_open_ns"].n_unique() != spot.height:
        raise ValueError(f"duplicate spot daily bars for {symbol}")
    if perp["ts_open_ns"].n_unique() != perp.height:
        raise ValueError(f"duplicate perpetual daily bars for {symbol}")
    if funding["ts_ns"].n_unique() != funding.height:
        raise ValueError(f"duplicate funding settlements for {symbol}")

    spot_ts = spot["ts_open_ns"].to_numpy()
    perp_ts = perp["ts_open_ns"].to_numpy()
    if not np.array_equal(spot_ts, perp_ts):
        raise ValueError(f"spot and perpetual daily timestamps do not align for {symbol}")
    return (
        spot_ts,
        spot["close"].to_numpy(),
        perp["close"].to_numpy(),
        funding["ts_ns"].to_numpy(),
        funding["rate"].to_numpy(),
        funding["interval_hours"].to_numpy(),
    )


def _turnover(position: np.ndarray) -> np.ndarray:
    """Entries plus exits per interval, expressed in round events."""
    return np.abs(np.diff(position, prepend=0.0))


def _periods(
    ts_ns: np.ndarray,
    result: CarryResult,
) -> dict[str, dict[str, float | int | None]]:
    exposure = np.abs(result.position)
    turnover = _turnover(result.position)

    def _summarize(start: int | None, end: int | None) -> dict[str, float | int | None]:
        return summarize_daily_series(
            ts_ns,
            result.net_returns,
            exposure,
            turnover,
            result.price_returns,
            result.fee_returns,
            result.funding_returns,
            start_ns=start,
            end_ns=end,
            hac_lag=20,
        )

    return {
        "is": _summarize(_date_ns(IS_START), _date_ns(IS_END)),
        "oos": _summarize(_date_ns(OOS_START), _date_ns(OOS_END)),
    }


def _portfolio_series(
    results: list[CarryResult],
) -> tuple[np.ndarray, CarryResult]:
    timestamps = results[0].ts_ns
    if any(not np.array_equal(item.ts_ns, timestamps) for item in results[1:]):
        raise ValueError("carry results must share aligned decision timestamps")

    def _mean(field: str) -> np.ndarray:
        return np.mean([getattr(item, field) for item in results], axis=0)

    position = _mean("position")
    portfolio = CarryResult(
        ts_ns=timestamps,
        position=position,
        price_returns=_mean("price_returns"),
        funding_returns=_mean("funding_returns"),
        fee_returns=_mean("fee_returns"),
        net_returns=_mean("net_returns"),
    )
    return timestamps, portfolio


def run_study(data_root: Path) -> list[dict[str, Any]]:
    histories = {symbol: _load_symbol(data_root, symbol) for symbol in SYMBOLS}
    reference_ts = histories[SYMBOLS[0]][0]
    for _symbol, history in histories.items():
        if not np.array_equal(history[0], reference_ts):
            raise ValueError(f"daily timestamps do not align across {SYMBOLS}")
    funding_intervals = {
        symbol: float(np.unique(history[5]).max()) for symbol, history in histories.items()
    }

    rows: list[dict[str, Any]] = []
    for cell in SENSITIVITIES:
        params = {key: cell[key] for key in PRIMARY}
        results: list[CarryResult] = []
        for symbol, (ts, spot, perp, funding_ts, rates, _) in histories.items():
            result = simulate_cash_and_carry(
                ts, spot, perp, funding_ts, rates,
                lookback_days=params["lookback_days"],
                entry_funding_sum=params["entry_funding_sum"],
                exit_funding_sum=params["exit_funding_sum"],
                entry_basis=params["entry_basis"],
                exit_basis=params["exit_basis"],
                spot_cost_bps=params["spot_cost_bps"],
                perp_cost_bps=params["perp_cost_bps"],
                mode=params["mode"],
            )
            results.append(result)
            rows.append(
                {
                    "label": cell["label"],
                    "scope": symbol,
                    "verdict_cell": bool(cell.get("verdict_cell", False)),
                    "params": {**params, "max_funding_interval_hours": funding_intervals[symbol]},
                    "periods": _periods(result.ts_ns, result),
                }
            )
        ts, portfolio = _portfolio_series(results)
        rows.append(
            {
                "label": cell["label"],
                "scope": "BTC_ETH_equal_weight",
                "verdict_cell": bool(cell.get("verdict_cell", False)),
                "params": params,
                "periods": _periods(ts, portfolio),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("data/spot_perp_carry_results.json"))
    args = parser.parse_args()
    rows = run_study(args.data_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2, allow_nan=False), encoding="utf-8")
    for row in rows:
        oos = row["periods"]["oos"]
        is_stats = row["periods"]["is"]
        verdict_tag = " *VERDICT*" if row["verdict_cell"] else ""
        print(
            f"{row['label']:<26} {row['scope']:<20} "
            f"IS CAGR={is_stats['cagr']!s:>9} OOS total={oos['total_return']!s:>9} "
            f"OOS CAGR={oos['cagr']!s:>9} OOS t_NW={oos['t_stat_nw']!s:>7} "
            f"OOS DD={oos['max_drawdown']!s:>8} "
            f"exposed={oos['fraction_exposed']!s:>7} "
            f"fees={oos['fees_bps']!s:>8} funding={oos['funding_bps']!s:>9}{verdict_tag}"
        )
    print(f"written: {args.out}")


if __name__ == "__main__":
    main()
