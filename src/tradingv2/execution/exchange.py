"""Simulated exchange: order validation, latency arrival, predictive fills.

Fill scheduling over the trade tape is vectorized (searchsorted): the cost of
an active order is O(log n) per event, not O(trades). Cancellation after a
scheduled fill time behaves like reality: the fill still arrives.
"""

from dataclasses import dataclass, field
from heapq import heapify, heappop, heappush
from typing import Protocol

import numpy as np
import polars as pl

from tradingv2.core.rounding import (
    order_values_pass_filters,
    round_price_to_tick,
    round_qty_to_step,
)
from tradingv2.core.types import Fill, FillRole, Order, OrderStatus, OrderType, Side
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.portfolio.spot import AccountError
from tradingv2.portfolio.tracker import PositionTracker


class ExchangeError(Exception):
    """Raised for exchange-level misuse (unknown order id, etc.)."""


@dataclass(frozen=True)
class FillEvent:
    """One fill applied to the account, with its PnL decomposition."""

    fill: Fill
    realized_gross: float
    slippage_cost: float


@dataclass
class _ScheduledFill:
    """Pending fill work for one order."""

    order: Order
    start_idx: int
    remaining: float
    reference_price: float | None


class Account(Protocol):
    """Common account interface used by the exchange."""

    def apply_fill(self, fill: Fill) -> float: ...

    def equity(self, mark_price: float) -> float: ...


@dataclass
class SimulatedExchange:
    """Order lifecycle simulation against a trade tape (or bars only)."""

    rules: InstrumentRules
    account: Account
    fees: FeeSchedule
    slippage: SlippageModel
    latency: LatencyModel
    tape: pl.DataFrame | None = None
    limit_fill_mode: str = "pessimistic"
    _tracker: PositionTracker = field(default_factory=PositionTracker, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.limit_fill_mode not in ("pessimistic", "optimistic"):
            raise ValueError(
                f"invalid limit_fill_mode '{self.limit_fill_mode}': expected pessimistic|optimistic"
            )
        self.last_price: float | None = None
        self._tape_ts: np.ndarray[tuple[int], np.dtype[np.int64]] | None = None
        self._tape_price: np.ndarray[tuple[int], np.dtype[np.float64]] | None = None
        self._tape_qty: np.ndarray[tuple[int], np.dtype[np.float64]] | None = None
        self._tape_buyer_maker: np.ndarray[tuple[int], np.dtype[np.bool_]] | None = None
        if self.tape is not None:
            self._tape_ts = self.tape["ts_ns"].to_numpy()
            self._tape_price = self.tape["price"].to_numpy()
            self._tape_qty = self.tape["qty"].to_numpy()
            self._tape_buyer_maker = self.tape["buyer_is_maker"].to_numpy()
            self.last_price = float(self._tape_price[0])
        self._orders: dict[int, Order] = {}
        self._arrivals: list[tuple[int, int, Order]] = []
        self._scheduled: list[tuple[int, int, _ScheduledFill]] = []
        self._seq = 0

    # -- submission ----------------------------------------------------------

    def submit(self, order: Order) -> Order:
        """Queue an order; it is validated at arrival (after latency)."""
        order.arrive_ns = order.submitted_ns + self.latency.sample_ns()
        self._orders[order.id] = order
        self._seq += 1
        heappush(self._arrivals, (order.arrive_ns, self._seq, order))
        return order

    def cancel(self, order_id: int, now_ns: int) -> None:
        """Cancel an order; a fill already scheduled survives (like reality)."""
        order = self._orders.get(order_id)
        if order is None:
            raise ExchangeError(f"unknown order id {order_id}")
        if order.status == OrderStatus.PENDING:
            order.transition(OrderStatus.CANCELED)
            return
        if order.status != OrderStatus.ACTIVE:
            return
        for ts, seq, scheduled in self._scheduled:
            if scheduled.order.id == order_id:
                if ts > now_ns + self.latency.sample_ns():
                    order.transition(OrderStatus.CANCELED)
                    self._scheduled.remove((ts, seq, scheduled))
                    heapify(self._scheduled)
                return
        order.transition(OrderStatus.CANCELED)

    # -- clock ---------------------------------------------------------------

    def advance_to(self, ts_ns: int) -> list[FillEvent]:
        """Process arrivals and scheduled fills up to ts_ns; return fill events."""
        events: list[FillEvent] = []
        while self._arrivals and self._arrivals[0][0] <= ts_ns:
            _, _, order = heappop(self._arrivals)
            if order.status != OrderStatus.PENDING:
                continue
            self._activate(order)
        while self._scheduled and self._scheduled[0][0] <= ts_ns:
            _, _, scheduled = heappop(self._scheduled)
            if scheduled.order.status != OrderStatus.ACTIVE:
                continue
            if scheduled.order.type == OrderType.MARKET:
                event = self._execute_market(scheduled)
            elif scheduled.order.type == OrderType.STOP_MARKET:
                event = self._execute_stop(scheduled)
            else:
                event = self._execute_limit(scheduled)
            if event is not None:
                events.append(event)
        return events

    # -- internals -----------------------------------------------------------

    def _reference_price(self) -> float | None:
        return self.last_price

    def _activate(self, order: Order) -> None:
        price = self._reference_price()
        original_qty = order.qty
        if order.type == OrderType.LIMIT:
            assert order.limit_price is not None
            order.limit_price = round_price_to_tick(order.limit_price, self.rules.tick_size)
        order.qty = round_qty_to_step(order.qty, self.rules.step_size)
        if order.type == OrderType.LIMIT:
            check_price = order.limit_price
        elif order.type == OrderType.STOP_MARKET:
            check_price = order.stop_price
        else:
            check_price = price
        if check_price is None:
            order.transition(OrderStatus.REJECTED)
            order.reject_reason = "no reference price for market order validation"
            return
        ok, reason = order_values_pass_filters(
            original_qty,
            check_price,
            self.rules.step_size,
            self.rules.tick_size,
            self.rules.min_notional,
        )
        if not ok:
            assert reason is not None
            order.transition(OrderStatus.REJECTED)
            order.reject_reason = reason
            return
        if order.type == OrderType.LIMIT and order.post_only and self._would_cross(order):
            order.transition(OrderStatus.REJECTED)
            order.reject_reason = "post-only order would cross the book"
            return
        try:
            self._check_funds(order, check_price)
        except AccountError as exc:
            order.transition(OrderStatus.REJECTED)
            order.reject_reason = str(exc)
            return
        order.transition(OrderStatus.ACTIVE)
        if order.type == OrderType.MARKET:
            self._schedule_market(order)
        elif order.type == OrderType.STOP_MARKET:
            self._schedule_stop(order)
        else:
            self._schedule_limit(order)

    def _would_cross(self, order: Order) -> bool:
        assert order.limit_price is not None
        price = self._reference_price()
        if price is None:
            return False
        if order.side == Side.BUY:
            return price <= order.limit_price
        return price >= order.limit_price

    def _check_funds(self, order: Order, price: float) -> None:
        from tradingv2.portfolio.margin import MarginAccount
        from tradingv2.portfolio.spot import SpotAccount

        if isinstance(self.account, SpotAccount):
            required = order.qty * price
            if order.side == Side.BUY:
                worst_fee = self.fees.fee("taker", required)
                if required + worst_fee > self.account.quote_balance:
                    raise AccountError(f"insufficient quote for {order.qty} at {price}")
            return
        if isinstance(self.account, MarginAccount):
            notional = order.qty * price
            margin_used = notional / self.account.leverage
            if margin_used > self.account.equity(price):
                raise AccountError(
                    f"insufficient margin: used {margin_used} > equity {self.account.equity(price)}"
                )

    # -- market fills on the tape -------------------------------------------

    def _aggressor_mask(self, side: Side) -> np.ndarray[tuple[int], np.dtype[np.bool_]]:
        assert self._tape_buyer_maker is not None
        # buy market orders consume aggressor-buy trades (buyer is taker);
        # sell market orders consume trades where the buyer is the maker.
        mask: np.ndarray[tuple[int], np.dtype[np.bool_]] = (
            self._tape_buyer_maker == (side == Side.SELL)
        ).astype(np.bool_)
        return mask

    def _schedule_market(self, order: Order) -> None:
        assert self._tape_ts is not None
        assert order.arrive_ns is not None
        first = self._first_aggressor_index(order.arrive_ns, order.side)
        if first is None:
            return  # no liquidity yet: the order rests
        reference = self._reference_price()
        self._seq += 1
        scheduled = _ScheduledFill(order, first, order.qty, reference)
        heappush(self._scheduled, (int(self._tape_ts[first]), self._seq, scheduled))

    def _first_aggressor_index(self, from_ns: int, side: Side) -> int | None:
        assert self._tape_ts is not None
        lo = int(np.searchsorted(self._tape_ts, from_ns, side="left"))
        if lo >= len(self._tape_ts):
            return None
        mask = self._aggressor_mask(side)[lo:]
        indices = np.nonzero(mask)[0]
        if indices.size == 0:
            return None
        return lo + int(indices[0])

    def _execute_market(self, scheduled: _ScheduledFill) -> FillEvent | None:
        assert self._tape_ts is not None
        assert self._tape_price is not None
        assert self._tape_qty is not None
        order = scheduled.order
        aggressor = self._aggressor_mask(order.side)
        notional = 0.0
        consumed = 0.0
        last_ts = int(self._tape_ts[scheduled.start_idx])
        index = scheduled.start_idx
        remaining = scheduled.remaining
        while remaining > 1e-12 and index < len(self._tape_ts):
            if aggressor[index]:
                take = min(float(self._tape_qty[index]), remaining)
                notional += float(self._tape_price[index]) * take
                consumed += take
                remaining -= take
                last_ts = int(self._tape_ts[index])
            index += 1
        if remaining > 1e-12:
            return None  # tape exhausted: the order rests (sizes << liquidity in v1)
        vwap = notional / consumed
        fee = self.fees.fee("taker", notional)
        fill = Fill(
            order_id=order.id,
            ts_ns=last_ts,
            price=vwap,
            qty=consumed,
            fee=fee,
            role=FillRole.TAKER,
            side=order.side,
        )
        order.transition(OrderStatus.FILLED)
        realized = self._tracker.apply(fill.qty if order.side == Side.BUY else -fill.qty, vwap)
        self.account.apply_fill(fill)
        slippage = self._slippage_cost(scheduled.reference_price, vwap, consumed, order.side)
        self.last_price = vwap
        return FillEvent(fill=fill, realized_gross=realized, slippage_cost=slippage)

    def _slippage_cost(
        self, reference: float | None, fill_price: float, qty: float, side: Side
    ) -> float:
        if reference is None:
            return 0.0
        sign = 1.0 if side == Side.BUY else -1.0
        return (fill_price - reference) * qty * sign

    # -- limit fills on the tape ---------------------------------------------

    def _schedule_limit(self, order: Order) -> None:
        assert self._tape_ts is not None
        assert self._tape_price is not None
        assert order.arrive_ns is not None
        assert order.limit_price is not None
        first = self._first_limit_index(order.arrive_ns, order.side, order.limit_price)
        if first is None:
            return  # rests until the market trades through the level
        reference = self._reference_price()
        self._seq += 1
        scheduled = _ScheduledFill(order, first, order.qty, reference)
        heappush(self._scheduled, (int(self._tape_ts[first]), self._seq, scheduled))

    def _first_limit_index(self, from_ns: int, side: Side, limit: float) -> int | None:
        assert self._tape_ts is not None
        assert self._tape_price is not None
        lo = int(np.searchsorted(self._tape_ts, from_ns, side="left"))
        if lo >= len(self._tape_ts):
            return None
        prices = self._tape_price[lo:]
        if side == Side.BUY:
            mask = prices < limit if self.limit_fill_mode == "pessimistic" else prices <= limit
        else:
            mask = prices > limit if self.limit_fill_mode == "pessimistic" else prices >= limit
        indices = np.nonzero(mask)[0]
        if indices.size == 0:
            return None
        return lo + int(indices[0])

    def _execute_limit(self, scheduled: _ScheduledFill) -> FillEvent | None:
        assert self._tape_ts is not None
        assert self._tape_price is not None
        order = scheduled.order
        assert order.limit_price is not None
        fill_ts = int(self._tape_ts[scheduled.start_idx])
        market_price = float(self._tape_price[scheduled.start_idx])
        fee = self.fees.fee("maker", order.qty * order.limit_price)
        fill = Fill(
            order_id=order.id,
            ts_ns=fill_ts,
            price=order.limit_price,
            qty=order.qty,
            fee=fee,
            role=FillRole.MAKER,
            side=order.side,
        )
        order.transition(OrderStatus.FILLED)
        signed = fill.qty if order.side == Side.BUY else -fill.qty
        realized = self._tracker.apply(signed, order.limit_price)
        self.account.apply_fill(fill)
        self.last_price = market_price
        return FillEvent(fill=fill, realized_gross=realized, slippage_cost=0.0)

    # -- stop fills on the tape ----------------------------------------------

    def _schedule_stop(self, order: Order) -> None:
        assert self._tape_ts is not None
        assert self._tape_price is not None
        assert order.arrive_ns is not None
        assert order.stop_price is not None
        lo = int(np.searchsorted(self._tape_ts, order.arrive_ns, side="left"))
        first: int | None = None
        if lo < len(self._tape_ts):
            prices = self._tape_price[lo:]
            mask = (
                prices >= order.stop_price if order.side == Side.BUY else prices <= order.stop_price
            )
            indices = np.nonzero(mask)[0]
            if indices.size > 0:
                first = lo + int(indices[0])
        if first is None:
            return  # rests until the stop level trades
        reference = self._reference_price()
        self._seq += 1
        scheduled = _ScheduledFill(order, first, order.qty, reference)
        heappush(self._scheduled, (int(self._tape_ts[first]), self._seq, scheduled))

    def _execute_stop(self, scheduled: _ScheduledFill) -> FillEvent | None:
        assert self._tape_price is not None
        order = scheduled.order
        trigger_price = float(self._tape_price[scheduled.start_idx])
        notional = order.qty * trigger_price
        fee = self.fees.fee("taker", notional)
        fill = Fill(
            order_id=order.id,
            ts_ns=int(self._tape_ts[scheduled.start_idx]),
            price=trigger_price,
            qty=order.qty,
            fee=fee,
            role=FillRole.TAKER,
            side=order.side,
        )
        order.transition(OrderStatus.FILLED)
        signed = fill.qty if order.side == Side.BUY else -fill.qty
        realized = self._tracker.apply(signed, trigger_price)
        self.account.apply_fill(fill)
        slippage = self._slippage_cost(
            scheduled.reference_price, trigger_price, order.qty, order.side
        )
        self.last_price = trigger_price
        return FillEvent(fill=fill, realized_gross=realized, slippage_cost=slippage)
