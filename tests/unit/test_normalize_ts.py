"""Tests for timestamp normalization to UTC nanoseconds."""

import pytest

from tradingv2.data.convert import TimestampScaleError, normalize_ts


def test_milliseconds_converted_to_ns() -> None:
    # futures kline open_time (ms)
    assert normalize_ts(1499040000000) == 1499040000000000000


def test_microseconds_converted_to_ns() -> None:
    # spot kline open_time since 2025-01-01 (µs)
    assert normalize_ts(1735689600000000) == 1735689600000000000


def test_nanoseconds_unchanged() -> None:
    assert normalize_ts(1735689600000000000) == 1735689600000000000


def test_too_small_value_raises() -> None:
    with pytest.raises(TimestampScaleError):
        normalize_ts(12345)


def test_negative_value_raises() -> None:
    with pytest.raises(TimestampScaleError):
        normalize_ts(-1)
