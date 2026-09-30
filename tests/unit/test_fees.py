"""Tests for the fee schedule."""

import pytest

from tradingv2.costs.fees import FeeSchedule

SCHEDULE = FeeSchedule(maker_bps=2, taker_bps=5)


def test_taker_fee() -> None:
    assert SCHEDULE.fee("taker", 10_000.0) == pytest.approx(5.0)


def test_maker_fee() -> None:
    assert SCHEDULE.fee("maker", 10_000.0) == pytest.approx(2.0)


def test_zero_notional_zero_fee() -> None:
    assert SCHEDULE.fee("taker", 0.0) == 0.0


def test_fee_is_notional_proportional() -> None:
    assert SCHEDULE.fee("taker", 123.45) == pytest.approx(123.45 * 5 / 10_000)


def test_round_trip_bps_combinations() -> None:
    assert SCHEDULE.round_trip_bps("maker", "maker") == 4
    assert SCHEDULE.round_trip_bps("maker", "taker") == 7
    assert SCHEDULE.round_trip_bps("taker", "maker") == 7
    assert SCHEDULE.round_trip_bps("taker", "taker") == 10


def test_negative_bps_rejected() -> None:
    with pytest.raises(ValueError, match="bps"):
        FeeSchedule(maker_bps=-1, taker_bps=5)
