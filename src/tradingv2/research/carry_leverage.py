"""Frozen sizing-factor support for the levered always-covered carry (014).

The factor multiplies the validated hedge quantity. Above 1 the spot leg must
run on a borrow-capable margin spot account and the perp leg needs a leverage
setting that still fits the notional: both derivations are frozen here so the
runner, configs and tests share one source of truth.
"""

import copy
import math
from collections.abc import Mapping
from typing import Any

FACTOR_MIN = 1.0
FACTOR_MAX = 6.0


def check_factor(factor: float) -> None:
    """Validate a sizing factor against the frozen bounds."""
    if not FACTOR_MIN <= factor <= FACTOR_MAX:
        raise ValueError(f"sizing_factor must be in [{FACTOR_MIN}, {FACTOR_MAX}], got {factor}")


def scaled_qty(qty: float, factor: float) -> float:
    """The hedge quantity multiplied by the sizing factor."""
    if qty <= 0.0:
        raise ValueError(f"qty must be positive, got {qty}")
    check_factor(factor)
    return qty * factor


def derive_legs_cfg(
    legs: Mapping[str, Any],
    *,
    factor: float,
    hedge_fraction: float,
    spot_margin_mmr: float,
    borrow_apr_pct: float,
) -> dict[str, dict[str, Any]]:
    """Return the leg configs of a levered run (pure, deep-copied).

    At factor 1 the legs pass through untouched. Above 1 the spot leg is
    re-accounted as a borrow-capable margin spot account (frozen MMR + APR)
    and the perp leg leverage setting is raised to ceil(factor x fraction)
    so the margin check still fits the equity.
    """
    check_factor(factor)
    legs_out: dict[str, dict[str, Any]] = {}
    for name, leg_raw in legs.items():
        leg_cfg: dict[str, Any] = copy.deepcopy(dict(leg_raw))
        if factor > 1.0 and name == "spot":
            leg_cfg["account"] = {
                "type": "margin_spot",
                "balance": float(leg_cfg["account"]["balance"]),
                "mmr": float(spot_margin_mmr),
                "borrow_apr_pct": float(borrow_apr_pct),
            }
        elif factor > 1.0 and name == "perp":
            account = dict(leg_cfg["account"])
            setting = math.ceil(factor * hedge_fraction)
            account["leverage"] = max(int(account["leverage"]), setting)
            leg_cfg["account"] = account
        legs_out[name] = leg_cfg
    return legs_out
