"""Tests for degenerate metric cases (no trades, infinite PF, zero variance)."""

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


def trip(net: float, entry_price: float = 100.0, qty: float = 0.002) -> RoundTrip:
    return RoundTrip(
        entry_ts=0, exit_ts=SECOND, side="buy", qty=qty, entry_price=entry_price,
        exit_price=entry_price + 1, gross=net, fees=0.0, slippage=0.0, funding=0.0,
        net=net, hold_ns=SECOND,
    )


def test_zero_trades_trade_fields_are_none() -> None:
    report = compute_metrics(make_equity([1000.0, 1010.0, 1005.0]), [], SECOND)
    assert report.n_trades == 0
    for field in ("win_rate", "avg_win", "avg_loss", "payoff", "profit_factor", "expectancy_bps"):
        assert getattr(report, field) is None
    for field in ("gross_total", "fees_total", "slippage_total", "funding_total", "net_total"):
        assert getattr(report, field) is None
    assert report.fee_drag is None
    assert report.t_stat is None
    # performance metrics still computed from equity
    assert report.total_return == pytest.approx(0.005)
    assert report.max_drawdown == pytest.approx(5.0 / 1010.0)
    assert report.sharpe is not None


def test_flat_equity_zero_variance_gives_none() -> None:
    report = compute_metrics(make_equity([1000.0] * 5), [], SECOND)
    assert report.sharpe is None  # std == 0
    assert report.sortino is None  # no downside at all
    assert report.max_drawdown == 0.0
    assert report.calmar is None  # division by zero drawdown
    assert report.total_return == pytest.approx(0.0)


def test_all_winning_profit_factor_is_none() -> None:
    report = compute_metrics(make_equity([1000.0, 1010.0]), [trip(5.0), trip(3.0)], SECOND)
    assert report.n_trades == 2
    assert report.win_rate == 1.0
    assert report.profit_factor is None  # infinity, never zero artifacts
    assert report.payoff is None  # no losing trade to compare against


def test_all_losing_profit_factor_zero() -> None:
    report = compute_metrics(make_equity([1000.0, 990.0]), [trip(-5.0), trip(-3.0)], SECOND)
    assert report.win_rate == 0.0
    assert report.profit_factor == pytest.approx(0.0)
    assert report.avg_win is None
    assert report.avg_loss == pytest.approx(4.0)


def test_t_stat_none_with_single_trade() -> None:
    report = compute_metrics(make_equity([1000.0, 1010.0]), [trip(5.0)], SECOND)
    assert report.t_stat is None


def test_t_stat_none_with_identical_nets() -> None:
    report = compute_metrics(make_equity([1000.0, 1010.0]), [trip(5.0), trip(5.0)], SECOND)
    assert report.t_stat is None  # zero variance in trade nets
