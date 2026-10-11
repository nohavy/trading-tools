"""On-chain flow ingestion: deterministic parquet + checksum manifest (012)."""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class IngestResult:
    """Ingestion evidence: artifact paths + checksum."""

    parquet: Path
    manifest: Path
    sha256: str
    rows: int


def bigquery_runner(dataset: str) -> Callable[[str], pl.DataFrame]:
    """Real runner: free public-data query -> Arrow -> polars (no pandas)."""
    from google.cloud import bigquery

    assert dataset == "crypto_ethereum"
    client = bigquery.Client()

    def run(sql: str) -> pl.DataFrame:
        result = client.query(sql).result()
        arrow = result.to_arrow(create_bqstorage_client=False)
        return pl.from_arrow(arrow)

    return run


def ingest_daily_flows(
    *,
    addresses: tuple[str, ...],
    start: str,
    end: str,
    data_dir: Path,
    runner: Callable[[str], pl.DataFrame],
    dataset: str = "crypto_ethereum",
) -> IngestResult:
    """Ingest the daily ETH flows of a frozen address set into Parquet+manifest."""
    from tradingv2.data.onchain.sqls import eth_flow_daily_sql

    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError("window must satisfy start < end")
    data_dir.mkdir(parents=True, exist_ok=True)
    sql = eth_flow_daily_sql(addresses=addresses, start=start, end=end)["eth_flows"]
    df = runner(sql)
    if df.height == 0:
        raise ValueError("empty ingestion result — check the window and address set")
    parquet = data_dir / f"eth_flows_{start}_{end}.parquet"
    df.sort("day").write_parquet(parquet, compression="zstd")
    blob = parquet.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    manifest = {
        "parquet": parquet.name,
        "rows": df.height,
        "sha256": digest,
        "dataset": dataset,
        "addresses": sorted(addresses),
        "start": start,
        "end": end,
    }
    manifest_path = data_dir / f"eth_flows_{start}_{end}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    os.replace(manifest_path, manifest_path)
    return IngestResult(
        parquet=parquet, manifest=manifest_path, sha256=digest, rows=df.height
    )
