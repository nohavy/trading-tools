"""Tests for YAML configuration loading."""

from pathlib import Path

import pytest

from tradingv2.config import ConfigError, load_config

VALID = """\
data:
  market: spot
  kind: klines
  symbol: BTCUSDT
  interval: 1s
  start: 2026-08-01
  end: 2026-08-31
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "cfg.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.data.market.value == "spot"
    assert cfg.data.kind.value == "klines"
    assert cfg.data.symbol == "BTCUSDT"
    assert cfg.data.interval == "1s"
    assert cfg.data.start.isoformat() == "2026-08-01"
    assert cfg.data.end.isoformat() == "2026-08-31"


def test_unknown_field_reports_field_and_file(tmp_path: Path) -> None:
    path = write(tmp_path, VALID + "  symboll: typo\n")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "symboll" in str(exc.value)
    assert "cfg.yaml" in str(exc.value)


def test_bad_market_value_reports_field(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace("market: spot", "market: binance"))
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "market" in str(exc.value)


def test_interval_required_for_klines(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace("  interval: 1s\n", ""))
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "interval" in str(exc.value)


def test_end_before_start_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace("start: 2026-08-01", "start: 2026-09-01"))
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "end" in str(exc.value)


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")
