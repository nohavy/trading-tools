"""Tests for backtest configuration loading and validation."""

from pathlib import Path

import pytest

from tradingv2.backtest.config import BacktestConfig, load_backtest_config

VALID = """\
data:
  market: um
  kind: klines
  symbol: BTCUSDT
  interval: 1s
  start: 2026-08-01
  end: 2026-08-31
  tape: aggTrades
account:
  type: margin
  balance: 1000
  leverage: 5
costs:
  maker_bps: 2
  taker_bps: 5
  slippage_bps: 0.5
  latency:
    mean_ms: 150
    jitter_ms: 50
    seed: 42
strategy:
  name: trivial
  params:
    hold_bars: 60
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "bt.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_full_config(tmp_path: Path) -> None:
    cfg = load_backtest_config(write(tmp_path, VALID))
    assert isinstance(cfg, BacktestConfig)
    assert cfg.data.market == "um"
    assert cfg.data.tape == "aggTrades"
    assert cfg.account.type == "margin"
    assert cfg.account.balance == 1000.0
    assert cfg.account.leverage == 5
    assert cfg.costs.maker_bps == 2
    assert cfg.costs.latency.seed == 42
    assert cfg.strategy.name == "trivial"
    assert cfg.strategy.params == {"hold_bars": 60}


def test_tape_optional_defaults_none(tmp_path: Path) -> None:
    content = VALID.replace("  tape: aggTrades\n", "")
    cfg = load_backtest_config(write(tmp_path, content))
    assert cfg.data.tape is None


def test_unknown_strategy_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="strategyy"):
        load_backtest_config(write(tmp_path, VALID.replace("strategy:", "strategyy:")))


def test_invalid_leverage_rejected(tmp_path: Path) -> None:
    bad = VALID.replace("leverage: 5", "leverage: 25")
    with pytest.raises(Exception, match="leverage"):
        load_backtest_config(write(tmp_path, bad))


def test_negative_balance_rejected(tmp_path: Path) -> None:
    bad = VALID.replace("balance: 1000", "balance: -5")
    with pytest.raises(Exception, match="balance"):
        load_backtest_config(write(tmp_path, bad))


def test_unknown_account_type_rejected(tmp_path: Path) -> None:
    bad = VALID.replace("type: margin", "type: futures")
    with pytest.raises(Exception, match="type"):
        load_backtest_config(write(tmp_path, bad))


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="not found"):
        load_backtest_config(tmp_path / "nope.yaml")
