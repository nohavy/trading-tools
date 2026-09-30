"""Application configuration models and YAML loading."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Market(StrEnum):
    """Binance market segment."""

    SPOT = "spot"
    UM = "um"


class DataKind(StrEnum):
    """Available historical data kinds on data.binance.vision."""

    KLINES = "klines"
    AGGTRADES = "aggTrades"
    FUNDING_RATE = "fundingRate"


class DataConfig(BaseModel):
    """Historical data request configuration."""

    model_config = ConfigDict(extra="forbid")

    market: Market
    kind: DataKind
    symbol: str = Field(min_length=1)
    interval: str | None = None
    start: date
    end: date

    @model_validator(mode="after")
    def _interval_required_for_klines(self) -> "DataConfig":
        if self.kind == DataKind.KLINES and self.interval is None:
            raise ValueError("interval is required when kind is 'klines'")
        return self

    @model_validator(mode="after")
    def _period_is_ordered(self) -> "DataConfig":
        if self.end < self.start:
            raise ValueError("'end' must be on or after 'start'")
        return self


class AppConfig(BaseModel):
    """Top-level application configuration."""

    model_config = ConfigDict(extra="forbid")

    data: DataConfig


class ConfigError(Exception):
    """Raised when a configuration file is missing, unreadable or invalid."""


def load_config(path: Path) -> AppConfig:
    """Load and validate a YAML configuration file."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc
