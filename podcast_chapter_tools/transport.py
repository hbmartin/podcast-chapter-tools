"""HTTP and verified archives, imported only by fetching entry points."""

import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

import httpx2
from loguru import logger

from .entities import ChapterParseResult
from .errors import (
    ChapterHTTPError,
    ChapterParseError,
    ChapterTransportError,
    _validate_result,
)
from .parsers import parse_pci_chapters

DEFAULT_TIMEOUT = 30.0


def get_response(
    url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> httpx2.Response:
    """Make one request, exposing HTTP and transport failures distinctly."""
    try:
        response = httpx2.get(
            url, headers=headers or {}, timeout=timeout, follow_redirects=True
        )
    except (httpx2.RequestError, httpx2.InvalidURL) as exc:
        raise ChapterTransportError(str(exc), url=url) from exc
    if not response.is_success:
        try:
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise ChapterHTTPError(
                url=url,
                status_code=response.status_code,
                retry_after=response.headers.get("Retry-After"),
            ) from exc
    return response


def _metadata_path(path: Path) -> Path:
    """Return the verification sidecar path for an archive."""
    return path.with_name(path.name + ".meta.json")


def _read_archive(
    path: Path, url: str, *, trust_legacy_archive: bool
) -> dict[str, Any] | None:
    """Read an archive only when its metadata or legacy policy permits it."""
    try:
        raw = path.read_bytes()
        metadata_path = _metadata_path(path)
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                not isinstance(metadata, dict)
                or metadata.get("version") != 1
                or metadata.get("url") != url
                or metadata.get("sha256") != hashlib.sha256(raw).hexdigest()
            ):
                return None
        elif not trust_legacy_archive:
            return None
        document = json.loads(raw)
        if isinstance(document, dict):
            return document
    except (OSError, ValueError):
        return None
    return None


def _atomic_write(path: Path, raw: bytes) -> None:
    """Atomically replace file bytes while preserving existing permissions."""
    temporary = None
    try:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            mode = None
        candidate = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
        descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        temporary = candidate
        with os.fdopen(descriptor, "wb") as file:
            if mode is not None:
                temporary.chmod(mode)
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_archive(path: Path, url: str, document: dict[str, Any]) -> None:
    """Write the JSON archive and its URL and digest verification sidecar."""
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    metadata = json.dumps(
        {"version": 1, "url": url, "sha256": hashlib.sha256(raw).hexdigest()}
    ).encode("utf-8")
    _atomic_write(path, raw)
    _atomic_write(_metadata_path(path), metadata)


def fetch_pci_chapters(  # noqa: PLR0913 - Retain the legacy arguments plus validation options.
    url: str,
    headers: dict[str, str] | None = None,
    archive_path_json: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    strict: bool = False,
    trust_legacy_archive: bool = False,
) -> ChapterParseResult:
    """Fetch once, recovering from unusable or unverified archives.

    Old raw archives require ``trust_legacy_archive=True`` for offline use.
    Verified URL mismatches are never accepted, including with that option.
    """
    if archive_path_json is not None:
        document = _read_archive(
            archive_path_json, url, trust_legacy_archive=trust_legacy_archive
        )
        if document is not None:
            try:
                result = parse_pci_chapters(document, source=url)
            except ChapterParseError:
                pass
            else:
                return _validate_result(result, strict=strict)
    response = get_response(url, headers, timeout)
    try:
        document = response.json()
    except ValueError as exc:
        msg = "Invalid PCI JSON"
        raise ChapterParseError(msg, source=url) from exc
    result = parse_pci_chapters(document, strict=strict, source=url)
    if archive_path_json is not None:
        try:
            _write_archive(archive_path_json, url, document)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Failed to write PCI archive {} for {}: {}", archive_path_json, url, exc
            )
    return result
