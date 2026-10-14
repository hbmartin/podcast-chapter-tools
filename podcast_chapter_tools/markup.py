"""Bounded HTML preparation and line boundaries for untrusted show notes."""

import re
from array import array
from bisect import bisect_right
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from unicodedata import category

from ._boundaries import LINE_BREAK_PATTERN, is_line_break
from .recognition import _ChapterPrefix, chapter_timestamp_end

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
_DATA_EVENT = re.compile(LINE_BREAK_PATTERN + "|" + _ENTITY.pattern)
_CONTEXT_BOUNDARY = re.compile(
    LINE_BREAK_PATTERN + "|"
    r"&#(?:[0-9]{1,10}|[xX][0-9a-fA-F]{1,8});?|&NewLine;"
)
_LITERAL = 0
_DECODE = 1
_BOUNDARY = 2
_HTML_SPACE = "\t\n\f\r "
_LINE_SPACE = "\t\f "
_INVALID_VALUE_START = "<=>`"
_TAG_NAME = re.compile(r"</?([A-Za-z][^\t\n\f\r /><'\"\x00]*)")
_RAW_START = re.compile(r"<(script|style)(?=[\t\n\f\r />])", re.IGNORECASE | re.ASCII)
_RAW_END = {
    tag: re.compile(rf"</{tag}(?=[\t\n\f\r />])", re.IGNORECASE | re.ASCII)
    for tag in ("script", "style")
}


class _GrammarProbe(HTMLParser):
    def __init__(self) -> None:
        """Observe bounded grammar examples through public parser callbacks."""
        super().__init__()
        self.boundary = -1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002 - HTMLParser callback.
        """Capture the recognized opening text without private parser state."""
        self.boundary = len(self.get_starttag_text() or "")


def _parser_boundary(text: str) -> int:
    """Probe the installed parser once with a bounded attribute example."""
    parser = _GrammarProbe()
    parser.feed(text)
    parser.close()
    return parser.boundary


_EQUALS_PROBE = '<b x=="a>b">'
_SPACE_PROBE = '<b x=\v"a>b">'
_REPEATED_EQUALS = _parser_boundary(_EQUALS_PROBE) == len(_EQUALS_PROBE)
_UNICODE_ATTRIBUTE_SPACE = _parser_boundary(_SPACE_PROBE) == len(_SPACE_PROBE)
_ATTRIBUTE_SPACE = r"\s" if _UNICODE_ATTRIBUTE_SPACE else r"[\t\n\f\r ]"
_ATTRIBUTE_PADDING = r"[^\S\r\n]" if _UNICODE_ATTRIBUTE_SPACE else r"[\t\f ]"
_ATTRIBUTE_FIRST = r"[^\s/>]" if _UNICODE_ATTRIBUTE_SPACE else r"[^\t\n\f\r />]"
_ATTRIBUTE_TAIL = r"[^\s/=>]*" if _UNICODE_ATTRIBUTE_SPACE else r"[^\t\n\f\r /=>]*"
_ATTRIBUTE_NAMES = tuple(
    re.compile(f"(?:{space}|/)*{_ATTRIBUTE_FIRST}{_ATTRIBUTE_TAIL}{space}*")
    for space in (_ATTRIBUTE_SPACE, _ATTRIBUTE_PADDING)
)
_ATTRIBUTE_WHITESPACE = tuple(
    re.compile(space + "+") for space in (_ATTRIBUTE_SPACE, _ATTRIBUTE_PADDING)
)
_ATTRIBUTE_SKIP = tuple(
    re.compile(f"(?:{space}|/)+") for space in (_ATTRIBUTE_SPACE, _ATTRIBUTE_PADDING)
)
_BARE_ATTRIBUTE = re.compile(
    r"[^\s>]+" if _UNICODE_ATTRIBUTE_SPACE else r"[^\t\n\f\r >]+"
)
_EVIDENCE_NAMES = re.compile(
    r"[^\s><='\"]+" if _UNICODE_ATTRIBUTE_SPACE else r"[^\t\n\f\r ><='\"]+"
)
_VALUE_BREAK = re.compile(LINE_BREAK_PATTERN)
_ASSIGNMENT = re.compile(r"=+")
_ATTRIBUTE_PREFIX = _HTML_SPACE + "/'\""
_NAME, _AFTER_NAME, _VALUE, _BARE, _QUOTED = range(5)
_NAME_STATES = frozenset({_NAME, _AFTER_NAME})


def _line_padding_end(text: str, cursor: int) -> int:
    """Skip ASCII HTML padding without crossing a physical line boundary."""
    while cursor < len(text) and text[cursor] in _LINE_SPACE:
        cursor += 1
    return cursor


def _attribute_padding_end(
    text: str, cursor: int, *, recover_chapters: bool = False
) -> int:
    """Share runtime whitespace ranges, leaving recovery newlines to the caller."""
    if cursor >= len(text):
        return cursor
    char = text[cursor]
    if (
        char not in _HTML_SPACE and not (_UNICODE_ATTRIBUTE_SPACE and char.isspace())
    ) or (recover_chapters and char in "\r\n"):
        return cursor
    match = _ATTRIBUTE_WHITESPACE[recover_chapters].match(text, cursor)
    return match.end() if match is not None else cursor


def _assignment_end(text: str, cursor: int) -> int:
    """Consume the installed parser's single or repeated assignment marker."""
    match = _ASSIGNMENT.match(text, cursor) if _REPEATED_EQUALS else None
    return match.end() if match is not None else cursor + 1


def _quote_end(text: str, cursor: int, missing_quotes: set[str] | None = None) -> int:
    """Share quoted-value boundaries and failed searches within a tag scan."""
    quote = text[cursor]
    if missing_quotes is not None and quote in missing_quotes:
        return -1
    closing = text.find(quote, cursor + 1)
    if closing < 0 and missing_quotes is not None:
        missing_quotes.add(quote)
    return closing


def _plain_name(name: str) -> bool:
    """Validate the Unicode identifier shared by framework recovery forms."""
    return (
        bool(name)
        and (name[0].isalnum() or name[0] in "_:")
        and all(
            char.isalnum() or category(char).startswith("M") or char in "_:.-"
            for char in name
        )
    )


def _attribute_name(name: str) -> bool:
    """Accept conservative identifier and framework forms as recovery evidence."""
    if not name or "/" in name or "?" in name or "@" in name[1:]:
        return False
    if "|" in name:
        base, *modifiers = name.split("|")
        return _attribute_name(base) and all(_plain_name(part) for part in modifiers)
    if name[0] in "@#*.":
        name = name[1:]
    elif name.startswith("[(") and name.endswith(")]"):
        name = name[2:-2]
    elif name[0] in "[(":
        return name[-1:] == ("]" if name[0] == "[" else ")") and _plain_name(name[1:-1])
    elif ":[" in name and name.endswith("]"):
        namespace, inner = name.split(":[", 1)
        return _plain_name(namespace) and _plain_name(inner[:-1])
    return _plain_name(name)


def _has_attribute_assignment(
    text: str, cursor: int, missing_quotes: set[str] | None = None
) -> bool:
    """Read whole attribute tokens after an already recognized timestamp."""
    if text[cursor : cursor + 1] in {")", "]"}:
        cursor += 1
    while cursor < len(text) and text[cursor] not in "\r\n>":
        padded = _attribute_padding_end(text, cursor, recover_chapters=True)
        match = _EVIDENCE_NAMES.match(text, padded)
        if match is None or _VALUE_BREAK.search(text, cursor, padded) is not None:
            return False
        cursor = padded
        name = match[0]
        if not _attribute_name(name):
            return False
        cursor = match.end()
        assignment = _attribute_padding_end(text, cursor)
        if text[assignment : assignment + 1] == "=":
            value = _attribute_padding_end(text, _assignment_end(text, assignment))
            crossed = _VALUE_BREAK.search(text, cursor, value) is not None
            if text[value : value + 1] in {"'", '"'}:
                return not crossed or _quote_end(text, value, missing_quotes) >= 0
            return (
                not crossed
                and _plain_name(name)
                and value < len(text)
                and text[value] not in _INVALID_VALUE_START
            )
        if _VALUE_BREAK.search(text, cursor, assignment) is not None:
            # Padding may connect this name to '=', never to another line's token.
            return False
        cursor = assignment
    return False


def _recover_line(
    text: str, index: int, missing_quotes: set[str] | None = None
) -> bool:
    """Find a recovery alternative; the caller decides chapter precedence."""
    end = chapter_timestamp_end(text, index)
    if end is None:
        return False
    padded = _line_padding_end(text, index)
    leading = text[padded : padded + 1] == ">"
    if leading:
        return True
    return not _has_attribute_assignment(text, end, missing_quotes)


def _tag_end(  # noqa: C901, PLR0912, PLR0915 - Attribute fallback and recovery share one bounded scan.
    text: str,
    cursor: int,
    *,
    recover_chapters: bool = False,
) -> tuple[int, bool]:
    """Scan to a tag end or recovery boundary while tracking quoted text."""
    state = _NAME
    nested = False
    length = len(text)
    # Preserve historically accepted truthy inputs despite the bool annotation.
    recover_chapters = bool(recover_chapters)  # pyrefly: ignore[unnecessary-type-conversion]
    names = _ATTRIBUTE_NAMES[recover_chapters]
    padding = _ATTRIBUTE_SKIP[recover_chapters]
    missing_quotes: set[str] = set()
    fallback: int | None = None
    fallback_state = _NAME
    while cursor < length:
        char = text[cursor]
        if state == _QUOTED:
            closing = _quote_end(text, cursor, missing_quotes)
            if closing < 0:
                if fallback is None:
                    return length, nested
                cursor, fallback, state = fallback, None, fallback_state
            else:
                cursor, state = closing + 1, _NAME
            continue
        if char == ">":
            return cursor, nested
        if recover_chapters and char in "\r\n":
            if _recover_line(text, cursor + 1, missing_quotes):
                return cursor, nested
            if state == _VALUE:
                fallback = cursor + 1
                fallback_state = _NAME
            cursor += 1
            continue
        if state in _NAME_STATES:
            if state == _NAME:
                match = names.match(text, cursor)
                if match is None:
                    skip = padding.match(text, cursor)
                    cursor = skip.end() if skip is not None else cursor + 1
                    continue
                end = match.end()
                nested = nested or text.find("<", cursor, end) >= 0
                cursor = end
            else:
                padded = _attribute_padding_end(
                    text, cursor, recover_chapters=recover_chapters
                )
                if padded != cursor:
                    cursor = padded
                    continue
                if char != "=":
                    state = _NAME
                    continue
            if cursor < length and text[cursor] == "=":
                preceding = text[cursor - 1]
                fallback = (
                    cursor
                    if preceding in _ATTRIBUTE_PREFIX
                    or (_UNICODE_ATTRIBUTE_SPACE and preceding.isspace())
                    else None
                )
                assignment = cursor
                cursor = _assignment_end(text, cursor)
                fallback_state = _NAME
                if cursor - assignment > 1:
                    # Legacy =+ can leave its final equals sign as a bare value
                    # when the preferred quoted value is incomplete.
                    fallback, fallback_state = cursor - 1, _BARE
                state = _VALUE
            elif recover_chapters and cursor < length and text[cursor] in "\r\n":
                state = _AFTER_NAME
        elif state == _VALUE:
            padded = _attribute_padding_end(
                text, cursor, recover_chapters=recover_chapters
            )
            if padded != cursor:
                cursor = padded
                # An incomplete quoted branch can instead leave an empty value
                # before this padding and read the quote as a boolean name.
                fallback = cursor
                fallback_state = _NAME
            else:
                state = _QUOTED if char in "'\"" else _BARE
        else:
            match = _BARE_ATTRIBUTE.match(text, cursor)
            if match is not None:
                end = match.end()
                nested = nested or text.find("<", cursor, end) >= 0
                cursor = end
            state = _NAME
    return cursor, nested


def _tag_boundary(
    text: str, start: int, *, recover_chapters: bool = False
) -> tuple[re.Match[str] | None, int, bool]:
    """Share lexical boundaries, including malformed tag-name delimiters."""
    match = _TAG_NAME.match(text, start)
    if match is None:
        return None, start, True
    delimiter = text[match.end() : match.end() + 1]
    if delimiter == ">":
        return match, match.end(), False
    if delimiter in {"'", '"'}:
        return match, match.end(), True
    if delimiter == "\x00":
        return match, match.end() + 1, True
    end, nested = _tag_end(text, match.end(), recover_chapters=recover_chapters)
    return match, end, nested


def _comment_end(text: str, start: int) -> int:
    """Find a complete comment or retain its entire unfinished remainder."""
    closing = text.find("-->", start + 4)
    return closing + 2 if closing >= 0 else len(text)


class _TagShape(HTMLParser):
    def __init__(self) -> None:
        """Reuse a parser for genuine self-closing markers and raw-tag openings."""
        super().__init__(convert_charrefs=False)
        self.self_closing = False

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002 - HTMLParser callback.
        """Distinguish slash markers from slash-valued unquoted attributes."""
        self.self_closing = True

    def is_self_closing(self, part: str) -> bool:
        """Classify one complete tag with fresh state in the reused parser."""
        self.reset()
        self.self_closing = False
        self.feed(part)
        return self.self_closing


@dataclass(frozen=True, slots=True, kw_only=True)
class _TagToken:
    """A cached source boundary and optional chapter recovery alternative."""

    start: int
    end: int
    name: str = ""
    closing: bool = False
    complete: bool = False
    self_closing: bool = False
    cut: int | None = None
    formatted: bool = False
    multiline: bool = False
    comment: bool = False
    balanced: bool = False

    @property
    def following(self) -> int:
        """Return the next source position for an unchanged lexical interpretation."""
        return self.end + 1 if self.complete else max(self.end, self.start + 1)

    @property
    def before(self) -> bool:
        """Lexical records do not establish contextual leading boundaries."""
        return False

    @property
    def after(self) -> bool:
        """Lexical records do not establish contextual trailing boundaries."""
        return False


def _terminator(text: str, newline: int) -> int | None:
    """Find a formatted > or /> introducing a timestamp outside attributes."""
    cursor = newline + 1
    if text[newline : newline + 2] == "\r\n":
        cursor += 1
    cursor = _line_padding_end(text, cursor)
    if text[cursor : cursor + 2] == "/>":
        cursor += 1
    if text[cursor : cursor + 1] != ">":
        return None
    return cursor if chapter_timestamp_end(text, cursor) is not None else None


def _has_newline(text: str, start: int, end: int) -> bool:
    """Check a source range without allocating a potentially large substring."""
    return text.find("\n", start, end) >= 0 or text.find("\r", start, end) >= 0


_TOKEN_CHUNK_SIZE = 4096
_OFFSET32_MAX = 2**32 - 1
_CLOSING = 1
_COMPLETE = 2
_SELF_CLOSING = 4
_FORMATTED = 8
_MULTILINE = 16
_COMMENT = 32
_BALANCED = 64


class _TokenChunk:
    def __init__(self, width: str) -> None:
        """Pack one releasable block with locally interned tag names."""
        self.starts = array(width)
        self.ends = array(width)
        self.names = array(width)
        self.flags = array("B")
        self.symbols: list[str] = []
        self.identifiers: dict[str, int] = {}
        self.cuts: dict[int, int] = {}

    def append(self, token: _TagToken) -> None:
        """Retain numeric boundaries instead of token objects and boxed offsets."""
        identifier = self.identifiers.get(token.name)
        if identifier is None:
            identifier = len(self.symbols)
            self.symbols.append(token.name)
            self.identifiers[token.name] = identifier
        if token.cut is not None:
            self.cuts[len(self.starts)] = token.cut
        self.starts.append(token.start)
        self.ends.append(token.end)
        self.names.append(identifier)
        self.flags.append(
            token.closing * _CLOSING
            | token.complete * _COMPLETE
            | token.self_closing * _SELF_CLOSING
            | token.formatted * _FORMATTED
            | token.multiline * _MULTILINE
            | token.comment * _COMMENT
            | token.balanced * _BALANCED
        )

    def token(self, offset: int) -> _TagToken:
        """Materialize only the boundary currently consumed by normal processing."""
        flags = self.flags[offset]
        return _TagToken(
            start=self.starts[offset],
            end=self.ends[offset],
            name=self.symbols[self.names[offset]],
            closing=bool(flags & _CLOSING),
            complete=bool(flags & _COMPLETE),
            self_closing=bool(flags & _SELF_CLOSING),
            cut=self.cuts.get(offset),
            formatted=bool(flags & _FORMATTED),
            multiline=bool(flags & _MULTILINE),
            comment=bool(flags & _COMMENT),
            balanced=bool(flags & _BALANCED),
        )


class _TokenStore:
    def __init__(self, size: int) -> None:
        """Keep a monotonic consumer cursor over compact, releasable blocks."""
        self.width = "I" if size <= _OFFSET32_MAX else "Q"
        self.blocks: dict[int, _TokenChunk] = {}
        self.length = 0
        self.read = 0

    def append(self, token: _TagToken) -> int:
        """Append a discovered boundary and return its balancing-stack index."""
        index = self.length
        number = index // _TOKEN_CHUNK_SIZE
        block = self.blocks.get(number)
        if block is None:
            block = self.blocks[number] = _TokenChunk(self.width)
        block.append(token)
        self.length += 1
        return index

    def _location(
        self, index: int
    ) -> tuple[_TokenChunk, int]:  # garuff: ignore[GAC005] - Record location.
        """Resolve a record without allocating or retaining a per-tag object."""
        number, offset = divmod(index, _TOKEN_CHUNK_SIZE)
        return self.blocks[number], offset

    def mark_balanced(self, index: int) -> None:
        """Record matching evidence in the opening record's packed flags."""
        if index < self.read:
            return
        block, offset = self._location(index)
        block.flags[offset] |= _BALANCED

    def _advance(self) -> None:
        """Release alternatives and complete chunks as their records are consumed."""
        number, offset = divmod(self.read, _TOKEN_CHUNK_SIZE)
        self.blocks[number].cuts.pop(offset, None)
        self.read += 1
        if self.read % _TOKEN_CHUNK_SIZE == 0:
            del self.blocks[number]

    def discard_before(self, start: int) -> None:
        """Explicitly release records passed by normal processing."""
        while self.read < self.length:
            block, offset = self._location(self.read)
            if block.starts[offset] >= start:
                return
            self._advance()

    def consume(self, start: int, *, raw: str | None = None) -> _TagToken | None:
        """Select a packed record before materializing and consuming it once."""
        self.discard_before(start)
        if self.read < self.length:
            block, offset = self._location(self.read)
            accepted = (
                block.starts[offset] == start
                if raw is None
                else bool(block.flags[offset] & _CLOSING)
                and block.symbols[block.names[offset]] == raw
            )
            if not accepted:
                return None
            token = block.token(offset)
            self._advance()
            return token
        return None


class _TagCache:
    def __init__(self, text: str, *, recover_chapters: bool) -> None:
        """Keep a forward-only lookahead frontier and reusable tag boundaries."""
        self.text = text
        # Cache flags must be booleans even for historical truthy/falsy inputs.
        self.recover = bool(recover_chapters)  # pyrefly: ignore[unnecessary-type-conversion]
        self.tokens = _TokenStore(len(text))
        self.openings: dict[str, array] = {}
        self.cursor = 0
        self.raw: str | None = None
        self.shape: _TagShape | None = None
        self._initial: _TagToken | None = None
        self.context: _RecoveryContext | None = None
        self.raw_absent: dict[str, int] = {}

    def token(self, start: int) -> _TagToken:
        """Consume a discovered boundary or scan one new candidate exactly once."""
        cached = self.tokens.consume(start)
        return cached if cached is not None else self._scan(start)

    def _scan(self, start: int) -> _TagToken:
        """Scan a quote-aware candidate without interpreting formatter timestamps."""
        text = self.text
        if text.startswith("<!--", start):
            end = _comment_end(text, start)
            return _TagToken(
                start=start,
                end=end,
                complete=end < len(text),
                comment=True,
                multiline=self.recover and _has_newline(text, start, end),
            )
        match, end, nested = _tag_boundary(text, start, recover_chapters=self.recover)
        if match is None:
            return _TagToken(start=start, end=start)
        cut = end if end < len(text) and text[end] in "\r\n" else None
        formatted = None
        multiline = self.recover and (cut is not None or _has_newline(text, start, end))
        if self.recover:
            if cut is not None:
                formatted = _terminator(text, cut)
            elif multiline and end < len(text):
                newline = max(
                    text.rfind("\r", start, end), text.rfind("\n", start, end)
                )
                if newline >= start:
                    candidate = _terminator(text, newline)
                    # Only the scanned, unquoted terminator can complete this tag.
                    formatted = candidate if candidate == end else None
        if formatted is not None and not nested:
            end = formatted
        complete = end < len(text) and text[end] == ">" and not nested
        self_closing = False
        if complete and text[end - 1 : end + 1] == "/>":
            self.shape = self.shape or _TagShape()
            self_closing = self.shape.is_self_closing(text[start : end + 1])
        return _TagToken(
            start=start,
            end=end,
            name=match[1].lower(),
            closing=text[start + 1] == "/",
            complete=complete,
            self_closing=self_closing,
            cut=cut,
            formatted=formatted is not None and complete,
            multiline=multiline,
        )

    def raw_closing(self, start: int, tag: str) -> _TagToken | None:
        """Reuse a raw-block search without examining its comparisons or quotes."""
        cached = self.tokens.consume(start, raw=tag)
        return cached if cached is not None else self._find_raw_closing(start, tag)

    def _find_raw_closing(self, start: int, tag: str) -> _TagToken | None:
        """Scan one raw region at the forward lookahead frontier."""
        if start >= self.raw_absent.get(tag, len(self.text) + 1):
            return None
        match = _RAW_END[tag].search(self.text, start)
        if match is None:
            self.raw_absent[tag] = start
            return None
        return self._scan(match.start())

    def _next(
        self,
    ) -> (
        tuple[int, _TagToken, bool, bool] | None
    ):  # garuff: ignore[GAC005] - Scan result.
        """Advance the lookahead frontier past comments and suppressed raw text."""
        raw_region = self.raw
        if raw_region is not None:
            token = self._find_raw_closing(self.cursor, raw_region)
            self.raw = None
            if token is None:
                self.cursor = len(self.text)
                return None
        else:
            start = self.text.find("<", self.cursor)
            if start < 0:
                self.cursor = len(self.text)
                return None
            token = self._initial if self._initial is not None else self._scan(start)
            self._initial = None
        context = self.context
        if context is not None and raw_region is None:
            context.data(self.text, self.cursor, token.start)
        event = _recovery_event(
            token,
            context.visible if context is not None else None,
            context.source if context is not None else None,
            protected=token.self_closing or token.name in _VOID,
            raw_closing=raw_region is not None and token.end < len(self.text),
        )
        provisional = bool(
            context is not None
            and token.complete
            and token.formatted
            and not token.closing
            and token.name not in _RAW_END
            and (context.visible.chapter or context.visible.state == "leading")
        )
        if context is not None:
            context.consume(self.text, token, event)
        position = self.tokens.append(token)
        self.cursor = event.following
        if event.complete and not token.closing and not token.self_closing:
            raw = _RAW_START.match(self.text, token.start)
            if raw is not None:
                self.raw = raw[1].lower()
        return position, token, event.complete, provisional

    def _push(self, position: int, token: _TagToken) -> None:
        """Retain source offsets independently of consumed cache chunks."""
        locations = self.openings.get(token.name)
        if locations is None:
            locations = array(self.tokens.width)
            self.openings[token.name] = locations
        locations.append(token.start)
        locations.append(position)

    def _matching(self, name: str) -> int | None:
        """Pair the nearest same-name opening without destroying other candidates."""
        locations = self.openings.get(name)
        if locations is None:
            return None
        position = locations.pop()
        start = locations.pop()
        self.tokens.mark_balanced(position)
        if not locations:
            del self.openings[name]
        return start

    def _begin_lookahead(
        self,
        opening: _TagToken,
        visible: _ChapterPrefix | None,
        source: "_SourcePrefix | None",
    ) -> None:
        """Snapshot the current context only when extending a new frontier."""
        if self.cursor <= opening.start:
            self.cursor = opening.start
            self._initial = opening
            if self.recover and (visible is not None or source is not None):
                self.context = _RecoveryContext(visible, source)
            else:
                self.context = None

    def balanced(
        self,
        opening: _TagToken,
        *,
        visible: _ChapterPrefix | None,
        source: "_SourcePrefix | None",
    ) -> bool:
        """Look ahead only as far as needed, retaining nested matching results."""
        if not opening.complete:
            return False
        if opening.self_closing or opening.name in _VOID or opening.balanced:
            return True
        self._begin_lookahead(opening, visible, source)
        while (record := self._next()) is not None:
            position, token, interpreted_complete, provisional = record
            if token.comment or not (interpreted_complete or provisional):
                continue
            if token.closing:
                matched = self._matching(token.name)
                if matched == opening.start:
                    return True
            elif not token.self_closing and token.name not in _VOID:
                self._push(position, token)
        self.openings.clear()
        return False


class _SourcePrefix:
    def __init__(self) -> None:
        """Track physical prefixes independently of visible HTML line boundaries."""
        self.prefix = _ChapterPrefix()

    def tag(self, token: _TagToken) -> None:
        """Ignore attribute lines while retaining a formatted terminator's prefix."""
        if token.multiline:
            self.prefix.reset()
            self.prefix.feed(">" if token.formatted else "<")
        else:
            self.prefix.feed("<")


@dataclass(frozen=True, slots=True, kw_only=True)
class _RecoveryEvent:
    """Contextual interpretation that never replaces lexical cache records."""

    end: int
    following: int
    complete: bool
    before: bool = False
    after: bool = False


def _recovery_event(
    token: _TagToken,
    visible: _ChapterPrefix | None,
    source: _SourcePrefix | None,
    *,
    protected: bool,
    raw_closing: bool = False,
) -> _TagToken | _RecoveryEvent:
    """Resolve literal recovery and formatter boundaries for both consumers."""
    if token.complete and not token.formatted:
        return token
    chapter = bool(
        (visible is not None and visible.chapter)
        or (source is not None and source.prefix.chapter)
    )
    boundary = visible is not None and (visible.chapter or visible.state == "leading")
    complete = token.complete
    before = False
    if raw_closing:
        complete = True
    elif complete and token.formatted and not token.closing:
        if token.name in _RAW_END:
            complete = not (chapter and token.cut is not None)
        elif boundary and protected:
            before = True
        elif chapter and token.cut is not None:
            complete = False
    end = token.end if complete or token.cut is None else token.cut
    following = (
        end
        if raw_closing and token.cut == end
        else end + 1
        if complete
        else max(end, token.start + 1)
    )
    return _RecoveryEvent(
        end=end,
        following=following,
        complete=complete,
        before=before,
        after=bool(
            complete
            and token.closing
            and token.formatted
            and visible is not None
            and visible.chapter
        ),
    )


def _data_events(text: str, start: int, end: int) -> Iterator[tuple[int, int, int]]:
    """Share literal ranges and bounded entity/line events without slicing runs."""
    cursor = start
    for match in _DATA_EVENT.finditer(text, start, end):
        if cursor < match.start():
            yield cursor, match.start(), _LITERAL
        if text[match.start()] == "&":
            yield match.start(), match.end(), _DECODE
        else:
            yield match.start(), match.end(), _BOUNDARY
        cursor = match.end()
    if cursor < end:
        yield cursor, end, _LITERAL


class _RecoveryContext:
    def __init__(
        self, visible: _ChapterPrefix | None, source: _SourcePrefix | None
    ) -> None:
        """Retain only incremental physical and visible prefix state."""
        self.visible = _ChapterPrefix()
        self.source = _SourcePrefix()
        if visible is not None:
            vars(self.visible).update(vars(visible))
        if source is not None:
            vars(self.source.prefix).update(vars(source.prefix))

    def boundary(self) -> None:
        """Reset both prefix views at the shared visible boundary."""
        self.visible.reset()
        self.source.prefix.reset()

    def _visible_data(self, text: str, start: int, end: int) -> None:
        """Decode entities only until the visible prefix is decided."""
        if self.visible.state == "done":
            return
        if start < end and text[start] != "&":
            self.visible.feed(text, start, start + 1)
            start += 1
        while start < end and self.visible.state != "done":
            entity_start = text.find("&", start, end)
            following = end if entity_start < 0 else entity_start
            self.visible.feed(text, start, following)
            if self.visible.state == "done" or entity_start < 0:
                return
            entity = _ENTITY.match(text, entity_start, end)
            if entity is None:
                self.visible.feed("&")
                start = entity_start + 1
            else:
                self.visible.feed(unescape(entity[0]))
                start = entity.end()

    def data(self, text: str, start: int, end: int) -> None:
        """Inspect only undecided prefixes and potential boundary events."""
        if start == end:
            return
        if end - start <= 2 and is_line_break(text[start:end]):  # noqa: PLR2004 - Avoid slicing a long range.
            self.boundary()
            return
        cursor = start
        for match in _CONTEXT_BOUNDARY.finditer(text, start, end):
            self.source.prefix.feed(text, cursor, match.start())
            self._visible_data(text, cursor, match.start())
            if text[match.start()] == "&":
                entity = unescape(match[0])
                self.source.prefix.feed(match[0])
                if is_line_break(entity):
                    self.boundary()
                else:
                    self.visible.feed(entity)
            else:
                self.boundary()
            cursor = match.end()
        self.source.prefix.feed(text, cursor, end)
        self._visible_data(text, cursor, end)

    def consume(
        self, text: str, token: _TagToken, event: _TagToken | _RecoveryEvent
    ) -> None:
        """Apply the shared interpretation without HTMLParser or text buffers."""
        if not event.complete:
            self.data(text, token.start, event.following)
            return
        if event.before:
            self.boundary()
        if token.multiline or self.source.prefix.state != "done":
            self.source.tag(token)
        if token.name in _BLOCKS or event.after:
            self.boundary()


def _supported_link(attrs: list[tuple[str, str | None]]) -> str | None:
    """Return the supported enclosing HTTP(S) href without changing URL policy."""
    href = dict(attrs).get("href")
    return href if href and href.startswith(("http://", "https://")) else None


def _generic_raw_parts(
    text: str, index: int, tag: str
) -> tuple[list[tuple[bool, str]], int]:  # garuff: ignore[GAC005] - Stream result.
    """Suppress raw content without recovery objects or balancing lookahead."""
    match = _RAW_END[tag].search(text, index)
    if match is None:
        return [(False, text[index:])], len(text)
    end, _ = _tag_end(text, match.end())
    return _closing_parts(text, index, match.start(), end, tag=tag)


def _closing_parts(
    text: str, index: int, start: int, end: int, *, tag: str
) -> tuple[list[tuple[bool, str]], int]:  # garuff: ignore[GAC005] - Raw scan result.
    """Share suppression and scanned-terminator consumption across both paths."""
    if end == len(text):
        return [(False, text[index:])], end
    following = end + (text[end] == ">")
    return [(False, text[index:start]), (True, _closing_tag(tag))], following


def _closing_tag(name: str) -> str:
    """Dispatch complete closings without source-length or attribute assumptions."""
    return f"</{name}>"


def _generic_markup_parts(text: str) -> Iterator[tuple[bool, str]]:
    """Stream ordinary markup without allocating recovery tokens or caches."""
    index = 0
    shape = None
    while index < len(text):
        start = text.find("<", index)
        yield False, text[index:] if start < 0 else text[index:start]
        if start < 0:
            return
        if text.startswith("<!--", start):
            end = _comment_end(text, start)
            if end == len(text):
                yield False, text[start:]
                return
            index = end + 1
            continue
        match, end, nested = _tag_boundary(text, start)
        if nested or end == len(text):
            yield False, text[start:end] if end > start else "<"
            index = end if end > start else start + 1
            continue
        part = text[start : end + 1]
        if text[start + 1] == "/" and match is not None:
            part = _closing_tag(match[1].lower())
        yield True, part
        index = end + 1
        raw = _RAW_START.match(part)
        if raw is None:
            continue
        if part.endswith("/>"):
            shape = shape or _TagShape()
            if shape.is_self_closing(part):
                continue
        parts, index = _generic_raw_parts(text, index, raw[1].lower())
        yield from parts


def _raw_parts(
    cache: _TagCache,
    index: int,
    tag: str,
    *,
    visible: _ChapterPrefix | None,
    source: _SourcePrefix | None,
) -> tuple[
    list[tuple[bool, str]], int
]:  # garuff: ignore[GAC005] - Scanner events and following offset.
    """Suppress a raw region while retaining complete and recovered closing tags."""
    closing = cache.raw_closing(index, tag)
    if closing is None or closing.end == len(cache.text):
        return [(False, cache.text[index:])], len(cache.text)
    parts, following = _closing_parts(
        cache.text, index, closing.start, closing.end, tag=tag
    )
    if source is not None:
        source.tag(closing)
    if closing.formatted and visible is not None and visible.chapter:
        parts.append((False, "\n"))
    return parts, following


def _markup_parts(  # noqa: C901 - Recovery, complete tags, and suppressed raw blocks share one scan.
    text: str,
    *,
    recover_chapters: bool = False,
    line_context: Callable[[], _ChapterPrefix | None] | None = None,
    source_context: _SourcePrefix | None = None,
) -> Iterator[tuple[bool, str]]:
    """Yield complete tags or literal data, reusing bounded lookahead regions."""
    if not recover_chapters:
        yield from _generic_markup_parts(text)
        return
    index = 0
    cache = _TagCache(text, recover_chapters=recover_chapters)
    if source_context is None or line_context is None:
        msg = "Chapter recovery requires parser-owned source and visible context"
        raise ValueError(msg)
    source = source_context
    while index < len(text):
        start = text.find("<", index)
        data = text[index:] if start < 0 else text[index:start]
        yield False, data
        if start < 0:
            break
        visible = line_context()
        token = cache.token(start)
        protected = False
        if (
            token.complete
            and token.formatted
            and not token.closing
            and token.name not in _RAW_END
        ):
            boundary = visible is not None and (
                visible.chapter or visible.state == "leading"
            )
            if boundary:
                protected = cache.balanced(token, visible=visible, source=source)
        event = _recovery_event(token, visible, source, protected=protected)
        if event.before:
            yield False, "\n"
        if not event.complete:
            fragment = text[start : event.end] if event.end > start else "<"
            yield False, fragment
            index = event.following
            continue
        part = text[start : token.end + 1]
        source.tag(token)
        if token.comment:
            index = token.end + 1
            continue
        if token.closing:
            part = _closing_tag(token.name)
        yield True, part
        index = token.end + 1
        if event.after:
            yield False, "\n"
        raw = (
            _RAW_START.match(part)
            if not token.closing and not token.self_closing
            else None
        )
        if raw is not None:
            parts, index = _raw_parts(
                cache, index, raw[1].lower(), visible=visible, source=source
            )
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
    def __init__(
        self, *, recover_chapters: bool = False, collect_spans: bool = True
    ) -> None:
        """Initialize visible line buffers, compact spans, and link context."""
        super().__init__(convert_charrefs=False)
        self._prefix = _ChapterPrefix() if recover_chapters else None
        self._source = _SourcePrefix() if recover_chapters else None
        self._collect_spans = collect_spans
        self.lines: list[DescriptionLine] = []
        self._raw: list[str] = []
        self._text: list[str] = []
        self._spans: list[_Span] = []
        self._anchors: list[str | None] = []
        self._length = 0
        self._visible_length = 0
        self._hidden: str | None = None

    def line_context(self) -> _ChapterPrefix | None:
        """Expose the one incremental visible-prefix state to tag recovery."""
        return self._prefix

    def boundary(self) -> None:
        """Flush the current visible line and reset its source buffers."""
        if self._prefix is not None:
            self._prefix.reset()
        if self._source is not None:
            self._source.prefix.reset()
        if not self._collect_spans:
            return
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
        if is_line_break(visible):
            self.boundary()
            return
        if self._prefix is not None:
            self._prefix.feed(visible)
        if not self._collect_spans:
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
        if is_line_break(data):
            self.boundary()
            return
        for start, end, kind in _data_events(data, 0, len(data)):
            if self._source is not None:
                self._source.prefix.feed(data, start, end)
            if kind == _BOUNDARY:
                self.boundary()
            else:
                raw = data[start:end]
                self._append(raw, unescape(raw) if kind == _DECODE else raw)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track block boundaries, suppressed content, and inline links."""
        if self._hidden:
            return
        if tag in {"script", "style"}:
            self._hidden = tag
        elif tag in _BLOCKS:
            self.boundary()
        elif self._collect_spans:
            raw = self.get_starttag_text() or ""
            self._raw.append(raw)
            self._length += len(raw)
            if tag == "a":
                self._anchors.append(_supported_link(attrs))

    def handle_endtag(self, tag: str) -> None:
        """Close suppressed content or update visible markup and link context."""
        if self._hidden:
            if self._hidden == tag:
                self._hidden = None
            return
        if tag in _BLOCKS:
            self.boundary()
        elif self._collect_spans:
            raw = _closing_tag(tag)
            self._raw.append(raw)
            self._length += len(raw)
            if tag == "a" and self._anchors:
                self._anchors.pop()


def description_lines(
    text: str, *, recover_chapters: bool = False
) -> list[DescriptionLine]:
    """Normalize boundaries without examining tag attributes as chapter text."""
    parser = _Lines(recover_chapters=recover_chapters)
    for is_tag, part in _markup_parts(
        text,
        recover_chapters=recover_chapters,
        line_context=parser.line_context if recover_chapters else None,
        source_context=parser._source,  # noqa: SLF001 - Shared parser boundary events.
    ):
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
            self.parts.append(_closing_tag(tag))
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
    parser.parts.extend(_closing_tag(tag) for tag in reversed(parser.stack))
    return "".join(parser.parts)


def plain_text(text: str) -> str:
    """Remove markup and decode entities through bounded HTML preparation."""
    return " ".join(" ".join(line.text for line in description_lines(text)).split())
