"""Constitutional gate: a paper config runs only against a passed holdout.

The frozen section (symbol, sizing, timing, legs) is fingerprinted with
sha256; a verdict file records the fingerprint of the configuration that
went through a preregistered holdout. A mismatch refuses to start.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_FROZEN_KEYS = (
    "symbol", "total_capital", "hedge_fraction", "trade_start_ns",
    "qty_date", "legs",
)


def frozen_part(config: dict[str, Any]) -> dict[str, Any]:
    """The section that defines the validated protocol (nothing local)."""
    return {key: config[key] for key in _FROZEN_KEYS if key in config}


def frozen_fingerprint(config: dict[str, Any]) -> str:
    payload = yaml.safe_dump(frozen_part(config), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GateResult:
    """Gate decision with its evidence."""

    allowed: bool
    fingerprint: str
    experimental: bool


def gate_check(config: dict[str, Any], verdict_paths: list[Path]) -> GateResult:
    """Allow only when a verdict file records this fingerprint as passed.

    ``experimental: true`` bypasses the check and must stay visible in logs
    and reports (constitution: a bypass is a choice, not an accident).
    """
    fingerprint = frozen_fingerprint(config)
    experimental = bool(config.get("experimental", False))
    if experimental:
        return GateResult(allowed=True, fingerprint=fingerprint, experimental=True)
    for path in verdict_paths:
        try:
            verdict = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = verdict if isinstance(verdict, list) else [verdict]
        for row in rows:
            if (
                isinstance(row, dict)
                and row.get("fingerprint") == fingerprint
                and row.get("passed") is True
            ):
                return GateResult(allowed=True, fingerprint=fingerprint, experimental=False)
    return GateResult(allowed=False, fingerprint=fingerprint, experimental=False)
