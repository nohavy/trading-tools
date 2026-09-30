"""Network integration tests (marked `net`): real downloads from data.binance.vision."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tradingv2.config import DataConfig, DataKind, Market
from tradingv2.data.pipeline import run_download_pipeline
from tradingv2.data.store import Catalog

pytestmark = pytest.mark.net

ONE_DAY = DataConfig(
    market=Market.SPOT,
    kind=DataKind.KLINES,
    symbol="BTCUSDT",
    interval="1s",
    start=date(2026, 9, 25),
    end=date(2026, 9, 25),
)


def test_real_download_one_day_spot_1s(tmp_path: Path) -> None:
    summary = run_download_pipeline(ONE_DAY, tmp_path, today=date(2026, 9, 30))
    assert summary.failed == 0
    assert summary.converted == 1
    parquet = tmp_path / "parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-09-25.parquet"
    df = pl.read_parquet(parquet)
    # verified manually: 2026-09-25 has a complete, zero-gap day (86400 bars)
    assert df.height == 86_400
    assert df["ts_open_ns"][0] == 1_790_294_400_000_000_000
    entry = Catalog.load(tmp_path).list()[0]
    assert entry.n_rows == 86_400
    assert entry.ts_max_ns == entry.ts_min_ns + 86_399 * 1_000_000_000


def test_real_download_is_idempotent(tmp_path: Path) -> None:
    run_download_pipeline(ONE_DAY, tmp_path, today=date(2026, 9, 30))
    summary = run_download_pipeline(ONE_DAY, tmp_path, today=date(2026, 9, 30))
    assert summary.downloaded == 0
    assert summary.converted == 0
    assert summary.skipped == 1
    assert summary.failed == 0


def test_real_instruments_spot_btcusdt(tmp_path: Path) -> None:
    from tradingv2.data.instruments import load_instrument_rules, save_instrument_rules
    from tradingv2.data.instruments import extract_instrument_rules, fetch_exchange_info
    import httpx

    with httpx.Client(timeout=30.0) as client:
        raw = fetch_exchange_info(Market.SPOT, client)
    rules = extract_instrument_rules(Market.SPOT, raw, "BTCUSDT")
    save_instrument_rules(rules, tmp_path)
    back = load_instrument_rules(tmp_path, Market.SPOT, "BTCUSDT")
    assert back == rules
    assert back.tick_size > 0 and back.step_size > 0 and back.min_notional > 0