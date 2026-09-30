"""Slippage cost model (used in bars-only fill mode)."""

from tradingv2.core.types import Side


class SlippageModel:
    """Fixed slippage in basis points, applied against the trade side."""

    def __init__(self, bps: float) -> None:
        if bps < 0:
            raise ValueError(f"slippage bps must be non-negative, got {bps}")
        self.bps = bps

    def adjust(self, price: float, side: Side) -> float:
        """Adjust a reference price: buys pay up, sells receive less."""
        factor = 1 + self.bps / 10_000 if side == Side.BUY else 1 - self.bps / 10_000
        return price * factor
