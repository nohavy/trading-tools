"""Breakout strategy: range break confirmed by above-average volume."""

from tradingv2.core.types import PriceBar, Side
from tradingv2.strategy.base import Context, Strategy


class BreakoutVolume(Strategy):
    """Long on upward break of the previous `lookback` bars' range with volume
    confirmation; short on downward break. Exits when price re-enters the
    ENTRY range, on stop, or at max_hold_bars. One position at a time.
    """

    def __init__(
        self,
        lookback: int = 60,
        volume_factor: float = 2.0,
        qty: float = 0.002,
        stop_bps: float | None = None,
        max_hold_bars: int | None = None,
    ) -> None:
        if lookback <= 0:
            raise ValueError(f"lookback must be positive, got {lookback}")
        if volume_factor <= 0:
            raise ValueError(f"volume_factor must be positive, got {volume_factor}")
        self._lookback = lookback
        self._volume_factor = volume_factor
        self._qty = qty
        self._stop_bps = stop_bps
        self._max_hold_bars = max_hold_bars
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._volumes: list[float] = []
        self._entry_range_high: float | None = None
        self._entry_range_low: float | None = None
        self._hold_count = 0
        self._entry_close: float | None = None
        self._stop_order_id: int | None = None

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        if len(self._highs) < self._lookback:
            self._shift(bar)
            return
        range_high = max(self._highs[-self._lookback:])
        range_low = min(self._lows[-self._lookback:])
        avg_volume = sum(self._volumes[-self._lookback:]) / self._lookback
        volume_confirmed = bar.volume > self._volume_factor * avg_volume

        position = ctx.exchange.position_qty
        if position == 0.0:
            if bar.close > range_high and volume_confirmed:
                self._enter(ctx, Side.BUY, bar, range_high, range_low)
            elif bar.close < range_low and volume_confirmed:
                self._enter(ctx, Side.SELL, bar, range_high, range_low)
            self._shift(bar)
            return
        self._hold_count += 1
        assert self._entry_range_high is not None
        assert self._entry_range_low is not None
        exit_needed = (
            (position > 0 and bar.close < self._entry_range_high)
            or (position < 0 and bar.close > self._entry_range_low)
            or (self._max_hold_bars is not None and self._hold_count >= self._max_hold_bars)
        )
        if exit_needed:
            self._exit(ctx, position)
        elif self._hold_count == 1 and self._stop_order_id is None and self._stop_bps is not None:
            self._place_stop(ctx, bar)
        self._shift(bar)

    def _shift(self, bar: PriceBar) -> None:
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._volumes.append(bar.volume)

    def _enter(
        self, ctx: Context, side: Side, bar: PriceBar, range_high: float, range_low: float
    ) -> None:
        ctx.submit_market(side, qty=self._qty)
        self._entry_range_high = range_high
        self._entry_range_low = range_low
        self._entry_close = bar.close
        self._hold_count = 0
        self._stop_order_id = None

    def _place_stop(self, ctx: Context, bar: PriceBar) -> None:
        del bar
        assert self._entry_close is not None
        assert self._stop_bps is not None
        offset = self._entry_close * self._stop_bps / 10_000
        position = ctx.exchange.position_qty
        if position > 0:
            self._stop_order_id = ctx.submit_stop(
                Side.SELL, qty=abs(position), stop_price=self._entry_close - offset
            )
        else:
            self._stop_order_id = ctx.submit_stop(
                Side.BUY, qty=abs(position), stop_price=self._entry_close + offset
            )

    def _exit(self, ctx: Context, position: float) -> None:
        if self._stop_order_id is not None:
            ctx.cancel(self._stop_order_id)
            self._stop_order_id = None
        ctx.submit_market(Side.SELL if position > 0 else Side.BUY, qty=abs(position))
        self._hold_count = 0
