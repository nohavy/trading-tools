"""Order-flow strategy: enter on strong taker-buy/sell imbalance."""

from tradingv2.core.types import PriceBar, Side
from tradingv2.features.incremental import FlowImbalanceIncr
from tradingv2.strategy.base import Context, Strategy


class OrderFlowImbalance(Strategy):
    """Long when the taker-buy imbalance >= threshold, short when <= -threshold.

    Exits when the flow turns against the position (crosses zero), on stop,
    or at max_hold_bars. One position at a time.
    """

    def __init__(
        self,
        window: int = 120,
        threshold: float = 0.5,
        qty: float = 0.002,
        stop_bps: float | None = None,
        max_hold_bars: int | None = None,
    ) -> None:
        if not 0 < threshold <= 1:
            raise ValueError(f"threshold must be in (0, 1], got {threshold}")
        self._flow = FlowImbalanceIncr(window=window)
        self._threshold = threshold
        self._qty = qty
        self._stop_bps = stop_bps
        self._max_hold_bars = max_hold_bars
        self._hold_count = 0
        self._stop_order_id: int | None = None
        self._exit_pending_id: int | None = None
        self._entry_close: float | None = None
        self._last_flow: float | None = None

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        self._last_flow = self._flow.update(bar.volume, bar.taker_buy_volume)
        position = ctx.exchange.position_qty
        if position == 0.0:
            if self._last_flow is None:
                return
            if self._last_flow >= self._threshold:
                self._enter(ctx, Side.BUY, bar)
            elif self._last_flow <= -self._threshold:
                self._enter(ctx, Side.SELL, bar)
            return
        self._hold_count += 1
        flow = self._last_flow
        exit_needed = (
            (position > 0 and flow is not None and flow <= 0)
            or (position < 0 and flow is not None and flow >= 0)
            or (self._max_hold_bars is not None and self._hold_count >= self._max_hold_bars)
        )
        if exit_needed:
            self._exit(ctx, position)
        elif self._hold_count == 1 and self._stop_order_id is None and self._stop_bps is not None:
            self._place_stop(ctx, bar)

    def _enter(self, ctx: Context, side: Side, bar: PriceBar) -> None:
        ctx.submit_market(side, qty=self._qty)
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
        self._exit_pending_id = ctx.submit_market(
            Side.SELL if position > 0 else Side.BUY, qty=abs(position)
        )
        self._hold_count = 0

    def on_fill(self, ctx: Context, event: object) -> None:
        """Bracket guard: when the stop closes the position, cancel the pending exit."""
        from tradingv2.execution.exchange import FillEvent

        assert isinstance(event, FillEvent)
        del event
        if ctx.exchange.position_qty == 0.0:
            if self._exit_pending_id is not None:
                ctx.cancel(self._exit_pending_id)
                self._exit_pending_id = None
            self._stop_order_id = None
