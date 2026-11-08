"""Derivations of the levered carry legs (sizing factor, spot-margin re-account)."""

from typing import Any

import pytest

from tradingv2.research.carry_leverage import (
    check_factor,
    derive_legs_cfg,
    scaled_qty,
)

LEGS: dict[str, dict[str, Any]] = {
    "spot": {
        "strategy": "carry_spot_leg",
        "account": {"type": "spot", "balance": 10000},
        "costs": {"maker_bps": 10, "taker_bps": 10},
    },
    "perp": {
        "strategy": "carry_perp_leg",
        "account": {"type": "margin", "balance": 10000, "leverage": 2},
        "costs": {"maker_bps": 5, "taker_bps": 5},
    },
}


def test_factor_bounds_validation() -> None:
    check_factor(1.0)
    check_factor(3.5)
    check_factor(6.0)
    with pytest.raises(ValueError, match="sizing_factor"):
        check_factor(0.99)
    with pytest.raises(ValueError, match="sizing_factor"):
        check_factor(6.01)


def test_scaled_qty_multiplies_and_validates() -> None:
    assert scaled_qty(0.11357648, 3.5) == pytest.approx(0.39751768)
    with pytest.raises(ValueError, match="qty"):
        scaled_qty(0.0, 2.0)
    with pytest.raises(ValueError, match="sizing_factor"):
        scaled_qty(1.0, 9.0)


def test_factor_one_passes_legs_through_untouched() -> None:
    legs = derive_legs_cfg(
        LEGS, factor=1.0, hedge_fraction=0.95, spot_margin_mmr=0.05, borrow_apr_pct=6.0
    )
    assert legs["spot"] == LEGS["spot"]
    assert legs["perp"] == LEGS["perp"]


def test_factor_above_one_switches_spot_to_margin_spot_account() -> None:
    legs = derive_legs_cfg(
        LEGS, factor=3.5, hedge_fraction=0.95, spot_margin_mmr=0.05, borrow_apr_pct=6.0
    )
    assert legs["spot"]["account"] == {
        "type": "margin_spot",
        "balance": 10000.0,
        "mmr": 0.05,
        "borrow_apr_pct": 6.0,
    }
    assert legs["spot"]["strategy"] == "carry_spot_leg"


def test_factor_above_one_raises_perp_leverage_setting() -> None:
    legs = derive_legs_cfg(
        LEGS, factor=5.0, hedge_fraction=0.95, spot_margin_mmr=0.05, borrow_apr_pct=6.0
    )
    # notional 5 x 0.95 x equity needs margin fits: setting = ceil(4.75) = 5
    assert legs["perp"]["account"]["leverage"] == 5
    # cost lines untouched: only the account block moves
    assert legs["perp"]["costs"] == LEGS["perp"]["costs"]


def test_factor_two_keeps_setting_two() -> None:
    legs = derive_legs_cfg(
        LEGS, factor=2.0, hedge_fraction=0.95, spot_margin_mmr=0.05, borrow_apr_pct=6.0
    )
    assert legs["perp"]["account"]["leverage"] == 2


def test_derivation_is_copy_isolated() -> None:
    legs = derive_legs_cfg(
        LEGS, factor=2.0, hedge_fraction=0.95, spot_margin_mmr=0.05, borrow_apr_pct=6.0
    )
    legs["perp"]["account"]["leverage"] = 9
    assert LEGS["perp"]["account"]["leverage"] == 2
