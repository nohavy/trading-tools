"""File downloading from data.binance.vision with checksum verification."""

import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CHUNK_SIZE = 1 << 20

logger = logging.getLogger(__name__)


class ChecksumError(Exception):
    """Raised when a checksum file is missing, empty or malformed."""


class DownloadError(Exception):
    """Raised when a file cannot be downloaded or fails verification."""


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of one download_file call."""

    path: Path | None
    from_cache: bool


def file_sha256(path: Path) -> str:
    """Stream-hash a file and return its sha256 hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def read_single_member_zip(path: Path) -> bytes:
    """Extract the single CSV member of a Binance archive zip."""
    from zipfile import BadZipFile, ZipFile

    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise DownloadError(f"expected a single member in {path}, got {names}")
            return archive.read(names[0])
    except BadZipFile as exc:
        raise DownloadError(f"not a valid zip archive: {path} ({exc})") from exc


class _TransientServerError(Exception):
    """Internal: retryable HTTP status (429/5xx)."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"transient server error {status_code}")
        self.status_code = status_code


def parse_checksum_text(text: str) -> str:
    """Extract the SHA256 hex digest from a .CHECKSUM file content."""
    token = text.split()[0] if text.split() else ""
    if not _SHA256_RE.match(token):
        raise ChecksumError(f"malformed checksum file: no sha256 token found in {text[:80]!r}")
    return token.lower()


def verify_checksum(file_path: Path, expected_sha256: str) -> bool:
    """Stream-hash a file and compare it with the expected digest."""
    if not file_path.is_file():
        return False
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256.lower()


def _fetch_checksum(client: httpx.Client, checksum_url: str) -> str | None:
    response = client.get(checksum_url)
    if response.status_code != 200:
        return None
    return parse_checksum_text(response.text)


def _download_body(client: httpx.Client, url: str, part: Path) -> None:
    start = part.stat().st_size if part.is_file() else 0
    headers = {"Range": f"bytes={start}-"} if start else {}
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code in (429, 500, 502, 503, 504):
            raise _TransientServerError(response.status_code)
        append = response.status_code == 206
        mode = "ab" if append else "wb"
        with part.open(mode) as handle:
            for chunk in response.iter_bytes(_CHUNK_SIZE):
                handle.write(chunk)


def download_file(
    client: httpx.Client,
    url: str,
    checksum_url: str,
    dest_dir: Path,
    *,
    retries: int = 5,
    backoff_base: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> DownloadResult:
    """Download one archive file, verify its checksum and store it atomically.

    Returns a DownloadResult whose path is None when no checksum is available
    (the file is skipped with a warning rather than stored unverified).
    Raises DownloadError after the retry budget is exhausted.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_name = url.rsplit("/", 1)[-1]
    dest = dest_dir / file_name
    part = dest_dir / (file_name + ".part")

    checksum = _fetch_checksum(client, checksum_url)
    if checksum is None:
        logger.warning("no checksum available for %s; skipping download", url)
        return DownloadResult(path=None, from_cache=False)
    if dest.is_file() and verify_checksum(dest, checksum):
        return DownloadResult(path=dest, from_cache=True)
    if dest.is_file():
        dest.unlink()

    last_error = "unknown"
    for attempt in range(retries):
        try:
            _download_body(client, url, part)
            if verify_checksum(part, checksum):
                part.replace(dest)
                return DownloadResult(path=dest, from_cache=False)
            last_error = "checksum mismatch"
            part.unlink(missing_ok=True)
        except (httpx.HTTPError, _TransientServerError) as exc:
            last_error = str(exc)
        if attempt < retries - 1:
            delay = backoff_base * (2**attempt)
            logger.warning(
                "download attempt %d/%d for %s failed (%s); retrying in %.1fs",
                attempt + 1,
                retries,
                url,
                last_error,
                delay,
            )
            sleep(delay)
    raise DownloadError(f"failed to download {url} after {retries} attempts: {last_error}")
