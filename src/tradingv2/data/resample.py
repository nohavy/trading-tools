"""Bar resampling: aggregate canonical bars to a coarser target interval."""

import polars as pl

from tradingv2.data.convert import BAR_SCHEMA

CANONICAL_COLUMNS = [
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


def bars_from_trades(trades: pl.DataFrame, interval_ns: int) -> pl.DataFrame:
    """Build canonical bars from trade ticks aggregated into interval_ns buckets.

    Buckets without any trade are absent (a silent second is a real gap).
    taker_buy_volume counts trades where the buyer was the taker
    (buyer_is_maker == False), matching the Binance klines semantics.
    """
    if trades.is_empty():
        return pl.DataFrame(schema=BAR_SCHEMA)
    bucketed = trades.with_columns(
        ((pl.col("ts_ns") // interval_ns) * interval_ns).alias("_bucket")
    )
    quote_volume = (pl.col("price") * pl.col("qty")).sum()
    aggregated = bucketed.group_by("_bucket", maintain_order=True).agg(
        pl.col("price").first().alias("open"),
        pl.col("price").max().alias("high"),
        pl.col("price").min().alias("low"),
        pl.col("price").last().alias("close"),
        pl.col("qty").sum().alias("volume"),
        quote_volume.alias("quote_volume"),
        pl.len().alias("n_trades"),
        pl.col("qty").filter(~pl.col("buyer_is_maker")).sum().alias("taker_buy_volume"),
        (pl.col("price") * pl.col("qty"))
        .filter(~pl.col("buyer_is_maker"))
        .sum()
        .alias("taker_buy_quote_volume"),
    )
    return aggregated.select(
        pl.col("_bucket").alias("ts_open_ns"),
        pl.col("open"),
        pl.col("high"),
        pl.col("low"),
        pl.col("close"),
        pl.col("volume"),
        pl.col("quote_volume"),
        pl.col("n_trades").cast(pl.UInt32),
        pl.col("taker_buy_volume"),
        pl.col("taker_buy_quote_volume"),
    ).sort("ts_open_ns")


def _source_interval_ns(ts: pl.Series) -> int:
    diffs = ts.diff().drop_nulls()
    positive = diffs.filter(diffs > 0)
    if positive.is_empty():
        raise ValueError("cannot infer source interval from a single bar")
    return int(positive.min())  # type: ignore[arg-type]


def resample_bars(df: pl.DataFrame, target_ns: int) -> pl.DataFrame:
    """Aggregate canonical bars into target_ns buckets.

    Buckets that are not completely covered (partial first or last bucket,
    e.g. data starting mid-bucket or an unfinished final bucket) are dropped.
    """
    source_ns = _source_interval_ns(df["ts_open_ns"])
    bucketed = df.with_columns(((pl.col("ts_open_ns") // target_ns) * target_ns).alias("_bucket"))
    source_ts = pl.col("ts_open_ns")
    aggregated = bucketed.group_by("_bucket", maintain_order=True).agg(
        source_ts.first().alias("_first_ts"),
        source_ts.last().alias("_last_ts"),
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("volume").sum(),
        pl.col("quote_volume").sum(),
        pl.col("n_trades").sum(),
        pl.col("taker_buy_volume").sum(),
        pl.col("taker_buy_quote_volume").sum(),
    )
    complete = aggregated.filter(
        (pl.col("_first_ts") == pl.col("_bucket"))
        & (pl.col("_last_ts") + source_ns == pl.col("_bucket") + target_ns)
    )
    return complete.select(
        pl.col("_bucket").alias("ts_open_ns"),
        pl.col("open"),
        pl.col("high"),
        pl.col("low"),
        pl.col("close"),
        pl.col("volume"),
        pl.col("quote_volume"),
        pl.col("n_trades").cast(pl.UInt32),
        pl.col("taker_buy_volume"),
        pl.col("taker_buy_quote_volume"),
    )
