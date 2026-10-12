"""Bounded HTML preparation and line boundaries for untrusted show notes."""

import re
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

from .recognition import begins_chapter_line

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
_RAW_START = re.compile(r"<(script|style)(?=[\s/>])", re.IGNORECASE)
_RAW_END = {
    tag: re.compile(rf"</{tag}\s*>", re.IGNORECASE) for tag in ("script", "style")
}


def _tag_end(text: str, cursor: int) -> tuple[int, bool]:
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
        elif char in "\r\n" and begins_chapter_line(text, cursor + 1):
            return cursor, True
        cursor += 1
    return cursor, nested


def _raw_parts(text: str, index: int, tag: str) -> tuple[list[tuple[bool, str]], int]:
    closing = _RAW_END[tag].search(text, index)
    if closing is None:
        return [(False, text[index:])], len(text)
    return [(False, text[index : closing.start()]), (True, closing[0])], closing.end()


def _markup_parts(text: str) -> Iterator[tuple[bool, str]]:
    """Yield complete tags or literal data, scanning each candidate once."""
    index = 0
    while index < len(text):
        start = text.find("<", index)
        if start < 0:
            yield False, text[index:]
            break
        yield False, text[index:start]
        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
            if end < 0:
                yield False, text[start:]
                break
            index = end + 3
            continue
        name_start = start + 1
        if text[name_start : name_start + 1] == "/":
            name_start += 1
        initial = text[name_start : name_start + 1]
        if not initial.isascii() or not initial.isalpha():
            yield False, "<"
            index = start + 1
            continue
        cursor, nested = _tag_end(text, name_start)
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
        if raw_start and not part.rstrip().endswith("/>"):
            parts, index = _raw_parts(text, index, raw_start[1].lower())
            yield from parts


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    raw_start: int
    raw_end: int
    url: str | None
    literal: bool


@dataclass(frozen=True, slots=True)
class DescriptionLine:
    """Visible text with exact offsets into its original inline markup."""

    text: str
    raw: str
    spans: tuple[_Span, ...]

    def _span(self, index: int) -> _Span:
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


def description_lines(text: str) -> list[DescriptionLine]:
    """Normalize boundaries without examining tag attributes as chapter text."""
    parser = _Lines()
    for is_tag, part in _markup_parts(text):
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
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002 - HTMLParser callback.
        self.parts.append(self.get_starttag_text() or "")
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.stack and self.stack[-1] == tag:
            self.parts.append(f"</{tag}>")
            self.stack.pop()

    def handle_data(self, data: str) -> None:
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
