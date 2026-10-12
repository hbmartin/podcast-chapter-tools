"""Pure PCI/PSC parsers and reusable RSS chapter lookup."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from .entities import (
    PCI,
    PCI_LEGACY,
    PSC,
    ChapterData,
    ChapterIssue,
    ChapterParseResult,
)
from .errors import ChapterParseError, _validate_result
from .timecodes import parse_timestamp


def _number(value: object, field: str, index: int, issues: list[ChapterIssue]) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        msg = "Expected a finite nonnegative number"
        raise TypeError(msg)
    number = float(value)
    if not math.isfinite(number) or number < 0:
        msg = "Expected a finite nonnegative number"
        raise ValueError(msg)
    if isinstance(value, str):
        issues.append(
            ChapterIssue(index, field, "coerced_number", "Coerced numeric string")
        )
    return number


def _optional_string(
    entry: Mapping[str, Any], field: str, index: int, issues: list[ChapterIssue]
) -> str | None:
    if field not in entry:
        return None
    value = entry[field]
    if isinstance(value, str):
        return value
    issues.append(
        ChapterIssue(index, field, "invalid_optional", "Expected a string; omitted")
    )
    return None


def _finish(  # noqa: PLR0913 - Shared result/context validation.
    chapters: list[ChapterData],
    issues: list[ChapterIssue],
    *,
    nonempty: bool,
    strict: bool,
    source: str | None,
    guid: str | None,
) -> ChapterParseResult:
    return _validate_result(
        ChapterParseResult(tuple(chapters), tuple(issues), source, guid),
        strict=strict,
        unusable=nonempty and not chapters,
    )


def parse_pci_chapters(
    chapters_json: Mapping[str, Any],
    *,
    strict: bool = False,
    source: str | None = None,
    guid: str | None = None,
) -> ChapterParseResult:
    """Parse PCI JSON, salvaging valid entries unless ``strict`` is enabled."""
    if not isinstance(chapters_json, Mapping) or not isinstance(
        chapters_json.get("chapters"), list
    ):
        msg = "Expected a chapters array"
        raise ChapterParseError(msg, source=source, guid=guid)
    entries = chapters_json["chapters"]
    chapters: list[ChapterData] = []
    issues: list[ChapterIssue] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            issues.append(
                ChapterIssue(index, "chapter", "invalid_entry", "Expected an object")
            )
            continue
        try:
            start = _number(entry.get("startTime"), "startTime", index, issues)
        except (TypeError, ValueError, OverflowError) as exc:
            issues.append(ChapterIssue(index, "startTime", "invalid_start", str(exc)))
            continue
        title = _optional_string(entry, "title", index, issues)
        url = _optional_string(entry, "url", index, issues)
        image = _optional_string(entry, "img", index, issues)
        toc = entry.get("toc", True)
        if not isinstance(toc, bool):
            issues.append(
                ChapterIssue(
                    index,
                    "toc",
                    "invalid_optional",
                    "Expected a boolean; defaulted to true",
                )
            )
            toc = True
        end = None
        if "endTime" in entry:
            try:
                end = _number(entry["endTime"], "endTime", index, issues)
            except (TypeError, ValueError, OverflowError) as exc:
                issues.append(
                    ChapterIssue(index, "endTime", "invalid_optional", str(exc))
                )
                end = None
            if end is not None and end < start:
                issues.append(
                    ChapterIssue(
                        index, "endTime", "invalid_optional", "End precedes start"
                    )
                )
                end = None
        chapters.append(ChapterData(start, title, url, image, end, toc))
    return _finish(
        chapters,
        issues,
        nonempty=bool(entries),
        strict=strict,
        source=source,
        guid=guid,
    )


def parse_psc_chapters(
    psc_chapters: ElementTree.Element,
    *,
    strict: bool = False,
    source: str | None = None,
    guid: str | None = None,
) -> ChapterParseResult:
    """Parse a PSC chapters element; start and title are required."""
    if not isinstance(psc_chapters, ElementTree.Element) or psc_chapters.tag not in {
        f"{PSC}chapters",
        "chapters",
    }:
        msg = "Expected a PSC chapters element"
        raise ChapterParseError(msg, source=source, guid=guid)
    chapters: list[ChapterData] = []
    issues: list[ChapterIssue] = []
    for index, entry in enumerate(psc_chapters):
        if entry.tag not in {f"{PSC}chapter", "chapter"}:
            issues.append(
                ChapterIssue(
                    index, "chapter", "invalid_entry", "Expected a PSC chapter"
                )
            )
            continue
        timestamp = entry.attrib.get("start")
        if not isinstance(timestamp, str):
            issues.append(
                ChapterIssue(
                    index, "start", "invalid_start", "Expected a timestamp string"
                )
            )
            continue
        try:
            start = parse_timestamp(timestamp)
        except (ValueError, OverflowError) as exc:
            issues.append(ChapterIssue(index, "start", "invalid_start", str(exc)))
            continue
        if not isinstance(entry.attrib.get("title"), str):
            issues.append(
                ChapterIssue(
                    index, "title", "missing_title", "PSC requires a string title"
                )
            )
            continue
        chapters.append(
            ChapterData(
                start,
                entry.attrib["title"],
                _optional_string(entry.attrib, "href", index, issues),
                _optional_string(entry.attrib, "image", index, issues),
            )
        )
    return _finish(
        chapters,
        issues,
        nonempty=bool(len(psc_chapters)),
        strict=strict,
        source=source,
        guid=guid,
    )


@dataclass(frozen=True, slots=True)
class _ParseFailure:
    message: str
    issues: tuple[ChapterIssue, ...]
    source: str | None
    guid: str | None

    def exception(self) -> ChapterParseError:
        return ChapterParseError(
            self.message, issues=self.issues, source=self.source, guid=self.guid
        )


class FeedChapterIndex:
    """One parsed RSS feed; repeated GUID lookups reuse parsed chapter results."""

    def __init__(
        self,
        items: dict[str, ElementTree.Element],
        *,
        source: str | None,
        issues: tuple[ChapterIssue, ...],
    ) -> None:
        self._items = items
        self._psc: dict[str, ChapterParseResult | _ParseFailure] = {}
        self.source = source
        self.issues = issues

    @property
    def guids(self) -> tuple[str, ...]:
        """Episode GUIDs in feed order, with duplicates omitted."""
        return tuple(self._items)

    def has_psc(self, guid: str) -> bool:
        """Whether this episode declares a PSC chapters element."""
        item = self._items.get(guid)
        return item is not None and item.find(f"{PSC}chapters") is not None

    def psc_for_guid(self, guid: str, *, strict: bool = False) -> ChapterParseResult:
        """Look up PSC chapters, isolating failures to this episode."""
        if guid not in self._psc:
            item = self._items.get(guid)
            element = item.find(f"{PSC}chapters") if item is not None else None
            if element is None:
                self._psc[guid] = ChapterParseResult(source=self.source, guid=guid)
            else:
                try:
                    self._psc[guid] = parse_psc_chapters(
                        element, source=self.source, guid=guid
                    )
                except ChapterParseError as exc:
                    self._psc[guid] = _ParseFailure(
                        exc.message, exc.issues, exc.source, exc.guid
                    )
        result = self._psc[guid]
        if isinstance(result, _ParseFailure):
            raise result.exception()
        return _validate_result(result, strict=strict)

    def pci_url_for_guid(self, guid: str) -> str | None:
        """Find PCI declarations, preferring the canonical namespace URI."""
        item = self._items.get(guid)
        if item is not None:
            for namespace in (PCI, PCI_LEGACY):
                element = item.find(f"{namespace}chapters")
                if element is not None:
                    return element.attrib.get("url")
        return None


def parse_feed_chapters(
    xml: str | bytes, *, source: str | None = None
) -> FeedChapterIndex:
    """Parse an RSS feed once into a GUID index, without fetching or reading files."""
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, ValueError, LookupError) as exc:
        msg = "Invalid feed XML"
        raise ChapterParseError(msg, source=source) from exc
    channel = root.find("./channel")
    if channel is None:
        msg = "Feed has no RSS channel"
        raise ChapterParseError(msg, source=source)
    items: dict[str, ElementTree.Element] = {}
    issues: list[ChapterIssue] = []
    for index, item in enumerate(channel.findall("item")):
        guid = item.findtext("guid")
        if not guid:
            continue
        if guid in items:
            issues.append(
                ChapterIssue(
                    index,
                    "guid",
                    "duplicate_guid",
                    f"Duplicate GUID {guid!r}; retained first episode",
                )
            )
            continue
        items[guid] = item
    return FeedChapterIndex(items, source=source, issues=tuple(issues))
