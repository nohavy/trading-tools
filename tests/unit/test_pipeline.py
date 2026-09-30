"""Tests for the download pipeline: download -> unzip -> convert -> parquet -> catalogue."""

import hashlib
import io
import zipfile
from datetime import date
from pathlib import Path

import httpx
import polars as pl

from tradingv2.config import DataConfig, DataKind, Market
from tradingv2.data.pipeline import PipelineSummary, run_download_pipeline
from tradingv2.data.store import Catalog

SPOT_HEADER_ROW = (
    b"open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    b"taker_buy_volume,taker_buy_quote_volume,ignore\n"
)
SPOT_DATA_ROWS = (
    SPOT_HEADER_ROW
    + b"1735689600000000,4.1507,4.1587,4.1506,4.1554,539.23,1735689599999999,2240.398609,13,401.82,1669.981213,0\n"  # noqa: E501
    + b"1735689601000000,4.1554,4.1560,4.1550,4.1558,100.00,1735689599999999,415.54,2,50.00,207.77,0\n"  # noqa: E501
)


def sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_bytes(csv: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BTCUSDT-1s.csv", csv)
    return buffer.getvalue()


def klines_client(csv: bytes, requests: list[httpx.Request]) -> httpx.Client:
    payload = zip_bytes(csv)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, text=sha_of(payload) + "  BTCUSDT-1s-2026-08.zip\n")
        return httpx.Response(200, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


SPOT_KLINES = DataConfig(
    market=Market.SPOT,
    kind=DataKind.KLINES,
    symbol="BTCUSDT",
    interval="1s",
    start=date(2026, 8, 1),
    end=date(2026, 8, 31),
)


def test_pipeline_downloads_converts_registers(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    client = klines_client(SPOT_DATA_ROWS, requests)
    summary = run_download_pipeline(SPOT_KLINES, tmp_path, today=date(2026, 9, 30), client=client)
    assert isinstance(summary, PipelineSummary)
    assert summary.downloaded == 1
    assert summary.converted == 1
    parquet = tmp_path / "parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet"
    assert parquet.is_file()
    df = pl.read_parquet(parquet)
    assert df.height == 2
    assert df["ts_open_ns"][0] == 1735689600000000 * 1_000
    catalog = Catalog.load(tmp_path)
    entry = catalog.list()[0]
    assert entry.n_rows == 2
    assert entry.ts_min_ns == 1735689600000000000
    assert entry.ts_max_ns == 1735689601000000000
    assert entry.sha256 == sha_of(zip_bytes(SPOT_DATA_ROWS))
    assert (entry.market, entry.kind, entry.symbol, entry.interval) == (
        "spot", "klines", "BTCUSDT", "1s"
    )
    assert entry.source_url.endswith("BTCUSDT-1s-2026-08.zip")


def test_pipeline_second_run_skips_everything(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    client = klines_client(SPOT_DATA_ROWS, requests)
    run_download_pipeline(SPOT_KLINES, tmp_path, today=date(2026, 9, 30), client=client)
    before = len(requests)
    summary = run_download_pipeline(SPOT_KLINES, tmp_path, today=date(2026, 9, 30), client=client)
    assert summary.downloaded == 0
    assert summary.converted == 0
    assert summary.skipped == 1
    body_requests = [r for r in requests if not str(r.url).endswith(".CHECKSUM")]
    # the skip path re-verifies the checksum (one request) but never re-fetches the body
    assert len(body_requests) * 2 == before  # run 1: one body + one checksum
    assert len(Catalog.load(tmp_path).list()) == 1


def test_pipeline_missing_checksum_counts_failed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"whatever")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = run_download_pipeline(SPOT_KLINES, tmp_path, today=date(2026, 9, 30), client=client)
    assert summary.failed == 1
    assert summary.converted == 0


FUNDING_CSV = (
    b"calc_time,funding_interval_hours,last_funding_rate\n"
    b"1785542400001,8,0.00004123\n"
    b"1785571200000,8,0.00003163\n"
)


def test_pipeline_funding(tmp_path: Path) -> None:
    payload = zip_bytes(FUNDING_CSV)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(".CHECKSUM"):
            return httpx.Response(200, text=sha_of(payload) + "  BTCUSDT-fundingRate-2026-08.zip\n")
        return httpx.Response(200, content=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    config = DataConfig(
        market=Market.UM,
        kind=DataKind.FUNDING_RATE,
        symbol="BTCUSDT",
        interval=None,
        start=date(2026, 8, 1),
        end=date(2026, 8, 31),
    )
    summary = run_download_pipeline(config, tmp_path, today=date(2026, 9, 30), client=client)
    assert summary.converted == 1
    parquet = tmp_path / "parquet/um/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-08.parquet"
    assert parquet.is_file()
    df = pl.read_parquet(parquet)
    assert df.height == 2
    assert df["ts_ns"][0] == 1785542400001 * 1_000_000
    entry = Catalog.load(tmp_path).list()[0]
    assert entry.interval is None
    assert entry.sha256 == sha_of(payload)
