"""Read the pre-declared 014 verdict ladder from the batch outputs.

Reading order frozen in the brief: solvency (joint margin ratio >= 2, no
liquidation), LUNA replay, drawdown budgets, tail p01, then the statistical
ladder (t, scaling net(F) ~ F x net(1)). The borrow interest is recovered
from the run artifacts: debt(series) = qty x daily close - leg equity.
"""

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

_DAY_NS = 86_400_000_000_000
LUNA_START = dt.datetime(2022, 5, 4, tzinfo=dt.UTC)
LUNA_END = dt.datetime(2022, 5, 20, tzinfo=dt.UTC)
MMR_PERP = 0.004

_spec = importlib.util.spec_from_file_location(
    "carryval", Path(__file__).parent / "run_carry_engine_validation.py"
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["carryval"] = _mod
_spec.loader.exec_module(_mod)


def _ns(value: dt.datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000


def _daily_open_marks(data_root: Path, market: str, symbol: str) -> dict[int, float]:
    """Open prices of the 1d bars keyed by their midnight open timestamp."""
    if market == "spot":
        directory = data_root / "parquet" / "spot" / "klines" / symbol / "1d"
    elif market == "um":
        directory = data_root / "daily" / "um" / symbol
    else:
        raise ValueError(f"unknown market {market}")
    marks: dict[int, float] = {}
    for path in sorted(directory.glob("*.parquet")):
        for row in pl.read_parquet(path).iter_rows(named=True):
            marks[int(row["ts_open_ns"])] = float(row["open"])
    return marks


def _monthly_funding_rate_sums(data_root: Path, symbol: str) -> dict[str, float]:
    """Funding rate sums per month, exact signs, from the fundingRate parquet."""
    directory = data_root / "parquet" / "um" / "fundingRate" / symbol
    sums: dict[str, float] = {}
    for path in sorted(directory.glob("*.parquet")):
        frame = pl.read_parquet(path)
        sums[path.stem[-7:]] = float(frame["rate"].sum())
    return sums


def _leg_run_dirs(runs_root: Path) -> dict[str, dict[str, Path]]:
    """The one backtest run per leg per invocation, keyed symbol -> leg -> dir."""
    legs: dict[str, dict[str, Path]] = {}
    for run_dir in sorted(runs_root.glob("*-*")):
        cfg_path = run_dir / "config.yaml"
        if not cfg_path.is_file():
            continue
        cfg = _mod.yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        symbol = str(cfg["data"]["symbol"])
        leg = "spot" if cfg["strategy"]["name"] == "carry_spot_leg" else "perp"
        legs.setdefault(symbol, {})[leg] = run_dir
    return legs


def _run_balance(run_dir: Path) -> float:
    """The engine account balance as written in the run's own config."""
    cfg = _mod.yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    return float(cfg["account"]["balance"])


def _leg_equity_series(run_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    equity = pl.read_csv(run_dir / "equity.csv").sort("ts_ns")
    daily = equity.filter(pl.col("ts_ns") % _DAY_NS == 0)
    return daily["ts_ns"].to_numpy(), daily["equity"].to_numpy()


def _entry_cost(run_dir: Path) -> tuple[float, float, float]:
    """(qty, fill price, fee) of the single entry fill."""
    fills = pl.read_csv(run_dir / "trades.csv")
    if fills.height != 1:
        raise RuntimeError(f"{run_dir}: expected one fill, got {fills.height}")
    row = fills.row(0, named=True)
    return float(row["qty"]), float(row["price"]), float(row["fee"])


def _max_drawdown(values: np.ndarray) -> float:
    if values.size < 2:
        return float("nan")
    peaks = np.maximum.accumulate(values)
    return float(np.max(1.0 - values / peaks))


def analyze_result(
    result: dict[str, Any],
    runs_root: Path,
    *,
    data_root: Path,
    oos_start_ns: int,
    oos_end_ns: int,
) -> dict[str, Any]:
    symbol = str(result["symbol"])
    legs_by_leg = _leg_run_dirs(runs_root)[symbol]
    qty = float(result["hedge_qty"])

    ts_spot, eq_spot = _leg_equity_series(legs_by_leg["spot"])
    ts_perp, eq_perp = _leg_equity_series(legs_by_leg["perp"])
    ts, combined = _mod.combine_leg_equities(ts_spot, eq_spot, ts_perp, eq_perp)
    keep = (ts >= oos_start_ns) & (ts <= oos_end_ns)
    ts, combined = ts[keep], combined[keep]

    perp_marks = _daily_open_marks(data_root, "um", symbol)
    ratio_ts: list[int] = []
    ratios: list[float] = []
    for i, t in enumerate(ts):
        mark = perp_marks.get(int(t))
        if mark is not None:
            ratio_ts.append(int(t))
            ratios.append(float(combined[i]) / (MMR_PERP * qty * mark))
    ratio_array = np.asarray(ratios) if ratios else np.asarray([float("nan")])
    joint_ratio_min = float(np.min(ratio_array))
    luna_mask = (ts >= _ns(LUNA_START)) & (ts <= _ns(LUNA_END))
    luna_slice = combined[luna_mask] if luna_mask.any() else np.asarray([float("nan")])

    entry_qty, entry_price, entry_fee = _entry_cost(legs_by_leg["spot"])
    balance = _run_balance(legs_by_leg["spot"])
    debt_entry = entry_qty * entry_price + entry_fee - balance
    spot_marks = _daily_open_marks(data_root, "spot", symbol)
    debt_final = qty * spot_marks[int(ts_spot[-1])] - float(eq_spot[-1])
    borrow_interest = debt_final - debt_entry

    return {
        "symbol": symbol,
        "sizing_factor": result["sizing_factor"],
        "oos_total": result["oos"]["full"]["total_return"],
        "oos_cagr": result["oos"]["full"]["cagr"],
        "oos_t": result["oos"]["full"]["t_stat_nw"],
        "oos_dd": result["oos"]["full"]["max_drawdown"],
        "tail_p01": result["tail"]["p01"],
        "joint_ratio_min": joint_ratio_min,
        "joint_ratio_min_date": (
            dt.datetime.fromtimestamp(
                ratio_ts[int(np.argmin(ratio_array))] / 1e9, tz=dt.UTC
            ).date()
            if ratios
            else None
        ),
        "luna_dd": _max_drawdown(luna_slice),
        "window_max_dd": _max_drawdown(combined),
        "spot_leg_min_equity": float(np.min(eq_spot)),
        "perp_leg_min_equity": float(np.min(eq_perp)),
        "borrow_interest": borrow_interest,
        "monthly_funding_rate_sums": _monthly_funding_rate_sums(data_root, symbol),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batches", required=True, help="JSON glob, e.g. data/carry_leverage_oos_f*.json"
    )
    parser.add_argument(
        "--runs-root-pattern", required=True, help="runs root per index, e.g. runs/.../oos-f{index}"
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--oos-start", required=True, help="window start date YYYY-MM-DD")
    parser.add_argument("--oos-end", required=True, help="window end date YYYY-MM-DD")
    args = parser.parse_args()

    start_ns = _ns(dt.datetime.fromisoformat(args.oos_start).replace(tzinfo=dt.UTC))
    end_ns = _ns(dt.datetime.fromisoformat(args.oos_end).replace(tzinfo=dt.UTC))

    rows: list[dict[str, Any]] = []
    for json_path in sorted(Path().glob(args.batches)):
        index = json_path.stem.rsplit("f", 1)[-1]
        runs_root = Path(args.runs_root_pattern.format(index=index))
        if not runs_root.is_dir():
            print(f"skip {json_path}: missing runs root {runs_root}", flush=True)
            continue
        results = json.loads(json_path.read_text(encoding="utf-8"))
        for result in results:
            rows.append(
                analyze_result(
                    result,
                    runs_root,
                    data_root=args.data_root,
                    oos_start_ns=start_ns,
                    oos_end_ns=end_ns,
                )
            )
    print(json.dumps(rows, indent=2, allow_nan=False, default=str))


if __name__ == "__main__":
    main()
