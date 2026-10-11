"""Tests for the on-chain flow ingestion (012): fake runner, parquet + checksum."""

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from tradingv2.data.onchain.ingest import ingest_daily_flows


def _fake_runner(sql: str) -> pl.DataFrame:
    assert "bigquery-public-data.crypto_ethereum.transactions" in sql
    assert "'0xaaa'" in sql
    assert "2021-01-01" in sql and "2021-01-03" in sql
    return pl.DataFrame(
        {
            "day": ["2021-01-01", "2021-01-02"],
            "deposit_eth": [100.0, 120.0],
            "withdraw_eth": [40.0, 55.0],
            "deposit_clients": [10, 9],
            "withdraw_clients": [7, 8],
        }
    )


def test_ingest_writes_zstd_parquet_and_manifest_checksum(tmp_path: Path) -> None:
    result = ingest_daily_flows(
        addresses=("0xaaa",),
        start="2021-01-01",
        end="2021-01-03",
        data_dir=tmp_path,
        runner=_fake_runner,
        dataset="crypto_ethereum",
    )
    df = pl.read_parquet(result.parquet)
    assert df.height == 2
    assert result.parquet.name == "eth_flows_2021-01-01_2021-01-03.parquet"
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["rows"] == 2
    assert manifest["sha256"] == hashlib.sha256(result.parquet.read_bytes()).hexdigest()
    assert manifest["addresses"] == ["0xaaa"]
    # deterministic: a second ingest writes identical bytes
    result2 = ingest_daily_flows(
        addresses=("0xaaa",),
        start="2021-01-01",
        end="2021-01-03",
        data_dir=tmp_path,
        runner=_fake_runner,
        dataset="crypto_ethereum",
    )
    assert result2.sha256 == result.sha256


def test_ingest_rejects_an_empty_result(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        ingest_daily_flows(
            addresses=("0xaaa",),
            start="2021-01-05",
            end="2021-01-06",
            data_dir=tmp_path,
            runner=lambda sql: pl.DataFrame(),
            dataset="crypto_ethereum",
        )
