"""Monte Carlo bootstrap of trade sequences (dispersion and ruin probability)."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl


class MonteCarloError(Exception):
    """Raised when the bootstrap cannot run (no trades)."""


@dataclass(frozen=True)
class MonteCarloResult:
    """Bootstrap distribution summary of the final PnL (quote units)."""

    n_sims: int
    n_trades: int
    p5: float
    p50: float
    p95: float
    mean: float
    prob_dd_over: float


def load_trade_nets(run_dir: Path) -> list[float]:
    """Read per-trade nets from a run's trips.csv."""
    path = run_dir / "trips.csv"
    if not path.is_file():
        raise MonteCarloError(f"no trips.csv in {run_dir}")
    df = pl.read_csv(path)
    if df.is_empty():
        raise MonteCarloError(f"run has no closed trades: {run_dir}")
    return [float(v) for v in df["net"].to_list()]


def bootstrap_trips(
    nets: list[float],
    *,
    n_sims: int,
    seed: int,
    dd_threshold: float,
) -> MonteCarloResult:
    """Resample trade nets with replacement; return final-PnL percentiles and
    the probability that a resampled sequence's drawdown exceeds the threshold
    (drawdown in absolute quote units from the running peak).

    Deterministic for a given seed (constitution III).
    """
    if not nets:
        raise MonteCarloError("no trades to bootstrap")
    rng = np.random.default_rng(seed)
    values = np.array(nets, dtype=np.float64)
    draws = rng.choice(values, size=(n_sims, len(nets)), replace=True)
    finals = draws.sum(axis=1)
    cum = np.cumsum(draws, axis=1)
    peaks = np.maximum.accumulate(cum, axis=1)
    dd = (peaks - cum).max(axis=1)
    return MonteCarloResult(
        n_sims=n_sims,
        n_trades=len(nets),
        p5=float(np.percentile(finals, 5)),
        p50=float(np.percentile(finals, 50)),
        p95=float(np.percentile(finals, 95)),
        mean=float(finals.mean()),
        prob_dd_over=float((dd > dd_threshold).mean()),
    )


def bootstrap_run(
    run_dir: Path, *, n_sims: int, seed: int, dd_threshold: float
) -> MonteCarloResult:
    """Bootstrap the closed trades of a run directory."""
    return bootstrap_trips(
        load_trade_nets(run_dir), n_sims=n_sims, seed=seed, dd_threshold=dd_threshold
    )
