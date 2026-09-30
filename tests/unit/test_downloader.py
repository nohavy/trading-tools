"""Tests for the archive downloader: atomicity, resume, skip, backoff."""

import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest

from tradingv2.data.download import DownloadError, download_file

ZIP_CONTENT = b"PK\x03\x04 fake zip payload " * 40


def sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_transport(
    *,
    zip_content: bytes,
    checksum_sha: str | None,
    fail_first: int = 0,
    status_first: int = 500,
    requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """Serve /file.zip (optionally failing the first N attempts) and /file.zip.CHECKSUM."""
    state = {"body_attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path.endswith(".CHECKSUM"):
            if checksum_sha is None:
                return httpx.Response(404)
            return httpx.Response(200, text=checksum_sha + "  file.zip\n")
        state["body_attempts"] += 1
        if state["body_attempts"] <= fail_first:
            return httpx.Response(status_first)
        range_header = request.headers.get("range")
        if range_header and range_header.startswith("bytes="):
            start = int(range_header.removeprefix("bytes=").split("-")[0])
            return httpx.Response(206, content=zip_content[start:])
        return httpx.Response(200, content=zip_content)

    return httpx.MockTransport(handler)


def run_download(client: httpx.Client, tmp_path: Path, **kwargs: Any) -> Path | None:
    url = "https://x/file.zip"
    return download_file(client, url, url + ".CHECKSUM", tmp_path, **kwargs)


def test_download_writes_file_atomically(tmp_path: Path) -> None:
    sha = sha_of(ZIP_CONTENT)
    transport = make_transport(zip_content=ZIP_CONTENT, checksum_sha=sha)
    with httpx.Client(transport=transport) as client:
        result = run_download(client, tmp_path)
    assert result == tmp_path / "file.zip"
    assert result.read_bytes() == ZIP_CONTENT
    assert not (tmp_path / "file.zip.part").exists()


def test_skips_existing_valid_file(tmp_path: Path) -> None:
    sha = sha_of(ZIP_CONTENT)
    dest = tmp_path / "file.zip"
    dest.write_bytes(ZIP_CONTENT)
    requests: list[httpx.Request] = []
    transport = make_transport(zip_content=ZIP_CONTENT, checksum_sha=sha, requests=requests)
    with httpx.Client(transport=transport) as client:
        result = run_download(client, tmp_path)
    assert result == dest
    assert dest.read_bytes() == ZIP_CONTENT
    # Only the checksum request was made; the body was not re-downloaded.
    assert len(requests) == 1


def test_existing_invalid_file_is_redownloaded(tmp_path: Path) -> None:
    sha = sha_of(ZIP_CONTENT)
    dest = tmp_path / "file.zip"
    dest.write_bytes(b"corrupted")
    transport = make_transport(zip_content=ZIP_CONTENT, checksum_sha=sha)
    with httpx.Client(transport=transport) as client:
        result = run_download(client, tmp_path)
    assert result is not None
    assert result.read_bytes() == ZIP_CONTENT


def test_resume_from_partial_file(tmp_path: Path) -> None:
    sha = sha_of(ZIP_CONTENT)
    part = tmp_path / "file.zip.part"
    part.write_bytes(ZIP_CONTENT[:10])
    transport = make_transport(zip_content=ZIP_CONTENT, checksum_sha=sha)
    with httpx.Client(transport=transport) as client:
        result = run_download(client, tmp_path)
    assert result is not None
    assert result.read_bytes() == ZIP_CONTENT
    assert not part.exists()


def test_retry_with_backoff_on_server_errors(tmp_path: Path) -> None:
    sha = sha_of(ZIP_CONTENT)
    transport = make_transport(
        zip_content=ZIP_CONTENT, checksum_sha=sha, fail_first=2, status_first=503
    )
    delays: list[float] = []
    with httpx.Client(transport=transport) as client:
        result = download_file(
            client, "https://x/file.zip", "https://x/file.zip.CHECKSUM", tmp_path,
            retries=5, backoff_base=0.5, sleep=delays.append,
        )
    assert result is not None
    assert result.read_bytes() == ZIP_CONTENT
    assert delays == [0.5, 1.0]


def test_rate_limit_429_also_backed_off(tmp_path: Path) -> None:
    sha = sha_of(ZIP_CONTENT)
    transport = make_transport(
        zip_content=ZIP_CONTENT, checksum_sha=sha, fail_first=1, status_first=429
    )
    delays: list[float] = []
    with httpx.Client(transport=transport) as client:
        result = download_file(
            client, "https://x/file.zip", "https://x/file.zip.CHECKSUM", tmp_path,
            retries=3, backoff_base=0.25, sleep=delays.append,
        )
    assert result is not None
    assert delays == [0.25]


def test_checksum_mismatch_retries_then_raises(tmp_path: Path) -> None:
    wrong_sha = sha_of(b"not the payload")
    transport = make_transport(zip_content=ZIP_CONTENT, checksum_sha=wrong_sha)
    delays: list[float] = []
    with httpx.Client(transport=transport) as client:
        with pytest.raises(DownloadError, match="checksum"):
            download_file(
                client, "https://x/file.zip", "https://x/file.zip.CHECKSUM", tmp_path,
                retries=2, backoff_base=0.1, sleep=delays.append,
            )
    assert delays == [0.1]
    assert not (tmp_path / "file.zip").exists()


def test_missing_checksum_file_returns_none_with_no_corrupt_output(tmp_path: Path) -> None:
    transport = make_transport(zip_content=ZIP_CONTENT, checksum_sha=None)
    with httpx.Client(transport=transport) as client:
        result = run_download(client, tmp_path)
    assert result is None
    assert list(tmp_path.iterdir()) == []
