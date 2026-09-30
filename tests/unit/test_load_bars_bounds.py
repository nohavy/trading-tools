"""Tests for _load_bars: bounds must restrict the monthly files actually read."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tradingv2.backtest.config import BacktestConfig, DataSpec
from tradingv2.backtest.runner import _load_bars
from typing import Any

import tradingv2.backtest.runner as runner


def make_env(tmp_path: Path) -> tuple[Path, BacktestConfig]:
    """Two monthly files: january and march 2020 (february gap on purpose)."""
    base_ns = int((date(2020, 1, 1) - date(1970, 1, 1)).total_seconds() * 1_000_000_000)
    for month, n in [(1, 100), (3, 100)]:
        offset = (month - 1) * 31 * 24 * 3600 * 1_000_000_000
        df = pl.DataFrame(
            {
                "ts_open_ns": [base_ns + offset + i * 60_000_000_000 for i in range(n)],
                "open": [5000.0 + i for i in range(n)],
                "high": [5000.4 + i for i in range(n)],
                "low": [4999.6 + i for i in range(n)],
                "close": [5000.2 + i for i in range(n)],
                "volume": [10.0] * n,
                "quote_volume": [50000.0] * n,
                "n_trades": [1] * n,
                "taker_buy_volume": [5.0] * n,
                "taker_buy_quote_volume": [25000.0] * n,
            }
        )
        directory = tmp_path / "parquet/um/klines/BTCUSDT/1m"
        directory.mkdir(parents=True, exist_ok=True)
        df.write_parquet(directory / f"BTCUSDT-1m-2020-{month:02d}.parquet")
    (tmp_path / "catalog.json").write_text('{"entries": []}', encoding="utf-8")
    cfg = BacktestConfig(
        data=DataSpec(
            market="um",
            kind="klines",
            symbol="BTCUSDT",
            interval="1m",
            start=date(2020, 1, 1),
            end=date(2020, 3, 31),
            tape=None,
        ),
        account={
            "type": "margin", "balance": 1000, "leverage": 5, "mmr": 0.004,
        },
        costs={
            "maker_bps": 2, "taker_bps": 5, "slippage_bps": 0.5,
            "latency": {"mean_ms": 150, "jitter_ms": 50, "seed": 42},
        },
        strategy={"name": "trivial", "params": {}},
    )
    return tmp_path, cfg


def _spy_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    reads: list[str] = []
    original = runner.pl.read_parquet

    def spy(path: Any, *args: Any, **kwargs: Any) -> pl.DataFrame:
        reads.append(Path(str(path)).name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(runner.pl, "read_parquet", spy)
    return reads


def test_bounds_skip_out_of_range_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A narrow march window must not read the january file at all."""
    data_root, cfg = make_env(tmp_path)
    reads = _spy_reads(monkeypatch)
    march_start = int((date(2020, 3, 1) - date(1970, 1, 1)).total_seconds() * 1_000_000_000)
    march_end = int((date(2020, 4, 1) - date(1970, 1, 1)).total_seconds() * 1_000_000_000)
    bars = _load_bars(cfg, data_root, bar_bounds=(march_start, march_end))
    assert bars, "march bars must load"
    assert all("2020-01" not in name for name in reads), f"january was read: {reads}"


def test_no_bounds_reads_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root, cfg = make_env(tmp_path)
    reads = _spy_reads(monkeypatch)
    bars = _load_bars(cfg, data_root, bar_bounds=None)
    assert bars
    assert len(reads) == 2