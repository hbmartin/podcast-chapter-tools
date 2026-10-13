"""Description timestamp scanning with linear forward progress."""

import itertools
from html import unescape
from typing import Literal

from .entities import ChapterData, ChapterIssue, ChapterParseResult, _re_url
from .errors import ChapterParseError
from .markup import DescriptionLine, description_lines, inline_fragment, plain_text
from .recognition import line_timestamp_start
from .timecodes import parse_timestamp

DescriptionMode = Literal["strict", "lenient"]
_MIN_CHAPTERS = 2
_SEPARATORS = "-\u2013\u2014"
_TOKEN_FOLLOW = ")]" + _SEPARATORS


def _marker_start(
    text: str, start: int, end: int, explicit_start: int | None
) -> int | None:
    """Return the wrapper start when a timestamp has valid boundaries."""
    marker = start - 1 if start and text[start - 1] in "([" else start
    if (
        marker
        and start != explicit_start
        and not (text[marker - 1].isspace() or text[marker - 1] == ">")
    ):
        return None
    if end < len(text) and not (text[end].isspace() or text[end] in _TOKEN_FOLLOW):
        return None
    return marker


def _timestamps(  # noqa: C901 - One forward scan, including explicit lenient mode.
    text: str, mode: DescriptionMode, explicit_start: int | None
) -> list[tuple[int, int, str, bool]]:
    """Collect timestamp tokens and title offsets in one forward scan."""
    matches: list[tuple[int, int, str, bool]] = []
    index = explicit_start if mode == "strict" else 0
    if index is None:
        return matches
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
        # A lone terminal punctuation mark is a delimiter, not another segment.
        if (
            token[-1:] in {":", "."}
            and len(token) > 1
            and token[-2].isdigit()
            and (
                index == len(text)
                or text[index].isspace()
                or text[index] in _TOKEN_FOLLOW
            )
        ):
            token = token[:-1]
        if ":" not in token:
            if mode == "strict":
                break
            continue
        marker_start = _marker_start(text, start, index, explicit_start)
        if marker_start is None:
            if mode == "strict":
                break
            continue
        end = index
        if end < len(text) and text[end] in ")]":
            end += 1
        while end < len(text) and (text[end].isspace() or text[end] in _SEPARATORS):
            end += 1
        matches.append((marker_start, end, token, start == explicit_start))
        if mode == "strict":
            break
        index = end
    return matches


def _title(line: DescriptionLine, start: int, end: int) -> str:
    """Recover a title fragment with its enclosing inline markup."""
    raw_start = line.raw_start(start)
    # Include opening inline tags immediately before the first visible title
    # character, e.g. '0:00 <a href="...">Intro</a>'.
    previous = line.raw_end(start - 1) if start else 0
    raw_start = min(raw_start, previous)
    raw_end = line.raw_end(end - 1) if end and end < len(line.text) else len(line.raw)
    return inline_fragment(line.raw[raw_start:raw_end]).strip()


def _chapter_candidate(
    line: DescriptionLine,
    title_start: int,
    title_end: int,
    token: str,
    *,
    incidental: bool,
) -> tuple[float, str, str] | None:
    """Validate timestamps before titles, except for titleless lenient prose."""
    title = None
    text_title = ""
    if incidental:
        title = _title(line, title_start, title_end)
        text_title = plain_text(title)
        if not text_title:
            return None
    start = parse_timestamp(token)
    if title is None:
        title = _title(line, title_start, title_end)
        text_title = plain_text(title)
    return start, title, text_title


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
    for line in description_lines(description, recover_chapters=True):
        explicit_start = line_timestamp_start(line.text)
        matches = _timestamps(line.text, mode, explicit_start)
        for index, (_, end, token, explicit) in enumerate(matches):
            title_end = (
                matches[index + 1][0] if index + 1 < len(matches) else len(line.text)
            )
            try:
                candidate = _chapter_candidate(
                    line,
                    end,
                    title_end,
                    token,
                    incidental=mode == "lenient" and not explicit,
                )
            except (ValueError, OverflowError) as exc:
                issues.append(
                    ChapterIssue(entry_index, "start", "invalid_start", str(exc))
                )
                entry_index += 1
                continue
            if candidate is None:
                continue
            start, title, text_title = candidate
            url_match = _re_url.search(title)
            enclosing_url = line.url_at(end)
            url = unescape(url_match[0]) if url_match else enclosing_url
            if not text_title:
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
                    ChapterData(start, text_title if strip_html else title, url)
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
