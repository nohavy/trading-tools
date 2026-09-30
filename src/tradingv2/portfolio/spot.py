"""Spot account: quote cash + base inventory, fees charged in quote (v1)."""

from dataclasses import dataclass

from tradingv2.core.types import Fill, Side


class AccountError(Exception):
    """Raised when a fill would make the account incoherent."""


@dataclass
class SpotAccount:
    """Spot holdings: quote balance and base inventory."""

    quote_balance: float
    base_balance: float = 0.0

    def apply_fill(self, fill: Fill) -> None:
        """Apply one fill: adjust cash and inventory; fees are paid in quote."""
        notional = fill.price * fill.qty
        if fill.side == Side.BUY:
            total_cost = notional + fill.fee
            if total_cost > self.quote_balance:
                raise AccountError(
                    f"insufficient quote: need {total_cost}, have {self.quote_balance}"
                )
            self.quote_balance -= total_cost
            self.base_balance += fill.qty
        else:
            if fill.qty > self.base_balance:
                raise AccountError(
                    f"insufficient base: need {fill.qty}, have {self.base_balance}"
                )
            self.base_balance -= fill.qty
            self.quote_balance += notional - fill.fee

    def equity(self, mark_price: float) -> float:
        """Account value in quote units at the given mark price."""
        return self.quote_balance + self.base_balance * mark_price
