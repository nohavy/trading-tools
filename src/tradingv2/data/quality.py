"""Data quality checks on canonical bar dataframes."""

from dataclasses import dataclass
from enum import StrEnum

import polars as pl

NS_PER_DAY = 86_400_000_000_000


class AnomalyKind(StrEnum):
    """Detected data quality anomaly kinds."""

    GAP = "gap"
    DUPLICATE_TS = "duplicate_ts"
    NON_MONOTONIC = "non_monotonic"
    HIGH_LT_LOW = "high_lt_low"
    PRICE_OUTLIER = "price_outlier"


@dataclass(frozen=True)
class Anomaly:
    """One detected anomaly with its timestamp and detail."""

    kind: AnomalyKind
    ts_ns: int | None
    detail: str


def _timestamp_sequence_anomalies(ts: pl.Series, interval_ns: int) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    diff = ts.diff()
    for idx in range(1, ts.len()):
        delta = diff[idx]
        if delta == 0:
            anomalies.append(Anomaly(AnomalyKind.DUPLICATE_TS, int(ts[idx]), "duplicate timestamp"))
        elif delta < 0:
            anomalies.append(
                Anomaly(AnomalyKind.NON_MONOTONIC, int(ts[idx]), "timestamps not sorted")
            )
        elif delta > interval_ns:
            missing = int(delta) // interval_ns - 1
            anomalies.append(Anomaly(AnomalyKind.GAP, int(ts[idx]), f"{missing} missing bars"))
    return anomalies


def _high_below_low_anomalies(df: pl.DataFrame) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for row in df.filter(pl.col("high") < pl.col("low")).iter_rows(named=True):
        detail = f"high {row['high']} < low {row['low']}"
        anomalies.append(Anomaly(AnomalyKind.HIGH_LT_LOW, int(row["ts_open_ns"]), detail))
    return anomalies


def _price_outlier_anomalies(df: pl.DataFrame, outlier_factor: float) -> list[Anomaly]:
    df = df.with_columns((pl.col("ts_open_ns") // NS_PER_DAY).alias("_day"))
    medians = df.group_by("_day").agg(pl.col("close").median().alias("_med_close"))
    joined = df.join(medians, on="_day", how="left")
    outliers = joined.filter(
        (pl.col("close") > pl.col("_med_close") * outlier_factor)
        | (pl.col("close") < pl.col("_med_close") / outlier_factor)
    )
    anomalies: list[Anomaly] = []
    for row in outliers.iter_rows(named=True):
        detail = f"close {row['close']} vs day median {row['_med_close']}"
        anomalies.append(Anomaly(AnomalyKind.PRICE_OUTLIER, int(row["ts_open_ns"]), detail))
    return anomalies


def check_bars(df: pl.DataFrame, interval_ns: int, outlier_factor: float = 100.0) -> list[Anomaly]:
    """Check canonical bars for gaps, duplicates, ordering, OHLC sanity and outliers."""
    anomalies = _timestamp_sequence_anomalies(df["ts_open_ns"], interval_ns)
    anomalies.extend(_high_below_low_anomalies(df))
    anomalies.extend(_price_outlier_anomalies(df, outlier_factor))
    return anomalies
