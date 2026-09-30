"""Run metrics: performance, trade and cost statistics (all net of costs).

Conventions:
- Sharpe/Sortino annualized with sqrt(365 * 86400 / interval_s) (crypto 24/7),
  computed from per-bar equity returns, population std (ddof=0).
- Sortino downside deviation: sqrt(mean of squared negative returns) over the
  FULL sample size.
- t-stat of expectancy: mean(net) / (sample std (ddof=1) / sqrt(n)).
- All trade/cost fields are None when there are no trades (never zero, never
  a crash) — spec FR-010.
"""
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from tradingv2.backtest.engine import RoundTrip


@dataclass(frozen=True)
class MetricsReport:
    """Frozen metrics snapshot of one run."""

    n_bars: int
    total_return: float
    max_drawdown: float
    calmar: float | None
    sharpe: float | None
    sortino: float | None
    n_trades: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    payoff: float | None
    profit_factor: float | None
    expectancy_bps: float | None
    avg_hold_ns: float | None
    gross_total: float | None
    fees_total: float | None
    slippage_total: float | None
    funding_total: float | None
    net_total: float | None
    fee_drag: float | None
    t_stat: float | None


@dataclass
class _ReturnStats:
    mean: float
    std: float | None
    downside_std: float | None


def _return_stats(returns: list[float]) -> _ReturnStats:
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / n
    std = variance**0.5 if n > 0 else None
    downside = [r for r in returns if r < 0]
    downside_var = sum(r**2 for r in downside) / n
    downside_std = downside_var**0.5 if downside else None
    return _ReturnStats(mean=mean, std=std, downside_std=downside_std)


def compute_metrics(
    equity: pl.DataFrame,
    round_trips: list[RoundTrip],
    interval_ns: int,
) -> MetricsReport:
    """Compute the full metrics report from run artifacts."""
    values = equity["equity"].to_list()
    if not values:
        raise ValueError("equity curve is empty")
    initial, final = values[0], values[-1]
    total_return = final / initial - 1 if initial > 0 else None

    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)

    returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1] > 0]
    stats = (
        _return_stats(returns)
        if returns
        else _ReturnStats(mean=0.0, std=None, downside_std=None)
    )
    annual_factor = math.sqrt(365 * 86_400 / (interval_ns / 1e9)) if interval_ns > 0 else None

    sharpe = (
        stats.mean / stats.std * annual_factor
        if stats.std is not None and stats.std > 0 and annual_factor is not None
        else None
    )
    sortino = (
        stats.mean / stats.downside_std * annual_factor
        if stats.downside_std is not None and stats.downside_std > 0 and annual_factor is not None
        else None
    )
    calmar = total_return / max_drawdown if total_return is not None and max_drawdown > 0 else None

    n_trades = len(round_trips)
    if n_trades == 0:
        return MetricsReport(
            n_bars=len(values),
            total_return=total_return or 0.0,
            max_drawdown=max_drawdown,
            calmar=calmar,
            sharpe=sharpe,
            sortino=sortino,
            n_trades=0,
            win_rate=None,
            avg_win=None,
            avg_loss=None,
            payoff=None,
            profit_factor=None,
            expectancy_bps=None,
            avg_hold_ns=None,
            gross_total=None,
            fees_total=None,
            slippage_total=None,
            funding_total=None,
            net_total=None,
            fee_drag=None,
            t_stat=None,
        )

    nets = [trip.net for trip in round_trips]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    win_rate = len(wins) / n_trades
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = abs(sum(losses) / len(losses)) if losses else None
    payoff = avg_win / avg_loss if avg_win is not None and avg_loss and avg_loss > 0 else None
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = None
    if losses and gross_loss > 0:
        profit_factor = gross_win / gross_loss
    elif wins:
        profit_factor = None  # all-winning: infinity (displayed as such)

    avg_entry_notional = sum(t.entry_price * t.qty for t in round_trips) / n_trades
    expectancy = sum(nets) / n_trades
    expectancy_bps = (
        expectancy / avg_entry_notional * 1e4 if avg_entry_notional > 0 else None
    )
    avg_hold_ns = sum(t.hold_ns for t in round_trips) / n_trades

    gross_total = sum(t.gross for t in round_trips)
    fees_total = sum(t.fees for t in round_trips)
    slippage_total = sum(t.slippage for t in round_trips)
    funding_total = sum(t.funding for t in round_trips)
    net_total = sum(nets)
    fee_drag = fees_total / gross_total if gross_total > 0 else None

    t_stat: float | None = None
    if n_trades >= 2:
        variance_sample = sum((x - expectancy) ** 2 for x in nets) / (n_trades - 1)
        if variance_sample > 0:
            se = (variance_sample / n_trades) ** 0.5
            t_stat = expectancy / se

    return MetricsReport(
        n_bars=len(values),
        total_return=total_return or 0.0,
        max_drawdown=max_drawdown,
        calmar=calmar,
        sharpe=sharpe,
        sortino=sortino,
        n_trades=n_trades,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff=payoff,
        profit_factor=profit_factor,
        expectancy_bps=expectancy_bps,
        avg_hold_ns=avg_hold_ns,
        gross_total=gross_total,
        fees_total=fees_total,
        slippage_total=slippage_total,
        funding_total=funding_total,
        net_total=net_total,
        fee_drag=fee_drag,
        t_stat=t_stat,
    )


def metrics_to_json(report: MetricsReport) -> dict[str, Any]:
    """JSON-serializable form (None kept as null)."""
    return {key: getattr(report, key) for key in report.__dataclass_fields__}


def metrics_from_json(raw: dict[str, Any]) -> MetricsReport:
    """Rebuild a report from its JSON form."""
    return MetricsReport(**raw)


@dataclass(frozen=True)
class RegimeMetrics:
    """Metrics of one volatility regime (bucket of bars)."""

    label: str  # "low" | "mid" | "high"
    n_bars: int
    total_return: float | None
    max_drawdown: float | None
    sharpe: float | None
    vol_mean: float | None = None


def regime_split(
    equity: pl.DataFrame,
    close: pl.Series,
    interval_ns: int,
    vol_window: int = 60,
) -> list[RegimeMetrics]:
    """Split the run by realized-volatility terciles and report per regime.

    Volatility: rolling std of close returns (population). Bars with an
    undefined vol (window not full) are excluded. With too few defined bars
    the whole run is a single "low" bucket.
    """
    closes = close.to_numpy()
    n = len(closes)
    if n < 2:
        return []
    returns = np.diff(closes) / closes[:-1]
    eq_values = equity["equity"].to_list()
    # vol of bar i (i >= 1) = std of returns[i-vol_window : i] → bar index offset
    vols = np.full(n, np.nan)
    if len(returns) >= vol_window:
        windows = np.lib.stride_tricks.sliding_window_view(returns, vol_window)
        vols[vol_window:] = windows.std(axis=1)
    defined = np.nonzero(~np.isnan(vols))[0]
    if defined.size == 0:
        return []
    vols_defined = vols[defined]
    q33, q66 = np.percentile(vols_defined, [33.3, 66.7])
    buckets: dict[str, list[int]] = {"low": [], "mid": [], "high": []}
    for idx in defined:
        v = vols[idx]
        label = "low" if v <= q33 else ("high" if v > q66 else "mid")
        buckets[label].append(int(idx))
    if sum(len(b) for b in buckets.values()) <= vol_window:
        buckets = {"low": [int(i) for i in defined]}
        labels = ["low"]
    else:
        labels = ["low", "mid", "high"]
    annual = math.sqrt(365 * 86_400 / (interval_ns / 1e9)) if interval_ns > 0 else None
    out: list[RegimeMetrics] = []
    for label in labels:
        indices = buckets.get(label, [])
        if not indices:
            continue
        vols_sub = [float(vols[i]) for i in indices]
        vol_mean = sum(vols_sub) / len(vols_sub)
        eq_sub = [eq_values[i] for i in indices]
        first, last = eq_sub[0], eq_sub[-1]
        total_return = last / first - 1 if first > 0 else None
        peak = eq_sub[0]
        max_dd = 0.0
        for value in eq_sub:
            peak = max(peak, value)
            if peak > 0:
                max_dd = max(max_dd, (peak - value) / peak)
        rets = (
            [eq_sub[i] / eq_sub[i - 1] - 1 for i in range(1, len(eq_sub)) if eq_sub[i - 1] > 0]
            if len(eq_sub) > 1
            else []
        )
        sharpe = None
        if rets and annual is not None:
            mean = sum(rets) / len(rets)
            variance = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = variance**0.5
            if std > 0:
                sharpe = mean / std * annual
        out.append(
            RegimeMetrics(
                label=label,
                n_bars=len(indices),
                total_return=total_return,
                max_drawdown=max_dd,
                sharpe=sharpe,
                vol_mean=vol_mean,
            )
        )
    return out
