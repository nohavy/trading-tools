"""Built-in strategies used by tests and as reference implementations."""

from tradingv2.core.types import PriceBar, Side
from tradingv2.strategy.base import Context, Strategy


class TrivialStrategy(Strategy):
    """Buys on the first bar, sells after `hold_bars` closes: golden PnL cycle."""

    def __init__(self, hold_bars: int = 60) -> None:
        self.hold_bars = hold_bars
        self._order_id: int | None = None
        self._bars_seen = 0
        self._bought = False

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        self._bars_seen += 1
        if not self._bought:
            self._order_id = ctx.submit_market(Side.BUY, qty=0.002)
            self._bought = True
        elif self._bars_seen >= self.hold_bars and self._order_id is not None:
            ctx.submit_market(Side.SELL, qty=0.002)
            self._order_id = None


STRATEGIES: dict[str, type[Strategy]] = {
    "trivial": TrivialStrategy,
}


def register_strategy(name: str, cls: type[Strategy]) -> None:
    """Register a strategy class under a config name."""
    STRATEGIES[name] = cls


def build_strategy(name: str, params: dict[str, float | int | str | bool]) -> Strategy:
    """Instantiate a registered strategy by config name."""
    if name not in STRATEGIES:
        known = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"unknown strategy '{name}' (known: {known})")
    return STRATEGIES[name](**params)
