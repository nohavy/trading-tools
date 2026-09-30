"""Strategy API: base class and execution context (identical backtest/paper/live)."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from tradingv2.core.types import OrderType, PriceBar, Side
from tradingv2.execution.exchange import FillEvent, SimulatedExchange


@dataclass
class Context:
    """Everything a strategy may use at decision time.

    Exposes only closed bars (anti-lookahead, constitution III): lookback
    never includes future bars, and the current bar is the one just closed.
    """

    now_ns: int
    exchange: SimulatedExchange
    _closed_bars: list[PriceBar] = field(default_factory=list)
    on_timer_scheduled: Callable[[int], None] | None = None

    def lookback(self, n: int) -> list[PriceBar]:
        """The last n closed bars (including the one just closed), oldest first."""
        return self._closed_bars[-n:]

    def submit_market(self, side: Side, qty: float) -> int:
        """Submit a market order; returns the order id."""
        return self._submit(side, OrderType.MARKET, qty)

    def submit_limit(self, side: Side, qty: float, price: float, post_only: bool = False) -> int:
        """Submit a limit order; returns the order id."""
        order = self.exchange._new_order(
            symbol=self.exchange.rules.symbol, side=side, type=OrderType.LIMIT,
            qty=qty, submitted_ns=self.now_ns, limit_price=price, post_only=post_only,
        )
        self.exchange.submit(order)
        return order.id

    def submit_stop(self, side: Side, qty: float, stop_price: float) -> int:
        """Submit a stop-market order; returns the order id."""
        order = self.exchange._new_order(
            symbol=self.exchange.rules.symbol, side=side, type=OrderType.STOP_MARKET,
            qty=qty, submitted_ns=self.now_ns, stop_price=stop_price,
        )
        self.exchange.submit(order)
        return order.id

    def cancel(self, order_id: int) -> None:
        """Cancel an order (a fill already scheduled survives)."""
        self.exchange.cancel(order_id, self.now_ns)

    def set_timer(self, delay_ns: int) -> None:
        """Schedule on_timer once, delay_ns from now."""
        if self.on_timer_scheduled is not None:
            self.on_timer_scheduled(self.now_ns + delay_ns)

    def equity(self) -> float:
        """Account equity at the last known price."""
        price = self.exchange.last_price or 0.0
        return self.exchange.account.equity(price)

    def _submit(self, side: Side, order_type: OrderType, qty: float) -> int:
        order = self.exchange._new_order(
            symbol=self.exchange.rules.symbol, side=side, type=order_type,
            qty=qty, submitted_ns=self.now_ns,
        )
        self.exchange.submit(order)
        return order.id


class Strategy(ABC):
    """Base class: the SAME code runs in backtest, paper and live."""

    def on_start(self, ctx: Context) -> None:  # noqa: B027
        """Called once before the first bar."""

    @abstractmethod
    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        """Called when a bar closes; the bar is now in lookback history."""

    def on_fill(self, ctx: Context, event: FillEvent) -> None:  # noqa: B027
        """Called after each fill has been applied to the account."""

    def on_funding(self, ctx: Context, rate: float) -> None:  # noqa: B027
        """Called at each funding settlement, after the accounting is applied."""

    def on_timer(self, ctx: Context) -> None:  # noqa: B027
        """Called when a timer set via set_timer fires."""

    def on_end(self, ctx: Context) -> None:  # noqa: B027
        """Called once after the last bar; open positions remain (valuated)."""
