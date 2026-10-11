"""Download pipeline: plan -> download -> unzip -> convert -> parquet -> catalogue."""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import httpx
import polars as pl

from tradingv2.config import DataConfig, DataKind
from tradingv2.data.convert import parse_aggtrades_csv, parse_funding_csv, parse_klines_csv
from tradingv2.data.download import download_file, file_sha256
from tradingv2.data.plan import build_download_plan
from tradingv2.data.store import Catalog, CatalogEntry, write_parquet

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Raised when the pipeline cannot process a data kind or archive."""


@dataclass(frozen=True)
class PipelineSummary:
    """Counters of one pipeline run."""

    downloaded: int
    skipped: int
    converted: int
    failed: int


def read_single_member_zip(path: Path) -> bytes:
    """Extract the single CSV member of a Binance archive zip."""
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise PipelineError(f"expected a single member in {path}, got {names}")
            return archive.read(names[0])
    except BadZipFile as exc:
        raise PipelineError(f"not a valid zip archive: {path} ({exc})") from exc


def _target_relative_path(config: DataConfig, stem: str) -> str:
    parts = ["parquet", config.market.value, config.kind.value, config.symbol]
    if config.interval is not None:
        parts.append(config.interval)
    parts.append(f"{stem}.parquet")
    return "/".join(parts)


def _convert(config: DataConfig, zip_path: Path) -> pl.DataFrame:
    csv = read_single_member_zip(zip_path)
    if config.kind == DataKind.KLINES:
        return parse_klines_csv(csv)
    if config.kind == DataKind.AGGTRADES:
        return parse_aggtrades_csv(csv, config.market)
    if config.kind == DataKind.FUNDING_RATE:
        return parse_funding_csv(csv)
    raise PipelineError(f"data kind '{config.kind.value}' is not supported by the pipeline yet")


def _ts_bounds(df: pl.DataFrame, column: str) -> tuple[int, int]:
    minimum = df[column].min()
    maximum = df[column].max()
    if minimum is None or maximum is None:
        raise PipelineError("empty dataframe: no timestamps")
    # polars stubs return a wide union for min()/max(); values are Int64 here.
    return int(minimum), int(maximum)  # type: ignore[arg-type]


def run_download_pipeline(
    config: DataConfig,
    data_root: Path,
    *,
    today: date,
    client: httpx.Client | None = None,
    max_workers: int = 4,
) -> PipelineSummary:
    """Download, convert and register all archive files for a data config.

    Idempotent: files already converted with a matching source checksum are
    skipped. The HTTP client can be injected for tests.
    """
    items = build_download_plan(
        config.market, config.kind, config.symbol, config.interval, config.start, config.end, today
    )
    raw_dir = data_root / "raw" / config.market.value / config.kind.value / config.symbol
    catalog = Catalog.load(data_root)
    downloaded = skipped = converted = failed = 0
    own_client = client is None
    http = client if client is not None else httpx.Client(timeout=120.0)
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(download_file, http, item.url, item.checksum_url, raw_dir): item
                for item in items
            }
            for future, item in futures.items():
                try:
                    result = future.result()
                except Exception:
                    failed += 1
                    logger.exception("download failed for %s", item.url)
                    continue
                if result.path is None:
                    failed += 1
                    continue
                if not result.from_cache:
                    downloaded += 1
                relative_path = _target_relative_path(config, item.stem)
                target = data_root / relative_path
                existing = catalog.entry_for(relative_path)
                source_sha = file_sha256(result.path)
                if existing is not None and existing.sha256 == source_sha and target.is_file():
                    skipped += 1
                    continue
                df = _convert(config, result.path)
                ts_column = "ts_open_ns" if config.kind == DataKind.KLINES else "ts_ns"
                ts_min, ts_max = _ts_bounds(df, ts_column)
                write_parquet(df, target)
                catalog.upsert(
                    CatalogEntry(
                        path=relative_path,
                        kind=config.kind.value,
                        market=config.market.value,
                        symbol=config.symbol,
                        interval=config.interval,
                        source_url=item.url,
                        sha256=source_sha,
                        n_rows=df.height,
                        ts_min_ns=ts_min,
                        ts_max_ns=ts_max,
                        converted_at=datetime.now(UTC).isoformat(),
                    )
                )
                converted += 1
    finally:
        if own_client:
            http.close()
    return PipelineSummary(
        downloaded=downloaded, skipped=skipped, converted=converted, failed=failed
    )
