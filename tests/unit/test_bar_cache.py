"""Process-local single-slot bar cache: identical data spec reuses the bars."""

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from tradingv2.backtest import runner as runner_mod
from tradingv2.core.types import PriceBar

SECOND = 1_000_000_000


def _make_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Synthetic UM 1s bars under a tmp data_root (catalog + one parquet)."""
    data_root = tmp_path / "data"
    directory = data_root / "parquet" / "um" / "klines" / "BTCUSDT" / "1s"
    directory.mkdir(parents=True)
    data_root.joinpath("catalog.json").write_text("{}", encoding="utf-8")
    base_ns = 1_785_542_400_000_000_000  # 2026-08-01 00:00 UTC
    next_day_ns = base_ns + 86_400 * SECOND
    ts = [base_ns + i * SECOND for i in range(20)] + [
        next_day_ns + i * SECOND for i in range(20)
    ]
    open_px = [5000.0 + 20.0 * i for i in range(40)]
    bars = pl.DataFrame(
        {
            "ts_open_ns": ts,
            "open": open_px,
            "high": [p + 1.0 for p in open_px],
            "low": [p - 1.0 for p in open_px],
            "close": [p + 0.5 for p in open_px],
            "volume": [1.0] * 40,
            "quote_volume": [5000.0] * 40,
            "n_trades": [1] * 40,
            "taker_buy_volume": [1.0] * 40,
            "taker_buy_quote_volume": [5000.0] * 40,
        }
    )
    bars.write_parquet(directory / "BTCUSDT-1s-2026-08-01.parquet")
    cfg = tmp_path / "bt.yaml"
    cfg.write_text(
        "data:\n  market: um\n  kind: klines\n  symbol: BTCUSDT\n  interval: 1s\n"
        "  start: 2026-08-01\n  end: 2026-08-02\n"
        "account:\n  type: margin\n  balance: 1000\n  leverage: 5\n"
        "costs:\n  maker_bps: 2\n  taker_bps: 5\n  slippage_bps: 0\n"
        "  latency:\n    mean_ms: 0\n    jitter_ms: 0\n    seed: 1\n"
        "strategy:\n  name: buy_hold\n  params:\n    qty: 0.005\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    return data_root, cfg, runs


def _variant(cfg_path: Path, tmp: Path, name: str, old: str, new: str) -> Path:
    path = tmp / name
    path.write_text(cfg_path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return path


def _metrics(run_dir: Path) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    return raw


def _counting_load(
    calls: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = runner_mod._load_bars_uncached

    def counting(
        cfg_arg: Any, root: Path, bounds: tuple[int, int] | None = None
    ) -> list[PriceBar]:
        calls.append(1)
        return original(cfg_arg, root, bounds)

    monkeypatch.setattr(runner_mod, "_load_bars_uncached", counting)


def test_identical_data_spec_reuses_cached_bars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root, cfg, runs = _make_env(tmp_path)
    calls: list[int] = []
    _counting_load(calls, monkeypatch)
    b = _variant(cfg, tmp_path, "b.yaml", "qty: 0.005", "qty: 0.004")
    metrics_a = _metrics(runner_mod.run_backtest(cfg, data_root=data_root, runs_root=runs))
    metrics_b = _metrics(runner_mod.run_backtest(b, data_root=data_root, runs_root=runs))
    assert len(calls) == 1  # second run reuses the cached, immutable bars
    assert metrics_b["n_trades"] == metrics_a["n_trades"]


def test_cache_invalidates_on_data_spec_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root, cfg, runs = _make_env(tmp_path)
    calls: list[int] = []
    _counting_load(calls, monkeypatch)
    runner_mod.run_backtest(cfg, data_root=data_root, runs_root=runs)
    other_start = _variant(
        cfg, tmp_path, "other-start.yaml", "start: 2026-08-01", "start: 2026-08-02"
    )
    runner_mod.run_backtest(other_start, data_root=data_root, runs_root=runs)
    assert len(calls) == 2


def test_cache_keeps_a_single_slot(tmp_path: Path) -> None:
    data_root, cfg, runs = _make_env(tmp_path)
    runner_mod.run_backtest(cfg, data_root=data_root, runs_root=runs)
    other_start = _variant(
        cfg, tmp_path, "other-start.yaml", "start: 2026-08-01", "start: 2026-08-02"
    )
    runner_mod.run_backtest(other_start, data_root=data_root, runs_root=runs)
    assert len(runner_mod._BAR_CACHE) == 1
    # original bars re-usable after eviction: rerun the first config (3rd load)
    runner_mod.run_backtest(cfg, data_root=data_root, runs_root=runs)
    assert len(runner_mod._BAR_CACHE) == 1
