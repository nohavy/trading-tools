"""Tests for the spot account (cash + inventory, fees in quote)."""

import pytest

from tradingv2.core.types import Fill, FillRole, Side
from tradingv2.portfolio.spot import AccountError, SpotAccount


def make_fill(side: Side, price: float, qty: float, fee: float) -> Fill:
    return Fill(order_id=1, ts_ns=0, price=price, qty=qty, fee=fee, role=FillRole.TAKER, side=side)


def test_initial_equity() -> None:
    account = SpotAccount(quote_balance=1000.0, base_balance=0.0)
    assert account.equity(mark_price=100.0) == pytest.approx(1000.0)


def test_buy_reduces_quote_increases_base() -> None:
    account = SpotAccount(quote_balance=1000.0, base_balance=0.0)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=0.5, fee=0.05))
    assert account.quote_balance == pytest.approx(1000.0 - 50.0 - 0.05)
    assert account.base_balance == pytest.approx(0.5)


def test_sell_increases_quote_reduces_base() -> None:
    account = SpotAccount(quote_balance=1000.0, base_balance=0.5)
    account.apply_fill(make_fill(Side.SELL, price=110.0, qty=0.5, fee=0.055))
    assert account.quote_balance == pytest.approx(1000.0 + 55.0 - 0.055)
    assert account.base_balance == pytest.approx(0.0)


def test_sell_more_than_base_rejected() -> None:
    account = SpotAccount(quote_balance=1000.0, base_balance=0.1)
    with pytest.raises(AccountError, match="base"):
        account.apply_fill(make_fill(Side.SELL, price=110.0, qty=0.5, fee=0.05))


def test_buy_beyond_quote_rejected() -> None:
    account = SpotAccount(quote_balance=50.0, base_balance=0.0)
    with pytest.raises(AccountError, match="quote"):
        account.apply_fill(make_fill(Side.BUY, price=100.0, qty=1.0, fee=0.05))


def test_equity_after_round_trip_accounts_for_fees() -> None:
    account = SpotAccount(quote_balance=1000.0, base_balance=0.0)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=0.5, fee=0.05))
    account.apply_fill(make_fill(Side.SELL, price=100.0, qty=0.5, fee=0.05))
    # same price round trip: only the two fees are lost
    assert account.equity(mark_price=100.0) == pytest.approx(1000.0 - 0.10)
