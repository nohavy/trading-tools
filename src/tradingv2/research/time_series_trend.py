"""Daily time-series trend research with close-only signals and perp funding."""

from dataclasses import dataclass

import numpy as np

from tradingv2.research.cross_section import newey_west_tstat

_DAY_NS = 86_400_000_000_000
_BAR_CLOSE_OFFSET_NS = _DAY_NS
_DAYS_PER_YEAR = 365.0
_MINUTE_NS = 60_000_000_000


def funding_mark_prices(
    funding_ts_ns: np.ndarray,
    minute_ts_open_ns: np.ndarray,
    minute_open: np.ndarray,
    minute_close: np.ndarray,
) -> np.ndarray:
    """Price each funding settlement using the last completed 1m close.

    If the previous minute is absent, the settlement-minute open is used; its
    close would be lookahead.
    """
    funding_times = np.asarray(funding_ts_ns, dtype=np.int64)
    minute_times = np.asarray(minute_ts_open_ns, dtype=np.int64)
    opens = np.asarray(minute_open, dtype=float)
    closes = np.asarray(minute_close, dtype=float)
    if minute_times.ndim != 1 or opens.ndim != 1 or closes.ndim != 1:
        raise ValueError("minute timestamps and prices must be 1D arrays")
    if minute_times.size != opens.size or minute_times.size != closes.size:
        raise ValueError("minute timestamps and open/close prices must have equal lengths")
    if np.any(np.diff(minute_times) <= 0):
        raise ValueError("minute timestamps must be strictly increasing")
    if not np.all(np.isfinite(opens)) or not np.all(np.isfinite(closes)):
        raise ValueError("minute open and close prices must be finite")
    if np.any(opens <= 0.0) or np.any(closes <= 0.0):
        raise ValueError("minute open and close prices must be positive")

    marks = np.empty(funding_times.size, dtype=float)
    for i, timestamp in enumerate(funding_times):
        minute_open_ts = (int(timestamp) // _MINUTE_NS) * _MINUTE_NS
        previous_minute_ts = minute_open_ts - _MINUTE_NS
        previous_index = int(np.searchsorted(minute_times, previous_minute_ts))
        has_previous = (
            previous_index < minute_times.size
            and minute_times[previous_index] == previous_minute_ts
        )
        if has_previous:
            marks[i] = closes[previous_index]
            continue
        current_index = int(np.searchsorted(minute_times, minute_open_ts))
        if current_index < minute_times.size and minute_times[current_index] == minute_open_ts:
            marks[i] = opens[current_index]
            continue
        raise ValueError(f"no completed minute price available before funding at {timestamp}")
    return marks


@dataclass(frozen=True)
class TrendResult:
    """Daily interval returns and the accounting components for one instrument."""

    ts_open_ns: np.ndarray
    positions: np.ndarray
    market_returns: np.ndarray
    funding_returns: np.ndarray
    fee_returns: np.ndarray
    turnover: np.ndarray
    net_returns: np.ndarray


def simulate_time_series_trend(
    ts_open_ns: np.ndarray,
    close: np.ndarray,
    funding_ts_ns: np.ndarray,
    funding_rates: np.ndarray,
    funding_prices: np.ndarray | None = None,
    *,
    lookback_days: int,
    mode: str,
    fee_per_side_bps: float,
    slippage_per_side_bps: float = 0.0,
) -> TrendResult:
    """Simulate a 1x daily trend position; decisions at close t earn t→t+1.

    `mode` is `long_short` (position = sign of the trailing return), `long_flat`
    (long only when the trailing return is positive), or `buy_hold`. Each
    funding settlement in the close-to-close interval is charged to the
    position in force during that interval. Fees and slippage are charged on
    actual notional traded to restore target exposure at each daily close,
    including signal flips and rebalancing caused by short/equity drift.
    """
    timestamps = np.asarray(ts_open_ns, dtype=np.int64)
    prices = np.asarray(close, dtype=float)
    funding_times = np.asarray(funding_ts_ns, dtype=np.int64)
    rates = np.asarray(funding_rates, dtype=float)
    mark_prices = (
        None if funding_prices is None else np.asarray(funding_prices, dtype=float)
    )

    if mode not in {"long_short", "long_flat", "buy_hold"}:
        raise ValueError(f"unsupported mode {mode!r}")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if fee_per_side_bps < 0 or slippage_per_side_bps < 0:
        raise ValueError("fees and slippage must be non-negative")
    if timestamps.ndim != 1 or prices.ndim != 1 or timestamps.size != prices.size:
        raise ValueError("timestamps and close must be 1D arrays with equal lengths")
    if timestamps.size < 2:
        raise ValueError("at least two daily bars are required")
    if not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("close prices must be finite and positive")
    if np.any(np.diff(timestamps) <= 0):
        raise ValueError("daily timestamps must be strictly increasing")
    if np.any(np.diff(timestamps) != _DAY_NS):
        raise ValueError("bar timestamps must be consecutive daily opens")
    if funding_times.ndim != 1 or rates.ndim != 1 or funding_times.size != rates.size:
        raise ValueError("funding timestamps and rates must be 1D arrays with equal lengths")
    if np.any(np.diff(funding_times) <= 0):
        raise ValueError("funding timestamps must be strictly increasing")
    if not np.all(np.isfinite(rates)):
        raise ValueError("funding rates must be finite")
    if mark_prices is not None:
        if mark_prices.ndim != 1 or mark_prices.size != rates.size:
            raise ValueError("funding prices must match the funding timestamps")
        if not np.all(np.isfinite(mark_prices)) or np.any(mark_prices <= 0.0):
            raise ValueError("funding prices must be finite and positive")

    n_intervals = prices.size - 1
    positions = np.zeros(n_intervals, dtype=float)
    if mode == "buy_hold":
        positions.fill(1.0)
    else:
        for i in range(lookback_days, n_intervals):
            trailing_return = prices[i] / prices[i - lookback_days] - 1.0
            if mode == "long_short":
                positions[i] = float(np.sign(trailing_return))
            elif trailing_return > 0.0:
                positions[i] = 1.0

    market_returns = prices[1:] / prices[:-1] - 1.0
    turnover = np.zeros(n_intervals, dtype=float)
    fee_returns = np.zeros(n_intervals, dtype=float)
    funding_returns = np.zeros(n_intervals, dtype=float)
    net_returns = np.zeros(n_intervals, dtype=float)
    equity = 1.0
    quantity = 0.0
    cost_per_side = (fee_per_side_bps + slippage_per_side_bps) / 1e4
    for i, position in enumerate(positions):
        start_price = prices[i]
        target_quantity = position * equity / start_price
        turnover[i] = abs(target_quantity - quantity) * start_price / equity
        fee_returns[i] = turnover[i] * cost_per_side

        interval_start = timestamps[i] + _BAR_CLOSE_OFFSET_NS
        interval_end = timestamps[i + 1] + _BAR_CLOSE_OFFSET_NS
        first = int(np.searchsorted(funding_times, interval_start, side="right"))
        after_last = int(np.searchsorted(funding_times, interval_end, side="right"))
        if position != 0.0 and first < after_last:
            interval_rates = rates[first:after_last]
            if mark_prices is None:
                marked_funding = float(interval_rates.sum())
            else:
                marked_funding = float(
                    interval_rates @ mark_prices[first:after_last] / start_price
                )
            funding_returns[i] = -position * marked_funding

        net_returns[i] = (
            position * market_returns[i] + funding_returns[i] - fee_returns[i]
        )
        equity *= 1.0 + net_returns[i]
        if equity <= 0.0 or not np.isfinite(equity):
            raise ValueError("account equity exhausted during the simulation")
        quantity = target_quantity

    return TrendResult(
        ts_open_ns=timestamps[:-1].copy(),
        positions=positions,
        market_returns=market_returns,
        funding_returns=funding_returns,
        fee_returns=fee_returns,
        turnover=turnover,
        net_returns=net_returns,
    )


def summarize_trend(
    result: TrendResult,
    *,
    start_ns: int | None = None,
    end_ns: int | None = None,
    hac_lag: int = 20,
) -> dict[str, float | int | None]:
    """Summarize a chronological segment of a trend result.

    Returns are compounded daily at 1x notional/equity. HAC t-statistics use
    Newey-West with the requested lag to account for serial correlation.
    """
    return summarize_daily_series(
        result.ts_open_ns,
        result.net_returns,
        np.abs(result.positions),
        result.turnover,
        result.positions * result.market_returns,
        result.fee_returns,
        result.funding_returns,
        start_ns=start_ns,
        end_ns=end_ns,
        hac_lag=hac_lag,
    )


def summarize_equal_weight_portfolio(
    results: list[TrendResult],
    *,
    start_ns: int | None = None,
    end_ns: int | None = None,
    hac_lag: int = 20,
) -> dict[str, float | int | None]:
    """Summarize an equal-capital portfolio of aligned instruments."""
    if not results:
        raise ValueError("at least one instrument result is required")
    timestamps = results[0].ts_open_ns
    if any(not np.array_equal(item.ts_open_ns, timestamps) for item in results[1:]):
        raise ValueError("portfolio instruments must have aligned daily timestamps")
    return summarize_daily_series(
        timestamps,
        np.mean([item.net_returns for item in results], axis=0),
        np.mean([np.abs(item.positions) for item in results], axis=0),
        np.mean([item.turnover for item in results], axis=0),
        np.mean(
            [item.positions * item.market_returns for item in results], axis=0
        ),
        np.mean([item.fee_returns for item in results], axis=0),
        np.mean([item.funding_returns for item in results], axis=0),
        start_ns=start_ns,
        end_ns=end_ns,
        hac_lag=hac_lag,
    )


def summarize_daily_equity_curve(
    ts_ns: np.ndarray,
    equity: np.ndarray,
    *,
    start_ns: int,
    end_ns: int,
    hac_lag: int = 20,
) -> dict[str, float | int | None]:
    """Extract UTC-midnight marks and summarize an event-engine equity curve."""
    if hac_lag < 0:
        raise ValueError("hac_lag must be non-negative")
    timestamps = np.asarray(ts_ns, dtype=np.int64)
    values = np.asarray(equity, dtype=float)
    if timestamps.ndim != 1 or values.ndim != 1 or timestamps.size != values.size:
        raise ValueError("equity timestamps and values must be 1D arrays with equal lengths")
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("equity values must be finite and positive")
    mask = (
        (timestamps >= start_ns)
        & (timestamps <= end_ns)
        & (timestamps % _DAY_NS == 0)
    )
    daily_ts, daily_equity = timestamps[mask], values[mask]
    if daily_equity.size < 2:
        raise ValueError("not enough daily OOS equity points")
    order = np.argsort(daily_ts)
    daily_ts, daily_equity = daily_ts[order], daily_equity[order]
    keep = np.r_[daily_ts[1:] != daily_ts[:-1], True]
    daily_ts, daily_equity = daily_ts[keep], daily_equity[keep]
    if np.any(np.diff(daily_ts) != _DAY_NS):
        raise ValueError("missing daily OOS equity point")

    returns = daily_equity[1:] / daily_equity[:-1] - 1.0
    n_days = returns.size
    total_return = float(daily_equity[-1] / daily_equity[0] - 1.0)
    cagr = float((daily_equity[-1] / daily_equity[0]) ** (_DAYS_PER_YEAR / n_days) - 1.0)
    daily_vol = float(np.std(returns, ddof=1))
    sharpe = (
        float(np.mean(returns) / daily_vol * np.sqrt(_DAYS_PER_YEAR))
        if daily_vol > 0
        else None
    )
    normalized_equity = daily_equity / daily_equity[0]
    peaks = np.maximum.accumulate(np.r_[1.0, normalized_equity])[1:]
    hac_t = newey_west_tstat(returns.tolist(), hac_lag)
    return {
        "n_days": int(n_days),
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": daily_vol * np.sqrt(_DAYS_PER_YEAR),
        "sharpe": sharpe,
        "t_stat_nw": float(hac_t) if np.isfinite(hac_t) else None,
        "max_drawdown": float(np.max(1.0 - normalized_equity / peaks)),
        "start_equity": float(daily_equity[0]),
        "end_equity": float(daily_equity[-1]),
    }


def holdout_screen(
    candidate_returns: dict[str, float],
    *,
    candidate_portfolio_return: float,
    benchmark_portfolio_return: float,
    rejected_exits: int,
) -> dict[str, object]:
    """Apply the pre-registered one-month replication screen (never a GO gate)."""
    if set(candidate_returns) != {"BTCUSDT", "ETHUSDT"}:
        raise ValueError("holdout requires exactly BTCUSDT and ETHUSDT")
    if any(not np.isfinite(value) for value in candidate_returns.values()):
        raise ValueError("candidate returns must be finite")
    if not np.isfinite(candidate_portfolio_return):
        raise ValueError("candidate portfolio return must be finite")
    if not np.isfinite(benchmark_portfolio_return):
        raise ValueError("benchmark return must be finite")
    if rejected_exits < 0:
        raise ValueError("rejected_exits must be non-negative")

    checks = {
        "btc_positive": candidate_returns["BTCUSDT"] > 0.0,
        "eth_positive": candidate_returns["ETHUSDT"] > 0.0,
        "beats_equal_weight_buy_hold": candidate_portfolio_return
        > benchmark_portfolio_return,
        "no_rejected_exits": rejected_exits == 0,
    }
    return {
        "candidate_survives_month": all(checks.values()),
        "checks": checks,
        "rejected_exits": rejected_exits,
        "is_go_verdict": False,
    }


def summarize_daily_series(
    ts_open_ns: np.ndarray,
    net_returns: np.ndarray,
    exposure: np.ndarray,
    turnover: np.ndarray,
    gross_price_returns: np.ndarray,
    fee_returns: np.ndarray,
    funding_returns: np.ndarray,
    *,
    start_ns: int | None = None,
    end_ns: int | None = None,
    hac_lag: int = 20,
) -> dict[str, float | int | None]:
    """Summarize aligned daily portfolio series and their accounting components."""
    if hac_lag < 0:
        raise ValueError("hac_lag must be non-negative")
    arrays = [
        np.asarray(values, dtype=float)
        for values in (
            net_returns,
            exposure,
            turnover,
            gross_price_returns,
            fee_returns,
            funding_returns,
        )
    ]
    timestamps = np.asarray(ts_open_ns, dtype=np.int64)
    if timestamps.ndim != 1 or any(a.ndim != 1 or a.size != timestamps.size for a in arrays):
        raise ValueError("daily summary arrays must be 1D and equally sized")
    mask = np.ones(timestamps.size, dtype=bool)
    if start_ns is not None:
        mask &= timestamps >= start_ns
    if end_ns is not None:
        mask &= timestamps <= end_ns
    returns, exposure_a, turnover_a, gross_a, fees_a, funding_a = [a[mask] for a in arrays]
    if returns.size == 0:
        raise ValueError("no daily returns in the requested period")
    if any(not np.all(np.isfinite(a)) for a in arrays):
        raise ValueError("daily summary arrays must be finite")

    equity = np.cumprod(1.0 + returns)
    total_return = float(equity[-1] - 1.0)
    annualized_return = (
        float(equity[-1] ** (_DAYS_PER_YEAR / returns.size) - 1.0)
        if equity[-1] > 0.0
        else None
    )
    daily_vol = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
    sharpe = (
        float(np.mean(returns) / daily_vol * np.sqrt(_DAYS_PER_YEAR))
        if daily_vol > 0.0
        else None
    )
    equity_with_initial = np.r_[1.0, equity]
    peaks = np.maximum.accumulate(equity_with_initial)
    drawdowns = 1.0 - equity_with_initial / peaks
    hac_t = newey_west_tstat(returns.tolist(), hac_lag)
    return {
        "n_days": int(returns.size),
        "total_return": total_return,
        "cagr": annualized_return,
        "annualized_volatility": daily_vol * np.sqrt(_DAYS_PER_YEAR),
        "sharpe": sharpe,
        "max_drawdown": float(np.max(drawdowns)),
        "t_stat_nw": float(hac_t) if np.isfinite(hac_t) else None,
        "average_exposure": float(np.mean(exposure_a)),
        "fraction_exposed": float(np.mean(exposure_a > 0.0)),
        "turnover_units": float(np.sum(turnover_a)),
        "annual_turnover_units": float(
            np.sum(turnover_a) / (returns.size / _DAYS_PER_YEAR)
        ),
        "gross_price_bps": float(np.sum(gross_a) * 1e4),
        "fees_bps": float(np.sum(fees_a) * 1e4),
        "funding_bps": float(np.sum(funding_a) * 1e4),
    }
