"""Position tracker: signed position with average entry price and realized PnL.

Shared by the margin account (balance effects) and the simulated exchange
(fill decomposition) so both compute identical realized PnL.
"""


class PositionTracker:
    """Tracks a signed position and its average entry price."""

    def __init__(self) -> None:
        self.qty: float = 0.0
        self.entry: float = 0.0

    def apply(self, signed_qty: float, price: float) -> float:
        """Apply one signed fill; return the realized gross PnL on reduction."""
        same_direction = signed_qty * self.qty > 0 or self.qty == 0.0
        realized = 0.0
        if not same_direction:
            reduce_qty = min(abs(signed_qty), abs(self.qty))
            direction = 1.0 if self.qty > 0 else -1.0
            realized = (price - self.entry) * reduce_qty * direction
        new_qty = self.qty + signed_qty
        if self.qty == 0.0 or same_direction:
            total_cost = abs(self.qty) * self.entry + abs(signed_qty) * price
            self.entry = total_cost / abs(new_qty) if new_qty != 0.0 else 0.0
        elif abs(new_qty) > abs(self.qty):
            # flip with excess: old leg closed, remainder re-enters at the fill price
            old_entry = self.entry
            flipped_size = abs(new_qty) - abs(self.qty)
            total_cost = abs(self.qty) * old_entry + flipped_size * price
            self.entry = total_cost / abs(new_qty)
        elif new_qty != 0.0 and signed_qty * new_qty > 0:
            # full flip: the remainder opens the opposite position at the fill price
            self.entry = price
        # partial reduce: entry price unchanged
        self.qty = new_qty
        return realized
