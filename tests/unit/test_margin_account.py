"""Tests for the perpetual margin account (signed position, funding, liquidation)."""

import pytest

from tradingv2.core.types import Fill, FillRole, Side
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.portfolio.spot import AccountError


def make_fill(side: Side, price: float, qty: float, fee: float = 0.0) -> Fill:
    return Fill(order_id=1, ts_ns=0, price=price, qty=qty, fee=fee, role=FillRole.TAKER, side=side)


def test_initial_equity_is_balance() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    assert account.equity(mark_price=100.0) == pytest.approx(1000.0)


def test_long_position_unrealized_pnl() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0, fee=0.05))
    assert account.position == pytest.approx(1.0)
    assert account.entry_price == pytest.approx(100.0)
    assert account.equity(mark_price=110.0) == pytest.approx(1000.0 - 0.05 + 10.0)


def test_short_position_unrealized_pnl() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.SELL, price=100.0, qty=1.0, fee=0.05))
    assert account.position == pytest.approx(-1.0)
    assert account.equity(mark_price=90.0) == pytest.approx(1000.0 - 0.05 + 10.0)


def test_increase_position_averages_entry() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0))
    account.apply_fill(make_fill(Side.BUY, price=110.0, qty=1.0))
    assert account.position == pytest.approx(2.0)
    assert account.entry_price == pytest.approx(105.0)


def test_partial_close_realizes_pnl() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0))
    realized = account.apply_fill(make_fill(Side.SELL, price=110.0, qty=0.5))
    assert realized == pytest.approx(5.0)  # (110-100) * 0.5
    assert account.position == pytest.approx(0.5)
    assert account.entry_price == pytest.approx(100.0)


def test_full_close_zeroes_position() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0))
    account.apply_fill(make_fill(Side.SELL, price=105.0, qty=1.0))
    assert account.position == pytest.approx(0.0)


def test_flip_averages_old_entry_with_new_leg() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0))
    realized = account.apply_fill(make_fill(Side.SELL, price=110.0, qty=3.0))
    assert realized == pytest.approx(10.0)  # (110-100) * 1 reduced
    assert account.position == pytest.approx(-2.0)
    # flipped remainder: old long leg (1 @ 100) closed; short = 2 @ avg(100, 110)
    assert account.entry_price == pytest.approx(105.0)
    # equity: 1000 + 10 realized; mark == entry so the short's unrealized PnL is 0
    assert account.equity(mark_price=105.0) == pytest.approx(1010.0)


def test_funding_paid_by_long_on_positive_rate() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0))
    account.apply_funding(ts_ns=0, rate=0.0001, mark_price=100.0)
    # funding = rate * mark * position = 0.0001 * 100 * 1 = 0.01 (paid)
    assert account.equity(mark_price=100.0) == pytest.approx(1000.0 - 0.01)


def test_short_receives_on_positive_rate() -> None:
    account = MarginAccount(balance=1000.0, leverage=5)
    account.apply_fill(make_fill(Side.SELL, price=100.0, qty=1.0))
    account.apply_funding(ts_ns=0, rate=0.0001, mark_price=100.0)
    assert account.equity(mark_price=100.0) == pytest.approx(1000.0 + 0.01)


def test_liquidation_threshold_long() -> None:
    account = MarginAccount(balance=100.0, leverage=10, mmr=0.004)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=10.0))
    assert not account.is_liquidated(mark_price=95.0)
    assert account.is_liquidated(mark_price=90.0)


def test_liquidation_price_long() -> None:
    account = MarginAccount(balance=100.0, leverage=10, mmr=0.004)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=10.0))
    liquidation = account.liquidation_price()
    assert liquidation is not None
    assert liquidation == pytest.approx(90.361, abs=0.01)


def test_no_position_no_liquidation() -> None:
    account = MarginAccount(balance=100.0, leverage=10)
    assert account.liquidation_price() is None
    assert not account.is_liquidated(mark_price=1.0)


def test_excess_leverage_rejected() -> None:
    with pytest.raises(ValueError, match="leverage"):
        MarginAccount(balance=1000.0, leverage=25)


def test_position_beyond_equity_rejected() -> None:
    account = MarginAccount(balance=100.0, leverage=10)
    with pytest.raises(AccountError, match="margin"):
        account.apply_fill(make_fill(Side.BUY, price=100.0, qty=50.0))  # notional 5000 > 100*10
