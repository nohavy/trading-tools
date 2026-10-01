"""Build the manifest of available UM 1d monthly klines (includes delisted symbols).

Listing the archive prefixes tells us exactly which (symbol, month) files exist,
so the download stage never fires a 404 storm and the study keeps delisted
symbols in the cross-section (survivorship bias control).
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
KLINES_ROOT = "data/futures/um/monthly/klines"
INTERVAL = "1d"
OUT = Path("data/daily_manifest.json")
_MONTH_RE = re.compile(r"(\d{4}-\d{2})\.zip$")


def _leaf(prefix: str) -> str:
    """Last non-empty path component of an S3 common prefix."""
    return prefix.strip("/").rsplit("/", 1)[-1]


def _list(
    client: httpx.Client, prefix: str, delimiter: str, marker: str = ""
) -> tuple[list[str], list[str], str | None]:
    """Return (common prefixes, object keys, next marker) for one S3 listing page."""
    params = {"delimiter": delimiter, "prefix": prefix}
    if marker:
        params["marker"] = marker
    resp = client.get(S3, params=params)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    prefixes = [_leaf(el.text or "") for el in root.findall("s3:CommonPrefixes/s3:Prefix", NS)]
    keys = [el.text or "" for el in root.findall("s3:Contents/s3:Key", NS)]
    next_marker = root.findtext("s3:NextMarker", default="", namespaces=NS) or None
    return prefixes, keys, next_marker


def list_symbols(client: httpx.Client) -> list[str]:
    symbols: list[str] = []
    marker: str | None = ""
    while True:
        page, _, next_marker = _list(client, f"{KLINES_ROOT}/", "/", marker or "")
        symbols.extend(page)
        if not next_marker:
            break
        marker = next_marker
    return sorted(set(symbols))


def list_months(client: httpx.Client, symbol: str) -> list[str]:
    """Months for which a monthly 1d klines zip exists (flat object keys)."""
    months: set[str] = set()
    marker: str | None = ""
    prefix = f"{KLINES_ROOT}/{symbol}/{INTERVAL}/"
    while True:
        _, keys, next_marker = _list(client, prefix, "/", marker or "")
        for key in keys:
            match = _MONTH_RE.search(key)
            if match:
                months.add(match.group(1))
        if not next_marker:
            break
        marker = next_marker
    return sorted(months)


def main() -> None:
    with httpx.Client(timeout=30.0) as client:
        symbols = list_symbols(client)
        print(f"symbols with any UM kline: {len(symbols)}", flush=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            per_symbol = list(pool.map(lambda s: (s, list_months(client, s)), symbols))
    manifest = {
        symbol: months for symbol, months in per_symbol if symbol.endswith("USDT")
    }
    total = sum(len(m) for m in manifest.values())
    with_months = sum(1 for m in manifest.values() if m)
    print(f"USDT symbols: {len(manifest)} (with 1d data: {with_months})")
    print(f"total monthly 1d files: {total}")
    spans = sorted((min(m), max(m)) for m in manifest.values() if m)
    print(f"earliest month: {spans[0][0]}, latest: {spans[-1][1]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=0, sort_keys=True))
    print(f"written: {OUT}")
    if "--top" in sys.argv:
        for symbol, months in sorted(manifest.items(), key=lambda kv: -len(kv[1]))[:10]:
            print(f"  {symbol}: {len(months)} months")


if __name__ == "__main__":
    main()
