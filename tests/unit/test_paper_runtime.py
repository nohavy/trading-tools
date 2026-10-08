"""Paper runtime tests: gate enforcement, two legs, shared sizing, CLI smoke."""

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from tradingv2.paper.gate import frozen_fingerprint
from tradingv2.paper.runtime import GateError, build_carry_session
from tradingv2.strategies.cash_carry import CashCarryPerpLeg, CashCarrySpotLeg

DAY_NS = 86_400_000_000_000
SPOT_CLOSE = 8_000_000.0
PERP_CLOSE = 7_990_000.0


def _config(tmp_path: Path, *, experimental: bool = False) -> dict[str, Any]:
    """A carry config shaped like configs/research-carry-engine-btc.yaml."""
    config = {
        "symbol": "BTCUSDT",
        "total_capital": 20000,
        "hedge_fraction": 0.95,
        "trade_start_ns": 1_785_542_400_000_000_000,
        "qty_date": "2026-07-31",
        "legs": {
            "spot": {
                "strategy": "carry_spot_leg",
                "data": {"market": "spot", "kind": "klines", "interval": "1m",
                         "start": "2026-07-30", "end": "2026-07-31"},
                "account": {"type": "spot", "balance": 10000},
                "costs": {"maker_bps": 10, "taker_bps": 10, "slippage_bps": 1,
                          "latency": {"mean_ms": 150, "jitter_ms": 50, "seed": 42}},
            },
            "perp": {
                "strategy": "carry_perp_leg",
                "data": {"market": "um", "kind": "klines", "interval": "1m",
                         "start": "2026-07-30", "end": "2026-07-31"},
                "account": {"type": "margin", "balance": 10000, "leverage": 2},
                "costs": {"maker_bps": 5, "taker_bps": 5, "slippage_bps": 1,
                          "latency": {"mean_ms": 150, "jitter_ms": 50, "seed": 42}},
            },
        },
    }
    if experimental:
        config["experimental"] = True
    return config


def _data_root(tmp_path: Path) -> Path:
    """Synthetic daily closes for the sizing date (spot + um 1d archives)."""
    root = tmp_path / "data"
    spot_dir = root / "parquet" / "spot" / "klines" / "BTCUSDT" / "1d"
    um_dir = root / "daily" / "um" / "BTCUSDT"
    spot_dir.mkdir(parents=True, exist_ok=True)
    um_dir.mkdir(parents=True, exist_ok=True)
    boundary_ns = 1_785_456_000_000_000_000  # 2026-07-31 00:00 UTC
    open_ts = boundary_ns - DAY_NS  # bar open 07-30, closed on 07-31 00:00
    spot = pl.DataFrame({"ts_open_ns": [open_ts], "close": [SPOT_CLOSE]})
    um = pl.DataFrame({"ts_open_ns": [open_ts], "close": [PERP_CLOSE]})
    spot.write_parquet(spot_dir / "BTCUSDT-1d-2026-07.parquet")
    um.write_parquet(um_dir / "BTCUSDT-1d-2026-07.parquet")
    return root


def test_build_refuses_without_a_passed_holdout(tmp_path: Path) -> None:
    with pytest.raises(GateError, match="fingerprint"):
        build_carry_session(_config(tmp_path), data_root=_data_root(tmp_path),
                            state_dir=tmp_path, feeds=[None, None])


def test_build_accepts_a_matching_passed_verdict(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _data_root(tmp_path)
    verdict_path = tmp_path / "data" / "carry-holdout-2026-10.json"
    verdict_path.write_text(
        json.dumps([{"fingerprint": frozen_fingerprint(config), "passed": True}]),
        encoding="utf-8",
    )
    built = build_carry_session(_config(tmp_path), data_root=_data_root(tmp_path),
                                state_dir=tmp_path, feeds=[None, None])
    session, gate = built.session, built.gate
    assert gate.experimental is False
    assert gate.allowed is True
    assert [leg.name for leg in session.legs] == ["spot", "perp"]


def test_build_experimental_creates_two_coordinated_legs(tmp_path: Path) -> None:
    built = build_carry_session(
        _config(tmp_path, experimental=True), data_root=_data_root(tmp_path),
        state_dir=tmp_path, feeds=[None, None],
    )
    gate = built.gate
    assert gate.allowed is True
    assert gate.experimental is True
    session = built.session
    spot_strategy = session.legs[0].engine.strategy
    perp_strategy = session.legs[1].engine.strategy
    assert isinstance(spot_strategy, CashCarrySpotLeg)
    assert isinstance(perp_strategy, CashCarryPerpLeg)
    # the shared hedge quantity: both legs sized identically from one number
    expected_qty = 0.95 * 20000 / (SPOT_CLOSE + PERP_CLOSE)
    assert spot_strategy.qty == pytest.approx(expected_qty)
    assert perp_strategy.qty == pytest.approx(expected_qty)
