"""Serialize legacy or rich chapters to PCI, PSC, and description text."""

import json
import re
from collections.abc import Iterable
from html import escape
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

from .entities import Chapter, ChapterData
from .timecodes import format_timestamp

_TITLE_BREAK = re.compile(r"\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]")
_URL_UNSAFE = re.compile(r"\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029<>\"']")

PCI_VERSION = "1.2.0"
PSC_VERSION = "1.2"
PSC_NAMESPACE = "http://podlove.org/simple-chapters"
type ChapterInput = Chapter | ChapterData | tuple[int, str, str | None, str | None]


def _data(chapter: ChapterInput) -> ChapterData:
    """Return rich chapter data, converting legacy fields when needed."""
    if isinstance(chapter, ChapterData):
        return chapter
    legacy = Chapter(*chapter)
    return ChapterData(legacy.start, legacy.title, legacy.url, legacy.image)


def chapters_to_pci_dict(chapters: Iterable[ChapterInput]) -> dict[str, Any]:
    """Build PCI JSON, retaining fractions, untitled markers, toc, and endTime."""
    entries = []
    for chapter in chapters:
        data = _data(chapter)
        format_timestamp(data.start)  # Reject nonfinite/negative hand-built data.
        entry: dict[str, Any] = {
            "startTime": int(data.start) if data.start.is_integer() else data.start
        }
        if data.title is not None:
            entry["title"] = data.title
        if data.url is not None:
            entry["url"] = data.url
        if data.image is not None:
            entry["img"] = data.image
        if data.end is not None:
            format_timestamp(data.end)
            if data.end < data.start:
                msg = "Chapter end precedes start"
                raise ValueError(msg)
            entry["endTime"] = int(data.end) if data.end.is_integer() else data.end
        if not data.toc:
            entry["toc"] = False
        entries.append(entry)
    return {"version": PCI_VERSION, "chapters": entries}


def chapters_to_pci_json(
    chapters: Iterable[ChapterInput], indent: int | None = None
) -> str:
    """Serialize chapters to PCI JSON without nonstandard NaN/Infinity values."""
    return json.dumps(chapters_to_pci_dict(chapters), indent=indent, allow_nan=False)


def chapters_to_psc_element(chapters: Iterable[ChapterInput]) -> ElementTree.Element:
    """Build PSC XML, omitting silent markers and PCI end boundaries."""
    ElementTree.register_namespace("psc", PSC_NAMESPACE)
    root = ElementTree.Element(f"{{{PSC_NAMESPACE}}}chapters", {"version": PSC_VERSION})
    for chapter in chapters:
        data = _data(chapter)
        if not data.toc:
            continue
        attributes = {"start": format_timestamp(data.start), "title": data.title or ""}
        if data.url is not None:
            attributes["href"] = data.url
        if data.image is not None:
            attributes["image"] = data.image
        ElementTree.SubElement(root, f"{{{PSC_NAMESPACE}}}chapter", attributes)
    return root


def chapters_to_psc_xml(chapters: Iterable[ChapterInput]) -> str:
    """Serialize visible chapters to PSC XML with fractional starts."""
    return ElementTree.tostring(chapters_to_psc_element(chapters), encoding="unicode")


def chapters_to_description(chapters: Iterable[ChapterInput]) -> str:
    """Serialize visible chapters as lines, retaining fractional starts."""
    lines = []
    for chapter in chapters:
        data = _data(chapter)
        if not data.toc:
            continue
        title = data.title or ""
        url = None
        if data.url:
            url = escape(
                _URL_UNSAFE.sub(lambda match: quote(match[0], safe=""), data.url),
                quote=False,
            )
            # Preserve already-rendered occurrences, including URLs ending in &.
            title = url.join(part.replace(data.url, url) for part in title.split(url))
        title = _TITLE_BREAK.sub(" ", title)
        line = f"{format_timestamp(data.start)} {title}"
        if url is not None and url not in title:
            line += f" {url}"
        lines.append(line)
    return "\n".join(lines)
