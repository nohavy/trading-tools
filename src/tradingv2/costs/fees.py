"""Fee schedule for the simulated exchange."""

from typing import Literal

FillRoleName = Literal["maker", "taker"]


class FeeSchedule:
    """Maker/taker fee rates in basis points of traded notional."""

    def __init__(self, maker_bps: float, taker_bps: float) -> None:
        if maker_bps < 0 or taker_bps < 0:
            raise ValueError(
                f"fee bps must be non-negative, got maker={maker_bps} taker={taker_bps}"
            )
        self.maker_bps = maker_bps
        self.taker_bps = taker_bps

    def fee(self, role: FillRoleName, notional: float) -> float:
        """Fee in quote units for a fill of the given notional."""
        bps = self.maker_bps if role == "maker" else self.taker_bps
        return notional * bps / 10_000

    def round_trip_bps(self, entry_role: FillRoleName, exit_role: FillRoleName) -> float:
        """Total round-trip cost in bps for a given entry/exit order-type pair."""
        entry = self.maker_bps if entry_role == "maker" else self.taker_bps
        exit_ = self.maker_bps if exit_role == "maker" else self.taker_bps
        return entry + exit_
