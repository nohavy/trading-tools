"""Tests for cost stress scenarios (only the costs block changes)."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest
import yaml

from tradingv2.backtest.stress import STRESS_SCENARIOS, stress_test

SECOND = 1_000_000_000


def make_env(tmp_path: Path, n_bars: int = 30) -> tuple[Path, Path, Path]:
    base_ns = int((date(2026, 8, 1) - date(1970, 1, 1)).total_seconds() * SECOND)
    bars = pl.DataFrame(
        {
            "ts_open_ns": [base_ns + i * SECOND for i in range(n_bars)],
            "open": [5000.0 + 0.1 * i for i in range(n_bars)],
            "high": [5000.3 + 0.1 * i for i in range(n_bars)],
            "low": [4999.9 + 0.1 * i for i in range(n_bars)],
            "close": [5000.2 + 0.1 * i for i in range(n_bars)],
            "volume": [10.0] * n_bars,
            "quote_volume": [50000.0] * n_bars,
            "n_trades": [1] * n_bars,
            "taker_buy_volume": [5.0] * n_bars,
            "taker_buy_quote_volume": [25000.0] * n_bars,
        }
    )
    directory = tmp_path / "parquet/um/klines/BTCUSDT/1s"
    directory.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(directory / "BTCUSDT-1s-2026-08-01.parquet")
    (tmp_path / "catalog.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    cfg = tmp_path / "bt.yaml"
    cfg.write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-01\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0.5\n"
        "  latency:\n    mean_ms: 150\n    jitter_ms: 0\n    seed: 42\n"
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 5\n",
        encoding="utf-8",
    )
    return tmp_path, cfg, tmp_path / "runs"


def test_four_scenarios_defined() -> None:
    assert set(STRESS_SCENARIOS) == {
        "fees_x1.5",
        "slippage_x2",
        "latency_plus_250ms",
        "combined",
    }


def test_stress_modifies_costs_only(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    results = stress_test(cfg, data_root=data_root, runs_root=runs)
    assert [r.name for r in results] == list(STRESS_SCENARIOS)
    base = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    def normalize(d: dict[str, object], reference: dict[str, object]) -> dict[str, object]:
        # only reference keys: defaults added by the model dump are ignored
        subset = {k: d[k] for k in reference if k in d and d[k] is not None}
        out: dict[str, object] = json.loads(json.dumps(subset, default=str))
        return out
    for scenario_result in results:
        variant = yaml.safe_load(
            (scenario_result.run_dir / "config.yaml").read_text(encoding="utf-8")
        )
        assert normalize(variant["data"], base["data"]) == normalize(base["data"], base["data"])
        assert normalize(variant["account"], base["account"]) == normalize(
            base["account"], base["account"]
        )
        assert normalize(variant["strategy"], base["strategy"]) == normalize(
            base["strategy"], base["strategy"]
        )
        fee_mult, slip_mult, latency_add = STRESS_SCENARIOS[scenario_result.name]
        assert variant["costs"]["maker_bps"] == pytest.approx(base["costs"]["maker_bps"] * fee_mult)
        assert variant["costs"]["taker_bps"] == pytest.approx(base["costs"]["taker_bps"] * fee_mult)
        assert variant["costs"]["slippage_bps"] == pytest.approx(
            base["costs"]["slippage_bps"] * slip_mult
        )
        assert variant["costs"]["latency"]["mean_ms"] == pytest.approx(
            base["costs"]["latency"]["mean_ms"] + latency_add
        )


def test_stress_survival_flag(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    results = stress_test(cfg, data_root=data_root, runs_root=runs)
    for scenario_result in results:
        assert scenario_result.survived == (
            scenario_result.expectancy_bps is not None and scenario_result.expectancy_bps > 0
        )
        assert scenario_result.net_total is not None


def test_stress_dying_strategy_reported(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    # brutal base costs: even the baseline barely survives; stress must kill it
    text = cfg.read_text(encoding="utf-8")
    text = text.replace("maker_bps: 2", "maker_bps: 80").replace("taker_bps: 5", "taker_bps: 200")
    cfg.write_text(text, encoding="utf-8")
    results = stress_test(cfg, data_root=data_root, runs_root=runs)
    assert not any(r.survived for r in results)
    metrics = json.loads((results[0].run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["n_trades"] > 0
