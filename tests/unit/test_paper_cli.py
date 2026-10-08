"""CLI smoke: tv2 paper run --once on a gated experimental config."""

import sys
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from tradingv2.cli import app

runner = CliRunner()

_BASE_MS = 1_785_542_400_000  # 2026-08-01 00:00 UTC


class InstantFillClient:
    """Fake public client: static closes, capped output, no network."""

    def klines(
        self, market: Any, symbol: str, interval: str, start_ms: int, limit: int
    ) -> list[list[object]]:
        first = max((start_ms - _BASE_MS) // 60_000, 0)
        rows = []
        for i in range(first, min(first + limit, first + 20)):
            t = _BASE_MS + i * 60_000
            rows.append([t, "100.0", "100.5", "99.5", "100.2", "1.0",
                         t + 59_999, "100.0", 1, "1.0", "100.0", "0.0"])
        return rows

    def funding_rates(self, symbol: str, start_ms: int, limit: int) -> list[tuple[int, float]]:
        return []


def test_paper_run_once_smoke(tmp_path: Path, monkeypatch: Any) -> None:
    config_path = tmp_path / "paper.yaml"
    import yaml

    payload = {
        "symbol": "BTCUSDT",
        "total_capital": 20000,
        "hedge_fraction": 0.95,
        "trade_start_ns": 0,
        "qty_date": "2026-07-31",
        "experimental": True,
        "legs": {
            "spot": {
                "strategy": "carry_spot_leg",
                "data": {"market": "spot", "kind": "klines", "interval": "1m",
                         "start": "2026-07-30", "end": "2026-08-01"},
                "account": {"type": "spot", "balance": 10000},
                "costs": {"maker_bps": 10, "taker_bps": 10, "slippage_bps": 1,
                          "latency": {"mean_ms": 0, "jitter_ms": 0, "seed": 1}},
            },
            "perp": {
                "strategy": "carry_perp_leg",
                "data": {"market": "um", "kind": "klines", "interval": "1m",
                         "start": "2026-07-30", "end": "2026-08-01"},
                "account": {"type": "margin", "balance": 10000, "leverage": 2},
                "costs": {"maker_bps": 5, "taker_bps": 5, "slippage_bps": 1,
                          "latency": {"mean_ms": 0, "jitter_ms": 0, "seed": 1}},
            },
        },
    }

    payload = {
        "symbol": "BTCUSDT",
        "total_capital": 20000,
        "hedge_fraction": 0.95,
        "trade_start_ns": 0,
        "qty_date": "2026-07-31",
        "experimental": True,
        "legs": {
            "spot": {
                "strategy": "carry_spot_leg",
                "data": {"market": "spot", "kind": "klines", "interval": "1m",
                         "start": "2026-07-30", "end": "2026-08-01"},
                "account": {"type": "spot", "balance": 10000},
                "costs": {"maker_bps": 10, "taker_bps": 10, "slippage_bps": 1,
                          "latency": {"mean_ms": 0, "jitter_ms": 0, "seed": 1}},
            },
            "perp": {
                "strategy": "carry_perp_leg",
                "data": {"market": "um", "kind": "klines", "interval": "1m",
                         "start": "2026-07-30", "end": "2026-08-01"},
                "account": {"type": "margin", "balance": 10000, "leverage": 2},
                "costs": {"maker_bps": 5, "taker_bps": 5, "slippage_bps": 1,
                          "latency": {"mean_ms": 0, "jitter_ms": 0, "seed": 1}},
            },
        },
    }
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    # synthetic daily closes for the sizing (spot + um 1d)
    import polars as pl

    spot_dir = tmp_path / "data" / "parquet" / "spot" / "klines" / "BTCUSDT" / "1d"
    um_dir = tmp_path / "data" / "daily" / "um" / "BTCUSDT"
    spot_dir.mkdir(parents=True)
    um_dir.mkdir(parents=True)
    open_ts = 1_785_369_600_000_000_000  # 2026-07-30 00:00 UTC
    pl.DataFrame({"ts_open_ns": [open_ts], "close": [100.0]}).write_parquet(
        spot_dir / "BTCUSDT-1d-2026-07.parquet"
    )
    pl.DataFrame({"ts_open_ns": [open_ts], "close": [100.2]}).write_parquet(
        um_dir / "BTCUSDT-1d-2026-07.parquet"
    )

    from tradingv2.paper import runtime

    monkeypatch.setattr(runtime, "RestKlinesClient", InstantFillClient)
    monkeypatch.setattr(sys, "argv", ["tv2"])  # no real argv interference

    result = runner.invoke(
        app,
        ["paper", "run", "--config", str(config_path), "--data-root", str(tmp_path / "data"),
         "--state-dir", str(tmp_path / "paper"), "--once"],
    )
    assert result.exit_code == 0, result.output
    assert "EXPERIMENTAL" in result.output
    assert "stepped" in result.output
    assert '"spot"' in result.output and '"perp"' in result.output
