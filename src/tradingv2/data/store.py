"""Parquet storage (zstd) and the local download catalogue."""

import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

_CATALOG_NAME = "catalog.json"


@dataclass(frozen=True)
class CatalogEntry:
    """One converted data file registered in the catalogue."""

    path: str
    kind: str
    market: str
    symbol: str
    interval: str | None
    source_url: str
    sha256: str
    n_rows: int
    ts_min_ns: int
    ts_max_ns: int
    converted_at: str


def write_parquet(df: pl.DataFrame, path: Path) -> None:
    """Write a dataframe to Parquet with zstd compression, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd")


def read_parquet(path: Path) -> pl.DataFrame:
    """Read a Parquet file back as a dataframe."""
    return pl.read_parquet(path)


def _entry_to_json(entry: CatalogEntry) -> dict[str, Any]:
    return dict(entry.__dict__)


def _entry_from_json(raw: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(**raw)


@dataclass
class Catalog:
    """Idempotent catalogue of converted files, persisted as catalog.json."""

    root: Path

    def __post_init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}
        path = self.root / _CATALOG_NAME
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw.get("entries", []):
                entry = _entry_from_json(item)
                self._entries[entry.path] = entry

    @classmethod
    def load(cls, root: Path) -> "Catalog":
        """Load the catalogue from a data root directory."""
        return cls(root)

    def list(self) -> list[CatalogEntry]:
        """All entries ordered by path."""
        return [self._entries[key] for key in sorted(self._entries)]

    def upsert(self, entry: CatalogEntry) -> None:
        """Insert or replace an entry, then persist the catalogue atomically."""
        self._entries[entry.path] = entry
        self._save()

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / _CATALOG_NAME
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "entries": [_entry_to_json(entry) for entry in self.list()],
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def entry_for(self, relative_path: str) -> CatalogEntry | None:
        """Look up one entry by its relative path."""
        return self._entries.get(relative_path)


def replace_entry(entry: CatalogEntry, **changes: object) -> CatalogEntry:
    """Return a copy of an entry with updated fields."""
    return replace(entry, **changes)  # type: ignore[arg-type]
