"""Tests for the UM perpetual universe (exchangeInfo filters + persistence)."""

import json

import httpx
import pytest

from tradingv2.data.universe import fetch_universe, save_universe

EXCHANGE_INFO = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "contractType": "PERPETUAL",
            "status": "TRADING",
            "quoteAsset": "USDT",
            "baseAsset": "BTC",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        },
        {
            "symbol": "BTCUSDT_250926",
            "contractType": "CURRENT_QUARTER",
            "status": "TRADING",
            "quoteAsset": "USDT",
            "filters": [],
        },
        {
            "symbol": "BTCBUSD",
            "contractType": "PERPETUAL",
            "status": "TRADING",
            "quoteAsset": "BUSD",
            "filters": [],
        },
        {
            "symbol": "DEADUSDT",
            "contractType": "PERPETUAL",
            "status": "SETTLING",
            "quoteAsset": "USDT",
            "filters": [],
        },
        {
            "symbol": "ETHUSDT",
            "contractType": "PERPETUAL",
            "status": "TRADING",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        },
    ]
}


def test_fetch_universe_filters_um_usdt_perpetuals() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "exchangeInfo" in request.url.path
        return httpx.Response(200, text=json.dumps(EXCHANGE_INFO))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        universe = fetch_universe(client)
    symbols = [entry.symbol for entry in universe]
    # only TRADING perpetuals quoted in USDT: quarterly contracts, BUSD, settling are excluded
    assert symbols == ["BTCUSDT", "ETHUSDT"]
    first = universe[0]
    assert first.tick_size == 0.10
    assert first.step_size == 0.001
    assert first.min_notional == 5.0


def test_save_load_universe_roundtrip(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(EXCHANGE_INFO))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        universe = fetch_universe(client)
    path = save_universe(universe, tmp_path)
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["fetched_at"].startswith("2026-") or "T" in raw["fetched_at"]
    assert len(raw["symbols"]) == 2
    assert raw["symbols"][0]["symbol"] == "BTCUSDT"
    assert raw["symbols"][0]["tick_size"] == 0.10


def test_fetch_universe_handles_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    from tradingv2.data.universe import UniverseError

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UniverseError):
            fetch_universe(client)
