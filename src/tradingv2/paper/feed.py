"""Public REST market feed for paper trading: klines polling + funding.

Only public endpoints are used: no API keys exist in this package, and no
order can ever leave the process (fills stay simulated).
"""

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from tradingv2.config import Market
from tradingv2.core.types import PriceBar

MINUTE_NS = 60_000_000_000
MINUTE_MS = 60_000


class FeedError(Exception):
    """Raised when the public feed cannot be reached or parsed."""


class KlinesClient(Protocol):
    """Injectable transport for tests; the REST client implements it live."""

    def klines(
        self, market: Market, symbol: str, interval: str, start_ms: int, limit: int
    ) -> list[list[object]]: ...

    def funding_rates(self, symbol: str, start_ms: int, limit: int) -> list[tuple[int, float]]: ...


class RestKlinesClient:
    """Real public REST transport (no keys, read-only)."""

    _BASES = {
        Market.UM: "https://fapi.binance.com/fapi/v1",
        Market.SPOT: "https://api.binance.com/api/v3",
    }
    _FUNDING_BASES = {
        Market.UM: "https://fapi.binance.com/fapi/v1",
        Market.SPOT: "https://api.binance.com/api/v3",
    }

    def klines_url(self, market: Market, symbol: str) -> str:
        return f"{self._BASES[market]}/klines"

    def funding_url(self, market: Market) -> str:
        return f"{self._FUNDING_BASES[market]}/fundingRate"

    def headers(self) -> dict[str, str]:
        """Explicitly key-free headers (constitution: paper touches no key)."""
        return {}

    def _get(self, url: str, params: dict[str, str]) -> object:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        request = urllib.request.Request(f"{url}?{query}", headers=self.headers())
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json_loads(response.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            raise FeedError(f"feed unreachable: {url}: {exc}") from exc

    def klines(
        self, market: Market, symbol: str, interval: str, start_ms: int, limit: int
    ) -> list[list[object]]:
        payload = self._get(
            self.klines_url(market, symbol),
            {"symbol": symbol, "interval": interval, "startTime": str(start_ms),
             "limit": str(limit)},
        )
        if not isinstance(payload, list):
            raise FeedError(f"unexpected klines payload for {symbol}")
        rows = [row for row in payload if isinstance(row, list)]
        return rows

    def funding_rates(self, symbol: str, start_ms: int, limit: int) -> list[tuple[int, float]]:
        payload = self._get(
            self.funding_url(Market.UM),
            {"symbol": symbol, "startTime": str(start_ms), "limit": str(limit)},
        )
        if not isinstance(payload, list):
            raise FeedError(f"unexpected funding payload for {symbol}")
        settlements: list[tuple[int, float]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            settlements.append((int(str(row["fundingTime"])), float(str(row["fundingRate"]))))
        return settlements


def json_loads(data: bytes) -> object:
    import json

    return json.loads(data.decode("utf-8"))


@dataclass
class BarFeed:
    """Delivers closed 1m bars (and funding settlements) exactly once, in order."""

    client: KlinesClient
    market: Market
    symbol: str
    interval: str = "1m"
    interval_ns: int = MINUTE_NS

    def _next_close_ms(self) -> int:
        return int(self.last_delivered_close_ns // 1_000_000 + MINUTE_MS)

    def __post_init__(self) -> None:
        self.last_delivered_close_ns = 0
        self.last_funding_ns = 0

    def poll(self, now_ns: int) -> list[PriceBar]:
        """Return all bars fully closed by ``now_ns`` that were not delivered yet."""
        now_ms = now_ns // 1_000_000
        horizon_ms = now_ms - self.interval_ns // 1_000_000
        start_ms = self._next_close_ms() - self.interval_ns // 1_000_000
        # initial backfill cap: at most ~500 minutes of history on a cold start
        start_ms = max(start_ms, horizon_ms - 499 * MINUTE_MS)
        if start_ms > horizon_ms:
            return []
        raw = self.client.klines(
            self.market, self.symbol, self.interval, start_ms=start_ms, limit=1000
        )
        bars: list[PriceBar] = []
        for row in raw:
            open_ms = int(str(row[0]))
            open_ns = open_ms * 1_000_000
            close_ns = open_ns + self.interval_ns
            if close_ns <= self.last_delivered_close_ns or close_ns > now_ns:
                continue
            bars.append(
                PriceBar(
                    ts_open_ns=open_ns,
                    open=float(str(row[1])),
                    high=float(str(row[2])),
                    low=float(str(row[3])),
                    close=float(str(row[4])),
                    ts_close_ns=close_ns,
                    volume=float(str(row[5])),
                )
            )
        bars.sort(key=lambda b: b.ts_close_ns)
        if bars:
            self.last_delivered_close_ns = bars[-1].ts_close_ns
        return bars

    def restore(self, last_close_ns: int, last_funding_ns: int) -> None:
        """Reposition the feed after a restart (paper resume)."""
        self.last_delivered_close_ns = last_close_ns
        self.last_funding_ns = last_funding_ns

    def poll_funding(self, now_ns: int) -> list[tuple[int, float]]:
        """Return funding settlements not seen yet, strictly in ts order."""
        start_ms = max(self.last_funding_ns // 1_000_000, now_ns // 1_000_000 - 480 * MINUTE_MS)
        raw = self.client.funding_rates(
            symbol=self.symbol, start_ms=start_ms, limit=100
        )
        events = [(ts * 1_000_000, rate) for ts, rate in raw if ts * 1_000_000 <= now_ns]
        events.sort(key=lambda item: item[0])
        unique = [(ts, rate) for ts, rate in events if ts > self.last_funding_ns]
        if unique:
            self.last_funding_ns = unique[-1][0]
        return unique
