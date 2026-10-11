"""Download plan construction: monthly files for elapsed months, daily otherwise."""

from dataclasses import dataclass
from datetime import date

from tradingv2.config import DataKind, Market
from tradingv2.data.sources import build_archive_url, build_checksum_url


@dataclass(frozen=True)
class DownloadItem:
    """One file to download from the public data archive."""

    url: str
    checksum_url: str
    stem: str
    is_monthly: bool


def _iter_months(start: date, end: date) -> list[tuple[date, date]]:
    """Return (month_start, month_end) pairs covering start..end inclusive."""
    months: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        month_end = next_month.fromordinal(next_month.toordinal() - 1)
        months.append((cursor, month_end))
        cursor = next_month
    return months


def _daily_items(
    market: Market,
    kind: DataKind,
    symbol: str,
    interval: str | None,
    day_start: date,
    day_end: date,
) -> list[DownloadItem]:
    items: list[DownloadItem] = []
    cursor = day_start
    while cursor <= day_end:
        url = build_archive_url(market, kind, symbol, interval, cursor.isoformat())
        items.append(
            DownloadItem(
                url=url,
                checksum_url=build_checksum_url(url),
                stem=url.rsplit("/", 1)[-1].removesuffix(".zip"),
                is_monthly=False,
            )
        )
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return items


def build_download_plan(
    market: Market,
    kind: DataKind,
    symbol: str,
    interval: str | None,
    start: date,
    end: date,
    today: date,
) -> list[DownloadItem]:
    """Build the ordered list of archive files needed for start..end (inclusive).

    A month that is fully elapsed (its last day strictly before today) is served
    by its monthly file; days of the current or future months use daily files.
    Future days are skipped silently. fundingRate is monthly-only.
    """
    if end < start:
        raise ValueError(f"invalid range: end {end} is before start {start}")

    items: list[DownloadItem] = []
    for month_start, month_end in _iter_months(start, end):
        if month_end >= today:
            if kind == DataKind.FUNDING_RATE:
                continue  # monthly-only kind: no data published yet for ongoing months
            day_start = max(start, month_start)
            day_end = min(end, month_end, today)
            if day_start <= day_end:
                items.extend(_daily_items(market, kind, symbol, interval, day_start, day_end))
            continue
        url = build_archive_url(market, kind, symbol, interval, month_start.isoformat()[:7])
        items.append(
            DownloadItem(
                url=url,
                checksum_url=build_checksum_url(url),
                stem=url.rsplit("/", 1)[-1].removesuffix(".zip"),
                is_monthly=True,
            )
        )
    return items
