"""Backtest event engine: strict event ordering at equal timestamps.

Ordering (constitution III): exchange (arrivals + scheduled fills) ->
strategy on_fill -> bar close -> timers -> strategy on_bar, with a global
sequence number breaking ties deterministically.
"""

import heapq
from dataclasses import dataclass, field

from tradingv2.core.types import Order, PriceBar
from tradingv2.execution.exchange import FillEvent, SimulatedExchange
from tradingv2.strategy.base import Context, Strategy


@dataclass
class EngineResult:
    """Raw run outputs (metrics and reporting are feature 003)."""

    n_bars: int
    fill_events: list[FillEvent] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    final_equity: float = 0.0
    orders: list[Order] = field(default_factory=list)


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

    def _on_timer_scheduled(self, ts_ns: int) -> None:
        """Callback used by the Context to register a timer in the engine heap."""
        self._timers.add(ts_ns)

    def _push(self, heap: list[_Event], ts: int, priority: int) -> None:
        self._seq += 1
        heapq.heappush(heap, _Event(ts=ts, priority=priority, seq=self._seq))

    def run(self) -> EngineResult:
        """Run the whole backtest and return raw results."""
        heap: list[_Event] = []
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

            # 2) then the event itself
            if event.priority == 1:  # bar close
                bar = self._bar_by_close[event.ts]
                self._closed_bars.append(bar)
                # bars-only mode: evaluate queued orders on the closing bar
                bar_events = self.exchange.on_bar_close(bar)
                for fill_event in bar_events:
                    self._fill_events.append(fill_event)
                    self.strategy.on_fill(ctx, fill_event)
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
        )
