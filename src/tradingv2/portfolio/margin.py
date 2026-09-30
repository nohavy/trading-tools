"""Perpetual margin account: signed position, leverage, funding, liquidation."""

from dataclasses import dataclass, field

from tradingv2.core.types import Fill, Side
from tradingv2.portfolio.spot import AccountError
from tradingv2.portfolio.tracker import PositionTracker

MAX_LEVERAGE = 20.0


@dataclass
class MarginAccount:
    """USDT-M perpetual account: signed position in base units, margin in quote."""

    balance: float
    leverage: float = 1.0
    mmr: float = 0.004
    _tracker: PositionTracker = field(default_factory=PositionTracker, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.leverage <= 0 or self.leverage > MAX_LEVERAGE:
            raise ValueError(f"leverage must be in (0, {MAX_LEVERAGE}], got {self.leverage}")
        if self.balance <= 0:
            raise ValueError(f"balance must be positive, got {self.balance}")

    @property
    def position(self) -> float:
        """Signed position in base units (long > 0)."""
        return self._tracker.qty

    @property
    def entry_price(self) -> float:
        """Average entry price of the open position."""
        return self._tracker.entry

    def apply_fill(self, fill: Fill) -> float:
        """Apply one fill; return the realized gross PnL on position reduction."""
        signed_qty = fill.qty if fill.side == Side.BUY else -fill.qty
        self.balance -= fill.fee
        realized = self._tracker.apply(signed_qty, fill.price)
        self.balance += realized
        self._check_margin(fill.price)
        return realized

    def _check_margin(self, mark_price: float) -> None:
        margin_used = abs(self.position) * self.entry_price / self.leverage
        if margin_used > self.equity(mark_price):
            raise AccountError(
                f"insufficient margin: used {margin_used} > equity {self.equity(mark_price)}"
            )

    def apply_funding(self, ts_ns: int, rate: float, mark_price: float) -> float:
        """Apply one funding event: longs pay positive rates; return amount paid."""
        del ts_ns
        amount = rate * mark_price * self.position
        self.balance -= amount
        return amount

    def unrealized(self, mark_price: float) -> float:
        """Unrealized PnL of the open position at the mark price."""
        if self.position == 0.0:
            return 0.0
        return (mark_price - self.entry_price) * self.position

    def equity(self, mark_price: float) -> float:
        """Account equity in quote: balance + unrealized PnL."""
        return self.balance + self.unrealized(mark_price)

    def liquidation_price(self) -> float | None:
        """Price at which equity hits the maintenance margin, or None if flat."""
        if self.position == 0.0:
            return None
        qty = abs(self.position)
        if self.position > 0:
            return (qty * self.entry_price - self.balance) / (qty * (1 - self.mmr))
        return (self.balance + qty * self.entry_price) / (qty * (1 + self.mmr))

    def is_liquidated(self, mark_price: float) -> bool:
        """True when equity falls to the maintenance margin."""
        if self.position == 0.0:
            return False
        notional = abs(self.position) * mark_price
        return self.equity(mark_price) <= self.mmr * notional
