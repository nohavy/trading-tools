"""Single-entry legs of the always-covered spot/perp cash-and-carry hedge."""

from tradingv2.core.types import PriceBar, Side
from tradingv2.strategy.base import Context, Strategy

_DAY_NS = 86_400_000_000_000


class CashCarryLeg(Strategy):
    """One leg of the always-covered carry: enter once, never exit.

    The entry decision happens at the first daily close boundary at or after
    ``trade_start_ns`` and fills at the following 1m open with engine latency
    and slippage. A rejected order is never retried: the leg stays flat and
    the validation's fidelity checks surface the failure.
    """

    def __init__(self, side: Side, qty: float, trade_start_ns: int = 0) -> None:
        if qty <= 0.0:
            raise ValueError("qty must be positive")
        if trade_start_ns < 0:
            raise ValueError("trade_start_ns must be non-negative")
        self._side = side
        self._qty = qty
        self._trade_start_ns = trade_start_ns
        self._submitted = False
        self._order_id: int | None = None

    def on_bar(self, ctx: Context, bar: PriceBar) -> None:
        if self._submitted:
            return
        if bar.ts_close_ns % _DAY_NS != 0:
            return
        if bar.ts_close_ns < self._trade_start_ns:
            return
        self._submitted = True
        self._order_id = ctx.submit_market(self._side, qty=self._qty)

    def export_state(self) -> dict[str, float | int | bool]:
        return {"submitted": self._submitted}

    def import_state(self, state: dict[str, float | int | bool]) -> None:
        self._submitted = bool(state.get("submitted", False))

    def restore_from_position(self, position: float) -> None:
        """One-entry semantics: a live position means the entry was submitted."""
        if position != 0.0:
            self._submitted = True


class CashCarrySpotLeg(CashCarryLeg):
    """Long spot leg, held on the cash (quote/base) account."""

    def __init__(self, qty: float, trade_start_ns: int = 0) -> None:
        super().__init__(Side.BUY, qty, trade_start_ns)


class CashCarryPerpLeg(CashCarryLeg):
    """Short perpetual leg, held on the margin account."""

    def __init__(self, qty: float, trade_start_ns: int = 0) -> None:
        super().__init__(Side.SELL, qty, trade_start_ns)
