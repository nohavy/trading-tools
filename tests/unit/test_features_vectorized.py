"""Tests for vectorized indicators (lot mode)."""

import polars as pl
import pytest

from tradingv2.features.vectorized import ema, flow_imbalance, realized_vol, vwap_session, zscore

DAY_NS = 86_400_000_000_000


def undef(series: pl.Series, index: int) -> bool:
    """True when the value is NaN or null (undefined)."""
    value = series[index]
    return value is None or value != value


def test_ema_golden_span3() -> None:
    values = pl.Series([1.0, 2.0, 3.0, 4.0])
    out = ema(values, span=3)
    assert out[0] == pytest.approx(1.0)  # seeded with the first value
    assert out[1] == pytest.approx(1.5)
    assert out[2] == pytest.approx(2.25)
    assert out[3] == pytest.approx(3.125)


def test_zscore_golden_window3() -> None:
    values = pl.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = zscore(values, window=3)
    assert undef(out, 0) and undef(out, 1)
    expected = 1 / (2 / 3) ** 0.5  # (x-mean)/std over 3 consecutive values
    assert out[2] == pytest.approx(expected)
    assert out[3] == pytest.approx(expected)  # (2,3,4) has the same spread
    assert out[4] == pytest.approx(expected)


def test_zscore_constant_series_undefined() -> None:
    out = zscore(pl.Series([5.0, 5.0, 5.0, 5.0]), window=3)
    assert undef(out, 3)  # std = 0 -> undefined, never 0/0 artifacts


def test_vwap_session_resets_at_utc_midnight() -> None:
    ts = pl.Series([0, DAY_NS - 1, DAY_NS, DAY_NS + 60_000_000_000])
    price = pl.Series([100.0, 110.0, 200.0, 220.0])
    volume = pl.Series([1.0, 1.0, 1.0, 1.0])
    out = vwap_session(ts, price, volume)
    assert out[0] == pytest.approx(100.0)
    assert out[1] == pytest.approx(105.0)  # (100+110)/2 cumulative in day 1
    assert out[2] == pytest.approx(200.0)  # reset at midnight
    assert out[3] == pytest.approx(210.0)  # (200+220)/2 in day 2


def test_vwap_session_undefined_before_first_volume() -> None:
    ts = pl.Series([0, 1, 2])
    price = pl.Series([100.0, 100.0, 100.0])
    volume = pl.Series([0.0, 0.0, 5.0])
    out = vwap_session(ts, price, volume)
    assert undef(out, 0) and undef(out, 1)
    assert out[2] == pytest.approx(100.0)


def test_realized_vol_golden_window3() -> None:
    close = pl.Series([100.0, 101.0, 102.0, 100.0])
    out = realized_vol(close, window=3)
    assert undef(out, 0) and undef(out, 1) and undef(out, 2)
    r = [101 / 100 - 1, 102 / 101 - 1, 100 / 102 - 1]
    mean = sum(r) / 3
    std = (sum((x - mean) ** 2 for x in r) / 3) ** 0.5
    assert out[3] == pytest.approx(std)


def test_flow_imbalance_golden_window2() -> None:
    volume = pl.Series([10.0, 10.0, 10.0, 10.0])
    taker_buy = pl.Series([10.0, 0.0, 5.0, 2.0])
    out = flow_imbalance(volume, taker_buy, window=2)
    assert undef(out, 0)
    assert out[1] == pytest.approx(0.0)  # Σbuy=10 / Σvol=20 -> 2*0.5-1
    assert out[2] == pytest.approx(-0.5)  # 5/20
    assert out[3] == pytest.approx(-0.3)  # 7/20


def test_flow_imbalance_zero_volume_window_undefined() -> None:
    volume = pl.Series([0.0, 0.0, 0.0])
    taker_buy = pl.Series([0.0, 0.0, 0.0])
    out = flow_imbalance(volume, taker_buy, window=2)
    assert undef(out, 2)
