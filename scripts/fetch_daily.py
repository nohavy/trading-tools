"""Download the manifest of UM 1d monthly klines into per-month Parquet files.

Resumable: an existing non-empty Parquet is skipped, so the job can be
re-launched after an interruption. Checksums are verified like the main
data pipeline does.
"""

import argparse
import hashlib
import io
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import httpx

from tradingv2.data.convert import parse_klines_csv

logger = logging.getLogger("fetch_daily")
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
MANIFEST = Path("data/daily_manifest.json")
OUT_DIR = Path("data/daily/um")


def target(symbol: str, month: str) -> Path:
    return OUT_DIR / symbol / f"{symbol}-1d-{month}.parquet"


def fetch_month(client: httpx.Client, symbol: str, month: str, retries: int = 4) -> str:
    """Download one monthly 1d archive and store it as Parquet. Returns a status."""
    dest = target(symbol, month)
    if dest.is_file() and dest.stat().st_size > 0:
        return "cached"
    url = f"{BASE}/{symbol}/1d/{symbol}-1d-{month}.zip"
    for attempt in range(retries):
        try:
            checksum = client.get(url + ".CHECKSUM")
            if checksum.status_code == 404:
                return "absent"
            checksum.raise_for_status()
            expected = checksum.text.split()[0].lower()
            body = client.get(url)
            body.raise_for_status()
            if hashlib.sha256(body.content).hexdigest() != expected:
                raise ValueError("checksum mismatch")
            with ZipFile(io.BytesIO(body.content)) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")]
                if len(names) != 1:
                    raise ValueError(f"expected 1 member, got {names}")
                csv_data = archive.read(names[0])
            frame = parse_klines_csv(csv_data, file=url)
            if frame.is_empty():
                return "empty"
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_suffix(".parquet.part")
            frame.write_parquet(part)
            part.replace(dest)
            return "ok"
        except (httpx.HTTPError, ValueError, BadZipFile) as exc:
            if attempt == retries - 1:
                return f"error:{exc}"
            time.sleep(1.0 * (2**attempt))
    return "error:unreachable"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0, help="only N symbols (smoke test)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    manifest = json.loads(MANIFEST.read_text())
    symbols = sorted(manifest)
    if args.limit:
        symbols = symbols[: args.limit]
    jobs = [(s, m) for s in symbols for m in manifest[s]]
    print(f"{len(symbols)} symbols, {len(jobs)} monthly files", flush=True)

    counts: dict[str, int] = {}
    failed: list[tuple[str, str]] = []
    done = 0
    started = time.monotonic()
    limits = httpx.Limits(max_connections=args.workers * 2, max_keepalive_connections=args.workers)
    with httpx.Client(timeout=60.0, limits=limits) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(fetch_month, client, s, m): (s, m) for s, m in jobs}
            for future in as_completed(futures):
                symbol, month = futures[future]
                status = future.result()
                counts[status.split(":")[0]] = counts.get(status.split(":")[0], 0) + 1
                if status.startswith("error"):
                    failed.append((symbol, month, status))
                    logger.warning("FAIL %s %s %s", symbol, month, status)
                done += 1
                if done % 1000 == 0:
                    rate = done / (time.monotonic() - started)
                    print(f"  {done}/{len(jobs)} ({rate:.0f}/s) {counts}", flush=True)

    print(f"done in {time.monotonic() - started:.0f}s: {counts}")
    if failed:
        log = Path("data/daily_failed.json")
        log.write_text(json.dumps(failed, indent=1))
        print(f"{len(failed)} failures logged to {log}")


if __name__ == "__main__":
    main()
