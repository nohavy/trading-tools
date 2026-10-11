"""The on-chain whale screen runner (012): flows -> IS/OOS verdict.

Frozen protocol:
  threshold  = q90 of the IS-window POSITIVE net flows (flows, never returns)
  flat exit  = q25 of the same series
  IS  2021-01-01 -> 2023-06-30 ; OOS 2023-07-01 -> 2026-08-31
  fees 10 bps per side (screen convention); hac lag 20
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


def _date_ns(value: str) -> int:
    return int(
        dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=dt.UTC).timestamp()
    ) * 1_000_000_000


def _date_from_ts_ns(ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(ts_ns / 1e9, tz=dt.UTC).strftime("%Y-%m-%d")


def _next_day(day: str) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()


def _closes_by_day(root: Path, symbol: str = "ETHUSDT") -> dict[str, float]:
    files = sorted(
        Path(root / "parquet" / "spot" / "klines" / symbol / "1d").glob("*.parquet")
    )
    df = pl.concat(
        [pl.read_parquet(p, columns=["ts_open_ns", "close"]) for p in files]
    ).sort("ts_open_ns")
    return {
        _date_from_ts_ns(int(ts)): float(close)
        for ts, close in zip(df["ts_open_ns"].to_list(), df["close"].to_list(), strict=True)
    }


def run_screen(
    *, data_root: Path = Path("data"), flows_path: Path | None = None
) -> dict[str, Any]:
    from tradingv2.research.onchain_screen import calibrate_entry_net, screen_net_flows
    from tradingv2.research.time_series_trend import summarize_daily_series

    fp = flows_path or Path("data/onchain/eth_flows_2021-01-01_2026-08-31.parquet")
    flows = pl.read_parquet(fp).sort("day").with_columns(
        pl.col("deposit_eth").cast(pl.Float64),
        pl.col("withdraw_eth").cast(pl.Float64),
    )
    closes_by_day = _closes_by_day(data_root)

    dep: list[float] = []
    wit: list[float] = []
    days: list[str] = []  # decision days: the day whose close starts the position
    for row in flows.to_dicts():
        day_str = str(row["day"])[:10]
        if closes_by_day.get(day_str) is None or closes_by_day.get(_next_day(day_str)) is None:
            continue
        dep.append(float(row["deposit_eth"]))
        wit.append(float(row["withdraw_eth"]))
        days.append(day_str)

    closes: list[float] = [closes_by_day[d] for d in days] + [
        closes_by_day[_next_day(days[-1])]
    ]

    net_flows = np.array(dep) - np.array(wit)
    is_from, is_to = "2021-01-01", "2023-06-30"
    is_mask = np.array([(is_from <= d <= is_to) for d in days])
    oos_from, oos_to = "2023-07-01", "2026-08-31"
    oos_mask = np.array([(oos_from <= d <= oos_to) for d in days])
    entry, flat_exit = calibrate_entry_net(net_flows[7:], is_mask[7:], quantile=0.90)

    screen = screen_net_flows(
        deposits=dep,
        withdraws=wit,
        closes=closes,
        lookback_days=7,
        entry_net_in=entry,
        flat_exit=flat_exit,
        cost_bps=10.0,
    )

    ts_full = np.array([_date_ns(d) for d in days])
    net_full = screen.net_returns[:]
    pos_full = screen.positions[:]

    def _stats(aligned_mask: np.ndarray) -> dict[str, Any]:
        idx_days = aligned_mask  # aligned with days (same length)
        net = net_full[idx_days]
        exposure = np.abs(pos_full[idx_days])
        pos_sel = pos_full[idx_days]
        turnover = np.abs(np.diff(pos_sel, prepend=0.0))
        closes_arr = np.array(closes)
        market_ret = closes_arr[1:] / closes_arr[:-1] - 1.0
        gross = np.abs(pos_sel) * market_ret[idx_days]
        fees = screen.fees_bcps[idx_days] / 1e4
        start = "2021-01-01" if aligned_mask is aligned_is else "2023-07-01"
        end = "2023-06-30" if aligned_mask is aligned_is else "2026-08-31"
        return summarize_daily_series(
            ts_full[idx_days], net, exposure, turnover, gross, fees,
            np.zeros(int(aligned_mask.sum())),
            start_ns=_date_ns(start), end_ns=_date_ns(end), hac_lag=20,
        )

    aligned_is = np.array([(is_from <= d <= is_to) for d in days])
    aligned_oos = np.array([(oos_from <= d <= oos_to) for d in days])
    return {
        "entry_net_in_eth": entry,
        "flat_exit_eth": flat_exit,
        "is": _stats(aligned_is),
        "oos": _stats(aligned_oos),
    }


def main() -> None:
    result = run_screen()
    Path("data/onchain_screen_results.json").write_text(
        json.dumps(result, indent=2, allow_nan=False, default=str), encoding="utf-8"
    )
    print(f"entry={result['entry_net_in_eth']:.1f} ETH  exit={result['flat_exit_eth']:.1f} ETH")
    for label in ("is", "oos"):
        s = result[label]
        print(
            f"{label:>3}: total={s['total_return']:+.1%} t_NW={s['t_stat_nw']} "
            f"DD={s['max_drawdown']:.1%} exposed={s['fraction_exposed']:.0%}"
        )
    print("written: data/onchain_screen_results.json")


if __name__ == "__main__":
    main()
