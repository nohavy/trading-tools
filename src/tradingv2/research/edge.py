"""Edge study: forward returns after signals, compared to round-trip costs.

This is the pre-backtest filter of the founding plan (constitution II): a
signal that does not beat the round-trip cost of any product/order pair is
not worth a backtest.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from tradingv2.research.signals import SignalEvent


def forward_returns(
    ts: np.ndarray,
    close: np.ndarray,
    event_ts: int,
    horizons_ns: list[int],
    direction: str = "buy",
) -> dict[int, float | None]:
    """Return (in bps) at each horizon after the event, or None beyond data.

    The reference price is the last known close at or before the event.
    A "sell" event profits from down moves: the return is negated.
    """
    assert direction in ("buy", "sell")
    event_idx = int(np.searchsorted(ts, event_ts, side="right")) - 1
    if event_idx < 0:
        return {h: None for h in horizons_ns}
    base = close[event_idx]
    sign = 1.0 if direction == "buy" else -1.0
    out: dict[int, float | None] = {}
    for horizon in horizons_ns:
        target_idx = int(np.searchsorted(ts, event_ts + horizon, side="right")) - 1
        if target_idx <= event_idx:
            # no price at all after the event: return not measurable
            out[horizon] = None
            continue
        out[horizon] = float((close[target_idx] / base - 1.0) * 1e4 * sign)
    return out


def _excursions(
    ts: np.ndarray,
    close: np.ndarray,
    event_ts: int,
    horizon_ns: int,
    direction: str,
) -> tuple[float | None, float | None]:
    """Max favorable / adverse excursion (bps) between event and horizon."""
    event_idx = int(np.searchsorted(ts, event_ts, side="right")) - 1
    if event_idx < 0:
        return None, None
    target_ts = event_ts + horizon_ns
    target_idx = int(np.searchsorted(ts, target_ts, side="right")) - 1
    if target_idx <= event_idx:
        return None, None
    base = close[event_idx]
    window = close[event_idx : target_idx + 1]
    if direction == "buy":
        mfe = (window.max() / base - 1.0) * 1e4
        mae = (window.min() / base - 1.0) * 1e4
    else:
        mfe = (1.0 - window.min() / base) * 1e4
        mae = (1.0 - window.max() / base) * 1e4
    return float(mfe), float(mae)


def edge_table(
    events: list[SignalEvent],
    ts: np.ndarray,
    close: np.ndarray,
    horizons_ns: list[int],
    cost_pairs: list[tuple[str, float]],
) -> list[dict[str, Any]]:
    """Rows per horizon: n, mean/median bps, hit rate, excursions, edges vs costs.

    edges = {cost_pair_name: mean_bps - round_trip_bps} (None without data).
    """
    rows: list[dict[str, Any]] = []
    for horizon in horizons_ns:
        rets: list[float] = []
        mfes: list[float] = []
        maes: list[float] = []
        for event in events:
            fr = forward_returns(ts, close, event.ts_ns, [horizon], event.direction)[horizon]
            if fr is None:
                continue
            rets.append(fr)
            mfe, mae = _excursions(ts, close, event.ts_ns, horizon, event.direction)
            if mfe is not None:
                mfes.append(mfe)
            if mae is not None:
                maes.append(mae)
        n_defined = len(rets)
        if n_defined == 0:
            rows.append(
                {
                    "horizon_s": horizon // 1_000_000_000,
                    "n": len(events),
                    "n_defined": 0,
                    "mean_bps": None,
                    "median_bps": None,
                    "hit_rate": None,
                    "mfe_bps": None,
                    "mae_bps": None,
                    "edges": {name: None for name, _rt in cost_pairs},
                }
            )
            continue
        mean = sum(rets) / n_defined
        sorted_rets = sorted(rets)
        mid = n_defined // 2
        median = (
            sorted_rets[mid]
            if n_defined % 2 == 1
            else (sorted_rets[mid - 1] + sorted_rets[mid]) / 2.0
        )
        hit_rate = sum(1 for r in rets if r > 0) / n_defined
        rows.append(
            {
                "horizon_s": horizon // 1_000_000_000,
                "n": len(events),
                "n_defined": n_defined,
                "mean_bps": mean,
                "median_bps": median,
                "hit_rate": hit_rate,
                "mfe_bps": sum(mfes) / len(mfes) if mfes else None,
                "mae_bps": sum(maes) / len(maes) if maes else None,
                "edges": {name: mean - rt for name, rt in cost_pairs},
            }
        )
    return rows


def _signal_events(config: dict[str, Any], bars: pl.DataFrame) -> list[SignalEvent]:
    from tradingv2.research.signals import signal_breakout, signal_flow, signal_meanrev

    signal = config["signal"]
    name = signal["name"]
    ts = bars["ts_open_ns"]
    if name == "meanrev":
        return signal_meanrev(
            bars["close"], ts, window=int(signal.get("window", 120)),
            entry_z=float(signal.get("entry_z", 2.5)),
        )
    if name == "breakout":
        return signal_breakout(
            bars["high"], bars["low"], bars["close"], bars["volume"], ts,
            lookback=int(signal.get("lookback", 60)),
            volume_factor=float(signal.get("volume_factor", 2.0)),
        )
    if name == "flow":
        return signal_flow(
            bars["volume"], bars["taker_buy_volume"], ts,
            window=int(signal.get("window", 120)),
            threshold=float(signal.get("threshold", 0.5)),
        )
    raise ValueError(f"unknown signal '{name}' (known: meanrev, breakout, flow)")


def _load_bars(config: dict[str, Any], data_root: Path) -> pl.DataFrame:
    data = config["data"]
    interval = data["interval"]
    directory = data_root / "parquet" / data["market"] / "klines" / data["symbol"] / interval
    files = sorted(directory.glob("*.parquet")) if directory.is_dir() else []
    if not files:
        raise FileNotFoundError(f"no bar data under {directory}: download data first")
    from datetime import date, timedelta

    lower = int((date.fromisoformat(str(data["start"])) - _EPOCH).total_seconds() * 1e9)
    upper = int(
        (date.fromisoformat(str(data["end"])) - _EPOCH + timedelta(days=1)).total_seconds() * 1e9
    ) - 1
    frames = [pl.read_parquet(path) for path in files]
    df = pl.concat(frames).sort("ts_open_ns")
    return df.filter((pl.col("ts_open_ns") >= lower) & (pl.col("ts_open_ns") <= upper))


_EPOCH = date(1970, 1, 1)


def run_edge_study(config_path: Path, data_root: Path, runs_root: Path) -> Path:
    """Run the edge study described by a research YAML; write runs/edge-*.json."""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    bars = _load_bars(config, data_root)
    if bars.is_empty():
        raise FileNotFoundError("no bars in the configured period")
    events = _signal_events(config, bars)
    ts = bars["ts_open_ns"].to_numpy()
    close = bars["close"].to_numpy()
    default_horizons = [1, 5, 15, 30, 60, 300, 900]
    horizons = config.get("horizons_s", default_horizons)
    horizons_ns = [int(h) * 1_000_000_000 for h in horizons]
    cost_pairs = [
        (pair["name"], float(pair["maker_bps"]) + float(pair["taker_bps"]))
        for pair in config.get("cost_pairs", [])
    ]
    rows = edge_table(events, ts, close, horizons_ns, cost_pairs)
    runs_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    out = runs_root / f"edge-{stamp}.json"
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "signal": config["signal"],
        "horizons_s": config.get("horizons_s", []),
        "n_events": len(events),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def session_labels(event_ts: np.ndarray) -> list[str]:
    """UTC session buckets: 0-8 (Asia), 8-16 (Europe), 16-24 (US)."""
    hour = (event_ts // 1_000_000_000 // 3600) % 24
    return ["0-8" if h < 8 else ("8-16" if h < 16 else "16-24") for h in hour]


def vol_regime_labels(ts: np.ndarray, close: np.ndarray, window: int) -> list[str]:
    """High/low volatility labels per bar: above/below the series median vol.

    Vol = std of simple returns over `window` bars (rolling, population).
    Undefined (window not full) bars get the label of the last defined value.
    """
    if len(close) < 2:
        return ["low"] * len(ts)
    returns = np.diff(close) / close[:-1]
    vols = np.full(len(close), np.nan)
    if len(returns) >= window:
        windows = np.lib.stride_tricks.sliding_window_view(returns, window)
        vols[window:] = windows.std(axis=1)
    defined = vols[~np.isnan(vols)]
    median = float(np.median(defined)) if defined.size else 0.0
    labels: list[str] = []
    last = "low"
    for value in vols:
        if value != value:
            labels.append(last)
            continue
        last = "high" if value > median else "low"
        labels.append(last)
    return labels


def edge_by_regime(
    events: list[SignalEvent],
    ts: np.ndarray,
    close: np.ndarray,
    horizons_ns: list[int],
    cost_pairs: list[tuple[str, float]],
    label_fn: "Callable[[int], str]",
) -> dict[str, list[dict[str, object]]]:
    """Edge table per regime: events grouped by label_fn(event_ts).

    Returns {label: edge_table rows for the events of that label}. Labels with
    no events are absent from the result.
    """
    groups: dict[str, list[SignalEvent]] = {}
    for event in events:
        label = label_fn(event.ts_ns)
        groups.setdefault(label, []).append(event)
    return {
        label: edge_table(group, ts, close, horizons_ns, cost_pairs)
        for label, group in sorted(groups.items())
    }


@dataclass(frozen=True)
class EdgeSweepEntry:
    """One signal parameter combination scored by its raw forward edge."""

    params: dict[str, float | int]
    score_bps: float | None
    n_events: int
    few_events: bool
    rows: list[dict[str, object]]


@dataclass
class EdgeSweepResult:
    """Ranked edge sweep entries + HTML report path."""

    entries: list[EdgeSweepEntry]
    html_path: Path


def edge_sweep(
    config_path: Path,
    grid: dict[str, list[float | int]],
    *,
    data_root: Path,
    runs_root: Path,
    target_horizon_s: int = 60,
    min_events: int = 100,
) -> EdgeSweepResult:
    """Score every signal parameter combination by its raw forward edge.

    The edge study is cheap (~seconds), so the grid is swept BEFORE any
    backtest. Score = mean forward return (bps) at the target horizon.
    Combinations without events (or below min_events) are flagged.
    """
    from tradingv2.backtest.sweep import _ENV as _sweep_env  # shared templates

    base = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    bars = _load_bars(base, data_root)
    if bars.is_empty():
        raise FileNotFoundError("no bars in the configured period")
    ts = bars["ts_open_ns"].to_numpy()
    close = bars["close"].to_numpy()
    horizons_ns = [int(h) * 1_000_000_000 for h in base.get("horizons_s", [1, 60])]
    cost_pairs = [
        (pair["name"], float(pair["maker_bps"]) + float(pair["taker_bps"]))
        for pair in base.get("cost_pairs", [])
    ]

    param_names = list(grid.keys())
    entries: list[EdgeSweepEntry] = []
    for combo in product(*[grid[key] for key in param_names]):
        params: dict[str, float | int] = dict(zip(param_names, combo, strict=True))
        variant = yaml.safe_load(yaml.safe_dump(base))  # deep copy, dates kept
        signal = dict(variant["signal"])
        signal.update(params)
        variant["signal"] = signal
        events = _signal_events(variant, bars)
        rows = edge_table(events, ts, close, horizons_ns, cost_pairs)
        score = None
        for row in rows:
            if row["horizon_s"] == target_horizon_s:
                score = row["mean_bps"]
                break
        entries.append(
            EdgeSweepEntry(
                params=params,
                score_bps=score,
                n_events=len(events),
                few_events=len(events) < min_events,
                rows=rows,
            )
        )
    entries.sort(
        key=lambda e: -(e.score_bps if e.score_bps is not None else float("-inf"))
    )
    runs_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    html_path = runs_root / f"edge-sweep-{stamp}.html"
    table_rows = [
        {
            "params": ", ".join(f"{k}={v}" for k, v in entry.params.items()),
            "score": f"{entry.score_bps:.3f}" if entry.score_bps is not None else "n/a",
            "n_events": entry.n_events,
            "few": entry.few_events,
        }
        for entry in entries
    ]
    html = _sweep_env.get_template("sweep.html.j2").render(rows=table_rows, n=len(entries))
    html_path.write_text(html, encoding="utf-8")
    return EdgeSweepResult(entries=entries, html_path=html_path)
