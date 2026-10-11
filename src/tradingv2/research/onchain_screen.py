"""Vectorized whale-flux screen (012): net inflows vs next returns.

The signal at day close t = deposits(t-lookback+1..t) - withdrawals(same).
A heavy positive net inflow (whales parking on exchanges) predicts a
NEGATIVE next interval → the screen enters short (spot-level, per the
brief's falsification-first step). Prices stay spot closes; fees 10 bps
per side (frozen "11 bps screen" convention) paid on entry AND exit flips,
never on holding days.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Screen:
    """Aligned arrays: per-day positions and per-interval net returns."""

    positions: np.ndarray
    net_returns: np.ndarray
    fees_bcps: np.ndarray
    flows_net: np.ndarray


def screen_net_flows(
    *,
    deposits: list[float],
    withdraws: list[float],
    closes: list[float],
    lookback_days: int,
    entry_net_in: float,
    flat_exit: float,
    cost_bps: float,
) -> Screen:
    """Compute daily positions and close-to-close net returns.

    Ante-lookahead rule: day t's position uses only flows at or before
    day t; the position applies to the interval [t -> t+1].
    """
    dep = np.asarray(deposits, dtype=float)
    wit = np.asarray(withdraws, dtype=float)
    prices = np.asarray(closes, dtype=float)
    n_days = dep.size
    if prices.size != n_days + 1:
        raise ValueError("closes must provide exactly one mark per included day + 1: aligned")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if dep.shape != wit.shape:
        raise ValueError("deposits and withdraws must be aligned")

    positions = np.zeros(n_days)
    flows_net = np.zeros(n_days)
    held = False
    for t in range(n_days):
        lo = max(0, t - lookback_days + 1)
        net = float(dep[lo:t + 1].sum() - wit[lo:t + 1].sum())
        flows_net[t] = net
        if held and abs(net) <= flat_exit:
            held = False
        elif not held and net >= entry_net_in:
            held = True
        positions[t] = -1.0 if held else 0.0

    net_returns = np.zeros(n_days)
    fees = np.zeros(n_days)
    for t in range(n_days):
        change = (positions[t] != positions[t - 1]) if t > 0 else positions[t] != 0.0
        if change:
            fees[t] = cost_bps
        if t + 1 <= n_days - 1:
            ret = prices[t + 1] / prices[t] - 1.0
            net_returns[t] = positions[t] * ret - (fees[t] / 1e4)
        else:
            net_returns[t] = -(fees[t] / 1e4)

    return Screen(
        positions=positions,
        net_returns=net_returns,
        fees_bcps=fees,
        flows_net=flows_net,
    )
