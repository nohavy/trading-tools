"""Tests for SHA256 checksum parsing and file verification."""

import hashlib
from pathlib import Path

import pytest

from tradingv2.data.download import ChecksumError, parse_checksum_text, verify_checksum


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_parse_checksum_text_with_file_name() -> None:
    sha = _sha256(b"hello\n")
    text = f"{sha}  BTCUSDT-1s-2026-08.zip\n"
    assert parse_checksum_text(text) == sha


def test_parse_checksum_text_bare_hash() -> None:
    sha = _sha256(b"hello\n")
    assert parse_checksum_text(sha + "\n") == sha


def test_parse_checksum_text_is_case_insensitive() -> None:
    sha = _sha256(b"hello\n")
    assert parse_checksum_text(sha.upper()) == sha


def test_parse_checksum_text_empty_raises() -> None:
    with pytest.raises(ChecksumError):
        parse_checksum_text("")


def test_parse_checksum_text_malformed_raises() -> None:
    with pytest.raises(ChecksumError):
        parse_checksum_text("not a checksum at all\n")


def test_verify_checksum_accepts_matching_file(tmp_path: Path) -> None:
    data = b"zip bytes here"
    path = tmp_path / "file.zip"
    path.write_bytes(data)
    assert verify_checksum(path, _sha256(data)) is True


def test_verify_checksum_rejects_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "file.zip"
    path.write_bytes(b"zip bytes here")
    assert verify_checksum(path, _sha256(b"other content")) is False


def test_verify_checksum_missing_file_is_false(tmp_path: Path) -> None:
    assert verify_checksum(tmp_path / "absent.zip", _sha256(b"x")) is False
