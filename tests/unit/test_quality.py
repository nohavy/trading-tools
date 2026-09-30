"""Tests for data quality checks on canonical bar dataframes."""

import polars as pl

from tradingv2.data.quality import AnomalyKind, check_bars

SECOND_NS = 1_000_000_000
DAY_NS = 86_400 * SECOND_NS


def make_bars(ts_list: list[int], closes: list[float] | None = None) -> pl.DataFrame:
    n = len(ts_list)
    close = closes if closes is not None else [100.0] * n
    return pl.DataFrame(
        {
            "ts_open_ns": ts_list,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1.0] * n,
            "quote_volume": [100.0] * n,
            "n_trades": [1] * n,
            "taker_buy_volume": [0.5] * n,
            "taker_buy_quote_volume": [50.0] * n,
        },
        schema={
            "ts_open_ns": pl.Int64,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "quote_volume": pl.Float64,
            "n_trades": pl.UInt32,
            "taker_buy_volume": pl.Float64,
            "taker_buy_quote_volume": pl.Float64,
        },
    )


def ts_range(start_ns: int, count: int) -> list[int]:
    return [start_ns + i * SECOND_NS for i in range(count)]


def test_clean_dataset_has_no_anomalies() -> None:
    df = make_bars(ts_range(DAY_NS, 60))
    assert check_bars(df, SECOND_NS) == []


def test_gap_detected() -> None:
    timestamps = ts_range(DAY_NS, 10)
    timestamps.remove(DAY_NS + 4 * SECOND_NS)
    anomalies = check_bars(make_bars(timestamps), SECOND_NS)
    kinds = [a.kind for a in anomalies]
    assert kinds == [AnomalyKind.GAP]
    assert anomalies[0].detail == "1 missing bars"


def test_duplicate_timestamp_detected() -> None:
    timestamps = ts_range(DAY_NS, 10)
    timestamps.insert(4, DAY_NS + 4 * SECOND_NS)
    anomalies = check_bars(make_bars(timestamps), SECOND_NS)
    assert [a.kind for a in anomalies] == [AnomalyKind.DUPLICATE_TS]
    assert anomalies[0].ts_ns == DAY_NS + 4 * SECOND_NS


def test_non_monotonic_detected() -> None:
    timestamps = ts_range(DAY_NS, 10)
    timestamps[5], timestamps[6] = timestamps[6], timestamps[5]
    anomalies = check_bars(make_bars(timestamps), SECOND_NS)
    # swapping two timestamps breaks monotonicity and also creates two gaps
    assert [a.kind for a in anomalies] == [
        AnomalyKind.GAP,
        AnomalyKind.NON_MONOTONIC,
        AnomalyKind.GAP,
    ]


def test_high_below_low_detected() -> None:
    df = make_bars(ts_range(DAY_NS, 10))
    df = df.with_columns(
        pl.when(pl.arange(0, df.height) == 3)
        .then(pl.lit(90.0))
        .otherwise(pl.col("high"))
        .alias("high")
    )
    anomalies = check_bars(df, SECOND_NS)
    assert [a.kind for a in anomalies] == [AnomalyKind.HIGH_LT_LOW]
    assert anomalies[0].ts_ns == DAY_NS + 3 * SECOND_NS


def test_price_outlier_detected() -> None:
    closes = [100.0] * 10
    closes[7] = 100_000.0
    anomalies = check_bars(make_bars(ts_range(DAY_NS, 10), closes), SECOND_NS)
    assert [a.kind for a in anomalies] == [AnomalyKind.PRICE_OUTLIER]
    assert anomalies[0].ts_ns == DAY_NS + 7 * SECOND_NS


def test_multiple_anomalies_all_reported() -> None:
    df = make_bars(ts_range(DAY_NS, 10))
    df = df.with_columns(
        pl.when(pl.arange(0, df.height) == 3)
        .then(pl.lit(90.0))
        .otherwise(pl.col("high"))
        .alias("high")
    )
    anomalies = check_bars(df, SECOND_NS)
    kinds = {a.kind for a in anomalies}
    assert AnomalyKind.HIGH_LT_LOW in kinds
