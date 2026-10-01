"""Asset scan orchestration: snapshot → metrics → edge → ranked report."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from tradingv2.research.asset_metrics import asset_metrics
from tradingv2.research.edge import edge_table
from tradingv2.research.signals import (
    SignalEvent,
    signal_breakout,
    signal_flow,
    signal_meanrev,
)

_EPOCH = date(1970, 1, 1)

# per-signal default parameters from the edge analyses (documented defaults)
_SIGNAL_FACTORIES: dict[str, Callable[[pl.DataFrame], list[SignalEvent]]] = {
    "breakout": lambda bars: signal_breakout(
        bars["high"], bars["low"], bars["close"], bars["volume"], bars["ts_open_ns"],
        lookback=30, volume_factor=5.0,
    ),
    "meanrev": lambda bars: signal_meanrev(
        bars["close"], bars["ts_open_ns"], window=120, entry_z=2.5
    ),
    "flow": lambda bars: signal_flow(
        bars["volume"], bars["taker_buy_volume"], bars["ts_open_ns"],
        window=120, threshold=0.5,
    ),
}


def asset_edge(
    bars: pl.DataFrame,
    *,
    target_horizon_s: int = 300,
    cost_rt_bps: float = 4.0,
    min_events: int = 30,
) -> dict[str, Any]:
    """Quick-pass edge for one asset: all known signals vs maker costs.

    Returns {signals: {name: {mean_bps, hit_rate, n}}, score_bps (max across
    signals at the target horizon), edge_net_bps (score - cost), n_events,
    few_events}.
    """
    ts = bars["ts_open_ns"].to_numpy()
    close = bars["close"].to_numpy()
    horizon_ns = target_horizon_s * 1_000_000_000

    signal_stats: dict[str, dict[str, Any]] = {}
    score = None
    total_events = 0
    for name, factory in _SIGNAL_FACTORIES.items():
        events = factory(bars)
        total_events = max(total_events, len(events))
        rows = edge_table(events, ts, close, [horizon_ns], [])
        row = rows[0]
        mean = row["mean_bps"]
        signal_stats[name] = {
            "mean_bps": mean,
            "hit_rate": row["hit_rate"],
            "n": row["n_defined"],
        }
        if mean is not None and (score is None or mean > score):
            score = mean
    edge_net = score - cost_rt_bps if score is not None else None
    best_signal = None
    for name, stats in signal_stats.items():
        if stats["mean_bps"] is not None and stats["mean_bps"] == score:
            best_signal = name
            break
    return {
        "signals": signal_stats,
        "score_bps": score,
        "edge_net_bps": edge_net,
        "best_signal": best_signal,
        "n_events": total_events,
        "few_events": total_events < min_events,
    }


def _load_symbol_bars(data_root: Path, symbol: str, market: str, interval: str,
                      start: date, end: date) -> pl.DataFrame | None:
    """Load one symbol's bars directly (no catalog dependency)."""
    from tradingv2.backtest.runner import _file_overlaps_bounds

    directory = data_root / "parquet" / market / "klines" / symbol / interval
    files = sorted(directory.glob("*.parquet")) if directory.is_dir() else []
    lower = int((start - _EPOCH).total_seconds() * 1e9)
    upper = int((end - _EPOCH + timedelta(days=1)).total_seconds() * 1e9) - 1
    files = [f for f in files if _file_overlaps_bounds(f, (lower, upper))]
    if not files:
        return None
    frames = [pl.read_parquet(f) for f in files]
    df = pl.concat(frames).sort("ts_open_ns")
    return df if df.height >= 2 else None


def run_scan(config_path: Path, data_root: Path, runs_root: Path) -> Path:
    """Orchestrate the asset scan: universe → metrics+edge → ranked report.

    Never raises on individual asset failures: they are skipped with warnings
    (FR-008). Returns the report path; the summary and candidates sit next to
    it in the runs directory.
    """

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data_cfg = config["data"]
    scan_cfg = config.get("scan", {})
    market = data_cfg["market"]
    interval = data_cfg["interval"]
    start = date.fromisoformat(str(data_cfg["start"]))
    end = date.fromisoformat(str(data_cfg["end"]))
    cost_pair = scan_cfg.get("cost_pair", {"maker_bps": 2, "taker_bps": 2})
    cost_rt = float(cost_pair["maker_bps"]) + float(cost_pair["taker_bps"])
    target_horizon_s = int(scan_cfg.get("target_horizon_s", 300))
    threshold_edge = float(scan_cfg.get("threshold_edge_bps", 0.0))
    min_quote_volume_daily = float(scan_cfg.get("min_quote_volume_daily", 1_000_000.0))
    min_trades = int(scan_cfg.get("min_trades", 5))

    from tradingv2.data.universe import load_universe

    symbols = [s["symbol"] for s in load_universe(data_root)]

    assets: list[dict[str, Any]] = []
    skipped: list[str] = []
    import sys
    for symbol in symbols:
        try:
            bars = _load_symbol_bars(data_root, symbol, market, interval, start, end)
        except Exception as exc:
            print(f"SCAN-DEBUG {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
            skipped.append(symbol)
            continue
        if bars is None:
            print(f"SCAN-DEBUG {symbol}: None returned", file=sys.stderr)
            skipped.append(symbol)
            continue
        fpath = data_root / "parquet" / market / "fundingRate" / symbol
        funding = None
        if fpath.is_dir():
            frames = [pl.read_parquet(p) for p in sorted(fpath.glob("*.parquet"))]
            if frames:
                funding = pl.concat(frames)
        try:
            metrics = asset_metrics(
                bars, funding=funding, min_quote_volume_daily=min_quote_volume_daily
            )
            edge = asset_edge(
                bars, target_horizon_s=target_horizon_s, cost_rt_bps=cost_rt,
                min_events=min_trades,
            )
        except Exception:
            skipped.append(symbol)
            continue
        assets.append({
            "symbol": symbol,
            **{k: v for k, v in metrics.items()},
            "edge_net_bps": edge["edge_net_bps"],
            "score_bps": edge["score_bps"],
            "best_signal": edge["best_signal"],
            "few_events": edge["few_events"],
        })

    ranked = sorted(
        assets,
        key=lambda a: -(a["edge_net_bps"] if a["edge_net_bps"] is not None else float("-inf")),
    )
    candidates = [
        a for a in ranked
        if not a["dead"]
        and a["edge_net_bps"] is not None
        and a["edge_net_bps"] > threshold_edge
        and not a["few_events"]
    ]

    runs_root.mkdir(parents=True, exist_ok=True)
    summary_path = runs_root / "scan-summary.json"
    candidates_path = runs_root / "scan-candidates.json"
    report_path = runs_root / "scan-report.html"

    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "n_universe": len(symbols),
        "n_scanned": len(assets),
        "skipped": skipped,
        "threshold_edge_bps": threshold_edge,
        "assets": ranked,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    candidates_path.write_text(json.dumps({
        "threshold_edge_bps": threshold_edge,
        "candidates": [
            {"symbol": a["symbol"], "edge_net_bps": a["edge_net_bps"],
             "best_signal": a["best_signal"]}
            for a in candidates
        ],
    }, indent=2), encoding="utf-8")

    from tradingv2.backtest.sweep import _ENV as _sweep_env

    table_rows = [
        {
            "symbol": a["symbol"],
            "dead": a["dead"],
            "vol": f"{a['vol_bps_1m']:.2f}" if a["vol_bps_1m"] is not None else "n/a",
            "liq": f"{a['quote_volume_daily']:,.0f}",
            "breaks": f"{a['breakout_freq']:.2f}" if a["breakout_freq"] is not None else "n/a",
            "edge": f"{a['edge_net_bps']:.2f}" if a["edge_net_bps"] is not None else "n/a",
            "best": a["best_signal"] or "n/a",
        }
        for a in ranked
    ]
    html = _sweep_env.get_template("scan.html.j2").render(
        rows=table_rows, n=len(ranked), skipped=skipped, n_candidates=len(candidates),
    )
    report_path.write_text(html, encoding="utf-8")
    return report_path
