"""Tests for the market-neutral spot-perp cash-and-carry screen."""

import numpy as np
import pytest

from tradingv2.research.cash_carry import simulate_cash_and_carry

DAY = 86_400_000_000_000


def _flat_books(
    n: int = 4, spot: float = 100.0, perp: float = 100.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ts = np.arange(n, dtype=np.int64) * DAY
    return ts, np.full(n, spot), np.full(n, perp)


def test_funding_received_by_short_has_no_lookahead() -> None:
    ts, spot, perp = _flat_books()
    settlements = np.array([DAY // 2, DAY + DAY // 2, 3 * DAY], dtype=np.int64)
    rates = np.array([0.01, 0.002, 0.50])
    result = simulate_cash_and_carry(
        ts, spot, perp, settlements, rates,
        lookback_days=1, entry_funding_sum=0.001, exit_funding_sum=-1.0,
        entry_basis=-1.0, exit_basis=-1.0, spot_cost_bps=0.0, perp_cost_bps=0.0,
    )
    # Decision at day-1 close sees 100 bps and enters; only the 20 bp settlement
    # inside the next interval is earned. The 50% settlement is after the sample.
    assert result.position.tolist() == [1.0, 1.0, 1.0]
    assert result.funding_returns[0] == pytest.approx(0.001)
    assert result.net_returns[0] == pytest.approx(0.001)


def test_basis_convergence_profits_the_hedge() -> None:
    ts = np.arange(3, dtype=np.int64) * DAY
    spot = np.array([100.0, 100.0, 100.0])
    perp = np.array([110.0, 100.0, 100.0])
    result = simulate_cash_and_carry(
        ts, spot, perp,
        np.array([DAY // 2], dtype=np.int64), np.array([0.01]),
        lookback_days=1, entry_funding_sum=0.001, exit_funding_sum=-1.0,
        entry_basis=0.0, exit_basis=-1.0, spot_cost_bps=0.0, perp_cost_bps=0.0,
    )
    assert result.position[0] == 1.0
    # qty = 1/210; perp falls by 10 while spot is unchanged.
    assert result.price_returns[0] == pytest.approx(10.0 / 210.0)
    assert result.funding_returns[0] == 0.0


def test_round_trip_charges_both_legs_once_each_way() -> None:
    ts, spot, perp = _flat_books(n=4)
    settlements = np.array(
        [DAY // 2, DAY + DAY // 2, 2 * DAY + DAY // 2], dtype=np.int64
    )
    rates = np.array([0.01, 0.01, -0.01])
    result = simulate_cash_and_carry(
        ts, spot, perp, settlements, rates,
        lookback_days=1, entry_funding_sum=0.001, exit_funding_sum=0.0,
        entry_basis=-1.0, exit_basis=-1.0, spot_cost_bps=10.0, perp_cost_bps=5.0,
    )
    assert result.position.tolist() == [1.0, 1.0, 0.0]
    # Equal prices: each transaction costs 7.5 bps of capital, entry + exit.
    assert result.fee_returns.sum() * 1e4 == pytest.approx(15.0, abs=0.05)


def test_negative_funding_and_discounted_perp_stay_flat() -> None:
    ts, spot, perp = _flat_books()
    perp = np.full(4, 99.0)
    result = simulate_cash_and_carry(
        ts, spot, perp,
        np.array([DAY // 2], dtype=np.int64), np.array([-0.01]),
        lookback_days=1, entry_funding_sum=0.001, exit_funding_sum=0.0,
        entry_basis=0.0, exit_basis=-1.0, spot_cost_bps=0.0, perp_cost_bps=0.0,
    )
    assert result.position.tolist() == [0.0, 0.0, 0.0]
    assert result.net_returns.tolist() == pytest.approx([0.0, 0.0, 0.0])


def test_future_funding_cannot_trigger_entry() -> None:
    ts, spot, perp = _flat_books(n=3)
    result = simulate_cash_and_carry(
        ts, spot, perp,
        np.array([DAY + 1], dtype=np.int64), np.array([0.05]),
        lookback_days=1, entry_funding_sum=0.001, exit_funding_sum=-1.0,
        entry_basis=-1.0, exit_basis=-1.0, spot_cost_bps=0.0, perp_cost_bps=0.0,
    )
    assert result.position[0] == 0.0
