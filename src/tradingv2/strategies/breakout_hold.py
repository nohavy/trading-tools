"""Fixed-hold breakout strategy: enter on confirmed break, exit after N bars.

Faithful reproduction of the scan's edge measurement (entry at the break,
exit exactly `hold_bars` bars later at market) so the engine measures what
the scan promised — with realistic fills, costs and one position at a time.
"""

from tradingv2.core.types import PriceBar, Side
from tradingv2.strategy.base import Context, Strategy


class BreakoutFixedHold(Strategy):
    """Long on upward range break with volume confirmation, short on downward.

    Exits at market exactly `hold_bars` bars after the entry fill (no range
    re-entry logic, no stop — matching the scan's fixed-horizon measurement).
    One position at a time; re-entry allowed on the next qualifying bar.
    """

    def __init__(
        self,
        lookback: int = 30,
        volume_factor: float = 2.0,
        hold_bars: int = 5,
        qty: float = 0.002,
        direction: str = "both",
    ) -> None:
        if direction not in ("both", "buy", "sell"):
            raise ValueError(f"direction must be 'both', 'buy' or 'sell', got {direction!r}")
        if lookback <= 0:
            raise ValueError(f"lookback must be positive, got {lookback}")
        if volume_factor <= 0:
            raise ValueError(f"volume_factor must be positive, got {volume_factor}")
        if hold_bars <= 0:
            raise ValueError(f"hold_bars must be positive, got {hold_bars}")
        self._lookback = lookback
        self._volume_factor = volume_factor
        self._hold_bars = hold_bars
        self._qty = qty
        self._direction = direction
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._volumes: list[float] = []
        self._exit_pending_id: int | None = None
        self._bars_held = 0

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:  # noqa: B027
        if len(self._highs) < self._lookback:
            self._shift(bar)
            return
        position = ctx.exchange.position_qty
        if position == 0.0:
            self._exit_pending_id = None
            self._bars_held = 0
            range_high = max(self._highs[-self._lookback :])
            range_low = min(self._lows[-self._lookback :])
            avg_volume = sum(self._volumes[-self._lookback :]) / self._lookback
            if bar.volume > self._volume_factor * avg_volume:
                up_break = bar.close > range_high
                down_break = bar.close < range_low
                if up_break and self._direction in ("both", "buy"):
                    ctx.submit_market(Side.BUY, qty=self._qty)
                elif down_break and self._direction in ("both", "sell"):
                    ctx.submit_market(Side.SELL, qty=self._qty)
            self._shift(bar)
            return
        # holding: fixed-duration exit
        self._bars_held += 1
        if self._bars_held >= self._hold_bars and self._exit_pending_id is None:
            self._exit_pending_id = ctx.submit_market(
                Side.SELL if position > 0 else Side.BUY, qty=abs(position)
            )
        self._shift(bar)

    def _shift(self, bar: PriceBar) -> None:
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._volumes.append(bar.volume)

    def on_fill(self, ctx: Context, event: object) -> None:  # noqa: B027
        """Reset the hold counter when the position closes."""
        if ctx.exchange.position_qty == 0.0:
            self._exit_pending_id = None
            self._bars_held = 0
