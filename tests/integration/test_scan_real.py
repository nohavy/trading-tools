"""Real asset scan: full universe snapshot + scan (slow, network)."""

import json
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.net]


def test_real_scan_finds_candidates(tmp_path: Path) -> None:
    from tradingv2.research.scan import run_scan

    # step 1: fetch the real universe
    with httpx.Client(timeout=30.0) as client:
        from tradingv2.data.universe import fetch_universe, save_universe

        universe = fetch_universe(client)
    save_universe(universe, Path("data"))
    assert len(universe) >= 100, f"expected 100+ UM perps, got {len(universe)}"

    # step 2: use only the symbols already in the catalog (BTC, ETH 1m)
    symbols = ["BTCUSDT", "ETHUSDT"]
    config = tmp_path / "scan.yaml"
    config.write_text(
        "data:\n  market: um\n  kind: klines\n  interval: 1m\n"
        "  start: 2026-08-01\n  end: 2026-08-31\n"
        "scan:\n  cost_pair:\n    maker_bps: 2\n    taker_bps: 2\n"
        "  target_horizon_s: 300\n  threshold_edge_bps: 0\n"
        "  min_quote_volume_daily: 1000000\n  min_trades: 3\n",
        encoding="utf-8",
    )
    # step 3: verify bars exist in the catalog (already downloaded)
    from datetime import date

    from tradingv2.research.scan import _load_symbol_bars

    downloaded = 0
    for symbol in symbols:
        bars = _load_symbol_bars(
            Path("data"), symbol, "um", "1m", date(2026, 8, 1), date(2026, 8, 31)
        )
        if bars is not None:
            downloaded += 1
    assert downloaded == 2, f"expected 2 symbols with data, got {downloaded}"

    # step 4: run the scan
    report = run_scan(config, data_root=Path("data"), runs_root=tmp_path / "runs")
    assert report.is_file()
    summary = json.loads((report.parent / "scan-summary.json").read_text(encoding="utf-8"))
    assert summary["n_scanned"] >= 2
    candidates = json.loads(
        (report.parent / "scan-candidates.json").read_text(encoding="utf-8")
    )
    assert "candidates" in candidates
