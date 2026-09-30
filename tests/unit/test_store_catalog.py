"""Tests for Parquet storage (zstd) and the download catalogue."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from tradingv2.data.convert import parse_klines_csv
from tradingv2.data.store import Catalog, CatalogEntry, read_parquet, replace_entry, write_parquet

SPOT_HEADER_ROW = (
    b"open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    b"taker_buy_volume,taker_buy_quote_volume,ignore\n"
)
SPOT_DATA_ROW = (
    b"1735689600000000,4.1507,4.1587,4.1506,4.1554,539.23,1735689599999999,"
    b"2240.398609,13,401.82,1669.981213,0\n"
)


def _sample_frame() -> pl.DataFrame:
    return parse_klines_csv(SPOT_HEADER_ROW + SPOT_DATA_ROW, file="spot.csv")


def _entry(path: str) -> CatalogEntry:
    return CatalogEntry(
        path=path,
        kind="klines",
        market="spot",
        symbol="BTCUSDT",
        interval="1s",
        source_url="https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.zip",
        sha256="ab" * 32,
        n_rows=86_400,
        ts_min_ns=1735689600000000000,
        ts_max_ns=1735689600863900000000,
        converted_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC).isoformat(),
    )


def test_write_parquet_is_zstd_roundtrip(tmp_path: Path) -> None:
    df = _sample_frame()
    path = tmp_path / "nested" / "bars.parquet"
    write_parquet(df, path)
    back = read_parquet(path)
    assert back.equals(df)
    metadata = pq.ParquetFile(path).metadata
    assert metadata.row_group(0).column(0).compression == "ZSTD"


def test_catalog_upsert_is_idempotent(tmp_path: Path) -> None:
    catalog = Catalog(root=tmp_path)
    catalog.upsert(_entry("parquet/spot/klines/BTCUSDT/1s/a.parquet"))
    catalog.upsert(_entry("parquet/spot/klines/BTCUSDT/1s/a.parquet"))
    assert len(catalog.list()) == 1


def test_catalog_persists_across_loads(tmp_path: Path) -> None:
    first = Catalog(root=tmp_path)
    first.upsert(_entry("parquet/a.parquet"))
    second = Catalog.load(tmp_path)
    entries = second.list()
    assert len(entries) == 1
    assert entries[0] == _entry("parquet/a.parquet")


def test_catalog_holds_multiple_distinct_entries(tmp_path: Path) -> None:
    catalog = Catalog(root=tmp_path)
    catalog.upsert(_entry("parquet/a.parquet"))
    catalog.upsert(_entry("parquet/b.parquet"))
    catalog.upsert(replace_entry(_entry("parquet/a.parquet"), n_rows=1))
    assert len(catalog.list()) == 2
    by_path = {e.path: e for e in catalog.list()}
    assert by_path["parquet/a.parquet"].n_rows == 1


def test_upsert_replaces_entry_on_update(tmp_path: Path) -> None:
    catalog = Catalog(root=tmp_path)
    updated = replace_entry(_entry("parquet/a.parquet"), n_rows=1)
    catalog.upsert(_entry("parquet/a.parquet"))
    catalog.upsert(updated)
    entries = catalog.list()
    assert len(entries) == 1
    assert entries[0].n_rows == 1
