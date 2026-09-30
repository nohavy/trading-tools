"""Tests for exchange info fetching and instrument rules extraction."""

import json
from pathlib import Path

import httpx
import pytest

from tradingv2.config import Market
from tradingv2.data.instruments import (
    InstrumentError,
    extract_instrument_rules,
    fetch_exchange_info,
    load_instrument_rules,
    save_instrument_rules,
)

SPOT_BTCUSDT = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "permissions": ["SPOT"],
            "filters": [
                {"filterType": "PRICE_FILTER", "minPrice": "0.01", "tickSize": "0.01"},
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "0.00001",
                    "maxQty": "9000",
                    "stepSize": "0.00001",
                },
                {"filterType": "NOTIONAL", "minNotional": "5", "applyMinToMarket": True},
            ],
        },
        {"symbol": "ETHBTC", "status": "TRADING", "filters": []},
    ]
}

UM_BTCUSDT = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "contractType": "PERPETUAL",
            "status": "TRADING",
            "filters": [
                {"filterType": "PRICE_FILTER", "minPrice": "0.10", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }
    ]
}


def test_extract_spot_rules() -> None:
    rules = extract_instrument_rules(Market.SPOT, SPOT_BTCUSDT, "BTCUSDT")
    assert rules.symbol == "BTCUSDT"
    assert rules.market == Market.SPOT
    assert rules.tick_size == 0.01
    assert rules.step_size == 0.00001
    assert rules.min_notional == 5.0


def test_extract_um_rules() -> None:
    rules = extract_instrument_rules(Market.UM, UM_BTCUSDT, "BTCUSDT")
    assert rules.market == Market.UM
    assert rules.tick_size == 0.10
    assert rules.step_size == 0.001
    assert rules.min_notional == 5.0


def test_unknown_symbol_raises() -> None:
    with pytest.raises(InstrumentError, match="ETHUSDT"):
        extract_instrument_rules(Market.SPOT, SPOT_BTCUSDT, "ETHUSDT")


def test_missing_filter_raises() -> None:
    incomplete = {
        "symbols": [
            {"symbol": "BTCUSDT", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.01"}]}
        ]
    }
    with pytest.raises(InstrumentError, match="LOT_SIZE"):
        extract_instrument_rules(Market.SPOT, incomplete, "BTCUSDT")


def test_fetch_exchange_info_via_mock() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "exchangeInfo" in request.url.path
        return httpx.Response(200, text=json.dumps(SPOT_BTCUSDT))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        raw = fetch_exchange_info(Market.SPOT, client)
    assert raw == SPOT_BTCUSDT


def test_save_load_roundtrip(tmp_path: Path) -> None:
    rules = extract_instrument_rules(Market.UM, UM_BTCUSDT, "BTCUSDT")
    save_instrument_rules(rules, tmp_path)
    assert load_instrument_rules(tmp_path, Market.UM, "BTCUSDT") == rules


def test_load_missing_rules_raises(tmp_path: Path) -> None:
    with pytest.raises(InstrumentError):
        load_instrument_rules(tmp_path, Market.SPOT, "BTCUSDT")
