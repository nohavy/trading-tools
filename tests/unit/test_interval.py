"""Tests for interval string parsing to nanoseconds."""

import pytest

from tradingv2.data.convert import parse_interval_ns


def test_seconds() -> None:
    assert parse_interval_ns("1s") == 1_000_000_000
    assert parse_interval_ns("5s") == 5_000_000_000


def test_minutes() -> None:
    assert parse_interval_ns("1m") == 60_000_000_000
    assert parse_interval_ns("15m") == 15 * 60_000_000_000


def test_hours() -> None:
    assert parse_interval_ns("1h") == 3_600_000_000_000


def test_unknown_unit_rejected() -> None:
    with pytest.raises(ValueError, match="unit"):
        parse_interval_ns("10x")


def test_missing_unit_rejected() -> None:
    with pytest.raises(ValueError, match="unit"):
        parse_interval_ns("10")


def test_zero_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        parse_interval_ns("0s")
