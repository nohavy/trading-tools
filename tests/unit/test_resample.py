"""Tests for bar resampling: 1s bars to 5s/1m with independent expected values."""

import polars as pl
import pytest

from tradingv2.data.resample import resample_bars

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
START = 1_790_294_400_000_000_000  # 2026-09-25T00:00:00Z, minute-aligned


def build_1s_bars(start_ts: int, n: int) -> pl.DataFrame:
    opens = [100.0 + i * 0.1 for i in range(n)]
    rows = {
        "ts_open_ns": [start_ts + i * SECOND for i in range(n)],
        "open": opens,
        "high": [o + 0.05 for o in opens],
        "low": [o - 0.05 for o in opens],
        "close": [o + 0.02 for o in opens],
        "volume": [float(i + 1) for i in range(n)],
        "quote_volume": [float((i + 1) * 100) for i in range(n)],
        "n_trades": [i + 1 for i in range(n)],
        "taker_buy_volume": [(i + 1) * 0.3 for i in range(n)],
        "taker_buy_quote_volume": [(i + 1) * 30.0 for i in range(n)],
    }
    return pl.DataFrame(rows, schema_overrides={"n_trades": pl.UInt32})


def expected_minute_bucket(b: int) -> dict[str, float]:
    idx = range(60 * b, 60 * b + 60)
    return {
        "open": 100.0 + 60 * b * 0.1,
        "high": max(100.0 + i * 0.1 + 0.05 for i in idx),
        "low": min(100.0 + i * 0.1 - 0.05 for i in idx),
        "close": 100.0 + (60 * b + 59) * 0.1 + 0.02,
        "volume": float(sum(i + 1 for i in idx)),
        "quote_volume": float(sum((i + 1) * 100 for i in idx)),
        "n_trades": sum(i + 1 for i in idx),
        "taker_buy_volume": float(sum((i + 1) * 0.3 for i in idx)),
        "taker_buy_quote_volume": float(sum((i + 1) * 30.0 for i in idx)),
    }


def test_resample_1s_to_1m_exact() -> None:
    out = resample_bars(build_1s_bars(START, 180), MINUTE)
    assert out.height == 3
    for b in range(3):
        row = out.row(b, named=True)
        expected = expected_minute_bucket(b)
        assert row["ts_open_ns"] == START + b * MINUTE
        for key, value in expected.items():
            assert row[key] == pytest.approx(value, rel=1e-9), f"bucket {b} field {key}"


def test_resample_1s_to_5s() -> None:
    out = resample_bars(build_1s_bars(START, 12), 5 * SECOND)
    assert out.height == 2
    first = out.row(0, named=True)
    assert first["ts_open_ns"] == START
    assert first["volume"] == pytest.approx(15.0)  # 1+2+3+4+5
    assert first["n_trades"] == 15


def test_incomplete_last_bucket_dropped() -> None:
    out = resample_bars(build_1s_bars(START, 185), MINUTE)
    assert out.height == 3


def test_incomplete_first_bucket_dropped() -> None:
    out = resample_bars(build_1s_bars(START + 5 * SECOND, 180), MINUTE)
    assert out.height == 2
    assert out["ts_open_ns"][0] == START + MINUTE


def test_output_keeps_canonical_schema() -> None:
    out = resample_bars(build_1s_bars(START, 180), MINUTE)
    assert out.columns == [
        "ts_open_ns", "open", "high", "low", "close", "volume", "quote_volume",
        "n_trades", "taker_buy_volume", "taker_buy_quote_volume",
    ]
    assert out.schema["ts_open_ns"] == pl.Int64
    assert out.schema["n_trades"] == pl.UInt32
