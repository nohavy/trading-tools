"""Funding-momentum strategy: buy funding extremes (crowded longs continuation).

State machine (documented decision): flat -> entering (order in flight) ->
holding -> exiting -> flat. Entry rule: the current rate must be >= its
rolling percentile computed over the PREVIOUS settlements only (strictly
past — no lookahead) AND above the rolling median (an equal-to-history rate
is not an extreme). Exits at market after `hold_bars` bars. One position at
a time; buy side only (v1: the sell side of funding extremes showed few,
noisy events on the studied period).
"""

import numpy as np

from tradingv2.core.types import OrderStatus, PriceBar, Side
from tradingv2.strategy.base import Context, Strategy

_FLAT, ENTERING, HOLDING, EXITING = "flat", "entering", "holding", "exiting"


class FundingMomentum(Strategy):
    """Buy funding extremes, hold a fixed duration, single position."""

    def __init__(
        self,
        window_events: int = 250,
        threshold_pct: float = 90.0,
        hold_bars: int = 1440,
        qty: float = 0.002,
    ) -> None:
        if window_events <= 0:
            raise ValueError(f"window_events must be positive, got {window_events}")
        if not 50 < threshold_pct <= 100:
            raise ValueError(f"threshold_pct must be in (50, 100], got {threshold_pct}")
        self._window = window_events
        self._threshold_pct = threshold_pct
        self._hold_bars = hold_bars
        self._qty = qty
        self._min_history = max(5, window_events // 2)
        self._history: list[float] = []
        self._state = _FLAT
        self._entry_order_id: int | None = None
        self._bars_held = 0
        self._exit_pending_id: int | None = None

    def on_funding(self, ctx: Context, rate: float) -> None:  # noqa: B027
        """Record the settlement and enter when it is an extreme."""
        if rate != rate:  # NaN
            return
        if self._state == _FLAT and len(self._history) >= self._min_history:
            past = np.array(self._history[-self._window :])
            threshold = float(np.percentile(past, self._threshold_pct))
            median = float(np.percentile(past, 50.0))
            if rate >= threshold and rate > median:
                self._entry_order_id = ctx.submit_market(Side.BUY, qty=self._qty)
                self._bars_held = 0
                self._state = ENTERING
        self._history.append(rate)

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:  # noqa: B027
        del bar
        if self._state == ENTERING:
            status = self._entry_order_id and ctx.order_status(self._entry_order_id)
            if status == OrderStatus.FILLED:
                self._state = HOLDING
            elif status in (OrderStatus.REJECTED, OrderStatus.CANCELED):
                self._state = _FLAT
                self._entry_order_id = None
        elif self._state == HOLDING:
            position = ctx.exchange.position_qty
            if position == 0.0:
                self._state = _FLAT
                return
            self._bars_held += 1
            if self._bars_held >= self._hold_bars and self._exit_pending_id is None:
                self._exit_pending_id = ctx.submit_market(Side.SELL, qty=abs(position))
                self._state = EXITING
        # EXITING: wait for the fill (on_fill resets to flat)

    def on_fill(self, ctx: Context, event: object) -> None:  # noqa: B027
        """Return to flat once the position is closed (exit fill applied)."""
        if ctx.exchange.position_qty == 0.0 and self._state in (HOLDING, EXITING):
            self._state = _FLAT
            self._exit_pending_id = None
            self._entry_order_id = None
            self._bars_held = 0
