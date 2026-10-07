"""Paper feed tests: 1m kline polling, dedup, outage backfill, funding."""

import pytest

from tradingv2.config import Market
from tradingv2.paper.feed import BarFeed, RestKlinesClient

MINUTE_NS = 60_000_000_000
BASE_MS = 1_785_542_400_000  # 2026-08-01 00:00 UTC, minute boundary


def _kline(i: int, close: float) -> list[object]:
    """Binance kline array shape: [open_time, open, high, low, close, volume, ...]."""
    t = BASE_MS + i * 60_000
    return [t, str(close - 0.5), str(close + 0.5), str(close - 1.0), str(close), "1.0",
            t + 59_999, "5000.0", 1, "1.0", "5000.0", "0.0"]


class FakeClient:
    """Serves klines generated per closed-minute from an internal clock."""

    def __init__(self, closes: dict[int, float]) -> None:
        self._closes = closes  # minute index -> close price

    def klines(
        self, market: Market, symbol: str, interval: str, start_ms: int, limit: int
    ) -> list[list[object]]:
        assert interval == "1m"
        first = (start_ms - BASE_MS) // 60_000
        out = [
            _kline(i, self._closes.get(i, 100.0))
            for i in range(max(first, 0), max(first, 0) + limit)
        ]
        return [k for k in out if int(str(k[0])) >= start_ms]

    def funding_rates(self, symbol: str, start_ms: int, limit: int) -> list[tuple[int, float]]:
        return []


FUNDING_SCHEDULE: list[tuple[int, float]] = [
    (BASE_MS + 480 * 60_000, 0.0001),
    (BASE_MS + 960 * 60_000, 0.0002),
]


class FundingClient(FakeClient):
    """Fake funding history anchored on BASE: settlements every 8 hours."""

    def funding_rates(self, symbol: str, start_ms: int, limit: int) -> list[tuple[int, float]]:
        return [(t, r) for t, r in FUNDING_SCHEDULE if t >= start_ms][:limit]


def test_first_poll_returns_all_closed_bars_in_order() -> None:
    client = FakeClient(closes={i: 100.0 + i for i in range(4)})
    feed = BarFeed(client=client, market=Market.UM, symbol="BTCUSDT")
    bars = feed.poll(now_ns=(BASE_MS + 4 * 60_000) * 1_000_000)
    assert [b.ts_close_ns for b in bars] == [
        (BASE_MS + (i + 1) * 60_000) * 1_000_000 for i in range(4)
    ]
    assert bars[0].close == pytest.approx(100.0)
    assert bars[-1].close == pytest.approx(103.0)


def test_repeated_poll_returns_nothing_new() -> None:
    client = FakeClient(closes={i: 100.0 + i for i in range(4)})
    feed = BarFeed(client=client, market=Market.UM, symbol="BTCUSDT")
    feed.poll(now_ns=(BASE_MS + 4 * 60_000) * 1_000_000)
    assert feed.poll(now_ns=(BASE_MS + 4 * 60_000) * 1_000_000) == []


def test_outage_backfill_returns_only_missing_bars_in_order() -> None:
    closes = {i: 100.0 + i for i in range(8)}
    client = FakeClient(closes=closes)
    feed = BarFeed(client=client, market=Market.UM, symbol="BTCUSDT")
    feed.poll(now_ns=(BASE_MS + 3 * 60_000) * 1_000_000)
    # simulated outage: now jumps three minutes ahead
    bars = feed.poll(now_ns=(BASE_MS + 6 * 60_000) * 1_000_000)
    assert [b.ts_close_ns for b in bars] == [
        (BASE_MS + (i + 1) * 60_000) * 1_000_000 for i in (3, 4, 5)
    ]
    # in-order arrival is preserved across polls
    assert [b.close for b in feed.poll(now_ns=(BASE_MS + 8 * 60_000) * 1_000_000)] == [
        pytest.approx(106.0), pytest.approx(107.0)
    ]


def test_unfinished_minute_never_leaks_a_partial_bar() -> None:
    client = FakeClient(closes={i: 100.0 for i in range(4)})
    feed = BarFeed(client=client, market=Market.UM, symbol="BTCUSDT")
    # now sits inside minute 3: bars 0..2 are closed, bar 3 is not
    bars = feed.poll(now_ns=(BASE_MS + 3 * 60_000 + 20_000) * 1_000_000)
    assert len(bars) == 3


def test_funding_settlements_delivered_once_in_order() -> None:
    feed = BarFeed(client=FundingClient(closes={}), market=Market.UM, symbol="BTCUSDT")
    first = feed.poll_funding(now_ns=(BASE_MS + 960 * 60_000) * 1_000_000)
    assert [rate for _, rate in first] == [0.0001, 0.0002]
    assert feed.poll_funding(now_ns=(BASE_MS + 960 * 60_000) * 1_000_000) == []


def test_rest_client_builds_public_urls_without_keys() -> None:
    client = RestKlinesClient()
    assert client.klines_url(Market.UM, "BTCUSDT").startswith("https://fapi.binance.com/fapi/")
    assert client.klines_url(Market.SPOT, "ETHUSDT").startswith("https://api.binance.com/api/")
    assert "X-MBX-APIKEY" not in str(client.headers())
