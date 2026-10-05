"""Market-neutral spot long / perpetual short cash-and-carry research model."""

from dataclasses import dataclass

import numpy as np

_DAY_NS = 86_400_000_000_000


@dataclass(frozen=True)
class CarryResult:
    """One interval per decision; position applies only to the following interval."""

    ts_ns: np.ndarray
    position: np.ndarray
    price_returns: np.ndarray
    funding_returns: np.ndarray
    fee_returns: np.ndarray
    net_returns: np.ndarray


def simulate_cash_and_carry(
    ts_open_ns: np.ndarray,
    spot_close: np.ndarray,
    perp_close: np.ndarray,
    funding_ts_ns: np.ndarray,
    funding_rates: np.ndarray,
    *,
    lookback_days: int,
    entry_funding_sum: float,
    exit_funding_sum: float,
    entry_basis: float,
    exit_basis: float,
    spot_cost_bps: float,
    perp_cost_bps: float,
    mode: str = "filtered",
) -> CarryResult:
    """Simulate an unlevered same-quantity spot/perp hedge.

    A decision at daily close t uses only settlements at or before t and earns
    the close-to-close interval that follows. Positive funding is received by
    the short perp. Capital finances both notionals, so returns are not levered
    to the spot leg alone.

    Warmup: no entry while the trailing funding window reaches back before the
    first observed daily bar, so the first ``lookback_days`` days stay flat.
    """
    timestamps = np.asarray(ts_open_ns, dtype=np.int64)
    spot = np.asarray(spot_close, dtype=float)
    perp = np.asarray(perp_close, dtype=float)
    funding_times = np.asarray(funding_ts_ns, dtype=np.int64)
    rates = np.asarray(funding_rates, dtype=float)
    _validate(
        timestamps, spot, perp, funding_times, rates,
        lookback_days, spot_cost_bps, perp_cost_bps, mode,
    )

    n_intervals = timestamps.size - 1
    position = np.zeros(n_intervals)
    price_returns = np.zeros(n_intervals)
    funding_returns = np.zeros(n_intervals)
    fee_returns = np.zeros(n_intervals)
    net_returns = np.zeros(n_intervals)
    equity = 1.0
    qty = 0.0
    held = False
    lookback_ns = lookback_days * _DAY_NS

    for i in range(n_intervals):
        equity_before = equity
        decision_time = int(timestamps[i] + _DAY_NS)
        next_time = int(timestamps[i + 1] + _DAY_NS)
        spot_now, perp_now = float(spot[i]), float(perp[i])
        basis = perp_now / spot_now - 1.0
        window_start = decision_time - lookback_ns
        trailing = _sum_between(funding_times, rates, window_start, decision_time)
        # Warmup: no entry until the trailing window is covered by observed
        # data, i.e. it no longer reaches back before the first daily bar.
        warmup = window_start < int(timestamps[0])
        target = _target_position(
            mode, warmup, held, trailing, basis,
            entry_funding_sum, exit_funding_sum, entry_basis, exit_basis,
        )
        fee = 0.0
        if target and not held:
            qty = equity / (spot_now + perp_now)
            fee = _transaction_cost(qty, spot_now, perp_now, spot_cost_bps, perp_cost_bps)
            equity -= fee
            held = True
        elif held and not target:
            fee = _transaction_cost(qty, spot_now, perp_now, spot_cost_bps, perp_cost_bps)
            equity -= fee
            qty = 0.0
            held = False

        price_pnl = 0.0
        funding_pnl = 0.0
        if held:
            price_pnl = qty * (
                (float(spot[i + 1]) - spot_now) - (float(perp[i + 1]) - perp_now)
            )
            interval_funding = _sum_between(funding_times, rates, decision_time, next_time)
            funding_pnl = qty * perp_now * interval_funding
            equity += price_pnl + funding_pnl
        if equity <= 0.0 or not np.isfinite(equity):
            raise ValueError("account equity exhausted during cash-and-carry simulation")

        position[i] = 1.0 if held else 0.0
        price_returns[i] = price_pnl / equity_before
        funding_returns[i] = funding_pnl / equity_before
        fee_returns[i] = fee / equity_before
        net_returns[i] = equity / equity_before - 1.0

    return CarryResult(
        ts_ns=timestamps[:-1] + _DAY_NS,
        position=position,
        price_returns=price_returns,
        funding_returns=funding_returns,
        fee_returns=fee_returns,
        net_returns=net_returns,
    )


def _target_position(
    mode: str,
    warmup: bool,
    held: bool,
    trailing_funding: float,
    basis: float,
    entry_funding_sum: float,
    exit_funding_sum: float,
    entry_basis: float,
    exit_basis: float,
) -> bool:
    if warmup:
        return False
    if mode == "always":
        return True
    if held:
        return not (trailing_funding <= exit_funding_sum or basis <= exit_basis)
    return trailing_funding >= entry_funding_sum and basis >= entry_basis


def _transaction_cost(
    qty: float, spot: float, perp: float, spot_cost_bps: float, perp_cost_bps: float
) -> float:
    return qty * spot * spot_cost_bps / 1e4 + qty * perp * perp_cost_bps / 1e4


def _sum_between(
    timestamps: np.ndarray, rates: np.ndarray, start_exclusive: int, end_inclusive: int
) -> float:
    if timestamps.size == 0:
        return 0.0
    first = int(np.searchsorted(timestamps, start_exclusive, side="right"))
    last = int(np.searchsorted(timestamps, end_inclusive, side="right"))
    return float(rates[first:last].sum())


def _validate(
    timestamps: np.ndarray,
    spot: np.ndarray,
    perp: np.ndarray,
    funding_times: np.ndarray,
    rates: np.ndarray,
    lookback_days: int,
    spot_cost_bps: float,
    perp_cost_bps: float,
    mode: str,
) -> None:
    if mode not in {"filtered", "always"}:
        raise ValueError(f"unsupported mode {mode!r}")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if spot_cost_bps < 0 or perp_cost_bps < 0:
        raise ValueError("costs must be non-negative")
    if timestamps.ndim != 1 or spot.shape != timestamps.shape or perp.shape != timestamps.shape:
        raise ValueError("spot and perp closes must align with daily timestamps")
    if timestamps.size < lookback_days + 2:
        raise ValueError("not enough daily bars for the funding lookback")
    if np.any(np.diff(timestamps) != _DAY_NS):
        raise ValueError("prices must be consecutive daily bars")
    if not np.all(np.isfinite(spot)) or not np.all(np.isfinite(perp)):
        raise ValueError("prices must be finite")
    if np.any(spot <= 0) or np.any(perp <= 0):
        raise ValueError("prices must be positive")
    if funding_times.shape != rates.shape or funding_times.ndim != 1:
        raise ValueError("funding timestamps and rates must be aligned 1D arrays")
    if funding_times.size and np.any(np.diff(funding_times) <= 0):
        raise ValueError("funding timestamps must be strictly increasing")
    if not np.all(np.isfinite(rates)):
        raise ValueError("funding rates must be finite")
