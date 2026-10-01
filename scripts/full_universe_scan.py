"""Full universe scan: download + metrics + edge for all UM perpetuals (2026-08)."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import polars as pl

DATA = Path("data")
S = 1_000_000_000
COST_RT = 4.0  # maker×maker UM


def fetch_universe(client: httpx.Client) -> list[dict]:
    resp = client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    resp.raise_for_status()
    raw = resp.json()
    out = []
    for entry in raw["symbols"]:
        if entry.get("contractType") != "PERPETUAL":
            continue
        if entry.get("status") != "TRADING":
            continue
        if entry.get("quoteAsset") != "USDT":
            continue
        tick = step = notional = None
        for f in entry.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                tick = float(f["tickSize"])
            elif f.get("filterType") == "LOT_SIZE":
                step = float(f["stepSize"])
            elif f.get("filterType") == "MIN_NOTIONAL":
                notional = float(f["notional"])
        if tick and step and notional:
            out.append({"symbol": entry["symbol"], "tick_size": tick,
                        "step_size": step, "min_notional": notional})
    out.sort(key=lambda x: x["symbol"])
    return out


def download_symbol_bars(client: httpx.Client, symbol: str) -> pl.DataFrame | None:
    """Download last-month 1m klines for one symbol from data.binance.vision."""
    url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-2026-08.zip"
    checksum_url = url + ".CHECKSUM"
    try:
        checksum_resp = client.get(checksum_url)
        if checksum_resp.status_code != 200:
            return None
        expected = checksum_resp.text.split()[0].lower()
        zip_resp = client.get(url)
        if zip_resp.status_code != 200:
            return None
        import hashlib
        import io
        from zipfile import BadZipFile, ZipFile
        content = zip_resp.content
        if hashlib.sha256(content).hexdigest() != expected:
            return None
        with ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != 1:
                return None
            csv_data = archive.read(names[0])
        # parse: 12 columns
        lines = [line for line in csv_data.decode("utf-8").splitlines() if line.strip()]
        header_present = lines[0].startswith("open_time") if lines else False
        body = lines[1:] if header_present else lines
        data = []
        for line in body:
            parts = line.split(",")
            if len(parts) != 12:
                continue
            try:
                ts = int(parts[0])
                if ts >= 10**18:
                    pass  # already ns
                elif ts >= 10**15:
                    ts *= 1000
                elif ts >= 10**12:
                    ts *= 1_000_000
                else:
                    continue
                data.append({
                    "ts_open_ns": ts, "open": float(parts[1]), "high": float(parts[2]),
                    "low": float(parts[3]), "close": float(parts[4]),
                    "volume": float(parts[5]), "quote_volume": float(parts[7]),
                    "n_trades": int(parts[8]),
                    "taker_buy_volume": float(parts[9]),
                    "taker_buy_quote_volume": float(parts[10]),
                })
            except (ValueError, IndexError):
                continue
        return pl.DataFrame(data) if data else None
    except (httpx.HTTPError, BadZipFile, KeyError):
        return None


def asset_metrics(bars: pl.DataFrame, min_quote_volume_daily: float = 0.0) -> dict:
    n = bars.height
    close = bars["close"].to_numpy()
    if n < 2:
        return {"dead": True, "vol_bps_1m": None, "quote_volume_daily": None,
                "breakout_freq": None, "n_bars": n}
    returns = np.diff(close) / close[:-1]
    vol_1m = float(np.std(returns) * 1e4)
    # 1h aggregation
    hour_ns = 3600 * S
    hour_bucket = bars["ts_open_ns"] // hour_ns
    hourly = bars.with_columns(hour_bucket.alias("_b")).group_by("_b", maintain_order=True).agg(pl.col("close").last())
    hourly_close = hourly["close"].to_numpy()
    if len(hourly_close) >= 2:
        hrets = np.diff(hourly_close) / hourly_close[:-1]
        vol_1h = float(np.std(hrets) * 1e4)
    else:
        vol_1h = None
    day_ns = 86_400 * S
    day_bucket = bars["ts_open_ns"] // day_ns
    daily_qv = bars.with_columns(day_bucket.alias("_d")).group_by("_d").agg(pl.col("quote_volume").sum())
    qv_daily = float(daily_qv["quote_volume"].mean())
    daily_nt = bars.with_columns(day_bucket.alias("_d")).group_by("_d").agg(pl.col("n_trades").sum())
    nt_daily = float(daily_nt["n_trades"].mean())
    span_days = (float(bars["ts_open_ns"][-1] - bars["ts_open_ns"][0])) / (86_400.0 * S)
    dead = qv_daily < min_quote_volume_daily or span_days < 20.0
    return {
        "dead": dead, "vol_bps_1m": vol_1m, "vol_bps_1h": vol_1h,
        "quote_volume_daily": qv_daily, "n_trades_daily": nt_daily,
        "n_bars": n, "span_days": span_days,
    }


def forward_edge(bars: pl.DataFrame, direction: str, horizon_s: int) -> float | None:
    """Raw forward return in bps for a buy/sell at every bar, at horizon."""
    close = bars["close"].to_numpy()
    ts = bars["ts_open_ns"].to_numpy()
    horizon_ns = horizon_s * S
    if len(close) < 10:
        return None
    sign = 1.0 if direction == "buy" else -1.0
    idx_targets = np.searchsorted(ts, ts + horizon_ns, side="right") - 1
    valid = (idx_targets > np.arange(len(ts))) & (idx_targets < len(ts))
    if valid.sum() < 5:
        return None
    rets = (close[idx_targets[valid]] / close[np.arange(len(ts))[valid]] - 1.0) * 1e4 * sign
    return float(np.mean(rets))


def breakout_forward_edge(bars: pl.DataFrame, horizon_s: int = 300) -> float | None:
    """Forward return after breakout signals (the best-performing signal)."""
    close = bars["close"].to_numpy()
    ts = bars["ts_open_ns"].to_numpy()
    high = bars["high"].to_numpy()
    vol = bars["volume"].to_numpy()
    lookback = 30
    n = len(close)
    rets = []
    for i in range(lookback, n - horizon_s):
        range_high = high[i - lookback : i].max()
        avg_vol = vol[i - lookback : i].mean()
        if close[i] > range_high and vol[i] > 2.0 * avg_vol:
            target = i + horizon_s
            if target < n:
                rets.append((close[target] / close[i] - 1.0) * 1e4)
    return float(np.mean(rets)) if rets else None


def main() -> None:
    t0 = time.perf_counter()
    print("=== 1. Univers ===")
    with httpx.Client(timeout=30.0) as client:
        universe = fetch_universe(client)
    symbols = [u["symbol"] for u in universe]
    print(f"{len(symbols)} perpétuels UM négociables")

    print("\n=== 2. Téléchargement parallèle (8 workers) ===")
    results: dict[str, pl.DataFrame] = {}
    errors: list[str] = []
    with httpx.Client(timeout=60.0) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(download_symbol_bars, client, s): s for s in symbols}
            done = 0
            for future in as_completed(futures):
                symbol = futures[future]
                done += 1
                if done % 50 == 0:
                    print(f"  {done}/{len(symbols)}...")
                try:
                    df = future.result()
                    if df is not None and df.height >= 100:
                        results[symbol] = df
                    else:
                        errors.append(symbol)
                except Exception:
                    errors.append(symbol)
    print(f"  téléchargés: {len(results)}, échoués/vides: {len(errors)}")

    print("\n=== 3. Métriques + edge par actif ===")
    assets = []
    for symbol, bars in sorted(results.items()):
        metrics = asset_metrics(bars, min_quote_volume_daily=1_000_000.0)
        if metrics["dead"]:
            assets.append({"symbol": symbol, **metrics, "brut_60s": None,
                           "brut_300s": None, "brut_breakout": None, "edge_net": None})
            continue
        brut_60 = forward_edge(bars, "buy", 60)
        brut_300 = forward_edge(bars, "buy", 300)
        brut_bo = breakout_forward_edge(bars, 300)
        # edge net = brut - 4 bps (maker×maker)
        best = max(v for v in [brut_60, brut_300, brut_bo] if v is not None) if any(
            v is not None for v in [brut_60, brut_300, brut_bo]
        ) else None
        edge_net = best - COST_RT if best is not None else None
        assets.append({
            "symbol": symbol, **metrics,
            "brut_60s": brut_60, "brut_300s": brut_300,
            "brut_breakout": brut_bo, "edge_net": edge_net,
        })

    print("\n=== 4. Classement par edge net (bps/trade, brut - 4) ===")
    ranked = sorted(
        [a for a in assets if a["edge_net"] is not None],
        key=lambda a: -a["edge_net"],
    )
    print(f"{'Symbole':>14} {'Vol1m':>7} {'Vol/j(M)':>8} {'BO/j':>6} {'Brut60':>8} {'Brut300':>8} {'BrutBO':>8} {'EdgeNet':>8}")
    for a in ranked[:20]:
        bo = a.get("breakout_freq", 0) or 0
        b60 = a.get("brut_60s", 0) or 0
        b300 = a.get("brut_300s", 0) or 0
        bbo = a.get("brut_breakout", 0) or 0
        net = a.get("edge_net", 0) or 0
        vol = a.get("vol_bps_1m", 0) or 0
        qv = a.get("quote_volume_daily", 0) or 0
        print(f"{a['symbol']:>14} {vol:>7.2f} {qv/1e6:>8.1f} "
              f"{bo:>6.2f} {b60:>8.2f} {b300:>8.2f} "
              f"{bbo:>8.2f} {net:>8.2f}")

    positive = [a for a in ranked if a["edge_net"] > 0]
    print(f"\nActifs avec edge net > 0: {len(positive)}/{len(ranked)}")
    for a in positive:
        print(f"  {a['symbol']}: edge_net={a['edge_net']:.2f} brut_bo={a['brut_breakout']:.2f}")

    # save results
    out_path = DATA / "scan"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "scan-results.json").write_text(json.dumps(ranked, indent=2), encoding="utf-8")
    print(f"\nrésultats -> {out_path / 'scan-results.json'}")
    print(f"total: {time.perf_counter()-t0:.0f}s")


if __name__ == "__main__":
    main()
