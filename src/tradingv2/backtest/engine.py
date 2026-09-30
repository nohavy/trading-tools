"""Backtest event engine: strict event ordering at equal timestamps.

Ordering (constitution III): exchange (arrivals + scheduled fills) ->
strategy on_fill -> bar close -> timers -> strategy on_bar, with a global
sequence number breaking ties deterministically.

The engine also owns the round-trip accounting: fees, slippage and funding
are accumulated from order entry to position close, then recorded in the
ledger (invariant: net = gross - fees - slippage - funding).
"""

import heapq
from dataclasses import dataclass, field

from tradingv2.core.types import FundingEvent, Order, PriceBar
from tradingv2.execution.exchange import FillEvent, SimulatedExchange
from tradingv2.portfolio.ledger import Ledger, LedgerTotals
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.strategy.base import Context, Strategy


@dataclass(frozen=True)
class RoundTrip:
    """One closed position, from first entry fill to the closing fill."""

    entry_ts: int
    exit_ts: int
    side: str
    qty: float
    entry_price: float
    exit_price: float
    gross: float
    fees: float
    slippage: float
    funding: float
    net: float
    hold_ns: int


@dataclass
class EngineResult:
    """Raw run outputs."""

    n_bars: int
    fill_events: list[FillEvent] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    final_equity: float = 0.0
    orders: list[Order] = field(default_factory=list)
    round_trips: list[RoundTrip] = field(default_factory=list)
    ledger_totals: LedgerTotals | None = None


@dataclass(order=True)
class _Event:
    """Heap event: (ts, priority, seq). Exchange events beat bars beat timers."""

    ts: int
    priority: int
    seq: int


class Engine:
    """Drives a strategy over a bar series through the simulated exchange."""

    def __init__(
        self,
        exchange: SimulatedExchange,
        strategy: Strategy,
        bars: list[PriceBar],
        initial_equity: float = 0.0,
    ) -> None:
        self.exchange = exchange
        self.strategy = strategy
        self.bars = sorted(bars, key=lambda b: b.ts_close_ns)
        self._bar_by_close: dict[int, PriceBar] = {}
        for bar in self.bars:
            self._bar_by_close[bar.ts_close_ns] = bar
        mark = exchange.last_price or 0.0
        self._initial_equity = (
            initial_equity if initial_equity > 0 else exchange.account.equity(mark)
        )
        self._closed_bars: list[PriceBar] = []
        self._fill_events: list[FillEvent] = []
        self._equity_curve: list[tuple[int, float]] = []
        self._seq = 0
        self._timers: set[int] = set()
        self._ledger = Ledger()
        self._round_trips: list[RoundTrip] = []
        # round-trip accumulators
        self._trip_open = False
        self._trip_entry_ts = 0
        self._trip_entry_price = 0.0
        self._trip_side = "buy"
        self._trip_qty = 0.0
        self._trip_gross = 0.0
        self._trip_fees = 0.0
        self._trip_slippage = 0.0
        self._trip_funding = 0.0

    def _on_timer_scheduled(self, ts_ns: int) -> None:
        """Callback used by the Context to register a timer in the engine heap."""
        self._timers.add(ts_ns)

    def _push(self, heap: list[_Event], ts: int, priority: int) -> None:
        self._seq += 1
        heapq.heappush(heap, _Event(ts=ts, priority=priority, seq=self._seq))

    def _start_trip(self, event: FillEvent) -> None:
        self._trip_open = True
        self._trip_entry_ts = event.fill.ts_ns
        self._trip_entry_price = event.fill.price
        self._trip_side = event.fill.side.value
        self._trip_qty = event.fill.qty
        self._trip_gross = event.realized_gross
        self._trip_fees = event.fill.fee
        self._trip_slippage = event.slippage_cost
        self._trip_funding = 0.0

    def _close_trip(self, event: FillEvent) -> None:
        trip = RoundTrip(
            entry_ts=self._trip_entry_ts,
            exit_ts=event.fill.ts_ns,
            side=self._trip_side,
            qty=self._trip_qty,
            entry_price=self._trip_entry_price,
            exit_price=event.fill.price,
            gross=self._trip_gross,
            fees=self._trip_fees,
            slippage=self._trip_slippage,
            funding=self._trip_funding,
            net=self._trip_gross - self._trip_fees - self._trip_slippage - self._trip_funding,
            hold_ns=event.fill.ts_ns - self._trip_entry_ts,
        )
        self._ledger.record_trade(
            gross=trip.gross, fee=trip.fees, slippage=trip.slippage, funding=trip.funding
        )
        self._round_trips.append(trip)
        self._trip_open = False

    def _account_fill(self, ctx: Context, event: FillEvent) -> None:
        if not self._trip_open:
            self._start_trip(event)
        else:
            self._trip_gross += event.realized_gross
            self._trip_fees += event.fill.fee
            self._trip_slippage += event.slippage_cost
        if self.exchange.position_qty == 0.0:
            self._close_trip(event)
        del ctx

    def _apply_funding(self, ts_ns: int, rate: float) -> None:
        account = self.exchange.account
        if not isinstance(account, MarginAccount):
            return
        mark = self.exchange.last_price or 0.0
        paid = account.apply_funding(ts_ns, rate, mark)
        if self._trip_open:
            self._trip_funding += paid

    def run(self, funding_events: list[FundingEvent] | None = None) -> EngineResult:
        """Run the whole backtest and return raw results."""
        funding_by_ts: dict[int, float] = {f.ts_ns: f.rate for f in (funding_events or [])}
        heap: list[_Event] = []
        # funding events first (lower seq): at equal ts they apply before bars
        for funding in funding_events or []:
            self._push(heap, funding.ts_ns, priority=1)
        for bar in self.bars:
            self._push(heap, bar.ts_close_ns, priority=1)
        ctx = Context(now_ns=0, exchange=self.exchange)
        ctx._closed_bars = self._closed_bars
        ctx.on_timer_scheduled = self._on_timer_scheduled
        self.strategy.on_start(ctx)

        while heap:
            # timers registered by the strategy join the heap before each pop
            while self._timers:
                ts = min(self._timers)
                self._timers.discard(ts)
                self._push(heap, ts, priority=2)
            event = heapq.heappop(heap)
            ctx.now_ns = event.ts

            # 1) exchange first, always: arrivals and scheduled fills up to now
            fills = self.exchange.advance_to(event.ts)
            for fill_event in fills:
                self._fill_events.append(fill_event)
                self.strategy.on_fill(ctx, fill_event)
                self._account_fill(ctx, fill_event)

            # 2) then the event itself
            if event.priority == 1:  # bar close or funding
                rate = funding_by_ts.get(event.ts)
                if rate is not None:
                    self._apply_funding(event.ts, rate)
                    if event.ts not in self._bar_by_close:
                        continue
                bar = self._bar_by_close[event.ts]
                self._closed_bars.append(bar)
                # bars-only mode: evaluate queued orders on the closing bar
                bar_events = self.exchange.on_bar_close(bar)
                for fill_event in bar_events:
                    self._fill_events.append(fill_event)
                    self.strategy.on_fill(ctx, fill_event)
                    self._account_fill(ctx, fill_event)
                self._equity_curve.append((event.ts, self.exchange.account.equity(bar.close)))
                self.strategy.on_bar(ctx, bar)
            elif event.priority == 2:  # timer
                self.strategy.on_timer(ctx)

        last_close = self.bars[-1].ts_close_ns if self.bars else 0
        final_mark = self.bars[-1].close if self.bars else (self.exchange.last_price or 0.0)
        ctx.now_ns = last_close
        self.strategy.on_end(ctx)
        return EngineResult(
            n_bars=len(self.bars),
            fill_events=self._fill_events,
            equity_curve=self._equity_curve,
            final_equity=self.exchange.account.equity(final_mark),
            orders=list(self.exchange._orders.values()),
            round_trips=self._round_trips,
            ledger_totals=self._ledger.totals(),
        )
