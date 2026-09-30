"""Simulated exchange: order validation, latency arrival, predictive fills.

Fill scheduling over the trade tape is vectorized (searchsorted): the cost of
an active order is O(log n) per event, not O(trades). Cancellation after a
scheduled fill time behaves like reality: the fill still arrives.
"""

import heapq
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


class ExchangeError(Exception):
    """Raised for exchange-level misuse (unknown order id, etc.)."""


class Account(Protocol):
    """Common account interface used by the exchange."""

    def apply_fill(self, fill: Fill) -> float: ...

    def equity(self, mark_price: float) -> float: ...


class SimulatedExchange:
    """Order lifecycle simulation against a trade tape (or bars only)."""

    def __init__(
        self,
        rules: InstrumentRules,
        account: Account,
        fees: FeeSchedule,
        slippage: SlippageModel,
        latency: LatencyModel,
        tape: pl.DataFrame | None = None,
        limit_fill_mode: str = "pessimistic",
    ) -> None:
        self.rules = rules
        self.account = account
        self.fees = fees
        self.slippage = slippage
        self.latency = latency
        self.limit_fill_mode = limit_fill_mode
        self.last_price: float | None = None
        self._tape_ts: np.ndarray[tuple[int], np.dtype[np.int64]] | None = None
        self._tape_price: np.ndarray[tuple[int], np.dtype[np.float64]] | None = None
        self._tape_qty: np.ndarray[tuple[int], np.dtype[np.float64]] | None = None
        self._tape_buyer_maker: np.ndarray[tuple[int], np.dtype[np.bool_]] | None = None
        if tape is not None:
            self._tape_ts = tape["ts_ns"].to_numpy()
            self._tape_price = tape["price"].to_numpy()
            self._tape_qty = tape["qty"].to_numpy()
            self._tape_buyer_maker = tape["buyer_is_maker"].to_numpy()
            self.last_price = float(self._tape_price[0])
        self._orders: dict[int, Order] = {}
        self._arrivals: list[tuple[int, int, Order]] = []
        self._scheduled: list[tuple[int, int, Order]] = []
        self._seq = 0

    # -- submission ----------------------------------------------------------

    def submit(self, order: Order) -> Order:
        """Queue an order; it is validated at arrival (after latency)."""
        order.arrive_ns = order.submitted_ns + self.latency.sample_ns()
        self._orders[order.id] = order
        self._seq += 1
        heapq.heappush(self._arrivals, (order.arrive_ns, self._seq, order))
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
            if scheduled.id == order_id:
                if ts > now_ns + self.latency.sample_ns():
                    order.transition(OrderStatus.CANCELED)
                    self._scheduled.remove((ts, seq, scheduled))
                    heapq.heapify(self._scheduled)
                return
        order.transition(OrderStatus.CANCELED)

    # -- clock ---------------------------------------------------------------

    def advance_to(self, ts_ns: int) -> list[Fill]:
        """Process arrivals and scheduled fills up to ts_ns; return fills made."""
        fills: list[Fill] = []
        while self._arrivals and self._arrivals[0][0] <= ts_ns:
            _, _, order = heapq.heappop(self._arrivals)
            if order.status != OrderStatus.PENDING:
                continue
            self._activate(order)
        while self._scheduled and self._scheduled[0][0] <= ts_ns:
            _, _, order = heapq.heappop(self._scheduled)
            if order.status != OrderStatus.ACTIVE:
                continue
            fill = self._execute(order)
            if fill is not None:
                fills.append(fill)
        return fills

    # -- internals -----------------------------------------------------------

    def _reference_price(self) -> float | None:
        return self.last_price

    def _activate(self, order: Order) -> None:
        price = self._reference_price()
        original_qty = order.qty
        if order.type != OrderType.MARKET:
            assert order.limit_price is not None
            order.limit_price = round_price_to_tick(order.limit_price, self.rules.tick_size)
        order.qty = round_qty_to_step(order.qty, self.rules.step_size)
        check_price = order.limit_price if order.type == OrderType.LIMIT else price
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
            self._schedule(order)

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
                worst_fee = self._worst_fee(order, FillRole.TAKER, required)
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

    def _worst_fee(self, order: Order, role: FillRole, notional: float) -> float:
        del order
        return self.fees.fee("taker" if role == FillRole.TAKER else "maker", notional)

    def _schedule(self, order: Order) -> None:
        # predictive fill scheduling is implemented in the tape-fill cycle (T010);
        # until then market orders rest without filling.
        del order

    def _execute(self, order: Order) -> Fill | None:
        del order
        raise NotImplementedError("tape fills arrive in T010-T012")
