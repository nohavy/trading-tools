"""Asset scan orchestration: snapshot → metrics → edge → ranked report."""

from collections.abc import Callable
from typing import Any

import polars as pl

from tradingv2.research.edge import edge_table
from tradingv2.research.signals import (
    SignalEvent,
    signal_breakout,
    signal_flow,
    signal_meanrev,
)

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
