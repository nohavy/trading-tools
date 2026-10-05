"""Daily-close time-series trend strategy driven by 1m engine bars."""

from tradingv2.core.types import OrderStatus, PriceBar, Side
from tradingv2.execution.exchange import FillEvent
from tradingv2.strategy.base import Context, Strategy

_DAY_NS = 86_400_000_000_000


class TimeSeriesTrend(Strategy):
    """Long/flat trend filter or delayed buy-and-hold benchmark.

    Daily closes are extracted only from completed 1m bars ending at 00:00 UTC.
    A signal is submitted after that minute's close and therefore fills no
    earlier than a later bar. Positions are not pyramided or rebalanced while
    held; quantity is sized to the configured fraction of equity on entry.
    """

    def __init__(
        self,
        lookback_days: int = 60,
        mode: str = "long_flat",
        target_exposure: float = 1.0,
        trade_start_ns: int = 0,
    ) -> None:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if mode not in {"long_flat", "buy_hold"}:
            raise ValueError("mode must be 'long_flat' or 'buy_hold'")
        if not 0.0 < target_exposure <= 1.0:
            raise ValueError("target_exposure must be in (0, 1]")
        if trade_start_ns < 0:
            raise ValueError("trade_start_ns must be non-negative")
        self._lookback_days = lookback_days
        self._mode = mode
        self._target_exposure = target_exposure
        self._trade_start_ns = trade_start_ns
        self._daily_closes: list[float] = []
        self._pending_order_id: int | None = None

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        is_daily_close = bar.ts_close_ns % _DAY_NS == 0
        if is_daily_close:
            self._daily_closes.append(bar.close)

        if self._pending_order_id is not None:
            status = ctx.order_status(self._pending_order_id)
            if status in (OrderStatus.PENDING, OrderStatus.ACTIVE):
                return
            self._pending_order_id = None

        if not is_daily_close:
            return
        if bar.ts_close_ns < self._trade_start_ns:
            return

        position = ctx.exchange.position_qty
        if position < 0.0:
            raise RuntimeError("time-series trend strategy must not hold a short position")
        if self._mode == "buy_hold":
            if position == 0.0:
                self._submit_long(ctx, bar)
            return

        if len(self._daily_closes) <= self._lookback_days:
            return
        trailing_return = (
            self._daily_closes[-1] / self._daily_closes[-self._lookback_days - 1] - 1.0
        )
        if position == 0.0 and trailing_return > 0.0:
            self._submit_long(ctx, bar)
        elif position > 0.0 and trailing_return <= 0.0:
            self._pending_order_id = ctx.submit_market(Side.SELL, qty=position)

    def on_fill(self, ctx: Context, event: FillEvent) -> None:
        if self._pending_order_id == event.fill.order_id:
            status = ctx.order_status(event.fill.order_id)
            if status in (OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELED):
                self._pending_order_id = None

    def _submit_long(self, ctx: Context, bar: PriceBar) -> None:
        quantity = ctx.equity() * self._target_exposure / bar.close
        if quantity > 0.0:
            self._pending_order_id = ctx.submit_market(Side.BUY, qty=quantity)
