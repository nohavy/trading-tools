"""Perpetual margin account: signed position, leverage, funding, liquidation."""

from dataclasses import dataclass

from tradingv2.core.types import Fill, Side
from tradingv2.portfolio.spot import AccountError

MAX_LEVERAGE = 20.0


@dataclass
class MarginAccount:
    """USDT-M perpetual account: signed position in base units, margin in quote."""

    balance: float
    leverage: float = 1.0
    mmr: float = 0.004
    position: float = 0.0
    entry_price: float = 0.0

    def __post_init__(self) -> None:
        if self.leverage <= 0 or self.leverage > MAX_LEVERAGE:
            raise ValueError(f"leverage must be in (0, {MAX_LEVERAGE}], got {self.leverage}")
        if self.balance <= 0:
            raise ValueError(f"balance must be positive, got {self.balance}")

    def apply_fill(self, fill: Fill) -> float:
        """Apply one fill; return the realized gross PnL on position reduction."""
        signed_qty = fill.qty if fill.side == Side.BUY else -fill.qty
        self.balance -= fill.fee
        same_direction = signed_qty * self.position > 0 or self.position == 0.0
        realized = 0.0
        if not same_direction:
            reduce_qty = min(abs(signed_qty), abs(self.position))
            direction = 1.0 if self.position > 0 else -1.0
            realized = (fill.price - self.entry_price) * reduce_qty * direction
            self.balance += realized
        new_position = self.position + signed_qty
        if self.position == 0.0 or same_direction:
            total_cost = abs(self.position) * self.entry_price + abs(signed_qty) * fill.price
            new_abs = abs(new_position)
            self.entry_price = total_cost / new_abs if new_abs > 0 else 0.0
        elif abs(new_position) > abs(self.position):
            old_entry = self.entry_price
            flipped_size = abs(new_position) - abs(self.position)
            total_cost = abs(self.position) * old_entry + flipped_size * fill.price
            self.entry_price = total_cost / abs(new_position)
        else:
            # full flip: the remainder opens a new position at the fill price
            if new_position != 0.0 and self.position != 0.0 and signed_qty * new_position > 0:
                self.entry_price = fill.price
        self.position = new_position
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
