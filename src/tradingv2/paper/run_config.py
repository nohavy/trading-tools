"""Paper run configuration: the frozen holdout protocol as the paper protocol."""

from pathlib import Path
from typing import Any

import yaml

_CONFIGS = Path("configs")


def paper_config(symbol_stem: str) -> dict[str, Any]:
    """Load the frozen holdout config for a symbol stem ("btc" -> BTCUSDT).

    The paper run MUST use the exact validated protocol: reading the same
    committed file as the holdout guarantees the fingerprint match.
    """
    path = _CONFIGS / f"research-carry-holdout-2026-10-{symbol_stem.strip().lower()}.yaml"
    config: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config
