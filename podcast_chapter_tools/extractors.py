"""Legacy tuple extractors and lazy access to HTTP fetching."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from loguru import logger

from .description import DescriptionMode, parse_description_chapters
from .entities import Chapter, ChapterParseResult
from .errors import ChapterFetchError, ChapterParseError
from .parsers import (
    FeedChapterIndex,
    parse_feed_chapters,
    parse_pci_chapters,
    parse_psc_chapters,
)
from .timecodes import ts_to_secs

DEFAULT_TIMEOUT = 30.0
_ts_to_secs = ts_to_secs


def _log_result(result: ChapterParseResult) -> None:
    for issue in result.issues:
        logger.warning(
            "Chapter issue source={} GUID={} entry={} field={} code={}: {}",
            result.source,
            result.guid,
            issue.index,
            issue.field,
            issue.code,
            issue.message,
        )


def _log_failure(exc: ChapterParseError | ChapterFetchError) -> None:
    logger.warning("Chapter extraction failed: {}", exc)
    if isinstance(exc, ChapterParseError):
        _log_result(
            ChapterParseResult(issues=exc.issues, source=exc.source, guid=exc.guid)
        )


def extract_description_chapters(  # noqa: PLR0913 - Backward-compatible keyword options.
    description: str,
    *,
    strip_html: bool = False,
    mode: DescriptionMode = "strict",
    strict: bool = False,
    require_monotonic: bool = False,
    require_zero_start: bool = False,
) -> list[Chapter] | None:
    """Extract chapter lines; opt into mode='lenient' for inline layouts."""
    try:
        result = parse_description_chapters(
            description,
            strip_html=strip_html,
            mode=mode,
            strict=strict,
            require_monotonic=require_monotonic,
            require_zero_start=require_zero_start,
        )
    except ChapterParseError as exc:
        _log_failure(exc)
        return None
    _log_result(result)
    return result.to_legacy() if result.chapters else None


def extract_pci_chapters(
    chapters_json: dict[str, Any],
    *,
    strict: bool = False,
    include_non_toc: bool = False,
) -> list[Chapter] | None:
    """Extract visible legacy PCI chapters, salvaging valid entries by default."""
    try:
        result = parse_pci_chapters(chapters_json, strict=strict)
    except ChapterParseError as exc:
        _log_failure(exc)
        return None
    _log_result(result)
    return result.to_legacy(include_non_toc=include_non_toc)


def fetch_pci_chapters(  # noqa: PLR0913 - Retain legacy positional arguments.
    url: str,
    headers: dict[str, str] | None = None,
    archive_path_json: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    strict: bool = False,
    trust_legacy_archive: bool = False,
) -> ChapterParseResult:
    """Fetch PCI with typed failures and verified archives; HTTP imports are lazy."""
    from .transport import fetch_pci_chapters as fetch  # noqa: PLC0415

    return fetch(
        url,
        headers,
        archive_path_json,
        timeout,
        strict=strict,
        trust_legacy_archive=trust_legacy_archive,
    )


def get_and_extract_pci_chapters(  # noqa: PLR0913 - Retain legacy positional arguments.
    url: str,
    headers: dict[str, str] | None = None,
    archive_path_json: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    strict: bool = False,
    include_non_toc: bool = False,
    trust_legacy_archive: bool = False,
) -> list[Chapter] | None:
    """Fetch visible PCI chapters, translating expected failures to None."""
    try:
        result = fetch_pci_chapters(
            url,
            headers,
            archive_path_json,
            timeout,
            strict=strict,
            trust_legacy_archive=trust_legacy_archive,
        )
    except (ChapterParseError, ChapterFetchError) as exc:
        _log_failure(exc)
        return None
    _log_result(result)
    return result.to_legacy(include_non_toc=include_non_toc)


def _iter_feed_items(root: ElementTree.Element) -> Iterator[ElementTree.Element]:
    channel = root.find("./channel")
    if channel is not None:
        yield from channel.findall("item")


def _file_index(feed_file: Path) -> FeedChapterIndex | None:
    try:
        index = parse_feed_chapters(feed_file.read_bytes(), source=str(feed_file))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read/parse feed {}: {}", feed_file, exc)
        return None
    _log_result(ChapterParseResult(issues=index.issues, source=index.source))
    return index


def _legacy_psc(
    index: FeedChapterIndex, guid: str, *, strict: bool
) -> list[Chapter] | None:
    if not index.has_psc(guid):
        return None
    try:
        result = index.psc_for_guid(guid, strict=strict)
    except ChapterParseError as exc:
        _log_failure(exc)
        return None
    _log_result(result)
    return result.to_legacy()


def extract_psc_chapters_from_file(
    feed_file: Path, guid: str, *, strict: bool = False
) -> list[Chapter] | None:
    """Read a feed and look up legacy PSC chapters for one GUID."""
    index = _file_index(feed_file)
    return _legacy_psc(index, guid, strict=strict) if index is not None else None


def extract_psc_chapters_from_url(
    feed_url: str,
    guid: str,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    strict: bool = False,
) -> list[Chapter] | None:
    """Fetch a feed once and look up legacy PSC chapters for one GUID."""
    from .transport import get_response  # noqa: PLC0415

    try:
        response = get_response(feed_url, headers, timeout)
        index = parse_feed_chapters(response.content, source=feed_url)
    except (ChapterFetchError, ChapterParseError) as exc:
        _log_failure(exc)
        return None
    _log_result(ChapterParseResult(issues=index.issues, source=index.source))
    return _legacy_psc(index, guid, strict=strict)


def extract_all_psc_chapters_from_file(
    feed_file: Path, *, strict: bool = False
) -> dict[str, list[Chapter]] | None:
    """Read/parse once and extract PSC chapters for all episodes keyed by GUID."""
    index = _file_index(feed_file)
    if index is None:
        return None
    all_chapters = {}
    for guid in index.guids:
        chapters = _legacy_psc(index, guid, strict=strict)
        if chapters is not None:
            all_chapters[guid] = chapters
    return all_chapters


def extract_psc_chapters(
    psc_chapters: ElementTree.Element, *, strict: bool = False
) -> list[Chapter] | None:
    """Extract legacy chapters from a PSC chapters element."""
    try:
        result = parse_psc_chapters(psc_chapters, strict=strict)
    except ChapterParseError as exc:
        _log_failure(exc)
        return None
    _log_result(result)
    return result.to_legacy()


def find_pci_chapters_url(feed_file: Path, guid: str) -> str | None:
    """Find a PCI URL using either supported podcast namespace URI."""
    index = _file_index(feed_file)
    return index.pci_url_for_guid(guid) if index is not None else None
