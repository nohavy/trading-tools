"""Tests for walk-forward: chronological folds, train optimization, OOS report."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tradingv2.backtest.walkforward import WalkForwardError, make_folds, walk_forward

SECOND = 1_000_000_000


def make_env(tmp_path: Path, n_bars: int = 20) -> tuple[Path, Path, Path]:
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
        "strategy:\n  name: trivial\n  params:\n    hold_bars: 3\n",
        encoding="utf-8",
    )
    return tmp_path, cfg, tmp_path / "runs"


def test_make_folds_golden_bornes() -> None:
    # 20 bars closing at 1s..20s; train 4, test 2
    closes = [(i + 1) * SECOND for i in range(20)]
    folds = make_folds(closes, train_bars=4, test_bars=2)
    assert [(f[0], f[1], f[2], f[3]) for f in folds] == [
        (1 * SECOND, 4 * SECOND, 5 * SECOND, 6 * SECOND),
        (7 * SECOND, 10 * SECOND, 11 * SECOND, 12 * SECOND),
        (13 * SECOND, 16 * SECOND, 17 * SECOND, 18 * SECOND),
    ]


def test_folds_never_overlap() -> None:
    closes = [(i + 1) * SECOND for i in range(40)]
    folds = make_folds(closes, train_bars=5, test_bars=3)
    for prev, current in zip(folds, folds[1:], strict=False):
        assert current[0] > prev[3]  # train starts strictly after previous test ends
        assert prev[2] > prev[1]  # test starts strictly after train ends


def test_walkforward_end_to_end(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    result = walk_forward(
        cfg,
        grid={"hold_bars": [2, 3]},
        train_bars=4,
        test_bars=2,
        data_root=data_root,
        runs_root=runs,
        workers=1,
    )
    assert len(result.folds) == 3
    for fold in result.folds:
        assert fold.best_params["hold_bars"] in (2, 3)
        assert (fold.test_metrics["n_bars"] or 0) > 0
    assert result.oos["n_trades"] == sum(
        (f.test_metrics["n_trades"] or 0) for f in result.folds
    )
    assert 0.0 <= result.pct_positive_folds <= 1.0


def test_walkforward_deterministic(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path)
    r1 = walk_forward(
        cfg, {"hold_bars": [2, 3]}, train_bars=4, test_bars=2, data_root=data_root, runs_root=runs
    )
    r2 = walk_forward(
        cfg, {"hold_bars": [2, 3]}, train_bars=4, test_bars=2, data_root=data_root, runs_root=runs
    )
    assert [(f.best_params, f.test_metrics["net_total"]) for f in r1.folds] == [
        (f.best_params, f.test_metrics["net_total"]) for f in r2.folds
    ]


def test_walkforward_too_short_raises(tmp_path: Path) -> None:
    data_root, cfg, runs = make_env(tmp_path, n_bars=5)
    with pytest.raises(WalkForwardError, match="too short"):
        walk_forward(
            cfg, {"hold_bars": [2]}, train_bars=4, test_bars=2, data_root=data_root, runs_root=runs
        )
