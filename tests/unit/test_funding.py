"""Tests for funding rate CSV parsing to the canonical Funding schema (golden fixture)."""

import polars as pl
import pytest

from tradingv2.data.convert import DataParseError, parse_funding_csv

GOLDEN = "tests/fixtures/BTCUSDT-fundingRate-2026-08.csv"

FUNDING_HEADER = b"calc_time,funding_interval_hours,last_funding_rate\n"

CANONICAL_NAMES = ["ts_ns", "interval_hours", "rate"]


def test_parse_real_monthly_golden() -> None:
    data = open(GOLDEN, "rb").read()
    df = parse_funding_csv(data, file=GOLDEN)
    assert df.height == 93
    row = df.row(0, named=True)
    assert row["ts_ns"] == 1785542400001 * 1_000_000
    assert row["interval_hours"] == 8
    assert row["rate"] == pytest.approx(0.00004123)


def test_canonical_dtypes() -> None:
    df = parse_funding_csv(open(GOLDEN, "rb").read(), file=GOLDEN)
    assert df.schema["ts_ns"] == pl.Int64
    assert df.schema["interval_hours"] == pl.UInt32
    assert df.schema["rate"] == pl.Float64
    assert df.columns == CANONICAL_NAMES


def test_timestamps_strictly_increasing() -> None:
    df = parse_funding_csv(open(GOLDEN, "rb").read(), file=GOLDEN)
    diff = df["ts_ns"].diff().drop_nulls()
    assert (diff > 0).all()


def test_last_row_of_golden() -> None:
    df = parse_funding_csv(open(GOLDEN, "rb").read(), file=GOLDEN)
    row = df.row(df.height - 1, named=True)
    assert row["ts_ns"] == 1788192000001 * 1_000_000
    assert row["interval_hours"] == 8
    assert row["rate"] == pytest.approx(0.0001)


def test_malformed_line_reports_file_and_line() -> None:
    bad = b"1785542400001,8,not_a_rate\n"
    with pytest.raises(DataParseError) as exc:
        parse_funding_csv(FUNDING_HEADER + bad, file="funding.csv")
    assert "funding.csv:2" in str(exc.value)


def test_wrong_column_count_raises() -> None:
    bad = b"1785542400001,8\n"
    with pytest.raises(DataParseError) as exc:
        parse_funding_csv(FUNDING_HEADER + bad, file="funding.csv")
    assert "funding.csv:2" in str(exc.value)


def test_empty_file_raises() -> None:
    with pytest.raises(DataParseError):
        parse_funding_csv(b"", file="empty.csv")
