"""Tests for the categorized PnL ledger and its reconciliation invariant."""

import pytest

from tradingv2.portfolio.ledger import Ledger, LedgerReconcileError


def test_single_trade_net_formula() -> None:
    ledger = Ledger()
    trade = ledger.record_trade(gross=10.0, fee=0.5, slippage=0.2, funding=0.0)
    assert trade.net == pytest.approx(9.3)
    totals = ledger.totals()
    assert totals.n_trades == 1
    assert totals.net == pytest.approx(9.3)


def test_funding_paid_reduces_net() -> None:
    ledger = Ledger()
    trade = ledger.record_trade(gross=1.0, fee=0.1, slippage=0.0, funding=0.3)
    assert trade.net == pytest.approx(0.6)


def test_funding_received_increases_net() -> None:
    ledger = Ledger()
    trade = ledger.record_trade(gross=1.0, fee=0.1, slippage=0.0, funding=-0.3)
    assert trade.net == pytest.approx(1.2)


def test_multiple_trades_accumulate() -> None:
    ledger = Ledger()
    ledger.record_trade(gross=10.0, fee=0.5, slippage=0.2, funding=0.0)
    ledger.record_trade(gross=-4.0, fee=0.3, slippage=0.1, funding=0.05)
    totals = ledger.totals()
    assert totals.n_trades == 2
    assert totals.gross == pytest.approx(6.0)
    assert totals.fee == pytest.approx(0.8)
    assert totals.slippage == pytest.approx(0.3)
    assert totals.funding == pytest.approx(0.05)
    assert totals.net == pytest.approx(10.0 - 0.5 - 0.2 - 4.0 - 0.3 - 0.1 - 0.05)


def test_reconciled_passes_on_healthy_ledger() -> None:
    ledger = Ledger()
    ledger.record_trade(gross=10.0, fee=0.5, slippage=0.2, funding=0.1)
    ledger.record_trade(gross=-4.0, fee=0.3, slippage=0.1, funding=-0.2)
    ledger.assert_reconciled()  # no exception


def test_reconciled_catches_tampered_record() -> None:
    ledger = Ledger()
    ledger.record_trade(gross=10.0, fee=0.5, slippage=0.2, funding=0.0)
    corrupted = ledger._trades[0]
    ledger._trades[0] = corrupted.__class__(
        gross=corrupted.gross, fee=corrupted.fee, slippage=corrupted.slippage,
        funding=corrupted.funding, net=corrupted.net + 1.0,
    )
    with pytest.raises(LedgerReconcileError):
        ledger.assert_reconciled()


def test_reconciled_checks_cumulative_net() -> None:
    ledger = Ledger()
    ledger.record_trade(gross=10.0, fee=0.5, slippage=0.2, funding=0.0)
    # tamper: overwrite the private net accumulator path via totals check
    tampered = ledger._trades[0].__class__(
        gross=0.0, fee=0.0, slippage=0.0, funding=0.0, net=0.5
    )
    ledger._trades.append(tampered)
    with pytest.raises(LedgerReconcileError):
        ledger.assert_reconciled()
