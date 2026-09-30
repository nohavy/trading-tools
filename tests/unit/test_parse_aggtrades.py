"""Tests for Binance aggTrades CSV parsing to the canonical TradeTick schema."""

import polars as pl
import pytest

from tradingv2.config import Market
from tradingv2.data.convert import DataParseError, parse_aggtrades_csv

SPOT_ROW_8 = b"0,0.20000000,50.00000000,0,0,1735689600010866,False,True\n"
UM_ROW_7 = b"26129,0.01633102,4.70443515,27781,27781,1498793709153,true\n"
SPOT_HEADER = (
    b"agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,"
    b"is_buyer_maker,is_best_match\n"
)

CANONICAL_NAMES = ["ts_ns", "price", "qty", "agg_id", "buyer_is_maker"]


def test_parse_spot_8_columns() -> None:
    df = parse_aggtrades_csv(SPOT_ROW_8, Market.SPOT, file="spot.csv")
    assert df.columns == CANONICAL_NAMES
    row = df.row(0, named=True)
    assert row["ts_ns"] == 1735689600010866 * 1_000
    assert row["price"] == pytest.approx(0.2)
    assert row["qty"] == pytest.approx(50.0)
    assert row["agg_id"] == 0
    assert row["buyer_is_maker"] is False


def test_parse_um_7_columns() -> None:
    df = parse_aggtrades_csv(UM_ROW_7, Market.UM, file="um.csv")
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["ts_ns"] == 1498793709153 * 1_000_000
    assert row["buyer_is_maker"] is True


def test_parse_spot_with_header() -> None:
    df = parse_aggtrades_csv(SPOT_HEADER + SPOT_ROW_8, Market.SPOT, file="spot.csv")
    assert df.height == 1
    assert df.row(0, named=True)["price"] == pytest.approx(0.2)


def test_boolean_case_insensitive() -> None:
    rows = (
        b"1,0.2,1.0,1,1,1735689600010866,true,True\n"
        b"2,0.2,1.0,2,2,1735689600010867,False,false\n"
    )
    df = parse_aggtrades_csv(rows, Market.SPOT, file="spot.csv")
    assert df["buyer_is_maker"].to_list() == [True, False]


def test_column_count_validated_per_market() -> None:
    with pytest.raises(DataParseError) as exc:
        parse_aggtrades_csv(UM_ROW_7, Market.SPOT, file="spot.csv")
    assert "spot.csv:1" in str(exc.value)


def test_malformed_number_reports_file_and_line() -> None:
    bad = b"1,oops,1.0,1,1,1735689600010866,False,True\n"
    with pytest.raises(DataParseError) as exc:
        parse_aggtrades_csv(SPOT_ROW_8 + bad, Market.SPOT, file="spot.csv")
    assert "spot.csv:2" in str(exc.value)


def test_canonical_dtypes() -> None:
    df = parse_aggtrades_csv(SPOT_ROW_8, Market.SPOT, file="spot.csv")
    assert df.schema["ts_ns"] == pl.Int64
    assert df.schema["price"] == pl.Float64
    assert df.schema["qty"] == pl.Float64
    assert df.schema["agg_id"] == pl.UInt64
    assert df.schema["buyer_is_maker"] == pl.Boolean


def test_empty_file_raises() -> None:
    with pytest.raises(DataParseError):
        parse_aggtrades_csv(b"", Market.SPOT, file="empty.csv")


def test_large_file_is_fast() -> None:
    import time

    n = 200_000
    lines = [
        f"{i},0.01633102,4.70443515,1,1,{1498793709153 + i},true".encode()
        for i in range(n)
    ]
    payload = b"\n".join(lines) + b"\n"
    start = time.perf_counter()
    df = parse_aggtrades_csv(payload, Market.UM, file="big.csv")
    elapsed = time.perf_counter() - start
    assert df.height == n
    assert elapsed < 5.0, f"parsing {n} rows took {elapsed:.1f}s"
