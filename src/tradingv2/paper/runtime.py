"""Paper runtime: build a gated carry session from a validated config."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentError, InstrumentRules, load_instrument_rules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.paper.feed import BarFeed, KlinesClient, RestKlinesClient
from tradingv2.paper.gate import GateResult, gate_check
from tradingv2.paper.session import PaperLeg, PaperSession
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.portfolio.spot import SpotAccount
from tradingv2.research.cash_carry import carry_qty
from tradingv2.strategies.builtin import build_strategy

HOLDOUT_VERDICT = "carry-holdout-2026-10.json"


class GateError(Exception):
    """Raised when no passed holdout covers this config's fingerprint."""


@dataclass(frozen=True)
class BuiltSession:
    """A gated session with its evidence."""

    session: PaperSession
    gate: GateResult
    hedge_qty: float


def _make_account(account_cfg: dict[str, Any]) -> MarginAccount | SpotAccount:
    if account_cfg["type"] == "margin":
        return MarginAccount(
            balance=float(account_cfg["balance"]),
            leverage=float(account_cfg["leverage"]),
        )
    return SpotAccount(quote_balance=float(account_cfg["balance"]))


def _make_rules(data_root: Path, market: Market, symbol: str) -> InstrumentRules:
    try:
        return load_instrument_rules(data_root, market, symbol)
    except InstrumentError:
        return InstrumentRules(
            symbol=symbol, market=market, tick_size=0.1, step_size=0.001, min_notional=5.0
        )


def build_carry_session(
    config: dict[str, Any],
    *,
    data_root: Path,
    state_dir: Path,
    feeds: list[Any] | None = None,
    client: KlinesClient | None = None,
) -> BuiltSession:
    """Enforce the holdout gate, then assemble both coordinated legs.

    ``feeds`` injects canned feeds for tests (None builds the real public
    feed for that leg's market).
    """
    gate = gate_check(config, [data_root / HOLDOUT_VERDICT])
    if not gate.allowed:
        raise GateError(
            f"fingerprint {gate.fingerprint[:16]} has no passed holdout verdict; "
            "the constitution requires a franchised preregistered holdout "
            "(or an explicit experimental: true)"
        )
    symbol = str(config["symbol"])
    qty = carry_qty(data_root, config)
    trade_start_ns = int(config["trade_start_ns"])
    provided = feeds or [None, None]
    legs: list[PaperLeg] = []
    for index, (name, leg_cfg) in enumerate(config["legs"].items()):
        market = Market(str(leg_cfg["data"]["market"]))
        costs = leg_cfg["costs"]
        exchange = SimulatedExchange(
            rules=_make_rules(data_root, market, symbol),
            account=_make_account(leg_cfg["account"]),
            fees=FeeSchedule(
                maker_bps=float(costs["maker_bps"]), taker_bps=float(costs["taker_bps"])
            ),
            slippage=SlippageModel(bps=float(costs["slippage_bps"])),
            latency=LatencyModel(
                mean_ms=float(costs["latency"]["mean_ms"]),
                jitter_ms=float(costs["latency"]["jitter_ms"]),
                seed=int(costs["latency"]["seed"]),
            ),
        )
        strategy = build_strategy(
            str(leg_cfg["strategy"]), {"qty": qty, "trade_start_ns": trade_start_ns}
        )
        feed = provided[index]
        if feed is None:
            feed = BarFeed(
                client=client or RestKlinesClient(), market=market, symbol=symbol
            )
        legs.append(PaperLeg(name=name, engine=Engine(exchange, strategy), feed=feed))
    session = PaperSession(
        legs,
        state_path=state_dir / "state.json",
        stop_path=state_dir / "paper-stop",
    )
    return BuiltSession(session=session, gate=gate, hedge_qty=qty)
