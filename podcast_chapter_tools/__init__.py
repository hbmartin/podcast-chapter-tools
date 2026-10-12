"""Extract and transform podcast chapter information.

Supports PodcastIndex (PCI) chapters, Podlove Simple Chapters (PSC),
description embeds, and ID3 CHAP frames.
"""

from loguru import logger

from .description import parse_description_chapters
from .entities import (
    Chapter,
    ChapterData,
    ChapterIssue,
    ChapterParseResult,
    ChapterType,
)
from .errors import (
    ChapterFetchError,
    ChapterHTTPError,
    ChapterParseError,
    ChapterTransportError,
)
from .extractors import (
    extract_all_psc_chapters_from_file,
    extract_description_chapters,
    extract_pci_chapters,
    extract_psc_chapters,
    extract_psc_chapters_from_file,
    extract_psc_chapters_from_url,
    fetch_pci_chapters,
    find_pci_chapters_url,
    get_and_extract_pci_chapters,
)
from .id3 import extract_id3_chapters
from .normalize import normalize_chapter_data, normalize_chapters, strip_html
from .parsers import (
    FeedChapterIndex,
    parse_feed_chapters,
    parse_pci_chapters,
    parse_psc_chapters,
)
from .timecodes import format_timestamp, parse_timestamp, secs_to_ts, ts_to_secs
from .writers import (
    chapters_to_description,
    chapters_to_pci_dict,
    chapters_to_pci_json,
    chapters_to_psc_element,
    chapters_to_psc_xml,
)

logger.disable("podcast_chapter_tools")

__version__ = "1.0.0"

__all__ = [
    "Chapter",
    "ChapterData",
    "ChapterFetchError",
    "ChapterHTTPError",
    "ChapterIssue",
    "ChapterParseError",
    "ChapterParseResult",
    "ChapterTransportError",
    "ChapterType",
    "FeedChapterIndex",
    "__version__",
    "chapters_to_description",
    "chapters_to_pci_dict",
    "chapters_to_pci_json",
    "chapters_to_psc_element",
    "chapters_to_psc_xml",
    "extract_all_psc_chapters_from_file",
    "extract_description_chapters",
    "extract_id3_chapters",
    "extract_pci_chapters",
    "extract_psc_chapters",
    "extract_psc_chapters_from_file",
    "extract_psc_chapters_from_url",
    "fetch_pci_chapters",
    "find_pci_chapters_url",
    "format_timestamp",
    "get_and_extract_pci_chapters",
    "normalize_chapter_data",
    "normalize_chapters",
    "parse_description_chapters",
    "parse_feed_chapters",
    "parse_pci_chapters",
    "parse_psc_chapters",
    "parse_timestamp",
    "secs_to_ts",
    "strip_html",
    "ts_to_secs",
]
