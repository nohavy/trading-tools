"""UM perpetual universe: exchangeInfo filters and persistence."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from tradingv2.config import Market
from tradingv2.data.instruments import InstrumentError, InstrumentRules
from tradingv2.data.sources import UM_EXCHANGE_INFO_URL


class UniverseError(Exception):
    """Raised when the universe cannot be fetched or parsed."""


def _filter_value(filters: list[dict[str, Any]], filter_type: str, key: str) -> str:
    for entry in filters:
        if entry.get("filterType") == filter_type:
            if key not in entry:
                raise InstrumentError(f"filter {filter_type} missing key '{key}'")
            return str(entry[key])
    raise InstrumentError(f"filter {filter_type} not found")


def fetch_universe(client: httpx.Client) -> list[InstrumentRules]:
    """Fetch the tradable UM USDT perpetuals with their exchange filters.

    Filters: contractType PERPETUAL, status TRADING, quoteAsset USDT.
    Returns InstrumentRules entries (the single-symbol rules already used by
    the engine).
    """
    response = client.get(UM_EXCHANGE_INFO_URL)
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict) or "symbols" not in raw:
        raise UniverseError("unexpected exchangeInfo payload")
    universe: list[InstrumentRules] = []
    symbols: list[dict[str, Any]] = raw["symbols"]
    for entry in symbols:
        if entry.get("contractType") != "PERPETUAL":
            continue
        if entry.get("status") != "TRADING":
            continue
        if entry.get("quoteAsset") != "USDT":
            continue
        filters = entry.get("filters", [])
        tick = float(_filter_value(filters, "PRICE_FILTER", "tickSize"))
        step = float(_filter_value(filters, "LOT_SIZE", "stepSize"))
        min_notional = float(_filter_value(filters, "MIN_NOTIONAL", "notional"))
        universe.append(
            InstrumentRules(
                symbol=entry["symbol"],
                market=Market.UM,
                tick_size=tick,
                step_size=step,
                min_notional=min_notional,
            )
        )
    universe.sort(key=lambda rule: rule.symbol)
    return universe


def save_universe(universe: list[InstrumentRules], data_root: Path) -> Path:
    """Persist the universe snapshot (symbols + filters + timestamp)."""
    directory = data_root / "scan"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "universe.json"
    payload: dict[str, Any] = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "symbols": [
            {
                "symbol": rule.symbol,
                "tick_size": rule.tick_size,
                "step_size": rule.step_size,
                "min_notional": rule.min_notional,
            }
            for rule in universe
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_universe(data_root: Path) -> list[dict[str, Any]]:
    """Load a previously saved universe snapshot."""
    path = data_root / "scan" / "universe.json"
    if not path.is_file():
        raise UniverseError(f"no universe snapshot at {path}: run 'tv2 scan universe'")
    out: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["symbols"]
    return out
