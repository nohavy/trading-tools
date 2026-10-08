"""Market-neutral spot long / perpetual short cash-and-carry research model."""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

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


def daily_close_before(
    data_root: Path, directory: Path, symbol: str, date: dt.date
) -> float:
    """The last daily close at or before midnight of ``date`` (runner convention)."""
    path = directory / f"{symbol}-1d-{date.year}-{date.month:02d}.parquet"
    bars = pl.read_parquet(path).sort("ts_open_ns")
    boundary_ns = int(
        dt.datetime.combine(date, dt.time(0, 0), tzinfo=dt.UTC).timestamp()
    ) * 1_000_000_000
    rows = bars.filter(pl.col("ts_open_ns") <= boundary_ns - 1).tail(1)
    if rows.height != 1:
        raise FileNotFoundError(f"no daily bar before {date} for {symbol} under {directory}")
    return float(rows["close"][0])


def carry_qty(data_root: Path, config: dict[str, object]) -> float:
    """Shared sizing: runner, bear replication and paper use the exact same rule."""
    symbol = str(config["symbol"])
    qty_date = dt.date.fromisoformat(str(config.get("qty_date", "2023-06-30")))
    spot = daily_close_before(
        data_root,
        data_root / "parquet" / "spot" / "klines" / symbol / "1d",
        symbol,
        qty_date,
    )
    perp = daily_close_before(data_root, data_root / "daily" / "um" / symbol, symbol, qty_date)
    return hedge_qty(
        spot,
        perp,
        float(str(config["total_capital"])),
        float(str(config["hedge_fraction"])),
    )


def hedge_qty(
    spot_close: float, perp_close: float, total_capital: float, hedge_fraction: float
) -> float:
    """Hedge quantity: capital fraction spread evenly across the two legs.

    The fraction stays below 1 so entry fees and slippage can never exceed a
    leg's cash balance or margin.
    """
    if total_capital <= 0.0:
        raise ValueError("total_capital must be positive")
    if not 0.0 < hedge_fraction < 1.0:
        raise ValueError("hedge_fraction must be in (0, 1)")
    for value, name in ((spot_close, "spot_close"), (perp_close, "perp_close")):
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and positive")
    return hedge_fraction * total_capital / (spot_close + perp_close)


def combine_leg_equities(
    ts_spot: np.ndarray, eq_spot: np.ndarray, ts_perp: np.ndarray, eq_perp: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Sum two aligned daily leg equity curves into one portfolio curve."""
    spot_ts = np.asarray(ts_spot, dtype=np.int64)
    spot_eq = np.asarray(eq_spot, dtype=float)
    perp_ts = np.asarray(ts_perp, dtype=np.int64)
    perp_eq = np.asarray(eq_perp, dtype=float)
    if spot_ts.shape != spot_eq.shape or perp_ts.shape != perp_eq.shape:
        raise ValueError("leg timestamps and equity values must be equally sized")
    if not np.array_equal(spot_ts, perp_ts):
        raise ValueError("leg daily marks do not align")
    return spot_ts, spot_eq + perp_eq


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
