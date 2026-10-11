"""Tests for the on-chain whale screen (012): net flux vs next returns."""

import pytest

from tradingv2.research.onchain_screen import screen_net_flows


def test_screen_enters_short_only_on_heavy_inflow_and_lags_one_day() -> None:
    result = screen_net_flows(
        deposits=[100.0, 100.0, 900.0, 100.0],
        withdraws=[10.0, 10.0, 10.0, 10.0],
        closes=[100.0, 110.0, 90.0, 105.0, 110.0],
        lookback_days=1,
        entry_net_in=800.0,       # heavy net deposits → short
        flat_exit=200.0,          # decayed net |inflow| → flat again
        cost_bps=10.0,
    )
    assert result.positions.tolist() == [0, 0, -1, 0]
    # the fee is paid on entry AND on the flip back to flat, never on holds
    assert result.fees_bcps.tolist() == [0, 0, 10.0, 10.0]
    # short applies over the NEXT interval after the decision (t -> t+1),
    # and the 10 bps entry fee is deducted from that same interval
    assert result.net_returns.tolist() == pytest.approx(
        [0.0, 0.0, -(105.0 / 90.0 - 1.0) - 10e-4, -10e-4]
    )


def test_screen_never_uses_later_flows_for_a_decision() -> None:
    result = screen_net_flows(
        deposits=[0.0, 0.0, 1000.0],
        withdraws=[0.0, 0.0, 0.0],
        closes=[100.0, 100.0, 100.0, 100.0],
        lookback_days=1,
        entry_net_in=500.0,
        flat_exit=100.0,
        cost_bps=0.0,
    )
    assert abs(result.positions[0]) == abs(result.positions[1]) == 0.0


def test_screen_validates_aligned_inputs() -> None:
    with pytest.raises(ValueError, match="aligned"):
        screen_net_flows(
            deposits=[1.0] * 3, withdraws=[1.0] * 3, closes=[1.0] * 2,
            lookback_days=1, entry_net_in=0.0, flat_exit=0.0,
            cost_bps=10.0,
        )
