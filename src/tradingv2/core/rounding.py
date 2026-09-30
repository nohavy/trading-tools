"""Exchange filter rounding and order value validation (decimal-exact)."""

from decimal import Decimal


class RoundingError(Exception):
    """Raised when a rounding input is invalid (non-positive step or value)."""


def _down(value: float, step: float) -> float:
    if step <= 0:
        raise RoundingError(f"step must be positive, got {step}")
    if value <= 0:
        raise RoundingError(f"value must be positive, got {value}")
    result = (Decimal(str(value)) // Decimal(str(step))) * Decimal(str(step))
    return float(result)


def round_qty_to_step(qty: float, step: float) -> float:
    """Round a quantity DOWN to the exchange lot step (decimal-exact)."""
    return _down(qty, step)


def round_price_to_tick(price: float, tick: float) -> float:
    """Round a price DOWN to the exchange tick (conservative, decimal-exact)."""
    return _down(price, tick)


def order_values_pass_filters(
    qty: float,
    price: float,
    step: float,
    tick: float,
    min_notional: float,
) -> tuple[bool, str | None]:
    """Validate rounded order values against exchange filters.

    Returns (True, None) when passable, else (False, reason).
    """
    if qty <= 0:
        return False, f"qty must be positive, got {qty}"
    if price <= 0:
        return False, f"price must be positive, got {price}"
    rounded_qty = round_qty_to_step(qty, step)
    if rounded_qty <= 0:
        return False, f"qty {qty} rounds to zero at step {step}"
    rounded_price = round_price_to_tick(price, tick)
    notional = rounded_qty * rounded_price
    if notional < min_notional:
        return False, f"notional {notional:.8f} below min {min_notional}"
    return True, None
