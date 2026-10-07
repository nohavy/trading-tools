"""Paper session tests: two legs, atomic snapshot, resume, stop file, gate."""

import json
from pathlib import Path

import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import PriceBar
from tradingv2.costs.fees import FeeSchedule
from tradingv2.costs.latency import LatencyModel
from tradingv2.costs.slippage import SlippageModel
from tradingv2.data.instruments import InstrumentRules
from tradingv2.execution.exchange import SimulatedExchange
from tradingv2.paper.gate import frozen_fingerprint, gate_check
from tradingv2.paper.session import PaperLeg, PaperSession
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.portfolio.spot import SpotAccount
from tradingv2.strategies.cash_carry import CashCarryPerpLeg, CashCarrySpotLeg

DAY_NS = 86_400_000_000_000
QTY = 0.1  # notional 10 USDT > minNotional 5: the leg must actually fill
BAR_NS = 1_000


class StaticFeed:
    """Canned bars: poll(now) returns every bar whose close <= now, once."""

    def __init__(self, bars: list[PriceBar], funding: list[tuple[int, float]]) -> None:
        self._bars = sorted(bars, key=lambda b: b.ts_close_ns)
        self._funding = funding
        self.cursor = 0
        self.funding_cursor = 0

    def poll(self, now_ns: int) -> list[PriceBar]:
        out = [b for b in self._bars[self.cursor:] if b.ts_close_ns <= now_ns]
        self.cursor += len(out)
        return out

    def poll_funding(self, now_ns: int) -> list[tuple[int, float]]:
        out = [f for f in self._funding[self.funding_cursor:] if f[0] <= now_ns]
        self.funding_cursor += len(out)
        return out

    def restore(self, last_close_ns: int, last_funding_ns: int) -> None:
        self.cursor = sum(1 for b in self._bars if b.ts_close_ns <= last_close_ns)
        self.funding_cursor = sum(1 for f in self._funding if f[0] <= last_funding_ns)


def _bars(n: int) -> list[PriceBar]:
    """Daily-boundary bars: the carry legs only decide at daily closes."""
    return [
        PriceBar(ts_open_ns=i * DAY_NS, open=100.0, high=101.0, low=99.0,
                 close=100.5, ts_close_ns=(i + 1) * DAY_NS)
        for i in range(n)
    ]


def _exchange_for(leg: str) -> SimulatedExchange:
    market = Market.UM if leg == "perp" else Market.SPOT
    return SimulatedExchange(
        rules=InstrumentRules(symbol="BTCUSDT", market=market, tick_size=0.1,
                              step_size=0.001, min_notional=5.0),
        account=(SpotAccount(quote_balance=10_000.0) if leg == "spot"
                 else MarginAccount(balance=10_000.0, leverage=2)),
        fees=FeeSchedule(maker_bps=10.0, taker_bps=10.0),
        slippage=SlippageModel(bps=1.0),
        latency=LatencyModel(mean_ms=0.0, jitter_ms=0.0, seed=1),
    )


def _carry_legs(feeds: list[StaticFeed]) -> list[PaperLeg]:
    """One hedge: the same qty configured on both legs (the sharing contract)."""
    return [
        PaperLeg(
            name="spot",
            engine=Engine(_exchange_for("spot"), CashCarrySpotLeg(qty=QTY)),
            feed=feeds[0],
        ),
        PaperLeg(
            name="perp",
            engine=Engine(_exchange_for("perp"), CashCarryPerpLeg(qty=QTY)),
            feed=feeds[1],
        ),
    ]


def _session(tmp_path: Path, feeds: list[StaticFeed]) -> PaperSession:
    return PaperSession(
        legs=_carry_legs(feeds),
        state_path=tmp_path / "state.json",
        stop_path=tmp_path / "stop",
    )


def test_step_enters_both_legs_once_with_shared_qty(tmp_path: Path) -> None:
    feeds = [StaticFeed(_bars(3), []), StaticFeed(_bars(3), [])]
    session = _session(tmp_path, feeds)
    status = session.step(now_ns=3 * DAY_NS)
    assert status["halted"] is False
    assert status["legs"]["spot"]["position"] == pytest.approx(QTY)
    assert status["legs"]["perp"]["position"] == pytest.approx(-QTY)
    assert (tmp_path / "state.json").is_file()


def test_resume_after_crash_restores_and_never_reenters(tmp_path: Path) -> None:
    feeds_a = [StaticFeed(_bars(3), []), StaticFeed(_bars(3), [])]
    session_a = _session(tmp_path, feeds_a)
    session_a.step(now_ns=3 * DAY_NS)
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))

    feeds_b = [StaticFeed(_bars(6), []), StaticFeed(_bars(6), [])]
    session_b = PaperSession(
        legs=_carry_legs(feeds_b), state_path=tmp_path / "state.json", stop_path=tmp_path / "stop"
    )
    assert session_b.resume() is True
    status = session_b.step(now_ns=6 * DAY_NS)
    # restored positions are intact and the one-entry legs did NOT resubmit
    assert status["legs"]["spot"]["position"] == pytest.approx(QTY)
    assert status["legs"]["spot"]["n_orders"] == 0  # no double submission
    assert status["legs"]["perp"]["n_orders"] == 0
    assert status["legs"]["spot"]["equity"] == pytest.approx(
        saved["legs"]["spot"]["equity"]
    )


def test_stop_file_halts_processing(tmp_path: Path) -> None:
    feeds = [StaticFeed(_bars(3), []), StaticFeed(_bars(3), [])]
    session = _session(tmp_path, feeds)
    (tmp_path / "stop").touch()
    status = session.step(now_ns=3 * DAY_NS)
    assert status["halted"] is True
    assert status["legs"]["spot"]["position"] == pytest.approx(0.0)


def test_gate_requires_a_passed_fingerprint(tmp_path: Path) -> None:
    config = {"data": {"symbol": "BTCUSDT"}, "strategy": {"name": "carry"}}
    fingerprint = frozen_fingerprint(config)
    verdict = {"fingerprint": fingerprint, "passed": True}

    bad_path = tmp_path / "verdict.json"
    bad_path.write_text(json.dumps({"fingerprint": "other", "passed": True}), encoding="utf-8")
    assert gate_check(config, [bad_path]).allowed is False

    good_path = tmp_path / "verdict.json"
    good_path.write_text(json.dumps(verdict), encoding="utf-8")
    assert gate_check(config, [good_path]).allowed is True

    experimental = {**config, "experimental": True}
    assert gate_check(experimental, [bad_path]).allowed is True
