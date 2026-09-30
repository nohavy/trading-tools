"""Tests for data.binance.vision URL construction (golden strings)."""

import pytest

from tradingv2.config import DataKind, Market
from tradingv2.data.sources import build_archive_url, build_checksum_url

GOLDEN_URLS = [
    (
        Market.SPOT,
        DataKind.KLINES,
        "BTCUSDT",
        "1s",
        "2026-08",
        "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.zip",
    ),
    (
        Market.SPOT,
        DataKind.KLINES,
        "BTCUSDT",
        "1s",
        "2026-09-26",
        "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1s/BTCUSDT-1s-2026-09-26.zip",
    ),
    (
        Market.UM,
        DataKind.KLINES,
        "BTCUSDT",
        "1m",
        "2026-08",
        "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip",
    ),
    (
        Market.SPOT,
        DataKind.AGGTRADES,
        "BTCUSDT",
        None,
        "2026-09-26",
        "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-09-26.zip",
    ),
    (
        Market.UM,
        DataKind.AGGTRADES,
        "BTCUSDT",
        None,
        "2026-08",
        "https://data.binance.vision/data/futures/um/monthly/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-08.zip",
    ),
    (
        Market.UM,
        DataKind.FUNDING_RATE,
        "BTCUSDT",
        None,
        "2026-08",
        "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-08.zip",
    ),
]


@pytest.mark.parametrize(
    ("market", "kind", "symbol", "interval", "period", "expected"),
    GOLDEN_URLS,
)
def test_build_archive_url_golden(
    market: Market,
    kind: DataKind,
    symbol: str,
    interval: str | None,
    period: str,
    expected: str,
) -> None:
    assert build_archive_url(market, kind, symbol, interval, period) == expected


def test_checksum_url_is_archive_url_plus_suffix() -> None:
    url = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.zip"
    assert build_checksum_url(url) == url + ".CHECKSUM"


def test_klines_require_interval() -> None:
    with pytest.raises(ValueError, match="interval"):
        build_archive_url(Market.SPOT, DataKind.KLINES, "BTCUSDT", None, "2026-08")


def test_aggtrades_reject_interval() -> None:
    with pytest.raises(ValueError, match="interval"):
        build_archive_url(Market.SPOT, DataKind.AGGTRADES, "BTCUSDT", "1s", "2026-08")


def test_funding_rate_is_um_monthly_only() -> None:
    with pytest.raises(ValueError, match="futures"):
        build_archive_url(Market.SPOT, DataKind.FUNDING_RATE, "BTCUSDT", None, "2026-08")
    with pytest.raises(ValueError, match="monthly"):
        build_archive_url(Market.UM, DataKind.FUNDING_RATE, "BTCUSDT", None, "2026-08-26")


def test_bad_period_format_rejected() -> None:
    with pytest.raises(ValueError, match="period"):
        build_archive_url(Market.SPOT, DataKind.AGGTRADES, "BTCUSDT", None, "2026/08")


def test_unknown_symbol_format_rejected() -> None:
    with pytest.raises(ValueError, match="symbol"):
        build_archive_url(Market.SPOT, DataKind.AGGTRADES, "btc usdt", None, "2026-08")
