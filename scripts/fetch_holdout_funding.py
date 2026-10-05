"""Fetch September UM funding settlements from the official Binance REST API.

The September monthly archive was not published when the holdout was opened;
this script stores the official historical funding-rate endpoint response using
the same Parquet columns the Engine reads. Run only after preregistration.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

from tradingv2.backtest.validate import read_holdout_attempts
from tradingv2.data.store import Catalog, CatalogEntry, write_parquet

SYMBOLS = ("BTCUSDT", "ETHUSDT")
API = "https://fapi.binance.com/fapi/v1/fundingRate"
START_MS = 1_788_220_800_000  # 2026-09-01T00:00:00Z
END_MS = 1_790_812_799_999  # 2026-09-30T23:59:59.999Z
DATA_ROOT = Path("data")
COUNTER = DATA_ROOT / "holdout_attempts.json"


def _fetch(client: httpx.Client, symbol: str) -> tuple[list[dict[str, object]], bytes]:
    rows: list[dict[str, object]] = []
    raw_pages: list[bytes] = []
    cursor = START_MS
    while cursor <= END_MS:
        response = client.get(
            API,
            params={"symbol": symbol, "startTime": cursor, "endTime": END_MS, "limit": 1000},
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError(f"unexpected funding API payload for {symbol}: {type(page)}")
        raw_pages.append(response.content)
        if not page:
            break
        rows.extend(row for row in page if START_MS <= int(row["fundingTime"]) <= END_MS)
        last_ms = max(int(row["fundingTime"]) for row in page)
        if last_ms >= END_MS or len(page) < 1000:
            break
        cursor = last_ms + 1
    return rows, b"\n".join(raw_pages)


def main() -> None:
    if read_holdout_attempts(COUNTER) != 2:
        raise RuntimeError("expected two preregistered holdout runs before funding access")
    output_paths = [
        DATA_ROOT / "parquet" / "um" / "fundingRate" / symbol
        / f"{symbol}-fundingRate-2026-09.parquet"
        for symbol in SYMBOLS
    ]
    if any(path.exists() for path in output_paths):
        raise RuntimeError("September funding output already exists; refusing an implicit rerun")

    with httpx.Client(timeout=30.0) as client:
        for symbol, output in zip(SYMBOLS, output_paths, strict=True):
            rows, raw = _fetch(client, symbol)
            if not rows:
                raise RuntimeError(f"no September funding settlements returned for {symbol}")
            rows.sort(key=lambda row: int(row["fundingTime"]))
            times_ms = [int(row["fundingTime"]) for row in rows]
            if len(set(times_ms)) != len(times_ms):
                raise ValueError(f"duplicate funding timestamps for {symbol}")
            intervals = [
                max(1, int(round((times_ms[i] - times_ms[i - 1]) / 3_600_000)))
                for i in range(1, len(times_ms))
            ]
            first_interval = intervals[0] if intervals else 8
            intervals.insert(0, first_interval)
            frame = pl.DataFrame(
                {
                    "ts_ns": [time_ms * 1_000_000 for time_ms in times_ms],
                    "interval_hours": intervals,
                    "rate": [float(row["fundingRate"]) for row in rows],
                },
                schema={
                    "ts_ns": pl.Int64,
                    "interval_hours": pl.UInt32,
                    "rate": pl.Float64,
                },
            )
            if not frame["rate"].is_finite().all():
                raise ValueError(f"non-finite funding rate for {symbol}")

            relative = output.relative_to(DATA_ROOT).as_posix()
            write_parquet(frame, output)
            digest = hashlib.sha256(raw).hexdigest()
            catalog = Catalog.load(DATA_ROOT)
            catalog.upsert(
                CatalogEntry(
                    path=relative,
                    kind="fundingRate",
                    market="um",
                    symbol=symbol,
                    interval=None,
                    source_url=API,
                    sha256=digest,
                    n_rows=frame.height,
                    ts_min_ns=int(frame["ts_ns"].min()),
                    ts_max_ns=int(frame["ts_ns"].max()),
                    converted_at=datetime.now(UTC).isoformat(),
                )
            )
            print(
                f"{symbol}: {frame.height} funding settlements "
                f"{frame['ts_ns'].min()}..{frame['ts_ns'].max()} -> {output}",
                flush=True,
            )


if __name__ == "__main__":
    main()
