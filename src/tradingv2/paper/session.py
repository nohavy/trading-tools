"""Paper session: coordinated legs, atomic snapshots, stop file, resume."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingv2.backtest.engine import Engine
from tradingv2.core.types import Fill, FillRole, FundingEvent, Side
from tradingv2.portfolio.margin import MarginAccount
from tradingv2.portfolio.spot import SpotAccount


@dataclass
class PaperLeg:
    """One market leg: its engine (strategy + simulated exchange) and feed."""

    name: str
    engine: Engine
    feed: Any  # poll/poll_funding/restore contract (BarFeed or test fake)


class PaperSession:
    """Drives the legs on the live clock with persistence and a stop file."""

    def __init__(
        self, legs: list[PaperLeg], *, state_path: Path, stop_path: Path
    ) -> None:
        self.legs = legs
        self.state_path = state_path
        self.stop_path = stop_path
        self._last_close: dict[str, int] = {leg.name: 0 for leg in legs}
        self._last_funding: dict[str, int] = {leg.name: 0 for leg in legs}

    def _stop_requested(self) -> bool:
        return self.stop_path.is_file()

    def step(self, now_ns: int) -> dict[str, Any]:
        """Poll every leg, process due bars, snapshot; halted if stop asked."""
        if self._stop_requested():
            return {"halted": True, "legs": self._status()}
        for leg in self.legs:
            bars = leg.feed.poll(now_ns)
            settlements = leg.feed.poll_funding(now_ns)
            events = [FundingEvent(ts_ns=ts, rate=rate) for ts, rate in settlements]
            for bar in bars:
                leg.engine.process_bar(bar, events)
                self._last_close[leg.name] = bar.ts_close_ns
            if settlements:
                self._last_funding[leg.name] = settlements[-1][0]
        self.snapshot()
        return {"halted": False, "legs": self._status()}

    def run(
        self,
        clock: Any,
        *,
        interval_s: int = 1,
        max_steps: int | None = None,
        sleep: Any = None,
    ) -> None:
        """Run until the stop file appears (or max_steps for smoke runs)."""
        if sleep is None:
            import time

            sleep = time.sleep
        steps = 0
        while True:
            if self.step(int(clock())).get("halted"):
                return
            steps += 1
            if max_steps is not None and steps >= max_steps:
                return
            sleep(interval_s)

    def _leg_state(self, leg: PaperLeg) -> dict[str, Any]:
        account = leg.engine.exchange.account
        state: dict[str, Any] = {
            "last_close_ns": self._last_close[leg.name],
            "last_funding_ns": self._last_funding[leg.name],
            "equity": account.equity(leg.engine.exchange.last_price or 0.0),
            "equity_curve": [list(mark) for mark in leg.engine._equity_curve],
            "n_bars": leg.engine._bars_processed,
            "strategy_state": leg.engine.strategy.export_state(),
        }
        if isinstance(account, MarginAccount):
            state.update(
                {
                    "kind": "margin",
                    "balance": account.balance,
                    "leverage": account.leverage,
                    "position": account.position,
                    "entry_price": account.entry_price,
                }
            )
        elif isinstance(account, SpotAccount):
            state.update(
                {
                    "kind": "spot",
                    "quote_balance": account.quote_balance,
                    "base_balance": account.base_balance,
                }
            )
        return state

    def snapshot(self) -> None:
        """Atomic JSON write: tmp file then rename, crash-safe."""
        payload = {"legs": {leg.name: self._leg_state(leg) for leg in self.legs}}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.state_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self.state_path)
        except BaseException:
            os.unlink(tmp)
            raise

    @staticmethod
    def _position(exchange: Any) -> float:
        """Account-level signed position (base units, 0 when flat)."""
        account = exchange.account
        if isinstance(account, MarginAccount):
            return account.position
        if isinstance(account, SpotAccount):
            return account.base_balance
        return float(exchange.position_qty)

    def resume(self) -> bool:
        """Restore accounts, feeds, history from the snapshot; True if resumed."""
        if not self.state_path.is_file():
            return False
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for leg in self.legs:
            saved = state["legs"][leg.name]
            exchange = leg.engine.exchange
            if saved["kind"] == "margin":
                account: MarginAccount | SpotAccount = MarginAccount(
                    balance=saved["balance"], leverage=saved["leverage"]
                )
                if saved["position"] != 0.0:
                    account.apply_fill(
                        Fill(
                            order_id=0,
                            ts_ns=0,
                            price=saved["entry_price"],
                            qty=abs(saved["position"]),
                            fee=0.0,
                            role=FillRole.TAKER,
                            side=Side.BUY if saved["position"] > 0 else Side.SELL,
                        )
                    )
                exchange.account = account
            elif saved["kind"] == "spot":
                exchange.account = SpotAccount(
                    quote_balance=saved["quote_balance"],
                    base_balance=saved["base_balance"],
                )
            leg.engine.restore_history(
                [tuple(mark) for mark in saved["equity_curve"]], saved["n_bars"]
            )
            leg.feed.restore(saved["last_close_ns"], saved["last_funding_ns"])
            self._last_close[leg.name] = saved["last_close_ns"]
            self._last_funding[leg.name] = saved["last_funding_ns"]
            if saved.get("strategy_state"):
                leg.engine.strategy.import_state(saved["strategy_state"])
            else:
                leg.engine.strategy.restore_from_position(self._position(exchange))
        return True

    def _status(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for leg in self.legs:
            exchange = leg.engine.exchange
            out[leg.name] = {
                "position": self._position(exchange),
                "equity": exchange.account.equity(exchange.last_price or 0.0),
                "n_orders": len(exchange._orders),
            }
        return out
