"""Description timestamp scanning with linear forward progress."""

import itertools
from html import unescape
from typing import Literal

from .entities import ChapterData, ChapterIssue, ChapterParseResult, _re_url
from .errors import ChapterParseError
from .markup import DescriptionLine, description_lines, inline_fragment, plain_text
from .timecodes import parse_timestamp

DescriptionMode = Literal["strict", "lenient"]
_MIN_CHAPTERS = 2
_SEPARATORS = "-\u2013\u2014"


def _marker_start(text: str, start: int, end: int) -> int | None:
    marker = start - 1 if start and text[start - 1] in "([" else start
    if marker and not (text[marker - 1].isspace() or text[marker - 1] == ">"):
        return None
    if end < len(text) and not (text[end].isspace() or text[end] in ")]" + _SEPARATORS):
        return None
    return marker


def _timestamps(text: str, mode: DescriptionMode) -> list[tuple[int, int, str]]:  # noqa: C901 - One forward scan, including explicit lenient mode.
    matches: list[tuple[int, int, str]] = []
    index = 0
    while index < len(text):
        if not text[index].isdigit():
            index += 1
            continue
        start = index
        while index < len(text) and (
            text[index].isdigit() or text[index] in {":", "."}
        ):
            index += 1
        token = text[start:index]
        if ":" not in token:
            continue
        marker_start = _marker_start(text, start, index)
        if mode == "strict" and text[:start].strip() not in {
            "",
            ">",
            "(",
            "[",
            ">(",
            ">[",
        }:
            # Strict mode needs only the first numeric run on each line.
            break
        if marker_start is None:
            if mode == "strict":
                break
            continue
        end = index
        if end < len(text) and text[end] in ")]":
            end += 1
        while end < len(text) and (text[end].isspace() or text[end] in _SEPARATORS):
            end += 1
        matches.append((marker_start, end, token))
        if mode == "strict":
            break
        index = end
    return matches


def _title(line: DescriptionLine, start: int, end: int) -> str:
    raw_start = line.offsets[start] if start < len(line.offsets) else len(line.raw)
    # Include opening inline tags immediately before the first visible title
    # character, e.g. '0:00 <a href="...">Intro</a>'.
    previous = line.ends[start - 1] if start else 0
    raw_start = min(raw_start, previous)
    raw_end = line.ends[end - 1] if end and end < len(line.offsets) else len(line.raw)
    return inline_fragment(line.raw[raw_start:raw_end]).strip()


def parse_description_chapters(  # noqa: PLR0913 - Independent public parsing options.
    description: str,
    *,
    strip_html: bool = False,
    mode: DescriptionMode = "strict",
    strict: bool = False,
    require_monotonic: bool = False,
    require_zero_start: bool = False,
    source: str | None = None,
    guid: str | None = None,
) -> ChapterParseResult:
    """Parse chapter lines (or opt-in inline timestamps), requiring two chapters."""
    if mode not in {"strict", "lenient"}:
        msg = f"Unknown description mode: {mode!r}"
        raise ValueError(msg)
    chapters: list[ChapterData] = []
    issues: list[ChapterIssue] = []
    entry_index = 0
    for line in description_lines(description):
        matches = _timestamps(line.text, mode)
        for index, (_, end, token) in enumerate(matches):
            title_end = (
                matches[index + 1][0] if index + 1 < len(matches) else len(line.text)
            )
            try:
                start = parse_timestamp(token)
            except (ValueError, OverflowError) as exc:
                issues.append(
                    ChapterIssue(entry_index, "start", "invalid_start", str(exc))
                )
                entry_index += 1
                continue
            title = _title(line, end, title_end)
            url_match = _re_url.search(title)
            enclosing_url = line.urls[end] if end < len(line.urls) else None
            url = unescape(url_match[0]) if url_match else enclosing_url
            if not plain_text(title):
                issues.append(
                    ChapterIssue(
                        entry_index,
                        "title",
                        "missing_title",
                        "Description title is empty",
                    )
                )
            else:
                chapters.append(
                    ChapterData(start, plain_text(title) if strip_html else title, url)
                )
            entry_index += 1
    if require_monotonic and any(
        b.start <= a.start for a, b in itertools.pairwise(chapters)
    ):
        issues.append(
            ChapterIssue(
                None, "start", "not_monotonic", "Chapter starts must increase strictly"
            )
        )
    if require_zero_start and chapters and chapters[0].start > 1:
        issues.append(
            ChapterIssue(
                0,
                "start",
                "not_zero_start",
                "First chapter must start within one second of zero",
            )
        )
    if (strict and issues) or any(
        issue.code in {"not_monotonic", "not_zero_start"} for issue in issues
    ):
        msg = "Invalid description chapters"
        raise ChapterParseError(
            msg,
            issues=tuple(issues),
            source=source,
            guid=guid,
        )
    return ChapterParseResult(
        tuple(chapters) if len(chapters) >= _MIN_CHAPTERS else (),
        tuple(issues),
        source,
        guid,
    )
