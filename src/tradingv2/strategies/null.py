"""Null strategy: seeded random entries to validate the engine charges costs.

Expected behavior (constitution II): with no drift in prices, the null
strategy loses on average its round-trip costs. If it shows a profit, the
engine has a bug.
"""

import numpy as np

from tradingv2.core.types import PriceBar, Side
from tradingv2.strategy.base import Context, Strategy


class NullStrategy(Strategy):
    """Enters long or short at random, exits after hold_bars closes."""

    def __init__(self, seed: int, hold_bars: int = 10, qty: float = 0.01) -> None:
        self.hold_bars = hold_bars
        self.qty = qty
        self._rng = np.random.default_rng(seed)
        self._open_order: int | None = None
        self._bars_held = 0

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        if self._open_order is not None:
            self._bars_held += 1
            if self._bars_held >= self.hold_bars:
                ctx.submit_market(Side.SELL, qty=self.qty)
                self._open_order = None
                self._bars_held = 0
            return
        if int(self._rng.integers(0, 2)) == 1:
            self._open_order = ctx.submit_market(Side.BUY, qty=self.qty)
            self._bars_held = 0
