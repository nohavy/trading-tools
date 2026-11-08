"""Spot margin account: own cash first, quote debt with a frozen borrow APR.

The levered carry needs the spot leg to borrow quote beyond its balance.
Frozen mechanics (brief 014, amended pre-execution): buy pays from the
balance first and borrows the residue into a debt; interest accrues to the
debt proportionally to elapsed time; sells repay the debt first; a fill is
rejected beyond the borrow cap.
"""

import pytest

from tradingv2.core.types import Fill, FillRole, Side
from tradingv2.portfolio.margin_spot import YEAR_NS, MarginSpotAccount
from tradingv2.portfolio.spot import AccountError


def make_fill(side: Side, price: float, qty: float, fee: float = 0.0, ts_ns: int = 0) -> Fill:
    return Fill(
        order_id=1, ts_ns=ts_ns, price=price, qty=qty, fee=fee,
        role=FillRole.TAKER, side=side,
    )


def test_initial_equity_is_balance() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    assert account.equity(mark_price=100.0) == pytest.approx(10000.0)
    assert account.debt == pytest.approx(0.0)


def test_buy_within_cash_does_not_borrow() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=90.0, fee=9.0))
    assert account.position == pytest.approx(90.0)
    assert account.balance == pytest.approx(991.0)
    assert account.debt == pytest.approx(0.0)


def test_buy_above_cash_borrows_the_residue() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=190.0, fee=19.0))
    cost = 190.0 * 100.0 + 19.0
    assert account.balance == pytest.approx(0.0)
    assert account.debt == pytest.approx(cost - 10000.0)
    assert account.position == pytest.approx(190.0)
    assert account.equity(mark_price=100.0) == pytest.approx(10000.0 - 19.0)


def test_sell_repays_debt_first() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=190.0))
    assert account.debt == pytest.approx(9000.0)
    accounted = account.apply_fill(make_fill(Side.SELL, price=100.0, qty=90.0))
    assert accounted == pytest.approx(0.0)  # exit at entry: no realized gain
    assert account.debt == pytest.approx(0.0)  # proceeds repaid the debt exactly
    assert account.balance == pytest.approx(0.0)
    assert account.position == pytest.approx(100.0)


def test_accrual_first_call_stamps_the_clock() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    assert account.accrue_to(ts_ns=1_000_000) == pytest.approx(0.0)
    assert account.accrue_to(ts_ns=1_000_000 + YEAR_NS // 2) == pytest.approx(0.0)
    assert account.accrue_to(ts_ns=1_000_000 + YEAR_NS) == pytest.approx(0.0)


def test_accrual_is_proportional_to_elapsed_time() -> None:
    account = MarginSpotAccount(balance=0.0, borrow_apr=0.06)
    account.debt = 1_000_000.0  # direct seed: borrow already outstanding
    account.accrue_to(ts_ns=0)
    first = account.accrue_to(ts_ns=YEAR_NS // 4)
    assert first == pytest.approx(1_000_000.0 * 0.06 * 0.25)
    # compounding: the second period accrues on the updated debt
    second = account.accrue_to(ts_ns=YEAR_NS)
    assert second == pytest.approx((1_000_000.0 + first) * 0.06 * 0.75)


def test_accrual_grows_the_debt_and_shrinks_equity() -> None:
    account = MarginSpotAccount(balance=0.0, borrow_apr=0.06)
    account.debt = 100_000.0
    account.accrue_to(ts_ns=0)
    account.accrue_to(ts_ns=YEAR_NS)
    assert account.debt == pytest.approx(106_000.0)
    # zero position: the net equity is exactly the debt, with the sign flipped
    assert account.equity(mark_price=100.0) == pytest.approx(-106_000.0)


def test_negative_funding_not_applied_to_spot_margin() -> None:
    """A margin spot account must not confuse the harness: no funding hook."""
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    assert not hasattr(account, "apply_funding")


def test_liquidation_when_net_equity_is_exhausted() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    account.apply_fill(make_fill(Side.BUY, price=100.0, qty=190.0))
    assert not account.is_liquidated(mark_price=60.0)  # net equity +2400
    assert account.is_liquidated(mark_price=45.0)  # net equity -450


def test_borrow_cap_rejects_excessive_notional() -> None:
    account = MarginSpotAccount(balance=10000.0, borrow_apr=0.06)
    with pytest.raises(AccountError, match="borrow cap"):
        account.apply_fill(make_fill(Side.BUY, price=100.0, qty=700.0))


def test_negative_balance_construction_rejected() -> None:
    with pytest.raises(ValueError, match="balance"):
        MarginSpotAccount(balance=-1.0, borrow_apr=0.06)
    with pytest.raises(ValueError, match="apr"):
        MarginSpotAccount(balance=1000.0, borrow_apr=-0.01)
