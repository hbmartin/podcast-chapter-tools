"""Bounded HTML preparation and line boundaries for untrusted show notes."""

import re
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

from .recognition import begins_chapter_line, chapter_timestamp_end

_BLOCKS = frozenset(
    {
        "address",
        "aside",
        "br",
        "dd",
        "details",
        "dialog",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hgroup",
        "hr",
        "p",
        "div",
        "li",
        "ul",
        "ol",
        "section",
        "article",
        "blockquote",
        "main",
        "nav",
        "pre",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
# Bounded alternatives cannot repeatedly scan an unbounded entity suffix.
_ENTITY = re.compile(
    r"&(?:#[0-9]{1,10};?|#[xX][0-9a-fA-F]{1,8};?|[A-Za-z][A-Za-z0-9]{0,31};?)"
)
_HTML_SPACE = "\t\n\f\r "
_LINE_SPACE = "\t\f "
_ATTRIBUTE_END = _HTML_SPACE + "><='\""
_CONTROL_END = 32
_DELETE = 127
_INVALID_VALUE_START = "<=>`"
_RAW_START = re.compile(r"<(script|style)(?=[\t\n\f\r />])", re.IGNORECASE | re.ASCII)
_RAW_END = {
    tag: re.compile(rf"</{tag}(?=[\t\n\f\r />])", re.IGNORECASE | re.ASCII)
    for tag in ("script", "style")
}


def _line_padding_end(text: str, cursor: int) -> int:
    """Skip ASCII HTML padding without crossing a physical line boundary."""
    while cursor < len(text) and text[cursor] in _LINE_SPACE:
        cursor += 1
    return cursor


def _has_attribute_assignment(text: str, cursor: int) -> bool:
    """Read whole attribute tokens after an already recognized timestamp."""
    if text[cursor : cursor + 1] in {")", "]"}:
        cursor += 1
    while cursor < len(text) and text[cursor] not in "\r\n>":
        cursor = _line_padding_end(text, cursor)
        start = cursor
        while cursor < len(text) and text[cursor] not in _ATTRIBUTE_END:
            cursor += 1
        name = text[start:cursor]
        if (
            not name
            or "/" in name
            or name.startswith("?")
            or "@" in name[1:]
            or any(ord(char) < _CONTROL_END or ord(char) == _DELETE for char in name)
        ):
            return False
        cursor = _line_padding_end(text, cursor)
        if text[cursor : cursor + 1] == "=":
            cursor = _line_padding_end(text, cursor + 1)
            return cursor < len(text) and text[cursor] not in _INVALID_VALUE_START
    return False


def _recover_line(text: str, index: int, *, chapter_context: bool) -> bool:
    """Apply chapter-context precedence before testing attribute evidence."""
    end = chapter_timestamp_end(text, index)
    if end is None:
        return False
    padded = _line_padding_end(text, index)
    leading = text[padded : padded + 1] == ">"
    if leading:
        return chapter_context
    return not _has_attribute_assignment(text, end)


def _tag_end(
    text: str,
    cursor: int,
    *,
    recover_chapters: bool = False,
    chapter_context: bool = False,
) -> tuple[int, bool]:
    """Scan to a tag end or recovery boundary while tracking quoted text."""
    quote = ""
    nested = False
    while cursor < len(text):
        char = text[cursor]
        if quote:
            if char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
        elif char == ">":
            break
        elif char == "<":
            nested = True
        elif (
            recover_chapters
            and char in "\r\n"
            and _recover_line(text, cursor + 1, chapter_context=chapter_context)
        ):
            return cursor, True
        cursor += 1
    return cursor, nested


def _raw_parts(
    text: str, index: int, tag: str, *, recover_chapters: bool = False
) -> tuple[list[tuple[bool, str]], int]:
    """Split raw script/style contents from the matching closing tag."""
    closing = _RAW_END[tag].search(text, index)
    if closing is None:
        return [(False, text[index:])], len(text)
    end, _ = _tag_end(text, closing.end(), recover_chapters=recover_chapters)
    if end == len(text):
        return [(False, text[index:])], end
    # Suppressed contents have no source spans, including unfinished closings.
    following = end if text[end] in "\r\n" else end + 1
    return [(False, text[index : closing.start()]), (True, f"</{tag}>")], following


class _TagShape(HTMLParser):
    def __init__(self) -> None:
        """Track whether a raw opening tag has a genuine self-closing marker."""
        super().__init__(convert_charrefs=False)
        self.self_closing = False

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002 - HTMLParser callback.
        """Distinguish slash markers from slash-valued unquoted attributes."""
        self.self_closing = True

    def is_self_closing(self, part: str) -> bool:
        """Classify one recognized raw opening tag with fresh parser state."""
        self.reset()
        self.self_closing = False
        self.feed(part)
        return self.self_closing


class _ChapterContext:
    def __init__(self, text: str, *, enabled: bool) -> None:
        """Cache recognition at each physical line's origin during forward scanning."""
        self.text = text
        self.enabled = enabled
        self.line_start = 0
        self.context_line = -1
        self.chapter = False

    def advance(self, start: int, end: int) -> None:
        """Account for consumed newlines without rescanning an earlier region."""
        newline = max(
            self.text.rfind("\n", start, end), self.text.rfind("\r", start, end)
        )
        if newline >= 0:
            self.line_start = newline + 1

    def recognized(self) -> bool:
        """Recognize a physical line once, even when it contains many tags."""
        if self.context_line != self.line_start:
            self.chapter = self.enabled and begins_chapter_line(
                self.text, self.line_start
            )
            self.context_line = self.line_start
        return self.chapter


def _markup_parts(
    text: str, *, recover_chapters: bool = False
) -> Iterator[tuple[bool, str]]:
    """Yield complete tags or literal data, scanning each candidate once."""
    index = 0
    shape = None
    context = _ChapterContext(text, enabled=recover_chapters)
    while index < len(text):
        start = text.find("<", index)
        if start < 0:
            yield False, text[index:]
            break
        # Advance physical-line context once, rather than rescanning long prefixes.
        context.advance(index, start)
        yield False, text[index:start]
        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
            if end < 0:
                yield False, text[start:]
                break
            index = end + 3
            context.advance(start, index)
            continue
        name_start = start + 1
        if text[name_start : name_start + 1] == "/":
            name_start += 1
        initial = text[name_start : name_start + 1]
        if not initial.isascii() or not initial.isalpha():
            yield False, "<"
            index = start + 1
            continue
        cursor, nested = _tag_end(
            text,
            name_start,
            recover_chapters=recover_chapters,
            chapter_context=context.recognized(),
        )
        # A complete multiline tag can change the following physical-line origin.
        context.advance(start, cursor)
        if cursor == len(text):
            yield False, text[start:]
            break
        if text[cursor] in "\r\n":
            yield False, text[start:cursor]
            index = cursor
            continue
        part = text[start : cursor + 1]
        yield not nested, part
        index = cursor + 1
        raw_start = _RAW_START.match(part) if not nested else None
        if raw_start and not (shape := shape or _TagShape()).is_self_closing(part):
            parts, index = _raw_parts(
                text, index, raw_start[1].lower(), recover_chapters=recover_chapters
            )
            context.advance(cursor, index)
            yield from parts


# Compact source spans retain positional construction during scanning.
@dataclass(frozen=True, slots=True)
class _Span:  # garuff: ignore[GAC009]
    start: int
    end: int
    raw_start: int
    raw_end: int
    url: str | None
    literal: bool


# Line snapshots retain positional construction during scanning.
@dataclass(frozen=True, slots=True)
class DescriptionLine:  # garuff: ignore[GAC009]
    """Visible text with exact offsets into its original inline markup."""

    text: str
    raw: str
    # Source mappings stay immutable once a visible line is flushed.
    spans: tuple[_Span, ...]  # garuff: ignore[GAC005]

    def _span(self, index: int) -> _Span:
        """Find the source span enclosing a visible character offset."""
        return self.spans[
            bisect_right(self.spans, index, key=lambda span: span.start) - 1
        ]

    def raw_start(self, index: int) -> int:
        """Find a visible character's raw start, including whole entities."""
        if index >= len(self.text):
            return len(self.raw)
        span = self._span(index)
        return span.raw_start + index - span.start if span.literal else span.raw_start

    def raw_end(self, index: int) -> int:
        """Find a visible character's raw end, including whole entities."""
        span = self._span(index)
        return span.raw_start + index - span.start + 1 if span.literal else span.raw_end

    def url_at(self, index: int) -> str | None:
        """Resolve enclosing link context without per-character references."""
        return self._span(index).url if index < len(self.text) else None


class _Lines(HTMLParser):
    def __init__(self) -> None:
        """Initialize visible line buffers, compact spans, and link context."""
        super().__init__(convert_charrefs=False)
        self.lines: list[DescriptionLine] = []
        self._raw: list[str] = []
        self._text: list[str] = []
        self._spans: list[_Span] = []
        self._anchors: list[str | None] = []
        self._length = 0
        self._visible_length = 0
        self._hidden: str | None = None

    def boundary(self) -> None:
        """Flush the current visible line and reset its source buffers."""
        if self._spans:
            self.lines.append(
                DescriptionLine(
                    "".join(self._text),
                    "".join(self._raw),
                    tuple(self._spans),
                )
            )
        self._raw = []
        self._text = []
        self._spans = []
        self._length = 0
        self._visible_length = 0

    def _append(self, raw: str, visible: str) -> None:
        """Append raw and visible text, merging adjacent literal spans."""
        if visible in {"\r", "\n", "\r\n"}:
            self.boundary()
            return
        self._raw.append(raw)
        self._text.append(visible)
        if visible:
            span = _Span(
                self._visible_length,
                self._visible_length + len(visible),
                self._length,
                self._length + len(raw),
                self._anchors[-1] if self._anchors else None,
                raw == visible,
            )
            previous = self._spans[-1] if self._spans else None
            if (
                previous is not None
                and previous.literal
                and span.literal
                and previous.raw_end == span.raw_start
                and previous.url == span.url
            ):
                self._spans[-1] = _Span(
                    previous.start,
                    span.end,
                    previous.raw_start,
                    span.raw_end,
                    span.url,
                    literal=True,
                )
            else:
                self._spans.append(span)
        self._length += len(raw)
        self._visible_length += len(visible)

    def handle_data(self, data: str) -> None:
        """Split visible data into lines and decode entities with source spans."""
        if self._hidden:
            return
        for index, line in enumerate(data.splitlines(keepends=True)):
            if index:
                self.boundary()
            part = line.rstrip("\r\n")
            cursor = 0
            for match in _ENTITY.finditer(part):
                self._append(part[cursor : match.start()], part[cursor : match.start()])
                self._append(match[0], unescape(match[0]))
                cursor = match.end()
            self._append(part[cursor:], part[cursor:])
            if line.endswith(("\r", "\n")):
                self.boundary()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track block boundaries, suppressed content, and inline links."""
        if self._hidden:
            return
        if tag in {"script", "style"}:
            self._hidden = tag
        elif tag in _BLOCKS:
            self.boundary()
        else:
            raw = self.get_starttag_text() or ""
            self._raw.append(raw)
            self._length += len(raw)
            if tag == "a":
                href = dict(attrs).get("href")
                self._anchors.append(
                    href if href and href.startswith(("http://", "https://")) else None
                )

    def handle_endtag(self, tag: str) -> None:
        """Close suppressed content or update visible markup and link context."""
        if self._hidden:
            if self._hidden == tag:
                self._hidden = None
            return
        if tag in _BLOCKS:
            self.boundary()
        else:
            raw = f"</{tag}>"
            self._raw.append(raw)
            self._length += len(raw)
            if tag == "a" and self._anchors:
                self._anchors.pop()


def description_lines(
    text: str, *, recover_chapters: bool = False
) -> list[DescriptionLine]:
    """Normalize boundaries without examining tag attributes as chapter text."""
    parser = _Lines()
    for is_tag, part in _markup_parts(text, recover_chapters=recover_chapters):
        if is_tag:
            parser.feed(part)
            # Suppression is explicit; avoid buffering later fragments as CDATA.
            parser.clear_cdata_mode()
            parser.close()  # Flush invalid complete tags without buffering suffixes.
        else:
            parser.handle_data(part)
    parser.boundary()
    return parser.lines


class _Inline(HTMLParser):
    def __init__(self) -> None:
        """Initialize preserved fragments and the stack of open inline tags."""
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002 - HTMLParser callback.
        """Preserve an opening tag and track its matching closing tag."""
        self.parts.append(self.get_starttag_text() or "")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        """Preserve a closing tag only when it matches the open stack."""
        if self.stack and self.stack[-1] == tag:
            self.parts.append(f"</{tag}>")
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        """Preserve literal fragment text without further decoding."""
        self.parts.append(data)


def inline_fragment(text: str) -> str:
    """Retain inline markup without emitting unmatched wrapper closing tags."""
    parser = _Inline()
    for is_tag, part in _markup_parts(text):
        if is_tag:
            parser.feed(part)
            parser.clear_cdata_mode()
            parser.close()
        else:
            parser.handle_data(part)
    parser.parts.extend(f"</{tag}>" for tag in reversed(parser.stack))
    return "".join(parser.parts)


def plain_text(text: str) -> str:
    """Remove markup and decode entities through bounded HTML preparation."""
    return " ".join(" ".join(line.text for line in description_lines(text)).split())
