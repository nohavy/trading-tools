"""Core domain types: orders, fills, positions."""

from dataclasses import dataclass
from enum import StrEnum


class Side(StrEnum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"


class OrderStatus(StrEnum):
    """Order lifecycle status."""

    PENDING = "pending"
    ACTIVE = "active"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class FillRole(StrEnum):
    """Maker or taker for the fill."""

    MAKER = "maker"
    TAKER = "taker"


class OrderError(Exception):
    """Raised when an order cannot be constructed."""


class InvalidTransitionError(Exception):
    """Raised when an order status transition is not allowed."""


_TERMINAL = {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}
_ALLOWED: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.ACTIVE, OrderStatus.CANCELED, OrderStatus.REJECTED},
    OrderStatus.ACTIVE: {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED},
}


@dataclass
class Order:
    """One order in the simulated exchange."""

    id: int
    symbol: str
    side: Side
    type: OrderType
    qty: float
    submitted_ns: int
    limit_price: float | None = None
    stop_price: float | None = None
    post_only: bool = False
    arrive_ns: int | None = None
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: str | None = None

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise OrderError(f"qty must be positive, got {self.qty}")
        if self.type == OrderType.LIMIT and self.limit_price is None:
            raise OrderError("limit orders require limit_price")
        if self.type == OrderType.MARKET and self.limit_price is not None:
            raise OrderError("market orders must not carry limit_price")
        if self.type == OrderType.STOP_MARKET and self.stop_price is None:
            raise OrderError("stop orders require stop_price")
        if self.post_only and self.type != OrderType.LIMIT:
            raise OrderError("post_only applies to limit orders only")

    def transition(self, new_status: OrderStatus) -> None:
        """Move the order to a new status if allowed."""
        if self.status in _TERMINAL:
            raise InvalidTransitionError(f"order {self.id} is terminal ({self.status.value})")
        allowed = _ALLOWED.get(self.status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"order {self.id}: cannot go from {self.status.value} to {new_status.value}"
            )
        self.status = new_status


@dataclass(frozen=True)
class FundingEvent:
    """One funding settlement for a perpetual."""

    ts_ns: int
    rate: float


@dataclass(frozen=True)
class PriceBar:
    """One OHLC bar delivered at its close time."""

    ts_open_ns: int
    open: float
    high: float
    low: float
    close: float
    ts_close_ns: int


@dataclass(frozen=True)
class Fill:
    """One executed (partial or complete) order fill."""

    order_id: int
    ts_ns: int
    price: float
    qty: float
    fee: float
    role: FillRole
    side: Side
