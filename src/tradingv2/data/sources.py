"""URL construction for Binance public data archives and API endpoints."""

import re

from tradingv2.config import DataKind, Market

ARCHIVE_BASE = "https://data.binance.vision/data"
SPOT_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
UM_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{4,20}$")


def _market_dir(market: Market) -> str:
    return market.value if market == Market.SPOT else "futures/um"


def _granularity(period: str) -> str:
    if _MONTH_RE.match(period):
        return "monthly"
    if _DAY_RE.match(period):
        return "daily"
    raise ValueError(f"invalid period '{period}': expected YYYY-MM or YYYY-MM-DD")


def _archive_file_name(kind: str, symbol: str, interval: str | None, period: str) -> str:
    suffix = (
        f"{symbol}-{interval}-{period}" if interval is not None else f"{symbol}-{kind}-{period}"
    )
    return f"{suffix}.zip"


def build_archive_url(
    market: Market, kind: DataKind, symbol: str, interval: str | None, period: str
) -> str:
    """Build the data.binance.vision archive URL for one file."""
    if not _SYMBOL_RE.match(symbol):
        raise ValueError(f"invalid symbol '{symbol}'")
    granularity = _granularity(period)

    if kind == DataKind.KLINES:
        if interval is None:
            raise ValueError("klines require an interval")
        name = _archive_file_name(kind.value, symbol, interval, period)
        return (
            f"{ARCHIVE_BASE}/{_market_dir(market)}/{granularity}/klines/{symbol}/{interval}/{name}"
        )

    if kind == DataKind.AGGTRADES:
        if interval is not None:
            raise ValueError("aggTrades have no interval")
        name = _archive_file_name(kind.value, symbol, None, period)
        return f"{ARCHIVE_BASE}/{_market_dir(market)}/{granularity}/aggTrades/{symbol}/{name}"

    if kind == DataKind.FUNDING_RATE:
        if market != Market.UM:
            raise ValueError("fundingRate is futures-only")
        if granularity != "monthly":
            raise ValueError("fundingRate is monthly only")
        name = _archive_file_name(kind.value, symbol, None, period)
        return f"{ARCHIVE_BASE}/{_market_dir(market)}/{granularity}/fundingRate/{symbol}/{name}"

    raise ValueError(f"unsupported data kind: {kind}")


def build_checksum_url(archive_url: str) -> str:
    """Build the SHA256 checksum URL for an archive file."""
    return archive_url + ".CHECKSUM"
