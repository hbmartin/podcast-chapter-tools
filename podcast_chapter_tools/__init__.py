"""Extract and transform podcast chapter information.

Supports PodcastIndex (PCI) chapters, Podlove Simple Chapters (PSC),
description embeds, and ID3 CHAP frames.
"""

from .entities import Chapter, ChapterType
from .extractors import (
    extract_all_psc_chapters_from_file,
    extract_description_chapters,
    extract_pci_chapters,
    extract_psc_chapters,
    extract_psc_chapters_from_file,
    extract_psc_chapters_from_url,
    find_pci_chapters_url,
    get_and_extract_pci_chapters,
)
from .id3 import extract_id3_chapters
from .normalize import normalize_chapters, strip_html
from .timecodes import secs_to_ts, ts_to_secs
from .writers import (
    chapters_to_description,
    chapters_to_pci_dict,
    chapters_to_pci_json,
    chapters_to_psc_element,
    chapters_to_psc_xml,
)

__version__ = "0.2.0"

__all__ = [
    "Chapter",
    "ChapterType",
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
    "find_pci_chapters_url",
    "get_and_extract_pci_chapters",
    "normalize_chapters",
    "secs_to_ts",
    "strip_html",
    "ts_to_secs",
]
