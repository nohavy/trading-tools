"""Tests for Binance klines CSV parsing to the canonical Bar schema."""

import polars as pl
import pytest

from tradingv2.data.convert import DataParseError, parse_klines_csv

SPOT_HEADER_ROW = (
    b"open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    b"taker_buy_volume,taker_buy_quote_volume,ignore\n"
)
SPOT_DATA_ROW = (
    b"1735689600000000,4.1507,4.1587,4.1506,4.1554,539.23,1735689599999999,"
    b"2240.398609,13,401.82,1669.981213,0\n"
)
UM_DATA_ROW = (
    b"1499040000000,0.01634790,0.8,0.015758,0.015771,148976.11427815,1499644799999,"
    b"2434.19055334,308,1756.87402397,28.46694368,17928899.62484339\n"
)

CANONICAL_NAMES = [
    "ts_open_ns",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "n_trades",
    "taker_buy_volume",
    "taker_buy_quote_volume",
]


def test_parse_spot_with_header() -> None:
    df = parse_klines_csv(SPOT_HEADER_ROW + SPOT_DATA_ROW, file="spot.csv")
    assert df.columns == CANONICAL_NAMES
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["ts_open_ns"] == 1735689600000000 * 1_000
    assert row["open"] == pytest.approx(4.1507)
    assert row["high"] == pytest.approx(4.1587)
    assert row["low"] == pytest.approx(4.1506)
    assert row["close"] == pytest.approx(4.1554)
    assert row["volume"] == pytest.approx(539.23)
    assert row["quote_volume"] == pytest.approx(2240.398609)
    assert row["n_trades"] == 13
    assert row["taker_buy_volume"] == pytest.approx(401.82)
    assert row["taker_buy_quote_volume"] == pytest.approx(1669.981213)


def test_parse_um_without_header_normalizes_ms() -> None:
    df = parse_klines_csv(UM_DATA_ROW, file="um.csv")
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["ts_open_ns"] == 1499040000000 * 1_000_000
    assert row["n_trades"] == 308


def test_parse_preserves_row_order() -> None:
    second = SPOT_DATA_ROW.replace(b"1735689600000000", b"1735689601000000")
    df = parse_klines_csv(SPOT_HEADER_ROW + SPOT_DATA_ROW + second, file="spot.csv")
    assert df.height == 2
    assert df["ts_open_ns"][0] < df["ts_open_ns"][1]


def test_canonical_dtypes() -> None:
    df = parse_klines_csv(SPOT_HEADER_ROW + SPOT_DATA_ROW, file="spot.csv")
    assert df.schema["ts_open_ns"] == pl.Int64
    assert df.schema["n_trades"] == pl.UInt32
    for name in ("open", "high", "low", "close", "volume", "quote_volume"):
        assert df.schema[name] == pl.Float64


def test_malformed_field_count_reports_file_and_line() -> None:
    bad = b"1735689600000000,4.1507,4.1587,4.1506,4.1554,539.23\n"
    with pytest.raises(DataParseError) as exc:
        parse_klines_csv(SPOT_HEADER_ROW + SPOT_DATA_ROW + bad, file="spot.csv")
    message = str(exc.value)
    assert "spot.csv" in message
    assert ":3" in message


def test_bad_number_reports_line() -> None:
    bad = SPOT_DATA_ROW.replace(b"4.1507", b"oops", 1)
    with pytest.raises(DataParseError) as exc:
        parse_klines_csv(SPOT_HEADER_ROW + SPOT_DATA_ROW + bad, file="spot.csv")
    assert ":3" in str(exc.value)


def test_empty_file_raises() -> None:
    with pytest.raises(DataParseError):
        parse_klines_csv(b"", file="empty.csv")
