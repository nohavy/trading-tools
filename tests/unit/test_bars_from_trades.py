"""Tests for building canonical bars from trade ticks."""

import polars as pl
import pytest

from tradingv2.data.resample import bars_from_trades

SECOND = 1_000_000_000
START = 1_790_294_400_000_000_000

BAR_NAMES = [
    "ts_open_ns", "open", "high", "low", "close", "volume", "quote_volume",
    "n_trades", "taker_buy_volume", "taker_buy_quote_volume",
]


def make_trades(rows: list[tuple[int, float, float, bool]]) -> pl.DataFrame:
    """Each row: (ts_ns, price, qty, buyer_is_maker)."""
    return pl.DataFrame(
        {
            "ts_ns": [r[0] for r in rows],
            "price": [r[1] for r in rows],
            "qty": [r[2] for r in rows],
            "buyer_is_maker": [r[3] for r in rows],
        },
        schema={
            "ts_ns": pl.Int64,
            "price": pl.Float64,
            "qty": pl.Float64,
            "buyer_is_maker": pl.Boolean,
        },
    )


def test_bars_from_trades_golden() -> None:
    trades = make_trades(
        [
            (START + 0 * SECOND, 100.0, 1.0, True),   # taker sells
            (START + 0 * SECOND + 100_000_000, 100.5, 2.0, False),  # taker buys
            (START + 0 * SECOND + 900_000_000, 100.2, 1.5, False),
            (START + 1 * SECOND, 99.0, 0.5, False),
            (START + 1 * SECOND + 200_000_000, 101.0, 3.0, True),
        ]
    )
    bars = bars_from_trades(trades, SECOND)
    assert bars.columns == BAR_NAMES
    assert bars.height == 2

    first = bars.row(0, named=True)
    assert first["ts_open_ns"] == START
    assert first["open"] == pytest.approx(100.0)
    assert first["high"] == pytest.approx(100.5)
    assert first["low"] == pytest.approx(100.0)
    assert first["close"] == pytest.approx(100.2)
    assert first["volume"] == pytest.approx(4.5)
    assert first["quote_volume"] == pytest.approx(100.0 * 1.0 + 100.5 * 2.0 + 100.2 * 1.5)
    assert first["n_trades"] == 3
    # taker buys = trades where the buyer was NOT the maker
    assert first["taker_buy_volume"] == pytest.approx(3.5)
    assert first["taker_buy_quote_volume"] == pytest.approx(100.5 * 2.0 + 100.2 * 1.5)

    second = bars.row(1, named=True)
    assert second["ts_open_ns"] == START + SECOND
    assert second["open"] == pytest.approx(99.0)
    assert second["high"] == pytest.approx(101.0)
    assert second["low"] == pytest.approx(99.0)
    assert second["close"] == pytest.approx(101.0)
    assert second["volume"] == pytest.approx(3.5)
    assert second["n_trades"] == 2
    assert second["taker_buy_volume"] == pytest.approx(0.5)


def test_silent_second_is_absent() -> None:
    trades = make_trades(
        [
            (START, 100.0, 1.0, False),
            (START + 2 * SECOND, 101.0, 1.0, False),  # second 1 has no trades
        ]
    )
    bars = bars_from_trades(trades, SECOND)
    assert bars["ts_open_ns"].to_list() == [START, START + 2 * SECOND]


def test_empty_trades_give_empty_canonical_frame() -> None:
    bars = bars_from_trades(make_trades([]), SECOND)
    assert bars.columns == BAR_NAMES
    assert bars.height == 0


def test_dtypes_match_bar_schema() -> None:
    trades = make_trades([(START, 100.0, 1.0, False)])
    bars = bars_from_trades(trades, SECOND)
    assert bars.schema["ts_open_ns"] == pl.Int64
    assert bars.schema["n_trades"] == pl.UInt32
    assert bars.schema["volume"] == pl.Float64
