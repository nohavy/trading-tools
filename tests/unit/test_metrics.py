"""Tests for run metrics (golden recomputations, net-of-costs accounting)."""

import math

import polars as pl
import pytest

from tradingv2.backtest.engine import RoundTrip
from tradingv2.metrics.compute import compute_metrics

SECOND = 1_000_000_000


def make_equity(values: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_ns": [(i + 1) * SECOND for i in range(len(values))],
            "equity": values,
        }
    )


def make_trips(*nets: tuple[float, float, float, float, float]) -> list[RoundTrip]:
    """Each tuple: (entry_price, qty, gross, fees, net) — slippage/funding 0."""
    trips = []
    for i, (entry_price, qty, gross, fees, net) in enumerate(nets):
        trips.append(
            RoundTrip(
                entry_ts=i * SECOND,
                exit_ts=(i + 1) * SECOND,
                side="buy",
                qty=qty,
                entry_price=entry_price,
                exit_price=entry_price + 1.0,
                gross=gross,
                fees=fees,
                slippage=0.0,
                funding=0.0,
                net=net,
                hold_ns=SECOND,
            )
        )
    return trips


EQUITY = [1000.0, 1010.0, 1005.0, 1015.0, 1020.0]
TRIPS = make_trips(
    (100.0, 0.002, 5.0, 0.02, 4.97),
    (200.0, 0.002, -3.0, 0.03, -3.06),
)


def test_total_return_and_drawdown() -> None:
    report = compute_metrics(make_equity(EQUITY), TRIPS, SECOND)
    assert report.total_return == pytest.approx(0.02)
    # peak 1010 -> trough 1005: drawdown 5/1010
    assert report.max_drawdown == pytest.approx(5.0 / 1010.0)
    assert report.calmar == pytest.approx(0.02 / (5.0 / 1010.0))


def test_sharpe_sortino_365_days() -> None:
    report = compute_metrics(make_equity(EQUITY), TRIPS, SECOND)
    returns = [1010 / 1000 - 1, 1005 / 1010 - 1, 1015 / 1005 - 1, 1020 / 1015 - 1]
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = var**0.5
    annual = math.sqrt(365 * 86_400)  # 1s bars, crypto 24/7
    assert report.sharpe == pytest.approx(mean / std * annual)
    downside = [r for r in returns if r < 0]
    dstd = (sum(r**2 for r in downside) / len(returns)) ** 0.5  # full-sample downside dev
    assert report.sortino == pytest.approx(mean / dstd * annual)


def test_trade_statistics() -> None:
    report = compute_metrics(make_equity(EQUITY), TRIPS, SECOND)
    assert report.n_trades == 2
    assert report.win_rate == pytest.approx(0.5)
    assert report.avg_win == pytest.approx(4.97)
    assert report.avg_loss == pytest.approx(3.06)
    assert report.payoff == pytest.approx(4.97 / 3.06)
    assert report.profit_factor == pytest.approx(4.97 / 3.06)
    assert report.expectancy_bps == pytest.approx(
        (4.97 - 3.06) / 2 / ((100.0 * 0.002 + 200.0 * 0.002) / 2) * 1e4
    )
    assert report.avg_hold_ns == pytest.approx(SECOND)


def test_costs_decomposition() -> None:
    report = compute_metrics(make_equity(EQUITY), TRIPS, SECOND)
    assert report.gross_total == pytest.approx(2.0)
    assert report.fees_total == pytest.approx(0.05)
    assert report.slippage_total == pytest.approx(0.0)
    assert report.funding_total == pytest.approx(0.0)
    assert report.net_total == pytest.approx(1.91)
    assert report.fee_drag == pytest.approx(0.05 / 2.0)


def test_t_stat_expectancy() -> None:
    report = compute_metrics(make_equity(EQUITY), TRIPS, SECOND)
    nets = [4.97, -3.06]
    n = len(nets)
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / (n - 1)
    se = (var / n) ** 0.5
    assert report.t_stat == pytest.approx(mean / se)
