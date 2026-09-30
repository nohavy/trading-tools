"""Real-data validation: edge study, sweep and verdict on august 2026 (slow)."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

RESEARCH = """\
data:
  market: spot
  kind: klines
  symbol: BTCUSDT
  interval: 1s
  start: 2026-08-01
  end: 2026-08-31
signal:
  name: meanrev
  window: 120
  entry_z: 2.5
horizons_s: [1, 5, 15, 60, 300]
cost_pairs:
  - name: spot_taker_market
    maker_bps: 10
    taker_bps: 10
  - name: um_maker_market
    maker_bps: 2
    taker_bps: 5
"""


def test_edge_study_on_real_month(tmp_path: Path) -> None:
    import time

    from tradingv2.research.edge import run_edge_study

    bars = Path("data/parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet")
    if not bars.is_file():
        pytest.skip("august 2026 data not downloaded")
    research = tmp_path / "research.yaml"
    research.write_text(RESEARCH, encoding="utf-8")
    start = time.perf_counter()
    out = run_edge_study(research, data_root=Path("data"), runs_root=tmp_path / "runs")
    elapsed = time.perf_counter() - start
    assert elapsed < 30, f"edge study took {elapsed:.0f}s"
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["n_events"] > 0
    assert len(payload["rows"]) == 5
    assert payload["rows"][0]["edges"]["um_maker_market"] is not None


def test_sweep_8_configs_on_real_month(tmp_path: Path) -> None:
    import time

    from tradingv2.backtest.sweep import sweep_grid

    bars = Path("data/parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet")
    if not bars.is_file():
        pytest.skip("august 2026 data not downloaded")
    cfg = tmp_path / "bt.yaml"
    cfg.write_text(
        "data:\n  market: spot\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-31\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 50\n    seed: 42\n"
        "strategy:\n  name: meanrev_zscore\n  params:\n    window: 120\n    entry_z: 2.5\n"
        "    exit_z: 0.5\n    qty: 0.002\n",
        encoding="utf-8",
    )
    start = time.perf_counter()
    result = sweep_grid(
        cfg,
        {"window": [60, 120], "entry_z": [2.0, 3.0], "max_hold_bars": [2, 5]},
        data_root=Path("data"),
        runs_root=tmp_path / "runs",
        workers=2,  # each worker loads ~1 GB of bars: 2 is the RAM-safe parallelism
    )
    elapsed = time.perf_counter() - start
    assert len(result.entries) == 8
    assert elapsed < 300, f"sweep took {elapsed:.0f}s"
    assert result.html_path.is_file()


def test_verdict_on_real_run(tmp_path: Path) -> None:
    import json

    from tradingv2.backtest.runner import run_backtest
    from tradingv2.backtest.validate import go_no_go

    bars = Path("data/parquet/spot/klines/BTCUSDT/1s/BTCUSDT-1s-2026-08.parquet")
    if not bars.is_file():
        pytest.skip("august 2026 data not downloaded")
    cfg = tmp_path / "bt.yaml"
    cfg.write_text(
        "data:\n  market: spot\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-31\n  tape: aggTrades\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 50\n    seed: 42\n"
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 60\n",
        encoding="utf-8",
    )
    run_dir = run_backtest(cfg, data_root=Path("data"), runs_root=tmp_path / "runs")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    verdict = go_no_go(
        metrics, stress_ok=None, pct_positive_folds=None,
        holdout_attempts=read_attempts(),
    )
    assert verdict.go is False  # stress and walk-forward not evaluated yet
    names = {c.name for c in verdict.criteria}
    assert names == {
        "trades_oos",
        "expectancy",
        "t_stat",
        "profit_factor",
        "drawdown",
        "stress",
        "folds",
    }


def read_attempts() -> int:
    from tradingv2.backtest.validate import read_holdout_attempts

    return read_holdout_attempts(Path("data/holdout_attempts.json"))
