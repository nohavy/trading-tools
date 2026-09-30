"""Property-based tests (hypothesis) for ledger and margin account invariants."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tradingv2.portfolio.ledger import Ledger, LedgerReconcileError


@given(
    gross=st.floats(min_value=-1_000, max_value=1_000, allow_nan=False),
    fee=st.floats(min_value=0, max_value=50, allow_nan=False),
    slippage=st.floats(min_value=0, max_value=50, allow_nan=False),
    funding=st.floats(min_value=-100, max_value=100, allow_nan=False),
)
def test_single_trade_reconciles(gross: float, fee: float, slippage: float, funding: float) -> None:
    ledger = Ledger()
    trade = ledger.record_trade(gross=gross, fee=fee, slippage=slippage, funding=funding)
    assert trade.net == gross - fee - slippage - funding
    totals = ledger.totals()
    assert totals.net == trade.net
    ledger.assert_reconciled()


@given(
    trades=st.lists(
        st.tuples(
            st.floats(min_value=-1_000, max_value=1_000, allow_nan=False),
            st.floats(min_value=0, max_value=50, allow_nan=False),
            st.floats(min_value=0, max_value=50, allow_nan=False),
            st.floats(min_value=-100, max_value=100, allow_nan=False),
        ),
        max_size=50,
    )
)
def test_totals_equal_sum_of_parts(trades: list[tuple[float, float, float, float]]) -> None:
    ledger = Ledger()
    for gross, fee, slippage, funding in trades:
        ledger.record_trade(gross=gross, fee=fee, slippage=slippage, funding=funding)
    totals = ledger.totals()
    assert totals.gross == sum(t[0] for t in trades)
    assert totals.fee == sum(t[1] for t in trades)
    assert totals.slippage == sum(t[2] for t in trades)
    assert totals.funding == sum(t[3] for t in trades)
    expected_net = sum(g - f - s - fu for g, f, s, fu in trades)
    assert totals.net == pytest.approx(expected_net, abs=1e-6)
    ledger.assert_reconciled()


@given(
    gross=st.floats(min_value=-1_000, max_value=1_000, allow_nan=False),
    fee=st.floats(min_value=0, max_value=50, allow_nan=False),
    slippage=st.floats(min_value=0, max_value=50, allow_nan=False),
    funding=st.floats(min_value=-100, max_value=100, allow_nan=False),
    tamper=st.floats(min_value=1e-3, max_value=1_000, allow_nan=False),
)
def test_any_tampering_is_detected(
    gross: float, fee: float, slippage: float, funding: float, tamper: float
) -> None:
    ledger = Ledger()
    ledger.record_trade(gross=gross, fee=fee, slippage=slippage, funding=funding)
    trade = ledger._trades[0]
    ledger._trades[0] = trade.__class__(
        gross=trade.gross,
        fee=trade.fee,
        slippage=trade.slippage,
        funding=trade.funding,
        net=trade.net + tamper,
    )
    with pytest.raises(LedgerReconcileError):
        ledger.assert_reconciled()


@settings(max_examples=50)
@given(
    balance=st.floats(min_value=100, max_value=1_000_000, allow_nan=False),
    entry=st.floats(min_value=1_000, max_value=100_000, allow_nan=False),
    qty=st.floats(min_value=0.001, max_value=10, allow_nan=False),
    exit_price=st.floats(min_value=1_000, max_value=100_000, allow_nan=False),
)
def test_margin_realized_pnl_matches_manual(
    balance: float, entry: float, qty: float, exit_price: float
) -> None:
    from tradingv2.core.types import Fill, FillRole, Side
    from tradingv2.portfolio.margin import MarginAccount

    leverage = 20.0
    # keep the position within margin AND away from ruin on the price move
    max_qty = balance * leverage / entry
    qty = min(qty, max_qty * 0.99)
    # cap the adverse move so the realized loss stays far from the balance
    max_adverse = balance * 0.5 / qty
    exit_price = max(entry - max_adverse, min(exit_price, entry + max_adverse))
    account = MarginAccount(balance=balance, leverage=leverage)
    open_fill = Fill(
        order_id=1, ts_ns=0, price=entry, qty=qty, fee=0.0, role=FillRole.TAKER, side=Side.BUY
    )
    close_fill = Fill(
        order_id=2, ts_ns=0, price=exit_price, qty=qty, fee=0.0, role=FillRole.TAKER, side=Side.SELL
    )
    account.apply_fill(open_fill)
    realized = account.apply_fill(close_fill)
    # rounding tolerance grows with the price scale (entry*qty products)
    scale = max(1.0, entry * qty)
    assert realized == pytest.approx((exit_price - entry) * qty, abs=1e-9 * scale)
    # full close: the residual position is float rounding, not a real position
    assert account.position == pytest.approx(0.0, abs=1e-9 * max(1.0, qty))
    # balance reflects only the realized PnL (no fees)
    assert account.balance == pytest.approx(
        balance + realized, abs=1e-9 * scale
    )
