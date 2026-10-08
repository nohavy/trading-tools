"""Paper state report rendering tests."""

from pathlib import Path

import pytest

from tradingv2.backtest.engine import Engine
from tradingv2.config import Market
from tradingv2.core.types import PriceBar
from tradingv2.paper.run_config import paper_config
from tradingv2.paper.session import PaperLeg, PaperSession
from tradingv2.report.paper import render_paper_state
from tradingv2.strategies.cash_carry import CashCarryPerpLeg, CashCarrySpotLeg

DAY_NS = 86_400_000_000_000
QTY = 0.1


class StaticFeed:
    def __init__(self, bars: list[PriceBar]) -> None:
        self._bars = bars
        self.cursor = 0

    def poll(self, now_ns: int) -> list[PriceBar]:
        out = [b for b in self._bars[self.cursor:] if b.ts_close_ns <= now_ns]
        self.cursor += len(out)
        return out

    def poll_funding(self, now_ns: int) -> list[tuple[int, float]]:
        return []

    def restore(self, last_close_ns: int, last_funding_ns: int) -> None:
        self.cursor = sum(1 for b in self._bars if b.ts_close_ns <= last_close_ns)


def _exchange_for(leg: str):
    from tradingv2.costs.fees import FeeSchedule
    from tradingv2.costs.latency import LatencyModel
    from tradingv2.costs.slippage import SlippageModel
    from tradingv2.data.instruments import InstrumentRules
    from tradingv2.execution.exchange import SimulatedExchange
    from tradingv2.portfolio.margin import MarginAccount
    from tradingv2.portfolio.spot import SpotAccount

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


def _bars(n: int) -> list[PriceBar]:
    return [
        PriceBar(ts_open_ns=i * DAY_NS, open=100.0, high=101.0, low=99.0,
                 close=100.5, ts_close_ns=(i + 1) * DAY_NS)
        for i in range(n)
    ]


def test_render_paper_state_html(tmp_path: Path) -> None:
    legs = [
        PaperLeg(name="spot", engine=Engine(_exchange_for("spot"), CashCarrySpotLeg(qty=QTY)),
                 feed=StaticFeed(_bars(3))),
        PaperLeg(name="perp", engine=Engine(_exchange_for("perp"), CashCarryPerpLeg(qty=QTY)),
                 feed=StaticFeed(_bars(3))),
    ]
    session = PaperSession(legs, state_path=tmp_path / "state.json", stop_path=tmp_path / "stop")
    session.resume()
    session.step(now_ns=3 * DAY_NS)

    html_path = render_paper_state(tmp_path)
    html = html_path.read_text(encoding="utf-8")
    assert html_path.name == "paper_report.html"
    assert "spot" in html and "perp" in html


def test_paper_config_loads_the_frozen_holdout_protocol() -> None:
    """The paper protocol IS the holdout protocol (same file, same fingerprint)."""
    config = paper_config("btc")
    assert config["hedge_fraction"] == 0.95
    assert config["legs"]["spot"]["strategy"] == "carry_spot_leg"
    assert config["legs"]["perp"]["account"]["type"] == "margin"
    with pytest.raises((FileNotFoundError, OSError)):
        paper_config("DOGEUSDT")
