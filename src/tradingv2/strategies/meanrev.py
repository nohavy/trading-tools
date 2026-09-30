"""Mean-reversion strategy: enter on extreme z-score, exit on reversion."""

from tradingv2.core.types import PriceBar, Side
from tradingv2.features.incremental import ZScoreIncr
from tradingv2.strategy.base import Context, Strategy


class MeanRevZScore(Strategy):
    """Long when z <= -entry_z, short when z >= +entry_z.

    Exits when the z-score reverts to |z| <= exit_z, on stop, or at
    max_hold_bars. One position at a time (no pyramiding).
    """

    def __init__(
        self,
        window: int = 120,
        entry_z: float = 2.5,
        exit_z: float = 0.5,
        qty: float = 0.002,
        stop_bps: float | None = None,
        max_hold_bars: int | None = None,
    ) -> None:
        self._zscore = ZScoreIncr(window=window)
        self._entry_z = entry_z
        self._exit_z = exit_z
        self._qty = qty
        self._stop_bps = stop_bps
        self._max_hold_bars = max_hold_bars
        self._stop_order_id: int | None = None
        self._hold_count = 0

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        z = self._zscore.update(bar.close)
        if z is None:
            return
        position = ctx.exchange.position_qty
        if position == 0.0:
            if z <= -self._entry_z:
                self._enter(ctx, Side.BUY, bar)
            elif z >= self._entry_z:
                self._enter(ctx, Side.SELL, bar)
            return
        # position open: manage the exit
        self._hold_count += 1
        exit_needed = (
            (position > 0 and z >= -self._exit_z)
            or (position < 0 and z <= self._exit_z)
            or (self._max_hold_bars is not None and self._hold_count >= self._max_hold_bars)
        )
        if exit_needed:
            self._exit(ctx, position)
        if self._hold_count == 1 and self._stop_order_id is None and self._stop_bps is not None:
            self._place_stop(ctx, bar)

    def _enter(self, ctx: Context, side: Side, bar: PriceBar) -> None:
        ctx.submit_market(side, qty=self._qty)
        self._hold_count = 0
        self._stop_order_id = None
        self._last_entry_close = bar.close

    def _place_stop(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        assert self._last_entry_close is not None
        position = ctx.exchange.position_qty
        if position == 0.0:
            return
        assert self._stop_bps is not None
        offset = self._last_entry_close * self._stop_bps / 10_000
        entry_close = self._last_entry_close
        if position > 0:
            self._stop_order_id = ctx.submit_stop(
                Side.SELL, qty=self._qty, stop_price=entry_close - offset
            )
        else:
            self._stop_order_id = ctx.submit_stop(
                Side.BUY, qty=self._qty, stop_price=entry_close + offset
            )

    def _exit(self, ctx: Context, position: float) -> None:
        if self._stop_order_id is not None:
            ctx.cancel(self._stop_order_id)
            self._stop_order_id = None
        ctx.submit_market(Side.SELL if position > 0 else Side.BUY, qty=abs(position))
        self._hold_count = 0
