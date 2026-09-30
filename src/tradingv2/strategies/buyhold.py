"""Buy-and-hold benchmark strategy: enter once, never exit."""

from tradingv2.core.types import PriceBar, Side
from tradingv2.strategy.base import Context, Strategy


class BuyHold(Strategy):
    """Reference strategy: buys at the first closed bar and holds forever."""

    def __init__(self, qty: float = 0.002) -> None:
        self._qty = qty
        self._bought = False

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        if not self._bought:
            ctx.submit_market(Side.BUY, qty=self._qty)
            self._bought = True
