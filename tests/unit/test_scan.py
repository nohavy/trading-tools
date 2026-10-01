"""Tests for the full asset scan orchestration (synthetic universe E2E)."""

import json
from datetime import date
from pathlib import Path

import polars as pl

from tradingv2.research.scan import run_scan

SECOND = 1_000_000_000


def _bars(symbol: str, start_day: int, n: int, *, dead: bool = False) -> pl.DataFrame:
    base_ns = int((date(2026, 7, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    closes = []
    volumes = []
    for i in range(n):
        base = 5000.0 + (0.05 * i if symbol == "GOODUSDT" else 0.0)
        if symbol == "SPIKEUSDT" and i > 30 and i % 25 == 0:
            base += 8.0
        if dead:
            base = 5000.0
        closes.append(base)
        vol = 200.0 if symbol == "SPIKEUSDT" and i > 30 and i % 25 == 0 else 10.0
        volumes.append(0.0001 if dead else vol)
    return pl.DataFrame(
        {
            "ts_open_ns": [base_ns + (start_day * 24 * 3600 + i * 60) * SECOND for i in range(n)],
            "open": [closes[max(i - 1, 0)] for i in range(n)],
            "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes],
            "close": closes,
            "volume": volumes,
            "quote_volume": [c * v for c, v in zip(closes, volumes, strict=True)],
            "n_trades": [1] * n,
            "taker_buy_volume": [v / 2 for v in volumes],
            "taker_buy_quote_volume": [c * v / 2 for c, v in zip(closes, volumes, strict=True)],
        }
    )


def make_env(tmp_path: Path) -> Path:
    """Universe snapshot + per-symbol data: 2 good, 1 dead, 1 broken (empty dir)."""
    universe = {
        "fetched_at": "2026-09-30T12:00:00",
        "symbols": [
            {"symbol": s, "tick_size": 0.1, "step_size": 0.001, "min_notional": 5.0}
            for s in ["GOODUSDT", "SPIKEUSDT", "DEADUSDT", "BROKENUSDT"]
        ],
    }
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir(parents=True)
    (scan_dir / "universe.json").write_text(json.dumps(universe), encoding="utf-8")

    directory = tmp_path / "parquet/um/klines"
    for symbol in ["GOODUSDT", "SPIKEUSDT", "DEADUSDT"]:
        symbol_dir = directory / symbol / "1m"
        symbol_dir.mkdir(parents=True, exist_ok=True)
        _bars(symbol, 0, 400, dead=(symbol == "DEADUSDT")).write_parquet(
            symbol_dir / f"{symbol}-1m-2026-07.parquet"
        )
    # BROKENUSDT: universe entry but NO data dir
    config = tmp_path / "scan.yaml"
    config.write_text(
        "data:\n  market: um\n  kind: klines\n  interval: 1m\n"
        "  start: 2026-07-01\n  end: 2026-07-31\n"
        "scan:\n  cost_pair:\n    maker_bps: 2\n    taker_bps: 2\n"
        "  target_horizon_s: 300\n  threshold_edge_bps: 0\n"
        "  min_quote_volume_daily: 1000\n  min_trades: 5\n",
        encoding="utf-8",
    )
    return config


def test_scan_survives_failures_and_ranks(tmp_path: Path) -> None:
    config = make_env(tmp_path)
    report = run_scan(config, data_root=tmp_path, runs_root=tmp_path / "runs")
    assert report.is_file()
    summary = json.loads((report.parent / "scan-summary.json").read_text(encoding="utf-8"))
    # BROKENUSDT (no data) is skipped, DEADUSDT (dead) is flagged
    assert summary["skipped"] == ["BROKENUSDT"]
    assert any(a["symbol"] == "DEADUSDT" and a.get("dead") for a in summary["assets"])
    # ranked by edge_net desc (None last)
    nets = [a["edge_net_bps"] for a in summary["assets"] if a["edge_net_bps"] is not None]
    assert nets == sorted(nets, reverse=True)


def test_scan_exports_candidates(tmp_path: Path) -> None:
    config = make_env(tmp_path)
    report = run_scan(config, data_root=tmp_path, runs_root=tmp_path / "runs")
    candidates_path = report.parent / "scan-candidates.json"
    assert candidates_path.is_file()
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    assert payload["threshold_edge_bps"] == 0
    symbols = [c["symbol"] for c in payload["candidates"]]
    assert "BROKENUSDT" not in symbols
    assert "DEADUSDT" not in symbols  # dead assets are not candidates


def test_scan_report_autonomous(tmp_path: Path) -> None:
    config = make_env(tmp_path)
    report = run_scan(config, data_root=tmp_path, runs_root=tmp_path / "runs")
    content = report.read_text(encoding="utf-8")
    assert 'src="http' not in content
    assert "GOODUSDT" in content
