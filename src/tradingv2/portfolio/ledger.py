"""Categorized PnL ledger with reconciliation invariant."""

from dataclasses import dataclass


class LedgerReconcileError(Exception):
    """Raised when the ledger invariant is violated."""


@dataclass(frozen=True)
class TradePnl:
    """PnL decomposition of one closed position."""

    gross: float
    fee: float
    slippage: float
    funding: float
    net: float


@dataclass(frozen=True)
class LedgerTotals:
    """Cumulative ledger totals."""

    gross: float
    fee: float
    slippage: float
    funding: float
    net: float
    n_trades: int


def _reconciled_net(trade: TradePnl) -> float:
    return trade.gross - trade.fee - trade.slippage - trade.funding


class Ledger:
    """Records closed-trade PnL decompositions and enforces net accounting.

    Invariant (constitution II): net = gross - fee - slippage - funding,
    where funding is signed (paid > 0, received < 0).
    """

    def __init__(self) -> None:
        self._trades: list[TradePnl] = []

    def record_trade(self, gross: float, fee: float, slippage: float, funding: float) -> TradePnl:
        """Record one closed trade and return its decomposition."""
        trade = TradePnl(
            gross=gross,
            fee=fee,
            slippage=slippage,
            funding=funding,
            net=gross - fee - slippage - funding,
        )
        self._trades.append(trade)
        return trade

    def totals(self) -> LedgerTotals:
        """Cumulative totals over all recorded trades."""
        n = len(self._trades)
        return LedgerTotals(
            gross=sum(t.gross for t in self._trades),
            fee=sum(t.fee for t in self._trades),
            slippage=sum(t.slippage for t in self._trades),
            funding=sum(t.funding for t in self._trades),
            net=sum(t.net for t in self._trades),
            n_trades=n,
        )

    def assert_reconciled(self, rel_tol: float = 1e-9) -> None:
        """Raise LedgerReconcileError unless every record and the totals reconcile."""
        for trade in self._trades:
            expected = _reconciled_net(trade)
            if abs(trade.net - expected) > rel_tol * max(1.0, abs(expected)):
                raise LedgerReconcileError(
                    f"trade net mismatch: stored {trade.net}, expected {expected}"
                )
        totals = self.totals()
        if totals.n_trades and abs(totals.net - sum(t.net for t in self._trades)) > rel_tol * max(
            1.0, abs(totals.net)
        ):
            raise LedgerReconcileError("cumulative net mismatch")
