"""Exchange info fetching and instrument trading rules."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from tradingv2.config import Market
from tradingv2.data.sources import SPOT_EXCHANGE_INFO_URL, UM_EXCHANGE_INFO_URL


class InstrumentError(Exception):
    """Raised when exchange info is missing, malformed or incomplete."""


@dataclass(frozen=True)
class InstrumentRules:
    """Trading rules of one symbol, from the exchange filters."""

    symbol: str
    market: Market
    tick_size: float
    step_size: float
    min_notional: float


def fetch_exchange_info(market: Market, client: httpx.Client) -> dict[str, Any]:
    """Fetch the raw exchangeInfo payload for a market."""
    url = SPOT_EXCHANGE_INFO_URL if market == Market.SPOT else UM_EXCHANGE_INFO_URL
    response = client.get(url)
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict) or "symbols" not in raw:
        raise InstrumentError(f"unexpected exchangeInfo payload from {url}")
    return raw


def _filter_value(filters: list[dict[str, Any]], filter_type: str, key: str) -> str:
    for entry in filters:
        if entry.get("filterType") == filter_type:
            if key not in entry:
                raise InstrumentError(f"filter {filter_type} missing key '{key}'")
            return str(entry[key])
    raise InstrumentError(f"filter {filter_type} not found")


def extract_instrument_rules(market: Market, raw: dict[str, Any], symbol: str) -> InstrumentRules:
    """Extract trading rules for one symbol from an exchangeInfo payload."""
    for entry in raw.get("symbols", []):
        if entry.get("symbol") == symbol:
            filters = entry.get("filters", [])
            tick = float(_filter_value(filters, "PRICE_FILTER", "tickSize"))
            step = float(_filter_value(filters, "LOT_SIZE", "stepSize"))
            if market == Market.SPOT:
                min_notional = float(_filter_value(filters, "NOTIONAL", "minNotional"))
            else:
                min_notional = float(_filter_value(filters, "MIN_NOTIONAL", "notional"))
            return InstrumentRules(
                symbol=symbol,
                market=market,
                tick_size=tick,
                step_size=step,
                min_notional=min_notional,
            )
    raise InstrumentError(f"symbol {symbol} not found in exchangeInfo")


def save_instrument_rules(rules: InstrumentRules, data_root: Path) -> Path:
    """Persist instrument rules as JSON under data_root/instruments."""
    path = data_root / "instruments" / rules.market.value / f"{rules.symbol}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": rules.symbol,
        "market": rules.market.value,
        "tick_size": rules.tick_size,
        "step_size": rules.step_size,
        "min_notional": rules.min_notional,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_instrument_rules(data_root: Path, market: Market, symbol: str) -> InstrumentRules:
    """Load instrument rules previously saved for a symbol."""
    path = data_root / "instruments" / market.value / f"{symbol}.json"
    if not path.is_file():
        raise InstrumentError(f"no saved instrument rules for {symbol} ({market.value})")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return InstrumentRules(
        symbol=raw["symbol"],
        market=Market(raw["market"]),
        tick_size=float(raw["tick_size"]),
        step_size=float(raw["step_size"]),
        min_notional=float(raw["min_notional"]),
    )
