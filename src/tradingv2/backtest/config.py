"""Backtest configuration models and YAML loading."""

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from tradingv2.config import ConfigError


class AccountType:
    """Supported account types."""

    SPOT = "spot"
    MARGIN = "margin"


class AccountSpec(BaseModel):
    """Account construction parameters."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern="^(spot|margin)$")
    balance: float = Field(gt=0)
    leverage: int = Field(default=1, ge=1, le=20)
    mmr: float = Field(default=0.004, gt=0, lt=0.1)


class LatencySpec(BaseModel):
    """Latency model parameters."""

    model_config = ConfigDict(extra="forbid")

    mean_ms: float = Field(ge=0)
    jitter_ms: float = Field(ge=0)
    seed: int = Field(ge=0)


class CostsSpec(BaseModel):
    """Cost model parameters."""

    model_config = ConfigDict(extra="forbid")

    maker_bps: float = Field(ge=0)
    taker_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    latency: LatencySpec


class StrategySpec(BaseModel):
    """Strategy selection and parameters."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)


class DataSpec(BaseModel):
    """Data section of a backtest run (same shape as the download config + tape)."""

    model_config = ConfigDict(extra="forbid")

    market: str = Field(pattern="^(spot|um)$")
    kind: str = Field(pattern="^(klines|aggTrades|fundingRate)$")
    symbol: str = Field(min_length=1)
    interval: str | None = None
    start: date
    end: date
    tape: str | None = None


class BacktestConfig(BaseModel):
    """Full backtest run configuration."""

    model_config = ConfigDict(extra="forbid")

    data: DataSpec
    account: AccountSpec
    costs: CostsSpec
    strategy: StrategySpec


def load_backtest_config(path: Path) -> BacktestConfig:
    """Load and validate a backtest YAML file."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"invalid backtest configuration in {path}: not a mapping")
    try:
        return BacktestConfig.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError -> ConfigError with location
        raise ConfigError(f"invalid backtest configuration in {path}:\n{exc}") from exc
