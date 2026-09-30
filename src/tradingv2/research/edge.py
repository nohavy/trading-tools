"""Edge study: forward returns after signals, compared to round-trip costs.

This is the pre-backtest filter of the founding plan (constitution II): a
signal that does not beat the round-trip cost of any product/order pair is
not worth a backtest.
"""

import json
from datetime import UTC, date, datetime
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
