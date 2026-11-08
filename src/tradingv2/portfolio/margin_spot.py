"""Spot margin account: quote borrowing with a frozen APR (brief 014).

The levered carry needs the spot leg to hold notional beyond its own cash.
Frozen mechanics (brief 014, amended pre-execution): a buy pays from the
balance first and borrows the residue into a quote debt; interest accrues to
the debt proportionally to elapsed time; a sell repays the debt first; fills
beyond the borrow cap are rejected.
"""

from dataclasses import dataclass, field
from typing import Protocol

from tradingv2.core.types import Fill, Side
from tradingv2.portfolio.spot import AccountError
from tradingv2.portfolio.tracker import PositionTracker

YEAR_NS = 365 * 86_400_000_000_000
MAX_BORROW_LEVERAGE = 6.0


class InterestBearer(Protocol):
    """Account protocol for time-based borrow interest accrual."""

    def accrue_to(self, ts_ns: int) -> float: ...


@dataclass
class MarginSpotAccount:
    """Spot-margin holdings: own quote, quote debt, long base position."""

    balance: float
    borrow_apr: float
    mmr: float = 0.05
    debt: float = 0.0
    _tracker: PositionTracker = field(default_factory=PositionTracker, repr=False, compare=False)
    _last_interest_ns: int | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.balance < 0:
            raise ValueError(f"balance must be non-negative, got {self.balance}")
        if not 0.0 <= self.borrow_apr < 1.0:
            raise ValueError(
                f"borrow apr must be a yearly fraction in [0, 1), got {self.borrow_apr}"
            )
        if not 0.0 < self.mmr < 1.0:
            raise ValueError(f"mmr must be in (0, 1), got {self.mmr}")

    @property
    def position(self) -> float:
        """Base units held (long only in v1)."""
        return self._tracker.qty

    @property
    def entry_price(self) -> float:
        """Average entry price of the open position."""
        return self._tracker.entry

    def apply_fill(self, fill: Fill) -> float:
        """Apply one fill; return the realized gross PnL on position reduction.

        The borrow-cap check runs BEFORE any mutation: on refusal the account
        is exactly as it was before the call.
        """
        signed_qty = fill.qty if fill.side == Side.BUY else -fill.qty
        self._check_borrow_prospective(signed_qty, fill.price, fill.fee)
        realized = self._tracker.apply(signed_qty, fill.price)
        if fill.side == Side.BUY:
            cost = fill.qty * fill.price + fill.fee
            used_cash = min(self.balance, cost)
            self.balance -= used_cash
            self.debt += cost - used_cash
        else:
            proceeds = fill.qty * fill.price - fill.fee
            repayment = min(max(0.0, proceeds), self.debt)
            self.debt -= repayment
            self.balance += proceeds - repayment
        return realized

    def _check_borrow_prospective(self, signed_qty: float, price: float, fee: float) -> None:
        """Reject fills whose post-fill notional outruns the borrow cap.

        The cap is expressed against own net equity (balance - debt + position
        at mark) rather than gross notional, mirroring the cross-margin model.
        """
        increase = max(0.0, abs(self.position + signed_qty) - abs(self.position))
        if increase <= 0:
            return
        del fee
        post_notional = abs(self.position + signed_qty) * price
        own_net = self.balance - self.debt + abs(self.position) * price
        cap = MAX_BORROW_LEVERAGE * max(own_net, 0.0)
        if post_notional > cap:
            raise AccountError(
                f"borrow cap exceeded: post notional {post_notional:.2f} > "
                f"{MAX_BORROW_LEVERAGE} x own net equity {max(own_net, 0.0):.2f}"
            )

    def accrue_to(self, ts_ns: int) -> float:
        """Accrue borrow interest to the debt from the last accrual clock.

        The first call only stamps the clock; later calls add
        debt x APR x elapsed / year and return the interest charged.
        """
        if self._last_interest_ns is None:
            self._last_interest_ns = ts_ns
            return 0.0
        elapsed = ts_ns - self._last_interest_ns
        if elapsed <= 0:
            return 0.0
        interest = self.debt * self.borrow_apr * elapsed / YEAR_NS
        self.debt += interest
        self._last_interest_ns = ts_ns
        return interest

    def unrealized(self, mark_price: float) -> float:
        """Unrealized PnL of the open position at the mark price."""
        if self.position == 0.0:
            return 0.0
        return (mark_price - self.entry_price) * self.position

    def equity(self, mark_price: float) -> float:
        """Net account value in quote: cash - debt + position at mark."""
        return self.balance - self.debt + self._tracker.qty * mark_price

    def is_liquidated(self, mark_price: float) -> bool:
        """True when the net equity is exhausted (frozen simplification)."""
        if self.position == 0.0:
            return False
        return self.equity(mark_price) <= 0.0
